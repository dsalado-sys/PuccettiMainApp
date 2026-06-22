"""Casos de uso de localización (§2.1)."""
from __future__ import annotations

from dataclasses import dataclass

from app.nucleo.modelo import ModuloPuccetti, Proyecto

from .dominio import (
    AgregadosMetaparcela,
    Lado,
    ORIENTACIONES,
    Parcela,
    ParcelaNoEncontrada,
    RateLimitCatastro,
    Subreferencia,
    TipoLado,
)
from .geometria import (
    area_m2_utm,
    bbox_wgs84_con_margen,
    clasificar_por_sondeo,
    extraer_lados,
    simplificar_dp_utm,
)
from .puertos import CatastroPort, ParcelaRaw, ParcelaTemporalRepositorio

# Palabras que indican uso residencial en la nomenclatura del Catastro.
_PALABRAS_VIVIENDA = ("VIVIENDA", "RESIDENCIAL")


def _uso_es_vivienda(uso: str) -> bool:
    if not uso:
        return False
    u = uso.upper()
    return any(p in u for p in _PALABRAS_VIVIENDA)


def calcular_agregados(
    subreferencias: list[Subreferencia],
    superficie_parcela_m2: float,
) -> AgregadosMetaparcela | None:
    """Agregados de una metaparcela. Devuelve None si no hay subreferencias."""
    if not subreferencias:
        return None
    suma = sum(s.superficie_construida_m2 or 0.0 for s in subreferencias)
    n_viv = sum(1 for s in subreferencias if _uso_es_vivienda(s.uso))
    sup = float(superficie_parcela_m2 or 0.0)
    edif = (suma / sup) if sup > 0 else 0.0
    densidad = (n_viv / (sup / 10_000.0)) if sup > 0 else 0.0
    return AgregadosMetaparcela(
        num_referencias=len(subreferencias),
        suma_superficie_construida_m2=suma,
        edificabilidad_m2t_m2s=edif,
        num_viviendas=n_viv,
        densidad_viviendas_viv_ha=densidad,
    )


def _construir_parcela(
    raw: ParcelaRaw,
    fuente: str,
    contornos_vecinos: list[list[tuple[float, float]]],
) -> Parcela:
    lados = extraer_lados(raw.contorno_wgs84)
    lados_clasificados = clasificar_por_sondeo(
        lados, raw.contorno_wgs84, contornos_vecinos
    )
    # Si el Catastro no dio superficie de suelo, deducirla del polígono UTM.
    superficie = float(raw.superficie_m2 or 0.0)
    if superficie <= 0.0:
        superficie = area_m2_utm(raw.contorno_wgs84)
    subrefs = list(raw.subreferencias)
    agregados = calcular_agregados(subrefs, superficie)
    return Parcela(
        referencia_catastral=raw.referencia_catastral,
        direccion=raw.direccion,
        municipio=raw.municipio,
        provincia=raw.provincia,
        superficie_m2=superficie,
        centroide_lonlat=raw.centroide_lonlat,
        contorno_wgs84=list(raw.contorno_wgs84),
        contorno_simplificado_wgs84=list(raw.contorno_wgs84),
        tolerancia_simplificacion_m=0.0,
        lados=lados_clasificados,
        fuente=fuente,
        subreferencias=subrefs,
        agregados=agregados,
        uso_catastral=raw.uso_catastral,
        anio_construccion=raw.anio_construccion,
        superficie_construida_total_m2=raw.superficie_construida_total_m2,
        plantas_sobre_rasante=raw.plantas_sobre_rasante,
        plantas_bajo_rasante=raw.plantas_bajo_rasante,
    )


def _vecinos(catastro: CatastroPort, raw: ParcelaRaw) -> list[list[tuple[float, float]]]:
    """Pide al Catastro los contornos de parcelas vecinas. Falla suave: lista vacía."""
    try:
        bbox = bbox_wgs84_con_margen(raw.contorno_wgs84, margen_metros=30.0)
        return catastro.vecinos_en_bbox(bbox, excluir_rc=raw.referencia_catastral)
    except Exception:
        return []


