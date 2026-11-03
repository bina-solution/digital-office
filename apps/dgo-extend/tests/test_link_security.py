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
  5. **The offer, the keys, the token and the one open port** (§9's own rows): a pairing offer is
     public material, ten minutes long and single-use; the six digits are derived on both sides from
     the shared secret alone; the office's identity is root-only on disk and crosses as public
     halves; a link's token is 256 bits, one per link per direction, and is minted INTO the vault
     under `dgo_link`; and the link publishes WireGuard's UDP and the carriers' key-proved TCP door
     and nothing else, each on loopback unless the office chose to be reached (2026-10-19: the TCP
     path of a pair that can never carry UDP). These five hold with no office, no tunnel and no network —
     asked here rather than left to `pairing.selftest()` and the phase suites, which run when a
     human runs them.

TWO claims in this family were open when the file was written, and both are now asserted without a
marker — each closed in the code the claim names, not in the test:

  · `POST /api/apps/<id>/apply` had no link guard (`platform-base/app-management/app.py:api_apply`),
    while §9 names that very route beside `PUT /api/remote` — measured 2026-10-09, closed the same day.
  · the identity mapping's `from` half crossed the link in a shape the far end could not read
    (`apps/dgo-extend/catalog.py:161` publishes a LIST, `platform/manager/serve.py` read it as one
    header string and then raised `TypeError: unhashable type: 'list'` on the pair's own value, so a
    peer publishing the shape it declares could not be compiled at all) — fixed in `serve.py`'s
    `remote` reader, which now validates the list and flattens it into the link's one identity.

Every claim below is therefore asserted plainly, and a claim that stops holding is a failure.

Hermetic by construction: no office, no tunnel, no network, no docker — every input is built here,
and nothing outside the repo is read except the files those claims are about.

    python3 apps/dgo-extend/tests/test_link_security.py   # non-zero exit on a violated claim

Discovered and run by gate G72 (`scripts/refactor/plane-tests-lint.py`) as well: it is named the way an
app's tests are named, so a claim that stops holding fails a gate rather than waiting for a reader.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import importlib.util
import json
import re
import socket
import stat
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
import firewall      # noqa: E402
import identity      # noqa: E402
import links         # noqa: E402
import linkproxy     # noqa: E402
import move          # noqa: E402
import net           # noqa: E402
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

    # An agent API's own port is opened for every SERVED app that declares one (DGO-570): the port is
    # a fact of the APP (`reconcile` compiles `agent_api_port` into its registry row), not a line the
    # link repeats. An explicit `serve:` entry opens it exactly as before, a WILDCARD no longer hides
    # it, and nothing is invented for an app that declares none.
    agent = {r["app"] for r in linkproxy._serve_doors("macbook", 3, "10.79.3.1", "10.79.3.2",
                                                      catalog.with_control(NAMED_AGENT))}
    if "bina-ds" not in agent:
        problems.append(f"an app served WITH its agent port opens that port, got {sorted(agent)}")
    declared = catalog.serve_with_agents(REGISTRY, STAR)
    if declared.get("bina-ds") != {"service": "bina-ds", "port": 3080, "agent_api_port": 3081}:
        problems.append(f"a wildcard must carry the agent door its app declares, got {declared}")
    wild_rules = linkproxy._serve_doors("macbook", 3, "10.79.3.1", "10.79.3.2",
                                        catalog.with_control(declared))
    wild = sorted((r["app"], r["port"]) for r in wild_rules)
    want_wild = sorted([(linkproxy.SELF_APP, int(catalog.CATALOG_PORT)),
                        (linkproxy.DOOR_APP, linkproxy.door_port(3)), ("bina-ds", 3081)])
    if wild != want_wild:
        problems.append(f"`serve: {{\"*\": {{}}}}` opens the link's two doors and the agent door its "
                        f"app declares — and nothing else (drive, app-management, computers and "
                        f"connections declare no agent API), got {wild}")
    # Explicit wins: a `serve:` entry that names its own agent port keeps it, and the port the app
    # declares does not quietly open a second door beside it.
    explicit = catalog.with_control(catalog.serve_with_agents(
        REGISTRY, {"bina-ds": {"port": 3080, "agent_api_port": 9999}}))
    if [r["port"] for r in linkproxy._serve_doors("macbook", 3, "10.79.3.1", "10.79.3.2", explicit)
            if r["app"] == "bina-ds"] != [9999]:
        problems.append(f"an explicit `agent_api_port` is the last word, got {explicit.get('bina-ds')}")
    # The adapter's DELIVERY name is the service, the same word the catalog publishes (DGO-38): `mail`
    # answers as `mailview`, so a wildcard office's second door must not aim at the app id.
    mail = catalog.serve_with_agents(
        {"apps": [{"app": "mail", "alias": "mail", "port": 8976, "agent_api_port": 8970,
                   "service": "mailview"}]}, STAR)
    mail_doors = [(r["app"], r["port"], r["target"]) for r in linkproxy._serve_doors(
        "macbook", 3, "10.79.3.1", "10.79.3.2", catalog.with_control(mail))
        if r["app"] not in (linkproxy.SELF_APP, linkproxy.DOOR_APP)]
    if mail_doors != [("mailview", 8970, "mailview:8970")]:
        problems.append(f"the door delivers to the service the catalog publishes, got {mail_doors}")
    # …and an entry that declares the SAME agent port by hand still delivers to that service: the
    # port is already open, so nothing new is opened, but the name must not fall back to the app id
    # (the HP, 2026-10-22: `browser42: {port 80, agent_api_port 8931}` → "nothing answers at
    # browser42:8931", while browser42 answers as browser42-caddy).
    b42 = catalog.serve_with_agents(
        {"apps": [{"app": "browser42", "alias": "browser42", "port": 80, "agent_api_port": 8931,
                   "service": "browser42-caddy"}]},
        {"*": {}, "browser42": {"port": 80, "agent_api_port": 8931}})
    b42_doors = [(r["app"], r["port"], r["target"]) for r in linkproxy._serve_doors(
        "macbook", 3, "10.79.3.1", "10.79.3.2", catalog.with_control(b42))
        if r["app"] not in (linkproxy.SELF_APP, linkproxy.DOOR_APP)]
    if b42_doors != [("browser42-caddy", 8931, "browser42-caddy:8931")]:
        problems.append(f"a hand-declared agent door delivers to the app's service, got {b42_doors}")
    # THE OWNER'S CASE (DGO-1018): one office shares its browser with another, and the other's CLI
    # drives it, out of the box, with nothing declared by hand. browser42's registry row as the
    # compiler writes it: the UI answers as browser42-caddy, the agent API is its task runner. Shared by
    # the wildcard (the default) and by ticking the app (`{port, agent_api_port}`), the agent door must
    # deliver to the task runner both times: delivered to the UI's service it reached nothing (502).
    row = {"app": "browser42", "alias": "browser42", "port": 80, "agent_api_port": 8766,
           "service": "browser42-caddy", "agent_api_service": "browser42-task-runner"}
    for how, serve in (("the wildcard", {"*": {}}),
                       ("an app ticked by hand", {"browser42": {"port": 80, "agent_api_port": 8766}})):
        shared = catalog.serve_with_agents({"apps": [row]}, serve)
        doors = [(r["port"], r["target"]) for r in linkproxy._serve_doors(
            "macbook", 3, "10.79.3.1", "10.79.3.2", catalog.with_control(shared))
            if r["app"] not in (linkproxy.SELF_APP, linkproxy.DOOR_APP)]
        if doors != [(8766, "browser42-task-runner:8766")]:
            problems.append(f"shared by {how}, the browser's agent door reaches its task runner, got {doors}")
    # …the catalog says it (`api.service`), and an office that renders this one's serving half from
    # that catalog (`converge._remote_delivery`) delivers there too.
    published = catalog.build({"apps": [row]}, "hp-laptop")
    api = next((a.get("api") for a in published.get("apps") or [] if a.get("app") == "browser42"), None)
    if not isinstance(api, dict) or api.get("service") != "browser42-task-runner" or api.get("port") != 8766:
        problems.append(f"the catalog publishes who answers the agent door, got {api}")
    far = catalog.serve_with_agents(published, {"*": {}})
    far_doors = [r["target"] for r in linkproxy._serve_doors(
        "macbook", 3, "10.79.3.1", "10.79.3.2", catalog.with_control(far))
        if r["app"] not in (linkproxy.SELF_APP, linkproxy.DOOR_APP)]
    if far_doors != ["browser42-task-runner:8766"]:
        problems.append(f"from the published catalog, the agent door reaches the task runner, got {far_doors}")
    # …and an app whose UI answers its API too (bina-ds) is unchanged: no second name, the UI's service.
    bina = catalog.serve_with_agents(REGISTRY, STAR).get("bina-ds") or {}
    if "agent_api_service" in bina:
        problems.append(f"an app whose UI service answers its API names no second service, got {bina}")
    # The registry's word on WHO answers holds for the door it describes and no other (the second reader
    # of DGO-1018). The HP's own stale tick names ANOTHER port (8931, the one its Caddy answers): that
    # door keeps going where it went, never to the task runner's 8931, where nothing listens; and the
    # catalog publishes the same pair, never 8931 beside the task runner.
    stale = catalog.serve_with_agents({"apps": [row]}, {"*": {}, "browser42": {"port": 80, "agent_api_port": 8931}})
    stale_doors = [r["target"] for r in linkproxy._serve_doors(
        "macbook", 3, "10.79.3.1", "10.79.3.2", catalog.with_control(stale))
        if r["app"] not in (linkproxy.SELF_APP, linkproxy.DOOR_APP)]
    if stale_doors != ["browser42-caddy:8931"]:
        problems.append(f"a hand entry naming another agent port keeps its own door, got {stale_doors}")
    pub = catalog.published_agent(row, stale.get("browser42"))
    if (pub.get("agent_api_port"), pub.get("agent_api_service")) != (8931, None):
        problems.append(f"the catalog publishes the door's own pair, got {pub}")
    if catalog.published_agent(row, catalog.serve_with_agents({"apps": [row]}, {"*": {}}).get("browser42")) \
            .get("agent_api_service") != "browser42-task-runner":
        problems.append("under the wildcard the catalog publishes who answers the agent door")
    # …a service named by hand is the owner's word, for the agent door too
    named = catalog.serve_with_agents(
        {"apps": [row]}, {"browser42": {"port": 80, "agent_api_port": 8766, "service": "browser42-caddy"}})
    named_doors = [r["target"] for r in linkproxy._serve_doors(
        "macbook", 3, "10.79.3.1", "10.79.3.2", catalog.with_control(named))
        if r["app"] not in (linkproxy.SELF_APP, linkproxy.DOOR_APP)]
    if named_doors != ["browser42-caddy:8766"]:
        problems.append(f"a service named by hand decides the agent door, got {named_doors}")
    # …and a delivery name the door does not take is never a target: neither a host outside the office
    # nor the link's own namespace (it shares one with dgo-net) — the door falls back to the UI's service.
    for bad in ("evil.example.com", "172.17.0.1", "localhost", "bina-ds\n", "a b", "dgo-net", "dgo-net-hp",
                "dgo-extend", "dgo-extend-hp"):
        rules_bad = [r for r in linkproxy._serve_doors(
            "macbook", 3, "10.79.3.1", "10.79.3.2",
            catalog.with_control({"browser42": {"port": 80, "agent_api_port": 8766, "service": "browser42-caddy",
                                                "agent_api_service": bad}}))
            if r["app"] not in (linkproxy.SELF_APP, linkproxy.DOOR_APP)]
        if [r["target"] for r in rules_bad] != ["browser42-caddy:8766"]:
            problems.append(f"agent_api_service {bad!r} must fall back to the UI's service, got {rules_bad}")
        elif repr(bad) not in str(rules_bad[0].get("note")):
            problems.append(f"a fallback from {bad!r} is said in the plan, got note {rules_bad[0].get('note')!r}")
    for bad in ("localhost", "evil.example.com", 7, "dgo-net", "dgo-net-hp", "dgo-extend", "dgo-extend-hp"):
        doc = {"office": "hp-laptop", "apps": [{"app": "browser42", "alias": "browser42", "port": 80,
                                                "api": {"port": 8766, "service": bad}}]}
        if not any("api.service" in e for e in catalog.validate(doc)):
            problems.append(f"a catalog whose api.service is {bad!r} is refused")
    # …and the catalog never publishes a name its own door refuses: behind a hand-written `Bad_Name` the
    # door delivers to the UI's service, so the catalog publishes no service at all — and a peer keeps
    # every tile of this office (it published `Bad_Name`, and a peer's `validate` refused the WHOLE
    # catalog: the second reader of DGO-1018).
    hand = catalog.serve_with_agents({"apps": [row]}, {"browser42": {"port": 80, "agent_api_port": 8766,
                                                                     "agent_api_service": "Bad_Name"}})
    pub_bad = catalog.build({"apps": [catalog.published_agent(row, hand.get("browser42"))]}, "hp-laptop")
    api_bad = next((a.get("api") for a in pub_bad.get("apps") or [] if a.get("app") == "browser42"), None)
    refused = [e for e in catalog.validate(pub_bad) if "api.service" in e]
    if not isinstance(api_bad, dict) or api_bad.get("port") != 8766 or "service" in api_bad or refused:
        problems.append(f"behind a name its door refuses, the catalog publishes the door's own pair, got "
                        f"{api_bad} {refused}")
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


@claim("§9 · the mapped user is a header value: one stored with a line break is never written (DGO-622)")
def c_mapped_user_is_a_header_value():
    problems = []
    said = []
    door_log, door_mod.log = door_mod.log, said.append
    try:
        # A catalog stored before the mapping was checked: the door's table is built from it as it is.
        stored = {"apps": [{"app": "bina-ds", "alias": "bina", "port": 3080, "host": "bina.localhost",
                            "identity": {"to": "owner\n"}}]}
        kept = door_mod.Door._table(stored).get("bina.localhost", (None, None, None))[2]
        if kept:
            problems.append(f"the door's table kept a mapped user that is not a header value: {kept!r}")
        head = door_mod.Door.rewrite(_get("bina.localhost"), "owner\n", "macbook", b"v1 macbook owner\n 0 x")
    finally:
        door_mod.log = door_log
    lines = head.split(b"\r\n\r\n", 1)[0].split(b"\r\n")
    if any(b"\n" in line or b"\r" in line for line in lines):
        problems.append(f"a line of the head the app reads carries a line break of its own: {head!r}")
    if _headers(head).get("x-authentik-username") or _headers(head).get("x-dgo-identity"):
        problems.append(f"a user that is not a header value is written, or signed: {_headers(head)}")
    if len(said) < 2:
        problems.append(f"each skip is said in the door's log, heard {said}")
    return problems


@claim("§9 · `*` gives a peer every app but this one: the door never reaches dgo-extend itself (DGO-624)")
def c_star_never_reaches_this_app():
    problems = []
    registry = dict(REGISTRY, apps=REGISTRY["apps"] + [
        {"app": "dgo-extend", "alias": "dgo-extend", "name": "לשכות", "port": 8983,
         "host": "dgo-extend.localhost"}])
    for serve_map in (STAR, {"dgo-extend": {"port": 8983}, "drive": {"port": 8975}}):
        door = _door(catalog.build(catalog.publishable(registry, serve_map, "macbook"), "hp-laptop"))
        for name in ("dgo-extend.localhost", "dgo-extend"):
            if door.route(name) is not None:
                problems.append(f"`serve: {serve_map!r}` lets the door reach this office's own declarations "
                                f"({name} → {door.route(name)})")
        if door.route("drive.localhost") is None:
            problems.append(f"`serve: {serve_map!r}` still gives the rest: drive must be reachable")
    return problems


#: A registry with two doors with no tile (`reconcile._office_apps` → `services`, DGO-945): the n8n
#: webhook receiver and the transcriber. The upstream of the first is this test's own listener.
DOORS = [{"app": "n8n", "alias": "workflow-hooks", "port": 5678, "service": "127.0.0.1", "health": "/healthz"},
         {"app": "apitools", "alias": "speech", "port": 8987, "service": "apitools-asr", "health": "/healthz"}]
HOOKS = {"to": ["vps1"], "paths": ["/webhook/meet-recordings"]}


def _upstream():
    """A listener that records the one head it is sent and answers 200 — the service behind a door."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    got = {}

    def serve():
        try:
            conn, _ = srv.accept()
            conn.settimeout(5)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            got["head"] = data
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            conn.close()
        except OSError:
            pass
        srv.close()

    threading.Thread(target=serve, daemon=True).start()
    return srv.getsockname()[1], got


@claim("§9 · a door with no tile is given by name, to the offices named, and answers its paths only (DGO-945)")
def c_door_with_no_tile_is_narrow():
    problems = []
    registry = dict(REGISTRY, services=DOORS)
    # Explicit only: `*` gives every app and no door; a door is given when `serve.services` names it.
    if catalog.publishable_services(registry, STAR, "vps1"):
        problems.append("`serve: {\"*\": {}}` must give no door with no tile — a door is named or not given")
    named = {"*": {}, "services": {"workflow-hooks": HOOKS}}
    got = catalog.publishable_services(registry, named, "vps1")
    if [d["alias"] for d in got] != ["workflow-hooks"] or got[0].get("paths") != HOOKS["paths"]:
        problems.append(f"a named door is given with its paths, got {got}")
    if catalog.publishable_services(registry, named, "macbook"):
        problems.append("a door given `to: [vps1]` must not reach another linked office")
    # `only` narrows a door with no `to` like an app; a path that is not one closes the door, never widens it
    narrowed = {"*": {}, "services": {"speech": {}}, "only": {"vps1": ["plane"]}}
    if catalog.publishable_services(registry, narrowed, "vps1") or \
            not catalog.publishable_services(registry, narrowed, "hp-laptop"):
        problems.append("`serve.only` must narrow a door with no `to` exactly as it narrows an app")
    for bad in (["/webhook/../rest/workflows"], ["webhook"], [], ["/a/%2e%2e"], ["/a\n"]):
        if catalog.publishable_services(registry, {"services": {"workflow-hooks": {"paths": bad}}}, "vps1"):
            problems.append(f"paths {bad!r} must give no door at all")
        if not catalog.clean_services({"workflow-hooks": {"paths": bad}})[1]:
            problems.append(f"the writers must refuse paths {bad!r}")
    if not catalog.clean_services({"speech": {"port": 1}})[1]:
        problems.append("a door's spec is `to` and `paths` only: a port there is refused")
    # The catalog carries the doors under their own key, never as tiles, and refuses a clash with an app
    published = catalog.build(catalog.publishable(registry, named, "vps1"), "hp-laptop",
                              link_port=linkproxy.door_port(3), services=got)
    if any(a.get("alias") == "workflow-hooks" for a in published["apps"]) or catalog.validate(published):
        problems.append(f"a door travels as `services`, valid, and never in `apps`: {catalog.validate(published)}")
    clash = dict(published, services=[dict(got[0], alias="drive")])
    if not catalog.validate(clash):
        problems.append("a door on the alias of a published app must be refused by the consuming office")
    # An office that serves a door and nothing else still opens the link's door for it
    rules = linkproxy._serve_doors("vps1", 3, "10.79.3.1", "10.79.3.2", catalog.with_control(
        catalog.serve_with_agents(registry, {"services": {"workflow-hooks": HOOKS}})))
    if {r["app"] for r in rules} != {linkproxy.DOOR_APP, linkproxy.SELF_APP}:
        problems.append(f"a door-only office opens the link's door and its catalog, got {sorted(r['app'] for r in rules)}")

    # THE DOOR: a path outside the list is the door's own `no-app`, before any upstream is dialed…
    port, seen = _upstream()
    doc = dict(published, office="hp-laptop", services=[dict(got[0], port=port)])
    answer = _asked_the_door(_door(doc, "vps1"), "workflow-hooks.hp-laptop",
                             b"POST /webhook/other HTTP/1.1\r\nHost: workflow-hooks.hp-laptop\r\n\r\n")
    if _headers(answer).get("x-dgo-door") != ["no-app"]:
        problems.append(f"a path the door was not given must be refused, got {answer[:60]!r}")
    for target in (b"/webhook/meet-recordings/../x", b"/webhook/meet-recordings%2f..%2fx",
                   b"http://n8n-webhook:5678/webhook/meet-recordings"):
        answer = _asked_the_door(_door(doc, "vps1"), "workflow-hooks.hp-laptop",
                                 b"POST " + target + b" HTTP/1.1\r\nHost: workflow-hooks.hp-laptop\r\n\r\n")
        if _headers(answer).get("x-dgo-door") != ["no-app"]:
            problems.append(f"{target!r} could be read as another path and must be refused, got {answer[:60]!r}")
    # …and the path it was given reaches the service as THIS door's caller: the peer's forwarding
    # claims and identity removed, the office it came from written.
    answer = _asked_the_door(_door(doc, "vps1"), "workflow-hooks.hp-laptop",
                             b"POST /webhook/meet-recordings?x=1 HTTP/1.1\r\nHost: workflow-hooks.hp-laptop\r\n"
                             b"X-Forwarded-For: 10.0.0.9\r\nForwarded: for=10.0.0.9\r\nX-Real-IP: 10.0.0.9\r\n"
                             b"X-Dgo-Office: macbook\r\nX-authentik-username: akadmin\r\nContent-Length: 0\r\n\r\n")
    head = _headers(seen.get("head") or b"")
    if not answer.startswith(b"HTTP/1.1 200"):
        problems.append(f"the path the door was given must reach the service, got {answer[:60]!r}")
    for name in ("x-forwarded-for", "forwarded", "x-real-ip", "x-authentik-username"):
        if name in head:
            problems.append(f"the service behind a door with no tile must not see the peer's {name}: {head[name]}")
    if head.get("x-dgo-office") != ["vps1"]:
        problems.append(f"the service is told which office called, got {head.get('x-dgo-office')}")
    # An app keeps the forwarding headers it always had — the change is the door's alone
    kept = door_mod.Door.rewrite(b"GET / HTTP/1.1\r\nHost: drive\r\nX-Forwarded-For: 93.184.216.7\r\n\r\n", "")
    if b"X-Forwarded-For: 93.184.216.7" not in kept:
        problems.append("an app's route must keep X-Forwarded-For as before")

    # The second reader's findings on this claim (DGO-945, round 2), each held here:
    # a path is that path — under it only when it ends in `/` …
    for target in (b"/webhook/meet-recordings/other", b"/webhook/meet-recordingsX"):
        answer = _asked_the_door(_door(doc, "vps1"), "workflow-hooks.hp-laptop",
                                 b"POST " + target + b" HTTP/1.1\r\nHost: workflow-hooks.hp-laptop\r\n\r\n")
        if _headers(answer).get("x-dgo-door") != ["no-app"]:
            problems.append(f"{target!r} is another webhook than the one given, got {answer[:60]!r}")
    # …a header hidden behind a bare CR or LF is refused before anything is forwarded (an app's own
    # parser would have read it as a second header, the door's office claim among them) …
    for smuggled in (b"X-A: b\rX-Dgo-Office: hp-laptop", b"X-A: b\nX-authentik-username: akadmin"):
        answer = _asked_the_door(_door(_published(NARROW), "macbook"), "drive.localhost",
                                 b"GET / HTTP/1.1\r\nHost: drive.localhost\r\n" + smuggled + b"\r\n\r\n")
        if not answer.startswith(b"HTTP/1.1 400") or _headers(answer).get("x-dgo-door") != ["bad-head"]:
            problems.append(f"a bare CR/LF in a header line must be refused, got {answer[:60]!r}")
    # …a path the regex cannot be made to hang on (it took 0.5 s at 24 characters, doubling) …
    started = time.time()
    door_mod._plain_path("/" + "a" * 5000 + "!")
    catalog.plain_path("/" + "a" * 5000 + "!")
    if time.time() - started > 0.5:
        problems.append("the door's path rule must run in linear time")
    # …a door never rides in on a re-shared section (`reshare` hands on apps alone) …
    hp = dict(published, office="hp-laptop")
    vps1_doc = catalog.build({"apps": []}, "vps1")
    vps1_doc["shared"] = [{"office": "dell", "apps": [], "services": [dict(DOORS[1])]}]
    if any("services" in s for s in catalog.shared_sections(vps1_doc, "hp-laptop")[0]):
        problems.append("a re-shared section must carry no door with no tile")
    # …"give nothing" closes the doors too, and an office that gives only doors has chosen …
    class Ports:
        served = {"services": {"workflow-hooks": dict(HOOKS)}}
        def serve(self): return dict(self.served)
        def set_serve(self, s): self.served = dict(s); return self.served
        def publishable(self): return []
        def render(self): return {}
    from pair_api import Pairing
    pair = Pairing(Ports())
    if not pair._gives_anything():
        problems.append("an office that gives only a door gives something — a pairing must not widen it to *")
    # the REAL writer (`converge._set_home_serve`), on a home record in a temp state dir: "give
    # everything" keeps the doors, "give nothing" (`{}`, what `give("none")` declares) closes them
    import converge
    import os
    with tempfile.TemporaryDirectory() as state:
        before = os.environ.get("DGO_STATE_DIR")
        os.environ["DGO_STATE_DIR"] = state
        try:
            Path(state, "home.json").write_text(json.dumps({"id": "hp-laptop", "serve": {
                "services": {"workflow-hooks": dict(HOOKS)}}}), encoding="utf-8")
            if not converge._set_home_serve({"*": {}}).get("services"):
                problems.append("re-declaring `serve` without `services` must keep the doors")
            pair.give("none")
            if pair.ports.served != {} or converge._set_home_serve({}).get("services"):
                problems.append("'give nothing' must close the doors too")
        finally:
            if before is None:
                os.environ.pop("DGO_STATE_DIR", None)
            else:
                os.environ["DGO_STATE_DIR"] = before
    # …and a door on the alias of an app this office publishes is left out by the office itself
    clashing = catalog.build({"apps": [dict(REGISTRY["apps"][0])]}, "hp-laptop",
                             services=[dict(DOORS[0], alias="drive")])
    if clashing.get("services") or catalog.validate(clashing):
        problems.append(f"the serving office must drop a door that clashes with its own app, got {clashing.get('services')}")
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
    secrets = {"token": "S3CRET-TOKEN", "password": "S3CRET-PW", "api_key": "S3CRET-KEY",
               "vault": {"api_key": "S3CRET-VAULT"}, "env": {"API_KEY": "S3CRET-ENV"}}
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


# ── the asset table and the audit line: where the keys are, and what an action leaves behind ─────
#: §9's first two asset rows name this volume; `identity.py`'s own docstring and `bbox`'s inventory
#: both read `data.volumes` as the declaration a backup carries it from.
IDENTITY_VOLUME = "dgo_identity"
#: The link's token writer — the module §9's third asset row is about. It comes in through `_load`,
#: the same door the two files above use: one loader for a module of this app keeps “which
#: `catalog.py`/`links.py` is this” answered in one place (see `_load`'s own docstring).
links = _load(APP / "links.py", "dgo_links")

#: A route is written `def` or `async def` — FastAPI uses both, and a check that knows only one of
#: them answers “there is no such route” about a route the office is serving at that moment.
DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _functions(path: Path) -> dict:
    """Every function in a module by name — nested ones too (`emit` lives inside the run loop)."""
    return {n.name: n for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(n, DEFS)}


def _names(node) -> set:
    """The names a piece of code actually USES — a mention in a comment or a docstring is not one."""
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _route(path: Path, verb: str, route: str):
    """The function a module registers for one route, asked of the decorator rather than its name."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, DEFS):
            continue
        for deco in node.decorator_list:
            if (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)
                    and deco.func.attr == verb and deco.args
                    and isinstance(deco.args[0], ast.Constant) and deco.args[0].value == route):
                return node
    return None


