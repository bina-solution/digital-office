#!/usr/bin/env python3
"""app-standard/measure.py — every app, measured against the one standard (DGO-1039, pillar 2).

    python3 scripts/app-standard/measure.py            # measure; write inventory.json + INVENTORY.md here
    python3 scripts/app-standard/measure.py --print    # …and print the table
    python3 scripts/app-standard/measure.py --check    # fail when an app lost a cell the committed file has

It imports the compiler, so it needs PyYAML. On the Mac it runs in the engine's guest:
    bash packaging/macos/engine.sh exec -- python3 scripts/app-standard/measure.py

THE STANDARD. The owner, 2026-10-30 (DGO-1039): every app «perfectly standing up to all standarts and
full ui api cli actionalble from agents and humens», «perfectly extended to and into dgos». Seven
columns, each read by what the platform ALREADY reads. This file keeps no list of apps, of verbs or of
answers, so a cell cannot turn green because someone remembered it:

  ui     a tile in the console: the compiler's own render of `console.modules.yaml`
         (`reconcile.render_registries`, over every manifest as if each were enabled, into a
         directory of this run), and the views the UI map counts for the app
         (`scripts/ui-coverage/inventory.py`, every app taken as running)
  api    a door an agent or another app calls: the agent door on the compiler's registry row, a
         capability with an endpoint, or `/api/…` route literals in the app's own source (a Python
         docstring is prose, not a route; a call the app makes OUT is still counted — read the number
         as "speaks HTTP under /api", not as its own route table)
  cli    `bbox <app> <verb>`: the app's hooks (bbox `app_verbs`), less the lifecycle hooks the
         platform runs on every app — found from their callers, not listed here
  ops    operatives, the recipes an agent follows to act as a person does (`apps/operatives/ops.py`)
  share  what this office would publish on a link if it served everything: `publishable` and
         `publishable_services` of `apps/dgo-extend/catalog.py` over the compiler's registry
  brief  the AGENT.md the compiler injects into every agent session (`agent.context`), inside its
         budget (`reconcile.MAX_BRIEF_BYTES`)
  gate   a registered gate (`scripts/refactor/GATES.md`) whose runner is the app's own file or whose
         code names the app's directory — never in an exemption map or a self-test case, which name
         an app to EXCUSE it; the app's own test files are counted beside it. A gate that scans every
         app without naming one (G84 reads every compose file) is not credited to any: the column
         says which apps a gate was written FOR

Every cell is read from source, not from a running office, so every office computes the same file.
The one exception is the console's own view count, which the UI map takes from this office's
compiled tiles — so a fresh clone runs `python3 platform/manager/reconcile.py render` first; without
`.generated/` the UI map says so, and the run (and `--check`) fails rather than measure short.
Each «קבץ קדמה» round closes cells; `--check` keeps a closed cell closed.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "inventory.json"
OUT_MD = HERE / "INVENTORY.md"
ROOTS = ("platform-base", "apps")
COLUMNS = ("ui", "api", "cli", "ops", "share", "brief", "gate")

sys.path.insert(0, str(ROOT / "platform" / "manager"))
sys.path.insert(0, str(ROOT / "scripts" / "ui-coverage"))
sys.path.insert(0, str(ROOT / "apps" / "operatives"))
import reconcile  # noqa: E402  the compiler: the registry, the console's tiles, the brief budget
import inventory as ui_map  # noqa: E402  the UI map's denominator
import ops  # noqa: E402  the operatives


def _module(name: str, rel: str):
    """A module by its file — `catalog` is also the name of platform/manager/catalog.py."""
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


link_catalog = _module("dgo_extend_catalog", "apps/dgo-extend/catalog.py")  # what a link publishes

# Directories that hold no source of the app's own: dependencies, build output, caches.
SKIP_DIRS = {"node_modules", "vendor", "dist", "build", "__pycache__", ".git"}
SOURCE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".ejs", ".html", ".sh"}
MAX_SOURCE_BYTES = 2_000_000          # a file this large is a bundle or a dump, not the app's source
ROUTE = re.compile(r"""["'`](/api/[A-Za-z0-9_\-./]*)""")
ROUTE_IN_STRING = re.compile(r"(?<![\w/])(/api/[A-Za-z0-9_\-./]*)")
SHELL_MODULES = "platform-base/console/modules.yaml"   # the shell's built-in views (ui-coverage `_modules`)
# A name that holds apps a gate EXCUSES, or the cases its self-test feeds it — not what it checks.
# Whole words of an identifier only: `swallowing_subcalls` (G53) and `unwaived` (G84) are checks.
# `NOT_RUN_HERE` (G84) names the compose files it does not read, so it excuses them too — the whole
# name: `test_archived_apps_do_not_run` (G17) is a check.
EXCUSING = re.compile(r"(?i)(?:^|_)(allow(?:ed|list)?|exempt\w*|justified|waiv(?:ed|ers?)|ignored?"
                      r"|skip(?:ped|s)?|known_red|baseline|self_?test\w*|cases|not_run_here)(?:_|$)")
