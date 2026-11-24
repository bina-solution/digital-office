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
import hashlib
import hmac
import json
import os
import re
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
#: What the consuming side writes about a mapping: its `from` list, the peer's own user names that map onto the
#: served identity. It is written by the `dgo-remote-<office>-identity` middleware (platform/manager/serve.py
#: and its Go twin) and by the console's `_as_remote`. Nothing on the serving side reads it, and a peer can
#: write anything there, so the door removes it along with the identity it replaces (hos-006, DGO-1155).
FROM_HEADER = b"x-dgo-from"
#: THE PEER IS THE HERD'S, BY KEY (DGO-1800) — written `1` by the door on the requests of a rule the delivery plan
#: marked (`herd: true`: linkproxy.build_multi, decided by give.herd_peer from both offices' WireGuard keys), and
#: REMOVED from every request on every rule, so a peer can never say it of itself. An app behind the door believes it
#: only from the door's own address, as it does x-dgo-office (apps/computers narrows what a non-herd office reads).
HERD_HEADER = b"x-dgo-herd"
#: What the door may write as the mapped user: the rule `platform/manager/serve.py`'s HEADER_RE holds.
#: A value stored before that rule was asked ("owner\n") is never written — a line break in a header
#: value ends the head early, and the signature line would carry it too (DGO-622).
HEADER_VALUE = re.compile(r"^[A-Za-z0-9@._+\-]{1,128}\Z")
#: An authority this door writes into `Host:` — `platform/manager/serve.py`'s AUTHORITY_RE.
AUTHORITY = re.compile(r"^[a-z0-9]([a-z0-9.\-]{0,251})?(:\d{1,5})?\Z")
#: A door's path allow-list entry (DGO-945) — `catalog.PATH_RE`: absolute, plain segments only, and
#: linear: each repeat ends at its slash (a nested `(…+/?)*` backtracked for hours on one request line).
PATH = re.compile(r"^/(?:[A-Za-z0-9._~-]+/)*[A-Za-z0-9._~-]*\Z")
#: A REQUEST's target, read against those entries: the same plain segments, and a colon inside one — RFC 3986's own
#: pchar, and every digest a registry is asked by (`/v2/<name>/blobs/sha256:<hex>`; DGO-2123: through the link the
#: image store's manifest came by tag and nothing by digest). Nothing that could be read two ways comes with it: an
#: absolute-form target never starts with `/`, `//` is an empty segment the pattern refuses, and `%`, `\` and dot
#: segments stay refused. The declared entries keep PATH, catalog.PATH_RE's twin.
TARGET = re.compile(r"^/(?:[A-Za-z0-9._~:-]+/)*[A-Za-z0-9._~:-]*\Z")
#: The headers that say where a request CAME FROM. A door with no tile is called by a machine, and the
#: service behind it may decide by the caller's address (n8n's webhook allow-list reads `req.ip`
#: through one trusted hop), so what the peer claims about it is removed, never passed on.
FORWARDED = (b"x-forwarded-for", b"x-real-ip", b"forwarded", b"x-forwarded-host", b"x-forwarded-proto")


def _plain_path(p) -> bool:
    return isinstance(p, str) and bool(PATH.match(p)) and "/../" not in f"{p}/" and "/./" not in f"{p}/"


def _plain_target(p) -> bool:
    """A request target the door can read one way only — `_plain_path`'s rule, with a colon inside a segment."""
    return isinstance(p, str) and bool(TARGET.match(p)) and "/../" not in f"{p}/" and "/./" not in f"{p}/"


def _path_allowed(head: bytes, paths: tuple) -> bool:
    """Is the request line's target one of `paths` — or under one that ends in `/`? Exact otherwise:
    `/webhook/meet-recordings` is that webhook, never `/webhook/meet-recordings/<another one>`. Read
    from the RAW target and refused when it could be read two ways: an absolute-form URL, an escape
    (`%2e%2e`), a dot segment or a backslash — the service would resolve those, and the check would
    have passed the wrong path."""
    line = head.split(b"\r\n", 1)[0].decode("latin-1")
    parts = line.split(" ")
    if len(parts) != 3:
        return False
    target = parts[1].split("?", 1)[0].split("#", 1)[0]
    if not target.startswith("/") or "%" in target or "\\" in target or not _plain_target(target):
        return False
    return any(target == p or (p.endswith("/") and target.startswith(p)) for p in paths)


def _split_head(head: bytes) -> bool:
    """Does a header line hold a bare CR or LF? A line this door reads as ONE header, the app's
    parser (Python's email parser behind http.server, among others) reads as TWO — so a peer could
    hide an `x-dgo-office` or an identity header from the stripping inside another header's value
    (second reader, DGO-945). Such a head is refused, never repaired."""
    block = head.split(b"\r\n\r\n", 1)[0]
    return any(b"\r" in line or b"\n" in line for line in block.split(b"\r\n"))

