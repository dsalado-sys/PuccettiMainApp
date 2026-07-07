# Registro — módulo Proyectos (§2.11) + flujo de estados

> Fotografía del estado a 2026-07-07 + reglas vigentes + bitácora. Documento de
> memoria: léelo antes de reexplorar el módulo. Foco principal: el **flujo de
> estados del proyecto** (nuevo, `flujo.py`); el resto del contexto (CRUD +
> carpetas) se resume solo lo justo para situarlo.

---

## 0. Qué es y dónde vive

- **§2.11** — gestión de proyectos: CRUD, organización en carpetas, proyecto
  activo (sesión), y el **flujo de estados** que resume en qué punto va cada
  proyecto (parcela / normativa / errores·avisos / viabilidad / informe).
- Código: `app/contextos/proyectos/` (`casos_uso.py`: `CrearProyecto`,
  `ListarProyectos`, `ObtenerProyecto`, `EliminarProyecto`; `puertos.py`:
  `ProyectoRepositorio`; **`flujo.py`**: modelo del flujo — sin `dominio.py`, el
  aggregate `Proyecto` vive en `nucleo/modelo/`) + `entrypoints/web/rutas/
  proyectos.py` + `entrypoints/web/rutas/menu.py` (landing) +
  `templates/proyectos.html` + `static/js/proyectos.js`.
- Persistencia: `ProyectosSQLAlchemy` (adapter del puerto `ProyectoRepositorio`);
  organización en carpetas vía tablas propias `carpeta_proyecto`/
  `proyecto_en_carpeta` (repo `carpetas_proyecto_repo`, fuera de este contexto).
- Proyecto activo: cookie `puccetti_proyecto` (`dependencias.py::proyecto_activo`,
  `COOKIE_PROYECTO`), fijada/borrada por `/proyectos/{id}/activar` y `/desactivar`.

---

## 1. Landing por defecto = Proyectos (2026-07-07)

`GET /` (`entrypoints/web/rutas/menu.py::menu_principal`) redirige 303 a
`/proyectos` cuando **no hay proyecto activo** (`proyecto is None`):

```python
if proyecto is None:
    return RedirectResponse(url="/proyectos", status_code=303)
```

- Cubre también el post-login (`autenticacion.py` redirige a `/` tras
  `POST /login`).
- El hub de tarjetas (rejilla de módulos) solo se muestra **una vez hay
  proyecto activo**; `/proyectos` siempre es alcanzable (sin bucle de
  redirección, porque su propia ruta no depende de tener proyecto activo).
- Proyectos ya era la primera tarjeta de `CATALOGO`
  (`entrypoints/web/catalogo_modulos.py`) — el orden visible no cambia, solo
  la entrada por defecto.

---

## 2. Flujo de estados del proyecto (`contextos/proyectos/flujo.py`)

### 2.1 Qué es

Proyección **pura y de solo lectura** sobre el aggregate `Proyecto`: sin I/O,
sin persistencia propia. Deriva, en cada llamada, un semáforo (verde/amarillo/
rojo) por dimensión a partir de lo que ya vive en `datos_por_modulo`, leído por
la clave `ModuloPuccetti.value` de cada módulo — **no importa ningún otro
contexto** (regla nuclear de independencia, `app/CLAUDE.md`).

`calcular_flujo(proyecto) -> FlujoProyecto` se llama en caliente desde
`GET /proyectos/datos` (una vez por proyecto listado); `flujo_a_dict(...)`
serializa cada `EstadoFlujo` como `{clave, etiqueta, color}`.

### 2.2 Las 5 dimensiones

| Dimensión | Progresión (color) | Fuente persistida | Función |
|---|---|---|---|
| **Parcela** | Sin parcela (amarillo) → Parcela guardada / Inmueble guardado (verde) | `datos_por_modulo["localizacion"]`: bloque presente → parcela; `inmueble_seleccionado` (dict truthy) → inmueble | `_parcela` |
| **Normativa** | Sin normativa (amarillo) → Normativa aplicada (verde) | `datos_por_modulo["render_calculos"]["normativa_aplicada"]["urbanisticos"]` no vacío | `_normativa` |
| **Errores/avisos** (**por escenario**, no agregado) | Con errores y avisos (rojo) · Con errores (rojo) · Con avisos (amarillo) · Sin errores (verde) | `resumen_ultimo_calculo["alertas_resumen"]` de cada escenario, dentro de cada modo de `datos_por_modulo["render_calculos"]` | `_escenarios` + `_clasificar_errores_avisos` |
| **Viabilidad** | Sin estudio (rojo) → Estudio sin aprobar (amarillo) → Estudio aprobado (verde) | `datos_por_modulo["viabilidad"]` presente → hay estudio; `["aprobado"]` truthy → verde | `_viabilidad` |
| **Informe** | Informe sin aprobar (rojo) → Informe revisado (amarillo) → Informe aprobado (verde) | `datos_por_modulo["informe"]["estado"]` ∈ `{revisado, aprobado}` | `_informe` |

