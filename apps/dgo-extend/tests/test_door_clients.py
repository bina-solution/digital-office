#!/usr/bin/env python3
"""WHO MAY ARRIVE at a serve rule — link-proxy's `outside` / `admit` (issues/a-peer-on-one-tunnel-can-reach-another-
pairs-catalog-listener-and-be-stamped-as-that-office.yaml).

A serve rule's `clients` is its pair's peer tunnel address. A peer that widens its own AllowedIPs can reach another
pair's catalog listener (one port for every pair) and be stamped as that pair's office; the door must know the
connection came from outside. Stage 1 (AGENTS rule 8): it is SAID — one log line per listener and address, and
`outside` on the door's access record — and served; DGO_LINK_CLIENTS=refuse closes it.

    python3 apps/dgo-extend/tests/test_door_clients.py

Python 3.9+, standard library only; real sockets on 127.0.0.1, nothing dialed outside the test.
"""
from __future__ import annotations

import importlib.util
import socket
import sys
import threading
import time
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
spec = importlib.util.spec_from_file_location("dgo_door_clients_mod", APP / "link-proxy.py")
lp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lp)

FAIL: list = []
LOG: list = []
lp.log = LOG.append                          # every line the proxy says, kept for the checks


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


SERVE = {"office": "hp-laptop", "direction": "serve", "app": "dgo-extend", "kind": "app",
         "bind": "10.79.5.1", "port": 8983, "target": "dgo-extend:8984", "clients": ["10.79.5.2"]}


def test_outside():
    check(lp.outside(SERVE, "10.79.5.2") is False, "the pair's own peer is not outside")
    check(lp.outside(SERVE, "10.79.6.2") is True, "THE FINDING: another pair's peer at this pair's catalog is outside")
    check(lp.outside(SERVE, "::ffff:10.79.5.2") is False, "an IPv4-mapped address is the same peer")
    check(lp.outside(SERVE, "::ffff:10.79.6.2") is True, "…and a mapped stranger is outside")
    check(lp.outside(SERVE, "") is False, "a unix-socket door has no address: not judged here (the host bridge's side)")
    check(lp.outside({**SERVE, "clients": []}, "10.79.6.2") is False, "a serve rule that names no clients judges nothing")
    check(lp.outside({**SERVE, "clients": None}, "10.79.6.2") is False, "…nor one whose clients is null")
    use = {**SERVE, "direction": "use", "clients": ["10.79.5.2"]}
    check(lp.outside(use, "172.18.0.9") is False, "a use rule (this office's own apps) is never judged")
    check(lp.outside({**SERVE, "clients": ["10.79.5.2", "10.79.5.3"]}, "10.79.5.3") is False, "any named client is in")
    check(lp.outside({**SERVE, "clients": "10.79.5.2"}, "10.79.5.2") is False
          and lp.outside({**SERVE, "clients": "10.79.5.2"}, "10.79.6.2") is True, "a string is one client")
    check(lp.outside({**SERVE, "clients": 7}, "10.79.6.2") is False, "a shape nobody renders is judged by nothing, never a crash")


def test_admit_modes():
    LOG.clear(); lp._SAID_OUTSIDE.clear()
    lp.CLIENTS_MODE = "warn"
    check(lp.admit(SERVE, "10.79.5.2") is True and not LOG, "the peer: served, nothing said")
    check(lp.admit(SERVE, "10.79.6.2") is True, "stage 1: an outsider is SERVED")
    check(len(LOG) == 1 and "OUTSIDE" in LOG[0] and "10.79.6.2" in LOG[0] and "10.79.5.2" in LOG[0],
          "…and SAID once, naming the address and the rule's clients")
    lp.admit(SERVE, "10.79.6.2")
    check(len(LOG) == 1, "…once per listener and address, not per connection")
    lp.admit(SERVE, "10.79.7.2")
    check(len(LOG) == 2, "…a second address is said too")
    for i in range(1100):
        lp.admit(SERVE, f"10.80.{i // 250}.{i % 250}")
    check(len(lp._SAID_OUTSIDE) <= 1024, "…and what was said is bounded (a spray of addresses cannot grow it)")
    LOG.clear(); lp._SAID_OUTSIDE.clear()
    lp.CLIENTS_MODE = "refuse"
    check(lp.admit(SERVE, "10.79.6.2") is False and "REFUSED" in LOG[0], "DGO_LINK_CLIENTS=refuse: closed, and said")
    check(lp.admit(SERVE, "10.79.5.2") is True, "…the pair's own peer still served")
    lp.CLIENTS_MODE = "warn"


ACCEPTED = [0]                               # connections the upstream (the app) accepted


