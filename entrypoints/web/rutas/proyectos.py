"""Rutas de gestión de proyectos (§2.11)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.contextos.proyectos.casos_uso import (
    CrearProyecto,
    EliminarProyecto,
    ListarProyectos,
    ObtenerProyecto,
)
from app.nucleo.modelo import Proyecto, Rol
from app.nucleo.modelo.rol import PermisoModulo, puede_acceder

from ..dependencias import (
    COOKIE_PROYECTO,
    crear_proyecto_uc,
    eliminar_proyecto_uc,
    listar_proyectos_uc,
    obtener_proyecto_uc,
    proyecto_activo,
    rol_activo,
)
from ..plantillas import plantillas

router = APIRouter(prefix="/proyectos")


@router.get("", response_class=HTMLResponse)
def listar(
    request: Request,
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    uc: ListarProyectos = Depends(listar_proyectos_uc),
):
    return plantillas.TemplateResponse(
        request,
        "proyectos.html",
        {
            "proyectos": uc.ejecutar(),
            "proyecto_activo": proyecto,
            "rol_activo": rol,
            "puede_editar": puede_acceder(rol, "proyectos", PermisoModulo.EDITAR),
        },
    )


@router.post("")
def crear(
    nombre: str = Form(...),
    referencia_catastral: str = Form(""),
    direccion: str = Form(""),
    rol: Rol = Depends(rol_activo),
    uc: CrearProyecto = Depends(crear_proyecto_uc),
):
    if not puede_acceder(rol, "proyectos", PermisoModulo.EDITAR):
        return RedirectResponse(url="/proyectos", status_code=303)
    proyecto = uc.ejecutar(
        nombre=nombre,
        referencia_catastral=referencia_catastral or None,
        direccion=direccion or None,
        creado_por=rol.value,
    )
    respuesta = RedirectResponse(url="/", status_code=303)
    respuesta.set_cookie(COOKIE_PROYECTO, proyecto.id, httponly=True, samesite="lax")
    return respuesta


@router.post("/{proyecto_id}/eliminar")
def eliminar(
    proyecto_id: str,
    rol: Rol = Depends(rol_activo),
    uc: EliminarProyecto = Depends(eliminar_proyecto_uc),
):
    if puede_acceder(rol, "proyectos", PermisoModulo.EDITAR):
        uc.ejecutar(proyecto_id)
    respuesta = RedirectResponse(url="/proyectos", status_code=303)
    respuesta.delete_cookie(COOKIE_PROYECTO)
    return respuesta
