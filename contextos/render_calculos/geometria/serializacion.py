"""Serialización del edificio plurifamiliar a JSON (§2.5/§2.7).

Adaptado desde `Modulos/puccetti-app/puccetti/serializacion.py`. Cambios:
- Las tablas de pandas se reemplazan por listas de dicts puros (sin pandas):
  el frontend no necesita DataFrame, y así evitamos arrastrar pandas al
  motor del módulo.
- `edificio_a_dict` añade el bounding box global y la lista de lados
  clasificados (fachada/medianera + azimut + orientación cardinal) que el
  canvas necesita para etiquetar orientaciones.
"""
from __future__ import annotations
from typing import Any

from shapely.geometry import Polygon

from .config import Parametros
from .macro_layout import EdificioPlurifamiliar, PlantaPlurifamiliar, Unidad, Nucleo
from .parcelas import LadoParcela, orientacion_cardinal


def ring(geom: Polygon, tol: float = 0.03) -> list[list[float]]:
    """Anillo exterior como lista [[x,y],...] redondeado a cm."""
    if geom is None or geom.is_empty:
        return []
    g = geom.simplify(tol, preserve_topology=True)
    if g.is_empty or not hasattr(g, "exterior"):
        g = geom
    return [[round(x, 2), round(y, 2)] for x, y in g.exterior.coords]


def _nucleo_dict(nuc: Nucleo | None) -> dict[str, Any] | None:
    if nuc is None:
        return None
    return {
        "poligono": ring(nuc.geometry),
        "escalera": ring(nuc.escalera),
        "ascensor": ring(nuc.ascensor),
        "vestibulo": ring(nuc.vestibulo),
        "area_m2": round(nuc.area_m2, 2),
        "circulo_libre": {
            "centro": [round(nuc.circulo_centro[0], 2), round(nuc.circulo_centro[1], 2)],
            "radio_m": round(nuc.circulo_radio, 2),
            "diametro_m": round(nuc.circulo_radio * 2, 2),
            "cumple": nuc.circulo_ok,
        },
    }


def _unidad_dict(u: Unidad) -> dict[str, Any]:
    return {
        "id": u.id,
        "tipo": u.tipo,
        "n_dormitorios": u.n_dorms,
        "poligono_util": ring(u.geometry),
        "poligono_construido": ring(u.geometry_construida),
        "area_util_m2": u.area_util_m2,
        "area_construida_m2": u.area_construida_m2,
        "area_min_m2": u.area_min_m2,
        "acceso_pasillo": u.acceso_pasillo,
        "borde_pasillo_m": u.borde_pasillo_m,
        "ventilacion": {
            "tipo": u.ventilacion_tipo,
            "borde_m": u.borde_ventilacion_m,
            "hueco_requerido_m2": u.hueco_req_m2,
            "hueco_disponible_m2": u.hueco_disp_m2,
            "cumple": u.ventila_ok,
        },
        "cumple_minimos": u.cumple_min,
        "es_adaptada": u.es_adaptada,
        "incidencias": list(u.incidencias),
    }


def _planta_dict(pl: PlantaPlurifamiliar) -> dict[str, Any]:
    return {
        "n": pl.n,
        "nombre": "PB" if pl.n == 0 else f"P{pl.n}",
        "tipologia": pl.tipologia,
        "edges": pl.edges,
        "footprint": ring(pl.footprint),
        "muros_perimetrales": ring(pl.muros_perimetrales),
        "nucleo": _nucleo_dict(pl.nucleo),
        "pasillos": [
            {"poligono": ring(p.geometry), "ancho_m": p.ancho_m,
             "area_m2": round(p.area_m2, 2)}
            for p in pl.pasillos
        ],
        "patios": [
            {"poligono": ring(p.geometry), "area_m2": round(p.area_m2, 2),
             "luz_recta_m": round(p.luz_recta_m, 2)}
            for p in pl.patios
        ],
        "unidades": [_unidad_dict(u) for u in pl.unidades],
        "superficies": {
            "construida_m2": pl.construida_m2,
            "util_viviendas_m2": pl.util_unidades_m2,
            "circulacion_comun_m2": pl.circulacion_m2,
            "muros_m2": pl.muros_m2,
            "patios_m2": pl.patios_m2,
            "eficiencia_util_pct": round(100 * pl.util_unidades_m2 / pl.construida_m2, 1)
                                   if pl.construida_m2 else 0.0,
        },
        "n_viviendas": len(pl.unidades),
        "score": pl.score,
        "incidencias": list(pl.incidencias),
    }


