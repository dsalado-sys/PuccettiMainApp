# app/ — Main App Puccetti

Integración de las funcionalidades de prefactibilidad sobre arquitectura
**hexagonal + screaming architecture** (ver `Info/puccetti-arquitecturaSoftware.md`).
Mapa de raíz del repo: `../CLAUDE.md`. Objetivo de este archivo: poder trabajar
dentro de `app/` **sin re-explorar**.

**Independencia (regla nuclear)**: la app NO importa código de directorios
hermanos (`Modulos/`, `Antiguo/`). Cuando se reutiliza lógica previa se **copia**
dentro de `contextos/` o `plataforma/`, nunca se referencia desde fuera. Caso real:
`render_calculos` duplica a propósito el cálculo de huso UTM de `localizacion`
(`_epsg_utm_para_lon`); **no deduplicar entre contextos**.

## Estructura real
```
app/
├── nucleo/modelo/            # shared kernel (lenguaje ubicuo)
│   ├── proyecto.py           # aggregate Proyecto + enums EstadoProyecto, ModuloPuccetti
│   └── rol.py                # Rol, PermisoModulo, MODULOS, MATRIZ_PERMISOS, AccesoModulo, puede_acceder/acceso
├── contextos/                # un bounded context por §x.y (dominio puro)
│   ├── localizacion/         # §2.1  dominio/puertos/casos_uso + geometria.py (fichero plano)
│   ├── viabilidad/           # §2.9  dominio/casos_uso (sin puertos.py) — único __init__ con __all__
│   ├── render_calculos/      # §2.4–2.7 dominio/puertos/casos_uso/parametros + geometria/ (subpaquete 14+ módulos) + README.md
│   ├── proyectos/            # §2.11 puertos/casos_uso (SIN dominio: el aggregate vive en nucleo/)
│   └── usuarios/             # login real: dominio/puertos/casos_uso + seguridad.py (PBKDF2)
├── plataforma/               # adapters driven (implementan los puertos)
│   ├── persistencia/         # SQLAlchemy/SQLite: ~14 tablas + seeds (ver §Persistencia)
│   ├── catastro/catastro_meh.py   # CatastroMEH (CatastroPort) — REST + ESCatastroLib
│   └── cache/parcelas_en_memoria.py # ParcelasEnMemoria (cache LRU efímero)
├── entrypoints/web/          # FastAPI + Jinja2 + JS vanilla
│   ├── aplicacion.py         # composition root (crear_app, app); middlewares, routers
│   ├── dependencias.py       # DI: sesión, repos, casos de uso, usuario/rol/proyecto activos
│   ├── catalogo_modulos.py   # única fuente de verdad del menú (CATALOGO)
│   ├── render_modos.py       # 3 modos del módulo Render (obra-nueva/rehabilitacion/inmueble)
│   ├── plantillas.py         # Jinja2Templates + estaticos_version (cache-busting automático por mtime)
│   ├── rutas/                # 8 routers (ver §Rutas HTTP)
│   ├── templates/  static/css/  static/js/
├── tests/                    # pytest (contextos/ + plataforma/) — ver §Tests
├── data/puccetti.sqlite      # BBDD (SE TRACKEA en git, ver §Persistencia)
└── run.py  requirements.txt
```
Pendientes de integrar como contexto: **solo** `modelos_planos` (desactivado en el
catálogo) e `informe` (stub de ruta `/modulos/informe`). El resto ya existe.

## Núcleo: aggregate Proyecto y comunicación inter-módulos
`nucleo/modelo/proyecto.py` — `Proyecto` es una **dataclass de dominio puro** (sin
SQLAlchemy), el **bus de información entre módulos**:
- Campos: `nombre`, `referencia_catastral`, `direccion`, `estado` (=`BORRADOR`),
  `id` (`uuid4().hex`), `creado_en`/`actualizado_en` (UTC), `creado_por`,
  `datos_por_modulo: dict[str, dict[str, Any]]` (JSON libre por módulo; el núcleo no valida su forma).
- Métodos: **escribir** con `fijar_datos(ModuloPuccetti.X, dict)` (reemplaza el rincón
  + `tocar()`); **leer** con `proyecto.datos_por_modulo.get(ModuloPuccetti.X.value)`
  (read-only, no crea la clave). `datos(modulo)` (setdefault, MUTA al leer) es marginal — evitarlo.
