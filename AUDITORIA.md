# Auditoría de `app/` — cambios, mejoras y arreglos pendientes

**Fecha:** 2026-06-12
**Alcance:** todo el árbol `app/` (~12 000 líneas: FastAPI + SQLAlchemy 2.x + Jinja2 + JS vanilla).
**Método:** revisión multi-agente en 9 dimensiones en paralelo + verificación adversarial (se confirmaron 167 de 168 hallazgos releyendo el código) + verificación manual de los de cabecera.

> ### ⚠️ Nota de rama
> El working tree estaba en **`auto-render-dev`**, que es **`pre` + trabajo sin commitear**: el refactor `reparto_unidades.py` (1471 líneas, **no existe en `pre`**) y ediciones en `casos_uso.py`, `capacidad.py`, `config.py`, `serializacion.py`, `render_calculos.py` (~+243/-10 líneas).
> La **inmensa mayoría** de los hallazgos están en archivos idénticos a `pre` (Catastro, persistencia, seguridad web, permisos, arquitectura). Los que viven **solo en el WIP** (no en `pre`) están marcados con **`[WIP]`**.

## Resumen de severidad

| Severidad | Nº | Temas dominantes |
|-----------|----|------------------|
| 🔴 Crítica | 1 | Quemar la API del Catastro |
| 🟠 Alta | 16 | Catastro, bugs de cálculo, seguridad web, persistencia, tests |
| 🟡 Media | 85 | Manejo de errores Catastro, CSRF/permisos, i18n números, duplicación |
| ⚪ Baja | 67 | Validación de entradas, código muerto, accesibilidad, comentarios |

**El patrón nº1, y el que más choca con una regla explícita del proyecto, es quemar la API del Catastro** (rate limit horario por IP que afecta a todo el estudio).

---

## 🔴 CRÍTICA

