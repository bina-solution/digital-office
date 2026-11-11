"""api_verbs — the CLI faces of computers.v1 (DGO-1257): every verb is one call to this app's own API.

Run INSIDE the computers container (tools/verb does it: `docker exec … python3 -c <this file> <verb> …`),
against http://127.0.0.1:8977, the routes the screen calls. Nothing here talks ssh or reads the vault:
the app does that, once, for every face (ai/context/app-cli-api-standard.md).

    list   [--json]                                  the fleet (no SSH round trip)
    status <id|local> [--fresh] [--json]             one computer's live state: reachable or why not
    probe  <id|local> [--json]                       reach it again now («בדוק מחדש»)
    audit  <id|local> [--fresh] [--json]             the machine's security findings («אבטחה»)
    exec   <id|local> [--timeout S] [--json] -- <command…>   run a command ON it; exits with its code
    add    <host> [--user U] [--port P] [--label L] [--key @file | --door @file] [--json]
    rm     <id> --yes --reason "…" [--json]          forget a computer and its stored key; never `local`
    transfer <from> <to> <volume> [--dest-volume V] [--restart] [--json]   a resumable volume copy
    transfer status <job> [--json]  |  transfer cancel <job>

Exit codes (the standard): 0 done (a read: it answered) · 1 failed (the app said why) · 2 usage · 3 the
app did not answer. `exec` exits with the remote command's own code: 124 when it timed out, 128+N when ssh
died of a signal. A remote code of 1–3 reads like the standard's own, so tell them apart with --json.
A secret (a private key, a share's door) arrives on stdin: `--key @file` and `--door @file` are read by
tools/verb on this machine and piped in, never put on a command line.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8977"
LOCAL = "computer_local-local"
MAX_TIMEOUT = 600                    # app.py MAX_TIMEOUT: the app clamps to it
AS_JSON = False


def usage(msg: str = "") -> int:
    if msg:
        print(f"computers: {msg}", file=sys.stderr)
    for line in __doc__.splitlines():              # the verbs, as the docstring lists them
        if line.startswith("    "):
            print(line, file=sys.stderr)
    return 2


def unreachable(e) -> None:
    if AS_JSON:
        print(json.dumps({"ok": False, "error": f"the computers app did not answer ({e})"}))
    print(f"computers: the app did not answer ({e})", file=sys.stderr)
    sys.exit(3)


def call(method: str, path: str, body=None, timeout: int = 120):
    """(status, json) — a 4xx/5xx with a body is the app's answer; no answer at all is exit 3."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {"error": f"HTTP {e.code}"}
    except (urllib.error.URLError, OSError, ValueError) as e:
        unreachable(e)


def why(out: dict) -> str:
    return str(out.get("error") or out.get("reason") or out.get("detail") or out.get("message") or out)


def cid_of(x: str) -> str:
    return LOCAL if x == "local" else x


def size(v) -> str:
    if isinstance(v, dict) and "used_percent" in v:                  # how full, and how much is left
        left = v.get("available")
        return f"{v['used_percent']}% used" + (f", {left / 1e9:.1f} GB free" if isinstance(left, (int, float)) else "")
    return str(v)


