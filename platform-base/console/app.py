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
from flask import Flask, g, request, Response, jsonify, redirect, send_from_directory
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
#
# …and a compressed shell file revalidates (DGO-611). flask-compress answers a STREAMED response (send_from_directory's)
# conditionally on the ETag it writes ("<file's>:br") only for the endpoints COMPRESS_STREAMING_ENDPOINT_CONDITIONAL
# names — "static" — and the shell is served by `spa`: a reload got the whole compressed file again for the ETag the
# browser held (measured in the image: 200, 61,619 bytes, every time; If-Modified-Since alone was a 304, and a browser
# sends both). `spa` is NOT named there: it also hands back what an app answers (app_proxy), and a named endpoint's
# compressed stream is buffered whole (second reader). So only the shell's own files (`g.shell_file`, set in spa) are
# made conditional again, after compression — this hook is registered before Compress, and Flask runs them in reverse.
def _shell_file_revalidates(resp):
    if g.get("shell_file") and request.method in ("GET", "HEAD") and resp.status_code == 200 \
            and resp.headers.get("Content-Encoding"):
        resp.make_conditional(request)
    return resp


app.after_request(_shell_file_revalidates)
Compress(app)


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ── the office's admins (DGO-1755) ─────────────────────────────────────────────────────────────
# forward-auth tells every app a person's groups (X-authentik-groups, `|`-joined, as /api/me reads them). `admins`
# opens the office's root apps — an app.json's `people: admins`; «authentik Admins» is the same group's name under
# authentik and with the SSO off. traefik's `authentik-admins@file` refuses anyone else at the app's own host, but
# THIS door (/a/<alias>/) reaches an app's container directly, past traefik, so it asks the same question itself —
# and so do the shell's own doors to the credential plane and to a service's accounts.
ADMIN_GROUPS = {"admins", "authentik-admins", "authentik Admins"}   # forward-auth's two names, authentik's own


def _is_admin():
    """Does the request's groups header name an admins' group? STAGE ONE of DGO-1813 (AGENTS rule 8): the header is
    still believed from any caller, as it always was, but a belief the request cannot prove — its sign-in headers
    were not written by a sign-in hop or the console's link builder (`_signin_proved`) — is NAMED in the log, so
    every office lists who still opens an admins' door on a header it wrote itself. Stage two believes it only when
    proved, once that log is empty."""
    believed = bool(ADMIN_GROUPS & set((request.headers.get("X-authentik-groups") or "").split("|")))
    if believed and not _signin_proved():
        try:
            _name_unproved_admin()
        except Exception:      # naming must never change an answer (48 threads share the dict below)
            pass
    return believed


#: (door, caller) → when it was last named: once per ten minutes each. Bounded: past 256 keys the ones older than
#: ten minutes go, and if that is not enough, all of them (a forger varying its address cannot grow it without end)
_UNPROVED_ADMIN_SAID: dict = {}


def _admins_door(path):
    """The DOOR a path is, never the path itself: the path is the caller's to choose (`/api/conn/<anything>` reaches
    the gate, a 404 included), and it can hold a token (`/api/conn/broker/redeem/<tok>`). So the door is one of a
    fixed set: `/a/<alias>/` (an alias that resolved — the only way past `_admins_alias`), the credential plane's
    two prefixes, a service's accounts by its validated name, the language, or `other`."""
    parts = path.split("/")
    if len(parts) > 2 and parts[1] == "a" and re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,62}", parts[2] or ""):
        return f"/a/{parts[2]}/"
    if path == "/api/connections" or path.startswith("/api/connections/"):
        return "/api/connections"
    if path.startswith("/api/conn/"):
        return "/api/conn/"
    if len(parts) > 4 and parts[1:3] == ["api", "svc"] and parts[4] == "connections":
        name = parts[3] if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", parts[3] or "") else "?"
        return f"/api/svc/{name}/connections"
    return path if path == "/api/language" else "other"


def _name_unproved_admin():
    door = _admins_door(request.path or "/")
    caller = request.remote_addr or "?"
    now = time.time()
    if now - _UNPROVED_ADMIN_SAID.get((door, caller), 0.0) < 600:
        return
    if len(_UNPROVED_ADMIN_SAID) >= 256:
        for k, at in list(_UNPROVED_ADMIN_SAID.items()):
            if now - at >= 600:
                _UNPROVED_ADMIN_SAID.pop(k, None)
        if len(_UNPROVED_ADMIN_SAID) >= 256:
            _UNPROVED_ADMIN_SAID.clear()
    _UNPROVED_ADMIN_SAID[(door, caller)] = now
    hops = len(_signin_hops())
    # hops=0 means THIS console could not resolve traefik/the door at all: then every admin is named, a person
    # through traefik too — the line says so, so stage two's «the log is empty» is never read off such an office
    app.logger.warning("console-unproved-admin: %r %r caller=%r agent=%r hops=%d — an admins' door opened on a "
                       "groups header no sign-in hop wrote (DGO-1813; refused from stage two)%s", request.method,
                       door, caller, (request.headers.get("User-Agent") or "")[:80], hops,
                       "" if hops else " — NO sign-in hop resolves here, so this names traefik's own requests too")


def _admins_path(path, method):
    """Is this a door of the shell only the office's admins go through? The credential plane (every key of the office,
    /api/connections and /api/conn/…), a WRITE to a platform service's accounts (/api/svc/<s>/connections…: add,
    select, remove — INDOX's read-only probes and every service's readyz stay everyone's), and a change of
    the office's language."""
    if path == "/api/connections" or path.startswith(("/api/connections/", "/api/conn/")):
        return True
    parts = path.split("/")
    if len(parts) > 4 and parts[1:3] == ["api", "svc"] and parts[4] == "connections":
        return method not in ("GET", "HEAD")
    return path == "/api/language" and method not in ("GET", "HEAD")


def _not_for_you(title="האפליקציה הזאת"):
    """The answer to a signed-in person who is not an admin at an admins' door: the card to a page, the sentence as
    JSON to a call. 403, never a hint of what the app holds."""
    text = "רק מנהלי הלשכה נכנסים לכאן: זה פותח את המחשבים, החיבורים והמפתחות של הלשכה. אם זה נחוץ לך, פנו לבעל הלשכה."
    if "text/html" in (request.headers.get("Accept") or "").lower():
        return Response(_card(title, "למנהלי הלשכה בלבד", f"<p>{text}</p>"), status=403,
                        content_type="text/html; charset=utf-8")
    return jsonify(error="admins_only", message=text), 403


@app.before_request
def _admins_doors():
    if _admins_path(request.path, request.method) and not _is_admin():
        return _not_for_you("הדלת הזאת")
    return None


@app.get("/api/me")
def me():
    u = {k.replace("X-authentik-", ""): request.headers.get(k) for k in _AUTH}
    return jsonify(user=u.get("username") or "אורח", email=u.get("email"),
                   name=u.get("name") or u.get("username") or "אורח",
                   groups=(u.get("groups") or "").split("|") if u.get("groups") else [])


