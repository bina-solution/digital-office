"""gdrive — Google Drive (protocol `drive_google_oauth`), Drive v3 over the OAuth grant.

Credentials come from secret-base per call (§5a: they live in exactly one place). The instance's
secret is the token dict the connections broker vaulted at consent time:
`{access_token, refresh_token, expires_in, scope, token_type, id_token?}` — note `expires_in` is a
DURATION captured at consent, so it is meaningless minutes later. We therefore treat readiness as
"try, and refresh on 401", and stamp our own absolute `expires_at` whenever we mint a token.

Refreshed tokens are written BACK to secret-base (`update_secret`) so the whole estate shares one
live token. If that write is not accepted, the refresh still works — it just has to happen again
next time; see connections_client.update_secret for the current gap.
"""
import json
import os
import re
import time
from urllib.parse import quote

import requests

import connections_client as cx
import media

import dlcache
from opsupport import download_headers, extract_file_id

API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
TOKEN_URL = "https://oauth2.googleapis.com/token"
# `md5Checksum` added 2026-08-06 for consistency with `op_list`, which already returns it.
#
# CORRECTED 2026-08-06: an earlier version of this comment claimed FIELDS was the projection behind
# `op_list` and therefore the root cause of 183 GOOGLE_DRIVE_FILE rows having no HASH. THAT
# ATTRIBUTION WAS WRONG. `op_list` set its own projection (`fields=nextPageToken, files(*)`) and
# never read FIELDS -- its own docstring noted callers rely on `md5Checksum` coming through that
# `*`. FIELDS belonged to `_list()`, the UI plane.
#
# NO LONGER TRUE AS OF 2026-08-09: `op_list` now uses FIELDS too, measured lossless against 500
# live records and 14.1x smaller on the wire (see op_list's docstring). FIELDS is now the single
# projection for BOTH planes, so adding a key here serves the UI and the sync engine alike.
#
# THE REAL CAUSE, established 2026-08-06 and no longer "unexplained": those rows predate this file.
# They were written by the n8n `Search File` workflow's GoogleDrive node (`resource: fileFolder`,
# `searchMethod: query`, `options: {}` -- see the pre-refactor export
# .claude/worktrees/a-worktree/production/n8n/workflows/exampleWorkflow7.json). With
# `options.fields` unset, the node's own `prepareQueryString(undefined)` returns the literal string
# 'id, name' (v2/helpers/utils.js in the running n8n image), so it asked Drive for
# `files(id, name)` -- NO md5Checksum and NO size. `Build: ... LINK FOUND` then evaluated
# `HASH = {{ $json.md5Checksum }}` against an object that never had the key: n8n's Set node coerced
# `undefined` to '' and stored an empty string. The DB fingerprint confirms it -- all 183 rows have
# NAME and SOURCE_ID (from `name`/`id`) and BOTH `SIZE` and `HASH` empty, which is exactly the pair
# that projection omitted.
#
# So the PROJECTION half is already closed here: `op_list`'s `files(*)` does return md5Checksum
# (verified live against the running drive service). Two things remain, and neither is a Drive-
# adapter bug:
#   1. Google-NATIVE files (Docs/Sheets/Slides) have NO md5Checksum at any projection -- Drive does
#      not compute one. `files(*)` on a `vnd.google-apps.spreadsheet` returns `size` but
#      `md5Checksum: null` (verified live). Drive metadata therefore CANNOT guarantee a content
#      hash for every document; the guarantee has to come from the bytes, i.e. apitools' `file_hash`
#      (md5 of the uploaded content) via BaseDocEx01 -> indoxV2UploadApiTools01.
#   2. `/list` in app.py accepts no `query` parameter, but indoxV2SearchFile01 /
#      indoxV2SearchWarehouse01 both send one. It is silently dropped, so the name-contains search
#      that used to find the file now returns an arbitrary first file. See op_list's docstring.
#
# Also true and independent of the cause: `find_link` overwrites SOURCE_TYPE and SOURCE_ID in the
# same step that leaves HASH blank, and uq_incdoc_hash is a PARTIAL index excluding null/empty, so
# those rows carry no duplicate protection at all -- 110 of the 183 turn out to be genuine
# duplicates of rows already in the table (scripts/ops/indox-rehash-missing.py --worklist).
FIELDS = "id,name,parents,size,mimeType,createdTime,webViewLink,trashed,md5Checksum,owners(displayName,emailAddress)"
# What the SCREEN shows of a file beyond what the sync engine reads (FIELDS stays the sync's projection,
# measured above): the star, when it was last opened, Google's own picture of it, a picture's or a
# video's size. Only the UI plane asks for these — `op_list` and the sync payload do not grow.
UI_FIELDS = (FIELDS + ",starred,viewedByMeTime,modifiedTime,hasThumbnail,thumbnailLink,"
             "imageMediaMetadata(width,height,time),videoMediaMetadata(width,height,durationMillis)")
FOLDER_FIELDS = "id,name,parents,driveId,createdTime,modifiedTime,starred,owners(displayName,emailAddress)"
_TIMEOUT = 30
_ROOTS = {}      # cid -> the id of the account's My Drive root (never changes for an account)

FOLDER_MIME = "application/vnd.google-apps.folder"

# `download` on a Google-native file EXPORTS it. These are n8n's GoogleDrive v2 defaults, reproduced
# verbatim (download.operation.js) — the gdoc lanes depend on doc→docx, and the odd spreadsheet mime
# is n8n's, not a typo. Anything else (drawings included) falls back to jpeg, exactly as the node did.
EXPORT_MIME = {
    "document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "presentation": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "spreadsheet": "application/x-vnd.oasis.opendocument.spreadsheet",
}
EXPORT_FALLBACK = "image/jpeg"
# What a PERSON downloads a Google-native file as (the screen's «הורדה»): the Office file that opens
# anywhere. To look at one in place the screen gets the PDF export. A drawing, a form or a site has no
# Office twin and comes as a PDF. (EXPORT_MIME above stays the automation's, byte-for-byte n8n's.)
DOWNLOAD_AS = {
    "document": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}

# The ONE deliberate divergence from n8n's GoogleDrive node, forced and verified against the real
# account: the node sends spaces='appDataFolder, drive', which needs the drive.appdata scope. This
# grant holds full `auth/drive` but not drive.appdata, so Google rejects the pair outright —
# "The granted scopes do not give access to all of the requested spaces." (the node would fail here
# too; its creds were empty, so nobody ever found out). appDataFolder is a hidden per-app sandbox
# that no INDOX file has ever lived in, so dropping it changes nothing about the data we search —
# and the node itself already drops it on the 'root' path below.
SPACES = "drive"

