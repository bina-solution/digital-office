#!/usr/bin/env python3
"""test_totp_route — the `totp` kind at the API: validated on write, minted only for an identified,
declared consumer (in every mode), never exported, never revealed over the network.

    python3 platform-base/connections/test_totp_route.py

Hermetic: a temp vault, a two-row catalog, and the broker's caller replaced by the identities the
docker socket would report — plus the flask test client's own loopback, which is the operator.
"""
import contextlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("CONN_DATA_DIR", tempfile.mkdtemp(prefix="totproute-"))
import app  # noqa: E402

ROW = "browser42-totp-facebook"
FIELD = "BROWSER42_LOGIN_FACEBOOK_TOTP"
PROV = {"id": ROW, "group": "Apps", "kind": "totp", "env": FIELD, "probe": {"type": "present"}}
PW = {"id": "browser42-login-facebook", "group": "Apps", "kind": "password",
      "env": "BROWSER42_LOGIN_FACEBOOK_PASSWORD"}
SERVICE = "browser42-task-runner"
KEY = "JBSWY3DPEHPK3PXP"

# What identity.identify reports for the callers that matter (see identity.py).
RUNNER = {"ok": True, "method": "container-id+ip", "service": SERVICE, "app": "browser42",
          "container_name": "browser42-task-runner-1", "container_id": "a" * 64, "ip": "10.0.0.5"}
OTHER_APP = {**RUNNER, "service": "drive", "app": "drive", "container_name": "drive-1",
             "container_id": "b" * 64, "ip": "10.0.0.6"}
UNIDENTIFIED = {"ok": False, "method": "none", "service": "", "app": "", "container_id": "",
                "container_name": "", "ip": "10.0.0.99", "reason": "no running container holds this address"}
SPOOF = {**UNIDENTIFIED, "method": "spoof-suspected", "container_id": "0" * 64,
         "reason": "claimed id does not own this address"}


def _client(declared=({"id": ROW}, {"id": PW["id"]})):
    app.VAULT_PATH = os.path.join(tempfile.mkdtemp(prefix="totpvault-"), "vault.enc")
    app.catalog = lambda: {ROW: dict(PROV), PW["id"]: dict(PW)}
    app.service_requires = lambda s: (list(declared) if s == SERVICE else [])
    return app.app.test_client()


@contextlib.contextmanager
def _as(ident, mode="warn"):
    """The request arrives from `ident` (what the docker socket says), in broker mode `mode`."""
    real_caller, real_mode = app.broker.caller, app.broker.MODE
    app.broker.caller, app.broker.MODE = (lambda: dict(ident)), mode
    try:
        yield
    finally:
        app.broker.caller, app.broker.MODE = real_caller, real_mode


def test_a_write_is_validated_and_stored_in_the_canonical_form():
    c = _client()
    r = c.post(f"/api/set/{ROW}", json={"value": "not a secret: 0189!"})   # 0/1/8/9 are outside base32
    assert r.status_code == 400 and "base32" in r.get_json()["error"], r.get_json()
    assert r.get_json()["field"] == FIELD and app.vault_read() == {}       # named, and nothing stored
    assert c.post(f"/api/set/{ROW}", json={"value": "jbsw y3dp ehpk 3pxp"}).status_code == 200
    assert app.vault_read()[ROW] == f"otpauth://totp/?secret={KEY}&digits=6&period=30&algorithm=SHA1"
    assert c.post(f"/api/set/{PW['id']}", json={"value": "a plain password"}).status_code == 200


def test_the_identified_declared_consumer_gets_a_code_and_never_the_secret():
    c = _client()
    c.post(f"/api/set/{ROW}", json={"value": KEY})
    with _as(RUNNER):
        r = c.get(f"/api/totp/{ROW}?service={SERVICE}")
    body = r.get_json()
    assert r.status_code == 200 and set(body) == {"id", "code", "next", "expires_in"}, body
    assert body["code"].isdigit() and len(body["code"]) == 6 and 1 <= body["expires_in"] <= 30
    assert KEY not in json.dumps(body)
    # The record is the grant log — not the vault's `_audit`, a whole-vault rewrite outside the lock.
    grant = app.broker.read_audit(1)[0]
    assert (grant["event"], grant["decision"], grant["service"], grant["connection"]) == \
        ("totp", "allow", SERVICE, ROW), grant
    assert body["code"] not in json.dumps(grant) and KEY not in json.dumps(grant)
    assert "totp" not in {e["event"] for e in app.vault_read().get("__audit__", [])}


