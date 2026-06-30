# Render geométrico de unidades — mapa de trabajo (§2.5 dibujo)

> **Para qué es este archivo.** Documento vivo del trabajo de **dibujar los planos
> del edificio**: distribuir geométricamente las unidades en cada planta y repartir
> los m² de las estancias **como polígonos** (no solo como tabla). El objetivo es no
> tener que releer el módulo entero cada sesión. El README.md de al lado documenta la
> cadena de **cálculo numérico** (que ya existe); esto documenta la capa de **dibujo**
> (que está por construir) y su contrato.
>
> Rama de origen del trabajo: **`render-dev`** · ya **integrado en `dev` → `pre` → `main`**
> (2026-06-29/30; squash en `dev`: «Render de patios implementado», «Cambio de frontend»,
> «Funcion de bloqueo y union de los patios»). Baseline al abrir el trabajo: **157** tests ·
> hoy: **182** (`python -m pytest app/tests -q`). Mantén este archivo al día (hay una bitácora al final).

---

## 1. Estado de un vistazo

| Capa | Qué hay hoy | Estado |
|---|---|---|
| Envolvente (huella por planta) | `geometria/envolvente.py` → `Planta.footprint` + `Planta.interior` (Polygon UTM), patios, ático/sótano | **HECHO**, se dibuja en canvas |
| Capacidad numérica | `geometria/capacidad.py` → nº unidades, m² por planta, `unidades_por_planta`, `tipologias_unidad_por_planta` | **HECHO** (fuente de verdad) |
| Reparto de m² de estancias | `geometria/programa*.py` → `list[Estancia]` con **área objetivo** por estancia | **HECHO** (solo áreas, sin posición) |
| Tablas por planta / por unidad | `geometria/serializacion.py` → tablas sintéticas desde capacidad | **HECHO** |
| **Disposición geométrica de unidades en planta** (rebanadas, núcleo, portal, pasillos) | — | **NO EXISTE → es el trabajo** |
| **Geometría de estancias dentro de la unidad** (polígonos por estancia) | — | **NO EXISTE → es el trabajo** |
| Dibujo en canvas de unidades/núcleo/pasillos | `rc_canvas.js` ya tiene el código (`_dibujarNucleo`, `_etiquetaUnidad`, bloque unidades) | **HECHO pero INERTE** (espera el contrato) |

**Resumen:** existe el *qué* numérico (cuántas unidades, de qué slug, cuántos m² útiles,
qué estancias y de qué área). Falta el *dónde* geométrico (colocar esos m² en polígonos
dentro de la huella). El canvas ya sabe pintar el resultado; falta **producir el dato**.

### El campo `edificio` es el hueco exacto
`CalcularLayout.ejecutar` y `CalcularEnvolvente.ejecutar` devuelven **`"edificio": None`**
de forma explícita (`casos_uso.py:488`, y en las ramas de error `:404`/`:424`), con el
comentario `# render geométrico en backlog`. **Rellenar ese campo es el trabajo.**

> ⚠️ Las memorias antiguas mencionan `reparto_unidades.py`, `macro_layout.py`,
> `interiores.py` con un algoritmo ya hecho (núcleo+portal+pasillos+rebanadas). **Esos
> ficheros NO existen en `render-dev`** — vivían en `auto-render-dev`/`pre-iter-5`. El
> punto de partida aquí es greenfield geométrico sobre `Planta.interior`. (El algoritmo
> de esa rama puede servir de inspiración, pero no está en este árbol.)

---

## 2. Lo que YA produce el backend (input disponible para el reparto)

Todo esto existe y es correcto; es la materia prima del dibujo:

- **`Planta.interior: Polygon` (UTM)** — huella útil de la planta **ya descontado** el
  muro de fachada (buffer negativo de `espesor_muro_fachada`) y los patios. Es el polígono
  que hay que **subdividir** en unidades. (`Planta.footprint` = huella construida bruta.)
- **`Planta.patios: list[Patio]`** — patios ya colocados. `Patio`: `geometry` (efectiva dibujada,
  adaptada al borde), `base` (forma ideal del usuario), `area_m2` (asignada), `luz_recta_m`, `id`,
  `area_efectiva_m2`, `cabe`.
- **`LadoParcela[]`** — cada lado clasificado `fachada`/`medianera` + `normal_azimut`
  (hacia dónde mira). Clave para orientar las unidades hacia fachada y pegar el núcleo a
  medianera. **Sin parcelas vecinas, TODOS los lados salen `fachada`** (limitación conocida).
- **`Capacidad.unidades_por_planta: list[list[tuple[int, float]]]`** — por planta, **una
  tupla `(n_dorms_label, util_m2)` por unidad real**. Esto dicta cuántas rebanadas y de
  qué m² objetivo. La disposición **no debe crear ni borrar unidades**: dibuja exactamente
  estas (criterio del estudio en la rama antigua; conservar como invariante).
