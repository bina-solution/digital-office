#!/usr/bin/env python3
"""test_give — what the herd file gives by name stays given, whatever `serve:` says (DGO-1433).

The incident, replayed: on 2026-11-06 at 12:56 the HP's group answerer wrote a `serve:` of seven apps over the
HP's own, and bina, bina-claude and browser42 left vps1 and the MacBook while links pointed at them. Asked here
through the catalog a linked office pulls and its door routes by (`build_catalog(office=…)`), the delivery plan
that opens the agent doors (`linkproxy.build_multi`), the writer's answer (`_withdrawal`), and home.json itself:
  * the herd's `give:` reaches the office it names, by name, on top of any `serve:` — named, narrowed, `*`, empty;
  * it is never written into home.json (a line taken out of the herd file withdraws it again);
  * by key: this office's own key and the peer's record key must be the herd file's, else nothing is given by it;
  * the writer's answer says what it withdrew from whom, and what the herd keeps;
  * the real apps/computers/herd.yaml gives vps1 and the MacBook the HP's agent, Claude and office browser.

Run: python3 apps/dgo-extend/tests/test_give.py   (needs PyYAML; app.py loaded as test_app_input loads it)
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
# Hermetic: nothing here may reach a live office's tunnel or identity (second reader — inside a dgo-extend
# container a real render would rewrite its nftables rules and drop its pairs)
for _var in ("DGO_TUNNEL_DIR", "DGO_IDENTITY_DIR"):
    os.environ[_var] = tempfile.mkdtemp(prefix=f"dgo-give-{_var.lower()}-")
spec = importlib.util.spec_from_file_location("test_app_input", HERE / "test_app_input.py")
tai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tai)
app = tai.load()
app.render_tunnel = lambda *a, **k: {}
cv = app.cv
catalog = app.catalog
import give  # noqa: E402 — app.py's directory is on the path once it is loaded
import identity as idmod  # noqa: E402
import linkproxy  # noqa: E402

FAIL: list[str] = []
KEY = {"macbook": "+0B1Hc+7nYPESAjx/uu3JSDeuYQYadu7dvV0eb/C5B8=",
       "hp-laptop": "OUBWvxLVZJDWW19J9sZPePVPi3i1rickvdqcXagbbns=",
       "dell": "goMFvhsFv7EUbKsnI2PGwdBOnEFdhdIzMBBp8axs4Vg=",
       "vps1": "ka9qFHK11KwtSPR1MDftp9Kpd9yb8Y6rvmf2ESWLHgQ="}
OTHER = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="      # a valid key that is none of ours
HERD = """\
offices:
  macbook: {label: MacBook, wg_public_key: '%(macbook)s'}
  hp-laptop: {label: HP, wg_public_key: '%(hp-laptop)s'}
  dell: {aliases: [portable-ubuntu, portable], wg_public_key: '%(dell)s'}
  vps1: {link_host: link.staging.digital-office.co.il, public: true, wg_public_key: '%(vps1)s'}
hub: vps1
admin_apps: [connections, computers, bina-ds, bina-claude, claude-terminal, browser42]
give:
  hp-laptop:
    vps1: [bina-ds, bina-claude, browser42, telegram, newsflow, project-pln]
    macbook: [bina-ds, bina-claude, browser42, computers, project-pln]
