"""§2.4–2.7 — Entidades del módulo Render y cálculos.

Dataclasses puras + enums. Sin frameworks ni I/O. La capa de casos de uso las
construye combinando el motor geométrico (`geometria/`) con los parámetros del
proyecto y la normativa municipal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class UsoEdificio(str, Enum):
    """§2.5 — usos contemplados. MVP: solo VIVIENDA está totalmente implementado."""
    VIVIENDA = "vivienda"
    HOTELERO = "hotelero"
    APARTAMENTOS_TURISTICOS = "apartamentos_turisticos"


class CategoriaVivienda(str, Enum):
    """Anexo I.5 — tipologías de vivienda por número de dormitorios."""
    ESTUDIO = "estudio"
    UNO_D = "1d"
    DOS_D = "2d"
    TRES_D = "3d"
    CUATRO_MAS_D = "4d+"


CATEGORIA_A_NUM_DORMS = {
    CategoriaVivienda.ESTUDIO: 0,
    CategoriaVivienda.UNO_D: 1,
    CategoriaVivienda.DOS_D: 2,
    CategoriaVivienda.TRES_D: 3,
    CategoriaVivienda.CUATRO_MAS_D: 4,
}


class TipologiaApartamento(str, Enum):
    """Anexo I.4 — tipologías de apartamento turístico por nº de dormitorios."""
    ESTUDIO = "estudio"
    UNO_D = "1d"
    DOS_D = "2d"
    TRES_D = "3d"


class CategoriaApartamentos(str, Enum):
    """Decreto 194/2010 — clasificación de apartamentos turísticos por llaves."""
    UNA_LLAVE = "1L"
    DOS_LLAVES = "2L"
    TRES_LLAVES = "3L"
    CUATRO_LLAVES = "4L"


TIPOLOGIA_APT_A_NUM_DORMS = {
    TipologiaApartamento.ESTUDIO: 0,
    TipologiaApartamento.UNO_D: 1,
    TipologiaApartamento.DOS_D: 2,
    TipologiaApartamento.TRES_D: 3,
}


NivelAlerta = Literal["info", "aviso", "incumplimiento"]


@dataclass(frozen=True)
class Alerta:
    """req. 7 — incumplimiento o aviso normativo."""
    nivel: NivelAlerta
    regla: str                    # "A2.5", "A2.4", "Anexo I.5", "PGOU"...
    mensaje: str
    elemento: str | None = None   # id de unidad/patio si aplica


@dataclass
class IndicadoresDiseno:
    """req. 15 — compacidad, orientación dominante, proporción de huecos."""
    compacidad: float                 # 4·π·area / perimetro² (1 = círculo perfecto)
    proporcion_huecos: float          # area_huecos / area_fachada (0..1)
    orientacion_dominante: str        # cardinal de la fachada más larga
    long_total_fachadas_m: float
    long_total_medianeras_m: float
    n_fachadas: int
    n_medianeras: int
    orientaciones_fachadas: list[str] = field(default_factory=list)


@dataclass
class ResumenEnvolvente:
    """Resumen del cálculo de envolvente (§2.4) — usado por `/preview`."""
    huella_m2: float
    n_plantas: int
    altura_planta_m: float
    edificabilidad_max_m2: float
    edificabilidad_consumida_m2: float
    n_viviendas_objetivo: int
    factor_limitante: str
    bbox_world: tuple[float, float, float, float]
