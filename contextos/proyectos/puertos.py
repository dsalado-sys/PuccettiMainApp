"""Puertos del contexto Proyectos (§2.11)."""
from __future__ import annotations

from typing import Protocol

from app.nucleo.modelo import Proyecto


class ProyectoRepositorio(Protocol):
    """Persistencia de proyectos. Implementaciones: en memoria, SQLite, Postgres."""

    def guardar(self, proyecto: Proyecto) -> Proyecto: ...
    def obtener(self, proyecto_id: str) -> Proyecto | None: ...
    def listar(self) -> list[Proyecto]: ...
    def eliminar(self, proyecto_id: str) -> bool: ...
