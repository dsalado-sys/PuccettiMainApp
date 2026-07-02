"""Detección de zonas edificables independientes (§2.4).

La huella construida menos los patios puede quedar partida en varias masas
edificables. A veces esas masas siguen topológicamente unidas por un «cuello»
estrecho (un paso demasiado angosto para funcionar como planta continua). Este
módulo detecta cuántas ZONAS independientes hay, las que haya: rompe los cuellos
más estrechos que `ancho_cuello_min` mediante apertura morfológica (erosión +
reconstrucción) y devuelve la partición de la región en zonas que la teselan
sin solapes.

Geometría vectorial pura (shapely), sin dependencias de FastAPI/SQLAlchemy,
como el resto de `geometria/`. Reutiliza `_normalizar` de `envolvente.py`.
"""
from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Polygon
from shapely.ops import unary_union

from .envolvente import _normalizar


@dataclass
class ZonaEdificable:
    geometry: Polygon
    area_m2: float
    indice: int          # 1-based, asignado tras ordenar por área descendente


def _componentes(g) -> list[Polygon]:
    """Piezas poligonales conexas de una geometría.

    A diferencia de `_normalizar` (que conserva SOLO la mayor), devuelve TODAS
    las piezas: aquí cada componente desconectada es una zona candidata.
    Descarta restos no poligonales (líneas/puntos de una GeometryCollection) y
    vacíos, y repara geometrías inválidas con `buffer(0)`.
    """
    if g is None or g.is_empty:
        return []
    if not g.is_valid:
        g = g.buffer(0)
        if g.is_empty:
            return []
    if hasattr(g, "geoms"):
        return [p for p in g.geoms if p.geom_type == "Polygon" and not p.is_empty]
    return [g] if g.geom_type == "Polygon" else []


def _repartir(region: Polygon, nucleos: list[Polygon], r: float) -> list[Polygon]:
    """Reparte `region` entre sus `nucleos` (≥2) teselándola sin solapes.

    Cada punto de la región se asigna a su núcleo más cercano: se dilata cada
    núcleo (procesados por área desc, para estabilidad), se recorta a la región
    y se resta lo ya asignado, de modo que el cuello compartido se parte entre
    ambos lados. Los restos fuera del alcance de todo núcleo (el borde comido
    por la erosión) se anexan a la zona más cercana.
    """
    holgura = max(r, 0.5)
    nucleos = sorted(nucleos, key=lambda n: n.area, reverse=True)
    zonas: list[Polygon] = []
    asignado = Polygon()
    for nucleo in nucleos:
        crecido = nucleo.buffer(r + holgura, join_style=2)
        zona = _normalizar(region.intersection(crecido).difference(asignado))
        if not zona.is_empty:
            zonas.append(zona)
            asignado = unary_union([asignado, zona])
    # Restos no alcanzados por ningún núcleo → a la zona más cercana.
    for pieza in _componentes(region.difference(asignado)):
        if not zonas:
            break
        j = min(range(len(zonas)), key=lambda k: zonas[k].distance(pieza))
        zonas[j] = _normalizar(unary_union([zonas[j], pieza]))
    return [z for z in zonas if not z.is_empty]


def _dividir_por_cuellos(comp: Polygon, ancho_cuello_min: float, area_min_zona: float) -> list[Polygon]:
    """Divide UNA componente conexa por sus cuellos estrechos (< ancho_cuello_min).

    Erosiona `ancho_cuello_min / 2` con inglete (`join_style=2`, como los
    retranqueos del motor: robusto en cóncavos): los cuellos más estrechos que
    el umbral desaparecen y la pieza se parte en varios núcleos. Si tras
    descartar esquirlas queda ≤ 1 núcleo, no hay cuello real y `comp` es una
    sola zona (se devuelve intacta, sin la deformación de la erosión).
    """
    r = ancho_cuello_min / 2.0
    nucleos = [n for n in _componentes(comp.buffer(-r, join_style=2)) if n.area >= area_min_zona]
    if len(nucleos) <= 1:
        return [comp]
    return _repartir(comp, nucleos, r)


def detectar_zonas_edificables(
    region,
    ancho_cuello_min: float = 4.0,
    area_min_zona: float = 10.0,
) -> list[Polygon]:
    """Detecta las zonas edificables independientes de `region` (huella − patios).

    `region` puede ser un `Polygon` (con o sin huecos) o un `MultiPolygon` (si
    los patios ya parten la huella del todo). Dos masas unidas por un cuello más
    estrecho que `ancho_cuello_min` metros cuentan como zonas separadas; las de
    área < `area_min_zona` m² se descartan como esquirlas.

    Devuelve la lista de polígonos de las zonas, ordenada por área descendente
    (vacía si no hay región edificable).
    """
    zonas: list[Polygon] = []
    for comp in _componentes(region):
        zonas.extend(_dividir_por_cuellos(comp, ancho_cuello_min, area_min_zona))
    zonas = [z for z in zonas if not z.is_empty and z.area >= area_min_zona]
    zonas.sort(key=lambda z: z.area, reverse=True)
    return zonas


def repartir_por_area(total: int, areas: list[float]) -> list[int]:
    """Reparte `total` unidades entre las zonas proporcionalmente a su área.

    Usa el método del resto mayor (Hamilton) para que la suma sea EXACTAMENTE
    `total`: se asigna la parte entera de `total·area_i/Σareas` a cada zona y las
    unidades sobrantes van a las zonas con mayor parte fraccionaria (empate →
    mayor área, luego menor índice). Así una zona grande recibe más y dos zonas
    iguales se reparten a mitades; una zona diminuta puede quedar en 0.

    Devuelve una lista de enteros alineada con `areas`; todo ceros si
    `total <= 0` o `Σareas <= 0`, y `[]` si no hay áreas.
    """
    n = len(areas)
    if n == 0:
        return []
    suma = sum(areas)
    if total <= 0 or suma <= 0:
        return [0] * n
    brutos = [total * a / suma for a in areas]
    reparto = [int(b) for b in brutos]          # parte entera (floor, áreas ≥ 0)
    sobrantes = total - sum(reparto)
    # Orden de prioridad para las sobrantes: mayor resto, luego mayor área, luego índice.
    orden = sorted(range(n), key=lambda i: (brutos[i] - reparto[i], areas[i], -i), reverse=True)
    for k in range(sobrantes):
        reparto[orden[k]] += 1
    return reparto
