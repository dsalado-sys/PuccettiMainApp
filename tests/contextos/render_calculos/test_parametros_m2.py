"""Parametrización en m² (antes %) de circulación común y reservas de planta baja.

- Circulación (PB/tipo) y reservas de PB (local/otros/usos comunes) son m² ABSOLUTOS
  por planta, acotados a la huella disponible (patrón del núcleo). % muros se mantiene.
- La circulación interior deja de vivir en el panel (ya no hay `pct_circulacion_interior`).
"""
from __future__ import annotations

from types import SimpleNamespace

from app.contextos.render_calculos.geometria.capacidad import calcular_capacidad
from app.contextos.render_calculos.parametros import (
    ParametrosRender, parametros_a_dict, parametros_desde_dict,
)


def _env(huella_m2: float, n_plantas: int = 1) -> SimpleNamespace:
    foot = SimpleNamespace(area=huella_m2)
    plantas = [
        SimpleNamespace(n=i, footprint=foot, tipo="regular", computa_edif=True)
        for i in range(n_plantas)
    ]
    return SimpleNamespace(
        plantas=plantas, parcela=SimpleNamespace(area=huella_m2),
        superficie_referencia_m2=huella_m2,
    )


def test_campos_m2_reemplazan_a_los_pct_en_el_serializado():
    d = parametros_a_dict(ParametrosRender())
    assert "circulacion_pb_m2" in d["diseno"] and "circulacion_tipo_m2" in d["diseno"]
    assert "pct_circulacion_pb" not in d["diseno"]
    assert "pct_circulacion_interior" not in d["diseno"]
    assert {"local_pb_m2", "otros_pb_m2", "usos_comunes_pb_m2"} <= set(d["programa"])
    assert "pct_local_pb" not in d["programa"]
    # % muros se mantiene como porcentaje.
    assert "pct_muros" in d["diseno"]


def test_circulacion_comun_es_m2_absolutos_acotados():
    p = ParametrosRender()
    p.diseno.circulacion_pb_m2 = 12.0
    p.diseno.pct_muros = 20.0
    cap = calcular_capacidad(_env(100.0), p.a_parametros_motor())
    # muros = 20 % de 100 = 20; circulación = 12 m² fijos (no %).
    assert abs(cap.muros_por_planta[0] - 20.0) < 1e-6
    assert abs(cap.circulacion_por_planta[0] - 12.0) < 1e-6


def test_circulacion_comun_se_acota_a_la_huella():
    p = ParametrosRender()
    p.diseno.circulacion_pb_m2 = 10_000.0   # absurdamente grande
    p.diseno.pct_muros = 20.0
    cap = calcular_capacidad(_env(100.0), p.a_parametros_motor())
    # No puede superar lo que queda tras muros (100 − 20 = 80).
    assert cap.circulacion_por_planta[0] <= 80.0 + 1e-6


def test_reservas_pb_en_m2_reducen_la_util():
    base = ParametrosRender()
    cap0 = calcular_capacidad(_env(200.0), base.a_parametros_motor())
    p = ParametrosRender()
    p.programa.local_pb_m2 = 30.0
    cap1 = calcular_capacidad(_env(200.0), p.a_parametros_motor())
    assert abs((cap0.util_por_planta[0] - cap1.util_por_planta[0]) - 30.0) < 1e-6
    assert abs(cap1.local_pb_m2 - 30.0) < 1e-6


def test_reserva_pb_se_acota_al_util_disponible():
    p = ParametrosRender()
    p.programa.local_pb_m2 = 10_000.0
    cap = calcular_capacidad(_env(120.0), p.a_parametros_motor())
    assert cap.util_por_planta[0] >= 0.0
    assert cap.local_pb_m2 == 10_000.0  # el KPI guarda el valor pedido…
    # …pero lo consumido no excede el útil disponible: la útil no es negativa.


def test_roundtrip_override_m2():
    d = parametros_a_dict(ParametrosRender())
    d["diseno"]["circulacion_pb_m2"] = 25.0
    d["programa"]["usos_comunes_pb_m2"] = 40.0
    p = parametros_desde_dict(d)
    assert p.diseno.circulacion_pb_m2 == 25.0
    assert p.programa.usos_comunes_pb_m2 == 40.0
    m = p.a_parametros_motor()
    assert m.diseno.circulacion_pb_m2 == 25.0
    assert m.programa.usos_comunes_pb_m2 == 40.0
