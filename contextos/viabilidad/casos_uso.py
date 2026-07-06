"""§2.9 — Casos de uso de viabilidad económica.

Lógica de cálculo pura (sin I/O) + helpers para serializar los parámetros al
aggregate `Proyecto` (clave `ModuloPuccetti.VIABILIDAD`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.nucleo.modelo import ModuloPuccetti, Proyecto

from . import finanzas
from .dominio import (
    DefinicionEscenario,
    Escenario,
    Estado,
    EstudioViabilidad,
    EstudioViabilidadDCF,
    Financiacion,
    FlujoCaja,
    FuenteSuperficie,
    Intervencion,
    Operacion,
    ParametrosEconomicos,
    ResultadoEscenario,
    SupuestosDCF,
    TipologiaPR,
    UmbralesPR,
)
from .modelo_dcf import construir_flujos


# ── Helpers compartidos (reutilizables por el motor DCF de Fases 1-2) ──────
def sanear_trazable(
    valor: float,
    etiqueta: str,
    avisos: list[str],
    maximo: float | None = None,
) -> float:
    """Saneo TRAZABLE de un parámetro económico: un valor negativo (o por encima
    de `maximo`) se corrige y se anota un aviso en `avisos`, en vez de absorberlo
    en silencio con `max(...)`. Un coste negativo silenciado inflaba el margen sin
    avisar — peligroso en una herramienta de decisión de inversión. Mantiene el
    contrato de no-excepción de los casos de uso (los KPI siguen siendo números
    válidos)."""
    v = float(valor)
    if v < 0:
        avisos.append(f"{etiqueta} no puede ser negativo; se ha usado 0.")
        v = 0.0
    if maximo is not None and v > maximo:
        avisos.append(f"{etiqueta} excede el máximo; se ha limitado.")
        v = maximo
    return v


def resolver_superficie(
    p: ParametrosEconomicos,
    datos_parcela: dict[str, Any] | None,
    avisos: list[str],
) -> tuple[float, FuenteSuperficie]:
    """Superficie construida a aplicar, con su procedencia. Prioridad:
    manual (>0) → [vacío si no hay parcela] → catastro existente (solo rehab con
    dato) → parcela × edificabilidad. Anota en `avisos` cada fallback o corrección."""
    # 1) Override manual: si el usuario fijó una superficie > 0, manda él.
    if p.superficie_construida_m2 and p.superficie_construida_m2 > 0:
        return float(p.superficie_construida_m2), FuenteSuperficie.MANUAL
    if p.superficie_construida_m2 and p.superficie_construida_m2 < 0:
        # Superficie manual negativa: no se usa como override (se descartaba en
        # silencio); se avisa y se cae al autocálculo por parcela × edificabilidad.
        avisos.append("La superficie introducida es negativa; se ha autocalculado.")

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
    edif = float(p.edificabilidad_m2t_m2s)
    if edif < 0:
        avisos.append("La edificabilidad no puede ser negativa; se ha usado 0.")
        edif = 0.0
    if sup_parcela <= 0:
        avisos.append("La parcela del proyecto no tiene superficie registrada.")
    return sup_parcela * edif, FuenteSuperficie.PARCELA_X_EDIFICABILIDAD


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

        sup, fuente = resolver_superficie(parametros, datos_parcela, avisos)

        coste_constr = sup * sanear_trazable(
            parametros.coste_construccion_eur_m2, "El coste de construcción (€/m²)", avisos
        )
        coste_indir = coste_constr * sanear_trazable(
            parametros.pct_costes_indirectos, "El % de costes indirectos", avisos
        )
        coste_suelo = sanear_trazable(parametros.coste_suelo_eur, "El coste del suelo (€)", avisos)
        coste_total = coste_constr + coste_indir + coste_suelo

        if parametros.operacion == Operacion.VENTA:
            ingresos = sup * sanear_trazable(parametros.precio_eur_m2, "El precio (€/m²)", avisos)
        else:
            ocup = sanear_trazable(parametros.ocupacion_anual_pct, "La ocupación anual", avisos, maximo=1.0)
            ingresos = (
                sup * sanear_trazable(parametros.precio_eur_m2, "El precio (€/m²)", avisos) * 12.0 * ocup
            )

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
def _rincon_viabilidad(proyecto: Proyecto) -> dict[str, Any]:
    return dict(proyecto.datos_por_modulo.get(ModuloPuccetti.VIABILIDAD.value) or {})


def asociar_a_proyecto(parametros: ParametrosEconomicos, proyecto: Proyecto) -> None:
    """Escribe los parámetros del estudio en `proyecto.datos_por_modulo`.

    Solo guarda los **parámetros**, no el resultado del cálculo: el estudio se
    deriva siempre desde los parámetros y los datos de localización vigentes,
    así no caduca cuando el usuario cambie la parcela. Preserva el subdiccionario
    `dcf` si ya existía (los dos flujos de guardado comparten el mismo rincón).
    """
    datos = parametros_a_dict(parametros)
    previo = _rincon_viabilidad(proyecto)
    if "dcf" in previo:
        datos["dcf"] = previo["dcf"]
    proyecto.fijar_datos(ModuloPuccetti.VIABILIDAD, datos)


# ── DCF: cómputo de métricas y caso de uso (Fases 1-2) ──────────────────────
def _metricas_escenario(
    escenario: Escenario,
    flujo: FlujoCaja,
    tasa_descuento: float,
    avisos: list[str],
) -> ResultadoEscenario:
    """Calcula VAN/TIR/MOIC/payback/capital de un escenario a partir de su serie de
    flujos. Agnóstico del modelo: opera solo sobre `flujo.neto`. Con serie vacía
    (modelo aún sin definir) devuelve métricas neutras sin lanzar."""
    if flujo.neto:
        van_eur = round(finanzas.van(tasa_descuento, flujo.neto), 0)
        tir = finanzas.tir(flujo.neto)
        payback = finanzas.payback(flujo.neto)
        moic = round(finanzas.moic(flujo.capital_aportado, flujo.capital_distribuido), 3)
        capital = round(flujo.capital_aportado, 0)
    else:
        van_eur, tir, payback, moic, capital = 0.0, None, None, 0.0, 0.0
    return ResultadoEscenario(
        escenario=escenario,
        van_eur=van_eur,
        tir=(round(tir, 4) if tir is not None else None),
        moic=moic,
        payback_anios=(round(payback, 2) if payback is not None else None),
        capital_necesario_eur=capital,
        flujo=flujo,
        avisos=avisos,
    )


@dataclass
class CalcularViabilidadDCF:
    """Motor DCF multi-escenario. Puro, sin repositorios. Reutiliza la resolución de
    superficie y el saneo trazable del cálculo de margen. El modelo financiero real
    vive en `modelo_dcf.construir_flujos` (costura pendiente de spec): este caso de
    uso ya orquesta escenarios, métricas y avisos alrededor de esa costura."""

    def ejecutar(
        self,
        supuestos: SupuestosDCF,
        financiacion: Financiacion,
        parametros: ParametrosEconomicos,
        datos_parcela: dict[str, Any] | None,
    ) -> EstudioViabilidadDCF:
        avisos: list[str] = []
        sup, fuente = resolver_superficie(parametros, datos_parcela, avisos)
        tasa = sanear_trazable(
            supuestos.tasa_descuento_anual, "La tasa de descuento", avisos, maximo=1.0
        )
        if supuestos.horizonte_anios <= 0:
            avisos.append("El horizonte del DCF no está definido (0 años).")

        escenarios: list[ResultadoEscenario] = []
        for definicion in supuestos.escenarios:
            avisos_esc: list[str] = []
            flujo = construir_flujos(
                supuestos, parametros, sup, financiacion, definicion, datos_parcela, avisos_esc
            )
            escenarios.append(_metricas_escenario(definicion.escenario, flujo, tasa, avisos_esc))

        disponible = any(e.flujo.neto for e in escenarios)
        return EstudioViabilidadDCF(
            supuestos=supuestos,
            financiacion=financiacion,
            superficie_aplicada_m2=round(sup, 1),
            fuente_superficie=fuente,
            escenarios=escenarios,
            precio_maximo_compra_eur=None,
            disponible=disponible,
            avisos=avisos,
        )


# ── DCF: serialización ──────────────────────────────────────────────────────
def _num(d: dict[str, Any], clave: str, defecto: float) -> float:
    """Lee `clave` de `d` como float, cayendo a `defecto` si falta o es inválido."""
    try:
        return float(d.get(clave, defecto))
    except (TypeError, ValueError):
        return defecto


def definicion_escenario_a_dict(x: DefinicionEscenario) -> dict[str, Any]:
    return {
        "escenario": x.escenario.value,
        "factor_precio": float(x.factor_precio),
        "factor_capex": float(x.factor_capex),
        "factor_ingreso": float(x.factor_ingreso),
    }


def definicion_escenario_desde_dict(d: dict[str, Any] | None) -> DefinicionEscenario:
    base = DefinicionEscenario()
    if not d:
        return base
    try:
        escenario = Escenario(d.get("escenario", base.escenario.value))
    except ValueError:
        escenario = base.escenario
    return DefinicionEscenario(
        escenario=escenario,
        factor_precio=_num(d, "factor_precio", base.factor_precio),
        factor_capex=_num(d, "factor_capex", base.factor_capex),
        factor_ingreso=_num(d, "factor_ingreso", base.factor_ingreso),
    )


def supuestos_dcf_a_dict(s: SupuestosDCF) -> dict[str, Any]:
    return {
        "horizonte_anios": int(s.horizonte_anios),
        "tasa_descuento_anual": float(s.tasa_descuento_anual),
        "tir_objetivo": float(s.tir_objetivo),
        "escenarios": [definicion_escenario_a_dict(e) for e in s.escenarios],
    }


def supuestos_dcf_desde_dict(d: dict[str, Any] | None) -> SupuestosDCF:
    base = SupuestosDCF()
    if not d:
        return base
    try:
        horizonte = int(d.get("horizonte_anios", base.horizonte_anios))
    except (TypeError, ValueError):
        horizonte = base.horizonte_anios
    escenarios_raw = d.get("escenarios")
    escenarios = (
        [definicion_escenario_desde_dict(e) for e in escenarios_raw]
        if isinstance(escenarios_raw, list) and escenarios_raw
        else base.escenarios
    )
    return SupuestosDCF(
        horizonte_anios=horizonte,
        tasa_descuento_anual=_num(d, "tasa_descuento_anual", base.tasa_descuento_anual),
        tir_objetivo=_num(d, "tir_objetivo", base.tir_objetivo),
        escenarios=escenarios,
    )


def financiacion_a_dict(f: Financiacion) -> dict[str, Any]:
    return {
        "ltv": float(f.ltv),
        "tipo_interes_anual": float(f.tipo_interes_anual),
        "plazo_anios": int(f.plazo_anios),
        "comision_apertura_pct": float(f.comision_apertura_pct),
    }


def financiacion_desde_dict(d: dict[str, Any] | None) -> Financiacion:
    base = Financiacion()
    if not d:
        return base
    try:
        plazo = int(d.get("plazo_anios", base.plazo_anios))
    except (TypeError, ValueError):
        plazo = base.plazo_anios
    return Financiacion(
        ltv=_num(d, "ltv", base.ltv),
        tipo_interes_anual=_num(d, "tipo_interes_anual", base.tipo_interes_anual),
        plazo_anios=plazo,
        comision_apertura_pct=_num(d, "comision_apertura_pct", base.comision_apertura_pct),
    )


def _resultado_escenario_a_dict(r: ResultadoEscenario) -> dict[str, Any]:
    return {
        "escenario": r.escenario.value,
        "van_eur": r.van_eur,
        "tir": r.tir,
        "moic": r.moic,
        "payback_anios": r.payback_anios,
        "capital_necesario_eur": r.capital_necesario_eur,
        "flujo_neto": list(r.flujo.neto),
        "avisos": list(r.avisos),
    }


def estudio_dcf_a_dict(e: EstudioViabilidadDCF) -> dict[str, Any]:
    return {
        "supuestos": supuestos_dcf_a_dict(e.supuestos),
        "financiacion": financiacion_a_dict(e.financiacion),
        "superficie_aplicada_m2": e.superficie_aplicada_m2,
        "fuente_superficie": e.fuente_superficie.value,
        "escenarios": [_resultado_escenario_a_dict(r) for r in e.escenarios],
        "precio_maximo_compra_eur": e.precio_maximo_compra_eur,
        "disponible": e.disponible,
        "avisos": list(e.avisos),
    }


# ── DCF: persistencia en el aggregate ───────────────────────────────────────
def asociar_dcf_a_proyecto(
    supuestos: SupuestosDCF,
    financiacion: Financiacion,
    parametros: ParametrosEconomicos,
    proyecto: Proyecto,
) -> None:
    """Guarda supuestos DCF + financiación bajo `dcf`, junto a los parámetros de
    margen (mismo rincón `VIABILIDAD`). Solo entradas, nunca el resultado."""
    datos = parametros_a_dict(parametros)
    datos["dcf"] = {
        "supuestos": supuestos_dcf_a_dict(supuestos),
        "financiacion": financiacion_a_dict(financiacion),
    }
    proyecto.fijar_datos(ModuloPuccetti.VIABILIDAD, datos)


def supuestos_dcf_desde_proyecto(proyecto: Proyecto | None) -> SupuestosDCF:
    if proyecto is None:
        return SupuestosDCF()
    dcf = _rincon_viabilidad(proyecto).get("dcf") or {}
    return supuestos_dcf_desde_dict(dcf.get("supuestos"))


def financiacion_desde_proyecto(proyecto: Proyecto | None) -> Financiacion:
    if proyecto is None:
        return Financiacion()
    dcf = _rincon_viabilidad(proyecto).get("dcf") or {}
    return financiacion_desde_dict(dcf.get("financiacion"))


# ── Umbrales PR: semáforo (Fase 3) ──────────────────────────────────────────
def evaluar_umbrales(
    umbrales: UmbralesPR,
    tipologia: TipologiaPR,
    *,
    tir: float | None = None,
    payback_anios: float | None = None,
    yield_neto: float | None = None,
    capex_hab: float | None = None,
) -> dict[str, Estado]:
    """Semáforo por métrica contra los umbrales PR. Función pura sobre escalares:
    no se acopla a la forma interna del DCF (las métricas se pasan explícitas; una
    métrica ausente → `SIN_DATO`).

    - TIR: binaria (verde si ≥ mínimo de la tipología, rojo si no).
    - Yield neto: tri-estado (rojo < mínimo; ámbar entre mínimo y objetivo; verde ≥ objetivo).
    - Payback: binaria (verde si ≤ máximo).
    - CAPEX/hab: binaria (verde si ≤ máximo).
    """
    estados: dict[str, Estado] = {}

    if tir is None:
        estados["tir"] = Estado.SIN_DATO
    else:
        estados["tir"] = Estado.VERDE if tir >= umbrales.tir_minima(tipologia) else Estado.ROJO

    if yield_neto is None:
        estados["yield"] = Estado.SIN_DATO
    elif yield_neto < umbrales.yield_neto_minimo:
        estados["yield"] = Estado.ROJO
    elif yield_neto < umbrales.yield_objetivo:
        estados["yield"] = Estado.AMBAR
    else:
        estados["yield"] = Estado.VERDE

    if payback_anios is None:
        estados["payback"] = Estado.SIN_DATO
    else:
        estados["payback"] = (
            Estado.VERDE if payback_anios <= umbrales.payback_maximo_anios else Estado.ROJO
        )

    if capex_hab is None:
        estados["capex_hab"] = Estado.SIN_DATO
    else:
        estados["capex_hab"] = (
            Estado.VERDE if capex_hab <= umbrales.capex_maximo_hab_eur else Estado.ROJO
        )

    return estados


def semaforo_global(estados: dict[str, Estado]) -> Estado:
    """Peor estado presente (rojo > ámbar > verde), ignorando los `SIN_DATO`.
    `SIN_DATO` si no hay ninguna métrica evaluada."""
    presentes = [e for e in estados.values() if e != Estado.SIN_DATO]
    if not presentes:
        return Estado.SIN_DATO
    for peor in (Estado.ROJO, Estado.AMBAR, Estado.VERDE):
        if peor in presentes:
            return peor
    return Estado.VERDE


# ── Umbrales PR: serialización ───────────────────────────────────────────────
def umbrales_a_dict(u: UmbralesPR) -> dict[str, Any]:
    return {
        "tir_min_btr_residencial": float(u.tir_min_btr_residencial),
        "tir_min_hotelero": float(u.tir_min_hotelero),
        "tir_min_rehab_intensiva": float(u.tir_min_rehab_intensiva),
        "yield_neto_minimo": float(u.yield_neto_minimo),
        "yield_objetivo": float(u.yield_objetivo),
        "payback_maximo_anios": float(u.payback_maximo_anios),
        "capex_maximo_hab_eur": float(u.capex_maximo_hab_eur),
    }


def umbrales_desde_dict(d: dict[str, Any] | None) -> UmbralesPR:
    """Tolerante: campos ausentes o inválidos caen al default (valor sembrado)."""
    base = UmbralesPR()
    if not d:
        return base
    return UmbralesPR(
        tir_min_btr_residencial=_num(d, "tir_min_btr_residencial", base.tir_min_btr_residencial),
        tir_min_hotelero=_num(d, "tir_min_hotelero", base.tir_min_hotelero),
        tir_min_rehab_intensiva=_num(d, "tir_min_rehab_intensiva", base.tir_min_rehab_intensiva),
        yield_neto_minimo=_num(d, "yield_neto_minimo", base.yield_neto_minimo),
        yield_objetivo=_num(d, "yield_objetivo", base.yield_objetivo),
        payback_maximo_anios=_num(d, "payback_maximo_anios", base.payback_maximo_anios),
        capex_maximo_hab_eur=_num(d, "capex_maximo_hab_eur", base.capex_maximo_hab_eur),
    )
