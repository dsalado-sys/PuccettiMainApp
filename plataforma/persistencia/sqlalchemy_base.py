"""Engine, Base declarativa y sessionmaker de SQLAlchemy 2.x.

Adapter por defecto de la app. Cambiar a Postgres en producción es solo
ajustar la variable de entorno `PUCCETTI_DB_URL`; ni dominio ni casos de uso
se enteran.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


RAIZ_APP = Path(__file__).resolve().parents[2]
DIR_DATOS = RAIZ_APP / "data"
DIR_DATOS.mkdir(parents=True, exist_ok=True)
BBDD_POR_DEFECTO = DIR_DATOS / "puccetti.sqlite"

DATABASE_URL = os.environ.get(
    "PUCCETTI_DB_URL",
    f"sqlite:///{BBDD_POR_DEFECTO.as_posix()}",
)


class Base(DeclarativeBase):
    """Base declarativa para todos los modelos ORM de la app."""


def _es_url_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _es_sqlite_memoria(url: str) -> bool:
    """True si la URL apunta a una SQLite en memoria (no a un fichero)."""
    return _es_url_sqlite(url) and (":memory:" in url or url in ("sqlite://", "sqlite:///"))


def crear_db(url: str, **engine_kwargs) -> tuple[Engine, sessionmaker]:
    """Factoría: construye `(engine, SessionLocal)` para una URL de BBDD.

    Es el único punto que conoce los detalles del motor. La app la usa con
    `DATABASE_URL` para el adapter por defecto; los tests la usan con
    `sqlite://` (en memoria) para aislarse de `app/data/puccetti.sqlite`.

    Para SQLite en memoria fuerza `StaticPool` + `check_same_thread=False` para
    que todas las conexiones (incluidas las de distintos hilos del TestClient)
    compartan la misma base; de lo contrario cada conexión vería una BBDD vacía.
    """
    es_sqlite = _es_url_sqlite(url)
    kwargs: dict = {
        "future": True,
        "echo": False,
        "connect_args": {"check_same_thread": False} if es_sqlite else {},
    }
    if _es_sqlite_memoria(url):
        kwargs["poolclass"] = StaticPool
    kwargs.update(engine_kwargs)
    engine = create_engine(url, **kwargs)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    return engine, session_factory


# Instancias por defecto (compat): el resto de la app sigue importando estos
# símbolos de módulo. Cambiar a Postgres es solo ajustar `PUCCETTI_DB_URL`.
engine, SessionLocal = crear_db(DATABASE_URL)
_es_sqlite = _es_url_sqlite(DATABASE_URL)


def _registrar_modelos() -> None:
    """Importa los módulos ORM para que se registren en `Base.metadata`."""
    from . import proyectos_sqlalchemy  # noqa: F401
    from . import callejero_sqlalchemy  # noqa: F401
    from . import normativa_municipal_sqlalchemy  # noqa: F401
    from . import catalogo_superficies_sqlalchemy  # noqa: F401
    from . import anexo_i_apartamentos_sqlalchemy  # noqa: F401
    from . import anexo_i_apartamentos_conjuntos_sqlalchemy  # noqa: F401
    from . import anexo_i_hotelero_sqlalchemy  # noqa: F401
    from . import carpetas_normativa_sqlalchemy  # noqa: F401
    from . import carpetas_proyecto_sqlalchemy  # noqa: F401
    from . import usuarios_sqlalchemy  # noqa: F401


def init_db(
    engine: Engine | None = None,
    session_factory: sessionmaker | None = None,
) -> None:
    """Crea las tablas si no existen y siembra catálogos. Idempotente.

    Sin argumentos usa el `engine`/`SessionLocal` de módulo (adapter por
    defecto). Los tests pasan un engine/sessionmaker en memoria para aislarse.
    """
    eng = engine if engine is not None else globals()["engine"]
    sf = session_factory if session_factory is not None else SessionLocal

    _registrar_modelos()
    # `create_all` crea las tablas que falten (cómodo en dev/test). No hay
    # migraciones automáticas: Alembic se retiró del árbol, así que evolucionar
    # el esquema sobre una BBDD existente se hace a mano (ver `app/CLAUDE.md`).
    Base.metadata.create_all(bind=eng)

    from .callejero_seed import sembrar_callejero
    from .seed_normativa import sembrar_todo
    from .seed_usuarios import sembrar_usuarios
    with sf() as session:
        sembrar_callejero(session)
        sembrar_todo(session)
        sembrar_usuarios(session)