def _logged_with_moment(node, keys=("t", "step", "line")):
    """The log-line literal a record writes: one line, carrying the step and the moment it happened.

    The moment is half of §9's audit line (“who linked, placed or moved WHAT, and WHEN”), so a record
    that writes a step with no time is not counted as one: it cannot order two actions.
    """
    for n in ast.walk(node):
        if isinstance(n, ast.Dict) and set(keys) <= {k.value for k in n.keys
                                                     if isinstance(k, ast.Constant)}:
            return n
    return None


@claim("§9 · the office's keys are one root-only 0600 file, in the volume a backup carries")
def c_the_office_keys_are_root_only_and_backed_up():
    """§9's first two asset rows: the Ed25519 office identity and the WireGuard key — `root-only`, in
    their own volume, carried by the backup.

    Asked of a REAL `mint` into a temporary directory: the mode is a fact about the file `mint` writes,
    and “0600” in a docstring while the umask decides is exactly the shape of a claim nobody measured.
    The backup is asked where a backup can see it — the volume is declared in `app.json`
    `data.volumes` (the declaration the inventory reads) and the app mounts it read-only, since an app
    that can rewrite its own identity can announce itself as another office. §9's second row is
    “same”, asked as the one record: both private halves in that one 0600 file. And `mint` is
    idempotent, because §9's “a new key means announced re-pairing” is only true if a routine converge
    can NOT re-mint the key every peer knows.
    """
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        where = Path(tmp) / "identity"
        first = identity.mint(where, label="hp-laptop")
        doc = where / identity.FILE
        if not doc.exists():
            return [f"`mint` wrote no {identity.FILE} under {where} — there is nothing to ask about"]
        mode = doc.stat().st_mode & 0o777
        if mode != 0o600:
            problems.append(f"the private halves must be root-only 0600, got {oct(mode)}")
        if (where.stat().st_mode & 0o777) != 0o700:
            problems.append(f"the directory holding them must be 0700, got "
                            f"{oct(where.stat().st_mode & 0o777)}")
        if not (first.get("ed25519", {}).get("private") and first.get("wg", {}).get("private")):
            problems.append(f"§9's second row is “same”: the WireGuard key is in the SAME record as "
                            f"the Ed25519 one, got {sorted(first)}")
        again = identity.mint(where, label="hp-laptop")
        if again.get("ed25519", {}).get("private") != first["ed25519"]["private"]:
            problems.append("an existing identity must come back untouched: a key that changes in a "
                            "converge is a new office no peer was told about")
        forced = identity.mint(where, label="hp-laptop", force=True)
        if forced.get("ed25519", {}).get("private") == first["ed25519"]["private"] or \
                forced.get("wg", {}).get("private") == first["wg"]["private"]:
            problems.append("`force` IS the announced re-pairing, so it must mint new keys, got the "
                            "old ones")
        if (doc.stat().st_mode & 0o777) != 0o600:
            problems.append(f"a re-minted file must keep the mode, got {oct(doc.stat().st_mode & 0o777)}")
    manifest = json.loads((APP / "app.json").read_text(encoding="utf-8"))
    declared = [str(v) for v in ((manifest.get("data") or {}).get("volumes") or [])]
    if IDENTITY_VOLUME not in declared:
        problems.append(f"the keys live in their own volume, and `app.json` `data.volumes` is what "
                        f"makes a backup carry it (§9's Backup column) — got {declared}")
    compose = yaml.safe_load((APP / "docker-compose.yml").read_text(encoding="utf-8"))
    mounts = [str(m) for spec in (compose.get("services") or {}).values()
              for m in (spec.get("volumes") or [])]
    if not any(m.startswith(IDENTITY_VOLUME + ":") and m.endswith(":ro") for m in mounts):
        problems.append(f"the app must read its identity volume read-only, got "
                        f"{[m for m in mounts if IDENTITY_VOLUME in m]}")
    return problems


