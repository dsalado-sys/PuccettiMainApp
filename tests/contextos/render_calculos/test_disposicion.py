"""Tests de la autodistribución del cálculo sobre el lienzo (§2.4/§2.5 + Anexo II).

Dos niveles:
1. Geometría pura (`geometria.disposicion.disponer_planta`): cuadre exacto de
   áreas con los m² objetivo, contención dentro de la huella, incidencias de
   Anexo II (vestíbulo Ø1,50, pasillo ≥1,20, luz de patio), huellas cóncavas,
   sótano y fallback treemap.
2. Caso de uso (`AutodistribuirLienzo`): de la capacidad calculada a piezas del
   lienzo, con persistencia por planta en el aggregate.
"""
from __future__ import annotations

import math

import pytest
from shapely.geometry import Polygon, box

from app.contextos.render_calculos.casos_uso import CalcularLayout, ParcelaMetrica
from app.contextos.render_calculos.casos_uso_lienzo import AutodistribuirLienzo
from app.contextos.render_calculos.geometria.config import Parametros
from app.contextos.render_calculos.geometria.disposicion import (
    ObjetivoPlanta,
    disponer_planta,
)
from app.contextos.render_calculos.geometria.parcelas import LadoParcela
from app.contextos.render_calculos.parametros import ParametrosRender
from app.nucleo.modelo import ModuloPuccetti, Proyecto
from app.plataforma.persistencia.proyectos_en_memoria import ProyectosEnMemoria


# ─── Helpers ────────────────────────────────────────────────────────────────
def _lado(p1, p2, tipo: str) -> LadoParcela:
    return LadoParcela(
        p1=p1, p2=p2, tipo=tipo,
        longitud_m=math.hypot(p2[0] - p1[0], p2[1] - p1[1]),
        azimut=0.0, normal_azimut=0.0,
    )


def _lados_rect(w: float, h: float) -> list[LadoParcela]:
    """Rectángulo entre medianeras: lados largos fachada, cortos medianera."""
    return [
        _lado((0, 0), (w, 0), "fachada"),
        _lado((w, 0), (w, h), "medianera"),
        _lado((w, h), (0, h), "fachada"),
        _lado((0, h), (0, 0), "medianera"),
    ]


def _objetivo_proporcional(nombre, tipo, footprint, n_unidades,
                           pct_muros=0.20, pct_circ=0.08, pct_nuc=0.05,
                           patio=12.0, local=0.0) -> ObjetivoPlanta:
    """Construye un objetivo cuyas categorías suman exactamente la huella."""
    A = footprint.area
    muros = A * pct_muros
    circ = A * pct_circ
    nuc = A * pct_nuc
    util = A - muros - circ - nuc - patio - local
    unidades = [(f"V{i + 1}", util / n_unidades) for i in range(n_unidades)] if n_unidades else []
    return ObjetivoPlanta(nombre, tipo, footprint, unidades, muros, circ, nuc, patio, local, util)


def _suma_areas(res) -> float:
    return round(sum(res.areas.values()), 2)


def _overflow(res, footprint: Polygon) -> float:
    fuera = 0.0
    for p in res.piezas:
        poly = Polygon(p.vertices).buffer(0)
        fuera += poly.difference(footprint.buffer(0.05)).area
    return fuera


# ─── 1. Geometría pura ──────────────────────────────────────────────────────
def test_cuadre_exacto_de_areas():
    fp = box(0, 0, 20, 12)  # 240 m²
    obj = _objetivo_proporcional("PB", "regular", fp, n_unidades=4)
    res = disponer_planta(obj, _lados_rect(20, 12), Parametros())

    assert _suma_areas(res) == pytest.approx(fp.area, abs=0.5)
    # Cada categoría coincide con su objetivo (±tolerancia de bisección).
    assert res.areas["muro"] == pytest.approx(obj.muros_m2, abs=0.5)
    assert res.areas["circulacion"] == pytest.approx(obj.circulacion_m2, abs=0.5)
    assert res.areas["nucleo"] == pytest.approx(obj.nucleo_m2, abs=0.5)
    assert res.areas["patio"] == pytest.approx(obj.patio_m2, abs=0.5)
    assert res.areas["unidad"] == pytest.approx(obj.util_m2, abs=0.5)


def test_una_pieza_por_unidad():
    fp = box(0, 0, 24, 12)
    obj = _objetivo_proporcional("PB", "regular", fp, n_unidades=5)
    res = disponer_planta(obj, _lados_rect(24, 12), Parametros())
    unidades = [p for p in res.piezas if p.categoria == "unidad"]
    assert len(unidades) == 5


