"""The drive's pure parts: what a file is, how its bytes may be served, resumable sessions, names.

    python3 apps/drive/test_core.py

Run as a script (like adapters/test_op_list_pages.py): no database, no storage, no network — a
missing driver is replaced by an empty stand-in, because nothing here calls it.
"""
import importlib
import io
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _have(name, **attrs):
    try:
        importlib.import_module(name)
    except Exception:                               # noqa: BLE001
        mod = types.ModuleType(name)
        mod.__dict__.update(attrs)
        sys.modules[name] = mod


_have("requests", RequestException=Exception, ConnectionError=Exception, Timeout=Exception)
_have("psycopg2", OperationalError=Exception, InterfaceError=Exception, connect=None)
_have("psycopg2.pool", ThreadedConnectionPool=None)
sys.modules["psycopg2"].pool = sys.modules["psycopg2.pool"]

import media      # noqa: E402
import uploads    # noqa: E402

FAILS = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


# ── what a file is ────────────────────────────────────────────────────────────────
check("m4a is audio/mp4 (python's table does not know it)", media.mime_for("הקלטה.m4a") == "audio/mp4")
check("octet-stream from the client is no answer", media.mime_for("a.pdf", "application/octet-stream") == "application/pdf")
check("a real type from the client wins", media.mime_for("a.bin", "image/png") == "image/png")
check("an unknown extension is octet-stream", media.mime_for("a.zzz9") == "application/octet-stream")
check("no extension", media.ext_of("Makefile") == "" and media.ext_of(".env") == "" and media.ext_of("a.TAR.GZ") == "gz")

# ── how its bytes may be served ───────────────────────────────────────────────────
h = media.serve_headers("x.html", "text/html")
check("html is shown as text, never rendered", h["Content-Type"].startswith("text/plain") and h["Content-Disposition"].startswith("inline"))
h = media.serve_headers("x.svg", "image/svg+xml")
check("svg downloads (it can carry script)", h["Content-Disposition"].startswith("attachment"))
h = media.serve_headers("x.pdf", "application/pdf")
check("pdf inline, and its CSP lets Chrome's viewer start", h["Content-Disposition"].startswith("inline") and "sandbox" not in h["Content-Security-Policy"])
h = media.serve_headers("x.mp4", "video/mp4", etag="abc")
check("video inline, sandboxed, nosniff, etag", h["Content-Disposition"].startswith("inline") and "sandbox" in h["Content-Security-Policy"]
      and h["X-Content-Type-Options"] == "nosniff" and h["ETag"] == '"abc"')
h = media.serve_headers("דוח.pdf", "application/pdf", "attachment")
check("a Hebrew name survives in filename*", "filename*=UTF-8''%D7%93" in h["Content-Disposition"] and h["Content-Disposition"].startswith("attachment"))

