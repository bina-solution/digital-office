#!/usr/bin/env python3
"""
browser42 tab reaper — keeps the one shared Chromium from piling up tabs.

WHY: the own-your-tab rule (window.name = b42:<session>) only governs CDP *scripts*.
Agents driving via the Playwright MCP open tabs that are NEVER tagged, and nothing runs
a trim on that path — so untagged duplicates accumulate (e.g. N identical /signin tabs).
This janitor enforces the cap no matter who opened the tab.

RULES (deliberately conservative — it must never disturb live work):
  1. Never touch page 0 (the human /view anchor) or any tab tagged `b42:*`/`b42g:*`
     (owned sessions / session groups).
  2. Dedupe untagged tabs by URL — keep the NEWEST, close older identical ones.
  3. Cap the browser at MAX_TABS — reap oldest untagged first (tagged sessions are spared).

Runs as a sidecar (loop) or one-shot:
  python3 reaper.py              # loop forever, sweep every INTERVAL seconds
  python3 reaper.py --once       # sweep once and exit (manual cleanup)

Env: CDP (default http://browser42-browser:9222), MAX_TABS (8), INTERVAL (30).
Holds ONE long-lived connection and never calls browser.close()/context.close() — it only
closes the specific untagged tabs it decides to reap. If the browser restarts the connection
drops; the reaper waits for CDP and RECONNECTS (which re-wakes the headed Chrome), so the live
view self-heals after a `b42 dump`/`load`/recreate without a crash-restart loop.
"""
import json, os, sys, time
from pathlib import Path
from urllib.request import Request, urlopen

CDP      = os.environ.get("CDP", "http://browser42-browser:9222")
MAX_TABS = int(os.environ.get("MAX_TABS", "6"))
INTERVAL = int(os.environ.get("INTERVAL", "30"))
ONCE     = "--once" in sys.argv
GRACE_SECONDS = int(os.environ.get("GRACE_SECONDS", "60"))
TASKS_DIR = Path(os.environ.get("TASKS_DIR", "/data/tasks"))
TERMINAL_STATES = {"finished", "rejected", "stalled", "closed", "failed"}
# Lane reconciliation (R-lane): a tab lane on any-concurrency is closed by finish /
# watchdog, but a task that DIES before finish (crashed start, legacy run from before
# span_close_tab existed) leaves its lane span open forever — the UI shows a dead task
# as "live". The reaper is the one component that always runs and knows both the live
# tagged tabs and the task states, so it reconciles: terminal (or zombie-allocated)
# task + no live tagged tab => push the lane-closing span. Idempotent via upsert-by-id.
SPANS_URL = os.environ.get("ANY_CONCURRENCY_SPANS_URL", "http://any-concurrency:8080/ingest/span")
SPANS_ENABLED = os.environ.get("BROWSER42_SPANS_ENABLED", "1") not in {"0", "false", "no", ""}
ALLOC_LANE_TIMEOUT = int(os.environ.get("BROWSER42_LANE_ALLOC_TIMEOUT", "1800"))
LANE_CLOSED: set = set()  # once per process — upserts are idempotent, don't re-push
first_seen = {}

# Idle sleep (start-browser.sh §4k). The reaper is the idle DECIDER — it is the one process that sees
# every tab, every task journal and the activity markers — and the browser container executes:
# after IDLE_SLEEP_S with no tab change, no marker touched (agent verbs, a /view session) and no
# live task, it releases its persistent CDP connection (which is what keeps Chrome launched) and
# writes /data/.sleep-request; start-browser.sh's sleeper ends Chrome gracefully and writes
# /data/.sleeping; this loop then waits — reconnecting earlier would relaunch Chrome ourselves,
# because cloakserve launches on connect — until the browser container clears the marker on the
# next use. 0 = never sleep. /data/settings.json {"idle_sleep_s": N} (bbox b42 sleep after N) wins
# over the environment.
ACTIVITY_DIR = Path("/data/.activity")
SLEEPING = Path("/data/.sleeping")
SLEEP_REQUEST = Path("/data/.sleep-request")
SETTINGS = Path("/data/settings.json")
IDLE_SLEEP_DEFAULT = int(os.environ.get("BROWSER42_IDLE_SLEEP_S", "120"))


def idle_sleep_s() -> int:
    try:
        return int(json.loads(SETTINGS.read_text()).get("idle_sleep_s", IDLE_SLEEP_DEFAULT))
    except Exception:
        return IDLE_SLEEP_DEFAULT


