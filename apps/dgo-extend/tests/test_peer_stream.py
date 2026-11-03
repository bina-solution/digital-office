#!/usr/bin/env python3
"""test_peer_stream — the link's door passes a large download on in bounded pieces (DGO-1272).

    python3 apps/dgo-extend/tests/test_peer_stream.py       # or: python3 -m pytest apps/dgo-extend/tests/test_peer_stream.py

`peer_proxy` handed on `r.iter_content(chunk_size=None)`, and urllib3 reads a body that has a
Content-Length with ONE `read(None)`: a meeting's recording opened as a remote tile sat whole in this
160M container. The console was OOM-killed exactly that way on FPG (DGO-1231). Measured here with the
real requests and the real web stack (this app's image) against a real server: the first piece the
door hands on is at most PASS_CHUNK, the whole body still arrives intact, and an event-stream keeps
passing on each event as it arrives. Hermetic: a loopback server, a scratch volume and registry.
"""
from __future__ import annotations

import asyncio
import atexit
import http.server
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

import requests                       # the real ones: this test is about what they do
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "apps/dgo-extend"
sys.path.insert(0, str(APP))

BODY = bytes(range(256)) * (16 * 1024)                    # 4 MiB, sent with a Content-Length


NAME = "dgo_extend_app_peer_stream"   # its own: test_app_input.py loads app.py with a registry of ITS own


def load():
    """app.py, loaded once, with a scratch volume and a compiled registry of its own."""
    if NAME in sys.modules:
        return sys.modules[NAME]
    os.environ["DGO_STATE_DIR"] = tempfile.mkdtemp(prefix="dgo-peer-stream-")
    registry = Path(tempfile.mkdtemp(prefix="dgo-peer-registry-"))
    for scratch in (os.environ["DGO_STATE_DIR"], registry):
        atexit.register(shutil.rmtree, scratch, True)
    (registry / "office.apps.json").write_text(json.dumps({"apps": []}), encoding="utf-8")
    os.environ["DGO_REGISTRY_DIR"] = str(registry)
    spec = importlib.util.spec_from_file_location(NAME, APP / "app.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[NAME] = module
    spec.loader.exec_module(module)
    return module


class Upstream(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.endswith("/events"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for n in range(3):
                event = f"data: {n}\n\n".encode()
                self.wfile.write(b"%x\r\n%s\r\n" % (len(event), event))
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            return
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *a):
        pass


def pieces(sub: str) -> tuple[int, list[bytes]]:
    """What peer_proxy hands on for GET /peer/office2/rec/<sub>, piece by piece, from a real server."""
    a = load()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    here = f"http://127.0.0.1:{server.server_address[1]}/"
    real = (a.load, a.peers.read, a.peers.token_for, a.requests.request)
    scope = {"type": "http", "method": "GET", "path": f"/peer/office2/rec/{sub}", "query_string": b"",
             "headers": [(b"accept", b"*/*")]}

    async def run():
        resp = await a.peer_proxy(Request(scope), "office2", "rec", sub)
        return resp.status_code, [chunk async for chunk in resp.body_iterator]
    try:
        a.load = lambda oid: {"domain": "office2.example.co.il"}
        a.peers.read = lambda oid, alias: {"alias": alias}
        a.peers.token_for = lambda oid, create=False: "peer-token"
        a.requests.request = lambda method, url, **kw: real[3](
            method, url.replace(f"https://{a.peers.PEER_HOST}.office2.example.co.il/", here), **kw)
        return asyncio.run(run())
    finally:
        a.load, a.peers.read, a.peers.token_for, a.requests.request = real
        server.shutdown()
        server.server_close()


def test_a_large_download_passes_through_in_bounded_pieces():
    status, got = pieces("meeting.mp4")
    first = len(got[0]) if got else 0
    assert status == 200 and 0 < first <= 256 * 1024, f"first piece {first} bytes"
    assert all(len(p) <= load().PASS_CHUNK for p in got)
    assert b"".join(got) == BODY


def test_an_event_stream_still_passes_each_event_on_as_it_arrives():
    status, got = pieces("events")
    assert status == 200 and b"".join(got) == b"data: 0\n\ndata: 1\n\ndata: 2\n\n"
    assert len(got) == 3, [len(p) for p in got]               # one piece per event, not one at the end


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:                            # noqa: BLE001 — report every test
                failed += 1
                print(f"FAIL {name}: {type(e).__name__}: {e}")
    sys.exit(1 if failed else 0)
