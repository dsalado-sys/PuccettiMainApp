---
name: design_rules
description: Aplica las reglas canonicas de sistema visual y UI/UX (tokens semanticos, tipografia, espaciado, sombras, primitives compartidas, patrones de dashboard, dark mode con tokens, honestidad operativa con status chips y SourceBadges) en productos SaaS multi-tenant con dashboards y backoffice. Usar siempre que se trabaje en UI o frontend del producto: cuando aparezcan terminos como tokens, design system, sistema visual, dashboard layout, dark mode, eyebrow, AppShell, SurfaceCard, MetricCard, StatusPill, glass header, rail vertical, KPI strip, o cuando el usuario pida revisar consistencia visual, anadir un nuevo componente compartido, montar una pagina nueva del producto, o evaluar si una decision visual rompe el sistema. Tambien usar al revisar PRs que tocan estilos, antes de introducir un color hex literal, o cuando alguien proponga importar lucide/heroicons.
allowed-tools: Read, Grep, Glob, Edit, Write
user-invocable: true
disable-model-invocation: false
---

# Design Rules — Buenas prácticas de UI/UX

Esta es una guía **general y transferible**. Recoge los principios que han funcionado bien en este proyecto y que cualquier producto SaaS multi-tenant con dashboards, listados densos y administración separada debería poder adoptar tal cual o con mínimos ajustes.

> **Cómo leerla:** cada sección define una regla y el porqué. Si tu proyecto rompe una regla a propósito, documenta el motivo en su sitio. No la rompas en silencio.

---

## 0. Principio raíz: una sola fuente de verdad para el sistema visual

Define los tokens visuales **una vez** y nunca los repitas:

- Un único fichero CSS (`tokens.css`) con **variables CSS** (colores, fuentes, radios, espaciados, sombras, atmósfera).
- Una única configuración de Tailwind (o equivalente) que mapea esas variables a clases utilitarias.
- Cualquier app del monorepo importa el `tokens.css` desde su `globals.css` y solo extiende `content` en su propio config; **nunca redefine un token**.

**Verificación automatizada obligatoria:** un script en CI que compile el CSS y confirme que existen las clases base del sistema (ej. `bg-primary`, `rounded-card`, `shadow-panel`, una clase `eyebrow` propia). Si el CI no las encuentra, falla. Sin esa red de seguridad, los proyectos jóvenes pierden tokens silenciosamente cuando alguien duplica config.

**Por qué importa:** sin un único punto de control, en seis meses tienes dos paletas, tres tipografías y un dark mode que solo funciona en la mitad de las pantallas.

---

## 1. Sistema de color: tokens semánticos, no estéticos

Define los colores por **función**, no por nombre del color:

| Familia | Tokens |
|---|---|
| Atmósfera | `--background`, `--surface`, `--body-background`, `--body-pattern` |
| Capas de superficie | `--surface-container-lowest` → `--surface-bright` (escala de 5–7 niveles de elevación) |
| Acento principal | `--primary`, `--primary-dim`, `--on-primary` |
| Acentos secundarios | `--secondary`, `--secondary-dim`, `--tertiary` |
| Estado | `--error` (y opcionalmente `--warning`, `--success`) |
| Bordes | `--outline`, `--outline-variant` |
| Texto | `--on-surface`, `--on-surface-variant` |

### Reglas

1. **Nunca usar hex literales en JSX/JSX-like.** Solo tokens (`bg-primary`, `text-on-surface-variant`). Excepción justificable: gradientes inline en visualizaciones (heatmaps, mini-bars) donde la rampa es la información.
2. **Para tonos puntuales de estado se permite una lista cerrada de paletas Tailwind** (típicamente `emerald`, `rose`, `amber`, `indigo`, `slate`). Esa lista debe estar en el `safelist` del config; el resto puede ser purgado.
3. **Asocia cada token de estado a un significado fijo y documentado**:
   - Verde (`tertiary` / `emerald`) = real, conectado, sano, positivo.
   - Cian (`secondary`) = aviso medio, "datos parciales", "demo".
   - Rosa/rojo (`error` / `rose`) = crítico, negativo.
   - Ámbar = atención, advertencia.
   - Slate/neutro = sin información o sin opinión.
4. **Dark mode se hace con tokens, no con `dark:`.** Activa `data-theme="dark"` en `<html>` y reasigna las variables CSS dentro de `:root[data-theme="dark"]`. Los componentes no tienen que conocer el tema.
5. **El estado del tema persiste en `localStorage`** y se aplica con un script inline en `<body>` antes del primer paint, para evitar el flash blanco→oscuro.

---

## 2. Tipografía

Dos familias máximo: una para **headlines y números** (más expresiva, geométrica) y otra para **body** (legible, neutra). Cárgalas con la utilidad de fuentes del framework (en Next.js, `next/font/google`) y expónlas como variables CSS para que las consuma todo el sistema.