def main(argv: list[str]) -> int:
    global AS_JSON
    if not argv or argv[0] in ("-h", "--help", "help"):
        usage()
        return 0 if argv else 2
    verb, rest = argv[0], argv[1:]
    # the CLI's own flags are read BEFORE `--` only: what follows is the remote command, word for word
    cut = rest.index("--") if "--" in rest else len(rest)
    head, tail = rest[:cut], rest[cut + 1:] if cut < len(rest) else []
    if "-h" in head or "--help" in head:
        usage()
        return 0
    AS_JSON = "--json" in head
    head = [a for a in head if a != "--json"]
    takes = {"list": set(), "status": {"--fresh"}, "probe": set(), "audit": {"--fresh"},
             "exec": {"--timeout"}, "add": {"--user", "--port", "--label", "--key-stdin", "--door-stdin"},
             "rm": {"--yes", "--reason"}, "transfer": {"--dest-volume", "--restart"}}
    if verb not in takes:
        return usage(f"unknown verb {verb!r}")
    valued = {"--timeout", "--user", "--port", "--label", "--reason", "--dest-volume"}
    i = 0
    while i < len(head):
        a = head[i]
        if a.startswith("--"):
            if a not in takes[verb]:
                return usage(f"{verb}: no flag {a}")
            if a in valued and i + 1 >= len(head):
                return usage(f"{a} needs a value")
            i += 2 if a in valued else 1
        else:
            i += 1

    def flag(name: str) -> bool:
        if name in head:
            head.remove(name)
            return True
        return False

    def opt(name: str, default: str = "") -> str:
        if name in head:
            j = head.index(name)
            val = head[j + 1]
            del head[j:j + 2]
            return val
        return default

    def done(status: int, out: dict, line: str) -> int:
        ok = 200 <= status < 300
        if AS_JSON:
            print(json.dumps(out, ensure_ascii=False))
        elif ok:
            print(line)
        else:
            print(f"computers {verb}: {why(out)}", file=sys.stderr)
        return 0 if ok else 1

    if verb == "list":
        if head:
            return usage("list takes no arguments")
        st, out = call("GET", "/api/computers?probe=0")
        if AS_JSON or st != 200:
            return done(st, out, "")
        for c in out.get("computers", []):
            where = f"{c.get('user')}@{c.get('host')}"
            print(f"{c['id']:28} {(c.get('label') or ''):24} {where}" + ("  (shared)" if c.get("shared") else ""))
        return 0

    if verb in ("status", "probe", "audit"):
        fresh = flag("--fresh")
        if len(head) != 1:
            return usage(f"{verb} <id|local>")
        cid = urllib.parse.quote(cid_of(head[0]), safe="")
        if verb == "status":
            st, out = call("GET", f"/api/computers/{cid}/status?fresh={int(fresh)}")
        elif verb == "probe":
            st, out = call("POST", f"/api/computers/{cid}/probe")
        else:
            st, out = call("GET", f"/api/computers/{cid}/audit?fresh={int(fresh)}", timeout=300)
        if AS_JSON or st != 200:
            return done(st, out, "")
        if verb == "audit":
            counts = out.get("counts") or {}
            print(f"{out.get('label') or out.get('id')}  ({out.get('host')})  "
                  + "  ".join(f"{k} {counts.get(k, 0)}" for k in ("error", "warn", "info", "ok")))
            for f in out.get("findings", []):
                print(f"  {f.get('severity', ''):5}  {f.get('title', '')}" + (f"  → {f['fix']}" if f.get("fix") else ""))
            return 0
        # the PROBE's verdict (`ok`, `state`, `reason`), never the vault row's own `status`, which is always "ok"
        state = out.get("state") or ("ok" if out.get("ok") else "error")
        print(f"{out.get('id')}  {out.get('label') or ''}  ({out.get('host')})")
        print(f"{'state':10} {state}" + ("" if out.get("ok") else f"  — {out.get('reason') or 'no answer'}"))
        for k in ("hostname", "os", "kernel", "uptime", "load", "ncpu", "memory", "disk"):
            if out.get(k) not in (None, ""):
                print(f"{k:10} {size(out[k])}")
        return 0

    if verb == "exec":
        timeout = opt("--timeout", "60")
        if len(head) != 1 or not tail:
            return usage("exec <id|local> [--timeout S] [--json] -- <command…>")
        try:
            t = int(timeout)
        except ValueError:
            return usage("--timeout is a whole number of seconds")
        if not 1 <= t <= MAX_TIMEOUT:
            return usage(f"--timeout is 1–{MAX_TIMEOUT} seconds (the app's own range)")
        st, out = call("POST", f"/api/computers/{urllib.parse.quote(cid_of(head[0]), safe='')}/exec",
                       {"command": " ".join(tail), "timeout": t}, timeout=t + 30)
        if AS_JSON:
            print(json.dumps(out, ensure_ascii=False))
        elif st == 200:
            sys.stdout.write(out.get("stdout") or "")
            sys.stderr.write(out.get("stderr") or "")
        if st != 200:
            if not AS_JSON:
                print(f"computers exec: {why(out)}", file=sys.stderr)
            return 1
        code = out.get("code")
        if not AS_JSON and (out.get("timed_out") or (code == 255 and not out.get("stderr") and out.get("reason"))):
            print(f"computers exec: {out.get('reason') or 'it did not answer'}", file=sys.stderr)  # say why it ended
        if out.get("timed_out"):
            return 124
        if isinstance(code, int) and code < 0:
            return min(255, 128 - code)            # ssh died of a signal
        return code if isinstance(code, int) and 0 <= code < 256 else 1

    if verb == "add":
        body = {"user": opt("--user", "root"), "label": opt("--label")}
        port = opt("--port", "22")
        try:
            body["port"] = int(port)
        except ValueError:
            return usage("--port is a number")
        if flag("--key-stdin"):
            key = sys.stdin.read()
            if "PRIVATE KEY" not in key:
                return usage("--key: the file holds no private key")
            body["private_key"] = key
        elif flag("--door-stdin"):
            body["door"] = sys.stdin.read().strip()
        if len(head) != 1:
            return usage("add <host> [--user U] [--port P] [--label L] [--key @file | --door @file]")
        body["host"] = head[0]
        st, out = call("POST", "/api/computers", body, timeout=120)
        probe = out.get("probe") or {}
        reach = "reached" if probe.get("ok") else f"added, not reached yet: {probe.get('reason') or 'no answer'}"
        return done(st, out, f"{out.get('id')}  {out.get('label')}  ({reach})")

    if verb == "rm":
        yes, reason = flag("--yes"), opt("--reason")
        if len(head) != 1:
            return usage('rm <id> --yes --reason "…"')
        if head[0] in ("local", LOCAL):
            print("computers rm: the computer the office runs on is built in and is never removed", file=sys.stderr)
            return 1
        if not yes or not reason.strip():
            print(f"computers rm {head[0]}: this forgets the computer and its stored key for good (the vault keeps "
                  "no copy) — say --yes and --reason \"…\"", file=sys.stderr)
            return 2
        st, out = call("DELETE", f"/api/computers/{urllib.parse.quote(head[0], safe='')}")
        return done(st, out, f"{head[0]} removed ({reason.strip()})")

    if verb == "transfer":
        if head[:1] in (["status"], ["cancel"]):
            if len(head) != 2:
                return usage(f"transfer {head[0]} <job>")
            job = urllib.parse.quote(head[1], safe="")
            if head[0] == "status":
                st, out = call("GET", f"/api/transfers/{job}")
                row = out.get("transfer") or {}
                if AS_JSON or st != 200:
                    return done(st, out, "")
                parts = [f"{k} {row[k]}" for k in ("state", "phase", "percent", "done_bytes", "total", "rate_bps", "eta_s")
                         if row.get(k) not in (None, "")]
                print("  ".join(parts) + (f"  — {row['error']}" if row.get("error") else ""))
                return 1 if row.get("state") == "error" else 0
            st, out = call("POST", f"/api/transfers/{job}/cancel")
            return done(st, out, f"{head[1]} stopped (a resumable copy keeps its staging file: start it again to resume)")
        dest, restart = opt("--dest-volume"), flag("--restart")
        if len(head) != 3:
            return usage("transfer <from> <to> <volume> [--dest-volume V] [--restart]")
        body = {"to": cid_of(head[1]), "volume": head[2], "restart": restart}
        if dest:
            body["dest_volume"] = dest
        st, out = call("POST", f"/api/computers/{urllib.parse.quote(cid_of(head[0]), safe='')}/stream", body)
        job = out.get("job") if isinstance(out.get("job"), dict) else {}
        return done(st, out, f"{job.get('id')}  {job.get('state') or 'started'} — follow it: computers transfer status {job.get('id')}")

    return usage(f"unknown verb {verb!r}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
