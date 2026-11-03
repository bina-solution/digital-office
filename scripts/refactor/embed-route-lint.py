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
# WHAT THE APP MUST READ. The shell hands the tail over as a PATH under the app's mount
# (`#/m/domains/d/x/records` arrives as `/a/domains/d/x/records`), so an app that only ever reads its
# own `location.hash` never sees the screen the link names — it opens the app and ignores the rest.
# Measured 2026-10-12 (round 10): `domains`, `sites` and `app-management` had NO reference to
# `location.pathname`/`document.baseURI` anywhere in their `static/*.js`, and the earlier, looser
# reading of this gate ("does it read and write its own URL") had passed all three because they do
# read their hash. A hash-routed app therefore has to translate the arriving path into its hash on
# load — and that translation is what this half of the gate asks for.
READS = re.compile(r"location\.(?:pathname|href)|document\.baseURI")
# `history.pushState(…)` and the bracket form a router with a replace/push choice writes
# (`history[replace ? "replaceState" : "pushState"]`) are the same act. The literal pattern missed
# the second one and read `apps/computers` as "keeps no screen in its URL" on 2026-10-12 while it
# plainly did — found by running this gate against the app right after converting it, which is what
# a gate is for.
WRITES = re.compile(r"history\.(?:push|replace)State|history\[[^\]]*(?:push|replace)State"
                    r"|location\.hash\s*=|location\.replace\(|location\.assign\(")

#: An app whose screen has no state to carry. Named with its reason — never a silent pass.
ALLOWED = {
    "apps/hello-bina": "a foreign image (caddy) answering one fixed sentence: there is no screen "
                       "inside it to address, and nothing to route",
    "platform-base/machine": "one LIVE dashboard and no selection to address: every number on it is "
                             "the host's current state (KPI tiles, sparklines, a containers grid), "
                             "and a link naming one container would point at a row the screen does "
                             "not select. Read 2026-10-12: nothing on this screen is a place a person "
                             "sends to another person. The allowance goes the moment it grows a "
                             "screen that selects something",
    "apps/bina-claude": "two streams of software this office does not draw (DGO-1074): the official "
                        "Claude Desktop app as video (Selkies) and Claude Code's terminal (ttyd). "
                        "What a person sees is pixels of a native app or characters of a TTY; the "
                        "state — which conversation, which project — lives inside that app, which "
                        "has no URL of its own to read or write. Its sessions are addressed through "
                        "the CLI instead (`./bbox bina-claude sessions|show <id>`)",
    "apps/cad": "FreeCAD's own window, streamed as pixels by linuxserver's KasmVNC image (DGO-1076): the "
                "model being edited lives inside FreeCAD, which has no URL of its own to read or write. "
                "The parametric families are addressed through cad-api and its CLI instead "
                "(`./bbox cad families|takeoff|model`)",
}

