"""Programa arquitectónico de Hoteles-Apartamento (Anexo I.2 del PDF).

Comportamiento análogo al apartamento turístico pero con **categorías por
estrellas** (5E–1E) y superficies más generosas. La unidad se clasifica por la
**ocupación del dormitorio** (individual/doble/triple/cuádruple) o es un estudio.

Cada hotel-apartamento se compone de salón-comedor-cocina (open-plan, A1.2 no
tabula cocina por separado) + 1 dormitorio + baño (derivado). Las áreas sociales
vinculadas son las mismas que para el Hotel del mismo nº de estrellas (A1.1):
4 / 3,2 / 3 / 2 / 2 m² por unidad de alojamiento.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from .programa import Estancia
from .programa_uso import ProgramaUso, TipologiaUnidadDescriptor


ESTRELLAS = ("5E", "4E", "3E", "2E", "1E")
TIPOLOGIAS = ("estudio", "individual", "doble", "triple", "cuadruple")

# Anexo I.2 — m² mínimos por estrella.
MIN_DORMITORIO_HAP: dict[str, dict[str, float]] = {
    "individual": {"5E": 15.0, "4E": 13.0, "3E": 12.0, "2E": 10.0, "1E": 10.0},
    "doble":      {"5E": 18.0, "4E": 16.0, "3E": 15.0, "2E": 14.0, "1E": 14.0},
    "triple":     {"5E": 22.0, "4E": 19.0, "3E": 18.0, "2E": 17.0, "1E": 17.0},
    "cuadruple":  {"5E": 25.0, "4E": 22.0, "3E": 21.0, "2E": 20.0, "1E": 20.0},
}
MIN_ESTUDIO_HAP: dict[str, float] = {"5E": 33.0, "4E": 28.0, "3E": 27.0, "2E": 23.0, "1E": 23.0}
MIN_SALON_COMEDOR_HAP: dict[str, float] = {"5E": 17.0, "4E": 16.0, "3E": 12.0, "2E": 10.0, "1E": 10.0}  # hasta 4 personas
# Baño DERIVADO (A1.2 no lo tabula); editable desde BBDD.
MIN_BANO_HAP: dict[str, float] = {"5E": 4.5, "4E": 4.0, "3E": 3.5, "2E": 3.0, "1E": 3.0}

# Áreas sociales por u.a. = Hotel del mismo nº de estrellas (Anexo I.1).
AREA_SOCIAL_POR_UA_HAP: dict[str, float] = {"5E": 4.0, "4E": 3.2, "3E": 3.0, "2E": 2.0, "1E": 2.0}

PLAZAS: dict[str, int] = {"estudio": 2, "individual": 1, "doble": 2, "triple": 3, "cuadruple": 4}


# % de circulación interior de la unidad, editable y compartido con los demás usos.
PCT_CIRCULACION_INTERIOR = 15.0


# ─── Configuración inmutable del programa (§3.8 — sin globals mutables) ──────
# Los mínimos editables del Anexo I.2 viven en una instancia FROZEN que se pasa
# como argumento; antes se volcaban a globals (`cargar_desde_repo` /
# `set_pct_circulacion_interior`), cruzando ediciones entre requests y tests.
@dataclass(frozen=True)
class ProgramaHotelApartamentoConfig:
    min_dormitorio: dict[str, dict[str, float]] = field(
        default_factory=lambda: {k: dict(v) for k, v in MIN_DORMITORIO_HAP.items()})
    min_estudio: dict[str, float] = field(default_factory=lambda: dict(MIN_ESTUDIO_HAP))
    min_salon_comedor: dict[str, float] = field(default_factory=lambda: dict(MIN_SALON_COMEDOR_HAP))
    min_bano: dict[str, float] = field(default_factory=lambda: dict(MIN_BANO_HAP))
    pct_circulacion_interior: float = PCT_CIRCULACION_INTERIOR


CONFIG_DEFAULT = ProgramaHotelApartamentoConfig()


def _fusionar_minimos(destino: dict, origen: dict) -> dict:
    """Devuelve una COPIA de `destino` fusionada con `origen` (hasta 1 nivel). Pura."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in destino.items()}
    for clave, valor in origen.items():
        if isinstance(valor, dict):
            sub = out.get(clave)
            if isinstance(sub, dict):
                sub.update({str(k): float(v) for k, v in valor.items()})
            else:
                out[clave] = {str(k): float(v) for k, v in valor.items()}
        else:
            out[clave] = float(valor)
    return out


def config_desde_repo(
    catalogo=None, pct_circulacion_interior: float | None = None,
) -> ProgramaHotelApartamentoConfig:
    """Construye un `ProgramaHotelApartamentoConfig` desde la BBDD (Anexo I.2).

    Sustituye a `cargar_desde_repo` (que mutaba globals). Claves ausentes conservan
    el default; `pct_circulacion_interior`, si se indica (panel), prevalece.
    """
    base = CONFIG_DEFAULT
    obtener = getattr(catalogo, "consolidadas_hotel_apartamento", None) if catalogo is not None else None
    try:
        datos = (obtener() or {}) if obtener is not None else {}
    except Exception:
        datos = {}
    campos: dict = {}
    for clave, campo in (
        ("MIN_DORMITORIO_HAP", "min_dormitorio"), ("MIN_ESTUDIO_HAP", "min_estudio"),
        ("MIN_SALON_COMEDOR_HAP", "min_salon_comedor"), ("MIN_BANO_HAP", "min_bano"),
    ):
        if clave in datos and isinstance(datos[clave], dict):
            campos[campo] = _fusionar_minimos(getattr(base, campo), datos[clave])
    if pct_circulacion_interior is not None:
        campos["pct_circulacion_interior"] = max(0.0, float(pct_circulacion_interior))
    return replace(base, **campos) if campos else base


