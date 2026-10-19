#!/usr/bin/env python3
"""Internal JSON request runner for Browser42 task operations.

v2 (final-architecture slice):
- Work commands queue for a slot (bounded wait) instead of failing instantly; reads
  (status/heartbeat) never contend with work slots at all.
- Subprocesses are tracked and killed on request-budget timeout, so an interrupted client
  can no longer hold a slot for the whole budget.
- Every command is emitted as a span to any-concurrency (POST /ingest/span) by the manager it
  runs, so console.localhost > כל מקביל shows a live browser42 lane per task/command.
- Adds the platform-side `goal` command: goto -> settle -> extract -> screenshot ->
  verify -> finish in one request, no model turns.
"""

import json
import os
import signal
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PROTOCOL_VERSION = 1
ALLOWED = {
    "start": (3, 4),
    "inspect": (2, 3),
    "act": (3, 3),
    "goto": (3, 3),
    "click": (3, 3),
    "fill": (4, 4),
    # login <slug> <site> — the SITE, never the credential: group-manager leases it from the
    # credential plane and types it into the page, so the value is not in argv, in the journal or in
    # the response. Keeping the arity at exactly 3 is the guard that stops a caller from passing one.
    "login": (3, 3),
    "press": (3, 4),
    "wait": (2, 3),
    "extract": (3, 3),
    "screenshot": (2, 4),
    # read <slug> [max-chars] — the WHOLE page as text in one answer: it walks the page's own scroll
    # container and stitches the steps by overlap, so the shared browser's small viewport stops
    # deciding how much context an agent can have.
    "read": (2, 3),
    # captcha <slug> [detect | click <index>] — a human-verification challenge lives in a
    # cross-origin frame that `inspect` cannot see; this verb reads it (instruction, targets in page
    # coordinates, a picture) and presses ONE target with a human-like click. Never a solver service.
    "captcha": (3, 4),
    "verify": (2, 2),
    "finish": (2, 2),
    "status": (2, 2),
    "heartbeat": (2, 2),
    "goal": (4, 4),
}
# Read commands never take a work slot — monitoring must not starve owning agents.
READ_COMMANDS = {"status", "heartbeat"}
# Effective runner budget must stay aligned with Compose
# (BROWSER42_TASK_REQUEST_SECONDS:-300) and the client timeout (310s).
TIMEOUT_SECONDS = int(os.environ.get("BROWSER42_TASK_REQUEST_SECONDS", "300"))
# Cap concurrent manager subprocesses; excess work commands queue (bounded wait) instead
# of failing instantly, so parallel agents + retries never hit a hard runner_busy wall.
# ONE at a time by default: parallel lanes keep their tabs/lanes open concurrently, but
# two heavy ad-heavy evaluates against the single shared Chrome saturate it (0805g).
MAX_CONCURRENT = int(os.environ.get("BROWSER42_TASK_MAX_CONCURRENT", "1"))
QUEUE_WAIT_SECONDS = float(os.environ.get("BROWSER42_TASK_QUEUE_SECONDS", "300"))


class RunnerState:
    def __init__(self, max_concurrent: int) -> None:
        self._semaphore = threading.Semaphore(max_concurrent)
        self._active: set[str] = set()
        self._queued = 0
        self._lock = threading.Lock()

    def acquire(self, request_id: str, wait: float) -> tuple[bool, int]:
        """Blocking acquire with a bounded wait. Returns (acquired, queue_depth_seen)."""
        with self._lock:
            depth = self._queued
        acquired = self._semaphore.acquire(timeout=max(0.0, wait))
        if acquired:
            with self._lock:
                self._active.add(request_id)
        return acquired, depth

    def queue_enter(self) -> int:
        with self._lock:
            self._queued += 1
            return self._queued

    def queue_exit(self) -> None:
        with self._lock:
            self._queued = max(0, self._queued - 1)

    def release(self, request_id: str) -> None:
        with self._lock:
            self._active.discard(request_id)
        self._semaphore.release()

    def snapshot(self) -> dict:
        with self._lock:
            return {"active": len(self._active), "queued": self._queued, "requests": sorted(self._active)}


def validate_arguments(arguments: object) -> list[str]:
    if not isinstance(arguments, list) or not arguments or not all(isinstance(value, str) and value for value in arguments):
        raise ValueError("argv must be a nonempty string list")
    command = arguments[0]
    bounds = ALLOWED.get(command)
    if bounds is None:
        raise ValueError("unsupported task command")
    if not bounds[0] <= len(arguments) <= bounds[1]:
        raise ValueError("invalid argument count for task command")
    return arguments


