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
        id=ModuloPuccetti.LOCALIZACION.value,
        titulo="Buscar parcela",
        descripcion="Localización por RC, dirección o click en el mapa. Catastro + PNOA + ficha del activo.",
        ruta="/modulos/localizacion",
        icono="icono-mapa",
    ),
    TarjetaModulo(
        id=ModuloPuccetti.VIABILIDAD.value,
        titulo="Estudio de viabilidad",
        descripcion="Urbanismo, programa por uso, viabilidad económica y optimizador.",
        ruta="/modulos/viabilidad",
        icono="icono-balanza",
    ),
    TarjetaModulo(
        id=ModuloPuccetti.RENDER_CALCULOS.value,
        titulo="Render y cálculos",
        descripcion="Envolvente paramétrica, distribución plurifamiliar y tabla de superficies.",
        ruta="/modulos/render-calculos",
        icono="icono-volumen",
    ),
    TarjetaModulo(
        id=ModuloPuccetti.INFORME.value,
        titulo="Informe del activo",
        descripcion="Generación de PDF para el inversor y exportación DXF.",
        ruta="/modulos/informe",
        icono="icono-documento",
    ),
    TarjetaModulo(
        id=ModuloPuccetti.NORMATIVA_MUNICIPAL.value,
        titulo="Normativa municipal",
        descripcion="Carpetas con normativas urbanísticas archivadas (PGOU). Crear, editar y consultar.",
        ruta="/modulos/normativa-municipal",
        icono="icono-documento",
    ),
    TarjetaModulo(
        id=ModuloPuccetti.PROYECTOS.value,
        titulo="Proyectos",
        descripcion="Crear, abrir, archivar proyectos. Estado compartido entre módulos.",
        ruta="/proyectos",
        icono="icono-carpeta",
    ),
)

'''
    TarjetaModulo(
        id=ModuloPuccetti.MODELOS_PLANOS.value,
        titulo="Modelos sobre planos",
        descripcion="Reconstrucción de estancias desde un PNG de plano; massing 3D animado.",
        ruta="/modulos/modelos-planos",
        icono="icono-plano",
    ),
    '''
