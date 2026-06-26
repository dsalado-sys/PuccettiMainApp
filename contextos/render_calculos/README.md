# Módulo Render y cálculos (§2.4 – §2.7)

Genera la envolvente edificable de una parcela, calcula la capacidad
(número y tamaño de unidades por planta para los 4 usos soportados),
valida cumplimiento normativo y serializa el resultado para el frontend
del módulo.

Está integrado en `app/` (main app) siguiendo arquitectura hexagonal +
screaming. La lógica de geometría/cálculo vive en `geometria/` aislada
de FastAPI y SQLAlchemy.

---

## 1. Estructura

```
app/contextos/render_calculos/
├── dominio.py                 # Enums (UsoEdificio, CategoriaVivienda, …)
├── parametros.py              # ParametrosRender (urbanísticos + diseño + programa)
├── casos_uso.py               # Calcular, Previsualizar, Validar cumplimiento
├── geometria/
│   ├── config.py              # Mirror de parámetros para el motor
│   ├── parcelas.py            # LadoParcela, orientación cardinal, normal exterior
│   ├── envolvente.py          # Retranqueos, ocupación, detección de patios, ático/sótano
│   ├── capacidad.py           # Bucle por planta → capacidad numérica
│   ├── programa.py            # Anexo I.5 vivienda VPO + política escalado
│   ├── programa_apartamentos.py     # Anexo I.3 (edificios) + I.4 (conjuntos) Decreto 194/2010
│   ├── programa_hotelero.py         # Anexo I.1 hotel/hostal/pensión/albergue (habitación)
│   ├── programa_uso.py        # `ProgramaUso` + `TipologiaUnidadDescriptor` + reparto genérico
│   └── serializacion.py       # Output JSON (tablas por planta, por unidad, modal)
└── README.md                  # Este documento
```

Persistencia (en `app/plataforma/persistencia/`):
- `catalogo_superficies_sqlalchemy.py` — Anexo I.5 vivienda + parámetros motor.
- `anexo_i_apartamentos_sqlalchemy.py` — Anexo I.3 apartamentos turísticos (edificios).
- `anexo_i_apartamentos_conjuntos_sqlalchemy.py` — Anexo I.4 apartamentos (conjuntos).
- `anexo_i_hotelero_sqlalchemy.py` — Anexo I.1 hotel/hostal/pensión/albergue.
- `normativa_municipal_sqlalchemy.py` — datos urbanísticos por municipio.
- `carpetas_normativa_sqlalchemy.py` — normativas archivadas (carpetas).
- `seed_normativa.py` — siembra inicial (idempotente).

Frontend (en `app/entrypoints/web/`):
- `rutas/render_calculos.py` — endpoints `/preview` y `/calcular`.
- `templates/render_calculos.html` + `_rc_panel_params.html` + `_rc_modal_unidad.html`.
- `static/js/render_calculos.js` — canvas 2D + tablas + modal de unidad.
- `static/css/render_calculos.css`.

---

## 2. Flujo de cálculo

```
parcela (poligono UTM30N)
        │
        ▼
construir_envolvente(parcela, params)       envolvente.py
   ├── aplicar_retranqueos                 (fachada vs lindero, direccional)
   ├── aplicar ocupación máxima            (recorte por área)
   ├── detectar_patio                      (si supera area_patio_min)
   └── _huella_atico (opcional)
        │
        ▼
Envolvente
   ├── plantas: list[Planta]               (PB, P1, P2, Ático, Sótano)
   └── parcela, lados, edificabilidad_*
        │
        ▼
calcular_capacidad(envolvente, params,     capacidad.py
                   descriptores_tipologia)
   └── Para cada planta:
        ├── PB:        circ_pb + patio + local
        ├── Planta tipo: circ_tipo + patio
        ├── Ático:    como tipo (sin local)
        └── Sótano:   viv = 0
        │
        ▼
Capacidad
   ├── viv_por_planta, util_por_planta
   ├── muros / circulación / núcleo / patio / local por planta
   ├── unidades_por_planta: list[(n_dorms_label, util_m2)]
   ├── tipologias_unidad_por_planta: list[list[slug]]   ← slug por unidad real
   └── viviendas_por_tipologia: list[dict]
        │
        ▼
tabla_planta_desde_capacidad / tabla_unidad_desde_capacidad
        serializacion.py
        │
        ▼
JSON al frontend
```

---

## 3. Modelo diferenciado por planta (PB independiente, iter. 6)

