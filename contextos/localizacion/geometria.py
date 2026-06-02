"""Geometría pura para localización (§2.1).

Tres operaciones que solo dependen de `shapely` y `pyproj`:
- Simplificación Douglas-Peucker en UTM (reproyecta para tolerancia en metros).
- Extracción de lados con longitud y azimut.
- Clasificación fachada / medianera por sondeo perpendicular a las parcelas vecinas.
"""
from __future__ import annotations

import math

from pyproj import CRS, Transformer
from shapely.geometry import Point, Polygon
from shapely.ops import transform as shp_transform
from shapely.ops import unary_union

from .dominio import Lado, ORIENTACIONES, TipoLado


def azimut_a_cardinal(azimut_grados: float) -> str:
    """Convierte azimut [0, 360) a uno de los 8 puntos cardinales (sectores 45°)."""
    az = float(azimut_grados) % 360.0
    idx = int(round(az / 45.0)) % 8
    return ORIENTACIONES[idx]

# UTM ETRS89 husos peninsulares + Baleares (zona 31) + Galicia (zona 29) +
# Canarias (REGCAN95 / UTM 28). Replicado de Modulos/frontend/backend/localizar.py.
def _epsg_utm_para_lon(lon: float, lat: float) -> int:
    if lat < 30:                  # Canarias
        return 4083               # REGCAN95 / UTM zone 28N
    if lon < -7.5:                # Galicia
        return 25829              # ETRS89 / UTM zone 29N
    if lon < 0.0:                 # Andalucía / Centro / Norte peninsular
        return 25830              # ETRS89 / UTM zone 30N
    return 25831                  # ETRS89 / UTM zone 31N — Cataluña, Baleares


def _crear_transformers(lon_ref: float, lat_ref: float):
    crs_utm = CRS.from_epsg(_epsg_utm_para_lon(lon_ref, lat_ref))
    crs_wgs = CRS.from_epsg(4326)
    a_utm = Transformer.from_crs(crs_wgs, crs_utm, always_xy=True).transform
    a_wgs = Transformer.from_crs(crs_utm, crs_wgs, always_xy=True).transform
    return a_utm, a_wgs


def simplificar_dp_utm(
    contorno_wgs84: list[tuple[float, float]],
    tolerancia_m: float,
) -> list[tuple[float, float]]:
    """Douglas-Peucker en UTM ETRS89 para que la tolerancia sea metros reales.

    Si tolerancia_m <= 0 devuelve el contorno tal cual. Garantiza polígono cerrado.
    """
    if len(contorno_wgs84) < 4:
        return list(contorno_wgs84)
    if tolerancia_m <= 0:
        return list(contorno_wgs84)

    lon_ref, lat_ref = contorno_wgs84[0]
    a_utm, a_wgs = _crear_transformers(lon_ref, lat_ref)
    poly_wgs = Polygon(contorno_wgs84)
    poly_utm = shp_transform(a_utm, poly_wgs)
    simplificado_utm = poly_utm.simplify(tolerancia_m, preserve_topology=True)
    if simplificado_utm.is_empty:
        return list(contorno_wgs84)
    simplificado_wgs = shp_transform(a_wgs, simplificado_utm)
    coords = list(simplificado_wgs.exterior.coords)
    return [(float(x), float(y)) for x, y in coords]


def extraer_lados(contorno_wgs84: list[tuple[float, float]]) -> list[Lado]:
    """Recorre los segmentos del polígono y mide longitud (m), azimut y orientación.

    Orientación = dirección de la normal EXTERIOR del lado (la fachada mira hacia
    ahí). Probamos las dos normales perpendiculares y nos quedamos con la que cae
    fuera del polígono propio — patrón validado en `clasificar_por_sondeo`.
    Todos los lados se inicializan como FACHADA; la clasificación es luego
    responsabilidad de `clasificar_por_sondeo`.
    """
    if len(contorno_wgs84) < 4:
        return []

    lon_ref, lat_ref = contorno_wgs84[0]
    a_utm, _ = _crear_transformers(lon_ref, lat_ref)

    try:
        propia_utm = shp_transform(a_utm, Polygon(contorno_wgs84))
    except Exception:
        propia_utm = None

    lados: list[Lado] = []
    # El último punto suele cerrar el polígono repitiendo el primero — no contar dos veces.
    pares = list(zip(contorno_wgs84[:-1], contorno_wgs84[1:]))
    for indice, (p1, p2) in enumerate(pares):
        x1, y1 = a_utm(p1[0], p1[1])
        x2, y2 = a_utm(p2[0], p2[1])
        dx, dy = x2 - x1, y2 - y1
        longitud = math.hypot(dx, dy)
        if longitud < 0.1:
            continue
        # Azimut del lado (dirección del vector p1→p2). 0° = Norte, 90° = Este.
        azimut = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
        # Normal perpendicular: rotamos 90° el director. Probamos qué signo
        # apunta hacia el exterior del polígono propio.
        nxv = dy / longitud
        nyv = -dx / longitud
        if propia_utm is not None and not propia_utm.is_empty:
            mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            sondeo_dist = max(0.5, longitud * 0.05)
            if Point(mx + nxv * sondeo_dist, my + nyv * sondeo_dist).within(propia_utm):
                nxv, nyv = -nxv, -nyv
        # Azimut de la normal exterior. En UTM, +X = Este, +Y = Norte → atan2(nxv, nyv).
        normal_az = (math.degrees(math.atan2(nxv, nyv)) + 360.0) % 360.0
        lados.append(
            Lado(
                indice=len(lados),
                p1=(float(p1[0]), float(p1[1])),
                p2=(float(p2[0]), float(p2[1])),
                longitud_m=float(longitud),
                azimut_grados=float(azimut),
                tipo=TipoLado.FACHADA,
                orientacion=azimut_a_cardinal(normal_az),
            )
        )
    return lados


