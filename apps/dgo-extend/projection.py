"""dgo-extend.projection — the CONSUMING side: pull each peer's catalog, write `remote:` HERE.

The shape of the problem
------------------------
A linked office's apps must appear on this office's console, and layer 0 (which renders the routes,
the tiles and the network aliases) may read exactly ONE file: `platform.state.yaml`. It cannot read
this app's volume — office declarations and catalogs live here, deliberately, because "which offices
am I linked to" is not a fact of the machine's desired state but of a relationship.

So the relationship is PROJECTED onto the one file layer 0 can see. Every 60 s, on `link up` and on
demand, this module:

  1. reads the link plane (`converge.home_office()` + the declarations) — which peers exist, and in
     which direction the link carries;
  2. pulls each SERVING peer's catalog over the tunnel (`GET http://10.79.<slot>.2:8983/api/link/catalog`
     — the office's own compiled registry, projected by `catalog.py`), and stores it under
     `/data/remote/<office>.json` for the screens and the delivery plan;
  3. writes the `remote:` block of `platform.state.yaml` — the generalisation of the older `serve:`
     block, which is still READ as an alias of it for one release.

Why the state file is written through the control plane
-------------------------------------------------------
This container has no copy of the checkout, no SSH client and no engine socket, on purpose (see the
app's compose), so it cannot edit `platform.state.yaml` — and it should not: that file has ONE
writer, the compiler. The block is DECLARED to the control plane (`GET` / `PUT /api/remote` on
app-management, `read_state` / `write_state` below), which hands it to the compiler's own writer:
only a declaration that changed is written, and one the compiler cannot plan is refused with its
reasons, so a peer's catalog can never leave this office unable to compile.

It used to go through `computers`' `/exec` — a shell on the machine. An office with no door to its
own machine (hp-laptop runs no SSH server, by its owner's ruling) could then show nothing a linked
office gave it. When the control plane does not take the block, the pass keeps what it WANTED
(`desired`) and the machine can still declare it itself: `./bbox dgo project` (hooks/project).

What this module refuses to do
------------------------------
* It never falls back to the peer's `serve:` list. A peer that does not answer keeps the tiles of the
  LAST catalog it gave (the one on disk) and is reported as not answering beside them: "the office
  is asleep" is a state the console draws ON the tile, in Hebrew (contract §4), and a tile that left
  would say "the app is gone" — a different state. Until 2026-10-08 the block was built from one
  pass's answers alone, so with two peers the one that slept lost its tiles and with one peer it
  kept them (measured on the MacBook: hp-laptop's 14 tiles left at 11:54, and the card built for
  that state had two tiles to stand on). A peer that never gave a catalog shows nothing.
* It never touches the machine when the block would not change: the state file is committed by the
  owner and rendered by the compiler, and a write every 60 s would make `git status` useless for
  everybody else in this office.
* It never publishes a catalog whose `office` is not the office the link names (`catalog.parse`).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import catalog

#: How long a live fetch may take before the peer counts as unavailable. Short: this runs on a timer.
FETCH_TIMEOUT = 8.0
#: The block in `platform.state.yaml` this module owns. Layer 0 reads it (`platform/manager/serve.py`).
BLOCK = catalog.BLOCK
#: Where the fetched catalogs live (this app's own volume).
DEFAULT_DIR = "/data"


def state_block(catalogs: dict, home: dict, exclude: dict | None = None,
                own_address: str = "", peer_addresses: dict | None = None) -> list[dict]:
    """Fetched catalogs → the `remote:` entries the compiler validates. Pure.

    `home` is this office's own record, and `own_address` this office's own end of the pair as the
    machine's link record states it: the peer's tunnel address is DERIVED from that fact and never
    published by the peer, because a peer that could name its own address could point this office's
    edge anywhere. Which end is `.1` belongs to the PAIR (whoever renders it dials), so deriving it
    from a constant was wrong on the first real pair — see `peer_side`.

    TWO different exclusions, and they are not the same act:
      · the peer's own `serve.exclude` — an app it never published, so it is not here at all and this
        side has no way to know it exists;
      · `exclude[office]` — THIS office's "hide this over there from MY console". The app keeps
        running on the peer and the peer keeps publishing it (the catalog on disk still lists it, with
        `hidden: true` for the screens); what disappears is the tile, the router and the alias.
        Declaring it here and not on the peer is deliberate: hiding an app from one office's rail must
        not take it away from every other office that is linked to the same peer.
    """
    hide = {str(o): {str(a) for a in (v or [])} for o, v in (exclude or {}).items()}
    slot = int((home.get("tunnel") or {}).get("slot") or 0)
    if not slot:
        return []
    # Which end of the pair the peer holds: PER PEER when the caller knows it (one /24 per pair, so
    # two peers do not share an address), and otherwise derived from THIS office's own address in the
    # single-pair case (a fact of the pair — see peer_side). `own_address` is empty only before the
    # link's first record exists.
    address = f"10.79.{slot}.{peer_side(own_address)}"
    addresses = {str(k): str(v) for k, v in (peer_addresses or {}).items() if v}
    out = []
    for office, doc in sorted((catalogs or {}).items()):
        apps = []
        for app in (doc.get("apps") or []):
            if str(app.get("alias") or "").lower() in hide.get(office, set()):
                continue
            row = {
                "app": app.get("app") or app.get("alias"),
                "alias": app.get("alias"),
                "port": app.get("port"),
                "name": (app.get("title") or {}).get("he") or app.get("alias"),
                "name_en": (app.get("title") or {}).get("en") or "",
                "icon": app.get("icon") or "external",
                "group": app.get("group") or "מרוחק",
                "desc": app.get("desc") or "",
                "order": app.get("order", 900),
                "module": app.get("module") or {"kind": "embedded"},
                "health": app.get("health") or "/healthz",
            }
            if (app.get("api") or {}).get("port"):
                row["agent_api_port"] = app["api"]["port"]
            if app.get("host"):
                row["host"] = app["host"]
            if (app.get("identity") or {}).get("to"):
                row["identity"] = {"to": app["identity"]["to"]}
            apps.append(row)
        if not apps:
            continue
        entry = {"office": office,
                 "label": doc.get("label") or {"he": office, "en": office},
                 "link": office,
                 "address": addresses.get(office) or address,
                 "commit": doc.get("commit") or "",
                 "fetched": int(doc.get("generated_at") or time.time()),
                 "apps": apps}
        # The port the PEER's link door answers on (DGO-32): published by the office that owns the
        # door, never computed here. One listener per link, and the Host header picks the app behind
        # it — so every UI route of that office targets this port, and the apps' own ports stay in the
        # catalog only for the agent API (a CLI addresses a port, not a name).
        if isinstance(doc.get("link"), dict) and doc["link"].get("port"):
            entry["link_port"] = int(doc["link"]["port"])
        out.append(entry)
    return out


#: THE CONTROL PLANE — the one service that holds this office's checkout and its engine. What this
#: app wants declared (`remote:`) and applied is ASKED of it: the compiler there validates and
#: writes the block (`reconcile.set_remote`), and `apply` brings the link's sidecar in line.
#: Both used to be scripts this module carried and ran on "the machine that runs this office"
#: through `computers` — an SSH door. Two offices in a row had none (a Windows host has no sshd; a
#: MacBook's record of itself was stuck on a changed host key): the catalogs arrived, the screen
#: said "up, 9 apps", no tile ever appeared, and a person had to run `bbox dgo project`. The office
#: reaching its own state must not depend on a door to its own machine.
CONTROL_URL = os.environ.get("APPMGMT_URL", "http://app-management:8080").rstrip("/")
#: This app's id there — the app whose running services an apply brings in line.
SELF_APP = "dgo-extend"


def _fact(text: str, name: str) -> str:
    for line in (text or "").splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    return ""


#: This office's OWN address in the pair, from the link's record on the machine — a FACT, in the order
#: the records are trusted: the addressing this office's tunnel applier reads, then the copy the link
#: step ships into the checkout for the machine that runs `wg-quick` there.
ADDRESS_READER = r'''
python3 - <<'PY'
import json, re
self_addr = ""
try:
    self_addr = (json.load(open("/tunnel/addressing.json", encoding="utf-8")) or {}).get("self") or ""
except Exception:
    self_addr = ""
if not self_addr:
    for p in (".dgo/addressing.json", ".dgo/wg0.conf"):
        try:
            text = open(p, encoding="utf-8").read()
        except OSError:
            continue
        if p.endswith(".json"):
            try:
                self_addr = (json.loads(text) or {}).get("self") or ""
            except ValueError:
                self_addr = ""
        else:
            m = re.search(r"^\s*Address\s*=\s*([0-9]{1,3}(?:\.[0-9]{1,3}){3})", text, re.M)
            self_addr = m.group(1) if m else ""
        if self_addr:
            break
print("SELF=" + self_addr)
PY
'''


#: The own-address read is one SSH round trip, and `sync` runs every 60 s: cached here, re-read
#: when it ages out (a link that is re-addressed converges, so ten minutes is generous).
_OWN = {"at": 0.0, "value": ""}


def own_address_cached(cv, ttl: float = 600.0) -> str:
    """This office's own end of the pair, from the machine's link record (cached briefly)."""
    now = time.time()
    if _OWN["value"] and now - float(_OWN["at"] or 0) < ttl:
        return str(_OWN["value"])
    value = read_own_address(cv, cv.LOCAL_MACHINE, cv.HOME_REPO)
    if value:
        _OWN.update({"at": now, "value": value})
    return value


def read_own_address(cv, machine: str, repo: str, timeout: int = 30) -> str:
    """This office's own tunnel address. Empty when there is no record yet.

    From the tunnel volume THIS container mounts — the addressing the tunnel's applier reads, which
    is the fact itself. The machine is asked only when that file names no address: the far end of a
    link whose tunnel runs on its host keeps its record in the checkout there."""
    try:
        local = json.loads((Path(os.environ.get("DGO_TUNNEL_DIR", "/tunnel")) / "addressing.json")
                           .read_text(encoding="utf-8")) or {}
        if local.get("self"):
            return str(local["self"])
    except (OSError, ValueError, AttributeError):
        pass
    if not repo:
        return ""
    r = cv.exec_on(machine, f"cd {cv.q(repo)} && {ADDRESS_READER}", timeout)
    if r.get("code") != 0:
        return ""
    return _fact(r.get("stdout") or "", "SELF")


def peer_side(own_address: str) -> int:
    """Which end of the pair the PEER holds, given the end THIS office holds.

    `net.py` gives a pair one /24 and two ends, and which one is `.1` is decided by whoever renders the
    pair (the office that can dial) — not by who consumes. Measured on the first real pair: the MacBook
    dials and holds `10.79.2.1`, while vps1, the office that SHOWS its apps, holds `10.79.2.2`. The
    constant `.2` that used to sit here therefore pointed vps1 at ITSELF: the catalog pull would have
    called vps1's own dgo-extend, and every remote tile would have proxied to a port on the wrong
    machine. An office with no record yet keeps the old default, and the caller reports that it guessed.
    """
    return 1 if str(own_address).strip().endswith(".2") else 2


def read_state(cv) -> list[dict]:
    """The `remote:` block as the FILE has it — the only honest answer to "what is declared"."""
    try:
        doc = cv._http("GET", f"{CONTROL_URL}/api/remote", timeout=40)
    except (OSError, ValueError):
        return []
    block = doc.get("remote") if isinstance(doc, dict) else None
    return block if isinstance(block, list) else []


def write_state(cv, block: list[dict]) -> dict:
    """Declare the block. Idempotent: the compiler writes only a declaration that changed, and
    refuses — with its reasons — one it could not plan, so a peer's catalog can never leave this
    office unable to compile."""
    apps = sum(len(e.get("apps") or []) for e in block)
    try:
        r = cv._http("PUT", f"{CONTROL_URL}/api/remote", {"remote": block}, timeout=60)
    except (OSError, ValueError) as e:
        return {"written": False, "apps": apps,
                "error": f"the control plane did not answer ({type(e).__name__})"}
    if r.get("_status"):
        return {"written": False, "apps": apps, "error": str(r.get("error") or r["_status"])[-400:],
                "refused": list(r.get("refused") or [])}
    return {"written": bool(r.get("written")), "apps": apps}


#: How often a projection-driven apply may run. A link that flaps (a laptop closing, a tunnel
#: re-dialing) must not become a loop that recreates the edge's containers every minute.
APPLY_MIN_SECONDS = int(os.environ.get("DGO_LINK_APPLY_SECONDS", "600"))
APPLY_STAMP = "link-apply.json"


def _rendered(block: list[dict]) -> dict[tuple[str, str], str]:
    """`(office, alias)` → everything the compiler renders for that app: its own row, and the two
    facts of its office's pair that every route of that office is built from."""
    out = {}
    for e in block or []:
        pair = [e.get("address"), e.get("link_port")]
        for a in (e.get("apps") or []):
            out[(str(e.get("office") or ""), str(a.get("alias") or ""))] = \
                json.dumps([a, pair], sort_keys=True, ensure_ascii=False)
    return out


