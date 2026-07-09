# Render geométrico de unidades — mapa de trabajo (§2.5 dibujo)

> **Para qué es este archivo.** Documento vivo del trabajo de **dibujar los planos
> del edificio**: distribuir geométricamente las unidades en cada planta y repartir
> los m² de las estancias **como polígonos** (no solo como tabla). El objetivo es no
> tener que releer el módulo entero cada sesión. El README.md de al lado documenta la
> cadena de **cálculo numérico** (que ya existe); esto documenta la capa de **dibujo**
> (que está por construir) y su contrato.
>
> Rama de origen del trabajo de patios: **`render-dev`** · ya **integrado en `dev` → `pre` →
> `main`** (2026-06-29/30). Suite completa hoy: **370 tests** (`python -m pytest app/tests -q`;
> detalle de la evolución del recuento en `REGISTRO.md`, no repetido aquí). Mantén este
> archivo al día (bitácora comprimida al final, §9).

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
- **`Capacidad.composicion_planta_forzada` (cross-uso, 2026-07-08/09)** — segundo
  camino de reparto: el arquitecto elige una combinación de tipologías POR PLANTA y esa
  mezcla se replica idéntica en cada planta habitable (en vez del reparto automático).
  Hotel (§1.9) usa `combinacion` (habitaciones); vivienda/apartamentos (§1.10, 2026-07-09)
  usan `tipos_unidad` + `mezcla_planta` (combo-slugs de dormitorios). **Mismo contrato de
  salida** (`unidades_por_planta`/`tipologias_unidad_por_planta`, invariante de cardinalidad
  intacto) — el futuro motor de disposición lee lo mismo en los tres usos, sin rama
  especial. Detalle: `REGISTRO.md` §1.9/§1.10 y memoria `project_combinaciones_hotel`.

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
| `capacidad.py` | 740 | **Fuente de verdad numérica**: `Capacidad` (~55 campos), `calcular_capacidad`, reparto por planta (`_reparto_planta` o, si hay `composicion_planta_forzada`, `_colocar_composicion_forzada`), factor limitante, `capacidad_a_dict`. Sin geometría. |
| `programa.py` | 693 | Reparto de m² en estancias de **vivienda** (Anexo I.5): `Estancia` (compartida), `programa_vivienda(_combo)`, `ProgramaViviendaConfig`, `config_desde_repo`. |
| `programa_uso.py` | 104 | Descriptores cross-uso: `ProgramaUso`, `TipologiaUnidadDescriptor`, `reparto_multi_tipologia_generico` (cuántas unidades caben por planta). |
| `programa_apartamentos.py` | 521 | Apartamentos turísticos (Decreto 194/2010, I.3 edificios / I.4 conjuntos): mínimos por categoría 1L–4L, `programa_apartamentos(_combo)`, áreas comunes. |
| `programa_hotelero.py` | 248 | Hotelero (I.1): la **habitación** es la unidad; `programa_habitacion`, `descriptor_tipologia_hotelero`, áreas sociales del establecimiento. |
| `combinador_tipologias.py` | 232 | Combina ocupaciones de N dormitorios (§2.5): `ComboDormitorios`, `enumerar_combinaciones`, codec de slug canónico. **+ (2026-07-08)** `enumerar_combinaciones_por_area` (empaquetados maximales de UNA planta por útil disponible, `requerir_todas` — § hotel, ver `REGISTRO.md`). Puro. |
| `accesibilidad.py` | 194 | Unidades adaptadas DB-SUA por tramos (sustituye `pct_unidades_adaptadas`): `aplicar_adaptacion_capacidad`, `_repack_adaptadas`. Solo usos turísticos; vivienda nunca. Corre DESPUÉS de cualquier reparto, incl. la composición forzada de hotel. |
| `serializacion.py` | 484 | Contrato JSON: `ring`, `lados_a_dict`, `tabla_planta/unidad_desde_capacidad`, `_estancias_por_unidad_dorms`, `_nivel_diametro`. **`edificio` no se serializa aquí todavía.** |

