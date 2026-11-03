"""serve.render's LAN form (DGO-1126): on the console's local-network NAME, a shared app keeps its own host
nested under that name, exactly as on a real domain, and is signed in by the `lan` entry's own outpost.

The owner's phone opened the console at the office's IP, and every shared app of its own host said it
cannot be shown from that address: no host can be nested under an IP. Under a name it can, so each app
gets one more form there — and nothing else changes for the forms that were already rendered.
"""
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import serve  # noqa: E402

CAT = {"console": {"routing": [{"host": "console", "service": "console", "port": 8000}]}}
LAN, PORT = "192-168-16-100.sslip.io", "8080"


def served(module_kind="external"):
    """One linked office sharing one app of its own host (Obsidian at FPG)."""
    return [{"office": "fireplace", "identity": {"to": "akadmin"}, "link_port": 9006,
             "apps": [{"alias": "obsidian", "port": 8080, "host": "obsidian", "module_kind": module_kind}]}]


def routers(**kw):
    return yaml.safe_load(serve.render(served(), CAT, **kw).split("\n", 4)[-1])["http"]


def test_no_lan_name_renders_no_lan_router():
    http = routers()
    assert not [n for n in http["routers"] if "-console-lan" in n]
    assert "lan-auth@docker" not in yaml.safe_dump(http)


def test_the_lan_form_nests_the_app_under_the_name_and_signs_in_on_the_lan_entry():
    http = routers(lan_domain=LAN, lan_port=PORT)
    r = http["routers"]["dgo-remote-fireplace-obsidian-console-lan"]
    assert r["rule"] == f"Host(`obsidian.fireplace.console.{LAN}`)"
    assert r["entryPoints"] == ["lan"]
    assert r["middlewares"][0] == "lan-auth@docker"
    assert "tls" not in r
    lan = {n: v for n, v in http["routers"].items() if "-console-lan" in n}
    # the app's own origin, the shell's question and the way in: all on the LAN entry, none on authentik
    assert {"dgo-remote-fireplace-obsidian-console-lan-own-origin",
            "dgo-remote-fireplace-obsidian-console-lan-signed-in",
            "dgo-remote-fireplace-obsidian-console-lan-enter"} <= set(lan)
    for v in lan.values():
        assert v["entryPoints"] == ["lan"] and "authentik@file" not in v["middlewares"]
    own = lan["dgo-remote-fireplace-obsidian-console-lan-own-origin"]["rule"]
    assert f"http://obsidian.fireplace.console.{LAN}:{PORT}" in own


def test_the_other_forms_keep_authentik():
    http = routers(lan_domain=LAN, lan_port=PORT)
    r = http["routers"]["dgo-remote-fireplace-obsidian-console-local"]
    assert r["entryPoints"] == ["web"] and r["middlewares"][0] == "authentik@file"


def test_the_console_on_its_lan_name_may_ask_and_is_returned_to():
    mw = routers(lan_domain=LAN, lan_port=PORT)["middlewares"]
    assert f"http://console.{LAN}:{PORT}" in mw["dgo-remote-console-asks"]["headers"]["accessControlAllowOriginList"]
    assert serve.re.escape(f"console.{LAN}") in mw["dgo-remote-console-returns"]["redirectRegex"]["regex"]