#: Apps whose SCREEN IS in their URL, in code this office does not own. Their front end is the
#: upstream image's (this repo holds a frame shim and patches, not a bundle), so the static probe
#: above finds nothing to read — and while the module is `external: true` the console hands the
#: tail to the app's OWN host and cannot read a cross-origin frame's navigations back
#: (`watchFrameRoute` returns on `!m.embed`, and reading another origin's `location.pathname`
#: throws: ai/context/build-your-first-app.md § "the address is the state" names exactly this as
#: the only case the rule does not cover).
#:
#: THE ALLOWANCE IS CONDITIONAL, and that is what keeps this declaration honest: it holds only
#: while the compiled module declares `external`. Mount one of these same-origin under
#: `/a/<alias>/` and the gate asks about it again — proven by the self-test, not promised here.
ALLOWED_WHILE_EXTERNAL = {
    "apps/meet": "the tile's own page is a redirect into Jitsi Meet on its own host — upstream's SPA, "
                 "which routes itself (a room IS its path, meet.<domain>/<room>, and that is the "
                 "link people send), and the one page this app owns, the recordings list, selects "
                 "nothing. It IS a screen on another host, so the allowance is conditional on that "
                 "being said: the module declares `external: true` on meet-start.<host> (2026-10-26, "
                 "the same block obsidian's and plane's carry), and mounting the module same-origin "
                 "under `/a/meet/` puts the question back to the static probe. Read 2026-10-20 "
                 "(DGO-826), made conditional 2026-10-26",
    "apps/obsidian": "the front end is Ignis (nobbe/ignis), which runs the REAL Obsidian: what this "
                     "repo holds is a frame shim, and the app is `external: true` on obsidian.<host>. "
                     "The screen IS in its URL — the image's own `shim-loader.js` reads "
                     "`new URLSearchParams(location.search)` for `file`, `vault` and `workspace` and "
                     "writes with `history.replaceState` (read from the served bundle 2026-10-26), and "
                     "the console hands the tail to that host, so `#/m/obsidian?file=<note>` opens the "
                     "note. What is impossible is the mirror back: a cross-origin frame's own "
                     "navigations cannot be read, so the console's address names the app while the "
                     "person is inside it. Read 2026-10-26",
    "apps/project-pln": "the front end is Plane's own SPA, upstream, in the app's image — this repo "
                        "holds its patches, Caddyfile and hooks, never its bundle — and the module is "
                        "`external: true` on plane.<host>. It routes itself and its screens ARE paths "
                        "on its own host: `/dgo/projects/<pid>/issues/<iid>/` is what "
                        "apps/project-pln/tasks.py prints as `app_link()`, and `console_link()` in the "
                        "same file already emits the office form "
                        "`#/m/plane/<ws>/projects/<pid>/issues/<iid>`, which the console frames onto "
                        "that host — so a work item is linkable both ways. The mirror back is the "
                        "same cross-origin impossibility as obsidian's. Read 2026-10-26",
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


def unrouted(rows: list[tuple[str, str]], external: frozenset[str] | set[str] = frozenset()) -> list[tuple[str, str]]:
    """(alias, directory) pairs that neither route by URL nor declare why they have nothing to route.

    `external` is the set of directories whose compiled module declares `external: true`: only
    those may claim ALLOWED_WHILE_EXTERNAL, because only there is the frame another origin the
    console cannot read.
    """
    out: list[tuple[str, str]] = []
    for alias, directory in rows:
        if routes_its_url(directory) or directory in ALLOWED:
            continue
        if directory in ALLOWED_WHILE_EXTERNAL and directory in external:
            continue
        out.append((alias, directory))
    return out


def main() -> int:
    if not REGISTRY.is_file():
        print("NOT CHECKED  nothing was compiled on this machine (.generated/registry/console.modules.yaml): "
              "an office that was never rendered has no tiles to answer for")
        return 0
    by_alias = apps_by_alias()
    rows: list[tuple[str, str]] = []
    external: set[str] = set()
    for module in modules():
        alias = (module.get("embed") or "").strip("/").split("/")[-1] or module.get("id", "")
        directory = by_alias.get(alias, "")
        if not directory:
            print(f"FAIL  {alias}: the compiled module names an embed no manifest declares "
                  f"(`module.alias: {alias}`) — the tile and the apps disagree")
            return 1
        rows.append((alias, directory))
        if module.get("external"):
            external.add(directory)

    if "--list" in sys.argv[1:]:
        for alias, directory in rows:
            state = "routes" if routes_its_url(directory) else ("allowed" if directory in ALLOWED else "NOTHING")
            if state == "NOTHING" and directory in ALLOWED_WHILE_EXTERNAL and directory in external:
                state = "allowed"
            print(f"  {alias:16} {directory:32} {state}")
    for alias, directory in rows:
        if directory in ALLOWED and not routes_its_url(directory):
            print(f"note  {alias} ({directory}) is allowed: {ALLOWED[directory]}")
        if directory in ALLOWED_WHILE_EXTERNAL and directory in external and not routes_its_url(directory):
            print(f"note  {alias} ({directory}) keeps its screen in its own URL upstream, and is "
                  f"allowed because its compiled module is external: {ALLOWED_WHILE_EXTERNAL[directory]}")

    bad = unrouted(rows, external)
    if bad:
        print(f"FAIL  {len(bad)} embedded app(s) do not keep their screen in their own URL, so their "
              f"screens cannot be linked, opened or sent: {', '.join(alias for alias, _ in bad)}")
        print("      The console mirrors the frame's URL verbatim (`#/m/<id><path>` is `/a/<alias><path>`),\n"
              "      so an app takes part by routing like any web app: read the route from your own URL on\n"
              "      load, write it back when the screen changes. See ai/context/build-your-first-app.md\n"
              "      § \"the address is the state\". A screen with no state of its own is named in this gate\n"
              "      with its reason, not left silent.")
        return 1
    named = [r for r in rows
             if (r[1] in ALLOWED) or (r[1] in ALLOWED_WHILE_EXTERNAL and r[1] in external)]
    print(f"G83 PASS — all {len(rows)} embedded app(s) keep their screen in their own URL"
          f" ({len(rows) - len(named)} routing, {len(named)} allowed by name)")
    return 0


def self_test() -> int:
    cases = [
        ("an app that routes by URL owes nothing", unrouted([("drive", "apps/drive")]), []),
        ("a named allowance owes nothing", unrouted([("hello-bina", "apps/hello-bina")]), []),
        ("a directory that neither routes nor is named is named",
         unrouted([("x", "scripts/refactor")]), [("x", "scripts/refactor")]),
        ("an upstream front end owes nothing while its module is external",
         unrouted([("obsidian", "apps/obsidian")], {"apps/obsidian"}), []),
        ("the same app is named again the moment it is no longer external",
         unrouted([("obsidian", "apps/obsidian")]), [("obsidian", "apps/obsidian")]),
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
