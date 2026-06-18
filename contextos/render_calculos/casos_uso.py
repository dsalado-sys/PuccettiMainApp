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
    # Superficie catastral REAL de la parcela (m² de suelo), tal y como la guardó
    # §2.1. Es la fuente de verdad para edificabilidad/ocupación; el área del
    # polígono reproyectado solo se usa si esta falta.
    superficie_catastral_m2: float | None = None


def superficie_referencia_parcela(parcela: ParcelaMetrica) -> float:
    """Superficie de suelo de referencia: catastral real si se conoce, si no la
    geométrica del polígono reproyectado."""
    s = parcela.superficie_catastral_m2
    if s and s > 0:
        return float(s)
    return parcela.poligono_utm.area


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

    try:
        superficie_cat = float(datos.get("superficie_m2") or 0.0)
    except (TypeError, ValueError):
        superficie_cat = 0.0

    return ParcelaMetrica(
        poligono_utm=poly,
        lados=lados,
        municipio=datos.get("municipio"),
        provincia=datos.get("provincia"),
        centroide_lonlat=centroide,
        referencia_catastral=datos.get("referencia_catastral"),
        superficie_catastral_m2=superficie_cat if superficie_cat > 0 else None,
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
        sup_ref = superficie_referencia_parcela(parcela)
        try:
            envolvente = construir_envolvente(
                parcela.poligono_utm, params_motor, parcela.lados,
                superficie_referencia=sup_ref,
            )
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
                "area_m2": round(sup_ref, 2),
                "area_geometrica_m2": round(parcela.poligono_utm.area, 2),
                "superficie_catastral_m2": parcela.superficie_catastral_m2,
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

    def ejecutar(
        self,
        parcela: ParcelaMetrica,
        params: ParametrosRender,
        combo_override: str | None = None,
    ) -> dict[str, Any]:
        """`combo_override` (§2.5): slug de combinación de dormitorios elegida por
        el técnico. Si se indica y el uso es apartamentos turísticos, sustituye la
        tipología por la combinación (toda la unidad, PB y plantas tipo). Selección
        temporal: el caso de uso no la persiste."""
        # Antes de calcular, vuelca los mínimos editables de BBDD a las constantes
        # del motor, para que las ediciones del editor de superficies mínimas se
        # respeten en cada cálculo (Anexo I.1–I.5).
        self._sincronizar_minimos(params)

        # R3: error bloqueante si la suma de mínimos de una tipología de vivienda
        # supera su útil máximo editable (antes se infradimensionaba en silencio).
        err_util_max = self._validar_util_maximo_vivienda(params, combo_override=combo_override)
        if err_util_max:
            return {
                "error": err_util_max,
                "edificio": None,
                "capacidad": None,
                "alertas": [_alerta_dict(Alerta("incumplimiento", "Normativa", err_util_max))],
                "tabla_planta": [],
                "tabla_unidad": [],
                "indicadores": None,
                "envolvente": None,
            }

        params_motor = params.a_parametros_motor()
        params_motor_tipo = params.a_parametros_motor_tipo()
        sup_ref = superficie_referencia_parcela(parcela)
        try:
            envolvente = construir_envolvente(
                parcela.poligono_utm, params_motor, parcela.lados,
                superficie_referencia=sup_ref,
            )
        except ValueError as exc:
            return {
                "error": str(exc),
                "edificio": None,
                "capacidad": None,
                "alertas": [_alerta_dict(Alerta("incumplimiento", "Geometría", str(exc)))],
                "tabla_planta": [],
                "tabla_unidad": [],
                "indicadores": None,
                "envolvente": None,
            }

        # 1) Resolver tamaño objetivo de la tipología principal (PB y plantas tipo).
        util_objetivo = self._resolver_util_objetivo(params, combo_override=combo_override)
        util_objetivo_tipo = self._resolver_util_objetivo(
            params, params.programa_tipo, combo_override=combo_override
        )

        # 2) Descriptores de tipología (principal + extras → mezcla), PB y tipo.
        descriptores = self._construir_descriptores_tipologia(
            params, util_objetivo, combo_override=combo_override
        )
        descriptores_tipo = self._construir_descriptores_tipologia(
            params, util_objetivo_tipo, params.programa_tipo, combo_override=combo_override
        )

        # 3) Construir programa_uso (áreas comunes/sociales obligatorias — de edificio).
        programa_uso = self._construir_programa_uso(
            params, envolvente, params_motor, util_objetivo, descriptores,
            combo_override=combo_override,
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

        # 4) Tablas sintéticas derivadas del cálculo (no de geometría).
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
                "area_m2": round(sup_ref, 2),
                "area_geometrica_m2": round(parcela.poligono_utm.area, 2),
                "superficie_catastral_m2": parcela.superficie_catastral_m2,
                "municipio": parcela.municipio,
                "provincia": parcela.provincia,
                "bbox": [round(v, 2) for v in parcela.poligono_utm.bounds],
            },
            "lados": lados_a_dict(parcela.lados),
        }

    # ─── Helpers privados de CalcularLayout ────────────────────────────────
    def _sincronizar_minimos(self, params: ParametrosRender) -> None:
        """BBDD → constantes del motor antes de calcular (Anexo I.1–I.5).

        Hace que las superficies mínimas editadas desde el editor lleguen al
        dimensionado de estancias en CADA cálculo (no solo vivienda). Es no-op si
        no hay catálogo inyectado (p. ej. en los tests, que usan las constantes del
        Anexo). Ante cualquier fallo, el motor mantiene sus constantes por defecto.
        """
        uso = params.programa.uso
        # % circulación interior de la unidad (panel de diseño, bloque PB). Único
        # y compartido por todos los usos; sustituye el 1.15 antes hardcodeado (R4).
        # Se aplica DESPUÉS de `cargar_desde_repo` para que el valor del panel gane
        # sobre el persistido por defecto (15%).
        pct_circ = float(params.diseno.pct_circulacion_interior)
        try:
            if uso == UsoEdificio.VIVIENDA:
                from .geometria import programa
                if self.catalogo_vivienda is not None:
                    programa.cargar_desde_repo(self.catalogo_vivienda)
                programa.set_pct_circulacion_interior(pct_circ)
            elif uso == UsoEdificio.APARTAMENTOS_TURISTICOS:
                from .geometria import programa_apartamentos
                if self.catalogo_apartamentos is not None:
                    grupo = params.programa.grupo_apartamentos.value
                    programa_apartamentos.cargar_desde_repo(self.catalogo_apartamentos, grupo)
                programa_apartamentos.set_pct_circulacion_interior(pct_circ)
            elif uso == UsoEdificio.HOTEL_APARTAMENTO:
                from .geometria import programa_hotel_apartamento
                if self.catalogo_hotel_apartamento is not None:
                    programa_hotel_apartamento.cargar_desde_repo(self.catalogo_hotel_apartamento)
                programa_hotel_apartamento.set_pct_circulacion_interior(pct_circ)
            elif uso == UsoEdificio.HOTELERO:
                from .geometria import programa_hotelero
                if self.catalogo_hotelero is not None:
                    programa_hotelero.cargar_desde_repo(self.catalogo_hotelero)
                programa_hotelero.set_pct_circulacion_interior(pct_circ)
        except Exception:
            pass

    def _validar_util_maximo_vivienda(self, params: ParametrosRender, combo_override=None) -> str | None:
        """R3: mensaje de error si Σ mínimos de una tipología supera su útil máximo.

        Solo vivienda (único uso con útil máximo editable por tipología). Devuelve
        None si todo cumple. Se evalúa tras `_sincronizar_minimos`, así que usa los
        mínimos y el útil máximo YA editados en BBDD. Sin referencias al PDF.
        """
        prog = params.programa
        if prog.uso != UsoEdificio.VIVIENDA:
            return None
        from .dominio import CATEGORIA_A_NUM_DORMS
        from .geometria.programa import (
            util_maximo,
            util_minimo_vivienda,
            util_minimo_vivienda_combo,
        )
        sco = bool(prog.salon_cocina_open)

        def _mensaje(n: int, umin: float, umax: float) -> str:
            etiqueta = (
                "estudio" if n == 0
                else f"{n} dormitorios" if n < 5
                else "más de 4 dormitorios"
            )
            return (
                f"Tipología «{etiqueta}»: la suma de mínimos de estancias "
                f"({umin:.2f} m²) supera el útil máximo de la vivienda "
                f"({umax:.2f} m²). Sube el útil máximo de esa tipología o reduce "
                f"sus superficies mínimas."
            )

        if combo_override is not None:
            from .geometria.combinador_tipologias import slug_a_combo
            combo = slug_a_combo(combo_override)
            umin = util_minimo_vivienda_combo(combo, sco)
            umax = util_maximo(combo.n_dorms)
            return _mensaje(combo.n_dorms, umin, umax) if umin > umax + 1e-6 else None

        slug_a_n = {"estudio": 0, "1d": 1, "2d": 2, "3d": 3, "4d+": 4}
        ns = [CATEGORIA_A_NUM_DORMS.get(prog.categoria_vivienda, 2)]
        ns += [slug_a_n[s] for s in prog.tipologias_extra if s in slug_a_n]
        for n in ns:
            umin = util_minimo_vivienda(n, sco)
            umax = util_maximo(n)
            if umin > umax + 1e-6:
                return _mensaje(n, umin, umax)
        return None

    def _resolver_util_objetivo(self, params: ParametrosRender, prog=None, combo_override=None) -> float | None:
        """Lee el m² útil objetivo por unidad desde la BBDD del Anexo I.

        Vivienda: `anexo_i_vivienda.max_m2_util` para `n_dormitorios`.
        Apartamentos: `anexo_i_apartamentos.max_m2_util` × 1.15.

        `prog` permite resolver el objetivo de las plantas tipo (`programa_tipo`);
        por defecto usa `params.programa` (planta baja). `combo_override` (§2.5)
        fuerza el objetivo de una combinación de dormitorios (apartamentos).

        Si la consulta falla o la fila no existe → None y `calcular_capacidad`
        cae en el hardcoded `util_maximo(n_dorms)` o `util_objetivo_apartamento`.
        """
        from .dominio import CATEGORIA_A_NUM_DORMS

        prog = prog if prog is not None else params.programa
        if prog.uso == UsoEdificio.APARTAMENTOS_TURISTICOS and combo_override is not None:
            return self._util_objetivo_combo(prog, combo_override)
        if prog.uso == UsoEdificio.VIVIENDA and combo_override is not None:
            from .geometria.combinador_tipologias import slug_a_combo
            from .geometria.programa import util_objetivo_vivienda_combo
            return util_objetivo_vivienda_combo(
                slug_a_combo(combo_override), bool(prog.salon_cocina_open)
            )
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

    def _util_objetivo_combo(self, prog, combo_override: str) -> float:
        """Objetivo de una combinación de dormitorios (§2.5).

        Prioriza la BBDD si la combinación está sembrada (p. ej. el estudio, que
        sí tiene fila); en otro caso compone desde las constantes del Anexo.
        """
        from .geometria.combinador_tipologias import slug_a_combo
        from .geometria.programa_apartamentos import util_objetivo_combo

        combo = slug_a_combo(combo_override)
        cat = prog.categoria_apartamentos.value
        grupo = prog.grupo_apartamentos.value
        if self.catalogo_apartamentos is not None:
            try:
                uo = self.catalogo_apartamentos.util_objetivo_apartamento(cat, combo.slug, grupo)
                if uo is not None and uo > 0:
                    return uo
            except Exception:
                pass
        return util_objetivo_combo(combo, cat, grupo)

    # ─── Descriptores de tipología (mezcla multi-tipología por uso) ─────────
    def _construir_descriptores_tipologia(self, params: ParametrosRender, util_objetivo, prog=None, combo_override=None):
        """Lista de `TipologiaUnidadDescriptor` del uso activo (principal + extras).

        La categoría del proyecto es fija; varía la tipología (igual que en
        vivienda solo varía el nº de dormitorios). `prog` permite construir la lista
        de las plantas tipo (`programa_tipo`); por defecto usa `params.programa`.
        `combo_override` (§2.5) sustituye la tipología por una combinación de
        dormitorios (edificio homogéneo de esa combinación). Devuelve `None` para
        vivienda (que sigue la vía int-based del motor) y para usos no soportados.
        """
        prog = prog if prog is not None else params.programa
        uso = prog.uso
        if uso == UsoEdificio.VIVIENDA and combo_override is not None:
            from .geometria.combinador_tipologias import slug_a_combo
            from .geometria.programa import descriptor_tipologia_vivienda_combo
            d = descriptor_tipologia_vivienda_combo(
                slug_a_combo(combo_override), bool(prog.salon_cocina_open)
            )
            if util_objetivo is not None and util_objetivo > 0:
                d = replace(d, util_objetivo=util_objetivo, util_maximo=round(util_objetivo * 1.25, 2))
            return [d]
        if uso == UsoEdificio.VIVIENDA:
            return None

        if uso == UsoEdificio.APARTAMENTOS_TURISTICOS and combo_override is not None:
            from .geometria.combinador_tipologias import slug_a_combo
            from .geometria.programa_apartamentos import descriptor_tipologia_combo
            combo = slug_a_combo(combo_override)
            d = descriptor_tipologia_combo(
                combo, prog.categoria_apartamentos.value, prog.grupo_apartamentos.value
            )
            if util_objetivo is not None and util_objetivo > 0:
                d = replace(d, util_objetivo=util_objetivo, util_maximo=round(util_objetivo * 1.25, 2))
            return [d]

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

        # Tras `_sincronizar_minimos`, el descriptor que produce `constructor(slug)`
        # ya refleja los mínimos editados en BBDD (su util_objetivo = Σ mínimos del
        # Anexo × 1.15). No se sobreescribe con el adapter, que antes leía un
        # `max_m2_util` que no se actualizaba al editar y dejaba la unidad —y por
        # tanto sus estancias— por debajo de los mínimos reales.
        slugs = [principal] + [s for s in prog.tipologias_extra]
        descriptores = [constructor(slug) for slug in slugs]
        return descriptores or None

    def _construir_programa_uso(
        self,
        params: ParametrosRender,
        envolvente,
        params_motor,
        util_objetivo: float | None,
        descriptores,
        combo_override=None,
    ):
        """Construye el descriptor de uso con sus áreas comunes/sociales obligatorias.

        Para vivienda: None (calcular_capacidad no necesita programa_uso). Para
        apartamentos / hotel-apartamento / hotelero hace una iteración de dos
        pasos para dimensionar las comunes (que escalan con nº de unidades, o de
        plazas en albergue). `combo_override` (§2.5) dimensiona desde la combinación.
        """
        prog = params.programa
        uso = prog.uso
        if uso == UsoEdificio.APARTAMENTOS_TURISTICOS and combo_override is not None:
            from .geometria.combinador_tipologias import slug_a_combo
            from .geometria.programa_apartamentos import programa_uso_apartamento_combo
            combo = slug_a_combo(combo_override)
            cat = prog.categoria_apartamentos.value
            grupo = prog.grupo_apartamentos.value
            builder = lambda n, p: programa_uso_apartamento_combo(combo, cat, n_unidades_estimado=n, grupo=grupo)
        elif uso == UsoEdificio.APARTAMENTOS_TURISTICOS:
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


