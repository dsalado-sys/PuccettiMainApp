"""Integración del motor CP-SAT en el pipeline de `CalcularLayout` (§2.4).

Verifica que el flag `algoritmo="cpsat"` cablea `disponer_edificio_cpsat` +
`edificio_cpsat_a_dict` dentro de `CalcularLayout.ejecutar` sin romper el contrato
que consume `rc_canvas.js` (`edificio.plantas[].unidades[]`) ni la vía numérica
por defecto (`edificio: null`). Cardinalidad exacta y unidades no ubicadas en rojo.

Toda la suite se salta limpiamente si falta `ortools` (motor CP-SAT).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("ortools")

from shapely.geometry import box  # noqa: E402

from app.contextos.render_calculos.casos_uso import (  # noqa: E402
    CalcularLayout,
    ParcelaMetrica,
    _alertas_disposicion,
)
from app.contextos.render_calculos.geometria.disposicion_cpsat import (  # noqa: E402
    disponer_edificio_cpsat,
)
from app.contextos.render_calculos.geometria.zonas import (  # noqa: E402
    detectar_zonas_edificables,
)
from app.contextos.render_calculos.parametros import ParametrosRender  # noqa: E402

CLAVES_UNIDAD = {
    "id", "poligono_construido", "poligono_util", "area_util_m2",
    "ubicada", "cumple_minimos", "es_adaptada",
}

# Referencias normativas prohibidas en avisos de UI (memoria feedback_avisos_sin_referencias_pdf).
TERMINOS_PROHIBIDOS = ("Anexo", "§", "DB SUA", "DB-SUA", "Decreto", "PGOU")


def _parcela() -> ParcelaMetrica:
    return ParcelaMetrica(
        poligono_utm=box(0.0, 0.0, 20.0, 20.0),   # 400 m²
        lados=[],
        municipio=None,
        provincia=None,
        centroide_lonlat=None,
        referencia_catastral=None,
        superficie_catastral_m2=400.0,
    )


def _params_pequenos() -> ParametrosRender:
    """Vivienda, una sola planta (PB) y sin patios → un solo `solve` CP-SAT rápido."""
    p = ParametrosRender()
    p.urbanisticos.n_plantas_max = 1
    p.urbanisticos.ocupacion_maxima_pct = 90.0
    p.urbanisticos.usar_coeficiente_edificabilidad = False
    p.urbanisticos.coeficiente_edificabilidad = 8.0
    p.urbanisticos.retranqueo_fachada_m = 0.0
    p.urbanisticos.retranqueo_linderos_m = 0.0
    p.urbanisticos.patios = []
    return p


def _unidades_serializadas(res: dict) -> list:
    return [u for pl in res["edificio"]["plantas"] for u in pl["unidades"]]


# ─── End-to-end a través de CalcularLayout.ejecutar ──────────────────────────
def test_flag_cpsat_puebla_edificio():
    res = CalcularLayout().ejecutar(_parcela(), _params_pequenos(), algoritmo="cpsat")
    assert res["edificio"] is not None
    assert res["edificio"]["plantas"], "debería haber al menos una planta dispuesta"


def test_cardinalidad_exacta():
    """Nº de unidades serializadas (ubicadas + no) == suma de viv_por_planta del cálculo."""
    res = CalcularLayout().ejecutar(_parcela(), _params_pequenos(), algoritmo="cpsat")
    total_cap = sum(res["capacidad"]["viv_por_planta"])
    assert len(_unidades_serializadas(res)) == total_cap


def test_contrato_de_serializacion():
    res = CalcularLayout().ejecutar(_parcela(), _params_pequenos(), algoritmo="cpsat")
    for pl in res["edificio"]["plantas"]:
        assert {"footprint", "patios", "pasillos", "unidades", "zonas"} <= set(pl)
        assert isinstance(pl["footprint"], list) and len(pl["footprint"]) >= 3
    for u in _unidades_serializadas(res):
        assert CLAVES_UNIDAD <= set(u)
        for clave in ("poligono_construido", "poligono_util"):
            poly = u[clave]
            assert isinstance(poly, list) and len(poly) >= 3
            assert all(len(pt) == 2 for pt in poly)


def test_contrato_numerico_intacto():
    """La vía CP-SAT solo rellena `edificio`; el resto del contrato no cambia."""
    res = CalcularLayout().ejecutar(_parcela(), _params_pequenos(), algoritmo="cpsat")
    for clave in ("capacidad", "tabla_planta", "tabla_unidad", "envolvente", "parcela", "lados"):
        assert clave in res and res[clave] is not None


def test_default_sin_algoritmo_no_dispone():
    res = CalcularLayout().ejecutar(_parcela(), _params_pequenos())
    assert res["edificio"] is None


def test_algoritmo_numerico_explicito_no_dispone():
    res = CalcularLayout().ejecutar(_parcela(), _params_pequenos(), algoritmo="numerico")
    assert res["edificio"] is None


# ─── Orquestador aislado: unidades que no caben → rojo (placeholder) ─────────
def _envolvente_fake(footprint):
    planta = SimpleNamespace(n=0, tipo="regular", footprint=footprint, patios=[])
    return SimpleNamespace(plantas=[planta])


def test_unidad_que_no_cabe_es_no_ubicada_con_placeholder():
    """Zona pequeña (16 m²) + unidad sobredimensionada (100 m²) → no ubicada, pero con
    polígono placeholder no vacío para dibujarla en rojo donde se intentó colocarla."""
    envolvente = _envolvente_fake(box(0.0, 0.0, 4.0, 4.0))
    cap = SimpleNamespace(
        unidades_por_planta=[[(3, 100.0)]],
        tipologias_unidad_por_planta=[["viv"]],
        n_unidades_adaptadas=0,
    )
    plantas = disponer_edificio_cpsat(envolvente, cap)
    assert len(plantas) == 1
    unidades = plantas[0].unidades
    assert len(unidades) == 1                     # cardinalidad exacta
    u = unidades[0]
    assert u.ubicada is False
    assert u.poligono is not None and not u.poligono.is_empty


def test_orquestador_preserva_cardinalidad_por_planta():
    """Mezcla ubicadas + no ubicadas: la lista mantiene todas las unidades objetivo."""
    envolvente = _envolvente_fake(box(0.0, 0.0, 10.0, 10.0))   # 100 m²
    cap = SimpleNamespace(
        unidades_por_planta=[[(1, 30.0), (2, 45.0), (3, 200.0)]],   # la de 200 no cabe
        tipologias_unidad_por_planta=[["viv", "viv", "viv"]],
        n_unidades_adaptadas=0,
    )
    plantas = disponer_edificio_cpsat(envolvente, cap)
    assert len(plantas[0].unidades) == 3
    assert all(u.poligono is not None and not u.poligono.is_empty for u in plantas[0].unidades)


# ─── Límite: patio que parte la zona en 2 componentes desconectadas ─────────
def test_patio_parte_la_zona_en_dos_componentes():
    """Un patio que corta la huella de lado a lado la parte en 2 zonas conexas.

    La separación la hace `zonas.py` upstream (resta de patios + componentes conexos),
    así que a `reparto_cpsat` siempre le llega un `Polygon` conexo: no necesita defensa.
    """
    footprint = box(0.0, 0.0, 20.0, 8.0)
    patio = box(9.0, 0.0, 11.0, 8.0)                     # franja vertical de lado a lado
    region = footprint.difference(patio)
    zonas = detectar_zonas_edificables(region)
    assert len(zonas) == 2                               # dos masas separadas
    assert all(z.geom_type == "Polygon" for z in zonas)  # cada zona es conexa

    # Y el orquestador reparte sobre ambas sin lanzar.
    patio_ns = SimpleNamespace(geometry=patio)
    planta = SimpleNamespace(n=0, tipo="regular", footprint=footprint, patios=[patio_ns])
    envolvente = SimpleNamespace(plantas=[planta])
    cap = SimpleNamespace(
        unidades_por_planta=[[(2, 40.0), (2, 40.0)]],
        tipologias_unidad_por_planta=[["viv", "viv"]],
        n_unidades_adaptadas=0,
    )
    plantas = disponer_edificio_cpsat(envolvente, cap)
    assert len(plantas) == 1
    assert len(plantas[0].zonas) == 2
    assert len(plantas[0].unidades) == 2                 # cardinalidad exacta


# ─── Degradación visible: aviso de disposición parcial (sin referencias) ────
def test_aviso_disposicion_parcial_sin_referencias():
    """Con unidades que no caben, `_alertas_disposicion` emite UN aviso de geometría,
    sin referencias normativas prohibidas."""
    envolvente = _envolvente_fake(box(0.0, 0.0, 10.0, 10.0))   # 100 m²
    cap = SimpleNamespace(
        unidades_por_planta=[[(1, 30.0), (3, 200.0)]],   # la de 200 no cabe
        tipologias_unidad_por_planta=[["viv", "viv"]],
        n_unidades_adaptadas=0,
    )
    plantas = disponer_edificio_cpsat(envolvente, cap)
    avisos = _alertas_disposicion(plantas)
    assert len(avisos) == 1
    a = avisos[0]
    assert a.nivel == "aviso" and a.regla == "Geometría"
    assert not any(t in a.mensaje for t in TERMINOS_PROHIBIDOS)


def test_alertas_disposicion_vacio_si_todo_ubicado():
    """Todas las unidades caben → sin aviso de disposición (evita ruido)."""
    envolvente = _envolvente_fake(box(0.0, 0.0, 10.0, 10.0))
    cap = SimpleNamespace(
        unidades_por_planta=[[(1, 20.0), (1, 20.0)]],
        tipologias_unidad_por_planta=[["viv", "viv"]],
        n_unidades_adaptadas=0,
    )
    plantas = disponer_edificio_cpsat(envolvente, cap)
    assert all(u.ubicada for u in plantas[0].unidades)   # precondición: todas ubicadas
    assert _alertas_disposicion(plantas) == []


# ─── Camino feliz vía CalcularLayout: sin aviso de fallo, sin referencias ───
def test_camino_feliz_sin_aviso_de_disposicion():
    res = CalcularLayout().ejecutar(_parcela(), _params_pequenos(), algoritmo="cpsat")
    mensajes = [a["mensaje"] for a in res["alertas"]]
    assert not any(m.startswith("No se pudo dibujar la disposición") for m in mensajes)
    for m in mensajes:
        assert not any(t in m for t in TERMINOS_PROHIBIDOS)
