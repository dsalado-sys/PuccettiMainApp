"""§2.4–2.7 — Casos de uso del módulo Render y cálculos.

Orquestación entre el motor geométrico (`geometria/`), el aggregate `Proyecto`
y los puertos de persistencia (normativa municipal + Anexo I).

Los casos de uso son funciones/clases puras: reciben dependencias por
parámetro (DI) y no conocen FastAPI ni SQLAlchemy.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from pyproj import Transformer
from shapely.geometry import Polygon
from shapely.ops import transform as shp_transform

from app.contextos.proyectos.puertos import ProyectoRepositorio
from app.nucleo.modelo import ModuloPuccetti, Proyecto

from .dominio import (
    Alerta,
    IndicadoresDiseno,
    ResumenEnvolvente,
    UsoEdificio,
)
from .geometria.capacidad import DisenoPlanta, calcular_capacidad, capacidad_a_dict
from .geometria.envolvente import construir_envolvente
from .geometria.parcelas import LadoParcela, azimut_normal_exterior, orientacion_cardinal
from .geometria.serializacion import (
    lados_a_dict,
    ring,
    tabla_planta_desde_capacidad,
    tabla_unidad_desde_capacidad,
)
from .parametros import (
    ParametrosRender,
    ParametrosUrbanisticos,
    parametros_a_dict,
    parametros_desde_dict,
)
from .puertos import (
    CatalogoApartamentosRepositorio,
    CatalogoHotelApartamentoRepositorio,
    CatalogoHoteleroRepositorio,
    CatalogoSuperficiesRepositorio,
    NormativaMunicipalRepositorio,
)


# ─── Reproyección WGS84 ↔ UTM30N (Iberia peninsular) ────────────────────────
# La localización guarda lon/lat en WGS84; el motor de geometría necesita metros.
_WGS84_A_UTM = Transformer.from_crs("EPSG:4326", "EPSG:25830", always_xy=True)
_UTM_A_WGS84 = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)


def _polygon_a_utm(coords_lonlat: list[tuple[float, float]]) -> Polygon:
    pts_xy = [_WGS84_A_UTM.transform(lon, lat) for lon, lat in coords_lonlat]
    return Polygon(pts_xy)


def _lado_a_utm(p1: tuple[float, float], p2: tuple[float, float]) -> tuple[tuple[float, float], tuple[float, float]]:
    a = _WGS84_A_UTM.transform(p1[0], p1[1])
    b = _WGS84_A_UTM.transform(p2[0], p2[1])
    return a, b


def _disenos_por_categoria(params: ParametrosRender) -> dict[str, DisenoPlanta]:
    """% muros/circulación/núcleo por categoría de planta (pb/tipo/atico/sotano).

    PB lee `pct_circulacion_pb`; el resto de categorías `pct_circulacion_tipo` de su
    propio bucket. Permite que PB sea independiente de las plantas tipo y que ático y
    sótano tengan su propio % muros y % circulación.
    """
    def dp(diseno, circ_field: str) -> DisenoPlanta:
        return DisenoPlanta(
            max(0.0, min(80.0, float(diseno.pct_muros))),
            max(0.0, min(50.0, float(getattr(diseno, circ_field)))),
            max(0.0, min(30.0, float(diseno.pct_nucleo))),
        )

    return {
        "pb": dp(params.diseno, "pct_circulacion_pb"),
        "tipo": dp(params.diseno_tipo, "pct_circulacion_tipo"),
        "atico": dp(params.diseno_atico, "pct_circulacion_tipo"),
        "sotano": dp(params.diseno_sotano, "pct_circulacion_tipo"),
    }


# ─── Construcción de la parcela métrica desde el proyecto ───────────────────
@dataclass
class ParcelaMetrica:
    poligono_utm: Polygon
    lados: list[LadoParcela]
    municipio: str | None
    provincia: str | None
    centroide_lonlat: tuple[float, float] | None
    referencia_catastral: str | None


def construir_parcela_metrica(proyecto: Proyecto) -> ParcelaMetrica | None:
    """Lee `proyecto.datos(LOCALIZACION)` y reproyecta a UTM30N.

    Devuelve None si no hay parcela asociada al proyecto. Es robusto frente a
    estructuras parciales (contorno sin lados, lados sin tipo válido, etc.).
    """
    datos = proyecto.datos_por_modulo.get(ModuloPuccetti.LOCALIZACION.value) or {}
    if not datos:
        return None

    contorno = datos.get("contorno_simplificado_wgs84") or datos.get("contorno_wgs84") or []
    if not contorno or len(contorno) < 3:
        return None

    poly = _polygon_a_utm([(float(p[0]), float(p[1])) for p in contorno])
    if poly.is_empty or not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty:
        return None

    lados_raw = datos.get("lados") or []
    lados: list[LadoParcela] = []
    for l in lados_raw:
        tipo = l.get("tipo", "fachada")
        if tipo not in ("fachada", "medianera"):
            tipo = "fachada"
        p1 = l.get("p1") or [0.0, 0.0]
        p2 = l.get("p2") or [0.0, 0.0]
        a, b = _lado_a_utm((float(p1[0]), float(p1[1])), (float(p2[0]), float(p2[1])))
        long_m = math.hypot(b[0] - a[0], b[1] - a[1])
        if long_m < 0.10:
            continue
        azimut_grados = (math.degrees(math.atan2(b[0] - a[0], b[1] - a[1]))) % 360
        lados.append(LadoParcela(
            p1=a, p2=b, tipo=tipo, longitud_m=long_m, azimut=azimut_grados,
            normal_azimut=azimut_normal_exterior(a, b, poly),
        ))

    if not lados:
        # Si la parcela no trae lados, asumimos todo fachada (req. 1: medianera
        # no admite huecos; al ser todo fachada el motor permite ventanas en todos
        # los lados — el técnico puede reclasificar desde §2.1).
        coords = list(poly.exterior.coords)[:-1]
        for i, p1 in enumerate(coords):
            p2 = coords[(i + 1) % len(coords)]
            long_m = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            if long_m < 0.10:
                continue
            azimut_grados = (math.degrees(math.atan2(p2[0] - p1[0], p2[1] - p1[1]))) % 360
            lados.append(LadoParcela(
                p1=p1, p2=p2, tipo="fachada", longitud_m=long_m, azimut=azimut_grados,
                normal_azimut=azimut_normal_exterior(p1, p2, poly),
            ))

    centroide_raw = datos.get("centroide_lonlat")
    centroide = None
    if centroide_raw and len(centroide_raw) >= 2:
        centroide = (float(centroide_raw[0]), float(centroide_raw[1]))

    return ParcelaMetrica(
        poligono_utm=poly,
        lados=lados,
        municipio=datos.get("municipio"),
        provincia=datos.get("provincia"),
        centroide_lonlat=centroide,
        referencia_catastral=datos.get("referencia_catastral"),
    )


# ─── Caso de uso 1: CalcularEnvolvente (§2.4 — preview rápido) ──────────────
@dataclass
class CalcularEnvolvente:
    """req. 8 — huella + plantas + patios. Sin distribución interior (rápido)."""

    def ejecutar(
        self,
        parcela: ParcelaMetrica,
        params: ParametrosRender,
    ) -> dict[str, Any]:
        params_motor = params.a_parametros_motor()
        params_motor_tipo = params.a_parametros_motor_tipo()
        try:
            envolvente = construir_envolvente(parcela.poligono_utm, params_motor, parcela.lados)
        except ValueError as exc:
            return {
                "error": str(exc),
                "envolvente": None,
                "alertas": [_alerta_dict(Alerta("incumplimiento", "Geometría", str(exc)))],
                "indicadores": None,
            }

        # Diferenciación por planta también en el preview (KPI nº viviendas): en
        # preview no se construyen descriptores, así que la mezcla por planta usa la
        # vía int-based de vivienda (igual que antes), pero con % y tipología por planta.
        cap = calcular_capacidad(
            envolvente, params_motor,
            params_tipo=params_motor_tipo,
            disenos=_disenos_por_categoria(params),
        )

        indicadores = _indicadores_disenho(parcela, envolvente.plantas)
        alertas = _alertas_envolvente(envolvente, parcela, params)

        bbox = envolvente.parcela.bounds
        resumen = ResumenEnvolvente(
            huella_m2=round(envolvente.plantas[0].footprint.area, 2) if envolvente.plantas else 0.0,
            n_plantas=len(envolvente.plantas),
            edificabilidad_max_m2=round(envolvente.edificabilidad_max, 2),
            edificabilidad_consumida_m2=round(envolvente.edificabilidad_consumida, 2),
            n_viviendas_objetivo=cap.n_viviendas_objetivo,
            factor_limitante=cap.factor_limitante,
            bbox_world=(round(bbox[0], 2), round(bbox[1], 2), round(bbox[2], 2), round(bbox[3], 2)),
        )

        plantas_dict = _plantas_envolvente_a_dict(envolvente)

        return {
            "envolvente": {
                "huella_m2": resumen.huella_m2,
                "n_plantas": resumen.n_plantas,
                "edificabilidad_max_m2": resumen.edificabilidad_max_m2,
                "edificabilidad_consumida_m2": resumen.edificabilidad_consumida_m2,
                "n_viviendas_objetivo": resumen.n_viviendas_objetivo,
                "factor_limitante": resumen.factor_limitante,
                "bbox": list(resumen.bbox_world),
                "plantas": plantas_dict,
            },
            "parcela": {
                "poligono": ring(parcela.poligono_utm),
                "area_m2": round(parcela.poligono_utm.area, 2),
                "municipio": parcela.municipio,
                "provincia": parcela.provincia,
                "bbox": [round(v, 2) for v in parcela.poligono_utm.bounds],
            },
            "lados": lados_a_dict(parcela.lados),
            "indicadores": _indicadores_dict(indicadores),
            "alertas": [_alerta_dict(a) for a in alertas],
        }


def _plantas_envolvente_a_dict(envolvente) -> list[dict[str, Any]]:
    """Serializa la lista de plantas de una envolvente para el canvas.

    No incluye unidades/núcleo/pasillos: el render geométrico de unidades
    queda en backlog (ver iteración 3 — `edificio: null`).
    """
    out: list[dict[str, Any]] = []
    idx_visual = 0
    for pl in envolvente.plantas:
        tipo = getattr(pl, "tipo", "regular")
        if tipo == "sotano":
            nombre = "S1"
        elif tipo == "atico":
            nombre = "Ático"
        else:
            nombre = "PB" if idx_visual == 0 else f"P{idx_visual}"
            idx_visual += 1
        out.append({
            "n": pl.n,
            "nombre": nombre,
            "tipo": tipo,
            "computa_edif": getattr(pl, "computa_edif", True),
            "footprint": ring(pl.footprint),
            "patios": [
                {"poligono": ring(p.geometry), "area_m2": round(p.area_m2, 2),
                 "luz_recta_m": round(p.luz_recta_m, 2)}
                for p in pl.patios
            ],
            "construida_m2": round(pl.area_construida_m2, 2),
            "util_m2": round(pl.area_util_m2, 2),
        })
    return out


@dataclass
class PreparacionCapacidad:
    """Envolvente + capacidad + programa de uso ya resueltos.

    Lo produce `CalcularLayout.preparar` y lo consumen tanto las tablas/KPIs
    (`CalcularLayout.ejecutar`) como la autodistribución del lienzo
    (`AutodistribuirLienzo`), para no duplicar la resolución de tipologías,
    descriptores y áreas comunes.
    """
    envolvente: Any = None
    cap: Any = None
    programa_uso: Any = None
    descriptores: Any = None
    error: str | None = None


# ─── Caso de uso 2: CalcularLayout (§2.4+§2.5 — calculations-first iter. 3) ─
@dataclass
class CalcularLayout:
    """req. 8+12 — capacidad numérica + tablas sintéticas, sin macro_layout.

    Desde iteración 3 la fuente de verdad es `calcular_capacidad()`. El render
    geométrico de unidades queda en backlog; la respuesta lleva `edificio: null`
    explícito y los datos viven en `capacidad` + `tabla_planta` + `tabla_unidad`.

    Inyectables opcionales (si faltan → fallback a constantes del motor):
    - `catalogo_vivienda`: Anexo I.5 (vivienda).
    - `catalogo_apartamentos`: Anexo I.3/I.4 (apartamentos turísticos).
    - `catalogo_hotel_apartamento`: Anexo I.2 (hoteles-apartamento).
    - `catalogo_hotelero`: Anexo I.1 (hoteles / hostales / pensiones / albergues).
    """

    catalogo_vivienda: CatalogoSuperficiesRepositorio | None = None
    catalogo_apartamentos: CatalogoApartamentosRepositorio | None = None
    catalogo_hotel_apartamento: CatalogoHotelApartamentoRepositorio | None = None
    catalogo_hotelero: CatalogoHoteleroRepositorio | None = None

    def preparar(
        self,
        parcela: ParcelaMetrica,
        params: ParametrosRender,
    ) -> PreparacionCapacidad:
        """Resuelve envolvente + capacidad + programa de uso (sin tablas ni alertas).

        Es la parte reutilizable: `ejecutar` la usa para las tablas/KPIs y
        `AutodistribuirLienzo` para repartir cada planta en el lienzo. Si la
        envolvente no es construible, devuelve `PreparacionCapacidad(error=…)`.
        """
        params_motor = params.a_parametros_motor()
        params_motor_tipo = params.a_parametros_motor_tipo()
        try:
            envolvente = construir_envolvente(parcela.poligono_utm, params_motor, parcela.lados)
        except ValueError as exc:
            return PreparacionCapacidad(error=str(exc))

        # 1) Resolver tamaño objetivo de la tipología principal (PB y plantas tipo).
        util_objetivo = self._resolver_util_objetivo(params)
        util_objetivo_tipo = self._resolver_util_objetivo(params, params.programa_tipo)

        # 2) Descriptores de tipología (principal + extras → mezcla), PB y tipo.
        descriptores = self._construir_descriptores_tipologia(params, util_objetivo)
        descriptores_tipo = self._construir_descriptores_tipologia(
            params, util_objetivo_tipo, params.programa_tipo
        )

        # 3) Construir programa_uso (áreas comunes/sociales obligatorias — de edificio).
        programa_uso = self._construir_programa_uso(
            params, envolvente, params_motor, util_objetivo, descriptores
        )
        area_comunes = programa_uso.area_servicios_obligatorios_m2 if programa_uso else 0.0

        # 4) Cálculo puro — diferenciando PB / plantas tipo / ático / sótano.
        cap = calcular_capacidad(
            envolvente, params_motor,
            util_objetivo_por_unidad=util_objetivo,
            area_servicios_comunes_m2=area_comunes,
            descriptores_tipologia=descriptores,
            params_tipo=params_motor_tipo,
            util_objetivo_por_unidad_tipo=util_objetivo_tipo,
            descriptores_tipologia_tipo=descriptores_tipo,
            disenos=_disenos_por_categoria(params),
        )
        return PreparacionCapacidad(
            envolvente=envolvente, cap=cap,
            programa_uso=programa_uso, descriptores=descriptores,
        )

    def ejecutar(
        self,
        parcela: ParcelaMetrica,
        params: ParametrosRender,
    ) -> dict[str, Any]:
        prep = self.preparar(parcela, params)
        if prep.error is not None:
            return {
                "error": prep.error,
                "edificio": None,
                "capacidad": None,
                "alertas": [_alerta_dict(Alerta("incumplimiento", "Geometría", prep.error))],
                "tabla_planta": [],
                "tabla_unidad": [],
                "indicadores": None,
                "envolvente": None,
            }
        envolvente = prep.envolvente
        cap = prep.cap
        programa_uso = prep.programa_uso

        # Tablas sintéticas derivadas del cálculo (no de geometría).
        tabla_planta = tabla_planta_desde_capacidad(cap, programa_uso=programa_uso)
        tabla_unidad = tabla_unidad_desde_capacidad(cap, params, programa_uso=programa_uso)

        # 5) Indicadores y alertas (sin edificio dispuesto).
        indicadores = _indicadores_disenho(parcela, envolvente.plantas)
        alertas = _alertas_envolvente(envolvente, parcela, params)
        alertas += _alertas_capacidad(cap, params, programa_uso)

        return {
            "edificio": None,                          # render geométrico en backlog
            "capacidad": capacidad_a_dict(cap),         # fuente de verdad
            "tabla_planta": tabla_planta,
            "tabla_unidad": tabla_unidad,
            "indicadores": _indicadores_dict(indicadores),
            "alertas": [_alerta_dict(a) for a in alertas],
            "envolvente": {
                "huella_m2": round(envolvente.plantas[0].footprint.area, 2) if envolvente.plantas else 0.0,
                "n_plantas": len(envolvente.plantas),
                "edificabilidad_max_m2": round(envolvente.edificabilidad_max, 2),
                "edificabilidad_consumida_m2": round(envolvente.edificabilidad_consumida, 2),
                "bbox": [round(v, 2) for v in envolvente.parcela.bounds],
                "plantas": _plantas_envolvente_a_dict(envolvente),
            },
            "parcela": {
                "poligono": ring(parcela.poligono_utm),
                "area_m2": round(parcela.poligono_utm.area, 2),
                "municipio": parcela.municipio,
                "provincia": parcela.provincia,
                "bbox": [round(v, 2) for v in parcela.poligono_utm.bounds],
            },
            "lados": lados_a_dict(parcela.lados),
        }

    # ─── Helpers privados de CalcularLayout ────────────────────────────────
    def _resolver_util_objetivo(self, params: ParametrosRender, prog=None) -> float | None:
        """Lee el m² útil objetivo por unidad desde la BBDD del Anexo I.

        Vivienda: `anexo_i_vivienda.max_m2_util` para `n_dormitorios`.
        Apartamentos: `anexo_i_apartamentos.max_m2_util` × 1.15.

        `prog` permite resolver el objetivo de las plantas tipo (`programa_tipo`);
        por defecto usa `params.programa` (planta baja).

        Si la consulta falla o la fila no existe → None y `calcular_capacidad`
        cae en el hardcoded `util_maximo(n_dorms)` o `util_objetivo_apartamento`.
        """
        from .dominio import CATEGORIA_A_NUM_DORMS

        prog = prog if prog is not None else params.programa
        if prog.uso == UsoEdificio.VIVIENDA:
            if self.catalogo_vivienda is None:
                return None
            n_dorms = CATEGORIA_A_NUM_DORMS.get(prog.categoria_vivienda, 2)
            try:
                return self.catalogo_vivienda.util_objetivo_vivienda(n_dorms)
            except Exception:
                return None
        if prog.uso == UsoEdificio.APARTAMENTOS_TURISTICOS:
            if self.catalogo_apartamentos is None:
                return None
            try:
                return self.catalogo_apartamentos.util_objetivo_apartamento(
                    prog.categoria_apartamentos.value,
                    prog.tipologia_apartamento.value,
                    prog.grupo_apartamentos.value,
                )
            except Exception:
                return None
        if prog.uso == UsoEdificio.HOTEL_APARTAMENTO:
            if self.catalogo_hotel_apartamento is None:
                return None
            try:
                return self.catalogo_hotel_apartamento.util_objetivo(
                    prog.categoria_hotel_apartamento.value,
                    prog.tipologia_apartamento.value,
                )
            except Exception:
                return None
        if prog.uso == UsoEdificio.HOTELERO:
            if self.catalogo_hotelero is None:
                return None
            try:
                return self.catalogo_hotelero.util_objetivo_habitacion(
                    prog.categoria_hotelero.value,
                    prog.tipologia_habitacion.value,
                )
            except Exception:
                return None
        return None

    # ─── Descriptores de tipología (mezcla multi-tipología por uso) ─────────
    def _construir_descriptores_tipologia(self, params: ParametrosRender, util_objetivo, prog=None):
        """Lista de `TipologiaUnidadDescriptor` del uso activo (principal + extras).

        La categoría del proyecto es fija; varía la tipología (igual que en
        vivienda solo varía el nº de dormitorios). `prog` permite construir la lista
        de las plantas tipo (`programa_tipo`); por defecto usa `params.programa`.
        Devuelve `None` para vivienda (que sigue la vía int-based del motor) y para
        usos no soportados.
        """
        prog = prog if prog is not None else params.programa
        uso = prog.uso
        if uso == UsoEdificio.VIVIENDA:
            return None

        if uso == UsoEdificio.APARTAMENTOS_TURISTICOS:
            from .geometria.programa_apartamentos import descriptor_tipologia_apartamento
            cat = prog.categoria_apartamentos.value
            grupo = prog.grupo_apartamentos.value
            principal = prog.tipologia_apartamento.value
            constructor = lambda slug: descriptor_tipologia_apartamento(cat, slug, grupo)
        elif uso == UsoEdificio.HOTEL_APARTAMENTO:
            from .geometria.programa_hotel_apartamento import descriptor_tipologia_hotel_apartamento
            cat = prog.categoria_hotel_apartamento.value
            principal = prog.tipologia_apartamento.value
            constructor = lambda slug: descriptor_tipologia_hotel_apartamento(cat, slug)
        elif uso == UsoEdificio.HOTELERO:
            from .geometria.programa_hotelero import descriptor_tipologia_hotelero
            cat = prog.categoria_hotelero.value
            principal = prog.tipologia_habitacion.value
            constructor = lambda slug: descriptor_tipologia_hotelero(cat, slug)
        else:
            return None

        slugs = [principal] + [s for s in prog.tipologias_extra]
        descriptores = []
        for idx, slug in enumerate(slugs):
            d = constructor(slug)
            # El útil objetivo de la principal proviene de BBDD (si está); las
            # extras usan la constante del Anexo (mismo valor salvo edición).
            uo_bbdd = util_objetivo if idx == 0 else self._util_objetivo_bbdd(params, slug, prog)
            if uo_bbdd is not None and uo_bbdd > 0:
                d = replace(d, util_objetivo=uo_bbdd, util_maximo=round(uo_bbdd * 1.25, 2))
            descriptores.append(d)
        return descriptores or None

    def _util_objetivo_bbdd(self, params: ParametrosRender, slug: str, prog=None):
        """Útil objetivo de una tipología desde BBDD (None si no hay catálogo/fila)."""
        prog = prog if prog is not None else params.programa
        try:
            if prog.uso == UsoEdificio.APARTAMENTOS_TURISTICOS and self.catalogo_apartamentos:
                return self.catalogo_apartamentos.util_objetivo_apartamento(
                    prog.categoria_apartamentos.value, slug, prog.grupo_apartamentos.value
                )
            if prog.uso == UsoEdificio.HOTEL_APARTAMENTO and self.catalogo_hotel_apartamento:
                return self.catalogo_hotel_apartamento.util_objetivo(
                    prog.categoria_hotel_apartamento.value, slug
                )
            if prog.uso == UsoEdificio.HOTELERO and self.catalogo_hotelero:
                return self.catalogo_hotelero.util_objetivo_habitacion(
                    prog.categoria_hotelero.value, slug
                )
        except Exception:
            return None
        return None

    def _construir_programa_uso(
        self,
        params: ParametrosRender,
        envolvente,
        params_motor,
        util_objetivo: float | None,
        descriptores,
    ):
        """Construye el descriptor de uso con sus áreas comunes/sociales obligatorias.

        Para vivienda: None (calcular_capacidad no necesita programa_uso). Para
        apartamentos / hotel-apartamento / hotelero hace una iteración de dos
        pasos para dimensionar las comunes (que escalan con nº de unidades, o de
        plazas en albergue).
        """
        prog = params.programa
        uso = prog.uso
        if uso == UsoEdificio.APARTAMENTOS_TURISTICOS:
            from .geometria.programa_apartamentos import programa_uso_apartamento
            cat = prog.categoria_apartamentos.value
            tip = prog.tipologia_apartamento.value
            grupo = prog.grupo_apartamentos.value
            builder = lambda n, p: programa_uso_apartamento(cat, tip, n_unidades_estimado=n, grupo=grupo)
        elif uso == UsoEdificio.HOTEL_APARTAMENTO:
            from .geometria.programa_hotel_apartamento import programa_uso_hotel_apartamento
            cat = prog.categoria_hotel_apartamento.value
            tip = prog.tipologia_apartamento.value
            builder = lambda n, p: programa_uso_hotel_apartamento(cat, tip, n_unidades_estimado=n)
        elif uso == UsoEdificio.HOTELERO:
            from .geometria.programa_hotelero import programa_uso_hotelero
            cat = prog.categoria_hotelero.value
            tip = prog.tipologia_habitacion.value
            builder = lambda n, p: programa_uso_hotelero(cat, tip, n_unidades_estimado=n, n_plazas_estimado=p)
        else:
            return None

        # Paso 1: provisional para estimar nº de unidades / plazas.
        provisional = builder(4, 8)
        util_obj_efectivo = util_objetivo if util_objetivo is not None else provisional.util_objetivo_unidad_m2
        cap_prov = calcular_capacidad(
            envolvente, params_motor,
            util_objetivo_por_unidad=util_obj_efectivo,
            area_servicios_comunes_m2=provisional.area_servicios_obligatorios_m2,
            descriptores_tipologia=descriptores,
        )
        n_estim = max(2, cap_prov.n_viviendas_objetivo)
        n_plazas_estim = self._estimar_plazas(params, cap_prov)
        return builder(n_estim, n_plazas_estim)

    def _estimar_plazas(self, params: ParametrosRender, cap) -> int:
        """Suma de plazas (camas) de las unidades — relevante en albergue."""
        if params.programa.uso != UsoEdificio.HOTELERO:
            return cap.n_viviendas_objetivo
        from .geometria.programa_hotelero import TIPOLOGIA_HABITACION_A_PLAZAS as PLAZAS
        total = 0
        for fila in getattr(cap, "tipologias_unidad_por_planta", []):
            for slug in fila:
                total += PLAZAS.get(slug, 2)
        return max(total, cap.n_viviendas_objetivo)


# ─── Caso de uso 3: ValidarCumplimiento ─────────────────────────────────────
@dataclass
class ValidarCumplimiento:
    """req. 7 — alertas Anexo I/II + PGOU + accesibilidad."""

    def ejecutar(
        self,
        parcela: ParcelaMetrica,
        params: ParametrosRender,
        normativa: ParametrosUrbanisticos | None,
    ) -> list[Alerta]:
        alertas: list[Alerta] = []

        if normativa is None:
            return alertas

        urb_p = params.urbanisticos
        dis_p = params.diseno
        prog_p = params.programa

        # ── Límites SUPERIORES (proyecto > normativa → incumplimiento) ──
        superiores = [
            ("Coeficiente edificabilidad", urb_p.coeficiente_edificabilidad,
             normativa.coeficiente_edificabilidad, "m²t/m²s", 2),
            ("Ocupación máxima", urb_p.ocupacion_maxima_pct,
             normativa.ocupacion_maxima_pct, "%", 0),
            ("Plantas máximas", urb_p.n_plantas_max,
             normativa.n_plantas_max, "", 0),
            ("Diámetro vestíbulo", dis_p.diametro_min_vestibulo_m,
             normativa.diametro_max_vestibulo_m, "m", 2),
            ("Espesor muro medianero", dis_p.espesor_muro_medianero_m,
             normativa.espesor_muro_medianero_max_m, "m", 2),
            ("Espesor separación unidades", dis_p.espesor_separacion_unidades_m,
             normativa.espesor_separacion_unidades_max_m, "m", 2),
            ("% muros", dis_p.pct_muros,
             normativa.pct_muros_normativo, "%", 1),
        ]
        for nombre, actual, lim, unidad, dec in superiores:
            if actual > lim + 1e-6:
                fmt = f"{{:.{dec}f}}"
                alertas.append(Alerta(
                    "incumplimiento", "Normativa",
                    f"{nombre} {fmt.format(actual)}{unidad} > {fmt.format(lim)}{unidad}.",
                ))

        # ── Límites INFERIORES (proyecto < normativa → aviso) ──
        ancho_fachada_total = sum(l.longitud_m for l in parcela.lados if l.tipo == "fachada")
        inferiores = [
            ("Retranqueo fachada", urb_p.retranqueo_fachada_m,
             normativa.retranqueo_fachada_m, "m", 1),
            ("Retranqueo linderos", urb_p.retranqueo_linderos_m,
             normativa.retranqueo_linderos_m, "m", 1),
            ("Retranqueo ático", urb_p.retranqueo_atico_m,
             normativa.retranqueo_atico_m, "m", 1),
            ("Luz recta patio", urb_p.luz_recta_patio_min_m,
             normativa.luz_recta_patio_min_m, "m", 2),
            ("Área patio mínima", urb_p.area_patio_min_m2,
             normativa.area_patio_min_m2, "m²", 2),
            ("Unidades adaptadas", prog_p.pct_unidades_adaptadas,
             normativa.pct_unidades_adaptadas_min, "%", 0),
            ("Ancho total fachada", ancho_fachada_total,
             normativa.ancho_min_fachada_m, "m", 1),
            ("Espesor tabique", dis_p.espesor_tabique_m,
             normativa.espesor_tabique_min_m, "m", 2),
            ("Pasillo común", dis_p.ancho_min_pasillo_comun_m,
             normativa.ancho_min_pasillo_comun_m, "m", 2),
            ("Pasillo vivienda", dis_p.ancho_min_pasillo_vivienda_m,
             normativa.ancho_min_pasillo_vivienda_m, "m", 2),
            ("Puerta paso libre", dis_p.ancho_min_puerta_m,
             normativa.ancho_min_puerta_m, "m", 2),
        ]
        for nombre, actual, lim, unidad, dec in inferiores:
            if actual + 1e-6 < lim:
                fmt = f"{{:.{dec}f}}"
                alertas.append(Alerta(
                    "aviso", "Normativa",
                    f"{nombre} {fmt.format(actual)}{unidad} < {fmt.format(lim)}{unidad}.",
                ))

        return alertas


# ─── Caso de uso 4: GuardarRender ───────────────────────────────────────────
@dataclass
class GuardarRender:
    """Persiste parámetros + resumen del último cálculo en el aggregate."""

    repo_proyectos: ProyectoRepositorio

    def ejecutar(
        self,
        proyecto: Proyecto,
        params: ParametrosRender,
        resumen: dict[str, Any],
    ) -> Proyecto:
        datos = {
            "parametros": parametros_a_dict(params),
            "resumen_ultimo_calculo": resumen,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        proyecto.fijar_datos(ModuloPuccetti.RENDER_CALCULOS, datos)
        return self.repo_proyectos.guardar(proyecto)


def parametros_desde_proyecto(proyecto: Proyecto | None) -> ParametrosRender:
    """Lee parámetros del aggregate; usa los del módulo de viabilidad como fallback."""
    if proyecto is None:
        return ParametrosRender()
    datos_render = proyecto.datos_por_modulo.get(ModuloPuccetti.RENDER_CALCULOS.value) or {}
    if datos_render.get("parametros"):
        return parametros_desde_dict(datos_render["parametros"])

    # Si no se ha guardado nada todavía, intentamos heredar la edificabilidad
    # introducida en §2.9 viabilidad. Compat con la clave antigua.
    base = ParametrosRender()
    datos_viab = proyecto.datos_por_modulo.get(ModuloPuccetti.VIABILIDAD.value) or {}
    try:
        clave = (
            "coeficiente_edificabilidad"
            if "coeficiente_edificabilidad" in datos_viab
            else "edificabilidad_m2t_m2s"
        )
        base.urbanisticos.coeficiente_edificabilidad = float(
            datos_viab.get(clave, base.urbanisticos.coeficiente_edificabilidad)
        )
    except (TypeError, ValueError):
        pass
    return base


# ─── Helpers privados ───────────────────────────────────────────────────────
def _alerta_dict(a: Alerta) -> dict[str, Any]:
    return {
        "nivel": a.nivel,
        "regla": a.regla,
        "mensaje": a.mensaje,
        "elemento": a.elemento,
    }


def _indicadores_dict(ind: IndicadoresDiseno) -> dict[str, Any]:
    return {
        "compacidad": round(ind.compacidad, 3),
        "proporcion_huecos": round(ind.proporcion_huecos, 3),
        "orientacion_dominante": ind.orientacion_dominante,
        "long_total_fachadas_m": round(ind.long_total_fachadas_m, 2),
        "long_total_medianeras_m": round(ind.long_total_medianeras_m, 2),
        "n_fachadas": ind.n_fachadas,
        "n_medianeras": ind.n_medianeras,
        "orientaciones_fachadas": list(ind.orientaciones_fachadas),
    }


def _indicadores_disenho(
    parcela: ParcelaMetrica,
    plantas: list,
    edificio=None,
) -> IndicadoresDiseno:
    """req. 15 — compacidad, orientación dominante, % huecos."""
    fach = [l for l in parcela.lados if l.tipo == "fachada"]
    med = [l for l in parcela.lados if l.tipo == "medianera"]
    long_fach = sum(l.longitud_m for l in fach)
    long_med = sum(l.longitud_m for l in med)

    orientacion_dom = "—"
    if fach:
        ldom = max(fach, key=lambda l: l.longitud_m)
        orientacion_dom = orientacion_cardinal(ldom.normal_azimut)

    huella = plantas[0].footprint if plantas else parcela.poligono_utm
    area = huella.area
    perim = huella.length if not huella.is_empty else 1.0
    compacidad = (4 * math.pi * area / (perim ** 2)) if perim > 0 else 0.0

    # Estimación gruesa de huecos: 25% de la fachada del edificio (regla de pulgar)
    # por número de plantas. En iteración posterior puede afinarse desde el
    # macro_layout (suma de hueco_disp_m2 por unidad).
    n_plantas = len(plantas) or 1
    altura_total = n_plantas * 3.0
    area_fachada = long_fach * altura_total if long_fach else 1.0
    if edificio is not None and edificio.plantas:
        hueco_total = sum(
            u.hueco_disp_m2 for pl in edificio.plantas for u in pl.unidades
        )
        proporcion = hueco_total / area_fachada if area_fachada > 0 else 0.0
    else:
        proporcion = 0.25  # estimación neutra

    return IndicadoresDiseno(
        compacidad=compacidad,
        proporcion_huecos=proporcion,
        orientacion_dominante=orientacion_dom,
        long_total_fachadas_m=long_fach,
        long_total_medianeras_m=long_med,
        n_fachadas=len(fach),
        n_medianeras=len(med),
        orientaciones_fachadas=[orientacion_cardinal(l.normal_azimut) for l in fach],
    )


def _alertas_envolvente(envolvente, parcela: ParcelaMetrica, params: ParametrosRender) -> list[Alerta]:
    """Alertas derivadas del cálculo de envolvente (§2.4)."""
    alertas: list[Alerta] = []
    if envolvente.edificabilidad_consumida > envolvente.edificabilidad_max + 1e-3:
        alertas.append(Alerta(
            "incumplimiento", "Normativa",
            f"Edificabilidad consumida ({envolvente.edificabilidad_consumida:.2f} m²) "
            f"supera el techo máximo ({envolvente.edificabilidad_max:.2f} m²).",
        ))
    if not [l for l in parcela.lados if l.tipo == "fachada"]:
        alertas.append(Alerta(
            "incumplimiento", "Normativa",
            "La parcela no tiene ningún lado clasificado como fachada. "
            "Sin fachada no se pueden abrir huecos.",
        ))
    return alertas


def _alertas_capacidad(cap, params: ParametrosRender, programa_uso) -> list[Alerta]:
    """Alertas derivadas del cálculo de capacidad (sin geometría)."""
    alertas: list[Alerta] = []

    if cap.factor_limitante != "ninguno (cumple holgado)":
        alertas.append(Alerta(
            "info", "Capacidad",
            f"Factor limitante: {cap.factor_limitante}.",
        ))

    if cap.util_objetivo_viv_m2 > 0:
        util_total_habitable = sum(
            u for u, t in zip(cap.util_por_planta, cap.tipo_planta) if t != "sotano"
        )
        sobrante = util_total_habitable - (cap.n_viviendas_objetivo * cap.util_objetivo_viv_m2)
        if sobrante >= cap.util_objetivo_viv_m2 * 0.5:
            alertas.append(Alerta(
                "info", "Capacidad",
                f"Sobran {sobrante:.2f} m² útiles tras truncar — si reduces el "
                f"objetivo por unidad (hoy {cap.util_objetivo_viv_m2:.2f} m²) "
                f"podría caber 1 unidad más.",
            ))

    if programa_uso is not None and programa_uso.tipo_unidad in (
        "apartamento", "hotel_apartamento", "habitacion"
    ):
        prog = params.programa
        if programa_uso.tipo_unidad == "apartamento":
            cat, tip = prog.categoria_apartamentos.value, prog.tipologia_apartamento.value
            etiqueta_area = "áreas comunes y sociales obligatorias"
        elif programa_uso.tipo_unidad == "hotel_apartamento":
            cat, tip = prog.categoria_hotel_apartamento.value, prog.tipologia_apartamento.value
            etiqueta_area = "áreas sociales obligatorias"
        else:  # habitacion
            cat, tip = prog.categoria_hotelero.value, prog.tipologia_habitacion.value
            etiqueta_area = "áreas sociales del establecimiento"

        if programa_uso.area_servicios_obligatorios_m2 > 0:
            alertas.append(Alerta(
                "info", "Capacidad",
                f"Reservados {programa_uso.area_servicios_obligatorios_m2:.2f} m² para "
                f"{etiqueta_area}. Categoría {cat}.",
            ))
        if cap.util_objetivo_viv_m2 < programa_uso.util_objetivo_unidad_m2 - 1e-3:
            alertas.append(Alerta(
                "aviso", "Normativa",
                f"El objetivo aplicado ({cap.util_objetivo_viv_m2:.2f} m²) es inferior al "
                f"mínimo para {cat} · {tip} ({programa_uso.util_objetivo_unidad_m2:.2f} m²).",
            ))

    return alertas
