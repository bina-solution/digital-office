"""connections — the single credential plane for digital-office.

One declarative catalog (providers/*.yaml) describes EVERY secret/connection in the estate; a
per-service manifest (manifests/*.yaml) declares what each service requires. Values are the only
state and warm-start from .env, resolved in a fixed order:

    vault store  ->  .env seed  ->  install-wizard prompt

- Fully declarative: behaviour is git YAML; adding a connection = a catalog entry, no code.
- Secret-zero: the vault is encrypted at rest; ONE root key (CONNECTIONS_ROOT_KEY) unlocks it.
- Health != presence: probes hit the live services (http/tcp/redis/derived/qr) so green means it works.
- Never leaks values: the API/UI return masked values + a source badge only.

Interfaces: HTTP API + this UI + cli.py (declarative-driven throughout).
"""
import base64, glob, hashlib, hmac, html, json, os, re, secrets, socket, string, tempfile, threading, time, urllib.parse, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

import yaml
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from flask import Flask, jsonify, request, Response

import broker
import identity
import totp

ROOT = os.path.dirname(os.path.abspath(__file__))
VAULT_PATH = os.path.join(ROOT, "data", "vault.enc")
GROUPS = {"10": "Infra & Edge", "20": "n8n (automation core)", "30": "Google", "40": "Apps & Data"}
# WhatsApp bot: connections surfaces its pairing QR + live state so "connect WhatsApp from the console"
# is real (the bot owns the Baileys session; connections is the single onboarding pane over it).
# Contributed by the chat app's app.json; empty when no chat app is installed, and _wa_request
# then reports "unreachable" rather than dialling a container that is not there.
WA_BOT_URL = os.environ.get("WA_BOT_URL", "").rstrip("/")

app = Flask(__name__)


# ── vault: encrypted-at-rest KV, unlocked by ONE root key (secret-zero) ──
#: The key a vault falls back to when CONNECTIONS_ROOT_KEY is unset. It is in this file, so a vault under it is
#: readable by anyone who has the vault file (S26, hos-002); an office still on it is told so at start and moves
#: off it with the two-key step below.
DEV_ROOT_KEY = "dev-root-key-not-for-production"


def _key(root):
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(root.encode()).digest()))


def _fernet():
    """The vault's keys. CONNECTIONS_ROOT_KEY encrypts; CONNECTIONS_ROOT_KEY_OLD (comma-separated) still
    decrypts. That is how a key is REPLACED without losing a byte (hos-002): set the new key with the old
    one beside it, restart, `rekey()` re-encrypts the vault under the new key, then drop the old."""
    root = os.environ.get("CONNECTIONS_ROOT_KEY") or DEV_ROOT_KEY
    olds = [k.strip() for k in (os.environ.get("CONNECTIONS_ROOT_KEY_OLD") or "").split(",") if k.strip()]
    return MultiFernet([_key(root)] + [_key(k) for k in olds if k != root])


class VaultUnreadable(RuntimeError):
    """The vault file exists and none of the configured keys opens it."""


#: Keys that are public: the code's fallback and .env.ex's placeholder.
PUBLIC_ROOT_KEYS = {DEV_ROOT_KEY, "CHANGE_ME"}

if (os.environ.get("CONNECTIONS_ROOT_KEY") or DEV_ROOT_KEY) in PUBLIC_ROOT_KEYS:
    print("[connections] WARNING: the vault is encrypted with a PUBLIC key (the one in app.py or .env.ex's "
          "placeholder): anyone with the vault file can open it. Replace it: a new CONNECTIONS_ROOT_KEY with the "
          "old one in CONNECTIONS_ROOT_KEY_OLD, then restart — the vault re-encrypts itself (hos-002).", flush=True)


# Connection ids that were RENAMED. {old: new} — applied on every read, so a deployment that predates
# a rename keeps working before anything is re-minted.
#
# Renaming a connection in a provider catalog changes what the injector LOOKS UP; it does nothing to
# what is already in the vault. Without this the lookup misses, the injector emits nothing, and the
# consuming service silently falls back to its compiled-in default password — while the connections UI
# still shows a healthy, auto-minted credential. Nothing errors; the service just stops authenticating.
RENAMED_CONNECTIONS = {"wadmin-auth": "chat-auth"}


def _apply_renames(store):
    """Surface old keys under their new id. Read-side only, and the NEW key always wins — a
    re-minted credential must never be shadowed by the stale one it replaced. Companion keys
    ("<id>:KEY") move too, including their env-name segment where that was renamed with the id."""
    for old, new in RENAMED_CONNECTIONS.items():
        if old in store:
            store.setdefault(new, store[old])
        for k, v in list(store.items()):
            if k.startswith(f"{old}:"):
                env = k.split(":", 1)[1]
                store.setdefault(f"{new}:{env.replace('WADMIN_', 'CHAT_')}", v)
    return store


def vault_read():
    """The vault's store. A vault the keys cannot open RAISES (VaultUnreadable): it used to read as `{}`, and
    the next write persisted that empty store over every secret, so one changed CONNECTIONS_ROOT_KEY would
    have wiped the vault with no error anywhere (found while making the key replaceable, hos-002)."""
    if not os.path.exists(VAULT_PATH):
        return {}
    raw = open(VAULT_PATH, "rb").read()
    try:
        plain = _fernet().decrypt(raw)
    except InvalidToken:
        raise VaultUnreadable(f"{VAULT_PATH}: no configured key opens the vault (CONNECTIONS_ROOT_KEY, "
                              f"CONNECTIONS_ROOT_KEY_OLD) — refusing to read it as empty") from None
    try:
        return _apply_renames(json.loads(plain.decode()))
    except ValueError:
        raise VaultUnreadable(f"{VAULT_PATH}: decrypted but not a vault (not JSON)") from None


def rekey() -> int:
    """Re-encrypt the vault under CONNECTIONS_ROOT_KEY. Returns the number of top-level entries carried over.
    Run by the SERVER itself at start while CONNECTIONS_ROOT_KEY_OLD is set (below), before it serves: a
    `docker exec` process would hold its own lock, not the server's, and race a request's write."""
    with _vault_lock:
        store = vault_read()
        vault_write(store)
        return len(store)


