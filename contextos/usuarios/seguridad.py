"""Hasheo y verificación de contraseñas con la librería estándar.

PBKDF2-HMAC-SHA256: sin dependencias nativas (robusto en Windows). El hash se
almacena como una sola cadena autodescriptiva: `pbkdf2_sha256$<iter>$<salt>$<hash>`.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

_ALGORITMO = "pbkdf2_sha256"
_ITERACIONES = 240_000
_BYTES_SALT = 16


def hashear_contraseña(plana: str, *, iteraciones: int = _ITERACIONES) -> str:
    """Devuelve el hash almacenable de una contraseña en claro."""
    salt = secrets.token_hex(_BYTES_SALT)
    derivado = hashlib.pbkdf2_hmac(
        "sha256", plana.encode("utf-8"), salt.encode("utf-8"), iteraciones
    ).hex()
    return f"{_ALGORITMO}${iteraciones}${salt}${derivado}"


def verificar_contraseña(plana: str, almacenado: str) -> bool:
    """Comprueba una contraseña en claro contra su hash almacenado.

    Usa comparación en tiempo constante y es tolerante a hashes malformados.
    """
    try:
        algoritmo, iteraciones_txt, salt, esperado = almacenado.split("$")
    except (ValueError, AttributeError):
        return False
    if algoritmo != _ALGORITMO:
        return False
    try:
        iteraciones = int(iteraciones_txt)
    except ValueError:
        return False
    derivado = hashlib.pbkdf2_hmac(
        "sha256", plana.encode("utf-8"), salt.encode("utf-8"), iteraciones
    ).hex()
    return hmac.compare_digest(derivado, esperado)
