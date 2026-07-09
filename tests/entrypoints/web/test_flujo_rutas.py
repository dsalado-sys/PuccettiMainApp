"""Tests de ruta del flujo del proyecto (§2.11) y del landing por defecto.

- `GET /` sin proyecto activo redirige a `/proyectos` (primera vista = Proyectos).
- `GET /proyectos/datos` expone el bloque `flujo` por proyecto.
- El resumen de alertas embebido por render (`resumen.alertas_resumen`) sobrevive el
  round-trip de `POST /escenarios` y el flujo lo clasifica en errores/avisos.
"""
from __future__ import annotations

from app.contextos.render_calculos.parametros import ParametrosRender, parametros_a_dict
from app.nucleo.modelo import ModuloPuccetti, Proyecto, Rol
from app.plataforma.persistencia.proyectos_sqlalchemy import ProyectosSQLAlchemy


def _params_vivienda() -> dict:
    d = parametros_a_dict(ParametrosRender())
    d["programa"]["uso"] = "vivienda"
    return d


def _sembrar_proyecto(session_factory, **bloques) -> str:
    with session_factory() as s:
        p = Proyecto(nombre="Proyecto test")
        for modulo, datos in bloques.items():
            p.fijar_datos(ModuloPuccetti[modulo], datos)
        ProyectosSQLAlchemy(s).guardar(p)
        return p.id


# ─── Landing por defecto ─────────────────────────────────────────────────────

def test_raiz_sin_proyecto_redirige_a_proyectos(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    resp = c.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/proyectos"


def test_raiz_con_proyecto_activo_muestra_hub(cliente_autenticado, engine_memoria):
    _engine, session_factory = engine_memoria
    pid = _sembrar_proyecto(session_factory, LOCALIZACION={"referencia_catastral": "1234"})
    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set("puccetti_proyecto", pid)
    resp = c.get("/", follow_redirects=False)
    assert resp.status_code == 200


# ─── Exposición del flujo ────────────────────────────────────────────────────

def test_datos_incluye_flujo(cliente_autenticado, engine_memoria):
    _engine, session_factory = engine_memoria
    _sembrar_proyecto(
        session_factory,
        LOCALIZACION={"referencia_catastral": "1234"},
        RENDER_CALCULOS={"normativa_aplicada": {"nombre": "PGOU", "urbanisticos": {"ocupacion_maxima_pct": 80}}},
    )
    c = cliente_autenticado(Rol.ARQUITECTO)
    datos = c.get("/proyectos/datos").json()
    flujo = datos["proyectos"][0]["flujo"]
    assert flujo["parcela"]["color"] == "verde"
    assert flujo["normativa"]["color"] == "verde"
    assert flujo["viabilidad"]["color"] == "rojo"      # sin estudio
    assert flujo["informe"]["color"] == "rojo"         # sin aprobar


def test_alertas_resumen_sobrevive_roundtrip_escenarios(cliente_autenticado, engine_memoria):
    _engine, session_factory = engine_memoria
    pid = _sembrar_proyecto(session_factory, LOCALIZACION={"referencia_catastral": "1234"})
    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set("puccetti_proyecto", pid)

    body = {
        "modo": "obra-nueva",
        "activo": "e1",
        "escenarios": [{
            "id": "e1", "nombre": "V", "parametros": _params_vivienda(),
            "resumen": {"alertas_resumen": {"error": 1, "aviso": 0}},
        }],
    }
    assert c.post("/modulos/render-calculos/escenarios", json=body).status_code == 200

    # El flujo, leído desde /proyectos/datos, refleja "con errores" para ese escenario.
    datos = c.get("/proyectos/datos").json()
    proyecto = next(p for p in datos["proyectos"] if p["id"] == pid)
    escenarios = proyecto["flujo"]["escenarios"]
    assert len(escenarios) == 1
    assert escenarios[0]["errores_avisos"]["clave"] == "con_errores"
    assert escenarios[0]["errores_avisos"]["color"] == "rojo"
