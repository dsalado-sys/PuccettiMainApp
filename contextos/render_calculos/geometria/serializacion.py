"""Serialización del edificio plurifamiliar a JSON (§2.5/§2.7).

Adaptado desde `Modulos/puccetti-app/puccetti/serializacion.py`. Cambios:
- Las tablas de pandas se reemplazan por listas de dicts puros (sin pandas):
  el frontend no necesita DataFrame, y así evitamos arrastrar pandas al
  motor del módulo.
- `lados_a_dict` produce la lista de lados clasificados (fachada/medianera +
  azimut + orientación cardinal) que el canvas necesita para etiquetar
  orientaciones.
- Las tablas se derivan del cálculo de capacidad (`*_desde_capacidad`), no de
  una geometría de polígonos.
"""
from __future__ import annotations
from typing import Any

from shapely.geometry import Polygon

from .parcelas import LadoParcela, orientacion_cardinal


def ring(geom: Polygon, tol: float = 0.03) -> list[list[float]]:
    """Anillo exterior como lista [[x,y],...] redondeado a cm."""
    if geom is None or geom.is_empty:
        return []
    g = geom.simplify(tol, preserve_topology=True)
    if g.is_empty or not hasattr(g, "exterior"):
        g = geom
    return [[round(x, 2), round(y, 2)] for x, y in g.exterior.coords]


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


# ─── Tablas sintéticas iter. 4 — datos reales desde Capacidad ───────────────
def tabla_planta_desde_capacidad(cap, programa_uso=None) -> list[dict[str, Any]]:
    """Tabla por planta derivada del cálculo (muros / circulación / núcleo separados)."""
    rows: list[dict[str, Any]] = []
    muros_est = list(getattr(cap, "muros_estimados_por_planta", [])) or [0.0] * len(cap.nombres_planta)
    muros_int_pp = list(getattr(cap, "muros_interior_por_planta", [])) or [0.0] * len(cap.nombres_planta)
    patio_pp = list(getattr(cap, "patio_por_planta", [])) or [0.0] * len(cap.nombres_planta)
    local_pp = list(getattr(cap, "local_por_planta", [])) or [0.0] * len(cap.nombres_planta)
    otros_pp = list(getattr(cap, "otros_por_planta", [])) or [0.0] * len(cap.nombres_planta)
    comunes_pp = list(getattr(cap, "usos_comunes_por_planta", [])) or [0.0] * len(cap.nombres_planta)
    mix_pp = list(getattr(cap, "viviendas_por_tipologia", [])) or [{}] * len(cap.nombres_planta)

    for i, nombre in enumerate(cap.nombres_planta):
        construida_i = cap.construida_por_planta[i]
        util_i = cap.util_por_planta[i]
        muros_i = cap.muros_por_planta[i]
        muros_int_i = muros_int_pp[i] if i < len(muros_int_pp) else 0.0
        muros_est_i = muros_est[i] if i < len(muros_est) else 0.0
        circulacion_i = cap.circulacion_por_planta[i]
        nucleo_i = cap.nucleo_por_planta[i]
        patio_i = patio_pp[i] if i < len(patio_pp) else 0.0
        local_i = local_pp[i] if i < len(local_pp) else 0.0
        otros_i = otros_pp[i] if i < len(otros_pp) else 0.0
        comunes_i = comunes_pp[i] if i < len(comunes_pp) else 0.0
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
            "muros_interior_m2": round(muros_int_i, 2),
            "muros_estimados_m2": round(muros_est_i, 2),
            "circulacion_m2": round(circulacion_i, 2),
            "nucleo_m2": round(nucleo_i, 2),
            "patios_m2": round(patio_i, 2),
            "local_m2": round(local_i, 2),
            "otros_m2": round(otros_i, 2),
            "usos_comunes_m2": round(comunes_i, 2),
            "mix_tipologia": dict(mix_i),
        })

    # NOTA iter. junio 2026: las "Comunes obligatorias" del uso (apartamentos,
    # hotelero) están ya distribuidas dentro de
    # `circulacion_por_planta[i]` (suma de `pct_circ × construida` + cuota de
    # `area_servicios_obligatorios_m2 / n_plantas_habitables`). No se añade
    # fila aparte: duplicaría m².
    #
    # El patio interior NO computa como construido (vacío a cielo abierto): la
    # columna `construida_m2` es la huella menos el patio, así que la identidad
    # por planta es `construida = útil + muros + muros_interior + circulación +
    # núcleo + local + otros + usos comunes` y la columna `patios_m2` queda fuera
    # de esa suma (se reporta aparte). `muros` es solo perímetro/edificio y
    # `muros_interior` la tabiquería de las unidades; otros y usos comunes solo
    # son > 0 en planta baja.
    return rows


