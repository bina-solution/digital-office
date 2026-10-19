"""Unit tests for the bring-up: what "enable" does, in what order, and how a caller follows it.

Enabling an app from this plane has to leave it USABLE, because this API is the only hand on a
machine nobody types on — the apps screen, and a linked office placing an app here over the link.
So the order is a contract (prepare -> containers -> answer -> onboard -> automations), and so is
the way a long one is followed (202 + `/job`). Neither can be shown on demand on a running stack:
an app that never becomes healthy, a second click during a ten-minute build.

Run: python -m pytest platform-base/app-management/test_bringup.py -q
"""
import importlib.util
import os
import pathlib
import sys
import threading

import pytest

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    """Import app.py without its Flask app touching a real repo or docker socket."""
    spec = importlib.util.spec_from_file_location("appmgmt_bringup", HERE / "app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["appmgmt_bringup"] = mod
    spec.loader.exec_module(mod)
    return mod


app = _load()
APP = {"id": "notes", "_root": "apps", "_dir": "/nowhere", "progress_deadline_seconds": 77}


@pytest.fixture
def plane(monkeypatch):
    """The plane with every effect replaced by a recorder; `calls` is what it did, in order."""
    calls = []
    monkeypatch.setattr(app, "_JOBS", {})
    monkeypatch.setattr(app, "docker_sdk", object())
    monkeypatch.setattr(app, "_manifest", lambda aid: dict(APP, id=aid))
    monkeypatch.setattr(app, "_services_of", lambda m: ["notes"])
    monkeypatch.setattr(app, "_set_disposition", lambda aid, d: calls.append(f"state:{d}") or True)
    monkeypatch.setattr(app, "_render", lambda: calls.append("render"))
    monkeypatch.setattr(app, "_app_containers", lambda services: [])
    monkeypatch.setattr(app, "_install", lambda aid: (calls.append("create") or ["notes"], []))
    monkeypatch.setattr(app, "_wait_ready", lambda services, s: calls.append(f"answer:{s}") or True)
    monkeypatch.setattr(app, "_run_hook",
                        lambda m, verb, t: calls.append(f"hook:{verb}") or {"ran": True, "rc": 0, "out": ""})
    monkeypatch.setattr(app, "_blueprint_apply", lambda aid, on: calls.append("automations"))
    monkeypatch.setattr(app, "_container_index", lambda: {})
    monkeypatch.setattr(app, "_held_volumes", lambda m: [])
    monkeypatch.setattr(app, "_required_by", lambda aid: [])        # nobody needs it, unless a test says so
    monkeypatch.setattr(app, "_closure_services", lambda aid: [])   # no providers pulled in, unless a test says so
    # the compiler's own parser is not importable from a bare copy of this file; its rule is tested there
    monkeypatch.setattr(app, "_disposition", lambda entry: (entry or {}).get("state", "disabled"))
    monkeypatch.setattr(app, "_signin_refresh", lambda: calls.append("signin") or {"ran": True, "rc": 0, "out": ""})
    monkeypatch.setattr(app, "_carry_in",
                        lambda aid, src: calls.append(f"data:{src['office']}/{src['archive']}"))
    return calls


def test_enabling_an_app_is_its_whole_bring_up_in_the_order_bbox_run_gives_it(plane):
    steps = []
    payload, code = app._apply("notes", APP, True, steps.append)
    assert plane == ["state:enabled", "render", "hook:prepare", "create", "answer:77",
                     "hook:onboard", "automations"]
    assert steps == ["state", "prepare", "containers", "health", "onboard", "automations"]
    assert code == 200 and payload["ok"] and payload["created"] == ["notes"]
    assert set(payload["hooks"]) == {"prepare", "onboard"}


def test_an_app_that_never_answers_is_not_onboarded_and_the_change_fails_saying_so(plane, monkeypatch):
    monkeypatch.setattr(app, "_wait_ready", lambda services, s: False)
    payload, code = app._apply("notes", APP, True)
    assert "hook:onboard" not in plane
    assert code == 500 and not payload["ok"]
    assert "77s" in payload["create_errors"][0]        # the app's OWN allowance, named


def test_containers_that_could_not_be_created_are_not_waited_for(plane, monkeypatch):
    monkeypatch.setattr(app, "_install", lambda aid: ([], ["compose up failed (1): boom"]))
    payload, code = app._apply("notes", APP, True)
    assert not any(c.startswith("answer") or c == "hook:onboard" for c in plane)
    assert code == 500 and payload["create_errors"] == ["compose up failed (1): boom"]


def test_switching_an_app_off_runs_none_of_its_bring_up(plane):
    payload, code = app._apply("notes", APP, False)
    assert plane == ["state:disabled", "render", "automations"]
    assert code == 200 and payload["enabled"] is False and payload["hooks"] == {}


def test_a_change_that_cannot_get_its_turn_is_refused_and_writes_nothing(plane):
    with app._LIFECYCLE:
        payload, code = app._apply("notes", APP, False, patience=0.05)
    assert code == 409 and plane == []


def _held(monkeypatch):
    """Make the bring-up wait for the test: returns (release, how many started)."""
    go, started = threading.Event(), []

    def slow(aid, m, enable, step=lambda _n: None, patience=-1, restore=None):
        if not enable:
            return {"ok": True, "id": aid, "enabled": False}, 200
        started.append(aid)
        step("containers")
        go.wait(10)
        return {"ok": True, "id": aid, "enabled": True}, 200

    monkeypatch.setattr(app, "_apply", slow)
    monkeypatch.setattr(app, "BRINGUP_WAIT_S", 0.2)
    return go, started


def test_a_long_bring_up_answers_202_and_the_job_route_answers_what_the_call_would_have(plane, monkeypatch):
    go, _ = _held(monkeypatch)
    web = app.app.test_client()
    first = web.post("/api/apps/notes/enable")
    assert first.status_code == 202
    assert first.get_json()["state"] == "running" and first.get_json()["step"] == "containers"
    assert web.get("/api/apps/notes/job").status_code == 202
    go.set()
    app._JOBS["notes"]["finished"].wait(5)
    done = web.get("/api/apps/notes/job")
    assert done.status_code == 200 and done.get_json() == {"ok": True, "id": "notes", "enabled": True}


def test_a_short_bring_up_answers_in_the_call_itself(plane):
    r = app.app.test_client().post("/api/apps/notes/enable")
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert plane[0] == "state:enabled" and plane[-1] == "automations"


def test_a_second_enable_joins_the_one_in_flight_and_nothing_may_undo_it_meanwhile(plane, monkeypatch):
    go, started = _held(monkeypatch)
    web = app.app.test_client()
    assert web.post("/api/apps/notes/enable").status_code == 202
    assert web.post("/api/apps/notes/enable").status_code == 202
    assert started == ["notes"]                         # one bring-up, not two
    for verb in ("disable", "archive", "uninstall"):
        r = web.post(f"/api/apps/notes/{verb}")
        assert r.status_code == 409 and r.get_json()["step"] == "containers", verb
    go.set()
    app._JOBS["notes"]["finished"].wait(5)
    assert web.post("/api/apps/notes/disable").status_code == 200


def test_a_bring_up_that_breaks_ends_as_a_failed_job_never_as_one_that_runs_forever(plane, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("compose vanished")

    monkeypatch.setattr(app, "_apply", broken)
    r = app.app.test_client().post("/api/apps/notes/enable")
    assert r.status_code == 500 and "compose vanished" in r.get_json()["error"]
    assert app._JOBS["notes"]["finished"].is_set()


def test_an_app_nobody_brought_up_has_no_job_and_a_core_app_is_never_touched(plane, monkeypatch):
    web = app.app.test_client()
    assert web.get("/api/apps/notes/job").status_code == 404
    monkeypatch.setattr(app, "_manifest", lambda aid: dict(APP, id=aid, _root="platform-base"))
    assert web.post("/api/apps/traefik/enable").status_code == 403
    assert plane == [] and "traefik" not in app._JOBS


@pytest.mark.skipif(os.name == "nt", reason="the exec bit is a POSIX fact")
def test_a_hook_runs_only_when_it_is_executable_the_rule_bbox_run_has(tmp_path, monkeypatch):
    # a hook runs from the checkout — which is /repo only inside this plane's own container
    monkeypatch.setattr(app, "REPO", str(tmp_path))
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "onboard").write_text("#!/usr/bin/env bash\necho \"brought up $APP_ID\"\n")
    (hooks / "onboard").chmod(0o755)
    (hooks / "prepare").write_text("#!/usr/bin/env bash\nexit 3\n")
    (hooks / "prepare").chmod(0o644)
    m = {"id": "notes", "_dir": str(tmp_path)}
    # present, not executable: not run — and SAID, because "the app ships no such hook" is another fact
    assert app._run_hook(m, "prepare", 10) == {
        "ran": False, "rc": 126, "out": "hooks/prepare is there and is not executable — not run"}
    assert app._run_hook(m, "verify", 10) is None       # absent
    assert app._run_hook(m, "onboard", 10) == {"ran": True, "rc": 0, "out": "brought up notes"}


# ── arriving with data, and moving ────────────────────────────────────────────

def test_arriving_with_data_restores_between_the_first_answer_and_the_apps_own_bootstrap(plane):
    steps = []
    payload, code = app._apply("notes", APP, True, steps.append,
                               restore={"office": "macbook", "archive": "mac-1-notes"})
    assert plane == ["state:enabled", "render", "hook:prepare", "create", "answer:77",
                     "data:macbook/mac-1-notes", "answer:77", "hook:onboard", "automations"]
    assert steps == ["state", "prepare", "containers", "health", "restore", "onboard", "automations"]
    assert code == 200 and payload["restored"] == {"office": "macbook", "archive": "mac-1-notes"}


def test_data_that_did_not_arrive_whole_fails_the_bring_up_before_any_bootstrap(plane, monkeypatch):
    monkeypatch.setattr(app, "_carry_in", lambda aid, src: "plane_work_items: 40 -> 0")
    payload, code = app._apply("notes", APP, True, restore={"office": "macbook", "archive": "a"})
    assert "hook:onboard" not in plane and code == 500
    assert payload["create_errors"] == ["plane_work_items: 40 -> 0"] and payload["restored"] is None


def test_an_office_that_holds_the_apps_data_is_never_overwritten_by_an_arrival(plane, monkeypatch):
    monkeypatch.setattr(app, "_held_volumes", lambda m: ["notes_db"])
    r = app.app.test_client().post("/api/apps/notes/enable", json={"restore": {"archive": "a", "office": "macbook"}})
    assert r.status_code == 409 and r.get_json()["volumes"] == ["notes_db"]
    assert plane == [] and "notes" not in app._JOBS
    # ...while a plain switch-on of the same app, on its own data, is untouched by that rule
    assert app.app.test_client().post("/api/apps/notes/enable").status_code == 200


def test_the_office_data_is_fetched_from_is_the_one_the_link_names_not_the_one_the_body_claims(plane):
    web = app.app.test_client()
    r = web.post("/api/apps/notes/enable", json={"restore": {"archive": "a1", "office": "some-third-office"}},
                 headers={"X-DGO-Office": "macbook"})
    assert r.status_code == 200 and "data:macbook/a1" in plane
    for bad in ({"archive": "../etc", "office": "macbook"}, {"archive": "a1", "office": "Not An Office"},
                {"archive": "a1"}, "a1"):
        assert web.post("/api/apps/notes/enable", json={"restore": bad}).status_code == 400, bad


@pytest.fixture
def linked(plane, monkeypatch):
    """A linked office and this office's data plane, as recorders. `far` is what that office answers."""
    far = {"apps": [{"id": "notes", "installed": False, "enabled": False}], "enable": (200, {"ok": True})}

    def call(method, url, body=None, timeout=60):
        plane.append(f"{method} {url.split('/a/')[-1]}" + (f" {body}" if body else ""))
        if url.endswith("/api/apps"):
            return 200, {"apps": far["apps"]}
        return far["enable"]

    def data_job(verb, **query):
        plane.append(f"data-job:{verb}:{query.get('app')}")
        return True, {"out": "/var/backups/bbox/hp-20261005-notes", "log": ["DONE"]}

    monkeypatch.setattr(app, "_call", call)
    monkeypatch.setattr(app, "_data_job", data_job)
    monkeypatch.setattr(app, "_app_runtime",
                        lambda services, cidx, enabled=True: {"state": "running", "running": 1, "total": 1,
                                                              "health": "healthy", "present": 1})
    return far


def test_a_move_exports_here_brings_it_up_there_and_only_then_switches_it_off_here(plane, linked):
    r = app.app.test_client().post("/api/apps/notes/move", json={"to": "macbook"})
    d = r.get_json()
    assert r.status_code == 200 and d["moved_to"] == "macbook" and d["archive"] == "hp-20261005-notes"
    assert plane == ["GET app-management.macbook/api/apps", "GET app-management.macbook/api/apps/notes/room",
                     "data-job:export:notes",
                     "POST app-management.macbook/api/apps/notes/enable {'restore': {'archive': 'hp-20261005-notes'}}",
                     "state:disabled", "render", "automations"]


def test_a_move_the_other_office_could_not_finish_leaves_the_app_running_here(plane, linked):
    linked["enable"] = (500, {"ok": False, "create_errors": ["plane_work_items: 40 -> 0"]})
    r = app.app.test_client().post("/api/apps/notes/move", json={"to": "macbook"})
    assert r.status_code == 502 and "plane_work_items: 40 -> 0" in r.get_json()["error"]
    assert not any(c.startswith("state:") for c in plane)      # nothing was switched off here


def test_a_move_is_refused_before_anything_is_exported_when_it_cannot_end_well(plane, linked, monkeypatch):
    web = app.app.test_client()
    assert web.post("/api/apps/notes/move", json={}).status_code == 400
    linked["apps"][0]["installed"] = True
    assert web.post("/api/apps/notes/move", json={"to": "macbook"}).status_code == 409   # already there
    linked["apps"].clear()
    assert web.post("/api/apps/notes/move", json={"to": "macbook"}).status_code == 409   # not in its catalog
    # …and with that office ready to take it, the app still has to be RUNNING here to be read
    linked["apps"].append({"id": "notes", "installed": False, "enabled": False})
    monkeypatch.setattr(app, "_app_runtime", lambda *a, **k: {"state": "stopped", "running": 0, "total": 1,
                                                               "health": "none", "present": 1})
    r = web.post("/api/apps/notes/move", json={"to": "macbook"})
    assert r.status_code == 409 and "not running here" in r.get_json()["error"]
    assert not any(c.startswith("data-job") or c.startswith("state:") for c in plane)


# ── sign-in, apply, and the remote block ──────────────────────────────────────

def test_sign_in_is_refreshed_for_an_app_that_gates_a_host_before_its_own_bootstrap(plane):
    gated = dict(APP, routing=[{"host": "notes", "port": 80, "auth": "sso"}])
    steps = []
    payload, code = app._apply("notes", gated, True, steps.append)
    assert plane[-3:] == ["signin", "hook:onboard", "automations"] and "signin" in steps
    assert code == 200 and "signin" in payload["hooks"]
    plane.clear()
    app._apply("notes", dict(APP, routing=[{"host": "notes", "port": 80, "auth": "none"}]), True)
    assert "signin" not in plane                        # nothing gated, nothing to refresh


def test_apply_recompiles_then_lets_compose_recreate_what_changed_then_refreshes_sign_in(plane, monkeypatch):
    monkeypatch.setattr(app, "_load_state", lambda: {"notes": {"state": "enabled"}})
    monkeypatch.setattr(app, "_compose_up", lambda services: plane.append(f"up:{','.join(services)}"))
    r = app.app.test_client().post("/api/apps/notes/apply")
    assert r.status_code == 200 and r.get_json()["applied"] == ["notes"]
    assert plane == ["render", "up:notes", "signin"]


def test_apply_touches_nothing_of_an_app_that_is_switched_off_or_of_the_platform(plane, monkeypatch):
    web = app.app.test_client()
    monkeypatch.setattr(app, "_load_state", lambda: {"notes": {"state": "disabled"}})
    assert web.post("/api/apps/notes/apply").status_code == 409
    monkeypatch.setattr(app, "_manifest", lambda aid: dict(APP, id=aid, _root="platform-base"))
    assert web.post("/api/apps/traefik/apply").status_code == 403
    assert plane == []


@pytest.fixture
def compiler(plane, monkeypatch):
    """The compiler's two remote verbs, as a recorder. `answer` is what the next call returns."""
    box = {"answer": (0, "[]", "")}

    def run(*args, stdin=None):
        plane.append(("compiler", args, stdin))
        return box["answer"]

    monkeypatch.setattr(app, "_compiler", run)
    return box


def test_the_remote_block_is_read_from_and_written_through_the_compiler(plane, compiler):
    web = app.app.test_client()
    compiler["answer"] = (0, '[{"office": "macbook", "apps": []}]', "")
    assert web.get("/api/remote").get_json() == {"remote": [{"office": "macbook", "apps": []}]}
    compiler["answer"] = (0, '{"written": true, "apps": 2, "offices": 1}', "")
    block = [{"office": "macbook", "apps": [{"alias": "drive"}, {"alias": "bina"}]}]
    r = web.put("/api/remote", json={"remote": block})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "written": True, "apps": 2, "offices": 1,
                                                    "withdrawn": []}
    verb, args, stdin = plane[-1]
    assert args == ("remote-set", "--json") and app.json.loads(stdin) == block     # the block, whole
    assert "render" not in plane                     # nothing compiled is undeclared: no compile


