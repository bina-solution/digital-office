#!/usr/bin/env python3
"""test_instance_secret_relay — an instance's secret is read and written by this office's own services only (hos-001).

    python3 platform-base/connections/test_instance_secret_relay.py

`GET`/`PUT /api/instances/<iid>/secret` serve the office's services that call `connections:8990` directly
(drive, git, computers, the link plane). Before this gate anything that reached the vault read and wrote every
secret: a linked office's request (mapped to akadmin), the console's app proxy, the edge. A request that carries
a relay header (traefik's X-Forwarded-*, the identity the edge or a link door writes, the link's office headers)
is refused with 403 and the refusal is in the grant log; a direct call is served as before.

Hermetic: the vault lives in a temporary directory, and the caller is the drive service by both factors.
"""
import contextlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["CONN_DATA_DIR"] = tempfile.mkdtemp(prefix="secretrelay-")   # never the real grant log
import app  # noqa: E402

DRIVE = {"ok": True, "method": "container-id+ip", "service": "drive", "app": "drive",
         "container_name": "drive-1", "container_id": "d" * 64, "ip": "172.18.0.7", "project": "office"}
FAILS = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAILS.append(what)


@contextlib.contextmanager
def client():
    real = app.broker.caller
    app.broker.caller = lambda: dict(DRIVE)
    try:
        yield app.app.test_client()
    finally:
        app.broker.caller = real


def main() -> int:
    # the vault's path is fixed beside app.py, not under CONN_DATA_DIR: a test that does not move it writes a
    # vault into the checkout (test_totp_route does the same)
    app.VAULT_PATH = os.path.join(tempfile.mkdtemp(prefix="secretrelay-vault-"), "vault.enc")
    iid = app.create_instance("google-oauth", "probe", {"refresh_token": "r" * 20}, "probe@example.com", iid="probe-1")
    url = f"/api/instances/{iid}/secret"
    with client() as c:
        r = c.get(url)
        check(r.status_code == 200 and r.get_json()["secret"].get("refresh_token") == "r" * 20,
              "a direct in-network call reads the secret")
        r = c.put(url, data=json.dumps({"secret": {"access_token": "a1"}}), content_type="application/json")
        check(r.status_code == 200, "a direct in-network call writes the secret back")
        for header, value in (("X-Forwarded-For", "192.168.16.50"), ("X-Forwarded-Host", "connections.localhost"),
                              ("X-Real-Ip", "10.0.0.1"), ("X-authentik-username", "akadmin"),
                              ("X-DGO-Office", "hp-laptop"), ("X-Dgo-Identity", "sig"), ("X-DGO-From", "vps1")):
            r = c.get(url, headers={header: value})
            body = r.get_json() or {}
            check(r.status_code == 403 and "secret" not in body and header in body.get("error", ""),
                  f"a read relayed through {header} is refused, and says why")
            r = c.put(url, headers={header: value}, data=json.dumps({"secret": {"access_token": "x"}}),
                      content_type="application/json")
            check(r.status_code == 403, f"a write relayed through {header} is refused")
        r = c.get(url)
        check(r.get_json()["secret"].get("access_token") == "a1", "no relayed write reached the vault")
    try:
        with open(app.broker.GRANT_LOG, encoding="utf-8") as f:
            log = [json.loads(ln) for ln in f if ln.strip()]
    except OSError:
        log = []
    for event in ("instance-secret", "instance-secret-put"):
        check(any(e.get("decision") == "refuse" and e.get("event") == event and e.get("instance") == iid for e in log),
              f"the {event} refusal is in the grant log, naming the instance")
    print(f"{'OK' if not FAILS else 'FAILED'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
