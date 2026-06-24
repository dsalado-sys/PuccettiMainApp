"""Siembra del primer usuario de la app.

Idempotente: solo crea el usuario inicial si la tabla está vacía.
"""
from __future__ import annotations

import logging
import os
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contextos.usuarios.dominio import Usuario
from app.contextos.usuarios.seguridad import hashear_contraseña
from app.nucleo.modelo import Rol

from .usuarios_sqlalchemy import UsuarioORM, UsuariosSQLAlchemy

log = logging.getLogger(__name__)

USUARIO_INICIAL = os.environ.get("PUCCETTI_ADMIN_USER", "Arquitecto0")


def _contrasena_inicial() -> tuple[str, bool]:
    """Devuelve (contraseña, generada).

    Prioriza `PUCCETTI_ADMIN_PASSWORD`. Si no está definida, genera una aleatoria
    (en vez del antiguo literal predecible `Arquitecto0`) que se comunica una sola
    vez al crear el usuario, para forzar su cambio antes de exponer la app.
    """
    env = os.environ.get("PUCCETTI_ADMIN_PASSWORD")
    if env:
        return env, False
    return secrets.token_urlsafe(12), True


def sembrar_usuarios(session: Session) -> None:
    """Crea el usuario administrador inicial si no hay ningún usuario."""
    existe = session.scalar(select(UsuarioORM).limit(1))
    if existe is not None:
        return
    clave, generada = _contrasena_inicial()
    repo = UsuariosSQLAlchemy(session)
    repo.guardar(
        Usuario(
            usuario=USUARIO_INICIAL,
            hash_contraseña=hashear_contraseña(clave),
            rol=Rol.ARQUITECTO,
        )
    )
    if generada:
        # Única vez: sin esto el operador no sabría la contraseña. Cámbiala tras
        # el primer acceso (o define PUCCETTI_ADMIN_PASSWORD antes del arranque).
        msg = (
            f"Usuario inicial creado: {USUARIO_INICIAL!r} con contraseña "
            f"generada {clave!r}. Cámbiala tras el primer acceso."
        )
        log.warning(msg)
        print(f"\n[Puccetti] {msg}\n")
