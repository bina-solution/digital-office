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


#: how long a test waits on an EVENT before it calls the code hung — never a measure of speed: every wait below ends
#: the moment its event happens, so a loaded runner only waits longer, it never fails (batch 49's red, 2026-11-13)
HANG = 30


class FakeSup:
    def __init__(self):
        self.state, self.asked = g.OFF, None
        self.viewers, self.touched, self.held = 0, 0, []
        self.closed = threading.Event()          # set when a display that opened has been counted closed again

    def status(self):
        return {"state": self.state, "asked_by": self.asked}

    def touch(self):
        self.touched += 1

    def hold(self, delta):
        self.held.append(delta)

    def watch(self, delta):
        self.viewers += delta
        if delta < 0 and self.viewers == 0:
            self.closed.set()

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
            with urllib.request.urlopen(req, timeout=HANG) as r:
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

    def test_a_device_verb_holds_the_device_for_as_long_as_it_runs(self):
        self.sup.state = g.RUNNING
        self.call("POST", "/api/shell", {"argv": ["true"]})
        self.call("POST", "/api/shell", {"argv": ["hang"], "timeout": 1})     # a verb that times out lets go too
        self.call("GET", "/api/screenshot")
        self.assertEqual(self.sup.held, [1, -1, 1, -1, 1, -1])
        self.call("GET", "/api/status")                  # asking how it is uses nothing
        self.assertEqual(self.sup.held, [1, -1, 1, -1, 1, -1])


class Tuning(unittest.TestCase):
    """Android's animations are switched off once per boot, outside the supervisor's lock (a thread)."""

    def test_once_per_boot_and_again_after_a_new_boot(self):
        said, up = [], [b"1"]

        def fake_adb(*args, timeout=30):
            if args[:2] == ("shell", "getprop"):
                return subprocess.CompletedProcess(args, 0, up[0], b"")
            said.append(args)
            return subprocess.CompletedProcess(args, 0, b"", b"")

        old = srv.adb
        srv.adb = fake_adb
        srv._tuned.clear()
        try:
            def settle():
                for t in [t for t in threading.enumerate() if t.name.startswith("Thread") and t.daemon]:
                    t.join(timeout=5)
            self.assertTrue(srv.booted()); settle()
            self.assertTrue(srv.booted()); settle()
            self.assertEqual(said, [("shell", "settings", "put", "global", k, "0") for k in srv.ANIMATIONS])   # once
            up[0] = b""
            self.assertFalse(srv.booted())                                       # off: the next boot is tuned again
            up[0] = b"1"
            self.assertTrue(srv.booted()); settle()
            self.assertEqual(len(said), 2 * len(srv.ANIMATIONS))
            # a put that fails (settings not yet up): the next poll tries again
            said.clear(); srv._tuned.clear(); fail = [True]
            def failing_adb(*args, timeout=30):
                if args[:2] == ("shell", "getprop"):
                    return subprocess.CompletedProcess(args, 0, b"1", b"")
                said.append(args)
                return subprocess.CompletedProcess(args, 1 if fail[0] else 0, b"", b"")
            srv.adb = failing_adb
            srv.booted(); settle()
            self.assertEqual(len(said), 1)                                       # stopped at the first failure
            fail[0] = False
            srv.booted(); settle()
            self.assertEqual(len(said), 1 + len(srv.ANIMATIONS))                # …and tried again, all three
        finally:
            srv.adb = old
            srv._tuned.clear()


class FakeWebsockify:
    """A stand-in for websockify: answers the upgrade with 101, then echoes every byte back."""

    def __init__(self):
        import socket
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(4)
        self.addr = self.srv.getsockname()
        self.heads = []
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self.one, args=(c,), daemon=True).start()

    def one(self, c):
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = c.recv(4096)
            if not chunk:
                return c.close()
            data += chunk
        head, rest = data.split(b"\r\n\r\n", 1)
        self.heads.append(head.decode("latin-1"))
        c.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n" + rest)
        while True:
            chunk = c.recv(4096)
            if not chunk:
                break
            c.sendall(chunk)
        c.close()

    def close(self):
        # shutdown first: on Linux a close() does not wake the thread blocked in accept(), and the port went on
        # ACCEPTING (batch 49's red: the «not answering» case got a 101 on the runner, never on macOS)
        import socket
        try:
            self.srv.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.srv.close()


