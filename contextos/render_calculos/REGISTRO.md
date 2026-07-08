# Registro — módulo Render y cálculos (§2.4 – §2.7)

> Fotografía del estado a 2026-07-06 + reglas vigentes + fórmulas activas + bitácora.
> Documento de memoria: léelo antes de reexplorar el módulo. El detalle exhaustivo
> fichero-a-fichero vive en **README.md** (cadena de cálculo numérico, completa) y
> **RENDER_GEOMETRICO.md** (dibujo de planos: patios hecho, unidades pendiente; tiene
> su propia bitácora larga). Este registro **consolida ambos** en un solo sitio —
> fórmulas y reglas inlineadas para no tener que saltar de fichero— y añade la foto de
> estado + reglas transversales que no viven en ninguno de los dos. Actualiza la
> bitácora (§5) cada vez que se toque este contexto; la fotografía (§3) solo si cambia
> de forma sustancial.

---

## 0. Qué es y dónde vive

- **§2.4** Envolvente edificable · **§2.5** Distribución paramétrica (tipologías/
  dormitorios) · **§2.6** Tabla de superficies · **§2.7** Validación de cumplimiento
  normativo.
- Código: `app/contextos/render_calculos/` (dominio puro: `dominio.py`, `parametros.py`,
  `puertos.py`, `casos_uso.py`) + `geometria/` (motor aislado de FastAPI/SQLAlchemy) +
  `app/entrypoints/web/rutas/render_calculos.py` + `templates/render_calculos*.html` +
  `static/js/{render_calculos,rc_canvas,rc_patios,rc_brujula}.js`.
- Persistencia: sin repositorio propio — parámetros y resultado viven en el aggregate
  `Proyecto.datos_por_modulo[ModuloPuccetti.RENDER_CALCULOS]` (se recalcula siempre,
  igual patrón que `viabilidad`). Los catálogos normativos (Anexo I.1/I.3/I.4/I.5 +
  normativa municipal) sí tienen tablas propias en BBDD.
- **Escenarios (pestañas)** — desde 2026-07-06 cada modo guarda una LISTA de
  escenarios, no un único bloque (ver §1.8).
- **3 usos**: vivienda (Anexo I.5), apartamentos turísticos (Anexo I.3/I.4, Decreto
  194/2010), hotelero (Anexo I.1). **3 modos** de entrada: `obra-nueva` (por defecto) /
  `rehabilitacion` / `inmueble` (auto-derivado solo si en §2.1 se eligió un inmueble
  concreto).

---

## 1. Cómo funciona — cadena de cálculo (numérica, COMPLETA)

```
parcela (polígono UTM, huso dinámico vía _epsg_utm_para_lon)
   │
   ▼
construir_envolvente          envolvente.py
   retranqueos direccionales (fachada ≠ lindero)
   + ocupación máxima por categoría (bisección de buffer)
   + N patios editables (colocar_patios + conformar_patio)
   + ático/sótano opcionales
   │
   ▼
calcular_capacidad            capacidad.py
   recorre cada Planta, aplica el bucket diseño+programa de SU categoría
   │
   ▼
reparto_multi_tipologia_generico   programa_uso.py
   asigna unidades reales por planta (use-agnóstico)
   │
   ▼
aplicar_adaptacion_capacidad   geometria/accesibilidad.py
   agranda/reduce por unidades DB-SUA adaptadas (solo turísticos)
   │
   ▼
tabla_planta / tabla_unidad_desde_capacidad   serializacion.py
   │
   ▼
JSON al frontend  ("edificio": null todavía — ver §3)
```

### 1.1 Envolvente por categoría de planta

Cuatro categorías, cada una con su propio bucket de parámetros. Herencia en cascada si
el JSON del proyecto no especifica el bucket: `tipo ← PB`, `ático ← tipo`,
`sótano ← PB`.