def run_task(arguments: list[str], request_id: str) -> tuple[int, dict]:
    """Run one task command, and make sure its WHOLE process tree dies with it.

    ⚠ The child is not one process. group-manager.py drives Playwright, which spawns a node driver
    and a Chromium helper; killing only the direct child on the request budget (`process.kill()`)
    orphans that tree, and an orphan does not go quiet — it keeps burning CPU against a browser that
    is no longer answering. Measured 2026-09-27 and again 2026-09-28: 33–39 orphaned Playwright
    processes piled up in this container, the guest went to load ~90–200 on 4 vCPUs, and the memory
    pressure that followed is what OOM-killed Chrome (and, before the profile fixes, cost a login).
    That is a self-amplifying loop: the busier the host, the more tasks time out, the more orphans.

    So the child gets its OWN process group (`start_new_session=True`) and the timeout path kills
    the GROUP, not the leader. Nothing else about the protocol changes.
    """
    environment = os.environ.copy()
    environment["BROWSER42_REQUEST_ID"] = request_id
    process = subprocess.Popen(
        [sys.executable, "/group-manager.py", "task", *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, _stderr = process.communicate(timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        kill_tree(process)
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        raise
    try:
        payload = json.loads(stdout)
        payload.setdefault("requestId", request_id)
    except json.JSONDecodeError:
        payload = {"ok": False, "requestId": request_id, "error": {"code": "runner_protocol_error", "message": "task command emitted invalid JSON"}}
    return process.returncode, payload


def kill_tree(process: subprocess.Popen) -> None:
    """SIGKILL the child's whole process group; never let a wedged task leave CPU behind.

    The group is the child's OWN (`start_new_session=True` above), so this cannot reach this runner
    or its siblings. If the group is already gone, fall back to the direct child — the one case
    where `killpg` raises is the case where there is nothing left to kill.
    """
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        process.kill()


def build_health() -> dict:
    return {
        "ok": True,
        "service": "browser42-task-runner",
        "version": PROTOCOL_VERSION,
        "maxConcurrent": MAX_CONCURRENT,
        "queueWaitSeconds": QUEUE_WAIT_SECONDS,
        "requestBudgetSeconds": TIMEOUT_SECONDS,
        **STATE.snapshot(),
    }


def build_response(request: object) -> tuple[int, dict]:
    try:
        arguments = validate_arguments(request.get("argv"))
    except ValueError as error:
        return 400, {"ok": False, "error": {"code": "invalid_request", "message": str(error)}}
    request_id = request.get("requestId") or uuid.uuid4().hex
    slug = arguments[1] if len(arguments) > 1 else ""
    is_read = arguments[0] in READ_COMMANDS
    if not is_read:
        STATE.queue_enter()
        try:
            acquired, _depth = STATE.acquire(request_id, QUEUE_WAIT_SECONDS)
        finally:
            STATE.queue_exit()
        if not acquired:
            return 429, {
                "ok": False,
                "requestId": request_id,
                "error": {"code": "runner_busy", "message": f"runner queue wait ({QUEUE_WAIT_SECONDS:.0f}s) exhausted at cap {MAX_CONCURRENT}"},
            }
    try:
        returncode, payload = run_task(arguments, request_id)
    except subprocess.TimeoutExpired:
        return 504, {
            "ok": False,
            "requestId": request_id,
            "error": {"code": "runner_timeout", "message": f"task request exceeded {TIMEOUT_SECONDS}s budget"},
        }
    finally:
        if not is_read:
            STATE.release(request_id)
    return 200, {**payload}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - HTTP handler API
        if self.path != "/healthz":
            self.respond(404, {"ok": False, "error": {"code": "not_found", "message": "unknown endpoint"}})
            return
        self.respond(200, build_health())

    def do_POST(self) -> None:  # noqa: N802 - HTTP handler API
        if self.path != "/v1/task":
            self.respond(404, {"ok": False, "error": {"code": "not_found", "message": "unknown endpoint"}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as error:
            self.respond(400, {"ok": False, "error": {"code": "invalid_request", "message": str(error)}})
            return
        status, payload = build_response(request)
        self.respond(status, payload)

    def respond(self, status: int, payload: dict) -> None:
        body = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


STATE = RunnerState(MAX_CONCURRENT)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8766), Handler).serve_forever()