# ── the identity, PROVED (DGO-545) ───────────────────────────────────────────────────────────────
#: The signature that makes `x-authentik-username` checkable. That header is written by the door for
#: every request that crosses a link, and any container on this office's network can write one too —
#: which is exactly why the app that has to believe it (apps/project-pln/office_identity.py) refuses a
#: bare one, and why a browser on a LINKED office's console never got past Plane's own sign-in. Over a
#: link there is no cookie to ask this office's provider about: the person was authenticated by the
#: OTHER office, whose answer is not ours to verify. So the door PROVES what it writes.
#:
#: The key is the pair's own secret, from the credential plane (`dgo_link*` — the value the pairing
#: exchanged, or the one a converge wrote for a declared office; both ends hold it and nobody else
#: does). What is signed is the protocol version, the office this door serves, the user the request
#: becomes here, and the moment — so a signature is worthless to anyone who cannot read the vault, and
#: stale within SIG_WINDOW seconds. An app verifies it by reading its own copy of the same secret.
#:
#: One header, space-separated. The reader is apps/project-pln/office_identity.py, so this line is a
#: contract between two apps and is written out in apps/dgo-extend/README.md § "the door's signature":
#:
#:     x-dgo-identity: v1 <office> <user> <unix-seconds> <hex hmac-sha256 of "v1\n<office>\n<user>\n<ts>">
ID_HEADER = b"x-dgo-identity"
SIG_VERSION = "v1"
#: How long a signature is good for. The two offices are the owner's own machines, minutes apart at
#: worst, and a request that took longer than this to be delivered is not one this door is carrying.
SIG_WINDOW = 300
CONNECTIONS_URL = (os.environ.get("CONNECTIONS_URL") or "http://connections:8990").rstrip("/")
#: `office -> (read_at, token)`. Read once per office per SIG_TTL: the vault is a service this door
#: must not call per request, and a pair's secret does not rotate under a live link.
SIG_TTL = 60.0
_LINK_SECRETS: dict = {}
_LINK_SECRETS_LOCK = threading.Lock()


def log(message: str) -> None:
    print(f"[dgo-link] {message}", flush=True)


def signed_text(office: str, user: str, ts: int) -> str:
    """What is signed, and the whole of it. A function so the two halves cannot drift."""
    return f"{SIG_VERSION}\n{office}\n{user}\n{int(ts)}"


def link_secret(office: str) -> str:
    """The secret this office shares with ONE linked office — the credential plane's own row.

    Found by NAME, the same way `apps/dgo-extend/links.py` and `scripts/bbox_agent/client.py` find a
    link's credentials: every `dgo_link` instance whose id names that office, first match wins. The id
    is derived from facts both ends see (`dgo_link-<peer>`, or `dgo_link-<office>-<peer>-<direction>`
    for a declared one), so the serving side and the app that verifies the signature look for the same
    names — and a token that is missing (vault down, a link nobody wrote a secret for) is a LINK whose
    identity cannot be proved, which is said in the log rather than papered over.
    """
    office = (office or "").strip().lower()
    if not office:
        return ""
    now = time.time()
    with _LINK_SECRETS_LOCK:
        hit = _LINK_SECRETS.get(office)
        if hit and now - hit[0] < SIG_TTL:
            return hit[1]
    token = ""
    try:
        with urllib.request.urlopen(
                f"{CONNECTIONS_URL}/api/instances?protocol=dgo_link", timeout=8) as r:
            rows = (json.loads(r.read() or b"{}").get("instances") or [])
        for row in rows:
            iid = str((row or {}).get("id") or "")
            # an agent's credential a linked office handed over is not the pair's secret (DGO-1127),
            # and `dgo_link-serve-vps1-…-agent` sorts before `dgo_link-vps1`
            if iid.startswith("dgo_link-serve-") and iid.endswith("-agent"):
                continue
            if not names_office(row, office):
                continue
            with urllib.request.urlopen(
                    f"{CONNECTIONS_URL}/api/instances/{iid}/secret", timeout=8) as r:
                token = str((json.loads(r.read() or b"{}").get("secret") or {}).get("token") or "")
            if token:
                break
    except (urllib.error.URLError, OSError, ValueError, TypeError) as e:
        log(f"cannot read the link secret for {office} ({e}) — this door will pass the identity "
            f"UNSIGNED, and an app that requires a signature will ask for a sign-in")
        return ""
    if not token:
        log(f"no dgo_link credential names {office} — the identity this door writes for it is UNSIGNED")
    with _LINK_SECRETS_LOCK:
        _LINK_SECRETS[office] = (now, token)
    return token


