"""engine_rpc — the engine side of `drive-engine.v1`, the one protocol between «קבצים» (the generic
`drive` app) and every drive engine (apps/drive/ENGINES.md, DGO-1500).

THE SAME FILE in every drive engine (apps/drive-local, apps/drive-google): apps/drive/test_engines.py
holds the copies byte for byte equal, so the protocol cannot drift between engines. An engine hands
`blueprint()` an object that knows how to build the adapter of one of its accounts; this file serves
the protocol over it. Nothing here knows a database, a storage or Google.

Every JSON answer is {"ok": true, ...} or {"ok": false, "error", "status", "kind"}. A byte answer
(content, download, a picture) that is an ERROR carries `X-Drive-Engine-Error: <kind>`, so a file
whose bytes happen to be JSON is never taken for an error, nor an error for a file.
"""
import json
import logging

import requests
from flask import Blueprint, Response, request
from werkzeug.exceptions import HTTPException

log = logging.getLogger(__name__)

INTERFACE = "drive-engine.v1"
ERROR_HEADER = "X-Drive-Engine-Error"
PROFILE_KEY_HEADER = "X-Drive-Profile-Key"

#: The drive interface /v1/call may reach — the methods the in-process adapters had, with the same
#: arguments and results. A method an adapter lacks is left out of /v1/describe, so the screen never
#: offers it. `file` is the adapters' `_file` (one file's metadata).
METHODS = ("probe", "folders", "subfolders", "create_folder", "rename", "move", "trash", "delete",
           "resolve_path", "ensure_path", "path_of", "free_name", "file", "files", "trashed_folders",
           "shared_folders", "views", "media_files", "changes_rev", "star", "touch", "storage", "search",
           "search_folders", "peaks", "op_list", "op_move", "op_update", "op_delete", "op_create_from_text")
#: what moves bytes, each on its own route; listed in /v1/describe when the adapter has it
STREAMS = ("content", "op_download", "store_file", "upload", "op_upload", "thumb")
ALIAS = {"file": "_file"}


class EngineError(Exception):
    def __init__(self, message, status=503, kind="adapter"):
        super().__init__(message)
        self.message, self.status, self.kind = message, int(status or 503), kind


class SizedStream:
    """A request body of a known size, readable once: `len()` lets `requests` send it with its own
    Content-Length (streamed, never read whole), `read()` passes through."""

    def __init__(self, stream, size):
        self.stream, self.size = stream, int(size)

    def __len__(self):
        return self.size

    def read(self, n=-1):
        return self.stream.read(n)


def _json(body, status=200, headers=None):
    return Response(json.dumps(body, ensure_ascii=False, default=str), status=status,
                    mimetype="application/json", headers=headers or {})


def _fail(e, stream=False):
    body = {"ok": False, "error": e.message, "status": e.status, "kind": e.kind}
    return _json(body, e.status, {ERROR_HEADER: e.kind} if stream else None)


def _from_http(e):
    """What a store or a provider said, in a person's words — never its English or an internal address — and
    with a status that is about the CALLER's request only when it is: a storage that refuses the engine's own
    key, or lost its bucket, is the engine's trouble (502/503), not «your file is not there» (404)."""
    resp = getattr(e, "response", None)
    status = getattr(resp, "status_code", None)
    text = (getattr(resp, "text", "") or "").lower() if resp is not None else ""
    if status == 413:
        return EngineError("הקובץ גדול מהמותר באחסון — הקובץ לא נשמר", 413)
    if status in (409, 416):
        return EngineError(f"האחסון לא קיבל את הבקשה (שגיאה {status})", status)
    if status and "bucket" in text:
        return EngineError("האחסון אינו מוכן כרגע — נסו שוב בעוד רגע", 503)
    if status == 404:
        return EngineError("הפריט אינו קיים באחסון", 404)
    if status:
        return EngineError(f"האחסון לא קיבל את הבקשה (שגיאה {status})", 502)
    if isinstance(e, (requests.ConnectionError, requests.Timeout)):
        return EngineError("שירות האחסון אינו עונה כרגע — נסו שוב בעוד רגע", 503)
    return EngineError("האחסון דחה את הבקשה", 502)


