"""§2.4–2.7 — Rutas del módulo Render y cálculos.

Endpoints:
- GET  /modulos/render-calculos                   → pantalla del módulo
- POST /modulos/render-calculos/preview           → envolvente rápida (req. 8)
- POST /modulos/render-calculos/calcular          → cálculo completo (req. 8+12)
- POST /modulos/render-calculos/guardar           → persiste params en aggregate
- GET  /modulos/render-calculos/normativa         → lista municipios con PGOU guardado
- GET  /modulos/render-calculos/normativa/{p}/{m} → consulta PGOU de un municipio
- POST /modulos/render-calculos/normativa/{p}/{m} → crea/actualiza PGOU
- GET  /modulos/render-calculos/export.csv        → tabla de superficies (req. 16)
"""
from __future__ import annotations

import csv
import io
import json
from typing import Annotated, Any

# Tope de tamaño del "resumen" persistido en el aggregate: evita que un POST
# guarde un blob arbitrariamente grande en el JSON del proyecto.
_RESUMEN_MAX_BYTES = 100_000

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from app.contextos.proyectos.puertos import ProyectoRepositorio
from app.contextos.render_calculos.casos_uso import (
    CalcularEnvolvente,
    CalcularEstanciasInmueble,
    CalcularLayout,
    CalcularTipologiasDormitorios,
    GuardarRender,
    ValidarCumplimiento,
    adaptar_params_a_edificio_existente,
    aviso_atico_catastral,
    construir_parcela_metrica,
    parametros_desde_proyecto,
)
from app.contextos.render_calculos.dominio import UsoEdificio
from app.contextos.render_calculos.parametros import (
    ParametrosUrbanisticos,
    parametros_a_dict,
    parametros_desde_dict,
)
from app.contextos.render_calculos.puertos import NormativaMunicipalRepositorio
from app.nucleo.modelo import ModuloPuccetti, Proyecto, Rol
from app.nucleo.modelo.rol import PermisoModulo, puede_acceder
from app.plataforma.persistencia.normativa_municipal_sqlalchemy import (
    NormativaMunicipalSQLAlchemy,
)

from ..catalogo_modulos import CATALOGO, TarjetaModulo
from ..render_modos import MODO_POR_DEFECTO, MODOS, modo_o_none
from ..dependencias import (
    catalogo_apartamentos_adapter,
    catalogo_hotel_apartamento_adapter,
    catalogo_hotelero_adapter,
    catalogo_superficies_adapter,
    proyecto_activo,
    repositorio_proyectos,
    rol_activo,
    sesion_bbdd,
)
from ..plantillas import plantillas


router = APIRouter(prefix="/modulos/render-calculos")


# ─── Helpers ────────────────────────────────────────────────────────────────
def _tarjeta() -> TarjetaModulo:
    for t in CATALOGO:
        if t.id == ModuloPuccetti.RENDER_CALCULOS.value:
            return t
    raise HTTPException(status_code=500, detail="Tarjeta render_calculos no encontrada en el catálogo.")


def _exige_permiso(rol: Rol, permiso: PermisoModulo) -> None:
    if not puede_acceder(rol, ModuloPuccetti.RENDER_CALCULOS.value, permiso):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"El rol {rol.value} no puede {permiso.value} en Render y cálculos.",
        )


def _normativa_repo(session: Session = Depends(sesion_bbdd)) -> NormativaMunicipalRepositorio:
    return NormativaMunicipalSQLAlchemy(session)


def _normativa_de_referencia(
    payload: dict[str, Any],
    parcela,
    repo_norm: NormativaMunicipalRepositorio,
):
    """Devuelve la `ParametrosUrbanisticos` contra la que se evaluarán los avisos.

    Prioridad:
      1. `payload["normativa_referencia"]["urbanisticos"]` — la normativa que el
         usuario eligió desde el módulo Normativa municipal y aplicó al proyecto.
      2. Normativa del municipio + provincia de la parcela (si está en BBDD).
      3. None — no se generarán avisos comparados.
    """
    ref = payload.get("normativa_referencia") or {}
    urb = ref.get("urbanisticos") if isinstance(ref, dict) else None
    if urb:
        return parametros_desde_dict({"urbanisticos": urb}).urbanisticos
    if parcela.municipio and parcela.provincia:
        return repo_norm.obtener(parcela.municipio, parcela.provincia)
    return None