### C1. «Asociar a proyecto» puede agotar la cuota del Catastro en un solo click
- **Archivo:** [contextos/localizacion/casos_uso.py:244](contextos/localizacion/casos_uso.py#L244) (`CargarTodosLosDetalles`)
- **Problema:** itera *todas* las subreferencias y llama a `obtener_detalle_subreferencia` por cada una; cada llamada construye un `ParcelaCatastral` de ESCatastroLib que hace ~3 peticiones HTTP. Un edificio con 100 inmuebles = ~300 peticiones seriadas (hasta 30 s de timeout cada una) → bloqueo horario de la IP para toda la app y petición colgada varios minutos. El propio docstring admite «una llamada al Catastro por subreferencia». **Verificado.**
- **Arreglo:** poner un tope de subreferencias por ejecución, o eliminar el bulk y obtener el agregado con **UNA** llamada a `Consulta_DNPRC` del RC14 (que ya devuelve todos los inmuebles) en vez de N por RC20.

---

## 🟠 ALTAS

### Tema A — Catastro (consumo y robustez)

#### A1. Entrar a Localización re-consulta el Catastro en cada GET
- **Archivo:** [entrypoints/web/rutas/localizacion.py:169](entrypoints/web/rutas/localizacion.py#L169) (`pantalla_buscar`)
- **Problema:** si el proyecto tiene RC, cada GET (incl. F5 y navegación ida/vuelta) ejecuta `uc_rc.ejecutar(rc_proyecto)` → ~4-6 peticiones, aunque el JSON completo de la parcela ya esté en `datos_por_modulo`. Navegar entre módulos quema la cuota sin que el usuario haga nada. **Verificado.**
- **Arreglo:** reconstruir **siempre** desde el JSON guardado (`restaurar_parcela_desde_proyecto`) y ofrecer un botón explícito «Actualizar desde Catastro»; o cachear por RC con TTL.

#### A2. El rate limit es invisible por la vía de ESCatastroLib
- **Archivo:** [plataforma/catastro/catastro_meh.py:460](plataforma/catastro/catastro_meh.py#L460)
- **Problema:** `RateLimitCatastro` solo se lanza en los 3 endpoints REST directos. Los caminos vía `ParcelaCatastral`/`MetaParcela`/`listar_calles` ante un 403 lanzan error genérico o devuelven lista vacía. Consecuencias: (1) el `except RateLimitCatastro` del bulk ([casos_uso.py:249](contextos/localizacion/casos_uso.py#L249)) es **código muerto**; (2) se marca `detalle_cargado=True` con datos vacíos que quedan **persistidos para siempre**; (3) el usuario rate-limitado ve listas vacías sin aviso.
- **Arreglo:** que `obtener_detalle_subreferencia` lance `RateLimitCatastro`/`ParcelaNoEncontrada` en vez de `(None, None)`, y solo marcar `detalle_cargado=True` cuando la consulta tuvo éxito.

#### A3. El «coeficiente de participación» es imposible de obtener
- **Archivo:** [plataforma/catastro/catastro_meh.py:469](plataforma/catastro/catastro_meh.py#L469)
- **Problema:** `getattr(p, "coeficiente_participacion")` sobre un objeto de ESCatastroLib que **nunca define ese atributo** → siempre `None`. Toda la columna de coeficiente (lazy + bulk) gasta 3 llamadas HTTP por subreferencia por un dato inalcanzable.
- **Arreglo:** obtenerlo por REST directo (`bico.bi.debi.cpt` del JSON del Catastro) o retirar la columna/flujo hasta implementarlo.

#### A4. Errores normales del Catastro llegan al usuario como 500
- **Archivo:** [plataforma/catastro/catastro_meh.py:404](plataforma/catastro/catastro_meh.py#L404)
- **Problema:** el adapter solo captura `ValueError`/`ErrorServidorCatastro`, pero «número no existe», «calle no existe», `AttributeError`/`ExpatError` al parsear, timeouts y `r.json()` sobre HTML (el Catastro a veces responde HTML con HTTP 200) escapan → **500 crudo** en una búsqueda corriente. Rompe la degradación suave de `pantalla_buscar`.
- **Arreglo:** en el borde del adapter, `except requests.RequestException` → error propio de conectividad, y `except Exception` de los constructores de ESCatastroLib → `ParcelaNoEncontrada` con el mensaje útil; envolver `r.json()` de `_rc_desde_coordenadas` en try/except.

### Tema B — Bugs de cálculo

#### B1. Rehabilitación ignora la superficie construida de parcelas únicas
- **Archivo:** [contextos/viabilidad/casos_uso.py:84](contextos/viabilidad/casos_uso.py#L84) (`_resolver_superficie`)
- **Problema:** la rama de rehabilitación solo mira `agregados.suma_superficie_construida_m2`, que es `None`/0 en edificios sin división horizontal (el caso más común), aunque el Catastro sí reportó `superficie_construida_total_m2`. Resultado: se cae a `parcela × edificabilidad` (default 1.0), con aviso engañoso, y costes/ingresos hasta **3× desviados**. **Verificado.**
- **Arreglo:** en `REHABILITACION`, si los agregados no aportan dato, caer primero a `datos_parcela.get("superficie_construida_total_m2")` antes del fallback. Añadir test.

#### B2. `[WIP]` El ascensor del núcleo queda recortado a 0,60 m
- **Archivo:** [contextos/render_calculos/geometria/reparto_unidades.py:571](contextos/render_calculos/geometria/reparto_unidades.py#L571) **(solo en `auto-render-dev`, no en `pre`)**
- **Problema:** `NUCLEO_LARGO=5.20` es insuficiente para escalera (4.50) + junta (0.10) + ascensor (1.60) = **6.20 m**. El box del ascensor se intersecta con el bloque y queda recortado a 0.60×1.60 m en **todos** los núcleos; además el chequeo del círculo Ø1,50 del vestíbulo se evalúa con más espacio del real. **Verificado aritméticamente.**
- **Arreglo:** subir `NUCLEO_LARGO` a ≥6.20 m (o colocar el ascensor en la franja del vestíbulo, 1.80 ≥ 1.60) y añadir incidencia si el ascensor resultante queda por debajo de 1.60 m.

### Tema C — Seguridad web

> Contexto: app de uso interno del estudio, sin login real todavía (previsto en CLAUDE.md). La severidad está calibrada a ese contexto.

#### C1-web. XSS almacenado por `innerHTML` con nombres editables
- **Archivos:** [normativa_municipal.js:102](entrypoints/web/static/js/normativa_municipal.js#L102) y `:147`; [render_calculos.js:614](entrypoints/web/static/js/render_calculos.js#L614) y `:645`; [proyectos.html:58](entrypoints/web/templates/proyectos.html#L58) (nombre de proyecto en `onsubmit` inline).
- **Problema:** nombres de carpeta/normativa/proyecto (entrada libre, sin sanear) interpolados en `innerHTML`/atributo JS. Un nombre `<img src=x onerror=...>` se ejecuta al abrir el módulo para cualquier rol.
- **Arreglo:** `document.createElement` + `textContent`, o un helper `escapeHtml` (ya existe en `viabilidad.js`). En la plantilla, `{{ p.nombre | tojson }}` o un listener con `data-nombre`.

#### C2-web. Rol por defecto = ARQUITECTO (máximo privilegio)
- **Archivo:** [entrypoints/web/dependencias.py:47](entrypoints/web/dependencias.py#L47)
- **Problema:** sin cookie (o cookie inválida), `rol_activo()` devuelve el rol con VER+EDITAR en los 7 módulos → la `MATRIZ_PERMISOS` es decorativa y amplifica el riesgo de CSRF.
- **Arreglo:** default al rol de menor privilegio (`INVERSOR`) o configurable por env var. La UI de cambio de rol sigue igual.

### Tema D — Persistencia y arquitectura

#### D1. Sin sistema de migraciones
- **Archivo:** [plataforma/persistencia/sqlalchemy_base.py:81](plataforma/persistencia/sqlalchemy_base.py#L81)
- **Problema:** el único mecanismo es `_migracion_sqlite_idempotente`, una lista manual con **una** columna y `except Exception: pass`. Renombrados de iteraciones previas (documentados en `normativa_municipal_sqlalchemy.py`) no tienen ruta de migración: una BBDD anterior rompe el arranque con «no such column». Hay `.bak` manuales como prueba del workaround. Contradice la promesa «cambiar a Postgres = cambiar `PUCCETTI_DB_URL` y nada más» (es solo-SQLite).
- **Arreglo:** Alembic (autogenerate sobre `Base.metadata`) dentro de `init_db()`.

#### D2. Factor de negocio `×1.15` hardcodeado y triplicado en persistencia
- **Archivos:** [anexo_i_hotelero_sqlalchemy.py:65](plataforma/persistencia/anexo_i_hotelero_sqlalchemy.py#L65), `anexo_i_apartamentos_sqlalchemy.py:84`, `anexo_i_hotel_apartamento_sqlalchemy.py:58`, **más** una 4ª copia en el dominio (`geometria/programa_hotelero.py:116`) sobre **otra base de cálculo** → divergencia real entre vía-BBDD y vía-fallback.
- **Problema:** un adapter debe devolver datos, no aplicar políticas (viola la convención del proyecto).
- **Arreglo:** que los puertos devuelvan el mínimo crudo y que un único punto en `render_calculos` aplique el ×1.15 con la misma base.

#### D3. Módulo «carpetas de normativa» sin puerto ni contexto
- **Archivo:** [entrypoints/web/rutas/normativa_municipal.py:28](entrypoints/web/rutas/normativa_municipal.py#L28)
- **Problema:** la ruta importa y anota directamente `CarpetasNormativaSQLAlchemy`; no existe puerto en `contextos/` ni casos de uso. La capa de aplicación entera vive en la ruta hablando con el adapter SQLAlchemy → incumple hexagonal.
- **Arreglo:** crear `contextos/normativa_municipal/` con el `Protocol` del repositorio + casos de uso; mover el provider a `dependencias.py`.

### Tema E — Tests (el mayor agujero de robustez)

> Solo hay 3 archivos de test (`test_programa_hotel_apartamentos.py`, `test_reparto_unidades.py` `[WIP]`, `test_calcular_viabilidad.py`). **Bloqueador transversal:** [sqlalchemy_base.py:21](plataforma/persistencia/sqlalchemy_base.py#L21) crea el engine en *import* → no se puede testear en `:memory:` sin fijar la env var antes de cualquier import (falta `conftest.py`).

| Hallazgo | Archivo | Riesgo sin test |
|----------|---------|-----------------|
| **E1.** `ValidarCumplimiento` sin test | [casos_uso.py:602](contextos/render_calculos/casos_uso.py#L602) | 18 reglas de normativa con comparadores manuales; un signo invertido deja de avisar de incumplimientos. **Es la función central de prefactibilidad.** |
| **E2.** `calcular_capacidad` solo con asserts `>0` | [capacidad.py:257](contextos/render_calculos/geometria/capacidad.py#L257) | El nº de viviendas/m² que decide la viabilidad podría duplicarse o partirse por la mitad sin que falle ningún test. |
| **E3.** `construir_envolvente` sin test | [envolvente.py:60](contextos/render_calculos/geometria/envolvente.py#L60) | `_restar_franja_lado` tiene un fallback que **ignora el retranqueo en silencio** y sobreestima la superficie edificable. |
| **E4.** Adapter del Catastro (480 líneas) sin test | [catastro_meh.py:347](plataforma/catastro/catastro_meh.py#L347) | Todo el parsing JSON/XML es testeable **100% offline** con respuestas grabadas; es justo donde no se puede depurar en vivo (quema la API). |
| **E5.** Cero tests de rutas/permisos | [proyectos.py:76](entrypoints/web/rutas/proyectos.py#L76) | `MATRIZ_PERMISOS` se aplica a mano en cada ruta; una ruta nueva sin `_exige_permiso` se desplegaría sin que nada falle. Testeable con `TestClient` sin red. |

---

## 🟡 MEDIAS (selección por tema)

### Catastro / caché
- **Caché sin índice por RC ni persistencia** — [parcelas_en_memoria.py:15](plataforma/cache/parcelas_en_memoria.py#L15): cada búsqueda repetida (doble click, F5, dos usuarios) y cada reinicio re-quema la API. Añadir índice por `referencia_catastral` con TTL y/o adapter SQLAlchemy.
- **Llamadas vía ESCatastroLib sin timeout** — [catastro_meh.py:450](plataforma/catastro/catastro_meh.py#L450): `listar_vias`, nº de plantas y croquis pueden colgar el worker indefinidamente.
- **Detección de rate-limit frágil ante tildes** — [catastro_meh.py:77](plataforma/catastro/catastro_meh.py#L77): no normaliza con `_sin_tildes` y solo mira 400 chars; «Petición denegada» con tilde no coincide.
- **`vecinos_en_bbox` ignora `excluir_rc`** — [catastro_meh.py:413](plataforma/catastro/catastro_meh.py#L413): contrato del puerto incumplido; la propia parcela entra en la unión de vecinos y puede clasificar mal un lado de fachada.

### Seguridad / permisos
- **Sin CSRF en formularios** — [proyectos.py:70](entrypoints/web/rutas/proyectos.py#L70): los POST por `Form` (crear/eliminar proyecto, cambiar rol, buscar) no validan `Origin`/`Sec-Fetch-Site`; con el rol por defecto = arquitecto, una página maliciosa puede eliminar proyectos o disparar búsquedas en bucle contra el Catastro. Arreglo global en `aplicacion.py` (middleware).
- **`n_plantas_max` sin cota superior → DoS** — [parametros.py:459](contextos/render_calculos/parametros.py#L459): alimenta un bucle de Shapely; un POST con `n_plantas_max: 10000000` bloquea el worker. Aplicar `min(60, ...)`.
- **Endpoints de callejero sin chequeo de permisos** — [localizacion.py:380](entrypoints/web/rutas/localizacion.py#L380): `/callejero/provincias` y `/municipios` no consultan `MATRIZ_PERMISOS`.
- **`detalle_subreferencia` solo exige VER pero consume Catastro y muta caché** — [localizacion.py:339](entrypoints/web/rutas/localizacion.py#L339): debería exigir EDITAR.
- **`POST /guardar` persiste «resumen» arbitrario sin validar ni limitar tamaño** — [render_calculos.py:243](entrypoints/web/rutas/render_calculos.py#L243).
- **500 con texto interno de la excepción** — [localizacion.py:142](entrypoints/web/rutas/localizacion.py#L142): fallback de `_mapear_error` filtra detalles internos.

### Bugs de cálculo / lógica
- **Reproyección clavada a EPSG:25830 (huso 30)** — [casos_uso.py:62](contextos/render_calculos/casos_uso.py#L62): Localización elige el huso por coordenadas, pero Render reproyecta siempre en huso 30 → áreas (y edificabilidad, nº viviendas, viabilidad) distorsionadas en Canarias, Cataluña, Galicia, Baleares.
- **`actualizar()` rompe el invariante de `max_m2_util`** — [anexo_i_hotelero_sqlalchemy.py:90](plataforma/persistencia/anexo_i_hotelero_sqlalchemy.py#L90) (copiado en otros 3 adapters): tras editar, `util_objetivo` con `.limit(1)` sin `ORDER BY` puede devolver una fila corrupta. Latente (ninguna ruta invoca aún `actualizar()`).
- **`reset()` hace commit del DELETE antes de resembrar** — [catalogo_superficies_sqlalchemy.py:166](plataforma/persistencia/catalogo_superficies_sqlalchemy.py#L166) (y los 3 análogos): si la siembra falla, la tabla queda vacía. Síntoma del patrón general «cada método hace su propio commit» (no hay unidad de trabajo por request).

### Arquitectura / persistencia
- **Cuatro adapters `anexo_i_*` casi idénticos** — [anexo_i_hotel_apartamento_sqlalchemy.py:17](plataforma/persistencia/anexo_i_hotel_apartamento_sqlalchemy.py#L17): mismo ORM y métodos; cada bugfix hay que aplicarlo 4 veces. Extraer adapter genérico parametrizado por clase ORM.
- **Volcado BD → constantes globales en el arranque** — [aplicacion.py:36](entrypoints/web/aplicacion.py#L36): `_volcar_superficies_a_runtime()` corre una vez; las ediciones posteriores del catálogo no surten efecto hasta reiniciar (lo contrario de lo que promete su comentario). Además mutar `globals()` no es seguro con concurrencia.
- **Engine resuelto en import** — [sqlalchemy_base.py:21](plataforma/persistencia/sqlalchemy_base.py#L21): bloquea testear sin tocar la BBDD real. Refactorizar a factoría `crear_engine(url)` o `conftest.py` con `:memory:`.
- **PK natural con texto libre sin normalizar** — [normativa_municipal_sqlalchemy.py:27](plataforma/persistencia/normativa_municipal_sqlalchemy.py#L27): `'SEVILLA'` no encuentra la fila `'Sevilla'` (SQLite es sensible a mayúsculas) → misses y duplicados. Canonicalizar la clave (minúsculas + sin tildes).
- **Seed del callejero depende de un fichero fuera de `app/`** — [callejero_seed.py:22](plataforma/persistencia/callejero_seed.py#L22): lee `Antiguo/Python/municipalities.json`; si se despliega `app/` sola, las tablas quedan vacías en silencio. Copiar el dato dentro de `app/`.

### Tests adicionales (medias)
- Round-trip `asociar_a_proyecto ↔ restaurar_parcela_desde_proyecto` ([casos_uso.py:378](contextos/localizacion/casos_uso.py#L378)): el `except Exception: return None` hace desaparecer la parcela del proyecto en silencio.
- Geometría de localización (azimuts, clasificación fachada/medianera, selección de huso) sin test — [geometria.py:102](contextos/localizacion/geometria.py#L102).
- Migraciones de JSON legacy en `parametros_desde_dict` sin test — [parametros.py:442](contextos/render_calculos/parametros.py#L442): una regresión cambia silenciosamente todos los proyectos ya guardados.
- Consistencia de `MATRIZ_PERMISOS` sin test — [rol.py:80](nucleo/modelo/rol.py#L80): un typo en un slug deja un módulo invisible para todos los roles.
- Adapter `ProyectosSQLAlchemy` (persistencia por defecto) sin round-trip — [proyectos_sqlalchemy.py:46](plataforma/persistencia/proyectos_sqlalchemy.py#L46).
- Asserts e2e débiles (`>0`) pese a ser deterministas (seed=42) — [test_programa_hotel_apartamentos.py:189](tests/contextos/render_calculos/test_programa_hotel_apartamentos.py#L189): anclar valores exactos.

### i18n de números (coma decimal es-ES)
Varios puntos mezclan punto y coma decimal, y los KPIs cambian de formato tras el primer recálculo (servidor Jinja `%.1f` vs cliente `Intl es-ES`):
- [viabilidad.html:165](entrypoints/web/templates/viabilidad.html#L165), [localizacion.js:406](entrypoints/web/static/js/localizacion.js#L406), [rc_canvas.js:187](entrypoints/web/static/js/rc_canvas.js#L187).
- **CSV exportado con punto decimal y delimitador `;`** — [render_calculos.py:328](entrypoints/web/rutas/render_calculos.py#L328): Excel es-ES lee los números como texto. Formatear con coma.
- **Recomendación:** un formateador `Intl.NumberFormat('es-ES')` compartido en el cliente + un filtro Jinja es-ES en el servidor.

---

## 🟡 Convención incumplida: referencias al PDF en textos de UI

Tu regla (avisos sin «Anexo I/II», «DB SUA», «Decreto 194/2010», «§x.x» — usar el identificador unificado «Normativa») tiene fugas reales **en texto visible** (los comentarios internos `{# … #}` y docstrings están bien):

| Ubicación | Texto actual | Cambio |
|-----------|--------------|--------|
| [render_calculos.html:15](entrypoints/web/templates/render_calculos.html#L15) | tooltip `«envolvente + Anexo I)»` | `«… + Normativa»` |
| [_rc_panel_params.html:235](entrypoints/web/templates/_rc_panel_params.html#L235) | `«% unidades adaptadas (DB SUA)»` | `«… (Normativa)»` |
| [_rc_modal_unidad.html:32](entrypoints/web/templates/_rc_modal_unidad.html#L32) | `<h3>Estancias (Anexo I)</h3>` | `«Estancias (Normativa)»` |
| [render_calculos.py:179](entrypoints/web/rutas/render_calculos.py#L179) y `:210` | HTTPException `«Localízala en §2.1»` (se muestra en toast) | `«… en Buscar parcela»` |
| [render_calculos.py:324](entrypoints/web/rutas/render_calculos.py#L324) | cabecera CSV `«§2.7»` | sin `§` |
| [adyacencias.py:64](contextos/render_calculos/geometria/adyacencias.py#L64), [macro_layout.py:297](contextos/render_calculos/geometria/macro_layout.py#L297) | incidencias `«A2.1/A2.2/A2.5»` (si se reactivan) | prefijo `«Normativa»` |

**Blindaje recomendado:** un test guardián que recorra los `detail`/`Alerta.mensaje` generados y falle ante `r'Anexo [IVX]|DB SUA|Decreto \d|§\d|A2\.\d'`.

---

## ⚪ MENORES (67) — agrupadas por categoría

### Validación de entradas (bugs)
- Crear proyecto con nombre en blanco → **500 sin controlar** ([proyectos.py:59](entrypoints/web/rutas/proyectos.py#L59), [proyectos/casos_uso.py:24](contextos/proyectos/casos_uso.py#L24)): envolver el `ValueError` y responder 422.
- Eliminar cualquier proyecto **borra la cookie del proyecto activo** aunque no fuera ese, e incluso sin permiso ([proyectos.py:79](entrypoints/web/rutas/proyectos.py#L79)).
- `referencia_catastral` en `String(14)` frente a RC de inmueble de 20 chars y entrada libre del formulario ([proyectos_sqlalchemy.py:25](plataforma/persistencia/proyectos_sqlalchemy.py#L25)): ampliar a `String(20)` y validar/normalizar.
- `CatalogoApartamentosSQLAlchemy.reset()` borra **los dos grupos** (edificios y conjuntos) sin distinción ([anexo_i_apartamentos_sqlalchemy.py:130](plataforma/persistencia/anexo_i_apartamentos_sqlalchemy.py#L130)).
- `margen_pct` se reporta como 0,0 % cuando `coste_total` es 0 aunque el margen sea positivo ([viabilidad/casos_uso.py:47](contextos/viabilidad/casos_uso.py#L47)).
- Parámetros negativos se recortan a 0 en el cálculo pero se **persisten y muestran tal cual** ([viabilidad/casos_uso.py:35](contextos/viabilidad/casos_uso.py#L35)).
- Se valida el coeficiente de edificabilidad aunque el proyecto lo tenga desactivado ([casos_uso.py:587](contextos/render_calculos/casos_uso.py#L587)).
- `NIVEL_PESO`/orden de alertas en el front usa la clave `'error'` que el backend nunca emite, y le falta `'incumplimiento'` ([render_calculos.js:341](entrypoints/web/static/js/render_calculos.js#L341)).
- Tras un error, el caché `ultimoPayload` bloquea el recálculo con los mismos datos ([viabilidad.js:130](entrypoints/web/static/js/viabilidad.js#L130)).

### Geometría (bugs de borde)
- Admisión voraz por techo puede admitir una planta superior tras rechazar una intermedia ([capacidad.py:264](contextos/render_calculos/geometria/capacidad.py#L264)).
- Factor limitante `'altura (nº plantas)'` inalcanzable desde el camino vivo ([capacidad.py:273](contextos/render_calculos/geometria/capacidad.py#L273)).
- Franja de retranqueo con cap plano deja cuñas sin retranquear en vértices cóncavos ([envolvente.py:59](contextos/render_calculos/geometria/envolvente.py#L59)).
- `treemap.aspect_ratio` casca con geometrías degeneradas (asume MRR de 4 vértices) ([treemap.py:63](contextos/render_calculos/geometria/treemap.py#L63)).
- Sonda de `clasificar_lados` sin verificación del flip: parcelas/entrantes estrechos se clasifican mal ([parcelas.py:119](contextos/render_calculos/geometria/parcelas.py#L119)).
- Umbral de solape de adyacencias equivale a la mitad de la longitud nominal del parámetro ([adyacencias.py:47](contextos/render_calculos/geometria/adyacencias.py#L47)).
- `[WIP]` `util_min` de vivienda en el reparto ignora `salon_cocina_open` ([reparto_unidades.py:399](contextos/render_calculos/geometria/reparto_unidades.py#L399)).
- Bbox degenerado dibuja fuera de pantalla sin mensaje ([rc_canvas.js:62](entrypoints/web/static/js/rc_canvas.js#L62)); `_patronPatio` sin la guarda anti-anillo-corto de `_trazarPoligono` ([rc_canvas.js:98](entrypoints/web/static/js/rc_canvas.js#L98)).

### Código muerto / higiene
- `macro_layout.py` (613 líneas): **algoritmo deprecado** pero sus dataclasses (`Unidad`, `Nucleo`, `PlantaPlurifamiliar`, `EdificioPlurifamiliar`) aún se importan desde `interiores.py`/`serializacion.py`. Separar estructuras vivas del algoritmo muerto. Sus funciones internas (`forzar_n` [:466], `generar_edificio` [:698]) y `fitness.evaluar` ([fitness.py:56](contextos/render_calculos/geometria/fitness.py#L56), accede a un atributo inexistente) son código muerto con bugs latentes.
- `textos_ayuda.py` / `TEXTOS_AYUDA` definido y **nunca importado** ([textos_ayuda.py:15](contextos/render_calculos/textos_ayuda.py#L15)).
- `config.py`: `ancho_portal` declarado y nunca consumido ([:38](contextos/render_calculos/geometria/config.py#L38)); `DEFAULT = Parametros()` singleton mutable sin usos ([:92](contextos/render_calculos/geometria/config.py#L92)).
- Backups con datos reales dentro de `app/data/` (`proyectos_backup_*.json`, `*.bak`) sin código que los genere: mover fuera de `app/`.
- Dependencias de test (pytest, httpx) no declaradas en ningún `requirements`; falta `conftest.py` ([requirements.txt](requirements.txt)).
- Migración SQLite con doble `except Exception: pass` silencia un `ALTER` fallido ([sqlalchemy_base.py:92](plataforma/persistencia/sqlalchemy_base.py#L92)).

### Accesibilidad / UX
- Brújula solo operable con ratón/touch, sin teclado ([rc_brujula.js:87](entrypoints/web/static/js/rc_brujula.js#L87)).
- Canvas del render sin nombre accesible (`role="img"` + `aria-label`) ([render_calculos.html:53](entrypoints/web/templates/render_calculos.html#L53)).
- Roles de solo lectura pueden editar el formulario de viabilidad sin feedback ([viabilidad.js:126](entrypoints/web/static/js/viabilidad.js#L126)).
- Guardar/Exportar sin protección anti-doble-click ni estado de carga ([render_calculos.js:492](entrypoints/web/static/js/render_calculos.js#L492)).
- Listado de carpetas se queda en «Cargando…» si el fetch falla ([normativa_municipal.js:63](entrypoints/web/static/js/normativa_municipal.js#L63)); DELETE muestra éxito sin comprobar `resp.ok` ([:125](entrypoints/web/static/js/normativa_municipal.js#L125)).
- Banner estático «Render gráfico en desarrollo» desactualizado ([render_calculos.html:61](entrypoints/web/templates/render_calculos.html#L61)).
- Numeración de unidades se desplaza cuando hay sótano ([serializacion.py:462](contextos/render_calculos/geometria/serializacion.py#L462)).

### Arranque / configuración
- Host y puerto del arranque hardcodeados ([run.py:37](run.py#L37)): leer `PUCCETTI_HOST`/`PUCCETTI_PORT`.
- Leaflet desde CDN unpkg ([localizacion.html:5](entrypoints/web/templates/localizacion.html#L5)): el módulo depende de internet. Vendorizar.
- `base.html` sin bloque `head`: los CSS de módulo se inyectan dentro de `<body>` ([base.html:7](entrypoints/web/templates/base.html#L7)).

### Comentarios desfasados
- Slugs erróneos en comentarios de `parametros.py:117` y `config.py:74`; docstring de `Alerta` con refs al PDF ([dominio.py:145](contextos/render_calculos/dominio.py#L145)); docstring de `anexo_i_apartamentos` contradice la convención real ([:5](plataforma/persistencia/anexo_i_apartamentos_sqlalchemy.py#L5)).

---

## Orden de ataque recomendado

1. **Catastro (C1, A1–A4 + medias del tema)** — es lo que rompe la app para todo el estudio y choca con tu regla explícita. Empezar por el tope del bulk (C1) y por reconstruir Localización desde el JSON guardado (A1).
2. **Bug de rehabilitación (B1)** — corrompe números de viabilidad en silencio; arreglo de ~3 líneas + 1 test.
3. **Lote de convención UI** — barato, cierra una regla tuya; blindar con el test guardián.
4. **Tests de adapters/rutas + `ValidarCumplimiento` + `calcular_capacidad` (E1–E5)** — la inversión que más reduce el riesgo de regresión; requiere antes el `conftest.py` con `:memory:`.
5. **Migraciones (Alembic, D1)** y **sacar el `×1.15` de persistencia (D2)**.
6. **Higiene del repo** — `.gitignore`, dejar de versionar `.pyc`/`.sqlite`, fijar versiones en `requirements.txt`.

---

## Apéndice

- **Higiene de Git no incluida arriba (conocida):** no hay `.gitignore`; hay **81 archivos `.pyc`/`.sqlite` versionados** (incluida `data/puccetti.sqlite`, que cambia casi en cada commit); `requirements.txt` usa solo `>=` (builds no reproducibles) e incluye `geopandas` (pesada) cuya necesidad conviene confirmar.
- **Cobertura del análisis:** 9 dimensiones (viabilidad/localización/proyectos, núcleo render_calculos, geometría, frontend, persistencia, Catastro, arquitectura, seguridad web, tests) + 3 dimensiones extra del crítico de completitud. 167/168 hallazgos resistieron la verificación adversarial.
- **Estado de la suite:** 57 tests en verde al cierre del análisis (eran 28 al empezar — el WIP de `reparto_unidades` añadió tests durante la sesión).
