"""flowpub.py — the ONE flow.v1 publisher every app of the office shares (DGO-1402).

    import flowpub                                          # mounted read-only at /opt/dgo/flowpub.py
    flowpub.emit("drive", "file.uploaded", "הועלה «דוח.pdf»", data={"size": 52341})
    with flowpub.span("sites", "site.deploy", "פריסת «example.co.il»", data={"site": "exampleu"}):
        ...                                                 # site.deploy.started … .ended / .failed

    read -r sid t0 < <(python3 flowpub.py start ci-runner job "gates-hosted · 57ef890") || true  # a bash hook
    [ -n "$sid" ] && python3 flowpub.py end ci-runner job "$sid" "$t0" ok "gates-hosted · 57ef890" || true

THE CONTRACT is flow.v1 (ai/context/build-your-first-app.md § «The event stream», read by
platform-base/redis/flow.py and by «כל מקביל»'s `flow` lane): one Redis stream per app, `dgo:flow:<app>`; an
event is one XADD of `type` (dotted), `title` (one line a person reads), `at` (ISO-8601 UTC), `app`, and
optionally `link` and `data` (a JSON object), capped `MAXLEN ~ 1000` with its EXPIRE (30 days) renewed in the
same MULTI.

WHY ONE FILE AND NOT A CLASS IN EVERY APP. Telegram and domain-internic each carry their own copy of these
twenty lines, and a contract written twice drifts. This is the one copy: the apps that publish mount it from
the platform (their compose: `../../platform-base/redis/flowpub.py:/opt/dgo/flowpub.py:ro`), so a change to
the contract is a change here.

WHY THE STANDARD LIBRARY. An app's image may not carry a redis client (sites, meet-start, notifications do
not), and an emitter that needs a pip install is an emitter nobody mounts. Redis's wire protocol for four
commands is a few lines of bytes.

NEVER IN THE APP'S WAY. `emit()` only puts the event on a bounded queue and returns: one daemon thread sends,
so a request never waits on redis, and redis being away costs events, never a request. A failure is COUNTED
(`stats()`, for the app's screen and health) and never raised; a full queue drops and counts. The stream is
a window, not the office's state — what was not written is simply not in the window.

WHAT NOT TO PUBLISH (the contract's own rule): a secret, a token, a session — ever. Every agent of the office
reads these streams. The caller chooses `data`; this file only bounds its size.
"""
from __future__ import annotations

import atexit
import json
import os
import queue
import re
import socket
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

PREFIX = "dgo:flow:"
MAXLEN = 1000
TTL_S = 30 * 24 * 3600
TITLE_MAX = 300
#: bytes of the `data` JSON; a bigger object is replaced by a note that it was cut. 16 KB because telegram's
#: `message.new` carries a message's text (up to 2000 characters — 8 KB of Hebrew or emoji in UTF-8) and the
#: group's relay READS it off the stream (apps/telegram/relay/relay_group.py): a cut there is a lost message.
DATA_MAX = 16384
QUEUE_MAX = 1000
TIMEOUT_S = 3.0
#: an app id and an event type, as the contract writes them — anything else is refused (and counted), so a
#: caller's typo cannot write into another app's stream or under a key outside the contract
APP_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
TYPE_RE = re.compile(r"^[a-z0-9_-]+(\.[a-z0-9_-]+)+$")

_q: "queue.Queue[tuple[str, list[str]]]" = queue.Queue(maxsize=QUEUE_MAX)
_stats = {"sent": 0, "failed": 0, "dropped": 0, "refused": 0, "last_error": None}
_lock = threading.Lock()
_worker: threading.Thread | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def stats() -> dict:
    """What the publisher did since the process started — for the app's own screen and health."""
    with _lock:
        return dict(_stats)


def _count(key: str, error: str | None = None) -> None:
    with _lock:
        _stats[key] += 1
        if error is not None or key == "sent":
            _stats["last_error"] = error


# ── the wire: four commands of the redis protocol (RESP2) ─────────────────────────────────────────────────
def _encode(*parts: str) -> bytes:
    out = [b"*%d\r\n" % len(parts)]
    for p in parts:
        b = p.encode("utf-8")
        out.append(b"$%d\r\n%s\r\n" % (len(b), b))
    return b"".join(out)


def _reply(f):
    """One reply off the socket's file: str for a simple string, int, bytes|None for a bulk, list for an array.
    An error reply raises — it is the one thing the caller must not mistake for success."""
    line = f.readline()
    if not line:
        raise ConnectionError("redis closed the connection")
    kind, rest = line[:1], line[1:].rstrip(b"\r\n")
    if kind == b"+":
        return rest.decode()
    if kind == b"-":
        raise RuntimeError(rest.decode("utf-8", "replace")[:200])
    if kind == b":":
        return int(rest)
    if kind == b"$":
        n = int(rest)
        if n < 0:
            return None
        data = f.read(n + 2)
        return data[:-2]
    if kind == b"*":
        n = int(rest)
        return None if n < 0 else [_reply(f) for _ in range(n)]
    raise RuntimeError(f"redis answered something that is not RESP: {line[:40]!r}")


