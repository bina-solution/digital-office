"""git — the ACCOUNT plane: every git account is an instance in the credential plane.

The design is the platform's, not this app's (ai/context/platform-service-contract.md §1): a
connection is an account, and the vault — `platform-base/connections` — is the ONE copy of it. This
module is the only place that talks to that vault, so "where does a token live" has exactly one
answer in this app: not here.

A PROTOCOL IS capability + auth method (§0), and nowhere is that truer than git: "GitHub" is not one
credential, it is four, and they differ in what they can do, how long they live and who can grant
them. So each one is its own protocol, which is also what makes the account bar truthful:

    git_github_pat             classic PAT                  long-lived, user-scoped
    git_github_fine_grained    fine-grained PAT             per-repo permissions
    git_github_app             GitHub App installation      minted hourly, no user, org-grantable
    git_github_oauth           OAuth (refreshable)          expires, refreshed from the vault
    git_gitlab_pat             personal access token        scope `api`
    git_gitlab_group_token     group access token           one group + its subgroups
    git_gitlab_project_token   project access token         one project, a bot user
    git_gitlab_oauth           OAuth (refreshable)          expires, refreshed from the vault
    git_gitlab_deploy_token    deploy token                 CODE ONLY — no API at all
    git_generic_token          any other HTTPS git host     CODE ONLY — Gitea, Bitbucket, Azure…

What the vault stores per instance is the DURABLE half of each: a token, or an App's `app_id` +
`private_key` + `installation_id`, or an OAuth pair with its refresh token. What it never stores is a
minted token that will be dead in an hour — `credentials.py` holds those in memory and re-mints them.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

import httpx

log = logging.getLogger("git.accounts")

CONNECTIONS_URL = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")
STATE_DIR = Path(os.environ.get("GIT_STATE_DIR", "/data"))
PROBE_TTL = float(os.environ.get("GIT_PROBE_TTL", "60"))
_VT = 10.0          # the vault is in-network; a slow reply is a broken reply

# protocol → (provider, kind). The auth METHOD is the protocol, exactly as `drive_google_oauth` and
# `drive_local` are two protocols for one capability.
PROTOCOLS: dict[str, tuple[str, str]] = {
    "git_github_pat": ("github", "pat"),
    "git_github_fine_grained": ("github", "fine_grained"),
    "git_github_app": ("github", "app"),
    "git_github_oauth": ("github", "oauth"),
    "git_gitlab_pat": ("gitlab", "pat"),
    "git_gitlab_group_token": ("gitlab", "group_token"),
    "git_gitlab_project_token": ("gitlab", "project_token"),
    "git_gitlab_oauth": ("gitlab", "oauth"),
    "git_gitlab_deploy_token": ("gitlab", "deploy_token"),
    "git_generic_token": ("generic", "generic_token"),
    # The office's OWN forge — a provider like any other, deliberately: local repositories and the
    # mirrors of external ones are driven through the same op surface, so `createRepo` on this
    # account creates a real repository in the local forge and every other op (issues, PR, releases,
    # files) acts on it too. See adapters/forge.py and mirrors.py.
    "git_forge_local": ("forgejo", "pat"),
    # The first spelling this app used was provider-level, not method-level. Kept resolvable so an
    # account created before the split keeps working; new accounts always carry the auth method.
    "git_github_token": ("github", "pat"),
    "git_gitlab_token": ("gitlab", "pat"),
}
# What this service ADVERTISES and OWNS — the legacy aliases are accepted, never offered.
OWNED_PROTOCOLS = [p for p, (_prov, kind) in PROTOCOLS.items()
                   if p not in ("git_github_token", "git_gitlab_token")]


def provider_kind(protocol: str) -> tuple[str, str]:
    return PROTOCOLS.get(protocol or "", ("", ""))


def protocol_of(provider: str, kind: str) -> str:
    """The canonical protocol for a (provider, method) pair — the modern spelling, always."""
    for proto, (prov, k) in PROTOCOLS.items():
        if prov == provider and k == kind and proto not in ("git_github_token", "git_gitlab_token"):
            return proto
    return ""


# ── the provider catalogue: the owner picks a PROVIDER, the method follows (§4b) ─────────────────
def _pat_fields(host_label: str, host_placeholder: str) -> list[dict]:
    return [
        {"name": "token", "label": "טוקן", "type": "password", "required": True, "dir": "ltr"},
        {"name": "host", "label": f"מארח ({host_label})", "type": "text",
         "placeholder": host_placeholder, "dir": "ltr"},
        {"name": "namespace", "label": "ארגון/משתמש כברירת מחדל", "type": "text", "dir": "ltr"},
    ]


PROVIDERS = [
    {
        # First in the catalogue because it is the office's own: no wizard, no token typed by a
        # person, no external account. apps/git/hooks/prepare mints its credential on enable (an
        # admin user + an access token in the local forge → the vault), which is why `explain` below
        # reads as a RECOVERY procedure rather than a shopping list.
        "id": "forgejo",
        "name": "הפורג' המקומי (Forgejo)",
        "icon": "git-branch",
        "description": "ספריית הקוד של הלשכה — מאגרים מקומיים, ומראות של מאגרים מספקים חיצוניים.",
        "auth_methods": [
            {
                "id": "pat", "kind": "pat", "protocol": protocol_of("forgejo", "pat"),
                "label": "טוקן של הפורג'", "recommended": True,
                "needs": ["token"], "optional": ["base_url", "username"],
                "can": "מאגרים מקומיים, issues, PR, releases, קבצים ודחיפת קוד — בפורג' של הלשכה.",
                "explain": "החשבון הזה נוצר על ידי הלשכה עצמה בזמן ההרמה (apps/git/hooks/prepare): "
                           "משתמש admin בפורג' וטוקן גישה שנשמר בוולט, ואין מה להקליד כאן. אם הטוקן "
                           "אבד — הנפק טוקן בפורג' (Settings → Applications → Generate New Token "
                           "עם הרשאות repository ו-admin) והדבק אותו כאן, או הרץ שוב את ה-hook.",
                "fields": [
                    {"name": "token", "label": "טוקן", "type": "password", "required": True,
                     "dir": "ltr"},
                    {"name": "base_url", "label": "כתובת הפורג' (ריק = הפורג' של הלשכה)",
                     "type": "text", "placeholder": "http://forge:3000", "dir": "ltr"},
                    {"name": "username", "label": "שם המשתמש בפורג'", "type": "text",
                     "placeholder": "office", "dir": "ltr"},
                ],
            },
        ],
    },
    {
        "id": "github",
        "name": "GitHub",
        "icon": "git-branch",
        "description": "github.com או GitHub Enterprise Server (self-managed).",
        "auth_methods": [
            {
                "id": "pat", "kind": "pat", "protocol": protocol_of("github", "pat"),
                "label": "טוקן אישי קלאסי (PAT)", "recommended": True,
                "needs": ["token"],
                "fields": _pat_fields("GitHub Enterprise בלבד", "github.example.com"),
                "can": "מאגרים, issues, PR, releases, קבצים ודחיפת קוד — בשם החשבון.",
                "explain": "GitHub → Settings → Developer settings → Tokens (classic). סמן repo "
                           "(ו-delete_repo רק אם תרצה למחוק מאגרים, ו-workflow אם תדחוף שינויי "
                           "GitHub Actions).",
                "help_url": "https://github.com/settings/tokens",
            },
            {
                "id": "fine_grained", "kind": "fine_grained",
                "protocol": protocol_of("github", "fine_grained"),
                "label": "טוקן fine-grained",
                "needs": ["token"],
                "fields": _pat_fields("GitHub Enterprise בלבד", "github.example.com"),
                "can": "אותן פעולות, בהרשאה מצומצמת לכל מאגר בנפרד.",
                "explain": "בחר את המאגרים ואת ההרשאות: Contents (קבצים/ענפים/releases), Issues, "
                           "Pull requests, ו-Administration אם תרצה ליצור מאגר. חלק מה-endpoints "
                           "אינם נתמכים בטוקן כזה, והארגון יכול לחסום אותו.",
                "help_url": "https://github.com/settings/personal-access-tokens",
            },
            {
                "id": "app", "kind": "app", "protocol": protocol_of("github", "app"),
                "label": "GitHub App (התקנה)",
                "needs": ["app_id", "private_key"], "optional": ["installation_id"],
                "can": "כל פעולת API שההתקנה הורשתה לה; טוקן ההתקנה מונפק ומתחדש אוטומטית.",
                "explain": "הדרך הנקייה: ה-App מותקן על מאגרים נבחרים ומנפיק לעצמו טוקן בן שעה, בלי "
                           "טוקן אישי שיכול לדלוף. GitHub → Settings → Developer settings → GitHub "
                           "Apps → New, ואז Generate a private key. הרשאות מומלצות: Contents, "
                           "Issues, Pull requests, ו-Administration אם תרצה יצירת מאגרים. המפתח "
                           "נשמר בוולט ואינו יוצא ממנו.",
                "help_url": "https://github.com/settings/apps",
                "fields": [
                    {"name": "app_id", "label": "App ID", "type": "text", "required": True,
                     "dir": "ltr"},
                    {"name": "private_key", "label": "Private key (PEM)", "type": "textarea",
                     "required": True, "dir": "ltr",
                     "placeholder": "-----BEGIN RSA PRIVATE KEY-----"},
                    {"name": "installation_id", "label": "Installation ID (ריק = ההתקנה הראשונה)",
                     "type": "text", "dir": "ltr"},
                    {"name": "host", "label": "מארח (GitHub Enterprise בלבד)", "type": "text",
                     "placeholder": "github.example.com", "dir": "ltr"},
                    {"name": "namespace", "label": "ארגון כברירת מחדל", "type": "text", "dir": "ltr"},
                ],
            },
            {
                "id": "oauth", "kind": "oauth", "protocol": protocol_of("github", "oauth"),
                "label": "OAuth (אפליקציית OAuth)",
                "needs": ["token"], "optional": ["refresh_token", "client_id", "client_secret"],
                "can": "כמו טוקן אישי, בזהות אפליקציית ה-OAuth והמשתמש שאישר אותה.",
                "explain": "טוקן של OAuth App. אם הפעלת תפוגת טוקנים ב-GitHub — הדבק גם "
                           "refresh_token, client_id ו-client_secret, והטוקן יחודש אוטומטית "
                           "והחידוש יישמר חזרה בוולט.",
                "help_url": "https://github.com/settings/developers",
                "fields": [
                    {"name": "token", "label": "Access token", "type": "password", "required": True,
                     "dir": "ltr"},
                    {"name": "refresh_token", "label": "Refresh token", "type": "password",
                     "dir": "ltr"},
                    {"name": "client_id", "label": "Client ID", "type": "text", "dir": "ltr"},
                    {"name": "client_secret", "label": "Client secret", "type": "password",
                     "dir": "ltr"},
                    {"name": "host", "label": "מארח (Enterprise בלבד)", "type": "text", "dir": "ltr"},
                ],
            },
        ],
    },
    {
        "id": "gitlab",
        "name": "GitLab",
        "icon": "git-branch",
        "description": "gitlab.com או GitLab self-managed.",
        "auth_methods": [
            {
                "id": "pat", "kind": "pat", "protocol": protocol_of("gitlab", "pat"),
                "label": "טוקן אישי (PAT)", "recommended": True,
                "needs": ["token"],
                "fields": _pat_fields("self-managed בלבד", "gitlab.example.com"),
                "can": "מאגרים, issues, MR, releases, קבצים ודחיפת קוד.",
                "explain": "GitLab → Preferences → Access tokens עם scope api (read_api לבדו אינו "
                           "מספיק לכתיבה, ו-write_repository אינו מאמת את ה-API).",
                "help_url": "https://gitlab.com/-/user_settings/personal_access_tokens",
            },
            {
                "id": "group_token", "kind": "group_token",
                "protocol": protocol_of("gitlab", "group_token"),
                "label": "טוקן קבוצה (group access token)",
                "needs": ["token"],
                "fields": _pat_fields("self-managed בלבד", "gitlab.example.com"),
                "can": "כל הפרויקטים בקבוצה ובקבוצות המשנה שלה.",
                "explain": "נוצר בהגדרות הקבוצה (Settings → Access tokens), גם הוא עם scope api. "
                           "החשבון יוצג כ-bot של הקבוצה.",
                "help_url": "https://docs.gitlab.com/user/group/settings/group_access_tokens/",
            },
            {
                "id": "project_token", "kind": "project_token",
                "protocol": protocol_of("gitlab", "project_token"),
                "label": "טוקן פרויקט (project access token)",
                "needs": ["token"],
                "fields": _pat_fields("self-managed בלבד", "gitlab.example.com"),
                "can": "הפרויקט הזה בלבד — קוד, issues, MR ו-releases בו.",
                "explain": "מוגבל לפרויקט אחד מעצם הגדרתו: אינו יכול ליצור פרויקטים ואינו רואה "
                           "אחרים, ומופיע כ-bot. אם צריך יצירת מאגרים — זה לא הכלי.",
                "help_url": "https://docs.gitlab.com/user/project/settings/project_access_tokens/",
            },
            {
                "id": "oauth", "kind": "oauth", "protocol": protocol_of("gitlab", "oauth"),
                "label": "OAuth (אפליקציית GitLab)",
                "needs": ["token"], "optional": ["refresh_token", "client_id", "client_secret"],
                "can": "כמו טוקן אישי, בזהות האפליקציה והמשתמש.",
                "explain": "טוקן OAuth עם refresh_token, client_id ו-client_secret — הטוקן יחודש "
                           "אוטומטית לפני שיפוג, והחידוש נשמר חזרה בוולט.",
                "help_url": "https://gitlab.com/-/user_settings/applications",
                "fields": [
                    {"name": "token", "label": "Access token", "type": "password", "required": True,
                     "dir": "ltr"},
                    {"name": "refresh_token", "label": "Refresh token", "type": "password",
                     "dir": "ltr"},
                    {"name": "client_id", "label": "Application ID", "type": "text", "dir": "ltr"},
                    {"name": "client_secret", "label": "Secret", "type": "password", "dir": "ltr"},
                    {"name": "host", "label": "מארח (self-managed בלבד)", "type": "text",
                     "dir": "ltr"},
                ],
            },
            {
                "id": "deploy_token", "kind": "deploy_token",
                "protocol": protocol_of("gitlab", "deploy_token"),
                "label": "Deploy token (קוד בלבד)",
                "needs": ["username", "token"], "optional": ["namespace"],
                "can": "clone ו-push לפי הרשאת ה-token — בלי API.",
                "explain": "נוצר בפרויקט/קבוצה (Settings → Repository → Deploy tokens) ונועד ל-clone "
                           "ו-push בלבד. החשבון הזה לא יציע issues או MR. שים את נתיב הפרויקט "
                           "בשדה ה-namespace (למשל group/project).",
                "help_url": "https://docs.gitlab.com/user/project/deploy_tokens/",
                "fields": [
                    {"name": "username", "label": "Deploy token username", "type": "text",
                     "required": True, "dir": "ltr"},
                    {"name": "token", "label": "Deploy token", "type": "password", "required": True,
                     "dir": "ltr"},
                    {"name": "namespace", "label": "נתיב הפרויקט", "type": "text", "dir": "ltr",
                     "placeholder": "group/project"},
                    {"name": "host", "label": "מארח (self-managed בלבד)", "type": "text",
                     "dir": "ltr"},
                ],
            },
        ],
    },
    {
        "id": "generic",
        "name": "מארח Git אחר",
        "icon": "git-branch",
        "description": "Gitea/Forgejo, Bitbucket, Azure DevOps — כל מארח Git ב-HTTPS.",
        "auth_methods": [
            {
                "id": "generic_token", "kind": "generic_token",
                "protocol": protocol_of("generic", "generic_token"),
                "label": "טוקן / סיסמת אפליקציה (קוד בלבד)",
                "needs": ["host", "token"], "optional": ["username"],
                "can": "clone ו-push בלבד.",
                "explain": "המארח, שם המשתמש (או oauth2 / x-token לפי המארח) והטוקן. clone ו-push "
                           "עובדים במלואם; פעולות API (issues/PR/releases) אינן נתמכות למארח כללי, "
                           "כי לכל אחד יש API אחר.",
                "fields": [
                    {"name": "host", "label": "מארח", "type": "text", "required": True,
                     "placeholder": "git.example.com", "dir": "ltr"},
                    {"name": "username", "label": "שם משתמש (לפי המארח)", "type": "text",
                     "placeholder": "oauth2", "dir": "ltr"},
                    {"name": "token", "label": "טוקן / סיסמה", "type": "password", "required": True,
                     "dir": "ltr"},
                ],
            },
        ],
    },
]


def provider_entry(provider: str) -> dict | None:
    return next((p for p in PROVIDERS if p["id"] == provider), None)


def auth_method(provider: str, method: str) -> dict | None:
    p = provider_entry(provider) or {}
    return next((m for m in (p.get("auth_methods") or []) if m["id"] == method), None)


def method_for_kind(provider: str, kind: str) -> dict | None:
    p = provider_entry(provider) or {}
    return next((m for m in (p.get("auth_methods") or []) if m.get("kind") == kind), None)


OT = httpx.Timeout(_VT)


# ── the vault ────────────────────────────────────────────────────────────────────────────────────
def _vault_error(e: Exception) -> str:
    return "שירות החיבורים אינו זמין"


def vault_list() -> tuple[list[dict], str | None]:
    """(instances of OUR protocols, error).

    The error is returned rather than folded into an empty list on purpose: "the vault is down" and
    "no git account is connected" look identical in a list, and only one of them is a reason to tell
    the owner to connect an account. Same lesson as computers' vault_list.
    """
    try:
        with httpx.Client(timeout=OT) as c:
            r = c.get(f"{CONNECTIONS_URL}/api/instances")
        r.raise_for_status()
        insts = list((r.json() or {}).get("instances", []))
        return [i for i in insts if i.get("protocol") in PROTOCOLS], None
    except (httpx.HTTPError, ValueError) as e:
        return [], _vault_error(e)


def vault_secret(cid: str) -> dict | None:
    try:
        with httpx.Client(timeout=OT) as c:
            r = c.get(f"{CONNECTIONS_URL}/api/instances/{cid}/secret")
        r.raise_for_status()
        return (r.json() or {}).get("secret") or {}
    except (httpx.HTTPError, ValueError) as e:
        log.warning("vault secret for %s unavailable: %s", cid, type(e).__name__)
        return None


def vault_add(protocol: str, label: str, secret: dict, account_hint: str | None) -> tuple[dict, int]:
    body: dict = {"protocol": protocol, "label": label, "secret": secret}
    if account_hint:
        body["account_hint"] = account_hint
    try:
        with httpx.Client(timeout=OT) as c:
            r = c.post(f"{CONNECTIONS_URL}/api/instances", json=body)
        return (r.json() if r.content else {}), r.status_code
    except ValueError:
        return {"error": "הוולט החזיר תשובה שאינה JSON"}, 502
    except httpx.HTTPError as e:
        return {"error": _vault_error(e)}, 502


def vault_update_secret(cid: str, secret: dict) -> tuple[dict, int]:
    """Merge-write a secret back (rotated refresh token, learned installation id).

    The vault merges by default, so a refresh that returns only `access_token` cannot drop the
    `refresh_token` it did not mention.
    """
    try:
        with httpx.Client(timeout=OT) as c:
            r = c.put(f"{CONNECTIONS_URL}/api/instances/{cid}/secret", json={"secret": secret})
        return (r.json() if r.content else {}), r.status_code
    except ValueError:
        return {"error": "הוולט החזיר תשובה שאינה JSON"}, 502
    except httpx.HTTPError as e:
        return {"error": _vault_error(e)}, 502


def vault_delete(cid: str) -> tuple[dict, int]:
    try:
        with httpx.Client(timeout=OT) as c:
            r = c.delete(f"{CONNECTIONS_URL}/api/instances/{cid}")
        return (r.json() if r.content else {"ok": r.is_success}), r.status_code
    except ValueError:
        return {"error": "הוולט החזיר תשובה שאינה JSON"}, 502
    except httpx.HTTPError as e:
        return {"error": _vault_error(e)}, 502


# ── the active pointer (the service's own state, and the only thing it keeps) ────────────────────
_active_lock = threading.Lock()
ACTIVE_PATH = STATE_DIR / "active.json"


def active_id() -> str | None:
    try:
        return (json.loads(ACTIVE_PATH.read_text(encoding="utf-8")) or {}).get("active")
    except (OSError, ValueError):
        return None


def set_active(cid: str | None) -> None:
    with _active_lock:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = ACTIVE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"active": cid}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(ACTIVE_PATH)


def resolve(cid: str | None = None) -> tuple[dict | None, dict | None, str | None]:
    """(instance, secret-with-kind, error) for one account — the named one, or the active one.

    An explicitly named id that does not exist is an ERROR, never a silent fall-back to the active
    account: acting on the wrong account is the failure mode a fallback produces, and it produces it
    on a write. The `kind` is derived from the PROTOCOL — one source of truth — and injected into the
    secret, so `credentials.py` and the adapters never consult the protocol table themselves.
    """
    insts, err = vault_list()
    if err:
        return None, None, err
    if not insts:
        return None, None, "לא מחובר אף חשבון Git — חבר חשבון במסך „ניהול גרסאות”."
    want = cid or active_id()
    if not want:
        return None, None, "לא נבחר חשבון פעיל — בחר חשבון במסך „ניהול גרסאות”."
    inst = next((i for i in insts if i.get("id") == want), None)
    if not inst:
        return None, None, f"החשבון {want} אינו קיים בוולט."
    sec = vault_secret(want)
    if sec is None:
        return inst, None, "לא ניתן לקרוא את סוד החשבון מהוולט."
    _provider, kind = provider_kind(inst.get("protocol") or "")
    if kind:
        sec = {**sec, "kind": kind}
    return inst, sec, None


def adapter_for_instance(inst: dict, sec: dict):
    """The adapter for a RESOLVED instance: provider from the protocol, credential from the secret."""
    from adapters import adapter_for
    provider, _kind = provider_kind(inst.get("protocol") or "")
    return adapter_for(provider, sec or {}, inst.get("id"))


# ── probes: a connection is VERIFIED, never merely "added" (§4b) ─────────────────────────────────
_probe_lock = threading.Lock()
_probe_cache: dict[str, tuple[float, dict]] = {}


def probe_instance(inst: dict, secret: dict, max_age: float | None = None) -> dict:
    """{state, reason, login, …} for one account, cached briefly.

    The adapter's `whoami` is the probe: the cheapest call that proves the credential is real, names
    who it belongs to, and reveals what it may do. A 401 is a STATE — "דורש טיפול" — not an exception.

    A code-only credential (a GitLab deploy token, any generic host) has no API to be probed with, and
    saying so is the truth: it is verified by the first clone or push, and the UI says exactly that
    rather than showing a green chip it has not earned.
    """
    from credentials import KINDS, CredentialError
    cid = inst.get("id") or "?"
    provider, kind = provider_kind(inst.get("protocol") or "")
    ttl = PROBE_TTL if max_age is None else max_age
    now = time.time()
    with _probe_lock:
        hit = _probe_cache.get(cid)
    if hit and now - hit[0] < ttl:
        return hit[1]

    if not KINDS.get(kind, {}).get("api"):
        out = {"ok": True, "state": "git_only", "git_only": True, "api_usable": False,
               "reason": None,
               "note": "קוד בלבד (clone/push) — אין API לאימות; יאומת בפעולת ה-git הראשונה."}
        with _probe_lock:
            _probe_cache[cid] = (now, out)
        return out

    out: dict
    try:
        a = adapter_for_instance(inst, secret)
        who = a.whoami()
        out = {"ok": True, "state": "ok", "login": who.get("login"),
               "name": who.get("name"), "scopes": who.get("scopes"),
               "capabilities": who.get("capabilities") or {},
               "auth_kind": who.get("auth_kind"), "expires_in": who.get("expires_in"),
               "api_usable": True, "note": who.get("note"),
               "base_url": a.base_url}
    except CredentialError as e:
        out = {"ok": False, "state": "needs_action", "reason": e.he_message,
               "status": e.status, "api_usable": True}
    except Exception as e:                    # a probe NEVER raises: it reports
        status = getattr(e, "status", None)
        out = {"ok": False, "state": "needs_action" if status in (401, 403) else "error",
               "reason": getattr(e, "he_message", None) or str(e), "status": status,
               "api_usable": True}
    with _probe_lock:
        _probe_cache[cid] = (now, out)
    return out


def forget_probe(cid: str | None = None) -> None:
    with _probe_lock:
        _probe_cache.pop(cid, None) if cid else _probe_cache.clear()


def account_row(inst: dict) -> dict:
    """The console's account-bar row for one instance. State is probed, never assumed."""
    protocol = inst.get("protocol") or ""
    provider, kind = provider_kind(protocol)
    sec = vault_secret(inst.get("id")) or {}
    method = method_for_kind(provider, kind) or {}
    row = {
        "id": inst.get("id"),
        "provider": provider,
        "protocol": protocol,
        "kind": kind,
        "kind_label": method.get("label") or kind,
        "label": inst.get("label") or provider or "חשבון",
        "account_hint": inst.get("account_hint") or "",
        "host": sec.get("host") or ("github.com" if provider == "github"
                                    else "gitlab.com" if provider == "gitlab" else ""),
        "namespace": sec.get("namespace") or "",
        "readonly": bool(sec.get("readonly")),
        "created_at": inst.get("created_at"),
    }
    row.update(probe_instance(inst, sec))
    return row