# In-process token cache: {connection_id: token_dict}. A refreshed access token is worth ~1h; when
# secret-base cannot store it (see module docstring) this keeps the service from re-refreshing on
# every single op. Per-worker and non-authoritative on purpose — secret-base stays the source.
_CACHE = {}


class GoogleAuthError(Exception):
    """The connection cannot authenticate — the operator must reconnect. Carries a Hebrew reason
    because it surfaces straight into the account bar / probe result.

    It also carries the STATUS the caller should return, because "the connection is unusable" and
    "that one file is not there" are not the same fact and must not answer the same way.

    MEASURED 2026-08-06: every Google response >= 400 was raised as this error and the service
    answered a flat 503. A file that genuinely does not exist in Drive therefore came back as
    "Service unavailable - try again later or consider setting this node to retry automatically",
    so n8n classified a PERMANENT miss as a transient outage and re-tried one dead file id
    (`lf0000000000000000000001`) 24 times in five minutes — 24 of the window's `drive api` errors,
    all one document. 404/410 now pass through as themselves; auth, quota and transport faults keep
    the 503 that the account bar and /readyz are built on.
    """

    #: statuses that describe THE OBJECT, not the connection — these are reported verbatim.
    PASS_THROUGH = (404, 410)

    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


def _client():
    cid = os.environ.get("N8N_GOOGLE_OAUTH_CLIENT_ID", "")
    sec = os.environ.get("N8N_GOOGLE_OAUTH_CLIENT_SECRET", "")
    return cid, sec


def _esc(v):
    """Escape a value for a Drive `q` string literal (ids and search terms are user input)."""
    return str(v).replace("\\", "\\\\").replace("'", "\\'")


