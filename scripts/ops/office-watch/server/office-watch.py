#!/usr/bin/env python3
"""office-watch — severe office events to the office notice centre (AUD-C5-001331).

Run once a minute by office-watch.timer (low priority: nice 19, idle IO). Each run looks at:
  * CPU    — host busy % from /proc/stat deltas (and PSI cpu `some` avg60) at/over the limit for
             CPU_MIN minutes in a row (default 90 % for 5 min);
  * services — every container of the office's compose project (+ WATCH_EXTRA names) that is
             unhealthy / restarting / dead / exited non-zero on SERVICE_RUNS checks in a row;
  * disk   — each DISK_PATHS mount at/over DISK_PCT used or under DISK_FREE_GB free;
  * off-site backup — the newest line of X-17's offsite.log per profile failed, or no good copy
             for longer than that profile's OFFSITE_MAX_AGE_H;
  * stale mounts — an office container whose bind mount still points at a folder the server replaced
             (MOUNT_WATCH, the rendered .generated/ folders): it is RESTARTED, which binds the live folder,
             and told (FPG-497: the credential broker kept a deleted registry and refused every lease).
Each event is told ONCE when it opens (level error) and ONCE when it clears (level info,
«back to normal»), as one row per event in the notice centre — the same upsert-by-(source,
source_id) contract meet-start's say() and X-17's notify() use:
  POST http://notifications-<office>:8977/api/notifications
  {"source", "source_id", "title", "body", "level", "link", "meta"}  → 201 created | 200 updated
A post that fails is retried on the next run; nothing is told twice (state: told vs want).
Settings: /etc/default/office-watch (KEY=VALUE). Python 3 stdlib only.

  office-watch            one run (what the timer does)
  office-watch --check    look once (CPU sampled over 1 s), print, post nothing, write nothing
  office-watch --test     post ONE clearly-marked test row (opened, then closed); exit 1 if refused
"""
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULTS = {
    "OFFICE": "fireplace",
    "SOURCE": "office-watch",
    "NOTICE_URL": "",            # empty → http://<NOTICE_CONTAINER IP>:<NOTICE_PORT> (the X-17 way)
    "NOTICE_CONTAINER": "",      # empty → notifications-<OFFICE>
    "NOTICE_PORT": "8977",
    "LINK": "",
    "ALSO_POST_URLS": "",        # extra receivers of the same JSON (e.g. a future push endpoint)
    "TIMEOUT_S": "5",
    "CPU_PCT": "90",             # host busy % that counts as «at its limit»
    "CPU_MIN": "5",              # … for this many minutes in a row
    "CPU_CLEAR_MIN": "2",        # back under the limit this long → «back to normal»
    "PSI_PCT": "80",             # PSI cpu some avg60 that also counts (0 = off)
    "WATCH_PROJECT": "",         # empty → OFFICE (compose project label)
    "WATCH_EXTRA": "site-fireplace-guys site-fireplace-guys-forms",
    "IGNORE": "*-init-*",        # globs of container names never told about
    "SERVICE_RUNS": "2",         # checks in a row before a service is «down» (autoheal gets the first)
    "EXITED_ZERO_OK": "1",       # a container that exited 0 finished its job (one-shot init)
    "DISK_PATHS": "/",
    "DISK_PCT": "90",
    "DISK_FREE_GB": "5",
    "OFFSITE_LOG": "/var/backups/fpg-offsite/offsite.log",   # empty = off
    "OFFSITE_MAX_AGE_H": "core=26 full=194",
    "MOUNT_WATCH": "*/.generated/*",   # host folders whose replacement leaves a container blind (empty = off)
    "HEAL_STALE": "1",           # restart such a container (0 = only tell)
    "HEAL_MIN": "10",            # … at most once per container in this many minutes
    "HEAL_MAX": "2",             # … and at most this many restarts in one run (a run must end within 45 s)
    "HEAL_FIRST": "connections-*",   # globs restarted first: the credential broker every app leases from
    "STATE": "/var/lib/office-watch/state.json",
    "PROC_ROOT": "/proc",
    "DOCKER_CMD": "docker",
    "DISK_FAKE": "",             # tests only: JSON {path: [total, free, avail]} bytes
    "FAKE_NOW": "",              # tests only: epoch seconds
    "VERBOSE": "0",
}
CONF_FILE = os.environ.get("OFFICE_WATCH_CONF", "/etc/default/office-watch")


