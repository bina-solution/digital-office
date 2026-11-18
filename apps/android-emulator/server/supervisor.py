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
    2026-11-11, DGO-1817). The host's fix: `./bbox apparmor install`, which gets root itself (DGO-1606, DGO-1848)."""
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
                       f"loads the profile (DGO-1606: ./bbox apparmor install)")
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _PROBES.append(p)
        return False, ("a signal inside this container was accepted and did nothing (the child lived on): the emulator "
                       "could not be paused or stopped here")
    return True, ""


class Supervisor:
    def __init__(self, argv, booted, temp, pub=None, cpus="0", taskset=True, disk_free=None, log=None,
                 signals_ok=signals_work, ask_exit=None, idle_s=0, save_s=g.SAVE_S, now=time.time):
        """`argv`: the emulator's command (governor.emulator_argv); `booted()`: True once Android says it booted;
        `temp()`: the package temperature or None; `pub`: flowpub (or None); `cpus`: the core to pin to;
        `disk_free()`: bytes free where the device writes (its sparse disk grows), or None when unread;
        `log`: the file the emulator's own output goes to, new each start (None: discarded); `signals_ok()`:
        (bool, why), asked before every start (signals_work); `ask_exit()`: True once a RUNNING emulator was asked to
        save its snapshot and exit (`adb emu kill`; None: every stop kills); `idle_s`: a device nobody watched or
        used for this long stops by itself (0: never); `save_s`: how long a stop waits for that save."""
        self.argv, self.booted, self.temp, self.pub = list(argv), booted, temp, pub
        self.disk_free, self.log, self.signals_ok = disk_free, log, signals_ok
        self.ask_exit, self.idle_s, self.save_s, self.now = ask_exit, max(0, int(idle_s or 0)), save_s, now
        self.cpus, self.taskset = cpus, taskset
        self.lock = threading.Lock()
        self.state, self.asked_by, self.since, self.why, self.code = g.OFF, "", 0.0, "", ""
        self.proc, self.span, self.last_temp, self.signal_error = None, None, None, ""
        # who looks at it (the screen's open displays), the door's verbs in flight, and when it was last used: the
        # idle rule's facts
        self.viewers, self.holds, self.last_used = 0, 0, 0.0
        self.stop_by, self.stop_why, self.stop_code = 0.0, "", ""
        self.again = ""         # who asked for a start while it was saving: it starts once the save is done
        self.saved = False      # whether the last stop saved the snapshot — the screen says «saved» only then
        self.idle_thread = None  # the last idle stop's thread (tick)

    # ── what the door asks ────────────────────────────────────────────────────────────────────────────────────
    def start(self, by: str) -> dict:
        with self.lock:
            if self.state == g.OFF and self.proc and self.proc.poll() is not None:
                self.proc = None                # a kept emulator (a stop that failed) has since ended by itself
            if self.state == g.STOPPING:        # kept, not dropped: a check that asks during a save gets its device
                self.again = str(by or "?")[:64]
            if self.state == g.OFF:
                self._wait_for(by)
            return self.status_locked()

    def stop(self, why: str = "asked", code: str = "asked") -> dict:
        """A RUNNING device is asked to save its snapshot and exit (`stopping`, finished by tick); anything else ends
        now. The ask (adb, up to 15 s) is made OUTSIDE the lock: the status and the display never wait for it."""
        with self.lock:
            self.again = ""
            ask = self._begin_stop(why, code)
        if ask:
            try:
                asked = bool(self.ask_exit())
            except Exception:                                      # noqa: BLE001 — not asked is a plain stop
                asked = False
            if not asked:
                with self.lock:
                    if self.state == g.STOPPING:                   # the emulator was not reached: a plain stop
                        self._end(failed=False, why=why, code=code)
                        self._after_stop()                         # …and a start asked meanwhile still stands
        with self.lock:
            return self.status_locked()

    def touch(self):
        """The device was used (bytes moved on an open display, a verb of the door): the idle clock starts again."""
        with self.lock:
            self.last_used = self.now()

    def hold(self, delta: int):
        """A verb of the door began (+1) or ended (-1): an install of 25 minutes is a use for all of them."""
        with self.lock:
            self.holds = max(0, self.holds + int(delta))
            self.last_used = self.now()

    def watch(self, delta: int):
        """A display of the screen opened (+1) or closed (-1): counted, and nothing more. A display that only
        reconnects (every two seconds while the display's stack is down) is no use; what moves on it is (touch)."""
        with self.lock:
            self.viewers = max(0, self.viewers + int(delta))

    def status(self) -> dict:
        with self.lock:
            return self.status_locked()

    def status_locked(self) -> dict:
        idle_in = None
        if self.idle_s and self.state in (g.BOOTING, g.RUNNING):
            idle_in = max(0, int(self.last_used + self.idle_s - self.now()))
        return {"state": self.state, "asked_by": self.asked_by, "since": int(self.since), "temp": self.last_temp,
                "pid": self.proc.pid if self.proc else None, "why": self.why, "code": self.code,
                "saved": self.saved, "again": bool(self.again), "viewers": self.viewers,
                "idle_stop_s": self.idle_s, "idle_in": idle_in}

    # ── one turn of the governor (server.py calls it every two seconds) ───────────────────────────────────────
    def tick(self) -> str | None:
        with self.lock:
            act = self._turn()
        if act == "idle":            # nobody watched it and nobody used it: the Dell's core and 4 GB go back —
            # stopped from a thread of its own, so the governor's next turn (the heat) never waits for adb; kept, so a
            # caller (a test) can join it instead of guessing how long it takes
            self.idle_thread = threading.Thread(target=self.stop, daemon=True, name="idle-stop",
                                                args=(f"nobody used it for {self.idle_s // 60} minutes", "idle"))
            self.idle_thread.start()
        return act

    def _turn(self) -> str | None:
        """One turn, under the lock. «idle» is returned, not acted on: its stop asks the emulator (tick, unlocked)."""
        if self.state == g.STOPPING:                      # saving its snapshot: done when it exits, killed when late
            if not self.proc or self.proc.poll() is not None:
                self._end(failed=False, why=self.stop_why, code=self.stop_code, saved=True)
                self._after_stop()
                return "stopped"
            if self.now() >= self.stop_by:
                self._end(failed=True, why=f"{self.stop_why}; the snapshot was not saved in {self.save_s} s",
                          code=self.stop_code)
                self._after_stop()
                return "stopped"
            t = self.temp()                               # the heat rules a save too: it writes gigabytes
            self.last_temp = t
            if t is not None and t >= g.STOP_AT:
                self._end(failed=True, why=f"{t}°C: the {g.STOP_AT}°C limit, while saving", code="heat")
                self._after_stop()
                return "stop"
            return None
        if self.proc and self.proc.poll() is not None and self.state != g.OFF:
            self._end(failed=True, why=f"the emulator exited ({self.proc.returncode})", code="exited")
            return "exited"
        if self.holds:                                    # a verb of the door is running: in use all along
            self.last_used = self.now()
        if self.idle_s and self.state in (g.BOOTING, g.RUNNING) and self.now() - self.last_used >= self.idle_s:
            return "idle"
        # the office's own room first: the device's disk grows by what the app writes (install-check kept
        # 20 GB for the office, DGO-1723) — under it the device is stopped and says why
        free = self.disk_free() if self.disk_free and self.state != g.OFF else None
        if free is not None and free < g.DISK_FLOOR_GB << 30:
            self._end(failed=True, why=f"{free >> 30} GB free on the office's disk, under its {g.DISK_FLOOR_GB}",
                      code="disk")
            return "disk"
        t = self.temp()
        self.last_temp = t
        act = g.decide(t, self.state)
        if act == "start":
            ok, why = self.signals_ok()
            if not ok:
                self._refuse(why)
                return "refused"
            if self.proc and self.proc.poll() is None:         # an emulator a stop could not end holds the device
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
            self.last_used = self.now()                   # a pause for the heat is nobody's idleness
            self._emit("device.resumed", f"ממשיך · {t}°C")
        elif act == "stop":
            self._end(failed=True, why=f"{t}°C: the {g.STOP_AT}°C limit", code="heat")
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
        self.state, self.since, self.last_used = g.BOOTING, self.now(), self.now()
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

    def _wait_for(self, by: str):
        self.state, self.asked_by, self.since, self.why, self.code = g.WAITING, str(by or "?")[:64], self.now(), "", ""
        self.last_used = self.now()

    def _begin_stop(self, why: str, code: str) -> bool:
        """Under the lock: True when a RUNNING device is now `stopping` and the emulator must be asked to save (the
        caller asks, outside the lock); otherwise it is ended now. One already stopping keeps its first reason."""
        if self.state == g.STOPPING:
            return False
        if self.state == g.RUNNING and self.ask_exit and self.proc and self.proc.poll() is None:
            self.state, self.stop_by, self.stop_why, self.stop_code = g.STOPPING, self.now() + self.save_s, why, code
            return True
        self._end(failed=False, why=why, code=code)
        return False

    def _after_stop(self):
        """A start asked for during the save: the device waits for the heat again, for whoever asked."""
        if self.again and self.state == g.OFF and not self.proc:
            self._wait_for(self.again)
        self.again = ""

    def _end(self, failed: bool, why: str, code: str = "asked", saved: bool = False):
        ran = self.proc is not None             # a stop of a device that never ran leaves the last snapshot as it was
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
            failed, code = True, "stuck"
        if self.span and self.pub:
            self.pub.span_end("android-emulator", "device", f"אמולטור · {why}", self.span[0], self.span[1], failed,
                              {"why": why, "code": code})
        self.proc = self.proc if alive else None
        self.span = None
        self.state, self.why, self.code, self.since = g.OFF, why, code, self.now()
        if ran:
            self.saved = saved and not alive

    def _refuse(self, why: str):
        """A start that cannot happen: off again at once, the reason said on the status and as an instant."""
        self.state, self.why, self.code, self.since = g.OFF, why, "refused", self.now()
        self._emit("device.failed", f"אמולטור לא הופעל · {why[:120]}")

    def _emit(self, typ, title):
        if self.pub:
            self.pub.emit("android-emulator", typ, title, {"temp": self.last_temp})
