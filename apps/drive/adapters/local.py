"""adapters.local — the built-in drive (protocol `drive_local`), one adapter per PROFILE.

Postgres-native: `drive_files` and `drive_folders` are the index, supabase storage holds the bytes
under the file's id. Ids are stable: rename and move touch metadata only, so a stored
/file/d/<id>/view link never breaks. Trash is a flag; a folder that is trashed takes everything
under it along (`trashed_by` names the folder that did it, so restoring it brings back exactly
those and nothing that was trashed on its own).

WHAT MAKES IT MULTI-PROFILE
Every row carries a `profile`, and this adapter is constructed FROM A CREDENTIAL: the instance's
vault secret is `{api_key, profile_id}`, the key is verified against the profile row, and the
profile id is stamped into every statement below. Scoping is enforced in the queries, not in the
UI; the one unscoped read is the public share link (`public_stream`), marked where it is.

ROOT is ''. Automation used to file a folder-less upload under the literal 'root', which then showed
as a phantom folder named "root"; writes now store '', and reads accept both.
"""
import hashlib
import os
import secrets
import time
import unicodedata
from datetime import timezone

import requests

import media
import profiles
from db import q, tx  # noqa: F401  (q re-exported: app.py's /healthz uses it)

from .opsupport import AdapterError, download_headers, extract_file_id

STORAGE = os.environ.get("STORAGE_URL", "http://storage:5000")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
PUBLIC_HOST = os.environ.get("DRIVE_PUBLIC_HOST", "drive.localhost")
BUCKET = os.environ.get("DRIVE_BUCKET", "drive")
ROOTS = ("", "root")