| Categoría | Bucket diseño | Bucket programa | Patio | Local PB |
|---|---|---|---|---|
| PB (primera regular) | `diseno` (`pct_circulacion_pb`) | `programa` | Sí | `pct_local_pb` (0–100 %) |
| Planta tipo | `diseno_tipo` (`pct_circulacion_tipo`) | `programa_tipo` | Sí | No |
| Ático | `diseno_atico` | `programa_tipo` (como tipo) | No | No |
| Sótano | `diseno_sotano` | — | 0 | 0 (`viv = 0`) |

Cada categoría: `muros = pct_muros × construida`; `circulación = pct_circulación ×
construida` (con los `pct_*` de SU bucket); `núcleo = min(nucleo_m2, construida)` — m²
**fijos**, iguales en todas las plantas del edificio.

Ocupación máxima también difiere por categoría: PB/sótano usan
`urbanisticos.ocupacion_maxima_pct`; plantas tipo/ático usan `…_pct_tipo` (hereda de PB
si la clave no viene en el JSON). El recorte es una erosión uniforme de la huella tras
retranqueos, independiente por cada límite.

### 1.2 Reparto multi-tipología (use-agnóstico)

Sobre una lista de `TipologiaUnidadDescriptor(slug, util_objetivo, util_minimo,
util_maximo, n_dorms_label, tipo_unidad, plazas)`, sin saber si la unidad es vivienda,
apartamento o habitación de hotel:

1. Ordenar tipologías por `util_maximo` ascendente (la más pequeña primero).
2. Asignar 1 unidad de cada tipología si cabe en el útil restante
   (consume `min(util_maximo, restante)`).
3. Rellenar el sobrante con la tipología más pequeña mientras quepa su `util_minimo`.

Ejemplo (`util_disponible = 158 m²`, tipologías `[2d, 1d]`):
`1d` consume `min(60,158)=60` → restante 98; `2d` consume `min(70,98)=70` → restante
28; `28 < util_min(1d)=41.4` → para. Resultado: `[(1d,60), (2d,70)]`, residual 28 m².

`Capacidad` guarda dos listas paralelas por planta: `unidades_por_planta`
(`(n_dorms_label, util_m2)`, formato numérico legacy) y
`tipologias_unidad_por_planta` (slug real, para regenerar estancias en plantas
mezcladas).

### 1.3 Escalado de estancias — vivienda (política vigente desde junio 2026)

`programa_vivienda(n_dorms, util_disponible)` reparte de forma que
`Σ area_target_m2 = util_disponible` **exacto** (antes quedaba un "gap invisible": 1d
tenía 42 m² de estancias sobre 60 útiles, 18 m² sin asignar):

1. **Circulación interior** = 15 % del útil (estancia explícita, categoría
   `circulacion`).
2. **Servicios fijos** desde BBDD: cocina = 8 m² · baño = 5 m² (nº de baños: 1 hasta 2
   dormitorios, 2 desde 3 dormitorios — `bano` / `bano_1`+`bano_2`).
3. **Salón + dormitorios** escalan proporcionales a su `area_min_m2` para consumir el
   resto (`util_principal = util − circulación − Σservicios`).

**Verificación aritmética** (suma = útil máximo VPO):

| n_dorms | salón | dorm₁ | dorm₂ | dorm₃ | cocina | baño(s) | circulación | **TOTAL** |
|---|---|---|---|---|---|---|---|---|
| 1d | 20.46 | 17.54 | — | — | 8.00 | 5.00 | 9.00 | **60.00** |
| 2d | 20.67 | 15.50 | 10.33 | — | 8.00 | 5.00 | 10.50 | **70.00** |
| 3d | 22.89 | 15.26 | 10.17 | 10.17 | 8.00 | 5+5 | 13.50 | **90.00** |

**Estudio** (`n_dorms=0`, rediseño completo — salón+cocina+cama en un
`espacio_principal` único): `espacio_principal=18` + `bano=4` + `circulacion=3` = **25
m²** (mínimo VPO). `util_minimo_vivienda(0) = max(25, Σmin × 1.15)` garantiza ≥ 25
siempre.

