#!/usr/bin/env python3
"""DGO-36 · phase 3 — the reverse direction and pairing: the gate of
ai/context/dgo-extend-plan.md §12.

Run with `bbox dgo test 3`. What it checks, and why each one is the gate rather than a symptom:

  · the `serve:` plane has RULES, and they refuse the mistakes that produce a route to the wrong
    place (a public address instead of a tunnel address, a port nobody declared, two apps on one
    tile, an identity value that would be a header injection) — pure functions, so they are measured
    even before any remote office exists;
  · the compiled route is what the tile needs: the nested host the shell derives at click time, the
    peer's tunnel address as the backend, this office's own SSO on it, and — the part that is easy to
    forget and impossible to explain afterwards — a provider at the identity layer for that host;
  · the tile is in the registry the console reads, and its `desc` names the office, because that
    string is what the shell shows when the remote is asleep (a framed host that never renders is
    detected and replaced by a Hebrew notice — the only "the remote is down" signal the owner gets);
  · an identity from anywhere but the link, or for an app that is not in `serve:`, or a user that is
    not mapped here, is 401 — and an anonymous request is NOT, because refusing those would take the
    local app down for everyone the moment one link exists;
  · pairing: a photographed offer redeems nothing, a wrong code aborts, an expired offer is refused.

Everything that needs the LINK ITSELF to be up (the tile answering, `bbox agent list` on the far
side, a real QR scan) reports what is missing and which work item owes it — a gate that goes green
because it could not look is worse than no gate.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phase0 import LAST_INSIDE_ERR, check, inside, run  # noqa: E402  (shared frame, deliberately)

ROOT = Path(__file__).resolve().parents[3]
SERVE_PY = ROOT / "platform/manager/serve.py"
PAIRING_PY = ROOT / "apps/dgo-extend/pairing.py"


def _serve_module():
    sys.path.insert(0, str(ROOT / "platform/manager"))
    import serve
    return serve


def _synthetic_entry(alias: str = "bina-mac") -> dict:
    """One entry of the `remote:` block as the projection writes it — the shape the compiler reads."""
    return {"office": "macbook", "address": "10.79.3.2",
            "label": {"he": "המקבוק", "en": "MacBook"}, "link": "macbook",
            "identity": {"to": "owner@local", "from": ["akadmin"]},
            "apps": [{"app": "bina-ds", "alias": alias, "port": 3080, "agent_api_port": 3081,
                      "name": "בינה ודעת", "icon": "bot", "group": "ראשי", "order": 1,
                      "desc": "הסוכן של הלשכה", "host": "bina.localhost",
                      "identity": {"to": "owner@local", "from": "akadmin"}}]}


@check("DGO-30 · the `serve:` plane refuses what would route to the wrong place")
def c_serve_rules():
    code, out = run(["python3", str(SERVE_PY)], 120)
    return code == 0, (out.strip().splitlines()[-1] if out.strip() else "no output")


@check("DGO-30 · the compiled route is the tile's: nested host, tunnel backend, SSO, mapping")
def c_serve_render():
    """The assertions here are the ones that cost an afternoon when they are wrong: the host the
    SHELL will ask for (it derives `<host>.<console hostname>`, so the router must match the same
    nesting), the backend being the PEER's tunnel address rather than a local service, and the SSO
    middleware — a served app published without it is another office's UI, open, on this office's
    domain."""
    import yaml
    serve = _serve_module()
    cat = json.loads((ROOT / "platform-base/console/app.json").read_text(encoding="utf-8"))
    doc = yaml.safe_load(serve.render([_synthetic_entry()], cat, domain="staging.example.co.il"))
    problems = []
    if "dgo-remote-macbook-bina-mac-console" not in doc["http"]["routers"]:
        problems.append("no router for the domain form of the remote host")
    rule = doc["http"]["routers"]["dgo-remote-macbook-bina-mac-console"]["rule"]
    # TWO labels before the console's own: `<alias>.<office>`. One label would put two offices'
    # apps in one namespace and make "which office is this" unanswerable from the host alone.
    if "`bina-mac.macbook.console.staging.example.co.il`" not in rule:
        problems.append(f"the router must match the nested host the shell derives, got {rule}")
    local = doc["http"]["routers"]["dgo-remote-macbook-bina-mac-console-local"]["rule"]
    if "`bina-mac.macbook.console.localhost`" not in local:
        problems.append(f"missing the local twin (the laptop deployment), got {local}")
    svc = doc["http"]["services"]["dgo-remote-macbook-bina-mac"]["loadBalancer"]["servers"][0]["url"]
    # The link proxy's network alias — NOT the peer's tunnel address, which exists only inside the
    # tunnel container's namespace and is not routable from the network the edge lives on.
    if svc != "http://bina-mac.macbook:3080":
        problems.append(f"the backend must be the link proxy's alias for the peer, got {svc}")
    if "10.79.3.2" in json.dumps(doc):
        problems.append("the peer's tunnel address must not appear in a route the edge serves")
    mw = doc["http"]["routers"]["dgo-remote-macbook-bina-mac-console"]["middlewares"]
    if "authentik@file" not in mw:
        problems.append("a remote host without this office's SSO is another office's UI, open")
    if "dgo-remote-macbook-identity" not in mw:
        problems.append("the identity mapping middleware is missing")
    mapped = doc["http"]["middlewares"]["dgo-remote-macbook-identity"]["headers"]["customRequestHeaders"]
    if mapped.get("X-authentik-username") != "owner@local":
        problems.append(f"the mapped identity must be the local user, got {mapped}")
    # And the identity layer must know the name, or forwardAuth answers 404 with a live router.
    hosts = [h["host"] for h in serve.sso_hosts([_synthetic_entry()], cat,
                                                domain="staging.example.co.il")]
    if "bina-mac.macbook.console.staging.example.co.il" not in hosts:
        problems.append(f"no identity provider host for the remote name, got {hosts}")
    return not problems, ("המסלול, הזהות וה-SSO כפי שהמסך צריך" if not problems
                          else "; ".join(problems))


@check("DGO-30 · the tile is in the registry the console reads, and names its office")
def c_serve_tile():
    """Compiled, not merged at runtime: the tile has to be there before any remote process has run.
    `external` is what makes the shell FRAME the app on its own host instead of proxying it through
    a WSGI proxy that buffers — an agent UI holds a websocket on /api."""
    serve = _serve_module()
    cat = json.loads((ROOT / "platform-base/console/app.json").read_text(encoding="utf-8"))
    tiles = serve.module_entries([_synthetic_entry()], cat)
    if not tiles:
        return False, "a remote app produced no tile"
    t = tiles[0]
    problems = []
    if not t.get("external"):
        problems.append("the tile must be `external` (framed on its own host, not proxied)")
    if t.get("id") != "bina-mac.macbook" or t.get("host") != t.get("id"):
        problems.append(f"the tile is namespaced by its office, got id {t.get('id')!r}")
    if t.get("office") != "macbook":
        problems.append("the tile must name the office it lives on")
    if "מקבוק" not in (t.get("desc") or ""):
        problems.append("the tile's text must name the office — it is what the shell shows when the "
                        "remote does not answer")
    if (t.get("remote") or {}).get("link") != "macbook":
        problems.append("the tile carries the link record the app manager and the CLI read")
    # The owner's own rule: an app installed in BOTH offices appears twice. A local `bina` owns a
    # tile named `bina`; the remote one is `bina.macbook` and must survive it.
    both = [x for x in serve.module_entries([_synthetic_entry("bina")], cat)
            if x.get("id") == "bina.macbook"]
    if not both:
        problems.append("a local app with the same alias must NOT suppress the remote tile")
    return not problems, (f"tile {t.get('id')} → host {t.get('host')}.<console host>"
                          if not problems else "; ".join(problems))


@check("DGO-31 · the compiler registers the served host at the IDENTITY layer too")
def c_serve_identity_provider():
    """A router is not a served host until authentik knows the name: measured on this deployment
    2026-09-30, the emitted router matched and forwardAuth answered 404 for a host nobody had
    registered, while the edge looked healthy in the access log."""
    src = (ROOT / "platform/manager/reconcile.py").read_text(encoding="utf-8")
    blueprint = ROOT / "platform-base/authentik/blueprints/zz-generated-apps.yaml"
    generated = blueprint.read_text(encoding="utf-8") if blueprint.exists() else ""
    served_declared = bool(_serve_module().plan(_state(), _catalog())[0])
    # The slug the compiler emits for a remote host (`serve.sso_hosts`): `dgo-remote-<office>-<alias>`.
    has = "dgo-remote-" in generated
    if not served_declared:
        # Nothing is served to THIS office right now. The emission itself is what can be checked, and
        # the compiler must not have left a stale provider behind from a declaration that is gone.
        return (not has), ("אין remote: בלשכה הזאת, וגם אין שארית ב-blueprint" if not has
                           else "a stale serve provider survived the declaration")
    return has, (f"blueprint carries {generated.count('provider-dgo-remote-')} remote provider(s)"
                 if has else "the served host has no identity provider — it will 404 at the outpost")


def _state():
    import yaml
    return yaml.safe_load((ROOT / "platform.state.yaml").read_text(encoding="utf-8")) or {}


def _catalog():
    cat = {}
    for root in (ROOT / "platform-base", ROOT / "apps"):
        for m in root.glob("*/app.json"):
            a = json.loads(m.read_text(encoding="utf-8"))
            cat[a["id"]] = a
    return cat


@check("DGO-30 · the compiled traefik file matches the declaration, and vanishes with it")
def c_serve_file():
    """Both directions of the same fact. A declared `serve:` that did not reach traefik is a tile
    that 404s; a REMOVED one that is still on the edge is a route to another office's app that
    nobody meant to keep. The file is gitignored compiled output, so its absence is the normal
    state of an office that serves nothing."""
    target = ROOT / "platform-base/traefik/config/zz-serve.yaml"
    entries, errs = _serve_module().plan(_state(), _catalog())
    if errs:
        return False, "the declaration does not validate: " + errs[0]
    if not entries:
        return (not target.exists()), ("אין serve: ואין קובץ — המצב הנקי" if not target.exists()
                                       else "a stale zz-serve.yaml is still routing")
    if not target.exists():
        return False, "serve: is declared but traefik has no compiled route (run `bbox reconcile`)"
    import yaml
    doc = yaml.safe_load(target.read_text(encoding="utf-8"))
    rules = " ".join(r.get("rule", "") for r in (doc.get("http", {}).get("routers") or {}).values())
    missing = [f"{a['alias']}.{e['office']}" for e in entries for a in e["apps"]
               if f"`{a['alias']}.{e['office']}.console." not in rules]
    if missing:
        return False, f"declared but not routed: {missing}"
    return True, (f"{sum(len(e['apps']) for e in entries)} served app(s) routed on "
                  f"{doc['http']['services'] and len(doc['http']['services'])} service(s)")


@check("DGO-33 · three pairing flows, one result — and a photograph redeems nothing")
def c_pairing():
    code, out = run(["python3", str(PAIRING_PY)], 120)
    return code == 0, (out.strip().splitlines()[-1] if out.strip() else "no output")


@check("DGO-33/34 · the two halves of a pairing read each other, and two offices pair end to end")
def c_pair_contract():
    """`pairing.py` and `static/connect.js` each passed their own selftest while speaking two different
    formats — so this runs one side's output through the other side's reader, then pairs two in-memory
    offices through every refusal (tests/pair_contract.py owns the detail)."""
    code, out = run(["python3", str(ROOT / "apps/dgo-extend/tests/pair_contract.py")], 180)
    lines = [x for x in out.strip().splitlines() if x.strip()]
    return code == 0, (lines[-1] if lines else "no output")


@check("DGO-49 · §9 of the pairing contract, as tests (its gaps are reported, never hidden)")
def c_link_security():
    """The trust boundary of a PAIRED office, one test per claim it makes — and the two claims the code
    does not hold are `xfail` with the code path named, which this check reports rather than swallows.
    Hermetic: no office, no tunnel, no network (tests/test_link_security.py owns the detail)."""
    code, out = run(["python3", str(ROOT / "apps/dgo-extend/tests/test_link_security.py")], 180)
    lines = [x for x in out.strip().splitlines() if x.strip()]
    summary = next((x for x in reversed(lines) if x.startswith("link_security:")),
                   lines[-1] if lines else "no output")
    gaps = [x for x in lines if x.startswith("XFAIL")]
    return code == 0, (summary + (f" · {len(gaps)} documented gap(s) open" if gaps else ""))


@check("DGO-33 · the offer carries public material only")
def c_offer_public():
    """The offer is a QR code: displayed, photographed, kept. If anything secret is inside it, the
    photograph IS the link. Checked structurally — on a real offer, minted here — rather than by
    reading the code, because "we were careful" is not a property a gate can hold."""
    sys.path.insert(0, str(ROOT / "apps/dgo-extend"))
    import pairing
    ident = {"ed25519": base64.b64encode(b"J" * 32).decode(), "wg": "W", "fingerprint": "AAAA-BBBB"}
    offer, _priv = pairing.new_offer("portable", ident, ["192.168.16.103:51820"])
    blob = json.dumps(offer).lower()
    leaked = [w for w in ("token", "private", "secret", "password") if w in blob]
    if leaked:
        return False, f"the offer carries {leaked} — a photographed QR would hand over the link"
    text = pairing.offer_text(offer)
    back = pairing.parse_offer(text)
    return (back["offer_id"] == offer["offer_id"]), \
           f"{len(text)} bytes of public material · offer_id round-trips"


@check("DGO-30 · a tile on the far console opens THIS office's app")
def c_live_tile():
    """The phase's acceptance, measured over the door a BROWSER uses.

    The tile lives on the OTHER office's console (`<alias>.<this office>.console.<its domain>`), and
    nothing here can read that office's registry. What this side can measure is the door itself: the
    nested host answering with that office's SSO over a certificate a browser accepts. The far side's
    own `health` step reports the same host from there (measured: `23/23 addresses answer` and the
    SSO outpost serving every gated host), and `reconcile render` on it emitted the router with
    `authentik@file` + the identity mapping + this app's own `Host`.
    """
    doc = _app_get("/api/link")
    if doc is None:
        return False, f"dgo-extend is not answering here ({LAST_INSIDE_ERR})"
    office = str((doc.get("home") or {}).get("id") or "")
    served = sorted((doc.get("serve") or {}).keys())
    if not served or not office:
        return False, ("NOT BUILT — this office declares nothing under `serve:`, so there is no tile "
                       "of its apps on any console")
    peers = _app_get("/api/office") or {}
    # WHICH TILE IS MEASURED: one this office really gives — its agent when it gives one. NOT the
    # first key of the `serve:` map: an office that gives everything declares `{"*": {}}`, and `*` is
    # not an app. Read that way, the host asked for was `*.<office>.console.<domain>` and the check
    # failed on the MacBook office (2026-10-05) while the real tile answered 302 by hand.
    giving = _app_get("/api/pair/giving") or {}
    given = [a.get("alias") for a in (giving.get("apps") or []) if a.get("given") and a.get("alias")]
    named = [s for s in served if s != "*"]
    alias = ("bina" if "bina" in given else given[0]) if given else (_manifest_alias(named[0]) if named else "")
    if not alias:
        return False, ("this office gives every app (`serve: {\"*\": {}}`) but does not answer which ones "
                       "(`GET /api/pair/giving`) — rebuild dgo-extend, then run this again")
    for decl in (peers.get("items") or []):
        domain = str(decl.get("domain") or "").strip()
        link = [l for l in (decl.get("links") or []) if (l or {}).get("office") == office]
        if not (domain and link):
            continue
        host = f"{alias}.{office}.console.{domain}"
        code, out = run(["curl", "-sk", "-o", "/dev/null", "-w", "%{http_code}", "-m", "25",
                         f"https://{host}/"], 60)
        status = (out or "").strip().splitlines()[-1].strip() if (out or "").strip() else ""
        ok = code == 0 and status in ("200", "301", "302", "303", "307", "308")
        return ok, (f"{host} → {status}" + (" (הלשכה המרוחקת עונה ומפנה ל-SSO שלה)"
                                            if ok else " — הלשכה המרוחקת אינה עונה על האריח"))
    # A PAIRED office is a different case from "nobody": it uses this office's apps over the link,
    # but its record here carries no console domain (it was never installed from here), so the URL of
    # the tile is a fact only that office has. Saying "not built" would send the reader looking for a
    # missing link; the gap is the measurement, and the sentence names where it can be taken.
    paired = [str(d.get("id")) for d in (peers.get("items") or [])
              if str(d.get("kind") or "") == "paired"
              and any((l or {}).get("office") == office and (l or {}).get("direction") in ("use", "both")
                      for l in (d.get("links") or []))]
    if paired:
        # MEASURED THROUGH THE PAIR ITSELF, as far as this side can start it. A paired office that
        # gives its console can be asked, over the link's door, for one of THIS office's tiles exactly
        # as its own console serves it — the same-origin path `/a/<alias>.<this office>/`. The request
        # travels this office → the link → that console → the link → this office's app. That path
        # exists only for an app a console may frame under a path (`serve.through_console`): the
        # agent keeps its own host on every console, and that host is routed by the FAR office's
        # edge, so its tile is measured there. An office that does not give its console is measured
        # only there too.
        import serve
        import yaml
        try:
            rows = json.loads((ROOT / ".generated/registry/office.apps.json").read_text(encoding="utf-8"))["apps"]
            remote = (yaml.safe_load((ROOT / "platform.state.yaml").read_text(encoding="utf-8")) or {}).get("remote") or []
        except (OSError, ValueError, KeyError, yaml.YAMLError) as e:
            return False, f"this office's compiled registry or state could not be read ({type(e).__name__})"
        pathed = {r.get("alias") for r in rows if serve.through_console(
            {"module_kind": (r.get("module") or {}).get("kind"), "host": r.get("host")})}
        mine = next((a for a in given if a in pathed), "")
        own_host = [a for a in given if a not in pathed]
        for peer in paired:
            entry = next((e for e in remote if isinstance(e, dict) and e.get("office") == peer), {})
            console = next((a for a in (entry.get("apps") or []) if a.get("alias") == "console-home"), None)
            if not (console and mine):
                continue
            door = f"http://console-home.{peer}:{int(entry.get('link_port') or 0) or int(console.get('port') or 0)}"
            path = f"/a/{mine}.{office}/"
            raw = inside("console", (
                "import urllib.request, urllib.error\n"
                f"req = urllib.request.Request({door + path!r}, headers={{'Host': {str(console.get('host') or '')!r}}})\n"
                "try:\n"
                "    print(urllib.request.urlopen(req, timeout=45).status)\n"
                "except urllib.error.HTTPError as e:\n"
                "    print(e.code)\n"
                "except Exception as e:\n"
                "    print('ERR', type(e).__name__)\n"), 90)
            status = (raw or "").strip().splitlines()[-1].strip() if (raw or "").strip() else "no answer"
            return status == "200", (f"{peer}'s console serves this office's `{mine}` over the link: "
                                     f"{path} → {status}" + (f" · {', '.join(own_host)} keep their own host "
                                                             f"there, routed by {peer}'s edge" if own_host else ""))
        return False, (f"NOT MEASURED HERE — {', '.join(paired)} uses this office's apps over a pairing, and a "
                       f"paired record holds no console domain: the tile is measured on that office "
                       f"(its console, `<alias>.{office}`), not from this one")
    return False, ("NOT BUILT — no declared office holds a link to this one, so nothing can frame "
                   "this office's apps")


@check("DGO-32 · a remote app is reached through the peer's ONE DOOR, and the Host it expects")
def c_door_route():
    """The door is what makes "all of vps1's apps" possible: its registry holds four apps on 8080, and
    a listener per app collides. So the route the edge serves must target the DOOR PORT the serving
    office published — and must still write the authority that app answers under, because the door
    picks the app by that very name (DGO-32, measured on vps1 2026-10-02).

    Two entries, so both halves of the rule are asserted: one app with its own authority, one with
    `host: ""` (pass-through), whose Host must be left alone for the door to match its alias.
    """
    import yaml
    serve = _serve_module()
    cat = json.loads((ROOT / "platform-base/console/app.json").read_text(encoding="utf-8"))
    entry = _synthetic_entry()
    entry["link_port"] = 9002
    entry["apps"].append({"app": "drive", "alias": "drive", "port": 8975, "name": "דרייב",
                          "icon": "drive", "group": "ראשי", "order": 2, "desc": "קבצים",
                          "host": "drive.example.co.il", "module_kind": "external",
                          "module_path": "/a/drive/"})
    entry["apps"][0].pop("host", None)          # bina: the pass-through case
    entries, errs = serve.plan({"remote": [entry]}, cat)
    if errs:
        return False, f"the door block does not compile: {errs[0]}"
    doc = yaml.safe_load(serve.render(entries, cat, domain="staging.example.co.il"))
    problems = []
    for alias in ("bina-mac", "drive"):
        url = doc["http"]["services"][f"dgo-remote-macbook-{alias}"]["loadBalancer"]["servers"][0]["url"]
        if url != f"http://{alias}.macbook:9002":
            problems.append(f"`{alias}` must be reached at the peer's DOOR, got {url}")
    drive = doc["http"]["routers"]["dgo-remote-macbook-drive-console"]["middlewares"]
    if "dgo-remote-macbook-drive-host" not in drive:
        problems.append("an app with its own authority must be reached under it — the door routes by "
                        "that name")
    bina = doc["http"]["routers"]["dgo-remote-macbook-bina-mac-console"]["middlewares"]
    if "dgo-remote-macbook-bina-mac-host" in bina:
        problems.append("`host: ""` is pass-through: the consuming office's own nested name must "
                        "reach the door unchanged")
    # And an office that published no door (a peer from before it) keeps working exactly as before:
    # the app's own port IS the door, which is what the link proxy listened on until now.
    plain = _synthetic_entry()
    doc2 = yaml.safe_load(serve.render(serve.plan({"remote": [plain]}, cat)[0], cat,
                                       domain="staging.example.co.il"))
    url = doc2["http"]["services"]["dgo-remote-macbook-bina-mac"]["loadBalancer"]["servers"][0]["url"]
    if url != "http://bina-mac.macbook:3080":
        problems.append(f"a peer with no published door keeps its app's own port, got {url}")
    return not problems, ("שני מסלולים דרך דלת אחת (9002), כל אחד בכותרות שהוא מצפה להן"
                          if not problems else "; ".join(problems))


@check("DGO-38 · the door connects to the app's SERVICE, not to its id")
def c_door_service():
    """Measured 2026-10-02, on the first full pass over a linked office's apps: 13 of vps1's 15
    answered through the door and two did not — `indox` (served by `incoming-documents`) and `mail`
    (served by `mailview`), both with an empty `502`. The door resolves a HOSTNAME; the catalog
    published the app's ID as it; and for those two the two differ.

    The chain is asserted here, in the three places it has to hold: the compiler's row carries the
    service, the catalog publishes it, and the door's route table uses it (falling back to the app's
    id, so a peer that predates the field keeps every app that DID work).
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("dgo_door_mod",
                                                 ROOT / "apps/dgo-extend/link-proxy.py")
    door_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(door_mod)
    doc = {"apps": [
        {"app": "indox", "alias": "incoming", "port": 8080, "service": "incoming-documents",
         "host": "incoming-documents.localhost"},
        {"app": "mail", "alias": "mailview", "port": 8976, "service": "mailview",
         "host": "mail.localhost"},
        {"app": "drive", "alias": "drive", "port": 8975, "host": "drive.localhost"}]}
    table = door_mod.Door._table(doc)
    problems = []
    if table.get("incoming-documents.localhost", (None,))[0] != "incoming-documents":
        problems.append(f"`indox` must be reached at its service, got {table.get('incoming-documents.localhost')}")
    if table.get("mail.localhost", (None,))[0] != "mailview":
        problems.append(f"`mail` must be reached at its service, got {table.get('mail.localhost')}")
    if table.get("drive.localhost", (None,))[0] != "drive":
        problems.append("an app whose service IS its id must keep working (fallback)")
    # and the field has to cross the link: the compiler's row → the catalog's entry
    sys.path.insert(0, str(ROOT / "apps/dgo-extend"))
    import catalog
    row = {"app": "indox", "alias": "incoming", "port": 8080, "name": "מסכים", "service": "incoming-documents"}
    entry = catalog.build({"apps": [row]}, "macbook", {"he": "המקבוק", "en": "MacBook"})["apps"][0]
    if entry.get("service") != "incoming-documents":
        problems.append(f"the catalog does not publish the service: {entry.get('service')!r}")
    return not problems, ("indox → incoming-documents · mail → mailview · drive → drive (fallback)"
                          if not problems else "; ".join(problems))