@app.get("/api/signout")
def signout():
    """Where a person signs out of THIS office (DGO-1621): the office's own sign-in app's page — the sign-in app
    signs out every app of the office at once. Its own route, not a field of /api/me, whose answer the native core
    (packaging/dgo) repeats byte for byte. Empty for a visitor nobody signed in, and under authentik, whose outpost
    sign-out no router of an app's host delivers — the menu then says there is no sign-out here, rather than offer
    a link that reloads the console. And only at the office's own console host (CONSOLE_HOST): at a LAN address
    (apps/lan-console) the person signed in through that app's own sign-in, which this page does not end, and a
    phone there cannot reach the sign-in host. The request's host only CHOOSES between the two; the address given
    is the office's own, and the page adds its return address (`rd`) itself. Nor through another office's link
    (X-DGO-Office, which the door writes on everything it hands on, with the console's own Host): that person
    signed in at the office they browse from, and this office's sign-in page is not theirs to reach."""
    signed_in = bool(request.headers.get("X-authentik-username"))
    own = os.getenv("DGO_IDENTITY", "authentik") == "forward-auth"
    here = request.host.split(":")[0].lower() == os.getenv("CONSOLE_HOST", "").split(":")[0].lower()
    linked = bool(request.headers.get("X-DGO-Office"))
    return jsonify(url=os.getenv("CONSOLE_SIGNOUT_URL", "") if signed_in and own and here and not linked else "")



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
        if not isinstance(doc, dict):
            # a list or a scalar is no placement (DGO-611): `.get` on it raised, and /api/modules answered 500 —
            # no tiles at all, for one file. Skipped by name; the rest of the rail stands.
            app.logger.warning("peers.d/%s is not a JSON object — skipped", n)
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


#: What a tile carries for THIS server only: `door`, how it reaches a remote app (an internal address
#: and the identity mapping of the link), and `handoffs`, where it asks an app which people it is
#: waiting for (DGO-1336). The browser needs the tile, not the route.
SERVER_ONLY = ("door", "handoffs")


def _tiles():
    return [{k: v for k, v in m.items() if k not in SERVER_ONLY} for m in _modules()]


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


# ── a person needed in another app's screen (DGO-1336) ──────────────────────────────────────────
# The owner pressed «Continue with Google» in the HP's Claude tile on his phone; Google's account
# chooser opened in the office browser's own display, and he went on looking at «Sign In» («זה לא עובד
# לא פותח לי שום דפדפן», 2026-11-04). An app that holds such a screen records each hand-off and lists
# the current ones (`handoffs` in its manifest; the compiler puts the address on its tile, here and on
# every office it is given to), so this server asks every tile that carries one and answers the shell
# with what concerns IT: in which tile the person is needed (`at`), for which tile (`for`, the app that
# asked, in the same office), and how it stands. The shell switches him there and back
# (static/handoffs.js). Records only — no address, no tab, nothing that acts.
HANDOFFS_TIMEOUT_S = float(os.getenv("CONSOLE_HANDOFFS_TIMEOUT_S", "3"))
#: Every open shell asks every 2 s; an app is asked once for all of them in this window — and an app
#: that did not answer is not asked again for a while, so a fallen link does not hold every request.
HANDOFFS_FRESH_S, HANDOFFS_SILENT_S = 1.0, 15.0
_HANDOFFS_SEEN = {}                     # address → (asked at, records, answered)
#: What a record may say to the shell — a linked office's answer is data, never a command: a slug that
#: is not one could steer the shell's address, so it is checked here, where the address is built.
HANDOFF_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
HANDOFF_STATES = ("needed", "done", "failed")


def _handoffs_of(address):
    """One app's list. An app that does not answer keeps its LAST GOOD answer: a link that drops for a
    moment (the HP while its browser wakes) must not read as "the hand-off is gone", or the shell would
    forget the way back it promised the person (the second reader of DGO-1336)."""
    seen = _HANDOFFS_SEEN.get(address)
    now = time.time()
    if seen and now - seen[0] < (HANDOFFS_FRESH_S if seen[2] else HANDOFFS_SILENT_S):
        return seen[1]
    records, answered = (seen[1] if seen else []), False
    try:
        r = requests.get(address, timeout=HANDOFFS_TIMEOUT_S)
        if r.ok:
            records = [h for h in (r.json().get("handoffs") or []) if isinstance(h, dict)]
            answered = True
    except (requests.RequestException, ValueError, AttributeError):
        pass
    _HANDOFFS_SEEN[address] = (now, records, answered)
    return records


#: The tiles that list hand-offs, kept while the registry they come from is unchanged: every visible
#: shell asks every 2 s, and the console must not parse the whole registry for each of them.
_HANDOFF_TILES = {"key": None, "tiles": []}


def _handoff_tiles():
    try:
        key = (os.stat(os.path.join(GENERATED, "console.modules.yaml")).st_mtime, _peers_stamp())
    except OSError:
        key = (None, _peers_stamp())
    if key != _HANDOFF_TILES["key"]:
        _HANDOFF_TILES.update(key=key, tiles=_modules())
    return _HANDOFF_TILES["tiles"]


def _office_of(tile):
    r = tile.get("remote")
    return str(r.get("office") or "") if isinstance(r, dict) else ""


def _names_of(tile):
    """What a tile is called: its id and alias here, and — a linked office's — what it is called THERE
    (the same names static/module-ref.js resolves a link by)."""
    r = tile.get("remote") if isinstance(tile.get("remote"), dict) else {}
    return {str(x) for x in (tile.get("id"), tile.get("alias"), r.get("module_id"), r.get("alias")) if x}


def handoffs_for(tiles, ask=None, now=None):
    """The hand-offs of every tile that lists them, each placed on THIS office's tiles. Pure but for
    `ask` (default `_handoffs_of`), so the rule is testable without a network. A record whose slug,
    state or id is not one is dropped; `age` is how long ago it last changed."""
    ask = ask or _handoffs_of
    stamp = time.time() if now is None else now
    out = []
    for at in tiles:
        address = at.get("handoffs")
        if not isinstance(address, str) or not address.startswith("http://"):
            continue
        office = _office_of(at)
        for h in ask(address):
            slug, state, hid = str(h.get("slug") or ""), str(h.get("state") or ""), str(h.get("id") or "")
            if not (HANDOFF_SLUG.fullmatch(slug) and state in HANDOFF_STATES and HANDOFF_SLUG.fullmatch(hid)):
                continue
            app_id = str(h.get("for") or "")
            target = next((t.get("id") for t in tiles
                           if t is not at and _office_of(t) == office and app_id in _names_of(t)), "")
            try:
                age = max(0, int(stamp - float(h.get("updated_at"))))
            except (TypeError, ValueError):
                age = None
            out.append({"at": at.get("id"), "for": target or "", "app": app_id, "slug": slug, "state": state,
                        "sentence": str(h.get("sentence") or "")[:300], "id": hid, "age": age})
    return out


@app.get("/api/handoffs")
def handoffs():
    return jsonify(handoffs=handoffs_for(_handoff_tiles()))


