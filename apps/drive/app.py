"""drive — THE drive platform service (contract: ai/context/platform-service-contract.md).

The office's one file layer: people drop files into it from the console, apps write into it
(meeting recordings into «פגישות», the recorder into «הקלטות»), and agents read what is there by
path. Three planes, one service:
  * the ENGINE plane — `drive_local` is a private engine we run, and it has N PROFILES. A profile is
    an identity holding a credential; it is declared in app.json or created here, and creating one
    creates its vault instance in the same operation. See profiles.py / bootstrap.py.
  * the CONNECTION plane (§2) — every profile, private or remote, is an ordinary vault instance.
    The BINDING (which one this drive acts as) lives here, as a {scope -> id} map.
  * the OP plane — every op runs through an adapter (`adapters/`). The UI plane (`/api/*`, the
    SSO-gated browser) runs on the account the operator selected — the BOUND profile.
    The §3 CANONICAL OPS (`/list /download /upload /move /update /delete /createFromText`, what
    n8n's driveApi01 calls) never fall back to the binding: `connection_id`/`profile_id` is
    REQUIRED on every one of them (see `_explicit_connection_required`).

BYTES IN: `/api/uploads` is a resumable (tus 1.0) session per file — pieces of a few MB, so memory
stays flat for any size and a dropped connection resumes (uploads.py). `/api/upload` (one multipart
request) remains for small files and streams each part from its spooled temp file. BYTES OUT:
streamed with Range; a user's file is served inline only when it is a type that cannot run anything
(media.serve_headers), so a stored .html or .svg can never act with the viewer's session.

AUTHORIZATION. Three rings, checked here, enforced in the adapter's QUERIES:
    data   any active profile — every drive op, scoped to its own rows
    self   any active profile — read/update itself, rotate its own key
    admin  is_admin only      — create/edit/suspend/delete OTHER profiles
The ACTING profile is the one whose credential the request presents (`X-Drive-Profile-Key`). When no
credential is presented the request is the SSO-gated browser UI, and it acts as the BOUND profile —
platform users are explicitly out of scope (profiles-and-engines.md §7), so the SSO session is the
authentication and the binding is the identity. Data scoping does not depend on this either way: it
is applied by the adapter to whichever profile ends up resolved.
"""
import hashlib
import os
import subprocess
import tempfile

import requests
from flask import Flask, Response, jsonify, request, send_from_directory

import adapters
import bootstrap
import connections_client as cx
import extensions
import media
import media_jobs
import profiles
import uploads
from adapters import AdapterError, local as local_engine
from adapters.google import GoogleAuthError
from adapters.local import DFILE_COLS, _dfile, ensure_schema, public_stream, q
from profiles import ProfileError

local_engine.ON_DELETE.append(media_jobs.forget)

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

CONNECTIONS_PUBLIC_URL = os.environ.get("CONNECTIONS_PUBLIC_URL", "https://connections.localhost").rstrip("/")
PROFILE_KEY_HEADER = "X-Drive-Profile-Key"
TUS = {"Tus-Resumable": "1.0.0"}

# ── one-time provisioning, RETRIED until the DB and the vault are actually there ───
# On a cold bring-up this service reaches gunicorn before supabase-db accepts TCP; a bare call at
# import used to leave the worker unprovisioned for life. The PROFILE RECONCILER runs in the same
# place for the same reason: in-process with direct DB access (which exempts it from profile
# authentication — the chicken-and-egg of needing an admin key to create the admin), idempotent,
# ledger-backed, and it NEVER re-mints a credential for a profile that already has an instance.
_SCHEMA_OK = False
_PROFILES_OK = False


def _provision():
    global _SCHEMA_OK, _PROFILES_OK
    if not _SCHEMA_OK:
        if not ensure_schema():
            return                  # DB still coming up — the next request tries again
        try:
            media_jobs.ensure_table()
        except Exception as e:
            print("[drive] media table deferred:", e, flush=True)
            return
        _SCHEMA_OK = True
    if not _PROFILES_OK:
        try:
            _PROFILES_OK = bootstrap.reconcile()
        except Exception as e:      # a reconciler must never take the service down with it
            print("[drive] profile reconcile deferred:", e, flush=True)


