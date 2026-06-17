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

from .programa import Estancia
from .programa_uso import ProgramaUso, TipologiaUnidadDescriptor


TIPOLOGIAS = ("estudio", "individual", "doble", "triple", "cuadruple")

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
    """Lista de `Estancia` de un apartamento turístico (categoría/tipología/grupo)."""
    cat = _cat_validada(categoria, grupo)
    tip = _tip_validada(tipologia)
    bano_min = MIN_BANO[cat]

    if tip == "estudio":
        est = MIN_ESTUDIO[cat]
        return [
            Estancia("salon_comedor", "publica", est, max(est, util_disponible * 0.78)),
            Estancia("bano", "servicio", bano_min, bano_min + 1.0),
        ]

    plazas = PLAZAS.get(tip, 2)
    # Salón-comedor base "hasta 4 personas" + superficie adicional desde la 5ª plaza.
    salon_min = MIN_SALON_COMEDOR[cat] + SUP_ADICIONAL_PLAZA[cat] * max(0, plazas - 4)
    dorm_min = MIN_DORMITORIO[tip][cat]
    cocina_min = MIN_COCINA[cat]

    estancias = [
        Estancia("salon_comedor", "publica", salon_min, max(salon_min, util_disponible * 0.32)),
        Estancia("dormitorio_1", "privada", dorm_min, dorm_min + 2.0),
        Estancia("cocina", "publica", cocina_min, cocina_min + 1.0),
        Estancia("bano", "servicio", bano_min, bano_min + 1.0),
    ]
    # Conjuntos (A1.4): 2º baño obligatorio si más de 5 usuarios.
    if grupo == "conjuntos" and plazas > 5:
        estancias.append(Estancia("aseo", "servicio", bano_min, bano_min))
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
