"""Adapter SQLAlchemy del catálogo de superficies Anexo I (editable).

En MVP solo se expone vivienda (Anexo I.5). Hotel y apartamentos turísticos
quedan como tablas vacías que se sembrarán cuando se implemente esos usos.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .sqlalchemy_base import Base


# Estancias que no son "habitaciones" editables (circulación es un derivado del
# útil, no una superficie mínima de estancia): se excluyen del editor de la UI.
_ESTANCIAS_NO_EDITABLES = {"circulacion_interior"}

# Clave sintética para editar el ÚTIL MÁXIMO de una tipología (no es una
# estancia; es el techo de la unidad, columna `max_m2_util`). El editor la envía
# como una fila aparte por tipología (R3).
_UTIL_MAXIMO_ESTANCIA = "_util_maximo"


def _exigir_min_le_max(valor_min: float, maximo: float, ref: str) -> None:
    """Invariante de fila `min_m2 ≤ max_m2_util`: rechaza romperlo antes de
    persistir (un mínimo por encima del útil máximo dejaría la tipología en
    estado imposible para el dimensionado)."""
    if valor_min > maximo:
        raise ValueError(
            f"El mínimo ({valor_min:g} m²) no puede superar el útil máximo "
            f"({maximo:g} m²) de {ref}."
        )


def _clave_global_estancia(estancia: str) -> str | None:
    """Clave de agrupación de las estancias cuyo mínimo es GLOBAL (no varía por
    nº de dormitorios): dormitorio principal/mínimo, cocina, baño, aseo. Las
    estancias por tipología (Estancia y Estancia+comedor+cocina, y el espacio
    único del estudio) devuelven None.

    Resuelve el colapso last-row-wins de `consolidadas_vivienda`: el editor las
    muestra una sola vez y al editar una se propaga a todas las tipologías
    (ver `CatalogoSuperficiesSQLAlchemy.actualizar`).
    """
    if estancia == "cocina":
        return "cocina"
    if estancia == "bano" or estancia.startswith("bano_"):
        return "bano"
    if estancia == "aseo" or estancia.startswith("aseo_"):
        return "aseo"
    if estancia == "dormitorio_1":
        return "dormitorio_principal"
    if estancia.startswith("dormitorio_"):
        return "dormitorio_minimo"
    return None


def _etiqueta_global(clave: str) -> str:
    """Etiqueta legible de un mínimo global, independiente de la tipología."""
    return {
        "cocina": "Cocina independiente",
        "bano": "Baño",
        "aseo": "Aseo",
        "dormitorio_principal": "Dormitorio principal",
        "dormitorio_minimo": "Dormitorio mínimo",
    }.get(clave, clave)


def _etiqueta_estancia(estancia: str) -> str:
    """Nombre legible de una estancia por tipología para el editor."""
    base = {
        "salon": "Estancia (E)",
        "salon_cocina": "Estancia + comedor + cocina",
        "espacio_principal": "Estancia principal (salón-dormitorio)",
        "cocina": "Cocina independiente",
        "dormitorio_1": "Dormitorio principal",
        "bano": "Baño",
        "aseo": "Aseo",
    }
    if estancia in base:
        return base[estancia]
    if estancia.startswith("dormitorio_"):
        return f"Dormitorio {estancia.split('_', 1)[1]}"
    if estancia.startswith("bano_"):
        return f"Baño {estancia.split('_', 1)[1]}"
    return estancia


def _orden_estancia(estancia: str) -> tuple[int, int]:
    """Orden de presentación de las estancias dentro de una tipología."""
    fijo = {"salon": 0, "salon_cocina": 1, "espacio_principal": 2, "cocina": 3, "aseo": 4}
    if estancia in fijo:
        return (fijo[estancia], 0)
    if estancia.startswith("dormitorio_"):
        return (10, int(estancia.split("_", 1)[1]))
    if estancia == "bano":
        return (20, 0)
    if estancia.startswith("bano_"):
        return (20, int(estancia.split("_", 1)[1]))
    return (99, 0)


class AnexoIViviendaORM(Base):
    """Una fila por (n_dormitorios, estancia) con su mínimo y máximo (m²).

    `area_target_m2` es opcional: si tiene valor, la estancia recibe ese
    tamaño FIJO en el programa generado por `programa_vivienda`. Si es NULL,
    la estancia escala proporcionalmente a su `min_m2` para consumir el útil
    sobrante (típico de salón y dormitorios). Cocina/baño/aseo se sembran con
    target fijo porque su tamaño no escala con el útil de la vivienda.
    """

    __tablename__ = "anexo_i_vivienda"

    n_dormitorios: Mapped[int] = mapped_column(Integer, primary_key=True)
    estancia: Mapped[str] = mapped_column(String(40), primary_key=True)
    min_m2: Mapped[float] = mapped_column(Float, nullable=False)
    max_m2_util: Mapped[float] = mapped_column(Float, nullable=False)
    area_target_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    editable_por_usuario: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ParametrosMotorViviendaORM(Base):
    """Parámetros globales de la política de reparto del programa de vivienda.

    Singleton: una sola fila (id=1). Los valores aquí controlan cómo
    `programa_vivienda` distribuye el útil disponible entre estancias.
    """

    __tablename__ = "parametros_motor_vivienda"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    pct_circulacion_interior_pct: Mapped[float] = mapped_column(Float, nullable=False, default=15.0)
    umbral_minimo_estudio_m2: Mapped[float] = mapped_column(Float, nullable=False, default=25.0)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogoSuperficiesSQLAlchemy:
    """Implementación del puerto CatalogoSuperficiesRepositorio.

    MVP: solo vivienda. Los nombres de estancia usados como clave coinciden con
    las constantes de `geometria.programa` (`salon`, `cocina`, `bano`,
    `dormitorio_1`, ..., `aseo`).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def superficies_vivienda(self, n_dormitorios: int) -> dict[str, float]:
        filas = self._session.scalars(
            select(AnexoIViviendaORM).where(AnexoIViviendaORM.n_dormitorios == n_dormitorios)
        ).all()
        out: dict[str, float] = {}
        for f in filas:
            out[f.estancia + "_min"] = f.min_m2
            out[f.estancia + "_max"] = f.max_m2_util
        return out

    def filas_vivienda(self) -> list[dict]:
        """Filas crudas de superficies mínimas para el editor de la UI.

        Una entrada por (n_dormitorios, estancia) con su mínimo (m²) y etiqueta
        legible, ordenadas por tipología y orden de presentación. Excluye las
        estancias no editables (circulación). El frontend las agrupa por nº de
        dormitorios para construir la tabla por tipología (incluido estudio=0).
        """
        filas = self._session.scalars(select(AnexoIViviendaORM)).all()
        out: list[dict] = []
        for f in filas:
            if f.estancia in _ESTANCIAS_NO_EDITABLES:
                continue
            clave = _clave_global_estancia(f.estancia)
            es_global = clave is not None
            out.append({
                "n_dormitorios": f.n_dormitorios,
                "estancia": f.estancia,
                "etiqueta": _etiqueta_global(clave) if es_global else _etiqueta_estancia(f.estancia),
                "min_m2": f.min_m2,
                "editable_por_usuario": bool(f.editable_por_usuario),
                # "global" → mínimo común a todas las tipologías (el editor lo
                # muestra una vez); "tipologia" → varía por nº de dormitorios.
                "ambito": "global" if es_global else "tipologia",
                "clave_global": clave or "",
            })
        out.sort(key=lambda r: (r["n_dormitorios"], _orden_estancia(r["estancia"])))
        return out

    def util_maximo_por_tipologia(self) -> dict[int, float]:
        """Útil máximo editable por nº de dormitorios (techo de la unidad, R3).

        Es el máximo de `max_m2_util` entre las estancias de cada tipología — el
        mismo valor que `consolidadas_vivienda` consolida como `UTIL_MAX[n]`.
        """
        out: dict[int, float] = {}
        for f in self._session.scalars(select(AnexoIViviendaORM)).all():
            n = f.n_dormitorios
            if n not in out or f.max_m2_util > out[n]:
                out[n] = f.max_m2_util
        return out

    def consolidadas_vivienda(self) -> dict:
        """Devuelve todos los mínimos + targets consolidados como dicts.
        Estructura:
            {
                "MIN_DORM_INDIVIDUAL": float, "MIN_DORM_DOBLE": float,
                "MIN_COCINA": float, "MIN_BANO": float, "MIN_ASEO": float,
                "SALON_MIN": {1: float, ...}, "SALON_MAS_COCINA_MIN": {1: ...},
                "UTIL_MAX": {0: ..., 1: ..., ...},
                "AREA_TARGET_VIVIENDA": {n_dorms: {estancia: target_m2 | None}},
                "PCT_CIRCULACION_INTERIOR_VIVIENDA": float (15.0),
                "UMBRAL_MINIMO_ESTUDIO_M2": float (25.0),
            }
        Si la BBDD aún no tiene filas, devuelve {} (caller usa defaults).
        """
        filas = self._session.scalars(select(AnexoIViviendaORM)).all()
        if not filas:
            return {}
        salon_min: dict[int, float] = {}
        salon_mas_cocina_min: dict[int, float] = {}
        util_max: dict[int, float] = {}
        valores: dict[str, float] = {}
        area_target: dict[int, dict[str, float | None]] = {}
        for f in filas:
            n = f.n_dormitorios
            est = f.estancia
            if est == "salon":
                salon_min[n] = f.min_m2
            elif est == "salon_cocina":
                salon_mas_cocina_min[n] = f.min_m2
            elif est == "cocina":
                valores["MIN_COCINA"] = f.min_m2
            elif est == "bano":
                valores["MIN_BANO"] = f.min_m2
            elif est == "aseo":
                valores["MIN_ASEO"] = f.min_m2
            elif est == "espacio_principal":
                valores["MIN_ESPACIO_PRINCIPAL"] = f.min_m2
            elif est == "dormitorio_1":
                valores["MIN_DORM_DOBLE"] = f.min_m2
            elif est.startswith("dormitorio_") and est != "dormitorio_1":
                valores["MIN_DORM_INDIVIDUAL"] = f.min_m2
            if n not in util_max or f.max_m2_util > util_max[n]:
                util_max[n] = f.max_m2_util
            area_target.setdefault(n, {})[est] = f.area_target_m2
        out = dict(valores)
        if salon_min: out["SALON_MIN"] = salon_min
        if salon_mas_cocina_min: out["SALON_MAS_COCINA_MIN"] = salon_mas_cocina_min
        if util_max: out["UTIL_MAX"] = util_max
        if area_target: out["AREA_TARGET_VIVIENDA"] = area_target

        # Parámetros globales del motor (singleton).
        motor = self._session.get(ParametrosMotorViviendaORM, 1)
        if motor is not None:
            out["PCT_CIRCULACION_INTERIOR_VIVIENDA"] = motor.pct_circulacion_interior_pct
            out["UMBRAL_MINIMO_ESTUDIO_M2"] = motor.umbral_minimo_estudio_m2
        return out

    def actualizar(
        self,
        uso: str,
        categoria: str,
        estancia: str,
        valor: float,
        usuario: str | None = None,
    ) -> None:
        # uso == "vivienda" y categoria == número de dormitorios (string)
        if uso != "vivienda":
            raise NotImplementedError(
                "Anexo I solo soporta vivienda en este MVP; hotel/apt llegarán en iteración posterior."
            )

        # Mínimo GLOBAL (dormitorio principal/mínimo, cocina, baño, aseo): se
        # propaga a TODAS las tipologías con la misma clave. Así el valor que
        # `consolidadas_vivienda` consolida (last-row-wins) es siempre coherente
        # y editar la cocina de una tipología no se pierde (resuelve R1).
        clave = _clave_global_estancia(estancia)
        if clave is not None:
            # Mínimo propagado a todas las tipologías: validar el invariante
            # contra el útil máximo de CADA fila afectada ANTES de mutar ninguna.
            afectadas = [
                orm for orm in self._session.scalars(select(AnexoIViviendaORM)).all()
                if _clave_global_estancia(orm.estancia) == clave
            ]
            for orm in afectadas:
                _exigir_min_le_max(valor, orm.max_m2_util, f"{orm.n_dormitorios}d/{orm.estancia}")
            ahora = datetime.now(timezone.utc)
            for orm in afectadas:
                orm.min_m2 = valor
                orm.editable_por_usuario = 1
                orm.actualizado_en = ahora
            self._session.commit()
            return

        try:
            n_dorms = int(categoria)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Categoría inválida para vivienda: {categoria!r}") from exc

        # Útil máximo de la tipología (R3): no es una estancia, es el techo de la
        # unidad. Se escribe en `max_m2_util` de TODAS las estancias de la
        # tipología (consolidadas_vivienda toma el máximo → UTIL_MAX[n]).
        if estancia == _UTIL_MAXIMO_ESTANCIA:
            filas = self._session.scalars(
                select(AnexoIViviendaORM).where(AnexoIViviendaORM.n_dormitorios == n_dorms)
            ).all()
            # No bajar el techo por debajo del mayor mínimo de estancia: rompería
            # el invariante (min ≤ max) en esa fila.
            if filas:
                min_mayor = max(f.min_m2 for f in filas)
                if valor < min_mayor:
                    raise ValueError(
                        f"El útil máximo ({valor:g} m²) no puede ser menor que el mayor "
                        f"mínimo de estancia ({min_mayor:g} m²) de la tipología {n_dorms}d."
                    )
            ahora = datetime.now(timezone.utc)
            for orm in filas:
                orm.max_m2_util = valor
                orm.editable_por_usuario = 1
                orm.actualizado_en = ahora
            self._session.commit()
            return

        orm = self._session.get(AnexoIViviendaORM, (n_dorms, estancia))
        if orm is None:
            orm = AnexoIViviendaORM(
                n_dormitorios=n_dorms,
                estancia=estancia,
                min_m2=valor,
                max_m2_util=valor,
                editable_por_usuario=1,
                actualizado_en=datetime.now(timezone.utc),
            )
            self._session.add(orm)
        else:
            _exigir_min_le_max(valor, orm.max_m2_util, f"{n_dorms}d/{estancia}")
            orm.min_m2 = valor
            orm.editable_por_usuario = 1
            orm.actualizado_en = datetime.now(timezone.utc)
        self._session.commit()

    def reset(self) -> None:
        """Reseed completo desde las constantes de `geometria.programa`.

        Atómico: borrado + siembra se confirman en una sola transacción. Si la
        siembra falla, el rollback restaura las filas previas (antes, el commit
        intermedio dejaba el catálogo vacío ante un fallo del seed)."""
        from .seed_normativa import sembrar_anexo_i_vivienda
        try:
            self._session.query(AnexoIViviendaORM).delete()
            sembrar_anexo_i_vivienda(self._session, forzar=True, commit=False)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
