"""Tests del caso de uso CalcularViabilidad (§2.9)."""
from __future__ import annotations

import pytest

from app.contextos.viabilidad import (
    CalcularViabilidad,
    FuenteSuperficie,
    Intervencion,
    Operacion,
    ParametrosEconomicos,
    parametros_a_dict,
    parametros_desde_dict,
)


@pytest.fixture
def uc() -> CalcularViabilidad:
    return CalcularViabilidad()


def _parcela(sup_m2: float = 500.0, construida_existente_m2: float = 0.0) -> dict:
    return {
        "referencia_catastral": "TEST0000000001",
        "superficie_m2": sup_m2,
        "agregados": {
            "num_referencias": 1,
            "suma_superficie_construida_m2": construida_existente_m2,
            "edificabilidad_m2t_m2s": construida_existente_m2 / sup_m2 if sup_m2 else 0.0,
            "num_viviendas": 0,
            "densidad_viviendas_viv_ha": 0.0,
        },
    }


# ── Venta · Obra nueva ─────────────────────────────────────────────────────
def test_venta_obra_nueva_con_parcela_calcula_ingresos_y_margen(uc):
    parametros = ParametrosEconomicos(
        operacion=Operacion.VENTA,
        intervencion=Intervencion.OBRA_NUEVA,
        precio_eur_m2=3000.0,
        coste_construccion_eur_m2=1400.0,
        edificabilidad_m2t_m2s=2.0,
        pct_costes_indirectos=0.0,  # aisla la fórmula básica
        coste_suelo_eur=0.0,
    )
    estudio = uc.ejecutar(parametros, _parcela(sup_m2=500.0))

    assert estudio.fuente_superficie == FuenteSuperficie.PARCELA_X_EDIFICABILIDAD
    assert estudio.superficie_aplicada_m2 == pytest.approx(1000.0)
    assert estudio.ingresos_eur == pytest.approx(3_000_000.0)
    assert estudio.coste_construccion_eur == pytest.approx(1_400_000.0)
    assert estudio.coste_total_eur == pytest.approx(1_400_000.0)
    assert estudio.margen_eur == pytest.approx(1_600_000.0)
    assert estudio.margen_pct > 0
    assert estudio.avisos == []


# ── Renta · Obra nueva ─────────────────────────────────────────────────────
def test_renta_aplica_doce_meses_y_ocupacion(uc):
    parametros = ParametrosEconomicos(
        operacion=Operacion.RENTA,
        intervencion=Intervencion.OBRA_NUEVA,
        precio_eur_m2=15.0,            # €/m²·mes
        coste_construccion_eur_m2=1400.0,
        edificabilidad_m2t_m2s=1.0,
        ocupacion_anual_pct=0.65,
        pct_costes_indirectos=0.0,
    )
    estudio = uc.ejecutar(parametros, _parcela(sup_m2=1000.0))

    # ingresos = 1000 m² × 15 €/m²·mes × 12 × 0.65
    esperado_ingresos = 1000.0 * 15.0 * 12.0 * 0.65
    assert estudio.ingresos_eur == pytest.approx(esperado_ingresos)


# ── Rehabilitación · usa catastro existente ────────────────────────────────
def test_rehabilitacion_usa_superficie_existente_del_catastro(uc):
    parametros = ParametrosEconomicos(
        operacion=Operacion.VENTA,
        intervencion=Intervencion.REHABILITACION,
        precio_eur_m2=3000.0,
        coste_construccion_eur_m2=900.0,
        edificabilidad_m2t_m2s=2.0,  # no debería aplicarse
    )
    estudio = uc.ejecutar(
        parametros,
        _parcela(sup_m2=500.0, construida_existente_m2=800.0),
    )

    assert estudio.fuente_superficie == FuenteSuperficie.CATASTRO_EXISTENTE
    assert estudio.superficie_aplicada_m2 == pytest.approx(800.0)
    assert estudio.avisos == []


def test_rehabilitacion_sin_catastro_cae_a_parcela_x_edificabilidad_con_aviso(uc):
    parametros = ParametrosEconomicos(
        operacion=Operacion.VENTA,
        intervencion=Intervencion.REHABILITACION,
        precio_eur_m2=3000.0,
        coste_construccion_eur_m2=900.0,
        edificabilidad_m2t_m2s=1.5,
    )
    estudio = uc.ejecutar(parametros, _parcela(sup_m2=400.0, construida_existente_m2=0.0))

    assert estudio.fuente_superficie == FuenteSuperficie.PARCELA_X_EDIFICABILIDAD
    assert estudio.superficie_aplicada_m2 == pytest.approx(600.0)
    assert any("no reporta" in a.lower() for a in estudio.avisos)