def test_declaring_the_block_compiles_away_a_tile_its_office_stopped_giving(plane, compiler, monkeypatch):
    """The state file is what is declared; the tile and its route are what is compiled. An app that
    was only WITHDRAWN left its tile standing until somebody ran a bring-up (two of the MacBook's, for
    days). The route compiles when — and only when — the compiled registry shows such a tile."""
    web = app.app.test_client()
    compiler["answer"] = (0, '{"written": false, "apps": 1, "offices": 1}', "")
    block = [{"office": "macbook", "apps": [{"alias": "drive"}]}]
    compiled = [{"id": "drive"}, {"id": "drive.macbook", "remote": {"office": "macbook", "alias": "drive"}},
                {"id": "browser42.macbook", "remote": {"office": "macbook", "alias": "browser42"}},
                {"id": "notes.vps1", "remote": {"office": "vps1", "alias": "notes"}}]   # vps1 did not answer
    monkeypatch.setattr(app, "_compiled_tiles", lambda: compiled)
    r = web.put("/api/remote", json={"remote": block})
    assert r.status_code == 200 and r.get_json()["withdrawn"] == ["browser42.macbook"]
    assert plane[-1] == "render"                     # compiled once, after the write, written or not

    del plane[:]
    monkeypatch.setattr(app, "_compiled_tiles", lambda: compiled[:2] + compiled[3:])
    assert web.put("/api/remote", json={"remote": block}).get_json()["withdrawn"] == []
    assert "render" not in plane                     # a silent office's tile is not withdrawn

    def broken():
        raise RuntimeError("SERVE PLAN REFUSED")
    monkeypatch.setattr(app, "_compiled_tiles", lambda: compiled)
    monkeypatch.setattr(app, "_render", broken)
    said = web.put("/api/remote", json={"remote": block}).get_json()
    assert said["ok"] and said["compile_error"] == "SERVE PLAN REFUSED"   # the write stands; the compile is said