# Campos urbanísticos que controla cada sección del panel. Cuando un modo OCULTA una
# sección (`render_modos.secciones_ocultas`), esos campos no se renderizan y por tanto
# no viajan en el payload; `parametros_desde_dict` los dejaría en el default del motor.
# Para esos campos ocultos la fuente de verdad es la NORMATIVA, no el default.
_URB_POR_SECCION: dict[str, tuple[str, ...]] = {
    "edificabilidad": ("usar_coeficiente_edificabilidad", "coeficiente_edificabilidad"),
    "ocupacion": ("ocupacion_maxima_pct",),
    "retranqueos": ("retranqueo_fachada_m", "retranqueo_linderos_m"),
}


def _aplicar_normativa_secciones_ocultas(
    params,
    payload: dict[str, Any],
    normativa,
) -> None:
    """Rellena desde la NORMATIVA los parámetros urbanísticos que el modo oculta.

    Rehabilitación oculta del panel la edificabilidad, la ocupación y los retranqueos
    (`render_modos`: los fija el PGOU y no se editan en este modo). Al no aparecer en el
    panel no llegan en el payload, así que `parametros_desde_dict` caería a los defaults
    del motor (p. ej. coeficiente 2.5), ignorando el planeamiento del municipio. Aquí se
    sustituyen por los de la normativa de referencia (PGOU del municipio o la aplicada al
    proyecto). Los campos VISIBLES en el modo (nº de plantas, ático/sótano, patios) se
    siguen tomando del panel / edificio existente. Sin normativa se respeta lo de partida.
    """
    modo_cfg = modo_o_none(payload.get("modo"))
    if modo_cfg is None or normativa is None:
        return
    for seccion in modo_cfg.secciones_ocultas:
        for attr in _URB_POR_SECCION.get(seccion, ()):
            if hasattr(normativa, attr):
                setattr(params.urbanisticos, attr, getattr(normativa, attr))


def _estado_pantalla(proyecto: Proyecto | None) -> str:
    if proyecto is None:
        return "sin_proyecto"
    datos_loc = proyecto.datos_por_modulo.get(ModuloPuccetti.LOCALIZACION.value)
    if not datos_loc:
        return "sin_parcela"
    return "ok"


def _preview_parcela(proyecto: Proyecto | None) -> dict[str, Any] | None:
    """Resumen de los datos de la parcela del proyecto para la pantalla de
    selección. Devuelve None si el proyecto aún no tiene parcela localizada.

    La superficie es la **catastral real** guardada por §2.1 (`superficie_m2`),
    la misma que alimenta ahora el cálculo de edificabilidad.

    Si en §2.1 se eligió un inmueble concreto de la metaparcela, la construida
    pasa a ser la de ESE inmueble (no la suma de la parcela) y se expone su
    localización (escalera·planta·puerta)."""
    if proyecto is None:
        return None
    loc = proyecto.datos_por_modulo.get(ModuloPuccetti.LOCALIZACION.value) or {}
    if not loc:
        return None

    inm = loc.get("inmueble_seleccionado") or None
    inm = inm if isinstance(inm, dict) else None
    inm_loc = (inm or {}).get("localizacion") or ""
    inm_uso = (inm or {}).get("uso") or ""
    inm_sup = (inm or {}).get("superficie_construida_m2")
    # Construida de referencia: la del inmueble elegido si la hay; si no, la total.
    construida = inm_sup if (inm_sup and inm_sup > 0) else loc.get("superficie_construida_total_m2")

    return {
        "referencia_catastral": loc.get("referencia_catastral"),
        "direccion": loc.get("direccion"),
        "municipio": loc.get("municipio"),
        "provincia": loc.get("provincia"),
        "superficie_m2": loc.get("superficie_m2"),
        "uso_catastral": inm_uso or loc.get("uso_catastral"),
        "anio_construccion": loc.get("anio_construccion"),
        "superficie_construida_total_m2": construida,
        "plantas_sobre_rasante": loc.get("plantas_sobre_rasante"),
        "plantas_bajo_rasante": loc.get("plantas_bajo_rasante"),
        # Patios del edificio existente (recogidos del Catastro en §2.1).
        "n_patios": loc.get("n_patios"),
        "patios_m2": loc.get("patios_m2") or [],
        # Inmueble elegido (escalera·planta·puerta) o "" si no se eligió ninguno.
        "inmueble_localizacion": inm_loc,
        "inmueble_rc": (inm or {}).get("rc") or "",
    }


def _inmueble_seleccionado(proyecto: Proyecto | None) -> bool:
    """¿El proyecto trata sobre un inmueble concreto de la parcela (§2.1)?"""
    if proyecto is None:
        return False
    loc = proyecto.datos_por_modulo.get(ModuloPuccetti.LOCALIZACION.value) or {}
    return bool(loc.get("inmueble_seleccionado"))


