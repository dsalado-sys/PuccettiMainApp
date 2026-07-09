"""Siembra del primer usuario de la app.

Idempotente: solo crea el usuario inicial si la tabla está vacía.
"""
from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contextos.usuarios.dominio import Usuario
from app.contextos.usuarios.seguridad import hashear_contraseña
from app.nucleo.modelo import Rol

from .usuarios_sqlalchemy import UsuarioORM, UsuariosSQLAlchemy

# Credencial semilla del arquitecto inicial, sobreescribible por env var.
USUARIO_INICIAL = os.environ.get("PUCCETTI_ADMIN_USER", "Arquitecto0")
CONTRASENA_INICIAL = os.environ.get("PUCCETTI_ADMIN_PASSWORD", "Arquitecto0")

# Cuenta de superadministración (gestión de usuarios). Se garantiza por NOMBRE
# (no por "tabla vacía"): la tabla ya trae al arquitecto inicial, pero el
# superadmin debe existir igualmente.
SUPERADMIN_USUARIO = os.environ.get("PUCCETTI_SUPERADMIN_USER", "superadmin")
SUPERADMIN_CONTRASENA = os.environ.get("PUCCETTI_SUPERADMIN_PASSWORD", "superadmin")


def sembrar_usuarios(session: Session) -> None:
    """Crea el usuario administrador inicial si no hay ningún usuario."""
    existe = session.scalar(select(UsuarioORM).limit(1))
    if existe is None:
        repo = UsuariosSQLAlchemy(session)
        repo.guardar(
            Usuario(
                usuario=USUARIO_INICIAL,
                hash_contraseña=hashear_contraseña(CONTRASENA_INICIAL),
                rol=Rol.ARQUITECTO,
            )
        )
    sembrar_superadmin(session)


def sembrar_superadmin(session: Session) -> None:
    """Garantiza la cuenta superadmin. Idempotente por nombre de usuario."""
    repo = UsuariosSQLAlchemy(session)
    if repo.obtener_por_usuario(SUPERADMIN_USUARIO) is not None:
        return
    repo.guardar(
        Usuario(
            usuario=SUPERADMIN_USUARIO,
            hash_contraseña=hashear_contraseña(SUPERADMIN_CONTRASENA),
            rol=Rol.SUPERADMIN,
        )
    )