@app.before_request
def _provision_before_request():
    # /healthz is polled every 30s, so this re-arms on its own even with no user traffic at all.
    _provision()


_provision()

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


def _override():
    """(profile_id, connection_id) for this call (§2).

    Two spellings of one idea, because the two callers think in different nouns: automation names a
    CONNECTION (it holds ids), the profile UI names a PROFILE. Both land on the same choke point.
    """
    b = _body()
    cid = (request.args.get("connection_id") or b.get("connection_id")
           or request.form.get("connection_id"))
    pid = (request.args.get("profile_id") or b.get("profile_id")
           or request.form.get("profile_id"))
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


def _use(require_explicit=False):
    """(instance, adapter) for this request — and the check that makes a credential a CONSTRAINT
    rather than a second way in.

    A request presenting profile B's key while naming profile A's connection is REFUSED; without
    this, `connection_id` would be a field the caller controls that decides whose files they get.
    A session request (no credential) has no claimed identity to contradict, and it is already
    behind the deployment's forward-auth.
    """
    pid, cid = _override()
    if require_explicit and not pid and not cid:
        _explicit_connection_required()
    inst, adapter = adapters.resolve(profile_id=pid, connection_id=cid)
    me = acting_profile() if _presented_key() else None
    if me and inst.get("protocol") in adapters.PRIVATE_PROTOCOLS:
        target = profiles.by_instance(inst.get("id")) or profiles.get(inst.get("account_hint"))
        if target and target["id"] != me["id"]:
            raise ProfileError(
                f"המפתח שייך לפרופיל «{me['display_name']}» ואינו יכול לפעול בשם "
                f"«{target['display_name']}»", 403)
    return inst, adapter


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


@app.errorhandler(GoogleAuthError)
def _google_error(e):
    # 503, not 500: the connection is unusable, the service is fine. A MISSING FILE carries the
    # status Google returned (404/410), so a caller can tell "retry later" from "never exists".
    return jsonify({"error": str(e), "connection_id": cx.active()}), getattr(e, "status", 503)


def _ids(b):
    """Every mutation accepts a single id or a bulk ids[] — one consolidated shape."""
    return [i for i in (b.get("ids") or ([b["id"]] if b.get("id") else [])) if i]


# ── the rings ─────────────────────────────────────────────────────────────────────
def _presented_key():
    """The credential on this request, or None. NEVER read from the query string: a secret in a URL
    ends up in access logs, referrer headers and browser history."""
    direct = request.headers.get(PROFILE_KEY_HEADER)
    if direct:
        return direct.strip()
    auth = request.headers.get("Authorization") or ""
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    return (_body().get("profile_key") or "").strip() or None


def acting_profile():
    """Who is making this request. A presented credential is authoritative; without one the caller
    is the browser UI behind authentik and acts as the bound profile (there is no platform-user →
    profile mapping yet, and inventing one here would be a second identity model)."""
    key = _presented_key()
    if key:
        p = profiles.by_key(key)
        if not p:
            raise ProfileError("מפתח הפרופיל אינו תקף", 401)
        return p
    inst, reason = cx.resolve_active()
    if reason or not inst:
        return None
    if inst.get("protocol") not in adapters.PRIVATE_PROTOCOLS:
        return None                 # bound to a remote account — there is no engine profile acting
    return profiles.by_instance(inst.get("id")) or profiles.get(inst.get("account_hint"))


def require_profile():
    p = acting_profile()
    if not p:
        raise ProfileError("אין פרופיל פעיל לבקשה הזו", 401)
    if p["status"] != profiles.STATUS_ACTIVE:
        raise ProfileError("הפרופיל מושעה", 403)
    return p


def require_admin():
    p = require_profile()
    if not p["is_admin"]:
        raise ProfileError("נדרשות הרשאות מנהל", 403)
    return p


