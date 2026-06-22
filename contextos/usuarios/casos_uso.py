"""Casos de uso del contexto Usuarios."""
from __future__ import annotations

from dataclasses import dataclass

from .dominio import Usuario
from .puertos import UsuarioRepositorio
from .seguridad import verificar_contraseña


@dataclass
class AutenticarUsuario:
    repo: UsuarioRepositorio

    def ejecutar(self, usuario: str, contraseña: str) -> Usuario | None:
        """Devuelve el Usuario si las credenciales son válidas, o None."""
        nombre = (usuario or "").strip()
        if not nombre:
            return None
        candidato = self.repo.obtener_por_usuario(nombre)
        if candidato is None or not candidato.activo:
            return None
        if not verificar_contraseña(contraseña or "", candidato.hash_contraseña):
            return None
        return candidato