def names_office(row: dict, office: str) -> bool:
    """Is this `dgo_link` row the link with `office`? A pairing writes `dgo_link-<office>`; a converge writes
    `dgo_link-<a>-<b>-<direction>` with `<a>-><b> <direction>` in its hint. Exact names only, never a split on
    `-`: office ids carry hyphens (hp-laptop, portable-ubuntu), and that split left them with no signed identity
    (hos-005). The checker, apps/project-pln/office_identity.py, matches the same way."""
    iid = str((row or {}).get("id") or "").lower()
    if iid == f"dgo_link-{office}":
        return True
    hint = str((row or {}).get("account_hint") or "").lower().split(" ", 1)[0]
    return office in hint.split("->") if "->" in hint else False


def identity_signature(office: str, user: str) -> bytes:
    """The `x-dgo-identity` value for one request — empty when it cannot be proved."""
    if not (office and user):
        return b""
    secret = link_secret(office)
    if not secret:
        return b""
    ts = int(time.time())
    mac = hmac.new(secret.encode("utf-8"), signed_text(office, user, ts).encode("utf-8"),
                   hashlib.sha256).hexdigest()
    return f"{SIG_VERSION} {office} {user} {ts} {mac}".encode("latin-1")


# ── the access record (DGO-890): every request another office made through this office's door ────
# The owner, 2026-10-21: "dgo extend should log exactly the app its sharing between dgo as there
# accesed". One JSON line per request — which office asked, for which app, as which user here, what it
# asked, what the app answered, how many bytes each way and how long it took — appended to a volume
# the app (dgo-extend's API, `GET /api/link/access`) reads and the security app shows. The record is
# written AFTER the connection closes (one request per connection, see `Door.rewrite`), so it costs
# the request nothing; a write that fails is dropped, never raised into the connection.
ACCESS_LOG = Path(os.environ.get("DGO_DOOR_ACCESS_LOG", "/doorlog/door-access.jsonl"))
ACCESS_MAX_BYTES = int(os.environ.get("DGO_DOOR_ACCESS_MAX_BYTES", str(20 * 1024 * 1024)))
_access_lock = threading.Lock()