# Usos cuyas unidades se rigen por normativa TURÍSTICA (computable ≠ útil total).
USOS_TURISMO = ("apartamento", "habitacion")

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
    "espacio_principal": 3.00,   # estudio: salón + zona dormir (cocina y baño aparte)
    "cocina": 1.60,
    "bano": 1.20, "bano_1": 1.20, "bano_2": 1.20, "aseo": 1.20, "aseo_2": 1.20,
    "vestibulo": 1.20,
    "pasillo": 1.00,
    "circulacion_interior": 1.00,
    "estudio": 3.50,
}


def _nivel_diametro(nombre: str, area_target_m2: float) -> tuple[str, float]:
    """Nivel de holgura para inscribir el círculo mínimo en la estancia.

    Devuelve (nivel, diametro_min_requerido_m) con nivel ∈ {"ok", "amarillo", "rojo"}:

    - "rojo":     ni siquiera en planta cuadrada cabe el círculo. Para contener un
                  círculo de Ø=D un rectángulo necesita ambos lados ≥ D, luego
                  área ≥ D². Si `área < D²` es **imposible** geométricamente.
    - "amarillo": el círculo cabe en planta cuadrada, pero no con la proporción
                  realista 1:1.5 (lado menor = √(área/1.5) < D). Fallo "blando":
                  depende de la forma que adopte la estancia.
    - "ok":       cabe con holgura asumiendo la proporción 1:1.5.

    Si la estancia no está en el catálogo de mínimos, devuelve ("ok", 0.0).
    """
    diam = _DIAMETROS_MIN_M.get(nombre, 0.0)
    if diam <= 0 or area_target_m2 <= 0:
        return "ok", diam
    if area_target_m2 + 1e-6 < diam * diam:            # ni en planta cuadrada
        return "rojo", diam
    lado_menor = (area_target_m2 / 1.5) ** 0.5         # proporción realista 1:1.5
    if lado_menor + 1e-6 < diam:
        return "amarillo", diam
    return "ok", diam


# Etiquetas legibles para el detalle por unidad (la clave es el nombre máquina
# que emiten los programas del Anexo I). Los dormitorios se numeran aparte.
_ETIQUETAS_ESTANCIA: dict[str, str] = {
    "salon": "Salón",
    "salon_cocina": "Salón-cocina",
    "salon_comedor": "Salón-comedor",
    "cocina": "Cocina",
    "espacio_principal": "Espacio principal",
    "habitacion": "Habitación",
    "estudio": "Estudio",
    "dormitorio": "Dormitorio",
    "bano": "Baño",
    "bano_1": "Baño 1",
    "bano_2": "Baño 2",
    "aseo": "Aseo",
    "aseo_2": "Aseo 2",
    "vestibulo": "Vestíbulo",
    "circulacion_interior": "Circulación interior",
}


def _etiqueta_estancia(nombre: str) -> str:
    """Etiqueta legible de una estancia para el detalle por unidad.

    Con ≥5 plazas los dos baños obligatorios llegan como `bano_1`/`bano_2` y se
    muestran "Baño 1"/"Baño 2". Los dormitorios se numeran (`dormitorio_2` →
    "Dormitorio 2"); el resto sale del diccionario o, por defecto, capitaliza
    sustituyendo guiones bajos por espacios.
    """
    if nombre in _ETIQUETAS_ESTANCIA:
        return _ETIQUETAS_ESTANCIA[nombre]
    if nombre.startswith("dormitorio_"):
        return "Dormitorio " + nombre.split("_", 1)[1]
    return nombre.replace("_", " ").capitalize()


def _slug_principal(params, tipo_unidad: str) -> str:
    """Slug de la tipología principal del proyecto, según el uso."""
    prog = params.programa
    if tipo_unidad == "habitacion":
        t = getattr(prog, "tipologia_habitacion", None)
        return t.value if t is not None else "doble"
    t = getattr(prog, "tipologia_apartamento", None)  # apartamento turístico
    return t.value if t is not None else "doble"


