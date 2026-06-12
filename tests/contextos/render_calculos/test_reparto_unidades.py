"""Tests del reparto geométrico de unidades en planta (§2.5 + criterios A2.x).

Invariantes principales:
- El plano dibuja EXACTAMENTE las unidades del cálculo (cardinalidad, orden,
  slugs); las que no caben se declaran «no ubicadas», nunca se omiten.
- `edificio.plantas` alineado 1:1 con `envolvente.plantas` / `cap.nombres_planta`.
- Tabla y plano marcan las MISMAS unidades adaptadas (helper compartido).
- Determinismo: mismo input → misma geometría.
- Textos de alerta sin referencias normativas literales (criterio del estudio).
"""
from __future__ import annotations

import json
import re

import pytest
from shapely.geometry import Polygon

from app.contextos.render_calculos.casos_uso import CalcularLayout, ParcelaMetrica
from app.contextos.render_calculos.geometria.capacidad import (
    calcular_capacidad,
    indices_adaptadas,
)
from app.contextos.render_calculos.geometria.config import Parametros
from app.contextos.render_calculos.geometria.envolvente import construir_envolvente
from app.contextos.render_calculos.geometria.parcelas import clasificar_lados
from app.contextos.render_calculos.geometria.reparto_unidades import (
    ASCENSOR_LADO,
    repartir_unidades,
)
from app.contextos.render_calculos.geometria.serializacion import (
    edificio_dispuesto_a_dict,
)

ASCENSOR_AREA = ASCENSOR_LADO ** 2
from app.contextos.render_calculos.parametros import parametros_desde_dict


# ─── Builders ────────────────────────────────────────────────────────────────
def _lados_fachada_sur(poly: Polygon):
    """Fachada en los lados sobre y=0; medianera en el resto."""
    lados = clasificar_lados(poly)
    for l in lados:
        l.tipo = "fachada" if abs(l.p1[1]) < 0.01 and abs(l.p2[1]) < 0.01 else "medianera"
    return lados


def _escenario_motor(coords, n_plantas=3, fachada_sur=True, **urbanismo):
    poly = Polygon(coords)
    lados = clasificar_lados(poly) if not fachada_sur else _lados_fachada_sur(poly)
    params = Parametros()
    params.programa.n_plantas = n_plantas
    params.urbanismo.n_plantas_max = n_plantas
    for k, v in urbanismo.items():
        setattr(params.urbanismo, k, v)
    env = construir_envolvente(poly, params, lados)
    cap = calcular_capacidad(env, params)
    edif = repartir_unidades(env, lados, params, cap)
    return env, cap, params, edif


def _parcela_metrica(coords=((0, 0), (30, 0), (30, 14), (0, 14))):
    poly = Polygon(coords)
    return ParcelaMetrica(
        poligono_utm=poly, lados=_lados_fachada_sur(poly),
        municipio="Sevilla", provincia="Sevilla",
        centroide_lonlat=None, referencia_catastral=None,
    )


def _calcular(payload_programa=None, payload_urbanisticos=None, parcela=None):
    params = parametros_desde_dict({
        "programa": payload_programa or {"uso": "vivienda", "categoria_vivienda": "2d"},
        "urbanisticos": payload_urbanisticos or {"n_plantas_max": 3},
    })
    return CalcularLayout().ejecutar(parcela or _parcela_metrica(), params)


def _unidades_reales(planta_dict):
    """Entradas de unidades del cálculo (excluye piezas local/social/resto)."""
    return [u for u in planta_dict["unidades"]
            if u["tipo"] not in ("local", "zona_social", "resto")]


# ─── Invariantes de contrato con el cálculo ──────────────────────────────────
def test_cardinalidad_y_slugs_por_planta():
    env, cap, params, edif = _escenario_motor([(0, 0), (30, 0), (30, 14), (0, 14)])
    assert len(edif.plantas) == len(env.plantas) == len(cap.nombres_planta)
    for i, pl in enumerate(edif.plantas):
        assert pl.nombre == cap.nombres_planta[i]
        assert len(pl.unidades) == len(cap.unidades_por_planta[i])
        assert [u.slug for u in pl.unidades] == cap.tipologias_unidad_por_planta[i]
        for u, (n_dorms, util) in zip(pl.unidades, cap.unidades_por_planta[i]):
            assert u.n_dorms == n_dorms
            assert u.util_objetivo_m2 == pytest.approx(util, abs=0.01)


