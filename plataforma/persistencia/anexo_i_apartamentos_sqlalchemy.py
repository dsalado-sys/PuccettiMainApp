"""Adapter SQLAlchemy del Anexo I.4 (apartamentos turísticos · Decreto 194/2010).

Análogo a `catalogo_superficies_sqlalchemy.py` (vivienda) pero con PK
`(categoria, tipologia, estancia)`. La categoría es "1L"-"4L"; la tipología es
"estudio"/"1d"/"2d"/"3d"; cuando la fila corresponde a áreas comunes
obligatorias se usa `categoria="comunes"` y `tipologia=<servicio>` (recepción,
sala social, etc.).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .sqlalchemy_base import Base


class AnexoIApartamentosORM(Base):
    """Una fila por (categoría, tipología, estancia)."""

    __tablename__ = "anexo_i_apartamentos"

    categoria: Mapped[str] = mapped_column(String(20), primary_key=True)
    tipologia: Mapped[str] = mapped_column(String(20), primary_key=True)
    estancia: Mapped[str] = mapped_column(String(40), primary_key=True)
    min_m2: Mapped[float] = mapped_column(Float, nullable=False)
    max_m2_util: Mapped[float] = mapped_column(Float, nullable=False)
    editable_por_usuario: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogoApartamentosSQLAlchemy:
    """Implementación del puerto CatalogoApartamentosRepositorio.

    Enruta por `grupo`: "edificios" (A1.3, tabla `anexo_i_apartamentos`) o
    "conjuntos" (A1.4, tabla `anexo_i_apartamentos_conjuntos`).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def _orm(self, grupo: str):
        if grupo == "conjuntos":
            from .anexo_i_apartamentos_conjuntos_sqlalchemy import (
                AnexoIApartamentosConjuntosORM,
            )
            return AnexoIApartamentosConjuntosORM
        return AnexoIApartamentosORM

    def superficies_apartamento(
        self, categoria: str, tipologia: str, grupo: str = "edificios",
    ) -> dict[str, float]:
        orm = self._orm(grupo)
        filas = self._session.scalars(
            select(orm)
            .where(orm.categoria == categoria)
            .where(orm.tipologia == tipologia)
        ).all()
        out: dict[str, float] = {}
        for f in filas:
            out[f.estancia + "_min"] = f.min_m2
            out[f.estancia + "_max"] = f.max_m2_util
        return out

    def util_objetivo_apartamento(
        self, categoria: str, tipologia: str, grupo: str = "edificios",
    ) -> float | None:
        """m² útiles objetivo por unidad (Σ mínimos de las estancias × 1.15).

        Se calcula sumando el `min_m2` EDITABLE de cada estancia de la unidad
        `(categoria, tipologia)`, de modo que cualquier mínimo editado en el editor
        se refleja en el objetivo (antes se leía `max_m2_util` de una fila al azar,
        que no se actualizaba al editar). Si no hay filas → None (fallback motor).
        """
        orm = self._orm(grupo)
        filas = self._session.scalars(
            select(orm)
            .where(orm.categoria == categoria)
            .where(orm.tipologia == tipologia)
        ).all()
        if not filas:
            return None
        base = sum(float(f.min_m2) for f in filas)
        return round(base * 1.15, 2)

    def consolidadas_apartamentos(self, grupo: str = "edificios") -> dict:
        """Mínimos editables de BBDD en la forma de las constantes del motor.

        Hermano de `consolidadas_vivienda`: `programa_apartamentos.cargar_desde_repo`
        lo vuelca a sus diccionarios `MIN_*` para que el dimensionado de estancias
        respete los mínimos editados. Devuelve `{}` si la tabla está vacía.

        Mapeo (excluye las filas `comunes_*`):
        - `dormitorio_1` por tipología de ocupación → `MIN_DORMITORIO[tip][cat]`.
        - `salon_comedor` del estudio              → `MIN_ESTUDIO[cat]`.
        - `salon_comedor` de la doble (base ≤4 pax) → `MIN_SALON_COMEDOR[cat]`.
        - `cocina` / `bano` (dependen solo de cat)  → `MIN_COCINA` / `MIN_BANO`.
        """
        orm = self._orm(grupo)
        filas = self._session.scalars(select(orm)).all()
        if not filas:
            return {}
        dorm: dict[str, dict[str, float]] = {}
        estudio: dict[str, float] = {}
        salon: dict[str, float] = {}
        cocina: dict[str, float] = {}
        bano: dict[str, float] = {}
        for f in filas:
            if str(f.categoria).startswith("comunes"):
                continue
            cat, tip, est = f.categoria, f.tipologia, f.estancia
            if est == "dormitorio_1" and tip in ("individual", "doble", "triple", "cuadruple"):
                dorm.setdefault(tip, {})[cat] = float(f.min_m2)
            elif est == "cocina":
                cocina[cat] = float(f.min_m2)
            elif est in ("bano", "bano_1"):
                bano[cat] = float(f.min_m2)
            elif est == "salon_comedor":
                if tip == "estudio":
                    estudio[cat] = float(f.min_m2)
                elif tip == "doble":
                    salon[cat] = float(f.min_m2)
        out: dict = {}
        if dorm:
            out["MIN_DORMITORIO"] = dorm
        if estudio:
            out["MIN_ESTUDIO"] = estudio
        if salon:
            out["MIN_SALON_COMEDOR"] = salon
        if cocina:
            out["MIN_COCINA"] = cocina
        if bano:
            out["MIN_BANO"] = bano
        return out

    def areas_comunes(self, categoria: str, grupo: str = "edificios") -> dict[str, float]:
        """Devuelve los m² por servicio común para la categoría dada."""
        orm = self._orm(grupo)
        filas = self._session.scalars(
            select(orm).where(orm.categoria == "comunes_" + categoria)
        ).all()
        return {f.estancia: f.min_m2 for f in filas}

    def filas_min(self, categoria: str, grupo: str = "edificios") -> list[dict]:
        """Filas del editor de mínimos para una categoría (unidades + áreas comunes)."""
        from .etiquetas_anexo import construir_filas_min
        orm = self._orm(grupo)
        unidad = self._session.scalars(
            select(orm).where(orm.categoria == categoria)
        ).all()
        comunes = self._session.scalars(
            select(orm).where(orm.categoria == "comunes_" + categoria)
        ).all()
        return construir_filas_min(unidad, comunes)

    def actualizar(
        self,
        categoria: str,
        tipologia: str,
        estancia: str,
        valor: float,
        usuario: str | None = None,
        grupo: str = "edificios",
    ) -> None:
        orm_cls = self._orm(grupo)
        orm = self._session.get(orm_cls, (categoria, tipologia, estancia))
        if orm is None:
            orm = orm_cls(
                categoria=categoria,
                tipologia=tipologia,
                estancia=estancia,
                min_m2=valor,
                max_m2_util=valor,
                editable_por_usuario=1,
                actualizado_en=datetime.now(timezone.utc),
            )
            self._session.add(orm)
        else:
            orm.min_m2 = valor
            orm.editable_por_usuario = 1
            orm.actualizado_en = datetime.now(timezone.utc)
        self._session.commit()

    def reset(self) -> None:
        from .anexo_i_apartamentos_conjuntos_sqlalchemy import (
            AnexoIApartamentosConjuntosORM,
        )
        from .seed_normativa import (
            sembrar_anexo_i_apartamentos,
            sembrar_anexo_i_apartamentos_conjuntos,
        )
        self._session.query(AnexoIApartamentosORM).delete()
        self._session.query(AnexoIApartamentosConjuntosORM).delete()
        self._session.commit()
        sembrar_anexo_i_apartamentos(self._session, forzar=True)
        sembrar_anexo_i_apartamentos_conjuntos(self._session, forzar=True)
