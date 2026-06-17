"""Clasificación fachada/medianera + orientación cardinal (§2.1 + §2.4).

Copia desde `Modulos/puccetti-app/puccetti/parcelas.py`. Cambios:
- Se quitan los helpers `cargar_parcelas` / `cargar_contexto` que dependen del
  `data/parcelas_sevilla.gpkg` del repo viejo (cabrá traerlos como fixture de
  tests, no como API pública del módulo).
- `clasificar_lados` acepta opcionalmente la geometría de las parcelas vecinas;
  cuando no hay datos colindantes, todos los lados se asumen fachada (la
  corrección manual del técnico desde §2.1 manda en cualquier caso).
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Literal

from shapely.geometry import Polygon, LineString, Point
from shapely.ops import unary_union


LadoTipo = Literal["fachada", "medianera"]


@dataclass
class LadoParcela:
    p1: tuple[float, float]
    p2: tuple[float, float]
    tipo: LadoTipo
    longitud_m: float
    azimut: float           # grados desde norte del segmento p1→p2 (0..360)
    normal_azimut: float = 0.0   # azimut de la NORMAL EXTERIOR (hacia dónde mira la fachada)


def simplificar(geom: Polygon, tolerancia: float = 0.20) -> Polygon:
    """§2.1 — Douglas-Peucker con tolerancia configurable (default 20 cm)."""
    from shapely.geometry import MultiPolygon
    s = geom.simplify(tolerancia, preserve_topology=True)
    if isinstance(s, MultiPolygon):
        s = max(s.geoms, key=lambda g: g.area)
    return s


def _azimut(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Azimut desde norte (CRS métrico) en grados, lado p1->p2."""
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    return (math.degrees(math.atan2(dx, dy))) % 360


def orientacion_cardinal(az: float) -> str:
    """Azimut → N/NE/E/SE/S/SO/O/NO."""
    sectores = ['N', 'NE', 'E', 'SE', 'S', 'SO', 'O', 'NO']
    idx = int(((az + 22.5) % 360) // 45)
    return sectores[idx]


def azimut_normal_exterior(
    p1: tuple[float, float],
    p2: tuple[float, float],
    parcela: Polygon,
    dist_probe: float = 0.5,
) -> float:
    """Azimut (desde norte, 0..360) de la normal EXTERIOR del lado p1→p2.

    Es la dirección hacia donde mira la fachada (vs `_azimut`, que es la
    dirección del lado). Sondea con `Point.within(parcela)` para decidir el
    lado exterior — robusto incluso en parcelas no convexas.
    """
    mx = (p1[0] + p2[0]) / 2.0
    my = (p1[1] + p2[1]) / 2.0
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    L = math.hypot(dx, dy) or 1.0
    # Candidato inicial: rotación 90° horario del vector p1→p2.
    nxv = dy / L
    nyv = -dx / L
    probe = Point(mx + nxv * dist_probe, my + nyv * dist_probe)
    if probe.within(parcela):
        nxv, nyv = -nxv, -nyv
    return math.degrees(math.atan2(nxv, nyv)) % 360


def clasificar_lados(
    parcela: Polygon,
    parcelas_vecinas: list[Polygon] | None = None,
    dist_probe: float = 1.0,
) -> list[LadoParcela]:
    """Cada lado del polígono → 'fachada' o 'medianera'.

    Heurística: sondeo perpendicular hacia el exterior del punto medio del lado.
    Si cae dentro de una parcela vecina, el lado es medianera; si no, fachada.

    Cuando no hay parcelas vecinas (lista vacía o `None`), se devuelven todos
    los lados como 'fachada'. El técnico puede luego reclasificar manualmente
    desde §2.1 (`CorregirLado`).
    """
    coords = list(parcela.exterior.coords)[:-1]
    lados: list[LadoParcela] = []

    if not parcelas_vecinas:
        union_vecinas = None
    else:
        otras = [g for g in parcelas_vecinas if not g.equals(parcela)]
        union_vecinas = unary_union(otras) if otras else None

    for i, p1 in enumerate(coords):
        p2 = coords[(i + 1) % len(coords)]
        seg = LineString([p1, p2])
        long_m = seg.length
        if long_m < 0.10:
            continue
        mx = (p1[0] + p2[0]) / 2.0
        my = (p1[1] + p2[1]) / 2.0
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        L = math.hypot(dx, dy)
        nxv = dy / L
        nyv = -dx / L
        probe = Point(mx + nxv * dist_probe, my + nyv * dist_probe)
        if probe.within(parcela):
            probe = Point(mx - nxv * dist_probe, my - nyv * dist_probe)

        if union_vecinas is not None and probe.within(union_vecinas):
            tipo: LadoTipo = "medianera"
        else:
            tipo = "fachada"
        lados.append(LadoParcela(
            p1=p1, p2=p2, tipo=tipo,
            longitud_m=long_m, azimut=_azimut(p1, p2),
            normal_azimut=azimut_normal_exterior(p1, p2, parcela),
        ))
    return lados


def resumen_lados(lados: list[LadoParcela]) -> dict:
    fach = [l for l in lados if l.tipo == "fachada"]
    med = [l for l in lados if l.tipo == "medianera"]
    return {
        "n_fachadas": len(fach),
        "n_medianeras": len(med),
        "long_fachada_total": sum(l.longitud_m for l in fach),
        "long_medianera_total": sum(l.longitud_m for l in med),
        "orientaciones_fachada": [orientacion_cardinal(l.normal_azimut) for l in fach],
    }