class _Conn:
    def __init__(self):
        # The office redis BY ITS NAME ON THE NETWORK, never `REDIS_HOST`: the office's .env sets that to the
        # edge's public TLS name (`redis.<domain>`, traefik's TCP entrypoint), and an app that loads .env would
        # dial the public name — every event lost, and AUTH sent in clear wherever the name answers (the second
        # reader, DGO-1402). The older publishers (telegram, domain-internic) read only this variable too.
        host = os.environ.get("REDIS_HOST_INTERNAL") or "redis"
        port = int(os.environ.get("REDIS_PORT_INTERNAL") or 6379)
        self.sock = socket.create_connection((host, port), timeout=TIMEOUT_S)
        self.sock.settimeout(TIMEOUT_S)
        self.f = self.sock.makefile("rb")
        pw = os.environ.get("REDIS_PASSWORD", "")
        if pw:
            self.sock.sendall(_encode("AUTH", pw))
            _reply(self.f)

    def publish(self, key: str, fields: list[str]) -> None:
        """MULTI · XADD key MAXLEN ~ 1000 * fields… · EXPIRE key 30d · EXEC — sent as one write, four replies read.
        EXEC's answer is checked, not assumed: a queued command that failed comes back inside it."""
        self.sock.sendall(_encode("MULTI")
                          + _encode("XADD", key, "MAXLEN", "~", str(MAXLEN), "*", *fields)
                          + _encode("EXPIRE", key, str(TTL_S))
                          + _encode("EXEC"))
        replies = [_reply(self.f) for _ in range(4)]
        if replies[0] != "OK" or not isinstance(replies[3], list) or len(replies[3]) != 2:
            raise RuntimeError(f"redis refused the transaction: {replies!r}"[:200])

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _run() -> None:
    conn: _Conn | None = None
    while True:
        key, fields = _q.get()
        try:
            # A connection kept from an earlier event may have died with a redis restart: the first failure on
            # a REUSED connection is retried once on a fresh one, so the event after a restart is not the one
            # lost (an `.ended` lost there would leave its bar open). Only a connection that is GONE is retried
            # (ConnectionError: closed, reset, broken pipe) — never a timeout or a refusal, after which redis may
            # well have run the transaction: a retry there wrote the event twice, and the telegram relay hands
            # every `message.new` it reads to the answerer (the second reader, DGO-1732).
            for attempt in (1, 2):
                reused = conn is not None
                try:
                    if conn is None:
                        conn = _Conn()
                    conn.publish(key, fields)
                    _count("sent")
                    break
                except Exception as e:                           # noqa: BLE001 — counted, never raised (above)
                    if conn is not None:
                        conn.close()
                    conn = None
                    if not (reused and attempt == 1 and isinstance(e, ConnectionError)):
                        _count("failed", f"{type(e).__name__}: {e}"[:200])
                        break
        finally:
            _q.task_done()


def flush(timeout: float = 2.0) -> bool:
    """Wait up to `timeout` for what is queued to be sent — for a short-lived process (a CLI that imports an
    app's module) whose daemon thread would die with it. Registered at exit; True when nothing is left."""
    end = time.time() + timeout
    while _q.unfinished_tasks and time.time() < end:
        time.sleep(0.02)
    return not _q.unfinished_tasks


atexit.register(flush)


def _ensure_worker() -> None:
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name="flowpub", daemon=True)
            _worker.start()


