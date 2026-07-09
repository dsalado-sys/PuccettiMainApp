"""Módulo de administración de usuarios (solo superadmin).

Alta, baja, cambio de rol, activar/desactivar y reset de contraseña. El acceso
lo gatea la matriz de permisos: solo `Rol.SUPERADMIN` tiene el módulo
`gestion_usuarios`, así que cualquier otro rol recibe 403.

Server-rendered: cada acción es un form POST mismo-origen (pasa el control CSRF)
que redirige de vuelta a la pantalla con un flash en el querystring.
"""
from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.contextos.usuarios.casos_uso import (
    CambiarActivo,
    CambiarContraseña,
    CambiarRol,
    CrearUsuario,
    EliminarUsuario,
    ListarUsuarios,
)
from app.contextos.usuarios.dominio import ROLES_ASIGNABLES, GestionUsuariosError, Usuario
from app.nucleo.modelo import ModuloPuccetti, Rol
from app.nucleo.modelo.rol import PermisoModulo, puede_acceder

from ..catalogo_modulos import CATALOGO, TarjetaModulo
from ..dependencias import (
    cambiar_activo_uc,
    cambiar_contraseña_uc,
    cambiar_rol_uc,
    crear_usuario_uc,
    eliminar_usuario_uc,
    listar_usuarios_uc,
    rol_activo,
    usuario_actual,
)
from ..plantillas import plantillas

router = APIRouter(prefix="/modulos/gestion-usuarios")

_MODULO = ModuloPuccetti.GESTION_USUARIOS.value


# ── Helpers ────────────────────────────────────────────────────────────────
def _tarjeta() -> TarjetaModulo:
    for t in CATALOGO:
        if t.id == _MODULO:
            return t
    raise HTTPException(status_code=500, detail="Tarjeta de gestión de usuarios no encontrada.")


def _exige_superadmin(rol: Rol) -> None:
    if not puede_acceder(rol, _MODULO, PermisoModulo.EDITAR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el superadministrador puede gestionar usuarios.",
        )


def _volver(mensaje: str = "", *, error: bool = False) -> RedirectResponse:
    destino = router.prefix
    if mensaje:
        clave = "error" if error else "ok"
        destino += "?" + urlencode({clave: mensaje})
    return RedirectResponse(url=destino, status_code=303)


def _rol_desde_form(valor: str) -> Rol:
    try:
        return Rol(valor)
    except ValueError:
        raise GestionUsuariosError("Rol desconocido.")


# ── Pantalla ────────────────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
def pantalla_usuarios(
    request: Request,
    rol: Rol = Depends(rol_activo),
    listar: ListarUsuarios = Depends(listar_usuarios_uc),
):
    _exige_superadmin(rol)
    usuarios = listar.ejecutar()
    return plantillas.TemplateResponse(
        request,
        "gestion_usuarios.html",
        {
            "tarjeta": _tarjeta(),
            "rol_activo": rol,
            "usuarios": usuarios,
            "roles_asignables": ROLES_ASIGNABLES,
            "ok": request.query_params.get("ok"),
            "error": request.query_params.get("error"),
        },
    )


# ── Acciones ──────────────────────────────────────────────────────────────
@router.post("/crear")
def crear(
    rol: Rol = Depends(rol_activo),
    usuario: str = Form(...),
    contraseña: str = Form(...),
    rol_nuevo: str = Form(...),
    crear_uc: CrearUsuario = Depends(crear_usuario_uc),
):
    _exige_superadmin(rol)
    try:
        creado = crear_uc.ejecutar(usuario, contraseña, _rol_desde_form(rol_nuevo))
    except GestionUsuariosError as exc:
        return _volver(str(exc), error=True)
    return _volver(f"Usuario «{creado.usuario}» creado.")


@router.post("/{usuario_id}/rol")
def cambiar_rol(
    usuario_id: str,
    rol: Rol = Depends(rol_activo),
    rol_nuevo: str = Form(...),
    cambiar_uc: CambiarRol = Depends(cambiar_rol_uc),
):
    _exige_superadmin(rol)
    try:
        cambiar_uc.ejecutar(usuario_id, _rol_desde_form(rol_nuevo))
    except GestionUsuariosError as exc:
        return _volver(str(exc), error=True)
    return _volver("Rol actualizado.")


@router.post("/{usuario_id}/activo")
def cambiar_activo(
    usuario_id: str,
    rol: Rol = Depends(rol_activo),
    activo: str = Form(...),
    cambiar_uc: CambiarActivo = Depends(cambiar_activo_uc),
):
    _exige_superadmin(rol)
    quiere_activo = activo.strip().lower() in ("1", "true", "on", "si", "sí")
    try:
        cambiar_uc.ejecutar(usuario_id, quiere_activo)
    except GestionUsuariosError as exc:
        return _volver(str(exc), error=True)
    return _volver("Usuario activado." if quiere_activo else "Usuario desactivado.")


@router.post("/{usuario_id}/contrasena")
def cambiar_contrasena(
    usuario_id: str,
    rol: Rol = Depends(rol_activo),
    contraseña: str = Form(...),
    cambiar_uc: CambiarContraseña = Depends(cambiar_contraseña_uc),
):
    _exige_superadmin(rol)
    try:
        cambiar_uc.ejecutar(usuario_id, contraseña)
    except GestionUsuariosError as exc:
        return _volver(str(exc), error=True)
    return _volver("Contraseña actualizada.")


@router.post("/{usuario_id}/eliminar")
def eliminar(
    usuario_id: str,
    rol: Rol = Depends(rol_activo),
    solicitante: Usuario | None = Depends(usuario_actual),
    eliminar_uc: EliminarUsuario = Depends(eliminar_usuario_uc),
):
    _exige_superadmin(rol)
    try:
        eliminar_uc.ejecutar(
            usuario_id, solicitante_id=solicitante.id if solicitante else None
        )
    except GestionUsuariosError as exc:
        return _volver(str(exc), error=True)
    return _volver("Usuario eliminado.")
