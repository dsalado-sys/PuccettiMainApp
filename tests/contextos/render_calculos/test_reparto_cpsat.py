"""Reparto de unidades por rejilla + OR-Tools CP-SAT (§2.5, motor candidato).

Verifica el solver puro `geometria/reparto_cpsat.py::repartir_zona_cpsat`: rasteriza la
zona edificable y asigna celdas a unidades con CP-SAT (área ± tolerancia, no-solape,
contacto fachada/patio, acceso a circulación/núcleo, conectividad por flujo). Cubre los
casos que el arquitecto exige (rectángulo, L/patio, cuello estrecho, sin solución) más
los invariantes del proyecto (cardinalidad exacta, determinismo).

Geometría sintética (`box`) alineada a la rejilla → rasterizado exacto; sin BBDD ni
Catastro. `num_workers=1` y zonas pequeñas (N ≤ ~34) para que cada test resuelva OPTIMAL
en < ~1 s y no sea flaky. Si `ortools` no está instalado, la suite salta limpio.
"""
from __future__ import annotations

import pytest

pytest.importorskip("ortools")

from shapely.geometry import box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from app.contextos.render_calculos.geometria.reparto_cpsat import (  # noqa: E402
    ResultadoReparto,
    UnidadObjetivo,
    _banda_area,
    repartir_zona_cpsat,
)

TOL = 0.10
EPS = 1e-6


def _uni(uid: str, area: float, tipo: str = "viv") -> UnidadObjetivo:
    return UnidadObjetivo(id=uid, area_objetivo=area, tipo=tipo)


def _en_banda(u, tam_celda: float) -> bool:
    """La `area_real` cae dentro de la banda entera de celdas para su objetivo."""
    cell_area = tam_celda ** 2
    A_lo, A_hi, _ = _banda_area(u.area_objetivo, cell_area, TOL)
    return A_lo * cell_area - EPS <= u.area_real <= A_hi * cell_area + EPS


# ─── Caso 1: rectángulo simple ──────────────────────────────────────────────
def test_rectangulo_simple():
    zona = box(0.0, 0.0, 8.0, 6.0)                       # 4×3 = 12 celdas a 2 m
    r = repartir_zona_cpsat(zona, [_uni("A", 12), _uni("B", 12)],
                            tam_celda=2.0, num_workers=1, timeout_s=10)
    assert isinstance(r, ResultadoReparto)
    assert r.estado == "OPTIMAL"
    assert len(r.unidades) == 2                          # cardinalidad exacta
    assert all(u.ubicada for u in r.unidades)
    for u in r.unidades:
        assert u.poligono is not None and not u.poligono.is_empty
        assert u.poligono.geom_type == "Polygon"         # conexa (una sola pieza)
        assert _en_banda(u, r.tam_celda)                 # área dentro de tolerancia
        assert zona.buffer(0.01).contains(u.poligono)    # dentro de la zona
    a, b = r.unidades[0].poligono, r.unidades[1].poligono
    assert a.intersection(b).area < EPS                  # sin solapes


# ─── Caso 2: parcela en L / patio grande (anillo) ───────────────────────────
def test_l_con_patio_grande():
    patio = box(3.0, 3.0, 7.0, 7.0)
    zona = box(0.0, 0.0, 10.0, 10.0).difference(patio)   # marco alrededor del patio
    r = repartir_zona_cpsat(zona, [_uni("A", 12), _uni("B", 12)],
                            patios=(patio,), tam_celda=2.0, num_workers=1, timeout_s=10)
    assert r.estado == "OPTIMAL"
    assert len(r.unidades) == 2
    assert all(u.ubicada for u in r.unidades)
    contacto = unary_union([zona.boundary, patio.boundary])
    for u in r.unidades:
        assert u.poligono.intersection(patio).area < EPS   # no pisa el patio
        assert _en_banda(u, r.tam_celda)
        assert u.poligono.distance(contacto) < r.tam_celda  # ventila a fachada o patio


# ─── Caso 3: cuello estrecho (regresión de conectividad) ────────────────────
def test_cuello_estrecho_conectividad():
    # Dos lóbulos 6×10 unidos por un puente de 2 m → UNA sola zona.
    zona = unary_union([box(0, 0, 6, 10), box(6, 4, 14, 6), box(14, 0, 20, 10)])
    # Objetivo grande (~100 m²) que no cabe en un lóbulo+cuello → obliga a enhebrar.
    r = repartir_zona_cpsat(zona, [_uni("A", 100)],
                            tam_celda=2.0, num_workers=1, timeout_s=15)
    assert r.estado == "OPTIMAL"
    assert len(r.unidades) == 1
    u = r.unidades[0]
    assert u.ubicada and u.poligono is not None
    assert u.poligono.geom_type == "Polygon"             # conexa pese al cuello
    minx, _miny, maxx, _maxy = u.poligono.bounds
    assert minx < 6.0 and maxx > 14.0                    # usa AMBOS lóbulos (enhebra)


# ─── Caso 4: sin solución factible → no_ubicada, no crashea ─────────────────
def test_sin_solucion_no_ubicada():
    zona = box(0.0, 0.0, 4.0, 4.0)                       # 2×2 = 4 celdas
    r = repartir_zona_cpsat(zona, [_uni("X", 100)],      # 100 m² no cabe
                            tam_celda=2.0, num_workers=1, timeout_s=10)
    assert isinstance(r, ResultadoReparto)               # retorna, no revienta
    assert len(r.unidades) == 1                          # cardinalidad preservada
    u = r.unidades[0]
    assert u.ubicada is False
    assert u.poligono is None
    assert isinstance(r.estado, str) and r.estado        # nombre de status válido


