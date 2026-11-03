"""The oracle of dgo's control plane: app-management's app.py — unmodified, imported from its file the
way its own tests import it — asked the requests the Go tests ask `dgo be-child control`.

    python oracle.py client <app.py> <repo>   one request per line on stdin, one answer per line on stdout:
                                              {method, path, headers: [[k, v], …], body, content_type} →
                                              {status, content_type, body}  (bodies base64) — Flask's test
                                              client, in-process; the caller may rewrite the fixture
                                              between two requests, as app.py reads its files on each
    python oracle.py serve <app.py> <repo>    the same app, live on 127.0.0.1:<a free port>; the port is
                                              the first line of stdout
    python oracle.py routes <gate.py>         G85's own enumeration of app.py's routes, as JSON

The stubs are the ones app.py's own tests use (test_bringup.py, test_catalog_reads.py): no docker
engine (`docker_sdk` is None, `_container_index` answers None) and no network (`_auth_blockers`
answers {}). REPO_DIR is a fixture tree carrying the compiler (platform/manager/*.py), so office-get
and remote-get run for real against it — by THIS interpreter: app.py names `python3`, which a
Windows host may not have.
"""
import base64
import importlib.util
import json
import os
import subprocess
import sys


class Clock:
    """app.py's `time`, with time() pinned when a request says `now` — the conditions' lastTransitionTime
    is the wall clock, which the Go side is handed the same reading of."""

    def __init__(self, real):
        self.real, self.at = real, None

    def time(self):
        return self.real.time() if self.at is None else self.at

    def __getattr__(self, name):
        return getattr(self.real, name)


def load(app_py, repo):
    os.environ["REPO_DIR"] = repo
    spec = importlib.util.spec_from_file_location("appmgmt_oracle", app_py)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["appmgmt_oracle"] = mod
    spec.loader.exec_module(mod)
    mod.time = Clock(mod.time)
    mod.docker_sdk = None
    mod._container_index = lambda: None
    mod._auth_blockers = lambda: {}
    real = subprocess.run

    def run(args, *a, **kw):
        if isinstance(args, list) and args[:1] == ["python3"]:
            args = [sys.executable, *args[1:]]
        return real(args, *a, **kw)

    subprocess.run = run
    return mod


def client(mod):
    c = mod.app.test_client()
    while True:
        line = sys.stdin.readline()
        if not line:
            return
        q = json.loads(line)
        if q.get("now") is not None:
            mod.time.at = q["now"]
        r = c.open(q["path"], method=q["method"], headers=[tuple(h) for h in q.get("headers") or []],
                   data=base64.b64decode(q.get("body") or ""), content_type=q.get("content_type"))
        print(json.dumps({"status": r.status_code, "content_type": r.headers.get("Content-Type") or "",
                          "body": base64.b64encode(r.get_data()).decode("ascii")}), flush=True)


def serve(mod):
    from werkzeug.serving import make_server
    srv = make_server("127.0.0.1", 0, mod.app, threaded=True)
    print(srv.server_port, flush=True)
    srv.serve_forever()


def routes(gate_py):
    spec = importlib.util.spec_from_file_location("link_write_guard_lint", gate_py)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    _src, tree = gate.parse()
    header = gate.header_value(tree)
    json.dump([{"func": r["func"], "rule": r["rule"], "methods": r["methods"],
                "guarded": gate.refuses_link(r["node"], header) is not None}
               for r in gate.routes(tree)], sys.stdout)


if __name__ == "__main__":
    if sys.argv[1] == "routes":
        routes(sys.argv[2])
    else:
        {"client": client, "serve": serve}[sys.argv[1]](load(sys.argv[2], sys.argv[3]))
