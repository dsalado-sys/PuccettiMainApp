"""ORM del Anexo I.4 (apartamentos turísticos · grupo "conjuntos", Decreto 194/2010).

Tabla separada de `anexo_i_apartamentos` (A1.3) porque comparten la misma PK
`(categoria, tipologia, estancia)` y SQLite no permite alterar la PK de una tabla
existente. Solo admite categorías 1L/2L. El adapter es
`CatalogoApartamentosSQLAlchemy` (enruta por `grupo`).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .sqlalchemy_base import Base


class AnexoIApartamentosConjuntosORM(Base):
    """Una fila por (categoría, tipología, estancia) — grupo conjuntos (A1.4)."""

    __tablename__ = "anexo_i_apartamentos_conjuntos"

    categoria: Mapped[str] = mapped_column(String(20), primary_key=True)
    tipologia: Mapped[str] = mapped_column(String(20), primary_key=True)
    estancia: Mapped[str] = mapped_column(String(40), primary_key=True)
    min_m2: Mapped[float] = mapped_column(Float, nullable=False)
    max_m2_util: Mapped[float] = mapped_column(Float, nullable=False)
    editable_por_usuario: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
