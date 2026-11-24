"""webhooks.py — what the `git` app does with the deliveries its public intake kept (DGO-2155, DGO-2138 §7.4).

The intake is its own app (apps/github-hooks/intake.py). It answers GitHub in milliseconds and writes each delivery to
its own spool, knowing no secret. Here, inside the app the internet never reaches, the drain asks the intake's
office-network door for a batch (GET /internal/batch), judges each delivery, and tells it what to drop and what to
keep apart (POST /internal/ack). The two share no volume. Each delivery is judged here:
- the HMAC: `X-Hub-Signature-256` over the exact body, with the `webhook_secret` of the GitHub App whose id the
  delivery names (`X-GitHub-Hook-Installation-Target-ID`), read from the credential plane at call time like every
  key of this app. A delivery that fails it is acked as «reject» (the intake keeps it apart in .rejected/, capped),
  never acted on.
- a target the vault knows no App for is dropped at once. While the vault cannot be read, deliveries wait, up to
  WAIT_MAX: a delivery nobody can verify is no event.
- dedupe: a delivery id already recorded is dropped (GitHub's redeliveries reuse the id). The record is written right
  after each event's sink, never at the end of a pass.
- the event goes to `sink`. Today that is the events log in this app's state (events.jsonl, capped); «ניהול גרסאות»
  takes them from there once its receiver exists. That is the seam: drain_once's `sink`.
Every delivery is judged on its own: one that is not a delivery is dropped and counted, and none stops the pass (the
second reader, 2026-11-20). A failed ack loses nothing: the next batch brings the same files, and dedupe drops the
ones already recorded.

Pure where it can be: verify() and drain_once() take their source, their secret lookup, their sink and their clock as
arguments, so the tests drive them with no network. A lookup answers a secret, "" (the vault answered, no such App)
or None (the vault cannot be read now). A source's batch() answers the intake's batch, or None when it cannot be
reached (the intake is not enabled on this office, or is down).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Protocol

WAIT_MAX = int(os.environ.get("WEBHOOK_WAIT_MAX", str(72 * 3600)))
SEEN_KEEP = int(os.environ.get("WEBHOOK_SEEN_KEEP", "20000"))       # delivery ids remembered for dedupe
EVENTS_KEEP = int(os.environ.get("WEBHOOK_EVENTS_KEEP", "5000"))   # lines kept in events.jsonl
SIG = re.compile(r"^sha256=[0-9a-f]{64}$")


def verify(body: bytes, signature: str, secret: str) -> bool:
    """GitHub's own check: «sha256=» + HMAC-SHA256(secret, body) in hex, compared in constant time."""
    if not secret or not isinstance(signature, str) or not SIG.match(signature):
        return False
    want = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want.encode("ascii"), signature.encode("ascii"))


_LINES: dict[str, int] = {}             # lines appended per file since it was last counted (never a reread per line)


def _append(p: Path, line: str, keep: int) -> None:
    """One line appended. The file is counted once per process, then by what this process appends, and cut back to its
    newest `keep` lines once it holds twice that: the whole file is read only at a cut, never at each line."""
    with p.open("a", encoding="ascii") as f:
        f.write(line + "\n")
    key = str(p)
    try:
        if key not in _LINES:
            with p.open("rb") as f:
                _LINES[key] = sum(1 for _ in f)
        else:
            _LINES[key] += 1
        if _LINES[key] > 2 * keep:
            lines = p.read_text(encoding="ascii").splitlines()[-keep:]
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_text("\n".join(lines) + "\n", encoding="ascii")
            os.replace(tmp, p)
            _LINES[key] = len(lines)
    except OSError:
        _LINES.pop(key, None)


def events_sink(state: Path) -> Callable[[dict], None]:
    """The sink until «ניהול גרסאות» receives: one JSON line per event in <state>/events.jsonl, ASCII-escaped so no
    character in a title can split a line, the newest EVENTS_KEEP kept."""
    out = state / "events.jsonl"

    def sink(event: dict) -> None:
        _append(out, json.dumps(event, ensure_ascii=True), EVENTS_KEEP)
    return sink


def _seen(state: Path) -> set[str]:
    try:
        return set((state / "webhook-seen.txt").read_text(encoding="ascii").split())
    except (OSError, UnicodeDecodeError):
        return set()


class Source(Protocol):
    def batch(self) -> dict | None: ...
    def ack(self, drop: list[str], reject: list[str]) -> bool: ...


class HookSource:
    """The intake's office-network door (apps/github-hooks, :8980). No secret crosses it, only the deliveries' bytes.
    It sends the drain's header, which the door requires beside git's address (intake.py DRAIN_HEADER)."""
    HEADERS = {"X-Webhook-Drain": "git"}

    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def batch(self) -> dict | None:
        """The batch; {"refused": <HTTP code>} when the door answers and says no; None when it does not answer."""
        req = urllib.request.Request(self.base + "/internal/batch", headers=self.HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read().decode("utf-8"))
            return d if isinstance(d, dict) else None
        except urllib.error.HTTPError as e:  # it answered: a 403 is a wrong address or header, never «not enabled»
            return {"refused": e.code}
        except (OSError, ValueError):       # not reachable: the app is not enabled here, or is down
            return None

    def ack(self, drop: list[str], reject: list[str]) -> bool:
        req = urllib.request.Request(self.base + "/internal/ack", method="POST",
                                     data=json.dumps({"drop": drop, "reject": reject}).encode("ascii"),
                                     headers={"Content-Type": "application/json", **self.HEADERS})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return 200 <= r.status < 300
        except (OSError, ValueError):
            return False


