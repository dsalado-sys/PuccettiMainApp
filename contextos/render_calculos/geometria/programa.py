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

from .programa_uso import (
    TipologiaUnidadDescriptor,
    reparto_multi_tipologia_generico,
)

Categoria = Literal["publica", "privada", "servicio", "circulacion"]


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
    "aseo": "servicio",
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