class GoogleDriveAdapter:
    protocol = "drive_google_oauth"
    #: A folder whose parent this account cannot see (shared with it by someone else) is, for a person,
    #: «shared with me» — its own view, as in Google Drive. A service account has nothing BUT such
    #: folders, so for it they are the top of its drive (google_sa.py).
    SHARED_AT_TOP = False

    def __init__(self, instance):
        self.instance = instance or {}
        self.cid = self.instance.get("id")
        self.owner_email = str(self.instance.get("account_hint") or "").strip().lower()

    # ── tokens ────────────────────────────────────────────────────────────────────
    def _token(self):
        tok = _CACHE.get(self.cid)
        if not tok:
            got = cx.get_secret(self.cid)
            if not got:
                raise GoogleAuthError("שירות החשבונות אינו זמין — לא ניתן לקרוא את ההרשאה")
            if got.get("refused"):
                raise GoogleAuthError(got["refused"])
            tok = got.get("secret") or {}
            if not tok.get("access_token") and not tok.get("refresh_token"):
                raise GoogleAuthError("החיבור אינו מכיל הרשאת Google — יש לחבר מחדש")
            _CACHE[self.cid] = tok
        exp = tok.get("expires_at")
        if exp and time.time() > float(exp) - 60:
            tok = self._refresh(tok)
        return tok

    def _refresh(self, tok):
        # The vault is the source, read again before a renewal: an account connected again (a new grant — a
        # read-only one, EXU-24) replaces the token this process still holds, so a renewal never revives the old
        # grant; a grant the vault now refuses to hand out is dropped here too, and so is one whose renewal it
        # refuses to keep. When the vault cannot answer, the token held is renewed, as before; when it answers with
        # no refresh token, the account is connected again — the held grant is not renewed behind its back.
        got = cx.get_secret(self.cid)
        if got and got.get("refused"):
            _CACHE.pop(self.cid, None)
            raise GoogleAuthError(got["refused"])
        if got:
            vault_tok = got.get("secret") or {}
            if not vault_tok.get("refresh_token"):
                _CACHE.pop(self.cid, None)
                raise GoogleAuthError("ההרשאה פגה ואין refresh token — יש לחבר את החשבון מחדש")
            tok = dict(vault_tok)
        rt = tok.get("refresh_token")
        if not rt:
            raise GoogleAuthError("ההרשאה פגה ואין refresh token — יש לחבר את החשבון מחדש")
        client_id, client_secret = _client()
        if not client_id or not client_secret:
            raise GoogleAuthError("חסר מזהה OAuth של Google בהגדרות השירות")
        try:
            r = requests.post(TOKEN_URL, data={"client_id": client_id, "client_secret": client_secret,
                                               "refresh_token": rt, "grant_type": "refresh_token"},
                              timeout=_TIMEOUT)
        except requests.RequestException as e:
            raise GoogleAuthError(f"חידוש ההרשאה נכשל: {e}")
        if r.status_code >= 400:
            raise GoogleAuthError(f"חידוש ההרשאה נדחה על ידי Google ({r.status_code}) — יש לחבר מחדש")
        new = r.json()
        # Google does not return the refresh_token on a refresh — carry it (and everything else the
        # grant held) forward, or the connection would authenticate exactly once more and then die.
        merged = dict(tok)
        merged.update(new)
        merged["refresh_token"] = new.get("refresh_token") or rt
        if new.get("expires_in"):
            merged["expires_at"] = int(time.time()) + int(new["expires_in"]) - 30
        kept = cx.update_secret(self.cid, merged)      # best-effort; see connections_client.update_secret
        if isinstance(kept, dict) and kept.get("refused"):
            _CACHE.pop(self.cid, None)                 # a grant the vault will not keep is not used (EXU-24)
            raise GoogleAuthError(kept["refused"])
        _CACHE[self.cid] = merged
        return merged

    def _req(self, method, url, **kw):
        """One authenticated Drive call, with a single refresh-and-retry on 401 — the access token
        may have died between the cache read and this call, and that must not surface as an error."""
        base = dict(kw.pop("headers", None) or {})
        tok = self._token()
        for attempt in (1, 2):
            headers = dict(base, Authorization="Bearer " + (tok.get("access_token") or ""))
            try:
                r = requests.request(method, url, headers=headers, timeout=_TIMEOUT, **kw)
            except requests.RequestException as e:
                raise GoogleAuthError(f"Google Drive אינו זמין: {e}")
            if r.status_code != 401 or attempt == 2:
                return r
            tok = self._refresh(tok)
        return r

    def _json(self, method, url, **kw):
        r = self._req(method, url, **kw)
        if r.status_code >= 400:
            raise GoogleAuthError(_reason(r), _status_for(r))
        return r.json() if r.content else {}

    # ── readiness ─────────────────────────────────────────────────────────────────
    def probe(self):
        """A real, cheap call — one file, one field. Anything else (a listed-but-broken account) is
        exactly the failure the account bar exists to show."""
        try:
            r = self._req("GET", f"{API}/files", params={"pageSize": 1, "fields": "files(id)"})
        except GoogleAuthError as e:
            return str(e)
        return None if r.status_code < 400 else _reason(r)

    # ── the shape of the account: its root, its shared drives, its folder tree ────
    def _root_id(self):
        """The id of this account's My Drive root. Google answers `parents: [<root id>]` for what sits at
        the top, and the screen calls the top "" — every folder and file this adapter hands out says ""
        there, so «הקבצים שלי» is the same place on every drive."""
        rid = _ROOTS.get(self.cid)
        if rid is None:
            rid = self._json("GET", f"{API}/files/root", params={"fields": "id"}).get("id") or ""
            _ROOTS[self.cid] = rid
        return rid

    def _top(self, pid):
        return "" if not pid or pid == self._root_id() else pid

    # A folder list is one Drive walk of every folder, and one request may ask for it more than once (a path
    # resolved, then its folder's path). It is kept on THIS adapter — one request's — and never across
    # requests: the drive runs more than one worker, and a cache in one process outlives a change made in the
    # other (a folder made, moved or trashed would be missing from the next screen for as long as it lived).
    def _drives(self):
        """The shared drives this account belongs to — each is a top-level place of its own, every page of them
        (G36: one page of an account in more drives than that would hide the rest). A Drive that refuses the
        call (a service account, an old grant) simply has none."""
        if getattr(self, "_drives_seen", None) is None:
            seen, page = [], None
            try:
                while True:
                    d = self._json("GET", f"{API}/drives", params={
                        "pageSize": 100, "fields": "nextPageToken,drives(id,name)", **({"pageToken": page} if page else {})})
                    seen += d.get("drives") or []
                    page = d.get("nextPageToken")
                    if not page:
                        break
            except GoogleAuthError:
                seen = []
            self._drives_seen = seen
        return self._drives_seen

    def _raw_folders(self):
        # UNBOUNDED on purpose, like `_list()`/`shared_folders()` below: this used to stop at
        # len(out) >= 600, which was fine only by accident (the client had 443 folders the day
        # that was written). A cap glued on top of an otherwise-correct nextPageToken loop is the
        # same defect as a missing loop — past the cap, real folders silently stop appearing, with
        # no error. Follow every page; there is no tree size where "stop reporting the rest" is
        # the right behaviour for a sync source. 1000 a page (Drive's own ceiling): a big account is
        # a few calls, not dozens.
        if getattr(self, "_tree_seen", None) is not None:
            return self._tree_seen
        out, page = [], None
        while True:
            d = self._json("GET", f"{API}/files", params={
                "q": "mimeType='application/vnd.google-apps.folder' and trashed=false",
                "fields": f"nextPageToken,incompleteSearch,files({FOLDER_FIELDS})", "pageSize": 1000,
                "supportsAllDrives": "true", "includeItemsFromAllDrives": "true", "corpora": "allDrives",
                **({"pageToken": page} if page else {})})
            if d.get("incompleteSearch"):
                print(f"[drive] {self.cid}: Google answered the folder walk incompletely (incompleteSearch)", flush=True)
            out += d.get("files", [])
            page = d.get("nextPageToken")
            if not page:
                break
        self._tree_seen = out
        return out

    def _changed(self):
        """Something this service did moved the tree: the next read walks it again."""
        self._tree_seen = None

    def folders(self):
        """Every folder, as the screen and the sync's folder picker read it: `parent` is None at the top.
        The top is My Drive's root, each shared drive (a folder of its own, marked `drive`), and — for a
        person — nothing else: a folder somebody shared whose parent this account cannot see is marked
        `shared` and kept out of the tree (it is «shared with me»); a service account has only those, so
        for it they ARE the top."""
        root = self._root_id()
        drives = self._drives()
        raw = self._raw_folders()
        known = {f["id"] for f in raw} | {d["id"] for d in drives}
        out = [{"id": d["id"], "name": d.get("name") or d["id"], "kind": "folder", "parent": None, "count": None,
                "last": None, "drive": True, "owner": "", "owner_id": "", "mine": False} for d in drives]
        for f in raw:
            row = _folder(f, self.owner_email, root)
            above = (f.get("parents") or [None])[0]
            # no parent this account can see (Google sends none, or one it cannot name): somebody shared it
            if above != root and (not above or above not in known):
                row["parent"] = None
                if not self.SHARED_AT_TOP:
                    row["shared"] = True
            out.append(row)
        return out

    def _tree(self):
        """{id: folder} of what `folders()` answers."""
        return {f["id"]: f for f in self.folders()}

    def subfolders(self, fid):
        """The folders directly inside `fid` ("" = the top, without what was shared with this account:
        that is the «shared» view's) — what a path read lists."""
        return [f for f in self.folders() if (f.get("parent") or "") == (fid or "") and not (not fid and f.get("shared"))]

    def create_folder(self, name, parent=""):
        meta = {"name": name, "mimeType": FOLDER_MIME}
        if parent:
            meta["parents"] = [parent]
        created = self._json("POST", f"{API}/files", params={
            "fields": "id,name,parents", "supportsAllDrives": "true"}, json=meta)
        self._changed()
        return {"id": created["id"], "name": created.get("name") or name,
                "parent": self._top((created.get("parents") or [None])[0]) or None}

    def path_of(self, folder):
        """'/a/b' for a folder id, '/' for the top. A folder outside the tree (shared with this account)
        starts at its own name: it has no path above it that this account can name."""
        tree, names, cur, seen = self._tree(), [], self._top(folder), set()
        while cur and cur not in seen:
            seen.add(cur)
            f = tree.get(cur)
            if not f:
                try:
                    meta = self._json("GET", f"{API}/files/{quote(cur)}",
                                      params={"fields": "name,parents", "supportsAllDrives": "true"})
                except GoogleAuthError:
                    names.append(cur)
                    break
                names.append(meta.get("name") or cur)
                cur = self._top((meta.get("parents") or [""])[0])
                continue
            names.append(f["name"])
            cur = f.get("parent") or ""
        return "/" + "/".join(reversed(names))

    def _child(self, parent, name, folders_only=False):
        """The newest live item called `name` directly in `parent` ("" = My Drive's root)."""
        p = parent or "root"
        qs = f"'{_esc(p)}' in parents and name = '{_esc(name)}' and trashed=false"
        if folders_only:
            qs += f" and mimeType = '{FOLDER_MIME}'"
        hits = self._list(qs, 10)
        hits.sort(key=lambda it: (it.get("kind") != "folder", ""))      # a folder wins over a file of its name
        return hits[0] if hits else None

    def resolve_path(self, path):
        """'/a/b.pdf' → ('file', item) · '/a' → ('folder', {id, name, path}) · '/' → ('folder', the top) ·
        None when nothing is there — the same answer the local drive gives, so every path verb (the
        agents', `api/fs`, the CLI) works on a Google account as it does on the office's own drive.
        A segment is a shared drive's name too, at the top (`/<shared drive>/…`)."""
        segs = [s for s in str(path or "").split("/") if s]
        parent = ""
        for i, seg in enumerate(segs):
            hit = self._child(parent, seg) if (parent or i) else None
            if not parent and not i:
                # the top: My Drive's own first, then a shared drive, then a folder shared with this account
                hit = (self._child("", seg)
                       or next(({"id": f["id"], "kind": "folder"} for f in self.folders()
                                if not f.get("parent") and f.get("name") == seg), None))
            if not hit:
                return None
            if hit.get("kind") == "folder":
                parent = hit["id"]
                continue
            if i != len(segs) - 1:
                return None
            return ("file", hit)
        return ("folder", {"id": parent, "name": segs[-1] if segs else "", "path": "/" + "/".join(segs)})

    def ensure_path(self, path, system=None):
        """Get-or-create every folder of `path`; the last one's id ('' for the top). `system` (an app's
        own folder) is the local drive's idea — Google has no such mark, so it is not kept here."""
        parent = ""
        for seg in [s.strip() for s in str(path or "").split("/") if s.strip()]:
            hit = self._child(parent, seg, folders_only=True)
            parent = hit["id"] if hit else self.create_folder(seg, parent)["id"]
        return parent

    def free_name(self, folder, name):
        """`name` if no live file in `folder` has it, else 'name (2).ext', 'name (3).ext'…"""
        p = folder or "root"
        taken = {it["name"] for it in self._list(f"'{_esc(p)}' in parents and trashed=false", 1000)}
        if name not in taken:
            return name
        stem, dot, ext = name.rpartition(".")
        stem, ext = (stem, "." + ext) if dot and stem else (name, "")
        n = 2
        while f"{stem} ({n}){ext}" in taken:
            n += 1
        return f"{stem} ({n}){ext}"

    # ── items ─────────────────────────────────────────────────────────────────────
    def _scope(self, folder):
        """The corpus a FOLDER's listing reads — what the sync enumerates, so never all drives at once (there
        Google may answer `incompleteSearch` and leave files out): a shared drive's folder is read from that
        drive, any other exactly as it always was (no corpus named)."""
        if not folder:
            return {}
        try:
            drive = self._json("GET", f"{API}/files/{quote(folder)}",
                               params={"fields": "driveId", "supportsAllDrives": "true"}).get("driveId")
        except GoogleAuthError:
            drive = None
        return {"corpora": "drive", "driveId": drive} if drive else {}

    def _list(self, qs, limit=None, order="createdTime desc", scope=None):
        """List items matching `qs`, FOLLOWING nextPageToken. `scope` is the corpus (`_scope`); the browse
        views (recent, starred, search…) read every drive the account has.

        `limit` caps how many items come back (None = every match). Drive returns at most ~460-1000
        per page regardless of pageSize, so a single request silently truncates any folder bigger
        than that — which for a real accounting archive (folders of 5k+ documents) means the sync
        would only ever see the first page and report the rest as absent. `folders()` above already
        paginates; this is the same loop, and the two now agree.
        """
        out, page = [], None
        root = self._root_id()
        while True:
            want = 1000 if limit is None else min(limit - len(out), 1000)
            d = self._json("GET", f"{API}/files", params={
                "q": qs, "fields": f"nextPageToken,files({UI_FIELDS})", "pageSize": max(want, 1),
                "orderBy": order, "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true", **({"corpora": "allDrives"} if scope is None else scope),
                **({"pageToken": page} if page else {})})
            out += [_folder(f, self.owner_email, root) if f.get("mimeType") == FOLDER_MIME
                    else _item(f, self.owner_email, root) for f in d.get("files", [])]
            page = d.get("nextPageToken")
            if not page or (limit is not None and len(out) >= limit):
                return out[:limit] if limit is not None else out

    def files(self, folder="", trashed=False, view="", created_after=None, limit=None, offset=0):
        """`created_after` (RFC3339) is the sync-discovery date bound — folded into the Drive `q`
        itself (never a post-filter), same as `op_list`'s. Only applied to the plain folder
        listing (what `/sync/inventory`'s at-source count reads); the `shared`/trashed views are
        browse surfaces, not a sync source, so they stay unbounded. `folder` "" is My Drive's root
        (it answered nothing, and «הקבצים שלי» of a Google account was an empty page).
        `limit`/`offset` are the local engine's paging (app.py passes them to an engine that also
        lists its trashed folders): a Drive folder is listed whole, by its own pages, so they are
        taken and not used — refusing them was a 500 on every Google folder."""
        nofolder = f"mimeType != '{FOLDER_MIME}'"
        if view == "shared":
            return self._list(f"sharedWithMe=true and trashed=false and {nofolder}", 200)
        if view == "recent":
            # what this person opened, newest first — Google keeps the time itself (viewedByMeTime)
            return self._list(f"viewedByMeTime > '2000-01-01T00:00:00' and trashed=false and {nofolder}", 100,
                              order="viewedByMeTime desc")
        if view == "starred":
            return self._list(f"starred=true and trashed=false and {nofolder}", 500)
        if view == "added":
            return self._list(f"trashed=false and {nofolder}", 30)
        if trashed:
            # A browse view, not a sync source — bounded so a huge trash can't stall the UI.
            return self._list(f"trashed=true and {nofolder}", 1000)
        # UNBOUNDED on purpose: this is what the sync engine enumerates. A cap here silently means
        # "the rest of the folder does not exist" (see _list).
        qs = f"'{_esc(folder or 'root')}' in parents and trashed=false and {nofolder}"
        if created_after:
            qs += f" and createdTime > '{_esc(created_after)}'"
        return self._list(qs, scope=self._scope(folder))

    def _file(self, fid):
        """One file's item (the screen's details, a path read), or None when it is not there."""
        r = self._req("GET", f"{API}/files/{quote(fid)}", params={"fields": UI_FIELDS, "supportsAllDrives": "true"})
        if r.status_code in (404, 410):
            return None
        if r.status_code >= 400:
            raise GoogleAuthError(_reason(r), _status_for(r))
        f = r.json()
        root = self._root_id()
        return _folder(f, self.owner_email, root) if f.get("mimeType") == FOLDER_MIME else _item(f, self.owner_email, root)

    def search(self, term):
        return self._list(
            f"name contains '{_esc(term)}' and trashed=false and mimeType != '{FOLDER_MIME}'", 200)

    def search_folders(self, term):
        t = str(term or "").lower()
        return [f for f in self.folders() if t and t in str(f.get("name") or "").lower()][:50]

    def trashed_folders(self, limit=500):
        """The trash's folders: a browse view, so bounded by the caller's `limit` — and paged up to it."""
        root, out, page = self._root_id(), [], None
        while True:
            d = self._json("GET", f"{API}/files", params={
                "q": f"trashed=true and mimeType = '{FOLDER_MIME}'", "fields": f"nextPageToken,files({FOLDER_FIELDS})",
                "pageSize": max(min(limit - len(out), 1000), 1), "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true", "corpora": "allDrives", **({"pageToken": page} if page else {})})
            out += [{**_folder(f, self.owner_email, root), "trashed": True} for f in d.get("files", [])]
            page = d.get("nextPageToken")
            if not page or len(out) >= limit:
                return out[:limit]

    def media_files(self, kind, limit=1000):
        """Every live photo/video (`visual`), video or audio file, newest first — with what Google
        already knows of each (size in pixels, duration, when a photo was taken). Nothing is probed
        here: the bytes are Google's, and so are the facts."""
        want = {"video": "mimeType contains 'video/'", "audio": "mimeType contains 'audio/'"}.get(
            kind, "(mimeType contains 'image/' or mimeType contains 'video/')")
        return self._list(f"{want} and trashed=false", limit)

    def storage(self):
        """What Google reports: bytes in use and the ceiling (an unlimited account has none)."""
        q = self._json("GET", f"{API}/about", params={"fields": "storageQuota"}).get("storageQuota") or {}
        used, lim = int(q.get("usage") or 0), int(q.get("limit") or 0)
        out = {"used": used, "trash_used": int(q.get("usageInDriveTrash") or 0)}
        if lim:
            out["limit"] = lim
            out["percent"] = round(100.0 * used / max(1, lim), 2)
        return out

    def star(self, ids, on=True):
        for fid in ids:
            self._json("PATCH", f"{API}/files/{quote(fid)}", params={"supportsAllDrives": "true", "fields": "id"},
                       json={"starred": bool(on)})
        self._changed()
        return {"ok": True, "changed": len(ids), "starred": bool(on)}

    def changes_rev(self):
        """Google's own marker of «something changed in this drive» — what an open window polls to
        refresh by itself when a file arrives from elsewhere (a phone, a colleague, a workflow)."""
        try:
            return self._json("GET", f"{API}/changes/startPageToken",
                              params={"supportsAllDrives": "true"}).get("startPageToken")
        except GoogleAuthError:
            return None

    def thumb(self, item, size):
        """(bytes, mime) of Google's own picture of a file at about `size` pixels, or None. The link
        lives a few hours, so it is asked fresh each time; the browser keeps the picture a week."""
        meta = self._json("GET", f"{API}/files/{quote(item['id'])}",
                          params={"fields": "thumbnailLink,hasThumbnail", "supportsAllDrives": "true"})
        link = meta.get("thumbnailLink")
        if not link:
            return None
        link = re.sub(r"=s\d+$", "", link) + f"=s{max(64, min(int(size or 256), 2048))}"
        r = self._req("GET", link, stream=False)
        if r.status_code >= 400 or not r.content:
            return None
        return r.content, (r.headers.get("Content-Type") or "image/jpeg").split(";")[0]

    def shared_folders(self):
        # Paginated for the same reason _list() is: a single page silently reports every folder past
        # it as ABSENT. A service account's whole world is what has been shared with it, so
        # truncating here means the sync cannot see sources that genuinely exist.
        out, page = [], None
        root = self._root_id()
        while True:
            d = self._json("GET", f"{API}/files", params={
                "q": f"sharedWithMe=true and trashed=false and mimeType = '{FOLDER_MIME}'",
                "fields": f"nextPageToken,files({FOLDER_FIELDS})",
                "pageSize": 1000,
                "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
                **({"pageToken": page} if page else {})})
            out += [_folder(f, self.owner_email, root) for f in d.get("files", [])]
            page = d.get("nextPageToken")
            if not page:
                return out

    def views(self):
        return ["recent", "starred", "shared", "added"]

    def upload(self, folder, filename, mime, data):
        mime = mime or "application/octet-stream"
        meta = {"name": filename, "parents": [folder]} if folder else {"name": filename}
        r = self._req("POST", UPLOAD, params={"uploadType": "multipart", "fields": "id,name",
                                              "supportsAllDrives": "true"},
                      files={"metadata": ("metadata", json.dumps(meta), "application/json"),
                             "file": (filename, data, mime)})
        if r.status_code >= 400:
            raise GoogleAuthError(_reason(r), _status_for(r))
        d = r.json()
        return self._file(d.get("id")) or {"id": d.get("id"), "name": d.get("name") or filename}

    def store_file(self, src, size, md5, name, mime, folder="", oid=None):
        """One file of any size from an open stream: Drive's resumable upload — the session first, then
        the bytes in one streamed PUT (memory stays flat; a 2 GB recording is fine). `md5` is checked
        against what Google computed: a file that arrived different is not kept."""
        meta = {"name": name}
        if folder:
            meta["parents"] = [folder]
        mime = mime or "application/octet-stream"
        r = self._req("POST", UPLOAD, params={"uploadType": "resumable", "supportsAllDrives": "true"},
                      json=meta, headers={"X-Upload-Content-Type": mime, "X-Upload-Content-Length": str(size)})
        if r.status_code >= 400 or not r.headers.get("Location"):
            raise GoogleAuthError(_reason(r), _status_for(r))
        put = self._req("PUT", r.headers["Location"], data=src,
                        headers={"Content-Type": mime, "Content-Length": str(size)})
        if put.status_code >= 400:
            raise GoogleAuthError(_reason(put), _status_for(put))
        got = put.json() if put.content else {}
        fid = got.get("id")
        item = self._file(fid) if fid else None
        if md5 and item and item.get("md5") and item["md5"] != md5:
            self.trash([fid])
            raise GoogleAuthError("הקובץ הגיע ל־Google Drive שונה ממה שנשלח — הוא הועבר לאשפה ולא נשמר", 502)
        self._changed()
        return item or {"id": fid, "name": got.get("name") or name}

    def rename(self, fid, name):
        self._json("PATCH", f"{API}/files/{quote(fid)}", params={"supportsAllDrives": "true"},
                   json={"name": name})
        self._changed()

    def move(self, ids, to):
        n = 0
        for fid in ids:
            cur = self._json("GET", f"{API}/files/{quote(fid)}",
                             params={"fields": "parents", "supportsAllDrives": "true"})
            self._json("PATCH", f"{API}/files/{quote(fid)}", params={
                "addParents": to or self._root_id(), "removeParents": ",".join(cur.get("parents") or []),
                "fields": "id", "supportsAllDrives": "true"})
            n += 1
        self._changed()
        return n

    def trash(self, ids, restore=False):
        for fid in ids:
            self._json("PATCH", f"{API}/files/{quote(fid)}", params={"supportsAllDrives": "true"},
                       json={"trashed": not restore})
        self._changed()
        return len(ids)

    def delete(self, ids):
        n = 0
        for fid in ids:
            # trash-only, like the local adapter: a permanent delete must never be reachable from a
            # normal folder view by accident.
            cur = self._json("GET", f"{API}/files/{quote(fid)}",
                             params={"fields": "trashed", "supportsAllDrives": "true"})
            if not cur.get("trashed"):
                continue
            r = self._req("DELETE", f"{API}/files/{quote(fid)}", params={"supportsAllDrives": "true"})
            if r.status_code >= 400:
                raise GoogleAuthError(_reason(r), _status_for(r))
            n += 1
        self._changed()
        return n

    def content(self, fid, range_header=None, want="inline"):
        """(status, headers, byte-iterator), streamed with Range. The headers are the office's own
        (media.serve_headers): what renders without running anything opens in place, the rest
        downloads, and every answer is sandboxed — a user's .html in Google Drive never runs on this
        app's origin. A Google Doc, Sheet or Slides file has no bytes of its own: it is EXPORTED — as
        a PDF to look at, as the matching Office file to download."""
        meta = self._json("GET", f"{API}/files/{quote(fid)}",
                          params={"fields": "name,mimeType,md5Checksum", "supportsAllDrives": "true"})
        name, mt = meta.get("name") or fid, meta.get("mimeType") or ""
        if mt.startswith("application/vnd.google-apps."):
            kind = mt.rsplit(".", 1)[-1]
            if want == "inline" or kind not in DOWNLOAD_AS:
                out_mime, ext = "application/pdf", ".pdf"
            else:
                out_mime, ext = DOWNLOAD_AS[kind]
            r = self._req("GET", f"{API}/files/{quote(fid)}/export",
                          params={"mimeType": out_mime, "supportsAllDrives": "true"}, stream=True)
            if r.status_code >= 400:
                raise GoogleAuthError(_reason(r), _status_for(r))
            hdrs = media.serve_headers(name + ext, out_mime, want)
            if r.headers.get("Content-Length"):
                hdrs["Content-Length"] = r.headers["Content-Length"]
            return 200, hdrs, r.iter_content(65536)
        r = self._req("GET", f"{API}/files/{quote(fid)}",
                      params={"alt": "media", "supportsAllDrives": "true"},
                      headers=({"Range": range_header} if range_header else {}), stream=True)
        if r.status_code >= 400 and r.status_code != 416:
            raise GoogleAuthError(_reason(r), _status_for(r))
        hdrs = media.serve_headers(name, mt or r.headers.get("Content-Type"), want, etag=meta.get("md5Checksum"))
        hdrs["Accept-Ranges"] = "bytes"
        for h in ("Content-Length", "Content-Range"):
            if r.headers.get(h):
                hdrs[h] = r.headers[h]
        return r.status_code, hdrs, r.iter_content(65536)

    # ── canonical ops (§3) ────────────────────────────────────────────────────────
    # These are NOT the domain-native methods above: they reproduce, call for call, what n8n's
    # GoogleDrive node did for driveApi01's seven ops, because ~39 workflows read those exact
    # payloads. The rule for this layer is "same bytes on the wire as the node sent" — every
    # divergence below is deliberate and noted. Shapes are Drive's own resources, passed through
    # untouched (§3: this refactor moves ownership, not schemas).

    def op_list(self, folder_id="", limit=100, what_to_search="files", include_trashed=False,
               created_after=None, query=None, name_contains=None, name_contains_any=None):
        """fileFolder:search, projected through the module-level FIELDS set.

        PROJECTION (2026-08-09). This asked Drive for `files(*)` — the FULL resource, 46 keys —
        because callers read md5Checksum/createdTime/size/webViewLink and an earlier revision of
        this docstring asserted that narrowing "would silently null those out". MEASURED against
        the live `drive-gdoc-scanned-synced` folder (500 files, one call): `*` returns 9 642 B per
        record, of which `permissions` alone is 5 878 B (61 %) and `capabilities` a further 1 048 B
        — neither is read anywhere in this repo. FIELDS returns 681 B per record, a 14.1x
        reduction, and all ten of its keys were present on every one of the 500 records, so the
        narrowing is provably lossless for every field any caller actually consumes.

        This matters because op_list is the SYNC path: a destination folder of thousands of files was
        moving tens of MB of JSON per listing into an n8n execution, which is what OOM-killed three
        reconcile passes ("possible out-of-memory issue" at `List` / `Call DIFF`). The payload, not
        the page count, was the constraint.

        IF YOU NEED A FIELD BACK, add it to FIELDS (line 63) — do not restore `*`. FIELDS is the
        same projection `_list()` uses, so both planes now answer with one shape.

        `created_after` (RFC3339) is the sync-discovery date bound — a file created before it is
        excluded from the Drive query itself (Drive's own `createdTime > '...'` comparison), never
        returned then filtered downstream. `None` (the default) is unbounded, unchanged from
        before this parameter existed.

        GAP CLOSED 2026-08-13 — `query` is now accepted and AND-ed into `q`. The evidence that
        forced it: across every row there were ZERO `LINK FOUND` stamps against thousands of
        `SEARCH_IN_DRIVE_COMPLETED` attempts spanning two weeks, i.e. the find-link feature had
        never once succeeded. A read-only ground-truth probe run as the SAME service account the
        pipeline uses found the intended predicate works — nearly all of a control of known-good
        file ids, and about half of a random sample of documents the pipeline had already given up
        on. So thousands of documents were being reported "file not found" while their file sat in
        Drive. The owner independently reproduced this by hand: searching Drive for one such
        document's number returns two matching PDFs, while INDOX shows that document as file-not-found.

        The write-path concern in the original note still stands and is deliberately NOT resolved
        here: the LINK FOUND builder overwrites NAME/SOURCE_TYPE on the row, which discards
        BALANCE_SHEET provenance. That is a data-model decision for the owner, so this change is
        confined to the SEARCH being correct. Nothing here writes to incoming_documents.

        ORIGINAL NOTE (2026-08-06), kept because it is the record of how long this ran broken. The
        `q` clause
        is built ENTIRELY from these parameters; there is no caller-supplied `query`, and `/list`
        in app.py does not read one. But the node this op replaced DID take a free-form query
        (`searchMethod: query`), and two live callers still send one:
          * indoxV2SearchFile01 -> `name contains '<COMPANY>' and name contains '<SHORT_DOC_ID>'`
          * indoxV2SearchWarehouse01 -> the same, scoped to a folder
        Their `params.query` is silently dropped, so what used to be "find THIS document" is now
        "return the first non-folder file in the whole drive". Verified live: an impossible query
        (`name contains 'ZZZ_NO_SUCH_COMPANY'`) returned two unrelated files. Downstream this is
        currently harmless-by-accident — indoxV2SearchFile01's own `If Found File1` re-checks
        `name contains SHORT_DOC_ID` and rejects the mismatch, so find-link simply never succeeds
        (0 new GOOGLE_DRIVE_FILE rows since 2026-08-05) — but if that guard ever passed by
        coincidence the row would be linked to the WRONG file, which is worse than not linking.
        Restoring it means accepting a caller `query` and AND-ing it into `q`; that revives a write
        path that overwrites SOURCE_TYPE/SOURCE_ID/LINK on live rows, so it is deliberately left to
        an explicit decision rather than bundled with the HASH work.

        SyncSource000001 also passes a `query`, but its value is
        `mimeType != '<folder>' and trashed = false` — exactly what this method already builds — so
        the folder-scan sync is unaffected by the drop."""
        q = []
        if folder_id and folder_id != "root":
            q.append(f"'{_esc(folder_id)}' in parents")
        if what_to_search == "folders":
            q.append(f"mimeType = '{FOLDER_MIME}'")
        elif what_to_search == "files":
            q.append(f"mimeType != '{FOLDER_MIME}'")
        if not include_trashed:
            q.append("trashed = false")
        if created_after:
            q.append(f"createdTime > '{_esc(created_after)}'")
        # See local.py: a list means AND, `nameContainsAny` is the OR. Each is folded in as a
        # CLAUSE so it ANDs with the folder/type/trashed bounds instead of replacing them.
        for _t in ([name_contains] if isinstance(name_contains, str) else (name_contains or [])):
            q.append(f"name contains '{_esc(_t)}'")
        _any = ([name_contains_any] if isinstance(name_contains_any, str)
                else (name_contains_any or []))
        if _any:
            q.append("(" + " or ".join(f"name contains '{_esc(v)}'" for v in _any) + ")")
        if query:
            # AND-ed, never substituted: the caller narrows within the scope this layer already
            # established, it cannot widen past the folder/mime/trashed/date bounds. Parenthesised
            # so a caller clause containing `or` cannot rebind against our terms. NOT _esc()'d --
            # this is Drive `q` SYNTAX, not a literal, and escaping it would break every operator
            # in it; the value reaches here only from a trusted internal caller.
            q.append(f"({query})")
        qs = {"fields": f"nextPageToken, files({FIELDS})", "q": " and ".join(q),
              "includeItemsFromAllDrives": "true", "supportsAllDrives": "true",
              "spaces": SPACES, "corpora": "allDrives"}
        if folder_id == "root":
            # the node's own special case: 'root' is the RLC sentinel, not an id — it is NOT sent as
            # `in parents`, and the search narrows to the user's own drive.
            qs.update({"corpora": "user", "spaces": SPACES,
                       "includeItemsFromAllDrives": "false", "supportsAllDrives": "false"})
        # FOLLOW nextPageToken, the same loop `_list()` above runs and for the same reason: this op
        # asked Drive for the token and then threw it away, so a N-file folder answered 100 —
        # measured live 2026-08-09, at limit=100 AND limit=1000 alike (Drive caps a `corpora=allDrives`
        # page well below the requested pageSize, so a big `pageSize` is not a workaround). `limit`
        # stays a REAL bound and stays 100 by default — this is the op a sync pass calls, and an
        # unbounded walk of a 17k folder inside a claiming pass is its own outage — but it is now the
        # caller's bound rather than "however much fit on page one". pageSize is clamped to Drive's
        # own [1,1000] range independently of `limit`, or limit=100000 400s ("Invalid value").
        out, page = [], None
        cap = int(limit or 100)
        while True:
            d = self._json("GET", f"{API}/files", params={
                **qs, "pageSize": max(min(cap - len(out), 1000), 1),
                **({"pageToken": page} if page else {})})
            out += d.get("files", [])
            page = d.get("nextPageToken")
            if not page or len(out) >= cap:
                return out[:cap]

    def op_download(self, file_id, file_id_mode="id"):
        """(status, headers, byte-iterator). Google-native files are EXPORTED (see EXPORT_MIME);
        the filename stays the Drive name with no extension fix-up — n8n did not add one either.

        CACHED on `md5Checksum` (adapters/dlcache.py). The pipeline calls this endpoint ~12x per
        distinct document — eleven workflows each re-read the same source, and the `/docExists`
        short-circuit upstream cannot help because it is keyed on a digest of bytes nobody has
        yet. Measured 2026-08-10: 1 214 downloads served 100 files. `md5Checksum` and `size` are
        two extra fields on the metadata call this method ALREADY made to choose export-vs-media,
        so a hit costs one Drive metadata round trip instead of the whole transfer, and the key
        being the content digest is what makes a hit provably the same bytes. Google-native files
        have no md5Checksum and are exported rather than stored, so they are never cached.
        """
        fid = extract_file_id(file_id, file_id_mode)
        meta = self._json("GET", f"{API}/files/{quote(fid)}",
                          params={"fields": "mimeType,name,md5Checksum,size",
                                  "supportsTeamDrives": "true",
                                  "supportsAllDrives": "true"})
        mt = meta.get("mimeType") or ""
        native = "vnd.google-apps" in mt
        key = None if native else meta.get("md5Checksum")

        if dlcache.usable(key):
            hit = dlcache.get(key)
            if hit:
                size, ctype = hit
                hdrs = download_headers(meta.get("name") or fid, ctype, str(size))
                return 200, hdrs, dlcache.stream(key)

        if native:
            parts = mt.split(".")
            mime = EXPORT_MIME.get(parts[2] if len(parts) > 2 else "", EXPORT_FALLBACK)
            r = self._req("GET", f"{API}/files/{quote(fid)}/export",
                          params={"mimeType": mime, "supportsAllDrives": "true"}, stream=True)
        else:
            r = self._req("GET", f"{API}/files/{quote(fid)}",
                          params={"alt": "media", "supportsAllDrives": "true"}, stream=True)
        if r.status_code >= 400:
            raise GoogleAuthError(_reason(r), _status_for(r))
        hdrs = download_headers(meta.get("name") or fid,
                                r.headers.get("Content-Type"), r.headers.get("Content-Length"))
        body = r.iter_content(65536)
        if dlcache.usable(key):
            try:
                expect = int(meta.get("size") or 0) or None
            except (TypeError, ValueError):
                expect = None
            body = dlcache.tee(key, body, r.headers.get("Content-Type"), expect)
        return r.status_code, hdrs, body

    def op_upload(self, folder_id, name, mime, data):
        """The node uploaded, then PATCHed with fields='*'; one multipart with the same metadata and
        fields='*' lands the same file and returns the same resource — md5Checksum included, which
        syncV3Deliver hard-requires (it throws on a missing md5)."""
        meta = {"name": name}
        if folder_id:
            meta["parents"] = [folder_id]
        r = self._req("POST", UPLOAD,
                      params={"uploadType": "multipart", "fields": "*", "supportsAllDrives": "true"},
                      files={"metadata": ("metadata", json.dumps(meta), "application/json"),
                             "file": (name, data, mime or "application/octet-stream")})
        if r.status_code >= 400:
            raise GoogleAuthError(_reason(r), _status_for(r))
        return r.json()

    def op_move(self, file_id, to_folder_id):
        """PATCH addParents/removeParents with NO `fields` — Drive's default projection, which is
        what the node returned: {kind, id, name, mimeType}."""
        fid = extract_file_id(file_id, "id")
        qs = {"includeItemsFromAllDrives": "true", "supportsAllDrives": "true",
              "spaces": SPACES, "corpora": "allDrives"}
        cur = self._json("GET", f"{API}/files/{quote(fid)}", params={**qs, "fields": "parents"})
        return self._json("PATCH", f"{API}/files/{quote(fid)}",
                          params={**qs, "addParents": to_folder_id,
                                  "removeParents": ",".join(cur.get("parents") or [])})

    def op_update(self, file_id, new_name):
        fid = extract_file_id(file_id, "id")
        body = {"name": new_name} if new_name else {}
        return self._json("PATCH", f"{API}/files/{quote(fid)}",
                          params={"supportsAllDrives": "true"}, json=body)

    def op_delete(self, file_id):
        """TRASH, not erase. driveApi01's d:delete left options.deletePermanently unset, so the node
        PATCHed trashed:true and returned {id, success:true}. Reproducing the shape but not this
        semantic would turn a reversible op into a destructive one on the client's real Drive."""
        fid = extract_file_id(file_id, "id")
        self._json("PATCH", f"{API}/files/{quote(fid)}",
                   params={"supportsAllDrives": "true"}, json={"trashed": True})
        return {"id": fid, "success": True}

    def op_create_from_text(self, name, content, folder_id):
        """Plain text only: d:createFromText never set convertToGoogleDocument, so the node took the
        multipart branch and returned {id} — nothing more."""
        meta = {"name": name or "Untitled", "mimeType": "text/plain"}
        if folder_id:
            meta["parents"] = [folder_id]
        r = self._req("POST", UPLOAD,
                      params={"uploadType": "multipart", "fields": "id", "supportsAllDrives": "true"},
                      files={"metadata": ("metadata", json.dumps(meta), "application/json"),
                             "file": (name or "Untitled", str(content or "").encode("utf-8"),
                                      "text/plain")})
        if r.status_code >= 400:
            raise GoogleAuthError(_reason(r), _status_for(r))
        return {"id": r.json().get("id")}