**Útil mínimo editable por tipología (suelo duro)** — desde 2026-07-08 cada tipología
de vivienda tiene un **útil mínimo editable** (default Estudio 40 · 1d 60 · 2d 70 · 3d
90 · 4d 110 · >4 130) que es un **suelo duro**: el reparto nunca dimensiona una vivienda
por debajo. El **útil máximo es DERIVADO = mínimo + 5** (`MARGEN_UTIL_MAXIMO_VIVIENDA`,
`programa.py`; no es un campo editable, se quitó en su día). El **objetivo por unidad =
el mínimo** (mono-tipología clava cada unidad al mínimo vía `util_objetivo_vivienda`;
las mezclas multi-tipología llenan la última unidad hasta `min+5`). Se edita en «Ver /
editar mínimos» como la fila **«Útil mínimo de la unidad»** por tipología. Persistencia:
columna nueva `anexo_i_vivienda.min_m2_util` (auto-migración idempotente en `init_db`,
sin alembic); consolidadas emite `UTIL_MIN`/`UTIL_MAX`; `ProgramaViviendaConfig.util_min`.
`util_minimo_vivienda` aplica `max(blando calculado, util_min[n])` como piso.

Apartamentos y hotelero **no** aplican este escalado por %: sus estancias salen de
mínimos legales + áreas comunes obligatorias (recepción, sociales, 2º baño >5
usuarios) descontadas del techo de planta — no hay pasillo interno propio por unidad.

### 1.4 Usos y sus Anexos

| Uso | Anexo | Driver de tipología | Construcción `ProgramaUso` |
|---|---|---|---|
| Vivienda | I.5 — VPO Junta Andalucía | nº de dormitorios (0..4) | rama directa (`programa_uso=None`); estancias vía `programa.programa_vivienda` |
| Apartamentos turísticos | I.3 (edificios) / I.4 (conjuntos) — Decreto 194/2010 | categoría 1L–4L × tipología estudio/individual/doble/triple/cuádruple | `programa_apartamentos.programa_uso_apartamento(cat, tip)` |
| Hotelero | I.1 — Hotel 1–5★, Hostal 1–2★, Pensión, Albergue | individual/doble/triple/cuádruple/múltiple (solo albergue) | `programa_hotelero.programa_uso_hotelero(cat, tip)` |

### 1.5 Unidades adaptadas DB-SUA (`geometria/accesibilidad.py`)

Sustituye al antiguo parámetro editable `pct_unidades_adaptadas`. Solo usos turísticos
(`apartamento`, `habitacion`); **vivienda nunca**.

- **Tramos** (`n_unidades_adaptadas(total)`): 1–50 → 1 · 51–100 → 2 · 101–150 → 4 ·
  151–200 → 6 · >200 → `8 + (n-201)//50`.
- **Modo**: `parcial` (1–5 alojamientos: agranda solo dormitorio/habitación + baño/aseo)
  vs `total` (≥6: agranda toda la unidad salvo la circulación de acceso).
- **Factor de agrandado** (único punto de ajuste, `FACTOR_AGRANDADO_POR_TIPO`):
  apartamento **×1.25**, habitación **×1.30**.
- Las adaptadas **reducen la capacidad** (ocupan más → caben menos unidades). La
  dependencia circular (nº adaptadas ↔ nº total final tras agrandar) se resuelve por
  **punto fijo sobre el área edificable** (máx. 12 iteraciones; en oscilación de
  frontera se toma el k **menor** — criterio del arquitecto: un edificio que ofrece
  ~50 alojamientos lleva las adaptadas de ~50, no de 51).
- `_repack_adaptadas`: coloca las adaptadas en las plantas más bajas primero
  (PB→P1→…, acceso sin ascensor); agranda sus primeras unidades y retira estándar (las
  últimas) hasta que la planta quepa; `util_por_planta` (footprint) no cambia.

