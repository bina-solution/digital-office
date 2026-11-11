#!/usr/bin/env python3
"""test_check — install-check on the office's device, against a scripted door (DGO-1797, package 12): a first
install, a refused one, the status screen's words, the machine followed to its 20 minutes, a device the heat
stops, and the rule that the check stops only a device it started. Also device.py's wait and put against a real
HTTP door (server.py with a fake adb).

    python3 apps/android-emulator/test_check.py      (G72 runs it; standard library only)
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "server"))
import check  # noqa: E402
import device  # noqa: E402

STATUS_XML = ('<hierarchy><node text="הלשכה הדיגיטלית"/><node text="הבסיס · מוכן"/><node text="מכולות"/>'
              '<node text="פתיחת הלשכה"/></hierarchy>')


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeDoor:
    """The door's verbs over a scripted device: `answers` maps a command's first word (or a prefix) to its output."""

    def __init__(self, clock, state="off", install_said="Success", qemu_from_min=3, stop_at_min=None,
                 qemu_until_min=10 ** 6):
        self.clock, self.state, self.install_said = clock, state, install_said
        self.qemu_from, self.stop_at, self.pauses, self.qemu_until = qemu_from_min, stop_at_min, 0, qemu_until_min
        self.calls, self.stopped, self.why = [], False, ""

    def minute(self):
        return int(self.clock() // 60)

    def status(self):
        if self.stop_at is not None and self.minute() >= self.stop_at:
            self.state, self.why = "off", "91°C: the 90°C limit"
        return {"state": self.state, "why": self.why, "temp": 70, "asked_by": "owner"}

    def start(self, by):
        self.calls.append(("start", by))
        self.state = "booting"

    def wait(self, limit_s):
        if self.state == "off":
            raise device.DeviceError("the device stopped: off")
        self.state = "running"
        return {"state": "running"}

    def stop(self):
        self.calls.append(("stop",))
        self.stopped, self.state = True, "off"

    def put(self, path):
        self.calls.append(("put", os.path.basename(path)))
        return {"bytes": os.path.getsize(path), "sha256": "ab" * 32}

    def remove(self, name):
        self.calls.append(("remove", name))
        return True

    def install(self, name):
        self.calls.append(("install", name))
        return self.install_said == "Success", self.install_said

    def shell(self, cmd, timeout=60):
        self.calls.append(("shell", cmd))
        if self.status()["state"] == "off":
            raise device.DeviceError("the device is not running")
        if cmd.startswith("pidof"):
            return 0, "4242\n"
        if cmd.startswith("uiautomator"):
            return 0, STATUS_XML
        if cmd.startswith("ps -A"):
            return 0, "init\n" + ("app /data/app/x/lib/arm64/libqemu-system-aarch64.so\n"
                                  if self.qemu_from <= self.minute() < self.qemu_until else "")
        if cmd == "df -k /data":
            return 0, "Filesystem 1K-blocks Used Available Use% Mounted\n/dev/block/dm-5 20000000 3000000 17000000 15% /data\n"
        if cmd.startswith("cat /proc/net/dev"):
            return 0, "Inter-| Receive\n lo: 999999999 1 0\n eth0: 2097152 10 0\n"
        return 0, ""

    def screenshot(self):
        return b"\x89PNG shot"


class CheckFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.apk = os.path.join(self.tmp.name, "dgo-0.2.112.apk")
        with open(self.apk, "wb") as f:
            f.write(b"PK\x03\x04")
        self.out = os.path.join(self.tmp.name, "out")
        os.makedirs(self.out)
        self.clock, self.lines = Clock(), []

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, door, **asked):
        c = check.Check(door, self.out, "77", say=self.lines.append, sleep=self.clock.sleep, clock=self.clock)
        return c.run_all(self.apk, "install-check 77", asked.get("status", False), asked.get("machine", False))

    def said(self):
        return "\n".join(self.lines)

    def test_a_first_install_on_a_device_it_started_and_then_stopped(self):
        door = FakeDoor(self.clock)
        self.assertEqual(self.run_check(door, status=True), 0, self.said())
        # removed before it is put and installed: the office's device keeps data between checks
        uninstall = next(i for i, c in enumerate(door.calls) if c[0] == "shell" and c[1].startswith("pm uninstall"))
        self.assertLess(uninstall, door.calls.index(("put", "dgo-0.2.112.apk")))
        self.assertEqual([f for f in os.listdir(self.out) if f.startswith(".")], [])   # its marks undone
        self.assertIn(("install", "dgo-0.2.112.apk"), door.calls)
        self.assertEqual(door.calls[0], ("start", "install-check 77"))
        self.assertTrue(door.stopped)
        self.assertTrue(os.path.isfile(os.path.join(self.out, "check-77-status.png")))
        self.assertIn("פתיחת הלשכה", open(os.path.join(self.out, "check-77-status.xml"), encoding="utf-8").read())
        self.assertIn("the app is running", self.said())

    def test_a_device_someone_else_runs_is_used_as_it_is_never_wiped_and_left_on(self):
        door = FakeDoor(self.clock, state="running")
        self.assertEqual(self.run_check(door), 0, self.said())
        self.assertFalse(door.stopped)
        self.assertNotIn("start", [c[0] for c in door.calls])
        self.assertFalse([c for c in door.calls if c[0] == "shell" and c[1].startswith("pm uninstall")])
        self.assertIn("::warning::the device is already running", self.said())
        # and the machine — a first open's — is refused there, with what to do
        self.lines.clear()
        self.assertEqual(self.run_check(FakeDoor(self.clock, state="running"), machine=True), 1)
        self.assertIn("a device someone else runs is not wiped", self.said())

    def test_a_killed_check_is_undone_by_its_marks(self):
        with open(os.path.join(self.out, ".put"), "w") as f:
            f.write("dgo-0.2.112.apk\n")
        open(os.path.join(self.out, ".started"), "w").close()
        door = FakeDoor(self.clock, state="running")
        check.undo(door, self.out, self.lines.append)
        self.assertEqual((door.calls, door.stopped), ([("remove", "dgo-0.2.112.apk"), ("stop",)], True))
        self.assertEqual(os.listdir(self.out), [])
        door = FakeDoor(self.clock, state="running")   # nothing marked: nothing touched
        check.undo(door, self.out, self.lines.append)
        self.assertEqual(door.calls, [])

    def test_a_reading_the_device_did_not_answer_is_unread_not_the_app_gone(self):
        door = FakeDoor(self.clock, qemu_from_min=3)
        real = door.shell

        def slow(cmd, timeout=60):
            if 5 <= door.minute() < 7 and (cmd.startswith("ps") or cmd.startswith("pidof")):
                raise device.NoAnswer("the device did not answer in 30 s")
            return real(cmd, timeout)
        door.shell = slow
        self.assertEqual(self.run_check(door, machine=True), 0, self.said())
        self.assertIn("the app's QEMU unread", self.said())
        self.assertIn("--- the app's last lines", self.said())

    def test_the_door_gone_at_the_end_never_replaces_the_outcome(self):
        door = FakeDoor(self.clock, qemu_from_min=3)
        real = door.shell

        def gone_at_the_end(cmd, timeout=60):
            if cmd.startswith("logcat -d") and door.minute() >= 23:
                raise ConnectionRefusedError(61, "Connection refused")
            return real(cmd, timeout)
        door.shell = gone_at_the_end
        self.assertEqual(self.run_check(door, machine=True), 0, self.said())
        self.assertIn("(none read)", self.said())

    def test_a_pause_that_never_ends_ends_the_follow_and_says_so(self):
        door = FakeDoor(self.clock, qemu_from_min=999)
        real = door.status

        def hot():
            st = real()
            if door.minute() >= 4 and st["state"] != "off":
                st["state"] = "paused"
            return st
        door.status = hot
        self.assertEqual(self.run_check(door, machine=True), 1)
        self.assertIn("paused for the heat 30 min", self.said())

    def test_a_mark_whose_act_failed_stays_for_the_next_cleanup(self):
        with open(os.path.join(self.out, ".put"), "w") as f:
            f.write("dgo-0.2.112.apk\n")
        door = FakeDoor(self.clock, state="running")
        door.remove = lambda name: False
        check.undo(door, self.out, self.lines.append)
        self.assertEqual(os.listdir(self.out), [".put"])
        self.assertIn("was not removed", self.said())

    def test_one_qemu_process_is_one_however_often_its_line_names_it(self):
        door = FakeDoor(self.clock)
        door.shell = lambda cmd, timeout=60: (0, "libqemu-system-aarch64.so /data/app/x/libqemu-system-aarch64.so -m 2048\n")
        c = check.Check(door, self.out, "77", say=self.lines.append, sleep=self.clock.sleep, clock=self.clock)
        self.assertEqual(c.qemu(), 1)

    def test_a_refused_install_says_why_and_still_stops_the_device(self):
        door = FakeDoor(self.clock, install_said="Failure [INSTALL_FAILED_NO_MATCHING_ABIS: x86_64]")
        self.assertEqual(self.run_check(door), 1)
        self.assertIn("::error::adb install refused dgo-0.2.112.apk: Failure [INSTALL_FAILED_NO_MATCHING_ABIS",
                      self.said())
        self.assertTrue(door.stopped)
        self.assertIn(("remove", "dgo-0.2.112.apk"), door.calls)   # a failed check removes its APK too

    def test_the_status_screen_must_say_the_office_and_not_the_old_words(self):
        self.assertIsNone(check.status_verdict(check.screen_texts(STATUS_XML)))
        self.assertIn("does not say ['מכולות']", check.status_verdict(["הלשכה הדיגיטלית", "הבסיס", "פתיחת הלשכה"]))
        self.assertIn("still says ['מנוע:']",
                      check.status_verdict(["הלשכה הדיגיטלית", "הבסיס", "מכולות", "פתיחת הלשכה", "מנוע: x"]))
        self.assertEqual(check.screen_texts("<not xml"), [])

    def test_the_machine_is_followed_until_its_qemu_ran_twenty_minutes(self):
        door = FakeDoor(self.clock, qemu_from_min=3)
        self.assertEqual(self.run_check(door, machine=True), 0, self.said())
        self.assertIn("QEMU started at", self.said())
        shots = sorted(f for f in os.listdir(self.out) if f.endswith("min.png"))
        self.assertGreaterEqual(len(shots), 4, shots)   # one every 5 minutes, and the last
        self.assertIn("received 2 MB", self.said())     # lo is not the device's network

    def test_a_qemu_that_ends_before_its_twenty_minutes_fails_the_check(self):
        door = FakeDoor(self.clock, qemu_from_min=3, qemu_until_min=9)
        self.assertEqual(self.run_check(door, machine=True), 1)
        self.assertRegex(self.said(), r"the app's QEMU ended at 1[01] min, [78] min after it started")

    def test_a_device_the_heat_stops_fails_the_check_and_says_so(self):
        door = FakeDoor(self.clock, qemu_from_min=999, stop_at_min=7)
        self.assertEqual(self.run_check(door, machine=True), 1)
        self.assertIn("91°C: the 90°C limit", self.said())

    def test_too_small_a_data_partition_is_named_before_the_machine_is_awaited(self):
        door = FakeDoor(self.clock)
        real = door.shell
        door.shell = lambda cmd, timeout=60: (0, "F 1K U A\n/d 8000000 3000000 5000000 40% /data\n") \
            if cmd == "df -k /data" else real(cmd, timeout)
        self.assertEqual(self.run_check(door, machine=True), 1)
        self.assertIn("ANDROID_EMULATOR_PARTITION_MB=20480", self.said())

    def test_readings(self):
        self.assertEqual(check.net_rx_mb(" lo: 99999999 0\n wlan0: 1048576 0\n eth0: 1048576 0\nbad: x\n"), 2)
        self.assertAlmostEqual(check.df_column_gb("h\n/d 1 2097152 3\n", 2), 2.0)
        self.assertIsNone(check.df_column_gb("only a header\n", 2))


class DeviceAgainstTheDoor(unittest.TestCase):
    """device.Door over a real HTTP door: put compares the digest; a paused device is waited for, not retried."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location("emu_server", os.path.join(HERE, "server", "server.py"))
        self.srv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.srv)
        self.tmp = tempfile.TemporaryDirectory()
        self.srv.APKS = os.path.realpath(self.tmp.name)
        g = self.srv.g
        # paused for the heat, then booting again after the resume (supervisor.tick), then running
        self.states = [g.PAUSED, g.PAUSED, g.BOOTING, g.RUNNING]

        self.srv_why = ""

        class Sup:
            def status(inner):
                return {"state": self.states[0] if len(self.states) == 1 else self.states.pop(0), "why": self.srv_why}

        def fake_adb(*args, timeout=30):
            if "hang" in args:
                raise subprocess.TimeoutExpired(args, timeout)
            return subprocess.CompletedProcess(args, 0, b"Success" if args[0] == "install" else b"1\n", b"")

        self.http = self.srv.ThreadingHTTPServer(("127.0.0.1", 0), self.srv.handler_for(Sup(), fake_adb))
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.clock = Clock()
        self.door = device.Door(f"http://127.0.0.1:{self.http.server_address[1]}", sleep=self.clock.sleep,
                                clock=self.clock, say=lambda s: None)

    def tearDown(self):
        self.http.shutdown()
        self.tmp.cleanup()

    def test_put_then_install_and_a_paused_device_is_waited_for(self):
        apk = os.path.join(self.tmp.name, "src.apk")
        with open(apk, "wb") as f:
            f.write(os.urandom(3 << 20))           # more than one chunk
        ans = self.door.put(apk)
        self.assertEqual(ans["bytes"], 3 << 20)
        ok, said = self.door.install("src.apk")   # the first two answers are «paused»: waited for, then done
        self.assertEqual((ok, said), (True, "Success"))
        self.assertGreaterEqual(self.door.pauses, 1)
        self.assertGreaterEqual(self.clock.t, 5)  # waited through wait()'s polls — never asked again at once
        self.assertEqual(self.door.pauses, 1)     # one pause, counted once
        self.assertEqual(self.door.shell("getprop", "sys.boot_completed"), (0, "1\n"))
        with self.assertRaises(device.NoAnswer):
            self.door.shell("hang", timeout=1)

    def test_a_device_that_stopped_says_why_to_its_caller(self):
        self.states = [self.srv.g.OFF]
        self.srv_why = "91°C: the 90°C limit"
        with self.assertRaises(device.DeviceError) as e:
            self.door.shell("pidof", "x")
        self.assertIn("91°C: the 90°C limit", str(e.exception))

    def test_a_device_booting_again_after_a_resume_is_waited_for(self):
        self.states = [self.srv.g.BOOTING, self.srv.g.BOOTING, self.srv.g.RUNNING]
        self.assertEqual(self.door.shell("pidof", "x"), (0, "1\n"))
        self.assertGreaterEqual(self.clock.t, 5)

    def test_the_doors_refusal_reaches_the_client_in_its_own_words(self):
        os.makedirs(os.path.join(self.tmp.name, "src"))
        apk = os.path.join(self.tmp.name, "src", "big.apk")   # outside the drop folder (APKS is tmp itself)
        with open(apk, "wb") as f:
            f.write(b"PK" * (8 << 20))   # 16 MiB: past the socket's buffers, where a refused PUT is a closed pipe
        keep = self.srv.ROOM_LEFT
        try:
            self.srv.ROOM_LEFT = 1 << 62
            with self.assertRaises(device.DeviceError) as e:
                self.door.put(apk)
            self.assertIn("no room", str(e.exception))
        finally:
            self.srv.ROOM_LEFT = keep
        self.assertFalse(os.path.exists(os.path.join(self.srv.APKS, "big.apk")))

    def test_the_cli_says_why_and_exits_one_when_the_door_refuses(self):
        self.states = [self.srv.g.OFF]
        rc = device.main(["--door", self.door.base, "install", "nosuch.apk"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
