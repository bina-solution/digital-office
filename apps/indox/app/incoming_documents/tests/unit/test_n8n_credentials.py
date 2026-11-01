"""Unit tests for the n8n credential lookup layer.

The decryption helper is exercised against fixed CryptoJS-encoded
ciphertext so we don't need a live n8n postgres in CI. The lookup is
exercised against a stubbed `_fetch_rows` so we don't open a real
connection either.
"""
from __future__ import annotations

import base64
import hashlib
import json

import pytest

from incoming_documents.n8n_credentials import (
    N8nCredential,
    N8nCredentialStore,
    decrypt_cryptojs,
    from_env,
)


# ---------- Helpers ----------


def _encrypt_cryptojs(plaintext: bytes, passphrase: str) -> str:
    """Build a CryptoJS-format AES-256-CBC ``Salted__`` ciphertext.

    Mirrors ``decrypt_cryptojs`` so tests stay self-contained.
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7

    salt = b"\x01\x02\x03\x04\x05\x06\x07\x08"
    derived = b""
    prev = b""
    while len(derived) < 48:
        prev = hashlib.md5(prev + passphrase.encode("utf-8") + salt).digest()
        derived += prev
    key, iv = derived[:32], derived[32:48]
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    body = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(b"Salted__" + salt + body).decode("ascii")


# ---------- decrypt_cryptojs ----------


def test_decrypt_cryptojs_roundtrip():
    blob = _encrypt_cryptojs(b'{"hello":"world"}', "passphrase-1")
    assert decrypt_cryptojs(blob, "passphrase-1") == b'{"hello":"world"}'


def test_decrypt_cryptojs_wrong_key_raises():
    blob = _encrypt_cryptojs(b'{"hello":"world"}', "right-key")
    with pytest.raises(Exception):
        # Wrong key produces either invalid padding or junk bytes.
        decrypt_cryptojs(blob, "wrong-key")


def test_decrypt_cryptojs_rejects_non_salted_blob():
    not_salted = base64.b64encode(b"NotSaltd" + b"\x00" * 16).decode()
    with pytest.raises(ValueError, match="Salted__"):
        decrypt_cryptojs(not_salted, "any")


# ---------- N8nCredentialStore ----------


class _StubStore(N8nCredentialStore):
    """Subclass that bypasses postgres and returns canned rows."""

    def __init__(self, rows, **kwargs):
        super().__init__(dsn="dsn", encryption_key=kwargs["encryption_key"])
        self._rows = rows
        self.queries = []

    def _fetch_rows(self, credential_type, name_contains, limit):
        self.queries.append((credential_type, name_contains, limit))
        return self._rows


def test_get_latest_decrypts_and_parses():
    passphrase = "n8n-key"
    payload = {"host": "https://x.supabase.co", "serviceRole": "k"}
    ciphertext = _encrypt_cryptojs(json.dumps(payload).encode(), passphrase)
    store = _StubStore(
        rows=[("id-1", "Supabase account", "supabaseApi", ciphertext)],
        encryption_key=passphrase,
    )

    cred = store.get_latest("supabaseApi", name_contains="Supabase")

    assert isinstance(cred, N8nCredential)
    assert cred.id == "id-1"
    assert cred.data == payload
    # SQL builder was called with the right arguments.
    assert store.queries == [("supabaseApi", "Supabase", 1)]


def test_get_latest_raises_lookup_error_when_empty():
    store = _StubStore(rows=[], encryption_key="key")
    with pytest.raises(LookupError):
        store.get_latest("nope")


def test_get_latest_rejects_non_object_payload():
    blob = _encrypt_cryptojs(b"[1,2,3]", "k")
    store = _StubStore(
        rows=[("id-2", "weird", "x", blob)], encryption_key="k"
    )
    with pytest.raises(ValueError, match="JSON object"):
        store.get_latest("x")


def test_constructor_validates_args():
    with pytest.raises(ValueError, match="dsn"):
        N8nCredentialStore(dsn="", encryption_key="k")
    with pytest.raises(ValueError, match="encryption_key"):
        N8nCredentialStore(dsn="dsn", encryption_key="")


# ---------- from_env ----------


def test_from_env_returns_none_when_unconfigured(monkeypatch):
    monkeypatch.delenv("N8N_DB_DSN", raising=False)
    monkeypatch.delenv("N8N_ENCRYPTION_KEY", raising=False)
    assert from_env() is None


def test_from_env_returns_store_when_configured(monkeypatch):
    monkeypatch.setenv("N8N_DB_DSN", "postgresql://x/y")
    monkeypatch.setenv("N8N_ENCRYPTION_KEY", "key")
    store = from_env()
    assert isinstance(store, N8nCredentialStore)
