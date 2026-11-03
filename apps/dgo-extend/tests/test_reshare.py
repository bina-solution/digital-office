#!/usr/bin/env python3
"""test_reshare — `serve.shared`: an office hands on what another office gave it (2026-10-19).

The case: claude-cloud is linked to vps1 only, vps1 is linked to hp-laptop, and Plane runs on
hp-laptop. A link is point-to-point and stays so, so the request is handed on at the APPLICATION
layer: claude-cloud's door → vps1's door → vps1's OWN door to hp-laptop → hp-laptop's door → Plane.

Every claim runs on real sockets on loopback — two doors of `link-proxy.py`, chained, in front of an
echo app — with route tables built by the functions the running offices use (`catalog.reshare` on the
office in the middle, `Door._table` on both doors). The one stand-in is a name: on an office the
re-shared app's upstream is `<alias>.<origin>`, the network alias the compiler puts on the link proxy,
which the docker DNS of this test does not have — so it is pointed at 127.0.0.1, and only it.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "apps/dgo-extend"
sys.path.insert(0, str(APP))

import catalog  # noqa: E402


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


door_mod = _load(APP / "link-proxy.py", "dgo_door_reshare")
# The link secret each door signs with is the credential plane's row; here, a fixed one per office.
door_mod.link_secret = lambda office: f"secret-of-{office}" if office else ""


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _read_head(sock: socket.socket) -> bytes:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(65536)
        if not chunk:
            break
        data += chunk
    return data


class EchoApp(threading.Thread):
    """Plane, as far as a door can tell: answers every request with the head it RECEIVED, as JSON —
    and a websocket handshake with `101`, then echoes."""

    def __init__(self):
        super().__init__(daemon=True)
        self.port = _free_port()
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", self.port))
        self.srv.listen(16)

    def run(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._one, args=(c,), daemon=True).start()

    def _one(self, c: socket.socket):
        head = _read_head(c)
        fields = {}
        for line in head.split(b"\r\n\r\n", 1)[0].split(b"\r\n")[1:]:
            k, _, v = line.decode("latin-1").partition(":")
            fields.setdefault(k.strip().lower(), []).append(v.strip())
        if fields.get("upgrade") == ["websocket"]:
            c.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
            rest = head.split(b"\r\n\r\n", 1)[1]
            if rest:
                c.sendall(rest)
            while True:
                b = c.recv(65536)
                if not b:
                    break
                c.sendall(b)
            c.close()
            return
        body = json.dumps(fields).encode()
        c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                  + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
        c.close()


def _door(office: str, doc: dict):
    """A serving door for the pair with `office`, its route table set from `doc` (no fetch)."""
    rule = {"kind": "door", "app": "door", "office": office, "bind": "127.0.0.1", "port": _free_port()}
    d = door_mod.Door(rule)
    d._routes = door_mod.Door._table(doc)
    d._at = time.time() + 3600          # the table is fresh for the test's life; no fetch happens
    d.start()
    if not d.ready.wait(5):
        raise RuntimeError(f"door for {office} did not listen: {d.refused}")
    return d


def _ask(port: int, host: str, extra: bytes = b"") -> tuple[int, dict, bytes]:
    c = socket.create_connection(("127.0.0.1", port), timeout=10)
    c.sendall(b"GET /api/v1/workspaces/ HTTP/1.1\r\nHost: " + host.encode() + b"\r\n" + extra + b"\r\n")
    data = b""
    while True:
        b = c.recv(65536)
        if not b:
            break
        data += b
    c.close()
    head, _, body = data.partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1]) if head else 0
    hdrs = {}
    for line in head.split(b"\r\n")[1:]:
        k, _, v = line.decode("latin-1").partition(":")
        hdrs[k.strip().lower()] = v.strip()
    return status, hdrs, body


# ── the three offices ──────────────────────────────────────────────────────────────────────────────
APP_UP = EchoApp()
APP_UP.start()
# hp-laptop's own door, for its pair with vps1: Plane under its own authority, mapped to `owner`.
HP_CATALOG = catalog.build({"apps": [
    {"app": "project-pln", "alias": "plane", "name": "Plane", "port": APP_UP.port, "service": "127.0.0.1",
     "host": "plane.localhost", "identity": {"to": "owner"}}]}, "hp-laptop", {"he": "HP"})
HP_DOOR = _door("vps1", HP_CATALOG)
# What vps1 PULLED from hp-laptop (the catalog its door published), and vps1's own door to it.
FETCHED = {"hp-laptop": {**catalog.build({"apps": [
    {"app": "project-pln", "alias": "plane", "name": "Plane", "port": 8080, "host": "plane.localhost"},
    {"app": "browser42", "alias": "browser42", "name": "דפדפן", "port": 8090}]}, "hp-laptop", {"he": "HP"}),
    # …and what hp-laptop ITSELF re-shared: never handed on a second time.
    "shared": [{"office": "macbook", "apps": [{"alias": "drive", "app": "drive", "port": 9, "host": "drive.macbook"}]}]}}
DOORS = {"hp-laptop": HP_DOOR.rule["port"]}
VPS1_OWN = {"apps": [{"app": "drive", "alias": "drive", "name": "Drive", "port": APP_UP.port,
                      "service": "127.0.0.1", "host": "drive.localhost", "identity": {"to": "akadmin"}}]}


def _vps1_door(serve: dict, asking: str = "claude-cloud"):
    """vps1's door for its pair with `asking`, its table what `build_catalog(office=asking)` serves."""
    doc = catalog.build(VPS1_OWN, "vps1")
    shared = catalog.reshare(serve, asking, "vps1", FETCHED, DOORS)
    for sec in shared:
        for app in sec["apps"]:
            app["service"] = "127.0.0.1"   # the `<alias>.<origin>` network alias, on loopback (see top)
    if shared:
        doc["shared"] = shared
    return _door(asking, doc)