@check("DGO-SEC · the door replaces a peer's whole identity, and keeps a connection only for a websocket")
def c_door_identity():
    """Who is calling is THIS office's answer, and it is given for every request.

    A request that crossed a link was authenticated by the other office's identity provider. Two ways
    it could still speak for itself here (found 2026-10-05, reading the door):
      · only `X-authentik-username` was replaced — groups, e-mail, uid and the signed token arrived
        as the peer wrote them;
      · the word `upgrade` in a `Connection` header kept the connection open, so a SECOND request on
        it reached the app with the peer's own `X-authentik-username`, never rewritten.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("dgo_door_mod", ROOT / "apps/dgo-extend/link-proxy.py")
    door = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(door)
    D = door.Door

    def fields(head: bytes) -> dict:
        out = {}
        for line in head.split(b"\r\n\r\n", 1)[0].split(b"\r\n")[1:]:
            name, _, value = line.partition(b":")
            out.setdefault(name.strip().lower(), []).append(value.strip())
        return out

    claimed = (b"POST /api/x HTTP/1.1\r\nHost: apps.localhost\r\nX-authentik-username: root-of-the-peer\r\n"
               b"X-Authentik-Groups: authentik Admins\r\nx-authentik-email: a@peer\r\nX-authentik-jwt: e30.e30.x\r\n"
               b"X-authentik-uid: 1\r\nConnection: keep-alive, upgrade\r\nContent-Length: 2\r\n\r\n{}")
    got = fields(D.rewrite(claimed, "mapped"))
    problems = []
    family = sorted(k.decode() for k in got if k.startswith(b"x-authentik-"))
    if family != ["x-authentik-username"] or got[b"x-authentik-username"] != [b"mapped"]:
        problems.append(f"only this office's mapped user may arrive, got {family} = {got.get(b'x-authentik-username')}")
    if got.get(b"connection") != [b"close"]:
        problems.append(f"an ordinary request that says `upgrade` must still be the only one on its "
                        f"connection, got Connection: {got.get(b'connection')}")
    if got.get(b"host") != [b"apps.localhost"] or got.get(b"content-length") != [b"2"] or b"{}" in D.rewrite(claimed, "mapped"):
        problems.append("the rest of the head must arrive as sent, and the body is not part of it")
    if any(k.startswith(b"x-authentik-") for k in fields(D.rewrite(claimed, ""))):
        problems.append("with no mapping published, NO identity arrives — never the peer's own")
    # …and WHICH OFFICE is asking is the link's fact: the door's own rule, never the peer's header.
    forged = claimed.replace(b"Connection:", b"X-DGO-Office: some-third-office\r\nConnection:")
    named = fields(D.rewrite(forged, "mapped", "macbook")).get(b"x-dgo-office")
    if named != [b"macbook"] or b"x-dgo-office" in fields(D.rewrite(forged, "mapped")):
        problems.append(f"the office a request came from is written by the door and only by it, got {named}")
    shake = (b"GET /api/remote.mux HTTP/1.1\r\nHost: bina.localhost\r\nUpgrade: websocket\r\n"
             b"Connection: Upgrade\r\nSec-WebSocket-Key: x\r\nX-authentik-username: someone\r\n\r\n")
    ws = fields(D.rewrite(shake, "mapped"))
    if not D.websocket(shake) or ws.get(b"connection") != [b"Upgrade"] or ws.get(b"x-authentik-username") != [b"mapped"]:
        problems.append(f"a websocket handshake keeps its upgrade and gets the mapped user: {ws}")
    for label, head in (("a POST", shake.replace(b"GET ", b"POST ")),
                        ("another protocol", shake.replace(b"Upgrade: websocket", b"Upgrade: h2c")),
                        ("no Connection: upgrade", shake.replace(b"Connection: Upgrade", b"Connection: keep-alive"))):
        if D.websocket(head) or fields(D.rewrite(head, "mapped")).get(b"connection") != [b"close"]:
            problems.append(f"{label} is not a websocket handshake and must close after one request")
    return not problems, ("the peer's five identity headers arrive as one: this office's mapped user · "
                          "`upgrade` without a websocket handshake closes after one request"
                          if not problems else "; ".join(problems))


@check("DGO-32 · a door carries an answer however long the app takes to give it")
def c_door_waits():
    """A door carries an answer however long the app takes to give it — on real sockets, on loopback.

    Measured 2026-10-05, both directions of one move: the MacBook asked hp-laptop to bring an app up
    (a call that answers after twenty seconds), hp-laptop started doing it, and the MacBook read 502;
    then hp-laptop's fetch of a 40 MB archive through the MacBook's door ended "closed without
    response". The head's read timeout had stayed on the client's socket, so a client waiting for its
    answer counted as silent, and the copy loop's cleanup shut both directions down after 5 seconds.
    """
    import importlib.util
    import socket
    import threading
    import time as _time
    spec = importlib.util.spec_from_file_location("dgo_door_slow", ROOT / "apps/dgo-extend/link-proxy.py")
    lp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lp)
    lp.log = lambda _m: None
    lp.CONNECT_TIMEOUT = 0.5                              # the head's own timeout, made short for the check
    SLOW = 2.0                                            # four times that: the app thinks, then answers

    app = socket.socket()
    app.bind(("127.0.0.1", 0))
    app.listen(4)

    def slow_app():
        while True:
            try:
                c, _ = app.accept()
            except OSError:
                return
            c.recv(65536)
            _time.sleep(SLOW)
            c.sendall(b"HTTP/1.1 202 Accepted\r\nContent-Length: 7\r\nConnection: close\r\n\r\nrunning")
            c.close()
    threading.Thread(target=slow_app, daemon=True).start()

    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()
    door = lp.Door({"office": "macbook", "app": "door", "kind": "door", "direction": "serve",
                    "bind": "127.0.0.1", "port": port, "target": "unused"})
    door.route = lambda host: ("127.0.0.1", app.getsockname()[1], "mapped")
    door.start()
    door.ready.wait(5)
    got, took = b"", 0.0
    try:
        started = _time.time()
        with socket.create_connection(("127.0.0.1", port), timeout=SLOW + 6) as c:
            c.sendall(b"POST /api/apps/x/enable HTTP/1.1\r\nHost: apps.localhost\r\nContent-Length: 2\r\n\r\n{}")
            while True:
                chunk = c.recv(4096)
                if not chunk:
                    break
                got += chunk
        took = _time.time() - started
    except OSError as e:
        got = f"{type(e).__name__}: {e}".encode()
    finally:
        door._halt.set()
        app.close()
    ok = got.startswith(b"HTTP/1.1 202") and got.endswith(b"running") and took >= SLOW
    return ok, (f"an answer that took {took:.1f}s arrived whole through a door whose head timeout is "
                f"{lp.CONNECT_TIMEOUT}s" if ok else f"the door cut a slow answer: {got[:80]!r} after {took:.1f}s")


@check("DGO-32 · a rule that changes keeps its door: the port is released first, and a failed bind is retried")
def c_proxy_reload():
    """The proxy follows the plan while it runs — on real sockets, on loopback.

    Measured 2026-10-05 on hp-laptop: the plan's targets changed, the proxy stopped each listener and
    started its replacement in one breath, the port was still held by the old listener's thread, and
    the link's door then refused every connection while the log said `plan applied: 6 listener(s)`.
    """
    import importlib.util
    import socket
    import tempfile
    import threading
    spec = importlib.util.spec_from_file_location("dgo_proxy_mod", ROOT / "apps/dgo-extend/link-proxy.py")
    lp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lp)

    def answering(word: bytes):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(8)

        def loop():
            while True:
                try:
                    c, _ = srv.accept()
                except OSError:
                    return
                c.sendall(word)
                c.close()
        threading.Thread(target=loop, daemon=True).start()
        return srv

    def ask(port: int) -> bytes:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
                return c.recv(16)
        except OSError as e:
            return f"refused ({e.strerror or e})".encode()

    first, second = answering(b"first"), answering(b"second")
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    problems = []
    with tempfile.TemporaryDirectory() as d:
        lp.PLAN = Path(d) / "link-proxy.json"
        lp.log = lambda _m: None

        def plan(target_port: int) -> None:
            lp.PLAN.write_text(json.dumps({"rules": [{
                "office": "peer", "app": "x", "direction": "use", "bind": "127.0.0.1", "port": port,
                "target": f"127.0.0.1:{target_port}"}]}), encoding="utf-8")
        proxy = lp.Proxy()
        plan(first.getsockname()[1])
        proxy.sync()
        if ask(port) != b"first":
            problems.append(f"the rule must deliver to its target, got {ask(port)!r}")
        plan(second.getsockname()[1])
        proxy.sync()
        got = ask(port)
        if got != b"second":
            problems.append(f"a rule whose target changed must keep answering, on the new target: {got!r}")
        # a listener that could not bind is not "applied": it is tried again, with the plan unchanged
        key = ("127.0.0.1", port)
        proxy.forwarders[key].stop()
        holder = socket.socket()
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # as the proxy's own listeners
        holder.bind(key)
        holder.listen(1)
        proxy.forwarders.pop(key)
        proxy._stamp = ()
        proxy.sync()
        if not proxy.forwarders[key].refused:
            problems.append("a listener whose port is held must say it could not bind")
        holder.close()
        proxy.sync()
        got = ask(port)
        if got != b"second":
            problems.append(f"a refused listener must be tried again once the port is free: {got!r}")
        for f in list(proxy.forwarders.values()):
            f.stop()
    first.close()
    second.close()
    return not problems, ("the target changed and the same port kept answering · a held port was "
                          "retried without a new plan" if not problems else "; ".join(problems))


@check("DGO-SEC · a linked office reaches the catalog, and nothing else of this app")
def c_link_listener():
    """What a peer can call is what the link listener serves — measured on the running app.

    The control door is a raw splice: it carries every path to whatever it leads to. It led to this
    app's own port, so a pairing that gave one app handed a peer the whole API — declare and converge
    offices, move apps, read the stored login of an installed office (found 2026-10-05). Three facts
    keep that closed, and each is asked of the live office rather than of the source:
      · the link listener answers the catalog and refuses an ordinary route of this app;
      · the app's own port no longer serves the catalog (one place, not two);
      · no rule of the live plan leads from the tunnel to the app's own port.
    """
    raw = inside("dgo-extend", (
        "import json, os, urllib.request, urllib.error\n"
        "import catalog\n"
        "def code(port, path):\n"
        "    try:\n"
        "        return urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=15).status\n"
        "    except urllib.error.HTTPError as e:\n"
        "        return e.code\n"
        "    except Exception as e:\n"
        "        return type(e).__name__\n"
        "plan = json.load(open('/tunnel/link-proxy.json')) if os.path.exists('/tunnel/link-proxy.json') else {}\n"
        "own = f'dgo-extend:{int(catalog.CATALOG_PORT)}'\n"
        "print('SEC=' + json.dumps({'link': int(catalog.LINK_PORT),\n"
        "    'catalog_on_link': code(catalog.LINK_PORT, '/api/link/catalog'),\n"
        "    'office_on_link': code(catalog.LINK_PORT, '/api/office'),\n"
        "    'login_on_link': code(catalog.LINK_PORT, '/api/office/x/login'),\n"
        "    'catalog_on_app': code(catalog.CATALOG_PORT, '/api/link/catalog'),\n"
        "    'to_own_port': [r.get('port') for r in plan.get('rules') or []\n"
        "                    if r.get('direction') == 'serve' and str(r.get('target')) == own]}))\n"), 60)
    line = [l for l in (raw or "").splitlines() if l.startswith("SEC=")]
    if not line:
        return False, f"dgo-extend is not answering here ({LAST_INSIDE_ERR or (raw or '')[:120]})"
    got = json.loads(line[-1][4:])
    ok = (got["catalog_on_link"] == 200 and got["office_on_link"] == 404 and got["login_on_link"] == 404
          and got["catalog_on_app"] == 404 and not got["to_own_port"])
    return ok, (f"link listener :{got['link']} — catalog {got['catalog_on_link']}, /api/office "
                f"{got['office_on_link']}, a stored login {got['login_on_link']} · the app's own port "
                f"answers the catalog {got['catalog_on_app']} · rules from the tunnel to the app's own "
                f"port: {got['to_own_port'] or 'none'}")


@check("DGO-32 · the catalog publishes the SERVED apps and nothing else")
def c_catalog_served():
    """A tile must mean a door (DGO-32, blocker 3 measured on vps1 2026-10-02).

    The catalog is what a linked office renders tiles from, so an app in it that nothing delivers to
    is a tile that cannot open. Measured there: the registry held 21 apps and `serve:` named none —
    the MacBook projected eight tiles of apps no door reached. The assertion is a SUBSET relation in
    the served direction, so it holds for an office that serves everything and for one that serves
    nothing: every published app must be a served one.

    Asked of the module that answers the route (`app.build_catalog`), which is the same answer the
    link listener gives a peer (see the check below for what that listener does NOT give).
    """
    raw = inside("dgo-extend",
                 "import json,os;"
                 "import app as a, linkproxy as lp;"
                 "cat=a.build_catalog();"
                 "serve=a.cv.home_office().get('serve') or {};"
                 "rules=(lp.read(os.environ.get('DGO_TUNNEL_DIR','/tunnel')).get('plan') or {}).get('rules') or [];"
                 "print('CAT='+json.dumps({"
                 "'apps':[x.get('alias') for x in cat.get('apps') or []],"
                 "'agents':{str(x.get('alias')):x.get('agent_api_port') for x in cat.get('apps') or [] if x.get('agent_api_port')},"
                 "'opened':sorted({int(r.get('port') or 0) for r in rules if r.get('direction')=='serve'}),"
                 "'serve':sorted(k for k in serve if k != 'exclude')}))")
    if not raw:
        return False, f"dgo-extend is not answering here ({LAST_INSIDE_ERR})"
    line = [l for l in raw.splitlines() if l.startswith("CAT=")]
    if not line:
        return False, f"the catalog check printed nothing readable: {raw[:160]}"
    try:
        doc = json.loads(line[-1][4:])
    except ValueError:
        return False, f"the catalog check is not a document: {line[-1][:160]}"
    served = {str(k).strip().lower() for k in doc.get("serve") or []}
    published = {str(a or "").strip().lower() for a in doc.get("apps") or []}
    if not served and published:
        return False, (f"this office serves nothing, yet its catalog publishes {sorted(published)}")
    extra = set() if "*" in served else {a for a in published if a not in served}
    if extra:
        return False, (f"published but not served: {sorted(extra)} — a tile with no door behind it")
    # The same rule for an agent app's SECOND door: a port in the catalog is a port a peer builds a
    # listener for. Asked only of an office that serves somebody (no pair, no plan, nothing to open).
    opened = {int(p) for p in doc.get("opened") or []}
    closed = {a: p for a, p in (doc.get("agents") or {}).items() if opened and int(p) not in opened}
    if closed:
        return False, (f"an agent API is published and nothing opens it: {closed} — the peer's CLI "
                       f"is reset on that port (name the app in `serve:` with its agent_api_port)")
    return True, (f"{len(published)} published app(s), all of them served "
                  f"({len(served)} declared); {len(doc.get('agents') or {})} agent API(s) published, "
                  f"each one opened")


@check("DGO-32 · this office knows WHO it is — an identity file and DGO_OFFICE_ID")
def c_identity_seeded():
    """The same defect blocker 1 measured on vps1, one level in.

    A far office whose `/identity` volume is empty and whose `DGO_OFFICE_ID` is unset is an office that
    cannot answer `GET /api/link/catalog` at all: `home_office()` raises, no tile can be namespaced,
    and the link's own control door answers for `local`. Measured on vps1 before the fix: the volume
    was empty while this office had minted its keys. So the two facts a peer depends on are asserted
    where they can be read anywhere — inside the container, by the same module that needs them.

    The identity's stored LABEL is reported and not asserted: it is written when the keys are minted
    (`identity.py --label`), so an office that was renamed keeps the name it was born with, and the
    fingerprint — not the label — is what two sides compare.
    """
    raw = inside("dgo-extend",
                 "import json,os,identity;"
                 "d=identity.load() or {};"
                 "print('DGO='+json.dumps({'office': d.get('office') or '',"
                 "'fingerprint': d.get('fingerprint') or '',"
                 "'env': os.environ.get('DGO_OFFICE_ID') or ''}))")
    if not raw:
        return False, f"dgo-extend is not answering here ({LAST_INSIDE_ERR})"
    line = [l for l in raw.splitlines() if l.startswith("DGO=")]
    if not line:
        return False, f"the identity check printed nothing readable: {raw[:120]}"
    try:
        doc = json.loads(line[-1][4:])
    except ValueError:
        return False, f"the identity check is not a document: {line[-1][:120]}"
    if not doc.get("env"):
        return False, ("DGO_OFFICE_ID is unset in this office's own dgo-extend — this office answers "
                       "`local` to every peer")
    if not doc.get("office") or not doc.get("fingerprint"):
        return False, ("the identity volume is empty — `bbox dgo identity mint` on this office; the "
                       "office that dials it seeds it (`converge._remote_identity_seed`)")
    born = "" if doc["office"] == doc["env"] else f" (minted as {doc['office']!r})"
    return True, f"{doc['env']} · {doc['fingerprint']}{born}"


@check("DGO-32 · `bbox agent list` on the far office lists THIS office's sessions")
def c_agent_list():
    """What is proved here, and what only the far office can prove.

    `bbox agent --office <office> list` runs ON THE OTHER OFFICE: it resolves the provider from that
    office's own state/vault and speaks to this office's adapter over the tunnel. Nothing on THIS side
    can read that machine's terminal output, so the check measures the half that is here and names the
    command that finishes the proof — a green check that could not look is worse than an honest gap.
    Measured on vps1 (2026-10-01, contract §"acceptance 2"): the MacBook's sessions listed, with this
    office's own id as the `--office` argument.
    """
    doc = _app_get("/api/link")
    if doc is None:
        return False, f"dgo-extend is not answering here ({LAST_INSIDE_ERR})"
    office = str((doc.get("home") or {}).get("id") or "")
    served = sorted((doc.get("serve") or {}).keys())
    if not served or not office:
        return False, ("NOT BUILT — this office declares no agent app under `serve:`, so no other "
                       "office can be handed a credential for it")
    code, out = run(["./bbox", "agent", "list"], 90)
    if code != 0:
        return False, f"`bbox agent list` failed on this office: {out[:120]}"
    # `both` uses this office's apps too: a two-way link (what a pairing makes by default) was read
    # as "nobody uses this office" and the check called a served office NOT BUILT (hp-laptop,
    # 2026-10-05, paired both ways with the MacBook).
    peers = [i for i in ((_app_get("/api/link") or {}).get("items") or [])
             if (i or {}).get("direction") in ("use", "both") and i.get("declared")]
    if not peers:
        return False, ("NOT BUILT — no declared link says another office uses this one's apps, so "
                       "there is nothing to hand a credential to")
    return True, (f"this office serves {', '.join(served)} to {len(peers)} linked office(s); the "
                  f"other half is measured THERE: `bbox agent --office {office} list`")


def _app_get(path: str) -> dict | None:
    """One GET of dgo-extend's own API, through the engine (`inside`) — the door that works wherever
    bbox runs, on the owner's machine as in CI."""
    raw = inside("dgo-extend",
                 "import urllib.request;"
                 f"print(urllib.request.urlopen('http://127.0.0.1:8983{path}',timeout=20).read().decode())")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _manifest_alias(app_id: str) -> str:
    """The tile alias an app declares in its own manifest (`routing[].module.alias`)."""
    for base in ("apps", "platform-base"):
        p = ROOT / base / app_id / "app.json"
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for route in (doc.get("routing") or []):
            alias = ((route.get("module") or {}).get("alias") or "").strip()
            if alias:
                return alias
    return app_id


