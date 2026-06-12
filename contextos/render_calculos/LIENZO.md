# Lienzo de dibujo sobre la parcela — Cómo funciona

Documentación funcional e interna del **lienzo de dibujo manual** del módulo
*Render y cálculos* (§2.4). El lienzo permite al técnico **pintar a mano**
superficies (rectángulos y polígonos) y muros sobre la parcela, por planta, y
obtener los **m² que ocupa cada pieza dentro de la parcela**.

---

## 1. Qué es y qué NO toca

La pantalla de *Render y cálculos* tiene 3 columnas. El lienzo **solo se apodera
de la columna central** (`<section class="rc-viz">`):

```
┌── Render y cálculos ─────────────────────────────────────────────┐
│  PARÁMETROS        │        LIENZO (centro)        │   TABLAS/KPIs │
│  (izquierda)       │  ── herramientas ──           │  (derecha)    │
│  intacto           │  pestañas planta · canvas     │  intacto      │
│                    │  inspector · resumen color    │               │
└──────────────────────────────────────────────────────────────────┘
```

- **No modifica** el panel de parámetros (izquierda) ni el motor de cálculo
  automático ni las tablas/KPIs «Por planta / Por unidad» (derecha): siguen
  funcionando igual. El cálculo automático sigue ejecutándose (alimenta las
  tablas), pero **ya no se dibuja** en el centro.
- El render pasivo automático (`RenderCanvas`) se **neutraliza** en el centro con
  un *shim*: `renderer.dibujar = noop` (en
  [render_calculos.js](../../entrypoints/web/static/js/render_calculos.js)). El
  canvas `#rc-canvas` pasa a ser propiedad del lienzo.

**Alcance actual:** «**Por planta**» (un dibujo independiente por índice de
planta). «Por unidad» queda para más adelante.

---

## 2. Mapa de archivos

| Capa | Archivo | Rol |
|------|---------|-----|
| Geometría | [`geometria/lienzo.py`](geometria/lienzo.py) | Recorte Shapely y resumen por color (funciones puras) |
| Casos de uso | [`casos_uso_lienzo.py`](casos_uso_lienzo.py) | `CalcularLienzo`, `GuardarLienzo`, `CargarLienzo` |
| Rutas | [`rutas/render_calculos.py`](../../entrypoints/web/rutas/render_calculos.py) | Endpoints `GET /lienzo`, `POST /lienzo/calcular`, `POST /lienzo/guardar` |
| Frontend | [`static/js/rc_lienzo.js`](../../entrypoints/web/static/js/rc_lienzo.js) | Controlador completo del lienzo |
| Plantilla | [`templates/render_calculos.html`](../../entrypoints/web/templates/render_calculos.html) | Toolbar + inspector + resumen |
| Estilos | [`static/css/render_calculos.css`](../../entrypoints/web/static/css/render_calculos.css) | Clases `.rc-lienzo-*` |
| Tests | [`tests/.../test_lienzo.py`](../../tests/contextos/render_calculos/test_lienzo.py) | Geometría + casos de uso |

---

## 3. Sistema de coordenadas (clave para entender todo)

Hay **dos espacios** y el lienzo convierte constantemente entre ellos:

- **Mundo**: metros **UTM30N (EPSG:25830)**. Es el mismo CRS en el que el backend
  reproyecta la parcela (`construir_parcela_metrica`). **Todas las figuras se
  almacenan en metros de mundo** → el área en m² es directa.
- **Pantalla**: píxeles CSS del canvas.

El viewport (escala + centrado de la parcela) lo aporta una instancia reutilizada
de `RenderCanvas` (no dibuja nada; solo se usa su matemática):

```
pantalla = mundo → pantalla:   sx(x) = origenX + x·scale
                               sy(y) = origenY − y·scale      (Y invertido)

mundo    = pantalla → mundo:   worldX(px) = (px − origenX) / scale
                               worldY(py) = (origenY − py) / scale
```

El inverso `worldX/worldY` es lo que permite saber **dónde, en metros, ha pulsado
el ratón**. Al redimensionar la ventana (`ResizeObserver`) se recalcula el
viewport; las figuras no se deforman porque están en mundo, solo cambia la
transformación.

