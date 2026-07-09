"""Singleton de Jinja2Templates apuntando a /templates de la web."""
from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.nucleo.modelo import Rol
from app.nucleo.modelo.rol import acceso

from .catalogo_modulos import CATALOGO, MODULOS_SIN_PROYECTO
from .dependencias import COOKIE_PROYECTO

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
        rol = Rol(slug_rol) if slug_rol else Rol.CLIENTE
    except ValueError:
        rol = Rol.CLIENTE

    # Sin proyecto activo (cookie ausente) solo son navegables Proyectos, Normativa
    # y Buscar parcela; el resto se oculta del rail (coherente con el gate central).
    hay_proyecto = bool(request.cookies.get(COOKIE_PROYECTO))

    ruta = request.url.path
    items = []
    for tarjeta in CATALOGO:
        requiere_proyecto = tarjeta.id not in MODULOS_SIN_PROYECTO
        items.append({
            "modulo": tarjeta,
            "acceso": acceso(rol, tarjeta.id),
            "activo": ruta == tarjeta.ruta or ruta.startswith(tarjeta.ruta + "/"),
            "requiere_proyecto": requiere_proyecto,
            # Deshabilitado (no oculto) si exige proyecto y no lo hay; el rail lo
            # alterna en vivo por JS al activar/desactivar (ver proyectos.js).
            "disponible": hay_proyecto or not requiere_proyecto,
        })
    return {"nav_items": items}


plantillas.env.globals["contexto_shell"] = _contexto_shell


def _formato_es(valor, decimales: int = 2) -> str:
    """Formatea un número al estilo es-ES (punto de millar, coma decimal) para el
    informe. `None`/no-numérico → «—»/texto tal cual. Filtro Jinja `es_num`."""
    if valor is None:
        return "—"
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    txt = f"{numero:,.{decimales}f}"           # formato en-US: 1,234.56
    # Intercambia separadores → es-ES: millar '.', decimal ','.
    return txt.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


plantillas.env.filters["es_num"] = _formato_es


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
