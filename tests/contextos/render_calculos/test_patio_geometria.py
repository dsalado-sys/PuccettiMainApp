"""Patios como secciones geométricas individuales (mover/estirar/girar/reformar).

A diferencia de `test_patio_capacidad` (que mira la SUMA de áreas que descuenta el
motor), aquí se comprueba la geometría: cada patio definido produce su propio polígono
dentro de la planta, con o sin posición explícita (`vertices`), conservando su área
asignada. El invariante de capacidad (deducir la suma de áreas) NO debe moverse.
"""
from __future__ import annotations

import pytest
from shapely.geometry import Polygon, box

from app.contextos.render_calculos.geometria.envolvente import (
    Patio,
    colocar_patios,
    conformar_patio,
    construir_envolvente,
)
from app.contextos.render_calculos.geometria.config import PatioPlacement
from app.contextos.render_calculos.geometria.serializacion import ring
from app.contextos.render_calculos.parametros import (
    ParametrosRender,
    PatioDef,
    parametros_a_dict,
    parametros_desde_dict,
)

PARCELA = box(0.0, 0.0, 40.0, 40.0)   # 1600 m²
AREA = 1600.0


def _render(patios: list[PatioDef], n_plantas: int = 1) -> ParametrosRender:
    p = ParametrosRender()
    p.urbanisticos.patios = list(patios)
    p.urbanisticos.usar_coeficiente_edificabilidad = False
    p.urbanisticos.coeficiente_edificabilidad = 8.0
    p.urbanisticos.n_plantas_max = n_plantas
    p.urbanisticos.retranqueo_fachada_m = 0.0
    p.urbanisticos.retranqueo_linderos_m = 0.0
    return p


def _envolvente(p: ParametrosRender):
    return construir_envolvente(PARCELA, p.a_parametros_motor(), None, superficie_referencia=AREA)


def _regulares(env):
    return [pl for pl in env.plantas if pl.tipo == "regular"]


# ─── 1. Cardinalidad: N patios → N polígonos por planta ──────────────────────
def test_n_patios_generan_n_poligonos_por_planta():
    env = _envolvente(_render([PatioDef(area_m2=12.0), PatioDef(area_m2=15.0)], n_plantas=2))
    regulares = _regulares(env)
    assert len(regulares) == 2
    for pl in regulares:
        assert len(pl.patios) == 2
        assert all(isinstance(pt, Patio) for pt in pl.patios)


# ─── 2. Patio con vértices: respeta el polígono y conserva el área asignada ───
def test_patio_con_vertices_respeta_poligono_y_area():
    verts = [[18.0, 18.0], [22.0, 18.0], [22.0, 22.0], [18.0, 22.0]]  # cuadrado 4×4 = 16 m²
    env = _envolvente(_render([PatioDef(area_m2=16.0, vertices=verts)]))
    pt = _regulares(env)[0].patios[0]
    assert pt.area_m2 == 16.0                                  # área ASIGNADA (invariante)
    assert pt.geometry.area == pytest.approx(16.0, rel=1e-3)   # polígono dibujado
    assert pt.geometry.centroid.x == pytest.approx(20.0, abs=0.1)
    assert pt.geometry.centroid.y == pytest.approx(20.0, abs=0.1)


# ─── 2b. Área fija: un polígono cuya superficie ≠ la asignada se reescala ─────
def test_area_fija_reescala_poligono_a_la_asignada():
    # Cuadrado dibujado de 16 m² pero con área asignada 36 → se reescala (centroide
    # fijo) hasta 36 m². Es la regla «área fija» (editar m² redimensiona la forma).
    verts = [[18.0, 18.0], [22.0, 18.0], [22.0, 22.0], [18.0, 22.0]]  # 16 m², centro (20,20)
    env = _envolvente(_render([PatioDef(area_m2=36.0, vertices=verts)]))
    pt = _regulares(env)[0].patios[0]
    assert pt.area_m2 == 36.0
    assert pt.geometry.area == pytest.approx(36.0, rel=1e-3)
    assert pt.geometry.centroid.x == pytest.approx(20.0, abs=0.1)  # centroide preservado
    assert pt.geometry.centroid.y == pytest.approx(20.0, abs=0.1)