def _etiqueta_combo(composicion: dict[str, int]) -> str:
    """Etiqueta legible de una combinación: '1 individual + 2 dobles'.

    Sin referencias normativas (memoria feedback_avisos_sin_referencias_pdf).
    """
    if not composicion:
        return "Estudio"
    plural = {
        "individual": ("individual", "individuales"),
        "doble": ("doble", "dobles"),
        "triple": ("triple", "triples"),
        "cuadruple": ("cuádruple", "cuádruples"),
    }
    partes = []
    for tam, n in sorted(composicion.items()):
        sing, plur = plural.get(tam, (tam, tam + "s"))
        partes.append(f"{n} {sing if n == 1 else plur}")
    return " + ".join(partes)


# ─── Caso de uso 3: CalcularTipologiasDormitorios (§2.5 — paradigma nuevo) ──
@dataclass
class CalcularTipologiasDormitorios:
    """req. §2.5 — Dado un nº de dormitorios, enumera TODAS las combinaciones de
    tamaños y calcula cuántas unidades caben de cada una.

    Las combinaciones se ordenan por útil objetivo ascendente y se **podan** al
    primer combo no viable (0 unidades): como el nº de unidades es no-creciente
    con el útil objetivo, a partir de ahí ninguna cabe. Reutiliza `CalcularLayout`
    con `combo_override` para que el conteo coincida exactamente con el que se
    obtiene al elegir esa combinación. Aplica a **vivienda** (dormitorios
    individual/doble) y **apartamentos turísticos** (individual/doble/triple/
    cuádruple); hotelero y hotel-apartamento clasifican por ocupación → error.
    """

    catalogo_vivienda: CatalogoSuperficiesRepositorio | None = None
    catalogo_apartamentos: CatalogoApartamentosRepositorio | None = None
    catalogo_hotel_apartamento: CatalogoHotelApartamentoRepositorio | None = None
    catalogo_hotelero: CatalogoHoteleroRepositorio | None = None

    def ejecutar(
        self,
        parcela: ParcelaMetrica,
        params: ParametrosRender,
        n_dorms: int,
    ) -> dict[str, Any]:
        from .geometria.combinador_tipologias import enumerar_combinaciones

        prog = params.programa
        uso = prog.uso
        n_dorms = max(0, int(n_dorms))

        # Reutiliza el motor de layout (y vuelca los mínimos editables de BBDD a las
        # constantes ANTES de que las lambdas `objetivo`/`minimo` los lean al ordenar).
        layout = CalcularLayout(
            catalogo_vivienda=self.catalogo_vivienda,
            catalogo_apartamentos=self.catalogo_apartamentos,
            catalogo_hotel_apartamento=self.catalogo_hotel_apartamento,
            catalogo_hotelero=self.catalogo_hotelero,
        )
        layout._sincronizar_minimos(params)

        # Despacho por uso: alfabeto de tamaños, objetivo, mínimo y plazas.
        if uso == UsoEdificio.APARTAMENTOS_TURISTICOS:
            from .geometria.programa_apartamentos import (
                PLAZAS, TAMANOS_DORMITORIO, util_minimo_combo,
            )
            cat = prog.categoria_apartamentos.value
            grupo = prog.grupo_apartamentos.value
            tamanos = TAMANOS_DORMITORIO
            plazas_map = PLAZAS
            objetivo = lambda combo: self._util_objetivo_combo(prog, combo.slug)
            minimo = lambda combo: util_minimo_combo(combo, cat, grupo)
            meta = {"categoria": cat, "grupo": grupo}
        elif uso == UsoEdificio.VIVIENDA:
            from .geometria.programa import (
                PLAZAS_DORMITORIO_VIVIENDA, TAMANOS_DORMITORIO_VIVIENDA,
                util_minimo_vivienda_combo, util_objetivo_vivienda_combo,
            )
            salon_open = bool(prog.salon_cocina_open)
            tamanos = TAMANOS_DORMITORIO_VIVIENDA
            plazas_map = PLAZAS_DORMITORIO_VIVIENDA
            objetivo = lambda combo: util_objetivo_vivienda_combo(combo, salon_open)
            minimo = lambda combo: (
                util_objetivo_vivienda_combo(combo, salon_open) if combo.es_estudio
                else util_minimo_vivienda_combo(combo, salon_open)
            )
            meta = {"categoria": prog.categoria_vivienda.value}
        else:
            return {
                "error": "El cálculo por nº de dormitorios solo aplica a vivienda y apartamentos turísticos.",
                "n_dorms": n_dorms, "combinaciones": [],
            }

        # Orden ascendente por útil objetivo → habilita la poda.
        combos = sorted(enumerar_combinaciones(n_dorms, tamanos), key=objetivo)

        viables: list[dict[str, Any]] = []
        for combo in combos:
            res = layout.ejecutar(parcela, params, combo_override=combo.slug)
            if res.get("error"):
                # Envolvente inválida: no depende de la combinación → abortar.
                return {"error": res["error"], "n_dorms": n_dorms, "combinaciones": []}
            cap = res.get("capacidad") or {}
            n_unidades = int(cap.get("n_viviendas_objetivo", 0) or 0)
            if n_unidades <= 0:
                break  # poda: las combinaciones mayores tampoco caben
            viables.append({
                "slug": combo.slug,
                "composicion": dict(combo.composicion),
                "etiqueta": _etiqueta_combo(combo.composicion),
                "n_dorms": combo.n_dorms,
                "plazas": combo.plazas(plazas_map),
                "util_objetivo_m2": round(objetivo(combo), 2),
                "util_minimo_m2": round(minimo(combo), 2),
                "n_unidades": n_unidades,
            })

        return {
            "n_dorms": n_dorms,
            **meta,
            "total_combinaciones": len(combos),
            "viables": len(viables),
            "podadas": len(combos) - len(viables),
            "combinaciones": viables,
        }

    def _util_objetivo_combo(self, prog, slug: str) -> float:
        """Objetivo de la combinación (BBDD si sembrada, si no constante del Anexo)."""
        from .geometria.combinador_tipologias import slug_a_combo
        from .geometria.programa_apartamentos import util_objetivo_combo

        combo = slug_a_combo(slug)
        cat = prog.categoria_apartamentos.value
        grupo = prog.grupo_apartamentos.value
        if self.catalogo_apartamentos is not None:
            try:
                uo = self.catalogo_apartamentos.util_objetivo_apartamento(cat, combo.slug, grupo)
                if uo is not None and uo > 0:
                    return uo
            except Exception:
                pass
        return util_objetivo_combo(combo, cat, grupo)


# ─── Caso de uso 4: ValidarCumplimiento ─────────────────────────────────────
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
