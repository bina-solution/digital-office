"""drive — THE drive platform service (contract: ai/context/platform-service-contract.md).

The office's one file layer: people drop files into it from the console, apps write into it
(meeting recordings into «פגישות», the recorder into «הקלטות»), and agents read what is there by
path. It is the GENERIC app of its kind (DGO-1500, apps/drive/ENGINES.md): every drive is an account
of an ENGINE — `drive-local` (the office's own storage, kind engine) or `drive-google` (Google Drive,
kind external) — found by name and asked over drive-engine.v1 (engines.py). This file holds no
engine's code: no database, no storage client, no Google. Three planes, one service:
  * the ENGINE plane — the engines' own. `drive_local` has N PROFILES (identities holding a key,
    declared in drive-local's app.json or made in «ניהול פרופילים»); its `/engine/*` routes and the
    share links `/file/d/*` are handed to it verbatim (`routes` in its /ops).
  * the CONNECTION plane (§2) — every drive of every engine is an ordinary vault instance.
    The BINDING (which one this drive acts as) lives here, as a {scope -> id} map.
  * the OP plane — every op runs through the account's engine (engines.RemoteAdapter). The UI plane
    (`/api/*`, the SSO-gated browser) runs on the account the operator selected — the BOUND profile.
    The §3 CANONICAL OPS (`/list /download /upload /move /update /delete /createFromText`, what
    n8n's driveApi01 calls) never fall back to the binding: `connection_id`/`profile_id` is
    REQUIRED on every one of them (see `_explicit_connection_required`).

BYTES IN: `/api/uploads` is a resumable (tus 1.0) session per file — pieces of a few MB, so memory
stays flat for any size and a dropped connection resumes (uploads.py). `/api/upload` (one multipart
request) remains for small files and streams each part from its spooled temp file. BYTES OUT:
streamed with Range; a user's file is served inline only when it is a type that cannot run anything
(media.serve_headers), so a stored .html or .svg can never act with the viewer's session.

AUTHORIZATION. Three rings (data / self / admin) on the office storage's profiles, checked by its
engine (drive-local) and enforced in its QUERIES. The ACTING profile is the one whose credential the
request presents (`X-Drive-Profile-Key`), passed to the engine with every call. When no credential is
presented the request is the SSO-gated browser UI, and it acts as the BOUND profile — platform users
are explicitly out of scope (profiles-and-engines.md §7), so the SSO session is the authentication and
the binding is the identity.
"""
import hashlib
import os
import secrets
import subprocess
import tempfile
import urllib.parse
from json import loads as json_loads

import requests
from flask import Flask, Response, jsonify, request, send_from_directory

import connections_client as cx
import engines
import extensions
import uploads
from engines import AdapterError, AuthError, ProfileError

# ── the fourth channel: what this app did, on `dgo:flow:drive` (flow.v1, DGO-1402) ────────────────
# Through the office's ONE publisher, platform-base/redis/flowpub.py, mounted read-only at /opt/dgo
# (docker-compose.yml): «כל מקביל» draws it as the row «דרייב» and agents hear it (`./bbox drive flow`).
# What goes out is what happened and how big — never a file's NAME (a person's content, the contract's
# rule). An image run without the mount publishes nothing and works the same.
import contextlib
import sys

sys.path.insert(0, "/opt/dgo")
try:
    import flowpub
except ImportError:
    flowpub = None


# The event's own two words are positional-only (`/`): what follows is the event's DATA, and a data key may
# be any word — `_upload_span` says the file's `kind`, and with `kind` a parameter here that call raised
# «got multiple values for argument 'kind'», which turned every upload into «שמירת הקובץ נכשלה» (ed670506).
def _flow(type_, title, /, **data):
    if flowpub is not None:
        flowpub.emit("drive", type_, title, data)


def _flow_span(kind, title, /, **data):
    return flowpub.span("drive", kind, title, data) if flowpub is not None else contextlib.nullcontext()


def _upload_span(name, mime, size):
    """A PERSON's upload as one bar — called on the two upload doors (the multipart form and a finished
    resumable session), NOT in `_store`: the office's backup writes every object through that too (restic,
    PUT /api/fs/content), and a night's packs would push every upload out of the stream (the second reader)."""
    kind = _kind_of(name, mime)
    return _flow_span("file.upload", f"העלאת קובץ {kind} ({max(1, int(size or 0) // 1024)} KB)", size=size, kind=kind)


def _kind_of(name, mime) -> str:
    """What sort of file, without its name: the extension, or the MIME type's major half."""
    ext = os.path.splitext(str(name or ""))[1].lstrip(".").lower()
    return ext[:8] if ext.isalnum() else (str(mime or "").split("/")[0] or "file")

# ── Sentry/GlitchTip error reporting (platform standard) ──────────────────────────
# Wired declaratively: glitchtip-push mints this service's project + deterministic DSN into
# DRIVE_SENTRY_DSN in .env; compose maps it to SENTRY_DSN. No-op if unset.
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

app = Flask(__name__, static_folder="static", static_url_path="")


class _Surfaces:
    """«הקלטות» is this same service under /rec — its tile points there, so its page, its scripts
    and its API calls arrive with that prefix. The prefix is dropped and the surface remembered:
    every route serves both apps as one, and the page is told which one it is."""

    def __init__(self, wsgi):
        self.wsgi = wsgi

    def __call__(self, environ, start_response):
        p = environ.get("PATH_INFO") or ""
        if p == "/rec" or p.startswith("/rec/"):
            environ["PATH_INFO"] = p[4:] or "/"
            environ["drive.surface"] = "recorder"
        return self.wsgi(environ, start_response)


app.wsgi_app = _Surfaces(app.wsgi_app)
# One multipart request may carry a file up to the upload ceiling (bigger files go through
# /api/uploads in pieces, which never parse a form at all).
app.config["MAX_CONTENT_LENGTH"] = uploads.MAX_SIZE + 16 * 1024 * 1024

PROFILE_KEY_HEADER = engines.PROFILE_KEY_HEADER
TUS = {"Tus-Resumable": "1.0.0"}
ENGINE_BODY_LIMIT = 1024 * 1024
# The office storage's schema and its profile reconciler run in ITS engine (apps/drive-local), which
# owns the database; nothing is provisioned here.


@app.before_request
def _engine_routes():
    """What an engine keeps for itself is handed to it verbatim, by the path prefixes its /ops names:
    drive-local's profile plane (`/engine/`) and its share links (`/file/d/`). No prefix is written here."""
    path = request.path
    if path.startswith(("/api/", "/oauth/", "/vendor/", "/js/", "/connections")) or path in ("/", "/healthz", "/readyz", "/manifest"):
        return None
    # a path that climbs (`/file/d/%2e%2e/…/engine/…`) is never handed over: the share links' router has no
    # sign-in, and a climb out of its prefix would reach another one (the second reader, DGO-1500)
    raw = request.environ.get("RAW_URI") or request.environ.get("REQUEST_URI") or ""
    segs = path.split("/") + urllib.parse.unquote(raw.split("?", 1)[0]).split("/")
    if any(s in (".", "..") for s in segs) or "\\" in path:
        return jsonify({"error": "נתיב לא תקין"}), 400
    for prefix, eid in engines.routes():
        if path.startswith(prefix):
            return _hand_over(eid)
    return None


def _hand_over(eid):
    """The request, as it came, to the engine that owns its prefix. Without a key the engine asks this app
    which drive is bound (GET /connections/active) — nothing a caller sends can name the profile it acts as."""
    if request.content_length:
        body = (request.stream, request.content_length)
    elif request.path.startswith("/engine/") and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        # a chunked body (no length) is read here — the profile plane's small JSON, capped: never a body
        # anyone without a sign-in could make this process hold (the share links take none at all)
        body = request.stream.read(ENGINE_BODY_LIMIT + 1)
        if len(body) > ENGINE_BODY_LIMIT:
            return jsonify({"error": "הבקשה גדולה מדי"}), 413
    else:
        body = b""
    status, out, chunks = engines.proxy(eid, request.path, request.method, request.args.to_dict(flat=False),
                                        dict(request.headers.items()), body)
    if request.method != "GET" and request.path.startswith("/engine/"):
        # a profile made, changed or removed: the drives' list and the default may have moved with it
        body = b"".join(chunks)
        engines.invalidate()
        cx.forget_default()
        if request.method == "DELETE" and 200 <= status < 300:
            try:
                gone = (json_loads(body) or {}).get("removed_connection")
            except ValueError:
                gone = None
            if gone and cx.active() == gone:
                cx.unbind()             # fall back to the default rather than a drive that is gone
        return Response(body, status=status, headers=out)
    return Response(chunks, status=status, headers=out, direct_passthrough=True)


# Retire what the deleted bootstrap shim registered (keyed on a marker only the shim wrote, so an
# app's own registration is untouched). See extensions.retire_bootstrap.
try:
    _retired = extensions.retire_bootstrap()
    if _retired:
        print(f"[drive] retired {_retired} bootstrap extension(s)", flush=True)
