"""Disposición geométrica del edificio con el motor CP-SAT (§2.4–2.5).

Motor CANDIDATO alternativo al reparto numérico, cableado detrás del flag
`algoritmo="cpsat"` de `CalcularLayout`. Orquesta `reparto_cpsat.repartir_zona_cpsat`
sobre las zonas edificables de cada planta: reutiliza la detección de zonas de
`zonas.py` (`detectar_zonas_edificables` + `repartir_por_area`) como preprocesado
y lanza UNA llamada al solver por zona, igual que hace el reparto numérico.

Dominio puro (shapely + ortools vía `reparto_cpsat`), aislado de FastAPI/SQLAlchemy
como el resto de `geometria/`. La serialización a JSON vive en `serializacion.py`
(`edificio_cpsat_a_dict`), que NO importa este módulo para no arrastrar ortools a
todo el que importe el serializador.

Cardinalidad exacta: la lista `unidades` de cada `PlantaDispuesta` contiene TODAS
las unidades objetivo (ubicadas + no ubicadas). Las que no caben se conservan con
`ubicada=False` y un polígono placeholder sintetizado en el área sobrante de su
zona, para que el frontend las dibuje en rojo donde se intentó colocarlas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

from .envolvente import _normalizar
from .reparto_cpsat import UnidadObjetivo, UnidadUbicada, repartir_zona_cpsat
from .zonas import detectar_zonas_edificables, repartir_por_area


@dataclass
class PlantaDispuesta:
    """Disposición de UNA planta: geometría lista para serializar al canvas."""
    n: int
    tipo: str
    nombre: str
    footprint: Polygon
    patios: list              # list[Patio] de la envolvente
    unidades: list            # list[UnidadUbicada] — TODAS (ubicadas + no ubicadas c/placeholder)
    circulacion: Any          # Polygon | MultiPolygon (unión de circulaciones por zona)
    zonas: list               # list[Polygon]
    zonas_reparto: list = field(default_factory=list)   # nº de unidades por zona (paralelo a zonas)
    n_dorms: list = field(default_factory=list)          # n_dormitorios paralelo a `unidades`
    adaptadas: set = field(default_factory=set)          # ids de unidades marcadas es_adaptada


def _piezas(g) -> list:
    """Piezas poligonales no vacías de una geometría (Polygon → [g]; Multi → sus geoms)."""
    if g is None or getattr(g, "is_empty", True):
        return []
    if isinstance(g, Polygon):
        return [g]
    if hasattr(g, "geoms"):
        return [p for p in g.geoms if getattr(p, "geom_type", "") == "Polygon" and not p.is_empty]
    return []


def _nombre_planta(tipo: str, idx_visual: int) -> str:
    """Etiqueta de planta coherente con `_plantas_envolvente_a_dict` (PB/P1/…, S1, Ático)."""
    if tipo == "sotano":
        return "S1"
    if tipo == "atico":
        return "Ático"
    return "PB" if idx_visual == 0 else f"P{idx_visual}"


def _placeholder(area_objetivo: float, zona: Polygon, sobrante, k: int) -> Polygon:
    """Polígono para una unidad NO ubicada: cuadrado de área `area_objetivo` en el
    área sobrante (circulación) de la zona, para señalar «se intentó aquí y no cupo».

    Se ancla al `representative_point()` de la pieza `k`-ésima del sobrante (o de la
    zona si no hay sobrante) y se recorta a esa base. Nunca vacío: si el recorte se
    anula, cae al cuadrado sin recortar (siempre hay algo rojo que dibujar).
    """
    lado = max(0.5, float(area_objetivo) ** 0.5)
    base = sobrante if (sobrante is not None and not getattr(sobrante, "is_empty", True)) else zona
    piezas = _piezas(base) or _piezas(zona)
    ref = piezas[k % len(piezas)] if piezas else zona
    pt = ref.representative_point()
    ph = box(pt.x - lado / 2.0, pt.y - lado / 2.0, pt.x + lado / 2.0, pt.y + lado / 2.0)
    rec = _normalizar(ph.intersection(base))
    if rec.is_empty:
        rec = _normalizar(ph.intersection(zona))
    return rec if not rec.is_empty else ph


def disponer_edificio_cpsat(
    envolvente,
    cap,
    *,
    ancho_cuello_min: float = 4.0,
    tam_celda: float = 1.6,
    tol_area: float = 0.10,
    timeout_s: float = 10.0,
    seed: int = 0,
) -> list[PlantaDispuesta]:
    """Dispone geométricamente el edificio: una `PlantaDispuesta` por planta.

    Por planta: región = huella − patios → zonas (`detectar_zonas_edificables`) →
    reparto de las unidades de la planta entre zonas por área (`repartir_por_area`)
    → una llamada a `repartir_zona_cpsat` por zona. Las unidades salen de
    `cap.unidades_por_planta[i]` (n_dorms, útil m²) y `cap.tipologias_unidad_por_planta[i]`.

    Núcleo: NO se pre-coloca en esta fase (`cap.nucleo_por_planta` da m² pero no
    geometría); la circulación de CP-SAT hace de pasillos.
    """
    plantas_out: list[PlantaDispuesta] = []
    uni_pp = cap.unidades_por_planta or []
    tip_pp = cap.tipologias_unidad_por_planta or []
    adaptadas_restantes = int(getattr(cap, "n_unidades_adaptadas", 0) or 0)

    idx_visual = 0
    for i, pl in enumerate(envolvente.plantas):
        tipo = getattr(pl, "tipo", "regular")
        nombre = _nombre_planta(tipo, idx_visual)
        if tipo not in ("sotano", "atico"):
            idx_visual += 1

        detalle = uni_pp[i] if i < len(uni_pp) else []
        slugs = tip_pp[i] if i < len(tip_pp) else []
        objetivos: list[UnidadObjetivo] = []
        dorms: list[int] = []
        for k, (n_d, util) in enumerate(detalle):
            slug = slugs[k] if k < len(slugs) else ""
            objetivos.append(UnidadObjetivo(id=f"P{i}-U{k + 1}", area_objetivo=float(util), tipo=slug))
            dorms.append(int(n_d))

        patios_pl = [p for p in pl.patios if getattr(p, "geometry", None) is not None]
        patios_geom = [p.geometry for p in patios_pl]
        region = pl.footprint.difference(unary_union(patios_geom)) if patios_geom else pl.footprint
        zonas = detectar_zonas_edificables(region, ancho_cuello_min=ancho_cuello_min)

        unidades_planta: list[UnidadUbicada] = []
        dorms_planta: list[int] = []
        circ_piezas: list = []
        reparto: list[int] = []

        if not zonas or not objetivos:
            # Sin zona edificable o sin unidades: las que haya, no ubicadas (placeholder en la huella).
            for k, obj in enumerate(objetivos):
                ph = _placeholder(obj.area_objetivo, pl.footprint, None, k)
                unidades_planta.append(UnidadUbicada(obj.id, obj.tipo, obj.area_objetivo, ph, 0.0, False))
                dorms_planta.append(dorms[k])
        else:
            reparto = repartir_por_area(len(objetivos), [z.area for z in zonas])
            cursor = 0
            for zi, z in enumerate(zonas):
                obj_zona = objetivos[cursor:cursor + reparto[zi]]
                dorms_zona = dorms[cursor:cursor + reparto[zi]]
                cursor += reparto[zi]
                if not obj_zona:
                    circ_piezas.extend(_piezas(z))
                    continue
                res = repartir_zona_cpsat(
                    z, obj_zona, patios=tuple(patios_geom), fachada=None,
                    tam_celda=tam_celda, tol_area=tol_area, timeout_s=timeout_s, seed=seed,
                )
                circ_piezas.extend(_piezas(res.circulacion))
                for u, nd in zip(res.unidades, dorms_zona):
                    if not u.ubicada or u.poligono is None:
                        ph = _placeholder(u.area_objetivo, z, res.circulacion, len(unidades_planta))
                        u = UnidadUbicada(u.id, u.tipo, u.area_objetivo, ph, 0.0, False)
                    unidades_planta.append(u)
                    dorms_planta.append(nd)

        circulacion = unary_union(circ_piezas) if circ_piezas else Polygon()
        adaptadas: set = set()
        for u in unidades_planta:
            if adaptadas_restantes > 0 and u.ubicada:
                adaptadas.add(u.id)
                adaptadas_restantes -= 1

        plantas_out.append(PlantaDispuesta(
            n=pl.n, tipo=tipo, nombre=nombre, footprint=pl.footprint, patios=patios_pl,
            unidades=unidades_planta, circulacion=circulacion, zonas=zonas,
            zonas_reparto=reparto, n_dorms=dorms_planta, adaptadas=adaptadas,
        ))
    return plantas_out
