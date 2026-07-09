"""Combinaciones de tipos de unidad POR PLANTA (vivienda / apartamentos turísticos).

Espejo de `test_combinaciones_hotel.py` pero para el paradigma por dormitorios: el
arquitecto define varios tipos de unidad (`programa.tipos_unidad`, combo-slugs) y el
sistema enumera las mezclas de unidades enteras que caben en una planta representativa
(`enumerar_combinaciones_por_area`, `requerir_todas=True`). La mezcla elegida
(`mezcla_planta`, lista plana) se replica en cada planta habitable vía
`composicion_planta_forzada`. Sin BBDD: usan las constantes del Anexo I.
"""
from __future__ import annotations

import math
from collections import Counter

from shapely.geometry import Polygon

from app.contextos.render_calculos.casos_uso import (
    CalcularCombinacionesPorPlanta,
    CalcularLayout,
    ParcelaMetrica,
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


def _params(uso, tipos, mezcla=None, prog_extra=None):
    urbanisticos = {"coeficiente_edificabilidad": 3.0, "n_plantas_max": 4,
                    "ocupacion_maxima_pct": 100.0}
    prog = {"uso": uso, "tipos_unidad": list(tipos)}
    if mezcla is not None:
        prog["mezcla_planta"] = list(mezcla)
    if uso == "apartamentos_turisticos":
        prog.setdefault("categoria_apartamentos", "2L")
        prog.setdefault("grupo_apartamentos", "edificios")
    if prog_extra:
        prog.update(prog_extra)
    return parametros_desde_dict({"urbanisticos": urbanisticos, "programa": prog})


# ── Enumerador por uso ───────────────────────────────────────────────────────
def test_vivienda_devuelve_cifras_por_planta():
    params = _params("vivienda", ["doble*1", "doble*1+individual*1"])
    res = CalcularCombinacionesPorPlanta().ejecutar(_parcela_cuadrada(30.0), params)
    assert not res.get("error"), res
    assert res["util_planta_m2"] > 0
    assert res["combinaciones"]
    for c in res["combinaciones"]:
        # requerir_todas: cada mezcla incluye los dos tipos definidos.
        assert set(c["composicion"]) == {"doble*1", "doble*1+individual*1"}
        assert c["unidades_por_planta"] == len(c["mezcla"])
        assert c["unidades_por_planta"] == sum(c["composicion"].values())
        assert c["util_usado_m2"] <= res["util_planta_m2"] + 1e-6
        assert "slug" not in c  # nunca `.slug` en vivienda/apartamento (colisiona)
    # Ordenado por plazas descendente.
    plazas = [c["plazas_por_planta"] for c in res["combinaciones"]]
    assert plazas == sorted(plazas, reverse=True)


def test_apartamentos_admite_estudio_y_dobles():
    params = _params("apartamentos_turisticos", ["estudio", "doble*2"])
    res = CalcularCombinacionesPorPlanta().ejecutar(_parcela_cuadrada(30.0), params)
    assert not res.get("error"), res
    assert res["combinaciones"]
    for c in res["combinaciones"]:
        assert set(c["composicion"]) == {"estudio", "doble*2"}


def test_sin_tipos_definidos_error():
    params = _params("vivienda", [])
    res = CalcularCombinacionesPorPlanta().ejecutar(_parcela_cuadrada(30.0), params)
    assert res.get("error")
    assert res["combinaciones"] == []


# ── Integración: la mezcla elegida se coloca por planta ──────────────────────
def test_mezcla_forzada_se_replica_en_planta_alta():
    parcela = _parcela_cuadrada(30.0)
    params = _params("vivienda", ["doble*1", "doble*1+individual*1"])
    res = CalcularCombinacionesPorPlanta().ejecutar(parcela, params)
    elegida = res["combinaciones"][len(res["combinaciones"]) // 2]
    mezcla = elegida["mezcla"]

    params_forzado = _params(
        "vivienda", list(dict.fromkeys(mezcla)), mezcla=mezcla,
    )
    r = CalcularLayout().ejecutar(parcela, params_forzado)
    assert not r.get("error"), r
    cap = r["capacidad"]
    tipos = cap["tipo_planta"]
    altas = [i for i, t in enumerate(tipos)
             if t != "sotano" and cap["nombres_planta"][i] != "PB"]
    assert altas, "debe haber al menos una planta tipo"
    fila = cap["tipologias_unidad_por_planta"][altas[-1]]
    assert dict(Counter(fila)) == dict(Counter(mezcla))


def test_truncado_en_pb_con_menos_util():
    parcela = _parcela_cuadrada(30.0)
    params = _params("apartamentos_turisticos", ["estudio", "doble*2"])
    res = CalcularCombinacionesPorPlanta().ejecutar(parcela, params)
    # La mezcla con más unidades es la más propensa a truncar en una PB con reservas.
    elegida = max(res["combinaciones"], key=lambda c: c["unidades_por_planta"])
    params_forzado = _params(
        "apartamentos_turisticos", list(dict.fromkeys(elegida["mezcla"])),
        mezcla=elegida["mezcla"], prog_extra={"usos_comunes_pb_m2": 400.0},
    )
    r = CalcularLayout().ejecutar(parcela, params_forzado)
    assert not r.get("error"), r
    assert r["capacidad"]["composicion_truncada"] is True


# ── Paridad de sizer: enumerador ↔ colocación ────────────────────────────────
def test_sizer_paridad_enumerador_vs_composicion():
    parcela = _parcela_cuadrada(30.0)
    tipos = ["doble*1", "doble*1+individual*1"]
    params = _params("vivienda", tipos)
    layout = CalcularLayout()
    cfg = layout._sincronizar_minimos(params)
    from app.contextos.render_calculos.geometria.programa import (
        util_objetivo_vivienda_combo,
    )
    from app.contextos.render_calculos.geometria.combinador_tipologias import slug_a_combo
    # El sizer de la colocación (`_composicion_planta_dorms`) usa el mismo m² por tipo
    # que el enumerador → sin drift entre lo enumerado y lo colocado.
    comp = layout._composicion_planta_dorms(params, tipos, cfg)
    por_slug = {slug: util for slug, util, _ in comp}
    for s in tipos:
        esperado = util_objetivo_vivienda_combo(slug_a_combo(s), False, cfg)
        assert por_slug[s] == esperado


# ── Estancias por unidad casan con el combo elegido ──────────────────────────
def test_estancias_por_unidad_casan_con_combo():
    parcela = _parcela_cuadrada(30.0)
    mezcla = ["doble*1+individual*1"]
    params = _params("vivienda", ["doble*1+individual*1"], mezcla=mezcla)
    r = CalcularLayout().ejecutar(parcela, params)
    assert not r.get("error"), r
    unidades = [u for u in r["tabla_unidad"] if u.get("tipo") == "vivienda"]
    assert unidades
    assert all(u["tipologia"] == "doble*1+individual*1" for u in unidades)
    assert all(u.get("estancias") for u in unidades)