### Escala recomendada (canónica)

| Rol | Familia | Tamaño | Peso | Tracking |
|---|---|---|---|---|
| Hero (h1) | headline | 4xl–5xl | 700 | tight (`-0.03em`) |
| Section title (h2) | headline | 2xl–3xl | 700–800 | tight |
| Card title (h3) | headline | lg–2xl | 700 | normal |
| KPI value | headline | 3xl–4xl | 700–900 | tight |
| Body | body | sm leading-7 | 400–500 | normal |
| Meta / footnote | body | xs leading-5 | 400 | normal |
| Eyebrow (clase global) | body | 11px | 600 | uppercase + 0.24em |

### Reglas

1. **Toda cifra clave usa la fuente headline.** Hace que los KPIs y dashboards se sientan instrumentados.
2. **Eyebrow es una clase global**, no un mix de utilities. Define `.eyebrow` en `tokens.css` y úsala en todo el producto. Variantes (0.18em / 0.28em de tracking) admisibles según composición, pero el peso y el tamaño base se mantienen.
3. **Eyebrows van en color de acento o de meta**, nunca en el color principal del texto.
4. **No introducir tamaños arbitrarios.** Si un caso no encaja, primero amplía la escala en `design_rules.md`.

---

## 3. Espaciado y radios

Define **una escala de espaciado y una escala de radios con nombre** y úsalas siempre.

### Espaciado canónico (tokens y clases)

| Token | Valor sugerido | Uso |
|---|---|---|
| `--space-section` (`gap-section`, `space-y-section`) | `1.5rem` | Separación entre bloques de página |
| `--space-content` | `1.25rem` | Separación interna entre subsecciones |
| `--space-card-pad` (`card-pad`) | `1.5rem` | Padding base de tarjetas |
| `--space-card-pad-xl` | `2rem` | Padding de tarjetas hero / amplias |
| `--space-tight` | `0.75rem` | Separación apretada (chips, dots, listas densas) |

### Radios

| Token | Valor | Uso |
|---|---|---|
| `--radius-card` (`rounded-card`) | `1.25–1.5rem` | Tarjetas, header sticky, hero, popovers grandes |
| `--radius-inner` (`rounded-inner`) | `0.625–0.75rem` | Botones, inputs, bloques internos |
| `--radius-pill` (`rounded-pill`) | `9999px` | Pills, chips, dots, tabs |

**Regla:** preferir clases con nombre (`rounded-card`, `rounded-inner`). Bracket-radii (`rounded-[1.25rem]`) se aceptan en composiciones híbridas, pero no inventar nuevos sin justificación; cuando uno se repite tres veces, conviértelo en token.

---

## 4. Sombras y atmósfera

### Sombras canónicas (3 niveles + 2 acentos)

| Clase | Función |
|---|---|
| `shadow-panel` | Tarjeta estándar y header (3 capas suaves) |
| `shadow-elevated` | Popovers, dropdowns, rail (2 capas pronunciadas) |
| `shadow-glow` | Botón activo, focus, CTA con gradient (color del primary) |
| `shadow-glow-secondary` | Variante con color secundario para énfasis |

Sombras inline `shadow-[...]` están permitidas para microefectos (inset highlights, glass borders), pero **las tarjetas y el header siempre usan los nombres canónicos**. Si una sombra puntual se repite, asciéndela a token.

### Atmósfera de fondo

El `body` aplica un fondo compuesto:

- Dos radial-gradients suaves con los acentos primary y secondary.
- Un patrón de puntos sutil (`24px 24px`) con máscara radial.
- Un linear-gradient base entre dos surfaces.

**Las páginas no replican gradientes globales.** Solo el hero superior añade su propio radial-gradient localizado. Esto evita "fondos compitiendo" y mantiene una atmósfera unificada.

---

## 5. Layout y shell

**El shell de la aplicación es un componente compartido único.** No se reproduce manualmente en cada página.

### Composición recomendada

```
┌──── [rail] ─┬─── [main] ─────────────────────────────────────┐
│ logo glass │ ┌── header sticky (glass, top-4) ───────────┐  │
│ nav icons  │ │ producto · nav pill · search · user · 🌓 │  │
│            │ └────────────────────────────────────────────┘  │
│            │ ┌── hero (rounded-card, atmósfera local) ──┐   │
│            │ │ eyebrow · h1 · descr · highlights[≤2]    │   │
│            │ └───────────────────────────────────────────┘   │
│            │ {children} con mt-section / space-y-section    │
└────────────┴────────────────────────────────────────────────┘
```

### Reglas del shell

