"""Envolvente edificatoria (§2.4): huella + plantas + patios interiores.

Iteración 4 (2026-06-04):
- Retranqueos direccionales: fachada se aplica solo a lados tipo "fachada",
  linderos solo a lados tipo "medianera". Excluyentes (cada lado lleva uno).
- Ocupación máxima se aplica a la huella final (no solo al cálculo): si la
  huella tras retranqueos excede `ocupacion × parcela`, se erosiona
  uniformemente hasta encajar.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from shapely.geometry import LineString, Polygon, box, Point
from shapely.ops import unary_union

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


def _restar_franja_lado(huella: Polygon, p1, p2, retranqueo: float) -> Polygon:
    """Resta del polígono una franja de grosor `retranqueo` hacia el interior
    del polígono, partiendo del segmento p1→p2.

    Estrategia: buffer del segmento con ambos lados (`single_sided=False`), de
    grosor `retranqueo`. Eso da un rectángulo angosto centrado en el segmento;
    al restarlo del polígono, solo afecta a la parte interior (el exterior
    queda fuera del polígono igualmente).
    """
    if retranqueo <= 0:
        return huella
    seg = LineString([p1, p2])
    franja = seg.buffer(retranqueo, cap_style=2)  # cap_style=2 = flat (sin redondeo)
    nueva = huella.difference(franja).buffer(0)
    if nueva.is_empty:
        return huella
    if hasattr(nueva, "geoms"):
        # Si la diferencia partió el polígono, conservamos la pieza más grande.
        nueva = max(nueva.geoms, key=lambda g: g.area)
    return nueva


def _aplicar_ocupacion_maxima(huella: Polygon, ocup_area: float) -> Polygon:
    """Erosiona uniformemente la huella hasta que su área ≤ ocup_area.

    Bisección numérica: prueba buffer(-delta) con delta creciente hasta encajar.
    Para parcelas pequeñas suele converger en <8 iteraciones.
    """
    if huella.area <= ocup_area + 1e-3:
        return huella
    lo, hi = 0.0, max(huella.area ** 0.5, 1.0)
    mejor = huella
    for _ in range(20):
        mid = (lo + hi) / 2.0
        candidato = huella.buffer(-mid).buffer(0)
        if candidato.is_empty:
            hi = mid
            continue
        if hasattr(candidato, "geoms"):
            candidato = max(candidato.geoms, key=lambda g: g.area)
        if candidato.area <= ocup_area + 1e-3:
            mejor = candidato
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-3:
            break
    return mejor


def aplicar_retranqueos(parcela: Polygon, params: Parametros, lados=None) -> Polygon:
    """Aplica retranqueos direccionales:
    - Lados tipo "fachada" reciben `retranqueo_fachada`.
    - Lados tipo "medianera" reciben `retranqueo_linderos`.

    Si `lados` es None, no hay clasificación: se aplica `retranqueo_linderos`
    como buffer uniforme negativo (comportamiento conservador).
    """
    u = params.urbanismo
    r_fach = float(u.retranqueo_fachada)
    r_lind = float(u.retranqueo_linderos)

    if r_fach <= 0 and r_lind <= 0:
        return parcela

    if not lados:
        # Sin lados clasificados, aplicamos el mayor de los dos como uniforme.
        retranqueo = max(r_fach, r_lind)
        return parcela.buffer(-retranqueo).buffer(0) if retranqueo > 0 else parcela

    huella = parcela
    for lado in lados:
        tipo = getattr(lado, "tipo", "fachada")
        if tipo == "fachada" and r_fach > 0:
            huella = _restar_franja_lado(huella, lado.p1, lado.p2, r_fach)
        elif tipo == "medianera" and r_lind > 0:
            huella = _restar_franja_lado(huella, lado.p1, lado.p2, r_lind)
    return huella


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
    """Huella reducida del ático tras aplicar el retranqueo perimetral."""
    if retranqueo_atico <= 0:
        return huella
    reducida = huella.buffer(-retranqueo_atico).buffer(0)
    if reducida.is_empty:
        return Polygon()
    if hasattr(reducida, "geoms"):
        reducida = max(reducida.geoms, key=lambda g: g.area)
    return reducida


def construir_envolvente(parcela: Polygon, params: Parametros, lados=None) -> Envolvente:
    """Pipeline §2.4 completo: retranqueos direccionales → ocupación → N plantas → patios.

    Iteración 4: acepta `lados: list[LadoParcela] | None`. Si se pasan, los
    retranqueos se aplican direccionalmente según el tipo de cada lado.
    """
    huella = aplicar_retranqueos(parcela, params, lados)
    if huella.is_empty:
        raise ValueError("Tras retranqueos no queda espacio edificable.")

    # Aplicar ocupación máxima: si la huella excede `ocupacion × parcela`, recortar.
    ocup_area = params.urbanismo.ocupacion_maxima * parcela.area
    if ocup_area > 0:
        huella = _aplicar_ocupacion_maxima(huella, ocup_area)
        if huella.is_empty:
            raise ValueError("Tras aplicar ocupación máxima no queda huella construible.")

    espesor = params.diseno.espesor_muro_fachada
    interior_base = huella.buffer(-espesor)
    if interior_base.is_empty:
        # Para parcelas muy pequeñas, fallback: interior = huella sin offset.
        interior_base = huella

    plantas: list[Planta] = []
    edif_acumulada = 0.0

    # ── Sótano ───────────────────────────────────────────────────────────────
    if params.urbanismo.tiene_sotano:
        sotano = Planta(
            n=-1,
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
            n=n,
            footprint=f,
            interior=i,
            patios=patios,
            area_construida_m2=f.area,
            area_util_m2=i.area,
            computa_edif=True,
            tipo="regular",
        ))
        edif_acumulada += f.area

    # ── Ático ────────────────────────────────────────────────────────────────
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

    edif_max = parcela.area * params.urbanismo.coeficiente_edificabilidad
    return Envolvente(
        parcela=parcela,
        plantas=plantas,
        edificabilidad_consumida=edif_acumulada,
        edificabilidad_max=edif_max,
    )