def require_self_or_admin(pid):
    p = require_profile()
    if p["id"] != pid and not p["is_admin"]:
        raise ProfileError("אפשר לשנות רק את הפרופיל שלך", 403)
    return p


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
@app.get("/api/folders")
def api_folders():
    inst, ad = _use()
    return jsonify({"folders": ad.folders(),
                    "connection": {"id": inst.get("id"), "protocol": inst.get("protocol"),
                                   "label": inst.get("label"),
                                   "profile_id": inst.get("profile_id"),
                                   "is_private": inst.get("is_private")}})


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
    if view and view in adapters.views_for(ad):
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
    files = _need(ad, "media_files", "תצוגות מדיה")(kind)
    todo = [f for f in files if not f.get("probed") or (kind == "audio" and not media_jobs.has_peaks(f["id"]))]
    if todo:
        media_jobs.probe_later(todo[:200])
    return jsonify({"files": files})


@app.get("/api/file/<fid>/thumb")
def api_file_thumb(fid):
    """The file's picture (webp) at about `s` pixels; 404 when it has none. Kept for a week in the
    browser: a file's bytes never change under its id."""
    _, ad = _use()
    item = _need(ad, "_file", "תמונות ממוזערות")(fid)
    if not item:
        return jsonify({"error": "הקובץ אינו קיים"}), 404
    data = media_jobs.thumb(item, request.args.get("s") or 256)
    if not data:
        return jsonify({"error": "אין תמונה לקובץ הזה"}), 404
    return Response(data, mimetype="image/webp",
                    headers={"Cache-Control": "private, max-age=604800, immutable", "X-Content-Type-Options": "nosniff"})


@app.get("/api/file/<fid>/peaks")
def api_file_peaks(fid):
    """An audio file's waveform — 600 loudness values between 0 and 1."""
    _, ad = _use()
    item = _need(ad, "_file", "גל קול")(fid)
    if not item:
        return jsonify({"error": "הקובץ אינו קיים"}), 404
    if request.args.get("cached") and not media_jobs.has_peaks(item["id"]):
        # a list asks without starting the work: the background job measures it (see _store, api_media)
        return jsonify({"error": "גל הקול עוד לא נמדד"}), 404, {"Cache-Control": "no-store"}
    vals = media_jobs.peaks(item)
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
    if "star" not in adapters.ops_for(ad)["optional_ops"]:
        return jsonify({"error": "החיבור הזה אינו תומך בסימון בכוכב"}), 501
    return jsonify(ad.star(ids, bool(b.get("starred", True))))


@app.get("/api/storage")
def api_storage():
    """Bytes used by THIS profile, file count, the trash's share, and a ceiling only if configured."""
    _, ad = _use()
    if "storage" not in adapters.ops_for(ad)["optional_ops"]:
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
    return jsonify({"folder": ad.create_folder(str(b.get("name") or ""), str(b.get("parent") or ""))}), 201


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
    # what the views show about a picture, a video or a recording (and a recording's waveform) is found
    # out now, in the background — not when somebody first opens it
    if isinstance(item, dict) and item.get("id") and media_jobs.wants_probe(item):
        media_jobs.probe_later([item])
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
            done.append(_store(ad, src, size, md5, f.filename, f.mimetype, folder))
        except (requests.RequestException, GoogleAuthError, AdapterError) as e:
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


@app.post("/api/uploads")
def tus_create():
    """Open a session. tus headers (`Upload-Length`, `Upload-Metadata: name <b64>,folder <b64>,
    path <b64>,mime <b64>,mode <b64>`) or a JSON body {size, name, folder|path, mime, mode}."""
    _, ad = _use()
    if request.headers.get("Upload-Length"):
        size = int(request.headers["Upload-Length"])
        meta = uploads.parse_metadata(request.headers.get("Upload-Metadata"))
    else:
        b = request.get_json(silent=True) or {}
        size, meta = int(b.get("size") or 0), {k: str(b.get(k) or "") for k in ("name", "folder", "path", "mime", "mode", "system", "remux")}
    if meta.get("path"):
        _need(ad, "ensure_path", "נתיבים")
    s = uploads.create(ad.profile_id if hasattr(ad, "profile_id") else "", size, meta)
    return jsonify({"id": s["id"], "offset": 0, "size": s["size"]}), 201, \
        {**TUS, "Location": f"api/uploads/{s['id']}", "Upload-Offset": "0"}


