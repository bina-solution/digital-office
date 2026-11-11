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

A READ IS NOT HARMLESS EITHER (DGO-1647, 2026-11-09). A prefix rule on `/containers` served every READ
under it, and this door sits on traefik-network, where every app can reach it. Measured on Exampleu from
inside n8n:
  - `GET /containers/forward-auth-<office>/json` returned the sign-in's secrets in `Config.Env`;
  - `/containers/traefik-<office>/archive?path=/etc/traefik/acme.json` answered 200, which means the
    edge's TLS private keys.
Code running in any app could forge a sign-in to every private app. Now:
  - under /containers the door serves exactly the list and one container's inspect;
  - both go back cut down to the fields the provider reads (INSPECT_KEEP, LIST_KEEP), so environment,
    command lines, healthcheck commands and mounts stay behind;
  - the event stream goes on without the `exec_*` events that carry a command;
  - the door serves no path but the version, the events and the containers.

AT MOST MAX_CONNECTIONS AT ONCE (DGO-992). Each connection runs on its own threads (the handler, and for a
stream the watch beside it), in a container capped at 64 MB. Until the door got a network of its own
(DGO-1652), any container on traefik-network could open connections without end, and nothing bounded the
threads. The cap bounds threads, not memory: MAX_ANSWER bounds what one held answer may take. The provider
needs a handful, because traefik's provider is sequential: one event stream, plus a list and its inspects
one at a time. So a connection past the cap gets a 503 with the reason at once, and the log says so, at most
once a second with a count. It is never queued. A slot is also never held for long by a peer that is not
working:
  - the whole head must arrive within HEAD_TIMEOUT, not each piece of it;
  - a held answer is sent within ANSWER_TIMEOUT;
  - TCP keepalive finds a peer on a quiet connection that vanished without a FIN in about 90 s. An /events
    stream can be quiet for hours, so without keepalive its slot would never be freed. If an event was being
    sent when the peer vanished, keepalive does not apply, and the kernel's retransmit timeout (about 15 min
    on Linux) frees the slot instead. That is longer, but still bounded.
The cap is safe only once the door sits on its own network (8b288848, DGO-1652): there, traefik is its one
client. On traefik-network, any app could hold the 16 slots with 16 event streams.

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
import time
import urllib.parse

#: The engine socket this door reads. Set once at start-up (`--socket`), never while running — the
#: handler reads it per connection, which is also what makes the self-test independent of it.
DOCKER_SOCKET = "/var/run/docker.sock"

#: The paths the edge's docker provider reads: the engine's version, its events, and its containers,
#: under GET/HEAD only. Nothing else (DGO-1647). Before that, the list also held `/info`, `/networks`,
#: `/services`, `/tasks`, `/nodes`, `/swarm` and `/distribution`, though no provider of ours reads any of
#: them, and each was a door of its own. On an engine in swarm mode, `/swarm` hands over the manager's join
#: token, and `/services` and `/tasks` hand over every service's environment. `/distribution/<host>/…`
#: makes the engine dial any address from the host's network. A traefik v3.3 pointed at a door serving
#: only these four came up with the same routers as the live edge (measured on Exampleu, 2026-11-09).
ALLOWED_PATHS = ("/_ping", "/version", "/events", "/containers")
ALLOWED_METHODS = ("GET", "HEAD")
#: WHICH CONSUMER THIS DOOR SERVES (DGO-1794), declared by its compose: `edge` — traefik's docker provider, every
#: rule in this file as it was; `connections` — the vault's identity reads (platform-base/connections/identity.py),
#: so that container holds no socket at all: GET the list, GET one inspect cut to its labels and its ONE
#: `AGENT_TOKEN_FILE` entry (an inspect otherwise carries the container's whole environment), and GET the archive of
#: exactly the file that container itself names there — the door inspects it first and compares. Nothing else: no
#: events, no HEAD, no other file. A profile this door does not know is refused when it starts.
PROFILE = os.environ.get("PROXY_PROFILE", "edge")
PROFILES = ("edge", "connections")
ARCHIVE = re.compile(r"^/containers/([A-Za-z0-9][A-Za-z0-9_.-]*)/archive$")
TOKEN_ENV = "AGENT_TOKEN_FILE="
CONN_INSPECT_KEEP = {"Id": True, "Name": True, "State": {"Status": True, "Running": True},
                     "Config": {"Labels": True, "Env": True}}


