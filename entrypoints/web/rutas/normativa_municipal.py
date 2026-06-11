"""Rutas del módulo Normativa municipal.

Aquí se gestiona la BBDD de carpetas + normativas archivadas. El módulo
Render y cálculos solo CONSULTA estas normativas (vía endpoints del mismo
módulo) para aplicarlas a su proyecto.

Endpoints:
- GET  /modulos/normativa-municipal                → pantalla 2 columnas
- GET  /modulos/normativa-municipal/carpetas       → listar carpetas
- POST /modulos/normativa-municipal/carpetas       → crear carpeta
- DEL  /modulos/normativa-municipal/carpetas/{id}  → eliminar carpeta
- GET  /modulos/normativa-municipal/carpetas/{id}/normativas → listar
- POST /modulos/normativa-municipal/carpetas/{id}/normativas → crear
- GET  /modulos/normativa-municipal/normativas/{id} → obtener una normativa
- PUT  /modulos/normativa-municipal/normativas/{id} → actualizar
- DEL  /modulos/normativa-municipal/normativas/{id} → eliminar
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.nucleo.modelo import ModuloPuccetti, Rol
from app.nucleo.modelo.rol import PermisoModulo, puede_acceder
from app.plataforma.persistencia.carpetas_normativa_sqlalchemy import (
    CarpetasNormativaSQLAlchemy,
)

from app.nucleo.modelo.proyecto import Proyecto

from ..catalogo_modulos import CATALOGO, TarjetaModulo
from ..dependencias import proyecto_activo, rol_activo, sesion_bbdd
from ..plantillas import plantillas


router = APIRouter(prefix="/modulos/normativa-municipal")


def _tarjeta() -> TarjetaModulo:
    for t in CATALOGO:
        if t.id == ModuloPuccetti.NORMATIVA_MUNICIPAL.value:
            return t
    raise HTTPException(status_code=500, detail="Tarjeta normativa_municipal no encontrada.")


def _exige_permiso(rol: Rol, permiso: PermisoModulo) -> None:
    if not puede_acceder(rol, ModuloPuccetti.NORMATIVA_MUNICIPAL.value, permiso):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"El rol {rol.value} no puede {permiso.value} en Normativa municipal.",
        )


def _repo(session: Session = Depends(sesion_bbdd)) -> CarpetasNormativaSQLAlchemy:
    return CarpetasNormativaSQLAlchemy(session)


# ─── Pantalla principal ─────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
def pantalla(
    request: Request,
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
):
    _exige_permiso(rol, PermisoModulo.VER)
    puede_editar = puede_acceder(rol, ModuloPuccetti.NORMATIVA_MUNICIPAL.value, PermisoModulo.EDITAR)
    return plantillas.TemplateResponse(
        request,
        "normativa_municipal.html",
        {
            "tarjeta": _tarjeta(),
            "rol_activo": rol,
            "proyecto_activo": proyecto,
            "puede_editar": puede_editar,
        },
    )


# ─── Carpetas ───────────────────────────────────────────────────────────────
@router.get("/carpetas")
def listar_carpetas(
    rol: Rol = Depends(rol_activo),
    repo: CarpetasNormativaSQLAlchemy = Depends(_repo),
):
    _exige_permiso(rol, PermisoModulo.VER)
    return JSONResponse({"carpetas": repo.listar_carpetas()})


@router.post("/carpetas")
def crear_carpeta(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    repo: CarpetasNormativaSQLAlchemy = Depends(_repo),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    nombre = str(payload.get("nombre", "")).strip()
    if not nombre:
        raise HTTPException(400, "El nombre de la carpeta es obligatorio.")
    try:
        return JSONResponse(repo.crear_carpeta(nombre))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.delete("/carpetas/{carpeta_id}")
def eliminar_carpeta(
    carpeta_id: int,
    rol: Rol = Depends(rol_activo),
    repo: CarpetasNormativaSQLAlchemy = Depends(_repo),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    if not repo.eliminar_carpeta(carpeta_id):
        raise HTTPException(404, f"Carpeta {carpeta_id} no encontrada.")
    return JSONResponse({"ok": True})


# ─── Normativas archivadas dentro de carpetas ────────────────────────────────
@router.get("/carpetas/{carpeta_id}/normativas")
def listar_normativas(
    carpeta_id: int,
    rol: Rol = Depends(rol_activo),
    repo: CarpetasNormativaSQLAlchemy = Depends(_repo),
):
    _exige_permiso(rol, PermisoModulo.VER)
    return JSONResponse({"normativas": repo.listar_normativas(carpeta_id)})


@router.post("/carpetas/{carpeta_id}/normativas")
def crear_normativa(
    carpeta_id: int,
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    repo: CarpetasNormativaSQLAlchemy = Depends(_repo),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    nombre = str(payload.get("nombre", "")).strip()
    direccion = str(payload.get("direccion", "")).strip()
    urb = payload.get("urbanisticos") or {}
    if not nombre:
        raise HTTPException(400, "Falta el nombre de la normativa.")
    try:
        return JSONResponse(repo.crear_normativa(carpeta_id, nombre, direccion, urb))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/normativas/{normativa_id}")
def obtener_normativa(
    normativa_id: int,
    rol: Rol = Depends(rol_activo),
    repo: CarpetasNormativaSQLAlchemy = Depends(_repo),
):
    _exige_permiso(rol, PermisoModulo.VER)
    n = repo.obtener_normativa(normativa_id)
    if n is None:
        raise HTTPException(404, f"Normativa {normativa_id} no encontrada.")
    return JSONResponse(n)


@router.put("/normativas/{normativa_id}")
def actualizar_normativa(
    normativa_id: int,
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    repo: CarpetasNormativaSQLAlchemy = Depends(_repo),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    actual = repo.obtener_normativa(normativa_id)
    if actual is None:
        raise HTTPException(404, f"Normativa {normativa_id} no encontrada.")
    nombre = str(payload.get("nombre", actual["nombre"])).strip() or actual["nombre"]
    direccion = str(payload.get("direccion", actual["direccion"])).strip()
    urb = payload.get("urbanisticos") or actual.get("urbanisticos") or {}
    repo.actualizar_normativa(normativa_id, nombre, direccion, urb)
    return JSONResponse({"ok": True})


@router.delete("/normativas/{normativa_id}")
def eliminar_normativa(
    normativa_id: int,
    rol: Rol = Depends(rol_activo),
    repo: CarpetasNormativaSQLAlchemy = Depends(_repo),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    if not repo.eliminar_normativa(normativa_id):
        raise HTTPException(404, f"Normativa {normativa_id} no encontrada.")
    return JSONResponse({"ok": True})
