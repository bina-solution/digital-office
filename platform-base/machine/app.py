from __future__ import annotations

import asyncio
import json
import os
import platform
import socket
import subprocess
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import docker
import desk
import requests  # the docker SDK's own transport (its dependency): a cleanup's read timeout is its exception
from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# ── Sentry/GlitchTip error reporting (platform standard) ──────────────────────────
# Wired declaratively: glitchtip-push mints this service's project + deterministic DSN into
# MACHINE_SENTRY_DSN in .env; compose maps it to SENTRY_DSN. No-op if unset. sentry-sdk
# auto-enables the FastAPI/Starlette integration.
_SENTRY_DSN = os.getenv("SENTRY_DSN")
if _SENTRY_DSN:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            environment=os.getenv("SENTRY_ENVIRONMENT", os.getenv("DEPLOYMENT_NAME", "production")),
            release=os.getenv("SENTRY_RELEASE"),
            traces_sample_rate=0.0,
            send_default_pii=False,
        )
    except Exception:  # never let telemetry break the app
        pass

APP_ROOT = Path(__file__).parent
STATIC_DIR = APP_ROOT / "static"
HOST_ROOT = Path(os.getenv("HOST_ROOT", "/host/root"))
DEPLOYMENT_PATH = Path(os.getenv("DEPLOYMENT_PATH", "/host/root/root/digital-office"))
POLL_TIMEOUT_S = float(os.getenv("MACHINE_DU_TIMEOUT_S", "20"))
CLEANUP_ALLOWED_ACTIONS = {
    action.strip()
    for action in os.getenv("MACHINE_CLEANUP_ALLOWED_ACTIONS", "").split(",")
    if action.strip()
}
DEPLOYMENT_NAME = os.getenv("DEPLOYMENT_NAME", "bina-deployment")
MAX_STAT_WORKERS = int(os.getenv("MACHINE_STAT_WORKERS", "8"))
OVERVIEW_CACHE_TTL_S = float(os.getenv("MACHINE_OVERVIEW_CACHE_TTL_S", "8"))
# The heavy disk walk (`du` of /var/lib/docker, /usr, the logs, home, the deployment, and `docker system df`)
# is taken again at most this often while a screen is open. Once a minute it re-walked EXF's 67 GB Docker
# tree all the time the owner watched it, on a 2-vCPU server the provider was throttling (DGO-1231); the
# folder sizes it shows do not move by the minute, and the disk's own use beside them stays live.
STORAGE_HEAVY_TTL_S = float(os.getenv("MACHINE_STORAGE_HEAVY_TTL_S", "900"))
# Background collector: keep the overview cache warm off the request path so the
# page loads instantly. Poll fast only while it's actually being watched (a
# request within ACTIVE_WINDOW_S), then relax to an idle heartbeat — light + optimised.
REFRESH_INTERVAL_S = float(os.getenv("MACHINE_REFRESH_INTERVAL_S", "10"))
ACTIVE_WINDOW_S = float(os.getenv("MACHINE_ACTIVE_WINDOW_S", "90"))
# Rolling metrics history for the resource chart (points × interval = window;
# 180 × 10s ≈ 30 min). Recorded by the collector so the chart is populated the
# instant the page loads — not built up client-side from empty.
HISTORY_POINTS = int(os.getenv("MACHINE_HISTORY_POINTS", "180"))

app = FastAPI(title="Automation Machine", version="0.1.0")
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_docker_client: docker.DockerClient | None = None
_executor = ThreadPoolExecutor(max_workers=MAX_STAT_WORKERS)
_cpu_prev: tuple[int, int] | None = None
_storage_cache: tuple[float, dict[str, Any]] | None = None
_overview_cache: tuple[float, dict[str, Any]] | None = None
_overview_lock = asyncio.Lock()
_last_access: float = 0.0  # last /api/overview hit — gates background poll cadence
_history: deque[dict[str, Any]] = deque(maxlen=HISTORY_POINTS)
_prev_net: tuple[float, int, int] | None = None  # (t, rx_total, tx_total) for rate calc
_cpu_pct: float | None = None       # sampled once per collector tick (delta is stateful)
_net_rate: tuple[int, int] = (0, 0)  # latest host rx/tx bytes-per-second
_building: bool = False              # a full container build is in flight


def docker_client() -> docker.DockerClient:
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"ok": "true"}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _host_path(path: str) -> Path:
    return HOST_ROOT / path.lstrip("/")


def _parse_os_release() -> dict[str, str]:
    data: dict[str, str] = {}
    for line in _read_text(_host_path("/etc/os-release")).splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key] = value.strip().strip('"')
    return data


def _cpu_times() -> tuple[int, int] | None:
    line = _read_text(_host_path("/proc/stat")).splitlines()[0:1]
    if not line:
        return None
    parts = [int(x) for x in line[0].split()[1:]]
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
    total = sum(parts)
    return idle, total