- `EstadoProyecto(str,Enum)`: `borrador, en_analisis, entregado, archivado`.
- `ModuloPuccetti(str,Enum)` = **catálogo de 7 módulos**: `localizacion, viabilidad,
  render_calculos, modelos_planos, informe, proyectos, normativa_municipal`
  ("Estable: añadir nunca renombrar").

**Ningún contexto importa a otro**: se comunican leyendo/escribiendo el mismo
aggregate, indexado por `ModuloPuccetti.value`. `viabilidad` y `render_calculos` NO
tienen repositorio propio para su resultado: persisten en el aggregate (viabilidad
solo guarda **parámetros**, se recalcula). Ej. verificado: render_calculos lee
`LOCALIZACION` y `VIABILIDAD`, escribe `RENDER_CALCULOS`.

Fachada `nucleo/modelo/__init__.py` re-exporta SOLO: `Proyecto, EstadoProyecto,
ModuloPuccetti, Rol, PermisoModulo, MATRIZ_PERMISOS, puede_acceder`. `acceso`,
`AccesoModulo`, `MODULOS` se importan desde `app.nucleo.modelo.rol`.

## Roles y permisos
`nucleo/modelo/rol.py` es la **única fuente de verdad de autorización**:
- `Rol(str,Enum)`: `arquitecto, financiero, inversor`. `PermisoModulo`: `ver, editar`.
- `MATRIZ_PERMISOS: dict[Rol, dict[slug_str, frozenset[PermisoModulo]]]` — **la clave
  de módulo es un slug `str` (= `ModuloPuccetti.value`), NO el enum**; por eso los
  llamantes pasan `ModuloPuccetti.X.value`. ARQUITECTO: VER+EDITAR en los 7.
  FINANCIERO: VER+EDITAR en viabilidad/informe, VER en otros, sin acceso a modelos_planos.
  INVERSOR: VER en todos salvo modelos_planos; nunca EDITAR.
- `puede_acceder(rol, slug, permiso=VER)->bool` (lo usan las rutas). `acceso(rol,
  slug)->AccesoModulo(modulo, puede_ver, puede_editar)` (lo llama `rutas/menu.py`
  para pintar tarjetas; la plantilla recibe el objeto, no importa la función).
- **Fail-closed**: rol/módulo desconocido → `frozenset()` → deniega (silencioso ante typos de slug).
- ⚠️ Al añadir un módulo hay que sincronizar a mano **TRES listas paralelas**: el enum
  `ModuloPuccetti` (proyecto.py), la tupla `MODULOS` (rol.py, no importa el enum) y las
  claves de `MATRIZ_PERMISOS` — más la tarjeta en `catalogo_modulos.py`.
- ⚠️ El docstring de `rol.py` ("autenticación se implementará más adelante") está
  **obsoleto**: el login real ya existe (`contextos/usuarios`).

## Contextos (detalle)
- **localizacion §2.1** — `dominio.py` (Parcela/Lado/Subreferencia, `TipoLado`
  FACHADA/MEDIANERA, `ORIENTACIONES`, excepciones `ParcelaError/RateLimitCatastro/...`);
  `puertos.py` (`CatastroPort`, `ParcelaTemporalRepositorio`, `CallejeroPort`);
  `casos_uso.py` (`LocalizarPorRC/Direccion/Coordenada`, `SimplificarContorno`,
  `CorregirLado/Orientacion`, `SeleccionarInmueble`, `CargarDetalleSubreferencia`);
  `geometria.py` (fichero plano). Enriquecimiento de subreferencias **lazy** (se eliminó
  `CargarTodosLosDetalles` para no quemar la cuota Catastro).
- **viabilidad §2.9** — `dominio.py` (`Operacion` VENTA/RENTA, `Intervencion`
  OBRA_NUEVA/REHABILITACION, `FuenteSuperficie`, `ParametrosEconomicos`,
  `EstudioViabilidad`; defaults: venta 3200 €/m², obra nueva 1400, rehab 900);
  `casos_uso.py` (`CalcularViabilidad`, puro, sin repo). **Único `__init__.py` con
  `__all__`** → se importa desde el paquete.
- **render_calculos §2.4–2.7** — `dominio.py` (`UsoEdificio`
  vivienda/hotelero/apartamentos_turisticos + enums de categoría/tipología; `Alerta`,
  `NivelAlerta` ∈ error/incumplimiento/aviso/info); `parametros.py` (parser MUY
  tolerante con compat de JSON antiguo; cota `N_PLANTAS_LIMITE=60` anti-DoS);
  `puertos.py` (4 catálogos: Normativa/Superficies/Apartamentos/Hotelero `Repositorio`);
  `casos_uso.py` (`CalcularEnvolvente/Layout/TipologiasDormitorios/EstanciasInmueble`,
  `ValidarCumplimiento`, `GuardarRender`); `geometria/` (subpaquete ~11 módulos, motor aislado de
  FastAPI/SQLAlchemy); **`README.md` propio** (doc de detalle). Lee los mínimos vivos de
  BBDD en CADA cálculo (`_sincronizar_minimos`, §3.8); sin globals.
