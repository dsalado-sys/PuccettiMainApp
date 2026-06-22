"""Wiring de la app web: sesión SQLAlchemy, rol activo, proyecto activo, repositorios.

Cambiar el motor de persistencia se hace SOLO aquí (y en sqlalchemy_base si
hace falta tocar la URL). Casos de uso y rutas no se enteran.
"""
from __future__ import annotations

import os
from collections.abc import Generator
from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.contextos.localizacion.casos_uso import (
    CargarDetalleSubreferencia,
    CargarTodosLosDetalles,
    CorregirLado,
    CorregirOrientacionLado,
    LocalizarPorCoordenada,
    LocalizarPorDireccion,
    LocalizarPorRC,
    SeleccionarInmueble,
    SimplificarContorno,
)
from app.contextos.localizacion.dominio import Parcela as ParcelaLoc
from app.contextos.localizacion.puertos import (
    CallejeroPort,
    CatastroPort,
    ParcelaTemporalRepositorio,
)
from app.plataforma.persistencia.callejero_sqlalchemy import CallejeroSQLAlchemy
from app.contextos.proyectos.casos_uso import (
    CrearProyecto,
    EliminarProyecto,
    ListarProyectos,
    ObtenerProyecto,
)
from app.contextos.proyectos.puertos import ProyectoRepositorio
from app.contextos.usuarios.casos_uso import AutenticarUsuario
from app.contextos.usuarios.dominio import Usuario
from app.contextos.usuarios.puertos import UsuarioRepositorio
from app.nucleo.modelo import Proyecto, Rol
from app.plataforma.cache.parcelas_en_memoria import ParcelasEnMemoria
from app.plataforma.catastro.catastro_meh import CatastroMEH
from app.plataforma.persistencia.proyectos_sqlalchemy import ProyectosSQLAlchemy
from app.plataforma.persistencia.sqlalchemy_base import SessionLocal
from app.plataforma.persistencia.usuarios_sqlalchemy import UsuariosSQLAlchemy

COOKIE_PROYECTO = "puccetti_proyecto"
COOKIE_PARCELA = "puccetti_parcela_temp"
ROL_POR_DEFECTO = Rol.ARQUITECTO

# Clave de firma de la cookie de sesión. Override por entorno en producción,
# mismo criterio que PUCCETTI_DB_URL.
SECRET_KEY = os.environ.get(
    "PUCCETTI_SECRET_KEY",
    "puccetti-dev-secret-cambia-esto-en-produccion",
)


