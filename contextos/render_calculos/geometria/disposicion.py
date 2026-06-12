"""Autodistribución del cálculo sobre el lienzo (§2.4 + §2.5 + Anexo II).

Toma los m² que produce el cálculo de capacidad (`calcular_capacidad`) — unidades
por planta, muros, circulación, núcleo, patio y local — y los **reparte como
piezas coloreadas dentro de la huella de cada planta**, respetando los criterios
del Anexo II. Es el motor que materializa el mandato del módulo: *«dibujar lo que
dice el cálculo, no lo que la geometría puede acomodar»* (ver el comentario de
deprecación de `macro_layout.py`).

Diferencia clave con `macro_layout.py` (geometry-driven, deprecado): aquí las
**áreas son el dato de entrada** y la geometría se dimensiona para **cuadrar con
ellas** (partición exacta de la huella), no al revés. La suma de cada categoría
pintada = su m² calculado (±tolerancia de bisección).

Funciones puras (Shapely), sin FastAPI ni persistencia. Todas las coordenadas en
metros UTM30N (mismo mundo que `ParcelaMetrica.poligono_utm` y el lienzo).

Esquema de una planta de vivienda (Anexo II A2.1/A2.2/A2.4/A2.5):

    ┌───── muro fachada / medianera (banda perimetral = muros_m2) ─────┐
    │ ┌─────┐  ┌────────── banda superior (unidades + patio) ───────┐  │
    │ │     │  │  V1   │  V2   │  V3   │            │   PATIO       │  │
    │ │ NÚ- │  ├───────┴───────┴───────┴────────────┴───────────────┤  │
    │ │ CLEO│  │░░░░░░░ CIRCULACIÓN (pasillo ≥ 1,20 m) ░░░░░░░░░░░░░░│  │
    │ │     │  ├───────┬───────┬───────┬────────────┬───────────────┤  │
    │ └─────┘  │  V4   │  V5   │  V6   │            │   LOCAL (PB)  │  │
    │          └──────────── banda inferior (unidades + local) ─────┘  │
    └─────────────────────────────────────────────────────────────────┘

- El núcleo se pega a una fachada (acceso) y se comprueba que inscribe Ø1,50 m
  libre (vestíbulo de giro, A2.1).
- El pasillo común central conecta el núcleo con todas las unidades; se avisa si
  su ancho cae por debajo del mínimo (A2.1/§2.6).
- El patio respeta luz recta mínima (A2.5); se avisa si no llega.
- Las unidades tocan el pasillo (acceso) y el muro de fachada (ventilación); se
  avisa si una banda da a medianera sin patio (A2.5: el patio mínimo no ventila
  estancias principales).

Si el esquema estructurado no encaja (planta muy pequeña, sótano, sin unidades…)
se cae a una partición *treemap* (slice-and-dice) que mantiene las áreas exactas
aunque sea menos arquitectónica, y se deja constancia en las incidencias.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from shapely.geometry import (
    LineString,
    MultiLineString,
    Point,
    Polygon,
    box,
)
from shapely.affinity import rotate, translate

from .config import Parametros
from .parcelas import LadoParcela

# ─── Paleta por categoría (corporativa Puccetti + paleta del lienzo) ────────
COLORES: dict[str, str] = {
    "unidad": "#2E9E5B",       # verde — unidades de alojamiento (viviendas)
    "circulacion": "#C9A84C",  # dorado claro — pasillos comunes
    "nucleo": "#B8960C",       # dorado — núcleo de comunicación vertical
    "patio": "#2D6CDF",        # azul — patio interior (vacío/luz)
    "local": "#F2C200",        # amarillo — local no residencial (PB)
    "muro": "#0A0A0A",         # negro corporativo — muros
    "resto": "#8A8A8A",        # gris — superficie libre / sótano
}

EdgeTipo = Literal["fachada", "medianera"]


# ─── Contrato de entrada/salida ─────────────────────────────────────────────
@dataclass(frozen=True)
class ObjetivoPlanta:
    """m² objetivo de una planta (los que dice `calcular_capacidad`) + su huella.

    Identidad que mantiene el cálculo: `footprint.area ≈ muros + circulacion +
    nucleo + patio + local + util`. `unidades` reparte `util` en piezas concretas;
    su suma puede ser ≤ `util_m2` (sobrante de truncar), que se absorbe escalando.
    """
    nombre: str                       # "PB", "P1", "Ático", "S1"
    tipo: str                         # "regular" | "atico" | "sotano"
    footprint: Polygon                # huella en UTM30N
    unidades: list[tuple[str, float]] # [(etiqueta, util_m2), ...]
    muros_m2: float
    circulacion_m2: float
    nucleo_m2: float
    patio_m2: float
    local_m2: float
    util_m2: float


@dataclass(frozen=True)
class PiezaDispuesta:
    """Una pieza lista para el lienzo (superficie coloreada)."""
    nombre: str
    categoria: str                    # unidad|circulacion|nucleo|patio|local|muro|resto
    color: str
    vertices: list[list[float]]       # anillo exterior abierto, UTM30N, redondeado a cm


@dataclass
class ResultadoPlanta:
    piezas: list[PiezaDispuesta] = field(default_factory=list)
    incidencias: list[str] = field(default_factory=list)
    areas: dict[str, float] = field(default_factory=dict)


# ─── Helpers de geometría (puros) ───────────────────────────────────────────
def _poly_safe(g: Any) -> Polygon:
    """Devuelve un Polygon válido (la pieza mayor si es Multi); Polygon() si nada."""
    if g is None or g.is_empty:
        return Polygon()
    if not g.is_valid:
        g = g.buffer(0)
    if g.is_empty:
        return Polygon()
    if g.geom_type == "MultiPolygon":
        return max(g.geoms, key=lambda p: p.area)
    if g.geom_type == "Polygon":
        return g
    return Polygon()


def _frame_angulo(footprint: Polygon) -> tuple[float, tuple[float, float]]:
    """Ángulo del lado más largo del rectángulo rotado mínimo + su centroide."""
    mrr = footprint.minimum_rotated_rectangle
    if mrr.geom_type != "Polygon":
        c = footprint.centroid
        return 0.0, (c.x, c.y)
    coords = list(mrr.exterior.coords)[:-1]
    edges = [(coords[i], coords[(i + 1) % 4]) for i in range(4)]
    elens = [math.dist(a, b) for a, b in edges]
    li = max(range(4), key=lambda i: elens[i])
    a, b = edges[li]
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    return ang, (mrr.centroid.x, mrr.centroid.y)


def _make_transforms(angulo_deg: float, cx: float, cy: float):
    """Devuelve (al, mu): mundo→local (eje largo horizontal) y su inverso."""
    def al(g):
        return rotate(translate(g, xoff=-cx, yoff=-cy), -angulo_deg, origin=(0, 0))

    def mu(g):
        return translate(rotate(g, angulo_deg, origin=(0, 0)), xoff=cx, yoff=cy)

    return al, mu


def _segmentos_por_tipo(lados: list[LadoParcela], al) -> dict[str, MultiLineString]:
    """Segmentos de los lados de la parcela, en frame local, agrupados por tipo."""
    out: dict[str, list[LineString]] = {"fachada": [], "medianera": []}
    for l in lados:
        out.get(l.tipo, out["fachada"]).append(al(LineString([l.p1, l.p2])))
    return {k: MultiLineString(v) if v else MultiLineString([]) for k, v in out.items()}


def _clasificar_box_edges(
    bounds: tuple[float, float, float, float],
    segs: dict[str, MultiLineString],
    n: int = 9,
) -> dict[str, EdgeTipo]:
    """Clasifica cada lado del bbox local (xmin/xmax/ymin/ymax) como fachada/medianera.

    Vota por cercanía a los segmentos fachada vs. medianera de la parcela. Sin
    medianeras → todo fachada (el técnico puede reclasificar desde §2.1).
    """
    mnx, mny, mxx, mxy = bounds
    fach, med = segs["fachada"], segs["medianera"]

    def lado_de(p: Point) -> EdgeTipo:
        df = p.distance(fach) if not fach.is_empty else math.inf
        dm = p.distance(med) if not med.is_empty else math.inf
        if math.isinf(df) and math.isinf(dm):
            return "fachada"
        return "fachada" if df <= dm else "medianera"

    def vota(pts: list[Point]) -> EdgeTipo:
        v = [lado_de(p) for p in pts]
        return "fachada" if v.count("fachada") >= v.count("medianera") else "medianera"

    ts = [i / (n - 1) for i in range(n)]
    return {
        "xmin": vota([Point(mnx, mny + t * (mxy - mny)) for t in ts]),
        "xmax": vota([Point(mxx, mny + t * (mxy - mny)) for t in ts]),
        "ymin": vota([Point(mnx + t * (mxx - mnx), mny) for t in ts]),
        "ymax": vota([Point(mnx + t * (mxx - mnx), mxy) for t in ts]),
    }


def _radio_inscrito(poly: Polygon) -> float:
    """Radio del mayor círculo inscrito (polo de inaccesibilidad)."""
    poly = _poly_safe(poly)
    if poly.is_empty:
        return 0.0
    try:
        from shapely.ops import polylabel
        c = polylabel(poly, tolerance=0.05)
    except Exception:
        c = poly.representative_point()
    return float(c.distance(poly.exterior))


# ─── Cortes por área exacta (bisección, robustos en huellas cóncavas) ───────
def _franja_v(region: Polygon, x0: float, x1: float) -> Polygon:
    b = region.bounds
    return _poly_safe(region.intersection(box(x0, b[1] - 1.0, x1, b[3] + 1.0)))


def _franja_h(region: Polygon, y0: float, y1: float) -> Polygon:
    b = region.bounds
    return _poly_safe(region.intersection(box(b[0] - 1.0, y0, b[2] + 1.0, y1)))


def _cortar_v(region: Polygon, x_lo: float, x_hi: float, area_obj: float) -> float:
    """x donde la parte izquierda (x≤c) de `region` alcanza `area_obj` (bisección)."""
    if area_obj <= 0:
        return x_lo
    if area_obj >= region.area:
        return x_hi
    b = region.bounds
    lo, hi = x_lo, x_hi
    for _ in range(40):
        mid = (lo + hi) / 2.0
        a = region.intersection(box(b[0] - 1.0, b[1] - 1.0, mid, b[3] + 1.0)).area
        if a < area_obj:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _cortar_h(region: Polygon, y_lo: float, y_hi: float, area_obj: float) -> float:
    """y donde la parte inferior (y≤c) de `region` alcanza `area_obj` (bisección)."""
    if area_obj <= 0:
        return y_lo
    if area_obj >= region.area:
        return y_hi
    b = region.bounds
    lo, hi = y_lo, y_hi
    for _ in range(40):
        mid = (lo + hi) / 2.0
        a = region.intersection(box(b[0] - 1.0, b[1] - 1.0, b[2] + 1.0, mid)).area
        if a < area_obj:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ─── Muros: banda perimetral dimensionada a `muros_m2` ──────────────────────
def _resolver_grosor_muros(fp_a: Polygon, bnds, muros_obj: float) -> float:
    """Grosor `t` de la banda perimetral tal que su área = `muros_obj` (bisección).

    La banda = huella − rectángulo interior reducido `t` por cada lado. Su área
    crece monótona con `t`, así que la bisección converge.
    """
    mnx, mny, mxx, mxy = bnds
    A = fp_a.area
    if muros_obj <= 0 or A <= 0:
        return 0.0
    tmax = min(mxx - mnx, mxy - mny) * 0.45
    lo, hi = 0.0, tmax
    for _ in range(40):
        t = (lo + hi) / 2.0
        inner = fp_a.intersection(box(mnx + t, mny + t, mxx - t, mxy - t)).area
        band = A - inner
        if band < muros_obj:
            lo = t
        else:
            hi = t
    return (lo + hi) / 2.0


def _muros_strips(fp_a: Polygon, bnds, t: float, edges: dict[str, EdgeTipo],
                  placed: list[tuple[dict, Any]]) -> None:
    """Descompone la banda perimetral en 4 tiras (esquinas a izquierda/derecha).

    Cada tira se etiqueta fachada/medianera (A2.4: huecos solo en fachada). Las
    tiras no se solapan: top/bottom van de `mnx+t` a `mxx-t`; las esquinas caen en
    left/right. Para huellas cóncavas la tira puede partirse (se emiten varias).
    """
    if t <= 1e-6:
        return
    mnx, mny, mxx, mxy = bnds
    tiras = [
        (edges["xmin"], box(mnx, mny, mnx + t, mxy)),
        (edges["xmax"], box(mxx - t, mny, mxx, mxy)),
        (edges["ymin"], box(mnx + t, mny, mxx - t, mny + t)),
        (edges["ymax"], box(mnx + t, mxy - t, mxx - t, mxy)),
    ]
    for tipo, bx in tiras:
        g = fp_a.intersection(bx)
        if g.is_empty or g.area < 1e-3:
            continue
        nombre = "Muro fachada" if tipo == "fachada" else "Muro medianera"
        placed.append(({"nombre": nombre, "categoria": "muro"}, g))


# ─── Treemap slice-and-dice (fallback robusto, áreas exactas) ───────────────
def _treemap(region: Polygon, items: list[dict]) -> list[tuple[dict, Polygon]]:
    """Parte `region` en piezas con las áreas de `items` (orden preservado)."""
    out: list[tuple[dict, Polygon]] = []

    def rec(reg: Polygon, its: list[dict]) -> None:
        reg = _poly_safe(reg)
        if reg.is_empty or reg.area < 1e-6 or not its:
            return
        if len(its) == 1:
            out.append((its[0], reg))
            return
        total = sum(i["area"] for i in its) or 1.0
        half = total / 2.0
        acc, k = 0.0, 1
        for idx, i in enumerate(its):
            acc += i["area"]
            if acc >= half:
                k = idx + 1
                break
        k = max(1, min(k, len(its) - 1))
        g1, g2 = its[:k], its[k:]
        a1 = sum(i["area"] for i in g1)
        b = reg.bounds
        if (b[2] - b[0]) >= (b[3] - b[1]):
            xc = _cortar_v(reg, b[0], b[2], a1)
            rec(_franja_v(reg, b[0], xc), g1)
            rec(_franja_v(reg, xc, b[2]), g2)
        else:
            yc = _cortar_h(reg, b[1], b[3], a1)
            rec(_franja_h(reg, b[1], yc), g1)
            rec(_franja_h(reg, yc, b[3]), g2)

    rec(region, list(items))
    return out


def _items_categorias(obj: ObjetivoPlanta, area_destino: float) -> list[dict]:
    """Lista de bloques por categoría escalada a `area_destino` (cuadre exacto)."""
    base: list[dict] = []
    if obj.nucleo_m2 > 0:
        base.append({"nombre": "Núcleo", "categoria": "nucleo", "area": obj.nucleo_m2})
    if obj.circulacion_m2 > 0:
        base.append({"nombre": "Circulación", "categoria": "circulacion", "area": obj.circulacion_m2})
    if obj.patio_m2 > 0:
        base.append({"nombre": "Patio", "categoria": "patio", "area": obj.patio_m2})
    if obj.local_m2 > 0:
        base.append({"nombre": "Local", "categoria": "local", "area": obj.local_m2})
    for etiqueta, u in obj.unidades:
        if u > 0:
            base.append({"nombre": etiqueta, "categoria": "unidad", "area": u})
    suma = sum(i["area"] for i in base)
    resto = area_destino - suma
    if resto > 0.5:
        nombre = "Sótano" if obj.tipo == "sotano" else "Sup. libre"
        base.append({"nombre": nombre, "categoria": "resto", "area": resto})
        suma += resto
    if suma > 0 and abs(suma - area_destino) > 1e-6:
        k = area_destino / suma
        for i in base:
            i["area"] *= k
    return base


# ─── Esquema estructurado de vivienda (Anexo II) ────────────────────────────
def _slice_unidades(region: Polygon, unidades: list[tuple[str, float]],
                    placed: list[tuple[dict, Any]]) -> None:
    """Trocea `region` en una pieza por unidad (cortes verticales por área)."""
    region = _poly_safe(region)
    unidades = [(n, u) for n, u in unidades if u > 0]
    if region.is_empty or not unidades:
        return
    reg = region
    for i, (nombre, u) in enumerate(unidades):
        if i == len(unidades) - 1:
            pieza = reg
        else:
            b = reg.bounds
            xc = _cortar_v(reg, b[0], b[2], u)
            pieza = _franja_v(reg, b[0], xc)
            reg = _franja_v(reg, xc, b[2])
        if not pieza.is_empty and pieza.area > 1e-3:
            placed.append(({"nombre": nombre, "categoria": "unidad"}, pieza))


def _colocar_patio_o_local(reg_extra: Polygon, extra_cat: str, extra_nombre: str,
                           pm: Parametros, obj: ObjetivoPlanta, incid: list[str],
                           placed: list[tuple[dict, Any]]) -> None:
    reg_extra = _poly_safe(reg_extra)
    if reg_extra.is_empty or reg_extra.area < 1e-3:
        return
    placed.append(({"nombre": extra_nombre, "categoria": extra_cat}, reg_extra))
    if extra_cat == "patio":
        # A2.5: el patio debe cumplir AMBOS — luz recta ≥ mínimo Y superficie ≥ mínimo.
        eb = reg_extra.bounds
        luz = min(eb[2] - eb[0], eb[3] - eb[1])
        if luz + 1e-3 < pm.diseno.luz_recta_patio_min:
            incid.append(
                f"Normativa: el patio de {obj.nombre} tiene luz recta {luz:.2f} m; "
                f"el mínimo es {pm.diseno.luz_recta_patio_min:.2f} m."
            )
        if reg_extra.area + 1e-3 < pm.diseno.area_patio_min:
            incid.append(
                f"Normativa: el patio de {obj.nombre} tiene {reg_extra.area:.2f} m²; "
                f"la superficie mínima es {pm.diseno.area_patio_min:.2f} m²."
            )


def _repartir_banda(banda: Polygon, unidades: list[tuple[str, float]],
                    extra_area: float, extra_cat: str, extra_nombre: str,
                    pm: Parametros, obj: ObjetivoPlanta, incid: list[str],
                    placed: list[tuple[dict, Any]]) -> None:
    """Reparte una banda (superior/inferior) en unidades + un extra (patio/local).

    Casos: la banda lleva unidades y extra (corte vertical), solo extra (toda la
    banda; pasa cuando la única unidad fue a la otra banda) o solo unidades.
    """
    banda = _poly_safe(banda)
    if banda.is_empty or banda.area < 1e-6:
        return
    u_area = sum(u for _, u in unidades)
    tiene_extra = extra_area > 1e-6

    if tiene_extra and u_area <= 1e-6:
        # Banda sin unidades: toda la banda es el extra (patio/local).
        _colocar_patio_o_local(banda, extra_cat, extra_nombre, pm, obj, incid, placed)
        return

    reg_unidades = banda
    if tiene_extra and banda.area > extra_area + 1e-6:
        b = banda.bounds
        xx = _cortar_v(banda, b[0], b[2], u_area)
        reg_unidades = _franja_v(banda, b[0], xx)
        _colocar_patio_o_local(
            _franja_v(banda, xx, b[2]), extra_cat, extra_nombre, pm, obj, incid, placed
        )
    _slice_unidades(reg_unidades, unidades, placed)


def _estructurado(interior: Polygon, obj: ObjetivoPlanta, pm: Parametros,
                  edges: dict[str, EdgeTipo],
                  incid: list[str]) -> list[tuple[dict, Polygon]] | None:
    """Esquema núcleo-pasillo-bandas (double-loaded) con áreas exactas.

    Devuelve la lista de (meta, polígono local) o None si el esquema no encaja
    (la huella es demasiado estrecha para dos crujías + pasillo).
    """
    interior = _poly_safe(interior)
    A = interior.area
    if A <= 1.0:
        return None

    # Escala los objetivos al área real del interior (cuadre exacto).
    N, C, P, Loc = obj.nucleo_m2, obj.circulacion_m2, obj.patio_m2, obj.local_m2
    unidades = [(n, u) for n, u in obj.unidades if u > 0]
    U = sum(u for _, u in unidades)
    S = N + C + P + Loc + U
    if S <= 0:
        return None
    k = A / S
    N, C, P, Loc = N * k, C * k, P * k, Loc * k
    unidades = [(n, u * k) for n, u in unidades]
    U = sum(u for _, u in unidades)

    ib = interior.bounds
    H = ib[3] - ib[1]
    # El esquema double-loaded necesita dos crujías mínimas + pasillo.
    prof_min = 2.6
    ancho_pas = max(pm.diseno.ancho_min_pasillo_comun, 0.9)
    if H < 2 * prof_min + ancho_pas - 1e-6:
        return None

    placed: list[tuple[dict, Polygon]] = []

    # 1) Núcleo: franja vertical pegada a la fachada izquierda (acceso).
    region = interior
    if N > 1e-6:
        xn = _cortar_v(interior, ib[0], ib[2], N)
        nucleo = _franja_v(interior, ib[0], xn)
        placed.append(({"nombre": "Núcleo", "categoria": "nucleo"}, nucleo))
        region = _franja_v(interior, xn, ib[2])
        if _radio_inscrito(nucleo) * 2.0 + 1e-3 < pm.diseno.diametro_min_vestibulo:
            incid.append(
                f"Normativa: el núcleo de {obj.nombre} no inscribe el círculo libre de "
                f"Ø{pm.diseno.diametro_min_vestibulo:.2f} m del vestíbulo de giro."
            )

    region = _poly_safe(region)
    if region.is_empty or region.area < 1.0:
        return None
    rb = region.bounds
    A_r = region.area  # = C + P + Loc + U

    # 2) Reparto de unidades entre banda superior e inferior (pasillo centrado).
    objetivo_top = max(0.0, (A_r - C) / 2.0 - P)
    unid_top: list[tuple[str, float]] = []
    unid_bot: list[tuple[str, float]] = []
    acc = 0.0
    for nombre, u in unidades:
        if acc + u * 0.5 <= objetivo_top:
            unid_top.append((nombre, u))
            acc += u
        else:
            unid_bot.append((nombre, u))
    U_t = sum(u for _, u in unid_top)
    U_b = sum(u for _, u in unid_bot)
    area_bot = U_b + Loc
    area_top = U_t + P

    # 3) Tres bandas horizontales: inferior, pasillo, superior.
    y1 = _cortar_h(region, rb[1], rb[3], area_bot)
    y2 = _cortar_h(region, rb[1], rb[3], area_bot + C)
    banda_bot = _franja_h(region, rb[1], y1)
    banda_cor = _franja_h(region, y1, y2)
    banda_top = _franja_h(region, y2, rb[3])

    if C > 1e-6 and not banda_cor.is_empty:
        placed.append(({"nombre": "Circulación", "categoria": "circulacion"}, banda_cor))
        hc = y2 - y1
        if hc + 1e-3 < pm.diseno.ancho_min_pasillo_comun:
            incid.append(
                f"Normativa: el pasillo común de {obj.nombre} mide {hc:.2f} m; "
                f"el ancho mínimo es {pm.diseno.ancho_min_pasillo_comun:.2f} m."
            )
    elif unidades:
        # Acceso a las unidades: sin pasillo común no hay acceso directo desde la
        # circulación (A2.2 — el acceso a la unidad es desde pasillo/distribuidor).
        incid.append(
            f"Normativa: {obj.nombre} no tiene pasillo común; las unidades quedan "
            f"sin acceso directo desde la circulación."
        )

    # 4) Bandas con sus unidades + extras (patio arriba, local abajo).
    _repartir_banda(banda_top, unid_top, P, "patio", "Patio", pm, obj, incid, placed)
    _repartir_banda(banda_bot, unid_bot, Loc, "local", "Local", pm, obj, incid, placed)

    # 5) Ventilación: una crujía contra medianera necesita patio o una fachada
    #    lateral; si no, las estancias principales no ventilan (A2.5). Solo se
    #    avisa cuando la banda queda completamente cerrada por medianeras.
    lateral_fachada = edges.get("xmin") == "fachada" or edges.get("xmax") == "fachada"
    if unid_top and edges.get("ymax") == "medianera" and P <= 1e-6 and not lateral_fachada:
        incid.append(
            f"Normativa: unidades de {obj.nombre} junto a medianera sin "
            f"ventilación a fachada o patio."
        )
    if unid_bot and edges.get("ymin") == "medianera" and Loc <= 1e-6 and not lateral_fachada:
        incid.append(
            f"Normativa: unidades de {obj.nombre} junto a medianera sin "
            f"ventilación a fachada o patio."
        )

    return placed


# ─── Rasterizado a piezas del lienzo ────────────────────────────────────────
def _rings_mundo(g: Any, mu) -> list[list[list[float]]]:
    """Anillos exteriores (mundo) de un polígono/multipolígono, sin punto de cierre."""
    if g is None or g.is_empty:
        return []
    geoms = list(g.geoms) if hasattr(g, "geoms") else [g]
    out: list[list[list[float]]] = []
    for gg in geoms:
        if getattr(gg, "geom_type", "") != "Polygon" or gg.is_empty:
            continue
        w = _poly_safe(mu(gg))
        if w.is_empty:
            continue
        coords = list(w.exterior.coords)
        if len(coords) >= 4:
            out.append([[round(x, 2), round(y, 2)] for x, y in coords[:-1]])
    return out


def disponer_planta(obj: ObjetivoPlanta, lados: list[LadoParcela],
                    pm: Parametros) -> ResultadoPlanta:
    """Reparte los m² objetivo de una planta en piezas del lienzo (Anexo II).

    Pipeline: orienta la huella al eje largo, fija una fachada a la izquierda,
    reserva la banda perimetral de muros (= `muros_m2`), y reparte el interior
    con el esquema estructurado de vivienda; si no encaja, con un treemap. Las
    áreas de cada categoría suman su m² calculado.
    """
    res = ResultadoPlanta()
    fp = _poly_safe(obj.footprint)
    if fp.is_empty or fp.area < 2.0:
        res.incidencias.append(f"{obj.nombre}: huella insuficiente para distribuir.")
        return res

    # Orientación: eje largo horizontal; fachada (con núcleo) a la izquierda.
    ang, (cx, cy) = _frame_angulo(fp)
    ang_deg = math.degrees(ang)
    al, mu = _make_transforms(ang_deg, cx, cy)
    fp_a = _poly_safe(al(fp))
    segs = _segmentos_por_tipo(lados, al)
    edges = _clasificar_box_edges(fp_a.bounds, segs)
    if edges["xmin"] != "fachada" and edges["xmax"] == "fachada":
        ang_deg += 180.0
        al, mu = _make_transforms(ang_deg, cx, cy)
        fp_a = _poly_safe(al(fp))
        segs = _segmentos_por_tipo(lados, al)
        edges = _clasificar_box_edges(fp_a.bounds, segs)

    bnds = fp_a.bounds
    mnx, mny, mxx, mxy = bnds

    placed: list[tuple[dict, Any]] = []

    # Muros: banda perimetral dimensionada a `muros_m2`.
    t = _resolver_grosor_muros(fp_a, bnds, obj.muros_m2)
    _muros_strips(fp_a, bnds, t, edges, placed)
    interior = _poly_safe(fp_a.intersection(box(mnx + t, mny + t, mxx - t, mxy - t)))
    if interior.is_empty or interior.area < 1.0:
        interior = fp_a  # huella diminuta: no se reserva banda

    # Interior: esquema estructurado (plantas con unidades) o treemap.
    estructura: list[tuple[dict, Polygon]] | None = None
    if obj.tipo in ("regular", "atico") and obj.unidades:
        try:
            estructura = _estructurado(interior, obj, pm, edges, res.incidencias)
        except Exception:
            estructura = None
    if estructura is None:
        estructura = _treemap(interior, _items_categorias(obj, interior.area))
        if obj.tipo in ("regular", "atico") and obj.unidades:
            res.incidencias.append(
                f"{obj.nombre}: disposición simplificada (la huella no admite el "
                f"esquema núcleo + pasillo de doble crujía)."
            )

    placed += estructura

    # Rasterizado a piezas del lienzo (mundo UTM30N).
    for meta, g in placed:
        cat = meta["categoria"]
        color = COLORES.get(cat, COLORES["resto"])
        for ring in _rings_mundo(g, mu):
            res.piezas.append(PiezaDispuesta(meta["nombre"], cat, color, ring))
        res.areas[cat] = res.areas.get(cat, 0.0) + _poly_safe(g).area

    return res
