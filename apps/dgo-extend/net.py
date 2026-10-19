"""dgo-extend.net — the tunnel: what one office's WireGuard interface and firewall must be.

The model, in one paragraph
--------------------------
Every linked pair gets ONE /24 and ONE interface: the pair on slot N is `wgN` with `10.79.N.0/24`.
Inside the pair one side is `.1` and the other is `.2`, and WHICH is ours comes from the pair's own
record (`tunnel.side`) rather than from the fact that this office is the one rendering: the office
that renders is not always `.1` (an office that joined by pairing is side 2 — see
`ai/context/dgo-pairing-contract.md`). Link proxies (the local addresses that stand in for apps
running on the other office) take `.3` upward. The tunnel does NOT route subnets: a peer's
`AllowedIPs` is its own single address, and traffic for an app of the other office is a connection
from a local proxy to `10.79.N.<the other side>:<port>`. That is deliberate — routing subnets through
a tunnel is how one office's address plan leaks into another's, and a `/32` per peer is a rule that
cannot be misread.

Why an interface per pair, and not one interface with several peers (measured 2026-10-04, before the
first pairing existed): with two peers declared, the renderer refused — `same slot`; and when it was
told the pair's slot, it handed BOTH peers the same `.2` (`render(..., pair={"slot": 2, "side": 1})`
→ `peers: [{office: hp-laptop, address: 10.79.2.2}, {office: vps1, address: 10.79.2.2}]`). One /24
holds exactly two addresses; two pairs sharing an interface is one addressing plan with two owners.

Who renders it, and why here
----------------------------
The compiler cannot: WHICH offices are linked is a declaration in this app's volume, not a fact of
the catalogue it compiles. So the app renders the config from the declarations it owns, and the
compiler's part is only the container that applies it (declared in this app's own compose, with the
capabilities it needs).

Direction
---------
A link is directed: `use` means "this office may reach the other's apps", `serve` means "the other
may reach mine". The firewall is rendered from that, per direction, on BOTH sides — the receiving
side is the one that enforces it (`nftables` drops what the direction does not allow, whatever the
token says).
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
from pathlib import Path

import firewall  # the rules themselves: what ONE link allows, in ONE direction (DGO-21)

#: The PAIR's port: what the dialed end listens on and what the dialing end's `Endpoint` names. It is
#: part of the pair's published address (`<peer endpoint>:51820`), so it is a constant of the model,
#: not a local preference.
WG_PORT = 51820
#: This office's OWN listen port, `DGO_WG_PORT` (default: the pair's port). It exists because a
#: dialing office's source port is the one thing on the path it does not control, and a home
#: NAT/ISP can blackhole that one flow while every other flow from the same machine crosses fine.
#: Measured 2026-10-04 (vps1 ↔ macbook): the tunnel had counted ~7.8 KiB of handshake initiations as
#: sent, tcpdump on the office's own host showed each 148-byte initiation leaving as
#: `192.168.5.15.51820 > 31.97.196.82.51820`, the server's `tcpdump` and its ufw counter saw NONE of
#: them — while packets with the same 5-tuple and the same WireGuard shape, sent from the same
#: machine or another container, arrived. Re-applying the plan (fresh socket, same port) did not help;
#: `wg set wg0 listen-port 51830` brought the handshake back within 10 seconds. So the dialing side's
#: port must be changeable WITHOUT touching the dialed side's published port (and without touching
#: its firewall, which allows the pair's port by name).
def local_listen_port(dial: str, env: dict | None = None, own: int | str | None = None,
                      slot: int = 0) -> int:
    """The `ListenPort` for the side being rendered: `own` first, then `DGO_WG_PORT`, then the pair's.

    `own` is this side's port for THIS pair, out of the record that owns the pair (`tunnel.port` on a
    paired record). It is the first source because a pair that was created by pairing agreed a port
    explicitly (the joiner listens on the port the grant named), and a preference read out of the
    environment must not silently override an agreement two offices made with each other.

    Without `own`, the historical rule, unchanged: only the DIALING side may move. The document
    rendered for the far end keeps `WG_PORT` — it is the address this office dials, and a number that
    moves on one side only would be a link that stops handshaking with no error anywhere. The dialing
    side's own port is local, and that is exactly the one a home network can poison.
    """
    # ONE UDP PORT PER INTERFACE. WireGuard binds a socket per interface, so two pairs listening on
    # one port is `RTNETLINK answers: Address already in use` at the second interface and no tunnel on
    # it — measured 2026-10-04 on the first live pairing: `wg2` held 51830 and `wg4` could not come up,
    # while the address `10.79.4.2` was free (adding it to `lo` by hand succeeded, which is how the two
    # causes were told apart). The pair's slot is the number both ends already share, so the port is
    # derived from it and needs no allocation: `DGO_WG_PORT + slot`.
    if own not in (None, ""):
        try:
            port = int(own)
        except (TypeError, ValueError):
            raise NetError(f"הפורט של הזוג אינו מספר ({own!r})")
        if not 1 <= port <= 65535:
            raise NetError(f"הפורט של הזוג מחוץ לטווח 1–65535 ({port})")
        return port
    if dial == "remote":
        return WG_PORT
    raw = str((env if env is not None else os.environ).get("DGO_WG_PORT") or "").strip()
    try:
        base = int(raw)
    except ValueError:
        base = WG_PORT
    if not 1 <= base <= 65535:
        base = WG_PORT
    try:
        offset = int(slot or 0)
    except (TypeError, ValueError):
        offset = 0
    port = base + offset if 1 <= offset <= 254 else base
    return port if 1 <= port <= 65535 else base


#: Where the rendered files live inside the tunnel container.
DEFAULT_DIR = "/tunnel"


class NetError(RuntimeError):
    """Rendering refused, with the reason the operator can act on."""


def slot_of(office: dict) -> int:
    """The pair slot of an office — its /24. Refused rather than defaulted when it is missing: two
    offices that silently share a slot are two offices whose packets arrive at the wrong interface."""
    slot = ((office.get("tunnel") or {}).get("slot"))
    try:
        slot = int(slot)
    except (TypeError, ValueError):
        raise NetError(f"ללשכה {office.get('id')!r} אין slot מוצהר (tunnel.slot) — אי אפשר לרנדר מנהרה")
    if not 1 <= slot <= 254:
        raise NetError(f"slot {slot} של {office.get('id')!r} מחוץ לטווח 1–254")
    return slot


def pair_network(slot: int) -> str:
    return f"10.79.{slot}.0/24"


def iface_name(slot: int | str) -> str:
    """The interface of ONE pair, named from the pair's slot: slot 2 is `wg2`.

    Named from the slot rather than from a counter, for two reasons. A pair that is ADDED must not
    renumber the interface of a pair that is already up (a live link that goes down for a decision
    nobody made), and the slot is the one number both ends of the pair already agree about — so the
    interface a person sees in `wg show` on either end names the same pair.
    """
    try:
        slot = int(slot)
    except (TypeError, ValueError):
        raise NetError(f"slot {slot!r} אינו מספר — אין שם לממשק")
    if not 1 <= slot <= 254:
        raise NetError(f"slot {slot} מחוץ לטווח 1–254 — אין שם לממשק")
    return f"wg{slot}"


def pair_side(record: dict, default: int = 1) -> int:
    """Which end of its pair the OFFICE THAT HOLDS THIS FILE is — 1 or 2, from `tunnel.side`.

    The holder, not the peer: `side` and `role` describe the office on whose disk the record sits
    (contract §1 of `ai/context/dgo-pairing-contract.md`). Measured on the first real pairing
    2026-10-04: the HP holds `{slot: 3, side: 2, role: joiner, dial: host}` and reading that `side` as
    the PEER's side rendered it `self 10.79.3.1` — so the HP tried to dial the address of itself.

    Refused rather than defaulted when it is neither: `.1` is not "ours" any more than `.2` is.
    """
    raw = (record.get("tunnel") or {}).get("side")
    if raw in (None, ""):
        return int(default)
    try:
        side = int(raw)
    except (TypeError, ValueError):
        raise NetError(f"tunnel.side של {record.get('id')!r} אינו 1 או 2 ({raw!r})")
    if side not in (1, 2):
        raise NetError(f"tunnel.side של {record.get('id')!r} הוא {side} — בזוג יש שני צדדים, 1 ו־2")
    return side


def pair_role(record: dict) -> str:
    """The holder's role in the pair: `host`, `joiner`, or `""` for a record that has none (a
    declaration). See `holder_dials` for what the two words are for."""
    role = str((record.get("tunnel") or {}).get("role") or "").strip().lower()
    if role and role not in ("host", "joiner"):
        raise NetError(f"tunnel.role של {record.get('id')!r} אינו host או joiner ({role!r})")
    return role


def holder_dials(record: dict) -> bool:
    """Does the office that HOLDS this record start the handshake?

    For a PAIRED record the pair names which role dials (`tunnel.dial`, the same word on both sides)
    and the record names the holder's own role (`tunnel.role`), so the holder dials exactly when the
    two agree — contract §2. A record with a `dial` no role can answer (`dial: peer|home`, the
    declaration vocabulary) is not this function's question; `we_dial` answers that one.
    """
    dial = str((record.get("tunnel") or {}).get("dial") or "").strip().lower()
    role = pair_role(record)
    if dial not in ("host", "joiner") or not role:
        raise NetError(f"רשומת {record.get('id')!r}: dial={dial!r} ו-role={role!r} — "
                       f"זוג מצומד אומר מי מחייג (host|joiner) ומי הזאת (role)")
    return dial == role


def stale_tunnel_files(desired: dict, present) -> list:
    """Rendered files that must be DELETED: what a plan that shrank leaves behind.

    A tunnel file nobody applies is still a tunnel on the next apply, and that is how an unpaired
    office kept a live interface: `render_multi` writes the first pair ALSO as `wg0.conf` for readers
    written before pairs existed, and with NO pairs it writes nothing at all — so the old `wg0.conf`
    stayed, the applier's legacy fallback read it as "the single pair", and the interface came back up
    with the revoked peer's key, listening. Measured on hp-laptop 2026-10-04 (after `unpair`, `pairs[]`
    was empty and `wg0` was still up).

    `desired` is `render_multi`'s `files` map; `present` the names found in the volume.
    """
    keep = set(desired or {})
    out = []
    for name in present or []:
        name = str(name)
        if name in keep:
            continue
        if name == "wg0.conf" or name.startswith("pairs/"):
            out.append(name)
    return sorted(out)


def subject_dials(record: dict, side: int) -> bool:
    """Does the SUBJECT of this record start the handshake — for a DECLARATION, and only for one.

    A paired record is `holder_dials`'s question (its own `side`/`role` are the holder's); this one
    exists for the records that predate pairing, whose words are relative to the declared office.

    `dial` is relative to whoever the record is ABOUT, and the two vocabularies say so in different
    words:

    * a DECLARATION is written by the office that holds it ABOUT the peer, and its words are relative
      to that peer — `home` = the subject dials, `peer` = the subject's peer dials. Measured on the
      live pair: vps1's declaration says `dial: peer` while it is THIS office's `wg0.conf` that carries
      the `Endpoint`, so `peer` is us.
    * this office's OWN record (`home.json`) speaks the same words about itself: `home` = we dial.
    * a PAIRED record says which END dials (`host` = side 1, `joiner` = side 2), so the subject dials
      when it is the named end.

    One question, asked once: "who dials" decided in two places is how a pair ends up with two ends
    that both wait or both dial.
    """
    raw = str((record.get("tunnel") or {}).get("dial") or "").strip().lower()
    if raw in ("", "home"):
        return True
    if raw == "peer":
        return False
    if raw in ("host", "joiner"):
        return int(side) == (1 if raw == "host" else 2)
    if raw == "relay":
        raise NetError("זוג שבנוי על מתווך (relay) — רינדור כזה טרם ממומש (תכנית ב׳)")
    raise NetError(f"dial {raw!r} אינו home / peer / host / joiner / relay")


def we_dial(peer_record: dict, our_side: int) -> bool:
    """Does THIS office dial the pair described by a PEER's record? The mirror of the record's own
    answer, and the question a caller actually has: the record's subject is the peer, not us."""
    side = pair_side(peer_record, default=2) if (peer_record.get("kind") or "") == "paired" else 2
    return not subject_dials(peer_record, side)


