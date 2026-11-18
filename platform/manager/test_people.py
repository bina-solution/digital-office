"""test_people — an app's `people: admins` reaches every door the compiler writes (DGO-1755).

    python3 -m pytest platform/manager/test_people.py -q

The Go twin (packaging/dgo/internal/compiler) is held to the same output by its render parity tests over the real
tree; this holds the Python side directly, on made-up apps, and the real manifests' admins.
"""
import importlib.util
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_people", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_people"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()


def _mw(labels):
    """router → its chain, the HSTS pin left out: on a server office the pin opens every https chain
    (DGO-1595), and what these tests ask is which sign-in comes first after it."""
    return {l.split(".")[3]: ",".join(m for m in l.split("=", 1)[1].split(",") if m != "hsts@file")
            for l in labels if ".middlewares=" in l and ".routers." in l}


def test_an_admins_app_is_signed_in_by_the_admins_middleware_on_every_router():
    route = {"host": "demo", "port": 80}
    mine = _mw(rc.routing_labels("demo", route, admins=True))
    theirs = _mw(rc.routing_labels("demo", route))
    assert mine and set(mine) == set(theirs)
    for name, chain in mine.items():
        assert chain.split(",")[0] == "authentik-admins@file", (name, chain)
        assert "authentik@file" not in chain.split(","), (name, chain)
    for name, chain in theirs.items():
        assert chain.split(",")[0] == "authentik@file", (name, chain)


def test_an_open_route_of_an_admins_app_stays_open():
    labels = rc.routing_labels("demo", {"host": "demo-hooks", "port": 80, "auth": "none"}, admins=True)
    assert not [l for l in labels if "authentik" in l], labels


def test_the_console_passthrough_of_an_admins_app_is_theirs_too():
    route = {"service": "demo", "port": 80, "auth": "sso", "emit_labels": False,
             "module": {"embed": True, "alias": "demo", "passthrough": [{"path": "/ws", "transport": "websocket"}]}}
    labels = rc.console_passthrough_labels("demo", route, {"host": "console"}, admins=True)
    chains = [l.split("=", 1)[1] for l in labels if ".middlewares=" in l]
    assert chains and all(c.split(",")[-1] == "authentik-admins@file" for c in chains), chains


def test_the_alias_file_says_who_opens_an_admins_app():
    module = {"url": "http://demo:80", "url_env": None}
    assert rc.app_base(module, {"people": "admins"}) == {"env": None, "default": "http://demo:80", "people": "admins"}
    assert rc.app_base(module, {}) == {"env": None, "default": "http://demo:80"}
    assert rc.app_base(module, {"people": "everyone"}) == {"env": None, "default": "http://demo:80"}


def test_the_offices_root_apps_say_admins_and_its_work_apps_do_not():
    def people(aid):
        for root in ("apps", "platform-base"):
            p = REPO / root / aid / "app.json"
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8")).get("people", "everyone")
        raise AssertionError(f"no app {aid}")
    for aid in ("computers", "app-management", "connections", "n8n", "security", "dgo-extend", "bina-ds",
                "bina-claude", "data-management", "browser42", "openhands", "machine", "containers", "portainer",
                "git", "telegram", "domains", "traefik"):
        assert people(aid) == "admins", aid
    for aid in ("drive", "meet", "project-pln", "examplem-io", "assets", "indox", "console", "notifications"):
        assert people(aid) == "everyone", aid
