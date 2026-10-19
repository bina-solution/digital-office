#!/usr/bin/env python3
"""
browser42 group manager — named tab groups in the ONE shared browser.

Each agent session owns a GROUP: a stable slug mapped to its own set of tabs in
the single shared Chromium. Groups SHARE everything — same browser, same cookie
jar, same /view — by design; the group is the boundary that stops simultaneous
agents from navigating each other's tabs. You reconnect, your slug finds YOUR
tabs (never another agent's), and the reaper spares them.

  * Slug — stable kebab id minted once per session (e.g. "browser42-install").
    The SAME slug in the same session = the SAME group = the SAME tabs, forever.
    Never re-mint it mid-session; use the value `session` printed.
  * Tag — every group's tabs carry window.name "b42g:<slug>". The anchor (first)
    tab is created on first use; later calls re-find it by tag, never by index.
  * Shared — all groups live in contexts[0]: same cookies/logins/profile. No
    isolation. The tag is the only boundary, and it is structural in the CLI.
  * Persist — cookies/logins live in /profile and survive restarts; tabs are
    in-memory, so after a browser restart get-or-use re-creates your anchor tab.
  * Cleanup — `close <slug>` closes exactly that group's tabs; `gc` reaps stale.

Data: /data/groups/<slug>/group.json   (host: data/browser42/groups/<slug>/group.json)
Env: CDP (default http://browser42-browser:9222)

Verbs:
  session [name]   resolve/mint the stable slug; write manifest; print it
    open <slug> <url> get-or-use the grouped direct-site tab; print the attach snippet
  list             list groups + live tab counts
  close <slug>     close exactly this group's tabs; remove its manifest
  gc [--stale N]   close + remove groups idle > N hours (default 24)
"""
import json
import hashlib
import os
import re
import shutil
import sys
import time
import uuid
import base64
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright
from websockets.sync.client import connect as websocket_connect

CDP = os.environ.get("CDP", "http://browser42-browser:9222")
BROKER = os.environ.get("BROKER", "ws://127.0.0.1:8765")
DATA = Path(os.environ.get("DATA", "/data"))
GROUPS = DATA / "groups"
TASKS = DATA / "tasks"
CURRENT = GROUPS / ".current"
PREFIX = "b42g:"
TAB_TAG = "b42:"  # reaper's spare namespace — group tags extend it
COLORS = ["cyan", "blue", "green", "orange", "pink", "purple", "red", "yellow"]
ACTIVE_STATES = {"allocated", "active", "verifying"}
FINAL_STATES = {"accepted", "rejected", "stalled", "finished"}
TASK_PROTOCOL_VERSION = 1
HARD_TAB_CAP = 6  # anchor page + up to 5 task tabs; mirrors the reaper MAX_TABS
# any-concurrency span ingest (layer-2 service on the shared traefik network). Every CLI
# command and every open tab is mirrored as a span so console.localhost > כל מקביל shows a
# live lane per tab for as long as the tab is open, plus full command I/O.
SPANS_URL = os.environ.get("ANY_CONCURRENCY_SPANS_URL", "http://any-concurrency:8080/ingest/span")
SPANS_ENABLED = os.environ.get("BROWSER42_SPANS_ENABLED", "1") not in {"0", "false", "no", ""}
# Every CLI response carries a tab census; above this many open tabs the response warns so
# agents always remember to finish/close tasks and keep the browser lean.
TAB_WARN_THRESHOLD = int(os.environ.get("BROWSER42_TAB_WARN_THRESHOLD", "4"))
# How long a `.current` marker is a valid "active session" lease before the CLI mints a new
# slug. Prevents a stale agent's marker from hijacking a simultaneous session's identity.
SESSION_TTL_SECONDS = int(os.environ.get("BROWSER42_SESSION_TTL_SECONDS", "43200"))  # 12h

try:
    import fcntl
except ImportError:  # pragma: no cover - local Windows unit tests use the fallback.
    fcntl = None


class BrowserTaskError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def error_code(error: Exception) -> str:
    if isinstance(error, BrowserTaskError):
        return error.code
    message = str(error).casefold()
    if "detached" in message:
        return "detached_target"
    if "502" in message or "cdp" in message or "connection" in message:
        return "transient_cdp_failure"
    if "timeout" in message:
        return "operation_timeout"
    return "internal_error"


# -- any-concurrency spans: one lane per open tab + full CLI I/O ----------------
# Every open task tab is mirrored as a long-lived span (svc "tab:<slug>") that stays
# open for as long as the tab is open, and every CLI command is mirrored as a span on
# that same lane carrying its full request/response, so console.localhost > כל מקביל
# shows the whole browser story per tab. Best-effort only — monitoring must never
# break task execution.

_CLI: dict = {}  # set by main() for task verbs: started_at/argv/command/slug


def span_push(payload: dict) -> None:
    if not SPANS_ENABLED:
        return
    try:
        request = Request(SPANS_URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=1.5):
            pass
    except Exception:
        pass


def _clip(value: object, limit: int = 6000) -> str:
    try:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = str(value)
    return text if len(text) <= limit else text[:limit] + f" … (+{len(text) - limit} chars)"


def span_open_tab(slug: str, opened_at: int, url: str) -> None:
    span_push({
        "id": f"b42tab:{slug}", "src": "browser42", "svc": f"tab:{slug}", "svcid": f"tab:{slug}",
        "label": f"🖥️ {slug}", "status": "running", "s": opened_at * 1000,
        "meta": {"kind": "tab", "slug": slug, "url": url},
    })


def span_close_tab(slug: str, opened_at: int, status: str = "ok") -> None:
    end_ms = int(time.time() * 1000)
    started_ms = opened_at * 1000
    span_push({
        "id": f"b42tab:{slug}", "src": "browser42", "svc": f"tab:{slug}", "svcid": f"tab:{slug}",
        "label": f"🖥️ {slug}", "status": status, "s": started_ms, "e": end_ms, "d": max(0, end_ms - started_ms),
        "meta": {"kind": "tab", "slug": slug},
    })


def span_command(slug: str, command: str, argv: list, started_at: int, ok: bool, response: dict) -> None:
    end_ms = int(time.time() * 1000)
    started_ms = started_at * 1000
    span_push({
        "id": f"b42cmd:{slug}:{uuid.uuid4().hex[:12]}", "src": "browser42",
        "svc": f"tab:{slug}" if slug else "browser42", "svcid": f"tab:{slug}" if slug else "cli",
        "label": f"{command} · {slug}", "status": "ok" if ok else "error",
        "s": started_ms, "e": end_ms, "d": max(0, end_ms - started_ms),
        "meta": {"kind": "command", "command": command, "slug": slug, "argv": argv[:8], "response": _clip(response)},
    })


def span_stage(slug: str, stage: str, started_at: int, url: str = "", detail: dict | None = None) -> None:
    """Fine-grained browsing-event span on the tab lane (goto/settle/scan/extract/...)
    so the timeline shows the actual browsing sequence, not one collapsed bar."""
    end_ms = int(time.time() * 1000)
    started_ms = started_at * 1000
    meta: dict = {"kind": "stage", "slug": slug, "stage": stage}
    if url:
        meta["url"] = url
    if detail:
        for key, value in detail.items():
            meta[key] = _clip(value, 800) if isinstance(value, str) else value
    span_push({
        "id": f"b42stage:{slug}:{uuid.uuid4().hex[:12]}", "src": "browser42",
        "svc": f"tab:{slug}", "svcid": f"tab:{slug}",
        "label": f"▸ {stage} · {slug}", "status": "ok",
        "s": started_ms, "e": end_ms, "d": max(0, end_ms - started_ms),
        "meta": meta,
    })


def broker_command_fast(command: dict, timeout: int = 3) -> dict:
    with websocket_connect(BROKER, open_timeout=timeout, close_timeout=1) as socket:
        socket.send(json.dumps({"role": "client", "command": {"protocolVersion": TASK_PROTOCOL_VERSION, **command}}))
        return json.loads(socket.recv(timeout=timeout + 2))


def release_tabs(slug: str, created_at: int, status: str = "ok") -> None:
    """Close the task's tab group via the broker and VERIFY through `list` that the
    session is gone, retrying once. A silent leak (the old bare `except: pass`) left
    an ad-heavy renderer alive forever — the exact thing that saturates Chrome's
    compositor and takes CDP down for everyone. The reaper also sweeps tabs whose
    task is terminal, but finish must not rely on the janitor."""
    for _attempt in range(2):
        try:
            broker_command_fast({"action": "close", "slug": slug})
        except Exception:
            pass
        try:
            sessions = broker_command_fast({"action": "list"}).get("sessions") or []
        except Exception:
            sessions = [{"slug": slug}]  # unverifiable — assume still open, retry
        if not any(session.get("slug") == slug for session in sessions):
            break
        time.sleep(0.5)
    try:
        span_close_tab(slug, created_at, status)
    except Exception:
        pass


def tab_census() -> dict:
    """Live tab census from the extension (sessions + open tabs). Best-effort."""
    try:
        result = broker_command_fast({"action": "list"})
        sessions = result.get("sessions") or [] if result.get("ok") else []
    except Exception:
        sessions = []
    open_tabs = sum(int(session.get("openTabs", 0) or 0) for session in sessions)
    census = {
        "sessions": len(sessions),
        "openTabs": open_tabs,
        "slugs": [session.get("slug") for session in sessions if session.get("slug")],
    }
    if open_tabs > TAB_WARN_THRESHOLD:
        census["warning"] = (
            f"⚠️ {open_tabs} browser tabs are open (>{TAB_WARN_THRESHOLD}). Every open tab holds a lane in "
            "any-concurrency and real browser memory — finish or close tasks you no longer need "
            "(bbox b42 task finish <slug> / bbox b42 close <slug>) before starting new ones."
        )
    return census


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "auto"


def canonical_slug(value: str) -> str:
    if not value or value != slugify(value):
        raise ValueError("task slug must be a nonempty lowercase kebab-case value and is never rewritten")
    return value


def _name(pg, timeout: int = 2000):
    # BOUND the evaluate: tab scans (group_tabs -> every task_connection, the start
    # ownership loop, the reaper) run this against EVERY page. Under parallel tasks a
    # a saturated ad-heavy renderer can wedge evaluate for the full default
    # timeout — one slow tab then multiplies into minutes of latency on EVERY other
    # task's commands (the reference iteration's 59-139s starts and 18-178s inspects).
    # A tag read that can't complete in 2s is treated as "not ours" and re-checked on
    # the next scan; ownership claims are re-driven by the extension either way.
    # NOTE: Page.evaluate() has NO `timeout` kwarg — passing one raises TypeError
    # (silent '' return here hid every tag and made scans see 0 tabs forever,
    # 2026-08-04 regression). Use the CDP session's Runtime.evaluate instead; it
    # answers a plain window.name read in milliseconds (probed live: 0.04s).
    # CDPSession.send() itself also takes NO kwargs (method, params only) — the
    # timeout param here is retained for caller compatibility only.
    try:
        session = pg.context.new_cdp_session(pg)
        try:
            result = session.send("Runtime.evaluate", {"expression": "window.name", "returnByValue": True})
        finally:
            try:
                session.detach()
            except Exception:
                pass
        value = result.get("result", {}).get("value")
        return value if isinstance(value, str) else ""
    except Exception:
        return ""


def manifest(slug: str) -> Path:
    return GROUPS / slug / "group.json"


def task_path(slug: str) -> Path:
    return TASKS / slug / "task.json"


def task_events_path(slug: str) -> Path:
    return TASKS / slug / "events.jsonl"


