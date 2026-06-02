"""Macro-layout plurifamiliar (§2.4/§2.5) — varias viviendas por planta.

Copia desde `Modulos/puccetti-app/puccetti/macro_layout.py`. Sin cambios funcionales:
solo imports relativos al paquete `geometria` y eliminación de comentarios
sobre Streamlit (que no aplican aquí).

Pipeline:
1. Frame alineado al lado largo del footprint; entrada en la fachada.
2. Núcleo vertical pegado a la fachada de acceso, sobre el eje del pasillo.
3. Pasillo común recto (ancho ≥ 1.20 m) que conecta el núcleo con todas las unidades.
4. Troceado de la banda(s) de unidades a lo largo del pasillo en N viviendas.
5. Validación por unidad: acceso, ventilación a fachada (A2.5) y mínimos Anexo I.5.
6. Genera N candidatos (4 estrategias × n_seeds) y devuelve el de mayor fitness.
"""
from __future__ import annotations
import math
import random
from dataclasses import dataclass, field
from typing import Literal, Optional

from shapely.geometry import Polygon, MultiPolygon, LineString, MultiLineString, Point, box
from shapely.ops import unary_union
from shapely.affinity import rotate, translate

from .config import Parametros
from .parcelas import LadoParcela
from .envolvente import Planta, Patio
from .programa import programa_vivienda, util_maximo, MIN_COCINA, MIN_BANO
from .capacidad import calcular_capacidad, Capacidad

# ---- dimensiones del núcleo vertical (m) ----
ESCALERA_ANCHO = 2.60
ESCALERA_LARGO = 4.50
ASCENSOR_LADO = 1.60
NUCLEO_LARGO = 5.20
NUCLEO_ANCHO = 4.40

PROF_UNIDAD_MIN = 3.50
ALTURA_HUECO = 1.50

EdgeTipo = Literal["fachada", "medianera"]


@dataclass
class Nucleo:
    geometry: Polygon
    escalera: Polygon
    ascensor: Polygon
    vestibulo: Polygon
    circulo_centro: tuple[float, float]
    circulo_radio: float
    circulo_ok: bool
    area_m2: float


@dataclass
class Pasillo:
    geometry: Polygon
    ancho_m: float
    area_m2: float


@dataclass
class Unidad:
    id: str
    tipo: str
    n_dorms: int
    geometry: Polygon
    geometry_construida: Polygon
    area_util_m2: float
    area_construida_m2: float
    area_min_m2: float
    acceso_pasillo: bool
    borde_pasillo_m: float
    ventilacion_tipo: str
    borde_ventilacion_m: float
    hueco_req_m2: float
    hueco_disp_m2: float
    ventila_ok: bool
    cumple_min: bool
    es_adaptada: bool = False
    incidencias: list[str] = field(default_factory=list)


@dataclass
class PlantaPlurifamiliar:
    n: int
    footprint: Polygon
    interior: Polygon
    nucleo: Optional[Nucleo]
    pasillos: list[Pasillo]
    patios: list[Patio]
    unidades: list[Unidad]
    edges: dict[str, EdgeTipo]
    tipologia: str
    muros_perimetrales: Polygon
    muros_divisorios: Polygon
    construida_m2: float
    util_unidades_m2: float
    circulacion_m2: float
    muros_m2: float
    patios_m2: float
    seed: int = 0
    score: float = 0.0
    score_alternativas: list[float] = field(default_factory=list)
    incidencias: list[str] = field(default_factory=list)


@dataclass
class EdificioPlurifamiliar:
    parcela: Polygon
    plantas: list[PlantaPlurifamiliar]
    edificabilidad_consumida: float
    edificabilidad_max: float
    n_viviendas_total: int
    capacidad: Optional[Capacidad] = None
    viv_por_planta_objetivo: int = 0
    viv_por_planta_dispuestas: int = 0


# ---------------------------------------------------------------------------
#  Helpers de geometría
# ---------------------------------------------------------------------------
def _frame_angulo(footprint: Polygon) -> tuple[float, tuple[float, float]]:
    mrr = footprint.minimum_rotated_rectangle
    coords = list(mrr.exterior.coords)[:-1]
    edges = [(coords[i], coords[(i + 1) % 4]) for i in range(4)]
    elens = [math.dist(a, b) for a, b in edges]
    li = max(range(4), key=lambda i: elens[i])
    a, b = edges[li]
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    return ang, (mrr.centroid.x, mrr.centroid.y)


