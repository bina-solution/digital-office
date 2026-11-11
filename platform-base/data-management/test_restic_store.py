"""test_restic_store.py — restic's REST backend over the generic drive (restic_store.py, DGO-1513).

The REAL app (app.py) is served by uvicorn, against a fake generic drive that keeps the drive's HTTP
contract (apps/drive/ENGINES.md «For backup») on a real directory. Then:

  - the protocol, call by call: who is admitted, what a name must be, what an append-only target
    refuses, how the drive's answers are mapped;
  - real restic, when a binary is on PATH or in RESTIC_BIN: init, backup, check --read-data,
    restore byte-equal, forget refused on the append-only target, forget --prune on an open one,
    and the drive's folder opened directly as a local repository — what a copy downloaded by hand is.

  Without a restic binary that class is SKIPPED and only the protocol is proven: the image carries
  none. The fake drive checks `mode=exclusive` under a lock, so it cannot show an engine's own races
  (drive-google's unlocked folder creation); what the store does about those is tested by its effect
  (every data/<2 hex> made at create), not by reproducing the race.

    # the data-management image has fastapi and uvicorn; restic is copied out of restic/restic:0.18.0
    docker run --rm --network none -v "$PWD":/t -w /t -v <restic binary>:/usr/local/bin/restic:ro \
        <data-management image> python3 test_restic_store.py
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import unittest
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
WORK = pathlib.Path(tempfile.mkdtemp(prefix="restic-store-"))
os.environ["DATA_STATE_DIR"] = str(WORK / "state")
os.environ["DATA_REPO_TARGETS"] = str(WORK / "targets.json")
os.environ.setdefault("DEPLOYMENT_PATH", str(HERE.parent.parent))
(WORK / "state").mkdir()
sys.path.insert(0, str(HERE))

import uvicorn  # noqa: E402

import app as APP  # noqa: E402  (the real wiring: middleware, route order, the page fallback)
import restic_store as RS  # noqa: E402


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── a fake generic drive: the HTTP contract, on a directory ─────────────────────────────────────
class FakeDrive(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, root: pathlib.Path):
        self.root = root
        self.trash = root.parent / (root.name + "-trash")
        self.root.mkdir(parents=True, exist_ok=True)
        self.trash.mkdir(exist_ok=True)
        self.calls: list[tuple[str, str, dict]] = []
        self.marks: dict[str, str] = {}
        self.fail = 0                   # when set, every call answers this status
        self.whole_lists = False        # /api/files ignores limit/offset, as Google lists a folder whole
        self.keep_bytes = False         # /api/delete deletes nothing, as a storage that refused
        self.lock = threading.Lock()
        super().__init__(("127.0.0.1", _port()), _DriveHandler)

    def at(self, path: str) -> pathlib.Path:
        segs = [s for s in (path or "/").split("/") if s]
        assert ".." not in segs, path
        return self.root.joinpath(*segs)

    def fid(self, p: pathlib.Path) -> str:
        return ("f:" if p.is_file() else "d:") + str(p.relative_to(self.root))

    def by_id(self, fid: str) -> pathlib.Path:
        return self.root / fid[2:]

    def file_obj(self, p: pathlib.Path) -> dict:
        return {"id": self.fid(p), "name": p.name, "size": p.stat().st_size, "folder": self.fid(p.parent)}


class _DriveHandler(http.server.BaseHTTPRequestHandler):
    server: FakeDrive

    def log_message(self, *a):
        pass

    def _send(self, status, body=b"", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
            headers = {"Content-Type": "application/json", **(headers or {})}
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if "Content-Length" not in (headers or {}):
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _route(self):
        u = urllib.parse.urlsplit(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        self.server.calls.append((self.command, u.path, q))
        if self.server.fail:
            return self._send(self.server.fail, {"error": "engine restarting or refusing"})
        return u.path, q

    def do_GET(self):
        r = self._route()
        if not r:
            return
        path, q = r
        s = self.server
        if path == "/api/fs":
            p = s.at(q.get("path", "/"))
            if p.is_file():
                return self._send(200, {"kind": "file", "file": s.file_obj(p), "path": q["path"]})
            if p.is_dir():
                kids = sorted(c for c in p.iterdir() if c.is_dir())
                files = sorted(c for c in p.iterdir() if c.is_file())
                return self._send(200, {"kind": "folder", "folder": {"id": s.fid(p), "name": p.name, "path": q["path"]},
                                        "folders": [{"id": s.fid(c), "name": c.name} for c in kids],
                                        "files": [s.file_obj(c) for c in files]})
            return self._send(404, {"error": "nothing there"})
        if path == "/api/files":
            p = s.by_id(q["folder"])
            files = sorted(c for c in p.iterdir() if c.is_file()) if p.is_dir() else []
            if not s.whole_lists:
                off, lim = int(q.get("offset", 0)), int(q.get("limit", 1000))
                files = files[off:off + lim]
            return self._send(200, {"files": [s.file_obj(c) for c in files], "folders": []})
        if path == "/api/fs/content":
            p = s.at(q.get("path", ""))
            if not p.is_file():
                return self._send(404, {"error": "no file"})
            data = p.read_bytes()
            rng = self.headers.get("Range")
            if rng:
                a, _, b = rng.replace("bytes=", "").partition("-")
                a = int(a)
                b = int(b) if b else len(data) - 1
                part = data[a:b + 1]
                return self._send(206, part, {"Content-Range": f"bytes {a}-{a + len(part) - 1}/{len(data)}",
                                              "Content-Length": str(len(part))})
            return self._send(200, data, {"Content-Length": str(len(data))})
        return self._send(404, {"error": "no route"})

    def do_PUT(self):
        r = self._route()
        if not r:
            return
        path, q = r
        s = self.server
        if path != "/api/fs/content":
            return self._send(404, {})
        p = s.at(q["path"])
        n = int(self.headers["Content-Length"])
        body = self.rfile.read(n)
        with s.lock:
            if q.get("mode") == "exclusive" and p.exists():
                return self._send(409, {"error": "taken"})
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = s.root.parent / f".up-{threading.get_ident()}"
            tmp.write_bytes(body)
            os.replace(tmp, p)               # whole before visible, as the drive's index row
        return self._send(201, {"file": s.file_obj(p), "path": q["path"]})

    def do_POST(self):
        r = self._route()
        if not r:
            return
        path, q = r
        s = self.server
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if path == "/api/fs/mkdir":
            p = s.at(body["path"])
            p.mkdir(parents=True, exist_ok=True)
            if body.get("system"):
                s.marks.setdefault(body["path"], body["system"])
            return self._send(200, {"id": s.fid(p), "path": body["path"]})
        if path == "/api/trash":
            n = 0
            for fid in body.get("ids") or []:
                p = s.by_id(fid)
                if p.is_file():
                    os.replace(p, s.trash / fid.replace("/", "%"))
                    n += 1
            return self._send(200, {"ok": True, "count": n})
        if path == "/api/delete":
            n = 0
            for fid in body.get("ids") or []:
                t = s.trash / fid.replace("/", "%")
                if t.is_file() and not s.keep_bytes:
                    t.unlink()
                    n += 1
            return self._send(200, {"ok": True, "deleted": n})
        return self._send(404, {})


# ── the stack under test ────────────────────────────────────────────────────────────────────────
DRIVE: FakeDrive
BASE: str
SERVER: uvicorn.Server


def setUpModule():
    global DRIVE, BASE, SERVER
    DRIVE = FakeDrive(WORK / "files")
    threading.Thread(target=DRIVE.serve_forever, daemon=True).start()
    drive_url = f"http://127.0.0.1:{DRIVE.server_address[1]}"
    (WORK / "targets.json").write_text(json.dumps({"targets": {
        "herd-exampleu": {"url": drive_url, "connection_id": "conn-herd", "folder": "/גיבויים/exampleu",
                        "append_only": True},
        "own-exampleu": {"url": drive_url, "connection_id": "conn-own", "folder": "/DGO backups/exampleu",
                       "append_only": False},
    }}, ensure_ascii=False))
    port = _port()
    SERVER = uvicorn.Server(uvicorn.Config(APP.app, host="127.0.0.1", port=port, log_level="warning",
                                           lifespan="off"))
    threading.Thread(target=SERVER.run, daemon=True).start()
    for _ in range(100):
        if SERVER.started:
            break
        time.sleep(0.05)
    BASE = f"http://127.0.0.1:{port}"


def tearDownModule():
    SERVER.should_exit = True
    DRIVE.shutdown()
    shutil.rmtree(WORK, ignore_errors=True)


def call(method, path, body=None, auth=None, headers=None):
    hdrs = dict(headers or {})
    if auth:
        hdrs["Authorization"] = "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
    # `%` stays as written: a test that sends %2F or %0A means the server to receive exactly that
    req = urllib.request.Request(BASE + urllib.parse.quote(path, safe="/?=&%"), data=body, method=method,
                                 headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def obj(data: bytes) -> tuple[str, bytes]:
    return hashlib.sha256(data).hexdigest(), data


class Protocol(unittest.TestCase):
    """restic's REST v2, call by call."""

    @classmethod
    def setUpClass(cls):
        cls.herd = RS.RUNS.open("herd-exampleu")
        cls.own = RS.RUNS.open("own-exampleu")
        assert call("POST", "/repo/herd-exampleu/?create=true", b"", cls.herd)[0] == 200

    # who is admitted
    def test_no_token_is_refused_before_the_drive_is_asked(self):
        before = len(DRIVE.calls)
        for m, p in (("GET", "/repo/herd-exampleu/keys/"), ("HEAD", "/repo/herd-exampleu/config"),
                     ("POST", "/repo/herd-exampleu/?create=true")):
            self.assertEqual(call(m, p, b"" if m == "POST" else None)[0], 401, (m, p))
        self.assertEqual(len(DRIVE.calls), before)

    def test_a_token_opens_only_its_own_target(self):
        # two guards, each proven alone: the run's own target, and (below, over HTTP) the bound target
        hdr = "Basic " + base64.b64encode(f"{self.herd[0]}:{self.herd[1]}".encode()).decode()
        self.assertIsNone(RS.RUNS.admits(hdr, "own-exampleu"))
        self.assertIsNotNone(RS.RUNS.admits(hdr, "herd-exampleu"))
        self.assertEqual(call("GET", "/repo/own-exampleu/keys/", auth=self.herd)[0], 401)
        self.assertEqual(call("GET", "/repo/herd-exampleu/keys/", auth=(self.herd[0], "wrong"))[0], 401)
        self.assertEqual(call("GET", "/repo/nobody/keys/", auth=self.herd)[0], 401)
        self.assertEqual(call("GET", "/repo/herd-exampleu/keys/", auth=self.herd)[0], 200)

    def test_a_closed_or_expired_run_is_refused(self):
        u, tok = RS.RUNS.open("herd-exampleu")
        RS.RUNS.close(u)
        self.assertEqual(call("GET", "/repo/herd-exampleu/keys/", auth=(u, tok))[0], 401)
        u, tok = RS.RUNS.open("herd-exampleu", idle=0)
        self.assertEqual(call("GET", "/repo/herd-exampleu/keys/", auth=(u, tok))[0], 401)

    def test_a_busy_run_stays_open_an_idle_one_closes_and_none_outlives_its_cap(self):
        clock = [0.0]
        runs = RS.Runs(clock=lambda: clock[0])
        hdr = lambda r: "Basic " + base64.b64encode(f"{r[0]}:{r[1]}".encode()).decode()  # noqa: E731
        busy = runs.open("herd-exampleu", idle=10, cap=1000)
        for t in (9, 18, 27, 36):                       # each call moves the idle deadline on
            clock[0] = t
            self.assertIsNotNone(runs.admits(hdr(busy), "herd-exampleu"), t)
        clock[0] = 47
        self.assertIsNone(runs.admits(hdr(busy), "herd-exampleu"), "idle for 11 s past a 10 s window")
        clock[0] = 0
        capped = runs.open("herd-exampleu", idle=10, cap=15)
        for t, ok in ((9, True), (14, True), (16, False)):
            clock[0] = t
            self.assertEqual(runs.admits(hdr(capped), "herd-exampleu") is not None, ok, t)

    def test_no_run_opens_for_an_undeclared_target(self):
        with self.assertRaises(KeyError):
            RS.RUNS.open("nobody")

    # what a name must be
    def test_an_object_is_written_once_under_its_own_hash(self):
        name, data = obj(b"pack-1" * 1000)
        self.assertEqual(call("POST", f"/repo/herd-exampleu/data/{name}", data, self.herd)[0], 200)
        stored = DRIVE.root / "גיבויים/exampleu/data" / name[:2] / name
        self.assertTrue(stored.is_file())
        self.assertEqual(call("HEAD", f"/repo/herd-exampleu/data/{name}", auth=self.herd)[1].get("content-length"),
                         str(len(data)))
        # a retry of a write that landed while its answer was lost meets its own object: done, not refused
        self.assertEqual(call("POST", f"/repo/herd-exampleu/data/{name}", data, self.herd)[0], 200)
        self.assertEqual(stored.read_bytes(), data)
        # something else already under a name restic is writing was not written by restic: refused
        other, odata = obj(b"pack-2" * 1000)
        planted = DRIVE.root / "גיבויים/exampleu/data" / other[:2] / other
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_bytes(b"a person's file under that name")
        self.assertEqual(call("POST", f"/repo/herd-exampleu/data/{other}", odata, self.herd)[0], 403)
        self.assertEqual(planted.read_bytes(), b"a person's file under that name")

    def test_a_name_with_a_trailing_newline_is_no_name(self):
        name, data = obj(b"newline")
        self.assertEqual(call("POST", f"/repo/herd-exampleu/snapshots/{name}%0A", data, self.herd)[0], 404)
        self.assertEqual(call("GET", f"/repo/herd-exampleu/snapshots/{name}%0A", auth=self.herd)[0], 404)

    def test_bytes_that_are_not_their_name_never_reach_the_drive(self):
        name, _ = obj(b"what the name says")
        before = len(DRIVE.calls)
        self.assertEqual(call("POST", f"/repo/herd-exampleu/index/{name}", b"something else", self.herd)[0], 400)
        self.assertEqual([c for c in DRIVE.calls[before:] if c[0] == "PUT"], [])

    def test_a_name_or_kind_restic_never_uses_is_404(self):
        for p in ("/repo/herd-exampleu/data/..%2F..%2Fetc", "/repo/herd-exampleu/data/ABC",
                  "/repo/herd-exampleu/other/" + "a" * 64, "/repo/herd-exampleu/config/"):
            self.assertEqual(call("GET", p, auth=self.herd)[0], 404, p)

    def test_an_oversized_body_is_refused(self):
        old = RS.MAX_OBJECT
        RS.MAX_OBJECT = 1000
        try:
            name, data = obj(b"x" * 2000)
            self.assertEqual(call("POST", f"/repo/herd-exampleu/data/{name}", data, self.herd)[0], 413)
        finally:
            RS.MAX_OBJECT = old

    # reading
    def test_ranged_read_and_lists_v1_v2(self):
        name, data = obj(bytes(range(256)) * 40)
        call("POST", f"/repo/herd-exampleu/snapshots/{name}", data, self.herd)
        st, h, body = call("GET", f"/repo/herd-exampleu/snapshots/{name}", auth=self.herd,
                           headers={"Range": "bytes=10-19"})
        self.assertEqual((st, body), (206, data[10:20]))
        st, h, body = call("GET", f"/repo/herd-exampleu/snapshots/{name}", auth=self.herd)
        self.assertEqual((st, body), (200, data))
        st, h, body = call("GET", "/repo/herd-exampleu/snapshots/", auth=self.herd, headers={"Accept": RS.V2})
        self.assertEqual(h.get("content-type"), RS.V2)
        self.assertIn({"name": name, "size": len(data)}, json.loads(body))
        st, h, body = call("GET", "/repo/herd-exampleu/snapshots/", auth=self.herd)
        self.assertIn(name, json.loads(body))
        self.assertEqual(call("GET", "/repo/herd-exampleu/snapshots/" + "0" * 64, auth=self.herd)[0], 404)
        self.assertEqual(call("HEAD", "/repo/herd-exampleu/snapshots/" + "0" * 64, auth=self.herd)[0], 404)

    def test_data_lists_across_its_prefix_folders_and_only_names_restic_wrote(self):
        names = []
        for i in range(5):
            n, d = obj(f"blob-{i}".encode())
            call("POST", f"/repo/herd-exampleu/data/{n}", d, self.herd)
            names.append(n)
        stray = DRIVE.root / "גיבויים/exampleu/data" / names[0][:2] / (names[0] + " (2)")
        stray.write_bytes(b"a copy a person made")
        not_hex = DRIVE.root / "גיבויים/exampleu/data/zz"
        not_hex.mkdir(exist_ok=True)
        (not_hex / ("a" * 64)).write_bytes(b"in a folder restic never makes")
        wrong_prefix = DRIVE.root / "גיבויים/exampleu/data/ab"
        wrong_prefix.mkdir(exist_ok=True)
        (wrong_prefix / ("cd" + "0" * 62)).write_bytes(b"under a prefix that is not its own")
        body = json.loads(call("GET", "/repo/herd-exampleu/data/", auth=self.herd, headers={"Accept": RS.V2})[2])
        got = {o["name"] for o in body}
        self.assertTrue(set(names) <= got)
        self.assertNotIn(names[0] + " (2)", got)
        self.assertNotIn("a" * 64, got)
        self.assertNotIn("cd" + "0" * 62, got, "listed, it would be read at data/cd/… where it is not")

    def test_a_listing_pages_and_stops_when_an_engine_ignores_the_page(self):
        d = RS.Drive(f"http://127.0.0.1:{DRIVE.server_address[1]}", "conn-herd")
        folder = DRIVE.root / "paging"
        folder.mkdir(exist_ok=True)
        for i in range(25):
            (folder / f"{i:064x}").write_bytes(b"x")
        fid = DRIVE.fid(folder)
        self.assertEqual(len(d.files(fid, page=10)), 25)
        DRIVE.whole_lists = True
        try:
            self.assertEqual(len(d.files(fid, page=10)), 25)
        finally:
            DRIVE.whole_lists = False

    # removing
    def test_append_only_target_refuses_every_delete_but_a_lock(self):
        n, d = obj(b"a snapshot to keep")
        call("POST", f"/repo/herd-exampleu/snapshots/{n}", d, self.herd)
        self.assertEqual(call("DELETE", f"/repo/herd-exampleu/snapshots/{n}", auth=self.herd)[0], 403)
        self.assertEqual(call("DELETE", "/repo/herd-exampleu/config", auth=self.herd)[0], 403)
        self.assertEqual(call("DELETE", "/repo/herd-exampleu/", auth=self.herd)[0], 405)
        self.assertTrue((DRIVE.root / "גיבויים/exampleu/snapshots" / n).is_file())
        lock, ld = obj(b"a lock")
        call("POST", f"/repo/herd-exampleu/locks/{lock}", ld, self.herd)
        self.assertEqual(call("DELETE", f"/repo/herd-exampleu/locks/{lock}", auth=self.herd)[0], 200)
        self.assertFalse((DRIVE.root / "גיבויים/exampleu/locks" / lock).exists())
        self.assertEqual(list(DRIVE.trash.glob("*" + lock)), [], "the delete left the lock in the trash")

    def test_an_open_target_deletes_hard(self):
        call("POST", "/repo/own-exampleu/?create=true", b"", self.own)
        n, d = obj(b"forgotten")
        call("POST", f"/repo/own-exampleu/snapshots/{n}", d, self.own)
        self.assertEqual(call("DELETE", f"/repo/own-exampleu/snapshots/{n}", auth=self.own)[0], 200)
        self.assertEqual(call("DELETE", f"/repo/own-exampleu/snapshots/{n}", auth=self.own)[0], 404)
        self.assertEqual(list(DRIVE.trash.glob("*" + n)), [])

    def test_a_delete_the_storage_refused_is_not_a_success(self):
        n, d = obj(b"kept by a stubborn storage")
        call("POST", f"/repo/own-exampleu/snapshots/{n}", d, self.own)
        DRIVE.keep_bytes = True
        try:
            self.assertEqual(call("DELETE", f"/repo/own-exampleu/snapshots/{n}", auth=self.own)[0], 502)
        finally:
            DRIVE.keep_bytes = False

    # the drive's own answers
    def test_every_call_names_the_targets_connection(self):
        before = len(DRIVE.calls)
        call("GET", "/repo/own-exampleu/keys/", auth=self.own)
        made = DRIVE.calls[before:]
        self.assertTrue(made)
        self.assertTrue(all(c[2].get("connection_id") == "conn-own" for c in made), made)

    def test_a_drive_that_cannot_answer_is_a_503_restic_retries(self):
        DRIVE.fail = 503
        try:
            self.assertEqual(call("HEAD", "/repo/herd-exampleu/config", auth=self.herd)[0], 503)
            n, d = obj(b"while the engine restarts")
            self.assertEqual(call("POST", f"/repo/herd-exampleu/data/{n}", d, self.herd)[0], 503)
        finally:
            DRIVE.fail = 0

    def test_a_drive_that_cannot_serve_the_target_is_not_retried(self):
        DRIVE.fail = 501                                # «this connection does not support paths»
        try:
            st, _, body = call("HEAD", "/repo/herd-exampleu/config", auth=self.herd)
            self.assertEqual(st, 403)                   # restic gives up at once instead of for 15 minutes
            st, _, body = call("GET", "/repo/herd-exampleu/keys/", auth=self.herd)
            self.assertEqual(st, 403)
            self.assertIn(b"HTTP 501", body)
        finally:
            DRIVE.fail = 0

    def test_create_makes_and_marks_every_folder_one_at_a_time(self):
        base = DRIVE.root / "גיבויים/exampleu"
        for kind in RS.KINDS:
            self.assertTrue((base / kind).is_dir(), kind)
            self.assertEqual(DRIVE.marks.get(f"/גיבויים/exampleu/{kind}"), RS.SYSTEM_MARK, kind)
        self.assertEqual(DRIVE.marks.get("/גיבויים/exampleu"), RS.SYSTEM_MARK)
        made = sorted(p.name for p in (base / "data").iterdir() if p.is_dir())
        self.assertTrue({f"{i:02x}" for i in range(256)} <= set(made), "every data/<2 hex> before any pack")
        self.assertEqual(DRIVE.marks.get("/גיבויים/exampleu/data/ff"), RS.SYSTEM_MARK)

    def test_a_target_changed_under_a_run_ends_the_run(self):
        f = WORK / "targets.json"
        good = f.read_text()
        run = RS.RUNS.open("herd-exampleu")
        self.assertEqual(call("GET", "/repo/herd-exampleu/keys/", auth=run)[0], 200)
        changed = json.loads(good)
        changed["targets"]["herd-exampleu"]["append_only"] = False
        f.write_text(json.dumps(changed, ensure_ascii=False))
        try:
            n, d = obj(b"a snapshot a run would like gone")
            st, _, body = call("DELETE", f"/repo/herd-exampleu/snapshots/{n}", auth=run)
            self.assertEqual(st, 401)
            self.assertIn(b"changed", body)
        finally:
            f.write_text(good)

    # the wiring in app.py
    def test_the_page_fallback_never_answers_a_repo_path(self):
        st, h, body = call("GET", "/repo/herd-exampleu/nothing/here/at/all")
        self.assertEqual(st, 404)
        self.assertNotIn(b"<html", body.lower())


