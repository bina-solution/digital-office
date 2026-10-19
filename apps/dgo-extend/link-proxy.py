#!/usr/bin/env python3
"""The link proxy, RUNNING — one process in the tunnel container's network namespace (DGO-24).

The plan is not here: `linkproxy.py` renders `link-proxy.json` from the declarations this office
owns, and this file only APPLIES what it finds. That split is the whole
design — the applier has no opinion, so a change of plan is a re-render, not a new container — and it
is the same split `net.py`/`tunnel-entrypoint.sh` already use for the tunnel itself.

It runs in the namespace of `dgo-net` (`network_mode: service:dgo-net`), which is the only place the
tunnel address exists at all: measured on this deployment, `wg0`/`10.79.x.1` is inside that container
and the machine running it has no WireGuard interface whatever.

It does NOT touch a firewall. The other half of delivery — a connection that terminates here is an
INPUT packet, and the permission chain drops what is not a reply or ICMP — is `firewall.py`'s own
`from_tunnel` chain, rendered from the same declaration. A base chain's `accept` is not final across
chains (measured 2026-10-01: a SYN accepted in a chain of this half's own was still dropped by the
permission chain), so a second table here would look right and deliver nothing.

It never exits on a bad plan: an office whose link delivers nothing is still an office, and the
screens must be able to say so rather than showing a crash loop. Every failure is printed once and
waited on; the plan is re-read when its file changes.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(os.environ.get("DGO_TUNNEL_DIR", "/tunnel"))
PLAN = BASE / "link-proxy.json"
#: How often the rendered plan is looked at (mtime, cheap, no inotify dependency).
POLL_SECONDS = float(os.environ.get("DGO_LINK_PROXY_POLL", "5"))
#: A connect attempt to the app behind a rule. Short: a delivery that takes longer than this is a
#: broken app, and holding the client's TCP open would only hide it.
CONNECT_TIMEOUT = float(os.environ.get("DGO_LINK_PROXY_CONNECT_TIMEOUT", "5"))

# ── the door (DGO-32) ─────────────────────────────────────────────────────────────────────────────
#: The app whose catalog IS the door's route table: which apps this office serves, under which
#: authority, on which port. Asked over HTTP rather than shipped in the plan, because "which apps do I
#: serve" is a declaration on THIS side and a copy in the plan would be a second answer to it.
SELF_APP = os.environ.get("DGO_SELF_APP", "dgo-extend")
#: The app's link listener (`catalog.LINK_PORT`), the one place the catalog is served.
LINK_PORT = int(os.environ.get("DGO_LINK_PORT", "8984"))
#: How long the route table is trusted. Short: an app that is switched off must stop being reachable,
#: and the fetch is a loopback call to our own app.
ROUTES_TTL = float(os.environ.get("DGO_DOOR_ROUTES_TTL", "30"))
#: Reading the route table is a round trip to our own app, which may itself have to ask the machine
#: which commit it runs (a cold cache once measured 5 s+). Generous on purpose: a door that cannot read
#: its table is a door that answers 404 to every name, and "wait, then answer correctly" is the better
#: failure.
ROUTES_TIMEOUT = float(os.environ.get("DGO_DOOR_ROUTES_TIMEOUT", "25"))
#: A request head is a few hundred bytes. Beyond this it is not a request we can route, and buffering
#: more would only hold a client's connection open to no purpose.
HEAD_LIMIT = 32768
#: The header the serving app reads its user from — the one thing the door WRITES. It is set from the
#: catalog's identity mapping (`to`), because the request crossed a link and the identity of the
#: person who started it is this office's own user vocabulary, not the peer's.
IDENTITY_HEADER = b"x-authentik-username"
#: …and everything the door REMOVES: the whole family, not the one name. A request that crossed a link
#: was authenticated by the OTHER office's identity provider, which that office runs — its groups,
#: e-mail, uid and signed token are that office's claims about itself, and an app here that read
#: `X-authentik-groups` would be taking another office's word for who is an administrator.
IDENTITY_FAMILY = b"x-authentik-"
#: WHICH OFFICE IS ASKING — written by the door, from the link the request arrived on. One door serves
#: one linked office (its rule names it), so this is the link's own fact and never the peer's claim:
#: an app asked to fetch something "from the office that asked" (a move pulls the app's data from
#: there) reads it here, and a peer cannot name a third office in its place.
OFFICE_HEADER = b"x-dgo-office"


def log(message: str) -> None:
    print(f"[dgo-link] {message}", flush=True)


# ── the delivery half: a listener per rule ────────────────────────────────────────────────────────
def _listen(rule: dict) -> socket.socket:
    """The one place a listener is created — for a TCP address AND for a unix socket.

    A unix socket is what the far end of a pair whose tunnel runs on its MACHINE can bind: that end's
    tunnel address is not in this container's namespace at all, so a service ON the machine — the only
    thing that can listen there — bridges into the socket (`converge.REMOTE_DOOR`). One code path, so
    a door is a door wherever it is bound.
    """
    bind = str(rule.get("bind") or "0.0.0.0")
    if bind.startswith("unix:"):
        path = Path(bind[len("unix:"):])
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.unlink()          # a socket file left by a previous process is not a listener
        except OSError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(path))
        os.chmod(path, 0o666)
    else:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((bind, int(rule["port"])))
    srv.listen(64)
    return srv


def _nodelay(sock: socket.socket) -> None:
    """TCP_NODELAY where there is TCP. A UNIX socket (a host door's bridge) refuses the option with
    EOPNOTSUPP, and raising it in a connection thread left that connection open and unanswered —
    measured 2026-10-02 on vps1: every request through a socket door hung until its client timed out."""
    if sock.family in (socket.AF_INET, socket.AF_INET6):
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass


def _pump(src: socket.socket, dst: socket.socket) -> None:
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


class Forwarder(threading.Thread):
    """One rule: listen on `bind:port`, deliver every connection to `target`."""

    def __init__(self, rule: dict):
        super().__init__(daemon=True, name=f"dgo-link-{rule['port']}")
        self.rule = rule
        self.host, self.target_port = str(rule["target"]).rsplit(":", 1)
        self.target_port = int(self.target_port)
        # `_halt`, never `_stop`: Thread has a method of that name, and an Event stored over it makes
        # `join()` raise — which is why a stopped listener was never waited for (`_stop_listener`).
        self._halt = threading.Event()
        self._srv: socket.socket | None = None
        self.ready = threading.Event()
        self.refused = ""

    def run(self) -> None:
        try:
            srv = _listen(self.rule)
        except OSError as e:
            # WHERE it could not bind is the whole diagnosis (an address that is not up yet, a port
            # another process holds), so it is named rather than swallowed.
            self.refused = f"{self.rule['bind']}:{self.rule['port']} — {e.strerror or e}"
            log(f"cannot listen on {self.refused} ({self.rule['office']}/{self.rule['app']})")
            return
        self._srv = srv
        self.ready.set()
        log(f"listening {self.rule['bind']}:{self.rule['port']} → {self.rule['target']} "
            f"({self.rule['office']}/{self.rule['app']}, {self.rule['direction']})")
        srv.settimeout(1.0)
        while not self._halt.is_set():
            try:
                client, _addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if self._halt.is_set():
                client.close()
                break
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()
        try:
            srv.close()
        except OSError:
            pass

    def _serve(self, client: socket.socket) -> None:
        try:
            infos = socket.getaddrinfo(self.host, self.target_port, type=socket.SOCK_STREAM)
            family, socktype, proto, _canon, addr = infos[0]
            upstream = socket.socket(family, socktype, proto)
            upstream.settimeout(CONNECT_TIMEOUT)
            upstream.connect(addr)
            upstream.settimeout(None)
        except OSError as e:
            # The app is named in the log because "connection refused" from the peer's side is
            # otherwise indistinguishable from a link that is down.
            log(f"{self.rule['app']}: nothing answers at {self.rule['target']} ({e.strerror or e})")
            # …and the caller is TOLD, when it is speaking HTTP (everything a link carries is): its
            # request is read first, so the answer is not lost to a reset. A caller that sent no
            # request head gets what it got before — the connection closed.
            head = _head(client)
            if head:
                _say(client, "unreachable", head)
            else:
                try:
                    client.close()
                except OSError:
                    pass
            return
        _nodelay(client)
        _nodelay(upstream)
        up = threading.Thread(target=_pump, args=(client, upstream), daemon=True)
        down = threading.Thread(target=_pump, args=(upstream, client), daemon=True)
        up.start()
        down.start()
        up.join()
        down.join()
        for s in (client, upstream):
            try:
                s.close()
            except OSError:
                pass

    def stop(self) -> None:
        _stop_listener(self)


def _stop_listener(listener) -> None:
    """Close a listener and WAIT until its port is free — for a Forwarder and a Door alike.

    Closing a listening socket from another thread does not release the port while that listener's
    own thread is still inside `accept()`. A rule that CHANGED (same address, new target) was stopped
    and started in one breath, so the new listener found the address in use, gave up, and was still
    counted as applied: measured 2026-10-05 on hp-laptop — the plan's targets changed, the log said
    `cannot listen on 10.79.4.1:9004 — Address already in use` and then `plan applied: 6 listener(s)`,
    and the link's door refused every connection until the container was restarted.
    """
    listener._halt.set()
    if listener._srv is not None:
        try:
            listener._srv.close()
        except OSError:
            pass
    if listener.is_alive() and listener is not threading.current_thread():
        listener.join(timeout=5)


# ── the door: one listener per link, and the Host header picks the app (DGO-32) ───────────────────
def _head(client: socket.socket) -> bytes:
    """The request head, up to and including the blank line — `b""` when there is none.

    The timeout is for READING THE HEAD and is taken off again before this returns. It used to stay
    on the socket, and the copy loops that run after it (`_pump`) read from that same socket: a
    client that had sent its request and was waiting for the answer was "silent" for five seconds,
    the read timed out, and the loop's cleanup shut BOTH directions down. So anything a door carried
    that took longer than five seconds to answer was cut — a call that waits for a job, a download,
    an event stream, a websocket whose client had nothing to say (measured 2026-10-05: the MacBook
    asked hp-laptop to bring an app up, hp-laptop started doing it, and the MacBook read 502; then
    hp-laptop's fetch of a 40 MB archive through the MacBook's door ended "closed without
    response"). A door has an opinion about how long a HEAD may take to arrive, and none about how
    long an app may take to answer.
    """
    buf = b""
    client.settimeout(CONNECT_TIMEOUT)
    try:
        while b"\r\n\r\n" not in buf:
            try:
                chunk = client.recv(4096)
            except OSError:
                return b""
            if not chunk:
                return b""
            buf += chunk
            if len(buf) > HEAD_LIMIT:
                return b""
        return buf
    finally:
        try:
            client.settimeout(None)
        except OSError:
            pass


# ── what the door says for ITSELF ─────────────────────────────────────────────────────────────
# Three things only the link can know, and it used to answer each with nothing: an empty `404`, an
# empty `502`, or a closed connection. Behind a console's own proxy that became the console's card;
# on a real domain a linked office's app is framed on a host the edge serves STRAIGHT from this
# door, so the empty answer WAS the frame — the owner's only sign, once, that a tunnel had been dead
# for fifteen hours (issues/a-linked-office-tile-fails-blank-and-no-surface-says-why.yaml).
#
# A request for a PAGE gets a card, in Hebrew, that asks again by itself. Anything else (an API
# call, an asset, a websocket) gets the status with no body, as before. Either way the answer
# carries `X-Dgo-Door: <reason>`, so whoever sits in front can tell "the door said so" from "the
# app said so" and show a better-informed card of its own.
DOOR_HEADER = b"X-Dgo-Door"


def _palette() -> str:
    """The office's palette, from the copy this app's own screen carries (static/index.html — G27
    keeps it). The card names its tokens, so it is the office's colours on the reader's light or dark
    ground, and no second copy of them is written here. A file that cannot be read gives a card in
    the browser's own colours — a card all the same."""
    name = "bina-theme-tokens"          # the marked region, as the console's own card reads its (app.py: _static_block)
    try:
        page = (Path(__file__).resolve().parent / "static" / "index.html").read_text(encoding="utf-8")
        return page.split(f"/* @{name}:start */", 1)[1].split(f"/* @{name}:end */", 1)[0]
    except (OSError, IndexError):
        return ""


_CARD = ('<!doctype html><html lang="he" dir="rtl" data-card><head><meta charset="utf-8">'
         '<meta http-equiv="refresh" content="15"><meta name="viewport" content="width=device-width, initial-scale=1">'
         '<title>%s</title><style>' + _palette().replace("%", "%%") +
         'body{margin:0;background:var(--bg);color:var(--ink);font-family:"Segoe UI",system-ui,'
         '"Noto Sans Hebrew",Arial,sans-serif;font-size:14px;line-height:1.6;display:grid;place-items:center;'
         'min-height:100vh}.c{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:22px 26px;'
         'max-width:34em;margin:16px}p{margin:8px 0 0;color:var(--muted)}</style></head><body><div class="c"><b>%s</b>'
         '<p>%s</p><p>המסך הזה בודק שוב בעצמו.</p></div></body></html>')
_SAID = {
    "no-app": (b"404 Not Found", "האפליקציה לא ניתנת כאן",
               "הלשכה ענתה, אבל היא לא נותנת אפליקציה בשם הזה ללשכות מקושרות."),
    "app-down": (b"502 Bad Gateway", "האפליקציה לא עונה",
                 "הלשכה שמריצה את האפליקציה ענתה, אבל האפליקציה עצמה לא עונה כרגע — היא כבויה או מופעלת מחדש."),
    "unreachable": (b"502 Bad Gateway", "הלשכה לא ענתה",
                    "הלשכה שמריצה את האפליקציה לא ענתה דרך הקישור — היא כבויה, מנותקת מהרשת, או שהמנהרה נפלה."),
}


def _say(client: socket.socket, reason: str, head: bytes = b"") -> None:
    """Answer for the door itself and close. Never raises: the client may already be gone."""
    status, title, text = _SAID[reason]
    accept = next((ln for ln in head.split(b"\r\n")[1:] if ln.lower().startswith(b"accept:")), b"")
    page = b"text/html" in accept.lower()
    body = (_CARD % (title, title, text)).encode("utf-8") if page else b""
    try:
        client.sendall(b"HTTP/1.1 " + status + b"\r\n" + DOOR_HEADER + b": " + reason.encode("ascii") + b"\r\n"
                       + (b"Content-Type: text/html; charset=utf-8\r\n" if page else b"")
                       + b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\nConnection: close\r\n\r\n" + body)
    except OSError:
        pass
    try:
        client.close()
    except OSError:
        pass


def _host_of(head: bytes) -> str:
    """The authority this request is for: lowercased, without its port."""
    for line in head.split(b"\r\n")[1:]:
        if not line:
            break
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"host":
            return value.strip().decode("latin-1").lower().split(":", 1)[0]
    return ""


class Door(threading.Thread):
    """The serving office's door: ONE listener, and the Host header picks the app behind it.

    Why here and not on the edge: this office's registry holds four apps on 8080, two on 8000 and two
    on 8977, and a link that opens one listener per app must collide or pick a winner silently
    (measured on vps1 2026-10-02 — the plan was refused and nothing was served at all). A name is not a
    scarce resource; a port is.

    It is deliberately NOT a second edge: no TLS, no opinion about paths, and after the first request's
    head it copies bytes both ways and nothing else — which is what keeps a websocket and a large
    upload working without this file knowing about either. What it DOES decide is which app the request
    is for (the authority the consuming office wrote, from this office's own catalog) and the identity
    it becomes (the mapping this office published for that app).
    """

    def __init__(self, rule: dict):
        super().__init__(daemon=True, name=f"dgo-door-{rule['port']}")
        self.rule = rule
        self._halt = threading.Event()
        self._srv: socket.socket | None = None
        self._routes: dict[str, tuple] = {}
        self._at = 0.0
        self._refreshing = threading.Event()
        self.ready = threading.Event()
        self.refused = ""
        # THE CATALOG LISTENER is a door with ONE place to go (`fixed`): the app's link listener,
        # whatever Host the peer wrote. It was a plain splice, and a splice cannot say who is asking
        # — so every linked office read the same catalog, and one that is given less than the rest
        # (`serve.only`) could not be told apart. Through here the request reaches the app with the
        # office this pair belongs to written on it, and with whatever the peer claimed removed.
        self.fixed: tuple | None = None
        if rule.get("kind") != "door":
            name, _, port = str(rule.get("target") or "").rpartition(":")
            self.fixed = (name, int(port), "")

    # ── the route table: this office's own catalog ────────────────────────────────────────────────
    def _fetch(self) -> dict:
        # Asked in the name of the office this door belongs to: the table is what THAT office is
        # given, so a name it was not given is "no app under that name" here, at the door.
        url = urllib.request.Request(f"http://{SELF_APP}:{LINK_PORT}/api/link/catalog",
                                     headers={OFFICE_HEADER.decode(): str(self.rule.get("office") or "")})
        try:
            with urllib.request.urlopen(url, timeout=ROUTES_TIMEOUT) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:         # the app ANSWERED — its body is the reason
            log(f"{SELF_APP} refused the route table ({e.code}: "
                f"{e.read()[:300].decode('utf-8', 'replace')}) — "
                f"keeping the previous one ({len(self._routes)} name(s))")
            return {}
        except Exception as e:                      # noqa: BLE001 — never die on one bad plan
            log(f"the route table could not be read from {SELF_APP} ({type(e).__name__}: {e}) — "
                f"keeping the previous one ({len(self._routes)} name(s))")
            return {}

    def routes(self) -> dict:
        now = time.time()
        if self._at and now - self._at < ROUTES_TTL:
            return self._routes
        self._at = now
        if self._routes:
            # STALE-WHILE-REVALIDATE. A request must never wait on the route table's refresh once a
            # table exists: the refresh is a catalog fetch, the catalog's commit is a git read through
            # `computers`, and a slow minute there stalled every request that happened to expire the
            # TTL (measured 2026-10-02 from vps1: the Mac's Bina tile timed out for two minutes, twice,
            # while the tunnel and the agent port answered). The table changes when an office's serve
            # list changes — seconds of staleness cost nothing; a 25 s wait in a page load costs the page.
            if not self._refreshing.is_set():
                self._refreshing.set()
                threading.Thread(target=self._refresh_bg, daemon=True, name="dgo-door-routes").start()
            return self._routes
        doc = self._fetch()
        if not doc:
            # Nothing known yet (dgo-extend restarting, measured 2026-10-02: one refused fetch at
            # boot and every request 404'd for the full TTL). Ask again in a few seconds rather
            # than serving "no app under that name" for half a minute.
            self._at = now - ROUTES_TTL + 3
            return self._routes
        self._routes = self._table(doc)
        return self._routes

    def _refresh_bg(self) -> None:
        try:
            doc = self._fetch()
            if doc:
                self._routes = self._table(doc)
        finally:
            self._refreshing.clear()

    @staticmethod
    def _table(doc: dict) -> dict:
        table: dict[str, tuple] = {}
        for app in doc.get("apps") or []:
            if not isinstance(app, dict):
                continue
            name = str(app.get("app") or app.get("alias") or "").strip().lower()
            alias = str(app.get("alias") or name).strip().lower()
            try:
                port = int(app.get("port"))
            except (TypeError, ValueError):
                continue
            if not name or not 1 <= port <= 65535:
                continue
            ident = str((app.get("identity") or {}).get("to") or "")
            # WHAT TO CONNECT TO: the app's own compose service, not its id. The two differ for a
            # real app (`indox` is `incoming-documents`), and connecting to the id is a DNS failure
            # answered as `502` — the shape of "the office is linked and one app is missing", which
            # is the hardest kind of gap to notice.
            upstream = str(app.get("service") or "").strip().lower() or name
            host = str(app.get("host") or "").strip().lower()
            if host:
                table[host] = (upstream, port, ident)
            # The FIRST LABEL, always: an app with no declared authority (`host: ""`) is reached under
            # the consuming office's own nested name — `<alias>.<office>.console.<its domain>` — which
            # this office cannot know, and the alias is the only part of it that is ours.
            if alias:
                table.setdefault(alias, (upstream, port, ident))
        return table

    def route(self, host: str) -> tuple | None:
        if self.fixed is not None:
            return self.fixed
        table = self.routes()
        if not table:
            return None
        if host in table:
            return table[host]
        first = host.split(".", 1)[0]
        return table.get(first)

    # ── one connection ────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def websocket(head: bytes) -> bool:
        """Is this head a websocket handshake — the one request after which a connection stays open?"""
        raw = head.split(b"\r\n\r\n", 1)[0].split(b"\r\n")
        fields = {}
        for line in raw[1:]:
            name, _, value = line.partition(b":")
            fields[name.strip().lower()] = value.strip().lower()
        return (raw[0].startswith(b"GET ") and fields.get(b"upgrade") == b"websocket"
                and b"upgrade" in fields.get(b"connection", b""))

    @staticmethod
    def rewrite(head: bytes, ident: str, office: str = "") -> bytes:
        """The head as the app must see it: the peer's identity claims REMOVED, ours written — the
        user it becomes here (`ident`) and the office it came from (`office`, see OFFICE_HEADER).

        The identity is not forwarded, it is replaced: a request that crossed a link arrives from a
        person this office never authenticated, and what it carries is the other office's user
        vocabulary (`IDENTITY_FAMILY`). The mapping in the catalog is what turns it into a user of
        THIS office.

        And it is ONE request per connection, except a websocket. The door rewrites the head it reads
        and copies bytes after it, so a second request on a kept-alive connection would reach the app
        with the peer's own claims intact. `Connection: close` is therefore written for every request
        that is not a websocket handshake — decided from the whole handshake (`websocket`), never
        from the word `upgrade` alone, which any client can send with an ordinary request to keep the
        socket (found 2026-10-05, reading this function).
        """
        # The HEAD only. `_head()` returns everything the first reads delivered, which for a POST
        # includes the start of its body; iterating that as header lines turned `{}` into a header
        # and every API call into a 400 (measured 2026-10-02 through the MacBook's door: direct → 404,
        # door → 400, for the same request). The caller sends the body bytes after this head.
        raw = head.split(b"\r\n\r\n", 1)[0].split(b"\r\n")
        lines = [raw[0]]
        for line in raw[1:]:
            name = line.split(b":", 1)[0].strip().lower()
            if line and name not in (b"connection", OFFICE_HEADER) and not name.startswith(IDENTITY_FAMILY):
                lines.append(line)
        lines.append(b"Connection: Upgrade" if Door.websocket(head) else b"Connection: close")
        if ident:
            lines.append(IDENTITY_HEADER.title() + b": " + ident.encode("latin-1"))
        if office:
            lines.append(OFFICE_HEADER.title() + b": " + office.encode("latin-1"))
        return b"\r\n".join(lines) + b"\r\n\r\n"

    def _serve(self, client: socket.socket) -> None:
        head = _head(client)
        if not head:
            client.close()
            return
        host = _host_of(head)
        route = self.route(host)
        if route is None:
            # A name nothing is served under is answered, not hung: the consuming side shows a page
            # that says what happened instead of a timeout nobody can read.
            log(f"{host or '(no Host header)'}: no app is served under that name")
            _say(client, "no-app", head)
            return
        name, port, ident = route
        try:
            infos = socket.getaddrinfo(name, port, type=socket.SOCK_STREAM)
            family, socktype, proto, _canon, addr = infos[0]
            upstream = socket.socket(family, socktype, proto)
            upstream.settimeout(CONNECT_TIMEOUT)
            upstream.connect(addr)
            upstream.settimeout(None)
        except OSError as e:
            log(f"{host}: nothing answers at {name}:{port} ({e.strerror or e})")
            _say(client, "app-down", head)
            return
        rest = head[head.index(b"\r\n\r\n") + 4:]
        try:
            upstream.sendall(self.rewrite(head, ident, str(self.rule.get("office") or "")) + rest)
            if self.websocket(head):
                # A websocket is the one connection that stays open — and only once the APP has
                # agreed to it. Until its `101` nothing more of the client's is forwarded: an app
                # that answers anything else has kept an ordinary connection, and what the client
                # sends next on it would be a request this door never rewrote.
                answer = _head(upstream)
                client.sendall(answer)
                if not answer.startswith(b"HTTP/1.1 101"):
                    _pump(upstream, client)
                    upstream.close()
                    client.close()
                    return
                upstream.settimeout(None)
        except OSError:
            upstream.close()
            client.close()
            return
        _nodelay(client)
        _nodelay(upstream)
        up = threading.Thread(target=_pump, args=(client, upstream), daemon=True)
        down = threading.Thread(target=_pump, args=(upstream, client), daemon=True)
        up.start()
        down.start()
        up.join()
        down.join()
        for s in (client, upstream):
            try:
                s.close()
            except OSError:
                pass

    def run(self) -> None:
        try:
            srv = _listen(self.rule)
        except OSError as e:
            self.refused = f"{self.rule['bind']}:{self.rule['port']} — {e.strerror or e}"
            log(f"cannot listen on {self.refused} ({self.rule['office']}/{self.rule['app']})")
            return
        self._srv = srv
        self.ready.set()
        log(f"door listening {self.rule['bind']}:{self.rule['port']} — "
            + ("Host picks the app" if self.fixed is None else f"the catalog, at {self.rule.get('target')}")
            + f" ({self.rule['office']})")
        srv.settimeout(1.0)
        while not self._halt.is_set():
            try:
                client, _addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if self._halt.is_set():
                client.close()
                break
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()
        try:
            srv.close()
        except OSError:
            pass

    def stop(self) -> None:
        _stop_listener(self)


# ── the loop: keep the running listeners equal to the rendered plan ───────────────────────────────
class Proxy:
    def __init__(self) -> None:
        self.forwarders: dict[tuple[str, int], Forwarder] = {}
        self._stamp: tuple = ()
        self._seen_missing = ""

    def _load(self) -> tuple[tuple, dict]:
        try:
            raw = PLAN.read_text(encoding="utf-8")
            stamp = (PLAN.stat().st_mtime_ns, len(raw))
            return stamp, json.loads(raw)
        except OSError:
            return (0, 0), {}
        except ValueError as e:
            log(f"the rendered plan is not readable JSON ({e}) — keeping what is running")
            return (0, 0), {}

    def _in_tunnel_namespace(self, rules: list) -> bool:
        """Is the address these rules bind actually HERE?

        `network_mode: service:dgo-net` binds this container to the tunnel container's namespace AT
        START. Recreating the tunnel container alone therefore leaves this process in the namespace of
        a container that no longer exists — no `wg0`, no tunnel address — and the listeners then fail
        with `EADDRNOTAVAIL` while every other check still reads green. Measured 2026-10-01: after
        `dc up -d --build dgo-net`, `10.79.2.1` was unreachable from the peer for as long as nobody
        recreated this container. When the tunnel container was only RESTARTED, restarting this one
        is enough (a restart rejoins the current namespace of the same container), so this notices,
        exits and lets `restart: unless-stopped` do it. When it was REPLACED there is nothing left to
        rejoin: that case is `netns_rejoin` (scripts/lib.sh), which recreates this container after
        every `up`.
        """
        wanted = {str(r.get("bind")) for r in rules
                  if str(r.get("bind")) not in ("0.0.0.0", "") and not str(r.get("bind")).startswith("unix:")}
        if not wanted:
            return True
        have = set()
        try:
            out = subprocess.run(["ip", "-4", "addr", "show"], capture_output=True, text=True,
                                 timeout=15).stdout
        except (OSError, subprocess.TimeoutExpired):
            return True                      # cannot tell → do not kill a working proxy
        for line in out.splitlines():
            parts = line.split()
            if "inet" in parts:
                have.add(parts[parts.index("inet") + 1].split("/")[0])
        return bool(wanted & have)

    def sync(self) -> None:
        stamp, plan = self._load()
        # An unchanged plan is left alone only while every listener of it is LISTENING: one that
        # could not bind (`refused`) or whose thread ended is tried again on the next pass, so "plan
        # applied" is never said of a door that is not there.
        if stamp == self._stamp and all(f.is_alive() and not f.refused for f in self.forwarders.values()):
            return
        self._stamp = stamp
        rules = plan.get("rules") or []
        if not rules and not plan:
            if self._seen_missing != "empty":
                self._seen_missing = "empty"
                log("no plan rendered yet (/tunnel/link-proxy.json) — waiting. The app writes it from "
                    "the office's own `serve:` list and its links")
            return
        self._seen_missing = ""
        if not self._in_tunnel_namespace(rules):
            # Exit rather than wait: `restart: unless-stopped` brings this container back into the
            # namespace the tunnel container has NOW, which is the only place these rules can bind.
            log("the tunnel address is not in this namespace — the tunnel container was recreated "
                "without this one. Exiting so the restart rejoins it.")
            sys.exit(2)
        # One listener per ADDRESS and port, which is what a socket is — not per port. A link the
        # owner made bidirectional holds the catalog port twice in this namespace (the `serve` door on
        # the tunnel address, the `use` door on this container's own address; `linkproxy._same_door`
        # renders exactly that as legal). Keyed by port alone, the second rule silently replaced the
        # first: measured 2026-10-01 on the MacBook, 4 rules → "3 listener(s)", and the peer's pulls of
        # 10.79.2.1:8983 were refused while every screen said the plan was applied.
        wanted = {(str(r.get("bind") or "0.0.0.0"), int(r["port"])): r for r in rules}
        for key in sorted(set(self.forwarders) - set(wanted)):
            log(f"rule for {key[0]}:{key[1]} is gone — closing its listener")
            self.forwarders.pop(key).stop()
        for key, rule in sorted(wanted.items()):
            current = self.forwarders.get(key)
            if current is not None and current.rule == rule and current.is_alive() and not current.refused:
                continue
            if current is not None:
                current.stop()
            # A SERVING door routes by Host (the app behind it is decided per request, from this
            # office's catalog), and the serving CATALOG listener is a door with one place to go
            # (`Door.fixed`): both write which office is asking. Everything else is a plain splice —
            # including the CONSUMING half of a door, which must carry the Host header the consuming
            # edge wrote to the peer unchanged, and an agent API's own port.
            serving = rule.get("direction") == "serve"
            f = Door(rule) if serving and (rule.get("kind") == "door" or str(rule.get("app")) == SELF_APP) \
                else Forwarder(rule)
            f.start()
            self.forwarders[key] = f
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and any(
                f.is_alive() and not f.ready.is_set() for f in self.forwarders.values()):
            time.sleep(0.05)
        listening = sum(1 for f in self.forwarders.values() if f.ready.is_set() and f.is_alive())
        log(f"plan applied: {listening} listener(s) for {len(rules)} rule(s)"
            + ("" if listening == len(rules) else " — the rest are tried again on the next pass"))

    def run(self) -> None:
        while True:
            try:
                self.sync()
            except Exception as e:                      # noqa: BLE001 — never die on one bad plan
                log(f"sync failed ({type(e).__name__}: {e}) — retrying")
            time.sleep(POLL_SECONDS)


def check() -> int:
    """`--check`: is the plan renderable, and is every rule ANSWERING in this namespace?

    Read-only: it never binds and never changes anything, so the gate can run it while the proxy
    is live.
    Exits non-zero with the reason, because "the link exists" is exactly the claim that must not be
    made from a file's presence.
    """
    try:
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"no usable plan at {PLAN} ({e})")
        return 1
    rules = plan.get("rules") or []
    if not rules:
        print("the plan declares no delivery rule")
        return 1
    bad = 0
    for rule in rules:
        bind = str(rule.get("bind") or "0.0.0.0")
        probe = "0.0.0.0" if bind == "0.0.0.0" else bind
        try:
            if bind.startswith("unix:"):
                # A socket rule is proved the same way a port is: something has to be listening. The
                # host-side bridge is what a PERSON cannot see, so it is measured here rather than
                # assumed from the plan.
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(CONNECT_TIMEOUT)
                s.connect(bind[len("unix:"):])
            else:
                s = socket.create_connection((probe, int(rule["port"])), timeout=CONNECT_TIMEOUT)
            s.close()
            print(f"OK   {rule['bind']}:{rule['port']} → {rule['target']} "
                  f"({rule['office']}/{rule['app']})")
        except OSError as e:
            bad += 1
            print(f"FAIL {rule['bind']}:{rule['port']} → {rule['target']} "
                  f"({rule['office']}/{rule['app']}): {e.strerror or e}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="the link proxy — what a link delivers, not what it allows")
    ap.add_argument("--check", action="store_true",
                    help="verify the rendered plan answers here, then exit")
    args = ap.parse_args()
    if args.check:
        return check()
    log(f"starting from {BASE} (plan {PLAN})")
    Proxy().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
