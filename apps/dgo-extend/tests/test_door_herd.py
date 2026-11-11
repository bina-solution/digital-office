#!/usr/bin/env python3
"""test_door_herd — the herd's mark (DGO-1800): the door says «this peer is the herd's» only when both offices' KEYS say so.

An app behind the door (apps/computers) must tell the owner's own offices from a client's before it narrows what a
linked office reads, and it cannot see a peer's WireGuard key — that lives in this app's records. So the door states the
one fact only it has: `x-dgo-herd: 1`. Asked here in its three places:
  * give.herd_peer — both ends by key (this office's own key, this office's record of the peer), never by a name;
    an alias counts as its office's name, an unreadable herd file or a missing key is «no»;
  * linkproxy.build_multi — the mark goes on the pair's SERVE rules when the caller decided `herd: True` (exactly
    True), never on its `use` rules, and never arrives inside a plan another office shipped;
  * link-proxy's Door.rewrite — a peer's own x-dgo-herd (any spelling) is removed on every request; the door writes
    it once, and only beside the office it writes.

Run: python3 apps/dgo-extend/tests/test_door_herd.py   (needs PyYAML — the dgo-extend image has it)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))

import give  # noqa: E402
import linkproxy  # noqa: E402

spec = importlib.util.spec_from_file_location("dgo_door_herd_mod", APP / "link-proxy.py")
door = importlib.util.module_from_spec(spec)
spec.loader.exec_module(door)

FAIL: list[str] = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAIL.append(what)


KEYS = {"macbook": "K-MAC=", "vps1": "K-VPS=", "dell": "K-DELL="}
DOC = {"offices": {"macbook": {"wg_public_key": KEYS["macbook"]}, "vps1": {"wg_public_key": KEYS["vps1"]},
                   "dell": {"aliases": ["portable-ubuntu", "portable"], "wg_public_key": KEYS["dell"]},   # as herd.yaml
                   "hp-laptop": {}}}


def rec(oid, key, shape="flat"):
    return {"id": oid, "identity": {"wg": {"public": key} if shape == "nested" else key}}


def test_herd_peer():
    home = rec("macbook", KEYS["macbook"])
    check(give.herd_peer(DOC, home, rec("vps1", KEYS["vps1"])), "a herd office, by its key, is the herd's")
    check(give.herd_peer(DOC, home, rec("vps1", KEYS["vps1"], "nested")), "…whichever shape its identity travels in")
    check(give.herd_peer(DOC, home, rec("portable-ubuntu", KEYS["dell"])), "…and under an alias the file gives it")
    check(not give.herd_peer(DOC, home, rec("vps1", "K-OTHER=")), "a herd NAME with another key is not the herd's")
    check(not give.herd_peer(DOC, home, rec("portable", "K-OTHER=")),
          "a client called `portable` — the Dell's own alias — with another key is not the herd's")
    check(give.herd_peer(DOC, home, rec("portable", KEYS["dell"])), "…the Dell under that alias, by its key, is")
    check(not give.herd_peer(DOC, home, rec("exw", KEYS["vps1"])), "a name the file does not give is not, whatever key")
    check(not give.herd_peer(DOC, home, rec("hp-laptop", "")), "an office the file names with no key is not")
    check(not give.herd_peer(DOC, rec("macbook", "K-STOLEN="), rec("vps1", KEYS["vps1"])),
          "this office must be the herd's by ITS key too: a client named macbook marks nobody")
    check(not give.herd_peer({}, home, rec("vps1", KEYS["vps1"])), "an unreadable herd file marks nobody")
    check(not give.herd_peer(DOC, home, rec("macbook", KEYS["macbook"])), "this office is not its own peer")
    check(not give.herd_peer(DOC, home, {"id": "vps1"}), "a record with no identity is not")


def test_build_multi():
    # an app with an agent port too: its second door is a raw splice that rewrites no header, so it is never marked
    home = {"id": "macbook", "serve": {"drive": {"port": 8975}, "bina-ds": {"port": 3080, "agent_api_port": 3081}}}
    # a link the owner made both ways: the pair renders the doors it SERVES and the doors that USE the peer
    pairs = lambda herd: [{"office": {"id": "vps1"}, "slot": 3, "side": 1, "herd": herd,   # noqa: E731
                           "link": {"direction": "both"}}]
    peer_serves = {"vps1": {"meet": {"port": 8443}}}          # so the pair has a USE half to look at

    def build(herd, **kw):
        # (the use doors bind the link proxy's own address: on 0.0.0.0 they would clash with the serve door, as in life)
        return linkproxy.build_multi(home, pairs(herd), served_by_peer=peer_serves, control_bind="172.30.0.5", **kw)

    plan = build(True)
    serve = [r for r in plan["rules"] if r.get("direction") == "serve"]
    use = [r for r in plan["rules"] if r.get("direction") == "use"]
    doors = [r for r in serve if r.get("kind") == "door" or r.get("app") == linkproxy.SELF_APP]
    splices = [r for r in serve if r not in doors]
    check(bool(doors) and all(r.get("herd") is True for r in doors),
          f"a herd pair's door and catalog rules carry the mark ({len(doors)} rules)")
    check(bool(splices) and all("herd" not in r for r in splices),
          f"…its agent ports, raw splices, do not ({[r.get('kind') for r in splices]})")
    check(bool(use) and all("herd" not in r for r in use), f"…its use rules do not ({len(use)} rules)")
    for not_true in (False, None, "yes", 1):
        plan = build(not_true)
        check(all("herd" not in r for r in plan["rules"]), f"herd={not_true!r} marks nothing")
    shipped = {"vps1": {"office": "vps1", "rules": [
        {"office": "dell", "direction": "serve", "app": "dgo-door", "kind": "door", "port": 9300,
         "target": "dgo-extend:8984", "clients": ["10.79.9.2"], "bind": "10.79.9.1", "herd": True}]}}
    plan = build(False, shipped=shipped)
    taken = [r for r in plan["rules"] if r.get("rendered_by") == "vps1"]
    check(bool(taken) and all("herd" not in r for r in taken),
          f"a rule another office shipped arrives without the mark ({len(taken)} taken)")


def fields(head: bytes) -> dict:
    out: dict = {}
    for line in head.split(b"\r\n\r\n", 1)[0].split(b"\r\n")[1:]:
        name, _, value = line.partition(b":")
        out.setdefault(name.strip().lower(), []).append(value.strip())
    return out


def test_rewrite():
    D = door.Door
    forged = (b"GET /api/computers HTTP/1.1\r\nHost: computers.macbook\r\nX-Dgo-Herd: 1\r\nX_DGO_Herd: 1\r\n"
              b"x-dgo-herd: yes\r\n\r\n")
    plain = b"GET /api/computers HTTP/1.1\r\nHost: computers.macbook\r\n\r\n"
    got = fields(D.rewrite(forged, "owner", "vps1"))
    check(not any(k.replace(b"_", b"-") == b"x-dgo-herd" for k in got),
          "a peer's own x-dgo-herd, in any spelling, is removed when the rule is not the herd's")
    got = fields(D.rewrite(forged, "owner", "vps1", herd=True))
    check(got.get(b"x-dgo-herd") == [b"1"] and b"x_dgo_herd" not in got,
          f"on a herd rule the door writes it ONCE, its own: {got.get(b'x-dgo-herd')}")
    check(fields(D.rewrite(plain, "owner", "vps1", herd=True)).get(b"x-dgo-herd") == [b"1"],
          "…and writes it where the peer sent none")
    check(b"x-dgo-herd" not in fields(D.rewrite(plain, "owner", "", herd=True)),
          "never without the office it rides beside")
    check(b"x-dgo-herd" not in fields(D.rewrite(plain, "owner", "vps1")), "the default is no mark")


def main() -> int:
    test_herd_peer()
    test_build_multi()
    test_rewrite()
    print(f"test_door_herd: {'all passed' if not FAIL else f'{len(FAIL)} failed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
