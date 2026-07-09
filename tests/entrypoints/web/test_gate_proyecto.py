"""Gate por proyecto activo: sin proyecto solo se usan Proyectos, Normativa y
Buscar parcela; el resto (render, viabilidad, informe) redirige a /proyectos, y el
rail oculta los módulos no disponibles."""
from __future__ import annotations

import re

from app.nucleo.modelo import Rol


def _ancla_rail(html: str, ruta: str) -> str:
    """Devuelve la etiqueta <a> del rail para una ruta dada (o '' si no está)."""
    m = re.search(r'<a class="rail-item[^>]*href="' + re.escape(ruta) + r'"[^>]*>', html)
    return m.group(0) if m else ""

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


def test_rail_oculta_modulos_sin_proyecto(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    # Sin proyecto: los módulos que exigen proyecto se OCULTAN del rail (atributo
    # `hidden`), no se muestran como bloqueados.
    sin = c.get("/proyectos").text
    assert "rail-item--bloqueado" not in sin
    ancla_informe = _ancla_rail(sin, "/modulos/informe")
    assert ancla_informe and "hidden" in ancla_informe
    # Con proyecto activo: el módulo vuelve a mostrarse (sin `hidden`).
    c.cookies.set("puccetti_proyecto", "activo")
    con = c.get("/proyectos").text
    ancla_con = _ancla_rail(con, "/modulos/informe")
    assert ancla_con and "hidden" not in ancla_con
