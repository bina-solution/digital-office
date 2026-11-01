"""git.credentials — one secret in the vault, every way a forge can authenticate.

A git host does not have one kind of credential, it has five, and they differ in ways that reach all
the way up: a classic PAT can create a repository, a fine-grained PAT needs "Administration: write"
for the same thing, a GitHub App installation token can do it with a one-hour life and no user at
all, an OAuth token expires and must be refreshed, and a GitLab deploy token can clone but cannot
touch the API. This module is where that difference LIVES, so the adapters and the proxy can be
written once against a single object:

    cred = credential_for(provider, secret, cid)
    cred.api_headers          # what to send to the REST API
    cred.git_user, cred.git_password   # what to send as BASIC auth to git-over-HTTPS
    cred.expires_at           # epoch seconds, or None

Three rules this module keeps, all of them learned from how these credentials actually behave:

  * a token that expires is MINTED, not stored: a GitHub App's installation token and a refreshed
    OAuth access token live in this process's cache with their expiry. The vault keeps the thing that
    does not expire (the App's private key, the OAuth refresh token), which is also the thing a
    restart can still use;
  * when a refresh produces a NEW long-lived secret (a rotated OAuth refresh token), it is written
    BACK to the vault, merged — never held only in memory, because a refresh token that lives in one
    container's RAM is lost on the next deploy and the account is stranded;
  * a credential that cannot do something says so here (`cred.api_usable`), so an op can refuse with
    a sentence instead of failing as a 403 three layers down.
"""
from __future__ import annotations

import logging
import os
import threading
import time

import httpx

log = logging.getLogger("git.credentials")

UA = "bina-office-git/0.1 (+digital-office)"
_APP_TOKEN_SKEW = 300          # treat an installation token as expired 5 minutes early
_CACHE: dict[str, tuple[float, str, int | None]] = {}
_CACHE_LOCK = threading.Lock()


class CredentialError(Exception):
    """A secret that cannot be turned into a usable credential, explained in Hebrew."""

    def __init__(self, he_message: str, status: int = 401, detail: str | None = None):
        super().__init__(he_message)
        self.he_message = he_message
        self.status = status
        self.detail = detail


# The auth kinds the catalogue offers. `api` says whether the kind can call the provider's REST API
# at all; a git-only credential (a GitLab deploy token) is a first-class choice, not a broken one —
# it is simply honest about being a clone/push credential.
KINDS = {
    "pat":            {"api": True,  "git": True,  "label": "טוקן אישי"},
    "fine_grained":   {"api": True,  "git": True,  "label": "טוקן fine-grained"},
    "app":            {"api": True,  "git": True,  "label": "GitHub App (installation)"},
    "oauth":          {"api": True,  "git": True,  "label": "OAuth"},
    "group_token":    {"api": True,  "git": True,  "label": "טוקן קבוצה"},
    "project_token":  {"api": True,  "git": True,  "label": "טוקן פרויקט"},
    "deploy_token":   {"api": False, "git": True,  "label": "Deploy token (קוד בלבד)"},
    "generic_token":  {"api": False, "git": True,  "label": "טוקן לכל מארח Git (קוד בלבד)"},
}


# The kinds that can call a REST API at all. Everything else is a git-only credential: legitimate,
# and honest about it — the wizard reports "no API to verify against" instead of a green chip.
API_KINDS = {k for k, v in KINDS.items() if v["api"]}


class Credential:
    def __init__(self, provider: str, kind: str, api_headers: dict, git_user: str,
                 git_password: str, *, expires_at: int | None = None, note: str | None = None,
                 login_hint: str | None = None):
        self.provider = provider
        self.kind = kind
        self.api_headers = api_headers
        self.git_user = git_user
        self.git_password = git_password
        self.expires_at = expires_at
        self.note = note
        self.login_hint = login_hint

    @property
    def api_usable(self) -> bool:
        return bool(KINDS.get(self.kind, {}).get("api"))

    @property
    def expires_in(self) -> int | None:
        return None if self.expires_at is None else int(self.expires_at - time.time())


