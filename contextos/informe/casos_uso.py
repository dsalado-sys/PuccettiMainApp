"""Ensamblado del informe (§2.8) — caso de uso PURO, sin I/O.

`EnsamblarInforme` recibe dicts ya extraídos por la capa web (composition root) y
produce un `Informe`. No lee catálogos, ni BBDD, ni recalcula nada: solo proyecta
lo que ya existe, decidiendo el `EstadoSeccion` de cada bloque según qué datos hay.
Si un dato no existe, la sección se marca `PENDIENTE`/`RESERVADA` con una
`nota_pendiente` explícita — nunca se inventa una cifra.

Espejo de `flujo.calcular_flujo`: los contextos no se importan entre sí; el router
reúne las cuatro esquinas del aggregate (`localizacion`, `render_calculos`,
`viabilidad`, `informe`) y las pasa aquí.

El ORDEN de las secciones es el de la estructura mínima del requisito (§2.8):
ficha · urbanismo · planimetría · volumetría · superficies · alertas · financiera.
"""
from __future__ import annotations

from typing import Any

from app.nucleo.modelo import ModuloPuccetti, Proyecto

from .dominio import EstadoSeccion, Informe, SeccionInforme
from .planimetria_svg import bbox_de, planta_a_svg

# ─── Parámetros urbanísticos que se muestran en el informe (§2 del documento) ──
# (clave en el snapshot, etiqueta legible, unidad, nº de decimales). Solo se
# listan si existen realmente en el snapshot aplicado.
_URBANISTICOS_VISIBLES: list[tuple[str, str, str, int]] = [
    ("coeficiente_edificabilidad", "Edificabilidad", "m²t/m²s", 2),
    ("ocupacion_maxima_pct", "Ocupación máx. (planta baja)", "%", 0),
    ("ocupacion_maxima_pct_tipo", "Ocupación máx. (plantas tipo)", "%", 0),
    ("n_plantas_max", "Nº máximo de plantas", "", 0),
    ("retranqueo_fachada_m", "Retranqueo a fachada", "m", 2),
    ("retranqueo_linderos_m", "Retranqueo a linderos", "m", 2),
    ("retranqueo_atico_m", "Retranqueo de ático", "m", 2),
    ("area_patio_min_m2", "Superficie mínima de patio", "m²", 2),
    ("luz_recta_patio_min_m", "Luz recta mínima de patio", "m", 2),
    ("ancho_min_fachada_m", "Ancho mínimo de fachada", "m", 2),
]


def _filas_urbanisticas(urb: dict[str, Any]) -> list[dict[str, Any]]:
    filas: list[dict[str, Any]] = []
    for clave, etiqueta, unidad, decimales in _URBANISTICOS_VISIBLES:
        if clave in urb and urb.get(clave) is not None:
            filas.append({
                "etiqueta": etiqueta, "valor": urb.get(clave),
                "unidad": unidad, "decimales": decimales, "numerico": True,
            })
    usos = urb.get("usos_permitidos")
    if isinstance(usos, list) and usos:
        filas.append({
            "etiqueta": "Usos permitidos",
            "valor": ", ".join(str(u) for u in usos),
            "unidad": "", "decimales": 0, "numerico": False,
        })
    return filas


