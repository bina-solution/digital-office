#!/usr/bin/env python3
"""test_link_security — §9 of the pairing contract, as tests (DGO-49).

`ai/context/dgo-pairing-contract.md` §E writes down what a `kind: paired` office may READ and DO in
the office that holds its record, and each of its facts names the test that guards it. Four of those
claims were carried by prose and by one boundary check (`pair_contract.py`'s §9 block, which is about
the SERVING office's `serve:` map and nothing else). This file turns the rest into tests — one
function per claim, named after the claim — and every one asserts on the function the running system
uses, never on a re-implementation of it:

  1. **A paired office serves only what it declares.** `catalog.publishable`/`catalog.build` are the
     serving side's decision, and `link-proxy.py`'s `Door` is what APPLIES it per request: a name the
     office does not serve is refused by the door's own route table (`no-app`), and `{"*": {}}` — "my
     other office" — publishes the vault and machine plane while a serve that NAMES apps does not.
  2. **Identity crosses the link boundedly.** The door writes the catalog's mapped user for the app
     being reached and strips the peer's whole `X-authentik-*` family; on the consuming side the
     compiler puts this office's own `authentik@file` BEFORE the mapping, which is what makes a
     forged `X-authentik-username` irrelevant rather than trusted.
  3. **The tunnel/role model.** Direction is enforced in the rendered delivery plan: a link this
     office serves renders no rule that reaches back, every rule that reaches a peer names the peer's
     OWN tunnel address, and a peer that did not answer is written down as not answering (status,
     and what the console is handed) and never as healthy.
  4. **Secrets never leave the offering side.** The catalog is an allow-list over the registry, so a
     served app receives an identity mapping and a POINTER to the credential plane
     (`bearer:vault:<app>`) — never a secret; `identity.public()` and the pairing's own wire format
     carry public halves only.

One claim in §9 is NOT implemented in the code, and its test here is marked `xfail` with the code
path named — the one shape of a test that must not be quietly weakened:

  · the identity mapping's `from` half crosses the link in a shape the far end cannot read
    (`apps/dgo-extend/catalog.py:161` publishes a LIST; `platform/manager/serve.py:357` reads one
    string and raises `TypeError: unhashable type: 'list'`).

The other one — `POST /api/apps/<id>/apply` having no link guard
(`platform-base/app-management/app.py:api_apply`), while §9 names that very route beside
`PUT /api/remote` — was measured here on 2026-10-09, closed the same day in the route itself, and is
asserted without a marker. Whoever closes the remaining one deletes its `xfail` too.

Hermetic by construction: no office, no tunnel, no network, no docker — every input is built here,
and nothing outside the repo is read except the files those claims are about.

    python3 apps/dgo-extend/tests/test_link_security.py   # non-zero exit on a violated claim

Discovered and run by gate G72 (`scripts/refactor/plane-tests-lint.py`) as well: it is named the way an
app's tests are named, so a claim that stops holding fails a gate rather than waiting for a reader.
"""
from __future__ import annotations

import ast
import base64
import importlib.util
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "apps/dgo-extend"
sys.path.insert(0, str(APP))

import catalog       # noqa: E402
import identity      # noqa: E402
import linkproxy     # noqa: E402
import pairing       # noqa: E402
import peers         # noqa: E402
import projection    # noqa: E402


