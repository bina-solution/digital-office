#!/usr/bin/env python3
"""Platform-owned Browser42 task watchdog.

Tasks are durable JSON records on the Browser42 shared data volume. An active task that stops
heartbeating is marked stalled; its native tab group and evidence remain intact for inspection.
The watchdog intentionally never closes a tab or browser.
"""

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request, urlopen


DATA = Path(os.environ.get("DATA", "/data"))
TASKS = DATA / "tasks"
INTERVAL = int(os.environ.get("BROWSER42_TASK_WATCHDOG_INTERVAL", "5"))
STALL_SECONDS = int(os.environ.get("BROWSER42_TASK_STALL_SECONDS", "300"))
TOTAL_SECONDS = int(os.environ.get("BROWSER42_TASK_TOTAL_SECONDS", "1800"))
# A queued (allocated) task has no owner yet and nothing heartbeats it while it waits
# for a runner slot, so the generic activity clock never fires for it. Silence here
# means nobody is coming — give the queue its own short budget (0805c: a start sat
# silently for 19 minutes because allocated was only governed by TOTAL_SECONDS).
ALLOCATED_STALL_SECONDS = int(os.environ.get("BROWSER42_TASK_ALLOCATED_STALL_SECONDS", "240"))
ACTIVE = {"allocated", "active", "verifying"}
# any-concurrency span ingest + broker, so a stalled task's tab lane is closed and its
# group is released (R1/R3). Best-effort only — monitoring must never break the sweep.
BROKER = os.environ.get("BROKER", "ws://browser42-browser:8765")
SPANS_URL = os.environ.get("ANY_CONCURRENCY_SPANS_URL", "http://any-concurrency:8080/ingest/span")
SPANS_ENABLED = os.environ.get("BROWSER42_SPANS_ENABLED", "1") not in {"0", "false", "no", ""}

try:
    import fcntl
except ImportError:  # pragma: no cover - local Windows unit tests use the fallback.
    fcntl = None


def broker_command(command: dict, timeout: int = 3) -> dict:
    """Best-effort websocket command to the browser42 broker (close tab group)."""
    from websockets.sync.client import connect as websocket_connect
    with websocket_connect(BROKER, open_timeout=timeout, close_timeout=1) as socket:
        socket.send(json.dumps({"role": "client", "command": {"protocolVersion": 1, **command}}))
        return json.loads(socket.recv(timeout=timeout + 2))


def span_push(payload: dict) -> None:
    """Best-effort span ingest; monitoring must never break the sweep."""
    if not SPANS_ENABLED:
        return
    try:
        request = Request(SPANS_URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=1.5):
            pass
    except Exception:
        pass


def span_close_tab(slug: str, opened_at: int, status: str = "error") -> None:
    end_ms = int(time.time() * 1000)
    started_ms = opened_at * 1000
    span_push({
        "id": f"b42tab:{slug}", "src": "browser42", "svc": f"tab:{slug}", "svcid": f"tab:{slug}",
        "label": f"🖥️ {slug}", "status": status, "s": started_ms, "e": end_ms, "d": max(0, end_ms - started_ms),
        "meta": {"kind": "tab", "slug": slug},
    })


def span_watchdog_stale(slug: str, reason: str, stage: str, created_at: int,
                        first_activity_at: int, last_activity_at: int, current: int) -> None:
    """Emit a point span whenever the watchdog marks a task stale (same conventions as task-runner.py)."""
    now_ms = int(current) * 1000
    span_push({
        "id": f"b42:watchdog:{slug}:{reason}:{int(current)}", "src": "browser42", "svc": "watchdog", "svcid": slug,
        "label": f"stall:{reason}", "status": "failed", "s": now_ms, "e": now_ms, "d": 0,
        "meta": {"slug": slug, "reason": reason, "stage": stage, "created_at": created_at,
                 "first_activity_at": first_activity_at, "last_activity_at": last_activity_at},
    })


@contextmanager
def task_lock(path: Path):
    lock_path = path.parent / ".lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def mark_stale(path: Path, task: dict, current: int) -> bool:
    with task_lock(path):
        task = json.loads(path.read_text(encoding="utf-8"))
        if task.get("state") not in ACTIVE:
            return False
        heartbeat = int(task.get("heartbeat_at", 0))
        stage = task.get("stage", "allocated")
        created_at = int(task.get("created_at", heartbeat))
        # Legacy/old-format tasks may lack first_activity_at; anchor on created_at — but
        # ONLY once the task has left the queue. An allocated task has done no activity and
        # must be governed exclusively by queue_timeout.
        raw_first = task.get("first_activity_at")
        first_activity = int(raw_first) if raw_first else (created_at if stage != "allocated" else 0)
        failure = None
        # FINAL-ARCHITECTURE clocks (see ai/context/browser42-final-architecture.md):
        # - a queued (allocated) task is NEVER killed by a wall clock; TOTAL_SECONDS is the
        #   maximum time a start may sit in the queue before the caller gives up on it.
        # - once a task has done ANY activity, the activity clock governs it: stalled iff
        #   nothing happened (heartbeat / stage transition / command) for STALL_SECONDS.
        # - TOTAL_SECONDS also caps total wall time measured from FIRST ACTIVITY, so a task
        #   that keeps heartbeating forever still cannot run away.
        last_activity = heartbeat
        for timing in (task.get("stage_timings") or {}).values():
            entered = int(timing.get("entered_at", 0))
            if entered > last_activity:
                last_activity = entered
        if stage == "allocated" and current - last_activity > ALLOCATED_STALL_SECONDS:
            failure = {"code": "queue_timeout", "message": f"task sat in the allocation queue with no activity for {ALLOCATED_STALL_SECONDS}s", "stage": stage}
        elif stage == "allocated" and current - created_at > TOTAL_SECONDS:
            failure = {"code": "queue_timeout", "message": "task never left the allocation queue", "stage": stage}
        elif first_activity and current - first_activity > TOTAL_SECONDS:
            failure = {"code": "task_timeout", "message": "task exceeded total budget since first activity", "stage": stage}
        elif first_activity and current - last_activity > STALL_SECONDS:
            failure = {"code": "stall_timeout", "message": f"no activity for {STALL_SECONDS}s", "stage": stage}
        if failure is None:
            return False
        task["state"] = "stalled"
        task["updated_at"] = current
        task["revision"] = task.get("revision", 0) + 1
        task["failure"] = failure
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        with (path.parent / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": current, "event": "watchdog_stalled", "state": "stalled", "failure": failure}, sort_keys=True) + "\n")
        # Release the tab group and close its lane on any-concurrency. Best-effort.
        try:
            broker_command({"action": "close", "slug": task.get("slug")})
        except Exception:
            pass
        try:
            span_close_tab(task.get("slug"), created_at, "error")
        except Exception:
            pass
        try:
            span_watchdog_stale(task.get("slug"), failure["code"], stage, created_at, first_activity, last_activity, current)
        except Exception:
            pass
        return True


def sweep(current=None) -> list[str]:
    current = int(time.time()) if current is None else current
    stalled = []
    for path in TASKS.glob("*/task.json"):
        try:
            task = json.loads(path.read_text(encoding="utf-8"))
            if mark_stale(path, task, current):
                stalled.append(task.get("slug", path.parent.name))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return stalled


if __name__ == "__main__":
    while True:
        for slug in sweep():
            print(f"task stalled: {slug}", flush=True)
        time.sleep(INTERVAL)