def _session_answer(s, status=200):
    body = {k: s.get(k) for k in ("id", "name", "size", "offset", "state", "error", "file")}
    return jsonify(body), status, {**TUS, "Upload-Offset": str(s["offset"]), "Upload-Length": str(s["size"]),
                                   "Cache-Control": "no-store"}


@app.route("/api/uploads/<uid>", methods=["HEAD", "GET"])
def tus_status(uid):
    _, ad = _use()
    s = uploads.status(uid, getattr(ad, "profile_id", ""))
    if s.get("state") == "complete":                    # every byte is in and nothing finished it
        s = uploads.finish_async(uid, getattr(ad, "profile_id", ""), _session_store(ad))
    return _session_answer(s)


@app.patch("/api/uploads/<uid>")
def tus_patch(uid):
    """The next piece at `Upload-Offset`. The piece that completes the file starts finishing it and
    answers 202 — the client then polls GET until `state` is `done` (with the stored file) or `failed`."""
    _, ad = _use()
    try:
        offset = int(request.headers.get("Upload-Offset", ""))
    except ValueError:
        raise uploads.UploadError("Upload-Offset חסר", 400)
    pid = getattr(ad, "profile_id", "")
    s = uploads.append(uid, pid, offset, request.stream, request.content_length)
    if s["offset"] == s["size"]:
        s = uploads.finish_async(uid, pid, _session_store(ad))
        return _session_answer(s, 202)
    return "", 204, {**TUS, "Upload-Offset": str(s["offset"])}


@app.delete("/api/uploads/<uid>")
def tus_delete(uid):
    _, ad = _use()
    uploads.remove(uid, getattr(ad, "profile_id", ""))
    return "", 204, TUS


@app.get("/api/uploads")
def tus_list():
    """This profile's unfinished sessions — what the page offers to resume after a reload."""
    _, ad = _use()
    return jsonify({"uploads": uploads.open_sessions(getattr(ad, "profile_id", ""))})


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
    return jsonify({"ok": True, "count": ad.trash(_ids(b), bool(b.get("restore")))})


@app.post("/api/delete")
def api_delete():
    """Permanent delete — only of what is in the trash."""
    b = request.get_json(silent=True) or {}
    _, ad = _use()
    return jsonify({"ok": True, "deleted": ad.delete(_ids(b))})


@app.get("/api/file/<fid>/content")
def api_file_content(fid):
    """The bytes of a file this profile owns, streamed with Range; `?dl=1` downloads. Serving the
    content is the "opened" event that orders Recent — counted once, on the request that starts at
    the first byte, not on every seek of a player."""
    _, ad = _use()
    rng = request.headers.get("Range")
    if "touch" in adapters.ops_for(ad)["optional_ops"] and (not rng or rng.replace(" ", "").startswith("bytes=0-")):
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
    kids = [f for f in ad.folders() if (f.get("parent") or "") == fid]
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
    `mode=replace` trashes the existing one first. The body streams through a temp file (md5 and
    size must be known before storage takes it), so a recording of any size is fine."""
    _, ad = _use()
    path = request.args.get("path") or ""
    parts = path.rstrip("/").rsplit("/", 1)
    if len(parts) != 2 or not parts[1].strip():
        return jsonify({"error": "path must end in a file name"}), 400
    folder = _need(ad, "ensure_path", "נתיבים")(parts[0] or "/", request.args.get("system") or None)
    name = parts[1]
    mode = request.args.get("mode") or "new"
    if mode == "replace":
        old = ad.resolve_path(path)
        if old and old[0] == "file":
            ad.trash([old[1]["id"]])
    else:
        name = ad.free_name(folder, name)
    with tempfile.TemporaryFile(dir=os.environ.get("DRIVE_UPLOAD_DIR", "/data/uploads")
                                if os.path.isdir(os.environ.get("DRIVE_UPLOAD_DIR", "/data/uploads")) else None) as tmp:
        h, size = hashlib.md5(), 0
        for buf in iter(lambda: request.stream.read(1024 * 1024), b""):
            h.update(buf)
            tmp.write(buf)
            size += len(buf)
        if size > uploads.MAX_SIZE:
            return jsonify({"error": "הקובץ גדול מהמותר"}), 413
        tmp.seek(0)
        item = _store(ad, tmp, size, h.hexdigest(), name, request.headers.get("Content-Type"), folder)
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
    if callable(getattr(ad, "store_file", None)):
        src, size, md5 = _spooled(f)
        item = ad.store_file(src, size, md5, name, f.mimetype, folder)
        rows = q(DFILE_COLS + "WHERE id=%s AND profile=%s", (item["id"], ad.profile_id))
        return jsonify(_dfile(*rows[0]))
    return jsonify(_op("op_upload", folder, name, f.mimetype, f.read()))


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


# ── public byte-serve — the share link, PROFILE-INDEPENDENT by design ─────────────
@app.get("/file/d/<oid>/view")
@app.get("/file/d/<oid>")
def file_view(oid):
    """/file/d/<id>/view — the shareable link written into documents and fetched by other services.
    Profile-independent (a link written last year must resolve to the same bytes whichever profile is
    bound today) and never enumerating: the exact opaque id is the capability. A trashed file is not
    served; a user's file renders inline only when its type cannot run anything; `?dl=1` downloads."""
    got = public_stream(oid, request.headers.get("Range"))
    if not got:
        return jsonify({"error": "הקובץ אינו קיים או שהועבר לאשפה"}), 404
    rs, name, mime, md5 = got
    if rs.status_code >= 400 and rs.status_code != 416:
        rs.close()
        return jsonify({"error": "הקובץ אינו זמין באחסון"}), 502 if rs.status_code >= 500 else 404
    hdrs = media.serve_headers(name, mime, "attachment" if request.args.get("dl") else "inline", etag=md5)
    for h in ("Content-Length", "Content-Range"):
        if rs.headers.get(h):
            hdrs[h] = rs.headers[h]
    return Response(rs.iter_content(65536), status=rs.status_code, headers=hdrs, direct_passthrough=True)


