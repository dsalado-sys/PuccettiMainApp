"""Singleton de Jinja2Templates apuntando a /templates de la web."""
from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

RAIZ_WEB = Path(__file__).parent
DIR_ESTATICOS = RAIZ_WEB / "static"
plantillas = Jinja2Templates(directory=str(RAIZ_WEB / "templates"))


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