def blueprint(engine):
    """`engine` gives: `ops()` (the /ops body), `adapter(cid)`, `as_error(exc)` → EngineError|None,
    `accounts(instances)`, `connect(body)`, `disconnect(cid)` → (body, status), and `check_key(cid, key)`
    (raises when a presented profile key may not act on that drive)."""
    bp = Blueprint("drive_engine", __name__)

    def guard(fn, stream=False, drain=False):
        """Every answer is the protocol's: an error the engine does not know is still JSON with its header
        (never Flask's HTML page, which a byte route would hand on as if it were the file). A refused PUT
        reads its body first, so the caller hears the refusal instead of a broken pipe."""
        try:
            return fn()
        except Exception as e:                       # noqa: BLE001 — every error becomes an answer of the protocol
            if isinstance(e, EngineError):
                mapped = e
            elif isinstance(e, HTTPException):        # the server's own (a body too large, a client gone)
                mapped = EngineError(e.description or e.name, e.code or 400, "request")
            else:
                mapped = engine.as_error(e)
                if mapped is None and isinstance(e, requests.RequestException):
                    mapped = _from_http(e)
                if mapped is None:
                    log.exception("drive engine: unexpected error")
                    mapped = EngineError("שגיאה פנימית במנוע הקבצים — הפעולה לא בוצעה", 500, "internal")
            if drain:
                try:
                    while request.stream.read(1 << 20):
                        pass
                except Exception:                    # noqa: BLE001 — the caller may have gone
                    pass
            return _fail(mapped, stream)

    def _args():
        b = request.get_json(silent=True)
        return b if isinstance(b, dict) else {}

    def _adapter(cid):
        if not cid:
            raise EngineError("connection_id required", 400)
        key = (request.headers.get(PROFILE_KEY_HEADER) or "").strip()
        if key:
            engine.check_key(cid, key)
        return engine.adapter(cid)

    @bp.get("/ops")
    def ops():
        return _json({"ok": True, "interface": INTERFACE, **engine.ops()})

    @bp.post("/v1/accounts")
    def accounts():
        b = _args()
        return guard(lambda: _json({"ok": True, "accounts": engine.accounts(list(b.get("instances") or []))}))

    @bp.post("/v1/describe")
    def describe():
        def run():
            ad = _adapter(_args().get("connection_id"))
            has = lambda m: callable(getattr(ad, ALIAS.get(m, m), None))  # noqa: E731
            views = list(ad.views()) if has("views") else []
            return _json({"ok": True, "protocol": getattr(ad, "protocol", ""),
                          "private": bool(engine.ops().get("protocols", {}).get(getattr(ad, "protocol", ""), {}).get("private")),
                          "profile_id": getattr(ad, "profile_id", None),
                          "methods": [m for m in METHODS if has(m)], "streams": [m for m in STREAMS if has(m)],
                          "views": views, "creates": not getattr(ad, "_SA_NO_CREATE", None)})
        return guard(run)

    @bp.post("/v1/call/<method>")
    def call(method):
        def run():
            if method not in METHODS:
                raise EngineError(f"{method!r} is not a drive-engine.v1 method", 404)
            b = _args()
            ad = _adapter(b.get("connection_id"))
            fn = getattr(ad, ALIAS.get(method, method), None)
            if not callable(fn):
                raise EngineError("החיבור הזה אינו תומך בפעולה הזו", 501)
            return _json({"ok": True, "result": fn(*(b.get("args") or []), **(b.get("kwargs") or {}))})
        return guard(run)

    def _bytes(status, hdrs, chunks):
        return Response(chunks, status=status, headers=hdrs, direct_passthrough=True)

    @bp.get("/v1/content")
    def content():
        def run():
            ad = _adapter(request.args.get("connection_id"))
            fid, rng, want = request.args.get("id") or "", request.headers.get("Range"), request.args.get("want") or "inline"
            return _bytes(*ad.content(fid, rng, want))
        return guard(run, stream=True)

    @bp.get("/v1/download")
    def download():
        def run():
            ad = _adapter(request.args.get("connection_id"))
            return _bytes(*ad.op_download(request.args.get("file_id"), request.args.get("file_id_mode") or "id"))
        return guard(run, stream=True)

    @bp.post("/v1/thumb")
    def thumb():
        def run():
            b = _args()
            ad = _adapter(b.get("connection_id"))
            fn = getattr(ad, "thumb", None)
            got = fn(b.get("item") or {}, b.get("size") or 256) if callable(fn) else None
            if not got or not got[0]:
                raise EngineError("אין תמונה לקובץ הזה", 404)
            data, mime = got
            return Response(data, mimetype=mime or "image/webp")
        return guard(run, stream=True)

    def _put(op):
        a = request.args
        ad = _adapter(a.get("connection_id"))
        size = int(a.get("size") or request.content_length or 0)
        src = SizedStream(request.stream, size)
        name, mime, folder, md5 = a.get("name") or "file", a.get("mime") or None, a.get("folder") or "", a.get("md5") or ""
        if op == "store":
            store = getattr(ad, "store_file", None)
            if callable(store):
                return store(src, size, md5, name, mime, folder)
            if size > 64 * 1024 * 1024:
                raise EngineError("החיבור הזה מקבל קבצים עד 64 MB", 413)
            return ad.upload(folder, name, mime, src.read())
        # the §3 `upload` op: streamed where the engine stores streams, else bytes (bounded)
        streamed = getattr(ad, "op_store", None)
        if callable(streamed):
            return streamed(src, size, md5, name, mime, folder)
        if size > 64 * 1024 * 1024:
            raise EngineError("החיבור הזה מקבל קבצים עד 64 MB", 413)
        return ad.op_upload(folder, name, mime, src.read())

    @bp.put("/v1/store")
    def store():
        return guard(lambda: _json({"ok": True, "result": _put("store")}), drain=True)

    @bp.put("/v1/op_upload")
    def op_upload():
        return guard(lambda: _json({"ok": True, "result": _put("op_upload")}), drain=True)

    @bp.post("/v1/connect")
    def connect():
        def run():
            body, status = engine.connect(_args())
            return _json(body, status)
        return guard(run)

    @bp.post("/v1/disconnect")
    def disconnect():
        def run():
            body, status = engine.disconnect(_args().get("connection_id") or "")
            return _json(body, status)
        return guard(run)

    return bp