@check("DGO-30 · a sleeping remote says so in Hebrew, on the tile")
def c_sleeping():
    """The acceptance's second half. The signal is the shell's own fallback: a framed host that never
    renders is detected (`.localhost` nesting keeps the frame same-origin, which is what makes the
    detection possible at all) and replaced with a Hebrew notice that shows the tile's `desc`. So the
    property to hold is that every served tile CARRIES text naming its office — measured here, and
    true regardless of whether the remote is awake."""
    serve = _serve_module()
    cat = json.loads((ROOT / "platform-base/console/app.json").read_text(encoding="utf-8"))
    tiles = serve.module_entries([_synthetic_entry()], cat)
    if not tiles:
        return False, "a remote app produced no tile"
    d = tiles[0].get("desc") or ""
    shell = (ROOT / "platform-base/console/static/app.js").read_text(encoding="utf-8")
    fallback = "renderExternalNotice" in shell and "האפליקציה לא נטענה" in shell
    ok = "מקבוק" in d and fallback
    return ok, (f"tile text: {d[:60]!r} · the shell's Hebrew fallback card exists: {fallback}")


@check("DGO-37 · the catalog is a PROJECTION of the compiled registry, not a second list")
def c_catalog_module():
    code, out = run(["python3", str(ROOT / "apps/dgo-extend/catalog.py")], 120)
    return code == 0, (out.strip().splitlines()[-1] if out.strip() else "no output")


