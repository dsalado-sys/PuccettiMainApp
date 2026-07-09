"""Tests de ruta del módulo Informe (flujo de estados).

- `GET /modulos/informe` → pantalla real (ya no el stub «en construcción»).
- `GET /modulos/informe/datos` → proyectos con su `flujo` serializado.
- El errores/avisos por escenario (sembrado vía render) aflora en el flujo.
"""
from __future__ import annotations

from app.contextos.render_calculos.parametros import ParametrosRender, parametros_a_dict
from app.nucleo.modelo import ModuloPuccetti, Proyecto, Rol
from app.plataforma.persistencia.proyectos_sqlalchemy import ProyectosSQLAlchemy

# El módulo Informe exige proyecto activo (gate central); basta la presencia de la
# cookie para pasarlo (las rutas actúan sobre el proyecto por id de la URL).
_COOKIE = ("puccetti_proyecto", "activo")


def _params_vivienda() -> dict:
    d = parametros_a_dict(ParametrosRender())
    d["programa"]["uso"] = "vivienda"
    return d


def _sembrar_proyecto(session_factory, **bloques) -> str:
    with session_factory() as s:
        p = Proyecto(nombre="Proyecto informe")
        for modulo, datos in bloques.items():
            p.fijar_datos(ModuloPuccetti[modulo], datos)
        ProyectosSQLAlchemy(s).guardar(p)
        return p.id


# ─── Pantalla ────────────────────────────────────────────────────────────────

def test_pantalla_informe_ok(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set(*_COOKIE)
    resp = c.get("/modulos/informe")
    assert resp.status_code == 200
    assert 'id="inf-lista"' in resp.text
    # Es la pantalla real, no el stub «Módulo en construcción».
    assert "Módulo en construcción" not in resp.text


# ─── Datos ───────────────────────────────────────────────────────────────────

def test_datos_incluye_flujo(cliente_autenticado, engine_memoria):
    _engine, session_factory = engine_memoria
    _sembrar_proyecto(
        session_factory,
        LOCALIZACION={"referencia_catastral": "1234"},
        RENDER_CALCULOS={"normativa_aplicada": {"nombre": "PGOU", "urbanisticos": {"ocupacion_maxima_pct": 80}}},
    )
    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set(*_COOKIE)
    resp = c.get("/modulos/informe/datos")
    assert resp.status_code == 200
    proyectos = resp.json()["proyectos"]
    assert len(proyectos) == 1
    p = proyectos[0]
    assert set(p) == {"id", "nombre", "referencia_catastral", "direccion", "flujo"}
    flujo = p["flujo"]
    assert set(flujo) == {"parcela", "normativa", "escenarios", "viabilidad", "informe"}
    assert flujo["parcela"]["color"] == "verde"
    assert flujo["normativa"]["color"] == "verde"
    assert flujo["viabilidad"]["color"] == "rojo"      # sin estudio
    assert flujo["informe"]["color"] == "rojo"         # sin aprobar


def test_datos_escenario_con_avisos(cliente_autenticado, engine_memoria):
    _engine, session_factory = engine_memoria
    pid = _sembrar_proyecto(session_factory, LOCALIZACION={"referencia_catastral": "1234"})
    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set("puccetti_proyecto", pid)

    body = {
        "modo": "obra-nueva",
        "activo": "e1",
        "escenarios": [{
            "id": "e1", "nombre": "V", "parametros": _params_vivienda(),
            "resumen": {"alertas_resumen": {"error": 0, "aviso": 2}},
        }],
    }
    assert c.post("/modulos/render-calculos/escenarios", json=body).status_code == 200

    datos = c.get("/modulos/informe/datos").json()
    proyecto = next(p for p in datos["proyectos"] if p["id"] == pid)
    escenarios = proyecto["flujo"]["escenarios"]
    assert len(escenarios) == 1
    assert escenarios[0]["errores_avisos"]["clave"] == "con_avisos"
    assert escenarios[0]["errores_avisos"]["color"] == "amarillo"


# ─── Aprobar el informe de un escenario ──────────────────────────────────────

def _rc_con_escenario(esc_id: str = "e1") -> dict:
    return {"obra-nueva": {"activo": esc_id, "escenarios": [
        {"id": esc_id, "nombre": "V", "parametros": _params_vivienda(),
         "resumen_ultimo_calculo": {}},
    ]}}


def test_aprobar_pone_informe_del_escenario_en_verde(cliente_autenticado, engine_memoria):
    _engine, session_factory = engine_memoria
    pid = _sembrar_proyecto(session_factory, RENDER_CALCULOS=_rc_con_escenario("e1"))
    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set(*_COOKIE)
    # Antes: el informe del escenario está en rojo (sin aprobar).
    antes = c.get("/modulos/informe/datos").json()["proyectos"][0]["flujo"]["escenarios"][0]["informe"]
    assert antes["color"] == "rojo"

    resp = c.post(f"/modulos/informe/{pid}/aprobar?modo=obra-nueva&escenario=e1")
    assert resp.status_code == 200
    assert resp.json()["flujo"]["escenarios"][0]["informe"]["color"] == "verde"

    # Persistido.
    despues = c.get("/modulos/informe/datos").json()["proyectos"][0]["flujo"]["escenarios"][0]["informe"]
    assert despues["color"] == "verde"


def test_aprobar_escenario_inexistente_da_409(cliente_autenticado, engine_memoria):
    _engine, session_factory = engine_memoria
    pid = _sembrar_proyecto(session_factory, RENDER_CALCULOS=_rc_con_escenario("e1"))
    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set(*_COOKIE)
    assert c.post(f"/modulos/informe/{pid}/aprobar?modo=obra-nueva&escenario=NOPE").status_code == 409


def test_aprobar_proyecto_inexistente_da_404(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set(*_COOKIE)
    assert c.post("/modulos/informe/no-existe/aprobar?modo=obra-nueva&escenario=e1").status_code == 404


def test_aprobar_cliente_da_403(cliente_autenticado, engine_memoria):
    _engine, session_factory = engine_memoria
    pid = _sembrar_proyecto(session_factory, RENDER_CALCULOS=_rc_con_escenario("e1"))
    c = cliente_autenticado(Rol.CLIENTE)
    c.cookies.set(*_COOKIE)
    assert c.post(f"/modulos/informe/{pid}/aprobar?modo=obra-nueva&escenario=e1").status_code == 403
