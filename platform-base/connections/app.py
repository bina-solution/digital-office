"""connections — the single credential plane for deployment-hacohen.

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
import base64, glob, hashlib, html, json, os, secrets, socket, string, tempfile, threading, time, urllib.parse, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

import yaml
from cryptography.fernet import Fernet
from flask import Flask, jsonify, request, Response

import broker
import identity

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
def _fernet():
    root = os.environ.get("CONNECTIONS_ROOT_KEY", "dev-root-key-not-for-production")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(root.encode()).digest()))


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
    if not os.path.exists(VAULT_PATH):
        return {}
    try:
        return _apply_renames(json.loads(_fernet().decrypt(open(VAULT_PATH, "rb").read()).decode()))
    except Exception:
        return {}


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
_AUTH_KINDS = {"oauth-client", "oauth-grant", "qr-session", "sa-key", "cert", "app-password"}
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
                  "sa-key": "service-account", "cert": "certificate", "app-password": "basic-auth"}


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


# ── multi-field credentials: a credential is its primary env + envs_extra companions.
# The operator edits ALL of them here (n8n = email + password + names), never .env. ──
_FIELD_LABELS = [("USERNAME", "שם משתמש"), ("_USER", "שם משתמש"), ("EMAIL", "אימייל"),
                 ("PASSWORD", "סיסמה"), ("_PASS", "סיסמה"), ("_PW", "סיסמה"),
                 ("FIRSTNAME", "שם פרטי"), ("LASTNAME", "שם משפחה"), ("_NAME", "שם"),
                 ("API_TOKEN", "טוקן API"), ("_TOKEN", "טוקן"), ("APIKEY", "מפתח API"),
                 ("API_KEY", "מפתח API"), ("_KEY", "מפתח"), ("SECRET", "סוד"),
                 ("_URL", "כתובת"), ("_HOST", "מארח"), ("_PORT", "פורט"),
                 ("_EMAIL", "אימייל"), ("_ID", "מזהה"), ("_IPS", "כתובות IP"), ("_DSN", "DSN")]
_SECRET_HINT = ("PASSWORD", "_PASS", "_PW", "TOKEN", "SECRET", "_KEY", "APIKEY", "DSN")


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


def _cred_fields(cid, prov, store):
    """Every editable field of a credential: primary (prov.env) + envs_extra companions.
    Secret fields are masked + reveal-gated; non-secret fields (user/email/name) show clear."""
    out = []
    primary = prov.get("env")
    if primary:
        src, val = resolve(cid, prov, store)
        sec = _primary_is_secret(prov)
        out.append({"key": primary, "label": _field_label(primary), "primary": True,
                    "secret": sec, "source": src,
                    "masked": mask(val) if sec else val,
                    "clear": (None if sec else val),
                    "derived": str(val or "").startswith("derived:")})
    for k in prov.get("envs_extra", []) or []:
        dbv = store.get(f"{cid}:{k}")
        if dbv is not None:
            src, val = "db", dbv
        elif os.environ.get(k):
            src, val = "env", os.environ[k]
        else:
            src, val = "unset", None
        sec = _field_is_secret(k)
        out.append({"key": k, "label": _field_label(k), "primary": False,
                    "secret": sec, "source": src,
                    "masked": mask(val) if sec else val,
                    "clear": (None if sec else val), "derived": False})
    return out


def _field_store_key(cid, prov, field):
    """DB vault key for a field: the primary env stores at <cid>, companions at <cid>:<KEY>."""
    if not field or field == (prov or {}).get("env"):
        return cid
    return f"{cid}:{field}"


# ── audit log (append-only, in the vault): reveal/edit/rotate/connect/revoke ──
def _audit(event, cid, **extra):
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
            "protocol": _protocol(prov, pillar), "app": _resolve_app(prov),
            "title": prov.get("title", cid), "title_he": prov.get("title_he"),
            "kind": prov.get("kind"), "source": source, "masked": mask(value),
            "secret": secret, "clear": (None if (secret or is_derived) else value),
            "fields_count": (1 if prov.get("env") else 0) + n_extra,
            "reveal_ok": prov.get("reveal_ok", True) and not is_derived,
            "rotatable": ("automint" in prov) or bool(prov.get("rotate")),
            "impact": prov.get("impact") or cons, "rotate_warn": prov.get("rotate_warn"),
            "status": state, "detail": detail, "required": required, "optional": bool(prov.get("optional")),
            "env": prov.get("env"), "consumers": cons, "now": prov.get("now", "").strip()}


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
    return jsonify(ok=True, providers=len(catalog()),
                   broker={"mode": broker.MODE, "docker": identity.docker_available()})


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
    return jsonify(id=cid, source=source, masked=mask(value), resolved=bool(value))


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
    field = (request.get_json(silent=True) or {}).get("field")
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
    prov = catalog().get(cid) or {}
    key = _field_store_key(cid, prov, field)
    store = vault_read(); store[key] = v; vault_write(store)
    _audit("edit", cid, **({"field": field} if field else {}))
    return jsonify(ok=True, id=cid, field=field, source="db", masked=mask(v))


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
    return jsonify(ok=True, id=cid, field=field, reverted_to="env")


@app.post("/api/add")
def api_add():
    """Add a brand-new secret not in the git catalog (stored + registered as Custom)."""
    b = request.get_json(force=True) or {}
    cid, v = b.get("id"), b.get("value")
    if not cid or not v:
        return jsonify(error="id and value required"), 400
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
        if not env_key:
            continue
        _, val = resolve(cid, prov, store)
        if val and not str(val).startswith("derived:"):
            out[env_key] = val
    if request.args.get("format") == "env":
        return Response("".join(f"{k}={v}\n" for k, v in sorted(out.items())), mimetype="text/plain")
    return jsonify(count=len(out), keys=sorted(out.keys()))


def export_env(service, only=None):
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
        if not prov:
            continue
        prod = {}                                   # what this ONE connection produces (env -> value)
        _, val = resolve(r["id"], prov, store)
        if val and prov.get("env"):
            prod[prov["env"]] = val
        # companion keys (e.g. LOCALMAIL_PW, GMAIL_IMAP_USER): DB override "<id>:<KEY>" wins, else .env
        for k in prov.get("envs_extra", []) or []:
            v = store.get(f"{r['id']}:{k}") or os.environ.get(k)
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
    out = export_env(service)
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


@app.get("/api/instances/<iid>/secret")
def api_instance_secret(iid):
    """Service-only, in-network: platform services fetch the live secret here at op time, so
    credentials live in exactly one place.

    Deliberately kept OUT of the vault's `_audit` trail (it fires on every drive op and would drown
    the reveal/edit history), but it IS written to the broker grant log with the caller's identity —
    a secret leaving the plane with no record of who took it is exactly what the grant log exists to
    end. ⚠ Not yet POLICY-gated: connection instances are per-account OAuth grants with no manifest
    declaration to check against, and `drive` reads them live today. See README residual risks."""
    rec = _instances(vault_read()).get(iid)
    if not rec:
        return jsonify(error="unknown instance"), 404
    broker.audit("instance-secret", "allow", broker.caller(), instance=iid,
                 protocol=rec.get("protocol"), gated=False)
    return jsonify(protocol=rec.get("protocol"), secret=rec.get("secret") or {})


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
    logged key NAMES tell an operator what moved, the values never leave.
    """
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
        rec["secret"] = dict(secret) if replace else {**(rec.get("secret") or {}), **secret}
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


