#!/usr/bin/env python3
"""test_api_verbs — the CLI faces of computers.v1 (DGO-1257) say what the app said, with the standard's exits.

`tools/api_verbs.py` is run with its one network call replaced by answers in the app's real shapes:
- probe() → {ok, state, reason, hostname, memory, disk, …};
- /exec → {code, stdout, stderr, timed_out, state, reason};
- POST /api/computers → {…, status: "ok", probe: {ok, state, reason}};
- /stream → {job: {id, state, …}}; /api/transfers/<job> → {transfer: {state, rate_bps, eta_s, error, …}}.

What it asks:
- the exits (the standard): 0 done, 1 failed, 2 usage, 3 not reachable;
- `exec` exits with the remote code (124 on a timeout, 128+N on a signal);
- what is printed for a machine that is down;
- a remote command's own flags are never taken;
- `rm` refuses `local` and wants --yes and a reason;
- `add` takes a secret only on stdin and never echoes it;
- unknown flags are refused by name.

Measured on the MacBook's live app (2026-11-10): list, status, audit, exec (local `exit 7` → 7, Exampleu's
hostname), and the rm refusals.

Run: python3 tests/test_api_verbs.py   (from apps/computers; standard library only)
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("api_verbs", HERE / "tools" / "api_verbs.py")
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
FAIL: list[str] = []
CALLS: list = []
ANSWER: dict = {}
KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAAsecretbytes\n-----END OPENSSH PRIVATE KEY-----\n"


def fake_call(method, path, body=None, timeout=120):
    CALLS.append((method, path, body))
    if ANSWER.get("down"):
        v.unreachable("connection refused")
    return ANSWER.get("status", 200), dict(ANSWER.get("out", {}))


v.call = fake_call


def run(*argv, answer=None, stdin=""):
    CALLS.clear()
    ANSWER.clear()
    ANSWER.update(answer or {})
    v.AS_JSON = False
    old = sys.stdin
    sys.stdin = io.StringIO(stdin)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = v.main(list(argv))
            except SystemExit as e:
                code = e.code
    finally:
        sys.stdin = old
    return code, out.getvalue(), err.getvalue(), list(CALLS)


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


DOWN = {"id": "c1", "label": "s", "host": "93.184.216.7", "status": "ok", "ok": False, "state": "error",
        "reason": "Connection refused"}
UP = {"id": "c1", "label": "s", "host": "93.184.216.7", "status": "ok", "ok": True, "state": "ok", "hostname": "h1",
      "memory": {"used_percent": 40.0, "available": 4e9}, "disk": {"used_percent": 24.0, "available": 154.6e9}}


def main() -> int:
    code, _, err, calls = run("status")
    check(code == 2 and not calls and "status <id|local>" in err, "a missing id is usage (2), nothing sent")
    check(run("bogus")[0] == 2, "an unknown verb is usage (2)")
    code, _, err, calls = run("status", "c1", "--frsh")
    check(code == 2 and "no flag --frsh" in err and not calls, "an unknown flag is refused by name")
    check(run("probe", "c1", "--fresh")[0] == 2, "probe has no --fresh: refused, not ignored")
    check(run("status", "--help")[0] == 0, "a verb's --help exits 0")

    code, out, _, calls = run("status", "local", "--fresh", answer={"out": DOWN})
    check(calls == [("GET", "/api/computers/computer_local-local/status?fresh=1", None)], "status reads the screen's route")
    check("state      error  — Connection refused" in out and "state      ok" not in out,
          f"a machine that is down says so, with the reason ({out!r})")
    code, out, *_ = run("status", "c1", answer={"out": UP})
    check(code == 0 and "hostname   h1" in out and "24.0% used, 154.6 GB free" in out and "40.0% used" in out,
          "a machine that is up shows its state, memory and disk")

    code, out, _, calls = run("exec", "c1", "--", "uname", "-s", answer={"out": {"code": 7, "stdout": "Linux\n"}})
    check(code == 7 and out == "Linux\n" and calls[0][2] == {"command": "uname -s", "timeout": 60},
          "exec exits with the remote command's own code and prints its output")
    code, _, _, calls = run("exec", "c1", "--", "grep", "--json", "--timeout", "5", "f", answer={"out": {"code": 0}})
    check(calls[0][2] == {"command": "grep --json --timeout 5 f", "timeout": 60} and code == 0,
          "the remote command's own flags are its own (never the CLI's --json/--timeout)")
    code, _, err, _ = run("exec", "c1", "--", "sleep 99",
                          answer={"out": {"code": None, "timed_out": True, "reason": "הפקודה לא הסתיימה בתוך 60 שניות"}})
    check(code == 124 and "לא הסתיימה" in err, "a timed-out exec exits 124 and says so")
    code, _, err, _ = run("exec", "c1", "--", "x", answer={"out": {"code": 255, "stderr": "", "state": "needs_action",
                                                                   "reason": "לא נוצר עדיין מפתח SSH ללשכה"}})
    check(code == 255 and "מפתח SSH" in err, "an exec that never ran says why, not silence")
    check(run("exec", "c1", "--", "x", answer={"out": {"code": -9}})[0] == 137, "ssh killed by a signal exits 128+N")
    check(run("exec", "c1", "--timeout", "0", "--", "x")[0] == 2, "a timeout of 0 is usage, never sent")
    check(run("exec", "c1", "--timeout", "-5", "--", "x")[0] == 2, "a negative timeout is usage, never a traceback")
    code, _, err, _ = run("exec", "c1", "--", "x", answer={"status": 404, "out": {"error": "לא נמצא"}})
    check(code == 1 and "לא נמצא" in err, "the app's refusal is the reason, exit 1")
    code, out, *_ = run("exec", "c1", "--json", "--", "x", answer={"down": True})
    check(code == 3 and '"ok": false' in out, "no answer from the app is exit 3, and --json still prints JSON")

    code, _, _, calls = run("rm", "local", "--yes", "--reason", "x")
    check(code == 1 and not calls, "rm never removes the computer the office runs on")
    check(run("rm", "c1", "--yes")[0] == 2, "rm without a reason removes nothing")
    code, out, _, calls = run("rm", "c1", "--yes", "--reason", "sold", answer={"out": {"ok": True, "id": "c1"}})
    check(code == 0 and calls == [("DELETE", "/api/computers/c1", None)] and "sold" in out,
          "rm --yes --reason is one DELETE of that computer")

    code, out, err, calls = run("add", "93.184.216.7", "--user", "u", "--key-stdin", stdin=KEY,
                                answer={"out": {"id": "c9", "label": "u@93.184.216.7", "status": "ok",
                                                "probe": {"ok": False, "state": "needs_action", "reason": "המפתח לא מורשה"}}})
    check(code == 0 and calls[0][2]["private_key"] == KEY and calls[0][2]["host"] == "93.184.216.7",
          "add takes the key from stdin")
    check("not reached yet: המפתח לא מורשה" in out, f"a new machine not reached yet says so ({out!r})")
    check("secretbytes" not in out + err, "the key is never echoed")
    code, _, _, calls = run("add", "93.184.216.7", "--key-stdin", stdin="not a key")
    check(code == 2 and not calls, "add refuses stdin that holds no private key")
    code, _, _, calls = run("add", "h", "--door-stdin", stdin="wss://x/share/tok\n", answer={"out": {"id": "c2"}})
    check(calls[0][2].get("door") == "wss://x/share/tok", "a share's door comes on stdin too")

    code, out, _, calls = run("transfer", "c1", "local", "vol", "--restart",
                              answer={"out": {"job": {"id": "j1", "state": "queued"}}})
    check(code == 0 and calls[0][:2] == ("POST", "/api/computers/c1/stream") and out.startswith("j1  queued"),
          f"transfer starts the stream route and prints the job's id ({out!r})")
    code, out, *_ = run("transfer", "status", "j1",
                        answer={"out": {"transfer": {"state": "error", "phase": "send", "percent": 40.0,
                                                     "rate_bps": 1000, "eta_s": None, "error": "ssh: broken pipe"}}})
    check(code == 1 and "state error" in out and "rate_bps 1000" in out and "broken pipe" in out,
          f"a failed transfer says so, with the real fields, exit 1 ({out!r})")

    print("test_api_verbs:", "FAIL" if FAIL else "PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