@check("DGO-37 · the published fixture IS what the module produces (remote-ui builds against it)")
def c_catalog_fixture():
    """`apps/dgo-extend/tests/fixtures/` is the contract remote-ui renders and remote-control tests
    against, so a fixture that has drifted from the code is worse than no fixture: it is a spec
    everybody codes to and nobody measures. Checked by REPRODUCING it — same registry, same office,
    same `now` — and comparing the bytes."""
    sys.path.insert(0, str(ROOT / "apps/dgo-extend"))
    import catalog
    base = ROOT / "apps/dgo-extend/tests/fixtures"
    reg = catalog.load_registry(base / "registry")
    if not reg.get("apps"):
        return False, "the fixture registry is missing or empty"
    built = catalog.build(reg, "macbook", {"he": "המקבוק", "en": "MacBook"},
                          commit="0123456789abcdef0123456789abcdef01234567", now=1759330000)
    published = json.loads((base / "catalog.macbook.json").read_text(encoding="utf-8"))
    if built != published:
        return False, ("the published catalog fixture has drifted from catalog.py — regenerate it "
                       "(remote-ui renders this file)")
    if catalog.validate(built, "macbook"):
        return False, f"the fixture does not validate: {catalog.validate(built, 'macbook')}"
    aliases = [a["alias"] for a in built["apps"]]
    return True, f"{len(aliases)} app(s) published: {', '.join(aliases)} — fixture reproduces byte-for-byte"