class EnsamblarInforme:
    """Ensambla el `Informe` de un proyecto a partir de sus datos ya trazados."""

    def ejecutar(
        self,
        *,
        proyecto_meta: dict[str, Any],
        localizacion: dict[str, Any] | None,
        normativa: dict[str, Any] | None,
        resultado_layout: dict[str, Any] | None,
        escenario_meta: dict[str, Any] | None,
        viabilidad: dict[str, Any] | None,
    ) -> Informe:
        secciones = [
            self._ficha(localizacion),
            self._urbanismo(normativa),
            self._planimetria(resultado_layout),
            self._volumetria(),
            self._superficies(resultado_layout),
            self._alertas(resultado_layout),
            self._financiera(viabilidad),
        ]
        esc = escenario_meta or {}
        return Informe(
            proyecto_id=str(proyecto_meta.get("id") or ""),
            proyecto_nombre=str(proyecto_meta.get("nombre") or "Proyecto"),
            referencia_catastral=proyecto_meta.get("referencia_catastral"),
            direccion=proyecto_meta.get("direccion"),
            generado_por=proyecto_meta.get("generado_por"),
            generado_el=proyecto_meta.get("generado_el"),
            escenario_nombre=esc.get("nombre"),
            escenario_modo=esc.get("modo"),
            secciones=secciones,
        )

    # ─── §1 Ficha del activo ────────────────────────────────────────────────
    def _ficha(self, loc: dict[str, Any] | None) -> SeccionInforme:
        loc = loc or {}
        if not (loc.get("referencia_catastral") or loc.get("direccion")):
            return SeccionInforme(
                "ficha", "Ficha del activo", EstadoSeccion.PENDIENTE,
                nota_pendiente="Aún no hay una parcela asociada. Búscala y guárdala en Localización.",
            )
        inm = loc.get("inmueble_seleccionado")
        contenido = {
            "referencia_catastral": loc.get("referencia_catastral"),
            "direccion": loc.get("direccion"),
            "municipio": loc.get("municipio"),
            "provincia": loc.get("provincia"),
            "superficie_m2": loc.get("superficie_m2"),
            "uso_catastral": loc.get("uso_catastral"),
            "anio_construccion": loc.get("anio_construccion"),
            "superficie_construida_total_m2": loc.get("superficie_construida_total_m2"),
            "centroide_lonlat": loc.get("centroide_lonlat"),
            "inmueble_seleccionado": inm if isinstance(inm, dict) else None,
            # La imagen aérea (ortofoto PNOA) NO se persiste por proyecto todavía.
            "imagen_aerea": None,
        }
        return SeccionInforme(
            "ficha", "Ficha del activo", EstadoSeccion.DISPONIBLE, contenido,
            nota_pendiente="La imagen aérea (ortofoto PNOA) aún no se guarda por proyecto; se incorporará más adelante.",
        )

    # ─── §2 Resumen de parámetros urbanísticos ──────────────────────────────
    def _urbanismo(self, normativa: dict[str, Any] | None) -> SeccionInforme:
        normativa = normativa or {}
        urb = normativa.get("urbanisticos")
        if not isinstance(urb, dict) or not urb:
            return SeccionInforme(
                "urbanismo", "Resumen de parámetros urbanísticos", EstadoSeccion.PENDIENTE,
                nota_pendiente="Aún no se ha aplicado una normativa municipal al proyecto (módulo Render y cálculos).",
            )
        contenido = {"nombre": normativa.get("nombre"), "parametros": _filas_urbanisticas(urb)}
        return SeccionInforme(
            "urbanismo", "Resumen de parámetros urbanísticos", EstadoSeccion.DISPONIBLE, contenido,
        )

    # ─── §3 Planimetría de la propuesta ─────────────────────────────────────
    def _planimetria(self, resultado: dict[str, Any] | None) -> SeccionInforme:
        resultado = resultado or {}
        env = resultado.get("envolvente") or {}
        plantas = env.get("plantas")
        if not isinstance(plantas, list) or not plantas:
            return SeccionInforme(
                "planimetria", "Planimetría de la propuesta", EstadoSeccion.PENDIENTE,
                nota_pendiente="Sin escenario de render calculado. Calcula la envolvente en Render y cálculos.",
            )
        parcela_pol = (resultado.get("parcela") or {}).get("poligono")
        anillos = [parcela_pol] + [pl.get("footprint") for pl in plantas]
        bbox = bbox_de(*[a for a in anillos if a])
        figuras = []
        for pl in plantas:
            figuras.append({
                "nombre": pl.get("nombre"),
                "tipo": pl.get("tipo"),
                "construida_m2": pl.get("construida_m2"),
                "util_m2": pl.get("util_m2"),
                "svg": planta_a_svg(pl, bbox=bbox, parcela_poligono=parcela_pol),
            })
        return SeccionInforme(
            "planimetria", "Planimetría de la propuesta", EstadoSeccion.PARCIAL,
            {"plantas": figuras},
            nota_pendiente=(
                "Las cotas acotadas y la distribución interior (unidades, núcleo, "
                "circulación) aún no se generan; se incorporarán más adelante."
            ),
        )

    # ─── §4 Perspectiva volumétrica simplificada (más tarde) ────────────────
    def _volumetria(self) -> SeccionInforme:
        return SeccionInforme(
            "volumetria", "Perspectiva volumétrica simplificada", EstadoSeccion.PENDIENTE,
            nota_pendiente="La perspectiva volumétrica 3D aún no está disponible; se incorporará más adelante.",
        )

    # ─── §5 Tabla de superficies completa ───────────────────────────────────
    def _superficies(self, resultado: dict[str, Any] | None) -> SeccionInforme:
        resultado = resultado or {}
        tabla_planta = resultado.get("tabla_planta")
        tabla_unidad = resultado.get("tabla_unidad")
        capacidad = resultado.get("capacidad")
        if not isinstance(tabla_planta, list) or not tabla_planta:
            return SeccionInforme(
                "superficies", "Tabla de superficies completa", EstadoSeccion.PENDIENTE,
                nota_pendiente="Sin escenario de render calculado. Calcula la propuesta en Render y cálculos.",
            )
        contenido = {
            "tabla_planta": tabla_planta,
            "tabla_unidad": tabla_unidad if isinstance(tabla_unidad, list) else [],
            "capacidad": capacidad if isinstance(capacidad, dict) else {},
        }
        return SeccionInforme(
            "superficies", "Tabla de superficies completa", EstadoSeccion.DISPONIBLE, contenido,
        )

    # ─── §6 Alertas y condicionantes relevantes ─────────────────────────────
    def _alertas(self, resultado: dict[str, Any] | None) -> SeccionInforme:
        resultado = resultado or {}
        alertas = resultado.get("alertas")
        if not isinstance(alertas, list):
            return SeccionInforme(
                "alertas", "Alertas y condicionantes", EstadoSeccion.PENDIENTE,
                nota_pendiente="Sin escenario de render calculado. Las alertas se generan al calcular la propuesta.",
            )
        resumen: dict[str, int] = {}
        for a in alertas:
            nivel = str((a or {}).get("nivel") or "info")
            resumen[nivel] = resumen.get(nivel, 0) + 1
        return SeccionInforme(
            "alertas", "Alertas y condicionantes", EstadoSeccion.PARCIAL,
            {"alertas": alertas, "resumen": resumen},
            nota_pendiente=(
                "Solo se listan incumplimientos urbanísticos calculados. Las protecciones "
                "patrimoniales o ambientales (BIC, afecciones) aún no se detectan; se incorporarán más adelante."
            ),
        )

    # ─── §7 Sección reservada al análisis financiero ────────────────────────
    def _financiera(self, viabilidad: dict[str, Any] | None) -> SeccionInforme:
        viabilidad = viabilidad or {}
        if not viabilidad:
            estado_estudio, etiqueta = "sin_estudio", "Sin estudio de viabilidad todavía"
        elif viabilidad.get("aprobado"):
            estado_estudio, etiqueta = "aprobado", "Estudio de viabilidad aprobado"
        else:
            estado_estudio, etiqueta = "sin_aprobar", "Estudio de viabilidad en preparación (sin aprobar)"
        return SeccionInforme(
            "financiera", "Análisis de rentabilidad", EstadoSeccion.RESERVADA,
            {"estado_estudio": estado_estudio, "etiqueta": etiqueta},
            nota_pendiente=(
                "Sección reservada para que los asociados financieros incorporen el análisis de "
                "rentabilidad (DCF, TIR, precio máximo de compra)."
            ),
        )


