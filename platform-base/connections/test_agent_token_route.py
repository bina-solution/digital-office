#!/usr/bin/env python3
"""test_agent_token_route — an agent's action token leaves the vault for dgo-extend alone (DGO-1127).

    python3 platform-base/connections/test_agent_token_route.py

`GET /api/agent-token/<service>` is how the office that SERVES an agent reads its token, to hand it to
the office it is linked with: dgo-extend used to read it over ssh to its own machine, which a machine
with no sshd does not have. The token drives the office's agent, so:

  · only `dgo-extend`, identified by BOTH factors (container id and address), in every broker mode —
    warn serves an unidentified caller elsewhere, and must not here; the operator on loopback too;
  · the token is read with GETs (`identity.agent_token`): the container's own `AGENT_TOKEN_FILE`, then
    that one file from its archive, and only a container of the vault's own compose project;
  · every answer is in the grant log.

Hermetic: the docker API is replaced by the answers it would give.
"""
import contextlib
import io
import json
import os
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("CONN_DATA_DIR", tempfile.mkdtemp(prefix="agenttoken-"))
import app  # noqa: E402
import identity  # noqa: E402

TOKEN = "t" * 64
EXTEND = {"ok": True, "method": "container-id+ip", "service": "dgo-extend", "app": "dgo-extend",
          "container_name": "dgo-extend-local", "container_id": "e" * 64, "ip": "172.18.0.9",
          "project": "office"}
EXTEND_IP_ONLY = {**EXTEND, "method": "ip", "container_id": ""}
#: another office's dgo-extend on the same docker host — the office network is shared (the second reader, #3)
EXTEND_OTHER_OFFICE = {**EXTEND, "container_id": "9" * 64, "project": "other-office"}
OTHER = {**EXTEND, "service": "drive", "app": "drive", "container_name": "drive-1", "container_id": "d" * 64}
UNIDENTIFIED = {"ok": False, "method": "none", "service": "", "app": "", "container_id": "",
                "container_name": "", "ip": "172.18.0.99", "reason": "no running container holds this address"}
LOOPBACK = {"ok": True, "method": "loopback", "service": "connections", "app": "connections",
            "container_id": "", "container_name": "connections(local)", "ip": "127.0.0.1"}


@contextlib.contextmanager
def _as(ident, mode="warn", token=(TOKEN, ""), project="office"):
    real = app.broker.caller, app.broker.MODE, identity.agent_token, identity.own_project
    app.broker.caller, app.broker.MODE = (lambda: dict(ident)), mode
    identity.agent_token = lambda service: token if service == "bina-ds" else ("", f"no running container of {service}")
    identity.own_project = lambda: project
    try:
        yield app.app.test_client()
    finally:
        app.broker.caller, app.broker.MODE, identity.agent_token, identity.own_project = real


