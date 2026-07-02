"""Detección de zonas edificables (§2.4).

La huella menos los patios puede quedar partida en varias masas edificables,
aunque sigan unidas por un cuello estrecho. `detectar_zonas_edificables` rompe
los cuellos más finos que el umbral (apertura morfológica) y devuelve la
partición de la región en zonas que la teselan sin solapes.

Se prueba la función pura con geometrías sintéticas (`box`), sin tocar el motor
de envolvente ni la API de Catastro.
"""
from __future__ import annotations

import pytest
from shapely.geometry import box
from shapely.ops import unary_union

from app.contextos.render_calculos.geometria.zonas import (
    detectar_zonas_edificables,
    repartir_por_area,
)

# Dos bloques de 20×20 con un hueco de 10 m entre ellos (x∈[20,30]).
IZQ = box(0.0, 0.0, 20.0, 20.0)
DER = box(30.0, 0.0, 50.0, 20.0)


def _region(*geoms):
    return unary_union(list(geoms))


# ─── Cuello estrecho vs. ancho ──────────────────────────────────────────────
def test_cuello_estrecho_da_dos_zonas():
    # Puente de 2 m de alto (< 4 m) → el cuello se rompe → 2 zonas.
    puente = box(20.0, 9.0, 30.0, 11.0)
    zonas = detectar_zonas_edificables(_region(IZQ, DER, puente), ancho_cuello_min=4.0)
    assert len(zonas) == 2


def test_cuello_ancho_da_una_zona():
    # Puente de 14 m de alto (> 4 m) → el paso admite planta continua → 1 zona.
    puente = box(20.0, 3.0, 30.0, 17.0)
    zonas = detectar_zonas_edificables(_region(IZQ, DER, puente), ancho_cuello_min=4.0)
    assert len(zonas) == 1


def test_umbral_configurable():
    # El MISMO puente estrecho (2 m) es "una zona" con umbral bajo y "dos" con umbral alto.
    puente = box(20.0, 9.0, 30.0, 11.0)
    region = _region(IZQ, DER, puente)
    assert len(detectar_zonas_edificables(region, ancho_cuello_min=1.0)) == 1
    assert len(detectar_zonas_edificables(region, ancho_cuello_min=4.0)) == 2


# ─── Casos base ─────────────────────────────────────────────────────────────
def test_bloque_unico_una_zona():
    zonas = detectar_zonas_edificables(box(0.0, 0.0, 20.0, 20.0))
    assert len(zonas) == 1
    assert zonas[0].area == pytest.approx(400.0, rel=1e-6)


def test_patio_central_con_cuello_estrecho():
    # Réplica del caso real: patio grande que toca el borde inferior y deja una
    # franja superior estrecha (3 m) uniendo ambos lados → 2 zonas.
    footprint = box(0.0, 0.0, 40.0, 20.0)
    patio = box(10.0, 0.0, 30.0, 17.0)
    region = footprint.difference(patio)
    zonas = detectar_zonas_edificables(region, ancho_cuello_min=4.0)
    assert len(zonas) == 2


def test_patio_parte_la_huella_multipolygon():
    # Patio que atraviesa toda la huella: `difference` ya devuelve MultiPolygon.
    footprint = box(0.0, 0.0, 40.0, 20.0)
    patio = box(18.0, 0.0, 22.0, 20.0)
    region = footprint.difference(patio)
    assert region.geom_type == "MultiPolygon"
    zonas = detectar_zonas_edificables(region, ancho_cuello_min=4.0)
    assert len(zonas) == 2


def test_region_vacia():
    from shapely.geometry import Polygon
    assert detectar_zonas_edificables(Polygon()) == []


# ─── Invariantes de la partición ────────────────────────────────────────────
def test_zonas_teselan_sin_solapes():
    footprint = box(0.0, 0.0, 40.0, 20.0)
    patio = box(10.0, 0.0, 30.0, 17.0)
    region = footprint.difference(patio)
    zonas = detectar_zonas_edificables(region, ancho_cuello_min=4.0)
    assert len(zonas) == 2
    # La suma de zonas cubre la región (sin perder área).
    assert sum(z.area for z in zonas) == pytest.approx(region.area, rel=0.02)
    # Sin solapes entre zonas.
    assert zonas[0].intersection(zonas[1]).area < 1.0


def test_zonas_ordenadas_por_area_desc():
    # Bloque grande + bloque pequeño separados del todo.
    grande = box(0.0, 0.0, 30.0, 20.0)
    pequeno = box(40.0, 0.0, 50.0, 10.0)
    zonas = detectar_zonas_edificables(_region(grande, pequeno))
    assert len(zonas) == 2
    assert zonas[0].area >= zonas[1].area


def test_esquirlas_descartadas():
    grande = box(0.0, 0.0, 20.0, 20.0)      # 400 m²
    esquirla = box(40.0, 0.0, 41.0, 1.0)    # 1 m² < area_min_zona
    zonas = detectar_zonas_edificables(_region(grande, esquirla), area_min_zona=10.0)
    assert len(zonas) == 1
    assert zonas[0].area == pytest.approx(400.0, rel=1e-6)


# ─── Reparto de unidades por área (método del resto mayor) ──────────────────
def test_reparto_proporcional_con_resto():
    # 10 uds, zona 3× la otra → más en la grande; el resto va a la de mayor área.
    assert repartir_por_area(10, [300.0, 100.0]) == [8, 2]


def test_reparto_zonas_iguales():
    assert repartir_por_area(4, [100.0, 100.0]) == [2, 2]        # par → mitades
    assert repartir_por_area(5, [100.0, 100.0]) == [3, 2]        # impar → la 1ª se lleva la extra


def test_reparto_suma_exacta():
    casos = [(7, [50.0, 30.0, 20.0]), (13, [100.0, 100.0, 100.0]), (1, [10.0, 9.0])]
    for total, areas in casos:
        reparto = repartir_por_area(total, areas)
        assert sum(reparto) == total
        assert len(reparto) == len(areas)
        assert all(u >= 0 for u in reparto)


def test_reparto_bordes():
    assert repartir_por_area(0, [100.0, 50.0]) == [0, 0]         # sin unidades
    assert repartir_por_area(5, [100.0]) == [5]                  # una sola zona
    assert repartir_por_area(5, []) == []                        # sin zonas
    assert repartir_por_area(3, [0.0, 0.0]) == [0, 0]            # área nula


def test_reparto_zona_diminuta_a_cero():
    assert repartir_por_area(3, [1000.0, 5.0]) == [3, 0]


# ─── Integración: reparto adjunto a cada zona serializada ───────────────────
def test_zonas_de_planta_reparte_unidades():
    from types import SimpleNamespace

    from app.contextos.render_calculos.casos_uso import _zonas_de_planta

    footprint = box(0.0, 0.0, 40.0, 20.0)
    patio = SimpleNamespace(geometry=box(10.0, 0.0, 30.0, 17.0))   # deja 2 zonas
    planta = SimpleNamespace(footprint=footprint, patios=[patio])

    zonas = _zonas_de_planta(planta, ancho_cuello_min=4.0, total_unidades=5)
    assert len(zonas) == 2
    assert all("unidades" in z for z in zonas)
    assert sum(z["unidades"] for z in zonas) == 5
    # La zona mayor (área) recibe al menos tantas como la menor.
    zonas_por_area = sorted(zonas, key=lambda z: z["area_m2"], reverse=True)
    assert zonas_por_area[0]["unidades"] >= zonas_por_area[1]["unidades"]
