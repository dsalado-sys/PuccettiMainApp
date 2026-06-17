"""Tests de la parte matemática de A1.1, A1.2 y A1.4 + multi-tipología por uso."""
from __future__ import annotations

import math

import pytest
from shapely.geometry import Polygon

from app.contextos.render_calculos.casos_uso import CalcularLayout, ParcelaMetrica
from app.contextos.render_calculos.geometria import programa_apartamentos as pa
from app.contextos.render_calculos.geometria import programa_hotel_apartamento as hap
from app.contextos.render_calculos.geometria import programa_hotelero as ph
from app.contextos.render_calculos.geometria.parcelas import (
    LadoParcela,
    azimut_normal_exterior,
)
from app.contextos.render_calculos.geometria.programa_uso import (
    reparto_multi_tipologia_generico,
)
from app.contextos.render_calculos.parametros import (
    parametros_a_dict,
    parametros_desde_dict,
)


# ── A1.1 Hotelero (modelo de habitación) ────────────────────────────────────
def test_hotelero_util_objetivo_y_estancias():
    # hotel_3 doble: habitación 17 + baño objetivo (3.5 + 0.5) = 21.0; objetivo ×1.15.
    assert ph.util_minimo_habitacion("hotel_3", "doble") == pytest.approx(21.0, abs=0.01)
    assert ph.util_objetivo_habitacion("hotel_3", "doble") == pytest.approx(21.0 * 1.15, abs=0.01)
    estancias = ph.programa_habitacion("doble", "hotel_3", 24.0)
    assert [e.nombre for e in estancias] == ["habitacion", "bano"]


def test_hotelero_pension_y_albergue_sin_bano_interior():
    # Pensión y albergue admiten baño compartido → la unidad no lleva baño.
    assert [e.nombre for e in ph.programa_habitacion("doble", "pension", 13.0)] == ["habitacion"]
    assert [e.nombre for e in ph.programa_habitacion("individual", "albergue", 9.0)] == ["habitacion"]


def test_hotelero_areas_sociales_por_ua_y_por_plaza():
    # Hotel 5*: 4 m² por u.a. (salón mínimo 12 si pocas unidades).
    assert ph.areas_sociales_obligatorias_hotel(10, 20, "hotel_5") == {"salon_social": 40.0}
    # Albergue: 1 m² por plaza (no por u.a.).
    assert ph.areas_sociales_obligatorias_hotel(5, 30, "albergue") == {"salon_social": 30.0}
    # Hostal 1* / pensión: sin exigencia por u.a. pero conservan el salón mínimo (8).
    assert ph.areas_sociales_obligatorias_hotel(3, 6, "pension") == {"salon_social": 8.0}


# ── A1.2 Hotel-apartamento (por ocupación de dormitorio) ────────────────────
def test_hotel_apartamento_util_y_estancias():
    # 3E doble: salón-comedor 12 + dormitorio doble 15 + baño 3.5 = 30.5 base; objetivo ×1.15.
    base = 12.0 + 15.0 + 3.5
    assert hap.util_minimo_hotel_apartamento("3E", "doble") == pytest.approx(base, abs=0.01)
    assert hap.util_objetivo_hotel_apartamento("3E", "doble") == pytest.approx(base * 1.15, abs=0.01)
    estancias = hap.programa_hotel_apartamento("doble", "3E", 50.0)
    assert [e.nombre for e in estancias] == ["salon_comedor", "dormitorio_1", "bano"]


def test_hotel_apartamento_areas_sociales_como_hotel():
    # 5E: 4 m² por u.a. (como Hotel del mismo nº de estrellas).
    assert hap.areas_sociales_obligatorias_hap(4, "5E") == {"areas_sociales": 16.0}


# ── Apartamento turístico por ocupación de dormitorio (A1.3) ────────────────
def test_apartamento_salon_comedor_dormitorio_cocina_bano():
    # 4L cuádruple: 4 plazas + 2 del salón = 6 personas > 4 (umbral 3L/4L) → 2 baños.
    # Y 6 personas → 2 por encima de 4 → salón = 16 + 2 × 4 (SUP 4L) = 24.
    est = {e.nombre: e for e in pa.programa_apartamentos("cuadruple", "4L", 0.0)}
    assert list(est) == ["salon_comedor", "dormitorio_1", "cocina", "bano_1", "bano_2"]
    assert est["salon_comedor"].area_min_m2 == pytest.approx(24.0)   # 16 base + 2 plazas × 4 (SUP 4L)
    assert est["dormitorio_1"].area_min_m2 == pytest.approx(27.0)    # dormitorio cuádruple 4L
    assert est["cocina"].area_min_m2 == pytest.approx(8.0)
    assert est["bano_1"].area_min_m2 == pytest.approx(4.0)
    assert est["bano_2"].area_min_m2 == pytest.approx(4.0)


# ── A1.4 Apartamentos conjuntos ─────────────────────────────────────────────
def test_conjuntos_cocina_y_bano_separados_y_clamp_categoria():
    estancias = pa.programa_apartamentos("doble", "2L", 40.0, grupo="conjuntos")
    nombres = [e.nombre for e in estancias]
    assert nombres == ["salon_comedor", "dormitorio_1", "cocina", "bano"]
    # 3L no existe en conjuntos → se acota a 2L sin reventar.
    estancias_clamp = pa.programa_apartamentos("estudio", "3L", 25.0, grupo="conjuntos")
    assert [e.nombre for e in estancias_clamp] == ["salon_comedor", "bano"]


