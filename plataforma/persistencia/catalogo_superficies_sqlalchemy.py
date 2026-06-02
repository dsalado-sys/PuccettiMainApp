"""Adapter SQLAlchemy del catálogo de superficies Anexo I (editable).

En MVP solo se expone vivienda (Anexo I.5). Hotel y apartamentos turísticos
quedan como tablas vacías que se sembrarán cuando se implemente esos usos.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .sqlalchemy_base import Base


class AnexoIViviendaORM(Base):
    """Una fila por (n_dormitorios, estancia) con su mínimo y máximo (m²)."""

    __tablename__ = "anexo_i_vivienda"

    n_dormitorios: Mapped[int] = mapped_column(Integer, primary_key=True)
    estancia: Mapped[str] = mapped_column(String(40), primary_key=True)
    min_m2: Mapped[float] = mapped_column(Float, nullable=False)
    max_m2_util: Mapped[float] = mapped_column(Float, nullable=False)
    editable_por_usuario: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogoSuperficiesSQLAlchemy:
    """Implementación del puerto CatalogoSuperficiesRepositorio.

    MVP: solo vivienda. Los nombres de estancia usados como clave coinciden con
    las constantes de `geometria.programa` (`salon`, `cocina`, `bano`,
    `dormitorio_1`, ..., `aseo`).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def superficies_vivienda(self, n_dormitorios: int) -> dict[str, float]:
        filas = self._session.scalars(
            select(AnexoIViviendaORM).where(AnexoIViviendaORM.n_dormitorios == n_dormitorios)
        ).all()
        out: dict[str, float] = {}
        for f in filas:
            out[f.estancia + "_min"] = f.min_m2
            out[f.estancia + "_max"] = f.max_m2_util
        return out

    def actualizar(
        self,
        uso: str,
        categoria: str,
        estancia: str,
        valor: float,
        usuario: str | None = None,
    ) -> None:
        # uso == "vivienda" y categoria == número de dormitorios (string)
        if uso != "vivienda":
            raise NotImplementedError(
                "Anexo I solo soporta vivienda en este MVP; hotel/apt llegarán en iteración posterior."
            )
        try:
            n_dorms = int(categoria)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Categoría inválida para vivienda: {categoria!r}") from exc

        orm = self._session.get(AnexoIViviendaORM, (n_dorms, estancia))
        if orm is None:
            orm = AnexoIViviendaORM(
                n_dormitorios=n_dorms,
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
        """Reseed completo desde las constantes de `geometria.programa`."""
        from .seed_normativa import sembrar_anexo_i_vivienda
        self._session.query(AnexoIViviendaORM).delete()
        self._session.commit()
        sembrar_anexo_i_vivienda(self._session, forzar=True)
