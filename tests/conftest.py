"""Fixtures compartidas de la suite de `app/`.

Aísla cada test de la BBDD de producción (`app/data/puccetti.sqlite`) y de la
red. Todo corre contra SQLite en memoria sembrada con los catálogos reales.

Decisión clave: se fija `PUCCETTI_DB_URL=sqlite://` (memoria) ANTES de importar
cualquier módulo de la app, para que el `engine`/`SessionLocal` de módulo —y el
`app = crear_app()` que `aplicacion.py` construye al importarse— jamás toquen el
fichero de producción. Las fixtures construyen, además, su PROPIO engine en
memoria (StaticPool) para que cada test tenga una BBDD limpia y aislada.
"""
from __future__ import annotations

import os

# ── Aislamiento de entorno (antes de importar la app) ───────────────────────
# Throwaway in-memory por defecto: ningún camino accidental escribe en disco.
os.environ.setdefault("PUCCETTI_DB_URL", "sqlite://")
# Credenciales del usuario semilla fijas para los tests. Permite, si hace falta,
# loguearse como el admin sin depender del valor por defecto del seed.
os.environ.setdefault("PUCCETTI_ADMIN_USER", "Arquitecto0")
os.environ.setdefault("PUCCETTI_ADMIN_PASSWORD", "Test-Admin-1234")
# Modo desarrollo: SECRET_KEY se autogenera; cookies no exigen https.
os.environ.setdefault("PUCCETTI_ENV", "dev")

import pytest
from fastapi.testclient import TestClient

from app.contextos.usuarios.dominio import Usuario
from app.contextos.usuarios.seguridad import hashear_contraseña
from app.entrypoints.web.aplicacion import crear_app
from app.nucleo.modelo import Rol
from app.plataforma.persistencia.sqlalchemy_base import crear_db, init_db
from app.plataforma.persistencia.usuarios_sqlalchemy import UsuariosSQLAlchemy

# Contraseña común de los usuarios de prueba creados por rol.
CLAVE_PRUEBA = "Prueba-1234"


# ── BBDD en memoria ─────────────────────────────────────────────────────────
@pytest.fixture
def engine_memoria():
    """Engine SQLite en memoria (StaticPool) con tablas creadas y catálogos
    sembrados. Devuelve `(engine, session_factory)`."""
    engine, session_factory = crear_db("sqlite://")
    init_db(engine=engine, session_factory=session_factory)
    try:
        yield engine, session_factory
    finally:
        engine.dispose()


@pytest.fixture
def session(engine_memoria):
    """Sesión SQLAlchemy sobre el engine en memoria; rollback al terminar.

    Los catálogos ya están comiteados por `init_db`; el rollback solo deshace
    lo que el test deje sin comitear, manteniéndolo aislado.
    """
    _engine, session_factory = engine_memoria
    s = session_factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


# ── App / TestClient ────────────────────────────────────────────────────────
@pytest.fixture
def client(engine_memoria):
    """`TestClient` sobre una app cableada al engine en memoria, sin red.

    Middleware real (login obligatorio + CSRF): sin autenticar, las rutas no
    públicas redirigen a `/login`. Para rutas autenticadas usa
    `cliente_autenticado`.
    """
    engine, session_factory = engine_memoria
    app = crear_app(engine=engine, session_factory=session_factory)
    with TestClient(app) as c:
        yield c


def sembrar_usuario(
    session_factory,
    usuario: str,
    rol: Rol,
    clave: str = CLAVE_PRUEBA,
) -> Usuario:
    """Crea (o deja existente) un usuario con un rol y contraseña conocidos."""
    with session_factory() as s:
        repo = UsuariosSQLAlchemy(s)
        existente = repo.obtener_por_usuario(usuario)
        if existente is not None:
            return existente
        # `guardar` comitea internamente.
        return repo.guardar(
            Usuario(
                usuario=usuario,
                hash_contraseña=hashear_contraseña(clave),
                rol=rol,
            )
        )


@pytest.fixture
def cliente_autenticado(engine_memoria):
    """Factoría: devuelve un `TestClient` autenticado con el rol indicado.

        def test_x(cliente_autenticado):
            c = cliente_autenticado(Rol.FINANCIERO)
            assert c.get("/viabilidad").status_code == 200

    Crea un usuario de ese rol (si no existe) y hace login real (POST /login),
    de modo que la sesión y el rol los fija la autenticación, no un mock.
    """
    engine, session_factory = engine_memoria
    app = crear_app(engine=engine, session_factory=session_factory)

    def _login(rol: Rol = Rol.ARQUITECTO, usuario: str | None = None) -> TestClient:
        nombre = usuario or f"test_{rol.value}"
        sembrar_usuario(session_factory, nombre, rol)
        c = TestClient(app)
        resp = c.post(
            "/login",
            data={"usuario": nombre, "contraseña": CLAVE_PRUEBA},
            follow_redirects=False,
        )
        assert resp.status_code == 303, f"login falló: {resp.status_code} {resp.text[:200]}"
        return c

    return _login


@pytest.fixture(autouse=True)
def _reset_throttle_login():
    """Aísla el throttling del login (estado de proceso) entre tests."""
    from app.entrypoints.web.rutas import autenticacion
    autenticacion._intentos_fallidos.clear()
    yield
    autenticacion._intentos_fallidos.clear()
