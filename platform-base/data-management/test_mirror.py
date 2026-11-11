"""test_mirror.py — a client office's backup, PULLED into the herd store (mirror.py, DGO-1523).

Exampleu backs up into a repository on its own files app (target `client-own`, `mirror_to: hp-laptop`). The HP keeps
the herd's copy by pulling it over the link it already has: a run that only reads, opened at Exampleu's
/api/repo-runs with the pair's proof, through Exampleu's door (which writes `x-dgo-office: hp-laptop`). Nothing of
the HP is opened to Exampleu.

One process plays both offices, as test_herd_store.py: the real app under uvicorn, its fake drive, one fake vault
holding both ends of the pair, and a fake door. Proven:

  - a pull copies config, keys, data, index and snapshots, each checked against its name, and a second pull
    copies nothing; what the source adds later is copied, and nothing the source removed leaves the mirror;
  - the run that pulls reads only: every write, delete and create of it is refused (403);
  - only the office named in `mirror_to` opens it, only through its own link; a target with no `mirror_to` is
    read by nobody;
  - bytes that are not their name are never written, and nothing after them is copied (no snapshot before its
    packs); another config at the source stops the pull before a byte is copied;
  - a source with no repository is refused and the night is not spent; backup_run.run pulls a mirror target and
    keeps its result, and never exports into it;
  - a target that mixes a mirror with a gift or with being read, or a mirror that is not append-only, is refused.

    python3 test_mirror.py      (in the data-management image: fastapi, uvicorn; no docker, no restic needed)
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import secrets
import sys
import threading
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import test_herd_store as H  # noqa: E402  (the real app, the fake drive, the vault with both ends, the door)

T, RS, BR, LP = H.T, H.RS, H.BR, H.LP
import mirror as MIRROR  # noqa: E402

SRC_DOOR: H.Door       # Exampleu's door, as the HP's requests arrive at it
DRIVE_URL = ""
LOG: list[str] = []


def obj(data: bytes) -> tuple[str, bytes]:
    return hashlib.sha256(data).hexdigest(), data


def setUpModule():
    global SRC_DOOR, DRIVE_URL
    H.setUpModule()
    SRC_DOOR = H.Door("hp-laptop", T.BASE)
    threading.Thread(target=SRC_DOOR.serve_forever, daemon=True).start()
    targets = json.loads((T.WORK / "targets.json").read_text())
    drive = DRIVE_URL = targets["targets"]["herd-exampleu"]["url"]
    door = f"http://127.0.0.1:{SRC_DOOR.port}"
    targets["targets"].update({
        # at Exampleu: its own repository, read by the HP alone
        "client-own": {"url": drive, "connection_id": "conn-client", "folder": "/גיבויים/dgo",
                       "append_only": False, "mirror_to": "hp-laptop"},
        "client-empty": {"url": drive, "connection_id": "conn-client", "folder": "/גיבויים/empty",
                         "append_only": False, "mirror_to": "hp-laptop"},
        # at the HP: the herd's copies of them
        "herd-mirror": {"url": drive, "connection_id": "conn-herd", "folder": "/גיבויים/mirror-exampleu",
                        "append_only": True, "mirror": {"remote": door, "target": "client-own", "link": "exampleu"}},
        "herd-mirror-empty": {"url": drive, "connection_id": "conn-herd", "folder": "/גיבויים/mirror-empty",
                              "append_only": True,
                              "mirror": {"remote": door, "target": "client-empty", "link": "exampleu"}},
    })
    (T.WORK / "targets.json").write_text(json.dumps(targets, ensure_ascii=False))
    # the client's repository, written as its own backup run writes it
    own = RS.RUNS.open("client-own")
    assert T.call("POST", "/repo/client-own/?create=true", b"", own)[0] == 200
    assert T.call("POST", "/repo/client-own/config", b"config of exampleu " + secrets.token_bytes(16), own)[0] == 200
    for kind in ("keys", "data", "data", "data", "index", "snapshots"):
        put(own, kind, secrets.token_bytes(3000 if kind == "data" else 300))
    RS.RUNS.close(own[0])


def tearDownModule():
    SRC_DOOR.shutdown()
    H.tearDownModule()


def put(run, kind: str, data: bytes) -> str:
    name, data = obj(data)
    assert T.call("POST", f"/repo/client-own/{kind}/{name}", data, run)[0] == 200
    return name


def listing(folder: str, kind: str) -> dict:
    return dict(RS.list_objects(RS.Drive(DRIVE_URL, "conn-client"), folder, kind))


def pull(target: str = "herd-mirror", began=lambda: None) -> dict:
    LOG.clear()
    spec = RS.targets()[target]
    return MIRROR.pull(target, spec, "hp-laptop", LOG.append, began=began)


def open_read(door: H.Door, target: str, as_office: str, link: str):
    """POST /api/repo-runs through `door`, proved by `as_office` with the pair row for `link`."""
    secret = LP.link_secret(link)
    return H.open_run(door, target, LP.make(as_office, target, secret))


def reads_open() -> int:
    with RS.RUNS._lock:
        return sum(1 for r in RS.RUNS._runs.values() if r.get("read"))


class Pull(unittest.TestCase):
    def setUp(self):
        H.fresh_vault()

    def test_1_everything_is_copied_checked_and_a_second_pull_copies_nothing(self):
        got = pull()
        self.assertTrue(got["complete"])
        self.assertEqual(got["copied"], {"keys": 1, "data": 3, "index": 1, "snapshots": 1})
        for kind in MIRROR.ORDER:
            self.assertEqual(listing("/גיבויים/dgo", kind), listing("/גיבויים/mirror-exampleu", kind), kind)
        src = T.DRIVE.at("/גיבויים/dgo/config").read_bytes()
        self.assertEqual(T.DRIVE.at("/גיבויים/mirror-exampleu/config").read_bytes(), src)
        self.assertTrue(T.DRIVE.at("/גיבויים/mirror-exampleu/data/00").is_dir(), "the mirror has restic's layout")
        again = pull()
        self.assertEqual(again["copied"], {"keys": 0, "data": 0, "index": 0, "snapshots": 0})
        self.assertEqual(reads_open(), 0, "the reading run is closed after each pull")

    def test_2_what_the_source_adds_is_copied_and_nothing_it_removed_leaves_the_mirror(self):
        pull()
        own = RS.RUNS.open("client-own")
        try:
            new = put(own, "snapshots", b"a later night " + secrets.token_bytes(8))
            gone = next(iter(listing("/גיבויים/dgo", "index")))
            self.assertEqual(T.call("DELETE", f"/repo/client-own/index/{gone}", None, own)[0], 200)
        finally:
            RS.RUNS.close(own[0])
        got = pull()
        self.assertEqual(got["copied"]["snapshots"], 1)
        self.assertIn(new, listing("/גיבויים/mirror-exampleu", "snapshots"))
        self.assertIn(gone, listing("/גיבויים/mirror-exampleu", "index"), "a prune at the source never reaches the mirror")


class ReadRun(unittest.TestCase):
    def setUp(self):
        H.fresh_vault()

    def test_the_run_that_pulls_reads_only(self):
        st, js = open_read(SRC_DOOR, "client-own", "hp-laptop", "exampleu")
        self.assertEqual(st, 200, js)
        auth = {"Authorization": H.basic(js["user"], js["token"])}
        try:
            name, data = obj(b"planted by the reader")
            for method, path, body in (("POST", f"/repo/client-own/data/{name}", data),
                                       ("POST", f"/repo/client-own/locks/{name}", data),
                                       ("POST", "/repo/client-own/config", b"x"),
                                       ("POST", "/repo/client-own/?create=true", b""),
                                       ("DELETE", f"/repo/client-own/snapshots/{next(iter(listing('/גיבויים/dgo', 'snapshots')))}", None)):
                self.assertEqual(H.through(SRC_DOOR, method, path, auth, body)[0], 403, f"{method} {path}")
            st, rows = H.through(SRC_DOOR, "GET", "/repo/client-own/keys/", {**auth, "Accept": RS.V2})
            self.assertEqual(st, 200)
            self.assertEqual(len(rows), 1)
            self.assertEqual(H.through(SRC_DOOR, "GET", "/repo/client-own/keys/", auth)[0], 200)
            self.assertEqual(H.direct("GET", "/repo/client-own/keys/", auth)[0], 401,
                             "past the door (a container at the client) the reading run is no run")
        finally:
            H.through(SRC_DOOR, "DELETE", "/api/repo-runs", auth)

    def test_only_the_office_named_opens_it_and_a_target_not_read_by_one_opens_for_nobody(self):
        # another linked office, proving itself with its own pair: not the one named
        self.assertEqual(open_read(H.STRANGER, "client-own", "other", "other")[0], 401)
        # the HP's proof, through a door that names another office
        self.assertEqual(open_read(H.STRANGER, "client-own", "hp-laptop", "exampleu")[0], 401)
        # no proof at all
        self.assertEqual(H.open_run(SRC_DOOR, "client-own", None)[0], 401)
        # a target that is given to nobody, and the mirror itself, open for nobody
        self.assertEqual(open_read(SRC_DOOR, "herd-exampleu", "hp-laptop", "exampleu")[0], 401)
        self.assertEqual(open_read(SRC_DOOR, "herd-mirror", "hp-laptop", "exampleu")[0], 401)
        self.assertEqual(reads_open(), 0)


class WhatIsNeverWritten(unittest.TestCase):
    def setUp(self):
        H.fresh_vault()

    def test_bytes_that_are_not_their_name_are_never_written_and_nothing_after_them(self):
        pull()
        own = RS.RUNS.open("client-own")
        try:
            snap = put(own, "snapshots", b"names a bad pack " + secrets.token_bytes(8))
        finally:
            RS.RUNS.close(own[0])
        bad = hashlib.sha256(b"what the name says").hexdigest()
        planted = T.DRIVE.at(f"/גיבויים/dgo/data/{bad[:2]}/{bad}")
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_bytes(b"other bytes, of the same length....")
        try:
            with self.assertRaises(MIRROR.Failed) as said:
                pull()
            self.assertIn("is not the object its name says", str(said.exception))
            self.assertNotIn(bad, listing("/גיבויים/mirror-exampleu", "data"))
            self.assertNotIn(snap, listing("/גיבויים/mirror-exampleu", "snapshots"),
                             "a snapshot never reaches the mirror before the packs it names")
            self.assertEqual(reads_open(), 0)
        finally:
            planted.unlink()
        self.assertEqual(pull()["copied"]["snapshots"], 1, "the next pull goes on")

    def test_another_config_at_the_source_stops_the_pull_before_a_byte_is_copied(self):
        pull()
        cfg = T.DRIVE.at("/גיבויים/dgo/config")
        was = cfg.read_bytes()
        own = RS.RUNS.open("client-own")
        try:
            new = put(own, "keys", b"a key of another repository " + secrets.token_bytes(8))
        finally:
            RS.RUNS.close(own[0])
        cfg.write_bytes(b"another repository's config")
        try:
            with self.assertRaises(MIRROR.Failed) as said:
                pull()
            self.assertIn("another config", str(said.exception))
            self.assertNotIn(new, listing("/גיבויים/mirror-exampleu", "keys"))
            self.assertEqual(T.DRIVE.at("/גיבויים/mirror-exampleu/config").read_bytes(), was)
        finally:
            cfg.write_bytes(was)


class TheNight(unittest.TestCase):
    def setUp(self):
        H.fresh_vault()

    def test_a_source_with_no_repository_is_refused_and_the_night_is_not_spent(self):
        began = []
        with self.assertRaises(MIRROR.Refused) as said:
            pull("herd-mirror-empty", began=lambda: began.append(1))
        self.assertIn("no repository", str(said.exception))
        self.assertEqual(began, [])
        self.assertEqual(reads_open(), 0)

    def test_a_pull_while_the_clients_night_deletes_waits_and_is_told_why(self):
        """DGO-1517: the client's own night holds its store while it forgets/prunes; the herd's pull asked for
        meanwhile is a 503 through the door, a Refused here (the night not spent), and the store's sentence arrives."""
        began = []
        self.assertTrue(RS.RUNS.begin_delete("client-own"))
        try:
            with self.assertRaises(MIRROR.Refused) as said:
                pull(began=lambda: began.append(1))
        finally:
            RS.RUNS.end_delete("client-own")
        self.assertIn("503", str(said.exception))
        self.assertIn("forgetting/pruning", str(said.exception), "the store's own sentence survives the hops")
        self.assertEqual((began, reads_open()), ([], 0))
        self.assertTrue(pull()["complete"], "the night over, the pull goes on")

    def test_a_link_that_does_not_admit_the_pull_is_refused(self):
        H.VAULT.instances.pop("dgo_link-exampleu")
        LP.forget()
        with self.assertRaises(MIRROR.Refused):
            pull()

    def test_backup_run_pulls_a_mirror_and_never_exports_into_it(self):
        state = T.WORK / "state-mirror"
        exported = []
        got = BR.run("herd-mirror", "hp-laptop", T.WORK / "archives", state,
                     lambda staging, log: exported.append(staging), LOG.append)
        self.assertEqual(exported, [], "nothing of this office is exported into a client's mirror")
        self.assertEqual(got["mirror_of"], {"office": "exampleu", "target": "client-own"})
        self.assertEqual(BR.last(state, "herd-mirror")["mirror_of"]["office"], "exampleu")
        self.assertIsNotNone(BR._started(state, "herd-mirror"))
        empty = T.WORK / "state-mirror-empty"
        with self.assertRaises(BR.Refused):
            BR.run("herd-mirror-empty", "hp-laptop", T.WORK / "archives", empty, lambda s, log: None, LOG.append)
        self.assertIsNone(BR._started(empty, "herd-mirror-empty"), "a refused pull is tried again, not a spent night")


