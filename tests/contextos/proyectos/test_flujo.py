"""Tests del flujo de estados del proyecto (§2.11, `contextos/proyectos/flujo.py`).

Función pura sobre el aggregate: se fabrica un `Proyecto` con `datos_por_modulo`
a mano y se comprueba el color/etiqueta de cada dimensión. Sin BBDD ni red.
"""
from __future__ import annotations

from app.contextos.proyectos.flujo import (
    ColorFlujo,
    calcular_flujo,
    flujo_a_dict,
)
from app.nucleo.modelo import ModuloPuccetti, Proyecto


def _proyecto(**bloques) -> Proyecto:
    p = Proyecto(nombre="P")
    for modulo, datos in bloques.items():
        p.fijar_datos(ModuloPuccetti[modulo], datos)
    return p


# ─── Parcela ─────────────────────────────────────────────────────────────────

def test_parcela_ausente_es_amarillo():
    f = calcular_flujo(_proyecto())
    assert f.parcela.color is ColorFlujo.AMARILLO
    assert f.parcela.clave == "sin_parcela"


def test_parcela_guardada_es_verde():
    f = calcular_flujo(_proyecto(LOCALIZACION={"referencia_catastral": "1234", "superficie_m2": 500}))
    assert f.parcela.color is ColorFlujo.VERDE
    assert f.parcela.clave == "parcela_guardada"


def test_inmueble_guardado_es_verde_y_distinto():
    f = calcular_flujo(_proyecto(LOCALIZACION={
        "referencia_catastral": "1234",
        "inmueble_seleccionado": {"rc": "1234ABCD"},
    }))
    assert f.parcela.color is ColorFlujo.VERDE
    assert f.parcela.clave == "inmueble_guardado"


# ─── Normativa ───────────────────────────────────────────────────────────────

def test_normativa_ausente_es_amarillo():
    assert calcular_flujo(_proyecto()).normativa.color is ColorFlujo.AMARILLO


def test_normativa_aplicada_es_verde():
    f = calcular_flujo(_proyecto(RENDER_CALCULOS={
        "normativa_aplicada": {"id": 1, "nombre": "PGOU", "urbanisticos": {"ocupacion_maxima_pct": 80}},
    }))
    assert f.normativa.color is ColorFlujo.VERDE
    assert f.normativa.clave == "normativa_aplicada"


def test_normativa_sin_urbanisticos_sigue_amarillo():
    f = calcular_flujo(_proyecto(RENDER_CALCULOS={
        "normativa_aplicada": {"id": 1, "nombre": "PGOU", "urbanisticos": {}},
    }))
    assert f.normativa.color is ColorFlujo.AMARILLO


# ─── Errores / avisos por escenario ──────────────────────────────────────────

def _rc_con_escenario(alertas_resumen) -> dict:
    resumen = {} if alertas_resumen is None else {"alertas_resumen": alertas_resumen}
    return {"obra-nueva": {"escenarios": [
        {"id": "e1", "nombre": "V", "resumen_ultimo_calculo": resumen},
    ], "activo": "e1"}}


def test_escenario_error_y_aviso_es_rojo():
    f = calcular_flujo(_proyecto(RENDER_CALCULOS=_rc_con_escenario({"error": 1, "aviso": 2})))
    ea = f.escenarios[0].errores_avisos
    assert ea.color is ColorFlujo.ROJO and ea.clave == "con_errores_y_avisos"


def test_escenario_solo_error_es_rojo():
    f = calcular_flujo(_proyecto(RENDER_CALCULOS=_rc_con_escenario({"error": 1})))
    assert f.escenarios[0].errores_avisos.clave == "con_errores"


def test_incumplimiento_cuenta_como_error():
    f = calcular_flujo(_proyecto(RENDER_CALCULOS=_rc_con_escenario({"incumplimiento": 1})))
    ea = f.escenarios[0].errores_avisos
    assert ea.color is ColorFlujo.ROJO and ea.clave == "con_errores"


def test_escenario_solo_aviso_es_amarillo():
    f = calcular_flujo(_proyecto(RENDER_CALCULOS=_rc_con_escenario({"aviso": 3})))
    ea = f.escenarios[0].errores_avisos
    assert ea.color is ColorFlujo.AMARILLO and ea.clave == "con_avisos"


def test_escenario_sin_alertas_es_verde():
    f = calcular_flujo(_proyecto(RENDER_CALCULOS=_rc_con_escenario({"error": 0, "aviso": 0, "info": 5})))
    assert f.escenarios[0].errores_avisos.color is ColorFlujo.VERDE


