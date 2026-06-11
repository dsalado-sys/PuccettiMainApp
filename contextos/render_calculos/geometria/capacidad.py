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


@dataclass(frozen=True)
class DisenoPlanta:
    """Porcentajes de descuento de una categoría de planta (muros/circulación/núcleo).

    Iteración 6: cada categoría (pb / tipo / atico / sotano) trae los suyos, lo que
    permite que PB sea independiente de las plantas tipo y que ático y sótano tengan
    su propio % muros y % circulación.
    """
    pct_muros: float
    pct_circulacion: float
    pct_nucleo: float


@dataclass
class _PerfilTipologia:
    """Cómo se reparte el útil de una planta en unidades (PB vs plantas tipo)."""
    descriptores: list | None
    n_dorms: int
    util_viv: float
    tipologias_set: list  # ints (vía int-based de vivienda)
    salon_open: bool


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


def _categoria_planta(p, es_primera_regular: bool) -> str:
    """Categoría de planta para elegir su perfil de diseño/tipología."""
    if p.tipo == "sotano":
        return "sotano"
    if p.tipo == "atico":
        return "atico"
    return "pb" if es_primera_regular else "tipo"


def _construir_perfil(prog_motor, descriptores, util_objetivo) -> _PerfilTipologia:
    """Perfil de reparto en unidades a partir del programa (motor) de una categoría."""
    n_dorms = prog_motor.n_dormitorios
    if descriptores:
        util_viv = descriptores[0].util_objetivo
    elif util_objetivo is not None:
        util_viv = util_objetivo
    else:
        util_viv = util_maximo(n_dorms)
    extras = list(getattr(prog_motor, "tipologias_extra", []) or [])
    tipologias_set = [n_dorms] + [int(t) for t in extras]
    salon_open = bool(getattr(prog_motor, "salon_cocina_open", False))
    return _PerfilTipologia(descriptores, n_dorms, util_viv, tipologias_set, salon_open)


def _reparto_planta(util_disponible: float, perfil: _PerfilTipologia):
    """Reparte el útil de una planta en unidades según su perfil de tipología.

    Devuelve `(unidades, tipologias)` con `unidades=[(n_dorms_label, util_m2)…]`
    y `tipologias=[slug…]` paralelo. Prioridad: descriptores (use-agnóstico) →
    vía int-based histórica (preview de vivienda).
    """
    if perfil.descriptores:
        if len(perfil.descriptores) > 1:
            seleccion = reparto_multi_tipologia_generico(util_disponible, perfil.descriptores)
            unidades = [(d.n_dorms_label, u) for d, u in seleccion]
            tipologias = [d.slug for d, _ in seleccion]
        else:
            d0 = perfil.descriptores[0]
            n_viv = _truncar(util_disponible / d0.util_objetivo) if d0.util_objetivo > 0 else 0
            unidades = [(d0.n_dorms_label, d0.util_objetivo) for _ in range(n_viv)]
            tipologias = [d0.slug for _ in range(n_viv)]
    elif len(set(perfil.tipologias_set)) > 1:
        unidades = reparto_multi_tipologia(util_disponible, perfil.tipologias_set, perfil.salon_open)
        tipologias = [str(n) for n, _ in unidades]
    else:
        n_viv = _truncar(util_disponible / perfil.util_viv) if perfil.util_viv > 0 else 0
        unidades = [(perfil.n_dorms, perfil.util_viv) for _ in range(n_viv)]
        tipologias = [str(perfil.n_dorms) for _ in range(n_viv)]
    return unidades, tipologias


