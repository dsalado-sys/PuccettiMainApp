"""§2.9 — Motor DCF: construcción de la serie de flujos de caja (all-equity).

**Estructura estándar y convencional, 1.ª iteración SIN DEUDA** (autorizada por el
arquitecto en ausencia de una spec del financiero). La *mecánica* es estándar; los
*números* (horizonte, periodo de obra, tasa, exit cap rate, deltas de escenario) son
entradas configurables que el financiero fija y **debe validar**. No hay cifras de
negocio quemadas: con los defaults neutros (0) el motor no construye flujos y lo avisa.

Mecánica (a validar por el financiero):
- **VENTA (promoción / build-to-sell)**: en t0 sale el coste de suelo; el CAPEX
  (construcción × (1+indirectos)) se reparte linealmente sobre `periodo_obra_anios`;
  el ingreso por venta (superficie × precio) entra al terminar la obra. Horizonte de
  la operación = periodo de obra.
- **RENTA (build-to-rent)**: en t0 sale el coste de suelo; el CAPEX se reparte sobre
  la obra; tras la obra entran las rentas netas anuales (superficie × precio·mes × 12
  × ocupación) hasta el horizonte; en el último año se suma el valor de salida =
  NOI estabilizado / `exit_cap_rate`.
- Sin financiación: todos los flujos son sobre **capital propio** (all-equity). El
  apalancamiento (LTV/tipo) es una iteración posterior — `financiacion` se acepta en
  la firma pero aún no se usa (se avisa si trae deuda).

Cada escenario aplica sus factores: `factor_precio` (precio de venta), `factor_ingreso`
(renta), `factor_capex` (coste de construcción). `factor_*` = 1.0 → igual que base.
"""
from __future__ import annotations

from typing import Any

from ._comun import sanear_trazable
from .dominio import (
    DefinicionEscenario,
    Financiacion,
    FlujoCaja,
    Operacion,
    ParametrosEconomicos,
    SupuestosDCF,
)


def construir_flujos(
    supuestos: SupuestosDCF,
    parametros: ParametrosEconomicos,
    superficie_m2: float,
    financiacion: Financiacion,
    definicion: DefinicionEscenario,
    datos_parcela: dict[str, Any] | None,
    avisos: list[str],
) -> FlujoCaja:
    """Serie de flujos de caja netos (all-equity) del escenario `definicion.escenario`.

    Devuelve `FlujoCaja` vacío (sin lanzar) si faltan datos para construirla (obra u
    horizonte sin definir), anotando el motivo en `avisos`. Rellena `FlujoCaja.detalle`
    con el desglose por concepto (suelo/capex/ingreso/salida) para el one-pager.
    """
    # 1.ª iteración: sin deuda. Si llega financiación, se avisa y se ignora.
    if financiacion.ltv and financiacion.ltv > 0:
        avisos.append(
            "La estructura de financiación (deuda) aún no se modela: cálculo "
            "all-equity (sobre capital propio)."
        )

    obra = int(sanear_trazable(supuestos.periodo_obra_anios, "El periodo de obra (años)", avisos))
    if obra <= 0:
        avisos.append("El periodo de obra no está definido (0 años): no se construyen flujos.")
        return FlujoCaja(neto=[])

    # Parámetros económicos saneados + factores del escenario.
    coste_unit = sanear_trazable(parametros.coste_construccion_eur_m2, "El coste de construcción (€/m²)", avisos)
    pct_indir = sanear_trazable(parametros.pct_costes_indirectos, "El % de costes indirectos", avisos)
    coste_suelo = sanear_trazable(parametros.coste_suelo_eur, "El coste del suelo (€)", avisos)
    precio = sanear_trazable(parametros.precio_eur_m2, "El precio (€/m²)", avisos)

    capex_total = superficie_m2 * coste_unit * float(definicion.factor_capex) * (1.0 + pct_indir)
    capex_por_anio = capex_total / obra

    if parametros.operacion == Operacion.VENTA:
        return _flujo_venta(
            obra, coste_suelo, capex_por_anio,
            ingreso_venta=superficie_m2 * precio * float(definicion.factor_precio),
        )

    # RENTA
    horizonte = int(sanear_trazable(supuestos.horizonte_anios, "El horizonte (años)", avisos))
    if horizonte <= obra:
        avisos.append(
            "En renta, el horizonte debe superar al periodo de obra para que haya años "
            "de explotación: no se construyen flujos."
        )
        return FlujoCaja(neto=[])
    ocupacion = sanear_trazable(parametros.ocupacion_anual_pct, "La ocupación anual", avisos, maximo=1.0)
    exit_cap = sanear_trazable(supuestos.exit_cap_rate, "El exit cap rate", avisos, maximo=1.0)
    renta_anual = superficie_m2 * precio * float(definicion.factor_ingreso) * 12.0 * ocupacion
    if exit_cap <= 0:
        avisos.append("Sin exit cap rate (> 0): no se calcula valor de salida del activo.")
        valor_salida = 0.0
    else:
        valor_salida = renta_anual / exit_cap
    return _flujo_renta(obra, horizonte, coste_suelo, capex_por_anio, renta_anual, valor_salida)


def _flujo_venta(
    obra: int,
    coste_suelo: float,
    capex_por_anio: float,
    *,
    ingreso_venta: float,
) -> FlujoCaja:
    """t0: −suelo. Años 1..obra: −CAPEX/año. Año obra: +ingreso de venta."""
    n = obra + 1
    suelo = [0.0] * n
    capex = [0.0] * n
    ingreso = [0.0] * n
    suelo[0] = -coste_suelo
    for t in range(1, obra + 1):
        capex[t] = -capex_por_anio
    ingreso[obra] = ingreso_venta
    neto = [suelo[t] + capex[t] + ingreso[t] for t in range(n)]
    return FlujoCaja(
        neto=neto,
        detalle={"suelo": suelo, "capex": capex, "ingreso_venta": ingreso},
    )


def _flujo_renta(
    obra: int,
    horizonte: int,
    coste_suelo: float,
    capex_por_anio: float,
    renta_anual: float,
    valor_salida: float,
) -> FlujoCaja:
    """t0: −suelo. Años 1..obra: −CAPEX/año. Años obra+1..horizonte: +renta anual.
    Año horizonte: += valor de salida."""
    n = horizonte + 1
    suelo = [0.0] * n
    capex = [0.0] * n
    rentas = [0.0] * n
    salida = [0.0] * n
    suelo[0] = -coste_suelo
    for t in range(1, obra + 1):
        capex[t] = -capex_por_anio
    for t in range(obra + 1, horizonte + 1):
        rentas[t] = renta_anual
    salida[horizonte] += valor_salida
    neto = [suelo[t] + capex[t] + rentas[t] + salida[t] for t in range(n)]
    return FlujoCaja(
        neto=neto,
        detalle={"suelo": suelo, "capex": capex, "renta": rentas, "valor_salida": salida},
    )
