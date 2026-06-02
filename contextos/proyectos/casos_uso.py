"""Casos de uso del contexto Proyectos (§2.11)."""
from __future__ import annotations

from dataclasses import dataclass

from app.nucleo.modelo import Proyecto

from .puertos import ProyectoRepositorio


@dataclass
class CrearProyecto:
    repo: ProyectoRepositorio

    def ejecutar(
        self,
        nombre: str,
        referencia_catastral: str | None = None,
        direccion: str | None = None,
        creado_por: str | None = None,
    ) -> Proyecto:
        nombre_limpio = (nombre or "").strip()
        if not nombre_limpio:
            raise ValueError("El nombre del proyecto no puede estar vacío.")
        proyecto = Proyecto(
            nombre=nombre_limpio,
            referencia_catastral=referencia_catastral,
            direccion=direccion,
            creado_por=creado_por,
        )
        return self.repo.guardar(proyecto)


@dataclass
class ListarProyectos:
    repo: ProyectoRepositorio

    def ejecutar(self) -> list[Proyecto]:
        proyectos = self.repo.listar()
        proyectos.sort(key=lambda p: p.actualizado_en, reverse=True)
        return proyectos


@dataclass
class ObtenerProyecto:
    repo: ProyectoRepositorio

    def ejecutar(self, proyecto_id: str) -> Proyecto | None:
        return self.repo.obtener(proyecto_id)


@dataclass
class EliminarProyecto:
    repo: ProyectoRepositorio

    def ejecutar(self, proyecto_id: str) -> bool:
        return self.repo.eliminar(proyecto_id)
