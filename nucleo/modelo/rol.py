"""Roles y matriz de permisos (§2.11).

El sistema de autenticación real vive en `contextos/usuarios`; este módulo define
el lenguaje y la matriz para que cualquier punto de la app pueda preguntar
"¿este rol puede entrar a este módulo?" sin acoplarse a la UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Rol(str, Enum):
    ARQUITECTO = "arquitecto"
    FINANCIERO = "financiero"
    INVERSOR = "inversor"


class PermisoModulo(str, Enum):
    """Acción autorizada sobre un módulo."""
    VER = "ver"
    EDITAR = "editar"


# Identificadores de módulos navegables desde el menú.
# Coinciden con los slugs declarados en nucleo.modelo.proyecto.ModuloPuccetti.
MODULOS = (
    "localizacion",         # §2.1 — buscar parcela
    "viabilidad",           # §2.3–2.9 — estudio de viabilidad
    "render_calculos",      # §2.4–2.7 — render y cálculos
    "modelos_planos",       # apoyo a §2.4 — visión sobre planos
    "informe",              # §2.10 — informe PDF / DXF
    "proyectos",            # §2.11 — gestión de proyectos
    "normativa_municipal",  # PGOU + carpetas y normativas archivadas
)


# Matriz autoritativa rol → módulo → permisos.
# Borrador inicial pensado para evolución; ajustar cuando se cierren los flujos.
MATRIZ_PERMISOS: dict[Rol, dict[str, frozenset[PermisoModulo]]] = {
    Rol.ARQUITECTO: {
        "localizacion":        frozenset({PermisoModulo.VER, PermisoModulo.EDITAR}),
        "viabilidad":          frozenset({PermisoModulo.VER, PermisoModulo.EDITAR}),
        "render_calculos":     frozenset({PermisoModulo.VER, PermisoModulo.EDITAR}),
        "modelos_planos":      frozenset({PermisoModulo.VER, PermisoModulo.EDITAR}),
        "informe":             frozenset({PermisoModulo.VER, PermisoModulo.EDITAR}),
        "proyectos":           frozenset({PermisoModulo.VER, PermisoModulo.EDITAR}),
        "normativa_municipal": frozenset({PermisoModulo.VER, PermisoModulo.EDITAR}),
    },
    Rol.FINANCIERO: {
        "localizacion":        frozenset({PermisoModulo.VER}),
        "viabilidad":          frozenset({PermisoModulo.VER, PermisoModulo.EDITAR}),
        "render_calculos":     frozenset({PermisoModulo.VER}),
        "modelos_planos":      frozenset(),
        "informe":             frozenset({PermisoModulo.VER, PermisoModulo.EDITAR}),
        "proyectos":           frozenset({PermisoModulo.VER}),
        "normativa_municipal": frozenset({PermisoModulo.VER}),
    },
    Rol.INVERSOR: {
        "localizacion":        frozenset({PermisoModulo.VER}),
        "viabilidad":          frozenset({PermisoModulo.VER}),
        "render_calculos":     frozenset({PermisoModulo.VER}),
        "modelos_planos":      frozenset(),
        "informe":             frozenset({PermisoModulo.VER}),
        "proyectos":           frozenset({PermisoModulo.VER}),
        "normativa_municipal": frozenset({PermisoModulo.VER}),
    },
}


@dataclass(frozen=True)
class AccesoModulo:
    """Resultado de consultar la matriz para una pareja rol × módulo."""
    modulo: str
    puede_ver: bool
    puede_editar: bool


def puede_acceder(rol: Rol, modulo: str, permiso: PermisoModulo = PermisoModulo.VER) -> bool:
    permisos = MATRIZ_PERMISOS.get(rol, {}).get(modulo, frozenset())
    return permiso in permisos


def acceso(rol: Rol, modulo: str) -> AccesoModulo:
    permisos = MATRIZ_PERMISOS.get(rol, {}).get(modulo, frozenset())
    return AccesoModulo(
        modulo=modulo,
        puede_ver=PermisoModulo.VER in permisos,
        puede_editar=PermisoModulo.EDITAR in permisos,
    )
