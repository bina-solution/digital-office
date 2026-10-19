"""sites.scheduler — what the office does on its own, and what it refuses to do twice.

Four loops, each with one job:

  * **uptime** (every `SITES_UPTIME_SECONDS`, default 60) — probe every monitored site, record the
    sample, and SPEAK only on a state CHANGE. A site that has been down for six hours produces one
    notification and 360 samples, not 360 notifications: an alert that repeats is an alert the owner
    swipes away, and then the real one goes with it.
  * **visits** (every `SITES_COLLECT_SECONDS`, default 300) — read each site's access log from the
    last byte consumed and fold it into hourly counts.
  * **scans** (daily, `SITES_SCAN_HOUR` local, default 03:00) — security, SEO and beauty, each on
    its own cadence (beauty renders a browser; doing that hourly to learn nothing would be a
    container spinning for a number that moves weekly).
  * **housekeeping** (daily) — drop samples older than the retention window.

Every loop is wrapped so that ONE bad site cannot stop the rest: an exception is logged, recorded as
an event on that site, and the loop moves on. A monitor that dies because the thing it monitors is
broken is worse than no monitor, because it looks like everything is fine.
"""
from __future__ import annotations

import logging
import os
import threading
import time

import checks
import machines
import public
import runtime
import store
from checks import uptime, visits

log = logging.getLogger("sites.scheduler")

UPTIME_SECONDS = int(os.environ.get("SITES_UPTIME_SECONDS", "60"))
COLLECT_SECONDS = int(os.environ.get("SITES_COLLECT_SECONDS", "300"))
DISPATCH_SECONDS = int(os.environ.get("SITES_DISPATCH_SECONDS", "300"))
#: How often the office refreshes its copy of a site it serves and re-publishes the edge file.
#: Five minutes: the content changes when a deploy or an asset push changes it (both of which sync
#: immediately), and a tighter loop would only re-read the same bytes through SSH.
PUBLIC_SECONDS = int(os.environ.get("SITES_PUBLIC_SYNC_SECONDS", "300"))
SCAN_HOUR = int(os.environ.get("SITES_SCAN_HOUR", "3"))
SAMPLE_RETENTION_DAYS = int(os.environ.get("SITES_SAMPLE_RETENTION_DAYS", "30"))
NOTIFY_URL = os.environ.get("NOTIFICATIONS_URL", "http://notifications:8977").rstrip("/")
NOTIFY_ENABLED = os.environ.get("SITES_NOTIFY", "1") != "0"
DISABLED = os.environ.get("SITES_SCHEDULER", "1") == "0"

_state = {"started": False, "last_uptime": None, "last_collect": None, "last_scan": None,
          "last_public": None, "errors": []}
_lock = threading.Lock()


def status() -> dict:
    return dict(_state)


def _notify(title: str, body: str, level: str = "info", site_id: str | None = None,
            link: str = "") -> None:
    """One sentence to the owner's notification centre, and never a reason to fail a check."""
    if not NOTIFY_ENABLED:
        return
    try:
        import requests
        requests.post(f"{NOTIFY_URL}/api/notifications",
                      json={"source": "sites", "title": title, "body": body, "level": level,
                            "source_id": site_id or "", "link": link, "meta": {"app": "sites"}},
                      timeout=10)
    except Exception as e:                                   # noqa: BLE001
        log.warning("notification not delivered: %s", type(e).__name__)


# ── uptime ───────────────────────────────────────────────────────────────────────────────────────
def check_uptime(site: dict, notify: bool = True) -> dict:
    sample = uptime.probe(site)
    store.add_sample(site["id"], bool(sample.get("ok")), sample.get("status"), sample.get("ms"),
                     uptime.reason(sample) or None, sample.get("url"))
    state = "up" if sample.get("ok") else "down"
    previous = site.get("last_state")
    store.set_state(site["id"], state, None if sample.get("ok") else uptime.reason(sample))
    if notify and previous and previous != state:
        name = site.get("label") or site["id"]
        url = runtime.site_url(site)
        if state == "down":
            store.event(site["id"], "down", f"האתר לא ענה: {uptime.reason(sample)}",
                        {"url": sample.get("url")})
            _notify(f"האתר „{name}” לא עונה", f"{uptime.reason(sample)} · {sample.get('url')}",
                    "error", site["id"], url)
        else:
            store.event(site["id"], "up", "האתר חזר לענות", {"ms": sample.get("ms")})
            _notify(f"האתר „{name}” חזר לענות", f"{sample.get('status')} תוך {sample.get('ms')}ms",
                    "info", site["id"], url)
    return sample


def uptime_pass() -> dict:
    out = {"checked": 0, "up": 0, "down": 0}
    for site in store.list_sites(enabled_only=True):
        if not site.get("monitor"):
            continue
        try:
            s = check_uptime(site)
            out["checked"] += 1
            out["up" if s.get("ok") else "down"] += 1
        except Exception as e:                               # noqa: BLE001
            log.warning("uptime failed for %s: %s", site.get("id"), type(e).__name__)
            out.setdefault("errors", []).append(f"{site.get('id')}: {type(e).__name__}")
    _state["last_uptime"] = store.now()
    return out