---

## 4. Cómo se representa internamente cada elemento

Todas las piezas (superficies y muros) son objetos JS con esta forma:

```js
{
  id:    "f<timestamp><n>",   // identificador estable
  tipo:  "rect" | "poly" | "muro",
  nombre:"S1",                // editable por el usuario
  color: "#2E9E5B",           // 5 predefinidos o hex libre
  verts: [[x,y], …],          // SIEMPRE en metros de mundo
  grosor: 0.30,               // solo muro (m)
  m2:    36.0,                // área recortada a la parcela (cacheada)
  m2_aprox: true              // true mientras es estimación de frontend
}
```

Diferencias por tipo:

- **`rect`** → `verts` son las **4 esquinas en orden**. La rotación está
  **horneada en las esquinas** (no se guarda un ángulo aparte): si el rectángulo
  está girado, sus 4 puntos ya están girados.
- **`poly`** → `verts` son los **N puntos** del polígono irregular.
- **`muro`** → `verts = [p1, p2]` (los dos extremos) + `grosor`. El muro **no
  almacena su rectángulo**: se calcula al vuelo cuando hace falta (ver abajo).

### `poligonoMundo(figura)` — el polígono "real" de una pieza

Función interna central. Devuelve el polígono que se usa para **pintar, etiquetar,
hit-test y área aproximada**:

- `rect`/`poly` → devuelve `verts` tal cual.
- `muro` → **construye el rectángulo** del segmento `p1→p2` expandido `grosor/2` a
  cada lado (dirección + normal perpendicular). Así un muro se trata
  geométricamente como una superficie fina.

---

## 5. Herramientas e interacción (máquina de estados)

La barra superior tiene 6 herramientas, seleccionables en cualquier momento:

| Herramienta | `data-tool` | Comportamiento |
|-------------|-------------|----------------|
| Seleccionar | `seleccionar` | mover / redimensionar / rotar / editar vértices |
| Geometría   | `rect` | arrastrar para crear un rectángulo |
| Líneas      | `poly` | clicar puntos; cerrar en el 1.er punto o con **Enter** |
| Muro        | `muro` | clicar dos puntos |
| Borrar superficie | `goma-sup` | borra la **superficie entera** que toca |
| Borrar muro | `goma-muro` | borra el **muro entero** que toca |

### Crear
- **Rectángulo**: `mousedown` fija una esquina, se arrastra hasta la opuesta,
  `mouseup` lo crea (si supera el lado mínimo). Eje‑alineado al crearse.
- **Polígono**: cada `mousedown` añade un vértice; línea elástica de previsualización
  hasta el cursor; se cierra clicando cerca del primer punto (≥3 vértices) o con
  **Enter**. **Esc** cancela.
- **Muro**: primer `mousedown` = `p1`; segundo = `p2` (si la longitud supera el
  mínimo). **Esc** cancela.

### Seleccionar y editar (herramienta `seleccionar`)
Prioridad de *hit-test* en `mousedown` (tolerancias en píxeles):
1. **Flecha de rotación** (si está visible) → rotar la figura alrededor de su
   centroide.
2. **Vértice/manejador** de la figura seleccionada →
   - `rect`: **redimensionar** conservando los ejes (incluso si está girado): se
     deriva el marco local de las propias aristas y se ancla la esquina opuesta.
   - `poly` / `muro`: **mover ese vértice** libremente.
3. **Interior** de alguna figura → la selecciona y permite **moverla** entera.
4. **Vacío** → deselecciona.

### Click simple vs arrastre (la flecha de rotación)
La distinción se decide en `mouseup` con un umbral de movimiento (`UMBRAL_DRAG`):
- Si pulsaste sobre una figura **ya seleccionada** y **no arrastraste** → se
  **alterna la flecha de rotación** (aparece/desaparece). Con la flecha visible,
  arrastrarla rota la figura desde el centro.
- Si arrastraste → fue una edición (mover/redimensionar/rotar).

