#!/usr/bin/env python3
"""notify-relay — an office with no notice board of its own posts its notices to the herd's board (DGO-2111, root 2).

The MacBook (its board disabled «by: user» since 10-04) and the Dell (since 10-21) posted into nothing: every poster
here reaches the board as http://notifications:8977, some by NOTIFICATIONS_URL and many written into the code (the n8n
workflows, Azaria's harness, esign). This process answers that name on such an office and carries each POST
/api/notifications to the hub's board over the link (its door.base in the compiled registry). The hub's board marks it
as this office's (platform-base/notifications/app.py `_from_office`): its title reads «<office> · …», its episodes
stay its own, and what would act on the hub is dropped.

  * A notice the hub does not take now (the link is down, the hub is busy) is kept on disk, in order, and sent when
    it answers again. It is never dropped silently: the spool's cap drops the OLDEST, said in the log.
  * On an office that HAS its own board this relay refuses to serve: the name `notifications` would answer twice.
  * Stdlib only: the image is python:3.12-alpine with this directory mounted.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.environ.get("NOTIFY_RELAY_PORT", "8977"))
HUB = os.environ.get("NOTIFY_RELAY_HUB", "hp-laptop").strip().lower()
REGISTRY = Path(os.environ.get("NOTIFY_RELAY_REGISTRY", "/registry"))
SPOOL = Path(os.environ.get("NOTIFY_RELAY_SPOOL", "/data/spool.jsonl"))
SPOOL_MAX = int(os.environ.get("NOTIFY_RELAY_SPOOL_MAX", "10000"))
SPOOL_MAX_BYTES = int(os.environ.get("NOTIFY_RELAY_SPOOL_MAX_BYTES", str(2 * 1024 * 1024)))
BODY_MAX = 256 * 1024
RETRY_S = float(os.environ.get("NOTIFY_RELAY_RETRY_S", "30"))
TIMEOUT_S = float(os.environ.get("NOTIFY_RELAY_TIMEOUT_S", "10"))
DEPLOYMENT = os.environ.get("DEPLOYMENT_NAME", "bina-deployment")
_LOCK = threading.Lock()


def log(msg: str) -> None:
    print(f"notify-relay: {msg}", flush=True)


def hub_base() -> str:
    """The hub board's address over the link: the compiled record of the hub's `alerts` (door.base), never a
    constant — the port is the pair's (9000 + its slot)."""
    try:
        doc = json.loads((REGISTRY / f"remote.{HUB}.alerts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(((doc.get("door") or {}).get("base")) or "").rstrip("/")


def own_board() -> bool:
    """Does this office run its own board? Its container name answers on the network only if it exists."""
    try:
        socket.getaddrinfo(f"notifications-{DEPLOYMENT}", None)
        return True
    except OSError:
        return False


def forward(body: bytes) -> tuple[bool, int, bytes]:
    """(taken, status, answer). Taken = the hub answered with any status but a 5xx: a 4xx is the hub's refusal of
    this notice, said back to the poster, never spooled for ever."""
    base = hub_base()
    if not base:
        return False, 0, b'{"error": "no hub board known to this office (no remote alerts record)"}'
    req = urllib.request.Request(f"{base}/api/notifications", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return True, r.status, r.read()
    except urllib.error.HTTPError as e:
        answer = e.read() or b"{}"
        # the way's, not the notice's: a 5xx, the door's own 404 (X-Dgo-Door: its table does not know the office
        # yet), a timeout, a rate limit — kept and tried again. A plain 404 is the board's own answer.
        if e.code >= 500 or (e.code == 404 and e.headers.get("X-Dgo-Door")) or e.code in (408, 429):
            return False, e.code, answer
        try:
            what = json.loads(body)
        except ValueError:
            what = {}
        log(f"the hub refused a notice ({e.code}): source={what.get('source')} source_id={what.get('source_id')}")
        return True, e.code, answer
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return False, 0, json.dumps({"error": f"the hub did not answer: {e}"}).encode()


def spool_add(body: bytes) -> None:
    """Append ONE line (the body re-serialized: a pretty-printed body would be several lines, each refused). Past the
    caps the oldest are dropped, said in the log. Never while a flush is sending: the flush keeps its own count of the
    first lines it sent, so a trim here waits for the lock."""
    line = json.dumps(json.loads(body), ensure_ascii=False, separators=(",", ":"))
    with _LOCK:
        SPOOL.parent.mkdir(parents=True, exist_ok=True)
        with open(SPOOL, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        if SPOOL.stat().st_size > SPOOL_MAX_BYTES or len(_kept()) > SPOOL_MAX:
            lines = _kept()
            keep, size = [], 0
            for ln in reversed(lines):
                size += len(ln.encode("utf-8")) + 1
                if size > SPOOL_MAX_BYTES or len(keep) >= SPOOL_MAX:
                    break
                keep.append(ln)
            keep.reverse()
            log(f"the spool is full: the oldest {len(lines) - len(keep)} notice(s) dropped")
            tmp = SPOOL.with_suffix(".tmp")
            tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
            tmp.replace(SPOOL)


def _kept() -> list[str]:
    return [ln for ln in SPOOL.read_text(encoding="utf-8").splitlines() if ln.strip()] if SPOOL.exists() else []


def spool_flush() -> int:
    """Send the kept notices in order; stop at the first the hub does not take. Returns how many were sent. The lock
    is NOT held while the hub is asked (a poster must never wait on it); only appends happen meanwhile, at the end,
    so the first `sent` lines are exactly the ones sent."""
    with _LOCK:
        lines = _kept()
    sent, last = 0, 0
    for ln in lines:
        taken, last, _ = forward(ln.encode("utf-8"))
        if not taken:
            break
        sent += 1
    with _LOCK:
        rest = _kept()[sent:]
        if rest:
            tmp = SPOOL.with_suffix(".tmp")
            tmp.write_text("\n".join(rest) + "\n", encoding="utf-8")
            tmp.replace(SPOOL)
        else:
            SPOOL.unlink(missing_ok=True)
    if sent or rest:
        log(f"sent {sent} kept notice(s) to {HUB}; {len(rest)} still kept"
            + (f" (the hub answered {last or 'nothing'})" if rest else ""))
    return sent


class Handler(BaseHTTPRequestHandler):
    def _answer(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") == "/health":
            return self._answer(200, json.dumps({"ok": True, "hub": HUB, "hub_base": hub_base(),
                                                 "kept": len(SPOOL.read_text().splitlines()) if SPOOL.exists() else 0}).encode())
        self._answer(404, json.dumps({"error": f"this office has no board: its notices go to {HUB}'s"}).encode())

    def do_POST(self):  # noqa: N802
        if self.path.split("?")[0].rstrip("/") != "/api/notifications":
            return self._answer(404, b'{"error": "only POST /api/notifications is carried to the hub"}')
        length = int(self.headers.get("Content-Length") or 0)
        if length > BODY_MAX:
            return self._answer(413, b'{"error": "a notice is at most 256 KB"}')
        body = self.rfile.read(length)
        try:
            json.loads(body or b"{}")
        except ValueError:
            return self._answer(400, b'{"error": "the body is not JSON"}')
        if not _kept():   # notices already kept go first: a «back» never overtakes its «down»
            taken, status, answer = forward(body)
            if taken:
                return self._answer(status, answer)
        spool_add(body)
        self._answer(202, json.dumps({"queued": True, "hub": HUB}).encode())

    def log_message(self, fmt, *args):  # quiet: one line per kept or failed notice is enough
        pass


def retry_loop() -> None:
    while True:
        time.sleep(RETRY_S)
        try:
            spool_flush()
        except Exception as e:  # noqa: BLE001 — the loop is the relay's memory; it never dies on one bad line
            log(f"retry failed: {type(e).__name__}: {e}")


def main() -> int:
    if own_board():
        log(f"this office runs its own board (notifications-{DEPLOYMENT}): the relay does not serve, so the name "
            f"«notifications» never answers twice. Disable notify-relay, or the board.")
        while True:  # stay up and quiet rather than restart-loop; the log says why
            time.sleep(3600)
    log(f"carrying POST /api/notifications to {HUB}'s board ({hub_base() or 'no record yet'}); kept in {SPOOL}")
    threading.Thread(target=retry_loop, name="retry", daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
