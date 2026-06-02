"""§2.9 — Entidades del estudio de viabilidad económica.

Dos ejes de decisión del usuario:
- **Operación**: venta (precio €/m²) o renta (precio €/m²·mes con ocupación
  anual). Es excluyente.
- **Intervención**: obra nueva o rehabilitación. Cambia el coste por defecto y
  cómo se autocalcula la superficie a aplicar (parcela × edificabilidad para
  obra nueva, superficie construida existente del catastro para rehabilitación).

La fórmula básica es:
    ingresos = sup × precio                      (venta)
    ingresos = sup × precio × 12 × ocupación     (renta)
    costes   = sup × coste_constr × (1 + %indir) + coste_suelo
    margen   = ingresos − costes
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Operacion(str, Enum):
    VENTA = "venta"
    RENTA = "renta"


class Intervencion(str, Enum):
    OBRA_NUEVA = "obra_nueva"
    REHABILITACION = "rehabilitacion"


class FuenteSuperficie(str, Enum):
    MANUAL = "manual"
    CATASTRO_EXISTENTE = "catastro_existente"
    PARCELA_X_EDIFICABILIDAD = "parcela_x_edificabilidad"
    VACIO = "vacio"


# Defaults económicos para Sevilla 2026 — heredados del módulo
# Modulos/restricciones_app/restricciones/modelo.py:83-96.
PRECIO_VENTA_DEFAULT_EUR_M2 = 3200.0
PRECIO_RENTA_DEFAULT_EUR_M2_MES = 15.0
COSTE_DEFAULT_OBRA_NUEVA_EUR_M2 = 1400.0
COSTE_DEFAULT_REHABILITACION_EUR_M2 = 900.0
PCT_INDIRECTOS_DEFAULT = 0.18
OCUPACION_DEFAULT = 0.65
EDIFICABILIDAD_DEFAULT_M2T_M2S = 1.0


@dataclass
class ParametrosEconomicos:
    """Entradas configurables por el técnico o por el asociado financiero."""
    operacion: Operacion = Operacion.VENTA
    intervencion: Intervencion = Intervencion.OBRA_NUEVA
    precio_eur_m2: float = PRECIO_VENTA_DEFAULT_EUR_M2
    coste_construccion_eur_m2: float = COSTE_DEFAULT_OBRA_NUEVA_EUR_M2
    superficie_construida_m2: float = 0.0
    edificabilidad_m2t_m2s: float = EDIFICABILIDAD_DEFAULT_M2T_M2S
    coste_suelo_eur: float = 0.0
    pct_costes_indirectos: float = PCT_INDIRECTOS_DEFAULT
    ocupacion_anual_pct: float = OCUPACION_DEFAULT


@dataclass
class EstudioViabilidad:
    """Salida calculada del estudio. Todos los importes en euros redondeados."""
    parametros: ParametrosEconomicos
    superficie_aplicada_m2: float
    fuente_superficie: FuenteSuperficie
    ingresos_eur: float
    coste_construccion_eur: float
    coste_indirectos_eur: float
    coste_suelo_eur: float
    coste_total_eur: float
    margen_eur: float
    margen_pct: float
    avisos: list[str] = field(default_factory=list)
