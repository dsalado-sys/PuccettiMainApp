"""Singleton de Jinja2Templates apuntando a /templates de la web."""
from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.nucleo.modelo import Rol
from app.nucleo.modelo.rol import acceso

from .catalogo_modulos import CATALOGO

RAIZ_WEB = Path(__file__).parent
DIR_ESTATICOS = RAIZ_WEB / "static"
plantillas = Jinja2Templates(directory=str(RAIZ_WEB / "templates"))


def _contexto_shell(request) -> dict:
    """Datos del shell común (rail + cabecera) para CADA página que extiende
    base.html, sin tocar BBDD: el rol vive en la sesión y la navegación se deriva
    del catálogo de módulos filtrado por permisos.

    Se expone como global de Jinja (en lugar de context_processor) para no
    depender de la versión de Starlette y porque `request` siempre está en el
    contexto de plantilla. Devuelve `nav_items` (catálogo + acceso por rol + flag
    `activo` según la ruta actual).
    """
    try:
        slug_rol = request.session.get("rol")
    except (AssertionError, AttributeError):
        slug_rol = None
    try:
        rol = Rol(slug_rol) if slug_rol else Rol.INVERSOR
    except ValueError:
        rol = Rol.INVERSOR

    ruta = request.url.path
    items = []
    for tarjeta in CATALOGO:
        items.append({
            "modulo": tarjeta,
            "acceso": acceso(rol, tarjeta.id),
            "activo": ruta == tarjeta.ruta or ruta.startswith(tarjeta.ruta + "/"),
        })
    return {"nav_items": items}


plantillas.env.globals["contexto_shell"] = _contexto_shell


def _calcular_version_estaticos() -> str:
    """Cache-busting automático: token derivado del mtime más reciente de TODOS
    los estáticos (CSS/JS/...). Cambia solo cuando editas un estático, sin
    bumping manual. Resolución de milisegundos para tolerar varias ediciones
    seguidas dentro del mismo segundo."""
    ultimo = 0.0
    for ruta in DIR_ESTATICOS.rglob("*"):
        if ruta.is_file():
            ultimo = max(ultimo, ruta.stat().st_mtime)
    return str(int(ultimo * 1000))


class _VersionEstaticos:
    """Wrapper que se reevalúa en CADA render: Jinja resuelve
    `{{ estaticos_version }}` vía `str(...)`, así en desarrollo el cambio de un
    CSS/JS se refleja sin reiniciar el servidor ni tocar nada a mano. Mantiene
    las plantillas intactas (siguen usando `?v={{ estaticos_version }}`)."""

    def __str__(self) -> str:
        return _calcular_version_estaticos()


plantillas.env.globals["estaticos_version"] = _VersionEstaticos()