def _last_apply(base: str) -> int:
    try:
        return int(json.loads((Path(base) / APPLY_STAMP).read_text(encoding="utf-8")).get("at") or 0)
    except (OSError, ValueError, AttributeError):
        return 0


def apply_new_remote_apps(cv, home: dict, before: list[dict], after: list[dict],
                          base: str = DEFAULT_DIR, timeout: int = 420) -> dict:
    """Turn a NEW remote app into a route and a tile, instead of waiting for someone to run `bbox run`.

    Measured twice on 2026-10-02, from both ends: a peer published an app, the projection wrote it
    into `platform.state.yaml`, its catalog grew — and the console showed nothing at all until a
    converge was run by hand. The block is the compiler's INPUT; the compiler, the edge's file and
    the link's network aliases are what make it visible, and this is that step.

    It is one request to the control plane (`POST /api/apps/<this app>/apply`): recompile, let
    compose recreate the link's sidecar with its new aliases, and make sign-in serve the new host —
    so a brand-new remote host is served by the identity layer rather than answering 404 from it.

    Runs when the block GAINED an app or CHANGED one it had — a port that moved, a door, an address
    (measured 2026-10-05 on the MacBook: the plan moved its listener for vps1's agent to another
    port, the block said so, nothing rendered, and the CLI went on dialling the old port from a
    stale registry record). Never because an app went AWAY: that is a tile that lingers until the
    next converge, a far better failure than an unattended loop restarting the office's edge every
    time a laptop sleeps. And at most once per `APPLY_MIN_SECONDS`.
    """
    was, now = _rendered(before), _rendered(after)
    gained = sorted(k for k, row in now.items() if was.get(k) != row)
    if not gained:
        return {"ran": False, "reason": "no new or changed remote app"}
    since = int(time.time()) - _last_apply(base)
    if since < APPLY_MIN_SECONDS:
        return {"ran": False, "reason": f"applied {since}s ago", "pending": [f"{o}/{a}" for o, a in gained]}
    return apply_now(cv, [f"{o}/{a}" for o, a in gained], base, timeout)