except Exception as _e:            # a read-only/corrupt /data must not stop the drive from serving
    print("[drive] bootstrap retirement skipped:", _e, flush=True)


@app.after_request
def _cache_assets(resp):
    """Vendored viewer libraries are versioned by their directory name and never change in place."""
    if request.path.startswith("/vendor/") and resp.status_code == 200:
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


# ── op plumbing: every op resolves an adapter first ───────────────────────────────
def _body():
    if request.is_json:
        return request.get_json(silent=True) or {}
    return {}


def _override(body=True):
    """(profile_id, connection_id) for this call (§2).

    Two spellings of one idea, because the two callers think in different nouns: automation names a
    CONNECTION (it holds ids), the profile UI names a PROFILE. Both land on the same choke point.

    `body=False` is for a route whose body IS a file (PUT /api/fs/content): its drive is named in the
    address only. Parsing a file as a form or as JSON would eat it (or answer 413 over Flask's form-memory
    limit), and a file's own `connection_id` must never choose the drive it is written to (DGO-2042).
    """
    b = _body() if body else {}
    cid = (request.args.get("connection_id") or b.get("connection_id")
           or (request.form.get("connection_id") if body else None))
    pid = (request.args.get("profile_id") or b.get("profile_id")
           or (request.form.get("profile_id") if body else None))
    return pid or None, cid or None


def _explicit_connection_required():
    """Raise the actionable 400 for an automation call that named no identity at all (§3).

    2026-08-06 INCIDENT: a missing `profile_id`/`connection_id` used to resolve SILENTLY to
    whatever this deployment's connection bar happens to be bound to — which is a per-console,
    human, ambient choice, not an identity an automated caller ever declared. On that host the
    binding was a Google SERVICE ACCOUNT (no personal storage, every write refused by Google), and
    three independent things broke from the one cause: mail registries without `drive_profile_id`
    quarantined every deposit, demo-injection nodes would have written the owner's real client
    Drive, and 16 `driveApi01` call sites across 5 E2E suites killed 6 of 8 suites with 503s while
    the survivors silently searched the wrong backend.

    So the §3 CANONICAL OPS refuse loudly, naming what was missing and every connection the caller
    could have named instead. This does NOT apply to the UI plane (`/api/*`): the browser SPA behind
    SSO has no other identity to declare. Reads are refused exactly like writes — a list against the
    wrong backend returns wrong or empty results an unattended pipeline acts on as ground truth.
    No staged rollout: the callers it refuses (G46, `scripts/refactor/drive-connection-lint.py`)
    were already silently wrong, and a loud 400 is the fastest route to someone fixing them.
    """
    conns = cx.list_instances()
    if conns:
        rows = "\n".join(
            f"    - connection_id={c.get('id')!r}"
            + (f"  profile_id={c.get('profile_id')!r}" if c.get("profile_id") else "")
            + f"  ({c.get('protocol')}, {c.get('label')})"
            for c in conns)
    else:
        rows = "    (none configured — create one first via POST /connections or /engine/profiles)"
    raise AdapterError(
        "drive: this operation requires an explicit `profile_id` or `connection_id` — none was "
        "passed. The deployment's active connection binding is no longer used as an implicit "
        "default for automation calls (it is for the console UI only), so this call would "
        "otherwise silently run against whichever account a human last selected there.\n"
        f"Available connections:\n{rows}\n"
        "Pass one of them as `profile_id` (an engine profile id, e.g. \"admin\") or "
        "`connection_id` (any vault instance id, local or remote) in the request body/params.",
        400,
    )


def _use(require_explicit=False, body=True):
    """(instance, adapter) for this request — and the check that makes a credential a CONSTRAINT
    rather than a second way in.

    A request presenting profile B's key while naming profile A's connection is REFUSED; without
    this, `connection_id` would be a field the caller controls that decides whose files they get.
    A session request (no credential) has no claimed identity to contradict, and it is already
    behind the deployment's forward-auth. `body=False`: the identity is read from the address and
    the headers only, never from the body (see `_override`).
    """
    pid, cid = _override(body)
    if require_explicit and not pid and not cid:
        _explicit_connection_required()
    key = _presented_key(body)
    inst = _resolve_instance(pid, cid)
    if key and not inst.get("is_private"):
        # a key is checked by the engine that issues keys, whatever drive it names: an invalid one is a 401
        _acting(key)
    # the engine of a private drive refuses a key of profile B on profile A's drive (its check_key)
    return inst, engines.for_instance(inst, key)


def _resolve_instance(pid, cid):
    """THE single choke point: the instance an op runs on. Precedence: explicit argument > binding >
    (the default profile, only when NOTHING is bound). A binding that names a missing instance RAISES:
    an op must fail rather than run against a different account than the one selected (see
    connections_client.resolve_active, and the 2026-07-17 incident it is named after)."""
    if pid and not cid:
        inst = _instance_for_profile(pid)
        if not inst:
            raise AdapterError(f"unknown profile {pid!r}", 404)
        return inst
    if cid:
        inst = cx.get_instance(cid)
        if not inst:
            raise AdapterError(f"unknown connection {cid!r}", 404)
        return inst
    inst, reason = cx.resolve_active()
    if reason:
        raise AdapterError(reason, 503)
    return inst


def _instance_for_profile(pid):
    """The instance carrying a profile's key: the office storage's engine names it (its accounts carry
    `profile_id`); a stale id resolves to nothing rather than to a connection that no longer exists."""
    insts, err = cx.vault_instances()
    if err:
        raise AdapterError(f"{err} — לא ניתן למצוא את הפרופיל {pid}", 503)
    private = set(engines.private_protocols())
    rows = [i for i in insts if i.get("protocol") in private]
    mine = [r for r in engines.accounts(rows) if r.get("profile_id") == pid and r.get("profile_status") != "missing"]
    # the profile's own instance (its row's `instance_id`, the authoritative map) before any other that
    # carries the same hint — a second row added by hand or left by a rotation must not win
    hit = next((r for r in mine if r.get("primary")), None) or (mine[0] if mine else None)
    return engines.annotate(hit) if hit else None


def _acting(key=None):
    """Who is acting — {profile, is_admin} — or None. Without a key: the bound drive, as its own engine
    describes the account (its profile's name, admin flag, state), answered here with no call back into this
    app. With a key: the office storage's /engine/whoami, and a key it does not know is a 401 here too."""
    if not key:
        inst, reason = cx.resolve_active()
        if reason or not inst or not inst.get("is_private"):
            return None                 # a binding that does not resolve, or a remote account: no profile acts
        row = next(iter(engines.accounts([inst])), {}) if inst else {}
        if row.get("profile_status") in (None, "missing"):
            return None
        prof = {"id": row.get("profile_id"), "display_name": row.get("label"), "is_admin": bool(row.get("is_admin")),
                "status": row.get("profile_status")}
        return {"ok": True, "profile": prof, "is_admin": prof["is_admin"]}
    eid = engines.private_engine()
    if not eid:
        return None
    hdrs = {PROFILE_KEY_HEADER: key}
    try:
        r = requests.get(engines.url(eid) + "/engine/whoami", headers=hdrs, timeout=(5, 15))
        doc = r.json()
    except (requests.RequestException, ValueError, AdapterError):
        return None
    if r.status_code == 401:
        raise ProfileError(doc.get("error") or "מפתח הפרופיל אינו תקף", 401)
    return doc if isinstance(doc, dict) and doc.get("ok") else None


def _need(ad, method, what):
    """The adapter's method, or a 501 that names what this connection cannot do."""
    fn = getattr(ad, method, None)
    if not callable(fn):
        raise AdapterError(f"החיבור הזה אינו תומך ב{what}", 501)
    return fn


@app.errorhandler(AdapterError)
def _adapter_error(e):
    return jsonify({"error": e.message}), e.status


@app.errorhandler(ProfileError)
def _profile_error(e):
    return jsonify({"error": e.message}), e.status


@app.errorhandler(uploads.UploadError)
def _upload_error(e):
    hdrs = dict(TUS)
    if e.offset is not None:
        hdrs["Upload-Offset"] = str(e.offset)
    return jsonify({"error": e.message, "offset": e.offset}), e.status, hdrs


@app.errorhandler(413)
def _too_large(_e):
    return jsonify({"error": f"הקובץ גדול מהמותר ({uploads.MAX_SIZE // 1024 ** 2} MB)"}), 413


@app.errorhandler(500)
def _crashed(e):
    """Never Flask's HTML page: the page reads JSON, and under the console an HTML body is taken
    for a screen. The cause stays in the log (Flask already wrote the traceback)."""
    return jsonify({"error": "שגיאה פנימית בדרייב — הפעולה לא בוצעה"}), 500


@app.errorhandler(AuthError)
def _google_error(e):
    # 503, not 500: the connection is unusable, the service is fine. A MISSING FILE carries the
    # status Google returned (404/410), so a caller can tell "retry later" from "never exists".
    return jsonify({"error": str(e), "connection_id": cx.active()}), getattr(e, "status", 503)


