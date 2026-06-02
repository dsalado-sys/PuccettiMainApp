"""Arranque de desarrollo de la main app Puccetti.

Funciona invocado de cualquiera de estas formas:

    # Desde la raíz del repo (c:\\Users\\Hublerr\\Documents\\Puccetti):
    py -m app.run

    # Desde dentro de la carpeta app/:
    py run.py

    # O directamente con uvicorn:
    py -m uvicorn app.entrypoints.web.aplicacion:app --reload
"""
from __future__ import annotations

import sys
from pathlib import Path


def _asegurar_paquete_app_en_path() -> None:
    """Permite ejecutar `py run.py` desde dentro de app/ sin instalar el paquete.

    Añade la carpeta padre (la que contiene a `app/`) al sys.path si todavía
    no está. Idempotente.
    """
    raiz_repo = Path(__file__).resolve().parent.parent
    raiz_repo_str = str(raiz_repo)
    if raiz_repo_str not in sys.path:
        sys.path.insert(0, raiz_repo_str)


def main() -> None:
    _asegurar_paquete_app_en_path()
    import uvicorn
    uvicorn.run(
        "app.entrypoints.web.aplicacion:app",
        host="127.0.0.1",
        port=8080,
        reload=True,
    )


if __name__ == "__main__":
    main()
