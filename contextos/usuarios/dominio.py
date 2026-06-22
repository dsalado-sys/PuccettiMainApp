"""Usuario: identidad que inicia sesión en la app.

El rol vive en el lenguaje ubicuo (`nucleo.modelo.rol`); aquí solo se asocia al
usuario. La contraseña nunca se guarda en claro: el dominio almacena su hash y
delega el hasheo/verificación en `seguridad`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.nucleo.modelo import Rol


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Usuario:
    """Cuenta de acceso. `usuario` es único y sirve de credencial de login."""
    usuario: str
    hash_contraseña: str
    rol: Rol = Rol.ARQUITECTO
    activo: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    creado_en: datetime = field(default_factory=_ahora)