def markers_epoch() -> float:
    t = 0.0
    try:
        for f in ACTIVITY_DIR.iterdir():
            t = max(t, f.stat().st_mtime)
    except OSError:
        pass
    return t


def live_task_exists() -> bool:
    """A task that is not terminal owns the browser, however quiet its tab looks right now."""
    try:
        for d in TASKS_DIR.iterdir():
            rec = task_record(d.name)
            if rec and rec.get("state") not in TERMINAL_STATES:
                return True
    except OSError:
        pass
    return False


def page_fingerprint(b) -> tuple:
    out = []
    for ctx in b.contexts:
        for pg in ctx.pages:
            try:
                out.append(pg.url)
            except Exception:
                out.append("?")
    return tuple(out)


# "Continue where it was" is done HERE, not left to Chromium. Measured 2026-09-30 (runs 6-8):
# --restore-last-session plus session.restore_on_startup=1 plus a graceful CDP Browser.close still
# brought back an empty new-tab page — this Chrome writes Tabs_* files but no Session_* window
# record for its CDP-driven session, so Chromium has nothing to restore from. The reaper is the one
# process that sees every tab at the moment of sleep, so it writes their URLs down and reopens them
# after the wake; agents' own tabs are re-created by group-manager by tag anyway, this covers the
# human's. Nothing is lost either way: the profile (cookies, logins) never leaves the volume.
LAST_TABS = Path("/data/last-tabs.json")
_SKIP = ("about:blank", "chrome://new-tab-page/", "chrome://newtab/", "")


def save_tabs(b) -> int:
    urls = []
    for ctx in b.contexts:
        for pg in ctx.pages:
            try:
                u = pg.url
            except Exception:
                continue
            if u not in _SKIP and u not in urls:
                urls.append(u)
    try:
        LAST_TABS.write_text(json.dumps({"saved_at": int(time.time()), "urls": urls}))
    except OSError:
        pass
    return len(urls)


def restore_tabs(b) -> int:
    try:
        urls = json.loads(LAST_TABS.read_text()).get("urls") or []
    except Exception:
        return 0
    have = set(page_fingerprint(b))
    ctx = b.contexts[0] if b.contexts else b.new_context()
    n = 0
    for u in urls:
        if u in have:
            continue
        try:
            pg = ctx.new_page()
            pg.goto(u, wait_until="domcontentloaded", timeout=20000)
            n += 1
        except Exception as e:
            print(f"restore: {u[:60]}: {repr(e)[:80]}", flush=True)
    try:
        LAST_TABS.unlink()
    except OSError:
        pass
    return n


def is_terminal_slug(slug: str) -> bool:
    """True when the task journal says the slug is done — its tabs are garbage.
    Re-read right before closing so a same-slug restart can't lose a fresh tab."""
    if not slug:
        return False
    try:
        return json.loads((TASKS_DIR / slug / "task.json").read_text()).get("state") in TERMINAL_STATES
    except Exception:
        return False


def task_record(slug: str) -> dict | None:
    try:
        return json.loads((TASKS_DIR / slug / "task.json").read_text())
    except Exception:
        return None


def span_push(payload: dict) -> None:
    if not SPANS_ENABLED:
        return
    try:
        request = Request(SPANS_URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=1.5):
            pass
    except Exception:
        pass


def span_close_tab(slug: str, opened_at: int, status: str = "reaped") -> None:
    end_ms = int(time.time() * 1000)
    started_ms = opened_at * 1000
    span_push({
        "id": f"b42tab:{slug}", "src": "browser42", "svc": f"tab:{slug}", "svcid": f"tab:{slug}",
        "label": f"🖥️ {slug}", "status": status, "s": started_ms, "e": end_ms, "d": max(0, end_ms - started_ms),
        "meta": {"kind": "tab", "slug": slug, "closed_by": "reaper"},
    })


def reconcile_lanes(live_tagged_slugs: set, now: int | None = None) -> None:
    """Close stale tab lanes: task terminal (or allocated past the queue timeout) and no
    live tagged tab for it. Best-effort — monitoring must never break the sweep."""
    if not SPANS_ENABLED:
        return
    try:
        dirs = [d for d in TASKS_DIR.iterdir() if d.is_dir()]
    except Exception:
        return
    now = int(time.time()) if now is None else now
    for directory in dirs:
        slug = directory.name
        if slug in LANE_CLOSED or slug in live_tagged_slugs:
            continue
        task = task_record(slug)
        if not task:
            continue  # unknown slug — conservative, leave the lane alone
        state = task.get("state")
        created = int(task.get("created_at", 0))
        age = now - created
        doomed = state in TERMINAL_STATES or (state == "allocated" and age > ALLOC_LANE_TIMEOUT)
        if not doomed:
            continue
        try:
            span_close_tab(slug, created, "reaped")
            LANE_CLOSED.add(slug)
            print(f"reaper closed stale lane: {slug} (task state={state})", flush=True)
        except Exception:
            pass


