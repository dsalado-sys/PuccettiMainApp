"""Superficie libre (complemento de la ocupación) y aviso de Capacidad.

Al eliminar el retranqueo de ocupación en el render, la ocupación deja de dibujarse
como un anillo y su complemento se reporta como «superficie libre» = (1 − ocupación) ×
sup_ref, sumada por plantas y contemplando las dos ocupaciones (PB y tipo). El total de
patios (sumado por plantas) no debe superar esa superficie libre; si lo hace, salta un
aviso `Alerta("aviso", "Capacidad", …)`.
"""
from __future__ import annotations

from shapely.geometry import box

from app.contextos.render_calculos.casos_uso import _alertas_capacidad
from app.contextos.render_calculos.geometria.capacidad import (
    calcular_capacidad,
    capacidad_a_dict,
)
from app.contextos.render_calculos.geometria.envolvente import construir_envolvente
from app.contextos.render_calculos.parametros import ParametrosRender

PARCELA = box(0.0, 0.0, 20.0, 20.0)   # 400 m²
AREA = 400.0


def _render(ocup_pb: float, ocup_tipo: float, n_plantas: int, patios=None) -> ParametrosRender:
    p = ParametrosRender()
    p.urbanisticos.ocupacion_maxima_pct = ocup_pb
    p.urbanisticos.ocupacion_maxima_pct_tipo = ocup_tipo
    p.urbanisticos.usar_coeficiente_edificabilidad = False
    p.urbanisticos.coeficiente_edificabilidad = 8.0   # techo holgado
    p.urbanisticos.n_plantas_max = n_plantas
    p.urbanisticos.retranqueo_fachada_m = 0.0
    p.urbanisticos.retranqueo_linderos_m = 0.0
    p.urbanisticos.patios = [] if patios is None else list(patios)
    return p


def _capacidad(p: ParametrosRender):
    env = construir_envolvente(PARCELA, p.a_parametros_motor(), None, superficie_referencia=AREA)
    return calcular_capacidad(env, p.a_parametros_motor(), params_tipo=p.a_parametros_motor_tipo())


def test_superficie_libre_por_planta_contempla_ambas_ocupaciones():
    """PB al 90% y plantas tipo al 60% (2 plantas, sin patios): la superficie libre por
    planta es (1 − ocupación) × sup_ref = [40, 160] y el total = 200 m²."""
    cap = _capacidad(_render(90.0, 60.0, n_plantas=2))
    assert abs(cap.superficie_libre_por_planta[0] - 40.0) < 1.0    # PB: 400 − 360
    assert abs(cap.superficie_libre_por_planta[1] - 160.0) < 1.0   # tipo: 400 − 240
    d = capacidad_a_dict(cap)
    assert abs(d["superficie_libre_total_m2"] - 200.0) < 1.5


def test_ocupacion_100_deja_superficie_libre_cero():
    """Al 100% de ocupación no hay superficie libre."""
    cap = _capacidad(_render(100.0, 100.0, n_plantas=1))
    d = capacidad_a_dict(cap)
    assert abs(d["superficie_libre_total_m2"]) < 1.0


def test_aviso_capacidad_cuando_patio_total_supera_superficie_libre():
    """1 planta al 80% → superficie libre = 80 m². Un patio total de 100 m² la supera →
    salta el aviso de Capacidad."""
    p = _render(80.0, 80.0, n_plantas=1, patios=[100.0])
    cap = _capacidad(p)
    alertas = _alertas_capacidad(cap, p, None)
    capacidad = [a for a in alertas if a.regla == "Capacidad"
                 and "supera la superficie libre" in a.mensaje]
    assert len(capacidad) == 1
    assert capacidad[0].nivel == "aviso"


def test_sin_aviso_capacidad_cuando_patio_total_cabe_en_superficie_libre():
    """1 planta al 80% → superficie libre = 80 m². Un patio total de 40 m² cabe → sin aviso."""
    p = _render(80.0, 80.0, n_plantas=1, patios=[40.0])
    cap = _capacidad(p)
    alertas = _alertas_capacidad(cap, p, None)
    assert not any("supera la superficie libre" in a.mensaje for a in alertas)
