#!/usr/bin/env python3
"""test_flowpub.py — the office's ONE flow.v1 publisher (flowpub.py, DGO-1402), against a redis that is a
twenty-line fake on a local port: what goes on the wire, what is refused, and that the app is never held.

    python3 platform-base/redis/test_flowpub.py        (G72 runs it; standard library only)
"""
from __future__ import annotations

import importlib.util
import json
import os
import socket
import socketserver
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FAILS: list[str] = []
LOADS: list[str] = []      # one name per load of flowpub.py: each is a module of its own


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"\n        {detail}"))
    if not ok:
        FAILS.append(name)


class FakeRedis(socketserver.ThreadingTCPServer):
    """Speaks just enough RESP: AUTH/MULTI/EXEC/XADD/EXPIRE, answering as redis does inside a transaction,
    and records every command it was sent."""
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, password: str = ""):
        self.commands: list[list[str]] = []
        self.password = password
        super().__init__(("127.0.0.1", 0), Handler)


class Handler(socketserver.StreamRequestHandler):
    def read_cmd(self):
        line = self.rfile.readline()
        if not line:
            return None
        assert line[:1] == b"*", line
        n = int(line[1:])
        parts = []
        for _ in range(n):
            size = int(self.rfile.readline()[1:])
            parts.append(self.rfile.read(size + 2)[:-2].decode("utf-8"))
        return parts

    def handle(self):
        in_multi, queued = False, []
        while True:
            cmd = self.read_cmd()
            if cmd is None:
                return
            self.server.commands.append(cmd)
            name = cmd[0].upper()
            if name == "AUTH":
                ok = cmd[1] == self.server.password
                self.wfile.write(b"+OK\r\n" if ok else b"-WRONGPASS invalid password\r\n")
            elif name == "MULTI":
                in_multi, queued = True, []
                self.wfile.write(b"+OK\r\n")
            elif name == "EXEC":
                in_multi = False
                time.sleep(getattr(self.server, "slow_exec", 0.0))   # a redis that ran it, and answers late
                self.wfile.write(b"*2\r\n$15\r\n1700000000000-0\r\n:1\r\n")
            elif in_multi:
                queued.append(cmd)
                self.wfile.write(b"+QUEUED\r\n")
            else:
                self.wfile.write(b"-ERR unknown\r\n")


