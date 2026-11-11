"""governor.py — how the office's Android emulator is started, pinned and kept cool (DGO-1797, package 11).

The emulator becomes an app the owner sees and uses (DGO-1797: nothing started on the Dell's host by hand). Its
rules come from the workflow that ran it until now, android-install-check.yml, where they were measured:

  * HEAT: it starts only under 80°C, is PAUSED (SIGSTOP, never killed) at 85°C, resumed under 80°C, and STOPPED
    at 90°C. On 2026-11-09 a boot on two threads took the Dell from 83 to 92°C in 81 s and it switched itself off,
    the herd's only runner with it; on one core it climbs 81→91°C in 5 s and cools in 5 s.
  * ONE physical core: cpu0 and its hyperthread sibling (`thread_siblings_list`), one virtual core.
  * x86_64 Android with its own arm64 translation, on KVM, software GPU (swiftshader_indirect).

Pure: no process is started here. The supervisor (server.py) reads the temperature, asks decide() what to do,
and signals the emulator; this file is what its tests hold.
"""
from __future__ import annotations

import glob
import os

START_BELOW = 80      # °C: the emulator starts only under this
PAUSE_AT = 85         # °C: SIGSTOP at or above this
RESUME_BELOW = 80     # °C: SIGCONT under this, after a pause
STOP_AT = 90          # °C: stopped at or above this, and it says why
DISK_FLOOR_GB = 20    # GB free on the office's disk: under it the device is stopped (the office keeps its room)

#: the states the screen shows (the design, §2(iii)): off, waiting at the door, booting, running, paused for heat
OFF, WAITING, BOOTING, RUNNING, PAUSED = "off", "waiting", "booting", "running", "paused"


def package_temp(root: str = "/sys/class/thermal") -> int | None:
    """The CPU package's temperature in °C (the x86_pkg_temp zone), or None where the machine says nothing — a
    machine that cannot be read is never taken as cool."""
    for zone in sorted(glob.glob(os.path.join(root, "thermal_zone*"))):
        try:
            with open(os.path.join(zone, "type"), encoding="utf-8") as f:
                if f.read().strip() != "x86_pkg_temp":
                    continue
            with open(os.path.join(zone, "temp"), encoding="utf-8") as f:
                return int(f.read().strip()) // 1000
        except (OSError, ValueError):
            continue
    return None


def decide(temp: int | None, state: str) -> str | None:
    """What to do now: "stop", "pause", "resume", "wait" (do not start yet) — or None, nothing to do.

    `state` is the emulator's: WAITING (asked for, not started), BOOTING or RUNNING (going), PAUSED (stopped by
    heat), OFF. An unreadable temperature holds a start and pauses nothing that runs: the hardware's own limit
    still stands, and a reading that comes back resumes the rule."""
    if state == OFF:
        return None
    if state == WAITING:
        return "wait" if temp is None or temp >= START_BELOW else "start"
    if temp is None:
        return None
    if temp >= STOP_AT:
        return "stop"
    if state in (BOOTING, RUNNING) and temp >= PAUSE_AT:
        return "pause"
    if state == PAUSED and temp < RESUME_BELOW:
        return "resume"
    return None


def pinned_cpus(root: str = "/sys/devices/system/cpu") -> str:
    """cpu0 and its hyperthread sibling (`0,4` or `0-1`), as taskset -c and compose `cpuset` take it; "0" when the
    machine does not say."""
    try:
        with open(os.path.join(root, "cpu0", "topology", "thread_siblings_list"), encoding="utf-8") as f:
            said = f.read().strip()
    except OSError:
        return "0"
    return said if said and all(c in "0123456789,-" for c in said) else "0"


def emulator_argv(avd: str, memory_mb: int, partition_mb: int) -> list[str]:
    """The emulator's command line: the workflow's flags, with a window — the screen shows it through VNC, so no
    -no-window here (DISPLAY is the app's Xvnc)."""
    return ["emulator", "-avd", avd, "-no-audio", "-no-boot-anim", "-no-snapshot", "-gpu", "swiftshader_indirect",
            "-cores", "1", "-memory", str(int(memory_mb)), "-partition-size", str(int(partition_mb))]