- **`Capacidad.tipologias_unidad_por_planta: list[list[str]]`** — slug de tipología paralelo
  (para regenerar las estancias correctas de cada unidad en plantas mezcladas).
- **`Capacidad.{nucleo,circulacion,muros,...}_por_planta`** — m² objetivo de núcleo,
  circulación común, etc. por planta (cuánto espacio reservar a cada elemento).
- **`programa_vivienda/_apartamentos/programa_habitacion(...)` → `list[Estancia]`** — el
  reparto de m² de estancias de UNA unidad (área objetivo por estancia). Es lo que habría
  que **posicionar** dentro del polígono de cada unidad.

---

## 3. El contrato `edificio` que el canvas YA sabe pintar (el objetivo)

`rc_canvas.js::RenderCanvas.dibujar(payload, indicePlanta)` lee la planta activa de
`payload.edificio.plantas[idx]` (preferente) o `payload.envolvente.plantas[idx]` (fallback
actual). **Ambos caminos usan el MISMO esquema de planta.** Rellenar estos campos basta para
que se dibuje (el canvas no necesita cambios para lo básico):

```jsonc
{
  "edificio": {
    "parcela": { "poligono": [[x,y],...], "bbox": [minx,miny,maxx,maxy] },   // opcional; cae a payload.parcela
    "plantas": [
      {
        "footprint": [[x,y],...],            // anillo UTM (ya lo da la envolvente)
        "patios":   [ { "id", "poligono": [[x,y],...] (efectiva), "base": [[x,y],...] (ideal),
                        "area_m2", "area_efectiva_m2", "cabe", "luz_recta_m" }, ... ],
        "pasillos": [ { "poligono": [[x,y],...] }, ... ],   // ← NUEVO
        "nucleo": {                                          // ← NUEVO (opcional por planta)
          "poligono":      [[x,y],...],
          "escalera":      [[x,y],...],
          "ascensor":      [[x,y],...],     // se dibuja una X con 4 vértices ordenados
          "circulo_libre": { "cx": x, "cy": y, "r": 0.75, "cumple": true }   // Ø1,50 → verde/rojo
        },
        "unidades": [                                        // ← NUEVO (el reparto)
          {
            "id": "V1A",
            "poligono_construido": [[x,y],...],   // rebanada con muros
            "poligono_util":       [[x,y],...],   // rebanada útil (centroide = etiqueta)
            "area_util_m2": 60.0,
            "cumple_minimos": true,               // rojo si false
            "es_adaptada": false                  // borde discontinuo si true + etiqueta "adapt."
          }
        ]
      }
    ]
  }
}
```

Notas del consumo en el canvas (verificadas en `rc_canvas.js`):
- `_etiquetaUnidad` usa `poligono_util || poligono_construido`, pinta `id` + `area_util_m2`
  (formato es-ES, coma decimal). Asume `area_util_m2` definido (`toFixed` sin guard).
- `_dibujarNucleo` dibuja `poligono`, `escalera`, `ascensor` (X con 4 vértices) y
  `circulo_libre` (arco Ø, verde si `cumple`, rojo si no).
- `payload.lados[]` (`{p1,p2,tipo,orientacion}`) se dibuja **siempre** al final, ya exista o no `edificio`.
- `indicadores.orientaciones_fachadas[]` alimenta la brújula.
- **Código muerto revelador**: `_indicadores_disenho` (casos_uso.py:~1456) tiene una rama
  `if edificio is not None and edificio.plantas:` que espera `u.hueco_disp_m2` por unidad
  para calcular el % de huecos real. Hoy nunca se ejecuta (% huecos fijo 0.25). Sugiere que
  el objeto unidad podría llevar también `hueco_disp_m2` (superficie de huecos a fachada).

> Antes de cablear, **verifica los nombres de clave** que ya emite
> `_plantas_envolvente_a_dict` (casos_uso.py:307) para `footprint`/`patios` y reusa los
> mismos en `edificio.plantas` para no bifurcar el contrato.

---

## 4. Dónde encaja el código nuevo (plan de integración)

1. **Motor de disposición — nuevo módulo** `geometria/reparto_geometrico.py` (nombre a
   elegir; aislado de FastAPI/SQLAlchemy como el resto de `geometria/`). Entrada sugerida:
   `Planta.interior` + `LadoParcela[]` + la lista de unidades de esa planta
   (`unidades_por_planta[i]` + `tipologias_unidad_por_planta[i]`) + m² de núcleo/circulación.
   Salida: dataclasses `EdificioDispuesto`/`PlantaDispuesta`/`UnidadDispuesta`/`Nucleo`
   con polígonos shapely (UTM).
