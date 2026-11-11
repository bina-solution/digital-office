"""remote_fleet_test — machines shared between offices, proven without two offices (DGO-553).

What this proves, and why each piece is here rather than in a screenshot:

  * a linked office's computers app is found from the COMPILED record and nothing else (no state, no
    second list of machines) — and an office with no `door` is skipped, because a wrong base is a
    request into somebody else's app;
  * `<machine>.<office>` splits on the LAST dot, so a local id (no dot) never becomes a network call;
  * a peer's rows are re-issued under the office suffix and a peer's OWN shared rows are not
    re-shared onward (sharing is one hop, not a chain);
  * `serve.computers.machines` is read the way the owner wrote it: `"*"`, a list, absent = today's
    behaviour, malformed = nothing, and the refusal sentence exists for the case that matters;
  * the whole merge is exercised against a stand-in door — no HTTP, no office, no machine.

Run: python3 apps/computers/tests/test_remote_fleet.py   (or pytest — plain functions)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # apps/computers, so `import remote` is the app's

import remote  # noqa: E402


def _registry(files: dict[str, dict]) -> str:
    d = tempfile.mkdtemp(prefix="dgo-registry-")
    for name, body in files.items():
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(json.dumps(body, ensure_ascii=False))
    return d


def _record(office: str, **over) -> dict:
    rec = {"id": f"computers.{office}", "app": "computers", "alias": "computers",
           "module": {"kind": "external", "host": f"computers.{office}", "path": "/a/computers/"},
           "port": 8977, "link_port": 9005,
           "remote": {"office": office, "label": {"he": "MacBook", "en": "MacBook"}},
           "door": {"base": f"http://computers.{office}:9005", "host": "computers.localhost",
                    "user": "akadmin"}}
    rec.update(over)
    return rec


def test_an_office_is_found_from_the_compiled_record() -> None:
    base = _registry({"remote.macbook.computers.json": _record("macbook")})
    found = remote.apps(base)
    assert len(found) == 1
    app = found[0]
    assert app["office"] == "macbook"
    assert app["base"] == "http://computers.macbook:9005"
    assert app["host"] == "computers.localhost", "the authority the door routes on crosses too"


def test_an_office_without_a_door_is_skipped() -> None:
    rec = _record("vps1")
    rec.pop("door")
    base = _registry({"remote.vps1.computers.json": rec})
    assert remote.apps(base) == [], "no door = no base = nothing to call"


def test_a_local_id_never_becomes_a_call() -> None:
    known = [{"office": "macbook", "label": "MacBook", "base": "http://x:9005",
              "host": "computers.localhost"}]
    assert remote.office_of("computer_local-local", known) == (None, None)
    assert remote.office_of("computer_ssh-abc", known) == (None, None)


def test_the_last_dot_is_the_office() -> None:
    known = [{"office": "macbook", "label": "MacBook", "base": "http://x:9005", "host": "h"}]
    app, machine = remote.office_of("computer_ssh-abc.macbook", known)
    assert app and machine == "computer_ssh-abc"
    assert remote.office_of("computer_ssh-abc.dell-x", known) == (None, None), "unknown office"


def test_rows_carry_their_office_and_are_not_reshared() -> None:
    app = {"office": "macbook", "label": "MacBook", "base": "http://x:9005", "host": "h"}
    payload = {"computers": [
        {"id": "computer_ssh-abc", "label": "Dell", "host": "192.168.16.105", "ok": True},
        # a machine the peer itself only SHARES: two hops would mean this office reaches a third
        # office's machine without that office ever having agreed with this one
        {"id": "computer_ssh-zzz.vps1", "label": "vps1 box", "ok": True,
         "remote": {"office": "vps1"}},
    ]}
    rows = remote.as_rows(app, payload)
    assert len(rows) == 1, "a peer's shared row is not passed on"
    row = rows[0]
    assert row["id"] == "computer_ssh-abc.macbook"
    assert row["remote"] == {"office": "macbook", "label": "MacBook",
                             "base": "http://x:9005", "host": "h",
                             "machine": "computer_ssh-abc", "shell": None}
    # `shell` is what the peer's app SAYS it can do (`supports_shell`): None = not asked, and the
    # screen keeps the button off with "the other office needs an update" rather than guessing yes.
    assert remote.as_rows(app, payload, shell=True)[0]["remote"]["shell"] is True
    assert row["removable"] is False and row["builtin"] is False


def test_what_the_office_gives_is_read_as_written() -> None:
    assert remote.machines_declared({}) == "*", "no serve block: today's behaviour"
    assert remote.machines_declared({"computers": {}}) == "*", "declared, no machines key"
    assert remote.machines_declared({"computers": {"machines": "*"}}) == "*"
    assert remote.machines_declared({"computers": {"machines": ["a", "b"]}}) == ["a", "b"]
    assert remote.machines_declared({"computers": {"machines": "a"}}) == ["a"]
    assert remote.machines_declared({"computers": {"machines": 7}}) == [], "malformed admits nothing"



def test_an_office_is_served_the_app_only_when_it_is_given_it() -> None:
    """«מחשבים» at all, before «which machines» — the two refusals that were one.

    `machines_declared` answers `"*"` when no `machines` key was declared — right once the APP is
    shared, and a hole when it is not: an office given only `terminal` reached every machine of this
    office (second reader, 2026-11-02). The rules are `catalog.publishable`'s own three.
    """
    assert remote.serves({}, "macbook") is False, "nothing served"
    assert remote.serves({"*": {}}, "macbook") is True, "the wildcard serves everything"
    assert remote.serves({"computers": {"port": 1}}, "macbook") is True, "named"
    assert remote.serves({"terminal": {"port": 1}}, "macbook") is False, "only another app is given"
    assert remote.serves({"*": {}, "exclude": ["computers"]}, "macbook") is False, "excluded"
    assert remote.serves({"*": {}, "exclude": "computers"}, "vps1") is False, "excluded, written once"
    # a per-office `only` list is that office's whole grant, and wins over the wildcard
    assert remote.serves({"*": {}, "only": {"vps1": ["terminal"]}}, "vps1") is False
    assert remote.serves({"*": {}, "only": {"vps1": ["ipados", "computers"]}}, "vps1") is True
    assert remote.serves({"*": {}, "only": {"vps1": ["terminal"]}}, "macbook") is True, "not narrowed"

def test_sharing_is_by_id_and_a_star_is_everything() -> None:
    assert remote.is_shared("*", "computer_local-local") is True
    assert remote.is_shared(["computer_ssh-abc"], "computer_ssh-abc") is True
    assert remote.is_shared(["computer_ssh-abc"], "computer_ssh-def") is False
    # an office may name a machine by its SHARED id as well as its own id
    assert remote.is_shared(["computer_ssh-abc.macbook"], "computer_ssh-abc.macbook") is True


def test_the_refusal_only_speaks_to_a_peer() -> None:
    assert remote.refusal("", ["computer_ssh-abc"], "computer_ssh-def") == "", (
        "a local caller is asked nothing new")
    assert remote.refusal("macbook", "*", "computer_local-local") == ""
    why = remote.refusal("macbook", ["computer_ssh-abc"], "computer_local-local")
    assert why and "לא שותף" in why, "a peer that asks for an unshared machine gets a sentence"


def test_the_merge_uses_the_peer_answer_end_to_end() -> None:
    """The full shape: registry → office → that office's answer → rows of THIS fleet."""
    base = _registry({"remote.macbook.computers.json": _record("macbook")})
    app = remote.apps(base)[0]
    answer = {"computers": [{"id": "computer_ssh-abc", "label": "Dell", "host": "10.0.0.5",
                             "port": 22, "user": "shlomy", "state": "ok", "ok": True}]}
    rows = remote.as_rows(app, answer)
    assert [r["id"] for r in rows] == ["computer_ssh-abc.macbook"]
    assert rows[0]["state"] == "ok" and rows[0]["user"] == "shlomy"



