"""adapters.local — the built-in drive (protocol `drive_local`), one adapter per PROFILE.

Postgres-native: `drive_files` is the index, supabase storage holds the bytes. Stable id;
rename/move touch metadata only (so stored /file/d/<id>/view links never break); trash is a flag.

WHAT MAKES IT MULTI-PROFILE
`drive_files` carries a `profile` discriminator, and this adapter is constructed FROM A CREDENTIAL:
the instance's vault secret is `{api_key, profile_id}`, the key is verified against the profile row,
and the resulting profile id is stamped into every single statement below. So:

  * data scoping is enforced in the QUERIES, not in the UI (rule 9). There is no endpoint, no
    parameter and no view that can return another profile's rows, because there is no unscoped
    query left in this file — except the two that /file/d/<oid>/view needs, which are marked and
    justified where they are;
  * the adapter's identity comes from its credential, not from the environment (rule 6). There is
    no `LOCALDRIVE_*` env var to read and no ambient "the local drive" to be.
"""
import hashlib
import mimetypes
import os
import random
import time
from datetime import timezone

import requests

import profiles
from db import q  # noqa: F401  (re-exported: app.py's /healthz uses it)

from .opsupport import AdapterError, download_headers, extract_file_id

STORAGE = os.environ.get("STORAGE_URL", "http://storage:5000")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
PUBLIC_HOST = os.environ.get("DRIVE_PUBLIC_HOST", "drive.localhost")


def _toint(x):
    # size is a bigint column -> comes back as a Python int; never call .isdigit() on it.
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def _utc16(when) -> str:
    """`YYYY-MM-DD HH:MM` in UTC — the one shape the page reads a time in (it places it in the
    reader's own zone). CONVERTED, not assumed: `str()` of a timestamptz is written in the database
    SESSION's zone, so a database that is not set to UTC handed the page local time labelled as
    nothing, and the page could not tell."""
    if not when:
        return ""
    try:
        return when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (AttributeError, ValueError, OverflowError):
        return str(when)[:16]


_SCHEMA_READY = False
_BUCKET_READY = False
BUCKET = "drive"


def _bucket_exists_answer(status, text):
    """Did storage say the bucket is THERE? Created now, or already there — both are success.

    Storage answers a second create with 400 and `"error":"Duplicate"` ("The resource already
    exists"); 409 is what newer builds use for the same thing. Pure, so the rule is testable."""
    body = (text or "").lower()
    return status in (200, 201) or (status in (400, 409) and ("already exists" in body or "duplicate" in body))


def ensure_bucket():
    """The bucket the bytes live in — created by the app that owns it, like the index table below.

    It existed only where a SEEDER had run (`scripts/ui-coverage/seed.sh` inserts it for the UI map),
    so on a fresh office the first upload anyone made answered `400 … Bucket not found` (measured
    2026-10-05, hp-laptop: drive enabled, healthy, and unable to store a single file). The bucket is
    this app's own storage, so this app provisions it — public, exactly as the seeder made it,
    because `/file/d/<id>/view` links are written into documents and fetched by other services.

    Idempotent, and retried until it succeeds for the same reason `ensure_schema` is: storage may
    not be answering when the first worker starts. Returns True once the bucket is known to exist.
    """
    global _BUCKET_READY
    if _BUCKET_READY:
        return True
    try:
        r = requests.post(f"{STORAGE}/bucket", json={"id": BUCKET, "name": BUCKET, "public": True},
                          headers={"Authorization": f"Bearer {SERVICE_KEY}"}, timeout=15)
    except requests.RequestException as e:
        print("[drive] ensure_bucket deferred (will retry on the next upload):", e, flush=True)
        return False
    if _bucket_exists_answer(r.status_code, r.text):
        _BUCKET_READY = True
    else:
        print(f"[drive] ensure_bucket: storage answered {r.status_code}: {(r.text or '')[:200]}", flush=True)
    return _BUCKET_READY