- **El rail vertical aparece solo en breakpoints anchos** (`xl:flex`). Por debajo, la navegación se reduce a pills horizontales en el header.
- **Header sticky** con `backdrop-blur` y borde glass; `z-index` controlado y documentado.
- **La navegación se decide a runtime**, no en el componente. La página llama a una función como `getRuntimeContext(modulo)` que devuelve los items de nav ya filtrados por:
  1. **Tenant** — ¿el cliente tiene contratado ese módulo?
  2. **Rol** — ¿el usuario actual puede acceder?
- **Hero opcional pero recomendado**: con `eyebrow`, `title`, `description` y como mucho dos `highlights` (label + value). Para mantener la firma visual, todas las páginas suelen tenerlo.
- **Status chips de honestidad operativa** (ver §10) viven al final del header.

---

## 6. Iconografía

Los íconos son **SVG inline**, nunca librería externa. Pesa cero, se rasteriza igual y permite control total del trazo.

### Convención técnica

- `viewBox="0 0 24 24"`, `fill="none"`, `stroke="currentColor"`, `strokeWidth="1.8"–"2"`, `strokeLinecap="round"`, `strokeLinejoin="round"`.
- Tamaño base `h-5 w-5` (nav), `h-4 w-4` (inline). No mezclar con bigger sizes salvo por densidad explícita.
- `aria-hidden="true"` salvo cuando el SVG sustituye texto y aporta semántica → entonces `role="img"` + `aria-label`.
- Los íconos del shell viven en una función `getRailIcon(navItem)` centralizada. Cuando un módulo nuevo entra al sistema, su ícono se añade ahí; no se inventan iconos sueltos en cada página.

**Regla operativa:** prohibido importar `lucide-react`, `react-icons`, `heroicons` o equivalentes. Mantén el bundle limpio y la línea visual coherente.

---

## 7. Primitives compartidos

Cualquier proyecto análogo debería tener un paquete `shared-ui` con un set mínimo. **Estas son las piezas mínimas que ahorran tiempo desde el día 1:**

| Componente | Para qué sirve |
|---|---|
| `AppShell` | Rail + header + hero + slot |
| `SurfaceCard` | Tarjeta base (`card-surface card-pad shadow-panel`) con `className` opcional para variar superficie |
| `SectionHeading` | Eyebrow + título + descripción de sección con divisor degradado |
| `MetricCard` | KPI grande con cintillo de tono y badge de cambio |
| `StatusPill` | Chip semántico (`primary` / `secondary` / `tertiary` / `error` / `neutral`) |
| `ProgressBar` | Barra fina con gradient según tono |
| `MiniBars` | Mini gráfico vertical de barras (5 columnas) |
| `LanguageFlag` | Banderas SVG inline en formato circular (cuando el producto sea multi-idioma) |

### Tone API

Cuatro componentes (al menos) comparten un tipo:

```ts
type Tone = "primary" | "secondary" | "tertiary" | "error" | "neutral";
```

**Cuando una nueva primitive exprese estado o intensidad, reutiliza este tipo.** No inventar `variant="warning"` ad hoc — encajarlo en la paleta existente.

---

## 8. Patrones de UI recurrentes (replicar antes que inventar)

Patrones que cualquier producto SaaS de dashboards debería tener resueltos desde el principio.

### 8.1 Página estándar

```tsx
const ctx = await getRuntimeContext("modulo");
const data = await ctx.dataAccess.getModuloPageData(ctx.session);

return (
  <AppShell {...ctx.shellProps} navigationItems={ctx.navigationItems}
            activeHref="/ruta" eyebrow="..." title="..." description="..."
            highlights={[...]}>
    <ClientView data={data} />
  </AppShell>
);
```

Página = `async server component` que **resuelve runtime + datos + shell**, y delega lo interactivo a un client component.

### 8.2 KPI strip superior

`grid gap-4 md:grid-cols-2 xl:grid-cols-4` con 4 KPIs. Es el "abre página" estándar de los dashboards.

### 8.3 Layout de dos columnas asimétrico

`grid gap-section xl:grid-cols-[1.2fr_0.8fr]` (o `[1.4fr_1fr]`, `[1.05fr_0.95fr]`, `[0.82fr_1.18fr]`). Fracciones pensadas, no fijas. Columna principal pesa más que la lateral.

### 8.4 Selects/filtros custom

Selects nativos no encajan visualmente con el sistema glass. Patrón:

- Un componente `ConsoleSelect` con popover (no `<select>` nativo).
- Estado `openSelectId / setOpenSelectId` **elevado al padre** para que solo uno esté abierto a la vez.
- Cuando aparezca el tercer caso del mismo patrón, **extráelo a `shared-ui`**. Dos copias se toleran; tres no.

### 8.5 Cards con badge de fuente (transparencia operativa)

