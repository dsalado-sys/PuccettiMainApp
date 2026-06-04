"""Programa arquitectónico de apartamentos turísticos (Anexo I.4 + Decreto 194/2010).

Análogo a `programa.py` (vivienda VPO) pero ajustado a:
- **Categorías por llaves** (1L, 2L, 3L, 4L) del Decreto 194/2010 Junta de Andalucía.
- **Tipologías**: estudio, 1 dormitorio, 2 dormitorios, 3 dormitorios.

A más llaves, m² mínimo más alto por estancia. La función `programa_apartamentos`
devuelve `list[Estancia]` reutilizando la dataclass `Estancia` de vivienda — los
NOMBRES de estancia se mantienen compatibles con `interiores.py` (prefijos
`salon`, `dormitorio`, `cocina`, `bano`) para que el motor no necesite ramificar.

El Decreto 194/2010 impone además **áreas comunes obligatorias** (recepción /
conserjería, sala social, equipajes, instalaciones). En el MVP se restan del
techo útil sin generar geometría específica — ver §16.5 del plan.
"""
from __future__ import annotations

from .programa import Estancia
from .programa_uso import ProgramaUso


# ─── Tablas Anexo I.4 — m² útiles mínimos por (categoría, tipología) ──────
# Cifras conservadoras alineadas con el Decreto 194/2010 (lo que el técnico
# puede sobreescribir desde la BBDD `anexo_i_apartamentos`).
UTIL_MIN_APT: dict[tuple[str, str], float] = {
    ("1L", "estudio"): 25.0, ("2L", "estudio"): 28.0, ("3L", "estudio"): 32.0, ("4L", "estudio"): 38.0,
    ("1L", "1d"): 35.0,      ("2L", "1d"): 40.0,      ("3L", "1d"): 45.0,      ("4L", "1d"): 55.0,
    ("1L", "2d"): 50.0,      ("2L", "2d"): 55.0,      ("3L", "2d"): 65.0,      ("4L", "2d"): 75.0,
    ("1L", "3d"): 70.0,      ("2L", "3d"): 80.0,      ("3L", "3d"): 95.0,      ("4L", "3d"): 110.0,
}


# ─── Mínimos por estancia (escalan con categoría) ─────────────────────────
# Los nombres respetan los prefijos que reconoce `interiores.py:81-82`
# (principal: salon_/dormitorio_, servicio: cocina/bano/aseo).
MIN_SALON_COMEDOR_COCINA: dict[str, float] = {"1L": 12.0, "2L": 14.0, "3L": 16.0, "4L": 18.0}
MIN_DORM_PRINCIPAL: dict[str, float] = {"1L": 9.0, "2L": 10.0, "3L": 11.0, "4L": 13.0}
MIN_DORM_SECUNDARIO: dict[str, float] = {"1L": 7.0, "2L": 8.0, "3L": 9.0, "4L": 10.0}
MIN_BANO_APT: dict[str, float] = {"1L": 3.0, "2L": 3.5, "3L": 4.0, "4L": 4.5}


# ─── Programa interior por unidad ─────────────────────────────────────────
def programa_apartamentos(
    tipologia: str,
    categoria: str,
    util_disponible: float,
) -> list[Estancia]:
    """Lista de `Estancia` para un apartamento turístico de la categoría/tipología dada.

    Apartamentos turísticos casi siempre son **salón-comedor-cocina open plan**.
    No se generan vestíbulos individuales — el acceso es directo desde el pasillo
    común a la pieza de día.
    """
    cat = categoria if categoria in MIN_SALON_COMEDOR_COCINA else "2L"
    sala_min = MIN_SALON_COMEDOR_COCINA[cat]
    dorm1_min = MIN_DORM_PRINCIPAL[cat]
    dorm2_min = MIN_DORM_SECUNDARIO[cat]
    bano_min = MIN_BANO_APT[cat]

    if tipologia == "estudio":
        target_sala = max(sala_min + 8.0, util_disponible * 0.70)
        return [
            Estancia("salon_comedor", "publica", sala_min + 8.0, target_sala),
            Estancia("bano", "servicio", bano_min, bano_min + 1.0),
        ]

    estancias: list[Estancia] = [
        Estancia("salon_comedor", "publica", sala_min, max(sala_min, util_disponible * 0.35)),
    ]

    n_dorms_map = {"1d": 1, "2d": 2, "3d": 3}
    n_dorms = n_dorms_map.get(tipologia, 2)

    for i in range(n_dorms):
        if i == 0:
            estancias.append(Estancia("dormitorio_1", "privada", dorm1_min, dorm1_min + 2.0))
        else:
            estancias.append(Estancia(f"dormitorio_{i + 1}", "privada", dorm2_min, dorm2_min + 1.5))

    estancias.append(Estancia("bano", "servicio", bano_min, bano_min + 1.0))
    if n_dorms >= 2 and cat in ("3L", "4L"):
        # Categorías altas con 2+ dormitorios suelen llevar segundo baño.
        estancias.append(Estancia("aseo", "servicio", bano_min - 1.0, bano_min - 0.5))

    return estancias


