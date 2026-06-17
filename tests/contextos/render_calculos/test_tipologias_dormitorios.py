"""Tests del paradigma multi-dormitorio end-to-end (§2.5).

Cubren `combo_override` en `CalcularLayout` (recalculo con una combinación
elegida) y `CalcularTipologiasDormitorios` (enumeración + conteo + poda). Sin
BBDD: usan las constantes del Anexo.
"""
from __future__ import annotations

import math

from shapely.geometry import Polygon

from app.contextos.render_calculos.casos_uso import (
    CalcularLayout,
    CalcularTipologiasDormitorios,
    ParcelaMetrica,
)
from app.contextos.render_calculos.geometria.parcelas import (
    LadoParcela,
    azimut_normal_exterior,
)
from app.contextos.render_calculos.parametros import parametros_desde_dict


def _parcela_cuadrada(lado_m: float = 24.0) -> ParcelaMetrica:
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


def _params_apartamentos(categoria="2L", grupo="edificios") -> "object":
    return parametros_desde_dict({
        "urbanisticos": {"coeficiente_edificabilidad": 2.5, "n_plantas_max": 3, "ocupacion_maxima_pct": 100.0},
        "programa": {
            "uso": "apartamentos_turisticos",
            "categoria_apartamentos": categoria,
            "grupo_apartamentos": grupo,
            "tipologia_apartamento": "doble",
        },
    })


def _params_vivienda() -> "object":
    return parametros_desde_dict({
        "urbanisticos": {"coeficiente_edificabilidad": 2.5, "n_plantas_max": 3, "ocupacion_maxima_pct": 100.0},
        "programa": {"uso": "vivienda", "categoria_vivienda": "2d"},
    })


# ── combo_override en CalcularLayout ─────────────────────────────────────────
def test_combo_override_genera_unidades_con_dos_dormitorios():
    params = _params_apartamentos()
    r = CalcularLayout().ejecutar(
        _parcela_cuadrada(), params, combo_override="doble*1+individual*1",
    )
    assert not r.get("error")
    assert r["capacidad"]["n_viviendas_objetivo"] > 0
    # La tipología real de cada unidad es el slug-combinación.
    slugs = {s for fila in r["capacidad"]["tipologias_unidad_por_planta"] for s in fila}
    assert slugs == {"doble*1+individual*1"}
    # Cada apartamento tiene 2 dormitorios nombrados + salón + cocina + baño.
    fila = next(f for f in r["tabla_unidad"] if f["tipo"] == "apartamento")
    nombres = [e["nombre"] for e in fila["estancias"]]
    assert "dormitorio_1" in nombres and "dormitorio_2" in nombres
    assert "salon_comedor" in nombres and "cocina" in nombres and "bano" in nombres


def test_combo_override_estudio_equivale_a_tipologia_estudio():
    params = _params_apartamentos()
    r = CalcularLayout().ejecutar(_parcela_cuadrada(), params, combo_override="estudio")
    assert not r.get("error")
    fila = next(f for f in r["tabla_unidad"] if f["tipo"] == "apartamento")
    nombres = [e["nombre"] for e in fila["estancias"]]
    # El estudio integra salón y no tiene dormitorio separado.
    assert "salon_comedor" in nombres
    assert "dormitorio_1" not in nombres


def test_combo_mas_grande_cabe_en_menos_unidades_que_uno_mas_pequeno():
    params = _params_apartamentos()
    parcela = _parcela_cuadrada()
    n_indiv = CalcularLayout().ejecutar(parcela, params, combo_override="individual*2")
    n_cuad = CalcularLayout().ejecutar(parcela, params, combo_override="cuadruple*2")
    assert (
        n_indiv["capacidad"]["n_viviendas_objetivo"]
        >= n_cuad["capacidad"]["n_viviendas_objetivo"]
    )


# ── CalcularTipologiasDormitorios (enumeración + poda) ───────────────────────
def test_tipologias_dormitorios_n2_enumera_y_ordena_ascendente():
    params = _params_apartamentos(categoria="2L")
    res = CalcularTipologiasDormitorios().ejecutar(_parcela_cuadrada(48.0), params, n_dorms=2)
    assert not res.get("error")
    assert res["n_dorms"] == 2
    assert res["total_combinaciones"] == 10  # C(4+2-1,2)
    combos = res["combinaciones"]
    assert combos, "debe haber al menos una combinación viable"
    # Útil objetivo ascendente y nº de unidades no-creciente (propiedad de la poda).
    objetivos = [c["util_objetivo_m2"] for c in combos]
    unidades = [c["n_unidades"] for c in combos]
    assert objetivos == sorted(objetivos)
    assert all(a >= b for a, b in zip(unidades, unidades[1:]))
    assert all(c["n_unidades"] >= 1 for c in combos)


def test_tipologias_dormitorios_poda_descarta_las_no_viables():
    # Parcela pequeña: los combos grandes no caben y deben quedar podados.
    params = _params_apartamentos(categoria="4L")
    res = CalcularTipologiasDormitorios().ejecutar(_parcela_cuadrada(20.0), params, n_dorms=3)
    assert res["viables"] + res["podadas"] == res["total_combinaciones"]
    assert res["viables"] == len(res["combinaciones"])