def test_a_block_the_compiler_refuses_is_answered_with_its_reasons_and_writes_nothing(plane, compiler):
    compiler["answer"] = (1, "", "  - remote[0].office 'MAC BOOK' is not an office id\n  - remote[0].apps must be a list")
    r = app.app.test_client().put("/api/remote", json={"remote": [{"office": "MAC BOOK"}]})
    assert r.status_code == 422
    assert r.get_json()["refused"] == ["remote[0].office 'MAC BOOK' is not an office id", "remote[0].apps must be a list"]


def test_only_this_offices_own_link_plane_may_write_the_remote_block(plane, compiler):
    web = app.app.test_client()
    r = web.put("/api/remote", json={"remote": []}, headers={"X-DGO-Office": "macbook"})
    assert r.status_code == 403 and plane == []          # a linked office: refused before the compiler
    for bad in ({}, {"remote": "macbook"}, [], None):
        assert web.put("/api/remote", json=bad).status_code == 400
    assert plane == []


def test_a_change_whose_state_could_not_be_written_does_nothing_else(plane, monkeypatch):
    monkeypatch.setattr(app, "_set_disposition", lambda aid, d: False)
    payload, code = app._apply("notes", APP, True)
    assert code == 500 and "desired state" in payload["error"]
    assert plane == []                                  # no compile, no hook, no container


