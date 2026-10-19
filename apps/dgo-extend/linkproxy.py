"""dgo-extend.linkproxy — DELIVERY: the half a firewall cannot do (DGO-24).

`firewall.py` decides PERMISSION, and says so in its own words: an `accept` on `wg0` is "the
permission, not the delivery" — deciding that an allowed packet ends up at the app's container rather
than at the tunnel container's own stack is FORWARDING, "the tunnel's other half and a different
owner". This module is that owner.

Why a TCP proxy and not a destination NAT
-----------------------------------------
The obvious shape for "deliver an allowed packet to the app" is a DNAT in the tunnel container. It is
the wrong one here, for three reasons that are measured rather than preferred:

* **The app's address is not a fact of any declaration.** Docker assigns it, and it moves when the
  app is recreated. A DNAT rule carries a rendered IP, so the day the address moves the link delivers
  to nothing while every screen still says the link is up — a silent failure of exactly the kind this
  plane exists to make impossible. The proxy resolves the app's NAME per connection instead, inside
  the tunnel container's own namespace, through Docker's resolver (measured 2026-10-01: a container
  sharing `dgo-net`'s namespace gets `nameserver 127.0.0.11` and resolves `bina-ds`).
* **A delivered connection is an INPUT packet, not a forwarded one.** It terminates in the tunnel
  container, so the permission table's `forward` chain — where `serve` renders its accepts — never
  sees it, and its `input` chain ended in `drop` (only replies and ICMP pass, which is what makes
  `ping 10.79.x.1` the link's proof). Measured from vps1 on 2026-10-01: `10.79.2.1:3081` and `:8983`
  answered nothing at all — `timeout 8` expired (rc=124), i.e. the SYN was DROPPED, not refused. The
  accept for that INPUT path therefore lives in `firewall.py`'s own `from_tunnel` chain, where the
  `drop` is: a base chain's `accept` is NOT final across chains (measured the same day — a SYN that
  matched and was accepted in a chain of this half's own was still dropped by the permission chain;
  flushing that chain made the port answer immediately). One chain, one verdict. This module only
  LISTENS.
* **A proxied connection can be counted, closed and refused by name.** Which is what the screens and
  the gate need; a DNAT half-delivers silently.

What it renders, and what it refuses
------------------------------------
`build()` is pure — a projection of the declarations this app already owns (the home office's own
`serve:` list, and each peer's link direction), so the gate can check it with no tunnel, no machine
and no second office. Every refusal is a sentence: a rule is a door, and a door rendered from a typo
is a door onto something nobody named.

* `serve` — a peer may arrive HERE: bind this office's own tunnel address, deliver to the local app.
* `use` — this office consumes the PEER's apps: bind locally, deliver to the peer's tunnel address.
  That half needs the peer's `serve:` list, which today only the serving office knows; `build()`
  takes it as `served_by_peer` so the day the link carries it, nothing here changes.

The rendered files live in the tunnel volume next to `wg0.conf`, for the same reason every other
plan does: the app has the opinion, the container only applies it.
"""
from __future__ import annotations

import ipaddress
import json
import re
import time
from pathlib import Path

import catalog

#: The tunnel interface, and the only interface traffic may arrive on (`firewall.py` owns the name).
WG_IF = "wg0"
#: Where the tunnel volume is mounted, in the app and in the proxy container alike.
DEFAULT_DIR = "/tunnel"
#: The link plane's own range (`net.py`): one /24 per pair, .1 this office, .2 the peer.
TUNNEL_NET = ipaddress.ip_network("10.79.0.0/16")
#: A Docker service name, which is what a delivery target may be: the proxy resolves it per
#: connection, so anything that is not a name in this network is a rule pointing at nothing.
SERVICE_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
#: The plan's file name. One file: the firewall half of delivery is `firewall.py`'s (`from_tunnel`),
#: rendered from the same declaration, so this half has no rules of its own to publish.
PLAN_NAME = "link-proxy.json"

# ── the ONE DOOR a link gets (DGO-32) ─────────────────────────────────────────────────────────────
#: Why a door and not a port per app: this office's registry holds four apps that answer on 8080, two
#: on 8000 and two on 8977, and a link that opens one listener per app must either collide (EADDRINUSE
#: at runtime) or silently pick a winner. Measured on vps1 2026-10-02 — the plan was REFUSED, so
#: nothing at all was served. One listener per link, and the HTTP `Host` header picks the app behind
#: it: a name is not a scarce resource, a port is.
#:
#: The port is derived from the PAIR's own slot (`net.py`: one /24 per pair, slot = its third octet),
#: so both ends compute the same number from a fact they already share — no allocation, no state, and
#: no second thing to keep in step. The serving office answers the peer on `10.79.<slot>.1:<door>`;
#: the consuming office listens for itself on `<its own address>:<door>`.
DOOR_BASE = 9000
#: The name a door rule carries in the plan (an app-level word, because a rule names a target).
DOOR_APP = "door"
#: The serving office's own app, which the door ASKS for the route table (`/api/link/catalog`), and
#: which is also the link's control door: `catalog.CATALOG_PORT` on the tunnel is how a peer learns
#: which apps exist. The door asks the SAME list rather than being shipped one, because which apps
#: this office serves is a declaration on THIS side and a copy would be a second answer to it.
SELF_APP = "dgo-extend"


def door_port(slot: int) -> int:
    """The link's door on the pair's own slot: `door_port(2)` = 9002."""
    slot = int(slot)
    if not 1 <= slot <= 254:
        raise LinkProxyError(f"slot {slot} מחוץ לטווח 1–254 — אין פורט לדלת הקישור")
    return DOOR_BASE + slot


