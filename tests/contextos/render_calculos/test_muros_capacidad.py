"""Muros: separación perímetro (planta) vs tabiquería interior (unidad).

Los «muros por planta» son SOLO perímetro/edificio (huella × pct_muros): fachadas,
medianeras y separaciones entre unidades. La tabiquería interior de las unidades
(pct_muros_interior) es un cálculo de UNIDAD: se descuenta del útil destinado a
viviendas, no de la huella, y se reporta aparte (`muros_interior_por_planta`).

Consecuencia: subir pct_muros_interior NO cambia los muros de planta; aparece como
tabiquería y reduce la útil. Con pct_muros_interior = 0 no se reserva ni un m².
"""
from __future__ import annotations

from types import SimpleNamespace

from app.contextos.render_calculos.geometria.capacidad import calcular_capacidad
from app.contextos.render_calculos.parametros import ParametrosRender


def _env(huella_m2: float, n_plantas: int = 1) -> SimpleNamespace:
    foot = SimpleNamespace(area=huella_m2)
    plantas = [
        SimpleNamespace(n=i, footprint=foot, tipo="regular", computa_edif=True)
        for i in range(n_plantas)
    ]
    return SimpleNamespace(
        plantas=plantas,
        parcela=SimpleNamespace(area=huella_m2),
        superficie_referencia_m2=huella_m2,
    )


def test_muros_planta_son_solo_perimetro():
    """huella 100, pct_muros 20% → muros de planta = 20 m², sin tabiquería."""
    p = ParametrosRender()  # pct_muros_interior = 0 por defecto
    cap = calcular_capacidad(_env(100.0), p.a_parametros_motor())
    assert abs(cap.muros_por_planta[0] - 20.0) < 1e-6
    assert cap.muros_interior_por_planta[0] == 0.0


def test_tabiqueria_no_cambia_los_muros_de_planta_y_baja_la_util():
    """Subir pct_muros_interior deja los muros de planta IGUAL (solo perímetro),
    crea tabiquería y reduce la útil disponible."""
    p0 = ParametrosRender()
    cap0 = calcular_capacidad(_env(100.0), p0.a_parametros_motor())
    util0 = cap0.util_por_planta[0]

    p1 = ParametrosRender()
    p1.diseno.pct_muros_interior = 10.0
    cap1 = calcular_capacidad(_env(100.0), p1.a_parametros_motor())

    # Muros de planta IDÉNTICOS: la tabiquería no se suma aquí.
    assert abs(cap1.muros_por_planta[0] - cap0.muros_por_planta[0]) < 1e-6
    # Ahora hay tabiquería = 10% del útil disponible (55 → 5.5).
    assert abs(cap1.muros_interior_por_planta[0] - 5.5) < 1e-6
    # Y la útil baja en esa misma cantidad (55 → 49.5).
    assert abs(cap1.util_por_planta[0] - (util0 - 5.5)) < 1e-6
    assert cap1.util_por_planta[0] < util0


def test_conservacion_construida_incluye_tabiqueria():
    """construida = útil + muros(perímetro) + muros_interior + circ + núcleo
    (el patio queda fuera de la construida reportada)."""
    p = ParametrosRender()
    p.diseno.pct_muros_interior = 10.0
    cap = calcular_capacidad(_env(100.0), p.a_parametros_motor())
    suma = (
        cap.util_por_planta[0]
        + cap.muros_por_planta[0]
        + cap.muros_interior_por_planta[0]
        + cap.circulacion_por_planta[0]
        + cap.nucleo_por_planta[0]
    )
    assert abs(cap.construida_por_planta[0] - suma) < 1e-6
