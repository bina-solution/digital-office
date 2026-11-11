"""drive-local — the office's own storage, an ENGINE of «קבצים» (apps/drive/ENGINES.md, DGO-1500).

`drive_local` is a private engine the office runs: the index in postgres (`drive_files`, `drive_folders`,
`drive_profiles`), the bytes in supabase storage (bucket `drive`). It has N PROFILES — an identity
holding a credential, declared in app.json (`engine.profiles`) or made in «ניהול פרופילים»; making one
makes its vault instance in the same operation (profiles.py, bootstrap.py).

It serves the generic `drive` app over drive-engine.v1 (engine_rpc.py) and has no screen of its own:
its drives, its profiles and their state are shown in «קבצים». Three things are its own beside the
protocol, and «קבצים» hands them over verbatim (`routes` in /ops):
  * `/engine/*` — the profile plane (the same route names mail and chat have);
  * `/file/d/<id>/view` — the share link, PROFILE-INDEPENDENT by design;
  * the pictures, waveforms and facts of its own files (media_jobs.py, from its own storage).

AUTHORIZATION — three rings, checked here, enforced in the adapter's QUERIES:
    data   any active profile — every drive op, scoped to its own rows
    self   any active profile — read/update itself, rotate its own key
    admin  is_admin only      — create/edit/suspend/delete OTHER profiles
The acting profile is the one whose key the request presents (`X-Drive-Profile-Key`). Without a key the
request is «קבצים»'s screen behind SSO, and the profile of the drive «קבצים» is bound to acts — asked of
«קבצים» itself (GET /connections/active), never taken from anything the caller sent: before the split a
keyless caller acted as the bound profile, and a caller must not be able to choose another.
"""
import json
import os
import time

import requests
from flask import Flask, Response, g, jsonify, request

import bootstrap
import connections_client as cx
import engine_rpc
import media
import media_jobs
import profiles
from engine_rpc import EngineError
from local import (DFILE_COLS, LocalAdapter, _dfile, ensure_schema, public_stream, q)
import local as local_engine
from opsupport import AdapterError
from profiles import ProfileError

local_engine.ON_DELETE.append(media_jobs.forget)

_SENTRY_DSN = os.getenv("SENTRY_DSN")
if _SENTRY_DSN:
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=_SENTRY_DSN, environment=os.getenv("SENTRY_ENVIRONMENT", os.getenv("DEPLOYMENT_NAME", "production")),
                        release=os.getenv("SENTRY_RELEASE"), traces_sample_rate=0.0, send_default_pii=False)
    except Exception:  # never let telemetry break the app
        pass

app = Flask(__name__)
PROFILE_KEY_HEADER = engine_rpc.PROFILE_KEY_HEADER
DRIVE_URL = os.environ.get("DRIVE_URL", "http://drive:8975")
PROTOCOL = LocalAdapter.protocol
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "provider.json"), encoding="utf-8") as _f:
    PROVIDER = json.load(_f)

# ── one-time provisioning, RETRIED until the DB and the vault are actually there ───
# On a cold bring-up this service reaches gunicorn before supabase-db accepts TCP; a bare call at import
# used to leave the worker unprovisioned for life. The profile reconciler runs here for the same reason:
# in-process with direct DB access (the one path exempt from profile authentication), idempotent.
_SCHEMA_OK = False
_PROFILES_OK = False


def _provision():
    global _SCHEMA_OK, _PROFILES_OK
    if not _SCHEMA_OK:
        if not ensure_schema():
            return
        try:
            media_jobs.ensure_table()
        except Exception as e:
            print("[drive-local] media table deferred:", e, flush=True)
            return
        _SCHEMA_OK = True
    if not _PROFILES_OK:
        try:
            _PROFILES_OK = bootstrap.reconcile()
        except Exception as e:      # a reconciler must never take the service down with it
            print("[drive-local] profile reconcile deferred:", e, flush=True)


@app.before_request
def _provision_before_request():
    _provision()


_provision()


