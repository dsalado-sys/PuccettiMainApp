"""Derivación del nº de viviendas a partir de la EDIFICABILIDAD (§2.3/§2.4).

Copia desde `Modulos/puccetti-app/puccetti/capacidad.py`.

El nº de unidades no lo fija el técnico a mano: se deriva del techo máximo
(edificabilidad · parcela), de la huella efectiva (ocupación · parcela) y del
tamaño objetivo de vivienda (Anexo I.5).
"""
from __future__ import annotations
from dataclasses import dataclass

from .config import Parametros
from .programa import util_maximo


EFICIENCIA_PLANTA = 0.72   # útil de viviendas / construida de la planta


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


def _round_half_up(x: float) -> int:
    return int(x + 0.5)


def calcular_capacidad(envolvente, params: Parametros,
                       eficiencia_planta: float = EFICIENCIA_PLANTA) -> Capacidad:
    parcela_area = envolvente.parcela.area
    urb = params.urbanismo
    n_plantas_solicitadas = max(1, len(envolvente.plantas) or params.programa.n_plantas)
    huella = envolvente.plantas[0].footprint.area if envolvente.plantas else parcela_area

    techo_max = urb.edificabilidad * parcela_area
    ocup_area = urb.ocupacion_maxima * parcela_area
    huella_efectiva = min(huella, ocup_area)

    n_plantas_edif_max = max(1, int(techo_max // huella_efectiva)) if huella_efectiva else 1
    n_plantas = max(1, min(n_plantas_solicitadas, n_plantas_edif_max))
    factor = ("altura (nº plantas)" if n_plantas_solicitadas <= n_plantas_edif_max
              else "edificabilidad")
    construida = huella_efectiva * n_plantas

    n_dorms = params.programa.n_dormitorios
    util_viv = util_maximo(n_dorms)
    util_planta = huella_efectiva * eficiencia_planta
    viv_pp = max(1, _round_half_up(util_planta / util_viv)) if util_viv else 1
    n_total = viv_pp * n_plantas

    return Capacidad(
        superficie_parcela_m2=round(parcela_area, 2),
        edificabilidad=urb.edificabilidad,
        ocupacion_maxima=urb.ocupacion_maxima,
        n_plantas_solicitadas=n_plantas_solicitadas,
        n_plantas_edificables=n_plantas,
        techo_max_m2=round(techo_max, 2),
        huella_m2=round(huella, 2),
        ocupacion_area_m2=round(ocup_area, 2),
        huella_efectiva_m2=round(huella_efectiva, 2),
        construida_prevista_m2=round(construida, 2),
        factor_limitante=factor,
        n_dormitorios=n_dorms,
        util_objetivo_viv_m2=round(util_viv, 2),
        util_planta_disponible_m2=round(util_planta, 2),
        viv_por_planta_objetivo=viv_pp,
        n_viviendas_objetivo=n_total,
    )
