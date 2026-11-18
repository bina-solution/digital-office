#!/usr/bin/env python3
"""test_context.py — `bbox context [app]` builds what an app is and does from the app itself and from what runs,
never from a hand-written fact about an installation (DGO-1960).

    python3 scripts/test_context.py

A made-up app in a throwaway folder (a manifest, a compose file, three hooks, a brief, its own hooks/context) and a
made-up engine: the context names its commands with their help lines, counts only its own containers of this
office's deployment, says an unhealthy one, carries its brief, and adds what its hooks/context says live. Then the
real catalogue of this checkout: every app the compiler knows gets a row, through the compiler's own functions.
Needs PyYAML (the compiler does).
"""
from __future__ import annotations

import contextlib
import importlib.util
import sys
import tempfile
from pathlib import Path

# the made-up app has a Hebrew title: on Windows python's own stdout is not UTF-8, and printing a failure would crash
# the test (G10)
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, ValueError):
        _stream.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("context_under_test", HERE / "context.py")
ctx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctx)

FAIL: list[str] = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp) / "demo"
    (d / "hooks").mkdir(parents=True)
    (d / "docker-compose.yml").write_text("services:\n  demo-web: {image: x}\n  demo-worker: {image: y}\n")
    (d / "AGENT.md").write_text("# Operating demo\n\nIts vocabulary and its traps.\n")
    (d / "hooks" / "list").write_text("#!/usr/bin/env bash\n#: list — every thing the demo holds\necho\n")
    (d / "hooks" / "flow").write_text("#!/usr/bin/env bash\nset -u\n#: flow — what happened, live\necho\n")
    # bbox's own app_verbs: the verb is the base name, whatever its ending (`./bbox demo sweep` runs sweep.py)
    (d / "hooks" / "sweep.py").write_text("#!/usr/bin/env python3\n#: sweep — clear what is old\n")
    (d / "hooks" / "check.mjs").write_text("#!/usr/bin/env node\n#: check — the app answers\n")
    (d / "hooks" / "__pycache__").mkdir()
    (d / "hooks" / "context").write_text("#!/usr/bin/env bash\n#: context — what demo says about itself\necho 'queue: 3 waiting'\n")
    app = {"id": "demo", "title": {"he": "הדגמה", "en": "Demo"}, "summary": {"en": "A made-up app"}, "layer": 3,
           "agent": {"context": "AGENT.md"}, "routing": [{"host": "demo", "port": 80}], "_dir": d}
    engine = [{"service": "demo-web", "project": "office", "running": True, "health": "healthy"},
              {"service": "demo-worker", "project": "office", "running": True, "health": "unhealthy"},
              {"service": "demo-web", "project": "another-deployment", "running": True, "health": ""},
              {"service": "other", "project": "office", "running": True, "health": ""}]
    project = ctx._own_project(engine)
    check(project == "office", f"this office's deployment is the one most containers run in: {project}")

    row = ctx.app_context("demo", app, {"demo"}, engine, project)
    check(row["enabled"] and row["running"] == 2 and row["containers"] == 2,
          f"its own containers of this deployment only: {row['running']}/{row['containers']}")
    check(row["unhealthy"] == 1, f"an unhealthy container is counted: {row['unhealthy']}")
    verbs = {c["verb"]: c["help"] for c in row["commands"]}
    check(set(verbs) == {"check", "context", "flow", "list", "sweep"},
          f"the verbs bbox lists — base names, endings dropped, __pycache__ not: {sorted(verbs)}")
    check(verbs["flow"] == "flow — what happened, live", f"a help line read past the first lines: {verbs['flow']!r}")
    check(verbs["sweep"] == "sweep — clear what is old" and verbs["check"] == "check — the app answers",
          f"the help of a .py and a .mjs verb, from the file the verb resolves to: {verbs}")
    check(row.get("live") == "queue: 3 waiting", f"its hooks/context is asked, live: {row.get('live')!r}")
    check(row["addresses"] == ["demo"], f"its addresses from the manifest: {row['addresses']}")

    page = ctx.render_app(row, ctx._brief(app))
    for want in ("context — demo: Demo · הדגמה", "enabled · 2 running / 2 container(s) · 1 UNHEALTHY",
                 "./bbox demo list", "== what it says about itself now (hooks/context)", "queue: 3 waiting",
                 "== its brief (agent.context)", "Its vocabulary and its traps."):
        check(want in page, f"the page says «{want}»:\n{page}")

    quiet = ctx.app_context("demo", app, set(), engine, project, live=False)
    check(not quiet["enabled"] and "live" not in quiet, "the office page asks no app's hook, and says not enabled")

    # a hook that fails says so; nothing running here counts nothing (not another deployment's containers)
    (d / "hooks" / "context").write_text("#!/usr/bin/env bash\necho 'half an answer'; exit 3\n")
    failed = ctx.app_context("demo", app, {"demo"}, engine, project)
    check(failed.get("live") == "its hooks/context failed (exit 3): half an answer", f"a failed hook: {failed.get('live')!r}")
    idle = ctx.app_context("demo", app, {"demo"}, engine, "", live=False)
    check(idle["containers"] == 0, f"no deployment running here: nothing counted, got {idle['containers']}")

# the real catalogue, through the compiler's own functions: every app gets a row, nothing about an installation needed
rc = ctx._reconcile()
cat = rc.load_catalog()
rows = [ctx.app_context(aid, a, set(), [], "", live=False) for aid, a in sorted(cat.items())]
check(len(rows) == len(cat) and len(cat) > 20, f"every app of this checkout has a row: {len(rows)} of {len(cat)}")
page = ctx.render_office([{**r, "enabled": True} for r in rows], "office-a")
check(page.startswith("context — office office-a") and "./bbox computers map" in page, "the office page:\n" + page[:300])

if FAIL:
    print("FAIL test_context:\n  " + "\n  ".join(FAIL))
    sys.exit(1)
print(f"ok test_context: an app's context from itself and from what runs; {len(cat)} apps of this checkout read")
