"""Rutas de gestión de proyectos (§2.11).

Pantalla a 2 columnas (espejo de Normativa municipal): a la izquierda las
carpetas con sus proyectos dentro (más un grupo «Sin carpeta»); a la derecha
el detalle del proyecto seleccionado, con acciones para abrirlo (proyecto
activo), deseleccionarlo, moverlo de carpeta o eliminarlo.

Endpoints:
- GET    /proyectos                       → pantalla 2 columnas
- GET    /proyectos/datos                 → carpetas + proyectos + activo (JSON)
- POST   /proyectos                       → crear proyecto (JSON)
- DELETE /proyectos/{id}                  → eliminar proyecto (JSON)
- POST   /proyectos/{id}/carpeta          → mover proyecto de carpeta (JSON)
- POST   /proyectos/{id}/activar          → fijar proyecto activo (cookie)
- POST   /proyectos/desactivar            → deseleccionar proyecto activo (cookie)
- POST   /proyectos/carpetas              → crear carpeta (JSON)
- DELETE /proyectos/carpetas/{id}         → eliminar carpeta (JSON; no borra proyectos)
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse

from app.contextos.proyectos.casos_uso import (
    CrearProyecto,
    EliminarProyecto,
    ListarProyectos,
)
from app.nucleo.modelo import Proyecto, Rol
from app.nucleo.modelo.rol import PermisoModulo, puede_acceder

from ..dependencias import (
    COOKIE_PROYECTO,
    carpetas_proyecto_repo,
    crear_proyecto_uc,
    eliminar_proyecto_uc,
    listar_proyectos_uc,
    proyecto_activo,
    rol_activo,
)
from ..plantillas import plantillas

router = APIRouter(prefix="/proyectos")


def _puede_editar(rol: Rol) -> bool:
    return puede_acceder(rol, "proyectos", PermisoModulo.EDITAR)


def _exige_edicion(rol: Rol) -> None:
    if not _puede_editar(rol):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"El rol {rol.value} no puede editar proyectos.",
        )


# ─── Pantalla principal ─────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
def listar(
    request: Request,
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
):
    return plantillas.TemplateResponse(
        request,
        "proyectos.html",
        {
            "rol_activo": rol,
            "proyecto_activo": proyecto,
            "puede_editar": _puede_editar(rol),
        },
    )


# ─── Datos (carpetas + proyectos + activo) ──────────────────────────────────
@router.get("/datos")
def datos(
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    uc: ListarProyectos = Depends(listar_proyectos_uc),
    carpetas=Depends(carpetas_proyecto_repo),
):
    mapa = carpetas.mapa_proyecto_carpeta()
    proyectos = [
        {
            "id": p.id,
            "nombre": p.nombre,
            "referencia_catastral": p.referencia_catastral,
            "direccion": p.direccion,
            "estado": p.estado.value,
            "actualizado_en": p.actualizado_en.strftime("%Y-%m-%d %H:%M"),
            "carpeta_id": mapa.get(p.id),
        }
        for p in uc.ejecutar()
    ]
    return JSONResponse(
        {
            "carpetas": carpetas.listar_carpetas(),
            "proyectos": proyectos,
            "activo_id": proyecto.id if proyecto else None,
        }
    )


# ─── CRUD de proyectos ──────────────────────────────────────────────────────
@router.post("")
def crear(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    uc: CrearProyecto = Depends(crear_proyecto_uc),
    carpetas=Depends(carpetas_proyecto_repo),
):
    _exige_edicion(rol)
    nombre = str(payload.get("nombre", "")).strip()
    carpeta_id = payload.get("carpeta_id")
    try:
        proyecto = uc.ejecutar(nombre=nombre, creado_por=rol.value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if carpeta_id is not None:
        try:
            carpetas.mover_proyecto(proyecto.id, int(carpeta_id))
        except (ValueError, TypeError):
            pass  # carpeta inválida: el proyecto se queda en «Sin carpeta»
    return JSONResponse(
        {"id": proyecto.id, "nombre": proyecto.nombre, "carpeta_id": carpeta_id}
    )


@router.delete("/{proyecto_id}")
def eliminar(
    proyecto_id: str,
    request: Request,
    rol: Rol = Depends(rol_activo),
    uc: EliminarProyecto = Depends(eliminar_proyecto_uc),
    carpetas=Depends(carpetas_proyecto_repo),
):
    _exige_edicion(rol)
    if not uc.ejecutar(proyecto_id):
        raise HTTPException(404, f"Proyecto {proyecto_id} no encontrado.")
    carpetas.olvidar_proyecto(proyecto_id)
    respuesta = JSONResponse({"ok": True})
    # Si el proyecto borrado era el activo, dejar de tenerlo activo.
    if request.cookies.get(COOKIE_PROYECTO) == proyecto_id:
        respuesta.delete_cookie(COOKIE_PROYECTO)
    return respuesta


@router.post("/{proyecto_id}/carpeta")
def mover_a_carpeta(
    proyecto_id: str,
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    carpetas=Depends(carpetas_proyecto_repo),
):
    _exige_edicion(rol)
    bruto = payload.get("carpeta_id")
    carpeta_id = None if bruto in (None, "", "null") else int(bruto)
    try:
        carpetas.mover_proyecto(proyecto_id, carpeta_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"ok": True})


# ─── Proyecto activo (cookie) ───────────────────────────────────────────────
@router.post("/{proyecto_id}/activar")
def activar(proyecto_id: str):
    respuesta = JSONResponse({"ok": True, "activo_id": proyecto_id})
    respuesta.set_cookie(COOKIE_PROYECTO, proyecto_id, httponly=True, samesite="lax")
    return respuesta


@router.post("/desactivar")
def desactivar():
    respuesta = JSONResponse({"ok": True, "activo_id": None})
    respuesta.delete_cookie(COOKIE_PROYECTO)
    return respuesta


# ─── Carpetas ───────────────────────────────────────────────────────────────
@router.post("/carpetas")
def crear_carpeta(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    carpetas=Depends(carpetas_proyecto_repo),
):
    _exige_edicion(rol)
    nombre = str(payload.get("nombre", "")).strip()
    if not nombre:
        raise HTTPException(400, "El nombre de la carpeta es obligatorio.")
    try:
        return JSONResponse(carpetas.crear_carpeta(nombre))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.delete("/carpetas/{carpeta_id}")
def eliminar_carpeta(
    carpeta_id: int,
    rol: Rol = Depends(rol_activo),
    carpetas=Depends(carpetas_proyecto_repo),
):
    _exige_edicion(rol)
    if not carpetas.eliminar_carpeta(carpeta_id):
        raise HTTPException(404, f"Carpeta {carpeta_id} no encontrada.")
    return JSONResponse({"ok": True})
