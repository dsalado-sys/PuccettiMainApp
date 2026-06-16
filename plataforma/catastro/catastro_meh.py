"""Adapter HTTP del Catastro.

Reutiliza la librería pública `ESCatastroLib` (paquete PyPI, ya validada por el
módulo `frontend`). Para coordenadas y subreferencias se hace REST directo
contra el host `ovc.catastro.meh.es`, también copiando el patrón que funciona.

URLs canónicas — NUNCA usar `.meta.minhap.es` (no resuelve) ni `minhap.es`
(certificado SSL inválido).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any
from xml.etree import ElementTree as ET

import requests
from ESCatastroLib import MetaParcela, ParcelaCatastral
from ESCatastroLib.utils import listar_calles as escl_listar_calles
from ESCatastroLib.utils.exceptions import ErrorServidorCatastro

from app.contextos.localizacion.dominio import (
    ParcelaNoEncontrada,
    RateLimitCatastro,
    SinParcelaEnPunto,
    Subreferencia,
)
from app.contextos.localizacion.puertos import (
    CatastroPort,
    DetalleSubreferencia,
    ParcelaRaw,
)

log = logging.getLogger(__name__)

HOST = "https://ovc.catastro.meh.es"
CATASTRO_RCCOOR = (
    f"{HOST}/OVCServWeb/OVCWcfCallejero/COVCCoordenadas.svc/json/Consulta_RCCOOR"
)
CATASTRO_DNPRC = (
    f"{HOST}/OVCServWeb/OVCWcfCallejero/COVCCallejero.svc/json/Consulta_DNPRC"
)
URL_INSPIRE_WFS = (
    "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"
)

UA = "Puccetti/0.1"
TIMEOUT = 30.0


def _sin_tildes(s: str) -> str:
    """El Catastro devuelve 0 resultados cuando recibe nombres con tildes
    (probado: 'Córdoba'/'Córdoba' → 0 vías; 'Cordoba'/'Cordoba' → 2892).
    Normaliza eliminando diacríticos antes de cualquier llamada.
    """
    if not s:
        return ""
    desc = unicodedata.normalize("NFD", s)
    return "".join(c for c in desc if unicodedata.category(c) != "Mn")


# ── Parseo de superficies del Catastro  ──────
def _superficie_catastro(valor: Any) -> float:
    """Convierte una superficie del Catastro a float SIN redondear ni truncar.

    Los endpoints DNPRC devuelven las superficies como cadenas en formato
    español: el punto es separador de millares y la coma, separador decimal
    (p. ej. ``"1.087"`` = 1087 m², ``"1.234,56"`` = 1234.56 m²). Aplicar
    ``float()`` directamente interpretaría ``"1.087"`` como 1.087 m² (el origen
    del bug en metaparcelas con inmuebles de ≥ 1.000 m²). Normalizamos el
    formato antes de convertir y conservamos todos los decimales.

    Acepta también ``int``/``float`` ya nativos (los devuelve intactos) y
    cae a ``0.0`` ante valores vacíos o no numéricos.
    """
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor).strip()
    if not s:
        return 0.0
    # Formato español: '.' = millares, ',' = decimal.
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _superficie_construida_de_parcela(p: ParcelaCatastral) -> float | None:
    """Suma la superficie construida de las regiones (locales/elementos) de una
    parcela con parseo correcto del formato español.

    ESCatastroLib calcula ``superficie_construida`` como ``sum(float(stl))`` y
    rompe igual que ``sfc`` cuando alguna región mide ≥ 1.000 m². Recalculamos
    aquí desde ``p.regiones`` (ya cargadas, sin llamadas extra al Catastro).
    Devuelve ``None`` si la librería no expone regiones.
    """
    regiones = getattr(p, "regiones", None)
    if not regiones:
        return None
    return sum(_superficie_catastro(r.get("superficie")) for r in regiones)


# ── Rate limit  ──────────────────────────────
def _detectar_rate_limit(respuesta: requests.Response) -> None:
    """Lanza RateLimitCatastro si la respuesta indica bloqueo por límite horario.

    El Catastro lo señaliza de dos formas distintas según el endpoint:
    - HTTP 403 en endpoints REST puros.
    - XML/JSON con texto "Peticion denegada" y HTTP 200 en endpoints WCF.
    """
    if respuesta.status_code == 403:
        raise RateLimitCatastro(
            "El Catastro ha bloqueado temporalmente las peticiones desde esta IP "
            "por exceder el límite horario. Inténtalo de nuevo en ~1 hora."
        )
    txt = (respuesta.text or "")[:400].lower()
    if "limite de peticiones" in txt or "peticion denegada" in txt or "petici&#243;n denegada" in txt:
        raise RateLimitCatastro(
            "El Catastro ha bloqueado temporalmente las peticiones desde esta IP "
            "por exceder el límite horario. Inténtalo de nuevo en ~1 hora."
        )


# ── Click en mapa: RC desde coordenadas  ─────
def _rc_desde_coordenadas(lon: float, lat: float, srs: str = "EPSG:4326") -> str:
    """Devuelve la RC de la parcela que contiene exactamente el punto.

    Nombres correctos de los parámetros HTTP: ``CoorX`` / ``CoorY``.
    """
    r = requests.get(
        CATASTRO_RCCOOR,
        params={"SRS": srs, "CoorX": lon, "CoorY": lat},
        headers={"User-Agent": UA},
        timeout=TIMEOUT,
    )
    _detectar_rate_limit(r)
    r.raise_for_status()
    data = r.json().get("Consulta_RCCOORResult", {})
    control = data.get("control", {})
    if control.get("cuerr", 0) and not control.get("cucoor"):
        raise SinParcelaEnPunto(
            "El punto no está sobre ninguna parcela del Catastro. "
            "Haz click dentro de una parcela."
        )
    coords = data.get("coordenadas", {}).get("coord", [])
    if not coords:
        raise SinParcelaEnPunto(
            "El punto no está sobre ninguna parcela del Catastro. "
            "Haz click dentro de una parcela."
        )
    pc = coords[0].get("pc", {})
    rc = f"{pc.get('pc1', '')}{pc.get('pc2', '')}"
    if not rc:
        raise SinParcelaEnPunto(
            "El punto no está sobre ninguna parcela del Catastro."
        )
    return rc


# ── Subreferencias  ──────────────────────────
def _extraer_rc20(rc_dict: dict) -> str:
    return "".join(rc_dict.get(k, "") or "" for k in ("pc1", "pc2", "car", "cc1", "cc2"))


def _subref_de_item(item: dict) -> Subreferencia:
    rc20 = _extraer_rc20(item.get("rc", {}))
    dt = item.get("dt", {}) or {}
    debi = item.get("debi", {}) or {}
    loint = (
        dt.get("locs", {}).get("lous", {}).get("lourb", {}).get("loint", {})
        or {}
    )
    partes = []
    es = (loint.get("es") or "").strip()
    pt = (loint.get("pt") or "").strip()
    pu = (loint.get("pu") or "").strip()
    if es: partes.append(f"Es {es}")
    if pt: partes.append(f"Pl {pt}")
    if pu: partes.append(f"Pt {pu}")
    return Subreferencia(
        rc=rc20,
        localizacion=" · ".join(partes),
        uso=(debi.get("luso") or "").strip(),
        superficie_construida_m2=_superficie_catastro(debi.get("sfc")),
    )


def _subreferencias_por_rc14(rc14: str) -> list[Subreferencia]:
    rc14 = (rc14 or "")[:14]
    if len(rc14) != 14:
        return []
    r = requests.get(
        CATASTRO_DNPRC,
        params={"RefCat": rc14},
        headers={"User-Agent": UA},
        timeout=TIMEOUT,
    )
    _detectar_rate_limit(r)
    r.raise_for_status()
    try:
        data = r.json().get("consulta_dnprcResult", {})
    except ValueError:
        return []
    lrcdnp = data.get("lrcdnp") or {}
    rcdnp = lrcdnp.get("rcdnp")
    if rcdnp is None:
        return []
    if isinstance(rcdnp, dict):
        rcdnp = [rcdnp]
    return [_subref_de_item(it) for it in rcdnp if _extraer_rc20(it.get("rc", {}))]


# ── Resolver parcela usando ESCatastroLib (copiado del frontend) ───────────
def _resolver_con_escatastro(rc: str | None = None, direccion: dict | None = None):
    """Devuelve (ParcelaCatastral, list[Subreferencia]).

    Si es metaparcela, devuelve la primera parcela como representante y la lista
    completa de subreferencias. Si es parcela única, subreferencias = [].
    """
    try:
        if rc:
            return ParcelaCatastral(rc=rc), []
        return ParcelaCatastral(**direccion), []
    except (ValueError, ErrorServidorCatastro) as exc:
        if "MetaParcela" not in str(exc):
            raise

    if rc:
        subref = _subreferencias_por_rc14(rc[:14])
        if not subref:
            raise ParcelaNoEncontrada("MetaParcela sin subreferencias resolubles")
        primer = ParcelaCatastral(rc=subref[0].rc)
        return primer, subref

    mp = MetaParcela(**direccion)
    if not mp.parcelas:
        raise ParcelaNoEncontrada("MetaParcela sin parcelas internas")
    primer = mp.parcelas[0]
    subref = _subreferencias_por_rc14(primer.rc[:14])
    if not subref:
        # Fallback: si DNPRC no devuelve subrefs detallados, montar a partir de mp.parcelas.
        subref = []
        for p in mp.parcelas:
            sup_p = _superficie_construida_de_parcela(p)
            if sup_p is None:
                sup_p = _superficie_catastro(getattr(p, "superficie_construida", 0))
            subref.append(Subreferencia(
                rc=p.rc,
                localizacion="",
                uso=(getattr(p, "uso", "") or "").strip(),
                superficie_construida_m2=sup_p,
            ))
    return primer, subref


def _parcela_a_raw(
    p: ParcelaCatastral,
    subreferencias: list[Subreferencia],
) -> ParcelaRaw:
    """Convierte un ParcelaCatastral de ESCatastroLib a nuestro DTO ParcelaRaw."""
    gdf = p.to_dataframe()
    if gdf.crs is None:
        gdf.set_crs(epsg=4326, inplace=True)
    if str(gdf.crs).upper() != "EPSG:4326":
        gdf = gdf.to_crs(epsg=4326)
    geom = gdf.geometry.union_all()
    if geom.geom_type == "Polygon":
        contorno = [(float(x), float(y)) for x, y in geom.exterior.coords]
    elif geom.geom_type == "MultiPolygon":
        # Tomamos el polígono mayor; las parcelas casi nunca son MultiPolygon.
        mayor = max(geom.geoms, key=lambda g: g.area)
        contorno = [(float(x), float(y)) for x, y in mayor.exterior.coords]
    else:
        contorno = []

    centro = getattr(p, "centroide", None) or {}
    lon = centro.get("longitud") or centro.get("lon") or centro.get("x")
    lat = centro.get("latitud") or centro.get("lat") or centro.get("y")
    if lon is None or lat is None:
        c = geom.centroid
        lon, lat = c.x, c.y

    direccion = " ".join(
        x for x in [getattr(p, "tipo_via", "") or "", getattr(p, "calle", "") or ""] if x
    ).strip()
    numero = getattr(p, "numero", "") or ""
    if numero:
        direccion = f"{direccion}, {numero}".strip(", ")

    # RC de la parcela = primeros 14 chars. Cuando ESCatastroLib trabajó con
    # una metaparcela, `p.rc` es el RC20 de la primera subreferencia, no el
    # RC14 de la parcela física — recortamos para tener siempre la RC14.
    rc_obj = (getattr(p, "rc", "") or "").upper().replace(" ", "")
    rc14 = rc_obj[:14] if len(rc_obj) >= 14 else rc_obj

    # Uso predominante: del objeto p si existe, si no del primer subref.
    uso = (getattr(p, "uso", "") or "").strip()
    if not uso and subreferencias:
        uso = (subreferencias[0].uso or "").strip()

    # Año de construcción: ESCatastroLib lo expone como `antiguedad` (str/int).
    anio: int | None = None
    raw_anio = getattr(p, "antiguedad", None)
    try:
        anio = int(raw_anio) if raw_anio not in (None, "") else None
    except (TypeError, ValueError):
        anio = None
    if anio is None and subreferencias:
        for s in subreferencias:
            if s.anio_construccion:
                anio = s.anio_construccion
                break

    # Superficie construida total: si es metaparcela, suma de subrefs; si es
    # parcela única, suma de sus regiones. En ambos casos con parseo correcto
    # del formato español (ESCatastroLib usaría float() directo y rompería los
    # valores de ≥ 1.000 m²).
    sup_construida: float | None = None
    if subreferencias:
        suma = sum(s.superficie_construida_m2 or 0.0 for s in subreferencias)
        sup_construida = suma if suma > 0 else None
    else:
        v = _superficie_construida_de_parcela(p)
        if v is None:
            v = _superficie_catastro(getattr(p, "superficie_construida", 0))
        sup_construida = v if v and v > 0 else None

    # Plantas sobre/bajo rasante: una llamada extra al WFS de edificios. Fallo
    # suave — no es bloqueante para el módulo.
    plantas_sup: int | None = None
    plantas_inf: int | None = None
    try:
        np = p.numero_plantas
        if isinstance(np, dict):
            ps = np.get("plantas")
            pi = np.get("sotanos")
            plantas_sup = int(ps) if isinstance(ps, (int, float)) else None
            plantas_inf = int(pi) if isinstance(pi, (int, float)) else None
    except Exception as exc:  # noqa: BLE001 — endpoint WFS opcional
        log.warning("No se pudo obtener nº plantas para %s: %s", rc14, exc)

    return ParcelaRaw(
        referencia_catastral=rc14,
        direccion=direccion,
        municipio=getattr(p, "municipio", "") or "",
        provincia=getattr(p, "provincia", "") or "",
        superficie_m2=float(getattr(p, "superficie_total", 0) or 0),
        centroide_lonlat=(float(lon), float(lat)),
        contorno_wgs84=contorno,
        subreferencias=tuple(subreferencias),
        uso_catastral=uso,
        anio_construccion=anio,
        superficie_construida_total_m2=sup_construida,
        plantas_sobre_rasante=plantas_sup,
        plantas_bajo_rasante=plantas_inf,
    )


# ── WFS INSPIRE bbox (vecinos) ─────────────────────────────────────────────
_GML_NS = {
    "gml": "http://www.opengis.net/gml/3.2",
    "gml31": "http://www.opengis.net/gml",
}


def _parsear_polygons_gml(xml_text: str) -> list[list[tuple[float, float]]]:
    contornos: list[list[tuple[float, float]]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return contornos
    candidatos: list[ET.Element] = []
    for ns_uri in _GML_NS.values():
        candidatos.extend(root.findall(f".//{{{ns_uri}}}exterior"))
    for ext in candidatos:
        poslist = None
        for ns_uri in _GML_NS.values():
            poslist = ext.find(f".//{{{ns_uri}}}posList")
            if poslist is not None:
                break
        if poslist is None or not (poslist.text or "").strip():
            continue
        valores = re.split(r"\s+", poslist.text.strip())
        try:
            pares = [
                (float(valores[i + 1]), float(valores[i]))
                for i in range(0, len(valores) - 1, 2)
            ]
        except (ValueError, IndexError):
            continue
        if pares and pares[0] != pares[-1]:
            pares.append(pares[0])
        contornos.append(pares)
    return contornos


# ── Adapter ────────────────────────────────────────────────────────────────
class CatastroMEH(CatastroPort):
    """Cliente Catastro. Para RC y dirección usa ESCatastroLib; resto REST directo."""

    def buscar_por_rc(self, rc: str) -> ParcelaRaw:
        rc_limpio = (rc or "").strip().upper().replace(" ", "")
        if not rc_limpio:
            raise ParcelaNoEncontrada("RC vacía.")
        try:
            p, subref = _resolver_con_escatastro(rc=rc_limpio)
        except RateLimitCatastro:
            raise
        except ParcelaNoEncontrada:
            raise
        except (ValueError, ErrorServidorCatastro) as exc:
            raise ParcelaNoEncontrada(f"Catastro: {exc}") from exc
        return _parcela_a_raw(p, subref)

    def buscar_por_coordenada(self, lon: float, lat: float) -> ParcelaRaw:
        rc14 = _rc_desde_coordenadas(float(lon), float(lat))
        return self.buscar_por_rc(rc14)

    def buscar_por_direccion(
        self,
        provincia: str,
        municipio: str,
        tipo_via: str,
        calle: str,
        numero: str,
    ) -> ParcelaRaw:
        # El Catastro / ESCatastroLib devuelve 0 si provincia o municipio
        # llevan tildes; las quitamos antes de llamar.
        direccion = dict(
            provincia=_sin_tildes((provincia or "").strip()),
            municipio=_sin_tildes((municipio or "").strip()),
            tipo_via=(tipo_via or "").strip(),
            calle=(calle or "").strip(),
            numero=str(numero or "").strip(),
        )
        try:
            p, subref = _resolver_con_escatastro(direccion=direccion)
        except RateLimitCatastro:
            raise
        except ParcelaNoEncontrada:
            raise
        except (ValueError, ErrorServidorCatastro) as exc:
            raise ParcelaNoEncontrada(
                f"No se encontró inmueble en {tipo_via} {calle} {numero}, {municipio} ({provincia}). {exc}"
            ) from exc
        return _parcela_a_raw(p, subref)

    def vecinos_en_bbox(
        self,
        bbox_4326: tuple[float, float, float, float],
        excluir_rc: str | None = None,
    ) -> list[list[tuple[float, float]]]:
        min_lon, min_lat, max_lon, max_lat = bbox_4326
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typenames": "cp:CadastralParcel",
            "srsname": "EPSG:4326",
            "bbox": f"{min_lat},{min_lon},{max_lat},{max_lon},EPSG:4326",
        }
        try:
            resp = requests.get(
                URL_INSPIRE_WFS,
                params=params,
                headers={"User-Agent": UA},
                timeout=TIMEOUT,
            )
            _detectar_rate_limit(resp)
            resp.raise_for_status()
        except RateLimitCatastro:
            raise
        except Exception as exc:
            log.warning("WFS bbox falló: %s", exc)
            return []
        return _parsear_polygons_gml(resp.text)

    def listar_vias(self, provincia: str, municipio: str) -> list[str]:
        """Una llamada al Catastro vía ESCatastroLib.utils.listar_calles.

        El Catastro responde 0 vías cuando los nombres llevan tildes; las quitamos.
        """
        prov = _sin_tildes((provincia or "").strip())
        mun = _sin_tildes((municipio or "").strip())
        if not prov or not mun:
            return []
        try:
            vias = escl_listar_calles(prov, mun)
        except (ValueError, ErrorServidorCatastro) as exc:
            log.warning("listar_calles falló para %s/%s: %s", prov, mun, exc)
            return []
        return [str(v).strip() for v in (vias or []) if str(v).strip()]

    def obtener_detalle_subreferencia(self, rc20: str) -> DetalleSubreferencia:
        rc_limpio = (rc20 or "").strip().upper().replace(" ", "")
        if not rc_limpio:
            return DetalleSubreferencia(None, None)
        try:
            p = ParcelaCatastral(rc=rc_limpio)
        except (ValueError, ErrorServidorCatastro):
            return DetalleSubreferencia(None, None)
        anio = getattr(p, "antiguedad", None)
        try:
            anio = int(anio) if anio else None
        except (TypeError, ValueError):
            anio = None
        coef = (
            getattr(p, "coeficiente_participacion", None)
            or getattr(p, "coeficiente", None)
        )
        try:
            coef = float(coef) if coef is not None else None
        except (TypeError, ValueError):
            coef = None
        return DetalleSubreferencia(
            coeficiente_participacion=coef,
            anio_construccion=anio,
        )
