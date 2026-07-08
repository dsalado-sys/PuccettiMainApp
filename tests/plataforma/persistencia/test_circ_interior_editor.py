"""La circulación interior es editable por tipología en los 3 editores de mínimos.

Se siembra como estancia `circulacion_interior` en las tablas Anexo I (vivienda,
apartamentos, hotelero); aparece en `filas_min`/`filas_vivienda`, se consolida como
`CIRC_INTERIOR_M2` y su edición se propaga por tipología (turístico/hotelero).
"""
from __future__ import annotations

import pytest

from app.plataforma.persistencia.anexo_i_apartamentos_sqlalchemy import (
    CatalogoApartamentosSQLAlchemy,
)
from app.plataforma.persistencia.anexo_i_hotelero_sqlalchemy import CatalogoHoteleroSQLAlchemy
from app.plataforma.persistencia.catalogo_superficies_sqlalchemy import (
    CatalogoSuperficiesSQLAlchemy,
)


def test_vivienda_circ_interior_editable_y_consolidada(session):
    cat = CatalogoSuperficiesSQLAlchemy(session)
    filas = [f for f in cat.filas_vivienda() if f["estancia"] == "circulacion_interior"]
    assert {f["n_dormitorios"] for f in filas} == {0, 1, 2, 3, 4, 5}
    cons = cat.consolidadas_vivienda()
    assert set(cons["CIRC_INTERIOR_M2"]) == {0, 1, 2, 3, 4, 5}
    cat.actualizar("vivienda", "2", "circulacion_interior", 14.0)
    assert cat.consolidadas_vivienda()["CIRC_INTERIOR_M2"][2] == pytest.approx(14.0)


def test_apartamentos_circ_interior_editable_y_propaga_por_tipologia(session):
    ap = CatalogoApartamentosSQLAlchemy(session)
    filas = [f for f in ap.filas_min("2L", "edificios") if f["estancia"] == "circulacion_interior"]
    assert filas, "debe aparecer la fila de circulación interior en el editor"
    cons = ap.consolidadas_apartamentos("edificios")
    assert "doble" in cons["CIRC_INTERIOR_M2"]
    # Editar la doble de una categoría se propaga a todas (valor por tipología).
    ap.actualizar("2L", "doble", "circulacion_interior", 9.0, grupo="edificios")
    assert ap.consolidadas_apartamentos("edificios")["CIRC_INTERIOR_M2"]["doble"] == pytest.approx(9.0)


def test_hotelero_circ_interior_editable_y_propaga_por_tipologia(session):
    ho = CatalogoHoteleroSQLAlchemy(session)
    filas = [f for f in ho.filas_min("hotel_3") if f["estancia"] == "circulacion_interior"]
    assert filas
    cons = ho.consolidadas_hotelero()
    assert "doble" in cons["CIRC_INTERIOR_M2"]
    ho.actualizar("hotel_3", "doble", "circulacion_interior", 7.5)
    assert ho.consolidadas_hotelero()["CIRC_INTERIOR_M2"]["doble"] == pytest.approx(7.5)