@claim("§9 · a link's token is a 256-bit vault instance (protocol `dgo_link`), one per direction")
def c_the_link_token_lives_in_the_vault():
    """§9's third asset row: “Link token (256-bit per link per direction) | vault, protocol
    `dgo_link` | vault backup”.

    `links.ensure` is the writer the running system uses and the vault is its boundary, so `_call`
    (the HTTP call — the only place a network would happen) is stood in for while the rest of `ensure`
    runs for real: what is asked is the instance it WOULD write, and what a second converge does with
    it. That second question is the one §9's whole revocation story rests on — a token re-minted by a
    converge is a token the other office does not hold, and the symptom is “the link stopped working
    after a converge”, not an error anyone sees.
    """
    problems = []
    if links.PROTOCOL != "dgo_link":
        problems.append(f"the vault protocol §9 names, got {links.PROTOCOL!r}")
    catalogue = yaml.safe_load((ROOT / "platform-base/connections/providers/40-apps.yaml")
                               .read_text(encoding="utf-8"))
    rows = catalogue if isinstance(catalogue, list) else (catalogue.get("providers") or [])
    entry = next((p for p in rows if isinstance(p, dict) and p.get("id") == "dgo-link"), None)
    if entry is None:
        problems.append("the vault's own catalogue has no `dgo-link` entry, so a link's token is not on "
                        "the screen the owner reads his accounts from")
    elif entry.get("kind") != "secret":
        problems.append(f"a link token is a secret, got kind={entry.get('kind')!r}")

    name = links.token_name("hp-laptop", "macbook", "serve")
    posts: list = []

    def minting(method, path, body=None, timeout=20):
        if method == "POST":
            posts.append(body or {})
            return {"ok": True}
        return {"instances": []}                 # this office has never held this link's token

    keep = links._call
    try:
        links._call = minting
        row = links.ensure("hp-laptop", "macbook", "serve")
    finally:
        links._call = keep
    if len(posts) != 1:
        return problems + [f"`ensure` on an empty vault must write exactly one instance, got {len(posts)}"]
    written = posts[0]
    token = str((written.get("secret") or {}).get("token") or "")
    if not (len(token) == 64 and all(c in "0123456789abcdef" for c in token)):
        problems.append(f"§9 says 256-bit: 32 random bytes, i.e. 64 hex characters, got "
                        f"{len(token)} character(s)")
    if written.get("protocol") != links.PROTOCOL or written.get("id") != name:
        problems.append(f"the instance must be the link's own (`{name}` on `{links.PROTOCOL}`), got "
                        f"{written.get('id')!r} on {written.get('protocol')!r}")
    if (written.get("secret") or {}).get("direction") != "serve":
        problems.append(f"one token per DIRECTION: the instance must name the direction it "
                        f"authorizes, got {written.get('secret')}")
    if links.token_name("hp-laptop", "macbook", "use") == name:
        problems.append("the two directions must not share one token")
    if row.get("id") != name:
        problems.append(f"a token comes back as its instance, got {row}")

    # …AND THE SECOND CONVERGE: the vault already holds the row, so nothing may be minted.
    again: list = []

    def holding(method, path, body=None, timeout=20):
        if method == "POST":
            again.append(body or {})
            return {"ok": True}
        return {"instances": [{"id": name, "protocol": links.PROTOCOL,
                               "account_hint": "hp-laptop->macbook serve"}]}

    try:
        links._call = holding
        same = links.ensure("hp-laptop", "macbook", "serve")
    finally:
        links._call = keep
    if again:
        problems.append("a link whose token exists must never be re-minted — a new token is a token "
                        "the other office does not hold")
    if same.get("id") != name:
        problems.append(f"an existing token must come back as itself, got {same}")
    # …and it is the VAULT's, so this module may hold no file to write a token into.
    links_tree = ast.parse((APP / "links.py").read_text(encoding="utf-8"))
    file_apis = {"open", "write_text", "write_bytes", "Path", "dump", "save", "mkdir"}
    uses = sorted({n.id for n in ast.walk(links_tree)
                   if isinstance(n, ast.Name) and n.id in file_apis} |
                  {n.attr for n in ast.walk(links_tree)
                   if isinstance(n, ast.Attribute) and n.attr in file_apis})
    if uses:
        problems.append(f"§9 keeps the token in the VAULT, and `links.py` uses {uses} — a token in this "
                        f"app's own files is a token in every copy of them")
    return problems


