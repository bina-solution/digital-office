#!/usr/bin/env python3
"""connections CLI — thin client over the service API (declarative catalog is the source of truth).

  connections list [--group G] [--blockers]   list connections + status
  connections get <id>                        run the resolve chain for one
  connections set <id> <value>                store a value (wizard / broker callback)
  connections health                          summary + install blockers
  connections manifest                        what each service requires

Env: CONN_URL (default http://localhost:8990).
"""
import json, os, sys, urllib.request

URL = os.environ.get("CONN_URL", "http://localhost:8990")
C = {"healthy": "\033[32m", "needs_action": "\033[33m", "degraded": "\033[33m",
     "missing": "\033[31m", "unset": "\033[90m", "0": "\033[0m", "b": "\033[1m", "d": "\033[90m"}


def api(path, method="GET", body=None):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(URL + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def cmd_list(args):
    grp = None
    blockers_only = "--blockers" in args
    if "--group" in args:
        grp = args[args.index("--group") + 1]
    d = api("/api/connections")
    rows = d["connections"]
    if grp:
        rows = [r for r in rows if grp.lower() in r["group"].lower()]
    if blockers_only:
        rows = [r for r in rows if r["required"] and r["status"] in ("missing", "needs_action")]
    last = None
    for r in rows:
        if r["group"] != last:
            print(f"\n{C['b']}== {r['group']} =={C['0']}"); last = r["group"]
        col = C.get(r["status"], "")
        star = "*" if r["required"] else " "
        print(f"  {col}{r['status']:<13}{C['0']} {star} {r['id']:<26} "
              f"{C['d']}{r['kind']:<12} src={r['source']:<7} {r.get('masked') or '—'}{C['0']}")
    print(f"\n{d['summary']['total']} connections · "
          f"blockers: {', '.join(d['summary']['install_blockers']) or 'none ✓'}")


def cmd_get(args):
    print(json.dumps(api(f"/api/resolve/{args[0]}", "POST"), indent=2))


def cmd_set(args):
    print(json.dumps(api(f"/api/set/{args[0]}", "POST", {"value": args[1]}), indent=2))


def cmd_health(_):
    d = api("/api/connections")["summary"]
    print(f"total={d['total']}  by_status={d['by_status']}")
    print(f"install_blockers: {', '.join(d['install_blockers']) or 'none ✓'}")


def cmd_manifest(_):
    print(json.dumps(api("/api/manifest")["manifest"], indent=2))


CMDS = {"list": cmd_list, "get": cmd_get, "set": cmd_set, "health": cmd_health, "manifest": cmd_manifest}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        print(__doc__); sys.exit(1)
    try:
        CMDS[sys.argv[1]](sys.argv[2:])
    except Exception as e:
        print(f"error: {e}", file=sys.stderr); sys.exit(1)
