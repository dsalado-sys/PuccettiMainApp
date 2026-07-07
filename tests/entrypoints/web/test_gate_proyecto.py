"""Gate por proyecto activo: sin proyecto solo se usan Proyectos, Normativa y
Buscar parcela; el resto (render, viabilidad, informe) redirige a /proyectos, y el
rail oculta los módulos no disponibles."""
from __future__ import annotations

from app.nucleo.modelo import Rol

_BLOQUEADOS = ("/modulos/render-calculos", "/modulos/viabilidad", "/modulos/informe")
_PERMITIDOS = ("/proyectos", "/modulos/normativa-municipal", "/modulos/localizacion")


def test_sin_proyecto_los_modulos_restringidos_redirigen(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    for ruta in _BLOQUEADOS:
        r = c.get(ruta, follow_redirects=False)
        assert r.status_code == 303, ruta
        assert r.headers["location"] == "/proyectos", ruta


def test_sin_proyecto_los_modulos_permitidos_responden(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    for ruta in _PERMITIDOS:
        assert c.get(ruta, follow_redirects=False).status_code == 200, ruta


def test_con_proyecto_el_modulo_restringido_es_accesible(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set("puccetti_proyecto", "activo")
    r = c.get("/modulos/viabilidad", follow_redirects=False)
    assert r.status_code == 200


def test_rail_deshabilita_modulos_sin_proyecto(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    # Sin proyecto: los módulos restringidos SIGUEN en el rail pero deshabilitados.
    sin = c.get("/proyectos").text
    assert "/modulos/viabilidad" in sin
    assert "rail-item--bloqueado" in sin
    assert 'data-requiere-proyecto="1"' in sin
    # Con proyecto activo: ninguno queda bloqueado.
    c.cookies.set("puccetti_proyecto", "activo")
    con = c.get("/proyectos").text
    assert "rail-item--bloqueado" not in con
