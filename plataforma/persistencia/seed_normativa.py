"""Seed inicial de la BBDD de normativa.

Carga:
1. Una entrada de `normativa_municipal` para "Sevilla / Sevilla" (PGOU 2006 casco).
2. La tabla `anexo_i_vivienda` con los mínimos del Anexo I.5 derivados de
   `geometria.programa` (constantes Junta de Andalucía VPO).

Idempotente: solo siembra si la tabla está vacía. Para resembrado forzado
existe el método `reset()` en cada adapter.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contextos.render_calculos.geometria.programa import (
    MIN_ASEO,
    MIN_BANO,
    MIN_COCINA,
    MIN_DORM_DOBLE,
    MIN_DORM_INDIVIDUAL,
    SALON_MAS_COCINA_MIN,
    SALON_MIN,
    UTIL_MAX,
)

from .catalogo_superficies_sqlalchemy import AnexoIViviendaORM
from .normativa_municipal_sqlalchemy import NormativaMunicipalORM


SEED_SEVILLA = {
    "municipio": "Sevilla",
    "provincia": "Sevilla",
    "coeficiente_edificabilidad": 2.5,
    "ocupacion_maxima_pct": 100.0,
    "n_plantas_max": 3,
    "retranqueo_fachada_m": 0.0,
    "retranqueo_linderos_m": 0.0,
    "usos_permitidos": ["residencial", "hotelero", "mixto"],
    "luz_recta_patio_min_m": 3.0,
    "area_patio_min_m2": 12.0,
    "tiene_atico_default": 0,
    "retranqueo_atico_m": 3.0,
    "atico_computa_edificabilidad": 0,
    "tiene_sotano_default": 0,
    "sotano_computa_edificabilidad": 0,
    "fuente_pgou": "PGOU Sevilla 2006 — casco histórico (orientativo).",
}


def sembrar_normativa_municipal(session: Session, forzar: bool = False) -> None:
    if not forzar:
        existe = session.scalar(select(NormativaMunicipalORM).limit(1))
        if existe is not None:
            return
    orm = session.get(NormativaMunicipalORM, (SEED_SEVILLA["municipio"], SEED_SEVILLA["provincia"]))
    if orm is None:
        orm = NormativaMunicipalORM(
            municipio=SEED_SEVILLA["municipio"],
            provincia=SEED_SEVILLA["provincia"],
            actualizado_en=datetime.now(timezone.utc),
        )
        session.add(orm)
    orm.coeficiente_edificabilidad = SEED_SEVILLA["coeficiente_edificabilidad"]
    orm.ocupacion_maxima_pct = SEED_SEVILLA["ocupacion_maxima_pct"]
    orm.n_plantas_max = SEED_SEVILLA["n_plantas_max"]
    orm.retranqueo_fachada_m = SEED_SEVILLA["retranqueo_fachada_m"]
    orm.retranqueo_linderos_m = SEED_SEVILLA["retranqueo_linderos_m"]
    orm.usos_permitidos_json = json.dumps(SEED_SEVILLA["usos_permitidos"])
    orm.luz_recta_patio_min_m = SEED_SEVILLA["luz_recta_patio_min_m"]
    orm.area_patio_min_m2 = SEED_SEVILLA["area_patio_min_m2"]
    orm.tiene_atico_default = SEED_SEVILLA["tiene_atico_default"]
    orm.retranqueo_atico_m = SEED_SEVILLA["retranqueo_atico_m"]
    orm.atico_computa_edificabilidad = SEED_SEVILLA["atico_computa_edificabilidad"]
    orm.tiene_sotano_default = SEED_SEVILLA["tiene_sotano_default"]
    orm.sotano_computa_edificabilidad = SEED_SEVILLA["sotano_computa_edificabilidad"]
    orm.fuente_pgou = SEED_SEVILLA["fuente_pgou"]
    orm.actualizado_por = "seed"
    orm.actualizado_en = datetime.now(timezone.utc)
    session.commit()


def _filas_anexo_i_vivienda() -> list[tuple[int, str, float, float]]:
    """Genera la matriz Anexo I.5 a partir de las constantes del motor."""
    filas: list[tuple[int, str, float, float]] = []
    # estudio
    filas.append((0, "salon_cocina", 20.0, UTIL_MAX[0]))
    filas.append((0, "dormitorio", MIN_DORM_DOBLE, UTIL_MAX[0]))
    filas.append((0, "bano", MIN_BANO, UTIL_MAX[0]))
    # 1d..5d
    for n in range(1, 6):
        util_max = UTIL_MAX.get(n, 150.0)
        filas.append((n, "salon", SALON_MIN.get(n, 18.0), util_max))
        filas.append((n, "salon_cocina", SALON_MAS_COCINA_MIN.get(n, 24.0), util_max))
        filas.append((n, "cocina", MIN_COCINA, util_max))
        filas.append((n, "dormitorio_1", MIN_DORM_DOBLE, util_max))
        for i in range(2, n + 1):
            filas.append((n, f"dormitorio_{i}", MIN_DORM_INDIVIDUAL, util_max))
        filas.append((n, "bano", MIN_BANO, util_max))
        if util_max > 70 or n >= 3:
            filas.append((n, "aseo", MIN_ASEO, util_max))
    return filas


def sembrar_anexo_i_vivienda(session: Session, forzar: bool = False) -> None:
    if not forzar:
        existe = session.scalar(select(AnexoIViviendaORM).limit(1))
        if existe is not None:
            return
    ahora = datetime.now(timezone.utc)
    for n_dorms, estancia, min_m2, max_m2 in _filas_anexo_i_vivienda():
        orm = session.get(AnexoIViviendaORM, (n_dorms, estancia))
        if orm is None:
            session.add(AnexoIViviendaORM(
                n_dormitorios=n_dorms,
                estancia=estancia,
                min_m2=min_m2,
                max_m2_util=max_m2,
                editable_por_usuario=0,
                actualizado_en=ahora,
            ))
    session.commit()


def _filas_anexo_i_apartamentos() -> list[tuple[str, str, str, float, float]]:
    """Anexo I.4 (Decreto 194/2010) + áreas comunes obligatorias por categoría.

    Devuelve `(categoria, tipologia, estancia, min_m2, max_m2_util)`.
    Las áreas comunes usan `categoria = "comunes_<llaves>"` y `tipologia = "comunes"`.
    """
    from app.contextos.render_calculos.geometria.programa_apartamentos import (
        UTIL_MIN_APT,
        MIN_SALON_COMEDOR_COCINA,
        MIN_DORM_PRINCIPAL,
        MIN_DORM_SECUNDARIO,
        MIN_BANO_APT,
        areas_comunes_obligatorias,
    )

    filas: list[tuple[str, str, str, float, float]] = []

    for (cat, tip), util_max in UTIL_MIN_APT.items():
        # Salón-comedor-cocina (open plan típico en apt. turísticos)
        filas.append((cat, tip, "salon_comedor", MIN_SALON_COMEDOR_COCINA[cat], util_max))
        if tip == "estudio":
            filas.append((cat, tip, "bano", MIN_BANO_APT[cat], util_max))
            continue
        n_dorms = {"1d": 1, "2d": 2, "3d": 3}[tip]
        for i in range(1, n_dorms + 1):
            estancia = "dormitorio_1" if i == 1 else f"dormitorio_{i}"
            min_m2 = MIN_DORM_PRINCIPAL[cat] if i == 1 else MIN_DORM_SECUNDARIO[cat]
            filas.append((cat, tip, estancia, min_m2, util_max))
        filas.append((cat, tip, "bano", MIN_BANO_APT[cat], util_max))
        if n_dorms >= 2 and cat in ("3L", "4L"):
            filas.append((cat, tip, "aseo", MIN_BANO_APT[cat] - 1.0, util_max))

    # Áreas comunes obligatorias por categoría (referencia n_unidades = 5).
    for cat in ("1L", "2L", "3L", "4L"):
        comunes = areas_comunes_obligatorias(n_unidades_estimado=5, categoria=cat)
        for servicio, m2 in comunes.items():
            filas.append((f"comunes_{cat}", "comunes", servicio, m2, m2))

    return filas


def sembrar_anexo_i_apartamentos(session: Session, forzar: bool = False) -> None:
    from .anexo_i_apartamentos_sqlalchemy import AnexoIApartamentosORM
    if not forzar:
        existe = session.scalar(select(AnexoIApartamentosORM).limit(1))
        if existe is not None:
            return
    ahora = datetime.now(timezone.utc)
    for cat, tip, estancia, min_m2, max_m2 in _filas_anexo_i_apartamentos():
        orm = session.get(AnexoIApartamentosORM, (cat, tip, estancia))
        if orm is None:
            session.add(AnexoIApartamentosORM(
                categoria=cat,
                tipologia=tip,
                estancia=estancia,
                min_m2=min_m2,
                max_m2_util=max_m2,
                editable_por_usuario=0,
                actualizado_en=ahora,
            ))
    session.commit()


def sembrar_todo(session: Session) -> None:
    """Punto único llamado desde `init_db()`."""
    sembrar_normativa_municipal(session)
    sembrar_anexo_i_vivienda(session)
    sembrar_anexo_i_apartamentos(session)
