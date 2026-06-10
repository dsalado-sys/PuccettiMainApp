"""Rutas del módulo Buscar parcela (§2.1)."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.contextos.localizacion.casos_uso import (
    CargarDetalleSubreferencia,
    CargarTodosLosDetalles,
    CorregirLado,
    CorregirOrientacionLado,
    LocalizarPorCoordenada,
    LocalizarPorDireccion,
    LocalizarPorRC,
    SimplificarContorno,
    asociar_a_proyecto,
    restaurar_parcela_desde_proyecto,
)
from app.contextos.localizacion.puertos import ParcelaTemporalRepositorio
from app.contextos.localizacion.dominio import (
    Parcela,
    ParcelaError,
    ParcelaNoEncontrada,
    RateLimitCatastro,
    SinParcelaEnPunto,
    TipoLado,
)
from app.contextos.localizacion.puertos import CallejeroPort, CatastroPort
from app.contextos.proyectos.puertos import ProyectoRepositorio
from app.nucleo.modelo import ModuloPuccetti, Proyecto, Rol
from app.nucleo.modelo.rol import PermisoModulo, puede_acceder

from ..dependencias import (
    COOKIE_PARCELA,
    callejero_adapter,
    cargar_detalle_subref_uc,
    cargar_todos_detalles_uc,
    catastro_adapter,
    corregir_lado_uc,
    corregir_orientacion_uc,
    exige_proyecto,
    localizar_por_coordenada_uc,
    localizar_por_direccion_uc,
    localizar_por_rc_uc,
    obtener_parcela_temporal,
    parcelas_temporales,
    proyecto_activo,
    repositorio_proyectos,
    rol_activo,
    simplificar_contorno_uc,
)
from ..plantillas import plantillas

log = logging.getLogger(__name__)

router = APIRouter(prefix="/modulos/localizacion")


def _parcela_a_dict(p: Parcela) -> dict:
    return {
        "id": p.id,
        "referencia_catastral": p.referencia_catastral,
        "direccion": p.direccion,
        "municipio": p.municipio,
        "provincia": p.provincia,
        "superficie_m2": p.superficie_m2,
        "uso_catastral": p.uso_catastral,
        "anio_construccion": p.anio_construccion,
        "superficie_construida_total_m2": p.superficie_construida_total_m2,
        "plantas_sobre_rasante": p.plantas_sobre_rasante,
        "plantas_bajo_rasante": p.plantas_bajo_rasante,
        "centroide_lonlat": list(p.centroide_lonlat),
        "contorno_wgs84": [list(pt) for pt in p.contorno_wgs84],
        "contorno_simplificado_wgs84": [list(pt) for pt in p.contorno_simplificado_wgs84],
        "tolerancia_simplificacion_m": p.tolerancia_simplificacion_m,
        "lados": [
            {
                "indice": l.indice,
                "p1": list(l.p1),
                "p2": list(l.p2),
                "longitud_m": round(l.longitud_m, 2),
                "azimut_grados": round(l.azimut_grados, 1),
                "orientacion": l.orientacion,
                "tipo": l.tipo.value,
            }
            for l in p.lados
        ],
        "subreferencias": [
            {
                "rc": s.rc,
                "localizacion": s.localizacion,
                "uso": s.uso,
                "superficie_construida_m2": s.superficie_construida_m2,
                "coeficiente_participacion": s.coeficiente_participacion,
                "anio_construccion": s.anio_construccion,
                "detalle_cargado": s.detalle_cargado,
            }
            for s in p.subreferencias
        ],
        "agregados": (
            {
                "num_referencias": p.agregados.num_referencias,
                "suma_superficie_construida_m2": p.agregados.suma_superficie_construida_m2,
                "edificabilidad_m2t_m2s": p.agregados.edificabilidad_m2t_m2s,
                "num_viviendas": p.agregados.num_viviendas,
                "densidad_viviendas_viv_ha": p.agregados.densidad_viviendas_viv_ha,
            }
            if p.agregados else None
        ),
        "fuente": p.fuente,
    }


def _exige_permiso(rol: Rol, permiso: PermisoModulo) -> None:
    if not puede_acceder(rol, ModuloPuccetti.LOCALIZACION.value, permiso):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"El rol {rol.value} no puede {permiso.value} en buscar parcela.",
        )


def _set_cookie_parcela(respuesta, parcela_id: str) -> None:
    respuesta.set_cookie(
        COOKIE_PARCELA,
        parcela_id,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 4,
    )


def _mapear_error(exc: ParcelaError) -> HTTPException:
    if isinstance(exc, RateLimitCatastro):
        return HTTPException(status_code=503, detail="Catastro ha bloqueado la IP (rate limit). Reintenta en una hora.")
    if isinstance(exc, SinParcelaEnPunto):
        return HTTPException(status_code=422, detail=str(exc) or "El punto no cae sobre ninguna parcela.")
    if isinstance(exc, ParcelaNoEncontrada):
        return HTTPException(status_code=404, detail=str(exc) or "Parcela no encontrada.")
    return HTTPException(status_code=500, detail=str(exc) or "Error de localización.")


# ── Pantalla principal ─────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
def pantalla_buscar(
    request: Request,
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    parcela_temp: Parcela | None = Depends(obtener_parcela_temporal),
    repo_parcelas: ParcelaTemporalRepositorio = Depends(parcelas_temporales),
    uc_rc: LocalizarPorRC = Depends(localizar_por_rc_uc),
):
    _exige_permiso(rol, PermisoModulo.VER)

    # Con proyecto activo: la parcela del proyecto manda sobre cualquier
    # parcela suelta que pudiera quedar en la cookie temporal.
    #   1. Si el proyecto tiene RC, se busca en Catastro para tener datos
    #      frescos (una llamada por entrada al módulo).
    #   2. Si la llamada falla (rate limit, offline) se reconstruye desde el
    #      JSON guardado en datos_por_modulo — degradación suave.
    # Sin proyecto: respetamos la parcela en cookie temporal (si la hay).
    cookie_a_setear: str | None = None
    if proyecto is not None:
        rc_proyecto = (proyecto.referencia_catastral or "").strip()
        parcela_proyecto_obj: Parcela | None = None
        if rc_proyecto:
            try:
                parcela_proyecto_obj = uc_rc.ejecutar(rc_proyecto)
            except ParcelaError as exc:
                log.warning(
                    "No se pudo re-resolver RC %s del proyecto %s: %s",
                    rc_proyecto, proyecto.id, exc,
                )
        if parcela_proyecto_obj is None:
            datos = proyecto.datos_por_modulo.get(ModuloPuccetti.LOCALIZACION.value)
            if isinstance(datos, dict):
                parcela_proyecto_obj = restaurar_parcela_desde_proyecto(datos)
                if parcela_proyecto_obj is not None:
                    repo_parcelas.guardar(parcela_proyecto_obj)
        if parcela_proyecto_obj is not None:
            parcela_temp = parcela_proyecto_obj
            cookie_a_setear = parcela_proyecto_obj.id

    parcela_proyecto = None
    if proyecto is not None:
        parcela_proyecto = proyecto.datos_por_modulo.get(
            ModuloPuccetti.LOCALIZACION.value
        )

    respuesta = plantillas.TemplateResponse(
        request,
        "localizacion.html",
        {
            "rol_activo": rol,
            "proyecto_activo": proyecto,
            "parcela_inicial": _parcela_a_dict(parcela_temp) if parcela_temp else None,
            "parcela_proyecto": parcela_proyecto,
            "puede_editar": puede_acceder(rol, ModuloPuccetti.LOCALIZACION.value, PermisoModulo.EDITAR),
        },
    )
    if cookie_a_setear:
        _set_cookie_parcela(respuesta, cookie_a_setear)
    return respuesta


# ── Búsquedas ──────────────────────────────────────────────────────────────
@router.post("/buscar/rc")
def buscar_por_rc(
    rc: Annotated[str, Form()],
    rol: Rol = Depends(rol_activo),
    uc: LocalizarPorRC = Depends(localizar_por_rc_uc),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    try:
        parcela = uc.ejecutar(rc)
    except ParcelaError as exc:
        raise _mapear_error(exc)
    respuesta = JSONResponse(_parcela_a_dict(parcela))
    _set_cookie_parcela(respuesta, parcela.id)
    return respuesta


@router.post("/buscar/direccion")
def buscar_por_direccion(
    provincia: Annotated[str, Form()],
    municipio: Annotated[str, Form()],
    tipo_via: Annotated[str, Form()],
    calle: Annotated[str, Form()],
    numero: Annotated[str, Form()],
    rol: Rol = Depends(rol_activo),
    uc: LocalizarPorDireccion = Depends(localizar_por_direccion_uc),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    try:
        parcela = uc.ejecutar(provincia, municipio, tipo_via, calle, numero)
    except ParcelaError as exc:
        raise _mapear_error(exc)
    respuesta = JSONResponse(_parcela_a_dict(parcela))
    _set_cookie_parcela(respuesta, parcela.id)
    return respuesta


@router.post("/buscar/coordenada")
def buscar_por_coordenada(
    payload: Annotated[dict, Body(...)],
    rol: Rol = Depends(rol_activo),
    uc: LocalizarPorCoordenada = Depends(localizar_por_coordenada_uc),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    try:
        lon = float(payload["lon"])
        lat = float(payload["lat"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Body debe incluir lon y lat numéricos.")
    try:
        parcela = uc.ejecutar(lon, lat)
    except ParcelaError as exc:
        raise _mapear_error(exc)
    respuesta = JSONResponse(_parcela_a_dict(parcela))
    _set_cookie_parcela(respuesta, parcela.id)
    return respuesta


# ── Acciones sobre la parcela cargada ──────────────────────────────────────
@router.post("/simplificar")
def simplificar(
    payload: Annotated[dict, Body(...)],
    rol: Rol = Depends(rol_activo),
    parcela: Parcela | None = Depends(obtener_parcela_temporal),
    uc: SimplificarContorno = Depends(simplificar_contorno_uc),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    if parcela is None:
        raise HTTPException(status_code=409, detail="No hay parcela en sesión para simplificar.")
    try:
        tol = float(payload.get("tolerancia_m", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="tolerancia_m debe ser numérico.")
    try:
        actualizada = uc.ejecutar(parcela.id, tol)
    except ParcelaError as exc:
        raise _mapear_error(exc)
    return _parcela_a_dict(actualizada)


@router.post("/lado/{indice}/tipo")
def cambiar_tipo_lado(
    indice: int,
    payload: Annotated[dict, Body(...)],
    rol: Rol = Depends(rol_activo),
    parcela: Parcela | None = Depends(obtener_parcela_temporal),
    uc: CorregirLado = Depends(corregir_lado_uc),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    if parcela is None:
        raise HTTPException(status_code=409, detail="No hay parcela en sesión.")
    tipo_raw = (payload or {}).get("tipo", "")
    try:
        nuevo_tipo = TipoLado(tipo_raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="tipo debe ser 'fachada' o 'medianera'.")
    try:
        actualizada = uc.ejecutar(parcela.id, indice, nuevo_tipo)
    except ParcelaError as exc:
        raise _mapear_error(exc)
    return _parcela_a_dict(actualizada)


@router.post("/lado/{indice}/orientacion")
def cambiar_orientacion_lado(
    indice: int,
    payload: Annotated[dict, Body(...)],
    rol: Rol = Depends(rol_activo),
    parcela: Parcela | None = Depends(obtener_parcela_temporal),
    uc: CorregirOrientacionLado = Depends(corregir_orientacion_uc),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    if parcela is None:
        raise HTTPException(status_code=409, detail="No hay parcela en sesión.")
    orientacion = (payload or {}).get("orientacion", "")
    try:
        actualizada = uc.ejecutar(parcela.id, indice, orientacion)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ParcelaError as exc:
        raise _mapear_error(exc)
    return _parcela_a_dict(actualizada)


@router.post("/subreferencia/{rc20}/detalle")
def detalle_subreferencia(
    rc20: str,
    rol: Rol = Depends(rol_activo),
    parcela: Parcela | None = Depends(obtener_parcela_temporal),
    uc: CargarDetalleSubreferencia = Depends(cargar_detalle_subref_uc),
):
    _exige_permiso(rol, PermisoModulo.VER)
    if parcela is None:
        raise HTTPException(status_code=409, detail="No hay parcela en sesión.")
    try:
        subref = uc.ejecutar(parcela.id, rc20)
    except ParcelaError as exc:
        raise _mapear_error(exc)
    return {
        "rc": subref.rc,
        "localizacion": subref.localizacion,
        "uso": subref.uso,
        "superficie_construida_m2": subref.superficie_construida_m2,
        "coeficiente_participacion": subref.coeficiente_participacion,
        "anio_construccion": subref.anio_construccion,
        "detalle_cargado": subref.detalle_cargado,
    }


@router.post("/asociar-a-proyecto")
def asociar(
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto = Depends(exige_proyecto),
    parcela: Parcela | None = Depends(obtener_parcela_temporal),
    bulk: CargarTodosLosDetalles = Depends(cargar_todos_detalles_uc),
    repo_proyectos: ProyectoRepositorio = Depends(repositorio_proyectos),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    if parcela is None:
        raise HTTPException(status_code=409, detail="No hay parcela en sesión.")
    # Antes de copiar al aggregate, completamos los detalles que faltan
    # (coef. participación + año constr.) de todas las subreferencias.
    try:
        parcela = bulk.ejecutar(parcela.id)
    except ParcelaError as exc:
        raise _mapear_error(exc)
    asociar_a_proyecto(parcela, proyecto)
    repo_proyectos.guardar(proyecto)
    return RedirectResponse(url="/modulos/localizacion", status_code=303)


# ── Callejero local (sin tocar Catastro) ───────────────────────────────────
@router.get("/callejero/provincias")
def listar_provincias(
    q: Annotated[str, Query()] = "",
    callejero: CallejeroPort = Depends(callejero_adapter),
):
    return [{"codigo": c, "nombre": n} for c, n in callejero.listar_provincias(q)]


@router.get("/callejero/municipios")
def listar_municipios(
    provincia: Annotated[str, Query(min_length=1, max_length=2)],
    q: Annotated[str, Query()] = "",
    callejero: CallejeroPort = Depends(callejero_adapter),
):
    return [
        {"codigo": c, "nombre": n}
        for c, n in callejero.buscar_municipios(provincia.zfill(2), q)
    ]


@router.get("/callejero/vias")
def listar_vias(
    provincia: Annotated[str, Query(min_length=1)],
    municipio: Annotated[str, Query(min_length=1)],
    rol: Rol = Depends(rol_activo),
    catastro: CatastroPort = Depends(catastro_adapter),
):
    """Lista vías de un municipio (toca el Catastro una vez por click de lupa)."""
    _exige_permiso(rol, PermisoModulo.VER)
    try:
        vias = catastro.listar_vias(provincia, municipio)
    except RateLimitCatastro as exc:
        raise _mapear_error(exc)
    # Cada item viene como "TIPO NOMBRE" (ej. "CL SIERPES"). El frontend lo parte.
    items = []
    for via in vias:
        partes = via.split(" ", 1)
        if len(partes) == 2:
            items.append({"tipo_via": partes[0], "calle": partes[1], "etiqueta": via})
        else:
            items.append({"tipo_via": "", "calle": via, "etiqueta": via})
    return items