class TheScreen(unittest.TestCase):
    """The tile's door (:6080): the screen, noVNC's files under a guard, the display's websocket spliced through, and
    only status/start/stop of the API — never install, shell or the drop folder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.screen, self.novnc = os.path.join(base, "screen"), os.path.join(base, "novnc")
        os.makedirs(os.path.join(self.novnc, "core"))
        os.makedirs(self.screen)
        with open(os.path.join(self.screen, "index.html"), "w") as f:
            f.write("<!doctype html><title>the screen</title>")
        with open(os.path.join(self.novnc, "core", "rfb.js"), "w") as f:
            f.write("export default class RFB {}")
        with open(os.path.join(base, "secret.txt"), "w") as f:
            f.write("outside")
        self.sup = FakeSup()
        self.ws = FakeWebsockify()
        self.http = srv.ThreadingHTTPServer(("127.0.0.1", 0), srv.screen_handler_for(
            self.sup, upstream=self.ws.addr, novnc=self.novnc, screen=self.screen))
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.port = self.http.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.http.shutdown()
        self.ws.close()
        self.tmp.cleanup()

    def get(self, path, method="GET", headers=None):
        req = urllib.request.Request(self.url + path, method=method, headers=headers or {},
                                     data=b"{}" if method == "POST" else None)
        try:
            with urllib.request.urlopen(req, timeout=HANG) as r:
                return r.status, r.headers.get("Content-Type"), r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Content-Type"), e.read()

    def test_the_screen_and_novncs_files_and_nothing_outside_them(self):
        code, kind, body = self.get("/")
        self.assertEqual((code, kind), (200, "text/html; charset=utf-8"))
        self.assertIn(b"the screen", body)
        code, kind, body = self.get("/vnc/core/rfb.js")
        self.assertEqual((code, kind), (200, "text/javascript; charset=utf-8"))   # a module script needs its type
        for bad in ("/vnc/../secret.txt", "/vnc/%2e%2e/secret.txt", "/vnc//etc/passwd", "/vnc/core"):
            self.assertEqual(self.get(bad)[0], 404, bad)

    def test_status_start_stop_only_and_who_asked_is_the_signed_in_person(self):
        # the edge writes the name's UTF-8 bytes; http.client (like any header reader) carries them as latin-1
        code, _k, body = self.get("/api/start", "POST", {"X-authentik-name": "ישראל".encode().decode("latin-1")})
        self.assertEqual((code, json.loads(body)["asked_by"]), (202, "ישראל"))
        self.assertEqual(json.loads(self.get("/api/status")[2])["state"], g.WAITING)
        self.assertEqual(json.loads(self.get("/api/stop", "POST")[2])["state"], g.OFF)
        self.assertEqual(json.loads(self.get("/api/start", "POST")[2])["asked_by"], "המסך")
        for path, method in (("/api/install", "POST"), ("/api/shell", "POST"), ("/api/log", "GET"),
                             ("/api/apks/dgo.apk?bytes=2", "GET"), ("/api/screenshot", "GET")):
            self.assertEqual(self.get(path, method)[0], 404, path)

    def test_a_body_the_screen_never_sends_is_refused_and_not_kept_alive(self):
        import socket
        for length, want in (("5000", b"413"), ("-1", b"400"), ("x", b"400")):
            c = socket.create_connection(("127.0.0.1", self.port), timeout=HANG)
            c.sendall(f"POST /api/start HTTP/1.1\r\nHost: x\r\nContent-Length: {length}\r\n\r\n".encode() + b"{}")
            got = b""
            while True:                                          # the door closes it: no stray body as a request
                chunk = c.recv(4096)
                if not chunk:
                    break
                got += chunk
            self.assertTrue(got.startswith(b"HTTP/1.1 " + want), (length, got[:60]))
            c.close()
        self.assertEqual(self.sup.state, g.OFF)                   # none of them started anything

    def test_the_displays_websocket_is_carried_both_ways_and_counted(self):
        import socket
        c = socket.create_connection(("127.0.0.1", self.port), timeout=HANG)
        c.sendall(b"GET /websockify?token=x HTTP/1.1\r\nHost: android-emulator\r\nUpgrade: websocket\r\n"
                  b"Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                  b"Sec-WebSocket-Version: 13\r\n\r\n")
        got = b""
        while b"\r\n\r\n" not in got:
            got += c.recv(4096)
        self.assertTrue(got.startswith(b"HTTP/1.1 101"), got)
        c.sendall(b"\x82\x05hello")
        echo = b""
        while len(echo) < 7:
            echo += c.recv(4096)
        self.assertEqual(echo, b"\x82\x05hello")
        self.assertEqual(self.sup.viewers, 1)
        # no wait: the echo is sent by the same pump thread that said «used» right after it sent the 101, so an
        # echo received is a use already counted (an ORDER, not a race)
        self.assertGreaterEqual(self.sup.touched, 1)
        head = self.ws.heads[0]
        self.assertTrue(head.startswith("GET /websockify?token=x HTTP/1.1"), head)
        self.assertIn("Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==", head)
        c.close()
        self.assertTrue(self.sup.closed.wait(HANG), "the display was never counted closed")
        self.assertEqual(self.sup.viewers, 0)

    def test_a_display_that_is_not_answering_is_said(self):
        # «not answering», the same on every OS: a port BOUND and never listening — a connect to it is refused at
        # once, by the kernel, with nothing to wait for (a closed listener went on accepting on Linux: batch 49's red)
        import socket
        dead = socket.socket()
        dead.bind(("127.0.0.1", 0))
        self.addCleanup(dead.close)
        http = srv.ThreadingHTTPServer(("127.0.0.1", 0), srv.screen_handler_for(
            self.sup, upstream=dead.getsockname(), novnc=self.novnc, screen=self.screen))
        threading.Thread(target=http.serve_forever, daemon=True).start()
        self.addCleanup(http.shutdown)
        c = socket.create_connection(("127.0.0.1", http.server_address[1]), timeout=HANG)
        c.sendall(b"GET /websockify HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
        got = c.recv(4096)
        self.assertTrue(got.startswith(b"HTTP/1.1 502"), got)
        self.assertTrue(self.sup.closed.wait(HANG), "never counted closed")   # counted down after the answer
        self.assertEqual(self.sup.viewers, 0)
        c.close()


if __name__ == "__main__":
    unittest.main()
