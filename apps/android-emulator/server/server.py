"""server.py — the emulator app's door (DGO-1797, package 11): the screen, the CLI hooks and a CI job ask HERE.

    GET  /api/status                → {state, asked_by, since, temp, pid, why} (a pid while off: a stop that failed)
    GET  /api/log                   → the emulator's own output since its last start, the last 64 KB
    POST /api/start   {"by": "..."} → 202 and the state: waiting for the heat, then booting
    POST /api/stop                  → the state (off)
    GET  /api/apks/<name>.apk?bytes=N → 200 when a PUT of N bytes would be kept, else why not (ask first)
    PUT  /api/apks/<name>.apk       → the body stored in /apks (the app's drop folder): {apk, bytes, sha256}
    DELETE /api/apks/<name>.apk     → removed from the drop folder (a check removes what it put: ~1 GB each)
    POST /api/install {"apk": "..."}→ adb install -r of an APK under /apks, its answer
    POST /api/shell {"argv": [...], "timeout": s} → adb shell on the device: {rc, out, cut}. adb joins argv
                                      with spaces and the device's sh runs the line: one string may be a pipeline
    GET  /api/screenshot            → the device's screen as PNG (adb exec-out screencap -p)
    GET  /healthz                   → ok

The device's verbs answer 409 unless it is running — paused for the heat included: wait, do not retry at once.
Each of them (install, shell, a screenshot) is a use of the device: the idle rule's clock starts again.

THE SCREEN is a second, narrower door on :6080 — the one the console's tile frames (app.json routing), and the
only one a browser reaches (behind the office's sign-in, admins only):

    GET  /                          → the app's screen (screen/index.html): the state, why, the heat, start/stop
                                      and the live display
    GET  /vnc/<file>                → noVNC's own files (the image's /usr/share/novnc): the display's client
    GET  /websockify                → the display's websocket, spliced to websockify (127.0.0.1:6081 → Xvnc :5901);
                                      while one is open the device counts as watched (Supervisor.watch)
    GET  /api/status, POST /api/start, POST /api/stop   → as above; nothing else of the door

Before (DGO-1797 pkg 11 to 2026-11-12) the tile was websockify's noVNC alone: with the device off it was a black
desktop — no state, no reason, no way to start it — and the owner read it as «the emulator does not work».

The governor turns every two seconds in a thread of its own (Supervisor.tick). One emulator at a time — the
office's, not a per-request one; who asked is on the status and on the flow's bar. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/opt/dgo")                       # the office's flow publisher, mounted read-only

import governor as g                                 # noqa: E402
from supervisor import Supervisor                    # noqa: E402

PORT = int(os.environ.get("EMU_PORT", "8080"))
AVD = os.environ.get("EMU_AVD", "dgo")
MEMORY_MB = int(os.environ.get("EMU_MEMORY_MB") or "3072")
PARTITION_MB = int(os.environ.get("EMU_PARTITION_MB") or "8192")
APKS = os.path.realpath(os.environ.get("EMU_APKS", "/apks"))
AVD_DIR = "/root/.android/avd"                       # the android_emulator_avd volume (compose)
EMU_LOG = os.environ.get("EMU_LOG") or os.path.join(AVD_DIR, "emulator.log")   # its own output, new each start
LOG_TAIL = 64 << 10                                  # GET /api/log: the last 64 KB
TICK_S = 2.0
APK_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.apk")
APK_MAX = 3 << 30                                    # the app's APK is ~1 GB; three is room, not a disk
ROOM_LEFT = 1 << 30                                  # what a stored APK leaves free on the drop folder's disk
SHELL_ARGS, SHELL_CHARS, SHELL_MAX_S = 64, 8192, 300
INSTALL_MAX_S = 1800
OUT_MAX = 1 << 20                                    # an answer's last MiB (a whole logcat is the caller's grep)
SCREEN_PORT = int(os.environ.get("EMU_SCREEN_PORT") or "6080")    # the tile's port (app.json routing)
VNC_WS = ("127.0.0.1", int(os.environ.get("EMU_VNC_WS_PORT") or "6081"))   # websockify, inside the container only
NOVNC_DIR = os.path.realpath(os.environ.get("EMU_NOVNC") or "/usr/share/novnc")
SCREEN_DIR = os.path.realpath(os.environ.get("EMU_SCREEN")
                              or os.path.join(os.path.dirname(os.path.abspath(__file__)), "screen"))
IDLE_STOP_MIN = int(os.environ.get("EMU_IDLE_STOP_MIN") or g.IDLE_STOP_MIN)
KINDS = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css",
         ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json"}


def adb(*args, timeout=30) -> subprocess.CompletedProcess:
    return subprocess.run(["adb", *args], capture_output=True, timeout=timeout)


#: Android's three animation scales, off: every screen change draws half the frames, and on a software GPU every frame
#: is the CPU's (the owner, 2026-11-13: «still pretty slow»). Settings persist on the device; set once per boot.
ANIMATIONS = ("window_animation_scale", "transition_animation_scale", "animator_duration_scale")
_tuned = threading.Event()


def tune() -> None:
    """All three, or the next poll tries again (a service not yet up answers «Can't find service: settings»)."""
    for key in ANIMATIONS:
        try:
            ok = adb("shell", "settings", "put", "global", key, "0", timeout=15).returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        if not ok:
            _tuned.clear()
            return


def booted() -> bool:
    r = adb("shell", "getprop", "sys.boot_completed", timeout=20)
    up = r.returncode == 0 and r.stdout.strip() == b"1"
    if not up:
        _tuned.clear()                                 # off or booting: the next boot is tuned again
    elif not _tuned.is_set():
        _tuned.set()                                   # once per boot, and never under the supervisor's lock
        threading.Thread(target=tune, daemon=True).start()
    return up


def apk_path(name: str) -> str | None:
    """An APK in the drop folder, by its name or a path under it — never a path outside it."""
    p = os.path.realpath(os.path.join(APKS, str(name or "")))
    return p if p.startswith(APKS + os.sep) and p.endswith(".apk") and os.path.isfile(p) else None


def apk_refusal(name: str, size: int, root: str | None = None) -> tuple[int, dict] | None:
    """Why an APK of this name and size would not be kept — or None. The PUT asks it, and so does the GET a client
    asks first: a refused PUT is answered before its body is read, and a client still sending sees only a closed
    connection, so the reason must reach it by the question asked before (the guard's words survive the hop)."""
    root = root or APKS
    if not APK_NAME.fullmatch(name or ""):
        return 400, {"error": "a name like dgo-0.2.112.apk (letters, digits, . _ -)"}
    if not 0 < size <= APK_MAX:
        return 413, {"error": f"an APK of 1 byte to {APK_MAX >> 30} GiB, with its Content-Length"}
    if shutil.disk_usage(root).free < size + ROOM_LEFT:
        return 507, {"error": f"no room: {size} bytes would leave under {ROOM_LEFT >> 30} GiB free"}
    return None


def store_apk(name: str, size: int, read, root: str | None = None) -> tuple[int, dict]:
    """Stream `size` bytes from read(n) into root/name — under a temporary name of its own (two uploads of one
    name never write one file) until all of it is there."""
    root = root or APKS
    refused = apk_refusal(name, size, root)
    if refused:
        return refused
    fd, part = tempfile.mkstemp(dir=root, prefix=f".{name}.", suffix=".part")
    final, digest, got = os.path.join(root, name), hashlib.sha256(), 0
    try:
        with os.fdopen(fd, "wb") as f:
            while got < size:
                chunk = read(min(1 << 20, size - got))
                if not chunk:
                    break
                f.write(chunk)
                digest.update(chunk)
                got += len(chunk)
        if got != size:
            return 400, {"error": f"the body ended at {got} of {size} bytes: nothing stored"}
        os.replace(part, final)
        return 201, {"apk": name, "bytes": got, "sha256": digest.hexdigest()}
    finally:
        if os.path.exists(part):
            os.remove(part)


def shell_argv(doc: dict) -> tuple[list[str] | None, int]:
    """The device-side command a caller sent: strings only, bounded; and its timeout, clamped."""
    argv, t = doc.get("argv"), doc.get("timeout", 60)
    if not isinstance(argv, list) or not argv or len(argv) > SHELL_ARGS or not all(isinstance(a, str) for a in argv) \
            or sum(len(a) for a in argv) > SHELL_CHARS:
        return None, 0
    return argv, max(1, min(SHELL_MAX_S, t if isinstance(t, int) and not isinstance(t, bool) else 60))


def avd_free() -> int | None:
    """Bytes free where the device's disk lives (its volume, on the office's disk), or None when unread."""
    try:
        return shutil.disk_usage(AVD_DIR).free
    except OSError:
        return None


def ask_exit() -> bool:
    """Ask the running emulator to save its quick-boot snapshot and exit (its console's `kill`, through adb)."""
    try:
        return adb("emu", "kill", timeout=15).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def make_supervisor(pub=None) -> Supervisor:
    return Supervisor(g.emulator_argv(AVD, MEMORY_MB, PARTITION_MB), booted=booted, temp=g.package_temp,
                      pub=pub, cpus=g.pinned_cpus(), disk_free=avd_free, log=EMU_LOG, ask_exit=ask_exit,
                      idle_s=IDLE_STOP_MIN * 60)


def asker(headers, fallback: str) -> str:
    """Who asked, for the status and the flow's bar — a label, never a decision: the office's sign-in names the person
    (the edge sets it; a linked office's door says which office), else the caller's own word."""
    for h in ("X-authentik-name", "X-authentik-username", "X-DGO-Office"):
        v = (headers.get(h) or "").strip()
        if v:
            try:                                 # a header is read as latin-1: a Hebrew name arrives as its UTF-8 bytes
                v = v.encode("latin-1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
            return v[:64]
    return fallback


def handler_for(sup: Supervisor, run_adb=adb):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def answer(self, code, body, kind="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def body(self) -> dict:
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                doc = json.loads(raw or b"{}")
                return doc if isinstance(doc, dict) else {}
            except (ValueError, OSError):
                return {}

        def not_running(self) -> bool:
            """Answers 409 (and says so) unless the device runs — paused for the heat is not running."""
            st = sup.status()
            if st["state"] == g.RUNNING:
                return False
            self.answer(409, {"error": "the device is paused for the heat: wait" if st["state"] == g.PAUSED
                              else "the device is not running", **st})
            return True

        def device(self, *args, timeout):
            """adb's answer, or None once a 504 has said that it did not come in time. A use of the device for as long
            as it runs (an install may take 25 minutes): the idle rule waits for it."""
            hold = getattr(sup, "hold", None) or (lambda d: None)
            hold(+1)
            try:
                return run_adb(*args, timeout=timeout)
            except subprocess.TimeoutExpired:
                self.answer(504, {"error": f"the device did not answer in {timeout} s", **sup.status()})
                return None
            finally:
                hold(-1)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                return self.answer(200, {"ok": True})
            if path == "/api/status":
                return self.answer(200, sup.status())
            if path == "/api/log":                     # the emulator's own output since its last start, the tail
                try:
                    with open(getattr(sup, "log", None) or EMU_LOG, "rb") as f:
                        f.seek(0, os.SEEK_END)
                        f.seek(max(0, f.tell() - LOG_TAIL))
                        return self.answer(200, f.read(), "text/plain; charset=utf-8")
                except OSError:
                    return self.answer(404, {"error": "no emulator log yet: the device has not started since"})
            if path.startswith("/api/apks/"):
                name = path[len("/api/apks/"):]
                asked = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
                try:
                    size = int((asked.get("bytes") or ["0"])[0])
                except ValueError:
                    size = 0
                refused = apk_refusal(name, size)
                if refused:
                    return self.answer(*refused)
                return self.answer(200, {"apk": name, "may": True, "exists": bool(apk_path(name))})
            if path == "/api/screenshot":
                if self.not_running():
                    return None
                r = self.device("exec-out", "screencap", "-p", timeout=30)
                if r is None:
                    return None
                return self.answer(200, r.stdout, "image/png") if r.returncode == 0 and r.stdout.startswith(
                    b"\x89PNG") else self.answer(502, {"error": "the device gave no screen"})
            self.answer(404, {"error": "unknown endpoint"})

        def do_PUT(self):
            path = self.path.split("?", 1)[0]
            if not path.startswith("/api/apks/"):
                return self.answer(404, {"error": "unknown endpoint"})
            try:
                size = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                size = 0
            code, doc = store_apk(path[len("/api/apks/"):], size, self.rfile.read)
            self.answer(code, doc)

        def do_DELETE(self):
            path = self.path.split("?", 1)[0]
            name = path[len("/api/apks/"):] if path.startswith("/api/apks/") else ""
            if not APK_NAME.fullmatch(name):
                return self.answer(404, {"error": "unknown endpoint"})
            apk = apk_path(name)
            if apk:
                os.remove(apk)
            self.answer(200, {"apk": name, "removed": bool(apk)})

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/start":
                return self.answer(202, sup.start(self.body().get("by") or asker(self.headers, "?")))
            if path == "/api/stop":
                return self.answer(200, sup.stop("asked"))
            if path == "/api/install":
                if self.not_running():
                    return None
                apk = apk_path(self.body().get("apk"))
                if not apk:
                    return self.answer(400, {"error": "an .apk in the drop folder (/apks) is named"})
                # a pause for the heat stops adb's answer too: 30 min, as long as a shell may take
                r = self.device("install", "-r", apk, timeout=INSTALL_MAX_S)
                if r is None:
                    return None
                said = (r.stdout + r.stderr).decode("utf-8", "replace").strip()[-2000:]
                return self.answer(200 if r.returncode == 0 else 502, {"ok": r.returncode == 0, "said": said})
            if path == "/api/shell":
                argv, t = shell_argv(self.body())
                if argv is None:
                    return self.answer(400, {"error": f"argv: 1–{SHELL_ARGS} strings, {SHELL_CHARS} characters in all"})
                if self.not_running():
                    return None
                r = self.device("shell", *argv, timeout=t)
                if r is None:
                    return None
                out = r.stdout.decode("utf-8", "replace")
                return self.answer(200, {"rc": r.returncode, "out": out[-OUT_MAX:], "cut": len(out) > OUT_MAX,
                                         "err": r.stderr.decode("utf-8", "replace")[-4000:]})
            self.answer(404, {"error": "unknown endpoint"})

    return Handler


def static_file(root: str, rel: str) -> str | None:
    """A file under `root` by its relative path — never one outside it (`..`, a link out, an absolute path)."""
    p = os.path.realpath(os.path.join(root, urllib.parse.unquote(rel).lstrip("/")))
    return p if p.startswith(root + os.sep) and os.path.isfile(p) else None


def keepalive(sock) -> None:
    """A peer that vanished without closing (a phone that lost its network) is found in about two minutes."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        for opt, v in (("TCP_KEEPIDLE", 60), ("TCP_KEEPINTVL", 20), ("TCP_KEEPCNT", 3)):
            if hasattr(socket, opt):
                sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, opt), v)
    except OSError:
        pass


def splice(client, client_read, upstream, head: bytes, used=None, every_s: float = 5.0) -> None:
    """Carry one websocket between the browser and websockify, byte for byte, both ways, until either side ends. The
    browser's request (`head`) is handed on as it came; websockify answers the upgrade and speaks the protocol.
    `used()` is called (at most every `every_s`) while bytes move: the display changed or a person touched it — an
    open socket alone is no use (a forgotten tab on a dark screen moves nothing)."""
    up = socket.create_connection(upstream, timeout=10)
    up.settimeout(None)
    keepalive(client)
    last = [None]                                # the first bytes are always a use (monotonic() may start at 0)

    def pump(read, dst):
        try:
            while True:
                chunk = read(1 << 16)
                if not chunk:
                    break
                dst.sendall(chunk)
                if used and (last[0] is None or time.monotonic() - last[0] >= every_s):
                    last[0] = time.monotonic()
                    used()
        except OSError:
            pass
        finally:
            try:
                dst.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    try:
        up.sendall(head)
        back = threading.Thread(target=pump, args=(up.recv, client), daemon=True)
        back.start()
        pump(client_read, up)
        back.join()
    finally:
        up.close()


def screen_handler_for(sup, upstream=VNC_WS, novnc=NOVNC_DIR, screen=SCREEN_DIR):
    """The tile's door (:6080): the screen, noVNC's files, the display's websocket, and status/start/stop only."""
    class Screen(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def answer(self, code, body, kind="application/json", cache="no-store"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache)
            self.end_headers()
            self.wfile.write(data)

        def file(self, path, cache):
            with open(path, "rb") as f:
                data = f.read()
            self.answer(200, data, KINDS.get(os.path.splitext(path)[1].lower(), "application/octet-stream"), cache)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                page = static_file(screen, "index.html")
                return self.file(page, "no-store") if page else self.answer(404, {"error": "no screen"})
            if path == "/healthz":
                return self.answer(200, {"ok": True})
            if path == "/api/status":
                return self.answer(200, sup.status())
            if path.startswith("/vnc/"):
                f = static_file(novnc, path[len("/vnc/"):])
                return self.file(f, "max-age=3600") if f else self.answer(404, {"error": "no such file"})
            if path == "/websockify" and "websocket" in (self.headers.get("Upgrade") or "").lower():
                return self.websocket()
            self.answer(404, {"error": "unknown endpoint"})

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not 0 <= length <= 4096:          # the screen sends `{}`: anything else is not read, and not kept alive
                self.close_connection = True
                return self.answer(413 if length > 4096 else 400, {"error": "a body of 0 to 4096 bytes"})
            if length:
                self.rfile.read(length)
            if path == "/api/start":
                return self.answer(202, sup.start(asker(self.headers, "המסך")))
            if path == "/api/stop":
                return self.answer(200, sup.stop("asked"))
            self.answer(404, {"error": "unknown endpoint"})

        def websocket(self):
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            head = (f"GET /websockify{'?' + query if query else ''} HTTP/1.1\r\n"
                    + "".join(f"{k}: {v}\r\n" for k, v in self.headers.items()) + "\r\n").encode("latin-1")
            self.close_connection = True
            sup.watch(+1)
            try:
                splice(self.connection, self.rfile.read1, upstream, head, used=sup.touch)
            except OSError:
                if not self.wfile.closed:
                    try:
                        self.answer(502, {"error": "the display is not answering"})
                    except OSError:
                        pass
            finally:
                sup.watch(-1)

    return Screen


def main() -> int:
    try:
        import flowpub
    except ImportError:                              # pragma: no cover — the mount missing: no bars, still a door
        flowpub = None
    sup = make_supervisor(flowpub)

    def turn():
        while True:
            try:
                sup.tick()
            except Exception as e:                   # noqa: BLE001 — the governor never dies of one bad reading
                print(f"android-emulator: tick: {type(e).__name__}: {e}"[:300], file=sys.stderr, flush=True)
            time.sleep(TICK_S)

    threading.Thread(target=turn, daemon=True).start()
    door = ThreadingHTTPServer(("0.0.0.0", PORT), handler_for(sup))
    threading.Thread(target=door.serve_forever, daemon=True, name="door").start()
    try:
        screen = ThreadingHTTPServer(("0.0.0.0", SCREEN_PORT), screen_handler_for(sup))
    except OSError as e:
        # an image's own start.sh (before it was mounted from the checkout) still runs websockify on this port: a
        # container RESTARTED, not recreated, after its checkout moved. The door and the governor go on; the tile is
        # noVNC's page as before until the container is recreated (`./scripts/dc up -d android-emulator`).
        print(f"android-emulator: the screen cannot listen on :{SCREEN_PORT} ({e.strerror}) — is this container's "
              f"start.sh the image's? Recreate it; the door on :{PORT} runs on", file=sys.stderr, flush=True)
        threading.Event().wait()
        return 1
    screen.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
