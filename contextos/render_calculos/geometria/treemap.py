"""Squarified Treemap + aspect_ratio.

Copia desde `Modulos/puccetti-app/puccetti/treemap.py`. Solo se usa
`aspect_ratio` desde `fitness.py`; el resto se conserva por completitud y para
no romper imports al traer el código original.
"""
from __future__ import annotations
import math
from dataclasses import dataclass

from shapely.geometry import Polygon, box


@dataclass
class TreemapItem:
    nombre: str
    area: float
    payload: dict | None = None


def subdividir_squarified(
    contenedor: Polygon,
    items: list[TreemapItem],
    eje_largo_horizontal: bool = True,
) -> dict[str, Polygon]:
    """Subdivisión por squarified treemap. Requiere `squarify` instalado."""
    try:
        import squarify  # type: ignore
    except ImportError as exc:
        raise ImportError("Falta el paquete `squarify` para subdividir_squarified.") from exc

    if not items:
        return {}
    minx, miny, maxx, maxy = contenedor.bounds
    W, H = maxx - minx, maxy - miny
    bbox_area = W * H
    if bbox_area <= 0:
        return {}

    target_areas = [it.area for it in items]
    total_target = sum(target_areas)
    if total_target <= 0:
        return {}
    factor = bbox_area / total_target
    sizes = [a * factor for a in target_areas]
    sizes = squarify.normalize_sizes(sizes, W, H)
    rects = squarify.squarify(sizes, minx, miny, W, H)

    out: dict[str, Polygon] = {}
    for it, r in zip(items, rects):
        rect = box(r['x'], r['y'], r['x'] + r['dx'], r['y'] + r['dy'])
        clipped = rect.intersection(contenedor)
        if not clipped.is_empty:
            out[it.nombre] = clipped
    return out


def aspect_ratio(geom: Polygon) -> float:
    """Aspect ratio del minimum_rotated_rectangle: lado_largo / lado_corto."""
    if geom.is_empty:
        return float('inf')
    mrr = geom.minimum_rotated_rectangle
    coords = list(mrr.exterior.coords)[:-1]
    edges = [math.dist(coords[i], coords[(i + 1) % 4]) for i in range(4)]
    largos = sorted(edges, reverse=True)
    if largos[2] < 1e-6:
        return float('inf')
    return largos[0] / largos[2]
