"""hostinfo — the machine itself: processor, memory, disk, containers and their use. This is the collector
the `machine` app had, moved here so that one base app observes the machine and Computers shows it
(the owner, 2026-10-21: "machine app and computers app should merge").

Same answer as machine's `/api/overview` (the shape Computers draws), from narrower mounts: the host's
/proc is the kernel's and needs no mount; the disk is the partition the office's data lives on (this
app's own volume), and the operating system's name is one file (`/etc/os-release`, read-only) — not
the whole host filesystem machine mounted (issues/sec-the-machine-app-mounts-the-whole-host-filesystem).
"""
from __future__ import annotations

import json
import os
import platform
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from dockerapi import Docker, DockerError

HISTORY = 180          # points; × the tick (10 s) = 30 minutes


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


class HostInfo:
    def __init__(self, docker: Docker, data_dir: str, sensor_dir: str, os_release: str = "/host/os-release"):
        self.docker = docker
        self.data_dir = data_dir
        self.sensor_dir = sensor_dir
        self.os_release = os_release
        self.history: deque = deque(maxlen=HISTORY)
        self.lock = threading.Lock()
        self._cpu_prev = None
        self._cpu_pct = None
        self._net_prev = None
        self._net_rate = {"rx": 0, "tx": 0}
        self._ctr_prev: dict = {}
        self._ctr_cache = (0.0, [])
        self._df_cache = (0.0, None)
        self._pool = ThreadPoolExecutor(max_workers=6)

    # ── the kernel's counters ────────────────────────────────────────────────────────────────────
    def _cpu_times(self):
        line = _read("/proc/stat").splitlines()[:1]
        if not line:
            return None
        vals = [int(v) for v in line[0].split()[1:]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        return idle, sum(vals)

    def _cpu_percent(self):
        cur = self._cpu_times()
        if not cur:
            return None
        prev, self._cpu_prev = self._cpu_prev, cur
        if not prev:
            return None
        di, dt = cur[0] - prev[0], cur[1] - prev[1]
        return round(max(0.0, (1 - di / dt) * 100), 1) if dt > 0 else None

    @staticmethod
    def memory() -> dict:
        info = {}
        for line in _read("/proc/meminfo").splitlines():
            k, _, v = line.partition(":")
            try:
                info[k] = int(v.strip().split()[0]) * 1024
            except (ValueError, IndexError):
                pass
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", info.get("MemFree", 0))
        used = max(0, total - avail)
        return {"total": total, "available": avail, "used": used,
                "percent": round(used / total * 100, 1) if total else 0,
                "swap_total": info.get("SwapTotal", 0), "swap_used": max(0, info.get("SwapTotal", 0) - info.get("SwapFree", 0))}

    def cpu(self) -> dict:
        model, cores = "", 0
        for line in _read("/proc/cpuinfo").splitlines():
            if line.startswith(("model name", "Model", "Hardware")) and not model:
                model = line.split(":", 1)[-1].strip()
            if line.startswith("processor"):
                cores += 1
        load = (_read("/proc/loadavg").split() + ["0", "0", "0"])[:3]
        return {"model": model or platform.machine(), "cores": cores or os.cpu_count() or 1,
                "load1": float(load[0]), "load5": float(load[1]), "load15": float(load[2]), "percent": self._cpu_pct}

    def disk(self) -> dict:
        try:
            st = os.statvfs(self.data_dir)
        except OSError:
            return {}
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        used = total - st.f_bfree * st.f_frsize
        return {"path": "data", "total": total, "used": used, "free": free,
                "percent": round(used / total * 100, 1) if total else 0}

    def _netdev(self):
        try:
            with open(os.path.join(self.sensor_dir, "netdev.json"), encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            return None
        rx = sum(v.get("rx", 0) for k, v in (d.get("ifaces") or {}).items() if not k.startswith(("lo", "veth", "br-", "docker")))
        tx = sum(v.get("tx", 0) for k, v in (d.get("ifaces") or {}).items() if not k.startswith(("lo", "veth", "br-", "docker")))
        return d.get("at") or time.time(), rx, tx

    # ── the collector's tick ─────────────────────────────────────────────────────────────────────
    def tick(self) -> None:
        self._cpu_pct = self._cpu_percent()
        net = self._netdev()
        if net and self._net_prev and net[0] > self._net_prev[0]:
            dt = net[0] - self._net_prev[0]
            self._net_rate = {"rx": max(0, int((net[1] - self._net_prev[1]) / dt)), "tx": max(0, int((net[2] - self._net_prev[2]) / dt))}
        if net:
            self._net_prev = net
        try:
            running = len(self.docker.containers())
        except DockerError:
            running = None
        mem = self.memory()
        d = self.disk()
        with self.lock:
            self.history.append({"t": int(time.time() * 1000), "cpu": self._cpu_pct, "mem": mem["percent"],
                                 "disk": d.get("percent"), "running": running,
                                 "rx": self._net_rate["rx"], "tx": self._net_rate["tx"]})

    # ── containers (only while somebody looks) ───────────────────────────────────────────────────
    def _one(self, c: dict) -> dict:
        labels = c.get("Labels") or {}
        row = {"id": (c.get("Id") or "")[:12], "name": labels.get("com.docker.compose.service") or (c.get("Names") or ["?"])[0].lstrip("/"),
               "raw_name": (c.get("Names") or ["?"])[0].lstrip("/"), "image": c.get("Image", ""),
               "status": c.get("State", ""), "health": "", "started_at": None, "restart_count": 0,
               "cpu_percent": 0, "memory": {"used": 0, "limit": 0, "percent": 0}, "pids": 0, "net": {"rx": 0, "tx": 0}}
        st = (c.get("Status") or "").lower()
        row["health"] = "unhealthy" if "unhealthy" in st else ("healthy" if "healthy" in st else ("starting" if "starting" in st else ""))
        if c.get("State") != "running":
            return row
        try:
            s = self.docker.stats(c["Id"])
        except DockerError as e:
            row["stats_error"] = str(e)[:120]
            return row
        cpu = s.get("cpu_stats") or {}
        now = ((cpu.get("cpu_usage") or {}).get("total_usage", 0), cpu.get("system_cpu_usage", 0))
        was = self._ctr_prev.get(c["Id"])
        self._ctr_prev[c["Id"]] = now
        online = cpu.get("online_cpus") or 1
        if was and now[1] > was[1] and now[0] >= was[0]:
            row["cpu_percent"] = round((now[0] - was[0]) / (now[1] - was[1]) * online * 100, 2)
        mem = s.get("memory_stats") or {}
        usage = int(mem.get("usage", 0))
        cache = int((mem.get("stats") or {}).get("inactive_file", (mem.get("stats") or {}).get("cache", 0)))
        limit = int(mem.get("limit", 0))
        used = max(usage - cache, 0)
        row["memory"] = {"used": used, "limit": limit, "percent": round(used / limit * 100, 1) if limit else 0}
        row["pids"] = (s.get("pids_stats") or {}).get("current", 0)
        nets = s.get("networks") or {}
        row["net"] = {"rx": sum(int(n.get("rx_bytes", 0)) for n in nets.values()),
                      "tx": sum(int(n.get("tx_bytes", 0)) for n in nets.values())}
        return row

    def containers(self) -> list:
        at, rows = self._ctr_cache
        if time.time() - at < 8:
            return rows
        try:
            cs = self.docker.containers(all_=True)
        except DockerError:
            return rows
        rows = list(self._pool.map(self._one, cs))
        rows.sort(key=lambda r: (r["status"] != "running", r["name"]))
        self._ctr_cache = (time.time(), rows)
        return rows

    def docker_df(self):
        at, df = self._df_cache
        if df is not None and time.time() - at < 600:
            return df
        try:
            raw = self.docker.system_df()
            # machine's shape — the engine's own lists — with only the fields a screen reads: the resource
            # view in computers draws this answer and machine's with one piece of code, and it broke on
            # the totals this used to return (2026-10-21)
            df = {"Images": [{"Size": i.get("Size", 0), "Containers": i.get("Containers", 0)} for i in raw.get("Images") or []],
                  "Containers": [{"SizeRw": c.get("SizeRw", 0) or 0} for c in raw.get("Containers") or []],
                  "Volumes": [{"UsageData": {"Size": max(0, (v.get("UsageData") or {}).get("Size") or 0)}}
                              for v in raw.get("Volumes") or []],
                  "BuildCache": [{"Size": b.get("Size", 0)} for b in raw.get("BuildCache") or []]}
        except DockerError as e:
            df = {"error": str(e)[:160]}
        self._df_cache = (time.time(), df)
        return df

    def os_name(self) -> str:
        for line in _read(self.os_release).splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
        return platform.platform()

    def overview(self, hostname: str = "", with_containers: bool = True) -> dict:
        ctrs = self.containers() if with_containers else []
        uptime = (_read("/proc/uptime").split() + ["0"])[0]
        with self.lock:
            hist = list(self.history)
        return {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "host": {"hostname": hostname or platform.node(), "os": self.os_name(), "kernel": platform.release(),
                     "architecture": platform.machine(), "uptime_seconds": int(float(uptime or 0))},
            "cpu": self.cpu(),
            "memory": self.memory(),
            "storage": {"root": self.disk(), "top_paths": [], "docker_df": self.docker_df() if with_containers else None},
            "docker": {"containers_total": len(ctrs), "containers_running": sum(1 for c in ctrs if c["status"] == "running"),
                       "containers_unhealthy": sum(1 for c in ctrs if c["health"] == "unhealthy")},
            "net": {"rx_total": sum(c["net"]["rx"] for c in ctrs), "tx_total": sum(c["net"]["tx"] for c in ctrs)},
            "containers": ctrs,
            "history": hist,
            "net_rate": dict(self._net_rate),
        }