SHARING = _vps1_door({"*": {}, "shared": "*"})


# ── the claims ─────────────────────────────────────────────────────────────────────────────────────
def chain_reaches_the_origin_as_the_middle_office():
    """claude-cloud → vps1 → hp-laptop: Plane sees its own authority, and the identity and office
    hp-laptop maps vps1 to — signed with hp-laptop's secret for vps1. Nothing claude-cloud wrote about
    who it is arrives."""
    status, _h, body = _ask(SHARING.rule["port"], "plane.hp-laptop",
                            b"X-authentik-username: someone-of-claude-cloud\r\nX-DGO-Office: forged\r\n"
                            b"Origin: http://plane.hp-laptop\r\n")
    p = []
    if status != 200:
        return [f"the request did not reach the origin's app through both doors: HTTP {status} {body[:200]!r}"]
    got = json.loads(body)
    if got.get("host") != ["plane.localhost"]:
        p.append(f"the origin's app must see its OWN authority, got Host {got.get('host')}")
    if got.get("origin") != ["http://plane.localhost"]:
        p.append(f"an Origin that named the name it arrived under is rewritten with the Host, got {got.get('origin')}")
    if got.get("x-authentik-username") != ["owner"]:
        p.append(f"the user is what the ORIGIN maps the middle office to, got {got.get('x-authentik-username')}")
    if got.get("x-dgo-office") != ["vps1"]:
        p.append(f"to the origin, the request comes from the office in the middle, got {got.get('x-dgo-office')}")
    sig = (got.get("x-dgo-identity") or [""])[0].split(" ")
    if len(sig) != 5 or sig[1:3] != ["vps1", "owner"] or not hmac.compare_digest(
            sig[4], hmac.new(b"secret-of-vps1", door_mod.signed_text("vps1", "owner", int(sig[3])).encode(),
                             hashlib.sha256).hexdigest()):
        p.append(f"the identity must be signed by the origin's door with its secret for vps1, got {sig}")
    return p


def the_cli_reaches_it_with_the_port_in_host():
    """`where.sh` gives the applier `http://plane.hp-laptop:<door>` — the Host carries the port."""
    status, _h, body = _ask(SHARING.rule["port"], "plane.hp-laptop:9004")
    return [] if status == 200 else [f"Host with a port must route the same, got HTTP {status} {body[:120]!r}"]


def a_handed_on_app_answers_under_its_full_name_only():
    p = []
    for host in ("plane", "plane.localhost", "plane.vps1"):
        status, hdrs, _b = _ask(SHARING.rule["port"], host)
        if status != 404 or hdrs.get("x-dgo-door") != "no-app":
            p.append(f"`{host}` is not a name vps1 answers a handed-on app under, got HTTP {status}")
    return p


def the_middle_office_own_apps_are_unchanged():
    status, _h, body = _ask(SHARING.rule["port"], "drive.localhost")
    if status != 200:
        return [f"vps1's own app must still answer, got HTTP {status}"]
    got = json.loads(body)
    p = []
    if got.get("host") != ["drive.localhost"] or got.get("x-authentik-username") != ["akadmin"] \
            or got.get("x-dgo-office") != ["claude-cloud"]:
        p.append(f"an own app keeps its Host, its mapping and the asking office, got {got}")
    return p


def nothing_is_handed_on_without_shared():
    d = _vps1_door({"*": {}})
    try:
        status, hdrs, _b = _ask(d.rule["port"], "plane.hp-laptop")
    finally:
        d.stop()
    return [] if status == 404 and hdrs.get("x-dgo-door") == "no-app" else [
        f"without `serve.shared`, vps1 must answer no-app for the HP's Plane, got HTTP {status}"]


def an_office_is_never_handed_its_own_apps_back():
    d = _vps1_door({"*": {}, "shared": "*"}, asking="hp-laptop")
    try:
        status, _h, _b = _ask(d.rule["port"], "plane.hp-laptop")
    finally:
        d.stop()
    return [] if status == 404 else [f"vps1's door for hp-laptop must not route hp-laptop's own Plane back, got {status}"]