def test_tipologias_dormitorios_estudio_es_n0():
    params = _params_apartamentos()
    res = CalcularTipologiasDormitorios().ejecutar(_parcela_cuadrada(), params, n_dorms=0)
    assert res["total_combinaciones"] == 1
    assert res["combinaciones"][0]["slug"] == "estudio"
    assert res["combinaciones"][0]["etiqueta"] == "Estudio"


def test_tipologias_dormitorios_etiqueta_legible():
    params = _params_apartamentos(categoria="2L")
    res = CalcularTipologiasDormitorios().ejecutar(_parcela_cuadrada(48.0), params, n_dorms=2)
    etiquetas = {c["slug"]: c["etiqueta"] for c in res["combinaciones"]}
    if "individual*2" in etiquetas:
        assert etiquetas["individual*2"] == "2 individuales"
    if "doble*1+individual*1" in etiquetas:
        assert etiquetas["doble*1+individual*1"] == "1 doble + 1 individual"


def test_tipologias_dormitorios_rechaza_uso_hotelero():
    params = parametros_desde_dict({
        "programa": {"uso": "hotelero", "categoria_hotelero": "hotel_3"},
    })
    res = CalcularTipologiasDormitorios().ejecutar(_parcela_cuadrada(), params, n_dorms=2)
    assert res.get("error")
    assert res["combinaciones"] == []


# ── Vivienda: mismo paradigma, alfabeto {individual, doble} ──────────────────
def test_vivienda_combo_override_genera_dormitorios_por_composicion():
    params = _params_vivienda()
    r = CalcularLayout().ejecutar(
        _parcela_cuadrada(40.0), params, combo_override="doble*1+individual*1",
    )
    assert not r.get("error")
    assert r["capacidad"]["n_viviendas_objetivo"] > 0
    slugs = {s for fila in r["capacidad"]["tipologias_unidad_por_planta"] for s in fila}
    assert slugs == {"doble*1+individual*1"}
    fila = next(f for f in r["tabla_unidad"] if f["tipo"] == "vivienda")
    nombres = [e["nombre"] for e in fila["estancias"]]
    assert "dormitorio_1" in nombres and "dormitorio_2" in nombres
    assert "salon" in nombres


def test_vivienda_tipologias_n2_solo_tres_combinaciones():
    # Alfabeto {individual, doble}, N=2 → C(2+2-1,2) = 3 combinaciones.
    params = _params_vivienda()
    res = CalcularTipologiasDormitorios().ejecutar(_parcela_cuadrada(48.0), params, n_dorms=2)
    assert not res.get("error")
    assert res["total_combinaciones"] == 3
    slugs = {c["slug"] for c in res["combinaciones"]}
    # Las viables son un subconjunto de las 3 posibles.
    assert slugs <= {"individual*2", "doble*1+individual*1", "doble*2"}
    objetivos = [c["util_objetivo_m2"] for c in res["combinaciones"]]
    unidades = [c["n_unidades"] for c in res["combinaciones"]]
    assert objetivos == sorted(objetivos)
    assert all(a >= b for a, b in zip(unidades, unidades[1:]))


def test_vivienda_combo_todo_doble_es_mas_grande_que_todo_individual():
    params = _params_vivienda()
    parcela = _parcela_cuadrada(40.0)
    ind = CalcularLayout().ejecutar(parcela, params, combo_override="individual*2")
    dob = CalcularLayout().ejecutar(parcela, params, combo_override="doble*2")
    # Más dobles → vivienda más grande → no más unidades que la versión individual.
    assert (
        ind["capacidad"]["n_viviendas_objetivo"]
        >= dob["capacidad"]["n_viviendas_objetivo"]
    )


def test_vivienda_banos_por_numero_de_dormitorios():
    # Anexo I.5: estudio/1/2 dorm → 1 baño; 3 dorm → 2 baños. En vivienda el
    # criterio es por nº de dormitorios (no por ocupación) y es determinista: el
    # nº de baños no cambia con la holgura de m² (mínimo vs. doble de útil).
    from app.contextos.render_calculos.geometria.combinador_tipologias import (
        ComboDormitorios,
    )
    from app.contextos.render_calculos.geometria.programa import (
        programa_vivienda_combo,
        util_minimo_vivienda_combo,
    )

    def banos(est):
        return [e.nombre for e in est if e.nombre.startswith("bano")]

    for comp, esperado in [
        ({"doble": 1}, ["bano"]),               # 1 dorm
        ({"doble": 2}, ["bano"]),               # 2 dorms
        ({"doble": 3}, ["bano_1", "bano_2"]),   # 3 dorms → 2 baños
    ]:
        combo = ComboDormitorios(comp)
        minimo = util_minimo_vivienda_combo(combo)
        assert banos(programa_vivienda_combo(combo, minimo)) == esperado
        assert banos(programa_vivienda_combo(combo, minimo * 2.0)) == esperado


def test_vivienda_combo_estudio_usa_programa_estudio():
    params = _params_vivienda()
    r = CalcularLayout().ejecutar(_parcela_cuadrada(), params, combo_override="estudio")
    assert not r.get("error")
    fila = next(f for f in r["tabla_unidad"] if f["tipo"] == "vivienda")
    nombres = [e["nombre"] for e in fila["estancias"]]
    assert "espacio_principal" in nombres
    assert "dormitorio_1" not in nombres
