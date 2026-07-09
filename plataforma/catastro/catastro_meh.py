"""Adapter HTTP del Catastro.

Reutiliza la librería pública `ESCatastroLib` (paquete PyPI, ya validada por el
módulo `frontend`). Para coordenadas y subreferencias se hace REST directo
contra el host `ovc.catastro.meh.es`, también copiando el patrón que funciona.

URLs canónicas — NUNCA usar `.meta.minhap.es` (no resuelve) ni `minhap.es`
(certificado SSL inválido).
"""
from __future__ import annotations

import logging
import math
import re
import socket
import unicodedata
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

import requests
from pyproj import Transformer
from shapely.geometry import Polygon
from shapely.ops import unary_union
from ESCatastroLib import MetaParcela, ParcelaCatastral
from ESCatastroLib.utils import listar_calles as escl_listar_calles
from ESCatastroLib.utils.exceptions import ErrorServidorCatastro

from app.contextos.localizacion.dominio import (
    ParcelaNoEncontrada,
    PatioCatastral,
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
# WFS de edificios (Buildings) INSPIRE. Stored query GetBuildingByParcel: huella
# del edificio de una parcela, con sus patios como anillos interiores (gml:interior).
URL_INSPIRE_WFS_BU = "https://ovc.catastro.meh.es/INSPIRE/wfsBU.aspx"

UA = "Puccetti/0.1"
TIMEOUT = 30.0
# ESCatastroLib usa `requests` internamente y NO expone un parámetro de timeout:
# acotamos a nivel de socket para que sus llamadas (ParcelaCatastral, listar_calles,
# nº de plantas, croquis) no cuelguen el worker indefinidamente. requests/urllib3
# honran el default de socket cuando no se pasa un timeout explícito.
socket.setdefaulttimeout(TIMEOUT)


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
_MSG_RATE_LIMIT = (
    "El Catastro ha bloqueado temporalmente las peticiones desde esta IP "
    "por exceder el límite horario. Inténtalo de nuevo en ~1 hora."
)


def _texto_indica_rate_limit(texto: str) -> bool:
    """True si el texto (cuerpo de respuesta o mensaje de excepción) delata un
    bloqueo por límite horario.

    Normaliza tildes y entidades HTML para no fallar ante "Petición denegada"
    con tilde real o con la entidad ``&#243;`` sin desescapar.
    """
    txt = (texto or "")[:400]
    txt = txt.replace("&#243;", "o").replace("&#xf3;", "o").replace("&#xF3;", "o")
    txt = _sin_tildes(txt).lower()
    return (
        "limite de peticiones" in txt
        or "peticion denegada" in txt
        or "limite horario" in txt
    )


def _detectar_rate_limit(respuesta: requests.Response) -> None:
    """Lanza RateLimitCatastro si la respuesta indica bloqueo por límite horario.

    El Catastro lo señaliza de dos formas distintas según el endpoint:
    - HTTP 403 en endpoints REST puros.
    - XML/JSON con texto "Peticion denegada" y HTTP 200 en endpoints WCF.
    """
    if respuesta.status_code == 403:
        raise RateLimitCatastro(_MSG_RATE_LIMIT)
    if _texto_indica_rate_limit(respuesta.text or ""):
        raise RateLimitCatastro(_MSG_RATE_LIMIT)


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
def _anio_o_none(valor: Any) -> int | None:
    """Convierte la antigüedad (``ant``) del Catastro a un año entero, o None."""
    if valor is None:
        return None
    s = str(valor).strip()
    if not s:
        return None
    try:
        return int(float(s.replace(".", "").replace(",", ".")))
    except (TypeError, ValueError):
        return None


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
    # El listado agregado (Consulta_DNPRC por RC14) ya trae la antigüedad (`ant`)
    # por inmueble cuando el Catastro la informa: la aprovechamos para que el
    # listado quede completo con UNA sola llamada y no haya que consultar cada RC20.
    return Subreferencia(
        rc=rc20,
        localizacion=" · ".join(partes),
        uso=(debi.get("luso") or "").strip(),
        superficie_construida_m2=_superficie_catastro(debi.get("sfc")),
        anio_construccion=_anio_o_none(debi.get("ant")),
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

    # Patios del edificio: anillos interiores de la huella catastral (WFS BU). Una
    # llamada extra best-effort; se persiste con la parcela y se muestra en el modo
    # Rehabilitación ("Patios del edificio"). Nunca bloquea la localización.
    res_patios = _patios_por_rc(rc14, contorno)
    if res_patios is None:
        n_patios: int | None = None
        patios_m2: tuple[float, ...] = ()
        patios_geom: tuple[PatioCatastral, ...] = ()
    else:
        patios_geom = tuple(res_patios)
        n_patios = len(patios_geom)
        patios_m2 = tuple(round(p.area_m2, 1) for p in patios_geom)

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
        n_patios=n_patios,
        patios_m2=patios_m2,
        patios_geom=patios_geom,
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


# ── Patios del edificio (WFS BU)  ────────────────────────────────────────────
# Patios ABIERTOS = patinejos/entrantes que el Catastro NO marca como `gml:interior`.
# Con la PARCELA conocida se toman como las zonas del HUECO (parcela − edificio) que:
#   1. sobreviven a una APERTURA morfológica (se descartan las franjas finas de
#      retranqueo, más estrechas que ~2·`_PATIO_APERTURA_M`), y
#   2. están muy RODEADAS por el edificio (≥ `_PATIO_FRAC_EDIF_MIN` de su perímetro
#      coincide con muros del edificio). Así un patio de luces cuenta ENTERO —aunque
#      parte cierre contra el lindero, no contra el propio edificio— pero un
#      retranqueo/jardín abierto a fachada (poco rodeado por el edificio) NO se
#      confunde con patio. (Patios reales medidos: 0.45–0.79; retranqueos ~0.25.)
# Sin parcela (fallback) se usa solo el cierre morfológico del edificio (capta menos:
# únicamente la parte del patio cerrada por muros del propio edificio).
_PATIO_ABIERTO_RADIO_M = 2.5    # radio de "boca estrecha" del entrante (fallback sin parcela)
_PATIO_APERTURA_M = 0.75        # apertura del hueco: descarta franjas más finas que ~2·este valor
_PATIO_FRAC_EDIF_MIN = 0.35     # mínimo del perímetro del hueco rodeado por el edificio para ser patio
_PATIO_AREA_MIN_M2 = 4.0        # área mínima de un patio abierto (descarta slivers)

# El WFS BU se pide en EPSG:25830 (ver `_patios_por_rc`): el anillo de cada patio
# llega en metros UTM30N. Se reproyecta a WGS84 para guardarlo en el MISMO sistema
# que el contorno de la parcela; el render lo vuelve a UTM con el huso de la parcela.
_T_BU_A_WGS84 = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)
# Inverso: el contorno de la parcela (WGS84, de ESCatastroLib) al CRS del edificio
# (EPSG:25830, del WFS BU) para restar el edificio del hueco en el mismo plano.
_T_WGS84_A_BU = Transformer.from_crs("EPSG:4326", "EPSG:25830", always_xy=True)


@dataclass(frozen=True)
class _PatioGml:
    """Patio crudo parseado del GML del WFS BU: anillos aún en EPSG:25830."""
    tipo: str                              # "cerrado" | "abierto"
    area_m2: float
    anillo_25830: list[tuple[float, float]]              # contorno exterior
    huecos_25830: tuple = ()               # anillos interiores (edificio(s) dentro del patio)


def _anillo_25830_a_wgs84(
    anillo: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Reproyecta un anillo de EPSG:25830 (m) a WGS84 (lon, lat). Descarta vértices
    no finitos para no envenenar la geometría aguas abajo."""
    out: list[tuple[float, float]] = []
    for x, y in anillo:
        try:
            lon, lat = _T_BU_A_WGS84.transform(float(x), float(y))
        except (TypeError, ValueError):
            continue
        if math.isfinite(lon) and math.isfinite(lat):
            out.append((float(lon), float(lat)))
    return out


def _area_anillo_m2(coords: list[tuple[float, float]]) -> float:
    """Área (fórmula del agrimensor / shoelace) de un anillo cerrado expresado en
    un CRS métrico (EPSG:25830) → m². El sentido del anillo es indiferente: se
    devuelve el valor absoluto. 0.0 si el anillo es degenerado."""
    n = len(coords)
    if n < 4:  # un anillo cerrado tiene mínimo 4 vértices (3 + el repetido)
        return 0.0
    acum = 0.0
    for i in range(n - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]
        acum += x1 * y2 - x2 * y1
    return abs(acum) / 2.0


def _coords_de_poslist(poslist: ET.Element | None) -> list[tuple[float, float]]:
    """(x, y) de un ``gml:posList`` respetando ``srsDimension`` (2D, o 3D → se
    descarta la Z). Lista vacía si no hay texto o no parsea."""
    if poslist is None or not (poslist.text or "").strip():
        return []
    try:
        dim = int(poslist.get("srsDimension") or "2")
    except ValueError:
        dim = 2
    if dim not in (2, 3):
        dim = 2
    valores = re.split(r"\s+", poslist.text.strip())
    try:
        return [
            (float(valores[i]), float(valores[i + 1]))
            for i in range(0, len(valores) - (dim - 1), dim)
        ]
    except (ValueError, IndexError):
        return []


def _poslist_en(elem: ET.Element) -> ET.Element | None:
    for ns_uri in _GML_NS.values():
        pl = elem.find(f".//{{{ns_uri}}}posList")
        if pl is not None:
            return pl
    return None


def _comps_poligonales(geom) -> list[Polygon]:
    """Componentes Polygon no vacías de una geometría (Polygon o Multi*/colección)."""
    return [g for g in getattr(geom, "geoms", [geom])
            if getattr(g, "geom_type", "") == "Polygon" and not g.is_empty]


def _frac_borde_edificio(comp: Polygon, building: Polygon) -> float:
    """Fracción del perímetro EXTERIOR de ``comp`` que coincide con el borde del
    edificio.

    ~1 = hueco muy rodeado por el edificio (patio); bajo = abierto al lindero
    (retranqueo/jardín). Solo se aplica a huecos MACIZOS (sin anillo interior): un
    patio en ANILLO —el edificio dentro— se acepta directamente por tener hueco, aunque
    su contorno exterior sea el lindero de la parcela. Tolerancia 0,15 m para el solape
    de bordes reproyectados.
    """
    borde = comp.exterior
    if borde.length <= 0:
        return 0.0
    try:
        compartido = borde.intersection(building.boundary.buffer(0.15))
    except Exception:  # noqa: BLE001
        return 0.0
    return float(getattr(compartido, "length", 0.0)) / float(borde.length)


def _patios_abiertos(
    building: Polygon | None,
    parcela: Polygon | None,
) -> list[tuple[float, list[tuple[float, float]], list[list[tuple[float, float]]]]]:
    """Patios ABIERTOS (patinejos/entrantes no marcados como ``gml:interior``).

    Con la parcela conocida: el patio es la zona del HUECO (``parcela − edificio``)
    que (1) sobrevive a una APERTURA morfológica —se descartan las franjas finas de
    retranqueo— y (2) está muy rodeada por el edificio (``_frac_borde_edificio`` ≥
    ``_PATIO_FRAC_EDIF_MIN``), lo que excluye retranqueos/jardines abiertos a fachada.
    Capta el patio ENTERO, aunque parte cierre contra el lindero (que el cierre del
    edificio dejaba fuera) y aunque no tenga un entrante marcado del edificio.

    Si el edificio queda DENTRO del patio (parcela ocupada por patio con la
    construcción en medio), la zona es un ANILLO: se conservan sus HUECOS.

    Sin parcela (fallback): solo el cierre morfológico del edificio.

    Devuelve, por cada patio ≥ mínimo, ``(area_m2, exterior_25830, huecos_25830)``.
    """
    if building is None or building.is_empty:
        return []

    def _como_salida(polis):
        salida = []
        for g in polis:
            if g.area < _PATIO_AREA_MIN_M2:
                continue
            ext = [(float(x), float(y)) for x, y in g.exterior.coords]
            huecos = [[(float(x), float(y)) for x, y in h.coords] for h in g.interiors]
            salida.append((float(g.area), ext, huecos))
        return salida

    if parcela is None or parcela.is_empty:
        # Fallback histórico: entrantes de boca estrecha del propio edificio.
        r = _PATIO_ABIERTO_RADIO_M
        try:
            cierre = building.buffer(r, join_style=2).buffer(-r, join_style=2)
            semillas = _comps_poligonales(cierre.difference(building))
        except Exception:  # noqa: BLE001 — geometría degenerada → sin patios abiertos
            return []
        return _como_salida(semillas)

    # Con parcela: zonas compactas del hueco. Un hueco en ANILLO (edificio dentro) es
    # patio por definición; uno MACIZO solo si está muy rodeado por el edificio.
    try:
        void = parcela.difference(building)
        w = _PATIO_APERTURA_M
        abierto = void.buffer(-w, join_style=2).buffer(w, join_style=2)
    except Exception:  # noqa: BLE001 — geometría degenerada → sin patios abiertos
        return []
    patios = []
    for g in _comps_poligonales(abierto):
        if g.area < _PATIO_AREA_MIN_M2:
            continue
        if len(g.interiors) > 0 or _frac_borde_edificio(g, building) >= _PATIO_FRAC_EDIF_MIN:
            patios.append(g)
    return _como_salida(patios)


def _parsear_patios_gml(
    xml_text: str, parcela_25830: Polygon | None = None,
) -> list[_PatioGml] | None:
    """Patios del edificio en la huella catastral (WFS BU), de dos tipos:

    - **Cerrados**: anillos interiores (``gml:interior``) = huecos de la huella.
      Geometría exacta.
    - **Abiertos**: patinejos/entrantes que el Catastro NO marca como hueco. Si se
      pasa ``parcela_25830`` (contorno de la parcela ya en EPSG:25830) se toman como
      la zona compacta del hueco ``parcela − edificio`` con entrante del edificio
      (geometría aproximada, pero ENTERA aunque cierre contra el lindero). Sin
      parcela, solo el cierre morfológico del edificio (capta menos).

    Con la respuesta en EPSG:25830 (metros) las áreas salen en m² y los anillos se
    conservan en ese mismo CRS. Devuelve la lista de patios (cerrados seguidos de
    abiertos) —lista vacía si la huella no tiene patios— o ``None`` si el XML no es
    parseable o es un ``ExceptionReport`` del servidor.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    if root.tag.rsplit("}", 1)[-1].lower() == "exceptionreport":
        return None

    exteriores: list[list[tuple[float, float]]] = []
    interiores: list[list[tuple[float, float]]] = []
    for ns_uri in _GML_NS.values():
        for ext in root.findall(f".//{{{ns_uri}}}exterior"):
            exteriores.append(_coords_de_poslist(_poslist_en(ext)))
        for inter in root.findall(f".//{{{ns_uri}}}interior"):
            interiores.append(_coords_de_poslist(_poslist_en(inter)))

    # Huella del edificio = unión de los exteriores (rellenos; los huecos interiores
    # se tratan aparte como patios cerrados, así no se cuentan dos veces).
    poligonos = []
    for coords in exteriores:
        if len(coords) >= 4:
            p = Polygon(coords)
            if not p.is_valid:
                p = p.buffer(0)
            if not p.is_empty and p.area > 0.5:
                poligonos.append(p)
    building = unary_union(poligonos) if poligonos else None

    patios: list[_PatioGml] = []
    # Patios cerrados (huecos): área por shoelace, cualquier tamaño > 0; anillo exacto.
    for coords in interiores:
        area = _area_anillo_m2(coords)
        if area > 0 and len(coords) >= 4:
            patios.append(_PatioGml("cerrado", area, [(float(x), float(y)) for x, y in coords]))
    # Patios abiertos (patinejos/entrantes): geometría aproximada, con huecos si el
    # edificio queda dentro del patio (anillo).
    for area, anillo, huecos in _patios_abiertos(building, parcela_25830):
        patios.append(_PatioGml("abierto", area, anillo, tuple(huecos)))

    return patios


def _patios_por_rc(
    rc14: str, contorno_wgs84: list[tuple[float, float]] | None = None,
) -> list[PatioCatastral] | None:
    """Patios del edificio de la parcela (con su anillo en WGS84), vía WFS BU
    INSPIRE (stored query ``GetBuildingByParcel``). UNA sola petición, en EPSG:25830
    para que las áreas salgan en metros; el anillo se reproyecta a WGS84.

    ``contorno_wgs84`` (contorno de la parcela de §2.1) acota los patios abiertos al
    hueco real ``parcela − edificio`` para captarlos enteros; si falta, se cae al
    cierre del propio edificio.

    *Best-effort*: devuelve ``None`` ante cualquier fallo (red, rate limit, parseo).
    Los patios NO son críticos para localizar la parcela —el caller sigue sin
    ellos—, así que el rate limit se traga aquí a propósito: lo señalan las
    llamadas principales, no este extra (ver feedback_no_quemar_api_catastro).
    """
    rc14 = (rc14 or "")[:14]
    if len(rc14) != 14:
        return None
    # Parcela (contorno WGS84 de §2.1) reproyectada al CRS del edificio (25830).
    parcela_25830: Polygon | None = None
    if contorno_wgs84 and len(contorno_wgs84) >= 3:
        try:
            pts = [_T_WGS84_A_BU.transform(float(x), float(y)) for x, y in contorno_wgs84]
            pp = Polygon(pts)
            if not pp.is_valid:
                pp = pp.buffer(0)
            if not pp.is_empty:
                parcela_25830 = pp
        except Exception:  # noqa: BLE001 — sin parcela usable → fallback al edificio
            parcela_25830 = None
    # URL cruda: el Catastro acepta `STOREDQUERIE_ID` (la usa él mismo) y NO debe
    # encodearse el ':' del srsName (el WFS de stored queries lo trata literal, igual
    # que `fetch_parcela_por_rc` del módulo). Por eso no se pasa por `params=`.
    url = (
        f"{URL_INSPIRE_WFS_BU}"
        f"?service=WFS&version=2.0.0&request=GetFeature"
        f"&STOREDQUERIE_ID=GetBuildingByParcel&refcat={rc14}"
        f"&srsName=urn:ogc:def:crs:EPSG::25830"
    )
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        _detectar_rate_limit(resp)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — patios opcionales, nunca bloqueantes
        log.warning("WFS BU patios falló para %s: %s", rc14, exc)
        return None
    crudos = _parsear_patios_gml(resp.text, parcela_25830)
    if crudos is None:
        return None
    patios: list[PatioCatastral] = []
    for pg in crudos:
        anillo_wgs = _anillo_25830_a_wgs84(pg.anillo_25830)
        if len(anillo_wgs) < 3:
            continue
        huecos_wgs: list[list[tuple[float, float]]] = []
        for h in pg.huecos_25830:
            hw = _anillo_25830_a_wgs84(h)
            if len(hw) >= 3:
                huecos_wgs.append(hw)
        patios.append(PatioCatastral(
            tipo=pg.tipo, area_m2=round(pg.area_m2, 1),
            contorno_wgs84=anillo_wgs, huecos_wgs84=huecos_wgs,
        ))
    if patios:
        log.info(
            "Patios catastrales de %s: %s",
            rc14, [(p.tipo, round(p.area_m2, 1)) for p in patios],
        )
    return patios


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
        except RateLimitCatastro:
            raise
        except (ValueError, ErrorServidorCatastro) as exc:
            # El rate limit por esta vía no llega como 403 sino como mensaje de
            # error de ESCatastroLib: hay que detectarlo en el texto, si no el
            # bloqueo horario quedaría invisible y se persistirían datos vacíos.
            if _texto_indica_rate_limit(str(exc)):
                raise RateLimitCatastro(_MSG_RATE_LIMIT) from exc
            raise ParcelaNoEncontrada(
                f"No se pudo obtener el detalle de la subreferencia {rc_limpio}."
            ) from exc
        except requests.RequestException as exc:
            raise ParcelaNoEncontrada(
                "No se pudo conectar con el Catastro al pedir el detalle de "
                f"{rc_limpio}. Inténtalo de nuevo en unos minutos."
            ) from exc
        except Exception as exc:  # parseo XML/atributos inesperados de ESCatastroLib
            raise ParcelaNoEncontrada(
                f"El Catastro devolvió una respuesta inesperada para {rc_limpio}."
            ) from exc
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
