"""Puertos del módulo Render y cálculos.

Interfaces (Protocol) que los casos de uso necesitan. La implementación vive en
`plataforma/persistencia/`. El dominio no sabe que existe SQLAlchemy.
"""
from __future__ import annotations

from typing import Any, Protocol

from .parametros import ParametrosUrbanisticos


class NormativaMunicipalRepositorio(Protocol):
    """req. 3 — BBDD de normativas urbanísticas municipales (consultar/actualizar)."""

    def obtener(self, municipio: str, provincia: str) -> ParametrosUrbanisticos | None: ...

    def guardar(
        self,
        municipio: str,
        provincia: str,
        params: ParametrosUrbanisticos,
        fuente_pgou: str,
        usuario: str | None = None,
    ) -> None: ...

    def listar(self) -> list[dict[str, Any]]: ...

    def eliminar(self, municipio: str, provincia: str) -> bool: ...


class CatalogoSuperficiesRepositorio(Protocol):
    """Anexo I editable (vivienda en MVP; hotel/apt en iteración posterior)."""

    def superficies_vivienda(self, n_dormitorios: int) -> dict[str, float]:
        """Mínimos y máximos por estancia para una vivienda de N dormitorios."""
        ...

    def actualizar(
        self,
        uso: str,
        categoria: str,
        estancia: str,
        valor: float,
        usuario: str | None = None,
    ) -> None: ...

    def reset(self) -> None: ...