2. **Serialización** — añadir `edificio_a_dict(...)` en `geometria/serializacion.py`
   (usa `ring()` para cada polígono), produciendo el contrato de la §3.
3. **Orquestación** — en `casos_uso.CalcularLayout.ejecutar`, tras `calcular_capacidad` +
   `aplicar_adaptacion_capacidad`, llamar al motor y **sustituir `"edificio": None` por el
   dict serializado**. Capturar excepciones geométricas estrechas (`ValueError`,
   `GEOSException`) → `edificio: null` + alerta, sin tumbar los números (patrón de la rama
   antigua; un `TypeError` no se debe silenciar).
4. **Frontend** — el canvas ya pinta. Activar el botón **«Pintar render»**
   (`#rc-btn-distribuir`, hoy `disabled` sin handler en `render_calculos.js`) si se quiere
   un disparo explícito; o seguir el recálculo automático por debounce. El cache-busting (`?v=`)
   es **automático** (mtime de `static/`): no hay que tocar nada al editar `rc_canvas.js`/JS/CSS.
5. **Tests** — batería nueva de geometría: cardinalidad invariante (dibuja exactamente
   `len(unidades_por_planta[i])`), unidades dentro de `interior`, núcleo entero (no recortado),
   patios respetados, suma de áreas dibujadas ≈ tabla §2.7. **No hay ningún test de geometría
   de dibujo hoy** (los 157 son numéricos/normativos).

---

## 5. Inventario real del módulo (rama `render-dev`)

### `geometria/` (motor, aislado de web/ORM)
| Fichero | Líneas | Rol |
|---|---:|---|
| `envolvente.py` | ~530 | **Huella por planta** (PB/tipo/ático/sótano) en UTM: retranqueos direccionales, ocupación máx. por categoría (bisección de buffer), interior (huella−muro). Patios: `colocar_patios` (N patios; **prioridad por orden de lista**: cada patio cede solo ante los ANTERIORES, no exclusión mutua) + `conformar_patio`/`_inflar_a_area` (**relleno LOCAL anclado**: `hi_max=2·√área` + `_pieza_anclada`, sin teletransporte) + `_ajustar_area` (área fija). `Planta`, `Patio{base,cabe,area_efectiva_m2}`, `Envolvente`, `construir_envolvente`. |
| `parcelas.py` | 144 | Clasifica lados `fachada`/`medianera` (sondeo a vecinas; sin vecinas→todo fachada), azimut, orientación cardinal, normal exterior. `LadoParcela`, `clasificar_lados`. |
| `config.py` | 93 | Dataclasses de parámetros del motor: `ParametrosDiseno`/`Urbanisticos`/`Programa`/`Parametros`. |
| `capacidad.py` | 652 | **Fuente de verdad numérica**: `Capacidad` (~50 campos), `calcular_capacidad`, reparto por planta (`_reparto_planta`), factor limitante, `capacidad_a_dict`. Sin geometría. |
| `programa.py` | 693 | Reparto de m² en estancias de **vivienda** (Anexo I.5): `Estancia` (compartida), `programa_vivienda(_combo)`, `ProgramaViviendaConfig`, `config_desde_repo`. |
| `programa_uso.py` | 104 | Descriptores cross-uso: `ProgramaUso`, `TipologiaUnidadDescriptor`, `reparto_multi_tipologia_generico` (cuántas unidades caben por planta). |
| `programa_apartamentos.py` | 521 | Apartamentos turísticos (Decreto 194/2010, I.3 edificios / I.4 conjuntos): mínimos por categoría 1L–4L, `programa_apartamentos(_combo)`, áreas comunes. |
| `programa_hotelero.py` | 237 | Hotelero (I.1): la **habitación** es la unidad; `programa_habitacion`, áreas sociales del establecimiento. |
| `combinador_tipologias.py` | 139 | **(no está en el árbol del README)** Combina ocupaciones de N dormitorios (§2.5): `ComboDormitorios`, `enumerar_combinaciones`, codec de slug canónico. Puro. |
| `accesibilidad.py` | 194 | **(no está en el árbol del README)** Unidades adaptadas DB-SUA por tramos (sustituye `pct_unidades_adaptadas`): `aplicar_adaptacion_capacidad`, `_repack_adaptadas`. Solo usos turísticos; vivienda nunca. |
| `serializacion.py` | 484 | Contrato JSON: `ring`, `lados_a_dict`, `tabla_planta/unidad_desde_capacidad`, `_estancias_por_unidad_dorms`, `_nivel_diametro`. **`edificio` no se serializa aquí todavía.** |

