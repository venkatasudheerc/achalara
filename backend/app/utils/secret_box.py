"""Secrets kept in the database, encrypted: a Plaid login's access key.

One key, ``PLAID_TOKEN_KEY`` (a Fernet key), encrypts them all. It lives only
in settings. Losing it means the stored logins can no longer be used and must
be linked again; nothing else depends on it. Never log a secret or its
encrypted form.
"""
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class SecretBoxError(RuntimeError):
    """No key is set, or a stored secret does not open with it."""


def _box(key: str = "") -> Fernet:
    key = key or settings.plaid_token_key
    if not key:
        raise SecretBoxError("PLAID_TOKEN_KEY is not set")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise SecretBoxError("PLAID_TOKEN_KEY is not a valid key") from exc


def seal(secret: str, key: str = "") -> str:
    """``secret`` encrypted, as text safe to store."""
    return _box(key).encrypt(secret.encode()).decode()


def open_sealed(sealed: str, key: str = "") -> str:
    """The secret ``seal`` stored."""
    try:
        return _box(key).decrypt(sealed.encode()).decode()
    except InvalidToken as exc:
        raise SecretBoxError("a stored secret does not open with PLAID_TOKEN_KEY") from exc
