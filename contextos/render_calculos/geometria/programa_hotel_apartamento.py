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


def _fusionar_minimos(destino: dict, origen: dict) -> None:
    """Actualiza `destino` in-place con `origen` (hasta 1 nivel de anidamiento)."""
    for clave, valor in origen.items():
        if isinstance(valor, dict):
            sub = destino.get(clave)
            if isinstance(sub, dict):
                sub.update({str(k): float(v) for k, v in valor.items()})
            else:
                destino[clave] = {str(k): float(v) for k, v in valor.items()}
        else:
            destino[clave] = float(valor)


def cargar_desde_repo(catalogo) -> bool:
    """Vuelca los mínimos editables de BBDD (Anexo I.2) a las constantes del módulo.

    Hermano de `programa.cargar_desde_repo` (vivienda): hace que las ediciones del
    editor de mínimos lleguen al dimensionado de estancias. Devuelve True si aplicó
    algún override; False si la BBDD está vacía o el catálogo no expone el método.
    """
    obtener = getattr(catalogo, "consolidadas_hotel_apartamento", None)
    if obtener is None:
        return False
    datos = obtener() or {}
    if not datos:
        return False
    g = globals()
    for clave in ("MIN_DORMITORIO_HAP", "MIN_ESTUDIO_HAP", "MIN_SALON_COMEDOR_HAP", "MIN_BANO_HAP"):
        if clave in datos and isinstance(datos[clave], dict):
            _fusionar_minimos(g[clave], datos[clave])
    return True


def _cat_validada(categoria: str) -> str:
    return categoria if categoria in MIN_SALON_COMEDOR_HAP else "3E"


def _tip_validada(tipologia: str) -> str:
    return tipologia if tipologia in TIPOLOGIAS else "doble"


def programa_hotel_apartamento(
    tipologia: str,
    categoria: str,
    util_disponible: float,
) -> list[Estancia]:
    """Estancias COMPUTABLES de un hotel-apartamento (salón-comedor-cocina + dormitorio + baño).

    Devuelve solo las estancias que **computan** a efectos turísticos. La
    circulación de acceso (vestíbulo/pasillo interior, NO computable) la añade la
    capa de serialización como remanente del útil. `util_disponible` es el
    presupuesto COMPUTABLE que reparten las estancias: el baño se fija en su
    mínimo y salón-comedor + dormitorio escalan proporcionalmente a sus mínimos
    (nunca por debajo de ellos).
    """
    cat = _cat_validada(categoria)
    tip = _tip_validada(tipologia)
    bano_min = MIN_BANO_HAP[cat]

    if tip == "estudio":
        est = MIN_ESTUDIO_HAP[cat]
        bano_t = bano_min
        salon_t = max(est, util_disponible - bano_t)
        return [
            Estancia("salon_comedor", "publica", est, round(salon_t, 2)),
            Estancia("bano", "servicio", bano_min, round(bano_t, 2)),
        ]

    salon_min = MIN_SALON_COMEDOR_HAP[cat]
    dorm_min = MIN_DORMITORIO_HAP[tip][cat]
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


# % de circulación interior de la unidad, editable y compartido con los demás
# usos (antes 1.15 fijo). `casos_uso` lo fija con `set_pct_circulacion_interior`.
PCT_CIRCULACION_INTERIOR = 15.0


def set_pct_circulacion_interior(pct: float) -> None:
    """Fija el % de circulación interior (panel de diseño → motor)."""
    global PCT_CIRCULACION_INTERIOR
    PCT_CIRCULACION_INTERIOR = max(0.0, float(pct))


def _factor_circulacion() -> float:
    return 1.0 + PCT_CIRCULACION_INTERIOR / 100.0


def _base_util(categoria: str, tipologia: str) -> float:
    return sum(e.area_min_m2 for e in programa_hotel_apartamento(tipologia, categoria, 0.0))


def util_objetivo_hotel_apartamento(categoria: str, tipologia: str) -> float:
    """Objetivo de m² útil por unidad: mínimos + % circulación interior."""
    return round(_base_util(categoria, tipologia) * _factor_circulacion(), 2)


def util_minimo_hotel_apartamento(categoria: str, tipologia: str) -> float:
    return round(_base_util(categoria, tipologia), 2)


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
) -> TipologiaUnidadDescriptor:
    tip = _tip_validada(tipologia)
    util_obj = util_objetivo_hotel_apartamento(categoria, tip)
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
) -> ProgramaUso:
    tip = _tip_validada(tipologia)
    util_obj = util_objetivo_hotel_apartamento(categoria, tip)
    util_min = util_minimo_hotel_apartamento(categoria, tip)
    sociales = total_sociales_obligatorias_m2(n_unidades_estimado, categoria)
    return ProgramaUso(
        util_objetivo_unidad_m2=util_obj,
        area_min_unidad_m2=util_min,
        util_max_unidad_m2=round(util_obj * 1.25, 2),
        n_dormitorios=0 if tip == "estudio" else 1,
        tipo_unidad="hotel_apartamento",
        area_servicios_obligatorios_m2=sociales,
    )
