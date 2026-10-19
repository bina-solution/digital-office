"""Unit tests for the condition machinery in app.py.

Conditions are the platform's answer to "what is actually wrong", and every consumer — the store
UI, `bbox`, and eventually an alerting rule — branches on `reason`. That makes the reason strings a
contract, not an implementation detail, so they get tested here rather than eyeballed on a running
stack. Every case below is one a live stack cannot be made to demonstrate on demand: an expired
OAuth grant, a docker socket that vanished, a deployment that never converged.

Run: python -m pytest platform-base/app-management/test_conditions.py -q
"""
import importlib.util
import pathlib
import sys
import time

import pytest

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    """Import app.py without its Flask app touching a real repo or docker socket."""
    spec = importlib.util.spec_from_file_location("appmgmt", HERE / "app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["appmgmt"] = mod
    spec.loader.exec_module(mod)
    return mod


app = _load()


def rt(running=1, total=1, health="healthy", present=1):
    return {"state": "running", "running": running, "total": total,
            "health": health, "present": present}


def by_type(conds):
    return {c["type"]: c for c in conds}


@pytest.fixture(autouse=True)
def _clean_transitions():
    """lastTransitionTime is process-global by design; tests must not inherit each other's clocks."""
    app._TRANSITIONS.clear()
    yield
    app._TRANSITIONS.clear()


# ── the happy path ────────────────────────────────────────────────────────────

def test_all_containers_running_and_healthy_is_ready():
    c = by_type(app._conditions("mail", rt(), "enabled", 7, set()))
    assert c["Ready"]["status"] == "True"
    assert c["Ready"]["reason"] == "AllChecksPassed"
    assert c["Started"]["status"] == "True"
    assert all(x["observedGeneration"] == 7 for x in c.values())


def test_every_condition_carries_the_full_contract():
    for cond in app._conditions("mail", rt(), "enabled", 1, set()):
        assert set(cond) == {"type", "status", "reason", "message",
                             "observedGeneration", "lastTransitionTime"}
        assert cond["status"] in ("True", "False", "Unknown")
        # `_since` is bookkeeping for the deadline check and must never reach a caller.
        assert "_since" not in cond


# ── the three-way failure taxonomy ────────────────────────────────────────────

def test_starting_is_not_ready_not_error():
    """A container still starting is the single most common not-Ready cause. Calling it an error
    would make the badge cry wolf on every single boot."""
    c = by_type(app._conditions("n8n", rt(health="starting"), "enabled", 1, set()))
    assert c["Ready"]["reason"] == app.COND_NOT_READY


def test_unhealthy_container_is_error():
    c = by_type(app._conditions("mail", rt(health="unhealthy"), "enabled", 1, set()))
    assert c["Ready"]["reason"] == app.COND_ERROR


def test_expired_grant_is_authfailed_not_error():
    """The distinction that justifies the taxonomy: this one a human can fix, and retrying cannot."""
    c = by_type(app._conditions("drive", rt(), "enabled", 1, set(), auth_missing=["Google Drive"]))
    assert c["Ready"]["reason"] == app.COND_AUTH_FAILED
    assert "Google Drive" in c["Ready"]["message"]


def test_auth_outranks_every_other_not_ready_reason():
    """A booting container with a dead token must report the token. Reporting 'starting' would send
    the operator away to wait for something that is never coming."""
    c = by_type(app._conditions("drive", rt(health="starting"), "enabled", 1,
                                {"mail (mail)"}, auth_missing=["Gmail"]))
    assert c["Ready"]["reason"] == app.COND_AUTH_FAILED


def test_unmet_dependency_is_notready_and_names_the_dependency():
    c = by_type(app._conditions("indox", rt(), "enabled", 1, {"sql (supabase)"}))
    assert c["Ready"]["reason"] == app.COND_NOT_READY
    assert "sql (supabase)" in c["Ready"]["message"]


# ── Unknown is a real status, not a synonym for False ─────────────────────────

def test_no_docker_view_reports_unknown_not_false():
    c = by_type(app._conditions("mail", {"running": None, "total": 2, "health": "unknown",
                                         "present": None}, "enabled", 1, set()))
    assert c["Started"]["status"] == "Unknown"
    assert c["Ready"]["status"] == "Unknown"
    assert c["Ready"]["reason"] == "DockerUnavailable"


# ── dispositions ──────────────────────────────────────────────────────────────

def test_archived_stays_installed():
    """Archiving removes the image, not the app. If Installed flipped to False the store would move
    the tile to the shop and the operator's data would look gone."""
    c = by_type(app._conditions("browser42", rt(running=0, present=0), "archived", 1, set()))
    assert c["Installed"]["status"] == "True"
    assert c["Ready"]["reason"] == "Archived"


def test_disabled_is_not_a_failure():
    c = by_type(app._conditions("portainer", rt(running=0, present=1), "disabled", 1, set()))
    assert c["Ready"]["reason"] == "Disabled"
    assert c["Installed"]["status"] == "True"


def test_never_installed_reports_notinstalled():
    c = by_type(app._conditions("ollama", rt(running=0, total=1, health="none", present=0),
                                "disabled", 1, set()))
    assert c["Installed"]["status"] == "False"
    assert c["Installed"]["reason"] == "NotInstalled"


# ── lastTransitionTime + progressDeadlineSeconds ──────────────────────────────

def test_transition_time_holds_while_status_is_unchanged():
    """The whole value of the field is knowing how long something has been stuck. Restamping it on
    every 5s poll would make everything look one tick old forever."""
    first = by_type(app._conditions("mail", rt(), "enabled", 1, set()))["Ready"]
    time.sleep(1.05)                       # the stamp has 1s resolution
    second = by_type(app._conditions("mail", rt(), "enabled", 1, set()))["Ready"]
    assert first["lastTransitionTime"] == second["lastTransitionTime"]


def test_transition_time_moves_when_status_changes():
    by_type(app._conditions("mail", rt(), "enabled", 1, set()))
    time.sleep(1.05)
    after = by_type(app._conditions("mail", rt(health="unhealthy"), "enabled", 1, set()))["Ready"]
    assert after["lastTransitionTime"] != app._TRANSITIONS[("mail", "Started")][1]
    assert after["status"] == "False"


def test_stale_notready_becomes_progress_deadline_exceeded():
    """A deployment that never converges must stop looking like progress."""
    app._conditions("n8n", rt(health="starting"), "enabled", 1, set(), deadline=60)
    # Rewind the recorded transition so the condition has 'been' starting for 10 minutes.
    key = ("n8n", "Ready")
    status, iso, mono = app._TRANSITIONS[key]
    app._TRANSITIONS[key] = (status, iso, mono - 600)
    c = by_type(app._conditions("n8n", rt(health="starting"), "enabled", 1, set(), deadline=60))
    assert c["Ready"]["reason"] == "ProgressDeadlineExceeded"


def test_deadline_does_not_touch_a_healthy_or_authfailed_app():
    """Only NotReady is time-limited. AuthFailed is already terminal, and re-labelling it after ten
    minutes would lose the one piece of actionable information on the card."""
    for kw in ({}, {"auth_missing": ["Gmail"]}):
        aid = "x" + str(len(kw))
        app._conditions(aid, rt(), "enabled", 1, set(), deadline=1, **kw)
        key = (aid, "Ready")
        st, iso, mono = app._TRANSITIONS[key]
        app._TRANSITIONS[key] = (st, iso, mono - 600)
        c = by_type(app._conditions(aid, rt(), "enabled", 1, set(), deadline=1, **kw))
        assert c["Ready"]["reason"] != "ProgressDeadlineExceeded"


# ── the auth probe must never take the catalog down with it ───────────────────

def test_auth_blockers_survive_a_dead_connections_service(monkeypatch):
    """connections being down is ITS failure, shown on ITS card. If it also turned every other app
    AuthFailed, one service outage would paint the whole platform red and mean nothing."""
    monkeypatch.setattr(app, "_AUTH_CACHE", {"at": 0.0, "by_service": {}})
    monkeypatch.setattr(app, "CONNECTIONS_URL", "http://127.0.0.1:9")   # discard port
    assert app._auth_blockers() == {}


def test_optional_unset_credentials_are_not_auth_failures(monkeypatch):
    """An optional connection left unset is a choice. Badging it would train the operator to ignore
    the badge, which costs more than the warning is worth."""
    rows = {"connections": [
        {"id": "opt", "required": False, "status": "missing", "title": "Optional",
         "consumers": ["mail"]},
        {"id": "req", "required": True, "status": "needs_action", "title": "Gmail",
         "consumers": ["mail"]},
        {"id": "fine", "required": True, "status": "ok", "title": "Fine", "consumers": ["mail"]},
    ]}

    class _R:
        status = 200
        def read(self):
            import json
            return json.dumps(rows).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(app, "_AUTH_CACHE", {"at": 0.0, "by_service": {}})
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _R())
    assert app._auth_blockers() == {"mail": ["Gmail"]}


