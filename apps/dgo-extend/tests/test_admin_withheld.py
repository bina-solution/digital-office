#!/usr/bin/env python3
"""test_admin_withheld — `*` never gives an admin surface to a public office or to an office that is not the
herd's own (DGO-1360).

Measured 2026-11-05: the MacBook rejoined vps1 through its door, the fresh pair inherited the MacBook's `*`,
and for 15 minutes the public server could reach the MacBook's vault (`connections`), its root commands on
every machine it holds keys for (`computers`) and its GitHub proxy (`git`). Asked here, through the catalog a
linked office pulls and its door routes by (`build_catalog(office=…)`), and through the hand-on (`reshare`):
the hub and an outsider are given the admin surfaces only by name (`serve.only.<office>`); the home offices keep
`*` as it is — and an office is one of them only when this office's own record of it holds the key the herd
file gives it, never by its name alone; an office reading its own list, and an office that is not itself the
herd's (a client's herd on this checkout), see no change.

Run: python3 apps/dgo-extend/tests/test_admin_withheld.py   (app.py loaded as test_app_input loads it)
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
spec = importlib.util.spec_from_file_location("test_app_input", HERE / "test_app_input.py")
tai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tai)
app = tai.load()
catalog = app.catalog

FAIL: list[str] = []
ADMIN = ["connections", "computers", "app-management", "git", "security", "console", "claude-terminal",
         "bina-ds", "bina-claude", "browser42"]
KEY = {"macbook": "+0B1Hc+7nYPESAjx/uu3JSDeuYQYadu7dvV0eb/C5B8=",
       "hp-laptop": "OUBWvxLVZJDWW19J9sZPePVPi3i1rickvdqcXagbbns=",
       "dell": "goMFvhsFv7EUbKsnI2PGwdBOnEFdhdIzMBBp8axs4Vg=",
       "vps1": "ka9qFHK11KwtSPR1MDftp9Kpd9yb8Y6rvmf2ESWLHgQ=",
       "kiosk": "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="}
OTHER = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="      # a valid key that is none of ours
HERD = """\
offices:
  macbook: {label: MacBook, wg_public_key: '%(macbook)s'}
  hp-laptop: {label: HP, wg_public_key: '%(hp-laptop)s'}
  dell: {aliases: [portable-ubuntu, portable], wg_public_key: '%(dell)s'}
  vps1: {link_host: link.staging.digital-office.co.il, wg_public_key: '%(vps1)s'}
  kiosk: {public: true, wg_public_key: '%(kiosk)s'}
