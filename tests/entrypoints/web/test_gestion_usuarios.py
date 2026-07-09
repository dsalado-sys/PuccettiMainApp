"""Rutas del módulo de gestión de usuarios (solo superadmin)."""
from __future__ import annotations

from app.nucleo.modelo import Rol
from app.plataforma.persistencia.usuarios_sqlalchemy import UsuariosSQLAlchemy

_RUTA = "/modulos/gestion-usuarios"


def _usuarios(session_factory) -> list:
    with session_factory() as s:
        return UsuariosSQLAlchemy(s).listar()


def _id_de(session_factory, nombre: str) -> str:
    with session_factory() as s:
        u = UsuariosSQLAlchemy(s).obtener_por_usuario(nombre)
        assert u is not None, f"usuario {nombre} no existe"
        return u.id


# ── Acceso ──────────────────────────────────────────────────────────────
def test_superadmin_ve_el_modulo(cliente_autenticado):
    c = cliente_autenticado(Rol.SUPERADMIN)
    resp = c.get(_RUTA)
    assert resp.status_code == 200
    assert "Gestión de usuarios" in resp.text


def test_roles_de_negocio_no_acceden(cliente_autenticado):
    for rol in (Rol.ARQUITECTO, Rol.FINANCIERO, Rol.CLIENTE):
        c = cliente_autenticado(rol)
        assert c.get(_RUTA).status_code == 403, rol


def test_superadmin_landing_redirige_al_modulo(cliente_autenticado):
    c = cliente_autenticado(Rol.SUPERADMIN)
    resp = c.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == _RUTA


def test_tarjeta_oculta_para_arquitecto(cliente_autenticado, engine_memoria):
    _engine, sf = engine_memoria
    # Con proyecto activo, el rail se pinta en las vistas de módulo.
    c = cliente_autenticado(Rol.ARQUITECTO)
    resp = c.get("/modulos/localizacion")
    assert "/modulos/gestion-usuarios" not in resp.text


# ── CRUD ────────────────────────────────────────────────────────────────
def test_crear_y_eliminar_usuario(cliente_autenticado, engine_memoria):
    _engine, sf = engine_memoria
    c = cliente_autenticado(Rol.SUPERADMIN)
    r = c.post(
        f"{_RUTA}/crear",
        data={"usuario": "financiero_x", "contraseña": "clave-larga", "rol_nuevo": "financiero"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert any(u.usuario == "financiero_x" for u in _usuarios(sf))

    uid = _id_de(sf, "financiero_x")
    r = c.post(f"{_RUTA}/{uid}/eliminar", follow_redirects=False)
    assert r.status_code == 303
    assert all(u.usuario != "financiero_x" for u in _usuarios(sf))


def test_cambiar_rol_y_activo(cliente_autenticado, engine_memoria):
    _engine, sf = engine_memoria
    c = cliente_autenticado(Rol.SUPERADMIN)
    c.post(
        f"{_RUTA}/crear",
        data={"usuario": "user_r", "contraseña": "clave-larga", "rol_nuevo": "cliente"},
        follow_redirects=False,
    )
    uid = _id_de(sf, "user_r")

    c.post(f"{_RUTA}/{uid}/rol", data={"rol_nuevo": "arquitecto"}, follow_redirects=False)
    with sf() as s:
        assert UsuariosSQLAlchemy(s).obtener_por_id(uid).rol is Rol.ARQUITECTO

    c.post(f"{_RUTA}/{uid}/activo", data={"activo": "0"}, follow_redirects=False)
    with sf() as s:
        assert UsuariosSQLAlchemy(s).obtener_por_id(uid).activo is False


def test_no_puede_crear_superadmin(cliente_autenticado, engine_memoria):
    _engine, sf = engine_memoria
    c = cliente_autenticado(Rol.SUPERADMIN)
    r = c.post(
        f"{_RUTA}/crear",
        data={"usuario": "otro_super", "contraseña": "clave-larga", "rol_nuevo": "superadmin"},
        follow_redirects=False,
    )
    assert r.status_code == 303  # redirige con flash de error
    assert all(u.usuario != "otro_super" for u in _usuarios(sf))


def test_superadmin_no_se_puede_eliminar(cliente_autenticado, engine_memoria):
    _engine, sf = engine_memoria
    c = cliente_autenticado(Rol.SUPERADMIN)
    # La cuenta superadmin sembrada por init_db.
    uid = _id_de(sf, "superadmin")
    c.post(f"{_RUTA}/{uid}/eliminar", follow_redirects=False)
    assert any(u.usuario == "superadmin" for u in _usuarios(sf))
