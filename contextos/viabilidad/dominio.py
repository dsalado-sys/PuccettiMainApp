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


# ── Modelo DCF multi-periodo (Fases 1-2) ────────────────────────────────────
# NOTA: los defaults son NEUTROS a propósito (horizonte/tasa/LTV a 0, factores de
# escenario a 1.0 = sin perturbación). No representan una recomendación de negocio:
# los valores reales los fija la especificación DCF del financiero. Mientras no
# llegue, el motor es ejecutable pero devuelve una serie de flujos vacía (ver
# `modelo_dcf.construir_flujos`).

class Escenario(str, Enum):
    BASE = "base"
    OPTIMISTA = "optimista"
    ESTRES = "estres"


@dataclass
class DefinicionEscenario:
    """Perturbación de las variables clave para un escenario. Factor 1.0 = igual
    que base (sin cambio). Las magnitudes reales (p. ej. precio −15 % en estrés)
    las fija la spec del financiero — aquí solo vive la estructura."""
    escenario: Escenario = Escenario.BASE
    factor_precio: float = 1.0
    factor_capex: float = 1.0
    factor_ingreso: float = 1.0  # RevPAR / renta


def _escenarios_por_defecto() -> list[DefinicionEscenario]:
    return [DefinicionEscenario(escenario=e) for e in Escenario]


@dataclass
class SupuestosDCF:
    """Entradas del modelo DCF (estructura estándar, all-equity — 1.ª iteración).

    Todos los campos son configurables por el financiero. Los defaults son NEUTROS
    (0 = sin definir): con ellos el motor no construye flujos y lo avisa, en vez de
    inventar un timing. `periodo_obra_anios` y `exit_cap_rate` los introduce el
    financiero por pantalla; la financiación (deuda) llega en una iteración posterior.
    """
    horizonte_anios: int = 0           # total (obra + explotación en renta); 0 = sin definir
    periodo_obra_anios: int = 0        # años de obra sobre los que se reparte el CAPEX; 0 = sin definir
    tasa_descuento_anual: float = 0.0  # 0 = sin descuento (VAN == suma simple)
    exit_cap_rate: float = 0.0         # solo renta: valor de salida = NOI / exit_cap_rate; 0 = sin salida
    tir_objetivo: float = 0.0          # para el precio máximo de compra (Fase 4)
    escenarios: list[DefinicionEscenario] = field(default_factory=_escenarios_por_defecto)


@dataclass
class Financiacion:
    """Estructura de financiación. Default all-equity (sin deuda): LTV 0. Los
    términos reales (tipo, plazo, comisiones) los fija la spec."""
    ltv: float = 0.0                 # loan-to-value 0..1
    tipo_interes_anual: float = 0.0
    plazo_anios: int = 0
    comision_apertura_pct: float = 0.0


@dataclass
class FlujoCaja:
    """Serie de flujos de caja netos por periodo. `neto[0]` = momento 0 (t0).
    Data holder puro: las métricas (VAN/TIR/payback) se calculan en el caso de uso
    con `finanzas.py`. `detalle` guarda opcionalmente el desglose por concepto para
    el one-pager (Fase 5)."""
    neto: list[float] = field(default_factory=list)
    detalle: dict[str, list[float]] = field(default_factory=dict)

    @property
    def capital_aportado(self) -> float:
        """Suma (en magnitud) de los flujos negativos (desembolsos)."""
        return -sum(f for f in self.neto if f < 0)

    @property
    def capital_distribuido(self) -> float:
        """Suma de los flujos positivos (retornos)."""
        return sum(f for f in self.neto if f > 0)


@dataclass
class ResultadoEscenario:
    """Métricas de un escenario, calculadas sobre su `FlujoCaja`."""
    escenario: Escenario
    van_eur: float
    tir: float | None
    moic: float
    payback_anios: float | None
    capital_necesario_eur: float
    flujo: FlujoCaja
    avisos: list[str] = field(default_factory=list)