def _ids(b):
    """Every mutation accepts a single id or a bulk ids[] — one consolidated shape."""
    return [i for i in (b.get("ids") or ([b["id"]] if b.get("id") else [])) if i]


# ── the rings ─────────────────────────────────────────────────────────────────────
def _presented_key(body=True):
    """The credential on this request, or None. NEVER read from the query string: a secret in a URL
    ends up in access logs, referrer headers and browser history. `body=False`: headers only — a
    file's own `profile_key` is not a credential (DGO-2042)."""
    direct = request.headers.get(PROFILE_KEY_HEADER)
    if direct:
        return direct.strip()
    auth = request.headers.get("Authorization") or ""
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    return ((_body().get("profile_key") or "").strip() or None) if body else None


def acting_profile():
    """Who is making this request, as the office storage's engine says (its /engine/whoami): a presented
    credential is authoritative; without one the browser UI behind authentik acts as the bound profile.
    None when the binding is a remote account or the engine does not answer."""
    who = _acting(_presented_key())
    return (who or {}).get("profile")


# ── SPA ───────────────────────────────────────────────────────────────────────────
@app.get("/")
@app.get("/files")
@app.get("/trash")
@app.get("/search")
@app.get("/folder/<path:_rest>")
@app.get("/open/<path:_rest>")
@app.get("/p/<path:_rest>")
def index(_rest=None):
    """SPA entry — every screen is a URL (deep-linkable, back/forward-able):
    /folder/<id>[/file/<fid>]   a folder, optionally with a file open in the viewer
    /open/<fid>                 a file open in the viewer, wherever it lives
    /trash · /search?q= · /p/<place> (recent, starred).
    Under /rec the same page opens as «הקלטות» (data-surface on <html>, its own title)."""
    if request.environ.get("drive.surface") == "recorder":
        with open(os.path.join(app.static_folder, "index.html"), encoding="utf-8") as f:
            page = f.read()
        page = page.replace('<html lang="he" dir="rtl">', '<html lang="he" dir="rtl" data-surface="recorder">', 1)                    .replace("<title>קבצים</title>", "<title>הקלטות</title>", 1)
        return Response(page, mimetype="text/html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    return send_from_directory("static", "index.html")


# ── the UI plane — all through the BOUND profile ──────────────────────────────────
def _local(ad):
    """Is this a private engine's drive — one whose bytes sit in this office's storage? Upload sessions
    are then the profile's own; a Google account's are the connection's."""
    return bool(getattr(ad, "private", False))


def _drive_of(inst, ad):
    """What the screen needs to know about the drive it is showing, beside its folders: which drive it
    is, and what this drive can do — so a place it cannot answer is not offered."""
    ops = engines.ops_for(ad)
    return {"id": inst.get("id"), "protocol": inst.get("protocol"), "label": inst.get("label"),
            "account_hint": inst.get("account_hint"),
            "profile_id": inst.get("profile_id"), "is_private": inst.get("is_private"),
            "views": engines.views_for(ad), "optional_ops": ops["optional_ops"],
            "media": callable(getattr(ad, "media_files", None)),
            "creates": not getattr(ad, "_SA_NO_CREATE", None)}


@app.get("/api/folders")
def api_folders():
    inst, ad = _use()
    return jsonify({"folders": ad.folders(), "connection": _drive_of(inst, ad)})


@app.get("/api/files")
def api_files():
    """A folder's files (`folder=`), a system view (`view=recent|starred` — only the views the
    adapter answers), or the trash (`trash=1`, with the folders trashed on their own).
    `created_after` (RFC3339) is the sync-discovery bound; `limit`/`offset` page a long folder."""
    _, ad = _use()
    view = (request.args.get("view") or "").strip().lower()
    trash = request.args.get("trash") == "1"
    kw = {"created_after": (request.args.get("created_after") or "").strip() or None}
    if callable(getattr(ad, "trashed_folders", None)):
        kw.update(limit=request.args.get("limit") or 1000, offset=request.args.get("offset") or 0)
    folders = []
    if view and view in engines.views_for(ad):
        files = ad.files(request.args.get("folder", ""), trash, view=view, **kw)
        if view == "shared" and callable(getattr(ad, "shared_folders", None)):
            folders = ad.shared_folders()
    else:
        files = ad.files(request.args.get("folder", ""), trash, **kw)
        if trash and callable(getattr(ad, "trashed_folders", None)):
            folders = ad.trashed_folders()
    return jsonify({"files": files, "folders": folders, "view": view})


@app.get("/api/file/<fid>")
def api_file(fid):
    """One file's metadata, with the path an agent would use to name it."""
    _, ad = _use()
    item = _need(ad, "_file", "פרטי קובץ")(fid)
    if not item:
        return jsonify({"error": "הקובץ אינו קיים"}), 404
    if callable(getattr(ad, "path_of", None)):
        folder_path = ad.path_of(item["folder"])
        item["path"] = folder_path.rstrip("/") + "/" + item["name"]
    return jsonify({"file": item})


@app.get("/api/media")
def api_media():
    """Photos and videos (`kind=visual`), videos or audio from every folder, with what is known about
    each (size in pixels, duration, title…). What is not known yet is found out in the background,
    one file at a time; the page asks again on its next refresh."""
    _, ad = _use()
    kind = (request.args.get("kind") or "visual").strip().lower()
    # the engine that holds the bytes starts finding out what it does not know yet (drive-local)
    return jsonify({"files": _need(ad, "media_files", "תצוגות מדיה")(kind)})


@app.get("/api/file/<fid>/thumb")
def api_file_thumb(fid):
    """The file's picture (webp) at about `s` pixels; 404 when it has none. Kept for a week in the
    browser: a file's bytes never change under its id."""
    _, ad = _use()
    item = _need(ad, "_file", "תמונות ממוזערות")(fid)
    if not item:
        return jsonify({"error": "הקובץ אינו קיים"}), 404
    # each engine draws its own pictures: drive-local from its storage, Google its thumbnail
    got = ad.thumb(item, request.args.get("s") or 256) if callable(getattr(ad, "thumb", None)) else None
    data, mime = got if got else (None, "image/webp")
    if not data:
        return jsonify({"error": "אין תמונה לקובץ הזה"}), 404
    return Response(data, mimetype=mime,
                    headers={"Cache-Control": "private, max-age=604800, immutable", "X-Content-Type-Options": "nosniff"})


@app.get("/api/file/<fid>/peaks")
def api_file_peaks(fid):
    """An audio file's waveform — 600 loudness values between 0 and 1."""
    _, ad = _use()
    if not callable(getattr(ad, "peaks", None)):   # measured only by an engine that holds the bytes
        return jsonify({"error": "אין גל קול לקובץ הזה"}), 404, {"Cache-Control": "no-store"}
    cached = bool(request.args.get("cached"))
    # a list asks without starting the work (`cached`): the engine's background job measures it
    vals = ad.peaks(fid, cached=cached)
    if not vals and cached:
        return jsonify({"error": "גל הקול עוד לא נמדד"}), 404, {"Cache-Control": "no-store"}
    if not vals:
        return jsonify({"error": "אין גל קול לקובץ הזה"}), 404
    return jsonify({"peaks": vals}), 200, {"Cache-Control": "private, max-age=604800, immutable"}


def _build_id():
    """What the page is made of (its own files, not the versioned libraries): a deploy changes it, and a
    window that has been open since before the deploy sees it change and offers a refresh."""
    h, root = hashlib.md5(), app.static_folder
    for dp, dn, fn in os.walk(root):
        dn[:] = sorted(d for d in dn if d != "vendor")
        for name in sorted(fn):
            try:
                with open(os.path.join(dp, name), "rb") as f:
                    h.update(name.encode() + f.read())
            except OSError:
                pass
    return h.hexdigest()[:12]


BUILD = _build_id()


@app.get("/api/changes")
def api_changes():
    """One number that moves when anything this profile sees changes (the page's live refresh) — and
    the page's own build, so an open window knows when it is older than the server."""
    _, ad = _use()
    fn = getattr(ad, "changes_rev", None)
    return jsonify({"rev": fn() if callable(fn) else None, "build": BUILD})


@app.get("/api/folder/<fid>/path")
def api_folder_path(fid):
    _, ad = _use()
    return jsonify({"id": fid, "path": _need(ad, "path_of", "נתיבים")(fid)})


@app.post("/api/star")
def api_star():
    """Flag/unflag files and folders. Body: {id|ids, starred?:bool}. Idempotent."""
    b = request.get_json(silent=True) or {}
    ids = _ids(b)
    if not ids:
        return jsonify({"error": "id or ids required"}), 400
    _, ad = _use()
    if "star" not in engines.ops_for(ad)["optional_ops"]:
        return jsonify({"error": "החיבור הזה אינו תומך בסימון בכוכב"}), 501
    return jsonify(ad.star(ids, bool(b.get("starred", True))))


@app.get("/api/storage")
def api_storage():
    """Bytes used by THIS profile, file count, the trash's share, and a ceiling only if configured."""
    _, ad = _use()
    if "storage" not in engines.ops_for(ad)["optional_ops"]:
        return jsonify({"error": "החיבור הזה אינו מדווח על נפח"}), 501
    return jsonify(ad.storage())


@app.get("/api/search")
def api_search():
    """Name search across the drive, newest first — files, and the folders whose name matches."""
    term = (request.args.get("q") or "").strip()
    if len(term) < 2:
        return jsonify({"files": [], "folders": []})
    _, ad = _use()
    folders = ad.search_folders(term) if callable(getattr(ad, "search_folders", None)) else []
    return jsonify({"files": ad.search(term), "folders": folders})


@app.post("/api/folders")
def api_create_folder():
    b = request.get_json(silent=True) or {}
    _, ad = _use()
    folder = ad.create_folder(str(b.get("name") or ""), str(b.get("parent") or ""))
    _flow("folder.created", "נוצרה תיקייה")
    return jsonify({"folder": folder}), 201


def _store(ad, src, size, md5, name, mime, folder):
    """One stored file, whatever the engine: streamed when it can take a stream, else as bytes
    (the Google engines; bounded, since those bytes sit in memory)."""
    store = getattr(ad, "store_file", None)
    if callable(store):
        item = store(src, size, md5, name, mime, folder)
    else:
        if size > 64 * 1024 * 1024:
            raise AdapterError("החיבור הזה מקבל קבצים עד 64 MB", 413)
        item = ad.upload(folder, name, mime, src.read())
    # what the views show about a picture, a video or a recording is found out by the engine that holds
    # the bytes, in the background, when it stores them (drive-local)
    return item


def _spooled(f):
    """(stream, size, md5) of a multipart part without reading it into memory."""
    s = f.stream
    h = hashlib.md5()
    s.seek(0)
    for buf in iter(lambda: s.read(1024 * 1024), b""):
        h.update(buf)
    size = s.tell()
    s.seek(0)
    return s, size, h.hexdigest()


def _upload_refusal(e) -> str:
    """What the PERSON is told when the store does not take a file: a sentence, never the engine's
    English and an internal address (that was the toast, 2026-10-05). The engine's words go to the log."""
    if not isinstance(e, requests.RequestException):
        return getattr(e, "message", None) or str(e) or "האחסון דחה את הקובץ"
    status = getattr(getattr(e, "response", None), "status_code", None)
    if status == 413:
        return "הקובץ גדול מהמותר באחסון — הקובץ לא נשמר"
    if status:
        return f"האחסון לא קיבל את הקובץ (שגיאה {status}) — הקובץ לא נשמר"
    if isinstance(e, (requests.ConnectionError, requests.Timeout)):
        return "שירות האחסון אינו עונה כרגע — הקובץ לא נשמר. נסו שוב בעוד רגע"
    return "האחסון דחה את הקובץ"


@app.post("/api/upload")
def api_upload():
    """One multipart request, one or more files (`files`), into `folder` ('' = root). Each part is
    streamed from werkzeug's spooled temp file — never read whole into memory. Per-file outcome:
    200 all stored, 207 some, 502 none."""
    folder = request.form.get("folder") or request.args.get("folder", "")
    _, ad = _use()
    done, failed = [], []
    for f in request.files.getlist("files"):
        try:
            src, size, md5 = _spooled(f)
            if not size:
                failed.append({"name": f.filename, "error": "קובץ ריק"})
                continue
            with _upload_span(f.filename, f.mimetype, size):
                done.append(_store(ad, src, size, md5, f.filename, f.mimetype, folder))
        except (requests.RequestException, AuthError, AdapterError) as e:
            app.logger.warning("upload of %r failed: %s", f.filename, e)
            failed.append({"name": f.filename, "error": _upload_refusal(e)})
        except Exception as e:
            app.logger.warning("indexing %r failed: %s", f.filename, e)
            failed.append({"name": f.filename, "error": "שמירת הקובץ נכשלה"})
    status = 200 if not failed else (207 if done else 502)
    return jsonify({"uploaded": done, "failed": failed}), status


# ── resumable uploads (tus 1.0: core + creation + termination) ───────────────────
def _session_store(ad):
    """The `store` callback a finished session calls: resolves the destination (a folder id, or a
    path created on demand) and the name (kept, or made free when `mode=new`)."""
    def store(src, size, md5, meta):
        folder = meta.get("folder") or ""
        if meta.get("path"):
            # an app keeps ONE folder of its own, named after it («הקלטות»): it may mark that folder
            # as kept by it (no rename / move / trash from the UI) — and nothing else
            segs = [s for s in str(meta["path"]).split("/") if s]
            system = meta.get("system") if segs and meta.get("system") == segs[-1] else None
            folder = _need(ad, "ensure_path", "נתיבים")(meta["path"], **({"system": system} if system else {}))
        name = meta.get("name") or "file"
        if meta.get("mode") == "new" and callable(getattr(ad, "free_name", None)):
            name = ad.free_name(folder, name)
        with _upload_span(name, meta.get("mime"), size):
            return _store(ad, src, size, md5, name, meta.get("mime"), folder)
    return store


def _remux_recording(part, meta):
    """A recording made in a browser (MediaRecorder) has no duration in its header and seeks badly.
    The same streams copied into a fresh container — no re-encoding, a second or two for an hour —
    fix both, for every player and for the agents that read it. Only what the recorder marks."""
    fmt = {"webm": "webm", "mp4": "mp4"}.get(str(meta.get("remux") or ""))
    if not fmt:
        return part
    out = part + ".fixed"
    args = ["nice", "-n", "10", "ffmpeg", "-v", "error", "-y", "-i", part, "-map", "0:a", "-c", "copy"]
    args += (["-movflags", "+faststart", "-f", "mp4"] if fmt == "mp4" else ["-f", "webm"]) + [out]
    try:
        subprocess.run(args, check=True, timeout=900)
        return out if os.path.getsize(out) > 0 else part
    except Exception as e:                          # stored as recorded: playable, just without a length
        print(f"[drive] remuxing a recording failed, storing it as recorded: {e}", flush=True)
        return part


uploads.PREPARE.append(_remux_recording)


@app.route("/api/uploads", methods=["OPTIONS"])
def tus_options():
    return "", 204, {**TUS, "Tus-Version": "1.0.0", "Tus-Extension": "creation,termination",
                     "Tus-Max-Size": str(uploads.MAX_SIZE)}


def _owner(inst, ad):
    """Whose upload sessions these are: the profile on the office's own engine, else the connection —
    two Google accounts never see (or finish) each other's half-sent files."""
    return getattr(ad, "profile_id", "") if _local(ad) else "c:" + str(inst.get("id") or "")


@app.post("/api/uploads")
def tus_create():
    """Open a session. tus headers (`Upload-Length`, `Upload-Metadata: name <b64>,folder <b64>,
    path <b64>,mime <b64>,mode <b64>`) or a JSON body {size, name, folder|path, mime, mode}."""
    inst, ad = _use()
    if request.headers.get("Upload-Length"):
        size = int(request.headers["Upload-Length"])
        meta = uploads.parse_metadata(request.headers.get("Upload-Metadata"))
    else:
        b = request.get_json(silent=True) or {}
        size, meta = int(b.get("size") or 0), {k: str(b.get(k) or "") for k in ("name", "folder", "path", "mime", "mode", "system", "remux")}
    if meta.get("path"):
        _need(ad, "ensure_path", "נתיבים")
    s = uploads.create(_owner(inst, ad), size, meta)
    return jsonify({"id": s["id"], "offset": 0, "size": s["size"]}), 201, \
        {**TUS, "Location": f"api/uploads/{s['id']}", "Upload-Offset": "0"}


def _session_answer(s, status=200):
    body = {k: s.get(k) for k in ("id", "name", "size", "offset", "state", "error", "error_status", "file")}
    return jsonify(body), status, {**TUS, "Upload-Offset": str(s["offset"]), "Upload-Length": str(s["size"]),
                                   "Cache-Control": "no-store"}


@app.route("/api/uploads/<uid>", methods=["HEAD", "GET"])
def tus_status(uid):
    inst, ad = _use()
    s = uploads.status(uid, _owner(inst, ad))
    if s.get("state") == "complete":                    # every byte is in and nothing finished it
        s = uploads.finish_async(uid, _owner(inst, ad), _session_store(ad))
    return _session_answer(s)


@app.patch("/api/uploads/<uid>")
def tus_patch(uid):
    """The next piece at `Upload-Offset`. The piece that completes the file starts finishing it and
    answers 202 — the client then polls GET until `state` is `done` (with the stored file) or `failed`."""
    inst, ad = _use()
    try:
        offset = int(request.headers.get("Upload-Offset", ""))
    except ValueError:
        raise uploads.UploadError("Upload-Offset חסר", 400)
    pid = _owner(inst, ad)
    s = uploads.append(uid, pid, offset, request.stream, request.content_length)
    if s["offset"] == s["size"]:
        s = uploads.finish_async(uid, pid, _session_store(ad))
        return _session_answer(s, 202)
    return "", 204, {**TUS, "Upload-Offset": str(s["offset"])}


@app.delete("/api/uploads/<uid>")
def tus_delete(uid):
    inst, ad = _use()
    uploads.remove(uid, _owner(inst, ad))
    return "", 204, TUS


@app.get("/api/uploads")
def tus_list():
    """This profile's unfinished sessions — what the page offers to resume after a reload."""
    inst, ad = _use()
    return jsonify({"uploads": uploads.open_sessions(_owner(inst, ad))})


# ── mutations: files and folders alike ────────────────────────────────────────────
@app.post("/api/rename")
def api_rename():
    b = request.get_json(silent=True) or {}
    if not b.get("id") or not str(b.get("name") or "").strip():
        return jsonify({"error": "id and name required"}), 400
    _, ad = _use()
    ad.rename(b["id"], b["name"])
    return jsonify({"ok": True})


@app.post("/api/move")
def api_move():
    b = request.get_json(silent=True) or {}
    _, ad = _use()
    return jsonify({"ok": True, "moved": ad.move(_ids(b), b.get("to") or "")})


@app.post("/api/trash")
def api_trash():
    b = request.get_json(silent=True) or {}
    _, ad = _use()
    restore = bool(b.get("restore"))
    count = ad.trash(_ids(b), restore)
    _flow("items.restored" if restore else "items.trashed",
          f"{'שוחזרו מהאשפה' if restore else 'הועברו לאשפה'} {count} פריטים", count=count)
    return jsonify({"ok": True, "count": count})


@app.post("/api/delete")
def api_delete():
    """Permanent delete — only of what is in the trash."""
    b = request.get_json(silent=True) or {}
    _, ad = _use()
    deleted = ad.delete(_ids(b))
    n = deleted if isinstance(deleted, int) else len(deleted or [])
    _flow("items.deleted", f"נמחקו לצמיתות {n} פריטים", count=n)
    return jsonify({"ok": True, "deleted": deleted})


@app.get("/api/file/<fid>/content")
def api_file_content(fid):
    """The bytes of a file this profile owns, streamed with Range; `?dl=1` downloads. Serving the
    content is the "opened" event that orders Recent — counted once, on the request that starts at
    the first byte, not on every seek of a player."""
    _, ad = _use()
    rng = request.headers.get("Range")
    if "touch" in engines.ops_for(ad)["optional_ops"] and (not rng or rng.replace(" ", "").startswith("bytes=0-")):
        ad.touch(fid)
    want = "attachment" if request.args.get("dl") else "inline"
    try:
        status, hdrs, chunks = ad.content(fid, rng, want)
    except TypeError:                                   # an engine whose content() takes no `want`
        status, hdrs, chunks = ad.content(fid, rng)
    return Response(chunks, status=status, headers=hdrs, direct_passthrough=True)


# ── paths: how agents and apps name a place ───────────────────────────────────────
@app.get("/api/fs")
def api_fs():
    """`?path=/הקלטות` → the folder and what is in it · `?path=/הקלטות/x.m4a` → the file."""
    _, ad = _use()
    path = request.args.get("path") or "/"
    hit = _need(ad, "resolve_path", "נתיבים")(path)
    if not hit:
        return jsonify({"error": f"אין כלום בנתיב {path}"}), 404
    kind, obj = hit
    if kind == "file":
        return jsonify({"kind": "file", "file": obj, "path": path})
    fid = obj["id"]
    sub = getattr(ad, "subfolders", None)
    kids = sub(fid) if callable(sub) else [f for f in ad.folders() if (f.get("parent") or "") == fid]
    return jsonify({"kind": "folder", "folder": obj, "path": obj["path"],
                    "folders": kids, "files": ad.files(fid)})


@app.get("/api/fs/content")
def api_fs_content():
    _, ad = _use()
    hit = _need(ad, "resolve_path", "נתיבים")(request.args.get("path") or "")
    if not hit or hit[0] != "file":
        return jsonify({"error": "אין קובץ בנתיב הזה"}), 404
    status, hdrs, chunks = ad.content(hit[1]["id"], request.headers.get("Range"),
                                      "attachment" if request.args.get("dl") else "inline")
    return Response(chunks, status=status, headers=hdrs, direct_passthrough=True)


@app.put("/api/fs/content")
def api_fs_put():
    """Write the request body as the file at `?path=/פגישות/2026-10-28/x.mp4` — folders are created
    on demand; `mode=new` (the default) keeps an existing file and names this one «x (2).mp4»,
    `mode=replace` trashes the existing one first, `mode=exclusive` refuses (409) when the path is
    taken. The body streams through a temp file (md5 and size must be known before storage takes it),
    so a recording of any size is fine.

    The body IS the file, whatever its Content-Type, and the drive is named only in the address and the
    headers. `_use()` used to look for a connection in `request.form` and in a JSON body before this route
    read the stream, so a body labelled as a form (`curl -d`, urllib's default) or as JSON was parsed away:
    the file was stored EMPTY with a 201, after `mode=replace` had already trashed the good copy (DGO-2042,
    issues/a-drive-upload-sent-as-a-form-is-stored-empty-and-replace-trashes-the-good-copy.yaml); a JSON
    file's own `connection_id` chose the drive; and a form body over Flask's form-memory limit got a 413.
    Now the drive is resolved first, from the address and the headers (`body=False`), and nothing is
    trashed before the body is known to be acceptable: a multipart envelope is refused (415, it is not a
    file: POST /api/upload takes forms), an empty body is refused unless the caller asks for an empty file
    (`empty=1`), and so is one over the limit. A store that fails AFTER the trash still leaves the old copy
    only in the trash (the issue's open task)."""
    path = request.args.get("path") or ""
    parts = path.rstrip("/").rsplit("/", 1)
    if len(parts) != 2 or not parts[1].strip():
        return jsonify({"error": "path must end in a file name"}), 400
    mode = request.args.get("mode") or "new"
    if request.mimetype == "multipart/form-data":
        return jsonify({"error": "PUT שומר את הקובץ עצמו, ומה שהגיע הוא טופס. שלחו את הבתים של הקובץ "
                                 "(או POST /api/upload לטופס). לא נשמר כלום ושום קובץ לא הוחלף.", "path": path}), 415
    _, ad = _use(body=False)
    with tempfile.TemporaryFile(dir=os.environ.get("DRIVE_UPLOAD_DIR", "/data/uploads")
                                if os.path.isdir(os.environ.get("DRIVE_UPLOAD_DIR", "/data/uploads")) else None) as tmp:
        h, size = hashlib.md5(), 0
        for buf in iter(lambda: request.stream.read(1024 * 1024), b""):
            h.update(buf)
            tmp.write(buf)
            size += len(buf)
        if size > uploads.MAX_SIZE:
            return jsonify({"error": "הקובץ גדול מהמותר"}), 413
        if size == 0 and request.args.get("empty") != "1":
            return jsonify({"error": f"לא התקבל תוכן לקובץ {path}, ולכן לא נשמר כלום ושום קובץ לא הוחלף. "
                                     "קובץ ריק בכוונה: empty=1 בכתובת (ב-bbox drive put: ‎--empty)", "path": path}), 400
        folder = _need(ad, "ensure_path", "נתיבים")(parts[0] or "/", request.args.get("system") or None)
        name = parts[1]
        if mode == "replace":
            old = ad.resolve_path(path)
            if old and old[0] == "file":
                ad.trash([old[1]["id"]])
        elif mode == "exclusive":
            # a create that FAILS when the name is taken (DGO-1505: restic writes each pack once, under its own
            # name, and a second copy under the same name — Google allows that — would be read as the first)
            if ad.resolve_path(path):
                return jsonify({"error": f"כבר יש פריט בנתיב {path}", "path": path}), 409
        else:
            name = ad.free_name(folder, name)
        # a form's label says nothing about the file inside it: as with no label at all, its name decides its type
        mime = None if request.mimetype == "application/x-www-form-urlencoded" else request.headers.get("Content-Type")
        tmp.seek(0)
        item = _store(ad, tmp, size, h.hexdigest(), name, mime, folder)
    return jsonify({"file": item, "path": ad.path_of(folder).rstrip("/") + "/" + item["name"]}), 201


@app.post("/api/fs/mkdir")
def api_fs_mkdir():
    """Get-or-create a folder path. `system` marks it as kept by that app (no rename/move/delete)."""
    b = request.get_json(silent=True) or {}
    _, ad = _use()
    fid = _need(ad, "ensure_path", "נתיבים")(str(b.get("path") or ""), b.get("system") or None)
    return jsonify({"id": fid, "path": ad.path_of(fid)})


# ── canonical ops (§3) — the surface n8n calls ────────────────────────────────────
# `POST /<op>` with driveApi01's own op names and params. The ops run through the SAME resolve()
# choke point as the UI, and every op REQUIRES a `connection_id`/`profile_id`.
def _p():
    return request.get_json(silent=True) or {}


def _op(fn, *a, **kw):
    """Run a canonical op on the resolved adapter, refusing a call that names no identity
    (`_explicit_connection_required`). Adapter/Google errors fall through to the handlers above,
    so a broken connection is a 400/503 naming itself — never a silent local substitution."""
    _inst, ad = _use(require_explicit=True)
    if not callable(getattr(ad, fn, None)):
        raise AdapterError("this connection does not support that operation", 501)
    return getattr(ad, fn)(*a, **kw)


@app.post("/list")
def op_list():
    """`createdAfter` (RFC3339) is the sync-discovery bound — an old file is excluded from the
    listing itself. `query` (Drive `q` syntax) is AND-ed into the clause this layer builds, never
    replacing it (closing the 2026-08-13 gap where it was silently dropped: 0 finds in 6,861
    searches). `nameContains`/`nameContainsAny` are the engine-agnostic name filters."""
    b = _p()
    files = _op("op_list", b.get("folderId") or "", b.get("limit") or 100,
                b.get("whatToSearch") or "files", bool(b.get("includeTrashed")),
                b.get("createdAfter") or None, b.get("query") or None,
                b.get("nameContains") or None, b.get("nameContainsAny") or None)
    return jsonify({"files": files})


@app.post("/download")
def op_download():
    b = _p()
    status, hdrs, chunks = _op("op_download", b.get("fileId"), b.get("fileIdMode") or "id")
    return Response(chunks, status=status, headers=hdrs, direct_passthrough=True)


@app.post("/upload")
def op_upload():
    """multipart: the bytes as `file`, plus `name`/`folderId` form fields. Binary in, the full
    drive#file out (md5Checksum included). Streamed from the spooled part on the local engine."""
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "file required"}), 400
    name = request.form.get("name") or f.filename
    folder = request.form.get("folderId") or ""
    _inst, ad = _use(require_explicit=True)
    if callable(getattr(ad, "op_upload", None)):
        # streamed from the spooled part; the engine answers its own file resource (drive#file)
        src, size, md5 = _spooled(f)
        return jsonify(ad.op_store_stream(src, size, md5, name, f.mimetype, folder))
    raise AdapterError("this connection does not support that operation", 501)


