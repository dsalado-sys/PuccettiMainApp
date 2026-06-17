"""Distribución interior por vivienda (Anexo II A2.2 + superficies Anexo I.5).

Copia desde `Modulos/puccetti-app/puccetti/interiores.py`. Sin cambios de
comportamiento; solo imports relativos.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field

from shapely.geometry import Polygon, MultiLineString, LineString, box
from shapely.ops import unary_union
from shapely.affinity import rotate, translate

from .config import Parametros
from .parcelas import LadoParcela
from .programa import programa_vivienda
from .macro_layout import PlantaPlurifamiliar, Unidad, _poly_safe


@dataclass
class EstanciaInterior:
    vivienda_id: str
    nombre: str
    categoria: str
    geometry: Polygon
    area_m2: float
    a_fachada: bool


@dataclass
class ViviendaInterior:
    unidad_id: str
    estancias: list[EstanciaInterior] = field(default_factory=list)
    muros: Polygon = field(default_factory=Polygon)


def _segmentos_fachada(lados: list[LadoParcela]) -> MultiLineString:
    segs = [LineString([l.p1, l.p2]) for l in lados if l.tipo == "fachada"]
    return MultiLineString(segs) if segs else MultiLineString([])


def _direccion_luz(u_geom: Polygon, fach: MultiLineString,
                   patios: list[Polygon]) -> float:
    cen = u_geom.centroid
    for fuente in (fach, unary_union(patios).boundary if patios else None):
        if fuente is None or fuente.is_empty:
            continue
        cerca = u_geom.boundary.intersection(fuente.buffer(0.45))
        if not cerca.is_empty:
            p = cerca.centroid
            return math.degrees(math.atan2(p.y - cen.y, p.x - cen.x))
    return 90.0


def distribuir_unidad(
    u: Unidad, fach: MultiLineString, patios: list[Polygon], params: Parametros,
) -> ViviendaInterior:
    geom = u.geometry
    if geom.is_empty or geom.area < 6.0:
        return ViviendaInterior(u.id)

    cen = geom.centroid
    ang = _direccion_luz(geom, fach, patios)
    theta = 90.0 - ang

    def al(g):
        return rotate(translate(g, xoff=-cen.x, yoff=-cen.y), theta, origin=(0, 0))

    def mu(g):
        return translate(rotate(g, -theta, origin=(0, 0)), xoff=cen.x, yoff=cen.y)

    ua = _poly_safe(al(geom))
    mnx, mny, mxx, mxy = ua.bounds
    W, H = mxx - mnx, mxy - mny

    prog = programa_vivienda(
        n_dorms=params.programa.n_dormitorios,
        util_disponible=geom.area * 0.92,
        salon_cocina_open=params.programa.salon_cocina_open,
    )
    principal = [e for e in prog if e.nombre.startswith(('salon', 'dormitorio', 'espacio_principal'))]
    servicio = [e for e in prog if e.nombre.startswith(('cocina', 'bano', 'aseo'))]

    pas_w = max(params.diseno.ancho_min_pasillo_vivienda, 1.00)
    items_world: list[tuple] = []

    def _rellenar(y0: float, y1: float, items: list[tuple], a_fachada: bool):
        banda = _poly_safe(box(mnx, y0, mxx, y1).intersection(ua))
        if banda.is_empty or banda.area < 1.0:
            return
        barea = banda.area
        total = sum(a for _, _, a in items) or 1.0
        x_prev = mnx
        for i, (nombre, cat, a) in enumerate(items):
            if i == len(items) - 1:
                g = _poly_safe(box(x_prev, y0, mxx, y1).intersection(banda))
            else:
                objetivo = barea * a / total
                lo, hi = x_prev, mxx
                for _ in range(24):
                    mid = (lo + hi) / 2
                    if box(x_prev, y0, mid, y1).intersection(banda).area < objetivo:
                        lo = mid
                    else:
                        hi = mid
                x_cut = (lo + hi) / 2
                g = _poly_safe(box(x_prev, y0, x_cut, y1).intersection(banda))
                x_prev = x_cut
            if not g.is_empty:
                items_world.append((nombre, cat, g, a_fachada))

    VEST = 3.5
    cabe_bandas = W > 2.0 and H > (2.6 + pas_w + 2.0) and principal and servicio
    if cabe_bandas:
        a_princ = sum(e.area_target_m2 for e in principal)
        a_serv = sum(e.area_target_m2 for e in servicio) + VEST
        Hr = H - pas_w
        d_top = min(max(Hr * a_princ / (a_princ + a_serv), 2.6), Hr - 2.0)
        y_top0 = mxy - d_top
        y_pas0 = y_top0 - pas_w

        _rellenar(y_top0, mxy, [(e.nombre, e.categoria, e.area_target_m2)
                                for e in principal], a_fachada=True)
        pas = _poly_safe(box(mnx, y_pas0, mxx, y_top0).intersection(ua))
        if not pas.is_empty:
            items_world.append(('pasillo', 'circulacion', pas, False))
        serv = [('vestibulo', 'circulacion', VEST)]
        serv += [(e.nombre, e.categoria, e.area_target_m2) for e in servicio]
        _rellenar(mny, y_pas0, serv, a_fachada=False)
    else:
        todos = [('vestibulo', 'circulacion', VEST)]
        todos += [(e.nombre, e.categoria, e.area_target_m2) for e in prog]
        _rellenar(mny, mxy, todos, a_fachada=True)

    esp = params.diseno.espesor_tabiqueria
    geoms = [g for _, _, g, _ in items_world if not g.is_empty]
    if len(geoms) >= 2:
        bordes = unary_union([g.boundary for g in geoms])
        muros_a = _poly_safe(bordes.buffer(esp / 2).intersection(ua))
    else:
        muros_a = Polygon()

    estancias: list[EstanciaInterior] = []
    for nombre, cat, g, a_f in items_world:
        g2 = _poly_safe(g.difference(muros_a)) if not muros_a.is_empty else g
        if g2.is_empty:
            continue
        estancias.append(EstanciaInterior(
            vivienda_id=u.id, nombre=nombre, categoria=cat,
            geometry=mu(g2), area_m2=round(g2.area, 2), a_fachada=a_f))

    return ViviendaInterior(u.id, estancias, mu(muros_a) if not muros_a.is_empty else Polygon())


def distribuir_planta_interiores(
    planta: PlantaPlurifamiliar, lados: list[LadoParcela], params: Parametros,
) -> list[ViviendaInterior]:
    fach = _segmentos_fachada(lados)
    patios = [p.geometry for p in planta.patios]
    return [distribuir_unidad(u, fach, patios, params) for u in planta.unidades]
