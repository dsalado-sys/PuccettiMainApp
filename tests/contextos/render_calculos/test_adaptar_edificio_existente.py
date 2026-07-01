"""Tests de `adaptar_params_a_edificio_existente` (modo Rehabilitación).

Arranque encajado al edificio catastral existente. Foco: detección del ático en
dos pasos. (1) Por código `AT` directo del Catastro (fiable). (2) Si no consta,
por nº de plantas: si las plantas sobre rasante (X) superan a las documentadas
(R), la planta extra no referenciada se asume ático (calculado). El motor lo
genera ENCIMA de `n_plantas_max`, así que con ático las regulares pasan a X-1 y el
total vuelve a X. `aviso_atico_catastral` señala el caso calculado (amarillo) y el
indeterminado sin datos (naranja). Sin tocar Catastro: la localización se inyecta
ya persistida.
"""
from __future__ import annotations

from app.contextos.render_calculos.casos_uso import (
    adaptar_params_a_edificio_existente,
    aviso_atico_catastral,
)
from app.contextos.render_calculos.parametros import ParametrosRender
from app.nucleo.modelo import ModuloPuccetti, Proyecto


def _proyecto_con(plantas_sobre_rasante, plantas_loc, *, plantas_bajo_rasante=None):
    """Proyecto con datos de localización: X plantas y una subreferencia por
    cada cadena de `plantas_loc` (formato real del adapter "Es 1 · Pl 03 · Pt B")."""
    proyecto = Proyecto(nombre="test")
    loc = {
        "plantas_sobre_rasante": plantas_sobre_rasante,
        "subreferencias": [
            {"localizacion": s, "rc": f"rc{i}", "uso": "Vivienda",
             "superficie_construida_m2": 80.0}
            for i, s in enumerate(plantas_loc)
        ],
    }
    if plantas_bajo_rasante is not None:
        loc["plantas_bajo_rasante"] = plantas_bajo_rasante
    proyecto.fijar_datos(ModuloPuccetti.LOCALIZACION, loc)
    return proyecto


def test_referencia_en_atico_marca_atico():
    """X=5 con una subreferencia en planta `AT` → ático leído del Catastro (fiable)."""
    proyecto = _proyecto_con(5, [
        "Es 1 · Pl 00 · Pt A",
        "Es 1 · Pl 01 · Pt A",
        "Es 1 · Pl 02 · Pt A",
        "Es 1 · Pl 03 · Pt A",
        "Es 1 · Pl AT · Pt A",
    ])
    params = ParametrosRender()
    adaptar_params_a_edificio_existente(params, proyecto)

    assert params.urbanisticos.tiene_atico is True
    assert params.urbanisticos.n_plantas_max == 4   # X-1 regulares + 1 ático = 5
    assert aviso_atico_catastral(proyecto) is None  # dato fiable → sin aviso


def test_documentado_sin_atico_no_marca_ni_avisa():
    """X=5 = R (todas las plantas documentadas, sin `AT`) → sin ático y sin aviso."""
    proyecto = _proyecto_con(5, [
        "Es 1 · Pl 00 · Pt A",
        "Es 1 · Pl 01 · Pt A",
        "Es 1 · Pl 02 · Pt A",
        "Es 1 · Pl 03 · Pt A",
        "Es 1 · Pl 04 · Pt A",
    ])
    params = ParametrosRender()
    adaptar_params_a_edificio_existente(params, proyecto)

    assert params.urbanisticos.tiene_atico is False
    assert params.urbanisticos.n_plantas_max == 5
    assert aviso_atico_catastral(proyecto) is None