def load_conf():
    c = dict(DEFAULTS)
    try:
        with open(CONF_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                if k in c:
                    c[k] = v
    except OSError:
        pass
    for k in c:                                   # systemd EnvironmentFile / test env win
        if k in os.environ:
            c[k] = os.environ[k]
    return c


def num(c, k):
    try:
        return float(c[k])
    except (TypeError, ValueError):
        return float(DEFAULTS[k])


def now_ts(c):
    return float(c["FAKE_NOW"]) if c.get("FAKE_NOW") else time.time()


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M")


def dur(sec):
    m = int(round(sec / 60.0))
    return f"{m} min" if m < 120 else f"{m // 60} h {m % 60} min"


def log(*a):
    print("office-watch:", *a, flush=True)


# ── state ────────────────────────────────────────────────────────────────────────────────────
def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
        if isinstance(s, dict):
            return s
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        try:
            os.replace(path, path + ".bad")
        except OSError:
            pass
        log("state was unreadable; started fresh (kept as .bad)")
    return {}


def save_state(path, s):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


# ── the checks: each yields (key, bad, (open title, body), (close title, body), meta) ────────────
def cpu_sample(c):
    with open(os.path.join(c["PROC_ROOT"], "stat"), encoding="ascii") as f:
        parts = f.readline().split()
    v = [int(x) for x in parts[1:9]]              # user nice system idle iowait irq softirq steal
    total = sum(v)
    idle = v[3] + v[4]
    return total - idle, total


def psi_avg60(c):
    try:
        with open(os.path.join(c["PROC_ROOT"], "pressure", "cpu"), encoding="ascii") as f:
            for line in f:
                if line.startswith("some"):
                    m = re.search(r"avg60=([\d.]+)", line)
                    return float(m.group(1)) if m else None
    except OSError:
        return None
    return None


def ncpu(c):
    try:
        with open(os.path.join(c["PROC_ROOT"], "stat"), encoding="ascii") as f:
            return sum(1 for ln in f if re.match(r"cpu\d+ ", ln)) or 1
    except OSError:
        return 1


def check_cpu(c, st, now, check_only=False):
    cs = st.setdefault("cpu", {})
    busy, total = cpu_sample(c)
    if check_only:
        time.sleep(1)
        b2, t2 = cpu_sample(c)
        pct = 100.0 * (b2 - busy) / max(1, t2 - total)
        return [("cpu", pct >= num(c, "CPU_PCT"), (f"CPU {pct:.0f} % busy now", ""), None,
                 {"busy_pct_1s": round(pct, 1), "psi_avg60": psi_avg60(c), "cores": ncpu(c)})]
    prev = cs.get("prev")
    cs["prev"] = [busy, total, now]
    open_now = st.get("events", {}).get("cpu", {}).get("want") == "open"
    if not prev or total <= prev[1] or now - prev[2] > 900 or now <= prev[2]:
        return [("cpu", open_now, None, None, {})]         # no window yet: keep what we had
    pct = 100.0 * (busy - prev[0]) / (total - prev[1])
    psi = psi_avg60(c)
    hot = pct >= num(c, "CPU_PCT") or (num(c, "PSI_PCT") > 0 and psi is not None and psi >= num(c, "PSI_PCT"))
    start = prev[2]
    if hot:
        cs["hot_since"] = cs.get("hot_since") or start
        cs.pop("cool_since", None)
        cs["peak"] = max(cs.get("peak", 0), round(pct))
    else:
        cs.pop("hot_since", None)
        cs["cool_since"] = cs.get("cool_since") or start
    if open_now:
        bad = hot or now - cs["cool_since"] < num(c, "CPU_CLEAR_MIN") * 60
    else:
        bad = hot and now - cs["hot_since"] >= num(c, "CPU_MIN") * 60
    if bad and not cs.get("episode"):
        cs["episode"] = cs.get("hot_since") or start
    since = cs.get("episode") or cs.get("hot_since") or start
    lim = f"limit {c['CPU_PCT']} % for {c['CPU_MIN']} min"
    psi_s = f"; waiting for CPU {psi:.0f} %" if psi is not None else ""
    opened = (f"The office server is at its CPU limit ({pct:.0f} %)",
              f"The server has been {pct:.0f} % busy for {dur(now - since)} ({lim}; {ncpu(c)} cores{psi_s}). "
              "Screens and calls may be slow. It usually passes on its own; if it keeps on, the heaviest "
              "app should be paused.")
    closed = ("The office server's CPU is back to normal",
              f"{pct:.0f} % busy now. It was at its limit from {iso(since)} UTC for {dur(now - since)} "
              f"(peak {cs.get('peak', round(pct))} %).")
    if not bad and not hot:                       # episode over (or never began): forget it
        cs.pop("peak", None)
        cs.pop("episode", None)
    return [("cpu", bad, opened, closed, {"busy_pct": round(pct, 1), "psi_avg60": psi})]


def docker(c, *args, timeout=20):
    cmd = shlex.split(c["DOCKER_CMD"]) + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def check_services(c, st):
    project = c["WATCH_PROJECT"] or c["OFFICE"]
    extra = set(c["WATCH_EXTRA"].split())
    ignore = c["IGNORE"].split()
    try:
        r = docker(c, "ps", "-a", "--format",
                   '{{.Names}}\t{{.State}}\t{{.Status}}\t{{.Label "com.docker.compose.project"}}')
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"docker ps did not answer: {e}")
        return None
    if r.returncode != 0:
        log(f"docker ps failed: {r.stderr.strip()[:200]}")
        return None
    runs = st.setdefault("svc_bad", {})
    seen, out = set(), []
    for line in r.stdout.splitlines():
        p = line.split("\t")
        if len(p) < 3:
            continue
        name, state, status = p[0], p[1].lower(), p[2]
        proj = p[3] if len(p) > 3 else ""
        if proj != project and name not in extra:
            continue
        if any(fnmatch.fnmatch(name, g) for g in ignore):
            continue
        seen.add(name)
        m = re.match(r"Exited \((-?\d+)\)", status)
        code = int(m.group(1)) if m else None
        bad_now = ("(unhealthy)" in status or state in ("restarting", "dead")
                   or (state == "exited" and (code != 0 or c["EXITED_ZERO_OK"] != "1")))
        runs[name] = runs.get(name, 0) + 1 if bad_now else 0
        if not runs[name]:
            runs.pop(name)
        k = "svc-" + name
        was = st.get("events", {}).get(k, {})
        bad = runs.get(name, 0) >= num(c, "SERVICE_RUNS")
        since = was.get("since") or now_ts(c)
        out.append((k, bad,
                    (f"An office service is down: {name}",
                     f"{name} is «{status}» on {runs.get(name, 0)} checks in a row; autoheal did not bring it back. "
                     "The app it serves may not open."),
                    (f"{name} is back",
                     f"{name} is «{status}» again (it was down from {iso(since)} UTC)."),
                    {"container": name, "status": status}))
    for name in [n for n in runs if n not in seen]:
        runs.pop(name)
    for k, e in list(st.get("events", {}).items()):   # a container that vanished: its open row closes
        if k.startswith("svc-") and k[4:] not in seen and (e.get("told") != "closed" or e.get("want") != "closed"):
            out.append((k, False, None,
                        (f"{k[4:]} is no longer listed", f"{k[4:]} was removed or renamed; nothing is watched under that name now."),
                        {"container": k[4:]}))
    return out