### Capa hexagonal del contexto
| Fichero | Líneas | Rol |
|---|---:|---|
| `dominio.py` | 166 | Enums (`UsoEdificio`, categorías/tipologías por uso), `NivelAlerta` (`error/incumplimiento/aviso/info`, debe casar con `NIVEL_PESO` del JS), `Alerta`, `IndicadoresDiseno`, `ResumenEnvolvente`. |
| `parametros.py` | 571 | `ParametrosRender` (4 buckets diseño PB/tipo/ático/sótano + 2 programa) → traducción al motor (`a_parametros_motor[_tipo]`), parser JSON tolerante, herencia tipo←pb / atico←tipo / sotano←pb. `N_PLANTAS_LIMITE=60`. |
| `puertos.py` | 115 | 4 puertos `Protocol`: `NormativaMunicipalRepositorio` + catálogos vivienda/apartamentos/hotelero. |
| `casos_uso.py` | ~1390 | **Orquestación**: `CalcularEnvolvente`, `CalcularLayout` (central, devuelve `edificio:None`), `CalcularTipologiasDormitorios`, `CalcularEstanciasInmueble`, `ValidarCumplimiento`, `GuardarRender` + parcela métrica (huso UTM dinámico) + rehabilitación. La serialización de `parcela` expone `area_m2` (catastral/`sup_ref`, gobierna edificabilidad/ocupación) **y** `area_geometrica_m2` (área REAL del polígono, la que ve el KPI «Superficie del polígono»). |

### Web
| Fichero | Líneas | Rol |
|---|---:|---|
| `entrypoints/web/rutas/render_calculos.py` | 827 | Router `/modulos/render-calculos`: `/preview`, `/calcular`, `/estancias`, `/tipologias-dormitorios`, `/guardar`, `/aplicar-normativa`, `/normativa…`, `/superficies-vivienda…`, `/minimos/{uso}…`, `/export.csv`. Permisos por endpoint. |
| `entrypoints/web/render_modos.py` | 110 | 3 modos `obra-nueva`/`rehabilitacion`/`inmueble` (`ModoRender`, `MODOS`, `MODO_POR_DEFECTO`). `inmueble` se auto-deriva si §2.1 eligió un inmueble. |
| `templates/render_calculos.html` | 262 | Pantalla principal: hero (botón «Pintar render» **disabled**), barra catastral, form 3 columnas, `<canvas id="rc-canvas">`, 6 modales. |
| `templates/render_calculos_landing.html` | 327 | Selección de modo + preview parcela + modal de normativa obligatoria. |
| `templates/_rc_panel_params.html` | 432 | Panel izquierdo de parámetros (`data-bloque` × `data-cuando-uso` × `data-visible-en-planta`). Macros `tip_bloque`, `dnum`. |
| `templates/_rc_modal_*.html` | — | unidad (60), tipologias (37), superficies (22), minimos (24), normativa (71), exceso (27). |
| `static/js/rc_canvas.js` | ~390 | **Render 2D**: `RenderCanvas`. Dibuja parcela/footprint/patios/lados/orientación **y** (cuando lleguen) unidades/núcleo/pasillos. UTM→pantalla, Y invertida, rotación de brújula. Inversas `_pantallaAMundo`/`_mundoAPantalla` + `setOverlay`/`repintar`. **Zoom Ctrl+rueda al cursor** (`zoomEn`/`resetVista` + listener de rueda; vista persistente entre repintados mientras la bbox no cambie; 1×–12×). |
| `static/js/rc_patios.js` | ~500 | **Editor de patios**: `PatioEditor`. Mover/estirar/girar/reformar de cada patio (área fija); sin bloqueo (puede salir y el backend lo adapta al borde al soltar). **Edita la forma EFECTIVA** (la adaptada y visible), no la base ideal → un patio adaptado se edita desde su forma adaptada y no revierte. Overlay de tiradores + commit por `data-vertices`. **Ciclado de tiradores superpuestos** (clic suelto alterna vértice↔rombo, el arrastre coge el resaltado). **Umbral de arrastre `DRAG_PX`** (un clic con micro-jitter NO comete «mover») y **anti-autointersección** (`autoCruza`: `_move` rechaza bowties al reformar, mantiene `_ultimoValido`). **Doble-clic** SOBRE una arista inserta vértice EN SITIO (vía `onFijarGeom`, **sin reorden ni recálculo**); en el cuerpo **ya no hace nada** (el «volver a cuadrado»/centrado se **eliminó** a petición del arquitecto). Clic derecho sobre vértice lo elimina (≥3, EN SITIO). |
| `static/js/rc_brujula.js` | 156 | Brújula SVG girable; `onRotate(cb)` → `renderer.setRotation`. Funcional. |
| `static/js/render_calculos.js` | ~1740 | Toda la UI: estado (`ESTADO`), recálculo automático por debounce 300 ms, tablas, 8 modales, visibilidad por uso×planta, tabs por planta, conmutador planta/unidad. Patios: `commitPatioGeom` (mueve la fila al final → prioridad más baja, recalcula), **`fijarPatioGeom`** (cuadrar en sitio: solo escribe `data-vertices`, **sin reorden ni recálculo**), `sincronizarPatiosDesdePayload` (persiste la EFECTIVA + aviso «no cabe» con botón **«Adaptar»** que fija forma+área a la que cabe). |

