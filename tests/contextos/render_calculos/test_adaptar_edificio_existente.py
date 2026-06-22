"""Tests de `adaptar_params_a_edificio_existente` (modo Rehabilitación).

Arranque encajado al edificio catastral existente. Foco: inferencia de ático
cuando las referencias catastrales no llegan a la planta superior. Si el edificio
tiene X plantas sobre rasante pero las subreferencias solo documentan R < X
plantas distintas, la superior se considera ático: como el motor lo genera ENCIMA
de `n_plantas_max`, las regulares pasan a X-1 y el total vuelve a X. Si R == X no
hay ático. Sin tocar Catastro: la localización se inyecta ya persistida.
"""
from __future__ import annotations

from app.contextos.render_calculos.casos_uso import adaptar_params_a_edificio_existente
from app.contextos.render_calculos.parametros import ParametrosRender
from app.nucleo.modelo import ModuloPuccetti, Proyecto


def _proyecto_con(plantas_sobre_rasante, plantas_loc, *, plantas_bajo_rasante=None):
    """Proyecto con datos de localización: X plantas y una subreferencia por
    cada cadena de `plantas_loc` (formato real del adapter "Es 1 · Pl 03 · Pt B")."""
    proyecto = Proyecto(nombre="test")
    loc = {
        "plantas_sobre_rasante": plantas_sobre_rasante,
        "subreferencias": [
            {"localizacion": s, "rc": f"rc{i}", "uso": "Vivienda",
             "superficie_construida_m2": 80.0}
            for i, s in enumerate(plantas_loc)
        ],
    }
    if plantas_bajo_rasante is not None:
        loc["plantas_bajo_rasante"] = plantas_bajo_rasante
    proyecto.fijar_datos(ModuloPuccetti.LOCALIZACION, loc)
    return proyecto


def test_referencias_no_llegan_a_la_superior_infiere_atico():
    """X=5, refs en plantas {00,01,02,03} (R=4 < X) → ático en la superior."""
    proyecto = _proyecto_con(5, [
        "Es 1 · Pl 00 · Pt A",
        "Es 1 · Pl 01 · Pt A",
        "Es 1 · Pl 02 · Pt A",
        "Es 1 · Pl 03 · Pt A",
    ])
    params = ParametrosRender()
    adaptar_params_a_edificio_existente(params, proyecto)

    assert params.urbanisticos.tiene_atico is True
    assert params.urbanisticos.n_plantas_max == 4   # X-1 regulares + 1 ático = 5


def test_referencias_cubren_todas_las_plantas_sin_atico():
    """X=5 = R=5 → sin ático; n_plantas_max = X."""
    proyecto = _proyecto_con(5, [
        "Es 1 · Pl 00 · Pt A",
        "Es 1 · Pl 01 · Pt A",
        "Es 1 · Pl 02 · Pt A",
        "Es 1 · Pl 03 · Pt A",
        "Es 1 · Pl 04 · Pt A",
    ])
    params = ParametrosRender()
    adaptar_params_a_edificio_existente(params, proyecto)

    assert params.urbanisticos.tiene_atico is False
    assert params.urbanisticos.n_plantas_max == 5


def test_sin_subreferencias_no_infiere_atico():
    """R=0 (parcela sin subreferencias legibles) → no se infiere ático."""
    proyecto = _proyecto_con(5, [])
    params = ParametrosRender()
    adaptar_params_a_edificio_existente(params, proyecto)

    assert params.urbanisticos.tiene_atico is False
    assert params.urbanisticos.n_plantas_max == 5


def test_subreferencia_bajo_rasante_no_cuenta_como_planta():
    """Una RC en sótano ("Pl -1") no suma a las plantas sobre rasante: con
    refs {00,01,02,03} sigue siendo R=4 < X=5 → ático."""
    proyecto = _proyecto_con(5, [
        "Es 1 · Pl -1 · Pt A",   # garaje en sótano: no es planta sobre rasante
        "Es 1 · Pl 00 · Pt A",
        "Es 1 · Pl 01 · Pt A",
        "Es 1 · Pl 02 · Pt A",
        "Es 1 · Pl 03 · Pt A",
    ], plantas_bajo_rasante=1)
    params = ParametrosRender()
    adaptar_params_a_edificio_existente(params, proyecto)

    assert params.urbanisticos.tiene_atico is True
    assert params.urbanisticos.n_plantas_max == 4
    assert params.urbanisticos.tiene_sotano is True