# ── moving an app that is switched off here ────────────────────────────────────

def _asleep(monkeypatch):
    monkeypatch.setattr(app, "_app_runtime", lambda *a, **k: {"state": "stopped", "running": 0, "total": 1,
                                                               "health": "none", "present": 1})


def test_a_switched_off_app_is_switched_on_for_the_read_only_when_the_move_asks(plane, linked, monkeypatch):
    _asleep(monkeypatch)
    web = app.app.test_client()
    refused = web.post("/api/apps/notes/move", json={"to": "macbook"})
    assert refused.status_code == 409 and '"wake": true' in refused.get_json()["error"]
    assert not any(c.startswith(("state:", "data-job")) for c in plane)          # nothing was started
    for not_a_yes in ("true", 1, "yes"):                                          # only the JSON `true`
        assert web.post("/api/apps/notes/move", json={"to": "macbook", "wake": not_a_yes}).status_code == 409
    plane.clear()
    r = web.post("/api/apps/notes/move", json={"to": "macbook", "wake": True})
    assert r.status_code == 200 and r.get_json()["moved_to"] == "macbook"
    assert plane == ["GET app-management.macbook/api/apps", "GET app-management.macbook/api/apps/notes/room",
                     "state:enabled", "render", "hook:prepare", "create", "answer:77", "hook:onboard", "automations",
                     "data-job:export:notes",
                     "POST app-management.macbook/api/apps/notes/enable {'restore': {'archive': 'hp-20261005-notes'}}",
                     "state:disabled", "render", "automations"]