# `test_*` in each of G72's three languages: `.sh` and `.mjs` were missed, eighteen tests G72 runs.
TEST_FILE = re.compile(r"^test_.*\.(py|sh|mjs)$|_test\.(py|go)$|\.test\.(m?js|ts)$|-test\.m?js$|^test(\.py|\.sh)?$")
APP_PATH = re.compile(r"(?<![\w-])(apps|platform-base)/([a-z0-9][a-z0-9-]*)")

# Where the platform runs an app's hooks BY NAME, for every app: layer 0, the compiler, the control
# plane and the data plane. A verb called from here is lifecycle — the platform's, not the app's CLI.
LIFECYCLE_CALLERS = ("bbox", "scripts/*", "platform/manager/*.py",
                     "platform-base/app-management/*.py", "platform-base/data-management/*.py")
LIFECYCLE_CALLS = (
    re.compile(r"run_app_hooks\s+([a-z][a-z0-9-]*)"),                              # bbox, lib.sh
    re.compile(r"_run_hook\(\s*\w+\s*,\s*[\"']([a-z][a-z0-9-]*)[\"']"),             # app-management
    re.compile(r"app_hook\(\s*\w+\s*,\s*\w+\s*,\s*[\"']([a-z][a-z0-9-]*)[\"']"),    # the archive
    re.compile(r"(?:\}|\*)/hooks/([a-z][a-z0-9-]*)"),                               # through a variable
)


class ReadError(RuntimeError):
    """A reader this inventory depends on did not read — the run fails rather than under-count."""


def is_test(path: Path) -> bool:
    return bool(TEST_FILE.search(path.name)) or bool({"tests", "test"} & set(path.parts[:-1]))