@dataclass
class LocalizarPorRC:
    catastro: CatastroPort
    repo: ParcelaTemporalRepositorio

    def ejecutar(self, rc: str) -> Parcela:
        raw = self.catastro.buscar_por_rc(rc.strip())
        parcela = _construir_parcela(raw, "rc", _vecinos(self.catastro, raw))
        self.repo.guardar(parcela)
        return parcela


@dataclass
class LocalizarPorDireccion:
    catastro: CatastroPort
    repo: ParcelaTemporalRepositorio

    def ejecutar(
        self,
        provincia: str,
        municipio: str,
        tipo_via: str,
        calle: str,
        numero: str,
    ) -> Parcela:
        raw = self.catastro.buscar_por_direccion(
            provincia.strip(),
            municipio.strip(),
            tipo_via.strip(),
            calle.strip(),
            numero.strip(),
        )
        parcela = _construir_parcela(raw, "direccion", _vecinos(self.catastro, raw))
        self.repo.guardar(parcela)
        return parcela


@dataclass
class LocalizarPorCoordenada:
    catastro: CatastroPort
    repo: ParcelaTemporalRepositorio

    def ejecutar(self, lon: float, lat: float) -> Parcela:
        raw = self.catastro.buscar_por_coordenada(float(lon), float(lat))
        parcela = _construir_parcela(raw, "coordenada", _vecinos(self.catastro, raw))
        self.repo.guardar(parcela)
        return parcela


@dataclass
class SimplificarContorno:
    repo: ParcelaTemporalRepositorio
    catastro: CatastroPort

    def ejecutar(self, parcela_id: str, tolerancia_m: float) -> Parcela:
        parcela = self.repo.obtener(parcela_id)
        if parcela is None:
            raise ParcelaNoEncontrada(f"No hay parcela con id {parcela_id} en memoria.")
        tol = max(0.0, float(tolerancia_m))
        nuevo_contorno = simplificar_dp_utm(parcela.contorno_wgs84, tol)
        nuevos_lados = extraer_lados(nuevo_contorno)
        try:
            bbox = bbox_wgs84_con_margen(parcela.contorno_wgs84, margen_metros=30.0)
            vecinos = self.catastro.vecinos_en_bbox(
                bbox, excluir_rc=parcela.referencia_catastral
            )
        except Exception:
            vecinos = []
        parcela.lados = clasificar_por_sondeo(nuevos_lados, nuevo_contorno, vecinos)
        parcela.contorno_simplificado_wgs84 = nuevo_contorno
        parcela.tolerancia_simplificacion_m = tol
        self.repo.guardar(parcela)
        return parcela


@dataclass
class CorregirLado:
    repo: ParcelaTemporalRepositorio

    def ejecutar(self, parcela_id: str, indice: int, nuevo_tipo: TipoLado) -> Parcela:
        parcela = self.repo.obtener(parcela_id)
        if parcela is None:
            raise ParcelaNoEncontrada(f"No hay parcela con id {parcela_id} en memoria.")
        encontrado = False
        for lado in parcela.lados:
            if lado.indice == indice:
                lado.tipo = nuevo_tipo
                encontrado = True
                break
        if not encontrado:
            raise ParcelaNoEncontrada(
                f"La parcela {parcela_id} no tiene un lado con índice {indice}."
            )
        self.repo.guardar(parcela)
        return parcela


@dataclass
class CorregirOrientacionLado:
    repo: ParcelaTemporalRepositorio

    def ejecutar(self, parcela_id: str, indice: int, nueva_orientacion: str) -> Parcela:
        if nueva_orientacion not in ORIENTACIONES:
            raise ValueError(
                f"Orientación inválida: {nueva_orientacion}. Permitidas: {ORIENTACIONES}."
            )
        parcela = self.repo.obtener(parcela_id)
        if parcela is None:
            raise ParcelaNoEncontrada(f"No hay parcela con id {parcela_id} en memoria.")
        encontrado = False
        for lado in parcela.lados:
            if lado.indice == indice:
                lado.orientacion = nueva_orientacion
                encontrado = True
                break
        if not encontrado:
            raise ParcelaNoEncontrada(
                f"La parcela {parcela_id} no tiene un lado con índice {indice}."
            )
        self.repo.guardar(parcela)
        return parcela


