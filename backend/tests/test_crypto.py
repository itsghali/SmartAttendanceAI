import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.config.settings import get_settings
from app.core import crypto


@pytest.fixture(autouse=True)
def _clear_caches():
    # get_settings() and crypto._get_cipher() are both @lru_cache — each
    # test that changes FACE_EMBEDDING_ENCRYPTION_KEYS via monkeypatch.setenv
    # needs both cleared, or a prior test's cached cipher leaks in.
    get_settings.cache_clear()
    crypto._get_cipher.cache_clear()
    yield
    get_settings.cache_clear()
    crypto._get_cipher.cache_clear()


def test_encrypt_decrypt_round_trip():
    embedding = [0.1, 0.2, 0.3, -0.4]

    token = crypto.encrypt_embedding(embedding)

    assert isinstance(token, str)
    assert crypto.decrypt_embedding(token) == embedding


def test_ciphertext_does_not_contain_plaintext_values():
    embedding = [0.123456789, 0.987654321]

    token = crypto.encrypt_embedding(embedding)

    assert "0.123456789" not in token
    assert "0.987654321" not in token


def test_key_rotation_new_key_encrypts_old_key_still_decrypts(monkeypatch):
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()

    monkeypatch.setenv("FACE_EMBEDDING_ENCRYPTION_KEYS", f'["{old_key}"]')
    get_settings.cache_clear()
    crypto._get_cipher.cache_clear()
    embedding = [1.0, 2.0, 3.0]
    old_token = crypto.encrypt_embedding(embedding)

    # Rotate: prepend the new key, keep the old one for decrypting existing data.
    monkeypatch.setenv("FACE_EMBEDDING_ENCRYPTION_KEYS", f'["{new_key}", "{old_key}"]')
    get_settings.cache_clear()
    crypto._get_cipher.cache_clear()

    assert crypto.decrypt_embedding(old_token) == embedding
    new_token = crypto.encrypt_embedding(embedding)
    assert new_token != old_token  # new writes use the new (first) key


def test_decrypt_fails_once_key_is_fully_rotated_out(monkeypatch):
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()

    monkeypatch.setenv("FACE_EMBEDDING_ENCRYPTION_KEYS", f'["{old_key}"]')
    get_settings.cache_clear()
    crypto._get_cipher.cache_clear()
    token = crypto.encrypt_embedding([1.0])

    # old_key removed entirely, not just deprioritized — simulates a
    # completed rotation where the old key was retired too early, or
    # corrupted/wrong-key data.
    monkeypatch.setenv("FACE_EMBEDDING_ENCRYPTION_KEYS", f'["{new_key}"]')
    get_settings.cache_clear()
    crypto._get_cipher.cache_clear()

    with pytest.raises(InvalidToken):
        crypto.decrypt_embedding(token)