# ── may an app be shown INSIDE this console? (#63) ─────────────────────────────
# A window on an app's own host that the app forbids being framed in stayed EMPTY — the browser
# draws its own grey error page and tells the page that framed it nothing (EXF, 2026-10-28: the
# services window). The browser decides from two headers of the app's answer, so the console asks
# the same answer server-side and judges it the way a browser does:
#   · CSP `frame-ancestors` (when present it wins: browsers then ignore X-Frame-Options) must allow
#     this console's origin — `'none'` never does, `'self'` only for the app's own origin;
#   · otherwise X-Frame-Options: DENY refuses, SAMEORIGIN refuses unless the app IS this origin.
# The verdict is "refused" only when the answer says so; no answer (a timeout, a TLS or DNS
# failure, a sign-in page) is "unknown" and the shell frames as it always did. Only hosts of this
# office's own domain are asked (no open fetcher inside the office network), and nothing of the
# body is read or returned.
#
# THE ANSWER JUDGED IS THE APP'S OWN (DGO-1502). This request carries nobody's sign-in, so an app
# behind the office's sign-in answers it with a redirect to the sign-in page — and that page refuses
# every frame (`X-Frame-Options: DENY`, forward-auth renderLogin), on purpose. Followed to the end,
# the chain judged THE SIGN-IN PAGE: Meet, Plane and Obsidian were all "refused" on Exampleu's office
# (measured 2026-11-09), while each answers a signed-in browser with no framing header at all. A
# desktop window of Meet was emptied into the «נפתחת בלשונית נפרדת» card, and the next open of it went
# straight to a new tab — «פגישות נפתחת לפעמים רק בחוץ». So a redirect is followed only while it stays
# on the asked origin (an app's own `/` → `/signin`); one that leaves it is the door the person's
# browser passes with its own session, and the verdict is "unknown". It also keeps this fetcher on the
# office's own hosts: an office host that redirects elsewhere is not followed there.
# What this check can still see is the answer of an app whose own host answers WITHOUT the sign-in
# (`auth: none` — the #63 case, examplech-services, sets X-Frame-Options itself). An app behind the
# sign-in that refused frames by itself could not be told apart from one that does not; none of the
# own-host tiles behind it does today (Meet, Plane, Obsidian, measured on Exampleu).
FRAME_CHECK_TTL = int(os.environ.get("FRAME_CHECK_TTL", "300"))
FRAME_CHECK_HOPS = 5
_frame_seen = {}
_REDIRECTS = (301, 302, 303, 307, 308)


def _origin(u):
    """scheme://host:port, the host lower-cased and the scheme's default port written out, so
    `https://Svc` and `https://svc:443/x` are one origin. A malformed port raises ValueError."""
    p = urlparse(u)
    port = p.port or {"http": 80, "https": 443}.get(p.scheme)
    return f"{p.scheme}://{(p.hostname or '').lower()}:{port}"


def frame_answer(url):
    """The asked origin's OWN answer to `url`: (response, None), or (None, why) when the redirects
    leave that origin (or never end). Each hop is closed; nothing of a body is read."""
    here = _origin(url)
    for _ in range(FRAME_CHECK_HOPS + 1):
        r = requests.get(url, timeout=(3, 4), allow_redirects=False, stream=True,
                         headers={"Accept": "text/html", "Sec-Fetch-Dest": "iframe"})
        r.close()
        loc = next((v for k, v in r.headers.items() if k.lower() == "location"), "")
        if r.status_code not in _REDIRECTS or not loc:
            return r, None
        nxt = urljoin(url, loc)
        if _origin(nxt) != here:
            return None, "redirect to " + (urlparse(nxt).hostname or "another address")
        url = nxt
    return None, "too many redirects"


def _csp_allows(policy, console_origin, app_origin):
    """None when the policy says nothing about framing, else (allowed, the directive as written)."""
    for part in policy.split(";"):
        bits = part.strip().split()
        if not bits or bits[0].lower() != "frame-ancestors":
            continue
        srcs = [s for s in bits[1:]]
        said = "frame-ancestors " + " ".join(srcs)
        c = urlparse(console_origin)
        for s in srcs:
            low = s.lower()
            if low == "'none'":
                return False, said
            if low == "'self'":
                if console_origin == app_origin:
                    return True, said
                continue
            if low == "*":
                return True, said
            if low.endswith(":") and "/" not in low:              # a scheme source: `https:`
                if c.scheme == low[:-1]:
                    return True, said
                continue
            anyport = low.endswith(":*")
            src = low[:-2] if anyport else low
            src = src if "://" in src else f"{c.scheme}://{src}"
            sp = urlparse(src)
            if sp.scheme != c.scheme:
                continue
            host = sp.hostname or ""
            ch = c.hostname or ""
            if host.startswith("*."):
                if not ch.endswith(host[1:]):
                    continue
            elif host != ch:
                continue
            try:
                port = sp.port or {"http": 80, "https": 443}.get(sp.scheme)
            except ValueError:
                continue
            cport = c.port or {"http": 80, "https": 443}.get(c.scheme)
            if anyport or port == cport:
                return True, said
        return False, said
    return None


def frame_verdict(headers, console_origin, app_origin):
    """("ok" | "refused", why) for an app's response headers, as a browser judges them."""
    csp = [v for k, v in headers.items() if k.lower() == "content-security-policy"]
    for policy in csp:
        for one in policy.split(","):                   # several policies folded into one header
            got = _csp_allows(one, console_origin, app_origin)
            if got is not None and not got[0]:
                return "refused", "Content-Security-Policy: " + got[1]
    if any(_csp_allows(p, console_origin, app_origin) is not None for pol in csp for p in pol.split(",")):
        return "ok", ""
    xfo = next((v for k, v in headers.items() if k.lower() == "x-frame-options"), "").strip()
    first = xfo.split(",")[0].strip().upper()
    if first == "DENY":
        return "refused", "X-Frame-Options: " + xfo
    if first == "SAMEORIGIN" and console_origin != app_origin:
        return "refused", "X-Frame-Options: " + xfo
    return "ok", ""


def _office_domain(host):
    host = (host or "").split(":")[0].lower()
    if re.fullmatch(r"[0-9.]+|\[[0-9a-f:]+\]", host):
        return None                                     # an address has no names under it
    return host.split(".", 1)[1] if "." in host else host


@app.get("/api/frame-check")
def frame_check():
    url = (request.args.get("url") or "").strip()
    u = urlparse(url)
    proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "https").split(",")[0].strip()
    console_origin = f"{proto}://{request.host}"
    dom = _office_domain(request.host)
    host = (u.hostname or "").lower()
    if u.scheme not in ("http", "https") or not host or not dom or not (host == dom or host.endswith("." + dom)):
        return jsonify(verdict="unknown", why="not an address of this office"), 400
    app_origin = f"{u.scheme}://{u.netloc.lower()}"
    key = (console_origin, app_origin + (u.path or "/"))
    hit = _frame_seen.get(key)
    if hit and time.time() - hit[0] < FRAME_CHECK_TTL:
        return jsonify(hit[1])
    try:
        r, left = frame_answer(url)
        if r is None:
            out = {"verdict": "unknown", "why": left}
        else:
            verdict, why = frame_verdict(r.headers, console_origin, app_origin)
            out = {"verdict": verdict, "why": why, "status": r.status_code}
    except (requests.RequestException, ValueError) as e:    # ValueError: a Location that is no URL
        out = {"verdict": "unknown", "why": type(e).__name__}
    _frame_seen[key] = (time.time(), out)
    return jsonify(out)


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


@app.route("/api/conn/<path:sub>", methods=["GET", "POST", "DELETE"])
def conn_generic(sub):
    """Passthrough to any connections API path (set/add/regenerate/export)."""
    return _proxy(f"{CONNECTIONS_URL}/api/{sub}")


# ── platform services (drive/mail) — the connection (account) plane ───────────────
# A platform service owns its own accounts + ONE active pointer, and exposes
# /manifest, /readyz, /connections (see ai/context/platform-service-contract.md §2). Each app shows and
# connects its accounts in its own screen (DGO-1624); the console proxies /readyz and /connections for
# another app's screen that reads them (INDOX reads mail's) — same-origin, with the shell's SSO already
# applied. Nothing sensitive rides back: the contract forbids the list endpoint from returning secrets,
# so credentials still never cross into the browser (§5).
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


@app.route("/api/svc/<service>/<any(readyz):what>", methods=["GET"])
def svc_meta(service, what):
    """/readyz = does the ACTIVE account actually probe ok — the same readiness contract n8n reads; INDOX reads
    mail's from the browser. /manifest and /providers went with the shell's connect wizard (DGO-1624): each app
    connects its accounts in its own screen, from its own service."""
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
    _drop_unproved_signin(fwd)
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
_ADMIN_BASES = ("connections",)      # of APP_BASES: the credential plane is the office's admins' (DGO-1755)
_BASES_SEEN = {"mtime": None, "peers": None, "map": dict(APP_BASES), "admins": frozenset(_ADMIN_BASES)}


