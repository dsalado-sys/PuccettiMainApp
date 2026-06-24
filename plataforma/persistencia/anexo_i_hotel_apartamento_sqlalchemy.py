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
        """m² útiles objetivo por unidad (Σ mínimos de las estancias × 1.15).

        Suma el `min_m2` editable de cada estancia de la unidad, de modo que un
        mínimo editado se refleja en el objetivo (antes leía `max_m2_util` de una
        fila al azar, que no se actualizaba al editar). None si no hay filas.
        """
        filas = self._session.scalars(
            select(AnexoIHotelApartamentoORM)
            .where(AnexoIHotelApartamentoORM.categoria == categoria)
            .where(AnexoIHotelApartamentoORM.tipologia == tipologia)
        ).all()
        if not filas:
            return None
        base = sum(float(f.min_m2) for f in filas)
        return round(base * 1.15, 2)

    def consolidadas_hotel_apartamento(self) -> dict:
        """Mínimos editables de BBDD en la forma de las constantes del motor (A1.2).

        `programa_hotel_apartamento.config_desde_repo` lo empaqueta en su config.
        Mapeo (excluye `comunes_*`): `dormitorio_1` → `MIN_DORMITORIO_HAP[tip][cat]`;
        `salon_comedor` del estudio → `MIN_ESTUDIO_HAP[cat]`; `salon_comedor` de la
        doble → `MIN_SALON_COMEDOR_HAP[cat]`; `bano` → `MIN_BANO_HAP[cat]`.
        """
        filas = self._session.scalars(select(AnexoIHotelApartamentoORM)).all()
        if not filas:
            return {}
        dorm: dict[str, dict[str, float]] = {}
        estudio: dict[str, float] = {}
        salon: dict[str, float] = {}
        bano: dict[str, float] = {}
        for f in filas:
            if str(f.categoria).startswith("comunes"):
                continue
            cat, tip, est = f.categoria, f.tipologia, f.estancia
            if est == "dormitorio_1" and tip in ("individual", "doble", "triple", "cuadruple"):
                dorm.setdefault(tip, {})[cat] = float(f.min_m2)
            elif est == "bano":
                bano[cat] = float(f.min_m2)
            elif est == "salon_comedor":
                if tip == "estudio":
                    estudio[cat] = float(f.min_m2)
                elif tip == "doble":
                    salon[cat] = float(f.min_m2)
        out: dict = {}
        if dorm:
            out["MIN_DORMITORIO_HAP"] = dorm
        if estudio:
            out["MIN_ESTUDIO_HAP"] = estudio
        if salon:
            out["MIN_SALON_COMEDOR_HAP"] = salon
        if bano:
            out["MIN_BANO_HAP"] = bano
        return out

    def areas_sociales(self, categoria: str) -> dict[str, float]:
        filas = self._session.scalars(
            select(AnexoIHotelApartamentoORM)
            .where(AnexoIHotelApartamentoORM.categoria == "comunes_" + categoria)
        ).all()
        return {f.estancia: f.min_m2 for f in filas}

    def filas_min(self, categoria: str) -> list[dict]:
        """Filas del editor de mínimos para una categoría (unidades + áreas sociales)."""
        from .etiquetas_anexo import construir_filas_min
        unidad = self._session.scalars(
            select(AnexoIHotelApartamentoORM)
            .where(AnexoIHotelApartamentoORM.categoria == categoria)
        ).all()
        comunes = self._session.scalars(
            select(AnexoIHotelApartamentoORM)
            .where(AnexoIHotelApartamentoORM.categoria == "comunes_" + categoria)
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
        from .seed_normativa import sembrar_anexo_i_hotel_apartamento
        try:
            self._session.query(AnexoIHotelApartamentoORM).delete()
            sembrar_anexo_i_hotel_apartamento(self._session, forzar=True, commit=False)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
