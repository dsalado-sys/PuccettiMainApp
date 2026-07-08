"""Derivación del nº de viviendas a partir de la EDIFICABILIDAD.

Iteración 5: diferenciación PB / planta tipo + multi-tipología + local en PB.

El patio interior es un vacío a cielo abierto: NO computa como superficie
construida. Por eso la `construida` que se reporta por planta es la HUELLA
menos el patio, y se cumple
`construida = útil + muros + circ + núcleo + local + otros + usos comunes`
(el patio queda fuera y se reporta en su columna aparte).

Planta baja (idx_visual == 0, tipo "regular"):
    huella_i      = huella_planta (ya con retranqueos + ocupación)
    muros_i       = huella_i × pct_muros / 100            # muros SÍ es %
    circ_i_pb     = min(circulacion_pb_m2, huella_i − muros_i)   # circulación es m²
    nucleo_i      = min(nucleo_m2, huella_i)   # área fija del núcleo, por planta
    local_i       = min(local_pb_m2, útil restante)      # reservas de PB en m²
    util_unidades_pb = huella_i − muros_i − circ_i − nucleo_i − reservas_pb
    construida_i  = huella_i − patio_i  (el patio no computa a construido)

Planta tipo / ático:
    Mismo esquema pero con circulacion_tipo_m2, sin reservas de PB.

Sótanos: viv=0 forzado. Ático: si computa_edif=False no consume techo.
Reparto multi-tipología: si hay tipologías_extra, se asigna ≥1 unidad de
cada y se rellena el sobrante con la más pequeña.

Edificabilidad: el exceso sobre el techo (`construida_computable_total >
edificabilidad_m2`) marca el factor limitante y dispara el aviso de incumplimiento,
pero NO retira plantas del reparto. Todas las plantas habitables con útil alojan
unidades, también las que superan el techo (p. ej. una planta consolidada/legalizada
por antigüedad en rehabilitación, que se usa como una planta más).
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .config import Parametros
from .programa import (
    CONFIG_DEFAULT as CONFIG_VIVIENDA_DEFAULT,
    ProgramaViviendaConfig,
    reparto_multi_tipologia,
    util_maximo,
)
from .programa_uso import TipologiaUnidadDescriptor, reparto_multi_tipologia_generico


def _truncar(x: float) -> int:
    """Política de redondeo del módulo: hacia abajo (truncar a entero)."""
    return max(0, int(x))


@dataclass(frozen=True)
class DisenoPlanta:
    """Descuentos de una categoría de planta: % muros + m² de circulación común.

    Iteración 6: cada categoría (pb / tipo / atico / sotano) trae los suyos, lo que
    permite que PB sea independiente de las plantas tipo y que ático y sótano tengan
    su propio % muros y su circulación. El núcleo (m² fijos) es de edificio y no
    vive aquí: lo aporta el programa (`nucleo_m2`), igual en todas las plantas.

    `circulacion_m2` es la circulación común de la planta en m² ABSOLUTOS (antes era
    un %); se reserva como el núcleo, acotada a la huella disponible.
    """
    pct_muros: float
    circulacion_m2: float
    # % muros INTERIORES de la unidad (tabiquería). Se suma a `pct_muros` al descontar
    # de la construida; default 0 (sin él, comportamiento idéntico al previo).
    pct_muros_interior: float = 0.0


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
    circulacion_pb_m2: float
    circulacion_tipo_m2: float
    nucleo_m2: float
    pct_muros_normativo: float = 20.0
    local_pb_m2: float = 0.0
    otros_pb_m2: float = 0.0
    usos_comunes_pb_m2: float = 0.0
    viv_por_planta: list[int] = field(default_factory=list)
    construida_por_planta: list[float] = field(default_factory=list)
    util_por_planta: list[float] = field(default_factory=list)
    muros_por_planta: list[float] = field(default_factory=list)
    # Tabiquería interior de las unidades, por planta (cálculo de unidad, % del útil
    # destinado a viviendas). Separada de `muros_por_planta` (solo perímetro/edificio).
    muros_interior_por_planta: list[float] = field(default_factory=list)
    muros_estimados_por_planta: list[float] = field(default_factory=list)
    circulacion_por_planta: list[float] = field(default_factory=list)
    nucleo_por_planta: list[float] = field(default_factory=list)
    patio_por_planta: list[float] = field(default_factory=list)
    # Superficie libre por planta (complemento de la ocupación máxima): en cada
    # planta habitable = superficie de referencia − construida = (1 − ocupación) ×
    # sup_ref. Sótano → 0. Su suma es la «superficie libre» contra la que se compara
    # el total de patios para el aviso de Capacidad.
    superficie_libre_por_planta: list[float] = field(default_factory=list)
    local_por_planta: list[float] = field(default_factory=list)
    otros_por_planta: list[float] = field(default_factory=list)
    usos_comunes_por_planta: list[float] = field(default_factory=list)
    tipo_planta: list[str] = field(default_factory=list)
    nombres_planta: list[str] = field(default_factory=list)
    viviendas_por_tipologia: list[dict[str, int]] = field(default_factory=list)
    # Detalle por unidad de cada planta: lista [(n_dorms, util_m2), ...].
    # Permite a `tabla_unidad_desde_capacidad` generar una fila por unidad con
    # su tipología y útil real (sin promediar). Las plantas sin viviendas
    # (sótano, o una planta sin útil tras descuentos) guardan lista vacía.
    unidades_por_planta: list[list[tuple[int, float]]] = field(default_factory=list)
    # Slug de tipología de cada unidad (paralelo a `unidades_por_planta`). Permite
    # a la serialización regenerar las estancias por unidad cuando la planta mezcla
    # varias tipologías (apartamento 1d+2d, hotel doble+triple, …).
    tipologias_unidad_por_planta: list[list[str]] = field(default_factory=list)
    area_servicios_comunes_m2: float = 0.0
    n_plantas_habitables: int = 0
    construida_computable_m2: float = 0.0
    # Superficie de patio interior objetivo (mínimo normativo configurable). El
    # patio vive preferentemente en la superficie libre (parcela − construida); la
    # parte que no cabe EXCAVA la huella construida y se acumula en
    # `patio_excavado_m2` (esa parte resta a la útil y dispara el aviso).
    area_patio_min_m2: float = 0.0
    patio_excavado_m2: float = 0.0
    # Accesibilidad (DB-SUA): nº de unidades adaptadas asignadas automáticamente
    # por tramos (0 en vivienda) y modo de adaptación ("total" o "parcial").
    n_unidades_adaptadas: int = 0
    modo_adaptacion: str = "total"
    # Útil de una planta representativa (planta tipo estándar): m² contra los que se
    # enumeran las combinaciones por planta (§ hotel).
    util_planta_representativa_m2: float = 0.0
    # § hotel: True si la composición por planta forzada no cupo entera en alguna
    # planta habitable (p. ej. la PB con reservas comunes) → se truncó ahí.
    composicion_truncada: bool = False


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


def _construir_perfil(
    prog_motor, descriptores, util_objetivo,
    cfg_vivienda: ProgramaViviendaConfig = CONFIG_VIVIENDA_DEFAULT,
) -> _PerfilTipologia:
    """Perfil de reparto en unidades a partir del programa (motor) de una categoría."""
    n_dorms = prog_motor.n_dormitorios
    if descriptores:
        util_viv = descriptores[0].util_objetivo
    elif util_objetivo is not None:
        util_viv = util_objetivo
    else:
        util_viv = util_maximo(n_dorms, cfg_vivienda)
    extras = list(getattr(prog_motor, "tipologias_extra", []) or [])
    tipologias_set = [n_dorms] + [int(t) for t in extras]
    salon_open = bool(getattr(prog_motor, "salon_cocina_open", False))
    return _PerfilTipologia(descriptores, n_dorms, util_viv, tipologias_set, salon_open)


def _reparto_planta(
    util_disponible: float, perfil: _PerfilTipologia,
    cfg_vivienda: ProgramaViviendaConfig = CONFIG_VIVIENDA_DEFAULT,
):
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
        unidades = reparto_multi_tipologia(
            util_disponible, perfil.tipologias_set, perfil.salon_open, cfg_vivienda)
        tipologias = [str(n) for n, _ in unidades]
    else:
        n_viv = _truncar(util_disponible / perfil.util_viv) if perfil.util_viv > 0 else 0
        unidades = [(perfil.n_dorms, perfil.util_viv) for _ in range(n_viv)]
        tipologias = [str(perfil.n_dorms) for _ in range(n_viv)]
    return unidades, tipologias


def _colocar_composicion_forzada(
    util_disponible: float,
    composicion: list[tuple[str, float, int]],
):
    """Coloca una composición fija de unidades en una planta (§ hotel).

    `composicion` = lista `(slug, util_objetivo, n_dorms_label)` con UNA entrada por
    unidad (la composición POR PLANTA elegida por el arquitecto). Coloca las unidades
    de mayor a menor útil mientras quepan en `util_disponible`; las que no caben se
    descartan (planta con menos útil que la representativa → `truncada=True`).

    Devuelve `(unidades, tipologias, truncada)` con el mismo formato que
    `_reparto_planta` (`unidades=[(n_dorms_label, util_m2)…]`, `tipologias=[slug…]`).
    """
    restante = util_disponible
    unidades: list[tuple[int, float]] = []
    tipologias: list[str] = []
    truncada = False
    for slug, util_obj, label in sorted(composicion, key=lambda t: -t[1]):
        if util_obj <= restante + 1e-6:
            unidades.append((label, util_obj))
            tipologias.append(slug)
            restante -= util_obj
        else:
            truncada = True
    return unidades, tipologias, truncada


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
    cfg_vivienda: ProgramaViviendaConfig | None = None,
    composicion_planta_forzada: list[tuple[str, float, int]] | None = None,
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
    # §3.8 — mínimos/política de vivienda editados (panel/BBDD). Solo se usa en la
    # vía int-based de vivienda (sin descriptores); para el resto de usos llega None.
    cfg_vivienda = cfg_vivienda if cfg_vivienda is not None else CONFIG_VIVIENDA_DEFAULT

    # Superficie de suelo para los límites legales (edificabilidad / ocupación):
    # la catastral real si la envolvente la conoce; si no, el área geométrica.
    parcela_area = getattr(envolvente, "superficie_referencia_m2", 0.0) or envolvente.parcela.area
    urb = params.urbanismo

    # Diseño por categoría de planta. Si no llega `disenos`, se deriva de `params`
    # reproduciendo el comportamiento histórico (sótano con circulación 0).
    if disenos is None:
        _pm = max(0.0, min(80.0, float(params.diseno.pct_muros)))
        _pmi = max(0.0, min(80.0, float(getattr(params.diseno, "pct_muros_interior", 0.0))))
        _cpb = max(0.0, float(getattr(params.diseno, "circulacion_pb_m2", 10.0)))
        _ct = max(0.0, float(getattr(params.diseno, "circulacion_tipo_m2", 10.0)))
        disenos = {
            "pb": DisenoPlanta(_pm, _cpb, _pmi),
            "tipo": DisenoPlanta(_pm, _ct, _pmi),
            "atico": DisenoPlanta(_pm, _ct, _pmi),
            "sotano": DisenoPlanta(_pm, 0.0, _pmi),
        }
    dis_pb = disenos["pb"]
    dis_tipo = disenos["tipo"]
    pct_muros_normativo = max(0.0, min(80.0, float(getattr(params.diseno, "pct_muros_normativo", 20.0))))
    uso_edificio = str(getattr(params.programa, "uso", "vivienda"))
    local_pb_m2 = max(0.0, float(getattr(params.programa, "local_pb_m2", 0.0)))
    otros_pb_m2 = max(0.0, float(getattr(params.programa, "otros_pb_m2", 0.0)))
    usos_comunes_pb_m2 = max(0.0, float(getattr(params.programa, "usos_comunes_pb_m2", 0.0)))
    # Núcleo (escalera/ascensor): área FIJA en m² reservada en cada planta. Es de
    # edificio (vertical y única), no un % por planta. Se acota por planta a la huella.
    nucleo_m2 = max(0.0, float(getattr(params.programa, "nucleo_m2", 15.0)))
    # Reservas de PB por uso (todas viven solo en planta baja):
    #   · "local"        → vivienda + apartamentos turísticos (no hoteles).
    #   · "usos comunes" → AT + hoteles (todo lo no residencial).
    #   · "otros"        → todos los usos.
    # El uso pone a 0 la reserva que no le corresponde, de modo que su columna/fila
    # no aparezca (el frontend la oculta además por uso).
    if uso_edificio not in ("vivienda", "apartamentos_turisticos"):
        local_pb_m2 = 0.0
    if uso_edificio == "vivienda":
        usos_comunes_pb_m2 = 0.0
    # Verificación de "no queda útil": ahora la circulación común y las reservas de PB
    # son m² absolutos (se acotan por planta y no pueden por sí solos dejar útil
    # negativo). Solo el % de muros puede vaciar la planta por porcentaje; el resto
    # (circulación, núcleo, reservas) se descuenta en m² más abajo con max(0, …).
    pct_total_max = dis_pb.pct_muros

    huella = envolvente.plantas[0].footprint.area if envolvente.plantas else parcela_area
    coef = urb.coeficiente_edificabilidad
    # `ocup_area` = ocupación de PB (KPI `ocupacion_area_m2`, huella efectiva y factor
    # limitante, todos referidos a la planta baja). El TECHO por ocupación, en cambio,
    # usa la MAYOR de PB/tipo: la planta de mayor huella puede ser la tipo, y el consumo
    # (suma de huellas por planta) debe caber bajo el techo sin falsear el exceso.
    ocup_area = urb.ocupacion_maxima * parcela_area
    ocup_max = max(urb.ocupacion_maxima, getattr(urb, "ocupacion_maxima_tipo", urb.ocupacion_maxima))
    if getattr(urb, "usar_coeficiente_edificabilidad", True):
        edificabilidad_m2 = coef * parcela_area
    else:
        edificabilidad_m2 = ocup_max * parcela_area * max(1, urb.n_plantas_max)
    huella_efectiva = min(huella, ocup_area) if ocup_area > 0 else huella

    # Perfiles de tipología: PB (params) y plantas tipo (params_tipo). El ático
    # usa el perfil tipo; el sótano no aloja unidades. Sin params_tipo, tipo = PB.
    perfil_pb = _construir_perfil(
        params.programa, descriptores_tipologia, util_objetivo_por_unidad, cfg_vivienda)
    if params_tipo is None:
        perfil_tipo = perfil_pb
    else:
        perfil_tipo = _construir_perfil(
            params_tipo.programa, descriptores_tipologia_tipo, util_objetivo_por_unidad_tipo,
            cfg_vivienda,
        )
    n_dorms = perfil_pb.n_dorms        # KPI: tipología principal de PB
    util_viv = perfil_pb.util_viv      # KPI

    n_plantas_solicitadas = max(1, len(envolvente.plantas) or params.programa.n_plantas)
    plantas = list(envolvente.plantas)

    n_plantas_habitables = sum(1 for p in plantas if p.tipo != "sotano")
    if n_plantas_habitables <= 0:
        n_plantas_habitables = 1

    descuento_por_planta = area_servicios_comunes_m2 / n_plantas_habitables

    construida_computable_total = sum(
        getattr(p, "area_construida_m2", p.footprint.area) for p in plantas if p.computa_edif
    )
    n_plantas_edif_max = (
        max(1, int(edificabilidad_m2 // huella_efectiva)) if huella_efectiva else 1
    )

    # El exceso de edificabilidad NO retira plantas del reparto: solo alimenta el factor
    # limitante y el aviso de incumplimiento (`_alertas_envolvente` / `ValidarCumplimiento`,
    # ambos independientes de aquí). Todas las plantas habitables con útil reparten unidades,
    # también las que superan el techo (p. ej. una planta consolidada/legalizada por
    # antigüedad en rehabilitación, que se usa como una planta más). El sótano no aloja
    # unidades por su propia rama (`cat == "sotano"`), no por el techo.
    excede_techo = construida_computable_total > edificabilidad_m2 + 1e-3

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
    muros_interior_por_planta: list[float] = []
    muros_estimados_por_planta: list[float] = []
    circulacion_por_planta: list[float] = []
    nucleo_por_planta: list[float] = []
    patio_por_planta: list[float] = []
    superficie_libre_por_planta: list[float] = []
    local_por_planta: list[float] = []
    otros_por_planta: list[float] = []
    usos_comunes_por_planta: list[float] = []
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
    patio_excavado_total = 0.0
    # § hotel: la composición POR PLANTA elegida se replica en cada planta habitable;
    # una planta con menos útil (PB con comunes) la trunca → aviso.
    composicion_truncada = False

    es_primera_regular = True

    for i, p in enumerate(plantas):
        # `construida_i` aquí es la HUELLA de la planta. Sirve de base para los
        # porcentajes de muros/circulación/núcleo y para la edificabilidad. La
        # construida que se REPORTA (sin patio) se calcula más abajo, una vez
        # conocido `patio_i`.
        construida_i = p.footprint.area
        if p.computa_edif:
            # La edificabilidad (techo consumido) suma la superficie CONSTRUIDA de las
            # plantas que computan: la huella menos los patios (vacíos a cielo abierto,
            # que no son techo). `construida_i` (huella completa) se reserva como base de
            # los % de muros/circulación/núcleo de más abajo.
            construida_computable_efectiva += getattr(p, "area_construida_m2", construida_i)

        cat = _categoria_planta(p, es_primera_regular)
        dis = disenos.get(cat, dis_tipo)
        # PB usa el perfil de tipología de planta baja; tipo y ático, el de
        # plantas tipo (ver §perfiles arriba). El sótano no aloja unidades.
        perfil = perfil_pb if cat == "pb" else perfil_tipo

        # Ocupación máxima como CAP NUMÉRICO (el retranqueo de ocupación ya no es
        # geometría: la huella llega íntegra). La construible de la planta se acota a
        # ocupación × sup_ref; PB/sótano usan la ocupación de PB, tipo/ático la de tipo.
        ocup_cat = urb.ocupacion_maxima if cat in ("pb", "sotano") else \
            getattr(urb, "ocupacion_maxima_tipo", urb.ocupacion_maxima)
        lim_ocup = max(0.0, float(ocup_cat)) * parcela_area
        if lim_ocup > 0:
            construida_i = min(construida_i, lim_ocup)

        # Muros de PLANTA = solo perímetro/edificio (pct_muros): fachadas, medianeras
        # y separaciones entre unidades. La tabiquería INTERIOR de las unidades
        # (pct_muros_interior) NO se suma aquí: es un cálculo de unidad y se descuenta
        # más abajo, sobre el útil disponible que se reparte (no sobre la huella).
        muros_i = construida_i * dis.pct_muros / 100.0
        muros_int_i = 0.0
        pct_muros_int = max(0.0, min(90.0, float(getattr(dis, "pct_muros_interior", 0.0))))
        muros_est_i = construida_i * pct_muros_normativo / 100.0
        # Núcleo: área fija en m² (misma en todas las plantas), acotada a la huella.
        nucl_i = min(nucleo_m2, construida_i)
        # Circulación común: m² fijos por planta, acotados a lo que queda tras muros.
        circ_i = min(dis.circulacion_m2, max(0.0, construida_i - muros_i))
        patio_i = 0.0
        local_i = 0.0
        otros_i = 0.0
        comunes_i = 0.0
        viv_i = 0
        util_disponible_planta = 0.0   # útil neto de la planta (lo que se reparte)
        mix_i: dict[str, int] = {}
        unidades_i: list[tuple[int, float]] = []
        tipologias_i: list[str] = []

        if cat == "sotano":
            # El sótano aplica sus propios % muros/circulación y el núcleo (m² fijos,
            # que también lo atraviesan), pero no aloja unidades (viv = 0, sin útil ni patio).
            patio_i = 0.0
            nombre = _nombre_planta(0, "sotano")
        else:
            # PB: usa circulacion_pb_m2 + descuenta reservas de PB. Resto (planta
            # tipo / ático): usa circulacion_tipo_m2, sin reservas.
            es_pb = es_primera_regular and p.tipo == "regular"
            # La circulación por categoría ya viene resuelta en `dis`
            # (disenos["pb"]→circulacion_pb_m2, "tipo"/"atico"→circulacion_tipo_m2).
            circ_m2_planta = dis.circulacion_m2
            # La circulación de la planta engloba: pasillos comunes (m² fijos) + cuota
            # de áreas comunes obligatorias del uso (`descuento_por_planta`, sólo
            # no-vivienda). Se acota a lo que queda tras muros para no dejar útil
            # negativo. Así la huella cuadra: huella_i = util + muros + circ + núcleo
            # + patio + reservas (y la construida reportada = huella_i − patio_i).
            circ_i = min(circ_m2_planta + descuento_por_planta, max(0.0, construida_i - muros_i))

            # Patio interior (modelo MIXTO): se reporta ÍNTEGRO, nunca se trunca.
            # Vive preferentemente en la superficie libre (parcela − construida); la
            # parte que no cabe ahí EXCAVA la huella construida. Reducir la ocupación
            # aumenta la superficie libre y reduce la excavación (comportamiento
            # intuitivo, opuesto al tope antiguo contra el interior).
            excavado_i = 0.0
            if area_patio_norm > 0:
                patio_i = area_patio_norm
                libre_planta = max(0.0, parcela_area - construida_i)
                excavado_i = max(0.0, patio_i - libre_planta)
                patio_excavado_total += excavado_i

            # La parte EXCAVADA del patio ocupa interior del edificio → resta a la
            # útil repartible entre las unidades. La parte que cae en superficie libre
            # (no incluida en `excavado_i`) no toca la útil.
            util_bruto_i = max(
                0.0,
                construida_i - muros_i - circ_i - nucl_i - excavado_i,
            )
            if es_pb:
                # Reservas de PB en m² ABSOLUTOS: local (vivienda/AT), otros (todos) y
                # usos comunes (AT/hoteles). El uso ya ha puesto a 0 las que no le
                # corresponden. Se descuentan secuencialmente, cada una acotada al útil
                # restante (nunca dejan útil negativo).
                local_i = min(local_pb_m2, util_bruto_i)
                otros_i = min(otros_pb_m2, max(0.0, util_bruto_i - local_i))
                comunes_i = min(usos_comunes_pb_m2, max(0.0, util_bruto_i - local_i - otros_i))
                util_disponible_bruto_i = max(0.0, util_bruto_i - local_i - otros_i - comunes_i)
                es_primera_regular = False
            else:
                util_disponible_bruto_i = util_bruto_i

            # Tabiquería interior de las unidades (CÁLCULO DE UNIDAD): es un % del
            # área destinada a viviendas, NO de la huella del edificio. Por eso se
            # descuenta aquí, sobre el área disponible tras muros de perímetro,
            # circulación, núcleo, patio y reservas. Consecuencia directa: con
            # pct_muros_interior = 0 no se reserva ni un m² de tabiquería y la útil
            # que se reparte es exactamente el área disponible (sin cambios).
            muros_int_i = util_disponible_bruto_i * pct_muros_int / 100.0
            util_disponible_i = max(0.0, util_disponible_bruto_i - muros_int_i)

            # Útil neto de la planta (lo que ocupan las estancias de las unidades):
            # huella = útil + muros(perímetro) + muros_interior + circ + núcleo +
            # patio + local (+ comunes en su fila aparte). El patio se excluye de la
            # construida reportada (vacío a cielo abierto).
            util_disponible_planta = util_disponible_i
            util_total += util_disponible_planta

            if util_disponible_i > 0 and (
                composicion_planta_forzada is not None or perfil.util_viv > 0
            ):
                if composicion_planta_forzada is not None:
                    # Composición fija por planta (§ hotel): la misma mezcla en cada
                    # planta habitable, truncada si esta planta tiene menos útil.
                    unidades_i, tipologias_i, trunc_i = _colocar_composicion_forzada(
                        util_disponible_i, composicion_planta_forzada)
                    if trunc_i:
                        composicion_truncada = True
                else:
                    unidades_i, tipologias_i = _reparto_planta(util_disponible_i, perfil, cfg_vivienda)
                viv_i = len(unidades_i)
                mix_counts: dict[str, int] = {}
                for slug in tipologias_i:
                    mix_counts[slug] = mix_counts.get(slug, 0) + 1
                mix_i = dict(mix_counts)

            nombre = _nombre_planta(idx_visual, p.tipo)
            idx_visual += 1

        # Los patios ya NO restan a la construida reportada: las unidades se construyen
        # sobre la construida completa y el patio se contabiliza aparte, contra la
        # superficie libre. La construida reportada es la huella de cálculo íntegra.
        construida_neta_i = construida_i
        construida_total += construida_neta_i

        # Superficie libre de la planta = complemento de la ocupación (sup_ref −
        # construida). Como `construida_i` = huella erosionada por ocupación, esto es
        # (1 − ocupación_planta) × sup_ref y contempla PB y plantas tipo por
        # construcción. El sótano (bajo rasante) no aporta superficie libre.
        libre_i = 0.0 if p.tipo == "sotano" else max(0.0, parcela_area - construida_neta_i)

        # Se guardan los m² SIN redondear (precisión completa). El redondeo a
        # 2 decimales se aplica solo en la serialización (capa de presentación).
        viv_por_planta.append(viv_i)
        construida_por_planta.append(construida_neta_i)
        superficie_libre_por_planta.append(libre_i)
        util_por_planta.append(util_disponible_planta)
        muros_por_planta.append(muros_i)
        muros_interior_por_planta.append(muros_int_i)
        muros_estimados_por_planta.append(muros_est_i)
        circulacion_por_planta.append(circ_i)
        nucleo_por_planta.append(nucl_i)
        patio_por_planta.append(patio_i)
        local_por_planta.append(local_i)
        otros_por_planta.append(otros_i)
        usos_comunes_por_planta.append(comunes_i)
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

    # Útil de una planta REPRESENTATIVA (planta tipo estándar): el máximo útil de las
    # plantas habitables — la PB, con reservas comunes, suele tener menos. Es el
    # «100 m² de útil en planta» contra el que el arquitecto enumera combinaciones.
    util_habitables = [u for u, t in zip(util_por_planta, tipo_planta) if t != "sotano"]
    util_planta_representativa = max(util_habitables) if util_habitables else 0.0

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
        circulacion_pb_m2=dis_pb.circulacion_m2,
        circulacion_tipo_m2=dis_tipo.circulacion_m2,
        nucleo_m2=nucleo_m2,
        pct_muros_normativo=pct_muros_normativo,
        local_pb_m2=local_pb_m2,
        otros_pb_m2=otros_pb_m2,
        usos_comunes_pb_m2=usos_comunes_pb_m2,
        viv_por_planta=viv_por_planta,
        construida_por_planta=construida_por_planta,
        util_por_planta=util_por_planta,
        muros_por_planta=muros_por_planta,
        muros_interior_por_planta=muros_interior_por_planta,
        muros_estimados_por_planta=muros_estimados_por_planta,
        circulacion_por_planta=circulacion_por_planta,
        nucleo_por_planta=nucleo_por_planta,
        patio_por_planta=patio_por_planta,
        superficie_libre_por_planta=superficie_libre_por_planta,
        local_por_planta=local_por_planta,
        otros_por_planta=otros_por_planta,
        usos_comunes_por_planta=usos_comunes_por_planta,
        tipo_planta=tipo_planta,
        nombres_planta=nombres_planta,
        viviendas_por_tipologia=viviendas_por_tipologia,
        unidades_por_planta=unidades_por_planta,
        tipologias_unidad_por_planta=tipologias_unidad_por_planta,
        area_servicios_comunes_m2=area_servicios_comunes_m2,
        n_plantas_habitables=n_plantas_habitables,
        construida_computable_m2=construida_computable_efectiva,
        area_patio_min_m2=area_patio_norm,
        patio_excavado_m2=patio_excavado_total,
        util_planta_representativa_m2=util_planta_representativa,
        composicion_truncada=composicion_truncada,
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
        "circulacion_pb_m2": cap.circulacion_pb_m2,
        "circulacion_tipo_m2": cap.circulacion_tipo_m2,
        "nucleo_m2": cap.nucleo_m2,
        "local_pb_m2": cap.local_pb_m2,
        "otros_pb_m2": cap.otros_pb_m2,
        "usos_comunes_pb_m2": cap.usos_comunes_pb_m2,
        "util_objetivo_viv_m2": round(cap.util_objetivo_viv_m2, 2),
        "util_planta_disponible_m2": round(cap.util_planta_disponible_m2, 2),
        "util_planta_representativa_m2": round(cap.util_planta_representativa_m2, 2),
        "composicion_truncada": cap.composicion_truncada,
        "n_dormitorios": cap.n_dormitorios,
        "viv_por_planta": list(cap.viv_por_planta),
        "viv_por_planta_objetivo": cap.viv_por_planta_objetivo,
        "n_viviendas_objetivo": cap.n_viviendas_objetivo,
        "construida_total_m2": round(sum(cap.construida_por_planta), 2),
        "util_total_m2": round(sum(cap.util_por_planta), 2),
        "muros_total_m2": round(sum(cap.muros_por_planta), 2),
        "muros_interior_total_m2": round(sum(cap.muros_interior_por_planta), 2),
        "muros_estimados_total_m2": round(sum(cap.muros_estimados_por_planta), 2),
        "circulacion_total_m2": round(sum(cap.circulacion_por_planta), 2),
        "nucleo_total_m2": round(sum(cap.nucleo_por_planta), 2),
        "patio_total_m2": round(sum(cap.patio_por_planta), 2),
        "superficie_libre_total_m2": round(sum(cap.superficie_libre_por_planta), 2),
        "local_total_m2": round(sum(cap.local_por_planta), 2),
        "otros_total_m2": round(sum(cap.otros_por_planta), 2),
        "usos_comunes_total_m2": round(sum(cap.usos_comunes_por_planta), 2),
        "construida_por_planta": _l2(cap.construida_por_planta),
        "util_por_planta": _l2(cap.util_por_planta),
        "muros_por_planta": _l2(cap.muros_por_planta),
        "muros_interior_por_planta": _l2(cap.muros_interior_por_planta),
        "muros_estimados_por_planta": _l2(cap.muros_estimados_por_planta),
        "circulacion_por_planta": _l2(cap.circulacion_por_planta),
        "nucleo_por_planta": _l2(cap.nucleo_por_planta),
        "patio_por_planta": _l2(cap.patio_por_planta),
        "superficie_libre_por_planta": _l2(cap.superficie_libre_por_planta),
        "local_por_planta": _l2(cap.local_por_planta),
        "otros_por_planta": _l2(cap.otros_por_planta),
        "usos_comunes_por_planta": _l2(cap.usos_comunes_por_planta),
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
        "area_patio_min_m2": round(cap.area_patio_min_m2, 2),
        "patio_excavado_m2": round(cap.patio_excavado_m2, 2),
        "n_unidades_adaptadas": cap.n_unidades_adaptadas,
        "modo_adaptacion": cap.modo_adaptacion,
        "factor_limitante": cap.factor_limitante,
    }
