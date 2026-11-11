"""supervisor.py — the emulator's one owner: asked to start, it waits for the heat, starts it pinned to one core,
pauses and resumes it with the heat, and stops it — the governor's rule (governor.py) applied to a real process
(DGO-1797, package 11). The HTTP door (server.py) and the CLI only ask this; nothing else starts an emulator.

Every step the owner should see is a bar or an instant on «כל מקביל» (flow.v1, `dgo:flow:android-emulator`):
`device.started` … `device.ended`/`device.failed`, and `device.paused` / `device.resumed` on the heat's acts.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time

import governor as g

_PROBES = []   # probe children a denied signal could not end: reaped when they end by themselves


def signals_work() -> tuple:
    """(True, "") when this container may signal a child of its own, else (False, why).

    On Ubuntu 26.04's kernel 7.0 docker's AppArmor profile is stacked (`docker-default//&unconfined`) and denies
    every signal inside a container (DGO-1604). QEMU kicks its own vCPUs and children with signals, so the
    emulator hung at boot with no word, and the supervisor's own SIGKILL failed in silence (measured on the Dell,
    2026-11-11, DGO-1817). The host's fix is the owner's: `sudo ./bbox apparmor install` (DGO-1606)."""
    for p in list(_PROBES):
        if p.poll() is not None:
            _PROBES.remove(p)
    try:
        p = subprocess.Popen(["sleep", "5"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    except OSError:
        return True, ""                       # nothing to probe with: the start itself will say what happens
    try:
        os.kill(p.pid, signal.SIGTERM)
    except PermissionError as e:
        _PROBES.append(p)
        return False, (f"signals are denied inside this container ({e.strerror}): the host's AppArmor (Ubuntu 26.04, "
                       f"kernel 7.0) stacks the container's profile, and the emulator cannot run here until the host "
                       f"loads the profile (DGO-1606: sudo ./bbox apparmor install)")
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _PROBES.append(p)
        return False, ("a signal inside this container was accepted and did nothing (the child lived on): the emulator "
                       "could not be paused or stopped here")
    return True, ""


class Supervisor:
    def __init__(self, argv, booted, temp, pub=None, cpus="0", taskset=True, disk_free=None, log=None,
                 signals_ok=signals_work):
        """`argv`: the emulator's command (governor.emulator_argv); `booted()`: True once Android says it booted;
        `temp()`: the package temperature or None; `pub`: flowpub (or None); `cpus`: the core to pin to;
        `disk_free()`: bytes free where the device writes (its sparse disk grows), or None when unread;
        `log`: the file the emulator's own output goes to, new each start (None: discarded); `signals_ok()`:
        (bool, why), asked before every start (signals_work)."""
        self.argv, self.booted, self.temp, self.pub = list(argv), booted, temp, pub
        self.disk_free, self.log, self.signals_ok = disk_free, log, signals_ok
        self.cpus, self.taskset = cpus, taskset
        self.lock = threading.Lock()
        self.state, self.asked_by, self.since, self.why = g.OFF, "", 0.0, ""
        self.proc, self.span, self.last_temp, self.signal_error = None, None, None, ""

    # ── what the door asks ────────────────────────────────────────────────────────────────────────────────────
    def start(self, by: str) -> dict:
        with self.lock:
            if self.state == g.OFF and self.proc and self.proc.poll() is not None:
                self.proc = None                # a kept emulator (a stop that failed) has since ended by itself
            if self.state == g.OFF:
                self.state, self.asked_by, self.since, self.why = g.WAITING, str(by or "?")[:64], time.time(), ""
            return self.status_locked()

    def stop(self, why: str = "asked") -> dict:
        with self.lock:
            self._end(failed=False, why=why)
            return self.status_locked()

    def status(self) -> dict:
        with self.lock:
            return self.status_locked()

    def status_locked(self) -> dict:
        return {"state": self.state, "asked_by": self.asked_by, "since": int(self.since), "temp": self.last_temp,
                "pid": self.proc.pid if self.proc else None, "why": self.why}

    # ── one turn of the governor (server.py calls it every two seconds) ───────────────────────────────────────
    def tick(self) -> str | None:
        with self.lock:
            if self.proc and self.proc.poll() is not None and self.state != g.OFF:
                self._end(failed=True, why=f"the emulator exited ({self.proc.returncode})")
                return "exited"
            # the office's own room first: the device's disk grows by what the app writes (install-check kept
            # 20 GB for the office, DGO-1723) — under it the device is stopped and says why
            free = self.disk_free() if self.disk_free and self.state != g.OFF else None
            if free is not None and free < g.DISK_FLOOR_GB << 30:
                self._end(failed=True, why=f"{free >> 30} GB free on the office's disk, under its {g.DISK_FLOOR_GB}")
                return "disk"
            t = self.temp()
            self.last_temp = t
            act = g.decide(t, self.state)
            if act == "start":
                ok, why = self.signals_ok()
                if not ok:
                    self._refuse(why)
                    return "refused"
                if self.proc and self.proc.poll() is None:     # an emulator a stop could not end holds the device
                    self._refuse(f"the previous emulator (pid {self.proc.pid}) is still running and could not be "
                                 f"stopped{': ' + self.signal_error if self.signal_error else ''}")
                    return "refused"
                self._spawn()
            elif act == "pause":
                self._signal(signal.SIGSTOP)
                self.state = g.PAUSED
                self._emit("device.paused", f"נעצר לקירור · {t}°C")
            elif act == "resume":
                self._signal(signal.SIGCONT)
                self.state = g.RUNNING if self._booted() else g.BOOTING
                self._emit("device.resumed", f"ממשיך · {t}°C")
            elif act == "stop":
                self._end(failed=True, why=f"{t}°C: the {g.STOP_AT}°C limit")
            elif self.state == g.BOOTING and self._booted():
                self.state = g.RUNNING
            return act

    # ── inside ────────────────────────────────────────────────────────────────────────────────────────────────
    def _spawn(self):
        cmd = (["taskset", "-c", self.cpus] if self.taskset else []) + self.argv
        # its own output in a file of its own, new each start: a boot that hangs says why there (GET /api/log)
        out = subprocess.DEVNULL
        if self.log:
            try:
                out = open(self.log, "wb")
            except OSError:
                out = subprocess.DEVNULL
        # its own process group: the emulator starts qemu children, and a pause must stop them all
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                         start_new_session=True)
        finally:
            if out is not subprocess.DEVNULL:
                out.close()                     # the child holds its own copy
        self.signal_error = ""
        self.state, self.since = g.BOOTING, time.time()
        if self.pub:
            sid, t0, _ = self.pub.span_start("android-emulator", "device", f"אמולטור · ביקש: {self.asked_by}",
                                             {"caller": self.asked_by, "cpus": self.cpus})
            self.span = (sid, t0)

    def _signal(self, sig):
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, sig)
            except ProcessLookupError:
                pass
            except PermissionError as e:       # kept: a stop that could not kill says so (_end), never «off» alone
                self.signal_error = f"signal {sig.name if hasattr(sig, 'name') else sig}: {e.strerror}"

    def _booted(self) -> bool:
        try:
            return bool(self.booted())
        except Exception:                                          # noqa: BLE001 — adb away is «not yet»
            return False

    def _end(self, failed: bool, why: str):
        if self.proc and self.proc.poll() is None:
            self._signal(signal.SIGCONT)                           # a stopped process must wake to die
            self._signal(signal.SIGKILL)
            if not self.signal_error:          # a refused SIGKILL kills nothing: no 10 s under the lock for it
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
        alive = bool(self.proc) and self.proc.poll() is None
        if alive:                    # said, and kept: «off» over a running emulator was what the Dell showed (DGO-1817)
            why = (f"{why}; the emulator (pid {self.proc.pid}) did not stop"
                   f"{': ' + self.signal_error if self.signal_error else ''}")
            failed = True
        if self.span and self.pub:
            self.pub.span_end("android-emulator", "device", f"אמולטור · {why}", self.span[0], self.span[1], failed,
                              {"why": why})
        self.proc = self.proc if alive else None
        self.span = None
        self.state, self.why, self.since = g.OFF, why, time.time()

    def _refuse(self, why: str):
        """A start that cannot happen: off again at once, the reason said on the status and as an instant."""
        self.state, self.why, self.since = g.OFF, why, time.time()
        self._emit("device.failed", f"אמולטור לא הופעל · {why[:120]}")

    def _emit(self, typ, title):
        if self.pub:
            self.pub.emit("android-emulator", typ, title, {"temp": self.last_temp})
