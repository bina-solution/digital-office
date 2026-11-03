"""The enable/update frame gate (#63) against REAL answers: a local HTTP server that answers like the apps do
(X-Frame-Options DENY, CSP frame-ancestors variants, a sign-in redirect), judged through `framecheck.gate`
and through the CLI the update hook runs (`check <app|service> --phase update`: exit 3 = refuse).

Run: python -m pytest platform/manager/test_framecheck.py -q      (or: python platform/manager/test_framecheck.py)
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import framecheck  # noqa: E402

#: what each host answers (the Host header decides, as the edge routes)
ANSWERS = {
    "deny.office.test": (200, {"X-Frame-Options": "DENY"}),
    "csp-ok.office.test": (200, {"Content-Security-Policy": "frame-ancestors 'self' http://console.office.test",
                                 "X-Frame-Options": "DENY"}),
    "csp-none.office.test": (200, {"Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'"}),
    "csp-self.office.test": (200, {"Content-Security-Policy": "frame-ancestors 'self'"}),
    "signin.office.test": (302, {"Location": "http://auth.office.test/login?next=/"}),
    "plain.office.test": (200, {}),
    "tabdeny.office.test": (200, {"X-Frame-Options": "DENY"}),
}
EMBEDDED = {"/same/": (200, {"X-Frame-Options": "SAMEORIGIN"}), "/deny/": (200, {"X-Frame-Options": "DENY"})}
SEEN = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):                       # noqa: N802
        host = (self.headers.get("Host") or "").split(":")[0]
        SEEN.append((host, self.path, self.headers.get("Sec-Fetch-Dest")))
        if host == "embedsvc":
            code, hdrs = EMBEDDED.get(self.path, (404, {}))
        elif host == "deny.office.test" and self.path == "/hop":
            code, hdrs = 302, {"Location": "/"}
        else:
            code, hdrs = ANSWERS.get(host, (404, {}))
        self.send_response(code)
        for k, v in hdrs.items():
            self.send_header(k, v)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<!doctype html><title>app</title>" * 50)

    def log_message(self, *a):
        pass


class _Srv(ThreadingHTTPServer):
    allow_reuse_address = False      # Windows lets SO_REUSEADDR bind a port another test already listens on
    daemon_threads = True


def _server():
    for port in range(8951, 8960):
        try:
            srv = _Srv(("127.0.0.1", port), Handler)
        except OSError:
            continue
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv, port
    raise RuntimeError("no free port in 8951-8959")


SRV, PORT = _server()


def _app(root, aid, routing, compose_services=()):
    d = root / "apps" / aid
    d.mkdir(parents=True, exist_ok=True)
    (d / "app.json").write_text(json.dumps({"id": aid, "version": "1.2.3", "title": {"en": aid.title()},
                                            "routing": routing}), encoding="utf-8")
    if compose_services:
        (d / "docker-compose.yml").write_text(
            "services:\n" + "".join(f"  {s}:\n    image: x\n" for s in compose_services) + "networks:\n  n: {}\n",
            encoding="utf-8")


def _repo():
    root = Path(tempfile.mkdtemp(prefix="framecheck-"))
    env = {"DEPLOYMENT_DOMAIN": "office.test", "CONSOLE_BASE_URL": "console.office.test", "AUTH_PROTOCOL": "http"}
    for aid in ("deny", "csp-ok", "csp-none", "csp-self", "signin", "plain"):
        _app(root, aid, [{"host": aid, "module": {"external": True, "alias": aid, "name": aid}}],
             compose_services=(aid + "-web",))
        env[framecheck.base_url_env(aid)] = f"http://{aid}.office.test:{PORT}"
    _app(root, "tabdeny", [{"host": "tabdeny", "module": {"embed": False, "name": "t"}}])
    env["TABDENY_BASE_URL"] = f"http://tabdeny.office.test:{PORT}"
    _app(root, "embsame", [{"host": "embsame", "module": {"alias": "embsame", "url": f"http://embedsvc:{PORT}/same"}}])
    _app(root, "embdeny", [{"host": "embdeny", "module": {"alias": "embdeny", "url": f"http://embedsvc:{PORT}/deny"}}])
    _app(root, "outside", [{"host": "outside", "module": {"external": True, "alias": "outside"}}])
    env["OUTSIDE_BASE_URL"] = f"http://outside.elsewhere.test:{PORT}"
    (root / ".env").write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")
    return root


REPO = _repo()
os.environ["FRAMECHECK_CONNECT_TO"] = f"office.test=127.0.0.1,embedsvc=127.0.0.1,elsewhere.test=127.0.0.1"
for k in ("FRAME_GATE", "DEPLOYMENT_DOMAIN", "CONSOLE_BASE_URL", "AUTH_PROTOCOL"):
    os.environ.pop(k, None)


def _gate(aid, gate_mode, phase="enable", was=False):
    os.environ["FRAME_GATE"] = gate_mode
    try:
        _, m = framecheck.manifest_of(aid, REPO)
        return framecheck.gate(aid, m, phase, was_enabled=was, repo=REPO)
    finally:
        os.environ.pop("FRAME_GATE", None)


def test_an_app_answering_x_frame_options_deny_is_refused_at_a_first_enable_in_refuse_mode():
    res = _gate("deny", "refuse")
    t = res["targets"][0]
    assert (t["kind"], t["verdict"], t["status"]) == ("external", "refused", 200)
    assert res["refuse"] and "X-Frame-Options: DENY" in res["sentence"]
    assert "frame-ancestors 'self' http://console.office.test" in res["sentence"]
    assert "switched off again" in res["sentence"]
    assert ("deny.office.test", "/", "iframe") in SEEN              # asked as a frame asks, at its own host


def test_warn_is_the_default_it_records_and_says_so_and_stops_nothing():
    res = _gate("deny", "")
    assert res["mode"] == "warn" and res["verdict"] == "refused" and not res["refuse"]
    assert "FRAME_GATE=warn: kept" in res["sentence"]
    doc = json.loads((REPO / "data" / "platform" / "frame-checks.json").read_text(encoding="utf-8"))
    assert doc["deny"]["verdict"] == "refused" and doc["deny"]["version"] == "1.2.3"


def test_an_app_that_was_already_running_is_never_switched_off_by_a_re_enable():
    res = _gate("deny", "refuse", was=True)
    assert res["verdict"] == "refused" and not res["refuse"]
    assert "already running" in res["sentence"]


def test_an_update_of_a_refusing_app_is_refused_so_the_previous_image_goes_back():
    res = _gate("deny", "refuse", phase="update", was=True)
    assert res["refuse"] and "previous image was put back" in res["sentence"]


def test_csp_frame_ancestors_naming_the_console_wins_over_x_frame_options():
    res = _gate("csp-ok", "refuse")
    assert res["verdict"] == "ok" and not res["refuse"] and not res["sentence"]


def test_csp_none_and_csp_self_on_another_origin_are_refused():
    for aid, said in (("csp-none", "frame-ancestors 'none'"), ("csp-self", "frame-ancestors 'self'")):
        res = _gate(aid, "refuse")
        assert res["verdict"] == "refused" and res["refuse"], aid
        assert said in res["targets"][0]["why"], res["targets"][0]["why"]


def test_a_sign_in_redirect_is_not_the_apps_answer_so_it_is_unknown_and_passes():
    res = _gate("signin", "refuse")
    assert res["verdict"] == "unknown" and not res["refuse"]
    assert "auth.office.test" in res["targets"][0]["why"]


def test_an_app_that_says_nothing_about_framing_passes():
    assert _gate("plain", "refuse")["verdict"] == "ok"


def test_an_app_that_opens_in_a_tab_is_recorded_and_never_refused():
    res = _gate("tabdeny", "refuse")
    t = res["targets"][0]
    assert (t["kind"], t["verdict"], t["enforced"]) == ("tab", "refused", False)
    assert res["verdict"] == "none" and not res["refuse"]


def test_an_embedded_app_is_judged_as_the_consoles_own_origin_through_its_proxy():
    same, deny = _gate("embsame", "refuse"), _gate("embdeny", "refuse")
    assert same["targets"][0]["kind"] == "embedded" and same["verdict"] == "ok"
    assert deny["verdict"] == "refused" and deny["refuse"]


def test_an_address_outside_the_office_is_never_asked():
    n = len(SEEN)
    res = _gate("outside", "refuse")
    assert res["verdict"] == "unknown" and not res["refuse"] and len(SEEN) == n


def test_off_asks_nothing_and_records_nothing():
    n = len(SEEN)
    res = _gate("csp-none", "off")
    assert res["targets"] == [] and len(SEEN) == n


def _cli(*args, gate_mode="refuse"):
    env = dict(os.environ, FRAME_GATE=gate_mode, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, str(HERE / "framecheck.py"), *args, "--repo", str(REPO)],
                          capture_output=True, text=True, env=env, encoding="utf-8", timeout=60)


def test_the_update_hooks_cli_exits_3_to_refuse_and_0_to_keep():
    r = _cli("check", "deny", "--phase", "update")
    assert r.returncode == 3 and "REFUSED:" in r.stdout, r.stdout + r.stderr
    r = _cli("check", "deny-web", "--phase", "update")                   # a compose service of the app
    assert r.returncode == 3, r.stdout + r.stderr
    r = _cli("check", "deny", "--phase", "update", gate_mode="warn")
    assert r.returncode == 0 and "warning:" in r.stdout
    r = _cli("check", "csp-ok", "--phase", "update")
    assert r.returncode == 0 and "-> ok" in r.stdout
    r = _cli("check", "no-such-thing", "--phase", "update")
    assert r.returncode == 0 and "nothing to judge" in r.stdout


def test_the_selftest_passes():
    assert framecheck.selftest() == []


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    bad = 0
    for name, fn in tests:
        try:
            fn()
            print("ok  ", name)
        except Exception as e:                       # noqa: BLE001
            bad += 1
            print("FAIL", name, "-", type(e).__name__, e)
    print(f"{len(tests) - bad}/{len(tests)} passed")
    sys.exit(1 if bad else 0)
