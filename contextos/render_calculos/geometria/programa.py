"""Programa arquitectónico — Anexo I.5 del PDF (vivienda, Decreto Junta de Andalucía).

Devuelve la lista de estancias objetivo dada: número de dormitorios, superficie
útil disponible, y si la cocina va integrada (open plan) o independiente.

Copia desde `Modulos/puccetti-app/puccetti/programa.py`. Los valores se exponen
también vía constantes para que la capa de persistencia pueda sembrarlos en la
BBDD de normativa.
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
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

def banos_vivienda(n_dorms: int) -> int:
    """Nº de baños de una vivienda (Anexo I.5), por nº de dormitorios:

    - estudio / 1 dorm / 2 dorm → 1 baño.
    - 3 dorm o más → 2 baños (uno suele asociarse al dormitorio principal).

    A diferencia de los apartamentos turísticos, en vivienda el criterio es por
    nº de dormitorios, no por ocupación.
    """
    return 2 if n_dorms >= 3 else 1


def nombres_banos(n_banos: int) -> list[str]:
    """Nombres de los `n_banos` baños de una unidad, en orden de incorporación.

    Todos son baños COMPLETOS (ducha, inodoro y lavabo): con 1 baño es `bano`;
    con 2 o más se numeran `bano_1`, `bano_2`, … para que el detalle por unidad
    los muestre como "Baño 1", "Baño 2".
    """
    if n_banos <= 0:
        return []
    if n_banos == 1:
        return ["bano"]
    return [f"bano_{i}" for i in range(1, n_banos + 1)]


@dataclass(frozen=True)
class Estancia:
    nombre: str
    categoria: Categoria
    area_min_m2: float       # del Anexo I.5
    area_target_m2: float    # nuestro objetivo (>= mínimo)

    def __repr__(self) -> str:
        return f"{self.nombre}({self.categoria},{self.area_target_m2:.1f}m2)"


# Anexo I.5 — superficies mínimas vivienda VPO Junta de Andalucía.
# Estos valores son DEFAULTS INMUTABLES sembrados en BBDD (ver seed_normativa.py) y
# empaquetados en `CONFIG_DEFAULT`. En cada cálculo, `config_desde_repo()` construye
# una config con los valores editados de BBDD (§3.8); estas constantes no se mutan.
# Mínimos GLOBALES de habitación (Anexo I.5 VPO): no varían por nº de
# dormitorios. El editor los presenta una sola vez ("comunes a todas las
# tipologías") y al editarlos se propagan a todas las tipologías (resuelve el
# colapso last-row-wins de `consolidadas_vivienda`).
MIN_DORM_INDIVIDUAL = 8.0   # dormitorio mínimo
MIN_DORM_DOBLE = 12.0       # dormitorio principal
MIN_COCINA = 7.0            # cocina independiente
MIN_BANO = 3.0
MIN_ASEO = 1.5
MIN_ESPACIO_PRINCIPAL = 14.0  # estancia única del estudio (salón-dormitorio), editable BBDD
# Mínimos POR TIPOLOGÍA del programa estar/comedor (sí varían con nº dorms).
# Estancia (E) y Estancia+comedor+cocina (E+C+K). La clave 5 representa el
# tramo "más de 4 dormitorios" del Anexo I.5 (E=24, E+C+K=28).
SALON_MIN = {1: 14, 2: 16, 3: 18, 4: 20, 5: 24}
SALON_MAS_COCINA_MIN = {1: 20, 2: 20, 3: 24, 4: 24, 5: 28}

# Superficie útil máxima de referencia (VPO). La UI expone hasta "4d" y un
# tramo ">4d" (clave 5). El estudio (0) no tiene máximo VPO; usamos un techo
# holgado por encima de su objetivo (estancia + cocina + baño + circulación,
# Anexo I.5) para que pueda crecer con el sobrante.
UTIL_MAX = {0: 40, 1: 60, 2: 70, 3: 90, 4: 110, 5: 130}

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


# ─── Configuración inmutable del programa (§3.8 — sin globals mutables) ──────
# Los mínimos/política editables del Anexo I.5 viven en una instancia FROZEN que se
# construye por cálculo (desde BBDD) y se pasa como argumento a las funciones de
# este módulo. Antes se volcaban a globals de módulo (`cargar_desde_repo` /
# `set_pct_circulacion_interior`), lo que cruzaba ediciones entre requests
# concurrentes y entre tests (Pendiente 3.8). Las constantes de arriba quedan como
# DEFAULTS inmutables; `CONFIG_DEFAULT` las empaqueta y es el valor por defecto de
# `cfg`, de modo que los llamadores que no editan (seed, tests, preview) ven el
# Anexo I.5 tal cual, sin estado compartido.
@dataclass(frozen=True)
class ProgramaViviendaConfig:
    min_dorm_individual: float = MIN_DORM_INDIVIDUAL
    min_dorm_doble: float = MIN_DORM_DOBLE
    min_cocina: float = MIN_COCINA
    min_bano: float = MIN_BANO
    min_aseo: float = MIN_ASEO
    min_espacio_principal: float = MIN_ESPACIO_PRINCIPAL
    salon_min: dict[int, float] = field(default_factory=lambda: dict(SALON_MIN))
    salon_mas_cocina_min: dict[int, float] = field(default_factory=lambda: dict(SALON_MAS_COCINA_MIN))
    util_max: dict[int, float] = field(default_factory=lambda: dict(UTIL_MAX))
    # Vacío = la política de targets cae al fallback `_targets_default_para` (igual
    # que cuando la BBDD aún no estaba sembrada en el diseño anterior).
    area_target: dict[int, dict[str, float | None]] = field(default_factory=dict)
    pct_circulacion_interior: float = PCT_CIRCULACION_INTERIOR_VIVIENDA
    umbral_minimo_estudio_m2: float = UMBRAL_MINIMO_ESTUDIO_M2


# Config por defecto (Anexo I.5 sin ediciones). Inmutable y compartible entre hilos.
CONFIG_DEFAULT = ProgramaViviendaConfig()


def config_desde_repo(catalogo=None, pct_circulacion_interior: float | None = None) -> ProgramaViviendaConfig:
    """Construye un `ProgramaViviendaConfig` desde el catálogo de BBDD (Anexo I.5).

    Sustituye al antiguo `cargar_desde_repo`, que mutaba globals de módulo. Cualquier
    clave ausente conserva el default del Anexo. `pct_circulacion_interior`, si se
    indica (valor del panel de diseño), prevalece sobre el persistido. Devuelve
    `CONFIG_DEFAULT` si no hay catálogo o la BBDD está vacía.
    """
    valores: dict = {}
    obtener = getattr(catalogo, "consolidadas_vivienda", None) if catalogo is not None else None
    try:
        datos = (obtener() or {}) if obtener is not None else {}
    except Exception:
        datos = {}
    mapa_escalar = {
        "MIN_DORM_INDIVIDUAL": "min_dorm_individual",
        "MIN_DORM_DOBLE": "min_dorm_doble",
        "MIN_COCINA": "min_cocina",
        "MIN_BANO": "min_bano",
        "MIN_ASEO": "min_aseo",
        "MIN_ESPACIO_PRINCIPAL": "min_espacio_principal",
    }
    for clave, campo in mapa_escalar.items():
        if clave in datos:
            valores[campo] = float(datos[clave])
    mapa_dict = {
        "SALON_MIN": "salon_min",
        "SALON_MAS_COCINA_MIN": "salon_mas_cocina_min",
        "UTIL_MAX": "util_max",
    }
    for clave, campo in mapa_dict.items():
        if clave in datos and isinstance(datos[clave], dict):
            valores[campo] = {int(k): float(v) for k, v in datos[clave].items()}
    if "AREA_TARGET_VIVIENDA" in datos and isinstance(datos["AREA_TARGET_VIVIENDA"], dict):
        valores["area_target"] = {
            int(n): {str(est): (None if t is None else float(t)) for est, t in mp.items()}
            for n, mp in datos["AREA_TARGET_VIVIENDA"].items()
        }
    if "PCT_CIRCULACION_INTERIOR_VIVIENDA" in datos:
        valores["pct_circulacion_interior"] = float(datos["PCT_CIRCULACION_INTERIOR_VIVIENDA"])
    if "UMBRAL_MINIMO_ESTUDIO_M2" in datos:
        valores["umbral_minimo_estudio_m2"] = float(datos["UMBRAL_MINIMO_ESTUDIO_M2"])
    if pct_circulacion_interior is not None:
        valores["pct_circulacion_interior"] = max(0.0, float(pct_circulacion_interior))
    return replace(CONFIG_DEFAULT, **valores) if valores else CONFIG_DEFAULT


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


def _salon_min_para(n_dorms: int, cfg: ProgramaViviendaConfig = CONFIG_DEFAULT) -> float:
    """Salón (estancia E) mínimo del Anexo I.5 por nº de dormitorios.

    Tabla VPO Junta de Andalucía: 1d=14, 2d=16, 3d=18, 4d=20 y "más de 4
    dormitorios"=24 m². La UI llega hasta 4d+, pero el combinador puede generar
    N≥5; para esos casos (o cualquier n fuera de tabla) se aplica el tramo
    ">4 dormitorios".
    """
    if n_dorms in cfg.salon_min:
        return float(cfg.salon_min[n_dorms])
    return 24.0 if n_dorms >= 5 else 20.0


def _salon_cocina_min_para(n_dorms: int, cfg: ProgramaViviendaConfig = CONFIG_DEFAULT) -> float:
    """Salón-cocina (E+Comedor+Cocina) mínimo del Anexo I.5 por nº de dormitorios.

    Tabla VPO: 1d=20, 2d=20, 3d=24, 4d=24 y "más de 4 dormitorios"=28 m².
    """
    if n_dorms in cfg.salon_mas_cocina_min:
        return float(cfg.salon_mas_cocina_min[n_dorms])
    return 28.0 if n_dorms >= 5 else 24.0


def _repartir_con_suelo(
    escalantes: list[tuple[str, float]], util_principal: float,
) -> dict[str, float]:
    """Reparte `util_principal` entre las estancias que escalan (salón +
    dormitorios) garantizando su superficie mínima del Anexo I.5.

    - Caso normal (`util_principal ≥ Σ mínimos`): cada estancia recibe su mínimo
      más una cuota proporcional del sobrante (las de mayor mínimo crecen más).
      Esto coincide al céntimo con el reparto proporcional puro `mín·util/Σmín`,
      pero nunca por debajo del mínimo (el salón conserva `SALON_MIN[n_dorms]`).
    - Caso degradado (unidad infradimensionada, `util_principal < Σ mínimos`): se
      prioriza el salón —estancia principal del Anexo I.5—, que conserva su
      mínimo; el resto se reparte entre los dormitorios. Si ni el salón cabe,
      reparto proporcional puro.
    """
    suma_min = sum(m for _, m in escalantes)
    if not escalantes or suma_min <= 0:
        return {n: 0.0 for n, _ in escalantes}
    if util_principal + 1e-9 >= suma_min:
        sobrante = util_principal - suma_min
        return {n: m + sobrante * (m / suma_min) for n, m in escalantes}
    salon = next((n for n, _ in escalantes if n in ("salon", "salon_cocina")), None)
    if salon is None:
        return {n: util_principal * (m / suma_min) for n, m in escalantes}
    salon_min = next(m for n, m in escalantes if n == salon)
    out = {salon: min(util_principal, salon_min)}
    resto = max(0.0, util_principal - out[salon])
    dorms = [(n, m) for n, m in escalantes if n != salon]
    suma_dorms = sum(m for _, m in dorms)
    for n, m in dorms:
        out[n] = resto * (m / suma_dorms) if suma_dorms > 0 else 0.0
    return out


def programa_vivienda(
    n_dorms: int,
    util_disponible: float,
    salon_cocina_open: bool = False,
    cfg: ProgramaViviendaConfig = CONFIG_DEFAULT,
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
        return _programa_estudio(util_disponible, cfg)

    targets_n = cfg.area_target.get(n_dorms, {})
    # Fallback si la BBDD aún no se ha cargado: usa la política por defecto
    # (cocina=min+1, banos=min+2, aseo=min+1, salón/dormitorios escalan).
    if not targets_n:
        targets_n = _targets_default_para(n_dorms, cfg)

    # 1. Circulación interior fija (% del útil).
    pct_circ = cfg.pct_circulacion_interior / 100.0
    circ_target = util_disponible * pct_circ

    # 2. Selección de estancias según salon_cocina_open y n_dorms.
    nombres = _nombres_estancias_vivienda(n_dorms, util_disponible, salon_cocina_open)

    # 3. Separa fijas (con target en BBDD) de escalantes (target=None).
    fijas: list[tuple[str, float, float]] = []      # (nombre, min_m2, target)
    escalantes: list[tuple[str, float]] = []        # (nombre, min_m2)
    for est in nombres:
        min_est = _area_min_estancia(est, n_dorms, salon_cocina_open, cfg)
        tgt = targets_n.get(est)
        if tgt is None:
            escalantes.append((est, min_est))
        else:
            # El target fijo (cocina/baño/aseo) se sembró desacoplado del mínimo y
            # `actualizar()` no lo recalcula al editar el mínimo: si el usuario sube
            # el mínimo por encima del target sembrado, la estancia saldría más
            # pequeña que su mínimo real. Se ancla el target al mínimo vigente.
            fijas.append((est, min_est, max(float(tgt), min_est)))

    suma_fijas = sum(t for _, _, t in fijas)
    util_principal = max(0.0, util_disponible - circ_target - suma_fijas)

    estancias: list[Estancia] = []

    # 4. Estancias en orden semánticamente útil para el modal:
    #    salón → cocina → dormitorios → baños → circulación.
    targets_por_nombre: dict[str, float] = {est: t for est, _, t in fijas}
    targets_por_nombre.update(_repartir_con_suelo(escalantes, util_principal))

    for est in nombres:
        min_est = _area_min_estancia(est, n_dorms, salon_cocina_open, cfg)
        # Suelo duro: ninguna estancia se emite por debajo de su mínimo del Anexo
        # (protege también el reparto degradado de unidades infradimensionadas).
        target = max(targets_por_nombre[est], min_est)
        estancias.append(Estancia(est, _CATEGORIA_ESTANCIA.get(est, "publica"), min_est, round(target, 2)))

    if circ_target > 1e-6:
        estancias.append(Estancia(
            "circulacion_interior", "circulacion", 0.0, round(circ_target, 2),
        ))

    return estancias


def _programa_estudio(
    util_disponible: float, cfg: ProgramaViviendaConfig = CONFIG_DEFAULT,
) -> list[Estancia]:
    """Estancias del estudio (n_dorms=0) escaladas a `util_disponible`.

    Anexo I.5: el estudio tiene cocina y baño independientes; su estancia única
    (`espacio_principal`) hace de salón y dormitorio. El catálogo de BBDD sembra
    estas 4 estancias con target sumando el útil objetivo del estudio; si
    `util_disponible` ≠ esa suma, las áreas se escalan proporcionalmente (el
    objetivo del estudio = la suma de targets —ver `util_minimo_vivienda`—, así
    que en el reparto el factor es ≥ 1 y la cocina nunca baja de su mínimo).
    """
    targets = cfg.area_target.get(0, {})
    if not targets:
        # Fallback si la BBDD aún no se ha cargado.
        targets = {
            "espacio_principal": cfg.min_espacio_principal + 4.0,
            "cocina": cfg.min_cocina + 1.0,
            "bano": 4.0,
            "circulacion_interior": 3.0,
        }

    nombres_ordenados = ["espacio_principal", "cocina", "bano", "circulacion_interior"]
    suma_baseline = sum(float(targets[e]) for e in nombres_ordenados if e in targets)
    factor = (util_disponible / suma_baseline) if suma_baseline > 0 else 1.0

    mins = {
        "espacio_principal": cfg.min_espacio_principal,
        "cocina": cfg.min_cocina,
        "bano": cfg.min_bano,
        "circulacion_interior": 0.0,
    }
    estancias: list[Estancia] = []
    for est in nombres_ordenados:
        if est not in targets:
            continue
        min_est = mins.get(est, 0.0)
        # Suelo duro: cocina y baño (mínimos independientes) y el espacio principal
        # nunca por debajo de su mínimo, aunque el factor de escala sea < 1 o el
        # mínimo editado supere el target sembrado.
        target_escalado = max(round(float(targets[est]) * factor, 2), min_est)
        estancias.append(Estancia(
            est, _CATEGORIA_ESTANCIA.get(est, "publica"),
            min_est, target_escalado,
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
    # Baños por nº de dormitorios (Anexo I.5): 1 hasta 2 dorms, 2 desde 3 dorms.
    nombres.extend(nombres_banos(banos_vivienda(n_dorms)))
    return nombres


def _area_min_estancia(
    est: str, n_dorms: int, salon_cocina_open: bool,
    cfg: ProgramaViviendaConfig = CONFIG_DEFAULT,
) -> float:
    if est == "salon":
        return _salon_min_para(n_dorms, cfg)
    if est == "salon_cocina":
        return _salon_cocina_min_para(n_dorms, cfg)
    if est == "cocina":
        return float(cfg.min_cocina)
    if est == "dormitorio_1":
        return float(cfg.min_dorm_doble)
    if est.startswith("dormitorio_"):
        return float(cfg.min_dorm_individual)
    if est == "bano" or est.startswith("bano_"):
        return float(cfg.min_bano)
    return 0.0


def _targets_default_para(
    n_dorms: int, cfg: ProgramaViviendaConfig = CONFIG_DEFAULT,
) -> dict[str, float | None]:
    """Política por defecto cuando la BBDD aún no se ha cargado.

    Replica los targets que sembraría `seed_normativa._filas_anexo_i_vivienda`.
    """
    out: dict[str, float | None] = {
        "salon": None,
        "salon_cocina": None,
        "cocina": cfg.min_cocina + 1.0,
        "dormitorio_1": None,
    }
    for i in range(2, n_dorms + 1):
        out[f"dormitorio_{i}"] = None
    # Baños completos (Anexo I.5): 1 hasta 2 dorms, 2 desde 3 dorms.
    for nombre in nombres_banos(banos_vivienda(n_dorms)):
        out[nombre] = cfg.min_bano + 2.0
    return out


def util_maximo(n_dorms: int, cfg: ProgramaViviendaConfig = CONFIG_DEFAULT) -> float:
    return cfg.util_max.get(n_dorms, cfg.util_max[4])


def util_minimo_vivienda(
    n_dorms: int, salon_cocina_open: bool = False,
    cfg: ProgramaViviendaConfig = CONFIG_DEFAULT,
) -> float:
    """Mínimo viable de una vivienda.

    - Estudio: la suma de los targets del programa (estancia única + cocina +
      baño + circulación interior, Anexo I.5), con piso en
      `umbral_minimo_estudio_m2` (25 m² excluyendo servicios comunes, VPO). Es
      también el útil objetivo, de modo que en el reparto el estudio se escala
      con factor ≥ 1 y la cocina respeta su mínimo independiente (7 m²).
    - 1d+: suma de mínimos × (1 + %circulación/100) — el % es editable (panel
      de diseño) y compartido con los demás usos; antes era un 1.15 fijo.
    """
    if n_dorms == 0:
        targets = cfg.area_target.get(0) or {
            "espacio_principal": cfg.min_espacio_principal + 4.0,
            "cocina": cfg.min_cocina + 1.0,
            "bano": 4.0,
            "circulacion_interior": 3.0,
        }
        suma_target = sum(float(t) for t in targets.values() if t is not None)
        return round(max(cfg.umbral_minimo_estudio_m2, suma_target), 2)
    prog = programa_vivienda(n_dorms, util_disponible=util_maximo(n_dorms, cfg),
                             salon_cocina_open=salon_cocina_open, cfg=cfg)
    factor = 1.0 + cfg.pct_circulacion_interior / 100.0
    return round(sum(e.area_min_m2 for e in prog) * factor, 2)


def descriptor_tipologia_vivienda(
    n_dorms: int,
    salon_cocina_open: bool = False,
    cfg: ProgramaViviendaConfig = CONFIG_DEFAULT,
) -> TipologiaUnidadDescriptor:
    """Descriptor de una tipología de vivienda para el reparto genérico."""
    return TipologiaUnidadDescriptor(
        slug=str(n_dorms),
        util_objetivo=util_maximo(n_dorms, cfg),
        util_minimo=util_minimo_vivienda(n_dorms, salon_cocina_open, cfg),
        util_maximo=util_maximo(n_dorms, cfg),
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
def _dorms_de_combo_vivienda(
    combo: ComboDormitorios, cfg: ProgramaViviendaConfig = CONFIG_DEFAULT,
) -> list[tuple[str, float]]:
    """[(tamaño, min_m2)] de los dormitorios de la combinación, orden canónico."""
    tam_min = {"individual": cfg.min_dorm_individual, "doble": cfg.min_dorm_doble}
    dorms: list[tuple[str, float]] = []
    for tam in sorted(combo.composicion):
        for _ in range(combo.composicion[tam]):
            dorms.append((tam, float(tam_min.get(tam, cfg.min_dorm_individual))))
    return dorms


def programa_vivienda_combo(
    combo: ComboDormitorios,
    util_disponible: float,
    salon_cocina_open: bool = False,
    cfg: ProgramaViviendaConfig = CONFIG_DEFAULT,
) -> list[Estancia]:
    """Estancias de una vivienda de N dormitorios (combinación de tamaños).

    Misma política de reparto que `programa_vivienda` (circulación 15 %, cocina y
    baños a target fijo, salón + dormitorios escalan), pero con un dormitorio por
    elemento de la combinación, dimensionado por su tamaño (individual / doble).
    """
    if util_disponible <= 0:
        return []
    if combo.es_estudio:
        return _programa_estudio(util_disponible, cfg)

    n_dorms = combo.n_dorms
    dorms = _dorms_de_combo_vivienda(combo, cfg)
    dorm_min_total = sum(m for _, m in dorms)

    circ_target = util_disponible * (cfg.pct_circulacion_interior / 100.0)

    salon_min = (
        _salon_cocina_min_para(n_dorms, cfg) if salon_cocina_open
        else _salon_min_para(n_dorms, cfg)
    )
    # Nº de baños por nº de dormitorios (Anexo I.5): 1 hasta 2 dorms, 2 desde 3.
    banos_unidad = nombres_banos(banos_vivienda(n_dorms))

    # Escalantes (salón + dormitorios) vs fijas (cocina + baños).
    escalantes: list[tuple[str, float]] = []
    fijas: list[tuple[str, float, float]] = []   # (nombre, min, target)
    if salon_cocina_open:
        escalantes.append(("salon_cocina", salon_min))
    else:
        escalantes.append(("salon", salon_min))
        fijas.append(("cocina", float(cfg.min_cocina), float(cfg.min_cocina + 1.0)))
    for i, (_tam, dmin) in enumerate(dorms, start=1):
        escalantes.append((f"dormitorio_{i}", dmin))
    # Todos los baños son completos (min_bano + 2 de target).
    for nombre in banos_unidad:
        fijas.append((nombre, float(cfg.min_bano), float(cfg.min_bano + 2.0)))

    suma_fijas = sum(t for _, _, t in fijas)
    util_principal = max(0.0, util_disponible - circ_target - suma_fijas)

    targets: dict[str, float] = {n: t for n, _, t in fijas}
    targets.update(_repartir_con_suelo(escalantes, util_principal))

    mins: dict[str, float] = {n: m for n, m, _ in fijas}
    mins.update({n: m for n, m in escalantes})

    # Orden de salida: salón → cocina → dormitorios → baños → circulación.
    orden: list[str] = ["salon_cocina"] if salon_cocina_open else ["salon", "cocina"]
    orden += [f"dormitorio_{i}" for i in range(1, n_dorms + 1)]
    orden += banos_unidad

    # Suelo duro: ninguna estancia por debajo de su mínimo (incl. reparto degradado).
    estancias = [
        Estancia(n, _CATEGORIA_ESTANCIA.get(n, "publica"), mins.get(n, 0.0),
                 round(max(targets.get(n, 0.0), mins.get(n, 0.0)), 2))
        for n in orden
    ]
    if circ_target > 1e-6:
        estancias.append(Estancia("circulacion_interior", "circulacion", 0.0, round(circ_target, 2)))
    return estancias


def _presupuesto_base_vivienda_combo(
    combo: ComboDormitorios, salon_cocina_open: bool,
    cfg: ProgramaViviendaConfig = CONFIG_DEFAULT,
) -> tuple[float, float]:
    """`(Σ mínimos escalantes, Σ target fijas)` de la combinación (Anexo I.5).

    - escalantes = salón (según nº de dormitorios) + dormitorios (individual/doble),
      cada uno a su mínimo del Anexo I.5.
    - fijas = cocina (si no va integrada en el salón) + baños, a su target del
      programa (cocina = mín+1, baño completo = mín+2), que es lo que realmente
      consume `programa_vivienda_combo`.
    """
    n_dorms = combo.n_dorms
    dorm_min_total = sum(m for _, m in _dorms_de_combo_vivienda(combo, cfg))
    if salon_cocina_open:
        escalante_min = _salon_cocina_min_para(n_dorms, cfg) + dorm_min_total
        fijas_target = 0.0
    else:
        escalante_min = _salon_min_para(n_dorms, cfg) + dorm_min_total
        fijas_target = float(cfg.min_cocina + 1.0)
    fijas_target += float(cfg.min_bano + 2.0) * banos_vivienda(n_dorms)
    return escalante_min, fijas_target


def util_minimo_vivienda_combo(
    combo: ComboDormitorios, salon_cocina_open: bool = False,
    cfg: ProgramaViviendaConfig = CONFIG_DEFAULT,
) -> float:
    """Útil VIABLE mínimo de la combinación (Anexo I.5).

    Es el menor útil en que TODAS las estancias alcanzan su mínimo del Anexo I.5
    —el salón según su nº de dormitorios incluido— a la vez que caben la cocina y
    los baños (a su target) y la circulación interior (15 %):

        útil_min = (Σ mínimos salón+dormitorios + target cocina+baños) / (1 − %circ)

    A este útil el reparto da al salón EXACTAMENTE su mínimo A1.5; por encima, el
    salón crece. (El cálculo anterior sumaba sólo los mínimos sin reservar la
    circulación ni el target de cocina/baños, por lo que el salón quedaba por
    debajo de su mínimo.)

    NO se capa al útil máximo VPO: si la suma de mínimos supera el techo editable
    de la tipología, el reparto infradimensionaría la unidad en silencio. En su
    lugar, `CalcularLayout` valida `util_mínimo ≤ útil máximo` antes de calcular y
    bloquea con error si se incumple (R3).
    """
    if combo.es_estudio:
        return util_minimo_vivienda(0, salon_cocina_open, cfg)
    escalante_min, fijas_target = _presupuesto_base_vivienda_combo(combo, salon_cocina_open, cfg)
    pct = cfg.pct_circulacion_interior / 100.0
    minimo = (escalante_min + fijas_target) / max(1e-6, 1.0 - pct)
    return round(minimo, 2)


def util_objetivo_vivienda_combo(
    combo: ComboDormitorios, salon_cocina_open: bool = False,
    cfg: ProgramaViviendaConfig = CONFIG_DEFAULT,
) -> float:
    """Objetivo de m² útil de la combinación = útil viable mínimo del Anexo I.5.

    Apunta al menor útil que cumple los mínimos (salón incluido), para que el
    reparto coloque el máximo nº de viviendas conformes; el salón sale a su mínimo
    A1.5 y crece con cualquier holgura adicional de la planta.
    """
    if combo.es_estudio:
        return util_minimo_vivienda(0, salon_cocina_open, cfg)
    return util_minimo_vivienda_combo(combo, salon_cocina_open, cfg)


def descriptor_tipologia_vivienda_combo(
    combo: ComboDormitorios, salon_cocina_open: bool = False,
    cfg: ProgramaViviendaConfig = CONFIG_DEFAULT,
) -> TipologiaUnidadDescriptor:
    """Descriptor para el reparto a partir de una combinación de vivienda."""
    util_obj = util_objetivo_vivienda_combo(combo, salon_cocina_open, cfg)
    util_min = util_obj if combo.es_estudio else util_minimo_vivienda_combo(combo, salon_cocina_open, cfg)
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
    cfg: ProgramaViviendaConfig = CONFIG_DEFAULT,
) -> list[tuple[int, float]]:
    """Reparte el útil disponible entre varias tipologías de vivienda.

    Mantiene la firma int-based histórica (la usa la rama de preview de
    `capacidad.py`); internamente construye descriptores y delega en
    `reparto_multi_tipologia_generico`. Devuelve `[(n_dorms, util_asignado), ...]`.
    """
    if not tipologias or util_disponible <= 0:
        return []
    descriptores = [
        descriptor_tipologia_vivienda(n, salon_cocina_open, cfg) for n in tipologias
    ]
    seleccion = reparto_multi_tipologia_generico(util_disponible, descriptores)
    return [(d.n_dorms_label, util) for d, util in seleccion]
