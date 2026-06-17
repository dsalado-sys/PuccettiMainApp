"""Programa arquitectónico de apartamentos turísticos (Decreto 194/2010).

Cubre los dos grupos del Decreto 194/2010 (Junta de Andalucía):
- **`edificios`** (Anexo I.3 · edificios / complejos): categorías 1L–4L.
- **`conjuntos`** (Anexo I.4 · conjuntos): solo 1L/2L (mismos mínimos), con 2º
  baño obligatorio si la unidad supera 5 usuarios y sin áreas sociales.

La unidad se clasifica por la **ocupación del dormitorio** (individual, doble,
triple, cuádruple) o es un **estudio**. Cada apartamento se compone de
salón-comedor (hasta 4 personas) + 1 dormitorio + cocina + baño. La superficie
del salón-comedor crece con la *superficie adicional por plaza* a partir de la 4ª.

`programa_apartamentos` devuelve `list[Estancia]` reutilizando la dataclass
`Estancia` de vivienda, con nombres compatibles (`salon_comedor`, `dormitorio_1`,
`cocina`, `bano`, `aseo`).
"""
from __future__ import annotations

from .combinador_tipologias import ComboDormitorios
from .programa import Estancia, nombres_banos
from .programa_uso import ProgramaUso, TipologiaUnidadDescriptor


TIPOLOGIAS = ("estudio", "individual", "doble", "triple", "cuadruple")

# Tamaños de dormitorio válidos en una combinación (§2.5): el alfabeto del
# combinador. Excluye "estudio", que es la unidad entera (combinación N=0), no
# un tamaño de dormitorio.
TAMANOS_DORMITORIO = ("individual", "doble", "triple", "cuadruple")

# ─── Anexo I.3/I.4 — m² mínimos por categoría (1L–4L) ─────────────────────
# Dormitorio por ocupación. 1L/2L coinciden con el grupo "conjuntos" (A1.4).
MIN_DORMITORIO: dict[str, dict[str, float]] = {
    "individual": {"1L": 7.0,  "2L": 7.0,  "3L": 8.0,  "4L": 9.0},
    "doble":      {"1L": 10.0, "2L": 10.0, "3L": 12.0, "4L": 15.0},
    "triple":     {"1L": 16.0, "2L": 16.0, "3L": 18.0, "4L": 21.0},
    "cuadruple":  {"1L": 22.0, "2L": 22.0, "3L": 24.0, "4L": 27.0},
}
MIN_ESTUDIO: dict[str, float] = {"1L": 20.0, "2L": 21.0, "3L": 23.0, "4L": 24.0}
MIN_SALON_COMEDOR: dict[str, float] = {"1L": 10.0, "2L": 12.0, "3L": 14.0, "4L": 16.0}  # hasta 4 personas
MIN_COCINA: dict[str, float] = {"1L": 5.0, "2L": 6.0, "3L": 7.0, "4L": 8.0}
MIN_BANO: dict[str, float] = {"1L": 3.0, "2L": 3.0, "3L": 3.5, "4L": 4.0}
# Superficie adicional por plaza a partir de la 4ª persona (incrementa el salón-comedor).
SUP_ADICIONAL_PLAZA: dict[str, float] = {"1L": 2.0, "2L": 2.5, "3L": 3.0, "4L": 4.0}

# Plazas (ocupación) por tipología.
PLAZAS: dict[str, int] = {"estudio": 2, "individual": 1, "doble": 2, "triple": 3, "cuadruple": 4}

# Personas que se imputan al salón-comedor a efectos de ocupación de la unidad
# (sofá-cama "hasta 2 personas"), sumadas a las plazas de los dormitorios.
PLAZAS_SALON = 2


def ocupacion_unidad(plazas_dormitorios: int) -> int:
    """Ocupación total de la unidad = plazas de los dormitorios + PLAZAS_SALON.

    Las 2 plazas del salón-comedor (sofá-cama) cuentan SIEMPRE, también en una
    unidad de 1 dormitorio: un dormitorio doble (2) + sofá-cama (2) = 4 personas;
    un estudio = 2 (cama) + 2 (sofá) = 4. Es la base común de las dos reglas que
    dependen de la ocupación: el 2º baño (`banos_apartamento`) y la superficie
    adicional del salón (`salon_min_apartamento`).
    """
    return plazas_dormitorios + PLAZAS_SALON


