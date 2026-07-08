"""Tests de las combinaciones de tipologías de habitación POR PLANTA (§ hotel).

Cubren el enumerador por área (`enumerar_combinaciones_por_area`), la composición
forzada replicada por planta en el motor (`calcular_capacidad` +
`_colocar_composicion_forzada`) y el caso de uso `CalcularCombinacionesHotel`. Sin
BBDD: usan las constantes del Anexo I.1.
"""
from __future__ import annotations

import math

from shapely.geometry import Polygon

from app.contextos.render_calculos.casos_uso import (
    CalcularCombinacionesHotel,
    CalcularLayout,
    ParcelaMetrica,
)
from app.contextos.render_calculos.geometria.combinador_tipologias import (
    enumerar_combinaciones_por_area,
)
from app.contextos.render_calculos.geometria.parcelas import (
    LadoParcela,
    azimut_normal_exterior,
)
from app.contextos.render_calculos.parametros import parametros_desde_dict


def _parcela_cuadrada(lado_m: float = 30.0) -> ParcelaMetrica:
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


def _params_hotel(extra=("individual",), combinacion="") -> object:
    return parametros_desde_dict({
        "urbanisticos": {"coeficiente_edificabilidad": 3.0, "n_plantas_max": 4,
                         "ocupacion_maxima_pct": 100.0},
        "programa": {
            "uso": "hotelero", "categoria_hotelero": "hotel_3",
            "tipologia_habitacion": "doble", "tipologias_extra": list(extra),
            "combinacion": combinacion,
        },
    })


# ── Enumerador por área ──────────────────────────────────────────────────────
def test_enumerar_ejemplo_del_arquitecto():
    # 100 m² útiles, doble=50, individual=25 → {2 dobles, 1 doble+2 ind, 4 ind}.
    combos, meta = enumerar_combinaciones_por_area(100.0, {"doble": 50.0, "individual": 25.0})
    slugs = {c.slug for c in combos}
    assert slugs == {"doble*2", "doble*1+individual*2", "individual*4"}
    assert meta["total"] == 3
    assert meta["no_caben_tipos"] == []


def test_enumerar_maximalidad_sin_hueco_para_la_mas_pequena():
    # Toda combinación viable deja < min(tamaños) de sobra (no cabe otra unidad).
    combos, _ = enumerar_combinaciones_por_area(100.0, {"doble": 50.0, "individual": 25.0})
    for c in combos:
        usado = 50.0 * c.composicion.get("doble", 0) + 25.0 * c.composicion.get("individual", 0)
        assert usado <= 100.0 + 1e-9
        assert 100.0 - usado < 25.0 - 1e-9  # no cabe ni la individual


def test_enumerar_tipologia_que_no_cabe_ni_una_vez():
    combos, meta = enumerar_combinaciones_por_area(
        100.0, {"doble": 50.0, "individual": 25.0, "triple": 120.0})
    assert "triple" in meta["no_caben_tipos"]
    # La triple no aparece en ninguna combinación viable.
    assert all("triple" not in c.composicion for c in combos)


def test_enumerar_planta_minuscula_no_cabe_nada():
    combos, meta = enumerar_combinaciones_por_area(10.0, {"doble": 50.0, "individual": 25.0})
    assert combos == []
    assert set(meta["no_caben_tipos"]) == {"doble", "individual"}


def test_enumerar_requerir_todas_incluye_cada_tipologia():
    # Con 3 tipologías elegidas, toda combinación debe llevar las 3 presentes.
    tamanos = {"individual": 25.0, "doble": 40.0, "triple": 60.0}
    combos, _ = enumerar_combinaciones_por_area(300.0, tamanos, requerir_todas=True)
    assert combos
    for c in combos:
        assert set(c.composicion) == {"individual", "doble", "triple"}
    # Sin el flag aparecen combinaciones que omiten alguna tipología.
    combos_libres, _ = enumerar_combinaciones_por_area(300.0, tamanos)
    assert any(set(c.composicion) != {"individual", "doble", "triple"} for c in combos_libres)


