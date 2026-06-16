"""Tests del parseo de superficies del Catastro (§2.1).

Regresión del bug: una subreferencia de "1.087" m² (formato español, punto =
millar) se tomaba como 1.087 m² al aplicar float() directo. Todo es función
pura sobre dicts/objetos mock: NO se hace ninguna llamada al Catastro.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.plataforma.catastro.catastro_meh import (
    _subref_de_item,
    _superficie_catastro,
    _superficie_construida_de_parcela,
)


# ── _superficie_catastro: formato español, sin redondeo ni truncado ─────────
@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("1.087", 1087.0),           # el bug original: punto = millar, no decimal
        ("87", 87.0),
        ("999", 999.0),
        ("1.000", 1000.0),
        ("12.345.678", 12345678.0),  # varios separadores de millar
        ("1.234,56", 1234.56),       # millar + decimal con coma
        ("87,5", 87.5),              # decimal sin millar
        ("0,75", 0.75),
        ("", 0.0),
        (None, 0.0),
        ("   1.087  ", 1087.0),      # espacios alrededor
        ("no-numérico", 0.0),
    ],
)
def test_superficie_catastro_formato_espanol(entrada, esperado):
    assert _superficie_catastro(entrada) == pytest.approx(esperado)


def test_superficie_catastro_acepta_numeros_nativos_intactos():
    # int/float ya nativos se devuelven tal cual, sin reinterpretar.
    assert _superficie_catastro(1087) == 1087.0
    assert _superficie_catastro(1234.56) == pytest.approx(1234.56)
    assert _superficie_catastro(0) == 0.0


def test_superficie_catastro_conserva_decimales_sin_truncar():
    # No se trunca ni redondea: el valor recogido queda intacto para operar.
    assert _superficie_catastro("1.234,567") == pytest.approx(1234.567)


# ── _subref_de_item: la superficie llega correcta desde el JSON DNPRC ───────
def _item_dnprc(sfc: str, luso: str = "Residencial") -> dict:
    """Imita un elemento del array `rcdnp` del Catastro con un `sfc` dado."""
    return {
        "rc": {"pc1": "1234567", "pc2": "AB1234C", "car": "0001", "cc1": "X", "cc2": "Y"},
        "dt": {"locs": {"lous": {"lourb": {"loint": {"es": "1", "pt": "03", "pu": "B"}}}}},
        "debi": {"sfc": sfc, "luso": luso},
    }


def test_subref_de_item_superficie_mayor_de_mil():
    s = _subref_de_item(_item_dnprc("1.087"))
    assert s.superficie_construida_m2 == 1087.0
    assert s.uso == "Residencial"
    assert s.localizacion == "Es 1 · Pl 03 · Pt B"


def test_subref_de_item_suma_de_metaparcela_intacta():
    items = [_item_dnprc("1.087"), _item_dnprc("868"), _item_dnprc("1.234,56")]
    subrefs = [_subref_de_item(it) for it in items]
    suma = sum(s.superficie_construida_m2 for s in subrefs)
    assert suma == pytest.approx(1087.0 + 868.0 + 1234.56)


# ── _superficie_construida_de_parcela: parcela única (regiones) ─────────────
def test_superficie_construida_suma_regiones_con_formato_espanol():
    p = SimpleNamespace(regiones=[
        {"descripcion": "VIVIENDA", "superficie": "1.087"},
        {"descripcion": "GARAJE", "superficie": "25"},
    ])
    assert _superficie_construida_de_parcela(p) == pytest.approx(1112.0)


def test_superficie_construida_sin_regiones_devuelve_none():
    assert _superficie_construida_de_parcela(SimpleNamespace()) is None
    assert _superficie_construida_de_parcela(SimpleNamespace(regiones=[])) is None
