"""console — the unified business-system shell (המרכז).

One RTL Hebrew webapp, my-docs/מסמכים שלי-styled, that federates every surface of the deployment into a
single portal: דרייב, מייל, צ׳אט, incoming-documents, מסמכים שלי, any-concurrency, alerts, machine,
apps, validation, and the settings/connections + install screen. It reuses the existing Authentik
SSO (reads X-authentik-* like my-docs) and proxies the connections credential plane so the install
wizard + connections view work inside the shell.
"""
import functools
import hashlib
import json
import os
import re
import time
from urllib.parse import urljoin, urlparse, urlunparse

import requests
import yaml
from flask import Flask, request, Response, jsonify, send_from_directory
from flask_compress import Compress

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
CONNECTIONS_URL = os.getenv("CONNECTIONS_URL", "http://connections:8990")
# APITOOLS_URL lived here for the /api/business proxy — the old install screen's business-identity
# step. Both are gone (core-003): the shell no longer dials the ledger at all.
_AUTH = ("X-authentik-username", "X-authentik-email", "X-authentik-name", "X-authentik-groups")
# content-encoding: `requests` auto-decompresses the body, so forwarding the app's original
# Content-Encoding (gzip/br) makes the browser try to decode already-plain bytes ->
# ERR_CONTENT_DECODING_FAILED (blank embed). content-length is recomputed by Flask.
_HOP = {"content-length", "content-encoding", "connection", "keep-alive", "transfer-encoding", "host"}
# How long one proxied event-stream may hold a worker thread (see _bounded_stream).
STREAM_MAX_S = float(os.getenv("CONSOLE_STREAM_MAX_S", "55"))
STREAM_IDLE_S = float(os.getenv("CONSOLE_STREAM_IDLE_S", "45"))

# ── Sentry/GlitchTip error reporting (platform standard) ──────────────────────────
# Wired declaratively: glitchtip-push mints this service's project + deterministic DSN into
# CONSOLE_SENTRY_DSN in .env; compose maps it to SENTRY_DSN. No-op if unset.
_SENTRY_DSN = os.getenv("SENTRY_DSN")
if _SENTRY_DSN:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            environment=os.getenv("SENTRY_ENVIRONMENT", os.getenv("DEPLOYMENT_NAME", "production")),
            release=os.getenv("SENTRY_RELEASE"),
            traces_sample_rate=0.0,
            send_default_pii=False,
        )
    except Exception:  # never let telemetry break the app
        pass

app = Flask(__name__, static_folder=None)

# ── compression (Fix 3) ────────────────────────────────────────────────────────
# Nothing was ever gzip/br compressed: the main JS chunk transferred 524,805 raw bytes where gzip
# gets it to ~166KB. flask-compress hooks Flask's after_request and covers every response this
# process emits — the shell's own static assets AND everything app_proxy()/`_proxy()` hand back,
# since both return plain flask.Response objects with no Content-Encoding of their own (_HOP
# already strips the upstream's, see the comment above it).
#
# SSE is NOT at risk from this: flask-compress only touches a response whose `mimetype` is in
# COMPRESS_MIMETYPES, and text/event-stream was never on that default list (nor added here) — so
# the `Response(r.iter_content(...), direct_passthrough=True)` streaming path for
# "text/event-stream" in app_proxy() is skipped outright, before flask-compress even looks at
# COMPRESS_STREAMS. Verified against the installed flask_compress source, not assumed.
Compress(app)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/me")
def me():
    u = {k.replace("X-authentik-", ""): request.headers.get(k) for k in _AUTH}
    return jsonify(user=u.get("username") or "אורח", email=u.get("email"),
                   name=u.get("name") or u.get("username") or "אורח",
                   groups=(u.get("groups") or "").split("|") if u.get("groups") else [])



# ── compiled registries ───────────────────────────────────────────────────────
# The console is a layer-2 base app: it must not author the list of layer-3 apps it shows.
# Each app declares its own tile (routing[].module) and reconcile.py compiles them into
# .generated/registry/, mounted here read-only. modules.yaml stays as the fallback for the
# console's OWN built-in views — today just the install screen, which belongs to no other app.
GENERATED = os.getenv("GENERATED_REGISTRY", "/app/generated")
# A peer registry: one file per app that runs on ANOTHER office and is shown here anyway. Written by
# the app that declares the placement (apps/dgo-extend, which mounts this directory read-only — see its
# `contributes.volumes`), never by the console and never by the compiler: an app placed remotely is
# disabled at home, so the compiler legitimately has no tile for it. Merged below, with the compiled
# registry winning on any alias both would describe.
PEERS_DIR = os.getenv("CONSOLE_PEERS_DIR", "/app/peers.d")


def _peer_entries():
    """Every published remote placement, oldest name first. A malformed or half-written file is
    skipped rather than allowed to empty the rail."""
    out = []
    try:
        names = sorted(os.listdir(PEERS_DIR))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(PEERS_DIR, n), encoding="utf-8") as f:
                doc = json.load(f) or {}
        except (OSError, ValueError):
            continue
        if doc.get("alias") and doc.get("module"):
            out.append(doc)
    return out