""" % KEY
#: The HP's registry, as its compiler renders the tiles the incident is about (ports as declared)
REGISTRY = {"apps": [
    {"app": "bina-ds", "alias": "bina", "name": "בינה", "port": 3080, "agent_api_port": 3081},
    {"app": "bina-claude", "alias": "bina-claude", "name": "בינה קלוד", "port": 3000},
    {"app": "bina-claude", "alias": "claude-terminal", "name": "בינה קלוד · מסוף", "port": 7681},
    {"app": "browser42", "alias": "browser42", "name": "דפדפן הלשכה", "port": 6080, "agent_api_port": 8931},
    {"app": "telegram", "alias": "telegram", "name": "טלגרם", "port": 8984},
    {"app": "newsflow", "alias": "newsflow", "name": "זרימת חדשות", "port": 8991},
    {"app": "project-pln", "alias": "plane", "name": "ניהול פרויקטים", "port": 80},
    {"app": "computers", "alias": "computers", "name": "מחשבים", "port": 8977},
    {"app": "dashboard", "alias": "dashboard", "name": "מרכז הבקרה", "port": 80},
    {"app": "drive", "alias": "drive", "name": "קבצים", "port": 8975},
    {"app": "calculator", "alias": "calculator", "name": "מחשבון", "port": 8997}]}
#: The HP's `serve:` after 12:56 — the seven apps the answerer declared — and vps1's narrowing as it was
INCIDENT = {"newsflow": {"port": 8991}, "drive": {"port": 8975}, "computers": {"port": 8977},
            "telegram": {"port": 8984}, "calculator": {"port": 8997}, "project-pln": {"port": 80},
            "dashboard": {"port": 80},
            "only": {"vps1": ["telegram", "newsflow", "plane", "bina", "bina-claude", "browser42"]}}
RECORDS = {"macbook": KEY["macbook"], "vps1": KEY["vps1"], "portable-ubuntu": KEY["dell"]}


def check(cond, what):
    if not cond:
        FAIL.append(what)


def setup(me: str, serve: dict, herd: str | None = HERD, my_key: str | None = None, records: dict = RECORDS):
    """A scratch office called `me`: home.json with `serve`, the herd file, its registry and its peers' records."""
    state = Path(os.environ["DGO_STATE_DIR"])
    key = my_key if my_key is not None else KEY.get(me, OTHER)
    (state / cv.HOME_FILE).write_text(json.dumps({"id": me, "serve": serve, "tunnel": {"slot": 1}}), encoding="utf-8")
    d = Path(tempfile.mkdtemp(prefix="dgo-give-"))
    if herd is not None:
        (d / "herd.yaml").write_text(herd, encoding="utf-8")
    give.HERD_FILE = d / "herd.yaml"
    app.HERD_FILE = d / "herd.yaml"
    reg = Path(tempfile.mkdtemp(prefix="dgo-give-reg-"))
    (reg / "office.apps.json").write_text(json.dumps(REGISTRY), encoding="utf-8")
    os.environ["DGO_REGISTRY_DIR"] = str(reg)
    app.REGISTRY_DIR = str(reg)
    idmod.public = lambda: {"office": me, "wg": key}
    app.DECL_DIR.mkdir(parents=True, exist_ok=True)
    for f in app.DECL_DIR.glob("*.yaml"):
        f.unlink()
    for rid, rkey in records.items():
        (app.DECL_DIR / f"{rid}.yaml").write_text(f"id: {rid}\nkind: paired\nidentity:\n  wg: '{rkey}'\n")


def given(office: str) -> list[str]:
    return sorted(r.get("alias") for r in app.build_catalog(office=office).get("apps") or [])


def on_disk() -> dict:
    return json.loads((Path(os.environ["DGO_STATE_DIR"]) / cv.HOME_FILE).read_text(encoding="utf-8"))["serve"]