@claim("§9 · who linked, placed and moved what is recorded: run log, link history, vault events, command log")
def c_the_actions_are_recorded():
    """§9's audit line: “Audit → offices run log + connections events + computers command log”.

    Four records across three apps, each asked at the code that WRITES it — a record nobody writes is
    a record that answers nothing when the question is “who did that, and when”.
    """
    problems = []
    # 1 · THE OFFICE'S OWN RUN LOG: a converge persists its steps under the runs directory, and every
    # line carries the step and the moment it happened.
    app_py = APP / "app.py"
    functions = _functions(app_py)
    persist, emit = functions.get("_persist"), functions.get("emit")
    if persist is None:
        problems.append("app.py has no `_persist`: an office's run would live only in memory, and a "
                        "restart would erase what was done to it")
    else:
        for need in ("RUN_DIR", "_run_file"):
            if need not in _names(persist):
                problems.append(f"a run must be written down under the runs directory: `_persist` no "
                                f"longer names {need!r}")
    if emit is None:
        problems.append("the run loop no longer emits per-step lines (`emit`)")
    else:
        line = _logged_with_moment(emit)
        if line is None:
            problems.append("a run's log line must carry the moment (`t`), the step and the line — "
                            "otherwise the run log cannot answer “when”")
        elif not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "time" for n in ast.walk(line)):
            problems.append("the run log's `t` must be read from the clock, not written as a constant")
    # 2 · THE LINK'S OWN HISTORY: one line per change of the verdict — what the link DID, not only
    # what it answers now.
    history = _route(app_py, "get", "/api/link/history")
    if history is None:
        problems.append("no `/api/link/history` route: a link's transitions then leave no record")
    else:
        for need in ("load_link_history", "_link_history_path"):
            if need not in _names(history):
                problems.append(f"the link history must read the record it publishes: it no longer "
                                f"names {need!r}")
    # 3 · THE PLACEMENT HALF (§9's “moved what”): a move writes one line per step into its job.
    move_tree = ast.parse((APP / "move.py").read_text(encoding="utf-8"))
    if _logged_with_moment(move_tree) is None:
        problems.append("a move must keep a per-step record with its moment (`move.py`'s job log)")
    elif not any(isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == "job"
                 and isinstance(n.slice, ast.Constant) and n.slice.value == "log"
                 for n in ast.walk(move_tree)):
        problems.append("the move log must be the JOB's own (`job[\"log\"]`), so it survives the request")
    # 4 · THE VAULT'S EVENTS: every secret-base operation is audited, and readable newest-first.
    vault_py = ROOT / "platform-base/connections/app.py"
    vault_tree = ast.parse(vault_py.read_text(encoding="utf-8"))
    if not any(isinstance(n, ast.FunctionDef) and n.name == "_audit" for n in ast.walk(vault_tree)):
        problems.append("the vault has no `_audit` writer: a link token's connect/reveal/rotate would "
                        "leave no event")
    events = {a.value for c in ast.walk(vault_tree) if isinstance(c, ast.Call)
              and isinstance(c.func, ast.Name) and c.func.id == "_audit"
              for a in c.args if isinstance(a, ast.Constant)}
    if not events & {"reveal", "edit", "rotate", "connect", "revoke"}:
        problems.append(f"the vault's events must name what happened, got {sorted(events)}")
    if _route(vault_py, "get", "/api/audit") is None:
        problems.append("the vault's events have no door (`/api/audit`), so nobody can read them")
    # 5 · THE MACHINES' COMMAND LOG: every command an office runs on a machine is logged with it.
    exec_route = _route(ROOT / "apps/computers/app.py", "post", "/api/computers/{cid}/exec")
    if exec_route is None:
        problems.append("`computers` has no `/exec` route — there is nothing to log")
    else:
        logged = [c for c in ast.walk(exec_route) if isinstance(c, ast.Call)
                  and isinstance(c.func, ast.Attribute) and c.func.attr == "info"
                  and isinstance(c.func.value, ast.Name) and c.func.value.id == "log"]
        if not logged:
            problems.append("a command run on a machine must be logged (§9's “computers command log”): "
                            "`/exec` writes no log line")
        elif not any("exec on" in str(k.value) for c in logged for k in ast.walk(c)
                     if isinstance(k, ast.Constant)):
            problems.append(f"the command log must name the machine and the command, got "
                            f"{[k.value for c in logged for k in ast.walk(c) if isinstance(k, ast.Constant)]}")
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


