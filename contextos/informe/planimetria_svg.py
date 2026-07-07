"""Planimetría a SVG (§2.8) — render server-side de la envolvente por planta.

Funciones puras: toman una planta ya serializada (`footprint` + `patios`, anillos
en metros UTM tal como los emite `render_calculos`) y devuelven un ``<svg>``
autocontenido para incrustar en el informe. Sin navegador ni librerías de dibujo,
así se reaprovecha en el PDF y es testeable. Duplica a propósito el criterio de
escala e inversión-Y del canvas (`rc_canvas.js`): la regla del proyecto es no
deduplicar geometría entre contextos.

Colores corporativos: Negro #0A0A0A · Dorado #B8960C / #C9A84C · Blanco #FFFFFF.
"""
from __future__ import annotations

from typing import Any, Sequence

Anillo = Sequence[Sequence[float]]

_ANCHO = 380.0   # unidades de viewBox del lado mayor del dibujo
_PAD = 10.0      # margen interior en unidades de viewBox

_ORO = "#B8960C"
_ORO_CLARO = "#C9A84C"
_NEGRO = "#0A0A0A"


def bbox_de(*anillos: Anillo | None) -> tuple[float, float, float, float] | None:
    """Caja envolvente (minx, miny, maxx, maxy) de varios anillos, o None si vacío."""
    xs: list[float] = []
    ys: list[float] = []
    for anillo in anillos:
        for punto in anillo or ():
            if len(punto) >= 2:
                xs.append(float(punto[0]))
                ys.append(float(punto[1]))
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _puntos(anillo: Anillo, tx, ty) -> str:
    return " ".join(f"{tx(p[0]):.1f},{ty(p[1]):.1f}" for p in anillo if len(p) >= 2)


def planta_a_svg(
    planta: dict[str, Any],
    *,
    bbox: tuple[float, float, float, float] | None,
    parcela_poligono: Anillo | None = None,
) -> str:
    """SVG de una planta: contorno de parcela (contexto) + huella + patios (vacíos).

    `bbox` es compartido por todas las plantas del informe para que rendericen a la
    MISMA escala. Devuelve "" si no hay geometría dibujable (nunca inventa un plano).
    """
    footprint = planta.get("footprint") or []
    patios = planta.get("patios") or []
    if bbox is None or len(footprint) < 3:
        return ""

    minx, miny, maxx, maxy = bbox
    dx = (maxx - minx) or 1.0
    dy = (maxy - miny) or 1.0
    escala = (_ANCHO - 2 * _PAD) / max(dx, dy)
    ancho = dx * escala + 2 * _PAD
    alto = dy * escala + 2 * _PAD

    def tx(x: float) -> float:
        return _PAD + (float(x) - minx) * escala

    def ty(y: float) -> float:
        return _PAD + (maxy - float(y)) * escala   # eje Y invertido (norte arriba)

    nombre = str(planta.get("nombre") or "")
    partes = [
        f'<svg viewBox="0 0 {ancho:.1f} {alto:.1f}" '
        f'xmlns="http://www.w3.org/2000/svg" class="plano-svg" '
        f'role="img" aria-label="Planta {nombre}">'
    ]

    if parcela_poligono and len(parcela_poligono) >= 3:
        partes.append(
            f'<polygon points="{_puntos(parcela_poligono, tx, ty)}" fill="none" '
            f'stroke="{_NEGRO}" stroke-opacity="0.25" stroke-dasharray="4 3" stroke-width="1"/>'
        )

    partes.append(
        f'<polygon points="{_puntos(footprint, tx, ty)}" fill="{_ORO_CLARO}" '
        f'fill-opacity="0.15" stroke="{_ORO}" stroke-width="1.6"/>'
    )

    for patio in patios:
        anillo = patio.get("poligono") or []
        if len(anillo) >= 3:
            partes.append(
                f'<polygon points="{_puntos(anillo, tx, ty)}" fill="#FFFFFF" '
                f'stroke="{_ORO}" stroke-opacity="0.7" stroke-dasharray="3 2" stroke-width="1"/>'
            )

    partes.append("</svg>")
    return "".join(partes)