@check("DGO-37 · the projection writes the compiler's own input, and refuses to guess")
def c_projection_module():
    code, out = run(["python3", str(ROOT / "apps/dgo-extend/projection.py")], 120)
    return code == 0, (out.strip().splitlines()[-1] if out.strip() else "no output")


@check("DGO-37 · a ONE-WAY link's consuming office learns its peer from its own plan")
def c_plan_peers():
    """The office that only CONSUMES a link holds no declaration for the other end — it does not
    manage it, and it may not even reach it over SSH (a home office that dials out). Its own link
    PLAN, shipped to it by the link step, names the peer and every door, and that is the only place
    the fact exists there.

    Measured 2026-10-02: vps1's plan held `use` rules for macbook, its tunnel and its door were up,
    and its console showed no tile for that office's apps at all — `peers()` read declarations only,
    so nothing was ever pulled. This check is that sentence, mechanically.
    """
    import tempfile
    sys.path.insert(0, str(ROOT / "apps/dgo-extend"))
    import projection
    plan = {"office": "vps1", "slot": 2, "self": "10.79.2.2", "rules": [
        {"office": "macbook", "direction": "serve", "app": "door", "port": 9002,
         "target": "dgo-extend:8984"},
        {"office": "macbook", "direction": "use", "app": "door", "port": 9002,
         "target": "10.79.2.1:9002"}]}
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "link-proxy.json").write_text(json.dumps(plan), encoding="utf-8")
        seen = projection.plan_peers({"id": "vps1"}, d)
        pulled = [p["office"] for p in projection.peers({"id": "vps1"}, [], d)]
        own = projection.plan_peers({"id": "macbook"}, d)
    if seen != [{"office": "macbook", "address": "10.79.2.1"}]:
        return False, f"the plan's own `use` peer was not read: {seen}"
    if pulled != ["macbook"]:
        return False, f"the peer was not added to the pull list: {pulled}"
    if own:
        return False, "an office read ITSELF back as a peer"
    return True, "peers(no declaration) → macbook @ 10.79.2.1 · this office is not its own peer"