def _name(pg):
    # Bounded read — see group-manager._name: an unbounded evaluate here lets one
    # saturated ad-heavy tab wedge the reaper's scan (and every reap cycle) for the
    # full default timeout. 2s cap; unreadable tags are re-checked next cycle.
    # NOTE: Page.evaluate() has NO `timeout` kwarg — the old call raised TypeError on
    # EVERY tab (silently -> ''), so the reaper saw ZERO tagged tabs and never reaped
    # terminal-task tabs: that is why groups piled up ("nobody cleaned"), 2026-08-05.
    # Read window.name via a CDP session like group-manager._name (ms-fast).
    try:
        session = pg.context.new_cdp_session(pg)
        try:
            result = session.send("Runtime.evaluate", {"expression": "window.name", "returnByValue": True})
        finally:
            try: session.detach()
            except Exception: pass
        value = (result or {}).get("result", {}).get("value")
        return value if isinstance(value, str) else ""
    except Exception:
        return ""


def reap(b):
    live_slugs = set()
    for ctx in b.contexts:
        pages = ctx.pages
        if not pages:
            continue
        anchor = pages[0]                         # rule 1: page 0 is the /view anchor — never close
        rest = pages[1:]
        tagged   = [p for p in rest if _name(p).startswith(("b42:", "b42g:"))]  # owned sessions/groups
        untagged = [p for p in rest if p not in tagged]
        # rule 1b: a tagged tab whose task is TERMINAL is a leak (finish's close can
        # fail against a busy browser) — it holds ad-heavy renderers forever and is
        # exactly what saturates Chrome. Sweep it; live sessions stay spared.
        doomed_tagged = []
        for pg in tagged:
            slug = _name(pg).split(":", 1)[1] if ":" in _name(pg) else ""
            if is_terminal_slug(slug):
                doomed_tagged.append((pg, slug))
        tagged = [p for p in tagged if p not in [d for d, _ in doomed_tagged]]
        for pg in tagged:
            nm = _name(pg)
            if ":" in nm:
                live_slugs.add(nm.split(":", 1)[1])
        for pg, slug in doomed_tagged:
            try:
                u = pg.url
                pg.close()
                print(f"reaped terminal-task tab: {slug} {u[:60]}", flush=True)
            except Exception:
                pass
        now = time.monotonic()
        live_ids = {id(page) for page in pages}
        for page in pages:
            first_seen.setdefault(id(page), now)
        for page_id in list(first_seen):
            if page_id not in live_ids:
                first_seen.pop(page_id, None)
        untagged = [p for p in untagged if now - first_seen[id(p)] >= GRACE_SECONDS]

        doomed = []
        # rule 2: dedupe untagged by URL, keeping the newest (last) occurrence
        seen = set()
        for pg in reversed(untagged):
            try: url = pg.url
            except Exception: url = ""
            if url in seen:
                doomed.append(pg)
            else:
                seen.add(url)
        survivors = [p for p in untagged if p not in doomed]

        # rule 3: cap total — reap oldest surviving untagged first (anchor + tagged are kept)
        keep_untagged = max(0, MAX_TABS - 1 - len(tagged))
        if len(survivors) > keep_untagged:
            doomed += survivors[:len(survivors) - keep_untagged]

        for pg in doomed:
            try:
                u = pg.url
                pg.close()
                print(f"reaped untagged tab: {u[:80]}", flush=True)
            except Exception:
                pass
    reconcile_lanes(live_slugs)