### Capa hexagonal del contexto
| Fichero | Líneas | Rol |
|---|---:|---|
| `dominio.py` | 166 | Enums (`UsoEdificio`, categorías/tipologías por uso), `NivelAlerta` (`error/incumplimiento/aviso/info`, debe casar con `NIVEL_PESO` del JS), `Alerta`, `IndicadoresDiseno`, `ResumenEnvolvente`. |
| `parametros.py` | 704 | `ParametrosRender` (4 buckets diseño PB/tipo/ático/sótano + 2 programa) → traducción al motor (`a_parametros_motor[_tipo]`), parser JSON tolerante, herencia tipo←pb / atico←tipo / sotano←pb. `N_PLANTAS_LIMITE=60`. **+ (2026-07-08)** `ParametrosPrograma.combinacion` (slug persistido de la combinación elegida, semántica por uso). |
| `puertos.py` | 115 | 4 puertos `Protocol`: `NormativaMunicipalRepositorio` + catálogos vivienda/apartamentos/hotelero. |
| `casos_uso.py` | 1888 | **Orquestación**: `CalcularEnvolvente`, `CalcularLayout` (central, devuelve `edificio:None`), `CalcularTipologiasDormitorios`, `CalcularCombinacionesHotel` (2026-07-08), `CalcularEstanciasInmueble`, `ValidarCumplimiento`, `GuardarEscenariosRender` + parcela métrica (huso UTM dinámico) + rehabilitación. La serialización de `parcela` expone `area_m2` (catastral/`sup_ref`, gobierna edificabilidad/ocupación) **y** `area_geometrica_m2` (área REAL del polígono, la que ve el KPI «Superficie del polígono»). |

### Web
| Fichero | Líneas | Rol |
|---|---:|---|
| `entrypoints/web/rutas/render_calculos.py` | 968 | Router `/modulos/render-calculos`: `/preview`, `/calcular`, `/estancias`, `/tipologias-dormitorios`, `/combinaciones-hotel` (2026-07-08), `/escenarios`, `/aplicar-normativa`, `/normativa…`, `/superficies-vivienda…`, `/minimos/{uso}…`, `/export.csv`. Permisos por endpoint. |
| `entrypoints/web/render_modos.py` | 110 | 3 modos `obra-nueva`/`rehabilitacion`/`inmueble` (`ModoRender`, `MODOS`, `MODO_POR_DEFECTO`). `inmueble` se auto-deriva si §2.1 eligió un inmueble. |
| `templates/render_calculos.html` | 262 | Pantalla principal: hero (botón «Pintar render» **disabled**), barra catastral, form 3 columnas, `<canvas id="rc-canvas">`, 8 modales. |
| `templates/render_calculos_landing.html` | 327 | Selección de modo + preview parcela + modal de normativa obligatoria. |
| `templates/_rc_panel_params.html` | 529 | Panel izquierdo de parámetros (`data-bloque` × `data-cuando-uso` × `data-visible-en-planta`). Macros `tip_bloque`, `dnum`. **+ (2026-07-08)** botón «Ver combinaciones» solo-hotel + `<input hidden name="combinacion">` uso-agnóstico (persiste la elección por escenario). |
| `templates/_rc_modal_*.html` | — | unidad (60), tipologias (37), **combinaciones_hotel (2026-07-08)**, superficies (22), minimos (24), normativa (71), exceso (27). |
| `static/js/rc_canvas.js` | ~390 | **Render 2D**: `RenderCanvas`. Dibuja parcela/footprint/patios/lados/orientación **y** (cuando lleguen) unidades/núcleo/pasillos. UTM→pantalla, Y invertida, rotación de brújula. Inversas `_pantallaAMundo`/`_mundoAPantalla` + `setOverlay`/`repintar`. **Zoom Ctrl+rueda al cursor** (`zoomEn`/`resetVista` + listener de rueda; vista persistente entre repintados mientras la bbox no cambie; 1×–12×). |
| `static/js/rc_patios.js` | ~500 | **Editor de patios**: `PatioEditor`. Mover/estirar/girar/reformar de cada patio (área fija, edita la forma EFECTIVA); bloqueo/fusión/edición en sitio (ver `REGISTRO.md` §2 reglas de patios para el detalle vigente). |
| `static/js/rc_brujula.js` | 156 | Brújula SVG girable; `onRotate(cb)` → `renderer.setRotation`. Funcional. |
| `static/js/render_calculos.js` | 2392 | Toda la UI: estado (`ESTADO`), recálculo automático por debounce 300 ms, tablas, 9 modales, visibilidad por uso×planta, tabs por planta, escenarios (pestañas), editor de patios. **+ (2026-07-08)** modal «combinaciones-hotel», `<input hidden name="combinacion">` sincronizado (persiste por escenario para todos los usos, ya no solo cliente). |

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
- **Patios: RESUELTO** (histórico completo en `git log`, no repetido aquí). Estado vigente:
  N patios editables como secciones individuales (`Patio{base, geometry, area_efectiva_m2,
  cabe}`), área fija, prioridad por orden de lista, relleno local anclado al soltar, bloqueo
  y fusión por cuello fino. El motor de disposición debe tratarlos como **obstáculos ya
  colocados** (polígonos fijos a evitar) — el detalle de edición vive en `rc_patios.js` y las
  reglas transversales en `REGISTRO.md` §2. `detectar_patio` es solo el fallback sin lista.
