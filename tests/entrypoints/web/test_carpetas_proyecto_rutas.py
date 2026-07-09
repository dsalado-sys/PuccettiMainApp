"""Eliminación de carpetas de proyectos: por defecto la carpeta se borra pero sus
proyectos se conservan (pasan a «Sin carpeta»); con `?con_proyectos=true` se borran
también los proyectos que contiene (borrado en cascada, tras doble confirmación en UI)."""
from __future__ import annotations

from app.nucleo.modelo import Rol


def _crear_carpeta(c, nombre: str) -> int:
    r = c.post("/proyectos/carpetas", json={"nombre": nombre})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _crear_proyecto(c, nombre: str, carpeta_id: int | None) -> str:
    r = c.post("/proyectos", json={"nombre": nombre, "carpeta_id": carpeta_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _ids_proyectos(c) -> set[str]:
    return {p["id"] for p in c.get("/proyectos/datos").json()["proyectos"]}


def _ids_carpetas(c) -> set[int]:
    return {f["id"] for f in c.get("/proyectos/datos").json()["carpetas"]}


def test_borrar_solo_carpeta_conserva_los_proyectos(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    carpeta = _crear_carpeta(c, "Sevilla")
    pid = _crear_proyecto(c, "Residencial", carpeta)

    r = c.request("DELETE", f"/proyectos/carpetas/{carpeta}")
    assert r.status_code == 200, r.text

    # La carpeta ya no existe, pero el proyecto sí (ahora en «Sin carpeta»).
    assert carpeta not in _ids_carpetas(c)
    datos = c.get("/proyectos/datos").json()
    proyecto = next(p for p in datos["proyectos"] if p["id"] == pid)
    assert proyecto["carpeta_id"] is None


def test_borrar_carpeta_con_proyectos_borra_ambos(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    carpeta = _crear_carpeta(c, "Sevilla")
    dentro = _crear_proyecto(c, "Dentro", carpeta)
    fuera = _crear_proyecto(c, "Fuera", None)

    r = c.request("DELETE", f"/proyectos/carpetas/{carpeta}?con_proyectos=true")
    assert r.status_code == 200, r.text

    ids = _ids_proyectos(c)
    assert dentro not in ids          # el de dentro se borra en cascada
    assert fuera in ids               # el de fuera (otra carpeta) no se toca
    assert carpeta not in _ids_carpetas(c)


def test_borrar_carpeta_con_proyectos_limpia_el_activo(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    carpeta = _crear_carpeta(c, "Sevilla")
    pid = _crear_proyecto(c, "Activo", carpeta)
    c.cookies.set("puccetti_proyecto", pid)

    r = c.request("DELETE", f"/proyectos/carpetas/{carpeta}?con_proyectos=true")
    assert r.status_code == 200, r.text
    # El proyecto activo estaba dentro: el servidor emite el borrado de la cookie.
    set_cookie = r.headers.get("set-cookie", "")
    assert "puccetti_proyecto=" in set_cookie and "Max-Age=0" in set_cookie
