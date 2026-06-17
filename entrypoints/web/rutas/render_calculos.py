"""§2.4–2.7 — Rutas del módulo Render y cálculos.

Endpoints:
- GET  /modulos/render-calculos                   → pantalla del módulo
- POST /modulos/render-calculos/preview           → envolvente rápida (req. 8)
- POST /modulos/render-calculos/calcular          → cálculo completo (req. 8+12)
- POST /modulos/render-calculos/guardar           → persiste params en aggregate
- GET  /modulos/render-calculos/normativa         → lista municipios con PGOU guardado
- GET  /modulos/render-calculos/normativa/{p}/{m} → consulta PGOU de un municipio
- POST /modulos/render-calculos/normativa/{p}/{m} → crea/actualiza PGOU
- GET  /modulos/render-calculos/export.csv        → tabla de superficies (req. 16)
"""
from __future__ import annotations

import csv
import io
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from app.contextos.proyectos.puertos import ProyectoRepositorio
from app.contextos.render_calculos.casos_uso import (
    CalcularEnvolvente,
    CalcularLayout,
    CalcularTipologiasDormitorios,
    GuardarRender,
    ValidarCumplimiento,
    construir_parcela_metrica,
    parametros_desde_proyecto,
)
from app.contextos.render_calculos.dominio import UsoEdificio
from app.contextos.render_calculos.parametros import (
    ParametrosUrbanisticos,
    parametros_a_dict,
    parametros_desde_dict,
)
from app.contextos.render_calculos.puertos import NormativaMunicipalRepositorio
from app.nucleo.modelo import ModuloPuccetti, Proyecto, Rol
from app.nucleo.modelo.rol import PermisoModulo, puede_acceder
from app.plataforma.persistencia.normativa_municipal_sqlalchemy import (
    NormativaMunicipalSQLAlchemy,
)

from ..catalogo_modulos import CATALOGO, TarjetaModulo
from ..dependencias import (
    catalogo_apartamentos_adapter,
    catalogo_hotel_apartamento_adapter,
    catalogo_hotelero_adapter,
    catalogo_superficies_adapter,
    proyecto_activo,
    repositorio_proyectos,
    rol_activo,
    sesion_bbdd,
)
from ..plantillas import plantillas


router = APIRouter(prefix="/modulos/render-calculos")


# ─── Helpers ────────────────────────────────────────────────────────────────
def _tarjeta() -> TarjetaModulo:
    for t in CATALOGO:
        if t.id == ModuloPuccetti.RENDER_CALCULOS.value:
            return t
    raise HTTPException(status_code=500, detail="Tarjeta render_calculos no encontrada en el catálogo.")


def _exige_permiso(rol: Rol, permiso: PermisoModulo) -> None:
    if not puede_acceder(rol, ModuloPuccetti.RENDER_CALCULOS.value, permiso):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"El rol {rol.value} no puede {permiso.value} en Render y cálculos.",
        )


def _normativa_repo(session: Session = Depends(sesion_bbdd)) -> NormativaMunicipalRepositorio:
    return NormativaMunicipalSQLAlchemy(session)


def _normativa_de_referencia(
    payload: dict[str, Any],
    parcela,
    repo_norm: NormativaMunicipalRepositorio,
):
    """Devuelve la `ParametrosUrbanisticos` contra la que se evaluarán los avisos.

    Prioridad:
      1. `payload["normativa_referencia"]["urbanisticos"]` — la normativa que el
         usuario eligió desde el módulo Normativa municipal y aplicó al proyecto.
      2. Normativa del municipio + provincia de la parcela (si está en BBDD).
      3. None — no se generarán avisos comparados.
    """
    ref = payload.get("normativa_referencia") or {}
    urb = ref.get("urbanisticos") if isinstance(ref, dict) else None
    if urb:
        return parametros_desde_dict({"urbanisticos": urb}).urbanisticos
    if parcela.municipio and parcela.provincia:
        return repo_norm.obtener(parcela.municipio, parcela.provincia)
    return None