# ── resumable sessions ────────────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as tmp:
    uploads.ROOT = tmp
    s = uploads.create("admin", 10, {"name": "a.txt", "folder": "ld1"})
    check("a new session starts at 0", s["offset"] == 0 and s["state"] == "receiving")
    s = uploads.append(s["id"], "admin", 0, io.BytesIO(b"hello"), 5)
    check("a piece moves the offset", s["offset"] == 5)
    try:
        uploads.append(s["id"], "admin", 3, io.BytesIO(b"xx"), 2)
        check("a wrong offset is refused", False)
    except uploads.UploadError as e:
        check("a wrong offset is refused with the real one", e.status == 409 and e.offset == 5)
    try:
        uploads.append(s["id"], "admin", 5, io.BytesIO(b"123456"), 6)
        check("a piece past the declared size is refused", False)
    except uploads.UploadError as e:
        check("a piece past the declared size is refused", e.status == 413)
    try:
        uploads.status(s["id"], "user2")
        check("another profile cannot see the session", False)
    except uploads.UploadError as e:
        check("another profile cannot see the session", e.status == 404)
    s = uploads.append(s["id"], "admin", 5, io.BytesIO(b"world"), 5)
    check("the last piece completes it", s["offset"] == 10 and s["state"] == "complete")
    got = {}

    def store(src, size, md5, meta):
        got.update(data=src.read(), size=size, md5=md5, folder=meta["folder"])
        return {"id": "lfX", "name": meta["name"]}

    def finished(uid):
        """`done`, and the finishing thread's last act over: it records done, THEN unlinks the part (and a
        prepared copy) — the order that survives a crash. This block's directory is removed when it ends,
        and an rmtree that listed a part the thread then unlinked failed on it (FileNotFoundError, under
        the gates' load, DGO-1038)."""
        part = uploads._paths(uid)[1]
        return (uploads.status(uid, "admin")["state"] == "done"
                and not os.path.exists(part) and not os.path.exists(part + ".fixed"))

    uploads.finish_async(s["id"], "admin", store)
    import time
    for _ in range(200):
        if finished(s["id"]):
            break
        time.sleep(0.05)
    st = uploads.status(s["id"], "admin")
    check("finishing hands the whole file and its md5 to the store",
          st["state"] == "done" and got.get("data") == b"helloworld" and got.get("md5") == "fc5e038d38a57032085441e7fe7010b0"
          and st["file"]["id"] == "lfX")
    check("…and its part is gone once it is done (the wait above did not time out)", finished(s["id"]))
    check("the session is listed as open until done", uploads.open_sessions("admin") == [])
    try:
        uploads.create("admin", uploads.MAX_SIZE + 1, {"name": "big"})
        check("a file over the ceiling is refused up front", False)
    except uploads.UploadError as e:
        check("a file over the ceiling is refused up front", e.status == 413)
    check("tus metadata parses base64 UTF-8", uploads.parse_metadata("name 16nXnNeV150=,folder ") == {"name": "שלום", "folder": ""})

    # an app's own folder marker and a recording's remux survive the session (they were dropped once:
    # the session kept five known fields, and the live office stored a browser recording untouched)
    s = uploads.create("admin", 4, {"name": "t.webm", "path": "/הקלטות", "system": "הקלטות", "remux": "webm"})
    st = uploads.status(s["id"], "admin")
    check("a session keeps the app's folder marker and the remux request", st.get("system") == "הקלטות" and st.get("remux") == "webm")
    seen = {}

    def prep(part, meta):
        seen.update(remux=meta.get("remux"))
        fixed = part + ".fixed"
        with open(fixed, "wb") as f:
            f.write(b"FIXED-BYTES")
        return fixed

    uploads.PREPARE.append(prep)
    try:
        uploads.append(s["id"], "admin", 0, io.BytesIO(b"raw!"), 4)
        got2 = {}
        uploads.finish_async(s["id"], "admin", lambda src, size, md5, meta: got2.update(data=src.read(), size=size) or {"id": "lfY"})
        for _ in range(200):
            if finished(s["id"]):
                break
            time.sleep(0.05)
        check("a prepare step sees the session and its copy is what gets stored (with its own size)",
              seen.get("remux") == "webm" and got2.get("data") == b"FIXED-BYTES" and got2.get("size") == 11)
        check("…done, its part and its prepared copy gone (the wait above did not time out)", finished(s["id"]))
    finally:
        uploads.PREPARE.remove(prep)

# ── names and paths ───────────────────────────────────────────────────────────────
# local.py ALONE, as a module of a package that is only adapters/ — importing `adapters` itself
# pulls in every engine and the vault client.
_pkg = types.ModuleType("drive_adapters")
_pkg.__path__ = [os.path.join(HERE, "adapters")]
sys.modules["drive_adapters"] = _pkg
local = importlib.import_module("drive_adapters.local")
check("a path splits into NFC segments", local.split_path("/פגישות//2026-10-28/") == ["פגישות", "2026-10-28"])
try:
    local.split_path("/a/../b")
    check("'..' is refused", False)
except Exception as e:      # AdapterError
    check("'..' is refused", getattr(e, "status", 0) == 400)
try:
    local.clean_name("a/b")
    check("a name with / is refused", False)
except Exception as e:
    check("a name with / is refused", getattr(e, "status", 0) == 400)
ids = {local.new_id("lf") for _ in range(2000)}
check("ids are unique and carry their kind", len(ids) == 2000 and all(i.startswith("lf") for i in ids))

print("\n" + ("ALL PASSED" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