# ── the adapter of one profile, with what this engine adds to it ──────────────────
class EngineAdapter(LocalAdapter):
    """A profile's drive, plus the facts and pictures this engine draws of its own bytes. The probe of
    a picture, a video or a recording is started here — when it is stored and when the media views ask
    — because only this engine holds those bytes."""

    def media_files(self, kind, limit=3000):
        files = super().media_files(kind, limit)
        todo = [f for f in files if not f.get("probed") or (kind == "audio" and not media_jobs.has_peaks(f["id"]))]
        if todo:
            media_jobs.probe_later(todo[:200])
        return files

    def store_file(self, src, size, md5, name, mime, folder="", oid=None):
        item = super().store_file(src, size, md5, name, mime, folder, oid)
        if isinstance(item, dict) and item.get("id") and media_jobs.wants_probe(item):
            media_jobs.probe_later([item])
        return item

    def op_store(self, src, size, md5, name, mime, folder=""):
        """The §3 `upload` op, streamed: the stored file in the shape automation reads (drive#file)."""
        item = self.store_file(src, size, md5, name, mime, folder)
        rows = q(DFILE_COLS + "WHERE id=%s AND profile=%s", (item["id"], self.profile_id))
        return _dfile(*rows[0])

    def thumb(self, item, size):
        mine = self._file((item or {}).get("id") or "")
        data = media_jobs.thumb(mine, size) if mine else None
        return (data, "image/webp") if data else None

    def peaks(self, fid, cached=False):
        """An audio file's waveform (600 values 0..1), or None. `cached` asks without starting the work."""
        item = self._file(fid)
        if not item or (cached and not media_jobs.has_peaks(item["id"])):
            return None
        return media_jobs.peaks(item)


_SECRET_TTL = 30
_secret_cache = {}      # cid -> (expires_at, secret)
_adapter_cache = {}     # (cid, fingerprint) -> (expires_at, adapter)


def invalidate(cid=None):
    if cid is None:
        _secret_cache.clear()
        _adapter_cache.clear()
        return
    _secret_cache.pop(cid, None)
    for k in [k for k in _adapter_cache if k[0] == cid]:
        _adapter_cache.pop(k, None)


def _secret(cid):
    now = time.time()
    hit = _secret_cache.get(cid)
    if hit and hit[0] > now:
        return hit[1]
    got = cx.get_secret(cid)
    if got is None:
        raise AdapterError("שירות החשבונות אינו זמין — לא ניתן לקרוא את מפתח הפרופיל", 503)
    sec = got.get("secret") or {}
    _secret_cache[cid] = (now + _SECRET_TTL, sec)
    return sec


def adapter_for(cid):
    """The adapter of one of this engine's instances, built FROM ITS CREDENTIAL and cached by the key's
    fingerprint (a rotated key keeps its id: an id-keyed cache would serve the dead one)."""
    inst = cx.get_instance(cid)
    if not inst:
        raise AdapterError(f"unknown connection {cid!r}", 404)
    sec = _secret(cid)
    fp = profiles.fingerprint(sec.get("api_key"))
    now = time.time()
    hit = _adapter_cache.get((cid, fp))
    if hit and hit[0] > now:
        return hit[1]
    ad = EngineAdapter(inst, secret=sec)
    _adapter_cache[(cid, fp)] = (now + _SECRET_TTL, ad)
    return ad


# ── the rings ─────────────────────────────────────────────────────────────────────
def _presented_key():
    """The credential on this request, or None. NEVER from the query string (logs, referrers, history)."""
    direct = request.headers.get(PROFILE_KEY_HEADER)
    if direct:
        return direct.strip()
    auth = request.headers.get("Authorization") or ""
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    b = request.get_json(silent=True) if request.is_json else None
    return ((b or {}).get("profile_key") or "").strip() or None if isinstance(b, dict) else None


def _profile_of(inst):
    return profiles.by_instance(inst.get("id")) or profiles.get(inst.get("account_hint"))