En el backoffice y en el producto, **cada bloque debe declarar de dónde salen sus datos**: `firestore` / `mock` / `static`. Un mini badge (`<SourceBadge source="..." />`) junto al título de sección. Esto convierte una decisión técnica (¿está conectado de verdad?) en información visible para el usuario, y evita que un demo se confunda con producción.

### 8.6 Barra de sentimiento

Tres segmentos verde/slate/rojo dentro de un `rounded-pill bg-surface-container-low`, acompañada de tres dots inline con porcentaje. Patrón canónico para distribución positivo/neutro/negativo.

### 8.7 Forms del backoffice

Inputs y selects nativos con clases custom (radii, bordes, `bg-surface-container-low`). En Next.js, **Server Actions + `revalidatePath`** son suficientes para todo CRUD interno. Evita meter `react-hook-form` o librerías de form para forms simples.

---

## 9. Accesibilidad y responsive

- `lang` en el root acorde al idioma principal del producto.
- `suppressHydrationWarning` en `<html>` cuando el theme se aplica con script inline pre-paint.
- SVGs decorativos → `aria-hidden="true"`. SVGs informativos → `role="img"` + `aria-label`.
- Inputs de búsqueda y comboboxes → `aria-autocomplete`, `aria-expanded`, `aria-label` siempre.
- Focus visible: usar `focus:` y `focus-within:` con border o ring del primary. **Nunca quitar outlines** sin alternativa visible.
- Hit targets mínimos: 36px de alto efectivo en interactivos.
- Breakpoints estándar (`sm/md/lg/xl/2xl`). El rail aparece desde `xl`. La nav pill envuelve con `flex-wrap`.

---

## 10. Honestidad operativa: chips de estado y badges de fuente

Patrón crítico para productos B2B en estado mixto demo/real:

- **Status chips en la cabecera del shell** que reflejan estado **real**, no aspiracional. Ejemplos:
  - `Sesion verificada` (auth Firebase OK) vs `Acceso de prueba` (mock).
  - `Datos conectados` vs `Contenido de ejemplo`.
- **Tono `tertiary`** (verde) cuando es real; **`secondary`** cuando es mock/parcial.
- **Cuando una sola sección está conectada y el resto sigue mock, los chips globales deben decir mock.** No inflar percepción de progreso.
- Complementario: `SourceBadge` por sección dentro del backoffice (ver §8.5).

**Por qué importa:** el cliente debe saber, en cada momento, si lo que ve es real. Un dashboard "verde" con datos de ejemplo destruye la confianza más que tres semanas de retraso.

---

## 11. Tema dark — checklist

- Activación con `data-theme="dark"` en `<html>`, persistido en `localStorage`.
- Script inline pre-paint que setea el atributo antes del primer render.
- **Tokens cambian solos**; no condicionar la UI con `dark:` salvo en glass overrides puntuales (rail, header, popovers donde un `bg-white/...` deba virar).
- Probar TODA pantalla en ambos modos antes de mergear. El bug típico: `bg-white` literal — en dark queda blanco contra fondo oscuro. Usar token de superficie.

---

## 12. Anti-patrones (no hacer)

| Antipatrón | Por qué |
|---|---|
| `style={{ color: "#4f46e5" }}` o hex en JSX | Rompe dark mode y descontrola el sistema |
| Repetir tokens en el config de la app | Doble fuente de verdad |
| Usar paletas Tailwind fuera del safelist | Pueden purgarse en producción |
| Crear una tarjeta sin la primitive base | Inconsistencia de radio/sombra/borde |
| Componentes shell propios por página | El shell es uno solo |
| Iconos lucide / heroicons importados | Bundle pesado y línea visual rota |
| `font-bold` en eyebrows | Eyebrows tienen su peso y tracking propios |
| `dark:bg-...` cuando el token ya cambia solo | Doble manejo de tema |
| Selects nativos en una vista de producto | Romper el sistema glass |
| Status chips aspiracionales | Mata la confianza del cliente |

---

## 13. Cuando hay duda — heurística rápida

1. ¿Hay ya una primitive en `shared-ui` que hace algo parecido? → **Usarla o extenderla.**
2. ¿El estilo se puede expresar con tokens existentes? → Sí, casi siempre. Si no, **proponer un token nuevo** antes de hardcodear.
3. ¿La interacción ya existe en otra página (filtros, tabs, popovers)? → **Replicar exacto.** No inventar variantes.
4. ¿Lo que vas a construir entra en el shell? → **Seguro.** No envolverlo en otro layout.
5. ¿Tienes que mostrar estado de un dato? → **Es obligatorio.** Status chips arriba; `SourceBadge` por sección.
6. ¿La regla aquí escrita estorba en un caso concreto? → **Documenta el porqué de la excepción** en el commit/PR antes de saltártela.