def test_a_woken_app_is_switched_off_again_when_the_move_fails(plane, linked, monkeypatch):
    _asleep(monkeypatch)
    linked["enable"] = (500, {"ok": False, "create_errors": ["no room"]})
    r = app.app.test_client().post("/api/apps/notes/move", json={"to": "macbook", "wake": True})
    d = r.get_json()
    assert r.status_code == 502 and "no room" in d["error"] and "switched off again" in d["error"]
    assert [c for c in plane if c.startswith("state:")] == ["state:enabled", "state:disabled"]


def test_an_app_that_was_running_is_not_touched_by_a_failed_move_even_when_wake_was_asked(plane, linked):
    linked["enable"] = (500, {"ok": False, "create_errors": ["no room"]})
    r = app.app.test_client().post("/api/apps/notes/move", json={"to": "macbook", "wake": True})
    assert r.status_code == 502 and "switched off again" not in r.get_json()["error"]
    assert not any(c.startswith("state:") for c in plane)


def test_an_app_that_cannot_be_switched_on_for_the_read_is_left_off_and_nothing_is_exported(plane, linked, monkeypatch):
    _asleep(monkeypatch)
    monkeypatch.setattr(app, "_install", lambda aid: ([], ["compose up failed (1): boom"]))
    r = app.app.test_client().post("/api/apps/notes/move", json={"to": "macbook", "wake": True})
    assert r.status_code == 500 and "could not be switched on here" in r.get_json()["error"]
    assert not any(c.startswith("data-job") or c.startswith("POST") for c in plane)
    assert [c for c in plane if c.startswith("state:")] == ["state:enabled", "state:disabled"]