@app.post("/move")
def op_move():
    b = _p()
    return jsonify(_op("op_move", b.get("fileId"), b.get("toFolderId")))


@app.post("/update")
def op_update():
    b = _p()
    return jsonify(_op("op_update", b.get("fileId"), b.get("newName")))


@app.post("/delete")
def op_delete():
    b = _p()
    return jsonify(_op("op_delete", b.get("fileId")))


@app.post("/createFromText")
def op_create_from_text():
    b = _p()
    return jsonify(_op("op_create_from_text", b.get("name"), b.get("content"),
                       b.get("folderId") or ""))


@app.post("/ensureFolder")
def op_ensure_folder():
    """get-or-create a folder PATH ('automations/thumbnails') on the NAMED identity — race-safe on
    the local engine (ensure_path), a name walk on engines without it. The LAST segment's id."""
    b = _p()
    path = str(b.get("path") or "").strip().strip("/")
    if not path:
        return jsonify({"error": "path required"}), 400
    _, ad = _use(require_explicit=True)
    if callable(getattr(ad, "ensure_path", None)):
        before = ad.resolve_path(path)
        fid = ad.ensure_path(path)
        return jsonify({"id": fid, "path": path, "created": before is None})
    if not hasattr(ad, "folders") or not hasattr(ad, "create_folder"):
        return jsonify({"error": "this engine has no folder tree"}), 400
    by_key = {(str(f.get("parent") or ""), str(f.get("name") or "")): f for f in (ad.folders() or [])
              if isinstance(f, dict)}
    parent, created = "", False
    for seg in [s.strip() for s in path.split("/") if s.strip()]:
        hit = by_key.get((parent, seg))
        if hit is None:
            hit = ad.create_folder(seg, parent)
            created = True
            by_key[(parent, seg)] = hit
        parent = str(hit.get("id") or "")
    return jsonify({"id": parent, "path": path, "created": created})


