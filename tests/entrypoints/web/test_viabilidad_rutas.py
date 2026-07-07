"""Tests de las rutas del módulo Viabilidad (§2.9): DCF, precio máximo, sensibilidad, umbrales."""
from __future__ import annotations

from app.nucleo.modelo import Rol

_PAYLOAD_VENTA = {
    "operacion": "venta",
    "intervencion": "obra_nueva",
    "superficie_construida_m2": 1000,
    "precio_eur_m2": 3000,
    "coste_construccion_eur_m2": 1000,
    "pct_costes_indirectos": 0,
    "coste_suelo_eur": 500000,
    "dcf": {
        "supuestos": {"periodo_obra_anios": 2, "tasa_descuento_anual": 0.0, "tir_objetivo": 0.15},
        "financiacion": {},
    },
}


def test_pantalla_viabilidad_ok(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    resp = c.get("/modulos/viabilidad")
    assert resp.status_code == 200


def test_calcular_dcf_devuelve_estudio_y_semaforo(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    resp = c.post("/modulos/viabilidad/calcular-dcf", json=_PAYLOAD_VENTA)
    assert resp.status_code == 200
    data = resp.json()
    assert data["estudio_dcf"]["disponible"] is True
    assert len(data["estudio_dcf"]["escenarios"]) == 3
    assert "global" in data["semaforo"]
    assert "tir" in data["semaforo"]["por_metrica"]


def test_precio_maximo_devuelve_valor(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    payload = {**_PAYLOAD_VENTA, "coste_suelo_eur": 0}
    resp = c.post("/modulos/viabilidad/precio-maximo", json=payload)
    assert resp.status_code == 200
    assert resp.json()["precio_maximo_compra_eur"] is not None


def test_sensibilidad_devuelve_drivers(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    resp = c.post("/modulos/viabilidad/sensibilidad", json=_PAYLOAD_VENTA)
    assert resp.status_code == 200
    data = resp.json()
    assert data["base_tir"] is not None
    assert {d["driver"] for d in data["drivers"]} == {"precio_compra", "capex", "ingreso"}


def test_umbrales_get_y_edicion(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    # Valores sembrados de la tabla PR.
    assert c.get("/modulos/viabilidad/umbrales").json()["tir_min_hotelero"] == 0.15
    # Editar y releer.
    assert c.post("/modulos/viabilidad/umbrales", json={"tir_min_hotelero": 0.20}).status_code == 200
    assert c.get("/modulos/viabilidad/umbrales").json()["tir_min_hotelero"] == 0.20


def test_inversor_no_puede_calcular_dcf_ni_editar_umbrales(cliente_autenticado):
    c = cliente_autenticado(Rol.INVERSOR)
    assert c.post("/modulos/viabilidad/calcular-dcf", json=_PAYLOAD_VENTA).status_code == 403
    assert c.post("/modulos/viabilidad/umbrales", json={"tir_min_hotelero": 0.9}).status_code == 403
    # Pero sí puede consultarlos (VER).
    assert c.get("/modulos/viabilidad/umbrales").status_code == 200


def test_guardar_dcf_sin_proyecto_da_409(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    resp = c.post("/modulos/viabilidad/guardar-dcf", json=_PAYLOAD_VENTA)
    assert resp.status_code == 409


def test_aprobar_sin_proyecto_da_409(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    assert c.post("/modulos/viabilidad/aprobar", json=_PAYLOAD_VENTA).status_code == 409


def test_aprobar_persiste_y_pone_viabilidad_verde(cliente_autenticado, engine_memoria):
    from app.nucleo.modelo import Proyecto
    from app.plataforma.persistencia.proyectos_sqlalchemy import ProyectosSQLAlchemy

    _engine, session_factory = engine_memoria
    with session_factory() as s:
        p = Proyecto(nombre="V aprobable")
        ProyectosSQLAlchemy(s).guardar(p)
        pid = p.id

    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set("puccetti_proyecto", pid)
    resp = c.post("/modulos/viabilidad/aprobar", json=_PAYLOAD_VENTA)
    assert resp.status_code == 200
    assert resp.json()["aprobado"] is True

    # El flujo del proyecto refleja la viabilidad aprobada (verde) y persiste.
    flujo = next(
        pp for pp in c.get("/modulos/informe/datos").json()["proyectos"] if pp["id"] == pid
    )["flujo"]
    assert flujo["viabilidad"]["color"] == "verde"