def files_of(app_dir: Path):
    for dirpath, dirnames, filenames in os.walk(app_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            yield Path(dirpath) / name


def read_text(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_SOURCE_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ── the readers ──────────────────────────────────────────────────────────────────────────────────
def console_tiles(cat: dict, order: list) -> dict:
    """app id → its console tiles, as the compiler renders them — into a directory of this run, so the
    office's own `.generated/` is never written. Every manifest counts as enabled."""
    owner = {}
    for aid in order:
        for r in cat[aid].get("routing") or []:
            if r.get("module"):
                mid = str(r["module"].get("id", aid))          # the renderer's own default
                if owner.setdefault(mid, aid) != aid:
                    raise ReadError(f"module id {mid!r} is declared by {owner[mid]} and {aid}")
    home = reconcile.GEN
    with tempfile.TemporaryDirectory() as tmp:
        reconcile.GEN = Path(tmp)
        try:
            reconcile.render_registries(cat, order)
            modules = reconcile.yaml.safe_load(
                (Path(tmp) / "registry" / "console.modules.yaml").read_text(encoding="utf-8")) or []
        finally:
            reconcile.GEN = home
    tiles = defaultdict(list)
    for m in modules:
        aid = owner.get(str(m.get("id")))
        if aid is None:
            raise ReadError(f"console tile {m.get('id')!r} belongs to no manifest — the render changed")
        tiles[aid].append({"id": m["id"], "kind": "external" if m.get("external") else "embedded"})
    if not tiles:
        raise ReadError("the compiler rendered no console tile")
    # …and the shell's OWN views, which no manifest declares: the file the console (and the UI map's
    # `_modules`) merges with the compiled tiles, credited to the app whose directory holds it.
    shell = ROOT / SHELL_MODULES
    own = [m for m in (reconcile.yaml.safe_load(shell.read_text(encoding="utf-8")) or [])
           if isinstance(m, dict) and m.get("id")]
    if not own:
        raise ReadError(f"{SHELL_MODULES}: no view of the shell's own — it always owns its settings")
    tiles[shell.parent.name] += [{"id": m["id"], "kind": "shell"} for m in own]
    return tiles


def catalog() -> tuple[dict, dict, dict, dict, dict]:
    """(manifests, registry rows by app, console tiles by app, published rows by app, published doors
    by app) — over EVERY app, as if each were enabled and this office served everything."""
    cat = reconcile.load_catalog()
    order = sorted(cat)
    registry = reconcile._office_apps(cat, order)
    rows, published, doors = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in registry.get("apps") or []:
        rows[r["app"]].append(r)
    if not rows:
        raise ReadError("the compiler's registry has no rows — `_office_apps` changed shape")
    for r in link_catalog.publishable(registry, {"*": {}}).get("apps") or []:
        published[r["app"]].append(r)
    # A door is published only when `serve.services` names it (never under `*`): name every one.
    every_door = {"services": {str(d["alias"]): {} for d in registry.get("services") or []}}
    for d in link_catalog.publishable_services(registry, every_door):
        doors[d["app"]].append(d)
    if not published:
        raise ReadError("dgo-extend's `publishable` published nothing under `*` — its contract changed")
    return cat, rows, console_tiles(cat, order), published, doors


#: The one framing error that is this run's own doing: with every app taken as running, the map asks
#: THIS office's compiled registry for the tiles of apps it does not run. Any other error is drift.
NOT_RENDERED_HERE = "the compiled registry has no such embedded module"


def ui_views() -> tuple[Counter, list[str]]:
    """Views per app id in the UI map, with every app taken as running (`on: None` is the map's own
    "the compiler cannot say" state). Every error but the one above is the map's drift, and is said.
    The views are what this column counts; the framing check (`embed_index`) stops at its first
    error, so on an office that does not run every app it speaks for none of them here — `bbox ui-map`
    on the office is where framing drift is read."""
    office = ui_map._office()
    office["on"] = None
    inv = ui_map.build()
    man = ui_map.yaml.safe_load(ui_map.MANIFEST.read_text(encoding="utf-8"))
    tile_app = {t["module"]: t["app"] for t in office["tiles"]}
    counts, errors = Counter(), [e for e in inv["errors"] if NOT_RENDERED_HERE not in e]
    for v in inv["views"]:
        label = ((man.get("hosts") or {}).get(v["app"]) or {}).get("local", "").split(".")[0]
        aid = office["owner"].get(label) or tile_app.get(v["app"])
        if aid is None:
            errors.append(f"UI map: view {v['app']}/{v['id']} belongs to no app")
            continue
        counts[aid] += 1
    if not counts:
        raise ReadError("the UI map read no views")
    return counts, errors


def operatives_by_app() -> dict:
    out = defaultdict(list)
    for op in ops.operatives():
        out[op["app"]].append(op.get("id") or Path(op["path"]).stem)
    if not out:
        raise ReadError("ops.operatives() read no operative — the operatives app has three of its own")
    return out


def verbs_of(app_dir: Path) -> list[str]:
    """`bbox <app> …`'s verbs exactly as bbox's `app_verbs` lists them: the hooks/ entries, base names."""
    d = app_dir / "hooks"
    if not d.is_dir():
        return []
    return sorted({re.sub(r"\.(py|mjs|sh)$", "", p.name) for p in d.iterdir() if p.name != "__pycache__"})


def lifecycle_verbs(every_verb: set) -> list[str]:
    found = set()
    for pattern in LIFECYCLE_CALLERS:
        for f in sorted(ROOT.glob(pattern)):
            if not f.is_file() or is_test(f):
                continue
            text = read_text(f)
            for call in LIFECYCLE_CALLS:
                found.update(call.findall(text))
    # A word in a comment ("run_app_hooks names the app") is the hook of no app, and drops out here.
    lifecycle = sorted(found & every_verb)
    if not lifecycle:
        raise ReadError("no lifecycle hook found in the platform's callers — their call shape changed")
    return lifecycle


def _text(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _excusing(node) -> bool:
    """Does this node hold names a gate excuses or feeds its self-test, rather than checks?"""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        # `self_test()` only — a runner that IS a test file (G16, G17) checks in its `test_*`.
        return bool(EXCUSING.search(node.name))
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return any(isinstance(t, ast.Name) and EXCUSING.search(t.id) for t in targets)
    return False


def code_strings(path: Path, excuse: bool = True) -> list[str]:
    """The string literals a file's CODE holds. Left out: docstrings (a gate that names an app in its
    prose as an example does not check it); and, for a gate (`excuse`), an exemption or a self-test
    case — a name such as `ALLOWED`/`EXEMPT`/`SELF_TEST` or a `self_test()` — because naming an app
    there EXCUSES it (G83's `ALLOWED = {"apps/hello-bina": …}`). A path joined in pieces
    (`ROOT / "apps" / "x"`, `os.path.join("apps", "x")`) counts whole; two literals that merely sit
    side by side (`st["apps"]["drive"]`, a state fixture) do not."""
    text = read_text(path)
    if path.suffix != ".py":
        return [text]
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [text]
    docs, joined = set(), []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and _text(first.value) is not None:
                docs.add(id(first.value))
        if excuse and _excusing(node):
            docs.update(id(n) for n in ast.walk(node))

    def kept(n) -> str | None:
        return _text(n) if id(n) not in docs else None

    for node in ast.walk(tree):                # second pass: a join of excused pieces names nothing
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left = node.left.right if isinstance(node.left, ast.BinOp) else node.left
            if kept(left) in ROOTS and kept(node.right):
                joined.append(f"{kept(left)}/{kept(node.right)}")
        elif isinstance(node, ast.Call):
            args = [kept(a) for a in node.args]
            joined += [f"{a}/{b}" for a, b in zip(args, args[1:]) if a in ROOTS and b]
    return [s for s in (kept(n) for n in ast.walk(tree)) if s is not None] + joined


def runner(name: str) -> Path | None:
    p = ROOT / name if "/" in name else ROOT / "scripts" / "refactor" / name
    if p.is_file():
        return p
    found = sorted((ROOT / "scripts").rglob(Path(name).name))
    return found[0] if found else None


def gates_by_app(apps: dict) -> tuple[dict, int]:
    """app id → the G-numbers whose registered runner names it; and how many runners were read."""
    text = (ROOT / "scripts" / "refactor" / "GATES.md").read_text(encoding="utf-8")
    if "\n## The gates" not in text:
        raise ReadError("GATES.md: the `## The gates` table is gone")
    table = text.split("\n## The gates", 1)[1].split("\n## ", 1)[0]

    def runners(cell: str) -> list[str]:
        live = re.sub(r"~~.*?~~", "", cell)               # a struck-through runner lives in the attic
        return [t.split()[0] for t in re.findall(r"`([^`]+)`", live)
                if t.split() and t.split()[0].endswith((".py", ".sh", ".mjs"))]

    out, read = defaultdict(set), 0
    for line in table.splitlines():
        m = re.match(r"^\|\s*(G\d+)\b[^|]*\|", line)
        cells = line.split("|")
        if not m or len(cells) < 4:
            continue
        # Read from the RIGHT: a description may hold a `|` of its own (G53, G58, G77) and an odd
        # backtick (G88), so counting cells from the left is wrong. Runs is the cell before Lane; a
        # row with no Lane cell (G75) has it last. A row that names no runner must say it has none.
        for cell in (cells[-3], cells[-2]):
            if runners(cell) or cell.strip() in ("—", "-") or "~~" in cell:
                break
        else:
            raise ReadError(f"GATES.md {m.group(1)}: no runner in its Runs cell — the table's shape changed")
        for name in runners(cell):
            path = runner(name)
            if path is None:
                continue
            read += 1
            named = set()
            rel = path.relative_to(ROOT).as_posix()
            for s in [rel] + code_strings(path):
                for root, aid in APP_PATH.findall(s):
                    named.add((root, aid))
            for aid, (root, _) in apps.items():
                if (root, aid) in named:
                    out[aid].add(m.group(1))
    if read < 10:
        raise ReadError(f"GATES.md: only {read} gate runner(s) read — the table's shape changed")
    return out, read


def api_routes(app_dir: Path) -> int:
    paths = set()
    for f in files_of(app_dir):
        if f.suffix not in SOURCE_EXT or is_test(f):
            continue
        found = ([r for s in code_strings(f, excuse=False) for r in ROUTE_IN_STRING.findall(s)]
                 if f.suffix == ".py"
                 else ROUTE.findall(read_text(f)))
        for route in found:
            route = route.rstrip("/.")
            if route and route != "/api":
                paths.add(route)
    return len(paths)


def tests_of(app_dir: Path) -> int:
    return sum(1 for f in files_of(app_dir) if is_test(f) and (f.suffix in SOURCE_EXT or not f.suffix))


# ── the measure ──────────────────────────────────────────────────────────────────────────────────
def measure() -> dict:
    cat, rows, console, published, doors = catalog()
    apps = {aid: (man["_dir"].parent.name, man) for aid, man in sorted(cat.items())}
    views, notes = ui_views()
    op_ids = operatives_by_app()
    gates, runners = gates_by_app(apps)
    verbs = {aid: verbs_of(man["_dir"]) for aid, (_, man) in apps.items()}
    lifecycle = lifecycle_verbs({v for vs in verbs.values() for v in vs})

    out = []
    for aid, (root, man) in apps.items():
        app_dir = man["_dir"]
        tiles, shared = console.get(aid, []), published.get(aid, [])
        caps = sorted(c["name"] for c in (man.get("capabilities") or []) if c.get("endpoint"))
        door = next((r["agent_api_port"] for r in rows.get(aid, []) if r.get("agent_api_port")), None)
        routes = api_routes(app_dir)
        own = [v for v in verbs[aid] if v not in lifecycle]
        agent = man.get("agent") or {}
        brief_rel = (agent.get("context") or "").strip()
        brief_file = app_dir / (brief_rel or "AGENT.md")
        brief_bytes = brief_file.stat().st_size if brief_file.is_file() else 0
        row = {
            "app": aid, "root": root, "layer": man.get("layer"), "kind": man.get("kind"),
            "system": bool(man.get("system")),
            # A screen people use is the standard's subject: the platform's own internals (`system`)
            # and an app with no service of its own (a library, a blueprint) are counted apart.
            "product": not man.get("system") and man.get("kind") not in ("library", "blueprint"),
            "ui": {"ok": bool(tiles), "views": views.get(aid, 0), "tiles": tiles},
            "api": {"ok": bool(door or caps or routes), "door": door, "capabilities": caps,
                    "routes": routes},
            "cli": {"ok": bool(own), "token": (man.get("cli") or {}).get("alias") or aid, "verbs": own,
                    "lifecycle": [v for v in verbs[aid] if v in lifecycle]},
            "ops": {"ok": bool(op_ids.get(aid)), "ids": sorted(op_ids.get(aid, []))},
            "share": {"ok": bool(shared or doors.get(aid)), "aliases": [r["alias"] for r in shared],
                      "doors": sorted(d["alias"] for d in doors.get(aid, [])),
                      "api_crosses": any(r.get("agent_api_port") for r in shared)},
            "brief": {"ok": bool(brief_rel) and 0 < brief_bytes <= reconcile.MAX_BRIEF_BYTES,
                      "declared": bool(brief_rel), "bytes": brief_bytes,
                      "file": brief_file.relative_to(ROOT).as_posix() if brief_bytes else None},
            "gate": {"ok": bool(gates.get(aid)), "gates": sorted(gates.get(aid, []), key=lambda g: int(g[1:])),
                     "tests": tests_of(app_dir)},
        }
        row["score"] = sum(1 for c in COLUMNS if row[c]["ok"])
        out.append(row)

    def totals(sel):
        return {c: sum(1 for r in sel if r[c]["ok"]) for c in COLUMNS} | {"apps": len(sel)}

    product = [r for r in out if r["product"]]
    return {
        "generated_by": "scripts/app-standard/measure.py",
        "standard": "DGO-1039 pillar 2: ui, api, cli, ops, share, brief, gate",
        "lifecycle_verbs": lifecycle,
        "gate_runners_read": runners,
        "totals": {"product": totals(product), "all": totals(out),
                   "complete": sum(1 for r in product if r["score"] == len(COLUMNS))},
        "notes": notes,
        "apps": out,
    }


# ── the outputs ──────────────────────────────────────────────────────────────────────────────────
def cell(row: dict, col: str) -> str:
    c = row[col]
    mark = "✓" if c["ok"] else "✗"
    detail = {
        "ui": lambda: " ".join(f"{t['id']}({t['kind'][:3]})" for t in c["tiles"]) + f" · {c['views']}v",
        "api": lambda: " ".join(x for x in (f"door:{c['door']}" if c["door"] else "",
                                             ",".join(c["capabilities"]),
                                             f"{c['routes']} routes" if c["routes"] else "") if x),
        "cli": lambda: f"{len(c['verbs'])} verbs" if c["verbs"] else "",
        "ops": lambda: str(len(c["ids"])) if c["ids"] else "",
        "share": lambda: " ".join(c["aliases"] + [f"door:{d}" for d in c["doors"]])
                         + (" +api" if c["api_crosses"] else ""),
        "brief": lambda: (f"{c['bytes']}B" + ("" if c["declared"] else " undeclared")) if c["bytes"] else "",
        "gate": lambda: " ".join(c["gates"]) + (f" · {c['tests']} tests" if c["tests"] else ""),
    }[col]().strip(" ·")
    return f"{mark} {detail}".strip()


def markdown(inv: dict) -> str:
    t = inv["totals"]
    head = "| app | kind | " + " | ".join(COLUMNS) + " | score |"
    lines = [
        "# The app standard — every app, measured (DGO-1039)",
        "",
        "Generated by `scripts/app-standard/measure.py` — do not edit by hand; run it again. The columns,",
        "and which reader each one comes from, are in the script's docstring. «קבץ קדמה» rounds close",
        "cells here, and `measure.py --check` refuses a cell that was closed and opened again.",
        "",
        f"**{t['complete']} of {t['product']['apps']} product apps meet all seven.** Per column, product "
        f"apps / all {t['all']['apps']} apps:",
        "",
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "---:|" * len(COLUMNS),
        "| " + " | ".join(f"{t['product'][c]}/{t['product']['apps']} ({t['all'][c]}/{t['all']['apps']})"
                          for c in COLUMNS) + " |",
        "",
        f"Lifecycle hooks, not counted as CLI: {', '.join(inv['lifecycle_verbs'])}. "
        f"Gate runners read: {inv['gate_runners_read']}.",
        "",
    ]
    for title, sel in (("Product apps", [r for r in inv["apps"] if r["product"]]),
                       ("Platform internals, libraries and blueprints", [r for r in inv["apps"] if not r["product"]])):
        lines += [f"## {title}", "", head, "|---|---|" + "---|" * len(COLUMNS) + "---:|"]
        for r in sorted(sel, key=lambda r: (-r["score"], r["app"])):
            lines.append(f"| `{r['app']}` | {r['kind']}{' · system' if r['system'] else ''} | "
                         + " | ".join(cell(r, c) for c in COLUMNS) + f" | {r['score']}/{len(COLUMNS)} |")
        lines.append("")
    if inv["notes"]:
        lines += ["## Notes", ""] + [f"- {n}" for n in inv["notes"]] + [""]
    return "\n".join(lines)


def dump(inv: dict) -> str:
    """The JSON with one line per app, so a round that closes a cell changes that app's line only."""
    head = [f" {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}," for k, v in inv.items() if k != "apps"]
    rows = [f"  {json.dumps(r, ensure_ascii=False)}" for r in inv["apps"]]
    return "\n".join(["{"] + head + [' "apps": [', ",\n".join(rows), " ]", "}"]) + "\n"


def check(inv: dict) -> int:
    """A cell the committed inventory has closed must stay closed."""
    try:
        old = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"check: no committed inventory to hold against ({e})", file=sys.stderr)
        return 1
    if not old.get("apps"):
        print("check: the committed inventory holds no app — nothing would be held", file=sys.stderr)
        return 1
    now = {r["app"]: r for r in inv["apps"]}
    lost, closed = [], []
    for r in old["apps"]:
        cur = now.get(r["app"])
        if cur is None:
            lost.append(f"{r['app']}: the app is gone")
            continue
        for c in COLUMNS:
            was = (r.get(c) or {}).get("ok")          # a column the committed file predates was not met
            if was and not cur[c]["ok"]:
                lost.append(f"{r['app']}: {c} was met and is not now")
            elif cur[c]["ok"] and not was:
                closed.append(f"{r['app']}: {c}")
    for line in closed:
        print(f"closed since the committed inventory: {line} — run measure.py to record it")
    for line in lost:
        print(f"LOST: {line}", file=sys.stderr)
    return 1 if lost else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--print", action="store_true", help="print the table too")
    ap.add_argument("--check", action="store_true", help="hold the committed inventory; write nothing")
    a = ap.parse_args()
    try:
        inv = measure()
    except ReadError as e:
        print(f"app-standard: {e}", file=sys.stderr)
        return 2
    for n in inv["notes"]:
        print(f"note: {n}", file=sys.stderr)
    if a.check:
        # A note is a reader that did not read (the UI map's drift, a view of no app): the cells it
        # feeds were measured short, so holding them proves nothing — the check fails with it.
        return check(inv) or (1 if inv["notes"] else 0)
    OUT_JSON.write_text(dump(inv), encoding="utf-8")
    md = markdown(inv)
    OUT_MD.write_text(md, encoding="utf-8")
    t = inv["totals"]
    print(f"app standard: {t['complete']}/{t['product']['apps']} product apps meet all seven; "
          + ", ".join(f"{c} {t['product'][c]}" for c in COLUMNS)
          + f" → {OUT_JSON.relative_to(ROOT)}, {OUT_MD.relative_to(ROOT)}")
    if a.print:
        print(md)
    return 1 if inv["notes"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
