#!/usr/bin/env python3
"""test_intake — github-hooks' two doors: GitHub's public one, and the office-network one git drains (DGO-2155).

Driven on loopback with a temp spool, no GitHub and no git. The public door's full set of refusals (a JSON bomb, a
slow body, a drip, a full spool, a forged twin) is driven end to end, through the drain, in
apps/git/tests/test_webhooks.py. Here are the claims of git's door:
- it answers the `git` service alone: another address gets 403 and reads nothing;
- a batch is the OLDEST deliveries, within its file and byte caps, and never empty while one waits;
- a file the intake could not have written (a symlink, a name not its own, bytes that are no delivery) is removed and
  counted, and never stops the batch;
- an ack deletes what it drops and keeps apart what it rejects (the newest REJECTED_KEEP), and a name outside the
  spool's own pattern is refused: no ack reaches a path outside the spool.

Run: python3 apps/github-hooks/test_intake.py      # exit 0 = every claim held
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_ID = "424242"
os.environ["WEBHOOK_APP_IDS"] = APP_ID
os.environ["WEBHOOK_INTERNAL_PEER"] = "127.0.0.1"
sys.path.insert(0, str(HERE))
import intake  # noqa: E402

FAIL: list[str] = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


DRAIN = {"X-Webhook-Drain": "git"}


def call(port: int, path: str, body: dict | bytes | None = None, headers: dict | None = None,
         drain: bool = True) -> tuple[int, dict]:
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json", **(DRAIN if drain else {}),
                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def deliver_body(port: int, body: bytes) -> list[str]:
    d = str(uuid.uuid4())
    code, _ = call(port, "/github/webhook", body, {"X-GitHub-Delivery": d, "X-GitHub-Event": "push",
                                                   "X-Hub-Signature-256": "sha256=" + "0" * 64,
                                                   "X-GitHub-Hook-Installation-Target-ID": APP_ID})
    time.sleep(0.01)                        # distinct mtimes: «oldest first» is measurable
    return [d] if code == 202 else []


def deliver(port: int, n: int = 1, size: int = 0) -> list[str]:
    ids = []
    for _ in range(n):
        ids += deliver_body(port, json.dumps({"action": "opened", "pad": "x" * size}).encode())
    return ids


def main() -> int:
    spool = Path(tempfile.mkdtemp(prefix="gh-hooks-"))
    intake.SPOOL = spool
    pub, internal = intake.serve(0), intake.serve(0, intake.InternalHandler)
    for s in (pub, internal):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    p, i = pub.server_address[1], internal.server_address[1]
    try:
        # the public door, in brief
        ids = deliver(p, 3)
        check(len(ids) == 3, f"three GitHub deliveries are kept (202): {len(ids)}")
        code, _ = call(p, "/github/webhook", b"{}", {"X-GitHub-Delivery": str(uuid.uuid4()), "X-GitHub-Event": "push",
                                                     "X-Hub-Signature-256": "sha256=" + "0" * 64,
                                                     "X-GitHub-Hook-Installation-Target-ID": "999"})
        check(code == 403, f"an App id the office did not declare: {code}")
        code, _ = call(p, "/internal/batch")
        check(code == 404, f"git's door is not on GitHub's port: {code}")

        # git's door answers git alone
        intake.INTERNAL_PEER = "192.0.2.1"  # TEST-NET: never this test's address
        intake._peer.update(at=0.0, ips=set())
        code, doc = call(i, "/internal/batch")
        check(code == 403 and "deliveries" not in doc, f"another address gets 403 and reads nothing: {code}")
        code, _ = call(i, "/internal/ack", {"drop": [f"{ids[0]}.{'0' * 16}.json"]})
        check(code == 403 and len(list(spool.glob("*.json"))) == 3, "…and cannot ack: the spool is untouched")
        intake.INTERNAL_PEER = "127.0.0.1"
        intake._peer.update(at=0.0, ips=set())
        # git's address WITHOUT the drain's header: git's smart-HTTP proxy calls out from that address too (the reader)
        code, doc = call(i, "/internal/batch", drain=False)
        check(code == 403 and "deliveries" not in doc, f"git's address without the drain's header reads nothing: {code}")

        # a raw control character is no JSON, and would have inflated six-fold on disk (the reader's OOM)
        d = str(uuid.uuid4())
        code, _ = call(p, "/github/webhook", b"{" + b"\x01" * 1000 + b"}",
                       {"X-GitHub-Delivery": d, "X-GitHub-Event": "push", "X-Hub-Signature-256": "sha256=" + "0" * 64,
                        "X-GitHub-Hook-Installation-Target-ID": APP_ID})
        check(code == 415 and not list(spool.glob(f"{d}.*")), f"a body of raw control bytes is refused unkept: {code}")
        heb = json.dumps({"title": "שלום " * 2000}, ensure_ascii=False).encode()
        ids += deliver_body(p, heb)
        f = next(spool.glob(f"{ids[-1]}.*"))
        check(f.stat().st_size < 2 * len(heb), f"a Hebrew body is kept as UTF-8, under twice its size: "
                                               f"{f.stat().st_size} for {len(heb)}")

        # a batch: the oldest, within the caps
        code, doc = call(i, "/internal/batch")
        got = [d["delivery"] for d in doc.get("deliveries", [])]
        check(code == 200 and got == ids, f"git gets every waiting delivery, oldest first: {code} {len(got)}")
        check(all(d["name"].startswith(d["delivery"]) and intake.NAME.match(d["name"]) for d in doc["deliveries"]),
              "each comes with the spool name to ack it by")
        old = intake.BATCH_FILES
        intake.BATCH_FILES = 2
        _, doc = call(i, "/internal/batch")
        intake.BATCH_FILES = old
        check([d["delivery"] for d in doc["deliveries"]] == ids[:2], "a file cap gives the two OLDEST")
        old = intake.BATCH_BYTES
        intake.BATCH_BYTES = 10
        _, doc = call(i, "/internal/batch")
        intake.BATCH_BYTES = old
        check(len(doc["deliveries"]) == 1, "a byte cap smaller than one delivery still gives one (never stuck)")

        # files the intake could not have written
        (spool / "not-a-delivery.json").write_text("{}")
        (spool / f"{uuid.uuid4()}.{'a' * 16}.json").write_text("[1, 2]")
        (spool / f"{uuid.uuid4()}.{'b' * 16}.json").symlink_to("/etc/hostname")
        _, doc = call(i, "/internal/batch")
        check(doc["unreadable"] == 3 and len(doc["deliveries"]) == len(ids),
              f"a foreign name, a list, a symlink: removed and counted, the batch goes on: {doc['unreadable']}")
        check(sorted(q.name for q in spool.iterdir()) == sorted(d["name"] for d in doc["deliveries"]),
              "only the deliveries are left in the spool")

        # acks
        names = [d["name"] for d in doc["deliveries"]]
        outside = spool.parent / f"{uuid.uuid4()}.{'c' * 16}.json"
        outside.write_text("{}")
        code, n = call(i, "/internal/ack", {"drop": [names[0], "../" + outside.name, "/etc/passwd", 7],
                                            "reject": [names[1]]})
        check(code == 200 and n == {"dropped": 1, "rejected": 1, "refused": 3}, f"drop one, reject one, refuse three: {n}")
        check(outside.exists(), "a name with a path is refused: the file outside the spool is still there")
        check([q.name for q in (spool / ".rejected").iterdir()] == [names[1]], "the rejected one is kept in .rejected/")
        _, doc = call(i, "/internal/batch")
        check([d["name"] for d in doc["deliveries"]] == names[2:], "the next batch holds only what was not acked")
        _, n = call(i, "/internal/ack", {"drop": [names[0]]})
        check(n == {"dropped": 0, "rejected": 0, "refused": 0}, f"an ack twice is harmless: {n}")
        old = intake.REJECTED_KEEP
        intake.REJECTED_KEEP = 2
        more = deliver(p, 3)
        _, doc = call(i, "/internal/batch")
        call(i, "/internal/ack", {"reject": [d["name"] for d in doc["deliveries"]]})
        intake.REJECTED_KEEP = old
        kept = list((spool / ".rejected").iterdir())
        check(len(kept) == 2 and len(more) == 3, f".rejected/ keeps the newest REJECTED_KEEP: {len(kept)}")
        code, _ = call(i, "/internal/ack", b"[1]")
        check(code == 400, f"an ack that is not an object: {code}")
        code, _ = call(i, "/internal/ack", b"x" * (300 * 1024))
        check(code == 413, f"an ack over 256 KB: {code}")
        outside.unlink()
        # a read that fails (here EACCES; on an office EIO or EMFILE) never deletes a real delivery (the reader)
        if os.geteuid() != 0:               # root reads a mode-000 file: the case cannot be made there
            locked = deliver(p, 1)
            f = next(spool.glob(f"{locked[0]}.*"))
            f.chmod(0)
            _, doc = call(i, "/internal/batch")
            f.chmod(0o644)
            check(f.exists() and locked[0] not in [d["delivery"] for d in doc["deliveries"]] and doc["unreadable"] == 0,
                  "a delivery that cannot be read now is kept for the next batch, not deleted")
            _, doc = call(i, "/internal/batch")
            check(locked[0] in [d["delivery"] for d in doc["deliveries"]], "…and the next batch brings it")
    finally:
        pub.shutdown()
        internal.shutdown()
    print(f"test_intake: {'all passed' if not FAIL else str(len(FAIL)) + ' failed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
