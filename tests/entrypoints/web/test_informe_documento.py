"""Tests de ruta del documento del informe (§2.8): GET /modulos/informe/{id}/documento.

Integración con SQLite en memoria sembrada (sin red / sin Catastro en vivo). Un
test cubre el caso sin escenario (placeholders explícitos anti-alucinación) y otro
el caso con escenario calculado (planimetría SVG + tabla de superficies).
"""
from __future__ import annotations

from app.contextos.render_calculos.parametros import ParametrosRender, parametros_a_dict
from app.nucleo.modelo import ModuloPuccetti, Proyecto, Rol
from app.plataforma.persistencia.proyectos_sqlalchemy import ProyectosSQLAlchemy

# El documento vive bajo /modulos/informe, que exige proyecto activo (gate central);
# basta la presencia de la cookie (el documento actúa sobre el proyecto por id de la URL).
_COOKIE = ("puccetti_proyecto", "activo")

# Parcela WGS84 cuadrada de ~40 m cerca de Sevilla: suficiente para la envolvente.
_CONTORNO = [
    [-5.99000, 37.38000],
    [-5.98955, 37.38000],
    [-5.98955, 37.38036],
    [-5.99000, 37.38036],
]
_LOC = {
    "referencia_catastral": "1234567AB1234C0001DE",
    "direccion": "Calle de Prueba 1",
    "municipio": "Sevilla",
    "provincia": "Sevilla",
    "superficie_m2": 1600.0,
    "centroide_lonlat": [-5.989775, 37.38018],
    "contorno_wgs84": _CONTORNO,
    "contorno_simplificado_wgs84": _CONTORNO,
    "lados": [],
}
_NORMATIVA = {"nombre": "PGOU Sevilla", "urbanisticos": {
    "coeficiente_edificabilidad": 2.5, "n_plantas_max": 3,
    "ocupacion_maxima_pct": 100.0, "retranqueo_fachada_m": 0.0,
    "usos_permitidos": ["residencial"],
}}


def _params_vivienda() -> dict:
    d = parametros_a_dict(ParametrosRender())
    d["programa"]["uso"] = "vivienda"
    return d


def _sembrar(session_factory, *, rc=None, direccion=None, **bloques) -> str:
    with session_factory() as s:
        p = Proyecto(nombre="Proyecto informe doc", referencia_catastral=rc, direccion=direccion)
        for modulo, datos in bloques.items():
            p.fijar_datos(ModuloPuccetti[modulo], datos)
        ProyectosSQLAlchemy(s).guardar(p)
        return p.id


def test_documento_sin_escenario_muestra_placeholders(cliente_autenticado, engine_memoria):
    _engine, sf = engine_memoria
    pid = _sembrar(sf, rc="1234567AB1234C0001DE", direccion="Calle de Prueba 1",
                   LOCALIZACION=_LOC, RENDER_CALCULOS={"normativa_aplicada": _NORMATIVA})
    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set(*_COOKIE)
    resp = c.get(f"/modulos/informe/{pid}/documento")
    assert resp.status_code == 200
    t = resp.text

    # Cabecera + las 7 secciones de la estructura mínima (§2.8).
    assert "Informe de prefactibilidad" in t
    for titulo in ["Ficha del activo", "Resumen de parámetros urbanísticos",
                   "Planimetría de la propuesta", "Perspectiva volumétrica",
                   "Tabla de superficies", "Alertas y condicionantes", "Análisis de rentabilidad"]:
        assert titulo in t, titulo

    # Datos DISPONIBLES: RC (ficha) + normativa aplicada.
    assert "1234567AB1234C0001DE" in t
    assert "PGOU Sevilla" in t

    # Sin escenario → placeholders EXPLÍCITOS (no datos inventados).
    assert "Sin escenario de render calculado" in t
    assert "perspectiva volumétrica 3D aún no está disponible" in t
    assert "reservada para que los asociados financieros" in t


def test_documento_con_escenario_muestra_tablas_y_plano(cliente_autenticado, engine_memoria):
    _engine, sf = engine_memoria
    pid = _sembrar(sf, rc="1234567AB1234C0001DE", direccion="Calle de Prueba 1",
                   LOCALIZACION=_LOC, RENDER_CALCULOS={"normativa_aplicada": _NORMATIVA})
    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set("puccetti_proyecto", pid)

    body = {"modo": "obra-nueva", "activo": "e1", "escenarios": [{
        "id": "e1", "nombre": "Vivienda base", "parametros": _params_vivienda(),
        "resumen": {"alertas_resumen": {"error": 0, "aviso": 0}},
    }]}
    assert c.post("/modulos/render-calculos/escenarios", json=body).status_code == 200

    resp = c.get(f"/modulos/informe/{pid}/documento")
    assert resp.status_code == 200
    t = resp.text

    # Planimetría: al menos un SVG incrustado (server-side).
    assert "<svg" in t and "plano-svg" in t
    # Tabla de superficies por planta.
    assert "Por planta" in t
    # El escenario activo aparece en la cabecera.
    assert "Vivienda base" in t


def test_documento_de_un_escenario_concreto(cliente_autenticado, engine_memoria):
    _engine, sf = engine_memoria
    pid = _sembrar(sf, rc="1234567AB1234C0001DE", direccion="Calle de Prueba 1",
                   LOCALIZACION=_LOC, RENDER_CALCULOS={"normativa_aplicada": _NORMATIVA})
    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set("puccetti_proyecto", pid)
    params = _params_vivienda()
    body = {"modo": "obra-nueva", "activo": "e1", "escenarios": [
        {"id": "e1", "nombre": "Escenario Uno", "parametros": params, "resumen": {"alertas_resumen": {}}},
        {"id": "e2", "nombre": "Escenario Dos", "parametros": params, "resumen": {"alertas_resumen": {}}},
    ]}
    assert c.post("/modulos/render-calculos/escenarios", json=body).status_code == 200

    # Se pide explícitamente el escenario e2 → su nombre sale en la cabecera.
    resp = c.get(f"/modulos/informe/{pid}/documento?modo=obra-nueva&escenario=e2")
    assert resp.status_code == 200
    assert "Escenario Dos" in resp.text


def test_documento_proyecto_inexistente_da_404(cliente_autenticado):
    c = cliente_autenticado(Rol.ARQUITECTO)
    c.cookies.set(*_COOKIE)
    assert c.get("/modulos/informe/no-existe/documento").status_code == 404


def test_documento_cliente_puede_ver(cliente_autenticado, engine_memoria):
    _engine, sf = engine_memoria
    pid = _sembrar(sf, rc="RC-INV", LOCALIZACION=_LOC)
    c = cliente_autenticado(Rol.CLIENTE)  # CLIENTE tiene VER en informe
    c.cookies.set(*_COOKIE)
    assert c.get(f"/modulos/informe/{pid}/documento").status_code == 200
