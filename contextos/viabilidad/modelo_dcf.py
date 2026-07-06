"""§2.9 — COSTURA DEL MODELO DCF (pendiente de la especificación del financiero).

Este fichero es el ÚNICO punto spec-dependiente del motor DCF. Todo lo demás
(dominio, cómputo de métricas, serialización, UI) es agnóstico del modelo y ya
funciona.

`construir_flujos` debe transformar supuestos + parámetros + superficie en una serie
de flujos de caja netos por periodo (`FlujoCaja`), aplicando la perturbación del
escenario. Hasta recibir la spec devuelve una serie VACÍA y anota un aviso: así el
resto del andamiaje es ejecutable y testeable **sin inventar el modelo financiero**.

Para rellenarlo, el financiero debe definir:
  (a) el timing de los flujos: periodo de obra con su curva de CAPEX; venta al final
      vs. rentas anuales netas + salida con exit cap rate;
  (b) el uso de `supuestos.tasa_descuento_anual` y `supuestos.horizonte_anios`;
  (c) el tratamiento de `financiacion` (servicio de la deuda, LTV, tipo, plazo);
  (d) cómo `definicion.factor_precio / factor_capex / factor_ingreso` perturban cada
      escenario.
Las entradas ya llegan saneadas (superficie resuelta, avisos acumulándose): usar
`sanear_trazable` para cualquier parámetro adicional que se lea aquí.
"""
from __future__ import annotations

from typing import Any

from .dominio import (
    DefinicionEscenario,
    Financiacion,
    FlujoCaja,
    ParametrosEconomicos,
    SupuestosDCF,
)


def construir_flujos(
    supuestos: SupuestosDCF,
    parametros: ParametrosEconomicos,
    superficie_m2: float,
    financiacion: Financiacion,
    definicion: DefinicionEscenario,
    datos_parcela: dict[str, Any] | None,
    avisos: list[str],
) -> FlujoCaja:
    """Serie de flujos de caja netos del escenario `definicion.escenario`.

    STUB pendiente de la spec del financiero: devuelve una serie vacía y anota un
    aviso, sin lanzar excepción (respeta el contrato de no-excepción de los casos de
    uso). Al implementar el modelo, sustituir el cuerpo por la construcción real y
    rellenar también `FlujoCaja.detalle` (desglose por concepto para el one-pager).
    """
    # TODO(spec-financiero): construir la serie real aquí (ver docstring del módulo).
    avisos.append(
        "El modelo DCF aún no está definido (pendiente de la especificación del "
        "financiero): no se han calculado flujos de caja."
    )
    return FlujoCaja(neto=[])