def _ownership(f, active_email):
    owner = (f.get("owners") or [{}])[0]
    owner_name = owner.get("displayName") or owner.get("emailAddress") or ""
    owner_email = str(owner.get("emailAddress") or "").lower()
    return {"owner": owner_name, "owner_id": owner_email,
            "mine": bool(active_email and owner_email == active_email)}


def _utc16(stamp):
    """Google's RFC 3339 time as the screen's `YYYY-MM-DD HH:MM` (UTC), '' when there is none."""
    return (stamp or "")[:16].replace("T", " ")


def _taken(exif):
    """A photo's own `2019:05:11 13:24:00` (EXIF, as Google reports it) → `2019-05-11 13:24`."""
    m = re.match(r"^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2})", str(exif or ""))
    return f"{m[1]}-{m[2]}-{m[3]} {m[4]}:{m[5]}" if m else None


def _folder(f, active_email, root=None):
    parent = (f.get("parents") or [None])[0]
    return {"id": f["id"], "name": f.get("name") or f["id"], "kind": "folder",
            "parent": None if not parent or parent == root else parent, "count": None,
            "last": _utc16(f.get("modifiedTime") or f.get("createdTime")) or None,
            "starred": bool(f.get("starred")), **_ownership(f, active_email)}


def _item(f, active_email, root=None):
    parent = (f.get("parents") or [""])[0]
    img, vid = f.get("imageMediaMetadata") or {}, f.get("videoMediaMetadata") or {}
    dur = vid.get("durationMillis")
    meta = {k: v for k, v in (("w", img.get("width") or vid.get("width")),
                              ("h", img.get("height") or vid.get("height")),
                              ("duration", round(int(dur) / 1000.0, 3) if dur else None)) if v}
    out = {"id": f.get("id"), "name": f.get("name") or f.get("id"),
           "folder": "" if parent == root else parent, "size": int(f.get("size") or 0),
           "mime": f.get("mimeType") or "", "created": _utc16(f.get("createdTime")),
           "link": f.get("webViewLink"), "starred": bool(f.get("starred")),
           "opened": _utc16(f.get("viewedByMeTime")), "md5": f.get("md5Checksum") or "",
           # the facts are Google's: nothing here is waiting to be measured by this service
           "probed": True, **_ownership(f, active_email)}
    if meta:
        out["meta"] = meta
    if f.get("hasThumbnail") or f.get("thumbnailLink"):
        out["thumb"] = True
    taken = _taken(img.get("time"))
    if taken:
        out["taken"] = taken
    return out


def _status_for(r):
    """The status the SERVICE should answer with for a failed Google response.

    Only object-level misses pass through (see GoogleAuthError.PASS_THROUGH). Everything else —
    401/403 (reconnect), 429 (quota), 5xx (Google is down) — stays 503, because those describe the
    connection and are exactly what the account bar and /readyz report on.
    """
    return r.status_code if r.status_code in GoogleAuthError.PASS_THROUGH else 503


def _reason(r):
    """Google's own message, never a stack trace (§4b: errors say what to fix)."""
    try:
        e = (r.json() or {}).get("error") or {}
        msg = e.get("message") or (e if isinstance(e, str) else "")
    except ValueError:
        msg = (r.text or "")[:160]
    return f"Google Drive: {msg or 'HTTP ' + str(r.status_code)}"
