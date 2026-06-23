"""Tests del parseo de patios desde el WFS BU del Catastro (rehabilitación).

Un patio es un anillo interior (``gml:interior``) de la huella del edificio. El
fixture es la respuesta REAL del WFS BU ``GetBuildingByParcel`` para la RC
``5036501TG3453E`` (Sevilla), pedida en EPSG:25830 → las áreas salen en m². Todo
es función pura sobre el XML guardado: NO se hace ninguna llamada al Catastro
(ver feedback_no_quemar_api_catastro).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.plataforma.catastro.catastro_meh import (
    _area_anillo_m2,
    _parsear_patios_gml,
)

FIXTURE = Path(__file__).parent / "fixtures" / "bu_5036501TG3453E.gml"
# Parcela con DOS patios: uno cerrado (hueco, ~4.6 m²) y uno abierto (entrante del
# contorno, ~13 m²). GML real del WFS BU, guardado offline.
FIXTURE_2 = Path(__file__).parent / "fixtures" / "bu_5028013TG3452G.gml"


def _gml() -> str:
    return FIXTURE.read_text(encoding="utf-8")


# ── _area_anillo_m2: shoelace en CRS métrico ────────────────────────────────
def test_area_anillo_cuadrado_10x10():
    # Cuadrado 10×10 m (anillo cerrado: último vértice = primero) → 100 m².
    cuadrado = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    assert _area_anillo_m2(cuadrado) == pytest.approx(100.0)


def test_area_anillo_independiente_del_sentido():
    horario = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0), (0.0, 0.0)]
    assert _area_anillo_m2(horario) == pytest.approx(100.0)


def test_area_anillo_degenerado_es_cero():
    assert _area_anillo_m2([(0.0, 0.0), (1.0, 1.0)]) == 0.0
    assert _area_anillo_m2([]) == 0.0


# ── _parsear_patios_gml sobre el fixture real ───────────────────────────────
def test_fixture_existe():
    assert FIXTURE.exists(), f"Falta el fixture offline {FIXTURE}"


def test_parsea_un_patio_de_la_huella_real():
    res = _parsear_patios_gml(_gml())
    assert res is not None
    n_patios, areas = res
    # El edificio 5036501TG3453E tiene exactamente un anillo interior (un patio).
    assert n_patios == 1
    assert len(areas) == 1
    # Su superficie es ~280 m² (shoelace sobre las coords EPSG:25830 del fixture).
    assert areas[0] == pytest.approx(280.2, abs=1.0)


def test_parsea_patio_cerrado_mas_abierto():
    # 5028013TG3452G: el WFS solo trae 1 anillo interior (hueco ~4.6 m²), pero la
    # huella tiene además un patio ABIERTO (entrante ~13 m²) que NO es gml:interior.
    # El parser debe devolver los 2 (cerrado + abierto detectado por cierre morf.).
    res = _parsear_patios_gml(FIXTURE_2.read_text(encoding="utf-8"))
    assert res is not None
    n_patios, areas = res
    assert n_patios == 2, f"esperados 2 patios, salieron {n_patios}: {areas}"
    assert any(a == pytest.approx(4.6, abs=1.0) for a in areas), areas   # cerrado
    assert any(11.0 <= a <= 16.0 for a in areas), areas                  # abierto


# ── Casos límite del parser ──────────────────────────────────────────────────
def test_huella_sin_patios_devuelve_cero():
    # Surface con solo exterior, sin gml:interior → (0, ()).
    xml = (
        '<gml:FeatureCollection xmlns:gml="http://www.opengis.net/gml/3.2">'
        "<gml:Surface><gml:patches><gml:PolygonPatch>"
        "<gml:exterior><gml:LinearRing>"
        "<gml:posList>0 0 10 0 10 10 0 10 0 0</gml:posList>"
        "</gml:LinearRing></gml:exterior>"
        "</gml:PolygonPatch></gml:patches></gml:Surface>"
        "</gml:FeatureCollection>"
    )
    assert _parsear_patios_gml(xml) == (0, ())


def test_exception_report_devuelve_none():
    xml = (
        '<?xml version="1.0"?>'
        '<ExceptionReport xmlns="http://www.opengis.net/ows/1.1">'
        "<Exception><ExceptionText>error</ExceptionText></Exception>"
        "</ExceptionReport>"
    )
    assert _parsear_patios_gml(xml) is None


def test_xml_invalido_devuelve_none():
    assert _parsear_patios_gml("esto no es xml") is None