Mapeo de `NivelAlerta` (dominio de `render_calculos`) → errores/avisos:
`error` + `incumplimiento` cuentan como **error**; `aviso` como **aviso**;
`info` se ignora — coincide con el orden de severidad documentado en
`render_calculos/dominio.py` y con `NIVEL_PESO` de `render_calculos.js`.

`_escenarios` recorre **todos los modos** presentes en
`datos_por_modulo["render_calculos"]` (cada valor con clave `escenarios` es el
contenedor de un modo — obra-nueva/rehabilitación/inmueble); salta la clave
hermana `normativa_aplicada` y cualquier entrada que no tenga forma de
contenedor de escenarios. Un proyecto puede tener así **N estados de
errores/avisos**, uno por pestaña de cada modo — no se agregan a un único
semáforo de proyecto (decisión explícita, ver §3).

### 2.3 Persistencia del resumen de alertas — quién escribe qué

Las alertas de render se calculan **en vivo** en `/calcular`/`/estancias` y
**no se guardaban** hasta ahora (`resumenActual()` en `render_calculos.js`
solo devolvía `capacidad`/`totales`). Para que el flujo tenga algo que leer,
el **frontend** (no el backend) embebe un resumen compacto:

- `ESTADO.ultimasAlertas` se fija dentro de `repintarAlertas(alertas)` — un
  único punto, cubre las 4 llamadas existentes (`pedirCalculo` éxito/error,
  `pedirEstancias` éxito/error). `undefined` mientras el escenario no se haya
  calculado nunca.
- `resumenAlertas(alertas)` cuenta por nivel: `{error, incumplimiento, aviso,
  info}`.
- `resumenActual()` embebe `alertas_resumen: resumenAlertas(...)` en el
  resumen solo si `ESTADO.ultimasAlertas !== undefined`; si no, deja el
  resumen tal cual (escenario nunca calculado → sin `alertas_resumen`).

El backend **no cambia**: `POST /modulos/render-calculos/escenarios` ya
guardaba `resumen_ultimo_calculo` **verbatim** (solo valida tamaño en bytes,
`rutas/render_calculos.py`), así que el nuevo campo viaja sin tocar la ruta ni
`GuardarEscenariosRender`/`GuardarRender`.

**Default pesimista**: un escenario sin `alertas_resumen` (nunca calculado) se
clasifica como rojo **"Con errores y avisos"** — el punto de partida más
conservador de la progresión, no un estado neutro aparte (el vocabulario dado
por el arquitecto tiene 4 estados, no 5).

### 2.4 Aprobaciones — solo modeladas, sin escritura

Viabilidad e informe se leen con default; **no hay endpoints ni botones de
aprobar/revisar todavía**:

- Viabilidad: bloque ausente → rojo; presente sin `aprobado` → amarillo;
  `aprobado` truthy → verde. Hoy `datos_por_modulo["viabilidad"]` nunca
  escribe `aprobado` (`asociar_a_proyecto`/`asociar_dcf_a_proyecto` en
  `viabilidad/casos_uso.py` no lo tocan) → **el verde es inalcanzable de
  momento**, es andamiaje a la espera de un endpoint de aprobación.
- Informe: **no existe persistencia de informe en absoluto** hoy
  (`ModuloPuccetti.INFORME` es un stub de ruta, `modulo_pendiente.html`, sin
  `datos_por_modulo["informe"]` en ningún sitio) → siempre rojo
  "Informe sin aprobar" hasta que se construya el módulo real.

### 2.5 Exposición

`GET /proyectos/datos` (`entrypoints/web/rutas/proyectos.py`) añade, por
proyecto:

```python
"flujo": flujo_a_dict(calcular_flujo(p)),
```