#: Where THIS office's own listener for a peer's catalog sits: `9400 + slot`. It is deliberately not
#: the peer's `catalog.CATALOG_PORT`: that number is the port the PEER binds on its own tunnel address,
#: while this is the address we answer OUR OWN projection on — and one port for two consuming pairs is
#: a collision that refuses the entire plan (measured 2026-10-04, read-only, against the real
#: declarations: two `use` peers, both control doors on 8983, `LinkProxyError`, zero listeners).
CONTROL_BASE = 9400


def control_port(slot: int) -> int:
    """This office's own catalog listener for the pair on `slot`."""
    slot = int(slot)
    if not 1 <= slot <= 254:
        raise LinkProxyError(f"slot {slot} מחוץ לטווח 1–254 — אין פורט לדלת הבקרה")
    return CONTROL_BASE + slot


#: Where THIS office's own listener for a peer's AGENT API goes when the number the peer published
#: is already taken here. Such a listener normally sits on the peer's own port — a CLI addresses a
#: port, and one peer's `3081` is `3081` here too — until a SECOND peer publishes the same number.
#: That is the normal case, not an accident: every office's agent answers on the same port. Measured
#: 2026-10-05 on the MacBook: hp-laptop and vps1 both published `bina-ds` on 3081, the plan was
#: refused as "one door, one app", and with it EVERY door of both links — including the control
#: door's corrected target, so neither peer could read this office's catalog any more and a security
#: fix that had been deployed never took effect. One consuming rule must not be able to do that.
#:
#: So the listener that cannot have its number moves into a range of its PAIR's own
#: (`AGENT_BASE + slot * AGENT_PER_PAIR`). Only this office's own listener moves: the peer is still
#: reached on the port it published, nothing changes on the wire, and an office with one such peer
#: renders exactly what it did. The plan states where each listener ended up, and the projection
#: writes THAT as the port to dial (`projection.apply_plan`) — one decision, read where it is needed.
AGENT_BASE = 10000
AGENT_PER_PAIR = 16


def agent_range(slot: int) -> range:
    """The local ports a pair's displaced agent listeners may take."""
    first = AGENT_BASE + int(slot) * AGENT_PER_PAIR
    return range(first, first + AGENT_PER_PAIR)


#: Where a far end whose tunnel runs on its MACHINE bridges TCP into this container: a directory the
#: host and `dgo-link` share (a bind mount), because a unix socket is the one door both sides can see
#: without either of them knowing the other's address.
DOOR_DIR = "/doors"


def _serve_doors(oid: str, slot: int, self_addr: str, peer_addr: str, own: dict,
                 host_doors: bool = False) -> list[dict]:
    """What lets a peer in: the ONE door, the catalog behind it, and the agent APIs' own ports.

    `own` is this office's `serve:` map WITH the control door (`catalog.with_control`), so an office
    that serves nothing gets no rule at all — not even a listener: a door onto nothing is worse than a
    closed one, because it looks open.

    `host_doors` renders the same doors as unix sockets for the far end of a pair whose tunnel runs on
    its MACHINE (`net.render(host_forward=True)`): that end's tunnel address is not in this container's
    namespace, so binding it fails (`link-proxy._in_tunnel_namespace` exits on exactly that), and a
    small service on the machine — the only thing that CAN listen there — bridges into the socket.
    """
    if not own:
        return []
    door = door_port(slot)
    link = f"{SELF_APP}:{int(catalog.LINK_PORT)}"
    out = [
        {"office": oid, "direction": "serve", "app": DOOR_APP, "kind": "door",
         "port": door, "target": link, "clients": [peer_addr],
         "note": "the link's one door — the Host header picks the app, this office's catalog is the "
                 "route table"},
        {"office": oid, "direction": "serve", "app": SELF_APP, "kind": "app",
         "port": int(catalog.CATALOG_PORT), "target": link, "clients": [peer_addr],
         "note": "the catalog: how the peer learns which apps this office serves — the app's link "
                 "listener, never its own port"},
    ]
    for app, spec in sorted(own.items()):
        if app == SELF_APP or app == catalog.WILDCARD:
            # The wildcard is not an app: it is "everything this office has, published" (see
            # `catalog.publishable`). Its apps' agent ports cannot be enumerated from here — this
            # module has no registry — so a wildcard-served office's agent APIs need their app named
            # explicitly in `serve:`. The UI doors are all behind the door above and need no entry.
            continue
        # The SECOND port of an agent app (DGO-32) keeps a door of its own: a CLI addresses a port,
        # and the door's Host routing cannot tell an adapter from the UI that shares its authority.
        for port in ports_of(app, spec)[1:]:
            out.append({"office": oid, "direction": "serve", "app": app, "kind": "app",
                        "port": _port(app, port), "target": f"{app}:{int(port)}",
                        "clients": [peer_addr], "note": "an agent API's own door"})
    for rule in out:
        if host_doors:
            # The socket name carries the SLOT: an office that serves two peers has two doors, and
            # one socket path for both would have the second bridge overwrite the first.
            rule["bind"] = f"unix:{DOOR_DIR}/{oid}-{slot}-{rule['app']}.sock"
            rule["host_bind"] = self_addr
        else:
            rule["bind"] = self_addr
    return out



class LinkProxyError(RuntimeError):
    """Rendering refused, with the field named. A rule nobody can check is a door nobody can close."""


def mirror(direction: str) -> str:
    """A link seen from the other end: what one office serves, the other uses.

    `both` mirrors to `both` (see `converge._mirror`): a bidirectional link is bidirectional on the
    far side too, and reading it back as `use` would close the half the owner declared.
    """
    d = direction or "use"
    if d == "both":
        return "both"
    return "use" if d == "serve" else "serve"