def _estado_pantalla(proyecto: Proyecto | None) -> str:
    if proyecto is None:
        return "sin_proyecto"
    datos_loc = proyecto.datos_por_modulo.get(ModuloPuccetti.LOCALIZACION.value)
    if not datos_loc:
        return "sin_parcela"
    return "ok"


# ─── Pantalla principal ─────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
def pantalla(
    request: Request,
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    repo_norm: NormativaMunicipalRepositorio = Depends(_normativa_repo),
):
    _exige_permiso(rol, PermisoModulo.VER)
    tarjeta = _tarjeta()
    params = parametros_desde_proyecto(proyecto)
    estado = _estado_pantalla(proyecto)

    municipios = repo_norm.listar()
    # Si la parcela tiene municipio conocido, intentamos cargar su PGOU como
    # base de los parámetros urbanísticos.
    pgou_municipio: dict[str, Any] | None = None
    if proyecto is not None:
        datos_loc = proyecto.datos_por_modulo.get(ModuloPuccetti.LOCALIZACION.value) or {}
        mun, prov = datos_loc.get("municipio"), datos_loc.get("provincia")
        if mun and prov:
            normativa = repo_norm.obtener(mun, prov)
            if normativa is not None:
                pgou_municipio = {"municipio": mun, "provincia": prov}
                # solo aplicamos como defaults si el proyecto aún no tiene params guardados
                datos_render = proyecto.datos_por_modulo.get(ModuloPuccetti.RENDER_CALCULOS.value) or {}
                if not datos_render.get("parametros"):
                    params.urbanisticos = normativa

    return plantillas.TemplateResponse(
        request,
        "render_calculos.html",
        {
            "tarjeta": tarjeta,
            "rol_activo": rol,
            "proyecto_activo": proyecto,
            "puede_editar": puede_acceder(
                rol, ModuloPuccetti.RENDER_CALCULOS.value, PermisoModulo.EDITAR
            ),
            "estado": estado,
            "parametros": parametros_a_dict(params),
            "municipios_disponibles": municipios,
            "pgou_municipio_activo": pgou_municipio,
            "usos_edificio": [
                {"value": "vivienda", "label": "Vivienda", "habilitado": True},
                {"value": "apartamentos_turisticos", "label": "Apartamentos turísticos", "habilitado": True},
                {"value": "hotel_apartamento", "label": "Hotel-apartamento", "habilitado": True},
                {"value": "hotelero", "label": "Hotelero", "habilitado": True},
            ],
        },
    )


# ─── Preview (envolvente rápida) ────────────────────────────────────────────
@router.post("/preview")
def preview(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    repo_norm: NormativaMunicipalRepositorio = Depends(_normativa_repo),
):
    _exige_permiso(rol, PermisoModulo.VER)
    if proyecto is None:
        raise HTTPException(409, "No hay proyecto activo.")
    parcela = construir_parcela_metrica(proyecto)
    if parcela is None:
        raise HTTPException(409, "El proyecto no tiene parcela asociada. Localízala en §2.1.")

    params = parametros_desde_dict(payload)
    resultado = CalcularEnvolvente().ejecutar(parcela, params)

    normativa = _normativa_de_referencia(payload, parcela, repo_norm)
    alertas_extra = ValidarCumplimiento().ejecutar(parcela, params, normativa)
    resultado["alertas"] = list(resultado.get("alertas", [])) + [
        {"nivel": a.nivel, "regla": a.regla, "mensaje": a.mensaje, "elemento": a.elemento}
        for a in alertas_extra
    ]
    return JSONResponse(resultado)


