"""Adapter SQLAlchemy del puerto UsuarioRepositorio.

Persistencia por defecto de usuarios. La conversión ORM ↔ dominio vive aquí;
el `Usuario` no sabe que existe SQLAlchemy.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.contextos.usuarios.dominio import Usuario
from app.contextos.usuarios.puertos import UsuarioRepositorio
from app.nucleo.modelo import Rol

from .sqlalchemy_base import Base


class UsuarioORM(Base):
    __tablename__ = "usuarios"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    usuario: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    hash_contraseña: Mapped[str] = mapped_column(String(255), nullable=False)
    rol: Mapped[str] = mapped_column(String(40), nullable=False, default=Rol.ARQUITECTO.value)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _asegurar_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _a_dominio(orm: UsuarioORM) -> Usuario:
    return Usuario(
        usuario=orm.usuario,
        hash_contraseña=orm.hash_contraseña,
        rol=Rol(orm.rol),
        activo=orm.activo,
        id=orm.id,
        creado_en=_asegurar_utc(orm.creado_en),
    )


def _a_orm(u: Usuario, orm: UsuarioORM | None) -> UsuarioORM:
    orm = orm or UsuarioORM(id=u.id)
    orm.usuario = u.usuario
    orm.hash_contraseña = u.hash_contraseña
    orm.rol = u.rol.value
    orm.activo = u.activo
    orm.creado_en = u.creado_en
    return orm


class UsuariosSQLAlchemy(UsuarioRepositorio):
    def __init__(self, session: Session) -> None:
        self._session = session

    def obtener_por_usuario(self, usuario: str) -> Usuario | None:
        orm = self._session.scalar(
            select(UsuarioORM).where(UsuarioORM.usuario == usuario)
        )
        return _a_dominio(orm) if orm else None

    def obtener_por_id(self, usuario_id: str) -> Usuario | None:
        orm = self._session.get(UsuarioORM, usuario_id)
        return _a_dominio(orm) if orm else None

    def guardar(self, usuario: Usuario) -> Usuario:
        existente = self._session.get(UsuarioORM, usuario.id)
        orm = _a_orm(usuario, existente)
        if existente is None:
            self._session.add(orm)
        self._session.commit()
        return _a_dominio(orm)

    def listar(self) -> list[Usuario]:
        ormas = self._session.scalars(select(UsuarioORM)).all()
        return [_a_dominio(o) for o in ormas]
