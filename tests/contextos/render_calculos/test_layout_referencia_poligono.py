"""Regresión: el cálculo del render usa el ÁREA DEL POLÍGONO como superficie de referencia,
no la catastral declarada.

`casos_uso` alimenta `construir_envolvente` con `parcela.poligono_utm.area`, de modo que
ocupación, edificabilidad y superficie libre se miden todas contra el polígono. Antes se
pasaba la catastral (`superficie_catastral_m2`): cuando la catastral era MENOR que el
polígono (lo habitual en parcelas reales, simplificadas o no), al 100% de ocupación aparecía
«superficie libre» = (polígono − catastral) × nº de plantas, que el usuario no configuraba.
Test a nivel de caso de uso (no de motor): ejercita el camino de producción.
"""
from __future__ import annotations

import math

from shapely.geometry import Polygon

from app.contextos.render_calculos.casos_uso import (
    CalcularEnvolvente,
    CalcularLayout,
    ParcelaMetrica,
)
from app.contextos.render_calculos.geometria.parcelas import (
    LadoParcela,
    azimut_normal_exterior,
)
from app.contextos.render_calculos.parametros import parametros_desde_dict

POLIGONO_M2 = 400.0        # box 20×20
CATASTRAL_MENOR_M2 = 300.0  # declarada MENOR que el polígono (caso que veía el usuario)


def _parcela(cat_m2: float | None) -> ParcelaMetrica:
    coords = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)]
    poly = Polygon(coords)
    lados = []
    for i, p1 in enumerate(coords):
        p2 = coords[(i + 1) % len(coords)]
        long_m = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        az = (math.degrees(math.atan2(p2[0] - p1[0], p2[1] - p1[1]))) % 360
        lados.append(LadoParcela(
            p1=p1, p2=p2, tipo="fachada", longitud_m=long_m, azimut=az,
            normal_azimut=azimut_normal_exterior(p1, p2, poly),
        ))
    return ParcelaMetrica(
        poligono_utm=poly, lados=lados, municipio="X", provincia="Y",
        centroide_lonlat=None, referencia_catastral=None,
        superficie_catastral_m2=cat_m2,
    )


def _params(usar_coef: bool):
    urb = {"ocupacion_maxima_pct": 100.0, "ocupacion_maxima_pct_tipo": 100.0,
           "n_plantas_max": 3, "retranqueo_fachada_m": 0.0, "retranqueo_linderos_m": 0.0,
           "usar_coeficiente_edificabilidad": usar_coef, "coeficiente_edificabilidad": 2.0}
    prog = {"uso": "vivienda", "tipos_unidad": ["doble*1"]}
    return parametros_desde_dict({"urbanisticos": urb, "programa": prog})


def test_layout_libre_cero_con_catastral_menor_que_poligono():
    """Catastral (300) < polígono (400), ocupación 100%, retranqueos 0: la huella llena el
    polígono ⇒ superficie libre = 0. Antes salía (400−300)×nº plantas > 0."""
    r = CalcularLayout().ejecutar(_parcela(CATASTRAL_MENOR_M2), _params(usar_coef=False))
    assert not r.get("error"), r
    assert abs(r["capacidad"]["superficie_libre_total_m2"]) < 1.0


def test_layout_libre_cero_sin_catastral_declarada():
    """Sin catastral la referencia ya era el polígono; sigue dando 0 al 100% (no regresa)."""
    r = CalcularLayout().ejecutar(_parcela(None), _params(usar_coef=False))
    assert not r.get("error"), r
    assert abs(r["capacidad"]["superficie_libre_total_m2"]) < 1.0


def test_edificabilidad_se_calcula_sobre_el_poligono():
    """La edificabilidad usa el polígono (coef×400 = 800), no la catastral (coef×300 = 600)."""
    res = CalcularEnvolvente().ejecutar(_parcela(CATASTRAL_MENOR_M2), _params(usar_coef=True))
    assert not res.get("error"), res
    assert abs(res["envolvente"]["edificabilidad_max_m2"] - 2.0 * POLIGONO_M2) < 1.0