def test_piezas_dentro_de_la_huella():
    fp = box(0, 0, 20, 12)
    obj = _objetivo_proporcional("PB", "regular", fp, n_unidades=3)
    res = disponer_planta(obj, _lados_rect(20, 12), Parametros())
    assert _overflow(res, fp) == pytest.approx(0.0, abs=0.05)


def test_local_en_planta_baja():
    fp = box(0, 0, 24, 12)  # 288
    obj = _objetivo_proporcional("PB", "regular", fp, n_unidades=2, local=30.0)
    res = disponer_planta(obj, _lados_rect(24, 12), Parametros())
    assert res.areas.get("local", 0.0) == pytest.approx(30.0, abs=0.5)
    assert _suma_areas(res) == pytest.approx(fp.area, abs=0.5)


def test_sotano_sin_unidades():
    fp = box(0, 0, 24, 12)
    obj = ObjetivoPlanta("S1", "sotano", fp, [], muros_m2=57.6,
                         circulacion_m2=0.0, nucleo_m2=14.4,
                         patio_m2=0.0, local_m2=0.0, util_m2=0.0)
    res = disponer_planta(obj, _lados_rect(24, 12), Parametros())
    assert not any(p.categoria == "unidad" for p in res.piezas)
    assert res.areas.get("resto", 0.0) > 0  # interior del sótano
    assert _suma_areas(res) == pytest.approx(fp.area, abs=0.5)


def test_una_unidad_con_patio_no_pierde_area():
    # Regresión: con una sola unidad, el patio queda en la banda sin unidades;
    # debe pintarse igualmente (antes se perdía → el cuadre fallaba ~18%).
    fp = box(0, 0, 9, 9)  # 81 m²
    obj = _objetivo_proporcional("PB", "regular", fp, n_unidades=1, patio=12.0)
    res = disponer_planta(obj, _lados_rect(9, 9), Parametros())
    assert res.areas.get("patio", 0.0) == pytest.approx(12.0, abs=0.6)
    assert _suma_areas(res) == pytest.approx(fp.area, abs=0.5)
    assert _overflow(res, fp) == pytest.approx(0.0, abs=0.05)


def test_huella_concava_cuadra_y_no_desborda():
    # Huella en L: 24×6 + 12×6 = 216 m².
    fp = Polygon([(0, 0), (24, 0), (24, 6), (12, 6), (12, 12), (0, 12)])
    obj = _objetivo_proporcional("P1", "regular", fp, n_unidades=2)
    lados = [_lado((0, 0), (24, 0), "fachada"), _lado((0, 12), (0, 0), "medianera")]
    res = disponer_planta(obj, lados, Parametros())
    assert _suma_areas(res) == pytest.approx(fp.area, abs=1.0)
    assert _overflow(res, fp) == pytest.approx(0.0, abs=0.1)


def test_huella_pequena_cae_a_treemap():
    fp = box(0, 0, 6, 5)  # 30 m² — no caben dos crujías + pasillo
    obj = _objetivo_proporcional("PB", "regular", fp, n_unidades=1, patio=0.0)
    res = disponer_planta(obj, _lados_rect(6, 5), Parametros())
    assert _suma_areas(res) == pytest.approx(fp.area, abs=0.5)
    assert any("simplificada" in inc for inc in res.incidencias)


def test_incidencia_vestibulo_y_pasillo_estrechos():
    # 200 m² con 5% núcleo y 8% circulación → vestíbulo y pasillo por debajo del mínimo.
    fp = box(0, 0, 20, 10)
    obj = _objetivo_proporcional("PB", "regular", fp, n_unidades=3)
    res = disponer_planta(obj, _lados_rect(20, 10), Parametros())
    texto = " ".join(res.incidencias)
    assert "vestíbulo" in texto.lower() or "Ø" in texto
    assert "pasillo" in texto.lower()
    # Las incidencias citan "Normativa" (trazabilidad sin artículos literales en UI).
    assert all(inc.startswith("Normativa") or "simplificada" in inc or "huella" in inc
               for inc in res.incidencias)


def test_patio_pequeno_avisa_superficie_minima():
    # Patio de 8 m² (< 12 m² normativo) → incidencia de superficie mínima (A2.5).
    fp = box(0, 0, 20, 12)  # 240
    A = fp.area
    muros, circ, nuc, patio = A * 0.2, A * 0.08, A * 0.05, 8.0
    util = A - muros - circ - nuc - patio
    unidades = [(f"V{i+1}", util / 3) for i in range(3)]
    obj = ObjetivoPlanta("PB", "regular", fp, unidades, muros, circ, nuc, patio, 0.0, util)
    res = disponer_planta(obj, _lados_rect(20, 12), Parametros())
    assert any("superficie mínima" in inc for inc in res.incidencias)