- El reparto numérico **no verifica** que las unidades quepan físicamente (ancho/profundidad):
  trunca por área total (o, en hotel con composición forzada, por planta — mismo hueco). La
  validación geométrica de adyacencia/forma es responsabilidad del nuevo motor (parcela
  profunda con fachada corta puede no alojar lo prometido → `no_ubicada` + aviso).
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

> Comprimida (2026-07-08) para lectura rápida: el detalle línea-a-línea de cada commit
> vive en `git log`; aquí solo lo que sigue siendo operativo y no está ya en §6/§7.

- **2026-06-26 → 2026-06-30** (`render-dev`, integrado en `dev`→`pre`→`main`) — Todo el
  trabajo de **patios editables**: individual → base/efectiva → prioridad por orden +
  relleno local anclado → zoom/tiradores en canvas → anti-bowtie → bloqueo + fusión por
  cuello fino → edición en sitio (doble-clic/clic-derecho sin reordenar ni recalcular).
  Reglas vigentes consolidadas en §7 (arriba) y `REGISTRO.md` §2. **Lección durable**: solo
  el arrastre deliberado (`≥COMMIT_PX`) debe reordenar+recalcular un patio; cualquier commit
  que reordene una forma que no cabe le desplaza el centroide hasta hacerlo desaparecer
  («teletransporte») — toda edición que conserve el área va por `_fijar`, no por `onCommit`.
  182 tests al cerrar esta fase. **No toca el render de UNIDADES** (sigue sin existir).
- **2026-06-29** — KPI «Superficie del polígono» (área geométrica real, distinta de la
  catastral que gobierna edificabilidad/ocupación) + cache-busting automático de estáticos
  (ambos ya recogidos en `app/CLAUDE.md` y `REGISTRO.md` §2).
- **2026-07-08** — `Capacidad` gana una vía de reparto POR PLANTA para hotel
  (`composicion_planta_forzada`): sigue siendo puramente NUMÉRICO, mismo contrato de salida
  (ver §2 arriba) — no adelanta el trabajo de disposición geométrica de este documento, pero
  es la fuente de datos que el futuro motor deberá leer también para hotel con combinación
  forzada. Detalle completo: `REGISTRO.md` §5 y memoria `project_combinaciones_hotel`.

**El hecho central de este documento NO cambia**: el render geométrico de **UNIDADES**
(rebanadas/núcleo/pasillos, §1/§3) sigue sin existir — `edificio: None` explícito en
`CalcularLayout`/`CalcularEnvolvente`. El §4 (plan de integración) y las preguntas del §8
siguen vigentes como el próximo trabajo real de este módulo.