def ensure_schema():
    """Self-provision the drive index so a fresh DB works out-of-the-box (bytes live in supabase
    storage; this table is the index). Idempotent — safe to run on every worker boot.

    RETRIES UNTIL IT SUCCEEDS, and that is the point of the `_SCHEMA_READY` flag rather than a
    plain one-shot call. On a cold bring-up `drive` reaches gunicorn before `supabase-db` accepts
    TCP, so the first attempt dies with `Connection refused`. A one-shot call swallowed that and
    NEVER TRIED AGAIN for the life of the worker.

    THIS IS THE ONLY DECLARATION OF `drive_files`. There used to be a second one — a mirror at
    `blueprint/fixtures/schema.sql` — kept "so a fresh database is correct no matter which of the two
    runs first". Two writers of one table is not redundancy, it is a race whose loser is whichever
    file someone forgets to edit, and this repo already shipped that bug: the mirror declared
    `size`/`trashed` as TEXT and had no `starred`/`opened`, so a deployment where the mirror won the
    race answered 500 on /api/storage (`function sum(text) does not exist`) and on
    /api/files?view=recent. It had drifted again by the time it was deleted — five columns
    (`drive_files.name`, `.folder`, `.created_at`, `drive_profiles.display_name`, `.key_hash`) are
    NOT NULL here and were nullable there.

    The mirror could not have been the survivor. It was pure DDL, and the two things that make this
    function correct on a database that is already WRONG cannot be expressed that way:
    `_drop_untenanted_table()` and `_migrate_column_types()`. `ADD COLUMN IF NOT EXISTS` never
    repairs an existing column's type, so a fixture can only ever be right about a database that is
    already right. This runs in-process at boot with retry, on every path that starts the container —
    including installing drive from the apps screen, which runs no hook at all.

    `profile` is the tenancy discriminator (see the module docstring), declared `text NOT NULL` with
    NO DEFAULT. That is what makes "an insert must name its profile" a rule the database enforces
    rather than a convention every future caller has to remember.

    A `drive_files` table WITHOUT that column is DROPPED AND RECREATED (`_drop_untenanted_table`).
    This targets a fresh deployment and says so plainly: the alternative is a column added with a
    transitional default, which means rows that belong to no profile, an owner invented for rows
    nobody recorded an owner for, or a default-to-admin rule that quietly hands one profile every
    pre-existing file. All three are a guess dressed as data. Untenanted rows are DELETED, and a
    deployment that has files it wants keeps them by not being upgraded in place.

    Returns True once the table is provisioned, False while the DB is still unreachable.
    """
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return True
    if not _drop_untenanted_table():
        return False
    try:
        q("""CREATE TABLE IF NOT EXISTS drive_files (
                id text PRIMARY KEY,
                profile text NOT NULL,
                name text NOT NULL,
                folder text NOT NULL DEFAULT '',
                link text, md5 text,
                size bigint NOT NULL DEFAULT 0,
                mime text,
                trashed boolean NOT NULL DEFAULT false,
                starred boolean NOT NULL DEFAULT false,
                opened timestamptz,
                created_at timestamptz NOT NULL DEFAULT now())""")
        q("""CREATE TABLE IF NOT EXISTS drive_folders (
                id text PRIMARY KEY,
                profile text NOT NULL,
                name text NOT NULL,
                parent text NOT NULL DEFAULT '',
                created_at timestamptz NOT NULL DEFAULT now())""")
    except Exception as e:   # DB not ready yet / perms — don't crash the worker, re-arm for next call
        print("[drive] ensure_schema deferred (will retry on the next request):", e, flush=True)
        return False
    _ensure_columns()
    _migrate_column_types()
    _ensure_indexes()
    _SCHEMA_READY = True
    return True


def _drop_untenanted_table():
    """A `drive_files` that predates the tenancy discriminator is DROPPED, not migrated.

    Stated plainly because it destroys rows: on a deployment that already has files, this deletes
    them. It is the right trade here and the reasoning is short — the column has to end up
    `NOT NULL` with no default, and every way of getting there without dropping the table has to
    invent an owner for rows that never recorded one. `''` means the files exist and no profile can
    see them; defaulting to the admin profile hands one identity every pre-existing file, which is
    the exact failure this whole change exists to remove. This targets a FRESH deployment; a live
    one with files worth keeping is not upgraded in place.

    Returns False when the database is unreachable, so `ensure_schema` re-arms rather than declaring
    a table it could not inspect.
    """
    try:
        rows = q("SELECT 1 FROM information_schema.tables WHERE table_name='drive_files'")
        if not rows:
            return True                      # nothing there — the CREATE below is the whole story
        cols = q("SELECT 1 FROM information_schema.columns "
                 "WHERE table_name='drive_files' AND column_name='profile'")
        if cols:
            return True
    except Exception as e:
        print("[drive] tenancy check deferred (will retry):", e, flush=True)
        return False
    try:
        # tenancy-lint: allow-unscoped — counting rows on a table that HAS no profile column, in
        # order to say how many are about to be destroyed. There is nothing to scope by yet.
        n = (q("SELECT count(*) FROM drive_files") or [[0]])[0][0]
        q("DROP TABLE drive_files")
        print(f"[drive] drive_files had no `profile` column — dropped and recreated "
              f"({n} untenanted row(s) removed)", flush=True)
    except Exception as e:
        print("[drive] could not drop the untenanted drive_files table:", e, flush=True)
        return False
    return True


