#!/usr/bin/env python3
"""G33 app-coupling-lint — chassis must not know the apps it carries.

THE RULE. Layer 1 and 2 are the platform; layer 2 and 3 are things installed ON it. A chassis app
that names an installable app by id has inverted that: installing a new app now requires editing
the platform, and removing one leaves a dangling reference nothing checks. The platform is supposed
to learn what exists from app.json manifests, `platform.state.yaml` and the compiled registries in
.generated/ — never from a name written into its own source.

The concrete failure this exists to prevent: data-management (the backup service) discovered
postgres instances with a hardcoded table of logins — supabase_admin/postgres, hacohen/n8n,
authentik/authentik, glitchtip/glitchtip. Every entry was another app's private credential, so a
newly installed app with its own database was simply NOT BACKED UP until somebody remembered to add
a row. It now reads POSTGRES_USER from the container, which is both decoupled and more accurate.

WHAT IS NOT COUPLING. A layer-1 app id that is also the name of the technology it provides —
`postgres`, `redis` — appears in chassis code as a driver name, a client binary or an image hint.
That is a dependency on a storage technology, which a backup service cannot avoid having. Only
layer 2 and layer 3 ids are checked.

RATCHET, not retrofit. platform/app-coupling-waivers.yaml records the coupling that existed when
this gate was introduced, so the build is green today and NEW coupling fails. Each waiver is a
decision someone can revisit; deleting one and making the gate pass is always an improvement.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
ROOTS = ("apps", "platform-base")
SRC_GLOBS = ("**/*.py", "**/*.sh", "**/*.mjs", "**/*.js")
# Vendored trees and build output are not this repo's authorship.
SKIP_PARTS = {"node_modules", "dist", "build", "vendor", ".venv", "__pycache__", "webapp"}


def load_yaml(p):
    try:
        import yaml
    except ImportError:
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:                                     # noqa: BLE001
        return {}


def catalog():
    out = {}
    for root in ROOTS:
        base = REPO / root
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            man = d / "app.json"
            if not man.is_file():
                continue
            try:
                m = json.loads(man.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            out[m.get("id") or d.name] = {"dir": d, "layer": m.get("layer")}
    return out


def strip_comment(path, line):
    """Comments and docstrings EXPLAIN coupling; they do not create it. Naming an app in a comment
    that says why something is the way it is is exactly the documentation this repo wants."""
    if path.suffix in (".py", ".sh"):
        return line.split("#", 1)[0]
    if path.suffix in (".js", ".mjs"):
        return line.split("//", 1)[0]
    return line


def main():
    apps = catalog()
    targets = {a for a, v in apps.items() if v["layer"] in (2, 3)}
    waivers = load_yaml(REPO / "platform/app-coupling-waivers.yaml")

    found = {}
    for aid, v in apps.items():
        if v["layer"] not in (1, 2):
            continue
        waived = set(waivers.get(aid) or [])
        for pat in SRC_GLOBS:
            for f in v["dir"].glob(pat):
                if SKIP_PARTS & set(f.parts):
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for n, line in enumerate(text.splitlines(), 1):
                    code = strip_comment(f, line)
                    for t in targets:
                        if t == aid or t in waived:
                            continue
                        if re.search(r"[\"']" + re.escape(t) + r"[\"']", code):
                            found.setdefault((aid, t), []).append(
                                f"{f.relative_to(REPO).as_posix()}:{n}")

    if not found:
        n = sum(1 for v in apps.values() if v["layer"] in (1, 2))
        print(f"G33 PASS — {n} chassis app(s) name no layer-2/3 app")
        return 0

    print(f"G33 FAIL — {len(found)} new chassis->app coupling(s):")
    for (aid, t), where in sorted(found.items()):
        print(f"  {aid} references '{t}'  ({len(where)}x)  e.g. {where[0]}")
    print("  -> resolve it from the manifests/registries instead, or record the decision in")
    print("     platform/app-coupling-waivers.yaml with a reason.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
