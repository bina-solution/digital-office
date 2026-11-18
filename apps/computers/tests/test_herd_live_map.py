#!/usr/bin/env python3
"""test_herd_live_map — `bbox computers map` answers with the network as it is, from what was read, and from no file
of the repository (DGO-1960).

The owner (2026-11-17): the context of an installation is built live from the real data, «I run a command and I get
the whole map of the network», never written into the repository. The map is the herd's own reads — this office's
engine, each linked office's machine, and the links as dgo-extend measures them — answered as they are. Every name
here is made up: the map must not need ours.

Needs PyYAML (herd_map imports it). Run: python3 tests/test_herd_live_map.py   (from apps/computers)
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


NAMER = hm.Namer({"console": {}, "drive": {}, "mail": {}}, {"console": "console", "drive": "drive", "mail": "mail"},
                 {}, {}, {})


def ctr(name, service, project, running=True):
    return {"Name": "/" + name, "Config": {"Image": f"example/{service}:1",
            "Labels": {"com.docker.compose.service": service, "com.docker.compose.project": project}},
            "State": {"Status": "running" if running else "exited"}, "Mounts": []}


BUNDLE = {
    "self": "office-a", "read_at": "2026-11-17 19:20 UTC",
    "offices": {
        "office-a": {"local": True, "df": {},
                     "inspect": [ctr("console-a", "console", "acme"), ctr("drive-a", "drive", "acme"),
                                 ctr("mail-a", "mail", "acme", running=False), ctr("old-x", "console", "olddeploy")],
                     "follow_state": None},
        "office-b": {"label": "Office B", "error": "the machine did not answer"},
    },
    "links": {"items": [
        {"office": "office-b", "label": "Office B", "state": "up", "transport": "tcp", "endpoint": "10.0.0.2",
         "direction": "both", "commit": "abcdef1234567", "apps": ["console", "drive"], "verdict": {"ok": True},
         "carry": {"state": "up", "via": "10.0.0.2:51443", "rtt_ms": 4.25, "heard_s": 0}},
        {"office": "office-c", "label": "Office C", "state": "down", "transport": "udp", "endpoint": "10.0.0.3",
         "direction": "serve", "apps": [], "verdict": {"ok": False, "why": "the tunnel carries nothing"}},
    ]},
}

m = hm.live_map(BUNDLE, NAMER)
offices = m["offices"]

# every office the reads or the links name is on the map — one the link names and no machine answered for, too
check(set(offices) == {"office-a", "office-b", "office-c"}, f"offices: {sorted(offices)}")

a = offices["office-a"]
check(a["this_office"] and a["project"] == "acme", f"this office: {a}")
check(a["runs"] == ["console", "drive"] and a["stopped"] == ["mail"], f"runs/stopped: {a['runs']} / {a['stopped']}")
check(a["other_deployments"] == ["olddeploy"], f"another deployment on the machine: {a['other_deployments']}")
check("DOES NOT FOLLOW" in a["follow"], f"this office's follow, none read: {a['follow']}")

b = offices["office-b"]
check(b["link"]["state"] == "up" and b["link"]["carry"]["rtt_ms"] == 4.25 and b["link"]["publishes"] == 2,
      f"office-b's link: {b['link']}")
check(b["error"] == "the machine did not answer", f"office-b not read: {b.get('error')}")

c = offices["office-c"]
check(c["link"]["state"] == "down" and c["link"]["why"] == "the tunnel carries nothing", f"office-c: {c}")
check("no machine answered" in c["error"], f"office-c, only the link knows it: {c.get('error')}")

page = hm.render_map(m)
check(page.splitlines()[2].startswith("== office-a (office-a) — this office"), "this office comes first:\n" + page)
check("carry up via 10.0.0.2:51443, rtt 4.2 ms" in page or "rtt 4.3 ms" in page, "the carry's round trip:\n" + page)
check("runs     console, drive" in page and "stopped  mail" in page, "what runs and what does not:\n" + page)
check("not read: the machine did not answer" in page, "an office that was not read says so:\n" + page)
check("the tunnel carries nothing" in page, "a link that is not ok says why:\n" + page)

# a link read that failed (dgo-extend off, or no answer) is said — never shown as an office with no links
check(m["links_read"] and "links: NOT READ" not in page, "links that were read are not called unread:\n" + page)
unread = hm.render_map(hm.live_map({**BUNDLE, "links": {}}, NAMER))
check("links: NOT READ" in unread, "a failed link read is said:\n" + unread)

# no target: the map reads nothing from herd.yaml — a bundle and a namer are all it takes
check("herd.yaml" not in page and "target" not in page, "the map never answers with the declaration:\n" + page)

# the hook passes --map, and the map is answered before any comparison (exit 0, not the drift count)
src = (Path(__file__).resolve().parents[1] / "tools" / "herd_map.py").read_text(encoding="utf-8")
check('if "--map" in argv:' in src and "return 0" in src.split('if "--map" in argv:')[1].split("res = compare")[0],
      "main answers the map before the comparison")

if FAIL:
    print("FAIL test_herd_live_map:\n  " + "\n  ".join(FAIL))
    sys.exit(1)
print("ok test_herd_live_map: the network map answers from what was read, with made-up names and no target")
