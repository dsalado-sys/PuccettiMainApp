"""Disposición geométrica interior del edificio (§2.5 — dibujo «Pintar render»).

Motor NUEVO (no resucita `Modulos/…/macro_layout.py`). Por cada ZONA edificable de
cada planta EMPAQUETA el NÚCLEO y las UNIDADES como un **bloque compacto contiguo**:
cada elemento es un cuadrado dimensionado por sus m² que se **adapta a los límites**
manteniendo SIEMPRE su área (mecanismo «área fija, forma flexible» de los patios,
`conformar_patio` de `envolvente.py`), colocado PEGADO al bloque ya puesto —
compartiendo muros medianeros, sin holgura entre unidades— y anclado hacia la ESQUINA
de FACHADA de la zona. La CIRCULACIÓN es la superficie sobrante (`zona − bloque`), que
queda como una franja contigua a un lado (al interior). Es el criterio elegido por el
arquitecto («bloque compacto») frente a unidades «flotando» centradas con holgura.

Reintentos y rojo: si en un intento algún elemento no alcanza su área, se REINTENTA
la zona variando el ORDEN de colocación (lista determinista de K estrategias) y se
conserva el intento con menos fallos; los elementos que sigan sin caber se dibujan en
su mejor forma con `cumple_minimos=False` (rojo) para que el arquitecto los reubique.
NUNCA se borra una unidad: se dibujan siempre las `cap.viv_por_planta[i]`.

Limitación conocida de Fases 1-2 (multi-zona): el contrato del canvas lleva UN núcleo
por planta (`nucleo: {poligono}`, `ring()` de un solo polígono). Cuando una planta se
parte en varias zonas se dibuja el núcleo de la zona MAYOR; garantizar acceso/núcleo
por zona es materia de la Fase 3 (conexión a fachada + casos límite).

Geometría vectorial pura (shapely), sin FastAPI/SQLAlchemy, como el resto de
`geometria/`. Reutiliza la maquinaria de área fija de `envolvente.py` y la detección
de zonas de `zonas.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from shapely.geometry import Point, Polygon, box
from shapely.ops import nearest_points, unary_union

from .config import Parametros
from .envolvente import _normalizar, conformar_patio
from .zonas import _componentes, detectar_zonas_edificables, repartir_por_area


# ─── Contrato de salida (polígonos shapely UTM) ────────────────────────────
@dataclass
class UnidadDispuesta:
    id: str
    poligono_construido: Polygon        # forma adaptada (área = construida)
    poligono_util: Polygon              # Fase 2: = construido (Fase 3 restará tabiquería)
    area_util_m2: float                 # útil objetivo de la unidad
    cumple_minimos: bool                # alcanzó su área tras los reintentos (False → rojo)
    es_adaptada: bool = False           # accesibilidad DB-SUA (de cap.n_unidades_adaptadas)


@dataclass
class NucleoDispuesto:
    poligono: Polygon


@dataclass
class PlantaDispuesta:
    n: int
    nombre: str
    tipo: str
    footprint: Polygon
    patios: list = field(default_factory=list)       # list[envolvente.Patio] (se reemiten)
    nucleo: Optional[NucleoDispuesto] = None
    unidades: list = field(default_factory=list)     # list[UnidadDispuesta]
    pasillos: list = field(default_factory=list)     # list[Polygon] (circulación sobrante)


@dataclass
class EdificioDispuesto:
    plantas: list = field(default_factory=list)      # list[PlantaDispuesta]


# ─── Colocación COMPACTA (bloque contiguo, muros medianeros) ────────────────
# El arquitecto quiere las unidades EMPAQUETADAS juntas (compartiendo muros) formando
# un bloque contiguo anclado hacia fachada, con la circulación como franja sobrante a
# un lado — no cuadrados «flotando» centrados con holgura. Cada elemento se ancla al
# punto del hueco libre MÁS CERCANO a la esquina de fachada y crece manteniendo su
# área fija (mecanismo de los patios), pegándose a lo ya colocado (holgura 0).
def _ancla_zona(zona: Polygon, footprint) -> Point:
    """Esquina de la zona hacia la que se empaqueta el bloque: la más cercana a la
    FACHADA (borde exterior de la huella), para que las unidades den a fachada y la
    circulación quede al interior. Sin huella válida, cae a la esquina inferior-izda.
    """
    minx, miny, maxx, maxy = zona.bounds
    esquinas = [Point(minx, miny), Point(maxx, miny), Point(maxx, maxy), Point(minx, maxy)]
    borde = getattr(footprint, "exterior", None) if footprint is not None else None
    if borde is None:
        return esquinas[0]
    return min(esquinas, key=lambda c: c.distance(borde))


def _seed_cuadrado(region: Polygon, area: float, ancla: Point) -> Optional[Polygon]:
    """Cuadrado de `area` m² pegado al punto de `region` más cercano a `ancla`, creciendo
    hacia el interior de `region`. Semilla del empaquetado: cada nueva pieza nace pegada
    a la esquina/al bloque ya colocado. None si `region` está vacía.
    """
    reg = _normalizar(region)
    if reg.is_empty or area <= 0:
        return None
    p = nearest_points(ancla, reg)[1]         # punto de la región libre pegado al ancla
    lado = max(0.5, area ** 0.5)
    c = reg.centroid                          # crecer hacia el interior de la región
    dx = lado if c.x >= p.x else -lado
    dy = lado if c.y >= p.y else -lado
    return box(min(p.x, p.x + dx), min(p.y, p.y + dy), max(p.x, p.x + dx), max(p.y, p.y + dy))


def _colocar_compacto(zona: Polygon, colocados: list, area: float, ancla: Point):
    """Coloca un elemento PEGADO al bloque ya colocado (muros medianeros, sin holgura),
    anclado hacia `ancla`, adaptándolo para conservar su área. Devuelve `(poligono, cabe)`.

    Garantías: nunca se apila exactamente sobre lo colocado (nace en el hueco libre
    `zona − colocados`); nunca devuelve vacío si `zona` no lo está (una unidad no se
    borra). `cabe=False` (rojo) si no alcanza su área o si hubo que solaparlo.
    """
    if area <= 0 or zona is None or zona.is_empty:
        return Polygon(), False

    ocupados = [g for g in colocados if g is not None and not g.is_empty]
    libre = _normalizar(zona.difference(unary_union(ocupados))) if ocupados else _normalizar(zona)

    # 1) En el hueco libre, pegado al bloque/esquina.
    if not libre.is_empty:
        seed = _seed_cuadrado(libre, area, ancla)
        if seed is not None:
            seed = _normalizar(seed)
            if not seed.is_empty:
                efectiva, _a, cabe = conformar_patio(seed, libre, area, 0.0, footprint=zona)
                efectiva = _normalizar(efectiva)
                if not efectiva.is_empty:
                    return efectiva, bool(cabe)

    # 2) Zona saturada: mejor forma en la zona aunque solape (rojo; se reubica a mano).
    seed = _seed_cuadrado(zona, area, ancla)
    if seed is not None:
        seed = _normalizar(seed)
        if not seed.is_empty:
            efectiva, _a, _c = conformar_patio(seed, zona, area, 0.0, footprint=zona)
            efectiva = _normalizar(efectiva)
            if not efectiva.is_empty:
                return efectiva, False

    # 3) Garantía última: cuadrado mínimo recortado a la zona (no vacío si la zona no lo es).
    p = zona.representative_point()
    lado = max(0.5, area ** 0.5)
    minimo = _normalizar(
        box(p.x - lado / 2, p.y - lado / 2, p.x + lado / 2, p.y + lado / 2).intersection(zona)
    )
    return (minimo if not minimo.is_empty else Polygon()), False


# ─── Reintentos por zona (orden de colocación determinista) ────────────────
def _secuencias(nucleo_area: float, unidades: list) -> list:
    """Lista determinista de K secuencias de colocación (orden variado) para reintentar
    una zona. Cada secuencia es `[(kind, key, area), ...]` con kind ∈ {"nucleo","unidad"}.
    `unidades` = `[(key, area_construida), ...]`. Sin aleatoriedad: mismo input → mismas
    secuencias (reproducibilidad).
    """
    U = list(unidades)
    U_desc = sorted(U, key=lambda u: (-u[1], u[0]))
    U_asc = sorted(U, key=lambda u: (u[1], u[0]))
    tiene_nucleo = nucleo_area > 0
    N = ("nucleo", "nucleo", nucleo_area)

    def sec(lista, pos):
        elems = [("unidad", k, a) for k, a in lista]
        if not tiene_nucleo:
            return elems
        if pos == "first":
            return [N] + elems
        if pos == "last":
            return elems + [N]
        mid = len(elems) // 2                     # núcleo en el centro de la secuencia
        return elems[:mid] + [N] + elems[mid:]

    candidatas = [
        sec(U, "first"),
        sec(U_desc, "first"),
        sec(U_asc, "first"),
        sec(U, "last"),
        sec(U_desc, "mid"),
        sec(U_desc, "last"),
    ]
    # Dedup preservando orden (con 0/1 unidades varias secuencias coinciden).
    vistas: list = []
    unicas: list = []
    for s in candidatas:
        clave = tuple((kind, key) for kind, key, _ in s)
        if clave not in vistas:
            vistas.append(clave)
            unicas.append(s)
    return unicas


def _disponer_zona(zona: Polygon, nucleo_area: float, unidades: list, ancla: Point):
    """Empaqueta núcleo + unidades en `zona` como un bloque contiguo anclado hacia
    `ancla` (fachada), con reintentos; conserva el mejor intento (el de MENOS fallos).
    `unidades` = `[(key, area_construida), ...]`.

    Devuelve `(nucleo_poly | None, {key: (poly, cabe)}, [pasillos])`. La circulación es
    la superficie sobrante `zona − Σcolocados`, partida en piezas (cada una un pasillo).
    """
    mejor = None   # (fallos, nucleo_poly, resultados, colocados)
    for secuencia in _secuencias(nucleo_area, unidades):
        colocados: list = []
        nucleo_poly: Optional[Polygon] = None
        resultados: dict = {}
        fallos = 0
        for kind, key, area in secuencia:
            poly, cabe = _colocar_compacto(zona, colocados, area, ancla)
            if poly is not None and not poly.is_empty:
                colocados.append(poly)
            if not cabe:
                fallos += 1
            if kind == "nucleo":
                nucleo_poly = poly if (poly is not None and not poly.is_empty) else None
            else:
                resultados[key] = (poly, cabe)
        if mejor is None or fallos < mejor[0]:
            mejor = (fallos, nucleo_poly, resultados, colocados)
        if fallos == 0:
            break

    _fallos, nucleo_poly, resultados, colocados = mejor
    pasillos: list = []
    if colocados:
        sobrante = zona.difference(unary_union(colocados))
        pasillos = [p for p in _componentes(sobrante) if p.area > 1e-6]
    return nucleo_poly, resultados, pasillos


def _nombre_fallback(pl) -> str:
    tipo = getattr(pl, "tipo", "regular")
    if tipo == "sotano":
        return "S1"
    if tipo == "atico":
        return "Ático"
    n = int(getattr(pl, "n", 0) or 0)
    return "PB" if n == 0 else f"P{n}"


def disponer_edificio(
    envolvente, cap, params: Parametros, lados=None, clearance: float | None = None,
) -> EdificioDispuesto:
    """Dispone núcleo + unidades + circulación por planta y zona (§2.5).

    - `envolvente` (Envolvente): geometría por planta (footprint / patios).
    - `cap` (Capacidad): reparto numérico por planta (unidades, núcleo, nº de zonas,
      unidades adaptadas). Sus listas van alineadas con `envolvente.plantas`.
    - `params` (config.Parametros): umbral de cuello de zona y % de tabiquería interior.
    - `lados` / `clearance`: reservados (afinado de fachada / holgura). El empaquetado
      es compacto (muros medianeros), así que no hay holgura entre unidades.

    Devuelve un `EdificioDispuesto` con una `PlantaDispuesta` por cada planta de la
    envolvente (mismo orden ⇒ mismos tabs que el canvas).
    """
    ancho_cuello = max(0.0, float(getattr(params.diseno, "ancho_cuello_zona_min", 4.0)))
    pct_muros_int = max(0.0, float(getattr(params.diseno, "pct_muros_interior", 0.0)))
    factor_construida = 1.0 + pct_muros_int / 100.0   # construida = útil × (1 + %tabiquería)

    n_adaptadas = int(getattr(cap, "n_unidades_adaptadas", 0) or 0)
    adaptadas_marcadas = 0

    nucleo_pp = list(getattr(cap, "nucleo_por_planta", []) or [])
    viv_pp = list(getattr(cap, "viv_por_planta", []) or [])
    unidades_pp = list(getattr(cap, "unidades_por_planta", []) or [])
    nombres_pp = list(getattr(cap, "nombres_planta", []) or [])

    plantas_out: list = []
    for i, pl in enumerate(envolvente.plantas):
        nombre = nombres_pp[i] if i < len(nombres_pp) else _nombre_fallback(pl)
        tipo = getattr(pl, "tipo", "regular")
        footprint = pl.footprint
        patios = list(getattr(pl, "patios", []) or [])

        # Región colocable = huella − patios; zonas edificables independientes (§2.4).
        patios_geom = [
            p.geometry for p in patios
            if getattr(p, "geometry", None) is not None and not p.geometry.is_empty
        ]
        region = footprint.difference(unary_union(patios_geom)) if patios_geom else footprint
        zonas = detectar_zonas_edificables(region, ancho_cuello_min=ancho_cuello)

        nucleo_area_planta = nucleo_pp[i] if i < len(nucleo_pp) else 0.0
        unidades_i = list(unidades_pp[i]) if i < len(unidades_pp) else []
        viv_i = viv_pp[i] if i < len(viv_pp) else 0

        if not zonas:
            plantas_out.append(PlantaDispuesta(
                n=pl.n, nombre=nombre, tipo=tipo, footprint=footprint, patios=patios,
                nucleo=None, unidades=[], pasillos=[],
            ))
            continue

        # Reparto de las unidades de la planta entre sus zonas, proporcional al área
        # (mismo criterio que `_zonas_de_planta`); se rebanan las tuplas reales en orden.
        reparto = repartir_por_area(viv_i, [z.area for z in zonas])
        # El núcleo (m² fijos) se dimensiona por zona (`nucleo_por_planta / nº zonas`) y,
        # por el contrato de un solo núcleo del canvas, se COLOCA en la zona mayor
        # (`zonas` viene ordenada por área desc.). Multi-zona por zona → Fase 3.
        nucleo_area_zona = nucleo_area_planta / max(1, len(zonas))

        nucleo_planta: Optional[NucleoDispuesto] = None
        unidades_out: list = []
        pasillos_out: list = []
        cursor = 0
        for zi, zona in enumerate(zonas):
            n_uni_zona = reparto[zi] if zi < len(reparto) else 0
            tuplas = unidades_i[cursor:cursor + n_uni_zona]
            cursor += n_uni_zona

            unidades_zona: list = []       # [(key, area_construida), ...]
            meta: dict = {}                # key -> (util_u, es_adaptada)
            for j, par in enumerate(tuplas):
                _n_dorms, util_u = par
                util_u = max(0.0, float(util_u))
                key = f"z{zi}u{j}"
                unidades_zona.append((key, util_u * factor_construida))
                es_adapt = adaptadas_marcadas < n_adaptadas
                if es_adapt:
                    adaptadas_marcadas += 1
                meta[key] = (util_u, es_adapt)

            nucleo_area_esta_zona = nucleo_area_zona if zi == 0 else 0.0
            ancla = _ancla_zona(zona, footprint)   # empaqueta el bloque hacia fachada
            nucleo_poly, resultados, pasillos = _disponer_zona(
                zona, nucleo_area_esta_zona, unidades_zona, ancla,
            )
            if zi == 0 and nucleo_poly is not None and not nucleo_poly.is_empty:
                nucleo_planta = NucleoDispuesto(poligono=nucleo_poly)
            pasillos_out.extend(pasillos)

            # INVARIANTE: se dibujan SIEMPRE las cap.viv_por_planta unidades (nunca se
            # borra una: `_colocar_compacto` garantiza forma no vacía; si aun así saliera
            # vacía, se sustituye por un cuadrado mínimo en la zona). Así el nº dibujado y
            # el mapeo de unidades adaptadas cuadran con la capacidad.
            for key, _area in unidades_zona:
                util_u, es_adapt = meta[key]
                poly, cabe = resultados.get(key, (Polygon(), False))
                if poly is None or poly.is_empty:
                    p = zona.representative_point()
                    poly = _normalizar(box(p.x - 0.5, p.y - 0.5, p.x + 0.5, p.y + 0.5).intersection(zona))
                    cabe = False
                unidades_out.append(UnidadDispuesta(
                    id=f"{nombre}·U{len(unidades_out) + 1}",
                    poligono_construido=poly,
                    poligono_util=poly,
                    area_util_m2=float(util_u),
                    cumple_minimos=bool(cabe),
                    es_adaptada=bool(es_adapt),
                ))

        plantas_out.append(PlantaDispuesta(
            n=pl.n, nombre=nombre, tipo=tipo, footprint=footprint, patios=patios,
            nucleo=nucleo_planta, unidades=unidades_out, pasillos=pasillos_out,
        ))

    return EdificioDispuesto(plantas=plantas_out)