def one_hop_only():
    """What hp-laptop itself re-shared (the MacBook's drive) is never handed on by vps1: its table
    does not name it, and the door answers no-app for it."""
    names = sorted(SHARING._routes)
    status, hdrs, _b = _ask(SHARING.rule["port"], "drive.macbook")
    return [] if "drive.macbook" not in names and status == 404 and hdrs.get("x-dgo-door") == "no-app" else [
        f"a re-shared app is handed on once, never twice: vps1's table names {names}, HTTP {status}"]


def another_office_name_never_falls_to_an_own_app():
    """`drive.macbook` with no share behind it — revoked, unlinked, or a tile left on the consuming
    side — is no-app at vps1's door, never vps1's OWN Drive under vps1's mapping; vps1's Drive still
    answers under the names that are its own: its authority, and `drive.vps1` (`bbox remote`)."""
    d = _vps1_door({"*": {}})
    p = []
    try:
        for host in ("drive.macbook", "drive.macbook."):
            status, hdrs, _b = _ask(d.rule["port"], host)
            if status != 404 or hdrs.get("x-dgo-door") != "no-app":
                p.append(f"`{host}` names another office: no-app, never vps1's own app of that alias, got HTTP {status}")
        for host in ("drive.vps1", "drive.vps1:9004", "drive.localhost"):
            status, _h, body = _ask(d.rule["port"], host)
            if status != 200 or json.loads(body).get("x-authentik-username") != ["akadmin"]:
                p.append(f"vps1's own Drive must answer under `{host}`, got HTTP {status}")
    finally:
        d.stop()
    return p


def a_host_declared_with_a_port_still_routes():
    """`host: plane.hp:8080` is legal; a request is looked up without its port, and so is the table."""
    table = door_mod.Door._table(catalog.build({"apps": [
        {"app": "project-pln", "alias": "plane", "name": "Plane", "port": 8080, "host": "plane.hp:8080"}]}, "vps1"))
    d = door_mod.Door({"kind": "door", "app": "door", "office": "x", "bind": "127.0.0.1", "port": 1})
    d._routes, d._at = table, time.time() + 3600
    return [] if d.route("plane.hp") == ("project-pln", 8080, "") else [
        f"a host declared with its port must route as the request names it, got {d.route('plane.hp')} from {sorted(table)}"]


def an_origin_authority_that_is_not_one_is_never_written():
    """The origin's authority goes into `Host:`; one with a line break would be a header of its own."""
    doc = catalog.build(VPS1_OWN, "vps1")
    doc["shared"] = [{"office": "hp-laptop", "apps": [
        {"alias": "plane", "port": HP_DOOR.rule["port"], "host": "plane.hp-laptop", "service": "127.0.0.1",
         "origin_host": "plane.localhost\r\nX-Injected: 1"}]}]
    table = door_mod.Door._table(doc)
    return [] if "plane.hp-laptop" not in table else [
        f"an origin authority that is not one must not be routed, got {table['plane.hp-laptop']}"]


def a_websocket_crosses_both_doors():
    """browser42 is a websocket after its first request: the 101 and the bytes after it cross both doors."""
    c = socket.create_connection(("127.0.0.1", SHARING.rule["port"]), timeout=10)
    c.sendall(b"GET /ws HTTP/1.1\r\nHost: plane.hp-laptop\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
              b"Sec-WebSocket-Key: x\r\nSec-WebSocket-Version: 13\r\n\r\n")
    head = _read_head(c)
    p = []
    if not head.startswith(b"HTTP/1.1 101"):
        p.append(f"the handshake must come back as 101 through both doors, got {head[:60]!r}")
    else:
        c.sendall(b"ping-through-two-doors")
        got = b""
        deadline = time.time() + 5
        while len(got) < 22 and time.time() < deadline:
            got += c.recv(64)
        if got != b"ping-through-two-doors":
            p.append(f"bytes after the 101 must be carried both ways, got {got!r}")
    c.close()
    return p


CLAIMS = [chain_reaches_the_origin_as_the_middle_office, the_cli_reaches_it_with_the_port_in_host,
          a_handed_on_app_answers_under_its_full_name_only, the_middle_office_own_apps_are_unchanged,
          nothing_is_handed_on_without_shared, an_office_is_never_handed_its_own_apps_back,
          one_hop_only, another_office_name_never_falls_to_an_own_app, a_host_declared_with_a_port_still_routes,
          an_origin_authority_that_is_not_one_is_never_written, a_websocket_crosses_both_doors]


def main() -> int:
    failed = 0
    for fn in CLAIMS:
        try:
            problems = list(fn())
        except Exception as e:                              # noqa: BLE001 — a claim that cannot run
            problems = [f"the claim could not be checked: {type(e).__name__}: {e}"]
        if problems:
            failed += 1
            for prob in problems:
                print(f"FAIL  {fn.__name__}\n      {prob}")
        else:
            print(f"PASS  {fn.__name__}")
    print(f"reshare: {len(CLAIMS)} claim(s), {len(CLAIMS) - failed} pass, {failed} fail")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
