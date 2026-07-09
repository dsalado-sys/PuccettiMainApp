"""Catálogo declarativo de módulos visibles en el menú principal.

Esta es la única fuente de verdad de la app para responder "qué tarjetas ve el
usuario en el menú".
"""
from __future__ import annotations

from dataclasses import dataclass

from app.nucleo.modelo import ModuloPuccetti


@dataclass(frozen=True)
class TarjetaModulo:
    id: str                  # coincide con ModuloPuccetti.value y con la matriz de permisos
    titulo: str
    descripcion: str
    ruta: str                # URL relativa dentro de la app
    icono: str               # ID de icono SVG inline (definido en menu.html)


CATALOGO: tuple[TarjetaModulo, ...] = (
    TarjetaModulo(
        id=ModuloPuccetti.PROYECTOS.value,
        titulo="Proyectos",
        descripcion=" ",
        ruta="/proyectos",
        icono="icono-carpeta",
    ),
    TarjetaModulo(
        id=ModuloPuccetti.NORMATIVA_MUNICIPAL.value,
        titulo="Normativa municipal",
        descripcion=" ",
        ruta="/modulos/normativa-municipal",
        icono="icono-documento",
    ),
    TarjetaModulo(
        id=ModuloPuccetti.LOCALIZACION.value,
        titulo="Buscar parcela",
        descripcion=" ",
        ruta="/modulos/localizacion",
        icono="icono-mapa",
    ),
    TarjetaModulo(
        id=ModuloPuccetti.RENDER_CALCULOS.value,
        titulo="Render y cálculos",
        descripcion=" ",
        ruta="/modulos/render-calculos",
        icono="icono-volumen",
    ),
    TarjetaModulo(
        id=ModuloPuccetti.VIABILIDAD.value,
        titulo="Estudio de viabilidad",
        descripcion=" ",
        ruta="/modulos/viabilidad",
        icono="icono-balanza",
    ),
    TarjetaModulo(
        id=ModuloPuccetti.INFORME.value,
        titulo="Informe del activo",
        descripcion=" ",
        ruta="/modulos/informe",
        icono="icono-documento",
    ),
    # Solo visible para el superadmin (la matriz de permisos oculta la tarjeta al
    # resto de roles vía `acceso(...).puede_ver == False`).
    TarjetaModulo(
        id=ModuloPuccetti.GESTION_USUARIOS.value,
        titulo="Gestión de usuarios",
        descripcion=" ",
        ruta="/modulos/gestion-usuarios",
        icono="icono-usuarios",
    ),
)


# Módulos usables SIN proyecto activo. Los demás (render, viabilidad, informe)
# exigen proyecto; el nexo/hub ya se gatea aparte (landing → /proyectos). Única
# fuente de verdad de esta política: la consumen el rail (`plantillas`) y el gate
# central del middleware (`aplicacion`).
MODULOS_SIN_PROYECTO: frozenset[str] = frozenset({
    ModuloPuccetti.PROYECTOS.value,
    ModuloPuccetti.NORMATIVA_MUNICIPAL.value,
    ModuloPuccetti.LOCALIZACION.value,
    ModuloPuccetti.GESTION_USUARIOS.value,
})


def rutas_requieren_proyecto() -> tuple[str, ...]:
    """Prefijos de ruta de los módulos que exigen proyecto activo (gate central)."""
    return tuple(t.ruta for t in CATALOGO if t.id not in MODULOS_SIN_PROYECTO)

'''
    TarjetaModulo(
        id=ModuloPuccetti.MODELOS_PLANOS.value,
        titulo="Modelos sobre planos",
        descripcion="Reconstrucción de estancias desde un PNG de plano; massing 3D animado.",
        ruta="/modulos/modelos-planos",
        icono="icono-plano",
    ),
    '''
