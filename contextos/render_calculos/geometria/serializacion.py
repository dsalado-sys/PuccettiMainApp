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
            "normal_azimut": round(l.normal_azimut, 1),
            "orientacion": orientacion_cardinal(l.normal_azimut),
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
    """Una fila por planta (req. 16 y 17).

    DEPRECATED desde iteración 3 — la fuente de verdad es ahora
    `tabla_planta_desde_capacidad` (deriva del cálculo, no de la geometría).
    Se mantiene para compatibilidad con código que aún reciba `EdificioPlurifamiliar`.
    """
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
        })
    return rows


def tabla_por_unidad(edif: EdificioPlurifamiliar) -> list[dict[str, Any]]:
    """Una fila por vivienda (req. 16). Idem deprecation que `tabla_por_planta`."""
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


# ─── Tablas sintéticas iter. 4 — datos reales desde Capacidad ───────────────
def tabla_planta_desde_capacidad(cap, programa_uso=None) -> list[dict[str, Any]]:
    """Tabla por planta derivada del cálculo (muros / circulación / núcleo separados)."""
    rows: list[dict[str, Any]] = []
    muros_est = list(getattr(cap, "muros_estimados_por_planta", [])) or [0.0] * len(cap.nombres_planta)
    patio_pp = list(getattr(cap, "patio_por_planta", [])) or [0.0] * len(cap.nombres_planta)
    local_pp = list(getattr(cap, "local_por_planta", [])) or [0.0] * len(cap.nombres_planta)
    mix_pp = list(getattr(cap, "viviendas_por_tipologia", [])) or [{}] * len(cap.nombres_planta)

    for i, nombre in enumerate(cap.nombres_planta):
        construida_i = cap.construida_por_planta[i]
        util_i = cap.util_por_planta[i]
        muros_i = cap.muros_por_planta[i]
        muros_est_i = muros_est[i] if i < len(muros_est) else 0.0
        circulacion_i = cap.circulacion_por_planta[i]
        nucleo_i = cap.nucleo_por_planta[i]
        patio_i = patio_pp[i] if i < len(patio_pp) else 0.0
        local_i = local_pp[i] if i < len(local_pp) else 0.0
        mix_i = mix_pp[i] if i < len(mix_pp) else {}
        viv_i = cap.viv_por_planta[i]
        tipo_i = cap.tipo_planta[i]

        rows.append({
            "planta": nombre,
            "tipo": tipo_i,
            "viviendas": viv_i,
            "construida_m2": round(construida_i, 2),
            "util_viviendas_m2": round(util_i, 2),
            "muros_m2": round(muros_i, 2),
            "muros_estimados_m2": round(muros_est_i, 2),
            "circulacion_m2": round(circulacion_i, 2),
            "nucleo_m2": round(nucleo_i, 2),
            "patios_m2": round(patio_i, 2),
            "local_m2": round(local_i, 2),
            "mix_tipologia": dict(mix_i),
        })

    # NOTA iter. junio 2026: las "Comunes obligatorias" del uso (apartamentos,
    # hotel-apartamento, hotelero) están ya distribuidas dentro de
    # `circulacion_por_planta[i]` (suma de `pct_circ × construida` + cuota de
    # `area_servicios_obligatorios_m2 / n_plantas_habitables`). No se añade
    # fila aparte: duplicaría m² y la suma de columnas dejaría de cuadrar con
    # `construida_i` (huella).
    return rows


# Usos cuyas unidades se rigen por normativa TURÍSTICA (computable ≠ útil total).
USOS_TURISMO = ("apartamento", "hotel_apartamento", "habitacion")

# Margen de circulación de acceso (vestíbulo/pasillo interior de la unidad) que NO
# computa a efectos turísticos. Coincide con el 15% que `util_objetivo_* = mínimos
# × 1.15` reserva en el Anexo I: las estancias computables ocupan `útil / 1.15` y
# el resto (`útil − útil/1.15`) es la circulación de acceso no computable.
PCT_CIRCULACION_TURISMO = 15.0


