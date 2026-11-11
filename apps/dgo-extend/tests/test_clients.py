"""test_clients — a client's office is linked to ours ONE WAY, by the herd file's declaration (DGO-1636, DGO-964).

The owner, MEET-13 (DGO-964): while we set up a company's office our herd is linked to it one way — we see and manage
it, it sees nothing of ours — and the link is cut at hand-over. DGO-1363: an office that runs DGO Extend of its own is
linked as a JOIN pair. So the herd file (apps/computers/herd.yaml) names each client office, its link door, its
fingerprint and the offices of ours that join it; each of those, by its own key, asks the client's door to join with
`use` beside its own DGO_JOIN, and the owner's approval on the client's screen is the one act. Asked here:

  * `clients.mine`: an office of ours joins a client only when the herd file names it in `by` AND this office holds
    the key the herd file gives that name; a client with no pin, or a door that is not https, is never joined;
  * `clients.withheld`: every record that is a client of this office — by its id, or by the pinned identity;
  * `clients.narrow` and the catalog a client pulls: nothing of ours, whatever `serve:` says (`*`, named, shared, a
    door with `to`), and home.json is never written;
  * the client joiner (join_api.ClientJoiner, through a real Hub and Pairing): a grant other than the host's
    `serve` is refused before anything is written; the mirrored grant joins, `use` on our record;
  * the real herd file names Exampleu's door and fingerprint, joined by the MacBook.

Run: python3 apps/dgo-extend/tests/test_clients.py   (PyYAML, FastAPI; `openssl` 3 for the joiner part)
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for _var in ("DGO_TUNNEL_DIR", "DGO_IDENTITY_DIR"):
    os.environ[_var] = tempfile.mkdtemp(prefix=f"dgo-clients-{_var.lower()}-")
spec = importlib.util.spec_from_file_location("test_app_input", HERE / "test_app_input.py")
tai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tai)
app = tai.load()
app.render_tunnel = lambda *a, **k: {}
cv = app.cv
import clients  # noqa: E402 — app.py's directory is on the path once it is loaded
import give  # noqa: E402
import identity as idmod  # noqa: E402
import join_api  # noqa: E402
import pair_api  # noqa: E402

FAIL: list[str] = []
KEY = {"macbook": "+0B1Hc+7nYPESAjx/uu3JSDeuYQYadu7dvV0eb/C5B8=",
       "hp-laptop": "OUBWvxLVZJDWW19J9sZPePVPi3i1rickvdqcXagbbns="}
OTHER = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
PIN = "CHANGE_ME"
HERD = """\
offices:
  macbook: {label: MacBook, aliases: [mac], wg_public_key: '%(macbook)s'}
  hp-laptop: {label: HP, wg_public_key: '%(hp-laptop)s'}
hub: vps1
clients:
  exampleu:
    herd: Exampleu
    door: https://link.exampleu.digital-office.co.il
    pin: %(pin)s
    by: [mac]
  nopin:
    door: https://link.nopin.example.org
    by: [macbook]
  plain:
    door: http://link.plain.example.org
    pin: %(pin)s
    by: [macbook]
  someone-else:
    door: https://link.else.example.org
    pin: %(pin)s
    by: [hp-laptop]
