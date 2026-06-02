"""Adapter de persistencia en memoria. Para arrancar y para tests.

Se sustituirá por SQLite cuando §2.11 entre en producción; el caso de uso no
notará la diferencia porque depende del puerto, no de la implementación.
"""
from __future__ import annotations

from threading import RLock

from app.contextos.proyectos.puertos import ProyectoRepositorio
from app.nucleo.modelo import Proyecto


class ProyectosEnMemoria(ProyectoRepositorio):
    def __init__(self) -> None:
        self._proyectos: dict[str, Proyecto] = {}
        self._lock = RLock()

    def guardar(self, proyecto: Proyecto) -> Proyecto:
        with self._lock:
            proyecto.tocar()
            self._proyectos[proyecto.id] = proyecto
            return proyecto

    def obtener(self, proyecto_id: str) -> Proyecto | None:
        with self._lock:
            return self._proyectos.get(proyecto_id)

    def listar(self) -> list[Proyecto]:
        with self._lock:
            return list(self._proyectos.values())

    def eliminar(self, proyecto_id: str) -> bool:
        with self._lock:
            return self._proyectos.pop(proyecto_id, None) is not None
