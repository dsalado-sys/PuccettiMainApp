"""Tests del contenedor de escenarios (pestañas) de render_calculos.

Cada modo guarda una LISTA de escenarios {id, nombre, parametros, resumen} + cuál
está activo. Se cubren: migración perezosa del formato antiguo (un solo bloque por
modo) y del plano legado, lectura del escenario activo (con override para
previsualizar otra pestaña) y persistencia conservando los demás modos.
"""
from __future__ import annotations

from app.contextos.render_calculos.casos_uso import (
    GuardarEscenariosRender,
    contenedor_escenarios_proyecto,
    parametros_desde_proyecto,
)
from app.contextos.render_calculos.dominio import UsoEdificio
from app.contextos.render_calculos.parametros import ParametrosRender, parametros_a_dict
from app.nucleo.modelo import ModuloPuccetti, Proyecto
from app.plataforma.persistencia.proyectos_en_memoria import ProyectosEnMemoria


def _params_uso(uso: str) -> dict:
    """Parámetros por defecto con el `uso` deseado (para distinguir escenarios)."""
    d = parametros_a_dict(ParametrosRender())
    d["programa"]["uso"] = uso
    return d


def _proyecto_con_render(datos_render: dict) -> Proyecto:
    p = Proyecto(nombre="test")
    p.fijar_datos(ModuloPuccetti.RENDER_CALCULOS, datos_render)
    return p


# ── Sin datos ───────────────────────────────────────────────────────────────
def test_sin_datos_no_hay_contenedor():
    p = Proyecto(nombre="vacio")
    assert contenedor_escenarios_proyecto(p, "obra-nueva") is None
    # Sin escenarios → parametros_desde_proyecto cae a defaults.
    assert isinstance(parametros_desde_proyecto(p, "obra-nueva"), ParametrosRender)


# ── Migración del formato antiguo (un solo bloque por modo) ───────────────────
def test_migracion_formato_antiguo_a_un_escenario():
    antiguo = {"obra-nueva": {
        "parametros": _params_uso("hotelero"),
        "resumen_ultimo_calculo": {"n": 3},
        "timestamp": "2026-01-01T00:00:00+00:00",
    }}
    p = _proyecto_con_render(antiguo)
    cont = contenedor_escenarios_proyecto(p, "obra-nueva")
    assert cont is not None
    assert cont["activo"] == "e1"
    assert [e["id"] for e in cont["escenarios"]] == ["e1"]
    # El escenario activo conserva los parámetros del bloque antiguo.
    assert parametros_desde_proyecto(p, "obra-nueva").programa.uso == UsoEdificio.HOTELERO


def test_migracion_legado_plano_solo_con_heredar():
    # Formato plano legado (parametros en la raíz de datos_render): solo el modo
    # por defecto puede heredarlo.
    plano = {"parametros": _params_uso("apartamentos_turisticos"), "resumen_ultimo_calculo": {}, "timestamp": ""}
    p = _proyecto_con_render(plano)
    assert contenedor_escenarios_proyecto(p, "obra-nueva", heredar_legado=True) is not None
    assert contenedor_escenarios_proyecto(p, "obra-nueva", heredar_legado=False) is None


# ── Formato nuevo: varios escenarios ─────────────────────────────────────────
def test_lee_escenario_activo_y_override():
    nuevo = {"obra-nueva": {
        "escenarios": [
            {"id": "a", "nombre": "Vivienda", "parametros": _params_uso("vivienda")},
            {"id": "b", "nombre": "Hotel", "parametros": _params_uso("hotelero")},
        ],
        "activo": "b",
    }}
    p = _proyecto_con_render(nuevo)
    assert contenedor_escenarios_proyecto(p, "obra-nueva")["activo"] == "b"
    # Activo = b → hotelero.
    assert parametros_desde_proyecto(p, "obra-nueva").programa.uso == UsoEdificio.HOTELERO
    # Override explícito a "a" → vivienda (previsualización sin persistir).
    assert parametros_desde_proyecto(p, "obra-nueva", escenario_id="a").programa.uso == UsoEdificio.VIVIENDA
    # Override inexistente → cae al activo (b).
    assert parametros_desde_proyecto(p, "obra-nueva", escenario_id="zzz").programa.uso == UsoEdificio.HOTELERO


def test_activo_invalido_cae_al_primero():
    nuevo = {"obra-nueva": {
        "escenarios": [{"id": "a", "parametros": _params_uso("vivienda")}],
        "activo": "no-existe",
    }}
    p = _proyecto_con_render(nuevo)
    assert contenedor_escenarios_proyecto(p, "obra-nueva")["activo"] == "a"


def test_escenarios_vacio_no_es_contenedor():
    # Lista de escenarios vacía o sin ids válidos → sin contenedor.
    p = _proyecto_con_render({"obra-nueva": {"escenarios": [], "activo": None}})
    assert contenedor_escenarios_proyecto(p, "obra-nueva") is None


# ── Persistencia ─────────────────────────────────────────────────────────────
def test_guardar_conserva_otros_modos_y_normativa():
    p = _proyecto_con_render({
        "rehabilitacion": {"escenarios": [{"id": "x", "parametros": _params_uso("vivienda")}], "activo": "x"},
        "normativa_aplicada": {"id": 1, "nombre": "PGOU", "urbanisticos": {}},
    })
    repo = ProyectosEnMemoria()
    escenarios = [
        {"id": "e1", "nombre": "V", "parametros": _params_uso("vivienda"), "resumen_ultimo_calculo": {}, "timestamp": "t"},
        {"id": "e2", "nombre": "H", "parametros": _params_uso("hotelero"), "resumen_ultimo_calculo": {}, "timestamp": "t"},
    ]
    GuardarEscenariosRender(repo_proyectos=repo).ejecutar(p, escenarios, "e2", modo_key="obra-nueva")

    datos = p.datos_por_modulo[ModuloPuccetti.RENDER_CALCULOS.value]
    # El modo obra-nueva ahora tiene el contenedor; rehabilitacion y normativa intactos.
    assert datos["obra-nueva"]["activo"] == "e2"
    assert [e["id"] for e in datos["obra-nueva"]["escenarios"]] == ["e1", "e2"]
    assert datos["rehabilitacion"]["activo"] == "x"
    assert datos["normativa_aplicada"]["nombre"] == "PGOU"
    # Y la lectura del activo del modo guardado devuelve hotelero.
    assert parametros_desde_proyecto(p, "obra-nueva").programa.uso == UsoEdificio.HOTELERO