# ─── Cálculo completo (capacidad numérica iter. 3) ──────────────────────────
@router.post("/calcular")
def calcular(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    repo_norm: NormativaMunicipalRepositorio = Depends(_normativa_repo),
    catalogo_viv=Depends(catalogo_superficies_adapter),
    catalogo_apt=Depends(catalogo_apartamentos_adapter),
    catalogo_hap=Depends(catalogo_hotel_apartamento_adapter),
    catalogo_hot=Depends(catalogo_hotelero_adapter),
):
    _exige_permiso(rol, PermisoModulo.VER)
    if proyecto is None:
        raise HTTPException(409, "No hay proyecto activo.")
    parcela = construir_parcela_metrica(proyecto)
    if parcela is None:
        raise HTTPException(409, "El proyecto no tiene parcela asociada. Localízala en §2.1.")

    params = parametros_desde_dict(payload)
    # §2.5 — selección temporal de combinación de dormitorios (apartamentos). El
    # slug no se persiste: solo recalcula esta respuesta con esa combinación.
    combo_override = payload.get("combo_dormitorios") or None
    if combo_override is not None:
        combo_override = str(combo_override).strip() or None
    caso_uso = CalcularLayout(
        catalogo_vivienda=catalogo_viv,
        catalogo_apartamentos=catalogo_apt,
        catalogo_hotel_apartamento=catalogo_hap,
        catalogo_hotelero=catalogo_hot,
    )
    resultado = caso_uso.ejecutar(parcela, params, combo_override=combo_override)

    normativa = _normativa_de_referencia(payload, parcela, repo_norm)
    alertas_extra = ValidarCumplimiento().ejecutar(parcela, params, normativa)
    resultado["alertas"] = list(resultado.get("alertas", [])) + [
        {"nivel": a.nivel, "regla": a.regla, "mensaje": a.mensaje, "elemento": a.elemento}
        for a in alertas_extra
    ]
    return JSONResponse(resultado)


# ─── Combinaciones por nº de dormitorios (§2.5 — apartamentos turísticos) ────
@router.post("/tipologias-dormitorios")
def tipologias_dormitorios(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    catalogo_viv=Depends(catalogo_superficies_adapter),
    catalogo_apt=Depends(catalogo_apartamentos_adapter),
    catalogo_hap=Depends(catalogo_hotel_apartamento_adapter),
    catalogo_hot=Depends(catalogo_hotelero_adapter),
):
    """Para un nº de dormitorios, devuelve las combinaciones viables y cuántas
    unidades cabe de cada una (ordenadas, podadas las no viables). El cliente
    muestra el modal de selección; la elección se reenvía a `/calcular` como
    `combo_dormitorios` (no se persiste hasta `/guardar`)."""
    _exige_permiso(rol, PermisoModulo.VER)
    if proyecto is None:
        raise HTTPException(409, "No hay proyecto activo.")
    parcela = construir_parcela_metrica(proyecto)
    if parcela is None:
        raise HTTPException(409, "El proyecto no tiene parcela asociada. Localízala en §2.1.")

    params = parametros_desde_dict(payload)
    try:
        n_dorms = int(payload.get("n_dormitorios", 1))
    except (TypeError, ValueError):
        n_dorms = 1

    resultado = CalcularTipologiasDormitorios(
        catalogo_vivienda=catalogo_viv,
        catalogo_apartamentos=catalogo_apt,
        catalogo_hotel_apartamento=catalogo_hap,
        catalogo_hotelero=catalogo_hot,
    ).ejecutar(parcela, params, n_dorms)
    return JSONResponse(resultado)


