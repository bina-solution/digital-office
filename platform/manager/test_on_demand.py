"""Unit tests for on-demand routes (DGO-1270) in the compiler's routing render.

A route that declares `on_demand: {idle: 2h}` runs only while it is used: autoheal stops its service
after the window (the label below), and the waker — app-management — carries the route's routers again
at priority 1, so a stopped app's address still answers and opening it starts it. What is held here:
the labels are exactly the route's own routers, behind the same sign-in, with only the service, the
priority and one header middleware changed; nothing is emitted where no waker runs (a stopped app would
then be unreachable); a window that is not a duration of 5 minutes to 30 days is refused.

Every catalog here is synthetic: no manifests are read, nothing is written or started.

Run: python -m pytest platform/manager/test_on_demand.py -q   (or python3 platform/manager/test_on_demand.py)
"""
import importlib.util
import pathlib
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_on_demand", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_on_demand"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()
WAKER = {"routing": [{"host": "apps", "port": 8080, "auth": "sso", "service": "app-management"}]}


def app(host, port, auth="sso", **on_demand):
    route = {"host": host, "port": port, "service": host, "auth": auth}
    if on_demand:
        route["on_demand"] = on_demand
    return {"routing": [route]}


def services(cat, order):
    return yaml.safe_load(rc.render_routing(cat, order))["services"]


def refused(idle):
    try:
        services({"app-management": WAKER, "cad": app("cad", 3000, idle=idle)}, ["app-management", "cad"])
    except SystemExit as e:
        return str(e)
    return None


def test_an_on_demand_route_is_labelled_with_its_window_and_woken_by_the_waker():
    svcs = services({"app-management": WAKER, "cad": app("cad", 3000, idle="2h")}, ["app-management", "cad"])
    cad, waker = svcs["cad"]["labels"], svcs["app-management"]["labels"]
    assert "binaos.on-demand.idle=7200" in cad and "binaos.on-demand.app=cad" in cad
    own = {l.split("=", 1)[0]: l.split("=", 1)[1] for l in cad}
    woke = {l.split("=", 1)[0]: l.split("=", 1)[1] for l in waker}
    for suffix in ("local", "http", "https"):
        p, w = f"traefik.http.routers.cad-{suffix}", f"traefik.http.routers.cad-wake-{suffix}"
        assert woke[f"{w}.rule"] == own[f"{p}.rule"] and woke[f"{w}.entrypoints"] == own[f"{p}.entrypoints"]
        assert woke[f"{w}.priority"] == "1" and woke[f"{w}.service"] == "dgo-wake"
        assert woke[f"{w}.middlewares"] == "authentik@file,cad-wake"          # the sign-in FIRST
    assert woke["traefik.http.routers.cad-wake-https.tls.certresolver"] == own["traefik.http.routers.cad-https.tls.certresolver"]
    assert woke["traefik.http.middlewares.cad-wake.headers.customrequestheaders.X-Dgo-Wake"] == "cad"
    assert woke["traefik.http.services.dgo-wake.loadbalancer.server.port"] == "8080"
    assert not any(".priority=" in l for l in cad)                             # the app's own routers keep theirs


def test_two_on_demand_apps_share_one_wake_service():
    cat = {"app-management": WAKER, "cad": app("cad", 3000, idle="2h"), "asr": app("asr", 8000, idle="30m")}
    waker = services(cat, ["app-management", "cad", "asr"])["app-management"]["labels"]
    assert sum(l.startswith("traefik.http.services.dgo-wake.") for l in waker) == 1
    assert "traefik.http.middlewares.asr-wake.headers.customrequestheaders.X-Dgo-Wake=asr" in waker


def test_with_no_waker_nothing_sleeps():
    svcs = services({"app-management": WAKER, "cad": app("cad", 3000, idle="2h")}, ["cad"])
    assert not any(l.startswith("binaos.on-demand") for l in svcs["cad"]["labels"])
    assert "app-management" not in svcs


def test_a_route_with_no_sign_in_is_woken_with_the_header_alone():
    waker = services({"app-management": WAKER, "pub": app("pub", 80, auth="none", idle="1h")},
                     ["app-management", "pub"])["app-management"]["labels"]
    assert "traefik.http.routers.pub-wake-https.middlewares=pub-wake" in waker


def test_a_route_that_is_not_on_demand_renders_as_before():
    cat = {"app-management": WAKER, "cad": app("cad", 3000)}
    svcs = services(cat, ["app-management", "cad"])
    assert svcs["cad"]["labels"] == rc.routing_labels("cad", cat["cad"]["routing"][0])
    assert not any("wake" in l for l in svcs["app-management"]["labels"])


def test_a_window_that_is_not_a_duration_of_5_minutes_to_30_days_is_refused():
    for bad in ("4m", "299s", "31d", "721h", "", "90", "2h\n", "0h", "02h", "2 h", "9999999999h", "٢h"):
        said = refused(bad)
        assert said and "routing.on_demand.idle" in said and repr(bad) in said, (bad, said)
    for good in ("5m", "300s", "2h", "720h"):
        assert refused(good) is None, good


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
