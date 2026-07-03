"""Disposición geométrica interior del edificio (§2.5 «Pintar render», Fases 1-2).

Verifica el motor nuevo `geometria/disposicion.py`: por cada zona coloca un núcleo y
sus unidades como cuadrados de área fija adaptados a los límites, con la circulación
como superficie sobrante. Reintentos + rojo cuando algo no cabe; nunca se borra una
unidad. También el contrato de serialización (`edificio_a_dict`) y el cableado del
flag `disponer` en `CalcularLayout`.

Geometría sintética (`box`) + pipeline real (`construir_envolvente` +
`calcular_capacidad`); sin tocar la API de Catastro ni la BBDD.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from app.contextos.render_calculos.casos_uso import CalcularLayout, ParcelaMetrica
from app.contextos.render_calculos.geometria.capacidad import calcular_capacidad
from app.contextos.render_calculos.geometria.disposicion import (
    EdificioDispuesto,
    disponer_edificio,
)
from app.contextos.render_calculos.geometria.envolvente import construir_envolvente
from app.contextos.render_calculos.geometria.parcelas import (
    LadoParcela,
    azimut_normal_exterior,
)
from app.contextos.render_calculos.geometria.serializacion import edificio_a_dict
from app.contextos.render_calculos.parametros import (
    ParametrosRender,
    parametros_desde_dict,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────
def _params_motor():
    return ParametrosRender().a_parametros_motor()


def _env_simple(footprint=box(0.0, 0.0, 30.0, 20.0), patios_geom=()):
    """Envolvente mínima (una planta) con control total de la geometría."""
    patios = [
        SimpleNamespace(
            geometry=g, area_m2=g.area, luz_recta_m=3.0, base=None,
            area_efectiva_m2=g.area, cabe=True, bloqueado=False, id="",
        )
        for g in patios_geom
    ]
    planta = SimpleNamespace(n=0, tipo="regular", footprint=footprint, patios=patios)
    return SimpleNamespace(plantas=[planta])


def _cap(*, viv, unidades, nucleo, nombres, nzonas=1, adaptadas=0):
    return SimpleNamespace(
        viv_por_planta=list(viv),
        unidades_por_planta=[list(u) for u in unidades],
        nucleo_por_planta=list(nucleo),
        nombres_planta=list(nombres),
        n_zonas=nzonas,
        n_unidades_adaptadas=adaptadas,
    )


def _cap_holgada():
    """3 unidades + núcleo en una planta espaciosa (600 m²): todo cabe con holgura."""
    return _cap(
        viv=[3],
        unidades=[[(2, 50.0), (2, 50.0), (1, 40.0)]],
        nucleo=[15.0],
        nombres=["PB"],
    )


def _pipeline(footprint=box(0.0, 0.0, 30.0, 20.0)):
    """Envolvente + capacidad REALES desde el motor (vivienda por defecto)."""
    pm = _params_motor()
    env = construir_envolvente(footprint, pm, None, superficie_referencia=footprint.area)
    cap = calcular_capacidad(env, pm)
    return env, cap, pm


def _parcela_cuadrada(lado_m: float = 28.0) -> ParcelaMetrica:
    coords = [(0.0, 0.0), (lado_m, 0.0), (lado_m, lado_m), (0.0, lado_m)]
    poly = Polygon(coords)
    lados = []
    for i, p1 in enumerate(coords):
        p2 = coords[(i + 1) % len(coords)]
        long_m = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        az = (math.degrees(math.atan2(p2[0] - p1[0], p2[1] - p1[1]))) % 360
        lados.append(LadoParcela(
            p1=p1, p2=p2, tipo="fachada", longitud_m=long_m, azimut=az,
            normal_azimut=azimut_normal_exterior(p1, p2, poly),
        ))
    return ParcelaMetrica(
        poligono_utm=poly, lados=lados, municipio="X", provincia="Y",
        centroide_lonlat=None, referencia_catastral=None,
    )


def _params_vivienda():
    return parametros_desde_dict({
        "urbanisticos": {"coeficiente_edificabilidad": 2.5, "n_plantas_max": 3,
                         "ocupacion_maxima_pct": 100.0},
        "programa": {"uso": "vivienda", "categoria_vivienda": "2d"},
    })


# ─── Fase 1: núcleo por zona + circulación sobrante ─────────────────────────
def test_nucleo_dentro_de_la_zona_y_area():
    footprint = box(0.0, 0.0, 30.0, 20.0)
    edif = disponer_edificio(_env_simple(footprint), _cap_holgada(), _params_motor())
    pl = edif.plantas[0]
    assert pl.nucleo is not None
    # Núcleo dentro de la huella (colocado en `zona.buffer(-c)` ⊆ footprint).
    assert footprint.buffer(0.1).contains(pl.nucleo.poligono)
    # Área fija ≈ objetivo (nucleo_por_planta / nº zonas = 15 / 1).
    assert pl.nucleo.poligono.area == pytest.approx(15.0, rel=0.05)


def test_circulacion_no_vacia_y_conexa_toca_el_borde():
    footprint = box(0.0, 0.0, 30.0, 20.0)
    edif = disponer_edificio(_env_simple(footprint), _cap_holgada(), _params_motor())
    pl = edif.plantas[0]
    assert len(pl.pasillos) >= 1
    circ = unary_union(pl.pasillos)
    assert circ.area > 0
    # El bloque se ancla a la esquina de fachada y la circulación queda como franja
    # sobrante al otro lado: por tanto toca el borde de la huella.
    assert circ.distance(footprint.exterior) < 1e-6


def test_sin_disponer_no_hay_edificio_en_calcular_layout():
    r = CalcularLayout().ejecutar(_parcela_cuadrada(), _params_vivienda())
    assert not r.get("error")
    assert r["edificio"] is None


# ─── Fase 2: unidades (área fija adaptada) + reintentos + rojo ───────────────
def test_numero_de_unidades_igual_a_capacidad():
    footprint = box(0.0, 0.0, 30.0, 20.0)
    cap = _cap_holgada()
    edif = disponer_edificio(_env_simple(footprint), cap, _params_motor())
    # Se dibujan SIEMPRE las viv_por_planta unidades (invariante: nunca se borra una).
    assert len(edif.plantas[0].unidades) == cap.viv_por_planta[0]


def test_cada_unidad_conserva_su_area_objetivo_si_cabe():
    footprint = box(0.0, 0.0, 30.0, 20.0)
    cap = _cap_holgada()
    pm = _params_motor()
    factor = 1.0 + pm.diseno.pct_muros_interior / 100.0
    edif = disponer_edificio(_env_simple(footprint), cap, pm)
    for u in edif.plantas[0].unidades:
        assert u.poligono_construido.area > 0            # dibujada siempre
        if u.cumple_minimos:
            objetivo = u.area_util_m2 * factor           # construida = útil × (1+%tabiquería)
            assert u.poligono_construido.area == pytest.approx(objetivo, rel=0.06)


def test_bloque_compacto_sin_solapes_y_contiguo():
    footprint = box(0.0, 0.0, 30.0, 20.0)
    cap = _cap_holgada()
    edif = disponer_edificio(_env_simple(footprint), cap, _params_motor())
    pl = edif.plantas[0]
    # En una planta espaciosa todas las unidades caben (cumplen su área).
    assert all(u.cumple_minimos for u in pl.unidades)
    piezas = [pl.nucleo.poligono] + [u.poligono_construido for u in pl.unidades]
    # Empaquetado compacto: comparten muros medianeros (se TOCAN) pero NO se solapan.
    for a in range(len(piezas)):
        for b in range(a + 1, len(piezas)):
            assert piezas[a].intersection(piezas[b]).area < 1e-6
    # El bloque núcleo+unidades es CONTIGUO (una sola pieza conexa).
    assert unary_union(piezas).geom_type == "Polygon"
    # La circulación queda como franja sobrante a un lado (no vacía).
    assert sum(p.area for p in pl.pasillos) > 0


def test_ids_unicos_por_planta():
    footprint = box(0.0, 0.0, 30.0, 20.0)
    edif = disponer_edificio(_env_simple(footprint), _cap_holgada(), _params_motor())
    ids = [u.id for u in edif.plantas[0].unidades]
    assert ids == ["PB·U1", "PB·U2", "PB·U3"]
    assert len(ids) == len(set(ids))


def test_unidad_que_no_cabe_va_en_rojo_pero_se_dibuja():
    # Planta diminuta (10×10 = 100 m²) con una unidad enorme (construida ~200): no cabe
    # ⇒ se dibuja en su mejor forma con cumple_minimos=False (rojo), no se descarta.
    footprint = box(0.0, 0.0, 10.0, 10.0)
    cap = _cap(viv=[1], unidades=[[(3, 200.0)]], nucleo=[0.0], nombres=["PB"])
    edif = disponer_edificio(_env_simple(footprint), cap, _params_motor())
    unidades = edif.plantas[0].unidades
    assert len(unidades) == 1                       # nunca se borra
    u = unidades[0]
    assert u.cumple_minimos is False                # rojo
    assert u.poligono_construido.area > 0           # dibujada
    assert footprint.buffer(0.1).contains(u.poligono_construido)   # dentro de la huella


# ─── Multi-zona + accesibilidad ─────────────────────────────────────────────
def test_dos_zonas_reparte_unidades_y_marca_adaptadas():
    footprint = box(0.0, 0.0, 40.0, 20.0)
    patio = box(18.0, 0.0, 22.0, 20.0)      # atraviesa la huella → 2 zonas
    env = _env_simple(footprint, patios_geom=[patio])
    cap = _cap(
        viv=[4],
        unidades=[[(2, 55.0), (2, 55.0), (1, 40.0), (1, 40.0)]],
        nucleo=[30.0], nombres=["PB"], nzonas=2, adaptadas=1,
    )
    edif = disponer_edificio(env, cap, _params_motor())
    pl = edif.plantas[0]
    assert len(pl.unidades) == 4                             # todas dibujadas
    assert sum(1 for u in pl.unidades if u.es_adaptada) == 1  # exactamente n_adaptadas
    assert pl.nucleo is not None                             # núcleo en la zona mayor
    # Las unidades no pisan el patio (viven en la región huella − patios).
    for u in pl.unidades:
        assert u.poligono_construido.intersection(patio).area < 0.5


def test_unidades_no_se_apilan_en_zona_sobrecargada():
    # Zona pequeña (12×10 = 120 m²) a la que se asignan 2 unidades grandes (70 m²
    # construida c/u): no caben ambas con holgura, pero NUNCA deben apilarse en el
    # mismo sitio: la segunda ocupa el resto libre de la zona.
    footprint = box(0.0, 0.0, 12.0, 10.0)
    cap = _cap(viv=[2], unidades=[[(2, 70.0), (2, 70.0)]], nucleo=[0.0], nombres=["PB"])
    edif = disponer_edificio(_env_simple(footprint), cap, _params_motor())
    unidades = edif.plantas[0].unidades
    assert len(unidades) == 2
    a, b = unidades[0].poligono_construido, unidades[1].poligono_construido
    assert a.area > 0 and b.area > 0
    # No se superponen apenas (no están una encima de la otra).
    solape = a.intersection(b).area
    assert solape < 0.5 * min(a.area, b.area)


def test_todas_las_unidades_se_dibujan_en_zona_saturada():
    # Planta diminuta (8×8 = 64 m²) con 3 unidades enormes: ninguna cabe, pero las 3
    # se dibujan (no vacías) en rojo. Garantía «nunca se borra una unidad».
    footprint = box(0.0, 0.0, 8.0, 8.0)
    cap = _cap(viv=[3], unidades=[[(3, 60.0), (3, 60.0), (3, 60.0)]], nucleo=[0.0],
               nombres=["PB"])
    edif = disponer_edificio(_env_simple(footprint), cap, _params_motor())
    unidades = edif.plantas[0].unidades
    assert len(unidades) == 3                                  # nunca se borra una unidad
    assert all(u.poligono_construido.area > 0 for u in unidades)   # todas dibujadas
    # La zona no da para las 3: al menos las sobrantes van en rojo (no caben).
    assert sum(1 for u in unidades if not u.cumple_minimos) >= 2


def test_planta_sin_unidades_solo_nucleo_y_circulacion():
    # Sótano/planta sin viviendas: núcleo + circulación, sin unidades (no revienta).
    footprint = box(0.0, 0.0, 30.0, 20.0)
    cap = _cap(viv=[0], unidades=[[]], nucleo=[15.0], nombres=["S1"])
    env = SimpleNamespace(plantas=[SimpleNamespace(
        n=-1, tipo="sotano", footprint=footprint, patios=[])])
    edif = disponer_edificio(env, cap, _params_motor())
    pl = edif.plantas[0]
    assert pl.unidades == []
    assert pl.nucleo is not None
    assert len(pl.pasillos) >= 1


# ─── Contrato del canvas (edificio_a_dict) ──────────────────────────────────
def test_edificio_a_dict_cumple_el_contrato_del_canvas():
    env, cap, pm = _pipeline()
    d = edificio_a_dict(disponer_edificio(env, cap, pm))
    assert d is not None and "plantas" in d
    assert len(d["plantas"]) == len(env.plantas)
    for pl in d["plantas"]:
        for clave in ("n", "nombre", "tipo", "footprint", "patios", "nucleo",
                      "unidades", "pasillos"):
            assert clave in pl
        assert isinstance(pl["footprint"], list) and len(pl["footprint"]) >= 3
        if pl["nucleo"] is not None:
            assert len(pl["nucleo"]["poligono"]) >= 3
        for p in pl["pasillos"]:
            assert isinstance(p["poligono"], list)
        for pt in pl["patios"]:                    # mismas claves que la envolvente
            assert {"id", "poligono", "huecos", "bloqueado"}.issubset(pt)
        for u in pl["unidades"]:
            assert len(u["poligono_construido"]) >= 3
            assert isinstance(u["poligono_util"], list)
            assert isinstance(u["area_util_m2"], (int, float))   # obligatorio (canvas .toFixed)
            assert isinstance(u["cumple_minimos"], bool)
            assert isinstance(u["es_adaptada"], bool)
            assert u["id"]


def test_edificio_a_dict_none_es_none():
    assert edificio_a_dict(None) is None


# ─── Cableado del flag `disponer` en CalcularLayout ─────────────────────────
def test_calcular_layout_con_disponer_devuelve_edificio():
    r = CalcularLayout().ejecutar(_parcela_cuadrada(), _params_vivienda(), disponer=True)
    assert not r.get("error")
    assert r["edificio"] is not None
    assert r["edificio"]["plantas"]
    # Alineado con la envolvente (mismos tabs de planta).
    assert len(r["edificio"]["plantas"]) == len(r["envolvente"]["plantas"])


def test_fallo_geometrico_no_tumba_el_calculo(monkeypatch):
    # Si el motor de disposición revienta, la respuesta conserva los números
    # (edificio None) y añade un aviso, sin propagar la excepción (§ robustez).
    from shapely.errors import GEOSException

    import app.contextos.render_calculos.casos_uso as cu

    def _boom(*a, **k):
        raise GEOSException("fallo geométrico simulado")

    monkeypatch.setattr(cu, "disponer_edificio", _boom)
    r = CalcularLayout().ejecutar(_parcela_cuadrada(), _params_vivienda(), disponer=True)
    assert not r.get("error")                     # los números siguen
    assert r["edificio"] is None                  # sin disposición
    assert r["capacidad"] is not None
    assert any("dibujar la disposición" in a["mensaje"] for a in r["alertas"])