@claim("§9 · the identity mapping crosses the link in the shape the far end reads")
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
    # peer's own user names.
    if entries[0]["identity"].get("from") != ["akadmin"]:
        problems.append(f"the mapping the far end keeps must be the names it was given, got "
                        f"{entries[0]['identity']}")
    # …and the SAME field written as ONE string — a hand-written block, or a peer older than the
    # list — has to land in that same list, because `render` reads `from` as a sequence of names:
    # left a string, it would be joined CHARACTER by character into `X-DGO-From`.
    string_block = json.loads(json.dumps(block))
    string_block["identity"]["from"] = "akadmin"
    for app in string_block["apps"]:
        app["identity"]["from"] = "akadmin"
    string_entries, string_errs = serve_mod.plan({"remote": [string_block]}, console)
    if string_errs or string_entries[0]["identity"].get("from") != ["akadmin"]:
        problems.append(f"a `from` given as one string must land as the same list of names, got "
                        f"{string_entries[0]['identity'] if string_entries else string_errs}")
    return problems


# ── 6. what §9 says about the OFFER, the keys and the one open port ──────────────────────────────
# The four claims below are the rest of §9's own sentences — "Pairing offer | the remote's memory,
# 10 min | none", "the six digits both screens derive", "Office identity | dgo-identity volume,
# root-only", "Not done: any public port besides WireGuard UDP". They were carried by the pairing
# module's own `selftest()` and by the phase suites, which run when a human runs them and need a peer
# in the room; asked here, they hold with no office, no tunnel and no network.
@claim("§9 · a pairing offer is public material, ten minutes long, and single-use")
def c_offer_is_public_short_and_single_use():
    problems = []
    joiner = {"ed25519": base64.b64encode(b"J" * 32).decode(), "wg": "W", "fingerprint": "AAAA-BBBB"}
    offer, eph_priv = pairing.new_offer("portable", joiner, ["192.168.16.103:51820"])
    # TEN MINUTES, and the offer carries its own window: the peer's screen counts down from
    # `expires_at`, so the number has one home (`pairing.OFFER_TTL`) and the offer must agree with it.
    if pairing.OFFER_TTL != 600:
        problems.append(f"the window §9 names is ten minutes, got OFFER_TTL={pairing.OFFER_TTL}")
    if offer["expires_at"] - offer["created_at"] != pairing.OFFER_TTL:
        problems.append(f"the offer must carry the window it was minted with, got "
                        f"{offer['expires_at'] - offer['created_at']}s")
    # PUBLIC MATERIAL ONLY: the text IS the QR payload, and a photograph of it must be worth nothing.
    # The ephemeral PRIVATE key is returned BESIDE the offer for exactly this reason, and the
    # identity in it is the public half.
    text = pairing.offer_text(offer)
    private = base64.b64encode(eph_priv).decode().rstrip("=")
    if private and private in text:
        problems.append("the offer's own text carries the ephemeral private key — a photographed QR "
                        "would then be enough")
    if offer["identity"].get("ed25519") != joiner["ed25519"] or "private" in json.dumps(offer):
        problems.append(f"the offer carries the public identity and nothing else, got {offer['identity']}")
    # …and a fact that LOOKS like a secret is refused at the door rather than trusted to the caller.
    try:
        pairing.new_offer("portable", joiner, [], extra={"link_token": "not-a-public-fact"})
        problems.append("an offer accepted a field that names a token — public material only")
    except pairing.PairingError:
        pass
    # SHORT-LIVED AND SINGLE-USE, through the store the screens poll (`pairing.Offers`): it keeps
    # offers in memory, refuses one at `expires_at + 1`, and refuses a redeemed one by name.
    clock = [1_700_000_000.0]
    offers = pairing.Offers(now=lambda: clock[0])
    offers.add(offer, eph_priv)
    if offers.state(offer["offer_id"]) != "waiting":
        problems.append(f"a minted offer is live, got {offers.state(offer['offer_id'])!r}")
    clock[0] = offer["expires_at"] + 1.0
    if offers.state(offer["offer_id"]) != "expired":
        problems.append(f"past its window the offer is expired, got {offers.state(offer['offer_id'])!r}")
    try:
        offers.get(offer["offer_id"])
        problems.append("a pair could be opened by an offer that had expired")
    except pairing.PairingError:
        pass
    claimed, claimed_priv = pairing.new_offer("portable", joiner, [], now=clock[0])
    offers.add(claimed, claimed_priv)
    offers.use(claimed["offer_id"])
    if offers.state(claimed["offer_id"]) != "confirmed":
        problems.append(f"a redeemed offer is done, got {offers.state(claimed['offer_id'])!r}")
    try:
        offers.get(claimed["offer_id"])
        problems.append("a redeemed offer was served a second time — the offer is single-use")
    except pairing.PairingError:
        pass
    return problems