def _api_base(provider: str, host: str) -> str:
    if provider == "github":
        return "https://api.github.com" if host.lower() in ("github.com", "www.github.com") \
            else f"https://{host}/api/v3"
    if provider == "gitlab":
        return f"https://{host}/api/v4"
    return ""


def normalize_host(provider: str, raw: str) -> str:
    host = (raw or "").strip().strip("/")
    for suffix in ("/api/v3", "/api/v4", "/api"):
        if host.endswith(suffix):
            host = host[: -len(suffix)]
    if host.lower().startswith("http"):
        host = host.split("://", 1)[1].strip("/")
    if not host:
        host = "github.com" if provider == "github" else "gitlab.com"
    return host


def _store_refresh(cid: str | None, patch: dict) -> None:
    """Write a rotated secret back to the vault (MERGE — the vault merges by default, so a refresh
    that returns only `access_token` cannot drop the `refresh_token` it did not mention)."""
    if not cid or not patch:
        return
    import accounts                            # local import: accounts imports adapters, not us
    body, status = accounts.vault_update_secret(cid, patch)
    if status >= 300:
        log.warning("token write-back for %s failed (%s): %s", cid, status, body)


# ── GitHub ───────────────────────────────────────────────────────────────────────────────────────
def _gh_app_credential(secret: dict, api: str, cid: str | None) -> Credential:
    """Mint an installation access token from the App's private key (RS256 JWT, 1 hour).

    A GitHub App is the ONLY credential here that can be created without a human hand-copying a
    token, and the only one an organisation can grant narrowly: the App is installed on chosen
    repositories and mints itself a token that dies in an hour. What the vault stores is therefore
    the durable half — `app_id`, `private_key`, `installation_id`.
    """
    try:
        import jwt as pyjwt
    except ImportError:                        # pragma: no cover - image installs PyJWT[crypto]
        raise CredentialError("רכיב PyJWT חסר בתמונה — אין אפשרות להנפיק טוקן של GitHub App.",
                              status=500)
    app_id = str(secret.get("app_id") or "").strip()
    key = (secret.get("private_key") or "").strip()
    if not app_id or not key:
        raise CredentialError("חסרים app_id או private_key של ה-GitHub App.", status=400)
    now = int(time.time())
    try:
        assertion = pyjwt.encode({"iat": now - 60, "exp": now + 540, "iss": app_id},
                                 key, algorithm="RS256")
    except Exception as e:                     # a malformed key is a user error, not a crash
        raise CredentialError("מפתח ה-private_key של ה-GitHub App אינו תקין (צריך PEM בפורמט RSA).",
                              status=400, detail=f"{type(e).__name__}: {e}")
    if isinstance(assertion, bytes):
        assertion = assertion.decode("ascii")
    h = {"Authorization": f"Bearer {assertion}", "Accept": "application/vnd.github+json",
         "User-Agent": UA}
    installation = str(secret.get("installation_id") or "").strip()
    with httpx.Client(timeout=httpx.Timeout(30.0)) as c:
        if not installation:
            r = c.get(f"{api}/app/installations", headers=h)
            if r.status_code >= 300:
                raise CredentialError("לא ניתן לקרוא את רשימת ההתקנות של ה-GitHub App.",
                                      status=r.status_code, detail=r.text[:300])
            items = r.json() or []
            if not items:
                raise CredentialError("ל-GitHub App אין התקנות — יש להתקין אותו על חשבון/ארגון.",
                                      status=400)
            installation = str(items[0].get("id"))
            _store_refresh(cid, {"installation_id": installation})
        r = c.post(f"{api}/app/installations/{installation}/access_tokens", headers=h)
        if r.status_code >= 300:
            raise CredentialError("הנפקת טוקן ההתקנה נכשלה.", status=r.status_code,
                                  detail=r.text[:300])
        token = (r.json() or {}).get("token") or ""
        if not token:
            raise CredentialError("GitHub לא החזיר טוקן התקנה.", status=502)
        # The installation's account name is DISPLAY ONLY (the account label in the UI). It is
        # fetched separately so a failure here cannot cost us a working credential — but the
        # failure is still read and logged, because "the label is blank" and "the GET failed" are
        # different states and only one of them is worth looking at later.
        login = None
        try:
            resp = c.get(f"{api}/app/installations/{installation}", headers=h)
            if resp.status_code < 300:
                login = ((resp.json() or {}).get("account") or {}).get("login")
            else:
                log.info("installation %s lookup returned %s: %s", installation,
                         resp.status_code, resp.text[:200])
        except (httpx.HTTPError, ValueError) as e:
            log.info("installation %s lookup failed: %s", installation, type(e).__name__)
    return Credential("github", "app",
                      {"Authorization": f"Bearer {token}",
                       "Accept": "application/vnd.github+json", "User-Agent": UA},
                      "x-access-token", token,
                      expires_at=now + 3600, login_hint=login,
                      note="טוקן התקנה זמני (שעה) — מונפק מחדש אוטומטית.")


