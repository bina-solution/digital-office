"""The frame gate THROUGH the enable path (`_apply`), against a real answer (#63).

An app is switched on from the apps screen; once it answers, the plane asks whether the console may show it
inside itself (platform/manager/framecheck.py). FRAME_GATE=warn (default): the enable succeeds and its answer
carries the verdict. FRAME_GATE=refuse: a NEW app that answers `X-Frame-Options: DENY` is switched off again
through the plane's own disable path, before its bootstrap, and the change fails with the sentence; an app that
was already enabled is never switched off by a re-apply.

Run: python -m pytest platform-base/app-management/test_frame_gate.py -q
"""
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import pytest
except ImportError:          # the app-management image has no pytest: `python test_frame_gate.py` runs them
    pytest = None

HERE = pathlib.Path(__file__).resolve().parent
MANAGER = HERE.parent.parent / "platform" / "manager"
sys.path.insert(0, str(MANAGER))
import framecheck  # noqa: E402


def _load():
    spec = importlib.util.spec_from_file_location("appmgmt_frame_gate", HERE / "app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["appmgmt_frame_gate"] = mod
    spec.loader.exec_module(mod)
    return mod


app = _load()


class Deny(BaseHTTPRequestHandler):
    def do_GET(self):                       # noqa: N802
        host = (self.headers.get("Host") or "").split(":")[0]
        self.send_response(200)
        if host.startswith("deny."):
            self.send_header("X-Frame-Options", "DENY")
        else:
            self.send_header("Content-Security-Policy", "frame-ancestors 'self' http://console.office.test")
        self.end_headers()
        self.wfile.write(b"<!doctype html>")

    def log_message(self, *a):
        pass


class _Srv(ThreadingHTTPServer):
    allow_reuse_address = False      # Windows lets SO_REUSEADDR bind a port another test already listens on
    daemon_threads = True


def _server():
    for port in range(8951, 8960):
        try:
            srv = _Srv(("127.0.0.1", port), Deny)
        except OSError:
            continue
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return port
    raise RuntimeError("no free port in 8951-8959")


PORT = _server()
REPO = pathlib.Path(tempfile.mkdtemp(prefix="frame-gate-"))
(REPO / ".env").write_text(f"CONSOLE_BASE_URL=console.office.test\nAUTH_PROTOCOL=http\nDEPLOYMENT_DOMAIN=office.test\n"
                           f"NOTES_BASE_URL=http://deny.office.test:{PORT}\n"
                           f"GOOD_BASE_URL=http://good.office.test:{PORT}\n", encoding="utf-8")
FRAMED = {"id": "notes", "_root": "apps", "_dir": "/nowhere", "progress_deadline_seconds": 77, "version": "2.0",
          "title": {"en": "Notes"},
          "routing": [{"host": "notes", "port": 80, "auth": "none",
                       "module": {"external": True, "alias": "notes", "name": "Notes"}}]}


def _fixture(fn):
    return pytest.fixture(fn) if pytest else fn


@_fixture
def plane(monkeypatch):
    """The plane with every effect replaced by a recorder (test_bringup.py's fixture), and the frame gate real."""
    calls = []
    monkeypatch.setattr(app, "_JOBS", {})
    monkeypatch.setattr(app, "docker_sdk", object())
    monkeypatch.setattr(app, "_services_of", lambda m: ["notes"])
    monkeypatch.setattr(app, "_set_disposition", lambda aid, d: calls.append(f"state:{d}") or True)
    monkeypatch.setattr(app, "_render", lambda: calls.append("render"))
    monkeypatch.setattr(app, "_app_containers", lambda services: [])
    monkeypatch.setattr(app, "_install", lambda aid: (calls.append("create") or ["notes"], []))
    monkeypatch.setattr(app, "_wait_ready", lambda services, s: calls.append("answer") or True)
    monkeypatch.setattr(app, "_run_hook",
                        lambda m, verb, t: calls.append(f"hook:{verb}") or {"ran": True, "rc": 0, "out": ""})
    monkeypatch.setattr(app, "_blueprint_apply", lambda aid, on: calls.append(f"automations:{on}"))
    monkeypatch.setattr(app, "_container_index", lambda: {})
    monkeypatch.setattr(app, "_held_volumes", lambda m: [])
    monkeypatch.setattr(app, "_required_by", lambda aid: [])
    monkeypatch.setattr(app, "_closure_services", lambda aid: [])
    monkeypatch.setattr(app, "_disposition", lambda entry: (entry or {}).get("state", "disabled"))
    monkeypatch.setattr(app, "_signin_refresh", lambda: calls.append("signin") or {"ran": True, "rc": 0, "out": ""})
    monkeypatch.setattr(app, "_load_state", lambda: {})                      # the app was OFF before
    monkeypatch.setattr(framecheck, "REPO", REPO)
    monkeypatch.setenv("FRAMECHECK_CONNECT_TO", "office.test=127.0.0.1")
    monkeypatch.delenv("FRAME_GATE", raising=False)
    for k in ("CONSOLE_BASE_URL", "AUTH_PROTOCOL", "DEPLOYMENT_DOMAIN", "NOTES_BASE_URL", "GOOD_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    return calls


def test_warn_by_default_the_enable_succeeds_and_its_answer_carries_the_verdict(plane):
    steps = []
    payload, code = app._apply("notes", FRAMED, True, steps.append)
    assert code == 200 and payload["ok"] and payload["enabled"]
    assert payload["frame"]["verdict"] == "refused" and not payload["frame"]["refuse"]
    assert "X-Frame-Options: DENY" in payload["frame"]["sentence"]
    assert steps == ["state", "prepare", "containers", "health", "frame", "onboard", "automations"]
    rec = json.loads((REPO / "data" / "platform" / "frame-checks.json").read_text(encoding="utf-8"))
    assert rec["notes"]["version"] == "2.0" and rec["notes"]["phase"] == "enable"


def test_refuse_switches_a_new_app_off_again_before_its_bootstrap_and_says_why(plane, monkeypatch):
    monkeypatch.setenv("FRAME_GATE", "refuse")
    payload, code = app._apply("notes", FRAMED, True)
    assert code == 409 and payload["ok"] is False and payload["enabled"] is False
    assert "X-Frame-Options: DENY" in payload["error"] and "frame-ancestors 'self' http://console.office.test" \
        in payload["error"]
    assert payload["switched_off"] is True
    # on, answered, judged — then the plane's own disable path; the app's bootstrap never ran
    assert plane == ["state:enabled", "render", "hook:prepare", "create", "answer",
                     "state:disabled", "render", "automations:False"]


def test_refuse_never_switches_off_an_app_that_was_already_enabled(plane, monkeypatch):
    monkeypatch.setenv("FRAME_GATE", "refuse")
    monkeypatch.setattr(app, "_load_state", lambda: {"notes": {"state": "enabled"}})
    payload, code = app._apply("notes", FRAMED, True)
    assert code == 200 and payload["ok"] and payload["frame"]["verdict"] == "refused"
    assert not payload["frame"]["refuse"] and "state:disabled" not in plane


def test_an_app_that_allows_the_console_passes_refuse(plane, monkeypatch):
    monkeypatch.setenv("FRAME_GATE", "refuse")
    good = dict(FRAMED, id="good", routing=[dict(FRAMED["routing"][0], host="good")])
    payload, code = app._apply("good", good, True)
    assert code == 200 and payload["ok"] and payload["frame"]["verdict"] == "ok"


def test_off_asks_nothing_and_the_enable_is_exactly_what_it_was(plane, monkeypatch):
    monkeypatch.setenv("FRAME_GATE", "off")
    steps = []
    payload, code = app._apply("notes", FRAMED, True, steps.append)
    assert code == 200 and "frame" not in payload and "frame" not in steps


def test_a_checker_that_cannot_run_never_stops_an_enable(plane, monkeypatch):
    monkeypatch.setenv("FRAME_GATE", "refuse")
    monkeypatch.setattr(framecheck, "gate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    payload, code = app._apply("notes", FRAMED, True)
    assert code == 200 and payload["ok"] and "frame" not in payload


def test_switching_off_is_never_judged(plane, monkeypatch):
    monkeypatch.setenv("FRAME_GATE", "refuse")
    payload, code = app._apply("notes", FRAMED, False)
    assert code == 200 and "frame" not in payload


if __name__ == "__main__":
    # without pytest (the app-management image has none): the same tests with a minimal monkeypatch
    class _MP:
        def __init__(self):
            self.undo = []

        def setattr(self, obj, name, value):
            self.undo.append(lambda old=getattr(obj, name): setattr(obj, name, old))
            setattr(obj, name, value)

        def setenv(self, k, v):
            self.undo.append(lambda old=os.environ.get(k): os.environ.__setitem__(k, old) if old is not None
                             else os.environ.pop(k, None))
            os.environ[k] = v

        def delenv(self, k, raising=True):
            if k in os.environ:
                self.setenv(k, os.environ[k])
                del os.environ[k]

        def close(self):
            for u in reversed(self.undo):
                u()

    bad, tests = 0, [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for name, fn in tests:
        mp = _MP()
        try:
            calls = getattr(plane, "__wrapped__", plane)(mp)
            fn(calls, mp) if fn.__code__.co_argcount == 2 else fn(calls)
            print("ok  ", name)
        except Exception as e:                       # noqa: BLE001
            bad += 1
            print("FAIL", name, "-", type(e).__name__, e)
        finally:
            mp.close()
    print(f"{len(tests) - bad}/{len(tests)} passed")
    sys.exit(1 if bad else 0)