# ── what a hook is reported to have said ───────────────────────────────────────

class _Ran:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_a_failed_hook_is_reported_by_its_reason_not_by_how_far_it_got():
    """drive's automations on hp-laptop, 2026-10-05: the converge said the error was the last thing
    that had WORKED, because the reason was on the other stream."""
    r = _Ran(1, "[n8n-push] Container: n8n-hp\n[n8n-push] PostgREST default privileges present\n",
             "[n8n-push] ====\n"
             "[n8n-push] FATAL: N8N_ENCRYPTION_KEY does not match the blueprint, and this instance already holds\n"
             "           24 credential(s) encrypted under a different key.\n\n  Fix: set N8N_ENCRYPTION_KEY in .env\n")
    assert app._hook_said(r) == ("[n8n-push] FATAL: N8N_ENCRYPTION_KEY does not match the blueprint, and this "
                                 "instance already holds 24 credential(s) encrypted under a different key.")
    # no FATAL and no ERROR: the last word on stderr
    assert app._hook_said(_Ran(1, "step one\n", "it broke\n[x] next thing\n")) == "[x] next thing"
    # nothing on stderr at all: the last word there is
    assert app._hook_said(_Ran(1, "[x] trying\n[x] gave up\n", "")) == "[x] gave up"
    assert app._hook_said(_Ran(3)) == "exit 3"
    # a hook that worked is where it got to, whatever it grumbled on the way
    assert app._hook_said(_Ran(0, "imported 4 workflow(s)\n", "a warning nobody asked about\n")) == "imported 4 workflow(s)"