@dataclass
class EstudioViabilidadDCF:
    """Salida agregada del estudio DCF: los tres escenarios + precio máximo de
    compra. `disponible` es False mientras `construir_flujos` sea un stub (sin spec):
    permite a la UI distinguir 'aún no calculable' de 'calculado a cero'."""
    supuestos: SupuestosDCF
    financiacion: Financiacion
    superficie_aplicada_m2: float
    fuente_superficie: FuenteSuperficie
    escenarios: list[ResultadoEscenario] = field(default_factory=list)
    precio_maximo_compra_eur: float | None = None
    disponible: bool = False
    avisos: list[str] = field(default_factory=list)


# ── Umbrales internos PR + semáforo (Fase 3) ────────────────────────────────
# Los defaults reproducen la tabla del CLAUDE.md de este contexto (umbrales internos
# PR), que el financiero confirmó sembrar como configuración editable. NO son cifras
# inventadas: provienen de esa especificación. Se guardan en BBDD y son editables por
# el financiero — cambiarlas es decisión suya, no del código.
TIR_MIN_BTR_RESIDENCIAL_DEFAULT = 0.12
TIR_MIN_HOTELERO_DEFAULT = 0.15
TIR_MIN_REHAB_INTENSIVA_DEFAULT = 0.18
YIELD_NETO_MINIMO_DEFAULT = 0.055
YIELD_OBJETIVO_DEFAULT = 0.07
PAYBACK_MAXIMO_ANIOS_DEFAULT = 18.0
CAPEX_MAXIMO_HAB_EUR_DEFAULT = 350_000.0


class TipologiaPR(str, Enum):
    """Tipología para elegir la TIR mínima aplicable (según la tabla PR)."""
    BTR_RESIDENCIAL = "btr_residencial"
    HOTELERO = "hotelero"
    REHAB_INTENSIVA = "rehab_intensiva"


class Estado(str, Enum):
    """Color del semáforo por métrica."""
    VERDE = "verde"
    AMBAR = "ambar"
    ROJO = "rojo"
    SIN_DATO = "sin_dato"


@dataclass
class UmbralesPR:
    """Umbrales internos PR (config editable, persistida). TIR mínima por tipología +
    yield mín./objetivo, payback máximo y CAPEX máximo por habitación (globales)."""
    tir_min_btr_residencial: float = TIR_MIN_BTR_RESIDENCIAL_DEFAULT
    tir_min_hotelero: float = TIR_MIN_HOTELERO_DEFAULT
    tir_min_rehab_intensiva: float = TIR_MIN_REHAB_INTENSIVA_DEFAULT
    yield_neto_minimo: float = YIELD_NETO_MINIMO_DEFAULT
    yield_objetivo: float = YIELD_OBJETIVO_DEFAULT
    payback_maximo_anios: float = PAYBACK_MAXIMO_ANIOS_DEFAULT
    capex_maximo_hab_eur: float = CAPEX_MAXIMO_HAB_EUR_DEFAULT

    def tir_minima(self, tipologia: TipologiaPR) -> float:
        return {
            TipologiaPR.BTR_RESIDENCIAL: self.tir_min_btr_residencial,
            TipologiaPR.HOTELERO: self.tir_min_hotelero,
            TipologiaPR.REHAB_INTENSIVA: self.tir_min_rehab_intensiva,
        }[tipologia]


# ── Benchmarks de mercado (Fase 5) ──────────────────────────────────────────
@dataclass
class Benchmarks:
    """Comparables de mercado (RevPAR/ADR/yield). 1.ª iteración: **entrada manual**
    del técnico — aún no hay fuente automática (librería PR / STR / Idealista). Se
    guardan en el aggregate. `fuente` documenta su procedencia. Defaults neutros (0)
    = sin comparable introducido."""
    revpar_eur: float = 0.0
    adr_eur: float = 0.0
    yield_comparable: float = 0.0
    fuente: str = ""
