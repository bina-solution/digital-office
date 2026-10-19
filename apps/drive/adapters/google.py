"""adapters.google — Google Drive (protocol `drive_google_oauth`), Drive v3 over the OAuth grant.

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
import time
from urllib.parse import quote

import requests

import connections_client as cx

from . import dlcache
from .opsupport import download_headers, extract_file_id

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
# .claude/worktrees/fervent-mestorf-20f464/production/n8n/workflows/cnvttABSBdZTe9Xv.json). With
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
_TIMEOUT = 30

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
    (`lf19fd81450ffe7b0eb24db`) 24 times in five minutes — 24 of the window's `drive api` errors,
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
            tok = got.get("secret") or {}
            if not tok.get("access_token") and not tok.get("refresh_token"):
                raise GoogleAuthError("החיבור אינו מכיל הרשאת Google — יש לחבר מחדש")
            _CACHE[self.cid] = tok
        exp = tok.get("expires_at")
        if exp and time.time() > float(exp) - 60:
            tok = self._refresh(tok)
        return tok

    def _refresh(self, tok):
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
        _CACHE[self.cid] = merged
        cx.update_secret(self.cid, merged)      # best-effort; see connections_client.update_secret
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

    # ── containers ────────────────────────────────────────────────────────────────
    def folders(self):
        # UNBOUNDED on purpose, like `_list()`/`shared_folders()` below: this used to stop at
        # len(out) >= 600, which was fine only by accident (the client had 443 folders the day
        # that was written). A cap glued on top of an otherwise-correct nextPageToken loop is the
        # same defect as a missing loop — past the cap, real folders silently stop appearing, with
        # no error. Follow every page; there is no tree size where "stop reporting the rest" is
        # the right behaviour for a sync source.
        out, page = [], None
        while True:
            d = self._json("GET", f"{API}/files", params={
                "q": "mimeType='application/vnd.google-apps.folder' and trashed=false",
                "fields": "nextPageToken,files(id,name,parents,owners(displayName,emailAddress))", "pageSize": 200,
                "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
                **({"pageToken": page} if page else {})})
            for f in d.get("files", []):
                out.append(_folder(f, self.owner_email))
            page = d.get("nextPageToken")
            if not page:
                return out

    def create_folder(self, name, parent=""):
        meta = {"name": name, "mimeType": FOLDER_MIME}
        if parent:
            meta["parents"] = [parent]
        created = self._json("POST", f"{API}/files", params={
            "fields": "id,name,parents", "supportsAllDrives": "true"}, json=meta)
        return {"id": created["id"], "name": created.get("name") or name,
                "parent": (created.get("parents") or [None])[0]}

    # ── items ─────────────────────────────────────────────────────────────────────
    def _list(self, qs, limit=None):
        """List items matching `qs`, FOLLOWING nextPageToken.

        `limit` caps how many items come back (None = every match). Drive returns at most ~460-1000
        per page regardless of pageSize, so a single request silently truncates any folder bigger
        than that — which for a real accounting archive (folders of 5k+ documents) means the sync
        would only ever see the first page and report the rest as absent. `folders()` above already
        paginates; this is the same loop, and the two now agree.
        """
        out, page = [], None
        while True:
            want = 1000 if limit is None else min(limit - len(out), 1000)
            d = self._json("GET", f"{API}/files", params={
                "q": qs, "fields": f"nextPageToken,files({FIELDS})", "pageSize": max(want, 1),
                "orderBy": "createdTime desc", "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
                **({"pageToken": page} if page else {})})
            out += [_item(f, self.owner_email) for f in d.get("files", [])]
            page = d.get("nextPageToken")
            if not page or (limit is not None and len(out) >= limit):
                return out[:limit] if limit is not None else out

    def files(self, folder="", trashed=False, view="", created_after=None):
        """`created_after` (RFC3339) is the sync-discovery date bound — folded into the Drive `q`
        itself (never a post-filter), same as `op_list`'s. Only applied to the plain folder
        listing (what `/sync/inventory`'s at-source count reads); the `shared`/trashed views are
        browse surfaces, not a sync source, so they stay unbounded."""
        if view == "shared":
            return self._list(
                f"sharedWithMe=true and trashed=false and mimeType != '{FOLDER_MIME}'", 200)
        if trashed:
            # A browse view, not a sync source — bounded so a huge trash can't stall the UI.
            return self._list(f"trashed=true and mimeType != '{FOLDER_MIME}'", 1000)
        if not folder:
            return []
        # UNBOUNDED on purpose: this is what the sync engine enumerates. A cap here silently means
        # "the rest of the folder does not exist" (see _list).
        qs = f"'{_esc(folder)}' in parents and trashed=false and mimeType != '{FOLDER_MIME}'"
        if created_after:
            qs += f" and createdTime > '{_esc(created_after)}'"
        return self._list(qs)

    def search(self, term):
        return self._list(
            f"name contains '{_esc(term)}' and trashed=false and mimeType != '{FOLDER_MIME}'", 200)

    def shared_folders(self):
        # Paginated for the same reason _list() is: a single page silently reports every folder past
        # it as ABSENT. A service account's whole world is what has been shared with it, so
        # truncating here means the sync cannot see sources that genuinely exist.
        out, page = [], None
        while True:
            d = self._json("GET", f"{API}/files", params={
                "q": f"sharedWithMe=true and trashed=false and mimeType = '{FOLDER_MIME}'",
                "fields": "nextPageToken,files(id,name,parents,owners(displayName,emailAddress))",
                "pageSize": 200,
                "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
                **({"pageToken": page} if page else {})})
            out += [_folder(f, self.owner_email) for f in d.get("files", [])]
            page = d.get("nextPageToken")
            if not page:
                return out

    def views(self):
        return ["shared"]

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
        return {"id": d.get("id"), "name": d.get("name") or filename}

    def rename(self, fid, name):
        self._json("PATCH", f"{API}/files/{quote(fid)}", params={"supportsAllDrives": "true"},
                   json={"name": name})

    def move(self, ids, to):
        n = 0
        for fid in ids:
            cur = self._json("GET", f"{API}/files/{quote(fid)}",
                             params={"fields": "parents", "supportsAllDrives": "true"})
            self._json("PATCH", f"{API}/files/{quote(fid)}", params={
                "addParents": to, "removeParents": ",".join(cur.get("parents") or []),
                "fields": "id", "supportsAllDrives": "true"})
            n += 1
        return n

    def trash(self, ids, restore=False):
        for fid in ids:
            self._json("PATCH", f"{API}/files/{quote(fid)}", params={"supportsAllDrives": "true"},
                       json={"trashed": not restore})
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
        return n

    def content(self, fid, range_header=None):
        r = self._req("GET", f"{API}/files/{quote(fid)}",
                      params={"alt": "media", "supportsAllDrives": "true"},
                      headers=({"Range": range_header} if range_header else {}), stream=True)
        if r.status_code >= 400:
            raise GoogleAuthError(_reason(r), _status_for(r))
        hdrs = {"Content-Type": r.headers.get("Content-Type", "application/octet-stream"),
                "Accept-Ranges": "bytes", "Content-Disposition": "inline"}
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

        This matters because op_list is the SYNC path: a 4 634-file destination folder was moving
        ~45 MB of JSON per listing into an n8n execution, which is what OOM-killed reconcile passes
        442363 / 445301 / 446737 ("possible out-of-memory issue" at `List` / `Call DIFF`). The
        payload, not the page count, was the constraint.

        IF YOU NEED A FIELD BACK, add it to FIELDS (line 63) — do not restore `*`. FIELDS is the
        same projection `_list()` uses, so both planes now answer with one shape.

        `created_after` (RFC3339) is the sync-discovery date bound — a file created before it is
        excluded from the Drive query itself (Drive's own `createdTime > '...'` comparison), never
        returned then filtered downstream. `None` (the default) is unbounded, unchanged from
        before this parameter existed.

        GAP CLOSED 2026-08-13 — `query` is now accepted and AND-ed into `q`. The evidence that
        forced it: across all 32,536 rows there were ZERO `LINK FOUND` stamps against 6,861
        `SEARCH_IN_DRIVE_COMPLETED` attempts spanning 14 days, i.e. the find-link feature had
        never once succeeded. A read-only ground-truth probe run as the SAME service account the
        pipeline uses found the intended predicate works perfectly — 11/12 on a control of
        known-good file ids, and 106/200 (53.0%) on a random sample of documents the pipeline had
        already given up on. So ~3,430 documents were being reported "file not found" while their
        file sat in Drive. The owner independently reproduced this by hand: searching Drive for
        `קל קל-05626` returns two matching PDFs, while INDOX shows that document as file-not-found.

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
        # asked Drive for the token and then threw it away, so a 17,325-file folder answered 100 —
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


def _folder(f, active_email):
    return {"id": f["id"], "name": f.get("name") or f["id"],
            "parent": (f.get("parents") or [None])[0], "count": None, "last": None,
            **_ownership(f, active_email)}


def _item(f, active_email):
    return {"id": f.get("id"), "name": f.get("name") or f.get("id"),
            "folder": (f.get("parents") or [""])[0], "size": int(f.get("size") or 0),
            "mime": f.get("mimeType") or "", "created": (f.get("createdTime") or "")[:16].replace("T", " "),
            "link": f.get("webViewLink"), **_ownership(f, active_email)}


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
