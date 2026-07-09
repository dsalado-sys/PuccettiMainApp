"""Tests de las primitivas financieras universales (§2.9, finanzas.py)."""
from __future__ import annotations

import pytest

from app.contextos.viabilidad.finanzas import moic, payback, tir, van


# ── VAN ────────────────────────────────────────────────────────────────────
def test_van_a_tasa_cero_es_suma_simple():
    assert van(0.0, [-100, 110]) == pytest.approx(10.0)


def test_van_descuenta_por_periodo():
    # -100 hoy + 110 dentro de un periodo, al 10 % → VAN ≈ 0.
    assert van(0.10, [-100, 110]) == pytest.approx(0.0, abs=1e-9)
    # 100 dentro de 2 periodos al 10 %.
    assert van(0.10, [0, 0, 121]) == pytest.approx(100.0, abs=1e-9)


def test_van_tasa_imposible_lanza():
    with pytest.raises(ValueError):
        van(-1.0, [-100, 110])


# ── TIR ────────────────────────────────────────────────────────────────────
def test_tir_flujo_simple_es_el_10_por_ciento():
    assert tir([-100, 110]) == pytest.approx(0.10, abs=1e-6)


def test_tir_multiperiodo_conocida():
    # -100 + 60/(1+r) + 60/(1+r)^2 = 0  →  r ≈ 0.130662.
    assert tir([-100, 60, 60]) == pytest.approx(0.130662, abs=1e-5)


def test_tir_es_consistente_con_van():
    flujos = [-500, 120, 130, 140, 260]
    r = tir(flujos)
    assert r is not None
    assert van(r, flujos) == pytest.approx(0.0, abs=1e-4)


@pytest.mark.parametrize(
    "flujos",
    [
        [],               # serie vacía
        [100, 50, 25],    # todos positivos: sin cambio de signo
        [-100, -50, -25], # todos negativos: sin cambio de signo
    ],
)
def test_tir_sin_raiz_devuelve_none(flujos):
    assert tir(flujos) is None


# ── MOIC ───────────────────────────────────────────────────────────────────
def test_moic_basico():
    assert moic(100, 130) == pytest.approx(1.30)


def test_moic_toma_magnitud_del_aportado():
    # Aportado firmado en negativo: se usa su magnitud.
    assert moic(-200, 300) == pytest.approx(1.50)


def test_moic_sin_capital_aportado_es_cero():
    assert moic(0, 50) == 0.0


# ── Payback ────────────────────────────────────────────────────────────────
def test_payback_fraccional_interpola_dentro_del_periodo():
    assert payback([-100, 60, 60]) == pytest.approx(1.0 + 40.0 / 60.0)


def test_payback_cruce_exacto_en_frontera_de_periodo():
    assert payback([-100, 50, 50, 50]) == pytest.approx(2.0)


def test_payback_nunca_recupera_devuelve_none():
    assert payback([-100, 10, 10]) is None


def test_payback_ya_positivo_en_t0_es_cero():
    assert payback([50, -10, -10]) == 0.0