def _cpu_percent() -> float | None:
    global _cpu_prev
    current = _cpu_times()
    if current is None:
        return None
    if _cpu_prev is None:
        _cpu_prev = current
        return None
    prev_idle, prev_total = _cpu_prev
    idle, total = current
    _cpu_prev = current
    total_delta = max(total - prev_total, 1)
    idle_delta = max(idle - prev_idle, 0)
    return round(max(0.0, min(100.0, (1 - idle_delta / total_delta) * 100)), 1)


def _cpu_info() -> dict[str, Any]:
    text = _read_text(_host_path("/proc/cpuinfo"))
    model = "unknown"
    cores = 0
    for line in text.splitlines():
        if line.startswith("processor"):
            cores += 1
        if line.startswith("model name") and model == "unknown":
            model = line.split(":", 1)[1].strip()
    load = _read_text(_host_path("/proc/loadavg")).split()
    return {
        "model": model,
        "cores": cores or (os.cpu_count() or 0),
        "load1": float(load[0]) if len(load) > 0 else None,
        "load5": float(load[1]) if len(load) > 1 else None,
        "load15": float(load[2]) if len(load) > 2 else None,
        # read the collector-sampled value — never call _cpu_percent() here, or two
        # callers per tick would split the stateful idle/total delta and skew the %
        "percent": _cpu_pct,
    }


def _mem_info() -> dict[str, Any]:
    values: dict[str, int] = {}
    for line in _read_text(_host_path("/proc/meminfo")).splitlines():
        parts = line.replace(":", "").split()
        if len(parts) >= 2:
            values[parts[0]] = int(parts[1]) * 1024
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    used = max(total - available, 0)
    swap_total = values.get("SwapTotal", 0)
    swap_free = values.get("SwapFree", 0)
    return {
        "total": total,
        "available": available,
        "used": used,
        "percent": round((used / total * 100) if total else 0, 1),
        "swap_total": swap_total,
        "swap_used": max(swap_total - swap_free, 0),
    }


# ── the disk, watched where it is MEASURED (DGO-70) ───────────────────────────────────────────────
# This service already samples the machine's root every REFRESH_INTERVAL_S (10 s), so the "a filling
# disk is said within a minute" half of the item costs one comparison here — and a watcher that reads
# a number nobody looks at is the item's whole subject: `df` under 80% at rest, and a fill that is
# SAID when it happens rather than discovered by a person whose build just failed.
#
# The notice goes through the office's own notification centre (the same door every watcher uses),
# with an id of its own so the owner can close it and so a recovery closes it: posted on a
# TRANSITION (under → over, over → under) and not on every tick, because a notice on a schedule is a
# notice nobody reads.
DISK_WARN_PCT = float(os.environ.get("MACHINE_DISK_WARN_PCT", "80"))
DISK_ERROR_PCT = float(os.environ.get("MACHINE_DISK_ERROR_PCT", "92"))
NOTIFY_URL = (os.environ.get("MACHINE_NOTIFY_URL") or "http://notifications:8977/api/notifications").rstrip("/")
_disk_alarm_state: dict[str, Any] = {"over": False}


def disk_alarm(percent: float, free: int) -> dict[str, Any] | None:
    """The sentence a given reading deserves — None while the machine is fine.

    Pure, so the proof does not have to fill a disk: `/api/disk/probe` runs THIS function on a
    reading somebody hands it and, when told to, posts the result through the same call the loop
    makes.
    """
    gb = free / (1 << 30)
    if percent >= DISK_ERROR_PCT:
        return {"id": "machine-disk", "level": "error",
                "title": f"הדיסק של המנוע כמעט מלא — {percent:.0f}%",
                "body": f"נשארו {gb:.1f} GB פנויים. כל בנייה, כל גיבוי וכל ייבוא נכשלים מכאן והלאה."}
    if percent >= DISK_WARN_PCT:
        return {"id": "machine-disk", "level": "warn",
                "title": f"הדיסק של המנוע מתמלא — {percent:.0f}%",
                "body": f"נשארו {gb:.1f} GB פנויים (הסף {DISK_WARN_PCT:.0f}%). "
                        f"מה שמתפנה לבד: images שאינן בשימוש ומטמון בנייה (bbox status מראה כמה)."}
    return None


def _refused(url: str, code: int, read) -> None:
    """What the notices service said when it refused (`read` is the error's own e.read), in the log —
    its words, never thrown away."""
    try:
        said = read(200)
    except Exception:                       # noqa: BLE001 — a body that breaks off while read is no body
        said = b""
    print(f"[machine] {url} answered HTTP {code}: {said!r}", flush=True)


def _get_json(url: str) -> dict | None:
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        _refused(url, e.code, e.read)
        return None
    except Exception:                       # noqa: BLE001 — reading the list is best-effort too
        return None


