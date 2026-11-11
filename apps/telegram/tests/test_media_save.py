#!/usr/bin/env python3
"""test_media_save — a Telegram file of any size reaches the office's drive in pieces, memory flat (DGO-1805).

    python3 apps/telegram/tests/test_media_save.py     (telethon, fastapi, requests: the telegram image)

The owner sent a 97 MB video and asked to download it through the personal account and transcribe it; `/api/media`
refuses above 20 MiB because it holds a file whole in a 192M container. Here the REAL save (app.save_media) runs
with Telegram and the drive stood in for: a client whose iter_download yields fresh chunks as the network gives
them, and a drive that is an HTTP server on loopback speaking its tus routes — it counts the bytes and keeps none.
Run it in a container of 192M (the telegram container's own limit) and a 100 MB file must pass:

    docker run --memory 192m … python3 tests/test_media_save.py

What it asks: the file arrives whole, in pieces no larger than DRIVE_PIECE, at «טלגרם/<chat>/<message>-<name>», with
the Python heap's peak a few pieces, not the file; a second save answers the file that is there; a stream that ends
short is refused and its upload session removed; the drive's own size refusal is said; an unwatched chat and
BotFather are refused; `/api/media` still refuses a large file — and names the way that works.
"""
from __future__ import annotations

import asyncio
import http.server
import json
import os
import sys
import tempfile
import threading
import tracemalloc
import types
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ.setdefault("TG_DATA_DIR", tempfile.mkdtemp(prefix="tg-test-"))
try:                                                         # the stream's reader only: stood in for when absent
    import redis  # noqa: F401
except ImportError:
    _r = types.ModuleType("redis")
    _r.asyncio = types.ModuleType("redis.asyncio")
    _r.asyncio.Redis = lambda **kw: None
    sys.modules["redis"], sys.modules["redis.asyncio"] = _r, _r.asyncio
try:
    import fastapi  # noqa: F401
    import requests  # noqa: F401
    import telethon  # noqa: F401
except ImportError as e:                                     # G72's convention: one NOT RUN line, a non-zero exit
    print(f"NOT RUN needs the package `{e.name}` (the telegram image has it)")
    sys.exit(1)
import app  # noqa: E402

FAIL: list[str] = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAIL.append(what)


# ── the drive, on loopback: its tus routes, counting and discarding ─────────────────────────────────────────────────
class Drive:
    ceiling = 2 * 1024 ** 3
    sessions: dict = {}
    files: set = set()
    pieces: list = []
    deleted: list = []
    fail: list = []                                          # what the next PATCHes do: "refuse" / "lose" / None
    never_done = False                                       # every byte taken, and the storing never ends
    n = 0


class DriveHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, doc=None):
        raw = json.dumps(doc or {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def do_GET(self):
        u = urlsplit(self.path)
        if u.path == "/api/fs":
            return self._send(200 if parse_qs(u.query).get("path", [""])[0] in Drive.files else 404)
        sid = u.path.rsplit("/", 1)[-1]
        s = Drive.sessions.get(sid)
        # as the real drive: a finished session's part file is gone, so its offset reads 0
        return self._send(200 if s else 404, {"state": "done" if s and s["done"] else "uploading",
                                              "offset": s["offset"] if s and not s["done"] else 0})

    def do_POST(self):
        u = urlsplit(self.path)
        b = json.loads(self._body() or b"{}")
        if u.path == "/api/fs/mkdir":
            return self._send(200, {})
        if b.get("size", 0) > Drive.ceiling:
            return self._send(413, {"error": "הקובץ גדול מהמותר באחסון"})
        Drive.n += 1
        sid = f"u{Drive.n}"
        Drive.sessions[sid] = {"size": int(b["size"]), "offset": 0, "path": f"{b['path']}/{b['name']}", "done": False}
        return self._send(201, {"id": sid, "offset": 0, "size": int(b["size"])})

    def do_PATCH(self):
        s = Drive.sessions.get(urlsplit(self.path).path.rsplit("/", 1)[-1])
        left, got = int(self.headers.get("Content-Length") or 0), 0
        while left:                                          # read and drop: the drive's disk is not this test's
            chunk = self.rfile.read(min(65536, left))
            got, left = got + len(chunk), left - len(chunk)
        mode = Drive.fail.pop(0) if Drive.fail else None
        if mode == "refuse":                                 # a passing error: nothing stored
            return self._send(502, {"error": "busy"})
        if s is None or int(self.headers.get("Upload-Offset", -1)) != s["offset"] or s["offset"] + got > s["size"]:
            return self._send(409, {"error": "offset"})
        s["offset"] += got
        Drive.pieces.append(got)
        if s["offset"] == s["size"] and not Drive.never_done:
            s["done"] = True
            Drive.files.add(s["path"])
        if mode == "lose":                                   # stored — and the answer lost on the way back
            return self._send(502, {"error": "gateway"})
        if s["done"]:
            return self._send(202, {"state": "done"})
        self.send_response(204)
        self.end_headers()

    def do_DELETE(self):
        Drive.deleted.append(urlsplit(self.path).path.rsplit("/", 1)[-1])
        self.send_response(204)
        self.end_headers()


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), DriveHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()
app.DRIVE_URL = f"http://127.0.0.1:{server.server_address[1]}"


# ── Telegram, stood in for: messages, and a download that yields fresh chunks ───────────────────────────────────────
class File:
    def __init__(self, name, size, mime):
        self.name, self.size, self.mime_type = name, size, mime


class Msg:
    def __init__(self, mid, size, kind="video", name="", mime="video/mp4"):
        self.id, self.media, self.file, self._kind = mid, object(), File(name, size, mime), kind

    def __getattr__(self, attr):                             # media_of asks photo / video / document …: one is set
        return object() if attr == self._kind else None


class Client:
    short_by = 0
    hang_after = None                                        # bytes after which the download never yields again

    def __init__(self, msgs):
        self.msgs = {m.id: m for m in msgs}

    async def get_messages(self, chat, ids):
        return self.msgs.get(ids)

    async def get_dialogs(self, limit=0):
        return []

    async def iter_download(self, media, request_size, file_size):
        sent, total = 0, file_size - Client.short_by
        while sent < total:
            if Client.hang_after is not None and sent >= Client.hang_after:
                await asyncio.Event().wait()                 # a data centre that stops answering, for good
            n = min(request_size, total - sent)
            yield bytes(n)                                   # a new chunk each time, as the network hands it over
            sent += n
            await asyncio.sleep(0)

    async def download_media(self, msg, file=bytes):
        return bytes(msg.file.size)


CHAT, OLD_CHAT, TITLE = -1004303648995, -4303648995, "בינה פיתרונות ראשי"   # a group and the supergroup it became
BIG = 100 * 1024 * 1024 + 4321                               # 100 MB and change: the last piece is a short one
CLIENT = Client([Msg(825, BIG), Msg(826, 300_000, kind="photo", mime="image/jpeg"), Msg(827, 9_000_000),
                 Msg(828, 5_000_000, kind="document", name="דוח/רבעון 3‮gpj.exe", mime="application/pdf"),
                 Msg(829, 0), Msg(830, 6_000_000), Msg(831, 6_000_000), Msg(832, 6_000_000)])
app.ACCOUNT.need = lambda: CLIENT
app.watched = lambda: {str(CHAT): {"id": CHAT, "title": TITLE}, str(OLD_CHAT): {"id": OLD_CHAT, "title": TITLE},
                       str(app.BOTFATHER_ID): {"id": app.BOTFATHER_ID, "title": "BotFather"}}
EVENTS: list = []


async def _publish(type_, title, data=None, link=""):
    EVENTS.append((type_, title, data or {}))


app.FLOW.publish = _publish
folder = f"/{app.DRIVE_FOLDER}/{TITLE} ({CHAT})"


async def save(chat, mid) -> dict:
    """The verb as a caller meets it: it answers at once, «saving»; the outcome is the record's, a moment later."""
    first = await app.save_media(chat, mid)
    while app.SAVES[(chat, mid)]["state"] == "saving":
        await asyncio.sleep(0.02)
    return {"first": first, **app.SAVES[(chat, mid)]}


async def main():
    # 1. the owner's case: a file five times the in-memory limit, its heap's peak measured while it moves
    tracemalloc.start()
    out = await save(CHAT, 825)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    check(out["first"]["state"] == "saving" and out["state"] == "saved",
          "the save answers at once («saving») and ends «saved» — the console's door never waits on it")
    check(out["path"] == f"{folder}/825-video.mp4" and out["size"] == BIG and out["already"] is False,
          f"a {BIG / 1048576:.1f} MB video lands at «טלגרם/<chat> (<id>)/825-video.mp4» ({out['path']})")
    check(sum(Drive.pieces) == BIG and max(Drive.pieces) <= app.DRIVE_PIECE and f"{folder}/825-video.mp4" in Drive.files,
          f"…whole, in {len(Drive.pieces)} pieces of at most {app.DRIVE_PIECE // 1048576} MB")
    check(peak < 4 * app.DRIVE_PIECE,
          f"…and the heap's peak while it moved was {peak / 1048576:.1f} MB — a few pieces, not the file")
    check(EVENTS and EVENTS[-1][0] == "media.saved" and EVENTS[-1][2].get("path") == out["path"],
          f"…said on the stream as media.saved with its path ({EVENTS[-1][:2] if EVENTS else None})")

    # 2. the same message again: the file that is there, not a second copy; its state is asked by the GET route
    n_before = Drive.n
    again = await app.save_media(CHAT, 825)
    check(again["already"] is True and again["state"] == "saved" and Drive.n == n_before,
          "a second save answers the file already in the drive")
    st = await app.api_media_save_state(CHAT, 825)
    check(st.status_code == 200 and json.loads(st.body)["path"] == out["path"], "GET /api/media/save says where it is")
    # …and the SAME number in the group the supergroup came from is another file, in its own folder
    other = await save(OLD_CHAT, 825)
    check(other["state"] == "saved" and other["path"] != out["path"] and f"({OLD_CHAT})" in other["path"],
          f"one title, two chats: message 825 of each is its own file ({other['path']})")

    # 3. a photo (through download_media) and a document whose name hides a right-to-left override and holds a «/»
    p = await save(CHAT, 826)
    check(p["path"].startswith(f"{folder}/826-photo.") and p["path"] in Drive.files, f"a photo is saved ({p['path']})")
    d = await save(CHAT, 828)
    check(d["path"] == f"{folder}/828-דוח רבעון 3 gpj.exe",
          f"a file's own name is kept, its «/» and its hidden override made spaces ({d['path']!r})")

    # 4. Telegram ends short: failed, and the upload session removed from the drive
    Client.short_by = 1000
    r = await save(CHAT, 827)
    check(r["state"] == "failed" and "לא נשמר" in r["error"] and f"u{Drive.n}" in Drive.deleted
          and f"{folder}/827-video.mp4" not in Drive.files,
          f"a stream that ends short fails and its session is removed ({r.get('error')})")
    Client.short_by = 0
    check(EVENTS[-1][0] == "media.failed", f"…said on the stream as media.failed ({EVENTS[-1][1]})")

    # 5. the drive's own ceiling
    Drive.ceiling = 1_000_000
    r = await save(CHAT, 827)
    check(r["state"] == "failed" and "לא נשמר" in r["error"], f"the drive's size refusal is said ({r.get('error')})")
    Drive.ceiling = 2 * 1024 ** 3

    # 6. who may: a chat nobody listens to, and BotFather even when listed; a file Telegram gives no size
    for chat, mid, code, what in ((-100999, 1, 403, "a chat the office does not listen to"),
                                  (app.BOTFATHER_ID, 1, 403, "BotFather"),
                                  (CHAT, 829, 422, "a file of 0 bytes (no session is opened, no slot is held)")):
        try:
            await app.save_media(chat, mid)
            check(False, f"{what} is refused")
        except app.HTTPException as e:
            check(e.status_code == code, f"{what} is refused at once ({e.status_code})")

    # 7. the drive stumbles once: a refused piece is sent again, and a piece stored whose answer was lost is not sent
    #    twice — the download minutes old goes on. Twice in a row on one piece ends it, its session removed.
    app_sleep, app.asyncio.sleep = asyncio.sleep, (lambda s: app_sleep(0))   # its 2-second pause, not this test's
    Drive.fail = ["refuse", None, "lose"]
    r = await save(CHAT, 830)
    check(r["state"] == "saved" and r["path"] in Drive.files,
          f"a refused piece is sent again and a stored one is not sent twice — saved ({r.get('error')})")
    Drive.fail = ["refuse", "refuse"]
    r = await save(CHAT, 831)
    check(r["state"] == "failed" and f"u{Drive.n}" in Drive.deleted,
          f"…and the same piece refused twice ends it, its session removed ({r.get('error')})")
    app.asyncio.sleep, Drive.fail = app_sleep, []

    # 8. a download that hangs ends at the save's deadline — failed, its session removed, and the slot free for the
    #    next save (it held every other save for good before)
    Client.hang_after, app.SAVE_MAX_S = 4 * 1024 * 1024, 1
    r = await save(CHAT, 832)
    check(r["state"] == "failed" and "לא הסתיימה" in r["error"] and f"u{Drive.n}" in Drive.deleted,
          f"a download that hangs ends at the deadline, its session removed ({r.get('error')})")
    Client.hang_after = None
    check(not app.SAVE_SLOT.locked(), "…and the save slot is free again")
    # …and when the deadline falls while the drive is still storing it, the session is dropped too (no «failed» file
    #    turning up later)
    Drive.never_done = True
    r = await save(OLD_CHAT, 832)
    check(r["state"] == "failed" and f"u{Drive.n}" in Drive.deleted,
          f"a deadline during the drive's storing drops the session as well ({r.get('error')})")
    Drive.never_done, app.SAVE_MAX_S = False, 3 * 3600

    # 9. the in-memory route still refuses the big file — and names the way that works
    try:
        await app.api_media(CHAT, 825)
        check(False, "/api/media refuses the 100 MB file")
    except app.HTTPException as e:
        check(e.status_code == 413 and "media-save" in e.detail and "api/media/save" in e.detail,
              f"/api/media still refuses it, naming media-save ({e.status_code})")


asyncio.run(main())
server.shutdown()
print("test_media_save: " + ("ok" if not FAIL else f"{len(FAIL)} FAILED"))
sys.exit(1 if FAIL else 0)