def _gh_oauth_refresh(secret: dict, cid: str | None) -> str | None:
    rt = (secret.get("refresh_token") or "").strip()
    cidv = (secret.get("client_id") or "").strip()
    cs = (secret.get("client_secret") or "").strip()
    if not (rt and cidv and cs):
        return None
    with httpx.Client(timeout=httpx.Timeout(30.0)) as c:
        r = c.post("https://github.com/login/oauth/access_token",
                   headers={"Accept": "application/json"}, data={
                       "client_id": cidv, "client_secret": cs,
                       "grant_type": "refresh_token", "refresh_token": rt})
    if r.status_code >= 300:
        raise CredentialError("חידוש טוקן ה-OAuth של GitHub נכשל.", status=r.status_code,
                              detail=r.text[:300])
    body = r.json() or {}
    tok = body.get("access_token")
    if not tok:
        raise CredentialError("חידוש ה-OAuth לא החזיר access_token.", status=502,
                              detail=str(body)[:300])
    patch = {"token": tok}
    if body.get("refresh_token"):
        patch["refresh_token"] = body["refresh_token"]
    if body.get("expires_in"):
        patch["expires_at"] = int(time.time()) + int(body["expires_in"])
    _store_refresh(cid, patch)
    return tok


# ── GitLab ───────────────────────────────────────────────────────────────────────────────────────
def _gl_oauth_refresh(secret: dict, api: str, cid: str | None) -> str | None:
    rt = (secret.get("refresh_token") or "").strip()
    cidv = (secret.get("client_id") or "").strip()
    cs = (secret.get("client_secret") or "").strip()
    if not (rt and cidv and cs):
        return None
    host = normalize_host("gitlab", secret.get("host") or "")
    with httpx.Client(timeout=httpx.Timeout(30.0)) as c:
        r = c.post(f"https://{host}/oauth/token", data={
            "client_id": cidv, "client_secret": cs,
            "grant_type": "refresh_token", "refresh_token": rt})
    if r.status_code >= 300:
        raise CredentialError("חידוש טוקן ה-OAuth של GitLab נכשל.", status=r.status_code,
                              detail=r.text[:300])
    body = r.json() or {}
    tok = body.get("access_token")
    if not tok:
        raise CredentialError("חידוש ה-OAuth לא החזיר access_token.", status=502,
                              detail=str(body)[:300])
    patch = {"token": tok}
    if body.get("refresh_token"):
        patch["refresh_token"] = body["refresh_token"]
    if body.get("expires_in"):
        patch["expires_at"] = int(time.time()) + int(body["expires_in"])
    _store_refresh(cid, patch)
    return tok


