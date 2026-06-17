"""Engine, Base declarativa y sessionmaker de SQLAlchemy 2.x.

Adapter por defecto de la app. Cambiar a Postgres en producción es solo
ajustar la variable de entorno `PUCCETTI_DB_URL`; ni dominio ni casos de uso
se enteran.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


RAIZ_APP = Path(__file__).resolve().parents[2]
DIR_DATOS = RAIZ_APP / "data"
DIR_DATOS.mkdir(parents=True, exist_ok=True)
BBDD_POR_DEFECTO = DIR_DATOS / "puccetti.sqlite"

DATABASE_URL = os.environ.get(
    "PUCCETTI_DB_URL",
    f"sqlite:///{BBDD_POR_DEFECTO.as_posix()}",
)


_es_sqlite = DATABASE_URL.startswith("sqlite")
engine = create_engine(
    DATABASE_URL,
    future=True,
    echo=False,
    connect_args={"check_same_thread": False} if _es_sqlite else {},
)


class Base(DeclarativeBase):
    """Base declarativa para todos los modelos ORM de la app."""


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def init_db() -> None:
    """Crea las tablas si no existen y siembra catálogos. Idempotente."""
    # Importar los módulos de modelos ORM aquí para que se registren en Base.metadata.
    from . import proyectos_sqlalchemy  # noqa: F401
    from . import callejero_sqlalchemy  # noqa: F401
    from . import normativa_municipal_sqlalchemy  # noqa: F401
    from . import catalogo_superficies_sqlalchemy  # noqa: F401
    from . import anexo_i_apartamentos_sqlalchemy  # noqa: F401
    from . import anexo_i_apartamentos_conjuntos_sqlalchemy  # noqa: F401
    from . import anexo_i_hotel_apartamento_sqlalchemy  # noqa: F401
    from . import anexo_i_hotelero_sqlalchemy  # noqa: F401
    from . import carpetas_normativa_sqlalchemy  # noqa: F401
    Base.metadata.create_all(bind=engine)

    if _es_sqlite:
        _migracion_sqlite_idempotente()

    from .callejero_seed import sembrar_callejero
    from .seed_normativa import sembrar_todo
    with SessionLocal() as session:
        sembrar_callejero(session)
        sembrar_todo(session)


def _migracion_sqlite_idempotente() -> None:
    """Aplica ALTER TABLE para columnas añadidas tras la creación de la BBDD.

    SQLAlchemy `create_all` solo crea tablas que no existen; no altera tablas
    existentes. Esta función añade columnas nuevas a tablas ya creadas, sin
    fallar si la columna ya existe.
    """
    from sqlalchemy import text
    columnas_nuevas: list[tuple[str, str, str]] = [
        # (tabla, nombre_columna, tipo SQL)
        ("anexo_i_vivienda", "area_target_m2", "REAL"),
    ]
    with engine.begin() as conn:
        for tabla, columna, tipo in columnas_nuevas:
            try:
                existe = conn.execute(
                    text(f"SELECT {columna} FROM {tabla} LIMIT 1")
                )
                existe.close()
            except Exception:
                try:
                    conn.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}"))
                except Exception:
                    pass
