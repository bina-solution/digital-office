"""status — a drive engine's own word on itself, for `./bbox drive-<engine> status` (hooks/status).

Run INSIDE the engine's container (the hook pipes it in): asks the engine's /ops, the vault for the rows
of its protocols, and the engine to say what each row is (/v1/accounts). Prints names, kinds and states —
never a key, a grant or a secret (the vault's list carries none). The same file in every drive engine.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

PORT = sys.argv[1] if len(sys.argv) > 1 else "8988"
ME = f"http://localhost:{PORT}"
VAULT = os.environ.get("CONNECTIONS_URL", "http://connections:8990")


def get(url):
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


try:
    ops = get(ME + "/ops")
except Exception as e:                                   # noqa: BLE001
    print(f"the engine does not answer on {ME}: {type(e).__name__}")
    sys.exit(1)
print(f"{ops.get('interface')} · for {ops.get('for')} · {ops.get('id')} ({ops.get('kind')}) · {ops.get('service')}")
for rung in ops.get("ladder") or []:
    print(f"  ladder  {rung.get('rung'):<13} {rung.get('state')}")
rows = []
for proto in ops.get("protocols") or {}:
    try:
        rows += [i for i in get(f"{VAULT}/api/instances?protocol={urllib.parse.quote(proto)}").get("instances", [])
                 if i.get("protocol") == proto]
    except Exception as e:                               # noqa: BLE001
        print(f"  the vault does not answer for {proto}: {type(e).__name__}")
accounts = post(ME + "/v1/accounts", {"instances": rows}).get("accounts") if rows else []
print(f"  {len(accounts)} account(s)")
for a in accounts:
    state = a.get("status") or "ok"
    extra = " · default" if a.get("default") else ""
    print(f"  - {a.get('id')}  {a.get('protocol')}  «{a.get('label') or a.get('account_hint') or ''}»  {state}{extra}"
          + (f"  ({a.get('reason')})" if a.get("reason") else ""))
