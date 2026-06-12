"""Geometría del lienzo de dibujo manual sobre la parcela (§2.4 — capa manual).

El usuario pinta superficies (rectángulos/polígonos) y muros (segmentos con
grosor) sobre la parcela. Cada pieza solo cuenta los m² que ocupa DENTRO de la
parcela: el área es la intersección Shapely de la figura con el polígono de la
parcela. Lo que se sale no cuenta (y en el frontend tampoco se ve, vía clip).

Funciones puras, sin dependencias de FastAPI ni de la persistencia. Reutiliza
`ring()` de la serialización del módulo. Todas las coordenadas están en metros
UTM30N (mismo CRS que `ParcelaMetrica.poligono_utm`).
"""
from __future__ import annotations

import math
from typing import Any

from shapely.geometry import LineString, Polygon

from .serializacion import ring


def _es_xy_finito(v: Any) -> bool:
    """True si `v` es un par (x, y) con ambos componentes finitos."""
    try:
        return len(v) >= 2 and math.isfinite(float(v[0])) and math.isfinite(float(v[1]))
    except (TypeError, ValueError):
        return False


def _saneo_poligono(poly: Polygon) -> Polygon:
    """Arregla auto-intersecciones / invalidez con buffer(0) (patrón del motor)."""
    if poly.is_empty or not poly.is_valid:
        poly = poly.buffer(0)
    return poly


def _rings_de(geom: Any) -> list[list[list[float]]]:
    """Lista de anillos de un resultado de intersección.

    Soporta Polygon, MultiPolygon y GeometryCollection (parcela cóncava parte la
    figura en varias piezas). Descarta piezas no poligonales (líneas/puntos de
    intersecciones tangentes, área 0) y anillos degenerados.
    """
    if geom is None or geom.is_empty:
        return []
    geoms = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
    rings: list[list[list[float]]] = []
    for g in geoms:
        if getattr(g, "geom_type", "") != "Polygon" or g.is_empty:
            continue
        r = ring(g)
        if len(r) >= 4:  # un anillo cerrado válido tiene >= 4 vértices
            rings.append(r)
    return rings


def _normalizar_color(c: Any) -> str:
    """Normaliza un color hex: minúsculas, con `#`; cae a negro si vacío."""
    s = str(c or "").strip().lower()
    if not s:
        return "#000000"
    if not s.startswith("#"):
        s = "#" + s
    return s


def recortar_poligono(
    vertices: Any, parcela_poly: Polygon
) -> tuple[list[list[list[float]]], float]:
    """Recorta una superficie (rect/polígono) a la parcela.

    Devuelve `(rings_recortados, area_m2)`. Si la figura tiene <3 vértices
    finitos o no solapa con la parcela, devuelve `([], 0.0)`.
    """
    pts = [(float(v[0]), float(v[1])) for v in (vertices or []) if _es_xy_finito(v)]
    if len(pts) < 3:
        return [], 0.0
    figura = _saneo_poligono(Polygon(pts))
    if figura.is_empty:
        return [], 0.0
    recorte = figura.intersection(parcela_poly)
    return _rings_de(recorte), round(recorte.area, 2)


def recortar_muro(
    p1: Any, p2: Any, grosor: Any, parcela_poly: Polygon
) -> tuple[list[list[list[float]]], float]:
    """Recorta un muro (segmento p1→p2 con grosor en metros) a la parcela.

    El muro se materializa como la banda del segmento expandida `grosor/2` a cada
    lado, con extremos planos (cap_style=2) para no sobresalir de p1/p2. Devuelve
    `(rings_recortados, area_m2)`. Casos inválidos (puntos no finitos, grosor<=0,
    longitud nula) → `([], 0.0)`.
    """
    if not (_es_xy_finito(p1) and _es_xy_finito(p2)):
        return [], 0.0
    try:
        g = float(grosor)
    except (TypeError, ValueError):
        return [], 0.0
    if not math.isfinite(g) or g <= 0:
        return [], 0.0
    a = (float(p1[0]), float(p1[1]))
    b = (float(p2[0]), float(p2[1]))
    if math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-6:
        return [], 0.0
    banda = _saneo_poligono(
        LineString([a, b]).buffer(g / 2.0, cap_style=2, join_style=2)
    )
    if banda.is_empty:
        return [], 0.0
    recorte = banda.intersection(parcela_poly)
    return _rings_de(recorte), round(recorte.area, 2)


def _agrupar_por_color(piezas: Any) -> list[dict[str, Any]]:
    """Agrupa piezas (con `color`, `area_m2`, `nombre`) por color hex.

    Solo entran piezas con área > 0. Devuelve grupos ordenados desc por m² con
    `{color, m2_total, n, nombres}` (nombres únicos en orden de aparición).
    """
    acc: dict[str, dict[str, Any]] = {}
    for p in piezas or []:
        try:
            area = float(p.get("area_m2") or 0.0)
        except (TypeError, ValueError):
            area = 0.0
        if area <= 0:
            continue
        color = _normalizar_color(p.get("color"))
        grupo = acc.setdefault(
            color, {"color": color, "m2_total": 0.0, "n": 0, "nombres": []}
        )
        grupo["m2_total"] += area
        grupo["n"] += 1
        nombre = str(p.get("nombre") or "").strip()
        if nombre and nombre not in grupo["nombres"]:
            grupo["nombres"].append(nombre)
    grupos = list(acc.values())
    for grupo in grupos:
        grupo["m2_total"] = round(grupo["m2_total"], 2)
    grupos.sort(key=lambda x: x["m2_total"], reverse=True)
    return grupos


def resumen_por_color(
    figuras_recortadas: Any, muros_recortados: Any
) -> dict[str, Any]:
    """Resumen agregado bajo el lienzo: superficies y muros por color + totales.

    Las superficies y los muros se agrupan por separado para que la UI muestre el
    total de m² de muro sumado aparte (requisito del usuario).
    """
    superficies = _agrupar_por_color(figuras_recortadas)
    muros = _agrupar_por_color(muros_recortados)
    total_sup = round(sum(g["m2_total"] for g in superficies), 2)
    total_mur = round(sum(g["m2_total"] for g in muros), 2)
    return {
        "superficies_por_color": superficies,
        "muros_por_color": muros,
        "total_superficies_m2": total_sup,
        "total_muros_m2": total_mur,
        "total_m2": round(total_sup + total_mur, 2),
    }
