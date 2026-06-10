"""Derivación del nº de viviendas a partir de la EDIFICABILIDAD.

Iteración 5: diferenciación PB / planta tipo + multi-tipología + local en PB.

Planta baja (idx_visual == 0, tipo "regular"):
    construida_i  = huella_planta (ya con retranqueos + ocupación)
    muros_i       = construida_i × pct_muros / 100
    circ_i_pb     = construida_i × pct_circulacion_pb / 100
    nucleo_i      = construida_i × pct_nucleo / 100
    patio_i       = min(area_patio_min, construida_i × 0.20)
    local_i       = (construida_i − muros_i − circ_i_pb − nucleo_i − patio_i) × pct_local_pb / 100
    util_unidades_pb = construida_i − muros_i − circ_i_pb − nucleo_i − patio_i − local_i − comunes_planta

Planta tipo / ático:
    Mismo esquema pero con pct_circulacion_tipo, sin local. El patio se
    descuenta también (es vertical) con el mismo área normativa.

Sótanos: viv=0 forzado. Ático: si computa_edif=False no consume techo.
Reparto multi-tipología: si hay tipologías_extra, se asigna ≥1 unidad de
cada y se rellena el sobrante con la más pequeña.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .config import Parametros
from .programa import reparto_multi_tipologia, util_maximo
from .programa_uso import TipologiaUnidadDescriptor, reparto_multi_tipologia_generico


def _truncar(x: float) -> int:
    """Política de redondeo del módulo: hacia abajo (truncar a entero)."""
    return max(0, int(x))


@dataclass
class Capacidad:
    superficie_parcela_m2: float
    coeficiente_edificabilidad: float
    edificabilidad_m2: float                # = parcela × coeficiente (KPI)
    ocupacion_maxima: float
    n_plantas_solicitadas: int
    n_plantas_edificables: int
    huella_m2: float
    ocupacion_area_m2: float
    huella_efectiva_m2: float
    construida_prevista_m2: float
    factor_limitante: str
    n_dormitorios: int
    util_objetivo_viv_m2: float
    util_planta_disponible_m2: float
    viv_por_planta_objetivo: int
    n_viviendas_objetivo: int
    pct_muros: float
    pct_circulacion_pb: float
    pct_circulacion_tipo: float
    pct_nucleo: float
    pct_muros_normativo: float = 20.0
    pct_local_pb: float = 0.0
    viv_por_planta: list[int] = field(default_factory=list)
    construida_por_planta: list[float] = field(default_factory=list)
    util_por_planta: list[float] = field(default_factory=list)
    muros_por_planta: list[float] = field(default_factory=list)
    muros_estimados_por_planta: list[float] = field(default_factory=list)
    circulacion_por_planta: list[float] = field(default_factory=list)
    nucleo_por_planta: list[float] = field(default_factory=list)
    patio_por_planta: list[float] = field(default_factory=list)
    local_por_planta: list[float] = field(default_factory=list)
    tipo_planta: list[str] = field(default_factory=list)
    nombres_planta: list[str] = field(default_factory=list)
    viviendas_por_tipologia: list[dict[str, int]] = field(default_factory=list)
    # Detalle por unidad de cada planta: lista [(n_dorms, util_m2), ...].
    # Permite a `tabla_unidad_desde_capacidad` generar una fila por unidad con
    # su tipología y útil real (sin promediar). Las plantas sin viviendas
    # (sotano, ático no admitido…) guardan lista vacía.
    unidades_por_planta: list[list[tuple[int, float]]] = field(default_factory=list)
    # Slug de tipología de cada unidad (paralelo a `unidades_por_planta`). Permite
    # a la serialización regenerar las estancias por unidad cuando la planta mezcla
    # varias tipologías (apartamento 1d+2d, hotel doble+triple, …).
    tipologias_unidad_por_planta: list[list[str]] = field(default_factory=list)
    area_servicios_comunes_m2: float = 0.0
    n_plantas_habitables: int = 0
    construida_computable_m2: float = 0.0


def _nombre_planta(idx_visual: int, tipo: str) -> str:
    if tipo == "sotano":
        return "S1"
    if tipo == "atico":
        return "Ático"
    return "PB" if idx_visual == 0 else f"P{idx_visual}"


def calcular_capacidad(
    envolvente,
    params: Parametros,
    *,
    util_objetivo_por_unidad: float | None = None,
    area_servicios_comunes_m2: float = 0.0,
    descriptores_tipologia: list[TipologiaUnidadDescriptor] | None = None,
) -> Capacidad:
    """Deriva la capacidad numérica del edificio (sin geometría de unidades).

    Reparto por planta (en orden de prioridad):
    - `descriptores_tipologia` con >1 entrada → mezcla multi-tipología
      use-agnóstica (`reparto_multi_tipologia_generico`); cada unidad lleva su
      propia tipología (slug).
    - `descriptores_tipologia` con 1 entrada → tantas unidades como quepan al
      `util_objetivo` de esa tipología.
    - `descriptores_tipologia is None` → vía int-based histórica (preview de
      vivienda, usa `tipologias_extra` del motor).
    """
    parcela_area = envolvente.parcela.area
    urb = params.urbanismo

    pct_muros = max(0.0, min(80.0, float(params.diseno.pct_muros)))
    pct_circ_pb = max(0.0, min(50.0, float(params.diseno.pct_circulacion_pb)))
    pct_circ_tipo = max(0.0, min(50.0, float(params.diseno.pct_circulacion_tipo)))
    pct_nucl = max(0.0, min(30.0, float(params.diseno.pct_nucleo)))
    pct_muros_normativo = max(0.0, min(80.0, float(getattr(params.diseno, "pct_muros_normativo", 20.0))))
    pct_local_pb = max(0.0, min(100.0, float(getattr(params.programa, "pct_local_pb", 0.0))))
    tipologias_extra = list(getattr(params.programa, "tipologias_extra", []) or [])
    # Verificación de no quedar útil: usamos el % de circulación más exigente.
    pct_total_max = pct_muros + max(pct_circ_pb, pct_circ_tipo) + pct_nucl

    huella = envolvente.plantas[0].footprint.area if envolvente.plantas else parcela_area
    coef = urb.coeficiente_edificabilidad
    ocup_area = urb.ocupacion_maxima * parcela_area
    if getattr(urb, "usar_coeficiente_edificabilidad", True):
        edificabilidad_m2 = coef * parcela_area
    else:
        edificabilidad_m2 = ocup_area * max(1, urb.n_plantas_max)
    huella_efectiva = min(huella, ocup_area) if ocup_area > 0 else huella

    n_dorms = params.programa.n_dormitorios
    if descriptores_tipologia:
        util_viv = descriptores_tipologia[0].util_objetivo
    elif util_objetivo_por_unidad is not None:
        util_viv = util_objetivo_por_unidad
    else:
        util_viv = util_maximo(n_dorms)

    n_plantas_solicitadas = max(1, len(envolvente.plantas) or params.programa.n_plantas)
    plantas = list(envolvente.plantas)

    n_plantas_habitables = sum(1 for p in plantas if p.tipo != "sotano")
    if n_plantas_habitables <= 0:
        n_plantas_habitables = 1

    descuento_por_planta = area_servicios_comunes_m2 / n_plantas_habitables

    construida_computable_total = sum(p.footprint.area for p in plantas if p.computa_edif)
    n_plantas_edif_max = (
        max(1, int(edificabilidad_m2 // huella_efectiva)) if huella_efectiva else 1
    )

    # Recorte por techo: si la suma de plantas computables excede, las de arriba
    # quedan sin admitir (generan 0 unidades).
    excede_techo = construida_computable_total > edificabilidad_m2 + 1e-3
    techo_restante = edificabilidad_m2
    plantas_admitidas_idx: set[int] = set()
    for i, p in enumerate(plantas):
        if not p.computa_edif:
            plantas_admitidas_idx.add(i)
            continue
        if techo_restante + 1e-3 >= p.footprint.area:
            plantas_admitidas_idx.add(i)
            techo_restante -= p.footprint.area

    factor_limitante = "ninguno (cumple holgado)"
    if pct_total_max >= 100.0:
        factor_limitante = "porcentajes (no queda útil)"
    elif excede_techo:
        factor_limitante = "edificabilidad"
    elif params.programa.n_plantas > urb.n_plantas_max:
        factor_limitante = "altura (nº plantas)"
    elif huella > ocup_area + 1e-3:
        factor_limitante = "ocupación"

    viv_por_planta: list[int] = []
    construida_por_planta: list[float] = []
    util_por_planta: list[float] = []
    muros_por_planta: list[float] = []
    muros_estimados_por_planta: list[float] = []
    circulacion_por_planta: list[float] = []
    nucleo_por_planta: list[float] = []
    patio_por_planta: list[float] = []
    local_por_planta: list[float] = []
    tipo_planta: list[str] = []
    nombres_planta: list[str] = []
    viviendas_por_tipologia: list[dict[str, int]] = []
    unidades_por_planta: list[list[tuple[int, float]]] = []
    tipologias_unidad_por_planta: list[list[str]] = []

    util_total = 0.0
    construida_total = 0.0
    construida_computable_efectiva = 0.0
    idx_visual = 0
    area_patio_norm = float(getattr(params.diseno, "area_patio_min", 12.0))

    salon_open = bool(getattr(params.programa, "salon_cocina_open", False))
    # Tipologías para reparto: la principal (n_dorms) primero, luego las extra
    # (deduplicadas más abajo en reparto_multi_tipologia).
    tipologias_set = [n_dorms] + [int(t) for t in tipologias_extra]

    es_primera_regular = True

    for i, p in enumerate(plantas):
        construida_i = p.footprint.area
        construida_total += construida_i
        admitida = i in plantas_admitidas_idx
        if p.computa_edif and admitida:
            construida_computable_efectiva += construida_i

        muros_i = construida_i * pct_muros / 100.0
        muros_est_i = construida_i * pct_muros_normativo / 100.0
        nucl_i = construida_i * pct_nucl / 100.0
        patio_i = min(area_patio_norm, construida_i * 0.20) if area_patio_norm > 0 else 0.0
        local_i = 0.0
        viv_i = 0
        util_i = 0.0
        util_disponible_planta = 0.0   # útil neto de la planta (lo que se reparte)
        mix_i: dict[str, int] = {}
        unidades_i: list[tuple[int, float]] = []
        tipologias_i: list[str] = []

        if p.tipo == "sotano":
            circ_i = 0.0
            patio_i = 0.0
            nombre = _nombre_planta(0, "sotano")
        else:
            # PB: usa pct_circulacion_pb + descuenta local. Resto (planta tipo /
            # ático): usa pct_circulacion_tipo, sin local.
            es_pb = es_primera_regular and p.tipo == "regular"
            pct_circ_planta = pct_circ_pb if es_pb else pct_circ_tipo
            circ_i = construida_i * pct_circ_planta / 100.0

            util_bruto_i = max(
                0.0,
                construida_i - muros_i - circ_i - nucl_i - patio_i - descuento_por_planta,
            )
            if es_pb:
                local_i = util_bruto_i * pct_local_pb / 100.0
                util_disponible_i = util_bruto_i - local_i
                es_primera_regular = False
            else:
                util_disponible_i = util_bruto_i

            # Útil neto de la planta (independiente de cuántas unidades quepan):
            # construida(huella) = útil + muros + circ + núcleo + patio + local
            # (+ comunes obligatorias, que se muestran en su fila aparte).
            util_disponible_planta = util_disponible_i
            util_total += util_disponible_planta

            if admitida and util_disponible_i > 0 and util_viv > 0:
                # Reparto. Prioridad: descriptores (use-agnóstico) → vía
                # int-based histórica (preview de vivienda).
                if descriptores_tipologia:
                    if len(descriptores_tipologia) > 1:
                        seleccion = reparto_multi_tipologia_generico(
                            util_disponible_i, descriptores_tipologia
                        )
                        unidades_i = [(d.n_dorms_label, u) for d, u in seleccion]
                        tipologias_i = [d.slug for d, _ in seleccion]
                    else:
                        d0 = descriptores_tipologia[0]
                        n_viv = (
                            _truncar(util_disponible_i / d0.util_objetivo)
                            if d0.util_objetivo > 0 else 0
                        )
                        unidades_i = [(d0.n_dorms_label, d0.util_objetivo) for _ in range(n_viv)]
                        tipologias_i = [d0.slug for _ in range(n_viv)]
                elif len(set(tipologias_set)) > 1:
                    unidades_i = reparto_multi_tipologia(
                        util_disponible_i, tipologias_set, salon_open
                    )
                    tipologias_i = [str(n) for n, _ in unidades_i]
                else:
                    n_viv = _truncar(util_disponible_i / util_viv)
                    unidades_i = [(n_dorms, util_viv) for _ in range(n_viv)]
                    tipologias_i = [str(n_dorms) for _ in range(n_viv)]

                viv_i = len(unidades_i)
                util_i = sum(u for _, u in unidades_i)
                mix_counts: dict[str, int] = {}
                for slug in tipologias_i:
                    mix_counts[slug] = mix_counts.get(slug, 0) + 1
                mix_i = dict(mix_counts)

            nombre = _nombre_planta(idx_visual, p.tipo)
            idx_visual += 1

        # Se guardan los m² SIN redondear (precisión completa). El redondeo a
        # 2 decimales se aplica solo en la serialización (capa de presentación).
        viv_por_planta.append(viv_i)
        construida_por_planta.append(construida_i)
        util_por_planta.append(util_disponible_planta)
        muros_por_planta.append(muros_i)
        muros_estimados_por_planta.append(muros_est_i)
        circulacion_por_planta.append(circ_i)
        nucleo_por_planta.append(nucl_i)
        patio_por_planta.append(patio_i)
        local_por_planta.append(local_i)
        tipo_planta.append(p.tipo)
        nombres_planta.append(nombre)
        viviendas_por_tipologia.append(mix_i)
        unidades_por_planta.append(unidades_i)
        tipologias_unidad_por_planta.append(tipologias_i)

    n_total = sum(viv_por_planta)
    viv_pp_regulares = [v for v, t in zip(viv_por_planta, tipo_planta) if t == "regular"]
    viv_pp_obj = (
        max(viv_pp_regulares) if viv_pp_regulares
        else (max(viv_por_planta) if viv_por_planta else 0)
    )

    util_planta_promedio = (
        util_total / max(1, n_plantas_habitables) if n_plantas_habitables else 0.0
    )

    return Capacidad(
        superficie_parcela_m2=parcela_area,
        coeficiente_edificabilidad=coef,
        edificabilidad_m2=edificabilidad_m2,
        ocupacion_maxima=urb.ocupacion_maxima,
        n_plantas_solicitadas=n_plantas_solicitadas,
        n_plantas_edificables=n_plantas_edif_max,
        huella_m2=huella,
        ocupacion_area_m2=ocup_area,
        huella_efectiva_m2=huella_efectiva,
        construida_prevista_m2=construida_total,
        factor_limitante=factor_limitante,
        n_dormitorios=n_dorms,
        util_objetivo_viv_m2=util_viv,
        util_planta_disponible_m2=util_planta_promedio,
        viv_por_planta_objetivo=viv_pp_obj,
        n_viviendas_objetivo=n_total,
        pct_muros=pct_muros,
        pct_circulacion_pb=pct_circ_pb,
        pct_circulacion_tipo=pct_circ_tipo,
        pct_nucleo=pct_nucl,
        pct_muros_normativo=pct_muros_normativo,
        pct_local_pb=pct_local_pb,
        viv_por_planta=viv_por_planta,
        construida_por_planta=construida_por_planta,
        util_por_planta=util_por_planta,
        muros_por_planta=muros_por_planta,
        muros_estimados_por_planta=muros_estimados_por_planta,
        circulacion_por_planta=circulacion_por_planta,
        nucleo_por_planta=nucleo_por_planta,
        patio_por_planta=patio_por_planta,
        local_por_planta=local_por_planta,
        tipo_planta=tipo_planta,
        nombres_planta=nombres_planta,
        viviendas_por_tipologia=viviendas_por_tipologia,
        unidades_por_planta=unidades_por_planta,
        tipologias_unidad_por_planta=tipologias_unidad_por_planta,
        area_servicios_comunes_m2=area_servicios_comunes_m2,
        n_plantas_habitables=n_plantas_habitables,
        construida_computable_m2=construida_computable_efectiva,
    )


def capacidad_a_dict(cap: Capacidad) -> dict:
    """Serializa Capacidad a JSON-friendly dict.

    Los m² se guardan SIN redondear en `Capacidad`; aquí se redondean a 2
    decimales SOLO para presentación (nunca se truncan a entero).
    """
    def _l2(xs):
        return [round(float(v), 2) for v in xs]

    return {
        "superficie_parcela_m2": round(cap.superficie_parcela_m2, 2),
        "coeficiente_edificabilidad": cap.coeficiente_edificabilidad,
        "edificabilidad_m2": round(cap.edificabilidad_m2, 2),
        "ocupacion_maxima": cap.ocupacion_maxima,
        "ocupacion_area_m2": round(cap.ocupacion_area_m2, 2),
        "huella_m2": round(cap.huella_m2, 2),
        "huella_efectiva_m2": round(cap.huella_efectiva_m2, 2),
        "n_plantas_solicitadas": cap.n_plantas_solicitadas,
        "n_plantas_edificables": cap.n_plantas_edificables,
        "n_plantas_habitables": cap.n_plantas_habitables,
        "pct_muros": cap.pct_muros,
        "pct_muros_normativo": cap.pct_muros_normativo,
        "pct_circulacion_pb": cap.pct_circulacion_pb,
        "pct_circulacion_tipo": cap.pct_circulacion_tipo,
        "pct_nucleo": cap.pct_nucleo,
        "pct_local_pb": cap.pct_local_pb,
        "util_objetivo_viv_m2": round(cap.util_objetivo_viv_m2, 2),
        "util_planta_disponible_m2": round(cap.util_planta_disponible_m2, 2),
        "n_dormitorios": cap.n_dormitorios,
        "viv_por_planta": list(cap.viv_por_planta),
        "viv_por_planta_objetivo": cap.viv_por_planta_objetivo,
        "n_viviendas_objetivo": cap.n_viviendas_objetivo,
        "construida_total_m2": round(sum(cap.construida_por_planta), 2),
        "util_total_m2": round(sum(cap.util_por_planta), 2),
        "muros_total_m2": round(sum(cap.muros_por_planta), 2),
        "muros_estimados_total_m2": round(sum(cap.muros_estimados_por_planta), 2),
        "circulacion_total_m2": round(sum(cap.circulacion_por_planta), 2),
        "nucleo_total_m2": round(sum(cap.nucleo_por_planta), 2),
        "patio_total_m2": round(sum(cap.patio_por_planta), 2),
        "local_total_m2": round(sum(cap.local_por_planta), 2),
        "construida_por_planta": _l2(cap.construida_por_planta),
        "util_por_planta": _l2(cap.util_por_planta),
        "muros_por_planta": _l2(cap.muros_por_planta),
        "muros_estimados_por_planta": _l2(cap.muros_estimados_por_planta),
        "circulacion_por_planta": _l2(cap.circulacion_por_planta),
        "nucleo_por_planta": _l2(cap.nucleo_por_planta),
        "patio_por_planta": _l2(cap.patio_por_planta),
        "local_por_planta": _l2(cap.local_por_planta),
        "tipo_planta": list(cap.tipo_planta),
        "nombres_planta": list(cap.nombres_planta),
        "viviendas_por_tipologia": list(cap.viviendas_por_tipologia),
        "unidades_por_planta": [
            [[int(n), round(float(u), 2)] for n, u in lista]
            for lista in cap.unidades_por_planta
        ],
        "tipologias_unidad_por_planta": [list(lista) for lista in cap.tipologias_unidad_por_planta],
        "construida_computable_m2": round(cap.construida_computable_m2, 2),
        "area_servicios_comunes_m2": round(cap.area_servicios_comunes_m2, 2),
        "factor_limitante": cap.factor_limitante,
    }