def authorize_url(prov, as_instance=False):
    o = prov["oauth"]
    client_id = resolve_value(o["client_ref"] + "-id") or resolve_value(o["client_ref"]) \
        or os.environ.get("N8N_GOOGLE_OAUTH_CLIENT_ID", "")
    # `state` is the only channel that survives the round-trip to the provider, so the as_instance
    # choice rides in it (the callback is a bare provider redirect — it carries nothing of ours).
    params = {"client_id": client_id, "response_type": "code",
              "redirect_uri": f"{callback_base()}/oauth/callback",
              "scope": " ".join(o["scopes"]),
              "state": prov["id"] + ("|as_instance" if as_instance else "")}
    params.update(o.get("extra", {}))
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
    before = vault_read()
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
    ?as_instance=1 makes the callback create connection instance(s) instead of injecting into n8n."""
    prov = catalog().get(cid)
    if not prov or "oauth" not in prov:
        return jsonify(error="not an oauth connection"), 404
    as_instance = request.args.get("as_instance") == "1"
    url, client_id = authorize_url(prov, as_instance)
    if request.args.get("go") == "1":
        return Response(status=302, headers={"Location": url})
    return jsonify(id=cid, authorize_url=url, client_id_present=bool(client_id),
                   redirect_uri=f"{callback_base()}/oauth/callback",
                   as_instance=as_instance, platform_protocols=_platform_protocols(prov),
                   note="the user is sent here BY connections and returns TO connections — n8n is never visited")


@app.get("/oauth/callback")
def oauth_callback():
    """Provider redirects here. Exchange code -> tokens, store in vault, inject into the consumer
    (default, unchanged) — or, with as_instance in `state`, create connection instance(s) instead."""
    code = request.args.get("code")
    cid, _, flag = (request.args.get("state") or "").partition("|")
    as_instance = flag == "as_instance"
    prov = catalog().get(cid or "")
    if not code or not prov or "oauth" not in prov:
        return Response("<h3>connections: invalid oauth callback</h3>", mimetype="text/html", status=400)
    o = prov["oauth"]
    client_id = resolve_value(o["client_ref"] + "-id") or os.environ.get("N8N_GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = resolve_value(o["client_ref"] + "-secret") or os.environ.get("N8N_GOOGLE_OAUTH_CLIENT_SECRET", "")
    from urllib.parse import urlencode
    body = urlencode({"code": code, "client_id": client_id, "client_secret": client_secret,
                      "redirect_uri": f"{callback_base()}/oauth/callback",
                      "grant_type": "authorization_code"}).encode()
    try:
        req = urllib.request.Request(o["token_url"], data=body, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            tok = json.load(r)
    except urllib.error.HTTPError as e:
        # The provider answered, and its body names the reason (`invalid_grant`,
        # `redirect_uri_mismatch`, `invalid_client`) — "HTTP Error 400: Bad Request" names nothing.
        said = html.escape(e.read().decode("utf-8", "replace")[:400])
        return Response(f"<h3>connections: token exchange refused ({e.code})</h3><pre>{said}</pre>",
                        mimetype="text/html", status=502)
    except Exception as e:
        return Response(f"<h3>connections: token exchange failed: {html.escape(str(e))}</h3>",
                        mimetype="text/html", status=502)
    store = vault_read(); store[cid] = json.dumps(tok); vault_write(store)   # grant now owned by connections
    if as_instance:
        made = instances_from_grant(prov, tok)
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


def instances_from_grant(prov, tok):
    """One instance per platform protocol the grant covers, each holding the same token dict — the
    single Google consent authorises Drive AND Gmail, and each platform service looks its own
    protocol up independently."""
    hint = _grant_account_hint(prov, tok)
    return [create_instance(proto, f"{hint} ({proto.split('_')[0]})", dict(tok), hint)
            for proto in _platform_protocols(prov)]


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
broker.register(app, declared_for=service_requires, export_env=export_env)


PAGE = open(os.path.join(ROOT, "ui.html")).read() if os.path.exists(os.path.join(ROOT, "ui.html")) else ""


@app.get("/")
def index():
    return Response(PAGE, mimetype="text/html")


if __name__ == "__main__":
    app.run("0.0.0.0", int(os.environ.get("PORT", 8990)))