def bound():
    """{"id", "bound", "is_private"} — the drive «קבצים» acts as when nobody names one, as «קבצים» says; asked
    once per request. Empty when it does not answer: then no keyless request acts as anyone."""
    if "drive_bound" in g:
        return g.drive_bound
    try:
        r = requests.get(DRIVE_URL + "/connections/active", timeout=(3, 10))
        doc = r.json() if r.ok else {}
    except (requests.RequestException, ValueError):
        doc = {}
    g.drive_bound = doc if isinstance(doc, dict) else {}
    return g.drive_bound


def acting_profile():
    """Who is making this request: a presented key is authoritative; without one, the profile of the drive
    «קבצים» is bound to, and nobody when it is bound to another engine's drive or does not answer."""
    key = _presented_key()
    if key:
        p = profiles.by_key(key)
        if not p:
            raise ProfileError("מפתח הפרופיל אינו תקף", 401)
        return p
    b = bound()
    inst = cx.get_instance(b["id"]) if b.get("is_private") and b.get("id") else None
    return _profile_of(inst) if inst else None


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


@app.errorhandler(AdapterError)
def _adapter_error(e):
    return jsonify({"error": e.message}), e.status


@app.errorhandler(ProfileError)
def _profile_error(e):
    return jsonify({"error": e.message}), e.status


# ── drive-engine.v1 ─────────────────────────────────────────────────────────────────
class Engine:
    def ops(self):
        return {**PROVIDER, "service": "drive-local", "routes": ["/engine/", "/file/d/"],
                "protocols": {PROTOCOL: {"private": True}},
                "engines": [{"id": PROTOCOL, "app": "drive", "name": "אחסון הלשכה", "icon": "hard-drive",
                             "private": True, "creates_profiles": True,
                             "description": "האחסון שמובנה בלשכה. כל פרופיל מקבל דרייב משלו, והקבצים נשארים אצלכם."}],
                "providers": [{"id": "local", "name": "אחסון הלשכה", "icon": "hard-drive", "builtin": True,
                               "engine": PROTOCOL, "private": True,
                               "description": "האחסון שמובנה בלשכה. עובד מיד, בלי חשבון חיצוני, והקבצים נשארים אצלכם.",
                               "auth_methods": [{"id": "profile", "label": "פרופיל באחסון הלשכה",
                                                 "protocol": PROTOCOL, "needs": [], "recommended": True, "private": True,
                                                 "can": "ניהול תיקיות וקבצים, העלאה, אשפה, חיפוש וקישורים ציבוריים — "
                                                        "בנפרד לכל פרופיל.",
                                                 "explain": "פרופילים נוצרים במסך ניהול הפרופילים; כאן בוחרים באיזה "
                                                            "פרופיל הדרייב פועל."}]}]}

    def adapter(self, cid):
        return adapter_for(cid)

    def as_error(self, e):
        if isinstance(e, ProfileError):
            return EngineError(e.message, e.status, "profile")
        if isinstance(e, AdapterError):
            return EngineError(e.message, e.status, "adapter")
        return None

    def check_key(self, cid, key):
        """A key of profile B may not act on profile A's drive: `connection_id` is a field the caller
        controls, and without this it would decide whose files they get."""
        me = profiles.by_key(key)
        if not me:
            raise ProfileError("מפתח הפרופיל אינו תקף", 401)
        inst = cx.get_instance(cid)
        target = _profile_of(inst) if inst else None
        if target and target["id"] != me["id"]:
            raise ProfileError(f"המפתח שייך לפרופיל «{me['display_name']}» ואינו יכול לפעול בשם "
                               f"«{target['display_name']}»", 403)

    def accounts(self, instances):
        """The vault rows of `drive_local`, said in a person's words: the profile's name, whether it is an
        admin, and a row whose profile is gone says so instead of looking healthy. The first admin profile
        is `default`: what an office that chose nothing works on."""
        try:
            admin = profiles.first_admin()
        except Exception:
            admin = None
        out = []
        ids = {i.get("id") for i in instances}
        for inst in instances:
            if inst.get("protocol") != PROTOCOL:
                continue
            row = dict(inst, engine=PROTOCOL, is_private=True, app="drive", profile_id=inst.get("account_hint"))
            try:
                p = _profile_of(inst)
            except Exception:            # the DB is not a dependency of LISTING
                p = None
            if p:
                row.update(is_admin=p["is_admin"], profile_status=p["status"], label=p["display_name"] or row.get("label"))
                # the profile's OWN instance (its row's `instance_id`, the authoritative map) — not a second
                # row that carries the same hint
                # (a row with no id yet — or an id the vault no longer has — is found by its hint, as
                # bootstrap.instance_for recovers it: a stale map must not leave the office with no default)
                own = p.get("instance_id")
                row["primary"] = own == inst.get("id") or not own or own not in ids
                row["default"] = bool(admin and p["id"] == admin["id"] and row["primary"])
            else:
                row.update(profile_status="missing", status="needs_action",
                           reason="הפרופיל שהחיבור הזה מייצג אינו קיים יותר")
            out.append(row)
        return out

    def connect(self, b):
        """A `drive_local` instance means «this credential, that profile», accepted only once THE KEY IS
        VERIFIED. Making a NEW identity is POST /engine/profiles, which mints the key and the instance."""
        label, secret, hint = b.get("label"), b.get("secret"), b.get("account_hint")
        if b.get("protocol") != PROTOCOL or not label or secret is None:
            return {"error": "protocol, label and secret required"}, 400
        key = (secret or {}).get("api_key")
        p = profiles.by_key(key) if key else None
        if not p:
            return {"error": "מפתח הפרופיל אינו תקף. ליצירת פרופיל חדש יש להשתמש במסך ניהול הפרופילים."}, 400
        if hint and hint != p["id"]:
            return {"error": "account_hint אינו תואם למפתח"}, 400
        return cx.add_instance(PROTOCOL, label, secret, p["id"])

    def disconnect(self, cid):
        # Deleting the instance alone would strand its profile: the identity would survive with its key
        # nowhere, and the next reconcile would rotate a key nobody asked to rotate.
        inst = cx.get_instance(cid)
        return {"error": "זהו פרופיל של המנוע המקומי — הסרה נעשית במסך ניהול הפרופילים",
                "profile_id": (inst or {}).get("account_hint")}, 400


