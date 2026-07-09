"""Útil mínimo editable por tipología (vivienda) como suelo duro del reparto.

Verifica que (a) `util_minimo_vivienda` nunca baja del útil mínimo configurable,
(b) el descriptor apunta al mínimo como objetivo y a `mínimo + margen` como techo,
y (c) el reparto multi-tipología no dimensiona ninguna vivienda por debajo del
mínimo y cada unidad cae en `[mínimo, mínimo + margen]`.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from app.contextos.render_calculos.geometria import programa as P


def _cfg_con_minimos(util_min: dict[int, float]) -> P.ProgramaViviendaConfig:
    """Config con útil mínimo editado y máximo derivado = mínimo + margen."""
    util_max = {n: v + P.MARGEN_UTIL_MAXIMO_VIVIENDA for n, v in util_min.items()}
    return replace(P.CONFIG_DEFAULT, util_min=dict(util_min), util_max=util_max)


def test_util_minimo_vivienda_respeta_suelo_duro():
    cfg = _cfg_con_minimos({0: 40, 1: 80, 2: 90, 3: 90, 4: 110, 5: 130})
    # El mínimo blando calculado (Σmín × factor) de 1d ronda 48; el suelo lo eleva.
    assert P.util_minimo_vivienda(1, cfg=cfg) == pytest.approx(80.0)
    # Estudio: el suelo también aplica por encima del umbral VPO (25).
    assert P.util_minimo_vivienda(0, cfg=cfg) == pytest.approx(40.0)


def test_descriptor_objetivo_es_minimo_y_maximo_es_minimo_mas_margen():
    cfg = _cfg_con_minimos({n: v for n, v in P.UTIL_MAX.items()})
    d = P.descriptor_tipologia_vivienda(2, cfg=cfg)
    assert d.util_objetivo == pytest.approx(70.0)
    assert d.util_minimo == pytest.approx(70.0)
    assert d.util_maximo == pytest.approx(70.0 + P.MARGEN_UTIL_MAXIMO_VIVIENDA)


def test_reparto_multi_nunca_baja_del_minimo():
    cfg = _cfg_con_minimos({0: 40, 1: 60, 2: 70, 3: 90, 4: 110, 5: 130})
    d1 = P.descriptor_tipologia_vivienda(1, cfg=cfg)
    d2 = P.descriptor_tipologia_vivienda(2, cfg=cfg)
    seleccion = P.reparto_multi_tipologia_generico(200.0, [d1, d2])
    assert seleccion, "debería caber al menos una unidad"
    for desc, util in seleccion:
        piso = P.util_minimo_tipologia(desc.n_dorms_label, cfg)
        techo = piso + P.MARGEN_UTIL_MAXIMO_VIVIENDA
        assert util >= piso - 1e-6, f"{desc.n_dorms_label}d por debajo del mínimo"
        assert util <= techo + 1e-6, f"{desc.n_dorms_label}d por encima de mín+margen"


def test_estancias_suman_el_util_asignado_por_encima_del_minimo():
    cfg = _cfg_con_minimos({0: 40, 1: 60, 2: 70, 3: 90, 4: 110, 5: 130})
    # Una vivienda de 1d a su útil mínimo: las estancias suman exactamente ese útil.
    estancias = P.programa_vivienda(1, util_disponible=60.0, cfg=cfg)
    total = sum(e.area_target_m2 for e in estancias)
    assert total == pytest.approx(60.0, abs=0.05)
    assert total >= P.util_minimo_tipologia(1, cfg) - 0.05


def test_config_desde_repo_mapea_util_min(monkeypatch):
    class _CatFake:
        def consolidadas_vivienda(self):
            return {"UTIL_MIN": {1: 66.0}, "UTIL_MAX": {1: 71.0}}

    cfg = P.config_desde_repo(_CatFake())
    assert cfg.util_min[1] == pytest.approx(66.0)
    assert cfg.util_max[1] == pytest.approx(71.0)
    assert P.util_minimo_tipologia(1, cfg) == pytest.approx(66.0)