---

## 6. Gotchas transversales (lo que cuesta tiempo)

- **Coordenadas UTM crudas**: el motor y el canvas trabajan en metros UTM (números
  grandes). El canvas **no** traslada al origen en `_x/_y`; la traslación está embebida en
  `origenX/origenY`. **Eje Y invertido** (`_y = origenY − y·scale`). Cualquier polígono de
  unidad debe venir en el mismo CRS/escala que el bbox.
- **La reproyección WGS84→UTM ocurre en `casos_uso.construir_parcela_metrica`** (huso
  dinámico `_epsg_utm_para_lon`), no en `geometria/`. El motor asume entrada ya métrica.
- **`Planta.interior` solo descuenta muro de fachada uniforme**, no distingue fachada vs
  medianera por lado (aunque `parcelas.py` sí clasifica). Para un reparto fiel quizá haya
  que cruzar lados con el offset de muro.
- **Dos paradigmas de tipología conviven**: antiguo por nº de dormitorios y nuevo §2.5 por
  `ComboDormitorios` (slug canónico `"doble*1+individual*1"` / `"estudio"`). El estudio es
  `n_dorms==0`.
- **Vía vivienda vs vía descriptores**: vivienda simple va por una vía *int-based*
  (`_construir_descriptores_tipologia` devuelve `None`); el resto de usos por descriptores.
- **Circulación interior**: en **vivienda** es una `Estancia` explícita y Σáreas = útil
  exacto; en **apartamentos/hotelero** NO se modela como estancia (se descuenta fuera como
  remanente, util/1.15). No mezclar los dos modelos al dibujar o se dobla/pierde el pasillo.
- **Circulación común y núcleo son del EDIFICIO**, no de la unidad: solo aparecen en la
  tabla por planta, no se imputan por unidad. El área repartible en unidades es la huella
  **neta** tras núcleo + circulación común + patios.
- **Edificabilidad solo AVISA**: aunque se supere el techo, todas las plantas habitables
  reparten unidades (no se retiran). El reparto geométrico debe dibujar lo que dicta capacidad.
- **Vivienda nunca tiene unidades adaptadas**; solo usos turísticos (factor 1,25 apt / 1,30
  hab). En modo `total` el útil ya viene agrandado en `unidades_por_planta`; en `parcial` lo
  agranda la serialización. No doblar el factor.
- **`NivelAlerta` (dominio) ↔ `NIVEL_PESO` (render_calculos.js)** deben coincidir exactos.
- **Cache-busting AUTOMÁTICO**: `plantillas.py` deriva `estaticos_version` (el `?v=`) del mtime
  más reciente de `static/`, reevaluado en cada render. **Ya NO hay que subir versión a mano** al
  tocar CSS/JS (en dev se refleja sin reiniciar). (Las viñetas/bitácora antiguas con
  `ESTATICOS_VERSION→NN` son históricas.)
- **Colores corporativos** (también en canvas/PDF): Negro `#0A0A0A`, Dorado
  `#B8960C`/`#C9A84C`, Blanco `#FFFFFF`. Error `#8C2A1F`. No introducir otros.
- **Avisos UI sin referencias normativas** ("Anexo", "DB SUA", "Decreto", "§x.x", "PGOU"):
  identificador unificado **"Normativa"** (hay tests por regex en la rama antigua).

---

## 7. Limitaciones conocidas que afectan al reparto

- Sin parcelas vecinas, **todos los lados salen `fachada`** → no hay medianera contra la que
  pegar el núcleo; decidir fallback.
- ~~`detectar_patio` coloca **un solo patio rectangular** por planta~~ **RESUELTO (2026-06-26, refinado 2026-06-29)**:
  `colocar_patios` (envolvente.py) coloca **N patios como secciones individuales** (polígono
  libre por patio, editable en el lienzo: mover/estirar/girar/reformar). Cada patio es un
  `PatioDef{area_m2, id, vertices}` (parametros.py) → `PatioPlacement` (config.py) → `Patio{id,
  base, area_efectiva_m2, cabe}`. **Área fija**: `_ajustar_area` normaliza cualquier polígono a su
  `area_m2` asignado. **Prioridad por orden de lista** (no exclusión mutua): cada patio cede solo
  ante los ANTERIORES; el frontend mueve el patio recién editado al FINAL de la lista → solo ÉL se
  adapta, los demás quedan donde estaban. **Adaptación LOCAL al borde** (no bloqueo, no teletransporte):
  el patio puede salir; al soltar, `conformar_patio` recorta a `footprint − patios_anteriores` y
  **rellena el hueco LOCAL** (`_inflar_a_area` acotado a `hi_max=2·√área` + `_pieza_anclada`); se queda
  donde se soltó. Si no cabe en ese hueco → `cabe=False` + aviso rojo con botón **«Adaptar»** (fija
  forma+área a la que cabe). Capacidad sigue deduciendo la SUMA de áreas asignadas (invariante intacto).
  `Patio.base` = forma ideal; `Patio.geometry` = efectiva dibujada. **El editor edita la EFECTIVA**
  (`static/js/rc_patios.js`, `_editable`→`poligono||base`): un patio adaptado se edita desde su forma
  adaptada y no revierte a la ideal que asomaba. `detectar_patio` queda como fallback (sin lista de patios).
