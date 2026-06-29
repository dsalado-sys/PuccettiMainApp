"""Ocupación máxima por categoría de planta (PB vs plantas tipo).

La ocupación de planta baja (`ocupacion_maxima_pct`) y la de plantas tipo
(`ocupacion_maxima_pct_tipo`) recortan huellas distintas en
`construir_envolvente`: PB (y sótano) usan la de PB; las plantas regulares por
encima de PB (y el ático) usan la de tipo. Si la clave de tipo no llega en el
JSON, hereda la de PB → todas las plantas comparten huella (histórico).
"""
from __future__ import annotations

from shapely.geometry import box

from app.contextos.render_calculos.geometria.capacidad import (
    calcular_capacidad,
    capacidad_a_dict,
)
from app.contextos.render_calculos.geometria.envolvente import construir_envolvente
from app.contextos.render_calculos.parametros import (
    ParametrosRender,
    parametros_a_dict,
    parametros_desde_dict,
)

PARCELA = box(0.0, 0.0, 20.0, 20.0)   # 400 m²
AREA = 400.0


def _render(ocup_pb: float, ocup_tipo: float | None = None, **urb) -> ParametrosRender:
    p = ParametrosRender()
    p.urbanisticos.ocupacion_maxima_pct = ocup_pb
    if ocup_tipo is not None:
        p.urbanisticos.ocupacion_maxima_pct_tipo = ocup_tipo
    p.urbanisticos.usar_coeficiente_edificabilidad = False
    p.urbanisticos.coeficiente_edificabilidad = 8.0   # techo holgado: no recorta plantas
    p.urbanisticos.n_plantas_max = 2                  # PB + 1 planta tipo
    p.urbanisticos.retranqueo_fachada_m = 0.0
    p.urbanisticos.retranqueo_linderos_m = 0.0
    p.urbanisticos.patios = []                        # sin patio: huella == construida
    for k, v in urb.items():
        setattr(p.urbanisticos, k, v)
    return p


def _envolvente(p: ParametrosRender):
    return construir_envolvente(PARCELA, p.a_parametros_motor(), None, superficie_referencia=AREA)


# ─── Geometría: footprint por categoría ─────────────────────────────────────
def test_footprint_pb_y_tipo_usan_su_propia_ocupacion():
    env = _envolvente(_render(90.0, 60.0))
    regulares = [pl for pl in env.plantas if pl.tipo == "regular"]
    assert len(regulares) == 2
    pb, tipo = regulares
    assert abs(pb.footprint.area - 0.90 * AREA) < 1.0      # ≈ 360
    assert abs(tipo.footprint.area - 0.60 * AREA) < 1.0    # ≈ 240
    assert tipo.footprint.area < pb.footprint.area


def test_misma_ocupacion_comparte_huella():
    """Con la misma ocupación en PB y tipo todas las plantas comparten huella
    (comportamiento histórico de un proyecto con una sola ocupación)."""
    env = _envolvente(_render(90.0, 90.0))
    regulares = [pl for pl in env.plantas if pl.tipo == "regular"]
    assert abs(regulares[0].footprint.area - regulares[1].footprint.area) < 1e-6


def test_atico_se_apoya_en_la_huella_de_plantas_tipo():
    """Ático (retranqueo 0) toma la huella de la planta tipo, no la de PB."""
    p = _render(90.0, 60.0, tiene_atico=True, retranqueo_atico_m=0.0)
    env = _envolvente(p)
    pb = next(pl for pl in env.plantas if pl.tipo == "regular")
    atico = next(pl for pl in env.plantas if pl.tipo == "atico")
    assert abs(atico.footprint.area - 0.60 * AREA) < 1.0
    assert atico.footprint.area < pb.footprint.area


def test_sotano_usa_la_ocupacion_de_pb():
    p = _render(90.0, 60.0, tiene_sotano=True)
    env = _envolvente(p)
    sotano = next(pl for pl in env.plantas if pl.tipo == "sotano")
    pb = next(pl for pl in env.plantas if pl.tipo == "regular")
    assert abs(sotano.footprint.area - pb.footprint.area) < 1e-6
    assert abs(sotano.footprint.area - 0.90 * AREA) < 1.0