# ── visits ───────────────────────────────────────────────────────────────────────────────────────
def collect_visits(site: dict) -> dict:
    """Read what is new in the site's log and fold it into hourly counts.

    The cursor is advanced ONLY by what was actually ingested, so a collection that fails halfway
    re-reads the same window next time instead of losing it — double counting is corrected for free
    because an hour's bucket is upserted by (site, hour), and losing visits is not correctable at all.
    """
    src = runtime.log_source(site)
    offset = int(store.cursor_get(site["id"], "log_offset", "0") or 0)
    since = int(store.cursor_get(site["id"], "log_since", "0") or 0)
    if src["kind"] == "docker" and not since:
        since = store.now() - COLLECT_SECONDS * 2
    res = runtime.read_logs(site, offset=offset, since=since)
    agg_ = visits.aggregate(res.get("lines") or [], host=(site.get("hosts") or [""])[0])
    for hour, h in (agg_.get("hours") or {}).items():
        store.add_visit_hour(site["id"], int(hour), h["hits"], h["uniques"], h["bots"],
                             h["errors"], h["bytes"], h["paths"], h["refs"])
    if src["kind"] == "file":
        store.cursor_set(site["id"], "log_offset", str(res.get("offset") or 0))
    else:
        store.cursor_set(site["id"], "log_since", str(store.now()))
    return {"site": site["id"], "lines": len(res.get("lines") or []), "hits": agg_.get("hits", 0),
            "bots": agg_.get("bots", 0), "source": res.get("source")}


def collect_pass() -> dict:
    out = {"sites": 0, "hits": 0}
    for site in store.list_sites(enabled_only=True):
        # A site the OFFICE serves writes no access log on the machine — its visits are counted at
        # the moment they are served (public.serve). Reading a log that no longer grows would keep
        # publishing stale numbers as if they were today's.
        if public.mode_of(site) == "office":
            continue
        try:
            r = collect_visits(site)
            out["sites"] += 1
            out["hits"] += r.get("hits") or 0
        except Exception as e:                               # noqa: BLE001
            log.warning("visit collection failed for %s: %s", site.get("id"), type(e).__name__)
            out.setdefault("errors", []).append(f"{site.get('id')}: {type(e).__name__}")
    _state["last_collect"] = store.now()
    return out


# ── scans ────────────────────────────────────────────────────────────────────────────────────────
def _check_kwargs(name: str, cfg: dict) -> dict:
    """The site's own knobs → the check's parameters, EXPLICITLY.

    `cfg` also holds cadence keys (`beauty_hours`, `seo_pages`…) that are not parameters of any
    check, so passing it through wholesale would raise `unexpected keyword argument` on the first
    site that configured a cadence — and the scan would fail for a reason that has nothing to do
    with the site. The mapping is written out for that reason and not for elegance.
    """
    if name == "security":
        return {"deep": bool(cfg.get("deep", True))}
    if name == "seo":
        return {"max_pages": int(cfg.get("seo_pages") or 20),
                "deep": bool(cfg.get("deep", True))}
    if name == "beauty":
        return {"min_score": cfg.get("beauty_min"), "viewports": cfg.get("viewports"),
                "mode": cfg.get("beauty_mode") or "ui"}
    return {}


def run_scan(site_id: str, names: list[str] | None = None, trigger: str = "manual") -> dict:
    """Run checks against one site and record everything: the run, its findings, its events.

    A check that RAISES still produces a run row with `state=error` and the exception's name. The
    alternative — no row — makes a crashed scan indistinguishable from a scan that was never asked
    for, and "the SEO report stopped updating three weeks ago" is exactly the failure this app exists
    to catch in other people's systems.
    """
    site = store.get_site(site_id)
    if not site:
        raise KeyError(site_id)
    names = names or list(checks.SCAN_CHECKS)
    out: dict = {"site": site_id, "trigger": trigger, "checks": {}}
    for name in names:
        if name not in checks.SCAN_CHECKS:
            continue
        run_id = store.start_run(site_id, name)
        try:
            result = checks.run(name, site, **_check_kwargs(name, site.get("checks") or {}))
            counts = store.record_findings(site_id, name, result.get("findings") or [])
            store.finish_run(run_id, result.get("state") or "ok",
                             {**(result.get("summary") or {}), "counts": counts})
            out["checks"][name] = {"state": result.get("state"), **counts}
        except Exception as e:                               # noqa: BLE001
            log.exception("check %s failed on %s", name, site_id)
            store.finish_run(run_id, "error", {}, f"{type(e).__name__}: {e}")
            out["checks"][name] = {"state": "error", "error": f"{type(e).__name__}: {e}"}
    store.event(site_id, "scan", "סריקה הורצה", {"checks": out["checks"], "trigger": trigger})
    _state["last_scan"] = store.now()
    return out