`ListarProyectos.ejecutar()` ya devuelve aggregates completos con
`datos_por_modulo` hidratado (`proyectos_sqlalchemy.py::_a_dominio`), sin
coste extra de BBDD. **El JS de proyectos NO consume `flujo` todavía** — el
dato está disponible en el JSON pero no se pinta (decisión explícita: "solo
interno, sin UI" en esta iteración).

---

## 3. Reglas vigentes (transversales a este contexto)

- **`flujo.py` no persiste nada propio** — es una proyección; toda la verdad
  vive en los rincones de otros módulos. Recalcular es barato y evita un
  sexto lugar de la verdad.
- **Errores/avisos es POR ESCENARIO, nunca agregado a un semáforo único de
  proyecto** — cada pestaña de render tiene su propio estado (decisión
  explícita del arquitecto, no una limitación técnica).
- **Aprobaciones son solo andamiaje** — el modelo lee `aprobado`/`estado` con
  default, pero escribirlos (endpoints, botones) es una iteración futura no
  decidida aún.
- **`flujo.py` no importa otros contextos** — regla nuclear de independencia;
  lee `datos_por_modulo` por su clave `ModuloPuccetti.value`, igual que
  cualquier otro consumidor cruzado del aggregate (ver `render_calculos` leyendo
  `LOCALIZACION`/`VIABILIDAD`).
- **Colores**: `ColorFlujo` = `verde` / `amarillo` / `rojo` (3 valores, sin
  "info"/"sin_dato" — a diferencia del semáforo de umbrales PR de viabilidad,
  que sí tiene un 4º estado `SIN_DATO`).

---

## 4. Foto de estado — rama `pestañas-proyectos` (verificado 2026-07-07)

| Pieza | Estado |
|---|---|
| Landing `/` → `/proyectos` sin proyecto activo | **COMPLETO** |
| Modelo `flujo.py` (5 dimensiones, puro) | **COMPLETO** |
| Captura de `alertas_resumen` por escenario (frontend) | **COMPLETO** |
| Exposición en `GET /proyectos/datos` | **COMPLETO** |
| **Pintado del flujo en la UI de Proyectos** (colores en tarjetas / detalle) | **NO EXISTE** — dato disponible en el JSON, sin consumir en `proyectos.js` |
| **Endpoints de aprobación** (viabilidad `aprobado`, informe `estado`) | **NO EXISTE** — verde de ambas dimensiones inalcanzable hoy |
| Módulo Informe real (persistencia `datos_por_modulo["informe"]`) | **NO EXISTE** (stub de ruta únicamente, ver `app/CLAUDE.md`) |

**Tests**: `app/tests/contextos/proyectos/test_flujo.py` (unit, ~20 casos: las
5 dimensiones + serialización) + `app/tests/entrypoints/web/test_flujo_rutas.py`
(ruta: redirect landing, `/datos` incluye `flujo`, round-trip de
`alertas_resumen` a través de `POST /escenarios` real). Suite completa:
**283 verde** (antes 259).

---

## 5. Qué NO hay todavía (gaps conocidos)

- **UI del flujo**: puntos/badges de color en `proyectos.js` (tarjetas de la
  lista) y/o en el panel de detalle (`#pr-d-estado`). CSS reutilizable ya
  existe (`.badge`, `.status-pill` en `puccetti.css`; `--sem-verde/ambar/rojo`
  hoy solo en `viabilidad.css`, habría que promoverlos a `puccetti.css` si se
  quiere un color global, no solo en viabilidad).
- **Endpoints de aprobación**: `POST /modulos/viabilidad/aprobar` (o similar)
  para fijar `datos_por_modulo["viabilidad"]["aprobado"]`; algo análogo para
  informe una vez ese módulo tenga persistencia real.
- **Módulo Informe**: sigue siendo un stub (`modulo_pendiente.html`); el
  campo `informe.estado` del flujo está preparado pero nada lo escribe.
- **Agregación opcional a nivel de proyecto** (p. ej. "peor estado de todas
  las dimensiones" para una vista de una sola línea) — no pedida, no
  construida; hoy el consumidor del JSON ve las 5 dimensiones sueltas.

---

## 6. Bitácora

- **2026-07-07** — Creado este registro. Implementado el flujo de estados del
  proyecto de principio a fin en esta sesión: `contextos/proyectos/flujo.py`
  (nuevo — `ColorFlujo`, `EstadoFlujo`, `FlujoEscenario`, `FlujoProyecto`,
  `calcular_flujo`, `flujo_a_dict`); redirect de landing en
  `entrypoints/web/rutas/menu.py`; exposición en
  `entrypoints/web/rutas/proyectos.py` (`GET /datos`); captura de
  `alertas_resumen` por escenario en `static/js/render_calculos.js`
  (`ESTADO.ultimasAlertas`, `resumenAlertas()`, `resumenActual()`). Sin cambios
  en `casos_uso.py`/rutas de `render_calculos` (el resumen viaja verbatim).
  Tests nuevos: `test_flujo.py` (unit) + `test_flujo_rutas.py` (ruta). Suite:
  259 → **283 verde**. Decisiones de alcance tomadas con el arquitecto: solo
  interno (sin UI), errores/avisos por escenario (no agregado), aprobaciones
  solo modeladas por defecto (sin endpoints). Detalle de la sesión de diseño en
  memoria persistente `project_flujo_proyecto`.