def _load(path: Path, name: str):
    """A module whose file name is not importable (`link-proxy.py`, `platform/manager/serve.py`).

    By path rather than by adding a directory to `sys.path`: `platform/manager` holds its own
    `catalog.py`, and a path that puts it before this app's would make `import catalog` mean two
    different modules in one process.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


door_mod = _load(APP / "link-proxy.py", "dgo_door")
serve_mod = _load(ROOT / "platform/manager/serve.py", "dgo_serve")

#: The office being tested, as its own registry and `serve:` map are: an app the owner gives, and the
#: three that OPERATE the office (`app-management`, `computers`, `connections` — the vault). `bina-ds`
#: is the agent: a UI port AND an agent-API port, and the only row that carries an identity mapping.
REGISTRY = {"apps": [
    {"app": "drive", "alias": "drive", "name": "דרייב", "name_en": "Drive", "icon": "drive",
     "group": "ראשי", "desc": "קבצים", "order": 2, "port": 8975, "host": "drive.localhost"},
    {"app": "bina-ds", "alias": "bina", "name": "בינה ודעת", "icon": "bot", "order": 1, "port": 3080,
     "agent_api_port": 3081, "host": "bina.localhost",
     "identity": {"to": "owner@local"}},
    {"app": "app-management", "alias": "apps", "name": "ניהול אפליקציות", "port": 8010,
     "host": "apps.localhost"},
    {"app": "computers", "alias": "computers", "name": "מחשבים", "port": 8977,
     "host": "computers.localhost"},
    {"app": "connections", "alias": "connections", "name": "מפתחות וחיבורים", "port": 8030,
     "host": "connections.localhost"},
]}
#: The four answers the serving side may give about what a peer sees.
NARROW = {"drive": {"port": 8975}}
STAR = {"*": {}}
NAMED_AGENT = {"bina-ds": {"port": 3080, "agent_api_port": 3081}}


def _published(serve_map: dict, office: str = "") -> dict:
    """This office's catalog, exactly as `build_catalog` builds it for a linked office."""
    return catalog.build(catalog.publishable(REGISTRY, serve_map, office), "hp-laptop",
                         {"he": "HP", "en": "HP"}, link_port=linkproxy.door_port(3))


def _door(catalog_doc: dict, office: str = "macbook"):
    """The serving office's door, holding the route table it builds from that catalog.

    `Door` is the running class (`link-proxy.py`); only the table is seeded instead of being fetched
    over HTTP from the app, because the fetch is `GET /api/link/catalog` — the same function
    `_published` calls — and the door's own decisions are what this file is about.
    """
    door = door_mod.Door({"office": office, "app": "door", "kind": "door", "direction": "serve",
                          "bind": "127.0.0.1", "port": 9003, "target": "dgo-extend:8984"})
    door.refused = ""
    # What `routes()` would have stored from the fetched catalog (see `Door._table`). Kept as the
    # real static method so a change in the table's shape is a change this test sees.
    door._routes = door_mod.Door._table(catalog_doc)
    door._at = time.time()
    return door


def _asked_the_door(door, host: str, head: bytes) -> bytes:
    """One request through the real door, on a real socket pair — the answer it gives for `host`.

    `Door._serve` is the loop a peer's connection goes through, and it is used as-is — on a real
    socket pair, with the head a browser would send. Nothing is dialed: this is the name the office
    does NOT serve, so the door answers before any upstream exists, and what it answers is what the
    peer reads.
    """
    client, peer = socket.socketpair()
    client.settimeout(5)
    thread = threading.Thread(target=door._serve, args=(client,), daemon=True)
    thread.start()
    peer.sendall(head)
    out = b""
    peer.settimeout(5)
    try:
        while True:
            chunk = peer.recv(65536)
            if not chunk:
                break
            out += chunk
    except OSError:
        pass
    thread.join(timeout=5)
    for sock in (client, peer):
        try:
            sock.close()
        except OSError:
            pass
    return out


def _get(host: str) -> bytes:
    """A browser's own request for a door: it asks for HTML, so a refusal may carry its card."""
    return (f"GET / HTTP/1.1\r\nHost: {host}\r\nAccept: text/html\r\n\r\n").encode()


def _headers(raw: bytes) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in raw.split(b"\r\n\r\n", 1)[0].split(b"\r\n")[1:]:
        name, _, value = line.partition(b":")
        out.setdefault(name.strip().lower().decode(), []).append(value.strip().decode())
    return out


CLAIMS: list[tuple[str, str, object]] = []


def claim(name: str, xfail: str = ""):
    """Register one claim. `xfail` names the code path that is missing — see the module docstring."""
    def deco(fn):
        CLAIMS.append((name, xfail, fn))
        return fn
    return deco