def access_record(rec: dict) -> None:
    try:
        with _access_lock:
            # `end`, the wall clock when the line is written, under the lock that orders the file: the log's
            # order exactly. `ts` is the request's start and `ms` is monotonic, so `ts + ms` drifts from it by a
            # clock step during a long connection; dgo-extend `_door_access` searches the log by this (DGO-1769).
            rec["end"] = round(time.time(), 3)
            line = (json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            ACCESS_LOG.parent.mkdir(parents=True, exist_ok=True)
            try:
                if ACCESS_LOG.stat().st_size > ACCESS_MAX_BYTES:
                    os.replace(ACCESS_LOG, ACCESS_LOG.with_name(ACCESS_LOG.name + ".1"))
            except FileNotFoundError:
                pass
            with open(ACCESS_LOG, "ab") as fh:
                fh.write(line)
    except OSError:
        pass


def _request_line(head: bytes) -> tuple:
    """(method, path) of a request head; ('', '') when the first line is not one."""
    first = head.split(b"\r\n", 1)[0].decode("latin-1", "replace").split(" ")
    if len(first) >= 2:
        return first[0][:16], first[1][:300]
    return "", ""


def _status_of(first: bytes) -> int:
    """The status of an HTTP answer from its first bytes (`HTTP/1.1 200 OK`); 0 when there is none."""
    try:
        parts = first.split(b"\r\n", 1)[0].split(b" ")
        return int(parts[1]) if parts[0].startswith(b"HTTP/") else 0
    except (IndexError, ValueError):
        return 0


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


def _pump(src: socket.socket, dst: socket.socket, meter: dict | None = None) -> None:
    """Copy one direction until it ends. `meter` (optional) is told how many bytes passed and keeps the
    first bytes — what the access record reads the app's status from."""
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            if meter is not None:
                meter["bytes"] = meter.get("bytes", 0) + len(data)
                if not meter.get("first"):
                    meter["first"] = data[:64]
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


# ── WHO MAY ARRIVE at a serve rule (issues/a-peer-on-one-tunnel-can-reach-another-pairs-catalog-listener-…) ──
# A serve rule's `clients` is its pair's PEER tunnel address (linkproxy: `[peer_addr]`), and WireGuard pins a
# peer's packets to it — but WireGuard checks only a packet's SOURCE, and the kernel answers any local address on
# any interface. So a peer that widens its own AllowedIPs can reach ANOTHER pair's catalog listener (every pair's
# is on the same port, each bound to its own pair address) and be stamped as that pair's office. A connection from
# an address the rule does not name is OUTSIDE. Stage 1 (AGENTS rule 8: enumerate, warn, then refuse): it is SAID —
# one log line per listener and address, and `outside` on the door's access record (dgo-extend's
# `/api/link/access` returns it; the security app's ingest does not copy it yet) — and served as before.
# DGO_LINK_CLIENTS=refuse in this process's environment closes it instead; stage 2 makes that the default once
# the counts say no legitimate caller is outside (`--check` connects from inside the namespace and is said too).
# A use rule names no clients (this office's own apps). A unix-socket door has no address, so the far end whose
# tunnel runs on its machine (`converge.REMOTE_DOOR`) is NOT covered here: its host bridge must judge it.
CLIENTS_MODE = (os.environ.get("DGO_LINK_CLIENTS") or "warn").strip().lower()
_SAID_OUTSIDE: set = set()


def outside(rule: dict, peer: str) -> bool:
    """Is `peer` an address this SERVE rule does not name in its `clients`? Never for a use rule, a rule that names
    no clients, or a connection with no address (a unix socket)."""
    clients = rule.get("clients") or []
    if isinstance(clients, str):
        clients = [clients]
    if not isinstance(clients, (list, tuple, set, frozenset)):
        return False                # a shape nobody renders (a hand-edited plan): judged by nothing, never a crash
    peer = str(peer or "").replace("::ffff:", "", 1)
    return rule.get("direction") == "serve" and bool(clients) and bool(peer) \
        and peer not in {str(c) for c in clients}


def admit(rule: dict, peer: str) -> bool:
    """Whether to serve a connection from `peer`. Outside is said once per listener and address (bounded), then
    served (stage 1) — or closed when DGO_LINK_CLIENTS=refuse."""
    if not outside(rule, peer):
        return True
    refuse = CLIENTS_MODE == "refuse"
    key = (str(rule.get("bind")), rule.get("port"), str(peer))
    if key not in _SAID_OUTSIDE:
        if len(_SAID_OUTSIDE) >= 1024:
            _SAID_OUTSIDE.clear()
        _SAID_OUTSIDE.add(key)
        log(f"{'REFUSED' if refuse else 'OUTSIDE (served: stage 1)'} {peer} at {rule.get('bind')}:{rule.get('port')} "
            f"({rule.get('office')}/{rule.get('app')}) — this rule's clients are {list(rule.get('clients') or [])}")
    return not refuse


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
                client, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if self._halt.is_set():
                client.close()
                break
            if not admit(self.rule, addr[0] if isinstance(addr, tuple) and addr else ""):
                client.close()
                continue
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
    return _static_block("index.html", "bina-theme-tokens")


def _static_block(file: str, name: str) -> str:
    """A marked region of one of this app's own static files (G27 keeps them), as the console's own card
    reads its (app.py: _static_block); nothing when the file cannot be read."""
    try:
        page = (Path(__file__).resolve().parent / "static" / file).read_text(encoding="utf-8")
        return page.split(f"/* @{name}:start */", 1)[1].split(f"/* @{name}:end */", 1)[0]
    except (OSError, IndexError):
        return ""


def _static_bytes(file: str) -> bytes:
    try:
        return (Path(__file__).resolve().parent / "static" / file).read_bytes()
    except OSError:
        return b""


# THE card (DGO-1501): the office's one card on the logo wall — static/card.css is its stamped copy — with
# the alert glyph of the office's icon set (bina-icons `alert`), as the console's frame card draws it.
_ALERT = ('<svg class="ic-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
          'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 '
          '0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>')
_CARD = ('<!doctype html><html lang="he" dir="rtl" data-card><head><meta charset="utf-8">'
         '<meta http-equiv="refresh" content="15"><meta name="viewport" content="width=device-width, initial-scale=1">'
         '<title>%s</title><style>'
         + (':root{--font:"Segoe UI",system-ui,-apple-system,"Noto Sans Hebrew","Assistant",Arial,sans-serif}'
            + _palette() + _static_block("card.css", "card")).replace("%", "%%") +
         '</style></head><body><div class="xn"><div class="xn-card"><span class="xn-ic">' + _ALERT + '</span>'
         '<h2>%s</h2><p>%s</p><p>המסך הזה בודק שוב בעצמו.</p></div></div></body></html>')
# The wall the card stands on. The card asks for it at /bina-wall.svg on the host it was answered on — the
# app's — and that request reaches the door for the same reason the page did, so the door answers it too.
_WALL = _static_bytes("bina-wall.svg")
_SAID = {
    "bad-head": (b"400 Bad Request", "הבקשה לא תקינה",
                 "בכותרות הבקשה יש מעבר שורה בתוך שורה — הדלת לא מעבירה בקשה שאפשר לקרוא בשתי דרכים."),
    "no-app": (b"404 Not Found", "האפליקציה לא ניתנת כאן",
               "הלשכה ענתה, אבל היא לא נותנת אפליקציה בשם הזה ללשכות מקושרות."),
    "app-down": (b"502 Bad Gateway", "האפליקציה לא עונה",
                 "הלשכה שמריצה את האפליקציה ענתה, אבל האפליקציה עצמה לא עונה כרגע — היא כבויה או מופעלת מחדש."),
    "unreachable": (b"502 Bad Gateway", "הלשכה לא ענתה",
                    "הלשכה שמריצה את האפליקציה לא ענתה דרך הקישור — היא כבויה, מנותקת מהרשת, או שהמנהרה נפלה."),
}


def _say(client: socket.socket, reason: str, head: bytes = b"") -> bool:
    """Answer for the door itself and close. Never raises: the client may already be gone. True when what
    it answered was the card's wall (a 200, not a refusal), so the access record can say so."""
    status, title, text = _SAID[reason]
    first = head.split(b"\r\n", 1)[0].split(b" ")
    if (reason != "bad-head" and _WALL and len(first) >= 2 and first[0] == b"GET"
            and first[1].split(b"?", 1)[0] == b"/bina-wall.svg"):
        # the card's own wall (see _WALL): an image, with no door header — it is not the door's refusal.
        # Never for a head the door refused to read (bad-head): that one is refused whatever it asks for.
        try:
            client.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: image/svg+xml\r\nContent-Security-Policy: default-src 'none'"
                           b"\r\nX-Content-Type-Options: nosniff\r\nCache-Control: public, max-age=86400\r\nContent-Length: "
                           + str(len(_WALL)).encode("ascii") + b"\r\nConnection: close\r\n\r\n" + _WALL)
        except OSError:
            pass
        try:
            client.close()
        except OSError:
            pass
        return True
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
    return False


