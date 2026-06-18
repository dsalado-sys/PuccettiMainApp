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
    """Anexo I.5 editable (vivienda). Hotel/apt usan otro adapter."""

    def superficies_vivienda(self, n_dormitorios: int) -> dict[str, float]:
        """Mínimos y máximos por estancia para una vivienda de N dormitorios."""
        ...

    def util_objetivo_vivienda(self, n_dormitorios: int) -> float | None:
        """m² útiles objetivo por unidad (None si no hay fila → motor usa fallback)."""
        ...

    def consolidadas_vivienda(self) -> dict:
        """Mínimos/targets consolidados para `programa.cargar_desde_repo` ({} si vacía)."""
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


class CatalogoApartamentosRepositorio(Protocol):
    """Anexo I.3/I.4 editable (apartamentos turísticos · Decreto 194/2010).

    `grupo` distingue "edificios" (A1.3, 1L-4L) de "conjuntos" (A1.4, 1L/2L).
    """

    def superficies_apartamento(self, categoria: str, tipologia: str, grupo: str = "edificios") -> dict[str, float]: ...

    def util_objetivo_apartamento(self, categoria: str, tipologia: str, grupo: str = "edificios") -> float | None: ...

    def consolidadas_apartamentos(self, grupo: str = "edificios") -> dict:
        """Mínimos consolidados para `programa_apartamentos.cargar_desde_repo` ({} si vacía)."""
        ...

    def areas_comunes(self, categoria: str, grupo: str = "edificios") -> dict[str, float]: ...

    def filas_min(self, categoria: str, grupo: str = "edificios") -> list[dict]: ...

    def actualizar(
        self,
        categoria: str,
        tipologia: str,
        estancia: str,
        valor: float,
        usuario: str | None = None,
        grupo: str = "edificios",
    ) -> None: ...

    def reset(self) -> None: ...


class CatalogoHotelApartamentoRepositorio(Protocol):
    """Anexo I.2 editable (hoteles-apartamento, categorías por estrellas)."""

    def superficies(self, categoria: str, tipologia: str) -> dict[str, float]: ...

    def util_objetivo(self, categoria: str, tipologia: str) -> float | None: ...

    def consolidadas_hotel_apartamento(self) -> dict:
        """Mínimos consolidados para `programa_hotel_apartamento.cargar_desde_repo` ({} si vacía)."""
        ...

    def areas_sociales(self, categoria: str) -> dict[str, float]: ...

    def filas_min(self, categoria: str) -> list[dict]: ...

    def actualizar(
        self,
        categoria: str,
        tipologia: str,
        estancia: str,
        valor: float,
        usuario: str | None = None,
    ) -> None: ...

    def reset(self) -> None: ...


class CatalogoHoteleroRepositorio(Protocol):
    """Anexo I.1 editable (hoteles / hostales / pensiones / albergues)."""

    def superficies_habitacion(self, categoria: str, tipologia: str) -> dict[str, float]: ...

    def util_objetivo_habitacion(self, categoria: str, tipologia: str) -> float | None: ...

    def consolidadas_hotelero(self) -> dict:
        """Mínimos consolidados para `programa_hotelero.cargar_desde_repo` ({} si vacía)."""
        ...

    def areas_sociales(self, categoria: str) -> dict[str, float]: ...

    def filas_min(self, categoria: str) -> list[dict]: ...

    def actualizar(
        self,
        categoria: str,
        tipologia: str,
        estancia: str,
        valor: float,
        usuario: str | None = None,
    ) -> None: ...

    def reset(self) -> None: ...
