"""Etiquetas y orden de estancias para los editores de mínimos del Anexo I.

Compartido por los adapters de apartamentos turísticos (I.3/I.4),
hoteles-apartamento (I.2) y hotelero (I.1). Análogo a los helpers privados de
`catalogo_superficies_sqlalchemy.py` (vivienda), pero reutilizable entre los
tres usos turístico/hoteleros, que comparten la PK `(categoria, tipologia,
estancia)`.
"""
from __future__ import annotations

from typing import Iterable, Protocol


_ETIQUETAS_ESTANCIA: dict[str, str] = {
    "salon": "Salón",
    "salon_cocina": "Salón-cocina integrado",
    "salon_comedor": "Salón-comedor",
    "espacio_principal": "Estancia principal (salón-dormitorio)",
    "cocina": "Cocina",
    "habitacion": "Habitación",
    "bano": "Baño",
    "aseo": "Aseo",
    # Servicios comunes / sociales obligatorios del establecimiento.
    "areas_sociales": "Áreas sociales",
    "salon_social": "Salón social",
    "area_social_por_ua": "Área social por unidad",
    "area_social_por_plaza": "Área social por plaza",
    "vestibulo_recepcion": "Vestíbulo / recepción",
    "recepcion": "Recepción",
}

# Orden de presentación de las tipologías dentro de la categoría (las áreas
# comunes siempre van al final).
_ORDEN_TIPOLOGIA: dict[str, int] = {
    "estudio": 0,
    "1d": 1, "individual": 1,
    "2d": 2, "doble": 2,
    "3d": 3, "triple": 3,
    "4d": 4, "cuadruple": 4,
    "multiple": 5,
    # Salón-comedor común de la unidad (hotel-apartamento, A1.2): tras las
    # ocupaciones y antes de las áreas comunes del establecimiento.
    "salon_comedor": 6,
}


def etiqueta_estancia(nombre: str) -> str:
    """Nombre legible de una estancia o servicio común."""
    if nombre in _ETIQUETAS_ESTANCIA:
        return _ETIQUETAS_ESTANCIA[nombre]
    if nombre.startswith("dormitorio_"):
        return f"Dormitorio {nombre.split('_', 1)[1]}"
    if nombre.startswith("bano_"):
        return f"Baño {nombre.split('_', 1)[1]}"
    return nombre.replace("_", " ").capitalize()


def _orden_estancia(nombre: str) -> tuple[int, int]:
    fijo = {"salon_comedor": 0, "salon": 0, "salon_cocina": 1, "espacio_principal": 2,
            "habitacion": 0, "dormitorio": 0, "estudio": 0, "cocina": 3, "aseo": 4}
    if nombre in fijo:
        return (fijo[nombre], 0)
    if nombre.startswith("dormitorio_"):
        return (10, int(nombre.split("_", 1)[1]))
    if nombre == "bano":
        return (20, 0)
    if nombre.startswith("bano_"):
        return (20, int(nombre.split("_", 1)[1]))
    return (99, 0)


class _FilaORM(Protocol):
    tipologia: str
    estancia: str
    min_m2: float
    editable_por_usuario: int


def construir_filas_min(
    unidad_rows: Iterable[_FilaORM],
    comunes_rows: Iterable[_FilaORM],
) -> list[dict]:
    """Construye las filas del editor para una categoría: las estancias de cada
    tipología de unidad seguidas de las áreas comunes, ordenadas para que el
    frontend las agrupe por tipología en orden canónico."""
    out: list[dict] = []
    for f in unidad_rows:
        out.append({
            "tipologia": f.tipologia,
            "estancia": f.estancia,
            "etiqueta": etiqueta_estancia(f.estancia),
            "min_m2": f.min_m2,
            "editable_por_usuario": bool(f.editable_por_usuario),
            "es_comun": False,
        })
    for f in comunes_rows:
        out.append({
            "tipologia": "comunes",
            "estancia": f.estancia,
            "etiqueta": etiqueta_estancia(f.estancia),
            "min_m2": f.min_m2,
            "editable_por_usuario": bool(f.editable_por_usuario),
            "es_comun": True,
        })
    out.sort(key=lambda r: (
        r["es_comun"],
        _ORDEN_TIPOLOGIA.get(r["tipologia"], 90),
        _orden_estancia(r["estancia"]),
    ))
    return out