# Diámetros mínimos inscribibles por nombre de estancia (m).
# Aproximamos cada habitación como rectángulo 1:1.5 → lado_menor = √(area/1.5).
# Cabe el círculo si lado_menor ≥ diametro_min_m.
_DIAMETROS_MIN_M: dict[str, float] = {
    "salon": 3.00, "salon_cocina": 3.00, "salon_comedor": 3.00,
    "dormitorio_1": 2.70,        # principal
    "dormitorio_2": 2.40,        # secundario doble
    "dormitorio_3": 2.00,        # individual
    "dormitorio_4": 2.00,
    "dormitorio": 2.40,          # estudio (legacy nombre)
    "habitacion": 2.70,          # unidad de alojamiento hotelera (Anexo I.1)
    "espacio_principal": 3.00,   # estudio: salón+cocina+zona dormir integrados
    "cocina": 1.60,
    "bano": 1.20, "bano_1": 1.20, "aseo": 1.20,
    "vestibulo": 1.20,
    "pasillo": 1.00,
    "circulacion_interior": 1.00,
    "estudio": 3.50,
}


def _cabe_diametro(nombre: str, area_target_m2: float) -> tuple[bool, float]:
    """Devuelve (cabe, diametro_min_requerido_m).

    Asume habitación rectangular 1:1.5; lado_menor = √(area/1.5).
    Si la estancia no está en el catálogo de mínimos, devuelve (True, 0.0).
    """
    diam = _DIAMETROS_MIN_M.get(nombre, 0.0)
    if diam <= 0 or area_target_m2 <= 0:
        return True, diam
    lado_menor = (area_target_m2 / 1.5) ** 0.5
    return lado_menor + 1e-6 >= diam, diam


def _slug_principal(params, tipo_unidad: str) -> str:
    """Slug de la tipología principal del proyecto, según el uso."""
    prog = params.programa
    if tipo_unidad == "habitacion":
        t = getattr(prog, "tipologia_habitacion", None)
        return t.value if t is not None else "doble"
    t = getattr(prog, "tipologia_apartamento", None)  # apartamento / hotel_apartamento
    return t.value if t is not None else "doble"