def _notify(method: str, url: str, body: dict | None = None) -> bool:
    import urllib.error
    import urllib.request
    try:
        req = urllib.request.Request(url, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return 200 <= r.status < 300
    except urllib.error.HTTPError as e:
        _refused(url, e.code, e.read)
        return False
    except Exception:                       # noqa: BLE001 — a notice that cannot be sent is not a fault of the machine
        return False


def disk_watch() -> None:
    """One tick of the watch: say it when it starts, close it when it ends, nothing in between."""
    try:
        usage = _disk_usage(HOST_ROOT)
    except Exception:                       # noqa: BLE001 — an unreadable root is not a disk alarm
        return
    alarm = disk_alarm(usage["percent"], usage["free"])
    over = alarm is not None
    if over and not _disk_alarm_state["over"]:
        _notify("POST", NOTIFY_URL, {"source": "machine", "source_id": alarm["id"],
                                     "title": alarm["title"], "body": alarm["body"],
                                     "level": alarm["level"], "link": "/#/m/machine"})
    elif not over and _disk_alarm_state["over"]:
        # A RECOVERY CLOSES ITS OWN NOTICE, the way every watcher here does it: read the open ones
        # and mark this one — there is no "close by source" door, and inventing one for this call
        # would be a second way to do what the notice list already does.
        listing = _get_json(NOTIFY_URL + "?limit=60") or {}
        for row in (listing.get("notifications") or []):
            if row.get("source_id") == "machine-disk" and not row.get("is_read"):
                _notify("POST", f"{NOTIFY_URL}/{row.get('id')}/read")
    _disk_alarm_state["over"] = over


def _disk_usage(path: Path) -> dict[str, Any]:
    st = os.statvfs(path)
    total = st.f_frsize * st.f_blocks
    free = st.f_frsize * st.f_bavail
    used = total - free
    return {"path": str(path), "total": total, "used": used, "free": free, "percent": round((used / total * 100) if total else 0, 1)}


def _du_bytes(path: Path) -> int | None:
    try:
        output = subprocess.check_output(
            ["nice", "-n", "19", "du", "-sx", "--block-size=1", str(path)],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=POLL_TIMEOUT_S,
        )
        return int(output.split()[0])
    except Exception:
        return None


_storage_measuring = False


def _storage_overview() -> dict[str, Any]:
    """Disk use as it is now, with the last heavy measurement beside it.

    The heavy half — seven `du` walks and `docker system df` — takes tens of seconds on a busy
    machine, and it used to be measured ON the answer's path whenever it was a minute old. Every
    sixth collection of the whole screen waited for it, and so did the first request after a pause
    (22.6 s, measured 2026-10-06). It is measured behind the answer now: the answer carries the
    last measurement and its time, and an empty one — `generated_at: null` — until the first exists.
    """
    global _storage_measuring
    if not _storage_measuring and (not _storage_cache or time.time() - _storage_cache[0] >= STORAGE_HEAVY_TTL_S):
        _storage_measuring = True
        threading.Thread(target=_storage_measure, daemon=True).start()
    heavy = _storage_cache[1] if _storage_cache else {"top_paths": [], "docker_df": {}, "generated_at": None}
    return {"root": _disk_usage(HOST_ROOT), **heavy}


def _storage_measure() -> None:
    global _storage_cache, _storage_measuring
    try:
        _storage_cache = (time.time(), _storage_heavy())
    finally:
        _storage_measuring = False


def _storage_heavy() -> dict[str, Any]:
    paths = [
        ("Docker", _host_path("/var/lib/docker")),
        ("Deployment", DEPLOYMENT_PATH),
        ("OS /usr", _host_path("/usr")),
        ("var logs", _host_path("/var/log")),
        ("home", _host_path("/home")),
    ]
    top_paths = []
    for label, path in paths:
        if path.exists():
            size = _du_bytes(path)
            if size is not None:
                top_paths.append({"label": label, "path": str(path).replace(str(HOST_ROOT), ""), "size": size})
    top_paths.sort(key=lambda item: item["size"], reverse=True)

    try:
        docker_df = docker_client().df()
    except Exception as exc:
        docker_df = {"error": str(exc)}

    return {"top_paths": top_paths, "docker_df": docker_df, "generated_at": _iso_now()}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hostname() -> str:
    return _read_text(_host_path("/etc/hostname")).strip() or socket.gethostname()


def _uptime_seconds() -> float | None:
    text = _read_text(_host_path("/proc/uptime")).split()
    return float(text[0]) if text else None


def _container_health(attrs: dict[str, Any]) -> str | None:
    """The engine's health verdict — of a container that runs. On a stopped one the engine keeps the
    last probe's answer for good ("unhealthy": the probe that failed as it went down); that is its
    history, not its state, and counted it paints a red "not healthy" over a machine where
    everything that runs is well."""
    state = attrs.get("State", {})
    health = state.get("Health")
    return health.get("Status") if isinstance(health, dict) and state.get("Running") else None


def _safe_container_name(name: str) -> str:
    suffix = f"-{DEPLOYMENT_NAME}"
    return name[:-len(suffix)] if name.endswith(suffix) else name


def _container_summary(container: Any) -> dict[str, Any]:
    attrs = container.attrs
    state = attrs.get("State", {})
    return {
        "id": container.short_id,
        "name": _safe_container_name(container.name),
        "raw_name": container.name,
        "image": attrs.get("Config", {}).get("Image", ""),
        "status": state.get("Status") or container.status,
        "health": _container_health(attrs),
        "started_at": state.get("StartedAt"),
        "restart_count": attrs.get("RestartCount", 0),
        "labels": attrs.get("Config", {}).get("Labels") or {},
    }


#: Each running container's CPU counters as the previous collection read them, and when that was.
#: A container's CPU share is the difference between two readings — ours, not the engine's.
_prev_cpu: dict[str, tuple[int, int]] = {}
_prev_cpu_at = 0.0


def _stats_for_container(container: Any) -> dict[str, Any]:
    row = _container_summary(container)
    try:
        # ONE reading, no waiting. Without `one_shot` the engine reads every container twice, a
        # second apart, to fill `precpu_stats`: 1.9 s a container (measured 2026-10-06: six in
        # 11.2 s, against 0.02 s for six one-shot readings). With 53 running containers through 8
        # workers one collection took 16–68 s, so the screen that says "live" was that old — and
        # 53 one-second sampling streams were open on the engine for as long as anyone watched.
        stats = container.stats(stream=False, one_shot=True)
        cpu = stats.get("cpu_stats", {})
        now = (cpu.get("cpu_usage", {}).get("total_usage", 0), cpu.get("system_cpu_usage", 0))
        was = _prev_cpu.get(container.id)
        _prev_cpu[container.id] = now
        cpu_delta, system_delta = (now[0] - was[0], now[1] - was[1]) if was else (0, 0)
        online = cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage") or []) or 1
        row["cpu_percent"] = round((cpu_delta / system_delta * online * 100)
                                   if system_delta > 0 and cpu_delta >= 0 else 0, 2)

        mem = stats.get("memory_stats", {})
        usage = int(mem.get("usage", 0))
        cache = int((mem.get("stats") or {}).get("cache", 0))
        limit = int(mem.get("limit", 0))
        used = max(usage - cache, 0)
        row["memory"] = {"used": used, "limit": limit, "percent": round((used / limit * 100) if limit else 0, 1)}
        row["pids"] = (stats.get("pids_stats") or {}).get("current", 0)

        nets = stats.get("networks") or {}
        rx = sum(int(n.get("rx_bytes", 0)) for n in nets.values())
        tx = sum(int(n.get("tx_bytes", 0)) for n in nets.values())
        row["net"] = {"rx": rx, "tx": tx}  # cumulative since container start
    except Exception as exc:
        row["stats_error"] = str(exc)
        row["cpu_percent"] = 0
        row["memory"] = {"used": 0, "limit": 0, "percent": 0}
        row["net"] = {"rx": 0, "tx": 0}
        row["pids"] = 0
    return row


async def _containers(include_stats: bool = True) -> list[dict[str, Any]]:
    client = docker_client()
    containers = await asyncio.to_thread(client.containers.list, all=True)
    if not include_stats:
        return [_container_summary(c) for c in containers]
    global _prev_cpu_at
    running = [c for c in containers if c.status == "running"]
    stopped = [_container_summary(c) for c in containers if c.status != "running"]
    loop = asyncio.get_running_loop()

    async def reading():
        return await asyncio.gather(*[loop.run_in_executor(_executor, _stats_for_container, c) for c in running])

    # Nothing recent to difference against (the first collection, or the first after nobody
    # watched): a share measured across the whole idle stretch would be an average of hours, shown
    # as "now". Two readings a second apart instead — once, then the collector's own cadence is the gap.
    if time.time() - _prev_cpu_at > 3 * REFRESH_INTERVAL_S:
        _prev_cpu.clear()
        await reading()
        await asyncio.sleep(1)
    stats_rows = await reading()
    _prev_cpu_at = time.time()
    for gone in set(_prev_cpu) - {c.id for c in running}:
        _prev_cpu.pop(gone, None)
    return sorted([*stats_rows, *stopped], key=lambda item: (item.get("status") != "running", item["name"]))


async def _build_overview() -> dict[str, Any]:
    os_release = _parse_os_release()
    containers = await _containers(include_stats=True)
    running = sum(1 for c in containers if c.get("status") == "running")
    unhealthy = sum(1 for c in containers if c.get("health") == "unhealthy")
    net_rx = sum((c.get("net") or {}).get("rx", 0) for c in containers)
    net_tx = sum((c.get("net") or {}).get("tx", 0) for c in containers)
    return {
        "generated_at": _iso_now(),
        "host": {
            "hostname": _hostname(),
            "os": os_release.get("PRETTY_NAME") or platform.platform(),
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "uptime_seconds": _uptime_seconds(),
        },
        "cpu": _cpu_info(),
        "memory": _mem_info(),
        "storage": _storage_overview(),
        "docker": {"containers_total": len(containers), "containers_running": running, "containers_unhealthy": unhealthy},
        "net": {"rx_total": net_rx, "tx_total": net_tx},
        "containers": containers,
        "cleanup_enabled": bool(CLEANUP_ALLOWED_ACTIONS),
        "cleanup_allowed_actions": sorted(CLEANUP_ALLOWED_ACTIONS),
    }


def _host_facts() -> dict[str, Any] | None:
    """The machine UNDER this one, as a host-side part of the office last wrote it — or None.

    Where the office runs in a VM (WSL, the macOS engine), everything this service measures is the
    VM's: on 2026-10-06 this screen read "memory 64%" while Windows had 275 MB free of 16 GB and
    WSL stopped answering for two minutes. The VM cannot see that; the host can, so the office's
    host-side pass writes it (`data/power/host.json` — on Windows the health task, every five
    minutes: `scripts/windows/platform-keepalive.ps1`). Older than fifteen minutes it is not a
    measurement any more, and nothing is shown rather than an old number.

    `short` is the state: less than 1 GiB free, or less than 8% — the margin under which the VM
    starts to be starved (the two minutes of silence came at 1.7%)."""
    doc = _power_read("host.json") or {}
    try:
        age = int(time.time() - float(doc["updated_at"]))
        total, free = int(doc["mem_total"]), int(doc["mem_free"])
    except (KeyError, TypeError, ValueError):
        return None
    if age > 900 or total <= 0:
        return None
    return {"os": str(doc.get("os") or ""), "mem_total": total, "mem_free": free, "age_s": max(0, age),
            "short": free < max(1 << 30, total * 0.08)}


#: the office's self-update state (scripts/follow.sh writes data/follow/state), read through the host root this app
#: already mounts read-only — never a bind of its own: docker would create a missing data/follow as root, and a follow
#: running as the office's user could then write no state at all (second reader)
FOLLOW_DIR = Path(os.getenv("FOLLOW_DIR") or (DEPLOYMENT_PATH / "data" / "follow"))
#: what of it an overview says: when, what came of it, why, the last take's merge once proven healthy, the target it
#: failed on, a take under way, and what that last take was of (its follow target, or the office's own branch)
FOLLOW_KEYS = {"LAST_AT": "at", "LAST_RESULT": "result", "LAST_DETAIL": "detail", "VERIFIED": "verified",
               "FAILED_TARGET": "failed_target", "FAILED_AT": "failed_at", "TAKING": "taking",
               "TAKING_WHAT": "last_take_of",
               # when it was last up to date (a take or a cycle that found it current): a follow that skips on load
               # every cycle has a fresh LAST_AT and no other sign — the Dell skipped all night (DGO-1838)
               "CURRENT_EPOCH": "current_epoch"}


def _follow_state() -> dict[str, Any] | None:
    """This office's follow — its last cycle (when, took / current / skipped / blocked / failed, the reason), the last
    take's merge once proven healthy, the target it failed on — or None where nothing follows here. Served in the overview, so a LINKED
    office reads why a machine did or did not take a green version: until now that was in a file only a shell on the
    machine could read (2026-11-11/12: the HP's and the Dell's takes could be explained only by a terminal on them —
    issues/an-offices-follow-result-can-be-read-only-by-a-shell-on-it-…, DGO-1848). Read fresh: a few lines."""
    try:
        text = (FOLLOW_DIR / "state").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    out: dict[str, Any] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in FOLLOW_KEYS:
            out[FOLLOW_KEYS[key]] = value.strip()[:400] or None
    return out or None


def _snapshot(cached: tuple[float, dict[str, Any]]) -> dict[str, Any]:
    """Return the cached overview with a freshness marker + the rolling history
    (no deep copy — the background loop replaces the tuple wholesale, never
    mutates in place; history is a separate ring buffer attached per request)."""
    snap = dict(cached[1])
    snap["cache_age_s"] = round(time.time() - cached[0], 1)
    # Under its OWN key. As `host` it replaced the overview's host block — this machine's name,
    # system, kernel, architecture and uptime — and the details card printed "undefined" three
    # times and "windows" for a Linux VM for half a day (2026-10-06).
    snap["vm_host"] = _host_facts()
    snap["follow"] = _follow_state()
    snap["history"] = list(_history)
    if _history:
        last = _history[-1]
        snap["net_rate"] = {"rx": last.get("rx", 0), "tx": last.get("tx", 0)}
    return snap


async def _full_build_once() -> None:
    """Do the expensive full collection (containers + per-container stats) and
    update the served cache + the shared host net RATE. Runs CONCURRENTLY so it
    never blocks the 10s host-sampling cadence."""
    global _overview_cache, _building, _net_rate, _prev_net
    try:
        result = await _build_overview()
        _overview_cache = (time.time(), result)
        net = result.get("net") or {}
        total = (net.get("rx_total", 0), net.get("tx_total", 0))
        now = time.time()
        if _prev_net is not None:
            pt, prx, ptx = _prev_net
            dt = max(now - pt, 1e-3)
            _net_rate = (max(0, round((total[0] - prx) / dt)),
                         max(0, round((total[1] - ptx) / dt)))
        _prev_net = (now, total[0], total[1])
    except Exception:
        pass  # keep the last good snapshot
    finally:
        _building = False


@app.get("/api/overview")
async def overview() -> dict[str, Any]:
    """Serve the cached snapshot instantly while the background collector keeps it warm — a
    request never blocks on a live collection then. It builds once, here, on the two occasions
    there is nothing warm to serve: the very first hit, and the first after an idle stretch."""
    global _overview_cache, _last_access
    _last_access = time.time()

    # Warm = the collector is still refreshing it (it does every REFRESH_INTERVAL_S while somebody
    # watches). A snapshot older than three of those is from before the collector went idle — a
    # cold start with old numbers in it: the screen opened on two-hour-old tiles under
    # "עודכן לפני 2 שע׳" and stayed so until the next poll (measured 2026-10-06, after an
    # afternoon nobody looked at the machine).
    def warm() -> bool:
        return _overview_cache is not None and time.time() - _overview_cache[0] < 3 * REFRESH_INTERVAL_S

    if warm():
        return _snapshot(_overview_cache)
    # cold start: build once under the lock so concurrent first-hits share it
    async with _overview_lock:
        if warm():
            return _snapshot(_overview_cache)
        result = await _build_overview()
        _overview_cache = (time.time(), result)
        return _snapshot(_overview_cache)


async def _refresh_loop() -> None:
    """Background collector — keeps `_overview_cache` warm off the request path.
    Wakes every REFRESH_INTERVAL_S and only does the expensive collection while
    the page is being watched (a request within ACTIVE_WINDOW_S) — when idle it
    just re-checks the timestamp and goes back to sleep (no docker calls at all),
    so it stays light yet becomes fresh within one interval once viewing resumes."""
    global _cpu_pct, _building
    while True:
        try:
            # 1) cheap host sample EVERY tick (proc reads only) → smooth 10s-resolution
            #    cpu/mem/disk history whether watched or idle. cpu sampled once here.
            _cpu_pct = _cpu_percent()
            _history.append({
                "t": round(time.time(), 1),
                "cpu": round(_cpu_pct or 0, 1),
                "mem": round(_mem_info()["percent"], 1),
                "disk": round(_disk_usage(HOST_ROOT)["percent"], 1),
                "running": _overview_cache[1]["docker"]["containers_running"] if _overview_cache else 0,
                "rx": _net_rate[0],
                "tx": _net_rate[1],
            })
            disk_watch()                    # DGO-70: a filling disk is SAID, not discovered
            # 2) full container build (cache + net) — only while watched (or cold),
            #    fired CONCURRENTLY so the expensive stats collection never stalls
            #    the sampling cadence above.
            watched = (time.time() - _last_access) < ACTIVE_WINDOW_S
            if (watched or _overview_cache is None) and not _building:
                _building = True
                asyncio.create_task(_full_build_once())
        except Exception:
            pass  # keep the last good snapshot; retry next tick
        await asyncio.sleep(REFRESH_INTERVAL_S)


@app.on_event("startup")
async def _start_collector() -> None:
    asyncio.create_task(_refresh_loop())


@app.post("/api/disk/probe")
async def disk_probe(payload: dict | None = None) -> dict[str, Any]:
    """Run the disk watch on a GIVEN reading — the proof, without filling a disk.

    `{"percent": 91, "free_gb": 12, "notify": "http://…"}`: the same `disk_alarm()` the loop calls,
    and (only when `notify` is given) the same POST — aimed wherever the caller says, so a proof run
    never writes into the owner's notice list. The real reading is in the answer either way.
    """
    body = payload or {}
    usage = _disk_usage(HOST_ROOT)
    percent = float(body.get("percent", usage["percent"]))
    free = int(float(body.get("free_gb", usage["free"] / (1 << 30))) * (1 << 30))
    alarm = disk_alarm(percent, free)
    posted = None
    target = str(body.get("notify") or "")
    if alarm and target:
        posted = _notify("POST", target.rstrip("/"), {"source": "machine", "source_id": alarm["id"],
                                                      "title": alarm["title"], "body": alarm["body"],
                                                      "level": alarm["level"], "link": "/#/m/machine"})
    return {"real": usage, "percent": percent, "alarm": alarm, "posted": posted,
            "warn_pct": DISK_WARN_PCT, "error_pct": DISK_ERROR_PCT}


@app.get("/api/storage")
def storage() -> dict[str, Any]:
    return _storage_overview()


@app.get("/api/cleanup/options")
def cleanup_options() -> dict[str, Any]:
    options = [
        {
            "id": "docker_container_prune",
            "title": "Prune stopped containers",
            "risk": "low",
            "description": "Remove containers that are already stopped. Running services are untouched.",
        },
        {
            "id": "docker_image_prune_dangling",
            "title": "Prune dangling images",
            "risk": "low",
            "description": "Remove untagged image layers left by rebuilds.",
        },
        {
            "id": "docker_builder_prune_all",
            "title": "Prune Docker build cache",
            "risk": "low",
            "description": "Remove rebuild cache. Future builds may take longer.",
        },
        {
            "id": "docker_image_prune_all",
            "title": "Prune inactive images",
            "risk": "medium",
            "description": "Remove images not used by any container. They can be pulled or rebuilt again.",
        },
    ]
    for option in options:
        option["enabled"] = option["id"] in CLEANUP_ALLOWED_ACTIONS
        if not option["enabled"]:
            option["disabled_reason"] = "Not in MACHINE_CLEANUP_ALLOWED_ACTIONS"
    return {
        "enabled": bool(CLEANUP_ALLOWED_ACTIONS),
        "allowed_actions": sorted(CLEANUP_ALLOWED_ACTIONS),
        "options": options,
    }


# A prune takes minutes on a full disk: the Dell's 22.7 GB of build cache (2026-11-11, DGO-1811) outlasted the
# Docker SDK's default 60 s read timeout, and the action answered 500 while the daemon finished the work. The
# cleanup calls get a client of their own, with a timeout a prune fits in, under the edge's own 600 s
# (traefik's respondingTimeouts): past it a caller through the edge gets nothing back whatever this says.
def _cleanup_timeout() -> int:
    try:
        value = int(os.getenv("MACHINE_CLEANUP_TIMEOUT_S") or "540")
    except ValueError:                       # a knob's typo never stops the app
        return 540
    return value if value > 0 else 540


CLEANUP_ACTIONS = {"docker_container_prune", "docker_image_prune_dangling", "docker_image_prune_all",
                   "docker_builder_prune_all"}


@app.post("/api/cleanup/{action_id}")
def run_cleanup(action_id: str) -> dict[str, Any]:
    if action_id not in CLEANUP_ALLOWED_ACTIONS:
        raise HTTPException(status_code=403, detail=f"Cleanup action is disabled. Add {action_id} to MACHINE_CLEANUP_ALLOWED_ACTIONS to enable it.")
    if action_id not in CLEANUP_ACTIONS:
        raise HTTPException(status_code=404, detail="Unknown cleanup action")
    timeout = _cleanup_timeout()
    client = docker.from_env(timeout=timeout)
    try:
        if action_id == "docker_container_prune":
            result = client.containers.prune()
        elif action_id == "docker_image_prune_dangling":
            result = client.images.prune(filters={"dangling": True})
        elif action_id == "docker_image_prune_all":
            result = client.images.prune(filters={"dangling": False})
        else:
            result = client.api.prune_builds(all=True)
    except requests.exceptions.ReadTimeout:
        # the daemon keeps going after the read gives up: say so, never «failed»
        raise HTTPException(status_code=504, detail=f"{action_id} did not answer in {timeout} s; the daemon may "
                            "still finish it — the storage card shows what it freed") from None
    finally:
        client.close()
    global _overview_cache, _storage_cache
    _overview_cache = None
    _storage_cache = None
    return {"action": action_id, "result": result, "generated_at": _iso_now()}


# ── Power: how the office behaves when the machine it runs on locks, sleeps or closes its lid ──────
# The office runs inside a VM on the owner's laptop, and a sleeping laptop freezes the VM and every
# agent in it (measured 2026-09-29: 28 of 43 agent-hours spent frozen). Whether to stay awake is a
# HOST decision, so a small agent on the host enforces it (packaging/macos/power-agent.py, started
# with the engine). This service only owns the two files the owner and that agent share:
#   policy.json — what the owner chose per situation (written here, read by the host agent)
#   status.json — what the host agent sees and did (written by it, read here)
# Both live in data/power/ of the checkout, which the host and this container both see.
POWER_DIR = Path(os.getenv("POWER_DIR", "/data/power"))
POWER_STALE_S = 90  # the host agent writes every ~15 s; older than this, it is not running
POWER_CHOICES = ("run", "sleep")
POWER_DEFAULTS: dict[str, Any] = {
    "version": 1,
    # "run": keep the machine awake so the office keeps working; "sleep": let it sleep as usual.
    "lock": {"ac": "run", "battery": "run"},   # screen locked, display off, nobody at the keyboard
    "lid": {"ac": "run", "battery": "run"},    # lid closed
    "battery_floor": 20,                       # on battery below this %, always let it sleep
    "thermal_guard": True,                     # under serious thermal pressure, let it sleep
}


def _power_read(name: str) -> dict[str, Any] | None:
    try:
        import json

        return json.loads((POWER_DIR / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _power_policy() -> dict[str, Any]:
    import copy

    policy = copy.deepcopy(POWER_DEFAULTS)
    stored = _power_read("policy.json") or {}
    for key in ("lock", "lid"):
        for src in ("ac", "battery"):
            value = (stored.get(key) or {}).get(src)
            if value in POWER_CHOICES:
                policy[key][src] = value
    floor = stored.get("battery_floor")
    if isinstance(floor, int) and 5 <= floor <= 90:
        policy["battery_floor"] = floor
    if isinstance(stored.get("thermal_guard"), bool):
        policy["thermal_guard"] = stored["thermal_guard"]
    return policy


# Is somebody at the desk (DGO-1797)? desk.py asks the desktop itself every DESK_TICK_S and writes
# data/power/desk.json, which the heavy-work admit reads and this screen shows. A reading older than
# DESK_STALE_S is «unknown» — and unknown is never «in use», so a dead sampler holds no job.
DESK_TICK_S = 10
DESK_STALE_S = 60
LOCKS_DIR = Path(os.getenv("LOCKS_DIR", "/data/locks"))   # the office's data/.locks, read-only (docker-compose.yml)
DESK_RETRY_S = 300   # a desk that answered «unknown» (no GNOME, a refusal) is asked again this often, not every tick


def _desk_loop() -> None:
    last: dict[str, Any] | None = None
    ask_at = 0.0
    while True:
        tick = time.monotonic()                  # the retry clock: a clock step on the host never delays it
        try:
            if last is None or last.get("in_use") is not None or tick >= ask_at:
                last = desk.read_desk(HOST_ROOT)
                ask_at = tick + (DESK_RETRY_S if last.get("in_use") is None else 0)
            desk.write_desk(POWER_DIR, {**last, "at": int(time.time())})
        except Exception:  # noqa: BLE001 — the sampler never stops the app
            pass
        time.sleep(DESK_TICK_S)


@app.on_event("startup")
async def _start_desk() -> None:
    threading.Thread(target=_desk_loop, name="desk", daemon=True).start()


def _desk_now() -> dict[str, Any] | None:
    reading = _power_read("desk.json")
    if not reading or not isinstance(reading.get("at"), (int, float)):
        return None
    age = max(0, int(time.time() - reading["at"]))
    if age > DESK_STALE_S:
        return {**reading, "in_use": None, "how": "unknown", "why": f"the reading is {age} s old", "age_s": age}
    return {**reading, "age_s": age}


@app.get("/api/power")
def power() -> dict[str, Any]:
    status = _power_read("status.json")
    agent = "absent"
    age = None
    if status and isinstance(status.get("updated_at"), (int, float)):
        age = max(0, int(time.time() - status["updated_at"]))
        agent = "running" if age <= POWER_STALE_S else "stale"
    # …and WHICH host this is, when its host-side pass says so: the agent that enforces the policy
    # exists for macOS; on a Windows host its absence is not a fault to start something about.
    return {"policy": _power_policy(), "defaults": POWER_DEFAULTS, "status": status,
            "agent": agent, "age_s": age, "host_os": (_host_facts() or {}).get("os") or "",
            "desk": _desk_now(), "heat": {"pkg_c": desk.pkg_temp_c(HOST_ROOT)},
            # a battery on the machine itself, and whether this is an engine's VM on a person's computer (desk): with no
            # agent and no host OS, no battery AND no engine VM is a server — the card's one line (DGO-1801)
            "battery": desk.has_battery(HOST_ROOT), "engine_vm": desk.engine_vm(HOST_ROOT),
            "heavy": desk.heavy_slot(LOCKS_DIR, HOST_ROOT / "proc" / "locks"), "generated_at": _iso_now()}


@app.put("/api/power/policy")
def set_power_policy(body: dict[str, Any]) -> dict[str, Any]:
    import json

    policy = _power_policy()
    for key in ("lock", "lid"):
        for src, value in (body.get(key) or {}).items():
            if src not in ("ac", "battery") or value not in POWER_CHOICES:
                raise HTTPException(status_code=400, detail=f"{key}.{src} must be one of {POWER_CHOICES}")
            policy[key][src] = value
    if "battery_floor" in body:
        floor = body["battery_floor"]
        if not isinstance(floor, int) or not 5 <= floor <= 90:
            raise HTTPException(status_code=400, detail="battery_floor must be an integer between 5 and 90")
        policy["battery_floor"] = floor
    if "thermal_guard" in body:
        if not isinstance(body["thermal_guard"], bool):
            raise HTTPException(status_code=400, detail="thermal_guard must be true or false")
        policy["thermal_guard"] = body["thermal_guard"]
    POWER_DIR.mkdir(parents=True, exist_ok=True)
    tmp = POWER_DIR / ".policy.json.tmp"
    tmp.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(POWER_DIR / "policy.json")   # atomic: the host agent never reads half a file
    return {"policy": policy, "saved_at": _iso_now()}