def test_orden_de_plantas_con_sotano_y_atico():
    env, cap, params, edif = _escenario_motor(
        [(0, 0), (26, 0), (26, 15), (0, 15)], n_plantas=2,
        tiene_atico=True, retranqueo_atico=3.0, tiene_sotano=True,
    )
    nombres = [pl.nombre for pl in edif.plantas]
    assert nombres == ["S1", "PB", "P1", "Ático"] == cap.nombres_planta
    d = edificio_dispuesto_a_dict(edif)
    assert [p["nombre"] for p in d["plantas"]] == nombres


def test_unidades_acceso_y_ventilacion_en_parcela_nominal():
    _, _, _, edif = _escenario_motor([(0, 0), (30, 0), (30, 14), (0, 14)])
    ubicadas = [u for pl in edif.plantas for u in pl.unidades if u.ubicada]
    assert ubicadas, "el escenario nominal debe ubicar unidades"
    assert all(u.acceso_pasillo for u in ubicadas)
    assert all(u.ventila_ok for u in ubicadas)
    assert all(u.frente_fachada_m > 0 for u in ubicadas)


def test_huella_en_L_todas_servidas():
    _, _, _, edif = _escenario_motor(
        [(0, 0), (28, 0), (28, 10), (14, 10), (14, 18), (0, 18)], n_plantas=2,
    )
    ubicadas = [u for pl in edif.plantas for u in pl.unidades if u.ubicada]
    assert ubicadas
    assert all(u.acceso_pasillo for u in ubicadas)
    assert all(u.ventila_ok for u in ubicadas)


def test_nucleo_unico_y_continuidad_vertical():
    _, _, _, edif = _escenario_motor([(0, 0), (30, 0), (30, 14), (0, 14)])
    nucleos = [pl.nucleo for pl in edif.plantas if pl.nucleo is not None]
    assert nucleos
    ref = nucleos[0].geometry
    assert all(n.geometry.equals(ref) for n in nucleos)


def test_atico_retranqueado_caseton_informativo():
    _, _, _, edif = _escenario_motor(
        [(0, 0), (26, 0), (26, 15), (0, 15)], n_plantas=2,
        tiene_atico=True, retranqueo_atico=3.0,
    )
    atico = next(pl for pl in edif.plantas if pl.tipo == "atico")
    # La unidad del ático debe ventilar por su PROPIA fachada (retranqueada).
    assert all(u.ventila_ok for u in atico.unidades if u.ubicada)
    if any(pl.nucleo_es_caseton for pl in edif.plantas):
        niveles = [a.nivel for a in edif.alertas if "casetón" in a.mensaje]
        assert niveles == ["info"]


def test_determinismo_mismo_input_misma_geometria():
    def run():
        _, _, _, edif = _escenario_motor([(0, 0), (30, 0), (30, 14), (0, 14)])
        return json.dumps(edificio_dispuesto_a_dict(edif), sort_keys=True)
    assert run() == run()


# ─── Adaptadas: tabla y plano coinciden ──────────────────────────────────────
@pytest.mark.parametrize("pct", [0.0, 10.0, 33.0, 100.0])
def test_adaptadas_coinciden_tabla_y_plano(pct):
    res = _calcular(payload_programa={
        "uso": "vivienda", "categoria_vivienda": "2d", "pct_unidades_adaptadas": pct,
    })
    plano = [u["id"] for p in res["edificio"]["plantas"]
             for u in _unidades_reales(p) if u["es_adaptada"]]
    tabla = [r["vivienda"] for r in res["tabla_unidad"]
             if r.get("adaptada") and r.get("tipo") != "local"]
    assert plano == tabla


def test_indices_adaptadas_redondeo_media_unidad():
    _, cap, _, _ = _escenario_motor([(0, 0), (30, 0), (30, 14), (0, 14)])
    total = cap.n_viviendas_objetivo
    # int(x + 0.5): con el 50% exacto de una unidad se marca 1 (no 0).
    pct_media = 50.0 / total
    assert len(indices_adaptadas(cap, pct_media)) == 1
    assert len(indices_adaptadas(cap, 0.0)) == 0
    assert len(indices_adaptadas(cap, 100.0)) == total


# ─── Piezas singulares ───────────────────────────────────────────────────────
def test_local_pb_a_fachada_y_sin_contar_como_vivienda():
    res = _calcular(payload_programa={
        "uso": "vivienda", "categoria_vivienda": "2d", "pct_local_pb": 25.0,
    })
    pb = res["edificio"]["plantas"][0]
    locales = [u for u in pb["unidades"] if u["tipo"] == "local"]
    assert len(locales) == 1
    local = locales[0]
    assert local["frente_fachada_m"] > 0, "el local debe tener escaparate a fachada"
    local_calc = res["capacidad"]["local_por_planta"][0]
    assert local["area_util_m2"] == pytest.approx(local_calc, rel=0.25)
    assert pb["n_viviendas"] == len([u for u in _unidades_reales(pb) if u["estado"] == "ubicada"])