ENGINE = Engine()
app.register_blueprint(engine_rpc.blueprint(ENGINE))


@app.get("/healthz")
def healthz():
    q("SELECT 1")
    return jsonify({"status": "ok"})


# ── the ENGINE plane: profiles (same route names in mail and chat) ─────────────────
@app.get("/engine/profiles")
def engine_profiles_list():
    """admin ring. The list carries each profile's instance id so the screen can bind straight to it."""
    me = require_admin()
    insts, _err = cx.vault_instances()
    out = []
    for p in profiles.listing():
        inst = bootstrap.instance_for(p["id"], insts)
        rec = profiles.public(p)
        rec["connection_id"] = (inst or {}).get("id")
        rec["declared"] = bootstrap.ours(p["id"])
        out.append(rec)
    return jsonify({"ok": True, "acting_as": me["id"], "profiles": out, "engine": PROTOCOL})


@app.get("/engine/whoami")
def engine_whoami():
    """No ring — the screen that decides whether to OFFER profile management asks who it is first."""
    me = acting_profile()
    return jsonify({"ok": True, "profile": profiles.public(me), "credentialed": bool(_presented_key()),
                    "connection_id": bound().get("bound"),
                    "is_admin": bool(me and me["is_admin"]), "engine": PROTOCOL})


@app.post("/engine/profiles/reconcile")
def engine_profiles_reconcile():
    require_admin()
    rep = bootstrap.reconcile(force=True, report=True)
    return jsonify({"ok": not rep["errors"], **rep}), (503 if rep["errors"] else 200)