# ── the share link /file/d/<id>/view is the office storage's (drive-local), handed to it verbatim by
# `_engine_routes` above: profile-independent by design, served on this app's address as it always was.


@app.get("/healthz")
def healthz():
    """The process answers. Whether a drive WORKS is /readyz's question (its engine, its account)."""
    return jsonify({"status": "ok"})


# ── Platform service contract (§2): manifest / readyz / connection management ──────
@app.get("/manifest")
def manifest():
    """What this service is and what it can do — the console discovers drive from here. `connection`
    is what THIS profile can do, by introspection of the live adapter, so the UI gates a control
    before the user presses it; null (with a reason) when nothing resolves."""
    conn = None
    try:
        inst = _resolve_instance(None, None)
        ad = engines.for_instance(inst)
        caps = engines.ops_for(ad)
        conn = {"id": inst.get("id"), "protocol": inst.get("protocol"),
                "is_private": inst.get("is_private"), "profile_id": inst.get("profile_id"),
                "views": engines.views_for(ad), **caps,
                "paths": callable(getattr(ad, "resolve_path", None)),
                "folder_ops": callable(getattr(ad, "trashed_folders", None)),
                "streams": callable(getattr(ad, "store_file", None))}
    except (AdapterError, AuthError, ProfileError) as e:
        conn = {"error": getattr(e, "message", str(e))}
    return jsonify({
        "service": "drive",
        "protocols": engines.protocols(),
        "private_protocols": engines.private_protocols(),
        "engines": [{"id": eid, "app": engines.PREFIX + eid, "kind": o.get("kind"),
                     "protocols": list(o.get("protocols") or {})} for eid, o in engines.all_ops()],
        "ops": list(engines.CANONICAL_OPS),
        "optional_ops": list(engines.PROTOCOL_OPS),
        "slots": list(extensions.SLOTS),
        "connection": conn,
        "capabilities": {
            "multi_connection": True,
            "engine_profiles": True,
            "local_adapter": True,
            "public_links": True,        # /file/d/<id>/view (local connection only)
            "folders": True,
            "trash": True,
            "search": True,
            "extensions": True,
            "resumable_uploads": True,   # /api/uploads — tus 1.0 core + creation + termination
            "max_upload": uploads.MAX_SIZE,
            "paths": True,               # /api/fs — name a place by path (agents, apps)
            "ops_use_active_connection": False,
            "ops_require_explicit_connection": True,
        },
    })


