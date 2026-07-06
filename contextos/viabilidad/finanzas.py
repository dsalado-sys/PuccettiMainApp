"""§2.9 — Primitivas financieras universales (VAN, TIR, MOIC, payback).

Matemática pura y **agnóstica del modelo de negocio**: opera sobre una serie de
flujos de caja `flujos` donde `flujos[t]` es el flujo neto al final del periodo `t`
(convención `flujos[0]` = momento 0, normalmente el desembolso inicial, negativo).

No decide *cómo* se construyen esos flujos (eso es la spec DCF del financiero,
Fases 1-2): solo los descuenta y calcula métricas. Sin dependencias externas —
la TIR se resuelve por bisección en Python puro para no arrastrar numpy/scipy.
"""
from __future__ import annotations

from collections.abc import Sequence

# Límites del bracket de búsqueda de la TIR: de −99,99 % a +1000 % (ampliable).
_TIR_MIN = -0.9999
_TIR_MAX_INICIAL = 10.0
_TIR_MAX_ABS = 1000.0


def van(tasa: float, flujos: Sequence[float]) -> float:
    """Valor Actual Neto: suma de los flujos descontados a `tasa` por periodo.

    `van(0, flujos)` == suma simple de los flujos (sin descontar).
    Precondición: `tasa > -1` (una tasa de −100 % o inferior no tiene sentido
    financiero); el caso de uso DCF sanea la tasa antes de llamar aquí.
    """
    factor = 1.0 + float(tasa)
    if factor <= 0.0:
        raise ValueError("La tasa de descuento debe ser mayor que -100 %.")
    return sum(float(cf) / factor ** t for t, cf in enumerate(flujos))


def tir(
    flujos: Sequence[float],
    *,
    tolerancia: float = 1e-7,
    max_iter: int = 200,
) -> float | None:
    """Tasa Interna de Retorno: tasa que hace `van(tir, flujos) == 0`.

    Devuelve `None` (no lanza) cuando la TIR no está definida: serie vacía, o sin
    cambio de signo en los flujos (todos ≥ 0 o todos ≤ 0), o sin raíz localizable
    dentro del rango de búsqueda. Resolución por bisección sobre un bracket con
    cambio de signo — robusta para flujos convencionales (un desembolso seguido de
    retornos)."""
    if not flujos:
        return None
    if not (any(float(f) < 0 for f in flujos) and any(float(f) > 0 for f in flujos)):
        return None

    lo, hi = _TIR_MIN, _TIR_MAX_INICIAL
    v_lo = van(lo, flujos)
    v_hi = van(hi, flujos)
    # Amplía el extremo superior duplicando hasta encontrar cambio de signo.
    while v_lo * v_hi > 0 and hi < _TIR_MAX_ABS:
        hi = min(hi * 2.0, _TIR_MAX_ABS)
        v_hi = van(hi, flujos)
    if v_lo * v_hi > 0:
        return None  # sin cambio de signo en el rango: no hay TIR localizable

    for _ in range(max_iter):
        medio = (lo + hi) / 2.0
        v_medio = van(medio, flujos)
        if abs(v_medio) < tolerancia:
            return medio
        if v_lo * v_medio < 0:
            hi, v_hi = medio, v_medio
        else:
            lo, v_lo = medio, v_medio
    return (lo + hi) / 2.0


def moic(capital_aportado: float, capital_distribuido: float) -> float:
    """Multiple on Invested Capital: capital distribuido / capital aportado.

    Ambos en magnitud positiva (aportado = suma de desembolsos; distribuido = suma
    de retornos). Devuelve 0.0 si no hay capital aportado (no lanza)."""
    aportado = abs(float(capital_aportado))
    if aportado == 0.0:
        return 0.0
    return float(capital_distribuido) / aportado


def payback(flujos: Sequence[float]) -> float | None:
    """Periodo de recuperación (fraccional) del flujo de caja acumulado.

    Nº de periodos hasta que el acumulado pasa a ser ≥ 0, interpolando linealmente
    dentro del periodo del cruce. `None` si nunca se recupera. Ej.:
    `payback([-100, 60, 60])` ≈ 1.667; `payback([-100, 50, 50, 50])` == 2.0."""
    acumulado = 0.0
    for t, cf in enumerate(flujos):
        anterior = acumulado
        acumulado += float(cf)
        if acumulado >= 0.0:
            if t == 0:
                return 0.0
            paso = acumulado - anterior
            if paso == 0.0:
                return float(t)
            return (t - 1) + (-anterior / paso)
    return None
