"""Local tests for office-watch with fakes: /proc, docker, disk, offsite.log, a clock and a fake notice centre.

Run:  python test/test_office_watch.py      (prints PASS/FAIL per check and a total; exit 1 on any FAIL)
"""
import importlib.util
import json
import os
import shlex
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "server", "office-watch.py")
spec = importlib.util.spec_from_file_location("office_watch", SRC)
ow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ow)

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""), flush=True)


# ── the fake notice centre: the live contract (upsert by source+source_id, 201 new / 200 updated) ──
class Centre:
    down = False
    rows = {}          # (source, source_id) -> row
    accepted = []      # every accepted POST body
    attempts = 0


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        Centre.attempts += 1
        n = int(self.headers.get("Content-Length") or 0)
        b = json.loads(self.rfile.read(n) or b"{}")
        if Centre.down:
            self.send_response(503); self.end_headers(); self.wfile.write(b'{"error":"down"}'); return
        if self.path != "/api/notifications" or not b.get("source") or not b.get("title"):
            self.send_response(400); self.end_headers(); return
        k = (b["source"], b.get("source_id"))
        created = k not in Centre.rows
        Centre.rows[k] = dict(b)
        Centre.accepted.append(b)
        self.send_response(201 if created else 200)
        self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps({"id": len(Centre.rows), "created": created}).encode())


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]


class World:
    """One fake server: counters, files and the clock, rebuilt per scenario."""

    def __init__(self):
        self.d = tempfile.mkdtemp(prefix="ow-")
        os.makedirs(os.path.join(self.d, "proc", "pressure"))
        self.now = ow.parse_ts("2026-01-15T05:00:00+00:00")
        self.busy, self.total = 1_000_000, 4_000_000
        self.containers = [["console-fireplace", "running", "Up 3 hours (healthy)", "fireplace"],
                           ["fireplace-mailserver-init-1", "exited", "Exited (0) 30 hours ago", "fireplace"],
                           ["meet-test", "exited", "Exited (137) 2 days ago", ""],
                           ["site-fireplace-guys", "running", "Up 3 hours", ""]]
        self.docker = {"ps": self.containers, "fail": False, "ip": ""}
        self.disk = {"/": [100e9, 55e9, 50e9]}
        self.psi = 20.0
        self.offsite = os.path.join(self.d, "offsite.log")
        self.write_offsite(["2026-01-15T04:41:43+00:00 profile=core status=ok file=x.tar.gpg bytes=258817629 warnings=0"])
        env = {"OFFICE_WATCH_CONF": os.path.join(self.d, "none.conf"),
               "PROC_ROOT": os.path.join(self.d, "proc"),
               "DOCKER_CMD": " ".join(shlex.quote(p.replace("\\", "/")) for p in (sys.executable, os.path.join(HERE, "fake_docker.py"))),
               "FAKE_DOCKER_STATE": os.path.join(self.d, "docker.json"),
               "DISK_FAKE": os.path.join(self.d, "disk.json"),
               "OFFSITE_LOG": self.offsite,
               "STATE": os.path.join(self.d, "state", "state.json"),
               "NOTICE_URL": f"http://127.0.0.1:{PORT}",
               "NOTICE_PORT": str(PORT),
               "OFFSITE_MAX_AGE_H": "core=26 full=194"}
        for k in list(os.environ):
            if k in ow.DEFAULTS:
                del os.environ[k]
        os.environ.update(env)
        Centre.down, Centre.rows, Centre.accepted, Centre.attempts = False, {}, [], 0
        self.flush(cpu_pct=None)

    def write_offsite(self, lines):
        with open(self.offsite, "w", encoding="utf-8") as f:
            f.write("".join(x + "\n" for x in lines))

    def flush(self, cpu_pct=30.0):
        if cpu_pct is not None:                       # one minute of 2 cores at 100 Hz
            step = 12_000
            self.total += step
            self.busy += int(step * cpu_pct / 100)
        idle = self.total - self.busy
        with open(os.path.join(self.d, "proc", "stat"), "w") as f:
            f.write(f"cpu  {self.busy} 0 0 {idle} 0 0 0 0 0 0\ncpu0 1 0 0 1 0 0 0 0 0 0\ncpu1 1 0 0 1 0 0 0 0 0 0\n")
        with open(os.path.join(self.d, "proc", "pressure", "cpu"), "w") as f:
            f.write(f"some avg10={self.psi:.2f} avg60={self.psi:.2f} avg300={self.psi:.2f} total=1\n"
                    "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n")
        with open(os.path.join(self.d, "docker.json"), "w") as f:
            json.dump(self.docker, f)
        with open(os.path.join(self.d, "disk.json"), "w") as f:
            json.dump(self.disk, f)

    def tick(self, cpu_pct=30.0, minutes=1, argv=()):
        self.now += 60 * minutes
        os.environ["FAKE_NOW"] = str(self.now)
        self.flush(cpu_pct)
        return ow.main(list(argv))


