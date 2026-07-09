"""§2.9 — Puertos del contexto viabilidad.

Interfaces (Protocol) que los casos de uso necesitan. La implementación vive en
`plataforma/persistencia/`. El dominio no sabe que existe SQLAlchemy.
"""
from __future__ import annotations

from typing import Protocol

from .dominio import Benchmarks, UmbralesPR


class BenchmarksPort(Protocol):
    """Fuente de comparables de mercado (RevPAR/ADR/yield). Sin implementación
    automática todavía (PR / STR / Idealista); de momento los comparables se
    introducen a mano y se guardan en el aggregate. Este puerto es la costura para
    cablear la fuente real cuando exista."""

    def comparables(self, municipio: str, tipologia: str) -> Benchmarks | None: ...


class UmbralesPRPort(Protocol):
    """Umbrales internos PR: un único registro global (config), editable por el
    financiero. Sembrado con los valores de la tabla PR (ver `dominio.UmbralesPR`)."""

    def obtener(self) -> UmbralesPR:
        """Devuelve los umbrales vigentes (los sembrados si nadie los editó)."""
        ...

    def guardar(self, umbrales: UmbralesPR, usuario: str | None = None) -> None: ...

    def reset(self) -> None:
        """Restaura los umbrales sembrados (valores de la tabla PR)."""
        ...
