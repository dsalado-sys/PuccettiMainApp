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
    MIN_BANO,
    MIN_COCINA,
    MIN_DORM_DOBLE,
    MIN_DORM_INDIVIDUAL,
    SALON_MAS_COCINA_MIN,
    SALON_MIN,
    UTIL_MAX,
    banos_vivienda,
    nombres_banos,
)

from .catalogo_superficies_sqlalchemy import AnexoIViviendaORM, ParametrosMotorViviendaORM
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


def _filas_anexo_i_vivienda() -> list[tuple[int, str, float, float, float | None]]:
    """Genera la matriz Anexo I.5 a partir de las constantes del motor.

    Cada tupla es `(n_dorms, estancia, min_m2, max_m2_util, area_target_m2)`.
    `area_target_m2 = None` indica que la estancia ESCALA con el útil
    disponible (salones, dormitorios). Valor concreto = tamaño fijo.

    Política de targets sembrada:
    - Estudio (0d): estancia única (salón+dormitorio)=18 + cocina=8 + baño=4 +
      circulación=3 = 33 m². Anexo I.5: el estudio tiene cocina y baño
      independientes (cocina independiente ≥ 7 m²); la estancia hace de salón y
      dormitorio.
    - 1d+: cocina=8, baño(s)=5 fijos; salón + dormitorios escalan al restante
      tras descontar la circulación interior (15% del útil). Nº de baños por nº
      de dormitorios (Anexo I.5): 1 hasta 2 dorms, 2 desde 3 dorms.
    - >4d (clave 5): tramo "más de 4 dormitorios" del Anexo I.5, con la
      Estancia (E)=24 y Estancia+comedor+cocina (E+C+K)=28.
    """
    filas: list[tuple[int, str, float, float, float | None]] = []
    # Estudio: estancia única + cocina + baño + circulación, target absoluto.
    util_max_estudio = UTIL_MAX[0]
    filas.append((0, "espacio_principal", 14.0, util_max_estudio, 18.0))
    filas.append((0, "cocina", MIN_COCINA, util_max_estudio, MIN_COCINA + 1.0))
    filas.append((0, "bano", MIN_BANO, util_max_estudio, 4.0))
    filas.append((0, "circulacion_interior", 0.0, util_max_estudio, 3.0))

    # 1d..4d y el tramo ">4d" (clave 5, con 5 dormitorios de referencia).
    for n in range(1, 6):
        util_max = UTIL_MAX.get(n, UTIL_MAX[4])
        filas.append((n, "salon", SALON_MIN.get(n, 24.0), util_max, None))
        filas.append((n, "salon_cocina", SALON_MAS_COCINA_MIN.get(n, 28.0), util_max, None))
        filas.append((n, "cocina", MIN_COCINA, util_max, MIN_COCINA + 1.0))
        filas.append((n, "dormitorio_1", MIN_DORM_DOBLE, util_max, None))
        for i in range(2, n + 1):
            filas.append((n, f"dormitorio_{i}", MIN_DORM_INDIVIDUAL, util_max, None))
        # Baños completos por nº de dormitorios: 1 hasta 2 dorms, 2 desde 3 dorms.
        for nombre in nombres_banos(banos_vivienda(n)):
            filas.append((n, nombre, MIN_BANO, util_max, MIN_BANO + 2.0))
    return filas


def sembrar_anexo_i_vivienda(session: Session, forzar: bool = False, commit: bool = True) -> None:
    """`commit=False` deja la transacción abierta para que el llamante (p. ej.
    `reset()`) confirme delete+seed de forma atómica."""
    if not forzar:
        existe = session.scalar(select(AnexoIViviendaORM).limit(1))
        if existe is not None:
            # Re-sincroniza targets en BBDD existente (idempotente).
            # No toca filas con `editable_por_usuario=1`.
            ahora = datetime.now(timezone.utc)
            for n_dorms, estancia, min_m2, max_m2, target in _filas_anexo_i_vivienda():
                orm = session.get(AnexoIViviendaORM, (n_dorms, estancia))
                if orm is None:
                    session.add(AnexoIViviendaORM(
                        n_dormitorios=n_dorms,
                        estancia=estancia,
                        min_m2=min_m2,
                        max_m2_util=max_m2,
                        area_target_m2=target,
                        editable_por_usuario=0,
                        actualizado_en=ahora,
                    ))
                elif orm.editable_por_usuario == 0:
                    orm.area_target_m2 = target
                    orm.actualizado_en = ahora
            if commit:
                session.commit()
            return
    ahora = datetime.now(timezone.utc)
    for n_dorms, estancia, min_m2, max_m2, target in _filas_anexo_i_vivienda():
        orm = session.get(AnexoIViviendaORM, (n_dorms, estancia))
        if orm is None:
            session.add(AnexoIViviendaORM(
                n_dormitorios=n_dorms,
                estancia=estancia,
                min_m2=min_m2,
                max_m2_util=max_m2,
                area_target_m2=target,
                editable_por_usuario=0,
                actualizado_en=ahora,
            ))
    if commit:
        session.commit()