- El reparto numérico **no verifica** que las unidades quepan físicamente (ancho/profundidad):
  trunca por área total. La validación geométrica de adyacencia/forma es responsabilidad del
  nuevo motor (parcela profunda con fachada corta puede no alojar lo prometido → `no_ubicada` + aviso).
- Apartamentos/hotel: el interior fiel por uso no-vivienda y la geometría de áreas comunes
  (recepción, sociales) están sin resolver (hoy solo restan m² del techo).

---

## 8. Decisiones y preguntas abiertas (rellenar con el arquitecto)

- [ ] ¿Resucitar/adaptar el algoritmo de la rama antigua (`reparto_unidades.py`: marco
  alineado al MRR, single/double-loaded, núcleo único, rebanado por bisección de área) o
  empezar con una versión más simple (rebanado en franjas paralelas a fachada)?
- [ ] ¿El reparto de m² de estancias se dibuja **dentro de cada unidad** (sub-polígonos por
  estancia, nueva primitiva en `rc_canvas.js`) o de momento solo las unidades + tabla?
- [ ] ¿Modo inmueble también dibuja el reparto de estancias de la unidad, o solo tabla?
- [ ] ¿`unidad.hueco_disp_m2` (huecos a fachada) se calcula para el % de huecos real?
- [ ] Rama de trabajo: confirmar que `render-dev` es donde construir (ver flujo `pro/pre`).

---

## 9. Bitácora

- **2026-06-26** — Mapeado a fondo el módulo en `render-dev` (workflow de 10 lectores).
  Confirmado: cálculo numérico completo y verde (157 tests); render geométrico de unidades
  **no existe** (`edificio: None`); `rc_canvas.js` ya tiene el código de dibujo de
  unidades/núcleo/pasillos, inerte por falta de contrato. Creado este documento + corregido
  el árbol del README. **Pendiente**: decidir algoritmo de disposición y empezar el motor.
- **2026-06-26** — **Patios editables individuales (1ª tarea).** Cada patio pasa de un `float`
  a `PatioDef{area_m2, id, vertices?}` (polígono libre UTM). Motor: `colocar_patios` coloca N
  patios (con posición → tal cual; sin posición → auto-place en el polo del residual sin solape);
  `_ajustar_area` impone «área fija» (reescala al área asignada respecto al centroide); capacidad
  intacta (sigue deduciendo la suma de áreas). Salida y params round-trippean `id`+`vertices`
  (persiste por el aggregate). Frontend: `rc_canvas.js` gana inversas pantalla→mundo
  (`_pantallaAMundo`/`_mundoAPantalla`) + `setOverlay`; nuevo `rc_patios.js` (`PatioEditor`):
  seleccionar, **mover/girar/estirar** (escala anisótropa que conserva el área) y **reformar
  vértices** (al soltar reescala al área), con restricción «impedir/encajar» (dentro de la huella,
  sin solape). 166 tests verdes (+9). `ESTATICOS_VERSION`→86. **Pendiente render geométrico de
  unidades** (rebanadas/núcleo) sigue abierto.
- **2026-06-26** — **Patios: plegado/adaptación al borde** (sustituye «impedir/encajar»). El patio
  ahora **puede salir**; al **soltar**, el backend lo **recorta al borde y rellena hacia dentro**
  conservando los m² (forma adaptada, una sola pieza). Modelo **BASE vs EFECTIVA**: `Patio.base` =
  forma ideal del usuario (lo que se edita/persiste); `Patio.geometry` = efectiva dibujada
  (`conformar_patio` = `∩ footprint−otros_patios` + `_inflar_a_area` por bisección de buffer). Si no
  cabe → `cabe=False` + `area_efectiva_m2`; el frontend pinta la fila del panel en rojo con «El patio
  de XX m² ahora tiene YY m²…». Cuando la base vuelve dentro, `footprint.contains(base)` ⇒ efectiva ==
  base (los vértices temporales desaparecen). `rc_patios.js` edita la **base** (sin bloqueo);
  `sincronizar` sella la base en `data-vertices`. Capacidad intacta. 173 tests (+7).
  `ESTATICOS_VERSION`→88.
