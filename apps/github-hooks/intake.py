#!/usr/bin/env python3
"""intake.py — the GitHub webhook's public door: it keeps what GitHub sends, and decides nothing (DGO-2155, DGO-2138).

GitHub posts an event to one URL and wants a 2XX within 10 seconds, or it marks the delivery failed. It does NOT
redeliver by itself: a failed delivery is recovered through the App's «list deliveries / redeliver» API. So this door
must stay open for GitHub, and closed to everyone else's junk. It knows NOTHING worth stealing:
- no secret, no token, no address of the vault;
- each delivery goes to a disk queue (this app's own spool, data/github-hooks/spool) as raw bytes, and the answer is 202;
- the `git` app, which is not public, verifies each one later (apps/git/webhooks.py drain_once): the HMAC against the
  GitHub App's `webhook_secret` from the credential plane, then dedupe and record.
A break-in through this door reaches a folder of bounded bytes, never an account.

Its own app (apps/github-hooks), not a service of `git`: the compiler runs every service of an enabled app, so a
public door inside `git` would open on every office that runs git. Here it opens only where an office enables it.
The two share no volume. `git` takes the deliveries over a second port, INTERNAL_PORT, which no router names (the
office network only) and which answers only the address of the `git` service:
- GET  /internal/batch → the oldest deliveries, up to BATCH_FILES of them and BATCH_BYTES in all (at least one);
- POST /internal/ack {"drop": [names], "reject": [names]} → dropped ones are deleted, rejected ones are kept apart in
  the spool's .rejected/ (the newest REJECTED_KEEP). A name is checked against the spool's own pattern, so an ack can
  never name a path outside it.

What it refuses, each before anything is written (its second reader's nine cases, 2026-11-20, each fixed here):
- every path and method but `POST /github/webhook` (404/405); `GET /healthz` answers the container's health;
- a body over MAX_BODY (413). The body is never parsed: a JSON bomb costs nothing. It must start with `{` (415);
- a delivery without its GitHub headers, with an id that is not a GUID, or a target that is not ASCII digits (400);
- a target App id this office did not declare (WEBHOOK_APP_IDS, public numbers): 403. Junk aimed at a made-up App
  never reaches the spool, so it cannot fill it for the real one;
- more than RATE posts a second (429), more than CONCURRENCY at once (503), a full spool (507);
- a body that does not arrive within READ_TIMEOUT: the connection is closed, and the thread comes back.
The key on disk is the delivery id AND its signature. An unsigned POST that reuses a real id is kept apart, and the
drain rejects it; it never shadows GitHub's own delivery as a «duplicate».

    python3 apps/github-hooks/intake.py    # GitHub on :8979, git on :8980, the spool in $WEBHOOK_SPOOL (/spool)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PATH = "/github/webhook"
PORT = int(os.environ.get("WEBHOOK_INTAKE_PORT", "8979"))
SPOOL = Path(os.environ.get("WEBHOOK_SPOOL", "/spool"))
MAX_BODY = int(os.environ.get("WEBHOOK_MAX_BODY", str(1024 * 1024)))
MAX_FILES = int(os.environ.get("WEBHOOK_MAX_FILES", "2000"))
MAX_BYTES = int(os.environ.get("WEBHOOK_MAX_BYTES", str(100 * 1024 * 1024)))
RATE = int(os.environ.get("WEBHOOK_RATE", "50"))                         # posts per second, all senders
# requests at once. Each holds its body, its decoded text and its spool document (≤ 2× the body, quotes escaped):
# ~5 MB for a 1 MB body, so 4 stay far inside the 48 MB the container has (the second reader measured 8 × 13.6 MB
# with control characters, which ensure_ascii escaped six-fold; those are refused now)
CONCURRENCY = int(os.environ.get("WEBHOOK_CONCURRENCY", "4"))
READ_TIMEOUT = float(os.environ.get("WEBHOOK_READ_TIMEOUT", "10"))
INTERNAL_PORT = int(os.environ.get("WEBHOOK_INTERNAL_PORT", "8980"))
INTERNAL_PEER = os.environ.get("WEBHOOK_INTERNAL_PEER", "git")             # the only name the internal door answers
# …and only with this header, which apps/git/webhooks.py HookSource alone sends. git's smart-HTTP proxy also calls out
# from git's address, to a base an account names, but it builds its headers from a fixed set and never passes this one
# (the second reader: an account whose base_url is this door would otherwise have read the queue through it)
DRAIN_HEADER = ("X-Webhook-Drain", "git")
INTERNAL_CONCURRENCY = 4
CONTROL = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")    # raw control bytes: invalid in JSON, never from GitHub
BATCH_FILES = int(os.environ.get("WEBHOOK_BATCH_FILES", "100"))
# a batch is held three times while it is answered (the bytes, the parsed docs, the JSON out): 2 MB stays far inside
# the 48 MB the container has beside the public door's 8 × 1 MB. A delivery is 5–30 KB, so ~100 a pass.
BATCH_BYTES = int(os.environ.get("WEBHOOK_BATCH_BYTES", str(2 * 1024 * 1024)))
REJECTED_KEEP = 200
GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
NAME = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.[0-9a-f]{16}\.json$")
EVENT = re.compile(r"^[a-z_]{1,64}$")
SIG = re.compile(r"^sha256=[0-9a-f]{64}$")
DIGITS = re.compile(r"^[0-9]{1,20}$")


def app_ids() -> set[str]:
    """The GitHub App ids this office takes deliveries for (WEBHOOK_APP_IDS, comma-separated). Empty: none at all."""
    return {x.strip() for x in os.environ.get("WEBHOOK_APP_IDS", "").split(",") if DIGITS.match(x.strip())}


_lock = threading.Lock()
_window = {"second": 0, "n": 0}
_slots = threading.BoundedSemaphore(CONCURRENCY)
_room = {"at": 0.0, "files": 0, "bytes": 0}


def _rate_ok() -> bool:
    now = int(time.time())
    with _lock:
        if _window["second"] != now:
            _window["second"], _window["n"] = now, 0
        _window["n"] += 1
        return _window["n"] <= RATE


def _spool_room(extra: int) -> bool:
    """The spool's count, read at most every 2 s (one scandir, a file the drain deletes meanwhile is skipped), plus
    what this process kept since."""
    with _lock:
        if time.time() - _room["at"] > 2:
            files = size = 0
            try:
                with os.scandir(SPOOL) as it:
                    for e in it:
                        if e.name.endswith(".json") and not e.name.startswith("."):
                            try:
                                size += e.stat(follow_symlinks=False).st_size
                                files += 1
                            except OSError:
                                continue
            except OSError:
                return False
            _room.update(at=time.time(), files=files, bytes=size)
        return _room["files"] < MAX_FILES and _room["bytes"] + extra <= MAX_BYTES


def keep(delivery: str, event: str, signature: str, target: str, body: bytes) -> str:
    """Writes one delivery to the spool, whole or not at all (a temp file renamed). «kept» or «duplicate»."""
    SPOOL.mkdir(parents=True, exist_ok=True)
    name = f"{delivery.lower()}.{hashlib.sha256(signature.encode()).hexdigest()[:16]}.json"
    final = SPOOL / name
    if final.exists():
        return "duplicate"
    doc = {"delivery": delivery.lower(), "event": event, "signature": signature, "target": target,
           "received_at": round(time.time(), 3), "body": body.decode("utf-8")}
    tmp = SPOOL / f".{name}.{os.getpid()}.{threading.get_ident()}.tmp"
    # UTF-8, not \u-escapes: a Hebrew body would triple on disk and in memory (the second reader)
    tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    try:
        os.link(tmp, final)                 # the first writer wins, a second (a parallel duplicate) finds it there
    except FileExistsError:
        return "duplicate"
    except OSError:                         # a filesystem with no hard links: the rename, under this process's lock
        with _lock:
            if final.exists():
                return "duplicate"
            os.replace(tmp, final)
    finally:
        tmp.unlink(missing_ok=True)
    with _lock:
        _room["files"] += 1
        _room["bytes"] += final.stat().st_size if final.exists() else 0
    return "kept"


class Handler(BaseHTTPRequestHandler):
    server_version = "dgo-webhook-intake"
    sys_version = ""
    timeout = READ_TIMEOUT                  # a body that does not arrive in time closes the connection (its reader, 2)

    def log_message(self, fmt, *args):         # one short line per request, never a body or a header value
        print(f"{self.command} {self.path.split('?')[0][:80]} {args[1] if len(args) > 1 else ''}", flush=True)

    def _say(self, code: int, doc: dict) -> None:
        data = json.dumps(doc).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/healthz":
            return self._say(200, {"ok": True})
        return self._say(404, {"error": "not here"})

    def do_POST(self):
        if self.path.split("?")[0] != PATH:
            return self._say(404, {"error": "not here"})
        if not _slots.acquire(blocking=False):
            return self._say(503, {"error": "busy: redeliver later"})
        try:
            return self._post()
        finally:
            _slots.release()

    def _post(self):
        try:
            n = int(self.headers.get("Content-Length") or "-1")
        except ValueError:
            n = -1
        if n < 0:
            return self._say(411, {"error": "a delivery says its length"})
        if n > MAX_BODY:
            return self._say(413, {"error": "too large"})
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return self._say(415, {"error": "the webhook's content type is application/json"})
        delivery = (self.headers.get("X-GitHub-Delivery") or "").strip()
        event = (self.headers.get("X-GitHub-Event") or "").strip()
        signature = (self.headers.get("X-Hub-Signature-256") or "").strip()
        target = (self.headers.get("X-GitHub-Hook-Installation-Target-ID") or "").strip()
        if not GUID.match(delivery) or not EVENT.match(event) or not SIG.match(signature) or not DIGITS.match(target):
            return self._say(400, {"error": "not a GitHub delivery"})
        if target not in app_ids():
            return self._say(403, {"error": "not an App this office takes deliveries for"})
        # counted only now: junk with no GitHub headers, or for an App not declared, never spends GitHub's rate
        if not _rate_ok():
            return self._say(429, {"error": "too many deliveries this second"})
        body = self._read_body(n)
        if body is None:                    # the body did not arrive in time: the connection goes, the slot comes back
            self.close_connection = True
            return None
        if len(body) != n:
            return self._say(400, {"error": "the body is shorter than its length"})
        if not body.lstrip()[:1] == b"{":
            return self._say(415, {"error": "the body is not a JSON object"})
        if CONTROL.search(body):
            return self._say(415, {"error": "a raw control character: not JSON"})
        try:
            body.decode("utf-8")
        except UnicodeDecodeError:
            return self._say(415, {"error": "the body is not UTF-8"})
        if not _spool_room(len(body)):
            return self._say(507, {"error": "the queue is full: redeliver later"})
        got = keep(delivery, event, signature, target, body)
        return self._say(200 if got == "duplicate" else 202, {got: delivery.lower()})

    def _read_body(self, n: int) -> bytes | None:
        """The body, read in chunks against ONE deadline for the whole of it: a timeout per recv lets one byte every
        9 s hold a slot for days (the confirming reader). None when the deadline passes."""
        deadline = time.monotonic() + READ_TIMEOUT
        parts, got = [], 0
        while got < n:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            try:
                self.connection.settimeout(left)
                chunk = self.rfile.read1(min(65536, n - got))
            except OSError:
                return None
            if not chunk:
                break
            parts.append(chunk)
            got += len(chunk)
        return b"".join(parts)

    def do_PUT(self):
        self._say(405, {"error": "POST only"})

    do_DELETE = do_PATCH = do_PUT


def batch(limit_files: int | None = None, limit_bytes: int | None = None) -> dict:
    """The oldest deliveries, for `git` to judge: each as the intake kept it, plus the file's `name` to ack it by.
    A file the intake could not have written (a symlink, a name not its own, bytes that are no delivery) is removed
    and counted here, and never stops the batch."""
    limit_files = BATCH_FILES if limit_files is None else limit_files
    limit_bytes = BATCH_BYTES if limit_bytes is None else limit_bytes
    found, unreadable = [], 0
    try:
        with os.scandir(SPOOL) as it:
            for e in it:
                if e.name.startswith(".") or not e.name.endswith(".json"):
                    continue                # .rejected/ and the intake's own temp files
                try:
                    if not NAME.match(e.name) or e.is_symlink() or not e.is_file(follow_symlinks=False):
                        os.unlink(e.path)
                        unreadable += 1
                        continue
                    found.append((e.stat(follow_symlinks=False).st_mtime, e.name))
                except OSError:
                    continue
    except OSError:
        return {"deliveries": [], "unreadable": unreadable, "queued": 0, "error": "the spool cannot be read"}
    out, size = [], 0
    for _, name in sorted(found):
        p = SPOOL / name
        try:
            raw = p.read_bytes()
            d = json.loads(raw.decode("utf-8"))
            if (not isinstance(d, dict) or not isinstance(d.get("body"), str) or not isinstance(d.get("signature"), str)
                    or not isinstance(d.get("delivery"), str)):
                raise ValueError("not a delivery")
        except OSError:                     # acked meanwhile, or a read that failed (EIO, EMFILE): kept for the next batch
            continue
        except (ValueError, UnicodeDecodeError):   # bytes that are no delivery: never a real one lost to a failed read
            p.unlink(missing_ok=True)
            unreadable += 1
            continue
        if out and size + len(raw) > limit_bytes:
            break
        d["name"] = name
        out.append(d)
        size += len(raw)
        if len(out) >= limit_files:
            break
    return {"deliveries": out, "unreadable": unreadable, "queued": len(found)}


def ack(drop: object, reject: object) -> dict:
    """What `git` judged: dropped files are deleted, rejected ones kept apart in .rejected/ (one filesystem: no
    EXDEV). A name that is not the spool's own pattern is refused and counted, so no ack reaches outside the spool."""
    n = {"dropped": 0, "rejected": 0, "refused": 0}
    rejected = SPOOL / ".rejected"
    for verb, names in (("drop", drop), ("reject", reject)):
        for name in names if isinstance(names, list) else []:
            if not isinstance(name, str) or not NAME.match(name):
                n["refused"] += 1
                continue
            try:
                if verb == "drop":
                    (SPOOL / name).unlink()
                    n["dropped"] += 1
                else:
                    rejected.mkdir(exist_ok=True)
                    os.replace(SPOOL / name, rejected / name)
                    n["rejected"] += 1
            except FileNotFoundError:       # acked twice: already gone
                continue
            except OSError:
                n["refused"] += 1
    if n["rejected"]:
        try:
            old = sorted(rejected.glob("*.json"), key=lambda q: q.stat().st_mtime)
            for q in old[:-REJECTED_KEEP]:
                q.unlink(missing_ok=True)
        except OSError:
            pass
    with _lock:
        _room["at"] = 0.0                   # the next post counts the spool again
    return n