@dataclass
class SeleccionarInmueble:
    """Marca uno de los inmuebles de la metaparcela como el elegido.

    No toca el Catastro: la subreferencia (con su escalera·planta·puerta y su
    superficie construida ya parseada del listado de la metaparcela) vive en
    `parcela.subreferencias`. Solo la fija como `inmueble_seleccionado` para que
    se muestre y se persista con el proyecto (ver [[feedback-no-quemar-api-catastro]]).
    """
    repo: ParcelaTemporalRepositorio

    def ejecutar(self, parcela_id: str, rc20: str) -> Parcela:
        parcela = self.repo.obtener(parcela_id)
        if parcela is None:
            raise ParcelaNoEncontrada(f"No hay parcela con id {parcela_id} en memoria.")
        rc = (rc20 or "").strip().upper().replace(" ", "")
        if not rc:
            parcela.inmueble_seleccionado = None
        else:
            elegido = next(
                (s for s in parcela.subreferencias
                 if (s.rc or "").strip().upper().replace(" ", "") == rc),
                None,
            )
            if elegido is None:
                raise ParcelaNoEncontrada(
                    f"La parcela {parcela_id} no contiene la referencia {rc20}."
                )
            parcela.inmueble_seleccionado = elegido
        self.repo.guardar(parcela)
        return parcela


@dataclass
class CargarTodosLosDetalles:
    """Recorre todas las subreferencias y rellena coef. participación + año.

    Una llamada al Catastro por subreferencia. Si alguna falla por rate limit,
    propaga el error; los demás fallos (ParcelaNoEncontrada, etc.) se ignoran
    y se sigue con la siguiente — la parcela queda con `detalle_cargado=True`
    en las que sí pudieron resolverse.
    """
    catastro: CatastroPort
    repo: ParcelaTemporalRepositorio

    def ejecutar(self, parcela_id: str) -> Parcela:
        parcela = self.repo.obtener(parcela_id)
        if parcela is None:
            raise ParcelaNoEncontrada(f"No hay parcela con id {parcela_id} en memoria.")
        for s in parcela.subreferencias:
            if s.detalle_cargado:
                continue
            try:
                detalle = self.catastro.obtener_detalle_subreferencia(s.rc)
            except RateLimitCatastro:
                # Rate limit afecta a toda la app: aborta el bulk y propaga
                # para que el handler avise al usuario.
                self.repo.guardar(parcela)
                raise
            except Exception:
                continue
            s.coeficiente_participacion = detalle.coeficiente_participacion
            s.anio_construccion = detalle.anio_construccion
            s.detalle_cargado = True
        self.repo.guardar(parcela)
        return parcela


@dataclass
class CargarDetalleSubreferencia:
    """Llamada lazy: el técnico pide enriquecer una fila concreta de la tabla."""
    catastro: CatastroPort
    repo: ParcelaTemporalRepositorio

    def ejecutar(self, parcela_id: str, rc20: str) -> Subreferencia:
        parcela = self.repo.obtener(parcela_id)
        if parcela is None:
            raise ParcelaNoEncontrada(f"No hay parcela con id {parcela_id} en memoria.")
        objetivo: Subreferencia | None = None
        for s in parcela.subreferencias:
            if s.rc == rc20:
                objetivo = s
                break
        if objetivo is None:
            raise ParcelaNoEncontrada(
                f"La parcela {parcela_id} no contiene la subreferencia {rc20}."
            )
        if objetivo.detalle_cargado:
            return objetivo
        detalle = self.catastro.obtener_detalle_subreferencia(rc20)
        objetivo.coeficiente_participacion = detalle.coeficiente_participacion
        objetivo.anio_construccion = detalle.anio_construccion
        objetivo.detalle_cargado = True
        self.repo.guardar(parcela)
        return objetivo


