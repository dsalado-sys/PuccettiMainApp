# app/ — Main App Puccetti

Integración de las funcionalidades de prefactibilidad sobre una arquitectura
hexagonal con screaming architecture (ver `Info/puccetti-arquitecturaSoftware.md`).

**Independencia**: la app no importa código de directorios hermanos. Cuando se
reutilice lógica ya escrita en versiones previas (Streamlit u otras), se
**copia** dentro de `contextos/` y `plataforma/`, nunca se referencia desde
fuera. Ver `Info/CLAUDE.md §Arquitectura del código`.

## Estructura

```
app/
├── nucleo/                     # shared kernel: lenguaje ubicuo + normativa
│   └── modelo/
│       ├── proyecto.py         # Aggregate root (§2.11)
│       └── rol.py              # Rol + matriz de permisos
├── contextos/                  # un subdirectorio por §x.y del PDF
│   └── proyectos/              # §2.11 — puertos + casos de uso
├── plataforma/                 # adapters driven
│   └── persistencia/
│       ├── sqlalchemy_base.py        # engine + Base + sessionmaker + init_db
│       ├── proyectos_sqlalchemy.py   # adapter por defecto (SQLite vía SQLAlchemy 2.x)
│       └── proyectos_en_memoria.py   # solo para tests
└── entrypoints/
    └── web/                    # FastAPI + Jinja2 + JS vanilla
        ├── aplicacion.py       # composition root
        ├── catalogo_modulos.py # única fuente de verdad del menú
        ├── dependencias.py     # sesión, rol, proyecto activo, repos
        ├── plantillas.py       # Jinja2Templates + cache-busting
        ├── rutas/
        ├── static/css/
        └── templates/
```

Las carpetas `localizacion/`, `viabilidad/`, `render_calculos/`, `modelos_planos/`,
`informe/` se crearán como contextos a medida que vayamos integrando cada módulo.

## Persistencia

Detrás del puerto `ProyectoRepositorio`. Adapter por defecto:
`ProyectosSQLAlchemy` sobre SQLite (`app/data/puccetti.sqlite`, gitignorable).
Sustituir por Postgres pasa por cambiar `PUCCETTI_DB_URL` y nada más; ni dominio
ni casos de uso saben qué BBDD hay debajo. `ProyectosEnMemoria` se mantiene
para tests, no en el wiring de la app.

Variable de entorno: `PUCCETTI_DB_URL` (por defecto `sqlite:///app/data/puccetti.sqlite`).

## Sesión

- Rol activo: cookie `puccetti_rol` (`arquitecto` | `financiero` | `inversor`).
  Cuando exista login real, `rol_activo()` en `dependencias.py` consultará al
  `UsuarioRepositorio` en su lugar — la firma no cambia.
- Proyecto activo: cookie `puccetti_proyecto` con el `proyecto.id`. Cada módulo
  leerá el proyecto activo por dependencia (`exige_proyecto`) y escribirá sus
  datos en `proyecto.datos(ModuloPuccetti.XXX)`. Los módulos se comunican
  por el aggregate, no entre sí.

## Permisos

`nucleo/modelo/rol.py::MATRIZ_PERMISOS` es la única fuente de verdad para
"¿este rol puede entrar a este módulo?". Las plantillas la consultan vía la
función `acceso(rol, modulo)`; las rutas vía `puede_acceder(...)`.

Si un módulo añade una acción que requiera un permiso nuevo, añadirlo al enum
`PermisoModulo` antes que a las rutas.

## Cache-busting

`plantillas.py::ESTATICOS_VERSION` es el `?v=` que `base.html` añade a CSS/JS.
Subirlo manualmente al tocar estáticos.

## Arranque

```powershell
python -m pip install -r app/requirements.txt
python -m app.run
# → http://127.0.0.1:8080
```