`calcular_capacidad` (capacidad.py) recorre cada `Planta` y aplica el
**bucket de diseño y tipología de su categoría**. `ParametrosRender` lleva
cuatro buckets de diseño (`diseno`=PB, `diseno_tipo`, `diseno_atico`,
`diseno_sotano`) y dos de programa (`programa`=PB, `programa_tipo`). Cada
categoría toma su `DisenoPlanta` (`% muros / % circulación / % núcleo`) del
dict `disenos` que arma [`casos_uso._disenos_por_categoria`](casos_uso.py), y
su perfil de tipología (PB vs plantas tipo) de `params` / `params_tipo`.

| Categoría | Bucket diseño | Tipología | Patio | Local | Comportamiento |
|-----------|---------------|-----------|-------|-------|----------------|
| **PB** (primera regular) | `diseno` (`pct_circulacion_pb`) | `programa` | Sí | `pct_local_pb` (0–100 %) | Resto disponible para unidades |
| **Planta tipo** | `diseno_tipo` (`pct_circulacion_tipo`) | `programa_tipo` | Sí | No | Multi-tipología si procede |
| **Ático** | `diseno_atico` | `programa_tipo` (como tipo) | No | No | `% muros` y `% circulación` propios; `computa_edif` opcional |
| **Sótano** | `diseno_sotano` | — | 0 | 0 | `% muros` y `% circulación` propios; `viv = 0` |

Cada categoría descuenta `muros = pct_muros × construida`,
`circ = pct_circulacion × construida` y `núcleo = pct_nucleo × construida`
con los `pct_*` de **su** bucket (antes de iter. 6, muros/núcleo eran únicos
para todo el edificio y el sótano forzaba circulación 0).

**Herencia por defecto** de los buckets (parser tolerante): `diseno_tipo`←
`diseno`, `diseno_atico`←`diseno_tipo`, `diseno_sotano`←`diseno`,
`programa_tipo`←`programa` (salvo la tipología). Un proyecto sin estos bloques
replica PB en todas las plantas → resultado idéntico al histórico hasta que el
usuario edita una planta tipo/ático/sótano.

**Ocupación máxima por planta** (`urbanisticos.ocupacion_maxima_pct` y
`…_pct_tipo`): la huella se calcula por categoría en
[`construir_envolvente`](geometria/envolvente.py). PB y sótano usan la ocupación
de planta baja; las plantas regulares por encima de PB (y el ático, retranqueado
sobre la planta inferior) usan la de plantas tipo. Si la clave `…_pct_tipo` no
viene en el JSON, **hereda** la de PB → todas las plantas comparten huella
(comportamiento previo). El recorte por ocupación es una erosión uniforme de la
misma huella tras retranqueos, independiente para cada límite.

---

## 4. Reparto multi-tipología (use-agnóstico)

Cuando el usuario elige tipologías extra (selector dinámico `+` / `−`),
`calcular_capacidad` reparte la planta entre varias tipologías. El
reparto NO sabe si la unidad es vivienda, apartamento o habitación de
hotel: opera sobre `TipologiaUnidadDescriptor`.

```python
# programa_uso.py
@dataclass(frozen=True)
class TipologiaUnidadDescriptor:
    slug: str                   # "1d" | "estudio" | "doble" | "individual" …
    util_objetivo: float
    util_minimo: float
    util_maximo: float
    n_dorms_label: int          # etiqueta numérica para `unidades_por_planta`
    tipo_unidad: str = "vivienda"
    plazas: int = 1
```

[`casos_uso._construir_descriptores_tipologia`](casos_uso.py) arma la
lista del uso activo (tipología principal + extras + categoría del
proyecto) y la pasa a `calcular_capacidad`.
[`reparto_multi_tipologia_generico`](geometria/programa_uso.py) hace el
reparto sobre esa lista.

**Política**:

1. Ordenar tipologías por `util_maximo` ascendente (la más pequeña primero).
2. Asignar 1 unidad de cada tipología si cabe en el útil restante
   (consume `min(util_maximo, restante)`).
3. Rellenar el sobrante con la tipología más pequeña mientras quepa su
   `util_minimo`.

**Resultado**: una entrada por unidad real con `(descriptor, util_asignado_m2)`.
El residual no asignable queda como espacio libre.

Ejemplo vivienda con `util_disponible = 158 m²`, tipologías = `[2d, 1d]`:

