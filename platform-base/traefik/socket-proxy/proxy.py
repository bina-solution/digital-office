#!/usr/bin/env python3
"""docker-socket-proxy — the read-only door the edge's provider goes through (DGO-136).

WHY IT EXISTS. traefik's docker provider only LISTS containers and WATCHES events — it never writes —
and it held the engine socket mounted read-write, in the container that is the office's front door.
DGO-136 says the consequence: breaching traefik means control of the host.

A READ-ONLY MOUNT IS NOT THE FIX, and that is measured, not reasoned (2026-10-10): a container with
`/var/run/docker.sock` mounted `:ro` answers

    socket.connect('/var/run/docker.sock'); GET /_ping  ->  HTTP/1.1 200 OK

`:ro` constrains the file node, not the protocol spoken over it, so a compromised traefik keeps
writing. The only thing that constrains the protocol is something that speaks it, which is this:
allow `GET`/`HEAD` on the handful of paths the provider uses, and answer everything else with a
refusal that names the path. Same shape as the platform's other single-purpose watchdogs (autoheal,
machine): one job, stdlib only, no dependency to pin.

WHAT IT IS NOT. Not a docker API. `POST /containers/<id>/restart`, `/exec`, `/build`, `/images/*`,
`/volumes/*`, `DELETE`, `PUT`, `PATCH` — none of them reach the engine: the answer is 403 with the
sentence, and the engine never sees the request. `/events` is allowed and stays open, because a
provider that cannot watch the engine serves a snapshot and never notices a container restarting;
it is the one long-lived connection this door holds.

ONE REQUEST PER CONNECTION (DGO-991, 2026-10-22). The door decides a request, so it may forward only
the request it decided. Its first version decided the first line on a connection and then copied the
connection both ways, so whatever followed on that connection reached the engine undecided, from any
container on traefik-network. Now the door reads the whole head and refuses one it cannot read exactly
one way: a line without CRLF, a folded header, a body, an upgrade, bytes after the head, a path with a
dot segment or an encoded separator. It sends the engine only the request line and headers it checked,
with `connection: close`, so the engine answers once and closes. From then on it only carries the
answer back, and any byte the client sends after its request closes the connection.

    python3 platform-base/traefik/socket-proxy/proxy.py [--selftest] [--port 2375]
                                                        [--socket /var/run/docker.sock]
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import socket
import socketserver
import sys
import tempfile
import threading

#: The engine socket this door reads. Set once at start-up (`--socket`), never while running — the
#: handler reads it per connection, which is also what makes the self-test independent of it.
DOCKER_SOCKET = "/var/run/docker.sock"

#: The paths the docker provider reads. Prefixes, so `/containers/json` and `/containers/<id>/json`
#: are both covered — and only under GET/HEAD, which is what makes a prefix safe to allow.
ALLOWED_PATHS = (
    "/_ping", "/version", "/info", "/events",
    "/containers", "/networks", "/services", "/tasks", "/nodes", "/swarm", "/distribution",
)
ALLOWED_METHODS = ("GET", "HEAD")
#: A VERSIONED PATH IS THE SAME PATH. The docker client — traefik's included, which hardcodes API
#: 1.24 — asks `/v1.24/version`, `/v1.24/containers/json`, `/v1.24/events`. The first version of this
#: door matched the path literally and refused every one of them, which is exactly what "the edge
#: finds zero routers and 404s every host while reporting healthy" looks like from the inside
#: (measured the moment traefik was pointed here: 302 -> 404, and the log said
#: `REFUSED 'GET /v1.24/version HTTP/1.1'`). The version is a prefix on the same path, so it is
#: stripped before the match — and the whitelist stays exactly as narrow.
VERSION_PREFIX = re.compile(r"^/v\d+(?:\.\d+)?(?=/|$)")

#: Longest request head this door will read before deciding. A docker client's head is a few hundred
#: bytes; anything larger is somebody probing, and it is refused rather than buffered.
MAX_HEAD = 16384
#: A docker client sends its head at once. One that has not finished in this many seconds is not
#: coming, and it does not get to hold a thread while it waits.
HEAD_TIMEOUT = 10
#: A path the engine could read as another path is not a path this door decides on.
DOT_OR_ENCODED = re.compile(r"(^|/)\.{1,2}(/|$)|%2e|%2f|%5c|\\", re.I)
#: The one shape of request line and header line the door reads (RFC 9112), nothing looser.
REQUEST_LINE = re.compile(r"[A-Z]+ /[!-~]* HTTP/1\.[01]")
HEADER_LINE = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+:[\t -~]*")
#: Headers about this hop, not the request: dropped, and the door sends its own `connection: close`.
HOP_BY_HOP = ("connection", "keep-alive", "proxy-connection", "te", "trailer")


def decide(request_line: str) -> "tuple[bool, str]":
    """(allowed, why) for one request line — the whole rule, in one place, testable without docker."""
    parts = request_line.split()
    if len(parts) < 2:
        return False, "malformed request line"
    method, target = parts[0].upper(), parts[1]
    path = VERSION_PREFIX.sub("", target.split("?", 1)[0])
    if method not in ALLOWED_METHODS:
        return False, (f"{method} is not a read: this door serves the edge's provider, which only "
                       f"lists containers and watches events")
    if DOT_OR_ENCODED.search(path):
        return False, f"{path} is not a plain path (a dot segment or an encoded separator)"
    if not path.startswith(ALLOWED_PATHS):
        return False, (f"{path} is not one of the paths the provider reads "
                       f"({', '.join(ALLOWED_PATHS)})")
    return True, "read"


def admit(raw: bytes) -> "tuple[bytes | None, str]":
    """(what goes to the engine, why) for all a client sent before the door decides. It must be exactly
    one request head: complete, CRLF lines, an allowed read, no body, no upgrade, nothing after it. What
    goes on is its request line and headers, less the hop-by-hop ones, plus `connection: close`."""
    end = raw.find(b"\r\n\r\n")
    if end < 0:
        return None, f"no complete request head within {MAX_HEAD} bytes"
    if end + 4 > MAX_HEAD:
        return None, f"a request head over {MAX_HEAD} bytes"
    if len(raw) > end + 4:
        return None, "bytes after the request head (this door forwards one request, with no body)"
    try:
        lines = raw[:end].decode("ascii").split("\r\n")
    except UnicodeDecodeError:
        return None, "a request head that is not ASCII"
    if not REQUEST_LINE.fullmatch(lines[0]):
        return None, "malformed request line"
    allowed, why = decide(lines[0])
    if not allowed:
        return None, why
    kept = [lines[0]]
    for line in lines[1:]:
        if not HEADER_LINE.fullmatch(line):
            return None, "a malformed or folded header line"
        name, value = line.split(":", 1)
        name, value = name.lower(), value.strip(" \t")
        if name == "transfer-encoding" or (name == "content-length" and value != "0"):
            return None, "a request with a body (a read has none)"
        if name == "upgrade":
            return None, "a request to switch protocols"
        if name not in HOP_BY_HOP:
            kept.append(line)
    return ("\r\n".join(kept) + "\r\nconnection: close\r\n\r\n").encode("ascii"), "read"


def _refusal(why: str) -> bytes:
    body = json.dumps({"message": "docker-socket-proxy: refused — " + why +
                       " (DGO-136: the edge holds a read-only door, not the engine)"}).encode()
    return (b"HTTP/1.1 403 Forbidden\r\ncontent-type: application/json\r\n"
            b"content-length: " + str(len(body)).encode() + b"\r\nconnection: close\r\n\r\n" + body)


def _pump(a: socket.socket, b: socket.socket) -> None:
    """Copy a to b until either end closes, then close both. Only the engine's answer runs through it."""
    try:
        while True:
            data = a.recv(65536)
            if not data:
                break
            b.sendall(data)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _watch(client: socket.socket, upstream: socket.socket, peer: str) -> None:
    """The client's side after its one request: nothing it sends goes on. Its next byte, or its end,
    closes both sides (its end did before, too)."""
    try:
        if client.recv(1):
            sys.stderr.write(f"docker-socket-proxy: REFUSED {peer} bytes after the request — one "
                             f"request per connection (DGO-991)\n")
            sys.stderr.flush()
    except OSError:
        pass
    for s in (client, upstream):
        try:
            s.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


class Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        client, peer = self.request, self.client_address[0]
        client.settimeout(HEAD_TIMEOUT)
        head = b""
        try:
            while b"\r\n\r\n" not in head and len(head) < MAX_HEAD:
                chunk = client.recv(4096)
                if not chunk:
                    return
                head += chunk
        except OSError:                                 # a reset, or a head that never came
            return
        line = head.split(b"\r\n", 1)[0][:200].decode("latin-1")
        request, why = admit(head)
        if request is None:
            sys.stderr.write(f"docker-socket-proxy: REFUSED {peer} {line!r} — {why}\n")
            sys.stderr.flush()
            try:
                client.sendall(_refusal(why))
            except OSError:
                pass
            return
        client.settimeout(None)                         # an answer (/events too) takes what it takes
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as upstream:
            try:
                upstream.connect(DOCKER_SOCKET)
            except OSError as e:
                try:
                    client.sendall(b"HTTP/1.1 502 Bad Gateway\r\ncontent-length: 0\r\nconnection: close\r\n\r\n")
                except OSError:
                    pass
                sys.stderr.write(f"docker-socket-proxy: engine socket unreachable: {e}\n")
                return
            try:
                upstream.sendall(request)               # the one request it decided, and nothing else
            except OSError:
                return
            t = threading.Thread(target=_watch, args=(client, upstream, peer), daemon=True)
            t.start()
            _pump(upstream, client)
            t.join(timeout=5)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _later_request_case() -> "tuple[bool | None, str]":
    """A later request on the same connection never reaches the engine. A fake engine on a temporary
    socket records every byte it gets; the door serves it a GET /events (a stream, so the answer stays
    open), and the client then sends a second request on the same connection. None where there are no
    unix sockets (the door runs on Linux)."""
    global DOCKER_SOCKET
    if not hasattr(socket, "AF_UNIX") or sys.platform == "win32":
        return None, "no unix sockets here"
    tmp = tempfile.mkdtemp(prefix="socket-proxy-selftest-")
    saved, DOCKER_SOCKET = DOCKER_SOCKET, os.path.join(tmp, "engine.sock")
    seen, finished = [], threading.Event()
    engine = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    engine.bind(DOCKER_SOCKET)
    engine.listen(1)
    engine.settimeout(5)

    def fake_engine() -> None:
        try:
            conn, _ = engine.accept()
            with conn:
                conn.settimeout(5)
                answered = False
                while True:
                    data = conn.recv(4096)
                    if not data:
                        break
                    seen.append(data)
                    if not answered and b"\r\n\r\n" in b"".join(seen):
                        conn.sendall(b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n"
                                     b"transfer-encoding: chunked\r\n\r\n")
                        answered = True
        except OSError:
            pass
        finished.set()

    threading.Thread(target=fake_engine, daemon=True).start()
    srv = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    first, closed, log, saved_err = b"", False, io.StringIO(), sys.stderr
    sys.stderr = log                                    # the door's refusal line is part of the proof
    try:
        cl = socket.create_connection(srv.server_address, 5)
        cl.sendall(b"GET /events HTTP/1.1\r\nHost: selftest\r\n\r\n")
        first = cl.recv(4096)
        cl.sendall(b"GET /_ping HTTP/1.1\r\nHost: selftest\r\n\r\n")
        try:
            while cl.recv(4096):
                pass
            closed = True
        except socket.timeout:
            closed = False
        except OSError:
            closed = True                               # a reset closes it too
        cl.close()
        finished.wait(5)
    finally:
        srv.shutdown()
        srv.server_close()
        engine.close()
        sys.stderr = saved_err
        DOCKER_SOCKET = saved
        shutil.rmtree(tmp, ignore_errors=True)
    got, logged = b"".join(seen), "REFUSED 127.0.0.1 bytes after the request" in log.getvalue()
    ok = (first.startswith(b"HTTP/1.1 200") and closed and finished.is_set() and logged
          and got == b"GET /events HTTP/1.1\r\nHost: selftest\r\nconnection: close\r\n\r\n")
    return ok, ("the engine got exactly the one request, and the refusal was logged" if ok
                else f"the engine got {got!r}, closed={closed}, refusal logged={logged}")