def vault_write(store):
    """Write-then-rename, and the tmp name must be unique PER WRITE, not per process: flask serves
    this app threaded, so a pid-scoped tmp is one shared path — writer B truncates writer A's tmp
    mid-write, A renames B's half-written bytes over the vault, every later decrypt fails, vault_read
    swallows that as `{}`, and the next write persists the empty store. The whole vault is gone, with
    no error anywhere. Observed under two concurrent secret writes; mkstemp makes it unreachable."""
    os.makedirs(os.path.dirname(VAULT_PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(VAULT_PATH), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(_fernet().encrypt(json.dumps(store).encode()))
            f.flush()
            os.fsync(f.fileno())    # a sleep or a crash between write and rename must not leave a 0-byte vault
        os.replace(tmp, VAULT_PATH)
    except Exception:
        try:
            os.unlink(tmp)          # never leave a stray encrypted fragment next to the vault
        except OSError:
            pass
        raise


# ── chat bridge: the chat service serves its own QR/state; connections proxies it with the admin
#    basic-auth (chat-auth) so the console shows/scans the QR without leaving the credential plane. ──
def _wa_auth():
    """The chat service's admin basic-auth.

    Catalog id is chat-auth (CHAT_AUTH_USER/PASS); the service code reads AUTH_USERNAME/AUTH_PASSWORD
    — we bridge both, defaulting to the service's own defaults.

    The pre-rename `wadmin-auth` vault key is handled centrally by RENAMED_CONNECTIONS in vault_read,
    so it does not need a second fallback here. The env fallbacks stay because a deployment can still
    be configured entirely from .env with nothing in the vault at all.
    """
    store = vault_read()
    user = (store.get("chat-auth:CHAT_AUTH_USER")
            or os.environ.get("CHAT_AUTH_USER") or os.environ.get("WADMIN_AUTH_USER")
            or os.environ.get("AUTH_USERNAME") or "admin")
    pw = (store.get("chat-auth")
          or os.environ.get("CHAT_AUTH_PASS") or os.environ.get("WADMIN_AUTH_PASS")
          or os.environ.get("AUTH_PASSWORD") or "1234")
    return user, pw


def _wa_request(path, method="GET"):
    """Call the bot with basic auth. Returns (status, content_type, raw_bytes) or (None, None, None)."""
    if not WA_BOT_URL:
        return None, None, None
    user, pw = _wa_auth()
    tok = base64.b64encode(f"{user}:{pw}".encode()).decode()
    req = urllib.request.Request(WA_BOT_URL + path, method=method,
                                 headers={"Authorization": f"Basic {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=4) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "") if e.headers else "", e.read()
    except Exception:
        return None, None, None


def _wa_state():
    """Live pairing state from the bot: {reachable, is_connected, has_qr, botNumber}."""
    st, ct, body = _wa_request("/api/bot/state")
    if st != 200 or not body:
        return {"reachable": False, "is_connected": False, "has_qr": False, "botNumber": None}
    try:
        d = json.loads(body)
    except Exception:
        return {"reachable": True, "is_connected": False, "has_qr": False, "botNumber": None}
    return {"reachable": True, "is_connected": bool(d.get("is_connected")),
            "has_qr": bool(d.get("qr_text")), "botNumber": d.get("botNumber")}


# ── declarative layers ──
def catalog():
    """Secret/connection catalog. `consumers` is DERIVED, never authored.

    Each provider used to carry a hand-written `consumers: [n8n, apitools, incoming-documents]`
    back-link — a layer-1 base app naming layer-3 apps, which goes stale the moment one is
    uninstalled (the lists still named `feature-validation`). The forward direction is the only
    one anyone maintains: each app declares the secrets it needs in its own `connections[]`.
    So invert it here and compute the back-link from the compiled manifest."""
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "providers", "*.yaml"))):
        grp = GROUPS.get(os.path.basename(f)[:2], "Other")
        for p in yaml.safe_load(open(f)) or []:
            p["group"] = grp
            out[p["id"]] = p
    # Providers an APP owns, compiled from its contributes.connection_providers. Loaded before the
    # consumer join so an app-owned secret gets its back-link like any other. providers/*.yaml is
    # layer-1 config, so a secret that exists only because a layer-3 app exists — portainer's admin
    # password — had to be authored there, which is a base app naming an installable one. Now the
    # app declares it, and uninstalling the app removes the secret from the catalog rather than
    # leaving an entry probing a container nobody has.
    try:
        with open(os.path.join(GENERATED, "connections.providers.yaml"), encoding="utf-8") as f:
            for p in (yaml.safe_load(f) or []):
                p.setdefault("group", GROUPS.get("40", "Other"))
                p.pop("_app", None)              # provenance for the registry, not for the API
                out[p["id"]] = p
    except (OSError, ValueError):
        pass
    for sid, users in manifest().items():
        if sid in out:
            out[sid]["consumers"] = sorted({u["service"] for u in users})
    # A probe URL that names a layer-3 service is contributed BY that app
    # (contributes.connection_probes) and compiled into the registry — this file must not
    # hardcode http://apitools:8080/health.
    try:
        with open(os.path.join(GENERATED, "connections.probes.json"), encoding="utf-8") as f:
            for sid, spec in (json.load(f) or {}).items():
                if sid in out:
                    # a bare string is the common http case; an object is a structured probe
                    out[sid]["probe"] = ({"type": "http", "url": spec}
                                         if isinstance(spec, str) else spec)
    except (OSError, ValueError):
        pass
    return out


# connections is a layer-1 base app: it must not author the list of services that need secrets.
# Each app declares its own `connections[]` and reconcile.py compiles them into
# .generated/registry/connections.consumers.yaml, mounted here read-only. manifests/ remains as
# the fallback so the service still boots if it is run without a render.
GENERATED = os.getenv("GENERATED_REGISTRY", "/app/generated")


def _manifest_files():
    gen = os.path.join(GENERATED, "connections.consumers.yaml")
    if os.path.exists(gen):
        return [gen]
    return sorted(glob.glob(os.path.join(ROOT, "manifests", "*.yaml")))


def manifest():
    reqs = {}
    for f in _manifest_files():
        for svc in yaml.safe_load(open(f)) or []:
            for r in svc.get("requires", []):
                reqs.setdefault(r["id"], []).append(
                    {"service": svc["service"], "required": r.get("required", False)})
    return reqs


def service_requires(service):
    """The connections ONE compose service declares — i.e. its capability list.

    This is the whole authorization input for the broker: an app may be granted what its own
    app.json `connections[]` names and nothing else, so this function is the manifest half of
    "narrow, declared, refusable". Empty list = declares nothing = gets nothing."""
    for f in _manifest_files():
        for svc in yaml.safe_load(open(f)) or []:
            if svc.get("service") == service:
                return svc.get("requires", []) or []
    return []


# Values that .env.ex ships as fill-me-in markers. `present` must not mistake any of them for a
# configured secret — see probe().
_PLACEHOLDER_MARKERS = ("your-", "your_", "change_me", "changeme", "example.com", "<", "todo",
                        "placeholder", "xxx", "fill-me", "fillme", "replace_me", "replace-me",
                        # belt-and-braces: the fabricated stand-in this code used to mint itself.
                        # resolve() no longer produces it, but a vault written by an older build
                        # still can — and it must never read as configured again.
                        "derived:")


def _is_placeholder(v):
    low = str(v).strip().lower()
    return any(m in low for m in _PLACEHOLDER_MARKERS)


def mask(v):
    if not v:
        return None
    return (v[:3] + "…" + v[-2:]) if len(v) > 6 else "•••"


# ── secret-base pillars: app-password | auth | infra (explicit `pillar:` or inferred) ──
_AUTH_KINDS = {"oauth-client", "oauth-grant", "qr-session", "sa-key", "cert", "app-password", "totp"}
_APP_PW_HINTS = ("admin", "-auth", "bootstrap", "dashboard", "owner", "login")


def _pillar(prov):
    if prov.get("pillar"):
        return prov["pillar"]
    kind = prov.get("kind")
    if kind in _AUTH_KINDS:
        return "auth"
    cid = prov.get("id", "")
    if kind in ("password", "basic-auth") and any(h in cid for h in _APP_PW_HINTS):
        return "app-password"
    if kind == "text-secret" and cid.endswith(("-key", "-token", "-api-token")) \
            and "encryption" not in cid and "secret-key" not in cid:
        return "auth"        # api keys are outbound auth, not infra
    return "infra"


_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def _public_url(value):
    """Turn a `*_BASE_URL` env (a BARE HOST — see .env.ex) into a URL that actually opens.

    THE HOST DECIDES THE SCHEME. This used to be a flat `"https://" + url`, which is right on the
    VPS and dead in dev: the platform's edge convention (platform/manager/reconcile.py
    `routing_labels`) serves `<host>.localhost` on the plain **web** entrypoint, and ACME cannot
    issue a certificate for a `.localhost` name — so there is no TLS listener behind
    `https://portainer.localhost` and every "open app" link on this page was a dead link locally.
    Identical rule and rationale as `_public_n8n_url()` in apps/any-concurrency/app.py.

    An explicit scheme is preserved for real domains, so a TLS deployment is unchanged.
    """
    url = (value or "").strip()
    if not url:
        return ""
    parts = urllib.parse.urlsplit(url if "://" in url else "//" + url)
    netloc = parts.netloc
    if not netloc:
        return ""
    host = netloc.split("@")[-1].rsplit(":", 1)[0].strip("[]").lower()
    local = host in _LOCAL_HOSTS or host.endswith(".localhost")
    scheme = "http" if local else (parts.scheme or "https")
    return urllib.parse.urlunsplit((scheme, netloc, parts.path.rstrip("/"), parts.query, ""))


def _resolve_app(prov):
    """For app-password rows: resolve the catalog `app:` block into a concrete
    {name, url, user} the UI can render an 'open app' link + login hint from.
    `url_env`/`user_env` are read live from the environment (deployment-aware:
    portainer.<domain> in prod, portainer.localhost in dev) so nothing is hardcoded."""
    app = prov.get("app")
    if not app:
        return None
    url = app.get("url") or (os.environ.get(app["url_env"], "") if app.get("url_env") else "")
    url = _public_url(url)
    user = app.get("user") or (os.environ.get(app["user_env"], "") if app.get("user_env") else "")
    return {"name": app.get("name", prov.get("title", prov.get("id"))),
            "url": url or None, "user": user or None}


# ── auth protocol: explicit `protocol:` or inferred from kind/id ──
# The auth pillar is a protocol-aware credential manager; this names the protocol
# so the UI can label it + pick the right connect/test lifecycle.
_KIND_PROTOCOL = {"oauth-client": "oauth2", "oauth-grant": "oauth2", "qr-session": "qr",
                  "sa-key": "service-account", "cert": "certificate", "app-password": "basic-auth",
                  "totp": "totp"}


def _protocol(prov, pillar):
    if prov.get("protocol"):
        return prov["protocol"]
    if pillar != "auth":
        return None
    kind = prov.get("kind")
    if kind in _KIND_PROTOCOL:
        return _KIND_PROTOCOL[kind]
    cid = prov.get("id", "")
    if kind in ("password", "basic-auth"):
        return "basic-auth"
    if cid.endswith("-token") or "bearer" in cid:
        return "bearer-token"
    return "api-key"     # remaining auth-pillar text-secrets are outbound API keys


# ── platform protocol: capability + auth method (drive_google_oauth, mail_imap_app_password…) ──
# _protocol() above names the AUTH METHOD of a catalog row (oauth2, basic-auth) — that is what the
# credential UI labels. The platform services (drive, mail) need the capability too, and no catalog
# row can infer it: ONE Google grant feeds BOTH Drive and Gmail. So a provider that backs a platform
# service says so explicitly, as a single value or a list when one grant covers several.
_PLATFORM_CAPS = ("drive_", "mail_")


def _platform_protocols(prov):
    """The platform protocol(s) this provider's credential can back. Explicit yaml wins; otherwise
    accept `protocol:`/_protocol() only when it already IS a platform protocol (never a bare
    'oauth2' — that would create instances no platform service can resolve)."""
    ps = prov.get("platform_protocols") or prov.get("platform_protocol")
    if ps:
        return [ps] if isinstance(ps, str) else list(ps)
    p = _protocol(prov, _pillar(prov))
    return [p] if p and str(p).startswith(_PLATFORM_CAPS) else []


# ── a consent for ONE protocol, and an office that connects one READ-ONLY (EXU-24, from Exampleu's 9810127) ──
# One Google grant backs Drive AND Gmail with full access. An office that reads a client's Drive must never be
# able to write to it: it declares the protocol in OAUTH_READONLY_PROTOCOLS, and then every consent that would
# mint that protocol's account asks Google for its read-only scopes alone. Offices that declare nothing are
# untouched: a start by provider is the provider-wide grant, as before.
def _readonly_protocols():
    """Protocols this office connects READ-ONLY (`OAUTH_READONLY_PROTOCOLS` in .env, comma-separated)."""
    return {p.strip() for p in os.environ.get("OAUTH_READONLY_PROTOCOLS", "").split(",") if p.strip()}


def _oauth_provider(cid, hint=None):
    """(provider, protocol) for an OAuth start or callback id, else (None, None). The id is a provider
    (`google-workspace-grant`: one consent for every protocol it declares) or a PLATFORM PROTOCOL a provider
    declares (`drive_google_oauth`: a consent for that protocol alone). `hint` is the protocol the app that asks
    serves (the drive door names its engine's): with a provider id it narrows the start to that protocol only
    where this office connects it read-only, so an office without the declaration gets the grant it always got."""
    cat = catalog()
    prov = cat.get(cid or "")
    if prov and "oauth" in prov:
        # honoured where this office connects one of the provider's protocols read-only: there every consent names
        # what it is for (the drive door its Drive, read-only; mailview its Gmail, without Drive)
        protos = _platform_protocols(prov)
        if hint and hint in protos and set(protos) & _readonly_protocols():
            return prov, hint
        return prov, None
    for p in cat.values():
        if "oauth" in p and cid and cid in _platform_protocols(p):
            return p, cid
    return None, None


def oauth_scopes(prov, proto=None):
    """The scopes a consent asks for: the provider's list for a provider-wide start; `protocol_scopes[proto]`
    for a protocol start — its `readonly` list where this office declares the protocol read-only. A read-only
    declaration with no read-only list is REFUSED (ValueError), never widened to full access."""
    o = prov["oauth"]
    if not proto:
        return list(o["scopes"])
    per = (o.get("protocol_scopes") or {}).get(proto) or {}
    ro = _readonly_protocols()
    if proto in ro:
        if not per.get("readonly"):
            raise ValueError(f"{proto} is declared read-only here (OAUTH_READONLY_PROTOCOLS), but {prov['id']} "
                             f"declares no read-only scopes for it")
        return list(per["readonly"])
    if not per.get("full"):
        covered = sorted(set(_platform_protocols(prov)) & ro)
        if covered:
            # the provider's full list would reach the read-only protocol's scopes too (Drive write, for Gmail)
            raise ValueError(f"{proto} declares no scopes of its own, and {prov['id']}'s full list would reach "
                             f"{', '.join(covered)}, read-only here")
    return list(per.get("full") or o["scopes"])


_SCOPE_ALIAS = {"email": "https://www.googleapis.com/auth/userinfo.email",
                "profile": "https://www.googleapis.com/auth/userinfo.profile"}


def _scope_refusal(prov, proto, secret):
    """Why a token of `proto` carries more than `proto` asks for (oauth_scopes), or None. Google answers
    `email`/`profile` as their userinfo URLs; a token that states no scope is refused, never assumed narrow."""
    try:
        want = set(oauth_scopes(prov, proto))
    except ValueError as e:
        return str(e)
    want |= {_SCOPE_ALIAS[s] for s in list(want) if s in _SCOPE_ALIAS}
    raw = (secret or {}).get("scope") if isinstance(secret, dict) else None
    got = set(raw.split()) if isinstance(raw, str) else set()
    beyond = sorted(got - want)
    if not got or beyond:
        return (f"החשבון של {proto} נושא יותר ממה שהוא מבקש: "
                f"{', '.join(beyond) if beyond else 'הרשאה שלא פורטה'} — שום דבר לא נשמר")
    return None


def readonly_refusal(prov, proto, tok=None):
    """Why this start or grant would break the office's read-only declaration, or None.
    1. A PROVIDER-WIDE consent of a provider that backs a read-only protocol asks for full access and mints that
       protocol's account too — refused; the app's own «connect an account» (a protocol start) is the way in.
    2. A PROTOCOL consent's token may carry no scope beyond what that protocol asks for — any protocol, not only a
       read-only one: the scope in the consent's address is not signed, and Google can fold earlier grants into a
       new token, so what was granted is checked, not assumed (a Gmail consent widened to Drive is refused too)."""
    ro = _readonly_protocols()
    if not proto:
        covered = sorted(set(_platform_protocols(prov)) & ro)
        if covered:
            return (f"בלשכה הזו {', '.join(covered)} מחובר לקריאה בלבד (OAUTH_READONLY_PROTOCOLS), והסכמה של "
                    f"{prov['id']} כולה הייתה נותנת גישה מלאה — מחברים את החשבון מתוך האפליקציה שלו («קבצים»), "
                    f"או ב-/oauth/{covered[0]}/start?as_instance=1")
        return None
    if tok is None:
        try:
            oauth_scopes(prov, proto)
        except ValueError as e:
            return str(e)
        return None
    return _scope_refusal(prov, proto, tok)


def secret_readonly_refusal(protocol, secret):
    """Why a secret of `protocol` may not be stored or handed out here, or None. Where the office connects one of a
    provider's protocols read-only, EVERY protocol of that provider is held to its own scopes (oauth_scopes): the
    read-only one to its read-only list, a sibling to its own `full` list — a Gmail account from a provider-wide
    consent made before the declaration carries Drive write too. Whichever way the secret comes (a consent, an
    account added by hand, a renewal written back) or goes (an engine's read); such an account then reads «connect
    again». An office that declares nothing is untouched."""
    ro = _readonly_protocols()
    if not ro or not protocol:
        return None
    prov = next((p for p in catalog().values() if "oauth" in p and protocol in _platform_protocols(p)), None)
    if not prov:
        return f"{protocol} is declared read-only here, but no OAuth provider declares it" if protocol in ro else None
    if not set(_platform_protocols(prov)) & ro:
        return None
    return _scope_refusal(prov, protocol, secret)


# ── multi-field credentials: a credential is its primary env + envs_extra companions.
# The operator edits ALL of them here (n8n = email + password + names), never .env. ──
_FIELD_LABELS = [("_TOTP", "סוד TOTP"), ("USERNAME", "שם משתמש"), ("_USER", "שם משתמש"), ("EMAIL", "אימייל"),
                 ("PASSWORD", "סיסמה"), ("_PASS", "סיסמה"), ("_PW", "סיסמה"),
                 ("FIRSTNAME", "שם פרטי"), ("LASTNAME", "שם משפחה"), ("_NAME", "שם"),
                 ("API_TOKEN", "טוקן API"), ("_TOKEN", "טוקן"), ("APIKEY", "מפתח API"),
                 ("API_KEY", "מפתח API"), ("_KEY", "מפתח"), ("SECRET", "סוד"),
                 ("_URL", "כתובת"), ("_HOST", "מארח"), ("_PORT", "פורט"),
                 ("_EMAIL", "אימייל"), ("_ID", "מזהה"), ("_IPS", "כתובות IP"), ("_DSN", "DSN")]
_SECRET_HINT = ("PASSWORD", "_PASS", "_PW", "TOKEN", "SECRET", "_KEY", "APIKEY", "DSN", "TOTP")


def _field_label(key):
    for suf, label in _FIELD_LABELS:
        if key.endswith(suf) or suf.strip("_") == key or suf in key:
            return label
    return key.split("_")[-1].capitalize()


def _field_is_secret(key):
    return any(h in key for h in _SECRET_HINT)


def _primary_is_secret(prov):
    # config = plain operator settings (emails, IPs, hosts) — shown in the clear.
    return prov.get("kind") != "config"


def _fixed(prov):
    """{field: value} a provider FIXES — shown, given to whoever reads the credential (browser42 takes a login's
    address from its `*_URL` field), never edited (DGO-1825: the Google sign-in address)."""
    fixed = (prov or {}).get("fixed")
    return {str(k): str(v) for k, v in fixed.items()} if isinstance(fixed, dict) else {}


def _reveal_to(prov):
    """The compose services a provider's secret is revealed to (`reveal_to:`), or an empty set: every caller, as
    before. A row that names them says no character of its value anywhere else (`masked` is dots)."""
    names = (prov or {}).get("reveal_to")
    return {str(n) for n in names} if isinstance(names, list) else set()


def _from_a_page(req):
    """A request a WEB PAGE made: a browser always sends `Origin` or a `Sec-Fetch-*` header with a fetch, and a page
    cannot remove them; urllib (logins.py, the task runner, the injector) sends neither (DGO-1825: the agent drives
    the office browser, and a page it opens must not read what that browser's own container may)."""
    if req is None:
        return False
    return bool(req.headers.get("Origin")) or any(k.lower().startswith("sec-fetch-") for k in req.headers.keys())


def _may_have(prov, ident, req=None):
    """May THIS caller be given a `reveal_to` secret? Only a caller the broker VERIFIED as one of the named services
    (its container id matches its address — never an address alone, never in the broker's warn mode) of THIS office's
    compose project (the office network is shared by every office on one docker host: another office's task runner
    is the same service name — the fifth reader; /api/agent-token holds the same rule), or the operator inside this
    container; never a request a page made. A vault that cannot tell its own project gives it to no container. A
    provider that names no one: as before, yes."""
    to = _reveal_to(prov)
    if not to:
        return True
    ident = ident or {}
    if ident.get("method") == "loopback":
        return True
    if _from_a_page(req) or not ident.get("ok") or ident.get("method") != "container-id+ip" \
            or ident.get("service") not in to:
        return False
    project = identity.own_project()
    return bool(project) and ident.get("project") == project


def _login_user(cid, prov, store):
    """A login's user name as saved HERE (its USER/EMAIL companion, never a secret) — shown on its row, as an app's
    `user_env` is (DGO-1825: the Gmail address of the office's Google account)."""
    for k in prov.get("envs_extra") or []:
        if re.search(r"(USER|USERNAME|EMAIL)", k) and not _field_is_secret(k):
            v = store.get(f"{cid}:{k}") or os.environ.get(k)
            if v:
                return {"name": None, "url": None, "user": v}
    return None


def _label(prov, key):
    """A field's label: the provider's own words for it (`labels:`), else the one its name implies."""
    labels = (prov or {}).get("labels")
    return str(labels[key]) if isinstance(labels, dict) and labels.get(key) else _field_label(key)


def _cred_fields(cid, prov, store):
    """Every editable field of a credential: primary (prov.env) + envs_extra companions.
    Secret fields are masked + reveal-gated; non-secret fields (user/email/name) show clear; a field the provider
    fixes is its value, marked `fixed`, and is not stored."""
    out = []
    fixed, hidden = _fixed(prov), bool(_reveal_to(prov))
    # a secret revealed only to named services: no character of it here, and no «reveal» offered on the screen
    shut = (lambda val: "•••" if val else None) if hidden else mask
    primary = prov.get("env")
    if primary:
        src, val = resolve(cid, prov, store)
        sec = _primary_is_secret(prov)
        out.append({"key": primary, "label": _label(prov, primary), "primary": True,
                    "secret": sec, "source": src,
                    **({"reveal": False} if sec and hidden else {}),
                    "masked": shut(val) if sec else val,
                    "clear": (None if sec else val),
                    "derived": str(val or "").startswith("derived:")})
    for k in prov.get("envs_extra", []) or []:
        dbv = store.get(f"{cid}:{k}")
        if k in fixed:
            src, val = "env", fixed[k]
        elif dbv is not None:
            src, val = "db", dbv
        elif os.environ.get(k):
            src, val = "env", os.environ[k]
        else:
            src, val = "unset", None
        sec = _field_is_secret(k) and k not in fixed
        out.append({"key": k, "label": _label(prov, k), "primary": False,
                    "secret": sec, "source": src,
                    **({"reveal": False} if sec and hidden else {}),
                    "masked": shut(val) if sec else val,
                    "clear": (None if sec else val), "derived": False,
                    **({"fixed": True} if k in fixed else {})})
    return out


def _field_store_key(cid, prov, field):
    """DB vault key for a field: the primary env stores at <cid>, companions at <cid>:<KEY>."""
    if not field or field == (prov or {}).get("env"):
        return cid
    return f"{cid}:{field}"


# ── audit log (append-only, in the vault): reveal/edit/rotate/connect/revoke ──
# ── the fourth channel: what was done to a connection, on `dgo:flow:connections` (flow.v1, DGO-1402) ──
# Through the office's ONE publisher, platform-base/redis/flowpub.py, mounted read-only at /opt/dgo
# (docker-compose.yml) — «כל מקביל» draws it as the row «חיבורים ומפתחות», agents hear it (`./bbox
# connections flow`). WHAT goes out: the act, the connection's or instance's id and scalar facts (a
# test's status, a field's name). NEVER a value, a masked value, a token or a key list — the stream is
# read by every agent of the office. An image run without the mount publishes nothing and works the same.
import sys as _sys

_sys.path.insert(0, "/opt/dgo")
try:
    import flowpub as _flowpub
except ImportError:
    _flowpub = None

#: audit event → (flow type, what a person reads; {id} is the connection or the instance)
_FLOW_ACTS = {
    "reveal": ("connection.revealed", "ערך של «{id}» הוצג"),
    "test": ("connection.tested", "החיבור «{id}» נבדק"),
    "edit": ("connection.changed", "החיבור «{id}» שונה"),
    "rotate": ("connection.rotated", "הסוד של «{id}» הוחלף"),
    "add": ("connection.added", "נוסף החיבור «{id}»"),
    "clear": ("connection.reverted", "החיבור «{id}» חזר לברירת המחדל"),
    "disconnect": ("connection.disconnected", "החיבור «{id}» נותק"),
    "instance-create": ("instance.created", "נוסף המופע «{id}»"),
    "instance-delete": ("instance.deleted", "המופע «{id}» הוסר"),
    "instance-secret-update": ("instance.changed", "הפרטים של המופע «{id}» עודכנו"),
}


def _flow(event, cid, **extra):
    if _flowpub is None or event not in _FLOW_ACTS:
        return
    type_, title = _FLOW_ACTS[event]
    facts = {k: v for k, v in extra.items() if isinstance(v, (bool, int, float)) or k in ("status", "field", "protocol", "source")}
    facts = {k: (str(v)[:80] if isinstance(v, str) else v) for k, v in facts.items()}
    if event == "test" and extra.get("status") not in (None, "healthy"):
        type_ = "connection.tested.failed"                   # drawn red: the probe did not find it healthy
    _flowpub.emit("connections", type_, title.format(id=str(cid)[:80]), {"id": str(cid)[:80], **facts})


def _audit(event, cid, **extra):
    _flow(event, cid, **extra)
    try:
        store = vault_read()
        log = store.get("__audit__", [])
        log.append({"t": int(time.time()), "event": event, "id": cid, **extra})
        store["__audit__"] = log[-500:]
        vault_write(store)
    except Exception:
        pass


# ── auto-mint: generate absent machine secrets so .env entries are OPTIONAL ──
def generate(spec):
    """Cryptographically strong value per the catalog's automint spec."""
    t = (spec or {}).get("type", "hex")
    if t == "hex":
        return secrets.token_hex(int(spec.get("bytes", 32)))            # == openssl rand -hex N
    if t == "password":
        alpha = string.ascii_letters + string.digits
        return "".join(secrets.choice(alpha) for _ in range(int(spec.get("chars", 24))))
    return secrets.token_urlsafe(32)


def mint_pass(cat, store):
    """For every automint connection NOT overridden in the DB and NOT present in .env: generate it,
    store it (encrypted), and record it as minted. Runs once, sequentially (safe before parallel probes)."""
    minted = set(store.get("__minted__", []))
    changed = False
    for cid, prov in cat.items():
        if "automint" not in prov:
            continue
        if cid in store:                       # user override or already minted -> keep
            continue
        if prov.get("env") and os.environ.get(prov["env"]):   # .env supplied it -> respect .env
            continue
        store[cid] = generate(prov["automint"])               # not set anywhere -> mint it
        minted.add(cid); changed = True
    if changed:
        store["__minted__"] = sorted(minted)
        vault_write(store)
    return store


# ── resolution chain: DB override -> .env (live default) -> derived -> unset ──
# The .env stays the source of defaults; a value the user saves is stored ENCRYPTED in the DB
# (vault) and WINS. Un-overridden connections track .env live. resolve() is read-only.
def resolve(cid, prov, store):
    if cid in store:                       # user override (encrypted DB) — highest precedence
        return "db", store[cid]
    env_key = prov.get("env")
    if env_key and os.environ.get(env_key):  # .env default, read live
        return "env", os.environ[env_key]
    if prov.get("kind") == "derived":
        # A derived value is MINTED by something else (glitchtip-push mints the DSNs/token into
        # .env). Its base existing proves only that minting is POSSIBLE — not that it HAPPENED.
        # This used to return a sha of the base as if it were the value; `probe: present` then saw a
        # non-empty string and reported healthy, so an EMPTY GLITCHTIP_API_TOKEN/SENTRY_DSN showed
        # green and masked as `der…57`, looking exactly like a real stored secret. That is how the
        # alert path stayed "healthy" while dead. The base is reported for diagnosis; it is NOT the
        # value, so `present` can never pass on it.
        base = os.environ.get(prov.get("derive_from", ""))
        if base:
            return "derivable", None
    return "unset", None


# ── health probes: green only if it actually works ──
def probe(prov, source, value):
    p = prov.get("probe") or {}
    t = p.get("type")
    # A PLACEHOLDER is not a configuration, and no probe run against one can produce a meaningful
    # answer — so it is answered before any probe runs. This check used to live inside the `present`
    # branch only, which meant a provider with a CONTRIBUTED probe took the other path: for
    # `gmail-app-password`, `.env.ex`'s own `your-gmail-app-password` was probed, failed, and was
    # reported `degraded` — "configured, and the dependency is down". It was never configured. Every
    # other untouched integration on that panel correctly read "not configured yet", so the one
    # integration nobody had set up was also the only one demanding attention.
    if value and _is_placeholder(value):
        return "missing", "placeholder value — not configured yet"
    try:
        if prov.get("kind") == "qr-session":
            wa = _wa_state()                         # ask the live bot, not the filesystem
            if not wa["reachable"]:
                # Bot not up yet: fall back to the session dir the OWNING app mounts here
                # (WA_SESSION_DIR, contributed with the mount). No env = that app isn't installed,
                # and "not paired" is the honest answer. The old fallback joined the catalog's
                # `session_path` onto ROOT/../.. — a production/ path the platform-OS refactor
                # renamed away, and once that key was dropped the join collapsed to "/", which IS a
                # directory: an unpaired device read as "paired" whenever the bot was down.
                path = os.environ.get("WA_SESSION_DIR")
                return (("healthy", "paired (session on disk)") if path and os.path.isdir(path)
                        else ("needs_action", "bot offline — start it to pair"))
            if wa["is_connected"]:
                return "healthy", f"paired{(' · ' + wa['botNumber']) if wa['botNumber'] else ''}"
            return "needs_action", "scan QR to pair" if wa["has_qr"] else "bot connecting…"
        if prov.get("kind") in ("oauth-grant",):
            return ("healthy", "token stored") if source == "db" else ("needs_action", "click Connect")
        if prov.get("kind") == "totp" and value:
            # A stored secret that cannot mint a code is a failure the login would otherwise be the
            # first to discover (a `.env`-seeded value is never validated on write). The parser
            # names the fault, never the value.
            try:
                totp.parse(value)
            except ValueError as e:
                return "degraded", f"not a usable TOTP secret: {e}"
        if t == "http":
            with urllib.request.urlopen(p["url"], timeout=2.5) as r:
                return ("healthy", f"HTTP {r.status}") if r.status < 400 else ("degraded", f"HTTP {r.status}")
        if t in ("tcp", "redis"):
            with socket.create_connection((p["host"], int(p["port"])), timeout=2.0):
                return "healthy", f"{p['host']}:{p['port']} open"
        if t == "present" or not t:
            if source in ("db", "minted", "env", "derived") and value:
                # A string is not a secret. .env.ex ships placeholders (`your-google-client-id…`,
                # `change_me_to_…`), and reporting them healthy is worse than reporting nothing:
                # the owner clicks "בדוק חיבור", sees green, and is MORE confident than before he
                # tested. GEMINI_API_KEY=`your-…-key` passed this check while every AI extraction
                # was impossible.
                if _is_placeholder(value):
                    return "missing", "placeholder value — not configured yet"
                return "healthy", source
            return "missing", "not configured"
    except urllib.error.HTTPError as e:
        # The dependency ANSWERED, with a refusal: urlopen raises on a 4xx/5xx, so the `r.status`
        # test above only ever saw a success, and the answer was shown as "probe failed: HTTP Er…".
        return "degraded", f"HTTP {e.code}"
    except Exception as e:
        # a probe error when the value IS set = the dependency is down, not the secret missing
        if source in ("db", "minted", "env", "derived") and value:
            return "degraded", f"probe failed: {str(e)[:40]}"
        return "missing", "not configured"
    return ("healthy", source) if value else ("missing", "not configured")


def _row(cid, prov, reqs, store, minted=frozenset()):
    source, value = resolve(cid, prov, store)
    if source == "db" and cid in minted:
        source = "minted"
    state, detail = probe(prov, source, value)
    # Each consumer declares in its OWN app.json whether it merely USES a connection or cannot run
    # without it. That flag was read here and then thrown away — requiredness came from the
    # provider's `optional` alone, so ANY declared consumer made a connection an install blocker.
    # It is why the install screen demanded an `n8n-api-key` n8n itself declares `required: false`,
    # and told a deployment syncing only local drive+mail to authorise Google first. The consuming
    # app owns this fact; layer 1 may not overrule it.
    declared = {}
    for u in reqs.get(cid, []):
        declared[u["service"]] = declared.get(u["service"], False) or bool(u.get("required"))
    for s in prov.get("consumers", []):   # provider naming its own consumers — no flag to read
        declared.setdefault(s, not prov.get("optional"))
    cons = list(declared)                 # insertion-ordered, declarations first (was: dedupe loop)
    # `optional: true` on the provider stays an absolute veto: a catalog row may declare that it is
    # never a blocker whoever asks for it. Otherwise ONE consumer saying "required" is enough.
    required = (not prov.get("optional")) and any(declared.values())
    if state == "missing" and not required:
        state = "unset"
    # A row NOBODY in this office consumes cannot be degraded. Its probe asks a service that is not
    # part of the office (the name does not even resolve), and "configured, and the dependency is
    # down" about a dependency that was never brought up kept a red dot on a healthy office for as
    # long as that app stayed off — GlitchTip's two secrets on hp-laptop, 2026-10-07.
    # Nor can it need anyone's ACTION: «2 דורשים טיפול» stood over that office for a WhatsApp pairing
    # ("bot offline — start it to pair") and a Google grant ("click Connect") that no app in it uses.
    # The row keeps its connect / pair control — that is offered by the row's kind, not its status.
    if state in ("degraded", "needs_action") and not cons:
        state, detail = "unset", "no service in this office uses it"
    pillar = _pillar(prov)
    secret = _primary_is_secret(prov)
    is_derived = str(value or "").startswith("derived:")
    n_extra = len(prov.get("envs_extra", []) or [])
    return {"id": cid, "group": prov["group"], "pillar": pillar,
            "protocol": _protocol(prov, pillar),
            "app": _resolve_app(prov) or (_login_user(cid, prov, store) if prov.get("pin") else None),
            "title": prov.get("title", cid), "title_he": prov.get("title_he"),
            "kind": prov.get("kind"), "source": source,
            # a value revealed only to named services says none of its characters here (the row is read by anyone)
            "masked": ("•••" if value else None) if _reveal_to(prov) else mask(value),
            "secret": secret, "clear": (None if (secret or is_derived) else value),
            "fields_count": (1 if prov.get("env") else 0) + n_extra,
            "reveal_ok": prov.get("reveal_ok", True) and not is_derived and prov.get("kind") != "totp"
                         and not _reveal_to(prov),
            "rotatable": ("automint" in prov) or bool(prov.get("rotate")),
            "impact": prov.get("impact") or cons, "rotate_warn": prov.get("rotate_warn"),
            "status": state, "detail": detail, "required": required, "optional": bool(prov.get("optional")),
            "env": prov.get("env"), "consumers": cons, "now": prov.get("now", "").strip(),
            # an entry every office has, shown first with what it is for (its provider's `pin`, DGO-1825)
            "pin": bool(prov.get("pin")), "purpose_he": prov.get("purpose_he"), "about_he": prov.get("about_he")}


def custom_catalog(store):
    """User-added ad-hoc secrets (not in the git catalog) live under __custom__ in the vault."""
    out = {}
    for cid, meta in (store.get("__custom__") or {}).items():
        out[cid] = {"id": cid, "group": "Custom (user-added)", "title": meta.get("title", cid),
                    "kind": meta.get("kind", "text-secret"), "consumers": meta.get("consumers", []),
                    "probe": {"type": "present"}, "custom": True,
                    "now": meta.get("now") or "added by a user directly in the connections UI/CLI/API"}
        if meta.get("env"):
            out[cid]["env"] = meta["env"]
        if meta.get("envs_extra"):
            out[cid]["envs_extra"] = meta["envs_extra"]
        if meta.get("wizard"):
            out[cid]["wizard"] = meta["wizard"]
        if meta.get("pillar"):
            out[cid]["pillar"] = meta["pillar"]
    return out


def status_rows():
    cat, reqs, store = catalog(), manifest(), vault_read()
    mint_pass(cat, store)                       # auto-generate absent machine secrets -> DB
    cat = {**cat, **custom_catalog(store)}
    minted = set(store.get("__minted__", []))
    with ThreadPoolExecutor(max_workers=16) as ex:
        return list(ex.map(lambda kv: _row(kv[0], kv[1], reqs, store, minted), cat.items()))


# ── API ──
@app.get("/healthz")
def healthz():
    """`broker` is reported here on purpose: "the credential plane is up" and "the credential plane
    can still tell who is calling it" are different facts, and the second one degrading silently
    (docker socket gone -> every caller unidentified -> warn mode serves everyone) is precisely the
    failure this whole feature exists to prevent."""
    try:
        vault_read()
        vault = "readable"
    except VaultUnreadable:
        vault = "unreadable"
    return jsonify(ok=True, providers=len(catalog()), vault=vault,
                   broker={"mode": broker.MODE, "docker": identity.docker_available()})


@app.errorhandler(VaultUnreadable)
def _vault_unreadable(e):
    """Every route that reads the vault says WHY when it cannot (a 503 with the reason), instead of a bare 500
    that a consumer's inject.sh prints as HTML and boot-loops on (hos-002's second reader)."""
    return jsonify(ok=False, error=str(e), vault="unreadable"), 503


@app.get("/api/connections")
def api_connections():
    rows = status_rows()
    blockers = [r["id"] for r in rows if r["required"] and r["status"] in ("missing", "needs_action")]
    by = {}
    for r in rows:
        by.setdefault(r["status"], 0)
        by[r["status"]] += 1
    return jsonify(connections=rows,
                   summary={"total": len(rows), "by_status": by, "install_blockers": blockers})


@app.post("/api/resolve/<cid>")
def api_resolve(cid):
    prov = catalog().get(cid)
    if not prov:
        return jsonify(error="unknown connection"), 404
    source, value = resolve(cid, prov, vault_read())
    # a value revealed only to named services says none of its characters to anyone (DGO-1825, the third reader)
    shown = ("•••" if value else None) if _reveal_to(prov) else mask(value)
    return jsonify(id=cid, source=source, masked=shown, resolved=bool(value))


@app.get("/api/is-set/<cid>")
def api_is_set(cid):
    """Is this connection SET — a value the office holds for it (its vault override or its .env key), not a
    placeholder — yes or no, and nothing else. (Not `/api/set/<id>`: that path WRITES a value, POST, and clears
    it, DELETE.)

    For a gate that runs before something leaves the office (DGO-1814: the Drive agent asks it before its OpenAI
    nodes, and n8n keeps every node's answer in the execution's record). So: no value and no mask of one
    (`/api/resolve` masks: three characters and two of the key), and no live probe (`/api/connections` probes
    every provider of the office, some of them outside it). Unknown id → 404, `set: false`."""
    prov = {**catalog(), **custom_catalog(vault_read())}.get(cid)
    if not prov:
        return jsonify(id=cid, set=False, known=False), 404
    _, value = resolve(cid, prov, vault_read())
    return jsonify(id=cid, set=bool(value) and not _is_placeholder(value), known=True)


@app.get("/api/cred/<cid>")
def api_cred(cid):
    """The full editable field-set of one credential (primary + envs_extra companions) so the
    operator can view/edit EVERY field here (user, email, password, token…) — never .env."""
    store = vault_read()
    prov = catalog().get(cid) or custom_catalog(store).get(cid)
    if not prov:
        return jsonify(error="unknown connection"), 404
    return jsonify(id=cid, title=prov.get("title", cid), title_he=prov.get("title_he"),
                   app=_resolve_app(prov), now=prov.get("now", "").strip(),
                   fields=_cred_fields(cid, prov, store))


@app.post("/api/reveal/<cid>")
def api_reveal(cid):
    """Reveal the ACTUAL resolved value of a field — the ONE route that returns a real secret.
    Deliberate, audit-logged. Optional {field} targets a companion; default = the primary."""
    store = vault_read()
    prov = catalog().get(cid) or custom_catalog(store).get(cid)
    if not prov:
        return jsonify(error="unknown connection"), 404
    if prov.get("kind") == "totp":
        # Write-once. A TOTP secret is never read back by a human — the plane mints codes from it —
        # so the one route that returns real secrets refuses this kind over the network; only the
        # operator inside this container (docker exec — the root key's holder anyway) still can.
        # The screen never offers the button: `reveal_ok` is false for the kind (_row).
        ident = broker.caller()
        if ident.get("method") != "loopback":
            broker.audit("reveal", "refuse", ident, connection=cid,
                         reason="a TOTP secret is written once and never revealed over the network")
            return jsonify(error="a TOTP secret is written once and never revealed over the network — "
                                 "GET /api/totp/<id> mints its code; to move it, re-enrol at the provider"), 403
    reveal_to = _reveal_to(prov)
    if reveal_to:
        # REVEALED ONLY TO THE SERVICES IT NAMES (DGO-1825: the office's Google password goes to the office
        # browser's own containers, verified by container id, and to no other — not an agent's container on the same
        # network, not a page the browser opened, not a person's screen; it is written once). The operator inside
        # this container still can.
        ident = broker.caller()
        if not _may_have(prov, ident, request):
            broker.audit("reveal", "refuse", ident, connection=cid,
                         reason=f"revealed only to {', '.join(sorted(reveal_to))}")
            return jsonify(error=f"{cid} is revealed only to {', '.join(sorted(reveal_to))}"), 403
    field = (request.get_json(silent=True) or {}).get("field")
    if field and field in _fixed(prov):            # a value the provider fixes is that value, wherever it is read
        return jsonify(id=cid, field=field, source="env", value=_fixed(prov)[field], revealed=True)
    if field and field != prov.get("env"):        # companion field
        dbv = store.get(f"{cid}:{field}")
        src, value = ("db", dbv) if dbv is not None else \
            (("env", os.environ[field]) if os.environ.get(field) else ("unset", None))
        _audit("reveal", cid, field=field)
        return jsonify(id=cid, field=field, source=src, value=value, revealed=bool(value))
    source, value = resolve(cid, prov, store)
    if str(value or "").startswith("derived:"):
        return jsonify(id=cid, source=source, value=None,
                       note="ערך נגזר אוטומטית ממפתח אחר — אין ערך גולמי להצגה")
    _audit("reveal", cid, source=source)
    return jsonify(id=cid, source=source, value=value, revealed=bool(value))


@app.get("/api/audit")
def api_audit():
    """Recent secret-base events (reveal/edit/rotate/connect/revoke), newest first."""
    return jsonify(audit=list(reversed(vault_read().get("__audit__", [])))[:200])


@app.get("/api/totp/<cid>")
def api_totp(cid):
    """Mint the CURRENT one-time code of a `totp` connection — `{code, next, expires_in}` — so a
    consumer (the office browser passing «אימות דו-שלבי») types a code it was handed and never holds
    the secret that makes it. The only read path for the kind: export and lease skip it, and `reveal`
    stays the owner's deliberate, audited act.

    Stricter than a lease, in EVERY mode: the caller must be identified from outside the request
    (broker.caller — the docker socket, or loopback for the operator inside this container), must be
    the service it names (`?service=`), and that service must declare this row in its own app.json
    connections[]. `warn` mode's "serve the unidentified" exists for the boot injector's staged
    rollout; a one-time code has no rollout. Every answer lands in the grant log; the code never does.

    404 with the FIELD name when the row holds no secret yet — the consumer turns that into its named
    refusal (`needs_totp_secret`) and the human handoff, instead of a guess."""
    store = vault_read()
    prov = catalog().get(cid) or custom_catalog(store).get(cid)
    if not prov or prov.get("kind") != "totp":
        return jsonify(error="not a totp connection", id=cid), 404
    ident = broker.caller()
    want = (request.args.get("service") or "").strip() or None
    try:
        if not ident.get("ok"):
            # Before `authorize`, which serves an unidentified caller in warn mode: a caller the
            # socket cannot name, or one presenting a container id it does not own, gets nothing
            # here whatever the mode. The attempt is in the grant log.
            raise broker.Refusal("caller could not be identified — a one-time code is never served to "
                                 "an unidentified caller, in any mode: " + (ident.get("reason") or "unknown"))
        svc, declared = broker.authorize(ident, want, service_requires)
        if cid not in declared:
            raise broker.Refusal(f"'{cid}' is not in {svc}'s declared connections[]")
    except broker.Refusal as e:
        broker.audit("totp", "refuse", ident, connection=cid, service_requested=want, reason=e.reason)
        return jsonify(error=e.reason, decision="refuse", mode=broker.MODE), e.status
    source, value = resolve(cid, prov, store)
    if not value:
        return jsonify(error="no TOTP secret stored", id=cid, field=prov.get("env")), 404
    try:
        minted = totp.mint(totp.parse(value))
    except ValueError as e:
        return jsonify(error=f"stored TOTP secret is not usable: {e}", id=cid, field=prov.get("env")), 409
    # The grant log is this mint's record (who, which row, when). Not `_audit`: that is a whole-vault
    # read-modify-write outside `_vault_lock`, racing every secret write — see api_instance_secret_put.
    broker.audit("totp", "allow", ident, connection=cid, service_requested=svc, source=source)
    return jsonify(id=cid, **minted)


@app.post("/api/conn/<cid>/test")
def api_conn_test(cid):
    """On-demand live test of a single connection — re-runs its probe against the real
    dependency right now (vs the passive status in /api/connections) and reports back."""
    store = vault_read()
    prov = catalog().get(cid) or custom_catalog(store).get(cid)
    if not prov:
        return jsonify(error="unknown connection"), 404
    source, value = resolve(cid, prov, store)
    state, detail = probe(prov, source, value)
    _audit("test", cid, status=state)
    return jsonify(id=cid, status=state, detail=detail, source=source,
                   ok=(state == "healthy"))


@app.post("/api/set/<cid>")
def api_set(cid):
    """View/change: store a user override in the encrypted DB (wins over .env). Optional {field}
    targets a companion (stored at <cid>:<KEY>); default = the primary value (at <cid>)."""
    b = request.get_json(force=True) or {}
    v, field = b.get("value"), b.get("field")
    if v is None or v == "":
        return jsonify(error="value required"), 400
    store = vault_read()
    prov = catalog().get(cid) or {}
    if field and field in _fixed(prov):
        # a value the provider FIXES (the address a login is for, DGO-1825) is not the operator's to change
        return jsonify(error=f"{field} is fixed by its provider", id=cid, field=field), 400
    key = _field_store_key(cid, prov, field)
    kind = (prov or custom_catalog(store).get(cid) or {}).get("kind")    # a custom row has a kind too
    if kind == "totp" and key == cid:
        # Validated on WRITE and stored in ONE canonical form (an otpauth:// URI carrying digits /
        # period / algorithm), so a login never meets a mistyped secret and an authenticator can
        # import the value back. The refusal names the fault and the field, never the value.
        try:
            v = totp.canonical(v, digits=b.get("digits"), period=b.get("period"), algorithm=b.get("algorithm"))
        except ValueError as e:
            return jsonify(error=f"not a usable TOTP secret: {e}", id=cid, field=prov.get("env")), 400
    store[key] = v; vault_write(store)
    _audit("edit", cid, **({"field": field} if field else {}))
    return jsonify(ok=True, id=cid, field=field, source="db",
                   masked="•••" if _reveal_to(prov) and (_field_is_secret(field) if field else _primary_is_secret(prov))
                   else mask(v))


@app.delete("/api/set/<cid>")
def api_clear(cid):
    """Clear an override -> the field reverts to its live .env default. Optional {field}."""
    field = (request.get_json(silent=True) or {}).get("field")
    prov = catalog().get(cid) or {}
    store = vault_read()
    store.pop(_field_store_key(cid, prov, field), None)
    if not field and cid in (store.get("__custom__") or {}):
        del store["__custom__"][cid]
    vault_write(store)
    _flow("clear", cid, **({"field": field} if field else {}))
    return jsonify(ok=True, id=cid, field=field, reverted_to="env")


@app.post("/api/add")
def api_add():
    """Add a brand-new secret not in the git catalog (stored + registered as Custom)."""
    b = request.get_json(force=True) or {}
    cid, v = b.get("id"), b.get("value")
    if not cid or not v:
        return jsonify(error="id and value required"), 400
    if b.get("kind") == "totp":
        try:
            v = totp.canonical(v)                         # same rule as /api/set: validated, canonical
        except ValueError as e:
            return jsonify(error=f"not a usable TOTP secret: {e}", id=cid), 400
    store = vault_read()
    store[cid] = v
    store.setdefault("__custom__", {})[cid] = {"title": b.get("title", cid),
                                               "kind": b.get("kind", "text-secret"),
                                               "pillar": b.get("pillar") or None,
                                               # A custom secret can be MULTI-FIELD, exactly like a
                                               # catalog one: `env` names the primary field and
                                               # `envs_extra` the companions, so the screen renders
                                               # labelled inputs (שם משתמש / סיסמה / כתובת) and edits
                                               # them through the same /api/set route. Without this a
                                               # secret a human (or a bridge) creates at runtime could
                                               # only ever hold ONE value, which is why site logins —
                                               # a URL, a username and a password — had nowhere to live
                                               # that the owner could see or fix.
                                               "env": b.get("env") or None,
                                               "envs_extra": list(b.get("envs_extra") or []),
                                               "wizard": b.get("wizard") or "",
                                               "consumers": b.get("consumers", [])}
    vault_write(store)
    _flow("add", cid)
    return jsonify(ok=True, id=cid, source="db", masked=mask(v))


@app.post("/api/regenerate/<cid>")
def api_regenerate(cid):
    """Rotate an auto-mintable secret to a fresh strong value (stored in the DB)."""
    prov = catalog().get(cid)
    if not prov or "automint" not in prov:
        return jsonify(error="not an auto-mintable connection"), 400
    store = vault_read()
    store[cid] = generate(prov["automint"])
    store.setdefault("__minted__", [])
    if cid not in store["__minted__"]:
        store["__minted__"] = sorted(set(store["__minted__"] + [cid]))
    vault_write(store)
    _audit("rotate", cid)
    impact = prov.get("impact") or prov.get("consumers", [])
    return jsonify(ok=True, id=cid, source="minted", masked=mask(store[cid]),
                   impact=impact, rotate_warn=prov.get("rotate_warn"))


@app.get("/api/export-all")
def api_export_all():
    """Resolve EVERY catalog secret to its env KEY=value (through DB override / mint / .env / derived).
    ?format=env returns a dotenv body — the connections-sourced secret set that services run off.

    LOOPBACK ONLY (broker.guard_export_all): this route is the documented kill chain's final step,
    and no service needs it — a service needs ITS OWN declared connections, which is what
    /api/broker/lease grants. `cli.py` runs inside this container, so the operator path is intact."""
    try:
        ident = broker.guard_export_all()
    except broker.Refusal as e:
        broker.audit("export-all", "refuse", broker.caller(), reason=e.reason)
        return jsonify(error=e.reason, decision="refuse", mode=broker.MODE), e.status
    broker.audit("export-all", "allow", ident)
    cat, store = catalog(), vault_read()
    mint_pass(cat, store)
    out = {}
    for cid, prov in cat.items():
        env_key = prov.get("env")
        if not env_key or prov.get("kind") == "totp":     # a totp secret is minted, never exported
            continue
        _, val = resolve(cid, prov, store)
        if val and not str(val).startswith("derived:"):
            out[env_key] = val
    if request.args.get("format") == "env":
        return Response("".join(f"{k}={v}\n" for k, v in sorted(out.items())), mimetype="text/plain")
    return jsonify(count=len(out), keys=sorted(out.keys()))


def export_env(service, only=None, caller=None, req=None):
    """{ENV_KEY: value} for the connections `service` declares — the resolve chain, narrowed.

    `only` is the broker's authorization result: the subset of the service's declared connections
    this particular call may have. Passing None means "everything it declares", which is what the
    boot-time injector asks for. Nothing outside the declaration can be produced here even when
    `only` names it, because the loop iterates the MANIFEST, not the request."""
    cat, store = catalog(), vault_read()
    out = {}
    for r in service_requires(service):
        if only is not None and r["id"] not in only:
            continue
        prov = cat.get(r["id"])
        if not prov or prov.get("kind") == "totp":
            continue        # a totp secret never leaves the plane — GET /api/totp/<id> mints the code
        if not _may_have(prov, caller, req):
            continue        # a `reveal_to` secret goes only to a verified caller it names (DGO-1825), by every path
        prod = {}                                   # what this ONE connection produces (env -> value)
        _, val = resolve(r["id"], prov, store)
        if val and prov.get("env"):
            prod[prov["env"]] = val
        # companion keys (e.g. LOCALMAIL_PW, GMAIL_IMAP_USER): DB override "<id>:<KEY>" wins, else .env
        for k in prov.get("envs_extra", []) or []:
            # a value the provider fixes is that value in a lease too (DGO-1825: one truth for a login's address)
            v = _fixed(prov).get(k) or store.get(f"{r['id']}:{k}") or os.environ.get(k)
            if v:
                prod[k] = v
        out.update(prod)
        # per-consumer aliases: a service that reads a DIFFERENT env name for the same secret
        # declares `as: {CANONICAL_ENV: SERVICE_ENV}` in its manifest, and we also emit it there.
        for src, tgt in (r.get("as") or {}).items():
            if src in prod:
                out[tgt] = prod[src]
    return out


@app.get("/api/export/<service>")
def api_export(service):
    """INJECTOR (legacy route): resolve every connection a service requires into KEY=value pairs.

    Kept for backward compatibility — an unmigrated consumer still boots against it — but it is now
    behind the SAME policy as the broker: the caller is identified from the docker socket, and a
    caller that is provably a different service is refused whatever it puts in the URL. Prefer
    POST /api/broker/lease, which also records a lease id and per-connection grants."""
    try:
        ident, service = broker.guard_export(service, service_requires)
    except broker.Refusal as e:
        broker.audit("export", "refuse", broker.caller(), service_requested=service, reason=e.reason)
        return jsonify(error=e.reason, decision="refuse", mode=broker.MODE), e.status
    out = export_env(service, caller=ident, req=request)
    broker.audit("export", "allow", ident, service_requested=service,
                 connections=[r["id"] for r in service_requires(service)],
                 unidentified=not ident.get("ok"))
    if request.args.get("format") == "env":
        body = "\n".join(f"{k}={v}" for k, v in out.items()) + "\n"
        return Response(body, mimetype="text/plain")
    return jsonify(service=service, env={k: mask(v) for k, v in out.items()}, count=len(out))


@app.get("/api/manifest")
def api_manifest():
    return jsonify(manifest=manifest())


# ── WhatsApp QR: surface the bot's pairing QR + state INSIDE the credential plane ──
@app.get("/api/qr/<cid>")
def api_qr_state(cid):
    """Live pairing state for a qr-session connection (default: the WhatsApp bot)."""
    prov = catalog().get(cid)
    if not prov or prov.get("kind") != "qr-session":
        return jsonify(error="not a qr-session connection"), 404
    wa = _wa_state()
    return jsonify(id=cid, **wa, qr_png=f"/api/qr/{cid}/png" if wa["has_qr"] else None)


@app.get("/api/qr/<cid>/png")
def api_qr_png(cid):
    """Proxy the bot's QR PNG so the console renders it without touching the bot directly."""
    prov = catalog().get(cid)
    if not prov or prov.get("kind") != "qr-session":
        return jsonify(error="not a qr-session connection"), 404
    st, ct, body = _wa_request("/api/bot/qr")
    if st == 200 and body:
        return Response(body, mimetype=ct or "image/png")
    return jsonify(error="qr unavailable", detail="bot offline or already paired"), 404


@app.post("/api/disconnect/<cid>")
def api_disconnect(cid):
    """Unified disconnect: oauth-grant -> drop token; qr-session -> log the bot out; else clear override.
    The connection reverts to unset/needs_action so it can be re-connected cleanly."""
    prov = catalog().get(cid)
    if not prov:
        return jsonify(error="unknown connection"), 404
    kind = prov.get("kind")
    store = vault_read()
    if kind == "qr-session":
        st, _, _ = _wa_request("/api/bot/disconnect", method="POST")
        return jsonify(ok=st in (200, 204), id=cid, action="whatsapp-logout", bot_status=st)
    store.pop(cid, None)                       # oauth token or user override both live under cid
    vault_write(store)
    _flow("disconnect", cid)
    return jsonify(ok=True, id=cid, action=("revoke-grant" if kind == "oauth-grant" else "clear-override"),
                   reverted_to="needs_action" if kind == "oauth-grant" else "env")


# ── feature enable/disable: a per-service flag the console reflects (grey out a module) ──
@app.get("/api/features")
def api_features():
    disabled = set(vault_read().get("__disabled__", []))
    services = sorted({s["service"] for f in glob.glob(os.path.join(ROOT, "manifests", "*.yaml"))
                       for s in (yaml.safe_load(open(f)) or [])})
    return jsonify(features=[{"service": s, "enabled": s not in disabled} for s in services])


@app.post("/api/features/<service>")
def api_feature_toggle(service):
    enabled = bool((request.get_json(force=True) or {}).get("enabled", True))
    store = vault_read()
    dis = set(store.get("__disabled__", []))
    dis.discard(service) if enabled else dis.add(service)
    store["__disabled__"] = sorted(dis)
    vault_write(store)
    return jsonify(ok=True, service=service, enabled=enabled)


# ── connection INSTANCES: many accounts per protocol ──
# The provider model above is strictly one id -> one env var, which cannot express "a second Drive
# account": there is nowhere to put the second value. Instances are the parallel concept the platform
# services (drive :8975, mail :8970) consume — id-keyed records under the vault's `instances` key,
# each holding its own live secret. Purely additive: providers/.env/injection are untouched.
_INSTANCES = "instances"
_PROTO_CHARS = set(string.ascii_lowercase + string.digits + "_")
# An instance id is a URL path segment too (`/api/instances/<iid>`), and a caller-proposed one
# (see create_instance) may carry `-` and `.` on top of the protocol's alphabet.
_ID_CHARS = set(string.ascii_lowercase + string.digits + "_.-")

# The vault is a whole-file read-modify-write (vault_read -> mutate -> vault_write): the write itself
# is atomic (tmp + os.replace) but the READ->WRITE window is not, so two concurrent mutations both
# start from the same store and the loser's change vanishes. This lock closes that window for the
# secret-update path, which is the one that races in practice: drive and mail can renew the same
# Google token at the same moment. Flask serves this app in ONE process (app.run, threaded), so a
# process-local lock is sufficient here — it would NOT be under multiple workers, and it does not
# guard the other writers (create/delete/_audit/features), which stay as they were.
_vault_lock = threading.Lock()


def _rekey_at_start():
    """A key replacement finishes itself (hos-002): while CONNECTIONS_ROOT_KEY_OLD is set, the server
    re-encrypts the vault under the new key once, before it serves; then the old key can be dropped from .env.
    A vault no key opens is left as it is and said (every route answers 503 with the reason)."""
    if not (os.environ.get("CONNECTIONS_ROOT_KEY_OLD") or "").strip() or not os.path.exists(VAULT_PATH):
        return
    try:
        n = rekey()
        print(f"[connections] the vault is re-encrypted under CONNECTIONS_ROOT_KEY ({n} entries); "
              f"CONNECTIONS_ROOT_KEY_OLD can now be removed from .env", flush=True)
    except VaultUnreadable as e:
        print(f"[connections] ERROR: {e}", flush=True)


_rekey_at_start()


def _instances(store):
    return store.get(_INSTANCES) or {}


def _instance_public(iid, rec):
    """The Instance shape — deliberately built field-by-field rather than by popping `secret` off the
    record, so a future field added to the record can never leak through the list endpoint."""
    return {"id": iid, "protocol": rec.get("protocol"), "label": rec.get("label"),
            "account_hint": rec.get("account_hint"), "status": rec.get("status", "ok"),
            "created_at": rec.get("created_at")}


def _protocol_match(protocol, pattern):
    """Trailing-* glob only (drive_*): callers filter by capability, not by arbitrary expression."""
    if not pattern or pattern == "*":
        return True
    if pattern.endswith("*"):
        return (protocol or "").startswith(pattern[:-1])
    return protocol == pattern


def create_instance(protocol, label, secret, account_hint=None, status="ok", iid=None):
    """Mint an instance and vault its secret. Shared by the API and the OAuth broker so a
    browser-consented account and a hand-entered one are the same kind of thing afterwards.

    `iid` lets the CALLER name the instance. That is not a convenience: a platform service's own
    built-in engine has a canonical id (`<protocol>-local`) — the name the whole estate already uses
    for "the thing this deployment runs by itself" — and a row addressed by a freshly minted hex id
    moves on every restart, so every stale copy reads as an ordinary, deletable account. The caller
    proposes the id; this plane is free to refuse it, and does when it is taken or malformed.
    """
    store = vault_read()
    if iid:
        if set(str(iid)) - _ID_CHARS:
            raise ValueError("instance id must be lowercase [a-z0-9_.-]")
        if iid in _instances(store):
            raise ValueError(f"instance {iid} already exists")
    else:
        iid = f"{protocol}-{secrets.token_hex(4)}"
    store.setdefault(_INSTANCES, {})[iid] = {
        "protocol": protocol, "label": label or protocol, "account_hint": account_hint,
        "status": status, "created_at": int(time.time()), "secret": secret or {}}
    vault_write(store)
    _audit("instance-create", iid, protocol=protocol)
    return iid


@app.get("/api/instances")
def api_instances():
    """List instances, optionally filtered by protocol glob (?protocol=drive_*). Never returns secrets."""
    pattern = request.args.get("protocol")
    return jsonify(instances=[_instance_public(i, r)
                              for i, r in sorted(_instances(vault_read()).items())
                              if _protocol_match(r.get("protocol"), pattern)])


@app.post("/api/instances")
def api_instance_add():
    """Add an account for a protocol: {protocol,label,secret{},account_hint?,id?}.

    `id` is optional and, when given, is the caller's proposed instance name (see create_instance) —
    a platform service declaring its own built-in engine as `<protocol>-local`. Everything else about
    the call is unchanged, and an id it may not have (taken, or not id-shaped) is a 409/400 naming
    which, never a silent mint of a different one.
    """
    b = request.get_json(force=True, silent=True) or {}
    protocol, secret = b.get("protocol"), b.get("secret")
    if not protocol or not isinstance(secret, dict) or not secret:
        return jsonify(error="protocol and a non-empty secret{} are required"), 400
    # the protocol is half the instance id, and the id is a URL path segment — keep it inert
    if set(str(protocol)) - _PROTO_CHARS:
        return jsonify(error="protocol must be lowercase [a-z0-9_]"), 400
    refused = secret_readonly_refusal(protocol, secret)     # an account added by hand is held to it too (EXU-24)
    if refused:
        return jsonify(error=refused), 409
    try:
        return jsonify(id=create_instance(protocol, b.get("label"), secret, b.get("account_hint"),
                                          iid=b.get("id")))
    except ValueError as e:
        return jsonify(error=str(e), requested_id=b.get("id")), 409


@app.delete("/api/instances/<iid>")
def api_instance_del(iid):
    store = vault_read()
    if iid not in _instances(store):
        return jsonify(error="unknown instance"), 404
    del store[_INSTANCES][iid]
    vault_write(store)
    _audit("instance-delete", iid)
    return jsonify(ok=True)


#: Headers only a RELAYED request carries: one that came through the edge (traefik), the console's app proxy
#: or another office's link door. An instance's secret is for this office's own services, which call
#: `connections:8990` directly and send none of them; a relayed caller is a browser or another office, and
#: before this gate a linked office (mapped to akadmin) read and wrote every secret in the vault (hos-001,
#: ai/context/dgo-herd-os.md §3).
_RELAYED_BY = ("X-Forwarded-For", "X-Forwarded-Host", "X-Real-Ip", "X-authentik-username",
               "X-DGO-Office", "X-Dgo-Identity", "X-DGO-From")


def _relayed() -> str:
    """The first relay header on this request, or "" for a direct in-network call."""
    return next((h for h in _RELAYED_BY if request.headers.get(h)), "")


def _refuse_relayed(action, iid):
    """A 403 for a relayed request to an instance's secret, in the grant log; None when the call is direct."""
    via = _relayed()
    if not via:
        return None
    why = f"an instance's secret is for this office's own services, not a request relayed through {via}"
    broker.audit(action, "refuse", broker.caller(), instance=iid, reason=why)
    return jsonify(error=why, decision="refuse"), 403


@app.get("/api/instances/<iid>/secret")
def api_instance_secret(iid):
    """Service-only, in-network: platform services fetch the live secret here at op time, so
    credentials live in exactly one place.

    Deliberately kept OUT of the vault's `_audit` trail (it fires on every drive op and would drown
    the reveal/edit history), but it IS written to the broker grant log with the caller's identity —
    a secret leaving the plane with no record of who took it is exactly what the grant log exists to
    end. ⚠ Not yet POLICY-gated: connection instances are per-account OAuth grants with no manifest
    declaration to check against, and `drive` reads them live today. See README residual risks.
    Refused when RELAYED (`_relayed`): only a direct in-network call reads it."""
    refused = _refuse_relayed("instance-secret", iid)
    if refused:
        return refused
    rec = _instances(vault_read()).get(iid)
    if not rec:
        return jsonify(error="unknown instance"), 404
    # a grant wider than this office's read-only declaration (one from before it) is never handed out (EXU-24)
    refused = secret_readonly_refusal(rec.get("protocol"), rec.get("secret") or {})
    if refused:
        broker.audit("instance-secret", "refuse", broker.caller(), instance=iid,
                     protocol=rec.get("protocol"), gated=False, reason="read-only")
        return jsonify(error=refused + " — יש לחבר את החשבון מחדש, לקריאה בלבד", read_only=True), 409
    broker.audit("instance-secret", "allow", broker.caller(), instance=iid,
                 protocol=rec.get("protocol"), gated=False)
    return jsonify(protocol=rec.get("protocol"), secret=rec.get("secret") or {})


#: Who may read an agent's action token here. One service always: the link plane hands it to the offices this
#: office serves its agent to (DGO-32, DGO-1127). Anything else asks the agent with its own token — or is one
#: of the readers the compiler declares for that agent (agent_readers, below).
AGENT_TOKEN_READERS = {"dgo-extend"}
_SERVICE_NAME = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,63}$")