- **2026-06-29** — **Patios: prioridad por orden + relleno LOCAL anclado.** En `colocar_patios`
  (Fase B) cada patio cede solo ante los ANTERIORES de la lista (no exclusión mutua); el frontend
  (`commitPatioGeom`) mueve el patio recién editado al final → solo ÉL se adapta, los demás quedan
  intactos. En `conformar_patio`/`_inflar_a_area`: eliminada la **re-siembra al polo** (teletransporte)
  y acotado el relleno a `hi_max=2·√área` + **pieza ANCLADA** (`_pieza_anclada`): el patio rellena su
  hueco local y, si no cabe, se queda ahí con `cabe=False` (no salta a otra zona). `conformar_patio`
  recibe la huella para el fallback de recorte. 176 tests (+2: prioridad, hueco muerto).
- **2026-06-29** — **Botón «Adaptar» + editar la forma EFECTIVA.** En el aviso «no cabe» aparece un
  botón **«Adaptar»** que adopta la forma efectiva + su área (de backend, `area_efectiva_m2`, menos
  0,05 de margen — el `ring()` serializa aproximado: simplifica/redondea/descarta agujeros) para que
  quepa justo. **Cambio de modelo de edición**: el editor pasa a operar sobre la **EFECTIVA** (forma
  adaptada y visible): `_editable`→`poligono||base`, `_up` no revierte en clic suelto (sella la forma
  arrastrada, no la base), `sincronizar` persiste `p.poligono`. Un patio adaptado se edita desde su
  forma adaptada y ya no «revierte» a la ideal que asomaba.
- **2026-06-29** — **Lienzo: zoom Ctrl+rueda + tiradores superpuestos.** `rc_canvas.js` gana zoom al
  cursor (`zoomEn`/`resetVista` + listener de rueda con Ctrl; vista persistente entre repintados
  mientras la bbox no cambie; 1×–12×, alejar del todo re-encaja). `rc_patios.js`: cuando vértice y
  rombo se solapan, un clic suelto cicla cuál queda ENCIMA/resaltado y el arrastre agarra el resaltado
  (`_candidatosHandle`, `_ciclo`, `_handleResaltado`).
- **2026-06-29** — **KPI «Superficie del polígono»** (antes «Superficie del solar»): el panel de
  resultados muestra el área geométrica REAL del polígono (`parcela.area_geometrica_m2`), distinta de
  la catastral (`sup_ref`/`area_m2`), que sigue gobernando edificabilidad/ocupación.
- **2026-06-29** — **Cache-busting AUTOMÁTICO**: `plantillas.py` deriva `estaticos_version` del mtime
  más reciente de `static/` (reevaluado en cada render). Ya NO hay que subir la versión a mano al
  tocar CSS/JS.
- **2026-06-29** — **Patios: anti-autointersección al reformar (bowtie).** Reformar un vértice podía cruzar
  aristas (figura imposible): el backend no sabe adaptar un anillo inválido y `escalarAArea` (shoelace) lo agranda
  con área falseada → «no cabe» falso y botón «Adaptar» vacío. Nuevo helper `autoCruza(v)` (par de aristas no
  adyacentes que se cruzan); `_move` rechaza el candidato autointersectante y mantiene `_ultimoValido` (sembrado
  en `_down`). Nunca se commitea un patio bowtie. 176 tests verdes.
- **2026-06-29** — **Patios: bloqueo (congelado) + fusión por proximidad.** Nuevo campo `bloqueado`
  propagado por todo el pipeline (`PatioDef`→`PatioPlacement`→`Patio`→dict de salida; parse/serialize en
  `parametros.py`, emitido solo si `True`). **Bloqueo**: botón candado 🔒/🔓 a la izquierda del `×` en cada
  `.rc-patio-fila`; un patio bloqueado NO admite interacción (lienzo, área `readonly`, `×` `disabled`) y en
  `colocar_patios` tiene **prioridad máxima** (`orden = bloqueados primero, luego lista` → los vecinos se
  adaptan alrededor; el bloqueado conserva su base). Persistente (round-trip por params). El editor
  (`rc_patios.js`) gatea los bloqueados leyendo `patio.bloqueado` del payload (`_bloqueado`): saltados en
  `_hit`/`_down`/`_candidatosHandle`/`_dblclick`/`_contextmenu`. **Fusión**: cuando dos patios NO bloqueados
  quedan a ≤ 0,1 m (`distanciaPoligonos`), `dibujarOverlay` pinta una **ventanita azul** (`COLOR.azul`
  `#2D6CDF`, excepción a la paleta pedida por el arquitecto) con un botón `+`; al pulsarlo, `fusionarPatios`
  (render_calculos.js) los une en uno: forma = **envolvente convexa** (`convexHull`, cadena monótona) de
  ambos, superficie = **suma** de áreas (el backend la normaliza vía `_ajustar_area`); se elimina el patio B
  y el A baja a última prioridad. 180 tests (+4: round-trip `bloqueado`, propagación motor/Patio, prioridad
  congelada, contrato del dict de salida).