@claim("§9 · the six digits are derived on both sides, from the shared secret alone")
def c_confirmation_code_both_sides():
    problems = []
    shared = hashlib.sha256(b"the-ecdh-secret").digest()
    here = pairing.sas(shared, "portable", "hp-laptop")
    there = pairing.sas(shared, "hp-laptop", "portable")
    if not re.fullmatch(r"\d{6}", here or ""):
        problems.append(f"the operator compares six digits, got {here!r}")
    if here != there:
        problems.append(f"both screens derive it from the same secret, got {here} and {there} — a code "
                        f"that depends on who typed first mismatches")
    if pairing.sas(hashlib.sha256(b"another-secret").digest(), "portable", "hp-laptop") == here:
        problems.append("the code does not depend on the shared secret")
    return problems


@claim("§9 · the office's identity is root-only on disk and crosses the link as public halves")
def c_identity_is_root_only_and_public():
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp) / "identity"
        store.mkdir(mode=0o755)          # a directory as ordinary as an install's own
        doc = identity.mint(store, label="portable")
        # ROOT-ONLY, and it is `mint` that makes it so: the store is narrowed and the key file is
        # owner-only. A world-readable identity is every peer's key, on this machine's disk.
        if stat.S_IMODE(store.stat().st_mode) != 0o700:
            problems.append(f"the identity store must be 0700, it is "
                            f"{oct(stat.S_IMODE(store.stat().st_mode))}")
        if stat.S_IMODE((store / identity.FILE).stat().st_mode) != 0o600:
            problems.append(f"{identity.FILE} must be 0600, it is "
                            f"{oct(stat.S_IMODE((store / identity.FILE).stat().st_mode))}")
        on_disk = (store / identity.FILE).read_text(encoding="utf-8")
        if "private" not in on_disk:
            problems.append("the file is where the private halves live — this one has none")
        # WHAT CROSSES IS `identity.public()` AND NOTHING ELSE: no private half of either key, in any
        # encoding, and the same is true of the offer `pairing` mints from it.
        public = identity.public(doc)
        blob = json.dumps(public, ensure_ascii=False)
        for half in (doc["ed25519"]["private"], doc["wg"]["private"]):
            if half and half in blob:
                problems.append("the public half carries a private key")
        if public.get("ed25519") != doc["ed25519"]["public"] or public.get("wg") != doc["wg"]["public"]:
            problems.append(f"the public half must be the two public keys, got {public}")
        offer, _ = pairing.new_offer("portable", public, [], extra={"label": "portable"})
        if any(doc.get(k, {}).get("private") in json.dumps(offer) for k in ("ed25519", "wg")):
            problems.append("the pairing offer carries a private half")
    return problems


#: The carriers' TCP door, exactly as dgo-net may publish it: loopback by default, onto the carrier's
#: own port (`net.CARRY_PORT`), on a host port Docker picks unless the office names one. Any other TCP
#: mapping is a door §9 says does not exist.
CARRIER_DOOR = re.compile(r"^\$\{DGO_CARRY_PUBLISH_BIND:-127\.0\.0\.1\}:\$\{DGO_CARRY_PUBLISH_PORT:-\d{0,5}\}:"
                          + str(net.CARRY_PORT) + r"/tcp$")


def _is_carrier_door(name: str, entry: str) -> bool:
    """The one TCP mapping §9 admits (2026-10-19): the carriers' door, on dgo-net, loopback by default.
    What it lets in is asked of the carrier itself (carrier/carry_test.go): nothing is answered to a
    connection that cannot name the pair, and nobody who cannot prove a pair's private key is admitted."""
    return name == "dgo-net" and bool(CARRIER_DOOR.match(str(entry)))


@claim("§9 · the link opens no port but WireGuard's UDP and the carriers' key-proved TCP door")
def c_only_wireguard_is_published():
    problems = []
    compose = yaml.safe_load((APP / "docker-compose.yml").read_text(encoding="utf-8"))
    published = [(name, str(entry))
                 for name, service in (compose.get("services") or {}).items()
                 for entry in ((service or {}).get("ports") or [])]
    # THE MAPPINGS THIS APP OWNS are the tunnel's, and the first exists for the DIALING office (whose
    # source port is the only part of the path the far end's firewall sees). §9's sentence is about
    # what a REACHABLE office publishes: WireGuard's UDP — and, for a pair that can never carry UDP,
    # the carriers' TCP door, which admits only a holder of the pair's key. Nothing else.
    udp = [(n, e) for n, e in published if e.endswith("/udp")]
    tcp = [(n, e) for n, e in published if not e.endswith("/udp")]
    if len(udp) != 1:
        problems.append(f"the link publishes exactly one UDP port — the tunnel's — got {udp}")
    if len(tcp) > 1:
        problems.append(f"the link publishes at most one TCP port — the carriers' door — got {tcp}")
    for name, entry in tcp:
        if not _is_carrier_door(name, entry):
            problems.append(f"{name} publishes {entry!r}: the link's only TCP is the carriers' door, "
                            f"dgo-net's {net.CARRY_PORT}/tcp on loopback by default")
    for name, entry in published:
        # …and it is LOOPBACK unless the office was deliberately made dialable: a mapping that binds
        # 0.0.0.0 by default would put a WireGuard listener on every install that never asked. The
        # bind is the FIRST `${VAR:-default}` of the mapping — `entry.split(':')` cannot read it, the
        # default's own colon is inside the token.
        bind = re.match(r"^\$\{[A-Z_]+:-([^}]*)\}", entry)
        if not bind:
            problems.append(f"{name} publishes {entry!r} with no loopback default — a fresh install "
                            f"would listen on every interface")
        elif bind.group(1) not in ("127.0.0.1", "localhost"):
            problems.append(f"{name} publishes {entry!r}, whose default bind is "
                            f"{bind.group(1)!r} rather than loopback")
    return problems


@claim("§9 · a link's token is 256 bits, one per link per direction, and lives in the vault")
def c_link_token_is_vault_made():
    problems = []
    if links.PROTOCOL != "dgo_link":
        problems.append(f"the token's vault protocol is §9's own name, got {links.PROTOCOL!r}")
    # The vault is the only store: `ensure` is asked for a link this office has never held, and the
    # calls it makes are recorded rather than performed (`_call` is the module's one seam — the same
    # function the running office uses to reach the credential plane).
    seen: list[tuple[str, str, dict | None]] = []
    real = links._call
    links._call = lambda method, path, body=None: (seen.append((method, path, body)), {"ok": True})[1]
    try:
        minted = links.ensure("hp-laptop", "vps1", "use", label="קישור")
    except Exception as e:                                        # noqa: BLE001 — a claim that cannot run
        links._call = real
        return [f"the token could not be minted: {type(e).__name__}: {e}"]
    finally:
        links._call = real
    posts = [(path, body) for method, path, body in seen if method == "POST"]
    if len(posts) != 1:
        problems.append(f"a link is minted INTO the vault — one create — got {seen}")
    else:
        path, body = posts[0]
        body = body or {}
        if path != "/api/instances" or body.get("protocol") != "dgo_link":
            problems.append(f"it is the credential plane that holds it, under dgo_link, got "
                            f"POST {path} protocol={body.get('protocol')!r}")
        token = str((body.get("secret") or {}).get("token") or "")
        try:
            bits = len(bytes.fromhex(token)) * 8
        except ValueError:
            bits = 0
        if bits != 256:
            problems.append(f"§9 says 256 bits per token, got {bits} bits ({token!r})")
        if (body.get("secret") or {}).get("direction") != "use":
            problems.append(f"the token records the direction it belongs to, got "
                            f"{(body.get('secret') or {}).get('direction')!r}")
        # ONE PER DIRECTION: the id is derived from office+peer+direction, so the other direction is
        # a different row and the two never share a token.
        if body.get("id") != links.token_name("hp-laptop", "vps1", "use"):
            problems.append(f"the instance id must derive from the link, got {body.get('id')!r}")
        if body.get("id") == links.token_name("hp-laptop", "vps1", "serve"):
            problems.append("the two directions share one instance id — one token would serve both")
    if minted.get("protocol") != "dgo_link" or not (minted.get("secret") or {}).get("token"):
        problems.append(f"the caller is handed the row it created, got {minted}")
    return problems


