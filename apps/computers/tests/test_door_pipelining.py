#!/usr/bin/env python3
"""test_door_pipelining — a request PIPELINED after the door's is never handled here (DGO-1800, before narrowing).

The link's door (apps/dgo-extend/link-proxy.py) rewrites only the FIRST head on a connection — removing a peer's
x-dgo-office, x-dgo-identity and x-dgo-herd, writing its own and `Connection: close` — and copies every byte after it
raw. A second request in those bytes would reach this app from the door's own address, carrying whatever x-dgo-herd
the peer wrote, and the door's address is what computers believes the mark from. So it must never be handled.

Measured here, on the server the computers image runs (its Dockerfile CMD: `uvicorn … --no-proxy-headers
--no-access-log`), with each of its HTTP engines (auto, h11, httptools): the bytes a door would copy — a GET with
`Connection: close` and a second GET carrying `x-dgo-herd: 1`, and the same after a POST body — are sent in one write,
and the app counts what it handled. Only the first; one response; the connection closes.

…AND A HEAD THAT LOOKS LIKE A WEBSOCKET HANDSHAKE (the second reader): the door gives it `Connection: Upgrade` instead,
and the bytes after it reach the app before it answers. With a websocket library installed (`websockets`, in
requirements.txt) uvicorn hands that connection to its websocket handler, so the bytes are never read as HTTP — a
refused upgrade is closed. Without one (`--ws none`, the control) h11 serves the pipelined request with the peer's mark.
So the protection rests on that library: the test asserts it is importable, and a uvicorn that ever answered the
second request on any path here fails it.

Run in the app's image: python3 tests/test_door_pipelining.py   (from apps/computers; needs no network)
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

APP = '''
from fastapi import FastAPI, Request
app = FastAPI()
SEEN = []
@app.api_route("/{p:path}", methods=["GET", "POST"])
async def any_(p: str, request: Request):
    if p == "seen":
        return {"seen": SEEN}
    SEEN.append({"path": "/" + p, "herd": request.headers.get("x-dgo-herd")})
    return {"ok": True}
'''
CASES = {
    "a GET, then a GET with the mark": (b"GET /first HTTP/1.1\r\nHost: c\r\nConnection: close\r\n\r\n"
                                        b"GET /smuggled HTTP/1.1\r\nHost: c\r\nx-dgo-herd: 1\r\n\r\n"),
    "a POST body, then a GET with the mark": (b"POST /first HTTP/1.1\r\nHost: c\r\nConnection: close\r\n"
                                              b"Content-Length: 2\r\n\r\n{}"
                                              b"GET /smuggled HTTP/1.1\r\nHost: c\r\nx-dgo-herd: 1\r\n\r\n"),
}
#: a head the door's `Door.websocket` takes for a handshake (it writes `Connection: Upgrade`), on a path with no
#: websocket route and no key — a refused upgrade — then the request a peer would hide behind it
UPGRADE = (b"GET /first HTTP/1.1\r\nHost: c\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n"
           b"GET /smuggled HTTP/1.1\r\nHost: c\r\nx-dgo-herd: 1\r\n\r\n")
FAIL: list[str] = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAIL.append(what)


def serve(impl: str, port: int, appdir: str, ws: str = "auto") -> subprocess.Popen:
    # the image's own CMD flags (apps/computers/Dockerfile), with the engine under test named
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "pipeapp:app", "--app-dir", appdir, "--host", "127.0.0.1",
                             "--port", str(port), "--no-proxy-headers", "--no-access-log", "--http", impl, "--ws", ws,
                             "--log-level", "warning"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(150):
        if proc.poll() is not None:
            raise SystemExit(f"uvicorn --http {impl} --ws {ws} ended before it listened")
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return proc
        except OSError:
            time.sleep(0.1)
    proc.kill()
    raise SystemExit(f"uvicorn --http {impl} did not listen")


def handled_after(impl: str, port: int, appdir: str, raw: bytes, ws: str = "auto", wait: float = 5) -> tuple[list, bytes]:
    """(the paths the app handled, the bytes it answered) for `raw` sent in ONE write, as the door copies it."""
    proc = serve(impl, port, appdir, ws)
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=wait)
        s.sendall(raw)
        got = b""
        try:
            while chunk := s.recv(65536):
                got += chunk
        except socket.timeout:
            got += b"[the connection stayed open]"
        s.close()
        time.sleep(0.3)
        seen = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/seen", timeout=5).read())["seen"]
    finally:
        proc.kill()
        proc.wait()
    return [x["path"] for x in seen], got


def main() -> int:
    appdir = tempfile.mkdtemp(prefix="pipeline-")
    Path(appdir, "pipeapp.py").write_text(APP, encoding="utf-8")
    # the websocket path's protection is this library being there (requirements.txt): said, never assumed —
    # as a DECLARATION wherever the file is (a bare runner, a desk), and as a fact where the library can be imported
    req = Path(__file__).resolve().parent.parent / "requirements.txt"
    if req.is_file():
        declared = any(ln.split("#")[0].strip().lower().startswith("websockets")
                       for ln in req.read_text(encoding="utf-8").splitlines())
        check(declared, "the image's requirements.txt names a websocket library, which is what keeps a refused "
                        "upgrade from serving HTTP")
    try:
        import websockets  # noqa: F401
    except ImportError:
        if FAIL:
            return 1
        # Off the image what the library does cannot be measured: the tests gate's own words for it (a line that
        # starts NOT RUN, and a non-zero exit — exit 0 would read as a pass), so that it is run in the app's image.
        # It was a FAIL here, and the proof of a version died on its own runner twice (2026-11-11, bab9c60e5).
        print("NOT RUN this machine has no `websockets` package — the computers image has it (requirements.txt); "
              "the cases run there")
        return 2
    for n, impl in enumerate(("auto", "h11", "httptools")):
        for m, (name, raw) in enumerate(CASES.items()):
            # a fresh server per case: what it handled is this case's
            handled, got = handled_after(impl, 18900 + n * 10 + m, appdir, raw)
            check(handled == ["/first"] and got.count(b"HTTP/1.1 ") == 1 and b"stayed open" not in got,
                  f"--http {impl}, {name}: only the first is handled, one answer, closed ({handled})")
        handled, got = handled_after(impl, 18900 + n * 10 + 5, appdir, UPGRADE)
        check("/smuggled" not in handled and b"stayed open" not in got,
              f"--http {impl}, a refused websocket upgrade, then a GET with the mark: the GET is never handled ({handled})")
        # THE CONTROL: the same bytes WITHOUT the door's `Connection: close` — the server does take a pipelined
        # request then, so this test can see one; it is the door's word that closes the connection, nothing else
        handled, _ = handled_after(impl, 18900 + n * 10 + 9, appdir,
                                   CASES["a GET, then a GET with the mark"].replace(b"Connection: close\r\n", b""), wait=3)
        check(handled == ["/first", "/smuggled"],
              f"--http {impl}, the control: without `Connection: close` both are handled, so the test sees one")
    # …and the upgrade's control: with no websocket handling (`--ws none`) h11 reads the bytes after a refused
    # upgrade as HTTP — what the library above prevents, shown so the reason it must stay installed is on record
    handled, _ = handled_after("h11", 18999, appdir, UPGRADE, ws="none", wait=3)
    check("/smuggled" in handled,
          f"the control: under `--ws none` h11 does serve the request behind a refused upgrade ({handled})")
    print(f"test_door_pipelining: {'all passed' if not FAIL else f'{len(FAIL)} failed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