def _link_of(office: dict, other_id: str) -> dict:
    for link in (office.get("links") or []):
        if (link or {}).get("office") == other_id or (link or {}).get("id") == other_id:
            return link or {}
    return {}


def ports_of(app: str, spec) -> list[int]:
    """Every port ONE served app is answered on, in declaration order.

    An app is usually one port, but an agent app is two: the UI a person opens (the tile) and the
    adapter a CLI speaks to (`agent_api_port`, DGO-32). Both are doors into the same container, and
    the delivery half must open exactly the set the firewall does — a port the firewall accepts and
    nothing listens on is the "accepted and dropped" failure this plane was written after.

    A spec that names no port at all is refused here, where the sentence can say which app: rendering
    no rule for a `serve:` entry would leave an app declared open and reachable by nobody.
    """
    values = []
    if isinstance(spec, dict):
        for key in ("port", "agent_api_port"):
            if key in spec and spec[key] not in (None, ""):
                values.append(spec[key])
    elif spec is not None:
        values.append(spec)
    if not values:
        raise LinkProxyError(f"ל„{app}” אין פורט מספרי בהצהרת ה-`serve:` ({spec!r})")
    return values


def _port(app: str, value) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise LinkProxyError(f"ל„{app}” אין פורט מספרי בהצהרת ה-`serve:` ({value!r})")
    if not 1 <= port <= 65535:
        raise LinkProxyError(f"הפורט של „{app}” ({port}) מחוץ לטווח")
    if not SERVICE_RE.match(str(app)):
        raise LinkProxyError(f"„{app}” אינו שם שירות שאפשר למסור אליו — יעד האספקה הוא שם "
                             f"בתוך הרשת (אותיות לטיניות קטנות, ספרות ומקף)")
    return port


def _slot(home: dict) -> int:
    try:
        slot = int((home.get("tunnel") or {}).get("slot"))
    except (TypeError, ValueError):
        raise LinkProxyError(f"ללשכה {(home.get('id'))!r} אין slot מוצהר (tunnel.slot) — "
                             f"אין כתובת מנהרה למסור עליה")
    if not 1 <= slot <= 254:
        raise LinkProxyError(f"slot {slot} מחוץ לטווח 1–254")
    return slot


def _address(slot: int, side: int) -> str:
    return f"10.79.{slot}.{side}"


def _same_door(a: dict, b: dict) -> bool:
    """Do two rules fight for one listener? Same port AND overlapping bind addresses.

    ONE namespace, and a socket may bind ONE address per port — so `10.79.2.1:8983` and
    `172.18.0.5:8983` are two listeners that both work, while `0.0.0.0:8983` claims the port on every
    address there is and collides with either. That distinction is what makes the link's own catalog
    door possible on an office that both serves its catalog (`10.79.x.1`, for the peer) and consumes
    another office's (`<its own network address>`, for itself).
    """
    left, right = str(a.get("bind") or "0.0.0.0"), str(b.get("bind") or "0.0.0.0")
    # A UNIX socket holds no TCP port: its "port" is the number the host-side bridge stands for, not a
    # listener in this namespace. It clashes only with the SAME socket path. Measured 2026-10-02 on
    # vps1: the far end that both consumes (use door, 0.0.0.0:9002) and serves (host door, a socket
    # for 10.79.2.2:9002) had its whole plan refused as "one door, one app".
    if left.startswith("unix:") or right.startswith("unix:"):
        return left == right
    if int(a.get("port") or 0) != int(b.get("port") or 0):
        return False
    return left == right or "0.0.0.0" in (left, right)


