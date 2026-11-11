"""flow.py — read the office's event stream: the last N events, then every new one as it happens (flow.v1).

    ./bbox redis flow [app…] [-n N] [--once] [--json]      every stream, or only the apps named
    ./bbox telegram flow  ==  ./dgo telegram flow           an app's own `flow` verb: this, for its stream

THE CONTRACT (flow.v1, ai/context/build-your-first-app.md § «The event stream»). One Redis stream per app,
`dgo:flow:<app>`, in the redis every office already runs. An event is one XADD with the fields
`type` (dotted: `message.new`), `title` (one line a person reads), `at` (ISO-8601 UTC), `app`, and optionally
`link` (an address in the console) and `data` (a JSON object). The publisher caps the stream (MAXLEN ~ 1000) and
renews its EXPIRE (30 days) with every event: redis has 256 MB and refuses writes when full (noeviction), and a
key with no TTL fails the deployment export (hooks/backup) — an event stream is a window, not the office's state.

HOW IT READS, AND WHY THIS WAY. The redis image has no Python, and the host cannot reach redis's port. So
redis-cli runs inside the redis container, and every answer that has to be PARSED comes out of a Lua script as
ONE line of JSON (redis's own cjson) — no parsing of redis-cli's human output. The live part is `XREAD BLOCK`,
used only as the wake-up: when it returns, the events after the last one shown are fetched by the same script.
Idle, that is one `docker exec` every BLOCK_MS. The password travels on redis-cli's stdin (REDISCLI_AUTH),
never on a command line, where `ps` on the host would show it.

The bash hook beside this (hooks/flow) resolves the engine, the container and the password and execs this
file; FLOW_CONTAINER and FLOW_PW come from it in the environment.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime

PREFIX = "dgo:flow:"
BLOCK_MS = 15000
CONTAINER = os.environ.get("FLOW_CONTAINER", "")
PW = os.environ.pop("FLOW_PW", "")

# Every stream of the contract (SCAN inside redis: one round trip, whatever the keyspace's size).
LUA_STREAMS = """local out, c = {}, "0"
repeat
  local r = redis.call("SCAN", c, "MATCH", ARGV[1] .. "*", "COUNT", 1000, "TYPE", "stream")
  c = r[1]
  for _, k in ipairs(r[2]) do out[#out+1] = k end
until c == "0"
return cjson.encode(out)"""

# The last ARGV[1] events of each stream in KEYS, newest first per stream.
LUA_LAST = """local out = {}
for _, k in ipairs(KEYS) do out[k] = redis.call("XREVRANGE", k, "+", "-", "COUNT", tonumber(ARGV[1])) end
return cjson.encode(out)"""

# The events after ARGV[i] in KEYS[i] (exclusive), oldest first.
LUA_AFTER = """local out = {}
for i, k in ipairs(KEYS) do out[k] = redis.call("XRANGE", k, "(" .. ARGV[i], "+", "COUNT", 500) end
return cjson.encode(out)"""


class FlowError(RuntimeError):
    """Redis did not answer, or refused. Before the live part it ends the run; during it, the reader waits and
    tries again — a redis restart must not end a listener that an agent left running."""


def cli(*args: str, timeout: float = 30) -> str:
    """One redis-cli command inside the redis container; its raw stdout."""
    cmd = ["docker", "exec", "-i", CONTAINER, "sh", "-c",
           'read -r REDISCLI_AUTH; export REDISCLI_AUTH; exec redis-cli --no-auth-warning --raw "$@" </dev/null',
           "sh", *args]
    try:
        # UTF-8 whatever the host's code page: titles are Hebrew (Git-Bash on Windows decodes ANSI otherwise)
        r = subprocess.run(cmd, input=PW + "\n", capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return ""
    if r.returncode != 0:
        raise FlowError(f"redis did not answer ({(r.stderr or r.stdout).strip()[:200] or r.returncode})")
    out = r.stdout.strip()
    if out.startswith(("NOAUTH", "WRONGPASS", "ERR ")):
        raise FlowError(f"redis refused: {out[:200]}")
    return out


def lua(script: str, keys: list[str], argv: list[str]):
    raw = cli("EVAL", script, str(len(keys)), *keys, *argv)
    try:
        doc = json.loads(raw or "null")
    except ValueError:
        raise FlowError(f"redis's answer was not JSON: {raw[:200]}")
    return doc if doc not in (None, {}) else ({} if keys else [])   # cjson writes an empty table as {}


def event(stream: str, entry) -> dict:
    eid, flat = entry[0], entry[1] or []
    f = dict(zip(flat[0::2], flat[1::2]))
    data = f.get("data") or ""
    try:
        data = json.loads(data) if data else {}
    except ValueError:
        pass                                        # a publisher's plain string stays a string
    return {"id": eid, "app": f.get("app") or stream[len(PREFIX):], "type": f.get("type") or "",
            "title": f.get("title") or "", "at": f.get("at") or "", "link": f.get("link") or "", "data": data}


def order(eid: str) -> tuple[int, int]:
    ms, _, seq = eid.partition("-")
    return int(ms or 0), int(seq or 0)


def show(ev: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(ev, ensure_ascii=False), flush=True)
        return
    t = datetime.fromtimestamp(order(ev["id"])[0] / 1000)
    stamp = t.strftime("%H:%M:%S" if t.date() == datetime.now().date() else "%m-%d %H:%M:%S")
    tail = f"  {ev['link']}" if ev["link"] else ""
    print(f"{stamp}  {ev['app']:<12} {ev['type']:<20} {ev['title']}{tail}", flush=True)


def main(argv: list[str]) -> int:
    apps, n, once, as_json = [], 10, False, False
    it = iter(argv)
    for a in it:
        if a in ("-n", "--last"):
            try:
                n = max(0, min(1000, int(next(it, "10"))))
            except ValueError:
                sys.exit("flow: -n takes a number")
        elif a == "--once":
            once = True
        elif a == "--json":
            as_json = True
        elif a in ("-h", "--help"):
            print(__doc__.split("\n\n")[0])
            return 0
        elif a.startswith("-"):
            sys.exit(f"flow: unknown option {a}")
        else:
            apps.append(a)
    if not CONTAINER:
        sys.exit("flow: no redis container named (run it as `./bbox redis flow`, not directly)")

    def streams() -> list[str]:
        return [PREFIX + a for a in apps] if apps else sorted(lua(LUA_STREAMS, [], [PREFIX]))

    try:
        keys = streams()
    except FlowError as e:
        sys.exit(f"flow: {e}")
    last = {k: "0-0" for k in keys}
    try:
        return follow(apps, keys, last, n, once, as_json, streams)
    except FlowError as e:
        sys.exit(f"flow: {e}")
    except KeyboardInterrupt:
        return 0


def follow(apps, keys, last, n, once, as_json, streams) -> int:
    if keys and n:
        hist = lua(LUA_LAST, keys, [str(n)])
        evs = sorted((event(k, e) for k, es in hist.items() for e in (es or [])), key=lambda e: order(e["id"]))
        for k, es in hist.items():
            if es:
                last[k] = es[0][0]                    # XREVRANGE: the newest first
        for ev in evs[-n:]:
            show(ev, as_json)
    elif keys:                                        # -n 0: nothing old, only what comes
        for k, es in lua(LUA_LAST, keys, ["1"]).items():
            if es:
                last[k] = es[0][0]
    if once:
        return 0
    if not as_json:
        names = ", ".join(k[len(PREFIX):] for k in keys) or "every app (none has published yet)"
        print(f"— live: {names} (Ctrl-C to stop)", file=sys.stderr, flush=True)
    rounds, down = 0, False
    while True:
        try:
            # a stream that appears while we listen is listened to (asked every 4th round: SCAN is the keyspace)
            if not apps and rounds % 4 == 0:
                for k in streams():
                    last.setdefault(k, "0-0")
            rounds += 1
            if not last:
                time.sleep(BLOCK_MS / 1000)
                continue
            ks = list(last)
            woke = cli("XREAD", "BLOCK", str(BLOCK_MS), "COUNT", "1", "STREAMS", *ks, *[last[k] for k in ks],
                       timeout=BLOCK_MS / 1000 + 20)
            if down:
                print("— redis answers again", file=sys.stderr, flush=True)
                down = False
            if not woke:
                continue
            got = lua(LUA_AFTER, ks, [last[k] for k in ks])
        except FlowError as e:
            if not down:
                print(f"— {e}; trying again every 5 s", file=sys.stderr, flush=True)
                down = True
            time.sleep(5)
            continue
        evs = []
        for k, es in got.items():
            for e in es or []:
                evs.append(event(k, e))
                last[k] = e[0]
        for ev in sorted(evs, key=lambda e: order(e["id"])):
            show(ev, as_json)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