# ── two defects the live stack found in this logic ────────────────────────────

def test_a_finished_one_shot_job_counts_as_satisfied():
    """glitchtip ran 4/5 forever: its `glitchtip-migrate` job runs once, exits 0 and stays exited by
    design. Counting only status=="running" made the app permanently NotReady and gave the operator
    a never-clearing amber dot with nothing to fix."""
    cidx = {
        "glitchtip":         {"status": "running", "health": "healthy", "exit_code": 0, "restart": "unless-stopped"},
        "glitchtip-migrate": {"status": "exited",  "health": None,      "exit_code": 0, "restart": "no"},
    }
    rt = app._app_runtime(["glitchtip", "glitchtip-migrate"], cidx)
    assert (rt["running"], rt["total"]) == (2, 2)
    assert by_type(app._conditions("glitchtip", rt, "enabled", 1, set()))["Ready"]["status"] == "True"


def test_a_crashed_one_shot_is_still_a_failure():
    """The exit code is the whole distinction — a job that ended badly must not read as success."""
    cidx = {"job": {"status": "exited", "health": None, "exit_code": 1, "restart": "no"}}
    rt = app._app_runtime(["job"], cidx)
    assert rt["running"] == 0


def test_a_stopped_service_is_not_mistaken_for_a_finished_job():
    """`restart: unless-stopped` says the author meant it to keep running, so exit 0 is a service
    that died quietly, not a job that completed."""
    cidx = {"svc": {"status": "exited", "health": None, "exit_code": 0, "restart": "unless-stopped"}}
    assert app._app_runtime(["svc"], cidx)["running"] == 0