def build_multi(home: dict, pairs: list[dict], served_by_peer: dict | None = None,
                control_bind: str = "", halves: tuple[str, ...] = ("serve", "use"),
                iface: str = "") -> dict:
    """The delivery plan for EVERY pair this office holds: one rule set, one file, one namespace.

    Each pair is described by its caller — `net.py`'s pair list is the same fact:

        {"office": <the peer's record>, "slot": 2, "side": 1, "host_doors": False}

    `side` is per PAIR (we may be `.1` in one pair and `.2` in another), which is exactly what a
    scalar could not express, and `host_doors` is per pair for the same reason (a pair whose tunnel
    runs on the far MACHINE is bridged by unix sockets; a pair whose tunnel runs here binds the address).

    ONE PLAN FOR ALL PAIRS is deliberate: every door binds inside this one container's namespace
    (`linkproxy`'s rules name the pair's own tunnel address, and the console's aliases hang off this
    same service), so the consumer — `link-proxy.py` — stays a loop over rules and needs no notion of
    a pair at all.
    """
    served_by_peer = served_by_peer or {}
    home_id = str(home.get("id") or "local")
    own = catalog.with_control(home.get("serve"))
    rules: list[dict] = []
    meta: list[dict] = []
    for pair in (pairs or []):
        office = pair.get("office") or {}
        oid = str(office.get("id") or pair.get("office_id") or "")
        if not oid or oid == home_id:
            continue
        slot = int(pair.get("slot") or 0)
        if not 1 <= slot <= 254:
            raise LinkProxyError(f"לזוג עם {oid!r} אין slot תקין ({pair.get('slot')!r})")
        side = int(pair.get("side") or 1)
        if side not in (1, 2):
            raise LinkProxyError(f"side {side!r} בזוג עם {oid!r} — זוג הוא שני קצוות בלבד (1 או 2)")
        host_doors = bool(pair.get("host_doors"))
        link = pair.get("link") or _link_of(office, home_id)
        # WHAT THIS PAIR IS GIVEN (`catalog.only_for`): an office narrowed by `serve.only` gets an
        # agent API's own door only for an app on its list. The link's door and the catalog stay —
        # they are how that office learns what it was given, and the door routes by that same list.
        only = catalog.only_for(home.get("serve"), oid)
        given = own if only is None else {k: v for k, v in own.items() if k == SELF_APP or k in only}
        rules.extend(_pair_rules(home_id, oid, slot, side, link, given,
                                 served_by_peer.get(oid) or {}, control_bind, halves, host_doors))
        meta.append({"office": oid, "slot": slot, "side": side, "self": _address(slot, side),
                     "peer": _address(slot, 3 - side),
                     # The interface is the pair's (`wg<slot>`) when the tunnel runs HERE, and the
                     # machine's own single tunnel (`wg0`, brought up by `wg-quick@wg0`) when this
                     # plan is for a far end whose tunnel runs on its host — two different facts, and
                     # the caller's `host_doors` is what says which one this is.
                     "iface": iface or (WG_IF if host_doors else f"wg{slot}"),
                     "host_doors": host_doors,
                     "direction": mirror((link or {}).get("direction") or "use")})
    seen: list[dict] = []
    # The doors a declaration decides come first, so a listener that CAN move never takes a port one
    # of them needs: a pair's door, its catalog listener and everything this office serves are fixed
    # by the pair's slot or by this office's own `serve:`.
    for rule in sorted(rules, key=lambda r: r.get("kind") == "agent"):
        # ONE listener per port AND ADDRESS in one namespace: a second bind on the same pair fails at
        # runtime (EADDRINUSE), and a rule that cannot be applied is worse than one that was never
        # rendered. Refused with both names, because the fix is a declaration.
        clash = next((r for r in seen if _same_door(r, rule)), None)
        if clash is not None and rule.get("kind") == "agent":
            # ...except our own listener for a peer's agent API (see AGENT_BASE): two peers publishing
            # one number is not something a declaration here can fix, so it takes the first free port
            # of its pair's range and keeps the peer's own port as its target.
            free = next((p for p in agent_range(rule["slot"])
                         if not any(_same_door(r, {**rule, "port": p}) for r in seen)), None)
            if free is not None:
                rule["port"], clash = free, None
        if clash is not None:
            raise LinkProxyError(f"פורט {rule['port']} ({rule['bind']}) מבוקש גם עבור "
                                 f"{clash['office']}/{clash['app']} וגם עבור "
                                 f"{rule['office']}/{rule['app']} — דלת אחת, אפליקציה אחת")
        seen.append(rule)
    plan = {"office": home_id, "generated_at": int(time.time()), "rules": rules, "pairs": meta}
    if meta:
        # The keys a reader written before pairs existed still reads describe the FIRST pair. The same
        # compatibility `net.render_multi` renders into `addressing.json`, for the same reason: the
        # office whose far end has not been updated is read by the code running there.
        first = meta[0]
        plan.update({"slot": first["slot"], "side": first["side"], "self": first["self"],
                     "wg_if": first["iface"]})
    else:
        plan.update({"slot": 0, "side": 1, "self": "", "wg_if": WG_IF})
    return plan


def _pair_rules(home_id: str, oid: str, pslot: int, side: int, link: dict, own: dict,
                served_by_peer: dict, control_bind: str, halves: tuple[str, ...],
                host_doors: bool) -> list[dict]:
    """Every rule ONE pair needs: the doors it serves, and the doors that reach the peer."""
    rules: list[dict] = []
    self_here = _address(pslot, side)
    peer_here = _address(pslot, 3 - side)
    mine = mirror((link or {}).get("direction"))
    # `both`: the owner declared the link bidirectional, so BOTH halves render here — this office's
    # own door on its tunnel address AND (next) the door that reaches the peer's. Two rules for one
    # address:port would collide, and the clash check still catches that: one door, one app.
    if mine in ("serve", "both") and "serve" in halves:
        rules.extend(_serve_doors(oid, pslot, self_here, peer_here, own, host_doors))
    if mine in ("use", "both") and "use" in halves:
        pdoor = door_port(pslot)
        # THE DOOR THAT REACHES THE PEER'S APPS (DGO-32). One listener per peer, bound where callers
        # HERE can reach it — the link proxy's own network address when it can be resolved
        # (`control_bind`), never 0.0.0.0 in that case: on a bidirectional link the same port is
        # already held by this half's serve door on the tunnel address, and 0.0.0.0 would claim it
        # there too — EADDRINUSE at runtime, an office whose delivery is half up with nothing in any
        # log to say why. It carries bytes to the peer's door and has no opinion about them: the Host
        # header the consuming edge wrote is what picks the app on the far side.
        rules.append({"office": oid, "direction": "use", "app": DOOR_APP, "kind": "door",
                      "slot": pslot, "port": pdoor, "target": f"{peer_here}:{pdoor}",
                      "bind": control_bind or "0.0.0.0", "clients": [],
                      "note": "one door to the peer — the serving office routes by Host"})
        # THE LINK'S OWN CONTROL DOOR, rendered unconditionally (DGO-37). The catalog is how this
        # office learns which of the peer's apps exist — so it cannot be something the peer's app list
        # has to announce before the list can be read. It is the peer's dgo-extend on ITS catalog port,
        # and the other half of it (`catalog.with_control`) is what opens that port on the peer's
        # firewall and renders its listener there.
        #
        # OUR listener is per PAIR (`control_port(slot)`), not the peer's catalog port: this is the
        # address WE answer ourselves on, and two consuming pairs sharing one port refused the whole
        # plan — measured 2026-10-04, read-only, against the real declarations: two `use` peers, both
        # control doors on 8983, `LinkProxyError`, zero listeners.
        rules.append({"office": oid, "direction": "use", "app": SELF_APP,
                      "slot": pslot, "kind": "control",
                      "port": control_port(pslot),
                      "target": f"{peer_here}:{int(catalog.CATALOG_PORT)}",
                      "bind": control_bind or "0.0.0.0", "clients": [],
                      "note": "our own listener for the peer's catalog, one port per pair"})
        # An agent app's SECOND door stays an explicit port rule: a CLI addresses a port, not a name,
        # and the door's Host routing cannot tell an adapter from the UI that shares its authority
        # (DGO-32). These are the apps whose ports the peer published, so nothing is guessed. Our
        # listener sits on the peer's own port unless another peer's already does (`build_multi` moves
        # it then, into this pair's `agent_range`); `published` is the port on the wire either way.
        for app, spec in sorted((served_by_peer or {}).items()):
            for port in ports_of(app, spec)[1:]:
                rules.append({"office": oid, "direction": "use", "app": app, "kind": "agent",
                              "slot": pslot, "port": _port(app, port), "published": int(port),
                              "target": f"{peer_here}:{int(port)}",
                              "bind": control_bind or "0.0.0.0", "clients": []})
    return rules