def test_escenario_sin_calcular_es_rojo_por_defecto():
    f = calcular_flujo(_proyecto(RENDER_CALCULOS=_rc_con_escenario(None)))
    ea = f.escenarios[0].errores_avisos
    assert ea.color is ColorFlujo.ROJO and ea.clave == "con_errores_y_avisos"


def test_escenarios_de_varios_modos_se_agregan():
    rc = {
        "normativa_aplicada": {"urbanisticos": {"x": 1}},   # se salta, no es escenario
        "obra-nueva": {"escenarios": [{"id": "e1", "resumen_ultimo_calculo": {"alertas_resumen": {}}}]},
        "rehabilitacion": {"escenarios": [{"id": "e1", "resumen_ultimo_calculo": {"alertas_resumen": {"aviso": 1}}}]},
    }
    f = calcular_flujo(_proyecto(RENDER_CALCULOS=rc))
    modos = {fe.modo for fe in f.escenarios}
    assert modos == {"obra-nueva", "rehabilitacion"}
    assert len(f.escenarios) == 2


# ─── Viabilidad ──────────────────────────────────────────────────────────────

def test_viabilidad_ausente_es_rojo():
    f = calcular_flujo(_proyecto())
    assert f.viabilidad.color is ColorFlujo.ROJO and f.viabilidad.clave == "sin_estudio"


def test_viabilidad_sin_aprobar_es_amarillo():
    f = calcular_flujo(_proyecto(VIABILIDAD={"precio_eur_m2": 3200}))
    assert f.viabilidad.color is ColorFlujo.AMARILLO and f.viabilidad.clave == "estudio_sin_aprobar"


def test_viabilidad_aprobada_es_verde():
    f = calcular_flujo(_proyecto(VIABILIDAD={"precio_eur_m2": 3200, "aprobado": True}))
    assert f.viabilidad.color is ColorFlujo.VERDE and f.viabilidad.clave == "estudio_aprobado"


# ─── Informe ─────────────────────────────────────────────────────────────────

def test_informe_ausente_es_rojo():
    f = calcular_flujo(_proyecto())
    assert f.informe.color is ColorFlujo.ROJO and f.informe.clave == "informe_sin_aprobar"


def test_informe_revisado_es_amarillo():
    f = calcular_flujo(_proyecto(INFORME={"estado": "revisado"}))
    assert f.informe.color is ColorFlujo.AMARILLO and f.informe.clave == "informe_revisado"


def test_informe_aprobado_es_verde():
    f = calcular_flujo(_proyecto(INFORME={"estado": "aprobado"}))
    assert f.informe.color is ColorFlujo.VERDE and f.informe.clave == "informe_aprobado"


# ─── Informe POR ESCENARIO ───────────────────────────────────────────────────

def test_informe_escenario_por_defecto_es_rojo():
    f = calcular_flujo(_proyecto(RENDER_CALCULOS=_rc_con_escenario({"aviso": 1})))
    assert f.escenarios[0].informe.color is ColorFlujo.ROJO
    assert f.escenarios[0].informe.clave == "informe_sin_aprobar"


def test_informe_escenario_aprobado_es_verde():
    f = calcular_flujo(_proyecto(
        RENDER_CALCULOS=_rc_con_escenario({"error": 0, "aviso": 0}),
        INFORME={"escenarios": {"obra-nueva:e1": {"estado": "aprobado"}}},
    ))
    assert f.escenarios[0].informe.color is ColorFlujo.VERDE
    assert f.escenarios[0].informe.clave == "informe_aprobado"


def test_informe_escenario_de_otra_pestana_no_afecta():
    # La aprobación es por escenario: aprobar "otro" no pone verde a "e1".
    f = calcular_flujo(_proyecto(
        RENDER_CALCULOS=_rc_con_escenario({}),
        INFORME={"escenarios": {"obra-nueva:otro": {"estado": "aprobado"}}},
    ))
    assert f.escenarios[0].informe.color is ColorFlujo.ROJO


# ─── Serialización ───────────────────────────────────────────────────────────

def test_flujo_a_dict_forma():
    p = _proyecto(
        LOCALIZACION={"referencia_catastral": "1234"},
        RENDER_CALCULOS=_rc_con_escenario({"aviso": 1}),
    )
    d = flujo_a_dict(calcular_flujo(p))
    assert set(d) == {"parcela", "normativa", "escenarios", "viabilidad", "informe"}
    assert d["parcela"] == {"clave": "parcela_guardada", "etiqueta": "Parcela guardada", "color": "verde"}
    assert d["escenarios"][0]["errores_avisos"]["color"] == "amarillo"
    assert set(d["escenarios"][0]) == {"modo", "escenario_id", "nombre", "errores_avisos", "informe"}
    assert d["escenarios"][0]["informe"]["color"] == "rojo"   # sin aprobar por defecto