def now() -> int:
    return int(time.time())


@contextmanager
def task_lock(slug: str):
    path = TASKS / slug / ".lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_task(task: dict) -> None:
    path = task_path(task["slug"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_task(slug: str) -> dict:
    path = task_path(slug)
    if not path.exists():
        raise BrowserTaskError("task_not_found", f"task '{slug}' does not exist")
    return json.loads(path.read_text(encoding="utf-8"))


def journal(task: dict, event: str, **fields) -> None:
    record = {
        "at": now(),
        "event": event,
        "state": task["state"],
        "stage": task.get("stage", "allocated"),
        **fields,
    }
    events = task_events_path(task["slug"])
    events.parent.mkdir(parents=True, exist_ok=True)
    with events.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def transition(task: dict, state: str, event: str, stage: str | None = None, **fields) -> None:
    with task_lock(task["slug"]):
        current = read_task(task["slug"])
        if current["state"] in FINAL_STATES:
            raise BrowserTaskError("terminal_task", f"task '{task['slug']}' is terminal ({current['state']})")
        if current.get("revision", 0) != task.get("revision", 0):
            raise BrowserTaskError("stale_task_revision", f"task '{task['slug']}' changed while this operation was running")
        current["evidence"] = task.get("evidence", current.get("evidence", {}))
        # `captcha` is the same kind of carried state as evidence: the challenge bookkeeping
        # (clicks spent, what was asked, what was clicked) belongs to the task, not to the call.
        if "captcha" in task:
            current["captcha"] = task["captcha"]
        current["state"] = state
        current["updated_at"] = now()
        current["heartbeat_at"] = current["updated_at"]
        current["revision"] = current.get("revision", 0) + 1
        if stage:
            current["stage"] = stage
            # Always refresh entered_at on every transition INTO a stage, INCLUDING re-entry
            # (inspecting -> acting -> inspecting). The watchdog activity clock reads these;
            # the old setdefault left a stale entered_at and killed actively-working tasks.
            current.setdefault("stage_timings", {})[stage] = {"entered_at": current["updated_at"]}
        if stage and stage != "allocated":
            current.setdefault("first_activity_at", current["updated_at"])
        journal(current, event, **fields)
        write_task(current)
        task.clear()
        task.update(current)


def emit(payload: dict, code: int = 0) -> None:
    payload.setdefault("protocol_version", TASK_PROTOCOL_VERSION)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
    os._exit(code)


def done(payload: dict, code: int = 0) -> None:
    """Emit a CLI response, mirroring it as a command span + tab census first.

    Every task command carries its full argv/response as a span on the tab's lane
    (R3) and a live tab census on the response (R2). Best-effort — monitoring must
    never break task execution.
    """
    if _CLI:
        try:
            span_command(_CLI["slug"], _CLI["command"], _CLI.get("argv", []), _CLI["started_at"], ok=bool(payload.get("ok")), response=payload)
        except Exception:
            pass
    try:
        census = tab_census()
        payload = {**payload, "tabs": census}
        if census.get("warning"):
            payload["warning"] = census["warning"]
    except Exception:
        pass
    emit(payload, code)


def task_error(error: Exception) -> None:
    if isinstance(error, json.JSONDecodeError):
        code = "invalid_json"
    elif isinstance(error, ValueError):
        code = "invalid_request"
    else:
        code = error_code(error)
    done({"ok": False, "error": {"code": code, "message": str(error)}}, 2)


def direct_url(url: str) -> str:
    parsed = urlparse(url or "")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BrowserTaskError("invalid_url", "task requires a direct http(s) website URL")
    return url


def retry_safe(task: dict, stage: str, operation, attempts: int = 2):
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as error:
            code = error_code(error)
            if attempt == attempts or code not in {"transient_cdp_failure", "detached_target", "operation_timeout"}:
                raise BrowserTaskError(code, str(error)) from error
            journal(task, "retrying", retry_stage=stage, attempt=attempt, error_code=code)
            time.sleep(0.25 * attempt)


def touch(slug: str) -> dict:
    GROUPS.mkdir(parents=True, exist_ok=True)
    m = manifest(slug)
    m.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if m.exists():
        try:
            data = json.loads(m.read_text())
        except Exception:
            pass
    data.setdefault("slug", slug)
    data.setdefault("created_at", int(time.time()))
    data["last_seen"] = int(time.time())
    m.write_text(json.dumps(data, indent=2))
    return data


def resolve_slug(name=None, return_source=False) -> tuple | str:
    """Resolve the stable session slug. Layers (see ai/context/browser42-groups.md):

    1. explicit name — always wins; same name => same slug forever.
    2. BROWSER42_SESSION env — per-session identity injected by the agent host
       (the "automatic" layer: distinct + stable per agent session, no collision).
    3. `.current` marker — single-active-session convenience; reused only while fresh
       (SESSION_TTL), so a stale agent can't hijack a simultaneous session's slug.
    4. mint `auto-*` — last resort, written to `.current`.

    Returns (slug, source) when return_source is set, else just the slug.
    """
    now = int(time.time())
    if name:
        return (slugify(name), "name") if return_source else slugify(name)
    if os.environ.get("BROWSER42_SESSION"):
        slug = slugify(os.environ["BROWSER42_SESSION"])
        return (slug, "env") if return_source else slug
    if CURRENT.exists():
        try:
            marker_slug = CURRENT.read_text().strip()
            age = now - int(CURRENT.stat().st_mtime)
            if marker_slug and 0 <= age <= SESSION_TTL_SECONDS:
                CURRENT.touch()  # refresh the single-session lease
                return (marker_slug, "current") if return_source else marker_slug
        except Exception:
            pass
    slug = f"auto-{uuid.uuid4().hex[:8]}"
    GROUPS.mkdir(parents=True, exist_ok=True)
    CURRENT.write_text(slug)
    return (slug, "minted") if return_source else slug


def group_tabs(b, slug, timeout: int = 2000):
    """The group's tabs in the SHARED default context."""
    tag = PREFIX + slug
    out = []
    for ctx in b.contexts:
        for i, pg in enumerate(ctx.pages):
            # page 0 is the human /view anchor — skip it UNLESS it's tagged ours
            if i == 0 and not _name(pg, timeout).startswith(PREFIX):
                continue
            if _name(pg, timeout) == tag:
                out.append(pg)
    return out


# One Playwright connection per CLI process. sync_playwright().start() REFUSES to start while
# another connection's loop is still marked running in this thread ("Playwright Sync API inside
# the asyncio loop"), so nested connect() calls — task_goal -> task_action/task_verify, each via
# task_connection() — must reuse a single connection. CLI commands are one-shot processes
# (runner Popen), so a process-global cache is exactly right; if the cached browser dropped,
# dispose it and reconnect.
_CONNECTION = None


def connect():
    global _CONNECTION
    if _CONNECTION is not None:
        playwright, browser = _CONNECTION
        if browser.is_connected():
            return playwright, browser
        try:
            playwright.stop()
        except Exception:
            pass
        _CONNECTION = None
    last_error = None
    for _ in range(10):
        playwright = None
        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.connect_over_cdp(CDP)
            _CONNECTION = (playwright, browser)
            return playwright, browser
        except Exception as error:
            # a started-but-unconnected playwright keeps its loop marked running in this
            # thread and would poison every retry — stop it before the next attempt.
            if playwright is not None:
                try:
                    playwright.stop()
                except Exception:
                    pass
            last_error = error
            time.sleep(0.5)
    raise RuntimeError(f"Browser42 CDP unavailable: {last_error}")


def reconnect():
    """Dispose the cached CDP connection and open a fresh one.

    Required after the extension creates a tab: a Playwright connection that was
    live BEFORE the tab existed never learns about it — cloakserve's CDP proxy
    does not relay Target.targetCreated to already-connected clients (proven
    2026-08-04: allocate while connected -> the new page stayed invisible for
    minutes; reconnect -> it appeared instantly). Every ownership scan must
    therefore run on a connection made AFTER allocate. Without this, task_start
    scanned 0 tabs for the whole 240s deadline ("did not acquire ownership").
    """
    global _CONNECTION
    if _CONNECTION is not None:
        playwright, _browser = _CONNECTION
        _CONNECTION = None
        try:
            playwright.stop()
        except Exception:
            pass
    return connect()


def cmd_session(name=None):
    fresh = name == "--fresh"
    if fresh:
        name = None
    slug, source = resolve_slug(name, return_source=True)
    if fresh:
        # Clean-slate: clear the previous attempt's group tabs + manifest, but KEEP the
        # slug — the session identity never changes within a session (browser42-groups.md).
        clear_group(slug)
    touch(slug)
    print(slug)
    print(f"# session identity: {source} (stable for this session; reuse the slug verbatim)", file=sys.stderr)


def broker_command(command):
    # Recv budget must EXCEED the broker's own command wait
    # (BROWSER42_BROKER_WAIT_SECONDS, 240s): if the client gives up first it
    # closes its socket while the broker is still waiting for the extension,
    # and the broker's result-send dies on a closed socket — that race was the
    # "connection handler failed" / extension-flapping root cause (0805r-t).
    last_error = None
    for _ in range(20):
        try:
            with websocket_connect(BROKER, open_timeout=2, close_timeout=1) as socket:
                socket.send(json.dumps({"role": "client", "command": {"protocolVersion": TASK_PROTOCOL_VERSION, **command}}))
                result = json.loads(socket.recv(timeout=250))
            if result.get("ok"):
                return result
            error = result.get("error", "broker command failed")
            if isinstance(error, dict):
                raise BrowserTaskError(error.get("code", "broker_error"), error.get("message", "broker command failed"))
            last_error = error
        except Exception as error:
            last_error = str(error)
        time.sleep(0.5)
    raise RuntimeError(last_error or "browser42 broker is unavailable")


def cmd_open(slug, url=None):
    if url:
        # --- URL provided: allocate a native Chrome Tab Group via the extension broker ---
        if not slug:
            raise ValueError("group requires an explicit slug")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("group requires a direct http(s) website URL")
        tag = PREFIX + slug
        digest = hashlib.sha256(slug.encode()).digest()
        color = COLORS[digest[0] % len(COLORS)]
        allocation = broker_command({
            "action": "allocate",
            "slug": slug,
            "label": slug,
            "color": color,
            "url": url,
        })
        p, b = reconnect()
        try:
            tabs = []
            for _ in range(150):
                tabs = group_tabs(b, slug)
                if tabs:
                    break
                b.contexts[0].pages[0].wait_for_timeout(100)
            if not tabs:
                broker_command({"action": "close", "slug": slug})
                raise RuntimeError(f"allocated tab {tag} did not acquire ownership")
            data = touch(slug)
            data.update({
                "url": url,
                "color": color,
                "tab_id": allocation.get("tabId"),
                "group_id": allocation.get("groupId"),
            })
            manifest(slug).write_text(json.dumps(data, indent=2))
            print(f"GROUP={tag}  TABS={len(tabs)}")
            print("# copy-paste attach snippet (work on `me` only; end with os._exit(0)):")
            print(SNIPPET.format(TAG=tag))
        finally:
            sys.stdout.flush()
            os._exit(0)  # never tear down shared state
    # --- Lightweight get-or-use: no URL → auto-resolve slug; reconnect to existing group or create blank anchor ---
    if not slug:
        slug = resolve_slug(None)
    tag = PREFIX + slug
    p, b = connect()
    try:
        tabs = group_tabs(b, slug)
        if not tabs:
            ctx = b.contexts[0]
            pg = ctx.new_page()
            pg.goto("about:blank")
            pg.evaluate(f"window.name = {tag!r}")
            tabs = [pg]
        data = touch(slug)
        data["url"] = data.get("url", tabs[0].url)
        manifest(slug).write_text(json.dumps(data, indent=2))
        print(f"GROUP={tag}  TABS={len(tabs)}")
        print("# copy-paste attach snippet (work on `me` only; end with os._exit(0)):")
        print(SNIPPET.format(TAG=tag))
    finally:
        sys.stdout.flush()
        os._exit(0)


def cmd_list():
    p, b = connect()
    try:
        rows = []
        for m in sorted(GROUPS.glob("*/group.json")):
            try:
                data = json.loads(m.read_text())
            except Exception:
                data = {"slug": m.parent.name}
            slug = data.get("slug", m.parent.name)
            rows.append({
                "slug": slug,
                "created_at": data.get("created_at"),
                "last_seen": data.get("last_seen"),
                "tabs": len(group_tabs(b, slug)),
            })
        print(json.dumps(rows, ensure_ascii=False))
    finally:
        sys.stdout.flush()
        os._exit(0)


def clear_group(slug):
    """Close exactly this group's tabs (never page 0, never another group's) and remove
    its manifest. The clean-slate primitive shared by `close` and `session --fresh`."""
    result = {"closed": 0}
    try:
        result = broker_command({"action": "close", "slug": slug})
    except Exception as error:
        # Broker may be down (browser restarting); the tab-level cleanup is best-effort.
        print(f"# clear_group: broker close failed for {slug}: {error}", file=sys.stderr)
    m = manifest(slug)
    if m.parent.exists():
        shutil.rmtree(m.parent)
    return result


def cmd_close(slug):
    if not slug:
        print("usage: group-manager.py close <slug>", file=sys.stderr)
        sys.exit(2)
    try:
        result = clear_group(slug)
        # A bare close used to leave the task dir non-terminal and its any-concurrency
        # lane "live" forever (the 0805 UI leak: probe-fix2-0805 stayed an open lane).
        # Mark the task terminal and push the lane-closing span so the UI, the reaper
        # and reconcile_lanes all agree the session is gone.
        tp = task_path(slug)
        if tp.exists():
            try:
                task = json.loads(tp.read_text())
                if task.get("state") not in {"finished", "rejected", "stalled", "closed", "failed"}:
                    task["state"] = "closed"
                    task["updated_at"] = now()
                    tp.write_text(json.dumps(task, ensure_ascii=False, indent=2))
                release_tabs(slug, int(task.get("created_at", now())), "closed")
            except Exception:
                pass
        print(f"closed {result.get('closed', 0)} tab(s) for {PREFIX}{slug}")
    finally:
        sys.stdout.flush()
        os._exit(0)


def cmd_gc(stale_hours):
    p, b = connect()
    now = time.time()
    try:
        for m in sorted(GROUPS.glob("*/group.json")):
            try:
                data = json.loads(m.read_text())
            except Exception:
                continue
            slug = data.get("slug", m.parent.name)
            last = data.get("last_seen", 0)
            if now - last > stale_hours * 3600:
                tabs = group_tabs(b, slug)
                broker_command({"action": "close", "slug": slug})
                shutil.rmtree(m.parent, ignore_errors=True)
                print(f"gc'd stale group {PREFIX}{slug} ({len(tabs)} tab(s))")
    finally:
        sys.stdout.flush()
        os._exit(0)


def handle(value: dict) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "b42h:" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def parse_handle(value: str) -> dict:
    if not value.startswith("b42h:"):
        raise ValueError("action requires a handle returned by task inspect")
    encoded = value[5:] + "=" * (-len(value[5:]) % 4)
    try:
        parsed = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    except Exception as error:
        raise ValueError("invalid Browser42 element handle") from error
    if not isinstance(parsed, dict) or parsed.get("kind") not in {"role", "placeholder", "tag"}:
        raise ValueError("invalid Browser42 element handle")
    return parsed


def locate(page, value: str):
    """Resolve a handle from `task inspect` back to exactly one live element.

    The role strategy is primary, with one documented fallback: a contenteditable EDITOR
    (role=textbox — Facebook's post composer, every Lexical/Draft rich-text box) publishes its
    hint in `aria-placeholder` and has an EMPTY accessible name, so `get_by_role(name=...)` finds
    nothing there while `inspect` named it from that very attribute, and Playwright's
    `get_by_placeholder` only understands real <input>/<textarea> placeholders. Same attribute,
    so the fallback resolves the element inspect already found — never a new guess at a selector.
    """
    target = parse_handle(value)
    if target["kind"] == "role":
        exact = page.get_by_role(target["role"], name=target["name"], exact=True)
        if exact.count() == 0:
            role = json.dumps(target["role"])
            name = json.dumps(target["name"], ensure_ascii=False)
            exact = page.locator(", ".join(
                f"[role={role}][{attribute}={name}]"
                for attribute in ("aria-placeholder", "data-placeholder", "aria-label")
            ))
        return exact.nth(target["nth"])
    if target["kind"] == "placeholder":
        return page.get_by_placeholder(target["name"], exact=True).nth(target["nth"])
    return page.locator(target["tag"]).nth(target["nth"])


def owned_page(browser, slug: str, timeout: int = 2000):
    pages = group_tabs(browser, slug, timeout=timeout)
    if len(pages) != 1:
        raise RuntimeError(f"ownership check failed: expected one live tab, found {len(pages)}")
    return pages[0]


def task_connection(slug: str):
    playwright, browser = connect()
    return playwright, browser, owned_page(browser, slug)


# ── site logins: the credential comes from the credential PLANE, never from argv ────────────────
#
# The agent says `bbox b42 task login <slug> facebook` and nothing else. The username and password
# are leased from `connections` at the moment of typing, under THIS container's own identity, and go
# straight into the page through CDP. They are never printed, never journaled, never part of a
# response — which is the whole point: an agent that drives the browser must be able to sign in to
# the accounts the office holds without ever holding them itself.
#
# Why the lease and not a config file: the credential is written ONCE (connections screen → the row
# this app declares in its own app.json) and every environment, container recreate and profile wipe
# after that re-derives it. Nothing to remember, nothing to copy between environments, nothing in
# .env, and one revocation point.
CONNECTIONS_URL = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")
CONN_SERVICE = os.environ.get("CONN_SERVICE", "browser42-task-runner")
# Credential id convention: `browser42-login-<site>` — the SAME string the app declares in its own
# app.json (connections[] + contributes.connection_providers), so adding a site is a declaration
# there plus one row here, and there is no third place that could disagree.
LOGIN_CREDENTIAL_PREFIX = "browser42-login-"
# Per-site flow. Selector LISTS, tried in order: a login page is markup we do not own and it drifts,
# so the first candidate that resolves wins, and a page where none of them resolves fails LOUDLY
# with the list it tried — inventing a box to type a password into is the one unrecoverable mistake.
LOGIN_FLOWS = {
    "facebook": {
        "url": "https://www.facebook.com/login",
        "user_env": "BROWSER42_LOGIN_FACEBOOK_USER",
        "pass_env": "BROWSER42_LOGIN_FACEBOOK_PASSWORD",
        "user": ["input#email", "input[name=email]", "input[type=email]", "input[type=text]"],
        "pass": ["input#pass", "input[name=pass]", "input[type=password]"],
        "submit": ["button[name=login]", "#loginbutton", "button[type=submit]"],
        # "still signed out" is this element being ON the page; signed in is it being gone.
        "logged_out": "input[name=pass]",
    },
}


def _self_container_id() -> str:
    """Our own container id — the broker's second factor (see platform-base/connections/identity.py).

    Read out of mountinfo exactly as inject.sh does it: docker bind-mounts
    /var/lib/docker/containers/<64-hex>/hostname into every container, so it is always legible from
    inside, and an attacker would need BOTH the network position and this value.
    """
    for path, marker in (("/proc/self/mountinfo", "/containers/"), ("/proc/self/cgroup", "/docker/")):
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    index = line.find(marker)
                    while index != -1:
                        candidate = line[index + len(marker):index + len(marker) + 64]
                        if len(candidate) == 64 and all(c in "0123456789abcdef" for c in candidate):
                            return candidate
                        index = line.find(marker, index + 1)
        except OSError:
            continue
    return ""


def lease_connection(cid: str) -> dict:
    """{ENV_KEY: value} for ONE declared connection, leased under this container's identity.

    A refusal is fatal and is reported AS ITSELF: typing on with an empty password would sign in as
    nobody and leave the failure far away from its cause. The plaintext exists only as the return
    value of this call — there is no file, no env var and no cache.
    """
    headers = {"Content-Type": "application/json"}
    identity = _self_container_id()
    if identity:
        headers["X-Conn-Container"] = identity
    body = json.dumps({"service": CONN_SERVICE, "connections": [cid]}).encode()
    request = Request(f"{CONNECTIONS_URL}/api/broker/lease", data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode(errors="replace")[:300]
        raise BrowserTaskError("credential_refused",
                               f"connections refused the lease for {cid}: {error.code} {detail}") from error
    except URLError as error:
        raise BrowserTaskError("credential_unreachable",
                               f"cannot reach the credential plane ({CONNECTIONS_URL}): {error.reason}") from error
    return payload.get("env") or {}


def login_credential(site: str) -> tuple:
    """(flow, username, password) for `site`, or a failure that says exactly what is missing."""
    flow = LOGIN_FLOWS.get(site)
    if not flow:
        raise BrowserTaskError("unknown_login_site",
                               f"no login flow for '{site}' (known: {', '.join(sorted(LOGIN_FLOWS))})")
    env = lease_connection(LOGIN_CREDENTIAL_PREFIX + site)
    user, password = env.get(flow["user_env"], ""), env.get(flow["pass_env"], "")
    if not password:
        raise BrowserTaskError(
            "credential_not_configured",
            f"the credential plane holds no password for '{site}'. Open חיבורים ומפתחות "
            f"(/a/connections/), fill '{LOGIN_CREDENTIAL_PREFIX}{site}' once — then the browser signs "
            "in by itself and no agent ever sees the value")
    return flow, user, password


def fill_first(page, selectors: list, value: str, what: str, timeout: int = 8000) -> str:
    """Type into the first selector that resolves, and name the one that worked."""
    last = None
    for selector in selectors:
        try:
            handle = page.locator(selector).first
            handle.wait_for(state="visible", timeout=timeout)
            handle.fill(value, timeout=timeout)
            return selector
        except Exception as error:                      # noqa: BLE001 — the next candidate is the point
            last = error
    raise BrowserTaskError("login_selector_missing",
                           f"none of the {what} selectors resolved: {selectors} (last error: {last})")


def task_start(slug: str, url: str, requirements: dict) -> dict:
    slug = canonical_slug(slug)
    url = direct_url(url)
    existing = task_path(slug)
    if existing.exists():
        raise BrowserTaskError("duplicate_slug", f"task '{slug}' already exists; use a new immutable slug")
    if not isinstance(requirements, dict):
        raise BrowserTaskError("invalid_requirements", "task requirements must be a JSON object")
    tag = PREFIX + slug
    digest = hashlib.sha256(slug.encode()).digest()
    color = COLORS[digest[0] % len(COLORS)]
    # Hard backpressure: every open tab is a live ad-heavy renderer in the ONE shared
    # Chrome. Past the cap, allocating more saturates the compositor and takes CDP
    # down for everyone — refuse early with a stable, actionable error instead.
    # Count REAL task tabs from the extension census (openTabs), not the Playwright
    # page count: the latter includes the anchor page, chrome://, the extension page
    # and blank tabs, so a browser with 2 task tabs can report "7 tabs" and false-
    # positive the cap, blocking a valid second parallel lane.
    census = tab_census()
    live_tabs = int(census.get("openTabs", 0))
    if live_tabs > HARD_TAB_CAP:
        raise BrowserTaskError(
            "browser_tab_pressure",
            f"{live_tabs} tabs open in the shared browser (cap {HARD_TAB_CAP}); finish or close "
            "existing tasks before starting new ones (bbox b42 task finish <slug> / bbox b42 close <slug>)",
        )
    # policy deny-popup: ad networks window.open popups that the
    # extension's 'single' policy would ADOPT — closing the original owned tab and
    # re-pointing session.tabId at the popup, so verify's one_live_owned_tab then
    # compares a dead task.tab_id and rejects a perfectly good run (0805c AI lane:
    # 98 records, every other check green, rejected). Task tabs must stay exactly one.
    allocation = broker_command({"action": "allocate", "slug": slug, "label": slug, "color": color, "policy": "deny-popup", "url": url})
    try:
        # Ownership is EXTENSION-authoritative: ask the worker to claim the exact
        # tabId allocate() returned. Python must never adopt a tab by URL match —
        # under two parallel starts on the same URL the URL guess steals the
        # sibling's tab (cross-task mutation) and both tasks then fail verify.
        # Ownership wait: the fresh tab's renderer is loading the ad-heavy site and may
        # not answer window.name evaluates for a while (ad storms on such sites wedge the main
        # thread for tens of seconds — the reference iteration's evaluates needed the
        # full default 30s to get through). Each attempt therefore uses a 30s evaluate
        # timeout so one scan can wait out the saturation instead of missing 150 times
        # at 2s (flash-iteration failure mode), and the whole loop is bounded by a 240s
        # deadline so a dead extension still fails fast enough for the runner budget.
        # The extension also tags window.name at tab creation (persists across
        # navigation), so in the common case the first scan already finds it.
        # A connection established before allocate never sees the extension-created
        # tab (cloakserve's CDP proxy does not relay targetCreated to existing
        # clients), so the ownership scan must run on a FRESH connection.
        _, browser = reconnect()
        page = None
        last_count = -1
        deadline = time.time() + 240
        while time.time() < deadline:
            try:
                pages = group_tabs(browser, slug, timeout=30000)
            except Exception:
                pages = []  # scan hiccup — re-claim below and rescan
            last_count = len(pages)
            if last_count == 1:
                page = pages[0]
                break
            try:
                broker_command({"action": "claim", "slug": slug, "tabId": allocation.get("tabId")})
            except Exception:
                pass
            try:
                browser.contexts[0].pages[0].wait_for_timeout(200)
            except Exception:
                _, browser = reconnect()  # stale/dropped handle — rescan fresh
        if page is None:
            broker_command({"action": "close", "slug": slug})
            raise RuntimeError(
                f"allocated tab {PREFIX}{slug} did not acquire ownership "
                f"(last scan saw {last_count} tagged tab(s))"
            )
        timestamp = now()
        task = {
            "version": TASK_PROTOCOL_VERSION,
            "slug": slug,
            "state": "allocated",
            "stage": "allocated",
            "stage_timings": {"allocated": {"entered_at": timestamp}},
            "created_at": timestamp,
            "updated_at": timestamp,
            "heartbeat_at": timestamp,
            "url": url,
            "requirements": requirements,
            "native_group": {"id": allocation.get("groupId"), "color": color, "label": slug},
            "ownership_generation": allocation.get("generation"),
            "tab_id": allocation.get("tabId"),
            "evidence": {"screenshots": [], "extractions": []},
        }
        write_task(task)
        journal(task, "started", final_url=page.url, native_group=task["native_group"])
        try:
            span_open_tab(slug, task["created_at"], url)
        except Exception:
            pass
        return {
            "ok": True,
            "slug": slug,
            "native_group": task["native_group"],
            "ownership_generation": task["ownership_generation"],
            "task": task,
            "next": ["inspect", "act", "verify", "finish"],
        }
    except Exception:
        broker_command({"action": "close", "slug": slug})
        raise


def parse_start_requirements(value: str | None) -> dict:
    if not value:
        return {}
    if value.isdecimal():
        return {
            "minimum_extractions": 1,
            "minimum_records": int(value),
            "required_record_fields": ["text", "url"],
        }
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise BrowserTaskError(
            "invalid_requirements",
            "requirements must be a JSON object or a plain minimum record count",
        ) from error


def task_inspect(slug: str, query: str = "") -> dict:
    task = read_task(slug)
    _, browser, page = task_connection(slug)
    try:
                raw = retry_safe(task, "inspecting", lambda: page.locator("a,button,input,textarea,select,[role]").evaluate_all("""(elements, query) => {
                    const count = new Map();
                    return elements.filter(element => {
                        const style = getComputedStyle(element);
                        return style.visibility !== 'hidden' && style.display !== 'none' && element.getClientRects().length;
                    }).map(element => {
                        const tag = element.tagName.toLowerCase();
                        const role = element.getAttribute('role') || (tag === 'a' ? 'link' : tag === 'button' ? 'button' : tag === 'input' ? (element.type === 'checkbox' ? 'checkbox' : 'textbox') : tag === 'textarea' ? 'textbox' : '');
                        // NAME SOURCES, in the order that actually finds things. `aria-placeholder` and
                        // `data-placeholder` were added 2026-09-22: a contenteditable EDITOR (Lexical,
                        // Draft — Facebook's post composer, every modern rich-text box) is role=textbox
                        // with NO aria-label and NO innerText while it is empty, so its placeholder
                        // attribute is the only self-description it has. Without those two the editor
                        // was collected and then discarded by the `!name` guard below — `inspect` could
                        // not see the one element the task existed to type into.
                        const name = (element.getAttribute('aria-label') || element.getAttribute('placeholder') || element.getAttribute('aria-placeholder') || element.getAttribute('data-placeholder') || element.innerText || element.value || '').trim().replace(/\\s+/g, ' ').slice(0, 160);
                        if (!role || !name) return null;
                        if (query && !(name + ' ' + (element.href || '')).toLocaleLowerCase().includes(query)) return null;
                        const key = role + '\\u0000' + name;
                        const nth = count.get(key) || 0;
                        count.set(key, nth + 1);
                        return {role, name, nth, href: element.href || undefined, placeholder: element.getAttribute('placeholder') || undefined};
                    }).filter(Boolean).slice(0, 40);
                }""", query.casefold()))
                controls = []
                for item in raw:
                        target = (
                                {"kind": "placeholder", "name": item["placeholder"], "nth": item["nth"]}
                                if item.get("placeholder") and item["role"] == "textbox"
                                else {"kind": "role", "role": item["role"], "name": item["name"], "nth": item["nth"]}
                        )
                        controls.append({"handle": handle(target), **item})
                raw_containers = retry_safe(task, "inspecting", lambda: page.locator("article, [role=list], main, section").evaluate_all("""(elements, query) => {
                    const count = new Map();
                    return elements.filter(element => {
                        const style = getComputedStyle(element);
                        return style.visibility !== 'hidden' && style.display !== 'none' && element.getClientRects().length;
                      }).map(element => {
                        const tag = element.tagName.toLowerCase();
                        const nth = count.get(tag) || 0;
                        count.set(tag, nth + 1);
                        return {tag, nth, text: (element.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 160)};
                    }).filter(item => item.text && (!query || item.text.toLocaleLowerCase().includes(query))).slice(0, 12);
                }""", query.casefold()))
                containers = [
                        {"handle": handle({"kind": "tag", "tag": item["tag"], "nth": item["nth"]}), **item}
                        for item in raw_containers
                ]
                transition(task, "active", "inspected", stage="inspecting", url=page.url, controls=len(controls), containers=len(containers))
                title = retry_safe(task, "inspecting", page.title)
                return {"ok": True, "slug": slug, "state": task["state"], "url": page.url, "title": title, "query": query, "controls": controls, "containers": containers}
    finally:
        pass


def task_action(slug: str, action: dict) -> dict:
    task = read_task(slug)
    if task["state"] not in ACTIVE_STATES:
        raise BrowserTaskError("task_not_active", f"task '{slug}' is not active ({task['state']})")
    _, browser, page = task_connection(slug)
    try:
        operation = action.get("op")
        if operation == "goto":
            retry_safe(task, "navigating", lambda: page.goto(direct_url(action.get("url", "")), wait_until="domcontentloaded", timeout=30000))
        elif operation == "click":
            locate(page, action.get("handle", "")).click(timeout=15000)
        elif operation == "fill":
            locate(page, action.get("handle", "")).fill(str(action.get("value", "")), timeout=15000)
        elif operation == "press":
            locate(page, action.get("handle", "")).press(str(action.get("key", "Enter")), timeout=15000)
        elif operation == "wait":
            retry_safe(task, "waiting", lambda: page.wait_for_timeout(min(max(int(action.get("timeout_ms", 500)), 100), 15000)))
        elif operation == "screenshot":
            name = re.sub(r"[^a-z0-9-]+", "-", str(action.get("name", "evidence")).lower()).strip("-") or "evidence"
            path = task_path(slug).parent / "screenshots" / f"{name}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            retry_safe(task, "capturing", lambda: page.screenshot(path=str(path), full_page=bool(action.get("full_page", False)), timeout=30000))
            task["evidence"]["screenshots"].append({
                "path": str(path.relative_to(DATA)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
        elif operation == "extract":
            root = locate(page, action.get("handle", ""))
            # The root element is included ([element, ...]) for the case where the
            # container itself is one clickable card, but it has no href — a record
            # with text but url:"" fails the verify record_fields contract (all
            # records must carry every required field). Emit ONLY complete records.
            records = retry_safe(task, "extracting", lambda: root.evaluate("""element => [element, ...element.querySelectorAll('a, [role=link]')].slice(0, 50).map(link => ({text: (link.innerText || link.getAttribute('aria-label') || '').trim(), url: link.href || ''})).filter(record => record.text && record.url)"""))
            task["evidence"]["extractions"].append(records)
        else:
            raise ValueError("unsupported action; use goto, click, fill, press, wait, screenshot, or extract")
        stage = {"extract": "extracting", "screenshot": "capturing"}.get(operation, "acting")
        transition(task, "active", "acted", stage=stage, action=operation, url=page.url)
        return {"ok": True, "slug": slug, "state": task["state"], "url": page.url, "extracted": task["evidence"]["extractions"][-1] if operation == "extract" else None}
    finally:
        pass


#: ---- human-verification challenges (captcha) -----------------------------------------------------
#: The office browser meets these on the owner's OWN logins (2026-10-09: claude.ai's sign-in raised a
#: Cloudflare Turnstile image round). Three facts shape this code:
#:   1. A challenge in a cross-origin frame is INVISIBLE to `inspect`: the frame is not the page, so a
#:      caller reading only the page is told there are no controls. Playwright reaches every frame of
#:      the context, so the solve belongs HERE, inside the one task loop, and nowhere else.
#:   2. What the challenge ASKS is decided by something that can SEE the pictures: the caller. This
#:      verb returns the instruction, the candidate targets in PAGE coordinates and a picture of the
#:      challenge, and takes back ONE index. It never guesses which tile is the right one.
#:   3. Nothing leaves the office: the frame is read in-process, the click is a real mouse event on
#:      the shared browser, and no solver service is consulted — a token solved elsewhere does not
#:      belong to this browser's fingerprint (it is rejected, or it lowers its trust), and a page's
#:      contents are the owner's business, not a stranger's.
#: After CAPTCHA_MAX_ATTEMPTS clicks the verb REFUSES by name instead of hammering: a challenge is a
#: security control, and an agent that keeps clicking is how an account gets flagged.
CAPTCHA_KINDS = (
    ("turnstile", ("challenges.cloudflare.com", "/cdn-cgi/challenge-platform/")),
    ("recaptcha", ("recaptcha/api2/anchor", "recaptcha/api2/bframe",
                   "recaptcha/enterprise/anchor", "recaptcha/enterprise/bframe")),
    ("hcaptcha", ("newassets.hcaptcha.com", "hcaptcha.com/1/api.js")),
    ("datadome", ("captcha-delivery.com",)),
    ("altcha", ("altcha.org", "altcha/")),
)
#: A widget normally lives in an IFRAME, and matching by host alone would mistake a demo page for
#: the challenge it hosts (2026-10-09: `google.com/recaptcha/api2/demo` matched its own page and the
#: scan read the form instead of the widget). The main frame therefore counts only when the page IS
#: the interstitial — Cloudflare's own challenge/under-attack page.
CAPTCHA_MAIN_FRAME_ONLY = ("/cdn-cgi/challenge-platform/", "/cdn-cgi/challenge")
CAPTCHA_MAX_ATTEMPTS = 3
CAPTCHA_TOKEN_SELECTORS = [
    "input[name=cf-turnstile-response]",
    "#g-recaptcha-response",
    "textarea[name=h-captcha-response]",
    "textarea[name=g-recaptcha-response]",
]
CAPTCHA_SCAN_JS = """() => {
        const targets = [];
        const roots = [document];
        // Cloudflare's newest widget can hold its checkbox inside a shadow root, where
        // `document.querySelectorAll` never looks (measured 2026-10-09 on a full-page challenge:
        // the checkbox was on screen and the plain scan found only the page's favicon).
        for (const host of document.querySelectorAll('*')) {
            if (host.shadowRoot) roots.push(host.shadowRoot);
        }
        const seen = new Set();
        for (const root of roots) {
            for (const node of root.querySelectorAll('button, [role=button], [role=checkbox], input[type=checkbox], a, img, [tabindex]')) {
                if (seen.has(node)) continue;
                seen.add(node);
                const rect = node.getBoundingClientRect();
                const min = (node.getAttribute('role') === 'checkbox' || node.type === 'checkbox') ? 16 : 24;
                if (rect.width < min || rect.height < min) continue;
                if (rect.bottom <= 0 || rect.right <= 0 || rect.top >= innerHeight || rect.left >= innerWidth) continue;
                const style = getComputedStyle(node);
                if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity) < 0.1) continue;
                targets.push({
                    x: rect.x + rect.width / 2,
                    y: rect.y + rect.height / 2,
                    w: Math.round(rect.width),
                    h: Math.round(rect.height),
                    tag: node.tagName.toLowerCase(),
                    role: node.getAttribute('role') || '',
                    label: (node.getAttribute('aria-label') || node.getAttribute('alt') || node.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 80),
                });
            }
        }
        const text = ((document.body && document.body.innerText) || '').trim().replace(/\\s+/g, ' ');
        return {text: text.slice(0, 500), targets: targets.slice(0, 24)};
    }"""
#: Cloudflare also serves the challenge as a FULL PAGE (nopecha.com's own demo, 2026-10-09): the
#: widget is then in the MAIN frame, whose URL says nothing about it — the page's own words do. A
#: marker in the text plus a widget in the DOM is what makes it a challenge, and anything else is a
#: page we leave alone.
CAPTCHA_PAGE_JS = """() => {
        const text = ((document.body && document.body.innerText) || '').toLowerCase();
        const markers = ['verify you are human', 'verifying you are human', 'performing security verification',
                         'checking your browser', 'just a moment', 'enable javascript and cookies to continue'];
        const marker = markers.find((m) => text.includes(m));
        if (!marker) return null;
        const widget = document.querySelector('#challenge-stage, #challenge-form, div.cf-turnstile, [data-sitekey], input[type=checkbox], [role=checkbox]');
        const branded = text.includes('cloudflare')
            || !!document.querySelector('script[src*="challenges.cloudflare.com"], iframe[src*="challenges.cloudflare.com"], link[href*="cloudflare"]');
        return (widget || branded) ? {marker} : null;
    }"""


def _captcha_frame(page):
    """(kind, frame) of the challenge the page is showing, or (None, None) when it shows none."""
    for frame in page.frames:
        url = frame.url or ""
        for kind, needles in CAPTCHA_KINDS:
            if not any(needle in url for needle in needles):
                continue
            if frame == page.main_frame and not any(
                marker in url for marker in CAPTCHA_MAIN_FRAME_ONLY
            ):
                continue
            return kind, frame
    return None, None


def _captcha_offset(page, frame):
    """Where the frame sits in the PAGE, so a coordinate read inside it becomes a clickable one."""
    if frame == page.main_frame:
        return 0.0, 0.0
    try:
        box = frame.frame_element().bounding_box()
    except Exception:                                      # detached, or not a frame element at all
        return 0.0, 0.0
    box = box or {}
    return float(box.get("x") or 0.0), float(box.get("y") or 0.0)


def _captcha_token(page) -> bool:
    """Was the page already given a response token? THAT — not the frame — is what 'passed' means."""
    for frame in page.frames:
        try:
            value = frame.evaluate(
                "(selectors) => selectors.map((s) => { const n = document.querySelector(s); "
                "return (n && (n.value || n.innerHTML)) || ''; }).find(Boolean) || ''",
                CAPTCHA_TOKEN_SELECTORS,
            )
        except Exception:                                  # a frame that went away mid-read
            continue
        if value:
            return True
    return False


def _human_click(page, x: float, y: float) -> None:
    """One click a behavioural model reads as a hand: a curve in, a settle, a press — never a jump.

    `page.wait_for_timeout` is deliberately NOT used here: it is a CDP round trip, and the browser's
    own vendor documents CDP traffic as a scoring signal (CloakBrowser README, "reCAPTCHA v3 scores
    are low — avoid page.wait_for_timeout"). A native sleep is invisible to the page.
    """
    import random
    page.mouse.move(x - 70 + random.randint(0, 40), y - 50 + random.randint(0, 30), steps=1)
    page.mouse.move(x - 16 + random.randint(0, 10), y - 10 + random.randint(0, 8),
                    steps=random.randint(9, 16))
    time.sleep(0.06 + random.random() * 0.09)
    page.mouse.move(x + random.randint(-2, 2), y + random.randint(-2, 2),
                    steps=random.randint(4, 8))
    time.sleep(0.05 + random.random() * 0.08)
    page.mouse.down()
    time.sleep(0.03 + random.random() * 0.06)
    page.mouse.up()


#: A widget frame that reports NO URL is the normal case for the challenge platform (measured twice
#: on 2026-10-09), so the frame cannot be identified by address — it is identified by what it SAYS.
PROBE_JS = """() => {
        const text = ((document.body && document.body.innerText) || '').trim();
        const low = text.toLowerCase();
        const markers = ['verify you are human', 'verifying you are human', 'performing security verification',
                         'checking your browser', 'just a moment', 'enable javascript and cookies to continue',
                         "i'm not a robot", 'i am not a robot', 'click on the item', 'select all'];
        const marker = markers.find((m) => low.includes(m));
        const widget = document.querySelector('input[type=checkbox], [role=checkbox], div.cf-turnstile, #challenge-stage, #challenge-form, [data-sitekey]');
        if (!marker && !widget) return null;
        return {marker: marker || '', text: text.replace(/\\s+/g, ' ').slice(0, 200), widget: !!widget};
    }"""


def _captcha_points(argument: str):
    """`@x:y[,@x:y…]` — page coordinates a caller that can SEE read off the widget picture.

    The escape hatch this exists for: Cloudflare's newest interstitial keeps its checkbox inside a
    CLOSED shadow root, where neither page JavaScript nor a locator can reach it (measured 2026-10-09
    on two live pages: the box was on screen and every DOM read returned nothing). `captcha detect`'s
    picture is a viewport screenshot in CSS pixels — exactly the units `page.mouse` takes — so the
    caller reads the pixel and names it, and the click is still a real human-like click on the office
    browser. Returns [] when the argument is not a point list.
    """
    points = []
    for piece in argument.replace(" ", "").split(","):
        if not piece.startswith("@"):
            return []
        try:
            px, py = (float(value) for value in piece[1:].split(":"))
        except ValueError:
            return []
        points.append((px, py))
    return points


def _captcha_read(task: dict, page, frame):
    """One read of a challenge: its instruction, its targets in PAGE coordinates, its own box.

    The widget does not always live where the page does: a full-page challenge can put its checkbox
    (and, later, its picture grid) inside a frame of its own. So every frame that LOOKS like the
    challenge platform is scanned too, and each target says which frame it came from.
    """
    scan_frames = [frame]
    for candidate in page.frames:
        if candidate is frame or candidate is page.main_frame:
            continue
        url = candidate.url or ""
        # An empty URL is not "no frame": Cloudflare's challenge iframe reports none in this build
        # (measured 2026-10-09 — the checkbox was on screen and the frame list said ""), so once a
        # challenge is established, an anonymous frame is a candidate too.
        if not url or any(needle in url for _, needles in CAPTCHA_KINDS for needle in needles):
            scan_frames.append(candidate)
        if len(scan_frames) >= 4:
            break
    options = []
    instruction = ""
    scanned: list = []
    for index, current in enumerate(scan_frames):
        offset_x, offset_y = _captcha_offset(page, current)
        scan = retry_safe(task, "acting", lambda: current.evaluate(CAPTCHA_SCAN_JS)) or {}
        text = (scan.get("text") or "").strip()
        scanned.append({"frame": index, "url": (current.url or "")[:60],
                        "targets": len(scan.get("targets") or []), "text": text[:60]})
        if text and (not instruction or len(text) > len(instruction)):
            instruction = text[:200]
        for target in scan.get("targets") or []:
            options.append({
                "index": len(options),
                "x": round(offset_x + target["x"], 1),
                "y": round(offset_y + target["y"], 1),
                "w": int(target["w"]),
                "h": int(target["h"]),
                "size": f'{target["w"]}x{target["h"]}',
                "tag": target["tag"],
                "role": target["role"],
                "label": target["label"],
                "frame": index,
            })
        # Playwright's own engine reaches where page JavaScript cannot — a checkbox inside a CLOSED
        # shadow root is invisible to `document.querySelectorAll` and visible to a locator (measured
        # 2026-10-09: the widget's box was on screen and the JS scan returned only a favicon).
        try:
            viewport = page.viewport_size or {}
            for handle in current.locator("input[type=checkbox], [role=checkbox]").all()[:6]:
                box = handle.bounding_box()
                if not box or box["width"] < 8 or box["height"] < 8:
                    continue
                # A target the caller cannot SEE is not a target: reCAPTCHA's badge checkbox sits
                # below the fold, and clicking it would burn a round on nothing (measured 2026-10-09).
                if viewport.get("width") and (box["x"] + box["width"] < 0 or box["x"] > viewport["width"]
                                              or box["y"] + box["height"] < 0 or box["y"] > viewport.get("height", 0)):
                    continue
                options.append({
                    "index": len(options),
                    "x": round(offset_x + box["x"] + box["width"] / 2, 1),
                    "y": round(offset_y + box["y"] + box["height"] / 2, 1),
                    "w": int(box["width"]),
                    "h": int(box["height"]),
                    "size": f'{int(box["width"])}x{int(box["height"])}',
                    "tag": "checkbox",
                    "role": "checkbox",
                    "label": "",
                    "frame": index,
                })
        except Exception:                                  # a frame that refuses locators is not fatal
            pass
    try:
        frame_box = frame.frame_element().bounding_box()
    except Exception:                                      # the main frame has no frame element
        frame_box = None
    return options, instruction, frame_box, scanned


def _captcha_evidence(task: dict, page, path, clip=None) -> dict | None:
    """A picture is evidence, never a failure: it is recorded, and a missing one never raises."""
    try:
        retry_safe(task, "capturing", lambda: page.screenshot(path=str(path), clip=clip, timeout=30000))
        task["evidence"]["screenshots"].append({
            "path": str(path.relative_to(DATA)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
        return {"path": str(path.relative_to(DATA))}
    except Exception:
        return None


def _captcha_tiles(task: dict, page, options, stamp: str) -> None:
    """Every picture-tile as its OWN cropped picture (in place, on the option it belongs to).

    The round the office actually met — "Click on the item used for gardening" over a 3x3 of
    pictures — is decided by LOOKING at the tiles. One photo of the whole widget cannot be read tile
    by tile; nine small crops can, and a caller that can see answers a round in one turn.
    """
    for option in options:
        if len([o for o in options if o.get("tile")]) >= 12:
            return
        width, height = option["w"], option["h"]
        if not (48 <= width <= 360 and 48 <= height <= 360):
            continue
        path = task_path(task["slug"]).parent / "screenshots" / f"{stamp}-tile-{option['index']}.png"
        clip = {
            "x": max(0.0, option["x"] - width / 2 - 3),
            "y": max(0.0, option["y"] - height / 2 - 3),
            "width": float(width) + 6,
            "height": float(height) + 6,
        }
        saved = _captcha_evidence(task, page, path, clip)
        if saved:
            option["tile"] = saved["path"]


def task_captcha(slug: str, sub: str, argument: str) -> dict:
    """captcha detect | click <index[,index…]> — read the challenge, or answer it like a hand.

    `detect` answers with the frame, its instruction, every clickable target with its PAGE
    coordinates, each picture-tile as its OWN cropped picture, and whether the page already holds a
    response token — so a caller that can SEE decides, tile by tile. `click 3` presses that one
    target; `click 0,4,7` presses several in ONE round (a round that says "click on the items used
    for X" wants every one of them). Every click reports what it CHANGED: `solved` (a token came
    out), `advanced` (the round moved on to new pictures) or `same`. Both refuse, by name, once
    CAPTCHA_MAX_ATTEMPTS rounds were spent on this task.
    """
    task = read_task(slug)
    if task["state"] not in ACTIVE_STATES:
        raise BrowserTaskError("task_not_active", f"task '{slug}' is not active ({task['state']})")
    _, _, page = task_connection(slug)
    book = task.get("captcha") or {"attempts": 0, "history": []}
    sub = (sub or "detect").strip().lower()
    if sub not in ("detect", "click"):
        raise BrowserTaskError("captcha_unknown_sub",
                               "captcha takes 'detect' or 'click <index[,index…]>'")
    if sub == "click" and book["attempts"] >= CAPTCHA_MAX_ATTEMPTS:
        raise BrowserTaskError(
            "captcha_attempts_exhausted",
            f"{CAPTCHA_MAX_ATTEMPTS} rounds were already spent on '{slug}'. Stop clicking: hand the "
            "challenge to the owner at http://browser42.localhost:8080/view/ — the challenge, the "
            "page and the profile are his.",
        )
    instruction = ""
    points = _captcha_points(str(argument)) if sub == "click" else []
    if points:
        # An explicit pixel click does not need the DOM to agree: the caller saw the widget.
        token_before = _captcha_token(page)
        for px, py in points:
            retry_safe(task, "acting", lambda: _human_click(page, px, py))
            time.sleep(0.25)
        book["attempts"] += 1
        stamp = f"captcha-{book['attempts']}"
        outcome = "clicked " + ", ".join(f"@{int(px)},{int(py)}" for px, py in points)
        time.sleep(0.45)
        kind_after, _ = _captcha_frame(page)
        changed = "solved" if (_captcha_token(page) and not token_before) else "same"
        path = task_path(slug).parent / "screenshots" / f"{stamp}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        saved = _captcha_evidence(task, page, path)
        book["history"].append({"at": now(), "action": sub, "kind": kind_after, "result": outcome,
                                "changed": changed, "attempts": book["attempts"]})
        task["captcha"] = book
        transition(task, task["state"], "acted", stage="acting", action="captcha", url=page.url)
        return {"ok": True, "slug": slug, "url": page.url, "captcha": {
            "present": True, "kind": kind_after or "pointer", "instruction": instruction,
            "options": [], "attempts": book["attempts"], "outcome": outcome, "changed": changed,
            "frames": [(f.url or "")[:90] for f in page.frames][:8],
            "screenshot": saved["path"] if saved else None, "token": _captcha_token(page)}}
    kind, frame = _captcha_frame(page)
    if frame is None:
        # A full-page challenge carries no telling frame URL — the page's own words name it.
        marker = retry_safe(task, "acting", lambda: page.evaluate(CAPTCHA_PAGE_JS))
        if marker:
            kind, frame = "turnstile-page", page.main_frame
    if frame is None:
        # …and a widget frame that reports no URL is named by what IT says, not by its address.
        for candidate in page.frames:
            if candidate is page.main_frame:
                continue
            try:
                probe = candidate.evaluate(PROBE_JS)
            except Exception:
                continue
            if probe:
                kind, frame = "turnstile-frame", candidate
                break
    # The frame list travels with every answer: when a widget is somewhere the scan cannot reach,
    # this is what says where it actually is (measured need, 2026-10-09).
    frames_seen = [(candidate.url or "")[:90] for candidate in page.frames][:8]
    if frame is None:
        book["history"].append({"at": now(), "action": sub, "kind": None, "result": "absent"})
        task["captcha"] = book
        transition(task, task["state"], "acted", stage="acting", action="captcha", url=page.url)
        return {"ok": True, "slug": slug, "url": page.url, "captcha": {
            "present": False, "kind": None, "token": _captcha_token(page), "frames": frames_seen,
            "attempts": book["attempts"], "instruction": "", "options": [],
            "hint": "nothing in the DOM looks like a challenge. If the picture shows a widget anyway "
                    "(Cloudflare's newest interstitial is unreadable to the DOM), read its pixel and "
                    "pass it: captcha click @x:y"}}
    stamp = f"captcha-{book['attempts'] + 1}"
    options, instruction, frame_box, scanned = _captcha_read(task, page, frame)
    outcome, changed = "read", "same"
    if sub == "click":
        argument = str(argument).replace(" ", "")
        clicks: list = []
        wanted: list = []
        if argument.startswith("@"):
            # The way out when the widget refuses the DOM: a checkbox inside a CLOSED shadow root is
            # invisible to page JavaScript AND to a locator, while `captcha detect`'s picture is a
            # viewport screenshot in CSS pixels — exactly the units `page.mouse` takes. The caller
            # that can SEE reads the pixel and names it. (Measured 2026-10-09, a full-page
            # Cloudflare interstitial whose checkbox no DOM read could reach.)
            for piece in argument.split(","):
                try:
                    px, py = (float(value) for value in piece[1:].split(":"))
                except ValueError:
                    clicks = []
                    break
                clicks.append((px, py))
            if not clicks:
                raise BrowserTaskError("captcha_unknown_target",
                                       "'captcha click @x:y[,@x:y…]' wants page coordinates")
        else:
            for piece in argument.split(","):
                try:
                    wanted.append(int(piece))
                except ValueError:
                    wanted = []
                    break
            if not wanted or any(index < 0 or index >= len(options) for index in wanted):
                raise BrowserTaskError(
                    "captcha_unknown_target",
                    f"'{argument}' is not one of the {len(options)} targets `captcha detect` returned",
                )
            clicks = [(options[index]["x"], options[index]["y"]) for index in wanted]
        token_before = _captcha_token(page)
        for px, py in clicks:
            retry_safe(task, "acting", lambda: _human_click(page, px, py))
            time.sleep(0.25)
        book["attempts"] += 1
        stamp = f"captcha-{book['attempts']}"
        outcome = "clicked " + ", ".join(
            (f"@{int(px)},{int(py)}" for px, py in clicks) if not wanted
            else (f"#{index}" for index in wanted))
        time.sleep(0.45)                                   # let the round answer before reading it
        kind_after, frame_after = _captcha_frame(page)
        marker_after = None
        if frame_after is None:
            marker_after = retry_safe(task, "acting", lambda: page.evaluate(CAPTCHA_PAGE_JS))
        if _captcha_token(page) and not token_before:
            changed = "solved"
        elif frame_after is not None:
            _, instruction_after, _, _ = _captcha_read(task, page, frame_after)
            changed = "same" if instruction_after == instruction else "advanced"
            instruction = instruction_after or instruction
            kind, frame = kind_after, frame_after
        elif marker_after:
            # A full-page interstitial that is STILL there after the click: the round did not pass.
            # "no frame" is not "solved" — measured 2026-10-09 on a hostile demo page, where a click
            # emptied the widget box and the page never moved on.
            changed = "same"
        else:
            changed = "solved"
    clip = None
    if frame_box:
        clip = {
            "x": max(0.0, float(frame_box["x"]) - 8),
            "y": max(0.0, float(frame_box["y"]) - 8),
            "width": float(frame_box["width"]) + 16,
            "height": float(frame_box["height"]) + 16,
        }
    path = task_path(slug).parent / "screenshots" / f"{stamp}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = _captcha_evidence(task, page, path, clip)
    if sub == "detect":
        _captcha_tiles(task, page, options, stamp)
    book["history"].append({"at": now(), "action": sub, "kind": kind, "result": outcome,
                            "changed": changed, "attempts": book["attempts"]})
    task["captcha"] = book
    transition(task, task["state"], "acted", stage="acting", action="captcha", url=page.url)
    return {"ok": True, "slug": slug, "url": page.url, "captcha": {
        "present": True,
        "kind": kind,
        "frame_url": (frame.url or "")[:120],
        "instruction": instruction,
        "options": options,
        "attempts": book["attempts"],
        "outcome": outcome,
        "changed": changed,
        "frames": frames_seen,
        "scanned": scanned,
        "screenshot": saved["path"] if saved else None,
        "token": _captcha_token(page),
    }}


#: ---- reading a WHOLE page, whatever the viewport ---------------------------------------------------
#: The office browser is one small shared screen (its viewport is ~780x395 most of the time), and a
#: transcript, a log or a long document does not fit in it. Scrolling it by hand to "get the context"
#: is what this exists to end: `bbox b42 task read <slug>` walks the page's own scroll container from
#: the top to the bottom, reads the text at every step, stitches the steps by their overlap, and
#: returns the WHOLE text in one answer — plus a full-page picture on request. The screen size stops
#: mattering, which is the point (the owner, 2026-10-09: "solve once and for all the need to scroll
#: around to get the entire context from small screen").
READ_ROOT_JS = """() => {
        let best = null;
        let bestHeight = 0;
        const candidates = [document.scrollingElement, ...document.querySelectorAll('*')];
        for (const element of candidates) {
            if (!element || element.scrollHeight <= element.clientHeight + 60) continue;
            const style = getComputedStyle(element);
            if (style.overflowY === 'hidden' && element !== document.scrollingElement) continue;
            if (element.scrollHeight > bestHeight) {
                bestHeight = element.scrollHeight;
                best = element;
            }
        }
        for (const element of document.querySelectorAll('[data-b42-read]')) element.removeAttribute('data-b42-read');
        if (best) best.setAttribute('data-b42-read', '1');
        return {found: !!best, scrollHeight: best ? best.scrollHeight : 0,
                clientHeight: best ? best.clientHeight : 0,
                node: best ? best.tagName.toLowerCase() : '', scrolled: best ? Math.round(best.scrollTop) : 0};
    }"""
READ_TEXT_JS = """() => {
        const element = document.querySelector('[data-b42-read]') || document.scrollingElement || document.body;
        return (element.innerText || '');
    }"""
READ_SCROLL_JS = """(top) => {
        const element = document.querySelector('[data-b42-read]') || document.scrollingElement || document.body;
        element.scrollTop = top;
        return Math.round(element.scrollTop);
    }"""


def _stitch(acc: str, chunk: str, window: int = 4000) -> str:
    """Append `chunk` to `acc`, keeping only the part of it that overlaps nothing.

    The steps of a walk see the same lines twice (the container is read at 80% steps, and a
    virtualised list re-renders its neighbourhood), so the join is by the largest overlap between the
    tail of what is already collected and the head of the new step — never by line equality, which
    would silently drop a legitimate repeated line.
    """
    if not acc:
        return chunk
    if not chunk:
        return acc
    limit = min(len(acc), len(chunk), window)
    for size in range(limit, 0, -1):
        if acc.endswith(chunk[:size]):
            return acc + chunk[size:]
    return acc + "\n" + chunk


def task_page_read(slug: str, max_chars: int) -> dict:
    """`read` — the WHOLE text of the page, however small the screen is.

    Walks the page's own scroll container from its top to its bottom, reads the rendered text at every
    step, and stitches the steps by overlap. Returns the text, how many steps it took, whether it
    reached the bottom, and (with `shot`) a full-page picture as evidence. A page that fits is one
    step, and this is exactly as cheap as a screenshot.
    """
    task = read_task(slug)
    if task["state"] not in ACTIVE_STATES:
        raise BrowserTaskError("task_not_active", f"task '{slug}' is not active ({task['state']})")
    _, _, page = task_connection(slug)
    limit = max(4000, min(int(max_chars or 120000), 600000))
    root = retry_safe(task, "reading", lambda: page.evaluate(READ_ROOT_JS)) or {}
    collected = ""
    steps = 0
    stopped = "bottom"
    if root.get("found"):
        retry_safe(task, "reading", lambda: page.evaluate(READ_SCROLL_JS, 0))
        time.sleep(0.35)
    while steps < 80:
        chunk = retry_safe(task, "reading", lambda: page.evaluate(READ_TEXT_JS)) or ""
        collected = _stitch(collected, chunk)
        steps += 1
        if len(collected) >= limit:
            collected = collected[:limit]
            stopped = "limit"
            break
        if not root.get("found"):
            stopped = "no_scroll"
            break
        position = retry_safe(task, "reading", lambda: page.evaluate("""() => {
                const element = document.querySelector('[data-b42-read]') || document.scrollingElement;
                return {top: Math.round(element.scrollTop), height: element.clientHeight,
                        total: element.scrollHeight};
            }""")) or {}
        if position.get("top", 0) + position.get("height", 0) >= position.get("total", 0) - 2:
            break
        target = min(position.get("total", 0), position.get("top", 0) + max(120, int(position.get("height", 300) * 0.8)))
        retry_safe(task, "reading", lambda: page.evaluate(READ_SCROLL_JS, target))
        time.sleep(0.28)
    else:
        stopped = "steps"
    collected = re.sub(r"\n{3,}", "\n\n", collected).strip()
    transition(task, task["state"], "acted", stage="acting", action="read", url=page.url)
    return {"ok": True, "slug": slug, "url": page.url, "title": retry_safe(task, "reading", page.title),
            "read": {"chars": len(collected), "steps": steps, "stopped": stopped,
                     "scroll": {"node": root.get("node", ""), "height": root.get("scrollHeight", 0)},
                     "text": collected}}


def task_login(slug: str, site: str) -> dict:
    """Sign in to `site` with the office's own credential, so the caller never handles it.

    The password is resolved from the credential plane INSIDE this function and typed straight into
    the page: it is not an argument, not a journal field, not a response field and not a log line.
    The response says which site, which selectors matched and whether the login form is gone — never
    the account, never the value.
    """
    task = read_task(slug)
    if task["state"] not in ACTIVE_STATES:
        raise BrowserTaskError("task_not_active", f"task '{slug}' is not active ({task['state']})")
    flow, user, password = login_credential(site)
    _, browser, page = task_connection(slug)
    retry_safe(task, "navigating", lambda: page.goto(direct_url(flow["url"]),
                                                     wait_until="domcontentloaded", timeout=45000))
    # The profile may already hold the session (that is the point of persisting it) — then there is
    # nothing to type, and the honest answer is "already in", not a second sign-in.
    if page.locator(flow["logged_out"]).count() == 0 and "login" not in page.url:
        transition(task, "active", "acted", stage="acting", action=f"login:{site}", url=page.url)
        return {"ok": True, "slug": slug, "site": site, "already_logged_in": True, "url": page.url}
    used_user = fill_first(page, flow["user"], user, "username")
    used_pass = fill_first(page, flow["pass"], password, "password")
    del password, user                                   # nothing below may carry them
    clicked = None
    last = None
    for selector in flow["submit"]:
        try:
            button = page.locator(selector).first
            button.wait_for(state="visible", timeout=8000)
            button.click(timeout=8000)
            clicked = selector
            break
        except Exception as error:                      # noqa: BLE001 — try the next candidate
            last = error
    if not clicked:
        raise BrowserTaskError("login_selector_missing",
                               f"none of the submit selectors resolved: {flow['submit']} (last error: {last})")
    # Signed in = the login form is GONE. A timeout here is reported without ever echoing a value.
    try:
        page.locator(flow["logged_out"]).first.wait_for(state="detached", timeout=30000)
    except Exception as error:                          # noqa: BLE001 — one clear failure, not a guess
        raise BrowserTaskError(
            "login_failed",
            f"the login form for '{site}' is still on screen after submitting — check the credential "
            f"in connections, or the site is asking for a second factor ({error})") from error
    path = task_path(slug).parent / "screenshots" / f"login-{site}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    retry_safe(task, "capturing", lambda: page.screenshot(path=str(path), timeout=30000))
    task["evidence"]["screenshots"].append({
        "path": str(path.relative_to(DATA)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    })
    transition(task, "active", "acted", stage="acting", action=f"login:{site}", url=page.url)
    return {"ok": True, "slug": slug, "site": site, "already_logged_in": False, "url": page.url,
            "selectors": {"user": used_user, "pass": used_pass, "submit": clicked}}


def task_verify(slug: str) -> dict:
    task = read_task(slug)
    _, browser, page = task_connection(slug)
    try:
        requirements = task.get("requirements") or {}
        records = [record for extraction in task["evidence"].get("extractions", []) for record in extraction]
        screenshots = task["evidence"].get("screenshots", [])
        required_fields = requirements.get("required_record_fields", [])
        if not isinstance(required_fields, list) or not all(isinstance(field, str) for field in required_fields):
            raise BrowserTaskError("invalid_requirements", "required_record_fields must be a list of field names")
        extension = broker_command({"action": "status", "slug": slug}).get("session")

        def valid_screenshot(item: dict) -> bool:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("sha256"), str):
                return False
            path = Path(item["path"])
            expected = Path("tasks") / slug / "screenshots" / path.name
            artifact = task_path(slug).parent / "screenshots" / path.name
            return path == expected and artifact.is_file() and hashlib.sha256(artifact.read_bytes()).hexdigest() == item["sha256"]

        screenshots_match = bool(screenshots) and all(valid_screenshot(item) for item in screenshots)
        checks = {
            "one_live_owned_tab": bool(extension) and extension.get("tabId") == task.get("tab_id") and extension.get("ownedTabIds") == [task.get("tab_id")],
            "native_group": bool(task.get("native_group", {}).get("id") is not None),
            "extension_ownership": bool(extension) and extension.get("groupId") == task["native_group"]["id"] and extension.get("generation") == task.get("ownership_generation"),
            "screenshot": screenshots_match,
            "minimum_extractions": len(task["evidence"].get("extractions", []) or []) >= int(requirements.get("minimum_extractions", 0)),
            "minimum_records": len(records) >= int(requirements.get("minimum_records", 0)),
            "record_fields": all(all(record.get(field) for field in required_fields) for record in records),
            "final_url_prefix": not requirements.get("final_url_prefix") or page.url.startswith(requirements["final_url_prefix"]),
        }
        accepted = all(checks.values())
        transition(task, "accepted" if accepted else "rejected", "verified", stage="verifying", checks=checks, final_url=page.url, record_count=len(records))
        result = {
            "protocol_version": TASK_PROTOCOL_VERSION,
            "ok": accepted,
            "slug": slug,
            "state": task["state"],
            "checks": checks,
            "final_url": page.url,
            "native_group": task["native_group"],
            "extension_session": extension,
            "evidence": task["evidence"],
            "records": records,
            "stage_timings": task.get("stage_timings", {}),
        }
        (task_path(slug).parent / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        pass


def task_goal(slug: str, url: str, topic: str, minimum_records: int) -> dict:
    """Platform-side goal executor: one request drives goto -> settle -> find container ->
    extract -> screenshot -> verify -> finish. No model turns. Used for the canonical goal
    "latest N items about <topic> on <url>"; the step loop stays as the general fallback."""
    try:
        task = read_task(slug)
    except BrowserTaskError as error:
        # Flash models frequently ran `goal` BEFORE `start` (the docs' fast path reads
        # goal-first) and then retry-stormed task_not_found. goal is self-contained
        # (goto -> ... -> finish), so auto-start the task and make BOTH orderings work.
        if error.code != "task_not_found":
            raise
        task_start(slug, url, parse_start_requirements(str(minimum_records)))
        task = read_task(slug)
    if task["state"] not in ACTIVE_STATES:
        raise BrowserTaskError("task_not_active", f"task '{slug}' is not active ({task['state']})")
    _, browser, page = task_connection(slug)
    steps: list[dict] = []

    def note(step: str, **fields) -> None:
        steps.append({"step": step, "at": now(), **fields})

    # 1. navigate only when needed. `start` already loads the URL into the owned tab; on
    #    ad-heavy sites even domcontentloaded can exceed 45s, so a redundant re-goto is
    #    pure waste and can kill the whole goal. Single attempt, tolerate the timeout, then
    #    settle on whatever DOM is already loaded — the container scan below is the real work.
    target = direct_url(url)
    t0 = now()
    if page.url.rstrip("/") != target.rstrip("/"):
        try:
            page.goto(target, wait_until="domcontentloaded", timeout=45000)
        except Exception as error:
            if "timeout" not in str(error).casefold():
                raise BrowserTaskError(error_code(error), str(error)) from error
            journal(task, "goal_goto_timeout_tolerated", url=target, error=str(error)[:200])
    note("goto", url=page.url)
    span_stage(slug, "goto", t0, url=page.url)
    # 2. settle: wait for network to quiet down OR hard cap; ad-heavy sites never go
    #    fully idle, so cap at 6s — humans don't wait for every ad either.
    t0 = now()
    try:
        page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        pass
    page.wait_for_timeout(800)
    note("settle", url=page.url)
    span_stage(slug, "settle", t0, url=page.url)
    # 3. find the best results container for the topic: prefer containers whose text mentions
    #    the topic and that hold the most links; fall back to the largest link-rich container.
    #    nth MUST be counted over ALL elements of the tag in DOM order — locate() resolves a
    #    tag handle via page.locator(tag).nth(n), which is unfiltered by visibility.
    lowered = (topic or "").casefold()
    t0 = now()
    containers = retry_safe(task, "extracting", lambda: page.evaluate("""(topic) => {
        const tags = ['article', 'main', 'section'];
        const out = [];
        for (const tag of tags) {
            let nth = 0;
            for (const element of document.querySelectorAll(tag)) {
                const current = nth;
                nth += 1;
                const style = getComputedStyle(element);
                if (style.visibility === 'hidden' || style.display === 'none' || !element.getClientRects().length) continue;
                const links = [...element.querySelectorAll('a[href]')].filter(a => (a.innerText || '').trim().length > 15);
                const text = (element.innerText || '').slice(0, 4000);
                out.push({
                    tag,
                    nth: current,
                    links: links.length,
                    hits: topic ? (text.toLocaleLowerCase().split(topic).length - 1) : 0,
                    chars: text.length,
                });
            }
        }
        return out;
    }""", lowered))
    ranked = sorted(containers, key=lambda c: (c["hits"] > 0, min(c["links"], 20), c["chars"]), reverse=True)
    note("scan", containers=len(ranked))
    span_stage(slug, "scan", t0, url=page.url, detail={"containers": len(ranked)})
    # 4. extract records. Preferred path: the best link-rich container. FALLBACK for
    #    flat-link layouts: some pages carry their content as bare links in the main frame
    #    with NO article/section/main wrappers (or the wrappers live in iframes and are
    #    invisible to this main-frame scan). A container-only executor can never harvest
    #    those pages — every 0805u/v health run got 0 records even though 20+ article
    #    links were visible in the DOM. Harvest visible main-frame links directly; the
    #    record contract (text+url, complete fields only) is identical.
    best = ranked[0] if ranked else None
    if best is not None and best["links"] > 0:
        note("container", **{k: best[k] for k in ("tag", "nth", "links", "hits")})
        t0 = now()
        task_action(slug, {"op": "extract", "handle": handle({"kind": "tag", "tag": best["tag"], "nth": best["nth"]})})
        note("extract")
        span_stage(slug, "extract", t0, url=page.url)
    else:
        t0 = now()
        links = retry_safe(task, "extracting", lambda: page.evaluate("""(topic) => {
            const lowered = (topic || '').toLocaleLowerCase();
            const seen = new Set();
            const out = [];
            for (const a of document.querySelectorAll('a[href]')) {
                const text = (a.innerText || a.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ');
                const url = a.href || '';
                if (!text || text.length <= 15 || !url || url.startsWith('javascript:')) continue;
                const style = getComputedStyle(a);
                if (style.visibility === 'hidden' || style.display === 'none' || !a.getClientRects().length) continue;
                if (seen.has(url)) continue;
                seen.add(url);
                out.push({text: text.slice(0, 200), url, rank: lowered && (text + ' ' + url).toLocaleLowerCase().includes(lowered) ? 1 : 0});
            }
            out.sort((x, y) => y.rank - x.rank);
            return out.slice(0, 60).map(item => ({text: item.text, url: item.url}));
        }""", lowered))
        fresh = read_task(slug)
        fresh["evidence"]["extractions"].append(links)
        transition(fresh, "active", "acted", stage="extracting", action="extract-links", url=page.url)
        note("extract-links", records=len(links))
        span_stage(slug, "extract-links", t0, url=page.url, detail={"records": len(links)})
    # 5. screenshot evidence
    t0 = now()
    task_action(slug, {"op": "screenshot", "name": "goal-final"})
    note("screenshot")
    span_stage(slug, "screenshot", t0, url=page.url)
    # 6. verify + finish
    t0 = now()
    verified = task_verify(slug)
    note("verify", ok=verified.get("ok"), records=verified.get("records") and len(verified.get("records") or []))
    span_stage(slug, "verify", t0, url=page.url, detail={"ok": verified.get("ok"), "records": len(verified.get("records") or [])})
    if not verified.get("ok"):
        return {"ok": False, "slug": slug, "state": verified.get("state"), "checks": verified.get("checks"), "steps": steps,
                "error": {"code": "goal_verify_rejected", "message": "goal executor evidence did not pass acceptance checks; fall back to the step loop"}}
    records = verified.get("records") or []
    if len(records) < max(1, minimum_records):
        return {"ok": False, "slug": slug, "state": verified.get("state"), "checks": verified.get("checks"), "steps": steps, "records": records,
                "error": {"code": "goal_insufficient_records", "message": f"goal executor found {len(records)} records, need {minimum_records}; fall back to the step loop"}}
    t0 = now()
    finished = task_finish(slug)
    note("finish")
    span_stage(slug, "finish", t0)
    return {"ok": True, "slug": slug, "state": "finished", "records": finished["result"].get("records", []), "steps": steps, "native_group": finished["native_group"]}


def task_finish(slug: str) -> dict:
    task = read_task(slug)
    if task["state"] != "accepted":
        raise BrowserTaskError("result_not_accepted", f"task result is not accepted ({task['state']}); run task verify and satisfy every check")
    result_path = task_path(slug).parent / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {"ok": True, "slug": slug}
    task["state"] = "finished"
    task["updated_at"] = now()
    journal(task, "finished", stage_timings=task.get("stage_timings", {}))
    write_task(task)
    # Tabs are released AFTER evidence is captured (verify already ran by then).
    release_tabs(slug, int(task.get("created_at", now())), "ok")
    return {"ok": True, "result": result, "evidence": task["evidence"], "native_group": task["native_group"]}


def task_status(slug: str) -> dict:
    task = read_task(slug)
    return {
        "ok": True,
        "slug": slug,
        "state": task["state"],
        "stage": task.get("stage"),
        "heartbeat_at": task["heartbeat_at"],
        "updated_at": task["updated_at"],
        "native_group": task.get("native_group"),
        "evidence": task["evidence"],
        "failure": task.get("failure"),
        "stage_timings": task.get("stage_timings", {}),
    }


def task_heartbeat(slug: str) -> dict:
    task = read_task(slug)
    if task["state"] not in ACTIVE_STATES:
        raise ValueError(f"task '{slug}' is not active ({task['state']})")
    transition(task, task["state"], "heartbeat")
    return {"ok": True, "slug": slug, "state": task["state"], "heartbeat_at": task["heartbeat_at"]}


SNIPPET = '''import os, sys
from playwright.sync_api import sync_playwright
SESSION = "{TAG}"                    # <- your group tag (stable per session)
p = sync_playwright().start()
b = p.chromium.connect_over_cdp("http://localhost:9222")
ctx = b.contexts[0]
def _n(pg):
    try: return pg.evaluate("window.name")
    except Exception: return ""
me = next((pg for pg in ctx.pages if _n(pg) == SESSION), None)
if me is None:
    print(f"ERROR: assigned Browser42 tab {{SESSION}} is missing", file=sys.stderr)
    sys.stderr.flush(); os._exit(2)
# ... do your work on `me` only ... (the reaper caps total tabs — you don't)
sys.stdout.flush(); os._exit(0)            # NOT b.close() — would kill shared state'''


def main():
    verb = sys.argv[1] if len(sys.argv) > 1 else ""
    # Any verb is "use": the idle sleeper (start-browser.sh §4k, reaper.py) counts idle time from
    # this marker, and a sleeping browser wakes for it.
    try:
        activity = Path("/data/.activity")
        activity.mkdir(parents=True, exist_ok=True)
        (activity / "agent").touch()
    except OSError:
        pass
    try:
        if verb == "session":
            cmd_session(sys.argv[2] if len(sys.argv) > 2 else None)
        elif verb == "open":
            cmd_open(sys.argv[2] if len(sys.argv) > 2 else None, sys.argv[3] if len(sys.argv) > 3 else None)
        elif verb == "list":
            cmd_list()
        elif verb == "close":
            cmd_close(sys.argv[2] if len(sys.argv) > 2 else None)
        elif verb == "gc":
            stale = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[2] == "--stale" else 24
            cmd_gc(stale)
        elif verb == "task":
            command = sys.argv[2] if len(sys.argv) > 2 else ""
            slug = sys.argv[3] if len(sys.argv) > 3 else ""
            _CLI.update({"started_at": now(), "argv": sys.argv[2:9], "command": command, "slug": slug})
            if command == "start":
                requirements = parse_start_requirements(sys.argv[5] if len(sys.argv) > 5 else None)
                done(task_start(slug, sys.argv[4] if len(sys.argv) > 4 else "", requirements))
            if command == "inspect":
                done(task_inspect(slug, sys.argv[4] if len(sys.argv) > 4 else ""))
            if command == "act":
                done(task_action(slug, json.loads(sys.argv[4])))
            if command == "goto":
                done(task_action(slug, {"op": "goto", "url": sys.argv[4]}))
            if command == "click":
                done(task_action(slug, {"op": "click", "handle": sys.argv[4]}))
            if command == "fill":
                done(task_action(slug, {"op": "fill", "handle": sys.argv[4], "value": sys.argv[5]}))
            if command == "login":
                # argv carries the SITE only. The credential is leased from the credential plane
                # inside task_login and typed into the page there — it never passes through here,
                # through the journal (`_CLI`) or through the response.
                done(task_login(slug, sys.argv[4] if len(sys.argv) > 4 else ""))
            if command == "press":
                done(task_action(slug, {"op": "press", "handle": sys.argv[4], "key": sys.argv[5] if len(sys.argv) > 5 else "Enter"}))
            if command == "wait":
                done(task_action(slug, {"op": "wait", "timeout_ms": int(sys.argv[4]) if len(sys.argv) > 4 else 500}))
            if command == "extract":
                done(task_action(slug, {"op": "extract", "handle": sys.argv[4]}))
            if command == "screenshot":
                # `… full` captures the WHOLE document, not just the small viewport — the picture
                # counterpart of `read`, for the pages that must be seen rather than quoted.
                done(task_action(slug, {"op": "screenshot",
                                        "name": sys.argv[4] if len(sys.argv) > 4 else "final",
                                        "full_page": len(sys.argv) > 5 and sys.argv[5] == "full"}))
            if command == "read":
                # The whole page as text, in ONE answer, whatever the screen size (see task_page_read).
                done(task_page_read(slug, int(sys.argv[4]) if len(sys.argv) > 4 else 120000))
            if command == "captcha":
                # `captcha <slug> detect` reads the challenge (frame, instruction, targets, picture);
                # `captcha <slug> click <index>` answers it with one human-like click. The caller is
                # the one that can SEE, so it decides which target — this loop never guesses.
                done(task_captcha(slug, sys.argv[4] if len(sys.argv) > 4 else "detect",
                                  sys.argv[5] if len(sys.argv) > 5 else ""))
            if command == "verify":
                done(task_verify(slug))
            if command == "finish":
                done(task_finish(slug))
            if command == "status":
                done(task_status(slug))
            if command == "heartbeat":
                done(task_heartbeat(slug))
            if command == "goal":
                done(task_goal(slug, sys.argv[4] if len(sys.argv) > 4 else "", sys.argv[5] if len(sys.argv) > 5 else "", 5))
            raise ValueError("unknown task command")
        else:
            print(__doc__)
            sys.exit(2)
    except (ValueError, RuntimeError, json.JSONDecodeError) as error:
        task_error(error)
    except Exception as error:                             # every failure is still one JSON object
        task_error(BrowserTaskError("task_internal_error", f"{type(error).__name__}: {error}"))


if __name__ == "__main__":
    main()