def build(home: dict, offices: list[dict], served_by_peer: dict | None = None,
          control_bind: str = "", side: int = 1,
          halves: tuple[str, ...] = ("serve", "use"), host_doors: bool = False,
          iface: str = "") -> dict:
    """The delivery plan for a SINGLE-pair view — the shape every existing caller passes.

    `home` is this office's own record, `offices` the declarations of the peers it may be linked to
    (the link is declared ON THE PEER — `links: [{office: local, direction: …}]` — which is why the
    direction is read there and mirrored here), and `served_by_peer` the ports a peer published in its
    catalog (only its agent APIs are still delivered by port).

    `side` is which end of the pair's /24 THIS office holds. It is decided by whoever renders the pair
    (the end that dials holds `.1`, `net.render(pair=…)`), not by who consumes — so the far end of a
    pair renders with `side=2`, and its `use` rules then reach `.1`. A constant `.2` here pointed the
    far end's listeners at ITSELF (the same trap `projection.peer_side` documents).

    A home with SEVERAL pairs is `build_multi`, where `side` and `host_doors` are per pair. This one
    keeps the scalar because that is what a far end has: one pair, one side.
    """
    home_id = str(home.get("id") or "local")
    # The home's OWN slot is validated here even though every pair carries its own: it is the fallback
    # for a peer declaration that predates the field, and an office with no slot at all is a refusal
    # (not a plan rendered against a slot nobody declared).
    home_slot = _slot(home)
    pairs = []
    for office in sorted(offices or [], key=lambda o: str(o.get("id") or "")):
        oid = str(office.get("id") or "")
        if not oid or oid == home_id:
            continue
        link = _link_of(office, home_id)
        if not link:
            continue
        try:
            pslot = int((office.get("tunnel") or {}).get("slot") or home_slot)
        except (TypeError, ValueError):
            pslot = home_slot
        pairs.append({"office": office, "slot": pslot, "side": int(side),
                      "host_doors": host_doors, "link": link})
    return build_multi(home, pairs, served_by_peer, control_bind, halves, iface)


def write(base: str | Path, home: dict, offices: list[dict],
          served_by_peer: dict | None = None, control_bind: str = "",
          host_doors: bool = False) -> dict:
    """Render and write the plan where the proxy container reads it. Returns what was written.

    Written even when EMPTY, on purpose: a file that says "no rules" is how a link that was taken
    away removes the listeners that carried it, and the proxy deletes its own firewall table when it
    sees one.
    """
    plan = build(home, offices, served_by_peer, control_bind, host_doors=host_doors)
    directory = Path(base)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / PLAN_NAME).write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return plan


def write_multi(base: str | Path, home: dict, pairs: list[dict], served_by_peer: dict | None = None,
                control_bind: str = "", halves: tuple[str, ...] = ("serve", "use"),
                iface: str = "") -> dict:
    """Render EVERY pair's delivery and write it where the proxy container reads it.

    One file for all pairs, deliberately (see `build_multi`): the consumer loops over rules, and a
    per-pair file would make it learn a notion of a pair it does not need.
    """
    plan = build_multi(home, pairs, served_by_peer, control_bind, halves, iface)
    directory = Path(base)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / PLAN_NAME).write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return plan