def due_scans(site: dict) -> list[str]:
    """Which checks are DUE for this site — decided from the last run of each, never from a timer
    that resets on restart (an office redeployed twice a day would otherwise never scan anything)."""
    cfg = site.get("checks") or {}
    due = []
    for name in checks.SCAN_CHECKS:
        entry = checks.CATALOG[name]
        hours = float(cfg.get(f"{name}_hours") or entry["default_hours"])
        last = store.last_run(site["id"], name)
        if not last or not last.get("finished_at"):
            due.append(name)
            continue
        if store.now() - last["finished_at"] >= hours * 3600:
            due.append(name)
    return due


def scan_pass(force: bool = False) -> dict:
    out: dict = {"sites": {}}
    for site in store.list_sites(enabled_only=True):
        due = list(checks.SCAN_CHECKS) if force else due_scans(site)
        if not due:
            continue
        try:
            out["sites"][site["id"]] = run_scan(site["id"], due, trigger="schedule")["checks"]
        except Exception as e:                               # noqa: BLE001
            log.warning("scan failed for %s: %s", site["id"], type(e).__name__)
    return out


# ── loops ────────────────────────────────────────────────────────────────────────────────────────
def _sleep_until_next_hour(hour: int) -> None:
    now = time.localtime()
    seconds = ((hour - now.tm_hour) % 24) * 3600 - now.tm_min * 60 - now.tm_sec
    time.sleep(max(60, seconds))


def _loop(name: str, interval: int, fn) -> None:
    log.info("scheduler loop %s every %ss", name, interval)
    while True:
        started = time.time()
        try:
            res = fn()
            if res:
                log.info("%s: %s", name, res)
        except Exception as e:                               # noqa: BLE001
            log.exception("%s pass failed: %s", name, e)
            with _lock:
                _state["errors"] = (_state["errors"] + [f"{name}: {type(e).__name__}: {e}"])[-10:]
        time.sleep(max(5, interval - (time.time() - started)))


def _scan_loop() -> None:
    while True:
        _sleep_until_next_hour(SCAN_HOUR)
        try:
            scan_pass()
        except Exception as e:                               # noqa: BLE001
            log.exception("daily scan failed: %s", e)
        try:
            store.prune_samples(SAMPLE_RETENTION_DAYS)
        except Exception as e:                               # noqa: BLE001
            log.warning("prune failed: %s", type(e).__name__)
        time.sleep(3600)


def public_pass() -> dict:
    """Keep the public path true: a fresh copy of every office-served site, and the edge published.

    Only sites whose record says `mode: office` are touched. A site the machine still serves is
    skipped entirely — this loop must never be the reason a container-served site is interrupted.
    """
    out: dict = {"sites": 0, "synced": [], "errors": []}
    try:
        rows = public.office_sites()
    except Exception as e:                                   # noqa: BLE001
        return {**out, "errors": [f"office_sites: {type(e).__name__}"]}
    for site in rows:
        out["sites"] += 1
        try:
            m = public.meta(site["id"])
            if public.SYNC_SECONDS and (time.time() - float(m.get("at") or 0)) < PUBLIC_SECONDS:
                continue
            if not public.cached_file_count(site["id"]):
                res = public.sync(site)
                if res.get("ok"):
                    out["synced"].append(site["id"])
                else:
                    out["errors"].append(f"{site['id']}: {res.get('reason')}")
        except Exception as e:                               # noqa: BLE001
            out["errors"].append(f"{site['id']}: {type(e).__name__}")
    # Called even with no office-served site: the pass is also what REMOVES a stale edge file
    # after a site moved back to its own container (or was deleted) while this process was down.
    # Cheap when there is nothing to publish — one `test -f` on the machine.
    try:
        out["edge"] = public.publish()
    except Exception as e:                                   # noqa: BLE001
        out["errors"].append(f"publish: {type(e).__name__}")
    _state["last_public"] = store.now()
    if out["errors"]:
        log.warning("public pass: %s", "; ".join(out["errors"])[:400])
    return out


def start() -> None:
    """Idempotent: a reload (uvicorn --reload, a second worker) must not double the probing."""
    with _lock:
        if _state["started"] or DISABLED:
            return
        _state["started"] = True
    for name, interval, fn in (("uptime", UPTIME_SECONDS, uptime_pass),
                               ("visits", COLLECT_SECONDS, collect_pass),
                               ("dispatch", DISPATCH_SECONDS, _dispatch_pass),
                               ("public", PUBLIC_SECONDS, public_pass)):
        threading.Thread(target=_loop, args=(name, interval, fn), daemon=True,
                         name=f"sites-{name}").start()
    threading.Thread(target=_scan_loop, daemon=True, name="sites-scans").start()
    log.info("scheduler started (uptime %ss, visits %ss, public %ss, scans daily at %02d:00)",
             UPTIME_SECONDS, COLLECT_SECONDS, PUBLIC_SECONDS, SCAN_HOUR)


def _dispatch_pass() -> dict:
    """Ask the `computers` service for a fresh fleet reading so a machine that went away is noticed
    even when nothing else is looking at it. Cheap on purpose (no SSH probe) — it warms the failure
    so the UI shows it instead of a stale green."""
    machines_list, err = machines.list_machines(probe=False)
    if err:
        return {"machines": err}
    return {"machines": len(machines_list)}