```
1d primero: consume min(60, 158)  = 60 → restante 98
2d:         consume min(70, 98)   = 70 → restante 28
2d paso: 28 < util_min(1d) = 41.4 → no añade más
Resultado: [(1d, 60), (2d, 70)] — 2 unidades, residual 28 m²
```

`Capacidad` guarda dos listas paralelas:
- `unidades_por_planta: list[list[(n_dorms_label, util_m2)]]` — formato
  numérico compatible con código legacy.
- `tipologias_unidad_por_planta: list[list[str]]` — slug por unidad
  real (clave para que `tabla_unidad_desde_capacidad` regenere las
  estancias correctas en una planta mezclada).

`reparto_multi_tipologia` (vivienda, int-based) se conserva en
[`programa.py`](geometria/programa.py) como envoltura del genérico para
el preview rápido.

---

## 5. Usos soportados y sus Anexos

| Uso | Anexo | Driver de tipología | Construcción `ProgramaUso` |
|-----|-------|---------------------|---------------------------|
| Vivienda | I.5 — VPO Junta Andalucía | nº de dormitorios (0..4) | rama directa con `programa_uso=None` (estancias vía `programa.programa_vivienda`) |
| Apartamentos turísticos | I.3 (edificios) / I.4 (conjuntos) — Decreto 194/2010 | categoría 1L–4L × tipología estudio/1d/2d/3d | `programa_apartamentos.programa_uso_apartamento(cat, tip)` |
| Hotelero | I.1 — Hotel 1–5★, Hostal 1–2★, Pensión, Albergue | individual / doble / triple / cuádruple / múltiple (sólo albergue) | `programa_hotelero.programa_uso_hotelero(cat, tip)` |

Para los usos NO-vivienda, cada uso descuenta del techo de planta las
**áreas comunes obligatorias** (recepción, áreas sociales, segundo
baño) según su Anexo. En vivienda, no hay áreas comunes obligatorias
(la "circulación común" del edificio ya está modelada como
`pct_circulacion_pb/tipo`).

---

## 6. Política de escalado de estancias (vivienda)

[`programa_vivienda(n_dorms, util_disponible)`](geometria/programa.py)
distribuye el útil de la vivienda entre estancias de forma que **la suma
de `area_target_m2` = `util_disponible` exacto** (sin "GAP invisible").

Hasta junio 2026, las áreas target eran `area_min + offset_fijo` y la
suma quedaba por debajo del útil (1d: 42 m² estancias vs 60 útil → 18 m²
sin asignar). La política nueva resuelve este desajuste.

**Reglas**:

1. **Circulación interior** = `util_disponible × 15 %` (estancia
   explícita en el detalle, categoría `circulacion`).
2. **Servicios fijos** — tamaño FIJO desde BBDD:
   - Cocina = 8 m² (MIN_COCINA + 1)
   - Baño = 5 m² (MIN_BANO + 2) — todos los baños son completos.
   - Nº de baños por nº de dormitorios (`banos_vivienda`): 1 hasta 2 dorms,
     2 desde 3 dorms (`bano` / `bano_1` + `bano_2`).
3. **Salón + dormitorios** escalan proporcionales a su `area_min_m2`
   para consumir el restante:
   `util_principal = util − circulación − Σ servicios`.

**Verificación aritmética (suma = `util_maximo` VPO):**

| n_dorms | salon | dorm₁ | dorm₂ | dorm₃ | cocina | baño/banos | circulación | **TOTAL** |
|---------|-------|-------|-------|-------|--------|-----------|-------------|----------|
| 1d | 20.46 | 17.54 | — | — | 8.00 | bano 5.00 | 9.00 | **60.00** |
| 2d | 20.67 | 15.50 | 10.33 | — | 8.00 | bano 5.00 | 10.50 | **70.00** |
| 3d | 22.89 | 15.26 | 10.17 | 10.17 | 8.00 | bano₁ 5 + bano₂ 5 | 13.50 | **90.00** |

**Estudio (n_dorms = 0)** — rediseño completo: salón+cocina+cama en un
único `espacio_principal`. Suma fija = 25 m² (umbral VPO mínimo
excluyendo servicios comunes).

```
espacio_principal    = 18 m²  (mínimo VPO 14)
bano                 =  4 m²  (mínimo VPO 3)
circulacion_interior =  3 m²
TOTAL = 25 m² (util_maximo VPO)
```

`util_minimo_vivienda(0)` = `max(25, sum_min × 1.15)` — garantiza ≥ 25
en cualquier caso.