def _echo_upstream():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0)); srv.listen(8)

    def serve():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            ACCEPTED[0] += 1
            data = c.recv(64)
            c.sendall(b"echo:" + data)
            c.close()
    threading.Thread(target=serve, daemon=True).start()
    return srv


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def _through(rule) -> bytes:
    f = lp.Forwarder(rule)
    f.start()
    f.ready.wait(5)
    out = b""
    try:
        with socket.create_connection(("127.0.0.1", rule["port"]), timeout=5) as c:
            c.sendall(b"hi")
            c.settimeout(5)
            try:
                while True:
                    chunk = c.recv(64)
                    if not chunk:
                        break
                    out += chunk
            except OSError:
                pass
    finally:
        f.stop()
    return out


def test_forwarder_live():
    up = _echo_upstream()
    target = f"127.0.0.1:{up.getsockname()[1]}"
    base = {"office": "hp-laptop", "direction": "serve", "app": "bina-ds", "kind": "app",
            "bind": "127.0.0.1", "target": target}
    LOG.clear(); lp._SAID_OUTSIDE.clear(); lp.CLIENTS_MODE = "warn"
    got = _through({**base, "port": _free_port(), "clients": ["127.0.0.1"]})
    check(got == b"echo:hi" and not [l for l in LOG if "OUTSIDE" in l], "a live agent-port door, the named client: served, nothing said")
    got = _through({**base, "port": _free_port(), "clients": ["10.79.5.2"]})
    check(got == b"echo:hi" and any("OUTSIDE" in l for l in LOG), "a live door, an outsider, stage 1: served and said")
    lp.CLIENTS_MODE = "refuse"
    before = ACCEPTED[0]
    got = _through({**base, "port": _free_port(), "clients": ["10.79.5.2"]})
    time.sleep(0.3)
    check(got == b"" and ACCEPTED[0] == before, "a live door, an outsider, refuse: closed, and the app never accepted it")
    got = _through({**base, "port": _free_port(), "direction": "use", "clients": []})
    check(got == b"echo:hi", "…a use rule is served in refuse mode too")
    lp.CLIENTS_MODE = "warn"
    up.close()


def test_door_record():
    recs = []
    lp.access_record = recs.append
    rule = {"office": "hp-laptop", "app": "door", "kind": "door", "direction": "serve", "bind": "10.79.5.1",
            "port": 9005, "target": "dgo-extend:8984", "clients": ["10.79.5.2"]}

    def asked(peer: str) -> dict:
        door = lp.Door(rule)
        door._routes = lp.Door._table({"office": "hp-laptop", "apps": []})
        door._at = time.time()
        a, b = socket.socketpair()
        t = threading.Thread(target=door._serve, args=(a, peer), daemon=True)
        t.start()
        b.sendall(b"GET / HTTP/1.1\r\nHost: nothing.hp-laptop\r\n\r\n")
        b.settimeout(5)
        try:
            while b.recv(4096):
                pass
        except OSError:
            pass
        t.join(5)
        b.close()
        return recs[-1] if recs else {}

    check(asked("10.79.6.2").get("outside") is True, "the door's access record says `outside` for an outsider")
    check("outside" not in asked("10.79.5.2"), "…and nothing for the pair's own peer")
    check("outside" not in asked(""), "…nor for a unix-socket door (no address)")


def test_door_live():
    """The DOOR's own accept loop (the catalog's and the link door's listener), on a real port."""
    def through(mode: str) -> bytes:
        lp.CLIENTS_MODE = mode
        rule = {"office": "hp-laptop", "app": "door", "kind": "door", "direction": "serve", "bind": "127.0.0.1",
                "port": _free_port(), "target": "dgo-extend:8984", "clients": ["10.79.5.2"]}
        door = lp.Door(rule)
        door._routes = lp.Door._table({"office": "hp-laptop", "apps": []})
        door._at = time.time()
        door.start()
        door.ready.wait(5)
        out = b""
        try:
            with socket.create_connection(("127.0.0.1", rule["port"]), timeout=5) as c:
                c.sendall(b"GET / HTTP/1.1\r\nHost: nothing.hp-laptop\r\n\r\n")
                c.settimeout(5)
                try:
                    while True:
                        chunk = c.recv(4096)
                        if not chunk:
                            break
                        out += chunk
                except OSError:
                    pass
        finally:
            door.stop()
            lp.CLIENTS_MODE = "warn"
        return out

    check(through("warn").startswith(b"HTTP/1."), "a live door, an outsider, stage 1: answered as before")
    check(through("refuse") == b"", "a live door, an outsider, refuse: closed before the door reads a byte")


def main() -> int:
    test_outside()
    test_admit_modes()
    test_forwarder_live()
    test_door_record()
    test_door_live()
    print(f"\n{'FAILED: ' + str(len(FAIL)) if FAIL else 'all passed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