### Rotación (interno)
No se guarda un ángulo: al rotar se aplican las coordenadas rotadas a **todos los
vértices** alrededor del centroide. Como `verts` ya quedan rotados, al backend se
le envían **vértices ya rotados** (y `rotacion: 0`): el backend **solo recorta**,
nunca rota.

### Gomas y teclado
- Las **gomas borran la figura entera** del tipo correspondiente bajo el cursor
  (la de superficie no toca muros y viceversa). Con una goma activa no hay
  selección ni manejadores.
- **Supr/Retroceso** borra la figura seleccionada (salvo que el foco esté en un
  input). **Esc** cancela la operación en curso o deselecciona.
- Cambiar de herramienta a media operación hace *commit/descarte* limpio (un
  polígono de ≥3 puntos se cierra; uno incompleto o un muro a medio se descartan).

---

## 6. Recorte a la parcela ("no se pinta fuera")

Dos niveles, ambos respetando *«lo de fuera no se ve ni cuenta»*:

1. **Visual (frontend)**: antes de pintar las figuras se aplica
   `ctx.clip(parcelaPath)` con el contorno de la parcela. Lo que cae fuera
   simplemente **no se dibuja** (funciona también con parcelas cóncavas). La
   geometría completa se conserva para poder seguir agarrando y moviendo la
   figura; **solo el relleno se recorta**.
2. **m² (backend)**: el área real es la **intersección Shapely** de la figura con
   el polígono de la parcela. Lo de fuera aporta 0.

Las **etiquetas** (nombre + m²) se pintan **sin recorte**, sobre el centroide,
para que se lean aunque parte de la figura se salga.

---

## 7. Cálculo de m²: estimación instantánea vs valor autoritativo

- **Instantáneo (frontend)**: mientras dibujas/mueves, el área se estima con
  **shoelace** sobre `poligonoMundo(figura)` (sin recortar) y se muestra con
  prefijo **`~`** (p. ej. `~ 42,0 m²`). Es solo feedback inmediato.
- **Autoritativo (backend)**: al terminar una edición se llama (con *debounce*
  250 ms y `AbortController`) a `POST /lienzo/calcular`, que recorta con Shapely
  y devuelve el área exacta dentro de la parcela. El `~` desaparece.

---

## 8. Resumen por color (debajo del lienzo)

Bajo el canvas se muestra el agregado, **separando superficies y muros**:

- **Superficies por color**: un chip por color con sus m² totales (y nº de piezas).
- **Muros**: muros agrupados por color **+ un total de m² de muro** sumado aparte.

El backend lo calcula en `resumen_por_color(...)` y devuelve:

```json
{
  "superficies_por_color": [{ "color": "#2e9e5b", "m2_total": 48.0, "n": 2, "nombres": ["S1","S2"] }],
  "muros_por_color":       [{ "color": "#2d6cdf", "m2_total":  5.0, "n": 1, "nombres": ["M1"] }],
  "total_superficies_m2": 48.0,
  "total_muros_m2": 5.0,
  "total_m2": 53.0
}
```

Solo entran piezas con área > 0; los grupos se ordenan de mayor a menor m².

---

## 9. Colores

5 predefinidos **fijos** (vivos, conforme al estilo de la app) + campo
hexadecimal libre:

```
Rojo #D7263D · Blanco #FFFFFF · Verde #2E9E5B · Azul #2D6CDF · Amarillo #F2C200
```

El color y el nombre se editan en el **inspector** (debajo del canvas) cuando hay
una figura seleccionada. Esos inputs viven dentro del `<form id="rc-form">`, así
que sus eventos hacen `stopPropagation()` para **no disparar** el `/preview` del
cálculo automático.

---

## 10. Persistencia (qué se guarda y dónde)

Aditiva: el dibujo se guarda en el aggregate `Proyecto`, bajo una **clave nueva**
del módulo, **sin tocar** `["parametros"]` ni el resto:

```
proyecto.datos_por_modulo["render_calculos"]["lienzo"] = {
  "plantas": {
    "0": {                                   // índice de planta (string)
      "figuras": [
        { "id","tipo":"rect|poly","nombre","color","vertices":[[x,y]…],"rotacion" }
      ],
      "muros": [
        { "id","nombre","color","p1":[x,y],"p2":[x,y],"grosor" }
      ]
    },
    "1": { "figuras": [], "muros": [] }
  },
  "timestamp": "…"
}
```