def test_atico_calculado_por_planta_extra():
    """Sin `AT` y X=4 > R=3 (una planta sobre rasante no documentada): se asume
    ático y se avisa en amarillo para verificación."""
    proyecto = _proyecto_con(4, [
        "Es 1 · Pl 00 · Pt A",
        "Es 1 · Pl 01 · Pt A",
        "Es 1 · Pl 02 · Pt A",
    ])
    params = ParametrosRender()
    adaptar_params_a_edificio_existente(params, proyecto)

    assert params.urbanisticos.tiene_atico is True
    assert params.urbanisticos.n_plantas_max == 3   # X-1 regulares + 1 ático = 4
    aviso = aviso_atico_catastral(proyecto)
    assert aviso is not None and aviso["color"] == "amarillo"


def test_sin_subreferencias_avisa_naranja():
    """Sin `AT` ni subreferencias legibles (R=0) → indeterminado: sin ático,
    n_plantas_max = X y aviso naranja para comprobar manualmente."""
    proyecto = _proyecto_con(5, [])
    params = ParametrosRender()
    adaptar_params_a_edificio_existente(params, proyecto)

    assert params.urbanisticos.tiene_atico is False
    assert params.urbanisticos.n_plantas_max == 5
    aviso = aviso_atico_catastral(proyecto)
    assert aviso is not None and aviso["color"] == "naranja"


def test_sin_plantas_sobre_rasante_avisa_naranja():
    """Sin `plantas_sobre_rasante` (X None) → indeterminado → aviso naranja."""
    proyecto = _proyecto_con(None, [
        "Es 1 · Pl 00 · Pt A",
        "Es 1 · Pl 01 · Pt A",
    ])
    aviso = aviso_atico_catastral(proyecto)
    assert aviso is not None and aviso["color"] == "naranja"


def test_atico_y_sotano_se_leen_de_codigos_distintos():
    """El ático viene del código `AT`; el sótano de `plantas_bajo_rasante` (la
    RC en "Pl -1" no afecta a la detección de ático)."""
    proyecto = _proyecto_con(5, [
        "Es 1 · Pl -1 · Pt A",   # garaje en sótano: no es planta sobre rasante
        "Es 1 · Pl 00 · Pt A",
        "Es 1 · Pl 01 · Pt A",
        "Es 1 · Pl 02 · Pt A",
        "Es 1 · Pl AT · Pt A",
    ], plantas_bajo_rasante=1)
    params = ParametrosRender()
    adaptar_params_a_edificio_existente(params, proyecto)

    assert params.urbanisticos.tiene_atico is True
    assert params.urbanisticos.n_plantas_max == 4
    assert params.urbanisticos.tiene_sotano is True


# ── Patios catastrales del edificio existente ───────────────────────────────
def _proyecto_con_patios(n_patios, patios_m2):
    """Proyecto cuya localización trae los patios catastrales (recogidos en §2.1)."""
    proyecto = Proyecto(nombre="test")
    proyecto.fijar_datos(ModuloPuccetti.LOCALIZACION, {
        "plantas_sobre_rasante": 4,
        "n_patios": n_patios,
        "patios_m2": patios_m2,
    })
    return proyecto


def test_patios_catastrales_sustituyen_al_patio_por_defecto():
    # La parcela tiene 2 patios reales → el motor usa esas 2 áreas, no el [12.0].
    proyecto = _proyecto_con_patios(2, [18.5, 9.0])
    params = ParametrosRender()
    assert [pd.area_m2 for pd in params.urbanisticos.patios] == [12.0]  # default antes de adaptar
    adaptar_params_a_edificio_existente(params, proyecto)
    assert [pd.area_m2 for pd in params.urbanisticos.patios] == [18.5, 9.0]


def test_catastro_sin_patios_deja_lista_vacia():
    # n_patios == 0 → el Catastro confirma que no hay patios.
    proyecto = _proyecto_con_patios(0, [])
    params = ParametrosRender()
    adaptar_params_a_edificio_existente(params, proyecto)
    assert params.urbanisticos.patios == []


def test_sin_dato_de_patios_respeta_el_default():
    # Proyecto antiguo sin n_patios/patios_m2 → no se toca el patio por defecto.
    proyecto = _proyecto_con(4, [])  # loc sin claves de patios
    params = ParametrosRender()
    adaptar_params_a_edificio_existente(params, proyecto)
    assert [pd.area_m2 for pd in params.urbanisticos.patios] == [12.0]