# ─── 3. Auto-place: área exacta, dentro de la planta, sin solape entre patios ─
def test_auto_place_area_exacta_y_sin_solape():
    env = _envolvente(_render([PatioDef(area_m2=20.0), PatioDef(area_m2=8.0)]))
    pl = _regulares(env)[0]
    p0, p1 = pl.patios
    assert p0.area_m2 == 20.0 and p1.area_m2 == 8.0
    assert p0.geometry.area == pytest.approx(20.0, rel=1e-3)
    assert p1.geometry.area == pytest.approx(8.0, rel=1e-3)
    # Auto-colocados dentro de la huella y sin solaparse entre sí.
    assert pl.footprint.buffer(1e-6).contains(p0.geometry.centroid)
    assert pl.footprint.buffer(1e-6).contains(p1.geometry.centroid)
    assert p0.geometry.intersection(p1.geometry).area < 1e-6


# ─── 4. Invariante de capacidad: la suma de áreas no se mueve ────────────────
def test_capacidad_deduce_la_suma_de_areas():
    motor = _render([PatioDef(area_m2=10.0), PatioDef(area_m2=8.0)]).a_parametros_motor()
    assert motor.diseno.area_patio_min == 18.0
    assert len(motor.patios) == 2
    assert all(isinstance(pp, PatioPlacement) for pp in motor.patios)
    assert {round(pp.area_m2, 1) for pp in motor.patios} == {10.0, 8.0}


# ─── 5. Compat: lista de floats desnudos sigue siendo válida (auto-place) ────
def test_compat_float_desnudo():
    p = parametros_desde_dict({"urbanisticos": {"patios": [12.0, 8.0]}})
    assert all(isinstance(pd, PatioDef) for pd in p.urbanisticos.patios)
    assert [pd.area_m2 for pd in p.urbanisticos.patios] == [12.0, 8.0]
    assert all(pd.vertices is None for pd in p.urbanisticos.patios)
    # Y se dibujan (auto-place) en la envolvente.
    env = _envolvente(p)
    assert len(_regulares(env)[0].patios) == 2


# ─── 6. Round-trip de un patio con polígono libre + id ───────────────────────
def test_round_trip_vertices_e_id():
    verts = [[18.0, 18.0], [22.0, 18.0], [22.0, 22.0], [18.0, 22.0]]
    p = ParametrosRender()
    p.urbanisticos.patios = [PatioDef(area_m2=16.0, id="patio01", vertices=verts)]
    p2 = parametros_desde_dict(parametros_a_dict(p))
    pd = p2.urbanisticos.patios[0]
    assert pd.id == "patio01"
    assert pd.area_m2 == 16.0
    assert pd.vertices == verts


# ─── 7. id estable: se autogenera y sobrevive al round-trip ──────────────────
def test_id_estable_se_genera_y_persiste():
    pd = PatioDef(area_m2=12.0)
    assert pd.id and len(pd.id) >= 4          # autogenerado en __post_init__
    p = ParametrosRender()
    p.urbanisticos.patios = [pd]
    p2 = parametros_desde_dict(parametros_a_dict(p))
    assert p2.urbanisticos.patios[0].id == pd.id


# ─── 8. colocar_patios sin lista → heurística histórica de patio único ───────
def test_sin_lista_cae_a_patio_unico_historico():
    interior = box(0.0, 0.0, 30.0, 30.0)
    params = _render([]).a_parametros_motor()   # patios=[] → motor.patios vacío
    patios = colocar_patios(interior, params)
    # Sin definiciones, el motor reproduce el patio único auto-detectado de siempre.
    assert len(patios) <= 1