- Se persiste **solo el dibujo crudo** (entrada del usuario). Los polígonos
  recortados y las áreas son **derivados** → se recalculan en `/calcular` (así, si
  cambia la parcela, no quedan áreas obsoletas).
- `GuardarLienzo` **muta solo** `["lienzo"]` (sobre el dict mutable que devuelve
  `proyecto.datos(...)`), nunca `["parametros"]`. Cada planta se guarda en su
  propia clave: guardar la planta 1 no afecta a la 0.
- Antes de persistir se **sanean** coordenadas no finitas (NaN/inf) y se recortan
  topes de tamaño, para no escribir JSON inválido.

---

## 11. Backend en detalle

### `geometria/lienzo.py` (funciones puras, Shapely)
- `recortar_poligono(vertices, parcela) -> (rings, area_m2)`: `<3` vértices o sin
  solape → `([], 0.0)`. `buffer(0)` sanea auto-intersecciones.
- `recortar_muro(p1, p2, grosor, parcela) -> (rings, area_m2)`: el muro es la banda
  del segmento (`buffer(grosor/2, cap_style=2 plano, join_style=2 mitre`)
  intersecada con la parcela. Descarta longitud nula / grosor ≤ 0 / no finitos.
- `resumen_por_color(figuras, muros) -> dict`: agrupa por color (solo área > 0),
  superficies y muros por separado, con totales.
- `_rings_de(geom)`: maneja **MultiPolygon / GeometryCollection** (la parcela
  cóncava puede partir una figura en varias piezas) → devuelve **varios anillos**.

### `casos_uso_lienzo.py` (puros, DI por parámetro)
- `CalcularLienzo.ejecutar(parcela, figuras, muros)`: recorta cada pieza y devuelve
  áreas + resumen + parcela. **No persiste.**
- `GuardarLienzo(repo).ejecutar(proyecto, planta, figuras, muros)`: persiste el
  dibujo crudo de una planta.
- `CargarLienzo.ejecutar(proyecto, parcela)`: devuelve parcela + dibujos guardados.

### Endpoints (router `/modulos/render-calculos`)
| Método · ruta | Permiso | Entrada | Salida |
|---|---|---|---|
| `GET /lienzo` | VER | — | `{parcela:{poligono,bbox}, plantas:{…}}` |
| `POST /lienzo/calcular` | VER | `{planta,figuras,muros}` | `{parcela, figuras:[{id,…,rings,area_m2}], muros:[…], resumen}` |
| `POST /lienzo/guardar` | EDITAR | `{planta,figuras,muros}` | `{ok, planta, actualizado_en}` |

Sin proyecto o sin parcela → **409**; payload mal formado → **422**.

---

## 12. Flujo frontend ↔ backend

```
Carga de página
  └─ GET /lienzo ──────────► parcela (ring+bbox) + dibujos por planta
       └─ recalcViewport (Path2D de la parcela) → render
       └─ POST /lienzo/calcular (si hay piezas) → m² reales + resumen

Cada edición (crear/mover/redimensionar/rotar/borrar/nombre/color)
  ├─ render inmediato (m² ~estimado)
  ├─ debounce 250 ms → POST /lienzo/calcular → m² reales + resumen
  └─ debounce 400 ms → POST /lienzo/guardar  → persiste (si puede editar)

Cambio de pestaña de planta (#rc-tabs-plantas, solo lectura)
  └─ carga el dibujo de esa planta → recalcula → render
```

El lienzo **escucha** los clics de las pestañas de planta de forma delegada (solo
lectura): no crea ni reordena pestañas ni toca la lógica de cálculo.

---

## 13. Casos límite cubiertos

- Sin proyecto / sin parcela → 409; el frontend muestra aviso y no deja dibujar.
- Figura con < 3 vértices, o totalmente fuera → área 0, sin grupo de color.
- Polígono auto‑intersecante → `buffer(0)` lo valida.
- **Parcela cóncava** → la figura/muro se parte en varias piezas (MultiPolygon),
  tanto en el recorte visual como en el área.