# ── 1. serve: is the whole of it ─────────────────────────────────────────────────────────────────
@claim("§9 · a paired office serves only what it declares: the door refuses a name it does not serve")
def c_serves_only_what_it_declares():
    problems = []
    door = _door(_published(NARROW))
    if door.route("drive.localhost") != ("drive", 8975, ""):
        problems.append(f"a served app must be reachable under its authority, got "
                        f"{door.route('drive.localhost')}")
    for name, what in (("connections.localhost", "the vault"),
                       ("apps.localhost", "the app plane"),
                       ("computers.localhost", "the machine plane"),
                       ("bina.localhost", "an app nobody named")):
        if door.route(name) is not None:
            problems.append(f"`serve: {NARROW!r}` names `drive` alone, so {what} ({name}) must not "
                            f"be reachable, got {door.route(name)}")
    # …and the refusal is the door's OWN answer, not a timeout or an empty connection: a peer that
    # asks for something it was not given is told so, with the reason on the answer.
    answer = _asked_the_door(_door(_published(NARROW)), "connections.localhost",
                             _get("connections.localhost"))
    first_line = answer.split(b"\r\n")[0]
    if not answer.startswith(b"HTTP/1.1 404") or _headers(answer).get("x-dgo-door") != ["no-app"]:
        problems.append(f"the door must answer `no-app` for a name it does not serve, got "
                        f"{first_line!r} {_headers(answer).get('x-dgo-door')}")

    # The other half of §9's sentence, in the shape that let a paired office read the other's
    # /api/instances (2026-10-04): `*` is "my other office" and publishes the operating apps too.
    star = _door(_published(STAR))
    for name, what in (("connections.localhost", "the vault"),
                       ("apps.localhost", "the app plane"),
                       ("computers.localhost", "the machine plane")):
        if star.route(name) is None:
            problems.append(f"`serve: {{\"*\": {{}}}}` is the owner's “my other office”: it publishes "
                            f"{what} ({name}), and a door that answers nothing means the wildcard "
                            f"stopped meaning “everything”")
    if star.route("drive.localhost") is None:
        problems.append("a wildcard serve must still publish the ordinary apps")

    # The DOOR RULES the office opens for the pair — `linkproxy._serve_doors` is what the plan is
    # rendered from, so "which apps a peer may arrive at" is answered here as well as at the door.
    rules = linkproxy._serve_doors("macbook", 3, "10.79.3.1", "10.79.3.2", catalog.with_control(NARROW))
    named = {r["app"] for r in rules}
    for app in ("connections", "app-management", "computers", "bina-ds"):
        if app in named:
            problems.append(f"a listener for {app!r} is a door onto an app `serve:` does not name: "
                            f"{sorted(named)}")
    if {r["app"] for r in rules} != {linkproxy.DOOR_APP, linkproxy.SELF_APP}:
        problems.append(f"`serve: {NARROW!r}` opens the link's door and its catalog, and nothing "
                        f"else, got {sorted((r['app'], r['port']) for r in rules)}")
    for rule in rules:
        if rule["clients"] != ["10.79.3.2"]:
            problems.append(f"only the peer's own tunnel address may arrive, got {rule['clients']}")

    # An agent API's own port is opened only when `serve:` names THAT PORT (DGO-32), and `*` never
    # enumerates them: the wildcard carries no port map, so it cannot open what it cannot name.
    agent = {r["app"] for r in linkproxy._serve_doors("macbook", 3, "10.79.3.1", "10.79.3.2",
                                                      catalog.with_control(NAMED_AGENT))}
    if "bina-ds" not in agent:
        problems.append(f"an app served WITH its agent port opens that port, got {sorted(agent)}")
    wild = {r["app"] for r in linkproxy._serve_doors("macbook", 3, "10.79.3.1", "10.79.3.2",
                                                     catalog.with_control(STAR))}
    if "bina-ds" in wild:
        problems.append(f"`*` does not include an agent API: it has no port to open, got {sorted(wild)}")
    return problems