@app.get("/readyz")
def readyz():
    """The only contract n8n needs: does the BOUND connection resolve and its adapter answer? A SET
    binding that does not resolve is a 503 naming the dangling id — never a silent downgrade; and
    `connection_id` is the id actually probed."""
    try:
        inst = _resolve_instance(None, None)
        reason = engines.for_instance(inst).probe()
    except (AdapterError, AuthError, ProfileError) as e:
        status = getattr(e, "status", 503)
        return jsonify({"ready": False, "reason": getattr(e, "message", str(e)),
                        "connection_id": None, "active": cx.active()}), status
    if reason:
        return jsonify({"ready": False, "reason": reason, "connection_id": inst.get("id"),
                        "profile_id": inst.get("profile_id")}), 503
    return jsonify({"ready": True, "connection_id": inst.get("id"),
                    "profile_id": inst.get("profile_id")})


@app.get("/connections")
def connections_list():
    """The list, and the binding's EFFECTIVE meaning — never an `active` id absent from the list.
    A dangling selection is surfaced as its own `needs_action` row (§4b), so the console can offer
    the one-click fix and never disagree with /readyz about whether this drive is usable."""
    conns = cx.list_instances()
    cid = cx.active()
    acting = None
    try:
        acting = acting_profile()
    except ProfileError:
        acting = None
    if not cid:
        eff = cx.default_instance()
        return jsonify({"active": (eff or {}).get("id"), "connections": conns,
                        "bound": None, "acting_profile": acting})
    if not any(c.get("id") == cid for c in conns):
        _inst, reason = cx.resolve_active()
        conns.append(cx.dangling_instance(cid, reason or "החשבון שנבחר אינו זמין"))
        return jsonify({"active": cid, "connections": conns, "reason": reason,
                        "bound": cid, "acting_profile": acting})
    return jsonify({"active": cid, "connections": conns, "bound": cid, "acting_profile": acting})


@app.get("/connections/active")
def connections_active():
    """Which drive this office acts as when nobody names one — the bound one, else the default — for the
    office storage's engine to know who a keyless request of the screen is (its /engine/whoami). Ids only."""
    inst, reason = cx.resolve_active()
    return jsonify({"id": (inst or {}).get("id") if not reason else None, "bound": cx.active(),
                    "is_private": bool(inst and not reason and inst.get("is_private")), "reason": reason})


LEGACY_LEDGER = os.environ.get("DRIVE_LEGACY_LEDGER", "/data/profile-ledger.json")


@app.get("/connections/profile-ledger")
def connections_profile_ledger():
    """The office storage's profile ledger as it was kept on THIS app's volume before the split (DGO-1500):
    which profiles the app.json reconciler made — ids only, no credential. drive-local reads it once, on its
    first start, so what it removes or repairs is what the old reconciler would have; 404 when there is none."""
    try:
        with open(LEGACY_LEDGER, encoding="utf-8") as f:
            doc = json_loads(f.read())
    except (OSError, ValueError):
        return jsonify({"error": "no ledger from before the split"}), 404
    declared = (doc or {}).get("declared") if isinstance(doc, dict) else None
    return jsonify({"declared": {str(k): {"created_at": (v or {}).get("created_at")}
                                 for k, v in (declared or {}).items()}})