def _peer_module(entry):
    """ONE peer registry entry as a module tile — the tile AND the `remote` block it is marked by.

    The mark is `remote` on the module (`apps/dgo-extend/peers.py` writes the tile, and the tile's
    own record carries the office), and the shell reads exactly those fields: `remoteInfo()` in
    `static/app.js` returns None for any module without a `remote` object, so a peer tile that
    arrives here WITHOUT it renders as a plain local tile — the app looks installed on this machine,
    with no corner mark, no office name and no `<office> לא זמינה כרגע`. That is the one thing the
    placement feature exists to say, so the block is rebuilt here from the record's own fields rather
    than assumed to be inside `module`.

    `embed` is what the shell frames (`/a/<alias>/`, the door this app serves) and is left exactly as
    the writer wrote it: this function adds no routing of its own.
    """
    m = dict(entry.get("module") or {})
    if isinstance(m.get("remote"), dict):
        return m                                  # already marked (a hand written or older record)
    lab = entry.get("label")
    m["remote"] = {
        "office": entry.get("office") or "",
        "label": lab if lab is not None else (entry.get("office") or ""),
        "link": entry.get("link") or entry.get("office") or "",
        "address": entry.get("address") or "",
        "commit": entry.get("commit") or "",
    }
    return m


# ── is the office behind a tile answering ────────────────────────────────────────────────────
# A tile of a linked office is drawn by this office and served by that one, so "the app is there"
# and "the app can be reached" are two facts. The second is MEASURED by the app that owns the link
# (`apps/dgo-extend`: `_verdict` → `peers.publish_link`, after every projection pass) and read here
# — one file, `{at, offices: {<id>: {ok, hop, why}}}`. `why` is the fallen hop as a sentence, in the
# link's own words: this shell shows it on the tile (`remote.why`, before anything is opened) and on
# the card a dead office gets instead of a frame, and holds no vocabulary about links itself.
def _link_verdicts():
    """`{office: {ok, hop, why}}` as last measured — or nothing: no link app here, a half-written file, or
    one nobody has rewritten for five minutes (it is written every minute; older is not a measurement
    and must not go on marking an office that may have been back for an hour)."""
    try:
        with open(os.path.join(PEERS_DIR, "link.json"), encoding="utf-8") as f:
            doc = json.load(f)
        return (doc.get("offices") or {}) if time.time() - float(doc["at"]) < 300 else {}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def _judged(tiles):
    """The tiles, each linked-office one carrying what was measured about ITS office: `remote.ok`,
    and `remote.why` when it is not. Unmeasured stays absent — the shell marks `false`, never a guess.
    No time goes on the tile: it is part of what a page compares itself with (`/api/version`), and a
    verdict that has not changed must not look like a registry that has."""
    seen = _link_verdicts()
    for m in tiles:
        r = m.get("remote")
        v = seen.get(str(r.get("office") or "")) if isinstance(r, dict) else None
        if v and v.get("ok") is not None:
            m["remote"] = {**r, "ok": bool(v["ok"]), **({} if v["ok"] else {"why": str(v.get("why") or "")})}
    return tiles


def _peers_stamp():
    """A change key for the peer directory: the newest mtime of the files in it."""
    try:
        return max((os.stat(os.path.join(PEERS_DIR, n)).st_mtime
                    for n in os.listdir(PEERS_DIR) if n.endswith(".json")), default=0.0)
    except OSError:
        return 0.0


def _own_views():
    """The console's built-in, non-embedded views — it legitimately owns these."""
    try:
        return [m for m in (yaml.safe_load(open(os.path.join(ROOT, "modules.yaml"))) or [])
                if not m.get("embed")]
    except OSError:
        return []


def _modules():
    peers = [_peer_module(e) for e in _peer_entries()]
    gen = os.path.join(GENERATED, "console.modules.yaml")
    if os.path.exists(gen):
        tiles = yaml.safe_load(open(gen, encoding="utf-8")) or []
        # Suppression is by ID ONLY. It used to also be by `embed`, and that single word deleted the
        # one case the whole feature exists for: a remote tile's `embed` is its DOOR on this office
        # (`/a/<alias>/`, served by dgo-extend), so it is identical to a local app of the same alias
        # even though the two are different apps on different machines. An app placed on a linked
        # office while it is ALSO installed here therefore rendered as one local tile, with no office
        # name and no corner mark — "an app installed in both offices appears twice, once with the
        # remote mark" was unreachable, and silently. The id is `<alias>.<office>` (unique by
        # construction, see serve.module_entries), so comparing ids alone cannot collide.
        known = {t.get("id") for t in tiles}
        remote = [m for m in peers if m.get("id") not in known]
        # merge by the authored `order` so the shell's own views keep their positions
        return sorted(_judged(tiles + remote) + _own_views(), key=lambda m: m.get("order", 999))
    return yaml.safe_load(open(os.path.join(ROOT, "modules.yaml"))) or []


def _tiles():
    # `door` is how THIS server reaches a remote app (an internal address and the identity mapping of
    # the link); the browser needs the tile, not the route.
    return [{k: v for k, v in m.items() if k != "door"} for m in _modules()]


def _digest(*chunks):
    h = hashlib.sha256()
    for chunk in chunks:
        h.update(chunk)
    return h.hexdigest()[:12]


def _shell_build():
    """One digest of every file the shell is made of. Taken once: they change only with the image."""
    parts = []
    for base, _dirs, files in sorted(os.walk(STATIC)):
        for name in sorted(files):
            path = os.path.join(base, name)
            with open(path, "rb") as f:
                parts += [os.path.relpath(path, STATIC).encode(), f.read()]
    return _digest(*parts)


_SHELL = _shell_build()


@app.get("/api/version")
def version():
    """The running build, and what a page that stays open compares itself with.

    `version` is BUILD_VERSION when the image sets it, otherwise `dev` — an honest unknown rather
    than a number that looks authoritative and is not. `shell` and `registry` are what the shell was
    DRAWN from: its own files and the tiles it was given. A tab loaded before either changed kept
    showing the office as it had been (measured 2026-10-05: a linked office's console drawn as this
    one's, an hour after the fix was live), so the shell asks for these and renews itself."""
    return jsonify(version=os.getenv("BUILD_VERSION", "").strip() or "dev", shell=_SHELL,
                   registry=_digest(json.dumps(_tiles(), sort_keys=True, ensure_ascii=False).encode()))