# ── Sin parcela en el proyecto ─────────────────────────────────────────────
def test_sin_parcela_devuelve_aviso_y_superficie_cero(uc):
    parametros = ParametrosEconomicos()  # defaults
    estudio = uc.ejecutar(parametros, None)

    assert estudio.fuente_superficie == FuenteSuperficie.VACIO
    assert estudio.superficie_aplicada_m2 == 0.0
    assert estudio.ingresos_eur == 0.0
    assert estudio.coste_total_eur == 0.0
    assert any("asocia" in a.lower() or "parcela" in a.lower() for a in estudio.avisos)


# ── Override manual de la superficie ───────────────────────────────────────
def test_superficie_manual_tiene_prioridad_sobre_parcela(uc):
    parametros = ParametrosEconomicos(
        superficie_construida_m2=1234.0,
        precio_eur_m2=2000.0,
        coste_construccion_eur_m2=1000.0,
        pct_costes_indirectos=0.0,
    )
    estudio = uc.ejecutar(parametros, _parcela(sup_m2=500.0, construida_existente_m2=999.0))
    assert estudio.fuente_superficie == FuenteSuperficie.MANUAL
    assert estudio.superficie_aplicada_m2 == pytest.approx(1234.0)


# ── Margen negativo no rompe el cálculo ────────────────────────────────────
def test_margen_negativo_cuando_precio_menor_que_coste(uc):
    parametros = ParametrosEconomicos(
        operacion=Operacion.VENTA,
        precio_eur_m2=500.0,
        coste_construccion_eur_m2=1400.0,
        superficie_construida_m2=1000.0,  # bypass parcela
        pct_costes_indirectos=0.18,
    )
    estudio = uc.ejecutar(parametros, None)
    assert estudio.margen_eur < 0
    assert estudio.margen_pct < 0  # sigue siendo divisible (coste > 0)


# ── % indirectos y coste de suelo se aplican ───────────────────────────────
def test_indirectos_y_suelo_se_suman_al_coste_total(uc):
    parametros = ParametrosEconomicos(
        operacion=Operacion.VENTA,
        precio_eur_m2=2000.0,
        coste_construccion_eur_m2=1000.0,
        superficie_construida_m2=100.0,
        pct_costes_indirectos=0.20,
        coste_suelo_eur=50_000.0,
    )
    estudio = uc.ejecutar(parametros, None)
    # constr = 100 * 1000 = 100.000
    # indir  = 100.000 * 0.20 = 20.000
    # suelo  = 50.000
    # total  = 170.000
    assert estudio.coste_construccion_eur == pytest.approx(100_000.0)
    assert estudio.coste_indirectos_eur == pytest.approx(20_000.0)
    assert estudio.coste_suelo_eur == pytest.approx(50_000.0)
    assert estudio.coste_total_eur == pytest.approx(170_000.0)


# ── Serialización round-trip ───────────────────────────────────────────────
def test_serializacion_parametros_roundtrip():
    original = ParametrosEconomicos(
        operacion=Operacion.RENTA,
        intervencion=Intervencion.REHABILITACION,
        precio_eur_m2=18.5,
        coste_construccion_eur_m2=950.0,
        superficie_construida_m2=750.0,
        edificabilidad_m2t_m2s=1.75,
        coste_suelo_eur=120_000.0,
        pct_costes_indirectos=0.22,
        ocupacion_anual_pct=0.7,
    )
    restaurado = parametros_desde_dict(parametros_a_dict(original))
    assert restaurado == original


def test_serializacion_desde_dict_parcial_aplica_defaults():
    p = parametros_desde_dict({"operacion": "renta"})
    assert p.operacion == Operacion.RENTA
    assert p.intervencion == Intervencion.OBRA_NUEVA  # default
    assert p.precio_eur_m2 > 0  # default no nulo


def test_serializacion_desde_dict_valores_invalidos_caen_a_default():
    p = parametros_desde_dict({
        "operacion": "no-existe",
        "precio_eur_m2": "no-es-numero",
    })
    assert p.operacion == Operacion.VENTA  # default
    assert p.precio_eur_m2 > 0  # default numérico
