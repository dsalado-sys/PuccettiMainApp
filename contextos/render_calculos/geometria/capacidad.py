"""Derivación del nº de viviendas a partir de la EDIFICABILIDAD (§2.3/§2.4).

Iteración 4 (2026-06-04): fuente de verdad numérica. Fórmula con
tres porcentajes explícitos (muros, circulación, núcleo).

Por planta:
    construida_i = huella_planta (ya con retranqueos + ocupación)
    muros_i      = construida_i × pct_muros / 100
    circulacion_i= construida_i × pct_circulacion / 100
    nucleo_i     = construida_i × pct_nucleo / 100
    descuento_comunes_i = comunes_obligatorias / n_plantas_habitables (apt)
    util_unidades_i = construida_i − muros_i − circulacion_i − nucleo_i − descuento_comunes_i
    viv_por_planta_i = floor(util_unidades_i / util_objetivo_por_unidad)

Sótanos: viv=0 forzado (no habitable). Muros y núcleo se siguen aplicando.
Ático: si computa_edif=False, sigue generando unidades pero no consume techo.
Plantas que excedan el techo (`construida_computable > coef × parcela`)
quedan recortadas: viv=0 y útil=0.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .config import Parametros
from .programa import util_maximo


def _truncar(x: float) -> int:
    """Política de redondeo del módulo: hacia abajo (truncar a entero)."""
    return max(0, int(x))


@dataclass
class Capacidad:
    superficie_parcela_m2: float
    coeficiente_edificabilidad: float
    edificabilidad_m2: float                # = parcela × coeficiente (KPI)
    ocupacion_maxima: float
    n_plantas_solicitadas: int
    n_plantas_edificables: int
    huella_m2: float
    ocupacion_area_m2: float
    huella_efectiva_m2: float
    construida_prevista_m2: float
    factor_limitante: str
    n_dormitorios: int
    util_objetivo_viv_m2: float
    util_planta_disponible_m2: float
    viv_por_planta_objetivo: int
    n_viviendas_objetivo: int
    pct_muros: float
    pct_circulacion: float
    pct_nucleo: float
    viv_por_planta: list[int] = field(default_factory=list)
    construida_por_planta: list[float] = field(default_factory=list)
    util_por_planta: list[float] = field(default_factory=list)
    muros_por_planta: list[float] = field(default_factory=list)
    circulacion_por_planta: list[float] = field(default_factory=list)
    nucleo_por_planta: list[float] = field(default_factory=list)
    tipo_planta: list[str] = field(default_factory=list)
    nombres_planta: list[str] = field(default_factory=list)
    area_servicios_comunes_m2: float = 0.0
    n_plantas_habitables: int = 0
    construida_computable_m2: float = 0.0


def _nombre_planta(idx_visual: int, tipo: str) -> str:
    if tipo == "sotano":
        return "S1"
    if tipo == "atico":
        return "Ático"
    return "PB" if idx_visual == 0 else f"P{idx_visual}"


def calcular_capacidad(
    envolvente,
    params: Parametros,
    *,
    util_objetivo_por_unidad: float | None = None,
    area_servicios_comunes_m2: float = 0.0,
) -> Capacidad:
    """Deriva la capacidad numérica del edificio (sin geometría de unidades)."""
    parcela_area = envolvente.parcela.area
    urb = params.urbanismo

    pct_muros = max(0.0, min(80.0, float(params.diseno.pct_muros)))
    pct_circ = max(0.0, min(50.0, float(params.diseno.pct_circulacion)))
    pct_nucl = max(0.0, min(30.0, float(params.diseno.pct_nucleo)))
    pct_total = pct_muros + pct_circ + pct_nucl

    huella = envolvente.plantas[0].footprint.area if envolvente.plantas else parcela_area
    coef = urb.coeficiente_edificabilidad
    ocup_area = urb.ocupacion_maxima * parcela_area
    if getattr(urb, "usar_coeficiente_edificabilidad", True):
        edificabilidad_m2 = coef * parcela_area
    else:
        edificabilidad_m2 = ocup_area * max(1, urb.n_plantas_max)
    huella_efectiva = min(huella, ocup_area) if ocup_area > 0 else huella

    n_dorms = params.programa.n_dormitorios
    util_viv = (
        util_objetivo_por_unidad if util_objetivo_por_unidad is not None
        else util_maximo(n_dorms)
    )

    n_plantas_solicitadas = max(1, len(envolvente.plantas) or params.programa.n_plantas)
    plantas = list(envolvente.plantas)

    n_plantas_habitables = sum(1 for p in plantas if p.tipo != "sotano")
    if n_plantas_habitables <= 0:
        n_plantas_habitables = 1

    descuento_por_planta = area_servicios_comunes_m2 / n_plantas_habitables

    construida_computable_total = sum(p.footprint.area for p in plantas if p.computa_edif)
    n_plantas_edif_max = (
        max(1, int(edificabilidad_m2 // huella_efectiva)) if huella_efectiva else 1
    )

    # Recorte por techo: si la suma de plantas computables excede, las de arriba
    # quedan sin admitir (generan 0 unidades).
    excede_techo = construida_computable_total > edificabilidad_m2 + 1e-3
    techo_restante = edificabilidad_m2
    plantas_admitidas_idx: set[int] = set()
    for i, p in enumerate(plantas):
        if not p.computa_edif:
            plantas_admitidas_idx.add(i)
            continue
        if techo_restante + 1e-3 >= p.footprint.area:
            plantas_admitidas_idx.add(i)
            techo_restante -= p.footprint.area

    factor_limitante = "ninguno (cumple holgado)"
    if pct_total >= 100.0:
        factor_limitante = "porcentajes (no queda útil)"
    elif excede_techo:
        factor_limitante = "edificabilidad"
    elif params.programa.n_plantas > urb.n_plantas_max:
        factor_limitante = "altura (nº plantas)"
    elif huella > ocup_area + 1e-3:
        factor_limitante = "ocupación"

    viv_por_planta: list[int] = []
    construida_por_planta: list[float] = []
    util_por_planta: list[float] = []
    muros_por_planta: list[float] = []
    circulacion_por_planta: list[float] = []
    nucleo_por_planta: list[float] = []
    tipo_planta: list[str] = []
    nombres_planta: list[str] = []

    util_total = 0.0
    construida_total = 0.0
    construida_computable_efectiva = 0.0
    idx_visual = 0

    for i, p in enumerate(plantas):
        construida_i = p.footprint.area
        construida_total += construida_i
        admitida = i in plantas_admitidas_idx
        if p.computa_edif and admitida:
            construida_computable_efectiva += construida_i

        muros_i = construida_i * pct_muros / 100.0
        circ_i = construida_i * pct_circ / 100.0
        nucl_i = construida_i * pct_nucl / 100.0

        if p.tipo == "sotano":
            viv_i = 0
            util_i = 0.0
            nombre = _nombre_planta(0, "sotano")
        else:
            util_disponible_i = max(
                0.0,
                construida_i - muros_i - circ_i - nucl_i - descuento_por_planta,
            )
            if not admitida or util_viv <= 0:
                viv_i = 0
                util_i = 0.0
            else:
                viv_i = _truncar(util_disponible_i / util_viv)
                util_i = util_disponible_i
                util_total += util_disponible_i
            nombre = _nombre_planta(idx_visual, p.tipo)
            idx_visual += 1

        viv_por_planta.append(viv_i)
        construida_por_planta.append(round(construida_i, 2))
        util_por_planta.append(round(util_i, 2))
        muros_por_planta.append(round(muros_i, 2))
        circulacion_por_planta.append(round(circ_i, 2))
        nucleo_por_planta.append(round(nucl_i, 2))
        tipo_planta.append(p.tipo)
        nombres_planta.append(nombre)

    n_total = sum(viv_por_planta)
    viv_pp_regulares = [v for v, t in zip(viv_por_planta, tipo_planta) if t == "regular"]
    viv_pp_obj = (
        max(viv_pp_regulares) if viv_pp_regulares
        else (max(viv_por_planta) if viv_por_planta else 0)
    )

    util_planta_promedio = (
        util_total / max(1, n_plantas_habitables) if n_plantas_habitables else 0.0
    )

    return Capacidad(
        superficie_parcela_m2=round(parcela_area, 2),
        coeficiente_edificabilidad=coef,
        edificabilidad_m2=round(edificabilidad_m2, 2),
        ocupacion_maxima=urb.ocupacion_maxima,
        n_plantas_solicitadas=n_plantas_solicitadas,
        n_plantas_edificables=n_plantas_edif_max,
        huella_m2=round(huella, 2),
        ocupacion_area_m2=round(ocup_area, 2),
        huella_efectiva_m2=round(huella_efectiva, 2),
        construida_prevista_m2=round(construida_total, 2),
        factor_limitante=factor_limitante,
        n_dormitorios=n_dorms,
        util_objetivo_viv_m2=round(util_viv, 2),
        util_planta_disponible_m2=round(util_planta_promedio, 2),
        viv_por_planta_objetivo=viv_pp_obj,
        n_viviendas_objetivo=n_total,
        pct_muros=pct_muros,
        pct_circulacion=pct_circ,
        pct_nucleo=pct_nucl,
        viv_por_planta=viv_por_planta,
        construida_por_planta=construida_por_planta,
        util_por_planta=util_por_planta,
        muros_por_planta=muros_por_planta,
        circulacion_por_planta=circulacion_por_planta,
        nucleo_por_planta=nucleo_por_planta,
        tipo_planta=tipo_planta,
        nombres_planta=nombres_planta,
        area_servicios_comunes_m2=round(area_servicios_comunes_m2, 2),
        n_plantas_habitables=n_plantas_habitables,
        construida_computable_m2=round(construida_computable_efectiva, 2),
    )


def capacidad_a_dict(cap: Capacidad) -> dict:
    """Serializa Capacidad a JSON-friendly dict."""
    return {
        "superficie_parcela_m2": cap.superficie_parcela_m2,
        "coeficiente_edificabilidad": cap.coeficiente_edificabilidad,
        "edificabilidad_m2": cap.edificabilidad_m2,
        "ocupacion_maxima": cap.ocupacion_maxima,
        "ocupacion_area_m2": cap.ocupacion_area_m2,
        "huella_m2": cap.huella_m2,
        "huella_efectiva_m2": cap.huella_efectiva_m2,
        "n_plantas_solicitadas": cap.n_plantas_solicitadas,
        "n_plantas_edificables": cap.n_plantas_edificables,
        "n_plantas_habitables": cap.n_plantas_habitables,
        "pct_muros": cap.pct_muros,
        "pct_circulacion": cap.pct_circulacion,
        "pct_nucleo": cap.pct_nucleo,
        "util_objetivo_viv_m2": cap.util_objetivo_viv_m2,
        "util_planta_disponible_m2": cap.util_planta_disponible_m2,
        "n_dormitorios": cap.n_dormitorios,
        "viv_por_planta": list(cap.viv_por_planta),
        "viv_por_planta_objetivo": cap.viv_por_planta_objetivo,
        "n_viviendas_objetivo": cap.n_viviendas_objetivo,
        "construida_total_m2": round(sum(cap.construida_por_planta), 2),
        "util_total_m2": round(sum(cap.util_por_planta), 2),
        "muros_total_m2": round(sum(cap.muros_por_planta), 2),
        "circulacion_total_m2": round(sum(cap.circulacion_por_planta), 2),
        "nucleo_total_m2": round(sum(cap.nucleo_por_planta), 2),
        "construida_por_planta": list(cap.construida_por_planta),
        "util_por_planta": list(cap.util_por_planta),
        "muros_por_planta": list(cap.muros_por_planta),
        "circulacion_por_planta": list(cap.circulacion_por_planta),
        "nucleo_por_planta": list(cap.nucleo_por_planta),
        "tipo_planta": list(cap.tipo_planta),
        "nombres_planta": list(cap.nombres_planta),
        "construida_computable_m2": cap.construida_computable_m2,
        "area_servicios_comunes_m2": cap.area_servicios_comunes_m2,
        "factor_limitante": cap.factor_limitante,
    }