@app.get("/api/modules")
def modules():
    return jsonify(modules=_tiles())


# `/api/apps` and its `_ADMIN_TOOLS` list lived here. Both are gone, and the list is why.
#
# It hardcoded the name, icon and description of five apps — n8n, GlitchTip, Supabase Studio,
# Authentik, RedisInsight — inside a codebase that owns none of them. Two of those five are layer-3
# apps, so a layer-2 app was naming layer-3 ones, the inversion gate G9 exists to stop. And because
# the list was unconditional while the apps are not, the console advertised tiles for
# supabase-studio and redisinsight while both were disabled: clicking either reached nothing.
#
# The route itself had no callers left. The apps screen became the app-management app (#/m/apps),
# which already derives every tile — name, icon, launch target, embeddable or not — from the
# manifests, and now gets a proper icon for these five because each declares `routing[].module`
# with `embed: false` instead of leaving console to invent one. Deleting the route removes the
# second implementation rather than fixing it twice.


# `/api/overview` and its `_get_json` helper went with the "לוח בקרה" screen — its KPI strip was the
# only caller, and every number it aggregated is still read live on the screen that owns it
# (#/m/connections, #/m/concurrency, the mail app). Left in place it would be a ~6s live connections
# probe nothing renders, kept warm by a cache. It was also the only consumer of KPI_MAIL_URL, so
# apps/mail/app.json no longer contributes it.


@app.route("/api/connections", methods=["GET"])
@app.route("/api/connections/<path:sub>", methods=["GET", "POST", "DELETE"])
def connections_proxy(sub=""):
    """Proxy the connections credential plane so the shell's settings + install wizard use it."""
    url = f"{CONNECTIONS_URL}/api/connections" + (f"/{sub}" if sub else "")
    return _proxy(url)


@app.route("/api/conn/oauth/<cid>/start", methods=["GET"])
def conn_oauth_start(cid):
    """Begin an OAuth grant. NOT served by conn_generic below: connections' oauth entry points are
    browser-facing (/oauth/<cid>/start, /oauth/callback — the one registered redirect URI) and are
    deliberately NOT under /api like the rest of its API. The generic passthrough prepends /api and
    404s, which silently dead-ended the install wizard's 'connect Google' button — it reads
    authorize_url out of this JSON."""
    return _proxy(f"{CONNECTIONS_URL}/oauth/{cid}/start")


@app.route("/api/conn/<path:sub>", methods=["GET", "POST", "DELETE"])
def conn_generic(sub):
    """Passthrough to any connections API path (set/add/regenerate/export/oauth)."""
    return _proxy(f"{CONNECTIONS_URL}/api/{sub}")


# ── platform services (drive/mail) — the connection (account) plane ───────────────
# A platform service owns its own accounts + ONE active pointer, and exposes
# /manifest, /readyz, /connections (see ai/context/platform-service-contract.md §2). The console is
# the only HUMAN surface for that plane, so it proxies exactly those endpoints — same-origin, with
# the shell's SSO already applied. Nothing sensitive rides back: the contract forbids the list
# endpoint from returning secrets, so credentials still never cross into the browser (§5).
# GENERATED IN, not written here: PLATFORM_SERVICES is compiled by reconcile.py from the
# `capabilities` of every INSTALLED app that declares contract "platform-service.v1"
# ({"drive": "http://drive:8975", "mail": "http://mailapi:8970"}). This file used to hold that map
# literally, which meant a layer-2 base app named its layer-3 apps and adding a fourth service
# meant editing the console. Each *_URL override still wins, so an operator can repoint one.
SVC_BASES = {
    name: os.getenv(f"{name.upper()}_URL", endpoint)
    for name, endpoint in json.loads(os.getenv("PLATFORM_SERVICES", "{}")).items()
}


@app.route("/api/svc/<service>/connections", methods=["GET", "POST", "DELETE"])
@app.route("/api/svc/<service>/connections/<path:sub>", methods=["GET", "POST", "DELETE"])
def svc_connections(service, sub=""):
    """View / add / select / remove the accounts of a platform service (…/connections,
    …/connections/select, …/connections/<id>)."""
    base = SVC_BASES.get(service)
    if not base:
        return jsonify(error="unknown_service", service=service), 404
    return _proxy(f"{base.rstrip('/')}/connections" + (f"/{sub}" if sub else ""))


@app.route("/api/svc/<service>/<any(manifest, readyz, providers):what>", methods=["GET"])
def svc_meta(service, what):
    """/manifest = which protocols this service can connect (drives the 'add account' choice);
    /readyz = does the ACTIVE account actually probe ok — the same readiness contract n8n reads,
    so the console's dot and the automation layer can never disagree;
    /providers = the service's OWN provider catalogue — which providers exist, which auth method
    each offers, and the exact field keys it will accept. The connect wizard reads it instead of
    the hardcoded map it used to carry; without it in this allowlist the request falls through to
    the SPA catch-all, the wizard gets index.html where it expected JSON, and every provider card
    is missing (measured 2026-09-02)."""
    base = SVC_BASES.get(service)
    if not base:
        return jsonify(error="unknown_service", service=service), 404
    return _proxy(f"{base.rstrip('/')}/{what}")


# ── this office's own record — whether its install wizard has run ────────────────────────────────
# The control plane keeps it (`/api/office`, the `office:` block of platform.state.yaml); the shell
# asks on every entry, so the answer is remembered for a few seconds. A plane that cannot be asked
# is NOT a fresh office: the shell is never held hostage by a wizard because a service is restarting.
APP_MANAGEMENT_URL = os.getenv("APP_MANAGEMENT_URL", "http://app-management:8080").rstrip("/")
OFFICE_TTL_S = float(os.getenv("CONSOLE_OFFICE_TTL_S", "10"))
_OFFICE = {"at": 0.0, "asked": False, "rec": None}


