#!/usr/bin/env python3
"""https-redirect — the office's port-80 answer: 308, and nothing else (DGO-1595).

WHY IT EXISTS. On every office the compiler (and every app's own labels) publishes a `-http`
router on traefik's `web` entrypoint, so `http://n8n.<domain>/` served the editor in cleartext —
measured 2026-11-09 from outside, `http://n8n.exampleu…/` 200, `/rest/settings` 200, `http://meet…/`
200 (Jitsi), and no HSTS anywhere. A laptop office (`*.localhost`) has no certificate, so nothing
there may be redirected: this service is only ever REACHED on a server office (the router that
carries it is rendered for those, and for those only).

WHY A SERVICE AND NOT TRAEFIK'S OWN REDIRECT. Traefik v3.3 has two redirect middlewares
(`redirectScheme`, `redirectRegex`) and an entrypoint redirection, and all three answer 301 or 302
— measured on this engine, 2026-11-09: `permanent: true` → 301, `false` → 302, and there is no 308
in the v3.5 reference either (fields: scheme, permanent, port). A 301 turns a POST into a GET at
the client, so a webhook that was configured with `http://` would arrive as nothing: 308 is the one
status that keeps the method AND the body. Traefik cannot emit it, so the office emits it.

WHY forwardAuth. It is the only mechanism that lets traefik hand a request to a service and return
THAT service's answer verbatim — a non-2xx from the auth server is copied to the client, Location
and status included (measured: a 308 from here reaches curl as 308, for GET and for POST). The
router that carries it is `dgo-port80`, rendered into traefik's file provider, with the ACME
challenge path excluded so HTTP-01 renewals keep working.

THE RULE. Anything else is 308 to the same host and path over https. The host and path come from
traefik's own `X-Forwarded-*` — never from anything a client can set, because traefik rebuilds those
from the request it received (its forwardAuth runs with `trustForwardHeader: false`).

AN OFFICE THAT MOVED (DGO-2013). An office whose domain changed keeps its old names in DNS, and every link
already out — a work item, a group line, a bookmark, an invite, an OAuth callback — names them. Those names
are declared (`DGO_FORMER_DOMAINS`, reaching here as `HTTPS_REDIRECT_FORMER`), the compiler routes them here
on both entrypoints (zz-https.yaml). On https a host under one of them is sent to the SAME host under the
office's current name: `console.<former>/go/DGO-1` → `https://console.<current>/go/DGO-1`. On port 80 it is first
sent to https on its own name, so a host an app still serves at the old name keeps working (target()). Still 308:
an old webhook's POST keeps its method and its body.
"""
import json
import os
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("HTTPS_REDIRECT_PORT", "8079"))
# The office's own name(s) a Location may point at. Set from DEPLOYMENT_DOMAIN by the compose file;
# EMPTY means "do not judge the host" (an office whose name nobody configured), never "allow anything"
# — the host still has to survive target()'s own checks.
SUFFIX = (os.environ.get("HTTPS_REDIRECT_SUFFIX") or "").strip().lower().lstrip(".")
# The office's FORMER names (DGO-2013), comma-separated; empty = the office never moved.
FORMER = tuple(d for d in (p.strip().lower().strip(".") for p in
                           (os.environ.get("HTTPS_REDIRECT_FORMER") or "").split(",")) if d)


def moved(host):
    """The same host under the office's current name, when `host` is under one of its FORMER names; else None.

    The longest former name that holds the host decides, and a host the CURRENT name holds more closely stays
    where it is: an office that moved from `example.com` to `bina.example.com` must not send
    `console.bina.example.com` to `console.bina.bina.example.com`. A port is dropped — the new name is https's."""
    if not SUFFIX or not FORMER:
        return None
    bare = host.split(":", 1)[0].lower().rstrip(".")
    best = max((d for d in FORMER if bare == d or bare.endswith("." + d)), key=len, default=None)
    if best is None:
        return None
    if (bare == SUFFIX or bare.endswith("." + SUFFIX)) and len(SUFFIX) >= len(best):
        return None
    return bare[:len(bare) - len(best)] + SUFFIX


