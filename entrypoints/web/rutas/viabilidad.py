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
    CalcularViabilidadDCF,
    EstudioViabilidad,
    Intervencion,
    ParametrosEconomicos,
    TipologiaPR,
    UmbralesPR,
    analizar_sensibilidad,
    aprobar_viabilidad,
    asociar_a_proyecto,
    asociar_dcf_a_proyecto,
    benchmarks_a_dict,
    benchmarks_desde_dict,
    benchmarks_desde_proyecto,
    estudio_a_dict,
    estudio_dcf_a_dict,
    evaluar_umbrales,
    financiacion_a_dict,
    financiacion_desde_dict,
    financiacion_desde_proyecto,
    parametros_a_dict,
    parametros_desde_dict,
    parametros_desde_proyecto,
    precio_maximo_compra,
    semaforo_global,
    supuestos_dcf_a_dict,
    supuestos_dcf_desde_dict,
    supuestos_dcf_desde_proyecto,
    umbrales_a_dict,
    umbrales_desde_dict,
)
from app.contextos.viabilidad.puertos import UmbralesPRPort
from app.nucleo.modelo import ModuloPuccetti, Proyecto, Rol
from app.nucleo.modelo.rol import PermisoModulo, puede_acceder

from ..catalogo_modulos import CATALOGO, TarjetaModulo
from ..dependencias import (
    calcular_viabilidad_dcf_uc,
    exige_proyecto,
    proyecto_activo,
    repositorio_proyectos,
    rol_activo,
    umbrales_pr_adapter,
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


def _tipologia_pr(parametros: ParametrosEconomicos, payload: dict[str, Any] | None = None) -> TipologiaPR:
    """Tipología para la TIR mínima del semáforo. Si el payload la trae, manda;
    si no, se deriva: rehabilitación → rehab intensiva; en otro caso → BTR residencial.
    (La distinción residencial/hotelero fina la aporta el uso del módulo Render; aquí
    se usa un valor por defecto razonable que el usuario puede cambiar en la UI.)"""
    if payload:
        try:
            return TipologiaPR(str(payload.get("tipologia")))
        except ValueError:
            pass
    if parametros.intervencion == Intervencion.REHABILITACION:
        return TipologiaPR.REHAB_INTENSIVA
    return TipologiaPR.BTR_RESIDENCIAL


def _semaforo_base(estudio_dcf, umbrales: UmbralesPR, tipologia: TipologiaPR) -> dict[str, Any]:
    """Semáforo sobre el escenario BASE. Yield/CAPEX-hab quedan como 'sin dato' en
    esta iteración (el modelo all-equity aún no los produce): el semáforo evalúa TIR y
    payback, que son las métricas disponibles."""
    base = next((e for e in estudio_dcf.escenarios if e.escenario.value == "base"), None)
    tir = base.tir if base else None
    payback = base.payback_anios if base else None
    estados = evaluar_umbrales(umbrales, tipologia, tir=tir, payback_anios=payback)
    return {
        "por_metrica": {k: v.value for k, v in estados.items()},
        "global": semaforo_global(estados).value,
        "tipologia": tipologia.value,
    }


# ── Pantalla principal ────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
def pantalla(
    request: Request,
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    uc: CalcularViabilidad = Depends(_calcular_uc),
    uc_dcf: CalcularViabilidadDCF = Depends(calcular_viabilidad_dcf_uc),
    umbrales_repo: UmbralesPRPort = Depends(umbrales_pr_adapter),
):
    _exige_permiso(rol, PermisoModulo.VER)
    tarjeta = _tarjeta()
    parametros = parametros_desde_proyecto(proyecto)
    datos_parcela = _datos_parcela(proyecto)
    estudio: EstudioViabilidad = uc.ejecutar(parametros, datos_parcela)

    # Estado inicial del DCF (a partir de lo guardado, o defaults neutros).
    supuestos = supuestos_dcf_desde_proyecto(proyecto)
    financiacion = financiacion_desde_proyecto(proyecto)
    benchmarks = benchmarks_desde_proyecto(proyecto)
    umbrales = umbrales_repo.obtener()
    tipologia = _tipologia_pr(parametros)
    estudio_dcf = uc_dcf.ejecutar(supuestos, financiacion, parametros, datos_parcela)

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
            # DCF (Fases 1-5)
            "supuestos": supuestos_dcf_a_dict(supuestos),
            "financiacion": financiacion_a_dict(financiacion),
            "benchmarks": benchmarks_a_dict(benchmarks),
            "umbrales": umbrales_a_dict(umbrales),
            "estudio_dcf": estudio_dcf_a_dict(estudio_dcf),
            "semaforo": _semaforo_base(estudio_dcf, umbrales, tipologia),
            "tipologias_pr": [t.value for t in TipologiaPR],
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


# ── DCF (Fases 1-5): motor multi-escenario ─────────────────────────────────
def _supuestos_financiacion(payload: dict[str, Any]):
    dcf = payload.get("dcf") or {}
    return supuestos_dcf_desde_dict(dcf.get("supuestos")), financiacion_desde_dict(dcf.get("financiacion"))


@router.post("/calcular-dcf")
def calcular_dcf(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    uc_dcf: CalcularViabilidadDCF = Depends(calcular_viabilidad_dcf_uc),
    umbrales_repo: UmbralesPRPort = Depends(umbrales_pr_adapter),
):
    """Preview en vivo del DCF (JSON, no persiste): estudio de los 3 escenarios +
    semáforo del escenario base contra los umbrales PR."""
    _exige_permiso(rol, PermisoModulo.EDITAR)
    parametros = parametros_desde_dict(payload)
    supuestos, financiacion = _supuestos_financiacion(payload)
    estudio = uc_dcf.ejecutar(supuestos, financiacion, parametros, _datos_parcela(proyecto))
    tipologia = _tipologia_pr(parametros, payload)
    umbrales = umbrales_repo.obtener()
    return JSONResponse(
        {
            "estudio_dcf": estudio_dcf_a_dict(estudio),
            "semaforo": _semaforo_base(estudio, umbrales, tipologia),
        }
    )


@router.post("/precio-maximo")
def precio_maximo(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    uc_dcf: CalcularViabilidadDCF = Depends(calcular_viabilidad_dcf_uc),
):
    """Precio máximo de compra (coste de suelo) para la TIR objetivo del escenario base."""
    _exige_permiso(rol, PermisoModulo.EDITAR)
    parametros = parametros_desde_dict(payload)
    supuestos, financiacion = _supuestos_financiacion(payload)
    precio = precio_maximo_compra(supuestos, financiacion, parametros, _datos_parcela(proyecto), uc=uc_dcf)
    return JSONResponse({"precio_maximo_compra_eur": precio, "tir_objetivo": supuestos.tir_objetivo})


@router.post("/sensibilidad")
def sensibilidad(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    uc_dcf: CalcularViabilidadDCF = Depends(calcular_viabilidad_dcf_uc),
):
    """Análisis de sensibilidad de la TIR (escenario base) a precio de compra / CAPEX / ingreso."""
    _exige_permiso(rol, PermisoModulo.EDITAR)
    parametros = parametros_desde_dict(payload)
    supuestos, financiacion = _supuestos_financiacion(payload)
    resultado = analizar_sensibilidad(supuestos, financiacion, parametros, _datos_parcela(proyecto), uc=uc_dcf)
    return JSONResponse(resultado)


@router.post("/guardar-dcf")
def guardar_dcf(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto = Depends(exige_proyecto),
    uc_dcf: CalcularViabilidadDCF = Depends(calcular_viabilidad_dcf_uc),
    umbrales_repo: UmbralesPRPort = Depends(umbrales_pr_adapter),
    repo: ProyectoRepositorio = Depends(repositorio_proyectos),
):
    """Persiste las ENTRADAS del DCF (parámetros de margen + supuestos + financiación +
    benchmarks) en el aggregate; el resultado se recalcula, no se guarda."""
    _exige_permiso(rol, PermisoModulo.EDITAR)
    parametros = parametros_desde_dict(payload)
    supuestos, financiacion = _supuestos_financiacion(payload)
    benchmarks = benchmarks_desde_dict((payload.get("dcf") or {}).get("benchmarks"))
    estudio = uc_dcf.ejecutar(supuestos, financiacion, parametros, _datos_parcela(proyecto))
    asociar_dcf_a_proyecto(supuestos, financiacion, parametros, proyecto, benchmarks=benchmarks)
    repo.guardar(proyecto)
    tipologia = _tipologia_pr(parametros, payload)
    umbrales = umbrales_repo.obtener()
    return JSONResponse(
        {
            "ok": True,
            "estudio_dcf": estudio_dcf_a_dict(estudio),
            "semaforo": _semaforo_base(estudio, umbrales, tipologia),
        }
    )


@router.post("/aprobar")
def aprobar(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto = Depends(exige_proyecto),
    uc_dcf: CalcularViabilidadDCF = Depends(calcular_viabilidad_dcf_uc),
    umbrales_repo: UmbralesPRPort = Depends(umbrales_pr_adapter),
    repo: ProyectoRepositorio = Depends(repositorio_proyectos),
):
    """Guarda las entradas del estudio y lo marca como **aprobado** (verde en el
    flujo de estados). A diferencia de «Guardar» (que lo deja «sin aprobar»,
    amarillo), «Aprobar» persiste y fija `aprobado=True` en un solo paso."""
    _exige_permiso(rol, PermisoModulo.EDITAR)
    parametros = parametros_desde_dict(payload)
    supuestos, financiacion = _supuestos_financiacion(payload)
    benchmarks = benchmarks_desde_dict((payload.get("dcf") or {}).get("benchmarks"))
    estudio = uc_dcf.ejecutar(supuestos, financiacion, parametros, _datos_parcela(proyecto))
    asociar_dcf_a_proyecto(supuestos, financiacion, parametros, proyecto, benchmarks=benchmarks)
    aprobar_viabilidad(proyecto)  # el rincón ya existe → marca aprobado=True
    repo.guardar(proyecto)
    tipologia = _tipologia_pr(parametros, payload)
    umbrales = umbrales_repo.obtener()
    return JSONResponse(
        {
            "ok": True,
            "aprobado": True,
            "estudio_dcf": estudio_dcf_a_dict(estudio),
            "semaforo": _semaforo_base(estudio, umbrales, tipologia),
        }
    )


# ── Umbrales internos PR (config editable) ─────────────────────────────────
@router.get("/umbrales")
def obtener_umbrales(
    rol: Rol = Depends(rol_activo),
    umbrales_repo: UmbralesPRPort = Depends(umbrales_pr_adapter),
):
    _exige_permiso(rol, PermisoModulo.VER)
    return JSONResponse(umbrales_a_dict(umbrales_repo.obtener()))


@router.post("/umbrales")
def guardar_umbrales(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    umbrales_repo: UmbralesPRPort = Depends(umbrales_pr_adapter),
):
    """Edita los umbrales PR (financiero/arquitecto). Tolerante: campos ausentes o
    inválidos conservan su valor por defecto."""
    _exige_permiso(rol, PermisoModulo.EDITAR)
    umbrales = umbrales_desde_dict(payload)
    umbrales_repo.guardar(umbrales, usuario=rol.value)
    return JSONResponse({"ok": True, "umbrales": umbrales_a_dict(umbrales)})
