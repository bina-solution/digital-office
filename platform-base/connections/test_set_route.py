"""test_set_route — `GET /api/is-set/<id>` answers set or not, and nothing else (DGO-1814).

    python3 platform-base/connections/test_set_route.py

A gate that runs before something leaves the office (the Drive agent's OpenAI nodes) asks the office whether its
key is set. n8n keeps every node's answer in the execution's record, so the answer carries no value and no mask of
one, and asking it runs no live probe (`/api/connections` probes every provider, some outside the office). What
holds: a value in the office's .env or vault → set; none, or a placeholder (`your-…`, `change_me`) → not set; an
unknown id → 404, not set; the reply's keys are exactly id, set, known, and no part of the value is in it; no probe
runs.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("CONN_DATA_DIR", tempfile.mkdtemp(prefix="setroute-"))
import app  # noqa: E402

KEY = "Zq9-value-THEREALVALUE-for-this-test"     # not shaped like any provider's key (G92 reads tracked files)
CAT = {"agent-openai": {"id": "agent-openai", "kind": "text-secret", "env": "AGENT_OPENAI_KEY", "probe": {"type": "present"}}}


def ask(cid, env_value, vault=None):
    real = (app.catalog, app.custom_catalog, app.vault_read, app.probe)
    probed = []
    app.catalog = lambda: CAT
    app.custom_catalog = lambda store: {}
    app.vault_read = lambda: dict(vault or {})
    app.probe = lambda *a, **k: probed.append(a) or ("ok", "")
    old = os.environ.pop("AGENT_OPENAI_KEY", None)
    if env_value is not None:
        os.environ["AGENT_OPENAI_KEY"] = env_value
    try:
        r = app.app.test_client().get(f"/api/is-set/{cid}")
        return r.status_code, r.get_json(), r.get_data(as_text=True), probed
    finally:
        app.catalog, app.custom_catalog, app.vault_read, app.probe = real
        os.environ.pop("AGENT_OPENAI_KEY", None)
        if old is not None:
            os.environ["AGENT_OPENAI_KEY"] = old


def test_a_value_in_the_env_is_set_and_no_part_of_it_is_said():
    status, body, raw, probed = ask("agent-openai", KEY)
    assert (status, body) == (200, {"id": "agent-openai", "set": True, "known": True}), body
    for part in (KEY, KEY[:3], KEY[-2:] + '"', "THEREAL"):
        assert part not in raw, part
    assert probed == [], "no live probe"


def test_a_value_in_the_vault_is_set():
    status, body, _, _ = ask("agent-openai", None, vault={"agent-openai": KEY})
    assert (status, body["set"]) == (200, True), body


def test_none_or_a_placeholder_is_not_set():
    for value in (None, "", "your-openai-key", "CHANGE_ME"):
        status, body, _, _ = ask("agent-openai", value)
        assert (status, body["set"]) == (200, False), (value, body)


def test_an_unknown_id_is_404_and_not_set():
    status, body, _, _ = ask("nobody-declared-this", KEY)
    assert (status, body) == (404, {"id": "nobody-declared-this", "set": False, "known": False}), body


def test_the_write_path_is_not_answered_by_a_read():
    # POST/DELETE /api/set/<id> write and clear a value; a GET there is not this question (405, not a boolean)
    assert app.app.test_client().get("/api/set/agent-openai").status_code == 405


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print(json.dumps({"passed": True}))