# ─── Capacidad: la construida por planta refleja la huella de su categoría ───
def test_capacidad_construida_menor_en_plantas_tipo():
    p = _render(90.0, 60.0)
    env = _envolvente(p)
    cap = calcular_capacidad(
        env, p.a_parametros_motor(), params_tipo=p.a_parametros_motor_tipo()
    )
    # construida = huella (sin patio en este test) → PB (360) > tipo (240).
    assert cap.construida_por_planta[0] > cap.construida_por_planta[1]
    assert abs(cap.construida_por_planta[0] - 0.90 * AREA) < 1.0
    assert abs(cap.construida_por_planta[1] - 0.60 * AREA) < 1.0


# ─── Caso tipo > PB: el techo por ocupación no falsea el exceso ─────────────
def test_tipo_mayor_que_pb_no_dispara_falso_exceso():
    """PB pequeña (comercial retranqueada) + plantas tipo voladas mayores. El techo
    por ocupación usa la MAYOR de las dos ocupaciones, así que el consumo no supera el
    máximo ni recorta la planta tipo (dimensionado por ocupación, no por coeficiente)."""
    p = _render(30.0, 100.0)   # usar_coeficiente_edificabilidad=False, n_plantas=2
    env = _envolvente(p)
    # Techo = max(0.30, 1.0) × 400 × 2 = 800; consumo = 120 + 400 = 520 ≤ 800.
    assert env.edificabilidad_consumida < env.edificabilidad_max + 1e-6
    assert abs(env.edificabilidad_max - 800.0) < 1.0

    cap = calcular_capacidad(
        env, p.a_parametros_motor(), params_tipo=p.a_parametros_motor_tipo()
    )
    assert cap.factor_limitante != "edificabilidad"
    # La planta tipo (mayor huella) NO se recorta: más construida que PB.
    assert cap.construida_por_planta[1] > cap.construida_por_planta[0]
    d = capacidad_a_dict(cap)
    assert abs(d["edificabilidad_m2"] - 800.0) < 1.0   # KPI con la ocupación mayor


# ─── Modo que oculta «ocupacion»: la normativa única se espeja en tipo ───────
def test_rehabilitacion_espeja_ocupacion_normativa_en_plantas_tipo():
    """En rehabilitación la sección «ocupacion» se oculta: la normativa archivada solo
    aporta UNA ocupación; se espeja en plantas tipo para conservar la ocupación única
    (tipo == PB), no dejarlas al 100%."""
    from app.contextos.render_calculos.parametros import ParametrosUrbanisticos
    from app.entrypoints.web.rutas.render_calculos import (
        _aplicar_normativa_secciones_ocultas,
    )

    params = ParametrosRender()
    normativa = ParametrosUrbanisticos(ocupacion_maxima_pct=70.0)
    _aplicar_normativa_secciones_ocultas(params, {"modo": "rehabilitacion"}, normativa)
    assert params.urbanisticos.ocupacion_maxima_pct == 70.0
    assert params.urbanisticos.ocupacion_maxima_pct_tipo == 70.0


# ─── Motor: mapeo de % → fracción ───────────────────────────────────────────
def test_motor_mapea_ocupacion_tipo():
    p = _render(80.0, 50.0)
    urb = p.a_parametros_motor().urbanismo
    assert abs(urb.ocupacion_maxima - 0.80) < 1e-9
    assert abs(urb.ocupacion_maxima_tipo - 0.50) < 1e-9


# ─── Parser/serialización ───────────────────────────────────────────────────
def test_parser_tipo_hereda_pb_si_falta_la_clave():
    """JSON legado (sin `…_pct_tipo`) → la ocupación de tipo hereda la de PB."""
    p = parametros_desde_dict({"urbanisticos": {"ocupacion_maxima_pct": 80.0}})
    assert p.urbanisticos.ocupacion_maxima_pct == 80.0
    assert p.urbanisticos.ocupacion_maxima_pct_tipo == 80.0


def test_parser_respeta_tipo_explicito_y_round_trip():
    d = {"urbanisticos": {"ocupacion_maxima_pct": 80.0, "ocupacion_maxima_pct_tipo": 50.0}}
    p = parametros_desde_dict(d)
    assert p.urbanisticos.ocupacion_maxima_pct_tipo == 50.0
    p2 = parametros_desde_dict(parametros_a_dict(p))
    assert p2.urbanisticos.ocupacion_maxima_pct == 80.0
    assert p2.urbanisticos.ocupacion_maxima_pct_tipo == 50.0
