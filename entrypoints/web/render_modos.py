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
    # ── Hooks para diferenciar más adelante (hoy idénticos en ambos modos) ──
    # Usos del catálogo ofrecidos en este modo. Vacío = todos los del catálogo.
    usos_permitidos: tuple[str, ...] = ()
    # IDs de secciones del panel de parámetros a ocultar en este modo (la plantilla
    # las consulta; hoy vacío, así que no se oculta nada).
    secciones_ocultas: tuple[str, ...] = field(default_factory=tuple)


# Orden = orden en que aparecen los botones en la pantalla de selección.
MODOS: dict[str, ModoRender] = {
    "obra-nueva": ModoRender(
        slug="obra-nueva",
        titulo="Obra nueva",
        descripcion=(
            "Edificio de nueva planta: envolvente paramétrica, distribución y "
            "tabla de superficies calculadas desde cero sobre la parcela."
        ),
        badge="Obra nueva",
    ),
    "rehabilitacion": ModoRender(
        slug="rehabilitacion",
        titulo="Rehabilitación",
        descripcion=(
            "Intervención sobre el edificio existente de la parcela, partiendo "
            "de su estado actual."
        ),
        badge="Rehabilitación",
    ),
}

# Si la URL no trae modo válido, se muestra la pantalla de selección (landing).
MODO_POR_DEFECTO = "obra-nueva"


def modo_o_none(slug: str | None) -> ModoRender | None:
    """Devuelve la configuración del modo o None si el slug no es válido."""
    if not slug:
        return None
    return MODOS.get(slug)