def _log():
    try:
        with open(app.broker.GRANT_LOG, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except OSError:
        return []


def test_dgo_extend_with_both_factors_reads_the_token_and_it_is_logged():
    with _as(EXTEND) as c:
        r = c.get("/api/agent-token/bina-ds")
    assert r.status_code == 200 and r.get_json() == {"service": "bina-ds", "token": TOKEN}, r.get_json()
    last = _log()[-1]
    assert (last["event"], last["decision"], last["service"], last["agent"]) == ("agent-token", "allow", "dgo-extend", "bina-ds")
    assert TOKEN not in json.dumps(last)


def test_every_other_caller_is_refused_in_every_mode():
    for mode in ("warn", "enforce", "off"):
        for who in (EXTEND_IP_ONLY, OTHER, UNIDENTIFIED, EXTEND_OTHER_OFFICE):
            with _as(who, mode) as c:
                r = c.get("/api/agent-token/bina-ds")
            assert r.status_code == 403 and "token" not in r.get_json(), (mode, who["method"], r.get_json())
    assert _log()[-1]["decision"] == "refuse"


def test_a_vault_that_cannot_tell_its_own_office_serves_nobody_but_the_operator():
    with _as(EXTEND, project="") as c:
        assert c.get("/api/agent-token/bina-ds").status_code == 403
    with _as(LOOPBACK, project="") as c:
        assert c.get("/api/agent-token/bina-ds").status_code == 200


def test_the_operator_on_loopback_may_read_it():
    with _as(LOOPBACK) as c:
        assert c.get("/api/agent-token/bina-ds").status_code == 200


def test_a_service_with_no_token_is_a_404_and_a_bad_name_a_400():
    with _as(EXTEND) as c:
        r = c.get("/api/agent-token/drive")
        assert r.status_code == 404 and "drive" in r.get_json()["error"], r.get_json()
        assert c.get("/api/agent-token/Bad..Name!").status_code in (400, 404)


def _tar(name, data):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_the_token_is_read_with_gets_from_this_projects_container_that_names_its_file():
    asked = []
    containers = [
        {"Id": "f" * 64, "Labels": {"com.docker.compose.service": "bina-ds", "com.docker.compose.project": "other-office"}},
        {"Id": "1" * 64, "Labels": {"com.docker.compose.service": "bina-ds", "com.docker.compose.project": "office"}},
        {"Id": "2" * 64, "Labels": {"com.docker.compose.service": "bina-ds", "com.docker.compose.project": "office"}},
    ]
    configs = {"f" * 64: ["AGENT_TOKEN_FILE=/data/dsh/api-token"],
               "1" * 64: ["PATH=/usr/bin"],                         # the self-update helper: no token file
               "2" * 64: ["DSH_HOME=/data/dsh", "AGENT_TOKEN_FILE=/data/dsh/api-token"]}

    def get(path, timeout=3.0):
        asked.append(path)
        if path.startswith("/containers/json"):
            return containers
        return {"Config": {"Env": configs[path.split("/")[2]]}}

    def raw(path, timeout=5.0, limit=1 << 20):
        asked.append(path)
        cid = path.split("/")[2]
        return _tar("api-token", (("x" if cid == "f" * 64 else "y") * 64 + "\n").encode())

    real = identity._docker_get, identity._docker_get_raw, identity._fresh, identity.self_container_id
    identity._docker_get, identity._docker_get_raw = get, raw
    identity._fresh = lambda force=False: {"by_id": {"c" * 64: {"project": "office"}}}
    identity.self_container_id = lambda: "c" * 64
    try:
        token, why = identity.agent_token("bina-ds")
    finally:
        identity._docker_get, identity._docker_get_raw, identity._fresh, identity.self_container_id = real
    assert token == "y" * 64 and why == "", (token, why)
    assert not any(("f" * 64) in p for p in asked), asked             # another office's container: never read
    assert any(p == f"/containers/{'2' * 64}/archive?path=/data/dsh/api-token" for p in asked), asked


def test_no_container_with_a_token_file_says_so():
    real = identity._docker_get, identity._fresh, identity.self_container_id
    identity._docker_get = lambda path, timeout=3.0: [] if path.startswith("/containers/json") else {}
    identity._fresh = lambda force=False: {"by_id": {"c" * 64: {"project": "office"}}}
    identity.self_container_id = lambda: "c" * 64
    try:
        token, why = identity.agent_token("bina-ds")
    finally:
        identity._docker_get, identity._fresh, identity.self_container_id = real
    assert token == "" and "AGENT_TOKEN_FILE" in why, why


def test_a_vault_that_cannot_tell_its_project_reads_no_container_at_all():
    asked = []
    real = identity._docker_get, identity._fresh, identity.self_container_id
    identity._docker_get = lambda path, timeout=3.0: asked.append(path) or []
    identity._fresh = lambda force=False: {"by_id": {}}
    identity.self_container_id = lambda: ""
    try:
        token, why = identity.agent_token("bina-ds")
    finally:
        identity._docker_get, identity._fresh, identity.self_container_id = real
    assert token == "" and "project" in why and asked == [], (why, asked)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    bad = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as e:                                # noqa: BLE001 — report every test
            bad += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")
    print(f"agent_token_route: {len(tests)} test(s), {len(tests) - bad} pass, {bad} fail")
    raise SystemExit(1 if bad else 0)
