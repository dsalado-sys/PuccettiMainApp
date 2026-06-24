"""Carpetas de proyectos: capa organizativa por encima de los proyectos.

A diferencia de las normativas archivadas (que viven dentro de su carpeta), un
Proyecto es un aggregate propio con su tabla y su repositorio. Aquí solo se
modela la ORGANIZACIÓN en carpetas, sin tocar el esquema de `proyectos`:

- `carpeta_proyecto`     : las carpetas (id, nombre).
- `proyecto_en_carpeta`  : a qué carpeta pertenece cada proyecto (un proyecto
                           en como mucho una carpeta; los que no aparezcan aquí
                           se muestran en «Sin carpeta»).

Borrar una carpeta NO borra sus proyectos: solo deshace la pertenencia (los
proyectos vuelven a «Sin carpeta»). Esto difiere a propósito de las normativas,
donde borrar la carpeta sí elimina su contenido.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .sqlalchemy_base import Base


class CarpetaProyectoORM(Base):
    __tablename__ = "carpeta_proyecto"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProyectoEnCarpetaORM(Base):
    __tablename__ = "proyecto_en_carpeta"

    # El proyecto_id es la PK: cada proyecto pertenece a una sola carpeta.
    proyecto_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    carpeta_id: Mapped[int] = mapped_column(
        ForeignKey("carpeta_proyecto.id", ondelete="CASCADE"), nullable=False, index=True,
    )


class CarpetasProyectoSQLAlchemy:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Carpetas ──────────────────────────────────────────────────────────
    def listar_carpetas(self) -> list[dict[str, Any]]:
        items = self._session.scalars(
            select(CarpetaProyectoORM).order_by(CarpetaProyectoORM.nombre)
        ).all()
        return [{"id": c.id, "nombre": c.nombre} for c in items]

    def crear_carpeta(self, nombre: str) -> dict[str, Any]:
        nombre = (nombre or "").strip()
        if not nombre:
            raise ValueError("El nombre de la carpeta no puede estar vacío.")
        existe = self._session.scalar(
            select(CarpetaProyectoORM).where(CarpetaProyectoORM.nombre == nombre)
        )
        if existe is not None:
            return {"id": existe.id, "nombre": existe.nombre}
        orm = CarpetaProyectoORM(nombre=nombre, creado_en=datetime.now(timezone.utc))
        self._session.add(orm)
        self._session.commit()
        return {"id": orm.id, "nombre": orm.nombre}

    def eliminar_carpeta(self, carpeta_id: int) -> bool:
        orm = self._session.get(CarpetaProyectoORM, carpeta_id)
        if orm is None:
            return False
        # Desvincular sus proyectos (NO borrarlos): vuelven a «Sin carpeta».
        self._session.query(ProyectoEnCarpetaORM).filter(
            ProyectoEnCarpetaORM.carpeta_id == carpeta_id
        ).delete(synchronize_session=False)
        self._session.delete(orm)
        self._session.commit()
        return True

    # ── Pertenencia proyecto → carpeta ────────────────────────────────────
    def mapa_proyecto_carpeta(self) -> dict[str, int]:
        """Devuelve {proyecto_id: carpeta_id} para todos los proyectos ubicados."""
        items = self._session.scalars(select(ProyectoEnCarpetaORM)).all()
        return {m.proyecto_id: m.carpeta_id for m in items}

    def mover_proyecto(self, proyecto_id: str, carpeta_id: int | None) -> None:
        """Asigna el proyecto a una carpeta, o lo saca de toda carpeta (None)."""
        actual = self._session.get(ProyectoEnCarpetaORM, proyecto_id)
        if carpeta_id is None:
            if actual is not None:
                self._session.delete(actual)
                self._session.commit()
            return
        if self._session.get(CarpetaProyectoORM, carpeta_id) is None:
            raise ValueError(f"Carpeta {carpeta_id} no existe.")
        if actual is None:
            self._session.add(
                ProyectoEnCarpetaORM(proyecto_id=proyecto_id, carpeta_id=carpeta_id)
            )
        else:
            actual.carpeta_id = carpeta_id
        self._session.commit()

    def olvidar_proyecto(self, proyecto_id: str) -> None:
        """Borra la pertenencia de un proyecto (al eliminar el proyecto)."""
        actual = self._session.get(ProyectoEnCarpetaORM, proyecto_id)
        if actual is not None:
            self._session.delete(actual)
            self._session.commit()