### 1.6 Validador de círculo inscrito en estancias

`_cabe_diametro(nombre, area)` (`serializacion.py`): aproximación rectángulo 1:1.5 →
`lado_menor = √(area/1.5)`; cabe si `lado_menor ≥ diámetro_min` (CTE DB-SUA + Anexo I).

Diámetros mínimos (`_DIAMETROS_MIN_M`): salón **3.00** · dorm₁ **2.70** · dorm₂
**2.40** · cocina **1.60** · baño **1.20** · circulación **1.00** · espacio_principal
**3.00**. El frontend pinta un ⚠ rojo junto a la estancia que no cumple, en el modal
de detalle de unidad.

### 1.7 Validación de cumplimiento (`ValidarCumplimiento.ejecutar`, `casos_uso.py:1087`)

Compara el proyecto contra la normativa municipal archivada **activa** (o la
`normativa_referencia.urbanisticos` guardada en el proyecto, que el backend prioriza
sobre la BBDD). Coeficiente de edificabilidad: solo se contrasta si el proyecto
**dimensiona por coeficiente** (`usar_coeficiente_edificabilidad`); si lo desmarca, el
techo lo vigila `_alertas_envolvente` por ocupación×plantas (evita duplicar el aviso).

- **SUPERIORES** (proyecto > normativa → `incumplimiento`): ocupación máxima PB,
  ocupación máxima plantas tipo, nº plantas máximas, Ø vestíbulo, espesor muro
  medianero, espesor separación unidades, % muros.
- **INFERIORES** (proyecto < normativa → `aviso`): retranqueo fachada, retranqueo
  linderos, retranqueo ático, luz recta de patio, área patio mínima, ancho total de
  fachada, espesor de tabique, ancho de pasillo común, ancho de puerta (paso libre).

### 1.8 Escenarios (pestañas) — hipótesis de programa por parcela

Desde 2026-07-06, encima de la barra catastral hay una barra de **pestañas**: cada
una es un **escenario** (hipótesis de programa completa — uso + parámetros +
resumen) sobre la MISMA parcela, con **nombre reactivo** al programa elegido
("Vivienda · 2 habitaciones", "Apartamento 2L · Edificio · 3 dorm.", "Hotel 3★ ·
Doble"). Preparado para una futura funcionalidad de **«informes del activo»** (aún
NO desarrollada).

- **Las pestañas son POR MODO**: cada modo (obra-nueva/rehabilitación/inmueble)
  tiene su propio juego de escenarios; no se comparan entre sí en la misma barra.
- **Persistencia**: cada `modo_key` de `datos_por_modulo[RENDER_CALCULOS]` pasa de
  un bloque plano (`{parametros, resumen_ultimo_calculo, timestamp}`) a un
  contenedor `{escenarios:[{id, nombre, parametros, resumen_ultimo_calculo,
  timestamp}], activo}`. **Migración perezosa**: el formato antiguo se envuelve
  como un único escenario `e1` al leer (`_normalizar_escenarios`,
  `casos_uso.py`); no se reescribe hasta el siguiente guardado.
- **Fuente de verdad = el cliente**: el frontend manda la lista completa de
  escenarios en cada `POST /escenarios`; el backend valida/sanea (round-trip por
  `parametros_desde_dict`/`parametros_a_dict`) y reemplaza el contenedor del modo,
  conservando los demás modos y `normativa_aplicada`.
  `GuardarEscenariosRender` (sustituye a `GuardarRender`, que ya no existe).
- **Conmutar/crear/borrar = persistir + recargar** con `?escenario=<id>` (el `GET`
  de `pantalla` renderiza ESE escenario vía `parametros_desde_proyecto(...,
  escenario_id=...)`): se evita reconstruir el formulario completo en cliente (los
  patios dinámicos lo harían frágil) y garantiza que nada se pierde al cambiar de
  pestaña. No se permite borrar el último escenario de un modo.
