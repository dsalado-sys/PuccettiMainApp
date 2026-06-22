"""Construcción de la FastAPI app (composition root)."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.plataforma.persistencia.sqlalchemy_base import init_db

from .dependencias import SECRET_KEY
from .rutas import (
    autenticacion,
    localizacion,
    menu,
    modulos,
    normativa_municipal,
    proyectos,
    render_calculos,
    viabilidad,
)

# Prefijos públicos que no requieren sesión iniciada.
RUTAS_PUBLICAS = ("/login", "/logout", "/static")

RAIZ_WEB = Path(__file__).parent


def _volcar_superficies_a_runtime() -> None:
    """Tras seed: BBDD → constantes de los motores del Anexo I (I.1–I.5).

    Permite que las ediciones de superficies mínimas persistidas en BBDD se
    respeten desde el arranque sin pasar el repo por toda la cadena de llamadas.
    En cada cálculo se vuelven a sincronizar (`CalcularLayout._sincronizar_minimos`);
    esto sólo asegura el estado inicial tras un reinicio.
    """
    from app.contextos.render_calculos.geometria import (
        programa,
        programa_apartamentos,
        programa_hotel_apartamento,
        programa_hotelero,
    )
    from app.plataforma.persistencia.anexo_i_apartamentos_sqlalchemy import (
        CatalogoApartamentosSQLAlchemy,
    )
    from app.plataforma.persistencia.anexo_i_hotel_apartamento_sqlalchemy import (
        CatalogoHotelApartamentoSQLAlchemy,
    )
    from app.plataforma.persistencia.anexo_i_hotelero_sqlalchemy import (
        CatalogoHoteleroSQLAlchemy,
    )
    from app.plataforma.persistencia.catalogo_superficies_sqlalchemy import (
        CatalogoSuperficiesSQLAlchemy,
    )
    from app.plataforma.persistencia.sqlalchemy_base import SessionLocal

    with SessionLocal() as session:
        programa.cargar_desde_repo(CatalogoSuperficiesSQLAlchemy(session))
        programa_apartamentos.cargar_desde_repo(CatalogoApartamentosSQLAlchemy(session))
        programa_hotel_apartamento.cargar_desde_repo(CatalogoHotelApartamentoSQLAlchemy(session))
        programa_hotelero.cargar_desde_repo(CatalogoHoteleroSQLAlchemy(session))


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

    @app.middleware("http")
    async def exigir_login(request: Request, call_next):
        """Puerta única: sin sesión iniciada todo redirige a /login."""
        ruta = request.url.path
        es_publica = any(ruta == p or ruta.startswith(p + "/") for p in RUTAS_PUBLICAS)
        if not es_publica and not request.session.get("usuario_id"):
            return RedirectResponse(url="/login", status_code=303)
        return await call_next(request)

    # SessionMiddleware se añade el último para quedar como capa más externa y
    # poblar request.session antes de que corra `exigir_login`.
    app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax")

    app.include_router(autenticacion.router)
    app.include_router(menu.router)
    app.include_router(proyectos.router)
    app.include_router(localizacion.router)
    app.include_router(viabilidad.router)
    app.include_router(render_calculos.router)
    app.include_router(normativa_municipal.router)
    app.include_router(modulos.router)
    return app


app = crear_app()
