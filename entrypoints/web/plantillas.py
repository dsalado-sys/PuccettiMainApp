"""Singleton de Jinja2Templates apuntando a /templates de la web."""
from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

RAIZ_WEB = Path(__file__).parent
plantillas = Jinja2Templates(directory=str(RAIZ_WEB / "templates"))

# Versión global para cache-busting de estáticos. Subir manualmente al tocar CSS/JS.
ESTATICOS_VERSION = "69"
plantillas.env.globals["estaticos_version"] = ESTATICOS_VERSION
