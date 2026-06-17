"""Carpetas de normativa y normativas archivadas en cada carpeta.

Modelo ligero: los datos urbanísticos se guardan como JSON en la columna
`datos_json` para evitar duplicar el esquema de `NormativaMunicipalORM`.
La estructura del JSON es la misma que produce `parametros_a_dict()` para
el bloque `urbanisticos`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .sqlalchemy_base import Base


class CarpetaNormativaORM(Base):
    __tablename__ = "carpeta_normativa"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NormativaArchivadaORM(Base):
    __tablename__ = "normativa_archivada"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    carpeta_id: Mapped[int] = mapped_column(
        ForeignKey("carpeta_normativa.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    direccion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    datos_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CarpetasNormativaSQLAlchemy:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Carpetas ──────────────────────────────────────────────────────────
    def listar_carpetas(self) -> list[dict[str, Any]]:
        items = self._session.scalars(
            select(CarpetaNormativaORM).order_by(CarpetaNormativaORM.nombre)
        ).all()
        return [{"id": c.id, "nombre": c.nombre} for c in items]

    def crear_carpeta(self, nombre: str) -> dict[str, Any]:
        nombre = nombre.strip()
        if not nombre:
            raise ValueError("El nombre de la carpeta no puede estar vacío.")
        existe = self._session.scalar(
            select(CarpetaNormativaORM).where(CarpetaNormativaORM.nombre == nombre)
        )
        if existe is not None:
            return {"id": existe.id, "nombre": existe.nombre}
        orm = CarpetaNormativaORM(nombre=nombre, creado_en=datetime.now(timezone.utc))
        self._session.add(orm)
        self._session.commit()
        return {"id": orm.id, "nombre": orm.nombre}

    def eliminar_carpeta(self, carpeta_id: int) -> bool:
        orm = self._session.get(CarpetaNormativaORM, carpeta_id)
        if orm is None:
            return False
        # Borrar también todas las normativas dentro (no hay ON DELETE CASCADE
        # automático en SQLite sin PRAGMA explícito).
        self._session.query(NormativaArchivadaORM).filter(
            NormativaArchivadaORM.carpeta_id == carpeta_id
        ).delete(synchronize_session=False)
        self._session.delete(orm)
        self._session.commit()
        return True

    # ── Normativas archivadas ─────────────────────────────────────────────
    def listar_normativas(self, carpeta_id: int) -> list[dict[str, Any]]:
        items = self._session.scalars(
            select(NormativaArchivadaORM)
            .where(NormativaArchivadaORM.carpeta_id == carpeta_id)
            .order_by(NormativaArchivadaORM.nombre)
        ).all()
        return [
            {"id": n.id, "nombre": n.nombre, "direccion": n.direccion}
            for n in items
        ]

    def obtener_normativa(self, normativa_id: int) -> dict[str, Any] | None:
        orm = self._session.get(NormativaArchivadaORM, normativa_id)
        if orm is None:
            return None
        try:
            datos = json.loads(orm.datos_json or "{}")
        except json.JSONDecodeError:
            datos = {}
        return {
            "id": orm.id,
            "carpeta_id": orm.carpeta_id,
            "nombre": orm.nombre,
            "direccion": orm.direccion,
            "urbanisticos": datos,
        }

    def crear_normativa(
        self,
        carpeta_id: int,
        nombre: str,
        direccion: str,
        urbanisticos: dict[str, Any],
    ) -> dict[str, Any]:
        carpeta = self._session.get(CarpetaNormativaORM, carpeta_id)
        if carpeta is None:
            raise ValueError(f"Carpeta {carpeta_id} no existe.")
        nombre = (nombre or "").strip()
        if not nombre:
            raise ValueError("El nombre de la normativa no puede estar vacío.")
        ahora = datetime.now(timezone.utc)
        orm = NormativaArchivadaORM(
            carpeta_id=carpeta_id,
            nombre=nombre,
            direccion=(direccion or "").strip(),
            datos_json=json.dumps(urbanisticos or {}),
            creado_en=ahora,
            actualizado_en=ahora,
        )
        self._session.add(orm)
        self._session.commit()
        return {"id": orm.id, "nombre": orm.nombre, "direccion": orm.direccion}

    def actualizar_normativa(
        self,
        normativa_id: int,
        nombre: str,
        direccion: str,
        urbanisticos: dict[str, Any],
    ) -> bool:
        orm = self._session.get(NormativaArchivadaORM, normativa_id)
        if orm is None:
            return False
        nombre = (nombre or "").strip()
        if nombre:
            orm.nombre = nombre
        orm.direccion = (direccion or "").strip()
        orm.datos_json = json.dumps(urbanisticos or {})
        orm.actualizado_en = datetime.now(timezone.utc)
        self._session.commit()
        return True

    def eliminar_normativa(self, normativa_id: int) -> bool:
        orm = self._session.get(NormativaArchivadaORM, normativa_id)
        if orm is None:
            return False
        self._session.delete(orm)
        self._session.commit()
        return True
