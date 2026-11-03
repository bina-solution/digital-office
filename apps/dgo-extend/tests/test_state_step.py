#!/usr/bin/env python3
"""test_state_step — a declaration that names only business apps never switches the platform off (FPG-8).

The state step switches off every app enabled on the machine that the declaration does not name. A
declaration of fireplace that named its business apps only (project-pln, bina-ds, n8n, sites, …) switched
off traefik, authentik, postgres, redis, console and connections — "7 enabled · 15 switched off" — and the
compiler then refused to render (identity had no provider it may start). This runs the Python the state
step sends to the machine, against a scratch office.

Run: python3 apps/dgo-extend/tests/test_state_step.py  (inside the app's image, or with its deps)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import converge  # noqa: E402

FAIL = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


def main() -> int:
    script = re.search(r"undeclared_off\(\) \{\nEXTRA=\$\(python3 - <<'PY'\n(.*?)\nPY\n", converge.STATE_SCRIPT, re.S)
    check(script is not None, "the state step still decides what to switch off in one Python block")
    if script is None:
        print("FAIL", FAIL[0])
        return 1
    with tempfile.TemporaryDirectory() as d:
        Path(d, "platform.state.yaml").write_text(
            "apps:\n  authentik: { enabled: true }\n  traefik: { enabled: true }\n"
            "  app-management: { enabled: true }\n  indox: { enabled: true }\n  bina-ds: { enabled: true }\n"
            "  broken: { enabled: true }\n  bina-ui: { enabled: true }\n  core: { enabled: true }\n")
        for base, app, manifest in (("platform-base", "authentik", {"system": True, "layer": 1}),
                                    ("platform-base", "traefik", {"system": True, "layer": 1}),
                                    ("platform-base", "app-management", {"layer": 1}),
                                    ("platform-base", "bina-ui", {"layer": 2}),       # the shared UI kit
                                    ("apps", "core", {"system": True}),
                                    ("apps", "indox", {"layer": 3}),
                                    ("apps", "bina-ds", {"layer": 3})):
            Path(d, base, app).mkdir(parents=True)
            Path(d, base, app, "app.json").write_text(json.dumps(manifest))
        Path(d, "apps", "broken").mkdir(parents=True)
        Path(d, "apps", "broken", "app.json").write_text("{not json")
        out = subprocess.run([sys.executable, "-"], input=script.group(1).replace("__DECLARED__", "bina-ds"),
                             text=True, capture_output=True, cwd=d, timeout=30)
        off = out.stdout.strip()
        check(out.returncode == 0, f"the block runs: {out.stderr[-300:]}")
        check(off == "indox", f"only an undeclared business app is switched off — the platform stays: {off!r}")
    for f in FAIL:
        print("FAIL", f)
    print("PASS test_state_step" if not FAIL else f"{len(FAIL)} failure(s)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