def test_serves_agrees_with_the_compiler_on_the_live_declaration() -> None:
    """The gate's rule and the compiler's publish rule must answer the same thing, office by office.

    They are two implementations of one decision (`remote.serves` here, `catalog.publishable` there),
    and a disagreement is not theoretical: the compiler withholds the app while the gate admits the
    machines (the hole that was `exclude`, 2026-11-02), or the reverse. This asks the live link app and
    the live catalog, and skips — loudly — when either is not reachable, because "could not check" is
    not "agrees".
    """
    import json
    import urllib.error
    import urllib.request
    try:
        link = json.load(urllib.request.urlopen("http://dgo-extend:8983/api/link", timeout=15))
    except (urllib.error.URLError, OSError, ValueError):
        print("      (skipped: the link app is not reachable from here)")
        return
    serve = link.get("serve") or {}
    for item in link.get("items") or []:
        oid = str(item.get("office") or "")
        try:
            req = urllib.request.Request("http://dgo-extend:8984/api/link/catalog",
                                         headers={"x-dgo-office": oid})
            cat = json.load(urllib.request.urlopen(req, timeout=20))
        except (urllib.error.URLError, OSError, ValueError):
            print(f"      ({oid}: its catalog could not be read — not counted as agreeing)")
            continue
        published = "computers" in [a.get("alias") for a in (cat.get("apps") or [])]
        assert remote.serves(serve, oid) == published, (
            f"{oid}: the catalog says {published}, remote.serves says {remote.serves(serve, oid)}")

if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:                 # noqa: BLE001 — a runner reports, never hides
                fails += 1
                print(f"FAIL {name}: {e}")
    print(f"remote_fleet_test — {fails} failing")
    sys.exit(1 if fails else 0)