# ── the tunnel half of §9: what is reachable, from where, and on which address ───────────────────
@claim("§9 · a peer arrives at the tunnel address alone: the link opens no listener on every address")
def c_the_link_is_not_on_every_address():
    """§9's “adapter and link API never on `0.0.0.0`”, as the two things that decide it.

    `0.0.0.0` is not a stricter default to fall back on — `linkproxy._same_door` says why: it claims
    the port on every address there is, so a door bound that way collides with the office's own
    listener and leaves it with NONE (measured here 2026-10-02, and the `_serve_doors` docstring
    carries it). So the binding is asked of the renderer, and the office's PUBLIC surface is asked of
    the manifest and the compose file: the app routes one port (its own UI), the link's separate
    listener is not an edge route at all, and the only published port in the whole app is the
    tunnel's WireGuard UDP — bound to loopback unless the owner makes that office a listener.

    The other half of §9's sentence — “and on the endpoint only during a pairing window” — is
    satisfied by a STRONGER fact rather than by a window: nothing here ever binds the endpoint. The
    pairing is not a transient listener at all; it runs through the app's own route (see
    `pair_api.py`, whose offer lives in memory and expires — `c_the_offer_lives_only_in_memory`).
    """
    problems = []
    own = catalog.with_control(NARROW)
    rules = linkproxy._serve_doors("macbook", 3, "10.79.3.1", "10.79.3.2", own)
    if not rules:
        problems.append("`serve:` naming one app must open the door and the catalog — got no rule at "
                        "all, so a served app is unreachable rather than over-exposed")
    for rule in rules:
        if rule.get("bind") != "10.79.3.1":
            problems.append(f"a door of a served link must bind THIS office's tunnel address "
                            f"(10.79.3.1), got {rule.get('app')!r}: {rule.get('bind')!r}")
    if linkproxy._serve_doors("macbook", 3, "10.79.3.1", "10.79.3.2", {}):
        problems.append("an office that serves nothing must open no listener at all — a door onto "
                        "nothing is worse than a closed one, because it looks open")
    plan = linkproxy.build_multi(
        {"id": "hp-laptop", "tunnel": {"slot": 1}, "serve": NARROW},
        [{"office": {"id": "macbook", "tunnel": {"slot": 3},
                     "links": [{"office": "hp-laptop", "direction": "use"}]},
          "slot": 3, "side": 1}])
    for rule in plan["rules"]:
        if rule["direction"] == "serve" and str(rule.get("bind") or "") not in ("10.79.3.1",):
            problems.append(f"the rendered plan must carry the same binding, got {rule}")

    manifest = json.loads((APP / "app.json").read_text(encoding="utf-8"))
    routed = sorted({int(r.get("port") or 0) for r in (manifest.get("routing") or [])})
    if routed != [int(catalog.CATALOG_PORT)]:
        problems.append(f"this app's ONE edge route is its own UI port ({catalog.CATALOG_PORT}), got "
                        f"{routed}")
    if int(catalog.LINK_PORT) in routed:
        problems.append(f"the link's listener ({catalog.LINK_PORT}) must not be an edge route: a "
                        f"routed port would make every route of this app a peer's as well (that is "
                        f"the hole the second listener was built to close, 2026-10-05)")

    compose = yaml.safe_load((APP / "docker-compose.yml").read_text(encoding="utf-8"))
    published = {name: list(svc.get("ports") or [])
                 for name, svc in (compose.get("services") or {}).items() if svc.get("ports")}
    for name, entries in published.items():
        for entry in entries:
            if not str(entry).endswith("/udp") and not _is_carrier_door(name, str(entry)):
                problems.append(f"{name} publishes {entry!r} — §9 leaves WireGuard UDP and the "
                                f"carriers' key-proved door as the only ports on a reachable office, "
                                f"and nothing else may be one")
            if "127.0.0.1" not in str(entry):
                problems.append(f"{name} publishes {entry!r} on every address by default — the "
                                f"mapping is meant to bind loopback until the owner names a listening "
                                f"office, so an office that never opted in publishes nothing")
    return problems


@claim("§9 · a stolen token opens nothing on its own: the door needs the tunnel's own source as well")
def c_a_token_alone_opens_nothing():
    """§9's “Stolen token → useless without the peer's WireGuard key; revoke = remove link”.

    Two conditions, and the second is what makes a leak survivable: the door's rule matches on
    `ClientIP` — the peer's tunnel address, which only its WireGuard key puts a packet at — beside
    the token. A token read out of a vault, a log or a screenshot therefore matches no router
    anywhere, which is why the check is on the RULE and not on the secrecy of the string. And
    revocation is asked as the same renderer: a peer that is gone from the declaration leaves no
    listener and no source on this edge.
    """
    problems = []
    peer_serve = {"office": "macbook", "address": "10.79.3.2", "direction": "serve",
                  "ports": {"drive": 8975}}
    g = firewall.guard([peer_serve])
    if g["sources"] != ["10.79.3.2/32"]:
        problems.append(f"the door may be opened to the peer's tunnel address alone, got {g}")
    rule = firewall.peer_rule("peer.office.example", "tok", "drive", g["sources"])
    for must in (f"ClientIP(`{peer_serve['address']}/32`)", "Header(`X-Office-Peer`, `tok`)",
                 "PathPrefix(`/drive`)"):
        if must not in rule:
            problems.append(f"the remote door's rule must carry {must} — a rule missing any one of "
                            f"the three matches from somewhere it should not, got {rule!r}")
    # …AND THE SAME QUESTION ABOUT THE VERSION §9 NAMES FIRST: a `use` peer may not arrive, so its
    # token is worth nothing here even if every byte of it is known.
    if firewall.guard([{"office": "macbook", "address": "10.79.3.2", "direction": "use"}])["sources"]:
        problems.append("a `use` link may not arrive at all, so it must open no door on this edge")
    if "ClientIP" not in firewall.guard([])["rule"] or firewall.guard([])["sources"]:
        problems.append("revoking a link must leave an edge guard that matches NOBODY, got "
                        f"{firewall.guard([])}")
    # AND THE DECLARATION SIDE, the other half of “revoke = remove link”: the peer's doors are a
    # function of what THIS office serves, so a link this office does not hold renders no listener.
    if linkproxy._serve_doors("macbook", 3, "10.79.3.1", "10.79.3.2", {}):
        problems.append("no `serve:` means no door, not a door with an empty route table")
    return problems