def sembrar_parametros_motor_vivienda(session: Session, forzar: bool = False) -> None:
    """Inserta el singleton `parametros_motor_vivienda` si no existe."""
    if not forzar:
        existe = session.get(ParametrosMotorViviendaORM, 1)
        if existe is not None:
            return
    orm = session.get(ParametrosMotorViviendaORM, 1)
    if orm is None:
        orm = ParametrosMotorViviendaORM(
            id=1,
            pct_circulacion_interior_pct=15.0,
            umbral_minimo_estudio_m2=25.0,
            actualizado_en=datetime.now(timezone.utc),
        )
        session.add(orm)
    else:
        orm.pct_circulacion_interior_pct = 15.0
        orm.umbral_minimo_estudio_m2 = 25.0
        orm.actualizado_en = datetime.now(timezone.utc)
    session.commit()


def _filas_anexo_i_apartamentos() -> list[tuple[str, str, str, float, float]]:
    """Anexo I.3 (edificios) + áreas comunes obligatorias por categoría.

    Devuelve `(categoria, tipologia, estancia, min_m2, max_m2_util)`. `max_m2_util`
    es el útil mínimo de la unidad (suma de mínimos), compartido por sus estancias.
    Las áreas comunes usan `categoria = "comunes_<llaves>"` y `tipologia = "comunes"`.
    """
    from app.contextos.render_calculos.geometria.programa_apartamentos import (
        programa_apartamentos,
        areas_comunes_obligatorias,
        TIPOLOGIAS,
    )

    filas: list[tuple[str, str, str, float, float]] = []
    for cat in ("1L", "2L", "3L", "4L"):
        for tip in TIPOLOGIAS:
            estancias = programa_apartamentos(tip, cat, 0.0, grupo="edificios")
            base = round(sum(e.area_min_m2 for e in estancias), 2)
            for e in estancias:
                filas.append((cat, tip, e.nombre, e.area_min_m2, base))

    # Áreas comunes obligatorias por categoría (referencia n_unidades = 5).
    for cat in ("1L", "2L", "3L", "4L"):
        for servicio, m2 in areas_comunes_obligatorias(5, cat, "edificios").items():
            filas.append((f"comunes_{cat}", "comunes", servicio, m2, m2))
    return filas


def sembrar_anexo_i_apartamentos(session: Session, forzar: bool = False, commit: bool = True) -> None:
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
    if commit:
        session.commit()


# ─── Anexo I.4 — apartamentos turísticos · grupo "conjuntos" ───────────────
def _filas_anexo_i_apartamentos_conjuntos() -> list[tuple[str, str, str, float, float]]:
    """Anexo I.4 (Decreto 194/2010, conjuntos): solo 1L/2L; sin áreas sociales."""
    from app.contextos.render_calculos.geometria.programa_apartamentos import (
        programa_apartamentos,
        TIPOLOGIAS,
    )

    filas: list[tuple[str, str, str, float, float]] = []
    for cat in ("1L", "2L"):
        for tip in TIPOLOGIAS:
            estancias = programa_apartamentos(tip, cat, 0.0, grupo="conjuntos")
            base = round(sum(e.area_min_m2 for e in estancias), 2)
            for e in estancias:
                filas.append((cat, tip, e.nombre, e.area_min_m2, base))
    return filas


def sembrar_anexo_i_apartamentos_conjuntos(session: Session, forzar: bool = False, commit: bool = True) -> None:
    from .anexo_i_apartamentos_conjuntos_sqlalchemy import AnexoIApartamentosConjuntosORM
    if not forzar:
        existe = session.scalar(select(AnexoIApartamentosConjuntosORM).limit(1))
        if existe is not None:
            return
    ahora = datetime.now(timezone.utc)
    for cat, tip, estancia, min_m2, max_m2 in _filas_anexo_i_apartamentos_conjuntos():
        orm = session.get(AnexoIApartamentosConjuntosORM, (cat, tip, estancia))
        if orm is None:
            session.add(AnexoIApartamentosConjuntosORM(
                categoria=cat,
                tipologia=tip,
                estancia=estancia,
                min_m2=min_m2,
                max_m2_util=max_m2,
                editable_por_usuario=0,
                actualizado_en=ahora,
            ))
    if commit:
        session.commit()