def _connect(p):
    # Hold ONE persistent connection. cloakserve answers 502 until Chrome's CDP endpoint is up
    # (it launches Chrome ON this connect), so retry until ready — the browser may be (re)starting.
    # This connect is also what RE-WAKES the headed Chrome after a browser-container restart, so
    # keeping the reaper resilient (vs. crash-and-let-Docker-restart) is what makes the live view
    # come back on its own after `b42 dump`/`load`/recreate — no per-caller CDP ping needed.
    # BACKOFF, because every connect is a LAUNCH: cloakserve starts Chrome on connect and answers 502
    # when Chrome has not bound CDP within its launch wait — on a loaded box a cold Chromium with a
    # real profile needs longer than that — after which it quarantines the profile and the next
    # connect launches again. Measured 2026-09-30 17:50 at load 50: this loop at a fixed 3 s was
    # the relaunch engine (a 502 every few seconds, a `.corrupt-*` directory each). 3 s → 6 → 12 →
    # … → 60 s gives a launch in progress the time it needs and turns a storm into one attempt a
    # minute; the first connect after a wake is still immediate.
    # timeout=120 s: cloakserve launches Chrome INSIDE this connect, and a cold Chromium with a real
    # profile took 52 s on 2026-09-30 18:51 at load 20. Playwright's default 30 s gave up mid-launch,
    # the websocket closed, cloakserve counted zero clients, and the sleeper put the freshly ready
    # Chrome to sleep ten seconds later — the reaper never got to hold it.
    delay = 3
    while True:
        try:
            b = p.chromium.connect_over_cdp(CDP, timeout=120000)
            print(f"reaper connected: cap={MAX_TABS} interval={INTERVAL}s once={ONCE}", flush=True)
            return b
        except Exception as e:
            print(f"reaper waiting for browser CDP (retry in {delay}s):", repr(e)[:100], flush=True)
            time.sleep(delay)
            delay = min(60, delay * 2)


def main():
    from playwright.sync_api import sync_playwright  # lazy: keeps the module importable for unit tests
    p = sync_playwright().start()
    b = _connect(p)
    last_activity = time.time()
    last_fp = None
    while True:
        try:
            reap(b)
            # Idle accounting: a changed tab set/URL, a touched marker or a live task is "use".
            fp = page_fingerprint(b)
            if fp != last_fp:
                last_fp = fp
                last_activity = time.time()
            last_activity = max(last_activity, markers_epoch())
            limit = idle_sleep_s()
            idle = time.time() - last_activity
            if limit > 0 and idle >= limit and not SLEEPING.exists() and not live_task_exists():
                saved = save_tabs(b)
                print(f"idle {int(idle)}s >= {limit}s, no live task — {saved} tab(s) noted; releasing CDP; the browser goes to sleep", flush=True)
                try:
                    b.close()          # disconnect only: connect_over_cdp never closes the browser, and cloakserve blocks Browser.close anyway
                except Exception:
                    pass
                SLEEP_REQUEST.write_text(str(int(time.time())))
                while (SLEEP_REQUEST.exists() or SLEEPING.exists()) and not ONCE:
                    time.sleep(5)
                print("reaper: browser awake — reconnecting", flush=True)
                b = _connect(p)
                restored = restore_tabs(b)
                if restored:
                    print(f"reaper: reopened {restored} tab(s) from before the sleep", flush=True)
                last_activity = time.time()
                last_fp = None
        except Exception as e:
            # A dropped connection (browser restarted) lands here. Reconnect instead of exiting —
            # the reconnect re-wakes Chrome, so the view self-heals without a Docker restart loop.
            try: alive = b.is_connected()
            except Exception: alive = False
            if not alive:
                # …unless the browser is ASLEEP: a connect is a launch, and relaunching a browser
                # that was just put to sleep by the sleeper's own decision (idle, no client — e.g.
                # this reaper still mid-connect on a loaded box) is the ping-pong measured 2026-09-30
                # 20:45-20:50 (three sleep/launch cycles in five minutes). Wait for the wake instead.
                if SLEEPING.exists() or SLEEP_REQUEST.exists():
                    print("reaper: browser connection lost while it sleeps — waiting for the wake", flush=True)
                    while (SLEEPING.exists() or SLEEP_REQUEST.exists()) and not ONCE:
                        time.sleep(5)
                print("reaper: browser connection lost — reconnecting…", flush=True)
                b = _connect(p)
                restored = restore_tabs(b)
                if restored:
                    print(f"reaper: reopened {restored} tab(s) from before the sleep", flush=True)
                last_activity = time.time()
                last_fp = None
            else:
                print("reaper sweep error:", repr(e)[:120], flush=True)
        if ONCE:
            break
        time.sleep(INTERVAL)
    sys.stdout.flush()
    os._exit(0)                                   # never tear down shared state on exit


if __name__ == "__main__":
    main()