# ── a client's door that is not to be trusted (the second reader) ───────────────────────────────────────────────────
class Hostile(H.http.server.ThreadingHTTPServer):
    """Answers each path as `routes` says: (status, headers, body, pause between chunks, cut after n bytes)."""
    daemon_threads = True

    def __init__(self):
        self.routes: dict = {}
        self.extra: dict = {}          # path -> {"declare": a Content-Length that lies, "no_length", "head_pause"}
        self.hits: list[str] = []
        super().__init__(("127.0.0.1", T._port()), _HostileHandler)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class _HostileHandler(H.http.server.BaseHTTPRequestHandler):
    server: Hostile

    def log_message(self, *a):
        pass

    def _any(self):
        self.server.hits.append(self.path)
        status, hdrs, body, pause, cut = self.server.routes.get(self.path.split("?")[0], (404, {}, b"", 0, None))
        extra = self.server.extra.get(self.path.split("?")[0], {})
        if extra.get("chunk_trickle"):
            # HTTP/1.1, `Connection: close`, chunked — and the chunk-size line one byte at a time (the third reader)
            self.wfile.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n")
            self.wfile.flush()
            for c in b"0000000000000000000000000000000000000001":
                time.sleep(extra["chunk_trickle"])
                try:
                    self.wfile.write(bytes([c]))
                    self.wfile.flush()
                except OSError:
                    return
            return
        if extra.get("head_pause"):
            time.sleep(extra["head_pause"])               # headers that trickle: nothing sent for a while
        self.send_response(status)
        for k, v in hdrs.items():
            self.send_header(k, v)
        if not extra.get("no_length"):
            self.send_header("Content-Length", str(extra.get("declare", len(body))))
        self.end_headers()
        sent = body if cut is None else body[:cut]
        for i in range(0, len(sent), 64):
            if pause:
                time.sleep(pause)
            self.wfile.write(sent[i:i + 64])
        self.wfile.flush()

    do_GET = do_POST = do_DELETE = _any