# ── room: does this office have space for an app ───────────────────────────────

GIB = 1024 ** 3
ROOMY = {"ncpu": 8, "load": 0.5, "memory": {"total": 16 * GIB, "available": 8 * GIB}, "disk": {"available": 200 * GIB}}
TIGHT = {"ncpu": 8, "load": 0.5, "memory": {"total": 8 * GIB, "available": 1 * GIB}, "disk": {"available": 200 * GIB}}


def test_an_office_answers_for_its_own_room_in_numbers(plane, monkeypatch):
    web = app.app.test_client()
    monkeypatch.setattr(app, "_manifest", lambda aid: dict(APP, id=aid, resources={"memory": "2G", "cpus": "1"}))
    monkeypatch.setattr(app, "_machine_here", lambda: ROOMY)
    fits = web.get("/api/apps/notes/room").get_json()
    assert fits["ok"] and fits["need"]["memory_mb"] == 2048 and fits["have"]["memory_available_mb"] == 8192
    monkeypatch.setattr(app, "_machine_here", lambda: TIGHT)
    full = web.get("/api/apps/notes/room").get_json()
    assert not full["ok"] and [p["code"] for p in full["problems"]] == ["memory"]
    assert "2.4GB" in full["summary"] and "1.0GB" in full["summary"]          # what it asked, what there is
    # a machine that could not be read is a refusal that says so, never an approval
    monkeypatch.setattr(app, "_machine_here", lambda: {})
    assert web.get("/api/apps/notes/room").get_json()["problems"][0]["code"] == "unreachable"
    monkeypatch.setattr(app, "_manifest", lambda aid: None)
    assert web.get("/api/apps/nothing/room").status_code == 404


def test_what_an_app_asks_for_is_its_own_word_and_an_app_that_says_nothing_is_not_called_small(plane, monkeypatch, tmp_path):
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n"
        "  web: {deploy: {resources: {limits: {memory: 512M, cpus: '0.5'}}}}\n"
        "  db:  {deploy: {resources: {limits: {memory: 1G}}}}\n"
        "  job: {image: x}\n", encoding="utf-8")
    here = {"_dir": str(tmp_path), "compose": "docker-compose.yml"}
    assert app._app_need(dict(here, resources={"memory": "256M"})) == {"memory": "256M", "cpus": 0}   # the manifest wins
    assert app._app_need(here) == {"memory": "1536M", "cpus": 0.5}                                    # else its services, summed
    (tmp_path / "docker-compose.yml").write_text("services:\n  web: {image: x}\n", encoding="utf-8")
    assert app._app_need(here) is None and app._app_need({"_dir": str(tmp_path), "compose": "missing.yml"}) is None
    # ...and the answer says so instead of "0MB fits"
    monkeypatch.setattr(app, "_manifest", lambda aid: dict(here, id=aid))
    monkeypatch.setattr(app, "_machine_here", lambda: ROOMY)
    said = app.app.test_client().get("/api/apps/notes/room").get_json()
    assert said["ok"] and said["undeclared"] is True and "לא מצהירה" in said["summary"]
    monkeypatch.setattr(app, "_machine_here", lambda: dict(ROOMY, disk={"available": GIB}))
    assert not app.app.test_client().get("/api/apps/notes/room").get_json()["ok"]                     # disk is still judged


def _far_room(linked, monkeypatch, room):
    """The linked office answers the room question with `room` (a status and a body)."""
    inner = app._call

    def call(method, url, body=None, timeout=60):
        if url.endswith("/room"):
            return room
        return inner(method, url, body, timeout)
    monkeypatch.setattr(app, "_call", call)


def test_a_move_asks_the_destination_for_room_before_it_exports_anything(plane, linked, monkeypatch):
    web = app.app.test_client()
    _far_room(linked, monkeypatch, (200, {"ok": False, "summary": "אין מקום בזיכרון ביעד: נדרש 2.4GB"}))
    r = web.post("/api/apps/notes/move", json={"to": "macbook"})
    assert r.status_code == 409 and "אין מקום בזיכרון" in r.get_json()["error"] and '"force": true' in r.get_json()["error"]
    assert not any(c.startswith(("data-job", "state:", "POST")) for c in plane)
    # the owner may know better — but only by saying so, and only with the JSON `true`
    assert web.post("/api/apps/notes/move", json={"to": "macbook", "force": "yes"}).status_code == 409
    assert web.post("/api/apps/notes/move", json={"to": "macbook", "force": True}).status_code == 200
    assert "data-job:export:notes" in plane


