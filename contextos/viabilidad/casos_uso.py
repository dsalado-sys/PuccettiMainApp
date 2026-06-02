"""§2.9 — Casos de uso de viabilidad económica.

Lógica de cálculo pura (sin I/O) + helpers para serializar los parámetros al
aggregate `Proyecto` (clave `ModuloPuccetti.VIABILIDAD`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.nucleo.modelo import ModuloPuccetti, Proyecto

from .dominio import (
    EstudioViabilidad,
    FuenteSuperficie,
    Intervencion,
    Operacion,
    ParametrosEconomicos,
)


# ── Cálculo ────────────────────────────────────────────────────────────────
@dataclass
class CalcularViabilidad:
    """Caso de uso puro. No depende de repositorios."""

    def ejecutar(
        self,
        parametros: ParametrosEconomicos,
        datos_parcela: dict[str, Any] | None,
    ) -> EstudioViabilidad:
        avisos: list[str] = []
        sup, fuente = self._resolver_superficie(parametros, datos_parcela, avisos)

        coste_constr = sup * max(parametros.coste_construccion_eur_m2, 0.0)
        coste_indir = coste_constr * max(parametros.pct_costes_indirectos, 0.0)
        coste_suelo = max(parametros.coste_suelo_eur, 0.0)
        coste_total = coste_constr + coste_indir + coste_suelo

        if parametros.operacion == Operacion.VENTA:
            ingresos = sup * max(parametros.precio_eur_m2, 0.0)
        else:
            ocup = max(min(parametros.ocupacion_anual_pct, 1.0), 0.0)
            ingresos = sup * max(parametros.precio_eur_m2, 0.0) * 12.0 * ocup

        margen = ingresos - coste_total
        margen_pct = (margen / coste_total * 100.0) if coste_total > 0 else 0.0

        return EstudioViabilidad(
            parametros=parametros,
            superficie_aplicada_m2=round(sup, 1),
            fuente_superficie=fuente,
            ingresos_eur=round(ingresos, 0),
            coste_construccion_eur=round(coste_constr, 0),
            coste_indirectos_eur=round(coste_indir, 0),
            coste_suelo_eur=round(coste_suelo, 0),
            coste_total_eur=round(coste_total, 0),
            margen_eur=round(margen, 0),
            margen_pct=round(margen_pct, 1),
            avisos=avisos,
        )

    @staticmethod
    def _resolver_superficie(
        p: ParametrosEconomicos,
        datos_parcela: dict[str, Any] | None,
        avisos: list[str],
    ) -> tuple[float, FuenteSuperficie]:
        # 1) Override manual: si el usuario fijó una superficie > 0, manda él.
        if p.superficie_construida_m2 and p.superficie_construida_m2 > 0:
            return float(p.superficie_construida_m2), FuenteSuperficie.MANUAL

        if not datos_parcela:
            avisos.append(
                "No hay parcela asociada al proyecto. Asocia una desde "
                "Buscar parcela o introduce una superficie manualmente."
            )
            return 0.0, FuenteSuperficie.VACIO

        sup_parcela = float(datos_parcela.get("superficie_m2") or 0.0)

        # 2) Rehabilitación: superficie construida ya existente según catastro.
        if p.intervencion == Intervencion.REHABILITACION:
            agregados = datos_parcela.get("agregados") or {}
            existente = float(agregados.get("suma_superficie_construida_m2") or 0.0)
            if existente > 0:
                return existente, FuenteSuperficie.CATASTRO_EXISTENTE
            avisos.append(
                "Catastro no reporta superficie construida existente. "
                "Usando parcela × edificabilidad como aproximación."
            )

        # 3) Obra nueva (o rehab. sin dato): parcela × edificabilidad.
        edif = max(p.edificabilidad_m2t_m2s, 0.0)
        if sup_parcela <= 0:
            avisos.append("La parcela del proyecto no tiene superficie registrada.")
        return sup_parcela * edif, FuenteSuperficie.PARCELA_X_EDIFICABILIDAD


# ── Serialización ──────────────────────────────────────────────────────────
def parametros_a_dict(p: ParametrosEconomicos) -> dict[str, Any]:
    return {
        "operacion": p.operacion.value,
        "intervencion": p.intervencion.value,
        "precio_eur_m2": float(p.precio_eur_m2),
        "coste_construccion_eur_m2": float(p.coste_construccion_eur_m2),
        "superficie_construida_m2": float(p.superficie_construida_m2),
        "edificabilidad_m2t_m2s": float(p.edificabilidad_m2t_m2s),
        "coste_suelo_eur": float(p.coste_suelo_eur),
        "pct_costes_indirectos": float(p.pct_costes_indirectos),
        "ocupacion_anual_pct": float(p.ocupacion_anual_pct),
    }


def parametros_desde_dict(d: dict[str, Any] | None) -> ParametrosEconomicos:
    """Crea ParametrosEconomicos desde un dict (típicamente el persistido).

    Acepta dicts parciales: los campos que falten reciben los defaults del
    dataclass. Valores inválidos también caen al default sin propagar excepción.
    """
    base = ParametrosEconomicos()
    if not d:
        return base

    def _f(clave: str, defecto: float) -> float:
        try:
            return float(d.get(clave, defecto))
        except (TypeError, ValueError):
            return defecto

    try:
        operacion = Operacion(d.get("operacion", base.operacion.value))
    except ValueError:
        operacion = base.operacion
    try:
        intervencion = Intervencion(d.get("intervencion", base.intervencion.value))
    except ValueError:
        intervencion = base.intervencion

    return ParametrosEconomicos(
        operacion=operacion,
        intervencion=intervencion,
        precio_eur_m2=_f("precio_eur_m2", base.precio_eur_m2),
        coste_construccion_eur_m2=_f("coste_construccion_eur_m2", base.coste_construccion_eur_m2),
        superficie_construida_m2=_f("superficie_construida_m2", base.superficie_construida_m2),
        edificabilidad_m2t_m2s=_f("edificabilidad_m2t_m2s", base.edificabilidad_m2t_m2s),
        coste_suelo_eur=_f("coste_suelo_eur", base.coste_suelo_eur),
        pct_costes_indirectos=_f("pct_costes_indirectos", base.pct_costes_indirectos),
        ocupacion_anual_pct=_f("ocupacion_anual_pct", base.ocupacion_anual_pct),
    )


def parametros_desde_proyecto(proyecto: Proyecto | None) -> ParametrosEconomicos:
    if proyecto is None:
        return ParametrosEconomicos()
    return parametros_desde_dict(
        proyecto.datos_por_modulo.get(ModuloPuccetti.VIABILIDAD.value)
    )


def estudio_a_dict(e: EstudioViabilidad) -> dict[str, Any]:
    return {
        "parametros": parametros_a_dict(e.parametros),
        "superficie_aplicada_m2": e.superficie_aplicada_m2,
        "fuente_superficie": e.fuente_superficie.value,
        "ingresos_eur": e.ingresos_eur,
        "coste_construccion_eur": e.coste_construccion_eur,
        "coste_indirectos_eur": e.coste_indirectos_eur,
        "coste_suelo_eur": e.coste_suelo_eur,
        "coste_total_eur": e.coste_total_eur,
        "margen_eur": e.margen_eur,
        "margen_pct": e.margen_pct,
        "avisos": list(e.avisos),
    }


# ── Persistencia en el aggregate ───────────────────────────────────────────
def asociar_a_proyecto(parametros: ParametrosEconomicos, proyecto: Proyecto) -> None:
    """Escribe los parámetros del estudio en `proyecto.datos_por_modulo`.

    Solo guarda los **parámetros**, no el resultado del cálculo: el estudio se
    deriva siempre desde los parámetros y los datos de localización vigentes,
    así no caduca cuando el usuario cambie la parcela.
    """
    proyecto.fijar_datos(ModuloPuccetti.VIABILIDAD, parametros_a_dict(parametros))
