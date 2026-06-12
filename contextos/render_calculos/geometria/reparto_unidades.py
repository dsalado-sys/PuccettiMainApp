"""Reparto geométrico de unidades en planta (§2.4/§2.5 + criterios de diseño interior).

Toma los RESULTADOS del cálculo (`Capacidad.unidades_por_planta`: lista exacta de
unidades con tipología y útil objetivo por planta) y los dispone sobre la
envolvente: núcleo vertical único del edificio, portal de acceso, pasillos o
galerías, vestíbulos con circunferencia Ø1,50 m, local de PB, zonas sociales
(hotelero/apartamentos) y una rebanada por unidad.

Principio rector (deuda saldada de `macro_layout`, deprecado): el reparto NUNCA
crea ni elimina unidades — dibuja exactamente las que dicta el cálculo, o las
declara «no ubicadas» con su incidencia. La cardinalidad por planta es un
invariante: `len(planta.unidades) == len(cap.unidades_por_planta[i])`.

Criterios codificados (referencias internas, nunca en textos de UI):
- A2.1  núcleo + acceso desde fachada (portal), pasillos ≥ ancho mínimo,
        vestíbulo Ø1,50 libre en encuentros de circulación.
- A2.3  acceso directo de cada unidad desde el pasillo; zonas sociales en PB.
- A2.4  los huecos solo computan en fachada (el frente a medianera no ventila).
- A2.5  el patio mínimo solo ventila servicios; las estancias principales
        exigen frente de fachada.

Determinismo: sin aleatoriedad. Candidatos enumerados en orden fijo, empates
resueltos por índice. Mismo input → misma geometría.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

from shapely.errors import GEOSException
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union
from shapely.validation import make_valid

from .capacidad import Capacidad, indices_adaptadas
from .config import Parametros
from .envolvente import Envolvente, Patio, Planta
from .parcelas import LadoParcela
from .programa import util_minimo_vivienda

# ---- dimensiones del núcleo vertical (m) — defaults del estudio ----
ESCALERA_ANCHO = 2.60
ESCALERA_LARGO = 4.50
ASCENSOR_LADO = 1.60
NUCLEO_LARGO = 5.20
NUCLEO_ANCHO = 4.40

ALTURA_HUECO = 1.50          # altura de referencia del hueco de fachada (m)
FACTOR_UTIL_REBANADA = 0.95  # útil/construida de una rebanada (descuenta separaciones)
AREA_MIN_RESTO = 6.0         # fragmento menor → se ignora; mayor → pieza «resto»
FRENTE_MIN_LOCAL = 4.00      # escaparate mínimo del local de PB (m)

# Frente mínimo de rebanada por tipo de unidad (m) — experiencia del estudio.
FRENTE_MIN_POR_TIPO = {
    "habitacion": 2.90,
    "apartamento": 3.20,
    "hotel_apartamento": 3.20,
}
# Proporción fondo/frente máxima razonable antes de avisar.
FONDO_FRENTE_MAX = {"vivienda": 2.2, "default": 3.0}


def _frente_min(tipo_unidad: str, n_dorms: int) -> float:
    if tipo_unidad == "vivienda":
        return 3.60 if n_dorms <= 1 else 4.80
    return FRENTE_MIN_POR_TIPO.get(tipo_unidad, 2.90)


# ─── Saneamiento geométrico ──────────────────────────────────────────────────
def _partes(g) -> list[Polygon]:
    """Componentes poligonales válidas de cualquier geometría (política explícita)."""
    if g is None or g.is_empty:
        return []
    g = make_valid(g)
    if isinstance(g, Polygon):
        return [g] if g.area > 1e-6 else []
    if isinstance(g, MultiPolygon):
        return [p for p in g.geoms if p.area > 1e-6]
    if hasattr(g, "geoms"):  # GeometryCollection
        out: list[Polygon] = []
        for sub in g.geoms:
            out.extend(_partes(sub))
        return out
    return []


def _mayor(g) -> Polygon:
    partes = _partes(g)
    if not partes:
        return Polygon()
    return max(partes, key=lambda p: p.area)


def _union(geoms) -> Polygon | MultiPolygon:
    gs = [g for g in geoms if g is not None and not g.is_empty]
    if not gs:
        return Polygon()
    return make_valid(unary_union(gs))


def _contacto(geom: Polygon, linea, tol: float = 0.35) -> float:
    """Longitud de contacto del borde de `geom` con `linea` (franja de tolerancia)."""
    if geom.is_empty or linea is None or linea.is_empty:
        return 0.0
    try:
        franja = linea.buffer(tol)
        inter = geom.boundary.intersection(franja)
        return float(inter.length) if not inter.is_empty else 0.0
    except GEOSException:
        return 0.0


def _circulo_libre(geom, ref: Point, radio_busqueda: float = 0.0) -> tuple[tuple[float, float], float]:
    """Centro y radio del mayor círculo inscrito en `geom` cerca de `ref`.

    Con `radio_busqueda > 0` la inscripción se restringe al entorno de `ref`
    (intersección con `ref.buffer(radio_busqueda)`): así el check Ø1,50 mide el
    círculo EN el nodo de circulación (A2.1 — «en cada nodo… debe poder
    inscribirse Ø1,50»), no el mayor círculo de toda la componente, que podría
    estar a metros del encuentro."""
    partes = _partes(geom)
    if not partes:
        return (ref.x, ref.y), 0.0
    comp = min(partes, key=lambda p: p.distance(ref))
    if radio_busqueda > 0:
        local = _mayor(comp.intersection(ref.buffer(radio_busqueda)))
        if not local.is_empty:
            comp = local
    try:
        from shapely.ops import polylabel
        c = polylabel(comp, tolerance=0.05)
    except Exception:
        c = comp.representative_point()
    radio = c.distance(comp.boundary)
    return (c.x, c.y), float(radio)


# ─── Marco alineado ──────────────────────────────────────────────────────────
def _angulo_marco(footprint: Polygon, lados: list[LadoParcela]) -> tuple[float, tuple[float, float]]:
    """Ángulo del lado largo del MRR. Desempate determinista en huellas casi
    cuadradas (lados que difieren <2%): azimut de la fachada más larga."""
    mrr = footprint.minimum_rotated_rectangle
    if mrr.geom_type != "Polygon":
        return 0.0, (footprint.centroid.x, footprint.centroid.y)
    coords = list(mrr.exterior.coords)[:-1]
    edges = [(coords[i], coords[(i + 1) % 4]) for i in range(4)]
    elens = [math.dist(a, b) for a, b in edges]
    orden = sorted(range(4), key=lambda i: elens[i], reverse=True)
    li = orden[0]
    if elens[orden[0]] > 0 and abs(elens[orden[0]] - elens[orden[2]]) / elens[orden[0]] < 0.02:
        fachadas = [l for l in lados if l.tipo == "fachada"]
        if fachadas:
            ldom = max(fachadas, key=lambda l: l.longitud_m)
            ang = math.atan2(ldom.p2[1] - ldom.p1[1], ldom.p2[0] - ldom.p1[0])
            return ang, (mrr.centroid.x, mrr.centroid.y)
    a, b = edges[li]
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    return ang, (mrr.centroid.x, mrr.centroid.y)


def _transformaciones(angulo_deg: float, cx: float, cy: float):
    from shapely.affinity import rotate, translate

    def al(g):
        return rotate(translate(g, xoff=-cx, yoff=-cy), -angulo_deg, origin=(0, 0))

    def mu(g):
        return translate(rotate(g, angulo_deg, origin=(0, 0)), xoff=cx, yoff=cy)

    return al, mu


def _segmentos_por_tipo(lados: list[LadoParcela], al) -> dict[str, MultiLineString]:
    out: dict[str, list[LineString]] = {"fachada": [], "medianera": []}
    for l in lados:
        out[l.tipo].append(al(LineString([l.p1, l.p2])))
    return {k: MultiLineString(v) if v else MultiLineString([]) for k, v in out.items()}


def _fachada_efectiva(fp_a: Polygon, segs: dict[str, MultiLineString], paso: float = 1.5) -> MultiLineString:
    """Tramos del contorno de ESTA huella que miran a fachada de parcela.

    Imprescindible en plantas retranqueadas (ático): su borde queda a metros de
    los lados de la parcela, pero sigue siendo fachada a todos los efectos de
    ventilación. Clasifica cada tramo del exterior por el tipo del lado de
    parcela más próximo."""
    fach, med = segs["fachada"], segs["medianera"]
    if fach.is_empty:
        return MultiLineString([])
    if med.is_empty:
        return MultiLineString([LineString(fp_a.exterior.coords)])
    coords = list(fp_a.exterior.coords)
    tramos: list[LineString] = []
    actual: list[tuple[float, float]] = []
    for a, b in zip(coords[:-1], coords[1:]):
        seg = LineString([a, b])
        n_m = max(2, int(seg.length / paso) + 1)
        votos = 0
        for k in range(n_m):
            p = seg.interpolate(k / (n_m - 1), normalized=True)
            votos += 1 if p.distance(fach) <= p.distance(med) else -1
        if votos >= 0:
            if not actual:
                actual.append(a)
            actual.append(b)
        elif actual:
            tramos.append(LineString(actual))
            actual = []
    if actual and len(actual) >= 2:
        tramos.append(LineString(actual))
    return MultiLineString(tramos) if tramos else MultiLineString([])


def _reubicar_patios(
    patios_a: list[Polygon], corr_y: tuple[float, float], nucleo_geom: Polygon,
    interior_a: Polygon,
) -> list[Polygon]:
    """Desplaza en y los patios que invaden la espina de circulación.

    El patio de la envolvente nace en el polo de inaccesibilidad (centro), que
    es exactamente donde pasa el pasillo. Se desplaza al lado de la espina con
    más fondo disponible, pegado a ella (sigue ventilando los fondos de las
    rebanadas adyacentes)."""
    cy0, cy1 = corr_y
    out: list[Polygon] = []
    mny_i, mxy_i = interior_a.bounds[1], interior_a.bounds[3]
    for p in patios_a:
        if p.is_empty:
            continue
        b = p.bounds
        if b[3] > cy0 - 0.05 and b[1] < cy1 + 0.05:  # invade la espina
            alto = b[3] - b[1]
            hueco_abajo = cy0 - mny_i
            hueco_arriba = mxy_i - cy1
            # Se pega el patio AL borde del pasillo (sin holgura): así, al
            # restarlo de la banda, abre una muesca abierta en vez de quedar
            # como agujero interior (que `ring()` perdería al serializar y la
            # unidad dibujaría tapando el patio).
            if hueco_abajo >= alto + 0.1 and hueco_abajo >= hueco_arriba:
                dy = cy0 - b[3]
            elif hueco_arriba >= alto + 0.1:
                dy = cy1 - b[1]
            else:
                out.append(p)
                continue
            from shapely.affinity import translate
            movido = translate(p, yoff=dy)
            if not nucleo_geom.is_empty and movido.intersects(nucleo_geom):
                ancho = b[2] - b[0]
                dx = nucleo_geom.bounds[2] + 0.1 - movido.bounds[0] \
                    if movido.bounds[0] < nucleo_geom.bounds[2] else 0.0
                movido = translate(movido, xoff=dx)
            movido = _mayor(movido.intersection(interior_a))
            out.append(movido if not movido.is_empty else p)
        else:
            out.append(p)
    return out


def _clasificar_bordes(fp_a: Polygon, segs: dict[str, MultiLineString], n: int = 9) -> dict[str, str]:
    """Tipo (fachada/medianera) de cada borde del bbox de la huella alineada.

    Muestrea puntos del CONTORNO REAL más próximos a cada borde del bbox (robusto
    en parcelas irregulares, donde el bbox queda lejos del polígono)."""
    mnx, mny, mxx, mxy = fp_a.bounds
    fach, med = segs["fachada"], segs["medianera"]
    borde = fp_a.exterior

    def clasifica(puntos_box: list[Point]) -> str:
        votos = []
        for pb in puntos_box:
            d = borde.project(pb)
            p_real = borde.interpolate(d)
            df = p_real.distance(fach) if not fach.is_empty else math.inf
            dm = p_real.distance(med) if not med.is_empty else math.inf
            votos.append("fachada" if df <= dm else "medianera")
        return "fachada" if votos.count("fachada") >= votos.count("medianera") else "medianera"

    ts = [i / (n - 1) for i in range(n)]
    return {
        "xmin": clasifica([Point(mnx, mny + t * (mxy - mny)) for t in ts]),
        "xmax": clasifica([Point(mxx, mny + t * (mxy - mny)) for t in ts]),
        "ymin": clasifica([Point(mnx + t * (mxx - mnx), mny) for t in ts]),
        "ymax": clasifica([Point(mnx + t * (mxx - mnx), mxy) for t in ts]),
    }


# ─── Modelo de resultado ─────────────────────────────────────────────────────
@dataclass
class AlertaReparto:
    nivel: str            # "info" | "aviso" | "incumplimiento"
    regla: str            # "Normativa" | "Capacidad"
    mensaje: str
    elemento: str | None = None


@dataclass
class NucleoEdificio:
    geometry: Polygon
    escalera: Polygon
    ascensor: Polygon
    vestibulo: Polygon
    circulo_centro: tuple[float, float]
    circulo_radio: float
    circulo_ok: bool
    area_m2: float


@dataclass
class PiezaCirculacion:
    geometry: Polygon
    tipo: str             # "pasillo" | "galeria" | "portal" | "vestibulo"
    ancho_m: float
    area_m2: float
    circulo_ok: bool | None = None


@dataclass
class PiezaSingular:
    geometry: Polygon
    tipo: str             # "local" | "zona_social" | "resto"
    nombre: str
    area_m2: float
    target_m2: float
    frente_fachada_m: float = 0.0


@dataclass
class UnidadDispuesta:
    id: str
    slug: str
    tipo_unidad: str
    n_dorms: int
    util_objetivo_m2: float
    util_min_m2: float
    geometry_util: Polygon
    geometry_constr: Polygon
    area_util_m2: float = 0.0
    area_constr_m2: float = 0.0
    ubicada: bool = True
    acceso_pasillo: bool = False
    borde_pasillo_m: float = 0.0
    frente_fachada_m: float = 0.0
    ventilacion_tipo: str = "ninguna"
    hueco_req_m2: float = 0.0
    hueco_disp_m2: float = 0.0
    ventila_ok: bool = False
    cumple_min: bool = False
    fondo_frente: float = 0.0
    proporcion_ok: bool = True
    es_adaptada: bool = False
    incidencias: list[str] = field(default_factory=list)


@dataclass
class PlantaDispuesta:
    indice: int                      # índice en envolvente.plantas / cap.*
    n: int
    nombre: str
    tipo: str                        # "regular" | "atico" | "sotano"
    footprint: Polygon
    interior: Polygon
    muros_perimetrales: Polygon
    nucleo: NucleoEdificio | None
    nucleo_es_caseton: bool
    circulaciones: list[PiezaCirculacion]
    patios: list[Patio]              # patios de la envolvente (coords mundo)
    piezas: list[PiezaSingular]
    unidades: list[UnidadDispuesta]
    muros_divisorios: Polygon
    tipologia_circulacion: str       # "pasillo" | "galeria" | "nucleo"
    # Franja residual convertida en patio (en coords alineadas hasta el final).
    patios_nuevos: list[Patio] = field(default_factory=list)
    superficies: dict = field(default_factory=dict)
    conciliacion: dict = field(default_factory=dict)
    incidencias: list[str] = field(default_factory=list)


@dataclass
class EdificioDispuesto:
    plantas: list[PlantaDispuesta]
    n_unidades: int
    n_unidades_ubicadas: int
    alertas: list[AlertaReparto] = field(default_factory=list)
    score: float = 0.0
    estrategia: str = ""
    acceso_en_fachada: bool = True   # el borde de acceso (xmin) es fachada


# ─── Targets por unidad (del cálculo) ────────────────────────────────────────
@dataclass
class _Target:
    j: int                # índice de unidad dentro de la planta (orden del cálculo)
    slug: str
    n_dorms: int
    util_m2: float
    tipo_unidad: str
    util_min_m2: float
    frente_min_m: float


def _targets_planta(
    cap: Capacidad, i: int, tipo_unidad: str, minimos_por_slug: dict[str, float] | None,
) -> list[_Target]:
    unidades = cap.unidades_por_planta[i] if i < len(cap.unidades_por_planta) else []
    slugs = cap.tipologias_unidad_por_planta[i] if i < len(cap.tipologias_unidad_por_planta) else []
    out: list[_Target] = []
    for j, (n_dorms, util) in enumerate(unidades):
        slug = slugs[j] if j < len(slugs) else str(n_dorms)
        if minimos_por_slug and slug in minimos_por_slug:
            util_min = float(minimos_por_slug[slug])
        elif tipo_unidad == "vivienda":
            util_min = util_minimo_vivienda(int(n_dorms))
        else:
            util_min = util * 0.85
        out.append(_Target(
            j=j, slug=slug, n_dorms=int(n_dorms), util_m2=float(util),
            tipo_unidad=tipo_unidad, util_min_m2=util_min,
            frente_min_m=_frente_min(tipo_unidad, int(n_dorms)),
        ))
    return out


# ─── Disposición en banda: corte por área acumulada ──────────────────────────
def _area_hasta(comp: Polygon, x0: float, x1: float) -> float:
    if x1 <= x0:
        return 0.0
    mny, mxy = comp.bounds[1], comp.bounds[3]
    return comp.intersection(box(x0, mny - 1.0, x1, mxy + 1.0)).area


def _corte_por_area(comp: Polygon, x_desde: float, area_obj: float) -> float:
    """x de corte tal que el área de `comp` entre `x_desde` y el corte ≈ `area_obj`.

    Bisección sobre x — robusto en componentes de profundidad variable (huellas
    en L, muescas), donde «ancho ∝ área» sería falso."""
    x_max = comp.bounds[2]
    if area_obj <= 0:
        return x_desde
    if _area_hasta(comp, x_desde, x_max) <= area_obj:
        return x_max
    lo, hi = x_desde, x_max
    for _ in range(28):
        mid = (lo + hi) / 2.0
        if _area_hasta(comp, x_desde, mid) < area_obj:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _rebanada(comp: Polygon, x0: float, x1: float, corredor) -> Polygon:
    """Trozo de la componente entre x0 y x1. Si queda partido (patio, muesca),
    conserva la parte con acceso al corredor (o la mayor) — el resto se pierde
    como fragmento y lo recoge la pieza «resto» de la banda."""
    mny, mxy = comp.bounds[1], comp.bounds[3]
    piezas = _partes(comp.intersection(box(x0, mny - 1.0, x1, mxy + 1.0)))
    if not piezas:
        return Polygon()
    if len(piezas) == 1:
        return piezas[0]
    if corredor is not None and not corredor.is_empty:
        con_acceso = [p for p in piezas if p.distance(corredor) < 0.40]
        if con_acceso:
            return max(con_acceso, key=lambda p: p.area)
    return max(piezas, key=lambda p: p.area)


# ─── Layout vertical (bandas / pasillo / patio residual) ─────────────────────
@dataclass
class _LayoutY:
    tipo: str                                  # "double" | "single"
    corr_y: tuple[float, float]
    bandas_y: list[tuple[float, float, str]]   # (y0, y1, borde de ventilación)
    patio_y: tuple[float, float] | None
    incidencias: list[str] = field(default_factory=list)


def _resolver_layout_y(bounds, edges: dict[str, str], params: Parametros) -> _LayoutY:
    mnx, mny, mxx, mxy = bounds
    H = mxy - mny
    d = params.diseno
    cw = d.ancho_min_pasillo_comun
    prof_min = getattr(d, "prof_min_unidad", 3.50)
    prof_max = getattr(d, "prof_max_unidad", 8.00)
    luz_patio = d.luz_recta_patio_min
    fach_ymin = edges["ymin"] == "fachada"
    fach_ymax = edges["ymax"] == "fachada"
    incidencias: list[str] = []

    # Double-loaded solo si AMBAS bandas ventilan a fachada (si no, una banda
    # entera quedaría ciega contra medianera) y cabe la doble crujía.
    if fach_ymin and fach_ymax and H >= 2 * prof_min + cw:
        yc = (mny + mxy) / 2.0
        return _LayoutY(
            tipo="double",
            corr_y=(yc - cw / 2.0, yc + cw / 2.0),
            bandas_y=[(yc + cw / 2.0, mxy, "ymax"), (mny, yc - cw / 2.0, "ymin")],
            patio_y=None,
        )

    lado = "ymax" if fach_ymax else ("ymin" if fach_ymin else "ymax")
    if not fach_ymin and not fach_ymax:
        incidencias.append("Las bandas de unidades no dan a fachada en esta orientación.")

    if H - cw < prof_min:
        # Planta muy estrecha: banda única con todo el fondo disponible.
        if lado == "ymax":
            return _LayoutY("single", (mny, mny + cw), [(mny + cw, mxy, "ymax")], None, incidencias)
        return _LayoutY("single", (mxy - cw, mxy), [(mny, mxy - cw, "ymin")], None, incidencias)

    fondo = min(prof_max, H - cw)
    resto = H - fondo - cw
    if 0 < resto < luz_patio:
        # El residuo no da para patio: la banda absorbe el fondo sobrante.
        fondo, resto = H - cw, 0.0

    if lado == "ymax":
        banda = (mxy - fondo, mxy, "ymax")
        corr = (mxy - fondo - cw, mxy - fondo)
        patio = (mny, mny + resto) if resto > 0 else None
    else:
        banda = (mny, mny + fondo, "ymin")
        corr = (mny + fondo, mny + fondo + cw)
        patio = (mxy - resto, mxy) if resto > 0 else None
    return _LayoutY("single", corr, [banda], patio, incidencias)


# ─── Núcleo vertical único del edificio ──────────────────────────────────────
def _construir_nucleo(
    region_a: Polygon, layout: _LayoutY, params: Parametros,
    solo_preferidos: bool = False, con_ascensor: bool = True,
) -> Optional[NucleoEdificio]:
    """Núcleo 5,20×4,40 pegado al pasillo, del lado opuesto a la banda principal
    (medianera en single-loaded). Barrido determinista en x desde el acceso.

    `solo_preferidos=True` restringe a los anclajes que NO invaden la banda de
    unidades (el llamador decide si prefiere casetón antes que comer fachada).
    `con_ascensor=False` dibuja solo escalera (edificios bajos que no exigen
    ascensor, A2.1)."""
    if region_a.is_empty:
        return None
    mnx, _, mxx, _ = region_a.bounds
    cy0, cy1 = layout.corr_y

    # Anclajes y en orden de preferencia: bajo/encima del pasillo según banda.
    lados_banda = {b[2] for b in layout.bandas_y}
    preferidos: list[tuple[float, float]] = []
    if "ymin" not in lados_banda:
        preferidos.append((cy0 - NUCLEO_ANCHO, cy0))      # debajo del pasillo
    if "ymax" not in lados_banda:
        preferidos.append((cy1, cy1 + NUCLEO_ANCHO))      # encima del pasillo
    # Fallback: invade la banda (consume frente de fachada) — última opción.
    fallbacks = [(cy1, cy1 + NUCLEO_ANCHO), (cy0 - NUCLEO_ANCHO, cy0)]
    anclajes = preferidos if solo_preferidos else preferidos + fallbacks
    if not anclajes:
        return None

    candidatos: list[tuple[float, float, float, float]] = []
    for (y0, y1) in anclajes:
        x = mnx
        while x + NUCLEO_LARGO <= mxx + 1e-6:
            candidatos.append((x, y0, x + NUCLEO_LARGO, y1))
            x += 0.5
    for (x0, y0, x1, y1) in candidatos:
        bloque = box(x0, y0, x1, y1)
        if bloque.within(region_a.buffer(0.05)):
            return _detallar_nucleo(bloque, (y0 + y1) / 2.0 > (cy0 + cy1) / 2.0, params, con_ascensor)
    if solo_preferidos:
        return None
    # Último recurso: bloque recortado a la región (núcleo parcial).
    area_min = ESCALERA_ANCHO * ESCALERA_LARGO + (ASCENSOR_LADO ** 2 if con_ascensor else 0.0)
    for (x0, y0, x1, y1) in candidatos[:40]:
        bloque = _mayor(box(x0, y0, x1, y1).intersection(region_a))
        if bloque.area >= area_min:
            return _detallar_nucleo(bloque, (y0 + y1) / 2.0 > (cy0 + cy1) / 2.0, params, con_ascensor)
    return None


def _detallar_nucleo(
    bloque: Polygon, encima_pasillo: bool, params: Parametros, con_ascensor: bool = True,
) -> NucleoEdificio:
    """Escalera + ascensor pegados al lado opuesto al pasillo; vestíbulo al pasillo.

    Escalera (4,50×2,60) a lo largo de x; ascensor (1,60×1,60) en la franja libre
    en y junto a la escalera (NUCLEO_ANCHO−ESCALERA_ANCHO = 1,80 ≥ 1,60). Así
    ambos caben SIEMPRE dentro del bloque de 5,20×4,40 (antes el ascensor se
    colocaba a +4,60 m en x y quedaba recortado por el borde a 5,20)."""
    bx0, by0, bx1, by1 = bloque.bounds
    if encima_pasillo:
        # Escalera al fondo (lejos del pasillo), ascensor en la franja del pasillo.
        ey0, ey1 = by1 - ESCALERA_ANCHO, by1
        ay0 = by0
    else:
        ey0, ey1 = by0, by0 + ESCALERA_ANCHO
        ay0 = by1 - ASCENSOR_LADO
    escalera = _mayor(box(bx0, ey0, bx0 + ESCALERA_LARGO, ey1).intersection(bloque))
    if con_ascensor:
        ascensor = _mayor(box(bx0, ay0, bx0 + ASCENSOR_LADO, ay0 + ASCENSOR_LADO).intersection(bloque))
    else:
        ascensor = Polygon()
    vestibulo = _union([bloque]).difference(_union([escalera, ascensor]))
    vestibulo_p = _mayor(vestibulo)
    centro, radio = _circulo_libre(vestibulo_p, bloque.centroid)
    req = params.diseno.diametro_min_vestibulo / 2.0
    return NucleoEdificio(
        geometry=bloque, escalera=escalera, ascensor=ascensor, vestibulo=vestibulo_p,
        circulo_centro=centro, circulo_radio=radio, circulo_ok=radio + 1e-3 >= req,
        area_m2=bloque.area,
    )


# ─── Disposición de una planta ───────────────────────────────────────────────
@dataclass
class _Banda:
    geom: Polygon
    borde_ventilacion: str


def _no_ubicadas(targets: list[_Target], motivo: str) -> list[UnidadDispuesta]:
    """Unidades del cálculo que no se pudieron disponer (preserva cardinalidad)."""
    return [
        UnidadDispuesta(
            id="", slug=t.slug, tipo_unidad=t.tipo_unidad, n_dorms=t.n_dorms,
            util_objetivo_m2=round(t.util_m2, 2), util_min_m2=round(t.util_min_m2, 2),
            geometry_util=Polygon(), geometry_constr=Polygon(), ubicada=False,
            incidencias=[motivo],
        )
        for t in targets
    ]


def _disponer_planta(
    indice: int,
    pl_env: Planta,
    nombre: str,
    targets: list[_Target],
    local_m2: float,
    social_m2: float,
    nucleo: NucleoEdificio | None,
    layout: _LayoutY,
    edges: dict[str, str],
    segs: dict[str, MultiLineString],
    params: Parametros,
    al,
    es_pb: bool,
    principales_m2: Callable[[str, int, float], float] | None,
) -> PlantaDispuesta:
    d = params.diseno
    cw = d.ancho_min_pasillo_comun
    esp_div = max(0.05, d.espesor_separacion_unidades)
    footprint = pl_env.footprint
    incidencias: list[str] = list(layout.incidencias) if targets else []

    # Interior SIN los huecos de patio (la envolvente ya los restó): el reparto
    # decide dónde van los patios para no cortar la circulación.
    interior_a = _mayor(al(make_valid(unary_union(
        [pl_env.interior] + [p.geometry for p in pl_env.patios]
    ))))
    fp_a = _mayor(al(footprint))
    muros_perim = _mayor(make_valid(footprint).difference(make_valid(pl_env.interior)))
    patios_a = [_mayor(al(p.geometry)) for p in pl_env.patios]
    # Fachada efectiva de ESTA huella (el ático retranqueado no toca los lados
    # de parcela pero sus bordes hacia fachada siguen ventilando).
    fach_efectiva = _fachada_efectiva(fp_a, segs)

    planta = PlantaDispuesta(
        indice=indice, n=pl_env.n, nombre=nombre, tipo=pl_env.tipo,
        footprint=footprint, interior=pl_env.interior, muros_perimetrales=muros_perim,
        nucleo=nucleo, nucleo_es_caseton=False, circulaciones=[], patios=[],
        piezas=[], unidades=[], muros_divisorios=Polygon(),
        tipologia_circulacion="pasillo", incidencias=incidencias,
    )

    if interior_a.is_empty:
        planta.incidencias.append(f"{nombre}: la huella no deja interior útil.")
        # Cardinalidad: las unidades del cálculo se devuelven como no ubicadas,
        # nunca se omiten (la tabla cuenta con ellas).
        planta.unidades = _no_ubicadas(
            targets, f"{nombre}: la huella no deja interior útil para disponer la unidad.")
        planta.superficies = _superficies_planta(planta, footprint.area)
        return planta

    # Núcleo recortado/casetón: si el bloque no cabe en ESTA huella (ático
    # retranqueado), se mantiene como casetón y se recortan bandas y pasillo.
    nucleo_geom = Polygon()
    if nucleo is not None:
        nucleo_geom = nucleo.geometry
        if not nucleo_geom.within(fp_a.buffer(0.10)):
            planta.nucleo_es_caseton = True

    # Sótano o planta sin contenido: solo núcleo + huella (+ patios originales).
    if pl_env.tipo == "sotano" or (not targets and local_m2 <= 0 and social_m2 <= 0):
        planta.patios = list(pl_env.patios)
        planta.superficies = _superficies_planta(planta, footprint.area)
        return planta

    mnx_i, mny_i, mxx_i, mxy_i = interior_a.bounds
    cy0, cy1 = layout.corr_y
    cy0 = max(cy0, mny_i)
    cy1 = min(cy1, mxy_i)

    # Los patios no pueden cortar la espina: se reubican pegados a ella.
    patios_a = _reubicar_patios(patios_a, (cy0, cy1), nucleo_geom, interior_a)
    patios_union = _union(patios_a)

    # ── Pasillo (espina) ────────────────────────────────────────────────────
    # La espina recorre todo el ancho útil; el portal (PB) y el ramal hacia el
    # núcleo se modelan aparte. Arranca en el borde de acceso de la huella.
    corr_full = box(mnx_i, cy0, mxx_i, cy1)
    corr_geom = _union(_partes(corr_full.intersection(interior_a)))
    if not patios_union.is_empty:
        # Un patio nunca puede cortar la espina de circulación.
        corr_geom = _union(_partes(make_valid(corr_geom).difference(patios_union)))
    if nucleo is not None:
        corr_geom = _union([corr_geom]).difference(_union([nucleo.escalera, nucleo.ascensor]))

    # ── Patio residual (franja contra medianera en parcelas profundas) ──────
    # Solo se etiqueta como patio si cumple los mínimos de A2.5 (≥ área y ≥ luz
    # recta); si no, no es patio (se deja como banda) para no dibujar un
    # patinillo no normativo sin avisar.
    patio_extra: Patio | None = None
    if layout.patio_y is not None:
        py0, py1 = layout.patio_y
        pgeom = _mayor(box(mnx_i, py0, mxx_i, py1).intersection(interior_a))
        recortar = [g for g in ([nucleo_geom] if nucleo is not None else []) + patios_a]
        if recortar and not pgeom.is_empty:
            pgeom = _mayor(make_valid(pgeom).difference(_union(recortar)))
        if not pgeom.is_empty:
            pb = pgeom.bounds
            luz = min(pb[2] - pb[0], pb[3] - pb[1])
            if pgeom.area + 1e-6 >= d.area_patio_min and luz + 1e-6 >= d.luz_recta_patio_min:
                patio_extra = Patio(geometry=pgeom, area_m2=pgeom.area, luz_recta_m=luz)

    # ── Bandas de unidades (componentes conexas) ────────────────────────────
    quitar = _union([corr_geom, nucleo_geom, patios_union,
                     patio_extra.geometry if patio_extra else None])
    bandas: list[_Banda] = []
    for (by0, by1, lado_vent) in layout.bandas_y:
        g = make_valid(box(mnx_i, by0, mxx_i, by1).intersection(interior_a))
        if not quitar.is_empty:
            g = make_valid(g.difference(quitar))
        for comp in _partes(g):
            if comp.area >= AREA_MIN_RESTO:
                bandas.append(_Banda(comp, lado_vent))
    bandas.sort(key=lambda b: (-(b.geom.area), b.geom.bounds[0]))

    # ── Ramales: una banda sin contacto con el pasillo recibe un ramal ──────
    vestibulos: list[PiezaCirculacion] = []
    for b in bandas:
        if corr_geom.is_empty or b.geom.distance(corr_geom) < 0.40:
            continue
        cx = (b.geom.bounds[0] + b.geom.bounds[2]) / 2.0
        y_lo = min(cy0, b.geom.bounds[1])
        y_hi = max(cy1, b.geom.bounds[3])
        ramal = _mayor(box(cx - cw / 2.0, y_lo, cx + cw / 2.0, y_hi).intersection(interior_a))
        if ramal.is_empty:
            continue
        corr_geom = _union([corr_geom, ramal])
        b.geom = _mayor(make_valid(b.geom).difference(ramal))
        # Vestíbulo de giro en el codo (encuentro de circulaciones).
        dv = max(d.diametro_min_vestibulo, cw)
        codo = box(cx - dv / 2.0, cy0 - (dv - (cy1 - cy0)) / 2.0,
                   cx + dv / 2.0, cy1 + (dv - (cy1 - cy0)) / 2.0)
        codo_g = _mayor(codo.intersection(interior_a))
        if not codo_g.is_empty:
            corr_geom = _union([corr_geom, codo_g])
            centro, radio = _circulo_libre(
                _union([corr_geom]), codo_g.centroid,
                radio_busqueda=2.0 * d.diametro_min_vestibulo)
            vestibulos.append(PiezaCirculacion(
                geometry=codo_g, tipo="vestibulo", ancho_m=dv, area_m2=codo_g.area,
                circulo_ok=radio + 1e-3 >= d.diametro_min_vestibulo / 2.0,
            ))

    # ── Vestíbulo de encuentro núcleo ↔ pasillo (Ø1,50 libre EN el nodo) ────
    if nucleo is not None and not corr_geom.is_empty:
        ref = Point(nucleo.vestibulo.centroid)
        zona = _union([corr_geom, nucleo.vestibulo])
        centro, radio = _circulo_libre(zona, ref, radio_busqueda=2.0 * d.diametro_min_vestibulo)
        ok = radio + 1e-3 >= d.diametro_min_vestibulo / 2.0
        if not ok:
            planta.incidencias.append(
                f"{nombre}: el vestíbulo del núcleo no inscribe la circunferencia "
                f"libre mínima (Ø{d.diametro_min_vestibulo:.2f} m)."
            )

    # ── Piezas singulares de PB: zonas sociales y local (a fachada) ─────────
    bandas_fachada = [b for b in bandas if edges.get(b.borde_ventilacion) == "fachada"] or bandas
    piezas_pb: list[tuple[str, str, float]] = []
    if es_pb and social_m2 > 0:
        piezas_pb.append(("zona_social", "Zonas sociales", social_m2))
    if es_pb and local_m2 > 0:
        piezas_pb.append(("local", "Local", local_m2))
    for (tipo_p, nombre_p, target_p) in piezas_pb:
        pieza = _cortar_pieza_singular(bandas_fachada, tipo_p, nombre_p, target_p,
                                       fach_efectiva, corr_geom, d)
        if pieza is not None:
            planta.piezas.append(pieza)
        else:
            planta.incidencias.append(
                f"{nombre}: no hay frente disponible para «{nombre_p}» "
                f"({target_p:.1f} m²)."
            )

    # ── Asignación orden-preservante de unidades a bandas + rebanado ────────
    rebanadas: list[tuple[_Target, Polygon]] = []
    pendientes = list(targets)
    for b in bandas:
        if not pendientes:
            break
        comp = b.geom
        if comp.is_empty:
            continue
        x_cursor = comp.bounds[0]
        x_fin_comp = comp.bounds[2]
        siguientes: list[_Target] = []
        for t in pendientes:
            target_constr = t.util_m2 / FACTOR_UTIL_REBANADA
            area_restante = _area_hasta(comp, x_cursor, x_fin_comp)
            if area_restante < 0.6 * target_constr or (x_fin_comp - x_cursor) < t.frente_min_m:
                siguientes.append(t)
                continue
            x_corte = _corte_por_area(comp, x_cursor, target_constr)
            if x_corte - x_cursor < t.frente_min_m:
                x_corte = min(x_cursor + t.frente_min_m, x_fin_comp)
            g = _rebanada(comp, x_cursor, x_corte, corr_geom)
            if g.is_empty or g.area < 0.4 * target_constr:
                siguientes.append(t)
                continue
            rebanadas.append((t, g))
            x_cursor = x_corte
        # Sobrante de la banda → pieza «resto» (trasteros/instalaciones) o
        # ensanche de la última rebanada si aún cabe en su tipología.
        resto_g = _mayor(make_valid(comp).difference(
            _union([g for _, g in rebanadas])))
        if not resto_g.is_empty and resto_g.area >= AREA_MIN_RESTO:
            ultima = rebanadas[-1] if rebanadas else None
            tope = (ultima[0].util_m2 * 1.25 / FACTOR_UTIL_REBANADA) if ultima else 0.0
            if (ultima is not None and resto_g.distance(ultima[1]) < 0.40
                    and ultima[1].area + resto_g.area <= tope):
                fusion = _union([ultima[1], resto_g])
                if isinstance(fusion, Polygon):
                    rebanadas[-1] = (ultima[0], fusion)
                    resto_g = Polygon()
            if not resto_g.is_empty and resto_g.area >= AREA_MIN_RESTO:
                planta.piezas.append(PiezaSingular(
                    geometry=resto_g, tipo="resto", nombre="Resto",
                    area_m2=resto_g.area, target_m2=0.0,
                ))
        pendientes = siguientes

    # ── Muros divisorios + evaluación de unidades ───────────────────────────
    todas_piezas = [g for _, g in rebanadas] + [p.geometry for p in planta.piezas] \
        + ([corr_geom] if not corr_geom.is_empty else []) + ([nucleo_geom] if nucleo else [])
    if len(todas_piezas) >= 2:
        bordes = unary_union([g.boundary for g in todas_piezas if not g.is_empty])
        muros_div = _mayor(bordes.buffer(esp_div / 2.0).intersection(interior_a))
    else:
        muros_div = Polygon()

    fach_segs = fach_efectiva
    colocadas: dict[int, tuple[_Target, Polygon]] = {t.j: (t, g) for t, g in rebanadas}
    for t in targets:
        if t.j in colocadas:
            _, g_constr = colocadas[t.j]
            g_util = _mayor(make_valid(g_constr).difference(muros_div)) if not muros_div.is_empty else g_constr
            u = _evaluar_unidad(
                t, g_util, g_constr, corr_geom, fach_segs, patios_a, params,
                nombre_planta=nombre, principales_m2=principales_m2,
            )
        else:
            u = UnidadDispuesta(
                id="", slug=t.slug, tipo_unidad=t.tipo_unidad, n_dorms=t.n_dorms,
                util_objetivo_m2=round(t.util_m2, 2), util_min_m2=round(t.util_min_m2, 2),
                geometry_util=Polygon(), geometry_constr=Polygon(), ubicada=False,
                incidencias=[
                    f"{nombre}: la unidad de {t.util_m2:.1f} m² no encuentra sitio "
                    f"en la planta (frente o fondo insuficientes)."
                ],
            )
        planta.unidades.append(u)

    # ── Circulaciones serializables ─────────────────────────────────────────
    if not corr_geom.is_empty:
        portal_geom = Polygon()
        if es_pb and nucleo is not None:
            x_nuc0 = nucleo_geom.bounds[0]
            if x_nuc0 - mnx_i > 0.30:
                # Zaguán de acceso: tramo de circulación entre el borde de acceso
                # y el núcleo. Se ensancha en y hasta `ancho_portal` tomando solo
                # del espacio libre (nunca de unidades ya colocadas).
                ancho_portal = max(cy1 - cy0, getattr(d, "ancho_portal", 3.0))
                yc_p = (cy0 + cy1) / 2.0
                ocupado = _union(
                    [g for _, g in rebanadas] + [nucleo_geom] + patios_a
                    + [p.geometry for p in planta.piezas])
                zona_portal = box(mnx_i, yc_p - ancho_portal / 2.0, x_nuc0, yc_p + ancho_portal / 2.0)
                zona_portal = make_valid(zona_portal.intersection(interior_a))
                if not ocupado.is_empty:
                    zona_portal = make_valid(zona_portal.difference(ocupado))
                portal_geom = _union([_mayor(zona_portal),
                                      box(mnx_i, cy0, x_nuc0, cy1).intersection(_union([corr_geom]))])
                portal_geom = _mayor(portal_geom)
                # Ø1,50 en el encuentro portal ↔ pasillo ↔ núcleo.
                ref_p = Point(((x_nuc0 + mnx_i) / 2.0, yc_p))
                _, radio_p = _circulo_libre(_union([portal_geom, corr_geom]), ref_p,
                                            radio_busqueda=2.0 * d.diametro_min_vestibulo)
                if radio_p + 1e-3 < d.diametro_min_vestibulo / 2.0:
                    planta.incidencias.append(
                        f"{nombre}: el zaguán de acceso no inscribe la circunferencia "
                        f"libre mínima (Ø{d.diametro_min_vestibulo:.2f} m).")
        resto_corr = _union([corr_geom]).difference(portal_geom) if not portal_geom.is_empty else corr_geom
        # Galería (A2.1): el pasillo linda con fachada/patio en la mayor parte de su traza.
        lon_corr = max(1e-6, sum(p.length for p in _partes(resto_corr)) / 2.0)
        frente_galeria = _contacto(_mayor(resto_corr), fach_segs, tol=d.espesor_muro_fachada + 0.2)
        if patio_extra is not None:
            frente_galeria += _contacto(_mayor(resto_corr), patio_extra.geometry.boundary, tol=0.3)
        tipo_corr = "galeria" if frente_galeria > 0.5 * lon_corr else "pasillo"
        planta.tipologia_circulacion = tipo_corr
        for p in _partes(resto_corr):
            planta.circulaciones.append(PiezaCirculacion(
                geometry=p, tipo=tipo_corr, ancho_m=cw, area_m2=p.area))
        if not portal_geom.is_empty:
            pb_portal = portal_geom.bounds
            planta.circulaciones.append(PiezaCirculacion(
                geometry=portal_geom, tipo="portal",
                ancho_m=round(pb_portal[3] - pb_portal[1], 2), area_m2=portal_geom.area))
    planta.circulaciones.extend(vestibulos)

    # Patios (reubicados) + franja residual: en coords alineadas hasta el final.
    for g in patios_a:
        if not g.is_empty:
            b = g.bounds
            planta.patios_nuevos.append(Patio(
                geometry=g, area_m2=g.area, luz_recta_m=min(b[2] - b[0], b[3] - b[1])))
    if patio_extra is not None:
        planta.patios_nuevos.append(patio_extra)
    planta.muros_divisorios = muros_div
    planta.superficies = _superficies_planta(planta, footprint.area)
    return planta


def _cortar_pieza_singular(
    bandas: list[_Banda], tipo: str, nombre: str, target_util: float,
    fach_segs, corredor, d,
) -> PiezaSingular | None:
    """Local / zonas sociales de PB: el frente de fachada manda; si la rebanada
    vertical daría escaparate estrecho, se corta en horizontal pegada a fachada."""
    target_constr = target_util / FACTOR_UTIL_REBANADA
    for b in bandas:
        comp = b.geom
        if comp.is_empty or comp.area < 0.5 * target_constr:
            continue
        x0 = comp.bounds[0]
        x_corte = _corte_por_area(comp, x0, target_constr)
        ancho = x_corte - x0
        if ancho < FRENTE_MIN_LOCAL:
            x_corte = min(x0 + FRENTE_MIN_LOCAL, comp.bounds[2])
        pieza = _rebanada(comp, x0, x_corte, corredor)
        if pieza.is_empty:
            continue
        if pieza.area > target_constr * 1.25:
            # Corte horizontal: solo el fondo necesario desde la fachada.
            pb = pieza.bounds
            fondo = target_constr / max(0.5, x_corte - x0)
            if b.borde_ventilacion == "ymax":
                recorte = box(pb[0], pb[3] - fondo, pb[2], pb[3])
            else:
                recorte = box(pb[0], pb[1], pb[2], pb[1] + fondo)
            pieza_h = _mayor(pieza.intersection(recorte))
            if not pieza_h.is_empty:
                pieza = pieza_h
        b.geom = _mayor(make_valid(comp).difference(pieza))
        frente = _contacto(pieza, fach_segs, tol=0.5)
        return PiezaSingular(
            geometry=pieza, tipo=tipo, nombre=nombre,
            area_m2=pieza.area, target_m2=target_util, frente_fachada_m=round(frente, 2),
        )
    return None


def _evaluar_unidad(
    t: _Target, g_util: Polygon, g_constr: Polygon, corredor, fach_segs, patios_a,
    params: Parametros, nombre_planta: str,
    principales_m2: Callable[[str, int, float], float] | None,
) -> UnidadDispuesta:
    d = params.diseno
    area_util = g_util.area

    borde_pas = _contacto(g_util, corredor.boundary if not corredor.is_empty else None, tol=0.30) \
        if corredor is not None else 0.0
    acceso = borde_pas >= d.radio_apertura_puerta

    # Frente de fachada = longitud de la LÍNEA de fachada cubierta por la unidad
    # (no el contorno de la unidad en una franja, que sumaría sus laterales). La
    # unidad arranca a `espesor_muro` de la línea (interior erosionado), de ahí
    # el buffer perpendicular; se descuentan los dos extremos que el buffer
    # añade (≈ d_perp por extremo) para no sobreestimar el hueco disponible.
    d_perp = d.espesor_muro_fachada + 0.10
    try:
        if fach_segs.is_empty:
            frente_fach = 0.0
        else:
            bruto = float(fach_segs.intersection(g_constr.buffer(d_perp)).length)
            ancho_bbox = g_constr.bounds[2] - g_constr.bounds[0]
            frente_fach = max(0.0, min(bruto - 2.0 * d_perp, ancho_bbox)) if bruto > 0 else 0.0
    except GEOSException:
        frente_fach = 0.0
    patios_union = _union(patios_a)
    borde_patio = _contacto(g_constr, patios_union.boundary, tol=0.35) \
        if not patios_union.is_empty else 0.0

    # Superficie de estancias principales (para el hueco del 10%): de las
    # estancias REALES de la tipología si hay callable; si no, heurística.
    if principales_m2 is not None:
        area_principal = max(4.0, principales_m2(t.slug, t.n_dorms, t.util_m2))
    else:
        area_principal = max(8.0, t.util_m2 * 0.70)
    hueco_req = 0.10 * area_principal
    hueco_disp = frente_fach * ALTURA_HUECO
    ventila_ok = frente_fach > 0.5 and hueco_disp + 1e-3 >= hueco_req

    if ventila_ok:
        vent_tipo = "fachada+patio" if borde_patio > 0.10 else "fachada"
    elif borde_patio > 0.10:
        vent_tipo = "solo patio (insuficiente)"
    else:
        vent_tipo = "ninguna"

    cumple_min = area_util + 1e-3 >= t.util_min_m2

    bb = g_constr.bounds
    frente = max(0.10, bb[2] - bb[0])
    fondo = max(0.10, bb[3] - bb[1])
    fondo_frente = round(max(fondo, frente) / min(fondo, frente), 2)
    tope_ff = FONDO_FRENTE_MAX.get(t.tipo_unidad, FONDO_FRENTE_MAX["default"])
    proporcion_ok = fondo_frente <= tope_ff

    incidencias: list[str] = []
    if not acceso:
        incidencias.append(f"{nombre_planta}: unidad sin acceso directo desde el pasillo común.")
    if not ventila_ok:
        if frente_fach <= 0.5 and borde_patio > 0.10:
            incidencias.append(
                f"{nombre_planta}: estancias principales sin frente de fachada "
                f"(el patio mínimo solo ventila cocinas y baños)."
            )
        else:
            incidencias.append(
                f"{nombre_planta}: hueco de fachada insuficiente "
                f"({hueco_disp:.1f}/{hueco_req:.1f} m²)."
            )
    if not cumple_min:
        incidencias.append(
            f"{nombre_planta}: {area_util:.1f} m² útiles < mínimo "
            f"{t.util_min_m2:.1f} m² de la tipología."
        )
    if not proporcion_ok:
        incidencias.append(
            f"{nombre_planta}: proporción fondo/frente {fondo_frente:.1f} "
            f"poco realista para la tipología."
        )

    return UnidadDispuesta(
        id="", slug=t.slug, tipo_unidad=t.tipo_unidad, n_dorms=t.n_dorms,
        util_objetivo_m2=round(t.util_m2, 2), util_min_m2=round(t.util_min_m2, 2),
        geometry_util=g_util, geometry_constr=g_constr,
        area_util_m2=round(area_util, 2), area_constr_m2=round(g_constr.area, 2),
        ubicada=True, acceso_pasillo=acceso, borde_pasillo_m=round(borde_pas, 2),
        frente_fachada_m=round(frente_fach, 2), ventilacion_tipo=vent_tipo,
        hueco_req_m2=round(hueco_req, 2), hueco_disp_m2=round(hueco_disp, 2),
        ventila_ok=ventila_ok, cumple_min=cumple_min,
        fondo_frente=fondo_frente, proporcion_ok=proporcion_ok,
        incidencias=incidencias,
    )


def _superficies_planta(planta: PlantaDispuesta, construida: float) -> dict:
    util_unidades = sum(u.area_util_m2 for u in planta.unidades if u.ubicada)
    circ = sum(c.area_m2 for c in planta.circulaciones)
    nucleo = planta.nucleo.area_m2 if planta.nucleo is not None else 0.0
    patios = sum(p.area_m2 for p in planta.patios) \
        + sum(p.area_m2 for p in planta.patios_nuevos)
    local = sum(p.area_m2 for p in planta.piezas if p.tipo == "local")
    social = sum(p.area_m2 for p in planta.piezas if p.tipo == "zona_social")
    resto = sum(p.area_m2 for p in planta.piezas if p.tipo == "resto")
    return {
        "construida_m2": round(construida, 2),
        "util_unidades_m2": round(util_unidades, 2),
        "circulacion_m2": round(circ, 2),
        "nucleo_m2": round(nucleo, 2),
        "patios_m2": round(patios, 2),
        "local_m2": round(local, 2),
        "zona_social_m2": round(social, 2),
        "resto_m2": round(resto, 2),
    }


# ─── Conciliación dibujo ↔ cálculo ──────────────────────────────────────────
def _conciliar(planta: PlantaDispuesta, cap: Capacidad, i: int) -> dict:
    sup = planta.superficies or {}
    # La referencia útil es la SUMA DE TARGETS de las unidades de la planta (lo
    # que el plano debe dibujar), no el útil neto de planta: el sobrante tras
    # truncar unidades ya lo avisa el propio cálculo.
    unidades_i = cap.unidades_por_planta[i] if i < len(cap.unidades_por_planta) else []
    util_calc = sum(u for _, u in unidades_i)
    util_neta = cap.util_por_planta[i] if i < len(cap.util_por_planta) else 0.0
    circ_calc = cap.circulacion_por_planta[i] if i < len(cap.circulacion_por_planta) else 0.0
    nucleo_calc = cap.nucleo_por_planta[i] if i < len(cap.nucleo_por_planta) else 0.0
    local_calc = cap.local_por_planta[i] if i < len(cap.local_por_planta) else 0.0

    # Las comunes obligatorias están repartidas en la circulación calculada de
    # cada planta habitable, pero se DIBUJAN concentradas en PB (zonas sociales).
    descuento = (cap.area_servicios_comunes_m2 / cap.n_plantas_habitables
                 if cap.n_plantas_habitables else 0.0)
    if planta.tipo != "sotano":
        circ_calc = max(0.0, circ_calc - descuento)

    def _desv(dib: float, calc: float) -> float | None:
        if calc <= 1e-6:
            return None
        return round((dib - calc) / calc * 100.0, 1)

    return {
        "util_dibujada_m2": sup.get("util_unidades_m2", 0.0),
        "util_calculada_m2": round(util_calc, 2),
        "util_neta_planta_m2": round(util_neta, 2),
        "desv_util_pct": _desv(sup.get("util_unidades_m2", 0.0), util_calc),
        "circulacion_dibujada_m2": sup.get("circulacion_m2", 0.0),
        "circulacion_calculada_m2": round(circ_calc, 2),
        "desv_circulacion_pct": _desv(sup.get("circulacion_m2", 0.0), circ_calc),
        "nucleo_dibujado_m2": sup.get("nucleo_m2", 0.0),
        "nucleo_calculado_m2": round(nucleo_calc, 2),
        "local_dibujado_m2": sup.get("local_m2", 0.0),
        "local_calculado_m2": round(local_calc, 2),
        "zona_social_dibujada_m2": sup.get("zona_social_m2", 0.0),
    }


# ─── Score de candidato ──────────────────────────────────────────────────────
def _puntuar(edif: EdificioDispuesto) -> float:
    unidades = [u for pl in edif.plantas for u in pl.unidades]
    if not unidades:
        return 0.0
    ubicadas = [u for u in unidades if u.ubicada]
    n, nu = len(unidades), len(ubicadas)
    f_ubic = nu / n
    f_vent = (sum(1 for u in ubicadas if u.ventila_ok) / nu) if nu else 0.0
    f_acc = (sum(1 for u in ubicadas if u.acceso_pasillo) / nu) if nu else 0.0
    f_min = (sum(1 for u in ubicadas if u.cumple_min) / nu) if nu else 0.0
    f_prop = (sum(1 for u in ubicadas if u.proporcion_ok) / nu) if nu else 0.0
    desvs = [abs(pl.conciliacion.get("desv_util_pct") or 0.0) / 100.0
             for pl in edif.plantas if pl.conciliacion]
    f_fid = max(0.0, 1.0 - (sum(desvs) / len(desvs) if desvs else 1.0))
    nucleos_ok = [pl.nucleo.circulo_ok for pl in edif.plantas if pl.nucleo is not None]
    f_nuc = 1.0 if (nucleos_ok and all(nucleos_ok)) else 0.0
    # El acceso del edificio debe darse por fachada, nunca por medianera (A2.1+A2.4).
    f_acceso = 1.0 if edif.acceso_en_fachada else 0.0
    score = (0.26 * f_vent + 0.20 * f_ubic + 0.14 * f_acc + 0.10 * f_min
             + 0.10 * f_prop + 0.07 * f_fid + 0.06 * f_nuc + 0.07 * f_acceso)
    return round(100.0 * score, 1)


# ─── Punto de entrada ────────────────────────────────────────────────────────
def repartir_unidades(
    envolvente: Envolvente,
    lados: list[LadoParcela],
    params: Parametros,
    cap: Capacidad,
    *,
    minimos_por_slug: dict[str, float] | None = None,
    tipo_unidad: str = "vivienda",
    principales_m2: Callable[[str, int, float], float] | None = None,
    area_social_m2: float = 0.0,
) -> EdificioDispuesto:
    """Dispone en planta las unidades que dicta el cálculo (`cap`).

    - `minimos_por_slug`: útil mínimo del Anexo I por tipología (de BBDD vía
      descriptores). Vivienda cae a `util_minimo_vivienda(n_dorms)`.
    - `principales_m2(slug, n_dorms, util)`: m² de estancias principales de una
      unidad (para dimensionar su hueco de fachada). Opcional.
    - `area_social_m2`: comunes obligatorias del uso (Decreto) → pieza «Zonas
      sociales» en PB.

    Devuelve SIEMPRE un `EdificioDispuesto` con tantas plantas como la
    envolvente y tantas unidades por planta como el cálculo (las imposibles,
    como «no ubicadas»). Lanza `ValueError` solo si no hay plantas.
    """
    if not envolvente.plantas:
        raise ValueError("La envolvente no tiene plantas que repartir.")

    regulares = [p for p in envolvente.plantas if p.tipo == "regular"]
    base = max(regulares, key=lambda p: p.footprint.area) if regulares else envolvente.plantas[0]
    if base.footprint.is_empty or base.interior.is_empty:
        # P. ej. única planta ático con huella vaciada por el retranqueo: el
        # caso de uso lo degrada a edificio:null (no es un dibujo posible).
        raise ValueError("La huella de la planta base está vacía.")
    ang_rad, (cx, cy) = _angulo_marco(base.footprint, lados)
    ang0 = math.degrees(ang_rad)

    # Ángulo de la fachada dominante: candidato adicional imprescindible en
    # huellas donde el lado largo del MRR es oblicuo a la fachada (triángulos,
    # parcelas irregulares) — si no, el marco se alinea con el sesgo y ninguna
    # unidad da a fachada.
    fachadas = [l for l in lados if l.tipo == "fachada"]
    ang_fachada = None
    if fachadas:
        ldom = max(fachadas, key=lambda l: l.longitud_m)
        ang_fachada = math.degrees(math.atan2(ldom.p2[1] - ldom.p1[1], ldom.p2[0] - ldom.p1[0]))

    # Ascensor obligatorio según nº de plantas (A2.1); por debajo, solo escalera.
    con_ascensor = len(envolvente.plantas) >= int(getattr(params.diseno, "plantas_para_ascensor", 3))

    # Región de continuidad vertical del núcleo: intersección de los interiores
    # de todas las plantas. Si el ático la rompe, se reintenta sin él (casetón).
    interiores = [make_valid(p.interior) for p in envolvente.plantas if not p.interior.is_empty]
    region_total = interiores[0]
    for g in interiores[1:]:
        region_total = make_valid(region_total.intersection(g))
    interiores_sin_atico = [make_valid(p.interior) for p in envolvente.plantas
                            if p.tipo != "atico" and not p.interior.is_empty]
    region_sin_atico = interiores_sin_atico[0] if interiores_sin_atico else region_total
    for g in interiores_sin_atico[1:]:
        region_sin_atico = make_valid(region_sin_atico.intersection(g))

    adaptadas = indices_adaptadas(cap, params.programa.pct_unidades_adaptadas)

    # Ángulos base a explorar (el de fachada solo si difiere del del MRR).
    bases = [(ang0, "mrr")]
    if ang_fachada is not None and abs(((ang_fachada - ang0 + 90) % 180) - 90) > 3.0:
        bases.append((ang_fachada, "fach"))

    candidatos: list[EdificioDispuesto] = []
    vistos_ang: set[int] = set()
    for ang_base, etq_base in bases:
        for rot90, flip in [(False, False), (False, True), (True, False), (True, True)]:
            ang = ang_base + (90.0 if rot90 else 0.0) + (180.0 if flip else 0.0)
            clave = int(round(ang % 360))
            if clave in vistos_ang:
                continue
            vistos_ang.add(clave)
            try:
                cand = _construir_candidato(
                    envolvente, lados, params, cap, ang, cx, cy,
                    region_total, region_sin_atico, adaptadas,
                    minimos_por_slug, tipo_unidad, principales_m2, area_social_m2,
                    con_ascensor,
                    estrategia=f"{etq_base}·rot{'90' if rot90 else '0'}{'·esp' if flip else ''}",
                )
            except (GEOSException, ValueError):
                continue
            cand.score = _puntuar(cand)
            candidatos.append(cand)

    if not candidatos:
        raise ValueError("Ningún candidato de reparto produjo una planta dibujable.")
    candidatos.sort(key=lambda e: -e.score)  # sort estable: empate → primer candidato
    mejor = candidatos[0]
    _alertas_edificio(mejor, cap)
    return mejor


def _construir_candidato(
    envolvente: Envolvente,
    lados: list[LadoParcela],
    params: Parametros,
    cap: Capacidad,
    ang: float,
    cx: float,
    cy: float,
    region_total: Polygon,
    region_sin_atico: Polygon,
    adaptadas: set[tuple[int, int]],
    minimos_por_slug: dict[str, float] | None,
    tipo_unidad: str,
    principales_m2,
    area_social_m2: float,
    con_ascensor: bool,
    estrategia: str,
) -> EdificioDispuesto:
    al, mu = _transformaciones(ang, cx, cy)
    segs = _segmentos_por_tipo(lados, al)

    regulares = [p for p in envolvente.plantas if p.tipo == "regular"]
    base = max(regulares, key=lambda p: p.footprint.area) if regulares else envolvente.plantas[0]
    fp_a = _mayor(al(base.footprint))
    interior_base_a = _mayor(al(base.interior))
    if interior_base_a.is_empty:
        raise ValueError("Interior de la planta base vacío.")
    edges = _clasificar_bordes(fp_a, segs)
    layout = _resolver_layout_y(interior_base_a.bounds, edges, params)
    # El edificio tiene acceso desde vía pública si la huella tiene algún frente
    # de fachada. Solo las parcelas sin fachada (interiores, en bandera) carecen
    # de acceso directo — ahí salta la alerta (no en el caso común entre
    # medianeras, donde la fachada está en un lado largo).
    acceso_en_fachada = any(t == "fachada" for t in edges.values())

    # Núcleo único (continuidad vertical). Prioridad: (1) bien colocado (sin
    # invadir la banda de unidades) cabiendo en todas las plantas; (2) bien
    # colocado como casetón sobre el retranqueo del ático; (3) donde quepa.
    nucleo = None
    caseton = False
    region_a = _mayor(al(region_total))
    region_b = _mayor(al(region_sin_atico))
    if not region_a.is_empty:
        nucleo = _construir_nucleo(region_a, layout, params, solo_preferidos=True, con_ascensor=con_ascensor)
    if nucleo is None and not region_b.is_empty and not region_b.equals(region_a):
        nucleo = _construir_nucleo(region_b, layout, params, solo_preferidos=True, con_ascensor=con_ascensor)
        caseton = nucleo is not None
    if nucleo is None and not region_a.is_empty:
        nucleo = _construir_nucleo(region_a, layout, params, con_ascensor=con_ascensor)
    if nucleo is None and not region_b.is_empty:
        nucleo = _construir_nucleo(region_b, layout, params, con_ascensor=con_ascensor)
        caseton = nucleo is not None

    edif = EdificioDispuesto(plantas=[], n_unidades=0, n_unidades_ubicadas=0,
                             estrategia=estrategia, acceso_en_fachada=acceso_en_fachada)
    idx_pb = next((i for i, p in enumerate(envolvente.plantas) if p.tipo == "regular"), None)

    for i, pl_env in enumerate(envolvente.plantas):
        nombre = cap.nombres_planta[i] if i < len(cap.nombres_planta) else f"#{i}"
        targets = _targets_planta(cap, i, tipo_unidad, minimos_por_slug)
        local_i = cap.local_por_planta[i] if i < len(cap.local_por_planta) else 0.0
        es_pb = (i == idx_pb)
        social_i = area_social_m2 if es_pb else 0.0
        try:
            planta = _disponer_planta(
                i, pl_env, nombre, targets, local_i, social_i, nucleo, layout,
                edges, segs, params, al, es_pb, principales_m2,
            )
        except (GEOSException, ValueError) as exc:
            # Cortafuegos por planta: la planta cae a huella + incidencia, las
            # demás siguen. Nunca se pierde el edificio entero por una planta.
            planta = PlantaDispuesta(
                indice=i, n=pl_env.n, nombre=nombre, tipo=pl_env.tipo,
                footprint=pl_env.footprint, interior=pl_env.interior,
                muros_perimetrales=Polygon(), nucleo=nucleo, nucleo_es_caseton=False,
                circulaciones=[], patios=list(pl_env.patios), piezas=[],
                unidades=[UnidadDispuesta(
                    id="", slug=t.slug, tipo_unidad=t.tipo_unidad, n_dorms=t.n_dorms,
                    util_objetivo_m2=round(t.util_m2, 2), util_min_m2=round(t.util_min_m2, 2),
                    geometry_util=Polygon(), geometry_constr=Polygon(), ubicada=False,
                ) for t in targets],
                muros_divisorios=Polygon(), tipologia_circulacion="pasillo",
                incidencias=[f"{nombre}: no se pudo disponer la planta ({exc})."],
            )
        if caseton and pl_env.tipo == "atico":
            planta.nucleo_es_caseton = True
        # Identidad y adaptadas — MISMO esquema que la tabla por unidad.
        for u, t in zip(planta.unidades, targets):
            letra = chr(ord("A") + t.j) if t.j < 26 else f"#{t.j + 1}"
            u.id = f"V{i + 1}{letra}"
            u.es_adaptada = (i, t.j) in adaptadas
        planta.conciliacion = _conciliar(planta, cap, i)
        edif.plantas.append(planta)

    # Devolver a coordenadas mundo. El núcleo es un único objeto compartido:
    # se transforma una sola vez y se reasigna a todas las plantas.
    nucleo_mundo: NucleoEdificio | None = None
    if nucleo is not None:
        nucleo_mundo = NucleoEdificio(
            geometry=mu(nucleo.geometry),
            escalera=mu(nucleo.escalera) if not nucleo.escalera.is_empty else Polygon(),
            ascensor=mu(nucleo.ascensor) if not nucleo.ascensor.is_empty else Polygon(),
            vestibulo=mu(nucleo.vestibulo) if not nucleo.vestibulo.is_empty else Polygon(),
            circulo_centro=tuple(mu(Point(nucleo.circulo_centro)).coords[0]),
            circulo_radio=nucleo.circulo_radio, circulo_ok=nucleo.circulo_ok,
            area_m2=nucleo.area_m2,
        )
    for pl in edif.plantas:
        pl.muros_divisorios = mu(pl.muros_divisorios) if not pl.muros_divisorios.is_empty else Polygon()
        for u in pl.unidades:
            if not u.geometry_util.is_empty:
                u.geometry_util = mu(u.geometry_util)
            if not u.geometry_constr.is_empty:
                u.geometry_constr = mu(u.geometry_constr)
        for c in pl.circulaciones:
            c.geometry = mu(c.geometry)
        for p in pl.piezas:
            p.geometry = mu(p.geometry)
        for p in pl.patios_nuevos:
            pl.patios.append(Patio(geometry=mu(p.geometry), area_m2=p.area_m2,
                                   luz_recta_m=p.luz_recta_m))
        pl.patios_nuevos = []
        if pl.nucleo is not None:
            pl.nucleo = nucleo_mundo

    unidades = [u for pl in edif.plantas for u in pl.unidades]
    edif.n_unidades = len(unidades)
    edif.n_unidades_ubicadas = sum(1 for u in unidades if u.ubicada)
    return edif


def _alertas_edificio(edif: EdificioDispuesto, cap: Capacidad) -> None:
    """Alertas agregadas (anti-ruido): una por concepto y grupo de plantas."""
    no_ubicadas = [u for pl in edif.plantas for u in pl.unidades if not u.ubicada]
    if no_ubicadas:
        edif.alertas.append(AlertaReparto(
            "aviso", "Capacidad",
            f"{len(no_ubicadas)} de {edif.n_unidades} unidades calculadas no caben "
            f"en el plano con los criterios de diseño actuales (ver detalle por planta).",
        ))

    ubicadas = [u for pl in edif.plantas for u in pl.unidades if u.ubicada]
    sin_vent = [u for u in ubicadas if not u.ventila_ok]
    if ubicadas and len(sin_vent) == len(ubicadas):
        edif.alertas.append(AlertaReparto(
            "incumplimiento", "Normativa",
            "Ninguna unidad consigue frente de fachada suficiente para ventilar "
            "sus estancias principales en esta parcela.",
        ))
    elif sin_vent:
        edif.alertas.append(AlertaReparto(
            "aviso", "Normativa",
            f"{len(sin_vent)} unidades sin hueco de fachada suficiente para sus "
            f"estancias principales.",
            elemento=", ".join(u.id for u in sin_vent[:8]),
        ))

    sin_acceso = [u for u in ubicadas if not u.acceso_pasillo]
    if sin_acceso:
        edif.alertas.append(AlertaReparto(
            "aviso", "Normativa",
            f"{len(sin_acceso)} unidades sin acceso directo desde el pasillo común.",
            elemento=", ".join(u.id for u in sin_acceso[:8]),
        ))

    if not edif.acceso_en_fachada:
        edif.alertas.append(AlertaReparto(
            "aviso", "Normativa",
            "El acceso del edificio no encuentra frente directo a vía pública en "
            "esta parcela; verificar la entrada desde fachada.",
        ))

    if any(pl.nucleo_es_caseton for pl in edif.plantas):
        edif.alertas.append(AlertaReparto(
            "info", "Normativa",
            "El núcleo de comunicaciones emerge como casetón sobre el retranqueo "
            "del ático — verificar la ordenanza municipal.",
        ))
    nucleos = [pl.nucleo for pl in edif.plantas if pl.nucleo is not None]
    if not nucleos:
        edif.alertas.append(AlertaReparto(
            "incumplimiento", "Normativa",
            "No cabe el núcleo de escalera y ascensor en la huella del edificio.",
        ))
    elif not nucleos[0].circulo_ok:
        edif.alertas.append(AlertaReparto(
            "aviso", "Normativa",
            "El vestíbulo del núcleo no inscribe la circunferencia libre mínima.",
        ))

    # Conciliación: una alerta informativa por grupo de plantas con desviación.
    grupos: dict[tuple[int, int], list[str]] = {}
    for pl in edif.plantas:
        if pl.tipo == "sotano" or not pl.conciliacion or not pl.unidades:
            continue
        du = pl.conciliacion.get("desv_util_pct")
        dc = pl.conciliacion.get("desv_circulacion_pct")
        if du is None or abs(du) <= 15.0:
            continue
        clave = (round((du or 0) / 5.0), round((dc or 0) / 5.0))
        grupos.setdefault(clave, []).append(pl.nombre)
    for (du5, _), nombres in sorted(grupos.items()):
        edif.alertas.append(AlertaReparto(
            "info", "Capacidad",
            f"{', '.join(nombres)}: la superficie útil dibujada se desvía "
            f"≈{du5 * 5:+d}% de la calculada (la tabla manda; el plano es orientativo).",
        ))