def _port(value, default: int, what: str) -> int:
    """A UDP port out of a record, or the default. Refused rather than clamped: a wrong port that
    becomes 51820 silently is a link that dials the wrong place and reports nothing."""
    if value in (None, ""):
        return int(default)
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise NetError(f"{what} אינו מספר ({value!r})")
    if not 1 <= port <= 65535:
        raise NetError(f"{what} מחוץ לטווח 1–65535 ({port})")
    return port


def _key(identity: dict | None) -> str:
    """The WireGuard public key, from EITHER shape an identity travels in: the full document the
    minting machine keeps (`wg: {public, private}`) or the public half that crosses the wire
    (`wg: "<base64>"`, identity.public()). Supporting only one of them is how a link renders on one
    side and refuses on the other."""
    wg = (identity or {}).get("wg")
    if isinstance(wg, dict):
        return wg.get("public", "")
    return wg or ""


def link_direction(link: dict) -> str:
    d = (link or {}).get("direction") or "use"
    return d if d in ("use", "serve", "both") else "use"


def endpoint_address(endpoint: str, resolve=socket.getaddrinfo) -> str:
    """The dialed end as an ADDRESS: a name is resolved HERE, when the pair is rendered.

    `wg` resolves an `Endpoint` name once, when the configuration is applied, inside the tunnel
    container. A name with no record makes `wg-quick up` fail there; the applier logs it and carries
    on, and the office runs with no tunnel (2026-10-04: `staging.digital-office.co.il`, an apex with
    no A record under a wildcard that resolves at every depth below it). So the name is asked about
    where a refusal can be READ — the render answers with this sentence and writes nothing — and
    what is written is the address, which no later lookup can fail on. The declared name stays what
    the screens show (`addressing.endpoint`)."""
    try:
        ipaddress.ip_address(endpoint)
        return endpoint
    except ValueError:
        pass
    try:
        family, *_rest, addr = resolve(endpoint, None, type=socket.SOCK_DGRAM)[0]
    except (OSError, IndexError):
        raise NetError(f"לשם {endpoint!r} אין רשומת DNS, ולכן אי אפשר לחייג אליו. הוסיפו לו רשומת A, "
                       "או הצהירו על כתובת IP כקצה המנהרה (tunnel.endpoint)") from None
    return f"[{addr[0]}]" if family == socket.AF_INET6 else addr[0]