- **2026-06-29** — **Fusión: cuello fino (sustituye la envolvente convexa) + fila del panel en una línea.**
  El hull deformaba («rellenaba alrededor»); ahora la fusión **conserva ambas formas/vértices exactos** y las
  une por un **cuello finísimo** en una sola figura (superficie = suma). La unión robusta se hace con **shapely
  en el backend**: `fusionar_poligonos(a, b, ancho=ANCHO_PUENTE=0.06)` (`envolvente.py`) = `unary_union([a, b,
  puente])` donde `puente` = buffer fino del segmento entre `nearest_points(a, b)` (o disco mínimo si ya se
  tocan); `_normalizar` garantiza un único Polygon válido. Endpoint **`POST /modulos/render-calculos/fusionar-patios`**
  (permiso editar): recibe `{a, b}` (anillos UTM), devuelve `{poligono: ring(fused)}` vía `fusionar_anillos`
  (wrapper coords→Polygon). `fusionarPatios` (render_calculos.js) ahora es **async**: pide la unión al backend,
  la fija como `vertices` del patio A (área = suma) y borra el B; `convexHull` eliminado. El anillo fusionado
  viaja luego como un patio normal (el pipeline lo preserva: `_ajustar_area`≈identidad, `conformar_patio`
  idéntico si cabe). **CSS**: `.rc-patio-fila input { flex:1 1 60px; min-width:0 }` → candado + `×` en la misma
  línea (el aviso «no cabe» sigue cayendo solo por `flex-basis:100%`). 182 tests (+2: fusión conserva ambas
  formas / un solo Polygon; fusión tocándose).
- **2026-06-29** — **Doble-clic en patios: edición de vértices EN SITIO (vivo) + «volver a cuadrado» AÑADIDO Y
  RETIRADO el mismo día.** **Vivo:** doble-clic SOBRE una arista inserta un vértice (`mejorD <= tolPx`) y clic
  derecho sobre un vértice lo borra (≥3); ambas conservan el área (`escalarAArea`), así que se fijan **EN SITIO**:
  callback `onFijarGeom` (`rc_patios.js`, helper `_fijar`) → `fijarPatioGeom` (`render_calculos.js`) solo escribe
  `data-vertices` (**sin reorden a última prioridad, sin `pedirCalculo`**); el lienzo se repinta en local desde
  `_lastPayload`. Umbral de arrastre `DRAG_PX=4` (preview) + gate de `_up` `COMMIT_PX=8`/`ev.detail>=2`
  (confirmación) → un clic con micro-jitter no comete un «mover» accidental. **Retirado (decisión del arquitecto):**
  el doble-clic en el CUERPO reconstruía el patio como cuadrado centrado; tras dos intentos fallidos de evitar que se
  teletransportara y desapareciera, se eliminó **solo** esa rama de `_dblclick` (y su discriminación por centroide,
  que solo existía para ella). Hoy el doble-clic en el cuerpo no hace nada. **Lección durable (motor del
  teletransporte, aplica a CUALQUIER commit de patio):** `commitPatioGeom` **reordena el patio a última prioridad
  (`appendChild`) + `pedirCalculo`** → el backend `conformar_patio` re-adapta una forma que protruye o «no cabe» y
  **desplaza su centroide** → el patio camina hasta desaparecer. Toda edición que conserve el área debe ir por
  `_fijar`, **nunca** por `onCommit`; el único camino que aún reordena+recalcula es `_up` con arrastre deliberado
  ≥ COMMIT_PX (correcto). Sin cambios de backend; 176 verdes.
- **2026-06-30** — **Sincronización del doc + integración de la rama.** Todo el trabajo de patios
  hecho en `render-dev` (editable individual → base/efectiva → prioridad por orden + relleno local →
  zoom/tiradores → anti-bowtie → bloqueo + fusión → doble-clic en sitio) **ya está fusionado en
  `dev`, `pre` y `main`** (en `dev` aparece squashed en 3 commits del 2026-06-29). Recuento real
  confirmado: **182 tests** (`pytest --collect-only`); el encabezado seguía en 176. **El hecho central
  del documento NO cambia**: el render geométrico de **unidades** (rebanadas/núcleo/pasillos) sigue
  **sin existir** — `CalcularLayout`/`CalcularEnvolvente` devuelven `edificio: None`
  (casos_uso.py:410/430/494, comentario «render geométrico en backlog»). «Render de patios implementado»
  se refiere a los PATIOS, no a las unidades; el §4 (plan de integración) y las preguntas abiertas del
  §8 siguen vigentes como próximo trabajo.