def drain_once(source: Source, state: Path, secret_for: Callable[[str], str | None], sink: Callable[[dict], None],
               now: Callable[[], float] = time.time) -> dict:
    """Judges one batch from the intake, oldest first, then acks it. Returns the counts, for the log and the screen."""
    counts = {"verified": 0, "rejected": 0, "waiting": 0, "duplicate": 0, "expired": 0, "unknown_app": 0,
              "unreadable": 0, "unreachable": 0, "refused": 0, "acked": True}
    got = source.batch()
    if got is None:
        counts["unreachable"] = 1
        return counts
    if got.get("refused"):
        counts["refused"] = int(got["refused"])
        return counts
    counts["unreadable"] = int(got.get("unreadable") or 0)
    state.mkdir(parents=True, exist_ok=True)
    seen = _seen(state)
    drop: list[str] = []
    reject: list[str] = []
    for d in got.get("deliveries") or []:
        name = d.get("name") if isinstance(d, dict) else None
        if not isinstance(name, str):
            counts["unreadable"] += 1
            continue
        try:
            delivery, body = str(d["delivery"]), str(d["body"]).encode("utf-8")
            target, signature = str(d.get("target") or ""), d.get("signature")
            if not isinstance(signature, str):
                raise ValueError("no signature")
        except (ValueError, KeyError, TypeError):
            counts["unreadable"] += 1
            drop.append(name)
            continue
        try:
            if delivery in seen:
                counts["duplicate"] += 1
                drop.append(name)
                continue
            secret = secret_for(target)
            if secret == "":
                counts["unknown_app"] += 1
                drop.append(name)
                continue
            if secret is None:
                if now() - float(d.get("received_at") or 0) > WAIT_MAX:
                    counts["expired"] += 1
                    print(f"webhooks: {delivery} for app {target} waited past {WAIT_MAX}s with no secret: dropped",
                          flush=True)
                    drop.append(name)
                else:
                    counts["waiting"] += 1
                continue
            if not verify(body, signature, secret):
                counts["rejected"] += 1
                reject.append(name)
                continue
            payload = json.loads(body.decode("utf-8"))
            sink({"delivery": delivery, "event": d.get("event"), "app_id": target,
                  "received_at": d.get("received_at"),
                  "action": payload.get("action") if isinstance(payload, dict) else None, "payload": payload})
            _append(state / "webhook-seen.txt", delivery, SEEN_KEEP)     # recorded right after its sink
            seen.add(delivery)
            counts["verified"] += 1
            drop.append(name)
        except Exception as e:  # noqa: BLE001 — one delivery never stops the pass; it stays for the next one
            print(f"webhooks: {name[:40]} not judged this pass: {type(e).__name__}"[:200], flush=True)
    if drop or reject:
        counts["acked"] = source.ack(drop, reject)
    return counts


def vault_secret_for() -> Callable[[str], str | None]:
    """The secret lookup the app's drain uses, built ONCE per pass: one read of the vault's instances and one secret
    per GitHub App, then a map from app_id to its `webhook_secret` (its second reader: thousands of made-up ids cost
    nothing more). A secret, "" when the vault answered and holds no such App, None when the vault cannot be read.
    No value is ever logged."""
    import accounts
    state: dict = {"built": False, "map": None}

    def build() -> dict | None:
        insts, err = accounts.vault_list()
        if err:
            return None
        m: dict[str, str] = {}
        for i in insts:
            if i.get("protocol") != "git_github_app":
                continue
            s = accounts.vault_secret(str(i.get("id") or ""))
            if s is None:                   # this instance alone (a deleted one answers 404): the others still count
                continue
            if str(s.get("app_id") or "").strip() and s.get("webhook_secret"):
                m[str(s["app_id"]).strip()] = str(s["webhook_secret"])
        return m

    def lookup(app_id: str) -> str | None:
        if not state["built"]:              # once per pass, a vault that did not answer included
            state["map"], state["built"] = build(), True
        if state["map"] is None:
            return None
        return state["map"].get(app_id, "")
    return lookup


LAST: dict = {"at": None, "counts": None}


def start(source_url: str, state: Path, every: float = 10.0) -> bool:
    """The drain, every `every` seconds, in a thread of the app. On an office that does not enable github-hooks the
    door does not answer: the drain asks once a minute and says so once, on the change, never on every pass."""
    import threading
    if not source_url:
        return False
    source = HookSource(source_url)

    def loop() -> None:
        said = None
        while True:
            c = None
            try:
                c = drain_once(source, state, vault_secret_for(), events_sink(state))
                LAST["counts"], LAST["at"] = c, time.time()
                # three states, each said once on its change: a refusal is a fault to fix (the queue fills behind
                # it, and GitHub gets 507), never the quiet «not enabled here» (the second reader)
                now = ("does not answer" if c["unreachable"] else
                       f"REFUSES the drain (HTTP {c['refused']}): its queue fills until this is fixed" if c["refused"]
                       else "answers")
                if now != said:
                    print(f"webhooks: the intake at {source_url} {now}", flush=True)
                    said = now
            except Exception as e:  # noqa: BLE001 — the drain outlives any one pass; the error is said, never hidden
                print(f"webhooks: a drain pass failed: {type(e).__name__}: {e}"[:300], flush=True)
            time.sleep(max(every, 60.0) if c and (c["unreachable"] or c["refused"]) else every)
    threading.Thread(target=loop, name="webhook-drain", daemon=True).start()
    return True
