"""
core/crypto.py
Cifrado/descifrado de tokens de API usando Fernet (AES-128-CBC).
La clave Fernet se deriva del JWT_SECRET de la config.
"""
import base64
import hashlib
from cryptography.fernet import Fernet


def _derive_key(secret: str) -> bytes:
    """Deriva una clave Fernet de 32 bytes a partir del JWT_SECRET."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def get_fernet(secret: str) -> Fernet:
    return Fernet(_derive_key(secret))


def encrypt_token(value: str, secret: str) -> str:
    """Cifra un valor de token. Devuelve string base64."""
    f = get_fernet(secret)
    return f.encrypt(value.encode()).decode()


def decrypt_token(encrypted: str, secret: str) -> str:
    """Descifra un token cifrado."""
    f = get_fernet(secret)
    return f.decrypt(encrypted.encode()).decode()
