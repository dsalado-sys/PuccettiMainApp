"""Adapter SQLAlchemy del puerto UmbralesPRPort (§2.9).

Umbrales internos PR como registro único (singleton `id=1`), editable por el
financiero. Sembrado con los valores de la tabla PR (defaults de `UmbralesPR`).
Mismo patrón singleton que `ParametrosMotorViviendaORM`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.contextos.viabilidad.dominio import UmbralesPR

from .sqlalchemy_base import Base

_ID_SINGLETON = 1


class UmbralesPRORM(Base):
    __tablename__ = "umbrales_pr"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tir_min_btr_residencial: Mapped[float] = mapped_column(Float, nullable=False)
    tir_min_hotelero: Mapped[float] = mapped_column(Float, nullable=False)
    tir_min_rehab_intensiva: Mapped[float] = mapped_column(Float, nullable=False)
    yield_neto_minimo: Mapped[float] = mapped_column(Float, nullable=False)
    yield_objetivo: Mapped[float] = mapped_column(Float, nullable=False)
    payback_maximo_anios: Mapped[float] = mapped_column(Float, nullable=False)
    capex_maximo_hab_eur: Mapped[float] = mapped_column(Float, nullable=False)

    actualizado_por: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _orm_a_dominio(orm: UmbralesPRORM) -> UmbralesPR:
    return UmbralesPR(
        tir_min_btr_residencial=orm.tir_min_btr_residencial,
        tir_min_hotelero=orm.tir_min_hotelero,
        tir_min_rehab_intensiva=orm.tir_min_rehab_intensiva,
        yield_neto_minimo=orm.yield_neto_minimo,
        yield_objetivo=orm.yield_objetivo,
        payback_maximo_anios=orm.payback_maximo_anios,
        capex_maximo_hab_eur=orm.capex_maximo_hab_eur,
    )


def _dominio_a_orm(u: UmbralesPR, orm: UmbralesPRORM) -> None:
    orm.tir_min_btr_residencial = u.tir_min_btr_residencial
    orm.tir_min_hotelero = u.tir_min_hotelero
    orm.tir_min_rehab_intensiva = u.tir_min_rehab_intensiva
    orm.yield_neto_minimo = u.yield_neto_minimo
    orm.yield_objetivo = u.yield_objetivo
    orm.payback_maximo_anios = u.payback_maximo_anios
    orm.capex_maximo_hab_eur = u.capex_maximo_hab_eur


class UmbralesPRSQLAlchemy:
    def __init__(self, session: Session) -> None:
        self._session = session

    def obtener(self) -> UmbralesPR:
        orm = self._session.get(UmbralesPRORM, _ID_SINGLETON)
        # Defensa: si la tabla aún no está sembrada, devuelve los defaults (tabla PR).
        return _orm_a_dominio(orm) if orm else UmbralesPR()

    def guardar(self, umbrales: UmbralesPR, usuario: str | None = None) -> None:
        orm = self._session.get(UmbralesPRORM, _ID_SINGLETON)
        if orm is None:
            orm = UmbralesPRORM(id=_ID_SINGLETON, actualizado_en=datetime.now(timezone.utc))
            self._session.add(orm)
        _dominio_a_orm(umbrales, orm)
        orm.actualizado_por = usuario
        orm.actualizado_en = datetime.now(timezone.utc)
        self._session.commit()

    def reset(self) -> None:
        """Restaura los valores sembrados (defaults de la tabla PR)."""
        self.guardar(UmbralesPR(), usuario="reset")


def sembrar_umbrales_pr(session: Session, forzar: bool = False) -> None:
    """Inserta el singleton `umbrales_pr` con los valores de la tabla PR si no existe.
    Idempotente (solo siembra si la fila no está)."""
    if not forzar:
        existe = session.get(UmbralesPRORM, _ID_SINGLETON)
        if existe is not None:
            return
    orm = session.get(UmbralesPRORM, _ID_SINGLETON)
    if orm is None:
        orm = UmbralesPRORM(id=_ID_SINGLETON, actualizado_en=datetime.now(timezone.utc))
        session.add(orm)
    _dominio_a_orm(UmbralesPR(), orm)  # defaults = valores sembrados de la tabla PR
    orm.actualizado_por = "seed"
    orm.actualizado_en = datetime.now(timezone.utc)
    session.commit()