# ── Patios catastrales CON geometría → posicionados y bloqueados ─────────────
# Parcela pequeña en Sevilla (lon<0, lat>30 → huso UTM 25830).
_SEVILLA_CONTORNO = [
    [-5.9930, 37.3825], [-5.9928, 37.3825],
    [-5.9928, 37.3827], [-5.9930, 37.3827], [-5.9930, 37.3825],
]


def _anillo_wgs84(cx, cy, d=0.00005):
    """Anillo cuadrado pequeño (cerrado) en WGS84 alrededor de (cx, cy)."""
    return [[cx - d, cy - d], [cx + d, cy - d], [cx + d, cy + d], [cx - d, cy + d], [cx - d, cy - d]]


def _proyecto_con_patios_geom(patios_geom, *, patios_m2=None):
    proyecto = Proyecto(nombre="test")
    loc = {
        "plantas_sobre_rasante": 4,
        "contorno_wgs84": _SEVILLA_CONTORNO,
        "patios_geom": patios_geom,
    }
    if patios_m2 is not None:
        loc["patios_m2"] = patios_m2
        loc["n_patios"] = len(patios_m2)
    proyecto.fijar_datos(ModuloPuccetti.LOCALIZACION, loc)
    return proyecto


def test_patios_geom_siembra_posicionados_y_bloqueados():
    geom = [
        {"tipo": "cerrado", "area_m2": 16.0, "contorno_wgs84": _anillo_wgs84(-5.99290, 37.38258)},
        {"tipo": "abierto", "area_m2": 12.0, "contorno_wgs84": _anillo_wgs84(-5.99285, 37.38264)},
    ]
    proyecto = _proyecto_con_patios_geom(geom)
    params = ParametrosRender()
    adaptar_params_a_edificio_existente(params, proyecto)

    patios = params.urbanisticos.patios
    assert len(patios) == 2
    for pd in patios:
        assert pd.bloqueado is True
        assert pd.vertices and len(pd.vertices) >= 3
        # Vértices en UTM (metros: ~2e5 E, ~4e6 N), no en lon/lat (< 100).
        assert all(abs(x) > 1000 and abs(y) > 1000 for x, y in pd.vertices), pd.vertices
    assert [pd.area_m2 for pd in patios] == [16.0, 12.0]   # área catastral preservada
    assert [pd.origen for pd in patios] == ["catastral", "catastral_aprox"]


def test_patios_geom_tiene_prioridad_sobre_patios_m2():
    # Con geometría disponible NO se cae al respaldo por áreas (patios_m2).
    geom = [{"tipo": "cerrado", "area_m2": 20.0, "contorno_wgs84": _anillo_wgs84(-5.99290, 37.38258)}]
    proyecto = _proyecto_con_patios_geom(geom, patios_m2=[5.0, 5.0])
    params = ParametrosRender()
    adaptar_params_a_edificio_existente(params, proyecto)

    patios = params.urbanisticos.patios
    assert len(patios) == 1
    assert patios[0].area_m2 == 20.0
    assert patios[0].vertices is not None
    assert patios[0].bloqueado is True


def test_patios_geom_corruptos_caen_al_respaldo_por_areas():
    # Anillos sin vértices válidos → no se siembra geometría; usa patios_m2.
    geom = [{"tipo": "cerrado", "area_m2": 16.0, "contorno_wgs84": [[1.0]]}]  # punto inválido
    proyecto = _proyecto_con_patios_geom(geom, patios_m2=[7.5])
    params = ParametrosRender()
    adaptar_params_a_edificio_existente(params, proyecto)

    patios = params.urbanisticos.patios
    assert [pd.area_m2 for pd in patios] == [7.5]
    assert all(pd.vertices is None for pd in patios)