def archive_path(target: str) -> "str | None":
    """The one file an archive request asks for: exactly one `path=` in the query, absolute, no dot segment, no
    control character — or None."""
    query = target.split("?", 1)[1] if "?" in target else ""
    try:
        pairs = urllib.parse.parse_qsl(query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    if len(pairs) != 1 or pairs[0][0] != "path":
        return None
    p = pairs[0][1]
    if not p.startswith("/") or re.search(r"(^|/)\.{1,2}(/|$)", p) or any(ord(ch) < 32 for ch in p):
        return None
    return p
#: A VERSIONED PATH IS THE SAME PATH. The docker client — traefik's included, which hardcodes API
#: 1.24 — asks `/v1.24/version`, `/v1.24/containers/json`, `/v1.24/events`. The first version of this
#: door matched the path literally and refused every one of them, which is exactly what "the edge
#: finds zero routers and 404s every host while reporting healthy" looks like from the inside
#: (measured the moment traefik was pointed here: 302 -> 404, and the log said
#: `REFUSED 'GET /v1.24/version HTTP/1.1'`). The version is a prefix on the same path, so it is
#: stripped before the match — and the whitelist stays exactly as narrow.
VERSION_PREFIX = re.compile(r"^/v\d+(?:\.\d+)?(?=/|$)")

#: UNDER /containers, TWO READS AND NO OTHER (DGO-1647). The provider lists containers and inspects one.
#: Every other read under /containers looks INSIDE a container:
#:   - `archive?path=` returns any file, its volumes included;
#:   - `export` returns the whole filesystem;
#:   - `logs`, `top`, `stats` and `changes` return what runs there and what it printed.
#: None of those is the edge's business. A container name may carry `_`, `.` and `-`; a dot segment
#: never reaches this check (DOT_OR_ENCODED refuses it first).
CONTAINER_READS = re.compile(r"^/containers/(?:json|[A-Za-z0-9][A-Za-z0-9_.-]*/json)$")
#: One container's inspect: an answer the door cuts down to INSPECT_KEEP before the client sees it.
INSPECT = re.compile(r"^/containers/[A-Za-z0-9][A-Za-z0-9_.-]*/json$")
#: The most of one list or inspect answer the door will hold to cut it. Exampleu's list of 56 containers is
#: well under one megabyte. The door's container may hold 64 MB, and cutting an answer costs a few times
#: its size.
MAX_ANSWER = 4 * 1024 * 1024
#: The longest single event the door will hold while filtering the stream.
MAX_EVENT = 256 * 1024
#: How long the door waits for the engine's whole answer to a list or an inspect.
ANSWER_TIMEOUT = 30
#: The status line the door reads before it cuts an answer.
STATUS_LINE = re.compile(r"^HTTP/1\.[01] ([1-5][0-9][0-9])(?: |$)")
#: A chunk-size line, extensions dropped: hex digits and nothing else (a sign or `0x` is not one).
CHUNK_SIZE = re.compile(rb"^[0-9A-Fa-f]{1,8}$")

# WHAT LEAVES THE DOOR ABOUT A CONTAINER (DGO-1647). These are the fields the edge's provider reads: traefik
# v3's docker provider takes the id, the name, the node, the health, the network mode, the labels, the
# ports and the networks. Every other field stays behind. Deleting `Config.Env` alone was the first
# version of this fix, and the second reader showed what that missed:
#   - redis's password rode its command line (`--requirepass`) until DGO-1651, so it sat in `Args`,
#     `Config.Cmd` and the healthcheck's `Config.Healthcheck.Test`, and any service may do the same;
#   - the list answer carries `Command`;
#   - an init container can carry `export PGPASSWORD=…` in its command.
# So the door keeps a list of fields, not a list of secrets: a secret in a new place stays behind too.
NET_KEEP = {"NetworkID": True, "EndpointID": True, "Gateway": True, "IPAddress": True, "IPPrefixLen": True,
            "IPv6Gateway": True, "GlobalIPv6Address": True, "GlobalIPv6PrefixLen": True, "MacAddress": True,
            "Aliases": True, "DNSNames": True}
INSPECT_KEEP = {
    "Id": True, "Name": True, "Created": True, "Image": True, "Node": True, "RestartCount": True,
    "State": {"Status": True, "Running": True, "Paused": True, "Restarting": True, "OOMKilled": True,
              "Dead": True, "ExitCode": True, "StartedAt": True, "FinishedAt": True,
              "Health": {"Status": True, "FailingStreak": True}},
    "HostConfig": {"NetworkMode": True},
    "Config": {"Labels": True, "Hostname": True, "Image": True, "ExposedPorts": True},
    "NetworkSettings": {"Ports": True, "Networks": ("each", NET_KEEP)},
}
LIST_KEEP = {"Id": True, "Names": True, "Image": True, "ImageID": True, "Created": True, "Labels": True,
             "State": True, "Status": True, "Ports": True, "HostConfig": {"NetworkMode": True},
             "NetworkSettings": {"Networks": ("each", NET_KEEP)}}


def keep(value, spec):
    """value cut down to spec. True keeps a field whole, a dict keeps the fields it names (each cut down
    the same way), and ("each", spec) keeps every entry of a mapping cut down to spec."""
    if spec is True:
        return value
    if isinstance(spec, tuple) and spec[0] == "each":
        return {k: keep(v, spec[1]) for k, v in value.items()} if isinstance(value, dict) else None
    if isinstance(spec, dict) and isinstance(value, dict):
        return {k: keep(value[k], s) for k, s in spec.items() if k in value}
    return None

#: Longest request head this door will read before deciding. A docker client's head is a few hundred
#: bytes; anything larger is somebody probing, and it is refused rather than buffered.
MAX_HEAD = 16384
#: A docker client sends its head at once. One that has not finished in this many seconds is not
#: coming, and it does not get to hold a thread while it waits.
HEAD_TIMEOUT = 10
#: How many connections the door serves at once (DGO-992). traefik's provider holds one event stream and asks a
#: list and its inspects; the door's own healthcheck asks /_ping. Sixteen is several times that.
MAX_CONNECTIONS = 16
#: A path the engine could read as another path is not a path this door decides on.
DOT_OR_ENCODED = re.compile(r"(^|/)\.{1,2}(/|$)|%2e|%2f|%5c|\\", re.I)
#: The one shape of request line and header line the door reads (RFC 9112), nothing looser.
REQUEST_LINE = re.compile(r"[A-Z]+ /[!-~]* HTTP/1\.[01]")
HEADER_LINE = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+:[\t -~]*")
#: Headers about this hop, not the request: dropped, and the door sends its own `connection: close`.
HOP_BY_HOP = ("connection", "keep-alive", "proxy-connection", "te", "trailer")


def decide(request_line: str, profile: "str | None" = None) -> "tuple[bool, str]":
    """(allowed, why) for one request line — the whole rule, in one place, testable without docker."""
    parts = request_line.split()
    if len(parts) < 2:
        return False, "malformed request line"
    method, target = parts[0].upper(), parts[1]
    path = VERSION_PREFIX.sub("", target.split("?", 1)[0])
    if (profile or PROFILE) == "connections":
        if method != "GET":
            return False, f"{method} is not a read the vault's identity makes"
        if DOT_OR_ENCODED.search(path):
            return False, f"{path} is not a plain path (a dot segment or an encoded separator)"
        if path in ("/_ping", "/version") or CONTAINER_READS.match(path):
            return True, "read"
        if ARCHIVE.match(path):
            if archive_path(target):
                return True, "read"
            return False, "an archive read names exactly one absolute file (path=), no dot segment"
        return False, (f"{path} is not one of the vault's reads (the list, one inspect, the agent token's file) — "
                       f"DGO-1794")
    if method not in ALLOWED_METHODS:
        return False, (f"{method} is not a read: this door serves the edge's provider, which only "
                       f"lists containers and watches events")
    if DOT_OR_ENCODED.search(path):
        return False, f"{path} is not a plain path (a dot segment or an encoded separator)"
    if not path.startswith(ALLOWED_PATHS):
        return False, (f"{path} is not one of the paths the provider reads "
                       f"({', '.join(ALLOWED_PATHS)})")
    if path.startswith("/containers") and not CONTAINER_READS.match(path):
        return False, (f"{path} reads inside a container (its files, logs or processes); under /containers "
                       f"the provider only lists containers and inspects one (DGO-1647)")
    return True, "read"


def mode_of(request: bytes) -> str:
    """How the door carries the engine's answer to an admitted request:
      - inspect, list: held whole and cut down to the fields the provider reads;
      - events: filtered event by event as it streams;
      - copy: copied as it comes (the ping, the version, any HEAD)."""
    parts = request.split(b"\r\n", 1)[0].decode("ascii", "replace").split()
    if len(parts) < 2 or parts[0] != "GET":
        return "copy"
    path = VERSION_PREFIX.sub("", parts[1].split("?", 1)[0])
    if ARCHIVE.match(path):
        return "archive"
    if INSPECT.match(path):
        return "inspect"
    if path == "/containers/json":
        return "list"
    if path == "/events":
        return "events"
    return "copy"


class Unchunker:
    """Chunked transfer coding undone as bytes arrive. `feed()` returns the body bytes now complete;
    `done` is set by the last chunk, and `bad` by a size line that is not hex digits (a sign, `0x`, a
    line longer than any real one): the door then stops reading rather than trust the count."""

    def __init__(self) -> None:
        self.buf, self.left, self.state, self.done, self.bad = b"", 0, "size", False, False

    def feed(self, data: bytes) -> bytes:
        self.buf += data
        out = []
        while not (self.done or self.bad):
            if self.state == "size":
                j = self.buf.find(b"\r\n")
                if j < 0:
                    self.bad = len(self.buf) > 1024
                    break
                token = self.buf[:j].split(b";", 1)[0].strip()
                self.buf = self.buf[j + 2:]
                if not CHUNK_SIZE.match(token):
                    self.bad = True
                    break
                self.left = int(token, 16)
                if self.left == 0:
                    self.done = True
                    break
                self.state = "data"
            elif self.state == "data":
                if not self.buf:
                    break
                take = self.buf[:self.left]
                out.append(take)
                self.buf, self.left = self.buf[len(take):], self.left - len(take)
                if self.left == 0:
                    self.state = "crlf"
            else:
                if len(self.buf) < 2:
                    break
                if self.buf[:2] != b"\r\n":
                    self.bad = True
                    break
                self.buf, self.state = self.buf[2:], "size"
        return b"".join(out)


def _dechunk(body: bytes) -> "bytes | None":
    """A whole chunked body, joined; None when its chunks do not add up."""
    u = Unchunker()
    out = u.feed(body)
    return out if u.done and not u.bad else None


def _bad_gateway(why: str) -> bytes:
    body = json.dumps({"message": "docker-socket-proxy: " + why + " (DGO-1647)"}).encode()
    return (b"HTTP/1.1 502 Bad Gateway\r\ncontent-type: application/json\r\n"
            b"content-length: " + str(len(body)).encode() + b"\r\nconnection: close\r\n\r\n" + body)


def _head(raw: bytes) -> "tuple[str, str, list, dict] | None":
    """(status line, code, header lines, header fields) of an answer's head; None if the status line is
    not one the door reads."""
    lines = raw.decode("latin-1").split("\r\n")
    m = STATUS_LINE.match(lines[0])
    if not m:
        return None
    fields = {}
    for h in lines[1:]:
        name, _, value = h.partition(":")
        fields[name.strip().lower()] = value.strip()
    return lines[0], m.group(1), lines[1:], fields


def _reframed(status: str, headers: list, body: bytes) -> bytes:
    kept = [h for h in headers
            if h.partition(":")[0].strip().lower() not in ("content-length", "transfer-encoding", "connection")]
    head = "\r\n".join([status] + kept + [f"content-length: {len(body)}", "connection: close"])
    return head.encode("latin-1") + b"\r\n\r\n" + body


def cleaned(answer: bytes, mode: str, profile: "str | None" = None) -> bytes:
    """The engine's whole answer to a list or an inspect, cut down to the fields the provider reads
    (LIST_KEEP, INSPECT_KEEP) and framed again by length.

    It fails closed. If the door cannot read an answer exactly, it does not serve it: no complete head, a
    status line it does not know, an interim 1xx, chunks that do not add up, a content encoding, or a
    body that is not JSON of the expected shape. An error is served only when it is the engine's own
    `{"message": …}`."""
    end = answer.find(b"\r\n\r\n")
    head = _head(answer[:end]) if end >= 0 else None
    if head is None or head[1].startswith("1"):
        return _bad_gateway(f"a {mode} answer whose head the door does not read")
    status, code, headers, fields = head
    body = answer[end + 4:]
    if fields.get("transfer-encoding", "").lower() == "chunked":
        body = _dechunk(body)
        if body is None:
            return _bad_gateway(f"a {mode} answer whose chunks do not add up")
    elif "content-length" in fields:
        if not re.fullmatch(r"[0-9]{1,9}", fields["content-length"]):
            return _bad_gateway(f"a {mode} answer with a length the door does not read")
        body = body[:int(fields["content-length"])]
    if fields.get("content-encoding"):
        return _bad_gateway(f"a {mode} answer in an encoding the door does not read")
    try:
        doc = json.loads(body)
    except (ValueError, RecursionError):
        return _bad_gateway(f"a {mode} answer that is not JSON")
    if not code.startswith("2"):
        if isinstance(doc, dict) and set(doc) <= {"message"}:
            return _reframed(status, headers, body)
        return _bad_gateway(f"a {mode} error answer that is not the engine's message")
    if mode == "inspect" and isinstance(doc, dict) and (profile or PROFILE) == "connections":
        doc = keep(doc, CONN_INSPECT_KEEP)              # the labels, and of the environment the one token entry
        cfg = doc.get("Config") if isinstance(doc.get("Config"), dict) else {}
        cfg["Env"] = [e for e in (cfg.get("Env") or []) if isinstance(e, str) and e.startswith(TOKEN_ENV)]
        doc["Config"] = cfg
    elif mode == "inspect" and isinstance(doc, dict):
        doc = keep(doc, INSPECT_KEEP)
    elif mode == "list" and isinstance(doc, list):
        doc = [keep(c, LIST_KEEP) for c in doc if isinstance(c, dict)]
    else:
        return _bad_gateway(f"a {mode} answer of an unexpected shape")
    return _reframed(status, headers, json.dumps(doc, separators=(",", ":")).encode())


def event_allowed(line: bytes) -> bool:
    """Does one event of the engine's stream go on to the client? An `exec_*` event carries the command
    it ran in its action. The engine runs every healthcheck as an exec, so redis's `redis-cli -a <password>
    ping` came by every 30 s. Those events, and anything that is not an event, stay behind."""
    try:
        ev = json.loads(line)
    except (ValueError, RecursionError):
        return False
    if not isinstance(ev, dict):
        return False
    action = str(ev.get("Action") or ev.get("status") or "")
    return not action.startswith("exec_")


def _read_all(upstream: socket.socket) -> "bytes | None":
    """All the engine answers to one request (it closes after it, `connection: close`); None past the cap
    or past ANSWER_TIMEOUT."""
    upstream.settimeout(ANSWER_TIMEOUT)
    data = []
    size = 0
    while True:
        try:
            chunk = upstream.recv(65536)
        except socket.timeout:
            return None
        if not chunk:
            return b"".join(data)
        size += len(chunk)
        if size > MAX_ANSWER:
            return None
        data.append(chunk)


def _pump_events(upstream: socket.socket, client: socket.socket) -> None:
    """The engine's event stream to the client, event by event, without the ones event_allowed refuses.
    The engine sends it chunked (one event per line). The door sends it on chunked again, one event per
    chunk, and closes both sides when either ends or the stream stops making sense."""
    raw = b""
    try:
        while b"\r\n\r\n" not in raw:
            data = upstream.recv(65536)
            if not data:
                return
            raw += data
            if len(raw) > MAX_HEAD:
                client.sendall(_bad_gateway("an event stream whose head never ended"))
                return
        end = raw.find(b"\r\n\r\n")
        head, rest = _head(raw[:end]), raw[end + 4:]
        if head is None or head[1].startswith("1"):
            client.sendall(_bad_gateway("an event stream whose head the door does not read"))
            return
        status, code, headers, fields = head
        if not code.startswith("2"):                     # the engine's error: no events in it
            client.sendall(raw)
            _pump(upstream, client)
            return
        kept = [h for h in headers
                if h.partition(":")[0].strip().lower() not in ("content-length", "transfer-encoding", "connection")]
        client.sendall(("\r\n".join([status] + kept + ["transfer-encoding: chunked", "connection: close"])
                        + "\r\n\r\n").encode("latin-1"))
        un = Unchunker() if fields.get("transfer-encoding", "").lower() == "chunked" else None
        pending, data = b"", rest
        while True:
            if data:
                pending += un.feed(data) if un else data
                if un and un.bad:
                    break
                *complete, pending = pending.split(b"\n")
                for line in complete:
                    if line.strip() and event_allowed(line):
                        out = line + b"\n"
                        client.sendall(b"%x\r\n" % len(out) + out + b"\r\n")
                if len(pending) > MAX_EVENT or (un and un.done):
                    break
            data = upstream.recv(65536)
            if not data:
                break
        client.sendall(b"0\r\n\r\n")
    except OSError:
        pass
    finally:
        for s in (upstream, client):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


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


def token_file_of(cid: str) -> "tuple[str, str] | None":
    """(the container's full id, the file it names in its own AGENT_TOKEN_FILE), read by the door's own inspect of
    it on the engine — what an archive read is held to (connections' profile). None when it names none, or the
    engine does not say, or its id is not a full 64-hex id."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(ANSWER_TIMEOUT)
            s.connect(DOCKER_SOCKET)
            s.sendall(f"GET /containers/{cid}/json HTTP/1.1\r\nhost: docker\r\nconnection: close\r\n\r\n"
                      .encode("ascii"))
            answer = _read_all(s)
    except OSError:
        return None
    if answer is None:
        return None
    served = cleaned(answer, "inspect", "connections")
    head, _, body = served.partition(b"\r\n\r\n")
    if not head.split(b" ", 2)[1:2] == [b"200"]:
        return None
    try:
        doc = json.loads(body)
        env, full = (doc.get("Config") or {}).get("Env") or [], doc.get("Id") or ""
    except (ValueError, AttributeError):
        return None
    found = [e[len(TOKEN_ENV):] for e in env if e.startswith(TOKEN_ENV)]
    path = found[0] if found else ""                    # the first, as identity.py reads it
    # a FILE: never the root or a directory (`AGENT_TOKEN_FILE=/` would hand over the whole filesystem)
    if not (path.startswith("/") and not path.endswith("/") and re.fullmatch(r"[0-9a-f]{64}", full)):
        return None
    return full, path


def _refusal(why: str, head_only: bool = False) -> bytes:
    """The 403 with its sentence. An answer to a HEAD carries no body (RFC 9110 §9.3.2): a client that
    reads one strictly counted the sentence's bytes as garbage on a closed connection."""
    body = json.dumps({"message": "docker-socket-proxy: refused — " + why +
                       " (DGO-136: the edge holds a read-only door, not the engine)"}).encode()
    return (b"HTTP/1.1 403 Forbidden\r\ncontent-type: application/json\r\n"
            b"content-length: " + str(len(body)).encode() + b"\r\nconnection: close\r\n\r\n" +
            (b"" if head_only else body))


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


def _keepalive(s: socket.socket) -> None:
    """TCP keepalive on an accepted connection (DGO-992). A peer that vanished without a FIN is found in about
    90 s (60 idle + 3 × 10), and its slot is freed. An /events stream writes nothing for hours, because exec
    events are filtered out, so no retransmit would ever find it. The idle, interval and count options are
    set where the OS has them; Python 3.9 on macOS has no TCP_KEEPIDLE."""
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        for name, value in (("TCP_KEEPIDLE", 60), ("TCP_KEEPINTVL", 10), ("TCP_KEEPCNT", 3)):
            if hasattr(socket, name):
                s.setsockopt(socket.IPPROTO_TCP, getattr(socket, name), value)
    except OSError:
        pass


class Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        client, peer = self.request, self.client_address[0]
        _keepalive(client)
        # the WHOLE head within HEAD_TIMEOUT, not each piece of it: a head trickled one byte at a time held a
        # thread, and now a slot, for as long as its sender liked (DGO-992, the second reader measured it)
        deadline = time.monotonic() + HEAD_TIMEOUT
        head = b""
        try:
            while b"\r\n\r\n" not in head and len(head) < MAX_HEAD:
                left = deadline - time.monotonic()
                if left <= 0:
                    return
                client.settimeout(left)
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
                client.sendall(_refusal(why, head_only=line.startswith("HEAD ")))
            except OSError:
                pass
            return
        if mode_of(request) == "archive":               # connections: only the file this container itself names,
            # checked BEFORE the engine sees the request, on the ADMITTED request line — never `line`, the log's
            # 200-character copy (a longer line once compared a cut target and forwarded the whole one)
            first = request.split(b"\r\n", 1)[0].decode("ascii")
            target = first.split()[1]
            m = ARCHIVE.match(VERSION_PREFIX.sub("", target.split("?", 1)[0]))
            asked = archive_path(target)
            owner = token_file_of(m.group(1)) if m and asked else None
            if not owner or owner[1] != asked:
                why = "an archive read of a file that container does not name in AGENT_TOKEN_FILE"
                sys.stderr.write(f"docker-socket-proxy: REFUSED {peer} {line!r} — {why}\n")
                sys.stderr.flush()
                try:
                    client.sendall(_refusal(why))
                except OSError:
                    pass
                return
            # forward to the container the door inspected — its full id — not a name or prefix that could be
            # another container by the time the engine reads it
            request = request.replace(f"/containers/{m.group(1)}/archive".encode("ascii"),
                                      f"/containers/{owner[0]}/archive".encode("ascii"), 1)
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
            mode = mode_of(request)
            if mode in ("inspect", "list"):             # held, cut down to what the provider reads, then sent
                try:
                    answer = _read_all(upstream)
                    client.settimeout(ANSWER_TIMEOUT)   # a client that does not read its answer frees its slot
                    client.sendall(cleaned(answer, mode) if answer is not None else
                                   _bad_gateway(f"a {mode} answer over {MAX_ANSWER} bytes or "
                                                f"{ANSWER_TIMEOUT} s"))
                except (OSError, ValueError, RecursionError) as e:
                    sys.stderr.write(f"docker-socket-proxy: a {mode} answer was not served: {type(e).__name__}\n")
                return
            t = threading.Thread(target=_watch, args=(client, upstream, peer), daemon=True)
            t.start()
            if mode == "events":
                _pump_events(upstream, client)
            else:
                _pump(upstream, client)
            t.join(timeout=5)


def _busy(cap: int) -> bytes:
    """The 503 for a connection past the cap (DGO-992). It says why, in the same shape as a refusal."""
    body = json.dumps({"message": f"docker-socket-proxy: busy — {cap} connections are open already; try again "
                                  f"(DGO-992)"}).encode()
    return (b"HTTP/1.1 503 Service Unavailable\r\ncontent-type: application/json\r\n"
            b"content-length: " + str(len(body)).encode() + b"\r\nconnection: close\r\n\r\n" + body)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, handler, bind_and_activate: bool = True, *,
                 max_connections: int = MAX_CONNECTIONS) -> None:
        self.max_connections = max_connections
        self.slots = threading.BoundedSemaphore(max_connections)
        self.refused, self.refused_said = 0, 0.0
        super().__init__(address, handler, bind_and_activate)

    def process_request(self, request, client_address) -> None:
        """One handler per connection, and never more than max_connections of them (DGO-992). A connection past
        the cap is answered here, on the accepting thread, without blocking: the 503 is a few hundred bytes into a
        fresh socket's buffer, and the socket is then closed. It never waits for a slot. The log line is written
        at most once a second, with the count since the last one, so a flood cannot stall accepting on the log."""
        if not self.slots.acquire(blocking=False):
            self.refused += 1
            now = time.monotonic()
            if now - self.refused_said >= 1 or not self.refused_said:
                sys.stderr.write(f"docker-socket-proxy: REFUSED {client_address[0]} — {self.max_connections} "
                                 f"connections are open already ({self.refused} refused since the last such "
                                 f"line; DGO-992)\n")
                sys.stderr.flush()
                self.refused, self.refused_said = 0, now
            try:
                request.setblocking(False)
                request.send(_busy(self.max_connections))
                request.recv(65536)     # a request already sent is read, so the close is a FIN and not a reset
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:                               # no thread started: the slot goes back here
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()                        # the thread's end, however it ends, frees its slot

    def service_actions(self) -> None:
        """Run by serve_forever on the accepting thread after every poll: refusals that the last line did not
        count are said once a second has passed, so a burst's tail is not left unsaid (DGO-992)."""
        if self.refused and time.monotonic() - self.refused_said >= 1:
            sys.stderr.write(f"docker-socket-proxy: REFUSED {self.refused} more connection(s) past the cap of "
                             f"{self.max_connections} (DGO-992)\n")
            sys.stderr.flush()
            self.refused, self.refused_said = 0, time.monotonic()