# ── 2. identity: who is calling is THIS office's answer ──────────────────────────────────────────
@claim("§9 · identity crosses boundedly: the mapped user is per served app, and a forgery is not believed")
def c_identity_crosses_boundedly():
    problems = []
    # ONE catalog, two served apps: `bina` carries a mapping, `drive` is served without one. The door
    # writes the mapping of the app being reached — never another app's, and never a name the peer
    # chose (the peer's whole `X-authentik-*` family is removed, not edited).
    table = door_mod.Door._table(_published({"drive": {"port": 8975}, "bina": {"port": 3080}}))
    if table.get("bina.localhost", (None, None, None))[2] != "owner@local":
        problems.append(f"a served app with a mapping must arrive as it, got {table.get('bina.localhost')}")
    if table.get("drive.localhost", (None, None, None))[2] != "":
        problems.append(f"an app served WITHOUT a mapping has no mapped user, and must never inherit "
                        f"another app's, got {table.get('drive.localhost')}")
    claimed = (b"POST /api/x HTTP/1.1\r\nHost: bina.localhost\r\nConnection: keep-alive, upgrade\r\n"
               b"X-authentik-username: root-of-the-peer\r\nX-Authentik-Groups: authentik Admins\r\n"
               b"X-authentik-jwt: e30.e30.x\r\nX-DGO-Office: some-third-office\r\n"
               b"Content-Length: 2\r\n\r\n{}")
    head = _headers(door_mod.Door.rewrite(claimed, "owner@local", "macbook"))
    if head.get("x-authentik-username") != ["owner@local"] or \
            [k for k in head if k.startswith("x-authentik-")] != ["x-authentik-username"]:
        problems.append(f"the mapped user is the only identity that may arrive, got {head}")
    if head.get("x-dgo-office") != ["macbook"]:
        problems.append(f"which office is asking is the LINK's fact and never the peer's claim, got "
                        f"{head.get('x-dgo-office')}")
    if head.get("connection") != ["close"]:
        problems.append("a request that says `upgrade` without a websocket handshake must be the only "
                        "one on its connection, or a second one arrives unrewritten")

    # FROM ANYWHERE ELSE: on the consuming side the router chain is what decides whether an incoming
    # identity header is believed, and the answer is the ORDER — this office's own outpost
    # (`authentik@file`, which overwrites every `X-authentik-*` with its own answer) runs BEFORE the
    # middleware that writes the mapped user. After it, the request carries this office's user.
    served = {"drive": {"port": 8975}, "bina": {"port": 3080}}
    entry = {"office": "macbook", "address": "10.79.3.2", "label": {"he": "המקבוק", "en": "MacBook"},
             "link": "macbook", "link_port": 9002, "identity": {"to": "owner@local"},
             "apps": [dict(a, module_kind="external", module_path=f"/a/{a['alias']}/")
                      for a in _published(served)["apps"]]}
    console = json.loads((ROOT / "platform-base/console/app.json").read_text(encoding="utf-8"))
    entries, errs = serve_mod.plan({"remote": [entry]}, console)
    if errs:
        problems.append(f"the remote block of one served app must compile, got {errs}")
        return problems
    doc = yaml.safe_load(serve_mod.render(entries, console, domain="office.example"))
    chain = doc["http"]["routers"]["dgo-remote-macbook-bina-console"]["middlewares"]
    if chain[0] != "authentik@file":
        problems.append(f"this office's own SSO must run FIRST, so a forged header is already gone "
                        f"before the mapping is written, got {chain}")
    mapping = f"dgo-remote-{entry['office']}-identity"
    if mapping not in chain:
        problems.append(f"the mapped identity middleware is missing from the chain: {chain}")
    elif chain.index(mapping) < chain.index("authentik@file"):
        problems.append(f"the mapping must be written AFTER the outpost overwrites the header, got {chain}")
    written = doc["http"]["middlewares"][mapping]["headers"]["customRequestHeaders"]
    if written.get("X-authentik-username") != "owner@local":
        problems.append(f"the middleware writes THIS office's mapped user, got {written}")
    if any("authentik" in str(k).lower() for k in written if k != "X-authentik-username"):
        problems.append(f"nothing of the caller's own claims may be passed through, got {written}")
    return problems