class Targets(unittest.TestCase):
    def test_a_target_is_checked_before_use(self):
        u = "http://files.example:8975"
        ok = RS.check_target("herd-exampleu", {"url": u + "/", "folder": "/גיבויים/exampleu/"})
        self.assertEqual(ok, {"url": u, "connection_id": "", "folder": "/גיבויים/exampleu", "append_only": True})
        # the folder as the drive will resolve it: each segment NFC and trimmed
        nfd = unicodedata.normalize("NFD", "/גיבויים/קבצֵי")
        self.assertEqual(RS.check_target("x", {"url": u, "folder": "/ גיבויים /exampleu "})["folder"], "/גיבויים/exampleu")
        self.assertEqual(RS.check_target("x", {"url": u, "folder": nfd})["folder"],
                         unicodedata.normalize("NFC", "/גיבויים/קבצֵי"))
        for tid, t in (("Herd", {"url": u, "folder": "/x"}), ("x", {"url": u, "folder": "relative"}),
                       ("x", {"url": u, "folder": "/a/../b"}), ("x", {"url": u, "folder": "/"}),
                       ("x", {"url": u, "folder": "/ "}),            # trimmed by the drive: its root
                       ("x", {"url": u, "folder": "/a/ /b"}),
                       ("x", {"url": u, "folder": "/a\\b"}),         # a backslash is a slash to the drive
                       ("x\n", {"url": u, "folder": "/a"}),
                       ("x", {"folder": "/a"}),                       # no address: never a default
                       ("x", {"url": "file:///etc", "folder": "/a"}),
                       ("x", {"url": "http://u:p@files.example", "folder": "/a"}),
                       ("x", {"url": "http://:p@files.example", "folder": "/a"}),
                       ("x", {"url": u + "/?x=1", "folder": "/a"}),
                       ("x", {"url": u, "folder": "/a", "connection_id": "a b"}),
                       ("x", {"url": u, "folder": "/a", "connection_id": "conn\n"}),
                       ("x", {"url": u, "folder": "/a", "append_only": "no"})):
            with self.assertRaises(ValueError, msg=(tid, t)):
                RS.check_target(tid, t)

    def test_two_targets_over_one_place_are_refused_whole(self):
        f = WORK / "targets.json"
        good = f.read_text()
        herd = json.loads(good)["targets"]["herd-exampleu"]
        try:
            for alias in ("/גיבויים/exampleu", "/ גיבויים /exampleu/", "/גיבויים/exampleu/data", "/גיבויים"):
                t = json.loads(good)
                t["targets"]["alias"] = dict(herd, folder=alias, append_only=False)
                f.write_text(json.dumps(t, ensure_ascii=False))
                with self.assertRaises(ValueError, msg=alias):
                    RS.targets()
            t = json.loads(good)                        # the same folder on ANOTHER account is another place
            t["targets"]["alias"] = dict(herd, connection_id="conn-other", append_only=False)
            f.write_text(json.dumps(t, ensure_ascii=False))
            self.assertIn("alias", RS.targets())
            t["targets"]["alias"] = dict(herd, folder="/גיבויים/exampleu-2", append_only=False)
            f.write_text(json.dumps(t, ensure_ascii=False))
            self.assertIn("alias", RS.targets())        # a sibling whose name only starts the same
        finally:
            f.write_text(good)

    def test_a_broken_targets_file_is_a_503_naming_itself_only_to_a_run(self):
        f = WORK / "targets.json"
        good = f.read_text()
        u, tok = RS.RUNS.open("herd-exampleu")
        f.write_text('{"targets": {"x": {"url": "http://10.0.0.5:9000", "folder": "relative"}}}')
        try:
            st, _, body = call("GET", "/repo/herd-exampleu/keys/")
            self.assertEqual(st, 401)
            self.assertNotIn(b"targets.json", body)
            self.assertNotIn(b"10.0.0.5", body)
            st, _, body = call("GET", "/repo/herd-exampleu/keys/", auth=(u, tok))
            self.assertEqual(st, 503)
            self.assertIn(b"targets.json", body)
        finally:
            f.write_text(good)


