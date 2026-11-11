#!/usr/bin/env python3
"""test_server — the emulator app's door: status, start, stop, install from the drop folder only, a screenshot
only of a running device (DGO-1797, package 11).

    python3 apps/android-emulator/test_server.py      (G72 runs it; standard library only)
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "server"))
spec = importlib.util.spec_from_file_location("emu_server", os.path.join(HERE, "server", "server.py"))
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)
g = srv.g


class FakeSup:
    def __init__(self):
        self.state, self.asked = g.OFF, None

    def status(self):
        return {"state": self.state, "asked_by": self.asked}

    def start(self, by):
        self.state, self.asked = g.WAITING, by
        return self.status()

    def stop(self, why):
        self.state = g.OFF
        return self.status()


class Door(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        srv.APKS = os.path.realpath(self.tmp.name)
        with open(os.path.join(srv.APKS, "dgo.apk"), "wb") as f:
            f.write(b"PK")
        self.sup, self.calls = FakeSup(), []

        def fake_adb(*args, timeout=30):
            self.calls.append(args)
            if "hang" in args:
                raise subprocess.TimeoutExpired(args, timeout)
            out = b"\x89PNG fake" if args[:2] == ("exec-out", "screencap") else b"Success"
            return subprocess.CompletedProcess(args, 0, out, b"")

        self.http = srv.ThreadingHTTPServer(("127.0.0.1", 0), srv.handler_for(self.sup, fake_adb))
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.http.server_address[1]}"

    def tearDown(self):
        self.http.shutdown()
        self.tmp.cleanup()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.url + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_the_emulators_log_is_its_tail_and_none_is_said(self):
        self.sup.log = os.path.join(self.tmp.name, "emulator.log")
        code, body = self.call("GET", "/api/log")
        self.assertEqual(code, 404)
        self.assertIn(b"no emulator log yet", body)
        with open(self.sup.log, "wb") as f:
            f.write(b"x" * (srv.LOG_TAIL + 10) + b"\nthe last line\n")
        code, body = self.call("GET", "/api/log")
        self.assertEqual(code, 200)
        self.assertEqual(len(body), srv.LOG_TAIL)          # the tail, not the whole file
        self.assertTrue(body.endswith(b"the last line\n"))

    def test_start_status_stop(self):
        code, body = self.call("POST", "/api/start", {"by": "owner"})
        self.assertEqual((code, json.loads(body)["state"], json.loads(body)["asked_by"]), (202, g.WAITING, "owner"))
        self.assertEqual(json.loads(self.call("GET", "/api/status")[1])["state"], g.WAITING)
        self.assertEqual(json.loads(self.call("POST", "/api/stop")[1])["state"], g.OFF)

    def test_install_and_screenshot_only_on_a_running_device_and_only_from_the_drop_folder(self):
        self.assertEqual(self.call("POST", "/api/install", {"apk": "dgo.apk"})[0], 409)
        self.assertEqual(self.call("GET", "/api/screenshot")[0], 409)
        self.sup.state = g.RUNNING
        code, body = self.call("POST", "/api/install", {"apk": "dgo.apk"})
        self.assertEqual((code, json.loads(body)["ok"]), (200, True))
        self.assertEqual(self.calls[-1], ("install", "-r", os.path.join(srv.APKS, "dgo.apk")))
        for bad in ("../../etc/passwd", "/etc/hosts", "nosuch.apk", "", None):
            self.assertEqual(self.call("POST", "/api/install", {"apk": bad})[0], 400, bad)
        code, png = self.call("GET", "/api/screenshot")
        self.assertEqual((code, png[:4]), (200, b"\x89PNG"))

    def test_an_apk_is_stored_whole_by_a_plain_name_or_not_at_all(self):
        req = urllib.request.Request(self.url + "/api/apks/dgo-0.2.112.apk", data=b"PK\x03\x04apk", method="PUT")
        with urllib.request.urlopen(req, timeout=5) as r:
            doc = json.loads(r.read())
        self.assertEqual((r.status, doc["bytes"], doc["sha256"]), (201, 7, hashlib.sha256(b"PK\x03\x04apk").hexdigest()))
        with open(os.path.join(srv.APKS, "dgo-0.2.112.apk"), "rb") as f:
            self.assertEqual(f.read(), b"PK\x03\x04apk")
        for bad in ("../x.apk", ".hidden.apk", "a/b.apk", "x.zip", "x%2F..%2Fy.apk"):
            req = urllib.request.Request(self.url + "/api/apks/" + bad, data=b"PK", method="PUT")
            with self.assertRaises(urllib.error.HTTPError, msg=bad) as e:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(e.exception.code, 400, bad)
        # a body that ends early leaves nothing behind, under either name
        chunks = [b"PK", b""]
        code, doc = srv.store_apk("cut.apk", 10, lambda n: chunks.pop(0), srv.APKS)
        self.assertEqual(code, 400)
        self.assertEqual(sorted(os.listdir(srv.APKS)), ["dgo-0.2.112.apk", "dgo.apk"])
        # asked first: may a PUT of N bytes be kept — the same rule the PUT applies
        code, body = self.call("GET", "/api/apks/next.apk?bytes=10")
        self.assertEqual((code, json.loads(body)), (200, {"apk": "next.apk", "may": True, "exists": False}))
        self.assertEqual(self.call("GET", f"/api/apks/next.apk?bytes={srv.APK_MAX + 1}")[0], 413)
        self.assertEqual(self.call("GET", "/api/apks/..%2Fx.apk?bytes=10")[0], 400)
        self.assertEqual(json.loads(self.call("GET", "/api/apks/dgo.apk?bytes=10")[1])["exists"], True)
        self.assertEqual(srv.store_apk("big.apk", srv.APK_MAX + 1, None, srv.APKS)[0], 413)
        self.assertEqual(srv.store_apk("empty.apk", 0, None, srv.APKS)[0], 413)
        keep = srv.ROOM_LEFT
        try:
            srv.ROOM_LEFT = 1 << 62
            self.assertEqual(srv.store_apk("room.apk", 2, None, srv.APKS)[0], 507)
        finally:
            srv.ROOM_LEFT = keep

    def test_an_apk_is_removed_by_its_plain_name_only(self):
        self.assertEqual(json.loads(self.call("DELETE", "/api/apks/dgo.apk")[1]), {"apk": "dgo.apk", "removed": True})
        self.assertFalse(os.path.exists(os.path.join(srv.APKS, "dgo.apk")))
        self.assertEqual(json.loads(self.call("DELETE", "/api/apks/dgo.apk")[1])["removed"], False)
        for bad in ("../x.apk", "x.zip", ""):
            self.assertEqual(self.call("DELETE", "/api/apks/" + bad)[0], 404, bad)

    def test_the_device_shell_is_bounded_and_only_on_a_running_device(self):
        self.assertEqual(self.call("POST", "/api/shell", {"argv": ["getprop"]})[0], 409)
        self.sup.state = g.PAUSED
        code, body = self.call("POST", "/api/shell", {"argv": ["getprop"]})
        self.assertEqual(code, 409)
        self.assertIn("heat", json.loads(body)["error"])
        self.sup.state = g.RUNNING
        code, body = self.call("POST", "/api/shell", {"argv": ["getprop", "sys.boot_completed"]})
        self.assertEqual((code, json.loads(body)["rc"], json.loads(body)["out"]), (200, 0, "Success"))
        self.assertEqual(self.calls[-1], ("shell", "getprop", "sys.boot_completed"))
        for bad in (None, [], "getprop", [1], ["x"] * (srv.SHELL_ARGS + 1), ["x" * (srv.SHELL_CHARS + 1)]):
            self.assertEqual(self.call("POST", "/api/shell", {"argv": bad})[0], 400, bad)
        self.assertEqual(srv.shell_argv({"argv": ["a"], "timeout": 10 ** 6})[1], srv.SHELL_MAX_S)
        self.assertEqual(srv.shell_argv({"argv": ["a"], "timeout": True})[1], 60)
        self.assertEqual(srv.shell_argv({"argv": ["a"], "timeout": -5})[1], 1)
        # a device that does not answer in time is a 504 that says so, not a dropped connection
        code, body = self.call("POST", "/api/shell", {"argv": ["hang"], "timeout": 1})
        self.assertEqual(code, 504)
        self.assertIn("did not answer", json.loads(body)["error"])

    def test_unknown_is_404_and_health_answers(self):
        self.assertEqual(self.call("GET", "/nope")[0], 404)
        self.assertEqual(self.call("GET", "/healthz")[0], 200)


if __name__ == "__main__":
    unittest.main()