def _admins_alias(name):
    """Is /a/<name>/ a door only the office's admins go through (DGO-1755)?"""
    _app_bases()
    return name in _BASES_SEEN["admins"]


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
            # who may go through each door (DGO-1755): an admins' app (`people: admins`, compiled in), the credential
            # plane, and — until a linked office's catalog says who opens its apps — every placement there
            admins = set(_ADMIN_BASES) | {a for a in remote if a not in compiled} | {
                alias for alias, spec in compiled.items() if spec.get("people") == "admins"}
            _BASES_SEEN.update(mtime=mtime, peers=peers_stamp, map=fresh, admins=frozenset(admins))
        except (OSError, ValueError, KeyError, TypeError):
            pass                     # a half-written file: keep the last good map, try next request
    return _BASES_SEEN["map"]


_app_bases()


# ── the office's language (DGO-971, ai/context/platform-language.md) ─────────────────────────────
# ONE variable for the whole office: `language:` in platform.state.yaml, compiled by reconcile.py (and its Go
# twin) into .generated/registry/locale.json. Read here per request, re-read when the file changes, like the
# bases above: switching a language must not need a restart of the shell. Two readers:
#   · GET /api/language answers it;
#   · app_proxy() puts <meta name="bina-lang"> at the start of every page it frames (_inject_lang): how a
#     framed app learns the language with no cookie, no fetch and no cross-origin request
#     (bina-ui/bina-lang.js reads it). It outranks a per-browser choice there by the runtime's design: inside
#     the console the office's language is the one shown.
# The fallback is Hebrew with `available` naming Hebrew only: an honest «not known», never an empty menu.
# Not here yet: the shell's own <html lang dir> and the switcher, which are display changes and come as a
# mock first; and the write path, which is the control plane's.
_LOCALE_FILE = os.path.join(GENERATED, "locale.json")
_LOCALE_FALLBACK = {"active": "he", "default": "he", "dir": "rtl",
                    "available": [{"code": "he", "label": "עברית", "label_en": "Hebrew", "dir": "rtl"}]}
_LOCALE_SEEN = {"mtime": None, "doc": _LOCALE_FALLBACK}
_LANG_CODE = re.compile(r"[a-z]{2,3}(-[a-z0-9]{2,8})?")


def _locale():
    """The compiled language document, re-read whenever the file changes; the last good one while it is
    half-written, and the fallback while there is none."""
    try:
        mtime = os.stat(_LOCALE_FILE).st_mtime
    except OSError:
        return _LOCALE_SEEN["doc"]
    if mtime != _LOCALE_SEEN["mtime"]:
        try:
            with open(_LOCALE_FILE, encoding="utf-8") as f:
                doc = json.load(f)
            if (isinstance(doc, dict) and _LANG_CODE.fullmatch(str(doc.get("active") or ""))
                    and doc.get("dir") in ("rtl", "ltr")):
                _LOCALE_SEEN.update(mtime=mtime, doc=doc)
        except (OSError, ValueError):
            pass                     # half-written: keep the last good document, try next request
    return _LOCALE_SEEN["doc"]


def _lang_meta(doc=None):
    """`<meta name="bina-lang">` for a framed page: the code and its direction, nothing a page could inject
    through (the document was checked when it was read)."""
    doc = doc or _locale()
    return f'<meta name="bina-lang" content="{doc["active"]}" data-dir="{doc["dir"]}">'


_HEAD_OPEN = re.compile(r"<head\b[^>]*>", re.I)
_HTML_OPEN = re.compile(r"<html\b[^>]*>", re.I)
_DOCTYPE = re.compile(r"<!doctype\b[^>]*>", re.I)


def _inject_lang(html, doc=None):
    """The meta at the START of <head>, so a script in <head> that reads it once finds it. A page with no
    <head> (connections' ui.html) gets it after <html>, or after the doctype: never BEFORE the doctype,
    which puts the page in quirks mode (the second reader of DGO-971). Found on the page itself, not on a
    lowercased copy whose offsets can differ."""
    meta = _lang_meta(doc)
    for pattern in (_HEAD_OPEN, _HTML_OPEN, _DOCTYPE):
        m = pattern.search(html)
        if m:
            return html[:m.end()] + meta + html[m.end():]
    return meta + html


@app.get("/api/language")
def language():
    """The office's language, and every language this platform has a dictionary for."""
    return jsonify(_locale())


@app.post("/api/language")
def language_set():
    """Switch the office's language through the control plane, which owns the write (this base app mounts no
    repo; app-management runs `reconcile.py lang` and the render). The answer is the plane's own: the new
    document, or its refusal with the reason. The caller's headers go with it as _proxy() sends them, the
    link's X-DGO-Office included, so the plane's refusal of a linked caller holds through this door too; only
    the body is rewritten, to say the console asked."""
    body = request.get_json(silent=True) or {}
    # a body that is not an object, and a «code» no language has (any length the browser sends), are answered
    # here by name — never a 500, never megabytes handed on (the second reader of slice 4)
    if not isinstance(body, dict):
        return jsonify(ok=False, error="the body is a JSON object of named fields: {\"lang\": \"en\"}"), 400
    lang = str(body.get("lang") or "").strip()
    if len(lang) > 40:
        return jsonify(ok=False, error="unknown_language", detail="not a language code"), 400
    payload = json.dumps({"lang": lang, "by": "console"}).encode()
    fwd = {k: v for k, v in request.headers if k.lower() not in _HOP and k.lower() != "content-length"}
    fwd["Content-Type"] = "application/json"
    try:
        # the plane's own worst case is 20 s for the lock, 60 s for the write and 120 s for the render: waited out
        # whole, so a slow render is never told as «unreachable» while the switch lands (the third reader)
        r = requests.post(f"{APP_MANAGEMENT_URL}/api/language", data=payload, headers=fwd, timeout=210)
    except requests.RequestException as e:
        return jsonify(ok=False, error="control_plane_unreachable", message=str(e)[:200]), 502
    return Response(r.content, status=r.status_code,
                    content_type=r.headers.get("Content-Type", "application/json"))


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


def _nests_host(hostname: str) -> bool:
    """Can this console's own host carry an app's label in front of it? (app.js `noNestedHost`, server-side.)

    On `*.localhost` every label is its own site, a bare service name and an IP address resolve nothing
    under them — so a nested host is not an address to send a person to, and nothing here offers one.
    """
    h = (hostname or "").strip().lower()
    if not h or ":" in h or h.endswith(".localhost") or h == "localhost":
        return False
    if h.replace(".", "").isdigit():                      # an IPv4 address
        return False
    return "." in h


def _external_redirect(name: str):
    """Where a `<alias>.<office>` TILE of a linked office is actually opened — or None.

    `/a/<id>/` answers a LOCAL app (or a tile whose door this office reaches). A remote tile that owns
    its own origin (`external: true` — the official Claude app, Plane) is framed by the shell on
    `<host>.<this console's host>`, an address the SHELL builds (app.js `externalUrl`); it was never a
    route of `/a/`. So a link written as `/a/bina-claude.hp-laptop/` answered `unknown_app` — measured
    2026-11-04 on vps1, after our own message told the owner to open exactly that (DGO-1338; the rule
    of DGO-1268 was written for this and broken again). The name is redirected to the address the
    shell would have opened, and ONLY for a remote tile of that kind: a local app's alias keeps its
    404 (it is a typo), a tile with a door never reaches here, and a console whose host cannot nest
    keeps its 404 rather than sending a person to a name that resolves nowhere.
    """
    for t in _tiles():
        if str(t.get("id")) != name or not isinstance(t.get("remote"), dict) or not t.get("external"):
            continue
        label = str(t.get("host") or t["id"])
        if not _nests_host(request.host.split(":")[0]):
            return None
        proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "https").split(",")[0].strip()
        tail = str(t.get("path") or "")
        return f"{proto}://{label}.{request.host}{tail if tail.startswith('/') else '/'}"
    return None