def disk_usage(c, path):
    if c["DISK_FAKE"]:
        with open(c["DISK_FAKE"], encoding="utf-8") as f:
            total, free, avail = json.load(f)[path]
    else:
        s = os.statvfs(path)
        total, free, avail = s.f_blocks * s.f_frsize, s.f_bfree * s.f_frsize, s.f_bavail * s.f_frsize
    used = total - free
    pct = 100.0 * used / max(1, used + avail)      # what df's Capacity column shows
    return pct, avail / 1e9


def check_disk(c, st):
    out = []
    for path in c["DISK_PATHS"].split():
        try:
            pct, free_gb = disk_usage(c, path)
        except (OSError, KeyError, ValueError) as e:
            log(f"disk {path}: {e}")
            continue
        k = "disk-" + (path.strip("/").replace("/", "-") or "root")
        open_now = st.get("events", {}).get(k, {}).get("want") == "open"
        over = pct >= num(c, "DISK_PCT") or free_gb < num(c, "DISK_FREE_GB")
        clear = pct < num(c, "DISK_PCT") - 1 and free_gb >= num(c, "DISK_FREE_GB") + 0.5   # no flapping at the line
        bad = over or (open_now and not clear)
        out.append((k, bad,
                    (f"The server's disk is nearly full ({pct:.0f} % used)",
                     f"{path}: {pct:.0f} % used, {free_gb:.1f} GB free (limit {c['DISK_PCT']} % / {c['DISK_FREE_GB']} GB). "
                     "Recordings and backups may fail to save until old files are cleared."),
                    ("The server's disk has room again", f"{path}: {pct:.0f} % used, {free_gb:.1f} GB free."),
                    {"path": path, "used_pct": round(pct, 1), "free_gb": round(free_gb, 1)}))
    return out


