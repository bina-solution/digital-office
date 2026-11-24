#!/usr/bin/env python3
"""test_webhooks — GitHub's webhook, from the public intake to a verified event (DGO-2155).

Driven in memory, with no GitHub, no vault and no network beyond 127.0.0.1:
- the intake (apps/github-hooks/intake.py, its own app since 2026-11-22) is served on two free loopback ports, GitHub's
  and git's, with a temp spool. The two apps share no volume: the drain reads only through git's door;
- the drain (webhooks.py drain_once, through HookSource) gets a lookup that knows one App's webhook_secret, and a sink
  that collects.
The signatures are made the way GitHub documents them: «sha256=» + HMAC-SHA256(secret, body) in hex. The second
reader's nine cases (2026-11-20) are claims here: a JSON bomb is never parsed, a slow body times out, a made-up App id
never reaches the spool, a forged POST with a real id never shadows the real delivery, and a bad spool file never stops
the drain.

Run: python3 apps/git/tests/test_webhooks.py      # exit 0 = every claim held
"""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
import time
import types
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
import webhooks  # noqa: E402

SECRET = "a-test-secret-not-a-real-one"
APP_ID = "123456"
os.environ["WEBHOOK_APP_IDS"] = APP_ID
os.environ["WEBHOOK_READ_TIMEOUT"] = "1"
os.environ["WEBHOOK_INTERNAL_PEER"] = "127.0.0.1"                   # the test is git, on loopback
spec = importlib.util.spec_from_file_location("intake", APP.parent / "github-hooks" / "intake.py")
intake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(intake)

FAIL: list[str] = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def post(port: int, body: bytes, headers: dict, path: str = "/github/webhook") -> tuple[int, dict, float]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}"), time.time() - t
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), time.time() - t


def gh_headers(body: bytes, delivery: str | None = None, event: str = "push", sig: str | None = None,
               target: str = APP_ID) -> dict:
    return {"X-GitHub-Delivery": delivery or str(uuid.uuid4()), "X-GitHub-Event": event,
            "X-Hub-Signature-256": sig if sig is not None else sign(body),
            "X-GitHub-Hook-Installation-Target-ID": target}