def _make_transforms(angulo_deg: float, cx: float, cy: float):
    def al(g):
        return rotate(translate(g, xoff=-cx, yoff=-cy), -angulo_deg, origin=(0, 0))

    def mu(g):
        return translate(rotate(g, angulo_deg, origin=(0, 0)), xoff=cx, yoff=cy)

    return al, mu


def _segmentos_por_tipo(lados: list[LadoParcela], al) -> dict[str, MultiLineString]:
    out: dict[str, list[LineString]] = {"fachada": [], "medianera": []}
    for l in lados:
        seg = al(LineString([l.p1, l.p2]))
        out[l.tipo].append(seg)
    return {k: MultiLineString(v) if v else MultiLineString([]) for k, v in out.items()}


def _clasificar_box_edges(
    bounds: tuple[float, float, float, float],
    segs: dict[str, MultiLineString],
    n_muestras: int = 9,
) -> dict[str, EdgeTipo]:
    mnx, mny, mxx, mxy = bounds
    fach = segs["fachada"]
    med = segs["medianera"]

    def lado_de_punto(p: Point) -> EdgeTipo:
        df = p.distance(fach) if not fach.is_empty else math.inf
        dm = p.distance(med) if not med.is_empty else math.inf
        if math.isinf(df) and math.isinf(dm):
            return "fachada"
        return "fachada" if df <= dm else "medianera"

    def vota(puntos: list[Point]) -> EdgeTipo:
        votos = [lado_de_punto(p) for p in puntos]
        return "fachada" if votos.count("fachada") >= votos.count("medianera") else "medianera"

    ts = [i / (n_muestras - 1) for i in range(n_muestras)]
    edges: dict[str, EdgeTipo] = {}
    edges["xmin"] = vota([Point(mnx, mny + t * (mxy - mny)) for t in ts])
    edges["xmax"] = vota([Point(mxx, mny + t * (mxy - mny)) for t in ts])
    edges["ymin"] = vota([Point(mnx + t * (mxx - mnx), mny) for t in ts])
    edges["ymax"] = vota([Point(mnx + t * (mxx - mnx), mxy) for t in ts])
    return edges


def _unidad_min_area(n_dorms: int) -> float:
    prog = programa_vivienda(n_dorms, util_disponible=util_maximo(n_dorms))
    return round(sum(e.area_min_m2 for e in prog) * 1.15, 2)


def _poly_safe(g) -> Polygon:
    if g.is_empty:
        return Polygon()
    if isinstance(g, MultiPolygon):
        return max(g.geoms, key=lambda p: p.area)
    if isinstance(g, Polygon):
        return g
    return Polygon()


# ---------------------------------------------------------------------------
#  Núcleo vertical
# ---------------------------------------------------------------------------
def _construir_nucleo(
    x0: float, yc: float, interior_a: Polygon, params: Parametros,
) -> Optional[Nucleo]:
    Ln, Wn = NUCLEO_LARGO, NUCLEO_ANCHO
    bloque = box(x0, yc - Wn / 2, x0 + Ln, yc + Wn / 2)
    bloque = _poly_safe(bloque.intersection(interior_a))
    if bloque.is_empty or bloque.area < (ESCALERA_ANCHO * ESCALERA_LARGO):
        return None

    bmnx, bmny, bmxx, bmxy = bloque.bounds
    escalera = _poly_safe(box(bmnx, bmny, bmnx + ESCALERA_ANCHO, bmny + ESCALERA_LARGO)
                          .intersection(bloque))
    ascensor = _poly_safe(box(bmnx + ESCALERA_ANCHO + 0.10, bmny,
                              bmnx + ESCALERA_ANCHO + 0.10 + ASCENSOR_LADO,
                              bmny + ASCENSOR_LADO).intersection(bloque))
    vestibulo = _poly_safe(bloque.difference(unary_union([escalera, ascensor])))
    if vestibulo.is_empty:
        return None

    try:
        from shapely.ops import polylabel
        c = polylabel(vestibulo, tolerance=0.05)
    except Exception:
        c = vestibulo.representative_point()
    radio = c.distance(vestibulo.exterior)
    req = params.diseno.diametro_min_vestibulo / 2.0
    return Nucleo(
        geometry=bloque, escalera=escalera, ascensor=ascensor, vestibulo=vestibulo,
        circulo_centro=(c.x, c.y), circulo_radio=radio, circulo_ok=radio + 1e-3 >= req,
        area_m2=bloque.area,
    )