LINE = re.compile(r"^(\S+) profile=(\S+) status=(\S+)(.*)$")


def parse_ts(s):
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:
        return None


def check_offsite(c, st, now):
    path = c["OFFSITE_LOG"]
    if not path:
        return []
    if not os.path.exists(path):
        return [("offsite-log", True,
                 ("The off-server backup log is missing", f"{path} does not exist; the off-server backup may not be installed or may have been removed."),
                 ("The off-server backup log is back", f"{path} exists again."), {"log": path})]
    lines = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            m = LINE.match(ln.strip())
            if m and parse_ts(m.group(1)) is not None:
                lines.append((parse_ts(m.group(1)), m.group(2), m.group(3), m.group(4)))
    first = min([x[0] for x in lines], default=os.path.getmtime(path))
    out = [("offsite-log", False, None, ("The off-server backup log is back", f"{path} exists again."), {"log": path})]
    for item in c["OFFSITE_MAX_AGE_H"].split():
        prof, _, h = item.partition("=")
        try:
            max_h = float(h)
        except ValueError:
            continue
        mine = [x for x in lines if x[1] == prof]
        oks = [x for x in mine if x[2] == "ok"]
        newest = mine[-1] if mine else None
        last_ok = oks[-1][0] if oks else None
        ref = last_ok if last_ok is not None else first
        failed = newest is not None and newest[2] != "ok"
        stale = now - ref > max_h * 3600
        k = "offsite-" + prof
        if failed:
            rc = re.search(r"rc=(\S+)", newest[3])
            opened = (f"The off-server backup ({prof}) failed",
                      f"The run at {iso(newest[0])} UTC failed (exit {rc.group(1) if rc else '?'}). "
                      + (f"The last good copy is from {iso(last_ok)} UTC." if last_ok else "There is no good copy yet."))
        else:
            opened = (f"No off-server backup ({prof}) for {int((now - ref) // 3600)} h",
                      (f"The last good copy is from {iso(last_ok)} UTC" if last_ok else "There has been no good copy yet")
                      + f" (expected at least every {h} h). The backup timer may be stopped.")
        mb = re.search(r"bytes=(\d+)", newest[3]) if newest else None
        closed = (f"The off-server backup ({prof}) works again",
                  f"Good copy at {iso(newest[0]) if newest else '?'} UTC" + (f", {int(mb.group(1)) // 1000000} MB." if mb else "."))
        out.append((k, failed or stale, opened, closed, {"profile": prof, "last_ok": last_ok}))
    return out


def stale_mounts(c, pid):
    """(mount point, host folder) of each bind mount of `pid` whose host folder was replaced while it ran — the
    kernel marks such a mount's root «…//deleted» in /proc/<pid>/mountinfo — limited to MOUNT_WATCH folders."""
    out = []
    try:
        with open(os.path.join(c["PROC_ROOT"], str(pid), "mountinfo"), encoding="utf-8", errors="replace") as f:
            for ln in f:
                p = ln.split()
                if len(p) > 4 and p[3].endswith("//deleted"):
                    root = p[3][:-len("//deleted")]
                    if any(fnmatch.fnmatch(root, g) for g in c["MOUNT_WATCH"].split()):
                        out.append((p[4], root))
    except OSError:
        pass
    return out