def agent_readers(agent):
    """The services the COMPILER says may read `agent`'s token (DGO-1152): registry/agent-token-readers.json,
    {agent service: [reader services]}, derived from the manifests — the services of an app that `use`s a
    capability the agent's app is the one provider of (newsflow uses `browser`: browser42-task-runner's token).
    Never authored here, never widened by a request: a file that is missing or not that shape grants nothing."""
    try:
        with open(os.path.join(GENERATED, "agent-token-readers.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return set()
    readers = data.get(agent) if isinstance(data, dict) else None
    return {r for r in readers if isinstance(r, str) and r} if isinstance(readers, list) else set()


@app.get("/api/agent-token/<service>")
def api_agent_token(service):
    """An `agent.v1` provider's action token, read out of its container (identity.agent_token).

    Both factors in EVERY mode (container id AND address), or the operator on loopback: this token
    drives the office's agent, and "warn" serving an unidentified caller would hand that to anyone on
    the network. And THIS office's reader: the office network is shared by every office on one docker
    host, so a dgo-extend of another compose project is refused too. Each answer is in the grant log."""
    ident = broker.caller()
    project = identity.own_project()
    if not _SERVICE_NAME.match(service or ""):
        return jsonify(error="not a service name"), 400
    readers = AGENT_TOKEN_READERS | agent_readers(service)
    allowed = ident.get("method") == "loopback" or (
        ident.get("ok") and ident.get("method") == "container-id+ip"
        and ident.get("service") in readers
        and bool(project) and ident.get("project") == project)
    if not allowed:
        why = (f"only this office's {', '.join(sorted(AGENT_TOKEN_READERS))} or a reader the compiler names for "
               f"{service}, identified by container id and address, reads its token (caller: "
               f"{ident.get('service') or 'unidentified'}, {ident.get('method')}, project {ident.get('project') or '?'})")
        broker.audit("agent-token", "refuse", ident, agent=service, reason=why)
        return jsonify(error=why, decision="refuse"), 403
    token, why = identity.agent_token(service)
    if not token:
        broker.audit("agent-token", "miss", ident, agent=service, reason=why)
        return jsonify(error=why), 404
    broker.audit("agent-token", "allow", ident, agent=service)
    return jsonify(service=service, token=token)


@app.put("/api/instances/<iid>/secret")
def api_instance_secret_put(iid):
    """Service-only, in-network: persist a secret a service just rotated. {secret:{...}, replace?}.

    Why this exists: an OAuth access token is renewed by whichever service hits the wall first, and a
    renewal that lives only in that process's memory is lost on the next container restart — the
    account then breaks for no visible reason. Worse, if Google ever rotates the refresh_token, an
    unshared renewal strands every other consumer holding the dead one. The renewer writes back here
    so the vault stays the single copy everyone reads (§5).

    MERGE by default, because a Google refresh response carries ONLY access_token/expires_in: a blind
    overwrite would drop the refresh_token and silently downgrade a routine renewal into "reconnect
    the account". `replace:true` is the explicit escape hatch for a real re-consent, where the old
    grant's leftovers must NOT survive.

    Never returns the secret: this is the write half: reads have their own endpoint above. Audited
    (unlike the read) — a write is rare and rotation is exactly what the audit trail is for; the
    logged key NAMES tell an operator what moved, the values never leave. Refused when RELAYED.
    """
    refused = _refuse_relayed("instance-secret-put", iid)
    if refused:
        return refused
    b = request.get_json(force=True, silent=True) or {}
    secret, replace = b.get("secret"), bool(b.get("replace"))
    if not isinstance(secret, dict) or not secret:
        return jsonify(error="a non-empty secret{} is required"), 400
    with _vault_lock:                       # see _vault_lock — keep this block read->write only
        store = vault_read()
        rec = _instances(store).get(iid)
        if not rec:
            return jsonify(error="unknown instance"), 404
        # Assign the two fields rather than rec.update(the body): protocol/label/account_hint/
        # created_at are the instance's identity, and a token write must never be able to move them.
        stored = rec.get("secret") or {}
        merged = dict(secret) if replace else {**stored, **secret}
        # a renewal from an older, wider grant (an engine that still held it) never widens a read-only account back;
        # a write that brings ANOTHER refresh token is another grant, so it states its own scope — the record's
        # read-only one would only label it
        refused = secret_readonly_refusal(rec.get("protocol"), merged)
        if not refused and secret.get("refresh_token") and secret.get("refresh_token") != stored.get("refresh_token"):
            refused = secret_readonly_refusal(rec.get("protocol"), secret)
        if refused:
            _audit("instance-secret-refused", iid, protocol=rec.get("protocol"), keys=sorted(secret))   # store untouched
            return jsonify(error=refused, read_only=True), 409
        rec["secret"] = merged
        rec["updated_at"] = int(time.time())
        vault_write(store)
        # Inside the lock: _audit is itself a read-modify-write of the whole store, so from out here
        # it would race the next request's write and could put back a store without this secret.
        _audit("instance-secret-update", iid, replace=replace, keys=sorted(secret))
    return jsonify(ok=True)


# ── OAuth broker: the WHOLE connect flow lives here (nothing on the consumer side) ──
def resolve_value(cid):
    cat, store = catalog(), vault_read()
    prov = cat.get(cid)
    if not prov:
        return None
    _, v = resolve(cid, prov, store)
    return v


def callback_base():
    # public callback the OAuth provider redirects back to (single redirect URI for all connections)
    return os.environ.get("CONNECTIONS_PUBLIC_URL", "https://connections.localhost").rstrip("/")


def authorize_url(prov, as_instance=False, state=None, redirect_uri=None, proto=None):
    o = prov["oauth"]
    client_id = resolve_value(o["client_ref"] + "-id") or resolve_value(o["client_ref"]) \
        or os.environ.get("N8N_GOOGLE_OAUTH_CLIENT_ID", "")
    # `state` is the only channel that survives the round-trip to the provider, so the as_instance
    # choice rides in it (the callback is a bare provider redirect — it carries nothing of ours).
    # A relayed consent (below) brings its own signed state and the relay's address. A protocol start
    # puts the PROTOCOL in it, so the callback mints that protocol's account only.
    params = {"client_id": client_id, "response_type": "code",
              "redirect_uri": redirect_uri or f"{callback_base()}/oauth/callback",
              "scope": " ".join(oauth_scopes(prov, proto)),
              "state": state or ((proto or prov["id"]) + ("|as_instance" if as_instance else ""))}
    params.update(o.get("extra", {}))
    if proto:
        # include_granted_scopes folds every scope this client was EVER granted by the account into the new
        # token: a read-only start would come back with full access after any earlier full grant
        params.pop("include_granted_scopes", None)
    from urllib.parse import urlencode
    return o["authorize_url"] + "?" + urlencode(params), client_id


@app.post("/api/vault/wipe")
def api_vault_wipe():
    """Reset the credential plane: DESTROY everything the vault holds — every user override, every
    OAuth grant/token, every connection INSTANCE, minted machine-secrets, custom connections, and
    the audit log — and fall the whole estate back to its .env defaults.

    This is the "leave no client secret on the host" button. The vault is the ONLY place a value
    that is not in .env can live (resolve() order is db-vault -> .env -> derived), so emptying it is
    exactly "delete all secrets except what .env provides". .env is never touched — it is the
    deployment's declared baseline, not a secret store.

    Destructive and irreversible (OAuth grants must be re-consented, instances re-created). Requires
    an explicit {"confirm": "wipe"} body so a stray call cannot nuke the estate. Leaves ONE fresh
    audit entry recording the wipe itself, so there is a trace of when the plane was reset without
    keeping any of the old material.
    """
    body = request.get_json(silent=True) or {}
    if body.get("confirm") != "wipe":
        return jsonify(ok=False, error="confirmation required",
                       hint='POST {"confirm":"wipe"} — this destroys every stored secret'), 400
    try:
        before = vault_read()
    except VaultUnreadable:
        # the one way back from a lost key: the unreadable file is set aside (never deleted — the key may yet
        # be found) and the plane starts from an empty vault, as this button promises
        aside = f"{VAULT_PATH}.unreadable-{int(time.time())}"
        os.replace(VAULT_PATH, aside)
        before = {}
    reserved = {"__audit__", "__minted__", "__custom__", "instances"}
    counts = {
        "overrides": sum(1 for k in before if k not in reserved),
        "instances": len(before.get("instances") or {}),
        "minted": len(before.get("__minted__") or []),
        "custom": len(before.get("__custom__") or {}),
    }
    # Overwrite with a fresh store carrying only the wipe marker — no old key survives.
    vault_write({"__audit__": [{"t": int(time.time()), "event": "vault-wiped", "id": None,
                                "cleared": counts}]})
    return jsonify(ok=True, wiped=counts,
                   note="all stored secrets cleared; every connection now resolves from .env "
                        "(OAuth grants + instances must be re-created)")


@app.get("/oauth/<cid>/start")
def oauth_start(cid):
    """Begin consent IN connections. ?go=1 issues the real 302 to the provider.
    ?as_instance=1 makes the callback create connection instance(s) instead of injecting into n8n.
    <cid> is a provider or one of its platform protocols (a consent for that protocol alone); ?protocol= is the
    protocol the asking app serves, honoured where this office connects it read-only (_oauth_provider)."""
    prov, proto = _oauth_provider(cid, (request.args.get("protocol") or "").strip())
    if not prov:
        return jsonify(error="not an oauth connection"), 404
    as_instance = request.args.get("as_instance") == "1"

    def said(text, status):     # a browser sent here (?go=1, the console's «חבר») reads a page, never raw JSON
        if request.args.get("go") == "1":
            return Response(f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                            f"<body dir=rtl style='font-family:system-ui,sans-serif;max-width:36em;margin:2em auto;"
                            f"padding:0 1em;line-height:1.6'><p>{html.escape(text)}</p></body>",
                            status=status, mimetype="text/html")
        return jsonify(error=text), status
    if proto and not as_instance:
        # a protocol grant exists only to become that protocol's account — it is never injected into n8n
        return said(f"a consent for {proto} alone connects an account: start it with as_instance=1", 400)
    refused = readonly_refusal(prov, proto)
    if refused:
        return said(refused, 409)
    ret = (request.args.get("ret") or "").strip()
    if ret:
        # a RELAYED consent: an app of this office asks, and the browser comes back to that app (`ret`)
        if not as_instance:
            return jsonify(error="a relayed consent connects an account (as_instance=1) — nothing else comes back this way"), 400
        if len(ret) > 600 or not _ret_allowed(ret):
            return jsonify(error="ret must be an app's own return page (…/oauth/google/return) on this herd's names"), 400
        if not _state_key(prov):
            # no client secret on this office: said as the refusal it is, in the same plain words (DGO-1634) — and
            # told apart from no client at all, whose fix is another (a new client vs. its secret pasted here)
            _url, client_id = authorize_url(prov, as_instance)
            return _refusal_answer("no_secret" if _real_client(client_id) else "no_client",
                                   _relay_base() + "/oauth/relay", client_id)
        # Bound to the BROWSER that asked (DGO-1418): the app keeps a secret in that window's own storage and gives
        # here only its sha256. /oauth/relayed completes the consent only with the secret — so a consent link that
        # somebody else opens and approves comes back to a page that cannot finish it.
        bind = (request.args.get("bind") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", bind):
            return jsonify(error="a relayed consent is bound to the window that asked for it: bind=<sha256 hex of its secret>"), 400
        redirect = _relay_base() + "/oauth/relay"
        nonce = secrets.token_urlsafe(18)
        exp = int(time.time()) + _STATE_TTL
        with _STATES_LOCK:
            for k in [k for k, v in _OAUTH_STATES.items() if v["t"] < time.time()]:
                _OAUTH_STATES.pop(k, None)
            while len(_OAUTH_STATES) >= _STATES_MAX:          # a flood of starts cannot grow it without end
                _OAUTH_STATES.pop(next(iter(_OAUTH_STATES)))
            _OAUTH_STATES[nonce] = {"c": prov["id"], "p": proto or "", "r": ret, "t": exp, "b": bind}
        # the provider's id, never a protocol's, in `c` (open_state finds the provider by it); the protocol in `p`
        state = sign_state(prov, {"c": prov["id"], "p": proto or "", "i": 1 if as_instance else 0, "n": nonce,
                                  "r": ret, "u": redirect, "t": exp})
        url, client_id = authorize_url(prov, as_instance, state=state, redirect_uri=redirect, proto=proto)
        refused = _provider_refusal(url) if _real_client(client_id) else "no_client"
        if refused:
            return _refusal_answer(refused, redirect, client_id)
        return jsonify(id=cid, authorize_url=url, client_id_present=bool(client_id), redirect_uri=redirect,
                       relayed=True, as_instance=as_instance,
                       platform_protocols=[proto] if proto else _platform_protocols(prov),
                       read_only=bool(proto and proto in _readonly_protocols()))
    url, client_id = authorize_url(prov, as_instance, proto=proto)
    # The broker's own consent is asked FIRST too (DGO-1634). The console's «חיבור חשבון חדש» comes here, and it
    # opened Google's English error page in a new window — «פתח חלון הרשאות … לא ברור לי מה זה אומר» on Exampleu,
    # where the office's client was gone at Google. Its return address is this office's own callback, which Google
    # knows only when it was registered on the client, so a live client refuses it as redirect_uri_mismatch: said.
    refused = _provider_refusal(url) if _real_client(client_id) else "no_client"
    if refused:
        said, status = _refusal_answer(refused, f"{callback_base()}/oauth/callback", client_id)
        if request.args.get("go") == "1":       # a browser sent here: a page of the same words, never Google's
            d = said.get_json()
            return Response(f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                            f"<body dir=rtl style='font-family:system-ui,sans-serif;max-width:36em;margin:2em auto;"
                            f"padding:0 1em;line-height:1.6'><p>{html.escape(d['error'])}</p>"
                            f"<p><a href='{html.escape(_REFUSAL_HELP)}' target=_blank rel=noopener>Google Cloud — "
                            f"מזהי התחברות</a></p></body>", status=status, mimetype="text/html")
        return said, status
    if request.args.get("go") == "1":
        return Response(status=302, headers={"Location": url})
    return jsonify(id=cid, authorize_url=url, client_id_present=bool(client_id),
                   redirect_uri=f"{callback_base()}/oauth/callback",
                   as_instance=as_instance, platform_protocols=[proto] if proto else _platform_protocols(prov),
                   read_only=bool(proto and proto in _readonly_protocols()),
                   note="the user is sent here BY connections and returns TO connections — n8n is never visited")


@app.get("/oauth/callback")
def oauth_callback():
    """Provider redirects here. Exchange code -> tokens, store in vault, inject into the consumer
    (default, unchanged) — or, with as_instance in `state`, create connection instance(s) instead."""
    code = request.args.get("code")
    cid, _, flag = (request.args.get("state") or "").partition("|")
    as_instance = flag == "as_instance"
    prov, proto = _oauth_provider(cid)      # this state is not signed: the declaration is checked again here
    if not code or not prov or (proto and not as_instance):
        return Response("<h3>connections: invalid oauth callback</h3>", mimetype="text/html", status=400)
    refused = readonly_refusal(prov, proto)
    if refused:
        return Response(f"<h3>connections: refused</h3><p>{html.escape(refused)}</p>", mimetype="text/html", status=409)
    tok, refused = _exchange(prov, code, f"{callback_base()}/oauth/callback")
    if refused:
        return Response(f"<h3>connections: token exchange {html.escape(refused)}</h3>", mimetype="text/html", status=502)
    refused = readonly_refusal(prov, proto, tok)
    if refused:
        return Response(f"<h3>connections: refused</h3><p>{html.escape(refused)}</p>", mimetype="text/html", status=409)
    if not proto:
        # the provider-wide grant is the provider's value; a protocol grant is narrower (one protocol, maybe
        # read-only) and would pass for the full grant there and in /oauth/<id>/reinject: its one home is its account
        store = vault_read(); store[prov["id"]] = json.dumps(tok); vault_write(store)   # grant now owned by connections
    if as_instance:
        made = instances_from_grant(prov, tok, [proto] if proto else None)
        if not made:
            return Response(f"<h3>connections: {cid} has no platform protocol</h3><p>the grant is vaulted, but "
                            f"the provider declares no platform_protocol(s) — nothing to create an instance of.</p>",
                            mimetype="text/html", status=400)
        return Response(f"<h3>connections: {cid} connected ✓</h3><p>tokens stored in the vault; created "
                        f"{len(made)} connection instance(s): {', '.join(made)}. You can close this tab.</p>",
                        mimetype="text/html")
    injected = inject_into_n8n(prov, tok)
    return Response(f"<h3>connections: {cid} connected ✓</h3><p>tokens stored in the vault; injected into "
                    f"{injected} n8n credential(s). You can close this tab.</p>", mimetype="text/html")


def _exchange(prov, code, redirect_uri):
    """(tokens, None) for a consent code, or (None, the refusal in words). The redirect_uri is the one
    the consent was ASKED with — Google refuses the code under any other."""
    o = prov["oauth"]
    client_id = resolve_value(o["client_ref"] + "-id") or os.environ.get("N8N_GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = resolve_value(o["client_ref"] + "-secret") or os.environ.get("N8N_GOOGLE_OAUTH_CLIENT_SECRET", "")
    body = urllib.parse.urlencode({"code": code, "client_id": client_id, "client_secret": client_secret,
                                   "redirect_uri": redirect_uri, "grant_type": "authorization_code"}).encode()
    try:
        req = urllib.request.Request(o["token_url"], data=body, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        # The provider answered, and its body names the reason (`invalid_grant`,
        # `redirect_uri_mismatch`, `invalid_client`) — "HTTP Error 400: Bad Request" names nothing.
        return None, f"refused ({e.code}): {e.read().decode('utf-8', 'replace')[:400]}"
    except Exception as e:
        return None, f"failed: {e}"


# ── A CONSENT THAT COMES BACK THROUGH THE HERD'S DOOR (DGO-1390) ────────────────────────────────────
# Google returns a person only to an address registered on the OAuth client: https, on a public name.
# An office at home (the HP, a laptop — `*.localhost`) has none, and registering one per office is a
# Google Cloud form per office. So the product registers ONE: `OAUTH_RELAY_URL/oauth/relay`, on the
# herd's public door. The office that starts a consent for one of its apps SIGNS the state (HMAC under the
# OAuth client's secret, which only our offices hold) and names where the browser comes back: `ret`, the
# app's own return page as the browser saw it, through whichever console it was opened in. The relay
# checks the signature and sends the browser there with Google's code — it exchanges nothing and keeps
# nothing. The app hands the code to ITS office's connections (`/oauth/relayed`), which takes it only for
# a nonce it issued itself (so a consent finished on another office — another of our clients — cannot be
# planted here) and only with the secret of the BROWSER that started it (DGO-1418: the app's start keeps a
# secret in that window, connections only its sha256 — a consent link somebody else approves cannot be
# finished), exchanges it, and keeps the account. The grant never reaches the relay's vault.
_STATE_TTL = 15 * 60
_STATES_MAX = 1000
_STATES_LOCK = threading.Lock()
_OAUTH_STATES = {}      # nonce -> {c: provider id, r: ret, t: expiry, b: sha256 of the browser's secret} — once each


def _relay_base():
    """Where Google sends the browser back for a relayed consent: the declared relay, else this office."""
    return (os.environ.get("OAUTH_RELAY_URL") or callback_base()).rstrip("/")


#: The only page a consent comes back to: an app's own return page (drive's, mailview's), at any mount — the
#: console's /a/<alias>[.<office>]/ or the app's own host.
_RETURN_PATH = re.compile(r"^(/[A-Za-z0-9._~%!$&'()*+,;=:@-]+)*/oauth/google/return$")


def _ret_allowed(ret):
    """Is `ret` one of OUR apps' return pages? The relay is public and hands Google's code to the address a state
    names, so that address is held to the herd's own names — `*.localhost` (an office at home, seen through its
    console) and the product's domain (OAUTH_RETURN_DOMAINS), plus this office's own — and to the return path.
    Checked where the state is made (/start) and again where it is used (/oauth/relay)."""
    try:
        u = urllib.parse.urlsplit(str(ret or ""))
        host = (u.hostname or "").lower()
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or not host or u.username or u.password or u.query or u.fragment:
        return False
    domains = [d.strip().lower().lstrip(".") for d in
               (os.environ.get("OAUTH_RETURN_DOMAINS") or "localhost,digital-office.co.il").split(",") if d.strip()]
    own = (urllib.parse.urlsplit(callback_base()).hostname or "").lower().split(".", 1)
    if len(own) == 2 and "." in own[1]:
        domains.append(own[1])                           # connections.<this office's domain> → <domain>
    return any(host == d or host.endswith("." + d) for d in domains) and bool(_RETURN_PATH.match(u.path))


#: What the person is told when the provider would refuse the consent before it starts — said in the window
#: they are in, instead of the provider's English error page after a new one opened. Plain words first (what is
#: missing, and who fixes it), the address to register last (DGO-1634: «יותר ברור מה צריך לעשות»).
_REFUSAL_HE = {
    "no_client": "ההתחברות עם Google עוד לא פתוחה בלשכה הזו: אין לה עדיין מזהה התחברות של Google (OAuth client). "
                 "מי שמנהל את Google Cloud של העסק יוצר אחד, עם כתובת החזרה {uri}",
    "no_secret": "ההתחברות עם Google עוד לא פתוחה בלשכה הזו: יש לה מזהה התחברות (OAuth client), אבל לא את הסוד שלו "
                 "(client secret). מי שמנהל את Google Cloud של העסק מעתיק אותו ממסך המזהה ומוסיף אותו ב«חיבורים ומפתחות»",
    "invalid_client": "ההתחברות עם Google עוד לא פתוחה בלשכה הזו: מזהה ההתחברות שלה (OAuth client) נמחק אצל Google. "
                      "מי שמנהל את Google Cloud של העסק יוצר מזהה חדש, עם כתובת החזרה {uri}",
    "redirect_uri_mismatch": "ההתחברות עם Google עוד לא פתוחה בלשכה הזו: Google לא מכיר את כתובת החזרה שלה. "
                             "מי שמנהל את Google Cloud של העסק מוסיף אותה למזהה ההתחברות: {uri}",
    "disabled_client": "ההתחברות עם Google עוד לא פתוחה בלשכה הזו: מזהה ההתחברות שלה הושבת ב־Google Cloud",
    "*": "Google מסרב לפתוח את ההתחברות עם המזהה שמוגדר בלשכה",
}
#: Where that is done: Google Cloud's credentials page, where an OAuth client is created and its return addresses
#: are listed («שיהיה פה קישור לזה»). Every refusal answer carries it; the screens show it as a link.
_REFUSAL_HELP = "https://console.cloud.google.com/apis/credentials"


def _refusal_answer(refused, redirect, client_id):
    """The 409 a consent that the provider would refuse gets, from either start: the sentence, what Google said,
    the address to register, and where to do it."""
    return jsonify(error=_REFUSAL_HE.get(refused, _REFUSAL_HE["*"]).format(uri=redirect), provider_error=refused,
                   redirect_uri=redirect, client_id_present=_real_client(client_id), help_url=_REFUSAL_HELP), 409


#: A Google OAuth client id has a shape of its own: one in it is real whatever its random part spells (`xxx`, `todo`
#: are placeholder markers anywhere else).
_GOOGLE_CLIENT_ID = re.compile(r"\d+-[0-9a-z]+\.apps\.googleusercontent\.com")


def _real_client(client_id):
    """Is an OAuth client configured at all — not absent, not a template's placeholder?"""
    v = str(client_id or "").strip()
    return bool(v) and (bool(_GOOGLE_CLIENT_ID.fullmatch(v)) or not _is_placeholder(v))


def _provider_refusal(url):
    """The provider's refusal of this consent request ("invalid_client", "redirect_uri_mismatch", …), or "".
    Google refuses a dead client or an unregistered address BEFORE anyone signs in — by redirecting the
    first request to its error page — so asking it costs one request and no person. Measured 2026-11-05:
    every office's client answered `invalid_client: The OAuth client was not found`."""
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    key = ((q.get("client_id") or [""])[0], (q.get("redirect_uri") or [""])[0])
    hit = _REFUSALS.get(key)
    if hit and hit[0] > time.time():             # one question a minute per client and address, not one per start
        return hit[1]

    class _Stop(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    try:
        r = urllib.request.build_opener(_Stop).open(
            urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (DGO connections)"}), timeout=8)
        loc = r.headers.get("Location") or ""
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location") or ""
    except Exception:
        # the provider cannot be asked from here: the person sees its own answer — and the next start for a minute
        # does not wait the whole timeout again (every start of the broker's own asks now too, DGO-1634)
        _REFUSALS[key] = (time.time() + 60, "")
        return ""
    said = ""
    if "/oauth/error" in loc:
        err = (urllib.parse.parse_qs(urllib.parse.urlsplit(loc).query).get("authError") or [""])[0]
        try:
            raw = base64.urlsafe_b64decode(err + "=" * (-len(err) % 4))
        except Exception:
            raw = b""
        m = re.search(rb"(invalid_client|redirect_uri_mismatch|disabled_client|invalid_request|access_denied)", raw)
        said = m.group(1).decode() if m else "error"
    _REFUSALS[key] = (time.time() + 60, said)
    return said


_REFUSALS = {}          # (client id, return address) -> (until, the provider's answer) — _provider_refusal


def _state_key(prov):
    o = prov.get("oauth") or {}
    sec = resolve_value(o.get("client_ref", "") + "-secret") or os.environ.get("N8N_GOOGLE_OAUTH_CLIENT_SECRET", "")
    return hashlib.sha256(b"dgo-oauth-relay\x1f" + sec.encode()).digest() if sec and not _is_placeholder(sec) else b""


def _b64u(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def sign_state(prov, payload):
    body = _b64u(json.dumps(payload, separators=(",", ":")).encode())
    return "r1." + body + "." + _b64u(hmac.new(_state_key(prov), body.encode(), hashlib.sha256).digest())


def open_state(state):
    """(payload, provider, "") for a state one of our offices signed and that has not expired, else
    (None, None, why)."""
    parts = str(state or "").split(".")
    if len(parts) != 3 or parts[0] != "r1":
        return None, None, "not a relayed consent"
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except Exception:
        return None, None, "an unreadable state"
    prov = catalog().get(str(payload.get("c") or "")) if isinstance(payload, dict) else None
    if not prov or "oauth" not in prov:
        return None, None, "an unknown provider"
    key = _state_key(prov)
    want = _b64u(hmac.new(key, parts[1].encode(), hashlib.sha256).digest()) if key else ""
    if not key or not hmac.compare_digest(want, parts[2]):
        return None, None, "a state no office of ours signed"
    if time.time() > float(payload.get("t") or 0):
        return None, None, "a consent older than 15 minutes"
    if not re.match(r"^https?://[^\s/]+/", str(payload.get("r") or "")):
        return None, None, "no address to return to"
    return payload, prov, ""


@app.get("/oauth/relay")
def oauth_relay():
    """Google's ONE return address for the whole herd. Served without the office's sign-in (the person
    returning from Google may be a client's, with no account on this office), so it does one thing: a
    state one of our offices signed → 302 to the return page that state names, with Google's answer.
    It never exchanges a code and never writes the vault."""
    payload, _prov, why = open_state(request.args.get("state"))
    if payload and not _ret_allowed(payload.get("r")):
        payload, why = None, "a return address that is not one of our apps' return pages"
    if not payload:
        return Response(f"<!doctype html><meta charset=utf-8><h3>החיבור לא הושלם</h3><p>{html.escape(why)}</p>",
                        mimetype="text/html", status=400)
    back = {k: request.args[k] for k in ("code", "state", "error") if request.args.get(k)}
    ret = payload["r"]
    return Response(status=302, headers={"Location": ret + ("&" if "?" in ret else "?") + urllib.parse.urlencode(back),
                                         "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


def _upsert_grant_instances(prov, tok, protocols=None):
    """One instance per platform protocol the grant covers (one Google consent is Drive AND Gmail; `protocols`
    narrows it to a protocol consent's own). An account connected again is the SAME instance with a fresh token,
    never a second row."""
    hint = _grant_account_hint(prov, tok)
    made = []
    for proto in (protocols or _platform_protocols(prov)):
        # the whole read-modify-write, its audit line included, under the vault's lock (api_instance_secret_put
        # says why: an audit written from outside it can put back a store without this token)
        with _vault_lock:
            store = vault_read()
            same = next((iid for iid, rec in _instances(store).items()
                         if rec.get("protocol") == proto and rec.get("account_hint") == hint and hint != prov.get("id")), None)
            if same:
                rec = store[_INSTANCES][same]
                rec["secret"], rec["status"], rec["updated_at"] = dict(tok), "ok", int(time.time())
                vault_write(store)
                _audit("instance-secret-update", same, replace=True, keys=sorted(tok))
                made.append({"id": same, "protocol": proto, "account_hint": hint, "again": True})
            else:
                made.append({"id": create_instance(proto, f"{hint} ({proto.split('_')[0]})", dict(tok), hint),
                             "protocol": proto, "account_hint": hint, "again": False})
    return made


@app.post("/oauth/relayed")
def oauth_relayed():
    """An app of THIS office hands over the code its return page received: {code, state, bind} (or {error,
    state, bind}). Only for a consent this office started (its nonce, once), only with the secret of the
    browser that started it (`bind`, DGO-1418), and only from this office's own services — a request relayed
    through the edge, the console or a link is refused."""
    if _relayed():
        return jsonify(ok=False, error="a consent is completed by this office's own app, not through a relay"), 403
    b = request.get_json(force=True, silent=True)
    if not isinstance(b, dict):
        return jsonify(ok=False, error="the body is a JSON object: {code, state, bind}"), 400
    payload, prov, why = open_state(b.get("state"))
    if not payload:
        return jsonify(ok=False, error=why), 400
    with _STATES_LOCK:
        mine = _OAUTH_STATES.pop(str(payload.get("n") or ""), None)
    if not mine or mine["r"] != payload.get("r") or mine["c"] != payload.get("c") \
            or mine.get("p", "") != str(payload.get("p") or ""):
        return jsonify(ok=False, error="this consent was not started on this office, or it was already used"), 409
    proto = str(payload.get("p") or "") or None
    if proto and proto not in _platform_protocols(prov):
        return jsonify(ok=False, error=f"{proto} is not a protocol of {prov['id']}"), 400
    refused = readonly_refusal(prov, proto)      # the declaration as it is NOW, not when the consent started
    if refused:
        return jsonify(ok=False, error=refused), 409
    secret = str(b.get("bind") or "")
    if not mine.get("b") or not secret or len(secret) > 200 or not hmac.compare_digest(
            hashlib.sha256(secret.encode("utf-8", "replace")).hexdigest(), mine["b"]):
        return jsonify(ok=False, error="this consent was started in another browser — connect the account from the "
                                       "window that asked for it"), 403
    if b.get("error"):
        return jsonify(ok=False, error=f"Google: {b['error']}"), 400
    if not b.get("code"):
        return jsonify(ok=False, error="no code came back from Google"), 400
    if not payload.get("i"):                     # before the exchange: a code is spent once, and never for nothing
        return jsonify(ok=False, error="only an account consent (as_instance) is completed this way"), 400
    tok, refused = _exchange(prov, b["code"], payload["u"])
    if refused:
        return jsonify(ok=False, error=f"Google: the code was {refused}"), 502
    refused = readonly_refusal(prov, proto, tok)
    if refused:
        return jsonify(ok=False, error=refused), 409
    made = _upsert_grant_instances(prov, tok, [proto] if proto else None)
    return jsonify(ok=True, made=made, account_hint=(made[0]["account_hint"] if made else None),
                   read_only=bool(proto and proto in _readonly_protocols()))


def _grant_account_hint(prov, tok):
    """Display-only hint. An OpenID provider returns an id_token JWT carrying the email; read its
    payload WITHOUT signature verification — this token came straight back from the token endpoint
    over TLS, is never trusted for authz, and a wrong hint is a cosmetic bug, not a breach.
    Falls back to the provider id when the grant carries no id_token (scopes without openid)."""
    raw = (tok or {}).get("id_token")
    if raw:
        try:
            payload = raw.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode())
            if claims.get("email"):
                return claims["email"]
        except Exception:
            pass
    return prov.get("id")


def instances_from_grant(prov, tok, protocols=None):
    """One instance per platform protocol the grant covers, each holding the same token dict — the
    single Google consent authorises Drive AND Gmail, and each platform service looks its own
    protocol up independently. `protocols` narrows it to a protocol consent's own."""
    hint = _grant_account_hint(prov, tok)
    return [create_instance(proto, f"{hint} ({proto.split('_')[0]})", dict(tok), hint)
            for proto in (protocols or _platform_protocols(prov))]


def inject_into_n8n(prov, tok):
    """Push the grant into n8n's Google credentials via its REST API (owner login).
    This is what replaces the manual 'open n8n and click Connect' — connections does it."""
    inj = prov["oauth"].get("inject", {})
    if inj.get("target") != "n8n":
        return 0
    base = os.environ.get("N8N_INTERNAL_URL") or "http://n8n:5678"   # empty-string env must fall back
    email = os.environ.get("N8N_OWNER_EMAIL", ""); pw = os.environ.get("N8N_OWNER_PASSWORD", "")
    op = urllib.request.build_opener()
    try:
        r = op.open(urllib.request.Request(base + "/rest/login", method="POST",
                    data=json.dumps({"emailOrLdapLoginId": email, "password": pw}).encode(),
                    headers={"Content-Type": "application/json"}), timeout=10)
        # Carry the auth cookie by hand. With N8N_SECURE_COOKIE=true (right for a browser on an
        # https deployment) n8n marks the cookie Secure, so a CookieJar correctly REFUSES to send
        # it back over this internal http://n8n:5678 call — login 200s, then every credential
        # request 401s and the grant silently injects into 0 credentials. CI never hit this
        # because CI runs N8N_SECURE_COOKIE=false.
        cookie = "; ".join(c.split(";", 1)[0] for c in (r.headers.get_all("Set-Cookie") or []))
    except Exception:
        return 0
    if not cookie:
        return 0
    hdrs = {"Content-Type": "application/json", "Cookie": cookie}
    n = 0
    for cred_id in inj.get("credential_ids", []):
        try:
            # n8n PATCH validates name+type; fetch them, then set only the token data
            g = op.open(urllib.request.Request(base + f"/rest/credentials/{cred_id}", headers=hdrs), timeout=10)
            meta = json.load(g).get("data", {})
            payload = {"name": meta.get("name"), "type": meta.get("type"),
                       "data": {"oauthTokenData": tok}}
            op.open(urllib.request.Request(base + f"/rest/credentials/{cred_id}", method="PATCH",
                    data=json.dumps(payload).encode(), headers=hdrs), timeout=10)
            n += 1
        except Exception:
            pass
    return n


@app.get("/oauth/<cid>/reinject")
def oauth_reinject(cid):
    """Re-push an already-vaulted grant into the consumer (repair path — no re-consent)."""
    prov = catalog().get(cid or "")
    if not prov or "oauth" not in prov:
        return jsonify(error="not an oauth connection"), 404
    refused = readonly_refusal(prov, None)      # a provider-wide grant kept from before a read-only declaration
    if refused:
        return jsonify(error=refused), 409
    store = vault_read(); raw = store.get(cid)
    if not raw:
        return jsonify(error="no vaulted grant for this connection"), 404
    tok = json.loads(raw)
    injected = inject_into_n8n(prov, tok)
    return jsonify(id=cid, injected=injected)


# ── the broker surface (identity-authenticated, manifest-checked, fully logged) ──
# Registered last so every dependency it is handed (service_requires, export_env) is defined. The
# dependencies are passed IN rather than imported by broker.py, so the vault/catalog/resolve chain
# stays owned by this file and the import graph stays one-way.
# …and every value the broker hands out (a lease, a token's redeem) is asked with THIS request's caller, so a
# `reveal_to` secret reaches only a verified caller it names, by every path (DGO-1825)
broker.register(app, declared_for=service_requires,
                export_env=lambda service, only=None: export_env(service, only, caller=broker.caller(), req=request))


PAGE = open(os.path.join(ROOT, "ui.html")).read() if os.path.exists(os.path.join(ROOT, "ui.html")) else ""


@app.get("/")
def index():
    return Response(PAGE, mimetype="text/html")


if __name__ == "__main__":
    app.run("0.0.0.0", int(os.environ.get("PORT", 8990)))
