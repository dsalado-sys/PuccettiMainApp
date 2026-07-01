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

from shapely.affinity import scale
from shapely.geometry import LineString, Polygon, box, Point
from shapely.ops import unary_union, nearest_points

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


# Ancho del «cuello» que une dos patios al fusionarlos. 6 cm: lo bastante ancho para
# sobrevivir a `ring()` (que simplifica con tol 0,03 m y redondea a cm), casi invisible,
# y de área despreciable (~ancho × hueco ≤ 0,006 m²).
ANCHO_PUENTE = 0.06


def fusionar_poligonos(a: Polygon, b: Polygon, ancho: float = ANCHO_PUENTE) -> Polygon:
    """Une dos patios en UNA sola figura conservando ambas formas EXACTAS.

    En vez de una envolvente convexa (que deforma y «rellena alrededor»), conecta los dos
    polígonos por sus puntos más cercanos con un cuello finísimo y los une (`unary_union`).
    El resultado es un único Polygon válido cuyo contorno son las dos formas originales más
    el cuello; su superficie ≈ suma de las dos (el cuello añade un área ínfima). Si ya se
    tocan/solapan, el cuello es inocuo. Devuelve un Polygon vacío si las entradas no valen.
    """
    a, b = _normalizar(a), _normalizar(b)
    if a.is_empty:
        return b
    if b.is_empty:
        return a
    try:
        p1, p2 = nearest_points(a, b)
        if p1.distance(p2) <= 1e-9:
            puente = p1.buffer(ancho)               # ya se tocan: un disco mínimo asegura conexión
        else:
            puente = LineString([p1, p2]).buffer(ancho / 2.0, cap_style=2)  # rectángulo fino plano
    except Exception:
        puente = Polygon()
    return _normalizar(unary_union([a, b, puente]))


def fusionar_anillos(a: list, b: list, ancho: float = ANCHO_PUENTE) -> Polygon:
    """Versión orientada a coordenadas de `fusionar_poligonos` (para la capa web).

    Recibe dos anillos `[[x, y], ...]` (UTM) y devuelve el Polygon fusionado, o un
    Polygon vacío si alguna entrada no es un polígono válido de ≥3 vértices.
    """
    try:
        pa = _normalizar(Polygon([(float(x), float(y)) for x, y in a]))
        pb = _normalizar(Polygon([(float(x), float(y)) for x, y in b]))
    except Exception:
        return Polygon()
    return fusionar_poligonos(pa, pb, ancho)