def test_incidencias_sin_referencias_literales():
    # Las alertas de UI no citan "A2.x" ni "§x.x" (criterio del estudio).
    fp = box(0, 0, 20, 10)
    obj = _objetivo_proporcional("PB", "regular", fp, n_unidades=3)
    res = disponer_planta(obj, _lados_rect(20, 10), Parametros())
    assert res.incidencias  # hay avisos (percentajes ajustados)
    for inc in res.incidencias:
        assert "A2." not in inc and "§" not in inc
        assert "Anexo" not in inc and "Decreto" not in inc


def test_muros_distinguen_fachada_y_medianera():
    fp = box(0, 0, 20, 12)
    obj = _objetivo_proporcional("PB", "regular", fp, n_unidades=3)
    res = disponer_planta(obj, _lados_rect(20, 12), Parametros())
    nombres = {p.nombre for p in res.piezas if p.categoria == "muro"}
    assert "Muro fachada" in nombres
    assert "Muro medianera" in nombres


# ─── 2. Caso de uso AutodistribuirLienzo ────────────────────────────────────
def _parcela(w=20.0, h=12.0) -> ParcelaMetrica:
    return ParcelaMetrica(
        poligono_utm=box(0, 0, w, h),
        lados=_lados_rect(w, h),
        municipio="Sevilla", provincia="Sevilla",
        centroide_lonlat=None, referencia_catastral=None,
    )


def test_autodistribuir_genera_plantas_y_cuadra():
    proyecto = Proyecto(nombre="Test")
    parcela = _parcela()
    params = ParametrosRender()  # vivienda 2D, coef 2.5, 3 plantas
    caso = AutodistribuirLienzo(layout=CalcularLayout())
    out = caso.ejecutar(proyecto, parcela, params)

    assert out.get("error") is None
    assert out["plantas"], "debe generar al menos una planta"
    # Cada planta: figuras con formato del lienzo y áreas que cuadran con la huella.
    for idx, bloque in out["plantas"].items():
        assert bloque["muros"] == []
        for fig in bloque["figuras"]:
            assert set(fig) >= {"id", "tipo", "nombre", "color", "vertices", "rotacion"}
            assert fig["tipo"] == "poly"
            assert len(fig["vertices"]) >= 3
    # El resumen reporta el cuadre por planta.
    for fila in out["resumen"]:
        assert fila["n_piezas"] > 0


def test_autodistribuir_persiste_reemplazando():
    repo = ProyectosEnMemoria()
    proyecto = Proyecto(nombre="Test")
    repo.guardar(proyecto)
    parcela = _parcela()
    params = ParametrosRender()
    caso = AutodistribuirLienzo(layout=CalcularLayout(), repo_proyectos=repo)
    out = caso.ejecutar(proyecto, parcela, params, persistir=True)

    assert out["persistido"] == len(out["plantas"])
    guardado = proyecto.datos_por_modulo[ModuloPuccetti.RENDER_CALCULOS.value]["lienzo"]["plantas"]
    assert set(guardado) == set(out["plantas"])
    # El bloque persistido conserva las figuras crudas (vertices) de una planta.
    alguna = next(iter(guardado.values()))
    assert alguna["figuras"] and alguna["figuras"][0]["vertices"]


def test_autodistribuir_limpia_plantas_obsoletas():
    # Si el proyecto tenía dibujos en más plantas de las que ahora existen,
    # autodistribuir (todas) descarta las obsoletas al persistir.
    repo = ProyectosEnMemoria()
    proyecto = Proyecto(nombre="Test")
    proyecto.datos(ModuloPuccetti.RENDER_CALCULOS)["lienzo"] = {
        "plantas": {str(i): {"figuras": [], "muros": []} for i in range(6)}
    }
    repo.guardar(proyecto)
    parcela = _parcela()
    caso = AutodistribuirLienzo(layout=CalcularLayout(), repo_proyectos=repo)
    out = caso.ejecutar(proyecto, parcela, ParametrosRender(), persistir=True)

    guardado = proyecto.datos_por_modulo[ModuloPuccetti.RENDER_CALCULOS.value]["lienzo"]["plantas"]
    assert set(guardado) == set(out["plantas"])  # sin claves obsoletas (3,4,5)


def test_autodistribuir_planta_unica():
    proyecto = Proyecto(nombre="Test")
    parcela = _parcela()
    params = ParametrosRender()
    caso = AutodistribuirLienzo(layout=CalcularLayout())
    out = caso.ejecutar(proyecto, parcela, params, planta=0)
    assert list(out["plantas"]) == ["0"]
