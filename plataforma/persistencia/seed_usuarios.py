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

# Credencial semilla. La gestión real de usuarios (alta, cambio de contraseña,
# rotación de la credencial inicial) se abordará más adelante; de momento se
# crea un administrador con valores fijos conocidos, sobreescribibles por env var.
USUARIO_INICIAL = os.environ.get("PUCCETTI_ADMIN_USER", "Arquitecto0")
CONTRASENA_INICIAL = os.environ.get("PUCCETTI_ADMIN_PASSWORD", "Arquitecto0")


def sembrar_usuarios(session: Session) -> None:
    """Crea el usuario administrador inicial si no hay ningún usuario."""
    existe = session.scalar(select(UsuarioORM).limit(1))
    if existe is not None:
        return
    repo = UsuariosSQLAlchemy(session)
    repo.guardar(
        Usuario(
            usuario=USUARIO_INICIAL,
            hash_contraseña=hashear_contraseña(CONTRASENA_INICIAL),
            rol=Rol.ARQUITECTO,
        )
    )