def test_an_office_that_has_room_or_does_not_know_the_question_is_not_refused(plane, linked, monkeypatch):
    web = app.app.test_client()
    for answer in ((200, {"ok": True, "summary": "אפשר"}), (404, {"error": "not found"}), (0, {"error": "no answer"})):
        plane.clear()
        app._JOBS.clear()
        _far_room(linked, monkeypatch, answer)
        assert web.post("/api/apps/notes/move", json={"to": "macbook"}).status_code == 200, answer
        assert "data-job:export:notes" in plane


# ── an app that an enabled app requires ────────────────────────────────────────

class _Box:
    """A container, as far as the lifecycle looks at one."""
    def __init__(self, name, calls):
        self.name, self.status, self.labels, self._calls = name, "running", {"com.docker.compose.service": name}, calls

    def stop(self, timeout=0):
        self._calls.append(f"stop:{self.name}")

    def start(self):
        self._calls.append(f"start:{self.name}")


def test_switching_off_an_app_that_another_needs_writes_the_line_and_leaves_it_running(plane, monkeypatch):
    monkeypatch.setattr(app, "_app_containers", lambda services: [_Box("notes", plane)])
    monkeypatch.setattr(app, "_required_by", lambda aid: ["drive"])
    payload, code = app._apply("notes", APP, False)
    assert code == 200 and payload["required_by"] == ["drive"] and payload["acted"] == []
    # its CONTAINERS stay (no stop) AND its workflows stay (no unpush): both would strand `drive`.
    assert plane == ["state:disabled", "render"]                             # no stop, no automations
    assert payload["blueprint"] == {"kept": "required by drive"}
    plane.clear()
    monkeypatch.setattr(app, "_required_by", lambda aid: [])
    payload, code = app._apply("notes", APP, False)
    assert payload["required_by"] == [] and payload["acted"] == ["notes"] and "stop:notes" in plane
    assert plane[-1] == "automations"                                        # nobody needs it: its blueprint is removed


def test_enabling_a_dependent_starts_its_providers_stopped_containers_and_names_the_absent(plane, monkeypatch):
    """Install INDOX, and n8n comes up: enabling an app START()s the compiled-but-stopped containers
    of the providers it pulls in, and NAMES any provider still wholly down — without ever failing the
    dependent's own enable (a provider up from nothing is its own bring-up, own-031)."""
    monkeypatch.setattr(app, "_closure_services", lambda aid: ["notes", "n8n", "n8n-worker"])
    stopped = _Box("n8n", plane); stopped.status = "exited"
    monkeypatch.setattr(app, "_app_containers", lambda services: [stopped] if "n8n" in services else [])
    payload, code = app._apply("notes", APP, True)
    assert code == 200 and payload["ok"]
    assert "start:n8n" in plane and payload["acted"] == ["n8n"]               # the stopped provider was started
    assert payload["providers_down"] == ["n8n-worker"]                       # the absent one is named, enable still ok


def test_an_app_that_is_required_is_not_archived_removed_or_moved(plane, linked, monkeypatch):
    monkeypatch.setattr(app, "_required_by", lambda aid: ["drive", "indox"])
    web = app.app.test_client()
    for verb, body in (("archive", {}), ("uninstall", {"purge": True}), ("move", {"to": "macbook"})):
        r = web.post(f"/api/apps/notes/{verb}", json=body)
        assert r.status_code == 409 and r.get_json()["required_by"] == ["drive", "indox"], verb
        assert "drive, indox" in r.get_json()["error"]
    assert plane == []                                   # nothing was asked of anyone, nothing written


def test_the_question_that_cannot_be_asked_refuses_nothing(monkeypatch):
    """A guard that refuses on its own failure would lock every app the day the compiler hiccups."""
    monkeypatch.setattr(app, "_compiler", lambda *a, **k: (1, "", "boom"))
    assert app._required_by("notes") == []
    monkeypatch.setattr(app, "_compiler", lambda *a, **k: (0, "not json", ""))
    assert app._required_by("notes") == []
    monkeypatch.setattr(app, "_compiler", lambda *a, **k: (0, '["drive"]', ""))
    assert app._required_by("notes") == ["drive"]