# ─── Anexo I.2 — hoteles-apartamento (categorías por estrellas) ────────────
def _filas_anexo_i_hotel_apartamento() -> list[tuple[str, str, str, float, float]]:
    from app.contextos.render_calculos.geometria.programa_hotel_apartamento import (
        programa_hotel_apartamento,
        areas_sociales_obligatorias_hap,
        ESTRELLAS,
        TIPOLOGIAS,
    )

    filas: list[tuple[str, str, str, float, float]] = []
    for star in ESTRELLAS:
        for tip in TIPOLOGIAS:
            estancias = programa_hotel_apartamento(tip, star, 0.0)
            base = round(sum(e.area_min_m2 for e in estancias), 2)
            for e in estancias:
                filas.append((star, tip, e.nombre, e.area_min_m2, base))

    # Áreas sociales por u.a. (= Hotel del mismo nº de estrellas).
    for star in ESTRELLAS:
        for servicio, m2 in areas_sociales_obligatorias_hap(5, star).items():
            filas.append((f"comunes_{star}", "comunes", servicio, m2, m2))
    return filas


def sembrar_anexo_i_hotel_apartamento(session: Session, forzar: bool = False, commit: bool = True) -> None:
    from .anexo_i_hotel_apartamento_sqlalchemy import AnexoIHotelApartamentoORM
    if not forzar:
        existe = session.scalar(select(AnexoIHotelApartamentoORM).limit(1))
        if existe is not None:
            return
    ahora = datetime.now(timezone.utc)
    for cat, tip, estancia, min_m2, max_m2 in _filas_anexo_i_hotel_apartamento():
        orm = session.get(AnexoIHotelApartamentoORM, (cat, tip, estancia))
        if orm is None:
            session.add(AnexoIHotelApartamentoORM(
                categoria=cat,
                tipologia=tip,
                estancia=estancia,
                min_m2=min_m2,
                max_m2_util=max_m2,
                editable_por_usuario=0,
                actualizado_en=ahora,
            ))
    if commit:
        session.commit()


# ─── Anexo I.1 — hoteles / hostales / pensiones / albergues ────────────────
def _filas_anexo_i_hotelero() -> list[tuple[str, str, str, float, float]]:
    from app.contextos.render_calculos.geometria.programa_hotelero import (
        MIN_HABITACION,
        MIN_BANO_HOTELERO,
        BANO_INTERIOR_OBLIGATORIO,
        SALON_SOCIAL_MIN,
        AREA_SOCIAL_POR_UA,
        AREA_SOCIAL_POR_PLAZA,
        CATEGORIAS,
        util_minimo_habitacion,
    )

    filas: list[tuple[str, str, str, float, float]] = []
    for (cat, tipo), room_min in MIN_HABITACION.items():
        util_max = util_minimo_habitacion(cat, tipo)  # habitación + baño
        filas.append((cat, tipo, "habitacion", room_min, util_max))
        if BANO_INTERIOR_OBLIGATORIO[cat]:
            filas.append((cat, tipo, "bano", MIN_BANO_HOTELERO[cat], util_max))

    # Áreas sociales del establecimiento (salón + escala por u.a. o por plaza).
    for cat in CATEGORIAS:
        salon = SALON_SOCIAL_MIN[cat]
        if salon > 0:
            filas.append((f"comunes_{cat}", "comunes", "salon_social", salon, salon))
        por_ua = AREA_SOCIAL_POR_UA.get(cat, 0.0)
        if por_ua > 0:
            filas.append((f"comunes_{cat}", "comunes", "area_social_por_ua", por_ua, por_ua))
        por_plaza = AREA_SOCIAL_POR_PLAZA.get(cat, 0.0)
        if por_plaza > 0:
            filas.append((f"comunes_{cat}", "comunes", "area_social_por_plaza", por_plaza, por_plaza))
    return filas


def sembrar_anexo_i_hotelero(session: Session, forzar: bool = False, commit: bool = True) -> None:
    from .anexo_i_hotelero_sqlalchemy import AnexoIHoteleroORM
    if not forzar:
        existe = session.scalar(select(AnexoIHoteleroORM).limit(1))
        if existe is not None:
            return
    ahora = datetime.now(timezone.utc)
    for cat, tip, estancia, min_m2, max_m2 in _filas_anexo_i_hotelero():
        orm = session.get(AnexoIHoteleroORM, (cat, tip, estancia))
        if orm is None:
            session.add(AnexoIHoteleroORM(
                categoria=cat,
                tipologia=tip,
                estancia=estancia,
                min_m2=min_m2,
                max_m2_util=max_m2,
                editable_por_usuario=0,
                actualizado_en=ahora,
            ))
    if commit:
        session.commit()


def sembrar_todo(session: Session) -> None:
    """Punto único llamado desde `init_db()`."""
    sembrar_normativa_municipal(session)
    sembrar_anexo_i_vivienda(session)
    sembrar_anexo_i_apartamentos(session)
    sembrar_anexo_i_apartamentos_conjuntos(session)
    sembrar_anexo_i_hotel_apartamento(session)
    sembrar_anexo_i_hotelero(session)
    sembrar_parametros_motor_vivienda(session)