- **Nombre reactivo**: se recompone en JS (`nombreEscenario()`,
  `render_calculos.js`) a partir del TEXTO de los `<option>` ya existentes en el
  panel (categoría por llaves 1L–4L, grupo edificio/conjunto, categoría hotelera
  con ★, tipología de habitación) — sin duplicar mapas de etiquetas.
- **Endpoint**: `POST /modulos/render-calculos/escenarios` (antes `/guardar`, que
  ya no existe); `GET ''` acepta `?escenario=<id>` para previsualizar una pestaña
  sin persistir. Tope anti-DoS: `_ESCENARIOS_MAX = 24` por modo.
- Detalle de decisiones (incl. por qué "XL" del brief inicial = categoría de
  llaves) en memoria persistente `project_pestanas_escenarios_render`.

---

## 2. Reglas vigentes (transversales — no romper sin decisión del arquitecto)

- **§3.8 — sin globals**: cada cálculo construye un `Programa*Config` inmutable desde
  BBDD (`CalcularLayout._sincronizar_minimos` + `config_desde_repo`) y lo pasa como
  argumento por toda la cadena de cálculo; las constantes de módulo son solo
  `CONFIG_DEFAULT`. Cálculos concurrentes y tests quedan aislados; nada de estado
  compartido mutable.
- **Edificabilidad solo AVISA**: superar el techo no retira unidades — todas las
  plantas habitables reparten igual (decisión explícita, no un bug).
- **Circulación común y núcleo son del EDIFICIO**, nunca de la unidad: solo aparecen
  en la tabla por planta. Únicamente los muros perimetrales se prorratean por unidad
  (proporcional al útil).
- **Vivienda nunca tiene unidades adaptadas** (solo apartamentos/hotel, §1.5).
- **`NivelAlerta`** (dominio, `Literal`) = EXACTAMENTE `error > incumplimiento > aviso
  > info`; debe casar con `NIVEL_PESO` en `render_calculos.js`.
- **Avisos UI sin referencias normativas**: prohibido citar "Anexo I/II", "DB SUA",
  "Decreto 194/2010", "§x.x", "PGOU" en los mensajes — identificador unificado
  **"Normativa"** (regla transversal a toda la app, no solo este módulo).
- **Colores corporativos** (UI y canvas): negro `#0A0A0A`, dorado `#B8960C`/`#C9A84C`,
  blanco `#FFFFFF`, error `#8C2A1F`. Única excepción documentada: azul `#2D6CDF` para
  la ventanita de fusión de patios (pedida explícitamente por el arquitecto).
- **Cache-busting automático**: el `?v=` de CSS/JS deriva del mtime más reciente de
  `static/` (`plantillas.py::estaticos_version`), reevaluado en cada render — no se
  sube versión a mano al tocar estáticos.
- **`N_PLANTAS_LIMITE = 60`** — cota anti-DoS en el parser de `parametros.py`.
- **Coordenadas UTM crudas**: motor y canvas trabajan en metros UTM (números
  grandes); el canvas no traslada al origen en `_x/_y` (la traslación vive en
  `origenX/origenY`); eje Y **invertido** en pantalla (`_y = origenY − y·scale`).
- **`render_calculos` duplica a propósito** el cálculo de huso UTM de `localizacion`
  (`_epsg_utm_para_lon`) — regla nuclear de independencia entre contextos (no
  deduplicar, ver `app/CLAUDE.md`).
- **Patios** (motor + editor, ya integrado): N patios independientes y editables;
  **prioridad por orden de lista** (cada uno cede solo ante los ANTERIORES, no
  exclusión mutua); al soltar, relleno **LOCAL anclado** (`hi_max=2·√área` +
  `_pieza_anclada`, nunca teletransporte a otra zona); **bloqueo** (`bloqueado=True`)
  da prioridad máxima y congela toda interacción; **fusión** de patios a ≤0.1 m
  conserva ambas formas unidas por un cuello fino vía `shapely` (no envolvente
  convexa: deformaba); edición **en sitio** (doble-clic sobre arista inserta vértice,
  clic derecho sobre vértice lo borra si quedan ≥3) **nunca** reordena ni recalcula —
  solo el arrastre deliberado (≥`COMMIT_PX`) mueve el patio a última prioridad y
  dispara el recálculo del backend.