def restaurar_parcela_desde_proyecto(datos: dict) -> Parcela | None:
    """Reconstruye un Parcela del dominio desde el JSON guardado en el aggregate.

    Inversa de `asociar_a_proyecto`. Devuelve None si el dict no tiene la forma
    esperada (proyectos antiguos guardados con otra versión).
    """
    if not isinstance(datos, dict) or not datos.get("referencia_catastral"):
        return None
    try:
        contorno = [tuple(p) for p in (datos.get("contorno_wgs84") or [])]
        contorno_simpl = [tuple(p) for p in (datos.get("contorno_simplificado_wgs84") or contorno)]
        centroide = tuple(datos.get("centroide_lonlat") or (0.0, 0.0))
        lados_raw = datos.get("lados") or []
        lados: list[Lado] = []
        for l in lados_raw:
            try:
                lados.append(Lado(
                    indice=int(l["indice"]),
                    p1=tuple(l["p1"]),
                    p2=tuple(l["p2"]),
                    longitud_m=float(l.get("longitud_m") or 0.0),
                    azimut_grados=float(l.get("azimut_grados") or 0.0),
                    tipo=TipoLado(l.get("tipo", "fachada")),
                    orientacion=str(l.get("orientacion") or "N"),
                ))
            except (KeyError, ValueError, TypeError):
                continue
        def _subref_desde_dict(s: dict) -> Subreferencia | None:
            try:
                return Subreferencia(
                    rc=str(s.get("rc") or ""),
                    localizacion=str(s.get("localizacion") or ""),
                    uso=str(s.get("uso") or ""),
                    superficie_construida_m2=float(s.get("superficie_construida_m2") or 0.0),
                    coeficiente_participacion=s.get("coeficiente_participacion"),
                    anio_construccion=s.get("anio_construccion"),
                    detalle_cargado=bool(s.get("detalle_cargado", False)),
                )
            except (TypeError, ValueError):
                return None

        subref_raw = datos.get("subreferencias") or []
        subreferencias: list[Subreferencia] = []
        for s in subref_raw:
            sub = _subref_desde_dict(s)
            if sub is not None:
                subreferencias.append(sub)

        inm_raw = datos.get("inmueble_seleccionado")
        inmueble_sel = _subref_desde_dict(inm_raw) if isinstance(inm_raw, dict) else None
        agg_raw = datos.get("agregados")
        agregados = None
        if isinstance(agg_raw, dict):
            agregados = AgregadosMetaparcela(
                num_referencias=int(agg_raw.get("num_referencias") or 0),
                suma_superficie_construida_m2=float(agg_raw.get("suma_superficie_construida_m2") or 0.0),
                edificabilidad_m2t_m2s=float(agg_raw.get("edificabilidad_m2t_m2s") or 0.0),
                num_viviendas=int(agg_raw.get("num_viviendas") or 0),
                densidad_viviendas_viv_ha=float(agg_raw.get("densidad_viviendas_viv_ha") or 0.0),
            )
        def _entero_o_none(v):
            try:
                return int(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                return None

        def _flotante_o_none(v):
            try:
                return float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                return None

        return Parcela(
            referencia_catastral=str(datos["referencia_catastral"]),
            direccion=str(datos.get("direccion") or ""),
            municipio=str(datos.get("municipio") or ""),
            provincia=str(datos.get("provincia") or ""),
            superficie_m2=float(datos.get("superficie_m2") or 0.0),
            centroide_lonlat=centroide,
            contorno_wgs84=contorno,
            contorno_simplificado_wgs84=contorno_simpl,
            tolerancia_simplificacion_m=float(datos.get("tolerancia_simplificacion_m") or 0.0),
            lados=lados,
            fuente=str(datos.get("fuente") or "proyecto"),
            subreferencias=subreferencias,
            inmueble_seleccionado=inmueble_sel,
            agregados=agregados,
            uso_catastral=str(datos.get("uso_catastral") or ""),
            anio_construccion=_entero_o_none(datos.get("anio_construccion")),
            superficie_construida_total_m2=_flotante_o_none(
                datos.get("superficie_construida_total_m2")
            ),
            plantas_sobre_rasante=_entero_o_none(datos.get("plantas_sobre_rasante")),
            plantas_bajo_rasante=_entero_o_none(datos.get("plantas_bajo_rasante")),
        )
    except Exception:
        return None


def _subref_a_dict(s: Subreferencia) -> dict:
    """Serializa una subreferencia (inmueble) a JSON-friendly dict."""
    return {
        "rc": s.rc,
        "localizacion": s.localizacion,
        "uso": s.uso,
        "superficie_construida_m2": s.superficie_construida_m2,
        "coeficiente_participacion": s.coeficiente_participacion,
        "anio_construccion": s.anio_construccion,
        "detalle_cargado": s.detalle_cargado,
    }


def asociar_a_proyecto(parcela: Parcela, proyecto: Proyecto) -> None:
    """Vuelca la parcela del cache temporal al aggregate Proyecto.

    Además del JSON detallado en `datos_por_modulo["localizacion"]`, copia la
    RC (14 chars) y la dirección al propio aggregate para que aparezcan en la
    cabecera del proyecto y permitan re-resolver la parcela desde Catastro
    al re-entrar al módulo.
    """
    # Cabecera del proyecto — visible en /proyectos y usable para re-lookup.
    if parcela.referencia_catastral:
        proyecto.referencia_catastral = parcela.referencia_catastral
    if parcela.direccion:
        proyecto.direccion = parcela.direccion

    proyecto.fijar_datos(
        ModuloPuccetti.LOCALIZACION,
        {
            "referencia_catastral": parcela.referencia_catastral,
            "direccion": parcela.direccion,
            "municipio": parcela.municipio,
            "provincia": parcela.provincia,
            "superficie_m2": parcela.superficie_m2,
            "uso_catastral": parcela.uso_catastral,
            "anio_construccion": parcela.anio_construccion,
            "superficie_construida_total_m2": parcela.superficie_construida_total_m2,
            "plantas_sobre_rasante": parcela.plantas_sobre_rasante,
            "plantas_bajo_rasante": parcela.plantas_bajo_rasante,
            "centroide_lonlat": list(parcela.centroide_lonlat),
            "contorno_wgs84": [list(p) for p in parcela.contorno_wgs84],
            "contorno_simplificado_wgs84": [
                list(p) for p in parcela.contorno_simplificado_wgs84
            ],
            "tolerancia_simplificacion_m": parcela.tolerancia_simplificacion_m,
            "lados": [
                {
                    "indice": l.indice,
                    "p1": list(l.p1),
                    "p2": list(l.p2),
                    "longitud_m": l.longitud_m,
                    "azimut_grados": l.azimut_grados,
                    "orientacion": l.orientacion,
                    "tipo": l.tipo.value,
                }
                for l in parcela.lados
            ],
            "subreferencias": [
                _subref_a_dict(s) for s in parcela.subreferencias
            ],
            "inmueble_seleccionado": (
                _subref_a_dict(parcela.inmueble_seleccionado)
                if parcela.inmueble_seleccionado else None
            ),
            "agregados": (
                {
                    "num_referencias": parcela.agregados.num_referencias,
                    "suma_superficie_construida_m2": parcela.agregados.suma_superficie_construida_m2,
                    "edificabilidad_m2t_m2s": parcela.agregados.edificabilidad_m2t_m2s,
                    "num_viviendas": parcela.agregados.num_viviendas,
                    "densidad_viviendas_viv_ha": parcela.agregados.densidad_viviendas_viv_ha,
                }
                if parcela.agregados else None
            ),
            "fuente": parcela.fuente,
        },
    )