def banos_apartamento(categoria: str, plazas_dormitorios: int) -> int:
    """Nº de baños de un apartamento turístico (Decreto 194/2010).

    Siempre 1 baño, salvo que la ocupación de la unidad supere el umbral de su
    categoría (en llaves), en cuyo caso se añade un 2º baño. La ocupación es
    `ocupacion_unidad` = plazas de los dormitorios + PLAZAS_SALON (2 del salón):

      - 1L / 2L → 2 baños si la unidad alberga MÁS DE 5 personas.
      - 3L / 4L → 2 baños si la unidad alberga MÁS DE 4 personas.

    Ej.: 2 dormitorios dobles = 4 plazas + 2 del salón = 6 personas → 2 baños en
    cualquier categoría. Todos los baños son completos (ducha, inodoro, lavabo).
    """
    personas = ocupacion_unidad(plazas_dormitorios)
    umbral = 5 if categoria in ("1L", "2L") else 4
    return 2 if personas > umbral else 1


def salon_min_apartamento(categoria: str, plazas_dormitorios: int) -> float:
    """m² mínimos del salón-comedor de un apartamento turístico (Anexo A1.3/A1.4).

    El salón-comedor base cubre "hasta 4 personas"; por cada persona por encima de
    la 4ª se añade `SUP_ADICIONAL_PLAZA[categoria]`. La ocupación incluye las 2
    plazas del salón (ver `ocupacion_unidad`): un estudio o una unidad de 1
    dormitorio doble (4 personas) se quedan en el mínimo; a partir de la 5ª persona
    el salón crece.

    Ej. (4L, SUP = 4): doble (2+2=4) → 16; triple (3+2=5) → 20; cuádruple
    (4+2=6) → 24; 2 dobles (4+2=6) → 24.
    """
    extra = max(0, ocupacion_unidad(plazas_dormitorios) - 4)
    return MIN_SALON_COMEDOR[categoria] + SUP_ADICIONAL_PLAZA[categoria] * extra


def _cat_validada(categoria: str, grupo: str) -> str:
    """Normaliza la categoría según el grupo (conjuntos solo admite 1L/2L)."""
    if grupo == "conjuntos":
        return categoria if categoria in ("1L", "2L") else "2L"
    return categoria if categoria in MIN_SALON_COMEDOR else "2L"


def _tip_validada(tipologia: str) -> str:
    return tipologia if tipologia in TIPOLOGIAS else "doble"


# ─── Programa interior por unidad ─────────────────────────────────────────
def programa_apartamentos(
    tipologia: str,
    categoria: str,
    util_disponible: float,
    grupo: str = "edificios",
) -> list[Estancia]:
    """Estancias COMPUTABLES de un apartamento turístico (categoría/tipología/grupo).

    Devuelve únicamente las estancias que **computan** a efectos de la normativa
    turística (salón-comedor, dormitorio, cocina, baño). La circulación de acceso
    (vestíbulo/pasillo interior de la unidad) NO se modela aquí: es un espacio NO
    computable que la capa de serialización añade como remanente del útil.

    `util_disponible` es el presupuesto COMPUTABLE a repartir entre estancias: las
    estancias devueltas suman ese presupuesto (cocina y baño en su mínimo práctico;
    salón-comedor y dormitorio escalan proporcionalmente a sus mínimos del Anexo,
    nunca por debajo de ellos). Con `util_disponible=0` cada estancia cae a su
    mínimo (lo aprovecha `_base_util`).
    """
    cat = _cat_validada(categoria, grupo)
    tip = _tip_validada(tipologia)
    bano_min = MIN_BANO[cat]

    if tip == "estudio":
        # Anexo I.3/I.4: el estudio es una estancia única (salón-comedor que hace
        # también de dormitorio) + cocina + baño, piezas independientes con su
        # propio mínimo. La estancia absorbe el resto del presupuesto computable.
        est = MIN_ESTUDIO[cat]
        cocina_min = MIN_COCINA[cat]
        cocina_t = cocina_min
        bano_t = bano_min
        salon_t = max(est, util_disponible - cocina_t - bano_t)
        return [
            Estancia("salon_comedor", "publica", est, round(salon_t, 2)),
            Estancia("cocina", "publica", cocina_min, round(cocina_t, 2)),
            Estancia("bano", "servicio", bano_min, round(bano_t, 2)),
        ]

    plazas = PLAZAS.get(tip, 2)
    # Salón-comedor: mínimo del Anexo + adicional por ocupación > 4 (incl. salón).
    salon_min = salon_min_apartamento(cat, plazas)
    dorm_min = MIN_DORMITORIO[tip][cat]
    cocina_min = MIN_COCINA[cat]

    # Cocina y baño(s): tamaño práctico fijo en su mínimo (no escalan con la superficie).
    # Nº de baños por ocupación y categoría (Decreto 194/2010): 1, o 2 si la unidad
    # supera el umbral de personas de su categoría en llaves.
    cocina_t = cocina_min
    n_banos = banos_apartamento(cat, plazas)
    fijas_t = cocina_t + n_banos * bano_min

    # Salón-comedor y dormitorio absorben el resto del presupuesto computable,
    # proporcional a sus mínimos; nunca por debajo del mínimo del Anexo.
    resto = max(0.0, util_disponible - fijas_t)
    base = salon_min + dorm_min
    if base > 0 and resto > 0:
        salon_t = max(salon_min, resto * salon_min / base)
        dorm_t = max(dorm_min, resto * dorm_min / base)
    else:
        salon_t, dorm_t = salon_min, dorm_min

    estancias = [
        Estancia("salon_comedor", "publica", salon_min, round(salon_t, 2)),
        Estancia("dormitorio_1", "privada", dorm_min, round(dorm_t, 2)),
        Estancia("cocina", "publica", cocina_min, round(cocina_t, 2)),
    ]
    for nombre in nombres_banos(n_banos):
        estancias.append(Estancia(nombre, "servicio", bano_min, round(bano_min, 2)))
    return estancias


