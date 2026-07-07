"""Tests de la planimetría a SVG (§2.8) — función pura, sin navegador."""
from __future__ import annotations

from app.contextos.informe.planimetria_svg import bbox_de, planta_a_svg


def test_bbox_de():
    assert bbox_de([[0, 0], [10, 0], [10, 5]]) == (0.0, 0.0, 10.0, 5.0)
    assert bbox_de(None, []) is None


def test_planta_a_svg_footprint_patio_e_inversion_y():
    planta = {
        "nombre": "PB",
        "footprint": [[0, 0], [10, 0], [10, 10], [0, 10]],
        "patios": [{"poligono": [[4, 4], [6, 4], [6, 6], [4, 6]]}],
    }
    bbox = bbox_de(planta["footprint"])
    svg = planta_a_svg(planta, bbox=bbox)

    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert svg.count("<polygon") == 2  # huella + 1 patio

    # bbox (0,0,10,10) → escala (380-20)/10 = 36, PAD=10.
    # Inversión-Y: UTM y=10 (arriba) → pantalla y=10 (arriba); UTM y=0 → pantalla y=370.
    assert "10.0,370.0" in svg   # vértice (0,0): abajo-izquierda
    assert "370.0,10.0" in svg   # vértice (10,10): arriba-derecha


def test_planta_sin_geometria_devuelve_vacio():
    assert planta_a_svg({"footprint": [[0, 0]]}, bbox=(0, 0, 1, 1)) == ""
    assert planta_a_svg({"footprint": [[0, 0], [1, 0], [1, 1]]}, bbox=None) == ""