def main() -> int:
    # ── the incident: seven apps written over the HP's list ─────────────────────────────────────────────────────
    setup("hp-laptop", INCIDENT)
    v, m = given("vps1"), given("macbook")
    for a in ("bina", "bina-claude", "browser42", "telegram", "newsflow", "plane"):
        check(a in v, f"vps1 is given {a} by the herd whatever serve: says: {v}")
    for a in ("bina", "bina-claude", "browser42", "computers", "plane"):
        check(a in m, f"the MacBook is given {a} by the herd: {m}")
    check("calculator" not in v, f"…and vps1 is still narrowed by its own only: list: {v}")
    check("calculator" in m and "drive" in m, f"…and the MacBook keeps what serve: gives it: {m}")
    check(on_disk() == INCIDENT, f"the floor is NEVER written into home.json: {on_disk()}")
    eff = cv.home_office()["serve"]
    check(eff["bina-ds"] == {"port": 3080} and eff["bina-claude"] == {"port": 3000},
          f"a floor app is named with its OWN tile's registry port: {eff.get('bina-ds')}, {eff.get('bina-claude')}")
    check(INCIDENT["only"]["vps1"] == ["telegram", "newsflow", "plane", "bina", "bina-claude", "browser42"],
          "merge never changes the map it was given")
    d = given("portable-ubuntu")
    check({"bina", "bina-claude", "browser42", "drive"} <= set(d),
          f"a NAMED app reaches every office only: does not narrow — the Dell, a home office, as under `*` before "
          f"12:56 (give.merge's docstring and herd.yaml say so): {d}")

    # what a writer reads back is what home.json HOLDS, never the floor (second reader: read, edit, write whole)
    written = cv.home_serve_written()
    check(written == INCIDENT, f"home_serve_written() is the volume's own map: {written}")
    check(app._PairPorts().serve() == INCIDENT if hasattr(app, "_PairPorts") else True,
          "the pairing screen's serve() is the volume's own map")
    cv.set_home_serve(written)
    check(on_disk() == INCIDENT, f"a read-modify-write round trip stores no floor: {on_disk()}")

    # the agent door the MacBook's `bbox agent --office hp-laptop` uses, through the delivery plan
    home = cv.home_office()
    plan = linkproxy.build_multi(home, [{"office": {"id": "macbook", "tunnel": {"slot": 5}}, "slot": 5, "side": 1}],
                                 registry=REGISTRY)
    agent_ports = sorted(r["port"] for r in plan["rules"] if r.get("kind") == "agent" or r.get("app") == "bina-ds")
    check(any(r.get("app") == "bina-ds" for r in plan["rules"]),
          f"the delivery plan opens bina-ds's agent door for the MacBook: {agent_ports}")
    plan = linkproxy.build_multi(home, [{"office": {"id": "vps1", "tunnel": {"slot": 3}}, "slot": 3, "side": 1}],
                                 registry=REGISTRY)
    check(any(r.get("app") == "bina-ds" for r in plan["rules"]),
          "…and for vps1, whose only: list named the tile `bina` and not the app id the door is keyed by")
    # …and the agent's token is named for it (api_link_agent hands it only to a NAMED agent)
    check("bina-ds" in app._named_agents(home, "macbook"), "the herd's name counts as a name for the agent token")
    check("bina-ds" not in app._named_agents(home, "portable-ubuntu"),
          "…for the office it names only: the Dell sees the tile, and is handed no token for it")
    check("bina-ds" in app._named_agents(home, "vps1"), "…and vps1, named, is")

    # ── the shapes `serve:` takes ───────────────────────────────────────────────────────────────────────────────
    setup("hp-laptop", {})
    want = ["bina", "bina-claude", "browser42", "newsflow", "plane", "telegram"]
    if not hasattr(app, "_admin_withheld"):
        # without DGO-1360's rule a NAMED app reaches every office only: does not narrow — the MacBook's computers
        # and bina-claude's terminal too — exactly as a name in `serve:` always has
        want = sorted(want + ["claude-terminal", "computers"])
    check(given("vps1") == want, f"serve: {{}} (nothing) — the herd's apps reach vps1: {given('vps1')}")
    everything = ["bina", "bina-claude", "browser42", "claude-terminal", "computers", "newsflow", "plane", "telegram"]
    check(given("macbook") == everything, f"…the MacBook, a home office, every named one: {given('macbook')}")
    check("drive" not in given("macbook"), "…and nothing the herd does not name")

    # a sibling tile named alone is keyed by its own alias: the desktop never takes the terminal's port
    one = HERD.split("give:")[0] + "give:\n  hp-laptop:\n    macbook: [claude-terminal]\n"
    setup("hp-laptop", {"drive": {"port": 8975}}, herd=one)
    eff = cv.home_office()["serve"]
    check(eff.get("claude-terminal") == {"port": 7681} and "bina-claude" not in eff,
          f"a sibling tile is keyed by its alias, with its own port: {eff}")
    # …and an office already narrowed is never widened by a name its list held for an app the map did not serve
    setup("hp-laptop", {"drive": {"port": 8975}, "only": {"vps1": ["drive", "claude-terminal"]}}, herd=one)
    check("claude-terminal" not in given("vps1") and given("vps1") == ["drive"],
          f"vps1's list named claude-terminal while it was not served; the floor serves it for the MacBook only: "
          f"{given('vps1')}")
    check("claude-terminal" in given("macbook"), "…and the MacBook it is given to has it")
    # a sibling named for one office does not stop the app's own tile from being added for another
    two = HERD.split("give:")[0] + "give:\n  hp-laptop:\n    macbook: [claude-terminal]\n    vps1: [bina-claude]\n"
    setup("hp-laptop", INCIDENT, herd=two)
    eff = cv.home_office()["serve"]
    check(eff.get("claude-terminal") == {"port": 7681} and eff.get("bina-claude") == {"port": 3000},
          f"both tiles keyed, each with its own port: {eff.get('claude-terminal')}, {eff.get('bina-claude')}")
    check("bina-claude" in given("vps1"), f"vps1 is given the desktop the herd names for it: {given('vps1')}")
    setup("hp-laptop", {"*": {}, "exclude": ["claude-terminal"]})
    check("claude-terminal" not in given("macbook") and "bina-claude" in given("macbook"),
          "a floor tile leaves exclude:, and only that tile — the excluded terminal stays excluded")
    setup("hp-laptop", {"*": {}, "only": {"vps1": []}})
    check("bina" in given("vps1") and "drive" not in given("vps1"),
          f"an EMPTY only: list is a statement, and the herd's word wins over it: {given('vps1')}")
    setup("hp-laptop", {"*": {}, "exclude": ["bina-claude", "drive"]})
    check("bina-claude" in given("vps1") and "drive" not in given("macbook"),
          "exclude: publishes to nobody — the herd's names leave it, the rest stays excluded")
    setup("hp-laptop", {"*": {}})
    check(not [k for k in cv.home_office()["serve"] if k not in ("*", "only", "exclude")],
          "under `*` nothing is added as a key (no app without a port reaches the plan)")

    # ── by key, never by name ───────────────────────────────────────────────────────────────────────────────────
    setup("hp-laptop", INCIDENT, my_key=OTHER)
    check("bina" not in given("macbook"), "this office's key is not the herd file's: nothing is given by it")
    narrowed = {"telegram": {"port": 8984}, "only": {"vps1": ["telegram"]}}
    setup("hp-laptop", narrowed, records={**RECORDS, "vps1": OTHER})
    check(given("vps1") == ["telegram"] and "bina" in given("macbook"),
          f"a peer CALLED vps1 with another key gets nothing by the herd ({given('vps1')}); the real MacBook still does")
    setup("examplef", INCIDENT)
    check("bina" not in given("vps1"), "an office the herd file does not name applies no give: of ours")
    setup("hp-laptop", INCIDENT, herd=None)
    check("bina" not in given("vps1"), "no herd file: serve: as it is")
    setup("hp-laptop", INCIDENT, herd=HERD + "since: 2026-11-31\n")
    try:
        check("bina" not in given("vps1"), "a herd file YAML refuses: serve: as it is")
    except Exception as e:                                  # noqa: BLE001
        check(False, f"a herd file YAML refuses must never fail the catalog: {type(e).__name__}")
    setup("hp-laptop", INCIDENT, herd=HERD.replace("vps1: [bina-ds,", "vps1: [BINA DS!, bina-ds,"))
    check("bina" in given("vps1"), "a name that is not one is dropped, never guessed — the rest still holds")
    setup("hp-laptop", INCIDENT, herd=HERD.replace("aliases: [portable-ubuntu, portable]", "aliases: true"))
    check("bina" in given("vps1"), "aliases: true names nobody — and raises nothing")

    # ── the writer's answer: what it took away, from whom, and what the herd keeps ──────────────────────────────
    setup("hp-laptop", {"*": {}})
    before = app._given_now()
    cv.set_home_serve({"drive": {"port": 8975}})
    report = app._withdrawal(before)
    gone = report.get("withdrawn") or {}
    check("dashboard" in gone.get("macbook", []), f"the answer names what the write withdrew from the MacBook: {gone}")
    check("bina" not in gone.get("macbook", []), "…and not what the herd kept")
    check(report.get("given_by_herd", {}).get("vps1") == sorted(
        ["bina-ds", "bina-claude", "browser42", "telegram", "newsflow", "project-pln"]),
        f"…and names what the herd keeps: {report.get('given_by_herd')}")
    if hasattr(app, "api_link_serve") and not app.STOOD_IN:
        out = asyncio.run(app.api_link_serve(tai._Asked({"serve": {"drive": {"port": 8975}}})))
        check(isinstance(out, dict) and "given_by_herd" in out, f"POST /api/link/serve answers with it: {out}")

    # ── mac-dgo's admin rule (DGO-1360), where it exists: a name in the herd's give: is a name ─────────────────
    if hasattr(app, "_admin_withheld"):
        setup("hp-laptop", {"*": {}})
        w = app._admin_withheld("vps1")
        check("bina-ds" not in w and "browser42" not in w, f"the herd's names are not withheld from vps1: {sorted(w)}")
        check("claude-terminal" in w and "connections" in w, f"…and what it does not name still is: {sorted(w)}")

    # ── a DOOR the herd gives (DGO-2125): the HP's signer page, narrowed to /s/ and opened, to vps1 ──────────────
    door_herd = HERD.replace("telegram, newsflow, project-pln]",
                             "telegram, newsflow, project-pln, {door: esign-public, paths: [/s/], public: true}]", 1)
    check(door_herd != HERD, "the test's herd file holds the door line")

    def door_registry():
        reg = Path(os.environ["DGO_REGISTRY_DIR"])
        (reg / "office.apps.json").write_text(json.dumps(dict(REGISTRY, services=[
            {"app": "esign", "alias": "esign-public", "port": 8080}])), encoding="utf-8")

    def doors_of(office: str) -> dict:
        return {s["alias"]: s for s in app.build_catalog(office=office).get("services") or []}

    setup("hp-laptop", INCIDENT, herd=door_herd)          # a map written with no `services` at all
    door_registry()
    v = doors_of("vps1")
    check(v.get("esign-public", {}).get("paths") == ["/s/"] and v["esign-public"].get("public") is True,
          f"the herd gives vps1 the door, narrowed and opened, though the map names no door: {v}")
    check("esign-public" not in doors_of("macbook"), f"…and no other office: {doors_of('macbook')}")
    check(on_disk() == INCIDENT and cv.home_serve_written() == INCIDENT,
          f"the door is never written into home.json, and a writer reads back the map as written: {on_disk()}")
    # the map's own entry for it: the herd's paths and consent win — and NEVER WIDER for an office the map named. One
    # alias holds one spec: an office keeps the door only when the herd's spec is no wider for it (the second reader)
    herd_spec = {"paths": ["/s/"], "public": True}
    for mine, want, why in (
            ({"to": ["macbook"], "paths": ["/api/"]}, ["vps1"], "other paths: the MacBook would gain /s/ and consent"),
            ({"to": ["macbook"], "paths": ["/s/"]}, ["vps1"], "no consent in the map: the MacBook would gain it"),
            ({"to": "claude-cloud"}, ["vps1"], "an office the herd never named, given no consent"),
            ({"to": ["macbook"], "paths": ["/s/"], "public": True}, ["macbook", "vps1"], "the same spec: kept"),
            ({"to": ["macbook"], "paths": ["/s/", "/x/"], "public": True}, ["macbook", "vps1"], "wider, consented: kept"),
            # the map's entry judged as publishable_services reads it, never its raw flags (the second reader)
            ({"to": ["macbook"], "public": True}, ["vps1"], "the whole door: no consent counts without paths"),
            ({"to": ["macbook"], "paths": ["/"], "public": True}, ["vps1"], "`/`: no consent counts for the whole app"),
            ({"to": ["macbook"], "paths": ["/", "/x/%2e"], "public": True}, ["vps1"], "a path that is none: it gave nothing"),
            ({"paths": ["/s/"]}, ["vps1"], "no `to` (wherever only allows): the herd's offices name it")):
        setup("hp-laptop", dict(INCIDENT, services={"esign-public": mine}), herd=door_herd)
        door_registry()
        eff = cv.home_office()["serve"]["services"]["esign-public"]
        check(eff == dict(herd_spec, to=want), f"{why}: {mine} → {eff}")
    # a writer that puts the door in `exclude` does not close it either, and the rest of `exclude` stays
    setup("hp-laptop", dict(INCIDENT, exclude=["esign-public", "calculator"]), herd=door_herd)
    door_registry()
    check("esign-public" in doors_of("vps1") and cv.home_office()["serve"].get("exclude") == ["calculator"],
          f"`exclude` does not close the herd's door: {cv.home_office()['serve'].get('exclude')}")
    # …and a door `exclude` gave to nobody goes to the herd's offices alone, never back to the map's own
    setup("hp-laptop", dict(INCIDENT, exclude=["esign-public"],
                            services={"esign-public": {"to": ["macbook"], "paths": ["/s/"], "public": True}}),
          herd=door_herd)
    door_registry()
    eff = cv.home_office()["serve"]
    check(eff["services"]["esign-public"]["to"] == ["vps1"] and "esign-public" not in doors_of("macbook"),
          f"an excluded door goes to the herd's offices alone: {eff['services']['esign-public']}")
    # a door line that names an APP re-opens nothing: an app's name stays in `exclude`, and the app stays closed
    app_herd = HERD.replace("telegram, newsflow, project-pln]",
                            "telegram, newsflow, project-pln, {door: esign, paths: [/s/], public: true}]", 1)
    setup("hp-laptop", {"*": {}, "exclude": ["esign"]}, herd=app_herd)
    reg = Path(os.environ["DGO_REGISTRY_DIR"])
    (reg / "office.apps.json").write_text(json.dumps(dict(
        REGISTRY, apps=REGISTRY["apps"] + [{"app": "esign", "alias": "esign", "name": "חתימות", "port": 8080}],
        services=[{"app": "esign", "alias": "esign-public", "port": 8080}])), encoding="utf-8")
    eff = cv.home_office()["serve"]
    check(eff.get("exclude") == ["esign"] and "services" not in eff and "esign" not in given("macbook"),
          f"a door line naming an app gives nothing and re-opens nothing: {eff}, macbook {given('macbook')}")
    # a door this office's registry does not have gives nothing
    setup("hp-laptop", INCIDENT, herd=HERD.replace(
        "telegram, newsflow, project-pln]", "telegram, newsflow, project-pln, {door: nothere, paths: [/s/]}]", 1))
    door_registry()
    check("services" not in cv.home_office()["serve"], "a door the registry does not list gives nothing")
    # an office narrowed to nothing still gets the door the herd names for it (its `to`, not `only`, decides)
    setup("hp-laptop", dict(INCIDENT, only={"vps1": []}), herd=door_herd)
    door_registry()
    check("esign-public" in doors_of("vps1"), f"`only.vps1: []` keeps the herd's door: {doors_of('vps1')}")
    # a peer whose record here holds another key gets no door by the herd file
    setup("hp-laptop", INCIDENT, herd=door_herd, records=dict(RECORDS, vps1=OTHER))
    door_registry()
    check("esign-public" not in doors_of("vps1"), "a peer whose record holds another key gets no door")
    # by key, not by name
    setup("hp-laptop", INCIDENT, herd=door_herd, my_key=OTHER)
    door_registry()
    check("esign-public" not in doors_of("vps1"), "an office whose key is not the herd's gives no door by it")
    # a door that breaks the rule gives nothing: a typo never opens more than was written
    for bad in ("{door: esign-public, public: true}",                  # no paths: the whole door
                "{door: esign-public, paths: [/], public: true}",       # the whole app, opened
                "{door: esign-public, paths: [/s/../x/]}",
                "{door: esign-public, paths: [/s/], public: 'yes'}",
                "{door: esign-public, paths: [/s/], to: [dell]}",       # a key the rule does not take
                "{door: Esign_Public, paths: [/s/]}"):
        setup("hp-laptop", INCIDENT, herd=HERD.replace("telegram, newsflow, project-pln]",
                                                      "telegram, newsflow, project-pln, " + bad + "]", 1))
        door_registry()
        check(not doors_of("vps1") and "services" not in cv.home_office()["serve"],
              f"a door that breaks the rule gives nothing: {bad}")
    # one door, two offices, two answers: given to none
    setup("hp-laptop", INCIDENT, herd=door_herd.replace(
        "macbook: [bina-ds, bina-claude, browser42, computers, project-pln]",
        "macbook: [bina-ds, bina-claude, browser42, computers, project-pln, {door: esign-public, paths: [/x/]}]", 1))
    door_registry()
    check(not doors_of("vps1") and not doors_of("macbook"), "one door given with two answers is given to none")
    # the apps' floor does not move for a door in the line
    setup("hp-laptop", INCIDENT, herd=door_herd)
    door_registry()
    check({"bina", "bina-claude", "browser42", "plane"} <= set(given("vps1")),
          f"the apps' floor is the same beside a door: {given('vps1')}")

    # ── THE REAL FILE ──────────────────────────────────────────────────────────────────────────────────────────
    real = (REPO / "apps" / "computers" / "herd.yaml").read_text(encoding="utf-8")
    setup("hp-laptop", INCIDENT, herd=real)
    for peer, apps in (("vps1", ("bina", "bina-claude", "browser42", "plane")), ("macbook", ("bina", "computers"))):
        for a in apps:
            check(a in given(peer), f"apps/computers/herd.yaml gives {peer} the HP's {a}: {given(peer)}")
    door_registry()
    v = doors_of("vps1")
    check(v.get("esign-public", {}).get("paths") == ["/s/"] and v["esign-public"].get("public") is True,
          f"apps/computers/herd.yaml gives vps1 the HP's signer door, narrowed and opened (DGO-2125): {v}")
    setup("macbook", {"*": {}}, herd=real)
    check(cv.home_office()["serve"] == {"*": {}}, "the real file gives nothing from the MacBook: no change there")

    for f in FAIL:
        print("FAIL:", f)
    print("test_give:", "all passed" if not FAIL else f"{len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