# ── real restic ─────────────────────────────────────────────────────────────────────────────────
RESTIC = os.environ.get("RESTIC_BIN") or shutil.which("restic")


@unittest.skipUnless(RESTIC, "no restic binary (RESTIC_BIN or PATH)")
class RealRestic(unittest.TestCase):
    def restic(self, target, run, *args, ok=True, repo=None):
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(WORK), "RESTIC_CACHE_DIR": str(WORK / "cache"),
               "RESTIC_PASSWORD_FILE": str(WORK / "pw"),
               "RESTIC_REPOSITORY": repo or f"rest:http://{run[0]}:{run[1]}@{BASE[7:]}/repo/{target}/"}
        p = subprocess.run([RESTIC, "-q", *args], env=env, capture_output=True, text=True, timeout=300)
        if ok:
            self.assertEqual(p.returncode, 0, f"restic {' '.join(args)}\n{p.stdout}\n{p.stderr}")
        return p

    def test_backup_check_restore_forget_and_a_folder_opened_by_hand(self):
        (WORK / "pw").write_text("a test password, not a secret\n")
        src = WORK / "src"
        (src / "app" / "volumes").mkdir(parents=True)
        (src / "app" / "dumps").mkdir(parents=True)
        (src / "app" / "dumps" / "plane.dump").write_bytes(os.urandom(3 * 1024 * 1024))
        (src / "app" / "volumes" / "notes.txt").write_text("פגישה עם ישראל\n" * 500)
        os.symlink("notes.txt", src / "app" / "volumes" / "link")

        # the protocol tests above wrote objects that are not a repository's: a target of its own
        tgt = json.loads((WORK / "targets.json").read_text())
        tgt["targets"]["herd-real"] = dict(tgt["targets"]["herd-exampleu"], folder="/גיבויים/real")
        tgt["targets"]["own-real"] = dict(tgt["targets"]["own-exampleu"], folder="/DGO backups/real")
        (WORK / "targets.json").write_text(json.dumps(tgt, ensure_ascii=False))
        herd, own = RS.RUNS.open("herd-real"), RS.RUNS.open("own-real")

        self.restic("herd-real", herd, "init")
        self.restic("herd-real", herd, "backup", "--host", "exampleu", "--tag", "app=plane", str(src))
        (src / "app" / "volumes" / "notes.txt").write_text("שונה\n")
        self.restic("herd-real", herd, "backup", "--host", "exampleu", "--tag", "app=plane", str(src))
        snaps = json.loads(self.restic("herd-real", herd, "snapshots", "--json").stdout)
        self.assertEqual(len(snaps), 2)
        self.restic("herd-real", herd, "check", "--read-data")

        out = WORK / "restored"
        self.restic("herd-real", herd, "restore", snaps[0]["short_id"], "--target", str(out))
        got = out / str(src).lstrip("/") / "app"
        self.assertEqual((got / "dumps" / "plane.dump").read_bytes(), (src / "app" / "dumps" / "plane.dump").read_bytes())
        self.assertEqual((got / "volumes" / "notes.txt").read_text(), "פגישה עם ישראל\n" * 500)
        self.assertEqual(os.readlink(got / "volumes" / "link"), "notes.txt")

        # the office cannot erase its copies on the herd store
        p = self.restic("herd-real", herd, "forget", "--keep-last", "1", "--prune", ok=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("403", p.stderr, "refused by the append-only rule, not by something else")
        self.assertEqual(len(json.loads(self.restic("herd-real", herd, "snapshots", "--json").stdout)), 2)

        # a copy downloaded by hand: the drive's folder IS a restic repository, opened with nothing of DGO
        local = DRIVE.root / "גיבויים" / "real"
        self.restic("", None, "check", "--read-data", repo=str(local))
        self.assertEqual(len(json.loads(self.restic("", None, "snapshots", "--json", repo=str(local)).stdout)), 2)

        # where the target is open (the office's own account), forget and prune work
        self.restic("own-real", own, "init")
        for _ in range(3):
            self.restic("own-real", own, "backup", "--host", "exampleu", str(src))
        self.restic("own-real", own, "forget", "--keep-last", "1", "--prune")
        self.assertEqual(len(json.loads(self.restic("own-real", own, "snapshots", "--json").stdout)), 1)
        self.restic("own-real", own, "check", "--read-data")
        # no lock left behind on either
        self.assertEqual(list((DRIVE.root / "גיבויים" / "real" / "locks").iterdir()), [])
        self.assertEqual(list((DRIVE.root / "DGO backups" / "real" / "locks").iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