def _office_record(fresh=False):
    """`{office, installed}` from the control plane, or None when it could not be asked."""
    now = time.time()
    if not fresh and _OFFICE["asked"] and now - _OFFICE["at"] < OFFICE_TTL_S:
        return _OFFICE["rec"]
    rec = None
    try:
        r = requests.get(f"{APP_MANAGEMENT_URL}/api/office", timeout=3)
        if r.ok:
            rec = r.json()
    except (requests.RequestException, ValueError):
        rec = None
    _OFFICE.update(at=now, asked=True, rec=rec if isinstance(rec, dict) else None)
    return _OFFICE["rec"]


def _first_run():
    """True only when the plane SAYS the wizard has not run (no `installed_at`).

    A FRESH answer is remembered for nothing: the one visitor of a fresh office is the person in the
    wizard, and the entry right after its last step must see the record it just wrote — not a
    ten-second-old "not yet" that hands them the wizard again. An installed office is remembered."""
    rec = _office_record()
    if rec is not None and not rec.get("installed"):
        rec = _office_record(fresh=True)
    return rec is not None and not rec.get("installed")


@app.get("/api/office")
def api_office():
    """The office's own record, as the control plane holds it — what the shell's brand line reads.

    `/api/business` lived here: a proxy to the ledger's (apitools') business profile, read by the old
    install screen and by the shell's first-run landing. Both are gone (core-003): the business's
    trading name and registration number are the ledger's own screen's business, the shell names the
    OFFICE, and first-run is decided server-side in `spa()`. A plane that cannot be asked answers
    `installed: null` — unknown, never "fresh"."""
    rec = _office_record()
    if rec is None:
        return jsonify(office={}, installed=None), 200
    return jsonify(office=rec.get("office") or {}, installed=bool(rec.get("installed")))


def _proxy(url):
    fwd = {k: v for k, v in request.headers if k.lower() not in _HOP}
    try:
        r = requests.request(request.method, url, params=request.args,
                             data=request.get_data(), headers=fwd, timeout=40)
    except requests.RequestException as e:
        return jsonify(error="connections_unreachable", message=str(e)), 502
    out = {k: v for k, v in r.headers.items() if k.lower() not in _HOP}
    return Response(r.content, status=r.status_code, headers=out)


# ── same-origin app embedding ─────────────────────────────────────────────────
# Each app is its own SSO-gated service on its own *.localhost — which CANNOT be iframed cross-origin
# (the in-frame auth redirect is X-Frame-blocked on http). So the console reverse-proxies each app under
# ITS OWN origin at /a/<name>/… : the iframe loads console.localhost/a/<name>/ (same origin, already
# authed by the console) and the app's relative URLs resolve back through here. The console shell (menu)
# therefore stays visible around every app. Apps must use RELATIVE URLs (a <base> is injected to help).
APP_BASES = {
    "connections":        CONNECTIONS_URL,
}
# Every OTHER entry is compiled: each app declares its own alias + backend in routing[].module,
# and reconcile.py writes .generated/registry/console.app_bases.json. A base app hardcoding
# "http://my-docs:8000" is the layering inversion G9 forbids — and it is how a proxy target for
# feature-validation outlived the service by weeks.
#
# Read AGAIN whenever the compiled file changes, not once at import: the map used to be frozen at
# the console's start, so an app enabled afterwards had its tile (modules are read per request) but
# every click on it answered `unknown_app` until someone restarted the console (2026-09-29:
# digital-assets and social-list, enabled and rendered while the console had been up for hours).
_BASES_FILE = os.path.join(GENERATED, "console.app_bases.json")
_BASES_SEEN = {"mtime": None, "peers": None, "map": dict(APP_BASES)}


def _app_bases():
    """The alias → backend map, rebuilt when the compiled file changes (an app enabled OR disabled
    since the last request), swapped in whole so a request never sees half a map."""
    try:
        mtime = os.stat(_BASES_FILE).st_mtime
    except OSError:
        return _BASES_SEEN["map"]
    peers_stamp = _peers_stamp()
    if mtime != _BASES_SEEN["mtime"] or peers_stamp != _BASES_SEEN["peers"]:
        try:
            with open(_BASES_FILE, encoding="utf-8") as f:
                compiled = json.load(f) or {}
            # A remote placement is a BASE URL like any other: the alias resolves to the office app's
            # door, which forwards it to the peer. Compiled entries win — an alias that a local app
            # also declares must not be stolen by a stale peer file.
            remote = {e["alias"]: e["base"] for e in _peer_entries() if e.get("base")}
            fresh = {**remote, **dict(APP_BASES)}
            for alias, spec in compiled.items():
                fresh[alias] = os.getenv(spec["env"], spec["default"]) if spec.get("env") else spec["default"]
            _BASES_SEEN.update(mtime=mtime, peers=peers_stamp, map=fresh)
        except (OSError, ValueError, KeyError, TypeError):
            pass                     # a half-written file: keep the last good map, try next request
    return _BASES_SEEN["map"]


_app_bases()