""" % {**KEY, "pin": PIN}
REGISTRY = {"apps": [
    {"app": "bina-ds", "alias": "bina", "name": "בינה", "port": 3080},
    {"app": "drive", "alias": "drive", "name": "קבצים", "port": 8975},
    {"app": "dashboard", "alias": "dashboard", "name": "מרכז הבקרה", "port": 80}]}


def check(cond, what):
    if not cond:
        FAIL.append(what)


def setup(me: str, serve: dict, records: dict, herd: str = HERD, my_key: str | None = None):
    state = Path(os.environ["DGO_STATE_DIR"])
    key = my_key if my_key is not None else KEY.get(me, OTHER)
    (state / cv.HOME_FILE).write_text(json.dumps({"id": me, "serve": serve, "tunnel": {"slot": 1}}), encoding="utf-8")
    d = Path(tempfile.mkdtemp(prefix="dgo-clients-"))
    (d / "herd.yaml").write_text(herd, encoding="utf-8")
    give.HERD_FILE = d / "herd.yaml"
    app.HERD_FILE = d / "herd.yaml"
    reg = Path(tempfile.mkdtemp(prefix="dgo-clients-reg-"))
    (reg / "office.apps.json").write_text(json.dumps(REGISTRY), encoding="utf-8")
    os.environ["DGO_REGISTRY_DIR"] = str(reg)
    app.REGISTRY_DIR = str(reg)
    idmod.public = lambda: {"office": me, "wg": key}
    app.DECL_DIR.mkdir(parents=True, exist_ok=True)
    for f in app.DECL_DIR.glob("*.yaml"):
        f.unlink()
    for rid, ident in records.items():
        (app.DECL_DIR / f"{rid}.yaml").write_text(f"id: {rid}\nkind: paired\nidentity: {json.dumps(ident)}\n")


def given(office: str) -> list[str]:
    return sorted(r.get("alias") for r in app.build_catalog(office=office).get("apps") or [])


def home(me: str, key: str) -> dict:
    return {"id": me, "identity": {"wg": key}}


def pure() -> None:
    doc = clients.load_herd_text(HERD)
    mine = clients.mine(doc, home("macbook", KEY["macbook"]))
    check(sorted(mine) == ["exampleu"], f"the MacBook joins exactly the clients the herd names it for (by an alias "
                                      f"too), and none with no pin or a door that is not https: {sorted(mine)}")
    check(mine.get("exampleu", {}).get("door") == "https://link.exampleu.digital-office.co.il"
          and mine["exampleu"].get("pin") == PIN, f"…with the door and the pin as written: {mine.get('exampleu')}")
    env = clients.declaration(mine["exampleu"])
    check(env == {"DGO_JOIN": "https://link.exampleu.digital-office.co.il", "DGO_JOIN_PIN": PIN,
                  "DGO_JOIN_DIRECTION": "use"}, f"a client is asked for `use`, pinned: {env}")
    check(join_api.parse_declaration(env)["direction"] == "use", "…a declaration the joiner reads as it reads DGO_JOIN")
    check(clients.mine(doc, home("macbook", OTHER)) == {},
          "an office called macbook whose key is not the herd's joins no client (a client runs this same checkout)")
    check(sorted(clients.mine(doc, home("hp-laptop", KEY["hp-laptop"]))) == ["someone-else"],
          "the HP joins only what names the HP")
    check(clients.mine(clients.load_herd_text("offices: {}\n"), home("macbook", KEY["macbook"])) == {},
          "no clients: nothing")
    check(clients.mine(clients.load_herd_text(HERD.replace("by: [mac]", "by: macbook")),
                       home("macbook", KEY["macbook"])).keys() == {"exampleu"}, "`by` may be one name")

    fp_ident = {"ed25519": "x", "fingerprint": PIN}
    cut = clients.withheld(doc, home("macbook", KEY["macbook"]),
                           [{"id": "exampleu", "identity": {}}, {"id": "srv000002", "identity": fp_ident},
                            {"id": "vps1", "identity": {"fingerprint": "CHANGE_ME"}}])
    check(cut == {"exampleu", "srv000002"}, f"a client is withheld by its id AND by its pinned identity: {cut}")
    check(clients.withheld(doc, home("macbook", OTHER), [{"id": "exampleu"}]) == {"exampleu"},
          "…and withholding needs no key: never giving a client anything is never wrong")

    serve = {"*": {}, "shared": "*", "only": {"vps1": ["bina"]},
             "services": {"backup-store": {"to": ["exampleu", "hp-laptop"]}, "hooks": {"to": "exampleu"}}}
    out = clients.narrow(serve, {"exampleu"})
    check(out["only"] == {"vps1": ["bina"], "exampleu": []}, f"a client is narrowed to nothing: {out['only']}")
    check(out["services"] == {"backup-store": {"to": ["hp-laptop"]}, "hooks": {"to": []}},
          f"…and no door with no tile is given to it: {out['services']}")
    check(serve["only"] == {"vps1": ["bina"]} and serve["services"]["backup-store"]["to"] == ["exampleu", "hp-laptop"],
          "narrow never changes the map it was given")
    check(clients.narrow(serve, set()) == serve, "nothing to cut: the same map")
    odd = clients.narrow({"services": {"x": {"to": 5}, "y": {"to": None}}}, {"exampleu"})
    check(odd["services"] == {"x": {"to": []}, "y": {"to": []}}, f"a `to` that is not names is given to nobody: {odd}")

    # our rule is not a client herd's own rule between ITS offices (a client runs this same checkout and herd file)
    check(clients.withheld(doc, home("exampleu-karkur", OTHER), [{"id": "exampleu"}]) == set(),
          "an office that is not ours withholds nothing from its own sibling")
    # …and a client entry that names, or pins, one of OUR offices is a mistake: never joined, never withheld
    ours = clients.load_herd_text(HERD + "  hp-laptop:\n    door: https://link.x.example.org\n    pin: %s\n"
                                  "    by: [macbook]\n" % PIN)
    check("hp-laptop" not in clients.mine(ours, home("macbook", KEY["macbook"])), "an office of ours is never a client")
    cut = clients.withheld(ours, home("macbook", KEY["macbook"]),
                           [{"id": "hp-laptop", "identity": {}}, {"id": "mac", "identity": {"fingerprint": PIN}}])
    check(cut == set(), f"nothing of ours is withheld, by name or by a pin it happens to match: {cut}")


def through_the_app() -> None:
    fp_ident = {"ed25519": "x", "fingerprint": PIN, "wg": OTHER}
    setup("macbook", {"*": {}, "shared": "*"}, {"exampleu": fp_ident, "vps1": {"wg": KEY["hp-laptop"]}})
    check(given("exampleu") == [], f"the client's office pulls an empty catalog from us under `*`: {given('exampleu')}")
    check("bina" in given("vps1"), f"…while a peer of ours is given what serve: says: {given('vps1')}")
    on_disk = json.loads((Path(os.environ["DGO_STATE_DIR"]) / cv.HOME_FILE).read_text(encoding="utf-8"))["serve"]
    check(on_disk == {"*": {}, "shared": "*"}, f"the cut is never written into home.json: {on_disk}")
    setup("macbook", {"drive": {"port": 8975}, "only": {"exampleu": ["drive"]}}, {"exampleu": fp_ident})
    check(given("exampleu") == [], f"…nor when serve: names an app and opens it to the client by name: {given('exampleu')}")


def the_joiner() -> None:
    if not shutil.which("openssl") or b"OpenSSL 3" not in subprocess.run(["openssl", "version"],
                                                                         capture_output=True).stdout:
        FAIL.append("the joiner part needs `openssl` 3 on PATH (pairing.py runs it); not proven here")
        return
    tmp = Path(tempfile.mkdtemp(prefix="dgo-clients-join-"))

    def pair(granted: str):
        """A fresh client office with a door, our MacBook's client joiner for it, and the client's screen
        approving with `granted` — (our ports, the joiner, the answer of the pass after the approval)."""
        exampleu = pair_api._MemoryPorts("exampleu", "Exampleu", slot=1)
        hub = join_api.Hub(pair_api.Pairing(exampleu), tmp / f"hub-{granted or 'mirror'}.json",
                           host=lambda: "link.exampleu.digital-office.co.il")

        def http(method, url, body=None, headers=None):
            try:
                if method == "POST" and url.endswith("/join"):
                    return 200, hub.join(body or {}, "203.0.113.9")
                if method == "GET" and "/join/" in url:
                    out = hub.poll(url.rsplit("/", 1)[1], (headers or {}).get("X-Dgo-Poll", ""))
                    return (404 if out.get("state") == "unknown" else 200), out
            except join_api.PairError as e:
                return e.status, {"error": str(e)}
            return 404, {"error": "no such path"}

        mac = pair_api._MemoryPorts("macbook", "MacBook", slot=2)
        # pinned by the FINGERPRINT, the form the herd file writes (6652-F66A-…), not the raw key
        spec = {"door": "https://link.exampleu.digital-office.co.il",
                "pin": join_api.fingerprint_of(exampleu.home()["identity"])}
        j = join_api.ClientJoiner(pair_api.Pairing(mac), tmp / f"client-{granted or 'mirror'}.json", "exampleu",
                                  env=clients.declaration(spec), http=http)
        check(j.step().get("state") == "waiting", "the client's door holds our request for a person")
        hub.approve("macbook", granted)
        return mac, j, j.step()

    for granted in ("both", "use"):                       # the client's screen chose to see ours
        mac, j, got = pair(granted)
        check(got.get("state") in ("failed", "refused") and "exampleu" not in mac.records,
              f"a grant of `{granted}` is refused, and nothing is written on our side: {got}")
        check(not (j.store.load().get("joined") or {}), f"…and the joiner keeps no join ({granted})")
    mac, j, got = pair("")                                # the mirror of our `use`: they serve, we use
    links = (mac.records.get("exampleu") or {}).get("links") or []
    check(got.get("state") == "joined" and got.get("peer") == "exampleu", f"the mirrored grant joins: {got}")
    check(bool(links) and links[0].get("direction") == "serve",
          f"our record of the client says the CLIENT serves (we use): {links}")
    check(bool(mac.vault.get("dgo_link-exampleu")), "the pair's token is held as after any join")


def the_supervisor() -> None:
    """app._clients_tick keeps one client joiner per client the herd gives this office (threads not run here)."""
    started: list = []
    real = join_api.ClientJoiner.run_forever
    join_api.ClientJoiner.run_forever = lambda self, stop=None: (started.append(self.client), stop.wait(600))
    try:
        setup("macbook", {"*": {}}, {})
        cv.home_office = (lambda base=cv.home_office: lambda: {**base(), "identity": {"wg": KEY["macbook"]}})()
        check(app._clients_tick() == ["exampleu"], f"the herd's client is joined: {sorted(app.CLIENT_JOINERS)}")
        first = app.CLIENT_JOINERS["exampleu"]
        check(app._clients_tick() == ["exampleu"] and app.CLIENT_JOINERS["exampleu"] is first,
              "a pass with nothing changed keeps the same joiner")
        other_pin = "AAAA-BBBB-CCCC-DDDD"
        give.HERD_FILE.write_text(HERD.replace(PIN, other_pin, 1), encoding="utf-8")
        app._clients_tick()
        check(app.CLIENT_JOINERS["exampleu"] is not first and app.CLIENT_JOINERS["exampleu"].env["DGO_JOIN_PIN"] == other_pin,
              "a changed declaration replaces the joiner")
        stop_old = app._CLIENT_STOPS["exampleu"][0]
        give.HERD_FILE.write_text("this: [is not: a herd\n", encoding="utf-8")
        check(app._clients_tick() == ["exampleu"] and not stop_old.is_set(),
              "a herd file that cannot be read keeps the joiners that run")
        give.HERD_FILE.write_text(HERD.split("clients:")[0], encoding="utf-8")
        check(app._clients_tick() == [] and stop_old.is_set(), "a client taken out of the herd file is let go")
    finally:
        join_api.ClientJoiner.run_forever = real
        for stop, _t in list(app._CLIENT_STOPS.values()):
            stop.set()
        app._CLIENT_STOPS.clear()
        app.CLIENT_JOINERS.clear()


def the_real_herd() -> None:
    doc = clients.load_herd_text((REPO / "apps" / "computers" / "herd.yaml").read_text(encoding="utf-8"))
    entry = (doc.get("clients") or {}).get("exampleu") or {}
    check(entry.get("door") == "https://link.exampleu.digital-office.co.il" and entry.get("pin") == PIN,
          f"the herd file names Exampleu's door and fingerprint: {entry}")
    by = entry.get("by")
    check(by == ["macbook"] or by == "macbook", f"…joined by the MacBook: {by}")
    key = ((doc.get("offices") or {}).get("macbook") or {}).get("wg_public_key")
    check(sorted(clients.mine(doc, home("macbook", key))) == ["exampleu"], "the MacBook, by its own key, joins Exampleu")


def main() -> int:
    pure()
    through_the_app()
    the_supervisor()
    the_joiner()
    the_real_herd()
    for f in FAIL:
        print("FAIL:", f)
    print(f"test_clients: {'OK' if not FAIL else f'{len(FAIL)} failure(s)'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