def _cap_case() -> "tuple[bool, str]":
    """Two connections fill a door capped at two. A third gets the 503 at once and is closed. Once the two
    close, a fourth is served again (DGO-992). No engine is needed: the fourth asks for a write, which the
    door answers itself with its 403."""
    srv = Server(("127.0.0.1", 0), Handler, max_connections=2)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log, saved_err = io.StringIO(), sys.stderr
    sys.stderr = log                                    # the door's refusal line is part of the proof
    third = fourth = b""
    held, closed_at_once = [], False
    try:
        held = [socket.create_connection(srv.server_address, 5) for _ in range(2)]   # each waits for its head
        cl = socket.create_connection(srv.server_address, 5)
        cl.settimeout(2)                                # «at once»: the 503 and the close, well inside 2 s
        try:
            while True:
                data = cl.recv(4096)
                if not data:
                    closed_at_once = True
                    break
                third += data
        except OSError:
            pass
        cl.close()
        for s in held:
            s.close()                                   # their handlers read the end, return, free the slots
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            cl = socket.create_connection(srv.server_address, 5)
            cl.settimeout(5)
            cl.sendall(b"POST /containers/x/restart HTTP/1.1\r\nHost: selftest\r\n\r\n")
            fourth = b""
            try:
                while True:
                    data = cl.recv(4096)
                    if not data:
                        break
                    fourth += data
            except OSError:
                pass
            cl.close()
            if not fourth.startswith(b"HTTP/1.1 503"):
                break
            time.sleep(0.05)                            # a slot not freed yet: the handlers are still ending
    finally:
        for s in held:
            s.close()
        srv.shutdown()
        srv.server_close()
        sys.stderr = saved_err
    logged = "REFUSED 127.0.0.1 — 2 connections are open already" in log.getvalue()
    ok = (third.startswith(b"HTTP/1.1 503") and b"DGO-992" in third and closed_at_once
          and fourth.startswith(b"HTTP/1.1 403") and logged)
    return ok, ("the third got the 503 and the close at once, the log names it, and the fourth was served" if ok
                else f"third={third[:60]!r} closed_at_once={closed_at_once} fourth={fourth[:60]!r} logged={logged}")


