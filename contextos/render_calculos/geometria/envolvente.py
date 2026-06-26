"""Envolvente edificatoria (§2.4): huella + plantas + patios interiores.

Iteración 4 (2026-06-04):
- Retranqueos direccionales: fachada se aplica solo a lados tipo "fachada",
  linderos solo a lados tipo "medianera". Excluyentes (cada lado lleva uno).
- Ocupación máxima se aplica a la huella final (no solo al cálculo): si la
  huella tras retranqueos excede `ocupacion × parcela`, se erosiona
  uniformemente hasta encajar.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from shapely.geometry import LineString, Polygon, box, Point
from shapely.ops import unary_union

from .config import Parametros


def _normalizar(g) -> Polygon:
    """Devuelve un Polygon válido y no vacío a partir de cualquier salida de offset.

    Los offsets de Shapely (`buffer`, `difference`) pueden devolver geometrías
    inválidas (auto-intersección en vértices cóncavos), MultiPolygon (la operación
    partió la huella) o GeometryCollection (restos de líneas/puntos). Aquí se
    reparan (`buffer(0)`), se descartan las piezas no poligonales y se conserva la
    pieza poligonal de mayor área. Si no queda ninguna, devuelve un Polygon vacío,
    que `construir_envolvente` traduce en el ValueError "no queda espacio edificable".
    """
    if g is None or g.is_empty:
        return Polygon()
    if not g.is_valid:
        g = g.buffer(0)
        if g.is_empty:
            return Polygon()
    if hasattr(g, "geoms"):
        polys = [p for p in g.geoms if p.geom_type == "Polygon" and not p.is_empty]
        if not polys:
            return Polygon()
        g = max(polys, key=lambda p: p.area)
    if g.geom_type != "Polygon":
        return Polygon()
    return g


@dataclass
class Patio:
    geometry: Polygon
    area_m2: float
    luz_recta_m: float


@dataclass
class Planta:
    n: int                       # 0=PB, 1=P1, ...
    footprint: Polygon
    interior: Polygon
    patios: list[Patio] = field(default_factory=list)
    area_construida_m2: float = 0.0
    area_util_m2: float = 0.0
    computa_edif: bool = True
    tipo: str = "regular"        # "regular" | "atico" | "sotano"


@dataclass
class Envolvente:
    parcela: Polygon
    plantas: list[Planta]
    edificabilidad_consumida: float
    edificabilidad_max: float
    # Superficie de SUELO usada para los límites legales (edificabilidad y
    # ocupación). Es la superficie catastral real de la parcela cuando se conoce;
    # si es 0, los consumidores caen en el área geométrica del polígono.
    superficie_referencia_m2: float = 0.0


def _restar_franja_lado(huella: Polygon, p1, p2, retranqueo: float) -> Polygon:
    """Resta del polígono una franja de grosor `retranqueo` hacia el interior
    del polígono, partiendo del segmento p1→p2.

    Estrategia: buffer del segmento con ambos lados (`single_sided=False`), de
    grosor `retranqueo`. Eso da un rectángulo angosto centrado en el segmento;
    al restarlo del polígono, solo afecta a la parte interior (el exterior
    queda fuera del polígono igualmente).
    """
    if retranqueo <= 0:
        return huella
    seg = LineString([p1, p2])
    franja = seg.buffer(retranqueo, cap_style=2)  # cap_style=2 = flat (sin redondeo)
    # `_normalizar` repara invalidez, descarta restos no poligonales (LineString/
    # GeometryCollection en vértices cóncavos) y conserva la pieza mayor. Si el
    # retranqueo agota la huella se devuelve Polygon() vacío (antes se devolvía la
    # huella intacta, sobreestimando el suelo edificable): así el ValueError de
    # construir_envolvente refleja que no queda espacio (§2.7-2.9).
    return _normalizar(huella.difference(franja))


def _aplicar_ocupacion_maxima(huella: Polygon, ocup_area: float) -> Polygon:
    """Erosiona uniformemente la huella hasta que su área ≤ ocup_area.

    Bisección numérica: prueba buffer(-delta) con delta creciente hasta encajar.
    Para parcelas pequeñas suele converger en <8 iteraciones.
    """
    if huella.area <= ocup_area + 1e-3:
        return huella
    lo, hi = 0.0, max(huella.area ** 0.5, 1.0)
    mejor = huella
    for _ in range(20):
        mid = (lo + hi) / 2.0
        candidato = huella.buffer(-mid).buffer(0)
        if candidato.is_empty:
            hi = mid
            continue
        if hasattr(candidato, "geoms"):
            candidato = max(candidato.geoms, key=lambda g: g.area)
        if candidato.area <= ocup_area + 1e-3:
            mejor = candidato
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-3:
            break
    return mejor


def aplicar_retranqueos(parcela: Polygon, params: Parametros, lados=None) -> Polygon:
    """Aplica retranqueos direccionales:
    - Lados tipo "fachada" reciben `retranqueo_fachada`.
    - Lados tipo "medianera" reciben `retranqueo_linderos`.

    Si `lados` es None, no hay clasificación: se aplica `retranqueo_linderos`
    como buffer uniforme negativo (comportamiento conservador).

    Caso uniforme (un único retranqueo efectivo para TODOS los lados — lo habitual
    en producción, donde la parcela suele venir con todos los lados como "fachada"):
    se usa `buffer(-d)` con esquinas a inglete (`join_style=2`), robusto en parcelas
    cóncavas (formas en L/U, patios). El offset por franjas solo se conserva para el
    caso direccional real (dos retranqueos distintos con lados mezclados), donde una
    erosión uniforme deformaría los lados que no deben moverse.
    """
    u = params.urbanismo
    r_fach = float(u.retranqueo_fachada)
    r_lind = float(u.retranqueo_linderos)

    if r_fach <= 0 and r_lind <= 0:
        return parcela

    if not lados:
        # Sin lados clasificados, aplicamos el mayor de los dos como uniforme.
        retranqueo = max(r_fach, r_lind)
        return _normalizar(parcela.buffer(-retranqueo, join_style=2)) if retranqueo > 0 else parcela

    # Retranqueo efectivo por lado según su tipo.
    retr_por_lado = [
        (r_fach if getattr(l, "tipo", "fachada") == "fachada" else r_lind)
        for l in lados
    ]
    distintos = {round(r, 6) for r in retr_por_lado}
    if distintos == {0.0}:
        return parcela
    if len(distintos) == 1:
        # Mismo retranqueo en todos los lados → erosión uniforme robusta a cóncavos.
        d = next(iter(distintos))
        return _normalizar(parcela.buffer(-d, join_style=2))

    # Caso direccional real (retranqueos distintos con lados mezclados): offset por
    # franja lado a lado. `_restar_franja_lado` ya normaliza la salida.
    huella = parcela
    for lado in lados:
        tipo = getattr(lado, "tipo", "fachada")
        if tipo == "fachada" and r_fach > 0:
            huella = _restar_franja_lado(huella, lado.p1, lado.p2, r_fach)
        elif tipo == "medianera" and r_lind > 0:
            huella = _restar_franja_lado(huella, lado.p1, lado.p2, r_lind)
    return huella


def detectar_patio(interior_planta: Polygon, params: Parametros) -> Optional[Patio]:
    """Abre un patio interior si la luz mínima cabe en la planta.

    El patio se intenta colocar en el "polo de inaccesibilidad" (el punto más
    interior). Solo se genera si su área alcanza al menos el 60% del área
    mínima normativa.
    """
    if interior_planta.is_empty:
        return None

    try:
        from shapely.ops import polylabel
        p_int: Point = polylabel(interior_planta, tolerance=0.5)
    except Exception:
        p_int = interior_planta.representative_point()

    lr = params.diseno.luz_recta_patio_min
    area_target = params.diseno.area_patio_min
    if lr <= 0 or area_target <= 0:
        return None
    lado_b = max(lr, area_target / lr)
    rect = box(p_int.x - lr / 2, p_int.y - lado_b / 2,
               p_int.x + lr / 2, p_int.y + lado_b / 2)
    rect = rect.intersection(interior_planta)
    if rect.is_empty or rect.area < area_target * 0.6:
        return None
    return Patio(geometry=rect, area_m2=rect.area, luz_recta_m=lr)


def _huella_atico(huella: Polygon, retranqueo_atico: float) -> Polygon:
    """Huella reducida del ático tras aplicar el retranqueo perimetral."""
    if retranqueo_atico <= 0:
        return huella
    reducida = huella.buffer(-retranqueo_atico).buffer(0)
    if reducida.is_empty:
        return Polygon()
    if hasattr(reducida, "geoms"):
        reducida = max(reducida.geoms, key=lambda g: g.area)
    return reducida


def construir_envolvente(
    parcela: Polygon,
    params: Parametros,
    lados=None,
    superficie_referencia: float | None = None,
) -> Envolvente:
    """Pipeline §2.4 completo: retranqueos direccionales → ocupación → N plantas → patios.

    Iteración 4: acepta `lados: list[LadoParcela] | None`. Si se pasan, los
    retranqueos se aplican direccionalmente según el tipo de cada lado.

    `superficie_referencia` es la superficie de SUELO contra la que se calculan los
    límites legales (edificabilidad y ocupación máxima). Cuando se conoce la
    superficie catastral real de la parcela se pasa aquí; si es None/0 se usa el
    área geométrica del polígono reproyectado (comportamiento histórico). La FORMA
    de la huella (retranqueos, geometría) siempre proviene del polígono.
    """
    sup_ref = (
        float(superficie_referencia)
        if superficie_referencia and superficie_referencia > 0
        else parcela.area
    )
    huella_retr = aplicar_retranqueos(parcela, params, lados)
    if huella_retr.is_empty:
        raise ValueError("Tras retranqueos no queda espacio edificable.")

    espesor = params.diseno.espesor_muro_fachada

    # Ocupación máxima POR CATEGORÍA DE PLANTA: PB (y sótano) usan la ocupación de
    # planta baja; las plantas tipo (y el ático) la suya. Partimos de la MISMA huella
    # tras retranqueos y la erosionamos a cada límite de forma independiente. Si ambas
    # ocupaciones coinciden (lo habitual / proyectos sin ocupación de tipo) las huellas
    # son idénticas y el resultado no cambia respecto al histórico.
    def _huella_ocupada(ocup_frac: float) -> Polygon:
        area = max(0.0, float(ocup_frac)) * sup_ref
        if area <= 0:
            return huella_retr
        return _aplicar_ocupacion_maxima(huella_retr, area)

    def _interior(h: Polygon) -> Polygon:
        # `_normalizar`: el offset de muro puede partir la huella en un cuello estrecho
        # (< 2·espesor) y devolver MultiPolygon; nos quedamos con la pieza mayor para no
        # falsear el útil. Fallback (parcelas muy pequeñas): interior = huella sin offset.
        if h.is_empty:
            return Polygon()
        i = _normalizar(h.buffer(-espesor))
        return i if not i.is_empty else h

    huella_pb = _huella_ocupada(params.urbanismo.ocupacion_maxima)
    if huella_pb.is_empty:
        raise ValueError("Tras aplicar ocupación máxima no queda huella construible.")
    huella_tipo = _huella_ocupada(
        getattr(params.urbanismo, "ocupacion_maxima_tipo", params.urbanismo.ocupacion_maxima)
    )
    if huella_tipo.is_empty:
        huella_tipo = huella_pb

    interior_pb = _interior(huella_pb)
    interior_tipo = _interior(huella_tipo)

    plantas: list[Planta] = []
    edif_acumulada = 0.0

    # ── Sótano (bajo rasante: ocupa la huella completa de PB) ──────────────────
    if params.urbanismo.tiene_sotano:
        sotano = Planta(
            n=-1,
            footprint=huella_pb,
            interior=interior_pb,
            patios=[],
            area_construida_m2=huella_pb.area,
            area_util_m2=interior_pb.area,
            computa_edif=params.urbanismo.sotano_computa_edificabilidad,
            tipo="sotano",
        )
        plantas.append(sotano)
        if sotano.computa_edif:
            edif_acumulada += huella_pb.area

    # ── Plantas regulares: la primera (PB) usa la huella de PB; el resto, la de las
    #    plantas tipo (su propia ocupación). ──────────────────────────────────
    huella_ultima_regular = huella_pb
    for n in range(params.programa.n_plantas):
        f = huella_pb if n == 0 else huella_tipo
        i = interior_pb if n == 0 else interior_tipo
        huella_ultima_regular = f
        patios: list[Patio] = []
        patio = detectar_patio(i, params)
        if patio is not None:
            i = i.difference(patio.geometry)
            patios.append(patio)
        # El patio interior (vacío a cielo abierto) no computa ni como construido ni
        # como edificabilidad: la construida de la planta —y el techo que consume— es
        # la huella menos el área de patio.
        patios_area = sum(pt.area_m2 for pt in patios)
        construida = max(0.0, f.area - patios_area)
        plantas.append(Planta(
            n=n,
            footprint=f,
            interior=i,
            patios=patios,
            area_construida_m2=construida,
            area_util_m2=i.area,
            computa_edif=True,
            tipo="regular",
        ))
        edif_acumulada += construida

    # ── Ático ────────────────────────────────────────────────────────────────
    # Retranqueo perimetral sobre la huella de la planta inmediatamente inferior
    # (plantas tipo si las hay; si no, PB). El ático comparte el perfil de las tipo.
    if params.urbanismo.tiene_atico:
        huella_at = _huella_atico(huella_ultima_regular, params.urbanismo.retranqueo_atico)
        interior_at = _normalizar(huella_at.buffer(-espesor)) if not huella_at.is_empty else Polygon()
        n_at = (plantas[-1].n + 1) if plantas else 0
        atico = Planta(
            n=n_at,
            footprint=huella_at,
            interior=interior_at if not interior_at.is_empty else huella_at,
            patios=[],
            area_construida_m2=huella_at.area,
            area_util_m2=interior_at.area if not interior_at.is_empty else 0.0,
            computa_edif=params.urbanismo.atico_computa_edificabilidad,
            tipo="atico",
        )
        plantas.append(atico)
        if atico.computa_edif:
            edif_acumulada += huella_at.area

    # El techo máximo debe respetar el mismo criterio que `calcular_capacidad`:
    # por coeficiente (parcela × coef) o, si no se usa el coeficiente, por
    # ocupación × nº de plantas. Antes se calculaba siempre por coeficiente, lo
    # que hacía saltar una falsa alerta de edificabilidad cuando el proyecto se
    # dimensionaba por ocupación.
    urb = params.urbanismo
    if getattr(urb, "usar_coeficiente_edificabilidad", True):
        edif_max = sup_ref * urb.coeficiente_edificabilidad
    else:
        # Techo por ocupación × nº de plantas → cota SUPERIOR. Se usa la MAYOR de las
        # dos ocupaciones (PB / plantas tipo), porque la planta de mayor huella puede
        # ser la tipo (PB comercial retranqueada + plantas voladas): así el consumo
        # real (huella_pb + (n−1)·huella_tipo) nunca supera n·max(ocup)·sup_ref y no
        # se dispara un falso exceso de edificabilidad.
        ocup_max = max(urb.ocupacion_maxima, getattr(urb, "ocupacion_maxima_tipo", urb.ocupacion_maxima))
        edif_max = ocup_max * sup_ref * max(1, urb.n_plantas_max)
    return Envolvente(
        parcela=parcela,
        plantas=plantas,
        edificabilidad_consumida=edif_acumulada,
        edificabilidad_max=edif_max,
        superficie_referencia_m2=sup_ref,
    )
