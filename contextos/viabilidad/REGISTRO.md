# Registro — módulo Viabilidad (§2.9)

> Fotografía del estado a 2026-07-06 + bitácora de cambios. Actualizar la
> bitácora (abajo) cada vez que se toque este contexto; la fotografía solo
> cuando cambie de forma sustancial (no en cada commit).

## Qué hay hoy (implementado)

**Dominio** (`dominio.py`):
- `Operacion` (VENTA / RENTA) × `Intervencion` (OBRA_NUEVA / REHABILITACION) — dos ejes independientes.
- `ParametrosEconomicos`: precio €/m², coste construcción €/m², superficie construida (override manual), edificabilidad m²t/m²s, coste de suelo €, % costes indirectos, ocupación anual % (solo renta). Defaults heredados de `Modulos/restricciones_app` (Sevilla 2026: venta 3200 €/m², obra nueva 1400 €/m², rehab 900 €/m², indirectos 18%, ocupación 65%).
- `EstudioViabilidad`: salida con superficie aplicada + fuente, ingresos, desglose de costes, margen € y %, lista de avisos.

**Caso de uso** (`casos_uso.py`, `CalcularViabilidad`, puro, sin I/O):
- Fórmula: `ingresos = sup × precio` (venta) o `sup × precio × 12 × ocupación` (renta); `costes = sup × coste_constr × (1+%indirectos) + coste_suelo`; `margen = ingresos − costes`.
- Resolución de superficie con prioridad: **1)** override manual si > 0 (y aviso + fallback si es negativo) → **2)** rehabilitación: superficie construida existente vía Catastro (`agregados.suma_superficie_construida_m2`), con fallback a parcela×edificabilidad si Catastro no la reporta → **3)** obra nueva (o rehab sin dato): parcela × edificabilidad.
- **Saneo trazable** (`_sanear`): cualquier valor negativo o por encima de un máximo se corrige a 0/máximo y genera un aviso explícito — decisión deliberada para no ocultar un dato inválido dentro del margen calculado (ver `feedback` en el CLAUDE.md de este contexto).
- Serialización: `parametros_a_dict` / `parametros_desde_dict` (tolerante: campos que faltan o son inválidos caen a default sin excepción) / `parametros_desde_proyecto` / `estudio_a_dict`.
- Persistencia: `asociar_a_proyecto` escribe **solo los parámetros** en `proyecto.datos_por_modulo[ModuloPuccetti.VIABILIDAD]` — el estudio se recalcula siempre, no caduca si cambia la parcela. Sin repositorio propio.

**Web** (`entrypoints/web/rutas/viabilidad.py` + `viabilidad.html/.js/.css`):
- `GET /modulos/viabilidad` — pantalla (calcula con los parámetros guardados del proyecto activo, o defaults si no hay).
- `POST /modulos/viabilidad/calcular` — preview en vivo (JSON), no persiste.
- `POST /modulos/viabilidad/guardar` — calcula y persiste en el aggregate.
- Permisos vía `MATRIZ_PERMISOS` (VER/EDITAR por rol, igual que el resto de módulos).

**Tests** (`app/tests/contextos/viabilidad/test_calcular_viabilidad.py`, 12 casos): venta/renta, obra nueva/rehabilitación (con y sin dato de Catastro), superficie manual con prioridad, sin parcela, margen negativo, indirectos+suelo, y round-trip de serialización incluyendo valores inválidos.

**Particularidad de paquete**: `viabilidad/__init__.py` es el **único contexto con `__all__`** — se importa desde el paquete (`from app.contextos.viabilidad import ...`), no desde el submódulo como el resto.

## Qué NO hay todavía (brecha vs. la visión del CLAUDE.md de este contexto)

El CLAUDE.md de `viabilidad/` describe un motor mucho más ambicioso que el cálculo de margen actual. Ninguno de estos puntos está construido:

- Flujo de caja descontado (DCF) multi-periodo — hoy es un cálculo estático de un solo periodo.
- Tres escenarios (base / optimista / estrés).
- TIR por escenario, MOIC, período de recuperación (payback).
- Precio máximo de compra para mantener una TIR objetivo (cálculo inverso).
- Estructura de financiación sugerida.
- Conexión con la librería de benchmarks propia **PR**, ni con STR data / Idealista Analytics para RevPAR/ADR.
- Umbrales internos PR (TIR mínima por tipología, yield mínimo/objetivo, payback máximo, CAPEX máx/hab) — hoy no se validan ni se muestran en la UI.
- Análisis de sensibilidad (precio ±10-20%, CAPEX ±15%, RevPAR/renta ±10-15%).
- Output "one-pager financiero".

**Lectura**: el MVP actual cubre el nivel "DESEABLE" que marcaba el PDF de requisitos para §2.9 (€/m² venta/renta, coste de construcción, margen). Todo lo anterior es la capa siguiente, a construir **encima** de `CalcularViabilidad` — evaluar caso a caso qué se reutiliza (la resolución de superficie y el saneo trazable son candidatos claros) y qué se sustituye (el cálculo de un solo periodo no sirve de base para un DCF multi-año; probablemente sea un caso de uso nuevo, `CalcularViabilidadDCF` o similar, que reutilice `ParametrosEconomicos`/superficie como entrada).

## Bitácora de cambios

- **2026-07-06** — Fusionado `CLAUDE.md` + `CLAUDE2.md` del contexto en un único `CLAUDE.md`. Creado este registro tras leer dominio/casos de uso/rutas/tests. Sin cambios de código.