class AHostileClient(unittest.TestCase):
    RUN = {"user": "run-0123456789abcdef", "token": "t" * 30}

    @classmethod
    def setUpClass(cls):
        cls.door, cls.inside = Hostile(), Hostile()
        for s in (cls.door, cls.inside):
            threading.Thread(target=s.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.door.shutdown()
        cls.inside.shutdown()

    def setUp(self):
        self.door.routes.clear()
        self.door.extra.clear()
        self.door.hits.clear()
        self.inside.hits.clear()

    def source(self, seconds: float = 30):
        return MIRROR._Source(self.door.url, "t", self.RUN, time.monotonic() + seconds)

    def route(self, path, status=200, body=b"", headers=None, pause=0, cut=None):
        self.door.routes[path] = (status, headers or {}, body, pause, cut)

    def test_a_redirect_is_never_followed_with_the_token_or_the_proof(self):
        self.route("/repo/t/keys/", 302, headers={"Location": f"{self.inside.url}/internal-secret"})
        self.route("/repo/t/config", 302, headers={"Location": f"{self.inside.url}/internal-config"})
        with self.assertRaises(MIRROR.Failed):
            self.source().listing("keys")
        with self.assertRaises(MIRROR.Failed):
            self.source().config()
        self.route("/api/repo-runs", 302, headers={"Location": f"{self.inside.url}/internal-runs"})
        H.fresh_vault()
        with self.assertRaises(BR.Refused):
            BR.Remote({"remote": self.door.url, "target": "t", "link": "exampleu"}, "hp-laptop").open()
        self.assertEqual(self.inside.hits, [], "nothing inside this office's network was asked")

    def test_a_listing_that_is_not_restics_is_a_failed_pull_never_a_stray_exception(self):
        good = "a" * 64
        for body in (b"[1]", b'{"name": 1}', b'[{"name": "' + good.encode() + b'", "size": true}]',
                     b'[{"name": "../../x", "size": 1}]', b'[{"name": "' + good.encode() + b'", "size": -1}]',
                     b"[" * 100_000 + b"]" * 100_000, b"not json"):
            self.route("/repo/t/keys/", body=body)
            with self.assertRaises(MIRROR.Failed, msg=body[:40]):
                self.source().listing("keys")
        self.route("/repo/t/keys/", body=b"[" + b" " * 2048 + b"]")
        old = MIRROR.LIST_MAX_BYTES
        MIRROR.LIST_MAX_BYTES = 1024
        try:
            with self.assertRaises(MIRROR.Failed) as said:
                self.source().listing("keys")
            self.assertIn("longer than", str(said.exception))
        finally:
            MIRROR.LIST_MAX_BYTES = old

    def test_an_answer_cut_short_or_too_slow_is_a_failed_pull(self):
        name, data = obj(b"x" * 1000)
        self.route(f"/repo/t/data/{name}", body=data, cut=100)
        with self.assertRaises(MIRROR.Failed):
            self.source().fetch("data", name, 1000)
        self.route("/repo/t/keys/", body=b"[]" + b" " * 4000, pause=0.2)
        t = time.monotonic()
        with self.assertRaises(MIRROR.Failed) as said:
            self.source(seconds=0.5).listing("keys")
        self.assertIn("ran past", str(said.exception))
        self.assertLess(time.monotonic() - t, 5, "a trickling answer is stopped at the deadline, not at its end")

    def test_a_config_that_is_empty_or_too_large_is_not_a_repository(self):
        self.route("/repo/t/config", body=b"")
        with self.assertRaises(MIRROR.Failed):
            self.source().config()
        self.route("/repo/t/config", body=b"c" * (MIRROR.CONFIG_MAX + 1))
        with self.assertRaises(MIRROR.Failed):
            self.source().config()

    # ── the mirror's second reader ──────────────────────────────────────────────────────────────────────────────
    def test_a_listing_or_a_config_cut_short_is_never_taken_for_a_short_one(self):
        name = "b" * 64
        whole = b'[{"name":"' + name.encode() + b'","size":10}]'
        self.route("/repo/t/data/", body=whole)
        self.door.extra["/repo/t/data/"] = {"declare": len(whole) + 400}       # the link dropped mid-answer
        with self.assertRaises(MIRROR.Failed) as said:
            self.source().listing("data")
        self.assertIn("cut short", str(said.exception))
        self.route("/repo/t/data/", body=b"[]")
        self.door.extra["/repo/t/data/"] = {"no_length": True}                 # HTTP/1.0, closed when done
        with self.assertRaises(MIRROR.Failed) as said:
            self.source().listing("data")
        self.assertIn("no known length", str(said.exception))
        self.route("/repo/t/config", body=b"half a config")
        self.door.extra["/repo/t/config"] = {"declare": 300}
        with self.assertRaises(MIRROR.Failed):
            self.source().config()

    def test_headers_that_trickle_end_at_the_deadline_for_the_pull_and_for_the_run(self):
        self.route("/repo/t/keys/", body=b"[]")
        self.door.extra["/repo/t/keys/"] = {"head_pause": 4}
        t = time.monotonic()
        with self.assertRaises(MIRROR.Failed) as said:
            self.source(seconds=0.5).listing("keys")
        self.assertIn("ran past", str(said.exception))
        self.assertLess(time.monotonic() - t, 3)
        self.route("/api/repo-runs", body=b"{}")
        self.door.extra["/api/repo-runs"] = {"head_pause": 4}
        H.fresh_vault()
        old, BR.Remote.DEADLINE = BR.Remote.DEADLINE, 0.5
        try:
            t = time.monotonic()
            with self.assertRaises(BR.Refused):
                BR.Remote({"remote": self.door.url, "target": "t", "link": "exampleu"}, "hp-laptop").open()
            self.assertLess(time.monotonic() - t, 3, "the run is asked for within its own deadline")
        finally:
            BR.Remote.DEADLINE = old

    def test_a_closed_connection_whose_chunk_line_trickles_still_ends_at_the_deadline(self):
        name = "e" * 64
        for path, call in (("/repo/t/keys/", lambda s: s.listing("keys")),
                           (f"/repo/t/data/{name}", lambda s: s.fetch("data", name, 10))):
            self.route(path, body=b"")
            self.door.extra[path] = {"chunk_trickle": 0.25}
            t = time.monotonic()
            with self.assertRaises(MIRROR.Failed):
                call(self.source(seconds=0.5))
            self.assertLess(time.monotonic() - t, 3, f"{path}: the socket is shut at the deadline")
        self.route("/api/repo-runs", body=b"")
        self.door.extra["/api/repo-runs"] = {"chunk_trickle": 0.25}
        H.fresh_vault()
        old, BR.Remote.DEADLINE = BR.Remote.DEADLINE, 0.5
        try:
            t = time.monotonic()
            with self.assertRaises(BR.Refused):
                BR.Remote({"remote": self.door.url, "target": "t", "link": "exampleu"}, "hp-laptop").open()
            self.assertLess(time.monotonic() - t, 3)
        finally:
            BR.Remote.DEADLINE = old

    def test_a_name_listed_twice_is_one_object_or_a_refusal(self):
        a, b = "a" * 64, "c" * 64
        self.assertEqual(MIRROR.parse_listing(
            f'[{{"name":"{a}","size":5}},{{"name":"{a}","size":5}},{{"name":"{b}","size":7}}]'.encode()),
            [(a, 5), (b, 7)])
        with self.assertRaises(MIRROR.Failed):
            MIRROR.parse_listing(f'[{{"name":"{a}","size":5}},{{"name":"{a}","size":6}}]'.encode())
        old = MIRROR.LIST_MAX_ROWS
        MIRROR.LIST_MAX_ROWS = 1
        try:
            with self.assertRaises(MIRROR.Failed):
                MIRROR.parse_listing(f'[{{"name":"{a}","size":5}},{{"name":"{b}","size":7}}]'.encode())
        finally:
            MIRROR.LIST_MAX_ROWS = old
        self.assertEqual(MIRROR.parse_listing(b"[ ]"), [])
        with self.assertRaises(MIRROR.Failed, msg="a size no restic object has"):
            MIRROR.parse_listing(f'[{{"name":"{a}","size":{RS.MAX_OBJECT + 1}}}]'.encode())
        for bad in (b"[,]", b'[{"name":"' + a.encode() + b'","size":5},]', b"[{}]", b"{}"):
            with self.assertRaises(MIRROR.Failed, msg=bad):
                MIRROR.parse_listing(bad)

    def test_a_run_answer_that_is_not_an_object_is_no_run(self):
        self.route("/api/repo-runs", body=b"[]")
        H.fresh_vault()
        with self.assertRaises(BR.Refused):
            BR.Remote({"remote": self.door.url, "target": "t", "link": "exampleu"}, "hp-laptop").open()


class WhileTheClientWrites(unittest.TestCase):
    def setUp(self):
        H.fresh_vault()

    def test_a_snapshot_written_during_the_pull_waits_for_the_next_one_with_its_packs(self):
        pull()
        real = MIRROR._Source.listing
        written = {}

        def listing_then_write(src, kind):
            got = real(src, kind)
            if kind == "data" and not written:
                own = RS.RUNS.open("client-own")     # the client's backup finishes right after data/ was listed
                try:
                    written["data"] = put(own, "data", b"a pack of tonight " + secrets.token_bytes(64))
                    written["snap"] = put(own, "snapshots", b"tonight, naming " + written["data"].encode())
                finally:
                    RS.RUNS.close(own[0])
            return got
        MIRROR._Source.listing = listing_then_write
        try:
            pull()
        finally:
            MIRROR._Source.listing = real
        held = listing("/גיבויים/mirror-exampleu", "snapshots")
        self.assertTrue(written["data"] in listing("/גיבויים/mirror-exampleu", "data") or written["snap"] not in held,
                        "a snapshot is never in the mirror without the pack it names")
        self.assertNotIn(written["snap"], held, "written after snapshots/ was listed: it waits for the next pull")
        got = pull()
        self.assertEqual(got["copied"]["snapshots"], 1)
        self.assertIn(written["data"], listing("/גיבויים/mirror-exampleu", "data"))

    def test_the_nights_budget_stops_the_pull_and_the_next_goes_on(self):
        pull()
        own = RS.RUNS.open("client-own")
        try:
            new = [put(own, "data", secrets.token_bytes(2000)) for _ in range(3)]
        finally:
            RS.RUNS.close(own[0])
        old = MIRROR.BUDGET
        MIRROR.BUDGET = 3000
        try:
            with self.assertRaises(MIRROR.Failed) as said:
                pull()
            self.assertIn("budget", str(said.exception))
        finally:
            MIRROR.BUDGET = old
        self.assertEqual(sum(n in listing("/גיבויים/mirror-exampleu", "data") for n in new), 1)
        self.assertEqual(pull()["copied"]["data"], 2)

    def test_the_mirrors_total_cap_stops_a_client_that_fills_it(self):
        pull()
        held = sum(sum(listing("/גיבויים/mirror-exampleu", k).values()) for k in MIRROR.ORDER)
        own = RS.RUNS.open("client-own")
        try:
            junk = [put(own, "data", secrets.token_bytes(3000)) for _ in range(2)]   # valid names, bytes nobody needs
        finally:
            RS.RUNS.close(own[0])
        old = MIRROR.MAX_TOTAL
        MIRROR.MAX_TOTAL = held + 4000
        try:
            with self.assertRaises(MIRROR.Failed) as said:
                pull()
            self.assertIn("its cap is", str(said.exception))
        finally:
            MIRROR.MAX_TOTAL = old
        self.assertEqual(sum(n in listing("/גיבויים/mirror-exampleu", "data") for n in junk), 1)


class Targets(unittest.TestCase):
    def test_a_mirror_is_its_pull_alone_and_append_only(self):
        door = {"remote": "http://door:9005", "target": "client-own", "link": "exampleu"}
        base = {"url": "http://files.example:8975", "folder": "/x", "append_only": True}
        for bad, words in (({**base, "mirror": door, "link": "exampleu"}, "given to no office"),
                           ({**base, "mirror": door, "mirror_to": "exampleu"}, "given to no office"),
                           ({**base, "append_only": False, "mirror": door}, "append-only"),
                           ({**base, "mirror": {**door, "extra": 1}}, "{remote, target, link}"),
                           ({**base, "mirror": {**door, "remote": "http://door:9005/x"}}, "with no path"),
                           ({**base, "mirror": {**door, "link": "Not An Office"}}, "office id"),
                           ({**base, "link": "exampleu", "mirror_to": "hp-laptop"}, "not also read")):
            with self.assertRaises(ValueError) as said:
                RS.check_target("t", bad)
            self.assertIn(words, str(said.exception))
        ok = RS.check_target("t", {**base, "mirror": door, "nightly_utc": "02:30"})
        self.assertEqual(ok["mirror"], door)
        self.assertEqual(RS.check_target("t", {**base, "append_only": False, "mirror_to": "hp-laptop"})["mirror_to"],
                         "hp-laptop")


if __name__ == "__main__":
    unittest.main(verbosity=2)
