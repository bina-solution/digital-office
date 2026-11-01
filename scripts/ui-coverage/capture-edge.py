#!/usr/bin/env python3
"""capture-edge.py — the edge's routing, for a capture that must not go through the edge.

    python3 capture-edge.py <listen-port> --route <name>=<host:port> [--route …] [--root <name>=<host:port>]

WHY. A capture runs inside the office network and reaches the console by its container address, so
it never visits Traefik — and Traefik is where the office's own ROOT paths are routed. `apps/bina-ds`
declares three passthroughs mounted at the console host's root (`/api`, `/plugins`, `/assets`,
`mount: root` in its app.json): the agent's page is framed at the console's own origin and addresses
those paths at that origin's root. Through Traefik they reach bina-ds; in a capture they reach the
console, which answers 404 (or its own shell), every client bundle "import fails", and the harness
renders "Failed to load plugins" — 20 nodes. Measured 2026-10-09: `bina` scored `failed · embedded
app near-empty (20 nodes)` in both profiles, which left the beauty score with no bina row at all.

WHAT IT IS. A byte-for-byte TCP forwarder with two decisions: the Host header picks an office name
(the same names the harness trusts — `console.localhost`, `bina.localhost`), and — for a name whose
app declares root paths — the FIRST path segment may pick a different app. Client bundles are large;
nothing here parses or re-encodes a body, so websockets and gzip pass through untouched.

It is the capture's stand-in for Traefik only: no TLS, no auth, no redirects. Its routes come from
the caller (`run_capture.sh`), which reads them from the compiled registry — never hardcoded here.
"""
from __future__ import annotations

import socket
import sys
import threading

PORT = int(sys.argv[1])
ROUTES: dict[str, tuple[str, int]] = {}
ROOT: dict[str, dict[str, tuple[str, int]]] = {}          # name → {first path segment: target}
args = sys.argv[2:]
i = 0
while i < len(args):
    kind, spec = args[i], args[i + 1]
    name, target = spec.split("=", 1)
    host, port = target.rsplit(":", 1)
    if kind == "--route":
        ROUTES[name.lower()] = (host, int(port))
    elif kind == "--root":                                # "<name>:<prefix>=<host:port>"
        name, prefix = name.split(":", 1)
        ROOT.setdefault(name.lower(), {})[prefix] = (host, int(port))
    else:
        raise SystemExit(f"unknown argument {kind}")
    i += 2


def target_for(host_header: str, path: str) -> tuple[str, int]:
    """The app that answers, by the LONGEST matching prefix first — so `--root …:/api=<agent>` can be
    carved out by `--root …:/api/me=<console>`, which is exactly how the edge's compiled rule reads
    (`PathPrefix(`/api`) && !PathRegexp(`^/(api/me|api/version|…)(/|$)`)`)."""
    name = (host_header or "").split(":")[0].strip().lower()
    hits = [(prefix, target) for prefix, target in ROOT.get(name, {}).items()
            if path == prefix or path.startswith(prefix.rstrip("/") + "/")]
    if hits:
        return max(hits, key=lambda t: len(t[0]))[1]
    if name in ROUTES:
        return ROUTES[name]
    return next(iter(ROUTES.values()))


def pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def handle(client: socket.socket) -> None:
    head = b""
    while b"\r\n\r\n" not in head and len(head) < 65536:
        chunk = client.recv(4096)
        if not chunk:
            client.close()
            return
        head += chunk
    host, path = "", "/"
    lines = head.split(b"\r\n")
    if lines and b" " in lines[0]:
        path = lines[0].split(b" ")[1].decode("latin-1")
    for line in lines[1:]:
        if line.lower().startswith(b"host:"):
            host = line.split(b":", 1)[1].strip().decode("latin-1")
            break
    target = target_for(host, path)
    try:
        upstream = socket.create_connection(target, timeout=15)
    except OSError as error:
        print(f"[capture-edge] {host} {path[:40]} -> {target}: {error}", flush=True)
        client.close()
        return
    print(f"[capture-edge] {host} {path[:60]} -> {target[0]}:{target[1]}", flush=True)
    # ONE REQUEST PER CONNECTION, forced: a browser keeps a connection alive and sends the NEXT
    # request down it — and this proxy decides the upstream from the FIRST request on a connection,
    # so `/plugins/??…` arriving on a connection that opened with `/` went to the console and came
    # back as its HTML (measured 2026-10-09: the client bundle answered `text/html`, every import
    # failed, and the agent rendered empty). Downgrading the request to HTTP/1.0 asks the upstream to
    # close after answering, which makes the browser open a fresh connection per request — the one
    # shape this proxy can route correctly.
    head = head.replace(b" HTTP/1.1\r\n", b" HTTP/1.0\r\n", 1)
    upstream.sendall(head)
    threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
    pipe(upstream, client)


srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", PORT))
srv.listen(128)
print(f"[capture-edge] :{PORT} routes={ROUTES} root={ROOT}", flush=True)
while True:
    conn, peer = srv.accept()
    # Logged on ACCEPT, before a single byte is read: a connection that opens and closes without a
    # complete request head is invisible to the per-request line below, and that blind spot is what
    # left "no requests" unexplained while the capture still rendered a page.
    print(f"[capture-edge] accept from {peer[0]}:{peer[1]}", flush=True)
    threading.Thread(target=handle, args=(conn,), daemon=True).start()