# ---------------------------------------------------------------------------
#  Ventilación y acceso (A2.5)
# ---------------------------------------------------------------------------
def _longitud_contacto(unidad: Polygon, linea, tol: float = 0.35) -> float:
    if linea.is_empty:
        return 0.0
    franja = linea.buffer(tol)
    inter = unidad.boundary.intersection(franja)
    return float(inter.length) if not inter.is_empty else 0.0


def _evaluar_unidad(
    uid: str, geom_util: Polygon, geom_constr: Polygon, n_dorms: int,
    pasillo: Polygon, fach_segments: MultiLineString, patios_a: list[Polygon],
    params: Parametros,
) -> Unidad:
    area_util = geom_util.area
    area_min = _unidad_min_area(n_dorms)

    borde_pas = _longitud_contacto(geom_util, pasillo.boundary, tol=0.30)
    acceso = borde_pas >= params.diseno.radio_apertura_puerta

    tol_fach = params.diseno.espesor_muro_fachada + 0.20
    borde_fach = _longitud_contacto(geom_util, fach_segments, tol=tol_fach)
    patios_union = unary_union(patios_a) if patios_a else None
    borde_patio = (_longitud_contacto(geom_util, patios_union.boundary, tol=0.35)
                   if patios_union is not None and not patios_union.is_empty else 0.0)

    n_banos = 2 if area_util > 70 else 1
    area_servicio = MIN_COCINA + n_banos * MIN_BANO
    area_principal = max(8.0, area_util - area_servicio)
    hueco_req = 0.10 * area_principal
    hueco_disp = borde_fach * ALTURA_HUECO
    ventila_ok = borde_fach > 0.5 and hueco_disp + 1e-3 >= hueco_req

    if ventila_ok:
        vent_tipo = "fachada+patio" if borde_patio > 0.10 else "fachada"
        borde_vent = borde_fach
    elif borde_patio > 0.10:
        vent_tipo, borde_vent = "solo patio (insuf.)", borde_patio
    else:
        vent_tipo, borde_vent = "ninguna", 0.0

    cumple_min = area_util + 1e-3 >= area_min

    incidencias = []
    if not acceso:
        incidencias.append(f"{uid}: sin acceso directo al pasillo común")
    if not ventila_ok:
        if borde_fach <= 0.5 and borde_patio > 0.10:
            incidencias.append(
                f"{uid}: estancias principales sin fachada (A2.5: el patio mínimo "
                f"solo ventila cocina/baños)")
        else:
            incidencias.append(
                f"{uid}: hueco a fachada insuficiente ({hueco_disp:.1f}/{hueco_req:.1f} m²)")
    if not cumple_min:
        incidencias.append(
            f"{uid}: {area_util:.1f} m² útil < mínimo {area_min:.1f} m² ({n_dorms} dorm.)")

    return Unidad(
        id=uid, tipo="vivienda", n_dorms=n_dorms,
        geometry=geom_util, geometry_construida=geom_constr,
        area_util_m2=round(area_util, 2), area_construida_m2=round(geom_constr.area, 2),
        area_min_m2=area_min, acceso_pasillo=acceso, borde_pasillo_m=round(borde_pas, 2),
        ventilacion_tipo=vent_tipo, borde_ventilacion_m=round(borde_vent, 2),
        hueco_req_m2=round(hueco_req, 2), hueco_disp_m2=round(hueco_disp, 2),
        ventila_ok=ventila_ok, cumple_min=cumple_min, incidencias=incidencias,
    )


# ---------------------------------------------------------------------------
#  Generación de un candidato
# ---------------------------------------------------------------------------
def _slice_banda(x0: float, x1: float, y0: float, y1: float, k: int,
                 jitter: float, rng: random.Random) -> list[tuple[float, float, float, float]]:
    if k <= 0 or x1 - x0 < 1.0:
        return []
    cortes = [x0 + (x1 - x0) * i / k for i in range(k + 1)]
    for i in range(1, k):
        cortes[i] += rng.uniform(-jitter, jitter)
    cortes = sorted(min(max(c, x0), x1) for c in cortes)
    return [(cortes[i], y0, cortes[i + 1], y1) for i in range(k)]


