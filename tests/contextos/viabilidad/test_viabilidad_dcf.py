"""Tests del andamiaje DCF (§2.9, Fases 1-2 hasta la costura `construir_flujos`).

Cubren solo lo spec-agnóstico: cómputo de métricas sobre una serie de flujos
conocida, comportamiento del stub (serie vacía → métricas neutras + avisos),
serialización tolerante y persistencia en el aggregate. El modelo financiero real
(`modelo_dcf.construir_flujos`) queda fuera hasta recibir la spec del financiero.
"""
from __future__ import annotations

import pytest

from app.contextos.viabilidad import (
    CalcularViabilidadDCF,
    DefinicionEscenario,
    Escenario,
    Financiacion,
    FlujoCaja,
    FuenteSuperficie,
    Operacion,
    ParametrosEconomicos,
    SupuestosDCF,
    asociar_a_proyecto,
    asociar_dcf_a_proyecto,
    estudio_dcf_a_dict,
    financiacion_a_dict,
    financiacion_desde_dict,
    financiacion_desde_proyecto,
    parametros_desde_proyecto,
    supuestos_dcf_a_dict,
    supuestos_dcf_desde_dict,
    supuestos_dcf_desde_proyecto,
)
from app.contextos.viabilidad.casos_uso import _metricas_escenario
from app.nucleo.modelo import Proyecto


# ── FlujoCaja: capital aportado / distribuido ───────────────────────────────
def test_flujo_caja_particiona_aportado_y_distribuido():
    flujo = FlujoCaja(neto=[-100.0, 60.0, -20.0, 90.0])
    assert flujo.capital_aportado == pytest.approx(120.0)   # 100 + 20
    assert flujo.capital_distribuido == pytest.approx(150.0)  # 60 + 90


# ── Métricas de un escenario sobre una serie conocida ───────────────────────
def test_metricas_escenario_serie_conocida():
    # -100 + 60/(1.1) + 60/(1.1)^2  ≈ 4.13 → VAN 4; TIR ≈ 13.07 %; payback ≈ 1.67.
    r = _metricas_escenario(Escenario.BASE, FlujoCaja(neto=[-100, 60, 60]), 0.10, [])
    assert r.van_eur == pytest.approx(4.0)
    assert r.tir == pytest.approx(0.1307, abs=1e-4)
    assert r.moic == pytest.approx(1.2)          # 120 / 100
    assert r.payback_anios == pytest.approx(1.67, abs=1e-2)
    assert r.capital_necesario_eur == pytest.approx(100.0)


def test_metricas_escenario_serie_vacia_es_neutra():
    r = _metricas_escenario(Escenario.ESTRES, FlujoCaja(neto=[]), 0.10, ["x"])
    assert r.van_eur == 0.0
    assert r.tir is None
    assert r.payback_anios is None
    assert r.moic == 0.0
    assert r.capital_necesario_eur == 0.0
    assert r.avisos == ["x"]


# ── Caso de uso con el stub (modelo aún sin definir) ────────────────────────
def test_dcf_stub_devuelve_tres_escenarios_no_disponible():
    supuestos = SupuestosDCF()  # horizonte 0, tres escenarios identidad
    parametros = ParametrosEconomicos(superficie_construida_m2=1000.0)  # override manual
    estudio = CalcularViabilidadDCF().ejecutar(supuestos, Financiacion(), parametros, None)

    assert estudio.disponible is False
    assert len(estudio.escenarios) == 3
    assert {e.escenario for e in estudio.escenarios} == set(Escenario)
    # Reutiliza la resolución de superficie del cálculo de margen.
    assert estudio.superficie_aplicada_m2 == 1000.0
    assert estudio.fuente_superficie == FuenteSuperficie.MANUAL
    # Avisos: horizonte sin definir (global) + modelo sin definir (por escenario).
    assert any("horizonte" in a.lower() for a in estudio.avisos)
    assert all(
        any("no está definido" in a.lower() for a in e.avisos) for e in estudio.escenarios
    )


def test_dcf_serializacion_estudio_es_json_amigable():
    estudio = CalcularViabilidadDCF().ejecutar(
        SupuestosDCF(), Financiacion(), ParametrosEconomicos(superficie_construida_m2=500.0), None
    )
    d = estudio_dcf_a_dict(estudio)
    assert d["disponible"] is False
    assert d["superficie_aplicada_m2"] == 500.0
    assert len(d["escenarios"]) == 3
    assert d["escenarios"][0]["escenario"] in {e.value for e in Escenario}
    assert d["precio_maximo_compra_eur"] is None


# ── Serialización tolerante: round-trip y defaults ──────────────────────────
def test_supuestos_dcf_roundtrip():
    s = SupuestosDCF(
        horizonte_anios=10,
        tasa_descuento_anual=0.09,
        tir_objetivo=0.15,
        escenarios=[
            DefinicionEscenario(Escenario.BASE),
            DefinicionEscenario(Escenario.ESTRES, factor_precio=0.85, factor_capex=1.15),
        ],
    )
    assert supuestos_dcf_desde_dict(supuestos_dcf_a_dict(s)) == s


def test_financiacion_roundtrip():
    f = Financiacion(ltv=0.6, tipo_interes_anual=0.05, plazo_anios=15, comision_apertura_pct=0.01)
    assert financiacion_desde_dict(financiacion_a_dict(f)) == f


def test_supuestos_dcf_desde_dict_invalido_cae_a_default():
    # horizonte no numérico y escenarios ausentes → defaults sin excepción.
    s = supuestos_dcf_desde_dict({"horizonte_anios": "no-es-numero"})
    assert s == SupuestosDCF()


# ── Persistencia en el aggregate ────────────────────────────────────────────
def test_persistencia_dcf_roundtrip_en_aggregate():
    proy = Proyecto(nombre="Test")
    supuestos = SupuestosDCF(horizonte_anios=8, tasa_descuento_anual=0.10)
    fin = Financiacion(ltv=0.5)
    params = ParametrosEconomicos(operacion=Operacion.RENTA)

    asociar_dcf_a_proyecto(supuestos, fin, params, proy)

    assert supuestos_dcf_desde_proyecto(proy) == supuestos
    assert financiacion_desde_proyecto(proy) == fin
    # Los parámetros de margen conviven en el mismo rincón.
    assert parametros_desde_proyecto(proy).operacion == Operacion.RENTA


def test_guardar_margen_preserva_dcf_existente():
    proy = Proyecto(nombre="Test")
    asociar_dcf_a_proyecto(SupuestosDCF(horizonte_anios=8), Financiacion(), ParametrosEconomicos(), proy)
    # Guardar solo los parámetros de margen no debe borrar el subdiccionario dcf.
    asociar_a_proyecto(ParametrosEconomicos(operacion=Operacion.RENTA), proy)

    assert supuestos_dcf_desde_proyecto(proy).horizonte_anios == 8
    assert parametros_desde_proyecto(proy).operacion == Operacion.RENTA
