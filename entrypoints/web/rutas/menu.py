"""Rutas del menú principal."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.nucleo.modelo import Proyecto, Rol
from app.nucleo.modelo.rol import acceso

from ..catalogo_modulos import CATALOGO
from ..dependencias import (
    COOKIE_PROYECTO,
    proyecto_activo,
    rol_activo,
)
from ..plantillas import plantillas

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def menu_principal(
    request: Request,
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
):
    # El superadmin es una cuenta administrativa sin módulos de negocio ni
    # proyectos: aterriza directamente en la gestión de usuarios.
    if rol is Rol.SUPERADMIN:
        return RedirectResponse(url="/modulos/gestion-usuarios", status_code=303)
    # Sin proyecto activo, la primera vista es Proyectos (el hub de tarjetas solo se
    # muestra una vez hay proyecto seleccionado). Cubre también el post-login (→ "/").
    if proyecto is None:
        return RedirectResponse(url="/proyectos", status_code=303)
    tarjetas = [
        {
            "modulo": tarjeta,
            "acceso": acceso(rol, tarjeta.id),
        }
        for tarjeta in CATALOGO
    ]
    return plantillas.TemplateResponse(
        request,
        "menu.html",
        {
            "tarjetas": tarjetas,
            "rol_activo": rol,
            "proyecto_activo": proyecto,
        },
    )


@router.post("/sesion/proyecto")
def cambiar_proyecto(proyecto_id: str = Form("")):
    respuesta = RedirectResponse(url="/", status_code=303)
    if proyecto_id:
        respuesta.set_cookie(COOKIE_PROYECTO, proyecto_id, httponly=True, samesite="lax")
    else:
        respuesta.delete_cookie(COOKIE_PROYECTO)
    return respuesta