hub: vps1
admin_by_name: [macbook, hp-laptop, vps1]
""" % KEY + "admin_apps: [%s]\n" % ", ".join(ADMIN)
#: This office's records of its peers, as pairing writes them: the real keys
RECORDS = {"hp-laptop": KEY["hp-laptop"], "portable-ubuntu": KEY["dell"], "vps1": KEY["vps1"], "kiosk": KEY["kiosk"],
           "claude-cloud": OTHER, "portable": OTHER}
REGISTRY = {"apps": [
    {"app": "connections", "alias": "connections", "name": "חיבורים", "port": 8990},
    {"app": "computers", "alias": "computers", "name": "מחשבים", "port": 8977},
    {"app": "git", "alias": "git-accounts", "name": "חשבונות", "port": 9100},
    {"app": "bina-ds", "alias": "bina", "name": "בינה", "port": 3080, "agent_api_port": 3081},
    {"app": "dashboard", "alias": "dashboard", "name": "מרכז הבקרה", "port": 80},
    {"app": "drive", "alias": "drive", "name": "קבצים", "port": 8975}]}


def check(cond, what):
    if not cond:
        FAIL.append(what)


#: every app the real herd file's admin lines name, for the real-file check (names resolve to tiles of the registry)
REAL_REGISTRY = {"apps": REGISTRY["apps"] + [
    {"app": "machine", "alias": "machine", "name": "מכונה", "port": 8994},
    {"app": "security", "alias": "security", "name": "אבטחה", "port": 8995},
    {"app": "office-routes", "alias": "office-routes", "name": "דרכים", "port": 8996},
    {"app": "bina-claude", "alias": "bina-claude", "name": "Claude", "port": 3900},
    {"app": "browser42", "alias": "browser42", "name": "דפדפן", "port": 9222},
    {"app": "app-management", "alias": "app-management", "name": "אפליקציות", "port": 8980}]}


def setup(me: str, serve: dict, herd: str | None = HERD, my_key: str | None = None, records: dict = RECORDS,
          registry: dict = REGISTRY):
    import give
    d = Path(tempfile.mkdtemp(prefix="dgo-admin-"))
    if herd is not None:
        (d / "herd.yaml").write_text(herd, encoding="utf-8")
    app.HERD_FILE = d / "herd.yaml"
    give.HERD_FILE = d / "herd.yaml"                 # `give:` is read through give.load_herd (DGO-863's names)
    reg = Path(tempfile.mkdtemp(prefix="dgo-admin-reg-"))
    (reg / "office.apps.json").write_text(json.dumps(registry), encoding="utf-8")
    app.REGISTRY_DIR = reg
    key = my_key if my_key is not None else KEY.get(me, OTHER)
    app.cv.home_office = lambda: {"id": me, "serve": serve, "identity": {"wg": key}}
    # `give:` (cv.given_by_herd → give.floor) reads this office from its own state file and identity, as test_give does
    import os
    import identity as idmod
    (Path(os.environ["DGO_STATE_DIR"]) / app.cv.HOME_FILE).write_text(
        json.dumps({"id": me, "serve": serve, "tunnel": {"slot": 1}}), encoding="utf-8")
    idmod.public = lambda: {"office": me, "wg": key}
    app.DECL_DIR.mkdir(parents=True, exist_ok=True)
    for f in app.DECL_DIR.glob("*.yaml"):
        f.unlink()
    for rid, rkey in records.items():
        (app.DECL_DIR / f"{rid}.yaml").write_text(f"id: {rid}\nkind: paired\nidentity:\n  wg: '{rkey}'\n")


def given(office: str) -> list[str]:
    return sorted(r.get("alias") for r in app.build_catalog(office=office).get("apps") or [])


def main() -> int:
    everything = ["bina", "computers", "connections", "dashboard", "drive", "git-accounts"]
    plain = ["dashboard", "drive"]

    setup("macbook", {"*": {}})
    check(given("hp-laptop") == plain, f"a home office gets no admin surface by `*` either (DGO-863): "
                                       f"{given('hp-laptop')}")
    check(given("portable-ubuntu") == plain, "…named by an alias too (the Dell)")
    check(given("") == everything, "this office reading its own list sees everything")
    check(given("vps1") == plain, f"the hub gets no admin surface by `*`: {given('vps1')}")
    check(given("kiosk") == plain, "an office marked public: true gets none either")
    check(given("claude-cloud") == plain, "an office that is not the herd's gets none")
    check(given("portable") == plain, "a peer CALLED by one of our names, with another key, is not ours: none")
    check(given("nobody") == plain, "a name with no record here: none")

    setup("macbook", {"*": {}}, records={**RECORDS, "hp-laptop": OTHER})
    check(given("hp-laptop") == plain, "a home office whose record here holds another key: none")

    setup("macbook", {"*": {}, "only": {"vps1": ["dashboard", "computers"]}})
    check(given("vps1") == ["computers", "dashboard"], f"named in serve.only, it is given: {given('vps1')}")
    check(given("hp-laptop") == plain, "…and nobody else's share changes")

    # BY NAME IN THE HERD FILE (DGO-863): a `give:` line hands a home office exactly the admin apps it names — and
    # only to that office: another home office still gets none of them
    gives = HERD + "give:\n  macbook:\n    hp-laptop: [computers, bina-ds]\n"
    setup("macbook", {"*": {}}, herd=gives)
    check(given("hp-laptop") == ["bina", "computers", "dashboard", "drive"],
          f"give: names computers and bina-ds for the HP: {given('hp-laptop')}")
    check(given("portable-ubuntu") == plain, f"…and not for the Dell: {given('portable-ubuntu')}")
    check(given("vps1") == plain, "…nor for the hub")
    setup("macbook", {"*": {}}, herd=gives, records={**RECORDS, "hp-laptop": OTHER})
    check(given("hp-laptop") == plain, "a give: line is read by KEY: an HP whose record holds another key gets none")

    setup("macbook", {"*": {}, "connections": {"port": 8990}})
    check("connections" not in given("vps1"), "an office-wide name is not a name FOR the hub: only serve.only is")

    setup("examplef", {"*": {}})
    check(given("vps1") == everything, "an office that is not the herd's own applies none of our rules")
    setup("macbook", {"*": {}}, my_key=OTHER)
    check(given("vps1") == plain, "FAILS CLOSED: this office called macbook whose key changed still withholds")
    setup("macbook", {"*": {}}, herd=HERD.replace("hub: vps1", "hub: VPS1"))
    check(given("vps1") == plain, "hub: read with any case")
    setup("macbook", {"*": {}}, herd=HERD.replace("hub: vps1", "hub: kiosk").replace("public: true, ", ""))
    check(given("kiosk") == plain, "the office hub: names is public, with no public: of its own")
    check(given("vps1") == plain, "…and an office that is neither the hub nor public: true gets none either")
    setup("macbook", {"*": {}}, herd=HERD.replace("public: true", "public: 'true'"))
    check(given("kiosk") == plain, "public: 'true' as a string is public")
    setup("macbook", {"*": {}}, herd=HERD.replace("aliases: [portable-ubuntu, portable]", "aliases: true"))
    try:
        check("connections" not in given("portable-ubuntu"), "aliases: true names nobody — and raises nothing")
    except Exception as e:                                  # noqa: BLE001
        check(False, f"aliases: true must never fail the catalog: {type(e).__name__}")

    # THE PORTS (second reader): what the catalog hides, the link proxy must not splice and the firewall must not open
    linkproxy, cv = app.linkproxy if hasattr(app, "linkproxy") else __import__("linkproxy"), app.cv
    office = {"id": "vps1", "tunnel": {"slot": 7}, "links": [{"office": "macbook", "direction": "use"}]}
    home = {"id": "macbook", "tunnel": {"slot": 1}, "serve": {"*": {}}}

    def ports(withheld):
        plan = linkproxy.build_multi(home, [{"office": office, "slot": 7, "side": 1, "withheld": withheld}],
                                     registry=REGISTRY)
        return sorted(r["port"] for r in plan["rules"] if r.get("direction") == "serve")
    check(3081 in ports(frozenset()), f"without the rule the agent's adapter is spliced: {ports(frozenset())}")
    check(3081 not in ports(frozenset(ADMIN)), f"a withheld agent's adapter is not spliced: {ports(frozenset(ADMIN))}")
    fw = cv._served_ports_local(home, 7, REGISTRY, peer="vps1", withheld=frozenset(ADMIN))
    check("bina-ds:agent" not in fw, f"…and the firewall opens no port for it: {sorted(fw)}")
    # a home office, from an office in admin_by_name (DGO-863): the agent's port only where `give:` names the agent
    setup("macbook", {"*": {}})
    w = app._admin_withheld("hp-laptop")
    check("bina-ds:agent" not in cv._served_ports_local(home, 7, REGISTRY, peer="hp-laptop", withheld=w),
          f"a home office the herd names no agent for gets no agent port: withheld {sorted(w)}")
    setup("macbook", {"*": {}}, herd=HERD + "give:\n  macbook:\n    hp-laptop: [bina-ds]\n")
    w = app._admin_withheld("hp-laptop")
    check("bina-ds:agent" in cv._served_ports_local(home, 7, REGISTRY, peer="hp-laptop", withheld=w),
          f"…and gets it once give: names bina-ds for it: withheld {sorted(w)}")
    # STAGED: an office NOT in admin_by_name (here the Dell, whose door was not measured) keeps `*` for the home
    # offices as before — and still withholds from the hub
    setup("dell", {"*": {}}, records={**RECORDS, "macbook": KEY["macbook"]})
    check(given("hp-laptop") == everything, f"the Dell, not listed, keeps `*` for the HP: {given('hp-laptop')}")
    check(given("vps1") == plain, "…and still gives the hub no admin surface")
    setup("macbook", {"*": {}}, herd=None)
    check(given("vps1") == everything, "no herd file: no change")
    setup("macbook", {"*": {}}, herd=HERD.replace("admin_apps: [%s]\n" % ", ".join(ADMIN), ""))
    check(given("vps1") == everything, "a herd file with no admin_apps: no change")
    setup("macbook", {"*": {}}, herd=HERD + "since: 2026-11-31\n")
    try:
        check(given("vps1") == everything, "a herd file YAML refuses: no change")
    except Exception as e:                                  # noqa: BLE001
        check(False, f"a herd file YAML refuses must never fail the catalog: {type(e).__name__}")

    # the agent door follows the app: no agent port for an agent that is not given
    setup("macbook", {"*": {}})
    doors = catalog.serve_with_agents(REGISTRY, {"*": {}}, "vps1", app._admin_withheld("vps1"))
    check("bina-ds" not in doors, f"no agent door for a withheld agent: {sorted(doors)}")

    # the hand-on: another office's admin surface is never handed on to the hub by `*`
    fetched = {"hp-laptop": {"apps": [
        {"app": "computers", "alias": "computers", "host": "computers.localhost"},
        {"app": "plane", "alias": "plane", "host": "plane.localhost"}]}}
    rows = lambda only=None: [a["alias"] for s in catalog.reshare(  # noqa: E731
        {"*": {}, "shared": "*", **({"only": {"vps1": only}} if only else {})}, "vps1", "macbook", fetched,
        {"hp-laptop": 9005}, None, frozenset(ADMIN)) for a in s["apps"]]
    check(rows() == ["plane"], f"computers.hp-laptop is not handed on to the hub by `*`: {rows()}")
    check(rows(["computers.hp-laptop"]) == ["computers"], "…and is, when serve.only names it")

    # THE REAL FILE: the herd as declared in git withholds the vault, commands and git from vps1 at the MacBook…
    real = (REPO / "apps" / "computers" / "herd.yaml").read_text(encoding="utf-8")
    setup("macbook", {"*": {}}, herd=real, registry=REAL_REGISTRY)
    w = app._admin_withheld("vps1")
    check({"connections", "computers", "git", "terminal", "n8n", "machine", "bina-ds", "dgo-extend"} <= w,
          f"apps/computers/herd.yaml withholds them from vps1: {sorted(w)}")
    # …and keeps open EVERY admin app a home office was measured opening at another (DGO-863: every door's served
    # requests, 72 h to 2026-11-11 ~09Z, through each office's security app; apps/computers/herd.yaml says the
    # numbers), while the vault and app management — opened once or twice — are withheld from every home office.
    # COMPUTED from ci-artifacts/…/door-counts-2026-11-11.txt (each admin row, by alias → app id), not from the
    # give: lines: the HP's 45 requests to the HP's computers by vps1 are left out — vps1 is the hub, withheld from
    # by DGO-1360 whatever this flip does. The agent (bina-ds) is held open wherever give: names it: its port is a
    # raw splice with no access record, so it was not measured.
    measured = {
        "hp-laptop": {"macbook": ["computers", "machine", "bina-ds", "bina-claude", "security", "browser42"],
                      "portable-ubuntu": ["security", "machine", "office-routes", "bina-ds"],
                      "vps1": ["bina-ds", "bina-claude", "browser42"]},
        "macbook": {"hp-laptop": ["computers", "git", "security", "bina-ds"],
                    "portable-ubuntu": ["security", "git", "bina-ds"]},
        "vps1": {"macbook": ["computers", "machine", "security", "bina-ds"],
                 "hp-laptop": ["computers", "machine", "security", "bina-ds"]},
    }
    peers = {**RECORDS, "macbook": KEY["macbook"]}
    for door, openers in measured.items():
        setup(door, {"*": {}}, herd=real, registry=REAL_REGISTRY, records=peers)
        for opener, apps in openers.items():
            w = app._admin_withheld(opener)
            kept = [a for a in apps if a in w]
            check(not kept, f"{door}'s door must keep {opener}'s measured {kept} open: withheld {sorted(w)}")
            if opener != "vps1":
                check({"connections", "app-management"} <= w,
                      f"{door} withholds the vault and app management from {opener}: {sorted(w)}")

    for f in FAIL:
        print("FAIL:", f)
    print("test_admin_withheld:", "all passed" if not FAIL else f"{len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
