"""Programa arquitectónico de Hoteles / Hostales / Pensiones / Albergues (Anexo I.1).

Modelo distinto al del apartamento turístico: la **habitación es la unidad de
alojamiento** (no un apartamento con cocina). Cada unidad es un espacio
principal + baño interior, salvo en pensión y albergue, donde la normativa
admite baños compartidos fuera de la unidad.

El salón social y las áreas sociales vinculadas son comunes del establecimiento
(se reservan por unidad de alojamiento; en albergue, por plaza). No se generan
como geometría en el MVP — se restan del techo útil repartible.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from .programa import Estancia
from .programa_uso import ProgramaUso, TipologiaUnidadDescriptor


CATEGORIAS = (
    "hotel_5", "hotel_4", "hotel_3", "hotel_2", "hotel_1",
    "hostal_2", "hostal_1", "pension", "albergue",
)

# Anexo I.1 — superficies mínimas de la unidad de alojamiento (m²).
# Las combinaciones marcadas "—" en el PDF simplemente no aparecen aquí.
MIN_HABITACION: dict[tuple[str, str], float] = {
    # individual
    ("hotel_5", "individual"): 15.0, ("hotel_4", "individual"): 13.0, ("hotel_3", "individual"): 12.0,
    ("hotel_2", "individual"): 10.0, ("hotel_1", "individual"): 10.0, ("hostal_2", "individual"): 9.0,
    ("hostal_1", "individual"): 9.0, ("pension", "individual"): 9.0, ("albergue", "individual"): 9.0,
    # doble
    ("hotel_5", "doble"): 20.0, ("hotel_4", "doble"): 18.0, ("hotel_3", "doble"): 17.0,
    ("hotel_2", "doble"): 15.0, ("hotel_1", "doble"): 14.0, ("hostal_2", "doble"): 14.0,
    ("hostal_1", "doble"): 13.0, ("pension", "doble"): 13.0, ("albergue", "doble"): 13.0,
    # triple
    ("hotel_5", "triple"): 25.0, ("hotel_4", "triple"): 22.0, ("hotel_3", "triple"): 21.0,
    ("hotel_2", "triple"): 19.0, ("hotel_1", "triple"): 17.0, ("hostal_2", "triple"): 17.0,
    ("hostal_1", "triple"): 17.0, ("pension", "triple"): 16.0,
    # cuádruple
    ("hotel_5", "cuadruple"): 29.0, ("hotel_4", "cuadruple"): 26.0, ("hotel_3", "cuadruple"): 25.0,
    ("hotel_2", "cuadruple"): 22.0, ("hotel_1", "cuadruple"): 20.0, ("hostal_2", "cuadruple"): 20.0,
    ("hostal_1", "cuadruple"): 18.0, ("pension", "cuadruple"): 18.0,
    # múltiple (solo albergue; el PDF marca "Sí" sin m² → valor de referencia editable)
    ("albergue", "multiple"): 20.0,
}

# Fila "Salón" del Anexo I.1 — superficie social mínima del establecimiento.
SALON_SOCIAL_MIN: dict[str, float] = {
    "hotel_5": 12.0, "hotel_4": 10.0, "hotel_3": 10.0, "hotel_2": 9.0, "hotel_1": 8.0,
    "hostal_2": 8.0, "hostal_1": 8.0, "pension": 8.0, "albergue": 0.0,
}

# Áreas sociales vinculadas por u.a. (Anexo I.1, 2ª tabla). Albergue: por plaza.
AREA_SOCIAL_POR_UA: dict[str, float] = {
    "hotel_5": 4.0, "hotel_4": 3.2, "hotel_3": 3.0, "hotel_2": 2.0, "hotel_1": 2.0,
    "hostal_2": 1.5, "hostal_1": 0.0, "pension": 0.0, "albergue": 0.0,
}
AREA_SOCIAL_POR_PLAZA: dict[str, float] = {"albergue": 1.0}

# Baño interior obligatorio salvo en pensión y albergue (admiten compartido).
BANO_INTERIOR_OBLIGATORIO: dict[str, bool] = {c: c not in ("pension", "albergue") for c in CATEGORIAS}
# Baño DERIVADO por categoría (A1.1 no lo tabula); editable desde BBDD.
MIN_BANO_HOTELERO: dict[str, float] = {
    "hotel_5": 4.5, "hotel_4": 4.0, "hotel_3": 3.5, "hotel_2": 3.0, "hotel_1": 3.0,
    "hostal_2": 3.0, "hostal_1": 3.0, "pension": 3.0, "albergue": 3.0,
}

TIPOLOGIA_HABITACION_A_PLAZAS = {
    "individual": 1, "doble": 2, "triple": 3, "cuadruple": 4, "multiple": 6,
}


# % de circulación interior de la unidad, editable y compartido con los demás usos.
PCT_CIRCULACION_INTERIOR = 15.0


# ─── Configuración inmutable del programa (§3.8 — sin globals mutables) ──────
# Los mínimos editables del Anexo I.1 (habitación + baño derivado) viven en una
# instancia FROZEN que se pasa como argumento; antes se volcaban a globals
# (`cargar_desde_repo` / `set_pct_circulacion_interior`), cruzando ediciones entre
# requests concurrentes y tests (Pendiente 3.8).
@dataclass(frozen=True)
class ProgramaHoteleroConfig:
    min_habitacion: dict[tuple[str, str], float] = field(default_factory=lambda: dict(MIN_HABITACION))
    min_bano: dict[str, float] = field(default_factory=lambda: dict(MIN_BANO_HOTELERO))
    pct_circulacion_interior: float = PCT_CIRCULACION_INTERIOR


CONFIG_DEFAULT = ProgramaHoteleroConfig()


def config_desde_repo(
    catalogo=None, pct_circulacion_interior: float | None = None,
) -> ProgramaHoteleroConfig:
    """Construye un `ProgramaHoteleroConfig` desde la BBDD (Anexo I.1).

    Sustituye a `cargar_desde_repo` (que mutaba globals). Claves ausentes conservan
    el default; `pct_circulacion_interior`, si se indica (panel), prevalece.
    """
    base = CONFIG_DEFAULT
    obtener = getattr(catalogo, "consolidadas_hotelero", None) if catalogo is not None else None
    try:
        datos = (obtener() or {}) if obtener is not None else {}
    except Exception:
        datos = {}
    campos: dict = {}
    hab = datos.get("MIN_HABITACION")
    if isinstance(hab, dict):
        # Claves tupla (categoria, tipologia).
        nuevo = dict(base.min_habitacion)
        nuevo.update({tuple(k): float(v) for k, v in hab.items()})
        campos["min_habitacion"] = nuevo
    banos = datos.get("MIN_BANO_HOTELERO")
    if isinstance(banos, dict):
        nuevo = dict(base.min_bano)
        nuevo.update({str(k): float(v) for k, v in banos.items()})
        campos["min_bano"] = nuevo
    if pct_circulacion_interior is not None:
        campos["pct_circulacion_interior"] = max(0.0, float(pct_circulacion_interior))
    return replace(base, **campos) if campos else base


def _cat_validada(categoria: str) -> str:
    return categoria if categoria in SALON_SOCIAL_MIN else "hotel_3"


def _habitacion_min(
    categoria: str, tipo: str, cfg: ProgramaHoteleroConfig = CONFIG_DEFAULT,
) -> float:
    cat = _cat_validada(categoria)
    if (cat, tipo) in cfg.min_habitacion:
        return cfg.min_habitacion[(cat, tipo)]
    # Fallback: la doble de la categoría, o 12 m².
    return cfg.min_habitacion.get((cat, "doble"), 12.0)


def _bano_target(categoria: str, cfg: ProgramaHoteleroConfig = CONFIG_DEFAULT) -> float:
    cat = _cat_validada(categoria)
    return (cfg.min_bano[cat] + 0.5) if BANO_INTERIOR_OBLIGATORIO[cat] else 0.0


def programa_habitacion(
    tipo: str, categoria: str, util_disponible: float,
    cfg: ProgramaHoteleroConfig = CONFIG_DEFAULT,
) -> list[Estancia]:
    """Estancias de una unidad de alojamiento hotelera (habitación + baño opcional)."""
    cat = _cat_validada(categoria)
    room_min = _habitacion_min(cat, tipo, cfg)
    bano_min = cfg.min_bano[cat]
    bano_tgt = _bano_target(cat, cfg)

    room_target = max(room_min, util_disponible - bano_tgt)
    estancias = [Estancia("habitacion", "privada", room_min, room_target)]
    if BANO_INTERIOR_OBLIGATORIO[cat]:
        estancias.append(Estancia("bano", "servicio", bano_min, bano_tgt))
    return estancias


def _factor_circulacion(cfg: ProgramaHoteleroConfig = CONFIG_DEFAULT) -> float:
    return 1.0 + cfg.pct_circulacion_interior / 100.0


def util_minimo_habitacion(
    categoria: str, tipo: str, cfg: ProgramaHoteleroConfig = CONFIG_DEFAULT,
) -> float:
    cat = _cat_validada(categoria)
    return round(_habitacion_min(cat, tipo, cfg) + _bano_target(cat, cfg), 2)


def util_objetivo_habitacion(
    categoria: str, tipo: str, cfg: ProgramaHoteleroConfig = CONFIG_DEFAULT,
) -> float:
    """Objetivo de m² útil por unidad: mínimo + % circulación interior."""
    return round(util_minimo_habitacion(categoria, tipo, cfg) * _factor_circulacion(cfg), 2)


def areas_sociales_obligatorias_hotel(
    n_unidades_estimado: int,
    n_plazas_estimado: int,
    categoria: str,
) -> dict[str, float]:
    """Salón / áreas sociales del establecimiento (escala por u.a. o por plaza)."""
    cat = _cat_validada(categoria)
    salon_min = SALON_SOCIAL_MIN[cat]
    por_ua = AREA_SOCIAL_POR_UA[cat] * max(0, n_unidades_estimado)
    por_plaza = AREA_SOCIAL_POR_PLAZA.get(cat, 0.0) * max(0, n_plazas_estimado)
    social = max(salon_min, por_ua, por_plaza)
    if social <= 0:
        return {}
    return {"salon_social": round(social, 2)}


def total_sociales_obligatorias_m2(
    n_unidades_estimado: int,
    n_plazas_estimado: int,
    categoria: str,
) -> float:
    return sum(areas_sociales_obligatorias_hotel(n_unidades_estimado, n_plazas_estimado, categoria).values())


def descriptor_tipologia_hotelero(
    categoria: str, tipo: str, cfg: ProgramaHoteleroConfig = CONFIG_DEFAULT,
) -> TipologiaUnidadDescriptor:
    util_obj = util_objetivo_habitacion(categoria, tipo, cfg)
    plazas = TIPOLOGIA_HABITACION_A_PLAZAS.get(tipo, 2)
    return TipologiaUnidadDescriptor(
        slug=tipo,
        util_objetivo=util_obj,
        # Mínimo viable con circulación interior reservada (R4).
        util_minimo=util_obj,
        util_maximo=round(util_obj * 1.25, 2),
        n_dorms_label=plazas,
        tipo_unidad="habitacion",
        plazas=plazas,
    )


def programa_uso_hotelero(
    categoria: str,
    tipo: str,
    n_unidades_estimado: int = 1,
    n_plazas_estimado: int = 1,
    cfg: ProgramaHoteleroConfig = CONFIG_DEFAULT,
) -> ProgramaUso:
    util_obj = util_objetivo_habitacion(categoria, tipo, cfg)
    util_min = util_minimo_habitacion(categoria, tipo, cfg)
    sociales = total_sociales_obligatorias_m2(n_unidades_estimado, n_plazas_estimado, categoria)
    return ProgramaUso(
        util_objetivo_unidad_m2=util_obj,
        area_min_unidad_m2=util_min,
        util_max_unidad_m2=round(util_obj * 1.25, 2),
        n_dormitorios=TIPOLOGIA_HABITACION_A_PLAZAS.get(tipo, 2),
        tipo_unidad="habitacion",
        area_servicios_obligatorios_m2=sociales,
    )
