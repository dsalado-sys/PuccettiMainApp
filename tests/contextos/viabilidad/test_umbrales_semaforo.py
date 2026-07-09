"""Tests del semáforo de umbrales PR (§2.9, Fase 3): lógica pura sobre escalares."""
from __future__ import annotations

from app.contextos.viabilidad import (
    Estado,
    TipologiaPR,
    UmbralesPR,
    evaluar_umbrales,
    semaforo_global,
    umbrales_a_dict,
    umbrales_desde_dict,
)


# ── evaluar_umbrales ─────────────────────────────────────────────────────────
def test_tir_verde_o_rojo_segun_minimo_de_la_tipologia():
    u = UmbralesPR()  # BTR 12 %, hotelero 15 %, rehab 18 %
    assert evaluar_umbrales(u, TipologiaPR.BTR_RESIDENCIAL, tir=0.13)["tir"] == Estado.VERDE
    assert evaluar_umbrales(u, TipologiaPR.BTR_RESIDENCIAL, tir=0.11)["tir"] == Estado.ROJO
    # 13 % pasa en BTR pero NO en hotelero (necesita 15 %).
    assert evaluar_umbrales(u, TipologiaPR.HOTELERO, tir=0.13)["tir"] == Estado.ROJO
    assert evaluar_umbrales(u, TipologiaPR.REHAB_INTENSIVA, tir=0.19)["tir"] == Estado.VERDE


def test_yield_es_tri_estado():
    u = UmbralesPR()  # mínimo 5,5 % · objetivo 7 %
    assert evaluar_umbrales(u, TipologiaPR.BTR_RESIDENCIAL, yield_neto=0.05)["yield"] == Estado.ROJO
    assert evaluar_umbrales(u, TipologiaPR.BTR_RESIDENCIAL, yield_neto=0.06)["yield"] == Estado.AMBAR
    assert evaluar_umbrales(u, TipologiaPR.BTR_RESIDENCIAL, yield_neto=0.08)["yield"] == Estado.VERDE


def test_payback_y_capex_son_binarios_por_maximo():
    u = UmbralesPR()  # payback ≤ 18 años · capex ≤ 350.000 €/hab
    est = evaluar_umbrales(u, TipologiaPR.HOTELERO, payback_anios=10, capex_hab=300_000)
    assert est["payback"] == Estado.VERDE
    assert est["capex_hab"] == Estado.VERDE
    est2 = evaluar_umbrales(u, TipologiaPR.HOTELERO, payback_anios=20, capex_hab=400_000)
    assert est2["payback"] == Estado.ROJO
    assert est2["capex_hab"] == Estado.ROJO


def test_metrica_ausente_es_sin_dato():
    est = evaluar_umbrales(UmbralesPR(), TipologiaPR.BTR_RESIDENCIAL)  # nada informado
    assert set(est.values()) == {Estado.SIN_DATO}


# ── semaforo_global ──────────────────────────────────────────────────────────
def test_semaforo_global_toma_el_peor_estado():
    assert semaforo_global({"tir": Estado.VERDE, "yield": Estado.AMBAR}) == Estado.AMBAR
    assert semaforo_global({"tir": Estado.ROJO, "yield": Estado.VERDE}) == Estado.ROJO
    assert semaforo_global({"tir": Estado.VERDE, "payback": Estado.VERDE}) == Estado.VERDE


def test_semaforo_global_ignora_sin_dato():
    assert semaforo_global({"tir": Estado.VERDE, "yield": Estado.SIN_DATO}) == Estado.VERDE
    assert semaforo_global({"tir": Estado.SIN_DATO, "yield": Estado.SIN_DATO}) == Estado.SIN_DATO


# ── Serialización de umbrales ────────────────────────────────────────────────
def test_umbrales_roundtrip():
    u = UmbralesPR(tir_min_hotelero=0.16, yield_objetivo=0.08, capex_maximo_hab_eur=400_000.0)
    assert umbrales_desde_dict(umbrales_a_dict(u)) == u


def test_umbrales_desde_dict_invalido_cae_a_default():
    assert umbrales_desde_dict({"tir_min_hotelero": "no-numero"}) == UmbralesPR()
    assert umbrales_desde_dict(None) == UmbralesPR()