# ─── Guardar parámetros en el aggregate ─────────────────────────────────────
@router.post("/guardar")
def guardar(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    repo_proy: ProyectoRepositorio = Depends(repositorio_proyectos),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    if proyecto is None:
        raise HTTPException(409, "No hay proyecto activo.")

    params_payload = payload.get("parametros") or payload
    resumen = payload.get("resumen") or {}
    params = parametros_desde_dict(params_payload)

    actualizado = GuardarRender(repo_proyectos=repo_proy).ejecutar(proyecto, params, resumen)
    return JSONResponse({"ok": True, "actualizado_en": actualizado.actualizado_en.isoformat()})


# ─── Normativa municipal: listado + lectura + escritura ─────────────────────
@router.get("/normativa")
def listar_normativa(
    rol: Rol = Depends(rol_activo),
    repo_norm: NormativaMunicipalRepositorio = Depends(_normativa_repo),
):
    _exige_permiso(rol, PermisoModulo.VER)
    return JSONResponse({"municipios": repo_norm.listar()})


@router.get("/normativa/{provincia}/{municipio}")
def obtener_normativa(
    provincia: str,
    municipio: str,
    rol: Rol = Depends(rol_activo),
    repo_norm: NormativaMunicipalRepositorio = Depends(_normativa_repo),
):
    _exige_permiso(rol, PermisoModulo.VER)
    p = repo_norm.obtener(municipio, provincia)
    if p is None:
        raise HTTPException(404, f"Sin normativa registrada para {municipio} ({provincia}).")
    base = parametros_a_dict(_envolver_params(p))
    return JSONResponse({"municipio": municipio, "provincia": provincia, "urbanisticos": base["urbanisticos"]})


@router.post("/normativa/{provincia}/{municipio}")
def guardar_normativa(
    provincia: str,
    municipio: str,
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    repo_norm: NormativaMunicipalRepositorio = Depends(_normativa_repo),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    bloque_urb = payload.get("urbanisticos") or payload
    parsed = parametros_desde_dict({"urbanisticos": bloque_urb})
    fuente = str(payload.get("fuente_pgou", ""))
    repo_norm.guardar(municipio, provincia, parsed.urbanisticos, fuente)
    return JSONResponse({"ok": True})


# Los endpoints de carpetas + normativas archivadas viven ahora en el módulo
# Normativa municipal (/modulos/normativa-municipal/...). Render solo lo consulta
# desde el frontend; aquí no expone esas rutas.


# ─── Export CSV ─────────────────────────────────────────────────────────────
@router.post("/export.csv")
def export_csv(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    catalogo_viv=Depends(catalogo_superficies_adapter),
    catalogo_apt=Depends(catalogo_apartamentos_adapter),
    catalogo_hap=Depends(catalogo_hotel_apartamento_adapter),
    catalogo_hot=Depends(catalogo_hotelero_adapter),
):
    _exige_permiso(rol, PermisoModulo.VER)
    if proyecto is None:
        raise HTTPException(409, "No hay proyecto activo.")
    parcela = construir_parcela_metrica(proyecto)
    if parcela is None:
        raise HTTPException(409, "El proyecto no tiene parcela asociada.")
    params = parametros_desde_dict(payload.get("parametros") or payload)
    caso_uso = CalcularLayout(
        catalogo_vivienda=catalogo_viv,
        catalogo_apartamentos=catalogo_apt,
        catalogo_hotel_apartamento=catalogo_hap,
        catalogo_hotelero=catalogo_hot,
    )
    resultado = caso_uso.ejecutar(parcela, params)

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["# Tabla de superficies por planta — Render y cálculos §2.7"])
    writer.writerow(["planta", "tipo", "viviendas", "construida_m2", "util_viviendas_m2",
                     "muros_m2", "circulacion_m2", "nucleo_m2"])
    for r in resultado.get("tabla_planta", []):
        writer.writerow([r["planta"], r.get("tipo", "regular"), r["viviendas"], r["construida_m2"],
                         r["util_viviendas_m2"], r.get("muros_m2", 0.0),
                         r["circulacion_m2"], r.get("nucleo_m2", 0.0)])
    writer.writerow([])
    writer.writerow(["# Tabla por unidad (iter. 3 — sintética desde cálculo)"])
    writer.writerow(["planta", "vivienda", "dorms", "tipo", "util_m2_objetivo",
                     "util_total_m2", "computable_turismo_m2", "circulacion_acceso_m2", "adaptada"])
    for r in resultado.get("tabla_unidad", []):
        writer.writerow([r["planta"], r["vivienda"], r["dorms"], r.get("tipo", "vivienda"),
                         r["util_m2_objetivo"], r.get("util_por_unidad_m2", 0.0),
                         r.get("computable_turismo_por_unidad_m2", 0.0),
                         r.get("circulacion_interior_por_unidad_m2", 0.0), r["adaptada"]])
    return Response(
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=puccetti_superficies.csv"},
    )


# ─── Helper privado ─────────────────────────────────────────────────────────
def _envolver_params(urb: ParametrosUrbanisticos):
    """Envuelve un ParametrosUrbanisticos en un ParametrosRender vacío para reutilizar `parametros_a_dict`."""
    from app.contextos.render_calculos.parametros import ParametrosRender
    bundle = ParametrosRender()
    bundle.urbanisticos = urb
    return bundle
