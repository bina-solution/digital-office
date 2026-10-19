#!/usr/bin/env python3
"""power-agent.py — keep the Mac awake while the office should be working, per the owner's policy.

WHY. The office runs in a Lima VM. When macOS sleeps, the VM and every container and agent in it
freeze until the Mac wakes. Measured 2026-09-29 (pmset -g log): the Mac idle-slept ~7 s after the
display went off — on battery AND on power — and the four agents running then spent 28 of 43
"running" hours frozen. Staying awake is a HOST decision, so it is enforced here, on the host.

WHAT. Every INTERVAL seconds it reads the owner's policy (data/power/policy.json, written by the
console's settings view through the machine service), senses the Mac (power source, battery,
lid, screen lock, thermal state), and enforces:
  * idle sleep (screen locked / display off / nobody at the keyboard): a `caffeinate -i` child,
    held while the policy says "run". Needs no admin.
  * lid closed: macOS sleeps on lid close no matter what `caffeinate` asserts (clamshell sleep).
    The only switch is the system-wide `pmset -a disablesleep 1`, which needs root. It is used
    ONLY if the owner installed the one narrow sudoers rule shown in the settings view (the exact
    command is in status.json → setup); otherwise the status says so and nothing is attempted.
Guards that always win: below the battery floor on battery, or under thermal pressure (critical at
once, serious for 5 minutes; when the thermal guard is on), everything is released and the Mac
sleeps as usual. These guards are not optional polish: `disablesleep 1` also switches off macOS's
OWN low-battery and thermal-emergency sleep (xnu checkSystemSleepAllowed tests SleepDisabled
first), so while it is set, this agent is the only thing standing between a closed MacBook in a
bag and a flat or overheated one. Clearing it does not make a closed lid sleep by itself, so a
release with the lid closed is followed by `pmset sleepnow`.
It writes what it saw and did to data/power/status.json for the settings view.

LIFETIME. Started by `bbox engine start` (packaging/macos/engine.sh), one per Mac. It watches the
engine's host-agent PID: when the engine stops, it releases everything it holds and exits. On
SIGTERM/SIGINT it releases too. It never leaves `disablesleep 1` behind on a normal exit.

Python 3.9 (the Command Line Tools' python3), standard library only.
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

PMSET = "/usr/bin/pmset"
SUDOERS_FILE = "/private/etc/sudoers.d/digital-office-power"
# SleepDisabled persists across reboots (powerd re-applies it at boot), so the one-time setup also
# installs a boot job that clears it; this agent sets it again only if the policy still wants it.
BOOT_RESET = "/Library/LaunchDaemons/co.digitaloffice.sleepreset.plist"
SERIOUS_GRACE_S = 300   # serious thermal pressure tolerated this long before releasing
DEFAULTS = {
    "version": 1,
    "lock": {"ac": "run", "battery": "run"},
    "lid": {"ac": "run", "battery": "run"},
    "battery_floor": 20,
    "thermal_guard": True,
}
THERMAL_NAMES = {0: "nominal", 1: "fair", 2: "serious", 3: "critical"}


def run(cmd, timeout=10):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_policy(path):
    policy = json.loads(json.dumps(DEFAULTS))
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return policy
    for key in ("lock", "lid"):
        for src in ("ac", "battery"):
            value = (stored.get(key) or {}).get(src)
            if value in ("run", "sleep"):
                policy[key][src] = value
    floor = stored.get("battery_floor")
    if isinstance(floor, int) and 5 <= floor <= 90:
        policy["battery_floor"] = floor
    if isinstance(stored.get("thermal_guard"), bool):
        policy["thermal_guard"] = stored["thermal_guard"]
    return policy


# ── sensing ─────────────────────────────────────────────────────────────────────────────────────
def sense_power():
    _, out = run([PMSET, "-g", "batt"])
    source = "ac" if "AC Power" in out else ("battery" if "Battery Power" in out else "unknown")
    m = re.search(r"(\d+)%;\s*([a-zA-Z ]+);", out)
    return {"source": source, "percent": int(m.group(1)) if m else None,
            "state": m.group(2).strip() if m else None, "has_battery": "InternalBattery" in out}


def sense_lid():
    _, out = run(["/usr/sbin/ioreg", "-r", "-k", "AppleClamshellState", "-d", "1"])
    closed = re.search(r'"AppleClamshellState" = (Yes|No)', out)
    causes = re.search(r'"AppleClamshellCausesSleep" = (Yes|No)', out)
    return {"closed": (closed.group(1) == "Yes") if closed else None,
            # No = an external display + power make the Mac run with the lid closed by itself
            "causes_sleep": (causes.group(1) == "Yes") if causes else None}


def sense_locked():
    _, out = run(["/usr/sbin/ioreg", "-n", "Root", "-d1"])
    return "CGSSessionScreenIsLocked\"=Yes" in out.replace(" ", "")


def sense_thermal():
    code, out = run(["/usr/bin/osascript", "-l", "JavaScript", "-e",
                     'ObjC.import("Foundation"); $.NSProcessInfo.processInfo.thermalState'], timeout=5)
    try:
        return int(out.strip()) if code == 0 else None
    except ValueError:
        return None


def sense_sleep_disabled():
    _, out = run([PMSET, "-g"])
    m = re.search(r"SleepDisabled\s+(\d)", out)
    return bool(m and m.group(1) == "1")


def can_control_lid():
    # `sudo -n -l CMD` exits 0 only when CMD is allowed without a password: the rule is in place.
    code, _ = run(["/usr/bin/sudo", "-n", "-l", PMSET, "-a", "disablesleep", "1"], timeout=5)
    return code == 0


EVENT_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) [+-]\d{4} (Sleep|Wake|DarkWake) +\t(.*)$")


def recent_events(limit=14):
    """The last sleeps and wakes, straight from pmset's own log (what actually happened)."""
    try:
        p = subprocess.run([PMSET, "-g", "log"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return [], None
    events, asleep_ms, last_sleep = [], 0, None
    cutoff = time.time() - 86400
    for line in p.stdout.splitlines():
        m = EVENT_RE.match(line)
        if not m:
            continue
        ts = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
        kind, msg = m.group(2), m.group(3)
        reason = re.search(r"due to '?([^:']+)'?", msg)
        if kind == "Sleep":
            last_sleep = ts
        elif last_sleep is not None:
            if ts > cutoff:
                asleep_ms += (ts - max(last_sleep, cutoff)) * 1000
            last_sleep = None
        label = event_label(kind, reason.group(1).strip() if reason else "", msg)
        if label is None:
            continue   # maintenance wakes and the re-sleeps after them: noise for the owner
        events.append({"at": m.group(1), "kind": kind, "cause": label,
                       "on": "battery" if "Using Batt" in msg or "Using BATT" in msg else ("ac" if "Using AC" in msg else "")})
    return events[-limit:], round(asleep_ms / 3600000, 1)


def event_label(kind, reason, msg):
    """pmset's cause, reduced to the handful the owner can act on (the UI words them)."""
    if kind == "DarkWake":
        return None
    if kind == "Wake":
        if "lid" in msg:
            return "lid-opened"
        if "HID" in msg or "UserActivity" in msg or "keyboard" in msg or "multi-touch" in msg:
            return "user"
        return "other"
    return {"Idle Sleep": "idle", "Clamshell Sleep": "lid-closed", "Low Power Sleep": "battery-empty",
            "Dark Wake Thermal Emergency": "overheated", "Software Sleep": "menu", "Power Button Sleep": "button",
            }.get(reason, None if reason in ("Maintenance Sleep", "Sleep Service Back to Sleep",
                                             "Notification Wake Back to Sleep") else "other")


def setup_commands():
    """The one-time admin step, spelled out for the OWNER to run in Terminal (this agent never
    runs it): a sudoers rule allowing exactly three pmset invocations without a password, checked
    by visudo before it is installed, plus a boot job that clears SleepDisabled on every start."""
    user = os.environ.get("USER") or "$USER"
    grant = "\n".join([
        "cat > /tmp/digital-office-power <<'EOF'",
        "Cmnd_Alias DO_POWER = %s -a disablesleep 1, %s -a disablesleep 0, %s sleepnow" % (PMSET, PMSET, PMSET),
        "%s ALL=(root) NOPASSWD: DO_POWER" % user,
        "EOF",
        "sudo visudo -cf /tmp/digital-office-power && sudo install -o root -g wheel -m 0440 /tmp/digital-office-power %s && rm /tmp/digital-office-power" % SUDOERS_FILE,
        "sudo /usr/libexec/PlistBuddy -c 'Add :Label string co.digitaloffice.sleepreset' -c 'Add :ProgramArguments array'"
        " -c 'Add :ProgramArguments:0 string %s' -c 'Add :ProgramArguments:1 string -a' -c 'Add :ProgramArguments:2 string disablesleep'"
        " -c 'Add :ProgramArguments:3 string 0' -c 'Add :RunAtLoad bool true' %s" % (PMSET, BOOT_RESET),
        "sudo launchctl bootstrap system %s" % BOOT_RESET,
    ])
    revoke = "; ".join([
        "sudo %s -a disablesleep 0" % PMSET,
        "sudo rm -f %s" % SUDOERS_FILE,
        "sudo launchctl bootout system/co.digitaloffice.sleepreset",
        "sudo rm -f %s" % BOOT_RESET,
    ])
    return {"grant": grant, "revoke": revoke, "boot_reset_installed": os.path.exists(BOOT_RESET)}


# ── enforcing ──────────────────────────────────────────────────────────────────────────────────
class Agent:
    def __init__(self, repo, watch_pid, interval):
        self.dir = repo / "data" / "power"
        self.watch_pid = watch_pid
        self.interval = interval
        self.caffeinate = None
        self.set_disablesleep = False   # we turned disablesleep on, so we must turn it off
        self.lid_permission = None
        self.permission_checked = 0.0
        self.events, self.asleep_24h, self.events_at = [], None, 0.0
        self.serious_since = None
        self.lid_closed = False
        self.notes = []

    def hold_idle(self, want):
        alive = self.caffeinate is not None and self.caffeinate.poll() is None
        if want and not alive:
            # -w: the assertion dies with this agent even if it is SIGKILLed
            self.caffeinate = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())])
        elif not want and alive:
            self.caffeinate.terminate()
            self.caffeinate = None
        return want

    def set_lid(self, want, current):
        if want == current:
            return current
        if not self.lid_permission:
            if current and not want and not self.set_disablesleep:
                self.notes.append("SleepDisabled is on but was not set by this agent; leaving it alone")
            return current
        code, _ = run(["/usr/bin/sudo", "-n", PMSET, "-a", "disablesleep", "1" if want else "0"])
        if code == 0:
            self.set_disablesleep = want
            if not want:
                self.sleep_if_lid_closed()
            return want
        self.notes.append("pmset disablesleep failed; the sudoers rule may have changed")
        return current

    def sleep_if_lid_closed(self):
        # Clearing SleepDisabled only flips the flag; a lid that is already closed is not looked at
        # again, so the Mac would stay up in the bag. Put it to sleep, as closing the lid meant.
        if self.lid_closed:
            if run([PMSET, "sleepnow"])[0] != 0:
                run(["/usr/bin/sudo", "-n", PMSET, "sleepnow"])

    def release(self):
        self.hold_idle(False)
        if self.set_disablesleep:
            run(["/usr/bin/sudo", "-n", PMSET, "-a", "disablesleep", "0"])
            self.set_disablesleep = False
            self.sleep_if_lid_closed()

    def engine_running(self):
        if not self.watch_pid:
            return True
        try:
            os.kill(self.watch_pid, 0)
            return True
        except OSError:
            return False

    def tick(self):
        self.notes = []
        policy = load_policy(self.dir / "policy.json")
        power, lid = sense_power(), sense_lid()
        locked, thermal = sense_locked(), sense_thermal()
        self.lid_closed = bool(lid["closed"])
        now = time.time()
        if now - self.permission_checked > 60:
            self.lid_permission = can_control_lid()
            self.permission_checked = now
        if now - self.events_at > 300:
            self.events, self.asleep_24h = recent_events()
            self.events_at = now
        src = power["source"] if power["source"] in ("ac", "battery") else "ac"
        reasons = []
        low = src == "battery" and power["percent"] is not None and power["percent"] < policy["battery_floor"]
        if low:
            reasons.append("battery below %d%%" % policy["battery_floor"])
        if thermal is not None and thermal >= 2:
            self.serious_since = self.serious_since or now
        else:
            self.serious_since = None
        hot_for = int(now - self.serious_since) if self.serious_since else 0
        hot = bool(policy["thermal_guard"] and thermal is not None
                   and (thermal >= 3 or hot_for >= SERIOUS_GRACE_S))
        if hot:
            reasons.append("thermal pressure: %s" % THERMAL_NAMES.get(thermal, thermal))
        elif self.serious_since:
            self.notes.append("thermal pressure serious for %ds; releasing at %ds" % (hot_for, SERIOUS_GRACE_S))
        engine = self.engine_running()
        if not engine:
            reasons.append("the engine is not running")
        guard = low or hot or not engine
        want_idle = policy["lock"][src] == "run" and not guard
        want_lid = policy["lid"][src] == "run" and not guard
        # disablesleep keeps the Mac up with the lid closed; it must be ON before the lid closes,
        # because a closing lid sleeps the Mac before anything here could react.
        sleep_disabled = self.set_lid(want_lid, sense_sleep_disabled())
        caffeinated = self.hold_idle(want_idle or (want_lid and not sleep_disabled))
        lid_ok = sleep_disabled or lid["causes_sleep"] is False
        status = {
            "version": 1, "platform": "macos", "host": os.uname().nodename,
            "updated_at": int(now), "agent_pid": os.getpid(), "engine_running": engine,
            "power": power, "lid": lid, "screen_locked": locked,
            "thermal": {"state": thermal, "name": THERMAL_NAMES.get(thermal)},
            "sleep_disabled": sleep_disabled, "caffeinated": caffeinated,
            "lid_permission": bool(self.lid_permission),
            "effective": {
                "lock": "run" if (caffeinated or sleep_disabled) else "sleep",
                "lid": "run" if (want_lid and lid_ok) else "sleep",
                "source": src, "guards": reasons,
            },
            "wanted": {"lock": "run" if want_idle else "sleep", "lid": "run" if want_lid else "sleep"},
            "notes": self.notes,
            "events": self.events, "asleep_last_24h_h": self.asleep_24h,
            "setup": setup_commands(),
        }
        atomic_write(self.dir / "status.json", status)
        return engine


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--watch-pid", type=int, default=0, help="exit when this PID (the engine) exits")
    ap.add_argument("--interval", type=int, default=15)
    ap.add_argument("--once", action="store_true", help="sense + write status once, hold nothing")
    a = ap.parse_args()
    agent = Agent(Path(a.repo), a.watch_pid, a.interval)

    def stop(*_):
        agent.release()
        sys.exit(0)

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, stop)
    if a.once:
        agent.tick()
        agent.release()
        print((agent.dir / "status.json").read_text(encoding="utf-8"))
        return
    while True:
        try:
            if not agent.tick():
                agent.release()
                agent.tick()   # record the released state for the settings view
                return
        except Exception as error:  # never die holding an assertion without saying why
            sys.stderr.write("power-agent: %s\n" % error)
        time.sleep(agent.interval)


if __name__ == "__main__":
    try:
        main()
    finally:
        pass