def _ensure_columns():
    """Bring a table that predates a column up to the declaration. `ADD COLUMN IF NOT EXISTS` is
    idempotent, so this is a no-op from the second boot onward.

    `opened` is deliberately NOT `created`. "Recent" means recently *looked at*; sorting it by
    creation date produces a list that never changes no matter what the user does, which is the kind
    of feature that looks implemented and is not.
    """
    # `profile` is deliberately absent from this list. It is NOT a column that gets added to an
    # existing table — a table without it is dropped by _drop_untenanted_table(), because adding it
    # here would need a default and a default is an invented owner.
    for col, ddl in (("starred", "boolean NOT NULL DEFAULT false"),
                     ("opened", "timestamptz")):
        try:
            q(f"ALTER TABLE drive_files ADD COLUMN IF NOT EXISTS {col} {ddl}")
        except Exception as e:
            print(f"[drive] add column {col} skipped:", e, flush=True)


def _ensure_indexes():
    """Every read below is `WHERE profile=... AND ...`; index the leading column so a second profile
    does not turn every listing into a full scan."""
    for name, ddl in (("drive_files_profile_folder_idx", "(profile, folder)"),
                      ("drive_files_profile_trashed_idx", "(profile, trashed)"),
                      ("drive_folders_profile_parent_idx", "(profile, parent)")):
        try:
            table = "drive_folders" if name.startswith("drive_folders_") else "drive_files"
            q(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {ddl}")
        except Exception as e:
            print(f"[drive] index {name} skipped:", e, flush=True)


def _migrate_column_types():
    """Bring a legacy text `size`/`trashed` up to the declared types. Idempotent: reads the live
    types first and only alters what actually drifted, so it is a no-op on a correct table (and on
    every boot after the first).

    Kept — and kept SMALL — because the queries below now compare `trashed` to a real Python bool.
    On a legacy text column that is `text = boolean`, which Postgres refuses outright, and the
    failure surfaces as an EMPTY FILE LIST rather than as an error anybody notices.
    """
    want = {"size": "bigint", "trashed": "boolean"}
    try:
        rows = q("SELECT column_name, data_type FROM information_schema.columns "
                 "WHERE table_name='drive_files' AND column_name = ANY(%s)", (list(want),))
    except Exception as e:
        print("[drive] type check skipped:", e, flush=True)
        return
    for col, actual in rows or []:
        target = want[col]
        if actual == target:
            continue
        using = (f"coalesce(nullif({col}, '')::bigint, 0)" if target == "bigint"
                 else f"coalesce(nullif({col}, '')::boolean, false)")
        default = "0" if target == "bigint" else "false"
        try:
            # DROP DEFAULT first, and it is not optional: postgres refuses to change a column's type
            # while a default it cannot auto-cast is attached — the legacy default here is the
            # STRING 'false'. Observed live: without this, size migrated and trashed did not.
            q(f"ALTER TABLE drive_files ALTER COLUMN {col} DROP DEFAULT")
            q(f"ALTER TABLE drive_files ALTER COLUMN {col} TYPE {target} USING {using}")
            q(f"ALTER TABLE drive_files ALTER COLUMN {col} SET NOT NULL")
            q(f"ALTER TABLE drive_files ALTER COLUMN {col} SET DEFAULT {default}")
            print(f"[drive] migrated drive_files.{col}: {actual} -> {target}", flush=True)
        except Exception as e:
            print(f"[drive] MIGRATION FAILED drive_files.{col} {actual} -> {target}: {e}", flush=True)


#: The scheme of every stored share link. A real deployment serves everything over TLS behind
#: traefik, and a document page on https://console.<domain> embedding an http:// link is MIXED
#: CONTENT the browser refuses silently — measured 2026-09-02 on hacohen-prod: every delivery
#: since the cut-over stored `http://drive.<domain>/file/d/…` and "the links do not work" was
#: exactly that. Dev hosts (*.localhost) stay plain http; DRIVE_PUBLIC_SCHEME overrides either way.
PUBLIC_SCHEME = os.environ.get("DRIVE_PUBLIC_SCHEME") or (
    "http" if PUBLIC_HOST == "localhost" or PUBLIC_HOST.endswith(".localhost") else "https")


def public_link(oid):
    return f"{PUBLIC_SCHEME}://{PUBLIC_HOST}/file/d/{oid}/view"


def stream(oid, range_header=None):
    """(upstream response, name, mime) for the PUBLIC byte-serve path (/file/d/<id>/view).

    ⚠ DELIBERATELY NOT PROFILE-SCOPED — the one unscoped read left in this file, and the reason it
    is exempt from tenancy-lint. These links are written into documents and fetched by other
    services, so they must resolve to the same bytes forever, whichever profile is bound now. The
    object id is the capability: it is opaque and unguessable, it is never enumerated (this takes an
    exact id and returns nothing for anything else), and the route that serves it was already
    public and unauthenticated by design.

    It is therefore not a way to READ another profile's files in any sense the listing endpoints
    are: to use it you must already have been given the link. Everything that enumerates — folders,
    files, search, storage, trash — is scoped, and the adapter's own content route below checks
    ownership before it streams a byte.
    """
    fwd = {"Range": range_header} if range_header else {}
    rs = requests.get(f"{STORAGE}/object/public/drive/{oid}", headers=fwd, stream=True, timeout=60)
    # tenancy-lint: allow-unscoped — the public share link must resolve to the same bytes forever,
    # whichever profile is bound. It takes an exact opaque id and never enumerates; see the
    # docstring above and app.py's /file/d/<oid>/view for the full reasoning.
    row = q("SELECT name, mime FROM drive_files WHERE id=%s", (oid,))
    name = row[0][0] if row else oid
    mime = (row[0][1] if row else None) or rs.headers.get("Content-Type") or "application/octet-stream"
    return rs, name, mime


SELECT_COLS = ("SELECT id, name, folder, size, mime, created_at, starred, opened "
               "FROM drive_files ")
DFILE_COLS = "SELECT id,name,folder,link,md5,size,mime,created_at FROM drive_files "


def _dfile(i, n, f, link, md5, size, mime, created=None):
    """The drive#file lookalike `driveApiLocal01` emitted, so its callers are unaffected.
    `size` is emitted as a STRING to match the real Google Drive API v3 (which returns size as an
    int64-encoded string); the DB column is `bigint`, and processors read it with n8n's string-only
    `.toNumber()` extension — which throws on a raw int."""
    d = {"kind": "drive#file", "id": i, "name": n, "webViewLink": link or public_link(i),
         "md5Checksum": md5, "size": ("0" if size is None else str(size)),
         "mimeType": mime, "parents": [f or "root"]}
    if created is not None:
        d["createdTime"] = created.isoformat() if hasattr(created, "isoformat") else str(created)
    return d


class LocalAdapter:
    """One instance of this class == one profile on the private engine.

    Constructed from the vault secret, never from the environment. `profile_id` is not optional and
    is not defaulted: an adapter that does not know whose drive it is has no business running a
    query, so construction fails loudly instead.
    """

    protocol = "drive_local"

    def __init__(self, instance=None, secret=None):
        self.instance = instance or {}
        self.cid = self.instance.get("id")
        sec = secret or {}
        key = sec.get("api_key")
        pid = sec.get("profile_id") or self.instance.get("account_hint")
        if not key or not pid:
            raise AdapterError("החיבור אינו מכיל מפתח פרופיל — יש ליצור אותו מחדש", 503)
        p = profiles.by_key(key)
        if not p:
            raise AdapterError("מפתח הפרופיל אינו תקף או שהפרופיל הושעה", 403)
        if p["id"] != pid:
            # the secret's own two halves disagree — refuse rather than pick one
            raise AdapterError("החיבור מצביע על פרופיל אחר מזה שהמפתח שייך לו", 403)
        self.profile = p
        self.profile_id = p["id"]
        self.owner_name = p["display_name"] or p["id"]

    # ── row shaping ───────────────────────────────────────────────────────────────
    def _row(self, i, n, f, s, m, c, starred=False, opened=None):
        """`owner` is REAL now. It used to be invented by the frontend (`isMine`), which meant the
        people filter was permanently empty and every file read "only you have access"."""
        return {"id": i, "name": n, "folder": f, "size": _toint(s), "mime": m or "",
                "created": _utc16(c), "link": public_link(i),
                "starred": bool(starred), "opened": _utc16(opened),
                "owner": self.owner_name, "owner_id": self.profile_id, "mine": True,
                "shared": []}

    def _owns(self, fid):
        return bool(q("SELECT 1 FROM drive_files WHERE id=%s AND profile=%s",
                      (fid, self.profile_id)))

    # ── readiness ─────────────────────────────────────────────────────────────────
    def probe(self):
        """None when ready, else a human reason.

        Ready iff the bytes store answers AND this profile is active — a suspended profile is not a
        working account, and a bar that shows it green is the same lie as a probe that never probes.
        """
        if self.profile.get("status") != profiles.STATUS_ACTIVE:
            return "הפרופיל מושעה"
        try:
            r = requests.get(f"{STORAGE}/status", timeout=5)
        except requests.RequestException as e:
            return f"storage unreachable: {e}"
        # any answer below 500 means storage is up and routing; only 5xx is a real outage
        return None if r.status_code < 500 else f"storage unhealthy: HTTP {r.status_code}"

    # ── containers ────────────────────────────────────────────────────────────────
    def folders(self):
        """Explicit folders plus backwards-compatible folders inferred from existing files."""
        explicit = q("SELECT id,name,parent,created_at FROM drive_folders WHERE profile=%s",
                     (self.profile_id,))
        rows = q("SELECT folder, count(*), max(created_at) FROM drive_files "
                 "WHERE profile=%s AND NOT trashed GROUP BY folder", (self.profile_id,))
        # A folder has an OWNER too, and here it is never in doubt: both queries above are scoped to
        # this profile. Left out, the list drew every folder with a red "?" and „לא ידוע” beside
        # files of the same drive that said „אני” (read off the two-office proof screenshots,
        # 2026-10-05) — the same fiction `_row` ended for files, one row type over.
        mine = {"owner": self.owner_name, "owner_id": self.profile_id, "mine": True}
        folders = [{"id": fid, "name": name, "parent": parent or None, "count": 0,
                    "last": _utc16(created) or None, **mine}
                   for fid, name, parent, created in explicit]
        known = {folder["id"] for folder in folders}
        for folder, count, last in rows:
            if folder and folder not in known:
                folders.append({"id": folder, "name": folder, "parent": None, "count": count,
                                "last": _utc16(last) or None, **mine})
        return folders

    def create_folder(self, name, parent=""):
        fid = "ld" + format(int(time.time() * 1000), "x") + format(random.getrandbits(40), "x")
        q("INSERT INTO drive_folders (id,profile,name,parent) VALUES (%s,%s,%s,%s)",
          (fid, self.profile_id, name, parent))
        return {"id": fid, "name": name, "parent": parent or None}

    # ── items ─────────────────────────────────────────────────────────────────────
    def files(self, folder="", trashed=False, view="", created_after=None):
        """`view` is the system-view dimension the UI's left rail selects:

            ""        the folder listing (the historical behaviour, unchanged)
            recent    everything this profile has actually OPENED, most recent first
            starred   everything flagged, newest first
            shared    NOT MODELLED LOCALLY — see below

        `shared` returns empty here on purpose. Profiles give the drive a real notion of an OWNER,
        but not yet of a GRANT: nothing can currently share a file from one profile to another, so
        answering this view with anything at all would be inventing data. The Google adapter, which
        has real sharing, answers it properly.

        `created_after` (RFC3339, applied only to the plain folder listing — the sync source) is
        the same discovery-window bound `op_list` honors below: an old file is excluded from the
        query itself, not returned-and-filtered.
        """
        if view == "recent":
            rows = q(SELECT_COLS + "WHERE profile=%s AND trashed=%s AND opened IS NOT NULL "
                     "ORDER BY opened DESC LIMIT 500", (self.profile_id, trashed))
        elif view == "starred":
            rows = q(SELECT_COLS + "WHERE profile=%s AND trashed=%s AND starred "
                     "ORDER BY created_at DESC LIMIT 500", (self.profile_id, trashed))
        elif view == "shared":
            return []
        elif trashed:
            rows = q(SELECT_COLS + "WHERE profile=%s AND trashed "
                     "ORDER BY created_at DESC LIMIT 500", (self.profile_id,))
        elif created_after:
            rows = q(SELECT_COLS + "WHERE profile=%s AND NOT trashed AND folder=%s "
                     "AND created_at >= %s ORDER BY created_at DESC LIMIT 500",
                     (self.profile_id, folder, created_after))
        else:
            rows = q(SELECT_COLS + "WHERE profile=%s AND NOT trashed AND folder=%s "
                     "ORDER BY created_at DESC LIMIT 500", (self.profile_id, folder))
        return [self._row(*r) for r in rows]

    def views(self):
        """The system views this engine can answer. `shared` is absent, not empty-and-advertised:
        absence of a capability is how an engine says "unsupported" (rule 4), and it lets the UI
        hide the rail entry instead of offering a tab that can only ever be blank."""
        return ["recent", "starred"]

    def star(self, ids, on=True):
        """Flag or unflag. Returns how many rows actually changed, so the caller can tell a no-op
        from a hit rather than assuming success — and a cross-profile id changes nothing."""
        ids = [ids] if isinstance(ids, str) else list(ids or [])
        if not ids:
            return {"ok": True, "changed": 0}
        rows = q("UPDATE drive_files SET starred=%s WHERE id = ANY(%s) AND profile=%s RETURNING id",
                 (bool(on), ids, self.profile_id))
        return {"ok": True, "changed": len(rows), "starred": bool(on)}

    def touch(self, fid):
        """Stamp `opened`. Called when a file's CONTENT is served — opening a file is the only
        event that should move it up Recent, and it is the one the UI cannot fake."""
        try:
            q("UPDATE drive_files SET opened=now() WHERE id=%s AND profile=%s",
              (fid, self.profile_id))
        except Exception as e:
            print("[drive] touch skipped:", e, flush=True)

    def storage(self):
        """Bytes used BY THIS PROFILE, and the ceiling if one is configured.

        Supabase storage exposes no per-bucket quota, so `limit` comes from DRIVE_STORAGE_LIMIT and
        is absent when unset — reporting a made-up ceiling would put a fictional number in a meter
        the operator is meant to trust."""
        rows = q("SELECT count(*), coalesce(sum(size),0) FROM drive_files "
                 "WHERE profile=%s AND NOT trashed", (self.profile_id,))
        n, used = (rows[0] if rows else (0, 0))
        out = {"files": int(n or 0), "used": int(used or 0)}
        lim = os.environ.get("DRIVE_STORAGE_LIMIT", "").strip()
        if lim.isdigit():
            out["limit"] = int(lim)
            out["percent"] = round(100.0 * out["used"] / max(1, out["limit"]), 2)
        return out

    def search(self, term):
        rows = q(SELECT_COLS + "WHERE profile=%s AND NOT trashed AND name ILIKE %s "
                 "ORDER BY created_at DESC LIMIT 200", (self.profile_id, "%" + term + "%"))
        return [self._row(*r) for r in rows]

    def upload(self, folder, filename, mime, data):
        oid = "lf" + format(int(time.time() * 1000), "x") + format(random.getrandbits(40), "x")
        # THE TYPE IS THE FILE'S, NOT THE CLIENT'S DEFAULT (2026-09-02, measured on hacohen-prod):
        # n8n's multipart upload sends every mail attachment as application/octet-stream, the
        # storage keeps that as the object's content-type, /file/d/<id>/view serves it back, and a
        # browser will not render an octet-stream inline — 1,153 PDFs "did not open". Guess from
        # the name whenever the client sent nothing useful; the storage then serves a real type.
        if not mime or mime == "application/octet-stream":
            mime = mimetypes.guess_type(filename or "")[0] or "application/octet-stream"
        # NO DEDUPE ON UPLOAD (2026-09-02, after two tries). Owner Decision 10 (no thumbnail storm:
        # 28,339 byte-identical rasters re-uploaded on every re-run) is met at its source — the
        # raster upload no longer exists — and every dedupe written here broke a caller: bytes-only
        # answered a NEW name with an old file (the bs/gdoc suites resolve fixture links by name);
        # name+bytes answered a fresh upload with a file from hours ago, which the same suites then
        # could not find among the newest hundred they list. An upload is a new object, as it always
        # was; the sync dedupes DOCUMENTS by content hash in the ledger, not files in the drive.
        digest = hashlib.md5(data).hexdigest()
        ensure_bucket()

        def put():
            return requests.post(f"{STORAGE}/object/{BUCKET}/{oid}", data=data,
                                 headers={"Authorization": f"Bearer {SERVICE_KEY}",
                                          "x-upsert": "true", "Content-Type": mime}, timeout=180)

        r = put()
        if r.status_code in (400, 404) and "bucket not found" in (r.text or "").lower():
            # the bucket was removed under a running app (a storage reset): make it and send again,
            # once — a second refusal is storage's own answer and goes to the caller as it is
            global _BUCKET_READY
            _BUCKET_READY = False
            if ensure_bucket():
                r = put()
        r.raise_for_status()
        q("INSERT INTO drive_files (id,profile,name,folder,link,md5,size,mime,trashed) "
          "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,false) ON CONFLICT (id) DO NOTHING",
          (oid, self.profile_id, filename, folder, public_link(oid),
           digest, len(data), mime))
        return {"id": oid, "name": filename, "owner": self.owner_name}

    def rename(self, fid, name):
        q("UPDATE drive_files SET name=%s WHERE id=%s AND profile=%s",
          (name, fid, self.profile_id))

    def move(self, ids, to):
        rows = q("UPDATE drive_files SET folder=%s WHERE id = ANY(%s) AND profile=%s RETURNING id",
                 (to, ids, self.profile_id))
        return len(rows)

    def trash(self, ids, restore=False):
        rows = q("UPDATE drive_files SET trashed=%s WHERE id = ANY(%s) AND profile=%s RETURNING id",
                 (not restore, ids, self.profile_id))
        return len(rows)

    def delete(self, ids):
        """Permanent delete (trash-only operation): storage object + index row."""
        deleted = 0
        for oid in ids:
            row = q("SELECT trashed FROM drive_files WHERE id=%s AND profile=%s",
                    (oid, self.profile_id))
            if not row or not row[0][0]:
                continue          # not ours, or not in trash
            requests.delete(f"{STORAGE}/object/drive/{oid}",
                            headers={"Authorization": f"Bearer {SERVICE_KEY}"}, timeout=60)
            q("DELETE FROM drive_files WHERE id=%s AND profile=%s", (oid, self.profile_id))
            deleted += 1
        return deleted

    def content(self, fid, range_header=None):
        """(status, headers, byte-iterator) — the same bytes /file/d/<id>/view serves, but ONLY for
        a file this profile owns. This is the authenticated read path, so it checks ownership
        first: without that, `GET /api/file/<other profile's id>/content` would be an unscoped read
        wearing an op route's clothes."""
        if not self._owns(fid):
            raise AdapterError("הקובץ אינו קיים בדרייב של הפרופיל הזה", 404)
        rs, name, mime = stream(fid, range_header)
        hdrs = {"Content-Type": mime, "Accept-Ranges": "bytes", "Content-Disposition": "inline"}
        for h in ("Content-Length", "Content-Range"):
            if rs.headers.get(h):
                hdrs[h] = rs.headers[h]
        return rs.status_code, hdrs, rs.iter_content(65536)

    # ── canonical ops (§3) ────────────────────────────────────────────────────────
    # The shape here is the one the retired `driveApiLocal01` emitted — a drive#file lookalike — so
    # the hermetic CI lanes that run on this adapter see exactly what they saw before. It is a
    # SUBSET of what the google adapter returns; callers read a handful of keys and tolerate both.

    def op_list(self, folder_id="", limit=100, what_to_search="files", include_trashed=False,
               created_after=None, query=None, name_contains=None, name_contains_any=None):
        # `query` (2026-08-13) exists here ONLY to keep this adapter call-compatible with the
        # google one, which gained it when the dropped-search-clause defect was fixed. `_op()`
        # forwards positionally, so /list now sends six arguments to WHICHEVER adapter is resolved
        # — and without this parameter every local-connection listing would raise
        # `TypeError: too many positional arguments`, EVEN WITH NO QUERY SENT, because
        # `b.get("query") or None` still passes None positionally. That would have broken the sync
        # path for the live local connection (drive_local-19213e58, 5,597 rows, still ingesting).
        #
        # It is deliberately NOT implemented: `query` is Google Drive `q` grammar, and silently
        # approximating it against this SQL-backed store would produce a DIFFERENT result set
        # under the same argument — the failure mode that made the google-side drop so expensive
        # (a search that quietly returns the wrong thing is worse than one that refuses). No live
        # caller sends a query to a local connection; if one ever does, refusing is correct.
        if query:
            raise AdapterError("this connection does not support free-form Drive queries", 501)
        # All four branches are spelled out rather than assembled from an f-string fragment: the
        # tenancy lint reads the SQL a call actually passes, and a WHERE clause hidden behind a
        # variable is exactly the shape that lets an unscoped query through a scoped-looking file.
        # `created_after` (RFC3339) is the sync-discovery date bound `driveApi01`'s v3 units pass
        # on every claiming pass — folded into the query, never a post-filter.
        # One predicate list, not four near-identical branches: adding `name_contains` to the
        # old shape would have meant eight. Semantics are unchanged — same columns, same
        # ordering, same LIMIT, same optional folder/created_after bounds, all parameterised.
        lim = int(limit or 100)
        # profile=%s is written LITERALLY into the statement below, not appended here, so
        # tenancy-lint can still see the discriminator. Collapsing four literal statements
        # into one dynamic join (39eaa8e6) made the predicate invisible to it: the check is
        # static, and " AND ".join(where) is a runtime value. The scoping was never lost --
        # profile was always first in this list -- but a guard that cannot read the code it
        # guards is not protecting anything, and this one exists so that a read crossing
        # profiles is always a decision somebody wrote down.
        where = ["trashed=%s"]
        args = [self.profile_id, bool(include_trashed)]
        if folder_id:
            where.append("folder=%s")
            args.append(folder_id)
        if created_after:
            where.append("created_at >= %s")
            args.append(created_after)
        # `nameContains` is a string OR a list, and a list means AND -- "a name holding all of
        # these". That is what the callers need: find_link asks for the company name AND the short
        # doc id, which is two independent substrings in one filename, in unknown order.
        # `nameContainsAny` is the OR. Two parameters rather than one with a mode flag, because a
        # caller that muddles them gets no results instead of the wrong ones.
        def _like(v):
            # Parameterised, AND % _ and backslash escaped, so a name holding a wildcard
            # character is matched literally. Unescaped, a filter for 'plb_' also matches
            # 'plbX' -- silently wrong, which is exactly the failure the free-form `query`
            # refusal exists to prevent. Proven against the live database:
            #     'dbf_x' ilike '%dbf\_%'  -> t     literal underscore matches
            #     'dbfZx' ilike '%dbf\_%'  -> f     no wildcard leak
            #     'dbfZx' ilike '%dbf_%'   -> t     unescaped, 'dbf_' WOULD match 'dbfZx'
            s = str(v)
            for ch in ('\\', '%', '_'):
                s = s.replace(ch, '\\' + ch)
            return '%' + s + '%'

        for _t in ([name_contains] if isinstance(name_contains, str) else (name_contains or [])):
            where.append("name ILIKE %s")
            args.append(_like(_t))
        _any = ([name_contains_any] if isinstance(name_contains_any, str)
                else (name_contains_any or []))
        if _any:
            where.append("(" + " OR ".join(["name ILIKE %s"] * len(_any)) + ")")
            args.extend(_like(v) for v in _any)
        args.append(lim)
        rows = q(DFILE_COLS + "WHERE profile=%s AND " + " AND ".join(where) +
                 " ORDER BY created_at DESC LIMIT %s", tuple(args))
        return [_dfile(*r) for r in rows]

    def op_download(self, file_id, file_id_mode="id"):
        fid = extract_file_id(file_id, file_id_mode)
        if not self._owns(fid):
            raise AdapterError("הקובץ אינו קיים בדרייב של הפרופיל הזה", 404)
        rs, name, mime = stream(fid)
        if rs.status_code >= 400:
            raise AdapterError(f"הקובץ אינו זמין באחסון (HTTP {rs.status_code})", rs.status_code)
        return rs.status_code, download_headers(name, mime, rs.headers.get("Content-Length")), \
            rs.iter_content(65536)

    def op_upload(self, folder_id, name, mime, data):
        got = self.upload(folder_id or "root", name, mime, data)
        rows = q(DFILE_COLS + "WHERE id=%s AND profile=%s", (got["id"], self.profile_id))
        return _dfile(*rows[0])

    def op_move(self, file_id, to_folder_id):
        rows = q("UPDATE drive_files SET folder=%s WHERE id=%s AND profile=%s "
                 "RETURNING id,name,folder,link,md5,size,mime,created_at",
                 (to_folder_id, file_id, self.profile_id))
        return _dfile(*rows[0]) if rows else {}

    def op_update(self, file_id, new_name):
        rows = q("UPDATE drive_files SET name=%s WHERE id=%s AND profile=%s "
                 "RETURNING id,name,folder,link,md5,size,mime,created_at",
                 (new_name, file_id, self.profile_id))
        return _dfile(*rows[0]) if rows else {}

    def op_delete(self, file_id):
        """Trash, mirroring the google adapter's op_delete — the canonical `delete` op means one
        thing on both."""
        rows = q("UPDATE drive_files SET trashed=true WHERE id=%s AND profile=%s RETURNING id",
                 (file_id, self.profile_id))
        return {"id": file_id, "success": bool(rows)}

    def op_create_from_text(self, name, content, folder_id):
        got = self.upload(folder_id or "root", name or "Untitled",
                          "text/plain", str(content or "").encode("utf-8"))
        return {"id": got["id"]}
