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
    """§2.5 — usos contemplados (cálculo matemático)."""
    VIVIENDA = "vivienda"                              # Anexo I.5
    HOTELERO = "hotelero"                              # Anexo I.1
    APARTAMENTOS_TURISTICOS = "apartamentos_turisticos"  # Anexo I.3 / I.4
    HOTEL_APARTAMENTO = "hotel_apartamento"            # Anexo I.2


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
    """Anexo I.2/I.3/I.4 — tipologías de apartamento turístico y hotel-apartamento.

    Salvo la vivienda (que va por nº de dormitorios), apartamentos turísticos y
    hoteles-apartamento se clasifican por la OCUPACIÓN del dormitorio
    (individual/doble/triple/cuádruple), más el estudio.
    """
    ESTUDIO = "estudio"
    INDIVIDUAL = "individual"
    DOBLE = "doble"
    TRIPLE = "triple"
    CUADRUPLE = "cuadruple"


class CategoriaApartamentos(str, Enum):
    """Decreto 194/2010 — clasificación de apartamentos turísticos por llaves."""
    UNA_LLAVE = "1L"
    DOS_LLAVES = "2L"
    TRES_LLAVES = "3L"
    CUATRO_LLAVES = "4L"


TIPOLOGIA_APT_A_NUM_DORMS = {
    TipologiaApartamento.ESTUDIO: 0,
    TipologiaApartamento.INDIVIDUAL: 1,
    TipologiaApartamento.DOBLE: 1,
    TipologiaApartamento.TRIPLE: 1,
    TipologiaApartamento.CUADRUPLE: 1,
}

# Plazas (ocupación) por tipología de apartamento / hotel-apartamento.
TIPOLOGIA_APT_A_PLAZAS = {
    TipologiaApartamento.ESTUDIO: 2,
    TipologiaApartamento.INDIVIDUAL: 1,
    TipologiaApartamento.DOBLE: 2,
    TipologiaApartamento.TRIPLE: 3,
    TipologiaApartamento.CUADRUPLE: 4,
}


class GrupoApartamentos(str, Enum):
    """Decreto 194/2010 — grupo del apartamento turístico.

    `edificios` = grupo "edificios / complejos" (Anexo I.3, admite 1L-4L).
    `conjuntos` = grupo "conjuntos" (Anexo I.4, solo 1L/2L, mínimos menores).
    """
    EDIFICIOS = "edificios"
    CONJUNTOS = "conjuntos"


class CategoriaHotelApartamento(str, Enum):
    """Anexo I.2 — Hoteles-Apartamento por número de estrellas."""
    CINCO_E = "5E"
    CUATRO_E = "4E"
    TRES_E = "3E"
    DOS_E = "2E"
    UNA_E = "1E"


class CategoriaHotelero(str, Enum):
    """Anexo I.1 — establecimientos hoteleros por tipo y categoría.

    Hotel y hostal llevan estrellas; pensión y albergue no.
    """
    HOTEL_5 = "hotel_5"
    HOTEL_4 = "hotel_4"
    HOTEL_3 = "hotel_3"
    HOTEL_2 = "hotel_2"
    HOTEL_1 = "hotel_1"
    HOSTAL_2 = "hostal_2"
    HOSTAL_1 = "hostal_1"
    PENSION = "pension"
    ALBERGUE = "albergue"


class TipologiaHabitacion(str, Enum):
    """Anexo I.1 — tipos de habitación (unidad de alojamiento hotelera)."""
    INDIVIDUAL = "individual"
    DOBLE = "doble"
    TRIPLE = "triple"
    CUADRUPLE = "cuadruple"
    MULTIPLE = "multiple"          # solo albergue


# Plazas (camas) por tipología de habitación: escala las áreas sociales por
# plaza (albergue) y decide el 2º baño obligatorio (>5 usuarios) en A1.4.
TIPOLOGIA_HABITACION_A_PLAZAS = {
    TipologiaHabitacion.INDIVIDUAL: 1,
    TipologiaHabitacion.DOBLE: 2,
    TipologiaHabitacion.TRIPLE: 3,
    TipologiaHabitacion.CUADRUPLE: 4,
    TipologiaHabitacion.MULTIPLE: 6,
}

# Hotel-apartamento comparte el espacio de tipologías del apartamento turístico.
TIPOLOGIA_HAP_A_NUM_DORMS = TIPOLOGIA_APT_A_NUM_DORMS


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
    edificabilidad_max_m2: float
    edificabilidad_consumida_m2: float
    n_viviendas_objetivo: int
    factor_limitante: str
    bbox_world: tuple[float, float, float, float]
