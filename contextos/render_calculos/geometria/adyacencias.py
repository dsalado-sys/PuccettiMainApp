"""Adyacencias físicas + validación de reglas A2.2.

Copia desde `Modulos/puccetti-app/puccetti/adyacencias.py`.
"""
from __future__ import annotations
from dataclasses import dataclass

import networkx as nx
from shapely.geometry import Polygon


@dataclass
class IncidenciaAdyacencia:
    estancia_a: str
    estancia_b: str
    motivo: str


def _cat_de(nombre: str) -> str:
    if nombre.startswith('salon') or nombre == 'cocina' or nombre == 'comedor':
        return 'publica'
    if nombre.startswith('dormitorio') or nombre == 'vestidor':
        return 'privada'
    if nombre.startswith('bano') or nombre == 'aseo':
        return 'servicio'
    if nombre in ('pasillo', 'vestibulo', 'distribuidor'):
        return 'circulacion'
    return 'otra'


def grafo_adyacencias_fisicas(
    estancias: dict[str, Polygon],
    buffer_muro: float = 0.30,
    min_overlap_m: float = 0.30,
) -> nx.Graph:
    g = nx.Graph()
    items = list(estancias.items())
    for nombre, geom in items:
        g.add_node(nombre, categoria=_cat_de(nombre), area_m2=geom.area)
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a_name, a = items[i]
            b_name, b = items[j]
            if a.is_empty or b.is_empty:
                continue
            inter = a.buffer(buffer_muro).intersection(b.buffer(buffer_muro))
            if inter.is_empty or inter.area < min_overlap_m * buffer_muro:
                continue
            g.add_edge(a_name, b_name, overlap_m2=inter.area)
    return g


def validar_a22(g: nx.Graph) -> list[IncidenciaAdyacencia]:
    incidencias: list[IncidenciaAdyacencia] = []
    for a, b in g.edges():
        ca = g.nodes[a]['categoria']
        cb = g.nodes[b]['categoria']
        if ca == 'publica' and cb == 'publica':
            continue
        if {ca, cb} == {'publica', 'privada'}:
            if 'salon' in a or 'salon' in b or a == 'cocina' or b == 'cocina':
                incidencias.append(IncidenciaAdyacencia(
                    a, b,
                    "A2.2: habitación no puede conectar directamente con salón/cocina; debe acceder desde pasillo"
                ))
        if {ca, cb} == {'publica', 'servicio'}:
            if 'cocina' in (a, b):
                incidencias.append(IncidenciaAdyacencia(
                    a, b, "A2.2: no se accede al baño desde la cocina"
                ))
    return incidencias


def validar_conectividad(g: nx.Graph) -> list[IncidenciaAdyacencia]:
    incidencias: list[IncidenciaAdyacencia] = []
    if not g.nodes:
        return incidencias
    nodos_circ = [n for n, d in g.nodes(data=True) if d['categoria'] == 'circulacion']
    if not nodos_circ:
        return [IncidenciaAdyacencia('-', '-', "A2.1: no hay pasillo/vestíbulo en la planta")]
    alcanzables: set[str] = set()
    for c in nodos_circ:
        alcanzables.update(nx.descendants(g, c))
        alcanzables.add(c)
    for n in g.nodes():
        if n not in alcanzables:
            incidencias.append(IncidenciaAdyacencia(
                n, '-', f"A2.2: {n} no es alcanzable desde pasillo/vestíbulo"
            ))
    return incidencias
