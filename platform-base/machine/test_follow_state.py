#!/usr/bin/env python3
"""test_follow_state.py — the machine overview says this office's follow: why it took, or did not take, a version.

Until now that was only in data/follow/state, a file a shell on the machine alone could read; the HP's and the Dell's
takes of 2026-11-11/12 could be explained by nobody outside them (DGO-1848). The overview (read over the link by
every linked office) now carries `follow`. The state file below is vps1's own, as it read after it took batch 45.

    python3 platform-base/machine/test_follow_state.py      (inside the machine image: it imports the app)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

D = tempfile.mkdtemp(prefix="follow-state-")
os.environ["FOLLOW_DIR"] = D
sys.path.insert(0, str(Path(__file__).resolve().parent))
import app  # noqa: E402

FAIL: list[str] = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


check(app._follow_state() is None, "no state file (nothing follows here): None")

VPS1 = """WHY=
TAKING_WHAT=dgo-stable
VERIFIED=75856788e4faaf2c99516d31cbb41e3d79a66612
TAKING=
MERGED=
BEFORE=
PUSH_PENDING=
NOTICE=
TOLD_PENDING=
LAST_AT=2026-11-12 18:31:13 UTC
LAST_RESULT=current
LAST_DETAIL=dgo-stable green at c66cf9ec is in vps1-dgo
CURRENT_EPOCH=1794508273
FAILED_TARGET=
FAILED_AT=
FAILED_HEAD=
"""
(Path(D) / "state").write_text(VPS1, encoding="utf-8")
s = app._follow_state()
check(s and s["result"] == "current" and s["at"] == "2026-11-12 18:31:13 UTC"
      and s["detail"] == "dgo-stable green at c66cf9ec is in vps1-dgo", "vps1's state: when, what, why")
check(s == {"at": "2026-11-12 18:31:13 UTC", "result": "current", "detail": "dgo-stable green at c66cf9ec is in vps1-dgo",
           "verified": "75856788e4faaf2c99516d31cbb41e3d79a66612", "failed_target": None, "failed_at": None,
           "taking": None, "last_take_of": "dgo-stable", "current_epoch": "1794508273"},
      "exactly these keys: WHY, BEFORE, MERGED, NOTICE and the rest are not said; empty is None")

(Path(D) / "state").write_text("LAST_RESULT=skipped\nLAST_DETAIL=" + "x" * 2000 + "\nnot a pair\n=empty key\n",
                               encoding="utf-8")
s = app._follow_state()
check(s == {"result": "skipped", "detail": "x" * 400}, "a long reason is cut at 400; lines that are no pair are skipped")

snap = app._snapshot((0.0, {"generated_at": "x"}))
check("follow" in snap and snap["follow"]["result"] == "skipped", "the overview carries it, read fresh per request")

compose = (Path(__file__).resolve().parent / "docker-compose.yml").read_text(encoding="utf-8")
check("data/follow" not in compose and "/:/host/root:ro" in compose,
      "no bind of its own (docker would create data/follow as root): read through the host root")
src = (Path(__file__).resolve().parent / "app.py").read_text(encoding="utf-8")
check('DEPLOYMENT_PATH / "data" / "follow"' in src, "…from this office's own checkout path")
import shutil  # noqa: E402
shutil.rmtree(D, ignore_errors=True)

print("test_follow_state: all passed" if not FAIL else f"test_follow_state: {len(FAIL)} failure(s)")
sys.exit(1 if FAIL else 0)
