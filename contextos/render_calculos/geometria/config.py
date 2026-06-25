"""Parámetros del motor de cálculo (§2.6 + §2.3).

Iteración 4: mirror de los cambios en `parametros.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParametrosDiseno:
    """§2.6 + Anexo II A2.x — parámetros de diseño interior.

    Iteración 4: tres porcentajes explícitos (`pct_muros`,
    `pct_circulacion`, `pct_nucleo`) controlan el reparto m² no-útil.
    """

    # Espesores (A2.4) — referencias para el render geométrico (DEPRECATED iter. 3)
    espesor_muro_fachada: float = 0.25
    espesor_muro_medianero: float = 0.25
    espesor_separacion_unidades: float = 0.20
    espesor_tabiqueria: float = 0.10

    # Anchos mínimos (A2.1, A2.2, A2.3 + DB SUA)
    ancho_min_pasillo_comun: float = 1.20
    ancho_min_pasillo_vivienda: float = 1.00
    diametro_min_vestibulo: float = 1.50
    radio_apertura_puerta: float = 0.80

    # Patios interiores (A2.5)
    luz_recta_patio_min: float = 3.00
    area_patio_min: float = 12.00

    # Porcentajes. Suma ≤ 90% por planta (validado en capacidad).
    pct_muros: float = 20.0
    # Tabiquería interior de las unidades (cálculo de unidad): se descuenta del útil
    # destinado a viviendas, no de la huella. Default 0 = sin tabiquería reservada.
    pct_muros_interior: float = 0.0
    pct_circulacion_pb: float = 8.0      # % circulación en planta baja
    pct_circulacion_tipo: float = 8.0    # % circulación en planta tipo / ático
    pct_nucleo: float = 5.0
    pct_muros_normativo: float = 20.0    # referencia normativa para "Muros estimado"


@dataclass
class ParametrosUrbanisticos:
    """§2.3 — defaults para Sevilla casco.

    Iteración 4: `edificabilidad` renombrado a `coeficiente_edificabilidad`,
    `altura_planta` eliminado, retranqueos refactorizados a `fachada` y
    `linderos`.
    """
    coeficiente_edificabilidad: float = 2.5
    usar_coeficiente_edificabilidad: bool = True
    ocupacion_maxima: float = 1.00
    n_plantas_max: int = 3
    retranqueo_fachada: float = 0.0
    retranqueo_linderos: float = 0.0
    # Ático y sótano (iter. 3).
    tiene_atico: bool = False
    retranqueo_atico: float = 3.0
    atico_computa_edificabilidad: bool = False
    tiene_sotano: bool = False
    sotano_computa_edificabilidad: bool = False


@dataclass
class ParametrosPrograma:
    """Programa arquitectónico (uso + tipología + accesibilidad)."""
    uso: str = "vivienda"                     # "vivienda" | "hotelero" | "apartamentos_turisticos"
    categoria: str = "libre"                  # libre/VPO (vivienda); 1*-5* (hotel); 1L-4L (apts.)
    n_dormitorios: int = 2                    # 0 = estudio
    salon_cocina_open: bool = False
    n_plantas: int = 3
    tipologias_extra: list[int] = field(default_factory=list)  # nº dormitorios adicionales
    pct_local_pb: float = 0.0                 # % útil PB destinado a local no residencial
    pct_otros_pb: float = 0.0                 # % útil PB destinado a otros usos
    pct_usos_comunes_pb: float = 0.0          # % útil PB destinado a usos comunes (AT / hoteles)


@dataclass
class Parametros:
    """Bundle global pasado al motor de geometría."""
    diseno: ParametrosDiseno = field(default_factory=ParametrosDiseno)
    urbanismo: ParametrosUrbanisticos = field(default_factory=ParametrosUrbanisticos)
    programa: ParametrosPrograma = field(default_factory=ParametrosPrograma)
    seed: Optional[int] = None


DEFAULT = Parametros()
