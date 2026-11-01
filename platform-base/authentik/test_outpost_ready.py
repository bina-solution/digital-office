#!/usr/bin/env python3
"""What `outpost-ready.py` calls SERVED, and which hosts it asks about, against a sign-in server
this test plays itself.

    python3 platform-base/authentik/test_outpost_ready.py

The probe is the one witness three things rely on: the sentinel's health, the bootstrap gate, and
the hook that decides whether to restart the sign-in server. Its verdict is one status code per
host, so the codes are what is tested: a 302 from an outpost that knows the host, a 404 from one
that does not — and the 502 a STARTING server gives every host alike, which used to count as
"served" and made a restarting office read as fully ready (hp-laptop, 2026-10-06: 21 seconds of it
in one re-creation of the server).

And WHICH hosts: the ones the compiled blueprint states (`context.gated_hosts`), read from the file
— so a host compiled a second ago is asked about before anybody has applied it, and no token, no
API and no remembered list stand between the probe and its question.
"""
import http.server
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import threading

HERE = pathlib.Path(__file__).resolve().parent
ANSWERS = {"known.t": 302, "open.t": 200, "refused.t": 403, "unknown.t": 404, "broken.t": 500,
           "ported.t:8080": 302}
MODE = {"starting": False}
ASKED = []


class _Outpost(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        host = self.headers.get("X-Forwarded-Host", "")
        ASKED.append(host)
        code = 502 if MODE["starting"] else ANSWERS.get(host, 404)
        self.send_response(code)
        if code == 302:
            self.send_header("Location", "http://sign-in.t/start")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_):
        pass


def _probe(server_url, blueprint):
    os.environ.update(AUTHENTIK_READY_SERVER=server_url, OUTPOST_HOSTS_BLUEPRINT=blueprint)
    spec = importlib.util.spec_from_file_location("outpost_ready", HERE / "outpost-ready.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Outpost)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    blueprint = os.path.join(tempfile.mkdtemp(), "zz-generated-apps.yaml")
    probe = _probe(f"http://127.0.0.1:{srv.server_port}", blueprint)
    failed = []

    def check(name, got, want):
        ok = got == want
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        got {got!r}, want {want!r}"))
        if not ok:
            failed.append(name)

    def compiled(*hosts, line=None):
        """A blueprint as the compiler writes it, gating `hosts` (or with `line` in their place)."""
        with open(blueprint, "w", encoding="utf-8") as fh:
            fh.write("# GENERATED\nversion: 1\ncontext:\n"
                     + (line if line is not None else "  gated_hosts: " + json.dumps(list(hosts))) + "\n"
                     + '  authentik_external_host: !Format ["%s://%s/", !Env [AUTH_PROTOCOL, https], "auth.t"]\n'
                     + "entries:\n  - id: provider-x\n    attrs:\n      external_host: http://not-a-gated-host.t\n")

    check("a redirect to sign-in is a host the outpost knows", probe._served("known.t"), True)
    check("…and so is a page it lets through, or refuses", (probe._served("open.t"), probe._served("refused.t")), (True, True))
    check("a 404 is a host it does not know", probe._served("unknown.t"), False)
    check("a 5xx is not an answer about the host at all", probe._served("broken.t"), False)

    compiled("known.t", "open.t", "ported.t:8080")
    del ASKED[:]
    check("every host the blueprint gates is known: ready", probe._check()[0], "ready")
    check("…and those hosts, port and all, are exactly what the outpost was asked about",
          sorted(ASKED), ["known.t", "open.t", "ported.t:8080"])
    compiled("known.t", "unknown.t")
    state, served, missing, _why = probe._check()
    check("a host compiled a moment ago and not yet loaded: unserved, and it is named",
          (state, missing), ("unserved", ["unknown.t"]))

    MODE["starting"] = True
    compiled("known.t", "open.t")
    state, served, missing, _why = probe._check()
    check("a server that is still starting (502 for every host) serves NOTHING yet",
          (state, served), ("unserved", []))
    MODE["starting"] = False

    # nothing to ask about is "unknown" — a different fact from "a host is refused"
    for name, line in (("a blueprint from a compiler older than this probe", "  some_other_key: 1"),
                       ("a blueprint that gates no host", "  gated_hosts: []"),
                       ("a list this probe cannot read", "  gated_hosts: [known.t")):
        compiled(line=line)
        state, _s, _m, why = probe._check()
        check(f"{name}: unknown, with the reason", (state, bool(why)), ("unknown", True))
    os.remove(blueprint)
    state, _s, _m, why = probe._check()
    check("an office that was never compiled: unknown, and the file is named",
          (state, blueprint in why), ("unknown", True))

    compiled("known.t")
    srv.shutdown(); srv.server_close()
    check("a server that is not there serves nothing", probe._check()[0], "unserved")

    print(f"\n{len(failed)} failing")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