def _base_util(categoria: str, tipologia: str, grupo: str) -> float:
    """Suma de mínimos de las estancias = útil mínimo neto de la unidad."""
    return sum(e.area_min_m2 for e in programa_apartamentos(tipologia, categoria, 0.0, grupo))


def util_objetivo_apartamento(categoria: str, tipologia: str, grupo: str = "edificios") -> float:
    """Objetivo de m² útil por unidad: mínimos + 15% (circulación interna)."""
    return round(_base_util(categoria, tipologia, grupo) * 1.15, 2)


def util_minimo_apartamento(categoria: str, tipologia: str, grupo: str = "edificios") -> float:
    """Mínimo viable (suma de mínimos del Anexo)."""
    return round(_base_util(categoria, tipologia, grupo), 2)


# ─── Programa interior por COMBINACIÓN de dormitorios (§2.5 · paradigma nuevo) ──
# Un apartamento turístico se clasifica por su nº de dormitorios; cada dormitorio
# se dimensiona por su ocupación. Una `ComboDormitorios` describe la combinación
# concreta de ocupaciones (p. ej. 1 individual + 1 doble). El estudio es N=0 y se
# delega al sizer monodormitorio (`tipologia="estudio"`: estancia única que hace
# de salón y dormitorio + cocina + baño). El resto compone: salón-comedor + N
# dormitorios + cocina + baño(s).
#
# La ocupación de la unidad = Σ plazas de los dormitorios + 2 del salón
# (`ocupacion_unidad`): gobierna la superficie adicional del salón (por cada
# persona por encima de la 4ª) y el 2º baño obligatorio (>5 personas en 1L/2L,
# >4 en 3L/4L).
def _plazas_combo(combo: ComboDormitorios) -> int:
    """Ocupación total = Σ plazas de los dormitorios (PLAZAS por ocupación)."""
    return combo.plazas(PLAZAS)


def util_minimo_combo(
    combo: ComboDormitorios, categoria: str, grupo: str = "edificios",
) -> float:
    """Útil mínimo viable de la combinación (suma de mínimos del Anexo)."""
    cat = _cat_validada(categoria, grupo)
    if combo.es_estudio:
        return util_minimo_apartamento(cat, "estudio", grupo)
    plazas = _plazas_combo(combo)
    salon_min = salon_min_apartamento(cat, plazas)
    dorm_min_total = sum(
        MIN_DORMITORIO[tam][cat] * n for tam, n in combo.composicion.items()
    )
    n_banos = banos_apartamento(cat, plazas)
    total = salon_min + dorm_min_total + MIN_COCINA[cat] + n_banos * MIN_BANO[cat]
    return round(total, 2)


