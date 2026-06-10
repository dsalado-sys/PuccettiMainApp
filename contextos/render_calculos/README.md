# Módulo Render y cálculos (§2.4 – §2.7)

Genera la envolvente edificable de una parcela, calcula la capacidad
(número y tamaño de viviendas por planta), valida cumplimiento normativo
y serializa el resultado para el frontend del módulo.

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
│   ├── programa_hotel_apartamento.py # Anexo I.2 hoteles-apartamento (estrellas)
│   ├── programa_hotelero.py         # Anexo I.1 hotel/hostal/pensión/albergue (habitación)
│   ├── programa_uso.py        # `ProgramaUso` + `TipologiaUnidadDescriptor` + reparto genérico
│   ├── macro_layout.py        # Generación geométrica de unidades dentro de la planta
│   ├── interiores.py          # Layout interior (paredes, bandas) por vivienda
│   ├── adyacencias.py         # Grafo de adyacencias entre estancias
│   └── serializacion.py       # Output JSON (tablas por planta, por unidad, modal)
└── README.md                  # Este documento
```

Persistencia (en `app/plataforma/persistencia/`):
- `catalogo_superficies_sqlalchemy.py` — Anexo I.5 vivienda + parámetros motor.
- `anexo_i_apartamentos_sqlalchemy.py` — Anexo I.3 apartamentos turísticos (edificios).
- `anexo_i_apartamentos_conjuntos_sqlalchemy.py` — Anexo I.4 apartamentos (conjuntos).
- `anexo_i_hotel_apartamento_sqlalchemy.py` — Anexo I.2 hoteles-apartamento.
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
EdificioPlurifamiliar
   ├── plantas: list[Planta]               (PB, P1, P2, Ático, Sótano)
   └── parcela, lados, edificabilidad_*
        │
        ▼
calcular_capacidad(envolvente, params)     capacidad.py
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
   ├── unidades_por_planta: list[(n_dorms, util_m2)]
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

## 3. Modelo diferenciado por planta

`calcular_capacidad` (capacidad.py) recorre cada `Planta` y aplica un
modelo distinto según su tipo:

| Tipo planta | Circulación común | Patio | Local | Comportamiento |
|------------|-------------------|-------|-------|----------------|
| **PB** (primera regular) | `pct_circulacion_pb` (8 %) | Sí | `pct_local_pb` (0–100 %) | Resto disponible para viviendas |
| **Planta tipo** | `pct_circulacion_tipo` (8 %) | Sí (mismo área, no editable) | No | Multi-tipología si procede |
| **Ático** | `pct_circulacion_tipo` | No | No | `computa_edif` opcional |
| **Sótano** | 0 % | 0 | 0 | `viv = 0` forzado |

Todos descuentan también: `muros = pct_muros × construida` y
`núcleo = pct_nucleo × construida`.

---

## 4. Reparto multi-tipología (todos los usos)

Cuando el usuario elige tipologías extra (selector dinámico `+` / `−`),
`calcular_capacidad` reparte la planta entre varias tipologías. El reparto es
**use-agnóstico**: vive en
[`reparto_multi_tipologia_generico`](geometria/programa_uso.py) y opera sobre
`TipologiaUnidadDescriptor` (slug, útil objetivo/mínimo/máximo, plazas), así que
sirve igual para vivienda, apartamentos, hotel-apartamento y hotelero. Cada
unidad guarda su **propia tipología** (`Capacidad.tipologias_unidad_por_planta`),
de modo que la tabla por unidad regenera las estancias correctas de cada una en
la mezcla. `casos_uso._construir_descriptores_tipologia` arma la lista del uso
activo (tipología principal + extras, con categoría fija del proyecto).
`reparto_multi_tipologia` (vivienda, int-based) se conserva como envoltura del
genérico para el preview rápido.

**Política**:

1. Sortear las tipologías por `util_maximo` ascendente (la más pequeña
   primero).
2. Asignar 1 unidad de cada tipología si cabe en el útil restante.
3. Rellenar el sobrante con la tipología más pequeña hasta agotar.

Devuelve `list[(n_dorms, util_asignado_m2)]` — una entrada por unidad
real. El `util_asignado` se acota por `util_maximo(n_dorms)` (no excede
el techo VPO). El residual no asignable queda como espacio libre no
contabilizado.

Ejemplo con `util_disponible = 158 m²`, tipologías = `[2d, 1d]`:

```
1d primero: consume min(60, 158)  = 60 → restante 98
2d:         consume min(70, 98)   = 70 → restante 28
2d paso: 28 < util_min(1d) = 41.4 → no añade más
Resultado: [(1, 60), (2, 70)] — 2 unidades, residual 28 m²
```

`Capacidad.unidades_por_planta` guarda este detalle por planta, y
`tabla_unidad_desde_capacidad` genera una fila por unidad real (no
promedia el util/viviendas).

---

## 5. Política de escalado de estancias (última adición)

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
   - Baño = 5 m² (MIN_BANO + 2)
   - Aseo = 2.5 m² (MIN_ASEO + 1)
3. **Salón + dormitorios** escalan proporcionales a su `area_min_m2`
   para consumir el restante:
   `util_principal = util − circulación − Σ servicios`.

**Verificación aritmética (suma = `util_maximo` VPO):**

| n_dorms | salon | dorm₁ | dorm₂ | dorm₃ | cocina | baño/banos | circulación | **TOTAL** |
|---------|-------|-------|-------|-------|--------|-----------|-------------|----------|
| 1d | 20.46 | 17.54 | — | — | 8.00 | bano 5.00 | 9.00 | **60.00** |
| 2d | 20.67 | 15.50 | 10.33 | — | 8.00 | bano 5.00 | 10.50 | **70.00** |
| 3d | 23.87 | 15.91 | 10.61 | 10.61 | 8.00 | bano₁ 5 + aseo 2.5 | 13.50 | **90.00** |

**Estudio (n_dorms = 0)** — rediseño completo: salón+cocina+cama en un
único `espacio_principal`. Suma fija = 25 m² (umbral VPO mínimo
excluyendo servicios comunes).

```
espacio_principal = 18 m²  (mínimo VPO 14)
bano              =  4 m²  (mínimo VPO 3)
circulacion_interior = 3 m²
TOTAL = 25 m² (util_maximo VPO)
```

`util_minimo_vivienda(0)` = `max(25, sum_min × 1.15)` — garantiza ≥ 25
en cualquier caso.

---

## 6. Persistencia de la política en BBDD

Toda la política (mínimos VPO, targets y porcentajes) vive en BBDD para
no estar hardcodeada en código.

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

### Carga en arranque

[`aplicacion.py`](../../entrypoints/web/aplicacion.py) llama a
[`programa.cargar_desde_repo(catalogo)`](geometria/programa.py)
después de `init_db()`. El catálogo expone `consolidadas_vivienda()`
que devuelve un dict con todos los valores: la función rellena las
constantes module-level (`MIN_DORM_DOBLE`, `UTIL_MAX`,
`AREA_TARGET_VIVIENDA`, `PCT_CIRCULACION_INTERIOR_VIVIENDA`, …).

### Migración SQLite

[`sqlalchemy_base.py::_migracion_sqlite_idempotente`](../../plataforma/persistencia/sqlalchemy_base.py)
aplica `ALTER TABLE ... ADD COLUMN` envuelto en try/except. Idempotente:
detecta si la columna ya existe consultándola; si falla, la añade. Las
filas no editadas por el usuario se resincronizan en cada seed.

---

## 7. Tabla "por unidad" vs tabla "por planta"

| Concepto | Tabla por planta | Tabla por unidad |
|----------|------------------|-------------------|
| Muros (`pct_muros`) | Sí (m² total) | Sí (prorrateados por util) |
| Circulación común (`pct_circ_pb/tipo`) | Sí (común planta) | **No** (no es de la unidad) |
| Núcleo (`pct_nucleo`) | Sí (común edificio) | **No** |
| Patio | Sí (descuento planta) | **No** |
| Local PB | Sí (m² destinados) | Fila "Local" sin estancias |
| Útil | Suma del útil consumido | Útil real por unidad |
| Construida | `Σ construida_planta` | `util + muros` |
| Circulación interior (15 % del util) | Implícita en "Útil" | Estancia del detalle |

**Decisión de junio 2026**: la circulación común y el núcleo son
del edificio. No se imputan a la unidad. Sólo los muros perimetrales
sí se prorratean (proporcionales al útil de cada vivienda).

---

## 8. Validador de círculo inscrito en estancias

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

## 9. Avisos / cumplimiento

[`ValidarCumplimiento`](casos_uso.py) compara los valores del proyecto
contra la normativa archivada activa. Tipos de comparación:

- **SUPERIORES** (proyecto > normativa → incumplimiento): coef. edif.,
  ocupación, nº plantas, retranqueos, luz patio, Ø vestíbulo, espesores
  máx., % muros.
- **INFERIORES** (proyecto < normativa → aviso): área patio mínima,
  % adaptadas, ancho fachada, espesor tabique, anchos pasillos, puerta.
- **FIJO** (≠ → aviso): retranqueo ático.

Los mensajes usan el identificador unificado **"Normativa"** y **no
referencian** el PDF (Anexo I/II, DB SUA, §x.x, PGOU, Decreto 194/2010
están prohibidos en los avisos de UI).

La normativa aplicada se persiste en el payload del proyecto bajo
`normativa_referencia.urbanisticos`; el backend prioriza este payload
sobre `NormativaMunicipal` archivada en BBDD.

---

## 10. Frontend

- **Canvas 2D**: dibuja parcela, plantas, núcleo, patios, lados con
  orientación cardinal (normal exterior, no azimut del segmento).
- **Pestañas de planta**: PB / P1 / P2 / Ático / S1. Parámetros
  específicos (`pct_circulacion_pb`, `pct_local_pb` solo en PB;
  `pct_circulacion_tipo` solo en planta tipo) se ocultan/muestran con
  `data-visible-en-planta`.
- **Tipologías**: selector dinámico con botón `+ Tipología` y `−` por
  fila. Persiste `tipologias_extra` como lista de slugs.
- **Tabla por planta**: columnas Plantas / Viv / Construida / Útil /
  Muros / Muros est. / Circul. / Núcleo / Patio / Local. Tooltip
  muestra mix tipología.
- **Tabla por unidad**: una fila por vivienda con su tipología (1d/2d/…)
  y `util` real; fila "Local" cuando aplica (sin estancias). Click en
  fila → modal con detalle de estancias.
- **Cache-busting**: `?v=ESTATICOS_VERSION` en CSS/JS. Subir versión
  manualmente al tocar estáticos.

---

## 11. Punto de extensión: editar la política desde la UI

`anexo_i_vivienda.editable_por_usuario` protege filas modificadas por
el usuario contra el reseed automático. La columna `area_target_m2` y
la tabla `parametros_motor_vivienda` están preparadas para futuras
pantallas de edición (panel de administración del Anexo I).

`programa.cargar_desde_repo()` se invoca al arrancar; si más adelante
se necesita recargar en caliente tras edición, basta llamarla de nuevo
con la sesión vigente.