def lados_a_dict(lados: list[LadoParcela]) -> list[dict[str, Any]]:
    """Lados con orientación cardinal y bandera fachada/medianera (req. 10)."""
    return [
        {
            "indice": i,
            "p1": [round(l.p1[0], 2), round(l.p1[1], 2)],
            "p2": [round(l.p2[0], 2), round(l.p2[1], 2)],
            "tipo": l.tipo,
            "longitud_m": round(l.longitud_m, 2),
            "azimut": round(l.azimut, 1),
            "orientacion": orientacion_cardinal(l.azimut),
        }
        for i, l in enumerate(lados)
    ]


def edificio_a_dict(
    edif: EdificioPlurifamiliar,
    params: Parametros,
    lados: list[LadoParcela] | None = None,
) -> dict[str, Any]:
    plantas = [_planta_dict(p) for p in edif.plantas]
    construida_total = sum(p["superficies"]["construida_m2"] for p in plantas)
    util_total = sum(p["superficies"]["util_viviendas_m2"] for p in plantas)
    bbox = list(edif.parcela.bounds) if not edif.parcela.is_empty else [0.0, 0.0, 0.0, 0.0]
    cap = edif.capacidad
    return {
        "proyecto": {
            "uso": params.programa.uso,
            "categoria": params.programa.categoria,
            "n_dormitorios": params.programa.n_dormitorios,
            "n_viviendas_por_planta": params.programa.n_viviendas_por_planta,
            "n_plantas": len(edif.plantas),
            "pct_unidades_adaptadas": params.programa.pct_unidades_adaptadas,
        },
        "parcela": {
            "poligono": ring(edif.parcela),
            "area_m2": round(edif.parcela.area, 2),
            "bbox": [round(v, 2) for v in bbox],
        },
        "lados": lados_a_dict(lados) if lados else [],
        "edificabilidad": {
            "maxima_m2": round(edif.edificabilidad_max, 2),
            "consumida_m2": round(edif.edificabilidad_consumida, 2),
            "consumida_pct": round(100 * edif.edificabilidad_consumida / edif.edificabilidad_max, 1)
                             if edif.edificabilidad_max else 0.0,
        },
        "plantas": plantas,
        "totales": {
            "n_viviendas": edif.n_viviendas_total,
            "construida_total_m2": round(construida_total, 2),
            "util_total_m2": round(util_total, 2),
            "incidencias": sum(len(p["incidencias"]) for p in plantas),
        },
        "capacidad": {
            "n_viviendas_objetivo": cap.n_viviendas_objetivo if cap else 0,
            "n_viviendas_dispuestas": edif.n_viviendas_total,
            "factor_limitante": cap.factor_limitante if cap else "—",
            "viv_por_planta_objetivo": edif.viv_por_planta_objetivo,
            "viv_por_planta_dispuestas": edif.viv_por_planta_dispuestas,
            "n_plantas_edificables": cap.n_plantas_edificables if cap else len(edif.plantas),
        } if cap else None,
    }


def tabla_por_planta(edif: EdificioPlurifamiliar) -> list[dict[str, Any]]:
    """Una fila por planta (req. 16 y 17)."""
    rows: list[dict[str, Any]] = []
    for p in edif.plantas:
        rows.append({
            "planta": "PB" if p.n == 0 else f"P{p.n}",
            "viviendas": len(p.unidades),
            "construida_m2": p.construida_m2,
            "util_viviendas_m2": p.util_unidades_m2,
            "circulacion_m2": p.circulacion_m2,
            "patios_m2": p.patios_m2,
            "muros_m2": p.muros_m2,
            "eficiencia_pct": round(100 * p.util_unidades_m2 / p.construida_m2, 1)
                              if p.construida_m2 else 0.0,
        })
    return rows


def tabla_por_unidad(edif: EdificioPlurifamiliar) -> list[dict[str, Any]]:
    """Una fila por vivienda (req. 16)."""
    rows: list[dict[str, Any]] = []
    for p in edif.plantas:
        for u in p.unidades:
            rows.append({
                "planta": "PB" if p.n == 0 else f"P{p.n}",
                "vivienda": u.id,
                "dorms": u.n_dorms,
                "util_m2": u.area_util_m2,
                "construida_m2": u.area_construida_m2,
                "min_m2": u.area_min_m2,
                "cumple_min": u.cumple_min,
                "ventilacion": u.ventilacion_tipo,
                "ventila_ok": u.ventila_ok,
                "acceso": u.acceso_pasillo,
                "adaptada": u.es_adaptada,
            })
    return rows
