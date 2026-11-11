"""test_herd_store.py — the herd store over the link, and the nightly run (DGO-1523, slice 3).

One office (Exampleu) backs up into a repository that ANOTHER office (the HP) keeps on its files app. The
two meet only through the link: Exampleu's data-management asks the HP's for a run's token at
`/api/repo-runs`, and restic talks to the HP's `/repo/<target>/`, both through the HP's link door. The
door (apps/dgo-extend/link-proxy.py, a door with no tile, DGO-945) answers only the paths its office
declared, removes what the peer wrote about which office it is, and writes `x-dgo-office` from the link.
It signs nothing for such a door, so the asking office proves itself: an HMAC with the pair's own secret,
which both ends hold in their vaults and nobody else does (link_proof.py).

Here one process plays both offices: the real app under uvicorn (test_restic_store.py), its fake drive,
one fake vault holding both ends' rows of the pair (`dgo_link-exampleu` on the HP, `dgo_link-hp-laptop` at
Exampleu, the same token, as a pairing writes them), and a fake DOOR in front of the app that does what the
real one does to a request. Then:

  - the proof: made with the pair's secret, checked once, for the office the door names and the target
    it was made for, inside its window; everything else is not a proof;
  - the store: the office a target is given to opens a run on it over the link and nobody else does;
    a run opened over the link answers only through that link; the run closes with its own token;
  - the run at Exampleu: a remote target asks the store over the link first, before any export, and
    learns there whether the repository exists (so the key is made once, and never in front of an
    existing repository); the helper gets the store's address with the run's token; the run is closed
    on every path; a store that refuses stops the run with nothing sent;
  - the nightly schedule: due once per night, catching up after a night the service was down;
  - with docker and restic: the REAL helper backs up through the door, twice, and the folder on the
    HP's drive opens with plain `restic -r`.

    # as test_backup_run.py: inside the data-management image, the docker socket, a shared network
    docker run --rm --network probe-net --name probe -e TEST_SELF_HOST=probe -e TEST_NETWORK=probe-net \\
        -e TEST_SHARED_DIR=/tmp/shared -v /tmp/shared:/tmp/shared -v /var/run/docker.sock:/var/run/docker.sock \\
        -v "$PWD":/t -w /t -v <restic binary>:/usr/local/bin/restic:ro <data-management image> \\
        python3 test_herd_store.py
"""
from __future__ import annotations

import asyncio
import base64
import datetime
import http.client  # noqa: F401  (the door's client, and a connection cut mid-answer)
import http.server
import json
import os
import pathlib
import secrets
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("DEPLOYMENT_NAME", "exampleu")

import test_restic_store as T  # noqa: E402  (the real app, its fake drive, the targets file)
import test_backup_run as BRT  # noqa: E402  (fake_export, the shared dir, docker and restic detection)

import backup_run as BR  # noqa: E402
import link_proof as LP  # noqa: E402
import restic_store as RS  # noqa: E402

UTC = datetime.timezone.utc
PAIR = "pair-" + secrets.token_urlsafe(24)       # the token a pairing sealed to both ends


# ── one vault holding both ends' rows of the pair ───────────────────────────────────────────────
class LinkVault(http.server.ThreadingHTTPServer):
    """connections' API as these modules call it: the instance list by protocol, one secret, a create."""
    daemon_threads = True

    def __init__(self):
        self.instances: dict[str, dict] = {}
        self.fail = 0
        self.posts = 0
        self.lists = 0
        super().__init__(("127.0.0.1", T._port()), _LinkVaultHandler)


