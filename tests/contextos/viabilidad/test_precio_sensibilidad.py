"""Tests de Fase 4: precio máximo de compra + análisis de sensibilidad (§2.9)."""
from __future__ import annotations

import pytest

from app.contextos.viabilidad import (
    CalcularViabilidadDCF,
    Escenario,
    Financiacion,
    Operacion,
    ParametrosEconomicos,
    SupuestosDCF,
    analizar_sensibilidad,
    precio_maximo_compra,
)


def _venta(coste_suelo: float = 0.0) -> ParametrosEconomicos:
    return ParametrosEconomicos(
        operacion=Operacion.VENTA,
        superficie_construida_m2=1000.0,
        precio_eur_m2=3000.0,
        coste_construccion_eur_m2=1000.0,
        pct_costes_indirectos=0.0,
        coste_suelo_eur=coste_suelo,
    )


# ── Precio máximo de compra ─────────────────────────────────────────────────
def test_precio_maximo_compra_resuelve_la_tir_objetivo():
    # obra 1 año: neto = [-suelo, -1.000.000 + 3.000.000] = [-suelo, 2.000.000].
    # TIR = 2.000.000/suelo − 1 = 0,20  →  suelo = 2.000.000/1,20 = 1.666.667.
    supuestos = SupuestosDCF(periodo_obra_anios=1, tasa_descuento_anual=0.0, tir_objetivo=0.20)
    precio = precio_maximo_compra(supuestos, Financiacion(), _venta(), None)
    assert precio == pytest.approx(1_666_667, rel=0.01)


def test_precio_maximo_baja_si_sube_la_tir_objetivo():
    s12 = SupuestosDCF(periodo_obra_anios=1, tir_objetivo=0.12)
    s25 = SupuestosDCF(periodo_obra_anios=1, tir_objetivo=0.25)
    p12 = precio_maximo_compra(s12, Financiacion(), _venta(), None)
    p25 = precio_maximo_compra(s25, Financiacion(), _venta(), None)
    assert p12 is not None and p25 is not None
    assert p25 < p12  # exigir más rentabilidad → pagar menos por el suelo


def test_precio_maximo_sin_objetivo_o_sin_timing_es_none():
    # Sin TIR objetivo.
    assert precio_maximo_compra(SupuestosDCF(periodo_obra_anios=1), Financiacion(), _venta(), None) is None
    # Con objetivo pero sin timing (motor no disponible).
    assert precio_maximo_compra(SupuestosDCF(tir_objetivo=0.15), Financiacion(), _venta(), None) is None


def test_precio_maximo_verifica_umbral_en_la_frontera():
    supuestos = SupuestosDCF(periodo_obra_anios=1, tir_objetivo=0.20)
    precio = precio_maximo_compra(supuestos, Financiacion(), _venta(), None)
    uc = CalcularViabilidadDCF()

    def tir_a(suelo):
        est = uc.ejecutar(supuestos, Financiacion(), _venta(suelo), None)
        return next(e for e in est.escenarios if e.escenario == Escenario.BASE).tir

    assert tir_a(precio) >= 0.20                 # al precio máximo, se cumple
    assert tir_a(precio * 1.05) < 0.20           # pagando un 5 % más, ya no


# ── Análisis de sensibilidad ────────────────────────────────────────────────
def test_sensibilidad_direcciones_correctas():
    supuestos = SupuestosDCF(periodo_obra_anios=1, tasa_descuento_anual=0.0)
    res = analizar_sensibilidad(supuestos, Financiacion(), _venta(coste_suelo=500_000.0), None)

    assert res["base_tir"] is not None
    drivers = {d["driver"]: d for d in res["drivers"]}
    assert set(drivers) == {"precio_compra", "capex", "ingreso"}

    base = res["base_tir"]
    # Subir el precio de compra o el CAPEX baja la TIR; subir el ingreso la sube.
    assert drivers["precio_compra"]["tir_arriba"] < base < drivers["precio_compra"]["tir_abajo"]
    assert drivers["capex"]["tir_arriba"] < base < drivers["capex"]["tir_abajo"]
    assert drivers["ingreso"]["tir_arriba"] > base > drivers["ingreso"]["tir_abajo"]
