"""§2.9 — Rutas del Estudio de viabilidad económica.

Tres endpoints:
- GET  /modulos/viabilidad           → pantalla del módulo (Jinja2).
- POST /modulos/viabilidad/calcular  → preview en vivo (JSON), no persiste.
- POST /modulos/viabilidad/guardar   → calcula y persiste en el aggregate.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse

from app.contextos.proyectos.puertos import ProyectoRepositorio
from app.contextos.viabilidad import (
    CalcularViabilidad,
    EstudioViabilidad,
    ParametrosEconomicos,
    asociar_a_proyecto,
    estudio_a_dict,
    parametros_a_dict,
    parametros_desde_dict,
    parametros_desde_proyecto,
)
from app.nucleo.modelo import ModuloPuccetti, Proyecto, Rol
from app.nucleo.modelo.rol import PermisoModulo, puede_acceder

from ..catalogo_modulos import CATALOGO, TarjetaModulo
from ..dependencias import (
    exige_proyecto,
    proyecto_activo,
    repositorio_proyectos,
    rol_activo,
)
from ..plantillas import plantillas

router = APIRouter(prefix="/modulos/viabilidad")


# ── Helpers ────────────────────────────────────────────────────────────────
def _tarjeta() -> TarjetaModulo:
    for t in CATALOGO:
        if t.id == ModuloPuccetti.VIABILIDAD.value:
            return t
    raise HTTPException(status_code=500, detail="Tarjeta de viabilidad no encontrada en el catálogo.")


def _exige_permiso(rol: Rol, permiso: PermisoModulo) -> None:
    if not puede_acceder(rol, ModuloPuccetti.VIABILIDAD.value, permiso):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"El rol {rol.value} no puede {permiso.value} en estudio de viabilidad.",
        )


def _calcular_uc() -> CalcularViabilidad:
    return CalcularViabilidad()


def _datos_parcela(proyecto: Proyecto | None) -> dict[str, Any] | None:
    if proyecto is None:
        return None
    datos = proyecto.datos_por_modulo.get(ModuloPuccetti.LOCALIZACION.value)
    return datos or None


# ── Pantalla principal ────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
def pantalla(
    request: Request,
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    uc: CalcularViabilidad = Depends(_calcular_uc),
):
    _exige_permiso(rol, PermisoModulo.VER)
    tarjeta = _tarjeta()
    parametros = parametros_desde_proyecto(proyecto)
    datos_parcela = _datos_parcela(proyecto)
    estudio: EstudioViabilidad = uc.ejecutar(parametros, datos_parcela)
    return plantillas.TemplateResponse(
        request,
        "viabilidad.html",
        {
            "tarjeta": tarjeta,
            "rol_activo": rol,
            "proyecto_activo": proyecto,
            "puede_editar": puede_acceder(
                rol, ModuloPuccetti.VIABILIDAD.value, PermisoModulo.EDITAR
            ),
            "parametros": parametros_a_dict(parametros),
            "estudio": estudio_a_dict(estudio),
            "parcela": datos_parcela,
            "guardado": bool(
                proyecto is not None
                and proyecto.datos_por_modulo.get(ModuloPuccetti.VIABILIDAD.value)
            ),
        },
    )


# ── Cálculo en vivo (no persiste) ─────────────────────────────────────────
@router.post("/calcular")
def calcular(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    uc: CalcularViabilidad = Depends(_calcular_uc),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    parametros = parametros_desde_dict(payload)
    estudio = uc.ejecutar(parametros, _datos_parcela(proyecto))
    return JSONResponse(estudio_a_dict(estudio))


# ── Guardado ──────────────────────────────────────────────────────────────
@router.post("/guardar")
def guardar(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto = Depends(exige_proyecto),
    uc: CalcularViabilidad = Depends(_calcular_uc),
    repo: ProyectoRepositorio = Depends(repositorio_proyectos),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    parametros = parametros_desde_dict(payload)
    estudio = uc.ejecutar(parametros, _datos_parcela(proyecto))
    asociar_a_proyecto(parametros, proyecto)
    repo.guardar(proyecto)
    return JSONResponse({"ok": True, "estudio": estudio_a_dict(estudio)})