def read(base: str | Path = DEFAULT_DIR) -> dict:
    """What is rendered right now, read back from the volume — "rendered" is never assumed."""
    directory = Path(base)
    plan: dict = {}
    try:
        plan = json.loads((directory / PLAN_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        plan = {}
    return {"plan": plan, "present": bool(plan)}


def selftest() -> list[str]:
    """The decisions this module makes, on a two-office example. No tunnel, no machine, no docker —
    which is the point: the gate checks the projection before a second office exists."""
    problems: list[str] = []
    CATALOG_PORT = int(catalog.CATALOG_PORT)
    home = {"id": "local", "tunnel": {"slot": 2},
            "serve": {"bina-ds": {"port": 3081}, "dgo-extend": {"port": 8983}}}
    vps1 = {"id": "vps1", "tunnel": {"slot": 2}, "links": [{"office": "local", "direction": "use"}]}
    plan = build(home, [vps1])
    # ONE door for the whole link (DGO-32): four apps of this office answer on 8080, so a listener per
    # app collides; the Host header picks the app instead. The catalog keeps its own explicit port —
    # it is how the peer learns which apps exist, and it cannot be behind the door it describes.
    got = sorted((r["direction"], r["app"], r["port"], r["target"], r["bind"]) for r in plan["rules"])
    link = f"{SELF_APP}:{int(catalog.LINK_PORT)}"
    want = [("serve", SELF_APP, CATALOG_PORT, link, "10.79.2.1"),
            ("serve", DOOR_APP, door_port(2), link, "10.79.2.1")]
    if got != want:
        problems.append(f"a serving office answers with its door and its catalog, got {got}")
    if any(str(r.get("target")) == f"{SELF_APP}:{CATALOG_PORT}" for r in plan["rules"]):
        problems.append("no rule may lead a peer to the app's OWN port: a splice carries every path, "
                        "so the control door must end at the link listener, which serves the catalog "
                        "and nothing else")
    for rule in plan["rules"]:
        if rule["clients"] != ["10.79.2.2"]:
            problems.append(f"only the link's own address may arrive, got {rule['clients']}")
    if plan["self"] != "10.79.2.1" or plan["wg_if"] != "wg2":
        problems.append("the plan must name the address the listeners bind and the pair's interface")
    # The door knows it is a door (the proxy reads the Host for exactly these), and the port is the
    # PAIR's own: both ends compute it from the slot they already share.
    door = next(r for r in plan["rules"] if r["app"] == DOOR_APP)
    if door.get("kind") != "door" or door_port(2) != 9002 or door_port(9) != 9009:
        problems.append(f"the door is one rule per link, keyed by the pair's slot, got {door}")
    try:
        door_port(0)
        problems.append("a door with no slot must be refused, not defaulted")
    except LinkProxyError:
        pass

    # An agent app is TWO doors in one container (DGO-32): the UI a person opens and the adapter a CLI
    # speaks to. The UI rides the link door; the adapter keeps a port of its own, because a CLI
    # addresses a port and the door's Host routing cannot tell one from the other.
    agent_home = {"id": "local", "tunnel": {"slot": 2},
                  "serve": {"bina-ds": {"port": 3080, "agent_api_port": 3081}}}
    agent_plan = build(agent_home, [vps1])
    agent_rules = sorted((r["port"], r["target"]) for r in agent_plan["rules"]
                         if r["app"] not in (SELF_APP, DOOR_APP))
    if agent_rules != [(3081, "bina-ds:3081")]:
        problems.append(f"an agent API keeps a door of its own, got {agent_rules}")
    # An office that serves nothing opens nothing — not even a door.
    if build({"id": "local", "tunnel": {"slot": 2}, "serve": {}}, [vps1])["rules"]:
        problems.append("an office that serves nothing must render no listener at all")
    # ...and `serve: {"*": {}}` ("all my apps") is still ONE door: the wildcard is not an app and has
    # no port of its own, which is exactly the typo that would otherwise refuse the whole plan.
    star = build({"id": "local", "tunnel": {"slot": 2}, "serve": {"*": {}}}, [vps1])
    if sorted(r["app"] for r in star["rules"]) != sorted([DOOR_APP, SELF_APP]):
        problems.append(f"a wildcard `serve:` renders the door and the catalog, got {star['rules']}")

    # The other direction: this office consumes the peer's apps, through ONE listener that carries the
    # consuming edge's Host header to the peer's door.
    consumer = {"id": "local", "tunnel": {"slot": 2}, "serve": {}}
    peer_serves = {"id": "vps1", "tunnel": {"slot": 2},
                   "links": [{"office": "local", "direction": "serve"}]}
    used = build(consumer, [peer_serves], {"vps1": {"drive": {"port": 8975}}})
    got = sorted((r["app"], r["port"], r["target"]) for r in used["rules"])
    want = [(SELF_APP, control_port(2), f"10.79.2.2:{CATALOG_PORT}"),
            (DOOR_APP, door_port(2), f"10.79.2.2:{door_port(2)}")]
    if got != want:
        problems.append(f"the consuming half is one door plus the catalog, got {got}")
    # The link's own control door (DGO-37): the catalog is how this office learns which apps exist over
    # there, so it is rendered even when nothing else is known about the peer.
    blind = build(consumer, [peer_serves])["rules"]
    if sorted(r["app"] for r in blind) != sorted([DOOR_APP, SELF_APP]):
        problems.append(f"with no published apps, the door and the catalog are still rendered: {blind}")
    # ...and everything binds this container's own address when it is known, because the same port may
    # be held by the SERVING half on the tunnel address in this very namespace.
    for rule in build(consumer, [peer_serves], control_bind="172.18.0.9")["rules"]:
        if rule["bind"] != "172.18.0.9":
            problems.append(f"the consuming half must bind where callers were told it answers: {rule}")
    # Two peers: each door is keyed by ITS OWN pair's slot, so two links never fight for one port.
    two = build({"id": "local", "tunnel": {"slot": 2}, "serve": {"drive": {"port": 8975}}},
                [{"id": "vps1", "tunnel": {"slot": 2},
                  "links": [{"office": "local", "direction": "use"}]},
                 {"id": "vps2", "tunnel": {"slot": 3},
                  "links": [{"office": "local", "direction": "use"}]}])
    if sorted(r["port"] for r in two["rules"] if r["app"] == DOOR_APP) != [9002, 9003]:
        problems.append(f"one door per peer, on that pair's own slot, got {two['rules']}")
    # TWO CONSUMING PAIRS ARE THE CASE THAT USED TO REFUSE THE WHOLE PLAN. Measured 2026-10-04,
    # read-only, against the real declarations: both control doors rendered on `CATALOG_PORT` with
    # `bind 0.0.0.0`, `_same_door` caught them, and the office was left with ZERO listeners — a second
    # link taking the first one down. Our own catalog listener is per pair, so both render.
    two_use = build({"id": "local", "tunnel": {"slot": 2}, "serve": {}},
                    [{"id": "vps1", "tunnel": {"slot": 2},
                      "links": [{"office": "local", "direction": "serve"}]},
                     {"id": "hp-laptop", "tunnel": {"slot": 3},
                      "links": [{"office": "local", "direction": "serve"}]}])
    controls = sorted(r["port"] for r in two_use["rules"] if r["app"] == SELF_APP)
    if controls != sorted([control_port(2), control_port(3)]):
        problems.append(f"each consuming pair needs its OWN catalog listener, got {controls}")
    if sorted(r["port"] for r in two_use["rules"] if r["app"] == DOOR_APP) != [9002, 9003]:
        problems.append(f"each consuming pair needs its own door, got {two_use['rules']}")
    # ...and the plan names every pair, so a reader does not have to infer one from a port number.
    if [m["office"] for m in two_use["pairs"]] != ["hp-laptop", "vps1"]:
        problems.append(f"the plan must carry one entry per pair, got {two_use.get('pairs')}")
    # ...and the SAME slot twice is one port on one address: refused, with both offices named.
    try:
        build({"id": "local", "tunnel": {"slot": 2}, "serve": {}},
              [{"id": "vps1", "tunnel": {"slot": 2},
                "links": [{"office": "local", "direction": "serve"}]},
               {"id": "vps2", "tunnel": {"slot": 2},
                "links": [{"office": "local", "direction": "serve"}]}])
        problems.append("two peers on one slot must be refused — one listener, one link")
    except LinkProxyError as e:
        if "vps1" not in str(e) or "vps2" not in str(e):
            problems.append(f"the clash must name both offices, got {e}")

    # TWO PEERS THAT PUBLISH THE SAME AGENT PORT — every office's agent answers on one number, so
    # this is what two links look like, and it refused the whole plan (measured 2026-10-05, MacBook:
    # hp-laptop and vps1 both on 3081, zero rules written, both peers lost this office's catalog).
    # Both render: the first keeps the number, the other moves into ITS pair's range, and each still
    # reaches its own peer on the port that peer published.
    agent = {"bina-ds": {"port": 3080, "agent_api_port": 3081}}
    two_agents = build({"id": "local", "tunnel": {"slot": 2}, "serve": {}},
                       [{"id": "hp-laptop", "tunnel": {"slot": 4},
                         "links": [{"office": "local", "direction": "serve"}]},
                        {"id": "vps1", "tunnel": {"slot": 2},
                         "links": [{"office": "local", "direction": "serve"}]}],
                       {"hp-laptop": agent, "vps1": agent}, control_bind="172.18.0.4")
    got = sorted((r["office"], r["port"], r["target"]) for r in two_agents["rules"] if r.get("kind") == "agent")
    want = [("hp-laptop", 3081, "10.79.4.2:3081"), ("vps1", agent_range(2)[0], "10.79.2.2:3081")]
    if got != want:
        problems.append(f"two peers on one agent port both get a listener, got {got}")
    if len({(r["bind"], r["port"]) for r in two_agents["rules"]}) != len(two_agents["rules"]):
        problems.append("no two rules of one plan may hold one address and port")
    # ...a listener that moves never takes a port a DOOR needs, whatever order the rules came in:
    # a peer that publishes its agent on another pair's door number is the one that moves.
    odd = build({"id": "local", "tunnel": {"slot": 2}, "serve": {}},
                [{"id": "a-first", "tunnel": {"slot": 4},
                  "links": [{"office": "local", "direction": "serve"}]},
                 {"id": "vps1", "tunnel": {"slot": 2},
                  "links": [{"office": "local", "direction": "serve"}]}],
                {"a-first": {"bina-ds": {"port": 3080, "agent_api_port": door_port(2)}}})
    moved = [r["port"] for r in odd["rules"] if r.get("kind") == "agent"]
    doors = sorted(r["port"] for r in odd["rules"] if r["app"] == DOOR_APP)
    if moved != [agent_range(4)[0]] or doors != [door_port(2), door_port(4)]:
        problems.append(f"an agent listener gives way to a door, never the reverse: agent {moved}, doors {doors}")
    # ...and two listeners of ONE pair that both have to move take two ports of its range, not one.
    pair = {"bina-ds": {"port": 3080, "agent_api_port": 3081}, "browser": {"port": 8930, "agent_api_port": 8931}}
    crowded = build({"id": "local", "tunnel": {"slot": 2}, "serve": {}},
                    [{"id": "hp-laptop", "tunnel": {"slot": 4},
                      "links": [{"office": "local", "direction": "serve"}]},
                     {"id": "vps1", "tunnel": {"slot": 2},
                      "links": [{"office": "local", "direction": "serve"}]}],
                    {"hp-laptop": pair, "vps1": pair}, control_bind="172.18.0.4")
    theirs = sorted(r["port"] for r in crowded["rules"] if r.get("kind") == "agent" and r["office"] == "vps1")
    if theirs != list(agent_range(2)[:2]):
        problems.append(f"each displaced listener gets a port of its own in the pair's range, got {theirs}")
    # ...and one peer alone renders what it always did: the peer's own number, nothing moved.
    alone = build({"id": "local", "tunnel": {"slot": 2}, "serve": {}},
                  [{"id": "vps1", "tunnel": {"slot": 2},
                    "links": [{"office": "local", "direction": "serve"}]}], {"vps1": agent})
    if [(r["port"], r["published"]) for r in alone["rules"] if r.get("kind") == "agent"] != [(3081, 3081)]:
        problems.append("with one peer, its agent listener sits on the port it published")

    # An office with no link, and an office with no slot, are different states.
    if build(home, [])["rules"]:
        problems.append("no peer must render no rule, not a listener for nobody")
    try:
        build({"id": "local", "serve": {"drive": {"port": 8975}}}, [vps1])
        problems.append("an office with no declared slot must be refused, not defaulted")
    except LinkProxyError:
        pass
    try:
        build({"id": "local", "tunnel": {"slot": 999}, "serve": {"drive": {"port": 80}}}, [vps1])
        problems.append("a slot outside 1–254 must be refused, not rendered")
    except LinkProxyError as e:
        if "slot" not in str(e):
            problems.append(f"the refusal must name the slot, got {e}")

    # The FAR end of a pair (side 2, its tunnel on the machine): it consumes the dialing office's
    # served apps, and every listener must reach `.1` — never `.2`, which is itself. Measured on the
    # first real pair (MacBook `.1` dials, vps1 `.2` shows its apps): with the constant, vps1's tile
    # would have proxied to a port on vps1.
    far = {"id": "vps1", "tunnel": {"slot": 2}, "serve": {}}
    dialer = {"id": "macbook", "links": [{"office": "vps1", "direction": "both"}]}
    far_plan = build(far, [dialer],
                     {"macbook": catalog.with_control({"bina-ds": {"port": 3080, "agent_api_port": 3081}})},
                     side=2, halves=("use",), iface=WG_IF)
    got = sorted((r["direction"], r["app"], r["port"], r["target"], r["bind"])
                 for r in far_plan["rules"])
    want = [("use", "bina-ds", 3081, "10.79.2.1:3081", "0.0.0.0"),
            ("use", SELF_APP, control_port(2), f"10.79.2.1:{CATALOG_PORT}", "0.0.0.0"),
            ("use", DOOR_APP, door_port(2), f"10.79.2.1:{door_port(2)}", "0.0.0.0")]
    if got != want:
        problems.append(f"the far end consumes `.1` with the use half only, got {got}")
    if far_plan["wg_if"] != WG_IF:
        problems.append("a plan for a far end names the MACHINE's own interface, wg0")
    if far_plan["self"] != "10.79.2.2" or far_plan["side"] != 2:
        problems.append(f"the far end holds `.2`, got self={far_plan['self']} side={far_plan['side']}")
    try:
        build(far, [dialer], side=3)
        problems.append("a pair has two ends: side 3 must be refused")
    except LinkProxyError:
        pass

    # ...and when the FAR end is the one that SERVES, its doors cannot bind the tunnel address (that
    # address is not in its proxy's namespace — its tunnel runs on the machine), so they are rendered
    # as unix sockets with the host address beside them: the only thing that can listen THERE bridges
    # into them (`converge.REMOTE_DOOR`).
    serving_far = {"id": "vps1", "tunnel": {"slot": 2},
                   "serve": {"drive": {"port": 8975, "agent_api_port": 8976},
                             "mail": {"port": 8970}}}
    far_serve = build(serving_far, [dialer], side=2, halves=("serve",), host_doors=True,
                      iface=WG_IF)
    for rule in far_serve["rules"]:
        if not str(rule["bind"]).startswith("unix:") or rule.get("host_bind") != "10.79.2.2":
            problems.append(f"a serving far end binds a socket and names its host address, got {rule}")
    ports = sorted(r["port"] for r in far_serve["rules"])
    # The door, the catalog, and the ONE agent port. `drive`'s UI port is behind the door, and no rule
    # carries an app's UI port any more — which is the whole point.
    if ports != sorted([door_port(2), CATALOG_PORT, 8976]):
        problems.append(f"a serving far end opens the door, the catalog and agent ports, got {ports}")
    if any(r["app"] == "mail" for r in far_serve["rules"]):
        problems.append("an app with one door must not get a listener of its own")

    # The far end of a BIDIRECTIONAL pair whose tunnel runs on the machine (vps1, 2026-10-02): it
    # consumes the dialer's apps (a use door, 0.0.0.0:9002 in its own namespace) AND serves its own (a
    # host door: a unix socket the machine's bridge stands in front of, for 10.79.2.2:9002). One port
    # number, two different listeners — the plan must render, not refuse.
    both_far = build({"id": "vps1", "tunnel": {"slot": 2}, "serve": {"*": {}}},
                     [{"id": "macbook", "links": [{"office": "vps1", "direction": "both"}]}],
                     {"macbook": catalog.with_control({"bina-ds": {"port": 3080, "agent_api_port": 3081}})},
                     side=2, halves=("serve", "use"), host_doors=True)
    doors = [r for r in both_far["rules"] if r["app"] == DOOR_APP]
    if len(doors) != 2 or sorted(str(r["bind"]).startswith("unix:") for r in doors) != [False, True]:
        problems.append(f"a bidirectional far end needs a use door and a socket serve door, got {doors}")
    if not any(r.get("host_bind") == "10.79.2.2" for r in doors):
        problems.append(f"the socket door must say which address the machine's bridge stands for, got {doors}")
    return problems


if __name__ == "__main__":
    bad = selftest()
    for b in bad:
        print("FAIL", b)
    print("linkproxy.py selftest:", "PASS" if not bad else f"{len(bad)} problem(s)")
    raise SystemExit(1 if bad else 0)
