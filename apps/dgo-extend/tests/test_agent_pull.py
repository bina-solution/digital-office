#!/usr/bin/env python3
"""test_agent_pull — a linked office takes the credential of the agent it is given, over the link (DGO-1127).

    python3 apps/dgo-extend/tests/test_agent_pull.py      # or: python3 -m pytest apps/dgo-extend/tests/test_agent_pull.py

The serving office's converge used to PUSH `dgo_link-serve-<office>-<app>-agent` into the peer's vault
over ssh, so a pairing (no ssh either way) and an office with no sshd (the HP) handed over nothing, and
`bbox agent --office hp-laptop` was a 401 from every office. Now the peer asks for it on the link
listener (`app.api_link_agent`) and keeps it (`projection.pull_agents`):

  · the listener answers only the office its own door names, and only a caller that presents the
    secret this office shares with that office — a container inside the office holds none;
  · only for an app that office is GIVEN with an agent door, read from the catalog it is shown;
  · the peer writes it under the name `bbox agent` and `bbox remote` look up, asks again an hour later
    (a re-minted token), and backs off for ten minutes when the peer did not give it.

Hermetic: the vault, the catalog and the link are replaced; app.py is loaded the way test_app_input
loads it (its web stack stood in where it is absent).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "apps/dgo-extend"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import links  # noqa: E402
import projection  # noqa: E402

SECRET = "s" * 64
AGENT = "a" * 64
CATALOG = {"office": "hp-laptop", "apps": [
    {"app": "bina-ds", "alias": "bina", "port": 3080, "api": {"port": 3081, "auth": "bearer:vault:bina-ds"}},
    {"app": "plane", "alias": "plane", "port": 80}]}


def _app():
    spec = importlib.util.spec_from_file_location("test_app_input", APP / "tests" / "test_app_input.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper.load()


#: Where the link proxy speaks from on the serving office's network (`app._link_proxy_addresses`).
PROXY = "172.18.0.7"


class _Req:
    def __init__(self, headers: dict, came: str = PROXY):
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.client = type("Client", (), {"host": came})()


def _status(answer) -> int:
    return getattr(answer, "status_code", 200)


def _serving(monkey: dict):
    """app.py as the HP: its home, the catalog it shows macbook, its vault."""
    app = _app()
    import os
    saved = {"home": app.cv.home_office, "cat": app.build_catalog, "pairs": links.pair_tokens,
             "agent": app.cv.vault_agent_token, "proxy": app._link_proxy_addresses,
             "env": os.environ.get("DGO_SERVE_AGENTS")}
    app._link_proxy_addresses = monkey.get("proxy") or (lambda: {PROXY})
    # the HP as it is declared: everything given (`*`), the agent named in its .env (DGO_SERVE_AGENTS)
    os.environ["DGO_SERVE_AGENTS"] = monkey.get("agents", "bina-ds")
    home = {"id": "hp-laptop", "label": {"he": "HP", "en": "HP"}, "serve": monkey.get("serve", {"*": {}})}
    app.cv.home_office = lambda: home
    app.build_catalog = lambda now=None, office="": CATALOG if office == "macbook" else {"apps": []}
    links.pair_tokens = lambda home, peer: [("dgo_link-macbook", SECRET)] if (home, peer) == ("hp-laptop", "macbook") else []
    app.cv.vault_agent_token = monkey.get("agent_token") or (lambda service: AGENT if service == "bina-ds" else "")
    return app, saved


def _restore(app, saved):
    app.cv.home_office, app.build_catalog = saved["home"], saved["cat"]
    links.pair_tokens, app.cv.vault_agent_token = saved["pairs"], saved["agent"]
    app._link_proxy_addresses = saved["proxy"]
    import os
    if saved["env"] is None:
        os.environ.pop("DGO_SERVE_AGENTS", None)
    else:
        os.environ["DGO_SERVE_AGENTS"] = saved["env"]


def test_an_agent_given_only_under_the_wildcard_hands_no_token():
    # The king's rule (DGO-1127): `*` shares the agent's screen; its token goes only where the serving
    # office NAMED the agent — by hand in `serve:`, in `serve.only` for that office, or DGO_SERVE_AGENTS.
    asked = _Req({"x-dgo-office": "macbook", "authorization": f"Bearer {SECRET}"})
    for named, ok in (({"agents": ""}, False),
                      ({"agents": "", "serve": {"*": {}, "bina-ds": {}}}, True),
                      ({"agents": "", "serve": {"*": {}, "only": {"macbook": ["bina"]}}}, True),
                      ({"agents": "bina"}, True),
                      ({"agents": " drive , bina-ds "}, True),
                      ({"agents": "drive"}, False)):
        app, saved = _serving(named)
        try:
            r = app.api_link_agent("bina", asked)
            assert (_status(r) == 200) is ok, (named, _status(r), getattr(r, "body", r))
            if not ok:
                assert _status(r) == 403 and AGENT.encode() not in getattr(r, "body", b""), r
        finally:
            _restore(app, saved)


def test_the_listener_hands_the_agent_token_only_to_the_paired_office_with_its_secret():
    app, saved = _serving({})
    try:
        ok = app.api_link_agent("bina", _Req({"x-dgo-office": "macbook", "authorization": f"Bearer {SECRET}"}))
        assert _status(ok) == 200 and ok["token"] == AGENT and ok["port"] == 3081 and ok["app"] == "bina-ds", ok
        assert ok["office"] == "hp-laptop" and ok["label"] == "HP", ok        # the label is a name, not a dict
        # no office named by the door: a caller inside the office
        assert _status(app.api_link_agent("bina", _Req({"authorization": f"Bearer {SECRET}"}))) == 403
        # the door's office, but not the pair's secret
        assert _status(app.api_link_agent("bina", _Req({"x-dgo-office": "macbook",
                                                         "authorization": "Bearer " + "x" * 64}))) == 403
        assert _status(app.api_link_agent("bina", _Req({"x-dgo-office": "macbook"}))) == 403
        # the secret of ANOTHER pair does not open this one
        assert _status(app.api_link_agent("bina", _Req({"x-dgo-office": "vps1",
                                                         "authorization": f"Bearer {SECRET}"}))) == 403
        # an app with no agent door, and an app that office is not given
        assert _status(app.api_link_agent("plane", _Req({"x-dgo-office": "macbook",
                                                          "authorization": f"Bearer {SECRET}"}))) == 404
        assert _status(app.api_link_agent("mail", _Req({"x-dgo-office": "macbook",
                                                         "authorization": f"Bearer {SECRET}"}))) == 404
    finally:
        _restore(app, saved)


def test_a_container_inside_the_office_is_refused_whatever_it_writes():
    # It can write `x-dgo-office`, and it can read the pair's secret out of the vault (instance
    # secrets are not gated): only the link proxy's own address is believed (the second reader, #1).
    app, saved = _serving({})
    try:
        forged = _Req({"x-dgo-office": "macbook", "authorization": f"Bearer {SECRET}"}, came="172.18.0.42")
        assert _status(app.api_link_agent("bina", forged)) == 403
        # a proxy address that cannot be resolved refuses everyone, never "anyone"
        app._link_proxy_addresses = lambda: set()
        assert _status(app.api_link_agent("bina", _Req({"x-dgo-office": "macbook",
                                                         "authorization": f"Bearer {SECRET}"}))) == 403
    finally:
        _restore(app, saved)


def test_a_vault_that_fails_is_a_503_never_a_wrong_secret():
    app, saved = _serving({})
    try:
        def down(home, peer):
            raise links.LinkError("כספת האישורים אינה זמינה", 0)
        links.pair_tokens = down
        r = app.api_link_agent("bina", _Req({"x-dgo-office": "macbook", "authorization": f"Bearer {SECRET}"}))
        assert _status(r) == 503, r.body
    finally:
        _restore(app, saved)


def test_a_token_the_vault_cannot_read_is_a_503_with_the_vaults_sentence():
    def refuse(service):
        raise links.LinkError("כספת האישורים השיבה 403: only dgo-extend")
    app, saved = _serving({"agent_token": refuse})
    try:
        r = app.api_link_agent("bina", _Req({"x-dgo-office": "macbook", "authorization": f"Bearer {SECRET}"}))
        assert _status(r) == 503 and b"only dgo-extend" in r.body, r.body
    finally:
        _restore(app, saved)


class _Cv:
    """converge as far as pull_agents reads it: the instance name, and one call over the link."""

    def __init__(self, answers):
        self.answers, self.asked = list(answers), []

    @staticmethod
    def agent_instance(office, app):
        import converge
        return converge.agent_instance(office, app)

    def _http_auth(self, method, url, token, timeout=30):
        self.asked.append((method, url, token))
        return self.answers.pop(0)


def _consuming(have=None):
    stored = dict(have or {})
    saved = (links.pair_tokens, links.put)
    links.pair_tokens = lambda home, peer: [("dgo_link-hp-laptop", SECRET)] if (home, peer) == ("macbook", "hp-laptop") else []

    def put(instance):
        changed = stored.get(instance["id"]) != instance["secret"]["token"]
        stored[instance["id"]] = instance["secret"]["token"]
        put.last = instance
        return changed
    links.put = put
    projection._agent_pulls.clear()
    return stored, saved


def test_the_peer_keeps_it_under_the_name_bbox_agent_looks_for_and_asks_again_an_hour_later():
    stored, saved = _consuming()
    try:
        cv = _Cv([{"office": "hp-laptop", "label": "HP", "app": "bina-ds", "alias": "bina",
                   "port": 3081, "token": AGENT}] * 2)
        url = "http://dgo-net:9405/api/link/catalog"
        got = projection.pull_agents(cv, {"id": "macbook"}, "hp-laptop", CATALOG, url, address="10.79.5.1", now=1000)
        iid = "dgo_link-serve-hp-laptop-bina-ds-agent"
        assert got == {"bina-ds": {"instance": iid, "ok": True, "changed": True}}, got
        assert stored == {iid: AGENT} and cv.asked == [("GET", "http://dgo-net:9405/api/link/agent/bina", SECRET)]
        sec = links.put.last["secret"]
        assert (sec["office"], sec["peer"], sec["address"], sec["port"]) == ("hp-laptop", "macbook", "10.79.5.1", 3081)
        assert links.put.last["account_hint"].startswith("macbook->hp-laptop"), links.put.last  # unlink revokes it
        # inside the hour: not asked
        assert projection.pull_agents(cv, {"id": "macbook"}, "hp-laptop", CATALOG, url, now=1000 + 60) == {}
        assert len(cv.asked) == 1
        # after it: asked, and an unchanged token is not rewritten
        again = projection.pull_agents(cv, {"id": "macbook"}, "hp-laptop", CATALOG, url,
                                       now=1000 + projection.AGENT_PULL_SECONDS)
        assert again["bina-ds"]["ok"] and len(cv.asked) == 2
    finally:
        links.pair_tokens, links.put = saved


def test_a_peer_that_does_not_give_it_is_asked_again_in_ten_minutes_and_says_why():
    stored, saved = _consuming()
    try:
        cv = _Cv([{"error": "not found", "_status": 404}, {"_status": 0, "error": "URLError: timed out"}])
        url = "http://dgo-net:9405/api/link/catalog"
        got = projection.pull_agents(cv, {"id": "macbook"}, "hp-laptop", CATALOG, url, now=1000)
        assert not got["bina-ds"]["ok"] and "HTTP 404" in got["bina-ds"]["reason"] and stored == {}, got
        assert projection.pull_agents(cv, {"id": "macbook"}, "hp-laptop", CATALOG, url, now=1000 + 60) == {}
        late = projection.pull_agents(cv, {"id": "macbook"}, "hp-laptop", CATALOG, url,
                                      now=1000 + projection.AGENT_RETRY_SECONDS)
        assert not late["bina-ds"]["ok"] and "HTTP 0" in late["bina-ds"]["reason"] and stored == {}, late
    finally:
        links.pair_tokens, links.put = saved


def test_no_pair_secret_and_no_agent_door_ask_nothing():
    stored, saved = _consuming()
    try:
        cv = _Cv([])
        url = "http://dgo-net:9406/api/link/catalog"
        none = projection.pull_agents(cv, {"id": "macbook"}, "fireplace", CATALOG, url, now=1000)
        assert none["*"]["ok"] is False and cv.asked == [], none
        assert projection.pull_agents(cv, {"id": "macbook"}, "hp-laptop",
                                      {"apps": [CATALOG["apps"][1]]}, url, now=1000) == {}
    finally:
        links.pair_tokens, links.put = saved


def test_a_peer_with_no_pair_secret_here_is_not_asked_of_the_vault_every_pass():
    stored, saved = _consuming()
    try:
        asked = []
        links.pair_tokens = lambda home, peer: asked.append(peer) or []
        url = "http://dgo-net:9406/api/link/catalog"
        projection.pull_agents(_Cv([]), {"id": "macbook"}, "fireplace", CATALOG, url, now=1000)
        assert projection.pull_agents(_Cv([]), {"id": "macbook"}, "fireplace", CATALOG, url, now=1060) == {}
        assert asked == ["fireplace"], asked                      # one read, then the back-off holds
    finally:
        links.pair_tokens, links.put = saved


def test_a_stale_secret_is_followed_by_the_next_one_the_vault_holds():
    stored, saved = _consuming()
    try:
        links.pair_tokens = lambda home, peer: [("dgo_link-hp-laptop", "o" * 64), ("dgo_link-macbook-hp-laptop-use", SECRET)]
        cv = _Cv([{"error": "not the pair's secret", "_status": 403},
                  {"office": "hp-laptop", "label": "HP", "port": 3081, "token": AGENT}])
        got = projection.pull_agents(cv, {"id": "macbook"}, "hp-laptop", CATALOG,
                                     "http://dgo-net:9405/api/link/catalog", now=1000)
        assert got["bina-ds"]["ok"] and [t for _m, _u, t in cv.asked] == ["o" * 64, SECRET], (got, cv.asked)
    finally:
        links.pair_tokens, links.put = saved


def test_an_answer_of_the_wrong_shape_fails_that_app_and_never_the_pass():
    stored, saved = _consuming()
    try:
        cv = _Cv([["not", "an", "object"]])
        got = projection.pull_agents(cv, {"id": "macbook"}, "hp-laptop", CATALOG,
                                     "http://dgo-net:9405/api/link/catalog", now=1000)
        assert got["bina-ds"]["ok"] is False and stored == {}, got
        cv = _Cv([{"token": AGENT, "port": "not a port"}])
        got = projection.pull_agents(cv, {"id": "macbook"}, "hp-laptop", CATALOG,
                                     "http://dgo-net:9405/api/link/catalog", now=1000 + projection.AGENT_RETRY_SECONDS)
        assert got["bina-ds"]["ok"] is False and "ValueError" in got["bina-ds"]["reason"], got
    finally:
        links.pair_tokens, links.put = saved


def test_an_agent_the_serving_office_stopped_naming_is_dropped_here_too():
    # A copy taken before the rule (or under `*`) must not stay usable here once the serving office
    # answers "not named" — and that answer is not a stale secret, so no other secret is tried.
    stored, saved = _consuming({"dgo_link-serve-hp-laptop-bina-ds-agent": AGENT})
    real_forget = links.forget
    gone = []
    links.forget = lambda iid, office: gone.append((iid, office)) or True
    try:
        links.pair_tokens = lambda home, peer: [("dgo_link-hp-laptop", SECRET), ("dgo_link-macbook-hp-laptop-use", "o" * 64)]
        cv = _Cv([{"error": "only under *", "code": "not_named", "_status": 403}])
        got = projection.pull_agents(cv, {"id": "macbook"}, "hp-laptop", CATALOG,
                                     "http://dgo-net:9405/api/link/catalog", now=1000)
        assert got["bina-ds"]["dropped"] is True and len(cv.asked) == 1, (got, cv.asked)
        assert gone == [("dgo_link-serve-hp-laptop-bina-ds-agent", "hp-laptop")], gone
    finally:
        links.forget = real_forget
        links.pair_tokens, links.put = saved


def test_forget_removes_only_a_row_of_the_office_it_names():
    real = links._call
    rows = {"dgo_link-serve-hp-laptop-bina-ds-agent": {"token": "h" * 64, "office": "hp"}}
    deleted = []

    def call(method, path, body=None, timeout=20):
        iid = path.split("/")[3]
        if method == "DELETE":
            deleted.append(iid)
            return {"ok": True}
        if iid in rows:
            return {"secret": rows[iid]}
        raise links.LinkError("כספת האישורים השיבה 404: unknown instance", 404)
    links._call = call
    try:
        assert links.forget("dgo_link-serve-hp-laptop-bina-ds-agent", "hp-laptop") is False and deleted == []
        assert links.forget("dgo_link-serve-hp-laptop-bina-ds-agent", "hp") is True and deleted == [
            "dgo_link-serve-hp-laptop-bina-ds-agent"]
        assert links.forget("dgo_link-serve-vps1-bina-ds-agent", "vps1") is False
    finally:
        links._call = real


def test_a_pair_unpaired_while_it_was_asked_is_not_written_and_its_pulls_are_forgotten():
    stored, saved = _consuming()
    try:
        calls = []

        def pairs(home, peer):
            calls.append(peer)
            return [("dgo_link-hp-laptop", SECRET)] if len(calls) == 1 else []     # gone before the write
        links.pair_tokens = pairs
        cv = _Cv([{"office": "hp-laptop", "port": 3081, "token": AGENT}])
        got = projection.pull_agents(cv, {"id": "macbook"}, "hp-laptop", CATALOG,
                                     "http://dgo-net:9405/api/link/catalog", now=1000)
        assert not got["bina-ds"]["ok"] and "gone" in got["bina-ds"]["reason"] and stored == {}, got
        assert ("hp-laptop", "bina-ds") in projection._agent_pulls
        projection.forget_agents("hp-laptop")
        assert ("hp-laptop", "bina-ds") not in projection._agent_pulls
    finally:
        links.pair_tokens, links.put = saved


def test_the_vault_writer_never_replaces_another_offices_credential_and_a_failing_vault_raises():
    real = links._call
    rows = {"dgo_link-serve-hp-laptop-bina-ds-agent": {"token": "h" * 64, "office": "hp-laptop"}}

    def call(method, path, body=None, timeout=20):
        iid = path.split("/")[3] if path.startswith("/api/instances/") else ""
        if method == "GET" and iid in rows:
            return {"secret": rows[iid]}
        if method == "GET":
            raise links.LinkError("כספת האישורים השיבה 404: unknown instance", 404)
        return {"ok": True}
    links._call = call
    try:
        # `hp` + `laptop-bina-ds` names hp-laptop's row (the second reader, #2)
        try:
            links.put({"id": "dgo_link-serve-hp-laptop-bina-ds-agent",
                       "secret": {"token": "x" * 64, "office": "hp"}})
            raise AssertionError("another office's row was replaced")
        except links.LinkError as e:
            assert "hp-laptop" in str(e), e
        assert links.pair_tokens("macbook", "vps1") == []                     # every name a 404: no pair
        links._call = lambda *a, **k: (_ for _ in ()).throw(links.LinkError("כספת האישורים אינה זמינה", 0))
        try:
            links.pair_tokens("macbook", "vps1")
            raise AssertionError("a vault that is down read as 'no pair'")
        except links.LinkError:
            pass
    finally:
        links._call = real


def test_the_readers_take_an_agent_credential_only_for_the_office_its_secret_names():
    # `hp` + `laptop-bina-ds` writes `dgo_link-serve-hp-laptop-bina-ds-agent` first: `bbox agent` and
    # `bbox remote` asked for hp-laptop must not take hp's token, or its address (the second reader).
    sys.path.insert(0, str(ROOT / "scripts"))
    from bbox_agent import client
    import remote
    claimed = {"id": "dgo_link-serve-hp-laptop-bina-ds-agent",
               "secret": {"token": "h" * 64, "office": "hp", "label": "HP small", "app": "laptop-bina-ds",
                          "address": "10.79.9.1", "port": 3081}}
    real_rows = client._vault_instances
    client._vault_instances = lambda: [claimed]
    try:
        assert client._vault_provider("hp-laptop") is None
        assert client._vault_provider("hp")["served_by"] == "hp"            # its own office still finds it
    finally:
        client._vault_instances = real_rows
    real_http, real_url = remote.http, remote.vault_url
    remote.vault_url = lambda: "http://connections:8990"
    remote.http = lambda method, url, timeout=30: (200, {}, json.dumps({"secret": claimed["secret"]}).encode())
    try:
        try:
            remote.vault_token([claimed["id"]], "hp-laptop")
            raise AssertionError("bbox remote took hp's token for hp-laptop")
        except remote.RemoteError as e:
            assert "holds the credential of hp" in e.message, e.message
        assert remote.vault_token([claimed["id"]], "hp")[0] == "h" * 64
    finally:
        remote.http, remote.vault_url = real_http, real_url


def test_the_host_door_says_when_a_caller_is_not_its_peer_and_still_carries_it_while_staged():
    import socket
    import tempfile
    import threading
    import time
    import types
    import converge
    base = Path(tempfile.mkdtemp(prefix="door-"))
    door_mod = types.ModuleType("link_door")
    door_mod.__file__ = str(base / "link-door.py")
    exec(compile(converge.REMOTE_DOOR, "link-door.py", "exec"), door_mod.__dict__)
    door_mod.SOCKETS = base
    said = []
    door_mod.log = said.append
    up = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    up.bind(str(base / "macbook-2-door.sock"))
    up.listen(1)
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    door = {"bind": "127.0.0.1", "port": port, "socket": "macbook-2-door", "clients": ["10.79.2.2"]}
    threading.Thread(target=door_mod.serve, args=(door,), daemon=True).start()
    for _ in range(50):
        if any("listening" in s for s in said):
            break
        time.sleep(0.05)
    c = socket.create_connection(("127.0.0.1", port), timeout=5)
    up.settimeout(5)
    carried, _ = up.accept()                                      # staged: carried, not refused
    c.close()
    carried.close()
    up.close()
    for _ in range(50):
        if any("would be refused" in s for s in said):
            break
        time.sleep(0.05)
    assert any("127.0.0.1 is not this door's peer (10.79.2.2)" in s for s in said), said


def test_a_host_off_the_office_network_reaches_the_link_through_a_relay():
    # The Mac host cannot resolve `bina.hp-laptop` nor route 10.79.5.1 (DGO-1127, measured): `bbox agent
    # --office` is carried through a process on the office network. Here that process is this python,
    # and the far end is a local HTTP server — the bytes take the relay's real path both ways.
    import http.server
    import threading
    import urllib.request
    sys.path.insert(0, str(ROOT / "scripts"))
    from bbox_agent import client

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"ok": True, "path": self.path}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    real = client._relay_cmd
    client._relay_cmd = lambda name, port: [sys.executable, "-c", client._RELAY_PIPE, name, str(port)]
    try:
        url = client._relay("127.0.0.1", srv.server_address[1])
        assert url.startswith("http://127.0.0.1:") and client._relay("127.0.0.1", srv.server_address[1]) == url
        for _ in range(2):                                   # one process per connection, twice
            with urllib.request.urlopen(url + "/v1/health", timeout=20) as r:
                assert json.loads(r.read()) == {"ok": True, "path": "/v1/health"}
        import time
        for _ in range(100):                                 # …and each is gone once its connection is
            if not client._live:
                break
            time.sleep(0.05)
        assert not client._live, client._live
        assert client._relay("bina.hp-laptop; rm -rf /", 3081) == ""   # never a word a shell would split
        assert client._relay("bina.hp-laptop\n", 3081) == ""           # nor a line a shell would end
        # A hop that fails says why, as an answer — not "the connection dropped".
        client._relay_cmd = lambda name, port: [sys.executable, "-c",
                                                "import sys;sys.stderr.write('no dgo-extend of this office is running');sys.exit(1)"]
        dead = client._relay("bina.vps1", 10032)
        try:
            urllib.request.urlopen(dead + "/v1/health", timeout=20)
            raise AssertionError("a failed relay answered 200")
        except urllib.error.HTTPError as e:
            assert e.code == 502 and b"no dgo-extend of this office is running" in e.read(), e
    finally:
        client._relay_cmd = real
        srv.shutdown()


def test_the_pair_secret_is_found_by_exact_name_for_an_office_whose_id_has_a_dash():
    names = links.pair_names("macbook", "hp-laptop")
    assert names[0] == "dgo_link-hp-laptop", names
    assert "dgo_link-macbook-hp-laptop-both" in names and "dgo_link-hp-laptop-macbook-use" in names, names


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    bad = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as e:                                # noqa: BLE001 — report every test
            bad += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")
    print(f"agent_pull: {len(tests)} test(s), {len(tests) - bad} pass, {bad} fail")
    raise SystemExit(1 if bad else 0)