# ── the entry point ──────────────────────────────────────────────────────────────────────────────
def credential_for(provider: str, secret: dict, cid: str | None = None) -> Credential:
    """One secret → the headers and the git password, minting or refreshing what expires."""
    secret = secret or {}
    kind = (secret.get("kind") or "pat").strip()
    if provider == "generic":
        token = (secret.get("token") or "").strip()
        if not token:
            raise CredentialError("חסר טוקן לחשבון הזה.", status=400)
        user = (secret.get("username") or "oauth2").strip() or "oauth2"
        return Credential("generic", "generic_token", {}, user, token,
                          note="מארח Git כללי — קוד (clone/push) בלבד, בלי API.")
    if provider == "forgejo":
        # The office's own forge. One auth method and no expiry logic: the token is minted ONCE by
        # this app's own bootstrap (hooks/prepare) and stored in the vault, and Forgejo access
        # tokens do not expire unless a person sets an expiry on them. The API wants
        # `Authorization: token <t>`; git-over-HTTPS through the proxy wants BASIC with the
        # username and the token as the password — Forgejo honours both, and the username is NOT
        # cosmetic there (an empty one is rejected).
        token = (secret.get("token") or "").strip()
        if not token:
            raise CredentialError("לחשבון הפורג' המקומי אין טוקן שמור בוולט — הרץ שוב את "
                                  "apps/git/hooks/prepare כדי להנפיק אחד.", status=400)
        user = (secret.get("username") or "").strip() or "office"
        base = (secret.get("base_url") or os.environ.get("FORGE_URL")
                or "http://forge:3000").rstrip("/")
        return Credential("forgejo", "pat",
                          {"Authorization": f"token {token}", "User-Agent": UA},
                          user, token, note=f"פורג' מקומי: {base}")
    if provider not in ("github", "gitlab"):
        raise CredentialError(f"אין תמיכה בספק {provider!r}.", status=400)

    host = normalize_host(provider, secret.get("host") or "")
    api = _api_base(provider, host)

    if provider == "github":
        if kind == "app":
            cache_key = f"{cid}:app"
            with _CACHE_LOCK:
                hit = _CACHE.get(cache_key)
            if hit and hit[2] and hit[2] - _APP_TOKEN_SKEW > time.time():
                return Credential("github", "app",
                                  {"Authorization": f"Bearer {hit[1]}",
                                   "Accept": "application/vnd.github+json", "User-Agent": UA},
                                  "x-access-token", hit[1], expires_at=hit[2], login_hint=hit[0])
            cred = _gh_app_credential(secret, api, cid)
            with _CACHE_LOCK:
                _CACHE[cache_key] = (cred.login_hint, cred.git_password, cred.expires_at)
            return cred
        token = (secret.get("token") or "").strip()
        if kind == "oauth":
            # A GitHub OAuth app's token may never expire (the default) or may expire in 8 hours
            # (when the app enables expiration). The secret carries `expires_at` when the second is
            # true, and only then is a refresh attempted — a refresh call against a non-expiring
            # token is a wasted round trip, and worse, a mutation.
            expires_at = secret.get("expires_at")
            if expires_at and float(expires_at) - 60 <= time.time():
                new = _gh_oauth_refresh(secret, cid)
                if new:
                    token = new
                    expires_at = int(time.time()) + 28800
        if not token:
            raise CredentialError("בחשבון GitHub אין טוקן שמור.", status=400)
        return Credential("github", kind,
                          {"Authorization": f"Bearer {token}",
                           "Accept": "application/vnd.github+json", "User-Agent": UA},
                          "x-access-token", token,
                          expires_at=int(secret["expires_at"]) if secret.get("expires_at") else None)

    # ── GitLab ──
    if kind == "oauth":
        token = (secret.get("token") or "").strip()
        expires_at = secret.get("expires_at")
        if expires_at and float(expires_at) - 60 <= time.time():
            new = _gl_oauth_refresh(secret, api, cid)
            if new:
                token = new
                expires_at = int(time.time()) + 7200
        if not token:
            raise CredentialError("בחשבון GitLab אין טוקן שמור.", status=400)
        return Credential("gitlab", "oauth",
                          {"Authorization": f"Bearer {token}", "User-Agent": UA},
                          "oauth2", token,
                          expires_at=int(expires_at) if expires_at else None)
    if kind == "deploy_token":
        user = (secret.get("username") or "").strip()
        token = (secret.get("token") or "").strip()
        if not user or not token:
            raise CredentialError("Deploy token דורש גם שם משתמש וגם טוקן.", status=400)
        return Credential("gitlab", "deploy_token", {}, user, token,
                          note="Deploy token: clone/push לפי ההרשאה שהוקצתה לו; אין גישת API.")
    token = (secret.get("token") or "").strip()
    if not token:
        raise CredentialError("בחשבון GitLab אין טוקן שמור.", status=400)
    return Credential("gitlab", kind, {"PRIVATE-TOKEN": token, "User-Agent": UA},
                      "oauth2", token)