#: The hops that WRITE the sign-in headers: traefik (forward-auth, every person's request) and the link's
#: door (the mapped user of a linked office). By container name of THIS deployment, re-read once a minute.
_SIGNIN_HOPS = {"at": 0.0, "addrs": set()}


def _signin_hops():
    import socket
    now = time.time()
    if _SIGNIN_HOPS["at"] and now - _SIGNIN_HOPS["at"] < (60 if _SIGNIN_HOPS["addrs"] else 15):
        return _SIGNIN_HOPS["addrs"]
    dn = os.getenv("DEPLOYMENT_NAME") or "bina-deployment"
    addrs = set()
    for name in (f"traefik-{dn}", f"dgo-net-{dn}", f"dgo-link-{dn}"):
        try:
            addrs |= {str(i[4][0]) for i in socket.getaddrinfo(name, None, proto=socket.IPPROTO_TCP)}
        except OSError:
            continue
    _SIGNIN_HOPS.update(at=now, addrs=addrs)
    return addrs


#: A WSGI environ key only this process can set: a network request reaches the WSGI environ as REMOTE_ADDR,
#: the request line and HTTP_* keys for its headers, never as a key of this name. The link builder
#: (`_frame_answer`, run in-process by link_cli.py) sets it on its own test_client request.
_LINK_BUILDER_MARK = "dgo.console.link_builder"


def _signin_proved():
    """Were THIS request's sign-in headers written by a sign-in hop — traefik (forward-auth, every person's request;
    with the SSO off, traefik writes them itself) or the link's door — or is it the console's own link builder's
    in-process request (the mark above)? The one answer both the forwarding (`_drop_unproved_signin`) and the
    admins' gate (`_is_admin`) take."""
    return (request.remote_addr or "") in _signin_hops() or request.environ.get(_LINK_BUILDER_MARK) is True


