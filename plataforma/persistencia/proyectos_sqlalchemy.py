"""Adapter SQLAlchemy del puerto ProyectoRepositorio.

Persistencia por defecto de la app. Mantiene el dominio puro: la conversión
ORM ↔ dominio vive aquí; el `Proyecto` no sabe que existe SQLAlchemy.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.contextos.proyectos.puertos import ProyectoRepositorio
from app.nucleo.modelo import EstadoProyecto, Proyecto

from .sqlalchemy_base import Base


class ProyectoORM(Base):
    __tablename__ = "proyectos"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    referencia_catastral: Mapped[str | None] = mapped_column(String(14), nullable=True)
    direccion: Mapped[str | None] = mapped_column(String(300), nullable=True)
    estado: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=EstadoProyecto.BORRADOR.value,
    )
    creado_por: Mapped[str | None] = mapped_column(String(80), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    datos_por_modulo: Mapped[dict[str, dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )


def _asegurar_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _a_dominio(orm: ProyectoORM) -> Proyecto:
    return Proyecto(
        nombre=orm.nombre,
        referencia_catastral=orm.referencia_catastral,
        direccion=orm.direccion,
        estado=EstadoProyecto(orm.estado),
        id=orm.id,
        creado_en=_asegurar_utc(orm.creado_en),
        actualizado_en=_asegurar_utc(orm.actualizado_en),
        creado_por=orm.creado_por,
        datos_por_modulo=dict(orm.datos_por_modulo or {}),
    )


def _a_orm(p: Proyecto, orm: ProyectoORM | None) -> ProyectoORM:
    orm = orm or ProyectoORM(id=p.id)
    orm.nombre = p.nombre
    orm.referencia_catastral = p.referencia_catastral
    orm.direccion = p.direccion
    orm.estado = p.estado.value
    orm.creado_por = p.creado_por
    orm.creado_en = p.creado_en
    orm.actualizado_en = p.actualizado_en
    orm.datos_por_modulo = dict(p.datos_por_modulo)
    return orm


class ProyectosSQLAlchemy(ProyectoRepositorio):
    def __init__(self, session: Session) -> None:
        self._session = session

    def guardar(self, proyecto: Proyecto) -> Proyecto:
        proyecto.tocar()
        existente = self._session.get(ProyectoORM, proyecto.id)
        orm = _a_orm(proyecto, existente)
        if existente is None:
            self._session.add(orm)
        self._session.commit()
        return _a_dominio(orm)

    def obtener(self, proyecto_id: str) -> Proyecto | None:
        orm = self._session.get(ProyectoORM, proyecto_id)
        return _a_dominio(orm) if orm else None

    def listar(self) -> list[Proyecto]:
        ormas = self._session.scalars(select(ProyectoORM)).all()
        return [_a_dominio(o) for o in ormas]

    def eliminar(self, proyecto_id: str) -> bool:
        orm = self._session.get(ProyectoORM, proyecto_id)
        if orm is None:
            return False
        self._session.delete(orm)
        self._session.commit()
        return True