def test_conjuntos_sin_areas_sociales_vestibulo_solo_si_mas_de_15():
    assert pa.areas_comunes_obligatorias(5, "2L", grupo="conjuntos") == {}
    comunes = pa.areas_comunes_obligatorias(20, "2L", grupo="conjuntos")
    assert comunes == {"vestibulo_recepcion": pytest.approx(6.0, abs=0.01)}


def test_edificios_areas_comunes_exactas_del_doc():
    # 2L / 1L: sin áreas sociales (Anexo I.3).
    assert pa.areas_comunes_obligatorias(5, "2L") == {}
    # 4L: 2 m²/u.a. de áreas sociales; vestíbulo solo si >15 u.a.
    assert pa.areas_comunes_obligatorias(5, "4L") == {"areas_sociales": 10.0}
    assert pa.areas_comunes_obligatorias(20, "4L") == {
        "areas_sociales": 40.0,
        "vestibulo_recepcion": pytest.approx(10.0, abs=0.01),
    }


# ── Reparto multi-tipología use-agnóstico ───────────────────────────────────
def test_reparto_generico_mezcla_dos_tipologias():
    desc = [
        ph.descriptor_tipologia_hotelero("hotel_3", "doble"),
        ph.descriptor_tipologia_hotelero("hotel_3", "triple"),
    ]
    seleccion = reparto_multi_tipologia_generico(200.0, desc)
    slugs = {d.slug for d, _ in seleccion}
    assert slugs == {"doble", "triple"}          # al menos una de cada
    assert len(seleccion) >= 2


def test_reparto_generico_vacio_si_no_cabe():
    desc = [pa.descriptor_tipologia_apartamento("2L", "cuadruple")]
    assert reparto_multi_tipologia_generico(5.0, desc) == []


# ── Round-trip de parámetros ────────────────────────────────────────────────
def test_parametros_roundtrip_campos_nuevos():
    base = {
        "programa": {
            "uso": "hotel_apartamento",
            "categoria_hotel_apartamento": "4E",
            "tipologia_apartamento": "doble",
            "tipologias_extra": ["individual", "estudio"],
        },
    }
    p = parametros_desde_dict(base)
    assert p.programa.uso.value == "hotel_apartamento"
    assert p.programa.categoria_hotel_apartamento.value == "4E"
    assert p.programa.tipologia_apartamento.value == "doble"
    assert p.programa.tipologias_extra == ["individual", "estudio"]
    # round-trip estable.
    p2 = parametros_desde_dict(parametros_a_dict(p))
    assert p2.programa.categoria_hotel_apartamento.value == "4E"
    assert p2.programa.tipologia_apartamento.value == "doble"
    assert p2.programa.tipologias_extra == ["individual", "estudio"]


def test_grupo_apartamentos_default_edificios_en_json_antiguo():
    # JSON sin grupo_apartamentos → "edificios" (no cambia resultados guardados).
    p = parametros_desde_dict({"programa": {"uso": "apartamentos_turisticos"}})
    assert p.programa.grupo_apartamentos.value == "edificios"


def test_tipologias_extra_se_filtran_por_uso():
    # Slugs de vivienda no son válidos en hotelero → se descartan.
    p = parametros_desde_dict({
        "programa": {"uso": "hotelero", "tipologias_extra": ["doble", "2d", "triple"]},
    })
    assert p.programa.tipologias_extra == ["doble", "triple"]


# ── End-to-end matemático (sin BBDD: usa constantes del motor) ───────────────
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


def _calcular(payload: dict) -> dict:
    params = parametros_desde_dict({
        "urbanisticos": {"coeficiente_edificabilidad": 2.5, "n_plantas_max": 3, "ocupacion_maxima_pct": 100.0},
        "programa": payload,
    })
    # Sin catálogos → usa constantes del motor (no toca BBDD).
    return CalcularLayout().ejecutar(_parcela_cuadrada(), params)


def test_e2e_hotelero_mezcla_produce_dos_tipologias():
    r = _calcular({
        "uso": "hotelero", "categoria_hotelero": "hotel_3",
        "tipologia_habitacion": "doble", "tipologias_extra": ["triple"],
    })
    assert r["capacidad"]["n_viviendas_objetivo"] > 0
    filas = [f for f in r["tabla_unidad"] if f["tipo"] == "habitacion"]
    assert filas, "debe haber habitaciones"
    # cada habitación tiene la estancia 'habitacion' (+ baño en hotel).
    for f in filas:
        nombres = [e["nombre"] for e in f["estancias"]]
        assert "habitacion" in nombres
    # la mezcla genera ambas tipologías en la planta.
    slugs = {s for fila in r["capacidad"]["tipologias_unidad_por_planta"] for s in fila}
    assert {"doble", "triple"} <= slugs


def test_e2e_apartamentos_conjuntos_reserva_vestibulo_si_muchas_unidades():
    r = _calcular({
        "uso": "apartamentos_turisticos", "grupo_apartamentos": "conjuntos",
        "categoria_apartamentos": "2L", "tipologia_apartamento": "doble",
    })
    cap = r["capacidad"]
    assert cap["n_viviendas_objetivo"] > 0
    # En conjuntos el apartamento lleva cocina separada.
    fila = next(f for f in r["tabla_unidad"] if f["tipo"] == "apartamento")
    assert "cocina" in [e["nombre"] for e in fila["estancias"]]
    assert fila["tipologia"] == "doble"


def test_e2e_vivienda_no_regresion_mezcla():
    r = _calcular({"uso": "vivienda", "categoria_vivienda": "2d", "tipologias_extra": ["1d"]})
    assert r["capacidad"]["n_viviendas_objetivo"] > 0
    tipos = {f["tipo"] for f in r["tabla_unidad"] if f["tipo"] != "local"}
    assert tipos == {"vivienda"}
