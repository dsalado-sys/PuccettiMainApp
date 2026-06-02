"""Semilla del callejero INE desde `Antiguo/Python/municipalities.json`.

Idempotente: solo siembra cuando las tablas están vacías. Lee provincias y
municipios del TopoJSON, normaliza nombres y los inserta en SQLite.
"""
from __future__ import annotations

import json
import logging
import unicodedata
from pathlib import Path

from sqlalchemy.orm import Session

from .callejero_sqlalchemy import MunicipioORM, ProvinciaORM

log = logging.getLogger(__name__)

# Resolver la ruta al TopoJSON a partir de la raíz del repo.
# `app/plataforma/persistencia/callejero_seed.py` → 3 niveles arriba → `Puccetti/`
_RAIZ_REPO = Path(__file__).resolve().parents[3]
_RUTA_TOPOJSON = _RAIZ_REPO / "Antiguo" / "Python" / "municipalities.json"


def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower().strip()


def sembrar_callejero(session: Session) -> int:
    """Siembra provincias y municipios si están vacías. Devuelve nº de filas insertadas."""
    if session.query(ProvinciaORM).first() is not None:
        return 0
    if not _RUTA_TOPOJSON.exists():
        log.warning("Callejero: TopoJSON no encontrado en %s; tablas quedan vacías.", _RUTA_TOPOJSON)
        return 0

    try:
        with _RUTA_TOPOJSON.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        log.warning("Callejero: error leyendo %s: %s", _RUTA_TOPOJSON, exc)
        return 0

    objects = data.get("objects", {})
    provs_geom = objects.get("provinces", {}).get("geometries", [])
    munis_geom = objects.get("municipalities", {}).get("geometries", [])

    insertados = 0
    for g in provs_geom:
        codigo = str(g.get("id", "")).zfill(2)
        nombre = (g.get("properties", {}) or {}).get("name", "")
        if codigo and nombre:
            session.add(ProvinciaORM(codigo=codigo, nombre=nombre))
            insertados += 1

    for g in munis_geom:
        codigo = str(g.get("id", "")).zfill(5)
        nombre = (g.get("properties", {}) or {}).get("name", "")
        if codigo and len(codigo) == 5 and nombre:
            session.add(
                MunicipioORM(
                    codigo=codigo,
                    provincia_codigo=codigo[:2],
                    nombre=nombre,
                    nombre_normalizado=_normalizar(nombre),
                )
            )
            insertados += 1

    session.commit()
    log.info("Callejero sembrado: %d filas (provincias + municipios).", insertados)
    return insertados