def posts(key):
    return [b for b in Centre.accepted if b.get("source_id") == key]


# ── 1. CPU: 95 % for 4 min → nothing; 5 min → one; still high → no duplicate; normal → one recovery ──
w = World()
w.tick(30)                                             # first sample: no window yet
for _ in range(4):
    w.tick(95)
check("cpu: 95 % for 4 min tells nothing", len(posts("cpu")) == 0, posts("cpu"))
w.tick(95)
p = posts("cpu")
check("cpu: 95 % for 5 min tells exactly one notice", len(p) == 1, p)
check("cpu: the notice is level error, source office-watch", p and p[0]["level"] == "error" and p[0]["source"] == "office-watch")
check("cpu: the notice has every field of the live contract",
      p and set(p[0]) == {"source", "source_id", "title", "body", "level", "link", "meta"})
check("cpu: the title says the limit and the %", p and "CPU limit" in p[0]["title"] and "95 %" in p[0]["title"], p and p[0]["title"])
for _ in range(3):
    w.tick(97)
check("cpu: still high for 3 more min → no duplicate", len(posts("cpu")) == 1)
w.tick(20)
check("cpu: 1 min back under the limit → not yet «back to normal»", len(posts("cpu")) == 1)
w.tick(20)
p = posts("cpu")
check("cpu: 2 min under the limit → exactly one recovery", len(p) == 2 and p[1]["level"] == "info", p[-1:])
check("cpu: the recovery says back to normal + peak", "back to normal" in p[-1]["title"] and "peak 97 %" in p[-1]["body"], p[-1]["body"])
for _ in range(3):
    w.tick(20)
check("cpu: calm after recovery → nothing more", len(posts("cpu")) == 2)
check("cpu: one row in the centre for the whole story (upsert)", len([k for k in Centre.rows if k[1] == "cpu"]) == 1)
w.tick(95); w.tick(95); w.tick(30); w.tick(95); w.tick(95); w.tick(95); w.tick(95)
check("cpu: hot spells broken by a calm minute never add up to 5 min", len(posts("cpu")) == 2)
w.psi = 85.0
for _ in range(5):
    w.tick(60)
check("cpu: PSI some avg60 ≥ 80 % for 5 min also tells (busy only 60 %)", len(posts("cpu")) == 3, posts("cpu")[-1:])

# ── 2. services: unhealthy 1 run → nothing; 2 runs → one; recovered → one recovery ──
w = World()
w.tick()
w.containers[0][2] = "Up 3 hours (unhealthy)"
w.tick()
check("service: unhealthy on 1 check tells nothing (autoheal's minute)", len(posts("svc-console-fireplace")) == 0)
w.tick()
p = posts("svc-console-fireplace")
check("service: unhealthy on 2 checks tells exactly one", len(p) == 1 and p[0]["level"] == "error", p)
check("service: the notice names the service", p and "console-fireplace" in p[0]["title"])
w.tick(); w.tick()
check("service: still unhealthy → no duplicate", len(posts("svc-console-fireplace")) == 1)
w.containers[0][2] = "Up 4 hours (healthy)"
w.tick()
p = posts("svc-console-fireplace")
check("service: healthy again → exactly one recovery", len(p) == 2 and p[1]["level"] == "info" and "is back" in p[1]["title"], p[-1:])
check("service: an init container that exited 0 is never told", len(posts("svc-fireplace-mailserver-init-1")) == 0)
check("service: a container outside the office project is never told", len(posts("svc-meet-test")) == 0)
w.containers[3][1:3] = ["exited", "Exited (137) 1 minute ago"]
w.tick(); w.tick()
check("service: a WATCH_EXTRA site container exited 137 is told once", len(posts("svc-site-fireplace-guys")) == 1)
w.containers[0][1:3] = ["restarting", "Restarting (1) 5 seconds ago"]
w.tick(); w.tick()
check("service: restarting on 2 checks is told", len(posts("svc-console-fireplace")) == 3)
w.docker["fail"] = True
w.tick(); w.tick()
check("service: docker not answering → no false recovery, no crash", len(posts("svc-console-fireplace")) == 3)
w.docker["fail"] = False
del w.containers[3]
w.tick()
p = posts("svc-site-fireplace-guys")
check("service: a told container that vanished closes once", len(p) == 2 and p[1]["level"] == "info", p[-1:])
w.tick()
check("service: …and is not told again", len(posts("svc-site-fireplace-guys")) == 2)

