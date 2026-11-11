#!/usr/bin/env python3
"""wrapped-app-lint — gate G108: a wrapped official app keeps the four channels (DGO-1266, cli-502 / cli-204).

    python3 scripts/refactor/wrapped-app-lint.py
    python3 scripts/refactor/wrapped-app-lint.py --self-test

WHY. The office's pattern for an outside product is to WRAP the vendor's own client (plans/dgo-cli.yaml,
decision 6; ai/context/app-cli-api-standard.md §6). bina-claude streams Claude Desktop and drives the
Claude Code CLI behind agent.v1. The catalogue of the next ones (DGO-1265) is Telegram, Obsidian, Signal,
Slack, Discord and Element. A wrap that brings only the vendor's screen is a remote desktop, not an app
of the office: the agents and automations cannot reach it. The plan's rule: «כל עטיפה חדשה עוברת את
ה-gate לפני שהיא נכנסת לקטלוג». This is that gate.

WHAT IT CHECKS. Every app whose app.json declares `wraps` (platform/schema/app.schema.json) has the four
channels of build-your-first-app.md. Channels other than the screen are also read in the app named by
`wraps.headless_app` (cad's are cad-api's). The definitions are the app standard's
(scripts/app-standard/measure.py), not a second set:
  screen  a `routing[]` entry with a console `module`
  cli     a verb of its own in hooks/ (by name, as bbox's `app_verbs` lists them): the platform's lifecycle
          hooks (measure.py's committed `lifecycle_verbs`, inventory.json) and `flow` do not count
  api     a door another app or an agent calls: a capability with an `endpoint` or an `interface`, or
          `/api/…` route literals in the app's own source (measure.py's `api` column)
  flow    hooks/flow, the event stream (G72 proves a `hooks/flow` really publishes)
A missing channel FAILS, unless it is in KNOWN with why. KNOWN is debt, not permission: a pair may not
join it, and one that is no longer missing fails until its line goes (the list only shrinks).

A vendor that publishes NO headless side (Signal: its only CLI, signal-cli, is third-party) is not debt but
a fact of the product, and the manifest says so where the schema puts it: `wraps.headless` is
`none: <why>` (or `none — <why>`). Such a wrap owes the screen and the CLI; the API and the flow, which
would sit on the headless side, are not asked of it (a note says so). It FAILS when the claim gives no
reason, names a `headless_app` beside it, or sits on an app that has an api channel (then it has a
headless side, and the claim would hide its missing flow).

It also fails, by name:
- a `wraps` that is not an object, has no `client`, or carries a key the schema does not name (the
  compilers check nested keys of no object, so a typo here would otherwise drop the headless side in
  silence);
- an app.json that does not parse;
- a scan that finds no wrapped app, because then it read nothing.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

# It prints Hebrew (G10): python on Windows writes it in the console's codepage and dies on its own output.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]

#: (app, channel) → why it is missing today. Remove a line when the channel lands.
KNOWN = {
    ("bina-claude", "flow"): "agent.v1 sessions do not publish dgo:flow:bina-claude yet; the adapter's events "
                             "go to its own clients only",
    ("cad", "flow"): "neither cad nor cad-api publishes an event stream",
}
CHANNELS = ("screen", "cli", "api", "flow")
HEADLESS_CHANNELS = ("api", "flow")            # what sits on the vendor's headless side
WRAPS_KEYS = {"client", "headless", "headless_app"}
# `wraps.headless` that declares the vendor has none: "none: why" or "none — why" (a hyphen only with spaces
# round it, so «none-cli» is a NAME). Bare "none" is a claim with no reason, and is refused as such.
NO_HEADLESS = re.compile(r"none(\s*[:—–]\s*\S.*|\s+-\s+\S.*)?", re.IGNORECASE | re.DOTALL)
# measure.py's ROUTE (scripts/app-standard): a quoted `/api/…` literal in the app's own source
ROUTE = re.compile(r"""["'`](/api/[A-Za-z0-9_\-./]+)""")
SOURCE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go"}
SKIP_DIRS = {"node_modules", "vendor", "dist", "build", "__pycache__", ".git", "tests", "test"}
TEST_FILE = re.compile(r"^test_.*|_test\.(py|go)$|\.test\.(m?js|ts)$")


def lifecycle(root: Path) -> set[str]:
    """measure.py's committed list of the hooks the platform runs on every app, plus `flow` (its own channel)."""
    try:
        got = json.loads((root / "scripts" / "app-standard" / "inventory.json").read_text(encoding="utf-8"))
        return set(got.get("lifecycle_verbs") or []) | {"flow"}
    except (OSError, ValueError):
        return {"backup", "facts", "onboard", "prepare", "refresh", "rename-address", "restore", "self-update",
                "test", "uninstall", "verify", "flow"}