# ════════════════════════════════════════════════════════════════════════════
# Adaptación al borde (plegado): base ideal vs efectiva conformada al contorno.
# ════════════════════════════════════════════════════════════════════════════
FOOT = box(0.0, 0.0, 40.0, 40.0)


def _motor(patios: list[PatioDef]):
    return _render(patios).a_parametros_motor()


def _n_vertices(poly) -> int:
    return len(poly.exterior.coords)


# ─── 9. Base entera dentro → efectiva == base (sin vértices temporales) ───────
def test_conform_base_dentro_es_identidad():
    verts = [[16.0, 16.0], [24.0, 16.0], [24.0, 24.0], [16.0, 24.0]]  # 64→ reescala a 16 (lado 4)
    p = colocar_patios(FOOT, _motor([PatioDef(area_m2=16.0, vertices=verts)]), footprint=FOOT)[0]
    assert p.cabe is True
    assert p.area_efectiva_m2 == pytest.approx(16.0, rel=1e-3)
    assert p.geometry.area == pytest.approx(16.0, rel=1e-3)
    # Sin recorte/inflado: misma cantidad de vértices que la base (no temporales).
    assert _n_vertices(p.geometry) == _n_vertices(p.base)


# ─── 10. Asoma fuera → recorta + rellena hacia dentro, conserva el área ───────
def test_conform_asoma_fuera_se_adapta_y_conserva_area():
    verts = [[36.0, 17.0], [42.0, 17.0], [42.0, 23.0], [36.0, 23.0]]  # 6×6=36, sale a x=42 (>40)
    p = colocar_patios(FOOT, _motor([PatioDef(area_m2=36.0, vertices=verts)]), footprint=FOOT)[0]
    assert p.cabe is True
    assert p.area_efectiva_m2 == pytest.approx(36.0, rel=2e-2)
    assert not FOOT.contains(p.base)                 # la base sí sobresale
    assert FOOT.buffer(1e-6).contains(p.geometry)    # la efectiva queda dentro
    assert not p.geometry.equals(p.base)             # se ha adaptado (deslizado hacia dentro)


# ─── 10b. Borde diagonal → se adapta al contorno conservando el área ─────────
def test_conform_borde_diagonal_se_adapta():
    triangulo = Polygon([(0.0, 0.0), (40.0, 0.0), (0.0, 40.0)])   # hipotenusa x+y=40
    verts = [[15.0, 15.0], [25.0, 15.0], [25.0, 25.0], [15.0, 25.0]]  # straddle de la diagonal
    p = colocar_patios(triangulo, _motor([PatioDef(area_m2=50.0, vertices=verts)]),
                       footprint=triangulo)[0]
    assert p.cabe is True
    assert p.area_efectiva_m2 == pytest.approx(50.0, rel=2e-2)  # área conservada
    assert triangulo.buffer(1e-6).contains(p.geometry)         # dentro, pegado a la diagonal
    assert not p.geometry.equals(p.base)                       # se ha adaptado al borde


# ─── 11. No cabe → cabe=False y área efectiva < asignada ─────────────────────
def test_conform_no_cabe_marca_aviso():
    small = box(0.0, 0.0, 5.0, 5.0)   # 25 m² de zona
    p = colocar_patios(small, _motor([PatioDef(area_m2=40.0)]), footprint=small)[0]
    assert p.cabe is False
    assert p.area_efectiva_m2 < 40.0
    assert p.area_efectiva_m2 <= 25.0 + 0.01            # como mucho, toda la zona
    assert p.area_efectiva_m2 > 15.0                    # pero rellena la mayor parte