def check_mounts(c, st, now, check_only=False):
    """A running office container whose bind mount points at a folder the server replaced (FPG-497). It keeps the
    deleted folder — empty, or the old copy — and still looks healthy: on 2026-10-29 a hand-made «restore» deleted
    and re-extracted .generated/ at 08:45:54Z, the credential broker went on reading the deleted registry, and every
    app that (re)started after it was refused its connections. A restart binds the live folder, so the watch
    restarts it (HEAL_FIRST first, HEAL_MAX a run, once per HEAL_MIN per container) and tells it once."""
    if not c["MOUNT_WATCH"].split():
        return []
    project = c["WATCH_PROJECT"] or c["OFFICE"]
    try:
        r = docker(c, "ps", "-a", "--format",
                   '{{.Names}}\t{{.State}}\t{{.Status}}\t{{.Label "com.docker.compose.project"}}')
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"docker ps did not answer: {e}")
        return None
    if r.returncode != 0:
        return None
    names = []
    for line in r.stdout.splitlines():
        p = line.split("\t")
        if len(p) > 3 and p[3] == project and p[1].lower() == "running":
            names.append(p[0])
    pids = {}
    if names:
        try:
            r = docker(c, "inspect", "-f", "{{.Name}} {{.State.Pid}}", *names)
        except (OSError, subprocess.TimeoutExpired) as e:
            log(f"docker inspect did not answer: {e}")
            return None
        for ln in r.stdout.splitlines():
            p = ln.split()
            if len(p) == 2 and p[1].isdigit() and int(p[1]) > 0:
                pids[p[0].lstrip("/")] = int(p[1])
    heals = st.setdefault("mount_heal", {})
    first = c["HEAL_FIRST"].split()
    order = sorted(pids, key=lambda n: (not any(fnmatch.fnmatch(n, g) for g in first), n))
    out, stale, restarted = [], set(), 0
    for name in order:
        bad = stale_mounts(c, pids[name])
        if not bad:
            continue
        stale.add(name)
        where = ", ".join(f"{mp} (from {root})" for mp, root in bad[:3])
        note = ""
        if (not check_only and c["HEAL_STALE"] == "1" and restarted < num(c, "HEAL_MAX")
                and now - heals.get(name, 0) >= num(c, "HEAL_MIN") * 60):
            try:
                ok = docker(c, "restart", "--time", "10", name, timeout=30).returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                ok = False
            heals[name], restarted = now, restarted + 1
            log(f"{'restarted' if ok else 'could not restart'} {name}: its mount {where} pointed at a replaced folder")
            note = (f" The watch restarted it at {iso(now)} UTC, which binds the live folder." if ok else
                    f" The watch could not restart it at {iso(now)} UTC — restart it by hand: docker restart {name}.")
        out.append(("mount-" + name, True,
                    (f"{name} was reading a folder the server replaced",
                     f"{name} has {where} bound to a folder that was replaced while it ran, so it saw an empty or old "
                     f"copy while it looked healthy — apps that depend on it can fail to start.{note}"),
                    (f"{name} reads the live folder again", f"{name}'s mounts point at the live folders again."),
                    {"container": name, "mounts": [mp for mp, _ in bad]}))
    for k, e in list(st.get("events", {}).items()):     # a container that recovered (or is gone): its open row closes
        if k.startswith("mount-") and k[6:] not in stale and (e.get("told") != "closed" or e.get("want") != "closed"):
            out.append((k, False, None, (f"{k[6:]} reads the live folder again",
                                          f"{k[6:]}'s mounts point at the live folders again."), {"container": k[6:]}))
    for name in [n for n in heals if n not in pids and now - heals[n] > 86400]:
        heals.pop(name)
    return out