def _pieza_anclada(g, ancla: Polygon) -> Polygon:
    """Como `_normalizar` pero, ante un MultiPolygon, conserva la pieza que MÁS se solapa
    con `ancla` (el recorte original donde el usuario soltó el patio), no la de mayor área.

    Así, al rellenar un patio dentro de su hueco, el resultado no «salta» a un blob
    desconectado al otro lado de un cuello: se queda anclado donde se soltó. Si ninguna
    pieza solapa el ancla (no debería pasar: el buffer siempre contiene a `poly`), cae a
    la de mayor área (mismo criterio que `_normalizar`).
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
        solapados = [p for p in polys if p.intersection(ancla).area > 1e-9]
        g = max(solapados or polys, key=lambda p: p.intersection(ancla).area if solapados else p.area)
    if g.geom_type != "Polygon":
        return Polygon()
    return g


@dataclass
class Patio:
    geometry: Polygon       # forma EFECTIVA dibujada (base adaptada al borde): puede llevar vértices temporales
    area_m2: float          # área ASIGNADA (invariante de capacidad), no geometry.area
    luz_recta_m: float
    id: str = ""            # identidad estable (eco del PatioPlacement); "" = auto/legacy
    base: Optional[Polygon] = None   # forma IDEAL del usuario (área asignada, sin vértices temporales)
    area_efectiva_m2: float = 0.0    # área que realmente entra tras adaptarse (== area_m2 si cabe)
    cabe: bool = True                # False si, ya adaptado, no alcanza el área asignada
    bloqueado: bool = False          # patio congelado: el usuario no lo edita y el motor le da prioridad máxima


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


def _ajustar_area(geom: Polygon, area: float) -> Polygon:
    """Reescala `geom` respecto a su centroide hasta tener exactamente `area` m².

    Es la regla «área fija»: el polígono que envía el usuario puede tener cualquier
    forma, pero su superficie se normaliza al área asignada (factor √(area/actual),
    isótropo → conserva la forma y el centroide). Así, editar los m² de un patio
    reescala su forma sin moverlo, y un reformado de vértices recupera los m².
    """
    a = geom.area
    if a <= 1e-9 or area <= 0:
        return geom
    if abs(a - area) <= 1e-6 * max(area, 1.0):
        return geom
    f = (area / a) ** 0.5
    c = geom.centroid
    return _normalizar(scale(geom, xfact=f, yfact=f, origin=(c.x, c.y)))


def _rect_area(zona: Polygon, lr: float, area: float) -> Optional[Polygon]:
    """Rectángulo de área EXACTA `area` centrado en el polo de inaccesibilidad de `zona`.

    Forma por defecto del auto-colocado: lado `lr` (luz recta) × `area/lr` cuando el
    área lo permite (mantiene el ancho mínimo); si no, un cuadrado de lado √area. En
    ambos casos el área dibujada == área asignada.
    """
    if zona is None or zona.is_empty or area <= 0:
        return None
    try:
        from shapely.ops import polylabel
        c = polylabel(zona, tolerance=0.5)
    except Exception:
        c = zona.representative_point()
    if lr > 0 and area >= lr * lr:
        w, h = lr, area / lr
    else:
        w = h = area ** 0.5
    return box(c.x - w / 2, c.y - h / 2, c.x + w / 2, c.y + h / 2)


def _inflar_a_area(poly: Polygon, region, objetivo: float, hi_max: float | None = None) -> Polygon:
    """Crece `poly` DENTRO de `region` hasta alcanzar `objetivo` m², en una sola pieza.

    Bisección de la distancia de buffer: `poly.buffer(d) ∩ region`, quedándose con la pieza
    ANCLADA a `poly` (la que más lo solapa, no la de mayor área), hasta que el área llega al
    objetivo o no puede crecer más (la zona no da para más). Si `poly` ya tiene el área, lo
    devuelve tal cual (sin inflar).

    `hi_max` acota la distancia de buffer (relleno LOCAL): con `None` se usa el histórico
    `region.area**0.5` (crecimiento prácticamente ilimitado); el llamante de patios pasa un
    tope ligado al tamaño del patio para que el relleno no escape del hueco hacia el espacio
    libre lejano.
    """
    poly = _normalizar(poly)
    if poly.is_empty or objetivo <= 0:
        return poly
    if poly.area >= objetivo - 1e-9:
        return poly
    lo, hi = 0.0, hi_max if hi_max is not None else max(region.area ** 0.5, 1.0)
    mejor_ok: Optional[Polygon] = None     # menor candidato que YA llega al objetivo
    mejor_bajo = poly                      # mayor candidato que aún no llega (por si nunca llega)
    for _ in range(24):
        d = (lo + hi) / 2.0
        cand = _pieza_anclada(poly.buffer(d, join_style=2).intersection(region), poly)
        if cand.is_empty:
            hi = d
            continue
        if cand.area >= objetivo:
            mejor_ok = cand
            hi = d
        else:
            if cand.area > mejor_bajo.area:
                mejor_bajo = cand
            lo = d
        if hi - lo < 1e-3:
            break
    return mejor_ok if mejor_ok is not None else mejor_bajo


def conformar_patio(base: Polygon, region, area_objetivo: float, lr: float, footprint=None):
    """Adapta `base` al HUECO LOCAL disponible en `region`, anclada donde el usuario la soltó.

    Devuelve `(efectiva, area_efectiva, cabe)`:
    - Si `base` ya está entera dentro → `efectiva == base` (sin vértices temporales).
    - Si asoma fuera / pisa a un vecino → recorta (`∩ region`) y rellena el hueco local
      (`_inflar_a_area` acotado a ~2 lados del patio: ni teletransporta ni se infla fuera).
    - Si el hueco local no alcanza el área → `efectiva` es lo máximo que entra ahí y `cabe=False`
      (salta el aviso). NUNCA se reubica a otra zona para forzar el área.
    - Si la base cae ENTERA fuera de `region` (sobre un vecino): se queda donde se soltó,
      recortada solo a la huella (`footprint`), marcada `cabe=False`. `lr` se conserva por
      compatibilidad de firma aunque ya no se use.
    """
    base = _normalizar(base)
    if region is None or region.is_empty or base.is_empty:
        return base, base.area, False
    if region.contains(base):
        return base, area_objetivo, True
    recorte = _normalizar(base.intersection(region))
    if recorte.is_empty:
        # La base cae entera sobre un vecino / fuera de la región: aquí no hay sitio. NO se
        # siembra en otra zona (eso teletransportaba el patio): se deja donde el usuario lo
        # soltó, recortado solo a la HUELLA (puede pisar al vecino), avisando que no cabe.
        zona = footprint if (footprint is not None and not footprint.is_empty) else region
        visible = _normalizar(base.intersection(zona))
        if visible.is_empty:
            return base, base.area, False
        return visible, visible.area, False
    hi_max = max(2.0 * area_objetivo ** 0.5, 1.0)
    efectiva = _inflar_a_area(recorte, region, area_objetivo, hi_max=hi_max)
    area_ef = efectiva.area
    cabe = area_ef >= area_objetivo - 1e-6 * max(area_objetivo, 1.0)
    return efectiva, area_ef, cabe


def colocar_patios(interior_planta: Polygon, params: Parametros, footprint: Optional[Polygon] = None) -> list[Patio]:
    """Coloca TODOS los patios definidos en `params.patios` como secciones individuales.

    - Patio con `vertices` → polígono libre tal cual lo posicionó el usuario (la
      restricción de encaje la impone el frontend; aquí no se recorta para no falsear
      la forma). Su `area_m2` es el área ASIGNADA (invariante de capacidad).
    - Patio sin `vertices` → auto-colocado: rectángulo del área asignada en el polo de
      inaccesibilidad del residual (restando los ya colocados para no solaparse).

    El mismo conjunto de definiciones se coloca en cada planta regular (patinejos
    verticales). Si no hay lista de patios, cae a la heurística histórica de patio único.

    Dos fases:
      A) Construye la forma BASE de cada patio (ideal del usuario, área asignada).
      B) Adapta cada base al borde con `conformar_patio` (recorte + relleno hacia dentro).
         Prioridad de colocación: primero los BLOQUEADOS (congelados; los demás se adaptan
         alrededor de ellos), luego por orden de lista (el patio recién movido va el último →
         es el único que cede). Cada patio cede solo ante los de MAYOR prioridad; el de mayor
         prioridad conserva su base. Así, al arrastrar un patio encima de otro, solo se
         reacomoda el movido y los demás quedan intactos. Las efectivas no se pisan y la
         capacidad no cambia (deduce Σ area_m2, orden-independiente). `Patio.geometry` =
         efectiva; `Patio.base` = ideal.
    """
    defs = list(getattr(params, "patios", None) or [])
    if not defs:
        patio = detectar_patio(interior_planta, params)
        return [patio] if patio is not None else []

    lr = params.diseno.luz_recta_patio_min
    # ── Fase A: bases (forma ideal, área asignada) ──────────────────────────────
    bases: list[Optional[tuple[Polygon, float, str, bool]]] = [None] * len(defs)  # (base, area, id, bloqueado)
    residual = interior_planta
    # A1: patios con polígono explícito (respetan la posición del usuario).
    for idx, d in enumerate(defs):
        area = max(0.0, float(getattr(d, "area_m2", 0.0)))
        if area <= 0:
            continue
        verts = getattr(d, "vertices", None)
        if verts and len(verts) >= 3:
            # Huecos: anillos interiores (edificio dentro del patio) → patio en anillo.
            huecos = getattr(d, "huecos", None) or []
            anillos_int = [
                [(float(x), float(y)) for x, y in h]
                for h in huecos if h and len(h) >= 3
            ]
            try:
                geom = _normalizar(Polygon([(float(x), float(y)) for x, y in verts], anillos_int))
            except Exception:
                geom = Polygon()
            if geom.is_empty:
                continue
            geom = _ajustar_area(geom, area)   # área fija: normaliza al área NETA asignada
            bases[idx] = (geom, area, str(getattr(d, "id", "") or ""), bool(getattr(d, "bloqueado", False)))
            residual = _normalizar(residual.difference(geom))
    # A2: patios sin posición → auto-colocado en el residual restante.
    for idx, d in enumerate(defs):
        if bases[idx] is not None:
            continue
        area = max(0.0, float(getattr(d, "area_m2", 0.0)))
        if area <= 0:
            continue
        geom = _rect_area(residual, lr, area)
        if geom is None or geom.is_empty:
            continue
        geom = _normalizar(geom)
        bases[idx] = (geom, area, str(getattr(d, "id", "") or ""), bool(getattr(d, "bloqueado", False)))
        residual = _normalizar(residual.difference(geom))

    # ── Fase B: adaptar cada base al borde según prioridad de colocación ─────────
    # Prioridad: primero los BLOQUEADOS (congelados; los demás se adaptan alrededor de
    # ellos), luego por orden de lista (el patio recién movido va el último → es el único
    # que cede). Cada patio evita las bases de MAYOR prioridad (no las de menor): el de
    # mayor prioridad conserva su forma ideal. La capacidad no cambia (deduce Σ area_m2,
    # orden-independiente). La salida conserva el ORDEN ORIGINAL (ids estables p/ el frontend).
    orden = sorted(
        (idx for idx, b in enumerate(bases) if b is not None),
        key=lambda i: (0 if bases[i][3] else 1, i),   # bloqueado primero, luego orden de lista
    )
    rank = {idx: pos for pos, idx in enumerate(orden)}   # menor rank = mayor prioridad
    zona = footprint if (footprint is not None and not footprint.is_empty) else interior_planta
    resultado: list[Patio] = []
    for idx, b in enumerate(bases):
        if b is None:
            continue
        base_geom, area, pid, bloqueado = b
        anteriores = [
            bb[0] for j, bb in enumerate(bases)
            if bb is not None and j != idx and rank[j] < rank[idx]
        ]
        region = zona
        if anteriores:
            region = zona.difference(unary_union(anteriores))
            if not region.is_valid:
                region = region.buffer(0)
        efectiva, area_ef, cabe = conformar_patio(base_geom, region, area, lr, footprint=zona)
        resultado.append(Patio(
            geometry=efectiva, area_m2=area, luz_recta_m=lr, id=pid,
            base=base_geom, area_efectiva_m2=area_ef, cabe=cabe, bloqueado=bloqueado,
        ))
    return resultado


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
        patios = colocar_patios(i, params, footprint=f)
        for pt in patios:
            i = _normalizar(i.difference(pt.geometry))
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
