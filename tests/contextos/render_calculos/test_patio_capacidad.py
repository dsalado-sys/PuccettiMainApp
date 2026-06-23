"""Patio interior: superficie mínima normativa (configurable), sin heurística.

Antes el patio se topaba al 20% de la huella (`min(area_patio_min, huella×0.20)`),
una heurística sin base normativa. Ahora se coloca el mínimo normativo completo si
cabe en lo que queda tras muros/circulación/núcleo; si no cabe, se coloca solo el
espacio disponible y `patio_sin_espacio` queda en True para avisar.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.contextos.render_calculos.casos_uso import _alertas_capacidad
from app.contextos.render_calculos.geometria.capacidad import (
    calcular_capacidad,
    capacidad_a_dict,
)
from app.contextos.render_calculos.parametros import (
    ParametrosRender,
    parametros_a_dict,
    parametros_desde_dict,
)


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


def test_sin_patios_desactiva_patio_y_aviso():
    """Sin patios definidos (lista vacía) no hay patio ni aviso (es opcional).

    El cálculo lo dirige la lista `patios`, no el mínimo normativo
    `area_patio_min_m2` (que queda solo como referencia de cumplimiento)."""
    params = ParametrosRender()
    params.urbanisticos.patios = []
    cap = calcular_capacidad(_env(14.0), params.a_parametros_motor())
    assert cap.patio_por_planta[0] == 0.0
    assert cap.patio_sin_espacio is False


def test_patio_total_es_la_suma_de_los_patios_definidos():
    """Con varios patios, cada planta descuenta la SUMA de sus áreas (patinejos
    que atraviesan todas las plantas). Huella amplia → caben íntegros."""
    params = ParametrosRender()
    params.urbanisticos.patios = [10.0, 8.0]
    cap = calcular_capacidad(_env(400.0, n_plantas=2), params.a_parametros_motor())
    assert cap.patio_por_planta[0] == 18.0
    assert cap.patio_por_planta[1] == 18.0
    d = capacidad_a_dict(cap)
    assert d["patio_total_m2"] == 36.0          # 18 por planta × 2 plantas
    assert d["patio_por_planta"] == [18.0, 18.0]


def test_parametros_patios_round_trip():
    """`patios` sobrevive a serializar y volver a parsear; `[]` explícito se respeta."""
    p = ParametrosRender()
    p.urbanisticos.patios = [10.0, 8.0]
    p2 = parametros_desde_dict(parametros_a_dict(p))
    assert p2.urbanisticos.patios == [10.0, 8.0]
    p3 = parametros_desde_dict({"urbanisticos": {"patios": []}})
    assert p3.urbanisticos.patios == []


def test_parametros_patios_migracion_legado():
    """JSON anterior a esta feature (sin clave `patios`) conserva su patio único:
    se siembra `[area_patio_min_m2]`."""
    legado = {"urbanisticos": {"area_patio_min_m2": 12.0}}  # sin "patios"
    p = parametros_desde_dict(legado)
    assert p.urbanisticos.patios == [12.0]


def test_aviso_cuando_un_patio_no_alcanza_el_area_minima():
    """Si algún patio definido es menor que el área mínima (12), salta el aviso."""
    params = ParametrosRender()
    params.urbanisticos.area_patio_min_m2 = 12.0
    params.urbanisticos.patios = [10.0, 8.0]   # ambos < 12
    cap = calcular_capacidad(_env(400.0), params.a_parametros_motor())
    alertas = _alertas_capacidad(cap, params, None)
    assert any("área mínima" in a.mensaje for a in alertas)


def test_sin_aviso_cuando_los_patios_cumplen_el_area_minima():
    params = ParametrosRender()
    params.urbanisticos.area_patio_min_m2 = 12.0
    params.urbanisticos.patios = [12.0, 15.0]  # ambos ≥ 12
    cap = calcular_capacidad(_env(400.0), params.a_parametros_motor())
    alertas = _alertas_capacidad(cap, params, None)
    assert not any("área mínima" in a.mensaje for a in alertas)
