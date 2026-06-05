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
    profundidad_max_sin_patio: float = 12.00

    # Porcentajes (iter. 4). Suma de los tres ≤ 90% (validado en capacidad).
    pct_muros: float = 20.0
    pct_circulacion: float = 8.0
    pct_nucleo: float = 5.0


@dataclass
class ParametrosUrbanisticos:
    """§2.3 — defaults para Sevilla casco.

    Iteración 4: `edificabilidad` renombrado a `coeficiente_edificabilidad`,
    `altura_planta` eliminado, retranqueos refactorizados a `fachada` y
    `linderos`.
    """
    coeficiente_edificabilidad: float = 2.5
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
    n_viviendas_por_planta: int = 1           # 0 = derivar automáticamente
    pct_unidades_adaptadas: float = 5.0       # DB SUA ≥5%


@dataclass
class Parametros:
    """Bundle global pasado al motor de geometría."""
    diseno: ParametrosDiseno = field(default_factory=ParametrosDiseno)
    urbanismo: ParametrosUrbanisticos = field(default_factory=ParametrosUrbanisticos)
    programa: ParametrosPrograma = field(default_factory=ParametrosPrograma)
    seed: Optional[int] = None


DEFAULT = Parametros()