@check("DGO-37 · the whole chain: catalog → projection → registry → route")
def c_remote_chain():
    """The four hops the owner's model is, end to end, on the FIXTURE — no link, no second machine,
    no peer. Each hop is asserted at its own boundary, so a break names which one it is:

      catalog    the peer's registry → the catalog it publishes (fixtures/registry → fixtures/catalog)
      projection the catalog → the `remote:` block the consuming office declares
      compile    that block → a router on the nested host + a network alias for it
      registry   the same block → `remote.<office>.<alias>.json`, which other surfaces read

    What this CANNOT prove is that the two offices agree over a live tunnel; that is phase 4's gate,
    and the live checks at the end of this file say so rather than going green.
    """
    import tempfile
    sys.path.insert(0, str(ROOT / "apps/dgo-extend"))
    import catalog
    import projection
    serve = _serve_module()
    cat = json.loads((ROOT / "platform-base/console/app.json").read_text(encoding="utf-8"))
    problems = []

    # 1 — catalog: a peer's compiled registry becomes what it publishes.
    fixtures = ROOT / "apps/dgo-extend/tests/fixtures"
    published = catalog.build(catalog.load_registry(fixtures / "registry"), "macbook",
                              {"he": "המקבוק", "en": "MacBook"}, commit="cafe" * 10, now=1)
    if [a["alias"] for a in published["apps"]] != ["bina", "drive", "n8n"]:
        problems.append(f"the catalog must carry the peer's apps in order, got "
                        f"{[a['alias'] for a in published['apps']]}")
    if catalog.validate(published, "macbook"):
        problems.append(f"our own catalog does not validate: {catalog.validate(published)}")

    # 2 — projection: the consumer's home record turns it into the block layer 0 reads.
    home = {"id": "vps1", "tunnel": {"slot": 3}, "label": "vps1"}
    block = projection.state_block({"macbook": published}, home)
    if len(block) != 1 or block[0]["address"] != "10.79.3.2":
        problems.append(f"the block must address the PEER's end of the pair, got {block}")

    # 3 — compile: routers on `<alias>.<office>.console.*`, and an alias per app on the link proxy.
    entries, errs = serve.plan({"remote": block}, cat)
    if errs:
        problems.append(f"what the projection writes does not compile: {errs[0]}")
    routes = serve.render(entries, cat, domain="staging.example.co.il") or ""
    for alias in ("bina", "n8n", "drive"):
        if f"{alias}.macbook.console.staging.example.co.il" not in routes:
            problems.append(f"no router for the remote host of `{alias}`")
        if f"http://{alias}.macbook:" not in routes:
            problems.append(f"the router for `{alias}` does not point at the link proxy's alias")
    for alias in ("bina", "n8n", "drive"):
        if alias not in (serve.render_aliases(entries) or ""):
            problems.append(f"`{alias}.macbook` is routed but never aliased")
    if "10.79.3.2" in routes:
        problems.append("a route the edge serves must not carry the peer's tunnel address")

    # 4 — registry: the per-app record other surfaces read, written by the compiler itself.
    sys.path.insert(0, str(ROOT / "platform/manager"))
    import reconcile
    with tempfile.TemporaryDirectory() as tmp:
        reg = Path(tmp)
        reconcile.render_remote_entries(reg, entries)
        names = sorted(f.name for f in reg.glob("remote.*.json"))
        want = ["remote.macbook.bina.json", "remote.macbook.drive.json", "remote.macbook.n8n.json"]
        if names != want:
            problems.append(f"one registry record per remote app, got {names}")
        else:
            rec = json.loads((reg / "remote.macbook.bina.json").read_text(encoding="utf-8"))
            if (rec.get("remote") or {}).get("office") != "macbook" or \
               (rec.get("remote") or {}).get("link") != "macbook":
                problems.append(f"the record must name its office and its link, got {rec}")
            if (rec.get("module") or {}).get("kind") != "external" or \
               (rec.get("module") or {}).get("host") != "bina.macbook":
                problems.append(f"a remote app's module is external, framed on its own host: {rec}")
            if rec.get("id") != "bina.macbook":
                problems.append(f"the record's id is namespaced by office, got {rec.get('id')!r}")
        # A record whose app is no longer remote must not survive its entry.
        reconcile.render_remote_entries(reg, [])
        if list(reg.glob("remote.*.json")):
            problems.append("a stale remote record survived the entry that produced it")
    return (not problems), ("קטלוג → הקרנה → רישום → מסלול: 3 אפליקציות של macbook" if not problems
                            else "; ".join(problems))