# ── 3. the tunnel/role model: direction, and “not answering” is not “healthy” ────────────────────
@claim("§9 · direction is one-way in the rendered plan, and a silent peer is reported as silent")
def c_direction_and_silence():
    problems = []
    # WE SERVE: our rules are the door and the catalog, bound on OUR tunnel address, and the peer
    # alone may arrive. There is no rule that reaches back to the peer at all — the receiving side
    # holds no listener that leads into this office's vault or its unserved apps.
    serve_plan = linkproxy.build_multi(
        {"id": "hp-laptop", "tunnel": {"slot": 1}, "serve": NARROW},
        [{"office": {"id": "macbook", "tunnel": {"slot": 3},
                     "links": [{"office": "hp-laptop", "direction": "use"}]},
          "slot": 3, "side": 1}])
    if any(r["direction"] != "serve" for r in serve_plan["rules"]):
        problems.append(f"a `serve` link renders serve rules only, got "
                        f"{[(r['direction'], r['app']) for r in serve_plan['rules']]}")
    if any(str(r.get("target", "")).startswith("10.79.3.2") for r in serve_plan["rules"]):
        problems.append(f"no rule of a `serve` link may point AT the peer, got {serve_plan['rules']}")

    # WE USE: every rule is a listener on OUR side reaching the PEER's door — the peer's own address,
    # never a local service name, so nothing here can be turned into a door into this office.
    use_plan = linkproxy.build_multi(
        {"id": "hp-laptop", "tunnel": {"slot": 1}, "serve": {}},
        [{"office": {"id": "macbook", "tunnel": {"slot": 3},
                     "links": [{"office": "hp-laptop", "direction": "serve"}]},
          "slot": 3, "side": 2}],
        {"macbook": {"bina-ds": {"port": 3080, "agent_api_port": 3081}}})
    if any(r["direction"] != "use" for r in use_plan["rules"]):
        problems.append(f"a `use` link renders use rules only, got "
                        f"{[(r['direction'], r['app']) for r in use_plan['rules']]}")
    for rule in use_plan["rules"]:
        if not str(rule["target"]).startswith("10.79.3.1:"):
            problems.append(f"the consuming half reaches the PEER's tunnel address only, got {rule}")
        if rule["clients"]:
            problems.append(f"our own listener has no arriving peer to name, got {rule}")

    # A PEER THAT DOES NOT ANSWER, through the pass that writes it down. A stand-in control plane and
    # machine: the catalog is fetched from the link's own control port (9403 — the pair's slot), and
    # a connection that fails is what a sleeping office looks like from here.
    class Plane:
        home = {"id": "hp-laptop", "tunnel": {"slot": 1}, "serve": {}}
        LOCAL_MACHINE, HOME_REPO = "computer_local-local", "/repo"

        def __init__(self, answers=None):
            self.answers, self.asked = dict(answers or {}), []

        def _http(self, method, url, body=None, timeout=30):
            key = (method, url.replace(projection.CONTROL_URL, ""))
            self.asked.append(key)
            if key in self.answers:
                return self.answers[key]
            raise ConnectionError("the link proxy is not listening")

        def home_office(self):
            return dict(self.home)

        def declarations(self):
            return [{"id": "macbook", "kind": "paired", "label": {"he": "המקבוק"},
                     "links": [{"office": "hp-laptop", "direction": "serve"}],
                     "tunnel": {"slot": 3}}]

        def exec_on(self, *_a, **_k):
            return {"code": 1, "stdout": ""}

        def q(self, s):
            return s

    catalog_url = "http://dgo-net:9403/api/link/catalog"
    answered = {"office": "macbook", "label": {"he": "המקבוק"}, "generated_at": 7,
                "apps": [{"alias": "bina", "app": "bina-ds", "port": 3080,
                          "identity": {"to": "owner@local"}}]}
    with tempfile.TemporaryDirectory() as tmp:
        silent = projection.sync(Plane(), tmp)
        status = projection.load_status(tmp)
        if status.get("macbook", {}).get("ok") is not False:
            problems.append(f"a peer that did not answer must be written down as not answering, got "
                            f"{status}")
        if not status.get("macbook", {}).get("error"):
            problems.append(f"the silence must carry its reason, got {status}")
        if silent.get("pulled") or silent.get("block"):
            problems.append(f"a peer that gave nothing is not projected from nothing, got "
                            f"{silent.get('block')}")
        if silent.get("errors", {}).get("macbook") != "ConnectionError":
            problems.append(f"the silence must be reported per office, got {silent.get('errors')}")
    with tempfile.TemporaryDirectory() as tmp:
        # …and the OTHER answer, so a check that could only ever see “not answering” is caught.
        plane = Plane({("GET", catalog_url): answered,
                       ("GET", "/api/remote"): {"remote": []},
                       ("PUT", "/api/remote"): {"ok": True, "written": True},
                       ("POST", "/api/apps/dgo-extend/apply"): {"ok": True}})
        sane = projection.sync(plane, tmp)
        if projection.load_status(tmp).get("macbook", {}).get("ok") is not True:
            problems.append(f"a peer that answered IS healthy — the two states must be told apart, "
                            f"got {projection.load_status(tmp)}")
        if sane.get("block") != [{"office": "macbook", "apps": ["bina"]}]:
            problems.append(f"an office that answered is projected as it answered, got {sane.get('block')}")

    # The countdown before a silence is a verdict, and what the console is handed: only what was
    # measured — an office nobody measured is absent, never defaulted to healthy.
    passes: dict = {}
    for _ in range(projection.QUICK_RETRIES):
        passes = projection.silent_passes(passes, {"macbook": "ConnectionError"})
    if not projection.retried(passes, "macbook"):
        problems.append("a silence inside its quick retries is not yet a verdict")
    if projection.retried(projection.silent_passes(passes, {"macbook": "ConnectionError"}), "macbook"):
        problems.append("one silent pass past the retries and it IS a verdict")
    if projection.projected({}, {"macbook": answered}, {"macbook": "timeout"}) != {"macbook": answered}:
        problems.append("a silent peer keeps the tiles it gave last — its apps are unconfirmed, not gone")
    with tempfile.TemporaryDirectory() as tmp:
        kept = (peers.STATE, peers.PEERS)
        peers.STATE, peers.PEERS = Path(tmp), Path(tmp) / "peers"
        try:
            peers.publish_link({"macbook": {"ok": False, "hop": "office"}})
            doc = json.loads((Path(tmp) / "peers" / "link.json").read_text(encoding="utf-8"))
            if doc.get("offices") != {"macbook": {"ok": False, "hop": "office"}}:
                problems.append(f"the console is handed the measurement, got {doc}")
            if abs(int(doc.get("at") or 0) - int(time.time())) > 30:
                problems.append(f"a measurement carries the moment it was taken, got {doc.get('at')}")
            peers.publish_link({})
            if json.loads((Path(tmp) / "peers" / "link.json").read_text())["offices"]:
                problems.append("an office nobody measured must not appear as a linked office at all")
        finally:
            peers.STATE, peers.PEERS = kept
    return problems


