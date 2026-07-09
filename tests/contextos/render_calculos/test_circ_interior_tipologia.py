"""Circulación interior por tipología en m² (antes % del panel), en los 3 usos.

La circulación interior de la unidad deja de ser un % global del panel y pasa a un
m² mínimo por tipología, editable en «Ver / editar mínimos» (estancia
`circulacion_interior`). El útil objetivo/mínimo de la unidad pasa de `×(1+%)` a
`+ circ_m2`.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from app.contextos.render_calculos.geometria import (
    programa as PV, programa_apartamentos as PA, programa_hotelero as PH,
)


# ─── Vivienda ────────────────────────────────────────────────────────────────
def test_vivienda_circ_interior_es_reserva_fija_por_tipologia():
    cfg = replace(PV.CONFIG_DEFAULT, circ_interior_m2={0: 3, 1: 9, 2: 12, 3: 13, 4: 16, 5: 19})
    prog = PV.programa_vivienda(2, 70.0, cfg=cfg)
    circ = [e for e in prog if e.nombre == "circulacion_interior"]
    assert circ and circ[0].area_target_m2 == pytest.approx(12.0)
    # Σ estancias == útil asignado (la circulación es una estancia más).
    assert sum(e.area_target_m2 for e in prog) == pytest.approx(70.0, abs=0.05)


def test_vivienda_util_minimo_suma_la_circulacion_m2():
    cfg = replace(PV.CONFIG_DEFAULT, circ_interior_m2={0: 3, 1: 20, 2: 10, 3: 13, 4: 16, 5: 19})
    # 1d con circulación grande (20): el útil mínimo la incluye de forma aditiva.
    prog = PV.programa_vivienda(1, PV.util_maximo(1, cfg), cfg=cfg)
    esperado = sum(e.area_min_m2 for e in prog) + 20.0
    assert PV.util_minimo_vivienda(1, cfg=cfg) == pytest.approx(max(esperado, PV.util_minimo_tipologia(1, cfg)))


def test_config_desde_repo_mapea_circ_interior_vivienda():
    class _Cat:
        def consolidadas_vivienda(self):
            return {"CIRC_INTERIOR_M2": {2: 11.0}}
    cfg = PV.config_desde_repo(_Cat())
    assert cfg.circ_interior_m2[2] == pytest.approx(11.0)


# ─── Apartamentos ────────────────────────────────────────────────────────────
def test_apartamentos_objetivo_es_minimo_mas_circulacion():
    obj = PA.util_objetivo_apartamento("2L", "doble")
    base = PA.util_minimo_apartamento("2L", "doble")
    assert obj == pytest.approx(base + PA.circ_interior_apartamento("doble"))


def test_config_desde_repo_mapea_circ_interior_apartamentos():
    class _Cat:
        def consolidadas_apartamentos(self, grupo="edificios"):
            return {"CIRC_INTERIOR_M2": {"doble": 8.5}}
    cfg = PA.config_desde_repo(_Cat())
    assert cfg.circ_interior_m2["doble"] == pytest.approx(8.5)


# ─── Hotelero ────────────────────────────────────────────────────────────────
def test_hotelero_objetivo_es_minimo_mas_circulacion():
    obj = PH.util_objetivo_habitacion("hotel_3", "doble")
    base = PH.util_minimo_habitacion("hotel_3", "doble")
    assert obj == pytest.approx(base + PH.circ_interior_habitacion("doble"))


def test_config_desde_repo_mapea_circ_interior_hotelero():
    class _Cat:
        def consolidadas_hotelero(self):
            return {"CIRC_INTERIOR_M2": {"doble": 6.5}}
    cfg = PH.config_desde_repo(_Cat())
    assert cfg.circ_interior_m2["doble"] == pytest.approx(6.5)