def _cat_validada(categoria: str, cfg: ProgramaHotelApartamentoConfig = CONFIG_DEFAULT) -> str:
    return categoria if categoria in cfg.min_salon_comedor else "3E"


def _tip_validada(tipologia: str) -> str:
    return tipologia if tipologia in TIPOLOGIAS else "doble"


def programa_hotel_apartamento(
    tipologia: str,
    categoria: str,
    util_disponible: float,
    cfg: ProgramaHotelApartamentoConfig = CONFIG_DEFAULT,
) -> list[Estancia]:
    """Estancias COMPUTABLES de un hotel-apartamento (salón-comedor-cocina + dormitorio + baño).

    Devuelve solo las estancias que **computan** a efectos turísticos. La
    circulación de acceso (vestíbulo/pasillo interior, NO computable) la añade la
    capa de serialización como remanente del útil. `util_disponible` es el
    presupuesto COMPUTABLE que reparten las estancias: el baño se fija en su
    mínimo y salón-comedor + dormitorio escalan proporcionalmente a sus mínimos
    (nunca por debajo de ellos).
    """
    cat = _cat_validada(categoria, cfg)
    tip = _tip_validada(tipologia)
    bano_min = cfg.min_bano[cat]

    if tip == "estudio":
        est = cfg.min_estudio[cat]
        bano_t = bano_min
        salon_t = max(est, util_disponible - bano_t)
        return [
            Estancia("salon_comedor", "publica", est, round(salon_t, 2)),
            Estancia("bano", "servicio", bano_min, round(bano_t, 2)),
        ]

    salon_min = cfg.min_salon_comedor[cat]
    dorm_min = cfg.min_dormitorio[tip][cat]
    bano_t = bano_min
    resto = max(0.0, util_disponible - bano_t)
    base = salon_min + dorm_min
    if base > 0 and resto > 0:
        salon_t = max(salon_min, resto * salon_min / base)
        dorm_t = max(dorm_min, resto * dorm_min / base)
    else:
        salon_t, dorm_t = salon_min, dorm_min
    return [
        Estancia("salon_comedor", "publica", salon_min, round(salon_t, 2)),
        Estancia("dormitorio_1", "privada", dorm_min, round(dorm_t, 2)),
        Estancia("bano", "servicio", bano_min, round(bano_t, 2)),
    ]


def _factor_circulacion(cfg: ProgramaHotelApartamentoConfig = CONFIG_DEFAULT) -> float:
    return 1.0 + cfg.pct_circulacion_interior / 100.0


def _base_util(
    categoria: str, tipologia: str,
    cfg: ProgramaHotelApartamentoConfig = CONFIG_DEFAULT,
) -> float:
    return sum(e.area_min_m2 for e in programa_hotel_apartamento(tipologia, categoria, 0.0, cfg))


def util_objetivo_hotel_apartamento(
    categoria: str, tipologia: str,
    cfg: ProgramaHotelApartamentoConfig = CONFIG_DEFAULT,
) -> float:
    """Objetivo de m² útil por unidad: mínimos + % circulación interior."""
    return round(_base_util(categoria, tipologia, cfg) * _factor_circulacion(cfg), 2)


def util_minimo_hotel_apartamento(
    categoria: str, tipologia: str,
    cfg: ProgramaHotelApartamentoConfig = CONFIG_DEFAULT,
) -> float:
    return round(_base_util(categoria, tipologia, cfg), 2)


def areas_sociales_obligatorias_hap(n_unidades_estimado: int, categoria: str) -> dict[str, float]:
    """Áreas sociales vinculadas (m² por u.a., como el Hotel equivalente, A1.1)."""
    cat = _cat_validada(categoria)
    por_ua = AREA_SOCIAL_POR_UA_HAP[cat]
    if por_ua <= 0:
        return {}
    return {"areas_sociales": round(por_ua * n_unidades_estimado, 2)}


def total_sociales_obligatorias_m2(n_unidades_estimado: int, categoria: str) -> float:
    return sum(areas_sociales_obligatorias_hap(n_unidades_estimado, categoria).values())


def descriptor_tipologia_hotel_apartamento(
    categoria: str,
    tipologia: str,
    cfg: ProgramaHotelApartamentoConfig = CONFIG_DEFAULT,
) -> TipologiaUnidadDescriptor:
    tip = _tip_validada(tipologia)
    util_obj = util_objetivo_hotel_apartamento(categoria, tip, cfg)
    return TipologiaUnidadDescriptor(
        slug=tip,
        util_objetivo=util_obj,
        # Mínimo viable con circulación interior reservada (R4).
        util_minimo=util_obj,
        util_maximo=round(util_obj * 1.25, 2),
        n_dorms_label=PLAZAS.get(tip, 2),
        tipo_unidad="hotel_apartamento",
        plazas=PLAZAS.get(tip, 2),
    )


def programa_uso_hotel_apartamento(
    categoria: str,
    tipologia: str,
    n_unidades_estimado: int = 1,
    cfg: ProgramaHotelApartamentoConfig = CONFIG_DEFAULT,
) -> ProgramaUso:
    tip = _tip_validada(tipologia)
    util_obj = util_objetivo_hotel_apartamento(categoria, tip, cfg)
    util_min = util_minimo_hotel_apartamento(categoria, tip, cfg)
    sociales = total_sociales_obligatorias_m2(n_unidades_estimado, categoria)
    return ProgramaUso(
        util_objetivo_unidad_m2=util_obj,
        area_min_unidad_m2=util_min,
        util_max_unidad_m2=round(util_obj * 1.25, 2),
        n_dormitorios=0 if tip == "estudio" else 1,
        tipo_unidad="hotel_apartamento",
        area_servicios_obligatorios_m2=sociales,
    )
