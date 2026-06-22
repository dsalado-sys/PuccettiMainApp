"""Patio interior: superficie mínima normativa (configurable), sin heurística.

Antes el patio se topaba al 20% de la huella (`min(area_patio_min, huella×0.20)`),
una heurística sin base normativa. Ahora se coloca el mínimo normativo completo si
cabe en lo que queda tras muros/circulación/núcleo; si no cabe, se coloca solo el
espacio disponible y `patio_sin_espacio` queda en True para avisar.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.contextos.render_calculos.geometria.capacidad import calcular_capacidad
from app.contextos.render_calculos.parametros import ParametrosRender


def _env(huella_m2: float, n_plantas: int = 1) -> SimpleNamespace:
    """Envolvente mínima: una o varias plantas regulares de huella conocida."""
    foot = SimpleNamespace(area=huella_m2)
    plantas = [
        SimpleNamespace(n=i, footprint=foot, tipo="regular", computa_edif=True)
        for i in range(n_plantas)
    ]
    return SimpleNamespace(
        plantas=plantas,
        parcela=SimpleNamespace(area=huella_m2),
        superficie_referencia_m2=huella_m2,
    )


def test_patio_usa_el_minimo_normativo_no_el_20pct():
    """Huella 50 m²: el 20% serían 10 m² (< 12), pero aún quedan > 12 tras
    muros/circulación/núcleo → el patio toma el mínimo normativo COMPLETO (12)."""
    params = ParametrosRender()  # area_patio_min_m2 = 12 por defecto
    cap = calcular_capacidad(_env(50.0), params.a_parametros_motor())
    assert cap.patio_por_planta[0] == 12.0   # mínimo normativo, no 10.0 (viejo 20%)
    assert cap.patio_sin_espacio is False
    assert cap.area_patio_min_m2 == 12.0


def test_patio_avisa_cuando_no_cabe_el_minimo():
    """Huella diminuta: tras muros/circulación/núcleo no caben 12 m² de patio →
    se coloca lo disponible y se marca el aviso, sin dejar útil negativo."""
    params = ParametrosRender()
    cap = calcular_capacidad(_env(14.0), params.a_parametros_motor())
    assert cap.patio_sin_espacio is True
    assert cap.patio_por_planta[0] < 12.0
    assert cap.util_por_planta[0] >= 0.0


def test_patio_cero_desactiva_patio_y_aviso():
    """Con superficie de patio 0 no hay patio ni aviso (el patio es opcional)."""
    params = ParametrosRender()
    params.urbanisticos.area_patio_min_m2 = 0.0
    cap = calcular_capacidad(_env(14.0), params.a_parametros_motor())
    assert cap.patio_por_planta[0] == 0.0
    assert cap.patio_sin_espacio is False