# ── a REMOTE app through this console's own origin ───────────────────────────────────────────────
# An app of a LINKED office has its own nested host (`<alias>.<office>.console.<domain>`, a router
# the compiler renders), and on a real domain the shell frames that. On `*.localhost` it cannot: each
# label under `localhost` is its own SITE, so the authorization hop to `auth.localhost` inside a
# frame is cross-site — the provider's session cookie is not sent and its login page refuses framing.
# The tile opened onto a browser error page (measured 2026-10-05, hp-laptop). It is the same failure
# the block above exists for, one office further away — so a remote app gets the same door:
# `/a/<alias>.<office>/` here, proxied to the alias and port the compiler names in the tile's `door`.
#
# WHICH apps come through here is the compiler's decision (`serve.through_console`), and not every
# app can: one that owns its origin — the office agent addresses `/api`, `/plugins` and a websocket
# at the ROOT — would find THIS office's agent there (measured 2026-10-05: the MacBook's בינה tile
# listed hp-laptop's conversations). Such a tile carries no `door`, so it is unknown here and the
# shell frames it on its nested host, asking that host for a sign-in first.
#
# WHAT THIS COSTS, said plainly: a page served here is in the console's own ORIGIN. A local app
# already is; a remote app framed this way is too — its scripts could reach whatever this console's
# own pages can, where on its nested host the browser kept the two origins apart. So on a localhost
# office, using another office's apps means trusting that office's app code as you trust your own.
# That is the trust a pairing already states (two operators confirm six digits to say "this is my
# other office"), it is limited to consoles where the nested host cannot work at all (the shell picks
# it only when the identity provider is another site), and a real-domain office keeps the isolation.
# The way to have both is a domain-level sign-in for `*.console.<domain>` at the identity layer, so
# the nested host needs no hop of its own — a change to the SSO blueprint, deliberately not made here.
_MODULES_FILE = os.path.join(GENERATED, "console.modules.yaml")
_DOORS_SEEN = {"mtime": None, "map": {}}


def _remote_doors():
    """`<alias>.<office>` → the door of that remote tile, re-read when the compiled registry changes."""
    try:
        mtime = os.stat(_MODULES_FILE).st_mtime
    except OSError:
        return _DOORS_SEEN["map"]
    if mtime != _DOORS_SEEN["mtime"]:
        try:
            with open(_MODULES_FILE, encoding="utf-8") as f:
                tiles = yaml.safe_load(f) or []
            _DOORS_SEEN.update(mtime=mtime, map=_doors_of(tiles))
        except (OSError, ValueError, yaml.YAMLError):
            pass                     # a half-written file: keep the last good map, try next request
    return _DOORS_SEEN["map"]


def _doors_of(tiles):
    """The doors a list of compiled tiles declares. Pure, so the rule is testable without a file."""
    doors = {}
    for t in tiles or []:
        if not isinstance(t, dict) or not isinstance(t.get("remote"), dict):
            continue
        d = t.get("door")
        if not isinstance(d, dict) or not d.get("base") or not t.get("id"):
            continue
        label = t["remote"].get("label")
        if isinstance(label, dict):
            label = label.get("he") or label.get("en")
        doors[str(t["id"])] = {
            "base": str(d["base"]), "host": str(d.get("host") or ""), "user": str(d.get("user") or ""),
            "from": [str(u) for u in (d.get("from") or []) if u],
            "office": str(label or t["remote"].get("office") or ""), "name": str(t.get("name") or t["id"]),
            "oid": str(t["remote"].get("office") or ""),
        }
    return doors


def _as_remote(fwd, door):
    """The request as the SERVING office must receive it — what the edge's chain writes for the
    nested host (`serve.render`): this office's authenticated user becomes the mapped user of that
    office, and the app is addressed by the name it answers under.

    And one thing the edge never has to do, because a browser does it for it: THIS office's own
    sign-in never crosses the link. Every app proxied here shares the console's origin, so the
    browser attaches the console's cookies — its SSO session among them — to every request; those are
    removed before the request leaves for another office.
    """
    def drop(name):
        for k in [k for k in fwd if k.lower() == name]:
            fwd.pop(k)

    drop("x-dgo-from")                               # never a client's claim
    if door.get("user"):
        drop("x-authentik-username")
        fwd["X-authentik-username"] = door["user"]
    if door.get("from"):
        fwd["X-DGO-From"] = ",".join(sorted(door["from"]))
    if door.get("host"):
        fwd["Host"] = door["host"]
    cookie = next((v for k, v in fwd.items() if k.lower() == "cookie"), None)
    if cookie is not None:
        kept = [part.strip() for part in cookie.split(";")
                if part.strip() and not part.strip().lower().startswith("authentik_")]
        drop("cookie")
        if kept:
            fwd["Cookie"] = "; ".join(kept)
    return fwd


@functools.lru_cache(maxsize=None)
def _static_block(file, name):
    """A marked region (`/* @<name>:start */ … /* @<name>:end */`) of one of the shell's static
    files, for a page this module writes itself: it carries the shell's own text, not a copy of it."""
    with open(os.path.join(STATIC, file), encoding="utf-8") as fh:
        return fh.read().split(f"/* @{name}:start */", 1)[1].split(f"/* @{name}:end */", 1)[0]


def _icon(name):
    """A glyph of the office's one icon set, drawn the way the shell draws it (app.js: mIcon)."""
    m = re.search(r"\b%s:\s*'([^']*)'" % re.escape(name), _static_block("app.js", "bina-icons"))
    return ('<svg class="ic-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{m.group(1)}</svg>') if m else ""


