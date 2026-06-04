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