def _estancias_por_unidad_dorms(
    params, n_dorms: int, util_por_unidad: float, programa_uso, slug: str | None = None,
    cfg=None, *, es_adaptada: bool = False, modo: str = "total", factor: float = 1.0,
) -> list[dict[str, Any]]:
    """Estancias programadas para una unidad concreta.

    Ramifica por `programa_uso.tipo_unidad`:
    - `vivienda`          → `programa_vivienda(n_dorms, util)` (Anexo I.5).
    - `apartamento`       → `programa_apartamentos(slug, cat, util, grupo)` (A1.3/A1.4).
    - `habitacion`        → `programa_habitacion(slug, cat, util)` (A1.1).

    `slug` es la tipología REAL de esta unidad (mezcla multi-tipología); si falta,
    se usa la tipología principal del proyecto.

    `cfg` (§3.8) son los mínimos/política EDITADOS del uso activo (un `Programa*Config`
    construido desde BBDD por `_sincronizar_minimos`); su tipo concuerda con
    `tipo_unidad`. Si es `None`, cada rama usa el default inmutable del Anexo.
    """
    from .combinador_tipologias import es_slug_combo, slug_a_combo
    from .programa import (
        CONFIG_DEFAULT as CFG_VIV, programa_vivienda, programa_vivienda_combo,
    )
    from .programa_apartamentos import (
        CONFIG_DEFAULT as CFG_APT, programa_apartamentos, programa_apartamentos_combo,
    )
    from .programa_hotelero import CONFIG_DEFAULT as CFG_HOT, programa_habitacion

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
        cfg_apt = cfg if cfg is not None else CFG_APT
        cat = getattr(params.programa, "categoria_apartamentos", None)
        cat_v = cat.value if cat is not None else "2L"
        grupo = getattr(params.programa, "grupo_apartamentos", None)
        grupo_v = grupo.value if grupo is not None else "edificios"
        tip_v = slug or _slug_principal(params, "apartamento")
        # §2.5 paradigma nuevo: si el slug codifica una combinación de dormitorios
        # ("doble*1+individual*1"), el programa lo genera por composición; un slug
        # de ocupación heredado ("doble") sigue la vía monodormitorio.
        if es_slug_combo(tip_v):
            estancias = programa_apartamentos_combo(slug_a_combo(tip_v), cat_v, util_computable, grupo_v, cfg_apt)
        else:
            estancias = programa_apartamentos(tip_v, cat_v, util_computable, grupo_v, cfg_apt)
    elif tipo_unidad == "habitacion":
        cfg_hot = cfg if cfg is not None else CFG_HOT
        cat = getattr(params.programa, "categoria_hotelero", None)
        cat_v = cat.value if cat is not None else "hotel_3"
        tip_v = slug or _slug_principal(params, "habitacion")
        estancias = programa_habitacion(tip_v, cat_v, util_computable, cfg_hot)
    else:
        cfg_viv = cfg if cfg is not None else CFG_VIV
        salon_open = bool(getattr(params.programa, "salon_cocina_open", False))
        # §2.5 paradigma nuevo: si el slug codifica una combinación de dormitorios,
        # la vivienda se genera por composición (individual/doble); un slug
        # heredado (n_dorms como "2") sigue la vía int-based.
        if slug and es_slug_combo(slug):
            estancias = programa_vivienda_combo(slug_a_combo(slug), util_por_unidad, salon_open, cfg_viv)
        else:
            estancias = programa_vivienda(n_dorms, util_por_unidad, salon_open, cfg_viv)

    salida: list[dict[str, Any]] = []
    # Accesibilidad (DB-SUA): en una unidad adaptada se agrandan por el factor del
    # uso las estancias correspondientes (modo total: toda la unidad; modo parcial:
    # solo dormitorio/habitación + baño/aseo).
    from .accesibilidad import estancia_se_agranda

    for e in estancias:
        area_target = e.area_target_m2
        if es_adaptada and factor > 1.0 and estancia_se_agranda(e.nombre, modo):
            area_target = area_target * factor
        nivel, diam = _nivel_diametro(e.nombre, area_target)
        salida.append({
            "nombre": e.nombre,
            "etiqueta": _etiqueta_estancia(e.nombre),
            "categoria": e.categoria,
            "area_target_m2": round(area_target, 2),
            "area_min_m2": round(e.area_min_m2, 2),
            "diametro_min_m": diam,
            "cabe_diametro": nivel == "ok",
            "nivel_diametro": nivel,
            # Computa a efectos turísticos todo salvo la circulación de acceso
            # (vestíbulos/pasillos). Los pasillos internos de una estancia ya están
            # descontados porque los mínimos del Anexo son superficies netas.
            "computa_turismo": e.categoria != "circulacion",
        })

    # Circulación de acceso (NO computable) como estancia explícita en turismo, si
    # el programa no la incluyó ya: remanente del útil tras las estancias computables.
    # En una unidad adaptada lo computable ya está agrandado por el factor; su
    # circulación es el margen normativo SOBRE ese computable (la unidad crece de
    # forma coherente: en modo total, ~factor; el remanente del slot estándar la
    # absorbería incorrectamente).
    if es_turismo and not any(not e["computa_turismo"] for e in salida):
        computable_total = sum(e["area_target_m2"] for e in salida)
        if es_adaptada and factor > 1.0:
            circ = round(computable_total * PCT_CIRCULACION_TURISMO / 100.0, 2)
        else:
            circ = round(max(0.0, util_por_unidad - computable_total), 2)
        if circ > 0.05:
            nivel, diam = _nivel_diametro("circulacion_interior", circ)
            salida.append({
                "nombre": "circulacion_interior",
                "etiqueta": _etiqueta_estancia("circulacion_interior"),
                "categoria": "circulacion",
                "area_target_m2": circ,
                "area_min_m2": 0.0,
                "diametro_min_m": diam,
                "cabe_diametro": nivel == "ok",
                "nivel_diametro": nivel,
                "computa_turismo": False,
            })
    return salida


