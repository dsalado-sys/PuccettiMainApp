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


# ─── tipos_unidad + mezcla_planta (vivienda / apartamentos) ──────────────────
def _pu(uso, tipos=None, mezcla=None):
    node = {"uso": uso}
    if tipos is not None:
        node["tipos_unidad"] = tipos
    if mezcla is not None:
        node["mezcla_planta"] = mezcla
    return parametros_desde_dict({"programa": node}).programa


def test_tipos_unidad_vivienda_canonicaliza_y_valida():
    # "individual*2+doble*1" se recanonicaliza alfabéticamente; "triple*1" no es un
    # tamaño válido en vivienda (solo individual/doble) → se descarta.
    p = _pu("vivienda", tipos=["doble*1", "individual*2+doble*1", "triple*1"])
    assert p.tipos_unidad == ["doble*1", "doble*1+individual*2"]


def test_tipos_unidad_apartamentos_admite_triple_cuadruple():
    p = _pu("apartamentos_turisticos", tipos=["estudio", "triple*1", "cuadruple*2"])
    assert p.tipos_unidad == ["estudio", "triple*1", "cuadruple*2"]


def test_hotel_fuerza_tipos_y_mezcla_vacios():
    p = _pu("hotelero", tipos=["doble*1"], mezcla=["doble*1"])
    assert p.tipos_unidad == []
    assert p.mezcla_planta == []


def test_mezcla_se_autosanea_al_alfabeto_de_tipos():
    # La mezcla añade un combo-slug al alfabeto (integridad: tipos ⊇ mezcla) y
    # solo conserva referencias válidas.
    p = _pu("vivienda", tipos=["doble*1"], mezcla=["doble*1", "individual*1", "doble*1"])
    assert set(p.tipos_unidad) == {"doble*1", "individual*1"}
    assert p.mezcla_planta == ["doble*1", "individual*1", "doble*1"]


def test_mezcla_descarta_combos_invalidos():
    # "triple*1" inválido en vivienda → fuera de tipos y de mezcla.
    p = _pu("vivienda", tipos=["doble*1"], mezcla=["doble*1", "triple*1"])
    assert "triple*1" not in p.tipos_unidad
    assert p.mezcla_planta == ["doble*1"]


def test_tipos_mezcla_ausentes_son_listas_vacias():
    p = _pu("vivienda")
    assert p.tipos_unidad == []
    assert p.mezcla_planta == []


def test_tipos_mezcla_round_trip():
    params = parametros_desde_dict({"programa": {
        "uso": "apartamentos_turisticos", "tipos_unidad": ["estudio", "doble*2"],
        "mezcla_planta": ["estudio", "doble*2", "doble*2"]}})
    d = parametros_a_dict(params)
    assert d["programa"]["tipos_unidad"] == ["estudio", "doble*2"]
    assert d["programa"]["mezcla_planta"] == ["estudio", "doble*2", "doble*2"]
    p2 = parametros_desde_dict(d).programa
    assert p2.tipos_unidad == params.programa.tipos_unidad
    assert p2.mezcla_planta == params.programa.mezcla_planta


def test_string_suelto_se_acepta_como_lista():
    p = _pu("vivienda", tipos="doble*1")
    assert p.tipos_unidad == ["doble*1"]


def test_no_se_propagan_a_programa_tipo():
    # tipos_unidad/mezcla_planta son concepto de EDIFICIO: no van a programa_tipo.
    params = parametros_desde_dict({
        "programa": {"uso": "vivienda", "tipos_unidad": ["doble*1"],
                     "mezcla_planta": ["doble*1"]},
    })
    assert params.programa_tipo.tipos_unidad == []
    assert params.programa_tipo.mezcla_planta == []