- **proyectos §2.11** — sin `dominio.py` (aggregate en `nucleo/`); `ProyectoRepositorio`;
  `CrearProyecto/ListarProyectos/ObtenerProyecto/EliminarProyecto`.
- **usuarios** — `Usuario(usuario, hash_contraseña, rol=ARQUITECTO, activo)`;
  `UsuarioRepositorio`; `AutenticarUsuario`; `seguridad.py` PBKDF2-HMAC-SHA256 stdlib
  (`pbkdf2_sha256$240000$<salt>$<hash>`).

**Convención de imports**: salvo `viabilidad` (tiene `__all__`), importar desde el
submódulo concreto: `from app.contextos.localizacion.casos_uso import LocalizarPorRC`.
Solo `render_calculos/` tiene README de detalle.

## Persistencia
`plataforma/persistencia/sqlalchemy_base.py`: `Base` (DeclarativeBase), `engine` +
`SessionLocal` vía `crear_db(url)` (lee `PUCCETTI_DB_URL`; StaticPool+
check_same_thread=False solo para SQLite en memoria). **`init_db()` = `Base.metadata.
create_all` + siembra** (callejero INE, normativa Sevilla, catálogos Anexo I,
usuarios). Hay que registrar cada ORM en `_registrar_modelos()` o `create_all` no lo crea.
- ⚠️ **Alembic NO se usa**: `app/alembic/` está vacío (solo `.pyc`, sin `.ini` ni
  revisiones, fuera de git — borrado deliberado). NO hay migraciones: cambiar el esquema
  sobre una BBDD existente = borrar/migrar a mano. El comentario de `sqlalchemy_base.py`
  que aún cita Alembic está stale.
- **Tablas (~14)**: `proyectos, usuarios, normativa_municipal, anexo_i_vivienda,
  parametros_motor_vivienda, anexo_i_apartamentos, anexo_i_apartamentos_conjuntos,
  anexo_i_hotelero, provincias_ine, municipios_ine, carpeta_proyecto, proyecto_en_carpeta,
  carpeta_normativa, normativa_archivada`.
- **Adapters**: `ProyectosSQLAlchemy` (default), `ProyectosEnMemoria` (solo tests),
  `UsuariosSQLAlchemy`, `NormativaMunicipalSQLAlchemy`,
  `CatalogoSuperficies/Apartamentos/HoteleroSQLAlchemy`, `CallejeroSQLAlchemy`,
  `CarpetasProyecto/NormativaSQLAlchemy`; + `CatastroMEH`, `ParcelasEnMemoria`.
  Cambiar a Postgres = cambiar `PUCCETTI_DB_URL` y nada más (dominio/casos de uso no saben qué BBDD hay).
- **Seeds** idempotentes (por "tabla vacía") y `reset()` atómico por catálogo. Las filas
  Anexo I **se derivan** de `geometria.programa*` (no son literales): editar mínimos en
  código se hace ahí. Mínimos globales de vivienda se **propagan** a todas las tipologías al editar.
- Detalles que muerden: apartamentos = **dos tablas físicas** (edificios A1.3 / conjuntos
  A1.4) por la PK de SQLite, un solo adapter enruta por `grupo`; borrar `carpeta_proyecto`
  solo DESVINCULA (no toca `proyectos`), borrar `carpeta_normativa` SÍ borra sus normativas
  (delete manual, SQLite sin CASCADE).
- **`data/puccetti.sqlite` SE TRACKEA en git** (decisión explícita; NO es "gitignorable").
  Conviven backups no esenciales (`.json`, `.bak` gitignorado) en `data/`.

## Catastro (`plataforma/catastro/catastro_meh.py`)
`CatastroMEH` (CatastroPort): RC/coordenada/dirección, vecinos, vías, detalle de
subreferencia; usa ESCatastroLib + REST.
- **URLs canónicas**: `ovc.catastro.meh.es` — NUNCA `.meta.minhap.es` (no resuelve) ni
  `minhap.es` (SSL inválido).
