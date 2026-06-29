"""Configuración declarativa de los modos del módulo «Render y cálculos».

El módulo se abre en uno de dos modos —**Obra nueva** y **Rehabilitación**— que
hoy comparten la MISMA pantalla (ambos abren lo mismo). En lugar de duplicar la
plantilla o el JS, cada modo se describe con un objeto de configuración: la
pantalla es dinámica y se dibuja a partir de estos campos.

Para diferenciar los modos en el futuro basta editar AQUÍ la entrada del modo
correspondiente (su título, los usos que ofrece, las secciones que oculta, etc.).
El motor de cálculo (`contextos/render_calculos/geometria/`) permanece intacto y
separado: estos modos solo afectan a qué se muestra y qué opciones se ofrecen.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModoRender:
    """Qué necesita un modo del módulo Render y cálculos.

    Campos de identidad (`slug`, `titulo`, `descripcion`, `badge`, `nota`) y
    *hooks* de configuración (`usos_permitidos`, `secciones_ocultas`) pensados
    para que los dos modos puedan divergir editando solo esta estructura.
    """

    slug: str                         # identificador en la URL (?modo=...)
    titulo: str                       # título mostrado en el hero de la pantalla
    descripcion: str                  # texto del botón en la pantalla de selección
    badge: str = ""                   # etiqueta corta opcional junto al título
    nota: str = ""                    # aclaración opcional bajo el hero
    # ── Hooks para diferenciar los modos ──
    # Usos del catálogo ofrecidos en este modo. Vacío = todos los del catálogo.
    usos_permitidos: tuple[str, ...] = ()
    # Claves de bloques del panel de parámetros a ocultar en este modo. La plantilla
    # `_rc_panel_params.html` las consulta (`modo.secciones_ocultas`) y omite del DOM
    # los campos cuya clave aparezca aquí. Claves soportadas hoy:
    #   "edificabilidad" · "ocupacion" · "retranqueos"  (sub-bloques de Urbanismo)
    #   "urbanismo"        → oculta el grupo «Urbanismo» entero
    #   "atico_sotano"     → oculta el grupo «Ático y sótano»
    #   "circulacion_comun"→ oculta el % de circulación común del edificio (Diseño)
    #   "nucleo"           → oculta el % de núcleo del edificio (Diseño)
    secciones_ocultas: tuple[str, ...] = field(default_factory=tuple)
    # ¿Trabaja este modo sobre un inmueble concreto (estancias de UNA unidad) en vez
    # de sobre el edificio completo de la parcela? Cambia la pantalla: sin canvas de
    # plantas, una sola tabla de estancias a la derecha, y cálculo desde la construida
    # del inmueble (no footprint×plantas). Se activa solo cuando hay inmueble elegido.
    es_inmueble: bool = False


# Orden = orden en que aparecen los botones en la pantalla de selección.
MODOS: dict[str, ModoRender] = {
    "obra-nueva": ModoRender(
        slug="obra-nueva",
        titulo="Obra nueva",
        descripcion=(
            " "
        ),
        badge="Obra nueva",
    ),
    "rehabilitacion": ModoRender(
        slug="rehabilitacion",
        titulo="Rehabilitación",
        descripcion=(
            " "
        ),
        badge="Rehabilitación",
        nota=(
            "La envolvente parte del edificio existente: la edificabilidad, la "
            "ocupación y los retranqueos del PGOU no se editan en este modo."
        ),
        # La envolvente la fija el edificio existente, no el PGOU: estos parámetros
        # de obra nueva no aplican y se ocultan del panel.
        secciones_ocultas=("edificabilidad", "ocupacion", "retranqueos"),
    ),
    "inmueble": ModoRender(
        slug="inmueble",
        titulo="Inmueble · estancias",
        descripcion=(
            "Intervención sobre un inmueble concreto de la parcela: se trabaja con "
            "su superficie construida y se distribuyen sus estancias."
        ),
        badge="Inmueble",
        nota=(
            "El cálculo parte de la superficie construida del inmueble: no hay "
            "urbanismo ni envolvente de edificio. Solo se distribuyen las estancias "
            "de esta unidad descontando muros y circulación interior."
        ),
        # Un inmueble no tiene urbanismo (lo fija el edificio existente) ni reparto en
        # plantas. Solo aplican los % de muros y circulación interior de la unidad.
        secciones_ocultas=(
            "urbanismo", "atico_sotano", "circulacion_comun", "nucleo",
            "edificabilidad", "ocupacion", "retranqueos",
        ),
        es_inmueble=True,
    ),
}

# Si la URL no trae modo válido, se muestra la pantalla de selección (landing).
MODO_POR_DEFECTO = "obra-nueva"


def modo_o_none(slug: str | None) -> ModoRender | None:
    """Devuelve la configuración del modo o None si el slug no es válido."""
    if not slug:
        return None
    return MODOS.get(slug)