def test_enumerar_requerir_todas_vacio_si_una_no_cabe():
    # triple no cabe en 30 m² → imposible incluir las tres → lista vacía.
    combos, meta = enumerar_combinaciones_por_area(
        30.0, {"individual": 12.0, "triple": 100.0}, requerir_todas=True)
    assert combos == []
    assert "triple" in meta["no_caben_tipos"]


# ── Composición forzada replicada por planta (motor) ─────────────────────────
def test_composicion_forzada_replica_misma_mezcla_en_cada_planta():
    parcela = _parcela_cuadrada(30.0)
    # Enumerar y elegir una combinación intermedia.
    res = CalcularCombinacionesHotel().ejecutar(parcela, _params_hotel())
    assert res["combinaciones"], res
    elegida = res["combinaciones"][len(res["combinaciones"]) // 2]
    slug = elegida["slug"]

    r = CalcularLayout().ejecutar(parcela, _params_hotel(combinacion=slug))
    assert not r.get("error"), r
    cap = r["capacidad"]
    # Plantas tipo (no PB) llevan la composición exacta elegida; la accesibilidad
    # DB-SUA puede reajustar las plantas bajas, así que se comprueba una planta alta.
    tipos = cap["tipo_planta"]
    comp_esperada = elegida["composicion"]
    plantas_altas = [
        i for i, t in enumerate(tipos)
        if t != "sotano" and cap["nombres_planta"][i] not in ("PB",)
    ]
    assert plantas_altas, "debe haber al menos una planta tipo"
    fila = cap["tipologias_unidad_por_planta"][plantas_altas[-1]]
    counts: dict[str, int] = {}
    for s in fila:
        counts[s] = counts.get(s, 0) + 1
    assert counts == {k: v for k, v in comp_esperada.items()}


def test_composicion_forzada_truncada_en_planta_con_menos_util():
    # PB con muchos usos comunes → menos útil que las tipo: la composición se trunca ahí.
    parcela = _parcela_cuadrada(30.0)
    res = CalcularCombinacionesHotel().ejecutar(parcela, _params_hotel())
    # La combinación que MÁS llena la planta (más unidades) es la más propensa a truncar.
    slug = max(res["combinaciones"], key=lambda c: c["unidades_por_planta"])["slug"]
    params = parametros_desde_dict({
        "urbanisticos": {"coeficiente_edificabilidad": 3.0, "n_plantas_max": 4,
                         "ocupacion_maxima_pct": 100.0},
        "programa": {
            "uso": "hotelero", "categoria_hotelero": "hotel_3",
            "tipologia_habitacion": "doble", "tipologias_extra": ["individual"],
            "combinacion": slug, "usos_comunes_pb_m2": 400.0,
        },
    })
    r = CalcularLayout().ejecutar(parcela, params)
    assert not r.get("error"), r
    assert r["capacidad"]["composicion_truncada"] is True


# ── Caso de uso CalcularCombinacionesHotel ───────────────────────────────────
def test_combinaciones_hotel_rechaza_no_hotel():
    params = parametros_desde_dict({"programa": {"uso": "vivienda"}})
    res = CalcularCombinacionesHotel().ejecutar(_parcela_cuadrada(), params)
    assert res.get("error")
    assert res["combinaciones"] == []


def test_combinaciones_hotel_devuelve_cifras_por_planta():
    res = CalcularCombinacionesHotel().ejecutar(_parcela_cuadrada(30.0), _params_hotel())
    assert not res.get("error")
    assert res["util_planta_m2"] > 0
    assert res["combinaciones"]
    for c in res["combinaciones"]:
        assert c["unidades_por_planta"] == sum(c["composicion"].values())
        assert c["util_usado_m2"] <= res["util_planta_m2"] + 1e-6
        # Toda combinación incluye las DOS tipologías elegidas (doble + individual).
        assert set(c["composicion"]) == {"doble", "individual"}
    # Ordenado por plazas descendente.
    plazas = [c["plazas_por_planta"] for c in res["combinaciones"]]
    assert plazas == sorted(plazas, reverse=True)
