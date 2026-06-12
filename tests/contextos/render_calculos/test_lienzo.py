"""Tests del lienzo de dibujo manual sobre la parcela (§2.4 — capa manual).

Cubre el recorte geométrico a la parcela (Shapely), el resumen por color y los
casos de uso de persistencia (sin pisar los parámetros del módulo).
"""
from __future__ import annotations

import math

import pytest
from shapely.geometry import Polygon

from app.contextos.render_calculos.casos_uso import ParcelaMetrica
from app.contextos.render_calculos.casos_uso_lienzo import (
    CalcularLienzo,
    CargarLienzo,
    GuardarLienzo,
)
from app.contextos.render_calculos.geometria.lienzo import (
    recortar_muro,
    recortar_poligono,
    resumen_por_color,
)
from app.nucleo.modelo import ModuloPuccetti, Proyecto
from app.plataforma.persistencia.proyectos_en_memoria import ProyectosEnMemoria

# Parcela cuadrada 10×10 en metros (UTM30N para los tests).
PARCELA = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])

# Parcela en "U": rectángulo 10×10 menos la ranura superior [3,7]×[3,10].
PARCELA_U = Polygon([
    (0, 0), (10, 0), (10, 10), (7, 10), (7, 3), (3, 3), (3, 10), (0, 10),
])


def _pm(poly: Polygon = PARCELA) -> ParcelaMetrica:
    return ParcelaMetrica(
        poligono_utm=poly,
        lados=[],
        municipio="Sevilla",
        provincia="Sevilla",
        centroide_lonlat=None,
        referencia_catastral=None,
    )


# ── recortar_poligono ───────────────────────────────────────────────────────
def test_superficie_integra_dentro():
    rings, area = recortar_poligono([[2, 2], [8, 2], [8, 8], [2, 8]], PARCELA)
    assert area == pytest.approx(36.0)
    assert len(rings) == 1


def test_superficie_media_fuera_solo_cuenta_lo_de_dentro():
    # Cuadrado [5,15]² ∩ parcela [0,10]² = [5,10]² = 25 m².
    rings, area = recortar_poligono([[5, 5], [15, 5], [15, 15], [5, 15]], PARCELA)
    assert area == pytest.approx(25.0)
    assert len(rings) == 1


def test_superficie_totalmente_fuera():
    rings, area = recortar_poligono([[20, 20], [30, 20], [30, 30], [20, 30]], PARCELA)
    assert rings == []
    assert area == 0.0


def test_superficie_auto_intersecante_bowtie_no_peta():
    # "Pajarita": polígono auto-intersecante. buffer(0) lo valida (colapsa el
    # lóbulo de orientación opuesta) → un polígono válido de 25 m². Lo clave es
    # que NO peta y devuelve un área finita positiva.
    rings, area = recortar_poligono([[0, 0], [10, 10], [10, 0], [0, 10]], PARCELA)
    assert area == pytest.approx(25.0)
    assert len(rings) == 1 and math.isfinite(area)


def test_superficie_menos_de_3_vertices():
    assert recortar_poligono([[1, 1], [2, 2]], PARCELA) == ([], 0.0)


def test_superficie_descarta_vertices_no_finitos():
    # Solo 2 vértices finitos → degenerada → área 0.
    rings, area = recortar_poligono(
        [[1, 1], [2, 2], [float("nan"), 3]], PARCELA
    )
    assert rings == []
    assert area == 0.0


def test_superficie_parcela_concava_parte_en_multipoligono():
    # Banda y∈[5,9] a lo ancho ∩ U = dos brazos [0,3] y [7,10] → 2 piezas, 24 m².
    rings, area = recortar_poligono([[0, 5], [10, 5], [10, 9], [0, 9]], PARCELA_U)
    assert len(rings) == 2
    assert area == pytest.approx(24.0)


# ── recortar_muro ───────────────────────────────────────────────────────────
def test_muro_dentro():
    # Segmento horizontal de 10 m con grosor 0.5 → 5.0 m² (extremos planos).
    rings, area = recortar_muro([0, 5], [10, 5], 0.5, PARCELA)
    assert area == pytest.approx(5.0)
    assert len(rings) == 1


def test_muro_medio_fuera():
    # x∈[5,15] ∩ parcela → x∈[5,10] → 5 m × 0.5 = 2.5 m².
    rings, area = recortar_muro([5, 5], [15, 5], 0.5, PARCELA)
    assert area == pytest.approx(2.5)


def test_muro_longitud_nula():
    assert recortar_muro([5, 5], [5, 5], 0.5, PARCELA) == ([], 0.0)


def test_muro_grosor_invalido():
    assert recortar_muro([0, 5], [10, 5], 0.0, PARCELA) == ([], 0.0)
    assert recortar_muro([0, 5], [10, 5], -1.0, PARCELA) == ([], 0.0)


# ── resumen_por_color ───────────────────────────────────────────────────────
def test_resumen_agrupa_superficies_y_muros_por_separado():
    figuras = [
        {"color": "#aaa", "area_m2": 5.0, "nombre": "A"},
        {"color": "#aaa", "area_m2": 7.0, "nombre": "B"},
        {"color": "#bbb", "area_m2": 3.0, "nombre": "C"},
        {"color": "#ccc", "area_m2": 0.0, "nombre": "fuera"},  # ignorada
    ]
    muros = [{"color": "#222", "area_m2": 2.0, "nombre": "M1"}]
    r = resumen_por_color(figuras, muros)

    # Superficies ordenadas desc por m²; #aaa normalizado y agregado.
    assert r["superficies_por_color"][0] == {
        "color": "#aaa", "m2_total": 12.0, "n": 2, "nombres": ["A", "B"],
    }
    assert r["superficies_por_color"][1]["color"] == "#bbb"
    assert len(r["superficies_por_color"]) == 2  # la de área 0 no entra
    assert r["total_superficies_m2"] == pytest.approx(15.0)
    assert r["total_muros_m2"] == pytest.approx(2.0)
    assert r["total_m2"] == pytest.approx(17.0)