def _host_of(head: bytes) -> str:
    """The authority this request is for: lowercased, without its port, and without the trailing dot
    of a fully qualified name (`drive.macbook.` is `drive.macbook`, and is routed as that)."""
    for line in head.split(b"\r\n")[1:]:
        if not line:
            break
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"host":
            return value.strip().decode("latin-1").lower().split(":", 1)[0].rstrip(".")
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
        me = str(doc.get("office") or "").strip().lower()
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
            if ident and not HEADER_VALUE.match(ident):   # DGO-622: never written; said once per table
                log(f"{alias}: the mapped user {ident!r} is not a header value — this door writes no "
                    f"identity for it until it is declared again")
                ident = ""
            # WHAT TO CONNECT TO: the app's own compose service, not its id. The two differ for a
            # real app (`indox` is `incoming-documents`), and connecting to the id is a DNS failure
            # answered as `502` — the shape of "the office is linked and one app is missing", which
            # is the hardest kind of gap to notice.
            upstream = str(app.get("service") or "").strip().lower() or name
            # Keyed as `_host_of` reads a request: without the port. A host declared WITH one
            # (`plane.hp:8080`) never matched exactly, and lived on the first-label fallback that a
            # two-label name no longer has (second reader, 2026-10-19).
            host = str(app.get("host") or "").strip().lower().split(":", 1)[0].rstrip(".")
            if host:
                table[host] = (upstream, port, ident)
            # The FIRST LABEL, always: an app with no declared authority (`host: ""`) is reached under
            # the consuming office's own nested name — `<alias>.<office>.console.<its domain>` — which
            # this office cannot know, and the alias is the only part of it that is ours.
            if alias:
                table.setdefault(alias, (upstream, port, ident))
                # …and `<alias>.<this office>`, the name every consuming office resolves it by (the
                # network alias on its link proxy, which `where.sh` and `bbox remote` address): a
                # two-label name is answered exactly or not at all (`route`).
                if me:
                    table.setdefault(f"{alias}.{me}", (upstream, port, ident))
        # THE DOORS WITH NO TILE this office gives the asking office (DGO-945, `serve.services`): a
        # capability another office's machines call — the recordings, the transcriber, a webhook. Its
        # route is the fifth field: the PATHS it answers (empty = every path), held at `_serve` before
        # a byte reaches the service. No identity is written for it, and a name an app answers under is
        # never taken over (the catalog refuses the clash too).
        for door in doc.get("services") or []:
            if not isinstance(door, dict):
                continue
            alias = str(door.get("alias") or "").strip().lower()
            upstream = str(door.get("service") or "").strip().lower()
            try:
                port = int(door.get("port"))
            except (TypeError, ValueError):
                continue
            paths = door.get("paths")
            if not alias or not upstream or not 1 <= port <= 65535 or alias in table:
                continue
            if paths is not None and (not isinstance(paths, list) or not paths
                                      or not all(_plain_path(p) for p in paths)):
                log(f"{alias}: the door's paths {paths!r} are not plain absolute paths — not served")
                continue
            route = (upstream, port, "", "", tuple(paths or ()))
            table[alias] = route
            if me:
                table.setdefault(f"{alias}.{me}", route)
        # WHAT OTHER OFFICES GAVE THIS ONE, handed on (`serve.shared`, catalog.reshare): one exact
        # name per app, `<alias>.<origin>`, and never its first label — `plane` alone is this office's
        # own app or nothing, and a name an own app answers under is never taken over. The upstream
        # is this office's OWN door to the origin, and the fourth field is the authority the origin
        # expects: the request reaches it as this office's own edge would have sent it. No identity
        # is written here — the origin's door replaces it with what the ORIGIN maps this office to.
        for sec in doc.get("shared") or []:
            for app in (sec.get("apps") if isinstance(sec, dict) else None) or []:
                if not isinstance(app, dict):
                    continue
                host = str(app.get("host") or "").strip().lower()
                upstream = str(app.get("service") or "").strip().lower()
                try:
                    port = int(app.get("port"))
                except (TypeError, ValueError):
                    continue
                # The origin's authority is written into `Host:` (`rewrite`): held to the compiler's
                # rule here, the last door before the wire (DGO-622) — a value with a CRLF in it would
                # be a second header, or a second request, toward the origin.
                origin_host = str(app.get("origin_host") or "").strip().lower()
                if not host or not upstream or not 1 <= port <= 65535 or not AUTHORITY.match(origin_host):
                    continue
                table.setdefault(host, (upstream, port, "", origin_host))
        return table

    def route(self, host: str) -> tuple | None:
        if self.fixed is not None:
            return self.fixed
        table = self.routes()
        if not table:
            return None
        if host in table:
            return table[host]
        first, _, rest = host.partition(".")
        # A TWO-LABEL name is another office's way of naming an app — `<alias>.<office>` — and is
        # answered exactly or not at all; `.localhost` is the one exception (an authority, not an
        # office). Falling to the first label served `drive.macbook` — a share of the MacBook's Drive
        # that is gone (revoked, unlinked, or a stale tile on the consuming side) — with THIS office's
        # own Drive, under this office's mapping (second reader, 2026-10-19). This office's own apps
        # answer under `<alias>.<this office>` exactly (`_table`).
        if rest and "." not in rest and rest != "localhost":
            return None
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
    def rewrite(head: bytes, ident: str, office: str = "", signature: bytes = b"",
                host: str = "", forwarded: bool = True, herd: bool = False) -> bytes:
        """The head as the app must see it: the peer's identity claims REMOVED, ours written — the
        user it becomes here (`ident`), the office it came from (`office`, see OFFICE_HEADER) and the
        PROOF of both (`signature`, see ID_HEADER).

        The identity is not forwarded, it is replaced: a request that crossed a link arrives from a
        person this office never authenticated, and what it carries is the other office's user
        vocabulary (`IDENTITY_FAMILY`). The mapping in the catalog is what turns it into a user of
        THIS office — and the signature is what lets an app here believe it (`identity_signature`).

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
        # `host` — a re-shared app's ORIGIN authority (`_table`): the Host this request is handed on
        # under, and the authority of an `Origin` that named the one it arrived under, which the
        # consuming edge writes for an app that checks who is calling. Nothing else is touched.
        came = _host_of(head)
        for line in raw[1:]:
            # compared with `_` read as `-`: a WSGI app (Flask) reads `X_DGO_Office` as `X-DGO-Office`, and
            # `X_authentik_username` as the identity this door writes, so a peer's underscore spelling is the same
            # claim and goes with it (DGO-1155; the Go edge's edge.Claimed reads names the same way)
            name = line.split(b":", 1)[0].strip().lower().replace(b"_", b"-")
            if host and name == b"host":
                line = b"Host: " + host.encode("latin-1")
            elif host and name == b"origin" and came:
                scheme, sep, authority = line.split(b":", 1)[1].strip().decode("latin-1").partition("://")
                if sep and authority.lower().split(":", 1)[0] == came:
                    line = b"Origin: " + f"{scheme}://{host}".encode("latin-1")
            # ID_HEADER is on the removal list for the same reason OFFICE_HEADER is: a peer could
            # otherwise send its own, and an app that verified it would believe whatever it said.
            # …and, for a door with no tile (`forwarded=False`, DGO-945), what the peer says about where
            # the request came from: the service sees this door as its caller, and nothing a peer wrote.
            if not forwarded and name in FORWARDED:
                continue
            if line and name not in (b"connection", OFFICE_HEADER, ID_HEADER, FROM_HEADER, HERD_HEADER) \
                    and not name.startswith(IDENTITY_FAMILY):
                lines.append(line)
        lines.append(b"Connection: Upgrade" if Door.websocket(head) else b"Connection: close")
        if ident and not HEADER_VALUE.match(ident):       # DGO-622: the last door before the wire
            log(f"the mapped user {ident!r} is not a header value — not written, and nothing signed for it")
            ident, signature = "", b""
        if ident:
            lines.append(IDENTITY_HEADER.title() + b": " + ident.encode("latin-1"))
        if office:
            lines.append(OFFICE_HEADER.title() + b": " + office.encode("latin-1"))
            if herd:                                        # the herd's mark rides only with the door's own office
                lines.append(HERD_HEADER.title() + b": 1")
        if signature:
            lines.append(ID_HEADER.title() + b": " + signature)
        return b"\r\n".join(lines) + b"\r\n\r\n"

    def _serve(self, client: socket.socket, peer: str = "") -> None:
        t0 = time.monotonic()
        head = _head(client)
        if not head:
            client.close()
            return
        if _split_head(head):
            log("a request head with a bare CR or LF inside a line — refused, nothing forwarded")
            _say(client, "bad-head", head)
            return
        host = _host_of(head)
        method, path = _request_line(head)
        office = str(self.rule.get("office") or "")
        rec = {"ts": round(time.time(), 3), "office": office, "peer_ip": peer, "host": host,
               "app": host.split(".", 1)[0] if host else "", "user": "", "method": method, "path": path,
               "status": 0, "bytes_in": 0, "bytes_out": 0, "ms": 0, "ws": False, "said": ""}
        if outside(self.rule, peer):
            rec["outside"] = True       # not one of this rule's clients (WHO MAY ARRIVE, above): served in stage 1

        def done(status: int = 0, said: str = "", up: dict | None = None, down: dict | None = None) -> None:
            rec["status"] = status
            rec["said"] = said
            rec["bytes_in"] = (up or {}).get("bytes", 0)
            rec["bytes_out"] = (down or {}).get("bytes", 0)
            rec["ms"] = int((time.monotonic() - t0) * 1000)
            access_record(rec)

        route = self.route(host)
        if route is None:
            # A name nothing is served under is answered, not hung: the consuming side shows a page
            # that says what happened instead of a timeout nobody can read.
            log(f"{host or '(no Host header)'}: no app is served under that name")
            if _say(client, "no-app", head):
                done(200, "the-wall")       # the card's own wall, answered by the door (_say)
            else:
                done(404, "no-app")
            return
        name, port, ident = route[:3]
        rec["user"] = ident
        origin_host = route[3] if len(route) > 3 else ""
        # A door with no tile (DGO-945) answers the paths its office declared and nothing else — one
        # request per connection (`rewrite`), so the first head is the only one there is to check.
        door = len(route) > 4
        if door and route[4] and not _path_allowed(head, route[4]):
            target = (head.split(b"\r\n", 1)[0].split(b" ") + [b"", b""])[1]
            log(f"{host}: {target[:120].decode('latin-1', 'replace') or '(no target)'} is not a path "
                f"this door answers")
            if _say(client, "no-app", head):
                done(200, "the-wall")
            else:
                done(404, "path-not-served")
            return
        try:
            infos = socket.getaddrinfo(name, port, type=socket.SOCK_STREAM)
            family, socktype, proto, _canon, addr = infos[0]
            upstream = socket.socket(family, socktype, proto)
            upstream.settimeout(CONNECT_TIMEOUT)
            upstream.connect(addr)
            upstream.settimeout(None)
        except OSError as e:
            log(f"{host}: nothing answers at {name}:{port} ({e.strerror or e})")
            if _say(client, "app-down", head):
                done(200, "the-wall")
            else:
                done(502, "app-down")
            return
        rest = head[head.index(b"\r\n\r\n") + 4:]
        up_m: dict = {"bytes": len(head)}
        down_m: dict = {}
        try:
            upstream.sendall(self.rewrite(head, ident, office, identity_signature(office, ident),
                                          origin_host, forwarded=not door,
                                          herd=self.rule.get("herd") is True) + rest)
            if self.websocket(head):
                # A websocket is the one connection that stays open — and only once the APP has
                # agreed to it. Until its `101` nothing more of the client's is forwarded: an app
                # that answers anything else has kept an ordinary connection, and what the client
                # sends next on it would be a request this door never rewrote.
                rec["ws"] = True
                answer = _head(upstream)
                client.sendall(answer)
                down_m = {"bytes": len(answer), "first": answer[:64]}
                if not answer.startswith(b"HTTP/1.1 101"):
                    _pump(upstream, client, down_m)
                    upstream.close()
                    client.close()
                    done(_status_of(answer), "", up_m, down_m)
                    return
                upstream.settimeout(None)
        except OSError:
            upstream.close()
            client.close()
            done(0, "send-failed", up_m, down_m)
            return
        _nodelay(client)
        _nodelay(upstream)
        up = threading.Thread(target=_pump, args=(client, upstream, up_m), daemon=True)
        down = threading.Thread(target=_pump, args=(upstream, client, down_m), daemon=True)
        up.start()
        down.start()
        up.join()
        down.join()
        for s in (client, upstream):
            try:
                s.close()
            except OSError:
                pass
        done(_status_of(down_m.get("first") or b""), "", up_m, down_m)

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
                client, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if self._halt.is_set():
                client.close()
                break
            # the peer's tunnel address for a TCP door; a unix-socket door (a host bridge) has none
            peer = addr[0] if isinstance(addr, tuple) and addr else ""
            if not admit(self.rule, peer):
                client.close()
                continue
            threading.Thread(target=self._serve, args=(client, peer), daemon=True).start()
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


# ── a proxy left in a namespace that is gone ends, so its restart joins the live one (DGO-1753) ─────────────
# This process runs in dgo-net's namespace. When dgo-net is restarted (by hand, or by Docker after a crash) it
# gets a NEW namespace and this process stays in the old one, whose endpoint Docker took away: every door of the
# office closed while the container still runs. Measured on the Dell, 2026-11-10, beside the carrier
# (carrier/netns.go says the same for it, and why «gone» is read as NO DEFAULT ROUTE: devices that are not
# Docker's — a kernel WireGuard interface, tunl0 — can outlive dgo-net there, and none carries a default route).
# The one exception to «never exits» above: no default route for STRANDED_AFTER seconds, past STRANDED_GRACE after
# the start, and it exits non-zero; its restart policy starts it again, and a start joins the namespace dgo-net
# holds now. A look that fails, or finds a default route, ends the run — a live namespace is never left.
def _seconds(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(name, default)))
    except ValueError:                       # a bad setting is the default, never a crash loop of the door
        return default


STRANDED_GRACE = _seconds("DGO_LINK_STRANDED_GRACE", 30.0)
STRANDED_AFTER = _seconds("DGO_LINK_STRANDED_AFTER", 20.0)
STRANDED_EXIT = 3


def no_default_route(route4: str, route6: str) -> bool:
    """/proc/net/route and /proc/net/ipv6_route hold no default route through anything but `lo` (IPv6 keeps a
    reject route for ::/0 on lo in every namespace; it is not a way out)."""
    for i, line in enumerate(route4.splitlines()):
        f = line.split()
        # Iface Destination Gateway Flags RefCnt Use Metric Mask …; the first line is the header
        if i > 0 and len(f) >= 8 and f[0] != "lo" and f[1] == "00000000" and f[7] == "00000000":
            return False
    for line in route6.splitlines():
        f = line.split()
        # destination prefix-length source prefix-length next-hop metric refcnt use flags iface
        if len(f) >= 10 and f[0] == "0" * 32 and f[1] == "00" and f[9] != "lo":
            return False
    return True


class Stranded:
    """One look at a time: is this process left in a dead namespace? (`gone` None: the look failed.)"""

    def __init__(self, start: float, grace: float = STRANDED_GRACE, after: float = STRANDED_AFTER):
        self.start, self.grace, self.after, self.since = start, grace, after, None

    def step(self, now: float, gone) -> bool:
        if gone is not True or now - self.start < self.grace:
            self.since = None
            return False
        if self.since is None:
            self.since = now
        return now - self.since >= self.after


def _look_routes():
    """No default route here? None when the IPv4 table cannot be read: it always exists, and the IPv6 one read
    alone (lo's reject route only) would call a live namespace gone (the third reader of DGO-1753)."""
    try:
        route4 = Path("/proc/self/net/route").read_text()
    except OSError:
        return None
    try:
        route6 = Path("/proc/self/net/ipv6_route").read_text()
    except OSError:
        route6 = ""
    return no_default_route(route4, route6)


def watch_namespace(every: float = 5.0, clock=time.monotonic, look=_look_routes, end=os._exit, stop=None,
                    grace: float = STRANDED_GRACE, after: float = STRANDED_AFTER, sleep=time.sleep) -> None:
    s = Stranded(clock(), grace, after)
    while not (stop is not None and stop.is_set()):
        sleep(every)
        if s.step(clock(), look()):
            log(f"no default route in this namespace for {int(clock() - s.since)}s: dgo-net was restarted under "
                f"this proxy — ending, so that its restart joins the namespace dgo-net holds now")
            end(STRANDED_EXIT)
            return


def main() -> int:
    ap = argparse.ArgumentParser(description="the link proxy — what a link delivers, not what it allows")
    ap.add_argument("--check", action="store_true",
                    help="verify the rendered plan answers here, then exit")
    args = ap.parse_args()
    if args.check:
        return check()
    log(f"starting from {BASE} (plan {PLAN})")
    threading.Thread(target=watch_namespace, daemon=True, name="dgo-link-netns").start()
    Proxy().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
