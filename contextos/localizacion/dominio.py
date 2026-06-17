"""Dominio puro de localización (§2.1).

No importa frameworks ni I/O. Las coordenadas son lon, lat en WGS84.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum


class TipoLado(str, Enum):
    FACHADA = "fachada"
    MEDIANERA = "medianera"


# 8 puntos cardinales válidos para la orientación del lado.
ORIENTACIONES = ("N", "NE", "E", "SE", "S", "SO", "O", "NO")


@dataclass
class Lado:
    indice: int
    p1: tuple[float, float]          # (lon, lat) WGS84
    p2: tuple[float, float]
    longitud_m: float
    azimut_grados: float             # 0..360 desde Norte (interno, para cálculos)
    tipo: TipoLado
    orientacion: str = "N"           # uno de ORIENTACIONES; auto-derivado, editable


@dataclass
class Subreferencia:
    """Inmueble dentro de una metaparcela (piso, local, garaje, etc.)."""
    rc: str                                          # 20 chars: pc1+pc2+car+cc1+cc2
    localizacion: str                                # "Es:1 Pl:03 Pt:B"
    uso: str                                         # "Vivienda", "Comercial", "Garaje", ...
    superficie_construida_m2: float
    coeficiente_participacion: float | None = None   # rellena el detalle lazy
    anio_construccion: int | None = None
    detalle_cargado: bool = False                    # True tras la consulta lazy


@dataclass
class AgregadosMetaparcela:
    """Métricas del conjunto cuando una parcela física tiene varios inmuebles."""
    num_referencias: int
    suma_superficie_construida_m2: float
    edificabilidad_m2t_m2s: float    # techo construido / suelo de parcela
    num_viviendas: int
    densidad_viviendas_viv_ha: float


@dataclass
class Parcela:
    referencia_catastral: str
    direccion: str
    municipio: str
    provincia: str
    superficie_m2: float
    centroide_lonlat: tuple[float, float]
    contorno_wgs84: list[tuple[float, float]]              # polígono exterior original
    contorno_simplificado_wgs84: list[tuple[float, float]] # = contorno original cuando tol = 0
    tolerancia_simplificacion_m: float
    lados: list[Lado]
    fuente: str                                            # "rc" | "direccion" | "coordenada"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    subreferencias: list[Subreferencia] = field(default_factory=list)
    agregados: AgregadosMetaparcela | None = None
    # Datos catastrales del edificio en la parcela (urbano).
    uso_catastral: str = ""
    anio_construccion: int | None = None
    superficie_construida_total_m2: float | None = None
    plantas_sobre_rasante: int | None = None
    plantas_bajo_rasante: int | None = None


class ParcelaError(Exception):
    """Base de los errores del contexto de localización."""


class RateLimitCatastro(ParcelaError):
    """El Catastro ha bloqueado la IP por exceso de peticiones."""


class SinParcelaEnPunto(ParcelaError):
    """Las coordenadas no caen sobre ninguna parcela conocida."""


class ParcelaNoEncontrada(ParcelaError):
    """RC inexistente, dirección sin resultados o parcela expirada del cache."""