def _trickle_case() -> "tuple[bool, str]":
    """A head sent one byte at a time is cut off at HEAD_TIMEOUT in all, not HEAD_TIMEOUT per byte (DGO-992). The
    door here waits 1 s in all, and the client sends a byte every 0.3 s for up to 6 s. It must be closed within
    3 s, which leaves room for a loaded machine. The old per-piece timeout held it for the whole 6 s."""
    global HEAD_TIMEOUT
    saved, HEAD_TIMEOUT = HEAD_TIMEOUT, 1
    held_for, srv = None, None
    try:
        srv = Server(("127.0.0.1", 0), Handler, max_connections=2)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        cl = socket.create_connection(srv.server_address, 5)
        t0 = time.monotonic()
        try:
            for b in b"GET /_ping HTTP/1.1\r\nHost: x\r\n":
                cl.sendall(bytes([b]))
                time.sleep(0.3)
                if time.monotonic() - t0 > 6:
                    break
        except OSError:
            pass                                        # the door closed it: the next send fails
        held_for = time.monotonic() - t0
        cl.close()
    finally:
        if srv is not None:
            srv.shutdown()
            srv.server_close()
        HEAD_TIMEOUT = saved
    ok = held_for is not None and held_for < 3
    return ok, (f"closed after {held_for:.1f} s" if held_for is not None else "the client failed")


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