def util_objetivo_combo(
    combo: ComboDormitorios, categoria: str, grupo: str = "edificios",
) -> float:
    """Objetivo de m² útil de la combinación: mínimos + 15% (circulación interna)."""
    return round(util_minimo_combo(combo, categoria, grupo) * 1.15, 2)


def descriptor_tipologia_combo(
    combo: ComboDormitorios, categoria: str, grupo: str = "edificios",
) -> TipologiaUnidadDescriptor:
    """Descriptor para el reparto multi-tipología a partir de una combinación.

    El `slug` es el slug canónico de la combinación (`"doble*1+individual*1"`),
    que la serialización reconoce vía `es_slug_combo` para regenerar el programa.
    """
    cat = _cat_validada(categoria, grupo)
    util_obj = util_objetivo_combo(combo, cat, grupo)
    util_min = util_minimo_combo(combo, cat, grupo)
    return TipologiaUnidadDescriptor(
        slug=combo.slug,
        util_objetivo=util_obj,
        util_minimo=util_min,
        util_maximo=round(util_obj * 1.25, 2),
        n_dorms_label=combo.n_dorms,
        tipo_unidad="apartamento",
        plazas=_plazas_combo(combo),
    )


def programa_apartamentos_combo(
    combo: ComboDormitorios,
    categoria: str,
    util_disponible: float,
    grupo: str = "edificios",
) -> list[Estancia]:
    """Estancias COMPUTABLES de un apartamento de N dormitorios (combinación).

    Análogo a `programa_apartamentos` pero con un dormitorio por cada elemento de
    la combinación (`dormitorio_1 … dormitorio_N`, en orden canónico). El estudio
    (N=0) reusa el sizer monodormitorio. Cocina y baño(s) van a su mínimo; el
    salón-comedor y los dormitorios absorben el presupuesto computable restante,
    proporcional a sus mínimos y nunca por debajo de ellos (con `util_disponible=0`
    cada estancia cae a su mínimo, igual que el sizer base).
    """
    cat = _cat_validada(categoria, grupo)
    if combo.es_estudio:
        return programa_apartamentos("estudio", cat, util_disponible, grupo)

    plazas = _plazas_combo(combo)
    salon_min = salon_min_apartamento(cat, plazas)
    cocina_min = MIN_COCINA[cat]
    bano_min = MIN_BANO[cat]

    # Un dormitorio por unidad de la composición (orden canónico = orden del slug).
    dorms: list[tuple[str, float]] = []
    for tam in sorted(combo.composicion):
        for _ in range(combo.composicion[tam]):
            dorms.append((tam, MIN_DORMITORIO[tam][cat]))
    dorm_min_total = sum(m for _, m in dorms)

    # Nº de baños por ocupación y categoría (Decreto 194/2010): 1, o 2 si la unidad
    # supera el umbral de personas de su categoría (ver banos_apartamento).
    n_banos = banos_apartamento(cat, plazas)

    # Cocina y baño(s): tamaño práctico fijo en su mínimo.
    fijas_t = cocina_min + n_banos * bano_min

    # Salón-comedor y dormitorios escalan proporcionalmente a sus mínimos.
    resto = max(0.0, util_disponible - fijas_t)
    base = salon_min + dorm_min_total
    factor = (resto / base) if (base > 0 and resto > 0) else 1.0

    estancias = [
        Estancia("salon_comedor", "publica", salon_min, round(max(salon_min, salon_min * factor), 2)),
    ]
    for i, (_tam, dmin) in enumerate(dorms, start=1):
        estancias.append(
            Estancia(f"dormitorio_{i}", "privada", dmin, round(max(dmin, dmin * factor), 2))
        )
    estancias.append(Estancia("cocina", "publica", cocina_min, round(cocina_min, 2)))
    for nombre in nombres_banos(n_banos):
        estancias.append(Estancia(nombre, "servicio", bano_min, round(bano_min, 2)))
    return estancias