- `_superficie_catastro()` parsea **formato español** (punto=millar, coma=decimal):
  `float()` directo rompe en ≥1000 m²; se recalcula desde regiones/subreferencias.
- **`RateLimitCatastro`** por IP (403 REST o "Petición denegada" con HTTP 200 en WCF).
  Patios (WFS BU) son best-effort y **se tragan el rate limit a propósito** (no quemar la API).
- Nombres con tildes → 0 resultados; se quitan antes de buscar. **No ejecutar probes en vivo.**

## Capa web
- `aplicacion.py` (composition root): `crear_app(engine=None, session_factory=None)`
  llama `init_db`, monta `/static`, añade middleware `seguridad_http` (CSRF mismo-origen
  + redirección 303 a `/login` si no hay `session['usuario_id']`) y `SessionMiddleware`
  **después** (capa más externa). `RUTAS_PUBLICAS=('/login','/logout','/static')`.
  En tests se cablea vía `app.dependency_overrides[obtener_session_factory]`.
- `dependencias.py` (DI): `usuario_actual`, `rol_activo` (deriva de `usuario_actual().rol`;
  sin usuario → `ROL_POR_DEFECTO=Rol.INVERSOR`, defensa en profundidad — ⚠️ el docstring
  dice "arquitecto por defecto" pero el código usa INVERSOR), `proyecto_activo`,
  `exige_proyecto` (409 si no hay proyecto activo). Adapters singleton + casos de uso.
- `render_modos.py`: 3 modos del módulo Render — `obra-nueva`, `rehabilitacion`,
  `inmueble`; `MODO_POR_DEFECTO='obra-nueva'`. `inmueble` es **auto-derivado** (solo si en
  §2.1 se eligió un inmueble concreto; si no, cae a la landing).
- `catalogo_modulos.py`: `CATALOGO` = 6 tarjetas (localizacion, viabilidad,
  render_calculos, informe, normativa_municipal, proyectos); **modelos_planos comentado**.
- **Cookies**: `puccetti_proyecto` (proyecto activo, httponly+lax) y
  `puccetti_parcela_temp` (parcela temporal de localización, max_age 4h).
  **Claves de sesión**: `usuario_id, usuario, rol`. Form de login: campo `contraseña`
  (con ñ), no `password`. Throttling 5 intentos/15 min por IP+usuario; `session.clear()`
  anti-fijación.
- **Cache-busting**: el `?v=` que las plantillas añaden a CSS/JS es **automático**:
  `plantillas.py` expone `estaticos_version` como un wrapper que se reevalúa en cada
  render y deriva del mtime más reciente de `static/`. **No hay que tocar nada al editar
  estáticos** (en dev el cambio se refleja sin reiniciar).
- `templates/`: base, login, menu, modulo_pendiente, localizacion, proyectos,
  normativa_municipal, viabilidad, render_calculos(+_landing) y parciales `_rc_*`.
  `static/css/` y `static/js/` (incl. `rc_canvas.js`, `rc_brujula.js`).

## Rutas HTTP (8 routers, en el orden de `aplicacion.py`)
- **autenticacion** (sin prefix): `GET/POST /login`, `POST /logout`.
- **menu** (sin prefix): `GET /` (menú), `POST /sesion/proyecto`.
- **proyectos** `/proyectos`: `GET ''|/datos`, `POST ''`, `DELETE /{id}`,
  `POST /{id}/carpeta|/{id}/activar|/desactivar|/carpetas`, `DELETE /carpetas/{id}`.
- **localizacion** `/modulos/localizacion`: `GET ''`, `POST /buscar/{rc|direccion|coordenada}`,
  `/simplificar`, `/lado/{i}/{tipo|orientacion}`, `/subreferencia/{rc20}/detalle`,
  `/seleccionar-inmueble`, `/guardar-como-proyecto`; `GET /callejero/{provincias|municipios|vias}`.
- **viabilidad** `/modulos/viabilidad`: `GET ''`, `POST /calcular` (preview JSON, no
  persiste), `POST /guardar` (persiste en aggregate).
- **render_calculos** `/modulos/render-calculos`: `GET ''` (`?modo=` → landing o render),
  `POST /preview|/calcular|/estancias|/tipologias-dormitorios|/guardar|/aplicar-normativa`;
  `GET/POST /normativa[...]` (LEGADO, solo consulta), `/superficies-vivienda[/reset]`,
  `/minimos/{uso}[/reset]`, `POST /export.csv`.
- **normativa_municipal** `/modulos/normativa-municipal`: CRUD carpetas + normativas archivadas.
- **modulos** `/modulos`: solo `GET /modulos/informe` (stub). `modelos_planos` no tiene ruta.

