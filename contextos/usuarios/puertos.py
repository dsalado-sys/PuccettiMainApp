"""Puertos del contexto Usuarios."""
from __future__ import annotations

from typing import Protocol

from .dominio import Usuario


class UsuarioRepositorio(Protocol):
    """Persistencia de usuarios. Implementaciones: en memoria, SQLite, Postgres."""

    def obtener_por_usuario(self, usuario: str) -> Usuario | None: ...
    def obtener_por_id(self, usuario_id: str) -> Usuario | None: ...
    def guardar(self, usuario: Usuario) -> Usuario: ...
    def listar(self) -> list[Usuario]: ...
