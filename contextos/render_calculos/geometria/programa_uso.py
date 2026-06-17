"""Generalización del motor: descriptor del programa por unidad (§2.5).

Hasta la iteración 1 el motor (`macro_layout.py`, `capacidad.py`) estaba atado
a `programa.programa_vivienda` y a la noción de `n_dormitorios`. La iteración 2
introduce apartamentos turísticos cuyo dimensionamiento depende de
(categoría, tipología), no del nº de dormitorios.

`ProgramaUso` encapsula los **cuatro datos** que el motor necesita para trocear
una planta sin saber si es vivienda o apartamento:

    util_objetivo_unidad_m2  → tamaño objetivo (driver del nº de unidades)
    area_min_unidad_m2       → mínimo viable (suma de mínimos Anexo I + 15%)
    util_max_unidad_m2       → tope para no sobredimensionar
    n_dormitorios            → conservado solo para `_evaluar_unidad` (ventilación, baños)
    tipo_unidad              → "vivienda" | "apartamento" (etiqueta en la dataclass `Unidad`)
    area_servicios_obligatorios_m2 → restado del techo en apartamentos (Decreto 194/2010)

Los constructores `programa_uso_vivienda()` y `programa_uso_apartamento()` viven
en sus respectivos módulos de programa para evitar imports circulares.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProgramaUso:
    util_objetivo_unidad_m2: float
    area_min_unidad_m2: float
    util_max_unidad_m2: float
    n_dormitorios: int
    tipo_unidad: str = "vivienda"
    area_servicios_obligatorios_m2: float = 0.0


@dataclass(frozen=True)
class TipologiaUnidadDescriptor:
    """Describe una tipología concreta para el reparto multi-tipología.

    Generaliza el reparto de vivienda (que solo conocía `n_dorms`) a cualquier
    uso: cada uso construye sus descriptores con los `util_*` de su Anexo I y el
    motor reparte sin saber si son viviendas, apartamentos o habitaciones.

    - `slug`            → identificador de la tipología en el espacio del uso
                          ("1d", "estudio", "doble"...). Lo consume la
                          serialización para regenerar las estancias por unidad.
    - `n_dorms_label`   → etiqueta numérica conservada en `unidades_por_planta`
                          (compatibilidad con el formato existente `(int, float)`).
    - `plazas`          → camas/usuarios de la tipología (áreas sociales por plaza
                          en albergue, 2º baño obligatorio si >5 en A1.4).
    """
    slug: str
    util_objetivo: float
    util_minimo: float
    util_maximo: float
    n_dorms_label: int
    tipo_unidad: str = "vivienda"
    plazas: int = 1


def reparto_multi_tipologia_generico(
    util_disponible: float,
    descriptores: list[TipologiaUnidadDescriptor],
) -> list[tuple[TipologiaUnidadDescriptor, float]]:
    """Reparte el útil disponible entre varias tipologías (cualquier uso).

    Misma política que `programa.reparto_multi_tipologia` (vivienda):
    1. Asigna 1 unidad de cada tipología seleccionada (consume su `util_maximo`,
       o lo que reste si es menor), ordenando de menor a mayor `util_maximo`.
    2. Rellena el sobrante con la tipología más pequeña mientras quepa su
       `util_minimo`.

    Devuelve `[(descriptor, util_asignado_m2), ...]` con UNA entrada por unidad.
    Si no llega ni para la más pequeña, devuelve `[]`.
    """
    if not descriptores or util_disponible <= 0:
        return []

    # Dedup por slug, conservando el primero, y orden ascendente por techo.
    vistos: dict[str, TipologiaUnidadDescriptor] = {}
    for d in descriptores:
        vistos.setdefault(d.slug, d)
    ordenados = sorted(vistos.values(), key=lambda d: d.util_maximo)
    mas_pequena = ordenados[0]

    unidades: list[tuple[TipologiaUnidadDescriptor, float]] = []
    util_restante = util_disponible

    for d in ordenados:
        if util_restante >= d.util_minimo - 1e-6:
            consumo = min(d.util_maximo, util_restante)
            unidades.append((d, consumo))
            util_restante -= consumo

    while util_restante >= mas_pequena.util_minimo - 1e-6:
        consumo = min(mas_pequena.util_maximo, util_restante)
        unidades.append((mas_pequena, consumo))
        util_restante -= consumo
        if consumo <= 1e-6:
            break

    return unidades