def lan_address(host: str) -> bool:
    """Is this an address a ROUTER hands out — i.e. one that can move without anybody deciding?

    The distinction is the whole safety of looking for a peer: a private IPv4 belongs to a home/office
    LAN, where DHCP renumbers a machine after a reconnect (measured 2026-10-07: hp-laptop's Wi-Fi came
    back as `192.168.16.100` while its pair still said `192.168.16.102`), and only its own /24 is a
    sane place to look. A public address or a NAME is a decision somebody made; it is never scanned.
    """
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.version == 4 and addr.is_private


def dialable_from_here(peer_endpoint: str, own_endpoint: str = "") -> bool:
    """Can an office that publishes `own_endpoint` reach `peer_endpoint`?

    A NAME or a public address is a decision somebody made and stands: it is an address anybody can
    dial. A PRIVATE address belongs to one LAN, and the only office that can dial it is one that is
    (or can be) on that network — so a peer's private address is dialable from here only when this
    office declares a private address of its own. An office that publishes a public endpoint is not
    on anybody's LAN.

    This is the question a pairing never asked, and a pair written without it is born dead: measured
    2026-10-12 on vps1 (lnk-032), the HP — at home, behind its NAT — published `192.168.16.100`, this
    office, a server at a public address, was made the DIALER, and 8.4 KiB of handshake initiations
    went into a private address no packet from here can reach, with every screen reporting a pair.
    Reachability is a fact of the PAIR, not of either office: the very same HP address is exactly
    right for the MacBook beside it at home (lnk-017) and impossible for a cloud office.

    `own_endpoint == ""` keeps the historical answer: an office that declared nothing (the macOS
    engine — nothing inbound is possible there) can only dial, and its peer's address, private or
    not, is the only address there is.
    """
    peer = str(peer_endpoint or "").strip().lower()
    if not peer:
        return False
    if not lan_address(peer):
        return True
    own = str(own_endpoint or "").strip().lower()
    return not own or lan_address(own)


def peer_candidates(address: str, limit: int = 128) -> list[str]:
    """Where a moved peer is looked for: its last known /24, NEAREST FIRST, bounded.

    A DHCP pool is contiguous, so the neighbours of the address the pair remembers are where the
    machine is — not the far end of the /24 — and the bound is what keeps a search honest: a few
    thousand probes and a blocked projection timer is not a repair. `limit` counts candidates, and
    the last known address is NOT one of them (it was just measured as answering nothing).
    """
    try:
        addr = ipaddress.ip_address(address)
    except ValueError:
        return []
    if addr.version != 4:
        return []
    net = ipaddress.ip_network(f"{addr}/24", strict=False)
    last = int(str(addr).split(".")[-1])
    hosts = [h for h in net.hosts()]                       # .1 … .254, network/broadcast excluded
    ordered = sorted(hosts, key=lambda h: (abs(int(str(h).split(".")[-1]) - last),
                                           int(str(h).split(".")[-1])))
    return [str(h) for h in ordered if str(h) != str(addr)][:max(0, int(limit))]