def test_no_secret_is_a_404_that_names_the_field():
    c = _client()
    with _as(RUNNER):
        r = c.get(f"/api/totp/{ROW}?service={SERVICE}")
        assert r.status_code == 404 and r.get_json()["field"] == FIELD, r.get_json()
        assert c.get(f"/api/totp/{PW['id']}?service={SERVICE}").status_code == 404   # not a totp row


def test_the_mint_refuses_everyone_but_the_identified_declared_consumer_in_warn_mode():
    """The reviewer's three cases, in the live mode (`warn`, where a lease WOULD serve the
    unidentified): a different identified service, an unidentifiable caller, and a caller whose
    declaration does not name the row. A spoofed container id is the fourth."""
    c = _client()
    c.post(f"/api/set/{ROW}", json={"value": KEY})
    with _as(OTHER_APP):                                              # identified, as somebody else
        r = c.get(f"/api/totp/{ROW}?service={SERVICE}")
        assert r.status_code == 403 and r.get_json()["decision"] == "refuse", r.get_json()
    with _as(UNIDENTIFIED):                                           # warn serves this on a lease
        r = c.get(f"/api/totp/{ROW}?service={SERVICE}")
        assert r.status_code == 403 and "identified" in r.get_json()["error"], r.get_json()
    with _as(SPOOF):
        assert c.get(f"/api/totp/{ROW}?service={SERVICE}").status_code == 403
    with _as(UNIDENTIFIED, mode="off"):                               # not even the escape hatch
        assert c.get(f"/api/totp/{ROW}?service={SERVICE}").status_code == 403
    undeclared = _client(declared=({"id": PW["id"]},))                # the runner, row not declared
    undeclared.post(f"/api/set/{ROW}", json={"value": KEY})
    with _as(RUNNER):
        r = undeclared.get(f"/api/totp/{ROW}?service={SERVICE}")
        assert r.status_code == 403 and "declared" in r.get_json()["error"], r.get_json()
    assert c.get(f"/api/totp/{ROW}").status_code == 400               # loopback naming no service
    refusals = app.broker.read_audit(10, decision="refuse")
    assert len(refusals) >= 5 and all(KEY not in json.dumps(g) for g in refusals)


def test_the_secret_is_never_exported_to_a_consumer():
    c = _client()
    c.post(f"/api/set/{ROW}", json={"value": KEY})
    c.post(f"/api/set/{PW['id']}", json={"value": "pw"})
    env = app.export_env(SERVICE)
    assert PW["env"] in env and FIELD not in env, sorted(env)


def test_a_totp_secret_is_written_once_and_never_revealed_over_the_network():
    c = _client()
    c.post(f"/api/set/{ROW}", json={"value": KEY})
    with _as(RUNNER):                                                 # any network caller, even a good one
        r = c.post(f"/api/reveal/{ROW}", json={})
    assert r.status_code == 403 and KEY not in json.dumps(r.get_json()), r.get_json()
    assert app.broker.read_audit(1)[0]["event"] == "reveal"
    r = c.post(f"/api/reveal/{ROW}", json={})                         # loopback: the operator inside
    assert r.status_code == 200 and r.get_json()["revealed"] is True
    assert c.post(f"/api/reveal/{PW['id']}", json={}).status_code == 200   # other kinds unchanged
    row = app._row(ROW, dict(PROV), {}, {ROW: app.totp.canonical(KEY)})
    assert row["reveal_ok"] is False and row["secret"] is True and row["status"] == "healthy", row


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("  ok  ", t.__name__)
    print(f"totp route: {len(tests)}/{len(tests)} ok")
