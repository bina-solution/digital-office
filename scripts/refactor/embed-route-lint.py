#!/usr/bin/env python3
"""embed-route-lint — gate G83: every app the shell frames is addressable — its screen is in its URL.

    python3 scripts/refactor/embed-route-lint.py [--self-test] [--list]

WHY THIS EXISTS. The owner, 2026-10-12: «deeply understand that console link as state is required
feature from all apps so everything can be linkable open and shared quick», and then, when the first
cut asked every app to carry an office protocol: «אסור שזה תלוי בסריקות וקוד מורכב חייב פשוט לנתב
את כל מה שהקישור בפנימי של אפליקציות בברירת מחדל כדי שהנתיב תמיד יהיה הנתיב המלא שניתן לשתף ומוביל
לאותה נקודת מסך».

THE RULE, and there is only one: the tail of the console's hash and the app's own URL are the SAME
string under the app's mount — `#/m/drive/folder/5` is `/a/drive/folder/5`. The shell reads the
frame's own navigations (same origin; `watchFrameRoute` in platform-base/console/static/app.js, one
Navigation-API listener, no polling) and mirrors them into its own address with `replaceState`. So an
app needs NO protocol, NO block, NO message: it needs what every web app already has — a router that
puts the screen in the URL and reads it back on load.

WHAT IT ENFORCES. Every embedded module THIS OFFICE runs must read its own URL and write it:
`location.pathname|hash|href|search` / `document.baseURI` on one side, `history.pushState|
replaceState` or a hash write on the other. An app that neither reads nor writes its own URL has
screens nobody can link to: they exist only inside one browser tab.

THE NAMED ALLOWANCES are apps whose screen has no state of its own to carry (a foreign image that
answers one fixed sentence). Each is named here WITH its reason — a declaration, never a silent pass.

WHAT THIS GATE IS NOT. It is the static half: "does the app keep its screen in its URL". The
product half — "does every screen the inventory declares open at its own console path" — is the
runtime claim, measured per app in a browser (`ci-artifacts/route-contract/console-route-qa.py`) and
owed by the same work item.

AN OFFICE, NOT THE ESTATE. Only the modules this office compiled are asked about. Nothing compiled
here: NOT CHECKED, never a pass.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / ".generated" / "registry" / "console.modules.yaml"
SKIP_DIRS = {"node_modules", ".git", "__pycache__", "dist", "build", ".venv", "ci-artifacts", "tests", "test"}
FRONT_END = (".js", ".mjs", ".jsx", ".ts", ".tsx", ".html", ".vue", ".svelte")
READS = re.compile(r"location\.(?:pathname|hash|href|search)|document\.baseURI")
WRITES = re.compile(r"history\.(?:push|replace)State|location\.hash\s*=|location\.replace\(|location\.assign\(")

#: An app whose screen has no state to carry. Named with its reason — never a silent pass.
ALLOWED = {
    "apps/hello-bina": "a foreign image (caddy) answering one fixed sentence: there is no screen "
                       "inside it to address, and nothing to route",
}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def modules() -> list[dict]:
    import yaml
    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    mods = data.get("modules") if isinstance(data, dict) else data
    return [m for m in (mods or []) if m.get("embed") and not (m.get("remote") or m.get("office"))]


def apps_by_alias() -> dict[str, str]:
    """alias -> the app directory that serves it, read from the manifests (the only declaration)."""
    found: dict[str, str] = {}
    for base in ("apps", "platform-base"):
        for manifest in sorted((ROOT / base).glob("*/app.json")):
            try:
                app = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for route in app.get("routing") or []:
                module = route.get("module") or {}
                if module.get("alias"):
                    found[module["alias"]] = str(manifest.parent.relative_to(ROOT))
    return found


def routes_its_url(directory: str) -> bool:
    """Does this app's own front end read a route out of its URL and write one back?"""
    reads = writes = False
    for path in (ROOT / directory).rglob("*"):
        if path.suffix not in FRONT_END or any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        reads = reads or bool(READS.search(text))
        writes = writes or bool(WRITES.search(text))
        if reads and writes:
            return True
    return reads and writes


def unrouted(rows: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(alias, directory) pairs that neither route by URL nor declare why they have nothing to route."""
    return [(alias, directory) for alias, directory in rows
            if not routes_its_url(directory) and directory not in ALLOWED]


def main() -> int:
    if not REGISTRY.is_file():
        print("NOT CHECKED  nothing was compiled on this machine (.generated/registry/console.modules.yaml): "
              "an office that was never rendered has no tiles to answer for")
        return 0
    by_alias = apps_by_alias()
    rows: list[tuple[str, str]] = []
    for module in modules():
        alias = (module.get("embed") or "").strip("/").split("/")[-1] or module.get("id", "")
        directory = by_alias.get(alias, "")
        if not directory:
            print(f"FAIL  {alias}: the compiled module names an embed no manifest declares "
                  f"(`module.alias: {alias}`) — the tile and the apps disagree")
            return 1
        rows.append((alias, directory))

    if "--list" in sys.argv[1:]:
        for alias, directory in rows:
            state = "routes" if routes_its_url(directory) else ("allowed" if directory in ALLOWED else "NOTHING")
            print(f"  {alias:16} {directory:32} {state}")
    for alias, directory in rows:
        if directory in ALLOWED and not routes_its_url(directory):
            print(f"note  {alias} ({directory}) is allowed: {ALLOWED[directory]}")

    bad = unrouted(rows)
    if bad:
        print(f"FAIL  {len(bad)} embedded app(s) do not keep their screen in their own URL, so their "
              f"screens cannot be linked, opened or sent: {', '.join(alias for alias, _ in bad)}")
        print("      The console mirrors the frame's URL verbatim (`#/m/<id><path>` is `/a/<alias><path>`),\n"
              "      so an app takes part by routing like any web app: read the route from your own URL on\n"
              "      load, write it back when the screen changes. See ai/context/build-your-first-app.md\n"
              "      § \"the address is the state\". A screen with no state of its own is named in this gate\n"
              "      with its reason, not left silent.")
        return 1
    print(f"G83 PASS — all {len(rows)} embedded app(s) keep their screen in their own URL"
          f" ({len(rows) - len([r for r in rows if r[1] in ALLOWED])} routing, "
          f"{len([r for r in rows if r[1] in ALLOWED])} allowed by name)")
    return 0


def self_test() -> int:
    cases = [
        ("an app that routes by URL owes nothing", unrouted([("drive", "apps/drive")]), []),
        ("a named allowance owes nothing", unrouted([("hello-bina", "apps/hello-bina")]), []),
        ("a directory that neither routes nor is named is named",
         unrouted([("x", "scripts/refactor")]), [("x", "scripts/refactor")]),
    ]
    bad = 0
    for name, got, want in cases:
        ok = got == want
        bad += 0 if ok else 1
        print("  [%s] %s (got %r, want %r)" % ("ok " if ok else "FAIL", name, got, want))
    print("embed-route-lint self-test: %d/%d passed" % (len(cases) - bad, len(cases)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(self_test() if "--self-test" in sys.argv[1:] else main())
