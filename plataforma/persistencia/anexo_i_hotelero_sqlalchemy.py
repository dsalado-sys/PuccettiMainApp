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
        """m² útiles objetivo por unidad (Σ mínimos de las estancias × 1.15).

        Suma el `min_m2` editable de la habitación (+ baño si lo lleva), de modo que
        un mínimo editado se refleja en el objetivo (antes leía `max_m2_util` de una
        fila al azar, que no se actualizaba al editar). None si no hay filas.
        """
        filas = self._session.scalars(
            select(AnexoIHoteleroORM)
            .where(AnexoIHoteleroORM.categoria == categoria)
            .where(AnexoIHoteleroORM.tipologia == tipologia)
        ).all()
        if not filas:
            return None
        base = sum(float(f.min_m2) for f in filas)
        return round(base * 1.15, 2)

    def consolidadas_hotelero(self) -> dict:
        """Mínimos editables de BBDD en la forma de las constantes del motor (A1.1).

        `programa_hotelero.config_desde_repo` lo empaqueta en su config. Mapeo
        (excluye `comunes_*`): `habitacion` → `MIN_HABITACION[(cat, tip)]`;
        `bano` → `MIN_BANO_HOTELERO[cat]`.
        """
        filas = self._session.scalars(select(AnexoIHoteleroORM)).all()
        if not filas:
            return {}
        habitacion: dict[tuple[str, str], float] = {}
        bano: dict[str, float] = {}
        for f in filas:
            if str(f.categoria).startswith("comunes"):
                continue
            cat, tip, est = f.categoria, f.tipologia, f.estancia
            if est == "habitacion":
                habitacion[(cat, tip)] = float(f.min_m2)
            elif est == "bano":
                bano[cat] = float(f.min_m2)
        out: dict = {}
        if habitacion:
            out["MIN_HABITACION"] = habitacion
        if bano:
            out["MIN_BANO_HOTELERO"] = bano
        return out

    def areas_sociales(self, categoria: str) -> dict[str, float]:
        """Áreas sociales del establecimiento para la categoría dada."""
        filas = self._session.scalars(
            select(AnexoIHoteleroORM)
            .where(AnexoIHoteleroORM.categoria == "comunes_" + categoria)
        ).all()
        return {f.estancia: f.min_m2 for f in filas}

    def filas_min(self, categoria: str) -> list[dict]:
        """Filas del editor de mínimos para una categoría (habitaciones + áreas sociales)."""
        from .etiquetas_anexo import construir_filas_min
        unidad = self._session.scalars(
            select(AnexoIHoteleroORM)
            .where(AnexoIHoteleroORM.categoria == categoria)
        ).all()
        comunes = self._session.scalars(
            select(AnexoIHoteleroORM)
            .where(AnexoIHoteleroORM.categoria == "comunes_" + categoria)
        ).all()
        return construir_filas_min(unidad, comunes)

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
            # Invariante de fila: el mínimo no puede superar el útil máximo.
            if valor > orm.max_m2_util:
                raise ValueError(
                    f"El mínimo ({valor:g} m²) no puede superar el útil máximo "
                    f"({orm.max_m2_util:g} m²) de {categoria}/{tipologia}/{estancia}."
                )
            orm.min_m2 = valor
            orm.editable_por_usuario = 1
            orm.actualizado_en = datetime.now(timezone.utc)
        self._session.commit()

    def reset(self) -> None:
        """Reseed atómico: borrado + siembra en una transacción (rollback si el
        seed falla; nunca deja la tabla vacía)."""
        from .seed_normativa import sembrar_anexo_i_hotelero
        try:
            self._session.query(AnexoIHoteleroORM).delete()
            sembrar_anexo_i_hotelero(self._session, forzar=True, commit=False)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
