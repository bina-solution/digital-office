#!/usr/bin/env python3
"""herd_home.py — the address of an app that runs on a LINKED office: the copy the herd names, never a guess.

    python3 scripts/herd_home.py <app> [<office-id>]
        prints `<ours> <url>`: ours is 1 when <office-id> is one of this herd's offices (else -), and url is
        empty when no linked office's copy may be used (the reason goes to stderr)

The compiled registry (`.generated/registry/remote.<office>.<alias>.json`) lists what every linked office
publishes, and more than one office can publish the same app — ours, and a client's office we installed
and linked. Measured 2026-10-22: with fireplace linked, the first file alphabetically was the client's, and
every `tasks` call went to a Plane that does not know this office (HTTP 401). Measured 2026-11-03 from the
MacBook while the HP was rebuilding its catalog (its own `bbox run`): the HP's plane entry was gone,
fireplace's was the only one left, and `tasks` went to the client's Plane again. So:
  - the herd (apps/computers/herd.yaml `apps:`) names the office that runs each of ITS apps, and a registry
    file names an office by the id that office declares, which may be one of its `aliases:`;
  - on one of the herd's own offices, that office is the ONLY answer: while it does not publish the app,
    there is none;
  - an office that is not one of the herd's (a client's office runs the same checkout) keeps the first one,
    and no office guesses between two when the herd names neither.
Used by apps/project-pln/where.sh and apps/meet/hooks/prepare (MEET_PLANE_API_URL). PyYAML is not needed.
"""
import glob
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def by_hand(text):
    """The two blocks needed, read without PyYAML (the MacBook's python3 has none)."""
    d, block, office = {"offices": {}, "apps": {}}, None, None
    for ln in text.splitlines():
        s = ln.split("#", 1)[0].rstrip()
        if not s:
            continue
        if not s[0].isspace():
            block = s[:-1] if s.endswith(":") else None
            office = None
            continue
        m = re.match(r"^  ([A-Za-z0-9_.-]+):\s*(.*)$", s)
        if m and block == "offices":
            office = d["offices"].setdefault(m.group(1), {})
        elif m and block == "apps":
            d["apps"][m.group(1)] = m.group(2).strip("'\" ")
        elif office is not None:
            a = re.match(r"^    aliases:\s*\[(.*)\]$", s)
            if a:
                office["aliases"] = [x.strip().strip("'\"") for x in a.group(1).split(",") if x.strip()]
    return d


def herd(path):
    """The herd file's `offices:` (with their aliases) and `apps:` — by PyYAML when the host has it, else by hand."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {}, {}
    try:
        import yaml
        d = yaml.safe_load(text)
    except Exception:                         # no PyYAML here, or it cannot read the file: the same two blocks by hand
        d = None
    if not isinstance(d, dict):
        d = by_hand(text)
    offices = {k: v if isinstance(v, dict) else {} for k, v in (d.get("offices") or {}).items()} \
        if isinstance(d.get("offices"), dict) else {}
    apps = d.get("apps") if isinstance(d.get("apps"), dict) else {}
    return offices, apps


def home(app, me, registry=None, herd_file=None):
    """(ours, url, why): url is "" when no linked office's copy may be used, and why then says so."""
    registry = registry or os.path.join(REPO, ".generated", "registry")
    offices, apps = herd(herd_file or os.path.join(REPO, "apps", "computers", "herd.yaml"))

    def names(o):
        return {o} | {str(a) for a in ((offices.get(o) or {}).get("aliases") or [])}

    found = []
    for f in sorted(glob.glob(os.path.join(registry, "remote.*.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("app") == app:
            office = os.path.basename(f)[len("remote."):].split(".", 1)[0]
            found.append((office, "http://%s.%s:%s" % (d.get("alias"), office, d.get("link_port") or d.get("port"))))
    ours = bool(me) and any(me in names(o) for o in offices)
    want = str(apps.get(app) or "")
    homes = names(want) if want else set()
    there = ", ".join(o for o, _ in found)
    if want and ours and not any(o in homes for o, _ in found):
        if me in homes:                       # asked only when it is not running here (apps/project-pln/where.sh)
            why = "the herd runs %s on this office (%s), and it is not running here" % (app, want)
        else:
            why = ("the herd runs %s on %s (apps/computers/herd.yaml, apps:), and %s does not publish it right now "
                   "— its link is down or its catalog is being rebuilt" % (app, want, want))
        return ours, "", why + ("; never another office's (%s)" % there if found else "")
    if len(found) > 1 and not any(o in homes for o, _ in found):
        return ours, "", ("%d linked offices publish %s (%s) and the herd (apps/computers/herd.yaml, apps:) names "
                          "none of them" % (len(found), app, there))
    return ours, next((u for o, u in found if o in homes), found[0][1] if found else ""), ""


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    ours, url, why = home(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
    if why:
        sys.stderr.write("[%s] %s\n" % (sys.argv[1], why))
    print(("1" if ours else "-") + " " + url)
