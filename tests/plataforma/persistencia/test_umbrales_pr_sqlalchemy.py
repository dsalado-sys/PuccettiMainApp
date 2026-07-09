"""Tests del adapter/seed de umbrales PR (§2.9, Fase 3) sobre SQLite en memoria."""
from __future__ import annotations

from app.contextos.viabilidad import UmbralesPR
from app.plataforma.persistencia.umbrales_pr_sqlalchemy import (
    UmbralesPRSQLAlchemy,
    sembrar_umbrales_pr,
)


def test_seed_deja_los_valores_de_la_tabla_pr(session):
    # `init_db` ya sembró la fila singleton con los defaults de la tabla PR.
    umbrales = UmbralesPRSQLAlchemy(session).obtener()
    assert umbrales == UmbralesPR()
    assert umbrales.tir_min_hotelero == 0.15
    assert umbrales.payback_maximo_anios == 18.0
    assert umbrales.capex_maximo_hab_eur == 350_000.0


def test_seed_es_idempotente(session):
    repo = UmbralesPRSQLAlchemy(session)
    repo.guardar(UmbralesPR(tir_min_hotelero=0.20), usuario="fin")
    # Re-sembrar no debe pisar lo editado (solo siembra si la fila no existe).
    sembrar_umbrales_pr(session)
    assert repo.obtener().tir_min_hotelero == 0.20


def test_guardar_y_obtener_roundtrip(session):
    repo = UmbralesPRSQLAlchemy(session)
    nuevos = UmbralesPR(
        tir_min_btr_residencial=0.14,
        yield_objetivo=0.085,
        payback_maximo_anios=15.0,
    )
    repo.guardar(nuevos, usuario="financiero")
    assert repo.obtener() == nuevos


def test_reset_restaura_los_valores_sembrados(session):
    repo = UmbralesPRSQLAlchemy(session)
    repo.guardar(UmbralesPR(tir_min_hotelero=0.25))
    repo.reset()
    assert repo.obtener() == UmbralesPR()
