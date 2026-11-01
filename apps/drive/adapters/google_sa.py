"""adapters.google_sa — Google Drive via Service Account (protocol `drive_google_service_account`).

The credential stored in secret-base is the parsed service account JSON key
({type, project_id, private_key_id, private_key, client_email, ...}).

Authentication: we build a signed JWT assertion and exchange it for a short-lived
access token — no OAuth consent window, no refresh token, no user interaction.
The service account must have been granted access to the target folders/shared drives.
"""
import base64
import json
import time

import requests

import connections_client as cx
from .google import TOKEN_URL, GoogleAuthError, GoogleDriveAdapter, _TIMEOUT

_SA_CACHE = {}   # cid -> token_dict with expires_at


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _make_jwt(client_email: str, private_key_pem: str) -> str:
    """Build and RS256-sign a JWT assertion for a service account token exchange."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding as _padding
    except ImportError as exc:
        raise GoogleAuthError(f"חבילת cryptography אינה מותקנת — {exc}")

    now = int(time.time())
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({
        "iss": client_email,
        "scope": "https://www.googleapis.com/auth/drive",
        "aud": TOKEN_URL,
        "exp": now + 3600,
        "iat": now,
    }).encode())

    try:
        key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    except Exception as exc:
        raise GoogleAuthError(f"המפתח הפרטי של חשבון השירות אינו תקין: {exc}")

    sig = key.sign(f"{header}.{payload}".encode(), _padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{_b64url(sig)}"


class GoogleServiceAccountAdapter(GoogleDriveAdapter):
    """Google Drive adapter authenticated via a service account JSON key.

    Inherits all API methods from GoogleDriveAdapter; overrides the token
    lifecycle (_token, _refresh) and the file-CREATION ops, which a service
    account cannot perform (see _SA_NO_CREATE below). Reads and metadata ops
    on already-granted items are identical to the base adapter.
    """
    protocol = "drive_google_service_account"

    def _mint_token(self) -> dict:
        got = cx.get_secret(self.cid)
        if not got:
            raise GoogleAuthError("שירות החשבונות אינו זמין — לא ניתן לקרוא את מפתח חשבון השירות")
        sa = got.get("secret") or {}
        email = sa.get("client_email")
        key_pem = sa.get("private_key")
        if not email or not key_pem:
            raise GoogleAuthError("חשבון השירות חסר client_email או private_key — חבר מחדש")
        assertion = _make_jwt(email, key_pem)
        try:
            r = requests.post(TOKEN_URL, data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            }, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            raise GoogleAuthError(f"בקשת האסימון של חשבון השירות נכשלה: {exc}")
        if r.status_code >= 400:
            try:
                msg = (r.json() or {}).get("error_description") or r.text[:160]
            except ValueError:
                msg = r.text[:160]
            raise GoogleAuthError(f"Google דחה את JWT של חשבון השירות ({r.status_code}): {msg}")
        tok = r.json()
        tok["expires_at"] = int(time.time()) + int(tok.get("expires_in", 3600)) - 30
        _SA_CACHE[self.cid] = tok
        return tok

    def _token(self) -> dict:
        tok = _SA_CACHE.get(self.cid)
        if not tok or time.time() > float(tok.get("expires_at", 0)) - 60:
            return self._mint_token()
        return tok

    def _refresh(self, _tok: dict) -> dict:
        # Service accounts have no refresh token — re-mint from the key
        return self._mint_token()

    # ── Service accounts cannot CREATE files ─────────────────────────────────────
    # A service account has no personal Drive storage and this deployment does not
    # grant it a Shared Drive, so upload / create-from-text / create-folder are NOT
    # supported. Reads (list, download) and metadata ops on already-granted items
    # (move, rename, delete) work fine. Raise an explicit, actionable error instead
    # of letting Google answer with an opaque 403 that surfaces upstream as a bare
    # 503 — the limitation is a property of the connection, not a transient fault.
    _SA_NO_CREATE = (
        "חשבון שירות אינו תומך בהעלאת/יצירת קבצים ב־Google Drive (אין לו אחסון אישי "
        "ולא הוקצה לו Shared Drive). פעולות נתמכות: רשימה, הורדה, העברה, שינוי שם "
        "ומחיקה של פריטים קיימים. להעלאת מסמכים יש להשתמש במנוע ה־Drive המקומי "
        "(פרופיל admin) או בחיבור OAuth של משתמש."
    )

    def create_folder(self, name, parent=""):
        raise GoogleAuthError(self._SA_NO_CREATE)

    def upload(self, folder, filename, mime, data):
        raise GoogleAuthError(self._SA_NO_CREATE)

    def op_upload(self, folder_id, name, mime, data):
        raise GoogleAuthError(self._SA_NO_CREATE)

    def op_create_from_text(self, name, content, folder_id):
        raise GoogleAuthError(self._SA_NO_CREATE)
