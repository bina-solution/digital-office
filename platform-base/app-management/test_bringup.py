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
    # whose services they are (the plan's `provider` rows), and what compose runs here: none, unless a test says so
    monkeypatch.setattr(app, "_providers_of", lambda aid: [], raising=False)
    monkeypatch.setattr(app, "_compiled_services", lambda: set(), raising=False)
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


# ── convergence and sign-in: the apps the compiler names, not the enabled ones ─────────

def test_convergence_checks_the_automations_the_compiler_lists_not_the_enabled_apps(monkeypatch):
    """DGO-998, DGO-1001: an enabled app whose workflows another office holds is not checked here, and a
    provider the plan pulls in (n8n, off in the state) is. The list is the compiler's (`blueprints`)."""
    asked, applied, held = [], [], {"engine": False}

    def present(aid):
        asked.append(aid)
        return held.get(aid, True)

    def apply(aid, on):
        applied.append(aid)
        held[aid] = True
        return {"ok": True, "detail": "imported"}
    monkeypatch.setattr(app, "_load_state", lambda: {"web": {"state": "enabled", "workflows": "vps1"},
                                                       "engine": {"state": "disabled"}})
    monkeypatch.setattr(app, "_load_manifests", lambda: [dict(APP, id=aid, blueprints={"n8n": "flows"})
                                                           for aid in ("web", "engine")])
    monkeypatch.setattr(app, "_services_of", lambda m: [])
    monkeypatch.setattr(app, "_disposition", lambda entry: (entry or {}).get("state", "disabled"))
    monkeypatch.setattr(app, "_workflow_apps", lambda: (["engine"], None))
    monkeypatch.setattr(app, "_blueprint_present", present)
    monkeypatch.setattr(app, "_blueprint_apply", apply)
    rep = app.reconcile_once()
    assert applied == ["engine"] and "web" not in asked
    assert rep["converged"] == [{"app": "engine", "action": "blueprint", "detail": "imported"}] and not rep["errors"]


def test_convergence_that_cannot_ask_the_compiler_says_so_and_still_checks_the_enabled_apps(monkeypatch):
    """The second reader of DGO-998: one app the compiler refuses must not stop every other app's
    automations. The failure is an error, and the enabled apps that declare automations are checked."""
    asked = []
    monkeypatch.setattr(app, "_load_state", lambda: {"web": {"state": "enabled"}, "off": {"state": "disabled"}})
    monkeypatch.setattr(app, "_load_manifests", lambda: [dict(APP, id=aid, blueprints={"n8n": "flows"})
                                                           for aid in ("web", "off")] + [dict(APP, id="plain")])
    monkeypatch.setattr(app, "_services_of", lambda m: [])
    monkeypatch.setattr(app, "_disposition", lambda entry: (entry or {}).get("state", "disabled"))
    monkeypatch.setattr(app, "_workflow_apps", lambda: (None, "ERROR ghost: blueprints.n8n -> flows is not a directory"))
    monkeypatch.setattr(app, "_blueprint_present", lambda aid: asked.append(aid) or True)
    rep = app.reconcile_once()
    assert [e["app"] for e in rep["errors"]] == ["*"] and "not a directory" in rep["errors"][0]["error"]
    assert asked == ["web"]


