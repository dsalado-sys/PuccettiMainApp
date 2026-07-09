"""Stubs de cada módulo del catálogo.

Cada ruta valida el permiso del rol activo y renderiza una página
"en construcción" con la sección §x.y del PDF.
Cuando integremos cada módulo, sustituiremos el body por su propio router.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from app.nucleo.modelo import Proyecto, Rol
from app.nucleo.modelo.rol import PermisoModulo, puede_acceder

from ..catalogo_modulos import CATALOGO, TarjetaModulo
from ..plantillas import plantillas

router = APIRouter(prefix="/modulos")


def _tarjeta(modulo_id: str) -> TarjetaModulo:
    for tarjeta in CATALOGO:
        if tarjeta.id == modulo_id:
            return tarjeta
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Módulo desconocido.")


def _pantalla_modulo(
    request: Request,
    modulo_id: str,
    rol: Rol,
    proyecto: Proyecto | None,
) -> HTMLResponse:
    tarjeta = _tarjeta(modulo_id)
    if not puede_acceder(rol, tarjeta.id, PermisoModulo.VER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"El rol {rol.value} no tiene acceso a {tarjeta.titulo}.",
        )
    return plantillas.TemplateResponse(
        request,
        "modulo_pendiente.html",
        {
            "tarjeta": tarjeta,
            "rol_activo": rol,
            "proyecto_activo": proyecto,
        },
    )


# NOTA: `modelos_planos` no expone ruta. Su tarjeta está desactivada en
# `catalogo_modulos.py` (módulo aún no integrado), por lo que `_tarjeta` no lo
# encontraría y la ruta devolvía 404 para todos los roles. Cuando se integre, se
# reactiva su tarjeta y se añade aquí su ruta a la vez.
# El enum/MODULOS/MATRIZ_PERMISOS conservan la entrada como roadmap.
#
# `informe` ya NO es un stub: tiene router propio (`rutas/informe.py`) con la
# pantalla del flujo de estados. `_pantalla_modulo` se conserva como andamiaje
# para el próximo módulo pendiente que se integre.