@app.get("/connections/<cid>/probe")
def connections_probe(cid):
    """Verify ONE connection without selecting it (§4b step 4: a connection is verified, not added).
    Same probe /readyz runs, so what the connect flow shows and what n8n trusts cannot disagree."""
    inst = cx.get_instance(cid)
    if not inst:
        return jsonify({"error": f"unknown connection {cid!r}"}), 404
    try:
        reason = engines.for_instance(inst).probe()
    except (AdapterError, AuthError, ProfileError) as e:
        reason = getattr(e, "message", str(e))
    return jsonify({"ok": not reason, "reason": reason, "id": cid,
                    "account_hint": inst.get("account_hint")})


@app.post("/connections/select")
def connections_select():
    b = request.get_json(force=True, silent=True) or {}
    cid = b.get("id")
    if not cid:
        return jsonify({"error": "id required"}), 400
    if not cx.get_instance(cid):
        return jsonify({"error": f"unknown connection {cid!r}"}), 404
    cx.select(cid, b.get("scope") or cx.DEFAULT_SCOPE)
    return jsonify({"ok": True, "active": cid, "scope": b.get("scope") or cx.DEFAULT_SCOPE})


@app.post("/connections")
def connections_add():
    """Add a connection to an EXISTING account, by the engine that serves its protocol — each checks its
    own credential (drive-local: the profile's key; drive-google: a service account's JSON), so nothing
    is added that was never verified. A NEW identity on the office storage is POST /engine/profiles."""
    b = request.get_json(force=True, silent=True) or {}
    proto, label, secret = b.get("protocol"), b.get("label"), b.get("secret")
    if not proto or not label or secret is None:
        return jsonify({"error": "protocol, label and secret required"}), 400
    eid = engines.engine_of(proto)
    if not eid:
        return jsonify({"error": f"אין מנוע קבצים פעיל לחשבון מסוג {proto!r}"}), 400
    try:
        r = requests.post(engines.url(eid) + "/v1/connect", timeout=(5, 30),
                          json={"protocol": proto, "label": label, "secret": secret, "account_hint": b.get("account_hint")})
        body = r.json()
    except (requests.RequestException, ValueError):
        return jsonify({"error": f"מנוע הקבצים {engines.PREFIX}{eid} אינו עונה — החשבון לא חובר"}), 503
    engines.invalidate()
    return jsonify(body), r.status_code


@app.delete("/connections/<cid>")
def connections_delete(cid):
    """Disconnect an account, by its own engine (the office storage refuses: a profile is removed in
    «ניהול פרופילים», or its identity would survive with its key nowhere)."""
    inst = cx.get_instance(cid)
    if not inst:
        return jsonify({"error": f"unknown connection {cid!r}"}), 404
    eid = engines.engine_of(inst.get("protocol") or "")
    if eid:
        try:
            r = requests.post(engines.url(eid) + "/v1/disconnect", json={"connection_id": cid}, timeout=(5, 30))
            body, status = r.json(), r.status_code
        except (requests.RequestException, ValueError):
            return jsonify({"error": f"מנוע הקבצים {engines.PREFIX}{eid} אינו עונה — החשבון לא נותק"}), 503
    elif engines.unanswered():
        # an engine of this office does not answer: it may be this account's, and its own refusal (a profile
        # of the office storage is removed in «ניהול פרופילים») must not be skipped by its silence
        return jsonify({"error": "מנוע קבצים של הלשכה אינו עונה כרגע — החשבון לא נותק. נסו שוב בעוד רגע.",
                        "engines": engines.unanswered()}), 503
    else:
        # every engine answered and none serves this account's kind: its engine is gone, it can be let go of
        body, status = cx.delete_instance(cid)
    engines.invalidate(cid)
    # Drop a now-dangling binding so the service falls back to the default rather than a dead one.
    if 200 <= status < 300 and cx.active() == cid:
        cx.unbind()
    return jsonify(body), status


# ── the ENGINE plane: the office storage's profiles live in its engine (drive-local /engine/*), handed
# to it verbatim by `_engine_routes` — the same route names in mail and chat, on this app's address.


# ── engines / providers ───────────────────────────────────────────────────────────
@app.get("/engines")
def engines_list():
    """Engine-first catalogue (§5e), each engine's own rows (its /ops `engines`). `private` tells a
    caller whether profiles can be CREATED here or only CONNECTED to."""
    return jsonify({"engines": [row for _eid, o in engines.all_ops() for row in (o.get("engines") or [])]})


@app.get("/providers")
def providers():
    """Provider-first catalog for the guided connect flow (§4b): users pick a PROVIDER, and each
    provider offers auth methods that each map to exactly one engine — each engine's own rows (its
    /ops `providers`), the office's own storage first. An engine that is not running offers nothing."""
    return jsonify({"providers": [row for _eid, o in engines.all_ops() for row in (o.get("providers") or [])]})


# ── «התחברות עם Google» from this screen (DGO-1390) ───────────────────────────────
# The consent belongs to the office's credential plane (connections: the client, the grant, the
# instances); this app only opens it and receives it, both legs through itself AS THE BROWSER SEES IT —
# under the console (/a/drive/…, /a/drive.<office>/… across a link) or on its own host — so the person
# comes back to the window they started from, on whichever office runs the drive. Google's one
# registered address is the herd's relay (connections OAUTH_RELAY_URL), never this office's: an office
# at home has none Google accepts.
def _theme_block():
    """The palette as the page carries it (index.html's stamped block): a page this app draws itself
    names no colour of its own (G82)."""
    try:
        with open(os.path.join(app.static_folder, "index.html"), encoding="utf-8") as f:
            page = f.read()
        a, b = page.index("/* @bina-theme-tokens:start */"), page.index("/* @bina-theme-tokens:end */")
        return page[a:b]
    except (OSError, ValueError):
        return ""


_THEME = _theme_block()


def _oauth_page(ok, title, detail="", made=None, status=200):
    """The window Google returns to: what happened, said in words, told to the window that opened it
    (so the screen there moves on by itself), and closed when it was a pop-up."""
    import html as _h
    import json as _j
    msg = _j.dumps({"type": "dgo:oauth", "ok": bool(ok), "made": made or [], "error": "" if ok else title}).replace("<", "\\u003c")
    accounts = "".join(f"<li><bdi>{_h.escape(m.get('account_hint') or '')}</bdi></li>" for m in (made or [])[:1])
    page = f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{_h.escape(title)}</title>
<style>{_THEME}
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);
font:14px/1.5 "Segoe UI",system-ui,-apple-system,"Noto Sans Hebrew",Arial,sans-serif}}
.card{{width:min(420px,calc(100vw - 32px));box-sizing:border-box;background:var(--surface);border:1px solid var(--line);
border-radius:16px;padding:22px;box-shadow:var(--shadow)}}
h1{{margin:0 0 8px;font-size:16px;font-weight:800;color:{'var(--ok)' if ok else 'var(--danger)'}}}
p,li{{margin:0 0 6px;font-size:13px;color:var(--muted);overflow-wrap:anywhere}} ul{{margin:8px 0 0;padding-inline-start:18px}}
button{{margin-top:14px;height:34px;padding:0 16px;border-radius:9px;border:0;background:var(--accent);color:var(--accent-ink);
font:inherit;font-weight:700;cursor:pointer}}</style></head>
<body><div class="card" role="status"><h1>{_h.escape(title)}</h1>
{f"<p><bdi>{_h.escape(detail)}</bdi></p>" if detail else ""}{f"<ul>{accounts}</ul>" if accounts else ""}
<button type="button" onclick="window.close()">סגירת החלון</button></div>
<script>(function(){{var m={msg};try{{if(window.opener)window.opener.postMessage(m,location.origin);}}catch(e){{}}
if(window.opener&&m.ok)setTimeout(function(){{window.close();}},1600);}})();</script></body></html>"""
    # X-Dgo-Oauth marks THIS page as the app's own answer: the return page clears its secret only on it — never on
    # an error page of the server's or a sign-in page that happens to be HTML too (DGO-1418).
    return Response(page, status=status, mimetype="text/html",
                    headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Dgo-Oauth": "1"})


#: Where the window that asked keeps its secret for the consent it started (DGO-1418): `<prefix><state>`, one slot per
#: consent, so two at once (the drive's and the mail's, two tabs) never take each other's. The screen stores it; the
#: return page — the same origin, under the console too — reads it, and removes it once the app has answered.
OAUTH_BIND_KEY = "dgo-oauth-bind:"


def _js(value):
    """A JSON string fit for a <script>: a `</script>` inside a value cannot end the script."""
    import json as _j
    return _j.dumps(value).replace("<", "\\u003c")


def _oauth_state_of(authorize_url):
    return (urllib.parse.parse_qs(urllib.parse.urlsplit(authorize_url).query).get("state") or [""])[0]


def _oauth_bind_page(authorize_url, secret):
    """Without the screen (`check` absent): this window keeps the secret itself, then goes to Google."""
    return Response(f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><title>Google</title></head>
<body><script>try{{localStorage.setItem({_js(OAUTH_BIND_KEY + _oauth_state_of(authorize_url))},{_js(secret)});}}catch(e){{}}
location.replace({_js(authorize_url)});</script></body></html>""", status=200, mimetype="text/html",
                    headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