def _estancias_por_unidad_dorms(
    params, n_dorms: int, util_por_unidad: float, programa_uso, slug: str | None = None,
) -> list[dict[str, Any]]:
    """Estancias programadas para una unidad concreta.

    Ramifica por `programa_uso.tipo_unidad`:
    - `vivienda`          → `programa_vivienda(n_dorms, util)` (Anexo I.5).
    - `apartamento`       → `programa_apartamentos(slug, cat, util, grupo)` (A1.3/A1.4).
    - `hotel_apartamento` → `programa_hotel_apartamento(slug, cat, util)` (A1.2).
    - `habitacion`        → `programa_habitacion(slug, cat, util)` (A1.1).

    `slug` es la tipología REAL de esta unidad (mezcla multi-tipología); si falta,
    se usa la tipología principal del proyecto.
    """
    from .programa import programa_vivienda
    from .programa_apartamentos import programa_apartamentos
    from .programa_hotel_apartamento import programa_hotel_apartamento
    from .programa_hotelero import programa_habitacion

    if util_por_unidad <= 0:
        return []

    tipo_unidad = getattr(programa_uso, "tipo_unidad", "vivienda") if programa_uso is not None else "vivienda"
    es_turismo = tipo_unidad in USOS_TURISMO

    # En usos turísticos reservamos el margen de circulación de acceso (no
    # computable): los programas del Anexo I sólo dimensionan estancias
    # computables, que se ajustan al presupuesto `útil / 1.15`. La vivienda
    # gestiona su propia circulación internamente (emite `circulacion_interior`).
    if es_turismo:
        util_computable = util_por_unidad / (1.0 + PCT_CIRCULACION_TURISMO / 100.0)
    else:
        util_computable = util_por_unidad

    if tipo_unidad == "apartamento":
        cat = getattr(params.programa, "categoria_apartamentos", None)
        cat_v = cat.value if cat is not None else "2L"
        grupo = getattr(params.programa, "grupo_apartamentos", None)
        grupo_v = grupo.value if grupo is not None else "edificios"
        tip_v = slug or _slug_principal(params, "apartamento")
        estancias = programa_apartamentos(tip_v, cat_v, util_computable, grupo_v)
    elif tipo_unidad == "hotel_apartamento":
        cat = getattr(params.programa, "categoria_hotel_apartamento", None)
        cat_v = cat.value if cat is not None else "3E"
        tip_v = slug or _slug_principal(params, "hotel_apartamento")
        estancias = programa_hotel_apartamento(tip_v, cat_v, util_computable)
    elif tipo_unidad == "habitacion":
        cat = getattr(params.programa, "categoria_hotelero", None)
        cat_v = cat.value if cat is not None else "hotel_3"
        tip_v = slug or _slug_principal(params, "habitacion")
        estancias = programa_habitacion(tip_v, cat_v, util_computable)
    else:
        salon_open = bool(getattr(params.programa, "salon_cocina_open", False))
        estancias = programa_vivienda(n_dorms, util_por_unidad, salon_open)

    salida: list[dict[str, Any]] = []
    for e in estancias:
        cabe, diam = _cabe_diametro(e.nombre, e.area_target_m2)
        salida.append({
            "nombre": e.nombre,
            "categoria": e.categoria,
            "area_target_m2": round(e.area_target_m2, 2),
            "area_min_m2": round(e.area_min_m2, 2),
            "diametro_min_m": diam,
            "cabe_diametro": cabe,
            # Computa a efectos turísticos todo salvo la circulación de acceso
            # (vestíbulos/pasillos). Los pasillos internos de una estancia ya están
            # descontados porque los mínimos del Anexo son superficies netas.
            "computa_turismo": e.categoria != "circulacion",
        })

    # Circulación de acceso (NO computable) como estancia explícita en turismo, si
    # el programa no la incluyó ya: remanente del útil tras las estancias computables.
    if es_turismo and not any(not e["computa_turismo"] for e in salida):
        computable_total = sum(e["area_target_m2"] for e in salida)
        circ = round(max(0.0, util_por_unidad - computable_total), 2)
        if circ > 0.05:
            cabe, diam = _cabe_diametro("circulacion_interior", circ)
            salida.append({
                "nombre": "circulacion_interior",
                "categoria": "circulacion",
                "area_target_m2": circ,
                "area_min_m2": 0.0,
                "diametro_min_m": diam,
                "cabe_diametro": cabe,
                "computa_turismo": False,
            })
    return salida


def _estancias_por_unidad(params, util_por_unidad: float, programa_uso) -> list[dict[str, Any]]:
    """Wrapper legacy — deriva n_dorms del programa principal."""
    n_dorms = getattr(params.programa, "n_dormitorios", None)
    if n_dorms is None:
        from ..dominio import CATEGORIA_A_NUM_DORMS
        n_dorms = CATEGORIA_A_NUM_DORMS.get(params.programa.categoria_vivienda, 2)
    return _estancias_por_unidad_dorms(params, n_dorms, util_por_unidad, programa_uso)