> Los programas de los otros 2 usos (apartamentos, hotelero) producen
> estancias derivadas de sus mínimos legales + áreas
> comunes — no aplican la política de escalado por % de circulación
> interior (las habitaciones de hotel no tienen pasillos internos
> propios).

---

## 7. Persistencia de la política en BBDD

Cada Anexo se siembra en su propia tabla. Sólo `anexo_i_vivienda` y
`parametros_motor_vivienda` modelan la política de escalado; el resto
son tablas planas con mínimos por (categoría, tipología, estancia).

### `anexo_i_vivienda` (Anexo I.5 + targets)

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `n_dormitorios` | INT (PK) | 0 = estudio · 1..4 = nº dorms |
| `estancia` | STR (PK) | `salon`, `cocina`, `dormitorio_1`, `bano`, … |
| `min_m2` | FLOAT | Mínimo legal (Anexo I.5 VPO) |
| `max_m2_util` | FLOAT | Útil máximo VPO de la tipología |
| `area_target_m2` | FLOAT (nullable) | `NULL` = la estancia ESCALA; valor = tamaño fijo |
| `editable_por_usuario` | INT | 0/1 (1 protege la fila contra reseed) |

### `parametros_motor_vivienda` (singleton)

| Columna | Tipo | Valor inicial |
|---------|------|--------------|
| `id` | INT (PK) | 1 |
| `pct_circulacion_interior_pct` | FLOAT | 15.0 |
| `umbral_minimo_estudio_m2` | FLOAT | 25.0 |

### Tablas paralelas para los demás Anexos

- `anexo_i_apartamentos` (PK: `categoria, tipologia, estancia`) — Anexo I.3.
- `anexo_i_apartamentos_conjuntos` (PK: `categoria, tipologia, estancia`)
  — Anexo I.4; solo categorías 1L y 2L.
- `anexo_i_hotelero` (PK: `categoria, tipologia, estancia`)
  — Anexo I.1; modelo "habitación" (sin cocina por unidad).

### Lectura por cálculo (§3.8)

No hay volcado a constantes de módulo al arrancar. En cada cálculo,
`CalcularLayout._sincronizar_minimos` construye un `Programa*Config`
inmutable con `programa*.config_desde_repo(catalogo, …)` para el uso
activo y lo pasa como argumento por toda la cadena de cálculo. Cada
catálogo expone un método `consolidadas_*()` que devuelve un dict con
los mínimos editados; las constantes de módulo son solo DEFAULTS
inmutables (`CONFIG_DEFAULT`). Así no hay estado global compartido:
los cálculos concurrentes y los tests quedan aislados.

### Migración SQLite

[`sqlalchemy_base.py::_migracion_sqlite_idempotente`](../../plataforma/persistencia/sqlalchemy_base.py)
aplica `ALTER TABLE ... ADD COLUMN` envuelto en try/except. Idempotente:
detecta si la columna ya existe consultándola; si falla, la añade. Las
filas no editadas por el usuario se resincronizan en cada seed.

---

## 8. Tabla "por unidad" vs tabla "por planta"

| Concepto | Tabla por planta | Tabla por unidad |
|----------|------------------|-------------------|
| Muros (`pct_muros`) | Sí (m² total) | Sí (prorrateados por util) |
| Circulación común (`pct_circ_pb/tipo`) | Sí (común planta) | **No** (no es de la unidad) |
| Núcleo (`pct_nucleo`) | Sí (común edificio) | **No** |
| Patio | Sí (descuento planta) | **No** |
| Local PB | Sí (m² destinados) | Fila "Local" sin estancias |
| Útil | Suma del útil consumido | Útil real por unidad |
| Construida | `Σ construida_planta` | `util + muros` |
| Circulación interior (15 % del util) | Implícita en "Útil" | Estancia del detalle (sólo vivienda) |
| Tipología por unidad | Mix agregado (`viviendas_por_tipologia`) | Slug real (`tipologias_unidad_por_planta`) |

**Decisión de junio 2026**: la circulación común y el núcleo son
del edificio. No se imputan a la unidad. Sólo los muros perimetrales
sí se prorratean (proporcionales al útil de cada unidad).

`tabla_unidad_desde_capacidad` itera `cap.tipologias_unidad_por_planta[i]`
y regenera las estancias específicas de cada slug llamando al
`programa_*` del uso activo (vivienda → `programa_vivienda`, apartamento
→ `programa_apartamentos`, etc.).

---

## 9. Validador de círculo inscrito en estancias

