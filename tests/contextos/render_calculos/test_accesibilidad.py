"""Tests de la asignación automática de unidades adaptadas (DB-SUA, §2.5).

Funciones puras de `geometria/accesibilidad.py`: tabla de tramos, modo, factor,
usos adaptables, qué estancias se agrandan y el punto fijo que reduce capacidad.
"""
from __future__ import annotations

from app.contextos.render_calculos.geometria.accesibilidad import (
    _repack_adaptadas,
    es_uso_adaptable,
    estancia_se_agranda,
    factor_agrandado,
    modo_adaptacion,
    n_unidades_adaptadas,
)
from app.contextos.render_calculos.geometria.capacidad import Capacidad


def _capacidad_3_plantas(uds_por_planta: int = 10, util: float = 30.0) -> Capacidad:
    """Capacidad mínima de 3 plantas regulares idénticas con unidades de `util` m²,
    sin holgura (útil disponible = suma exacta), para probar el repack."""
    fila = [(1, util)] * uds_por_planta
    return Capacidad(
        superficie_parcela_m2=0, coeficiente_edificabilidad=0, edificabilidad_m2=0,
        ocupacion_maxima=0, n_plantas_solicitadas=3, n_plantas_edificables=3,
        huella_m2=0, ocupacion_area_m2=0, huella_efectiva_m2=0, construida_prevista_m2=0,
        factor_limitante="", n_dormitorios=1, util_objetivo_viv_m2=util,
        util_planta_disponible_m2=uds_por_planta * util, viv_por_planta_objetivo=uds_por_planta,
        n_viviendas_objetivo=3 * uds_por_planta, pct_muros=0, pct_circulacion_pb=0,
        pct_circulacion_tipo=0, pct_nucleo=0,
        viv_por_planta=[uds_por_planta] * 3,
        util_por_planta=[uds_por_planta * util] * 3,
        unidades_por_planta=[list(fila), list(fila), list(fila)],
        tipologias_unidad_por_planta=[["doble"] * uds_por_planta for _ in range(3)],
        tipo_planta=["regular", "regular", "regular"],
        nombres_planta=["PB", "P1", "P2"],
        viviendas_por_tipologia=[{"doble": uds_por_planta} for _ in range(3)],
    )


def test_tramos_n_unidades_adaptadas():
    casos = {
        0: 0, 1: 1, 5: 1, 6: 1, 50: 1, 51: 2, 100: 2, 101: 4, 150: 4,
        151: 6, 200: 6, 201: 8, 250: 8, 251: 9, 300: 9, 301: 10, 351: 11,
    }
    for total, esperado in casos.items():
        assert n_unidades_adaptadas(total) == esperado, total


def test_modo_parcial_solo_1_a_5():
    for n in range(1, 6):
        assert modo_adaptacion(n) == "parcial", n
    for n in (0, 6, 7, 50, 200, 500):
        assert modo_adaptacion(n) == "total", n


def test_factor_por_uso():
    assert factor_agrandado("apartamento") == 1.25
    assert factor_agrandado("habitacion") == 1.30
    assert factor_agrandado("hotel_apartamento") == 1.30
    assert factor_agrandado("vivienda") == 1.0
    assert factor_agrandado("desconocido") == 1.0


def test_usos_adaptables_excluyen_vivienda():
    for t in ("apartamento", "habitacion", "hotel_apartamento"):
        assert es_uso_adaptable(t)
    assert not es_uso_adaptable("vivienda")


def test_estancia_se_agranda_modo_total():
    for nombre in ("salon_comedor", "dormitorio_1", "cocina", "bano", "habitacion"):
        assert estancia_se_agranda(nombre, "total")
    assert not estancia_se_agranda("circulacion_interior", "total")


def test_estancia_se_agranda_modo_parcial():
    for nombre in ("dormitorio_1", "dormitorio_2", "habitacion", "bano", "bano_2", "aseo", "aseo_2"):
        assert estancia_se_agranda(nombre, "parcial"), nombre
    for nombre in ("salon_comedor", "salon", "cocina", "circulacion_interior"):
        assert not estancia_se_agranda(nombre, "parcial"), nombre


def test_repack_agranda_en_pb_y_reduce_solo_esa_planta():
    # 30 unidades (10/planta) de 30 m², 4 adaptadas. Las 4 caben en PB: se agrandan
    # a 37.5 m² y PB pierde unidades estándar para que quepa; P1/P2 intactas.
    cap = _capacidad_3_plantas(uds_por_planta=10, util=30.0)
    out = _repack_adaptadas(cap, 4, 1.25)
    pb = out.unidades_por_planta[0]
    # Las 4 primeras de PB son las adaptadas, con su útil real agrandado.
    assert all(abs(u - 37.5) < 1e-6 for _, u in pb[:4])
    assert all(abs(u - 30.0) < 1e-6 for _, u in pb[4:])
    # PB cabe en su útil disponible (300 m²) y aloja MENOS unidades que las de arriba.
    assert sum(u for _, u in pb) <= cap.util_por_planta[0] + 1e-6
    assert out.viv_por_planta[0] < out.viv_por_planta[1]
    assert out.viv_por_planta[1] == 10 and out.viv_por_planta[2] == 10
    # El total emerge del área (no de un descuento global arbitrario).
    assert out.n_viviendas_objetivo == sum(out.viv_por_planta)


def test_repack_sin_recorte_si_hay_holgura():
    # Con holgura suficiente, agrandar 1 unidad no obliga a perder ninguna.
    cap = _capacidad_3_plantas(uds_por_planta=10, util=30.0)
    cap = replace_util_disp(cap, 360.0)  # 60 m² de holgura por planta
    out = _repack_adaptadas(cap, 1, 1.25)
    assert out.viv_por_planta == [10, 10, 10]
    assert abs(out.unidades_por_planta[0][0][1] - 37.5) < 1e-6


def replace_util_disp(cap: Capacidad, util_disp: float) -> Capacidad:
    from dataclasses import replace
    return replace(cap, util_por_planta=[util_disp] * 3)