def tabla_unidad_desde_capacidad(cap, params, programa_uso=None) -> list[dict[str, Any]]:
    """Una fila por unidad — n_dorms y útil REAL por unidad (no promediados).

    Cada unidad se lee de `cap.unidades_por_planta[i]` (lista de (n_dorms, util_m2)
    producida por `calcular_capacidad`). Esto permite mezclas heterogéneas
    (ej. 1 unidad 2d + 1 unidad 1d en una misma planta) sin perder la
    tipología real de cada una.

    Reparto m² por unidad:
    - `util_por_unidad_m2`: útil real de la vivienda (incluye su circulación
      interior, que aparece como una estancia más en el detalle).
    - `muros_por_unidad_m2`: muros del proyecto prorrateados al útil de la
      unidad (los muros perimetrales SÍ pertenecen a la vivienda).
    - `construida_por_unidad_m2` = `util + muros`.
    - La CIRCULACIÓN COMÚN y el NÚCLEO del edificio NO se imputan por unidad
      (son del edificio, viven solo en la tabla por planta).

    - `estancias`: derivadas del Anexo I correspondiente al uso, calculadas
      con el `n_dorms` y `util` específicos de la unidad.
    """
    rows: list[dict[str, Any]] = []
    util_obj = cap.util_objetivo_viv_m2
    tipo_unidad = programa_uso.tipo_unidad if programa_uso is not None else "vivienda"

    total_unidades = cap.n_viviendas_objetivo
    pct_adapt = max(0.0, float(getattr(params.programa, "pct_unidades_adaptadas", 0.0)))
    n_adaptadas = int(total_unidades * pct_adapt / 100.0 + 0.5)
    adaptadas_marcadas = 0

    local_pp = list(getattr(cap, "local_por_planta", [])) or [0.0] * len(cap.nombres_planta)
    pct_local_pb = float(getattr(cap, "pct_local_pb", 0.0))
    unidades_pp = list(getattr(cap, "unidades_por_planta", []))
    tipologias_pp = list(getattr(cap, "tipologias_unidad_por_planta", []))

    for i, nombre_planta in enumerate(cap.nombres_planta):
        viv_i = cap.viv_por_planta[i]
        local_i = local_pp[i] if i < len(local_pp) else 0.0
        unidades_i = unidades_pp[i] if i < len(unidades_pp) else []
        tipologias_i = tipologias_pp[i] if i < len(tipologias_pp) else []

        # Fila "Local" — solo aparece si la planta tiene m² destinados a local.
        if local_i > 0:
            rows.append({
                "planta": nombre_planta,
                "vivienda": "Local",
                "dorms": "—",
                "tipo": "local",
                "util_m2_objetivo": 0.0,
                "construida_por_unidad_m2": round(local_i, 2),
                "util_por_unidad_m2": round(local_i, 2),
                "muros_por_unidad_m2": 0.0,
                "circulacion_por_unidad_m2": 0.0,
                "pct_util_destinado": round(pct_local_pb, 1),
                "adaptada": False,
                "estancias": [],
            })

        if viv_i == 0 or not unidades_i:
            continue

        util_i_consumido = sum(u for _, u in unidades_i) or 1.0
        muros_i = cap.muros_por_planta[i]

        for j, (n_dorms_u, util_u) in enumerate(unidades_i):
            letra = chr(ord('A') + j) if j < 26 else f"#{j+1}"
            slug_u = tipologias_i[j] if j < len(tipologias_i) else None
            es_adapt = adaptadas_marcadas < n_adaptadas
            if es_adapt:
                adaptadas_marcadas += 1
            # Solo los MUROS perimetrales se prorratean a la unidad. La
            # circulación común y el núcleo son del edificio (tabla por planta).
            factor = util_u / util_i_consumido
            muros_u = muros_i * factor
            construida_u = util_u + muros_u

            estancias = _estancias_por_unidad_dorms(
                params, n_dorms_u, util_u, programa_uso, slug_u
            )

            # Circulación interior (intrínseca) de la unidad = útil de la unidad
            # menos la suma de las estancias que NO son circulación. En vivienda
            # coincide con la estancia "circulacion_interior" (15% del útil); en
            # apartamentos/hoteles es el remanente del útil tras las estancias.
            # Superficie computable (turismo) = estancias que computan; la
            # circulación de acceso (vestíbulo/pasillo) NO computa. En vivienda la
            # estancia `circulacion_interior` (15% del útil) también se excluye.
            computable_u = sum(
                e["area_target_m2"] for e in estancias if e.get("computa_turismo", e.get("categoria") != "circulacion")
            )
            circ_interior_u = max(0.0, util_u - computable_u)

            rows.append({
                "planta": nombre_planta,
                "vivienda": f"V{i+1}{letra}",
                "dorms": n_dorms_u,
                "tipologia": slug_u,
                "tipo": tipo_unidad,
                "util_m2_objetivo": util_obj,
                "construida_por_unidad_m2": round(construida_u, 2),
                "util_por_unidad_m2": round(util_u, 2),
                "computable_turismo_por_unidad_m2": round(computable_u, 2),
                "muros_por_unidad_m2": round(muros_u, 2),
                "circulacion_interior_por_unidad_m2": round(circ_interior_u, 2),
                "adaptada": es_adapt,
                "estancias": estancias,
            })
    return rows
