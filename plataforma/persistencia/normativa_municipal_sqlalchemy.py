"""Adapter SQLAlchemy del puerto NormativaMunicipalRepositorio.

Persiste y consulta los parámetros urbanísticos por municipio (PGOU).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.contextos.render_calculos.dominio import UsoEdificio
from app.contextos.render_calculos.parametros import ParametrosUrbanisticos

from .sqlalchemy_base import Base


class NormativaMunicipalORM(Base):
    __tablename__ = "normativa_municipal"

    municipio: Mapped[str] = mapped_column(String(120), primary_key=True)
    provincia: Mapped[str] = mapped_column(String(60), primary_key=True)

    edificabilidad_m2t_m2s: Mapped[float] = mapped_column(Float, nullable=False)
    ocupacion_maxima_pct: Mapped[float] = mapped_column(Float, nullable=False)
    n_plantas_max: Mapped[int] = mapped_column(Integer, nullable=False)
    retranqueo_frontal_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retranqueo_lateral_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retranqueo_trasero_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    altura_planta_m: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)

    usos_permitidos_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    luz_recta_patio_min_m: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    area_patio_min_m2: Mapped[float] = mapped_column(Float, nullable=False, default=12.0)

    tiene_atico_default: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retranqueo_atico_m: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    atico_computa_edificabilidad: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tiene_sotano_default: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sotano_computa_edificabilidad: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    fuente_pgou: Mapped[str | None] = mapped_column(Text, nullable=True)
    actualizado_por: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _orm_a_params(orm: NormativaMunicipalORM) -> ParametrosUrbanisticos:
    usos_raw: list[str]
    try:
        usos_raw = json.loads(orm.usos_permitidos_json or "[]")
    except json.JSONDecodeError:
        usos_raw = []
    usos: list[UsoEdificio] = []
    for v in usos_raw:
        try:
            usos.append(UsoEdificio(v))
        except ValueError:
            continue
    if not usos:
        usos = [UsoEdificio.VIVIENDA]

    return ParametrosUrbanisticos(
        edificabilidad_m2t_m2s=orm.edificabilidad_m2t_m2s,
        ocupacion_maxima_pct=orm.ocupacion_maxima_pct,
        n_plantas_max=orm.n_plantas_max,
        retranqueo_frontal_m=orm.retranqueo_frontal_m,
        retranqueo_lateral_m=orm.retranqueo_lateral_m,
        retranqueo_trasero_m=orm.retranqueo_trasero_m,
        altura_planta_m=orm.altura_planta_m,
        usos_permitidos=usos,
        luz_recta_patio_min_m=orm.luz_recta_patio_min_m,
        area_patio_min_m2=orm.area_patio_min_m2,
        tiene_atico=bool(orm.tiene_atico_default),
        retranqueo_atico_m=orm.retranqueo_atico_m,
        atico_computa_edificabilidad=bool(orm.atico_computa_edificabilidad),
        tiene_sotano=bool(orm.tiene_sotano_default),
        sotano_computa_edificabilidad=bool(orm.sotano_computa_edificabilidad),
    )


def _params_a_orm(p: ParametrosUrbanisticos, orm: NormativaMunicipalORM) -> None:
    orm.edificabilidad_m2t_m2s = p.edificabilidad_m2t_m2s
    orm.ocupacion_maxima_pct = p.ocupacion_maxima_pct
    orm.n_plantas_max = p.n_plantas_max
    orm.retranqueo_frontal_m = p.retranqueo_frontal_m
    orm.retranqueo_lateral_m = p.retranqueo_lateral_m
    orm.retranqueo_trasero_m = p.retranqueo_trasero_m
    orm.altura_planta_m = p.altura_planta_m
    orm.usos_permitidos_json = json.dumps([u.value for u in p.usos_permitidos])
    orm.luz_recta_patio_min_m = p.luz_recta_patio_min_m
    orm.area_patio_min_m2 = p.area_patio_min_m2
    orm.tiene_atico_default = 1 if p.tiene_atico else 0
    orm.retranqueo_atico_m = p.retranqueo_atico_m
    orm.atico_computa_edificabilidad = 1 if p.atico_computa_edificabilidad else 0
    orm.tiene_sotano_default = 1 if p.tiene_sotano else 0
    orm.sotano_computa_edificabilidad = 1 if p.sotano_computa_edificabilidad else 0


class NormativaMunicipalSQLAlchemy:
    def __init__(self, session: Session) -> None:
        self._session = session

    def obtener(self, municipio: str, provincia: str) -> ParametrosUrbanisticos | None:
        orm = self._session.get(NormativaMunicipalORM, (municipio, provincia))
        return _orm_a_params(orm) if orm else None

    def guardar(
        self,
        municipio: str,
        provincia: str,
        params: ParametrosUrbanisticos,
        fuente_pgou: str,
        usuario: str | None = None,
    ) -> None:
        orm = self._session.get(NormativaMunicipalORM, (municipio, provincia))
        if orm is None:
            orm = NormativaMunicipalORM(
                municipio=municipio,
                provincia=provincia,
                actualizado_en=datetime.now(timezone.utc),
            )
            self._session.add(orm)
        _params_a_orm(params, orm)
        orm.fuente_pgou = fuente_pgou
        orm.actualizado_por = usuario
        orm.actualizado_en = datetime.now(timezone.utc)
        self._session.commit()

    def listar(self) -> list[dict[str, Any]]:
        ormas = self._session.scalars(
            select(NormativaMunicipalORM).order_by(NormativaMunicipalORM.provincia, NormativaMunicipalORM.municipio)
        ).all()
        return [
            {
                "municipio": o.municipio,
                "provincia": o.provincia,
                "edificabilidad_m2t_m2s": o.edificabilidad_m2t_m2s,
                "n_plantas_max": o.n_plantas_max,
                "actualizado_en": o.actualizado_en.isoformat() if o.actualizado_en else None,
            }
            for o in ormas
        ]

    def eliminar(self, municipio: str, provincia: str) -> bool:
        orm = self._session.get(NormativaMunicipalORM, (municipio, provincia))
        if orm is None:
            return False
        self._session.delete(orm)
        self._session.commit()
        return True
