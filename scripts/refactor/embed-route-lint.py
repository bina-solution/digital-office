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

A LINKED OFFICE'S TILES TOO (DGO-569, the owner: «הדפדפן גם תומך בתת קישורים … ככה אני אוכל לפתוח את
הקישור מכל מקום בשנייה»). A tile another office gives (`remote` in the compiled module) was skipped
outright, so the deep link into it — `#/m/browser42.hp-laptop/view/`, handed to that office's host —
was a contract nobody checked. Its app is the same app, from the same tree, so it is asked the same
question by the alias the far office names (`remote.alias`). STAGED, as every tightening is: a remote
tile that does not keep its screen in its URL is a WARN now, and the gate refuses it once the warnings
of every office have been read (AGENTS.md, non-negotiable 8). A tile whose app is not in this tree (a
client's own app) is said by name, never passed in silence.
"""
from __future__ import annotations

import functools
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
    "apps/browser42": "ONE live screen — the office browser's, as pixels (noVNC): which tab, which page is the "
                      "browser's own state, not the viewer's. Its addresses are SERVER paths the app's Caddyfile "
                      "routes, so the tail of a link lands with no router in the page: `/view/` the screen, "
                      "`/handoff/<slug>` a group's tab brought to the front and then the screen (handoff.py). "
                      "The page reads its query (`?lost=<slug>`), never a path. Read 2026-11-10 (DGO-569)",
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
#: (apps/meet was named here until 2026-11-09: its tile was a redirect into Jitsi. Its tile is «פגישות»
#: now, meet-start's own page, which reads and writes its own URL, so it is mounted same-origin again
#: and the static probe answers for it — DGO-1502.)
ALLOWED_WHILE_EXTERNAL = {
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


def is_remote(module: dict) -> bool:
    return bool(module.get("remote") or module.get("office"))


def modules(remote: bool = False) -> list[dict]:
    """The embedded modules this office compiled: its own, or (`remote`) the tiles its linked offices give."""
    import yaml
    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    mods = data.get("modules") if isinstance(data, dict) else data
    return [m for m in (mods or []) if m.get("embed") and is_remote(m) == remote]


def remote_alias(module: dict) -> str:
    """The alias of the app a linked office's tile is: the far office names it (`remote.alias`); the
    embed's last segment is the same name when it does not."""
    far = module.get("remote") if isinstance(module.get("remote"), dict) else {}
    return far.get("alias") or (module.get("embed") or "").strip("/").split("/")[-1]


def remote_rows(mods: list[dict], by_alias: dict[str, str]) -> tuple[list[tuple[str, str]], list[str], set[str]]:
    """(tile id, directory) for every linked office's tile whose app is in this tree; the ids of those whose
    app is not; and the directories whose tile is `external` (another origin: the mirror back is impossible)."""
    rows, absent, external = [], [], set()
    for module in mods:
        directory = by_alias.get(remote_alias(module), "")
        if not directory:
            absent.append(module.get("id", ""))
            continue
        rows.append((module.get("id", ""), directory))
        if module.get("external"):
            external.add(directory)
    return rows, absent, external


def apps_by_alias() -> dict[str, str]:
    """alias -> the app directory that serves it, read from the manifests (the only declaration)."""
    found: dict[str, str] = {}
    # instances/: an app's further copies (DGO-1920), generated per office — each declares its own tile
    for base in ("apps", "platform-base", "instances"):
        for manifest in sorted((ROOT / base).glob("*/app.json")):
            try:
                app = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            # a copy's screen is its template's: judged (and allowed) by the template's own folder
            home = manifest.parent
            of = app.get("instance_of")
            if base == "instances" and isinstance(of, str):
                home = next((ROOT / b / of for b in ("apps", "platform-base") if (ROOT / b / of / "app.json").is_file()),
                            home)
            for route in app.get("routing") or []:
                module = route.get("module") or {}
                if module.get("alias"):
                    found[module["alias"]] = str(home.relative_to(ROOT))
    return found


@functools.lru_cache(maxsize=None)   # one walk per app directory: 58 remote tiles name a dozen of them again and again
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

    # the linked offices' tiles (DGO-569) — WARN, not yet refuse: see the module's docstring
    far, absent, far_external = remote_rows(modules(remote=True), by_alias)
    far_bad = unrouted(far, far_external)
    for tile, directory in far_bad:
        print(f"WARN  {tile}: a linked office's tile whose app ({directory}) does not keep its screen in its "
              f"own URL — a link into it opens the app and loses the screen (refused once this stage ends)")
    for tile in absent:
        print(f"note  {tile}: a linked office's tile whose app is not in this tree — not checked here")
    far_named = [r for r in far if r not in far_bad and not routes_its_url(r[1])]
    print(f"G83 remote — {len(far) + len(absent)} linked office tile(s): {len(far) - len(far_bad) - len(far_named)} "
          f"routing, {len(far_named)} allowed by name, {len(far_bad)} warned, {len(absent)} not in this tree")
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
        # DGO-569: a linked office's tile is counted, by the alias the far office names
        ("a linked office's tile is asked about its app, found by the far office's alias",
         remote_rows([{"id": "browser42.hp-laptop", "embed": "/a/browser42/", "external": True,
                       "remote": {"alias": "browser42"}}], {"browser42": "apps/browser42"}),
         ([("browser42.hp-laptop", "apps/browser42")], [], {"apps/browser42"})),
        ("…and one whose app is not in this tree is named, never passed",
         remote_rows([{"id": "x.examplef", "embed": "/a/x/", "remote": {"alias": "x"}}], {}),
         ([], ["x.examplef"], set())),
        ("a remote tile is not one of this office's own, and an own tile is not remote",
         (is_remote({"remote": {"alias": "a"}}), is_remote({"office": "hp-laptop"}), is_remote({"id": "drive"})),
         (True, True, False)),
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
