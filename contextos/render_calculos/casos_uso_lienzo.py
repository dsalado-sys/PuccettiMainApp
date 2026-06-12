"""§2.4 — Casos de uso del lienzo de dibujo manual sobre la parcela.

Capa ADITIVA al módulo Render y cálculos: no toca los parámetros ni la lógica de
cálculo automático. El dibujo se guarda por índice de planta bajo una clave nueva
`proyecto.datos(RENDER_CALCULOS)["lienzo"]`, sin pisar `["parametros"]`.

Casos de uso puros: reciben dependencias por parámetro (DI) y no conocen FastAPI
ni SQLAlchemy. Reciben la `ParcelaMetrica` ya construida desde el endpoint (igual
que /preview).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.contextos.proyectos.puertos import ProyectoRepositorio
from app.nucleo.modelo import ModuloPuccetti, Proyecto

from .casos_uso import ParcelaMetrica
from .geometria.lienzo import recortar_muro, recortar_poligono, resumen_por_color
from .geometria.serializacion import ring

# Topes defensivos del payload (backstop ante dibujos accidentalmente enormes).
LIENZO_MAX_FIGURAS = 1000
LIENZO_MAX_MUROS = 1000
LIENZO_MAX_VERTICES = 2000
GROSOR_MURO_DEFECTO = 0.30


# ─── Helpers de saneo ───────────────────────────────────────────────────────
def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _saneo_punto(v: Any) -> list[float] | None:
    if not v or len(v) < 2:
        return None
    x, y = _num(v[0]), _num(v[1])
    if x is None or y is None:
        return None
    return [x, y]


def _saneo_vertices(verts: Any) -> list[list[float]]:
    out: list[list[float]] = []
    for v in (verts or [])[:LIENZO_MAX_VERTICES]:
        p = _saneo_punto(v)
        if p is not None:
            out.append(p)
    return out


def _saneo_figura(f: Any) -> dict[str, Any]:
    return {
        "id": str(f.get("id") or ""),
        "tipo": str(f.get("tipo") or "poly"),
        "nombre": str(f.get("nombre") or ""),
        "color": str(f.get("color") or "#000000"),
        "vertices": _saneo_vertices(f.get("vertices")),
        "rotacion": _num(f.get("rotacion")) or 0.0,
    }


def _saneo_muro(m: Any) -> dict[str, Any]:
    grosor = _num(m.get("grosor"))
    return {
        "id": str(m.get("id") or ""),
        "nombre": str(m.get("nombre") or ""),
        "color": str(m.get("color") or "#000000"),
        "p1": _saneo_punto(m.get("p1")),
        "p2": _saneo_punto(m.get("p2")),
        "grosor": grosor if (grosor is not None and grosor > 0) else GROSOR_MURO_DEFECTO,
    }


def _parcela_dict(parcela: ParcelaMetrica) -> dict[str, Any]:
    poly = parcela.poligono_utm
    return {"poligono": ring(poly), "bbox": [round(v, 2) for v in poly.bounds]}


# ─── Caso de uso 1: CalcularLienzo (recorte + áreas + resumen) ──────────────
@dataclass
class CalcularLienzo:
    """Recorta cada pieza a la parcela y devuelve áreas + resumen por color.

    No persiste: es el endpoint que el frontend llama (debounced) para obtener los
    m² autoritativos mientras el usuario dibuja.
    """

    def ejecutar(
        self, parcela: ParcelaMetrica, figuras: Any, muros: Any
    ) -> dict[str, Any]:
        poly = parcela.poligono_utm
        figuras = list(figuras or [])[:LIENZO_MAX_FIGURAS]
        muros = list(muros or [])[:LIENZO_MAX_MUROS]

        piezas_fig: list[dict[str, Any]] = []
        for f in figuras:
            rings, area = recortar_poligono(f.get("vertices"), poly)
            piezas_fig.append({
                "id": f.get("id"),
                "tipo": str(f.get("tipo") or "poly"),
                "nombre": str(f.get("nombre") or ""),
                "color": str(f.get("color") or "#000000"),
                "rings": rings,
                "area_m2": area,
            })

        piezas_mur: list[dict[str, Any]] = []
        for m in muros:
            grosor = m.get("grosor", GROSOR_MURO_DEFECTO)
            rings, area = recortar_muro(m.get("p1"), m.get("p2"), grosor, poly)
            piezas_mur.append({
                "id": m.get("id"),
                "tipo": "muro",
                "nombre": str(m.get("nombre") or ""),
                "color": str(m.get("color") or "#000000"),
                "rings": rings,
                "area_m2": area,
            })

        return {
            "parcela": _parcela_dict(parcela),
            "figuras": piezas_fig,
            "muros": piezas_mur,
            "resumen": resumen_por_color(piezas_fig, piezas_mur),
        }


# ─── Caso de uso 2: GuardarLienzo (persiste sin pisar ["parametros"]) ───────
@dataclass
class GuardarLienzo:
    """Persiste el dibujo crudo de una planta en el aggregate.

    Muta SOLO `datos(RENDER_CALCULOS)["lienzo"]["plantas"][str(planta)]`; nunca
    toca `["parametros"]`/`["resumen_ultimo_calculo"]` (a diferencia de
    `GuardarRender`, que reemplaza el bloque entero con `fijar_datos`). Solo se
    persiste la entrada del usuario; rings y áreas son derivados (se recalculan).
    """

    repo_proyectos: ProyectoRepositorio

    def ejecutar(
        self, proyecto: Proyecto, planta: int, figuras: Any, muros: Any
    ) -> Proyecto:
        idx = str(int(planta))
        datos = proyecto.datos(ModuloPuccetti.RENDER_CALCULOS)  # dict mutable real
        lienzo = datos.setdefault("lienzo", {"plantas": {}})
        lienzo.setdefault("plantas", {})

        figs = [_saneo_figura(f) for f in list(figuras or [])[:LIENZO_MAX_FIGURAS]]
        figs = [f for f in figs if len(f["vertices"]) >= 2]
        murs = [_saneo_muro(m) for m in list(muros or [])[:LIENZO_MAX_MUROS]]
        murs = [m for m in murs if m["p1"] is not None and m["p2"] is not None]

        lienzo["plantas"][idx] = {"figuras": figs, "muros": murs}
        lienzo["timestamp"] = datetime.now(timezone.utc).isoformat()
        proyecto.tocar()
        return self.repo_proyectos.guardar(proyecto)


# ─── Caso de uso 3: CargarLienzo (parcela + dibujos guardados) ──────────────
@dataclass
class CargarLienzo:
    """Devuelve la parcela (ring UTM + bbox) y el dibujo guardado por planta."""

    def ejecutar(self, proyecto: Proyecto, parcela: ParcelaMetrica) -> dict[str, Any]:
        datos = proyecto.datos_por_modulo.get(ModuloPuccetti.RENDER_CALCULOS.value) or {}
        lienzo = datos.get("lienzo") or {}
        plantas = lienzo.get("plantas") or {}
        return {"parcela": _parcela_dict(parcela), "plantas": plantas}