def pair_conf(pair: dict) -> dict:
    """ONE pair's rendered half: its `wg` document, its addressing entry and its firewall peer.

    A pair is DESCRIBED by the caller, never guessed here:

        {"slot": 2, "side": 1, "dial": "home",
         "listen_port": 51830,                  # OUR port in this pair (None → the historical rule)
         "ports": {"drive": 8975},              # what the PEER may reach here (the firewall's list)
         "peer": {"office": "vps1", "public_key": "…", "endpoint": "31.97.196.82",
                  "endpoint_port": 51820, "direction": "both", "address": None}}

    `dial` is which end starts the handshake — `home` means the side this document belongs to dials
    (it sets `Endpoint` and a keepalive), `remote` means the far end dials and this side only listens.
    It is a fact of the pair, not a preference: the side that can be reached is the side that gets
    dialed, and the side whose one source port a NAT can blackhole is the side that must be able to
    move its own port (`local_listen_port`).

    `peer.address` overrides the peer's address inside the pair's /24. It exists for the historical
    render, where a peer's address was derived from the PEER's own slot (`10.79.<peer slot>.2`) — a
    shape older records still carry. Everything new leaves it out and gets the pair's other side.
    """
    slot = int(pair.get("slot") or 0)
    if not 1 <= slot <= 254:
        raise NetError(f"slot {slot} של הזוג מחוץ לטווח 1–254")
    side = int(pair.get("side") or 1)
    if side not in (1, 2):
        raise NetError(f"side {side} של הזוג אינו 1 או 2")
    dial = pair.get("dial") or "home"
    if dial not in ("home", "remote"):
        raise NetError(f"dial {dial!r} אינו home או remote")
    peer = pair.get("peer") or {}
    pid = peer.get("office") or ""
    pkey = peer.get("public_key") or ""
    if not pkey:
        raise NetError(f"אין מפתח WireGuard ציבורי ללשכה {pid!r} — "
                       f"קרא אותו ב-`bbox dgo identity --office {pid}`")
    mine = f"10.79.{slot}.{side}"
    other = str(peer.get("address") or f"10.79.{slot}.{3 - side}")
    listen = local_listen_port(dial, own=pair.get("listen_port"), slot=slot)
    endpoint = str(peer.get("endpoint") or "").strip()
    endport = _port(peer.get("endpoint_port"), WG_PORT, f"פורט הקצה של {pid!r}")
    direction = link_direction({"direction": peer.get("direction")})
    iface = iface_name(slot)
    lines = ["# GENERATED by dgo-extend/net.py from the declarations this office owns — DO NOT EDIT.",
             "# ONE interface per PAIR: slot %d, %s, this side holds %s." % (slot, pair_network(slot), mine),
             "# One [Peer] per link; AllowedIPs is that office's single tunnel address, because app",
             "# traffic goes through a local proxy rather than through routed subnets.",
             "[Interface]", "Address = %s/24" % mine,
             "ListenPort = %d" % listen, "PrivateKey = @PRIVATE@",
             "", "[Peer]", "# %s (%s)" % (pid, direction),
             "PublicKey = %s" % pkey, "AllowedIPs = %s/32" % other]
    # Which side dials: the one that can reach. The other side needs PersistentKeepalive, or its NAT
    # mapping expires and the link goes quiet without anybody touching it.
    if dial == "home" and endpoint:
        lines += ["Endpoint = %s:%d" % (endpoint_address(endpoint), endport), "PersistentKeepalive = 25"]
    return {
        "iface": iface, "file": f"pairs/{iface}.conf", "slot": slot, "side": side, "dial": dial,
        "self": mine, "peer": other, "listen_port": listen,
        "wg": "\n".join(lines) + "\n",
        "addressing": {"office": pid, "iface": iface, "slot": slot, "side": side, "self": mine,
                       "peer": other, "network": pair_network(slot), "public_key": pkey,
                       "endpoint": endpoint or None, "endpoint_port": endport, "dial": dial,
                       "direction": direction},
        "legacy_peer": {"office": pid, "address": other, "public_key": pkey,
                        "endpoint": endpoint or None},
        # The firewall is rendered from the SAME two facts the [Peer] block is: this address, and the
        # direction of this link. Permission is not a second opinion about the tunnel — it is the same
        # declaration, asked the other question ("what may arrive", not "how do I reach it").
        "firewall_peer": {"office": pid, "address": other, "direction": direction, "iface": iface,
                          "ports": pair.get("ports") or {}},
    }


def render_multi(pairs: list[dict], host_forward: bool = False) -> dict:
    """Every pair this office holds, rendered together: one `wg` document per pair, ONE firewall.

    Nothing here touches the disk — the caller writes what this returns:

        {"pairs": [{"iface", "file", "slot", "side", "dial", "self", "peer", "listen_port"}],
         "files": {"pairs/wg2.conf": "…", "pairs/wg3.conf": "…", "wg0.conf": "…"},
         "nftables": "…", "guard": {…}, "addressing": {…}}

    `addressing` carries the new `pairs[]` list AND, for the FIRST pair, the keys a reader written
    before pairs existed still looks for (`slot`/`self`/`network`/`peers`). That is a rendering
    compatibility, not a second model: an office that already holds a live link is read by whatever
    code is running on its far end until that end is updated, and a plan that arrives in a shape the
    reader does not know is an outage at the far end (`projection.ADDRESS_READER`, `_pair_slot`).
    New code reads `pairs[]` and never the legacy keys.

    A pair MUST be unique per slot and per peer: two pairs on one slot would render two interfaces
    claiming one /24 — the exact failure this layout exists to remove — so it is refused here rather
    than left to the kernel.
    """
    rendered = [pair_conf(p) for p in (pairs or [])]
    seen_slots, seen_peers = {}, {}
    for r in rendered:
        if r["slot"] in seen_slots:
            raise NetError(f"שני זוגות על אותו slot ({r['slot']}) — לכל זוג /24 משלו")
        seen_slots[r["slot"]] = r["iface"]
        pid = r["addressing"]["office"]
        if pid and pid in seen_peers:
            raise NetError(f"לשכה {pid!r} מוצהרת פעמיים — זוג אחד לכל עמית")
        seen_peers[pid] = r["iface"]
    fw_peers = [r["firewall_peer"] for r in rendered]
    addressing = {"pairs": [r["addressing"] for r in rendered]}
    files = {r["file"]: r["wg"] for r in rendered}
    if rendered:
        first = rendered[0]["addressing"]
        addressing.update({"slot": first["slot"], "self": first["self"],
                           "network": first["network"], "ifaces": [r["iface"] for r in rendered],
                           "peers": [r["legacy_peer"] for r in rendered]})
        # The first pair is ALSO written under the name every reader used before pairs existed. A file
        # nothing applies is not a tunnel — the applier only ever brings up `pairs/*.conf` (see
        # tunnel-entrypoint.sh) — but a plan an older reader can still read is the difference between
        # an update and an outage.
        files["wg0.conf"] = rendered[0]["wg"]
    return {"pairs": [{k: r[k] for k in ("iface", "file", "slot", "side", "dial", "self", "peer",
                                         "listen_port")} for r in rendered],
            "files": files,
            "nftables": firewall.nft_document(fw_peers,
                                              forward_policy="accept" if host_forward else "drop"),
            "guard": firewall.guard(fw_peers),
            "addressing": addressing}


