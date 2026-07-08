"""Persistencia del campo `combinacion` (elección de combinación por escenario).

`ParametrosPrograma.combinacion` es un slug multiconjunto canónico cuya semántica
depende del uso (dormitorios de una unidad en vivienda/apartamentos, mezcla de
habitaciones por planta en hotel). Se valida contra los slugs del uso activo y
round-trippea por `parametros_a_dict`/`parametros_desde_dict`.
"""
from __future__ import annotations

from app.contextos.render_calculos.parametros import (
    parametros_a_dict, parametros_desde_dict,
)


def _prog(uso, combinacion):
    return parametros_desde_dict({"programa": {"uso": uso, "combinacion": combinacion}}).programa


def test_combinacion_hotel_valida_se_conserva():
    assert _prog("hotelero", "doble*2+individual*1").combinacion == "doble*2+individual*1"


def test_combinacion_de_otro_uso_se_descarta():
    # Un slug de dormitorios de vivienda no es válido en hotel → se descarta.
    assert _prog("hotelero", "1d*2").combinacion == ""


def test_combinacion_tipologia_no_valida_se_descarta():
    # "suite" no es una tipología hotelera válida.
    assert _prog("hotelero", "suite*2").combinacion == ""


def test_combinacion_vivienda_estudio_round_trip():
    assert _prog("vivienda", "estudio").combinacion == "estudio"


def test_combinacion_apartamentos_se_canonicaliza():
    # El orden de los tokens no importa: se re-canonicaliza alfabéticamente.
    assert _prog("apartamentos_turisticos", "individual*2+doble*1").combinacion == \
        "doble*1+individual*2"


def test_combinacion_round_trip_idempotente():
    p = parametros_desde_dict({"programa": {"uso": "hotelero",
                                            "combinacion": "doble*2+individual*1"}})
    d = parametros_a_dict(p)
    assert d["programa"]["combinacion"] == "doble*2+individual*1"
    assert parametros_desde_dict(d).programa.combinacion == "doble*2+individual*1"


def test_combinacion_ausente_es_vacia():
    assert parametros_desde_dict({"programa": {"uso": "hotelero"}}).programa.combinacion == ""