## Tests
```powershell
python -m pytest app/tests          # desde la raíz del repo (los tests importan `app.*`)
python -m pytest app/tests -q
python -m pytest app/tests --collect-only -q   # recuento exacto
```
16 ficheros `test_*.py` (~150 casos con parametrize; sobre todo `contextos/render_calculos/`).
No hay `pytest.ini`/`pyproject`; pytest autodetecta rootdir y resuelve `app.*` por los `__init__.py`.
- `conftest.py` fija `PUCCETTI_DB_URL=sqlite://` (memoria) y `PUCCETTI_ENV=dev` **antes**
  de importar la app, así el `app = crear_app()` a nivel de módulo nunca toca
  `data/puccetti.sqlite`. Fixtures: `engine_memoria`, `session` (rollback al cerrar),
  `client` (TestClient **no** autenticado → rutas no públicas redirigen a /login),
  `cliente_autenticado(Rol)` (login **real** vía `POST /login`), `sembrar_usuario`;
  `CLAVE_PRUEBA='Prueba-1234'`; autouse resetea el throttling entre tests.
- Convenciones: **integración usa SQLite en memoria real sembrada** (NO se mockea la
  BBDD; `ProyectosEnMemoria` solo para unitarios). Tests de catastro son funciones puras
  sobre mocks: **no pegar al Catastro en vivo**.
- Añadir test: `app/tests/<capa>/<contexto>/test_<algo>.py` (+`__init__.py` si la carpeta
  es nueva), `from __future__ import annotations`, importar el SUT de su paquete público,
  `pytest.approx` para floats, `@pytest.mark.parametrize`. BBDD → `session`/`engine_memoria`;
  HTTP → `client`/`cliente_autenticado(Rol.X)`. Nunca llamar al Catastro real ni escribir en `data/`.

## Variables de entorno
- Persistencia/seed: `PUCCETTI_DB_URL` (def `sqlite:///app/data/puccetti.sqlite`),
  `PUCCETTI_ADMIN_USER`/`PUCCETTI_ADMIN_PASSWORD` (def `Arquitecto0`/`Arquitecto0`, solo
  siembra si la tabla está vacía).
- Sesión/seguridad: `PUCCETTI_SECRET_KEY` (**obligatoria en prod**), `PUCCETTI_ENV`
  (`dev`/`prod`), `PUCCETTI_SECURE_COOKIES`, `PUCCETTI_SESION_MAX_AGE` (def 3600).
- Arranque: `PUCCETTI_HOST` (127.0.0.1), `PUCCETTI_PORT` (8080), `PUCCETTI_RELOAD` (True).

## Arranque
```powershell
python -m pip install -r app/requirements.txt
python -m app.run        # → http://127.0.0.1:8080 (reload). También: `py run.py` desde app/, o uvicorn directo
```

## Cómo añadir un módulo/contexto nuevo (checklist)
1. **Dominio**: añadir el valor a `ModuloPuccetti` (`nucleo/modelo/proyecto.py`) — añadir, nunca renombrar.
2. **Permisos**: añadir el slug a `MODULOS` y a `MATRIZ_PERMISOS` para cada `Rol` (las TRES listas sincronizadas; fail-closed si falta).
3. **Menú**: añadir `TarjetaModulo` a `CATALOGO` (`catalogo_modulos.py`).
4. **Contexto**: `app/contextos/<modulo>/` con `dominio.py`/`puertos.py`/`casos_uso.py` (importar por submódulo salvo que añadas `__all__`).
5. **Adapter(s)**: implementar el/los puerto(s) en `plataforma/...`; si hay ORM nuevo, registrarlo en `_registrar_modelos()` y añadir seed idempotente si procede.
6. **Web**: router en `entrypoints/web/rutas/<modulo>.py` con su prefix, incluirlo en `aplicacion.py`, plantilla(s) + estáticos (el cache-busting `?v=` es automático, no hay que tocarlo).
7. Persistir resultados en el aggregate vía `proyecto.fijar_datos(ModuloPuccetti.X, dict)` salvo que justifique repositorio propio.

## Mantenimiento de este archivo
Actualízalo **solo cuando el cambio sea importante y deba entrar en contexto en futuras
sesiones**: nueva tabla/adapter, nuevo contexto o router, cambio de arranque/tests/env,
o una convención transversal. Los cambios menores no se documentan aquí. Mantenlo como
mapa preciso, no como volcado del código.