def render(office: dict, peers: list[dict], identities: dict | None = None,
           app_ports: dict | None = None, pair: dict | None = None,
           host_forward: bool = False) -> dict:
    """The tunnel files for ONE PAIR of ONE office — the single-pair render every caller still uses.

    `office` is the side this document belongs to, `peers` the declaration(s) it is linked to in either
    direction, `identities` a mapping office id → public identity (from `bbox dgo identity`), and
    `app_ports` a mapping office id → {app: port} for the apps that office serve()s.

    `host_forward` says this document is applied in a MACHINE's network namespace rather than in the
    tunnel's own container, where the `forward` hook also carries Docker's traffic: the rendered
    firewall then leaves forwarding alone except for the link's own packets. The dialed end of a pair
    is exactly that case (`step_link` ships the peer document for `wg-quick` on the host), and getting
    it wrong closes every published port on that machine (`firewall.nft_document` has the measurement).

    `pair` renders THE SAME PAIR from the other end: `{"slot": N, "side": 2, "dial": "remote"}` pins
    the pair's one /24 and which end of it this config belongs to. It exists because a pair has ONE
    /24 and both ends must agree about it: rendered by itself, the second office would claim `.1` for
    its own address, and every packet would then arrive from an address the other side's `AllowedIPs`
    does not contain — a tunnel that handshakes and passes nothing. So the end that can dial allocates
    the slot and renders BOTH ends (see converge.step_link), and the peer only applies what it is
    handed.

    An office with SEVERAL links is not this function: it is `render_multi`, which gives each pair its
    own interface. Passing more than one peer here is refused rather than rendered into one interface
    with two owners.
    """
    identities = identities or {}
    app_ports = app_ports or {}
    pair = pair or {}
    oid = office.get("id") or "office"
    if len(peers or []) > 1:
        raise NetError("render() מרנדר זוג אחד; ללשכה עם כמה קישורים קרא ל-render_multi()")
    own_key = _key(identities.get(oid))
    if not own_key:
        raise NetError(f"אין מפתח WireGuard ציבורי ללשכה {oid} — הרץ `bbox dgo identity` על המכונה שלה")
    side = int(pair.get("side") or pair_side(office))
    if pair.get("slot"):
        slot = int(pair["slot"])
    else:
        slot = slot_of(office)
    if pair.get("dial"):
        dial = pair["dial"]
    else:
        dial = "home" if subject_dials(office, side) else "remote"
    peer = (peers or [{}])[0]
    pid = peer.get("id") or ""
    pkey = _key(identities.get(pid)) if pid else ""
    if not pkey:
        raise NetError(f"אין מפתח WireGuard ציבורי ללשכה {pid} — "
                       f"קרא אותו ב-`bbox dgo identity --office {pid}`")
    pslot = slot_of(peer)
    if not pair.get("slot") and pslot == slot:
        raise NetError(f"ללשכה {pid} יש אותו slot ({slot}) כמו ללשכה הזו — כל צד חייב slot משלו")
    p_endpoint = (peer.get("tunnel") or {}).get("endpoint") or ""
    conf = pair_conf({
        "slot": slot, "side": side, "dial": dial,
        "listen_port": pair.get("listen_port"),
        "ports": app_ports.get(pid) or {},
        "peer": {"office": pid, "public_key": pkey,
                 # A peer rendered without a pinned pair keeps the historical address: its OWN slot's
                 # `.2`. It is the same number as the pair's other side whenever the two records agree
                 # about the slot, which is what pins a pair in the first place.
                 "address": None if pair.get("slot") else f"10.79.{pslot}.2",
                 "endpoint": p_endpoint,
                 "endpoint_port": (peer.get("tunnel") or {}).get("port"),
                 "direction": _link_between(office, pid).get("direction")
                              or (pair.get("direction") or "use")},
    })
    return {"wg": conf["wg"],
            "nftables": firewall.nft_document([conf["firewall_peer"]],
                                              forward_policy="accept" if host_forward else "drop"),
            "guard": firewall.guard([conf["firewall_peer"]]),
            "addressing": {"slot": conf["slot"], "self": conf["self"],
                           "network": pair_network(conf["slot"]),
                           "peers": [conf["legacy_peer"]],
                           "pairs": [conf["addressing"]]},
            "iface": conf["iface"], "file": conf["file"],
            "endpoint": conf["addressing"]["endpoint"] or "", "listen_port": WG_PORT}


def _link_between(office: dict, peer_id: str) -> dict:
    for link in (office.get("links") or []):
        if (link or {}).get("office") == peer_id or (link or {}).get("id") == peer_id:
            return link
    return {}


def naming_fingerprint(office: dict, peers: list[dict]) -> str:
    """A short digest of the rendered peer set — what a converge compares to know whether the tunnel
    it applied is still the tunnel the declarations describe."""
    material = json.dumps([[p.get("id"), slot_of(p)] for p in sorted(peers, key=lambda x: x.get("id") or "")]
                          + [slot_of(office)], sort_keys=True)
    return hashlib.sha256(material.encode()).hexdigest()[:12]