- **Escenarios (pestañas, §1.8)**: el contenedor `{escenarios, activo}` es POR MODO,
  nunca cruza modos; `GuardarRender`/`/guardar` **ya no existen** (sustituidos por
  `GuardarEscenariosRender`/`POST /escenarios`) — cualquier referencia a ellos en
  código o docs antiguos está obsoleta.

---

## 3. Foto de estado — rama actual `pestañas-proyectos` (verificado 2026-07-06)

| Capa | Estado |
|---|---|
| Envolvente (huella, retranqueos, ocupación, patios, ático/sótano) | **COMPLETO** |
| Capacidad numérica (nº unidades, m² por planta, multi-tipología) | **COMPLETO** — fuente de verdad |
| Reparto de m² de estancias (área objetivo por estancia) | **COMPLETO** (solo áreas, sin polígonos) |
| Adaptación DB-SUA | **COMPLETO** |
| Validación de cumplimiento normativo | **COMPLETO** |
| Tablas por planta / por unidad | **COMPLETO** |
| Patios: N editables, base/efectiva, prioridad, bloqueo, fusión, zoom, edición en sitio | **COMPLETO** (trabajo de `render-dev`, ya integrado en `dev`→`pre`→esta rama) |
| Escenarios (pestañas): alta/baja/conmutación, nombre reactivo, persistencia por modo (§1.8) | **COMPLETO** (2026-07-06) |
| **Disposición geométrica de UNIDADES en planta** (rebanadas, núcleo, pasillos) | **NO EXISTE** — `"edificio": None` explícito en `CalcularLayout`/`CalcularEnvolvente` (`casos_uso.py`, comentario "render geométrico en backlog") |
| **Geometría de estancias dentro de la unidad** (polígonos por estancia) | **NO EXISTE** |
| Canvas: dibujo de unidades/núcleo/pasillos | Código YA escrito en `rc_canvas.js` (`_dibujarNucleo`, `_etiquetaUnidad`), **inerte** a la espera del contrato `edificio` |
| Botón «Pintar render» (`#rc-btn-distribuir`) | presente en `render_calculos.html`, **disabled**, sin handler |

> ⚠️ **Nota de ramas** (para no confundir memoria antigua con el árbol real): la
> memoria persistente del proyecto describe motores de disposición de unidades ya
> construidos en OTRAS ramas — bloque compacto (`render-dev`, `geometria/
> disposicion.py`), zonificación (`geometria/zonas.py`) y rejilla+CP-SAT
> (`layout-cpsat`, `geometria/reparto_cpsat.py`). **Ninguno de esos ficheros existe
> en `pestañas-proyectos`** (solo quedan `.pyc` sueltos en `__pycache__` de cuando se
> cambió de rama; no hay `.py` fuente). Antes de dar por resuelto el render
> geométrico de unidades, comprobar `git -C app branch` y en qué rama se está
> trabajando realmente — hoy, en `pestañas-proyectos` (hija de `pre`, base común
> `9d37100`), el estado real es el de la tabla de arriba: solo patios, no unidades.

**Tests**: específicos de este contexto en `app/tests/contextos/render_calculos/`
(dominio/geometría, incl. `test_escenarios.py`, `test_util_minimo_tipologia.py`) ·
**334** en total la suite del repo (`python -m pytest app/tests --collect-only -q`).
Desde 2026-07-06 SÍ hay tests de ruta HTTP para `render_calculos`
(`app/tests/entrypoints/web/test_render_calculos_rutas.py`, escenarios: página +
roundtrip `POST /escenarios` + permisos) — cierra el hueco que este registro
señalaba antes (ya alineado con `viabilidad`, `test_viabilidad_rutas.py`).

