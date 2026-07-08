"""Tests de las rutas de escenarios (pestañas) de Render y cálculos (§2.4–2.7).

Cubre el seam de integración que los unitarios de dominio no tocan: la página
embebe la barra de escenarios y el endpoint `POST /escenarios` persiste la lista y
el activo, que un `GET` posterior refleja. Se siembra un proyecto con bloque de
localización (para `estado == "ok"`) y se activa por cookie.
"""
from __future__ import annotations

from app.contextos.render_calculos.parametros import ParametrosRender, parametros_a_dict
from app.nucleo.modelo import ModuloPuccetti, Proyecto, Rol
from app.plataforma.persistencia.proyectos_sqlalchemy import ProyectosSQLAlchemy


def _params_uso(uso: str) -> dict:
    d = parametros_a_dict(ParametrosRender())
    d["programa"]["uso"] = uso
    return d


def _sembrar_proyecto_con_parcela(session_factory) -> str:
    """Proyecto con un bloque de localización mínimo → `estado == "ok"`."""
    with session_factory() as s:
        p = Proyecto(nombre="Parcela test")
        p.fijar_datos(ModuloPuccetti.LOCALIZACION, {"superficie_m2": 500.0})
        ProyectosSQLAlchemy(s).guardar(p)
        return p.id


def test_pantalla_render_muestra_barra_escenarios(cliente_autenticado, engine_memoria):
    _engine, session_factory = engine_memoria
    pid = _sembrar_proyecto_con_parcela(session_factory)
    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set("puccetti_proyecto", pid)

    resp = c.get("/modulos/render-calculos?modo=obra-nueva")
    assert resp.status_code == 200
    assert 'id="rc-escenarios"' in resp.text
    assert "__RC_ESCENARIOS__" in resp.text
    assert "__RC_ESCENARIO_ACTIVO__" in resp.text


def test_escenarios_roundtrip_persiste_y_refleja_activo(cliente_autenticado, engine_memoria):
    _engine, session_factory = engine_memoria
    pid = _sembrar_proyecto_con_parcela(session_factory)
    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set("puccetti_proyecto", pid)

    body = {
        "modo": "obra-nueva",
        "activo": "e2",
        "escenarios": [
            {"id": "e1", "nombre": "V", "parametros": _params_uso("vivienda"), "resumen": {}},
            {"id": "e2", "nombre": "H", "parametros": _params_uso("hotelero"), "resumen": {}},
        ],
    }
    r = c.post("/modulos/render-calculos/escenarios", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert r.json()["activo"] == "e2"

    # GET posterior → el activo (e2) es el reflejado y ambas pestañas se embeben.
    resp = c.get("/modulos/render-calculos?modo=obra-nueva")
    assert resp.status_code == 200
    assert '"e2"' in resp.text
    # Previsualizar la otra pestaña sin persistir vía ?escenario=.
    resp_e1 = c.get("/modulos/render-calculos?modo=obra-nueva&escenario=e1")
    assert resp_e1.status_code == 200


def test_escenarios_requiere_edicion(cliente_autenticado, engine_memoria):
    _engine, session_factory = engine_memoria
    pid = _sembrar_proyecto_con_parcela(session_factory)
    c = cliente_autenticado(Rol.INVERSOR)   # solo VER
    c.cookies.set("puccetti_proyecto", pid)

    body = {"modo": "obra-nueva", "activo": "e1",
            "escenarios": [{"id": "e1", "parametros": _params_uso("vivienda"), "resumen": {}}]}
    assert c.post("/modulos/render-calculos/escenarios", json=body).status_code == 403


def test_escenarios_lista_vacia_da_422(cliente_autenticado, engine_memoria):
    _engine, session_factory = engine_memoria
    pid = _sembrar_proyecto_con_parcela(session_factory)
    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set("puccetti_proyecto", pid)
    assert c.post("/modulos/render-calculos/escenarios",
                  json={"modo": "obra-nueva", "escenarios": []}).status_code == 422


def test_superficies_vivienda_incluye_util_minimo(cliente_autenticado, engine_memoria):
    _engine, session_factory = engine_memoria
    pid = _sembrar_proyecto_con_parcela(session_factory)
    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set("puccetti_proyecto", pid)
    r = c.get("/modulos/render-calculos/superficies-vivienda")
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    umin = [f for f in filas if f["estancia"] == "_util_minimo"]
    assert {f["n_dormitorios"] for f in umin} == {0, 1, 2, 3, 4, 5}
    assert next(f for f in umin if f["n_dormitorios"] == 2)["min_m2"] == 70.0


def test_superficies_vivienda_editar_util_minimo_persiste(cliente_autenticado, engine_memoria):
    _engine, session_factory = engine_memoria
    pid = _sembrar_proyecto_con_parcela(session_factory)
    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set("puccetti_proyecto", pid)
    body = {"cambios": [{"n_dormitorios": 2, "estancia": "_util_minimo", "valor": 76.0}]}
    r = c.post("/modulos/render-calculos/superficies-vivienda", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["aplicados"] == 1
    filas = c.get("/modulos/render-calculos/superficies-vivienda").json()["filas"]
    umin2 = next(f for f in filas if f["estancia"] == "_util_minimo" and f["n_dormitorios"] == 2)
    assert umin2["min_m2"] == 76.0
