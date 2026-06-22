"""Siembra del primer usuario de la app.

Idempotente: solo crea el usuario inicial si la tabla está vacía.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contextos.usuarios.dominio import Usuario
from app.contextos.usuarios.seguridad import hashear_contraseña
from app.nucleo.modelo import Rol

from .usuarios_sqlalchemy import UsuarioORM, UsuariosSQLAlchemy

USUARIO_INICIAL = "Arquitecto0"
CONTRASEÑA_INICIAL = "Arquitecto0"


def sembrar_usuarios(session: Session) -> None:
    """Crea el usuario inicial `Arquitecto0` si no hay ningún usuario."""
    existe = session.scalar(select(UsuarioORM).limit(1))
    if existe is not None:
        return
    repo = UsuariosSQLAlchemy(session)
    repo.guardar(
        Usuario(
            usuario=USUARIO_INICIAL,
            hash_contraseña=hashear_contraseña(CONTRASEÑA_INICIAL),
            rol=Rol.ARQUITECTO,
        )
    )
