"""Envolvente edificatoria (§2.4): huella + plantas + patios interiores.

Desde iteración 3 cada Planta lleva dos atributos extra:
- `computa_edif`: si la planta consume techo edificable (regla del PGOU).
- `tipo`: "regular" | "atico" | "sotano".

Esto permite a `capacidad.calcular_capacidad()` saber qué plantas suman al
techo máximo y qué plantas son habitables/no habitables.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from shapely.geometry import Polygon, box, Point

from .config import Parametros


@dataclass
class Patio:
    geometry: Polygon
    area_m2: float
    luz_recta_m: float


@dataclass
class Planta:
    n: int                       # 0=PB, 1=P1, ...
    footprint: Polygon
    interior: Polygon
    patios: list[Patio] = field(default_factory=list)
    area_construida_m2: float = 0.0
    area_util_m2: float = 0.0
    computa_edif: bool = True
    tipo: str = "regular"        # "regular" | "atico" | "sotano"


@dataclass
class Envolvente:
    parcela: Polygon
    plantas: list[Planta]
    edificabilidad_consumida: float
    edificabilidad_max: float


def aplicar_retranqueos(parcela: Polygon, params: Parametros) -> Polygon:
    """Aplica retranqueos diferenciados (frontal/lateral/trasero).

    Si los tres son 0 (caso Sevilla casco), devuelve la parcela tal cual. Para
    el MVP se aplica el máximo como buffer uniforme; una versión más precisa
    requeriría mover cada lado individualmente según su tipo.
    """
    p = params.urbanismo
    if p.retranqueo_frontal == 0 and p.retranqueo_lateral == 0 and p.retranqueo_trasero == 0:
        return parcela
    max_retr = max(p.retranqueo_frontal, p.retranqueo_lateral, p.retranqueo_trasero)
    return parcela.buffer(-max_retr).buffer(0)


def detectar_patio(interior_planta: Polygon, params: Parametros) -> Optional[Patio]:
    """Si la planta es demasiado profunda, abrimos un patio interior."""
    if interior_planta.is_empty:
        return None

    try:
        from shapely.ops import polylabel
        p_int: Point = polylabel(interior_planta, tolerance=0.5)
    except Exception:
        p_int = interior_planta.representative_point()

    d_max = p_int.distance(interior_planta.exterior)
    if d_max <= params.diseno.profundidad_max_sin_patio / 2:
        return None

    lr = params.diseno.luz_recta_patio_min
    area_target = params.diseno.area_patio_min
    lado_b = max(lr, area_target / lr)
    rect = box(p_int.x - lr / 2, p_int.y - lado_b / 2,
               p_int.x + lr / 2, p_int.y + lado_b / 2)
    rect = rect.intersection(interior_planta)
    if rect.is_empty or rect.area < area_target * 0.6:
        return None
    return Patio(geometry=rect, area_m2=rect.area, luz_recta_m=lr)


def _huella_atico(huella: Polygon, retranqueo_atico: float) -> Polygon:
    """Huella reducida del ático tras aplicar el retranqueo perimetral.

    Si el buffer negativo deja huella vacía o muy degenerada, devolvemos un
    polígono vacío (capacidad lo tratará como ático no habitable).
    """
    if retranqueo_atico <= 0:
        return huella
    reducida = huella.buffer(-retranqueo_atico).buffer(0)
    if reducida.is_empty:
        return Polygon()
    # Si el polígono se convirtió en MultiPolygon (corte por estrechamientos),
    # nos quedamos con la parte más grande.
    if hasattr(reducida, "geoms"):
        reducida = max(reducida.geoms, key=lambda g: g.area)
    return reducida


def construir_envolvente(parcela: Polygon, params: Parametros) -> Envolvente:
    """Pipeline §2.4 completo: retranqueos → huella → N plantas → patios.

    Iteración 3: añade sótano (si `tiene_sotano`) y ático (si `tiene_atico`)
    como plantas extra con su huella propia y su flag `computa_edif`. El
    cálculo de techo consumido solo suma las plantas que computan.
    """
    huella = aplicar_retranqueos(parcela, params)
    if huella.is_empty:
        raise ValueError("Tras retranqueos no queda espacio edificable.")

    espesor = params.diseno.espesor_muro_fachada
    interior_base = huella.buffer(-espesor)
    if interior_base.is_empty:
        raise ValueError("Huella demasiado pequeña para los espesores configurados.")

    plantas: list[Planta] = []
    edif_acumulada = 0.0

    n_offset = 0

    # ── Sótano (si procede) — siempre planta 0 si existe ─────────────────────
    if params.urbanismo.tiene_sotano:
        sotano = Planta(
            n=-1,  # índice negativo para distinguirlo
            footprint=huella,
            interior=interior_base,
            patios=[],
            area_construida_m2=huella.area,
            area_util_m2=interior_base.area,
            computa_edif=params.urbanismo.sotano_computa_edificabilidad,
            tipo="sotano",
        )
        plantas.append(sotano)
        if sotano.computa_edif:
            edif_acumulada += huella.area

    # ── Plantas regulares ────────────────────────────────────────────────────
    for n in range(params.programa.n_plantas):
        f = huella
        i = interior_base
        patios: list[Patio] = []
        patio = detectar_patio(i, params)
        if patio is not None:
            i = i.difference(patio.geometry)
            patios.append(patio)
        plantas.append(Planta(
            n=n + n_offset,
            footprint=f,
            interior=i,
            patios=patios,
            area_construida_m2=f.area,
            area_util_m2=i.area,
            computa_edif=True,
            tipo="regular",
        ))
        edif_acumulada += f.area

    # ── Ático (si procede) — encima de la última regular ────────────────────
    if params.urbanismo.tiene_atico:
        huella_at = _huella_atico(huella, params.urbanismo.retranqueo_atico)
        interior_at = huella_at.buffer(-espesor) if not huella_at.is_empty else Polygon()
        n_at = (plantas[-1].n + 1) if plantas else 0
        atico = Planta(
            n=n_at,
            footprint=huella_at,
            interior=interior_at if not interior_at.is_empty else huella_at,
            patios=[],
            area_construida_m2=huella_at.area,
            area_util_m2=interior_at.area if not interior_at.is_empty else 0.0,
            computa_edif=params.urbanismo.atico_computa_edificabilidad,
            tipo="atico",
        )
        plantas.append(atico)
        if atico.computa_edif:
            edif_acumulada += huella_at.area

    edif_max = parcela.area * params.urbanismo.edificabilidad
    return Envolvente(
        parcela=parcela,
        plantas=plantas,
        edificabilidad_consumida=edif_acumulada,
        edificabilidad_max=edif_max,
    )