def selftest() -> int:
    cases = [
        ("GET /_ping HTTP/1.1", True),
        ("HEAD /_ping HTTP/1.1", True),
        ("GET /version HTTP/1.1", True),
        ("GET /containers/json?all=0&filters=%7B%7D HTTP/1.1", True),
        ("GET /containers/abc123/json HTTP/1.1", True),
        ("GET /events?filters=%7B%22type%22%3A%5B%22container%22%5D%7D HTTP/1.1", True),
        ("GET /networks HTTP/1.1", True),
        # the docker client versions EVERY path — traefik asks /v1.24/..., and refusing those is
        # how the edge came up with zero routers the first time this door was switched on
        ("GET /v1.24/version HTTP/1.1", True),
        ("GET /v1.24/containers/json?filters=%7B%7D HTTP/1.1", True),
        ("GET /v1.43/events HTTP/1.1", True),
        ("POST /v1.24/containers/abc/restart HTTP/1.1", False),
        ("DELETE /v1.24/containers/abc HTTP/1.1", False),
        # everything a compromised front door would try
        ("POST /containers/abc/restart HTTP/1.1", False),
        ("POST /containers/create HTTP/1.1", False),
        ("POST /exec/abc/start HTTP/1.1", False),
        ("DELETE /containers/abc HTTP/1.1", False),
        ("PUT /containers/abc/archive HTTP/1.1", False),
        ("GET /images/json HTTP/1.1", False),
        ("GET /volumes HTTP/1.1", False),
        ("POST /build HTTP/1.1", False),
        ("GET / HTTP/1.1", False),
        ("garbage", False),
        # a path the engine could read as another path (DGO-991)
        ("GET /containers/../images/json HTTP/1.1", False),
        ("GET /containers/%2e%2e/images/json HTTP/1.1", False),
        ("GET /containers/x%2Fy/json HTTP/1.1", False),
        ("GET /containers/x%5cy/json HTTP/1.1", False),
        ("GET /containers/x\\y/json HTTP/1.1", False),
        ("GET /containers/./json HTTP/1.1", False),
        ("GET /v1.24/../images/json HTTP/1.1", False),
        ("GET /v1.24/containers/json?filters=%7B%22label%22%3A%5B%22a%2Fb%22%5D%7D HTTP/1.1", True),
    ]
    bad = 0
    for line, want in cases:
        got, why = decide(line)
        ok = got == want
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] {'allow' if got else 'refuse':6} {line[:58]:58}"
              f"{'' if ok else '  WANTED ' + str(want)}")
    # ONE REQUEST PER CONNECTION (DGO-991): what goes to the engine is exactly one checked request,
    # byte for byte, or nothing (None)
    host = b"Host: docker-socket-proxy:2375\r\n"
    close = b"connection: close\r\n\r\n"
    listing = (b"GET /v1.24/containers/json?limit=0 HTTP/1.1\r\n" + host +
               b"User-Agent: Go-http-client/1.1\r\nAccept-Encoding: gzip\r\n\r\n")
    framing = [
        ("the healthcheck's HTTP/1.0 ping", b"GET /_ping HTTP/1.0\r\n\r\n", b"GET /_ping HTTP/1.0\r\n" + close),
        ("the provider's listing", listing, listing[:-2] + close),
        ("keep-alive asked, close sent", b"GET /v1.24/events HTTP/1.1\r\n" + host + b"Connection: keep-alive\r\n\r\n",
         b"GET /v1.24/events HTTP/1.1\r\n" + host + close),
        ("an empty body declared", b"GET /_ping HTTP/1.1\r\n" + host + b"Content-Length: 0\r\n\r\n",
         b"GET /_ping HTTP/1.1\r\n" + host + b"Content-Length: 0\r\n" + close),
        ("hop-by-hop headers dropped", b"GET /_ping HTTP/1.1\r\n" + host +
         b"TE: trailers\r\nTrailer: x\r\nProxy-Connection: keep-alive\r\nKeep-Alive: 5\r\n\r\n",
         b"GET /_ping HTTP/1.1\r\n" + host + close),
        ("a second request after the first", b"GET /_ping HTTP/1.1\r\n" + host + b"\r\n"
         b"GET /_ping HTTP/1.1\r\n" + host + b"\r\n", None),
        ("a body by length", b"GET /_ping HTTP/1.1\r\n" + host + b"Content-Length: 12\r\n\r\n", None),
        ("a body by chunks", b"GET /_ping HTTP/1.1\r\n" + host + b"Transfer-Encoding: chunked\r\n\r\n", None),
        ("an upgrade", b"GET /_ping HTTP/1.1\r\n" + host + b"Upgrade: tcp\r\nConnection: Upgrade\r\n\r\n", None),
        ("a line ending in a bare LF", b"GET /_ping HTTP/1.1\n" + host + b"\r\n", None),
        ("a folded header", b"GET /_ping HTTP/1.1\r\n" + host + b" folded\r\n\r\n", None),
        ("a head that is not ASCII", b"GET /_ping HTTP/1.1\r\n" + host + b"X-Note: \xe2\x9c\x93\r\n\r\n", None),
        ("two spaces in the request line", b"GET  /_ping HTTP/1.1\r\n\r\n", None),
        ("no end within the limit", b"GET /_ping HTTP/1.1\r\nX-Pad: " + b"a" * MAX_HEAD, None),
        ("a head over the limit", b"GET /_ping HTTP/1.1\r\nX-Pad: " + b"a" * MAX_HEAD + b"\r\n\r\n", None),
        ("a write, framed well", b"POST /containers/create HTTP/1.1\r\n" + host + b"\r\n", None),
    ]
    for label, raw, want in framing:
        got, why = admit(raw)
        ok = got == want
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] {'admit' if got else 'refuse':6} {label[:58]:58}"
              f"{'' if ok else '  GOT ' + repr(got)[:80] + ' (' + why + ')'}")
    live, why = _later_request_case()
    if live is None:
        print(f"  [skip] {'live':6} a later request on the same connection ({why})")
    else:
        bad += 0 if live else 1
        print(f"  [{'ok ' if live else 'FAIL'}] {'live':6} a later request on the same connection never reaches "
              f"the engine{'' if live else '  (' + why + ')'}")
    total = len(cases) + len(framing) + (0 if live is None else 1)
    print(f"\nsocket-proxy self-test: {total - bad}/{total} passed")
    return 1 if bad else 0


def main() -> int:
    global DOCKER_SOCKET
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--port", type=int, default=2375)
    ap.add_argument("--socket", default=DOCKER_SOCKET)
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    DOCKER_SOCKET = a.socket
    print(f"docker-socket-proxy: listening on :{a.port} -> {DOCKER_SOCKET} "
          f"(GET/HEAD on {', '.join(ALLOWED_PATHS)}; everything else refused)", flush=True)
    with Server(("0.0.0.0", a.port), Handler) as srv:
        srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
