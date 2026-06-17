"""Programa arquitectónico — Anexo I.5 del PDF (vivienda, Decreto Junta de Andalucía).

Devuelve la lista de estancias objetivo dada: número de dormitorios, superficie
útil disponible, y si la cocina va integrada (open plan) o independiente.

Copia desde `Modulos/puccetti-app/puccetti/programa.py`. Los valores se exponen
también vía constantes para que la capa de persistencia pueda sembrarlos en la
BBDD de normativa.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

from .combinador_tipologias import ComboDormitorios
from .programa_uso import (
    TipologiaUnidadDescriptor,
    reparto_multi_tipologia_generico,
)

Categoria = Literal["publica", "privada", "servicio", "circulacion"]

# Tamaños de dormitorio de una vivienda (Anexo I.5): cada dormitorio es
# individual (MIN_DORM_INDIVIDUAL) o doble (MIN_DORM_DOBLE). Es el alfabeto del
# combinador para el paradigma "elegir nº de dormitorios" (§2.5), hermano del de
# apartamentos turísticos pero con dos tamaños en vez de cuatro.
TAMANOS_DORMITORIO_VIVIENDA = ("individual", "doble")
# Plazas (ocupación) por tamaño de dormitorio de vivienda.
PLAZAS_DORMITORIO_VIVIENDA: dict[str, int] = {"individual": 1, "doble": 2}

# Nombres de baño en orden de incorporación: el 1º es un baño completo, el resto
# aseos/baños secundarios (uno suele asociarse al dormitorio principal).
NOMBRES_BANOS = ("bano", "aseo", "aseo_2")


def banos_objetivo(n_dorms: int) -> tuple[int, int]:
    """(obligatorios, deseables) nº de baños por nº de dormitorios (§2.5).

    - estudio / 1 dorm → 1 baño.
    - 2 dorm → 1 obligatorio; un 2º si los m² útiles lo permiten (suele ser el
      baño del dormitorio principal).
    - 3+ dorm → 2 obligatorios; un 3º si los m² útiles lo permiten.

    El nº REAL se ajusta al útil disponible de la unidad: se añade un baño más
    solo si cabe sin bajar ninguna estancia de su mínimo; si no, se queda con la
    opción reducida. Política común a vivienda y apartamentos turísticos.
    """
    if n_dorms <= 1:
        return (1, 1)
    if n_dorms == 2:
        return (1, 2)
    return (2, 3)


# Ocupación a partir de la cual una unidad necesita 2 baños obligatoriamente,
# con independencia del nº de dormitorios o del uso.
PLAZAS_DOS_BANOS = 5


def banos_min_max(n_dorms: int, plazas: int) -> tuple[int, int]:
    """(obligatorios, deseables) baños combinando dormitorios y ocupación.

    Sobre la política por nº de dormitorios (`banos_objetivo`) se aplica el suelo
    por plazas: toda unidad de `PLAZAS_DOS_BANOS` (5) plazas o más exige 2 baños.
    """
    n_min, n_max = banos_objetivo(n_dorms)
    if plazas >= PLAZAS_DOS_BANOS:
        n_min = max(n_min, 2)
        n_max = max(n_max, n_min)
    return n_min, n_max


def nombres_banos(n_dorms: int, plazas: int, n_banos: int) -> list[str]:
    """Nombres de los `n_banos` baños de la unidad, en orden de incorporación.

    Toda unidad de `PLAZAS_DOS_BANOS` (5) plazas o más exige 2 baños COMPLETOS
    (no "baño + aseo"): se nombran `bano_1` y `bano_2` para que el detalle por
    unidad los muestre como "Baño 1" y "Baño 2" (un eventual 3er servicio es un
    aseo). Por debajo de ese suelo se mantiene el criterio general (`NOMBRES_BANOS`):
    1er baño completo (`bano`) y los secundarios como aseos (el del dormitorio
    principal).
    """
    if n_banos <= 0:
        return []
    if plazas >= PLAZAS_DOS_BANOS:
        return (["bano_1", "bano_2", "aseo", "aseo_2"])[:n_banos]
    return list(NOMBRES_BANOS[:n_banos])


@dataclass(frozen=True)
class Estancia:
    nombre: str
    categoria: Categoria
    area_min_m2: float       # del Anexo I.5
    area_target_m2: float    # nuestro objetivo (>= mínimo)

    def __repr__(self) -> str:
        return f"{self.nombre}({self.categoria},{self.area_target_m2:.1f}m2)"


# Anexo I.5 — superficies mínimas vivienda VPO Junta de Andalucía.
# Estos valores son DEFAULTS sembrados en BBDD (ver seed_normativa.py); al arranque
# de la app, `cargar_desde_repo()` los reescribe con los de BBDD para reflejar
# cualquier edición persistida por el usuario.
MIN_DORM_INDIVIDUAL = 8.0
MIN_DORM_DOBLE = 12.0
MIN_COCINA = 7.0
MIN_BANO = 3.0
MIN_ASEO = 1.5
SALON_MIN = {1: 14, 2: 16, 3: 18, 4: 20}
SALON_MAS_COCINA_MIN = {1: 20, 2: 20, 3: 24, 4: 24}

# Superficie útil máxima de referencia (VPO). La UI solo expone hasta "4d+",
# así que n_dorms se acota a 4 (con default vía .get).
UTIL_MAX = {0: 25, 1: 60, 2: 70, 3: 90, 4: 110}

# Política de reparto del programa entre estancias. Cargable desde BBDD.
# - AREA_TARGET_VIVIENDA: dict[n_dorms] → dict[estancia → m² target | None].
#   `None` = la estancia escala con el útil disponible. Valor concreto =
#   tamaño fijo (cocina, baño, aseo, y todas las del estudio).
# - PCT_CIRCULACION_INTERIOR_VIVIENDA: % del útil reservado a circulación
#   interna (pasillos + vestíbulo) en viviendas 1d+. No aplica al estudio.
# - UMBRAL_MINIMO_ESTUDIO_M2: piso absoluto del útil del estudio (Anexo I.5
#   VPO Andalucía dice "≥ 25 m² excluyendo servicios comunes").
AREA_TARGET_VIVIENDA: dict[int, dict[str, float | None]] = {}
PCT_CIRCULACION_INTERIOR_VIVIENDA: float = 15.0
UMBRAL_MINIMO_ESTUDIO_M2: float = 25.0


def cargar_desde_repo(catalogo) -> bool:
    """Vuelca los valores del catálogo de BBDD a las constantes module-level.

    Esto permite que el usuario modifique los mínimos del Anexo I.5 desde
    persistencia y que `programa_vivienda()` los respete sin tener que pasar
    el repo por toda la cadena de llamadas. Devuelve True si se aplicó algún
    override; False si la BBDD estaba vacía o el catálogo no expone el método.
    """
    obtener = getattr(catalogo, "consolidadas_vivienda", None)
    if obtener is None:
        return False
    datos = obtener() or {}
    if not datos:
        return False
    g = globals()
    for clave in ("MIN_DORM_INDIVIDUAL", "MIN_DORM_DOBLE", "MIN_COCINA", "MIN_BANO", "MIN_ASEO"):
        if clave in datos:
            g[clave] = float(datos[clave])
    for clave in ("SALON_MIN", "SALON_MAS_COCINA_MIN", "UTIL_MAX"):
        if clave in datos and isinstance(datos[clave], dict):
            g[clave].clear()
            g[clave].update({int(k): float(v) for k, v in datos[clave].items()})

    if "AREA_TARGET_VIVIENDA" in datos and isinstance(datos["AREA_TARGET_VIVIENDA"], dict):
        g["AREA_TARGET_VIVIENDA"] = {
            int(n): {str(est): (None if t is None else float(t)) for est, t in mp.items()}
            for n, mp in datos["AREA_TARGET_VIVIENDA"].items()
        }
    if "PCT_CIRCULACION_INTERIOR_VIVIENDA" in datos:
        g["PCT_CIRCULACION_INTERIOR_VIVIENDA"] = float(datos["PCT_CIRCULACION_INTERIOR_VIVIENDA"])
    if "UMBRAL_MINIMO_ESTUDIO_M2" in datos:
        g["UMBRAL_MINIMO_ESTUDIO_M2"] = float(datos["UMBRAL_MINIMO_ESTUDIO_M2"])
    return True


_CATEGORIA_ESTANCIA: dict[str, Categoria] = {
    "espacio_principal": "publica",
    "salon": "publica",
    "salon_cocina": "publica",
    "cocina": "publica",
    "dormitorio": "privada",
    "dormitorio_1": "privada",
    "dormitorio_2": "privada",
    "dormitorio_3": "privada",
    "dormitorio_4": "privada",
    "dormitorio_5": "privada",
    "bano": "servicio",
    "bano_1": "servicio",
    "bano_2": "servicio",
    "aseo": "servicio",
    "aseo_2": "servicio",
    "circulacion_interior": "circulacion",
}


def programa_vivienda(
    n_dorms: int,
    util_disponible: float,
    salon_cocina_open: bool = False,
) -> list[Estancia]:
    """§2.5 + Anexo I.5 — lista de estancias para una vivienda.

    Política sembrada en BBDD (ver `seed_normativa._filas_anexo_i_vivienda`):

    - Estudio (n_dorms=0): 3 estancias con target absoluto que suman
      `UTIL_MAX[0]` exactamente (espacio_principal=18 + bano=4 +
      circulacion_interior=3 = 25 m²).
    - 1d+: el útil de la vivienda se reparte así:
        1. `circulacion_interior` = `util_disponible × PCT_CIRCULACION_INTERIOR / 100`.
        2. Estancias con target fijo (cocina, baño, aseo) consumen su tamaño.
        3. Salón + dormitorios escalan proporcional a su `area_min_m2` hasta
           consumir el útil sobrante.

    La suma de `area_target_m2` de las estancias devueltas es siempre
    `util_disponible` exacto (sin "GAP invisible").

    `salon_cocina_open=True` agrupa salón+cocina en un único `salon_cocina`
    con target ≥ `SALON_MAS_COCINA_MIN[n_dorms]`.
    """
    if util_disponible <= 0:
        return []

    if n_dorms == 0:
        return _programa_estudio(util_disponible)

    targets_n = AREA_TARGET_VIVIENDA.get(n_dorms, {})
    # Fallback si la BBDD aún no se ha cargado: usa la política por defecto
    # (cocina=min+1, banos=min+2, aseo=min+1, salón/dormitorios escalan).
    if not targets_n:
        targets_n = _targets_default_para(n_dorms)

    # 1. Circulación interior fija (% del útil).
    pct_circ = PCT_CIRCULACION_INTERIOR_VIVIENDA / 100.0
    circ_target = util_disponible * pct_circ

    # 2. Selección de estancias según salon_cocina_open y n_dorms.
    nombres = _nombres_estancias_vivienda(n_dorms, util_disponible, salon_cocina_open)

    # 3. Separa fijas (con target en BBDD) de escalantes (target=None).
    fijas: list[tuple[str, float, float]] = []      # (nombre, min_m2, target)
    escalantes: list[tuple[str, float]] = []        # (nombre, min_m2)
    for est in nombres:
        min_est = _area_min_estancia(est, n_dorms, salon_cocina_open)
        tgt = targets_n.get(est)
        if tgt is None:
            escalantes.append((est, min_est))
        else:
            fijas.append((est, min_est, float(tgt)))

    suma_fijas = sum(t for _, _, t in fijas)
    suma_min_escalantes = sum(m for _, m in escalantes)
    util_principal = max(0.0, util_disponible - circ_target - suma_fijas)

    estancias: list[Estancia] = []

    # 4. Estancias en orden semánticamente útil para el modal:
    #    salón → cocina → dormitorios → baños → circulación.
    targets_por_nombre: dict[str, float] = {est: t for est, _, t in fijas}
    if suma_min_escalantes > 0:
        for est, min_est in escalantes:
            targets_por_nombre[est] = util_principal * min_est / suma_min_escalantes
    else:
        for est, _ in escalantes:
            targets_por_nombre[est] = 0.0

    for est in nombres:
        min_est = _area_min_estancia(est, n_dorms, salon_cocina_open)
        target = targets_por_nombre[est]
        estancias.append(Estancia(est, _CATEGORIA_ESTANCIA.get(est, "publica"), min_est, round(target, 2)))

    if circ_target > 1e-6:
        estancias.append(Estancia(
            "circulacion_interior", "circulacion", 0.0, round(circ_target, 2),
        ))

    return estancias


def _programa_estudio(util_disponible: float) -> list[Estancia]:
    """Estancias del estudio (n_dorms=0) escaladas a `util_disponible`.

    El catálogo de BBDD sembra 3 estancias con target sumando UTIL_MAX[0]=25.
    Si `util_disponible` ≠ 25, las áreas se escalan proporcionalmente.
    """
    targets = AREA_TARGET_VIVIENDA.get(0, {})
    if not targets:
        # Fallback si la BBDD aún no se ha cargado.
        targets = {"espacio_principal": 18.0, "bano": 4.0, "circulacion_interior": 3.0}

    nombres_ordenados = ["espacio_principal", "bano", "circulacion_interior"]
    suma_baseline = sum(float(targets[e]) for e in nombres_ordenados if e in targets)
    factor = (util_disponible / suma_baseline) if suma_baseline > 0 else 1.0

    mins = {
        "espacio_principal": 14.0,
        "bano": MIN_BANO,
        "circulacion_interior": 0.0,
    }
    estancias: list[Estancia] = []
    for est in nombres_ordenados:
        if est not in targets:
            continue
        target_escalado = round(float(targets[est]) * factor, 2)
        estancias.append(Estancia(
            est, _CATEGORIA_ESTANCIA.get(est, "publica"),
            mins.get(est, 0.0), target_escalado,
        ))
    return estancias


def _nombres_estancias_vivienda(
    n_dorms: int, util_disponible: float, salon_cocina_open: bool,
) -> list[str]:
    nombres: list[str] = []
    if salon_cocina_open:
        nombres.append("salon_cocina")
    else:
        nombres.append("salon")
        nombres.append("cocina")
    nombres.append("dormitorio_1")
    for i in range(2, n_dorms + 1):
        nombres.append(f"dormitorio_{i}")
    if util_disponible > 70 or n_dorms >= 3:
        nombres.append("bano_1")
        nombres.append("aseo")
    else:
        nombres.append("bano")
    return nombres


def _area_min_estancia(est: str, n_dorms: int, salon_cocina_open: bool) -> float:
    if est == "salon":
        return float(SALON_MIN.get(n_dorms, 20))
    if est == "salon_cocina":
        return float(SALON_MAS_COCINA_MIN.get(n_dorms, 24))
    if est == "cocina":
        return float(MIN_COCINA)
    if est == "dormitorio_1":
        return float(MIN_DORM_DOBLE)
    if est.startswith("dormitorio_"):
        return float(MIN_DORM_INDIVIDUAL)
    if est in ("bano", "bano_1"):
        return float(MIN_BANO)
    if est == "aseo":
        return float(MIN_ASEO)
    return 0.0


def _targets_default_para(n_dorms: int) -> dict[str, float | None]:
    """Política por defecto cuando la BBDD aún no se ha cargado.

    Replica los targets que sembraría `seed_normativa._filas_anexo_i_vivienda`.
    """
    out: dict[str, float | None] = {
        "salon": None,
        "salon_cocina": None,
        "cocina": MIN_COCINA + 1.0,
        "dormitorio_1": None,
    }
    for i in range(2, n_dorms + 1):
        out[f"dormitorio_{i}"] = None
    util_max = UTIL_MAX.get(n_dorms, UTIL_MAX[4])
    if util_max > 70 or n_dorms >= 3:
        out["bano_1"] = MIN_BANO + 2.0
        out["aseo"] = MIN_ASEO + 1.0
    else:
        out["bano"] = MIN_BANO + 2.0
    return out


def util_maximo(n_dorms: int) -> float:
    return UTIL_MAX.get(n_dorms, UTIL_MAX[4])


def util_minimo_vivienda(n_dorms: int, salon_cocina_open: bool = False) -> float:
    """Mínimo viable de una vivienda.

    - Estudio: ≥ `UMBRAL_MINIMO_ESTUDIO_M2` (25 m² excluyendo servicios
      comunes, Anexo I.5 VPO).
    - 1d+: suma de mínimos × 1.15 (factor 15 % para circulación interior).
    """
    if n_dorms == 0:
        prog = programa_vivienda(0, util_disponible=util_maximo(0))
        suma_min = sum(e.area_min_m2 for e in prog)
        return round(max(UMBRAL_MINIMO_ESTUDIO_M2, suma_min * 1.15), 2)
    prog = programa_vivienda(n_dorms, util_disponible=util_maximo(n_dorms),
                             salon_cocina_open=salon_cocina_open)
    return round(sum(e.area_min_m2 for e in prog) * 1.15, 2)


def descriptor_tipologia_vivienda(
    n_dorms: int,
    salon_cocina_open: bool = False,
) -> TipologiaUnidadDescriptor:
    """Descriptor de una tipología de vivienda para el reparto genérico."""
    return TipologiaUnidadDescriptor(
        slug=str(n_dorms),
        util_objetivo=util_maximo(n_dorms),
        util_minimo=util_minimo_vivienda(n_dorms, salon_cocina_open),
        util_maximo=util_maximo(n_dorms),
        n_dorms_label=n_dorms,
        tipo_unidad="vivienda",
        plazas=max(1, n_dorms) + 1,
    )


# ─── Programa por COMBINACIÓN de dormitorios (§2.5 · paradigma nuevo) ─────────
# Hermano del de apartamentos: la vivienda se define por su nº de dormitorios y
# cada dormitorio es individual o doble. Una `ComboDormitorios` describe la
# composición concreta (p. ej. 1 individual + 1 doble). El estudio (N=0) reusa el
# programa de estudio. El resto compone: salón (+cocina) + N dormitorios + baño(s)
# + circulación interior (15 %).
def _dorms_de_combo_vivienda(combo: ComboDormitorios) -> list[tuple[str, float]]:
    """[(tamaño, min_m2)] de los dormitorios de la combinación, orden canónico."""
    tam_min = {"individual": MIN_DORM_INDIVIDUAL, "doble": MIN_DORM_DOBLE}
    dorms: list[tuple[str, float]] = []
    for tam in sorted(combo.composicion):
        for _ in range(combo.composicion[tam]):
            dorms.append((tam, float(tam_min.get(tam, MIN_DORM_INDIVIDUAL))))
    return dorms


def _banos_min_m2_vivienda(n_banos: int, plazas: int) -> float:
    """m² mínimos de `n_banos` baños. Con ≥5 plazas los 2 primeros son baños
    completos (MIN_BANO); en el caso general solo el 1º. El resto son aseos
    (MIN_ASEO). Coherente con los nombres de `nombres_banos`."""
    if n_banos <= 0:
        return 0.0
    completos = min(n_banos, 2 if plazas >= PLAZAS_DOS_BANOS else 1)
    return float(MIN_BANO) * completos + float(MIN_ASEO) * (n_banos - completos)


def _n_banos_vivienda(
    n_dorms: int, plazas: int, fijo_no_bano_min: float, room_budget: float,
) -> int:
    """Nº de baños de la vivienda: obligatorios + 1 más si cabe en los m² útiles.

    `fijo_no_bano_min` = mínimos de salón + cocina + dormitorios. `room_budget` =
    útil disponible menos la circulación interior. Se añade el baño opcional solo
    si el conjunto de mínimos (con ese baño) sigue cabiendo en el presupuesto.
    """
    n_min, n_max = banos_min_max(n_dorms, plazas)
    n = n_min
    while n < n_max and fijo_no_bano_min + _banos_min_m2_vivienda(n + 1, plazas) <= room_budget + 1e-6:
        n += 1
    return n


def programa_vivienda_combo(
    combo: ComboDormitorios,
    util_disponible: float,
    salon_cocina_open: bool = False,
) -> list[Estancia]:
    """Estancias de una vivienda de N dormitorios (combinación de tamaños).

    Misma política de reparto que `programa_vivienda` (circulación 15 %, cocina y
    baños a target fijo, salón + dormitorios escalan), pero con un dormitorio por
    elemento de la combinación, dimensionado por su tamaño (individual / doble).
    """
    if util_disponible <= 0:
        return []
    if combo.es_estudio:
        return _programa_estudio(util_disponible)

    n_dorms = combo.n_dorms
    dorms = _dorms_de_combo_vivienda(combo)
    dorm_min_total = sum(m for _, m in dorms)

    circ_target = util_disponible * (PCT_CIRCULACION_INTERIOR_VIVIENDA / 100.0)
    room_budget = max(0.0, util_disponible - circ_target)

    salon_min = float(
        SALON_MAS_COCINA_MIN.get(n_dorms, 24) if salon_cocina_open
        else SALON_MIN.get(n_dorms, 20)
    )
    # Cocina independiente cuenta para el presupuesto; integrada va dentro del salón.
    cocina_min_fit = 0.0 if salon_cocina_open else float(MIN_COCINA)
    # Nº de baños: obligatorios por nº de dormitorios / plazas + 1 más si cabe (§2.5).
    plazas = combo.plazas(PLAZAS_DORMITORIO_VIVIENDA)
    n_banos = _n_banos_vivienda(
        n_dorms, plazas, salon_min + cocina_min_fit + dorm_min_total, room_budget,
    )
    banos_unidad = nombres_banos(n_dorms, plazas, n_banos)

    # Escalantes (salón + dormitorios) vs fijas (cocina + baños).
    escalantes: list[tuple[str, float]] = []
    fijas: list[tuple[str, float, float]] = []   # (nombre, min, target)
    if salon_cocina_open:
        escalantes.append(("salon_cocina", salon_min))
    else:
        escalantes.append(("salon", salon_min))
        fijas.append(("cocina", float(MIN_COCINA), float(MIN_COCINA + 1.0)))
    for i, (_tam, dmin) in enumerate(dorms, start=1):
        escalantes.append((f"dormitorio_{i}", dmin))
    # Baños completos (MIN_BANO + 2) vs aseos secundarios (MIN_ASEO + 1), según el
    # nombre: con ≥5 plazas hay 2 baños completos (`bano_1`/`bano_2`), ver nombres_banos.
    for nombre in banos_unidad:
        if nombre.startswith("aseo"):
            fijas.append((nombre, float(MIN_ASEO), float(MIN_ASEO + 1.0)))
        else:
            fijas.append((nombre, float(MIN_BANO), float(MIN_BANO + 2.0)))

    suma_fijas = sum(t for _, _, t in fijas)
    suma_min_esc = sum(m for _, m in escalantes)
    util_principal = max(0.0, util_disponible - circ_target - suma_fijas)

    targets: dict[str, float] = {n: t for n, _, t in fijas}
    if suma_min_esc > 0:
        for n, m in escalantes:
            targets[n] = util_principal * m / suma_min_esc
    else:
        for n, _ in escalantes:
            targets[n] = 0.0

    mins: dict[str, float] = {n: m for n, m, _ in fijas}
    mins.update({n: m for n, m in escalantes})

    # Orden de salida: salón → cocina → dormitorios → baños → circulación.
    orden: list[str] = ["salon_cocina"] if salon_cocina_open else ["salon", "cocina"]
    orden += [f"dormitorio_{i}" for i in range(1, n_dorms + 1)]
    orden += banos_unidad

    estancias = [
        Estancia(n, _CATEGORIA_ESTANCIA.get(n, "publica"), mins.get(n, 0.0), round(targets.get(n, 0.0), 2))
        for n in orden
    ]
    if circ_target > 1e-6:
        estancias.append(Estancia("circulacion_interior", "circulacion", 0.0, round(circ_target, 2)))
    return estancias


def util_minimo_vivienda_combo(combo: ComboDormitorios, salon_cocina_open: bool = False) -> float:
    """Suma de mínimos de las estancias (sin la circulación del 15 %).

    Usa los baños OBLIGATORIOS por nº de dormitorios (`banos_objetivo`); el baño
    opcional no entra en el mínimo viable (solo aparece si los m² lo permiten).
    """
    if combo.es_estudio:
        return util_minimo_vivienda(0, salon_cocina_open)
    n_dorms = combo.n_dorms
    dorm_min_total = sum(m for _, m in _dorms_de_combo_vivienda(combo))
    salon_min = float(
        SALON_MAS_COCINA_MIN.get(n_dorms, 24) if salon_cocina_open
        else SALON_MIN.get(n_dorms, 20)
    )
    cocina_min = 0.0 if salon_cocina_open else float(MIN_COCINA)
    plazas = combo.plazas(PLAZAS_DORMITORIO_VIVIENDA)
    n_banos_min, _ = banos_min_max(n_dorms, plazas)
    total = salon_min + cocina_min + dorm_min_total + _banos_min_m2_vivienda(n_banos_min, plazas)
    return round(total, 2)


def util_objetivo_vivienda_combo(combo: ComboDormitorios, salon_cocina_open: bool = False) -> float:
    """Objetivo de m² útil de la combinación: mínimos + 15 % (circulación)."""
    if combo.es_estudio:
        return util_minimo_vivienda(0, salon_cocina_open)
    return round(util_minimo_vivienda_combo(combo, salon_cocina_open) * 1.15, 2)


def descriptor_tipologia_vivienda_combo(
    combo: ComboDormitorios, salon_cocina_open: bool = False,
) -> TipologiaUnidadDescriptor:
    """Descriptor para el reparto a partir de una combinación de vivienda."""
    util_obj = util_objetivo_vivienda_combo(combo, salon_cocina_open)
    util_min = util_obj if combo.es_estudio else util_minimo_vivienda_combo(combo, salon_cocina_open)
    return TipologiaUnidadDescriptor(
        slug=combo.slug,
        util_objetivo=util_obj,
        util_minimo=util_min,
        util_maximo=round(util_obj * 1.25, 2),
        n_dorms_label=combo.n_dorms,
        tipo_unidad="vivienda",
        plazas=combo.plazas(PLAZAS_DORMITORIO_VIVIENDA) or 1,
    )


def reparto_multi_tipologia(
    util_disponible: float,
    tipologias: list[int],
    salon_cocina_open: bool = False,
) -> list[tuple[int, float]]:
    """Reparte el útil disponible entre varias tipologías de vivienda.

    Mantiene la firma int-based histórica (la usa la rama de preview de
    `capacidad.py`); internamente construye descriptores y delega en
    `reparto_multi_tipologia_generico`. Devuelve `[(n_dorms, util_asignado), ...]`.
    """
    if not tipologias or util_disponible <= 0:
        return []
    descriptores = [
        descriptor_tipologia_vivienda(n, salon_cocina_open) for n in tipologias
    ]
    seleccion = reparto_multi_tipologia_generico(util_disponible, descriptores)
    return [(d.n_dorms_label, util) for d, util in seleccion]


def programa_uso_vivienda(n_dorms: int, salon_cocina_open: bool = False):
    """Constructor del descriptor `ProgramaUso` para vivienda.

    Import perezoso para evitar ciclos: `programa_uso.py` no importa nada de
    este módulo, y este módulo importa `ProgramaUso` solo cuando hace falta.
    """
    from .programa_uso import ProgramaUso
    return ProgramaUso(
        util_objetivo_unidad_m2=util_maximo(n_dorms),
        area_min_unidad_m2=util_minimo_vivienda(n_dorms, salon_cocina_open),
        util_max_unidad_m2=util_maximo(n_dorms) * 1.25,
        n_dormitorios=n_dorms,
        tipo_unidad="vivienda",
        area_servicios_obligatorios_m2=0.0,
    )