def _absorber_resto(
    constr_polys: list[Polygon], comunes: Polygon, interior_a: Polygon,
    min_frag: float = 2.0, tope_area: float | None = None,
) -> list[Polygon]:
    ocup = unary_union([g for g in constr_polys if not g.is_empty] +
                       ([comunes] if not comunes.is_empty else []))
    resto = interior_a.difference(ocup) if not ocup.is_empty else Polygon()
    if resto.is_empty:
        return constr_polys
    piezas = list(resto.geoms) if resto.geom_type == "MultiPolygon" else [resto]
    out = list(constr_polys)
    for fr in piezas:
        if fr.area < min_frag:
            continue
        best_i, best_len = -1, 0.0
        for i, g in enumerate(out):
            if g.is_empty:
                continue
            if tope_area is not None and g.area + fr.area > tope_area:
                continue
            l = fr.boundary.intersection(g.boundary.buffer(0.05)).length
            if l > best_len:
                best_len, best_i = l, i
        if best_i >= 0 and best_len > 0.30:
            out[best_i] = _poly_safe(unary_union([out[best_i], fr]))
    return out


def _generar_candidato(
    planta: Planta, lados: list[LadoParcela], params: Parametros,
    n_viviendas: int, seed: int, rot90: bool = False, tipologia_pref: str = "double",
    forzar_n: bool = False,
) -> PlantaPlurifamiliar:
    rng = random.Random(seed)
    n_dorms = params.programa.n_dormitorios
    cw = params.diseno.ancho_min_pasillo_comun
    esp_div = params.diseno.espesor_separacion_unidades

    footprint = planta.footprint
    espesor_fach = params.diseno.espesor_muro_fachada
    interior_full = _poly_safe(footprint.buffer(-espesor_fach))
    necesita_patio = len(planta.patios) > 0

    ang, (cx, cy) = _frame_angulo(footprint)
    ang_deg = math.degrees(ang) + (90.0 if rot90 else 0.0)
    al, mu = _make_transforms(ang_deg, cx, cy)

    segs = _segmentos_por_tipo(lados, al)
    fp_a = al(footprint)
    bounds = fp_a.bounds
    edges = _clasificar_box_edges(bounds, segs)

    if edges["xmin"] != "fachada" and edges["xmax"] == "fachada":
        ang_deg += 180.0
        al, mu = _make_transforms(ang_deg, cx, cy)
        segs = _segmentos_por_tipo(lados, al)
        fp_a = al(footprint)
        bounds = fp_a.bounds
        edges = _clasificar_box_edges(bounds, segs)

    interior_a = _poly_safe(al(interior_full))
    fach_segments = segs["fachada"]
    mnx, mny, mxx, mxy = bounds
    H = mxy - mny

    yc = (mny + mxy) / 2.0
    nucleo = _construir_nucleo(mnx, yc, interior_a, params)
    x_units0 = mnx + (NUCLEO_LARGO if nucleo is not None else 1.0)

    doble = (tipologia_pref == "double") and H >= (2 * PROF_UNIDAD_MIN + cw)
    tipologia = "double-loaded" if doble else "single-loaded"

    if doble:
        bandas = [(yc + cw / 2, mxy, "ymax"), (mny, yc - cw / 2, "ymin")]
        cor_lo, cor_hi = yc - cw / 2, yc + cw / 2
        pas_geom = box(x_units0, cor_lo, mxx, cor_hi)
    else:
        ymin_fach = edges["ymin"] == "fachada"
        ymax_fach = edges["ymax"] == "fachada"
        if ymax_fach and not ymin_fach:
            pas_y0, pas_y1 = mny, mny + cw
            bandas = [(mny + cw, mxy, "ymax")]
        else:
            pas_y0, pas_y1 = mxy - cw, mxy
            bandas = [(mny, mxy - cw, "ymin")]
        cor_lo, cor_hi = pas_y0, pas_y1
        pas_geom = box(x_units0, pas_y0, mxx, pas_y1)

    pas_geom = _poly_safe(pas_geom.intersection(interior_a))
    if nucleo is not None:
        pas_geom = _poly_safe(unary_union([pas_geom, nucleo.vestibulo]).intersection(
            interior_a.buffer(0)))
        pas_geom = _poly_safe(pas_geom.difference(unary_union([nucleo.escalera, nucleo.ascensor])))

    patios_a: list[Polygon] = []
    if necesita_patio:
        luz = params.diseno.luz_recta_patio_min
        L = max(luz, params.diseno.area_patio_min / luz)
        pcx = min(max((x_units0 + mxx) / 2.0, x_units0 + luz), mxx - luz)
        crece_arriba = (edges["ymax"] == "medianera") or (cor_lo <= mny + 0.05)
        if crece_arriba and (cor_hi + L) <= mxy + 0.5:
            py0, py1 = cor_hi, cor_hi + L
        else:
            py0, py1 = cor_lo - L, cor_lo
        rect = box(pcx - luz / 2, py0, pcx + luz / 2, py1)
        patio_a = _poly_safe(rect.intersection(interior_a))
        if not patio_a.is_empty and patio_a.area >= 0.6 * params.diseno.area_patio_min:
            patios_a = [patio_a]

    util_target = util_maximo(n_dorms)
    area_min_viv = _unidad_min_area(n_dorms)
    UEFIC = 0.88
    util_tope = util_target * 1.25
    slice_max = util_tope / UEFIC
    patios_union = unary_union(patios_a) if patios_a else None

    band_info = []
    for (y0, y1, _lado) in bandas:
        banda = _poly_safe(box(x_units0, y0, mxx, y1).intersection(interior_a))
        if patios_union is not None and not patios_union.is_empty:
            banda = _poly_safe(banda.difference(patios_union))
        band_info.append((y0, y1, banda.area * UEFIC))
    band_info = [b for b in band_info if b[2] >= 0.6 * area_min_viv]
    total_util = sum(b[2] for b in band_info) or 1.0

    rects: list[tuple[float, float, float, float]] = []
    restante = n_viviendas
    for j, (y0, y1, banda_util) in enumerate(band_info):
        if forzar_n and n_viviendas:
            ultimas = j == len(band_info) - 1
            k = restante if ultimas else max(1, round(n_viviendas * banda_util / total_util))
            k = max(1, min(k, restante))
            restante -= k
        else:
            k = max(1, int(banda_util / util_target + 0.5))
            while k > 1 and banda_util / k < area_min_viv:
                k -= 1
            while banda_util / k > util_tope and k < 12:
                k += 1
        jitter = min(1.0, (mxx - x_units0) / max(k, 1) * 0.15)
        rects += _slice_banda(x_units0, mxx, y0, y1, k, jitter, rng)

    quitar = [pas_geom]
    if nucleo is not None:
        quitar.append(nucleo.geometry)
    quitar_union = unary_union([g for g in quitar if not g.is_empty])

    constr_polys: list[Polygon] = []
    for (x0, y0, x1, y1) in rects:
        g = _poly_safe(box(x0, y0, x1, y1).intersection(interior_a))
        if not g.is_empty and not quitar_union.is_empty:
            g = _poly_safe(g.difference(quitar_union))
        if patios_union is not None and not patios_union.is_empty and not g.is_empty:
            g = _poly_safe(g.difference(patios_union))
        constr_polys.append(g)

    comunes_list = [pas_geom]
    if nucleo is not None:
        comunes_list.append(nucleo.geometry)
    if patios_union is not None and not patios_union.is_empty:
        comunes_list.append(patios_union)
    comunes = unary_union([g for g in comunes_list if not g.is_empty])
    constr_polys = _absorber_resto(constr_polys, comunes, interior_a,
                                   tope_area=None if forzar_n else slice_max)

    todas = [g for g in constr_polys if not g.is_empty]
    if nucleo is not None:
        todas = todas + [nucleo.geometry]
    todas = todas + ([pas_geom] if not pas_geom.is_empty else [])
    todas = todas + [p for p in patios_a if not p.is_empty]
    if len(todas) >= 2:
        bordes = unary_union([g.boundary for g in todas])
        muros_div = _poly_safe(bordes.buffer(esp_div / 2).intersection(interior_a))
    else:
        muros_div = Polygon()

    area_min_viv = _unidad_min_area(n_dorms)
    sliver_min = max(8.0, 0.35 * area_min_viv)

    unidades: list[Unidad] = []
    idx = 0
    for g_constr in constr_polys:
        if g_constr.is_empty or g_constr.area < sliver_min:
            continue
        g_util = _poly_safe(g_constr.difference(muros_div)) if not muros_div.is_empty else g_constr
        if g_util.is_empty or g_util.area < sliver_min:
            continue
        idx += 1
        u = _evaluar_unidad(
            f"P{planta.n}-V{idx}", g_util, g_constr, n_dorms,
            pas_geom, fach_segments, patios_a, params,
        )
        u.geometry = mu(g_util)
        u.geometry_construida = mu(g_constr)
        unidades.append(u)

    nucleo_world = None
    if nucleo is not None:
        nucleo_world = Nucleo(
            geometry=mu(nucleo.geometry), escalera=mu(nucleo.escalera),
            ascensor=mu(nucleo.ascensor), vestibulo=mu(nucleo.vestibulo),
            circulo_centro=tuple(mu(Point(nucleo.circulo_centro)).coords[0]),
            circulo_radio=nucleo.circulo_radio, circulo_ok=nucleo.circulo_ok,
            area_m2=nucleo.area_m2,
        )
    pasillo_world = Pasillo(geometry=mu(pas_geom), ancho_m=cw, area_m2=pas_geom.area) \
        if not pas_geom.is_empty else None

    patios_world: list[Patio] = []
    for pa in patios_a:
        if pa.is_empty:
            continue
        b = pa.bounds
        patios_world.append(Patio(
            geometry=mu(pa), area_m2=pa.area,
            luz_recta_m=min(b[2] - b[0], b[3] - b[1]),
        ))

    muros_perim = _poly_safe(footprint.difference(interior_full))
    muros_div_world = mu(muros_div) if not muros_div.is_empty else Polygon()

    util_unidades = sum(u.area_util_m2 for u in unidades)
    circ = (pas_geom.area if not pas_geom.is_empty else 0.0) + \
           (nucleo.area_m2 if nucleo is not None else 0.0)
    patios_area = sum(p.area_m2 for p in patios_world)
    construida = footprint.area
    muros_area = max(0.0, construida - util_unidades - circ - patios_area)

    incidencias = [inc for u in unidades for inc in u.incidencias]
    if nucleo is None:
        incidencias.append(f"P{planta.n}: no cabe núcleo vertical en la huella")
    elif not nucleo.circulo_ok:
        incidencias.append(
            f"P{planta.n}: vestíbulo sin círculo libre Ø"
            f"{params.diseno.diametro_min_vestibulo:.2f} m (radio {nucleo.circulo_radio:.2f})")
    if len(unidades) < n_viviendas:
        incidencias.append(
            f"P{planta.n}: solo caben {len(unidades)} de {n_viviendas} viviendas pedidas")

    return PlantaPlurifamiliar(
        n=planta.n, footprint=footprint, interior=interior_full,
        nucleo=nucleo_world, pasillos=[pasillo_world] if pasillo_world else [],
        patios=patios_world, unidades=unidades, edges=edges, tipologia=tipologia,
        muros_perimetrales=muros_perim, muros_divisorios=muros_div_world,
        construida_m2=round(construida, 2), util_unidades_m2=round(util_unidades, 2),
        circulacion_m2=round(circ, 2), muros_m2=round(muros_area, 2),
        patios_m2=round(patios_area, 2), seed=seed, incidencias=incidencias,
    )