def _card(title, sub, body_html, again=0, raw=""):
    """What a tile shows when its app has no screen to show: THE card — the one the shell draws for
    an app it cannot frame (app.js: externalNotice), by the shell's own rules, palette and icon —
    in Hebrew, INSIDE the frame; never a JSON error, a blank page, or an engine's own sentence in
    its own language. `sub` is the one line that says which of the cases this is. `raw` is what was
    actually answered, as it was, one click away — a status code is not a sentence, so it lives
    there. `again` is how often (seconds) the card asks for the app again by itself, so it becomes
    the app the moment there is one — a card that has to be noticed and reloaded is a dead end with
    a sentence on it. `data-card` says, to whatever reads the page rather than looks at it (the live
    UI map), that this is a card and not the app's screen."""
    from html import escape
    said = f"<details><summary>מה שהיא אמרה</summary><pre>{escape(raw)}</pre></details>" if raw else ""
    return (
        '<!doctype html><html lang="he" dir="rtl" data-card><head><meta charset="utf-8">'
        + (f'<meta http-equiv="refresh" content="{int(again)}">' if again else "") +
        f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)}</title>'
        f'<style>{_static_block("style.css", "palette")}{_static_block("style.css", "card")}</style></head>'
        f'<body><div class="xn"><div class="xn-card"><span class="xn-ic">{_icon("alert")}</span>'
        f'<h2>{escape(title)}</h2><div class="xn-sub">{escape(sub)}</div>{body_html}{said}</div></div></body></html>')


#: What the link's door said about an app (`X-Dgo-Door`), in this console's words. `unreachable`
#: has none here on purpose: that is the link itself, and the link's own measured sentence is used.
_DOOR_SAID = {
    "app-down": "הלשכה ענתה, אבל האפליקציה הזאת לא עונה בה כרגע — היא כבויה או מופעלת מחדש.",
    "no-app": "הלשכה ענתה, אבל היא לא נותנת את האפליקציה הזאת ללשכה הזו.",
}


def _remote_said(door, said=""):
    """The sentence about a linked office that did not serve this app. Without `said` (what its door
    answered), it is the link's own for the hop it measured down, and only when it measured none,
    the three things it could be."""
    return (said or (_link_verdicts().get(door.get("oid") or "") or {}).get("why")
            or "הלשכה לא ענתה כרגע — היא מכובה, מנותקת, או שהקישור אליה נפל.")


def _remote_asleep(door, said="", raw=""):
    """A linked office that did not answer — or answered that it does not serve this app ("the app is
    broken" sends the owner to the wrong office's logs) — as the card a tile shows."""
    from html import escape
    office = door.get("office") or ""
    return _card(door.get("name") or "",
                 f"{office} · האפליקציה לא זמינה" if said else f"{office} לא זמינה כרגע",
                 f'<p>האפליקציה הזאת רצה בלשכת <b>{escape(office)}</b> ומגיעה לכאן דרך '
                 f'הקישור בין הלשכות. {escape(_remote_said(door, said))}</p>'
                 '<p>המסך הזה בודק שוב בעצמו, והאפליקציה תיפתח כאן ברגע שתהיה זמינה.</p>', again=15, raw=raw)


def _remote_refusal(door, said, status, page):
    """The answer when the LINK did not deliver (nobody answered through it, or its door said so):
    the card to a request for a page, and to a CALL the same sentence as JSON. A screen that was
    open when its office went quiet got an empty 502 for every call it made, and all it could tell
    the person looking at it was "the answer is not JSON" (the Mac office asleep, 2026-10-07).
    `code` is the door's own word; an app's own answer is never touched — only the link's."""
    if page:
        return Response(_remote_asleep(door, _DOOR_SAID.get(said, "")), status=status,
                        content_type="text/html; charset=utf-8")
    text = f'האפליקציה רצה בלשכת {door.get("office") or ""}. {_remote_said(door, _DOOR_SAID.get(said, ""))}'
    return jsonify(error=text, message=text, code=said or "unreachable", office=door.get("oid") or ""), status


def _app_no_screen(name, status=None, raw=""):
    """An app of THIS office that was asked for its page and had none to give: it did not answer
    (`status` None — restarting, switched off), or it answered an error that is not a page. The
    harness of the office agent answers a visitor it does not know with one line of English,
    `dsh web authentication required; reopen the URL printed by dsh web.`, and that line WAS the
    tile (measured 2026-10-06). What the app said stays one click away, as it said it."""
    from html import escape
    title = next((m.get("name") for m in _modules() if m.get("id") == name), None) or name
    if status is None:
        return _card(title, "האפליקציה לא ענתה",
                     "<p>האפליקציה לא ענתה כרגע — היא מופעלת מחדש או כבויה. כדאי לנסות שוב בעוד רגע.</p>")
    why = {401: "היא לא זיהתה את הכניסה שלך.", 403: "לחשבון הזה אין הרשאה אליה.",
           404: "המסך הזה לא קיים בה."}.get(status, "היא נתקלה בתקלה.")
    return _card(title, "אין לה מסך להציג", f"<p>האפליקציה ענתה, אבל בלי מסך להציג. {escape(why)}</p>",
                 raw=f"{status} {(raw or '').strip()[:400]}".strip())


def _inject_base(html, base):
    if "<base " in html.lower():
        return html
    tag = f'<base href="{base}">'
    low = html.lower()
    for anchor in ("<head>", "</title>", "<meta charset=\"utf-8\">"):
        i = low.find(anchor.lower())
        if i >= 0:
            i += len(anchor)
            return html[:i] + tag + html[i:]
    import re
    m = re.search(r"<html[^>]*>", html, re.I)
    return (html[:m.end()] + tag + html[m.end():]) if m else tag + html


# Console-embed polish. This used to hide every embedded app's own sidebar brand block
# (`.side/.sidebar .brand{display:none}`) on the theory that the shell already names the app in its
# nav and topbar, so the app's own header was a duplicate.
#
# The simulation — the design reference this platform is ported from — embeds its apps in the same
# shell and KEEPS each app's brand: the console's dark rail names the workspace, the app's light
# sidebar names itself, and the two read as two panels rather than one. Hiding it did not just remove
# a logo, it lifted the ENTIRE app sidebar by the brand's height, so every rail row below it sat ~40px
# off the design for every embedded app at once. That was the largest single pixel gap in the mail
# panels and it was equally present in drive.
#
# Nothing is injected now. Keep the constant (and the concatenation below) so a future per-shell rule
# has an obvious home, and so it is visible that the emptiness is a decision, not an omission.
EMBED_CSS = ""

