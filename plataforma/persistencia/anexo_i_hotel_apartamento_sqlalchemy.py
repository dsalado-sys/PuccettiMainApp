"""Adapter SQLAlchemy del Anexo I.2 (hoteles-apartamento).

Análogo a `anexo_i_apartamentos_sqlalchemy.py` pero con categorías por estrellas
("5E".."1E"). PK `(categoria, tipologia, estancia)`. Tipologías estudio/1d/2d/3d.
Áreas sociales con `categoria="comunes_<cat>"`, `tipologia="comunes"`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .sqlalchemy_base import Base


class AnexoIHotelApartamentoORM(Base):
    """Una fila por (categoría, tipología, estancia)."""

    __tablename__ = "anexo_i_hotel_apartamento"

    categoria: Mapped[str] = mapped_column(String(20), primary_key=True)
    tipologia: Mapped[str] = mapped_column(String(20), primary_key=True)
    estancia: Mapped[str] = mapped_column(String(40), primary_key=True)
    min_m2: Mapped[float] = mapped_column(Float, nullable=False)
    max_m2_util: Mapped[float] = mapped_column(Float, nullable=False)
    editable_por_usuario: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogoHotelApartamentoSQLAlchemy:
    """Implementación del puerto CatalogoHotelApartamentoRepositorio."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def superficies(self, categoria: str, tipologia: str) -> dict[str, float]:
        filas = self._session.scalars(
            select(AnexoIHotelApartamentoORM)
            .where(AnexoIHotelApartamentoORM.categoria == categoria)
            .where(AnexoIHotelApartamentoORM.tipologia == tipologia)
        ).all()
        out: dict[str, float] = {}
        for f in filas:
            out[f.estancia + "_min"] = f.min_m2
            out[f.estancia + "_max"] = f.max_m2_util
        return out

    def util_objetivo(self, categoria: str, tipologia: str) -> float | None:
        fila = self._session.scalar(
            select(AnexoIHotelApartamentoORM)
            .where(AnexoIHotelApartamentoORM.categoria == categoria)
            .where(AnexoIHotelApartamentoORM.tipologia == tipologia)
            .limit(1)
        )
        if fila is None:
            return None
        return round(float(fila.max_m2_util) * 1.15, 2)

    def areas_sociales(self, categoria: str) -> dict[str, float]:
        filas = self._session.scalars(
            select(AnexoIHotelApartamentoORM)
            .where(AnexoIHotelApartamentoORM.categoria == "comunes_" + categoria)
        ).all()
        return {f.estancia: f.min_m2 for f in filas}

    def actualizar(
        self,
        categoria: str,
        tipologia: str,
        estancia: str,
        valor: float,
        usuario: str | None = None,
    ) -> None:
        orm = self._session.get(AnexoIHotelApartamentoORM, (categoria, tipologia, estancia))
        if orm is None:
            orm = AnexoIHotelApartamentoORM(
                categoria=categoria,
                tipologia=tipologia,
                estancia=estancia,
                min_m2=valor,
                max_m2_util=valor,
                editable_por_usuario=1,
                actualizado_en=datetime.now(timezone.utc),
            )
            self._session.add(orm)
        else:
            orm.min_m2 = valor
            orm.editable_por_usuario = 1
            orm.actualizado_en = datetime.now(timezone.utc)
        self._session.commit()

    def reset(self) -> None:
        from .seed_normativa import sembrar_anexo_i_hotel_apartamento
        self._session.query(AnexoIHotelApartamentoORM).delete()
        self._session.commit()
        sembrar_anexo_i_hotel_apartamento(self._session, forzar=True)
