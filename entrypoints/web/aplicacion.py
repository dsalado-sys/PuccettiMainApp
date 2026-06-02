"""Construcción de la FastAPI app (composition root)."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.plataforma.persistencia.sqlalchemy_base import init_db

from .rutas import localizacion, menu, modulos, proyectos, render_calculos, viabilidad

RAIZ_WEB = Path(__file__).parent


def crear_app() -> FastAPI:
    init_db()

    app = FastAPI(
        title="Puccetti — Prefactibilidad inmobiliaria",
        description="Main app: integra localización, viabilidad, render e informe sobre un mismo proyecto.",
        version="0.1.0",
    )

    app.mount(
        "/static",
        StaticFiles(directory=str(RAIZ_WEB / "static")),
        name="static",
    )

    app.include_router(menu.router)
    app.include_router(proyectos.router)
    app.include_router(localizacion.router)
    app.include_router(viabilidad.router)
    app.include_router(render_calculos.router)
    app.include_router(modulos.router)
    return app


app = crear_app()
