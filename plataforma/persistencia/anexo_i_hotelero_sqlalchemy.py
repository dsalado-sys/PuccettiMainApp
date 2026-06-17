"""Adapter SQLAlchemy del Anexo I.1 (hoteles / hostales / pensiones / albergues).

Análogo a `anexo_i_apartamentos_sqlalchemy.py` pero para el modelo de
*habitación*. PK `(categoria, tipologia, estancia)`. La categoría es
"hotel_5".."hotel_1", "hostal_2"/"hostal_1", "pension", "albergue"; la tipología
es "individual"/"doble"/"triple"/"cuadruple"/"multiple". Las áreas sociales del
establecimiento se guardan con `categoria="comunes_<cat>"`, `tipologia="comunes"`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .sqlalchemy_base import Base


class AnexoIHoteleroORM(Base):
    """Una fila por (categoría, tipología, estancia)."""

    __tablename__ = "anexo_i_hotelero"

    categoria: Mapped[str] = mapped_column(String(20), primary_key=True)
    tipologia: Mapped[str] = mapped_column(String(20), primary_key=True)
    estancia: Mapped[str] = mapped_column(String(40), primary_key=True)
    min_m2: Mapped[float] = mapped_column(Float, nullable=False)
    max_m2_util: Mapped[float] = mapped_column(Float, nullable=False)
    editable_por_usuario: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogoHoteleroSQLAlchemy:
    """Implementación del puerto CatalogoHoteleroRepositorio."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def superficies_habitacion(self, categoria: str, tipologia: str) -> dict[str, float]:
        filas = self._session.scalars(
            select(AnexoIHoteleroORM)
            .where(AnexoIHoteleroORM.categoria == categoria)
            .where(AnexoIHoteleroORM.tipologia == tipologia)
        ).all()
        out: dict[str, float] = {}
        for f in filas:
            out[f.estancia + "_min"] = f.min_m2
            out[f.estancia + "_max"] = f.max_m2_util
        return out

    def util_objetivo_habitacion(self, categoria: str, tipologia: str) -> float | None:
        """m² útiles objetivo por unidad (mínimo del Anexo I.1 × 1.15).

        Las filas del mismo `(categoria, tipologia)` comparten `max_m2_util`
        (= útil mínimo de esa combinación). Si no hay filas → None (fallback motor).
        """
        fila = self._session.scalar(
            select(AnexoIHoteleroORM)
            .where(AnexoIHoteleroORM.categoria == categoria)
            .where(AnexoIHoteleroORM.tipologia == tipologia)
            .limit(1)
        )
        if fila is None:
            return None
        return round(float(fila.max_m2_util) * 1.15, 2)

    def areas_sociales(self, categoria: str) -> dict[str, float]:
        """Áreas sociales del establecimiento para la categoría dada."""
        filas = self._session.scalars(
            select(AnexoIHoteleroORM)
            .where(AnexoIHoteleroORM.categoria == "comunes_" + categoria)
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
        orm = self._session.get(AnexoIHoteleroORM, (categoria, tipologia, estancia))
        if orm is None:
            orm = AnexoIHoteleroORM(
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
        from .seed_normativa import sembrar_anexo_i_hotelero
        self._session.query(AnexoIHoteleroORM).delete()
        self._session.commit()
        sembrar_anexo_i_hotelero(self._session, forzar=True)