# ── Sesión BBDD ─────────────────────────────────────────────────────────────
def sesion_bbdd() -> Generator[Session, None, None]:
    """Cede una sesión SQLAlchemy por request y la cierra al terminar."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ── Singletons de adapters externos ────────────────────────────────────────
@lru_cache(maxsize=1)
def catastro_adapter() -> CatastroPort:
    return CatastroMEH()


@lru_cache(maxsize=1)
def parcelas_temporales() -> ParcelaTemporalRepositorio:
    return ParcelasEnMemoria(capacidad=200)


# ── Casos de uso de proyectos ──────────────────────────────────────────────
def repositorio_proyectos(
    session: Session = Depends(sesion_bbdd),
) -> ProyectoRepositorio:
    return ProyectosSQLAlchemy(session)


def crear_proyecto_uc(
    repo: ProyectoRepositorio = Depends(repositorio_proyectos),
) -> CrearProyecto:
    return CrearProyecto(repo=repo)


def listar_proyectos_uc(
    repo: ProyectoRepositorio = Depends(repositorio_proyectos),
) -> ListarProyectos:
    return ListarProyectos(repo=repo)


def obtener_proyecto_uc(
    repo: ProyectoRepositorio = Depends(repositorio_proyectos),
) -> ObtenerProyecto:
    return ObtenerProyecto(repo=repo)


def eliminar_proyecto_uc(
    repo: ProyectoRepositorio = Depends(repositorio_proyectos),
) -> EliminarProyecto:
    return EliminarProyecto(repo=repo)


# ── Usuarios / autenticación ───────────────────────────────────────────────
def repositorio_usuarios(
    session: Session = Depends(sesion_bbdd),
) -> UsuarioRepositorio:
    return UsuariosSQLAlchemy(session)


def autenticar_usuario_uc(
    repo: UsuarioRepositorio = Depends(repositorio_usuarios),
) -> AutenticarUsuario:
    return AutenticarUsuario(repo=repo)


def usuario_actual(
    request: Request,
    repo: UsuarioRepositorio = Depends(repositorio_usuarios),
) -> Usuario | None:
    """Carga el usuario conectado a partir de la sesión, o None si no hay."""
    usuario_id = request.session.get("usuario_id")
    if not usuario_id:
        return None
    return repo.obtener_por_id(usuario_id)


# ── Casos de uso de localización ───────────────────────────────────────────
def localizar_por_rc_uc(
    catastro: CatastroPort = Depends(catastro_adapter),
    repo: ParcelaTemporalRepositorio = Depends(parcelas_temporales),
) -> LocalizarPorRC:
    return LocalizarPorRC(catastro=catastro, repo=repo)


def localizar_por_direccion_uc(
    catastro: CatastroPort = Depends(catastro_adapter),
    repo: ParcelaTemporalRepositorio = Depends(parcelas_temporales),
) -> LocalizarPorDireccion:
    return LocalizarPorDireccion(catastro=catastro, repo=repo)


def localizar_por_coordenada_uc(
    catastro: CatastroPort = Depends(catastro_adapter),
    repo: ParcelaTemporalRepositorio = Depends(parcelas_temporales),
) -> LocalizarPorCoordenada:
    return LocalizarPorCoordenada(catastro=catastro, repo=repo)


def simplificar_contorno_uc(
    catastro: CatastroPort = Depends(catastro_adapter),
    repo: ParcelaTemporalRepositorio = Depends(parcelas_temporales),
) -> SimplificarContorno:
    return SimplificarContorno(repo=repo, catastro=catastro)


def corregir_lado_uc(
    repo: ParcelaTemporalRepositorio = Depends(parcelas_temporales),
) -> CorregirLado:
    return CorregirLado(repo=repo)


def corregir_orientacion_uc(
    repo: ParcelaTemporalRepositorio = Depends(parcelas_temporales),
) -> CorregirOrientacionLado:
    return CorregirOrientacionLado(repo=repo)


def seleccionar_inmueble_uc(
    repo: ParcelaTemporalRepositorio = Depends(parcelas_temporales),
) -> SeleccionarInmueble:
    return SeleccionarInmueble(repo=repo)


def cargar_detalle_subref_uc(
    catastro: CatastroPort = Depends(catastro_adapter),
    repo: ParcelaTemporalRepositorio = Depends(parcelas_temporales),
) -> CargarDetalleSubreferencia:
    return CargarDetalleSubreferencia(catastro=catastro, repo=repo)


def cargar_todos_detalles_uc(
    catastro: CatastroPort = Depends(catastro_adapter),
    repo: ParcelaTemporalRepositorio = Depends(parcelas_temporales),
) -> CargarTodosLosDetalles:
    return CargarTodosLosDetalles(catastro=catastro, repo=repo)


def callejero_adapter(
    session: Session = Depends(sesion_bbdd),
) -> CallejeroPort:
    return CallejeroSQLAlchemy(session)


# ── Catálogos Anexo I editables (iter. 3) ──────────────────────────────────
def catalogo_superficies_adapter(session: Session = Depends(sesion_bbdd)):
    """Adapter para Anexo I.5 (vivienda) editable."""
    from app.plataforma.persistencia.catalogo_superficies_sqlalchemy import (
        CatalogoSuperficiesSQLAlchemy,
    )
    return CatalogoSuperficiesSQLAlchemy(session)


def catalogo_apartamentos_adapter(session: Session = Depends(sesion_bbdd)):
    """Adapter para Anexo I.3/I.4 (apartamentos turísticos · Decreto 194/2010) editable."""
    from app.plataforma.persistencia.anexo_i_apartamentos_sqlalchemy import (
        CatalogoApartamentosSQLAlchemy,
    )
    return CatalogoApartamentosSQLAlchemy(session)


def catalogo_hotel_apartamento_adapter(session: Session = Depends(sesion_bbdd)):
    """Adapter para Anexo I.2 (hoteles-apartamento) editable."""
    from app.plataforma.persistencia.anexo_i_hotel_apartamento_sqlalchemy import (
        CatalogoHotelApartamentoSQLAlchemy,
    )
    return CatalogoHotelApartamentoSQLAlchemy(session)


def catalogo_hotelero_adapter(session: Session = Depends(sesion_bbdd)):
    """Adapter para Anexo I.1 (hoteles / hostales / pensiones / albergues) editable."""
    from app.plataforma.persistencia.anexo_i_hotelero_sqlalchemy import (
        CatalogoHoteleroSQLAlchemy,
    )
    return CatalogoHoteleroSQLAlchemy(session)


def obtener_parcela_temporal(
    request: Request,
    repo: ParcelaTemporalRepositorio = Depends(parcelas_temporales),
) -> ParcelaLoc | None:
    pid = request.cookies.get(COOKIE_PARCELA)
    if not pid:
        return None
    return repo.obtener(pid)


# ── Sesión: rol y proyecto activos ─────────────────────────────────────────
def rol_activo(usuario: Usuario | None = Depends(usuario_actual)) -> Rol:
    """Rol del usuario conectado. Por defecto, arquitecto si no hay sesión.

    Con autenticación real (§2.11), el rol lo fija el usuario y no la UI; la
    firma sigue devolviendo `Rol`, así que las rutas que dependen de ella no
    cambian.
    """
    return usuario.rol if usuario else ROL_POR_DEFECTO


def proyecto_activo(
    request: Request,
    uc: ObtenerProyecto = Depends(obtener_proyecto_uc),
) -> Proyecto | None:
    proyecto_id = request.cookies.get(COOKIE_PROYECTO)
    if not proyecto_id:
        return None
    return uc.ejecutar(proyecto_id)


def exige_proyecto(
    proyecto: Proyecto | None = Depends(proyecto_activo),
) -> Proyecto:
    if proyecto is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No hay proyecto activo. Crea uno o ábrelo desde el menú.",
        )
    return proyecto