def fresh(srv: FakeRedis | None, password: str = ""):
    """flowpub as a new process would see it: the fake's address and password in its environment, and a module of
    its own — its own queue, counters and worker. (A reload re-ran the file inside ONE module, so the worker of the
    earlier load, still closing its last event, read the NEW queue and counters: on a loaded machine it sent case
    5's event over its old, live connection, and «redis away» read sent 2, failed 0 — the proof of 2026-11-11.)"""
    if srv is not None:
        os.environ["REDIS_HOST_INTERNAL"] = "127.0.0.1"
        os.environ["REDIS_PORT_INTERNAL"] = str(srv.server_address[1])
    os.environ["REDIS_PASSWORD"] = password
    LOADS.append("flowpub_load_%d" % len(LOADS))
    spec = importlib.util.spec_from_file_location(LOADS[-1], os.path.join(HERE, "flowpub.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[LOADS[-1]] = module
    spec.loader.exec_module(module)
    return module


def wait_for(cond, s: float = 3.0) -> bool:
    end = time.time() + s
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def main() -> int:
    srv = FakeRedis(password="pw-123")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fp = fresh(srv, "pw-123")

    # 1. one event: AUTH, then ONE transaction — XADD capped ~1000 with the contract's fields, EXPIRE 30 days
    ok = fp.emit("drive", "file.uploaded", "  הועלה   קובץ  ", data={"size": 52341}, link="#/m/drive")
    check("emit returns at once, queued", ok is True)
    check("the event reaches redis", wait_for(lambda: fp.stats()["sent"] == 1), repr(fp.stats()))
    cmds = srv.commands
    names = [c[0].upper() for c in cmds]
    check("AUTH first, then MULTI · XADD · EXPIRE · EXEC", names == ["AUTH", "MULTI", "XADD", "EXPIRE", "EXEC"], repr(names))
    xadd = next((c for c in cmds if c[0].upper() == "XADD"), [])
    check("the stream is dgo:flow:<app>, capped MAXLEN ~ 1000", xadd[1:6] == ["dgo:flow:drive", "MAXLEN", "~", "1000", "*"],
          repr(xadd[:6]))
    fields = dict(zip(xadd[6::2], xadd[7::2]))
    check("type/title/at/app/link/data, the title on one line",
          fields.get("type") == "file.uploaded" and fields.get("title") == "הועלה קובץ" and fields.get("app") == "drive"
          and fields.get("link") == "#/m/drive" and json.loads(fields.get("data", "{}")) == {"size": 52341}
          and fields.get("at", "").endswith("Z"), repr(fields))
    exp = next((c for c in cmds if c[0].upper() == "EXPIRE"), [])
    check("EXPIRE renews 30 days in the same transaction", exp == ["EXPIRE", "dgo:flow:drive", str(30 * 24 * 3600)], repr(exp))

    # 2. the contract refuses what is not an app id or a dotted type — and says so in its counters
    before = len(srv.commands)
    check("an app id with a colon is refused", fp.emit("drive:x", "file.uploaded", "x") is False)
    check("a type with no dot is refused", fp.emit("drive", "uploaded", "x") is False)
    check("…counted, not raised", fp.stats()["refused"] == 2, repr(fp.stats()))
    time.sleep(0.1)
    check("…and nothing was sent for them", len(srv.commands) == before)

    # 3. a span: one id on both events, the end carries t0 and ms; an exception is re-raised AND told
    srv.commands.clear()
    with fp.span("sites", "site.deploy", "פריסה", data={"site": "u"}):
        time.sleep(0.01)
    try:
        with fp.span("sites", "site.deploy", "פריסה"):
            raise ValueError("boom")
    except ValueError:
        reraised = True
    else:
        reraised = False
    check("a block's exception is not swallowed", reraised)
    check("four events sent", wait_for(lambda: sum(1 for c in srv.commands if c[0].upper() == "XADD") == 4),
          repr([c[:2] for c in srv.commands]))
    xs = [dict(zip(c[6::2], c[7::2])) for c in srv.commands if c[0].upper() == "XADD"]
    types = [x["type"] for x in xs]
    check("started · ended · started · failed", types == ["site.deploy.started", "site.deploy.ended",
                                                         "site.deploy.started", "site.deploy.failed"], repr(types))
    d = [json.loads(x["data"]) for x in xs]
    check("one span id per bar, the end with t0 and ms",
          d[0]["span"] == d[1]["span"] != d[2]["span"] == d[3]["span"] and "t0" in d[1] and d[1]["ms"] >= 0
          and d[3]["error"] == "ValueError" and d[1]["site"] == "u", repr(d))

    # 4. a data object too big for the stream is replaced by a note, never sent whole
    srv.commands.clear()
    # (a chat app's 2000-character message must pass whole — 8 KB of Hebrew; past DATA_MAX it is cut)
    fp.emit("demo-app", "message.new", "x", data={"text": "א" * 2000})
    check("a 2000-character Hebrew message goes whole", wait_for(lambda: any(
        c[0].upper() == "XADD" and "א" * 2000 in "".join(c) for c in srv.commands)))
    srv.commands.clear()
    wait_for(lambda: fp.flush(0.1))
    sent_before = fp.stats()["sent"]
    srv.slow_exec = 0.4    # this load is still closing its last event when the next one starts (case 5)
    fp.emit("drive", "file.uploaded", "x", data={"blob": "א" * 9000})
    check("the big event is sent", wait_for(lambda: any(c[0].upper() == "XADD" for c in srv.commands)))
    big = next(dict(zip(c[6::2], c[7::2])) for c in srv.commands if c[0].upper() == "XADD")
    check("…with its data cut to a note", json.loads(big["data"]).get("note", "").startswith("data cut"), big["data"][:80])

    # 5. redis away: emit still returns at once, the failure is counted, nothing is raised
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    dead_port = sock.getsockname()[1]
    sock.close()
    os.environ["REDIS_PORT_INTERNAL"] = str(dead_port)
    earlier, fp = fp, fresh(None, "pw-123")
    t = time.time()
    ok = fp.emit("drive", "file.uploaded", "x")
    check("redis away: emit does not wait", ok is True and time.time() - t < 0.05, f"{time.time() - t:.3f}s")
    check("…the failure is counted", wait_for(lambda: fp.stats()["failed"] >= 1), repr(fp.stats()))
    check("the earlier load closes its own last event, in its own counters",
          wait_for(lambda: earlier.stats()["sent"] == sent_before + 1), f"{earlier.stats()!r}, {sent_before} before")
    srv.slow_exec = 0.0
    check("…and this load counts nothing of it", fp.stats()["sent"] == 0, repr(fp.stats()))

    # 6. a wrong password is a failure the counters name, not an exception in the app
    os.environ["REDIS_PORT_INTERNAL"] = str(srv.server_address[1])
    fp = fresh(None, "wrong")
    fp.emit("drive", "file.uploaded", "x")
    check("a refused AUTH is counted with its reason",
          wait_for(lambda: fp.stats()["failed"] >= 1) and "WRONGPASS" in (fp.stats()["last_error"] or ""), repr(fp.stats()))

    # 7. the public name is never dialled: REDIS_HOST (the edge's TLS name in an office's .env) is ignored
    os.environ["REDIS_HOST"] = "redis.public.example"
    os.environ["REDIS_PASSWORD"] = "pw-123"
    os.environ.pop("REDIS_HOST_INTERNAL", None)
    import flowpub as fp7
    hosts = []
    real = fp7.socket.create_connection
    fp7.socket.create_connection = lambda addr, timeout=None: (hosts.append(addr[0]), real(("127.0.0.1", srv.server_address[1]), timeout))[1]
    try:
        fp7._Conn().close()
    finally:
        fp7.socket.create_connection = real
        os.environ.pop("REDIS_HOST", None)
    check("REDIS_HOST (the public name) is never dialled — the internal `redis` is", hosts == ["redis"], repr(hosts))

    # 8. a redis restart: the event after it is retried once on a fresh connection, not lost
    os.environ["REDIS_HOST_INTERNAL"] = "127.0.0.1"
    fp = fresh(None, "pw-123")
    srv.commands.clear()
    fp.emit("drive", "file.uploaded", "before")
    wait_for(lambda: fp.stats()["sent"] == 1)
    srv.shutdown(); srv.server_close()
    srv2 = FakeRedis.__new__(FakeRedis)
    srv2.commands, srv2.password = [], "pw-123"
    socketserver.ThreadingTCPServer.__init__(srv2, ("127.0.0.1", srv.server_address[1]), Handler)
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    fp.emit("drive", "file.uploaded", "after the restart")
    check("the first event after a restart is sent, not lost",
          wait_for(lambda: fp.stats()["sent"] == 2) and fp.stats()["failed"] == 0, repr(fp.stats()))
    check("flush() waits for the queue to drain", fp.flush(1.0) is True)

    # 9. a redis that ran the transaction and answers after the timeout: the event is NOT sent again — a retry
    #    there wrote it twice, and a relay that hands each `message.new` to an answerer answered twice (DGO-1732)
    fp = fresh(None, "pw-123")
    fp.TIMEOUT_S = 0.3
    fp.emit("demo-app", "message.new", "fast")
    wait_for(lambda: fp.stats()["sent"] == 1)
    srv2.slow_exec = 0.8
    fp.emit("demo-app", "message.new", "slow")
    wait_for(lambda: fp.stats()["failed"] == 1 or fp.stats()["sent"] == 2, 5)
    time.sleep(1.2)   # let any second send land in the fake before counting
    srv2.slow_exec = 0.0
    slow = [c for c in srv2.commands if c[0].upper() == "XADD" and "slow" in c]
    check("a reply that comes after the timeout is not retried: the event is written once", len(slow) == 1,
          f"{len(slow)} XADDs of it; stats {fp.stats()!r}")

    # 10. the command line (DGO-1797): a hook that cannot import this file opens a bar and closes it, the same
    #     events span() writes, sent before the process ends; its exit says whether redis took the event
    import subprocess
    cli_env = {**os.environ, "REDIS_HOST_INTERNAL": "127.0.0.1", "REDIS_PORT_INTERNAL": str(srv2.server_address[1]),
               "REDIS_PASSWORD": "pw-123"}

    def cli(*args, env=cli_env):
        p = subprocess.run([sys.executable, os.path.join(HERE, "flowpub.py"), *args], env=env,
                           capture_output=True, text=True, timeout=30)
        return p.returncode, p.stdout.strip(), p.stderr.strip()

    def xadds():
        return [dict(zip(c[6::2], c[7::2])) for c in srv2.commands if c[0].upper() == "XADD"]

    srv2.commands.clear()
    rc_, out, err = cli("start", "ci-runner", "job", "gates-hosted · 57ef890", "--data", '{"run_id": 42}')
    sid, _, t0 = out.partition(" ")
    check("start: exit 0, prints «<span> <t0_ms>»", rc_ == 0 and fp.SPAN_RE.match(sid) is not None and t0.isdigit(),
          f"rc={rc_} out={out!r} err={err!r}")
    x = xadds()
    check("…and redis has `job.started` with that span and the caller's data",
          len(x) == 1 and x[0]["type"] == "job.started" and x[0]["app"] == "ci-runner"
          and json.loads(x[0]["data"]) == {"run_id": 42, "span": sid}, repr(x))
    rc_, out, err = cli("end", "ci-runner", "job", sid, t0, "ok", "gates-hosted · 57ef890")
    x = xadds()
    end = json.loads(x[-1]["data"]) if x else {}
    check("end ok: `job.ended` with the same span, its t0 and a duration", rc_ == 0 and out == "" and len(x) == 2
          and x[-1]["type"] == "job.ended" and end.get("span") == sid and end.get("t0") == int(t0) and end.get("ms", -1) >= 0,
          f"rc={rc_} {x!r}")
    rc_, out, err = cli("end", "ci-runner", "job", sid, t0, "failed", "gates-hosted", "--data", '{"exit": 3}')
    x = xadds()
    check("end failed: `job.failed`, with the caller's data", rc_ == 0 and x[-1]["type"] == "job.failed"
          and json.loads(x[-1]["data"]).get("exit") == 3, f"rc={rc_} {x[-1:]!r}")
    before = len(srv2.commands)
    rc_, out, err = cli("start", "ci:runner", "job", "x")
    check("an app id the contract refuses: exit 1, the reason said, nothing sent",
          rc_ == 1 and "not sent" in err and len(srv2.commands) == before, f"rc={rc_} err={err!r}")
    rc_, out, err = cli("start", "ci-runner", "job", "x", "--data", "[1]")
    check("--data that is not a JSON object: exit 2", rc_ == 2, f"rc={rc_} err={err[-120:]!r}")
    rc_, out, err = cli("end", "ci-runner", "job", "a b", "1", "ok", "x")
    check("a span id that is not one word: exit 2", rc_ == 2, f"rc={rc_} err={err[-120:]!r}")
    rc_, out, err = cli("start", "ci-runner", "job", "x", env={**cli_env, "REDIS_PORT_INTERNAL": str(dead_port)})
    check("redis away: exit 1, said — and the span still printed, so the hook's end closes what it opened",
          rc_ == 1 and "not sent" in err and len(out.split()) == 2, f"rc={rc_} out={out!r} err={err!r}")

    srv2.shutdown()
    print(f"\n{'all passed' if not FAILS else f'{len(FAILS)} failed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