def _construida_inmueble_m2(proyecto: Proyecto | None) -> float:
    """Superficie construida del inmueble elegido (m²); la total de la parcela si no hay."""
    if proyecto is None:
        return 0.0
    loc = proyecto.datos_por_modulo.get(ModuloPuccetti.LOCALIZACION.value) or {}
    inm = loc.get("inmueble_seleccionado")
    inm = inm if isinstance(inm, dict) else {}
    try:
        sup = float(inm.get("superficie_construida_m2") or 0.0)
    except (TypeError, ValueError):
        sup = 0.0
    if sup > 0:
        return sup
    try:
        return float(loc.get("superficie_construida_total_m2") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _tiene_params_guardados(proyecto: Proyecto | None, modo: str, *, heredar_legado: bool) -> bool:
    """¿El modo dado ya tiene parámetros propios guardados en el aggregate?

    El formato plano legado solo cuenta para el modo por defecto (`heredar_legado`)."""
    if proyecto is None:
        return False
    datos = proyecto.datos_por_modulo.get(ModuloPuccetti.RENDER_CALCULOS.value) or {}
    blk = datos.get(modo)
    if isinstance(blk, dict) and blk.get("parametros"):
        return True
    return bool(heredar_legado and datos.get("parametros"))


# ─── Pantalla principal ─────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
def pantalla(
    request: Request,
    modo: Annotated[str, Query()] = "",
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    repo_norm: NormativaMunicipalRepositorio = Depends(_normativa_repo),
):
    _exige_permiso(rol, PermisoModulo.VER)
    tarjeta = _tarjeta()
    estado = _estado_pantalla(proyecto)

    # Auto (decisión de negocio): si el proyecto trata sobre un INMUEBLE concreto de
    # la parcela (§2.1 eligió uno), el módulo entra directo en modo «inmueble»
    # (estancias de esa unidad), sin pasar por la landing ni por obra-nueva/rehab.
    if _inmueble_seleccionado(proyecto):
        modo_cfg = MODOS["inmueble"]
    else:
        # Sin modo válido en la URL → pantalla de selección (preview de la parcela +
        # botones Obra nueva / Rehabilitación). El modo elegido reabre esta misma
        # ruta con ?modo=… y entonces se dibuja el módulo.
        modo_cfg = modo_o_none(modo)
        # «inmueble» solo es válido auto-derivado (hay un inmueble elegido en §2.1):
        # si llega por URL sin inmueble, se ignora y se cae a la pantalla de selección.
        if modo_cfg is not None and modo_cfg.es_inmueble:
            modo_cfg = None
    datos_rc_proyecto = (proyecto.datos_por_modulo.get(ModuloPuccetti.RENDER_CALCULOS.value) or {}) if proyecto else {}
    normativa_aplicada = datos_rc_proyecto.get("normativa_aplicada")
    if modo_cfg is None:
        return plantillas.TemplateResponse(
            request,
            "render_calculos_landing.html",
            {
                "tarjeta": tarjeta,
                "rol_activo": rol,
                "proyecto_activo": proyecto,
                "estado": estado,
                # La landing solo ofrece los modos elegibles a mano; «inmueble» es
                # automático (se activa al elegir un inmueble en la localización).
                "modos": [m for m in MODOS.values() if not m.es_inmueble],
                "preview": _preview_parcela(proyecto),
                "puede_editar": puede_acceder(
                    rol, ModuloPuccetti.RENDER_CALCULOS.value, PermisoModulo.EDITAR
                ),
                "normativa_aplicada": normativa_aplicada,
            },
        )

    # Parámetros del MODO activo (cada modo guarda los suyos). El formato plano
    # legado se trata como del modo por defecto. Rehabilitación, sin params
    # propios, arranca adaptado al edificio existente.
    es_modo_defecto = modo_cfg.slug == MODO_POR_DEFECTO
    es_rehabilitacion = modo_cfg.slug == "rehabilitacion"
    tiene_params = _tiene_params_guardados(proyecto, modo_cfg.slug, heredar_legado=es_modo_defecto)
    params = parametros_desde_proyecto(
        proyecto, modo_cfg.slug,
        heredar_legado=es_modo_defecto,
        adaptar_a_existente=es_rehabilitacion,
    )

    municipios = repo_norm.listar()
    # Si la parcela tiene municipio conocido, intentamos cargar su PGOU como
    # base de los parámetros urbanísticos.
    pgou_municipio: dict[str, Any] | None = None
    aviso_atico: dict[str, Any] | None = None
    if proyecto is not None:
        datos_loc = proyecto.datos_por_modulo.get(ModuloPuccetti.LOCALIZACION.value) or {}
        mun, prov = datos_loc.get("municipio"), datos_loc.get("provincia")
        if mun and prov:
            normativa = repo_norm.obtener(mun, prov)
            if normativa is not None:
                pgou_municipio = {"municipio": mun, "provincia": prov}
                # Solo aplicamos como defaults si el MODO aún no tiene params guardados.
                if not tiene_params:
                    params.urbanisticos = normativa
        # En rehabilitación sin params propios, el edificio existente manda sobre el
        # PGOU genérico en nº de plantas / sótano. Se aplica fuera del bloque de
        # normativa para que funcione aunque no haya PGOU del municipio.
        if es_rehabilitacion and not tiene_params:
            adaptar_params_a_edificio_existente(params, proyecto)
            aviso_atico = aviso_atico_catastral(proyecto)

    usos_catalogo = [
        {"value": "vivienda", "label": "Vivienda", "habilitado": True},
        {"value": "apartamentos_turisticos", "label": "Apartamentos turísticos", "habilitado": True},
        {"value": "hotel_apartamento", "label": "Hotel-apartamento", "habilitado": True},
        {"value": "hotelero", "label": "Hotelero", "habilitado": True},
    ]
    # Hook de configuración por modo: si el modo restringe usos, se filtran.
    if modo_cfg.usos_permitidos:
        usos_catalogo = [u for u in usos_catalogo if u["value"] in modo_cfg.usos_permitidos]

    return plantillas.TemplateResponse(
        request,
        "render_calculos.html",
        {
            "tarjeta": tarjeta,
            "modo": modo_cfg,
            "rol_activo": rol,
            "proyecto_activo": proyecto,
            "puede_editar": puede_acceder(
                rol, ModuloPuccetti.RENDER_CALCULOS.value, PermisoModulo.EDITAR
            ),
            "estado": estado,
            "parametros": parametros_a_dict(params),
            "municipios_disponibles": municipios,
            "pgou_municipio_activo": pgou_municipio,
            "usos_edificio": usos_catalogo,
            # Datos catastrales para la barra siempre visible del módulo.
            "catastro": _preview_parcela(proyecto),
            # Aviso sobre la procedencia del ático en rehabilitación (o None).
            "aviso_atico": aviso_atico,
            "normativa_aplicada": normativa_aplicada,
        },
    )


# ─── Preview (envolvente rápida) ────────────────────────────────────────────
@router.post("/preview")
def preview(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    repo_norm: NormativaMunicipalRepositorio = Depends(_normativa_repo),
):
    _exige_permiso(rol, PermisoModulo.VER)
    if proyecto is None:
        raise HTTPException(409, "No hay proyecto activo.")
    parcela = construir_parcela_metrica(proyecto)
    if parcela is None:
        raise HTTPException(409, "El proyecto no tiene parcela asociada. Localízala en «Buscar parcela».")

    params = parametros_desde_dict(payload)
    normativa = _normativa_de_referencia(payload, parcela, repo_norm)
    _aplicar_normativa_secciones_ocultas(params, payload, normativa)
    resultado = CalcularEnvolvente().ejecutar(parcela, params)

    env = resultado.get("envolvente") or {}
    parc = resultado.get("parcela") or {}
    alertas_extra = ValidarCumplimiento().ejecutar(
        parcela, params, normativa,
        edificabilidad_consumida_m2=env.get("edificabilidad_consumida_m2"),
        superficie_referencia_m2=parc.get("area_m2"),
    )
    resultado["alertas"] = list(resultado.get("alertas", [])) + [
        {"nivel": a.nivel, "regla": a.regla, "mensaje": a.mensaje, "elemento": a.elemento}
        for a in alertas_extra
    ]
    return JSONResponse(resultado)


# ─── Cálculo completo (capacidad numérica iter. 3) ──────────────────────────
@router.post("/calcular")
def calcular(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    repo_norm: NormativaMunicipalRepositorio = Depends(_normativa_repo),
    catalogo_viv=Depends(catalogo_superficies_adapter),
    catalogo_apt=Depends(catalogo_apartamentos_adapter),
    catalogo_hap=Depends(catalogo_hotel_apartamento_adapter),
    catalogo_hot=Depends(catalogo_hotelero_adapter),
):
    _exige_permiso(rol, PermisoModulo.VER)
    if proyecto is None:
        raise HTTPException(409, "No hay proyecto activo.")
    parcela = construir_parcela_metrica(proyecto)
    if parcela is None:
        raise HTTPException(409, "El proyecto no tiene parcela asociada. Localízala en «Buscar parcela».")

    params = parametros_desde_dict(payload)
    normativa = _normativa_de_referencia(payload, parcela, repo_norm)
    _aplicar_normativa_secciones_ocultas(params, payload, normativa)
    # §2.5 — selección temporal de combinación de dormitorios (apartamentos). El
    # slug no se persiste: solo recalcula esta respuesta con esa combinación.
    combo_override = payload.get("combo_dormitorios") or None
    if combo_override is not None:
        combo_override = str(combo_override).strip() or None
    caso_uso = CalcularLayout(
        catalogo_vivienda=catalogo_viv,
        catalogo_apartamentos=catalogo_apt,
        catalogo_hotel_apartamento=catalogo_hap,
        catalogo_hotelero=catalogo_hot,
    )
    resultado = caso_uso.ejecutar(parcela, params, combo_override=combo_override)

    env = resultado.get("envolvente") or {}
    parc = resultado.get("parcela") or {}
    alertas_extra = ValidarCumplimiento().ejecutar(
        parcela, params, normativa,
        edificabilidad_consumida_m2=env.get("edificabilidad_consumida_m2"),
        superficie_referencia_m2=parc.get("area_m2"),
    )
    resultado["alertas"] = list(resultado.get("alertas", [])) + [
        {"nivel": a.nivel, "regla": a.regla, "mensaje": a.mensaje, "elemento": a.elemento}
        for a in alertas_extra
    ]
    return JSONResponse(resultado)


# ─── Estancias de un inmueble concreto (modo «inmueble») ────────────────────
@router.post("/estancias")
def estancias_inmueble(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    catalogo_viv=Depends(catalogo_superficies_adapter),
    catalogo_apt=Depends(catalogo_apartamentos_adapter),
    catalogo_hap=Depends(catalogo_hotel_apartamento_adapter),
    catalogo_hot=Depends(catalogo_hotelero_adapter),
):
    """Distribuye las estancias de un inmueble concreto a partir de su construida.

    No usa envolvente: parte de la superficie construida del inmueble elegido en §2.1
    y reparte sus estancias como una sola unidad (modo «inmueble»). El nº de
    dormitorios llega en el payload (`n_dormitorios`); el resto de datos, del panel."""
    _exige_permiso(rol, PermisoModulo.VER)
    if proyecto is None:
        raise HTTPException(409, "No hay proyecto activo.")
    construida = _construida_inmueble_m2(proyecto)
    if construida <= 0:
        raise HTTPException(409, "El inmueble no tiene superficie construida. Elígelo en «Buscar parcela».")

    params = parametros_desde_dict(payload)
    n_dorms_raw = payload.get("n_dormitorios")
    try:
        n_dorms = int(n_dorms_raw) if n_dorms_raw is not None else None
    except (TypeError, ValueError):
        n_dorms = None

    resultado = CalcularEstanciasInmueble(
        catalogo_vivienda=catalogo_viv,
        catalogo_apartamentos=catalogo_apt,
        catalogo_hotel_apartamento=catalogo_hap,
        catalogo_hotelero=catalogo_hot,
    ).ejecutar(params, construida, n_dormitorios=n_dorms)
    return JSONResponse(resultado)


# ─── Combinaciones por nº de dormitorios (§2.5 — apartamentos turísticos) ────
@router.post("/tipologias-dormitorios")
def tipologias_dormitorios(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    catalogo_viv=Depends(catalogo_superficies_adapter),
    catalogo_apt=Depends(catalogo_apartamentos_adapter),
    catalogo_hap=Depends(catalogo_hotel_apartamento_adapter),
    catalogo_hot=Depends(catalogo_hotelero_adapter),
):
    """Para un nº de dormitorios, devuelve las combinaciones viables y cuántas
    unidades cabe de cada una (ordenadas, podadas las no viables). El cliente
    muestra el modal de selección; la elección se reenvía a `/calcular` como
    `combo_dormitorios` (no se persiste hasta `/guardar`)."""
    _exige_permiso(rol, PermisoModulo.VER)
    if proyecto is None:
        raise HTTPException(409, "No hay proyecto activo.")
    parcela = construir_parcela_metrica(proyecto)
    if parcela is None:
        raise HTTPException(409, "El proyecto no tiene parcela asociada. Localízala en «Buscar parcela».")

    params = parametros_desde_dict(payload)
    try:
        n_dorms = int(payload.get("n_dormitorios", 1))
    except (TypeError, ValueError):
        n_dorms = 1

    resultado = CalcularTipologiasDormitorios(
        catalogo_vivienda=catalogo_viv,
        catalogo_apartamentos=catalogo_apt,
        catalogo_hotel_apartamento=catalogo_hap,
        catalogo_hotelero=catalogo_hot,
    ).ejecutar(parcela, params, n_dorms)
    return JSONResponse(resultado)


# ─── Guardar parámetros en el aggregate ─────────────────────────────────────
@router.post("/guardar")
def guardar(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    repo_proy: ProyectoRepositorio = Depends(repositorio_proyectos),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    if proyecto is None:
        raise HTTPException(409, "No hay proyecto activo.")

    params_payload = payload.get("parametros") or payload
    resumen = payload.get("resumen") or {}
    try:
        if len(json.dumps(resumen).encode("utf-8")) > _RESUMEN_MAX_BYTES:
            raise HTTPException(413, "El resumen a guardar es demasiado grande.")
    except (TypeError, ValueError):
        raise HTTPException(422, "El resumen a guardar no es válido.")
    params = parametros_desde_dict(params_payload)

    # Cada modo guarda su propio bloque. Modo inválido → modo por defecto.
    modo_cfg = modo_o_none(payload.get("modo"))
    modo_key = modo_cfg.slug if modo_cfg else MODO_POR_DEFECTO

    actualizado = GuardarRender(repo_proyectos=repo_proy).ejecutar(
        proyecto, params, resumen, modo_key=modo_key
    )
    return JSONResponse({"ok": True, "modo": modo_key, "actualizado_en": actualizado.actualizado_en.isoformat()})


# ─── Persistir normativa elegida en el aggregate ─────────────────────────────
@router.post("/aplicar-normativa")
def aplicar_normativa(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    repo_proy: ProyectoRepositorio = Depends(repositorio_proyectos),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    if proyecto is None:
        raise HTTPException(409, "No hay proyecto activo.")
    datos_rc = dict(proyecto.datos_por_modulo.get(ModuloPuccetti.RENDER_CALCULOS.value) or {})
    datos_rc["normativa_aplicada"] = {
        "id": payload.get("id"),
        "nombre": payload.get("nombre"),
        "urbanisticos": payload.get("urbanisticos") or {},
    }
    proyecto.fijar_datos(ModuloPuccetti.RENDER_CALCULOS, datos_rc)
    repo_proy.guardar(proyecto)
    return JSONResponse({"ok": True})


# ─── Normativa municipal: listado + lectura + escritura ─────────────────────
@router.get("/normativa")
def listar_normativa(
    rol: Rol = Depends(rol_activo),
    repo_norm: NormativaMunicipalRepositorio = Depends(_normativa_repo),
):
    _exige_permiso(rol, PermisoModulo.VER)
    return JSONResponse({"municipios": repo_norm.listar()})


@router.get("/normativa/{provincia}/{municipio}")
def obtener_normativa(
    provincia: str,
    municipio: str,
    rol: Rol = Depends(rol_activo),
    repo_norm: NormativaMunicipalRepositorio = Depends(_normativa_repo),
):
    _exige_permiso(rol, PermisoModulo.VER)
    p = repo_norm.obtener(municipio, provincia)
    if p is None:
        raise HTTPException(404, f"Sin normativa registrada para {municipio} ({provincia}).")
    base = parametros_a_dict(_envolver_params(p))
    return JSONResponse({"municipio": municipio, "provincia": provincia, "urbanisticos": base["urbanisticos"]})


@router.post("/normativa/{provincia}/{municipio}")
def guardar_normativa(
    provincia: str,
    municipio: str,
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    repo_norm: NormativaMunicipalRepositorio = Depends(_normativa_repo),
):
    _exige_permiso(rol, PermisoModulo.EDITAR)
    bloque_urb = payload.get("urbanisticos") or payload
    parsed = parametros_desde_dict({"urbanisticos": bloque_urb})
    fuente = str(payload.get("fuente_pgou", ""))
    repo_norm.guardar(municipio, provincia, parsed.urbanisticos, fuente)
    return JSONResponse({"ok": True})


# Los endpoints de carpetas + normativas archivadas viven ahora en el módulo
# Normativa municipal (/modulos/normativa-municipal/...). Render solo lo consulta
# desde el frontend; aquí no expone esas rutas.


# ─── Superficies mínimas de estancias (vivienda · Normativa) ────────────────
@router.get("/superficies-vivienda")
def listar_superficies_vivienda(
    rol: Rol = Depends(rol_activo),
    catalogo_viv=Depends(catalogo_superficies_adapter),
):
    """Mínimos de superficie por estancia y tipología de vivienda (incl. estudio)."""
    _exige_permiso(rol, PermisoModulo.VER)
    return JSONResponse({
        "filas": catalogo_viv.filas_vivienda(),
        "util_maximo": {str(n): v for n, v in catalogo_viv.util_maximo_por_tipologia().items()},
    })


@router.post("/superficies-vivienda")
def guardar_superficies_vivienda(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    catalogo_viv=Depends(catalogo_superficies_adapter),
):
    """Persiste los mínimos editados. `payload = {"cambios": [{n_dormitorios,
    estancia, valor}, ...]}`. §3.8: ya no hay que recargar constantes del motor;
    cada cálculo lee los mínimos vivos de BBDD vía `_sincronizar_minimos`."""
    _exige_permiso(rol, PermisoModulo.EDITAR)
    cambios = payload.get("cambios") or []
    aplicados = 0
    rechazados: list[str] = []
    for c in cambios:
        if not isinstance(c, dict):
            continue
        estancia = str(c.get("estancia") or "").strip()
        if not estancia:
            continue
        try:
            n_dorms = int(c.get("n_dormitorios"))
            valor = float(c.get("valor"))
        except (TypeError, ValueError):
            continue
        if valor < 0:
            continue
        # El adapter rechaza romper el invariante min ≤ útil máximo: se omite
        # ese cambio (como los negativos) y se informa, sin abortar el lote.
        try:
            catalogo_viv.actualizar("vivienda", str(n_dorms), estancia, valor)
        except ValueError as exc:
            rechazados.append(str(exc))
            continue
        aplicados += 1
    return JSONResponse({"ok": True, "aplicados": aplicados, "rechazados": rechazados})


@router.post("/superficies-vivienda/reset")
def reset_superficies_vivienda(
    rol: Rol = Depends(rol_activo),
    catalogo_viv=Depends(catalogo_superficies_adapter),
):
    """Restablece los mínimos a los valores sembrados (defaults del motor)."""
    _exige_permiso(rol, PermisoModulo.EDITAR)
    catalogo_viv.reset()
    return JSONResponse({"ok": True})


# ─── Superficies mínimas de los usos turístico/hoteleros (Anexo I.1–I.4) ─────
# Análogo a vivienda, pero acotado a la categoría seleccionada en el panel
# (las tablas tienen una entrada por categoría × tipología × estancia). Los
# adapters de apartamentos/hotel-apt/hotelero se consultan en vivo en cada
# cálculo, así que no hay constantes que recargar tras editar (a diferencia de
# vivienda, cuyo motor cachea los mínimos).
_USOS_MINIMOS = {"apartamentos_turisticos", "hotel_apartamento", "hotelero"}


def _adapter_minimos(uso: str, apt, hap, hot):
    if uso == "apartamentos_turisticos":
        return apt
    if uso == "hotel_apartamento":
        return hap
    if uso == "hotelero":
        return hot
    raise HTTPException(404, f"Uso desconocido para el editor de mínimos: {uso!r}.")


@router.get("/minimos/{uso}")
def listar_minimos(
    uso: str,
    categoria: Annotated[str, Query(...)],
    grupo: Annotated[str, Query()] = "edificios",
    rol: Rol = Depends(rol_activo),
    catalogo_apt=Depends(catalogo_apartamentos_adapter),
    catalogo_hap=Depends(catalogo_hotel_apartamento_adapter),
    catalogo_hot=Depends(catalogo_hotelero_adapter),
):
    """Mínimos por estancia y tipología de la categoría seleccionada del uso dado."""
    _exige_permiso(rol, PermisoModulo.VER)
    adapter = _adapter_minimos(uso, catalogo_apt, catalogo_hap, catalogo_hot)
    if uso == "apartamentos_turisticos":
        filas = adapter.filas_min(categoria, grupo)
    else:
        filas = adapter.filas_min(categoria)
    return JSONResponse({"filas": filas})


@router.post("/minimos/{uso}")
def guardar_minimos(
    uso: str,
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    catalogo_apt=Depends(catalogo_apartamentos_adapter),
    catalogo_hap=Depends(catalogo_hotel_apartamento_adapter),
    catalogo_hot=Depends(catalogo_hotelero_adapter),
):
    """Persiste los mínimos editados de la categoría. `payload = {categoria,
    grupo, cambios: [{tipologia, estancia, valor}, ...]}`."""
    _exige_permiso(rol, PermisoModulo.EDITAR)
    adapter = _adapter_minimos(uso, catalogo_apt, catalogo_hap, catalogo_hot)
    categoria = str(payload.get("categoria") or "").strip()
    grupo = str(payload.get("grupo") or "edificios").strip() or "edificios"
    if not categoria:
        raise HTTPException(422, "Falta la categoría.")
    cambios = payload.get("cambios") or []
    aplicados = 0
    rechazados: list[str] = []
    for c in cambios:
        if not isinstance(c, dict):
            continue
        tipologia = str(c.get("tipologia") or "").strip()
        estancia = str(c.get("estancia") or "").strip()
        if not tipologia or not estancia:
            continue
        try:
            valor = float(c.get("valor"))
        except (TypeError, ValueError):
            continue
        if valor < 0:
            continue
        # El adapter rechaza romper el invariante min ≤ útil máximo: se omite ese
        # cambio y se informa, sin abortar el lote.
        try:
            if uso == "apartamentos_turisticos":
                adapter.actualizar(categoria, tipologia, estancia, valor, grupo=grupo)
            else:
                adapter.actualizar(categoria, tipologia, estancia, valor)
        except ValueError as exc:
            rechazados.append(str(exc))
            continue
        aplicados += 1
    return JSONResponse({"ok": True, "aplicados": aplicados, "rechazados": rechazados})


@router.post("/minimos/{uso}/reset")
def reset_minimos(
    uso: str,
    rol: Rol = Depends(rol_activo),
    catalogo_apt=Depends(catalogo_apartamentos_adapter),
    catalogo_hap=Depends(catalogo_hotel_apartamento_adapter),
    catalogo_hot=Depends(catalogo_hotelero_adapter),
):
    """Restablece los mínimos del uso a los valores sembrados (Anexo I)."""
    _exige_permiso(rol, PermisoModulo.EDITAR)
    adapter = _adapter_minimos(uso, catalogo_apt, catalogo_hap, catalogo_hot)
    adapter.reset()
    return JSONResponse({"ok": True})


# ─── Export CSV ─────────────────────────────────────────────────────────────
@router.post("/export.csv")
def export_csv(
    payload: Annotated[dict[str, Any], Body(...)],
    rol: Rol = Depends(rol_activo),
    proyecto: Proyecto | None = Depends(proyecto_activo),
    catalogo_viv=Depends(catalogo_superficies_adapter),
    catalogo_apt=Depends(catalogo_apartamentos_adapter),
    catalogo_hap=Depends(catalogo_hotel_apartamento_adapter),
    catalogo_hot=Depends(catalogo_hotelero_adapter),
):
    _exige_permiso(rol, PermisoModulo.VER)
    if proyecto is None:
        raise HTTPException(409, "No hay proyecto activo.")
    parcela = construir_parcela_metrica(proyecto)
    if parcela is None:
        raise HTTPException(409, "El proyecto no tiene parcela asociada.")
    params = parametros_desde_dict(payload.get("parametros") or payload)
    caso_uso = CalcularLayout(
        catalogo_vivienda=catalogo_viv,
        catalogo_apartamentos=catalogo_apt,
        catalogo_hotel_apartamento=catalogo_hap,
        catalogo_hotelero=catalogo_hot,
    )
    resultado = caso_uso.ejecutar(parcela, params)

    def _es(v):
        # Formato es-ES para el CSV (delimitador ';'): coma decimal en los
        # valores con decimales. Enteros, cadenas y booleanos pasan tal cual.
        return f"{v:.2f}".replace(".", ",") if isinstance(v, float) else v

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["# Tabla de superficies por planta — Render y cálculos"])
    writer.writerow(["planta", "tipo", "viviendas", "construida_m2", "util_viviendas_m2",
                     "muros_m2", "muros_interior_m2", "circulacion_m2", "nucleo_m2",
                     "local_m2", "otros_m2", "usos_comunes_m2"])
    for r in resultado.get("tabla_planta", []):
        writer.writerow([_es(v) for v in [r["planta"], r.get("tipo", "regular"), r["viviendas"], r["construida_m2"],
                         r["util_viviendas_m2"], r.get("muros_m2", 0.0), r.get("muros_interior_m2", 0.0),
                         r["circulacion_m2"], r.get("nucleo_m2", 0.0),
                         r.get("local_m2", 0.0), r.get("otros_m2", 0.0), r.get("usos_comunes_m2", 0.0)]])
    writer.writerow([])
    writer.writerow(["# Tabla por unidad (iter. 3 — sintética desde cálculo)"])
    writer.writerow(["planta", "vivienda", "dorms", "tipo", "util_m2_objetivo",
                     "util_total_m2", "computable_turismo_m2", "circulacion_acceso_m2", "adaptada"])
    for r in resultado.get("tabla_unidad", []):
        writer.writerow([_es(v) for v in [r["planta"], r["vivienda"], r["dorms"], r.get("tipo", "vivienda"),
                         r["util_m2_objetivo"], r.get("util_por_unidad_m2", 0.0),
                         r.get("computable_turismo_por_unidad_m2", 0.0),
                         r.get("circulacion_interior_por_unidad_m2", 0.0), r["adaptada"]]])
    return Response(
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=puccetti_superficies.csv"},
    )


# ─── Helper privado ─────────────────────────────────────────────────────────
def _envolver_params(urb: ParametrosUrbanisticos):
    """Envuelve un ParametrosUrbanisticos en un ParametrosRender vacío para reutilizar `parametros_a_dict`."""
    from app.contextos.render_calculos.parametros import ParametrosRender
    bundle = ParametrosRender()
    bundle.urbanisticos = urb
    return bundle
