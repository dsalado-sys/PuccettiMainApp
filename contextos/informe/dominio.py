"""Módulo Informe (§2.8) — dominio del documento de prefactibilidad.

Modelo de un **informe exportable**: una proyección de solo lectura sobre los
datos ya trazados en el aggregate `Proyecto`. No calcula ni inventa cifras; cada
sección declara su `EstadoSeccion` según qué datos existen DE VERDAD. Lo que la
app aún no tiene se marca `PENDIENTE`/`RESERVADA` con una nota explícita, y nunca
se rellena con datos inventados — ese es el mecanismo anti-alucinación del módulo.

Espejo del patrón de `contextos/proyectos/flujo.py`: dominio puro (sin FastAPI ni
SQLAlchemy); el ensamblado vive en `casos_uso.py` y el wiring entre módulos en la
capa web (los contextos no se importan entre sí).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EstadoSeccion(str, Enum):
    """Disponibilidad real del dato de una sección (mecanismo anti-alucinación)."""

    DISPONIBLE = "disponible"   # el dato existe y se muestra completo
    PARCIAL = "parcial"         # parte del dato existe; el resto queda pendiente
    PENDIENTE = "pendiente"     # aún no hay dato (se incorporará más adelante)
    RESERVADA = "reservada"     # hueco reservado a un tercero (p. ej. el financiero)


@dataclass(frozen=True)
class SeccionInforme:
    """Una sección del informe: título + estado + contenido ya trazado.

    `contenido` solo lleva datos que existen de verdad (dicts/listas/números
    JSON-friendly). `nota_pendiente` explicita qué falta cuando el estado no es
    `DISPONIBLE` (o qué sub-parte falta en un `PARCIAL`).
    """

    clave: str
    titulo: str
    estado: EstadoSeccion
    contenido: dict[str, Any] = field(default_factory=dict)
    nota_pendiente: str | None = None


@dataclass(frozen=True)
class Informe:
    """Documento ensamblado de un proyecto (cabecera + secciones ordenadas)."""

    proyecto_id: str
    proyecto_nombre: str
    referencia_catastral: str | None
    direccion: str | None
    generado_por: str | None
    generado_el: str | None
    escenario_nombre: str | None
    escenario_modo: str | None
    secciones: list[SeccionInforme]