def tabla_unidad_desde_capacidad(cap, params, programa_uso=None, cfg=None) -> list[dict[str, Any]]:
    """Una fila por unidad — n_dorms y útil REAL por unidad (no promediados).

    Cada unidad se lee de `cap.unidades_por_planta[i]` (lista de (n_dorms, util_m2)
    producida por `calcular_capacidad`). Esto permite mezclas heterogéneas
    (ej. 1 unidad 2d + 1 unidad 1d en una misma planta) sin perder la
    tipología real de cada una.

    Reparto m² por unidad:
    - `util_por_unidad_m2`: útil real de la vivienda (incluye su circulación
      interior, que aparece como una estancia más en el detalle).
    - `muros_por_unidad_m2`: muros de PERÍMETRO/edificio del proyecto prorrateados
      al útil de la unidad (fachadas/medianeras/separaciones SÍ pertenecen a la
      vivienda).
    - `muros_interior_por_unidad_m2`: TABIQUERÍA interior de la unidad (cálculo de
      unidad, % del útil destinado a viviendas; 0 si pct_muros_interior = 0).
    - `construida_por_unidad_m2` = `util + muros + muros_interior`.
    - La CIRCULACIÓN COMÚN y el NÚCLEO del edificio NO se imputan por unidad
      (son del edificio, viven solo en la tabla por planta).

    - `estancias`: derivadas del Anexo I correspondiente al uso, calculadas
      con el `n_dorms` y `util` específicos de la unidad.
    """
    rows: list[dict[str, Any]] = []
    util_obj = cap.util_objetivo_viv_m2
    tipo_unidad = programa_uso.tipo_unidad if programa_uso is not None else "vivienda"

    from .accesibilidad import factor_agrandado

    # Accesibilidad (DB-SUA): nº y modo ya resueltos en la capacidad por tramos
    # (0 en vivienda). Las `n_adaptadas` primeras unidades —recorridas PB primero—
    # se marcan como adaptadas. En modo TOTAL su útil ya viene agrandado en
    # `unidades_por_planta` (repack geométrico), así que las estancias salen mayores
    # SIN reescalar aquí (factor=1, evita doble conteo). En modo PARCIAL (edificios
    # diminutos, sin repack) el agrandado de dormitorio+aseo se aplica aquí.
    n_adaptadas = int(getattr(cap, "n_unidades_adaptadas", 0))
    modo_adapt = getattr(cap, "modo_adaptacion", "total")
    factor_adapt = factor_agrandado(tipo_unidad) if modo_adapt == "parcial" else 1.0
    adaptadas_marcadas = 0

    local_pp = list(getattr(cap, "local_por_planta", [])) or [0.0] * len(cap.nombres_planta)
    pct_local_pb = float(getattr(cap, "pct_local_pb", 0.0))
    otros_pp = list(getattr(cap, "otros_por_planta", [])) or [0.0] * len(cap.nombres_planta)
    pct_otros_pb = float(getattr(cap, "pct_otros_pb", 0.0))
    comunes_pp = list(getattr(cap, "usos_comunes_por_planta", [])) or [0.0] * len(cap.nombres_planta)
    pct_usos_comunes_pb = float(getattr(cap, "pct_usos_comunes_pb", 0.0))
    unidades_pp = list(getattr(cap, "unidades_por_planta", []))
    tipologias_pp = list(getattr(cap, "tipologias_unidad_por_planta", []))
    muros_int_pp = list(getattr(cap, "muros_interior_por_planta", [])) or [0.0] * len(cap.nombres_planta)

    for i, nombre_planta in enumerate(cap.nombres_planta):
        viv_i = cap.viv_por_planta[i]
        local_i = local_pp[i] if i < len(local_pp) else 0.0
        otros_i = otros_pp[i] if i < len(otros_pp) else 0.0
        comunes_i = comunes_pp[i] if i < len(comunes_pp) else 0.0
        unidades_i = unidades_pp[i] if i < len(unidades_pp) else []
        tipologias_i = tipologias_pp[i] if i < len(tipologias_pp) else []

        # Filas de reserva de PB (local / otros / usos comunes) — cada una aparece
        # solo si la planta tiene m² destinados a ese uso. Sin estancias y sin
        # circulación: son superficie útil de PB apartada para uso no residencial.
        for etiqueta, tipo_reserva, m2_reserva, pct_reserva in (
            ("Local", "local", local_i, pct_local_pb),
            ("Otros", "otros", otros_i, pct_otros_pb),
            ("Usos comunes", "usos_comunes", comunes_i, pct_usos_comunes_pb),
        ):
            if m2_reserva > 0:
                rows.append({
                    "planta": nombre_planta,
                    "vivienda": etiqueta,
                    "dorms": "—",
                    "tipo": tipo_reserva,
                    "util_m2_objetivo": 0.0,
                    "construida_por_unidad_m2": round(m2_reserva, 2),
                    "util_por_unidad_m2": round(m2_reserva, 2),
                    "muros_por_unidad_m2": 0.0,
                    "muros_interior_por_unidad_m2": 0.0,
                    "circulacion_por_unidad_m2": 0.0,
                    "pct_util_destinado": round(pct_reserva, 1),
                    "adaptada": False,
                    "estancias": [],
                })

        if viv_i == 0 or not unidades_i:
            continue

        util_i_consumido = sum(u for _, u in unidades_i) or 1.0
        muros_i = cap.muros_por_planta[i]
        muros_int_i = muros_int_pp[i] if i < len(muros_int_pp) else 0.0

        for j, (n_dorms_u, util_u) in enumerate(unidades_i):
            letra = chr(ord('A') + j) if j < 26 else f"#{j+1}"
            slug_u = tipologias_i[j] if j < len(tipologias_i) else None
            es_adapt = adaptadas_marcadas < n_adaptadas
            if es_adapt:
                adaptadas_marcadas += 1
            # La unidad lleva su cuota de MUROS perimetrales del edificio
            # (prorrateada al útil) MÁS su propia TABIQUERÍA interior. La
            # circulación común y el núcleo son del edificio (tabla por planta).
            prorr = util_u / util_i_consumido
            muros_u = muros_i * prorr
            muros_int_u = muros_int_i * prorr

            estancias = _estancias_por_unidad_dorms(
                params, n_dorms_u, util_u, programa_uso, slug_u, cfg,
                es_adaptada=es_adapt, modo=modo_adapt, factor=factor_adapt,
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
            # Una unidad adaptada es más grande: su útil reportado es la suma de
            # sus estancias (ya agrandadas), no el slot estándar de la planta.
            util_unidad = (
                sum(e["area_target_m2"] for e in estancias)
                if (es_adapt and factor_adapt > 1.0) else util_u
            )
            circ_interior_u = max(0.0, util_unidad - computable_u)
            construida_u = util_unidad + muros_u + muros_int_u

            rows.append({
                "planta": nombre_planta,
                "vivienda": f"V{i+1}{letra}",
                "dorms": n_dorms_u,
                "tipologia": slug_u,
                "tipo": tipo_unidad,
                "util_m2_objetivo": util_obj,
                "construida_por_unidad_m2": round(construida_u, 2),
                "util_por_unidad_m2": round(util_unidad, 2),
                "computable_turismo_por_unidad_m2": round(computable_u, 2),
                "muros_por_unidad_m2": round(muros_u, 2),
                "muros_interior_por_unidad_m2": round(muros_int_u, 2),
                "circulacion_interior_por_unidad_m2": round(circ_interior_u, 2),
                "adaptada": es_adapt,
                "estancias": estancias,
            })
    return rows
