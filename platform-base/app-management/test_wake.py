"""The waker of on-demand apps (DGO-1270): what app-management answers at a sleeping app's address.

The compiler gives an on-demand route's routers to this service at priority 1, behind the same sign-in
and a header naming the app (reconcile.on_demand_labels). Held here, over a fake engine: a page request
starts the app's stopped container and gets a Hebrew page that reloads itself; any other request gets
the same start and a JSON 503; nothing is started for an app that is not on demand, for one that is
switched off here, or for a caller that crossed a link; a missing container is said, never built in a
request; a running one that fails its probe is said too; a start under way is not queued behind; a
request without the header is the app's own; and an on-demand app that ended as a stop does is ASLEEP on
the apps screen, while one that crashed or was OOM-killed is not.

Run: python -m pytest platform-base/app-management/test_wake.py -q   (or python3 …/test_wake.py)
"""
import importlib.util
import pathlib
import sys
import types

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("appmgmt_wake", HERE / "app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["appmgmt_wake"] = mod
    spec.loader.exec_module(mod)
    return mod


app = _load()
CAD = {"id": "cad", "title": {"he": "מודלים תלת־ממד", "en": "FreeCAD"}, "compose": "docker-compose.yml",
       "routing": [{"host": "cad", "port": 3000, "on_demand": {"idle": "2h"}}]}
PLAIN = {"id": "drive", "routing": [{"host": "drive", "port": 8975}]}


class Container:
    def __init__(self, svc, status, health=None):
        self.labels, self.status, self.started = {"com.docker.compose.service": svc}, status, 0
        self.attrs = {"State": {"Health": {"Status": health}} if health else {}}

    def start(self):
        self.started += 1
        self.status = "running"


def wake(headers, containers, path="/", enabled=("cad", "drive")):
    """One request to the waker over a fake engine: (response, the containers, the filters asked, the
    services compose was asked to create)."""
    asked, made = [], []
    client = types.SimpleNamespace(containers=types.SimpleNamespace(
        list=lambda all=False, filters=None: (asked.append(filters) or
                                              [c for c in containers if any(
                                                  f"com.docker.compose.service={c.labels['com.docker.compose.service']}" == l
                                                  for l in filters["label"])])))
    real = (app._manifest, app._services_of, app.docker_sdk, app._compose_up, app._disposition, app._load_state)
    app._manifest = lambda aid: next((m for m in (CAD, PLAIN) if m["id"] == aid), None)
    app._services_of = lambda m: [r["host"] for r in m.get("routing") or []]
    app.docker_sdk = types.SimpleNamespace(from_env=lambda timeout=None: client)
    app._compose_up = lambda services: made.extend(services)
    app._load_state = lambda: {a: {"state": "enabled"} for a in enabled}
    app._disposition = lambda entry: (entry or {}).get("state") or "disabled"
    try:
        return app.app.test_client().get(path, headers=headers), containers, asked, made
    finally:
        (app._manifest, app._services_of, app.docker_sdk, app._compose_up, app._disposition,
         app._load_state) = real


def test_a_page_request_starts_the_sleeping_app_and_gets_a_page_that_reloads():
    r, (cad,), asked, made = wake({"X-Dgo-Wake": "cad", "Accept": "text/html,*/*"}, [Container("cad", "exited")])
    page = r.get_data(as_text=True)
    assert r.status_code == 503 and r.headers["Retry-After"] == "4" and "no-store" in r.headers["Cache-Control"]
    assert 'dir="rtl"' in page and "מפעיל את מודלים תלת־ממד" in page and 'http-equiv="refresh" content="4"' in page
    assert cad.started == 1 and made == []
    assert asked and "com.docker.compose.service=cad" in asked[0]["label"]
    assert f"com.docker.compose.project={app.PROJECT}" in asked[0]["label"]   # this office's only


def test_any_other_request_gets_the_same_start_and_a_json_503():
    r, (cad,), _, _ = wake({"X-Dgo-Wake": "cad", "Accept": "application/json"}, [Container("cad", "exited")],
                           path="/websocket")
    assert r.status_code == 503 and r.get_json() == {"waking": "cad", "started": ["cad"], "state": "starting",
                                                     "error": None}
    assert cad.started == 1


def test_a_container_that_is_already_starting_is_not_started_again():
    r, (cad,), _, _ = wake({"X-Dgo-Wake": "cad", "Accept": "text/html"}, [Container("cad", "running", "starting")])
    assert r.status_code == 503 and cad.started == 0 and "ועולה עכשיו" in r.get_data(as_text=True)


def test_a_running_app_that_fails_its_probe_is_said_not_promised():
    r, (cad,), _, _ = wake({"X-Dgo-Wake": "cad", "Accept": "application/json"}, [Container("cad", "running", "unhealthy")])
    assert r.status_code == 503 and r.get_json()["state"] == "unhealthy" and r.headers["Retry-After"] == "30"
    assert cad.started == 0


def test_a_missing_container_is_said_and_never_built_in_a_request():
    r, _, _, made = wake({"X-Dgo-Wake": "cad", "Accept": "text/html"}, [])
    page = r.get_data(as_text=True)
    assert r.status_code == 503 and made == [] and "המכולה שלה חסרה" in page and 'content="30"' in page


def test_an_app_that_is_not_on_demand_is_never_started_from_here():
    r, (drive,), _, _ = wake({"X-Dgo-Wake": "drive", "Accept": "text/html"}, [Container("drive", "exited")])
    assert r.status_code == 404 and drive.started == 0
    r, _, _, _ = wake({"X-Dgo-Wake": "nope", "Accept": "text/html"}, [])
    assert r.status_code == 404


def test_an_app_switched_off_here_stays_off_whatever_routes_are_still_up():
    r, (cad,), asked, _ = wake({"X-Dgo-Wake": "cad", "Accept": "text/html"}, [Container("cad", "exited")],
                               enabled=("drive",))
    assert r.status_code == 409 and cad.started == 0 and asked == []


def test_a_caller_that_crossed_a_link_starts_nothing_here():
    r, (cad,), asked, _ = wake({"X-Dgo-Wake": "cad", "X-DGO-Office": "macbook", "Accept": "text/html"},
                               [Container("cad", "exited")])
    assert r.status_code == 403 and cad.started == 0 and asked == []


def test_a_start_under_way_is_answered_not_queued_behind():
    app._WAKE_LOCK.acquire()
    try:
        r, (cad,), _, _ = wake({"X-Dgo-Wake": "cad", "Accept": "text/html"}, [Container("cad", "exited")])
    finally:
        app._WAKE_LOCK.release()
    assert r.status_code == 503 and cad.started == 0


def test_a_request_without_the_header_is_the_apps_own():
    r, _, asked, _ = wake({}, [Container("cad", "exited")], path="/healthz")
    assert r.status_code == 200 and asked == []


def test_an_on_demand_app_that_ended_as_a_stop_does_is_asleep_and_one_that_crashed_is_not():
    row = lambda code, oom=False: {"cad": {"status": "exited", "exit_code": code, "oom": oom}}  # noqa: E731
    for code in (0, 137, 143):
        assert app._asleep(["cad"], row(code), CAD), code
    assert not app._asleep(["cad"], row(1), CAD)                       # it crashed
    assert not app._asleep(["cad"], row(137, oom=True), CAD)           # the kernel killed it
    assert not app._asleep(["cad"], row(0), PLAIN)                     # not on demand: stopped is stopped
    assert not app._asleep(["cad"], {}, CAD)                           # no container at all
    asleep = {"state": "asleep", "running": 0, "total": 1, "health": "none", "present": 1}
    conds = {c["type"]: c for c in app._conditions("cad", asleep, "enabled", 1, [], [], None)}
    assert conds["Started"]["reason"] == "Asleep" and conds["Ready"]["status"] == "True"
    fell = {"state": "stopped", "running": 0, "total": 1, "health": "none", "present": 1}
    conds = {c["type"]: c for c in app._conditions("drive", fell, "enabled", 1, [], [], None)}
    assert conds["Ready"]["status"] == "False" and conds["Started"]["reason"] == "NoContainersRunning"


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:                            # noqa: BLE001 — report every test
                failed += 1
                print(f"FAIL {name}: {type(e).__name__}: {e}")
    sys.exit(1 if failed else 0)