# ─── Áreas comunes obligatorias (Decreto 194/2010) ────────────────────────
def areas_comunes_obligatorias(
    n_unidades_estimado: int,
    categoria: str,
    grupo: str = "edificios",
) -> dict[str, float]:
    """Servicios comunes mínimos por edificio, con los valores EXACTOS del PDF.

    - **Vestíbulo de recepción / conserjería**: solo obligatorio si hay >15 u.a.
      (0,5/0,4/0,3/0,2 m² por u.a. en 4L/3L/2L/1L).
    - **Áreas sociales**: solo exigibles en 4L (2 m²/u.a.) y 3L (1,5 m²/u.a.);
      2L/1L y el grupo "conjuntos" sin exigencia.
    """
    cat = _cat_validada(categoria, grupo)
    out: dict[str, float] = {}

    if grupo != "conjuntos":
        area_social_por_ua = {"1L": 0.0, "2L": 0.0, "3L": 1.5, "4L": 2.0}[cat]
        if area_social_por_ua > 0:
            out["areas_sociales"] = round(area_social_por_ua * n_unidades_estimado, 2)

    vest_por_ua = {"1L": 0.2, "2L": 0.3, "3L": 0.4, "4L": 0.5}[cat]
    if n_unidades_estimado > 15:
        out["vestibulo_recepcion"] = round(vest_por_ua * n_unidades_estimado, 2)

    return out


def total_comunes_obligatorias_m2(
    n_unidades_estimado: int,
    categoria: str,
    grupo: str = "edificios",
) -> float:
    return sum(areas_comunes_obligatorias(n_unidades_estimado, categoria, grupo).values())


# ─── Descriptor de tipología y ProgramaUso ────────────────────────────────
def descriptor_tipologia_apartamento(
    categoria: str,
    tipologia: str,
    grupo: str = "edificios",
) -> TipologiaUnidadDescriptor:
    """Descriptor para el reparto multi-tipología (mezcla por planta)."""
    tip = _tip_validada(tipologia)
    util_obj = util_objetivo_apartamento(categoria, tip, grupo)
    util_min = util_minimo_apartamento(categoria, tip, grupo)
    return TipologiaUnidadDescriptor(
        slug=tip,
        util_objetivo=util_obj,
        util_minimo=util_min,
        util_maximo=round(util_obj * 1.25, 2),
        n_dorms_label=PLAZAS.get(tip, 2),
        tipo_unidad="apartamento",
        plazas=PLAZAS.get(tip, 2),
    )


def programa_uso_apartamento_combo(
    combo: ComboDormitorios,
    categoria: str,
    n_unidades_estimado: int = 1,
    grupo: str = "edificios",
) -> ProgramaUso:
    """Descriptor de uso para una combinación de dormitorios (§2.5).

    Hermano de `programa_uso_apartamento` pero dimensionado desde la combinación;
    las áreas comunes obligatorias son idénticas (dependen de la categoría y del
    nº de unidades, no de la composición de la unidad).
    """
    cat = _cat_validada(categoria, grupo)
    util_obj = util_objetivo_combo(combo, cat, grupo)
    util_min = util_minimo_combo(combo, cat, grupo)
    comunes = total_comunes_obligatorias_m2(n_unidades_estimado, cat, grupo)
    return ProgramaUso(
        util_objetivo_unidad_m2=util_obj,
        area_min_unidad_m2=util_min,
        util_max_unidad_m2=round(util_obj * 1.25, 2),
        n_dormitorios=combo.n_dorms,
        tipo_unidad="apartamento",
        area_servicios_obligatorios_m2=comunes,
    )


def programa_uso_apartamento(
    categoria: str,
    tipologia: str,
    n_unidades_estimado: int = 1,
    grupo: str = "edificios",
) -> ProgramaUso:
    """Descriptor de uso (incluye áreas comunes obligatorias dimensionadas)."""
    tip = _tip_validada(tipologia)
    util_obj = util_objetivo_apartamento(categoria, tip, grupo)
    util_min = util_minimo_apartamento(categoria, tip, grupo)
    comunes = total_comunes_obligatorias_m2(n_unidades_estimado, categoria, grupo)
    return ProgramaUso(
        util_objetivo_unidad_m2=util_obj,
        area_min_unidad_m2=util_min,
        util_max_unidad_m2=round(util_obj * 1.25, 2),
        n_dormitorios=0 if tip == "estudio" else 1,
        tipo_unidad="apartamento",
        area_servicios_obligatorios_m2=comunes,
    )
