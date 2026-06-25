"""§2.5 / DB-SUA — unidades adaptadas automáticas por tramos.

Sustituye al antiguo parámetro editable `pct_unidades_adaptadas`. El número de
unidades adaptadas se deriva del número total de alojamientos del edificio
según la tabla normativa de accesibilidad; solo aplica a los usos turísticos
(apartamentos turísticos y hoteles), NUNCA a vivienda.

Las unidades adaptadas son más grandes (un factor por uso) y, al ocupar más,
REDUCEN la capacidad del edificio (caben menos unidades). La dependencia
circular (nº de adaptadas ↔ nº total) se resuelve por punto fijo sobre el área
edificable, que se conserva.

Config inmutable (§3.8): constantes de módulo, sin estado mutable global.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from .capacidad import Capacidad

# Usos cuyas unidades pueden adaptarse (tipo_unidad del motor de estancias).
USOS_TURISTICOS_ADAPTABLES: tuple[str, ...] = (
    "apartamento", "habitacion",
)

# Factor de agrandado de las estancias de una unidad adaptada, por uso (este mapa
# es el ÚNICO punto a tocar para ajustarlo).
FACTOR_AGRANDADO_POR_TIPO: Mapping[str, float] = {
    "apartamento": 1.25,
    "habitacion": 1.30,
}


def es_uso_adaptable(tipo_unidad: str) -> bool:
    """¿El uso (tipo_unidad del motor) admite unidades adaptadas? Vivienda no."""
    return tipo_unidad in USOS_TURISTICOS_ADAPTABLES


def factor_agrandado(tipo_unidad: str) -> float:
    """Factor multiplicativo de agrandado de la unidad adaptada (1.0 si no aplica)."""
    return FACTOR_AGRANDADO_POR_TIPO.get(tipo_unidad, 1.0)


def n_unidades_adaptadas(total: int) -> int:
    """Nº de unidades adaptadas según el nº total de alojamientos (DB-SUA).

    1–5→1 · 6–50→1 · 51–100→2 · 101–150→4 · 151–200→6 · >200→8+(n-201)//50.
    """
    if total <= 0:
        return 0
    if total <= 50:
        return 1
    if total <= 100:
        return 2
    if total <= 150:
        return 4
    if total <= 200:
        return 6
    return 8 + (total - 201) // 50


def modo_adaptacion(total: int) -> str:
    """`parcial` (solo dormitorio + aseo/baño) en edificios de 1–5 alojamientos;
    `total` (toda la unidad) en el resto."""
    return "parcial" if 1 <= total <= 5 else "total"


def estancia_se_agranda(nombre: str, modo: str) -> bool:
    """¿Esta estancia se agranda en una unidad adaptada, según el modo?

    - `parcial`: solo el dormitorio/habitación y el baño/aseo.
    - `total`: toda la unidad (cualquier estancia neta, salvo la circulación de
      acceso, que no es una estancia computable).
    """
    if modo == "parcial":
        return (
            nombre.startswith("dormitorio")
            or nombre == "habitacion"
            or nombre.startswith("bano")
            or nombre.startswith("aseo")
        )
    return not nombre.startswith("circulacion")


def _repack_adaptadas(cap: Capacidad, k: int, factor: float) -> Capacidad:
    """Recoloca, planta a planta, las `k` unidades adaptadas con su tamaño REAL
    agrandado, y deja que el nº de unidades de cada planta EMERJA de su área.

    Las adaptadas se sitúan en las plantas más bajas primero (PB → P1 → …, acceso
    sin ascensor). En cada planta: se agrandan sus primeras unidades por el factor
    (su útil pasa a `útil×factor`, dato real que la serialización ya verá grande) y
    se retiran unidades estándar (de las últimas) hasta que la suma de útiles quepa
    en el útil disponible de la planta. Así una planta con adaptadas aloja MENOS
    unidades —porque las suyas son mayores—, y las superiores mantienen su
    capacidad. `util_por_planta` (útil disponible) no cambia: es el mismo footprint.
    """
    if k <= 0:
        return cap
    unidades = [list(p) for p in cap.unidades_por_planta]
    tipologias = [list(p) for p in cap.tipologias_unidad_por_planta]
    mix = [dict(m) for m in cap.viviendas_por_tipologia]
    viv = list(cap.viv_por_planta)
    util_pp = list(cap.util_por_planta)
    adapt_restantes = k
    for i in range(len(unidades)):
        if adapt_restantes <= 0:
            break
        tipo = cap.tipo_planta[i] if i < len(cap.tipo_planta) else ""
        if tipo == "sotano" or not unidades[i]:
            continue
        util_disp = util_pp[i] if i < len(util_pp) else sum(u for _, u in unidades[i])
        n_adapt = min(adapt_restantes, len(unidades[i]))
        for j in range(n_adapt):
            nd, u = unidades[i][j]
            unidades[i][j] = (nd, u * factor)
        adapt_restantes -= n_adapt
        # Recortar unidades estándar (las últimas) hasta que la planta quepa. Si la
        # holgura del reparto ya absorbe el agrandado, no se retira ninguna.
        while (len(unidades[i]) > n_adapt
               and sum(u for _, u in unidades[i]) > util_disp + 1e-6):
            unidades[i].pop()
            slug = tipologias[i].pop() if tipologias[i] else None
            if i < len(viv) and viv[i] > 0:
                viv[i] -= 1
            if slug is not None and i < len(mix) and slug in mix[i]:
                mix[i][slug] -= 1
                if mix[i][slug] <= 0:
                    del mix[i][slug]
    return replace(
        cap,
        unidades_por_planta=unidades,
        tipologias_unidad_por_planta=tipologias,
        viviendas_por_tipologia=mix,
        viv_por_planta=viv,
        n_viviendas_objetivo=sum(viv),
    )


def aplicar_adaptacion_capacidad(cap: Capacidad, tipo_unidad: str) -> Capacidad:
    """Aplica la asignación automática de unidades adaptadas a una `Capacidad`.

    Para usos no adaptables (vivienda) devuelve `cap` sin cambios. Para usos
    turísticos:
    - modo `total` (≥6 alojamientos): recoloca las adaptadas con su tamaño real por
      planta (`_repack_adaptadas`); el nº de unidades por planta —y el total— emergen
      del área, así que una planta con adaptadas aloja menos unidades.
    - modo `parcial` (1–5): solo se agrandan dormitorio+aseo de 1 unidad; el
      incremento cabe en la holgura de la planta, no se pierde ninguna unidad y el
      agrandado se aplica en serialización.
    Fija `n_unidades_adaptadas` y `modo_adaptacion`.
    """
    if not es_uso_adaptable(tipo_unidad):
        return cap
    total = cap.n_viviendas_objetivo
    if total <= 0:
        return replace(cap, n_unidades_adaptadas=0, modo_adaptacion="total")
    if modo_adaptacion(total) == "parcial":
        return replace(
            cap, n_unidades_adaptadas=min(n_unidades_adaptadas(total), total),
            modo_adaptacion="parcial",
        )
    # El nº de adaptadas lo fija el nº NOMINAL de alojamientos (lo que la huella da
    # antes de agrandar); el repack determina luego el total real. Así el par
    # (total, k) es siempre consistente y no oscila en las fronteras de tramo.
    factor = factor_agrandado(tipo_unidad)
    k = n_unidades_adaptadas(total)
    capn = _repack_adaptadas(cap, k, factor)
    return replace(
        capn,
        n_unidades_adaptadas=min(k, capn.n_viviendas_objetivo),
        modo_adaptacion="total",
    )
