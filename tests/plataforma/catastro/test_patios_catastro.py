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

from shapely.geometry import box
from shapely.ops import unary_union

from app.plataforma.catastro.catastro_meh import (
    _anillo_25830_a_wgs84,
    _area_anillo_m2,
    _parsear_patios_gml,
    _patios_abiertos,
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
    # El edificio 5036501TG3453E tiene exactamente un anillo interior (un patio).
    assert len(res) == 1
    patio = res[0]
    assert patio.tipo == "cerrado"
    # Su superficie es ~280 m² (shoelace sobre las coords EPSG:25830 del fixture).
    assert patio.area_m2 == pytest.approx(280.2, abs=1.0)
    # AHORA se conserva la GEOMETRÍA: anillo cerrado (≥ 4 vértices) en EPSG:25830,
    # cuya área por shoelace coincide con la reportada.
    assert len(patio.anillo_25830) >= 4
    assert _area_anillo_m2(patio.anillo_25830) == pytest.approx(patio.area_m2, abs=0.5)


def test_anillo_del_patio_reproyecta_a_wgs84_en_sevilla():
    # Reproyectado a WGS84, el anillo del patio cae en Sevilla (lon ≈ -6, lat ≈ 37.4):
    # valida la dirección de la reproyección (always_xy) y que las coords son sanas.
    res = _parsear_patios_gml(_gml())
    assert res and res[0].anillo_25830
    wgs = _anillo_25830_a_wgs84(res[0].anillo_25830)
    assert len(wgs) == len(res[0].anillo_25830)
    lons = [p[0] for p in wgs]
    lats = [p[1] for p in wgs]
    assert all(-6.2 < lon < -5.8 for lon in lons), lons
    assert all(37.2 < lat < 37.6 for lat in lats), lats


def test_parsea_patio_cerrado_mas_abierto():
    # 5028013TG3452G: el WFS solo trae 1 anillo interior (hueco ~4.6 m²), pero la
    # huella tiene además un patio ABIERTO (entrante ~13 m²) que NO es gml:interior.
    # El parser debe devolver los 2 (cerrado + abierto detectado por cierre morf.),
    # cada uno con su tipo y su geometría.
    res = _parsear_patios_gml(FIXTURE_2.read_text(encoding="utf-8"))
    assert res is not None
    assert len(res) == 2, f"esperados 2 patios, salieron {len(res)}: {res}"
    cerrados = [p for p in res if p.tipo == "cerrado"]
    abiertos = [p for p in res if p.tipo == "abierto"]
    assert len(cerrados) == 1 and len(abiertos) == 1, res
    assert cerrados[0].area_m2 == pytest.approx(4.6, abs=1.0)
    assert 11.0 <= abiertos[0].area_m2 <= 16.0, abiertos
    # Ambos conservan anillo poligonal (≥ 4 vértices).
    assert all(len(p.anillo_25830) >= 4 for p in res), res


# ── Casos límite del parser ──────────────────────────────────────────────────
def test_huella_sin_patios_devuelve_lista_vacia():
    # Surface con solo exterior, sin gml:interior → [].
    xml = (
        '<gml:FeatureCollection xmlns:gml="http://www.opengis.net/gml/3.2">'
        "<gml:Surface><gml:patches><gml:PolygonPatch>"
        "<gml:exterior><gml:LinearRing>"
        "<gml:posList>0 0 10 0 10 10 0 10 0 0</gml:posList>"
        "</gml:LinearRing></gml:exterior>"
        "</gml:PolygonPatch></gml:patches></gml:Surface>"
        "</gml:FeatureCollection>"
    )
    assert _parsear_patios_gml(xml) == []


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


# ── Patio abierto: con parcela se capta ENTERO (aunque cierre contra el lindero) ──
def test_patio_abierto_con_parcela_capta_entero():
    """Patio "embudo": estrecho arriba (cerrado por el edificio) y ancho abajo
    (cerrado por el LINDERO de la parcela, no por el edificio). El cierre del
    edificio solo capta la parte de arriba; con la parcela se capta entero."""
    parcela = box(0, 0, 20, 20)
    patio_real = unary_union([box(8, 8, 12, 14),   # estrecho arriba (cerrado por edificio)
                              box(4, 0, 16, 8)])    # ancho abajo (toca el lindero y=0)
    edificio = parcela.difference(patio_real)       # 400 − 120 = 280 m²

    con = _patios_abiertos(edificio, parcela)
    sin = _patios_abiertos(edificio, None)
    area_con = sum(a for a, _, _ in con)
    area_sin = sum(a for a, _, _ in sin)

    # Con la parcela se capta casi todo el patio real (~120 m²); el cierre del
    # edificio solo, mucho menos (la mitad inferior queda fuera).
    assert area_con > 100.0, (area_con, area_sin)
    assert area_con > 1.7 * area_sin, (area_con, area_sin)
    # Y el patio llega hasta el borde de la parcela (y≈0), no se queda a media altura.
    y_min = min(y for _, anillo, _ in con for _, y in anillo)
    assert y_min < 1.0, y_min


def test_patio_en_anillo_conserva_hueco():
    """Edificio en MEDIO de la parcela: el patio la rodea (anillo) y conserva el hueco
    del edificio. El criterio de cierre no aplica (un anillo es patio por definición)."""
    parcela = box(0, 0, 30, 30)
    edificio = box(11, 11, 19, 19)   # 8×8 en el centro, sin tocar el lindero
    res = _patios_abiertos(edificio, parcela)
    assert len(res) == 1
    area, ext, huecos = res[0]
    # Área NETA = parcela − edificio = 900 − 64 = 836 m².
    assert area == pytest.approx(836, abs=25), area
    assert len(huecos) == 1, huecos          # un hueco: el edificio central
    assert len(huecos[0]) >= 4               # anillo cerrado
    assert len(ext) >= 4


def test_patio_abierto_sin_edificio_es_vacio():
    assert _patios_abiertos(None, box(0, 0, 10, 10)) == []