# ── 4. secrets never leave the offering side ─────────────────────────────────────────────────────
@claim("§9 · a served app receives an identity, not a credential: no secret is published")
def c_no_secret_crosses():
    problems = []
    # A registry row that carries secrets (they exist: `.env` values reach a manifest's row in some
    # apps), a vault reference beside them, and an identity mapping. What crosses is the ALLOW-LIST
    # `catalog.build` writes — and the only credential-shaped thing in it is the NAME of a vault
    # entry on the RECEIVING office (`bearer:vault:<app>`), which is a pointer, not a secret.
    secrets = {"token": "REDACTED-value-2", "password": "S3CRET-PW", "api_key": "S3CRET-KEY",
               "vault": {"api_key": "REDACTED-value-3"}, "env": {"API_KEY": "S3CRET-ENV"}}
    row = {"app": "bina-ds", "alias": "bina", "name": "בינה", "port": 3080, "agent_api_port": 3081,
           "identity": {"to": "owner@local", "from": ["akadmin"]}, **secrets}
    cat = catalog.build({"apps": [row]}, "hp-laptop", {"he": "HP"})
    blob = json.dumps(cat, ensure_ascii=False)
    leaked = [name for name, value in secrets.items() if isinstance(value, str) and value in blob]
    leaked += [v for v in ("S3CRET-VAULT", "S3CRET-ENV") if v in blob]
    if leaked:
        problems.append(f"the catalog is an allow-list: {leaked} crossed the link")
    entry = cat["apps"][0]
    if entry["api"]["auth"] != "bearer:vault:bina-ds":
        problems.append(f"an agent API publishes the vault KEY'S NAME, never its value, got {entry['api']}")
    # WHAT THE MAPPING IS: two user names, and nothing else — not the shape they are spelled in (that
    # is `c_mapping_crosses_intact`'s claim), and certainly not a value the vault holds.
    mapping = json.dumps(entry["identity"], ensure_ascii=False)
    if set(entry["identity"]) != {"to", "from"} or "owner@local" not in mapping or "akadmin" not in mapping:
        problems.append(f"the mapping is a user vocabulary, not a credential, got {entry['identity']}")

    # The office's own keys: `identity.public()` is the only half any route or log may use (its own
    # docstring says so), and the pairing's wire format is a photographed QR code — a secret inside
    # it is a secret given away by a photograph.
    doc = {"office": "hp-laptop", "created_at": 1, "fingerprint": "AAAA-BBBB",
           "ed25519": {"private": "PRIV-ED25519", "public": "PUB-ED25519"},
           "wg": {"private": "PRIV-WG", "public": "PUB-WG"}}
    public = identity.public(doc)
    crossed = json.dumps(public, ensure_ascii=False)
    if "PRIV-ED25519" in crossed or "PRIV-WG" in crossed:
        problems.append(f"a private half crossed the wire, got {public}")
    if public["ed25519"] != "PUB-ED25519" or public["wg"] != "PUB-WG":
        problems.append(f"the public halves are what crosses, got {public}")
    offer, eph = pairing.new_offer("macbook", public, ["192.168.16.102:51830"],
                                   extra={"label": "HP", "direction": "use"})
    priv, pubraw = pairing._ed25519_keypair()
    host = {"ed25519": base64.b64encode(pubraw[-32:]).decode(), "wg": "W" * 43 + "=",
            "fingerprint": "75FF-E977-0881-0625"}
    reply = pairing.accept(offer, "hp-laptop", priv, host, token="t" * 64, direction="serve",
                           tunnel={"slot": 3, "dial": "host", "endpoint": "192.168.16.102",
                                   "port": 51830})
    # …and what the wire actually CARRIES, read back through the peer's own reader. A base64 blob
    # hides nothing from the peer that decodes it, so the check is on the decoded document (the raw
    # text is checked for the one thing that must never appear even in plain sight — the token).
    for where, blob in (("the offer", offer), ("the reply", reply)):
        plain = json.dumps(blob, ensure_ascii=False)
        for word in ("private", "PRIV-WG", "PRIV-ED25519", "S3CRET"):
            if word.lower() in plain.lower():
                problems.append(f"{where} carries {word!r} once the peer decodes it — a photographed "
                                f"code would hand it over")
        if "t" * 64 in plain:
            problems.append(f"{where} carries the pair's token in the clear instead of an encrypted "
                            f"grant addressed to the other side")
    back = pairing.parse_offer(pairing.offer_text(offer))
    if back["identity"]["ed25519"] != public["ed25519"] or "PRIV-ED25519" in json.dumps(back):
        problems.append(f"the offer the peer reads back must carry this office's PUBLIC identity, "
                        f"got {back['identity']}")
    # …and the builder refuses a secret-shaped field rather than trusting its caller to leave one out:
    # the offer is displayed and photographed, so "nobody would put a token there" is not a property.
    for banned in ("token", "private_key", "secret"):
        try:
            pairing.new_offer("macbook", public, ["192.168.16.102:51830"], extra={banned: "x"})
            problems.append(f"an offer with a {banned!r} field must be refused by the builder itself")
        except pairing.PairingError:
            pass
    grant, code = pairing.open_reply(offer, eph, pairing.parse_reply(pairing.reply_text(reply)))
    if grant.get("token") != "t" * 64 or not code:
        problems.append("the token exists only inside the grant the far side opens: it is not in the "
                        "code two people compare out loud")
    return problems


