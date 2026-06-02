"""§2.9 — Estudio de viabilidad económica básica.

Contexto autónomo: el dominio expone parámetros económicos y el cálculo del
estudio (ingresos − costes = margen). Los datos se persisten en
`proyecto.datos(ModuloPuccetti.VIABILIDAD)`; no requiere repositorio propio.
"""
from .dominio import (
    COSTE_DEFAULT_OBRA_NUEVA_EUR_M2,
    COSTE_DEFAULT_REHABILITACION_EUR_M2,
    EstudioViabilidad,
    FuenteSuperficie,
    Intervencion,
    Operacion,
    ParametrosEconomicos,
)
from .casos_uso import (
    CalcularViabilidad,
    asociar_a_proyecto,
    estudio_a_dict,
    parametros_a_dict,
    parametros_desde_dict,
    parametros_desde_proyecto,
)

__all__ = [
    "COSTE_DEFAULT_OBRA_NUEVA_EUR_M2",
    "COSTE_DEFAULT_REHABILITACION_EUR_M2",
    "CalcularViabilidad",
    "EstudioViabilidad",
    "FuenteSuperficie",
    "Intervencion",
    "Operacion",
    "ParametrosEconomicos",
    "asociar_a_proyecto",
    "estudio_a_dict",
    "parametros_a_dict",
    "parametros_desde_dict",
    "parametros_desde_proyecto",
]
