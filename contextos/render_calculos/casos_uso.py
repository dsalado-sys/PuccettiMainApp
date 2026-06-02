"""§2.4–2.7 — Casos de uso del módulo Render y cálculos.

Orquestación entre el motor geométrico (`geometria/`), el aggregate `Proyecto`
y los puertos de persistencia (normativa municipal + Anexo I).

Los casos de uso son funciones/clases puras: reciben dependencias por
parámetro (DI) y no conocen FastAPI ni SQLAlchemy.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pyproj import Transformer
from shapely.geometry import Polygon
from shapely.ops import transform as shp_transform

from app.contextos.proyectos.puertos import ProyectoRepositorio
from app.nucleo.modelo import ModuloPuccetti, Proyecto

from .dominio import (
    Alerta,
    IndicadoresDiseno,
    ResumenEnvolvente,
    UsoEdificio,
)
from .geometria import macro_layout as ml
from .geometria.envolvente import construir_envolvente
from .geometria.parcelas import LadoParcela, orientacion_cardinal
from .geometria.serializacion import (
    edificio_a_dict,
    lados_a_dict,
    ring,
    tabla_por_planta,
    tabla_por_unidad,
)
from .parametros import (
    ParametrosRender,
    ParametrosUrbanisticos,
    parametros_a_dict,
    parametros_desde_dict,
)
from .puertos import NormativaMunicipalRepositorio


# ─── Reproyección WGS84 ↔ UTM30N (Iberia peninsular) ────────────────────────
# La localización guarda lon/lat en WGS84; el motor de geometría necesita metros.
_WGS84_A_UTM = Transformer.from_crs("EPSG:4326", "EPSG:25830", always_xy=True)
_UTM_A_WGS84 = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)


def _polygon_a_utm(coords_lonlat: list[tuple[float, float]]) -> Polygon:
    pts_xy = [_WGS84_A_UTM.transform(lon, lat) for lon, lat in coords_lonlat]
    return Polygon(pts_xy)


def _lado_a_utm(p1: tuple[float, float], p2: tuple[float, float]) -> tuple[tuple[float, float], tuple[float, float]]:
    a = _WGS84_A_UTM.transform(p1[0], p1[1])
    b = _WGS84_A_UTM.transform(p2[0], p2[1])
    return a, b


# ─── Construcción de la parcela métrica desde el proyecto ───────────────────
@dataclass
class ParcelaMetrica:
    poligono_utm: Polygon
    lados: list[LadoParcela]
    municipio: str | None
    provincia: str | None
    centroide_lonlat: tuple[float, float] | None
    referencia_catastral: str | None


def construir_parcela_metrica(proyecto: Proyecto) -> ParcelaMetrica | None:
    """Lee `proyecto.datos(LOCALIZACION)` y reproyecta a UTM30N.

    Devuelve None si no hay parcela asociada al proyecto. Es robusto frente a
    estructuras parciales (contorno sin lados, lados sin tipo válido, etc.).
    """
    datos = proyecto.datos_por_modulo.get(ModuloPuccetti.LOCALIZACION.value) or {}
    if not datos:
        return None

    contorno = datos.get("contorno_simplificado_wgs84") or datos.get("contorno_wgs84") or []
    if not contorno or len(contorno) < 3:
        return None

    poly = _polygon_a_utm([(float(p[0]), float(p[1])) for p in contorno])
    if poly.is_empty or not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty:
        return None

    lados_raw = datos.get("lados") or []
    lados: list[LadoParcela] = []
    for l in lados_raw:
        tipo = l.get("tipo", "fachada")
        if tipo not in ("fachada", "medianera"):
            tipo = "fachada"
        p1 = l.get("p1") or [0.0, 0.0]
        p2 = l.get("p2") or [0.0, 0.0]
        a, b = _lado_a_utm((float(p1[0]), float(p1[1])), (float(p2[0]), float(p2[1])))
        long_m = math.hypot(b[0] - a[0], b[1] - a[1])
        if long_m < 0.10:
            continue
        azimut_grados = (math.degrees(math.atan2(b[0] - a[0], b[1] - a[1]))) % 360
        lados.append(LadoParcela(
            p1=a, p2=b, tipo=tipo, longitud_m=long_m, azimut=azimut_grados,
        ))

    if not lados:
        # Si la parcela no trae lados, asumimos todo fachada (req. 1: medianera
        # no admite huecos; al ser todo fachada el motor permite ventanas en todos
        # los lados — el técnico puede reclasificar desde §2.1).
        coords = list(poly.exterior.coords)[:-1]
        for i, p1 in enumerate(coords):
            p2 = coords[(i + 1) % len(coords)]
            long_m = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            if long_m < 0.10:
                continue
            azimut_grados = (math.degrees(math.atan2(p2[0] - p1[0], p2[1] - p1[1]))) % 360
            lados.append(LadoParcela(
                p1=p1, p2=p2, tipo="fachada", longitud_m=long_m, azimut=azimut_grados,
            ))

    centroide_raw = datos.get("centroide_lonlat")
    centroide = None
    if centroide_raw and len(centroide_raw) >= 2:
        centroide = (float(centroide_raw[0]), float(centroide_raw[1]))

    return ParcelaMetrica(
        poligono_utm=poly,
        lados=lados,
        municipio=datos.get("municipio"),
        provincia=datos.get("provincia"),
        centroide_lonlat=centroide,
        referencia_catastral=datos.get("referencia_catastral"),
    )


# ─── Caso de uso 1: CalcularEnvolvente (§2.4 — preview rápido) ──────────────
@dataclass
class CalcularEnvolvente:
    """req. 8 — huella + plantas + patios. Sin macro_layout (rápido)."""

    def ejecutar(
        self,
        parcela: ParcelaMetrica,
        params: ParametrosRender,
    ) -> dict[str, Any]:
        params_motor = params.a_parametros_motor()
        try:
            envolvente = construir_envolvente(parcela.poligono_utm, params_motor)
        except ValueError as exc:
            return {
                "error": str(exc),
                "envolvente": None,
                "alertas": [_alerta_dict(Alerta("incumplimiento", "Geometría", str(exc)))],
                "indicadores": None,
            }

        from .geometria.capacidad import calcular_capacidad
        cap = calcular_capacidad(envolvente, params_motor)

        indicadores = _indicadores_disenho(parcela, envolvente.plantas)
        alertas = _alertas_envolvente(envolvente, parcela, params)

        bbox = envolvente.parcela.bounds
        resumen = ResumenEnvolvente(
            huella_m2=round(envolvente.plantas[0].footprint.area, 2) if envolvente.plantas else 0.0,
            n_plantas=len(envolvente.plantas),
            altura_planta_m=params.urbanisticos.altura_planta_m,
            edificabilidad_max_m2=round(envolvente.edificabilidad_max, 2),
            edificabilidad_consumida_m2=round(envolvente.edificabilidad_consumida, 2),
            n_viviendas_objetivo=cap.n_viviendas_objetivo,
            factor_limitante=cap.factor_limitante,
            bbox_world=(round(bbox[0], 2), round(bbox[1], 2), round(bbox[2], 2), round(bbox[3], 2)),
        )

        plantas_dict = []
        for pl in envolvente.plantas:
            plantas_dict.append({
                "n": pl.n,
                "nombre": "PB" if pl.n == 0 else f"P{pl.n}",
                "footprint": ring(pl.footprint),
                "patios": [
                    {"poligono": ring(p.geometry), "area_m2": round(p.area_m2, 2),
                     "luz_recta_m": round(p.luz_recta_m, 2)}
                    for p in pl.patios
                ],
                "construida_m2": round(pl.area_construida_m2, 2),
                "util_m2": round(pl.area_util_m2, 2),
            })

        return {
            "envolvente": {
                "huella_m2": resumen.huella_m2,
                "n_plantas": resumen.n_plantas,
                "altura_planta_m": resumen.altura_planta_m,
                "edificabilidad_max_m2": resumen.edificabilidad_max_m2,
                "edificabilidad_consumida_m2": resumen.edificabilidad_consumida_m2,
                "n_viviendas_objetivo": resumen.n_viviendas_objetivo,
                "factor_limitante": resumen.factor_limitante,
                "bbox": list(resumen.bbox_world),
                "plantas": plantas_dict,
            },
            "parcela": {
                "poligono": ring(parcela.poligono_utm),
                "area_m2": round(parcela.poligono_utm.area, 2),
                "municipio": parcela.municipio,
                "provincia": parcela.provincia,
                "bbox": [round(v, 2) for v in parcela.poligono_utm.bounds],
            },
            "lados": lados_a_dict(parcela.lados),
            "indicadores": _indicadores_dict(indicadores),
            "alertas": [_alerta_dict(a) for a in alertas],
        }


# ─── Caso de uso 2: CalcularLayout (§2.4+§2.5 — completo) ───────────────────
@dataclass
class CalcularLayout:
    """req. 8+12 — envolvente + macro_layout + interiores + tabla."""

    def ejecutar(
        self,
        parcela: ParcelaMetrica,
        params: ParametrosRender,
    ) -> dict[str, Any]:
        # MVP: solo vivienda. Hotel y apartamentos se devuelven con aviso.
        if params.programa.uso != UsoEdificio.VIVIENDA:
            ce = CalcularEnvolvente().ejecutar(parcela, params)
            aviso = Alerta(
                "aviso",
                "Alcance MVP",
                f"La distribución interior para uso '{params.programa.uso.value}' "
                "está en desarrollo. La envolvente sí se calcula. "
                "Para vivienda plurifamiliar usa el modo 'Vivienda'.",
            )
            ce["alertas"] = [_alerta_dict(aviso)] + list(ce.get("alertas", []))
            ce["plantas"] = []
            ce["tabla_planta"] = []
            ce["tabla_unidad"] = []
            ce["edificio"] = None
            return ce

        params_motor = params.a_parametros_motor()
        try:
            envolvente = construir_envolvente(parcela.poligono_utm, params_motor)
        except ValueError as exc:
            return {
                "error": str(exc),
                "edificio": None,
                "alertas": [_alerta_dict(Alerta("incumplimiento", "Geometría", str(exc)))],
                "tabla_planta": [],
                "tabla_unidad": [],
                "indicadores": None,
            }

        n_viv_pp = params.programa.n_viviendas_por_planta_objetivo
        edificio = ml.generar_edificio(
            envolvente,
            parcela.lados,
            params_motor,
            n_viviendas_por_planta=n_viv_pp,
            seed=params.seed,
        )

        edif_dict = edificio_a_dict(edificio, params_motor, lados=parcela.lados)
        indicadores = _indicadores_disenho(parcela, envolvente.plantas, edificio=edificio)
        alertas = _alertas_envolvente(envolvente, parcela, params)
        alertas += _alertas_edificio(edificio, params)

        return {
            "edificio": edif_dict,
            "tabla_planta": tabla_por_planta(edificio),
            "tabla_unidad": tabla_por_unidad(edificio),
            "indicadores": _indicadores_dict(indicadores),
            "alertas": [_alerta_dict(a) for a in alertas],
        }


# ─── Caso de uso 3: ValidarCumplimiento ─────────────────────────────────────
@dataclass
class ValidarCumplimiento:
    """req. 7 — alertas Anexo I/II + PGOU + accesibilidad."""

    def ejecutar(
        self,
        parcela: ParcelaMetrica,
        params: ParametrosRender,
        normativa: ParametrosUrbanisticos | None,
    ) -> list[Alerta]:
        alertas: list[Alerta] = []

        if normativa is not None:
            if params.urbanisticos.edificabilidad_m2t_m2s > normativa.edificabilidad_m2t_m2s + 1e-6:
                alertas.append(Alerta(
                    "incumplimiento", "PGOU",
                    f"Edificabilidad {params.urbanisticos.edificabilidad_m2t_m2s:.2f} > "
                    f"{normativa.edificabilidad_m2t_m2s:.2f} (PGOU {parcela.municipio}).",
                ))
            if params.urbanisticos.n_plantas_max > normativa.n_plantas_max:
                alertas.append(Alerta(
                    "incumplimiento", "PGOU",
                    f"Plantas máximas {params.urbanisticos.n_plantas_max} > "
                    f"{normativa.n_plantas_max} (PGOU {parcela.municipio}).",
                ))
            if params.programa.uso not in normativa.usos_permitidos:
                alertas.append(Alerta(
                    "incumplimiento", "PGOU",
                    f"Uso '{params.programa.uso.value}' no permitido por el PGOU de "
                    f"{parcela.municipio}.",
                ))

        if params.urbanisticos.area_patio_min_m2 < 12.0 - 1e-6:
            alertas.append(Alerta(
                "aviso", "Anexo II A2.5",
                "El patio mínimo del Anexo II es 12 m². Estás permitiendo patios más pequeños.",
            ))
        if params.urbanisticos.luz_recta_patio_min_m < 3.0 - 1e-6:
            alertas.append(Alerta(
                "aviso", "Anexo II A2.5",
                "La luz recta mínima del patio en el Anexo II es 3.00 m.",
            ))

        if params.programa.pct_unidades_adaptadas < 5.0:
            alertas.append(Alerta(
                "aviso", "DB SUA",
                f"DB SUA exige ≥5% de unidades adaptadas; tienes {params.programa.pct_unidades_adaptadas:.0f}%.",
            ))
        if params.diseno.ancho_min_pasillo_comun_m < 1.20 - 1e-6:
            alertas.append(Alerta(
                "incumplimiento", "DB SUA",
                f"Pasillo común {params.diseno.ancho_min_pasillo_comun_m:.2f} m < 1.20 m (DB SUA).",
            ))
        if params.diseno.diametro_min_vestibulo_m < 1.50 - 1e-6:
            alertas.append(Alerta(
                "incumplimiento", "Anexo II A2.1",
                f"Vestíbulo Ø {params.diseno.diametro_min_vestibulo_m:.2f} m < 1.50 m.",
            ))

        return alertas


# ─── Caso de uso 4: GuardarRender ───────────────────────────────────────────
@dataclass
class GuardarRender:
    """Persiste parámetros + resumen del último cálculo en el aggregate."""

    repo_proyectos: ProyectoRepositorio

    def ejecutar(
        self,
        proyecto: Proyecto,
        params: ParametrosRender,
        resumen: dict[str, Any],
    ) -> Proyecto:
        datos = {
            "parametros": parametros_a_dict(params),
            "resumen_ultimo_calculo": resumen,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        proyecto.fijar_datos(ModuloPuccetti.RENDER_CALCULOS, datos)
        return self.repo_proyectos.guardar(proyecto)


def parametros_desde_proyecto(proyecto: Proyecto | None) -> ParametrosRender:
    """Lee parámetros del aggregate; usa los del módulo de viabilidad como fallback."""
    if proyecto is None:
        return ParametrosRender()
    datos_render = proyecto.datos_por_modulo.get(ModuloPuccetti.RENDER_CALCULOS.value) or {}
    if datos_render.get("parametros"):
        return parametros_desde_dict(datos_render["parametros"])

    # Si no se ha guardado nada todavía, intentamos heredar la edificabilidad
    # introducida en §2.9 viabilidad.
    base = ParametrosRender()
    datos_viab = proyecto.datos_por_modulo.get(ModuloPuccetti.VIABILIDAD.value) or {}
    try:
        base.urbanisticos.edificabilidad_m2t_m2s = float(
            datos_viab.get("edificabilidad_m2t_m2s", base.urbanisticos.edificabilidad_m2t_m2s)
        )
    except (TypeError, ValueError):
        pass
    return base


# ─── Helpers privados ───────────────────────────────────────────────────────
def _alerta_dict(a: Alerta) -> dict[str, Any]:
    return {
        "nivel": a.nivel,
        "regla": a.regla,
        "mensaje": a.mensaje,
        "elemento": a.elemento,
    }


def _indicadores_dict(ind: IndicadoresDiseno) -> dict[str, Any]:
    return {
        "compacidad": round(ind.compacidad, 3),
        "proporcion_huecos": round(ind.proporcion_huecos, 3),
        "orientacion_dominante": ind.orientacion_dominante,
        "long_total_fachadas_m": round(ind.long_total_fachadas_m, 2),
        "long_total_medianeras_m": round(ind.long_total_medianeras_m, 2),
        "n_fachadas": ind.n_fachadas,
        "n_medianeras": ind.n_medianeras,
        "orientaciones_fachadas": list(ind.orientaciones_fachadas),
    }


def _indicadores_disenho(
    parcela: ParcelaMetrica,
    plantas: list,
    edificio=None,
) -> IndicadoresDiseno:
    """req. 15 — compacidad, orientación dominante, % huecos."""
    fach = [l for l in parcela.lados if l.tipo == "fachada"]
    med = [l for l in parcela.lados if l.tipo == "medianera"]
    long_fach = sum(l.longitud_m for l in fach)
    long_med = sum(l.longitud_m for l in med)

    orientacion_dom = "—"
    if fach:
        ldom = max(fach, key=lambda l: l.longitud_m)
        orientacion_dom = orientacion_cardinal(ldom.azimut)

    huella = plantas[0].footprint if plantas else parcela.poligono_utm
    area = huella.area
    perim = huella.length if not huella.is_empty else 1.0
    compacidad = (4 * math.pi * area / (perim ** 2)) if perim > 0 else 0.0

    # Estimación gruesa de huecos: 25% de la fachada del edificio (regla de pulgar)
    # por número de plantas. En iteración posterior puede afinarse desde el
    # macro_layout (suma de hueco_disp_m2 por unidad).
    n_plantas = len(plantas) or 1
    altura_total = n_plantas * 3.0
    area_fachada = long_fach * altura_total if long_fach else 1.0
    if edificio is not None and edificio.plantas:
        hueco_total = sum(
            u.hueco_disp_m2 for pl in edificio.plantas for u in pl.unidades
        )
        proporcion = hueco_total / area_fachada if area_fachada > 0 else 0.0
    else:
        proporcion = 0.25  # estimación neutra

    return IndicadoresDiseno(
        compacidad=compacidad,
        proporcion_huecos=proporcion,
        orientacion_dominante=orientacion_dom,
        long_total_fachadas_m=long_fach,
        long_total_medianeras_m=long_med,
        n_fachadas=len(fach),
        n_medianeras=len(med),
        orientaciones_fachadas=[orientacion_cardinal(l.azimut) for l in fach],
    )


def _alertas_envolvente(envolvente, parcela: ParcelaMetrica, params: ParametrosRender) -> list[Alerta]:
    """Alertas derivadas del cálculo de envolvente (§2.4)."""
    alertas: list[Alerta] = []
    if envolvente.edificabilidad_consumida > envolvente.edificabilidad_max + 1e-3:
        alertas.append(Alerta(
            "incumplimiento", "PGOU",
            f"Edificabilidad consumida ({envolvente.edificabilidad_consumida:.0f} m²) "
            f"supera el techo máximo ({envolvente.edificabilidad_max:.0f} m²).",
        ))
    if not [l for l in parcela.lados if l.tipo == "fachada"]:
        alertas.append(Alerta(
            "incumplimiento", "A2.4",
            "La parcela no tiene ningún lado clasificado como fachada. "
            "Sin fachada no se puede abrir huecos: revisa la clasificación en §2.1.",
        ))
    return alertas


def _alertas_edificio(edificio, params: ParametrosRender) -> list[Alerta]:
    """Alertas derivadas del macro_layout (§2.5)."""
    alertas: list[Alerta] = []
    for pl in edificio.plantas:
        for inc in pl.incidencias:
            nivel = "incumplimiento" if any(k in inc for k in ("A2.", "sin acceso", "sin fachada", "ciega")) else "aviso"
            alertas.append(Alerta(nivel, "Anexo II", inc, elemento=None))

    cap = edificio.capacidad
    if cap and edificio.viv_por_planta_dispuestas < edificio.viv_por_planta_objetivo:
        alertas.append(Alerta(
            "aviso", "Distribución",
            f"Se han dispuesto {edificio.viv_por_planta_dispuestas} viviendas/planta de "
            f"{edificio.viv_por_planta_objetivo} objetivo. Factor limitante: {cap.factor_limitante}.",
        ))
    return alertas