def _door(name):
    """The consent door an engine names for itself (/ops `oauth`): {"grant", "provider", "connected", "engine"}."""
    door = engines.oauth(name)
    if not door or not door.get("grant"):
        raise AdapterError(f"אין מנוע קבצים פעיל שמתחבר דרך {name!r}", 404)
    return door


@app.get("/oauth/<name>/start")
def oauth_google_start(name):
    """Open a provider's consent for a new account — the grant the engine names (drive-google: Google's).
    `ret` is this app's return page, absolute, as the browser sees it (the screen builds it from its own
    base). `check=1` answers JSON instead of the redirect: the screen asks first and sends its window to
    the provider only when it would take the request — a client the provider no longer has is said in the
    screen, in Hebrew, not on the provider's page.

    The consent is bound to THIS browser (DGO-1418): a secret is made here, connections keeps only its
    sha256, and the secret goes back in the answer's body (never in an address) for the window to keep."""
    check = request.args.get("check") == "1"
    try:
        door = _door(name)
    except AdapterError as e:
        return (jsonify({"error": e.message}), 404) if check else _oauth_page(False, "ההתחברות לא נפתחה", e.message, status=404)
    who = door.get("provider") or name
    failed = f"ההתחברות ל־{who} לא נפתחה"
    ret = (request.args.get("ret") or "").strip()
    if not ret:          # without a return page it would be the broker's own consent, bound to nothing
        why = f"חסרה כתובת החזרה של המסך — ההתחברות ל־{who} לא נפתחה."
        return (jsonify({"error": why}), 400) if check else _oauth_page(False, failed, why, status=400)
    secret = secrets.token_urlsafe(24)
    try:
        # `protocol`: the one this door serves — connections narrows the consent to it where the office connects
        # it read-only (EXU-24), and ignores it elsewhere
        r = requests.get(f"{cx.CONNECTIONS_URL}/oauth/{urllib.parse.quote(door['grant'])}/start",
                         params={"as_instance": "1", "ret": ret, "protocol": door.get("protocol") or "",
                                 "bind": hashlib.sha256(secret.encode()).hexdigest()}, timeout=20)
        d = r.json()
    except (requests.RequestException, ValueError):
        why = f"שירות החשבונות של הלשכה אינו עונה — ההתחברות ל־{who} לא נפתחה. נסו שוב בעוד רגע."
        return (jsonify({"error": why}), 503) if check else _oauth_page(False, "שירות החשבונות של הלשכה אינו עונה", why, status=503)
    if r.status_code >= 400 or not d.get("authorize_url"):
        why = d.get("error") or f"HTTP {r.status_code}"
        status = 502 if r.status_code < 400 else r.status_code
        # …with where it is fixed, when connections says (Google Cloud's credentials page, DGO-1634): the screen
        # shows it as a link under the sentence
        help_url = d.get("help_url") if str(d.get("help_url") or "").startswith("https://") else None
        return (jsonify({"error": why, "provider_error": d.get("provider_error"), "help_url": help_url}), status) if check \
            else _oauth_page(False, failed, why, status=status)
    if not str(d["authorize_url"]).startswith("https://") or d.get("relayed") is not True:
        # only a RELAYED consent is bound to this browser; anything else is the broker's own, and not handed out here
        why = f"כתובת ההסכמה שהתקבלה אינה של הסכמה חתומה ומאובטחת — ההתחברות ל־{who} לא נפתחה."
        return (jsonify({"error": why}), 502) if check else _oauth_page(False, failed, why, status=502)
    if check:
        resp = jsonify({"ok": True, "authorize_url": d["authorize_url"], "bind": secret})
        resp.headers["Cache-Control"] = "no-store"
        return resp
    return _oauth_bind_page(d["authorize_url"], secret)


@app.get("/oauth/<name>/return")
def oauth_google_return(name):
    """Where the provider (Google, through the herd's relay) sends the browser back. Nothing is done on this
    GET: the page reads the secret its own window kept (same origin) and hands it, with the provider's
    answer, to /oauth/<name>/finish — a browser that did not start the consent has no secret to hand.

    `finish` is resolved against THIS page's address, never the document's base: under the console the
    proxy injects one at the app's mount (`/a/<alias>/`), and a bare relative URL went to `/a/<alias>/finish`.
    The secret is removed only on the app's own answer (X-Dgo-Oauth). When none came, the page says so and keeps
    the secret for a reload — and tells the screen nothing: its poller sees an account that was made anyway."""
    page = f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>מחבר את החשבון</title>
<style>{_THEME}
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);
font:14px/1.5 "Segoe UI",system-ui,-apple-system,"Noto Sans Hebrew",Arial,sans-serif}}
.card{{width:min(420px,calc(100vw - 32px));box-sizing:border-box;background:var(--surface);border:1px solid var(--line);
border-radius:16px;padding:22px;box-shadow:var(--shadow)}} h1{{margin:0 0 8px;font-size:16px;font-weight:800}}
p{{margin:0;font-size:13px;color:var(--muted)}}</style></head>
<body><div class="card" role="status"><h1 id="t">מחבר את החשבון…</h1><p id="d">החשבון נבדק ונשמר בלשכה.</p></div>
<script>(function(){{var q=new URLSearchParams(location.search),key={_js(OAUTH_BIND_KEY)}+(q.get("state")||""),bind="";
try{{bind=localStorage.getItem(key)||"";}}catch(e){{}}
function fail(){{document.getElementById("t").textContent="שירות החשבונות של הלשכה אינו עונה";
document.getElementById("d").textContent="לא ידוע אם החשבון נשמר. אפשר לטעון את החלון מחדש, או לחזור למסך.";}}
fetch(new URL("finish",location.href),{{method:"POST",credentials:"same-origin",headers:{{"Content-Type":"application/json"}},
body:JSON.stringify({{code:q.get("code")||"",state:q.get("state")||"",error:q.get("error")||"",bind:bind}})}})
.then(function(r){{if(!r.headers.get("X-Dgo-Oauth"))throw new Error("HTTP "+r.status);return r.text();}})
.then(function(h){{try{{localStorage.removeItem(key);}}catch(e){{}}document.open();document.write(h);document.close();}})
.catch(fail);}})();</script></body></html>"""
    return Response(page, status=200, mimetype="text/html",
                    headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@app.post("/oauth/<name>/finish")
def oauth_google_finish(name):
    """The return page's hand-over: the provider's answer and the secret its window kept go to this
    office's connections, which keeps the account (Google: one consent, Drive and Gmail) — and the page
    says which, in the words the engine gives (/ops `oauth`)."""
    b = request.get_json(force=True, silent=True)
    b = b if isinstance(b, dict) else {}
    body = {k: str(b.get(k)) for k in ("code", "state", "error", "bind") if b.get(k)}
    if body.get("error") == "access_denied":
        return _oauth_page(False, "ההתחברות בוטלה", "לא נוסף חשבון. אפשר לנסות שוב מתי שרוצים.")
    try:
        r = requests.post(f"{cx.CONNECTIONS_URL}/oauth/relayed", json=body, timeout=30)
        d = r.json()
    except (requests.RequestException, ValueError):
        return _oauth_page(False, "שירות החשבונות של הלשכה אינו עונה", "החשבון לא נשמר. נסו להתחבר שוב.", status=503)
    if not d.get("ok"):
        return _oauth_page(False, "החשבון לא חובר", d.get("error") or f"HTTP {r.status_code}", status=400)
    engines.invalidate()
    door = engines.oauth(name) or {}
    said = (d.get("read_only") and door.get("connected_read_only")) or door.get("connected") or "החשבון זמין עכשיו בלשכה."
    return _oauth_page(True, "החשבון חובר", said, made=d.get("made"))


# ── extension slots (§4c) — an app registers UI, this service renders it ───────────
@app.get("/extensions")
def extensions_list():
    """What is registered. `spec` is echoed back verbatim: stored and rendered, never interpreted."""
    return jsonify({"extensions": extensions.listing(request.args.get("slot"),
                                                     request.args.get("app")),
                    "slots": list(extensions.SLOTS)})


@app.post("/extensions")
def extensions_register():
    b = request.get_json(force=True, silent=True) or {}
    rec, err = extensions.register(b.get("app"), b.get("slot"), b.get("spec"))
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"ok": True, "app": rec["app"], "slot": rec["slot"]})


@app.delete("/extensions/<appname>/<slot>")
def extensions_unregister(appname, slot):
    return jsonify({"ok": extensions.unregister(appname, slot)})
