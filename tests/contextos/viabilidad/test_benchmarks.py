"""Tests de benchmarks manuales (§2.9, Fase 5): serialización + persistencia."""
from __future__ import annotations

from app.contextos.viabilidad import (
    Benchmarks,
    Financiacion,
    ParametrosEconomicos,
    SupuestosDCF,
    asociar_dcf_a_proyecto,
    benchmarks_a_dict,
    benchmarks_desde_dict,
    benchmarks_desde_proyecto,
)
from app.nucleo.modelo import Proyecto


def test_benchmarks_roundtrip():
    b = Benchmarks(revpar_eur=85.0, adr_eur=120.0, yield_comparable=0.06, fuente="STR 2026")
    assert benchmarks_desde_dict(benchmarks_a_dict(b)) == b


def test_benchmarks_desde_dict_invalido_cae_a_default():
    assert benchmarks_desde_dict({"revpar_eur": "no-numero"}) == Benchmarks()
    assert benchmarks_desde_dict(None) == Benchmarks()


def test_benchmarks_persisten_en_el_aggregate():
    proy = Proyecto(nombre="Test")
    b = Benchmarks(revpar_eur=90.0, fuente="manual")
    asociar_dcf_a_proyecto(SupuestosDCF(), Financiacion(), ParametrosEconomicos(), proy, benchmarks=b)
    assert benchmarks_desde_proyecto(proy) == b


def test_guardar_dcf_sin_benchmarks_preserva_los_previos():
    proy = Proyecto(nombre="Test")
    b = Benchmarks(adr_eur=110.0, fuente="Idealista")
    asociar_dcf_a_proyecto(SupuestosDCF(), Financiacion(), ParametrosEconomicos(), proy, benchmarks=b)
    # Volver a guardar el DCF sin pasar benchmarks no debe borrarlos.
    asociar_dcf_a_proyecto(SupuestosDCF(horizonte_anios=5), Financiacion(), ParametrosEconomicos(), proy)
    assert benchmarks_desde_proyecto(proy) == b