@claim("§9 · commit drift is refused before a move: two commits are two different apps")
def c_commit_drift_is_refused():
    """§9's “Commit drift → placements refused”, in the shape the model has today.

    A move carries an app's declaration and its data to a machine that checks out a COMMIT — so two
    revisions are two different apps, and the refusal is what keeps a move from writing the client's
    data into another build. `move._same_commit` is the decision itself (short sha against
    `git rev-parse HEAD`, with the six-character trap named in its own docstring), and the guard that
    refuses is `_step_preflight` — asked of THAT function's own names rather than of a neighbour, so
    a move that stopped checking cannot pass by inheriting the mention from somewhere else.
    """
    problems = []
    short, full = "719537ab", "719537abcdef0123456789abcdef0123456789a"
    if not move._same_commit(short, full):
        problems.append("a declared short sha must equal the full HEAD it names")
    if move._same_commit(short, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"):
        problems.append("two different commits must never compare equal — that is the whole thing "
                        "being checked")
    if move._same_commit("719537", short):
        problems.append("six characters must NOT be accepted as the same commit: `_same_commit`'s "
                        "own docstring names that as the trap it exists to avoid")
    if move._same_commit("", full) or move._same_commit(full, ""):
        problems.append("an office with no declared commit must not compare equal to one that has a "
                        "commit — silence is not agreement")
    # The guard itself: `_step_preflight` is the function that refuses, and the names below are its
    # OWN (`co_names`), not its module's: the comparison, an escape hatch that must be deliberate,
    # and the refusal it raises.
    own = set(move._step_preflight.__code__.co_names)
    for need, why in (("_same_commit", "the preflight must COMPARE the commits it is handed"),
                      ("_tree_at", "the app's own tree is what must match, not only the sha"),
                      ("MoveFailed", "the refusal must be raised, not logged")):
        if need not in own:
            problems.append(f"{why}: `_step_preflight` no longer names {need!r} ({sorted(own)})")
    # The override is read as a key off the job (`ctx.get("allow_mismatch")`), so it is a CONSTANT of
    # the function rather than a name in it — asked for where it actually lives.
    if "allow_mismatch" not in set(move._step_preflight.__code__.co_consts):
        problems.append("a mismatch must be an explicit operator override: `_step_preflight` no "
                        "longer reads `allow_mismatch` at all, so nothing bounds the comparison")
    return problems


@claim("§9 · the pairing offer lives in the remote's memory for ten minutes and is never on disk")
def c_the_offer_lives_only_in_memory():
    """§9's asset row: “Pairing offer | remote's memory, 10 min | none”.

    An offer is a photographed QR code: its whole value is that it is short-lived, and an offer that
    survives a restart is one that can be redeemed after the room has emptied. So “in memory” is
    asked of the CLASS's own code — not of a docstring that says so — and single-use and expiry are
    asked by redeeming one.
    """
    problems = []
    if pairing.OFFER_TTL != 600:
        problems.append(f"the offer's ten minutes are the constant the screens and the refusals both "
                        f"read, got OFFER_TTL={pairing.OFFER_TTL}")
    tree = ast.parse((APP / "pairing.py").read_text(encoding="utf-8"))
    cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Offers"), None)
    if cls is None:
        problems.append("pairing.Offers is not in pairing.py — the offer store moved, and this claim "
                        "then checks nothing")
        return problems
    writes = ("write_text", "write_bytes", "open", "dump", "mkdir", "makedirs", "touch", "replace",
              "unlink", "Path")
    touched = sorted({n.attr if isinstance(n, ast.Attribute) else n.id
                      for n in ast.walk(cls)
                      if (isinstance(n, ast.Attribute) and n.attr in writes)
                      or (isinstance(n, ast.Name) and n.id in writes)})
    if touched:
        problems.append(f"an offer must never reach the disk (§9: the remote's MEMORY, no backup), "
                        f"and `Offers` uses {touched}")

    clock = {"t": time.time()}
    store = pairing.Offers(now=lambda: clock["t"])
    offer, _priv = pairing.new_offer("macbook", {"ed25519": "P", "wg": "W", "fingerprint": "A-B-C-D"},
                                     ["192.168.16.102:51830"], now=clock["t"])
    store.add(offer, b"x" * 32)
    if store.state(offer["offer_id"]) != "waiting":
        problems.append(f"a fresh offer is waiting to be claimed, got {store.state(offer['offer_id'])}")
    store.get(offer["offer_id"])                                   # readable once
    store.use(offer["offer_id"])                                   # the code matched: redeemed
    try:
        store.get(offer["offer_id"])
        problems.append("an offer that was redeemed must not be readable again — a photographed code "
                        "that still works is exactly the hole §9 calls “rogue office by QR”")
    except pairing.PairingError:
        pass
    fresh, _ = pairing.new_offer("macbook", {"ed25519": "P", "wg": "W", "fingerprint": "A-B-C-D"},
                                 ["192.168.16.102:51830"], now=clock["t"])
    store.add(fresh, b"y" * 32)
    clock["t"] += pairing.OFFER_TTL + 1
    if store.state(fresh["offer_id"]) != "expired":
        problems.append(f"an offer past its ten minutes is expired, got {store.state(fresh['offer_id'])}")
    try:
        store.get(fresh["offer_id"])
        problems.append("an expired offer must not be readable — the window is what makes the code "
                        "two people read out loud worth comparing")
    except pairing.PairingError:
        pass
    return problems


@claim("§9 · WireGuard's UDP and the carriers' key-proved door are the only surfaces this app adds")
def c_wireguard_udp_is_the_only_public_port():
    """§9's closing “Not done: … any public port besides WireGuard UDP on a reachable office”, and
    the one exception it names since 2026-10-19: the carriers' TCP door (`_is_carrier_door`).

    Read as the manifest and the two compose files that decide it: the app's edge routes are its own
    authenticated UI, and the ONE published port in the whole app is the tunnel's UDP mapping — which
    binds loopback unless the owner names a listening office, so an office that never opted in
    publishes nothing at all. The two things §9 says are NOT DONE (shared passwords, authentik
    federation) are negatives, and this is where a negative is worth checking: a second door is a
    port, a route, or a protocol this file would have to name — and it names none of them.
    """
    problems = []
    if not net.WG_PORT:
        problems.append("the WireGuard listen port is a constant of the addressing model, got "
                        f"{net.WG_PORT!r}")
    manifest = json.loads((APP / "app.json").read_text(encoding="utf-8"))
    for route in manifest.get("routing") or []:
        if str(route.get("auth") or "") != "sso":
            problems.append(f"every route this app adds to the office is behind its own SSO, got "
                            f"{route.get('host')}: auth={route.get('auth')!r}")
    for name, doc in (("apps/dgo-extend/docker-compose.yml",
                       yaml.safe_load((APP / "docker-compose.yml").read_text(encoding="utf-8"))),):
        for svc, spec in (doc.get("services") or {}).items():
            for entry in (spec.get("ports") or []):
                if "/udp" not in str(entry) and not _is_carrier_door(svc, str(entry)):
                    problems.append(f"{name}: {svc} publishes {entry!r} — a TCP port published on the "
                                    f"host is an office-wide door §9 says does not exist")
    # A negative is also a claim about THIS file: no shared-password or federation surface may be
    # reached from a link, so no route of the link's own listener may mention one.
    link_routes = _link_listener_routes()
    for path in link_routes:
        if any(word in path.lower() for word in ("password", "federat", "ldap", "saml")):
            problems.append(f"the link listener answers {path!r} — §9 lists shared passwords and "
                            f"authentik federation as deliberately NOT done ({link_routes})")
    if not link_routes:
        problems.append("the link listener serves no route at all — the catalog a peer pulls is the "
                        "one thing it is for, so this check has stopped measuring anything")
    return problems


#: The edge route of the link DOOR (carrier/door.go, join_api.py), exactly: one host, four paths. The fourth,
#: `/relay`, is the herd's hub joining two OTHER offices' declared pairs (carrier/relay.go, DGO-1097): it was
#: answered by the door and 404'd at the edge until the rule named it (2026-11-01, ac1fbcc1).
DOOR_RULE = re.compile(r"^Host\(`\$\{DGO_LINK_HOST:-link\.localhost\}`\) && \(Path\(`/carry`\) \|\| "
                       r"Path\(`/relay`\) \|\| Path\(`/join`\) \|\| PathPrefix\(`/join/`\)\)$")


@claim("§9 · the link door at the edge answers a carrier, another pair's relay, a join and its state — on TLS, "
       "and nothing else")
def c_the_link_door_is_three_paths():
    """2026-10-19 (join_api.py): an office that can reach another only over HTTPS joins it and carries
    its pair through ONE route at that office's edge. It has no sign-in in front of it on purpose — a
    machine with no screen cannot sign in — so what it admits must be what a KEY admits, and nothing it
    answers may be the app's own API. Read from the three places that decide it: the compose labels
    (one router, the four paths, websecure only, onto the door's unpublished port), the app's public
    join router (two routes), and the door's own path switch, which 404s everything else whatever the
    edge's rule says (carrier/ws_test.go: TestTheDoorAnswersItsThreePathsAndNothingElse)."""
    problems = []
    compose = yaml.safe_load((APP / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose.get("services") or {}
    door_port = net.DOOR_LISTEN.rsplit(":", 1)[1]
    routers = {}
    for svc, spec in services.items():
        for label in (spec or {}).get("labels") or []:
            m = re.match(r"^traefik\.http\.routers\.([a-z0-9-]+)\.(rule|entrypoints|tls|service)=(.*)$", str(label))
            if m:
                routers.setdefault((svc, m.group(1)), {})[m.group(2)] = m.group(3)
            if str(label).startswith("traefik.") and svc != "dgo-net":
                problems.append(f"{svc} carries an edge label ({label}) — the link door is dgo-net's alone")
    if list(routers) != [("dgo-net", "dgo-extend-link-door")]:
        problems.append(f"the link adds exactly ONE edge router, the door on dgo-net, got {list(routers)}")
    door = routers.get(("dgo-net", "dgo-extend-link-door")) or {}
    if not DOOR_RULE.match(door.get("rule") or ""):
        problems.append(f"the door's rule is its host and the four paths, nothing wider: {door.get('rule')!r}")
    if door.get("entrypoints") != "websecure" or door.get("tls") != "true":
        problems.append(f"the door is served on TLS only (websecure), got {door}")
    labels = [str(x) for x in (services.get("dgo-net") or {}).get("labels") or []]
    if f"traefik.http.services.dgo-extend-link-door.loadbalancer.server.port={door_port}" not in labels:
        problems.append(f"the edge hands the door to its own listener ({net.DOOR_LISTEN}), got {labels}")
    for svc, spec in services.items():
        for entry in (spec or {}).get("ports") or []:
            if door_port in str(entry):
                problems.append(f"{svc} publishes {entry!r} — the door is reached through the edge only")
    source = ast.parse((APP / "join_api.py").read_text(encoding="utf-8"))
    builder = next((n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "build_public_router"), None)
    routes = sorted((d.func.attr, d.args[0].value) for n in ast.walk(builder or ast.Module(body=[], type_ignores=[]))
                    if isinstance(n, ast.AsyncFunctionDef) for d in n.decorator_list
                    if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.args
                    and isinstance(d.args[0], ast.Constant))
    if routes != [("get", "/join/{rid}"), ("post", "/join")]:
        problems.append(f"the public join router is POST /join and GET /join/<id>, got {routes}")
    door_go = (APP / "carrier" / "door.go").read_text(encoding="utf-8")
    if ('case r.URL.Path == "/carry":' not in door_go or 'case r.URL.Path == "/relay":' not in door_go
            or "http.NotFound(w, r)" not in door_go):
        problems.append("the door's own switch names /carry, /relay and the join paths, and 404s the rest")
    return problems


def _link_listener_routes():
    """The routes of `app.py`'s SECOND listener (`link_app`), read off the module rather than guessed:
    §9's “not done” list is about what a peer can reach, and a peer reaches only these."""
    source = ast.parse((APP / "app.py").read_text(encoding="utf-8"))
    app = next((n for n in source.body if isinstance(n, ast.Assign)
                and any(getattr(t, "id", "") == "link_app" for t in n.targets)), None)
    if app is None:
        return []
    out = []
    for node in source.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for deco in node.decorator_list:
            if (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)
                    and isinstance(deco.func.value, ast.Name) and deco.func.value.id == "link_app"
                    and deco.args and isinstance(deco.args[0], ast.Constant)):
                out.append(deco.args[0].value)
    return out


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