def test_resumen_normaliza_color_sin_almohadilla():
    r = resumen_por_color([{"color": "aaa", "area_m2": 4.0, "nombre": "X"}], [])
    assert r["superficies_por_color"][0]["color"] == "#aaa"


# ── CalcularLienzo (extremo a extremo con ParcelaMetrica) ───────────────────
def test_calcular_lienzo_devuelve_areas_y_resumen():
    salida = CalcularLienzo().ejecutar(
        _pm(),
        figuras=[{"id": "f1", "tipo": "rect", "nombre": "Salón", "color": "#2E9E5B",
                  "vertices": [[2, 2], [8, 2], [8, 8], [2, 8]]}],
        muros=[{"id": "m1", "nombre": "Med", "color": "#2D6CDF",
                "p1": [0, 5], "p2": [10, 5], "grosor": 0.5}],
    )
    assert salida["figuras"][0]["area_m2"] == pytest.approx(36.0)
    assert salida["muros"][0]["area_m2"] == pytest.approx(5.0)
    assert salida["resumen"]["total_muros_m2"] == pytest.approx(5.0)
    assert "poligono" in salida["parcela"] and "bbox" in salida["parcela"]


# ── GuardarLienzo / CargarLienzo (persistencia aditiva) ─────────────────────
def _proyecto_con_parametros() -> Proyecto:
    p = Proyecto(nombre="Test")
    p.fijar_datos(ModuloPuccetti.RENDER_CALCULOS, {"parametros": {"coef": 2.5}})
    return p


def test_guardar_lienzo_no_pisa_parametros():
    repo = ProyectosEnMemoria()
    p = _proyecto_con_parametros()
    figuras = [{"id": "f1", "tipo": "rect", "nombre": "S1", "color": "#D7263D",
                "vertices": [[1, 1], [2, 1], [2, 2], [1, 2]], "rotacion": 0.0}]

    GuardarLienzo(repo_proyectos=repo).ejecutar(p, 0, figuras, muros=[])

    datos = p.datos_por_modulo[ModuloPuccetti.RENDER_CALCULOS.value]
    assert datos["parametros"] == {"coef": 2.5}            # intacto
    assert datos["lienzo"]["plantas"]["0"]["figuras"][0]["nombre"] == "S1"


def test_guardar_lienzo_aisla_plantas():
    repo = ProyectosEnMemoria()
    p = Proyecto(nombre="Test")
    fig0 = [{"id": "a", "tipo": "rect", "nombre": "PB", "color": "#fff",
             "vertices": [[0, 0], [1, 0], [1, 1], [0, 1]]}]
    fig1 = [{"id": "b", "tipo": "rect", "nombre": "P1", "color": "#fff",
             "vertices": [[2, 2], [3, 2], [3, 3], [2, 3]]}]

    GuardarLienzo(repo_proyectos=repo).ejecutar(p, 0, fig0, [])
    GuardarLienzo(repo_proyectos=repo).ejecutar(p, 1, fig1, [])

    plantas = p.datos_por_modulo[ModuloPuccetti.RENDER_CALCULOS.value]["lienzo"]["plantas"]
    assert plantas["0"]["figuras"][0]["nombre"] == "PB"   # no lo pisó la planta 1
    assert plantas["1"]["figuras"][0]["nombre"] == "P1"


def test_guardar_lienzo_descarta_no_finitos():
    repo = ProyectosEnMemoria()
    p = Proyecto(nombre="Test")
    muros = [
        {"id": "m1", "p1": [0, 5], "p2": [10, 5], "grosor": 0.3},
        {"id": "bad", "p1": [float("inf"), 5], "p2": [10, 5], "grosor": 0.3},
    ]
    GuardarLienzo(repo_proyectos=repo).ejecutar(p, 0, [], muros)
    guardados = p.datos_por_modulo[ModuloPuccetti.RENDER_CALCULOS.value]["lienzo"]["plantas"]["0"]["muros"]
    assert len(guardados) == 1 and guardados[0]["id"] == "m1"


def test_cargar_lienzo_devuelve_parcela_y_plantas():
    repo = ProyectosEnMemoria()
    p = Proyecto(nombre="Test")
    GuardarLienzo(repo_proyectos=repo).ejecutar(
        p, 0,
        [{"id": "f", "tipo": "rect", "nombre": "S", "color": "#fff",
          "vertices": [[0, 0], [1, 0], [1, 1], [0, 1]]}],
        [],
    )
    salida = CargarLienzo().ejecutar(p, _pm())
    assert salida["plantas"]["0"]["figuras"][0]["nombre"] == "S"
    assert salida["parcela"]["bbox"] == [0.0, 0.0, 10.0, 10.0]


def test_finitud_helpers_no_falla_con_listas_vacias():
    # Sanidad: el resumen vacío devuelve totales 0.
    r = resumen_por_color([], [])
    assert r["total_m2"] == 0.0
    assert math.isfinite(r["total_m2"])
