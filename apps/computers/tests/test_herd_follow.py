#!/usr/bin/env python3
"""test_herd_follow — `bbox computers herd` says whether each office takes dgo-stable by itself (DGO-1838).

The Dell never followed and nobody saw it: it kept link code from before the herd's withholding and served the public
hub every app it had (issues/an-office-that-does-not-follow-…yaml). Then, when it did run a follow, every cycle was
skipped on load all night, with a fresh last cycle and no other sign. The herd check now reads each office's follow
(a linked office's from its machine overview, this office's from its state file) and counts as a difference an office
that does not follow, whose follow stopped, is blocked or failed, or that has not been up to date for a day.

Needs PyYAML (herd_map reads herd.yaml). Run: python3 tests/test_herd_follow.py   (from apps/computers)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import herd_map as hm  # noqa: E402

FAIL: list[str] = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


READ_AT = "2026-11-13 01:30 UTC"
NOW = hm._epoch(READ_AT)
H = 3600

# vps1's own state file at 01:03Z on 2026-11-13, the keys it carries beyond the four read here left in
VPS1 = """WHY=
TAKING_WHAT=dgo-stable
VERIFIED=75856788e4faaf2c99516d31cbb41e3d79a66612
TAKING=
CURRENT_EPOCH=1794522257
FAILED_TARGET=
LAST_AT=2026-11-13 01:03:31 UTC
LAST_RESULT=blocked
LAST_DETAIL=local changes in apps/examplex/static/examplex.js
"""


def remote(follow, **extra) -> dict:
    return {"label": "x", "overview": {"containers": [], "follow": follow, **extra}}


def stamp(seconds_ago: float) -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(NOW - seconds_ago))


def main() -> int:
    # the state file, read with the overview's keys
    s = hm.follow_state_of(VPS1)
    check(s == {"at": "2026-11-13 01:03:31 UTC", "result": "blocked", "detail": "local changes in apps/examplex/static/examplex.js",
                "current_epoch": "1794522257"}, f"vps1's file → the overview's four keys, empty ones left out: {s}")
    check(hm.follow_state_of(None) is None, "no file: None")
    check(hm.follow_state_of("WHY=\nnot a pair\n") is None, "a file with nothing read here: None")
    check(hm._epoch("2026-11-13 01:03:31 UTC") == 1794531811.0, "LAST_AT's own form is read")
    check(hm._epoch("1794522257") == 1794522257.0 and hm._epoch("") is None and hm._epoch("soon") is None,
          "an epoch is read; nothing and words are not")

    f = hm.follow_of
    # does not follow at all — the Dell until 2026-11-13, and the MacBook
    r = f({"local": True, "follow_state": None}, NOW)
    check(not r["ok"] and r["line"].startswith("DOES NOT FOLLOW"), f"this office with no state file: {r}")
    r = f(remote(None), NOW)
    check(not r["ok"] and r["line"].startswith("DOES NOT FOLLOW"), f"a linked office whose machine says none: {r}")
    r = f({"label": "x", "overview": {"containers": []}}, NOW)
    check(not r["ok"] and r["line"].startswith("FOLLOW UNREAD"), f"a machine older than the field says nothing: {r}")

    # follows, and is where it should be
    r = f(remote({"at": stamp(10 * 60), "result": "current", "detail": "dgo-stable green at 4a298932 is in vps1-dgo"}), NOW)
    check(r["ok"] and r["line"].startswith("follow ") and "4a298932" in r["line"], f"current ten minutes ago: {r}")
    r = f(remote({"at": stamp(5 * 60), "result": "took", "current_epoch": str(int(NOW - 5 * 60))}), NOW)
    check(r["ok"], f"took five minutes ago: {r}")

    # follows, and is not
    r = f({"local": True, "follow_state": VPS1}, NOW)
    check(not r["ok"] and r["line"].startswith("FOLLOW BLOCKED") and "examplex.js" in r["line"],
          f"blocked 27 minutes ago, the reason said: {r}")
    r = f(remote({"at": stamp(H), "result": "failed", "detail": "unhealthy: n8n"}), NOW)
    check(not r["ok"] and r["line"].startswith("FOLLOW FAILED") and "n8n" in r["line"], f"failed: {r}")
    r = f(remote({"at": stamp(7 * H), "result": "current"}), NOW)
    check(not r["ok"] and r["line"].startswith("FOLLOW SILENT") and "7 h" in r["line"], f"no cycle for seven hours: {r}")
    r = f(remote({"result": "current"}), NOW)
    check(not r["ok"] and r["line"].startswith("FOLLOW SILENT") and "ever" in r["line"], f"a state with no time: {r}")
    # two hours with no cycle and no take open: the follow stopped — the Dell 2026-11-13, its follow-runner declared and
    # never created, its last line the take of 04:45Z while two batches went green after it
    dell_took = {"result": "took", "detail": "dgo-stable 43d533c1f into dell-dgo, healthy"}
    r = f(remote({"at": stamp(2 * H + 10 * 60), **dell_took}), NOW)
    check(not r["ok"] and r["line"].startswith("FOLLOW SILENT") and "130 min" in r["line"] and "43d533c1f" in r["line"]
          and "a take open" not in r["line"], f"no cycle for 2 h 10 min, no take open, said in minutes: {r}")
    r = f(remote({"at": stamp(2 * H - 60), **dell_took}), NOW)
    check(r["ok"], f"119 minutes: a laptop's first cycle after a wake, one dropped line — not yet a stop: {r}")
    r = f(remote({"at": stamp(2 * H + 60), **dell_took}), NOW)
    check(not r["ok"] and r["line"].startswith("FOLLOW SILENT"), f"121 minutes: a stop: {r}")
    # the machine serves an empty TAKING as null (platform-base/machine/app.py): no take open
    r = f(remote({"at": stamp(2 * H + 60), "taking": None, **dell_took}), NOW)
    check(not r["ok"] and "a take open" not in r["line"], f"taking: null is no take: {r}")
    # a take writes its line only when it ends: its 6 h bound counts from the cycle's start, up to a cycle after the
    # last line — so 8 h from that line
    taking = {"result": "current", "taking": "1e9a1eceb 97ef6a3f1"}
    r = f(remote({"at": stamp(8 * H - 60), **taking}), NOW)
    check(r["ok"], f"7 h 59 min with a take open: still inside its bound: {r}")
    r = f(remote({"at": stamp(8 * H + 60), **taking}), NOW)
    check(not r["ok"] and r["line"].startswith("FOLLOW SILENT") and "a take open" in r["line"],
          f"8 h 1 min with a take open: past its bound: {r}")
    r = f({"local": True, "follow_state": f"LAST_AT={stamp(3 * H)}\nLAST_RESULT=current\nTAKING=1e9a1eceb 97ef6a3f1\n"}, NOW)
    check(r["ok"], f"…the take read from this office's own state file too: {r}")
    r = f({"local": True, "follow_state": f"LAST_AT={stamp(3 * H)}\nLAST_RESULT=current\nTAKING=\n"}, NOW)
    check(not r["ok"] and r["line"].startswith("FOLLOW SILENT"), f"…and an empty TAKING= there is no take: {r}")

    # a failed take is said once as `failed`; the cycles after it say `waiting` or `skipped` while its target stays set
    # (the second reader: these read as healthy until BEHIND, up to a day later)
    stuck = {"failed_target": "4a2989323a892c80bf189a2c3356a490b19fef64", "failed_at": "2026-11-13 00:31:02 UTC",
             "current_epoch": str(int(NOW - 2 * H))}
    r = f(remote({"at": stamp(60), "result": "waiting", "detail": "dgo-stable 4a298932 failed at 2026-11-13 00:31:02 UTC; "
                  "waiting for a newer one", **stuck}), NOW)
    check(not r["ok"] and r["line"].startswith("FOLLOW FAILED") and "4a2989323 failed at 2026-11-13 00:31:02 UTC" in r["line"],
          f"waiting on a failed target, an hour after it failed: {r}")
    r = f(remote({"at": stamp(60), "result": "skipped", "detail": "load 5.1 on 4 CPU(s)", **stuck}), NOW)
    check(not r["ok"] and r["line"].startswith("FOLLOW FAILED"), f"skipped on load with a failed target still set: {r}")
    r = f({"local": True, "follow_state": VPS1.replace("FAILED_TARGET=", "FAILED_TARGET=4a2989323a89")
           .replace("LAST_RESULT=blocked", "LAST_RESULT=waiting")}, NOW)
    check(not r["ok"] and r["line"].startswith("FOLLOW FAILED"), f"…read from this office's own state file too: {r}")

    # an office updated by hand ON PURPOSE (herd.yaml `follow: by-hand`, the MacBook) is said, not counted
    r = f({"local": True, "follow_state": None}, NOW, "by-hand")
    check(r["ok"] and "by hand" in r["line"], f"declared by hand, no state: {r}")
    r = f(remote({"at": stamp(60), "result": "blocked", "detail": "x"}), NOW, "by-hand")
    check(not r["ok"] and r["line"].startswith("FOLLOW BLOCKED"), f"declared by hand but a follow runs: judged as one: {r}")
    r = f({"label": "x", "overview": {"containers": []}}, NOW, "by-hand")
    check(r["ok"], f"declared by hand, a machine older than the field: nothing to read, nothing owed: {r}")

    # skipped every cycle: fine for a night, a difference after a day
    dell = {"at": stamp(20 * 60), "result": "skipped", "detail": "load 4.63 on 4 CPU(s)"}
    r = f(remote({**dell, "current_epoch": str(int(NOW - 13 * H))}), NOW)
    check(r["ok"] and "load 4.63" in r["line"], f"skipped, up to date 13 h ago: {r}")
    r = f(remote({**dell, "current_epoch": str(int(NOW - 30 * H))}), NOW)
    check(not r["ok"] and r["line"].startswith("BEHIND") and "30 h" in r["line"] and "load 4.63" in r["line"],
          f"skipped, up to date 30 h ago: {r}")
    r = f(remote({**dell, "current_epoch": str(int(NOW - 3 * 86400))}), NOW)
    check(not r["ok"] and "3.0 days" in r["line"], f"three days behind is said in days: {r}")
    r = f(remote(dell), NOW)
    check(r["ok"], f"skipped, from a machine that does not say when it was up to date: no guess: {r}")

    # the herd: each office's line on the page, and one difference for each office that does not take green
    target = hm.Target({"offices": {"vps1": {"label": "vps1"}, "dell": {"label": "Dell", "aliases": ["portable-ubuntu"]}}})
    namer = hm.Namer({}, {}, {}, {}, {})
    bundle = {"self": "vps1", "read_at": READ_AT, "offices": {
        "vps1": {"local": True, "inspect": [], "df": {}, "follow_state": VPS1.replace("blocked", "current")},
        "portable-ubuntu": remote({**dell, "current_epoch": str(int(NOW - 30 * H))})}}
    res = hm.compare(bundle, target, namer)
    check(res["offices"]["vps1"]["follow"]["ok"], "vps1, current: no difference")
    check(not res["offices"]["dell"]["follow"]["ok"], "the Dell, by its link id, behind: a difference")
    check(res["drift"] == 1, f"exactly one difference, the Dell's: {res['drift']}")
    page = hm.render(res, target, bundle)
    check("   follow           current at 2026-11-13 01:03:31 UTC" in page and "   BEHIND           last up to date 30 h" in page,
          "the page says each office's follow on its own line")
    bundle["offices"]["vps1"]["follow_state"] = None
    check(hm.compare(bundle, target, namer)["drift"] == 2, "an office with no follow is one more difference")
    target.offices["vps1"]["follow"] = "by-hand"
    check(hm.compare(bundle, target, namer)["drift"] == 1, "…unless herd.yaml declares it by hand")
    real = hm.Target(hm.yaml.safe_load(hm.TARGET.read_text(encoding="utf-8")))
    check([k for k, o in real.offices.items() if (o or {}).get("follow")] == ["macbook"]
          and real.offices["macbook"]["follow"] == "by-hand", "in the real herd.yaml only the MacBook is by hand")

    print("test_herd_follow: all passed" if not FAIL else f"test_herd_follow: {len(FAIL)} failure(s)")
    for what in FAIL:
        print("  FAIL", what)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