def test_hotel_zonas_sociales_en_pb():
    res = _calcular(payload_programa={
        "uso": "hotelero", "categoria_hotelero": "hotel_3", "tipologia_habitacion": "doble",
    })
    plantas = res["edificio"]["plantas"]
    sociales_pb = [u for u in plantas[0]["unidades"] if u["tipo"] == "zona_social"]
    assert len(sociales_pb) == 1
    assert sociales_pb[0]["area_util_m2"] > 0
    for p in plantas[1:]:
        assert not [u for u in p["unidades"] if u["tipo"] == "zona_social"]


def test_unidades_no_ubicadas_se_serializan():
    # Parcela profunda con fachada corta: el cálculo promete más de lo que la
    # geometría puede ventilar — las unidades sobrantes deben aparecer como
    # no ubicadas, nunca desaparecer.
    poly = [(0, 0), (12, 0), (12, 30), (0, 30)]
    env, cap, params, edif = _escenario_motor(poly)
    d = edificio_dispuesto_a_dict(edif)
    for i, p in enumerate(d["plantas"]):
        reales = _unidades_reales(p)
        assert len(reales) == len(cap.unidades_por_planta[i])
        for u in reales:
            assert isinstance(u["area_util_m2"], float)
            if u["estado"] == "no_ubicada":
                assert u["poligono_util"] == []
                assert u["area_util_m2"] == 0.0


# ─── Contrato del canvas y textos ────────────────────────────────────────────
def test_contrato_canvas_claves_y_tipos():
    res = _calcular()
    ed = res["edificio"]
    assert ed is not None
    assert len(ed["plantas"]) == len(res["envolvente"]["plantas"])
    for p in ed["plantas"]:
        for clave in ("n", "nombre", "tipo", "footprint", "nucleo", "pasillos",
                      "patios", "unidades", "superficies", "incidencias"):
            assert clave in p
        if p["nucleo"] is not None:
            cl = p["nucleo"]["circulo_libre"]
            assert isinstance(cl["centro"], list) and len(cl["centro"]) == 2
            assert isinstance(cl["cumple"], bool)
        for c in p["pasillos"]:
            assert set(c) >= {"poligono", "tipo", "ancho_m", "area_m2"}
        for u in p["unidades"]:
            assert isinstance(u["area_util_m2"], float)
            assert isinstance(u["poligono_construido"], list)
            assert isinstance(u["cumple_minimos"], bool)
            assert isinstance(u["es_adaptada"], bool)


def test_textos_sin_referencias_normativas_literales():
    prohibido = re.compile(r"Anexo|A2\.|Decreto|DB SUA|§")
    for programa in (
        {"uso": "vivienda", "categoria_vivienda": "2d", "pct_local_pb": 20.0},
        {"uso": "hotelero", "categoria_hotelero": "hotel_3", "tipologia_habitacion": "doble"},
    ):
        res = _calcular(payload_programa=programa)
        textos = [a["mensaje"] for a in res["alertas"]]
        textos += [i for p in res["edificio"]["plantas"] for i in p["incidencias"]]
        malos = [t for t in textos if prohibido.search(t)]
        assert not malos, f"textos con referencias literales: {malos}"


# ─── Degradación elegante en el caso de uso ──────────────────────────────────
def test_fallo_geometrico_no_rompe_calcular(monkeypatch):
    import app.contextos.render_calculos.casos_uso as cu

    def revienta(*args, **kwargs):
        raise ValueError("geometría imposible")

    monkeypatch.setattr(cu, "repartir_unidades", revienta)
    res = _calcular()
    assert res["edificio"] is None
    assert res["capacidad"] is not None
    assert any("plano" in a["mensaje"] for a in res["alertas"])


def test_bug_de_programacion_no_se_silencia(monkeypatch):
    import app.contextos.render_calculos.casos_uso as cu

    def revienta(*args, **kwargs):
        raise TypeError("bug")

    monkeypatch.setattr(cu, "repartir_unidades", revienta)
    with pytest.raises(TypeError):
        _calcular()