def _toint(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def _utc16(when) -> str:
    """`YYYY-MM-DD HH:MM` in UTC — the one shape the page reads a time in (it places it in the
    reader's own zone). Converted, not assumed: `str()` of a timestamptz is in the DB session's zone."""
    if not when:
        return ""
    try:
        return when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (AttributeError, ValueError, OverflowError):
        return str(when)[:16]


def new_id(prefix):
    """`lf…` for a file, `ld…` for a folder: the creation time (so ids sort by age) and 64 bits from
    the OS's random source — an id is the capability behind a share link, so it must not be
    predictable from the ones before it."""
    return prefix + format(int(time.time() * 1000), "x") + secrets.token_hex(8)


def clean_name(name):
    """A file or folder name as the index stores it: NFC (a Hebrew name typed on a Mac and the same
    name typed on Windows are one name), trimmed, and never a path."""
    n = unicodedata.normalize("NFC", str(name or "")).strip()
    if not n or n in (".", ".."):
        raise AdapterError("שם ריק אינו שם", 400)
    if "/" in n or "\\" in n:
        raise AdapterError("שם אינו יכול להכיל / או \\", 400)
    if len(n) > 255:
        raise AdapterError("השם ארוך מדי (עד 255 תווים)", 400)
    return n


def split_path(path):
    """'/פגישות/2026-10-28/' → ['פגישות', '2026-10-28']. A segment of '..' is refused, not resolved."""
    segs = [unicodedata.normalize("NFC", s).strip() for s in str(path or "").replace("\\", "/").split("/")]
    segs = [s for s in segs if s and s != "."]
    if ".." in segs:
        raise AdapterError("נתיב אינו יכול להכיל ..", 400)
    return segs


def _root(folder):
    f = str(folder or "")
    return "" if f in ROOTS else f


_SCHEMA_READY = False
_BUCKET_READY = False
#: Called with the ids a permanent delete removed — the media cache drops their pictures (app.py
#: registers it; this module may not import the media jobs, which import it).
ON_DELETE = []

#: What the media views gather from every folder. By type, and by name for files whose type was
#: stored as octet-stream by an older uploader.
_MEDIA = {
    "visual": (r"^(image/(jpeg|png|gif|webp|avif|heic|heif|bmp|tiff)|video/)",
               r"\.(jpe?g|png|gif|webp|avif|heic|heif|bmp|tiff?|mp4|m4v|mov|webm|mkv|avi|3gp)$"),
    "video": (r"^video/", r"\.(mp4|m4v|mov|webm|mkv|avi|wmv|flv|3gp|mpe?g)$"),
    "audio": (r"^audio/", r"\.(mp3|m4a|aac|flac|ogg|oga|opus|wav|wma|weba|amr)$"),
}


def _auth():
    return {"Authorization": f"Bearer {SERVICE_KEY}"}


def _bucket_exists_answer(status, text):
    """Did storage say the bucket is THERE? Created now, or already there — both are success.
    Storage answers a second create with 400 "Duplicate"; newer builds use 409."""
    body = (text or "").lower()
    return status in (200, 201) or (status in (400, 409) and ("already exists" in body or "duplicate" in body))


def ensure_bucket():
    """The bucket the bytes live in, provisioned by the app that owns it. PRIVATE for a new office:
    every byte the drive serves goes through the drive (`stream`), which reads with the service key,
    so nothing needs storage's own public path. A bucket created public earlier stays as it is.
    Idempotent and retried — storage may not be answering when the first worker starts."""
    global _BUCKET_READY
    if _BUCKET_READY:
        return True
    try:
        r = requests.post(f"{STORAGE}/bucket", json={"id": BUCKET, "name": BUCKET, "public": False},
                          headers=_auth(), timeout=15)
    except requests.RequestException as e:
        print("[drive] ensure_bucket deferred (will retry on the next upload):", e, flush=True)
        return False
    if _bucket_exists_answer(r.status_code, r.text):
        _BUCKET_READY = True
    else:
        print(f"[drive] ensure_bucket: storage answered {r.status_code}: {(r.text or '')[:200]}", flush=True)
    return _BUCKET_READY


def ensure_schema():
    """The drive index, provisioned in-process and retried until the database answers (on a cold
    start the drive reaches gunicorn before supabase-db accepts connections). THE ONLY DECLARATION of
    these tables — a second writer of one table is a race whose loser is whichever file someone
    forgot to edit (it happened: a fixture mirror once declared `size` as text).

    `profile` is `text NOT NULL` with no default: an insert must name its owner. A `drive_files`
    without that column is from before profiles existed; it is REFUSED (the drive does not start)
    rather than dropped — it used to be dropped and recreated, which deletes every file on a
    database that is merely older than this code."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return True
    try:
        if q("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='drive_files'") \
                and not q("SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
                          "AND table_name='drive_files' AND column_name='profile'"):
            print("[drive] REFUSING to start: public.drive_files has no `profile` column. It predates "
                  "profiles; migrate it by hand — nothing was changed.", flush=True)
            return False
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
    except Exception as e:   # DB not ready yet — re-arm for the next request
        print("[drive] ensure_schema deferred (will retry on the next request):", e, flush=True)
        return False
    _ensure_columns()
    _migrate_column_types()
    _ensure_indexes()
    _SCHEMA_READY = True
    return True


def _ensure_columns():
    """Bring a table that predates a column up to the declaration; a no-op from the second boot."""
    for table, col, ddl in (("drive_files", "starred", "boolean NOT NULL DEFAULT false"),
                            ("drive_files", "opened", "timestamptz"),
                            ("drive_files", "trashed_by", "text"),
                            ("drive_files", "updated_at", "timestamptz"),
                            ("drive_folders", "trashed", "boolean NOT NULL DEFAULT false"),
                            ("drive_folders", "trashed_by", "text"),
                            ("drive_folders", "starred", "boolean NOT NULL DEFAULT false"),
                            ("drive_folders", "updated_at", "timestamptz"),
                            # the app that keeps this folder (meet, recorder…): it cannot be renamed,
                            # moved or deleted from under the app that writes into it
                            ("drive_folders", "system", "text")):
        try:
            q(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {ddl}")
        except Exception as e:
            print(f"[drive] add column {table}.{col} skipped:", e, flush=True)


def _ensure_indexes():
    for table, name, ddl in (("drive_files", "drive_files_profile_folder_idx", "(profile, folder)"),
                             ("drive_files", "drive_files_profile_trashed_idx", "(profile, trashed)"),
                             ("drive_files", "drive_files_profile_opened_idx", "(profile, opened)"),
                             ("drive_folders", "drive_folders_profile_parent_idx", "(profile, parent)")):
        try:
            q(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {ddl}")
        except Exception as e:
            print(f"[drive] index {name} skipped:", e, flush=True)


def _migrate_column_types():
    """Bring a legacy text `size`/`trashed` up to the declared types (a `text = boolean` comparison
    is refused by Postgres and surfaced as an EMPTY list). Reads the live types first, so this is a
    no-op on a correct table."""
    want = {"size": "bigint", "trashed": "boolean"}
    try:
        rows = q("SELECT column_name, data_type FROM information_schema.columns "
                 "WHERE table_schema='public' AND table_name='drive_files' AND column_name = ANY(%s)",
                 (list(want),))
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
            # the legacy default is the STRING 'false': drop it first or the type change is refused
            q(f"ALTER TABLE drive_files ALTER COLUMN {col} DROP DEFAULT")
            q(f"ALTER TABLE drive_files ALTER COLUMN {col} TYPE {target} USING {using}")
            q(f"ALTER TABLE drive_files ALTER COLUMN {col} SET NOT NULL")
            q(f"ALTER TABLE drive_files ALTER COLUMN {col} SET DEFAULT {default}")
            print(f"[drive] migrated drive_files.{col}: {actual} -> {target}", flush=True)
        except Exception as e:
            print(f"[drive] MIGRATION FAILED drive_files.{col} {actual} -> {target}: {e}", flush=True)


#: The scheme of a stored share link: https behind traefik (an http link inside an https page is
#: mixed content the browser drops silently), plain http on *.localhost. DRIVE_PUBLIC_SCHEME wins.
PUBLIC_SCHEME = os.environ.get("DRIVE_PUBLIC_SCHEME") or (
    "http" if PUBLIC_HOST == "localhost" or PUBLIC_HOST.endswith(".localhost") else "https")


def public_link(oid):
    return f"{PUBLIC_SCHEME}://{PUBLIC_HOST}/file/d/{oid}/view"


def _object(oid, range_header=None):
    """The stored bytes of one object, streamed, read with the service key (works on a private
    bucket and on a public one alike)."""
    fwd = {"Range": range_header} if range_header else {}
    return requests.get(f"{STORAGE}/object/authenticated/{BUCKET}/{oid}", headers={**_auth(), **fwd},
                        stream=True, timeout=(10, 120))


def public_stream(oid, range_header=None):
    """(upstream response, name, mime, md5) for the PUBLIC share link /file/d/<id>/view — or None.

    ⚠ NOT PROFILE-SCOPED, deliberately: the link is written into documents and fetched by other
    services, so it resolves to the same bytes whichever profile is bound. The id is the capability:
    exact, never enumerated. A file in the trash is NOT served — trashing is how a person takes back
    a link they gave out."""
    # tenancy-lint: allow-unscoped — the public share link resolves by its exact opaque id only.
    row = q("SELECT name, mime, md5 FROM drive_files WHERE id=%s AND NOT trashed", (oid,))
    if not row:
        return None
    rs = _object(oid, range_header)
    return rs, row[0][0], row[0][1] or rs.headers.get("Content-Type"), row[0][2]


SELECT_COLS = ("SELECT id, name, folder, size, mime, created_at, starred, opened, md5 "
               "FROM drive_files ")
DFILE_COLS = "SELECT id,name,folder,link,md5,size,mime,created_at FROM drive_files "


def _dfile(i, n, f, link, md5, size, mime, created=None):
    """The drive#file lookalike the n8n ops have always read. `size` is a STRING, as Google's API
    sends it — n8n reads it with `.toNumber()`, which throws on a raw int."""
    d = {"kind": "drive#file", "id": i, "name": n, "webViewLink": link or public_link(i),
         "md5Checksum": md5, "size": ("0" if size is None else str(size)),
         "mimeType": mime, "parents": [_root(f) or "root"]}
    if created is not None:
        d["createdTime"] = created.isoformat() if hasattr(created, "isoformat") else str(created)
    return d


class LocalAdapter:
    """One instance of this class == one profile on the private engine. Constructed from the vault
    secret, never from the environment; without a verified profile it refuses to exist."""

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
            raise AdapterError("החיבור מצביע על פרופיל אחר מזה שהמפתח שייך לו", 403)
        self.profile = p
        self.profile_id = p["id"]
        self.owner_name = p["display_name"] or p["id"]

    # ── row shaping ───────────────────────────────────────────────────────────────
    def _row(self, i, n, f, s, m, c, starred=False, opened=None, md5=None):
        return {"id": i, "name": n, "folder": _root(f), "size": _toint(s), "mime": m or "",
                "created": _utc16(c), "link": public_link(i),
                "starred": bool(starred), "opened": _utc16(opened), "md5": md5 or "",
                "owner": self.owner_name, "owner_id": self.profile_id, "mine": True, "shared": []}

    def _owns(self, fid):
        return bool(q("SELECT 1 FROM drive_files WHERE id=%s AND profile=%s", (fid, self.profile_id)))

    def _file(self, fid):
        rows = q(SELECT_COLS + "WHERE id=%s AND profile=%s", (fid, self.profile_id))
        return self._row(*rows[0]) if rows else None

    def _is_folder(self, fid, live=False):
        return bool(q("SELECT 1 FROM drive_folders WHERE id=%s AND profile=%s" + (" AND NOT trashed" if live else ""),
                      (fid, self.profile_id)))

    def _split_ids(self, ids):
        """A mixed selection → (folder ids, file ids). The page selects both kinds in one list."""
        ids = [i for i in ([ids] if isinstance(ids, str) else list(ids or [])) if i]
        if not ids:
            return [], []
        folders = {r[0] for r in q("SELECT id FROM drive_folders WHERE id = ANY(%s) AND profile=%s",
                                   (ids, self.profile_id))}
        return [i for i in ids if i in folders], [i for i in ids if i not in folders]

    # ── readiness ─────────────────────────────────────────────────────────────────
    def probe(self):
        """None when ready, else a human reason: the store answers AND this profile is active."""
        if self.profile.get("status") != profiles.STATUS_ACTIVE:
            return "הפרופיל מושעה"
        try:
            r = requests.get(f"{STORAGE}/status", timeout=5)
        except requests.RequestException as e:
            return f"storage unreachable: {e}"
        return None if r.status_code < 500 else f"storage unhealthy: HTTP {r.status_code}"

    # ── folders ───────────────────────────────────────────────────────────────────
    def folders(self):
        """Every live folder with its file count, plus folders inferred from files whose `folder`
        names no folder row (written by automation before folders were rows)."""
        explicit = q("SELECT id,name,parent,created_at,system,starred FROM drive_folders "
                     "WHERE profile=%s AND NOT trashed", (self.profile_id,))
        counts = {_root(f): (n, last) for f, n, last in q(
            "SELECT folder, count(*), max(created_at) FROM drive_files "
            "WHERE profile=%s AND NOT trashed GROUP BY folder", (self.profile_id,))}
        mine = {"owner": self.owner_name, "owner_id": self.profile_id, "mine": True}
        out = []
        for fid, name, parent, created, system, starred in explicit:
            n, last = counts.get(fid, (0, None))
            out.append({"id": fid, "name": name, "parent": _root(parent) or None, "count": int(n or 0),
                        "last": _utc16(last or created) or None, "system": system or None,
                        "starred": bool(starred), **mine})
        known = {f["id"] for f in out} | {""}
        trashed = {r[0] for r in q("SELECT id FROM drive_folders WHERE profile=%s AND trashed",
                                   (self.profile_id,))}
        for folder, (n, last) in counts.items():
            if folder not in known and folder not in trashed:
                out.append({"id": folder, "name": folder, "parent": None, "count": int(n or 0),
                            "last": _utc16(last) or None, "system": None, "starred": False, **mine})
        return out

    def create_folder(self, name, parent="", system=None):
        name, parent = clean_name(name), _root(parent)
        if parent and not self._is_folder(parent, live=True):
            raise AdapterError("תיקיית היעד אינה קיימת או שהיא באשפה", 404)
        fid = new_id("ld")
        q("INSERT INTO drive_folders (id,profile,name,parent,system,updated_at) VALUES (%s,%s,%s,%s,%s,now())",
          (fid, self.profile_id, name, parent, system))
        return {"id": fid, "name": name, "parent": parent or None, "system": system}

    def _guard_system(self, ids, verb):
        rows = q("SELECT name, system FROM drive_folders WHERE id = ANY(%s) AND profile=%s AND system IS NOT NULL",
                 (list(ids), self.profile_id))
        if rows:
            raise AdapterError(f"«{rows[0][0]}» היא תיקייה שאפליקציה כותבת אליה ({rows[0][1]}) — "
                               f"אי אפשר {verb} אותה", 409)

    def rename(self, fid, name):
        name = clean_name(name)
        if self._is_folder(fid):
            self._guard_system([fid], "לשנות את שמה של")
            q("UPDATE drive_folders SET name=%s, updated_at=now() WHERE id=%s AND profile=%s",
              (name, fid, self.profile_id))
            return 1
        return len(q("UPDATE drive_files SET name=%s, updated_at=now() WHERE id=%s AND profile=%s RETURNING id",
                     (name, fid, self.profile_id)))

    def _descendants(self, cur, ids):
        """Every folder under `ids` (not including them), via one recursive query."""
        cur.execute("""WITH RECURSIVE t AS (
                           SELECT id FROM drive_folders WHERE parent = ANY(%s) AND profile=%s
                           UNION SELECT f.id FROM drive_folders f JOIN t ON f.parent = t.id WHERE f.profile=%s)
                       SELECT id FROM t""", (list(ids), self.profile_id, self.profile_id))
        return [r[0] for r in cur.fetchall()]

    def move(self, ids, to):
        """Move files and folders into `to` ('' = root). A folder cannot go into itself or under
        one of its own descendants — that would cut a branch off the tree."""
        to = _root(to)
        folders, files = self._split_ids(ids)
        if to and not self._is_folder(to, live=True):
            raise AdapterError("תיקיית היעד אינה קיימת או שהיא באשפה", 404)
        moved = 0
        with tx() as cur:
            if folders:
                self._guard_system(folders, "להעביר")
                if to and (to in folders or to in self._descendants(cur, folders)):
                    raise AdapterError("אי אפשר להעביר תיקייה לתוך עצמה", 409)
                cur.execute("UPDATE drive_folders SET parent=%s, updated_at=now() "
                            "WHERE id = ANY(%s) AND profile=%s", (to, folders, self.profile_id))
                moved += cur.rowcount
            if files:
                cur.execute("UPDATE drive_files SET folder=%s, updated_at=now() "
                            "WHERE id = ANY(%s) AND profile=%s", (to, files, self.profile_id))
                moved += cur.rowcount
        return moved

    def trash(self, ids, restore=False):
        """Trash (or restore) files and folders. A folder takes its whole subtree along, marked
        `trashed_by` it, so restoring it restores exactly what it took."""
        folders, files = self._split_ids(ids)
        n = 0
        with tx() as cur:
            if files:
                if restore:
                    cur.execute("UPDATE drive_files SET trashed=false, trashed_by=NULL, updated_at=now() "
                                "WHERE id = ANY(%s) AND profile=%s", (files, self.profile_id))
                else:
                    cur.execute("UPDATE drive_files SET trashed=true, trashed_by=NULL, updated_at=now() "
                                "WHERE id = ANY(%s) AND profile=%s AND NOT trashed", (files, self.profile_id))
                n += cur.rowcount
            for fid in folders:
                if restore:
                    cur.execute("UPDATE drive_folders SET trashed=false, trashed_by=NULL, updated_at=now() "
                                "WHERE profile=%s AND (id=%s OR trashed_by=%s)", (self.profile_id, fid, fid))
                    n += 1 if cur.rowcount else 0
                    cur.execute("UPDATE drive_files SET trashed=false, trashed_by=NULL "
                                "WHERE profile=%s AND trashed_by=%s", (self.profile_id, fid))
                    continue
                self._guard_system([fid], "למחוק")
                sub = self._descendants(cur, [fid])
                cur.execute("UPDATE drive_folders SET trashed=true, trashed_by=NULL, updated_at=now() "
                            "WHERE id=%s AND profile=%s AND NOT trashed", (fid, self.profile_id))
                if not cur.rowcount:
                    continue
                n += 1
                if sub:
                    cur.execute("UPDATE drive_folders SET trashed=true, trashed_by=%s "
                                "WHERE id = ANY(%s) AND profile=%s AND NOT trashed", (fid, sub, self.profile_id))
                cur.execute("UPDATE drive_files SET trashed=true, trashed_by=%s "
                            "WHERE folder = ANY(%s) AND profile=%s AND NOT trashed", (fid, [fid] + sub, self.profile_id))
        return n

    def delete(self, ids):
        """Permanent delete — only of what is already in the trash. Bytes first; a row goes only
        when its bytes are gone (or were never there), so a failed delete never leaves bytes no
        index row can reach."""
        folders, files = self._split_ids(ids)
        with tx() as cur:
            cur.execute("SELECT id FROM drive_folders WHERE id = ANY(%s) AND profile=%s AND trashed",
                        (folders, self.profile_id))
            roots = [r[0] for r in cur.fetchall()]
            tree = roots + (self._descendants(cur, roots) if roots else [])
            cur.execute("SELECT id FROM drive_files WHERE profile=%s AND trashed AND "
                        "(id = ANY(%s) OR folder = ANY(%s))", (self.profile_id, files, tree))
            victims = [r[0] for r in cur.fetchall()]
        gone = []
        for oid in victims:
            try:
                r = requests.delete(f"{STORAGE}/object/{BUCKET}/{oid}", headers=_auth(), timeout=60)
            except requests.RequestException as e:
                print(f"[drive] delete of {oid} deferred: {e}", flush=True)
                continue
            if r.status_code < 300 or r.status_code in (400, 404):    # deleted, or not there to delete
                gone.append(oid)
            else:
                print(f"[drive] storage kept {oid}: HTTP {r.status_code} {r.text[:120]}", flush=True)
        with tx() as cur:
            if gone:
                cur.execute("DELETE FROM drive_files WHERE id = ANY(%s) AND profile=%s", (gone, self.profile_id))
            if tree and len(gone) == len(victims):
                cur.execute("DELETE FROM drive_folders WHERE id = ANY(%s) AND profile=%s", (tree, self.profile_id))
        for fn in ON_DELETE:
            try:
                fn(gone)
            except Exception as e:
                print("[drive] after-delete hook failed:", e, flush=True)
        return len(gone) + (len(roots) if len(gone) == len(victims) else 0)

    # ── paths: how an agent or an app names a place ───────────────────────────────
    def _child_folder(self, cur, parent, name):
        cur.execute("SELECT id FROM drive_folders WHERE profile=%s AND parent = ANY(%s) AND name=%s "
                    "AND NOT trashed ORDER BY created_at, id LIMIT 1",
                    (self.profile_id, [parent] if parent else list(ROOTS), name))
        r = cur.fetchone()
        return r[0] if r else None

    def resolve_path(self, path):
        """'/הקלטות/x.m4a' → ('file', item) · '/הקלטות' → ('folder', {id,name,path}) · '/' →
        ('folder', root) · None when nothing is there. Among two files of one name the NEWEST wins."""
        segs = split_path(path)
        parent = ""
        with tx() as cur:
            for i, seg in enumerate(segs):
                fid = self._child_folder(cur, parent, seg)
                if fid:
                    parent = fid
                    continue
                if i != len(segs) - 1:
                    return None
                cur.execute(SELECT_COLS + "WHERE profile=%s AND folder = ANY(%s) AND name=%s AND NOT trashed "
                            "ORDER BY created_at DESC LIMIT 1",
                            (self.profile_id, [parent] if parent else list(ROOTS), seg))
                r = cur.fetchone()
                return ("file", self._row(*r)) if r else None
        return ("folder", {"id": parent, "name": segs[-1] if segs else "", "path": "/" + "/".join(segs)})

    def ensure_path(self, path, system=None):
        """Get-or-create every folder of `path`; the last one's id ('' for root). Safe when two
        workers ask at once: each level is created under a transaction-scoped advisory lock on
        (profile, parent, name), so the second one finds the folder the first one made. `system`
        marks the LAST folder as kept by that app."""
        parent = ""
        for seg in split_path(path):
            seg = clean_name(seg)
            with tx() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{self.profile_id}\x1f{parent}\x1f{seg}",))
                fid = self._child_folder(cur, parent, seg)
                if not fid:
                    fid = new_id("ld")
                    cur.execute("INSERT INTO drive_folders (id,profile,name,parent,updated_at) "
                                "VALUES (%s,%s,%s,%s,now())", (fid, self.profile_id, seg, parent))
            parent = fid
        if system and parent:
            q("UPDATE drive_folders SET system=%s WHERE id=%s AND profile=%s AND system IS NULL",
              (system, parent, self.profile_id))
        return parent

    def path_of(self, folder):
        """'/a/b' for a folder id, '/' for root."""
        names, cur_id, seen = [], _root(folder), set()
        while cur_id and cur_id not in seen:
            seen.add(cur_id)
            r = q("SELECT name, parent FROM drive_folders WHERE id=%s AND profile=%s", (cur_id, self.profile_id))
            if not r:
                names.append(cur_id)
                break
            names.append(r[0][0])
            cur_id = _root(r[0][1])
        return "/" + "/".join(reversed(names))

    def free_name(self, folder, name):
        """`name` if no live file in `folder` has it, else 'name (2).ext', 'name (3).ext'…"""
        taken = {r[0] for r in q("SELECT name FROM drive_files WHERE profile=%s AND folder = ANY(%s) AND NOT trashed",
                                 (self.profile_id, [folder] if folder else list(ROOTS)))}
        if name not in taken:
            return name
        stem, dot, ext = name.rpartition(".")
        stem, ext = (stem, "." + ext) if dot and stem else (name, "")
        n = 2
        while f"{stem} ({n}){ext}" in taken:
            n += 1
        return f"{stem} ({n}){ext}"

    # ── items ─────────────────────────────────────────────────────────────────────
    def files(self, folder="", trashed=False, view="", created_after=None, limit=1000, offset=0):
        """A folder's files, or a system view: recent (OPENED, newest first), starred, trash (what
        was trashed on its own or a folder's top). `shared` is not modelled locally — absent from
        `views()`, so the page offers no tab that could only be blank."""
        folders = [_root(folder)] if _root(folder) else list(ROOTS)
        lim, off = max(1, min(int(limit or 1000), 5000)), max(0, int(offset or 0))
        if view == "added":
            rows = q(SELECT_COLS + "WHERE profile=%s AND NOT trashed ORDER BY created_at DESC LIMIT %s OFFSET %s",
                     (self.profile_id, lim, off))
        elif view == "recent":
            rows = q(SELECT_COLS + "WHERE profile=%s AND NOT trashed AND opened IS NOT NULL "
                     "ORDER BY opened DESC LIMIT %s OFFSET %s", (self.profile_id, lim, off))
        elif view == "starred":
            rows = q(SELECT_COLS + "WHERE profile=%s AND NOT trashed AND starred "
                     "ORDER BY created_at DESC LIMIT %s OFFSET %s", (self.profile_id, lim, off))
        elif view == "shared":
            return []
        elif trashed:
            rows = q(SELECT_COLS + "WHERE profile=%s AND trashed AND trashed_by IS NULL "
                     "ORDER BY coalesce(updated_at, created_at) DESC LIMIT %s OFFSET %s", (self.profile_id, lim, off))
        elif created_after:
            rows = q(SELECT_COLS + "WHERE profile=%s AND NOT trashed AND folder = ANY(%s) "
                     "AND created_at >= %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                     (self.profile_id, folders, created_after, lim, off))
        else:
            rows = q(SELECT_COLS + "WHERE profile=%s AND NOT trashed AND folder = ANY(%s) "
                     "ORDER BY created_at DESC LIMIT %s OFFSET %s", (self.profile_id, folders, lim, off))
        return self._with_media([self._row(*r) for r in rows])

    def _with_media(self, items):
        """What the media probe already knows (pixels, duration, title) on the items of a list — one
        query for the page, so a folder's card carries a recording's length as the media views do."""
        ids = [it["id"] for it in items]
        if not ids:
            return items
        try:
            rows = q("SELECT id, w, h, duration, title, artist, album FROM drive_media WHERE id = ANY(%s)", (ids,))
        except Exception:
            return items            # no probe has run yet on this office: the table comes with the first
        known = {r[0]: {k: v for k, v in zip(("w", "h", "duration", "title", "artist", "album"), r[1:]) if v} for r in rows}
        for it in items:
            if known.get(it["id"]):
                it["meta"] = known[it["id"]]
        return items

    def trashed_folders(self):
        """The trash's folders: each trashed on its own (not carried along by a parent)."""
        rows = q("SELECT id,name,parent,coalesce(updated_at, created_at) FROM drive_folders "
                 "WHERE profile=%s AND trashed AND trashed_by IS NULL ORDER BY 4 DESC", (self.profile_id,))
        return [{"id": i, "name": n, "parent": _root(p) or None, "last": _utc16(t), "owner": self.owner_name,
                 "owner_id": self.profile_id, "mine": True, "trashed": True} for i, n, p, t in rows]

    def views(self):
        return ["recent", "starred", "added"]

    def media_files(self, kind, limit=3000):
        """Every live photo/video (`visual`), video or audio file of this profile, newest first by
        when it was taken, with what is known about it so far (`meta`; `probed` false = not yet)."""
        mime_re, name_re = _MEDIA.get(kind, _MEDIA["visual"])
        # a recording in a .webm / .mp4 container is sound: its audio type keeps it out of the pictures
        # and the videos, whatever its name says
        not_sound = "" if kind == "audio" else "AND coalesce(f.mime,'') !~* '^audio/' "
        rows = q("SELECT f.id, f.name, f.folder, f.size, f.mime, f.created_at, f.starred, f.opened, f.md5, "
                 "m.w, m.h, m.duration, m.title, m.artist, m.album, m.taken, (m.id IS NOT NULL) "
                 "FROM drive_files f LEFT JOIN drive_media m ON m.id = f.id "
                 "WHERE f.profile=%s AND NOT f.trashed AND (coalesce(f.mime,'') ~* %s OR f.name ~* %s) " + not_sound +
                 "ORDER BY coalesce(m.taken, f.created_at) DESC LIMIT %s",
                 (self.profile_id, mime_re, name_re, int(limit)))
        out = []
        for r in rows:
            item = self._row(*r[:9])
            w, h, dur, title, artist, album, taken, probed = r[9:]
            item["meta"] = {k: v for k, v in (("w", w), ("h", h), ("duration", dur), ("title", title),
                                              ("artist", artist), ("album", album)) if v}
            item["taken"] = _utc16(taken.replace(tzinfo=timezone.utc)) if taken else None
            item["probed"] = bool(probed)
            out.append(item)
        return out

    def changes_rev(self):
        """A number that moves whenever anything this profile sees changes — what the page polls."""
        r = q("SELECT extract(epoch FROM greatest("
              "(SELECT max(greatest(created_at, coalesce(updated_at, created_at))) FROM drive_files WHERE profile=%s),"
              "(SELECT max(greatest(created_at, coalesce(updated_at, created_at))) FROM drive_folders WHERE profile=%s),"
              "(SELECT max(m.probed_at) FROM drive_media m JOIN drive_files f ON f.id = m.id WHERE f.profile=%s)))",
              (self.profile_id, self.profile_id, self.profile_id))
        # …and the counts, because a row deleted for good leaves no newer time behind
        n = q("SELECT (SELECT count(*) FROM drive_files WHERE profile=%s), (SELECT count(*) FROM drive_folders WHERE profile=%s)",
              (self.profile_id, self.profile_id))[0]
        return f"{float(r[0][0] or 0):.3f}-{n[0]}-{n[1]}"

    def star(self, ids, on=True):
        """Flag or unflag files and folders; how many rows actually changed."""
        folders, files = self._split_ids(ids)
        changed = 0
        if files:
            changed += len(q("UPDATE drive_files SET starred=%s WHERE id = ANY(%s) AND profile=%s RETURNING id",
                             (bool(on), files, self.profile_id)))
        if folders:
            changed += len(q("UPDATE drive_folders SET starred=%s WHERE id = ANY(%s) AND profile=%s RETURNING id",
                             (bool(on), folders, self.profile_id)))
        return {"ok": True, "changed": changed, "starred": bool(on)}

    def touch(self, fid):
        """Stamp `opened` — serving a file's content is the one event that should move it up Recent."""
        try:
            q("UPDATE drive_files SET opened=now() WHERE id=%s AND profile=%s", (fid, self.profile_id))
        except Exception as e:
            print("[drive] touch skipped:", e, flush=True)

    def storage(self):
        """Bytes used by THIS profile; a ceiling only when DRIVE_STORAGE_LIMIT says one (a made-up
        ceiling would put a fictional number in a meter the operator is meant to trust)."""
        rows = q("SELECT count(*), coalesce(sum(size),0) FROM drive_files WHERE profile=%s AND NOT trashed",
                 (self.profile_id,))
        n, used = (rows[0] if rows else (0, 0))
        out = {"files": int(n or 0), "used": int(used or 0)}
        trash = q("SELECT count(*), coalesce(sum(size),0) FROM drive_files WHERE profile=%s AND trashed",
                  (self.profile_id,))
        out["trash_files"], out["trash_used"] = int(trash[0][0] or 0), int(trash[0][1] or 0)
        lim = os.environ.get("DRIVE_STORAGE_LIMIT", "").strip()
        if lim.isdigit():
            out["limit"] = int(lim)
            out["percent"] = round(100.0 * out["used"] / max(1, out["limit"]), 2)
        return out

    def search(self, term, limit=200):
        """Name search across the drive, newest first; LIKE wildcards in the term are literal."""
        like = "%" + str(term).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = q(SELECT_COLS + "WHERE profile=%s AND NOT trashed AND name ILIKE %s "
                 "ORDER BY created_at DESC LIMIT %s", (self.profile_id, like, int(limit)))
        return self._with_media([self._row(*r) for r in rows])

    def search_folders(self, term, limit=50):
        like = "%" + str(term).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = q("SELECT id,name,parent,created_at,system FROM drive_folders WHERE profile=%s AND NOT trashed "
                 "AND name ILIKE %s ORDER BY created_at DESC LIMIT %s", (self.profile_id, like, int(limit)))
        return [{"id": fid, "name": name, "parent": _root(parent) or None, "last": _utc16(created),
                 "system": system, "owner": self.owner_name, "owner_id": self.profile_id, "mine": True}
                for fid, name, parent, created, system in rows]

    # ── bytes in ──────────────────────────────────────────────────────────────────
    def store_file(self, src, size, md5, name, mime, folder="", oid=None):
        """Store one file from an open binary stream `src` holding exactly `size` bytes whose md5 is
        `md5`: bytes to storage first (streamed — memory stays flat for any size), then the index
        row. A failed insert takes its bytes back out, so storage never holds an object no row
        names. Returns the new item."""
        name, folder = clean_name(name), _root(folder)
        mime = media.mime_for(name, mime)
        oid = oid or new_id("lf")
        ensure_bucket()

        def put():
            return requests.post(f"{STORAGE}/object/{BUCKET}/{oid}", data=src,
                                 headers={**_auth(), "Content-Type": mime, "Content-Length": str(size),
                                          "x-upsert": "false"}, timeout=(10, 600))

        r = put()
        if r.status_code in (400, 404) and "bucket not found" in (r.text or "").lower() and hasattr(src, "seek"):
            # the bucket went away under a running app (a storage reset): make it, send again once
            global _BUCKET_READY
            _BUCKET_READY = False
            if ensure_bucket():
                src.seek(0)
                r = put()
        r.raise_for_status()
        try:
            q("INSERT INTO drive_files (id,profile,name,folder,link,md5,size,mime,trashed,updated_at) "
              "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,false,now())",
              (oid, self.profile_id, name, folder, public_link(oid), md5, int(size), mime))
        except Exception:
            requests.delete(f"{STORAGE}/object/{BUCKET}/{oid}", headers=_auth(), timeout=60)
            raise
        return self._file(oid) or {"id": oid, "name": name, "owner": self.owner_name}

    def upload(self, folder, filename, mime, data):
        """Bytes already in memory (small uploads, automation's createFromText). No dedupe: an
        upload is a new object (every dedupe tried here broke a caller — see git history)."""
        import io
        data = data or b""
        return self.store_file(io.BytesIO(data), len(data), hashlib.md5(data).hexdigest(), filename, mime, folder)

    # ── bytes out ─────────────────────────────────────────────────────────────────
    def content(self, fid, range_header=None, want="inline"):
        """(status, headers, byte-iterator) — only for a file this profile owns; streamed with Range."""
        rows = q("SELECT name, mime, md5 FROM drive_files WHERE id=%s AND profile=%s", (fid, self.profile_id))
        if not rows:
            raise AdapterError("הקובץ אינו קיים בדרייב של הפרופיל הזה", 404)
        name, mime, md5 = rows[0]
        rs = _object(fid, range_header)
        if rs.status_code >= 400 and rs.status_code != 416:
            rs.close()
            raise AdapterError(f"הקובץ אינו זמין באחסון (HTTP {rs.status_code})", 502 if rs.status_code >= 500 else 404)
        hdrs = media.serve_headers(name, mime, want, etag=md5)
        for h in ("Content-Length", "Content-Range"):
            if rs.headers.get(h):
                hdrs[h] = rs.headers[h]
        return rs.status_code, hdrs, rs.iter_content(65536)

    # ── canonical ops (§3) — the n8n surface; shapes unchanged ───────────────────
    def op_list(self, folder_id="", limit=100, what_to_search="files", include_trashed=False,
                created_after=None, query=None, name_contains=None, name_contains_any=None):
        """`query` is Google `q` grammar: accepted for call-compatibility with the google adapter and
        REFUSED when sent — approximating it in SQL would return a different set under the same
        argument. `nameContains` (str or list, AND) and `nameContainsAny` (OR) are the engine-
        agnostic name filters. `profile=%s` stays literal in the statement for tenancy-lint."""
        if query:
            raise AdapterError("this connection does not support free-form Drive queries", 501)
        where = ["trashed=%s"]
        args = [self.profile_id, bool(include_trashed)]
        if folder_id:
            where.append("folder = ANY(%s)")
            args.append([_root(folder_id)] if _root(folder_id) else list(ROOTS))
        if created_after:
            where.append("created_at >= %s")
            args.append(created_after)

        def _like(v):
            # parameterised AND with % _ \ escaped: a filter for 'plb_' must not match 'plbX'
            s = str(v)
            for ch in ('\\', '%', '_'):
                s = s.replace(ch, '\\' + ch)
            return '%' + s + '%'

        for _t in ([name_contains] if isinstance(name_contains, str) else (name_contains or [])):
            where.append("name ILIKE %s")
            args.append(_like(_t))
        _any = [name_contains_any] if isinstance(name_contains_any, str) else (name_contains_any or [])
        if _any:
            where.append("(" + " OR ".join(["name ILIKE %s"] * len(_any)) + ")")
            args.extend(_like(v) for v in _any)
        args.append(int(limit or 100))
        rows = q(DFILE_COLS + "WHERE profile=%s AND " + " AND ".join(where) +
                 " ORDER BY created_at DESC LIMIT %s", tuple(args))
        return [_dfile(*r) for r in rows]

    def op_download(self, file_id, file_id_mode="id"):
        fid = extract_file_id(file_id, file_id_mode)
        rows = q("SELECT name, mime FROM drive_files WHERE id=%s AND profile=%s", (fid, self.profile_id))
        if not rows:
            raise AdapterError("הקובץ אינו קיים בדרייב של הפרופיל הזה", 404)
        rs = _object(fid)
        if rs.status_code >= 400:
            rs.close()
            raise AdapterError(f"הקובץ אינו זמין באחסון (HTTP {rs.status_code})", rs.status_code)
        return rs.status_code, download_headers(rows[0][0], rows[0][1], rs.headers.get("Content-Length")), \
            rs.iter_content(65536)

    def op_upload(self, folder_id, name, mime, data):
        got = self.upload(folder_id or "", name, mime, data)
        rows = q(DFILE_COLS + "WHERE id=%s AND profile=%s", (got["id"], self.profile_id))
        return _dfile(*rows[0])

    def op_move(self, file_id, to_folder_id):
        rows = q("UPDATE drive_files SET folder=%s, updated_at=now() WHERE id=%s AND profile=%s "
                 "RETURNING id,name,folder,link,md5,size,mime,created_at",
                 (_root(to_folder_id), file_id, self.profile_id))
        return _dfile(*rows[0]) if rows else {}

    def op_update(self, file_id, new_name):
        rows = q("UPDATE drive_files SET name=%s, updated_at=now() WHERE id=%s AND profile=%s "
                 "RETURNING id,name,folder,link,md5,size,mime,created_at",
                 (clean_name(new_name), file_id, self.profile_id))
        return _dfile(*rows[0]) if rows else {}

    def op_delete(self, file_id):
        """Trash — the canonical `delete` means the same thing on both engines."""
        rows = q("UPDATE drive_files SET trashed=true, trashed_by=NULL, updated_at=now() "
                 "WHERE id=%s AND profile=%s RETURNING id", (file_id, self.profile_id))
        return {"id": file_id, "success": bool(rows)}

    def op_create_from_text(self, name, content, folder_id):
        got = self.upload(folder_id or "", name or "Untitled", "text/plain", str(content or "").encode("utf-8"))
        return {"id": got["id"]}