def fields_of(app: str, type_: str, title: str, data: dict | None = None, link: str = "") -> list[str] | None:
    """The XADD fields of one event, or None when the event breaks the contract (an app id or a type that is
    not one). Pure — the tests read it, and `emit` is this plus a queue."""
    if not isinstance(app, str) or not APP_RE.match(app) or not isinstance(type_, str) or not TYPE_RE.match(type_):
        return None
    title = " ".join(str(title or "").split())[:TITLE_MAX] or type_
    out = ["type", type_, "title", title, "at", _now_iso(), "app", app]
    if link:
        out += ["link", str(link)[:500]]
    if data:
        try:
            blob = json.dumps(data, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            blob = json.dumps({"note": "data was not JSON"})
        if len(blob.encode("utf-8")) > DATA_MAX:
            blob = json.dumps({"note": f"data cut: {len(blob)} chars"})
        out += ["data", blob]
    return out


def emit(app: str, type_: str, title: str, data: dict | None = None, link: str = "") -> bool:
    """Queue one event for `dgo:flow:<app>`. True when it was queued; never raises, never waits."""
    try:
        fields = fields_of(app, type_, title, data, link)
        if fields is None:
            _count("refused", f"not an app id or a type: {app!r} {type_!r}"[:200])
            return False
        _ensure_worker()
        _q.put_nowait((PREFIX + app, fields))
        return True
    except queue.Full:
        _count("dropped", "the queue is full (redis away?)")
        return False
    except Exception as e:                                       # noqa: BLE001 — never in the app's way
        _count("failed", f"{type(e).__name__}: {e}"[:200])
        return False


def span_start(app: str, kind: str, title: str, data: dict | None = None, link: str = "") -> tuple[str, int, bool]:
    """The first half of a bar: `<kind>.started` now, with `data.span`. Returns (span id, t0 in ms, queued) — the
    two words `span_end` needs. span() and the command line both open a bar here, so a bar is written one way."""
    sid = uuid.uuid4().hex[:12]
    t0 = int(time.time() * 1000)
    return sid, t0, emit(app, f"{kind}.started", title, {**dict(data or {}), "span": sid}, link)


def span_end(app: str, kind: str, title: str, sid: str, t0: int, failed: bool = False,
             data: dict | None = None, link: str = "") -> bool:
    """The second half: `<kind>.ended` (or `.failed`) with `data.span`, `data.t0` and `data.ms`, so a reader
    draws ONE bar from the two. True when it was queued."""
    ms = max(0, int(time.time() * 1000) - t0)
    return emit(app, f"{kind}.{'failed' if failed else 'ended'}", title,
                {**dict(data or {}), "span": sid, "t0": t0, "ms": ms}, link)


@contextmanager
def span(app: str, kind: str, title: str, data: dict | None = None, link: str = ""):
    """A piece of work with a duration: `<kind>.started` now, `<kind>.ended` (or `.failed`, then re-raised) when
    the block leaves. Both carry `data.span` (one id) and the end carries `data.t0` and `data.ms`, so a reader
    draws ONE bar. The block's own exception is never swallowed."""
    base = dict(data or {})
    sid, t0, _ = span_start(app, kind, title, base, link)
    try:
        yield sid
    except BaseException as e:
        span_end(app, kind, title, sid, t0, True, {**base, "error": type(e).__name__}, link)
        raise
    span_end(app, kind, title, sid, t0, False, base, link)


#: a span id as span_start makes it (and as the command line takes it back): a word, never a place for text
SPAN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def main(argv: list[str] | None = None) -> int:
    """The command line, for what cannot import this file — a CI job's pre/post hook, a shell script:

        python3 flowpub.py start <app> <kind> <title> [--data JSON] [--link L]
            → `<kind>.started`; prints «<span> <t0_ms>», the two words `end` takes back (printed even when
              the start was not sent, so the hook's end still closes what it opened)
        python3 flowpub.py end <app> <kind> <span> <t0_ms> ok|failed <title> [--data JSON] [--link L]
            → `<kind>.ended` or `<kind>.failed`, with data.span, data.t0 and data.ms, as span() writes them

    Sent before it returns (a hook's process does not live long enough for the daemon thread): exit 0 when
    redis took the event, 1 when it did not — refused by the contract, or redis away or refusing; the reason on
    stderr — and 2 for a command line that is none of these. Whether a lost bar matters is the hook's call; the
    flow never fails a job — so a hook (bash: `< <(…)` is not sh) ends each call with `|| true` and sends `end`
    only when `start` printed a span. A title that begins with `-` is read as an option: put `--` before it.
    `--data` is a JSON object, and the contract's rule stands: never a secret in it."""
    import argparse
    import sys

    ap = argparse.ArgumentParser(prog="flowpub.py", description="publish one half of a flow.v1 bar",
                                 epilog=main.__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="verb", required=True)
    for verb in ("start", "end"):
        p = sub.add_parser(verb)
        p.add_argument("app")
        p.add_argument("kind")
        if verb == "end":
            p.add_argument("span")
            p.add_argument("t0", type=int)
            p.add_argument("result", choices=("ok", "failed"))
        p.add_argument("title")
        p.add_argument("--data", default="")
        p.add_argument("--link", default="")
    a = ap.parse_args(argv)
    data = None
    if a.data:
        try:
            data = json.loads(a.data)
        except ValueError as e:
            ap.error(f"--data is not JSON: {e}")
        if not isinstance(data, dict):
            ap.error("--data must be a JSON object")
    if a.verb == "end" and not SPAN_RE.fullmatch(a.span):
        ap.error(f"not a span id: {a.span!r}")
    sent = stats()["sent"]
    if a.verb == "start":
        sid, t0, queued = span_start(a.app, a.kind, a.title, data, a.link)
    else:
        queued = span_end(a.app, a.kind, a.title, a.span, a.t0, a.result == "failed", data, a.link)
    flush(3 * TIMEOUT_S + 1)        # connect, AUTH and the transaction may each take TIMEOUT_S
    if a.verb == "start":
        print(f"{sid} {t0}")        # printed even when not sent: the hook's `end` still closes what it opened
    if not queued or stats()["sent"] <= sent:
        print(f"flowpub: not sent — {stats()['last_error'] or 'not delivered in time'}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