def _remote_block_from_fixture():
    """The `remote:` block a consuming office projects from the published fixture catalog.

    The same four hops `c_remote_chain` walks, stopped one hop earlier: this returns the block the
    compiler and the CLI are both handed, so the two checks below measure the SAME declaration the
    chain check measures the rendering of.
    """
    sys.path.insert(0, str(ROOT / "apps/dgo-extend"))
    import catalog
    import projection
    published = catalog.build(catalog.load_registry(ROOT / "apps/dgo-extend/tests/fixtures/registry"),
                              "macbook", {"he": "המקבוק", "en": "MacBook"}, commit="cafe" * 10, now=1)
    return projection.state_block({"macbook": published}, {"id": "vps1", "tunnel": {"slot": 3},
                                                           "label": "vps1"})


def _mocked_state_file(tmp: Path, block: list) -> Path:
    """The REAL state file plus a mocked `remote:` block.

    The block itself is never written into the repo: `projection.py` is its one writer, and a test
    that wrote one by hand would leave this office declaring an office that does not exist — the
    exact failure the single-writer rule exists to prevent.
    """
    import yaml
    doc = yaml.safe_load((ROOT / "platform.state.yaml").read_text(encoding="utf-8")) or {}
    doc["remote"] = block
    doc.setdefault("apps", {})["bina-ds"] = {"enabled": True}      # the local twin of the alias
    path = tmp / "platform.state.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