# Per-app embed overrides — for apps we can't easily edit at the source (e.g. a vendored app),
# the console recolors their dark vertical sidebar to a LIGHT subordinate panel so it never competes
# with the console's dark primary rail (the double-navigation rule).
#
# EMPTY, and that is the correct state rather than a gap. The one entry here targeted the old wadmin
# admin UI (`.sidebar`, `.sidebar-link`, `.userbox`, `#username-display`). That page was deleted when
# its sections were folded into the chat app, and the replacement uses `aside.side` — so all seven
# rules matched nothing and had been dead since. Verified before removing: zero `class="sidebar"`
# attributes and zero `.sidebar` CSS rules in apps/chat/src/api/ui/chat.ejs (the twelve textual hits
# are all prose in comments).
#
# Keep the mechanism. An app that genuinely needs a light-mode override inside the shell adds its id
# here, and the injection point below is already wired.
APP_EMBED_CSS = {
    # Console owns connection selection and health. Drive's footer switcher duplicates those actions
    # inside the frame, so retain it standalone but hide it when the service is embedded here.
    "drive": """
<style id="console-drive-embed-css">
#acct { display: none !important; }
</style>
""",
}


def _rewrite_abs(html, name):
    """Rewrite root-absolute asset/link refs (href="/x" src="/x" action="/x") to the proxied
    path. A <base> only rebases *relative* URLs; root-absolute ones would otherwise escape to
    console.localhost/x. Skips protocol-relative (//) and already-proxied (/a/<name>/) URLs."""
    import re
    pat = re.compile(r'((?:href|src|action)=)(["\'])/(?!/|a/' + re.escape(name) + r'/)')
    return pat.sub(lambda m: f'{m.group(1)}{m.group(2)}/a/{name}/', html)


def _rewrite_location(location, upstream_url, base, name):
    """Map an upstream redirect back into an app's console mount."""
    resolved = urlparse(urljoin(upstream_url, location))
    upstream = urlparse(base)
    if (resolved.scheme, resolved.netloc) != (upstream.scheme, upstream.netloc):
        return location

    base_path = upstream.path or "/"
    if not base_path.endswith("/"):
        base_path += "/"
    if resolved.path == base_path.rstrip("/"):
        relative_path = ""
    elif resolved.path.startswith(base_path):
        relative_path = resolved.path[len(base_path):]
    else:
        relative_path = resolved.path.lstrip("/")
    mounted_path = f"/a/{name}/" + relative_path
    return urlunparse(("", "", mounted_path, "", resolved.query, resolved.fragment))


