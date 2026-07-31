"""Encrypt / decrypt AI provider API keys at rest.

Master key comes from ``AI_SECRETS_MASTER_KEY`` (url-safe base64 Fernet key).
In DEBUG / test only, a deterministic key is derived from ``SECRET_KEY`` when
the env var is unset so local and CI can run without extra config.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


def _is_relaxed_secrets_env() -> bool:
    if settings.DEBUG:
        return True
    # Django test runner / manage.py test
    import sys

    return any(arg == "test" or arg.endswith("pytest") for arg in sys.argv)


def _fernet_key_bytes() -> bytes:
    configured = (getattr(settings, "AI_SECRETS_MASTER_KEY", None) or "").strip()
    if configured:
        return configured.encode("utf-8")

    if _is_relaxed_secrets_env():
        digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)

    raise ImproperlyConfigured(
        "AI_SECRETS_MASTER_KEY must be set to encrypt/decrypt AI provider keys. "
        "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )


def get_fernet() -> Fernet:
    return Fernet(_fernet_key_bytes())


def encrypt_api_key(plaintext: str) -> str:
    if plaintext is None or plaintext == "":
        raise ValueError("api_key must not be empty")
    return get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_api_key(ciphertext: str) -> str:
    if not ciphertext:
        raise ValueError("encrypted api_key is empty")
    try:
        return get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        logger.error("Failed to decrypt AI provider API key (wrong AI_SECRETS_MASTER_KEY?)")
        raise ValueError("Unable to decrypt AI provider API key") from exc


def mask_api_key(plaintext: str | None) -> str | None:
    if not plaintext:
        return None
    if len(plaintext) <= 4:
        return "****"
    return f"…{plaintext[-4:]}"