def util_objetivo_apartamento(categoria: str, tipologia: str) -> float:
    """Paralelo a `programa.util_maximo` de vivienda. Devuelve el objetivo de m² útil
    del apartamento, con margen del 15% sobre el mínimo del Anexo I.4.
    """
    base = UTIL_MIN_APT.get((categoria, tipologia), 40.0)
    return round(base * 1.15, 2)


def util_minimo_apartamento(categoria: str, tipologia: str) -> float:
    """Mínimo viable (suma de mínimos + 15% de circulación interna)."""
    prog = programa_apartamentos(tipologia, categoria, util_disponible=util_objetivo_apartamento(categoria, tipologia))
    return round(sum(e.area_min_m2 for e in prog) * 1.15, 2)


# ─── Áreas comunes obligatorias (Decreto 194/2010) ────────────────────────
# Se restan del techo útil disponible antes de trocear las unidades.
def areas_comunes_obligatorias(
    n_unidades_estimado: int,
    categoria: str,
) -> dict[str, float]:
    """Servicios comunes mínimos por edificio.

    No se generan como geometría en el MVP — se acumulan como una sola línea en
    la tabla por planta y se descuentan del área útil que el motor reparte
    entre unidades.

    Valores derivados de las recomendaciones del Decreto 194/2010 y del uso
    habitual en apartamentos turísticos de pequeño/medio tamaño.
    """
    cat = categoria if categoria in MIN_SALON_COMEDOR_COCINA else "2L"
    base_recepcion = {"1L": 4.0, "2L": 6.0, "3L": 10.0, "4L": 15.0}[cat]
    base_sala_social = {"1L": 0.8, "2L": 1.2, "3L": 1.8, "4L": 2.5}[cat]  # m² por unidad

    return {
        "recepcion_conserjeria": max(base_recepcion, 4.0 + 0.5 * n_unidades_estimado),
        "sala_social": max(8.0, base_sala_social * n_unidades_estimado),
        "equipajes": max(1.5, 0.4 * n_unidades_estimado),
        "instalaciones": 3.0,
    }


def total_comunes_obligatorias_m2(
    n_unidades_estimado: int,
    categoria: str,
) -> float:
    return sum(areas_comunes_obligatorias(n_unidades_estimado, categoria).values())


# ─── Constructor del ProgramaUso para apartamentos ────────────────────────
TIPOLOGIA_A_NUM_DORMS = {"estudio": 0, "1d": 1, "2d": 2, "3d": 3}


def programa_uso_apartamento(
    categoria: str,
    tipologia: str,
    n_unidades_estimado: int = 1,
) -> ProgramaUso:
    """Construye el descriptor que `_generar_candidato` necesita para apartamentos.

    `n_unidades_estimado` se usa para dimensionar las áreas comunes obligatorias
    (que escalan con el nº total de unidades). Si no se conoce a priori, basta
    pasar 1 — la diferencia entre 1 y 10 unidades es <20 m² en comunes.
    """
    util_obj = util_objetivo_apartamento(categoria, tipologia)
    util_min = util_minimo_apartamento(categoria, tipologia)
    comunes = total_comunes_obligatorias_m2(n_unidades_estimado, categoria)
    return ProgramaUso(
        util_objetivo_unidad_m2=util_obj,
        area_min_unidad_m2=util_min,
        util_max_unidad_m2=util_obj * 1.25,
        n_dormitorios=TIPOLOGIA_A_NUM_DORMS.get(tipologia, 2),
        tipo_unidad="apartamento",
        area_servicios_obligatorios_m2=comunes,
    )
