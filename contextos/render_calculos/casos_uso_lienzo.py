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

from .casos_uso import CalcularLayout, ParcelaMetrica
from .geometria.disposicion import ObjetivoPlanta, disponer_planta
from .geometria.lienzo import recortar_muro, recortar_poligono, resumen_por_color
from .geometria.serializacion import ring
from .parametros import ParametrosRender

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


# ─── Caso de uso 4: AutodistribuirLienzo (cálculo → piezas del lienzo) ──────
@dataclass
class AutodistribuirLienzo:
    """Reparte los m² calculados (unidades / muros / circulación / núcleo /
    patio / local) como piezas coloreadas del lienzo, planta a planta (Anexo II).

    Reutiliza `CalcularLayout.preparar` (mismo cálculo que la tabla de
    superficies) para obtener envolvente + capacidad, y `geometria.disposicion`
    para la geometría. Las áreas de cada categoría cuadran con el cálculo.

    El índice de planta coincide con el de las pestañas del lienzo y con la clave
    bajo la que `GuardarLienzo` persiste cada dibujo (posición en
    `envolvente.plantas`).
    """

    layout: CalcularLayout
    repo_proyectos: ProyectoRepositorio | None = None

    def ejecutar(
        self,
        proyecto: Proyecto,
        parcela: ParcelaMetrica,
        params: ParametrosRender,
        planta: int | None = None,
        persistir: bool = False,
    ) -> dict[str, Any]:
        prep = self.layout.preparar(parcela, params)
        if prep.error is not None or prep.cap is None:
            return {
                "error": prep.error or "No se pudo calcular la capacidad de la parcela.",
                "plantas": {},
                "incidencias": [],
                "resumen": [],
                "persistido": 0,
            }

        cap = prep.cap
        plantas_motor = list(prep.envolvente.plantas)
        pm = params.a_parametros_motor()  # anchos / espesores de referencia (PB)

        plantas_out: dict[str, dict[str, Any]] = {}
        incidencias: list[str] = []
        resumen: list[dict[str, Any]] = []

        # `i` es la posición en `envolvente.plantas`, que coincide con el índice de
        # `cap.*_por_planta[]` (ambos se recorren en el mismo orden), con la pestaña
        # del lienzo (`data-indice`) y con la clave de `GuardarLienzo`. Con sótano:
        # i=0 → sótano (n=-1), i=1 → PB (n=0), etc. La alineación está garantizada.
        for i, pl in enumerate(plantas_motor):
            if planta is not None and i != planta:
                continue
            obj = self._objetivo(i, pl, cap)
            res = disponer_planta(obj, parcela.lados, pm)
            figuras = [
                {
                    "id": f"auto-P{i}-{j}",
                    "tipo": "poly",
                    "nombre": pieza.nombre,
                    "color": pieza.color,
                    "vertices": pieza.vertices,
                    "rotacion": 0.0,
                }
                for j, pieza in enumerate(res.piezas)
            ]
            muros = [
                {
                    "id": f"autom-P{i}-{j}",
                    "nombre": m.nombre,
                    "color": m.color,
                    "p1": m.p1,
                    "p2": m.p2,
                    "grosor": m.grosor,
                }
                for j, m in enumerate(res.muros)
            ]
            plantas_out[str(i)] = {"figuras": figuras, "muros": muros}
            incidencias.extend(res.incidencias)
            resumen.append({
                "planta": cap.nombres_planta[i] if i < len(cap.nombres_planta) else f"P{i}",
                "areas": {k: round(v, 2) for k, v in res.areas.items()},
                "n_piezas": len(res.piezas),
                "n_muros": len(res.muros),
            })

        persistido = 0
        if persistir and self.repo_proyectos is not None and plantas_out:
            # Al regenerar TODAS las plantas (planta is None), se descartan primero
            # los dibujos de plantas que ya no existen (p. ej. si se redujo el nº de
            # plantas), para que no reaparezcan al volver a aumentarlo.
            if planta is None:
                lienzo = proyecto.datos(ModuloPuccetti.RENDER_CALCULOS).setdefault(
                    "lienzo", {"plantas": {}}
                )
                lienzo.setdefault("plantas", {})
                for obsoleta in [k for k in lienzo["plantas"] if k not in plantas_out]:
                    lienzo["plantas"].pop(obsoleta, None)
            guardar = GuardarLienzo(repo_proyectos=self.repo_proyectos)
            for idx, bloque in plantas_out.items():
                guardar.ejecutar(proyecto, int(idx), bloque["figuras"], bloque["muros"])
                persistido += 1

        return {
            "plantas": plantas_out,
            "incidencias": incidencias,
            "resumen": resumen,
            "persistido": persistido,
        }

    def _objetivo(self, i: int, pl, cap) -> ObjetivoPlanta:
        """Construye el objetivo de una planta desde la capacidad calculada."""
        def _g(lista, defecto=0.0):
            return float(lista[i]) if i < len(lista) else defecto

        unidades_raw = cap.unidades_por_planta[i] if i < len(cap.unidades_por_planta) else []
        unidades = [(f"V{j + 1}", float(util)) for j, (_n, util) in enumerate(unidades_raw)]
        return ObjetivoPlanta(
            nombre=cap.nombres_planta[i] if i < len(cap.nombres_planta) else f"P{i}",
            tipo=cap.tipo_planta[i] if i < len(cap.tipo_planta) else "regular",
            footprint=pl.footprint,
            unidades=unidades,
            muros_m2=_g(cap.muros_por_planta),
            circulacion_m2=_g(cap.circulacion_por_planta),
            nucleo_m2=_g(cap.nucleo_por_planta),
            patio_m2=_g(cap.patio_por_planta),
            local_m2=_g(cap.local_por_planta),
            util_m2=_g(cap.util_por_planta),
        )