def selftest() -> list[str]:
    """Render a two-office example and check the decisions this module makes. Run by the phase-1
    gate; needs no machine, no docker and no tunnel — which is the point of keeping the rendering
    separate from applying it."""
    problems = []
    home = {"id": "home", "tunnel": {"slot": 3, "dial": "home", "endpoint": ""},
            "links": [{"office": "vps1", "direction": "use"}]}
    vps1 = {"id": "vps1", "tunnel": {"slot": 2, "dial": "peer", "endpoint": "31.97.196.82"},
            "links": [{"office": "home", "direction": "serve"}]}
    ids = {"home": {"wg": {"public": "HOMEKEY="}}, "vps1": {"wg": {"public": "VPSKEY="}}}
    doc = render(home, [vps1], ids, {"vps1": {"drive": 8975}})
    if "Address = 10.79.3.1/24" not in doc["wg"]:
        problems.append("this side must be .1 of its own /24")
    if "AllowedIPs = 10.79.2.2/32" not in doc["wg"]:
        problems.append("a peer's AllowedIPs is its single address, not a subnet")
    if "Endpoint = 31.97.196.82:51820" not in doc["wg"] or "PersistentKeepalive = 25" not in doc["wg"]:
        problems.append("the dialing side sets the endpoint and a keepalive")
    # The dialing side's OWN port may move (a home NAT can blackhole one source port while every
    # other flow crosses) — and ONLY the dialing side: the far end's port is the address we dial.
    if local_listen_port("home", {"DGO_WG_PORT": "51830"}) != 51830:
        problems.append("the dialing side honours DGO_WG_PORT")
    if local_listen_port("remote", {"DGO_WG_PORT": "51830"}) != WG_PORT:
        problems.append("the dialed side keeps the pair's port — it is the address we dial")
    if local_listen_port("home", {"DGO_WG_PORT": "nonsense"}) != WG_PORT:
        problems.append("a malformed DGO_WG_PORT falls back to the pair's port")
    _prev = os.environ.get("DGO_WG_PORT")
    os.environ["DGO_WG_PORT"] = "51830"
    try:
        moved = render(home, [vps1], ids, {"vps1": {"drive": 8975}})
        moved_far = render(vps1, [home], {"home": {"wg": {"public": "HOMEKEY="}}, "vps1": ids["vps1"]},
                           {"home": {"drive": 8975}}, pair={"slot": 3, "side": 2, "dial": "remote"})
    finally:
        os.environ.pop("DGO_WG_PORT", None)
        if _prev is not None:
            os.environ["DGO_WG_PORT"] = _prev
    if "ListenPort = 51833" not in moved["wg"]:
        problems.append("a rendered dialing document carries DGO_WG_PORT + the pair's slot")
    if "ListenPort = %d" % WG_PORT not in moved_far["wg"]:
        problems.append("the document handed to the far end never carries our local port")
    if "10.79.2.2 tcp dport 8975 accept" in doc["nftables"]:
        problems.append("a `use` link must not open a port for the peer (direction is enforced here)")
    if 'ip saddr 10.79.2.2 drop' not in doc["nftables"]:
        problems.append("a `use` link must DROP what arrives from the peer, not merely not allow it")
    if doc["guard"]["sources"]:
        problems.append("a `use` peer may not arrive, so it opens no door on this edge")
    served = render(vps1, [home], {"home": {"wg": {"public": "HOMEKEY="}}, "vps1": ids["vps1"]},
                    {"home": {"drive": 8975}})
    if 'ip saddr 10.79.3.2 tcp dport 8975 accept   # drive' not in served["nftables"]:
        problems.append("a `serve` link opens exactly the served app ports")
    if "ip saddr 10.79.3.2 drop" not in served["nftables"]:
        problems.append("and drops everything else from that peer")
    if served["guard"]["rule"] != "ClientIP(`10.79.3.2/32`)":
        problems.append("a `serve` link guards its door with the caller's tunnel address")
    try:
        render(home, [{"id": "clash", "tunnel": {"slot": 3}}], ids)
        problems.append("two offices on the same slot must be refused")
    except NetError:
        pass
    try:
        render(home, [{"id": "nokey", "tunnel": {"slot": 4}}], ids)
        problems.append("a peer without a WireGuard key must be refused")
    except NetError:
        pass

    # ── several pairs, one interface each (2026-10-04) ────────────────────────────────────────────
    # Two pairs must each get their own interface, their own /24 and their own address for us: the
    # whole reason this is a list and not "one office, one tunnel".
    multi = render_multi([
        {"slot": 2, "side": 1, "dial": "home", "ports": {"drive": 8975},
         "peer": {"office": "vps1", "public_key": "VPSKEY=", "endpoint": "31.97.196.82",
                  "endpoint_port": 51820, "direction": "both"}},
        {"slot": 3, "side": 1, "dial": "home",
         "peer": {"office": "hp-laptop", "public_key": "HPKEY=", "endpoint": "192.168.16.102",
                  "endpoint_port": 51999, "direction": "use"}},
    ])
    if sorted(multi["files"]) != ["pairs/wg2.conf", "pairs/wg3.conf", "wg0.conf"]:
        problems.append(f"two pairs must render one file per interface, got {sorted(multi['files'])}")
    wg2, wg3 = multi["files"]["pairs/wg2.conf"], multi["files"]["pairs/wg3.conf"]
    if "Address = 10.79.2.1/24" not in wg2 or "Address = 10.79.3.1/24" not in wg3:
        problems.append("each pair's interface must hold its OWN /24")
    if "AllowedIPs = 10.79.2.2/32" not in wg2 or "AllowedIPs = 10.79.3.2/32" not in wg3:
        problems.append("each pair's peer must be the other side of ITS /24 (not 10.79.2.2 twice)")
    if "Endpoint = 192.168.16.102:51999" not in wg3:
        problems.append("the peer's port comes from the record, not from the WG_PORT constant")
    _base = int(os.environ.get("DGO_WG_PORT") or WG_PORT)
    for _conf, _slot in ((wg2, 2), (wg3, 3)):
        if f"ListenPort = {_base + _slot}" not in _conf:
            problems.append(f"pair slot {_slot} must listen on {_base + _slot}, got "
                            f"{[l for l in _conf.splitlines() if l.startswith('ListenPort')]}")
    if multi["files"]["wg0.conf"] != wg2:
        problems.append("the first pair is also written under the legacy name, for older readers")
    if multi["addressing"]["slot"] != 2 or multi["addressing"]["self"] != "10.79.2.1":
        problems.append("the legacy addressing keys must describe the FIRST pair, unchanged")
    if [p["iface"] for p in multi["addressing"]["pairs"]] != ["wg2", "wg3"]:
        problems.append("addressing must carry every pair, with its interface")
    if "iifname { \"wg2\", \"wg3\" } oifname { \"wg2\", \"wg3\" } drop" not in multi["nftables"]:
        problems.append("the firewall must police every pair's interface")
    # The same pair, from the JOINING end: we are `.2`, the peer is `.1`, and we do not dial.
    joiner = render_multi([{"slot": 3, "side": 2, "dial": "remote", "listen_port": 51999,
                            "peer": {"office": "macbook", "public_key": "HOMEKEY=",
                                     "endpoint": "79.177.165.212", "endpoint_port": 51830,
                                     "direction": "serve"}}])["files"]["pairs/wg3.conf"]
    if "Address = 10.79.3.2/24" not in joiner or "AllowedIPs = 10.79.3.1/32" not in joiner:
        problems.append("an office that joined as side 2 holds .2 and reaches .1")
    if "Endpoint" in joiner:
        problems.append("the side that does NOT dial must set no endpoint — its peer dials it")
    if "ListenPort = 51999" not in joiner:
        problems.append("the listening side keeps the port the pairing agreed, not the pair's default")
    # Two pairs on one slot, or one peer twice: refused here rather than by the kernel.
    for bad, why in (([{"slot": 2, "side": 1, "peer": {"office": "a", "public_key": "K="}},
                       {"slot": 2, "side": 1, "peer": {"office": "b", "public_key": "K="}}],
                      "two pairs on one slot"),
                     ([{"slot": 2, "side": 1, "peer": {"office": "a", "public_key": "K="}},
                       {"slot": 3, "side": 1, "peer": {"office": "a", "public_key": "K="}}],
                      "one peer declared twice"),
                     ([{"slot": 0, "side": 1, "peer": {"office": "a", "public_key": "K="}}],
                      "slot 0"),
                     ([{"slot": 2, "side": 3, "peer": {"office": "a", "public_key": "K="}}],
                      "side 3"),
                     ([{"slot": 2, "side": 1, "peer": {"office": "a"}}],
                      "a pair without the peer's key")):
        try:
            render_multi(bad)
            problems.append(f"{why} must be refused")
        except NetError:
            pass
    try:
        render(home, [vps1, {"id": "second", "tunnel": {"slot": 5}}], ids)
        problems.append("render() must refuse several peers — that is render_multi's job")
    except NetError:
        pass

    # ── the SAME PAIR from BOTH ends (contract §1–§3) ─────────────────────────────────────────────
    # Two records, one per office, both naming the LISTENER's address (§3 — the same value in both),
    # each naming its OWN side and role (§1). Rendered they must be a mirror of each other: each side's
    # own address is the other side's peer address, each `AllowedIPs` is the other's own address, and
    # the `Endpoint` appears on the DIALING side alone.
    #
    # This is the shape that was measured wrong on the first real pairing (2026-10-04): the HP holds
    # `{side: 2, role: joiner, dial: host}` and reading `side` as the PEER's end rendered it as `.1`
    # with the endpoint of ITSELF — a machine dialing its own address, and no error anywhere.
    host_rec = {"id": "macbook", "kind": "paired",
                "tunnel": {"slot": 3, "side": 1, "role": "host", "dial": "host",
                           "endpoint": "192.168.16.102", "port": 51830, "listen_port": None}}
    join_rec = {"id": "hp-laptop", "kind": "paired",
                "tunnel": {"slot": 3, "side": 2, "role": "joiner", "dial": "host",
                           "endpoint": "192.168.16.102", "port": 51830, "listen_port": 51830}}
    if pair_side(host_rec) != 1 or pair_side(join_rec) != 2:
        problems.append("`side` is the HOLDER's end of the pair, not the peer's")
    if not holder_dials(host_rec) or holder_dials(join_rec):
        problems.append("with `dial: host` the host dials and the joiner only listens")

    def own_document(rec, peer_id):
        dials = holder_dials(rec)
        return pair_conf({"slot": 3, "side": pair_side(rec),
                          "dial": "home" if dials else "remote",
                          "listen_port": rec["tunnel"]["listen_port"],
                          "peer": {"office": peer_id, "public_key": "PEERKEY=",
                                   "endpoint": rec["tunnel"]["endpoint"] if dials else "",
                                   "endpoint_port": rec["tunnel"]["port"], "direction": "both"}})

    mac = own_document(host_rec, "hp-laptop")
    hp = own_document(join_rec, "macbook")
    if (mac["self"], mac["peer"]) != ("10.79.3.1", "10.79.3.2"):
        problems.append(f"the host holds .1 and reaches .2, got {mac['self']} → {mac['peer']}")
    if (hp["self"], hp["peer"]) != ("10.79.3.2", "10.79.3.1"):
        problems.append(f"the joiner holds .2 and reaches .1, got {hp['self']} → {hp['peer']}")
    if "AllowedIPs = 10.79.3.2/32" not in mac["wg"] or "AllowedIPs = 10.79.3.1/32" not in hp["wg"]:
        problems.append("each end's AllowedIPs must be the OTHER end's address — a mirror, not a copy")
    if "Endpoint = 192.168.16.102:51830" not in mac["wg"]:
        problems.append("the dialing side carries the LISTENER's address and port (§3)")
    if "Endpoint" in hp["wg"]:
        problems.append("the side being dialed writes no Endpoint at all")
    if "ListenPort = 51830" not in hp["wg"]:
        problems.append("the side being dialed listens on its `tunnel.listen_port`")
    if "PersistentKeepalive" not in mac["wg"] or "PersistentKeepalive" in hp["wg"]:
        problems.append("the dialing side keeps the mapping alive; the listening side has nothing to keep")
    for bad, why in (( {"id": "x", "kind": "paired", "tunnel": {"slot": 3, "side": 1, "role": "peer",
                                                                "dial": "host"}},
                      "a role that is neither host nor joiner"),
                     ({"id": "x", "kind": "paired", "tunnel": {"slot": 3, "side": 1, "role": "host",
                                                               "dial": "peer"}},
                      "a paired record with the declaration vocabulary in `dial`")):
        try:
            holder_dials(bad)
            problems.append(f"{why} must be refused")
        except NetError:
            pass

    # A NAMED endpoint is written as the address it resolves to, and one with no record is refused
    # in words — where `wg-quick` would have failed it in a log nobody reads.
    def names(host, *_a, **_k):
        if host == "office.example":
            return [(socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("203.0.113.7", 0))]
        if host == "six.example":
            return [(socket.AF_INET6, socket.SOCK_DGRAM, 17, "", ("2001:db8::7", 0, 0, 0))]
        raise socket.gaierror(-2, "Name or service not known")
    if (endpoint_address("31.97.196.82", names), endpoint_address("office.example", names),
            endpoint_address("six.example", names)) != ("31.97.196.82", "203.0.113.7", "[2001:db8::7]"):
        problems.append("an address stays itself, a name becomes its address, an IPv6 one is bracketed")
    try:
        endpoint_address("apex.example", names)
        problems.append("a name with no DNS record must be refused")
    except NetError as e:
        if "apex.example" not in str(e) or "רשומת A" not in str(e):
            problems.append(f"the refusal names the name and the record to add, got: {e}")

    # The vocabulary translation, one place: who dials, asked of a declaration (`home|peer`) and of a
    # paired record (`host|joiner`) alike.
    if subject_dials({}, 1) is not True or subject_dials({"tunnel": {"dial": "peer"}}, 2) is not False:
        problems.append("a record with no dial, or `dial: home`, means its subject dials; `peer` does not")
    if subject_dials({"tunnel": {"dial": "host"}}, 1) is not True \
            or subject_dials({"tunnel": {"dial": "host"}}, 2) is not False:
        problems.append("`dial: host` is 'side 1 dials' — so the joiner (side 2) is dialed, not dialing")
    if we_dial({"id": "vps1", "tunnel": {"slot": 2, "dial": "peer"}}, 1) is not True:
        problems.append("a declaration that says `peer` means the far side dials, so WE dial")
    if we_dial({"id": "hp", "kind": "paired", "tunnel": {"slot": 3, "side": 1, "dial": "host"}}, 2) \
            is not False:
        problems.append("a paired record naming the host as dialer means the joiner does not dial")
    for bad in ("relay", "sideways"):
        try:
            subject_dials({"tunnel": {"dial": bad}}, 1)
            problems.append(f"dial {bad!r} must be refused, not silently rendered")
        except NetError:
            pass
    # PAIR -> UNPAIR (2026-10-04): with no pairs nothing may be left for the applier to bring up.
    if stale_tunnel_files({}, ["wg0.conf", "pairs/wg9.conf", "nftables.rules", "addressing.json"]) \
            != ["pairs/wg9.conf", "wg0.conf"]:
        problems.append("an empty plan must retire wg0.conf and every pair's file, and nothing else")
    if stale_tunnel_files({"pairs/wg2.conf": "x", "wg0.conf": "x"},
                          ["wg0.conf", "pairs/wg2.conf", "pairs/wg9.conf"]) != ["pairs/wg9.conf"]:
        problems.append("a pair that is still declared must not be retired by a re-render")
    if stale_tunnel_files({"pairs/wg2.conf": "x"}, ["wg0.conf"]) != ["wg0.conf"]:
        problems.append("the legacy copy goes when the pair it copied is no longer first/alone")
    # LOOKING FOR A PEER WHOSE ADDRESS MOVED (2026-10-07). Only a LAN address is ever searched, the
    # search is nearest-first (a DHCP pool is contiguous) and it is bounded, and the address that was
    # just measured as dead is not offered back.
    if not lan_address("192.168.16.102") or not lan_address("10.79.4.1") or lan_address("31.97.196.82"):
        problems.append("a LAN address is searchable, a public one is not")
    if lan_address("staging.digital-office.co.il"):
        problems.append("a name is never scanned — it is a decision, not a DHCP lease")
    first = peer_candidates("192.168.16.102", limit=6)
    if first[:3] != ["192.168.16.101", "192.168.16.103", "192.168.16.100"]:
        problems.append(f"the search must start beside the address that was lost, not at .1: {first}")
    if "192.168.16.102" in peer_candidates("192.168.16.102"):
        problems.append("the address that just answered nothing is not a candidate")
    if len(peer_candidates("192.168.16.102")) > 254 or peer_candidates("192.168.16.102", 0):
        problems.append("the search is bounded by its limit and never empty by default")
    if peer_candidates("") or peer_candidates("vps.example.org"):
        problems.append("a candidate list exists only for an address")
    # WHO CAN DIAL WHOM (2026-10-12, lnk-032). A public office dials anything but a private address;
    # a private (LAN) office may dial a private address — possibly the next /24 over — and an office
    # that declared nothing dials whatever address it was given.
    if not dialable_from_here("31.97.196.82", "") or not dialable_from_here("console.example.org", ""):
        problems.append("a public address or a name is dialable by anybody")
    if dialable_from_here("192.168.16.100", "31.97.196.82") \
            or dialable_from_here("192.168.16.100", "console.staging.example"):
        problems.append("a public office can never dial a private address — the pair must be the other way")
    if not dialable_from_here("192.168.16.100", "192.168.5.15") \
            or not dialable_from_here("192.168.16.100", ""):
        problems.append("a LAN office dials a private address (another /24 of the same home is still "
                        "reachable), and an office that declared nothing dials the only address it has")
    if dialable_from_here("", "10.0.0.1"):
        problems.append("no address is not an address to dial")
    return problems


if __name__ == "__main__":
    bad = selftest()
    for b in bad:
        print("FAIL", b)
    print("net.py selftest:", "PASS" if not bad else f"{len(bad)} problem(s)")
    raise SystemExit(1 if bad else 0)