def clasificar_por_sondeo(
    lados: list[Lado],
    contorno_propio_wgs84: list[tuple[float, float]],
    contornos_vecinos_wgs84: list[list[tuple[float, float]]],
    dist_probe_m: float = 1.0,
) -> list[Lado]:
    """Sondeo perpendicular al exterior para clasificar cada lado.

    Algoritmo validado en `Modulos/puccetti-app/puccetti/parcelas.py`:
    1. Calcula la normal del lado y un punto sondeo a `dist_probe_m`.
    2. Si ese sondeo cae DENTRO del polígono propio, invierte el signo
       (asegurando un punto exterior, sin necesidad de orientación CCW/CW).
    3. Si el punto exterior cae dentro de la unión de parcelas vecinas →
       MEDIANERA. En otro caso → FACHADA.
    """
    if not lados or not contornos_vecinos_wgs84 or len(contorno_propio_wgs84) < 3:
        return lados

    lon_ref, lat_ref = lados[0].p1
    a_utm, _ = _crear_transformers(lon_ref, lat_ref)

    try:
        propia_utm = shp_transform(a_utm, Polygon(contorno_propio_wgs84))
    except Exception:
        return lados
    if not propia_utm.is_valid or propia_utm.is_empty:
        return lados

    polys_vecinos: list[Polygon] = []
    for contorno in contornos_vecinos_wgs84:
        if len(contorno) < 3:
            continue
        try:
            poly_utm = shp_transform(a_utm, Polygon(contorno))
        except Exception:
            continue
        if poly_utm.is_valid and not poly_utm.is_empty:
            polys_vecinos.append(poly_utm)
    if not polys_vecinos:
        return lados

    union_vecinas = unary_union(polys_vecinos)

    resultado: list[Lado] = []
    for lado in lados:
        x1, y1 = a_utm(lado.p1[0], lado.p1[1])
        x2, y2 = a_utm(lado.p2[0], lado.p2[1])
        dx, dy = x2 - x1, y2 - y1
        norma = math.hypot(dx, dy)
        if norma < 1e-6:
            resultado.append(lado)
            continue
        # Rotación 90° (sentido antihorario en plano UTM); si cae dentro de la
        # propia parcela invertimos para asegurar que el sondeo es exterior.
        nxv = dy / norma
        nyv = -dx / norma
        mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        probe = Point(mx + nxv * dist_probe_m, my + nyv * dist_probe_m)
        if probe.within(propia_utm):
            probe = Point(mx - nxv * dist_probe_m, my - nyv * dist_probe_m)
        nuevo_tipo = (
            TipoLado.MEDIANERA if probe.within(union_vecinas) else TipoLado.FACHADA
        )
        resultado.append(
            Lado(
                indice=lado.indice,
                p1=lado.p1,
                p2=lado.p2,
                longitud_m=lado.longitud_m,
                azimut_grados=lado.azimut_grados,
                tipo=nuevo_tipo,
                orientacion=lado.orientacion,
            )
        )
    return resultado


def area_m2_utm(contorno_wgs84: list[tuple[float, float]]) -> float:
    """Área del polígono reproyectado a UTM (m²). 0 si el polígono es inválido."""
    if len(contorno_wgs84) < 4:
        return 0.0
    lon_ref, lat_ref = contorno_wgs84[0]
    a_utm, _ = _crear_transformers(lon_ref, lat_ref)
    try:
        poly_utm = shp_transform(a_utm, Polygon(contorno_wgs84))
    except Exception:
        return 0.0
    if not poly_utm.is_valid or poly_utm.is_empty:
        return 0.0
    return float(poly_utm.area)


def bbox_wgs84_con_margen(
    contorno_wgs84: list[tuple[float, float]],
    margen_metros: float = 30.0,
) -> tuple[float, float, float, float]:
    """Bbox de la parcela ampliado para capturar vecinos contiguos."""
    if not contorno_wgs84:
        return (0.0, 0.0, 0.0, 0.0)
    lons = [p[0] for p in contorno_wgs84]
    lats = [p[1] for p in contorno_wgs84]
    lat_ref = sum(lats) / len(lats)
    # Aprox: 1 m latitud ≈ 1/111320 grados; longitud divide por cos(lat).
    dlat = margen_metros / 111_320.0
    dlon = margen_metros / (111_320.0 * max(math.cos(math.radians(lat_ref)), 1e-4))
    return (min(lons) - dlon, min(lats) - dlat, max(lons) + dlon, max(lats) + dlat)