# ── 3. disk ──
w = World()
w.disk["/"] = [100e9, 9e9, 8.5e9]                       # 91.5 % used
w.tick()
p = posts("disk-root")
check("disk: over 90 % tells one notice", len(p) == 1 and p[0]["level"] == "error", p)
w.tick()
check("disk: still over → no duplicate", len(posts("disk-root")) == 1)
w.disk["/"] = [100e9, 10.6e9, 10.1e9]                   # ~89.5 % — inside the 1-point band
w.tick()
check("disk: just under the line → no flapping recovery", len(posts("disk-root")) == 1)
w.disk["/"] = [100e9, 20e9, 19e9]
w.tick()
p = posts("disk-root")
check("disk: back under → exactly one recovery", len(p) == 2 and p[1]["level"] == "info", p[-1:])
w.disk["/"] = [100e9, 40e9, 4e9]                        # few GB free though % is fine
w.tick()
check("disk: under DISK_FREE_GB free also tells", len(posts("disk-root")) == 3)

# ── 4. off-site backup ──
w = World()
w.now = ow.parse_ts("2026-01-15T05:00:00+00:00")
w.tick()
check("offsite: a fresh good copy tells nothing", len(posts("offsite-core")) == 0)
w.write_offsite(["2026-01-15T04:41:43+00:00 profile=core status=ok file=x.tar.gpg bytes=258817629 warnings=0",
                 "2026-01-16T03:52:00+00:00 profile=core status=failed rc=3"])
w.now = ow.parse_ts("2026-01-16T03:52:00+00:00")       # the clock follows the log (23 h after the good copy)
w.tick()
p = posts("offsite-core")
check("offsite: a failed line tells one notice", len(p) == 1 and p[0]["level"] == "error" and "failed" in p[0]["title"], p)
check("offsite: the notice gives the exit code and the last good copy", p and "exit 3" in p[0]["body"] and "2026-01-15 04:41" in p[0]["body"], p and p[0]["body"])
w.tick()
check("offsite: no duplicate", len(posts("offsite-core")) == 1)
with open(w.offsite, "a", encoding="utf-8") as f:
    f.write("2026-01-16T04:10:00+00:00 profile=core status=ok file=y.tar.gpg bytes=260000000 warnings=0\n")
w.now = ow.parse_ts("2026-01-16T04:10:00+00:00")
w.tick()
p = posts("offsite-core")
check("offsite: a good copy again → one recovery", len(p) == 2 and p[1]["level"] == "info" and "works again" in p[1]["title"], p[-1:])
check("offsite: no full profile line yet and the log is young → nothing about full", len(posts("offsite-full")) == 0)
w.tick(minutes=27 * 60)
p = posts("offsite-core")
check("offsite: no good copy for 27 h → one stale notice", len(p) == 3 and "No off-server backup (core)" in p[2]["title"], p[-1:])
w.tick(minutes=8 * 24 * 60)
check("offsite: the full profile overdue (> 194 h since the log began) tells once", len(posts("offsite-full")) == 1)
os.remove(w.offsite)
w.tick()
check("offsite: the log removed → one «log is missing»", len(posts("offsite-log")) == 1)

