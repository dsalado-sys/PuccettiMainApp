"""La edificabilidad solo AVISA: no retira plantas del reparto.

Antes, una planta cuya huella no cabía bajo el techo de edificabilidad quedaba con 0
unidades (recorte por techo, admisión contigua de abajo arriba). Ahora todas las plantas
habitables con útil reparten unidades —también las que superan el techo, p. ej. una planta
consolidada/legalizada por antigüedad en rehabilitación, usada como una planta más— y el
exceso solo dispara el factor limitante y el aviso de incumplimiento.
"""
from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import box

from app.contextos.render_calculos.casos_uso import _alertas_envolvente
from app.contextos.render_calculos.geometria.capacidad import calcular_capacidad
from app.contextos.render_calculos.geometria.envolvente import construir_envolvente
from app.contextos.render_calculos.parametros import ParametrosRender

PARCELA = box(0.0, 0.0, 20.0, 20.0)   # 400 m²
AREA = 400.0


def _params(coef: float, n_plantas: int) -> ParametrosRender:
    p = ParametrosRender()
    p.urbanisticos.usar_coeficiente_edificabilidad = True
    p.urbanisticos.coeficiente_edificabilidad = coef
    p.urbanisticos.ocupacion_maxima_pct = 100.0
    p.urbanisticos.ocupacion_maxima_pct_tipo = 100.0
    p.urbanisticos.n_plantas_max = n_plantas
    p.urbanisticos.retranqueo_fachada_m = 0.0
    p.urbanisticos.retranqueo_linderos_m = 0.0
    p.urbanisticos.patios = []   # sin patio: huella == construida
    return p


def _envolvente(p: ParametrosRender):
    return construir_envolvente(PARCELA, p.a_parametros_motor(), None, superficie_referencia=AREA)


def _capacidad(p: ParametrosRender):
    env = _envolvente(p)
    cap = calcular_capacidad(
        env, p.a_parametros_motor(), params_tipo=p.a_parametros_motor_tipo()
    )
    return env, cap


def test_edificabilidad_no_deja_plantas_sin_unidades():
    """3 plantas × 400 m² = 1200 consumido; techo = 400 × 2.0 = 800 → excede, pero
    TODAS las plantas (incl. la superior, antes recortada) reparten unidades."""
    p = _params(coef=2.0, n_plantas=3)
    env, cap = _capacidad(p)
    assert len(env.plantas) == 3
    assert env.edificabilidad_consumida > env.edificabilidad_max   # 1200 > 800

    assert all(v > 0 for v in cap.viv_por_planta)   # ninguna a 0 por techo
    assert cap.viv_por_planta[-1] > 0               # la planta que antes se recortaba
    assert cap.factor_limitante == "edificabilidad" # el exceso se sigue reportando


def test_aviso_de_edificabilidad_persiste():
    """El recorte desaparece pero el aviso de incumplimiento de edificabilidad NO."""
    p = _params(coef=2.0, n_plantas=3)
    env = _envolvente(p)
    parcela = SimpleNamespace(lados=[SimpleNamespace(tipo="fachada")])
    alertas = _alertas_envolvente(env, parcela, p)
    assert any("supera el techo máximo" in a.mensaje for a in alertas)


def test_techo_holgado_reparte_igual_sin_factor_edificabilidad():
    """Coeficiente holgado: no excede → factor limitante distinto, todas reparten."""
    p = _params(coef=10.0, n_plantas=3)
    _env, cap = _capacidad(p)
    assert all(v > 0 for v in cap.viv_por_planta)
    assert cap.factor_limitante != "edificabilidad"


def test_edificabilidad_consumida_descuenta_patios():
    """La edificabilidad consumida = superficie CONSTRUIDA (huella − patios), no la
    huella completa: el patio interior a cielo abierto no es techo y no computa."""
    p = _params(coef=2.5, n_plantas=3)
    p.urbanisticos.patios = [20.0]            # un patio de 20 m² (el helper deja [])
    env = _envolvente(p)
    computa = [pl for pl in env.plantas if pl.computa_edif]
    suma_construida = sum(pl.area_construida_m2 for pl in computa)
    suma_huella = sum(pl.footprint.area for pl in computa)
    assert suma_huella - suma_construida > 1.0               # el patio resta de verdad
    assert abs(env.edificabilidad_consumida - suma_construida) < 1e-6
    assert env.edificabilidad_consumida < suma_huella