---

## 4. Qué NO hay todavía (gaps conocidos)

- **Dibujo geométrico de unidades y estancias** (§3 arriba) — el trabajo grande
  pendiente. Contrato JSON propuesto (campo `edificio.plantas[].{pasillos,nucleo,
  unidades}`) y plan de integración ya escritos en `RENDER_GEOMETRICO.md` §3–4;
  preguntas abiertas sin decidir en su §8 (qué algoritmo de disposición — rebanado
  simple vs adaptar el de una rama antigua vs CP-SAT —, si se dibujan también las
  estancias dentro de cada unidad, si el modo `inmueble` también dibuja reparto).
- **Interior fiel para apartamentos/hotel**: las áreas comunes obligatorias
  (recepción, sociales) solo restan m² del techo de planta, sin geometría propia.
- **`hueco_disp_m2` real por unidad**: el % de huecos del indicador de diseño está
  fijo en 0.25; hay código muerto en `casos_uso.py::_indicadores_disenho` que ya
  espera ese campo por unidad para calcularlo de verdad.
- **Pantalla de edición de mínimos Anexo I** (I.1/I.3/I.4) — solo Normativa Municipal
  tiene CRUD hoy; los Anexo I se protegen con `editable_por_usuario` pero sin panel
  propio (sí lo tiene el vivienda I.5 vía `/superficies-vivienda` y `/minimos/{uso}`).
- **Validación geométrica de que las unidades quepan físicamente** (ancho/
  profundidad): el reparto actual trunca solo por área total, no por forma.
- **Financiación/edición en caliente de patrones de disposición**: no aplica todavía
  porque la disposición de unidades no existe (ver punto 1).

---

## 5. Bitácora

- **2026-07-08 (2)** — **Parametrización en m² (en vez de %) de circulación común,
  reservas de PB y circulación interior por tipología.** (a) Panel: `pct_circulacion_pb/
  tipo` → `circulacion_pb_m2`/`circulacion_tipo_m2` (m² por planta, acotados a la huella,
  patrón del núcleo); `pct_local_pb`/`pct_otros_pb`/`pct_usos_comunes_pb` → `local_pb_m2`/
  `otros_pb_m2`/`usos_comunes_pb_m2` (m² en PB, descuento secuencial acotado). **`% muros`
  se mantiene en %.** (b) La circulación interior sale del panel (`pct_circulacion_interior`
  eliminado) y pasa a un **m² mínimo por tipología** editable en «Ver / editar mínimos»
  (estancia `circulacion_interior`) en los **3 usos**. El útil objetivo/mínimo de la unidad
  pasa de `×(1+%)` a `+ circ_m2` (aditivo). Se implementó `util_objetivo_vivienda` ya en la
  sesión previa; ahora las tres tablas Anexo I siembran `circulacion_interior` por tipología
  y `consolidadas_*` emiten `CIRC_INTERIOR_M2`. Cambios: `parametros.py`, `geometria/config.py`,
  `geometria/capacidad.py` (`DisenoPlanta.circulacion_m2`, aplicación m², KPIs renombrados),
  `geometria/programa*.py` (config `circ_interior_m2`, sizing aditivo, quitado
  `pct_circulacion_interior`), `geometria/serializacion.py` (circulación turística por m²),
  `casos_uso.py` (`_disenos_por_categoria`, `_sincronizar_minimos` sin el %), los 3 adapters +
  `seed_normativa.py` + `etiquetas_anexo.py`. Seeds turístico/hotelero ahora **idempotentes
  add-missing** (las filas nuevas aparecen sin reset). Defaults orientativos: circulación
  común 10 m²/planta; circ. interior vivienda 3/9/10/13/16/19, apt 5–8, hotel 4–8. Tests
  nuevos: `test_parametros_m2.py`, `test_circ_interior_tipologia.py`, `test_circ_interior_editor.py`.
  ⚠️ Escenarios guardados con los `pct_*` viejos NO son convertibles a m² (arrancan en los
  defaults nuevos).
