"""Derivación del nº de viviendas a partir de la EDIFICABILIDAD (§2.3/§2.4).

Iteración 3: el motor es ahora la **fuente de verdad** del módulo. La respuesta
de `/calcular` se construye desde estos números, no desde la geometría dispuesta
por `macro_layout.py` (que queda como código muerto hasta el rediseño del render).

Cambios respecto a iter. 2:
- **Truncar** en vez de redondeo half-up. Política conservadora: nunca inflar
  capacidad prometida en prefactibilidad.
- **Eficiencia configurable** desde `params.diseno.eficiencia_planta` (rango
  0.65–0.85, validado en `parametros.py`).
- **Áticos y sótanos** respetan los flags `atico_computa_edificabilidad` y
  `sotano_computa_edificabilidad`. Las plantas que no computan no consumen techo;
  las plantas tipo "sotano" no generan unidades habitables.
- **Desglose por planta**: `viv_por_planta`, `construida_por_planta`,
  `util_por_planta`, `tipo_planta` — alimentan las tablas sintéticas del módulo.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .config import Parametros
from .programa import util_maximo


EFICIENCIA_PLANTA = 0.72   # default histórico, hoy override desde params.diseno


def _truncar(x: float) -> int:
    """Política de redondeo del módulo: hacia abajo (truncar a entero).

    Si útil/objetivo = 3.5 → 3 unidades, no 4. Acordado con el usuario en
    iteración 3 para no inflar la capacidad mostrada al inversor.
    """
    return max(0, int(x))


@dataclass
class Capacidad:
    superficie_parcela_m2: float
    edificabilidad: float
    ocupacion_maxima: float
    n_plantas_solicitadas: int
    n_plantas_edificables: int
    techo_max_m2: float
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
    # Iteración 3 — desglose plantar por plantar
    eficiencia_planta: float = 0.72
    viv_por_planta: list[int] = field(default_factory=list)
    construida_por_planta: list[float] = field(default_factory=list)
    util_por_planta: list[float] = field(default_factory=list)
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
    envolvente, params: Parametros,
    eficiencia_planta: float | None = None,
    *,
    util_objetivo_por_unidad: float | None = None,
    area_servicios_comunes_m2: float = 0.0,
) -> Capacidad:
    """Deriva la capacidad numérica del edificio (sin generar geometría).

    Parámetros:
    - `eficiencia_planta`: si None, lee de `params.diseno.eficiencia_planta`
      (que a su vez es configurable por el técnico). Si se pasa explícito,
      sobreescribe — útil para tests.
    - `util_objetivo_por_unidad`: tamaño objetivo (m² útiles) por unidad. Lo
      resuelve `casos_uso.py` desde la BBDD del Anexo I editable, con fallback
      a las constantes hardcoded de `programa.py` / `programa_apartamentos.py`.
    - `area_servicios_comunes_m2`: m² del Decreto 194/2010 para apartamentos
      turísticos. Se restan del útil disponible POR EDIFICIO antes de derivar
      unidades/planta; el reparto se hace entre las plantas habitables.
    """
    parcela_area = envolvente.parcela.area
    urb = params.urbanismo

    # Eficiencia: prioridad parámetro explícito → params.diseno → default módulo.
    if eficiencia_planta is None:
        eficiencia_planta = getattr(params.diseno, "eficiencia_planta", EFICIENCIA_PLANTA)
    eficiencia_planta = max(0.50, min(0.95, float(eficiencia_planta)))

    huella = envolvente.plantas[0].footprint.area if envolvente.plantas else parcela_area
    techo_max = urb.edificabilidad * parcela_area
    ocup_area = urb.ocupacion_maxima * parcela_area
    huella_efectiva = min(huella, ocup_area)

    # Tamaño objetivo: lo da el caso de uso (BBDD del Anexo I), o fallback al
    # n_dormitorios del programa.
    n_dorms = params.programa.n_dormitorios
    util_viv = (
        util_objetivo_por_unidad if util_objetivo_por_unidad is not None
        else util_maximo(n_dorms)
    )

    # Plantas regulares = las que computan edif y son habitables. Las "regular"
    # y "atico" computan según su flag; los sótanos nunca generan unidades.
    n_plantas_solicitadas = max(1, len(envolvente.plantas) or params.programa.n_plantas)
    plantas = list(envolvente.plantas)

    # Plantas habitables = todas menos los sótanos.
    n_plantas_habitables = sum(1 for p in plantas if p.tipo != "sotano")
    if n_plantas_habitables <= 0:
        n_plantas_habitables = 1

    # Reparto de los servicios comunes obligatorios entre plantas habitables.
    descuento_por_planta = area_servicios_comunes_m2 / n_plantas_habitables

    construida_computable_total = sum(p.footprint.area for p in plantas if p.computa_edif)
    n_plantas_edif_max = (
        max(1, int(techo_max // huella_efectiva)) if huella_efectiva else 1
    )

    # Recortar plantas computables si exceden el techo: las regulares de arriba
    # abajo van perdiendo capacidad hasta encajar. Se marca el factor limitante.
    # Plantas no computables (ático no computa, sótano no computa) sobreviven.
    excede_techo = construida_computable_total > techo_max + 1e-3
    techo_restante = techo_max
    plantas_admitidas_idx: set[int] = set()
    for i, p in enumerate(plantas):
        if not p.computa_edif:
            plantas_admitidas_idx.add(i)
            continue
        if techo_restante + 1e-3 >= p.footprint.area:
            plantas_admitidas_idx.add(i)
            techo_restante -= p.footprint.area

    factor_limitante = "ninguno (cumple holgado)"
    if excede_techo:
        factor_limitante = "edificabilidad"
    elif params.programa.n_plantas > urb.n_plantas_max:
        factor_limitante = "altura (nº plantas)"
    elif huella > ocup_area + 1e-3:
        factor_limitante = "ocupación"

    # Cálculo plantar por plantar.
    viv_por_planta: list[int] = []
    construida_por_planta: list[float] = []
    util_por_planta: list[float] = []
    tipo_planta: list[str] = []
    nombres_planta: list[str] = []

    util_total = 0.0
    construida_total = 0.0
    idx_visual = 0  # numeración PB/P1/P2... saltándose el sótano

    construida_computable_efectiva = 0.0

    for i, p in enumerate(plantas):
        construida_i = p.footprint.area
        construida_total += construida_i
        admitida = i in plantas_admitidas_idx
        if p.computa_edif and admitida:
            construida_computable_efectiva += construida_i

        if p.tipo == "sotano":
            viv_i = 0
            util_i = 0.0
            nombre = _nombre_planta(0, "sotano")
        else:
            util_planta_bruta = construida_i * eficiencia_planta
            util_disponible_i = max(0.0, util_planta_bruta - descuento_por_planta)
            # Si la planta no entra en el techo edificable, no genera unidades.
            viv_i = (
                _truncar(util_disponible_i / util_viv) if (util_viv > 0 and admitida) else 0
            )
            util_i = util_disponible_i if admitida else 0.0
            util_total += util_i
            nombre = _nombre_planta(idx_visual, p.tipo)
            idx_visual += 1

        viv_por_planta.append(viv_i)
        construida_por_planta.append(round(construida_i, 2))
        util_por_planta.append(round(util_i, 2))
        tipo_planta.append(p.tipo)
        nombres_planta.append(nombre)

    n_total = sum(viv_por_planta)
    # viv_por_planta_objetivo = el valor más común entre las plantas regulares
    # (mejor representación para "X viviendas por planta" mostrado al técnico).
    viv_pp_regulares = [v for v, t in zip(viv_por_planta, tipo_planta) if t == "regular"]
    viv_pp_obj = max(viv_pp_regulares) if viv_pp_regulares else (max(viv_por_planta) if viv_por_planta else 0)

    util_planta_promedio = (util_total / max(1, n_plantas_habitables)) if n_plantas_habitables else 0.0

    return Capacidad(
        superficie_parcela_m2=round(parcela_area, 2),
        edificabilidad=urb.edificabilidad,
        ocupacion_maxima=urb.ocupacion_maxima,
        n_plantas_solicitadas=n_plantas_solicitadas,
        n_plantas_edificables=n_plantas_edif_max,
        techo_max_m2=round(techo_max, 2),
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
        eficiencia_planta=eficiencia_planta,
        viv_por_planta=viv_por_planta,
        construida_por_planta=construida_por_planta,
        util_por_planta=util_por_planta,
        tipo_planta=tipo_planta,
        nombres_planta=nombres_planta,
        area_servicios_comunes_m2=round(area_servicios_comunes_m2, 2),
        n_plantas_habitables=n_plantas_habitables,
        construida_computable_m2=round(construida_computable_efectiva, 2),
    )


def capacidad_a_dict(cap: Capacidad) -> dict:
    """Serializa Capacidad a JSON-friendly dict (consumido por el frontend)."""
    return {
        "superficie_parcela_m2": cap.superficie_parcela_m2,
        "edificabilidad": cap.edificabilidad,
        "ocupacion_maxima": cap.ocupacion_maxima,
        "techo_max_m2": cap.techo_max_m2,
        "huella_m2": cap.huella_m2,
        "huella_efectiva_m2": cap.huella_efectiva_m2,
        "ocupacion_area_m2": cap.ocupacion_area_m2,
        "n_plantas_solicitadas": cap.n_plantas_solicitadas,
        "n_plantas_edificables": cap.n_plantas_edificables,
        "n_plantas_habitables": cap.n_plantas_habitables,
        "eficiencia_planta": round(cap.eficiencia_planta, 3),
        "util_objetivo_viv_m2": cap.util_objetivo_viv_m2,
        "util_planta_disponible_m2": cap.util_planta_disponible_m2,
        "n_dormitorios": cap.n_dormitorios,
        "viv_por_planta": list(cap.viv_por_planta),
        "viv_por_planta_objetivo": cap.viv_por_planta_objetivo,
        "n_viviendas_objetivo": cap.n_viviendas_objetivo,
        "construida_total_m2": round(sum(cap.construida_por_planta), 2),
        "util_total_m2": round(sum(cap.util_por_planta), 2),
        "construida_por_planta": list(cap.construida_por_planta),
        "util_por_planta": list(cap.util_por_planta),
        "tipo_planta": list(cap.tipo_planta),
        "nombres_planta": list(cap.nombres_planta),
        "construida_computable_m2": cap.construida_computable_m2,
        "area_servicios_comunes_m2": cap.area_servicios_comunes_m2,
        "factor_limitante": cap.factor_limitante,
    }
