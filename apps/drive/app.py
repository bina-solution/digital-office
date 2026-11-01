"""drive — THE drive platform service (contract: ai/context/platform-service-contract.md).

Three planes, one service:
  * the ENGINE plane — `drive_local` is a private engine we run, and it has N PROFILES. A profile is
    an identity holding a credential; it is declared in app.json or created here, and creating one
    creates its vault instance in the same operation. See profiles.py / bootstrap.py.
  * the CONNECTION plane (§2) — every profile, private or remote, is an ordinary vault instance.
    The BINDING (which one this drive acts as) lives here, as a {scope -> id} map.
  * the OP plane — every op runs through an adapter (`adapters/`). The UI plane (`/api/*`, the
    SSO-gated browser) runs on the account the operator selected — the BOUND profile.
    The §3 CANONICAL OPS (`/list /download /upload /move /update /delete /createFromText`, what
    n8n's driveApi01 calls) are different on purpose: they never fall back to the binding.
    `connection_id`/`profile_id` is REQUIRED on every one of them — omit both and the call is
    refused (400, naming what to pass) rather than silently running as whatever the console
    happens to be bound to. See `_explicit_connection_required` (2026-08-06): that silent
    fallback was one default causing three independent failures — a mail registry missing
    `drive_profile_id` quarantining its whole deposit pile, demo-injection nodes that would have
    written the owner's real Drive, and 16 test-suite call sites 503ing or silently querying the
    wrong backend — all because the binding on this host is a Google service account with no
    storage of its own.

The UI is domain-native (§5): folders · files · preview · upload · move · trash · search. It knows
nothing about any app above it; apps register their own UI through /extensions (§4c) and this
service renders those specs without interpreting them.

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
import os

import requests
from flask import Flask, Response, jsonify, request, send_from_directory

import adapters
import bootstrap
import connections_client as cx
import extensions
import profiles
from adapters import AdapterError
from adapters.google import GoogleAuthError
from adapters.local import ensure_schema, q, stream
from profiles import ProfileError

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

PUBLIC_HOST = os.environ.get("DRIVE_PUBLIC_HOST", "drive.localhost")
CONNECTIONS_PUBLIC_URL = os.environ.get("CONNECTIONS_PUBLIC_URL", "https://connections.localhost").rstrip("/")
PROFILE_KEY_HEADER = "X-Drive-Profile-Key"

# ── one-time provisioning, RETRIED until the DB and the vault are actually there ───
# Schema provisioning needs supabase-db, and on a cold bring-up this service reaches gunicorn first —
# psycopg2 raises `Connection refused` and, when this was a bare call at import, that was the end of
# it: the worker served the rest of its life with an unprovisioned schema.
#
# The PROFILE RECONCILER runs in the same place and for the same reason. It is in-process with
# direct DB access — that is what exempts it from profile authentication and resolves the
# chicken-and-egg of needing an admin key in order to create the admin. It is idempotent and
# ledger-backed, it NEVER re-mints a credential for a profile that already has an instance, and a
# connections outage costs it a retry rather than the boot.
_SCHEMA_OK = False
_PROFILES_OK = False


def _provision():
    global _SCHEMA_OK, _PROFILES_OK
    if not _SCHEMA_OK:
        if not ensure_schema():
            return                  # DB still coming up — the next request tries again
        _SCHEMA_OK = True
    if not _PROFILES_OK:
        try:
            _PROFILES_OK = bootstrap.reconcile()
        except Exception as e:      # a reconciler must never take the service down with it
            print("[drive] profile reconcile deferred:", e, flush=True)


@app.before_request
def _provision_before_request():
    # /healthz is polled by the container healthcheck every 30s, so this re-arms on its own even
    # on a deployment with no user traffic at all.
    _provision()


_provision()

# Retire what the deleted bootstrap shim registered. The store is a VOLUME, so removing the code
# that seeded INDOX's sync rail did not remove the rail. Idempotent, and keyed on a marker only the
# shim ever wrote, so an app's own registration is untouched. See extensions.retire_bootstrap.
try:
    _retired = extensions.retire_bootstrap()
    if _retired:
        print(f"[drive] retired {_retired} bootstrap extension(s)", flush=True)
except Exception as _e:            # a read-only/corrupt /data must not stop the drive from serving
    print("[drive] bootstrap retirement skipped:", _e, flush=True)


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
    human, ambient choice, not an identity an automated caller ever declared. On this host that
    binding is the Google SERVICE ACCOUNT (no personal storage, no Shared Drive, every write
    refused by Google itself), and three independent things broke from the one cause: every mail
    registry missing `drive_profile_id` quarantined 100% of its deposits after 5 attempts; the
    demo-injection nodes carried no `connection_id` and would have written the owner's REAL client
    Drive; and 16 `driveApi01` call sites across 5 E2E suites omitted `profile_id`, killing 6 of 8
    suites with 503s while the survivors silently searched the wrong backend and found nothing.

    So the §3 CANONICAL OPS (the automation surface — `/list /download /upload /move /update
    /delete /createFromText`, always reached through `_op()`) no longer accept the ambient binding
    as a default AT ALL: they refuse loudly, naming exactly what was missing and every connection
    the caller could have named instead, rather than silently doing the wrong thing to the wrong
    account. This does NOT apply to the UI plane (`/api/*`) — the browser SPA behind SSO has no
    other identity to declare (module docstring §authorization: "the SSO session is the
    authentication and the binding is the identity"), and that path already fails loudly on a
    dangling binding (connections_client.resolve_active, the 2026-07-17 fix). Automation always has
    an identity to declare; a human clicking through the SPA does not.

    Reads are refused exactly like writes, not warned-and-allowed: a `list`/`download` against the
    wrong backend does not error, it returns wrong or empty results that an unattended pipeline acts
    on as ground truth — that is failure mode #3 above, functionally silent data loss, not a
    survivable one.

    No staged (warn-then-refuse) rollout, and this is the one place the decision needs a real
    argument rather than a default: a repo-wide caller survey (every n8n workflow + every
    non-n8n/Python caller, 2026-08-06) found the INDOX API, the E2E-loadtest harness, and the
    webapp's own automation helpers ALL already pass an explicit id — but ~44 driveApi01 call sites
    in `apps/indox/blueprint/n8n/`, `apps/chat/blueprint/n8n/whatsappSendDoc01.json` and
    `apps/google-workspace-agent/blueprint/n8n/gwaHealthCheck01.json` still do not (see
    `scripts/refactor/drive-connection-lint.py`, G46, wired KNOWN FAILING because those files are
    outside this fix's ownership boundary). Staging would protect exactly those 44 — and that is the
    argument AGAINST staging: every one is already silently wrong today (writing/reading against a
    service account with no storage), so a warn period would spend days logging a corruption the
    service can already name precisely, while the writes keep landing in the wrong place. Refusing
    immediately does not take down a working path — none of these 44 were working correctly — it
    converts each one from "silently wrong, invisible" to "loud 400, actionable," which is a strict
    improvement and the fastest route to someone actually fixing them.
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

    `require_explicit` is set by the §3 canonical-ops choke point (`_op`, below): an automation
    call with neither `profile_id` nor `connection_id` is refused before it ever reaches
    `adapters.resolve()`, rather than falling through to the ambient binding — see
    `_explicit_connection_required` for the incident this closes. UI-plane routes (`/api/*`) leave
    this False on purpose: the SSO-gated browser has no other identity to declare and already fails
    loudly on a dangling binding.

    A request presenting profile B's key while naming profile A's connection is REFUSED. Without
    this, `connection_id` would be a field the caller controls that decides whose files they get,
    which is exactly the impersonation the credential exists to remove — just with an extra header.
    A session request (no credential) is not subject to it: it has no claimed identity to contradict,
    and it is already behind the deployment's forward-auth.
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


@app.errorhandler(AdapterError)
def _adapter_error(e):
    return jsonify({"error": e.message}), e.status


@app.errorhandler(ProfileError)
def _profile_error(e):
    return jsonify({"error": e.message}), e.status


@app.errorhandler(GoogleAuthError)
def _google_error(e):
    # 503, not 500: the connection is unusable, the service is fine — that distinction is what the
    # account bar and /readyz are for.
    #
    # …but a MISSING FILE is not an unusable connection. The error now carries the status Google
    # actually returned for object-level misses (404/410) and 503 for everything else, so a caller
    # can tell "retry this later" from "this file will never exist" — n8n was retrying a dead file
    # id 24 times because both arrived as 503. Default keeps the old behaviour for any raise site
    # that does not set one.
    return jsonify({"error": str(e), "connection_id": cx.active()}), getattr(e, "status", 503)


def _ids(b):
    """Every mutation accepts a single id or a bulk ids[] — one consolidated shape."""
    return [i for i in (b.get("ids") or ([b["id"]] if b.get("id") else [])) if i]


# ── the rings ─────────────────────────────────────────────────────────────────────
def _presented_key():
    """The credential on this request, or None.

    Deliberately NEVER read from the query string — the same rule chat's `keyFrom` states: a secret
    in a URL ends up in access logs, referrer headers and browser history, and the convenience is
    not worth a credential that leaks into three places nobody thinks of as a secret store.
    """
    direct = request.headers.get(PROFILE_KEY_HEADER)
    if direct:
        return direct.strip()
    auth = request.headers.get("Authorization") or ""
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    return (_body().get("profile_key") or "").strip() or None


def acting_profile():
    """Who is making this request.

    A presented credential is authoritative and is the only thing that can name a profile OTHER than
    the bound one. With no credential, the caller is the browser UI behind authentik and it acts as
    the bound profile — see the module docstring for why that is the honest answer today rather
    than a hole: there is no platform-user→profile mapping yet, and inventing one here would be a
    second, competing identity model.
    """
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
@app.get("/trash")
@app.get("/search")
@app.get("/folder/<path:_rest>")
@app.get("/p/<path:_rest>")
def index(_rest=None):
    """SPA entry — folder/file state lives in the URL (deep-linkable, back/forward-able):
    /folder/<id>            open a folder
    /folder/<id>/file/<fid> open a folder with the file preview
    /trash                  the trash view
    /p/<place>              a system place (recent, starred, shared) — the page writes this URL
                            itself (pathFor), so a reload of it must find the page, not a 404
    (/file/d/* never reaches this app — traefik routes it to storage.)"""
    return send_from_directory("static", "index.html")


# ── ops (UI plane) — all through the BOUND profile ─────────────────────────────────
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
    """`view=recent|starred|shared` selects a system view; without it this is the folder listing it
    has always been.

    Which views exist is asked of the ADAPTER (`views`, a PROTOCOL op) rather than discovered by
    calling and catching TypeError. An engine that does not implement views gets the folder listing
    and the UI already knows not to offer the tabs.

    `created_after` (RFC3339, optional) is the sync-discovery date bound — a file created before
    it is excluded from the listing itself, not returned-and-filtered downstream. Callers include
    it, they don't invent it: INDOX's `_inventory_drive` derives it from the live
    `OldDocumentMonthsBack` setting. Absent (the historical default) means unbounded, unchanged.
    """
    _, ad = _use()
    view = (request.args.get("view") or "").strip().lower()
    created_after = (request.args.get("created_after") or "").strip() or None
    if view and view in adapters.views_for(ad):
        files = ad.files(request.args.get("folder", ""), request.args.get("trash") == "1",
                         view=view, created_after=created_after)
        folders = ad.shared_folders() if view == "shared" and callable(getattr(ad, "shared_folders", None)) else []
    else:
        files = ad.files(request.args.get("folder", ""), request.args.get("trash") == "1",
                         created_after=created_after)
        folders = []
    return jsonify({"files": files, "folders": folders, "view": view})


@app.post("/api/star")
def api_star():
    """Flag/unflag. Body: {id|ids, starred?:bool}. Idempotent — starring a starred file is a no-op
    that still reports ok, so the UI never has to read before it writes."""
    b = request.get_json(silent=True) or {}
    ids = b.get("ids") or ([b["id"]] if b.get("id") else [])
    if not ids:
        return jsonify({"error": "id or ids required"}), 400
    _, ad = _use()
    if "star" not in adapters.ops_for(ad)["optional_ops"]:
        return jsonify({"error": "this connection does not support starring"}), 501
    return jsonify(ad.star(ids, bool(b.get("starred", True))))


@app.get("/api/storage")
def api_storage():
    """Bytes used by THIS profile, file count, and a ceiling only if one is configured."""
    _, ad = _use()
    if "storage" not in adapters.ops_for(ad)["optional_ops"]:
        return jsonify({"error": "this connection does not report storage"}), 501
    return jsonify(ad.storage())


@app.get("/api/search")
def api_search():
    """Global search across all folders (name match, newest first) — within this profile."""
    term = (request.args.get("q") or "").strip()
    if len(term) < 2:
        return jsonify({"files": []})
    _, ad = _use()
    return jsonify({"files": ad.search(term)})


@app.post("/api/folders")
def api_create_folder():
    b = request.get_json(silent=True) or {}
    name = str(b.get("name") or "").strip()
    if not name:
        return jsonify({"error": "folder name required"}), 400
    if len(name) > 255:
        return jsonify({"error": "folder name is too long"}), 400
    _, ad = _use()
    return jsonify({"folder": ad.create_folder(name, str(b.get("parent") or ""))}), 201


def _upload_refusal(e) -> str:
    """What the PERSON is told when the store does not take a file.

    An adapter's own refusal is a sentence already and is passed on. A transport exception is not:
    `str()` of one is "400 Client Error: Bad Request for url: http://supabase-storage:5000/object/…"
    — the engine's English and an internal address — and that was the upload toast (seen 2026-10-05,
    when a fresh office had no storage bucket yet). It becomes a sentence here, with the status when
    there is one; the engine's own words stay in the log line the caller writes."""
    if not isinstance(e, requests.RequestException):
        return getattr(e, "message", None) or str(e) or "האחסון דחה את הקובץ"
    status = getattr(getattr(e, "response", None), "status_code", None)
    if status:
        return f"האחסון לא קיבל את הקובץ (שגיאה {status}) — הקובץ לא נשמר"
    if isinstance(e, (requests.ConnectionError, requests.Timeout)):
        return "האחסון אינו עונה כרגע — הקובץ לא נשמר. נסו שוב בעוד רגע"
    return "האחסון דחה את הקובץ"


@app.post("/api/upload")
def api_upload():
    fid = request.form.get("folder") or request.args.get("folder", "")
    _, ad = _use()
    done, failed = [], []
    for f in request.files.getlist("files"):
        data = f.read()
        if not data:
            failed.append({"name": f.filename, "error": "קובץ ריק"})
            continue
        try:
            done.append(ad.upload(fid, f.filename, f.mimetype, data))
        except (requests.RequestException, GoogleAuthError) as e:
            # the store rejected/is unreachable — surface a clear per-file error, never a blanket 500
            app.logger.warning("upload of %r failed: %s", f.filename, e)
            failed.append({"name": f.filename, "error": _upload_refusal(e)})
        except Exception as e:
            app.logger.warning("indexing %r failed: %s", f.filename, e)
            failed.append({"name": f.filename, "error": "שמירת המפתח נכשלה"})
    status = 200 if not failed else (207 if done else 502)
    return jsonify({"uploaded": done, "failed": failed}), status


@app.post("/api/rename")
def api_rename():
    b = request.get_json(force=True)
    _, ad = _use()
    ad.rename(b["id"], b["name"])
    return jsonify({"ok": True})


@app.post("/api/move")
def api_move():
    b = request.get_json(force=True)
    _, ad = _use()
    return jsonify({"ok": True, "moved": ad.move(_ids(b), b["to"])})


@app.post("/api/trash")
def api_trash():
    b = request.get_json(force=True)
    _, ad = _use()
    return jsonify({"ok": True, "count": ad.trash(_ids(b), bool(b.get("restore")))})


@app.post("/api/delete")
def api_delete():
    """Permanent delete (trash-only operation)."""
    b = request.get_json(force=True)
    _, ad = _use()
    return jsonify({"ok": True, "deleted": ad.delete(_ids(b))})


@app.get("/api/file/<path:fid>/content")
def api_file_content(fid):
    """Preview/download bytes for the bound profile. The local adapter checks OWNERSHIP before it
    streams: this is the authenticated read path, and it must not become a way around the scoping
    every listing endpoint applies."""
    _, ad = _use()
    # Recent is "recently opened", and serving the bytes IS the open event — the only one the UI
    # cannot fake by rendering a list.
    if "touch" in adapters.ops_for(ad)["optional_ops"]:
        ad.touch(fid)
    status, hdrs, chunks = ad.content(fid, request.headers.get("Range"))
    return Response(chunks, status=status, headers=hdrs)


# ── canonical ops (§3) — the surface n8n calls ────────────────────────────────────
# `POST /<op>` with driveApi01's own op names and params. The ops run through the SAME resolve()
# choke point as the UI, so "which account did that op touch?" has one answer and /readyz already
# reports it. Every op REQUIRES a `connection_id`/`profile_id` — see `_explicit_connection_required`
# — which is what makes automation multi-profile without ever touching, or falling back onto, the
# console's ambient binding.
def _p():
    return request.get_json(silent=True) or {}


def _op(fn, *a, **kw):
    """Run a canonical op on the resolved adapter. `require_explicit=True` is THE gate for the
    2026-08-06 fix: every op on this surface — list and download included, not just the writes —
    must name its connection or is refused before it runs (see `_explicit_connection_required`).
    GoogleAuthError/AdapterError fall through to the error handlers above, so a broken or missing
    connection is a 400/503 naming itself — never a silent local substitution and never a 500."""
    _inst, ad = _use(require_explicit=True)
    if not callable(getattr(ad, fn, None)):
        raise AdapterError("this connection does not support that operation", 501)
    return getattr(ad, fn)(*a, **kw)


@app.post("/list")
def op_list():
    """`createdAfter` (RFC3339, optional) is the sync-discovery date bound the n8n v3 engine's
    drive units pass on every claiming pass, derived from the live `OldDocumentMonthsBack`
    setting (never hardcoded by a caller) — a file created before it is excluded from the listing
    itself, so it is never claimed at all rather than claimed and later classified OLD. Absent
    means unbounded, unchanged from before this parameter existed.

    `query` (optional, Drive `q` syntax) is the caller-supplied search clause. It is AND-ed into
    the clause this layer builds from the other parameters — it does not replace it, so the
    folder/mime/trashed/date bounds still apply and a caller cannot widen its own scope. Absent
    means unchanged behaviour, which is what every sync caller relies on.

    This closes the KNOWN GAP documented at length in adapters/google.py::op_list. The parameter
    was accepted by the n8n GoogleDrive node this surface replaced, two live callers never stopped
    sending it, and it was being silently dropped — turning "find THIS document" into "return the
    first non-folder file in the whole drive". Measured 2026-08-13 before the fix: 0 successful
    finds in 6,861 search attempts over 14 days, against a ground-truth probe (same service
    account, read-only) showing 53.0% of those documents DO have a matching file in Drive."""
    b = _p()
    # `nameContains` (2026-08-21) is the ENGINE-AGNOSTIC way to ask "files whose name contains
    # X". `query` is Google `q` grammar and the local adapter refuses it outright — correctly, a
    # search that quietly returns the wrong thing is worse than one that refuses — which left
    # name-matching reachable on Google only. Both adapters implement this one: google folds it
    # into its q, local into an ILIKE. That is what a canonical op is for.
    files = _op("op_list", b.get("folderId") or "", b.get("limit") or 100,
                b.get("whatToSearch") or "files", bool(b.get("includeTrashed")),
                b.get("createdAfter") or None, b.get("query") or None,
                b.get("nameContains") or None, b.get("nameContainsAny") or None)
    return jsonify({"files": files})


@app.post("/download")
def op_download():
    b = _p()
    status, hdrs, chunks = _op("op_download", b.get("fileId"), b.get("fileIdMode") or "id")
    return Response(chunks, status=status, headers=hdrs)


@app.post("/upload")
def op_upload():
    """multipart: the bytes as `file`, plus `name`/`folderId` form fields. Binary in, binary's
    metadata out — the response is the full drive#file, md5Checksum included."""
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "file required"}), 400
    data = f.read()
    name = request.form.get("name") or f.filename
    return jsonify(_op("op_upload", request.form.get("folderId") or "", name,
                       f.mimetype, data))


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
    """get-or-create a folder PATH ('automations/thumbnails') on the NAMED identity.

    The one folder primitive automations were missing (2026-09-02): every INDOX-owned destination
    (thumbnails, per-pipe upload folders) used to be get-or-created by the INDOX BFF walking this
    app's /api/folders — a cross-app call the BFF is no longer allowed to make. n8n asks here
    instead, through driveApi01's `ensureFolder` op. Idempotent: an existing segment is reused
    (matched by name under its parent), a missing one is created; the LAST segment's id is the
    answer. Identity is explicit (profile_id | connection_id), like every other §3 op.
    """
    b = _p()
    path = str(b.get("path") or "").strip().strip("/")
    if not path:
        return jsonify({"error": "path required"}), 400
    _, ad = _use(require_explicit=True)
    if not hasattr(ad, "folders") or not hasattr(ad, "create_folder"):
        return jsonify({"error": "this engine has no folder tree"}), 400
    existing = ad.folders() or []
    by_key = {(str(f.get("parent") or ""), str(f.get("name") or "")): f for f in existing
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


# ── public byte-serve — LOCAL, PROFILE-INDEPENDENT, and deliberately unchanged ─────
@app.get("/file/d/<oid>/view")
@app.get("/file/d/<oid>")
def file_view(oid):
    """Public byte-serve for /file/d/<id>/view — the canonical shareable link.

    THE DECISION, now that the local engine has profiles: this route stays LOCAL BY CONSTRUCTION
    and PROFILE-INDEPENDENT. It does not resolve the binding, it does not take a profile, and it
    does not change its answer when the connection bar changes.

    Why that is right, and why it is not a hole in the scoping:
      * these links are stored inside documents and fetched by other services. If the route became
        profile-dependent, a link written last year would resolve to different bytes — or to
        nothing — the moment the bar was switched. A share link that depends on who is looking is
        not a share link;
      * it is not a way to READ another profile's drive, because it never ENUMERATES. It takes one
        opaque, unguessable object id and returns exactly that object. Possession of the id is the
        capability, exactly as it is for a Google `?usp=sharing` link, and the traefik router for
        this path already carries no authentik middleware by design;
      * everything that enumerates — folders, files, search, storage, trash — IS scoped, in the
        queries, and the adapter's own /api/file/<id>/content checks ownership before streaming a
        byte. The scoped path and the capability path are separate on purpose.
    """
    rs, name, mime = stream(oid, request.headers.get("Range"))
    passhdr = {"Content-Type": mime, "Accept-Ranges": "bytes",
               "Content-Disposition": "inline"}
    for h in ("Content-Length", "Content-Range"):
        if rs.headers.get(h):
            passhdr[h] = rs.headers[h]
    return Response(rs.iter_content(65536), status=rs.status_code, headers=passhdr)


@app.get("/healthz")
def healthz():
    q("SELECT 1")
    return jsonify({"status": "ok"})


# ── Platform service contract (§2): manifest / readyz / connection management ──────
@app.get("/manifest")
def manifest():
    """What this service is and what it can do — the console discovers drive from here.

    `connection` is what THIS profile can do, derived by introspection from the live adapter, so the
    UI can gate a control before the user presses it instead of after. It is null (with a reason)
    when nothing resolves — a manifest that hides an unresolvable binding would be the same lie
    /readyz exists to prevent.
    """
    conn = None
    try:
        inst, ad = adapters.resolve()
        caps = adapters.ops_for(ad)
        conn = {"id": inst.get("id"), "protocol": inst.get("protocol"),
                "is_private": inst.get("is_private"), "profile_id": inst.get("profile_id"),
                "views": adapters.views_for(ad), **caps}
    except (AdapterError, GoogleAuthError) as e:
        conn = {"error": getattr(e, "message", str(e))}
    return jsonify({
        "service": "drive",
        "protocols": list(adapters.BY_PROTOCOL),
        "private_protocols": sorted(adapters.PRIVATE_PROTOCOLS),
        # from the dispatch tables, not a hand-kept copy
        "ops": list(adapters.CANONICAL_OPS),
        "optional_ops": list(adapters.PROTOCOL_OPS),
        "slots": list(extensions.SLOTS),
        "connection": conn,
        "capabilities": {
            "multi_connection": True,
            "engine_profiles": True,     # N identities on the private engine, declared in app.json
            "local_adapter": True,
            "public_links": True,        # /file/d/<id>/view (local connection only)
            "folders": True,
            "trash": True,
            "search": True,
            "extensions": True,          # §4c: apps register UI into the slots above
            # 2026-08-06: the §3 canonical ops (list/download/upload/move/update/delete/
            # createFromText — everything driveApi01 calls) no longer fall back to the console's
            # active binding when profile_id/connection_id is omitted; they refuse with a 400
            # naming what to pass (see app.py `_explicit_connection_required`). Only the UI plane
            # (/api/*, the SSO-gated browser) still acts as the bound connection.
            "ops_use_active_connection": False,
            "ops_require_explicit_connection": True,
        },
    })


@app.get("/readyz")
def readyz():
    """The only contract n8n needs: does the BOUND connection resolve and its adapter answer?
    A real probe against the real account — never a guess from the instance record.

    Two properties n8n's trust rests on, both structural:
      * a SET binding that does not resolve is a 503 naming the dangling id — never a silent
        downgrade to another account (the 2026-07-17 defect);
      * `connection_id` is the id we ACTUALLY probed, so "ready" can never be about another
        account than the selected one. resolve() is the only way to get an adapter here, which is
        what makes that true rather than merely intended.
    """
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

    A dangling selection is surfaced as its own `needs_action` row (§4b) instead of being papered
    over, so the console can offer the one-click fix and can never disagree with /readyz about
    whether this drive is usable.
    """
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
    """Add a connection to an EXISTING account.

    `drive_local` used to be refused outright, and that refusal was correct while the local drive
    was one global table: a second `drive_local` instance could only ever have served the same
    files under a different name. Now that `drive_files` carries a profile discriminator, a
    `drive_local` instance means something real — "this credential, that profile" — so it is
    accepted, on one condition: THE KEY IS VERIFIED FIRST. A private connection that names a
    profile it cannot authenticate as is exactly the "added but never verified" row the contract
    forbids.

    Creating a NEW identity is not this route. That is POST /engine/profiles, which mints the
    credential and the instance together.
    """
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
        # Removing access to a private profile is a profile operation, and it has its own route.
        return jsonify({"error": "זהו פרופיל של המנוע המקומי — הסרה נעשית במסך ניהול הפרופילים",
                        "profile_id": inst.get("account_hint")}), 400
    body, status = cx.delete_instance(cid)
    # Drop a now-dangling binding so the service falls back to the default rather than a dead one.
    if 200 <= status < 300 and cx.active() == cid:
        cx.unbind()
    return jsonify(body), status


# ── the ENGINE plane: profiles on the private drive engine ────────────────────────
# Same route names in mail and chat. The profile screen is NOT the connect wizard: creating an
# identity and connecting to one are different acts, and merging them is what made "add a user"
# undiscoverable everywhere it was merged.
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
    """No ring — deliberately. The screen that decides whether to OFFER profile management has to be
    able to ask who it is without already being an admin, or the answer is only available to people
    who do not need it."""
    me = acting_profile()
    return jsonify({"ok": True, "profile": profiles.public(me),
                    "credentialed": bool(_presented_key()),
                    "connection_id": cx.active(),
                    "is_admin": bool(me and me["is_admin"]),
                    "engine": adapters.LocalAdapter.protocol})


@app.post("/engine/profiles/reconcile")
def engine_profiles_reconcile():
    """admin ring. Force the boot-time reconcile pass, on demand.

    Idempotence is a claim, and a claim you cannot exercise on a running deployment is a claim
    nobody checks. Run this twice: the second report's `created`/`repaired`/`removed` are empty and
    every `key_fp` is unchanged. That emptiness is the property rule 10 is about.
    """
    require_admin()
    rep = bootstrap.reconcile(force=True, report=True)
    return jsonify({"ok": not rep["errors"], **rep}), (503 if rep["errors"] else 200)


@app.post("/engine/profiles")
def engine_profiles_create():
    """admin ring. Creates the profile AND its vault instance in one operation (rule 7), and returns
    the credential ONCE — this service stores only its hash and can never show it again."""
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
    # `key` appears here and at rotation, and nowhere else in the service. Only its hash is stored.
    body = {"ok": True, "profile": profiles.public(profiles.get(pid)), "key": key,
            "connection_id": iid}
    if err:
        # The identity exists; the vault could not be told. Say so instead of reporting success —
        # a write that did not happen never reports ok (rule 5). A later reconcile completes it.
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
        # A suspended or demoted profile must stop serving IMMEDIATELY, not when its cached
        # adapter happens to expire — the cache is keyed on the connection id and would
        # otherwise keep answering as the profile the operator just changed.
        adapters.invalidate(cur["instance_id"])
    return jsonify({"ok": True, "profile": profiles.public(p)})


@app.post("/engine/profiles/<pid>/key")
def engine_profiles_rotate(pid):
    """self (own) / admin (others). Mints a replacement credential and writes it into the profile's
    EXISTING vault instance, so the connection id — and therefore every binding and every stored
    reference to it — survives the rotation."""
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
    """admin ring. Removes ACCESS — the profile row and its vault instance. NEVER the files: the
    `drive_files` rows keep their `profile` value, so re-creating the profile under the same id
    restores the view of them (rule 8)."""
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
    """Engine-first catalogue: the noun the other services are converging on (§5e).

    `private` is the field that matters — it is what tells a caller whether profiles can be CREATED
    here or only CONNECTED to, without anybody parsing an id for a `-local` suffix.
    """
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
    """What is registered. `spec` is echoed back verbatim: this service stores and renders it, and
    never reads a field of it for meaning."""
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
