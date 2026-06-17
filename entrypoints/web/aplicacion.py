"""Construcción de la FastAPI app (composition root)."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.plataforma.persistencia.sqlalchemy_base import init_db

from .rutas import (
    localizacion,
    menu,
    modulos,
    normativa_municipal,
    proyectos,
    render_calculos,
    viabilidad,
)

RAIZ_WEB = Path(__file__).parent


def _volcar_superficies_a_runtime() -> None:
    """Tras seed: BBDD → constantes de `geometria.programa`.

    Permite que las ediciones del Anexo I.5 persistidas se respeten sin
    pasar el repo por toda la cadena de llamadas.
    """
    from app.contextos.render_calculos.geometria import programa
    from app.plataforma.persistencia.catalogo_superficies_sqlalchemy import (
        CatalogoSuperficiesSQLAlchemy,
    )
    from app.plataforma.persistencia.sqlalchemy_base import SessionLocal

    with SessionLocal() as session:
        programa.cargar_desde_repo(CatalogoSuperficiesSQLAlchemy(session))


def crear_app() -> FastAPI:
    init_db()
    _volcar_superficies_a_runtime()

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
    app.include_router(normativa_municipal.router)
    app.include_router(modulos.router)
    return app


app = crear_app()