# ─── Serialización para la plantilla ────────────────────────────────────────
def _seccion_a_dict(s: SeccionInforme) -> dict[str, Any]:
    return {
        "clave": s.clave,
        "titulo": s.titulo,
        "estado": s.estado.value,
        "contenido": s.contenido,
        "nota_pendiente": s.nota_pendiente,
    }


def informe_a_dict(informe: Informe) -> dict[str, Any]:
    return {
        "proyecto_id": informe.proyecto_id,
        "proyecto_nombre": informe.proyecto_nombre,
        "referencia_catastral": informe.referencia_catastral,
        "direccion": informe.direccion,
        "generado_por": informe.generado_por,
        "generado_el": informe.generado_el,
        "escenario_nombre": informe.escenario_nombre,
        "escenario_modo": informe.escenario_modo,
        "secciones": [_seccion_a_dict(s) for s in informe.secciones],
    }


# ─── Aprobación del informe POR ESCENARIO (camino de escritura del semáforo) ──
def _escenario_existe(proyecto: Proyecto, modo: str, escenario_id: str) -> bool:
    """¿Existe un escenario (modo+id) en el rincón render del proyecto?

    Lee el aggregate por su clave string (no importa el contexto render; patrón de
    `proyectos/flujo.py`).
    """
    rc = proyecto.datos_por_modulo.get(ModuloPuccetti.RENDER_CALCULOS.value) or {}
    bloque = rc.get(modo) if isinstance(rc, dict) else None
    escenarios = bloque.get("escenarios") if isinstance(bloque, dict) else None
    if not isinstance(escenarios, list):
        return False
    return any(
        isinstance(e, dict) and str(e.get("id") or "") == escenario_id
        for e in escenarios
    )


def aprobar_informe(proyecto: Proyecto, modo: str, escenario_id: str) -> bool:
    """Marca como aprobado el informe de un escenario (→ nodo Informe en verde).

    Escribe `datos_por_modulo["informe"]["escenarios"]["{modo}:{id}"] =
    {"estado": "aprobado"}` preservando el resto del rincón. Devuelve `False` si el
    escenario no existe (no crea aprobaciones fantasma).
    """
    if not modo or not escenario_id or not _escenario_existe(proyecto, modo, escenario_id):
        return False
    inf = dict(proyecto.datos_por_modulo.get(ModuloPuccetti.INFORME.value) or {})
    escenarios = dict(inf.get("escenarios") or {})
    escenarios[f"{modo}:{escenario_id}"] = {"estado": "aprobado"}
    inf["escenarios"] = escenarios
    proyecto.fijar_datos(ModuloPuccetti.INFORME, inf)
    return True