# ── 5. the notice centre down: no state advance, told next run, never twice ──
w = World()
Centre.down = True
w.disk["/"] = [100e9, 5e9, 4.5e9]
w.tick(); w.tick()
check("down: posts were tried while the centre was down", Centre.attempts >= 2)
check("down: nothing counted as told", len(posts("disk-root")) == 0)
with open(os.environ["STATE"], encoding="utf-8") as f:
    told = json.load(f)["events"]["disk-root"]["told"]
check("down: the state still says not told (want open)", told == "closed")
Centre.down = False
w.tick()
check("down: told on the first run after it is back", len(posts("disk-root")) == 1)
w.tick(); w.tick()
check("down: …and never twice", len(posts("disk-root")) == 1)

# ── 6. the address found the X-17 way (docker inspect of notifications-<office>) ──
w = World()
os.environ["NOTICE_URL"] = ""
w.docker["ip"] = "127.0.0.1"
w.disk["/"] = [100e9, 5e9, 4.5e9]
w.tick()
check("address: resolved via docker inspect → told", len(posts("disk-root")) == 1)
w = World()
os.environ["NOTICE_URL"] = ""
w.docker["ip"] = ""
w.disk["/"] = [100e9, 5e9, 4.5e9]
w.tick()
check("address: no address → nothing told, no crash", len(posts("disk-root")) == 0)
w.docker["ip"] = "127.0.0.1"
w.tick()
check("address: told once it has an address", len(posts("disk-root")) == 1)

# ── 7. --test, --check, a broken state file ──
w = World()
rc = w.tick(argv=["--test"])
tp = [b for b in Centre.accepted if b["source_id"].startswith("deploy-test-")]
check("--test: one row, opened (warning) then closed (info), exit 0",
      rc == 0 and len(tp) == 2 and tp[0]["level"] == "warning" and tp[1]["level"] == "info"
      and tp[0]["source_id"] == tp[1]["source_id"] and "TEST" in tp[0]["title"], tp)
check("--test: the open and close are ONE row in the centre", len([k for k in Centre.rows if k[1].startswith("deploy-test-")]) == 1)
Centre.down = True
rc = w.tick(argv=["--test"])
check("--test: exit 1 when the centre refuses", rc == 1)
Centre.down = False
w = World()
w.disk["/"] = [100e9, 5e9, 4.5e9]
before = len(Centre.accepted)
rc = w.tick(argv=["--check"])
check("--check: posts nothing and writes no state", rc == 0 and len(Centre.accepted) == before and not os.path.exists(os.environ["STATE"]))
w = World()
os.makedirs(os.path.dirname(os.environ["STATE"]), exist_ok=True)
with open(os.environ["STATE"], "w") as f:
    f.write("{not json")
rc = w.tick()
check("state: a broken state file → fresh start, kept as .bad", rc == 0 and os.path.exists(os.environ["STATE"] + ".bad"))
w = World()
os.environ["OFFSITE_LOG"] = ""
os.environ["DISK_FAKE"] = os.path.join(w.d, "missing.json")
w.containers[0][2] = "Up (unhealthy)"
w.tick(); w.tick()
check("isolation: a broken disk check never silences the service check", len(posts("svc-console-fireplace")) == 1)


# ── 6. stale mounts (FPG-497): a container reading a replaced .generated folder is restarted and told once ──
def mountinfo(w, pid, lines):
    d = os.path.join(w.d, "proc", str(pid))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "mountinfo"), "w") as f:
        f.write("".join(x + "\n" for x in lines))


def restarted(w):
    with open(os.path.join(w.d, "docker.json")) as f:
        return json.load(f).get("restarted", [])


OK_LINE = "100 90 8:1 / / rw,relatime - ext4 /dev/sda1 rw"
STALE = "512 500 8:1 /opt/digital-office/fireplace/.generated/registry//deleted /app/generated ro,relatime - ext4 /dev/sda1 rw"
FILE_STALE = "513 500 8:1 /opt/digital-office/fireplace/apps/browser42/handoff.py//deleted /handoff.py ro,relatime - ext4 /dev/sda1 rw"
w = World()
w.containers[:] = [["console-fireplace", "running", "Up 3 hours (healthy)", "fireplace"],
                   ["connections-fireplace", "running", "Up 9 hours (healthy)", "fireplace"],
                   ["meet-test", "running", "Up 2 days", ""]]
