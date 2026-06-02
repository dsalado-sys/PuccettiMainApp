"""Lenguaje ubicuo de Puccetti. Todo módulo debe hablar este vocabulario."""
from .proyecto import Proyecto, EstadoProyecto, ModuloPuccetti
from .rol import Rol, PermisoModulo, MATRIZ_PERMISOS, puede_acceder

__all__ = [
    "Proyecto",
    "EstadoProyecto",
    "ModuloPuccetti",
    "Rol",
    "PermisoModulo",
    "MATRIZ_PERMISOS",
    "puede_acceder",
]
