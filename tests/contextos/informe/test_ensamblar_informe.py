"""Tests del ensamblador del informe (§2.8) — caso de uso puro.

Verifica el mecanismo anti-alucinación: sin dato → sección `PENDIENTE`/`RESERVADA`
con nota explícita; con dato → `DISPONIBLE`/`PARCIAL` proyectando lo trazado, sin
inventar nada (p. ej. la imagen aérea siempre es None).
"""
from __future__ import annotations

from app.contextos.informe.casos_uso import EnsamblarInforme, informe_a_dict

_META = {
    "id": "p1", "nombre": "Demo", "referencia_catastral": None, "direccion": None,
    "generado_por": "u", "generado_el": "07/07/2026",
}


def _ensamblar(**kw) -> dict:
    base = dict(
        proyecto_meta=_META, localizacion=None, normativa=None,
        resultado_layout=None, escenario_meta=None, viabilidad=None,
    )
    base.update(kw)
    return informe_a_dict(EnsamblarInforme().ejecutar(**base))


def _sec(d: dict, clave: str) -> dict:
    return next(s for s in d["secciones"] if s["clave"] == clave)


def test_orden_y_todo_vacio_pendiente_con_nota():
    d = _ensamblar()
    # Orden = estructura mínima del requisito (§2.8).
    assert [s["clave"] for s in d["secciones"]] == [
        "ficha", "urbanismo", "planimetria", "volumetria", "superficies", "alertas", "financiera",
    ]
    for s in d["secciones"]:
        esperado = "reservada" if s["clave"] == "financiera" else "pendiente"
        assert s["estado"] == esperado, s
        # Anti-alucinación: nunca un hueco mudo; siempre nota explícita.
        assert s["nota_pendiente"], f"{s['clave']} sin nota explícita"


def test_ficha_disponible_no_inventa_imagen_aerea():
    d = _ensamblar(localizacion={"referencia_catastral": "RC", "direccion": "Calle", "municipio": "Sevilla"})
    f = _sec(d, "ficha")
    assert f["estado"] == "disponible"
    assert f["contenido"]["referencia_catastral"] == "RC"
    assert f["contenido"]["imagen_aerea"] is None  # no persistida → nunca inventada
    assert f["nota_pendiente"]  # explica que la ortofoto queda pendiente


def test_urbanismo_disponible_lista_parametros():
    d = _ensamblar(normativa={"nombre": "PGOU", "urbanisticos": {
        "coeficiente_edificabilidad": 2.5, "n_plantas_max": 4, "usos_permitidos": ["residencial"],
    }})
    u = _sec(d, "urbanismo")
    assert u["estado"] == "disponible"
    etiquetas = [f["etiqueta"] for f in u["contenido"]["parametros"]]
    assert "Edificabilidad" in etiquetas and "Nº máximo de plantas" in etiquetas
    assert "Usos permitidos" in etiquetas


def test_urbanismo_sin_snapshot_pendiente():
    assert _sec(_ensamblar(normativa={"nombre": "PGOU"}), "urbanismo")["estado"] == "pendiente"


def test_superficies_planimetria_y_alertas_desde_layout():
    layout = {
        "tabla_planta": [{"planta": "PB", "tipo": "regular", "viviendas": 1,
                          "construida_m2": 100.0, "util_viviendas_m2": 80.0, "circulacion_m2": 5.0}],
        "tabla_unidad": [],
        "capacidad": {"construida_total_m2": 100.0, "util_total_m2": 80.0, "muros_total_m2": 8.0,
                      "circulacion_total_m2": 5.0, "nucleo_total_m2": 3.0, "patio_total_m2": 0.0},
        "alertas": [],
        "parcela": {"poligono": [[0, 0], [10, 0], [10, 10], [0, 10]]},
        "envolvente": {"plantas": [{"nombre": "PB", "tipo": "regular", "construida_m2": 100.0,
                                    "util_m2": 80.0, "footprint": [[1, 1], [9, 1], [9, 9], [1, 9]], "patios": []}]},
    }
    d = _ensamblar(resultado_layout=layout)
    assert _sec(d, "superficies")["estado"] == "disponible"
    plan = _sec(d, "planimetria")
    assert plan["estado"] == "parcial"
    assert plan["contenido"]["plantas"][0]["svg"].startswith("<svg")
    # Lista de alertas vacía = escenario calculado sin incidencias (PARCIAL, no PENDIENTE).
    assert _sec(d, "alertas")["estado"] == "parcial"


def test_sin_layout_planimetria_y_superficies_pendientes():
    d = _ensamblar()
    assert _sec(d, "planimetria")["estado"] == "pendiente"
    assert _sec(d, "superficies")["estado"] == "pendiente"
    assert _sec(d, "volumetria")["estado"] == "pendiente"  # 3D nunca disponible aún


def test_financiera_reservada_reporta_estado_del_estudio():
    assert _sec(_ensamblar(), "financiera")["contenido"]["estado_estudio"] == "sin_estudio"
    assert _sec(_ensamblar(viabilidad={"precio": 1}), "financiera")["contenido"]["estado_estudio"] == "sin_aprobar"
    assert _sec(_ensamblar(viabilidad={"aprobado": True}), "financiera")["contenido"]["estado_estudio"] == "aprobado"
    # Siempre reservada, nunca rellena cifras financieras por su cuenta.
    assert _sec(_ensamblar(viabilidad={"aprobado": True}), "financiera")["estado"] == "reservada"