# ─── 12. Prioridad por orden: el posterior cede ante el anterior ─────────────
def test_conform_evita_otro_patio():
    # Prioridad por orden de lista: el ANTERIOR (índice 0) conserva su base; el POSTERIOR
    # (índice 1) es el único que se adapta para no invadirlo. Las efectivas no se pisan.
    v1 = [[16.0, 16.0], [24.0, 16.0], [24.0, 24.0], [16.0, 24.0]]   # 64→ 30 centrado (20,20)
    v2 = [[20.0, 20.0], [28.0, 20.0], [28.0, 28.0], [20.0, 28.0]]   # 64→ 30 centrado (24,24), solapa v1
    a, b = colocar_patios(FOOT, _motor([
        PatioDef(area_m2=30.0, vertices=v1), PatioDef(area_m2=30.0, vertices=v2),
    ]), footprint=FOOT)
    assert a.geometry.equals(a.base)                       # el anterior queda intacto
    assert b.geometry.intersection(a.base).area < 0.5      # el posterior esquiva al anterior
    assert a.geometry.intersection(b.geometry).area < 0.5  # las efectivas no se pisan
    assert a.area_efectiva_m2 == pytest.approx(30.0, rel=0.05)
    assert b.area_efectiva_m2 == pytest.approx(30.0, rel=0.05)


# ─── 12b. Arrastrar un patio sobre otro solo adapta el movido (último) ────────
def test_prioridad_solo_el_ultimo_patio_se_adapta():
    # Reproduce el caso del editor: dos patios ya disjuntos + un tercero que el usuario
    # arrastra encima del primero. El frontend coloca el patio movido el ÚLTIMO, así que
    # solo él debe ceder; los dos anteriores deben quedar EXACTAMENTE donde estaban.
    base_a = [[5.0, 5.0], [15.0, 5.0], [15.0, 15.0], [5.0, 15.0]]      # 100→30 centrado (10,10)
    base_b = [[25.0, 25.0], [35.0, 25.0], [35.0, 35.0], [25.0, 35.0]]  # 100→30 centrado (30,30), lejos de A
    encima = [[6.0, 6.0], [16.0, 6.0], [16.0, 16.0], [6.0, 16.0]]      # 100→30 centrado (11,11), solapa A
    a, b, c = colocar_patios(FOOT, _motor([
        PatioDef(area_m2=30.0, vertices=base_a),
        PatioDef(area_m2=30.0, vertices=base_b),
        PatioDef(area_m2=30.0, vertices=encima),
    ]), footprint=FOOT)
    # Los anteriores (A y B) quedan intactos: efectiva == base.
    assert a.geometry.equals(a.base)
    assert b.geometry.equals(b.base)
    # El último (el "movido") es el único que se adapta: evita las bases anteriores
    # y no se pisa con sus efectivas, conservando su área.
    assert c.geometry.intersection(a.base).area < 0.5
    assert c.geometry.intersection(a.geometry).area < 0.5
    assert c.geometry.intersection(b.geometry).area < 0.5
    assert c.area_efectiva_m2 == pytest.approx(30.0, rel=0.05)
    assert c.cabe is True
    # Anclado: rellena el hueco local junto a donde se soltó (~11,11), no salta al centro.
    assert c.geometry.centroid.x == pytest.approx(12.0, abs=2.5)
    assert c.geometry.centroid.y == pytest.approx(12.0, abs=2.5)


# ─── 13. Resultado siempre de UNA pieza (Polygon, nunca MultiPolygon) ────────
def test_conform_siempre_una_pieza():
    verts = [[36.0, 10.0], [44.0, 10.0], [44.0, 30.0], [36.0, 30.0]]  # franja que sale por la derecha
    p = colocar_patios(FOOT, _motor([PatioDef(area_m2=80.0, vertices=verts)]), footprint=FOOT)[0]
    assert p.geometry.geom_type == "Polygon"   # nunca multipolígono
    assert FOOT.buffer(1e-6).contains(p.geometry)


# ─── 14. conformar_patio: base ya contenida → identidad exacta ───────────────
def test_conformar_patio_identidad_si_contenido():
    base = box(10.0, 10.0, 20.0, 20.0)        # 100 m², dentro de FOOT
    efectiva, area_ef, cabe = conformar_patio(base, FOOT, 100.0, 3.0)
    assert cabe is True
    assert area_ef == pytest.approx(100.0, rel=1e-9)
    assert efectiva.equals(base)