@app.route("/a/<name>/", defaults={"sub": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
@app.route("/a/<name>/<path:sub>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def app_proxy(name, sub):
    base = _app_bases().get(name)
    # a remote app (`<alias>.<office>`): never a local alias — those have no dot — so a compiled
    # local app can never be shadowed by one
    door = None if base else _remote_doors().get(name)
    if door:
        base = door["base"]
    if not base:
        return jsonify(error="unknown_app", app=name), 404
    # THE QUERY GOES THROUGH VERBATIM. `params=request.args` round-trips every parameter through
    # urlencode(), which is lossy for any URL that is not a list of `k=v` pairs. DSH (the office
    # agent, module `bina`) addresses its client bundles as
    #
    #     /plugins/??@scope/pkg/client.js,@scope/other/client.js&rev=<hash>
    #
    # where the leading `?` of the specifier list is a LITERAL character of the path. Re-encoded it
    # becomes `?%3F…=&rev=…`, the app does not recognise its own plugin URL, and every bundle answers
    # 404 — measured 2026-10-01: the bina tile in the console rendered its HTML and then said
    # "Failed to load plugins", while the same URLs served 200 at the app's own origin. A capture
    # cannot tell that from a broken app; this is the proxy's bug and it belongs here.
    query = request.query_string.decode("latin-1")
    url = base.rstrip("/") + "/" + sub + (("?" + query) if query else "")
    fwd = {k: v for k, v in request.headers if k.lower() not in _HOP}
    fwd["X-Forwarded-Prefix"] = f"/a/{name}"
    if door:
        _as_remote(fwd, door)

    # A STREAMING response must not be buffered here, or the embedded app loses live updates.
    #
    # This proxy read the whole body (`r.content`) before answering. For an event-stream that never
    # completes, that means the browser receives nothing until the 40s timeout fires and then gets a
    # dead connection — so EventSource reopens it, forever. The app works perfectly at its own origin
    # and appears simply not to push inside the console, which is the surface operators actually use.
    #
    # Keyed on the CLIENT's Accept header rather than on the response, because the read timeout has
    # to be decided before the request is made: a stream that is idle between heartbeats must not be
    # torn down as a slow response. `stream=True` is safe for everything — `r.content` below still
    # reads the full body on demand for the non-streaming paths.
    wants_stream = "text/event-stream" in (request.headers.get("Accept") or "").lower()
    asked_for_a_page = "text/html" in (request.headers.get("Accept") or "").lower()
    try:
        r = requests.request(request.method, url,
                             data=request.get_data(), headers=fwd,
                             timeout=(5, STREAM_IDLE_S) if wants_stream else 40,
                             stream=True, allow_redirects=False)
    except requests.RequestException as e:
        if door:
            return _remote_refusal(door, "", 502, asked_for_a_page)
        if asked_for_a_page:
            return Response(_app_no_screen(name), status=502, content_type="text/html; charset=utf-8")
        return jsonify(error="app_unreachable", app=name, message=str(e)), 502
    out = {k: v for k, v in r.headers.items() if k.lower() not in _HOP}
    ct = r.headers.get("Content-Type", "")
    # The linked office ANSWERED, and what it answered for the tile's own page is an error with no
    # page of its own (its door has no listener for the app, the app is switched off there): the
    # frame was simply blank — the MacBook's browser tile, 404 with an empty body, 2026-10-06. The
    # same card as an office that did not answer, with what is different about it; the status the
    # office gave stays the status.
    # …or it was the LINK's own door that answered, and said which of three things it is
    # (`X-Dgo-Door`): nobody answered through the link, the office answered and the app does not, or
    # the office does not give this app. The answer is this console's — it knows the office by name
    # and what was last measured about it — whatever the door wrote for a browser that reaches it bare.
    said = r.headers.get("X-Dgo-Door") if door else None
    if said:
        r.close()
        return _remote_refusal(door, said, r.status_code, asked_for_a_page)
    if door and asked_for_a_page and r.status_code >= 400 and "text/html" not in ct:
        return Response(_remote_asleep(door, "הלשכה ענתה, אבל האפליקציה הזאת לא זמינה בה כרגע.",
                                       raw=str(r.status_code)),
                        status=r.status_code, content_type="text/html; charset=utf-8")
    if not door and asked_for_a_page and r.status_code >= 400 and "text/html" not in ct:
        return Response(_app_no_screen(name, r.status_code, r.content[:2000].decode("utf-8", "replace")),
                        status=r.status_code, content_type="text/html; charset=utf-8")

    # keep the user inside the shell — and never leak internal hostnames to the client:
    # rewrite BOTH root-absolute ("/login") and app-absolute ("http://machine:8080/login")
    # Location headers to the proxied path.
    if r.is_redirect:
        for k in list(out):
            if k.lower() != "location":
                continue
            out[k] = _rewrite_location(out[k], url, base, name)
    if "text/html" in ct:
        html = _rewrite_abs(r.content.decode("utf-8", "replace"), name)
        html = _inject_base(html, f"/a/{name}/")
        _hi = html.lower().find("</head>")   # case-insensitive: injecting before <!DOCTYPE> forces quirks mode
        _css = EMBED_CSS + APP_EMBED_CSS.get(name, "")
        html = (html[:_hi] + _css + html[_hi:]) if _hi >= 0 else _css + html
        out.pop("Content-Length", None)
        # never let the browser cache the rewritten shell HTML — otherwise console-side embed
        # changes (base, asset rewrites, embed CSS) are masked by a stale copy in the iframe.
        out["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return Response(html.encode("utf-8"), status=r.status_code, headers=out)

    # Everything that is NOT html streams straight through.
    #
    # HTML above must stay buffered — the rewrite needs the whole document. Nothing else does, and
    # buffering everything is what made Server-Sent Events impossible: `r.content` waits for a body
    # to END, and an event-stream never does, so the request hung until the 40s timeout and the
    # browser got a dead connection it then reopened forever. Live updates therefore worked at an
    # app's own origin and silently failed inside the console iframe, which is the surface operators
    # actually use.
    #
    # Streaming the rest is a straight win beyond SSE: a large download (chat's conversation export,
    # a document, a QR image) no longer has to sit in this process's memory in full before the first
    # byte reaches the client.
    #
    # Safe to hand back DECODED bytes because _HOP already strips content-length and
    # content-encoding from the forwarded headers — so the client is never told a length or an
    # encoding that iter_content has already undone.
    if "text/event-stream" in ct:
        # Only for streams that stay open: re-state upstream's own request to any proxy in FRONT of
        # the console. Setting it on ordinary assets would change their caching for no reason.
        out["Cache-Control"] = "no-cache, no-transform"
        out["X-Accel-Buffering"] = "no"
        return Response(_bounded_stream(r), status=r.status_code, headers=out, direct_passthrough=True)
    return Response(r.iter_content(chunk_size=None),
                    status=r.status_code, headers=out, direct_passthrough=True)


# A proxied event-stream holds one of the worker's threads for as long as it stays open. With one
# app on screen that was one thread; desktop mode (static/desktop.js) keeps many apps open at once,
# and unbounded streams starved the pool: /healthz went unanswered for ~7 minutes, docker marked the
# console unhealthy and traefik stopped routing to it (measured on the local stack, 2026-09-25).
# So a stream ends after STREAM_MAX_S, or after STREAM_IDLE_S without a byte. The only consumers
# through this proxy (domains, chat) use EventSource, which reconnects by itself.
def _bounded_stream(r):
    end = time.monotonic() + STREAM_MAX_S
    try:
        for chunk in r.iter_content(chunk_size=None):
            yield chunk
            if time.monotonic() >= end:
                break
    except requests.RequestException:
        pass   # idle past STREAM_IDLE_S, or the upstream went away: end it; the client reconnects
    finally:
        r.close()


@app.route("/", defaults={"p": "index.html"})
@app.route("/<path:p>")
def spa(p):
    # A fresh office meets the install wizard instead of the shell — decided HERE, from the control
    # plane's record, so no script has to run first and nothing is installed by default. Only the
    # shell's own entry: a deep link into an app or a file is served as asked, and index.html asked
    # for by name is the shell itself.
    if p == "index.html" and request.path == "/" and _first_run():
        p = "install.html"
    full = os.path.join(STATIC, p)
    resp = send_from_directory(STATIC, p) if os.path.isfile(full) \
        else send_from_directory(STATIC, "index.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


if __name__ == "__main__":
    app.run("0.0.0.0", int(os.getenv("PORT", "8000")))
