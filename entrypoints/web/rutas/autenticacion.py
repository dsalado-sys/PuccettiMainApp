"""Rutas de autenticación: login y logout."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.contextos.usuarios.casos_uso import AutenticarUsuario

from ..dependencias import autenticar_usuario_uc
from ..plantillas import plantillas

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def pantalla_login(request: Request):
    if request.session.get("usuario_id"):
        return RedirectResponse(url="/", status_code=303)
    return plantillas.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def iniciar_sesion(
    request: Request,
    usuario: str = Form(...),
    contraseña: str = Form(...),
    autenticar: AutenticarUsuario = Depends(autenticar_usuario_uc),
):
    cuenta = autenticar.ejecutar(usuario, contraseña)
    if cuenta is None:
        return plantillas.TemplateResponse(
            request,
            "login.html",
            {"error": "Usuario o contraseña incorrectos.", "usuario": usuario},
            status_code=401,
        )
    request.session["usuario_id"] = cuenta.id
    request.session["usuario"] = cuenta.usuario
    request.session["rol"] = cuenta.rol.value
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
def cerrar_sesion(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
