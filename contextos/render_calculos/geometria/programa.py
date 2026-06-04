"""Programa arquitectónico — Anexo I.5 del PDF (vivienda, Decreto Junta de Andalucía).

Devuelve la lista de estancias objetivo dada: número de dormitorios, superficie
útil disponible, y si la cocina va integrada (open plan) o independiente.

Copia desde `Modulos/puccetti-app/puccetti/programa.py`. Los valores se exponen
también vía constantes para que la capa de persistencia pueda sembrarlos en la
BBDD de normativa.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

Categoria = Literal["publica", "privada", "servicio", "circulacion"]


@dataclass(frozen=True)
class Estancia:
    nombre: str
    categoria: Categoria
    area_min_m2: float       # del Anexo I.5
    area_target_m2: float    # nuestro objetivo (>= mínimo)

    def __repr__(self) -> str:
        return f"{self.nombre}({self.categoria},{self.area_target_m2:.1f}m2)"


# Anexo I.5 — superficies mínimas vivienda VPO Junta de Andalucía.
MIN_DORM_INDIVIDUAL = 8.0
MIN_DORM_DOBLE = 12.0
MIN_COCINA = 7.0
MIN_BANO = 3.0
MIN_ASEO = 1.5
SALON_MIN = {1: 14, 2: 16, 3: 18, 4: 20, 5: 24}
SALON_MAS_COCINA_MIN = {1: 20, 2: 20, 3: 24, 4: 24, 5: 28}

# Superficie útil máxima de referencia (VPO):
UTIL_MAX = {0: 35, 1: 60, 2: 70, 3: 90, 4: 110, 5: 130, 6: 150}


def programa_vivienda(
    n_dorms: int,
    util_disponible: float,
    salon_cocina_open: bool = False,
) -> list[Estancia]:
    """§2.5 + Anexo I.5 — lista de estancias para una vivienda. n_dorms = 0 → estudio."""
    if n_dorms == 0:
        return [
            Estancia('salon_cocina', 'publica', 20.0, max(20.0, util_disponible * 0.55)),
            Estancia('dormitorio', 'privada', MIN_DORM_DOBLE, max(MIN_DORM_DOBLE, util_disponible * 0.30)),
            Estancia('bano', 'servicio', MIN_BANO, MIN_BANO + 1.0),
        ]

    estancias: list[Estancia] = []
    salon_min = SALON_MIN.get(n_dorms, 24)
    cocina_min = MIN_COCINA
    if salon_cocina_open:
        target = max(SALON_MAS_COCINA_MIN.get(n_dorms, 28), util_disponible * 0.30)
        estancias.append(Estancia('salon_cocina', 'publica', salon_min + cocina_min, target))
    else:
        estancias.append(Estancia('salon', 'publica', salon_min, salon_min + 2.0))
        estancias.append(Estancia('cocina', 'publica', cocina_min, cocina_min + 1.0))

    for i in range(n_dorms):
        if i == 0:
            estancias.append(Estancia('dormitorio_1', 'privada', MIN_DORM_DOBLE, MIN_DORM_DOBLE + 1.0))
        else:
            estancias.append(Estancia(f'dormitorio_{i + 1}', 'privada', MIN_DORM_INDIVIDUAL, MIN_DORM_INDIVIDUAL + 2.0))

    if util_disponible > 70 or n_dorms >= 3:
        estancias.append(Estancia('bano_1', 'servicio', MIN_BANO, MIN_BANO + 2.0))
        estancias.append(Estancia('aseo', 'servicio', MIN_ASEO, MIN_ASEO + 1.0))
    else:
        estancias.append(Estancia('bano', 'servicio', MIN_BANO, MIN_BANO + 2.0))

    return estancias


def util_maximo(n_dorms: int) -> float:
    return UTIL_MAX.get(n_dorms, 150)


def util_minimo_vivienda(n_dorms: int, salon_cocina_open: bool = False) -> float:
    """Mínimo viable de una vivienda (Anexo I.5 + 15% de circulación interior).

    Es el `area_min_unidad_m2` que `ProgramaUso` necesita para vivienda. Se
    expone aquí para que tanto `macro_layout._unidad_min_area` como el
    constructor `programa_uso_vivienda` lo derive del mismo cálculo.
    """
    prog = programa_vivienda(n_dorms, util_disponible=util_maximo(n_dorms),
                             salon_cocina_open=salon_cocina_open)
    return round(sum(e.area_min_m2 for e in prog) * 1.15, 2)


def programa_uso_vivienda(n_dorms: int, salon_cocina_open: bool = False):
    """Constructor del descriptor `ProgramaUso` para vivienda.

    Import perezoso para evitar ciclos: `programa_uso.py` no importa nada de
    este módulo, y este módulo importa `ProgramaUso` solo cuando hace falta.
    """
    from .programa_uso import ProgramaUso
    return ProgramaUso(
        util_objetivo_unidad_m2=util_maximo(n_dorms),
        area_min_unidad_m2=util_minimo_vivienda(n_dorms, salon_cocina_open),
        util_max_unidad_m2=util_maximo(n_dorms) * 1.25,
        n_dormitorios=n_dorms,
        tipo_unidad="vivienda",
        area_servicios_obligatorios_m2=0.0,
    )