def _through_door(request: bytes, engine_answer: bytes) -> "bytes | None":
    """What a client gets for `request` through the real handler, when a fake engine on a temporary unix
    socket answers `engine_answer` (sent in small pieces, so a chunk boundary falls anywhere) and then
    closes. None where there are no unix sockets."""
    global DOCKER_SOCKET
    if not hasattr(socket, "AF_UNIX") or sys.platform == "win32":
        return None
    tmp = tempfile.mkdtemp(prefix="socket-proxy-selftest-")
    saved, DOCKER_SOCKET = DOCKER_SOCKET, os.path.join(tmp, "engine.sock")
    engine = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    engine.bind(DOCKER_SOCKET)
    engine.listen(1)
    engine.settimeout(5)

    def fake_engine() -> None:
        try:
            conn, _ = engine.accept()
            with conn:
                conn.settimeout(5)
                got = b""
                while b"\r\n\r\n" not in got:
                    data = conn.recv(4096)
                    if not data:
                        return
                    got += data
                for i in range(0, len(engine_answer), 37):
                    conn.sendall(engine_answer[i:i + 37])
        except OSError:
            pass

    threading.Thread(target=fake_engine, daemon=True).start()
    srv = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    answer = b""
    try:
        cl = socket.create_connection(srv.server_address, 5)
        cl.sendall(request)
        while True:
            data = cl.recv(65536)
            if not data:
                break
            answer += data
        cl.close()
    except OSError:
        pass
    finally:
        srv.shutdown()
        srv.server_close()
        engine.close()
        DOCKER_SOCKET = saved
        shutil.rmtree(tmp, ignore_errors=True)
    return answer


FULL_ID = "ab" * 32