# ── telling the notice centre ───────────────────────────────────────────────────────────────
class Teller:
    def __init__(self, c):
        self.c, self.url, self.tried = c, None, False

    def base(self):
        if self.tried:
            return self.url
        self.tried = True
        if self.c["NOTICE_URL"]:
            self.url = self.c["NOTICE_URL"].rstrip("/")
            return self.url
        name = self.c["NOTICE_CONTAINER"] or "notifications-" + self.c["OFFICE"]
        try:
            r = docker(self.c, "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", name, timeout=10)
            ip = (r.stdout.split() or [""])[0] if r.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            ip = ""
        self.url = f"http://{ip}:{self.c['NOTICE_PORT']}" if ip else None
        if not self.url:
            log(f"the notice centre ({name}) has no address now; will retry next run")
        return self.url

    def post(self, key, level, title, body, meta):
        base = self.base()
        if not base:
            return False
        payload = json.dumps({"source": self.c["SOURCE"], "source_id": key, "title": title[:200], "body": body[:2000],
                              "level": level, "link": self.c["LINK"], "meta": meta}, ensure_ascii=False).encode("utf-8")
        ok = self._send(base + "/api/notifications", payload)
        if ok:
            for extra in self.c["ALSO_POST_URLS"].split():   # best effort, once per change like the main row
                self._send(extra, payload)
        return ok

    def _send(self, url, payload):
        req = urllib.request.Request(url, data=payload, method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=num(self.c, "TIMEOUT_S")) as r:
                r.read(200)
                return r.status in (200, 201)
        except (OSError, ValueError, urllib.error.HTTPError) as e:
            log(f"the notice centre did not take it ({url}): {e}")
            return False


def run(c, check_only=False):
    now = now_ts(c)
    st = {} if check_only else load_state(c["STATE"])
    ev = st.setdefault("events", {})
    found = []
    for name, fn in (("cpu", lambda: check_cpu(c, st, now, check_only)), ("services", lambda: check_services(c, st)),
                     ("disk", lambda: check_disk(c, st)), ("offsite", lambda: check_offsite(c, st, now)),
                     ("mounts", lambda: check_mounts(c, st, now, check_only))):
        try:
            got = fn()
        except Exception as e:                      # one broken check never silences the others
            log(f"{name} check failed: {type(e).__name__}: {e}")
            got = None
        if got is None and name in ("services", "mounts"):   # docker did not answer: keep what we had
            continue
        found.extend(got or [])
    if check_only:
        for k, bad, o, cl, meta in found:
            print(f"{'BAD' if bad else 'ok '} {k} {json.dumps(meta, ensure_ascii=False)}" + (f" — {o[0]}" if bad and o else ""))
        return 0
    teller, told = Teller(c), 0
    for k, bad, opened, closed, meta in found:
        e = ev.get(k) or {"told": "closed"}
        want = "open" if bad else "closed"
        if want == "open" and e.get("want") != "open":
            e["since"] = now
        e["want"] = want
        if opened:
            e["open_text"] = list(opened)
        if want != e.get("told"):
            title, body = (opened or e.get("open_text") or ("", "")) if want == "open" else (closed or ("", ""))
            if not title:
                e["told"] = want                    # nothing sensible to say (no window yet)
            elif teller.post(k, "error" if want == "open" else "info", title, body,
                             dict(meta, event=k, state=want, since=iso(e.get("since", now)))):
                e["told"], e["told_at"] = want, now
                e.pop("tries", None)
                told += 1
                log(f"told {k}: {want} — {title}")
            else:
                e["tries"] = e.get("tries", 0) + 1
        ev[k] = e
    for k in list(ev):                               # forget closed rows that are no longer observed
        if ev[k].get("told") == "closed" and ev[k].get("want") == "closed" and k not in {f[0] for f in found}:
            ev.pop(k)
    st["last_run"] = now
    save_state(c["STATE"], st)
    if c["VERBOSE"] == "1":
        log(f"run done: {len(found)} checks, {told} told")
    return 0


def test_event(c):
    key = "deploy-test-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    t = Teller(c)
    a = t.post(key, "warning", "TEST — the office watch is installed (nothing is wrong)",
               "A one-off test from the office watch's install. It watches the CPU, every office service, "
               "the disk and the off-server backup, and tells each problem here once.", {"test": True})
    b = a and t.post(key, "info", "TEST — the office watch works (test finished)",
                     "This row was the install test; it needs no action.", {"test": True})
    print(f"office-watch: test row {key}: opened={'yes' if a else 'NO'} closed={'yes' if b else 'NO'}", flush=True)
    return 0 if (a and b) else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    c = load_conf()
    if "--test" in argv:
        return test_event(c)
    return run(c, check_only="--check" in argv)


if __name__ == "__main__":
    sys.exit(main())