# ─── Invariante: cardinalidad y orden ───────────────────────────────────────
def test_cardinalidad_y_orden():
    zona = box(0.0, 0.0, 4.0, 4.0)                       # solo 4 celdas
    entrada = [_uni("U1", 60), _uni("U2", 60), _uni("U3", 60)]
    r = repartir_zona_cpsat(zona, entrada, tam_celda=2.0, num_workers=1, timeout_s=10)
    assert len(r.unidades) == len(entrada)               # ni crea ni borra
    assert [u.id for u in r.unidades] == [u.id for u in entrada]  # mismo orden/ids
    assert all(not u.ubicada for u in r.unidades)        # ninguna cabe → todas no_ubicada


# ─── Invariante: determinismo (regla «sin aleatoriedad») ────────────────────
def test_determinismo():
    zona = box(0.0, 0.0, 10.0, 6.0)
    uds = [_uni("A", 16), _uni("B", 16)]
    kw = dict(tam_celda=2.0, seed=0, num_workers=1, timeout_s=10)
    r1 = repartir_zona_cpsat(zona, [_uni(u.id, u.area_objetivo) for u in uds], **kw)
    r2 = repartir_zona_cpsat(zona, [_uni(u.id, u.area_objetivo) for u in uds], **kw)
    assert r1.estado == r2.estado

    def _huella(res):
        return [
            (u.ubicada, round(u.area_real, 3),
             None if u.poligono is None else u.poligono.wkb)
            for u in res.unidades
        ]

    assert _huella(r1) == _huella(r2)                    # byte-idéntico


# ─── Núcleo reservado + acceso ──────────────────────────────────────────────
def test_reserva_nucleo_y_acceso():
    zona = box(0.0, 0.0, 10.0, 6.0)
    nucleo = box(4.0, 2.0, 6.0, 4.0)                     # reserva 1 celda central
    r = repartir_zona_cpsat(zona, [_uni("A", 12), _uni("B", 12)],
                            nucleo=nucleo, exigir_acceso=True,
                            tam_celda=2.0, num_workers=1, timeout_s=10)
    assert r.estado == "OPTIMAL"
    colocadas = [u for u in r.unidades if u.ubicada]
    assert colocadas                                     # se coloca al menos una
    for u in colocadas:
        assert u.poligono.intersection(nucleo).area < EPS   # no invade el núcleo
        # Acceso: adyacente a la circulación o al núcleo (comparten arista → distancia ~0).
        d = min(u.poligono.distance(r.circulacion), u.poligono.distance(nucleo))
        assert d < r.tam_celda


# ─── Contacto / ventilación ─────────────────────────────────────────────────
def test_contacto_ventilacion():
    zona = box(0.0, 0.0, 8.0, 6.0)
    r = repartir_zona_cpsat(zona, [_uni("A", 12), _uni("B", 12)],
                            tam_celda=2.0, num_workers=1, timeout_s=10)
    assert r.estado == "OPTIMAL"
    for u in r.unidades:
        if u.ubicada:
            # Toca la fachada (borde de la zona) para ventilar.
            assert u.poligono.distance(zona.boundary) < r.tam_celda


# ─── Límite: zona con menos celdas que unidades ─────────────────────────────
def test_zona_menos_celdas_que_unidades():
    """Zona con menos celdas que unidades: cardinalidad exacta, casi ninguna cabe, no crashea."""
    zona = box(0.0, 0.0, 2.0, 2.0)                       # 1 celda a 2 m
    entrada = [_uni("A", 4), _uni("B", 4), _uni("C", 4)]
    r = repartir_zona_cpsat(zona, entrada, tam_celda=2.0, num_workers=1, timeout_s=10)
    assert isinstance(r, ResultadoReparto)               # retorna, no revienta
    assert len(r.unidades) == 3                          # cardinalidad exacta
    assert [u.id for u in r.unidades] == ["A", "B", "C"]  # mismo orden/ids
    assert sum(u.ubicada for u in r.unidades) <= 1       # 1 celda → a lo sumo 1 ubicada


# ─── Límite: unidad con área objetivo mayor que toda la zona ────────────────
def test_unidad_mayor_que_toda_la_zona():
    """Área objetivo mayor que la zona entera: no ubicada, sin polígono, no crashea."""
    zona = box(0.0, 0.0, 4.0, 4.0)                       # 16 m²
    r = repartir_zona_cpsat(zona, [_uni("G", 500)], tam_celda=2.0, num_workers=1, timeout_s=10)
    assert isinstance(r, ResultadoReparto)
    assert len(r.unidades) == 1
    u = r.unidades[0]
    assert u.ubicada is False
    assert u.poligono is None
    assert isinstance(r.estado, str) and r.estado        # nombre de status válido


# ─── `tam_celda` es parámetro configurable y se refleja en el resultado ─────
def test_tam_celda_configurable():
    zona = box(0.0, 0.0, 10.0, 10.0)
    r = repartir_zona_cpsat(zona, [_uni("A", 25), _uni("B", 25)],
                            tam_celda=2.5, num_workers=1, timeout_s=10)
    # 4×4 = 16 celdas a 2.5 m: por debajo de `max_celdas` → no se engrosa la celda.
    assert r.tam_celda == pytest.approx(2.5)
    assert r.n_celdas == 16