# ─── Regresión de los hallazgos de la revisión adversarial ───────────────────
def test_ascensor_cabe_completo_en_el_nucleo():
    """Hallazgo crítico: el ascensor (1,60×1,60 = 2,56 m²) no debe quedar
    recortado por una colocación que se sale del bloque de 5,20 m."""
    _, _, _, edif = _escenario_motor([(0, 0), (30, 0), (30, 14), (0, 14)])
    nucleo = next(pl.nucleo for pl in edif.plantas if pl.nucleo is not None)
    assert not nucleo.ascensor.is_empty
    assert nucleo.ascensor.area == pytest.approx(ASCENSOR_AREA, abs=0.15)
    # Escalera y ascensor caben dentro del bloque, sin solaparse.
    assert nucleo.escalera.within(nucleo.geometry.buffer(0.01))
    assert nucleo.ascensor.within(nucleo.geometry.buffer(0.01))
    assert nucleo.escalera.intersection(nucleo.ascensor).area < 0.01


@pytest.mark.parametrize("n_plantas,espera_ascensor", [(1, False), (2, False), (3, True), (5, True)])
def test_ascensor_condicional_al_numero_de_plantas(n_plantas, espera_ascensor):
    """Hallazgo: el ascensor solo es obligatorio a partir de `plantas_para_ascensor`."""
    _, _, _, edif = _escenario_motor([(0, 0), (30, 0), (30, 14), (0, 14)], n_plantas=n_plantas)
    nucleo = next((pl.nucleo for pl in edif.plantas if pl.nucleo is not None), None)
    assert nucleo is not None
    assert (not nucleo.ascensor.is_empty) == espera_ascensor


def test_parcela_triangular_ubica_unidades():
    """Hallazgo: en huellas donde el lado largo del MRR es oblicuo a la fachada,
    el candidato de ángulo de fachada debe rescatar el reparto."""
    _, _, _, edif = _escenario_motor([(0, 0), (30, 0), (15, 20)])
    ubicadas = [u for pl in edif.plantas for u in pl.unidades if u.ubicada]
    total = [u for pl in edif.plantas for u in pl.unidades]
    assert total, "el cálculo debe proponer unidades"
    assert len(ubicadas) >= 0.5 * len(total)


def test_patios_dibujados_cumplen_minimos():
    """Hallazgo: nunca dibujar un patio por debajo de 12 m² / 3 m de luz recta."""
    _, _, params, edif = _escenario_motor(
        [(0, 0), (30, 0), (30, 9.4), (16, 9.4), (16, 13.4), (13.4, 13.4),
         (13.4, 9.4), (0, 9.4)], n_plantas=2,
    )
    area_min = params.diseno.area_patio_min
    luz_min = params.diseno.luz_recta_patio_min
    for pl in edif.plantas:
        for p in pl.patios:
            assert p.area_m2 + 1e-6 >= area_min
            assert p.luz_recta_m + 1e-6 >= luz_min


def test_frente_fachada_no_sobreestima_el_ancho():
    """Hallazgo: `frente_fachada_m` no puede superar el ancho de la unidad
    (sobreestimarlo inflaba el hueco disponible para ventilación)."""
    _, _, _, edif = _escenario_motor([(0, 0), (30, 0), (30, 14), (0, 14)])
    for pl in edif.plantas:
        for u in pl.unidades:
            if u.ubicada and not u.geometry_constr.is_empty:
                b = u.geometry_constr.bounds
                ancho = b[2] - b[0]
                assert u.frente_fachada_m <= ancho + 1e-6


def test_huella_base_vacia_lanza_valueerror():
    """Hallazgo: una huella base vacía debe degradar a ValueError (capturable
    por el caso de uso) en vez de un IndexError → HTTP 500."""
    from app.contextos.render_calculos.geometria.envolvente import Envolvente, Planta

    vacia = Planta(n=0, footprint=Polygon(), interior=Polygon(), tipo="regular")
    env = Envolvente(parcela=Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
                     plantas=[vacia], edificabilidad_consumida=0.0, edificabilidad_max=100.0)
    params = Parametros()
    cap = calcular_capacidad(env, params)
    with pytest.raises(ValueError):
        repartir_unidades(env, [], params, cap)


def test_export_csv_omite_reparto_y_da_mismas_tablas():
    """Hallazgo: `con_reparto=False` salta el plano (rápido) sin alterar las tablas."""
    parcela = _parcela_metrica()
    params = parametros_desde_dict({
        "programa": {"uso": "vivienda", "categoria_vivienda": "2d"},
        "urbanisticos": {"n_plantas_max": 3},
    })
    con = CalcularLayout().ejecutar(parcela, params, con_reparto=True)
    sin = CalcularLayout().ejecutar(parcela, params, con_reparto=False)
    assert con["edificio"] is not None
    assert sin["edificio"] is None
    assert con["tabla_planta"] == sin["tabla_planta"]
    assert con["tabla_unidad"] == sin["tabla_unidad"]
