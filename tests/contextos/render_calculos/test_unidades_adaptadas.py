"""Unidades adaptadas automáticas — integración (§2.5 / DB-SUA).

Verifica end-to-end (vía `CalcularLayout`) que: vivienda no adapta; los usos
turísticos marcan el nº por tramo, reducen capacidad y agrandan las adaptadas; y
que el agrandado por estancia respeta el modo (total vs parcial). El cálculo es
el MISMO para Obra Nueva y Rehabilitación (ambas corren `CalcularLayout`), por lo
que la lógica de adaptación es independiente del modo.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

from shapely.geometry import Polygon

from app.contextos.render_calculos.casos_uso import CalcularLayout, ParcelaMetrica
from app.contextos.render_calculos.geometria.parcelas import (
    LadoParcela,
    azimut_normal_exterior,
)
from app.contextos.render_calculos.geometria.serializacion import (
    _estancias_por_unidad_dorms,
)
from app.contextos.render_calculos.parametros import parametros_desde_dict


def _parcela_cuadrada(lado_m: float = 28.0) -> ParcelaMetrica:
    coords = [(0.0, 0.0), (lado_m, 0.0), (lado_m, lado_m), (0.0, lado_m)]
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
    )


def _params(uso: str, **prog) -> object:
    return parametros_desde_dict({
        "urbanisticos": {"coeficiente_edificabilidad": 2.5, "n_plantas_max": 3,
                         "ocupacion_maxima_pct": 100.0},
        "programa": {"uso": uso, **prog},
    })


def _params_apartamentos() -> object:
    return _params("apartamentos_turisticos", categoria_apartamentos="2L",
                   grupo_apartamentos="edificios", tipologia_apartamento="doble")


def _filas_unidad(resultado) -> list[dict]:
    """Filas de la tabla que son unidades reales (no reservas local/otros/comunes)."""
    reservas = {"local", "otros", "usos_comunes"}
    return [r for r in resultado["tabla_unidad"] if r.get("tipo") not in reservas]


# ── Vivienda: nunca se adapta ────────────────────────────────────────────────
def test_vivienda_no_tiene_unidades_adaptadas():
    r = CalcularLayout().ejecutar(_parcela_cuadrada(), _params("vivienda", categoria_vivienda="2d"))
    assert not r.get("error")
    assert r["capacidad"]["n_unidades_adaptadas"] == 0
    assert all(not row["adaptada"] for row in _filas_unidad(r))


# ── Usos turísticos: marca por tramo + reduce capacidad + agranda ────────────
def test_apartamentos_marca_por_tramo_y_es_coherente():
    r = CalcularLayout().ejecutar(_parcela_cuadrada(28.0), _params_apartamentos())
    assert not r.get("error")
    cap = r["capacidad"]
    total = cap["n_viviendas_objetivo"]
    assert total > 5  # parcela mediana → tramo "total"
    assert cap["modo_adaptacion"] == "total"
    # Hay ≥1 adaptada y coincide con el nº de filas marcadas.
    filas = _filas_unidad(r)
    adaptadas = [f for f in filas if f["adaptada"]]
    assert cap["n_unidades_adaptadas"] >= 1
    assert len(adaptadas) == cap["n_unidades_adaptadas"]
    # La adaptada lleva su tamaño REAL ~1.25× el de una estándar de su tipología.
    ad = adaptadas[0]
    estandar = next(f for f in filas if not f["adaptada"] and f.get("tipologia") == ad.get("tipologia"))
    assert abs(ad["util_por_unidad_m2"] - 1.25 * estandar["util_por_unidad_m2"]) < 0.6


def test_edificio_grande_pierde_unidades_en_la_planta_de_las_adaptadas():
    """Cuando el agrandado no cabe en la holgura (≥4 adaptadas), la planta que las
    aloja pierde unidades estándar; las superiores mantienen su capacidad."""
    params = parametros_desde_dict({
        "urbanisticos": {"coeficiente_edificabilidad": 6.0, "n_plantas_max": 4,
                         "ocupacion_maxima_pct": 100.0},
        "programa": {"uso": "apartamentos_turisticos", "categoria_apartamentos": "1L",
                     "grupo_apartamentos": "edificios", "tipologia_apartamento": "doble"},
    })
    r = CalcularLayout().ejecutar(_parcela_cuadrada(44.0), params)
    assert not r.get("error")
    cap = r["capacidad"]
    assert cap["n_unidades_adaptadas"] >= 4  # tramo que fuerza recorte
    filas = _filas_unidad(r)
    planta_ad = next(f["planta"] for f in filas if f["adaptada"])
    viv = dict(zip(cap["nombres_planta"], cap["viv_por_planta"]))
    # Plantas regulares con unidades, distintas de la de las adaptadas.
    otras = [n for n, v in viv.items() if n != planta_ad and v > 0]
    assert otras and all(viv[planta_ad] < viv[n] for n in otras)


def test_hotel_usa_factor_30():
    r = CalcularLayout().ejecutar(
        _parcela_cuadrada(28.0),
        _params("hotelero", categoria_hotelero="hotel_3", tipologia_habitacion="doble"),
    )
    assert not r.get("error")
    cap = r["capacidad"]
    assert cap["n_unidades_adaptadas"] >= 1
    filas = _filas_unidad(r)
    adaptadas = [f for f in filas if f["adaptada"]]
    assert len(adaptadas) == cap["n_unidades_adaptadas"]
    ad = adaptadas[0]
    estandar = next(f for f in filas if not f["adaptada"] and f.get("tipologia") == ad.get("tipologia"))
    # +30%: la habitación adaptada lleva su tamaño real ~1.3×.
    assert abs(ad["util_por_unidad_m2"] - 1.30 * estandar["util_por_unidad_m2"]) < 0.6


def test_modo_parcial_solo_en_edificios_diminutos():
    """`parcial` solo puede salir si el edificio tiene 1–5 alojamientos."""
    for lado in (14.0, 20.0, 30.0):
        r = CalcularLayout().ejecutar(_parcela_cuadrada(lado), _params_apartamentos())
        if r.get("error"):
            continue
        cap = r["capacidad"]
        assert cap["modo_adaptacion"] in ("total", "parcial")
        if cap["modo_adaptacion"] == "parcial":
            assert cap["n_viviendas_objetivo"] <= 5


# ── Agrandado por estancia (serialización), determinista ─────────────────────
def _estancias_dict(es_adaptada=False, modo="total", factor=1.0):
    params = _params_apartamentos()
    programa_uso = SimpleNamespace(tipo_unidad="apartamento")
    estancias = _estancias_por_unidad_dorms(
        params, 1, 50.0, programa_uso, slug="doble",
        es_adaptada=es_adaptada, modo=modo, factor=factor,
    )
    return {e["nombre"]: e["area_target_m2"] for e in estancias}


def test_agrandado_total_crece_toda_la_unidad():
    base = _estancias_dict()
    adap = _estancias_dict(es_adaptada=True, modo="total", factor=1.25)
    for nombre, area in base.items():
        if nombre.startswith("circulacion"):
            continue
        assert abs(adap[nombre] - round(area * 1.25, 2)) < 0.05, nombre
    # La unidad entera (incl. circulación) crece ~1.25×.
    assert abs(sum(adap.values()) - 1.25 * sum(base.values())) < 1.0


def test_agrandado_parcial_solo_dormitorio_y_bano():
    base = _estancias_dict()
    adap = _estancias_dict(es_adaptada=True, modo="parcial", factor=1.25)
    for nombre, area in base.items():
        if nombre.startswith("dormitorio") or nombre.startswith("bano") or nombre.startswith("aseo"):
            assert adap[nombre] > area, nombre
        elif nombre.startswith("salon") or nombre == "cocina":
            assert adap[nombre] == area, nombre