- Muro de longitud nula o grosor ≤ 0 → área 0.
- NaN/inf en coordenadas → filtrados antes de Shapely y antes de persistir.
- Redimensionar/resize de un rectángulo **rotado** → conserva su forma y ejes.

---

## 14. Limitaciones / fuera del MVP

- La **brújula** (rotación de vista) no afecta al lienzo.
- El recorte exacto contra parcela **cóncava** lo da el backend; el frontend solo
  estima el m² con shoelace mientras editas.
- `ring()` aplana una parcela **multipolígono** a su anillo exterior (limitación
  conocida del serializador).
- Sin: deshacer/rehacer, *snapping*, multiselección, edición del grosor del muro
  desde la UI (usa 0,30 m por defecto), vista «Por unidad», ni integración del
  área del lienzo con el cálculo de capacidad (el lienzo es informativo).

---

## 15. Cómo verificar / extender

- **Tests**: `python -m pytest app/tests/contextos/render_calculos/test_lienzo.py -q`.
- **App**: `python -m app.run` → abrir un proyecto **con parcela** (localizarla en
  §2.1) → *Render y cálculos*. Recuerda subir `ESTATICOS_VERSION` en
  [`plantillas.py`](../../entrypoints/web/plantillas.py) al tocar JS/CSS.
- **Extender**: la geometría vive en `geometria/lienzo.py` (puro, testeable); la
  interacción en `rc_lienzo.js` (estado en el objeto `S`, render en `render()`,
  eventos en `onMouseDown/Move/Up` + `onKeyDown`).

---

## 16. Autodistribución — rellenar el lienzo desde el cálculo (§2.5 + Anexo II)

El botón **«✦ Autodistribuir»** de la barra reparte automáticamente los m² que
produce el cálculo de capacidad (`calcular_capacidad`) como piezas coloreadas
dentro de la huella de cada planta. Materializa el mandato del módulo: **«dibujar
lo que dice el cálculo, no lo que la geometría puede acomodar»** (el comentario de
deprecación de `macro_layout.py`). A diferencia de aquel motor (geometry-driven),
aquí **las áreas son el dato de entrada** y la geometría se dimensiona para
**cuadrar con ellas** (partición exacta de la huella por bisección).

### Qué pinta (bloques por categoría + muros con la herramienta de muro)
Un **bloque (superficie)** por **unidad** (V1, V2…) + **circulación** + **núcleo**
+ **patio** + **local** (solo PB). Los **muros NO son superficies**: se dibujan con
la **herramienta de muro** (piezas de muro: segmento + grosor).

| Categoría | Color | Origen / forma |
|-----------|-------|----------------|
| Unidad | Verde `#2E9E5B` | `unidades_por_planta[i]` (útil de cada unidad) |
| Circulación | Dorado claro `#C9A84C` | `circulacion_por_planta[i]` |
| Núcleo | Dorado `#B8960C` | `nucleo_por_planta[i]` |
| Patio | Azul `#2D6CDF` | `patio_por_planta[i]` |
| Local | Amarillo `#F2C200` | `local_por_planta[i]` (PB) |
| Muros | Negro `#0A0A0A` | **piezas de muro** (p1→p2 + grosor), espesor normativo A2.4 |

### Muros (criterio del estudio)
Los muros salen del **contorno de las regiones con muro** (unidad/patio/local):
`wall_lines = unión de sus fronteras`. Por construcción se cumple:
- unidades, patios y locales van **rodeados de muro**;
- circulación y núcleos **no** llevan muro propio;
- unidad pegada a núcleo → **un solo** muro (el de la unidad); unidad↔unidad → un
  muro compartido (una vez); unidad↔exterior → fachada/medianera (clasificado por
  el punto medio del segmento).

Cada muro lleva su **espesor normativo** (A2.4: fachada/medianera 0,25 m,
separación entre unidades 0,20 m, configurables). Su banda se **descuenta** de las
superficies → la suma (superficies + muro) cuadra con la huella. Como los muros
reales (≈0,20-0,25 m) ocupan menos que el 20 % abstracto de `muros_por_planta`, las
superficies quedan **algo por encima** de su útil neto calculado («acercándose»).