_peer = {"at": 0.0, "ips": set()}


def _peer_ok(addr: str) -> bool:
    """Is this the `git` service? Its name is resolved on the office network: kept 5 min while it matches, and asked
    again on a miss at most every 5 s (a recreated git gets a new address; a stranger's spam costs no lookups)."""
    now = time.time()
    with _lock:
        if addr in _peer["ips"] and now - _peer["at"] < 300:
            return True
        if now - _peer["at"] < 5:
            return addr in _peer["ips"]
    try:
        ips = {ai[4][0] for ai in socket.getaddrinfo(INTERNAL_PEER, None)}
    except OSError:
        ips = set()
    with _lock:
        _peer.update(at=now, ips=ips)
    return addr in ips


_internal_slots = threading.BoundedSemaphore(INTERNAL_CONCURRENCY)


class InternalHandler(Handler):
    """The office-network door for `git` (INTERNAL_PORT): no router names it, and it answers INTERNAL_PEER alone, with
    DRAIN_HEADER. At most INTERNAL_CONCURRENCY requests at once, like the public door."""
    server_version = "dgo-webhook-internal"

    def _peer(self) -> bool:
        if (self.headers.get(DRAIN_HEADER[0]) or "") == DRAIN_HEADER[1] and _peer_ok(self.client_address[0]):
            return True
        self._say(403, {"error": "this door answers the git service's drain only"})
        return False

    def _slot(self, fn):
        if not _internal_slots.acquire(blocking=False):
            return self._say(503, {"error": "busy"})
        try:
            return fn()
        finally:
            _internal_slots.release()

    def do_GET(self):
        if self.path.split("?")[0] != "/internal/batch":
            return self._say(404, {"error": "not here"})
        return self._slot(lambda: self._say(200, batch()) if self._peer() else None)

    def do_POST(self):
        if self.path.split("?")[0] != "/internal/ack":
            return self._say(404, {"error": "not here"})
        return self._slot(self._ack)

    def _ack(self):
        if not self._peer():
            return None
        try:
            n = int(self.headers.get("Content-Length") or "-1")
        except ValueError:
            n = -1
        if n < 0 or n > 256 * 1024:
            return self._say(413, {"error": "an ack says its length, under 256 KB"})
        try:
            doc = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (OSError, ValueError, UnicodeDecodeError):
            return self._say(400, {"error": "not JSON"})
        if not isinstance(doc, dict):
            return self._say(400, {"error": "an ack is an object"})
        return self._say(200, ack(doc.get("drop"), doc.get("reject")))


def serve(port: int = PORT, handler: type = Handler) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
    httpd.daemon_threads = True
    return httpd


if __name__ == "__main__":
    SPOOL.mkdir(parents=True, exist_ok=True)
    print(f"webhook intake on :{PORT}, git's door on :{INTERNAL_PORT} (for «{INTERNAL_PEER}»), spool {SPOOL}, "
          f"{len(app_ids())} App id(s) declared", flush=True)
    threading.Thread(target=serve(INTERNAL_PORT, InternalHandler).serve_forever, name="internal", daemon=True).start()
    serve().serve_forever()