@check("DGO-37 · `bbox apps list` shows a linked office's app in the SAME list, and keeps the twin")
def c_apps_list_remote():
    """The owner's rule, at the CLI: one list, an office per row, and an app installed in both
    offices appears TWICE.

    Run through `reconcile.main()` with the argv `bbox apps list` uses, against a state file that is
    the real one plus a mocked `remote:` block — so this is the command a person runs, not a helper
    standing in for it. Two rows sharing one alias is the assertion that matters: a CLI that merged
    them (or that printed the remote app under the bare alias) would give the console's shell two
    tiles with one id, which is one unreachable tile.
    """
    import contextlib
    import io
    import re
    import tempfile
    sys.path.insert(0, str(ROOT / "platform/manager"))
    import reconcile

    block = _remote_block_from_fixture()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        state_path = _mocked_state_file(tmp, block)
        saved = (reconcile.STATE, reconcile.PLANS, sys.argv)
        reconcile.STATE, reconcile.PLANS = state_path, tmp / "plans"
        try:
            table, js = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(table):
                sys.argv = ["reconcile.py", "plan"]
                rc_table = reconcile.main()
            with contextlib.redirect_stdout(js):
                sys.argv = ["reconcile.py", "plan", "--json"]
                rc_json = reconcile.main()
        finally:
            reconcile.STATE, reconcile.PLANS, sys.argv = saved

    problems = []
    if rc_table or rc_json:
        return False, f"`bbox apps list` exited {rc_table}/{rc_json}: {table.getvalue()[:120]}"
    rows = [re.split(r"\s{2,}", ln.strip()) for ln in table.getvalue().splitlines()
            if ln.strip() and not ln.startswith(("alias", "---", "plan", "  ", "apps"))]
    twins = [r for r in rows if r and r[0] in ("bina", "bina.macbook")]
    offices = {r[0]: r[2] for r in twins if len(r) > 2}
    if offices.get("bina") != "local":
        problems.append(f"the local row must be this office's, got {offices}")
    if offices.get("bina.macbook") != "macbook":
        problems.append(f"the remote row must carry the office it lives on, got {offices}")
    if len([r for r in twins if r[0] == "bina.macbook"]) != 1:
        problems.append(f"exactly one row per remote app of the office, got {twins}")
    try:
        doc = json.loads(js.getvalue())
    except ValueError:
        return False, f"`bbox apps list --json` is not a document: {js.getvalue()[:120]}"
    if not doc.get("remote") or doc["remote"][0].get("office") != "macbook":
        problems.append(f"--json must carry the linked offices, got {doc.get('remote')}")
    both = [r for r in doc.get("apps") or [] if r.get("alias") == "bina"]
    if len(both) != 2:
        problems.append(f"an alias installed here AND there is two rows, got {len(both)}")
    elif {r["office"] for r in both} != {"local", "macbook"}:
        problems.append(f"the two rows must differ by office, got {[r['office'] for r in both]}")
    else:
        remote_row = next(r for r in both if r["office"] == "macbook")
        if (remote_row.get("remote") or {}).get("link") != "macbook":
            problems.append(f"the remote row must carry its link record, got {remote_row.get('remote')}")
        if remote_row["id"] != "bina.macbook":
            problems.append(f"the row's id is office-namespaced, got {remote_row['id']!r}")
    return (not problems), (f"{len(rows)} row(s); bina here + bina.macbook there, and --json carries "
                            f"{len(doc.get('remote') or [])} office(s)" if not problems
                            else "; ".join(problems))


@check("DGO-32 · `bbox remote` resolves an app through the compiler's record and builds the alias URL")
def c_remote_cli():
    """The CLI half of the contract (§6–7), measured where it can be: the resolution and the URL.

    What is asserted is what a wrong answer would cost: the host is the ALIAS (`<alias>.<office>`),
    never the peer's tunnel address (which means nothing outside this office and would send a token
    to a name that is not the app); the two doors come from the port the SERVING office published;
    and a path carrying a host is refused, because a caller who can name the host can send the
    office's own credential anywhere.
    """
    import tempfile
    sys.path.insert(0, str(ROOT / "scripts"))
    sys.path.insert(0, str(ROOT / "platform/manager"))
    import reconcile
    import remote as remotecli
    serve = _serve_module()

    cat = json.loads((ROOT / "platform-base/console/app.json").read_text(encoding="utf-8"))
    entries, errs = serve.plan({"remote": _remote_block_from_fixture()}, cat)
    if errs:
        return False, f"the fixture block does not compile: {errs[0]}"
    problems = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        reg = tmp / ".generated/registry"
        reg.mkdir(parents=True)
        (tmp / "apps").mkdir()          # a checkout-shaped root: the CLI refuses a repo-less read
        reconcile.render_remote_entries(reg, entries)
        saved = remotecli.REPO
        remotecli.REPO = tmp
        try:
            ui = remotecli.resolve("macbook", "bina", False)
            api = remotecli.resolve("macbook", "bina", True)
        except remotecli.RemoteError as e:
            return False, f"the CLI cannot resolve a remote app the compiler routes: {e.message}"
        finally:
            remotecli.REPO = saved
    if ui["url"] != "http://bina.macbook:3080":
        problems.append(f"the UI door must be the network alias the compiler renders, got {ui['url']}")
    if api["url"] != "http://bina.macbook:3081":
        problems.append(f"the API door is the app's second port, got {api['url']}")
    if "10.79.3.2" in ui["url"]:
        problems.append("the peer's tunnel address is this office's private view of the peer — it "
                        "must never be what a call is addressed to")
    # TWO SOURCES, on purpose: the compiler's record carries the doors (it is what the routes were
    # rendered from), while the credential's NAME is published by the SERVING office in its catalog
    # (`api.auth`) — the only party that knows which instance opens its own app. So the record names
    # no instance, and the CLI asks the catalog; both halves are asserted here.
    if api["instances"]:
        problems.append(f"the registry record must not invent a credential name, got {api['instances']}")
    names = remotecli._auth_instances("bearer:vault:bina-ds", "macbook", "bina-ds")
    if names[0] != "bina-ds" or "dgo_link-serve-macbook-bina-ds-agent" not in names:
        problems.append(f"the catalog's name is tried first, then the converge conventions: {names}")
    saved_fetch = remotecli._fetch_link
    remotecli._fetch_link = lambda url, timeout: {"items": [
        {"office": "macbook", "apps": [{"alias": "bina", "app": "bina-ds",
                                        "api": {"port": 3081, "auth": "bearer:vault:bina-ds"}}]}]}
    try:
        from_catalog = remotecli._catalog_instances(
            {"office": "macbook", "alias": "bina", "app": "bina-ds"}, 5)
    finally:
        remotecli._fetch_link = saved_fetch
    if from_catalog[:1] != ["bina-ds"]:
        problems.append(f"the catalog's `api.auth` must be what a token is fetched by, got "
                        f"{from_catalog}")
    # A path is a path. Anything that names a host is refused before a token exists.
    sys.path.insert(0, str(ROOT / "scripts"))
    args = remotecli.build_parser().parse_args(["macbook", "bina", "http://evil.example/x"])
    os.environ[remotecli.ENV_RESOLVED] = json.dumps(ui)
    try:
        rc = remotecli.cmd_call(args)
    except remotecli.RemoteError as e:
        rc = e.code
    finally:
        os.environ.pop(remotecli.ENV_RESOLVED, None)
    if rc != remotecli.EXIT_USAGE:
        problems.append(f"a path that carries a host must be a usage refusal, got exit {rc}")
    return (not problems), ("http://bina.macbook:3080 | :3081, credential by catalog name, host in "
                            "a path refused" if not problems else "; ".join(problems))


@check("DGO-37 · `bbox remote` reads the LIVE link plane (or says which half is missing)")
def c_remote_live():
    """The listing, against whatever the office actually has: a gate that went green because it could
    not look would claim the owner can see another office's apps, which is the thing this lane is.

    `bbox remote` needs the link plane and nothing else — not the link, not the peer — so it is
    decided here on any machine that runs the office. A link plane that does not answer is reported
    as NOT BUILT with its own sentence, exactly like the live checks around it.
    """
    code, out = run(["./bbox", "remote", "--json"], 120)
    if code != 0:
        return False, (f"NOT BUILT (DGO-37) — `bbox remote` could not read the link plane: "
                       f"{(out.splitlines() or ['no output'])[-1][:140]}")
    try:
        doc = json.loads(out)
    except ValueError:
        return False, f"`bbox remote --json` is not a document: {out[:140]}"
    home = doc.get("home") or {}
    if not home.get("id"):
        return False, "the link plane answered without this office's own record"
    items = doc.get("offices") or []
    for item in items:
        if item.get("state") not in ("up", "down", "unknown"):
            return False, f"a linked office must carry its state, got {item.get('state')!r}"
    summary = ", ".join(f"{i.get('office')}={i.get('state')}({len(i.get('apps') or [])} apps)"
                        for i in items) or "no linked office"
    return True, f"home {home.get('id')} · {summary}"


PHASE3 = [c_serve_rules, c_serve_render, c_serve_tile, c_catalog_module, c_catalog_fixture,
          c_projection_module, c_remote_chain, c_apps_list_remote, c_remote_cli, c_remote_live,
          c_serve_identity_provider, c_serve_file, c_pairing, c_pair_contract, c_link_security,
          c_offer_public, c_live_tile,
          c_door_route, c_door_service, c_door_identity, c_door_waits, c_proxy_reload, c_link_listener,
          c_catalog_served, c_identity_seeded, c_agent_list, c_sleeping]