### Esquema (vivienda, Anexo II)
Núcleo pegado a una fachada (acceso) → pasillo común central → dos crujías de
unidades (double-loaded), con el patio en la banda superior y el local en la
inferior. Se **avisan** los incumplimientos sin encajarlos a la fuerza:
- vestíbulo del núcleo que no inscribe **Ø1,50 m** libre (A2.1),
- pasillo común por debajo de **1,20 m** (A2.1/§2.6),
- patio con luz recta `< 3 m` (A2.5),
- unidades junto a medianera sin ventilación a fachada/patio (A2.5).

Si la huella no admite el esquema (muy estrecha, sótano, ático sin sitio…) se cae
a un **treemap** slice-and-dice que mantiene las áreas exactas y deja constancia
(«disposición simplificada»). Las incidencias se citan como **«Normativa: …»**
(sin artículos literales en la UI, criterio del estudio).

### Mapa de archivos (añadidos)
| Capa | Archivo | Rol |
|------|---------|-----|
| Geometría | [`geometria/disposicion.py`](geometria/disposicion.py) | `disponer_planta(objetivo, lados, params)` — partición exacta + Anexo II |
| Caso de uso | [`casos_uso_lienzo.py`](casos_uso_lienzo.py) | `AutodistribuirLienzo` (reutiliza `CalcularLayout.preparar`) |
| Ruta | [`rutas/render_calculos.py`](../../entrypoints/web/rutas/render_calculos.py) | `POST /lienzo/autodistribuir` |
| Frontend | [`rc_lienzo.js`](../../entrypoints/web/static/js/rc_lienzo.js) | botón `#rc-lienzo-autodistribuir` → `autodistribuir()` |
| Tests | [`tests/.../test_disposicion.py`](../../tests/contextos/render_calculos/test_disposicion.py) | cuadre de áreas, contención, incidencias, persistencia |

### Endpoint
`POST /modulos/render-calculos/lienzo/autodistribuir` · Entrada
`{parametros, planta?, persistir?}` (sin `planta` → todas; `persistir` solo si el
rol puede **EDITAR**). Salida `{plantas:{idx:{figuras,muros}}, incidencias,
resumen}` con el **mismo formato de dibujo** que `GET /lienzo`: las superficies
son `figuras` tipo `poly` y los **muros son piezas de muro** (`{p1,p2,grosor}`),
que `recortar_muro` recorta y que se editan con la herramienta de muro. El índice
de planta coincide con la pestaña del lienzo y con la clave de `GuardarLienzo`.

### Flujo (un clic, reemplaza con confirmación)
```
✦ Autodistribuir
  ├─ confirma si alguna planta ya tiene dibujo manual
  ├─ lee los parámetros del formulario (window.rcLeerParametros)
  ├─ POST /lienzo/autodistribuir {parametros, persistir:true}
  │    └─ CalcularLayout.preparar → (envolvente, capacidad)
  │    └─ por planta: ObjetivoPlanta → disponer_planta → figuras
  │    └─ GuardarLienzo por planta (reemplaza el dibujo crudo)
  └─ adoptarDibujos(plantas) → render → /lienzo/calcular (m² autoritativos)
```

### Limitaciones (v1)
- **Solo vivienda** afinada; otros usos caen al reparto genérico/treemap (la
  arquitectura es use-agnostic, pendiente afinar hotelero/apartamentos).
- Las superficies por categoría son **aproximadas** (los muros reales ocupan menos
  que el 20 % del cálculo, así que las superficies quedan algo por encima del útil
  neto); el **total** (superficies + muro) sí cuadra con la huella.
- Sin subdivisión interior de cada unidad en estancias (salón, dormitorios…): es
  «bloques por categoría». La subdivisión queda para una capa posterior
  (`interiores.py` ya existe para vivienda).
- Plantas que exceden la edificabilidad muestran su interior como **«Sup. libre»**
  (0 unidades), coherente con la tabla por planta.
