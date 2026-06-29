"""Construcción de la FastAPI app (composition root)."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.plataforma.persistencia.sqlalchemy_base import init_db

from .dependencias import COOKIES_SEGURAS, SECRET_KEY, SESION_MAX_AGE_S
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

# Métodos que mutan estado y, por tanto, deben pasar el control CSRF.
METODOS_MUTANTES = frozenset({"POST", "PUT", "PATCH", "DELETE"})

RAIZ_WEB = Path(__file__).parent


def _mismo_origen(request: Request) -> bool:
    """Defensa CSRF (OWASP, apps same-site): acepta la petición solo si su
    origen es el propio host.

    Prefiere `Sec-Fetch-Site` (lo envían los navegadores modernos); si falta,
    compara `Origin` con `Host`. Solo rechaza ante evidencia de origen cruzado;
    sin ninguna cabecera (clientes antiguos, curl) no puede afirmarse que sea
    cruzado y se permite (el control de sesión sigue exigiéndose aparte).
    """
    sec_fetch = request.headers.get("sec-fetch-site")
    if sec_fetch:
        return sec_fetch in ("same-origin", "same-site", "none")
    origin = request.headers.get("origin")
    if not origin:
        return True
    host = request.headers.get("host", "")
    if "://" not in origin:
        return False
    return origin.split("://", 1)[1] == host


def crear_app(engine=None, session_factory=None) -> FastAPI:
    """Composition root.

    Sin argumentos arranca contra el adapter por defecto (`app/data/puccetti.sqlite`).
    Los tests pasan un `engine`/`session_factory` en memoria: `init_db` siembra
    ahí y el sessionmaker de las rutas se sustituye vía `dependency_overrides`,
    de modo que ningún test toca la BBDD de producción.

    §3.8 — ya no hay volcado de superficies a constantes de módulo al arrancar: cada
    cálculo construye su config inmutable desde BBDD (`CalcularLayout._sincronizar_minimos`),
    así que las ediciones se reflejan en vivo sin estado global compartido.
    """
    init_db(engine=engine, session_factory=session_factory)

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
    async def seguridad_http(request: Request, call_next):
        """Puerta única: control CSRF en métodos mutantes + login obligatorio."""
        if request.method in METODOS_MUTANTES and not _mismo_origen(request):
            return PlainTextResponse("Origen no permitido (CSRF).", status_code=403)
        ruta = request.url.path
        es_publica = any(ruta == p or ruta.startswith(p + "/") for p in RUTAS_PUBLICAS)
        if not es_publica and not request.session.get("usuario_id"):
            return RedirectResponse(url="/login", status_code=303)
        return await call_next(request)

    # SessionMiddleware se añade el último para quedar como capa más externa y
    # poblar request.session antes de que corra `exigir_login`.
    app.add_middleware(
        SessionMiddleware,
        secret_key=SECRET_KEY,
        same_site="lax",
        https_only=COOKIES_SEGURAS,
        max_age=SESION_MAX_AGE_S,
    )

    app.include_router(autenticacion.router)
    app.include_router(menu.router)
    app.include_router(proyectos.router)
    app.include_router(localizacion.router)
    app.include_router(viabilidad.router)
    app.include_router(render_calculos.router)
    app.include_router(normativa_municipal.router)
    app.include_router(modulos.router)

    # En modo test, las rutas deben usar el sessionmaker en memoria, no el de
    # módulo. Se sustituye el punto de indirección de `dependencias`.
    if session_factory is not None:
        from .dependencias import obtener_session_factory
        app.dependency_overrides[obtener_session_factory] = lambda: session_factory

    return app


app = crear_app()
