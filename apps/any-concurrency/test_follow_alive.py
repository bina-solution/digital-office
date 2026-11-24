#!/usr/bin/env python3
"""test_follow_alive — a quiet log follow keeps its source ok while its container RUNS, and only then (DGO-2111, root 19).

On 2026-11-20 the HP's traefik, n8n-bg:main and n8n-bg:webhook stood 3.2 h without a line while their containers ran
for days, and raphael's collector watch (24 h) read such a quiet log as «a source went silent» every day.

The container is stood in for: `show()` answers a running one, a stopped one, or fails.
Run: python3 apps/any-concurrency/test_follow_alive.py   (in the app's image: it imports app.py, aiodocker and FastAPI)
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

os.environ["FOLLOW_ALIVE_S"] = "0.01"            # read at import: ten milliseconds a tick here, five minutes live
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))                    # app.py imports its neighbours (flow_source)
spec = importlib.util.spec_from_file_location("any_concurrency_app", HERE / "app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class Box:
    """A container as aiodocker shows it."""

    def __init__(self, running: bool = True, fail: bool = False):
        self.running, self.fail = running, fail

    async def show(self) -> dict:
        if self.fail:
            raise RuntimeError("inspect failed")
        return {"State": {"Running": self.running}}


async def ticks(box: Box, health: dict, n: int = 5) -> None:
    task = asyncio.create_task(app._follow_alive(box, health))
    await asyncio.sleep(0.01 * n)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def main() -> int:
    fails: list[str] = []
    quiet = app._source_health(True)
    quiet.update(ok=True, last_ok=1)                 # the last line came long ago
    asyncio.run(ticks(Box(running=True), quiet))
    if not (quiet["ok"] and quiet["last_ok"] > 1 and quiet["last_event"] is None):
        fails.append(f"a quiet follow of a running container stays ok, with no event invented: {quiet}")
    stopped = app._source_health(True)
    stopped["ok"] = True
    asyncio.run(ticks(Box(running=False), stopped))
    if stopped["ok"] or "not running" not in (stopped["last_error"] or ""):
        fails.append(f"a container that stopped running is not ok: {stopped}")
    blind = app._source_health(True)
    blind["ok"] = True
    asyncio.run(ticks(Box(fail=True), blind))
    if blind["ok"] or "inspect failed" not in (blind["last_error"] or ""):
        fails.append(f"a container that cannot be read is not ok: {blind}")
    print("PASS test_follow_alive" if not fails else "FAIL test_follow_alive")
    for f in fails:
        print("FAIL", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
