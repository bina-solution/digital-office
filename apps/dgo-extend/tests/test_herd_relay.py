#!/usr/bin/env python3
"""test_herd_relay — the hub's relay is the HERD's, not a line in each office's `.env` (DGO-1355).

Measured 2026-11-05: the relay (carrier/relay.go, DGO-1097) was built on 11-01 and ran for nobody until the
owner's MacBook, away from home, saw the HP, the Dell and vps1 red — every office waited for a `DGO_RELAY`
line, and vps1 for keys pasted into `DGO_RELAY_FOR`. Asked here, with a herd file of its own and the real one:
an office of the herd takes `wss://<the hub's link host>/relay`, by its name or an alias, when its OWN key is
the one the file gives it; the hub joins the pairs of every other office, with the key its own record holds
(else the file's); an office that is not the herd's — a client's, on the same checkout, even one called by one
of our names — takes nothing; `.env` still overrides; a missing or broken file costs nothing and raises nothing.

Run: python3 apps/dgo-extend/tests/test_herd_relay.py   (app.py loaded as test_app_input loads it)
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
spec = importlib.util.spec_from_file_location("test_app_input", HERE / "test_app_input.py")
tai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tai)
app = tai.load()

FAIL: list[str] = []
#: The six tags vps1's carrier joined on 2026-11-05 (its carry.json, from the hand-written DGO_RELAY_FOR): the
#: three pairs of macbook, hp-laptop and the Dell, each in both orders.
VPS1_RUNS = ["2f89caed5c76", "71c60ea34589", "842cef8f1985", "974d58b9d259", "d3b52b1f28db", "efed8dd0487d"]
KEY = {"macbook": "+0B1Hc+7nYPESAjx/uu3JSDeuYQYadu7dvV0eb/C5B8=",
       "hp-laptop": "OUBWvxLVZJDWW19J9sZPePVPi3i1rickvdqcXagbbns=",
       "dell": "goMFvhsFv7EUbKsnI2PGwdBOnEFdhdIzMBBp8axs4Vg=",
       "vps1": "ka9qFHK11KwtSPR1MDftp9Kpd9yb8Y6rvmf2ESWLHgQ="}
OTHER = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="      # a valid key that is none of ours
HERD = """\
offices:
  macbook:
    label: MacBook
    wg_public_key: '%(macbook)s'
  hp-laptop:
    wg_public_key: '%(hp-laptop)s'
  dell:
    aliases: [portable-ubuntu, portable]
    wg_public_key: '%(dell)s'
  vps1:
    wg_public_key: '%(vps1)s'
    link_host: link.staging.digital-office.co.il