# ---------------------------------------------------------------------------
#  Fitness + selección
# ---------------------------------------------------------------------------
def _score_planta(pl: PlantaPlurifamiliar, n_viviendas: int) -> float:
    if not pl.unidades:
        return 0.0
    n = len(pl.unidades)
    f_min = sum(1 for u in pl.unidades if u.cumple_min) / n
    f_vent = sum(1 for u in pl.unidades if u.ventila_ok) / n
    f_acc = sum(1 for u in pl.unidades if u.acceso_pasillo) / n
    f_count = n / n_viviendas if n_viviendas else 1.0
    f_nucleo = 1.0 if (pl.nucleo is not None and pl.nucleo.circulo_ok) else 0.0
    efic = pl.util_unidades_m2 / pl.construida_m2 if pl.construida_m2 else 0.0
    score = (
        0.22 * f_min + 0.38 * f_vent + 0.12 * f_acc +
        0.08 * min(f_count, 1.0) + 0.10 * f_nucleo + 0.10 * min(efic / 0.72, 1.0)
    )
    return round(100 * score, 1)


def generar_planta_plurifamiliar(
    planta: Planta, lados: list[LadoParcela], params: Parametros,
    n_viviendas: int, seed: int | None = None, n_candidatos: int = 8,
    forzar_n: bool = False,
) -> PlantaPlurifamiliar:
    base = seed if seed is not None else random.randint(0, 10 ** 6)
    estrategias = [(False, "double"), (False, "single"),
                   (True, "double"), (True, "single")]
    n_seeds = max(1, n_candidatos // len(estrategias))
    cands: list[tuple[float, PlantaPlurifamiliar]] = []
    k = 0
    for rot90, tip in estrategias:
        for s in range(n_seeds):
            cand = _generar_candidato(planta, lados, params, n_viviendas,
                                      base + k * 1009, rot90=rot90, tipologia_pref=tip,
                                      forzar_n=forzar_n)
            cand.score = _score_planta(cand, n_viviendas)
            cands.append((cand.score, cand))
            k += 1
    cands.sort(key=lambda t: t[0], reverse=True)
    mejor = cands[0][1]
    mejor.score_alternativas = sorted((s for s, _ in cands), reverse=True)
    return mejor


def _clonar_planta(tipo: PlantaPlurifamiliar, n: int) -> PlantaPlurifamiliar:
    from dataclasses import replace

    def rel(s: str) -> str:
        return s.replace(f"P{tipo.n}-", f"P{n}-").replace(f"P{tipo.n}:", f"P{n}:")

    unis = [replace(u, id=f"P{n}-V{k}", incidencias=[rel(x) for x in u.incidencias])
            for k, u in enumerate(tipo.unidades, start=1)]
    return replace(tipo, n=n, unidades=unis, incidencias=[rel(x) for x in tipo.incidencias])


def _marcar_unidades_adaptadas(
    plantas: list[PlantaPlurifamiliar], pct: float,
) -> None:
    """Marca como adaptadas (DB SUA) un % del total de unidades del edificio.

    Se priorizan las viviendas en planta baja (acceso sin ascensor), después
    las de planta primera. Modifica `u.es_adaptada` en sitio.
    """
    todas: list[Unidad] = [u for pl in plantas for u in pl.unidades]
    if not todas:
        return
    objetivo = max(0, round(len(todas) * pct / 100.0))
    if objetivo == 0:
        return
    todas.sort(key=lambda u: int(u.id.split("-")[0][1:]) if "-" in u.id else 0)
    for u in todas[:objetivo]:
        u.es_adaptada = True


def generar_edificio(
    envolvente, lados: list[LadoParcela], params: Parametros,
    n_viviendas_por_planta: int | None = None,
    seed: int | None = None, n_candidatos: int = 8,
) -> EdificioPlurifamiliar:
    """Pipeline completo §2.4/§2.5 plurifamiliar.

    El nº de viviendas se DERIVA de la edificabilidad (`capacidad.py`) salvo que
    se imponga uno explícito. Genera una planta tipo (la mejor) y la replica en
    todos los niveles.
    """
    cap = calcular_capacidad(envolvente, params)
    if not envolvente.plantas:
        return EdificioPlurifamiliar(
            parcela=envolvente.parcela, plantas=[],
            edificabilidad_consumida=envolvente.edificabilidad_consumida,
            edificabilidad_max=envolvente.edificabilidad_max, n_viviendas_total=0,
            capacidad=cap)
    forzar = n_viviendas_por_planta is not None
    n_viv = max(1, n_viviendas_por_planta if forzar else (cap.viv_por_planta_objetivo or 1))

    tipo = generar_planta_plurifamiliar(
        envolvente.plantas[0], lados, params, n_viv,
        seed=seed, n_candidatos=n_candidatos, forzar_n=forzar)
    plantas = [tipo if n == tipo.n else _clonar_planta(tipo, n)
               for n in range(cap.n_plantas_edificables)]
    _marcar_unidades_adaptadas(plantas, params.programa.pct_unidades_adaptadas)
    consumida = sum(p.construida_m2 for p in plantas)
    return EdificioPlurifamiliar(
        parcela=envolvente.parcela, plantas=plantas,
        edificabilidad_consumida=consumida,
        edificabilidad_max=envolvente.edificabilidad_max,
        n_viviendas_total=sum(len(p.unidades) for p in plantas),
        capacidad=cap,
        viv_por_planta_objetivo=n_viv,
        viv_por_planta_dispuestas=len(tipo.unidades),
    )