class _LinkVaultHandler(http.server.BaseHTTPRequestHandler):
    server: LinkVault

    def log_message(self, *a):
        pass

    def _send(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.server.fail:
            return self._send(self.server.fail, {"error": "vault down"})
        u = urllib.parse.urlsplit(self.path)
        parts = u.path.strip("/").split("/")
        if parts == ["api", "instances"]:
            self.server.lists += 1
            proto = (urllib.parse.parse_qs(u.query).get("protocol") or [None])[0]
            rows = [{"id": i, "protocol": r["protocol"], "account_hint": r.get("account_hint", "")}
                    for i, r in self.server.instances.items() if not proto or r["protocol"] == proto]
            return self._send(200, {"instances": rows})
        if len(parts) == 4 and parts[:2] == ["api", "instances"] and parts[3] == "secret":
            rec = self.server.instances.get(parts[2])
            return self._send(200, {"secret": rec["secret"]}) if rec else self._send(404, {"error": "unknown"})
        return self._send(404, {})

    def do_POST(self):
        self.server.posts += 1
        if self.server.fail:
            return self._send(self.server.fail, {"error": "vault down"})
        b = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if b["id"] in self.server.instances:
            return self._send(409, {"error": "exists"})
        self.server.instances[b["id"]] = {"protocol": b["protocol"], "secret": b["secret"]}
        return self._send(200, {"id": b["id"]})


def pair_rows(token: str = PAIR) -> dict:
    return {
        # the HP's row for Exampleu, and Exampleu's row for the HP: one pair, one token
        "dgo_link-exampleu": {"protocol": "dgo_link", "secret": {"token": token}},
        "dgo_link-hp-laptop": {"protocol": "dgo_link", "secret": {"token": token}},
        # rows that must never be taken for those: another office whose name only starts the same, and
        # an agent's credential a linked office handed over (link-proxy.py skips those too, DGO-1127)
        "dgo_link-hp": {"protocol": "dgo_link", "secret": {"token": "the hp row, not hp-laptop"}},
        "dgo_link-serve-exampleu-hp-laptop-agent": {"protocol": "dgo_link",
                                                   "account_hint": "exampleu->hp-laptop agent",
                                                   "secret": {"token": "an agent's token"}},
        "dgo_link-other": {"protocol": "dgo_link", "secret": {"token": "another pair's token"}},
    }


# ── the serving office's link door, as link-proxy.py treats a door with no tile ─────────────────
_DROP = {"x-dgo-office", "x-dgo-identity", "x-authentik-username", "connection", "x-forwarded-for",
         "x-real-ip", "forwarded", "x-forwarded-host", "x-forwarded-proto", "content-length", "transfer-encoding"}


class Door(http.server.ThreadingHTTPServer):
    """The paths its office declared and nothing else (a door whose office declared none answers every
    path: `paths=("/",)`); the peer's `x-dgo-office`, identity and forwarding claims removed;
    `x-dgo-office: <the link's office>` written; the asker's Host kept (the door routes by it and does
    not rewrite it for a door with no tile); one request per connection."""
    daemon_threads = True

    def __init__(self, office: str, upstream: str, paths=("/repo/", "/api/repo-runs"), host="127.0.0.1"):
        self.office, self.paths = office, tuple(paths)
        self.up = urllib.parse.urlsplit(upstream)
        self.calls: list[tuple[str, str]] = []
        super().__init__((host, T._port()), _DoorHandler)

    @property
    def port(self) -> int:
        return self.server_address[1]


class _DoorHandler(http.server.BaseHTTPRequestHandler):
    server: Door

    def log_message(self, *a):
        pass

    def _say(self, status: int):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _any(self):
        target = self.path.split("?", 1)[0]
        self.server.calls.append((self.command, self.path))
        if "%" in target or not any(target == p or (p.endswith("/") and target.startswith(p))
                                    for p in self.server.paths):
            return self._say(404)
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else None
        hdrs = {k: v for k, v in self.headers.items() if k.lower() not in _DROP}
        hdrs["X-Dgo-Office"] = self.server.office
        conn = http.client.HTTPConnection(self.server.up.hostname, self.server.up.port, timeout=300)
        try:
            conn.request(self.command, self.path, body=body, headers=hdrs)
            resp = conn.getresponse()
            data = resp.read()
        finally:
            conn.close()
        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() not in ("transfer-encoding", "connection", "content-length"):
                self.send_header(k, v)
        # a HEAD's length is the object's, as the app said it; anything else, the bytes carried
        length = resp.getheader("Content-Length") if self.command == "HEAD" else str(len(data))
        self.send_header("Content-Length", length or "0")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    do_GET = do_POST = do_HEAD = do_DELETE = do_PUT = _any


VAULT: LinkVault
DOOR: Door            # the HP's door to Exampleu
STRANGER: Door        # the HP's door to another linked office
HOST_DOOR: Door | None = None   # the same door, on every interface, for the helper container


def basic(user: str, token: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()


def through(door: Door, method: str, path: str, headers=None, body=None):
    """(status, json or bytes) of one request through `door`."""
    req = urllib.request.Request(f"http://127.0.0.1:{door.port}{path}", data=body, method=method,
                                 headers=dict(headers or {}))
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    try:
        return status, json.loads(raw or b"null")
    except ValueError:
        return status, raw


def direct(method: str, path: str, headers=None, body=None):
    req = urllib.request.Request(T.BASE + path, data=body, method=method, headers=dict(headers or {}))
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def open_run(door: Door, target: str, proof: str | None):
    hdrs = {LP.HEADER: proof} if proof is not None else {}
    return through(door, "POST", f"/api/repo-runs?target={target}", hdrs, b"")


def setUpModule():
    global VAULT, DOOR, STRANGER, HOST_DOOR
    T.setUpModule()
    BR.MIN_INTERVAL = 0
    VAULT = LinkVault()
    threading.Thread(target=VAULT.serve_forever, daemon=True).start()
    BR.VAULT = LP.VAULT = f"http://127.0.0.1:{VAULT.server_address[1]}"
    DOOR = Door("exampleu", T.BASE)
    STRANGER = Door("other", T.BASE)
    for d in (DOOR, STRANGER):
        threading.Thread(target=d.serve_forever, daemon=True).start()
    drive = json.loads((T.WORK / "targets.json").read_text())["targets"]["herd-exampleu"]["url"]
    targets = json.loads((T.WORK / "targets.json").read_text())
    targets["targets"].update({
        # at the HP: one target given to Exampleu over the link, one to another office
        "link-exampleu": {"url": drive, "connection_id": "conn-herd", "folder": "/גיבויים/link-exampleu",
                        "append_only": True, "link": "exampleu"},
        "link-exampleu-2": {"url": drive, "connection_id": "conn-herd", "folder": "/גיבויים/link-exampleu-2",
                          "append_only": True, "link": "exampleu"},
        "link-other": {"url": drive, "connection_id": "conn-herd", "folder": "/גיבויים/link-other",
                       "append_only": True, "link": "other"},
        # at Exampleu: the herd store, on the HP, through its door
        "remote-herd": {"remote": f"http://127.0.0.1:{DOOR.port}", "target": "link-exampleu-2", "link": "hp-laptop"},
    })
    if BRT.DOCKER:
        HOST_DOOR = Door("exampleu", T.BASE, host="0.0.0.0")
        threading.Thread(target=HOST_DOOR.serve_forever, daemon=True).start()
        targets["targets"]["link-exampleu-real"] = {"url": drive, "connection_id": "conn-herd",
                                                  "folder": "/גיבויים/link-exampleu-real", "append_only": True,
                                                  "link": "exampleu"}
        targets["targets"]["remote-herd-real"] = {"remote": f"http://{BRT.SELF_HOST}:{HOST_DOOR.port}",
                                                  "target": "link-exampleu-real", "link": "hp-laptop"}
        BR.NETWORK = BRT.NETWORK
    (T.WORK / "targets.json").write_text(json.dumps(targets, ensure_ascii=False))


def tearDownModule():
    for d in (DOOR, STRANGER, HOST_DOOR):
        if d is not None:
            d.shutdown()
    VAULT.shutdown()
    T.tearDownModule()


def fresh_vault(**extra):
    VAULT.instances.clear()
    VAULT.instances.update(pair_rows())
    VAULT.instances.update(extra)
    VAULT.fail = 0
    VAULT.posts = 0
    LP.forget()                          # the secret cache: each test reads the vault it set up


# ── the proof ───────────────────────────────────────────────────────────────────────────────────
class Proof(unittest.TestCase):
    def setUp(self):
        fresh_vault()

    def test_a_proof_holds_once_for_its_office_target_and_window(self):
        p = LP.make("exampleu", "link-exampleu", PAIR)
        self.assertEqual(LP.verify(p, "exampleu", "link-exampleu"), "exampleu")
        with self.assertRaises(LP.NotProved):
            LP.verify(p, "exampleu", "link-exampleu")                       # the same proof twice
        now = time.time()
        for value, door, target, why in (
                (LP.make("exampleu", "link-exampleu", PAIR), "other", "link-exampleu", "the door names another office"),
                (LP.make("exampleu", "link-exampleu", PAIR), None, "link-exampleu", "no door wrote the office"),
                (LP.make("exampleu", "link-exampleu", PAIR), "exampleu", "link-other", "made for another target"),
                (LP.make("exampleu", "link-exampleu", "not the pair's"), "exampleu", "link-exampleu", "another secret"),
                (LP.make("exampleu", "link-exampleu", PAIR, now=now - LP.WINDOW - 5), "exampleu", "link-exampleu", "stale"),
                (LP.make("exampleu", "link-exampleu", PAIR, now=now + LP.WINDOW + 5), "exampleu", "link-exampleu", "future"),
        ):
            with self.assertRaises(LP.NotProved, msg=why):
                LP.verify(value, door, target)

    def test_a_name_with_no_link_is_remembered_but_the_table_is_bounded(self):
        for i in range(LP.CACHE_MAX + 40):
            self.assertEqual(LP.link_secret(f"forged-{i}"), "")
        self.assertLessEqual(len(LP._CACHE), LP.CACHE_MAX)
        asked = VAULT.lists
        LP.link_secret(f"forged-{LP.CACHE_MAX + 39}")                   # the newest is still remembered
        self.assertEqual(VAULT.lists, asked)

    def test_what_is_not_a_proof(self):
        good = LP.make("exampleu", "link-exampleu", PAIR).split(" ")
        bad = [
            "", "v1", " ".join(good[:5]),                                   # too few fields
            " ".join(["v2"] + good[1:]),                                    # another version
            " ".join(good[:1] + ["Exampleu"] + good[2:]),                     # not an office id
            " ".join(good[:3] + ["12x"] + good[4:]),                        # not a time
            " ".join(good[:4] + ["zz" * 16] + good[5:]),                    # not a nonce
            " ".join(good[:5] + [good[5].upper()]),                         # not lowercase hex
            " ".join(good) + "\n",                                          # a line break rides along
            " ".join(good) + " extra",
        ]
        for value in bad:
            with self.assertRaises(LP.NotProved, msg=repr(value)):
                LP.verify(value, "exampleu", "link-exampleu")

    def test_the_pair_row_is_found_by_its_exact_name(self):
        self.assertEqual(LP.link_secret("hp-laptop"), PAIR)
        self.assertEqual(LP.link_secret("exampleu"), PAIR)
        self.assertEqual(LP.link_secret("hp"), "the hp row, not hp-laptop")
        self.assertEqual(LP.link_secret("nobody"), "")
        LP.forget()
        del VAULT.instances["dgo_link-hp-laptop"]
        self.assertEqual(LP.link_secret("hp-laptop"), "", "the agent row or the `hp` row was taken for the pair")

    def test_a_silent_vault_is_unavailable_never_no_secret(self):
        VAULT.fail = 503
        with self.assertRaises(LP.Unavailable):
            LP.link_secret("exampleu")
        with self.assertRaises(LP.Unavailable):
            LP.verify(LP.make("exampleu", "link-exampleu", PAIR), "exampleu", "link-exampleu")


# ── the store, at the HP ────────────────────────────────────────────────────────────────────────
class StoreOverTheLink(unittest.TestCase):
    def setUp(self):
        fresh_vault()
        RS.RUNS._runs.clear()

    def test_the_linked_office_opens_a_run_on_its_own_target(self):
        st, js = open_run(DOOR, "link-exampleu", LP.make("exampleu", "link-exampleu", PAIR))
        self.assertEqual(st, 200, js)
        self.assertEqual(set(js), {"user", "token", "exists"})
        self.assertFalse(js["exists"])
        auth = {"Authorization": basic(js["user"], js["token"])}
        self.assertEqual(through(DOOR, "POST", "/repo/link-exampleu/?create=true", auth, b"")[0], 200)
        name, data = T.obj(b"a config restic would write")
        self.assertEqual(through(DOOR, "POST", "/repo/link-exampleu/config", auth, data)[0], 200)
        self.assertEqual(through(DOOR, "HEAD", "/repo/link-exampleu/config", auth)[0], 200)
        # the next run learns the repository is there, so its key is never made again
        st, js = open_run(DOOR, "link-exampleu", LP.make("exampleu", "link-exampleu", PAIR))
        self.assertEqual((st, js["exists"]), (200, True))
        # the token is never logged, kept or answered twice
        self.assertNotIn(js["token"], json.dumps({u: {k: v for k, v in r.items() if k != "digest"}
                                                  for u, r in RS.RUNS._runs.items()}, default=str))

    def test_nobody_else_opens_a_run(self):
        cases = [
            (DOOR, "link-exampleu", None, "no proof"),
            (DOOR, "link-other", LP.make("exampleu", "link-other", PAIR), "a target given to another office"),
            (DOOR, "herd-exampleu", LP.make("exampleu", "herd-exampleu", PAIR), "a target given to no link"),
            (DOOR, "remote-herd", LP.make("exampleu", "remote-herd", PAIR), "a target that is not a store here"),
            (DOOR, "nobody", LP.make("exampleu", "nobody", PAIR), "no such target"),
            (DOOR, "link-exampleu", LP.make("exampleu", "link-exampleu", "a guess"), "a secret that is not the pair's"),
            (STRANGER, "link-exampleu", LP.make("exampleu", "link-exampleu", PAIR), "through another office's door"),
            (STRANGER, "link-other", LP.make("other", "link-other", PAIR), "the other office, with Exampleu's pair"),
            (DOOR, "link-exampleu", LP.make("exampleu", "link-exampleu", PAIR, now=time.time() - 3600), "an hour old"),
        ]
        for door, target, proof, why in cases:
            st, _ = open_run(door, target, proof)
            self.assertEqual(st, 401, why)
        replay = LP.make("exampleu", "link-exampleu", PAIR)
        self.assertEqual(open_run(DOOR, "link-exampleu", replay)[0], 200)
        self.assertEqual(open_run(DOOR, "link-exampleu", replay)[0], 401, "a proof used twice")
        # past the door: nothing wrote the office, so no proof is taken
        st, _ = direct("POST", "/api/repo-runs?target=link-exampleu",
                       {LP.HEADER: LP.make("exampleu", "link-exampleu", PAIR)}, b"")
        self.assertEqual(st, 401)
        self.assertEqual(len(RS.RUNS._runs), 1, "a refused request opened a run")

    def test_the_other_office_opens_its_own(self):
        VAULT.instances["dgo_link-other"]["secret"]["token"] = "another pair's token"
        st, js = open_run(STRANGER, "link-other", LP.make("other", "link-other", "another pair's token"))
        self.assertEqual(st, 200, js)

    def test_a_silent_vault_opens_nothing_and_says_so(self):
        VAULT.fail = 503
        st, js = open_run(DOOR, "link-exampleu", LP.make("exampleu", "link-exampleu", PAIR))
        self.assertEqual(st, 503)
        self.assertEqual(RS.RUNS._runs, {})

    def test_a_run_opened_over_the_link_answers_only_through_that_link(self):
        st, js = open_run(DOOR, "link-exampleu", LP.make("exampleu", "link-exampleu", PAIR))
        auth = {"Authorization": basic(js["user"], js["token"])}
        self.assertEqual(through(DOOR, "GET", "/repo/link-exampleu/keys/", auth)[0], 200)
        self.assertEqual(through(STRANGER, "GET", "/repo/link-exampleu/keys/", auth)[0], 401)
        self.assertEqual(direct("GET", "/repo/link-exampleu/keys/", auth)[0], 401, "past the door, with the token")
        # …while a run this office opened for itself is not tied to any link
        user, token = RS.RUNS.open("herd-exampleu")
        self.assertEqual(direct("GET", "/repo/herd-exampleu/keys/", {"Authorization": basic(user, token)})[0], 200)

    def test_the_run_is_closed_with_its_own_token(self):
        st, js = open_run(DOOR, "link-exampleu", LP.make("exampleu", "link-exampleu", PAIR))
        auth = {"Authorization": basic(js["user"], js["token"])}
        self.assertEqual(through(DOOR, "DELETE", "/api/repo-runs", {"Authorization": basic(js["user"], "no")})[0],
                         401)
        self.assertEqual(through(STRANGER, "DELETE", "/api/repo-runs", auth)[0], 401)
        self.assertEqual(through(DOOR, "GET", "/repo/link-exampleu/keys/", auth)[0], 200, "a refused close closed it")
        self.assertEqual(through(DOOR, "DELETE", "/api/repo-runs", auth)[0], 200)
        self.assertEqual(through(DOOR, "GET", "/repo/link-exampleu/keys/", auth)[0], 401)

    def test_an_append_only_target_stays_so_over_the_link(self):
        st, js = open_run(DOOR, "link-exampleu", LP.make("exampleu", "link-exampleu", PAIR))
        auth = {"Authorization": basic(js["user"], js["token"])}
        through(DOOR, "POST", "/repo/link-exampleu/?create=true", auth, b"")
        name, data = T.obj(b"a snapshot Exampleu must not be able to erase")
        self.assertEqual(through(DOOR, "POST", f"/repo/link-exampleu/snapshots/{name}", auth, data)[0], 200)
        self.assertEqual(through(DOOR, "DELETE", f"/repo/link-exampleu/snapshots/{name}", auth)[0], 403)

    def test_a_target_given_to_a_link_is_append_only_and_names_an_office(self):
        u = "http://files.example:8975"
        ok = RS.check_target("t", {"url": u, "folder": "/a", "link": "exampleu"})
        self.assertEqual((ok["link"], ok["append_only"]), ("exampleu", True))
        for t in ({"url": u, "folder": "/a", "link": "exampleu", "append_only": False},
                  {"url": u, "folder": "/a", "link": "Exampleu"}, {"url": u, "folder": "/a", "link": "u"},
                  {"url": u, "folder": "/a", "link": "exampleu\n"}, {"url": u, "folder": "/a", "link": 7},
                  {"url": u, "folder": "/a", "link": "exampleu", "nightly_utc": "00:30"}):
            with self.assertRaises(ValueError, msg=repr(t)):
                RS.check_target("t", t)

    def test_this_office_never_backs_up_into_a_store_it_keeps_for_another(self):
        calls: list = []
        with self.assertRaises(BR.Refused) as c:
            BR.run("link-exampleu", "hp-laptop", BRT.SHARED, BRT.SHARED / "state-kept", BRT.fake_export({}, calls),
                   lambda s: None)
        self.assertIn("only exampleu backs up into it", str(c.exception))
        self.assertEqual((calls, VAULT.posts), ([], 0))

    def test_through_the_store_door_only_the_store_answers(self):
        # the serving office named the door and no paths: the door itself narrows nothing
        wide = Door("exampleu", T.BASE, paths=("/",))
        threading.Thread(target=wide.serve_forever, daemon=True).start()
        try:
            host = {"Host": f"backup-store.hp-laptop:{wide.port}"}
            for method, path in (("GET", "/api/inventory"), ("GET", "/api/archives"), ("GET", "/api/jobs"),
                                 ("POST", "/api/import?path=/x&force=true"), ("POST", "/api/export"),
                                 ("POST", "/api/backup?target=herd-exampleu"), ("GET", "/healthz"), ("GET", "/"),
                                 ("GET", "/api/backup/last?target=herd-exampleu"),
                                 ("GET", "/api/archives/x/download/manifest.json")):
                st, _ = through(wide, method, path, host, b"" if method == "POST" else None)
                self.assertEqual(st, 404, f"{method} {path}")
            self.assertEqual(open_run(wide, "link-exampleu", None)[0], 401)          # the store's own answer
            st, _ = through(wide, "POST", "/api/repo-runs?target=link-exampleu",
                            {**host, LP.HEADER: LP.make("exampleu", "link-exampleu", PAIR)}, b"")
            self.assertEqual(st, 200, "the store itself, through its door")
            self.assertEqual(through(wide, "GET", "/repo/link-exampleu/keys/", host)[0], 401)
            # …while the same paths under another name (a tile's door, this office's own callers) are untouched
            self.assertEqual(through(wide, "GET", "/healthz")[0], 200)
        finally:
            wide.shutdown()

    def test_data_management_offers_the_store_as_a_door_with_no_tile(self):
        man = json.loads((HERE / "app.json").read_text(encoding="utf-8"))
        doors = [c for c in man.get("capabilities") or [] if c.get("link")]
        self.assertEqual([(c["name"], c["endpoint"]) for c in doors],
                         [("backup-store", "http://data-management:8080")])


# ── the run, at Exampleu ──────────────────────────────────────────────────────────────────────────
class FakeHelper:
    """subprocess.run as backup_run calls it: the helper's `docker run` answered by a request through the
    door with the token it was given (restic's first call), and a summary line, as restic prints one."""

    def __init__(self, exit_code: int = 0):
        self.exit_code = exit_code
        self.got: list[tuple[list, str, int]] = []
        self._real = subprocess.run

    def __call__(self, argv, *a, **kw):
        if list(argv[:2]) != ["docker", "run"]:
            return self._real(argv, *a, **kw)
        repo, key = (kw.get("input") or "").splitlines()[:2]
        u = urllib.parse.urlsplit(repo[len("rest:"):])
        req = urllib.request.Request(f"{u.scheme}://{u.hostname}:{u.port}{u.path}keys/",
                                     headers={"Authorization": basic(u.username, u.password)})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                seen = r.status
        except urllib.error.HTTPError as e:
            seen = e.code
        self.got.append((list(argv), kw.get("input") or "", seen))
        out = "\n".join([json.dumps({"step": "unlock", "ok": True}),
                         json.dumps({"message_type": "summary", "snapshot_id": "cd" * 32,
                                     "total_files_processed": 2, "total_bytes_processed": 10, "data_added": 10}),
                         json.dumps({"step": "check", "ok": self.exit_code == 0, "subset": "1/7"})])
        return subprocess.CompletedProcess(argv, self.exit_code, out, "")


class RemoteRun(unittest.TestCase):
    def setUp(self):
        fresh_vault()
        RS.RUNS._runs.clear()
        self.state = BRT.SHARED / f"state-remote-{secrets.token_hex(3)}"
        self.helper = FakeHelper()
        BR.subprocess.run, self._real = self.helper, BR.subprocess.run

    def tearDown(self):
        BR.subprocess.run = self._real

    def test_a_run_to_the_herd_store_goes_through_the_link(self):
        logs: list[str] = []
        calls: list = []
        before = len(DOOR.calls)
        r = BR.run("remote-herd", "exampleu", BRT.SHARED, self.state, BRT.fake_export({"a": b"x"}, calls), logs.append,
                   weekday=1)
        self.assertEqual(r["snapshot"], "cd" * 32)
        self.assertEqual(r["target"], "remote-herd")
        self.assertEqual(len(calls), 1)
        (argv, stdin, seen), = self.helper.got
        repo = stdin.splitlines()[0]
        u = urllib.parse.urlsplit(repo[len("rest:"):])
        self.assertEqual((u.hostname, u.port, u.path), ("127.0.0.1", DOOR.port, "/repo/link-exampleu-2/"))
        self.assertEqual(seen, 200, "the token the helper got was not admitted at the store")
        self.assertNotIn(u.password, " ".join(argv))
        self.assertEqual(VAULT.posts, 1, "the key: made once, for a new repository")
        key = VAULT.instances["backup_key-exampleu"]["secret"]["key"]
        for text in logs + [json.dumps(r)]:
            self.assertNotIn(u.password, text)
            self.assertNotIn(key, text)
            self.assertNotIn(PAIR, text)
        # what crossed the door: the store asked, then a token for the helper, then the run closed
        crossed = [c for c in DOOR.calls[before:] if c[1].startswith("/api/repo-runs")]
        self.assertEqual([m for m, _ in crossed], ["POST", "DELETE", "POST", "DELETE"])
        self.assertEqual(RS.RUNS._runs, {}, "a token outlived the run")
        self.assertEqual(BR.last(self.state, "remote-herd")["snapshot"], "cd" * 32)

    def test_a_store_that_refuses_stops_the_run_before_the_export(self):
        calls: list = []
        for setup, why in (
                (lambda: VAULT.instances["dgo_link-hp-laptop"]["secret"].update(token="a stale pair"), "refused"),
                (lambda: VAULT.instances.pop("dgo_link-hp-laptop"), "no link"),
        ):
            fresh_vault()
            setup()
            with self.assertRaises(BR.Refused, msg=why) as c:
                BR.run("remote-herd", "exampleu", BRT.SHARED, self.state, BRT.fake_export({}, calls), lambda s: None)
            self.assertIn("hp-laptop", str(c.exception))
            self.assertNotIn(PAIR, str(c.exception))
        fresh_vault()
        VAULT.fail = 503
        with self.assertRaises(BR.Refused):
            BR.run("remote-herd", "exampleu", BRT.SHARED, self.state, BRT.fake_export({}, calls), lambda s: None)
        self.assertEqual((calls, self.helper.got), ([], []))
        self.assertEqual(VAULT.posts, 0, "a key was made for a run the store refused")
        self.assertEqual(RS.RUNS._runs, {})

    def test_a_store_nobody_answers_at_is_refused_by_name(self):
        targets = json.loads((T.WORK / "targets.json").read_text())
        targets["targets"]["remote-dead"] = {"remote": f"http://127.0.0.1:{T._port()}", "target": "link-exampleu",
                                             "link": "hp-laptop"}
        (T.WORK / "targets.json").write_text(json.dumps(targets, ensure_ascii=False))
        with self.assertRaises(BR.Refused) as c:
            BR.run("remote-dead", "exampleu", BRT.SHARED, self.state, BRT.fake_export({}), lambda s: None)
        self.assertIn("did not answer", str(c.exception))

    def test_an_existing_repository_is_never_given_a_new_key(self):
        st, js = open_run(DOOR, "link-exampleu-2", LP.make("exampleu", "link-exampleu-2", PAIR))
        auth = {"Authorization": basic(js["user"], js["token"])}
        through(DOOR, "POST", "/repo/link-exampleu-2/?create=true", auth, b"")
        through(DOOR, "POST", "/repo/link-exampleu-2/config", auth, b"made by a key nobody has now")
        RS.RUNS._runs.clear()
        calls: list = []
        try:
            with self.assertRaises(BR.Failed) as c:
                BR.run("remote-herd", "exampleu", BRT.SHARED, self.state, BRT.fake_export({}, calls), lambda s: None)
        finally:
            cfg = T.DRIVE.root / "גיבויים/link-exampleu-2/config"
            if cfg.exists():
                cfg.unlink()
        self.assertIn("No new key", str(c.exception))
        self.assertEqual((calls, VAULT.posts), ([], 0))
        self.assertEqual(RS.RUNS._runs, {}, "the run the question opened was left open")

    def test_the_proof_names_the_office_as_its_links_know_it(self):
        # compose calls the MacBook `local`, every link calls it `macbook`: the door writes the link's name
        calls: list = []
        saved = BR.LINK_OFFICE
        try:
            BR.LINK_OFFICE = ""
            with self.assertRaises(BR.Refused):
                BR.run("remote-herd", "local", BRT.SHARED, self.state, BRT.fake_export({}, calls), lambda s: None)
            self.assertEqual(calls, [], "the store refused the deployment's name, and nothing was exported")
            BR.LINK_OFFICE = "exampleu"
            r = BR.run("remote-herd", "local", BRT.SHARED, self.state, BRT.fake_export({"a": b"z"}, calls),
                       lambda s: None)
        finally:
            BR.LINK_OFFICE = saved
        self.assertEqual(r["store"], {"office": "hp-laptop", "target": "link-exampleu-2"})
        self.assertIn("backup_key-local", VAULT.instances, "the key and the restic host stay the office's own name")

    def test_a_close_cut_mid_answer_still_frees_the_run(self):
        real = BR.Remote._call

        def cut(self, method, headers):
            if method == "DELETE":
                raise http.client.IncompleteRead(b"")
            return real(self, method, headers)
        BR.Remote._call = cut
        try:
            BR.run("remote-herd", "exampleu", BRT.SHARED, self.state, BRT.fake_export({"a": b"q"}), lambda s: None)
        finally:
            BR.Remote._call = real
        self.assertTrue(BR._ONE.acquire(blocking=False), "the one run stayed held")
        BR._ONE.release()

    def test_a_slot_changed_during_a_run_does_not_end_it(self):
        user, token = RS.RUNS.open("herd-exampleu")
        auth = {"Authorization": basic(user, token)}
        targets = json.loads((T.WORK / "targets.json").read_text())
        saved = json.dumps(targets, ensure_ascii=False)
        try:
            self.assertEqual(direct("GET", "/repo/herd-exampleu/keys/", auth)[0], 200)
            targets["targets"]["herd-exampleu"]["nightly_utc"] = "02:45"          # the owner moves the night's time
            (T.WORK / "targets.json").write_text(json.dumps(targets, ensure_ascii=False))
            self.assertEqual(direct("GET", "/repo/herd-exampleu/keys/", auth)[0], 200, "a long first backup ended")
            targets["targets"]["herd-exampleu"]["folder"] = "/גיבויים/moved"       # …but where it goes is the run's
            (T.WORK / "targets.json").write_text(json.dumps(targets, ensure_ascii=False))
            self.assertEqual(direct("GET", "/repo/herd-exampleu/keys/", auth)[0], 401, "moved: that run is over")
        finally:
            (T.WORK / "targets.json").write_text(saved)
            RS.RUNS.close(user)

    def test_the_remote_run_is_closed_when_restic_fails(self):
        self.helper.exit_code = 1
        with self.assertRaises(BR.Failed):
            BR.run("remote-herd", "exampleu", BRT.SHARED, self.state, BRT.fake_export({"a": b"y"}), lambda s: None)
        self.assertEqual(RS.RUNS._runs, {})

    def test_a_remote_target_is_not_served_here(self):
        with self.assertRaises(KeyError):
            RS.RUNS.open("remote-herd")
        self.assertEqual(direct("GET", "/repo/remote-herd/keys/", {"Authorization": basic("run-x", "y")})[0], 401)

    def test_a_remote_target_is_checked(self):
        ok = RS.check_target("r", {"remote": "https://backup-store.hp-laptop:9443/", "target": "herd-exampleu",
                                   "link": "hp-laptop"})
        self.assertEqual(ok, {"remote": "https://backup-store.hp-laptop:9443", "target": "herd-exampleu",
                              "link": "hp-laptop"})
        for t in ({"remote": "http://u:p@h:1", "target": "t", "link": "hp-laptop"},
                  {"remote": "http://h:1/some/path", "target": "t", "link": "hp-laptop"},
                  {"remote": "ftp://h:1", "target": "t", "link": "hp-laptop"},
                  {"remote": "http://h:1", "target": "T", "link": "hp-laptop"},
                  {"remote": "http://h:1", "target": "t"},
                  {"remote": "http://h:1", "target": "t", "link": "hp-laptop", "folder": "/a"}):
            with self.assertRaises(ValueError, msg=repr(t)):
                RS.check_target("r", t)


# ── the nightly schedule ────────────────────────────────────────────────────────────────────────
def at(day: int, hh: int, mm: int, ss: int = 0) -> datetime.datetime:
    return datetime.datetime(2026, 11, day, hh, mm, ss, tzinfo=UTC)


class Nightly(unittest.TestCase):
    def test_due_once_a_night_and_after_a_night_missed(self):
        ts = lambda d: d.timestamp()                                    # noqa: E731
        cases = [
            ("00:30", None, at(10, 0, 31), True, "never run: due at once"),
            ("00:30", ts(at(9, 23, 0)), at(10, 0, 31), True, "the night's slot passed since the last start"),
            ("00:30", ts(at(10, 0, 30, 5)), at(10, 0, 45), False, "started in tonight's slot"),
            ("00:30", ts(at(9, 0, 31)), at(10, 0, 29), False, "tonight's slot has not come"),
            ("00:30", ts(at(7, 0, 31)), at(10, 0, 29), True, "a night missed while the service was down"),
            ("23:50", ts(at(9, 23, 55)), at(10, 23, 49), False, "a late slot, the day before it"),
            ("23:50", ts(at(9, 23, 55)), at(10, 23, 51), True, "a late slot, reached"),
        ]
        for slot, last, now, want, why in cases:
            self.assertIs(BR.due(slot, last, now), want, why)

    def test_the_schedule_starts_with_the_service(self):
        # the tests serve the app with lifespan off: what starts the loop is asserted to be wired
        self.assertIn(T.APP._start_schedule, T.APP.app.router.on_startup)

    def test_a_slot_is_a_time_of_day(self):
        u = "http://files.example:8975"
        self.assertEqual(RS.check_target("t", {"url": u, "folder": "/a", "nightly_utc": "00:30"})["nightly_utc"],
                         "00:30")
        self.assertNotIn("nightly_utc", RS.check_target("t", {"url": u, "folder": "/a"}))
        for bad in ("24:00", "0:30", "00:60", "00:30\n", "night", 30):
            with self.assertRaises(ValueError, msg=repr(bad)):
                RS.check_target("t", {"url": u, "folder": "/a", "nightly_utc": bad})

    def test_the_tick_starts_one_due_target_at_a_time_and_none_beside_another_job(self):
        targets = json.loads((T.WORK / "targets.json").read_text())
        saved = json.dumps(targets, ensure_ascii=False)
        targets["targets"]["remote-herd"]["nightly_utc"] = "00:30"
        targets["targets"]["herd-exampleu"]["nightly_utc"] = "03:00"
        (T.WORK / "targets.json").write_text(json.dumps(targets, ensure_ascii=False))
        state = BRT.SHARED / f"state-tick-{secrets.token_hex(3)}"
        state.mkdir(parents=True)
        started: list[str] = []
        tick = lambda now: asyncio.run(T.APP.schedule_tick(now, start=started.append))   # noqa: E731
        began = lambda tid, when: (state / f"last-start-{tid}").write_text(str(when.timestamp()))  # noqa: E731
        saved_dir, T.APP.STATE_DIR = T.APP.STATE_DIR, state
        saved_spread, BR.NIGHTLY_SPREAD = BR.NIGHTLY_SPREAD, 0     # the slot rule alone (the spread: its own test)
        T.APP.SCHEDULE_TRIED.clear()
        try:
            # never beside an export, a restore or another backup: each would read a half office or
            # double the load (a second backup would only be refused by the one-run lock)
            for kind in ("import", "export", "backup"):
                T.APP.JOBS["busy"] = {"id": "busy", "kind": kind, "state": "running", "log": []}
                self.assertEqual((tick(at(10, 4, 0)), started), ([], []), kind)
                del T.APP.JOBS["busy"]
            self.assertEqual(tick(at(10, 4, 0)), ["herd-exampleu"])
            self.assertEqual(tick(at(10, 4, 1)), ["remote-herd"])
            # a start that did not become a run (refused: the store unreachable, no room) is tried again
            # within the night, but not every minute
            self.assertEqual(tick(at(10, 4, 2)), [])
            self.assertEqual(tick(at(10, 5, 1)), ["herd-exampleu"])
            # a run started tonight is not started again tonight — and is, the next night
            began("remote-herd", at(10, 4, 30))
            began("herd-exampleu", at(10, 5, 2))
            T.APP.SCHEDULE_TRIED.clear()
            started.clear()
            self.assertEqual(tick(at(10, 23, 59)), [])
            self.assertEqual(started, [])
            self.assertEqual(tick(at(11, 0, 31)), ["remote-herd"])
            self.assertEqual(tick(at(11, 0, 32)), [], "herd-exampleu's slot is 03:00")
            self.assertEqual(tick(at(11, 3, 1)), ["herd-exampleu"])
        finally:
            T.APP.STATE_DIR = saved_dir
            BR.NIGHTLY_SPREAD = saved_spread
            T.APP.JOBS.pop("busy", None)
            T.APP.SCHEDULE_TRIED.clear()
            (T.WORK / "targets.json").write_text(saved)

    def test_a_scheduled_job_says_who_started_it(self):
        async def go():
            T.APP.SCHEDULE_TRIED.clear()
            job = T.APP.start_backup_job("nobody", by="schedule")
            for _ in range(200):
                if T.APP.JOBS[job]["state"] not in ("starting", "running"):
                    break
                await asyncio.sleep(0.05)
            return T.APP.JOBS[job]
        js = asyncio.run(go())
        self.assertEqual((js["by"], js["state"]), ("schedule", "skipped"))


# ── DGO-1517: what a night keeps, when it starts, and a night that did not happen ───────────────
def _helper(keep: str, forget_rc: int = 0, check_rc: int = 0) -> tuple[int, list[list[str]], list[dict]]:
    """The REAL helper script, run by /bin/sh with a fake `restic` that records each call: (exit, calls, steps)."""
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp(prefix="helper-"))
    (d / "k").mkdir()
    (d / "bin").mkdir()
    log = d / "calls"
    # each argument as restic gets it, one per line between a start and an end mark: `--keep-daily 7` as ONE
    # argument, or an empty one, would show (the reader)
    (d / "bin" / "restic").write_text(
        "#!/bin/sh\n"
        f'{{ echo "<<"; for a in "$@"; do printf "[%s]\\n" "$a"; done; echo ">>"; }} >> "{log}"\n'
        'case " $* " in\n'
        f'  *" forget "*) exit {forget_rc} ;;\n'
        f'  *" check "*) exit {check_rc} ;;\n'
        '  *" backup "*) echo \'{"message_type":"summary","snapshot_id":"abc"}\' ;;\n'
        "esac\nexit 0\n")
    (d / "bin" / "restic").chmod(0o755)
    script = BR.HELPER.replace("/run/k", str(d / "k"))
    argv = BR.helper_argv("n", pathlib.Path("/s"), "exampleu", "r1", "7/7", keep)
    tail = argv[argv.index("restic-run") + 1:]                 # what the script gets as $1…$5
    p = subprocess.run(["/bin/sh", "-c", script, "restic-run", *tail], input="rest:http://u:t@h/repo/x/\nkey\n",
                       capture_output=True, text=True, timeout=60,
                       env={"PATH": f"{d / 'bin'}:/usr/bin:/bin"})
    calls: list[list[str]] = []
    for line in (log.read_text().splitlines() if log.exists() else []):
        if line == "<<":
            calls.append([])
        elif line != ">>":
            calls[-1].append(line[1:-1])
    return p.returncode, calls, BR._parse(p.stdout)["steps"]


class Retention(unittest.TestCase):
    def test_only_a_target_that_may_delete_forgets_and_it_prunes_on_its_day(self):
        local = {"url": "http://files:8975", "folder": "/a"}
        self.assertEqual(BR.retention({**local, "append_only": True}, 3), "none")
        self.assertEqual(BR.retention(local, 3), "none", "append-only unless it says otherwise")
        self.assertEqual(BR.retention({**local, "append_only": False}, 3), "forget")
        self.assertEqual(BR.retention({**local, "append_only": False}, BR.PRUNE_DAY), "prune")
        self.assertEqual(BR.retention({"remote": "http://hp", "target": "t", "link": "hp", "append_only": False}, 7),
                         "none", "a store on another office is never asked to delete")
        self.assertEqual(BR.retention({**local, "append_only": False, "mirror": {"remote": "x"}}, 7), "none")
        may, now = {**local, "append_only": False}, 1_800_000_000.0
        self.assertEqual(BR.retention(may, 3, now - BR.PRUNE_OVERDUE, now), "prune", "a prune missed on its day")
        self.assertEqual(BR.retention(may, 3, now - BR.PRUNE_OVERDUE + 60, now), "forget")
        self.assertEqual(BR.retention(may, 3, None, now), "forget", "no prune recorded: its day, as before")
        self.assertEqual(BR.retention({**local, "append_only": True}, 3, now - 99 * 86400, now), "none")
        with self.assertRaises(ValueError):
            BR.helper_argv("n", pathlib.Path("/s"), "o", "r", "1/7", "all")

    def test_a_reading_run_is_seen_while_it_is_open(self):
        runs, t = RS.Runs(), "herd-exampleu"
        self.assertFalse(runs.reading(t))
        u, _ = runs.open(t)                                     # a run that writes is not a pull
        self.assertFalse(runs.reading(t))
        r, _ = runs.open(t, read=True)
        self.assertTrue(runs.reading(t))
        self.assertFalse(runs.reading("remote-herd"))
        runs.close(r)
        self.assertFalse(runs.reading(t))
        runs.close(u)

    def test_a_pull_that_went_quiet_past_its_idle_time_is_no_pull(self):
        clock = [1000.0]
        runs, t = RS.Runs(clock=lambda: clock[0]), "herd-exampleu"
        runs.open(t, idle=60, read=True)
        self.assertTrue(runs.reading(t))
        self.assertFalse(runs.begin_delete(t), "a night may not delete under an open pull")
        clock[0] += 61
        self.assertFalse(runs.reading(t), "an idle pull past its time")
        self.assertTrue(runs.begin_delete(t))
        with self.assertRaises(RS.Busy):
            runs.open(t, read=True)
        runs.open(t)                                            # a run that writes is not held up
        runs.end_delete(t)
        runs.open(t, read=True)                                 # the night's mark is gone with it

    def test_the_helper_forgets_7_4_6_of_this_office_alone_before_the_check(self):
        rc, calls, steps = _helper("forget")
        self.assertEqual(rc, 0)
        verbs = [next(w for w in c if not w.startswith("-")) for c in calls]
        self.assertEqual(verbs, ["cat", "unlock", "backup", "forget", "check"], "forget comes before the check")
        # exactly these arguments, each its own: this office alone, grouped by host and path (never by tags, which
        # carry each run's own id), the policy split into flag and number, and no empty argument
        self.assertEqual(calls[verbs.index("forget")],
                         ["--no-cache", "-q", "forget", "--host", "exampleu", "--group-by", "host,paths",
                          "--keep-daily", "7", "--keep-weekly", "4", "--keep-monthly", "6"])
        self.assertIn({"step": "forget", "ok": True, "prune": False}, steps)

    def test_the_prune_night_prunes_and_an_append_only_night_forgets_nothing(self):
        rc, calls, steps = _helper("prune")
        self.assertEqual(rc, 0)
        self.assertEqual(next(c for c in calls if "forget" in c)[-7:],
                         ["--keep-daily", "7", "--keep-weekly", "4", "--keep-monthly", "6", "--prune"])
        self.assertIn({"step": "forget", "ok": True, "prune": True}, steps)
        rc, calls, steps = _helper("none")
        self.assertEqual(rc, 0)
        self.assertFalse([c for c in calls if "forget" in c])
        self.assertFalse([s for s in steps if s["step"] == "forget"])

    def test_a_forget_that_failed_fails_the_night_even_when_the_check_passed(self):
        rc, calls, steps = _helper("forget", forget_rc=1)
        self.assertEqual(rc, 21)
        self.assertIn({"step": "forget", "ok": False, "prune": False}, steps)
        self.assertTrue([c for c in calls if "check" in c], "the check still reads the repository")
        rc, _, _ = _helper("forget", forget_rc=1, check_rc=3)
        self.assertEqual(rc, 3, "a failed check says so itself")


class RetentionInTheRun(unittest.TestCase):
    """The REAL run() hands the night's retention to the helper, and holds the store against a pull for the helper's
    whole run (the reader: two mutations of run() passed every suite; a pull opened mid-night was not seen)."""

    def setUp(self):
        fresh_vault()
        RS.RUNS._runs.clear()
        RS.RUNS._deleting.clear()
        self.state = BRT.SHARED / f"state-ret-{secrets.token_hex(3)}"
        self.saved = (T.WORK / "targets.json").read_text()
        targets = json.loads(self.saved)
        drive = targets["targets"]["herd-exampleu"]["url"]
        for tid, append_only in (("own-delete", False), ("own-keep", True)):
            targets["targets"][tid] = {"url": drive, "connection_id": "conn-herd", "folder": f"/גיבויים/{tid}",
                                       "append_only": append_only}
        (T.WORK / "targets.json").write_text(json.dumps(targets, ensure_ascii=False))
        self.argv: list[list[str]] = []
        self.during = None
        real = subprocess.run

        def helper(argv, *a, **kw):
            if list(argv[:2]) != ["docker", "run"]:
                return real(argv, *a, **kw)
            self.argv.append(list(argv))
            if self.during:
                self.during()
            out = "\n".join([json.dumps({"message_type": "summary", "snapshot_id": "ef" * 32,
                                         "total_files_processed": 1, "total_bytes_processed": 1, "data_added": 1}),
                             json.dumps({"step": "check", "ok": True, "subset": "1/7"})])
            return subprocess.CompletedProcess(argv, 0, out, "")
        BR.subprocess.run, self._real = helper, real

    def tearDown(self):
        BR.subprocess.run = self._real
        (T.WORK / "targets.json").write_text(self.saved)
        RS.RUNS._runs.clear()
        RS.RUNS._deleting.clear()

    def night(self, target, weekday):
        r = BR.run(target, "exampleu", BRT.SHARED, self.state, BRT.fake_export({"a": b"x"}), lambda s: None,
                   weekday=weekday)
        return r, self.argv[-1][-2:]                        # the helper's $4 and $5

    def test_a_target_that_may_delete_forgets_every_night_and_prunes_on_its_day(self):
        r, tail = self.night("own-delete", 3)
        self.assertEqual(tail, ["forget", BR.keep_flags()])
        self.assertEqual(r["retention"], "7/4/6 forgotten")
        self.assertEqual(r["pruned"], r["finished"], "the first night starts the prune's clock (never pruned is late too)")
        r, tail = self.night("own-delete", BR.PRUNE_DAY)
        self.assertEqual(tail, ["prune", BR.keep_flags()])
        self.assertTrue(r["pruned"], "the prune is recorded")
        pruned = r["pruned"]
        r, tail = self.night("own-delete", 3)
        self.assertEqual(r["pruned"], pruned, "…and carried to the next night's result")
        self.assertEqual(tail[0], "forget")
        self.assertEqual(RS.RUNS._deleting, {}, "the night's mark outlived it")

    def test_an_append_only_target_keeps_every_snapshot(self):
        r, tail = self.night("own-keep", BR.PRUNE_DAY)
        self.assertEqual(tail[0], "none")
        self.assertEqual(r["retention"], "every snapshot kept (append-only)")
        self.assertIsNone(r["pruned"], "a store that keeps everything has no prune to be late")

    def test_a_pull_open_when_the_night_starts_means_nothing_is_deleted(self):
        user, _ = RS.RUNS.open("own-delete", read=True)
        r, tail = self.night("own-delete", BR.PRUNE_DAY)
        self.assertEqual(tail[0], "none")
        self.assertIn("another office was pulling", r["retention"])
        RS.RUNS.close(user)

    def test_a_pull_that_asks_while_the_night_deletes_waits_for_it(self):
        asked: list = []

        def pull():
            try:
                RS.RUNS.open("own-delete", read=True)
                asked.append("opened")
            except RS.Busy:
                asked.append("busy")
        self.during = pull
        _, tail = self.night("own-delete", BR.PRUNE_DAY)
        self.assertEqual((tail[0], asked), ("prune", ["busy"]))
        user, _ = RS.RUNS.open("own-delete", read=True)       # the night is over: the pull goes on
        RS.RUNS.close(user)
        self.during, asked[:] = pull, []
        self.night("own-keep", BR.PRUNE_DAY)                  # a night that deletes nothing holds nothing
        self.assertEqual(asked, ["opened"])

    def test_a_prune_missed_on_its_day_is_done_the_next_night_and_a_late_one_is_said(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        for days, want in ((BR.PRUNE_OVERDUE / 86400 + 1, "prune"), (3, "forget")):
            BR._keep(self.state, "own-delete", {"snapshot": "x", "finished": now.isoformat(),
                                                "pruned": (now - datetime.timedelta(days=days)).isoformat()})
            _, tail = self.night("own-delete", 3)
            self.assertEqual(tail[0], want, f"last prune {days} days ago")
        BR._keep(self.state, "own-delete", {"snapshot": "x", "finished": now.isoformat(), "pruned": "not a time"})
        r, _ = self.night("own-delete", 3)
        self.assertNotEqual(r["pruned"], "not a time", "a carried value that does not read is a new baseline")
        self.assertEqual(r["pruned"], r["finished"])
        BR._keep(self.state, "own-delete", {"snapshot": "x", "finished": now.isoformat(),
                                            "pruned": (now - datetime.timedelta(days=20)).isoformat()})
        user, _ = RS.RUNS.open("own-delete", read=True)
        r, tail = self.night("own-delete", 3)
        RS.RUNS.close(user)
        self.assertEqual(tail[0], "none")
        self.assertIn("NOT PRUNED since", r["retention"])


class Spread(unittest.TestCase):
    def test_each_target_starts_at_its_slot_plus_its_own_spread_the_same_every_night(self):
        a, b = BR.spread("exampleu", "herd-exampleu"), BR.spread("exampleu", "remote-herd")
        self.assertEqual(a, BR.spread("exampleu", "herd-exampleu"))
        self.assertTrue(0 <= a < BR.NIGHTLY_SPREAD and 0 <= b < BR.NIGHTLY_SPREAD)
        self.assertNotEqual({BR.spread(f"office-{i}", "herd") for i in range(20)}, {a}, "offices are spread")
        saved, BR.NIGHTLY_SPREAD = BR.NIGHTLY_SPREAD, 0
        try:
            self.assertEqual(BR.spread("exampleu", "herd-exampleu"), 0)
        finally:
            BR.NIGHTLY_SPREAD = saved

    def test_due_counts_the_spread_and_a_slot_it_carries_past_midnight(self):
        ts = lambda d: d.timestamp()                                    # noqa: E731
        cases = [
            ("03:00", 1200, ts(at(9, 3, 30)), at(10, 3, 10), False, "03:20 has not come"),
            ("03:00", 1200, ts(at(9, 3, 30)), at(10, 3, 21), True, "03:20 reached"),
            ("23:50", 1800, ts(at(9, 0, 25)), at(10, 0, 10), False, "tonight's 00:20 has not come"),
            ("23:50", 1800, ts(at(9, 0, 25)), at(10, 0, 21), True, "carried past midnight, reached"),
            ("23:50", 1800, ts(at(10, 0, 21)), at(10, 23, 55), False, "the day's start was its night"),
            # the first night after this deploy: last night started at the bare slot, under the rule before the
            # spread — that was its night, not a reason for an extra run in the middle of the day (the reader)
            ("03:00", 2931, ts(at(10, 3, 0, 40)), at(10, 9, 0), False, "no daytime run after the deploy"),
            ("03:00", 2931, ts(at(10, 3, 0, 40)), at(10, 23, 0), False, "…nor late in the day"),
            ("03:00", 2931, ts(at(10, 3, 0, 40)), at(11, 3, 48, 52), True, "the next night, at its spread"),
            ("03:00", 2931, ts(at(11, 3, 10)), at(11, 3, 49), False, "a run by hand after the slot is the night's"),
        ]
        for slot, off, last, now, want, why in cases:
            self.assertIs(BR.due(slot, last, now, off), want, why)

    def test_the_tick_waits_for_the_spread(self):
        targets = json.loads((T.WORK / "targets.json").read_text())
        saved = json.dumps(targets, ensure_ascii=False)
        only = {"herd-exampleu": {**targets["targets"]["herd-exampleu"], "nightly_utc": "03:00"}}
        (T.WORK / "targets.json").write_text(json.dumps({"targets": only}, ensure_ascii=False))
        state = BRT.SHARED / f"state-spread-{secrets.token_hex(3)}"
        state.mkdir(parents=True)
        (state / "last-start-herd-exampleu").write_text(str(at(9, 4, 0).timestamp()))
        started: list[str] = []
        tick = lambda now: asyncio.run(T.APP.schedule_tick(now, start=started.append))   # noqa: E731
        saved_dir, T.APP.STATE_DIR = T.APP.STATE_DIR, state
        saved_spread, BR.NIGHTLY_SPREAD = BR.NIGHTLY_SPREAD, 3600
        T.APP.SCHEDULE_TRIED.clear()
        try:
            off = BR.spread(BR.LINK_OFFICE or T.APP.INV.deployment_name(), "herd-exampleu")
            self.assertGreater(off, 61, "a fixture whose spread is a minute or less proves nothing here")
            slot = at(10, 3, 0) + datetime.timedelta(seconds=off)
            self.assertEqual(tick(slot - datetime.timedelta(seconds=60)), [])
            self.assertEqual(tick(slot + datetime.timedelta(seconds=1)), ["herd-exampleu"])
        finally:
            T.APP.STATE_DIR = saved_dir
            BR.NIGHTLY_SPREAD = saved_spread
            T.APP.SCHEDULE_TRIED.clear()
            (T.WORK / "targets.json").write_text(saved)


class Stale(unittest.TestCase):
    """A scheduled target with no good run for 26 h is told once; its return is told; a restart tells nothing twice."""

    def setUp(self):
        self.targets_saved = (T.WORK / "targets.json").read_text()
        targets = json.loads(self.targets_saved)
        t = targets["targets"]
        t["herd-exampleu"]["nightly_utc"] = "03:00"
        t.get("remote-herd", {}).pop("nightly_utc", None)
        (T.WORK / "targets.json").write_text(json.dumps(targets, ensure_ascii=False))
        self.state = BRT.SHARED / f"state-stale-{secrets.token_hex(3)}"
        self.state.mkdir(parents=True)
        self.saved_dir, T.APP.STATE_DIR = T.APP.STATE_DIR, self.state
        self.sent: list[tuple[str, str]] = []
        self.deliver = True

    def tearDown(self):
        T.APP.STATE_DIR = self.saved_dir
        (T.WORK / "targets.json").write_text(self.targets_saved)

    def notify(self, sid, title, body, level):
        self.sent.append((sid, level))
        return self.deliver

    def tell(self, when):
        return T.APP.tell_stale(when, notify=self.notify)

    def good(self, when):
        BR._keep(self.state, "herd-exampleu", {"snapshot": "s", "finished": when.isoformat()})

    def test_a_target_never_run_is_told_26_hours_after_it_was_first_seen_once(self):
        self.assertEqual(self.tell(at(10, 4, 0)), [])
        self.assertEqual(self.tell(at(11, 5, 59)), [], "25 h 59 min")
        told = self.tell(at(11, 6, 1))
        self.assertEqual(len(told), 1)
        self.assertEqual(self.sent[-1][1], "error", "a backup that stopped rings (push.py's PUSH_LEVELS)")
        self.assertEqual(self.tell(at(11, 7, 0)), [], "once per outage")
        # a restart: the clock is in the state file, so nothing is told twice and nothing is forgotten
        self.assertTrue((self.state / T.APP.STALE_FILE).exists())
        self.assertEqual(self.tell(at(12, 7, 0)), [])
        self.good(at(12, 8, 0))
        back = self.tell(at(12, 8, 1))
        self.assertEqual((len(back), self.sent[-1][1]), (1, "info"), "its return is told")
        self.assertEqual(self.sent[-1][0], self.sent[-2][0], "on the outage's own row (one source id)")
        self.assertEqual(self.tell(at(12, 9, 0)), [])
        self.assertEqual(len(self.sent), 2)

    def test_a_targets_file_that_does_not_read_is_told_once_and_its_return_on_the_same_row(self):
        self.assertEqual(self.tell(at(10, 4, 0)), [])
        good = (T.WORK / "targets.json").read_text()
        (T.WORK / "targets.json").write_text(good[:-3])        # a cut file: no night starts at all
        self.assertEqual(self.tell(at(10, 4, 1)), [T.APP._TARGETS_SID])
        self.assertEqual(self.sent[-1], (T.APP._TARGETS_SID, "error"))
        self.assertEqual(self.tell(at(10, 5, 0)), [], "once")
        (T.WORK / "targets.json").write_text(good)
        self.assertEqual(self.tell(at(10, 5, 1)), [T.APP._TARGETS_SID])
        self.assertEqual(self.sent[-1], (T.APP._TARGETS_SID, "info"))
        self.assertNotIn(T.APP._TARGETS_KEY, json.loads((self.state / T.APP.STALE_FILE).read_text()))
        self.assertEqual(len(self.tell(at(11, 6, 1))), 1, "the targets' own clock went on meanwhile")

    def test_a_store_not_pruned_for_two_weeks_is_told_once_and_its_end_on_the_same_row(self):
        targets = json.loads((T.WORK / "targets.json").read_text())
        targets["targets"]["herd-exampleu"]["append_only"] = False         # a store this office prunes
        (T.WORK / "targets.json").write_text(json.dumps(targets, ensure_ascii=False))
        now = at(20, 4, 0)
        late = now - datetime.timedelta(days=15)
        BR._keep(self.state, "herd-exampleu", {"snapshot": "s", "finished": at(20, 3, 30).isoformat(),
                                             "pruned": late.isoformat()})
        told = self.tell(now)
        sid = f"backup-prune-late-herd-exampleu-{int(late.timestamp())}"
        self.assertEqual((told, self.sent[-1]), ([sid], (sid, "warning")))
        self.assertEqual(self.tell(now + datetime.timedelta(hours=2)), [], "once")
        BR._keep(self.state, "herd-exampleu", {"snapshot": "s", "finished": at(20, 7, 0).isoformat(),
                                             "pruned": at(20, 7, 0).isoformat()})
        self.assertEqual(self.tell(at(20, 7, 30)), [sid])
        self.assertEqual(self.sent[-1], (sid, "info"), "its end, on the same row")
        self.assertNotIn("~prune-herd-exampleu", json.loads((self.state / T.APP.STALE_FILE).read_text()))

    def test_a_record_that_is_not_an_object_or_is_gone_never_stops_the_notices_nor_gives_an_all_clear(self):
        targets = json.loads((T.WORK / "targets.json").read_text())
        targets["targets"]["herd-exampleu"]["append_only"] = False
        (T.WORK / "targets.json").write_text(json.dumps(targets, ensure_ascii=False))
        late = at(20, 4, 0) - datetime.timedelta(days=15)
        BR._keep(self.state, "herd-exampleu", {"snapshot": "s", "finished": at(20, 3, 30).isoformat(),
                                             "pruned": late.isoformat()})
        self.assertEqual(len(self.tell(at(20, 4, 0))), 1)
        record = next(self.state.glob("last-*herd-exampleu*"))
        record.write_text('"not an object"')               # valid JSON, not a record
        self.assertEqual(self.tell(at(20, 5, 0)), [], "no all-clear without a prune")
        self.assertIn("~prune-herd-exampleu", json.loads((self.state / T.APP.STALE_FILE).read_text()))
        record.unlink()                                    # gone: still no all-clear, and the stale clock runs on
        self.assertEqual(self.tell(at(20, 6, 0)), [])
        told = self.tell(at(21, 7, 1))          # 26 h after the record stopped reading (20 05:00, its clock began then)
        self.assertEqual(len(told), 1, f"the stale notice still goes: {told}")
        self.assertTrue(told[0].startswith("backup-stale-herd-exampleu-"))

    def test_an_append_only_store_is_never_told_about_pruning(self):
        BR._keep(self.state, "herd-exampleu", {"snapshot": "s", "finished": at(20, 3, 30).isoformat(),
                                             "pruned": at(1, 3, 0).isoformat()})
        self.assertEqual(self.tell(at(20, 4, 0)), [])

    def test_a_time_that_is_not_a_finite_number_starts_the_clock_again(self):
        (self.state / T.APP.STALE_FILE).write_text('{"herd-exampleu": {"since": NaN, "tried": Infinity, "told": true}}')
        self.assertEqual(self.tell(at(10, 4, 0)), [])
        self.assertEqual(len(self.tell(at(11, 6, 1))), 1)

    def test_a_good_run_older_than_26_hours_is_told_and_a_fresh_one_is_not(self):
        self.good(at(10, 3, 30))
        self.assertEqual(self.tell(at(11, 5, 0)), [], "25 h 30 min")
        self.assertEqual(len(self.tell(at(11, 5, 31))), 1)
        self.assertIn("backup-stale-herd-exampleu-", self.sent[-1][0])

    def test_a_notice_not_delivered_is_tried_again_later_not_every_minute(self):
        self.good(at(10, 3, 0))
        self.deliver = False
        self.assertEqual(self.tell(at(11, 6, 0)), [])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.tell(at(11, 6, 5)), [])
        self.assertEqual(len(self.sent), 1, "not before STALE_RETRY")
        self.deliver = True
        self.assertEqual(len(self.tell(at(11, 6, 11))), 1)
        self.assertEqual(len(self.sent), 2)

    def test_a_target_not_scheduled_is_never_told(self):
        targets = json.loads((T.WORK / "targets.json").read_text())
        targets["targets"]["herd-exampleu"].pop("nightly_utc")
        (T.WORK / "targets.json").write_text(json.dumps(targets, ensure_ascii=False))
        self.assertEqual(self.tell(at(10, 4, 0)), [])
        self.assertEqual(self.tell(at(13, 4, 0)), [])
        self.assertEqual(self.sent, [])

    def test_a_state_value_nobody_can_read_starts_the_clock_again(self):
        (self.state / T.APP.STALE_FILE).write_text(
            json.dumps({"herd-exampleu": {"since": "x", "tried": None, "told": True}}))   # «told» would silence it
        self.assertEqual(self.tell(at(10, 4, 0)), [])
        self.assertEqual(self.tell(at(11, 5, 59)), [])
        self.assertEqual(len(self.tell(at(11, 6, 1))), 1, "26 h from when it was read again")

    def test_a_target_removed_and_added_again_is_told_again(self):
        self.tell(at(10, 4, 0))
        self.assertEqual(len(self.tell(at(11, 6, 1))), 1)
        saved = (T.WORK / "targets.json").read_text()
        targets = json.loads(saved)
        targets["targets"].pop("herd-exampleu")
        (T.WORK / "targets.json").write_text(json.dumps(targets, ensure_ascii=False))
        self.tell(at(11, 7, 0))
        self.assertNotIn("herd-exampleu", json.loads((self.state / T.APP.STALE_FILE).read_text()))
        (T.WORK / "targets.json").write_text(saved)
        self.assertEqual(self.tell(at(11, 8, 0)), [])
        self.assertEqual(len(self.tell(at(12, 10, 1))), 1, "told again, 26 h after it came back failing")

    def test_a_new_outage_after_a_return_that_was_never_delivered_is_told(self):
        self.good(at(10, 3, 0))
        self.assertEqual(len(self.tell(at(11, 6, 0))), 1)
        self.good(at(11, 7, 0))
        self.deliver = False                               # its return is never delivered
        self.assertEqual(self.tell(at(11, 7, 1)), [])
        self.deliver = True
        self.assertEqual(len(self.tell(at(12, 9, 1))), 1, "26 h after the last good run: another outage, told")
        self.assertIn(f"backup-stale-herd-exampleu-{int(at(11, 7, 0).timestamp())}", self.sent[-1][0])

    def test_a_target_whose_backup_is_running_is_not_judged_until_it_ends(self):
        self.good(at(10, 3, 0))
        self.assertEqual(T.APP.tell_stale(at(11, 6, 0), notify=self.notify, running=frozenset({"herd-exampleu"})), [])
        self.assertEqual(self.sent, [])
        self.assertEqual(len(self.tell(at(11, 6, 1))), 1)

    def test_a_bad_status_line_is_a_notice_not_delivered(self):
        import http.client as hc
        import urllib.request as ur
        real = ur.urlopen

        def bad(*a, **kw):
            raise hc.BadStatusLine("garbage")
        ur.urlopen = bad
        try:
            self.assertIs(T.APP._notify("s", "t", "b", "info"), False)
        finally:
            ur.urlopen = real


# ── with docker and restic: the real helper, through the door ──────────────────────────────────
@unittest.skipUnless(BRT.DOCKER and BRT.RESTIC, "needs docker on a shared network (TEST_SELF_HOST, TEST_NETWORK) "
                                                "and restic")
class RealHelperThroughTheDoor(unittest.TestCase):
    def test_two_runs_through_the_door_and_the_folder_opens_with_restic_alone(self):
        fresh_vault()
        RS.RUNS._runs.clear()
        state = BRT.SHARED / "state-real-remote"
        files = {"apps/n8n/n8n.dump": os.urandom(1024 * 1024), "volumes/notes.txt": "גיבוי\n".encode() * 500}
        r1 = BR.run("remote-herd-real", "exampleu", BRT.SHARED, state, BRT.fake_export(files), lambda s: None, weekday=4)
        files["volumes/notes.txt"] = b"changed\n"
        r2 = BR.run("remote-herd-real", "exampleu", BRT.SHARED, state, BRT.fake_export(files), lambda s: None, weekday=5)
        self.assertNotEqual(r1["snapshot"], r2["snapshot"])
        self.assertLess(r2["added"], 512 * 1024, "the second run sent the unchanged dump again")
        key = VAULT.instances["backup_key-exampleu"]["secret"]["key"]
        snaps = BRT._local_snapshots("/גיבויים/link-exampleu-real", key)
        self.assertEqual((len(snaps), {s["hostname"] for s in snaps}), (2, {"exampleu"}))
        self.assertTrue(any(c[1].startswith("/repo/link-exampleu-real/data/") for c in HOST_DOOR.calls),
                        "restic's packs did not cross the door")
        self.assertEqual(RS.RUNS._runs, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
