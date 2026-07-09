"""Puertos del contexto Localización (§2.1)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .dominio import Parcela, PatioCatastral, Subreferencia


@dataclass(frozen=True)
class ParcelaRaw:
    """DTO Catastro → dominio antes de geometrizar lados.

    El adapter del Catastro devuelve esto; los casos de uso lo enriquecen con
    simplificación, lados y clasificación antes de producir un `Parcela`.
    """
    referencia_catastral: str
    direccion: str
    municipio: str
    provincia: str
    superficie_m2: float
    centroide_lonlat: tuple[float, float]
    contorno_wgs84: list[tuple[float, float]]
    subreferencias: tuple[Subreferencia, ...] = field(default_factory=tuple)
    uso_catastral: str = ""
    anio_construccion: int | None = None
    superficie_construida_total_m2: float | None = None
    plantas_sobre_rasante: int | None = None
    plantas_bajo_rasante: int | None = None
    # Patios del edificio existente: nº de patios (anillos interiores de la huella
    # catastral) y su superficie en m². n_patios=None → el Catastro no dio el dato.
    n_patios: int | None = None
    patios_m2: tuple[float, ...] = field(default_factory=tuple)
    # Geometría de cada patio (anillo WGS84 + tipo). Paralela a patios_m2.
    patios_geom: tuple[PatioCatastral, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DetalleSubreferencia:
    """Datos enriquecidos que solo aparecen al consultar la RC20 individualmente."""
    coeficiente_participacion: float | None
    anio_construccion: int | None


class CatastroPort(Protocol):
    def buscar_por_rc(self, rc: str) -> ParcelaRaw: ...

    def buscar_por_direccion(
        self,
        provincia: str,
        municipio: str,
        tipo_via: str,
        calle: str,
        numero: str,
    ) -> ParcelaRaw: ...

    def buscar_por_coordenada(self, lon: float, lat: float) -> ParcelaRaw: ...

    def vecinos_en_bbox(
        self,
        bbox_4326: tuple[float, float, float, float],
        excluir_rc: str | None = None,
    ) -> list[list[tuple[float, float]]]:
        """Contornos WGS84 de parcelas en el bbox, excluyendo la propia si se indica."""

    def obtener_detalle_subreferencia(self, rc20: str) -> DetalleSubreferencia: ...

    def listar_vias(self, provincia: str, municipio: str) -> list[str]:
        """Devuelve las vías de un municipio (formato "TIPO NOMBRE"). Una llamada al Catastro."""


class ParcelaTemporalRepositorio(Protocol):
    """Almacenamiento corto de parcelas localizadas pero no asociadas a proyecto."""

    def guardar(self, parcela: Parcela) -> None: ...
    def obtener(self, parcela_id: str) -> Parcela | None: ...


class CallejeroPort(Protocol):
    """Catálogo INE local de provincias y municipios (no toca Catastro)."""

    def listar_provincias(self, prefijo: str = "") -> list[tuple[str, str]]: ...
    def buscar_municipios(self, provincia_codigo: str, prefijo: str) -> list[tuple[str, str]]: ...
