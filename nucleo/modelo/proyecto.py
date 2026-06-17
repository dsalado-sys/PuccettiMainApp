"""Proyecto: la unidad de trabajo compartida entre todos los módulos (§2.11).

Un Proyecto encapsula un estudio de prefactibilidad concreto sobre un activo.
Cada módulo (localización, viabilidad, render, informe…) lee y enriquece el
mismo Proyecto, de forma que la información viaje sin copia entre pestañas.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EstadoProyecto(str, Enum):
    BORRADOR = "borrador"
    EN_ANALISIS = "en_analisis"
    ENTREGADO = "entregado"
    ARCHIVADO = "archivado"


class ModuloPuccetti(str, Enum):
    """Catálogo de módulos integrados. Estable: añadir nunca renombrar."""
    LOCALIZACION = "localizacion"
    VIABILIDAD = "viabilidad"
    RENDER_CALCULOS = "render_calculos"
    MODELOS_PLANOS = "modelos_planos"
    INFORME = "informe"
    PROYECTOS = "proyectos"
    NORMATIVA_MUNICIPAL = "normativa_municipal"


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Proyecto:
    """Aggregate root de §2.11.

    Cada módulo escribe en su propio rincón de `datos_por_modulo` usando la
    clave del enum ModuloPuccetti. Así el Proyecto sirve de bus de información
    entre módulos sin que ninguno conozca a los demás.
    """
    nombre: str
    referencia_catastral: str | None = None
    direccion: str | None = None
    estado: EstadoProyecto = EstadoProyecto.BORRADOR
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    creado_en: datetime = field(default_factory=_ahora)
    actualizado_en: datetime = field(default_factory=_ahora)
    creado_por: str | None = None
    datos_por_modulo: dict[str, dict[str, Any]] = field(default_factory=dict)

    def datos(self, modulo: ModuloPuccetti) -> dict[str, Any]:
        return self.datos_por_modulo.setdefault(modulo.value, {})

    def fijar_datos(self, modulo: ModuloPuccetti, datos: dict[str, Any]) -> None:
        self.datos_por_modulo[modulo.value] = datos
        self.actualizado_en = _ahora()

    def tocar(self) -> None:
        self.actualizado_en = _ahora()
