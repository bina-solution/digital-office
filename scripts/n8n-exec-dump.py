#!/usr/bin/env python3
"""Dump what a node actually received and returned in an n8n execution.

Written because a static read of a 54-node workflow produced a confident, wrong answer. When a
workflow does nothing and says it succeeded, the only thing that settles it is the data one
execution carried, and getting at that meant hand-writing the same three awkward steps every time:
log in, find the execution, and un-flatten n8n's storage format.

n8n stores `execution_data.data` "flatted": index 0 is the root object and every string INSIDE a
container is an index into the same array. A referenced string is the value itself, so a naive
walk turns real strings into array indices and quietly hands you nonsense.

    scripts/n8n-exec-dump.py "Mail Label Engine"
    scripts/n8n-exec-dump.py "Mail Label Engine" --node "Get many messages"
    scripts/n8n-exec-dump.py 62 --node "Start Gmail Item" --full

Reads N8N_OWNER_* from .env and auto-detects the endpoint the same way apps/indox/hooks/test.py
does, so it works on a laptop, in WSL and in CI without arguments.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE, HOST_HDR = os.environ.get("INDOX_TEST_BASE", ""), os.environ.get("INDOX_TEST_HOST", "")


def env(key, default=""):
    try:
        for line in open(os.path.join(ROOT, ".env"), encoding="utf-8", errors="replace"):
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return default


def detect():
    global BASE, HOST_HDR
    if BASE:
        return
    for base, host in (("http://localhost:5678", ""), ("http://127.0.0.1", "n8n.localhost")):
        try:
            req = urllib.request.Request(base + "/rest/settings",
                                         headers={"Host": host} if host else {})
            with urllib.request.urlopen(req, timeout=5) as r:
                if r.status == 200:
                    BASE, HOST_HDR = base, host
                    return
        except Exception:
            pass
    sys.exit("n8n unreachable (tried localhost:5678 and traefik n8n.localhost)")


def req(path, method="GET", body=None, cookie=None, timeout=60):
    headers = {"Content-Type": "application/json"}
    if HOST_HDR:
        headers["Host"] = HOST_HDR
    if cookie:
        headers["Cookie"] = cookie
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.getheaders(), resp.read().decode()
    except urllib.error.HTTPError as e:
        return list(e.headers.items()), e.read().decode()


def _cookie_cache():
    import tempfile
    return os.path.join(tempfile.gettempdir(), ".n8n-exec-dump-cookie")


def login():
    """Log in, reusing a cached cookie.

    n8n rate-limits authentication, and this tool is most useful in a loop — scanning a range of
    executions to find the one you want. Logging in per invocation trips the limiter after a handful
    of calls and then reports "login failed", which reads as a credentials problem and is not one.
    So the cookie is cached and only re-minted when it stops working.
    """
    cache = _cookie_cache()
    try:
        cookie = open(cache, encoding="utf-8").read().strip()
        if cookie:
            _, body = req("/rest/login", cookie=cookie, timeout=15)
            if '"id"' in body and "unauthorized" not in body.lower():
                return cookie
    except OSError:
        pass

    headers, _ = req("/rest/login", "POST",
                     {"emailOrLdapLoginId": env("N8N_OWNER_EMAIL"),
                      "password": env("N8N_OWNER_PASSWORD")})
    cookies = [v.split(";")[0] for k, v in headers if k.lower() == "set-cookie"]
    if not cookies:
        sys.exit("n8n login failed — check N8N_OWNER_EMAIL / N8N_OWNER_PASSWORD in .env, "
                 "or wait a minute: n8n rate-limits repeated logins")
    cookie = "; ".join(cookies)
    try:
        with open(cache, "w", encoding="utf-8") as fh:
            fh.write(cookie)
        os.chmod(cache, 0o600)
    except OSError:
        pass
    return cookie


def deflatten(arr):
    """Resolve n8n's flatted array back into a normal object graph.

    The subtlety that bites: a string sitting inside a container is an INDEX, but the thing it
    points at may itself be a string — and that one is the value. Resolving one level too far
    turns every string into a lookup and the result into garbage.
    """
    def walk(node, depth=0):
        if depth > 60:
            return node
        if isinstance(node, str):
            if node.isdigit() and int(node) < len(arr):
                target = arr[int(node)]
                return target if isinstance(target, str) else walk(target, depth + 1)
            return node
        if isinstance(node, list):
            return [walk(x, depth + 1) for x in node]
        if isinstance(node, dict):
            return {k: walk(v, depth + 1) for k, v in node.items()}
        return node

    return walk(arr[0]) if arr else None


def latest_execution(cookie, wanted):
    """The newest execution of a workflow, by id or (case-insensitive) name."""
    if str(wanted).isdigit():
        return str(wanted)
    _, body = req("/rest/executions?limit=100", cookie=cookie)
    try:
        rows = (json.loads(body).get("data") or {}).get("results") or []
    except Exception:
        sys.exit("could not read /rest/executions — is the cookie valid?")
    for row in rows:
        name = ((row.get("workflowData") or {}).get("name")
                or row.get("workflowName") or "")
        if wanted.lower() in name.lower() or row.get("workflowId") == wanted:
            return str(row["id"])
    sys.exit(f"no execution found for {wanted!r} in the last 100")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workflow", nargs="?", default="",
                    help="execution id, workflow id, or part of the workflow name")
    # A workflow fired several times in one run (lanes, retries, a schedule) leaves several
    # executions, and "the newest" is rarely the one you want. Listing them with their trigger
    # input is how you pick the right one instead of dumping three and squinting.
    ap.add_argument("--list", action="store_true",
                    help="list recent executions (id, status, workflow, started) and exit")
    ap.add_argument("--limit", type=int, default=25, help="how many to list (default 25)")
    ap.add_argument("--node", help="only this node (default: every node that produced data)")
    ap.add_argument("--full", action="store_true", help="do not truncate values")
    ap.add_argument("--items", type=int, default=3, help="items per node (default 3)")
    # When a node reports no items but you have evidence it produced some, the question stops being
    # "what did the workflow do" and becomes "is this reader lying". --raw answers that: it prints
    # the node's runData exactly as n8n stored it, before any un-flattening.
    ap.add_argument("--raw", action="store_true",
                    help="print the node's stored runData verbatim, skipping interpretation")
    args = ap.parse_args()

    detect()
    cookie = login()

    if args.list:
        _, body = req(f"/rest/executions?limit={args.limit}", cookie=cookie)
        rows = (json.loads(body).get("data") or {}).get("results") or []
        for row in rows:
            name = ((row.get("workflowData") or {}).get("name")
                    or row.get("workflowName") or "?")
            if args.workflow and args.workflow.lower() not in name.lower():
                continue
            print(f"{row['id']:>7}  {str(row.get('status')):9}  {name[:44]:44}  "
                  f"{row.get('startedAt')}")
        return

    if not args.workflow:
        sys.exit("give an execution id, a workflow id, or part of a workflow name (or --list)")
    exec_id = latest_execution(cookie, args.workflow)
    _, body = req(f"/rest/executions/{exec_id}", cookie=cookie)
    data = json.loads(body).get("data") or {}

    print(f"execution {exec_id}  workflow={(data.get('workflowData') or {}).get('name')}  "
          f"status={data.get('status')}  started={data.get('startedAt')}")
    if data.get("status") == "error":
        print("  error:", str(data.get("data"))[:300])

    raw = data.get("data")
    if isinstance(raw, str):
        raw = json.loads(raw)
    if isinstance(raw, list):
        raw = deflatten(raw)
    run_data = (((raw or {}).get("resultData") or {}).get("runData")) or {}
    if not run_data:
        sys.exit("no runData in this execution (still running, or pruned by the data-retention setting)")

    trim = (lambda v: v) if args.full else (lambda v: v[:600] + "…" if len(v) > 600 else v)
    for node, runs in run_data.items():
        if args.node and args.node.lower() not in node.lower():
            continue
        print(f"\n─── {node} ───")
        if args.raw:
            print(json.dumps(runs, ensure_ascii=False)[:4000])
            continue
        for i, run in enumerate(runs or []):
            if run.get("error"):
                print(f"  run {i}: ERROR {str(run['error'])[:400]}")
            main_out = ((run.get("data") or {}).get("main") or [[]])[0] or []
            print(f"  run {i}: {len(main_out)} item(s)")
            for item in main_out[: args.items]:
                j = item.get("json") if isinstance(item, dict) else item
                print("     ", trim(json.dumps(j, ensure_ascii=False)))


if __name__ == "__main__":
    main()
