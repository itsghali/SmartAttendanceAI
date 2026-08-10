"""Application-layer encryption for biometric data at rest (see PLAN.md item 5).

MultiFernet gives key rotation "for free": encryption always uses the first
key in the list; decryption tries each key in order until one succeeds. To
rotate, prepend a new key and keep the old one around for as long as any
still-encrypted-under-it data exists — no forced re-encryption migration.
"""
import json
from functools import lru_cache

from cryptography.fernet import Fernet, MultiFernet

from app.config.settings import get_settings


@lru_cache
def _get_cipher() -> MultiFernet:
    keys = get_settings().face_embedding_encryption_keys
    return MultiFernet([Fernet(key.encode()) for key in keys])


def encrypt_embedding(embedding: list[float]) -> str:
    payload = json.dumps(embedding).encode()
    return _get_cipher().encrypt(payload).decode()


def decrypt_embedding(token: str) -> list[float]:
    """Raises cryptography.fernet.InvalidToken if no configured key can
    decrypt it (key rotated out, or corrupted data) — callers must catch
    this and surface a domain-specific error, not let it 500 (see
    FaceProfileCorruptedError)."""
    payload = _get_cipher().decrypt(token.encode())
    return json.loads(payload.decode())
