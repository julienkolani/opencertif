"""Chiffrement symétrique pour les secrets stockés en base (mot de passe SMTP…).

Utilise Fernet (AES-128-CBC + HMAC) de la bibliothèque `cryptography`.
Si SECRET_KEY n'est pas défini dans l'env, les valeurs sont stockées en clair
avec un avertissement de sécurité.
"""
import base64
import hashlib
import logging
import os

logger = logging.getLogger(__name__)

_fernet = None  # initialisé paresseusement


def _get_fernet():
    """Retourne l'instance Fernet ou None si SECRET_KEY absent."""
    global _fernet
    if _fernet is not None:
        return _fernet
    secret = os.getenv("SECRET_KEY", "").strip()
    if not secret:
        logger.warning(
            "SECRET_KEY non défini : les secrets sont stockés en clair. "
            "Définissez SECRET_KEY dans .env pour activer le chiffrement."
        )
        return None
    from cryptography.fernet import Fernet
    key_bytes = hashlib.sha256(secret.encode("utf-8")).digest()
    _fernet = Fernet(base64.urlsafe_b64encode(key_bytes))
    return _fernet


def encrypt_secret(value: str) -> str:
    """Chiffre `value`. Retourne la valeur en clair si SECRET_KEY absent."""
    f = _get_fernet()
    if f is None or not value:
        return value
    return f.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    """Déchiffre `value`. Retourne la valeur telle quelle si clé absente ou erreur."""
    f = _get_fernet()
    if f is None or not value:
        return value
    try:
        return f.decrypt(value.encode("utf-8")).decode("utf-8")
    except Exception:
        logger.debug("Déchiffrement impossible, valeur retournée telle quelle (migration possible).")
        return value