def calcular_capacidad(
    envolvente,
    params: Parametros,
    *,
    util_objetivo_por_unidad: float | None = None,
    area_servicios_comunes_m2: float = 0.0,
    descriptores_tipologia: list[TipologiaUnidadDescriptor] | None = None,
    params_tipo: Parametros | None = None,
    util_objetivo_por_unidad_tipo: float | None = None,
    descriptores_tipologia_tipo: list[TipologiaUnidadDescriptor] | None = None,
    disenos: dict[str, DisenoPlanta] | None = None,
) -> Capacidad:
    """Deriva la capacidad numérica del edificio (sin geometría de unidades).

    Diferenciación por categoría de planta (iter. 6 — PB independiente):
    - `params` / `descriptores_tipologia` / `util_objetivo_por_unidad` describen la
      PLANTA BAJA y los valores de edificio.
    - `params_tipo` / `descriptores_tipologia_tipo` / `util_objetivo_por_unidad_tipo`
      describen las PLANTAS TIPO (y el ático). Si `params_tipo is None`, las plantas
      tipo replican PB (comportamiento histórico).
    - `disenos`: dict `categoría → DisenoPlanta` con los % muros/circulación/núcleo
      de "pb"/"tipo"/"atico"/"sotano". Si es None se derivan de `params` igual que
      antes (sótano con circulación 0).

    Reparto por planta (en orden de prioridad):
    - descriptores con >1 entrada → mezcla multi-tipología use-agnóstica
      (`reparto_multi_tipologia_generico`); cada unidad lleva su slug.
    - descriptores con 1 entrada → tantas unidades como quepan al `util_objetivo`.
    - sin descriptores → vía int-based histórica (preview de vivienda).
    """
    parcela_area = envolvente.parcela.area
    urb = params.urbanismo

    # Diseño por categoría de planta. Si no llega `disenos`, se deriva de `params`
    # reproduciendo el comportamiento histórico (sótano con circulación 0).
    if disenos is None:
        _pm = max(0.0, min(80.0, float(params.diseno.pct_muros)))
        _cpb = max(0.0, min(50.0, float(params.diseno.pct_circulacion_pb)))
        _ct = max(0.0, min(50.0, float(params.diseno.pct_circulacion_tipo)))
        _nu = max(0.0, min(30.0, float(params.diseno.pct_nucleo)))
        disenos = {
            "pb": DisenoPlanta(_pm, _cpb, _nu),
            "tipo": DisenoPlanta(_pm, _ct, _nu),
            "atico": DisenoPlanta(_pm, _ct, _nu),
            "sotano": DisenoPlanta(_pm, 0.0, _nu),
        }
    dis_pb = disenos["pb"]
    dis_tipo = disenos["tipo"]
    pct_muros_normativo = max(0.0, min(80.0, float(getattr(params.diseno, "pct_muros_normativo", 20.0))))
    pct_local_pb = max(0.0, min(100.0, float(getattr(params.programa, "pct_local_pb", 0.0))))
    # Verificación de no quedar útil: usamos el % de circulación más exigente.
    pct_total_max = dis_pb.pct_muros + max(dis_pb.pct_circulacion, dis_tipo.pct_circulacion) + dis_pb.pct_nucleo

    huella = envolvente.plantas[0].footprint.area if envolvente.plantas else parcela_area
    coef = urb.coeficiente_edificabilidad
    ocup_area = urb.ocupacion_maxima * parcela_area
    if getattr(urb, "usar_coeficiente_edificabilidad", True):
        edificabilidad_m2 = coef * parcela_area
    else:
        edificabilidad_m2 = ocup_area * max(1, urb.n_plantas_max)
    huella_efectiva = min(huella, ocup_area) if ocup_area > 0 else huella

    # Perfiles de tipología: PB (params) y plantas tipo (params_tipo). El ático
    # usa el perfil tipo; el sótano no aloja unidades. Sin params_tipo, tipo = PB.
    perfil_pb = _construir_perfil(params.programa, descriptores_tipologia, util_objetivo_por_unidad)
    if params_tipo is None:
        perfil_tipo = perfil_pb
    else:
        perfil_tipo = _construir_perfil(
            params_tipo.programa, descriptores_tipologia_tipo, util_objetivo_por_unidad_tipo
        )
    n_dorms = perfil_pb.n_dorms        # KPI: tipología principal de PB
    util_viv = perfil_pb.util_viv      # KPI

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

    es_primera_regular = True

    for i, p in enumerate(plantas):
        construida_i = p.footprint.area
        construida_total += construida_i
        admitida = i in plantas_admitidas_idx
        if p.computa_edif and admitida:
            construida_computable_efectiva += construida_i

        cat = _categoria_planta(p, es_primera_regular)
        dis = disenos.get(cat, dis_tipo)

        muros_i = construida_i * dis.pct_muros / 100.0
        muros_est_i = construida_i * pct_muros_normativo / 100.0
        nucl_i = construida_i * dis.pct_nucleo / 100.0
        circ_i = construida_i * dis.pct_circulacion / 100.0
        patio_i = min(area_patio_norm, construida_i * 0.20) if area_patio_norm > 0 else 0.0
        local_i = 0.0
        viv_i = 0
        util_disponible_planta = 0.0   # útil neto de la planta (lo que se reparte)
        mix_i: dict[str, int] = {}
        unidades_i: list[tuple[int, float]] = []
        tipologias_i: list[str] = []

        if cat == "sotano":
            # El sótano aplica sus propios % muros/circulación/núcleo pero no aloja
            # unidades (viv = 0, sin útil ni patio).
            patio_i = 0.0
            nombre = _nombre_planta(0, "sotano")
        else:
            # PB: usa pct_circulacion_pb + descuenta local. Resto (planta tipo /
            # ático): usa pct_circulacion_tipo, sin local.
            es_pb = es_primera_regular and p.tipo == "regular"
            pct_circ_planta = pct_circ_pb if es_pb else pct_circ_tipo
            # La circulación de la planta engloba: pasillos comunes
            # (`pct_circulacion_*`) + cuota de áreas comunes obligatorias del
            # uso (`descuento_por_planta`, sólo no-vivienda). Así la tabla
            # cuadra: construida_i = util + muros + circ + núcleo + patio + local.
            circ_i = construida_i * pct_circ_planta / 100.0 + descuento_por_planta

            util_bruto_i = max(
                0.0,
                construida_i - muros_i - circ_i - nucl_i - patio_i,
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

            if admitida and util_disponible_i > 0 and perfil.util_viv > 0:
                unidades_i, tipologias_i = _reparto_planta(util_disponible_i, perfil)
                viv_i = len(unidades_i)
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
        pct_muros=dis_pb.pct_muros,
        pct_circulacion_pb=dis_pb.pct_circulacion,
        pct_circulacion_tipo=dis_tipo.pct_circulacion,
        pct_nucleo=dis_pb.pct_nucleo,
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