[`_cabe_diametro(nombre, area)`](geometria/serializacion.py) verifica
que un círculo del diámetro mínimo del tipo de estancia (CTE DB-SUA + Anexo I)
quepa dentro. Aproximación: rectángulo 1:1.5 → `lado_menor = √(area/1.5)`;
cabe si `lado_menor ≥ diametro_min`.

Diámetros mínimos por estancia (`_DIAMETROS_MIN_M`): salón 3.00, dorm₁
2.70, dorm₂ 2.40, cocina 1.60, baño 1.20, circulación 1.00,
espacio_principal 3.00.

El frontend pinta un ⚠ rojo (`.rc-mu-est-warn`) junto al nombre de la
estancia que no cumple, dentro del modal de detalle.

---

## 10. Avisos / cumplimiento

[`ValidarCumplimiento`](casos_uso.py) compara los valores del proyecto
contra la normativa archivada activa. Tipos de comparación:

- **SUPERIORES** (proyecto > normativa → incumplimiento): coef. edif.,
  ocupación, nº plantas, Ø vestíbulo, espesores máx., % muros.
- **INFERIORES** (proyecto < normativa → aviso): retranqueos (fachada,
  linderos y ático, que son mínimos), luz patio, área patio mínima,
  % adaptadas, ancho fachada, espesor tabique, anchos pasillos, puerta.

Los mensajes usan el identificador unificado **"Normativa"** y **no
referencian** el PDF (Anexo I/II, DB SUA, §x.x, PGOU, Decreto 194/2010
están prohibidos en los avisos de UI).

La normativa aplicada se persiste en el payload del proyecto bajo
`normativa_referencia.urbanisticos`; el backend prioriza este payload
sobre `NormativaMunicipal` archivada en BBDD.

---

## 11. Frontend

- **Canvas 2D**: dibuja parcela, plantas, núcleo, patios, lados con
  orientación cardinal (normal exterior, no azimut del segmento).
- **Pestañas de planta**: PB / P1 / P2 / Ático / S1. PB es independiente: en
  ella se edita todo (urbanismo, opciones de sótano/ático, uso, % local PB,
  tipología y ambas secciones de Diseño). En las plantas tipo se edita el
  **tipo de unidad**, la **ocupación máxima de plantas tipo** (recorta su
  huella) y **Diseño · muros** + **Diseño · circulación y accesibilidad**;
  ático y sótano solo su **% muros** y **% circulación**. La
  visibilidad combina `data-cuando-uso` × `data-visible-en-planta`
  (`pb|tipo|atico|sotano`) en `aplicarVisibilidad`; cada campo editable por
  planta se enruta con `data-bloque` (`diseno`/`diseno_tipo`/`diseno_atico`/
  `diseno_sotano` · `programa`/`programa_tipo`) y `leerFormulario` los envía
  todos (estén o no ocultos por planta, salvo los de otro uso).
- **Tipologías**: selector dinámico con botón `+ Tipología` y `−` por fila,
  **por planta** (PB → `programa.tipologias_extra`; plantas tipo →
  `programa_tipo.tipologias_extra`). La categoría de edificio (estrellas /
  llaves) es global, se fija en PB.
- **Tabla por planta**: columnas Plantas / Viv / Construida / Útil /
  Muros / Muros est. / Circul. / Núcleo / Patio / Local. Tooltip
  muestra mix de tipologías.
- **Tabla por unidad**: una fila por unidad con su tipología real
  (slug del descriptor) y `util` real; fila "Local" cuando aplica (sin
  estancias). Click en fila → modal con detalle de estancias.
- **Cache-busting**: `?v=ESTATICOS_VERSION` en CSS/JS. Subir versión
  manualmente al tocar estáticos.

---

## 12. Punto de extensión: editar la política desde la UI

`anexo_i_vivienda.editable_por_usuario` protege filas modificadas por
el usuario contra el reseed automático. La columna `area_target_m2` y
la tabla `parametros_motor_vivienda` están preparadas para futuras
pantallas de edición (panel de administración del Anexo I).

Las tablas `anexo_i_apartamentos*` y `anexo_i_hotelero` siguen el mismo
patrón (flag `editable_por_usuario`)
y el módulo de Normativa Municipal ya tiene CRUD para los parámetros
urbanísticos. Falta exponer las tablas de superficies mínimas en una
pantalla específica.

Las ediciones surten efecto en caliente sin recargar nada: el siguiente
cálculo lee los mínimos vivos de BBDD vía `config_desde_repo` (§3.8).
