#!/usr/bin/env python3
"""test_app_input — what app.py accepts into a declaration it STORES, and from whom (DGO-622, DGO-624).

    python3 apps/dgo-extend/tests/test_app_input.py       # or: python3 -m pytest apps/dgo-extend/tests/test_app_input.py

What app.py takes from a request and keeps: the `apps` map of an office it declares (each key becomes
`set-state --app <key>` on that office's machine, a line of its platform.state.yaml), the `serve:` map
(each key reaches the firewall's rule text) and the users `serve.<app>.identity` presents a linked
office's request as (the link's door writes them into a header). A value that ends in a line break is
none of these, and each used to be checked with `$` (which also matches just before a final newline)
or not at all. And a request that crossed a link writes none of it (DGO-624).

app.py needs its web stack to be imported; where fastapi or requests is absent (the gate's own host),
the few names it reads while loading are stood in for and the functions under test are called
directly. Where the web stack is installed, the link's guard is also asked through the app itself.
Hermetic: no office, no network — the store and the tunnel render are replaced for the test.
"""
from __future__ import annotations

import asyncio
import atexit
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "apps/dgo-extend"
sys.path.insert(0, str(APP))


def _stand_ins() -> list[str]:
    """fastapi and requests, as far as loading app.py needs them — only the ones that are absent."""
    absent = []
    try:
        import requests  # noqa: F401
    except ImportError:
        sys.modules["requests"] = types.ModuleType("requests")
        absent.append("requests")
    try:
        import fastapi  # noqa: F401
        return absent
    except ImportError:
        absent.append("fastapi")

    class Routes:
        added: list = []                       # what app.py wraps itself in

        def __init__(self, *args, **kwargs):
            pass

        def _route(self, *args, **kwargs):
            return lambda fn: fn
        get = post = put = delete = patch = api_route = on_event = exception_handler = middleware = _route

        def mount(self, *args, **kwargs):
            pass

        def include_router(self, *args, **kwargs):
            pass

        def add_middleware(self, cls, *args, **kwargs):
            Routes.added.append(cls)

    class Response:
        def __init__(self, content=None, status_code=200, **kwargs):
            self.status_code = status_code
            self.body = json.dumps(content, ensure_ascii=False).encode()

    async def run_in_threadpool(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    fastapi = types.ModuleType("fastapi")
    fastapi.FastAPI = fastapi.APIRouter = Routes
    fastapi.Request = type("Request", (), {})
    concurrency = types.ModuleType("fastapi.concurrency")
    concurrency.run_in_threadpool = run_in_threadpool
    responses = types.ModuleType("fastapi.responses")
    responses.FileResponse = responses.JSONResponse = responses.Response = responses.StreamingResponse = Response
    static = types.ModuleType("fastapi.staticfiles")
    static.StaticFiles = type("StaticFiles", (), {"__init__": lambda self, *a, **k: None})
    sys.modules.update({"fastapi": fastapi, "fastapi.concurrency": concurrency,
                        "fastapi.responses": responses, "fastapi.staticfiles": static})
    return absent


def load():
    """app.py, loaded once, with a scratch volume and a compiled registry of its own."""
    if "dgo_extend_app" in sys.modules:
        return sys.modules["dgo_extend_app"]
    stood_in = _stand_ins()
    os.environ["DGO_STATE_DIR"] = tempfile.mkdtemp(prefix="dgo-app-input-")
    registry = Path(tempfile.mkdtemp(prefix="dgo-app-registry-"))
    for scratch in (os.environ["DGO_STATE_DIR"], registry):
        atexit.register(shutil.rmtree, scratch, True)
    (registry / "office.apps.json").write_text(json.dumps({"apps": [
        {"app": "drive", "alias": "drive", "name": "Drive", "port": 8975},
        {"app": "dgo-extend", "alias": "dgo-extend", "name": "לשכות", "port": 8983}]}), encoding="utf-8")
    os.environ["DGO_REGISTRY_DIR"] = str(registry)
    spec = importlib.util.spec_from_file_location("dgo_extend_app", APP / "app.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["dgo_extend_app"] = module
    spec.loader.exec_module(module)
    module.STOOD_IN = stood_in
    return module


class _Asked:
    """A request with a JSON body, as far as app.py reads one."""

    def __init__(self, body: dict):
        self._raw = json.dumps(body).encode()

    async def body(self):
        return self._raw

    async def json(self):
        return json.loads(self._raw)


GOOD = {"id": "office2", "machine": "computer_ssh-x", "domain": "office2.example.co.il",
        "source": {"repo": "https://example.org/office.git", "commit": "abcdef1"}}


def test_an_apps_key_that_is_an_app_id_is_kept():
    d, err = load().validate(dict(GOOD, apps={"drive": "enabled", "bina-ds": True, "n8n": "disabled"}), None)
    assert err is None and d["apps"] == {"drive": "enabled", "bina-ds": "enabled", "n8n": "disabled"}, err


def test_a_domain_change_keeps_the_domain_before_it():
    # FPG-33: the env step moves an installed office's .env from the previous domain, and from no other
    a = load()
    d, err = a.validate(GOOD, None)
    assert err is None and "renamed_from" not in d, (d, err)
    moved, err = a.validate({"domain": "o2.example.co.il"}, d)
    assert err is None and moved["domain"] == "o2.example.co.il" and moved["renamed_from"] == GOOD["domain"], (moved, err)
    same, err = a.validate({"label": "Office two"}, moved)
    assert err is None and same["renamed_from"] == GOOD["domain"], "an edit that keeps the domain keeps the record"
    # a typo corrected before the converge ran: the machine is still on the first domain (the second reader)
    again, err = a.validate({"domain": "o3.example.co.il"}, moved)
    assert err is None and again["renamed_from"] == GOOD["domain"], "the machine's domain, not the typo's"
    back, err = a.validate({"domain": GOOD["domain"]}, again)
    assert err is None and "renamed_from" not in back, "changed back to the machine's domain: nothing to rename"
    applied = dict(moved)
    applied.pop("renamed_from")                          # what the env step leaves once the machine moved
    later, err = a.validate({"domain": "o3.example.co.il"}, applied)
    assert err is None and later["renamed_from"] == "o2.example.co.il", "after a converge, the next change starts there"
    nested, err = a.validate({"domain": "staging." + GOOD["domain"]}, d)
    assert nested is None and err, "a rename into a subdomain of the old name is refused at once"


def test_a_rename_the_machine_finished_is_forgotten_and_an_edit_meanwhile_starts_where_the_machine_is():
    # FPG-33, the third reader: the env step's _forget_rename, against the record on disk
    a = load()
    sys.modules.setdefault("app", a)                     # what converge's `import app` reaches
    import converge
    d, err = a.validate(dict(GOOD, id="renamer"), None)
    assert err is None
    a.save(d)
    moved, _ = a.validate({"domain": "o2.example.co.il"}, d)
    a.save(moved)
    run_copy = dict(moved)
    converge._forget_rename(run_copy)                    # the machine reached o2
    assert "renamed_from" not in a.load("renamer") and "renamed_from" not in run_copy
    moved, _ = a.validate({"domain": "o3.example.co.il"}, a.load("renamer"))
    a.save(moved)
    run_copy = dict(moved)                               # a run for o3 starts, machine on o2 …
    edited, _ = a.validate({"domain": "o4.example.co.il"}, a.load("renamer"))
    a.save(edited)                                       # … the owner changes to o4 meanwhile
    converge._forget_rename(run_copy)                    # the machine reached o3
    on_disk = a.load("renamer")
    assert on_disk["domain"] == "o4.example.co.il" and on_disk["renamed_from"] == "o3.example.co.il", on_disk


def test_the_accounts_step_moves_the_addresses_once_then_forgets_and_refreshes_the_login():
    # FPG-34: the env step leaves `addresses_from`; `accounts` runs the office's own verb, after `run`
    a = load()
    sys.modules.setdefault("app", a)
    import converge
    d, _ = a.validate(dict(GOOD, id="mover", domain="new.example.co.il"), None)
    a.save(d)
    converge._forget_rename(dict(d), addresses_from="old.example.co.il")
    converge._forget_rename(dict(d), addresses_from="mid.example.co.il")
    converge._forget_rename(dict(d), addresses_from="old.example.co.il")
    assert a.load("mover")["addresses_from"] == ["old.example.co.il", "mid.example.co.il"], \
        "every domain the addresses may still be on is kept, once each (a second rename before they moved)"
    office, scripts, said, runs, logins = a.load("mover"), {}, [], [], []
    real = converge.exec_on, converge.step_login, converge.step_run, converge.start_detached, converge.wait_detached
    answers = {"old.example.co.il": "RC=0\nCHANGED=1", "mid.example.co.il": "RC=1"}
    try:
        converge.step_login = lambda o, c, e: logins.append(1) or {"summary": "login refreshed", "warnings": ["w1"]}
        converge.step_run = lambda o, c, e: runs.append(1) or {"summary": "ran"}
        converge.exec_on = lambda m, cmd, t=0: {"code": 0, "stdout": ""}          # the verb is there
        converge.start_detached = lambda o, name, script, secret=False: scripts.__setitem__(name, script)

        def waited(o, name, emit, limit, every=8.0):
            out = ("[bbox] [n8n] sign-in addresses moved: admin\n[bbox] plane: rename-address hook FAILED\n"
                   "  detail of the failure\n" + next(v for k, v in answers.items() if k in scripts[name]) + "\n")
            for ln in out.splitlines():
                emit(ln)
            return out
        converge.wait_detached = waited
        res = converge.step_accounts(office, {}, said.append)
        assert all("rename-address: second pass" in s and "RC=" in s for s in scripts.values()), \
            "the detached script keeps the verdict pass and the facts"
        assert any("mid.example.co.il" in w for w in res["warnings"]), "an app that refused is a warning, not a stop"
        assert a.load("mover")["addresses_from"] == ["mid.example.co.il"], "the domain that moved is forgotten, the other kept"
        assert runs == [1] and logins == [1], "what changed is run again, and the login is read again even on a refusal"
        assert any("hook FAILED" in s for s in said) and "אזהרה: w1" in said, said
        answers["mid.example.co.il"] = "RC=0"                                   # nothing written: no restart
        res = converge.step_accounts(a.load("mover"), {}, said.append)
        assert "addresses_from" not in a.load("mover") and res["warnings"] == ["w1"] and runs == [1], (res, runs)
        assert "אין" in converge.step_accounts(a.load("mover"), {}, said.append)["summary"], "then nothing to move"
        converge._forget_rename(dict(d), addresses_from="old.example.co.il")
        converge.wait_detached = lambda o, name, emit, limit, every=8.0: "[bbox] error: something died early\n"
        try:
            converge.step_accounts(a.load("mover"), {}, said.append)
            assert False, "a verb that never said how it ended fails the step"
        except converge.StepFailed:
            assert len(logins) == 3, f"…and the login is still read again ({len(logins)} reads: two runs, this one)"
        converge.exec_on = lambda m, cmd, t=0: {"code": 1, "stdout": ""}          # code without the verb
        res = converge.step_accounts(a.load("mover"), {}, said.append)
        assert "FPG-34" in res["warnings"][0] and a.load("mover").get("addresses_from"), \
            "code without the verb is a warning that keeps the domain, never a stopped converge"
        converge.exec_on = lambda m, cmd, t=0: {"code": 255, "stdout": ""}        # the machine did not answer
        try:
            converge.step_accounts(a.load("mover"), {}, said.append)
            assert False, "an unreachable machine is a failure"
        except converge.StepFailed:
            pass
    finally:
        (converge.exec_on, converge.step_login, converge.step_run, converge.start_detached,
         converge.wait_detached) = real


def test_an_apps_key_that_ends_in_a_line_break_is_refused():
    # DGO-622: `$` matched before the break and kept "drive\n" — which the state step then wrote on the
    # far machine as `set-state --app 'drive\n' --create`, a platform.state.yaml line in two halves.
    d, err = load().validate(dict(GOOD, apps={"drive\n": "enabled"}), None)
    assert d is None and err and "apps" in err, (d, err)


def _serve(serve_map):
    """(status, the `serve:` map as /api/link/serve STORED it) — the store and the render replaced."""
    a = load()
    stored = []
    a.cv.set_home_serve = lambda serve: stored.append(json.loads(json.dumps(serve))) or serve
    a.render_tunnel = lambda *args, **kwargs: {}
    answer = asyncio.run(a.api_link_serve(_Asked({"serve": serve_map})))
    return getattr(answer, "status_code", 200), (stored[-1] if stored else None)


def _identity(ident):
    status, stored = _serve({"bina-ds": {"port": 3080, "identity": ident}})
    return status, (stored["bina-ds"].get("identity") if stored else None)


def test_identity_to_is_stored_without_the_line_break_it_arrived_with():
    # DGO-622: the door writes `to` into the identity header, and "owner\n" passed `$` and was stored
    # as sent — a header line that ends early. Stripped, then asked serve.py's own rule, then stored.
    assert _identity({"to": "owner\n"}) == (200, {"to": "owner"})
    assert _identity({"to": "  owner@local "}) == (200, {"to": "owner@local"})


def test_identity_to_with_a_line_break_inside_it_is_refused_and_not_stored():
    assert _identity({"to": "owner\r\nX-Evil: 1"}) == (400, None)
    assert _identity({"to": "own\ner"}) == (400, None)


def test_identity_from_is_a_list_of_users_each_checked_like_to():
    # DGO-622: `from` was stored as sent — "guest\n" reached the peer, whose compiler then refused the
    # whole remote block — and a string was stored as its letters.
    assert _identity({"to": "owner", "from": [" guest\n", "akadmin"]}) == \
        (200, {"to": "owner", "from": ["guest", "akadmin"]})
    assert _identity({"to": "owner", "from": ["gu\nest"]}) == (400, None)
    assert _identity({"to": "owner", "from": "alice"}) == (400, None)


def test_a_serve_key_that_is_not_an_app_id_is_refused_and_not_stored():
    # DGO-624: a `serve:` key reaches the firewall's rule text (`# <app>` beside each accept), and a
    # line break in it was a rule line of its own.
    assert _serve({"bina-ds\nadd rule inet x y accept #": {"port": 3080, "agent_api_port": 3081}}) == (400, None)
    status, stored = _serve({"bina-ds": {"port": 3080}, "*": {}})
    assert status == 200 and set(stored) == {"bina-ds", "*"}, (status, stored)


def test_this_app_is_never_offered_to_give():
    # DGO-624: the list a person chooses what to give from is every app this office runs but this one
    names = [row["app"] for row in load()._PairPorts().publishable()]
    assert names == ["drive"], names


def _through_the_guard(method: str, headers: dict) -> tuple:
    """One request through the guard alone, as ASGI: (the status it answered, did the app run)."""
    a = load()
    ran, sent = [], []

    async def behind(scope, receive, send):
        ran.append(scope["method"])

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)
    scope = {"type": "http", "method": method, "path": "/api/link/serve",
             "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}
    asyncio.run(a._NoWritesFromALinkedOffice(behind)(scope, receive, send))
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
    return status, bool(ran)


def test_a_linked_office_writes_nothing_here():
    # DGO-624: the door writes `x-dgo-office` on every request it carries in; such a request never
    # reaches a route that writes — and a read, or this office's own write, is not stopped.
    a = load()
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert _through_the_guard(method, {"X-Dgo-Office": "vps1"}) == (403, False), method
    assert _through_the_guard("GET", {"X-Dgo-Office": "vps1"}) == (None, True)
    assert _through_the_guard("POST", {}) == (None, True)
    guard = a._NoWritesFromALinkedOffice
    if "fastapi" in a.STOOD_IN:
        assert guard in sys.modules["fastapi"].FastAPI.added, "the guard must wrap the app"
    else:
        assert any(m.cls is guard for m in a.app.user_middleware), "the guard must wrap the app"


def test_through_the_app_a_linked_write_is_refused_and_nothing_is_stored():
    a = load()
    try:
        import httpx
    except ImportError:
        httpx = None
    if "fastapi" in a.STOOD_IN or httpx is None:
        return                     # asked of the guard alone above; this one needs the web stack
    stored = []
    a.cv.set_home_serve = lambda serve: stored.append(serve) or serve
    a.render_tunnel = lambda *args, **kwargs: {}
    linked = {"X-Dgo-Office": "vps1"}

    async def ask():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=a.app),
                                     base_url="http://dgo-extend") as c:
            serve = await c.post("/api/link/serve", headers=linked,
                                 json={"serve": {"bina-ds": {"port": 3080, "identity": {"to": "akadmin"}}}})
            office = await c.post("/api/office", headers=linked, json=GOOD)
            unpair = await c.delete("/api/pair/vps1", headers=linked)
            own = await c.post("/api/link/serve", json={"serve": {"bina-ds": {"port": 3080}}})
            return serve, office, unpair, own
    serve, office, unpair, own = asyncio.run(ask())
    assert (serve.status_code, office.status_code, unpair.status_code) == (403, 403, 403), \
        (serve.status_code, office.status_code, unpair.status_code)
    assert "מקושרת" in serve.json()["error"]
    assert own.status_code == 200 and len(stored) == 1, (own.status_code, stored)
    assert not list((Path(os.environ["DGO_STATE_DIR"]) / "dgo").glob("*.yaml"))


if __name__ == "__main__":
    loaded = load()
    print("app.py loaded" + (f" with {', '.join(loaded.STOOD_IN)} stood in for (not installed here)"
                             if loaded.STOOD_IN else " with its own web stack"))
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok    {name}")
            except Exception as e:                                         # noqa: BLE001
                failed += 1
                print(f"FAIL  {name}: {type(e).__name__}: {e}")
    sys.exit(1 if failed else 0)