def test_the_sign_in_refresh_runs_where_the_compiler_says_sign_in_runs(monkeypatch):
    """DGO-999: the refresh looked for `forward-auth` among the ENABLED apps only, so an identity app pulled
    in through the product's binding got none. It asks the compiler, and runs the refresh of the app it
    names; when nothing runs sign-in, there is nothing to refresh."""
    ran = []
    monkeypatch.setattr(app, "_capability_provider", lambda cap: "idp" if cap == "forward-auth" else None)
    monkeypatch.setattr(app, "_manifest", lambda aid: dict(APP, id=aid))
    monkeypatch.setattr(app, "_run_hook", lambda m, verb, timeout: ran.append((m["id"], verb)) or {"rc": 0})
    assert app._signin_refresh() == {"rc": 0} and ran == [("idp", "refresh")]
    monkeypatch.setattr(app, "_capability_provider", lambda cap: None)
    assert app._signin_refresh() is None and ran == [("idp", "refresh")]


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
    of the providers it pulls in, and NAMES a service still wholly down that no provider row claims
    (the fixture's plan knows none) — without failing the dependent's own enable. One the plan claims
    is brought up instead: the tests after `SUPABASE` below (DGO-1496)."""
    monkeypatch.setattr(app, "_closure_services", lambda aid: ["notes", "n8n", "n8n-worker"])
    stopped = _Box("n8n", plane); stopped.status = "exited"
    monkeypatch.setattr(app, "_app_containers", lambda services: [stopped] if "n8n" in services else [])
    payload, code = app._apply("notes", APP, True)
    assert code == 200 and payload["ok"]
    assert "start:n8n" in plane and payload["acted"] == ["n8n"]               # the stopped provider was started
    assert payload["providers_down"] == ["n8n-worker"]                       # the absent one is named, enable still ok


def test_a_dependent_waits_for_its_providers_after_they_are_started_and_its_failure_names_the_absent(plane, monkeypatch):
    """Exampleu, 2026-11-08: the wizard enabled drive, which requires supabase's database. Supabase had
    never been created. Drive waited its 600 s, failed its health check, and the job said only «did
    not all answer»: providers_down was empty because the providers were looked at only after a
    healthy wait. The providers come BEFORE the wait: a stopped one is started first, so the app can
    answer, and a failed wait names every provider that is wholly down."""
    monkeypatch.setattr(app, "_closure_services", lambda aid: ["notes", "db", "storage", "kong"])
    stopped = _Box("kong", plane); stopped.status = "exited"
    monkeypatch.setattr(app, "_app_containers", lambda services: [stopped] if "kong" in services else [])
    monkeypatch.setattr(app, "_wait_ready", lambda services, s: plane.append(f"answer:{s}") or False)
    payload, code = app._apply("notes", APP, True)
    assert plane.index("start:kong") < plane.index("answer:77")            # started before the wait
    assert code == 500 and payload["providers_down"] == ["db", "storage"]
    assert payload["create_errors"] == ["the app's containers did not all answer within 77s"
                                        " — the providers it needs are not up: db, storage"]
    assert "hook:onboard" not in plane


def test_a_compiler_that_hangs_never_strands_the_apps_own_bring_up(monkeypatch):
    """`_closure_services` is asked before the health wait now, so a compiler that times out must
    answer «no providers» (its docstring's promise), not end the bring-up as a 500 TimeoutExpired."""
    def hang(*args, **kw):
        raise app.subprocess.TimeoutExpired(cmd="reconcile.py", timeout=120)
    monkeypatch.setattr(app, "_compiler", hang)
    assert app._closure_services("notes") == []


# ── a provider the app needs and that has NO container is brought up, by `bbox update`'s own bring-up ──
# DGO-1496: the wizard enabled drive on Exampleu's core office, supabase had never been created, and the enable could
# only NAME it. `bbox update` (43ed7457) learned to bring a provider up as a bring-up does: its prepare, its images,
# its containers alone, a wait as long as its first start may take, its onboard — scripts/provider-up.sh. The enable
# brings up an absent provider through that same file, before the app's own prepare, as `bbox run` orders them.
SUPABASE = ("platform-base", "supabase", 600, ["db", "storage", "kong"])


def _needs_supabase(plane, monkeypatch, rc=0, out="  ok — supabase is up: db storage"):
    """notes needs supabase: kong runs, db and storage have no container. `_provider_up` is recorded, answers rc;
    automations are recorded per app (`automations:<id>`), and only notes declares any."""
    kong = _Box("kong", plane)
    monkeypatch.setattr(app, "_closure_services", lambda aid: ["db", "storage", "kong", "notes"])
    monkeypatch.setattr(app, "_app_containers", lambda services: [kong] if "kong" in services else [])
    monkeypatch.setattr(app, "_providers_of", lambda aid: [SUPABASE], raising=False)
    monkeypatch.setattr(app, "_compiled_services", lambda: {"db", "storage", "kong", "notes"}, raising=False)
    monkeypatch.setattr(app, "_provider_up",
                        lambda root, pid, seconds, svcs: plane.append(f"provider-up:{root}/{pid}:{seconds}:{','.join(svcs)}")
                        or {"ran": True, "rc": rc, "out": out}, raising=False)
    monkeypatch.setattr(app, "_blueprint_apply",
                        lambda aid, on: plane.append(f"automations:{aid}") or ({"ok": True} if aid == "notes" else None))


def test_an_enable_brings_up_a_provider_that_has_no_container_before_the_apps_own_prepare(plane, monkeypatch):
    _needs_supabase(plane, monkeypatch)
    steps = []
    payload, code = app._apply("notes", APP, True, steps.append)
    assert code == 200 and payload["ok"]
    # only what has no container (kong runs, and is not recreated), before anything of the app's own; its
    # automations are asked for as it comes up (it declares none here)
    assert plane == ["state:enabled", "render", "provider-up:platform-base/supabase:600:db,storage",
                     "automations:supabase", "hook:prepare", "create", "answer:77", "hook:onboard", "automations:notes"]
    assert steps[:3] == ["state", "providers", "prepare"]
    assert payload["providers_up"] == ["supabase"] and payload["providers_down"] == []
    assert payload["hooks"]["provider:supabase"] == {"ran": True, "rc": 0, "out": "  ok — supabase is up: db storage"}
    assert "provider_blueprints" not in payload


def test_the_lock_is_not_held_while_a_provider_comes_up_and_is_for_the_apps_own_containers(plane, monkeypatch):
    """A provider's bring-up is as long as its first start: held under the lock, every other change waited (a
    switch-off answered 409, `bbox run`'s converge timed out). The app's own prepare and containers keep it."""
    _needs_supabase(plane, monkeypatch)
    seen = {}
    locks = lambda aid: (app._LIFECYCLE.locked(), app._app_lock(aid).locked())   # noqa: E731
    monkeypatch.setattr(app, "_provider_up",
                        lambda root, pid, *a: seen.setdefault("provider", locks(pid)) and {"ran": True, "rc": 0, "out": ""})
    monkeypatch.setattr(app, "_run_hook",
                        lambda m, verb, t: seen.setdefault(verb, locks("notes")) and {"ran": True, "rc": 0, "out": ""})
    monkeypatch.setattr(app, "_install", lambda aid: (seen.setdefault("create", locks("notes")), ([], []))[1])
    payload, code = app._apply("notes", APP, True)
    # (lifecycle lock, the app's own lock): the provider's bring-up holds ITS lock only; the app's prepare and
    # containers hold both; its onboard neither
    assert code == 200 and seen == {"provider": (False, True), "prepare": (True, True), "create": (True, True),
                                    "onboard": (False, False)}
    assert not app._LIFECYCLE.locked() and not app._app_lock("notes").locked() and not app._app_lock("supabase").locked()


def test_a_provider_another_enable_brought_up_meanwhile_is_not_brought_up_again(plane, monkeypatch):
    """Two enables that need the same absent provider: the second asks again once it holds that provider's lock,
    and finds it there — its hooks and its `up` do not run a second time."""
    _needs_supabase(plane, monkeypatch)
    calls = []

    def containers(services):
        calls.append(list(services))
        if len(calls) == 1:                           # the first look: db and storage have no container
            return [] if "kong" not in services else [_Box("kong", plane)]
        return [_Box(s, plane) for s in services]     # under the lock: the other enable made them
    monkeypatch.setattr(app, "_app_containers", containers)
    payload, code = app._apply("notes", APP, True)
    assert code == 200 and not any(c.startswith("provider-up") for c in plane)
    assert payload["providers_up"] == [] and payload["providers_down"] == []


def test_a_provider_with_an_empty_key_of_its_own_is_refused_and_named(plane, monkeypatch):
    """`bbox run` and `bbox update` make an empty key (scripts/env-secrets.py) before a bring-up. This plane runs
    as root and does not write the owner's .env: a provider whose compose reads a key .env has no value for is
    refused, its keys named, and what makes them said."""
    _needs_supabase(plane, monkeypatch)
    monkeypatch.setattr(app, "_empty_keys_of", lambda m: ["SUPABASE_DB_PASSWORD", "SUPABASE_JWT_SECRET"]
                        if m.get("id") == "supabase" else [])
    payload, code = app._apply("notes", APP, True)
    assert code == 500 and not any(c.startswith(("provider-up", "hook:prepare", "create")) for c in plane)
    assert payload["create_errors"] == [
        "supabase, which notes needs, has no value yet in this office's .env for SUPABASE_DB_PASSWORD, "
        "SUPABASE_JWT_SECRET — `bbox run` makes them (scripts/env-secrets.py, which names any it cannot); "
        "switch notes on again after it"]
    assert payload["providers_down"] == ["db", "storage"]


def test_the_empty_keys_are_the_office_secrets_its_compose_reads_that_env_lacks(monkeypatch, tmp_path):
    app_dir, repo = tmp_path / "supabase", tmp_path / "repo"
    app_dir.mkdir(); repo.mkdir()
    (app_dir / "docker-compose.yml").write_text(
        "services:\n  db:\n    environment:\n      POSTGRES_PASSWORD: ${SUPABASE_DB_PASSWORD}\n"
        "      JWT: ${SUPABASE_JWT_SECRET:?the jwt}\n      SITE: ${SITE_URL:-x}\n      HOOK: ${N8N_WEBHOOK_PASS:-}\n"
        "      KEY: ${SUPABASE_ANON_KEY}\n")
    # as compose reads it: the LAST line for a key wins (SUPABASE_DB_PASSWORD ends empty)
    (repo / ".env").write_text("SUPABASE_DB_PASSWORD=old\nSUPABASE_JWT_SECRET='set'\n# SUPABASE_ANON_KEY=x\n"
                               "SUPABASE_DB_PASSWORD=\n")
    m = {"id": "supabase", "_dir": str(app_dir), "compose": "docker-compose.yml"}
    monkeypatch.setattr(app, "REPO", str(repo))
    monkeypatch.setattr(app, "_secret_names",
                        lambda: {"SUPABASE_DB_PASSWORD", "SUPABASE_JWT_SECRET", "SUPABASE_ANON_KEY", "N8N_WEBHOOK_PASS", "OTHER"})
    # SITE_URL is no office secret; N8N_WEBHOOK_PASS has compose's own fallback; OTHER is not read; a comment is no value
    assert app._empty_keys_of(m) == ["SUPABASE_ANON_KEY", "SUPABASE_DB_PASSWORD"]
    assert app._empty_keys_of({"id": "x"}) == [] and app._empty_keys_of(dict(m, compose="gone.yml")) == []
    (repo / ".env").unlink()          # a .env this container cannot read (a packaged office's /etc/binaos link)
    assert app._empty_keys_of(m) == []


def test_the_converge_leaves_an_app_that_is_being_brought_up_to_its_bring_up(plane, monkeypatch):
    """`bbox run`'s converge between an enable's two locks would create the app before its prepare."""
    made = []
    monkeypatch.setattr(app, "_load_state", lambda: {"notes": {"state": "enabled"}})
    monkeypatch.setattr(app, "_load_manifests", lambda: [dict(APP)])
    monkeypatch.setattr(app, "_install", lambda aid: made.append(aid) or ([aid], []))
    monkeypatch.setattr(app, "_workflow_apps", lambda: ([], None))
    for busy in ("job", "lock"):
        made.clear()
        ev = threading.Event()
        app._JOBS["notes"] = {"finished": ev} if busy == "job" else {"finished": threading.Event()}
        if busy == "lock":
            app._JOBS["notes"]["finished"].set()
            app._app_lock("notes").acquire()
        try:
            rep = app.reconcile_once()
        finally:
            if busy == "lock":
                app._app_lock("notes").release()
        assert made == [] and {"app": "notes", "why": "being brought up"} in rep["skipped"], busy
    app._JOBS["notes"]["finished"].set()
    seen = []
    monkeypatch.setattr(app, "_install", lambda aid: seen.append(app._app_lock(aid).locked()) or made.append(aid) or ([aid], []))
    rep = app.reconcile_once()
    # nobody is: the converge makes it, as before — holding the app's lock while it does, and giving it back
    assert made == ["notes"] and seen == [True] and not app._app_lock("notes").locked()


def test_a_provider_whose_workflows_another_office_holds_is_not_given_them_here(plane, monkeypatch):
    _needs_supabase(plane, monkeypatch)
    monkeypatch.setattr(app, "_workflow_apps", lambda: (["notes"], None))
    payload, code = app._apply("notes", APP, True)
    assert "automations:supabase" not in plane and "automations:notes" in plane


def test_a_sign_in_refresh_that_failed_for_a_provider_is_asked_again_for_the_app(plane, monkeypatch):
    _needs_supabase(plane, monkeypatch)
    sso = {"id": "supabase", "_dir": "/nowhere", "routing": [{"host": "studio", "auth": "sso"}]}
    monkeypatch.setattr(app, "_manifest", lambda aid: sso if aid == "supabase" else dict(APP, id=aid))
    answers = iter([{"ran": True, "rc": 1, "out": "the sign-in server did not answer"}, {"ran": True, "rc": 0, "out": ""}])
    monkeypatch.setattr(app, "_signin_refresh", lambda: plane.append("signin") or next(answers))
    payload, code = app._apply("notes", dict(APP, routing=[{"host": "notes", "auth": "sso"}]), True)
    assert plane.count("signin") == 2 and payload["hooks"]["signin"]["rc"] == 0


def test_a_provider_brought_up_gets_its_automations(plane, monkeypatch):
    """`reconcile_once` imports what is missing only when `bbox run` asks: a provider brought up by the enable gets
    its workflows with it, as the app gets its own."""
    _needs_supabase(plane, monkeypatch)
    monkeypatch.setattr(app, "_blueprint_apply",
                        lambda aid, on: plane.append(f"automations:{aid}") or {"hook": "push", "ok": True, "detail": aid})
    payload, code = app._apply("notes", APP, True)
    assert code == 200 and payload["provider_blueprints"] == {"supabase": {"hook": "push", "ok": True, "detail": "supabase"}}
    assert plane.index("automations:supabase") < plane.index("hook:prepare")


def test_an_enable_whose_providers_all_have_containers_brings_up_nothing(plane, monkeypatch):
    """Nothing new: a running provider is left alone, and the plan is not even asked."""
    n8n = _Box("n8n", plane)
    asked = []
    monkeypatch.setattr(app, "_closure_services", lambda aid: ["n8n", "notes"])
    monkeypatch.setattr(app, "_app_containers", lambda services: [n8n] if "n8n" in services else [])
    monkeypatch.setattr(app, "_providers_of", lambda aid: asked.append(aid) or [("apps", "n8n", 600, ["n8n"])],
                        raising=False)
    monkeypatch.setattr(app, "_provider_up", lambda *a: plane.append("provider-up") or {"rc": 0, "out": ""},
                        raising=False)
    payload, code = app._apply("notes", APP, True)
    assert code == 200 and payload["ok"]
    assert "provider-up" not in plane and asked == [] and payload["acted"] == []
    assert payload["providers_up"] == [] and payload["providers_down"] == []
    assert plane == ["state:enabled", "render", "hook:prepare", "create", "answer:77", "hook:onboard", "automations"]


def test_a_provider_that_does_not_come_up_fails_the_enable_with_its_words_and_the_app_is_not_started(plane, monkeypatch):
    _needs_supabase(plane, monkeypatch, rc=1, out="  build FAILED — last lines:\n    no space left on device")
    payload, code = app._apply("notes", APP, True)
    assert code == 500 and not payload["ok"]
    assert payload["create_errors"] == ["supabase, which notes needs, did not come up: no space left on device"]
    assert payload["providers_up"] == [] and payload["providers_down"] == ["db", "storage"]
    # it cannot answer without it: no prepare, no containers, no wait, no onboard — and no automations either: an
    # active schedule would fire at an app that is not there (Exampleu's first run: INDOX's, 46 times)
    assert not any(c.startswith(("hook:prepare", "create", "answer", "hook:onboard", "automations")) for c in plane), plane
    assert payload["blueprint"] == {"held": "the app was not started"}


def test_after_a_provider_that_failed_the_next_is_not_brought_up(plane, monkeypatch):
    """Two absent providers in order: the first comes up, the second fails — named, and nothing after it is tried."""
    rows = [("apps", "drive-local", 600, ["drive-local"]), SUPABASE, ("apps", "drive-google", 600, ["drive-google"])]
    monkeypatch.setattr(app, "_closure_services", lambda aid: ["drive-local", "db", "storage", "kong", "drive-google", "notes"])
    monkeypatch.setattr(app, "_app_containers", lambda services: [])
    monkeypatch.setattr(app, "_providers_of", lambda aid: rows)
    monkeypatch.setattr(app, "_compiled_services", lambda: {"drive-local", "db", "storage", "kong", "drive-google", "notes"})
    monkeypatch.setattr(app, "_provider_up", lambda root, pid, s, svcs: plane.append(f"provider-up:{pid}")
                        or {"ran": True, "rc": 1 if pid == "supabase" else 0, "out": "  db: exited  1"})
    payload, code = app._apply("notes", APP, True)
    assert [c for c in plane if c.startswith("provider-up")] == ["provider-up:drive-local", "provider-up:supabase"]
    assert payload["providers_up"] == ["drive-local"]
    assert payload["create_errors"] == ["supabase, which notes needs, did not come up: db: exited  1"]
    assert payload["providers_down"] == ["db", "storage", "kong", "drive-google"] and code == 500
    # held: not even the provider that came up gets its automations (they may call the one that did not)
    assert "automations" not in plane


def test_a_provider_with_a_stopped_and_an_absent_service_is_brought_up_whole_in_the_plans_order(plane, monkeypatch):
    """The stopped one goes to the same bring-up as its absent sibling (compose starts them in their own order),
    and a provider earlier in the plan whose services all exist is started BEFORE it — never storage before db."""
    db = _Box("db", plane); db.status = "exited"
    conn = _Box("connections", plane); conn.status = "exited"
    monkeypatch.setattr(app, "_closure_services", lambda aid: ["connections", "db", "storage", "kong", "notes"])
    monkeypatch.setattr(app, "_app_containers", lambda services: [c for c in (db, conn) if c.name in services])
    monkeypatch.setattr(app, "_providers_of", lambda aid: [("platform-base", "connections", 600, ["connections"]), SUPABASE])
    monkeypatch.setattr(app, "_compiled_services", lambda: {"connections", "db", "storage", "kong", "notes"})
    monkeypatch.setattr(app, "_provider_up", lambda root, pid, s, svcs: plane.append(f"provider-up:{pid}:{','.join(svcs)}")
                        or {"ran": True, "rc": 0, "out": ""})
    payload, code = app._apply("notes", APP, True)
    assert plane.index("start:connections") < plane.index("provider-up:supabase:db,storage,kong")
    assert "start:db" not in plane                                   # compose starts it, with storage
    assert payload["acted"] == ["connections"] and payload["providers_up"] == ["supabase"]


def test_a_checkout_without_the_bring_up_names_the_provider_and_fails_nothing(plane, monkeypatch):
    """app.py is the image's, scripts/provider-up.sh the mounted checkout's: an image newer than its checkout finds
    no such file. Then the provider is named, as before, and what is stopped is still started."""
    _needs_supabase(plane, monkeypatch)
    kong_stopped = _Box("kong", plane); kong_stopped.status = "exited"
    monkeypatch.setattr(app, "_app_containers", lambda services: [kong_stopped] if "kong" in services else [])
    monkeypatch.setattr(app, "_provider_up", lambda *a: plane.append("provider-up")
                        or {"ran": False, "rc": None, "out": "scripts/provider-up.sh is not in this office's checkout"})
    payload, code = app._apply("notes", APP, True)
    assert code == 200 and payload["ok"] and payload["create_errors"] == []      # not a failure of the enable
    assert "start:kong" in plane and payload["providers_down"] == ["db", "storage"] and payload["providers_up"] == []
    monkeypatch.setattr(app, "REPO", "/no/such/checkout")
    assert app._provider_up("platform-base", "supabase", 600, ["db"])["rc"] is None


def test_a_provider_whose_hook_failed_is_up_and_the_enable_goes_on_saying_so(plane, monkeypatch):
    """A hook that fails is said, and never fatal (as the app's own hooks): exit 3 is «up, a hook failed»."""
    _needs_supabase(plane, monkeypatch, rc=3, out="  supabase: its onboard hook FAILED (exit 1)\n  ok — supabase is up: db storage")
    payload, code = app._apply("notes", APP, True)
    assert code == 200 and payload["ok"] and payload["providers_up"] == ["supabase"]
    assert payload["hooks"]["provider:supabase"]["rc"] == 3
    assert "its onboard hook FAILED" in payload["hooks"]["provider:supabase"]["out"]


def test_a_provider_brought_up_that_serves_a_signed_in_host_gets_the_sign_in_refresh(plane, monkeypatch):
    _needs_supabase(plane, monkeypatch)
    sso = {"id": "supabase", "_dir": "/nowhere", "routing": [{"host": "studio", "auth": "sso"}]}
    monkeypatch.setattr(app, "_manifest", lambda aid: sso if aid == "supabase" else dict(APP, id=aid))
    payload, code = app._apply("notes", APP, True)
    # right after it comes up, whatever becomes of the app (notes itself gates no host), and once
    assert code == 200 and plane.count("signin") == 1
    assert plane.index("provider-up:platform-base/supabase:600:db,storage") < plane.index("signin") < plane.index("hook:prepare")
    sso_app = dict(APP, routing=[{"host": "notes", "auth": "sso"}])
    plane.clear()
    payload, code = app._apply("notes", sso_app, True)
    assert plane.count("signin") == 1                            # one refresh serves every compiled host


def test_absent_services_no_plan_row_claims_are_named_and_nothing_is_brought_up(plane, monkeypatch):
    """The plan could not be asked (or names no app for them): named in providers_down, as before."""
    _needs_supabase(plane, monkeypatch)
    monkeypatch.setattr(app, "_providers_of", lambda aid: [])
    payload, code = app._apply("notes", APP, True)
    assert not any(c.startswith("provider-up") for c in plane)
    assert payload["providers_down"] == ["db", "storage"] and payload["providers_up"] == []


def test_a_provider_this_office_does_not_compile_is_not_brought_up(plane, monkeypatch):
    """It runs on a linked office, or not at all: compose here has no such service (the question `bbox update` asks
    too). Named, never brought up; and when compose cannot say what it runs, nothing is."""
    for compiled in ({"kong", "notes"}, None):
        plane.clear()
        _needs_supabase(plane, monkeypatch)
        monkeypatch.setattr(app, "_compiled_services", lambda c=compiled: c)
        payload, code = app._apply("notes", APP, True)
        assert not any(c.startswith("provider-up") for c in plane), compiled
        assert payload["providers_down"] == ["db", "storage"] and payload["providers_up"] == [], compiled


class _Proc:
    """subprocess.Popen, as far as `_provider_up` uses it; `hang` makes communicate() time out once."""
    seen, hang, killed = {}, False, []

    def __init__(self, argv, **kw):
        _Proc.seen = dict(argv=argv, cwd=kw.get("cwd"), env=kw.get("env") or {}, group=kw.get("start_new_session"))
        self.pid, self.returncode, self.waited = 4242, 0, False

    def communicate(self, timeout=None):
        if _Proc.hang and not self.waited:
            self.waited = True
            _Proc.seen["timeout"] = timeout
            raise app.subprocess.TimeoutExpired(cmd="provider-up.sh", timeout=timeout)
        _Proc.seen.setdefault("timeout", timeout)
        return "  ok — supabase is up: db storage\n", None


def test_a_provider_is_brought_up_by_the_file_bbox_update_sources(monkeypatch):
    """ONE bring-up: the enable runs scripts/provider-up.sh, the file app-update.sh sources for its own providers —
    in its own process group, building only what is missing (as `_install` does)."""
    monkeypatch.setattr(app, "REPO", str(HERE.parents[1]))          # where scripts/provider-up.sh is
    monkeypatch.setattr(_Proc, "hang", False)
    monkeypatch.setattr(app.subprocess, "Popen", _Proc)
    r = app._provider_up("platform-base", "supabase", 600, ["db", "storage"])
    seen = _Proc.seen
    assert seen["argv"] == ["bash", "scripts/provider-up.sh", "platform-base", "supabase", "600", "db", "storage"]
    assert seen["cwd"] == app.REPO and seen["env"].get("COMPOSE_PROJECT_NAME") == app.PROJECT
    assert seen["env"].get("PROVIDER_UP_BUILD") == "missing" and seen["group"] is True
    assert seen["timeout"] > 600                                  # longer than its own first start
    assert r == {"ran": True, "rc": 0, "out": "  ok — supabase is up: db storage"}
    update = (HERE.parents[1] / "scripts" / "app-update.sh").read_text()
    assert '. "${HERE}/provider-up.sh"' in update


def test_what_this_office_runs_is_composes_own_answer(monkeypatch):
    class Services:
        returncode, stdout, stderr = 0, "db\nstorage\n", ""
    seen = {}
    monkeypatch.setattr(app.subprocess, "run",
                        lambda argv, **kw: seen.update(argv=argv, cwd=kw.get("cwd"), env=kw.get("env") or {}) or Services())
    assert app._compiled_services() == {"db", "storage"}
    assert seen["argv"] == ["bash", "scripts/dc", "config", "--services"] and seen["cwd"] == app.REPO
    assert seen["env"].get("COMPOSE_PROJECT_NAME") == app.PROJECT
    Services.returncode = 1
    assert app._compiled_services() is None                        # cannot say: nothing is brought up


def test_a_bring_up_that_never_ends_is_ended_whole_and_did_not_come_up(monkeypatch):
    monkeypatch.setattr(app, "REPO", str(HERE.parents[1]))
    monkeypatch.setattr(_Proc, "hang", True)
    monkeypatch.setattr(app.subprocess, "Popen", _Proc)
    killed = []
    monkeypatch.setattr(app.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    r = app._provider_up("platform-base", "supabase", 600, ["db"])
    assert r["rc"] == 1 and "did not finish" in r["out"]
    assert killed == [(4242, app.signal.SIGKILL)]                  # its group: compose and a hook too, not only bash


def test_the_providers_are_the_plans_provider_rows_in_its_order(monkeypatch):
    class Plan:
        returncode, stderr = 0, ""
        stdout = ("named drive drive apps drive\nprovider platform-base connections 600 connections\n"
                  "later connections sign-in\nprovider apps supabase 900 db rest storage\n")
    seen = {}
    monkeypatch.setattr(app.subprocess, "run", lambda argv, **kw: seen.update(argv=argv) or Plan())
    assert app._providers_of("drive") == [("platform-base", "connections", 600, ["connections"]),
                                          ("apps", "supabase", 900, ["db", "rest", "storage"])]
    assert seen["argv"][-2:] == [app.os.path.join(app.REPO, "scripts", "app-update-plan.py"), "drive"]
    Plan.returncode = 1
    assert app._providers_of("drive") == []                        # a plan that cannot be had brings up nothing


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
