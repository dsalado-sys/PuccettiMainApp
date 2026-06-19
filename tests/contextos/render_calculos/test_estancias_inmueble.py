"""Tests del modo «inmueble» (§2.5 — estancias de UNA unidad).

`CalcularEstanciasInmueble` parte de la superficie construida del inmueble (no de
una envolvente footprint×plantas) y distribuye sus estancias como una sola unidad:
útil = construida × (1 − %muros/100), y el programa de estancias reserva la
circulación interior. Sin BBDD: usa las constantes del Anexo.
"""
from __future__ import annotations

from app.contextos.render_calculos.casos_uso import CalcularEstanciasInmueble
from app.contextos.render_calculos.parametros import ParametrosRender


def test_construida_a_util_descuenta_solo_muros():
    """útil = construida × (1 − %muros/100); muros = construida − útil."""
    params = ParametrosRender()
    params.diseno.pct_muros = 20.0
    res = CalcularEstanciasInmueble().ejecutar(params, 100.0, n_dormitorios=2)

    assert res.get("error") is None
    tot = res["totales"]
    assert tot["construida_m2"] == 100.0
    assert abs(tot["util_m2"] - 80.0) < 1e-6
    assert abs(tot["muros_m2"] - 20.0) < 1e-6
    assert tot["n_dormitorios"] == 2
    assert tot["uso"] == "vivienda"


def test_pct_muros_distinto_cambia_el_util():
    params = ParametrosRender()
    params.diseno.pct_muros = 25.0
    res = CalcularEstanciasInmueble().ejecutar(params, 200.0, n_dormitorios=3)
    assert abs(res["totales"]["util_m2"] - 150.0) < 1e-6  # 200 × 0.75


def test_estancias_suman_el_util_y_contienen_el_programa():
    """Las estancias (incl. circulación interior) suman el útil; hay salón,
    dormitorios y baño (programa de vivienda del Anexo I.5)."""
    params = ParametrosRender()
    res = CalcularEstanciasInmueble().ejecutar(params, 100.0, n_dormitorios=2)

    estancias = res["estancias"]
    suma = sum(e["area_target_m2"] for e in estancias)
    assert abs(suma - res["totales"]["util_m2"]) < 0.1

    nombres = {e["nombre"] for e in estancias}
    assert "salon" in nombres
    assert {"dormitorio_1", "dormitorio_2"} <= nombres
    assert any(n == "bano" or n.startswith("bano_") for n in nombres)
    # La circulación interior se reserva dentro del programa (no se descuenta dos veces).
    assert "circulacion_interior" in nombres


def test_n_estancias_excluye_la_circulacion():
    params = ParametrosRender()
    res = CalcularEstanciasInmueble().ejecutar(params, 90.0, n_dormitorios=2)
    no_circ = [e for e in res["estancias"] if e["categoria"] != "circulacion"]
    assert res["totales"]["n_estancias"] == len(no_circ)


def test_sin_construida_devuelve_error_sin_estancias():
    res = CalcularEstanciasInmueble().ejecutar(ParametrosRender(), 0.0)
    assert res["error"]
    assert res["estancias"] == []
    assert res["totales"] is None


def test_inmueble_infradimensionado_avisa_pero_calcula():
    """Un inmueble por debajo del mínimo viable emite un aviso de Normativa,
    pero sigue devolviendo estancias (con suelo en el mínimo de cada una)."""
    params = ParametrosRender()
    # 30 m² construidos para 3 dormitorios: muy por debajo del mínimo viable.
    res = CalcularEstanciasInmueble().ejecutar(params, 30.0, n_dormitorios=3)
    assert res["estancias"]  # no se queda vacío
    assert any(a["nivel"] == "aviso" for a in res["alertas"])
