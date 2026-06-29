"""Rutas de autenticación: login y logout."""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.contextos.usuarios.casos_uso import AutenticarUsuario

from ..dependencias import autenticar_usuario_uc
from ..plantillas import plantillas

router = APIRouter()

# Throttling anti-fuerza-bruta del login. En memoria y por proceso (suficiente
# como primera defensa; para multi-worker conviene un backend compartido).
_MAX_INTENTOS = 5
_VENTANA_S = 15 * 60
_intentos_fallidos: dict[str, list[float]] = defaultdict(list)


def _clave_throttle(request: Request, usuario: str) -> str:
    ip = request.client.host if request.client else "?"
    return f"{ip}|{(usuario or '').strip().lower()}"


def _demasiados_intentos(clave: str) -> bool:
    ahora = time.monotonic()
    recientes = [t for t in _intentos_fallidos[clave] if ahora - t < _VENTANA_S]
    _intentos_fallidos[clave] = recientes
    return len(recientes) >= _MAX_INTENTOS


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
    clave = _clave_throttle(request, usuario)
    if _demasiados_intentos(clave):
        return plantillas.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Demasiados intentos fallidos. Espera unos minutos e inténtalo de nuevo.",
                "usuario": usuario,
            },
            status_code=429,
        )
    cuenta = autenticar.ejecutar(usuario, contraseña)
    if cuenta is None:
        _intentos_fallidos[clave].append(time.monotonic())
        return plantillas.TemplateResponse(
            request,
            "login.html",
            {"error": "Usuario o contraseña incorrectos.", "usuario": usuario},
            status_code=401,
        )
    # Anti-fijación de sesión: descartar cualquier sesión previa antes de
    # asociarla a la cuenta autenticada.
    _intentos_fallidos.pop(clave, None)
    request.session.clear()
    request.session["usuario_id"] = cuenta.id
    request.session["usuario"] = cuenta.usuario
    request.session["rol"] = cuenta.rol.value
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
def cerrar_sesion(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
