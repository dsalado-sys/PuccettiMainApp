"""Grafo de adyacencias REQUERIDAS/PERMITIDAS/PROHIBIDAS — A2.2 + criterios funcionales.

Copia desde `Modulos/puccetti-app/puccetti/grafo_funcional.py`.
"""
from __future__ import annotations
from enum import Enum

import networkx as nx


class TipoArista(Enum):
    REQUERIDA = 'requerida'
    PERMITIDA = 'permitida'
    PROHIBIDA = 'prohibida'


REGLAS_VIVIENDA: list[tuple[str, str, TipoArista]] = [
    ('vestibulo', 'salon', TipoArista.REQUERIDA),
    ('vestibulo', 'salon_cocina', TipoArista.REQUERIDA),
    ('salon', 'cocina', TipoArista.REQUERIDA),
    ('salon', 'pasillo', TipoArista.REQUERIDA),
    ('salon_cocina', 'pasillo', TipoArista.REQUERIDA),
    ('vestibulo', 'pasillo', TipoArista.PERMITIDA),
    ('pasillo', 'dormitorio_*', TipoArista.REQUERIDA),
    ('pasillo', 'bano_*', TipoArista.REQUERIDA),
    ('pasillo', 'aseo', TipoArista.REQUERIDA),
    ('pasillo', 'bano', TipoArista.REQUERIDA),
    ('salon', 'dormitorio_*', TipoArista.PROHIBIDA),
    ('cocina', 'dormitorio_*', TipoArista.PROHIBIDA),
    ('cocina', 'bano_*', TipoArista.PROHIBIDA),
    ('cocina', 'aseo', TipoArista.PROHIBIDA),
    ('cocina', 'bano', TipoArista.PROHIBIDA),
]


def _coincide(patron: str, nombre: str) -> bool:
    if patron.endswith('*'):
        return nombre.startswith(patron[:-1])
    return patron == nombre


def construir_grafo_funcional(
    estancias_nombres: list[str],
    reglas: list[tuple[str, str, TipoArista]] | None = None,
) -> nx.Graph:
    if reglas is None:
        reglas = REGLAS_VIVIENDA
    g = nx.Graph()
    for n in estancias_nombres:
        g.add_node(n)
    for a_pat, b_pat, tipo in reglas:
        for a in estancias_nombres:
            if not _coincide(a_pat, a):
                continue
            for b in estancias_nombres:
                if a == b or not _coincide(b_pat, b):
                    continue
                if g.has_edge(a, b):
                    actual = g[a][b]['tipo']
                    if actual == TipoArista.PROHIBIDA:
                        continue
                g.add_edge(a, b, tipo=tipo)
    return g


def aristas_requeridas(g: nx.Graph) -> list[tuple[str, str]]:
    return [(a, b) for a, b, d in g.edges(data=True) if d['tipo'] == TipoArista.REQUERIDA]


def aristas_prohibidas(g: nx.Graph) -> list[tuple[str, str]]:
    return [(a, b) for a, b, d in g.edges(data=True) if d['tipo'] == TipoArista.PROHIBIDA]
