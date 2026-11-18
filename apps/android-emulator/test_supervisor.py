#!/usr/bin/env python3
"""test_supervisor — the emulator's owner drives a real process through the heat rule (DGO-1797, package 11).

    python3 apps/android-emulator/test_supervisor.py      (G72 runs it; standard library only, Linux or macOS)

A stand-in emulator (a sleeping python) in its own process group: started only when cool, paused (its state
`T`) at 85°C, resumed under 80, stopped at 90 with its bar closed as failed; a stop on request closes it ended.
"""
import importlib.util
import os
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "server"))
spec = importlib.util.spec_from_file_location("emu_supervisor", os.path.join(HERE, "server", "supervisor.py"))
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)
g = s.g


class Pub:
    def __init__(self):
        self.events = []

    def span_start(self, app, kind, title, data=None, link=""):
        self.events.append(("start", kind, title))
        return "sid", 1, True

    def span_end(self, app, kind, title, sid, t0, failed=False, data=None, link=""):
        self.events.append(("failed" if failed else "ended", kind, title))
        return True

    def emit(self, app, typ, title, data=None, link=""):
        self.events.append((typ, title))
        return True


def stopped(pid):
    """True when the process is stopped (SIGSTOP): `ps` says T."""
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return out.startswith("T")


class Supervise(unittest.TestCase):
    def setUp(self):
        self.temp = [70]
        self.boot = [False]
        self.pub = Pub()
        self.sup = s.Supervisor([sys.executable, "-c", "import time; time.sleep(60)"], booted=lambda: self.boot[0],
                                temp=lambda: self.temp[0], pub=self.pub, taskset=False)

    def tearDown(self):
        self.sup.stop("test over")

    def test_the_whole_life(self):
        self.temp[0] = 82
        self.assertEqual(self.sup.start("owner")["state"], g.WAITING)
        self.assertEqual(self.sup.tick(), "wait")                      # too hot to start
        self.assertIsNone(self.sup.proc)
        self.temp[0] = 75
        self.assertEqual(self.sup.tick(), "start")
        self.assertEqual(self.sup.state, g.BOOTING)
        pid = self.sup.proc.pid
        self.boot[0] = True
        self.sup.tick()
        self.assertEqual(self.sup.state, g.RUNNING)
        self.temp[0] = 86
        self.assertEqual(self.sup.tick(), "pause")
        time.sleep(0.2)
        self.assertTrue(stopped(pid), "paused at 85°C")
        self.temp[0] = 82
        self.assertIsNone(self.sup.tick())                              # not yet under 80
        self.temp[0] = 78
        self.assertEqual(self.sup.tick(), "resume")
        time.sleep(0.2)
        self.assertFalse(stopped(pid))
        self.assertEqual(self.sup.state, g.RUNNING)
        self.temp[0] = 91
        self.assertEqual(self.sup.tick(), "stop")
        self.assertEqual(self.sup.state, g.OFF)
        self.assertIn("90°C limit", self.sup.why)
        self.assertEqual([e[0] for e in self.pub.events], ["start", "device.paused", "device.resumed", "failed"])

    def test_a_stop_on_request_closes_the_bar_ended(self):
        self.sup.start("ci")
        self.sup.tick()
        self.assertEqual(self.sup.status()["state"], g.BOOTING)
        self.assertEqual(self.sup.stop()["state"], g.OFF)
        self.assertEqual(self.pub.events[-1][0], "ended")

    def test_an_emulator_that_exits_is_said(self):
        sup = s.Supervisor([sys.executable, "-c", "raise SystemExit(3)"], booted=lambda: False, temp=lambda: 70,
                           pub=self.pub, taskset=False)
        sup.start("ci")
        sup.tick()
        time.sleep(0.5)
        self.assertEqual(sup.tick(), "exited")
        self.assertEqual((sup.state, sup.why), (g.OFF, "the emulator exited (3)"))

    def test_under_the_offices_disk_floor_the_device_is_stopped_and_says_why(self):
        free = [50 << 30]
        sup = s.Supervisor([sys.executable, "-c", "import time; time.sleep(60)"], booted=lambda: True,
                           temp=lambda: 70, pub=self.pub, taskset=False, disk_free=lambda: free[0])
        self.addCleanup(sup.stop, "test over")
        sup.start("ci")
        self.assertEqual(sup.tick(), "start")
        free[0] = None                                                  # unread: no word on the disk
        sup.tick()
        self.assertEqual(sup.state, g.RUNNING)
        free[0] = (g.DISK_FLOOR_GB << 30) - 1
        self.assertEqual(sup.tick(), "disk")
        self.assertEqual(sup.state, g.OFF)
        self.assertIn(f"under its {g.DISK_FLOOR_GB}", sup.why)

    def test_an_unreadable_temperature_holds_the_start(self):
        self.temp[0] = None
        self.sup.start("owner")
        self.assertEqual(self.sup.tick(), "wait")
        self.assertIsNone(self.sup.proc)

    # ── DGO-1817: what the Dell's AppArmor did (in-container signals denied), said instead of a silent hang ──
    def test_signals_work_here_and_the_probe_says_so(self):
        ok, why = s.signals_work()
        self.assertTrue(ok, why)                          # this machine lets a process signal its own child
        self.assertEqual(why, "")

    def test_a_start_where_signals_are_denied_is_refused_and_says_why(self):
        sup = s.Supervisor([sys.executable, "-c", "import time; time.sleep(60)"], booted=lambda: False,
                           temp=lambda: 60, pub=self.pub, taskset=False,
                           signals_ok=lambda: (False, "signals are denied inside this container (DGO-1606)"))
        sup.start("owner")
        self.assertEqual(sup.tick(), "refused")
        self.assertIsNone(sup.proc)                       # nothing spawned that could never be stopped
        self.assertEqual(sup.state, g.OFF)
        self.assertIn("DGO-1606", sup.why)
        self.assertEqual(self.pub.events[-1][0], "device.failed")

    def test_a_stop_that_cannot_kill_keeps_the_process_and_says_it(self):
        self.sup.start("owner")
        self.sup.tick()
        pid = self.sup.proc.pid
        real = s.os.killpg

        def end_it():                                     # the stand-in ends even when an assert below fails
            try:
                real(pid, s.signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.addCleanup(end_it)

        def denied(p, sig):
            raise PermissionError(1, "Operation not permitted")
        s.os.killpg = denied
        try:
            self.sup.stop("asked")
        finally:
            s.os.killpg = real
        st = self.sup.status()
        self.assertEqual(st["state"], g.OFF)
        self.assertEqual(st["pid"], pid)                  # «off» with the pid: the process is still there
        self.assertIn("did not stop", st["why"])
        self.assertIn("Operation not permitted", st["why"])
        self.sup.start("again")                           # a new start does not spawn a second one over it
        self.assertEqual(self.sup.tick(), "refused")
        self.assertIn(f"pid {pid}", self.sup.why)
        self.assertEqual(self.sup.proc.pid, pid)
        real(pid, s.signal.SIGKILL)                        # the stand-in, ended for real
        self.sup.proc.wait(timeout=10)
        self.sup.start("after it ended by itself")        # the kept one is dropped: this start spawns (the reader's 1)
        self.assertEqual(self.sup.tick(), "start")
        self.assertNotEqual(self.sup.proc.pid, pid)

    def test_the_emulators_output_goes_to_its_log_new_each_start(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "emulator.log")
            with open(log, "w") as f:
                f.write("an older start\n")
            sup = s.Supervisor([sys.executable, "-c", "print('qemu says hello', flush=True); import time; "
                                                      "time.sleep(60)"], booted=lambda: False, temp=lambda: 60,
                               taskset=False, log=log)
            sup.start("owner")
            sup.tick()
            for _ in range(50):
                if os.path.getsize(log):
                    break
                time.sleep(0.1)
            sup.stop("test over")
            with open(log) as f:
                text = f.read()
            self.assertIn("qemu says hello", text)
            self.assertNotIn("an older start", text)


class StopsAndIdles(unittest.TestCase):
    """A running device asked to stop saves its snapshot first (quick boot); one nobody watches or uses stops by
    itself (the Dell's core and memory go back to the office). The clock is the test's."""

    def setUp(self):
        self.clock = [1000.0]
        self.asked = []
        self.temp = [60]
        self.pub = Pub()

    def make(self, ask_exit=None, idle_s=0, save_s=120):
        sup = s.Supervisor([sys.executable, "-c", "import time; time.sleep(60)"], booted=lambda: True,
                           temp=lambda: self.temp[0], pub=self.pub, taskset=False, ask_exit=ask_exit, idle_s=idle_s,
                           save_s=save_s, now=lambda: self.clock[0])
        self.addCleanup(lambda: sup.proc and sup.proc.poll() is None and sup.proc.kill())
        return sup

    def running(self, sup):
        sup.start("owner")
        self.assertEqual(sup.tick(), "start")
        sup.tick()
        self.assertEqual(sup.state, g.RUNNING)
        return sup

    def test_a_stop_saves_the_snapshot_and_ends_when_the_emulator_exits(self):
        sup = None

        def ask():                                    # the emulator, asked by `adb emu kill`, saves and exits
            self.asked.append(True)
            sup.proc.terminate()
            return True

        sup = self.running(self.make(ask_exit=ask))
        st = sup.stop()
        self.assertEqual((st["state"], self.asked), (g.STOPPING, [True]))
        self.assertEqual(self.pub.events[-1][0], "start")             # the bar stays open while it saves
        sup.proc.wait(timeout=10)
        self.assertEqual(sup.tick(), "stopped")
        self.assertEqual((sup.state, sup.code, sup.why), (g.OFF, "asked", "asked"))
        self.assertEqual(self.pub.events[-1][0], "ended")
        self.assertEqual((sup.status()["pid"], sup.status()["saved"]), (None, True))

    def test_a_save_that_runs_late_is_killed_says_so_and_a_start_asked_meanwhile_is_kept(self):
        sup = self.running(self.make(ask_exit=lambda: True, save_s=30))
        self.assertEqual(sup.stop()["state"], g.STOPPING)
        st = sup.start("check")                                     # no second emulator over a saving one…
        self.assertEqual((st["state"], st["again"]), (g.STOPPING, True))
        self.clock[0] += 10
        self.assertIsNone(sup.tick())
        self.clock[0] += 30
        self.assertEqual(sup.tick(), "stopped")
        self.assertEqual(self.pub.events[-1][0], "failed")          # the bar on «כל מקביל» says it, and why
        self.assertIn("not saved in 30 s", self.pub.events[-1][2])
        self.assertFalse(sup.saved)                                 # the screen will not say «saved»
        self.assertIsNone(sup.proc)
        self.assertEqual((sup.state, sup.asked_by), (g.WAITING, "check"))   # …but the start is not dropped

    def test_the_heat_rules_a_save_too(self):
        sup = self.running(self.make(ask_exit=lambda: True))
        sup.stop()
        self.temp[0] = 91
        self.assertEqual(sup.tick(), "stop")
        self.assertEqual((sup.state, sup.code, sup.saved), (g.OFF, "heat", False))
        self.assertIn("while saving", sup.why)
        self.assertEqual(sup.status()["temp"], 91)

    def test_an_emulator_that_cannot_be_asked_is_stopped_plainly_and_the_lock_is_free_meanwhile(self):
        seen = []
        sup = None

        def ask():                                    # the status answers while adb is being asked
            seen.append(sup.status()["state"])
            return False

        sup = self.running(self.make(ask_exit=ask))
        self.assertEqual(sup.stop()["state"], g.OFF)
        self.assertEqual((seen, sup.saved), ([g.STOPPING], False))

    def test_a_start_asked_while_a_stop_asks_in_vain_still_stands(self):
        sup = None

        def ask():                                    # a check asks for the device while adb is being asked
            sup.start("check")
            return False

        sup = self.running(self.make(ask_exit=ask))
        st = sup.stop()
        self.assertEqual((st["state"], st["asked_by"], st["again"]), (g.WAITING, "check", False))

    def test_stopping_a_device_that_never_ran_keeps_what_the_last_save_left(self):
        sup = None

        def ask():
            sup.proc.terminate()
            return True

        sup = self.running(self.make(ask_exit=ask))
        sup.stop()
        sup.proc.wait(timeout=10)
        sup.tick()
        self.assertTrue(sup.saved)
        self.temp[0] = 85                              # too hot to start: it waits, and is stopped while waiting
        sup.start("owner")
        self.assertEqual(sup.tick(), "wait")
        sup.stop()
        self.assertEqual((sup.state, sup.saved), (g.OFF, True))   # the snapshot is still there: say so

    def test_a_device_not_running_is_ended_at_once_and_one_not_asked_is_killed(self):
        sup = self.make(ask_exit=lambda: True)
        sup.start("owner")
        sup.tick()                                     # booting: nothing to save yet
        sup.booted = lambda: False
        sup.state = g.BOOTING
        self.assertEqual(sup.stop()["state"], g.OFF)
        refused = self.running(self.make(ask_exit=lambda: False))
        self.assertEqual(refused.stop()["state"], g.OFF)           # the emulator was not reached: a plain stop

    def test_nobody_watching_or_using_it_stops_it_and_a_use_keeps_it(self):
        sup = self.running(self.make(idle_s=1200))
        self.assertEqual(sup.status()["idle_in"], 1200)
        self.clock[0] += 1100
        sup.watch(+1)                                  # a display opened (or reconnected): counted, no use
        self.assertEqual((sup.status()["viewers"], sup.status()["idle_in"]), (1, 100))
        sup.touch()                                    # the display moved
        self.clock[0] += 1000
        sup.hold(+1)                                   # a verb of the door: in use for as long as it runs
        self.clock[0] += 5000
        self.assertIsNone(sup.tick())
        sup.hold(-1)
        self.clock[0] += 1199
        self.assertIsNone(sup.tick())
        self.assertEqual(sup.status()["idle_in"], 1)
        self.clock[0] += 1                             # an open display on which nothing moved is no use
        self.assertEqual(sup.tick(), "idle")           # …stopped from a thread of its own (the governor goes on)
        sup.idle_thread.join(30)                       # joined, never guessed: a loaded runner only takes longer
        self.assertFalse(sup.idle_thread.is_alive())
        self.assertEqual((sup.state, sup.code, sup.why), (g.OFF, "idle", "nobody used it for 20 minutes"))
        sup.watch(-1)
        self.assertEqual(sup.status()["viewers"], 0)

    def test_a_pause_for_the_heat_is_nobodys_idleness(self):
        sup = self.running(self.make(idle_s=1200))
        self.temp[0] = 86
        self.assertEqual(sup.tick(), "pause")
        self.clock[0] += 3000                          # paused for 50 minutes, its screen frozen
        self.temp[0] = 70
        self.assertEqual(sup.tick(), "resume")
        self.assertIsNone(sup.tick())                  # not stopped as idle two seconds after it came back
        self.assertEqual((sup.state, sup.status()["idle_in"]), (g.RUNNING, 1200))

    def test_an_idle_rule_of_zero_never_stops_it(self):
        sup = self.running(self.make(idle_s=0))
        self.clock[0] += 10 ** 6
        self.assertIsNone(sup.tick())
        self.assertEqual(sup.state, g.RUNNING)
        self.assertIsNone(sup.status()["idle_in"])
        sup.stop("test over")


if __name__ == "__main__":
    unittest.main()