w.docker["pids"] = {"console-fireplace": 4101, "connections-fireplace": 4202, "meet-test": 4303}
for pid in (4101, 4202, 4303):
    mountinfo(w, pid, [OK_LINE])
w.tick()
check("mounts: live folders → nothing told, nothing restarted", len(posts("mount-connections-fireplace")) == 0 and restarted(w) == [])
mountinfo(w, 4202, [OK_LINE, STALE])
mountinfo(w, 4303, [OK_LINE, STALE])
w.tick()
p = posts("mount-connections-fireplace")
check("mounts: a replaced .generated folder → the container is restarted", restarted(w) == ["connections-fireplace"], restarted(w))
check("mounts: …and told once, level error, naming the mount and the restart",
      len(p) == 1 and p[0]["level"] == "error" and "/app/generated" in p[0]["body"] and "restarted it" in p[0]["body"], p)
check("mounts: a container outside the office is left alone", "meet-test" not in restarted(w) and len(posts("mount-meet-test")) == 0)
w.tick()
check("mounts: still stale a minute later → no second restart within HEAL_MIN", restarted(w) == [], restarted(w))
check("mounts: …and no duplicate notice", len(posts("mount-connections-fireplace")) == 1)
w.tick(minutes=10)
check("mounts: still stale after HEAL_MIN → restarted again", restarted(w) == ["connections-fireplace"], restarted(w))
mountinfo(w, 4202, [OK_LINE])
w.tick()
p = posts("mount-connections-fireplace")
check("mounts: live again → exactly one recovery", len(p) == 2 and p[1]["level"] == "info" and "live folder again" in p[1]["title"], p[-1:])
mountinfo(w, 4101, [OK_LINE, FILE_STALE])
w.tick()
check("mounts: a replaced file outside MOUNT_WATCH is not touched", restarted(w) == [] and len(posts("mount-console-fireplace")) == 0)
w = World()
os.environ["HEAL_MAX"] = "1"
w.containers[:] = [["console-fireplace", "running", "Up (healthy)", "fireplace"], ["connections-fireplace", "running", "Up (healthy)", "fireplace"]]
w.docker["pids"] = {"console-fireplace": 4101, "connections-fireplace": 4202}
mountinfo(w, 4101, [OK_LINE, STALE])
mountinfo(w, 4202, [OK_LINE, STALE])
w.tick()
check("mounts: the credential broker goes first; HEAL_MAX=1 → one restart this run", restarted(w) == ["connections-fireplace"], restarted(w))
w.tick()
check("mounts: …the next container on the next run", restarted(w) == ["console-fireplace"], restarted(w))
check("mounts: both told, once each", len(posts("mount-console-fireplace")) == 1 and len(posts("mount-connections-fireplace")) == 1)
w = World()
os.environ["HEAL_STALE"] = "0"
w.containers[:] = [["connections-fireplace", "running", "Up (healthy)", "fireplace"]]
w.docker["pids"] = {"connections-fireplace": 4202}
mountinfo(w, 4202, [STALE])
w.tick()
p = posts("mount-connections-fireplace")
check("mounts: HEAL_STALE=0 → told, not restarted", restarted(w) == [] and len(p) == 1 and "restarted it" not in p[0]["body"], p)
w = World()
w.containers[:] = [["connections-fireplace", "running", "Up (healthy)", "fireplace"]]
w.docker["pids"] = {"connections-fireplace": 4202}
w.docker["restart_fail"] = ["connections-fireplace"]
mountinfo(w, 4202, [STALE])
w.tick()
p = posts("mount-connections-fireplace")
check("mounts: a restart that fails is told, with the command to run", p and "could not restart" in p[0]["body"]
      and "docker restart connections-fireplace" in p[0]["body"], p)
w = World()
w.containers[:] = [["connections-fireplace", "running", "Up (healthy)", "fireplace"]]
w.docker["pids"] = {"connections-fireplace": 4202}
mountinfo(w, 4202, [STALE])
rc = w.tick(argv=["--check"])
check("mounts: --check looks and never restarts", rc == 0 and restarted(w) == [])

srv.shutdown()
n, ok = len(RESULTS), sum(RESULTS)
print(f"\n{ok}/{n} pass" + ("" if ok == n else f" — {n - ok} FAIL"))
sys.exit(0 if ok == n else 1)