def allowed_host(host):
    """Is this a host of THIS office? A 308 is a Location copied into a browser's address bar, and a
    stranger's Host header must not be able to choose it (DNS rebinding, a caching proxy in front).

    With no suffix configured nothing is refused here — the app is told its domain by the compose file
    (`HTTPS_REDIRECT_SUFFIX`), and a check that cannot run must not reject a real caller."""
    if not SUFFIX:
        return True
    bare = host.split(":", 1)[0].lower()
    return bare == SUFFIX or bare.endswith("." + SUFFIX)


def target(headers, path):
    """(host, uri) the caller asked for, or None when there is no host to redirect to.

    `X-Forwarded-Host` first: traefik writes it from the Host header it received, and it is the only
    one of the two that survives a proxy in front of it. `X-Forwarded-Uri` carries the path AND the
    query; the request's own path is the fallback for a direct call.

    PORT 80 ONLY UPGRADES A FORMER NAME (the second reader of 0d64d3b23, then measured on vps1 2026-11-20). An
    office that moved can still serve some hosts at an old name: vps1's n8n, meet, auth and security stay on
    staging. `dgo-former-http` outranks every app's port-80 router, so moving on port 80 sent
    `http://n8n.staging…/healthz` to `https://n8n.bina-solutions…`, where nothing serves it, and an http webhook
    with it. On port 80 (traefik's forwardAuth says `X-Forwarded-Proto: http`) a former host is sent to https on the
    SAME name. There a host still served keeps its own router, and only the hosts nothing serves reach `dgo-former`
    (websecure, priority 2), which moves them. A direct call, with no X-Forwarded-Proto, moves as before."""
    host = (headers.get("X-Forwarded-Host") or headers.get("Host") or "").strip()
    if not host or any(c in host for c in " \t\r\n/\\@?#") or host.startswith("."):
        return None                     # no host, or one that would make a Location another origin
    cleartext = (headers.get("X-Forwarded-Proto") or "").strip().lower() == "http"
    new = moved(host)
    if new and not cleartext:
        host = new
    elif new:                             # a former host on port 80: upgraded where it is, without :80
        host = host.split(":", 1)[0].lower().rstrip(".")
    elif not allowed_host(host):
        return None
    uri = headers.get("X-Forwarded-Uri") or path or "/"
    if not uri.startswith("/"):
        uri = "/" + uri
    if any(c in uri for c in "\r\n\t\x00") or not uri.startswith("/"):
        return None                     # a header value is not a place to paste a control character
    return f"https://{host}{uri}"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "https-redirect"
    sys_version = ""

    def _health(self):
        body = b'{"ok":true,"app":"https-redirect"}'
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self):
        # A 308 answers without a body of its own, so the request's body must be CONSUMED before the
        # connection is reused: a keep-alive POST whose body is left in the socket makes the next
        # request on it read as `helloGET` (measured). `Connection: close` is the simpler half of the
        # contract and costs a redirect nothing.
        length = self.headers.get("content-length")
        if length and length.isdigit() and int(length) <= 1_048_576:
            self.rfile.read(int(length))
        dest = target(self.headers, self.path)
        if dest is None:
            body = b'{"error":"no host"}'
            self.send_response(400)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        # 308: the method and the body are kept by the client, which is the whole point
        self.send_response(308)
        self.send_header("Location", dest)
        self.send_header("content-length", "0")
        self.send_header("connection", "close")
        self.end_headers()
        self.close_connection = True

    def do_GET(self):
        self._health() if self.path.split("?")[0] == "/healthz" else self._redirect()

    def do_HEAD(self):
        self._redirect()

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD

    def log_message(self, fmt, *args):        # noqa: D102 — one line per request, no query strings
        sys.stderr.write("https-redirect: %s %s\n" % (self.command, self.path.split("?")[0]))


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    # shutdown() BLOCKS until serve_forever returns, so calling it from this (the serving) thread
    # deadlocks and every stop becomes a SIGKILL ten seconds later — measured on the first build.
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=srv.shutdown, daemon=True).start())
    print(json.dumps({"ok": True, "listening": PORT}), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
