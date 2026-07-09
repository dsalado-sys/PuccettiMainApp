"""Útil mínimo editable por tipología en el catálogo de vivienda (Anexo I.5).

El seed puebla `min_m2_util` (= base) y `max_m2_util` (= base + margen); el editor
lo expone como fila `_util_minimo` por tipología y `consolidadas_vivienda` emite
`UTIL_MIN`/`UTIL_MAX`. Editar el mínimo se propaga a todas las estancias y respeta
el invariante «no por debajo del mayor mínimo de estancia».
"""
from __future__ import annotations

import pytest

from app.contextos.render_calculos.geometria.programa import MARGEN_UTIL_MAXIMO_VIVIENDA
from app.plataforma.persistencia.catalogo_superficies_sqlalchemy import (
    CatalogoSuperficiesSQLAlchemy,
)

_BASE = {0: 40.0, 1: 60.0, 2: 70.0, 3: 90.0, 4: 110.0, 5: 130.0}


def test_seed_puebla_min_y_max_derivado(session):
    cat = CatalogoSuperficiesSQLAlchemy(session)
    cons = cat.consolidadas_vivienda()
    assert cons["UTIL_MIN"] == pytest.approx(_BASE)
    for n, base in _BASE.items():
        assert cons["UTIL_MAX"][n] == pytest.approx(base + MARGEN_UTIL_MAXIMO_VIVIENDA)


def test_util_objetivo_vivienda_es_el_minimo(session):
    cat = CatalogoSuperficiesSQLAlchemy(session)
    assert cat.util_objetivo_vivienda(2) == pytest.approx(70.0)
    assert cat.util_objetivo_vivienda(0) == pytest.approx(40.0)


def test_filas_incluyen_util_minimo_por_tipologia(session):
    cat = CatalogoSuperficiesSQLAlchemy(session)
    umin = [f for f in cat.filas_vivienda() if f["estancia"] == "_util_minimo"]
    assert {f["n_dormitorios"] for f in umin} == set(_BASE)
    for f in umin:
        assert f["ambito"] == "tipologia"
        assert f["min_m2"] == pytest.approx(_BASE[f["n_dormitorios"]])


def test_editar_util_minimo_propaga_y_deriva_maximo(session):
    cat = CatalogoSuperficiesSQLAlchemy(session)
    cat.actualizar("vivienda", "2", "_util_minimo", 75.0)
    cons = cat.consolidadas_vivienda()
    assert cons["UTIL_MIN"][2] == pytest.approx(75.0)
    assert cons["UTIL_MAX"][2] == pytest.approx(75.0 + MARGEN_UTIL_MAXIMO_VIVIENDA)


def test_editar_util_minimo_por_debajo_de_estancia_falla(session):
    cat = CatalogoSuperficiesSQLAlchemy(session)
    with pytest.raises(ValueError):
        cat.actualizar("vivienda", "2", "_util_minimo", 3.0)


def test_reset_restaura_min_y_max(session):
    cat = CatalogoSuperficiesSQLAlchemy(session)
    cat.actualizar("vivienda", "1", "_util_minimo", 80.0)
    cat.reset()
    cons = cat.consolidadas_vivienda()
    assert cons["UTIL_MIN"][1] == pytest.approx(60.0)
    assert cons["UTIL_MAX"][1] == pytest.approx(60.0 + MARGEN_UTIL_MAXIMO_VIVIENDA)