def _drop_unproved_signin(fwd):
    """A sign-in header is a fact only when traefik (or the door) wrote it. The console is reachable from
    every container on the office network, and it forwarded whatever headers it was given — so any container
    could call `/a/computers/…/exec` here with its own `X-authentik-username` and be a PERSON to the app
    behind it (DGO-1304, the second reader). From anywhere else, the headers are dropped, not believed —
    except the console's own link builder, whose in-process request carries the mark defined above."""
    if _signin_proved():
        return
    for k in [k for k in fwd if k.lower().startswith("x-authentik-")]:
        fwd.pop(k)


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
        # this office's own sign-in never travels: authentik's cookies, and forward-auth's session and
        # its sign-in state (dgo_session, dgo_state — DGO-1090), which would be a live session here
        kept = [part.strip() for part in cookie.split(";")
                if part.strip() and not part.strip().lower().startswith(
                    ("authentik_", "dgo_session=", "dgo_state=", "__host-dgo_state="))]
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
        # a tile of a linked office that owns its own origin: `/a/<id>/` was never its route, and a
        # person who was handed that link gets the address the shell itself would have opened
        url = _external_redirect(name) if request.method == "GET" else None
        if url:
            return redirect(url, code=302)
    if not base:
        return jsonify(error="unknown_app", app=name), 404
    # past traefik: this door asks who may go through it itself — an admins' app, and (until a linked office says
    # who opens its apps) every app of a linked office, are the office's admins' alone (DGO-1755)
    if (door or _admins_alias(name)) and not _is_admin():
        return _not_for_you()
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
    _drop_unproved_signin(fwd)
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
    # ── THE HISTORY FALLBACK: a path that is a SCREEN is served, one that is not stays a 404 ─────
    # The console's tail IS the app's own URL (`#/m/computers/<id>` arrived as
    # `/a/computers/<id>`), and an app whose server serves its single page only at `/` answers 404
    # for that path — so the screen the link names never loads. Measured 2026-10-12: twelve of this
    # office's fifteen embedded apps do exactly that (drive serves the paths its router knows and
    # 404s the rest; `my-docs` and `incoming` serve anything; the hash-routed ones never see a path
    # at all). The standard fix is the one every SPA framework ships — connect-history-api-fallback:
    # a GET that a BROWSER asked for as a page, whose last segment has no file extension, is
    # answered with the app's entry document instead of an error. It lives HERE, once, rather than
    # in fifteen servers, and it is what makes "the path is always the full path" true for an app
    # that only knows how to be a directory of files.
    #
    # `out`/`ct` are assigned BEFORE this branch and re-assigned inside it, on purpose: an earlier
    # version of this change assigned them only in the fallback, so every OTHER proxied request died
    # with UnboundLocalError — the console answered 500 for the whole office and GlitchTip raised it
    # as the newest alert within the minute (measured 2026-10-12 22:16, notification 3205861). The
    # two lines above are the fix, and they are why the assignment stays where the original was.
    # …unless the app MEANS its error and says so (`X-Bina-Final: 1`): then its answer is the page, exactly
    # as it gave it — no fallback here and no card below. A site the office serves under `/a/sites/public/
    # <id>/` answers a missing page with the site's own 404, and the fallback put the Sites app itself in
    # the site's frame, with 200 (measured on Exampleu, 2026-11-09, DGO-1591).
    final = r.headers.get("X-Bina-Final") == "1"
    if (r.status_code == 404 and asked_for_a_page and request.method == "GET" and not final
            and "." not in (sub or "").rsplit("/", 1)[-1]):
        r.close()
        try:
            r = requests.request("GET", base.rstrip("/") + "/", headers=fwd,
                                 timeout=40, stream=True, allow_redirects=False)
        except requests.RequestException as e:
            return jsonify(error="app_unreachable", app=name, message=str(e)), 502
        out = {k: v for k, v in r.headers.items() if k.lower() not in _HOP}
        out["X-Bina-History-Fallback"] = "1"
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
    if door and not final and asked_for_a_page and r.status_code >= 400 and "text/html" not in ct:
        return Response(_remote_asleep(door, "הלשכה ענתה, אבל האפליקציה הזאת לא זמינה בה כרגע.",
                                       raw=str(r.status_code)),
                        status=r.status_code, content_type="text/html; charset=utf-8")
    if not door and not final and asked_for_a_page and r.status_code >= 400 and "text/html" not in ct:
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
        html = _inject_lang(html)            # the office's language (DGO-971)
        _hi = html.lower().find("</head>")   # case-insensitive: injecting before <!DOCTYPE> forces quirks mode
        _css = EMBED_CSS + APP_EMBED_CSS.get(name, "")
        html = (html[:_hi] + _css + html[_hi:]) if _hi >= 0 else _css + html
        out.pop("Content-Length", None)
        # never let the browser cache the rewritten shell HTML — otherwise console-side embed
        # changes (base, asset rewrites, embed CSS) are masked by a stale copy in the iframe.
        out["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return Response(html.encode("utf-8"), status=r.status_code, headers=out)

    # ── asset freshness (2026-10-11) ──────────────────────────────────────────────────────────────
    # A JS or CSS file a framed app serves often carries NO Cache-Control at all (only ETag and
    # Last-Modified), and a browser then applies HEURISTIC freshness — so an app whose code was just
    # rebuilt keeps running the PREVIOUS bundle from cache. That is invisible from the server side
    # (the file on disk is new, `curl` gets the new bytes) and it is exactly how a translated screen
    # goes on rendering Hebrew: the runtime that translates it is the cached one. Forcing
    # revalidation here costs a conditional request per asset and returns a 304 while the file is
    # unchanged, so the app keeps its own caching semantics and only loses the heuristics.
    # Only where the app said NOTHING: an explicit policy (a hashed bundle's `immutable`, a `no-store`)
    # is the app's own decision and stays, and a lowercase `cache-control` from the app counts as one
    # (otherwise the response would carry two Cache-Control headers).
    if ("text/event-stream" not in ct and any(t in ct for t in ("javascript", "text/css"))
            and not any(k.lower() == "cache-control" for k in out)):
        out["Cache-Control"] = "no-cache"

    # Everything that is NOT html streams straight through.
    #
    # HTML above must stay buffered — the rewrite needs the whole document. Nothing else does, and
    # buffering everything is what made Server-Sent Events impossible: `r.content` waits for a body
    # to END, and an event-stream never does, so the request hung until the 40s timeout and the
    # browser got a dead connection it then reopened forever. Live updates therefore worked at an
    # app's own origin and silently failed inside the console iframe, which is the surface operators
    # actually use.
    #
    # Streaming the rest keeps a large download (a meeting's recording, chat's conversation export, a
    # document) out of this process's memory — but only in pieces of a BOUNDED size. With
    # `chunk_size=None`, urllib3 reads a body that has a Content-Length with ONE `read(None)`: the
    # whole file, in memory, before the first byte goes out. That is what OOM-killed this worker at
    # its 256M limit five times on EXF (DGO-1231, 10-28..10-30): a 297 MB and a 369 MB meeting mp4
    # served through /a/meet/recordings, each kill at ~250 MB anon. An event-stream is chunked, so
    # it keeps `None` below: each chunk is passed on the moment it arrives.
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
    passed = Response(_passed_on(r), status=r.status_code, headers=out, direct_passthrough=True)
    # A HEAD, 204 or 304 never starts the generator (werkzeug answers it with no body), so its
    # `finally` does not run there; this closes the upstream in that case too. Closing twice is safe.
    passed.call_on_close(r.close)
    return passed


# The most of a proxied body this process holds at once, per request (see the comment above).
PASS_CHUNK = 64 * 1024


def _passed_on(r):
    """The body of `r`, PASS_CHUNK at a time; the upstream is closed when the body ends, fails or
    the client goes away."""
    try:
        yield from r.iter_content(chunk_size=PASS_CHUNK)
    finally:
        r.close()


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


def _referer_app():
    """The alias of the embedded app a request came FROM, or None.

    `Referer: http://<this host>/a/<alias>/…` is a page inside an app's frame — and that is the ONLY
    thing that can say whose a root-level path is. Used for a path the console itself does not serve:
    an app that addresses its own assets from the ROOT of the origin (DSH does: `/plugins/??…`, an
    absolute path, because at its own origin it is the whole site) has no other way to be reached from
    inside its tile. Never crosses hosts — a referer from somewhere else is not this office's page."""
    ref = request.headers.get("Referer") or ""
    m = re.match(r"^https?://([^/]+)/a/([A-Za-z0-9._-]+)(?:/|$)", ref)
    if not m or m.group(1) != request.host:
        return None
    return m.group(2)


# ── /go/<ref>: the ONE link a person is given (DGO-1433, links.py) ─────────────────────────────────
# A PATH, resolved here against this console's own live registry and answered with a 302 to the shell's
# route for it — so it survives any sign-in round trip (a `#` fragment never reaches a server), names the
# thing rather than the mechanism, and opens on every console that has the thing. What does not resolve is
# this console's card, in Hebrew, and never another tile — JSON only to the shell's own frame-link catcher, which asks.
PLANE_WORKSPACE = os.getenv("PLANE_WORKSPACE", "bina")


def _own_office():
    """This office's id — DGO_OFFICE_ID, which the console's compose hands it (the control plane's office record
    carries no id: reconcile.OFFICE_FIELDS) — or "" when the office declares none."""
    own = str(os.getenv("DGO_OFFICE_ID") or "").strip().lower()
    if own:
        return own                     # never a call to the control plane per link (it may be down: 3 s each)
    return str(((_office_record() or {}).get("office") or {}).get("id") or "").strip().lower()


def go_resolve(ref, query=""):
    """`links.resolve` against this console's tiles — the one resolution `/go/` and `/api/links` share."""
    import links
    return links.resolve(ref, query, _tiles(), _own_office(), PLANE_WORKSPACE)


@app.get("/go/", defaults={"ref": ""}, strict_slashes=False)
@app.get("/go/<path:ref>")
def go(ref):
    from flask import redirect
    from html import escape
    hit = go_resolve(ref, request.query_string.decode("latin-1"))
    if request.accept_mimetypes.best_match(["text/html", "application/json"]) == "application/json" \
            and request.accept_mimetypes["application/json"] > request.accept_mimetypes["text/html"]:
        # the shell's own frame-link catcher asks for the route itself (static/app.js `goTo`): it moves its route
        # rather than loading itself again inside an app's frame. One URL, two bodies by Accept: never kept by a cache.
        resp = jsonify(hit)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Vary"] = "Accept"
        return resp, (200 if hit.get("to") else (300 if hit.get("choices") else 404))
    if hit.get("to"):
        resp = redirect(hit["to"], 302)
        resp.headers["Cache-Control"] = "no-store"
        return resp
    # several linked offices run what the link asks for, and this one does not: the choice, each its own link
    picks = "".join(f'<li><a href="{escape(c["go"], quote=True)}" target="_top" dir="ltr">{escape(c["tile"])}</a></li>'
                    for c in hit.get("choices") or [])
    page = _card("הקישור לא נפתח" if not picks else "באיזו לשכה?",
                 "אין כאן מה שהקישור הזה מבקש" if not picks else "הקישור מתאים לכמה לשכות",
                 f'<p>{escape(hit.get("why") or "")}</p>' + (f"<ul>{picks}</ul>" if picks else "")
                 + f'<p>הקישור שנפתח: <code dir="ltr">/go/{escape(ref)}</code></p>'
                 '<p>קישור של הלשכה נראה כך: <code dir="ltr">/go/DGO-1433</code> למשימה, '
                 '<code dir="ltr">/go/meet/&lt;חדר&gt;</code> לפגישה, '
                 '<code dir="ltr">/go/&lt;אפליקציה&gt;.&lt;לשכה&gt;</code> לאפליקציה.</p>')
    return Response(page, status=300 if picks else 404, content_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-store"})


# ── links_check: a link is opened past the sign-in BEFORE anybody is given it (DGO-1433) ────────────────
# No HTTP route: the builder (`bbox console link`, link_cli.py) calls `links_check` IN this container's own
# process (`docker exec … python3 -c 'import app; app.links_check(…)'`), so nothing is exposed — not through the
# edge, not to a caller on the office network, not on a native console's loopback (second reader). The check
# replays what the edge sends AFTER the sign-in, as the person it names (`user`, required — no identity, no
# check), for the frame the shell would load for that link: a tile this console proxies is asked through its own
# `/a/<id>/` (`app_proxy`, in process); a linked office's own-host tile is asked at its door, addressed by the
# tile's own name `<alias>.<office>` (never a field a peer wrote), with the Host the edge's router writes
# (`<alias>.localhost`, link-proxy `route`) — the far door maps the identity as it does for the edge. A redirect
# within the app is followed (three at most) as a browser would; a redirect anywhere else, the door's refusal,
# the console's card, `unknown_app`, a sign-in page or anything not a page is a FAILURE with its sentence — a 302
# to a sign-in never counts (the owner's phone, twice: `/a/bina-claude.hp-laptop/`). What it proves is said
# exactly: the page answered past the gate. That the screen drew is a browser's to prove.


def _judge_page(status, headers, body):
    """(ok, sentence) for what a frame was answered, read as a person's browser would show it."""
    import re as _re
    head = (body or b"")[:4096].decode("utf-8", "replace")
    low = head.lower()
    ctype = str((headers or {}).get("Content-Type") or "")
    if 300 <= int(status or 0) < 400:
        return False, f"האפליקציה ענתה הפניה ({status} אל {(headers or {}).get('Location') or '?'}) — הפניה אינה המסך"
    said = (headers or {}).get("X-Dgo-Door")
    if said:
        return False, f"דלת הקישור ענתה במקום האפליקציה ({status}, {said}): " + _DOOR_SAID.get(said, "הלשכה לא ענתה דרך הקישור.")
    if int(status or 0) != 200:
        return False, f"האפליקציה ענתה {status} ולא את המסך"
    if "text/html" not in ctype.lower():
        return False, f"התשובה אינה דף ({ctype or 'בלי סוג'})"
    if "data-card" in low[:600]:
        return False, "הקונסול הציג את הכרטיס שלו — לאפליקציה אין מסך להציג כרגע"
    if '"unknown_app"' in low or "unknown_app" in low[:200]:
        return False, "הקונסול לא מכיר את האפליקציה (unknown_app)"
    if "/if/flow/" in low or "ak-flow" in low or "<ak-" in low:
        return False, "נפתח דף התחברות ולא האפליקציה"
    m = _re.search(r"<title[^>]*>([^<]{0,120})", head, _re.I)
    title = (m.group(1).strip() if m else "") or "בלי כותרת"
    return True, f"200 · דף ({len(body or b'')} בתים) · «{title}»"


def _same_place(location, prefix):
    """The path a redirect leads to when it stays inside the app (relative, or under `prefix`), else None."""
    loc = str(location or "")
    if loc.startswith("/") and not loc.startswith("//"):
        return loc if (not prefix or loc.startswith(prefix)) else None
    return None


def _frame_answer(tile, inner, user):
    """(ok, sentence, how) — the frame the shell loads for `tile` with `inner`, asked as the edge asks it."""
    tid = str(tile.get("id") or "")
    path = inner if inner.startswith("/") else "/" + inner
    # asked as `user` AMONG THE OFFICE'S ADMINS: the link builder runs in this process (link_cli.py, `docker exec`),
    # never for a browser's request, and this process cannot read another person's groups — so the check is of the
    # frame. Whether a person the owner invited may open an admins' app is the door's own answer (DGO-1755).
    hdrs = {"Accept": "text/html", "X-authentik-username": user, "X-authentik-groups": "admins"}
    local = tid in _app_bases() or tid in _remote_doors()
    alias = str(tile.get("alias") or "")
    if local or (not tile.get("office") and not tile.get("remote") and alias in _app_bases()):
        mount = f"/a/{tid if local else alias}"
        asked = mount + path
        for _hop in range(4):
            # in-process, so its address is 127.0.0.1 — not a sign-in hop — and the /a/ proxy would drop the
            # identity this check is asked as; the WSGI mark (no network caller can set one) keeps it (DGO-1792)
            r = app.test_client().get(asked, headers=hdrs, environ_base={_LINK_BUILDER_MARK: True})
            nxt = _same_place(r.headers.get("Location"), mount + "/") if 300 <= r.status_code < 400 else None
            if not nxt:
                break
            asked = nxt
        ok, said = _judge_page(r.status_code, r.headers, r.get_data())
        return ok, said, f"{asked} (דרך הקונסול)"
    office = str(tile.get("office") or (tile.get("remote") or {}).get("office") or "")
    if not office or not tid.endswith("." + office):
        return False, "אין לקונסול הזה דרך לפתוח את המסך הזה מעבר להתחברות — הקישור לא נבדק ולכן לא ניתן", tid
    far = tid[: -len(office) - 1]
    try:
        with open(os.path.join(GENERATED, f"remote.{office}.{far}.json"), encoding="utf-8") as f:
            port = int(json.load(f).get("link_port") or 0)
    except (OSError, ValueError, TypeError):
        port = 0
    if not port:
        return False, f"לא נמצאה הדלת של {office} לאפליקציה הזאת בלשכה הזאת", f"{tid} (דלת)"
    base = f"http://{tid}:{port}"            # the tile's own name — the network alias the link's door answers on
    asked = path
    # inside a recheck pass, the door's cookies are kept for the pass (_PASS_JARS): signed in once per door and person
    jar = None if _PASS_JARS is None else _PASS_JARS.setdefault((base, user), requests.cookies.RequestsCookieJar())
    for _hop in range(4):
        try:
            r = requests.get(base + asked, headers={**hdrs, "Host": f"{far}.localhost"}, timeout=25,
                             allow_redirects=False, **({} if jar is None else {"cookies": jar}))
        except requests.RequestException as e:
            app.logger.warning("links check: %s did not answer (%s)", base + asked, type(e).__name__)
            return False, f"הדלת של {office} לא ענתה — הלשכה כבויה, מנותקת, או שהקישור אליה נפל", base + asked
        if jar is not None:
            for c in r.cookies:      # sent back to this door over its internal http, so a Secure mark is dropped here
                c.secure = False
                jar.set_cookie(c)
        nxt = _same_place(r.headers.get("Location"), "") if 300 <= r.status_code < 400 else None
        if not nxt:
            break
        asked = nxt
    ok, said = _judge_page(r.status_code, r.headers, r.content)
    return ok, said, f"{base}{asked} (Host {far}.localhost)"


def _checked_path(hit):
    """The `/go/` link exactly as it was checked — its inner route and query included (second reader: the builder
    handed out the app's home while it had checked a screen inside it)."""
    to, tid, kind = hit["to"], hit["tile"], hit.get("kind")
    if kind == "item":
        return "/go/" + hit["ref"] + to.split(f"/browse/{hit['ref']}/", 1)[1]
    if kind == "meeting":
        return "/go/meet/" + to.split("/flow/", 1)[1]
    return "/go/" + tid + to[len(f"/#/m/{tid}"):]


def links_check(ref, user, query=""):
    """Resolve `ref` as `/go/` does, then open its frame past the sign-in as `user`. `ok` only when the page answered;
    `path` is the link that was checked. Called in this process only (link_cli.py) — never over HTTP."""
    hit = go_resolve(ref, query)
    canon = hit.get("ref") or str(ref or "").strip("/")
    out = {"ref": canon, "path": f"/go/{canon}", "kind": hit.get("kind") or "", "at": int(time.time())}
    if not str(user or "").strip():
        return {**out, "ok": False, "why": "בלי זהות אין בדיקה — הקישור נבדק כמו שהוא נפתח לאדם מסוים"}
    if not hit.get("to"):
        return {**out, "ok": False, "why": hit.get("why") or "הקישור לא נפתר",
                **({"choices": hit["choices"]} if hit.get("choices") else {})}
    out.update(opens=hit["to"], tile=hit["tile"], path=_checked_path(hit), user=str(user).strip())
    tile = next((m for m in _modules() if m.get("id") == hit["tile"]), None)
    if tile is None:
        return {**out, "ok": False, "why": "המסך נעלם מהלשכה בזמן הבדיקה"}
    inner = hit["to"][len(f"/#/m/{hit['tile']}"):]
    ok, said, how = _frame_answer(tile, inner, str(user).strip())
    out["checks"] = [{"what": how, "ok": ok, "said": said}]
    return {**out, "ok": ok, **({} if ok else {"why": said})}


# ── the ledger: every link a person was given, opened again every 15 minutes (DGO-1433) ─────────────────
# A link is a record: what was given, to whom, as whom it was opened, when, and every time it was opened again —
# one line each, appended, never edited (LINKS_DIR, the console's own volume). `bbox console link` records a link
# only after links_check passed; the console opens every link given again every LINKS_RECHECK_SECONDS (gunicorn's
# one worker starts the loop, gunicorn.conf.py), and a link that STOPPED opening is a notice in the office's
# notifications, with the sentence why — before the owner meets it; one that came back closes it.
LINKS_DIR = os.getenv("LINKS_DIR", "/app/links")
LINKS_RECHECK_SECONDS = int(os.getenv("LINKS_RECHECK_SECONDS", "900") or 0)
LINKS_RECHECK_DAYS = int(os.getenv("LINKS_RECHECK_DAYS", "14") or 0)    # a link given longer ago is not opened again
LINKS_NOTIFY_URL = os.getenv("LINKS_NOTIFY_URL", "http://notifications:8977/api/notifications")
_DAY = 86400
# {(door, user): cookie jar} while a recheck pass runs, else None: a door that signs a person in on every request
# without a cookie (the HP's Plane: office_identity.py) minted a session per link and per hop, 96 times a day for
# every link — the pattern of the 972k-session jam. One pass signs in once per door (second reader, DGO-1433).
_PASS_JARS = None


def _num(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _ledger_path():
    return os.path.join(LINKS_DIR, "ledger.jsonl")


def links_record(row):
    """One line of the ledger, appended under a lock (the builder's process and the loop write it)."""
    import fcntl
    os.makedirs(LINKS_DIR, exist_ok=True)
    with open(_ledger_path(), "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def links_given():
    """{path: what the ledger knows of each link GIVEN — its last verdict on top}."""
    out = {}
    try:
        with open(_ledger_path(), encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and str(row.get("path") or "").startswith("/go/"):
                    out.setdefault(row["path"], {}).update({k: v for k, v in row.items() if v is not None})
    except OSError:
        return {}
    return {p: r for p, r in out.items() if r.get("given_at")}


def _links_notice(row, ok, said):
    """The office's notice for a link that stopped opening (error) or came back (info) — one per link, updated.
    True only when the notifications app took it: a refusal or a stopped app is said again on the next pass."""
    link = row.get("link") or row.get("path")
    body = f"הקישור {link} " + ("נפתח שוב." if ok else f"הפסיק להיפתח: {said}. הוא ייבדק שוב בעוד רבע שעה.")
    try:
        r = requests.post(LINKS_NOTIFY_URL, json={
            "source": "links", "source_id": row.get("path"), "level": "info" if ok else "error",
            "title": "קישור שנשלח חזר להיפתח" if ok else "קישור שנשלח הפסיק להיפתח", "body": body,
            "link": row.get("path")}, timeout=10)
    except requests.RequestException as e:
        app.logger.warning("links recheck: the notice for %s was not written (%s)", row.get("path"), type(e).__name__)
        return False
    if not r.ok:
        app.logger.warning("links recheck: the notice for %s was refused (%s)", row.get("path"), r.status_code)
    return bool(r.ok)


def links_recheck():
    """Open again every link given in the last LINKS_RECHECK_DAYS, as the person it was opened as, and say a CHANGE.

    A change is against what the owner was last TOLD — the row's `noticed`, and a link given is told as opening —
    and it is written as told only once the notifications app took it: a notice that failed is said again, and one
    left up for a link given again is closed (second reader). A check line is written when the verdict changes, for
    the first check after a link is given, and once a day — not 96 lines a day for every link ever given. One link
    whose check raises is a verdict of its own, never the end of the pass for the links after it."""
    global _PASS_JARS
    now = int(time.time())
    seen = []
    _PASS_JARS = {}
    try:
        for path, row in sorted(links_given().items()):
            # older than the window: not opened again — unless the owner was last told it is broken, which stays
            # checked until the notice that it opens again is said (second reader: it stayed up forever)
            if LINKS_RECHECK_DAYS > 0 and now - _num(row.get("given_at")) > LINKS_RECHECK_DAYS * _DAY \
                    and bool(row.get("noticed", True)):
                continue
            ref, _, query = path[len("/go/"):].partition("?")
            try:
                out = links_check(ref, row.get("as") or "", query)
            except Exception as e:                      # noqa: BLE001 — one link's check never stops the others
                app.logger.warning("links recheck: the check of %s failed (%s)", path, type(e).__name__)
                out = {"ok": False, "why": "הבדיקה עצמה נכשלה — היא תרוץ שוב בעוד רבע שעה"}
            ok = bool(out.get("ok"))
            said = out.get("why") or "; ".join(c.get("said", "") for c in out.get("checks") or [])
            at = _num(out.get("at")) or now
            line = {"path": path, "link": row.get("link"), "checked_at": at, "ok": ok, "said": said}
            if ok != bool(row.get("noticed", True)) and _links_notice(row, ok, said):
                line["noticed"] = ok
            last = _num(row.get("checked_at"))
            if ok != bool(row.get("ok", True)) or "noticed" in line or last <= _num(row.get("given_at")) \
                    or at - last >= _DAY:
                links_record(line)
            seen.append({"path": path, "link": row.get("link"), "ok": ok, "said": said})
    finally:
        _PASS_JARS = None
    return seen


def start_links_recheck():
    """The loop, in the server only (gunicorn.conf.py `post_worker_init`): never in a process that imports this file."""
    import threading
    if LINKS_RECHECK_SECONDS <= 0 or getattr(start_links_recheck, "started", False):
        return
    start_links_recheck.started = True

    def loop():
        while True:
            time.sleep(LINKS_RECHECK_SECONDS)
            try:
                links_recheck()
            except Exception as e:                      # noqa: BLE001 — the loop outlives one bad pass
                app.logger.warning("links recheck: the pass failed (%s)", type(e).__name__)
    threading.Thread(target=loop, daemon=True, name="links-recheck").start()


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
    # A PATH THE CONSOLE DOES NOT OWN, ASKED FOR BY A PAGE INSIDE AN APP, IS THAT APP'S. This is the
    # standard rule for an app mounted under a prefix that still speaks from the root, and here it is
    # what makes the harness work inside its tile: DSH addresses its client bundles as
    # `/plugins/??@scope/pkg/client.js,…` (an absolute path). The catch-all answered that with
    # index.html, the browser evaluated HTML as JavaScript ("Unexpected token '<'"), the harness said
    # «Failed to load plugins», and — because `office-links` is one of those bundles — a link inside
    # the chat opened a NEW TAB instead of moving the desktop (measured 2026-10-13, ui2-060).
    # `app_proxy` rebuilds the upstream URL byte for byte, including the literal second `?` of the
    # specifier list (see its own note); nothing here re-encodes it.
    if not os.path.isfile(full):
        owner = _referer_app()
        if owner and (owner in _app_bases() or owner in _remote_doors()):
            return app_proxy(owner, p)
    g.shell_file = True                         # the shell's own file: revalidated after compression (DGO-611)
    resp = send_from_directory(STATIC, p) if os.path.isfile(full) \
        else send_from_directory(STATIC, "index.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


if __name__ == "__main__":
    app.run("0.0.0.0", int(os.getenv("PORT", "8000")))
