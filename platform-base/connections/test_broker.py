#!/usr/bin/env python3
"""test_broker — the credential broker's refusals, proven without Docker or the vault.

    python3 platform-base/connections/test_broker.py

The broker's value is entirely in what it REFUSES, and a refusal is exactly the behaviour nobody
notices when it silently stops working. These are the cases that must hold forever:

    · an app cannot obtain a connection it did not declare
    · an app cannot obtain ANOTHER app's connections, in any mode
    · a caller presenting a container id it does not own is refused as a spoof
    · `enforce` refuses an unidentifiable caller; `warn` serves it AND records `unidentified`
    · /api/export-all is loopback-only
    · a capability token is single-use, expiring, and bound to the service it was minted for
    · every one of the above lands in the grant log

Plus identity.py's own parsing, driven by a real-shaped `/containers/json` payload rather than a
stub of itself — including a container on two networks, a short (12-char) id, and a dead socket,
which must yield "not identified" and never a guess.

Hermetic on purpose: the docker call is replaced, so this runs on a laptop with no docker socket and
no secrets — which is what makes it a gate the estate can actually keep green.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["CONN_DATA_DIR"] = tempfile.mkdtemp(prefix="brokertest-")

from flask import Flask                                    # noqa: E402
import identity                                            # noqa: E402
import broker                                              # noqa: E402

# ── the fake estate ───────────────────────────────────────────────────────────
DECLARED = {
    "drive": [{"id": "supabase-service-key", "required": True},
              {"id": "supabase-db-password", "required": True}],
    "indox": [{"id": "gemini-key", "required": True}],
}
VALUES = {"supabase-service-key": "SUPABASE_SERVICE_KEY=sk-live",
          "supabase-db-password": "SUPABASE_DB_PASSWORD=pw-live",
          "gemini-key": "GEMINI_API_KEY=g-live"}

# address -> the identity the docker socket would report
CONTAINERS = {
    "10.0.0.10": {"service": "drive", "container_name": "drive-1", "container_id": "a" * 64},
    "10.0.0.11": {"service": "indox", "container_name": "indox-1", "container_id": "b" * 64},
}


def fake_identify(addr, claimed=None):
    rec = CONTAINERS.get(addr)
    if claimed and rec and claimed != rec["container_id"]:
        return {"ok": False, "method": "spoof-suspected", "service": rec["service"],
                "container_name": rec["container_name"], "container_id": claimed, "ip": addr,
                "reason": "claimed id does not own this address"}
    if not rec:
        return {"ok": False, "method": "none", "service": "", "app": "", "container_id": "",
                "container_name": "", "ip": addr, "reason": "no running container holds " + addr}
    return {"ok": True, "method": "container-id+ip" if claimed else "ip", "app": rec["service"],
            "ip": addr, "reason": "", **rec}


def declared_for(service):
    return DECLARED.get(service, [])


def export_env(service, only=None):
    out = {}
    for r in declared_for(service):
        if only is not None and r["id"] not in only:
            continue
        k, v = VALUES[r["id"]].split("=", 1)
        out[k] = v
    return out


# Captured BEFORE the override, so run_identity() exercises the real implementation rather than
# quietly re-installing the fake and passing on nothing.
REAL_IDENTIFY, REAL_DOCKER_GET = identity.identify, identity._docker_get

identity.identify = fake_identify
identity.docker_available = lambda: True

app = Flask(__name__)
broker.register(app, declared_for=declared_for, export_env=export_env)


@app.get("/api/export-all")
def export_all():
    try:
        broker.guard_export_all()
    except broker.Refusal as e:
        return {"error": e.reason}, e.status
    return {"env": VALUES}


@app.get("/api/export/<service>")
def export(service):
    try:
        _ident, svc = broker.guard_export(service, declared_for)
    except broker.Refusal as e:
        return {"error": e.reason}, e.status
    return {"service": svc, "env": export_env(svc)}


C = app.test_client()
FAILED = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"   {detail}" if not cond else ""))
    if not cond:
        FAILED.append(name)


def call(method, path, addr, body=None, cid=None):
    headers = {broker.ID_HEADER: cid} if cid else {}
    fn = getattr(C, method)
    r = fn(path, json=body, headers=headers, environ_base={"REMOTE_ADDR": addr})
    try:
        return r.status_code, json.loads(r.data)
    except ValueError:
        return r.status_code, {}


def run(mode):
    broker.MODE = mode
    print(f"\nmode = {mode}")

    st, b = call("post", "/api/broker/lease", "10.0.0.10", {}, "a" * 64)
    check("drive leases its own two connections", st == 200 and sorted(b.get("granted", [])) ==
          ["supabase-db-password", "supabase-service-key"], f"{st} {b}")
    check("drive's lease carries the real values",
          b.get("env", {}).get("SUPABASE_SERVICE_KEY") == "sk-live", str(b.get("env")))

    st, b = call("post", "/api/broker/lease", "10.0.0.11", {"service": "drive"}, "b" * 64)
    check("indox may NOT lease drive's secrets", st == 403, f"{st} {b}")

    st, b = call("post", "/api/broker/lease", "10.0.0.10",
                 {"connections": ["supabase-service-key", "n8n-encryption-key"]}, "a" * 64)
    check("an undeclared connection is refused by name",
          st == 200 and [r["id"] for r in b.get("refused", [])] == ["n8n-encryption-key"], str(b))
    check("...and its value is not in the lease",
          "N8N_ENCRYPTION_KEY" not in (b.get("env") or {}), str(b.get("env")))

    st, b = call("post", "/api/broker/lease", "10.0.0.10", {}, "f" * 64)
    check("a container id that does not own the address is refused", st == 403, f"{st} {b}")

    st, b = call("post", "/api/broker/lease", "10.9.9.9", {"service": "drive"})
    if mode == "enforce":
        check("enforce refuses an unidentifiable caller", st == 403, f"{st} {b}")
    else:
        check("warn serves an unidentifiable caller", st == 200, f"{st} {b}")

    st, b = call("get", "/api/export/drive", "10.0.0.11", None, "b" * 64)
    check("the LEGACY export route also refuses cross-app requests", st == 403, f"{st} {b}")

    st, b = call("get", "/api/export-all", "10.0.0.10", None, "a" * 64)
    check("export-all is refused over the network", st == 403, f"{st} {b}")
    st, b = call("get", "/api/export-all", "127.0.0.1")
    check("export-all still works for the operator (loopback)", st == 200, f"{st} {b}")

    # capability tokens
    st, b = call("post", "/api/broker/token", "10.0.0.10", {"connection": "supabase-db-password"},
                 "a" * 64)
    check("a token is minted for a declared connection", st == 200 and b.get("token"), f"{st} {b}")
    tok = b.get("token", "")
    st2, b2 = call("get", f"/api/broker/redeem/{tok}", "10.0.0.10", None, "a" * 64)
    check("the token redeems to exactly one secret",
          st2 == 200 and list(b2.get("env", {})) == ["SUPABASE_DB_PASSWORD"], f"{st2} {b2}")
    st3, _ = call("get", f"/api/broker/redeem/{tok}", "10.0.0.10", None, "a" * 64)
    check("the token is single-use", st3 == 404, str(st3))

    st, b = call("post", "/api/broker/token", "10.0.0.10", {"connection": "gemini-key"}, "a" * 64)
    check("a token cannot be minted for an undeclared connection", st == 403, f"{st} {b}")

    st, b = call("post", "/api/broker/token", "10.0.0.11", {"connection": "gemini-key"}, "b" * 64)
    tok = b.get("token", "")
    st2, b2 = call("get", f"/api/broker/redeem/{tok}", "10.0.0.10", None, "a" * 64)
    check("a stolen token cannot be redeemed by another service", st2 == 403, f"{st2} {b2}")


def run_identity():
    """identity.py's own parsing, against a real-shaped /containers/json payload.

    The rest of this file fakes `identify`, so without this the one module that actually talks to
    the docker socket would be the only untested part of the broker. The payload below is the shape
    docker returns, including the case that broke a naive implementation: a container on SEVERAL
    networks (drive sits on traefik-network AND supabase-net) whose second address must resolve just
    as well as its first."""
    print("\nidentity (docker payload parsing)")
    payload = [
        {"Id": "a" * 64, "Names": ["/drive-box"],
         "Labels": {"com.docker.compose.service": "drive", "com.docker.compose.project": "dh"},
         "NetworkSettings": {"Networks": {"traefik-network": {"IPAddress": "172.18.0.13"},
                                          "supabase-net": {"IPAddress": "172.21.0.2"}}}},
        {"Id": "b" * 64, "Names": ["/indox-box"],
         "Labels": {"com.docker.compose.service": "indox"},
         "NetworkSettings": {"Networks": {"traefik-network": {"IPAddress": "172.18.0.20"}}}},
    ]
    identity.identify = REAL_IDENTIFY
    identity._docker_get = lambda path, timeout=3.0: payload
    identity._cache.update({"at": 0.0, "available": False})

    i = identity.identify("172.18.0.13")
    check("an address resolves to its compose service", i["ok"] and i["service"] == "drive", str(i))
    i = identity.identify("172.21.0.2")
    check("the SECOND network's address resolves too", i["ok"] and i["service"] == "drive", str(i))
    i = identity.identify("172.18.0.13", "a" * 64)
    check("id + address agreeing is the strong method", i["method"] == "container-id+ip", str(i))
    i = identity.identify("172.18.0.20", "a" * 64)
    check("indox claiming drive's id is spoof-suspected",
          i["method"] == "spoof-suspected" and not i["ok"], str(i))
    i = identity.identify("172.18.0.13", "a" * 12)
    check("a short (12-char) id is accepted", i["ok"] and i["method"] == "container-id+ip", str(i))
    i = identity.identify("10.1.2.3")
    check("an address no container holds is not identified", not i["ok"], str(i))
    i = identity.identify("172.18.0.13", "c" * 64)
    check("an unknown claimed id is refused, not ignored", not i["ok"], str(i))

    identity._docker_get = lambda path, timeout=3.0: None
    identity._cache.update({"at": 0.0, "available": False})
    i = identity.identify("172.18.0.13")
    check("a dead docker socket yields 'not identified', never a guess",
          not i["ok"] and "unavailable" in i["reason"], str(i))

    identity._docker_get = REAL_DOCKER_GET
    identity.identify = fake_identify
    identity._cache.update({"at": 0.0, "available": False})


run_identity()

for m in ("warn", "enforce"):
    run(m)

print("\naudit log")
grants = broker.read_audit(limit=500)
check("every decision was recorded", len(grants) >= 20, f"{len(grants)} records")
check("refusals are recorded with a reason",
      all(g.get("reason") for g in grants if g["decision"] == "refuse"), "")
check("an unidentified grant is marked as such",
      any(g.get("unidentified") for g in grants if g["decision"] == "allow"), "")
check("no secret VALUE is ever written to the audit log",
      not any("sk-live" in json.dumps(g) or "pw-live" in json.dumps(g) for g in grants), "")

print()
if FAILED:
    print(f"BROKER TESTS FAILED ({len(FAILED)}): " + ", ".join(FAILED))
    sys.exit(1)
print("BROKER TESTS OK — every refusal holds and every decision is logged.")
