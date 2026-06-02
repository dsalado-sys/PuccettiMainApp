"""ORM y adapter del callejero INE (provincias + municipios).

Solo catálogo local; no toca el Catastro. Implementa `CallejeroPort`.
"""
from __future__ import annotations

from sqlalchemy import Index, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.contextos.localizacion.puertos import CallejeroPort

from .sqlalchemy_base import Base


class ProvinciaORM(Base):
    __tablename__ = "provincias_ine"

    codigo: Mapped[str] = mapped_column(String(2), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)


class MunicipioORM(Base):
    __tablename__ = "municipios_ine"

    codigo: Mapped[str] = mapped_column(String(5), primary_key=True)
    provincia_codigo: Mapped[str] = mapped_column(String(2), nullable=False)
    nombre: Mapped[str] = mapped_column(String(180), nullable=False)
    nombre_normalizado: Mapped[str] = mapped_column(String(180), nullable=False)


Index("ix_municipios_provincia", MunicipioORM.provincia_codigo)
Index("ix_municipios_nombre_norm", MunicipioORM.nombre_normalizado)


class CallejeroSQLAlchemy(CallejeroPort):
    def __init__(self, session: Session) -> None:
        self._session = session

    def listar_provincias(self, prefijo: str = "") -> list[tuple[str, str]]:
        stmt = select(ProvinciaORM.codigo, ProvinciaORM.nombre).order_by(ProvinciaORM.nombre)
        filas = [(c, n) for c, n in self._session.execute(stmt).all()]
        norm = _normalizar(prefijo or "")
        if norm:
            filas = [(c, n) for c, n in filas if norm in _normalizar(n)]
        return filas[:50]

    def buscar_municipios(self, provincia_codigo: str, prefijo: str) -> list[tuple[str, str]]:
        prov = (provincia_codigo or "").zfill(2)
        if not prov or len(prov) != 2:
            return []
        norm = _normalizar(prefijo or "")
        stmt = select(MunicipioORM.codigo, MunicipioORM.nombre).where(
            MunicipioORM.provincia_codigo == prov
        )
        if norm:
            # Búsqueda contains (no prefijo) sobre el nombre normalizado sin tildes.
            stmt = stmt.where(MunicipioORM.nombre_normalizado.like(f"%{norm}%"))
        stmt = stmt.order_by(MunicipioORM.nombre).limit(50)
        return [(c, n) for c, n in self._session.execute(stmt).all()]


def _normalizar(texto: str) -> str:
    """Pasa a minúsculas y quita acentos para búsqueda case/accent-insensitive."""
    import unicodedata
    t = unicodedata.normalize("NFD", texto)
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower().strip()