def manifests(root: Path, fail: list) -> dict[str, tuple[Path, dict]]:
    out = {}
    for layer in ("apps", "platform-base"):
        for f in sorted((root / layer).glob("*/app.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                fail.append(f"{f.relative_to(root)}: does not parse ({e.__class__.__name__}) — no app is checked blind")
                continue
            if isinstance(d, dict) and d.get("id"):
                out[d["id"]] = (f.parent, d)
    return out


def verbs(app_dir: Path, skip: set) -> list[str]:
    h = app_dir / "hooks"
    names = {re.sub(r"\.(py|mjs|sh)$", "", p.name) for p in h.iterdir() if p.is_file()} if h.is_dir() else set()
    return sorted(names - skip)


def routes(app_dir: Path) -> bool:
    for f in app_dir.rglob("*"):
        if (f.suffix in SOURCE_EXT and f.is_file() and not TEST_FILE.search(f.name)
                and not SKIP_DIRS & set(f.relative_to(app_dir).parts[:-1])):
            try:
                if ROUTE.search(f.read_text(encoding="utf-8", errors="replace")):
                    return True
            except OSError:
                continue
    return False


def channels(app_id: str, apps: dict, skip: set) -> dict[str, bool]:
    app_dir, d = apps[app_id]
    head = (d.get("wraps") or {}).get("headless_app")
    sides = [(app_dir, d)] + ([apps[head]] if head in apps else [])
    return {
        "screen": any(isinstance(r, dict) and r.get("module") for r in d.get("routing") or []),
        "cli": any(verbs(p, skip) for p, _ in sides),
        "api": any(isinstance(c, dict) and (c.get("endpoint") or c.get("interface"))
                   for _, m in sides for c in m.get("capabilities") or []) or any(routes(p) for p, _ in sides),
        "flow": any((p / "hooks" / "flow").is_file() for p, _ in sides),
    }


def run(root: Path, known: dict) -> tuple[int, list[str], list[str]]:
    fail, notes = [], []
    apps = manifests(root, fail)
    skip = lifecycle(root)
    wrapped = sorted(a for a, (_, d) in apps.items() if "wraps" in d)
    missing_now = set()
    for a in wrapped:
        w = apps[a][1]["wraps"]
        if not isinstance(w, dict) or not str(w.get("client") or "").strip():
            fail.append(f"{a}: `wraps` must be an object with a `client` (got {type(w).__name__})")
            continue
        extra = sorted(set(w) - WRAPS_KEYS)
        if extra:
            fail.append(f"{a}: `wraps` has keys the schema does not name: {', '.join(extra)} (a typo drops the headless side)")
        head = w.get("headless_app")
        if head and head not in apps:
            fail.append(f"{a}: wraps.headless_app names {head!r}, which is no app here")
        claim = NO_HEADLESS.fullmatch(w["headless"].strip()) if isinstance(w.get("headless"), str) else None
        none = claim is not None
        if none and not claim.group(1):
            fail.append(f"{a}: wraps.headless says «none» with no reason — write `none: <why the vendor has no "
                        f"headless side>`, the reason the API and the flow are not owed")
        if none and head:
            fail.append(f"{a}: wraps.headless says the vendor has none, yet wraps.headless_app names {head!r}")
        got = channels(a, apps, skip)
        if none and got["api"]:
            # the exemption is for a vendor with NO headless side; an app that has an API has one, and the
            # claim would hide its missing flow (the second reader of DGO-1264)
            fail.append(f"{a}: wraps.headless says the vendor has none, yet the app has an api channel — "
                        f"name its headless side, and it owes the flow")
        for ch in CHANNELS:
            if got[ch]:
                continue
            if none and ch in HEADLESS_CHANNELS:
                notes.append(f"{a}: no {ch} channel, and none owed — wraps.headless: {w['headless'].strip()!r}")
                continue
            missing_now.add((a, ch))
            if (a, ch) in known:
                notes.append(f"{a}: no {ch} channel (KNOWN: {known[(a, ch)]})")
            else:
                fail.append(f"{a}: no {ch} channel — a wrapped app keeps the four (screen, cli, api, flow)")
    for pair in sorted(set(known) - missing_now):
        fail.append(f"{pair[0]}: its {pair[1]} channel is there now — remove its line from KNOWN (the list only shrinks)")
    print(f"wrapped-app-lint: {len(apps)} app(s) read, {len(wrapped)} wrapped ({', '.join(wrapped) or 'none'}), "
          f"{len(missing_now)} channel(s) missing ({len(known)} known)")
    return len(wrapped), fail, notes


def main() -> int:
    n, fail, notes = run(ROOT, KNOWN)
    for line in notes:
        print("  note", line)
    if n == 0:
        print("G108 FAIL — no app declares `wraps`: the scan read nothing, which is not a pass")
        return 1
    for line in fail:
        print("  FAIL", line)
    if fail:
        print("G108 FAIL — a wrapped official app keeps the four channels (DGO-1266, app-cli-api-standard.md §6)")
        return 1
    print("G108 PASS — every wrapped app has its four channels, or a KNOWN line that says why not")
    return 0


def self_test() -> int:
    bad = 0
    whole = {"routing": [{"module": "w"}], "capabilities": [{"name": "w", "interface": "w.v1"}]}
    wrap = {"client": "x"}
    cases = [  # (what, apps {id: (manifest or raw text, hooks)}, known, the failure wanted: a substring, or "")
        ("the four channels pass", {"w": ({**whole, "wraps": wrap}, ["send", "flow"])}, {}, ""),
        ("no screen", {"w": ({"capabilities": whole["capabilities"], "wraps": wrap}, ["send", "flow"])}, {}, "no screen"),
        ("no cli", {"w": ({**whole, "wraps": wrap}, ["flow"])}, {}, "no cli"),
        ("only lifecycle hooks are no cli", {"w": ({**whole, "wraps": wrap}, ["prepare", "verify", "flow"])}, {}, "no cli"),
        ("no api", {"w": ({"routing": [{"module": "w"}], "wraps": wrap}, ["send", "flow"])}, {}, "no api"),
        ("no flow", {"w": ({**whole, "wraps": wrap}, ["send"])}, {}, "no flow"),
        ("the CLI, API and flow may live in the headless app",
         {"w": ({"routing": [{"module": "w"}], "wraps": {"client": "x", "headless_app": "w-api"}}, []),
          "w-api": ({"capabilities": [{"name": "a", "endpoint": "http://a:1"}]}, ["run", "flow"])}, {}, ""),
        ("a KNOWN gap that closed must leave the list",
         {"w": ({**whole, "wraps": wrap}, ["send", "flow"])}, {("w", "flow"): "old"}, "remove its line"),
        ("a headless_app that is no app", {"w": ({**whole, "wraps": {"client": "x", "headless_app": "gone"}}, ["send", "flow"])}, {}, "no app here"),
        ("a typo in wraps", {"w": ({**whole, "wraps": {"client": "x", "headles_app": "y"}}, ["send", "flow"])}, {}, "headles_app"),
        ("wraps that is not an object", {"w": ({**whole, "wraps": "Claude"}, ["send", "flow"])}, {}, "must be an object"),
        ("an app.json that does not parse", {"w": ({**whole, "wraps": wrap}, ["send", "flow"]), "x": ("{oops", [])}, {}, "does not parse"),
        ("an app that wraps nothing is not this gate's", {"p": (whole, [])}, {}, ""),
        ("a vendor with no headless side owes no api and no flow",
         {"w": ({"routing": [{"module": "w"}], "wraps": {"client": "x", "headless": "none: no CLI of its own"}},
                ["status"])}, {}, ""),
        ("'None — why' with a dash is none too",
         {"w": ({"routing": [{"module": "w"}], "wraps": {"client": "x", "headless": "None — no CLI"}}, ["status"])}, {}, ""),
        ("a bare 'none' gives no reason",
         {"w": ({"routing": [{"module": "w"}], "wraps": {"client": "x", "headless": "none"}}, ["status"])}, {}, "no reason"),
        ("'none-cli' is a name, not none",
         {"w": ({"routing": [{"module": "w"}], "wraps": {"client": "x", "headless": "none-cli"}}, ["status"])}, {}, "no api"),
        ("none, yet an api: the claim may not hide the flow",
         {"w": ({**whole, "wraps": {"client": "x", "headless": "none: no CLI"}}, ["send"])}, {}, "yet the app has an api"),
        ("no headless side still owes the screen",
         {"w": ({"wraps": {"client": "x", "headless": "none: no CLI"}}, ["status"])}, {}, "no screen"),
        ("no headless side still owes the cli",
         {"w": ({"routing": [{"module": "w"}], "wraps": {"client": "x", "headless": "none: no CLI"}}, [])}, {}, "no cli"),
        ("a word that starts with none is not none",
         {"w": ({"routing": [{"module": "w"}], "wraps": {"client": "x", "headless": "nonexistent-cli"}}, ["status"])},
         {}, "no api"),
        ("none, and a headless_app beside it",
         {"w": ({**whole, "wraps": {"client": "x", "headless": "none: x", "headless_app": "w-api"}}, ["send", "flow"]),
          "w-api": (whole, ["run"])}, {}, "yet wraps.headless_app"),
    ]
    for what, spec, known, want in cases:
        with tempfile.TemporaryDirectory(prefix="g108-") as d:
            root = Path(d)
            for app, (manifest, hooks) in spec.items():
                p = root / "apps" / app
                (p / "hooks").mkdir(parents=True)
                (p / "app.json").write_text(manifest if isinstance(manifest, str) else json.dumps({"id": app, **manifest}))
                for h in hooks:
                    (p / "hooks" / h).write_text("#!/bin/sh\n")
            _, fail, _ = run(root, known)
        got = " | ".join(fail)
        if (want and want not in got) or (not want and fail):
            print(f"  self-test FAIL: {what}: wanted {want or 'no failure'!r}, got {got or 'none'!r}")
            bad += 1
    print("wrapped-app-lint self-test:", "FAIL" if bad else f"PASS ({len(cases)} cases, each naming its failure)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv[1:] else main())
