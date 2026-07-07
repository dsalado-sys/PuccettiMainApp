"""Flujo de estados del proyecto (§2.11) — modelo de dominio interno.

Proyección **de solo lectura** sobre el aggregate `Proyecto`: resume, con color
(verde/amarillo/rojo), en qué punto del flujo está cada proyecto. No persiste nada
propio; deriva cada estado de lo que ya viven en `datos_por_modulo`, leído por su
clave `ModuloPuccetti.value` (comunicación entre módulos vía aggregate; este módulo
**no importa** ningún otro contexto).

Dimensiones (ver `REGISTRO`/plan del flujo):
- **parcela**   : sin parcela (amarillo) → parcela/inmueble guardado (verde)
- **normativa** : sin normativa (amarillo) → normativa aplicada (verde)
- **errores/avisos** (por escenario de render): con errores y avisos / con errores
  (rojo) · con avisos (amarillo) · sin errores (verde)
- **viabilidad**: sin estudio (rojo) → estudio sin aprobar (amarillo) → aprobado (verde)
- **informe**   : sin aprobar (rojo) → revisado (amarillo) → aprobado (verde)

Las aprobaciones (viabilidad `aprobado`, informe `estado`) aún no tienen camino de
escritura: se leen con default. El resumen de alertas por escenario lo escribe el
frontend de render dentro de `resumen_ultimo_calculo["alertas_resumen"]`.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.nucleo.modelo import ModuloPuccetti, Proyecto


class ColorFlujo(str, Enum):
    VERDE = "verde"
    AMARILLO = "amarillo"
    ROJO = "rojo"


@dataclass(frozen=True)
class EstadoFlujo:
    """Un estado del flujo: clave máquina + etiqueta humana + color."""

    clave: str
    etiqueta: str
    color: ColorFlujo


@dataclass(frozen=True)
class FlujoEscenario:
    """Estado de errores/avisos de un escenario (pestaña) de render."""

    modo: str
    escenario_id: str
    nombre: str
    errores_avisos: EstadoFlujo


@dataclass(frozen=True)
class FlujoProyecto:
    parcela: EstadoFlujo
    normativa: EstadoFlujo
    escenarios: list[FlujoEscenario]
    viabilidad: EstadoFlujo
    informe: EstadoFlujo


# ─── Derivación de cada dimensión ───────────────────────────────────────────

def _parcela(datos: dict[str, Any]) -> EstadoFlujo:
    loc = datos.get(ModuloPuccetti.LOCALIZACION.value) or {}
    if isinstance(loc.get("inmueble_seleccionado"), dict) and loc.get("inmueble_seleccionado"):
        return EstadoFlujo("inmueble_guardado", "Inmueble guardado", ColorFlujo.VERDE)
    if loc:
        return EstadoFlujo("parcela_guardada", "Parcela guardada", ColorFlujo.VERDE)
    return EstadoFlujo("sin_parcela", "Sin parcela guardada", ColorFlujo.AMARILLO)


def _normativa(datos: dict[str, Any]) -> EstadoFlujo:
    rc = datos.get(ModuloPuccetti.RENDER_CALCULOS.value) or {}
    na = rc.get("normativa_aplicada")
    if isinstance(na, dict) and na.get("urbanisticos"):
        return EstadoFlujo("normativa_aplicada", "Normativa aplicada", ColorFlujo.VERDE)
    return EstadoFlujo("sin_normativa", "Sin normativa", ColorFlujo.AMARILLO)


def _clasificar_errores_avisos(resumen: Any) -> EstadoFlujo:
    """Clasifica un escenario a partir de su ``resumen["alertas_resumen"]``.

    ``error`` + ``incumplimiento`` cuentan como "errores"; ``aviso`` como "avisos";
    ``info`` se ignora. Un escenario sin resumen de alertas (nunca calculado) se trata
    como el estado inicial pesimista "con errores y avisos".
    """
    ar = resumen.get("alertas_resumen") if isinstance(resumen, dict) else None
    if not isinstance(ar, dict):
        return EstadoFlujo("con_errores_y_avisos", "Con errores y avisos", ColorFlujo.ROJO)
    err = (ar.get("error") or 0) + (ar.get("incumplimiento") or 0)
    avi = ar.get("aviso") or 0
    if err and avi:
        return EstadoFlujo("con_errores_y_avisos", "Con errores y avisos", ColorFlujo.ROJO)
    if err:
        return EstadoFlujo("con_errores", "Con errores", ColorFlujo.ROJO)
    if avi:
        return EstadoFlujo("con_avisos", "Con avisos", ColorFlujo.AMARILLO)
    return EstadoFlujo("sin_errores", "Sin errores", ColorFlujo.VERDE)


def _escenarios(datos: dict[str, Any]) -> list[FlujoEscenario]:
    """Un `FlujoEscenario` por cada escenario de cada modo de render.

    Recorre `datos_por_modulo["render_calculos"]`: cada valor con clave ``escenarios``
    es el contenedor de un modo (`obra-nueva`/`rehabilitacion`/`inmueble`); se salta la
    clave hermana ``normativa_aplicada`` y el formato plano legado.
    """
    rc = datos.get(ModuloPuccetti.RENDER_CALCULOS.value) or {}
    salida: list[FlujoEscenario] = []
    for modo, contenedor in rc.items():
        if not isinstance(contenedor, dict):
            continue
        escenarios = contenedor.get("escenarios")
        if not isinstance(escenarios, list):
            continue
        for e in escenarios:
            if not isinstance(e, dict):
                continue
            salida.append(FlujoEscenario(
                modo=modo,
                escenario_id=str(e.get("id") or ""),
                nombre=str(e.get("nombre") or "") or "Escenario",
                errores_avisos=_clasificar_errores_avisos(e.get("resumen_ultimo_calculo")),
            ))
    return salida


def _viabilidad(datos: dict[str, Any]) -> EstadoFlujo:
    via = datos.get(ModuloPuccetti.VIABILIDAD.value) or {}
    if not via:
        return EstadoFlujo("sin_estudio", "Sin estudio de viabilidad", ColorFlujo.ROJO)
    if via.get("aprobado"):
        return EstadoFlujo("estudio_aprobado", "Estudio aprobado", ColorFlujo.VERDE)
    return EstadoFlujo("estudio_sin_aprobar", "Estudio sin aprobar", ColorFlujo.AMARILLO)


def _informe(datos: dict[str, Any]) -> EstadoFlujo:
    inf = datos.get(ModuloPuccetti.INFORME.value) or {}
    estado = inf.get("estado") if isinstance(inf, dict) else None
    if estado == "aprobado":
        return EstadoFlujo("informe_aprobado", "Informe aprobado", ColorFlujo.VERDE)
    if estado == "revisado":
        return EstadoFlujo("informe_revisado", "Informe revisado", ColorFlujo.AMARILLO)
    return EstadoFlujo("informe_sin_aprobar", "Informe sin aprobar", ColorFlujo.ROJO)


def calcular_flujo(proyecto: Proyecto) -> FlujoProyecto:
    """Proyección pura del flujo de estados de un proyecto (sin I/O)."""
    datos = proyecto.datos_por_modulo or {}
    return FlujoProyecto(
        parcela=_parcela(datos),
        normativa=_normativa(datos),
        escenarios=_escenarios(datos),
        viabilidad=_viabilidad(datos),
        informe=_informe(datos),
    )


# ─── Serialización ──────────────────────────────────────────────────────────

def _estado_a_dict(e: EstadoFlujo) -> dict[str, str]:
    return {"clave": e.clave, "etiqueta": e.etiqueta, "color": e.color.value}


def flujo_a_dict(flujo: FlujoProyecto) -> dict[str, Any]:
    return {
        "parcela": _estado_a_dict(flujo.parcela),
        "normativa": _estado_a_dict(flujo.normativa),
        "escenarios": [
            {
                "modo": fe.modo,
                "escenario_id": fe.escenario_id,
                "nombre": fe.nombre,
                "errores_avisos": _estado_a_dict(fe.errores_avisos),
            }
            for fe in flujo.escenarios
        ],
        "viabilidad": _estado_a_dict(flujo.viabilidad),
        "informe": _estado_a_dict(flujo.informe),
    }