def _archive_case(token_file: "str | None", asked: str, pad: int = 0) -> "tuple[bytes, list] | None":
    """Through the real handler under the `connections` profile, an archive read of `asked` from a container whose
    own environment names `token_file`: a fake engine answers its inspect and its archive, and records every
    request it received. (client's answer, the engine's requests); None where there are no unix sockets."""
    global DOCKER_SOCKET, PROFILE
    if not hasattr(socket, "AF_UNIX") or sys.platform == "win32":
        return None
    tmp = tempfile.mkdtemp(prefix="socket-proxy-archive-")
    saved, DOCKER_SOCKET = (DOCKER_SOCKET, PROFILE), os.path.join(tmp, "engine.sock")
    PROFILE = "connections"
    engine = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    engine.bind(DOCKER_SOCKET)
    engine.listen(4)
    engine.settimeout(3)
    asked_engine = []

    def fake_engine() -> None:
        for _ in range(3):
            try:
                conn, _ = engine.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(3)
                got = b""
                while b"\r\n\r\n" not in got:
                    data = conn.recv(4096)
                    if not data:
                        break
                    got += data
                first = got.split(b"\r\n", 1)[0]
                asked_engine.append(first)
                if b"/archive" in first:
                    conn.sendall(b"HTTP/1.1 200 OK\r\ncontent-length: 4\r\n\r\nTOKN")
                else:
                    env = ["PATH=/bin", "SECRET=x"] + ([f"AGENT_TOKEN_FILE={token_file}"] if token_file else [])
                    body = json.dumps({"Id": FULL_ID, "Config": {"Labels": {}, "Env": env}}).encode()
                    conn.sendall(b"HTTP/1.1 200 OK\r\ncontent-length: " + str(len(body)).encode() + b"\r\n\r\n" + body)

    threading.Thread(target=fake_engine, daemon=True).start()
    srv = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    answer = b""
    try:
        cl = socket.create_connection(srv.server_address, 5)
        q = urllib.parse.quote(asked, safe="")
        version = "1." + "0" * pad + "41"           # a padded version the door's prefix accepts: a line over 200
        cl.sendall(f"GET /v{version}/containers/abc/archive?path={q} HTTP/1.1\r\nHost: t\r\n\r\n".encode())
        while True:
            data = cl.recv(65536)
            if not data:
                break
            answer += data
        cl.close()
    except OSError:
        pass
    finally:
        srv.shutdown()
        srv.server_close()
        engine.close()
        DOCKER_SOCKET, PROFILE = saved
        shutil.rmtree(tmp, ignore_errors=True)
    return answer, asked_engine


def _inspect_case(engine_answer: bytes, secret: str) -> "tuple[bool | None, str]":
    """An inspect through the real handler: a fake engine answers in chunks with a secret in the
    environment, the command line and the healthcheck, and the client must get valid JSON, framed by
    length, with no trace of it and with the labels intact. None without unix sockets."""
    global DOCKER_SOCKET
    if not hasattr(socket, "AF_UNIX") or sys.platform == "win32":
        return None, "no unix sockets here"
    tmp = tempfile.mkdtemp(prefix="socket-proxy-selftest-")
    saved, DOCKER_SOCKET = DOCKER_SOCKET, os.path.join(tmp, "engine.sock")
    engine = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    engine.bind(DOCKER_SOCKET)
    engine.listen(1)
    engine.settimeout(5)

    def fake_engine() -> None:
        try:
            conn, _ = engine.accept()
            with conn:
                conn.settimeout(5)
                got = b""
                while b"\r\n\r\n" not in got:
                    data = conn.recv(4096)
                    if not data:
                        return
                    got += data
                conn.sendall(engine_answer)
        except OSError:
            pass

    threading.Thread(target=fake_engine, daemon=True).start()
    srv = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    answer = b""
    try:
        cl = socket.create_connection(srv.server_address, 5)
        cl.sendall(b"GET /v1.24/containers/forward-auth-x/json HTTP/1.1\r\nHost: selftest\r\n\r\n")
        while True:
            data = cl.recv(65536)
            if not data:
                break
            answer += data
        cl.close()
    except OSError as e:
        return False, f"the client failed: {e}"
    finally:
        srv.shutdown()
        srv.server_close()
        engine.close()
        DOCKER_SOCKET = saved
        shutil.rmtree(tmp, ignore_errors=True)
    head, _, body = answer.partition(b"\r\n\r\n")
    try:
        doc = json.loads(body)
    except ValueError:
        return False, f"the client got no JSON: {answer[:120]!r}"
    ok = (head.startswith(b"HTTP/1.1 200") and secret.encode() not in answer and "Env" not in doc["Config"]
          and doc["Config"].get("Labels") == {"traefik.enable": "true"} and b"content-length: %d" % len(body) in head)
    return ok, "clean" if ok else f"the client got {answer[:200]!r}"


def selftest() -> int:
    """Every case, whatever PROXY_PROFILE the shell running it set: the edge's cases are the edge's, and the
    connections cases name their profile (or set it, in _archive_case)."""
    global PROFILE
    saved, PROFILE = PROFILE, "edge"
    try:
        return _selftest()
    finally:
        PROFILE = saved