def apply_now(cv, new: list[str], base: str = DEFAULT_DIR, timeout: int = 420) -> dict:
    """The compile itself — that one request to the control plane — and its stamp.

    For the pass above, and for the ONE act that compiles an app going away: an unpairing. That is
    a person's act, not a laptop asleep — and without it the office's tiles and routes stayed on the
    console until the next `bbox run` (2026-10-08, hp-laptop: sixteen tiles of vps1 and 249 lines of
    the edge's file, half an hour after the pair was removed)."""
    try:
        r = cv._http("POST", f"{CONTROL_URL}/api/apps/{SELF_APP}/apply", {}, timeout=timeout)
    except (OSError, ValueError) as e:
        r = {"error": f"the control plane did not answer ({type(e).__name__})"}
    report = {"ran": True, "at": int(time.time()), "new": new,
              "ok": bool(r.get("ok")), "tail": str(r.get("error") or "")[-400:]}
    try:
        (Path(base) / APPLY_STAMP).write_text(json.dumps(report, ensure_ascii=False),
                                              encoding="utf-8")
    except OSError:
        pass
    return report


# ── the pull ─────────────────────────────────────────────────────────────────────────────────────
def plan_peers(home: dict, base: str = "") -> list[dict]:
    """The peers this office's own LINK PLAN names — the links shipped to it, not declarations.

    A declaration is how the office that DRIVES a link describes it, and it lives there; the office
    that only CONSUMES has none — it does not manage the other office, and it may not even be able to
    reach it over SSH (the home office behind NAT, which dials out). Yet the plan the link step
    rendered for it names every peer and every door: `use` rules carry the peer's own tunnel address.
    Reading that file is what makes the consuming side of a one-way link exist.

    Measured 2026-10-02: vps1's plan held `use` rules for `macbook` while its console showed no tile
    for that office's apps — the tunnel, the door and the delivery were all fine, and `peers()` only
    ever looked at declarations, so nothing was ever pulled.

    Returns `[{office, address, slot, control, door}]`: the peer's end of the pair (empty when the plan
    does not state one), the pair's slot, the port OUR OWN listener for that peer's catalog answers on
    (`linkproxy.control_port(slot)` — one per pair, which is why it is read from the plan instead of
    assumed), and `door` — the port OUR OWN door for that pair listens on (`linkproxy.door_port`),
    which is what every UI route of that office has to target here (see `apply_plan`).
    """
    import linkproxy
    directory = base or os.environ.get("DGO_TUNNEL_DIR", "/tunnel")
    try:
        doc = json.loads((Path(directory) / "link-proxy.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    mine = str(home.get("id") or "")
    out: dict[str, dict] = {}
    for rule in doc.get("rules") or []:
        if not isinstance(rule, dict) or str(rule.get("direction") or "") != "use":
            continue
        oid = str(rule.get("office") or "").strip()
        if not oid or oid == mine:
            continue
        entry = out.setdefault(oid, {"office": oid, "address": "", "agents": {},
                                     "slot": int(rule.get("slot") or 0), "control": 0, "door": 0})
        if not entry["slot"]:
            entry["slot"] = int(rule.get("slot") or 0)
        if str(rule.get("app") or "") == linkproxy.SELF_APP and rule.get("port"):
            entry["control"] = int(rule["port"])
        if str(rule.get("kind") or "") == "door" and rule.get("port"):
            entry["door"] = int(rule["port"])
        if str(rule.get("kind") or "") == "agent" and rule.get("port"):
            entry["agents"][str(rule.get("app") or "")] = int(rule["port"])
        target = str(rule.get("target") or "")
        host = target.split(":", 1)[0] if target else ""
        if host and not entry["address"]:
            entry["address"] = host
    return [out[k] for k in sorted(out)]


def own_plan(home: dict, base: str = "") -> dict:
    """This office's own link plan, by peer — from the TUNNEL volume, where the plan is rendered.

    `sync` used to read it from `base`, which is this app's STATE directory (`/data`): the file is not
    there, so the plan was always empty and both facts it carries fell back to guesses — the peer's
    address derived from the HOME slot, and the door port taken from what the peer published. Both
    guesses are right for an office with ONE pair whose slot is its own, and wrong for a second pair
    (measured 2026-10-05 on hp-laptop, home slot 1, paired with the MacBook on slot 4: the block said
    `address: 10.79.1.2, link_port: 9002` while the pair is `10.79.4.2` and its door here is 9004).
    `base` is still tried second, for a rig that renders a plan beside its state.
    """
    rows = plan_peers(home) or (plan_peers(home, base) if base else [])
    return {p["office"]: p for p in rows}


def apply_plan(block: list[dict], plan: dict) -> list[dict]:
    """Write into each entry the two facts only THIS office's own plan knows about that pair.

    * `address` — the peer's end of the pair's /24.
    * `link_port` — OUR door for that pair. Every UI route of that office targets
      `http://<alias>.<office>:<link_port>` on the link proxy, so the port has to be one the proxy
      listens on HERE. The peer publishes ITS door (`catalog.link.port`), and with one pair per office
      that is the same number — the door is `9000 + slot` on both ends. With several pairs a peer
      publishes a single number (the pair it considers primary), and for every other pair that number
      is a port nothing listens on here: a tile that answers 502 over a healthy tunnel.
    * `agent_api_port` — OUR listener for that app's agent API. It is the port the peer published
      unless another peer published the same number, in which case the plan moved this one
      (`linkproxy.AGENT_BASE`) — and `http://<alias>.<office>:<the published port>` would then be
      answered by the OTHER office's agent, since every alias here is one address.
    A peer the plan does not name (an older plan, a link this office was only given) keeps what the
    catalog said.
    """
    for entry in block:
        mine = (plan or {}).get(entry.get("office")) or {}
        if mine.get("address"):
            entry["address"] = str(mine["address"])
        if mine.get("door"):
            entry["link_port"] = int(mine["door"])
        for app in entry.get("apps") or []:
            ours = (mine.get("agents") or {}).get(str(app.get("app") or ""))
            if ours and app.get("agent_api_port"):
                app["agent_api_port"] = int(ours)
    return block


def peers(home: dict, offices: list[dict], plan_base: str = "") -> list[dict]:
    """The offices this one CONSUMES from: a declared link whose direction is `use` here.

    Direction, not intent: `links: [{office: vps1, direction: use}]` on the PEER's record means the
    peer uses THIS office's apps, so this office's link to it is the reverse (`linkproxy.mirror`).
    Only the peer whose apps we consume has a catalog we need, and asking a peer that consumes US
    would collect a list this office has no door to reach.

    Two sources, and the second is what closes the one-way case: the declarations this office holds
    (it drives those links) and the peers its own plan names (`plan_peers` — the links it was given).
    A peer in both is one, not two.
    """
    import linkproxy
    out = []
    for office in offices:
        oid = str(office.get("id") or "")
        if not oid or oid == home.get("id"):
            continue
        link = linkproxy._link_of(office, str(home.get("id") or "local"))
        if not link:
            continue
        # `both` consumes too — a bidirectional link is one whose peer's apps this office shows.
        if linkproxy.mirror(link.get("direction")) not in ("use", "both"):
            continue
        out.append({"office": oid, "machine": office.get("machine"),
                    "domain": office.get("domain")})
    seen = {p["office"] for p in out}
    for p in plan_peers(home, plan_base):
        if p["office"] not in seen:
            out.append({"office": p["office"], "machine": "", "domain": "",
                        "address": p.get("address") or ""})
            seen.add(p["office"])
    return out


def catalog_url(home: dict = None, host: str = "", port: int = catalog.CATALOG_PORT) -> str:
    """Where a peer's catalog answers FROM HERE: the link proxy, on this app's own port.

    NOT the peer's tunnel address, and that is the correction rather than a preference: the tunnel
    address exists only inside the tunnel container's namespace, and this app runs beside it on the
    office network with no route to it. The proxy is the one process that listens here and forwards
    into the tunnel, and this office's `use` rule for the peer's catalog (`linkproxy.build`) is what
    puts a listener there — before either office knows anything about the other's apps.

    Never the peer's public domain either: the catalog is part of the LINK (`catalog.with_control`),
    and a peer that must be reachable over the internet for this office to list its apps is not a
    link, it is a second front door.
    """
    host = host or os.environ.get("DGO_LINK_PROXY_HOST", "dgo-net")
    return f"http://{host}:{int(port)}/api/link/catalog"


def fetch(cv, url: str, expect_office: str = "", timeout: float = FETCH_TIMEOUT) -> dict:
    """One peer's catalog, validated. Failures are states with a sentence, never exceptions."""
    try:
        doc = cv._http("GET", url, timeout=timeout)
    except Exception as e:                                   # noqa: BLE001 — a sleeping peer
        return {"error": f"{type(e).__name__}", "url": url}
    # A NON-2xx IS "SHE DID NOT ANSWER", NOT A BAD CATALOG. This office's own link proxy answers 502
    # with an empty body while the tunnel carries nothing (`cv._http` folds that into `_status`), and
    # reading it as a payload ended in „catalog.office None אינו מזהה לשכה תקין” — a sentence about
    # the SHAPE of a document, for a peer that never spoke, printed on the tooltip of a pair whose
    # tunnel had not completed a single handshake (measured 2026-10-12, lnk-032).
    status = doc.get("_status") if isinstance(doc, dict) else None
    if status is not None and not 200 <= int(status) < 300:
        return {"error": f"הלשכה האחרת לא ענתה (HTTP {int(status)})", "url": url,
                "status": int(status)}
    try:
        cat = catalog.parse(doc, expect_office)
    except catalog.CatalogError as e:
        return {"error": str(e), "url": url}
    return {"catalog": cat}


def projected(pulled: dict, stored: dict, failed) -> dict:
    """The catalogs one pass projects: what each peer answered NOW, and for a peer that did not
    answer, the catalog it gave LAST. Pure.

    Its tiles stay; the status written beside the block is what says the office is not answering,
    and the console draws that on the tile. A stored catalog with no failure of this pass behind it
    adds nothing — an office that answered is taken at its word, app that left included."""
    return {**{o: stored[o] for o in failed if o in stored}, **pulled}


#: An office that has only just gone silent is asked again within seconds, for this many passes;
#: until they are spent its silence is not yet a verdict (`retried`).
QUICK_RETRIES = 5


def silent_passes(before: dict, errors) -> dict:
    """Per office, the passes in a row it has not answered: one more for each office silent in this
    pass, and no entry for one that answered. Pure."""
    return {o: before.get(o, 0) + 1 for o in errors or ()}


def retried(silent: dict, office: str) -> bool:
    """Is this office inside its quick retries — silent, and not for long enough to say so?"""
    return 0 < silent.get(office, 0) <= QUICK_RETRIES


def sync(cv, base: str = DEFAULT_DIR, replan=None) -> dict:
    """One full pass: pull every peer, store, project onto `platform.state.yaml`. Never raises.

    `replan` renders the delivery plan (the app's `render_link_proxy`). It is called HERE, between
    storing the catalogs and writing the block, because the block states ports only the plan decides
    — and a block written from the plan of the pass before is a minute of a tile pointing at a
    listener that has moved.

    The order matters and is the point: the catalogs are stored FIRST, so the screens and the
    delivery plan can answer with what was last seen even when the state file cannot be written
    (a read-only checkout, a machine that is not answering), and the projection is what the compiler
    reads. A peer that fails is reported per office — never as a silent absence, because "no apps"
    and "the peer did not answer" are different states and the console says which.
    """
    import linkproxy
    home = cv.home_office()
    offices = [o for o in cv.declarations() if o.get("id") != home.get("id")]
    plan = own_plan(home, base)
    hidden = load_exclude(base)
    pulled, errors = {}, {}
    for peer in peers(home, offices):
        oid = peer["office"]
        # ONE LISTENER PER PAIR, so the URL is per PEER: `catalog_url` with the pair's own control port
        # (`plan_peers` read it off the plan). Two consuming pairs on one port is the collision that
        # used to refuse the whole delivery plan.
        rec = next((o for o in offices if o.get("id") == oid), None)
        slot = int(((rec or {}).get("tunnel") or {}).get("slot")
                   or (plan.get(oid) or {}).get("slot") or 0)
        control = int((plan.get(oid) or {}).get("control") or 0) \
            or (linkproxy.control_port(slot) if slot else 0)
        url = catalog_url(home, port=control) if control else ""
        if not url:
            errors[oid] = "אין slot מוצהר לזוג הזה — אין כתובת מנהרה לפנות אליה"
            continue
        got = fetch(cv, url, oid)
        if got.get("catalog"):
            pulled[peer["office"]] = got["catalog"]
            catalog.store(base, got["catalog"])
        else:
            errors[peer["office"]] = got.get("error") or "לא התקבל קטלוג"
    proxy = None
    if replan is not None:
        try:
            proxy = replan()
        except Exception as e:                               # noqa: BLE001 — a refused plan is a state
            proxy = {"refused": f"{type(e).__name__}: {e}"}
        plan = own_plan(home, base)
    # The peer's end of the pair comes from THIS office's own record (see peer_side): the pair's
    # sides are decided by whoever renders it, and a constant here pointed vps1 at itself.
    # The peer's address, per peer: the plan's own answer for that pair, then this office's record of
    # it. One /24 per pair means one address per peer — a single derived address pointed every remote
    # tile at the same office.
    peer_addresses = {oid: p.get("address") or "" for oid, p in plan.items()}
    for p in peers(home, offices):
        peer_addresses.setdefault(p["office"], p.get("address") or "")
    # A peer that did not answer is projected from the LAST catalog it gave (`projected`); the status
    # below is what says it is not answering. Only this office's peers count: a file left on disk by
    # an office that is no longer one is not a reason for a tile.
    mine = peers(home, offices)
    stored = {o: d for o, d in catalog.load_all(base).items() if o in {p["office"] for p in mine}}
    block = state_block(projected(pulled, stored, errors), home, hidden,
                        own_address=own_address_cached(cv), peer_addresses=peer_addresses)
    # The peer's tunnel address comes from the PLAN when the plan states it: `state_block` derives it
    # from THIS office's pair slot, and on the consuming side of a one-way link that slot is the
    # peer's (vps1 holds `slot: 1` as its own name while the pair is `10.79.2.0/24`), so the derived
    # address was `10.79.1.x` — a wrong value nothing routes by (the alias is what routes) and every
    # screen would print.
    for entry in block:
        if peer_addresses.get(entry.get("office")):
            entry["address"] = peer_addresses[entry["office"]]
    # ...and OUR door for each pair, for the same reason (see apply_plan): the plan is the one place
    # that knows which port this office's proxy listens on for that peer.
    apply_plan(block, plan)
    status = {p["office"]: {"ok": p["office"] in pulled,
                            "at": int(time.time()),
                            "error": errors.get(p["office"], "")} for p in mine}
    save_status(base, status)
    have = read_state(cv)
    written = {"written": False}
    applied = {"ran": False, "reason": "nothing changed"}
    if not block and not errors:
        written = write_state(cv, [])
    elif block:
        written = write_state(cv, block)
    if written.get("written"):
        applied = apply_new_remote_apps(cv, home, have, block, base)
    return {"at": int(time.time()), "home": home.get("id"),
            "url": catalog_url(home, port=int((plan.get(mine[0]["office"]) or {}).get("control") or 0))
                   if mine else "",
            "applied": applied,
            "peers": [p["office"] for p in mine],
            "pulled": sorted(pulled), "stored": sorted(stored), "errors": errors,
            "hidden": hidden,
            "block": [{"office": e["office"], "apps": [a["alias"] for a in e["apps"]]} for e in block],
            # The block this pass WANTS declared, whole — beside what it managed to write. When the
            # control plane did not take it (`state.error`), the machine itself still can:
            # `bbox dgo project` (hooks/project) hands this to the compiler's own writer.
            "desired": block,
            "proxy": proxy,
            "state": written}


# ── this office's own "hide it here" ─────────────────────────────────────────────────────────────
# The app manager's show/hide switch writes HERE, in this office's own volume, and not on the peer:
# hiding an app from one office's rail must not take it away from every other office linked to the
# same peer, and the peer's own `serve.exclude` is a different act (it never publishes the app).
# The catalog on disk is untouched, so the screens can still list the app as `hidden` — a switch whose
# effect nobody can see is a switch nobody trusts.
EXCLUDE_FILE = "exclude.json"
STATUS_FILE = "remote-status.json"


def _state_path(base: str | Path, name: str) -> Path:
    return Path(base) / name


def load_exclude(base: str | Path = DEFAULT_DIR) -> dict:
    """`{office: [alias…]}` — what this office does not show. An unreadable file hides nothing."""
    try:
        doc = json.loads(_state_path(base, EXCLUDE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict):
        return {}
    return {str(o): sorted({str(a) for a in (v or [])}) for o, v in doc.items() if v}


def set_exclude(base: str | Path, office: str, alias: str, hidden: bool) -> dict:
    """Turn one app of one office on/off on THIS console. Returns the whole map, written."""
    office, alias = str(office).strip().lower(), str(alias).strip().lower()
    if not catalog.OFFICE_RE.match(office):
        raise catalog.CatalogError(f"office {office!r} אינו מזהה לשכה תקין")
    if not catalog.ALIAS_RE.match(alias):
        raise catalog.CatalogError(f"alias {alias!r} אינו כינוי תקין")
    doc = load_exclude(base)
    current = set(doc.get(office) or [])
    current.add(alias) if hidden else current.discard(alias)
    if current:
        doc[office] = sorted(current)
    else:
        doc.pop(office, None)
    path = _state_path(base, EXCLUDE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return doc


def load_status(base: str | Path = DEFAULT_DIR) -> dict:
    """`{office: {ok, at, error}}` from the last pass — what the console reads for "up/down".

    A file and not this process's memory: a restarted container must be able to say "vps1 answered
    four minutes ago" instead of "unknown", and an office that never answered must not look like one
    that answered with nothing.
    """
    try:
        doc = json.loads(_state_path(base, STATUS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def save_status(base: str | Path, status: dict) -> None:
    path = _state_path(base, STATUS_FILE)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def selftest() -> list[str]:
    """Pure checks of the projection's own decisions: addresses, exclusions, and what a failure
    means. No tunnel, no machine, no peer."""
    problems: list[str] = []
    home = {"id": "vps1", "tunnel": {"slot": 4}, "serve": {}}
    mac = {"office": "macbook", "label": {"he": "המקבוק", "en": "MacBook"}, "commit": "abc",
           "generated_at": 111,
           "apps": [{"alias": "bina", "app": "bina-ds", "title": {"he": "בינה ודעת", "en": "Bina"},
                     "port": 3080, "api": {"port": 3081, "auth": "bearer:vault:bina-ds"},
                     "module": {"kind": "embedded", "path": "/a/bina/"}, "host": "bina.localhost",
                     "identity": {"to": "owner@local"}, "order": 1, "icon": "bot", "group": "ראשי",
                     "desc": "הסוכן", "health": "/healthz"}]}
    block = state_block({"macbook": mac}, home)
    if len(block) != 1:
        problems.append(f"one peer with one app is one entry, got {block}")
    entry = block[0]
    if entry["address"] != "10.79.4.2":
        problems.append(f"the peer's address is DERIVED from the pair's slot, got {entry['address']}")
    if entry["label"]["en"] != "MacBook" or entry["link"] != "macbook":
        problems.append(f"the entry carries the peer's label and link: {entry}")
    app = entry["apps"][0]
    if app["agent_api_port"] != 3081 or app["host"] != "bina.localhost":
        problems.append(f"both doors and the authority must be projected, got {app}")
    if app.get("identity") != {"to": "owner@local"}:
        problems.append(f"the identity mapping crosses the link with the app, got {app}")
    if state_block({}, home) or state_block({"macbook": mac}, {"id": "vps1"}):
        problems.append("no peer, or no slot, must project NOTHING rather than guess an address")
    # Hiding is THIS office's act, and it is not the peer's: the app disappears from the block (no
    # tile, no router, no alias) while the catalog on disk still lists it, so the switch's effect is
    # visible both ways — the screens can say `hidden`, and the peer keeps running it.
    if state_block({"macbook": mac}, home, {"macbook": ["bina"]}):
        problems.append("a hidden app must not be projected")
    if len(state_block({"macbook": mac}, home, {"vps9": ["bina"]})) != 1:
        problems.append("hiding an app on ANOTHER office must not hide this one")
    # A PEER THAT DID NOT ANSWER keeps what it gave last; one that answered is taken at its word; a
    # catalog on disk with no failure of this pass behind it adds nothing.
    old = dict(mac, generated_at=1)
    if projected({}, {"macbook": old}, {"macbook": "timeout"}) != {"macbook": old}:
        problems.append("a peer that did not answer must keep the catalog it gave last")
    if projected({"vps9": mac}, {"macbook": old, "vps9": old}, {"macbook": "timeout"}) != {"macbook": old, "vps9": mac}:
        problems.append("with two peers, the one that answered is new and the one that did not keeps its last")
    if projected({"macbook": mac}, {"macbook": old, "vps9": old}, {}) != {"macbook": mac}:
        problems.append("an answer replaces the stored catalog, and a stored one with no failure adds nothing")
    if projected({}, {}, {"macbook": "timeout"}):
        problems.append("a peer that never gave a catalog shows nothing")
    # AN OFFICE THAT HAS ONLY JUST GONE SILENT is counted by itself, is being retried for
    # QUICK_RETRIES passes and no longer, and starts over when it answers — whoever else is silent.
    n: dict = {}
    for _ in range(QUICK_RETRIES):
        n = silent_passes(n, {"macbook": "timeout"})
    if n != {"macbook": QUICK_RETRIES} or not retried(n, "macbook") or retried(n, "vps9"):
        problems.append("an office silent for QUICK_RETRIES passes is still being retried, and only it")
    if retried(silent_passes(n, {"macbook": "timeout"}), "macbook"):
        problems.append("one silent pass more and the silence is a verdict")
    if silent_passes(n, {"vps9": "refused"}) != {"vps9": 1} or silent_passes(n, {}):
        problems.append("an office that answered starts over, whoever else is silent")
    # A SECOND PAIR: this office's own plan names the peer's address and OUR door for that pair, and
    # both replace what a single-pair office could get away with guessing.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "link-proxy.json").write_text(json.dumps({"rules": [
            {"office": "macbook", "direction": "use", "app": "door", "kind": "door", "slot": 4,
             "port": 9004, "target": "10.79.4.2:9004"},
            {"office": "macbook", "direction": "use", "app": "dgo-extend", "kind": "control", "slot": 4,
             "port": 9404, "target": "10.79.4.2:8983"},
            {"office": "vps9", "direction": "serve", "app": "door", "kind": "door", "slot": 2,
             "port": 9002, "target": "10.79.2.1:9002"}]}), encoding="utf-8")
        plan = {p["office"]: p for p in plan_peers({"id": "hp-laptop"}, tmp)}
    mine = plan.get("macbook") or {}
    if mine.get("door") != 9004 or mine.get("control") != 9404 or mine.get("address") != "10.79.4.2" \
            or "vps9" in plan:
        problems.append(f"the plan answers, per consumed peer, its address, our catalog port and OUR door: {plan}")
    second = state_block({"macbook": dict(mac, link={"port": 9002})}, {"id": "hp-laptop", "tunnel": {"slot": 1}})
    if second[0]["address"] != "10.79.1.2" or second[0].get("link_port") != 9002:
        problems.append(f"without a plan the entry holds the single-pair guesses: {second[0]}")
    apply_plan(second, plan)
    if second[0]["address"] != "10.79.4.2" or second[0]["link_port"] != 9004:
        problems.append(f"the plan's own address and door replace the guesses: {second[0]['address']} {second[0].get('link_port')}")
    untouched = apply_plan(state_block({"macbook": dict(mac, link={"port": 9002})}, home), {})
    if untouched[0].get("link_port") != 9002:
        problems.append("a peer the plan does not name keeps the door its catalog published")
    # OUR listener for a peer's agent API is the plan's fact too: it is the peer's own port until a
    # second peer publishes the same number, and then the plan moves it — the block must say where,
    # because `<alias>.<office>:<published port>` is by then answered by the OTHER office's agent.
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "link-proxy.json").write_text(json.dumps({"rules": [
            {"office": "macbook", "direction": "use", "app": "bina-ds", "kind": "agent", "slot": 4,
             "port": 10064, "published": 3081, "target": "10.79.4.2:3081"},
            {"office": "vps1", "direction": "use", "app": "bina-ds", "kind": "agent", "slot": 2,
             "port": 3081, "published": 3081, "target": "10.79.2.2:3081"}]}), encoding="utf-8")
        moved = {p["office"]: p for p in plan_peers({"id": "hp-laptop"}, tmp)}
    both = apply_plan(state_block({"macbook": mac, "vps1": dict(mac, office="vps1")}, home), moved)
    dial = {e["office"]: e["apps"][0]["agent_api_port"] for e in both}
    if dial != {"macbook": 10064, "vps1": 3081}:
        problems.append(f"the block names OUR listener for each office's agent API, got {dial}")
    if apply_plan(state_block({"macbook": mac}, home), plan)[0]["apps"][0]["agent_api_port"] != 3081:
        problems.append("a plan that names no agent listener leaves the published port alone")
    # THE CONTROL PLANE IS HOW THIS OFFICE REACHES ITS OWN STATE — never a door to its machine. A
    # stand-in for it records what it was asked, so the three calls are checked for what they send.
    class Plane:
        def __init__(self, answers):
            self.answers, self.asked = dict(answers), []

        def _http(self, method, url, body=None, timeout=30):
            self.asked.append((method, url.replace(CONTROL_URL, ""), body))
            return self.answers.get((method, url.replace(CONTROL_URL, "")), {})

        def exec_on(self, *_a, **_k):
            raise AssertionError("the projection asked for a shell on the machine")

    one = state_block({"macbook": mac}, home)
    plane = Plane({("GET", "/api/remote"): {"remote": one},
                   ("PUT", "/api/remote"): {"ok": True, "written": True, "apps": 1, "offices": 1}})
    if read_state(plane) != one or write_state(plane, one) != {"written": True, "apps": 1}:
        problems.append(f"the block is read from and written through the control plane: {plane.asked}")
    if plane.asked[-1] != ("PUT", "/api/remote", {"remote": one}):
        problems.append(f"the WHOLE block is what is sent, got {plane.asked[-1]}")
    refused = Plane({("PUT", "/api/remote"): {"_status": 422, "error": "the compiler refuses this block",
                                              "refused": ["remote[0].office is not an office id"]}})
    got = write_state(refused, one)
    if got.get("written") or not got.get("refused"):
        problems.append(f"a refused block is reported with its reasons, never as written: {got}")
    # ...and WHEN the office is brought in line: an app that is new, or one whose row changed (a
    # port that moved) — never because one went away, and never when nothing changed.
    moved_port = [dict(one[0], apps=[dict(one[0]["apps"][0], agent_api_port=10064)])]
    with tempfile.TemporaryDirectory() as tmp:
        for label, before, after, runs in (("a new app", [], one, True), ("a port that moved", one, moved_port, True),
                                           ("an app that went away", one, [], False), ("nothing", one, one, False)):
            (Path(tmp) / APPLY_STAMP).unlink(missing_ok=True)
            plane = Plane({("POST", f"/api/apps/{SELF_APP}/apply"): {"ok": True}})
            ran = apply_new_remote_apps(plane, home, before, after, tmp).get("ran")
            if bool(ran) != runs or (runs and plane.asked != [("POST", f"/api/apps/{SELF_APP}/apply", {})]):
                problems.append(f"{label}: apply ran={ran}, asked {plane.asked}")
    # The compiler's own reader is the second half of this contract: what we write must validate.
    # Checked where the compiler IS — the checkout. The app's image carries only this directory, and
    # there this check used to end the whole selftest with `IndexError: 2` instead of a result.
    manager = _compiler_dir()
    if manager:
        import sys
        sys.path.insert(0, manager)
        import serve
        cat = {"console": {"routing": [{"host": "console"}]}}
        entries, errs = serve.plan({"remote": block}, cat)
        if errs or len(entries) != 1 or not serve.render(entries, cat):
            problems.append(f"what the projection writes must compile: {errs}")
    return problems


def _compiler_dir() -> str:
    """`platform/manager` of the checkout this file is in, or "" inside the app's image."""
    up = Path(__file__).resolve().parents
    manager = up[2] / "platform/manager" if len(up) > 2 else None
    return str(manager) if manager is not None and (manager / "serve.py").is_file() else ""


if __name__ == "__main__":
    bad = selftest()
    for b in bad:
        print("FAIL", b)
    print("projection.py selftest:", "PASS" if not bad else f"{len(bad)} problem(s)",
          "" if _compiler_dir() else "(without the compiler's half: it is not in this image)")
    raise SystemExit(1 if bad else 0)