# ── the two §9 claims the code does not hold ─────────────────────────────────────────────────────
def _route_reads_the_link_header(path: Path, func: str) -> bool:
    """Does THIS route function read the door's `X-DGO-Office` header?

    Asked of the function itself (`ast`), because the question is what the route does — a mention in a
    comment, a docstring or a neighbouring helper is not an answer. Both routes §9 names are asked
    the same way, so a checker that can only ever say “no” is caught by the one that IS guarded.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            return any(isinstance(n, ast.Name) and n.id == "OFFICE_HEADER"
                       for n in ast.walk(node))
    raise AssertionError(f"{path} has no function {func}")


@claim("§9 · a request that crossed a link cannot write this office's own state")
def c_lifecycle_write_is_refused():
    problems = []
    app_py = ROOT / "platform-base/app-management/app.py"
    if not app_py.exists():
        return [f"{app_py} is not here — the claim cannot be checked"]
    # The control: the same question about the route §9 names FIRST, which does refuse a linked call.
    if not _route_reads_the_link_header(app_py, "api_remote_put"):
        problems.append("`PUT /api/remote` refused a linked request in §9's own words — the guard is "
                        "gone (or this check stopped finding it), and the second half below is then "
                        "unmeasurable")
    if not _route_reads_the_link_header(app_py, "api_apply"):
        problems.append("`POST /api/apps/<id>/apply` is not guarded: a peer this office serves "
                        "`app-management` to can recompile and recreate containers here, which is "
                        "writing this office's own state — the route §9 names beside /api/remote")
    return problems


@claim("§9 · the identity mapping crosses the link in the shape the far end reads",
       xfail="catalog.build publishes identity.from as a LIST (apps/dgo-extend/catalog.py:161) while "
             "platform/manager/serve.py:357 reads it as one header string: `sorted({... 'from'})` on "
             "a list raises TypeError: unhashable type: 'list', so the peer cannot compile at all")
def c_mapping_crosses_intact():
    problems = []
    # The serving office declares `identity: {to: …, from: [akadmin]}` — a `from` nothing validates
    # (app.py's `/api/link/serve` checks `to` alone) — and `catalog.build` is what publishes it.
    row = {"app": "drive", "alias": "drive", "name": "דרייב", "port": 8975,
           "identity": {"to": "owner@local", "from": ["akadmin"]}}
    entry = catalog.build({"apps": [row]}, "hp-laptop", {"he": "HP"})["apps"][0]
    entry.update({"module_kind": "external", "module_path": "/a/drive/"})
    block = {"office": "hp-laptop", "address": "10.79.3.1", "label": {"he": "HP"}, "link": "hp-laptop",
             "link_port": 9003, "identity": {"to": "owner@local", "from": ["akadmin"]},
             "apps": [entry]}
    console = json.loads((ROOT / "platform-base/console/app.json").read_text(encoding="utf-8"))
    try:
        entries, errs = serve_mod.plan({"remote": [block]}, console)
    except TypeError as e:
        problems.append(f"the consuming office cannot compile the mapping it was given "
                        f"({type(e).__name__}: {e}) — the peer's `from` arrives as "
                        f"{entry['identity']['from']!r}")
        return problems
    if errs:
        problems.append(f"the mapping must compile on the far end, got {errs}")
        return problems
    # WHAT THE FAR END IS LEFT WITH: `serve.render` joins this field into `X-DGO-From` (one link,
    # one identity — `plan` normalises a per-app value onto the office), so it must be a list of the
    # peer's own user names. This is the shape the fix has to leave behind, whichever end it lands on.
    if entries[0]["identity"].get("from") != ["akadmin"]:
        problems.append(f"the mapping the far end keeps must be the names it was given, got "
                        f"{entries[0]['identity']}")
    return problems


def main() -> int:
    failed, xfailed = [], []
    for name, xfail, fn in CLAIMS:
        try:
            problems = list(fn())
        except Exception as e:                              # noqa: BLE001 — a claim that cannot run
            problems = [f"the claim could not be checked: {type(e).__name__}: {e}"]
        if problems and xfail:
            xfailed.append((name, problems[0]))
            print(f"XFAIL {name}\n      {problems[0]}")
        elif problems:
            failed.append(name)
            for p in problems:
                print(f"FAIL  {name}\n      {p}")
        elif xfail:
            # The gap was closed and nobody removed the xfail: that is a FAILURE here, not a pass —
            # a marker left behind is how a real assertion goes missing without anyone deciding.
            failed.append(name)
            print(f"XPASS {name}\n      this claim is implemented now — remove the xfail marker "
                  f"(was: {xfail})")
        else:
            print(f"PASS  {name}")
    # THE SUMMARY IS THE LAST LINE, deliberately: it is what a gate that ran this file prints as its
    # one-line report (`plane-tests-lint` reads the last line), so that line has to be the verdict and
    # the count of what is still open — never a sentence from inside a gap.
    print(f"link_security: {len(CLAIMS)} claim(s), {len(CLAIMS) - len(failed) - len(xfailed)} pass, "
          f"{len(xfailed)} xfail (documented gap(s) still open), {len(failed)} fail")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
