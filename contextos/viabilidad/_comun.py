"""§2.9 — Helpers puros compartidos por el cálculo de margen y el motor DCF.

Viven aquí (y no en `casos_uso.py`) para que `modelo_dcf.py` pueda reutilizarlos
sin crear un ciclo de imports (`casos_uso` importa el motor; el motor importa estos
helpers). `casos_uso` los re-expone para el resto del contexto.
"""
from __future__ import annotations

from typing import Any

from .dominio import FuenteSuperficie, Intervencion, ParametrosEconomicos


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