def _selftest() -> int:
    cases = [
        ("GET /_ping HTTP/1.1", True),
        ("HEAD /_ping HTTP/1.1", True),
        ("GET /version HTTP/1.1", True),
        ("GET /containers/json?all=0&filters=%7B%7D HTTP/1.1", True),
        ("GET /containers/abc123/json HTTP/1.1", True),
        ("GET /events?filters=%7B%22type%22%3A%5B%22container%22%5D%7D HTTP/1.1", True),
        # DGO-1647 narrowed the paths to what the provider reads: this case was True before it
        ("GET /networks HTTP/1.1", False),
        ("GET /v1.24/info HTTP/1.1", False),
        ("GET /swarm HTTP/1.1", False),
        ("GET /v1.24/services?status=true HTTP/1.1", False),
        ("GET /tasks HTTP/1.1", False),
        ("GET /nodes HTTP/1.1", False),
        ("GET /distribution/registry.example:5000/x/json HTTP/1.1", False),
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
        # READS INSIDE A CONTAINER (DGO-1647): measured served to n8n on Exampleu, the edge's TLS keys among them
        ("GET /containers/traefik-exampleu/archive?path=/etc/traefik/acme.json HTTP/1.1", False),
        ("HEAD /containers/traefik-exampleu/archive?path=/etc/traefik/acme.json HTTP/1.1", False),
        ("GET /v1.24/containers/security-exampleu/archive?path=/data/security.db HTTP/1.1", False),
        ("GET /containers/forward-auth-exampleu/export HTTP/1.1", False),
        ("GET /containers/forward-auth-exampleu/logs?stdout=1&stderr=1 HTTP/1.1", False),
        ("GET /containers/abc/top HTTP/1.1", False),
        ("GET /containers/abc/stats?stream=0 HTTP/1.1", False),
        ("GET /containers/abc/changes HTTP/1.1", False),
        ("GET /containers HTTP/1.1", False),
        ("GET /containersx/json HTTP/1.1", False),
        # …and the two the provider asks, in every shape it asks them
        ("GET /containers/n8n_worker.1-exampleu/json HTTP/1.1", True),
        ("GET /v1.24/containers/0123456789ab/json?size=0 HTTP/1.1", True),
        ("HEAD /containers/abc/json HTTP/1.1", True),
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
    # WHAT A CONTAINER'S ANSWER CARRIES OUT (DGO-1647): only the fields the provider reads. The fixture is
    # shaped like the leaks the second reader found: redis's password on its command line and in its
    # healthcheck, the sign-in's secret in the environment, the list's `Command`.
    secret = "s3cr3t-pw"
    inspect_doc = json.dumps({
        "Id": "abc", "Name": "/redis-x", "Path": "redis-server", "Args": ["--requirepass", secret],
        "State": {"Status": "running", "Running": True, "Health": {"Status": "healthy", "Log": [{"Output": secret}]}},
        "HostConfig": {"NetworkMode": "traefik-network", "Binds": ["/srv:/data"]},
        "Config": {"Env": ["FORWARD_AUTH_SECRET=" + secret], "Cmd": ["redis-server", "--requirepass", secret],
                   "Healthcheck": {"Test": ["CMD-SHELL", "redis-cli -a " + secret + " ping"]},
                   "Labels": {"traefik.enable": "true"}},
        "Mounts": [{"Source": "/srv"}],
        "NetworkSettings": {"Ports": {"6379/tcp": None},
                            "Networks": {"traefik-network": {"IPAddress": "172.18.0.9", "NetworkID": "n1",
                                                             "DriverOpts": {"x": secret}}}}}).encode()
    list_doc = json.dumps([{"Id": "abc", "Names": ["/redis-x"], "Command": "redis-server --requirepass " + secret,
                            "Labels": {"traefik.enable": "true"}, "State": "running", "Mounts": [{"Source": "/srv"}],
                            "NetworkSettings": {"Networks": {"traefik-network": {"IPAddress": "172.18.0.9"}}}}]).encode()

    def by_length(doc: bytes, status: bytes = b"200 OK") -> bytes:
        return b"HTTP/1.1 " + status + b"\r\nContent-Type: application/json\r\nContent-Length: " + \
            str(len(doc)).encode() + b"\r\n\r\n" + doc

    def by_chunks(doc: bytes) -> bytes:
        return (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n" +
                b"%x\r\n" % 10 + doc[:10] + b"\r\n" + b"%x\r\n" % (len(doc) - 10) + doc[10:] + b"\r\n0\r\n\r\n")

    def parsed(answer: bytes) -> "tuple[str, object]":
        head, _, body = answer.partition(b"\r\n\r\n")
        length = [h for h in head.decode("latin-1").split("\r\n") if h.lower().startswith("content-length:")]
        try:
            doc = json.loads(body)
        except ValueError:
            doc = None
        return (head.split(b"\r\n", 1)[0].decode("latin-1")
                + (" length-ok" if length and int(length[0].split(":")[1]) == len(body) else " length-WRONG"), doc)

    env_cases = []
    for label, raw in (("an inspect framed by length", by_length(inspect_doc)),
                       ("an inspect framed in chunks", by_chunks(inspect_doc))):
        out = cleaned(raw, "inspect")
        line, doc = parsed(out)
        env_cases.append((label + ": no env, command, healthcheck or mounts; labels, health, networks kept",
                          line == "HTTP/1.1 200 OK length-ok" and secret.encode() not in out
                          and doc["Config"] == {"Labels": {"traefik.enable": "true"}}
                          and doc["State"]["Health"] == {"Status": "healthy"}
                          and doc["NetworkSettings"]["Networks"]["traefik-network"] == {"IPAddress": "172.18.0.9",
                                                                                       "NetworkID": "n1"}
                          and doc["HostConfig"] == {"NetworkMode": "traefik-network"}
                          and "Args" not in doc and "Mounts" not in doc))
    out = cleaned(by_chunks(list_doc), "list")
    line, doc = parsed(out)
    env_cases.append(("a list answer: no command or mounts; ids, names, labels and networks kept",
                      line == "HTTP/1.1 200 OK length-ok" and secret.encode() not in out
                      and doc == [{"Id": "abc", "Names": ["/redis-x"], "Labels": {"traefik.enable": "true"},
                                   "State": "running",
                                   "NetworkSettings": {"Networks": {"traefik-network": {"IPAddress": "172.18.0.9"}}}}]))
    line, doc = parsed(cleaned(by_length(b'{"message":"No such container: nope"}', b"404 Not Found"), "inspect"))
    env_cases.append(("the engine's own error message goes back as it came",
                      line == "HTTP/1.1 404 Not Found length-ok" and doc == {"message": "No such container: nope"}))
    for label, raw in (
            ("an error that is not the engine's message is not served",
             by_length(b'{"message":"x","Config":{"Env":["A=1"]}}', b"500 Internal Server Error")),
            ("a 200 that is not JSON is not served (fails closed)", b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nabc"),
            ("a 200 in an encoding the door cannot read is not served",
             b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: 2\r\n\r\n\x1f\x8b"),
            ("broken chunks are not served", b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\nabc"),
            ("a negative chunk size is not served, and does not loop",
             b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n-6\r\nabcdefgh"),
            ("an interim 1xx head is not taken for the answer",
             b"HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}"),
            ("a status line the door does not read is not served",
             b"HTTP/1.1  200 OK\r\nContent-Length: 2\r\n\r\n{}"),
            ("a length that is not digits is not served", b"HTTP/1.1 200 OK\r\nContent-Length: \xb2\r\n\r\n{}"),
            ("an inspect that is a list is not served", by_length(b"[]"))):
        env_cases.append((label, cleaned(raw, "inspect").startswith(b"HTTP/1.1 502")))
    env_cases.append(("the door holds and cuts exactly a GET of the list or of one inspect, and filters events",
                      mode_of(b"GET /v1.24/containers/abc/json HTTP/1.1\r\n\r\n") == "inspect"
                      and mode_of(b"GET /v1.24/containers/json?all=1 HTTP/1.1\r\n\r\n") == "list"
                      and mode_of(b"GET /v1.24/events?filters=%7B%7D HTTP/1.1\r\n\r\n") == "events"
                      and mode_of(b"HEAD /containers/abc/json HTTP/1.1\r\n\r\n") == "copy"
                      and mode_of(b"GET /_ping HTTP/1.1\r\n\r\n") == "copy"))
    start = json.dumps({"Type": "container", "Action": "start", "Actor": {"ID": "abc"}}).encode()
    execd = json.dumps({"Type": "container", "Action": "exec_create: /bin/sh -c redis-cli -a " + secret + " ping",
                        "status": "exec_create: /bin/sh -c redis-cli -a " + secret + " ping"}).encode()
    legacy = json.dumps({"status": "exec_start: redis-cli -a " + secret}).encode()
    env_cases.append(("an exec event (it carries the command it ran) does not go on; a start does",
                      event_allowed(start) and not event_allowed(execd) and not event_allowed(legacy)
                      and not event_allowed(b"not json") and not event_allowed(b"[1]")))
    u, got = Unchunker(), b""
    stream = b"%x\r\n" % (len(start) + 1) + start + b"\n\r\n" + b"0\r\n\r\n"
    for i in range(len(stream)):
        got += u.feed(stream[i:i + 1])
    env_cases.append(("chunks undone one byte at a time", got == start + b"\n" and u.done and not u.bad))
    events_stream = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n" +
                     b"".join(b"%x\r\n" % (len(e) + 1) + e + b"\n\r\n" for e in (start, execd, legacy, start)) +
                     b"0\r\n\r\n")
    through = _through_door(b"GET /v1.24/events HTTP/1.1\r\nHost: selftest\r\n\r\n", events_stream)
    if through is not None:
        head, _, body = through.partition(b"\r\n\r\n")
        events = Unchunker().feed(body).split(b"\n")
        env_cases.append(("live: the event stream reaches the client without the exec events",
                          head.startswith(b"HTTP/1.1 200") and secret.encode() not in through
                          and [e for e in events if e] == [start, start]))
        listed = _through_door(b"GET /v1.24/containers/json HTTP/1.1\r\nHost: selftest\r\n\r\n", by_chunks(list_doc))
        env_cases.append(("live: a list through the door carries no command line",
                          listed.startswith(b"HTTP/1.1 200") and secret.encode() not in listed
                          and b'"Names":["/redis-x"]' in listed))
    for label, ok in env_cases:
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] {'env':6} {label[:72]}")
    live, why = _later_request_case()
    if live is None:
        print(f"  [skip] {'live':6} a later request on the same connection ({why})")
    else:
        bad += 0 if live else 1
        print(f"  [{'ok ' if live else 'FAIL'}] {'live':6} a later request on the same connection never reaches "
              f"the engine{'' if live else '  (' + why + ')'}")
    live2, why2 = _inspect_case(by_chunks(inspect_doc), secret)
    if live2 is None:
        print(f"  [skip] {'live':6} an inspect through the door ({why2})")
    else:
        bad += 0 if live2 else 1
        print(f"  [{'ok ' if live2 else 'FAIL'}] {'live':6} an inspect through the door reaches the client without "
              f"its environment{'' if live2 else '  (' + why2 + ')'}")
    live3, why3 = _cap_case()
    bad += 0 if live3 else 1
    print(f"  [{'ok ' if live3 else 'FAIL'}] {'live':6} a connection past the cap gets a 503 at once, and the slots "
          f"free again{'' if live3 else '  (' + why3 + ')'}")
    live4, why4 = _trickle_case()
    bad += 0 if live4 else 1
    print(f"  [{'ok ' if live4 else 'FAIL'}] {'live':6} a head trickled a byte at a time is cut off at HEAD_TIMEOUT "
          f"in all ({why4})")
    # DGO-1794: the `connections` profile — the vault's identity reads, and nothing else
    conn_cases = [
        ("GET /v1.41/_ping HTTP/1.1", True),
        ("GET /v1.41/containers/json?filters=%7B%22label%22%3A%5B%22a%3Db%22%5D%7D HTTP/1.1", True),
        ("GET /v1.41/containers/abc123/json HTTP/1.1", True),
        ("GET /v1.41/containers/abc123/archive?path=%2Fdata%2Fagent.token HTTP/1.1", True),
        ("GET /containers/abc/archive HTTP/1.1", False),
        ("GET /containers/abc/archive?path=relative HTTP/1.1", False),
        ("GET /containers/abc/archive?path=/a/../etc/shadow HTTP/1.1", False),
        ("GET /containers/abc/archive?path=/a&path=/b HTTP/1.1", False),
        ("GET /containers/abc/archive?path=/a&noOverwriteDirNonDir=1 HTTP/1.1", False),
        ("HEAD /containers/abc/archive?path=/a HTTP/1.1", False),
        ("PUT /containers/abc/archive?path=/a HTTP/1.1", False),
        ("GET /events HTTP/1.1", False),
        ("GET /containers/abc/logs HTTP/1.1", False),
        ("GET /containers/abc/export HTTP/1.1", False),
        ("POST /containers/abc/exec HTTP/1.1", False),
        ("GET /images/json HTTP/1.1", False),
    ]
    for line, want in conn_cases:
        got, _ = decide(line, "connections")
        ok = got == want
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] conn   {line[:58]:58}{'' if ok else '  WANTED ' + str(want)}")
    extra = []
    extra.append(("the edge still refuses the archive a connections door serves",
                  decide("GET /containers/abc/archive?path=/data/agent.token HTTP/1.1", "edge")[0] is False))
    doc = {"Id": "x", "Name": "/n", "Config": {"Labels": {"a": "b"}, "Cmd": ["c"],
                                              "Env": ["SECRET_KEY=s3cr3t-v4lue", "AGENT_TOKEN_FILE=/data/t", "X=y"]},
           "HostConfig": {"Binds": ["/:/host"]}}
    body = json.dumps(doc).encode()
    served = cleaned(b"HTTP/1.1 200 OK\r\ncontent-length: " + str(len(body)).encode() + b"\r\n\r\n" + body,
                     "inspect", "connections")
    try:
        cut = json.loads(served.partition(b"\r\n\r\n")[2])
    except ValueError:
        cut = {}
    extra.append(("a connections inspect keeps the labels and the ONE token entry of the environment",
                  cut.get("Config") == {"Labels": {"a": "b"}, "Env": ["AGENT_TOKEN_FILE=/data/t"]}
                  and b"s3cr3t" not in served and "HostConfig" not in cut))
    for name, want_file, asked, pad, want_served in (
            ("the archive of the file the container names is served, to the id the door inspected",
             "/data/t", "/data/t", 0, True),
            ("…another file of the same container is refused before the engine sees it", "/data/t", "/etc/shadow",
             0, False),
            ("…and a container that names no token file serves none", None, "/data/t", 0, False),
            # the second reader's: a line over the log's 200 characters, cut before its query — once forwarded whole
            ("…a request line over 200 characters is judged whole (no token file, a database's file)", None,
             "/var/lib/postgresql/data/pg_hba.conf", 120, False),
            ("…and so is one cut right after the token's path", "/data/t", "/data/t-other-file", 140, False),
            # the third reader's: a container that names the root (or a directory) hands over nothing
            ("…a token file that is the root is never served", "/", "/", 0, False),
            ("…nor one that is a directory", "/data/", "/data/", 0, False)):
        got = _archive_case(want_file, asked, pad)
        if got is None:
            continue
        answer, engine_asked = got
        ok = (b" 200 " in answer.split(b"\r\n", 1)[0] and b"TOKN" in answer
              and any(f"/containers/{FULL_ID}/archive".encode() in r for r in engine_asked)) if want_served else \
             (b" 403 " in answer.split(b"\r\n", 1)[0] and not any(b"/archive" in r for r in engine_asked))
        extra.append((name, ok))
    for name, ok in extra:
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] conn   {name}")
    total = (len(cases) + len(framing) + len(env_cases) + (0 if live is None else 1)
             + (0 if live2 is None else 1) + 2 + len(conn_cases) + len(extra))
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
    if PROFILE not in PROFILES:
        print(f"docker-socket-proxy: PROXY_PROFILE={PROFILE!r} is not one of {', '.join(PROFILES)} — not starting",
              file=sys.stderr, flush=True)
        return 2
    DOCKER_SOCKET = a.socket
    serves = (f"GET/HEAD on {', '.join(ALLOWED_PATHS)}; under /containers only the list and one inspect, its Env "
              f"emptied" if PROFILE == "edge" else
              "GET the list, one inspect cut to its labels and its AGENT_TOKEN_FILE, and the archive of that file")
    print(f"docker-socket-proxy: [{PROFILE}] listening on :{a.port} -> {DOCKER_SOCKET} ({serves}; everything else "
          f"refused; at most {MAX_CONNECTIONS} connections at once)", flush=True)
    with Server(("0.0.0.0", a.port), Handler) as srv:
        srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
