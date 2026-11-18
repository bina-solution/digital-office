#!/usr/bin/env python3
"""test_stale_image_services.py — the stale images a take rebuilds are the services the office DECLARES (DGO-1848).

    python3 scripts/test_stale_image_services.py

scripts/lib.sh stale_images reads every app's compose and every running container. A disabled app whose container
still ran (chat on vps1, up since 10-17) was named among the services to rebuild after a take, and `bbox run … chat …`
failed the whole rebuild with «no such service: chat»: none of the 13 stale services was rebuilt. Now only the
services of the compiled config are named; a config that cannot be read keeps every row (the run then fails loudly,
as before — never a silent «nothing is stale»). lib.sh is sourced in bash under `set -u`, as follow.sh runs it, with
the measurement (_stale_image_rows) and compose (_dcx_run) stood in by functions; compose's calls are counted.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
fails = 0


def check(name, cond, got=None):
    global fails
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"   got {got!r}"))
    fails += 0 if cond else 1


if not shutil.which("bash") or subprocess.run(["bash", "-c", "[ \"${BASH_VERSINFO[0]}\" -ge 4 ]"]).returncode:
    print("NOT RUN needs bash 4 (lib.sh)")
    sys.exit(1)


def run(fn, rows, declared, rc=0):
    """`fn` with _stale_image_rows printing `rows` and `config --services` printing `declared` (exit `rc`):
    (its stdout, how many times compose was asked)."""
    with tempfile.TemporaryDirectory() as tmp:
        marks = Path(tmp) / "asked"
        script = f'''
. "{ROOT}/scripts/lib.sh" >/dev/null 2>&1
set -u
_stale_image_rows() {{ [ -n "${{ROWS}}" ] && printf '%s\\n' "${{ROWS}}"; return 0; }}
_dcx_run() {{
  echo x >> "{marks}"
  [ "$1 $2" = "config --services" ] || return 9
  [ -n "${{DECLARED}}" ] && printf '%s\\n' "${{DECLARED}}"
  return "${{DRC}}"
}}
{fn}
'''
        env = dict(os.environ, ROWS=rows, DECLARED=declared, DRC=str(rc))
        p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, timeout=60)
        asked = len(marks.read_text().splitlines()) if marks.exists() else 0
        return p.stdout.strip(), asked


VPS1 = "any-concurrency (2h) chat (11h) console (3h) n8n (2h)"
DECLARED = "any-concurrency\nconsole\nn8n\ntraefik\r"

out, _ = run("stale_images", VPS1, DECLARED)
check("a disabled app's running container is left out, the ages kept", out == "any-concurrency (2h) console (3h) n8n (2h)", out)
out, _ = run("stale_image_services", VPS1, DECLARED)
check("…and the names a take hands to `bbox run` have no chat", out == "any-concurrency console n8n", out)
out, _ = run("stale_image_services", "chat (11h)", DECLARED)
check("only undeclared ones stale: nothing to rebuild", out == "", out)
out, _ = run("stale_images", "console-x (3h) console (1h)", "console")
check("whole names only (console-x is not console)", out == "console (1h)", out)
out, _ = run("stale_image_services", VPS1, "", rc=1)
check("a config that cannot be read keeps every row (the run then fails loudly)", out == "any-concurrency chat console n8n", out)
out, asked = run("stale_image_services", "", DECLARED)
check("nothing stale: nothing, and compose is not asked", out == "" and asked == 0, (out, asked))
out, asked = run("stale_images", "console (3h)", "console")
check("something stale: compose is asked once", out == "console (3h)" and asked == 1, (out, asked))

src = (ROOT / "bbox").read_text(encoding="utf-8")
check("bbox status reads the filtered stale_images", 'stale_img="$(stale_images)"' in src)
src = (ROOT / "scripts" / "follow.sh").read_text(encoding="utf-8")
check("a take rebuilds what stale_image_services names", "stale_image_services" in src)

print(f"test_stale_image_services: {'all passed' if not fails else f'{fails} failure(s)'}")
sys.exit(1 if fails else 0)