def main() -> int:
    spool = Path(tempfile.mkdtemp(prefix="gh-spool-"))
    state = Path(tempfile.mkdtemp(prefix="gh-state-"))
    intake.SPOOL = spool
    httpd = intake.serve(0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    door = intake.serve(0, intake.InternalHandler)
    threading.Thread(target=door.serve_forever, daemon=True).start()
    src = webhooks.HookSource(f"http://127.0.0.1:{door.server_address[1]}")
    try:
        body = json.dumps({"action": "opened", "issue": {"number": 7, "title": "a test with a line separator"}}).encode()
        h = gh_headers(body)
        code, doc, took = post(port, body, h)
        check(code == 202 and doc.get("kept") == h["X-GitHub-Delivery"], f"a delivery is kept and answered 202: {code} {doc}")
        check(took < 1.0, f"…well inside GitHub's 10 s: {took:.3f}s")
        code, doc, _ = post(port, body, h)
        check(code == 200 and "duplicate" in doc, f"the same delivery (id and signature) again is kept once: {code}")
        forged = json.dumps({"action": "deleted"}).encode()
        code, _, _ = post(port, forged, gh_headers(forged, delivery=h["X-GitHub-Delivery"], sig=sign(forged, "wrong")))
        check(code == 202, "a forged POST reusing a real id is kept APART (another signature): it never shadows it")
        code, _, _ = post(port, body, gh_headers(body, target="999"))
        check(code == 403, f"an App id this office did not declare never reaches the spool: {code}")
        code, _, _ = post(port, body, gh_headers(body, target="1²"))
        check(code == 400, f"a target that is not ASCII digits («1²»): {code}")
        code, _, _ = post(port, body, h, path="/admin")
        check(code == 404, f"every other path is not here: {code}")
        code, _, _ = post(port, body, {k: v for k, v in h.items() if k != "X-GitHub-Delivery"})
        check(code == 400, f"a POST without GitHub's headers is no delivery: {code}")
        code, _, _ = post(port, body, {**h, "X-GitHub-Delivery": "../../etc/passwd"})
        check(code == 400, f"a delivery id that is not a GUID never names a file: {code}")
        bomb = b"[" + b"{}," * 300000 + b"{}]"
        code, _, _ = post(port, bomb, gh_headers(bomb))
        check(code == 415, f"a JSON bomb (a 900 KB list) is refused unparsed: {code}")
        old = intake.MAX_BODY
        intake.MAX_BODY = 10
        code, _, _ = post(port, body, gh_headers(body))
        intake.MAX_BODY = old
        check(code == 413, f"a body over the cap: {code}")
        # a body that never comes: the connection is closed within READ_TIMEOUT and the slot comes back
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        hb = gh_headers(b"{}")
        s.sendall(("POST /github/webhook HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: 1000\r\n"
                   + "".join(f"{k}: {v}\r\n" for k, v in hb.items()) + "\r\n").encode() + b"{")
        t = time.time()
        try:
            got = s.recv(100)
        except OSError:
            got = b""
        s.close()
        check(time.time() - t < 5, f"a slow body is cut off within the read timeout ({time.time() - t:.1f}s)")
        code, _, _ = post(port, body, gh_headers(body))
        check(code == 202, "…and the door still answers after it")
        # a DRIP: one byte every 0.4 s. The deadline is for the whole body, so the slot comes back within it
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        s.sendall(("POST /github/webhook HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: 1000\r\n"
                   + "".join(f"{k}: {v}\r\n" for k, v in hb.items()) + "\r\n").encode())
        t = time.time()
        closed = False
        for _ in range(10):
            try:
                s.sendall(b" ")
                time.sleep(0.4)
            except OSError:
                closed = True
                break
        s.close()
        check(closed or time.time() - t < 3.5, f"a drip of one byte at a time is cut at the body's deadline ({time.time() - t:.1f}s)")
        # junk with no GitHub headers never spends GitHub's rate
        for _ in range(intake.RATE + 10):
            post(port, b"{}", {"X-GitHub-Event": "push"})
        code, _, _ = post(port, body, gh_headers(body))
        check(code == 202, f"after {intake.RATE + 10} header-less posts in a second, GitHub's delivery still goes: {code}")
        intake._room["at"] = 0
        old = intake.MAX_FILES
        intake.MAX_FILES = 2
        code, _, _ = post(port, body, gh_headers(body))
        intake.MAX_FILES = old
        intake._room["at"] = 0
        check(code == 507, f"a full spool says so: {code}")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as r:
            check(r.status == 200, "the container's health path answers")
        check(not any(SECRET in p.read_text() for p in spool.glob("*.json")), "no secret is in the spool")

        # THE DRAIN, through git's door. A door that does not answer (github-hooks not enabled here) is no event
        c = webhooks.drain_once(webhooks.HookSource("http://127.0.0.1:9"), state, lambda a: SECRET, lambda e: None)
        check(c["unreachable"] == 1 and c["verified"] == 0, f"a door that does not answer: «unreachable», nothing else: {c}")
        # a door that answers and refuses (no drain header: a wrong address or a stray caller) is «refused», a fault,
        # never the quiet «not enabled here» (the second reader)
        stranger = webhooks.HookSource(src.base)
        stranger.HEADERS = {}
        c = webhooks.drain_once(stranger, state, lambda a: SECRET, lambda e: None)
        check(c["refused"] == 403 and c["unreachable"] == 0, f"a refusing door is «refused 403»: {c}")
        # bad files first: a list, a symlink. They are removed and counted, and the pass goes on
        (spool / f"aaaaaaaa-0000-0000-0000-000000000000.{'0' * 16}.json").write_text("[]")
        (spool / f"bbbbbbbb-0000-0000-0000-000000000000.{'0' * 16}.json").symlink_to("/etc/hostname")
        got: list[dict] = []
        c = webhooks.drain_once(src, state, lambda a: None, got.append)
        check(c["unreadable"] == 2 and c["waiting"] == 4 and not got, f"bad files go, the rest wait for the vault: {c}")
        # an ack that fails loses nothing: the next batch brings the same files, and the recorded ones are duplicates
        lost = types.SimpleNamespace(batch=src.batch, ack=lambda drop, reject: False)
        c = webhooks.drain_once(lost, state, lambda a: SECRET if a == APP_ID else "", got.append)
        check(c["acked"] is False and len(list(spool.glob("*.json"))) == 4,
              f"a failed ack: all four still in the spool: {c}")
        check(c["verified"] == 3 and c["rejected"] + c["duplicate"] == 1,
              f"the true ones are verified; the forged twin, after its real one, is dropped unacted: {c}")
        c = webhooks.drain_once(src, state, lambda a: SECRET if a == APP_ID else "", got.append)
        check(c["duplicate"] == 4 and c["verified"] == 0 and len(got) == 3 and c["acked"] is True,
              f"…the next pass drops all four as recorded ids, never a second event: {c}")
        first = [e for e in got if e["delivery"] == h["X-GitHub-Delivery"]]
        check(len(first) == 1 and first[0]["action"] == "opened" and first[0]["payload"]["issue"]["number"] == 7,
              "the real delivery whose id a forger reused is the one recorded")
        check(not list(spool.glob("*.json")), "the spool is empty after the pass")
        # a forger FIRST: its POST with an id GitHub will use arrives before GitHub's own
        x = str(uuid.uuid4())
        real = json.dumps({"action": "closed"}).encode()
        post(port, forged, gh_headers(forged, delivery=x, sig=sign(forged, "wrong")))
        time.sleep(0.01)
        post(port, real, gh_headers(real, delivery=x))
        c = webhooks.drain_once(src, state, lambda a: SECRET, got.append)
        check(c["rejected"] == 1 and c["verified"] == 1 and got[-1]["action"] == "closed",
              f"a forger first is rejected, and GitHub's own delivery after it is still recorded: {c}")
        check(len(list((spool / ".rejected").glob("*.json"))) == 1,
              "the forged one is kept apart, in the spool's .rejected/ (one filesystem: no EXDEV)")
        before = len(got)
        post(port, body, h)
        c = webhooks.drain_once(src, state, lambda a: SECRET, got.append)
        check(c["duplicate"] == 1 and len(got) == before, f"a redelivery of a recorded id is dropped: {c}")
        b2 = json.dumps({"action": "x"}).encode()
        post(port, b2, gh_headers(b2))
        c = webhooks.drain_once(src, state, lambda a: "", got.append)
        check(c["unknown_app"] == 1, f"a target the vault knows no App for is dropped at once: {c}")
        post(port, b2, gh_headers(b2))
        c = webhooks.drain_once(src, state, lambda a: None, got.append, now=lambda: time.time() + webhooks.WAIT_MAX + 5)
        check(c["expired"] == 1, f"past WAIT_MAX with the vault unreadable, a delivery is dropped: {c}")
        check(webhooks.verify(body, sign(body), SECRET) and not webhooks.verify(body, sign(body), "")
              and not webhooks.verify(body, "sha1=" + "0" * 40, SECRET) and not webhooks.verify(body, "sha256=é", SECRET),
              "verify: the right one, no secret, a sha1 header, a non-ASCII one")
        # the vault lookup: one App whose secret read fails (a deleted instance) never empties the map for the others
        fake = types.SimpleNamespace(
            vault_list=lambda: ([{"id": "gone", "protocol": "git_github_app"}, {"id": "ok", "protocol": "git_github_app"},
                                 {"id": "pat", "protocol": "git_github_pat"}], None),
            vault_secret=lambda cid: None if cid == "gone" else {"app_id": APP_ID, "webhook_secret": SECRET})
        sys.modules["accounts"] = fake
        look = webhooks.vault_secret_for()
        check(look(APP_ID) == SECRET and look("777") == "", "one App's failed secret read leaves the others' in the map")
        sys.modules["accounts"] = types.SimpleNamespace(vault_list=lambda: ([], "the vault is down"),
                                                        vault_secret=lambda cid: None)
        check(webhooks.vault_secret_for()(APP_ID) is None, "a vault that does not answer is «can't tell», never «no App»")
        sink = webhooks.events_sink(state)
        sink({"delivery": "d", "event": "ping", "title": "a b"})
        lines = (state / "events.jsonl").read_text(encoding="ascii").split("\n")
        check(all(json.loads(x) for x in lines if x), "the events log is one JSON per line, a U+2028 in a title included")
    finally:
        httpd.shutdown()
        door.shutdown()
    print(f"test_webhooks: {'all passed' if not FAIL else str(len(FAIL)) + ' failed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