def test_an_app_with_no_containers_is_ready_when_enabled():
    """bina-ui reported NotReady "0/0 running" permanently. An app that owns no compose (kind: ui or
    blueprint) has nothing that can be down — its installation IS its content."""
    rt = app._app_runtime([], {})
    c = by_type(app._conditions("bina-ui", rt, "enabled", 1, set()))
    assert c["Ready"]["status"] == "True"
    assert c["Ready"]["reason"] == "NoServicesToRun"


# ── launch URL: the public origin an "open" tile sends the browser to ────────────────────────────
def _env(monkeypatch, values):
    monkeypatch.setattr(app, "_repo_env", lambda name, _depth=0: values.get(name, ""))


def test_launch_uses_the_app_base_url_convention_when_the_entry_declares_none(monkeypatch):
    # n8n: auth none, no sso.base_url_env — the same N8N_BASE_URL traefik routes must win over the
    # `.localhost` guess, port included (the macOS engine's edge is :8080).
    _env(monkeypatch, {"N8N_BASE_URL": "n8n.localhost:8080", "DEPLOYMENT_DOMAIN": "localhost"})
    assert app._public_origin("n8n", "n8n", None) == "http://n8n.localhost:8080"


def test_a_localhost_twin_with_a_port_is_still_http(monkeypatch):
    _env(monkeypatch, {"REDISINSIGHT_BASE_URL": "redisinsight.localhost:8080"})
    assert app._public_origin("redisinsight", "redisinsight", "REDISINSIGHT_BASE_URL") == \
        "http://redisinsight.localhost:8080"


def test_a_real_domain_is_https(monkeypatch):
    _env(monkeypatch, {"N8N_BASE_URL": "n8n.hacohen.digital-office.co.il"})
    assert app._public_origin("n8n", "n8n", None) == "https://n8n.hacohen.digital-office.co.il"


def test_the_entry_own_env_wins_over_the_convention(monkeypatch):
    _env(monkeypatch, {"MY_DOCS_BASE_URL": "my-docs.localhost:8080", "DOCS_BASE_URL": "docs.example.com"})
    assert app._public_origin("my-docs", "my-docs", "DOCS_BASE_URL") == "https://docs.example.com"


def test_no_env_at_all_falls_back_to_the_deployment_domain(monkeypatch):
    _env(monkeypatch, {"DEPLOYMENT_DOMAIN": "hacohen.digital-office.co.il"})
    assert app._public_origin("glitchtip", "glitchtip", None) == "https://glitchtip.hacohen.digital-office.co.il"
    _env(monkeypatch, {})
    assert app._public_origin("glitchtip", "glitchtip", None) == "http://glitchtip.localhost"


# ── what a linked office stopped giving ──────────────────────────────────────────────────────
def test_a_tile_whose_office_stopped_giving_the_app_is_withdrawn_and_a_silent_office_keeps_its_tiles():
    """Declaring the block writes the state file; the compile is what takes a tile away — and it is
    asked for from what is COMPILED, not from what changed. An office that did not answer is not in
    the block at all: its tiles are unconfirmed, not withdrawn."""
    tiles = [{"id": "drive"},                                                   # an app of this office
             {"id": "drive.macbook", "remote": {"office": "macbook", "alias": "drive"}},
             {"id": "browser42.macbook", "remote": {"office": "macbook", "alias": "browser42"}},
             {"id": "notes.vps1", "remote": {"office": "vps1", "alias": "notes"}}]
    block = [{"office": "macbook", "apps": [{"alias": "drive"}]}]               # vps1 did not answer

    assert app.withdrawn_tiles(block, tiles) == ["browser42.macbook"]
    assert app.withdrawn_tiles([], tiles) == []                                 # nobody answered: nothing is judged
    assert app.withdrawn_tiles(block + [{"office": "vps1", "apps": []}], tiles) == ["browser42.macbook", "notes.vps1"]
    assert app.withdrawn_tiles(block, [{"id": "drive.macbook", "remote": {"office": "macbook", "alias": "drive"}}]) == []