- **2026-07-08 (1)** — **Útil mínimo editable por tipología (vivienda) + máximo derivado
  = mínimo + 5.** Nueva fila **«Útil mínimo de la unidad»** por tipología en «Ver /
  editar mínimos» (default 40/60/70/90/110/130); suelo duro en el cálculo (ninguna
  vivienda baja de él; las estancias se reparten hasta completarlo). El útil máximo se
  reintroduce **derivado** = mínimo + `MARGEN_UTIL_MAXIMO_VIVIENDA` (5.0), no editable;
  el objetivo por unidad = el mínimo (implementado `util_objetivo_vivienda`, cierra
  Pendiente 3.9). Cambios: `geometria/programa.py` (`MARGEN_UTIL_MAXIMO_VIVIENDA`,
  `ProgramaViviendaConfig.util_min`, `util_minimo_tipologia`, suelo en
  `util_minimo_vivienda(_combo)`, objetivo/máximo en `descriptor_tipologia_vivienda(_combo)`,
  mapeo `UTIL_MIN` en `config_desde_repo`); `plataforma/persistencia/
  catalogo_superficies_sqlalchemy.py` (columna `min_m2_util`, sentinela `_util_minimo`,
  `util_minimo_por_tipologia`, `util_objetivo_vivienda`, fila sintética en
  `filas_vivienda`, `UTIL_MIN` en `consolidadas_vivienda`, rama en `actualizar` con
  máximo=mín+5); `seed_normativa.py` (min=base, max=base+5); `sqlalchemy_base.py`
  (auto-migración idempotente `_asegurar_columna_min_util`, sin alembic);
  `render_calculos.js` + `render_calculos.css` (realce de la fila). Tests nuevos:
  `test_util_minimo_tipologia.py`, `test_catalogo_superficies_util_minimo.py` + 2 de
  ruta en `test_render_calculos_rutas.py`. Suite **334** verde.
- **2026-07-06 (2)** — Implementadas las **pestañas de escenario** (§1.8): barra de
  escenarios encima de la catastral, nombre reactivo, persistencia por-modo
  `{escenarios, activo}` con migración perezosa del formato antiguo. Cambios:
  `casos_uso.py` (`GuardarEscenariosRender`, `contenedor_escenarios_proyecto`,
  `_normalizar_escenarios`, `parametros_desde_proyecto(escenario_id=...)`, sustituye
  a `GuardarRender`); `rutas/render_calculos.py` (`POST /escenarios` sustituye a
  `/guardar`, `GET ?escenario=`); `templates/render_calculos.html`
  (`#rc-escenarios` junto con `window.__RC_ESCENARIOS__`/`__RC_ESCENARIO_ACTIVO__`);
  `render_calculos.js` (`nombreEscenario`, `dibujarTabsEscenarios`,
  `cambiarEscenario`/`crearEscenario`/`borrarEscenario`); `render_calculos.css`
  (`.rc-esc-*`). Tests nuevos:
  `test_escenarios.py` (dominio/migración) y `test_render_calculos_rutas.py`
  (primeros tests de ruta HTTP del contexto). Detalle de decisiones en memoria
  persistente `project_pestanas_escenarios_render`.
- **2026-07-06 (1)** — Creado este registro (lectura de README.md, RENDER_GEOMETRICO.md,
  `dominio.py`, `casos_uso.py`, `accesibilidad.py`, `parametros.py` + verificación de
  rama activa y recuento de tests). Sin cambios de código. Rama activa:
  `pestañas-proyectos` (hija de `pre`, commit base `9d37100`). Para la evolución
  detallada fichero-a-fichero y las bitácoras completas de cada pieza, ver
  **README.md** (cálculo numérico) y **RENDER_GEOMETRICO.md** (patios + plan de
  disposición de unidades; bitácora propia hasta 2026-06-30).
