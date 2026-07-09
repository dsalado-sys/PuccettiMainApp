"""Casos de uso de administración de usuarios: guardas de dominio."""
from __future__ import annotations

import pytest

from app.contextos.usuarios.casos_uso import (
    CambiarActivo,
    CambiarRol,
    CrearUsuario,
    EliminarUsuario,
    ListarUsuarios,
)
from app.contextos.usuarios.dominio import GestionUsuariosError, Usuario
from app.contextos.usuarios.seguridad import hashear_contraseña
from app.nucleo.modelo import Rol


class RepoMemoria:
    """Implementación mínima del puerto UsuarioRepositorio para tests unitarios."""

    def __init__(self, usuarios: list[Usuario] | None = None) -> None:
        self._por_id: dict[str, Usuario] = {u.id: u for u in (usuarios or [])}

    def obtener_por_usuario(self, usuario: str) -> Usuario | None:
        return next((u for u in self._por_id.values() if u.usuario == usuario), None)

    def obtener_por_id(self, usuario_id: str) -> Usuario | None:
        return self._por_id.get(usuario_id)

    def guardar(self, usuario: Usuario) -> Usuario:
        self._por_id[usuario.id] = usuario
        return usuario

    def listar(self) -> list[Usuario]:
        return list(self._por_id.values())

    def eliminar(self, usuario_id: str) -> None:
        self._por_id.pop(usuario_id, None)


def _usuario(nombre: str, rol: Rol) -> Usuario:
    return Usuario(usuario=nombre, hash_contraseña=hashear_contraseña("x-secreta"), rol=rol)


def test_crear_usuario_ok():
    repo = RepoMemoria()
    creado = CrearUsuario(repo).ejecutar("nuevo", "clave-larga", Rol.FINANCIERO)
    assert creado.usuario == "nuevo"
    assert creado.rol is Rol.FINANCIERO
    assert repo.obtener_por_usuario("nuevo") is not None


def test_crear_usuario_duplicado_falla():
    repo = RepoMemoria([_usuario("dup", Rol.CLIENTE)])
    with pytest.raises(GestionUsuariosError):
        CrearUsuario(repo).ejecutar("dup", "clave-larga", Rol.CLIENTE)


def test_crear_usuario_rol_superadmin_no_asignable():
    repo = RepoMemoria()
    with pytest.raises(GestionUsuariosError):
        CrearUsuario(repo).ejecutar("hacker", "clave-larga", Rol.SUPERADMIN)


def test_crear_usuario_contrasena_corta_falla():
    repo = RepoMemoria()
    with pytest.raises(GestionUsuariosError):
        CrearUsuario(repo).ejecutar("nuevo", "ab", Rol.CLIENTE)


def test_superadmin_intocable_cambiar_rol():
    sup = _usuario("superadmin", Rol.SUPERADMIN)
    repo = RepoMemoria([sup])
    with pytest.raises(GestionUsuariosError):
        CambiarRol(repo).ejecutar(sup.id, Rol.ARQUITECTO)


def test_superadmin_intocable_desactivar():
    sup = _usuario("superadmin", Rol.SUPERADMIN)
    repo = RepoMemoria([sup])
    with pytest.raises(GestionUsuariosError):
        CambiarActivo(repo).ejecutar(sup.id, False)


def test_superadmin_intocable_eliminar():
    sup = _usuario("superadmin", Rol.SUPERADMIN)
    repo = RepoMemoria([sup])
    with pytest.raises(GestionUsuariosError):
        EliminarUsuario(repo).ejecutar(sup.id)


def test_no_autoborrado():
    yo = _usuario("arq", Rol.ARQUITECTO)
    repo = RepoMemoria([yo])
    with pytest.raises(GestionUsuariosError):
        EliminarUsuario(repo).ejecutar(yo.id, solicitante_id=yo.id)


def test_eliminar_usuario_normal_ok():
    victima = _usuario("temp", Rol.CLIENTE)
    repo = RepoMemoria([victima])
    EliminarUsuario(repo).ejecutar(victima.id, solicitante_id="otro-id")
    assert repo.obtener_por_id(victima.id) is None


def test_listar_ordenado():
    repo = RepoMemoria([_usuario("Zeta", Rol.CLIENTE), _usuario("alfa", Rol.CLIENTE)])
    nombres = [u.usuario for u in ListarUsuarios(repo).ejecutar()]
    assert nombres == ["alfa", "Zeta"]
