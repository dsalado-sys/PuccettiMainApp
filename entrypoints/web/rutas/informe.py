"""Módulo Informe — flujo de estados de los proyectos.

Materializa como UI el flujo de estados que `contextos/proyectos/flujo.py` ya
deriva (semáforo verde/amarillo/rojo por parcela / normativa / errores·avisos
por pestaña / viabilidad / informe). La página muestra un buscador simple y una
lista de cards grandes, una por proyecto, con el diagrama de flujo y dos botones
(«Revisar proyecto» / «Aprobar») que se cablearán más adelante.

Endpoints:
- GET  /modulos/informe               → pantalla (lista de cards)
- GET  /modulos/informe/datos         → proyectos + su flujo serializado (JSON)
- POST /modulos/informe/{id}/aprobar  → aprueba la viabilidad del proyecto (→ verde)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse

from app.contextos.proyectos.casos_uso import ListarProyectos
from app.contextos.proyectos.flujo import calcular_flujo, flujo_a_dict
from app.contextos.proyectos.puertos import ProyectoRepositorio
from app.contextos.viabilidad import aprobar_viabilidad
from app.nucleo.modelo import Proyecto, Rol
from app.nucleo.modelo.rol import PermisoModulo, puede_acceder

from ..dependencias import (
    listar_proyectos_uc,
    proyecto_activo,
    repositorio_proyectos,
    rol_activo,
)
from ..plantillas import plantillas

router = APIRouter(prefix="/modulos/informe")

_MODULO = "informe"


def _exige_ver(rol: Rol) -> None:
    if not puede_acceder(rol, _MODULO, PermisoModulo.VER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"El rol {rol.value} no tiene acceso al Informe.",
        )


def _exige_editar(rol: Rol) -> None:
    if not puede_acceder(rol, _MODULO, PermisoModulo.EDITAR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"El rol {rol.value} no puede aprobar en el Informe.",
        )


# ─── Pantalla ───────────────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
def pantalla(
    request: Request,
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
):
    _exige_ver(rol)
    return plantillas.TemplateResponse(
        request,
        "informe.html",
        {
            "rol_activo": rol,
            "proyecto_activo": proyecto,
            "puede_editar": puede_acceder(rol, _MODULO, PermisoModulo.EDITAR),
        },
    )


# ─── Datos (proyectos + flujo) ──────────────────────────────────────────────
@router.get("/datos")
def datos(
    rol: Rol = Depends(rol_activo),
    uc: ListarProyectos = Depends(listar_proyectos_uc),
):
    _exige_ver(rol)
    proyectos = [
        {
            "id": p.id,
            "nombre": p.nombre,
            "referencia_catastral": p.referencia_catastral,
            "direccion": p.direccion,
            "flujo": flujo_a_dict(calcular_flujo(p)),
        }
        for p in uc.ejecutar()
    ]
    return JSONResponse({"proyectos": proyectos})


# ─── Aprobar viabilidad (desde la card del Informe) ─────────────────────────
@router.post("/{proyecto_id}/aprobar")
def aprobar(
    proyecto_id: str,
    rol: Rol = Depends(rol_activo),
    repo: ProyectoRepositorio = Depends(repositorio_proyectos),
):
    """Aprueba el estudio de viabilidad del proyecto (→ nodo Viabilidad en verde).

    Actúa sobre el proyecto elegido en la card (por id), no sobre el activo.
    """
    _exige_editar(rol)
    proyecto = repo.obtener(proyecto_id)
    if proyecto is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado.")
    if not aprobar_viabilidad(proyecto):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El proyecto no tiene un estudio de viabilidad que aprobar.",
        )
    repo.guardar(proyecto)
    return JSONResponse({"ok": True, "flujo": flujo_a_dict(calcular_flujo(proyecto))})
