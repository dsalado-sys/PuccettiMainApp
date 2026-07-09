"""Módulo Informe — flujo de estados de los proyectos.

Materializa como UI el flujo de estados que `contextos/proyectos/flujo.py` ya
deriva (semáforo verde/amarillo/rojo por parcela / normativa / errores·avisos
por pestaña / viabilidad / informe). La página muestra un buscador simple y una
lista de cards grandes, una por proyecto, con el diagrama de flujo y dos botones
(«Revisar proyecto» / «Aprobar») que se cablearán más adelante.

Endpoints:
- GET  /modulos/informe                  → pantalla (lista de cards)
- GET  /modulos/informe/datos            → proyectos + su flujo serializado (JSON)
- GET  /modulos/informe/{id}/documento   → documento del informe (§2.8), imprimible a PDF
- POST /modulos/informe/{id}/aprobar     → aprueba la viabilidad del proyecto (→ verde)
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse

from app.contextos.informe.casos_uso import (
    EnsamblarInforme,
    aprobar_informe,
    informe_a_dict,
)
from app.contextos.proyectos.casos_uso import ListarProyectos
from app.contextos.proyectos.flujo import calcular_flujo, flujo_a_dict
from app.contextos.proyectos.puertos import ProyectoRepositorio
from app.contextos.render_calculos.casos_uso import (
    CalcularLayout,
    construir_parcela_metrica,
    contenedor_escenarios_proyecto,
    parametros_desde_proyecto,
)
from app.nucleo.modelo import ModuloPuccetti, Proyecto, Rol
from app.nucleo.modelo.rol import PermisoModulo, puede_acceder

from ..dependencias import (
    catalogo_apartamentos_adapter,
    catalogo_hotelero_adapter,
    catalogo_superficies_adapter,
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


# ─── Aprobar el informe de un ESCENARIO (desde la card del Informe) ──────────
@router.post("/{proyecto_id}/aprobar")
def aprobar(
    proyecto_id: str,
    modo: str = Query(...),
    escenario: str = Query(...),
    rol: Rol = Depends(rol_activo),
    repo: ProyectoRepositorio = Depends(repositorio_proyectos),
):
    """Aprueba el informe del escenario elegido (→ su nodo Informe en verde).

    Actúa sobre el proyecto (por id) y el escenario (modo + id) seleccionado en la
    card. La aprobación de la viabilidad vive en su propio módulo (no aquí).
    """
    _exige_editar(rol)
    proyecto = repo.obtener(proyecto_id)
    if proyecto is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado.")
    if not aprobar_informe(proyecto, modo, escenario):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El escenario indicado no existe en el proyecto.",
        )
    repo.guardar(proyecto)
    return JSONResponse({"ok": True, "flujo": flujo_a_dict(calcular_flujo(proyecto))})


# ─── Documento del informe (§2.8) ───────────────────────────────────────────
# Modos de render que producen envolvente (planimetría + tablas). `inmueble` no
# genera envolvente (reparte estancias de una unidad) → queda fuera de esta pasada.
_MODOS_RENDER = ("obra-nueva", "rehabilitacion")


def _recalcular_escenario_activo(proyecto, modo_pedido, escenario_pedido, catalogos):
    """Recalcula la propuesta de un escenario (réplica del patrón de `export_csv`).

    Si viene ``escenario_pedido`` se recalcula ESA pestaña (en el modo que la
    contiene); si no, el escenario activo del modo. Devuelve ``(resultado_layout,
    escenario_meta)`` o ``(None, None)`` si no hay parcela o ningún escenario.
    Degrada a ``(None, None)`` ante cualquier fallo del recálculo (el informe
    muestra el bloque como PENDIENTE en vez de romper).
    """
    try:
        parcela = construir_parcela_metrica(proyecto)
    except Exception:
        parcela = None
    if parcela is None:
        return None, None

    catalogo_viv, catalogo_apt, catalogo_hot = catalogos
    modos = [modo_pedido] if modo_pedido in _MODOS_RENDER else list(_MODOS_RENDER)
    for modo in modos:
        heredar = modo == "obra-nueva"
        cont = contenedor_escenarios_proyecto(proyecto, modo, heredar_legado=heredar)
        if not cont:
            continue
        # Si se pidió un escenario concreto, solo sirve el modo que lo contiene.
        esc_id = None
        if escenario_pedido:
            if not any(e.get("id") == escenario_pedido for e in cont["escenarios"]):
                continue
            esc_id = escenario_pedido
        params = parametros_desde_proyecto(
            proyecto, modo, heredar_legado=heredar, escenario_id=esc_id,
        )
        try:
            resultado = CalcularLayout(
                catalogo_vivienda=catalogo_viv,
                catalogo_apartamentos=catalogo_apt,
                catalogo_hotelero=catalogo_hot,
            ).ejecutar(parcela, params)
        except Exception:
            continue
        objetivo_id = esc_id or cont.get("activo")
        activo = next(
            (e for e in cont["escenarios"] if e.get("id") == objetivo_id),
            cont["escenarios"][0],
        )
        return resultado, {"modo": modo, "nombre": activo.get("nombre") or "Escenario"}
    return None, None


@router.get("/{proyecto_id}/documento", response_class=HTMLResponse)
def documento(
    proyecto_id: str,
    request: Request,
    modo: str | None = Query(None),
    escenario: str | None = Query(None),
    rol: Rol = Depends(rol_activo),
    repo: ProyectoRepositorio = Depends(repositorio_proyectos),
    catalogo_viv=Depends(catalogo_superficies_adapter),
    catalogo_apt=Depends(catalogo_apartamentos_adapter),
    catalogo_hot=Depends(catalogo_hotelero_adapter),
):
    """Documento del informe de un proyecto (§2.8), imprimible a PDF (print-CSS).

    Ensambla las secciones desde los datos ya trazados del aggregate: ficha y
    normativa se leen directas; planimetría/superficies/alertas se recalculan del
    escenario elegido (`modo`+`escenario`) o del activo (como `export_csv`); la
    sección financiera queda reservada.
    """
    _exige_ver(rol)
    proyecto = repo.obtener(proyecto_id)
    if proyecto is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado.")

    datos = proyecto.datos_por_modulo or {}
    localizacion = datos.get(ModuloPuccetti.LOCALIZACION.value) or {}
    rc_corner = datos.get(ModuloPuccetti.RENDER_CALCULOS.value)
    normativa = rc_corner.get("normativa_aplicada") if isinstance(rc_corner, dict) else None
    viabilidad = datos.get(ModuloPuccetti.VIABILIDAD.value) or {}

    resultado_layout, escenario_meta = _recalcular_escenario_activo(
        proyecto, modo, escenario, (catalogo_viv, catalogo_apt, catalogo_hot),
    )

    proyecto_meta = {
        "id": proyecto.id,
        "nombre": proyecto.nombre,
        "referencia_catastral": proyecto.referencia_catastral,
        "direccion": proyecto.direccion,
        "generado_por": request.session.get("usuario"),
        "generado_el": datetime.now().strftime("%d/%m/%Y"),
    }
    informe = EnsamblarInforme().ejecutar(
        proyecto_meta=proyecto_meta,
        localizacion=localizacion,
        normativa=normativa,
        resultado_layout=resultado_layout,
        escenario_meta=escenario_meta,
        viabilidad=viabilidad,
    )
    return plantillas.TemplateResponse(
        request,
        "informe_documento.html",
        {"rol_activo": rol, "informe": informe_a_dict(informe)},
    )
