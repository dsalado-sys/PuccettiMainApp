"""Casos de uso del contexto Usuarios."""
from __future__ import annotations

from dataclasses import dataclass

from app.nucleo.modelo import Rol

from .dominio import ROLES_ASIGNABLES, GestionUsuariosError, Usuario
from .puertos import UsuarioRepositorio
from .seguridad import hashear_contraseña, verificar_contraseña


@dataclass
class AutenticarUsuario:
    repo: UsuarioRepositorio

    def ejecutar(self, usuario: str, contraseña: str) -> Usuario | None:
        """Devuelve el Usuario si las credenciales son válidas, o None."""
        nombre = (usuario or "").strip()
        if not nombre:
            return None
        candidato = self.repo.obtener_por_usuario(nombre)
        if candidato is None or not candidato.activo:
            return None
        if not verificar_contraseña(contraseña or "", candidato.hash_contraseña):
            return None
        return candidato


# ── Administración de usuarios (módulo superadmin) ─────────────────────────
# Reglas transversales aplicadas por estos casos de uso:
#   · El superadmin es INTOCABLE: no se borra, ni se degrada, ni se desactiva.
#   · `SUPERADMIN` no es un rol asignable a cuentas normales.
_MIN_CONTRASENA = 4


def _exigir_rol_asignable(rol: Rol) -> None:
    if rol not in ROLES_ASIGNABLES:
        raise GestionUsuariosError("Rol no asignable.")


def _cargar(repo: UsuarioRepositorio, usuario_id: str) -> Usuario:
    usuario = repo.obtener_por_id(usuario_id)
    if usuario is None:
        raise GestionUsuariosError("El usuario no existe.")
    return usuario


def _proteger_superadmin(usuario: Usuario) -> None:
    if usuario.rol is Rol.SUPERADMIN:
        raise GestionUsuariosError("La cuenta de superadministrador no puede modificarse.")


@dataclass
class ListarUsuarios:
    repo: UsuarioRepositorio

    def ejecutar(self) -> list[Usuario]:
        return sorted(self.repo.listar(), key=lambda u: u.usuario.lower())


@dataclass
class CrearUsuario:
    repo: UsuarioRepositorio

    def ejecutar(self, usuario: str, contraseña: str, rol: Rol) -> Usuario:
        nombre = (usuario or "").strip()
        if not nombre:
            raise GestionUsuariosError("El nombre de usuario es obligatorio.")
        if len((contraseña or "")) < _MIN_CONTRASENA:
            raise GestionUsuariosError(
                f"La contraseña debe tener al menos {_MIN_CONTRASENA} caracteres."
            )
        _exigir_rol_asignable(rol)
        if self.repo.obtener_por_usuario(nombre) is not None:
            raise GestionUsuariosError(f"Ya existe un usuario «{nombre}».")
        return self.repo.guardar(
            Usuario(usuario=nombre, hash_contraseña=hashear_contraseña(contraseña), rol=rol)
        )


@dataclass
class CambiarRol:
    repo: UsuarioRepositorio

    def ejecutar(self, usuario_id: str, rol: Rol) -> Usuario:
        usuario = _cargar(self.repo, usuario_id)
        _proteger_superadmin(usuario)
        _exigir_rol_asignable(rol)
        usuario.rol = rol
        return self.repo.guardar(usuario)


@dataclass
class CambiarActivo:
    repo: UsuarioRepositorio

    def ejecutar(self, usuario_id: str, activo: bool) -> Usuario:
        usuario = _cargar(self.repo, usuario_id)
        _proteger_superadmin(usuario)
        usuario.activo = activo
        return self.repo.guardar(usuario)


@dataclass
class CambiarContraseña:
    repo: UsuarioRepositorio

    def ejecutar(self, usuario_id: str, nueva: str) -> Usuario:
        usuario = _cargar(self.repo, usuario_id)
        _proteger_superadmin(usuario)
        if len((nueva or "")) < _MIN_CONTRASENA:
            raise GestionUsuariosError(
                f"La contraseña debe tener al menos {_MIN_CONTRASENA} caracteres."
            )
        usuario.hash_contraseña = hashear_contraseña(nueva)
        return self.repo.guardar(usuario)


@dataclass
class EliminarUsuario:
    repo: UsuarioRepositorio

    def ejecutar(self, usuario_id: str, *, solicitante_id: str | None = None) -> None:
        usuario = _cargar(self.repo, usuario_id)
        _proteger_superadmin(usuario)
        if solicitante_id is not None and usuario.id == solicitante_id:
            raise GestionUsuariosError("No puedes eliminar tu propia cuenta.")
        self.repo.eliminar(usuario_id)
