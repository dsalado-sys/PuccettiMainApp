"""Reparto geométrico de unidades por rejilla + OR-Tools CP-SAT (§2.5 — «Pintar render»).

Motor CANDIDATO alternativo al empaquetador compacto de `disposicion.py`. En vez de
colocar cada unidad como un cuadrado que se adapta a fachada, **rasteriza la zona
edificable en una rejilla** y resuelve la asignación *celda→unidad* con CP-SAT: cada
celda va a exactamente una unidad o a la circulación; cada unidad respeta su área
(± tolerancia), toca fachada/patio (ventilación), es adyacente a circulación/núcleo y
es geométricamente **conexa** (conectividad en-modelo por flujo de un commodity).

Validado por el spike del 2026-07-03 (memoria `project_spike_cpsat_rejilla`): la
geometría (área, no-solape, contacto) es trivial para CP-SAT; el cuello de botella es
la conectividad por flujo, cuyo coste explota por encima de ~150-200 celdas. Punto de
operación viable: rejilla ~1,6 m (N≈80). Por eso el default de `tam_celda` es 1,6 m y
existe un guarda anti-explosión (`max_celdas`) que engrosa la celda determinísticamente.

Contrato de dominio puro: solo geometría vectorial (shapely) + CP-SAT, sin FastAPI /
SQLAlchemy, como el resto de `geometria/`. **NO** crea ni elimina unidades: la salida
tiene EXACTAMENTE tantas `UnidadUbicada` como unidades de entrada; una que no cabe /
timeout / infeasible sale con `ubicada=False, poligono=None` (nunca revienta).

Determinismo (regla del proyecto «sin aleatoriedad»): `num_workers=1`, `random_seed`
fijo, `max_deterministic_time` como límite primario (independiente de la máquina; el
timeout de reloj es solo backstop), orden de construcción fijo (celdas row-major,
unidades en orden de entrada, vecinos ordenados) y versión de ortools fijada.

Limitaciones conocidas de esta v1 (documentadas):
- Rasterizado «centro dentro»: las celdas de borde cuentan área completa, así que la
  unión de una unidad puede asomar levemente de la zona en bordes no alineados a la
  rejilla y `area_real` es una sobre-aproximación (±media celda; ≤2,4 % a 1,6 m). NO se
  recorta a la zona (recortar reintroduce error de área y slivers). El downstream puede
  recortar si necesita contención estricta.
- `exigir_acceso` garantiza adyacencia LOCAL a una celda de circulación/núcleo, no un
  sistema de circulación conexo hasta el núcleo/portal (eso duplicaría el flujo).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from ortools.sat.python import cp_model
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union
from shapely.prepared import prep

from .envolvente import _normalizar

_VECINOS = ((-1, 0), (1, 0), (0, -1), (0, 1))   # 4-vecindad, orden fijo (determinismo)


# ─── Contrato de entrada / salida ───────────────────────────────────────────
@dataclass
class UnidadObjetivo:
    """Unidad a colocar: identidad, área objetivo (m²) y tipología (informativa)."""
    id: str
    area_objetivo: float
    tipo: str = ""


@dataclass
class UnidadUbicada:
    """Resultado por unidad. `poligono=None` y `ubicada=False` si no se ubicó."""
    id: str
    tipo: str
    area_objetivo: float
    poligono: Optional[Polygon]
    area_real: float
    ubicada: bool


@dataclass
class ResultadoReparto:
    """Salida del solver. `len(unidades) == len(entrada)` SIEMPRE (cardinalidad exacta)."""
    unidades: list                # list[UnidadUbicada], mismo orden/ids que la entrada
    circulacion: object           # Polygon | MultiPolygon (circulación SIN restringir → puede ser multi)
    estado: str                   # "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "UNKNOWN" | "EMPTY" | "ERROR"
    tam_celda: float              # tamaño de celda EFECTIVO (puede haberse engrosado por el guarda de N)
    n_celdas: int


# ─── Rejilla (rasterizado determinista) ─────────────────────────────────────
@dataclass
class _Rejilla:
    tam_celda: float
    cols: int
    rows: int
    n: int
    cell_box: list                # list[Polygon], índice = c
    ij: list                      # list[(i, j)], índice = c (row-major)
    vecinos: list                 # list[list[int]], vecinos 4-conexos de cada celda (ordenados)
    nucleo_ij: set = field(default_factory=set)   # posiciones (i, j) reservadas por el núcleo


def _rasterizar(zona, tam_celda: float, nucleo) -> _Rejilla:
    """Rejilla de celdas cuadradas cuyo CENTRO cae en `zona`, anclada a la esquina
    mínima de la zona (`floor(min/tam)·tam`) para estabilidad ante traslaciones.

    Las celdas cuyo centro cae en `nucleo` se RESERVAN (no asignables), pero su
    posición se guarda en `nucleo_ij` para la restricción de acceso.
    """
    minx, miny, maxx, maxy = zona.bounds
    x0 = math.floor(minx / tam_celda) * tam_celda
    y0 = math.floor(miny / tam_celda) * tam_celda
    cols = max(0, int(math.ceil((maxx - x0) / tam_celda - 1e-9)))
    rows = max(0, int(math.ceil((maxy - y0) / tam_celda - 1e-9)))

    pz = prep(zona)
    pn = prep(nucleo) if (nucleo is not None and not nucleo.is_empty) else None

    idx_de_ij: dict = {}
    ij: list = []
    nucleo_ij: set = set()
    for i in range(rows):                       # i = fila (y)
        cy = y0 + (i + 0.5) * tam_celda
        for j in range(cols):                   # j = columna (x)
            cx = x0 + (j + 0.5) * tam_celda
            pt = Point(cx, cy)
            if pn is not None and pn.contains(pt):
                nucleo_ij.add((i, j))
                continue
            if pz.contains(pt):
                idx_de_ij[(i, j)] = len(ij)
                ij.append((i, j))

    n = len(ij)
    cell_box: list = []
    for (i, j) in ij:
        bx = x0 + j * tam_celda
        by = y0 + i * tam_celda
        cell_box.append(box(bx, by, bx + tam_celda, by + tam_celda))

    vecinos: list = [[] for _ in range(n)]
    for c, (i, j) in enumerate(ij):
        for (di, dj) in _VECINOS:
            nb = idx_de_ij.get((i + di, j + dj))
            if nb is not None:
                vecinos[c].append(nb)
        vecinos[c].sort()
    return _Rejilla(tam_celda, cols, rows, n, cell_box, ij, vecinos, nucleo_ij)


def _a_linea(g):
    """Frontera lineal de una geometría (el borde de un polígono; la propia línea si ya lo es)."""
    if g is None or g.is_empty:
        return None
    if g.geom_type in ("Polygon", "MultiPolygon"):
        return g.boundary
    return g


def _celdas_contacto(rej: _Rejilla, zona, fachada, patios) -> set:
    """Celdas que TOCAN la fachada (o `zona.boundary` si `fachada` es None; incluye los
    anillos de los huecos/patios) o la frontera de algún polígono de `patios`.

    Una celda toca el contacto si su `box` está a distancia ~0 de la geometría de
    contacto: en una rejilla, solo las celdas del perímetro exterior o pegadas a un
    patio (las interiores quedan a ≥ `tam_celda`).
    """
    partes = [_a_linea(fachada if fachada is not None else zona.boundary)]
    for p in patios or ():
        partes.append(_a_linea(p))
    partes = [g for g in partes if g is not None and not g.is_empty]
    if not partes:
        return set()
    contacto = unary_union(partes)
    if contacto.is_empty:
        return set()
    tol = max(rej.tam_celda * 1e-6, 1e-9)
    return {c for c in range(rej.n) if rej.cell_box[c].distance(contacto) <= tol}


def _celdas_adyacentes_nucleo(rej: _Rejilla) -> set:
    """Celdas asignables 4-adyacentes a una celda reservada por el núcleo."""
    if not rej.nucleo_ij:
        return set()
    out: set = set()
    for c, (i, j) in enumerate(rej.ij):
        for (di, dj) in _VECINOS:
            if (i + di, j + dj) in rej.nucleo_ij:
                out.add(c)
                break
    return out


# ─── Banda de área entera (nunca vacía, ≥1 celda, objetivo alcanzable) ──────
def _banda_area(area_objetivo: float, cell_area: float, tol: float):
    """`(A_lo, A_hi, A_tgt)` en nº de celdas, o None si el objetivo es inválido.

    Garantiza `1 ≤ A_lo ≤ A_tgt ≤ A_hi`. NO se recorta a N: si `A_lo` excede las celdas
    disponibles, la unidad quedará sin colocar (colocada=0), no se fuerza a caber.
    """
    if area_objetivo is None or not math.isfinite(area_objetivo) or area_objetivo <= 0:
        return None
    A_tgt = max(1, round(area_objetivo / cell_area))
    A_lo = max(1, min(A_tgt, math.floor(area_objetivo * (1.0 - tol) / cell_area)))
    A_hi = max(A_lo, A_tgt, math.ceil(area_objetivo * (1.0 + tol) / cell_area))
    return A_lo, A_hi, A_tgt


# ─── Función principal ──────────────────────────────────────────────────────
def repartir_zona_cpsat(
    zona: Polygon,
    unidades: list,
    *,
    fachada=None,
    patios: tuple = (),
    nucleo: Optional[Polygon] = None,
    tam_celda: float = 1.6,
    tol_area: float = 0.10,
    max_celdas: int = 150,
    det_time: float = 40.0,
    timeout_s: float = 10.0,
    exigir_acceso: bool = True,
    seed: int = 0,
    num_workers: int = 1,
) -> ResultadoReparto:
    """Reparte `unidades` (id, área objetivo, tipo) dentro de `zona` por rejilla + CP-SAT.

    - `zona`: zona edificable (huella − patios; ya excluye patios). Puede ser Polygon
      con huecos o MultiPolygon.
    - `fachada`: geometría de contacto obligatorio (ventilación). None → `zona.boundary`.
    - `patios`: polígonos de patio cuyo borde también vale como contacto.
    - `nucleo`: núcleo ya colocado; sus celdas se reservan y las unidades exigen acceso.
    - `tam_celda`, `tol_area`: resolución de rejilla y tolerancia de área (±).
    - `max_celdas`: si N excede, se engrosa `tam_celda` hasta N ≤ max (guarda anti-explosión).
    - `det_time` / `timeout_s`: límite determinista (primario) y backstop de reloj.
    - `exigir_acceso`, `seed`, `num_workers`: acceso a circulación/núcleo y determinismo.

    Devuelve un `ResultadoReparto` con EXACTAMENTE `len(unidades)` entradas (cardinalidad
    exacta; nunca crea ni borra unidades) y la circulación sobrante.
    """
    def _todo_no_ubicada(estado: str, circulacion, tam: float, n: int) -> ResultadoReparto:
        return ResultadoReparto(
            unidades=[UnidadUbicada(u.id, u.tipo, u.area_objetivo, None, 0.0, False) for u in unidades],
            circulacion=circulacion, estado=estado, tam_celda=tam, n_celdas=n,
        )

    if zona is None or zona.is_empty:
        return _todo_no_ubicada("EMPTY", Polygon(), tam_celda, 0)

    # Guarda anti-explosión: engrosa la celda determinísticamente hasta N ≤ max_celdas.
    rej = _rasterizar(zona, tam_celda, nucleo)
    intentos = 0
    while rej.n > max_celdas and intentos < 40:
        tam_celda *= 1.25
        rej = _rasterizar(zona, tam_celda, nucleo)
        intentos += 1

    if rej.n == 0:
        return _todo_no_ubicada("EMPTY", zona, rej.tam_celda, 0)
    if not unidades:
        return ResultadoReparto([], unary_union(rej.cell_box), "EMPTY", rej.tam_celda, rej.n)

    try:
        contacto_idx = _celdas_contacto(rej, zona, fachada, patios)
        nucleo_adj = _celdas_adyacentes_nucleo(rej)
        model, mv = _construir_modelo(rej, unidades, contacto_idx, nucleo_adj, tol_area, exigir_acceso)

        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = int(max(1, num_workers))
        solver.parameters.random_seed = int(seed)
        solver.parameters.max_deterministic_time = float(det_time)
        solver.parameters.max_time_in_seconds = float(timeout_s)
        status = solver.Solve(model)
        return _extraer_solucion(solver, status, rej, unidades, mv, zona)
    except Exception:
        return _todo_no_ubicada("ERROR", zona, rej.tam_celda, rej.n)


# ─── Construcción del modelo CP-SAT ─────────────────────────────────────────
def _construir_modelo(rej: _Rejilla, unidades, contacto_idx: set, nucleo_adj: set,
                      tol_area: float, exigir_acceso: bool):
    """Arma el `CpModel` (partición, área, contacto, acceso, conectividad por flujo,
    compacidad bbox, ruptura de simetría) y su objetivo entero lexicográfico.

    Devuelve `(model, mv)` donde `mv` reúne las variables necesarias para extraer.
    """
    model = cp_model.CpModel()
    n = rej.n
    U = len(unidades)
    cell_area = rej.tam_celda ** 2

    # Aristas dirigidas 4-conexas (mismas para todas las unidades), orden fijo.
    edges = [(a, b) for a in range(n) for b in rej.vecinos[a]]

    bandas = [_banda_area(u.area_objetivo, cell_area, tol_area) for u in unidades]

    # Variables de asignación.
    circ = [model.NewBoolVar(f"circ_{c}") for c in range(n)]
    x = [[model.NewBoolVar(f"x_{c}_{u}") for u in range(U)] for c in range(n)]
    colocada = [model.NewBoolVar(f"col_{u}") for u in range(U)]

    # Partición: cada celda a exactamente una unidad o a circulación.
    for c in range(n):
        model.Add(sum(x[c][u] for u in range(U)) + circ[c] == 1)

    root = [None] * U   # root[u][c] (solo unidades válidas)
    for u in range(U):
        banda = bandas[u]
        if banda is None:                       # unidad inválida (área ≤ 0): nunca se coloca
            model.Add(colocada[u] == 0)
            model.Add(sum(x[c][u] for c in range(n)) == 0)
            continue
        A_lo, A_hi, _A_tgt = banda
        M = min(A_hi, n)                         # cota big-M ajustada (celdas máx. de la unidad)

        # Área dentro de banda (0 celdas si no se coloca).
        total_u = sum(x[c][u] for c in range(n))
        model.Add(total_u >= A_lo * colocada[u])
        model.Add(total_u <= A_hi * colocada[u])

        # Contacto fachada/patio (ventilación).
        if contacto_idx:
            model.Add(sum(x[c][u] for c in contacto_idx) >= colocada[u])
        else:
            model.Add(colocada[u] == 0)          # sin celdas de contacto → no colocable

        # Acceso: ≥1 celda de la unidad adyacente a circulación o núcleo.
        if exigir_acceso:
            touch = []
            for c in range(n):
                t = model.NewBoolVar(f"touch_{c}_{u}")
                model.Add(t <= x[c][u])
                vecinos_circ = sum(circ[b] for b in rej.vecinos[c])
                const_nucleo = 1 if c in nucleo_adj else 0
                model.Add(t <= vecinos_circ + const_nucleo)
                touch.append(t)
            model.Add(sum(touch) >= colocada[u])

        # Conectividad por flujo (fuente virtual, single-commodity).
        r = [model.NewBoolVar(f"r_{c}_{u}") for c in range(n)]
        root[u] = r
        model.Add(sum(r) == colocada[u])
        for c in range(n):
            model.Add(r[c] <= x[c][u])
        g = [model.NewIntVar(0, M, f"g_{c}_{u}") for c in range(n)]
        for c in range(n):
            model.Add(g[c] <= M * r[c])
        cap = max(0, M - 1)
        f = {(a, b): model.NewIntVar(0, cap, f"f_{a}_{b}_{u}") for (a, b) in edges}
        for (a, b) in edges:
            model.Add(f[(a, b)] <= cap * x[a][u])
            model.Add(f[(a, b)] <= cap * x[b][u])
        for c in range(n):
            inflow = sum(f[(a, c)] for a in rej.vecinos[c])
            outflow = sum(f[(c, b)] for b in rej.vecinos[c])
            model.Add(g[c] + inflow - outflow == x[c][u])

    # Compacidad: medio-perímetro del bbox de cada unidad (proxy barato, entero).
    spanX = [model.NewIntVar(0, rej.cols, f"spanX_{u}") for u in range(U)]
    spanY = [model.NewIntVar(0, rej.rows, f"spanY_{u}") for u in range(U)]
    for u in range(U):
        if bandas[u] is None:
            model.Add(spanX[u] == 0)
            model.Add(spanY[u] == 0)
            continue
        xmin = model.NewIntVar(0, rej.cols, f"xmin_{u}")
        xmax = model.NewIntVar(0, rej.cols, f"xmax_{u}")
        ymin = model.NewIntVar(0, rej.rows, f"ymin_{u}")
        ymax = model.NewIntVar(0, rej.rows, f"ymax_{u}")
        for c, (i, j) in enumerate(rej.ij):
            model.Add(xmin <= j + rej.cols * (1 - x[c][u]))
            model.Add(xmax >= j - rej.cols * (1 - x[c][u]))
            model.Add(ymin <= i + rej.rows * (1 - x[c][u]))
            model.Add(ymax >= i - rej.rows * (1 - x[c][u]))
        model.Add(spanX[u] >= xmax - xmin)
        model.Add(spanY[u] >= ymax - ymin)

    # Ruptura de simetría entre unidades intercambiables (mismo tipo y misma banda):
    # colocar preferentemente la de menor índice (poda + canonicaliza el conjunto colocado).
    grupos: dict = {}
    for u in range(U):
        if bandas[u] is None:
            continue
        clave = (unidades[u].tipo, bandas[u][0], bandas[u][1])
        grupos.setdefault(clave, []).append(u)
    for indices in grupos.values():
        for a, b in zip(indices, indices[1:]):
            model.Add(colocada[a] >= colocada[b])

    # Objetivo entero lexicográfico: primero MÁXIMO nº colocadas, luego compacidad.
    max_comp = U * (rej.cols + rej.rows)
    W_place = max_comp + 1
    model.Maximize(W_place * sum(colocada) - sum(spanX[u] + spanY[u] for u in range(U)))

    mv = {"x": x, "circ": circ, "colocada": colocada, "cell_area": cell_area}
    return model, mv


# ─── Extracción de la solución ──────────────────────────────────────────────
def _extraer_solucion(solver, status, rej: _Rejilla, unidades, mv, zona) -> ResultadoReparto:
    """Mapea `status` → `ResultadoReparto`. Se ramifica ANTES de leer valores. Cada
    unidad de entrada produce EXACTAMENTE una `UnidadUbicada` (cardinalidad exacta).
    """
    estado = solver.StatusName(status)
    x, circ, colocada, cell_area = mv["x"], mv["circ"], mv["colocada"], mv["cell_area"]

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return ResultadoReparto(
            unidades=[UnidadUbicada(u.id, u.tipo, u.area_objetivo, None, 0.0, False) for u in unidades],
            circulacion=zona, estado=estado, tam_celda=rej.tam_celda, n_celdas=rej.n,
        )

    salida: list = []
    for u_idx, u in enumerate(unidades):
        celdas = [c for c in range(rej.n) if solver.Value(x[c][u_idx]) == 1]
        if solver.Value(colocada[u_idx]) == 1 and celdas:
            poly = _normalizar(unary_union([rej.cell_box[c] for c in celdas]))
            if not poly.is_empty:
                salida.append(UnidadUbicada(
                    u.id, u.tipo, u.area_objetivo, poly, len(celdas) * cell_area, True,
                ))
                continue
        salida.append(UnidadUbicada(u.id, u.tipo, u.area_objetivo, None, 0.0, False))

    circ_cells = [rej.cell_box[c] for c in range(rej.n) if solver.Value(circ[c]) == 1]
    circulacion = unary_union(circ_cells) if circ_cells else Polygon()
    return ResultadoReparto(
        unidades=salida, circulacion=circulacion, estado=estado,
        tam_celda=rej.tam_celda, n_celdas=rej.n,
    )