# ─── 15. Hueco muerto demasiado pequeño: se queda ahí y avisa, NO se reubica ──
def test_conform_hueco_muerto_no_teletransporta():
    # Un vecino (prioridad alta) ocupa la mitad derecha salvo un BOLSILLO sin salida de
    # 5×5=25 m² en la esquina superior-derecha. El usuario suelta ahí un patio de 40 m².
    # No cabe → rellena el bolsillo al máximo (~25), se queda ANCLADO en la esquina y
    # cabe=False. NUNCA salta al polo del gran área libre de la izquierda (~10,20).
    vecino = [[20.0, 0.0], [40.0, 0.0], [40.0, 35.0], [35.0, 35.0],
              [35.0, 40.0], [20.0, 40.0]]                       # área cruda = 775 (800 − bolsillo 25)
    drop = [[34.0, 34.0], [41.0, 34.0], [41.0, 41.0], [34.0, 41.0]]   # cae en el bolsillo
    a, b = colocar_patios(FOOT, _motor([
        PatioDef(area_m2=775.0, vertices=vecino),   # area == cruda → _ajustar_area no lo reescala
                                                    # (si no, se encoge y abre rendijas: el bolsillo
                                                    # dejaría de ser un fondo de saco)
        PatioDef(area_m2=40.0, vertices=drop),      # patio movido (último, el que cede)
    ]), footprint=FOOT)
    assert b.cabe is False
    assert b.area_efectiva_m2 < 40.0
    assert b.area_efectiva_m2 == pytest.approx(25.0, abs=3.0)
    cx, cy = b.geometry.centroid.x, b.geometry.centroid.y
    assert cx == pytest.approx(37.5, abs=2.5) and cy == pytest.approx(37.5, abs=2.5)  # en el bolsillo
    assert ((cx - 20.0) ** 2 + (cy - 20.0) ** 2) ** 0.5 > 15.0   # lejos del centro/polo libre
    assert b.geometry.geom_type == "Polygon"
    assert FOOT.buffer(1e-6).contains(b.geometry)


# ─── 16. «Adaptar»: adoptar la efectiva serializada + (área efectiva − margen) re-encaja ─
def test_adaptar_reencaja_con_area_efectiva_menos_margen():
    # Invariante en que se apoya el botón «Adaptar» del frontend: tras un patio que NO cabe,
    # adoptar su forma EFECTIVA tal como la serializa el backend (ring(): exterior + simplify
    # + redondeo a cm — puede descartar agujeros y desplazar el borde) con su área efectiva
    # MENOS un pequeño margen (0,05 m², = MARGEN_ADAPTAR_M2 en render_calculos.js) vuelve a
    # caber. Pedir el área efectiva EXACTA puede quedar un pelo por encima y re-avisar.
    diamante = [[20.0, 8.0], [32.0, 20.0], [20.0, 32.0], [8.0, 20.0]]   # vecino (prioridad alta)
    grande = [[12.0, 12.0], [28.0, 12.0], [28.0, 28.0], [12.0, 28.0]]   # pide 1400 → no cabe
    a, b = colocar_patios(FOOT, _motor([
        PatioDef(area_m2=288.0, vertices=diamante),
        PatioDef(area_m2=1400.0, vertices=grande),
    ]), footprint=FOOT)
    assert b.cabe is False
    poligono = ring(b.geometry)                   # exactamente lo que recibe el frontend (p.poligono)
    objetivo = round(b.geometry.area, 2) - 0.05   # p.area_efectiva_m2 − MARGEN_ADAPTAR_M2
    a2, b2 = colocar_patios(FOOT, _motor([
        PatioDef(area_m2=288.0, vertices=diamante),
        PatioDef(area_m2=objetivo, vertices=poligono),
    ]), footprint=FOOT)
    assert b2.cabe is True
    assert b2.area_efectiva_m2 == pytest.approx(objetivo, rel=0.02)