@app.post("/engine/profiles")
def engine_profiles_create():
    """admin ring. The profile AND its vault instance in one operation; the key is returned ONCE."""
    require_admin()
    b = request.get_json(force=True, silent=True) or {}
    pid = str(b.get("id") or "").strip().lower()
    if not profiles.valid_id(pid):
        return jsonify({"error": "מזהה פרופיל חייב להיות אותיות קטנות/ספרות/מקף"}), 400
    if profiles.get(pid):
        return jsonify({"error": f"הפרופיל {pid} כבר קיים"}), 409
    name = str(b.get("display_name") or pid).strip()
    _profile, key, iid, err = bootstrap.provision_profile(pid, name, bool(b.get("admin", b.get("is_admin"))))
    cx.forget()
    body = {"ok": True, "profile": profiles.public(profiles.get(pid)), "key": key, "connection_id": iid}
    if err:
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
        pid, demoting=(is_admin is not None and not bool(is_admin) and cur["is_admin"]),
        suspending=(status == profiles.STATUS_SUSPENDED))
    p = profiles.update(pid, display_name=b.get("display_name"),
                        is_admin=None if is_admin is None else bool(is_admin), status=status)
    if cur.get("instance_id"):
        invalidate(cur["instance_id"])        # a suspended profile stops serving NOW, not when a cache expires
    return jsonify({"ok": True, "profile": profiles.public(p)})


@app.post("/engine/profiles/<pid>/key")
def engine_profiles_rotate(pid):
    """self / admin. A new key into the profile's EXISTING instance, so its id — and every binding and
    stored reference to it — survives."""
    require_self_or_admin(pid)
    if not profiles.get(pid):
        return jsonify({"error": "unknown profile"}), 404
    inst = bootstrap.instance_for(pid)
    profile, key = profiles.rotate(pid)
    if inst:
        ok = cx.update_secret(inst["id"], {"api_key": key, "profile_id": pid})
        invalidate(inst["id"])
        if not ok:
            return jsonify({"ok": False, "profile": profiles.public(profile), "key": key,
                            "connection_id": inst["id"], "vault_updated": False,
                            "warning": "המפתח הוחלף אך לא נשמר בכספת — יש לנסות שוב"}), 202
        return jsonify({"ok": True, "profile": profiles.public(profile), "key": key,
                        "connection_id": inst["id"], "vault_updated": True})
    iid, err = bootstrap.mint_instance(pid, profile["display_name"], key)
    cx.forget()
    return jsonify({"ok": not err, "profile": profiles.public(profiles.get(pid)), "key": key,
                    "connection_id": iid, "vault_updated": not err,
                    **({"warning": err} if err else {})}), (202 if err else 200)


@app.delete("/engine/profiles/<pid>")
def engine_profiles_delete(pid):
    """admin ring. Removes ACCESS — the profile row and its vault instance. NEVER the files: rows keep
    their `profile`, so making the profile again under the same id brings the view back. A binding of
    «קבצים» to it then names a missing drive, which «קבצים» shows as such and lets a person move off."""
    require_admin()
    if not profiles.get(pid):
        return jsonify({"error": "unknown profile"}), 404
    profiles.require_last_admin_survives(pid, removing=True)
    inst = bootstrap.instance_for(pid)
    if inst:
        cx.delete_instance(inst["id"])
        invalidate(inst["id"])
    profiles.delete(pid)
    bootstrap.unmark(pid)
    return jsonify({"ok": True, "id": pid, "removed_connection": (inst or {}).get("id"), "data_kept": True})


# ── the share link — PROFILE-INDEPENDENT by design ────────────────────────────────
@app.get("/file/d/<oid>/view")
@app.get("/file/d/<oid>")
def file_view(oid):
    """/file/d/<id>/view — the link written into documents and fetched by other services. A link written
    last year resolves to the same bytes whichever profile is bound today; never enumerating (the exact
    opaque id is the capability); a trashed file is not served; a user's file renders inline only when its
    type cannot run anything; `?dl=1` downloads."""
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