@app.get("/healthz")
def healthz():
    q("SELECT 1")
    return jsonify({"status": "ok"})


# ── Platform service contract (§2): manifest / readyz / connection management ──────
@app.get("/manifest")
def manifest():
    """What this service is and what it can do — the console discovers drive from here. `connection`
    is what THIS profile can do, by introspection of the live adapter, so the UI gates a control
    before the user presses it; null (with a reason) when nothing resolves."""
    conn = None
    try:
        inst, ad = adapters.resolve()
        caps = adapters.ops_for(ad)
        conn = {"id": inst.get("id"), "protocol": inst.get("protocol"),
                "is_private": inst.get("is_private"), "profile_id": inst.get("profile_id"),
                "views": adapters.views_for(ad), **caps,
                "paths": callable(getattr(ad, "resolve_path", None)),
                "folder_ops": callable(getattr(ad, "trashed_folders", None)),
                "streams": callable(getattr(ad, "store_file", None))}
    except (AdapterError, GoogleAuthError) as e:
        conn = {"error": getattr(e, "message", str(e))}
    return jsonify({
        "service": "drive",
        "protocols": list(adapters.BY_PROTOCOL),
        "private_protocols": sorted(adapters.PRIVATE_PROTOCOLS),
        "ops": list(adapters.CANONICAL_OPS),
        "optional_ops": list(adapters.PROTOCOL_OPS),
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
        inst, ad = adapters.resolve()
        reason = ad.probe()
    except (AdapterError, GoogleAuthError) as e:
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
        acting = profiles.public(acting_profile())
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


@app.get("/connections/<cid>/probe")
def connections_probe(cid):
    """Verify ONE connection without selecting it (§4b step 4: a connection is verified, not added).
    Same probe /readyz runs, so what the connect flow shows and what n8n trusts cannot disagree."""
    inst = cx.get_instance(cid)
    if not inst:
        return jsonify({"error": f"unknown connection {cid!r}"}), 404
    try:
        reason = adapters.for_instance(inst).probe()
    except (AdapterError, GoogleAuthError) as e:
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
    """Add a connection to an EXISTING account. A `drive_local` instance means "this credential,
    that profile", and it is accepted only once THE KEY IS VERIFIED — a private connection naming a
    profile it cannot authenticate as is the "added but never verified" row the contract forbids.
    Creating a NEW identity is POST /engine/profiles, which mints the credential and the instance."""
    b = request.get_json(force=True, silent=True) or {}
    proto, label, secret = b.get("protocol"), b.get("label"), b.get("secret")
    if not proto or not label or secret is None:
        return jsonify({"error": "protocol, label and secret required"}), 400
    hint = b.get("account_hint")
    if proto == "drive_google_service_account":
        import json as _json
        raw = (secret or {}).get("service_account_json") or ""
        try:
            parsed = _json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            return jsonify({"error": "ה־JSON של חשבון השירות אינו תקין"}), 400
        if not isinstance(parsed, dict) or parsed.get("type") != "service_account" \
                or not parsed.get("client_email") or not parsed.get("private_key"):
            return jsonify({"error": "קובץ JSON אינו חשבון שירות תקין — חסרים שדות type / client_email / private_key"}), 400
        secret = parsed
        hint = hint or parsed.get("client_email")
    if proto in adapters.PRIVATE_PROTOCOLS:
        key = (secret or {}).get("api_key")
        p = profiles.by_key(key) if key else None
        if not p:
            return jsonify({"error": "מפתח הפרופיל אינו תקף. ליצירת פרופיל חדש יש להשתמש "
                                     "במסך ניהול הפרופילים."}), 400
        if hint and hint != p["id"]:
            return jsonify({"error": "account_hint אינו תואם למפתח"}), 400
        hint = p["id"]
    body, status = cx.add_instance(proto, label, secret, hint)
    return jsonify(body), status


@app.delete("/connections/<cid>")
def connections_delete(cid):
    inst = cx.get_instance(cid)
    if inst and inst.get("protocol") in adapters.PRIVATE_PROTOCOLS:
        # Deleting the instance alone would strand its profile: the identity would survive with its
        # credential nowhere, and the next reconcile would rotate a key nobody asked to rotate.
        return jsonify({"error": "זהו פרופיל של המנוע המקומי — הסרה נעשית במסך ניהול הפרופילים",
                        "profile_id": inst.get("account_hint")}), 400
    body, status = cx.delete_instance(cid)
    # Drop a now-dangling binding so the service falls back to the default rather than a dead one.
    if 200 <= status < 300 and cx.active() == cid:
        cx.unbind()
    return jsonify(body), status


# ── the ENGINE plane: profiles on the private drive engine ────────────────────────
# Same route names in mail and chat. The profile screen is NOT the connect wizard: creating an
# identity and connecting to one are different acts.
@app.get("/engine/profiles")
def engine_profiles_list():
    """admin ring. The list carries each profile's instance id so the UI can bind straight to it."""
    me = require_admin()
    insts, _err = cx.vault_instances()
    out = []
    for p in profiles.listing():
        inst = bootstrap.instance_for(p["id"], insts)
        rec = profiles.public(p)
        rec["connection_id"] = (inst or {}).get("id")
        rec["declared"] = bootstrap.ours(p["id"])
        out.append(rec)
    return jsonify({"ok": True, "acting_as": me["id"], "profiles": out,
                    "engine": adapters.LocalAdapter.protocol})


@app.get("/engine/whoami")
def engine_whoami():
    """No ring — deliberately: the screen that decides whether to OFFER profile management has to
    be able to ask who it is without already being an admin."""
    me = acting_profile()
    return jsonify({"ok": True, "profile": profiles.public(me),
                    "credentialed": bool(_presented_key()),
                    "connection_id": cx.active(),
                    "is_admin": bool(me and me["is_admin"]),
                    "engine": adapters.LocalAdapter.protocol})


@app.post("/engine/profiles/reconcile")
def engine_profiles_reconcile():
    """admin ring. Force the boot-time reconcile pass; run twice, the second report is empty."""
    require_admin()
    rep = bootstrap.reconcile(force=True, report=True)
    return jsonify({"ok": not rep["errors"], **rep}), (503 if rep["errors"] else 200)


@app.post("/engine/profiles")
def engine_profiles_create():
    """admin ring. Creates the profile AND its vault instance in one operation, and returns the
    credential ONCE — this service stores only its hash and can never show it again."""
    require_admin()
    b = request.get_json(force=True, silent=True) or {}
    pid = str(b.get("id") or "").strip().lower()
    if not profiles.valid_id(pid):
        return jsonify({"error": "מזהה פרופיל חייב להיות אותיות קטנות/ספרות/מקף"}), 400
    if profiles.get(pid):
        return jsonify({"error": f"הפרופיל {pid} כבר קיים"}), 409
    name = str(b.get("display_name") or pid).strip()
    profile, key, iid, err = bootstrap.provision_profile(
        pid, name, bool(b.get("admin", b.get("is_admin"))))
    body = {"ok": True, "profile": profiles.public(profiles.get(pid)), "key": key,
            "connection_id": iid}
    if err:
        # The identity exists; the vault could not be told. Say so — a later reconcile completes it.
        body["ok"] = False
        body["warning"] = f"הפרופיל נוצר אך החיבור לא נוצר עדיין ({err})"
        return jsonify(body), 202
    return jsonify(body), 201


@app.patch("/engine/profiles/<pid>")
def engine_profiles_patch(pid):
    """self (own) / admin (others). Renaming is self; the admin flag and suspension are admin."""
    me = require_self_or_admin(pid)
    cur = profiles.get(pid)
    if not cur:
        return jsonify({"error": "unknown profile"}), 404
    b = request.get_json(force=True, silent=True) or {}
    is_admin = b.get("admin", b.get("is_admin"))
    status = b.get("status")
    if (is_admin is not None or status is not None) and not me["is_admin"]:
        return jsonify({"error": "רק מנהל יכול לשנות הרשאות או להשעות פרופיל"}), 403
    if status not in (None, profiles.STATUS_ACTIVE, profiles.STATUS_SUSPENDED):
        return jsonify({"error": "status must be active or suspended"}), 400
    profiles.require_last_admin_survives(
        pid,
        demoting=(is_admin is not None and not bool(is_admin) and cur["is_admin"]),
        suspending=(status == profiles.STATUS_SUSPENDED))
    p = profiles.update(pid, display_name=b.get("display_name"),
                        is_admin=None if is_admin is None else bool(is_admin), status=status)
    if cur.get("instance_id"):
        # A suspended or demoted profile must stop serving IMMEDIATELY, not when its cached adapter
        # expires — the cache is keyed on the connection id.
        adapters.invalidate(cur["instance_id"])
    return jsonify({"ok": True, "profile": profiles.public(p)})


@app.post("/engine/profiles/<pid>/key")
def engine_profiles_rotate(pid):
    """self (own) / admin (others). Mints a replacement credential into the profile's EXISTING vault
    instance, so the connection id — and every binding and stored reference to it — survives."""
    require_self_or_admin(pid)
    if not profiles.get(pid):
        return jsonify({"error": "unknown profile"}), 404
    inst = bootstrap.instance_for(pid)
    profile, key = profiles.rotate(pid)
    if inst:
        ok = cx.update_secret(inst["id"], {"api_key": key, "profile_id": pid})
        adapters.invalidate(inst["id"])
        if not ok:
            return jsonify({"ok": False, "profile": profiles.public(profile), "key": key,
                            "connection_id": inst["id"], "vault_updated": False,
                            "warning": "המפתח הוחלף אך לא נשמר בכספת — יש לנסות שוב"}), 202
        return jsonify({"ok": True, "profile": profiles.public(profile), "key": key,
                        "connection_id": inst["id"], "vault_updated": True})
    iid, err = bootstrap.mint_instance(pid, profile["display_name"], key)
    return jsonify({"ok": not err, "profile": profiles.public(profiles.get(pid)), "key": key,
                    "connection_id": iid, "vault_updated": not err,
                    **({"warning": err} if err else {})}), (202 if err else 200)


@app.delete("/engine/profiles/<pid>")
def engine_profiles_delete(pid):
    """admin ring. Removes ACCESS — the profile row and its vault instance. NEVER the files: rows
    keep their `profile` value, so re-creating the profile under the same id restores the view."""
    require_admin()
    if not profiles.get(pid):
        return jsonify({"error": "unknown profile"}), 404
    profiles.require_last_admin_survives(pid, removing=True)
    inst = bootstrap.instance_for(pid)
    if inst:
        if cx.active() == inst["id"]:
            cx.unbind()
        cx.delete_instance(inst["id"])
        adapters.invalidate(inst["id"])
    profiles.delete(pid)
    bootstrap.unmark(pid)
    return jsonify({"ok": True, "id": pid, "removed_connection": (inst or {}).get("id"),
                    "data_kept": True})


# ── engines / providers ───────────────────────────────────────────────────────────
@app.get("/engines")
def engines():
    """Engine-first catalogue (§5e). `private` tells a caller whether profiles can be CREATED here
    or only CONNECTED to."""
    return jsonify({"engines": [
        {"id": "drive_local", "app": "drive", "name": "אחסון מקומי", "icon": "hard-drive",
         "private": True, "creates_profiles": True,
         "description": "האחסון שמובנה במערכת. כל פרופיל מקבל דרייב משלו, והקבצים נשארים אצלך."},
        {"id": "drive_google_oauth", "app": "drive", "name": "Google Drive", "icon": "cloud",
         "private": False, "creates_profiles": False,
         "description": "החשבון שלך ב־Google. הקבצים נשארים ב־Drive; המערכת עובדת עליהם ישירות."},
        {"id": "drive_google_service_account", "app": "drive", "name": "Google Drive — חשבון שירות",
         "icon": "cloud", "private": False, "creates_profiles": False,
         "description": "גישה דרך Service Account — ללא צורך בהתחברות של משתמש."},
    ]})


@app.get("/providers")
def providers():
    """Provider-first catalog for the guided connect flow (§4b): users pick a PROVIDER, and each
    provider offers auth methods that each map to exactly one engine."""
    return jsonify({"providers": [
        {"id": "local", "name": "אחסון מקומי", "icon": "hard-drive", "builtin": True,
         "engine": "drive_local", "private": True,
         "description": "האחסון שמובנה במערכת. עובד מיד, בלי חשבון חיצוני, והקבצים נשארים אצלך.",
         "auth_methods": [{"id": "profile", "label": "פרופיל במנוע המקומי",
                           "protocol": "drive_local", "needs": [], "recommended": True,
                           "private": True,
                           "can": "ניהול תיקיות וקבצים, העלאה, אשפה, חיפוש וקישורים ציבוריים — "
                                  "בנפרד לכל פרופיל.",
                           "explain": "פרופילים נוצרים במסך ניהול הפרופילים; כאן בוחרים באיזה "
                                      "פרופיל הדרייב פועל."}]},
        {"id": "google_drive", "name": "Google Drive", "icon": "cloud",
         "engine": "drive_google_oauth", "private": False,
         "description": "החשבון שלך ב־Google. הקבצים נשארים ב־Drive; המערכת עובדת עליהם ישירות.",
         "auth_methods": [
             {"id": "oauth", "label": "התחברות עם Google",
              "protocol": "drive_google_oauth", "needs": [], "recommended": True,
              "private": False,
              "can": "צפייה, העלאה, העברה, שינוי שם ומחיקה בקבצים של החשבון שתאשר.",
              "explain": "נפתח חלון של Google. לאחר האישור החשבון נוצר כאן ואפשר לבדוק "
                         "אותו ולהפעיל אותו. אפשר לסגור את החלון בכל שלב — לא ייווצר חיבור.",
              "start_url": f"{CONNECTIONS_PUBLIC_URL}/oauth/google-workspace-grant/start"
                           f"?as_instance=1&go=1"},
             {"id": "service_account", "label": "חשבון שירות (Service Account)",
              "protocol": "drive_google_service_account", "needs": [], "recommended": False,
              "private": False,
              "fields": [{"name": "service_account_json",
                          "label": "תוכן קובץ ה־JSON של חשבון השירות",
                          "type": "textarea"}],
              "can": "גישה מלאה דרך חשבון שירות — ללא צורך בהתחברות של משתמש.",
              "explain": "הורד את קובץ ה־JSON של חשבון השירות מ־Google Cloud Console ("
                         "IAM & Admin → Service Accounts → Keys) והדבק את תוכנו כאן. "
                         "חשוב: ודא שחשבון השירות קיבל גישה לתיקיות הרצויות ב־Drive.",
              "help_url": "https://cloud.google.com/iam/docs/service-account-overview"},
         ]},
    ]})


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
