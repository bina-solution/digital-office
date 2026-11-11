#!/usr/bin/env python3
"""herd_enable_guard.py — `bbox apps enable` does not start, on one of the herd's offices, an app the herd runs
on ANOTHER office (DGO-579).

    DGO_GUARD_OFFICE=<this office's id> [DGO_GUARD_HERD=<its DGO_HERD>] \\
        python3 scripts/herd_enable_guard.py [--anyway] <app-id>…

The herd file (apps/computers/herd.yaml `apps:`) names, for each of its business apps, the ONE office that runs
it; the others reach it through their links. On 2026-10-14 an agent ran `bbox apps enable browser42` on vps1
while the herd's browser — every sign-in, in one profile — was the HP's: a second profile with none of them,
memory down to 174 MiB during the first WhatsApp sync, and two identical "office browser" tiles. So, read through
the same reader project-pln and domain-internic use (scripts/herd_home.py):
  * an office that is not one of the herd's — no word. It is the herd's when its id is one of the herd file's
    offices (by key or alias, any case) AND it does not declare another herd: an office whose `DGO_HERD` names
    a herd other than the file's own `herd:` is someone else's, whatever it is called (the public release ships
    this file, and `.env.ex` gives our ids as examples). An empty `DGO_HERD` says no herd, and an office that
    says none is counted in ours — `.env.ex`'s own rule. The herd file's test is the WireGuard key; that lives
    in dgo-extend's volume, which a CLI verb does not open on every call (second reader, DGO-579);
  * an app the herd does not place, or places on THIS office — no word;
  * an app already enabled here — no word: enabling it again changes nothing;
  * otherwise refused, naming the office that runs it. `--anyway` — the caller saying a second one is meant.
The office comes from the environment, never from argv: a `--office` typed after the app ids would otherwise
have chosen whose rule applies (second reader). Exit 0 = go on, 1 = refused (the reason on stdout), 2 = usage.
It reads; it writes nothing.
"""
from __future__ import annotations

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:      # once: app-management loads this file again when it changes, in a long-lived process
    sys.path.insert(0, _HERE)
import herd_home  # noqa: E402  (beside this file)

REPO = herd_home.REPO


def enabled_here(app: str, state_file: str) -> bool:
    """The app's own `apps:` entry says enabled — `{ state: enabled }` or the legacy `{ enabled: true }`."""
    try:
        text = open(state_file, encoding="utf-8").read()
    except OSError:
        return False
    m = re.search(r"^\s+" + re.escape(app) + r":\s*\{([^}]*)\}", text, re.M)
    body = m.group(1) if m else ""
    return bool(re.search(r"\bstate:\s*enabled\b", body) or re.search(r"\benabled:\s*true\b", body))


def herd_name(herd_file: str) -> str:
    """The herd file's own top-level `herd:` — the name its offices declare as `DGO_HERD`; "" when it gives none."""
    try:
        text = open(herd_file, encoding="utf-8").read()
    except OSError:
        return ""
    m = re.search(r"^herd:[ \t]*(['\"]?)([^'\"#\n]*?)\1[ \t]*(?:#.*)?$", text, re.M)
    return m.group(2).strip() if m else ""


def homes(me: str, declared: str = "", herd_file: str | None = None) -> dict:
    """{app: (office key, its label)} for every app the herd runs on ANOTHER office than this one — {} when this
    office is not one of the herd's. One read of the herd file, for a caller that asks about every app at once (the
    apps screen's catalog, app-management)."""
    herd_file = herd_file or os.path.join(REPO, "apps", "computers", "herd.yaml")
    offices, places = herd_home.herd(herd_file)
    me = (me or "").strip().lower()

    def names(o: str) -> set:
        # str(o): PyYAML reads an office key such as `no:` or `123:` as a bool or a number, and every office is
        # walked here — one such key must not take the guard down for every app of every office (DGO-579's reader)
        return {str(o).lower()} | {str(a).lower() for a in ((offices.get(o) or {}).get("aliases") or [])}

    def key(name: str) -> str:
        """The office a name points at — its key when it is a key or an alias, the name itself otherwise."""
        return next((o for o in offices if name.strip().lower() in names(o)), name)

    if not me or not any(me in names(o) for o in offices):
        return {}
    ours = herd_name(herd_file)
    if (declared or "").strip() and ours and declared.strip().casefold() != ours.casefold():
        return {}
    out = {}
    for app, there in places.items():
        if not isinstance(there, str) or not there.strip() or me in names(key(there)):
            continue
        k = key(there)
        out[str(app)] = (k, str((offices.get(k) or {}).get("label") or k))
    return out


def refusals(apps: list[str], me: str, declared: str = "", herd_file: str | None = None,
             state_file: str | None = None) -> list[str]:
    away = homes(me, declared, herd_file)
    out = []
    for app in apps:
        if app not in away or enabled_here(app, state_file or os.path.join(REPO, "platform.state.yaml")):
            continue
        out.append(f"{app}: the herd runs {app} on {away[app][0]} (apps/computers/herd.yaml, apps:) — this office "
                   f"reaches it through the link. To start a second one here on purpose: "
                   f"bbox apps enable --anyway {app}")
    return out


def main(argv: list[str]) -> int:
    apps, anyway = [], False
    for a in argv:
        if a == "--anyway":
            anyway = True
        elif a.startswith("-"):
            print(f"bbox apps enable: unknown option {a} (the one option is --anyway)")
            return 2
        else:
            apps.append(a)
    if not apps:
        print("usage: bbox apps enable [--anyway] <app-id>…")
        return 2
    if anyway:
        return 0
    lines = refusals(apps, os.environ.get("DGO_GUARD_OFFICE", ""), os.environ.get("DGO_GUARD_HERD", ""))
    for line in lines:
        print(line)
    return 1 if lines else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
