"""Read-only n8n credential lookup for the incoming-documents module.

n8n stores its credentials in the `credentials_entity` table of its
postgres database, encrypted with `N8N_ENCRYPTION_KEY` using CryptoJS's
``Salted__`` AES-256-CBC format (key+IV derived via OpenSSL
EVP_BytesToKey with MD5).

This module exposes a small, focused API:

* `decrypt_cryptojs(ciphertext, passphrase)` — pure helper, fully unit
  testable without a database.
* `N8nCredentialStore.get_latest(credential_type, name_contains)` — the
  one lookup the rest of the codebase uses. Returns the most-recently
  updated credential whose `type` matches and whose `name` contains the
  given substring (case-insensitive).
* `from_env()` — builds a store from `N8N_DB_DSN` + `N8N_ENCRYPTION_KEY`,
  or returns ``None`` when either is missing (so the rest of the code
  can degrade gracefully).

Convention used by the deployment: credential names embed the operating
account's email so we can pick the right one in multi-account setups,
e.g. `"Google Sheets person17@example.com"`. The caller passes the
email via env (`GSHEET_CREDS_EMAIL`, `SUPABASE_CREDS_NAME`, etc.).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ---------- Decryption ----------


def _evp_bytes_to_key(
    passphrase: bytes, salt: bytes, key_len: int = 32, iv_len: int = 16
) -> tuple[bytes, bytes]:
    """OpenSSL ``EVP_BytesToKey`` with MD5 — what CryptoJS uses by default."""
    derived = b""
    prev = b""
    while len(derived) < key_len + iv_len:
        prev = hashlib.md5(prev + passphrase + salt).digest()
        derived += prev
    return derived[:key_len], derived[key_len : key_len + iv_len]


def decrypt_cryptojs(ciphertext_b64: str, passphrase: str) -> bytes:
    """Decrypt a CryptoJS ``Salted__`` AES-256-CBC base64 blob."""
    raw = base64.b64decode(ciphertext_b64)
    if len(raw) < 16 or raw[:8] != b"Salted__":
        raise ValueError("Not a CryptoJS Salted__ ciphertext")
    salt = raw[8:16]
    body = raw[16:]
    key, iv = _evp_bytes_to_key(passphrase.encode("utf-8"), salt)

    # Lazy import: only pulled in when an n8n cred is actually decrypted.
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7

    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(body) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


# ---------- Lookup ----------


@dataclass(frozen=True)
class N8nCredential:
    id: str
    name: str
    type: str
    data: dict


class N8nCredentialStore:
    """Read-only credential store backed by an n8n postgres database.

    The store opens a fresh connection per lookup. Credentials are read
    rarely (typically once at backend init), so per-call overhead is
    cheaper than holding a long-lived connection.
    """

    def __init__(self, dsn: str, encryption_key: str):
        if not dsn:
            raise ValueError("dsn is required")
        if not encryption_key:
            raise ValueError("encryption_key is required")
        self._dsn = dsn
        self._key = encryption_key

    # Surface used by the rest of the codebase.
    def get_latest(
        self, credential_type: str, name_contains: Optional[str] = None
    ) -> N8nCredential:
        """Return the most-recently updated matching credential.

        Raises ``LookupError`` when nothing matches.
        """
        rows = self._fetch_rows(credential_type, name_contains, limit=1)
        if not rows:
            raise LookupError(
                "No n8n credential found "
                f"type={credential_type!r} name_contains={name_contains!r}"
            )
        cid, cname, ctype, ciphertext = rows[0]
        plaintext = decrypt_cryptojs(ciphertext, self._key)
        try:
            data = json.loads(plaintext)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Decrypted credential {cid!r} is not JSON: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise ValueError(
                f"Decrypted credential {cid!r} is not a JSON object"
            )
        return N8nCredential(id=cid, name=cname, type=ctype, data=data)

    # Split out so tests can stub the SQL without spinning up postgres.
    def _fetch_rows(
        self,
        credential_type: str,
        name_contains: Optional[str],
        limit: int,
    ) -> list[tuple[str, str, str, str]]:
        sql = (
            'SELECT id, name, type, data FROM credentials_entity '
            'WHERE type = %s'
        )
        params: list = [credential_type]
        if name_contains:
            sql += ' AND name ILIKE %s'
            params.append(f"%{name_contains}%")
        sql += ' ORDER BY "updatedAt" DESC LIMIT %s'
        params.append(limit)

        # Lazy import: psycopg is only loaded when the store is used.
        import psycopg  # type: ignore

        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())


def from_env() -> Optional[N8nCredentialStore]:
    """Build a store from env, or return ``None`` if not configured.

    Recognised env vars:
      * ``N8N_DB_DSN`` — libpq connection string, e.g.
        ``postgresql://user:pass@n8n-postgres:5432/n8n``.
      * ``N8N_ENCRYPTION_KEY`` — hex string from the n8n container env.
    """
    dsn = os.getenv("N8N_DB_DSN", "").strip()
    key = os.getenv("N8N_ENCRYPTION_KEY", "").strip()
    if not dsn or not key:
        return None
    return N8nCredentialStore(dsn=dsn, encryption_key=key)