hub: vps1
""" % KEY


def check(cond, what):
    if not cond:
        FAIL.append(what)


def as_office(oid: str, key: str, herd_text: str | None = HERD, records: dict | None = None):
    """This office is `oid` with WireGuard key `key`; its herd file says `herd_text` (None = no file); its own
    records of other offices are `records` ({id: key})."""
    d = Path(tempfile.mkdtemp(prefix="dgo-herd-"))
    if herd_text is not None:
        (d / "herd.yaml").write_bytes(herd_text if isinstance(herd_text, bytes) else herd_text.encode("utf-8"))
    app.HERD_FILE = d / "herd.yaml"
    app.cv.home_office = lambda: {"id": oid, "identity": {"wg": key}}
    app.DECL_DIR.mkdir(parents=True, exist_ok=True)
    for f in app.DECL_DIR.glob("*.yaml"):
        f.unlink()
    for rid, rkey in (records or {}).items():
        (app.DECL_DIR / f"{rid}.yaml").write_text(f"id: {rid}\nkind: paired\nidentity:\n  wg: '{rkey}'\n")
    for k in ("DGO_RELAY", "DGO_RELAY_FOR"):
        os.environ.pop(k, None)


def main() -> int:
    relay = "wss://link.staging.digital-office.co.il/relay"

    as_office("hp-laptop", KEY["hp-laptop"])
    check(app._herd_relay() == relay, "an office of the herd takes the hub's relay")
    as_office("portable-ubuntu", KEY["dell"])
    check(app._herd_relay() == relay, "an office named by an alias (the Dell) takes it too")
    as_office("macbook", KEY["macbook"])
    check(app._herd_relay() == relay, "the MacBook takes it")
    check(app._relay_tags() == [], "an office that is not the hub joins nobody's pairs")

    as_office("vps1", KEY["vps1"])
    check(app._herd_relay() == "", "the hub is not its own relay")
    for_ = app._herd_relay_for()
    check(sorted(x.split("=", 1)[0] for x in for_) == ["dell", "hp-laptop", "macbook"],
          f"the hub joins every other office of the herd: {for_}")
    tags = [t[:12] for t in app._relay_tags()]
    check(tags == VPS1_RUNS, f"the herd file's keys give the tags vps1 joined by hand: {tags}")

    # the hub's own record of an office beats the file: the pair's real key is the one relayed
    as_office("vps1", KEY["vps1"], records={"portable-ubuntu": OTHER, "hp-laptop": KEY["hp-laptop"]})
    for_ = dict(x.split("=", 1) for x in app._herd_relay_for())
    check(for_.get("dell") == OTHER, f"the record's key (found by the alias) beats a stale file: {for_.get('dell')}")
    check(for_.get("hp-laptop") == KEY["hp-laptop"], "a record that agrees changes nothing")

    # BY KEY, NOT BY NAME: a client's machine called by one of our names is not ours
    as_office("portable", OTHER)
    check(app._herd_relay() == "" and app._relay_tags() == [], "a machine called `portable` with another key: nothing")
    as_office("vps1", OTHER)
    check(app._herd_relay_for() == [] and app._relay_tags() == [], "a machine called `vps1` with another key: no tags")
    as_office("hp-laptop", "")
    check(app._herd_relay() == "", "an office with no key of its own: nothing")

    as_office("examplef", OTHER)
    check(app._herd_relay() == "" and app._relay_tags() == [],
          "a client's office on the same checkout never takes our hub")

    as_office("hp-laptop", KEY["hp-laptop"])
    os.environ["DGO_RELAY"] = "wss://other.example.org/relay"
    check(app._carry_facts()["relay"] == "wss://other.example.org/relay", "a value in .env overrides the herd")
    os.environ.pop("DGO_RELAY")
    check(app._carry_facts()["relay"] == relay, "with nothing in .env the carrier plan gets the herd's relay")

    as_office("vps1", KEY["vps1"])
    os.environ["DGO_RELAY_FOR"] = f"hp-laptop={KEY['hp-laptop']},macbook={KEY['macbook']}"
    check(len(app._relay_tags()) == 2, "DGO_RELAY_FOR in .env overrides the herd (one pair, both orders)")
    os.environ.pop("DGO_RELAY_FOR")

    as_office("hp-laptop", KEY["hp-laptop"], HERD.replace("    link_host: link.staging.digital-office.co.il\n", ""))
    check(app._herd_relay() == "", "a hub with no link_host gives no relay (and says so in the log)")
    broken = {
        "no file": None,
        "offices not a map": "offices: just a string\nhub: vps1\n",
        "entries not maps": "offices:\n  hp-laptop: x\n  vps1: [a]\nhub: vps1\n",
        "not YAML": "offices: [\n",
        "a date YAML refuses": HERD + "since: 2026-11-31\n",
        "an int tag that is not one": HERD + "n: !!int x\n",
        "bytes that are not UTF-8": HERD.encode("utf-8") + b"\xff\xfe\n",
        "nesting too deep": "a: " + "[" * 5000 + "]" * 5000 + "\n",
    }
    for what, text in broken.items():
        as_office("hp-laptop", KEY["hp-laptop"], text)
        try:
            ok = app._herd_relay() == "" and app._relay_tags() == [] and app._carry_facts()["relay"] == ""
        except Exception as e:                              # noqa: BLE001 — the point is that nothing escapes
            ok = False
            what += f" (raised {type(e).__name__})"
        check(ok, f"a broken herd file ({what}): nothing derived, nothing raised")

    # THE REAL FILE: the herd as declared in git reproduces, on vps1, exactly what vps1 runs.
    real = (REPO / "apps" / "computers" / "herd.yaml").read_text(encoding="utf-8")
    as_office("vps1", KEY["vps1"], real)
    tags = [t[:12] for t in app._relay_tags()]
    check(tags == VPS1_RUNS, f"apps/computers/herd.yaml on vps1 gives the tags it runs: {tags}")
    as_office("portable-ubuntu", KEY["dell"], real)
    check(app._herd_relay() == relay, "apps/computers/herd.yaml gives the Dell the hub's relay")

    for f in FAIL:
        print("FAIL:", f)
    print("test_herd_relay:", "all passed" if not FAIL else f"{len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
