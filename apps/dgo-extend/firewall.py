"""dgo-extend.firewall — what ONE link allows, rendered from the declaration, enforced where the
packet ARRIVES.

Decision 9 of `ai/context/dgo-extend-plan.md` in one sentence: **a token proves who is calling, not
what they may do** — so the direction of a link is enforced on the RECEIVING side, in the tunnel
container's firewall and in the edge's router rules, and never by trusting the caller.

Two appliers, one renderer
--------------------------
`net.py` decides ADDRESSING (which /24, which side is `.1`, who dials); this module decides
PERMISSION (what may cross, from whom, to where). They are separate because they are separate
questions with separate evidence: addressing is proved by a handshake, permission by a packet that
must NOT arrive. `net.render()` calls `nft_document()` and carries the edge fragment onward; the
tunnel container applies the firewall (`tunnel-entrypoint.sh`), the office that OWNS the door applies
the edge rule.

What the firewall says, per peer
--------------------------------
* link `serve` — this office's apps are the ones being opened: the peer's tunnel address may reach
  exactly the ports those apps listen on (the ones declared under `serve:`, and — once placement
  exists — the ports a placed app must reach back to), and NOTHING else. One `accept` per declared
  port, then a `drop` for that address: the drop is what makes the list an allow-list rather than a
  suggestion.
* link `use` — this office consumes the peer's apps: nothing may ARRIVE from the peer except replies
  to connections this office opened (covered by `ct state established,related`), so the peer's
  address gets a plain drop.
* no relay — a packet that arrives from one peer and would leave towards another is dropped here.
  Relaying is phase 5 and is a decision; today it is not one anybody made, so it is not a hole.

The chains, and why the tunnel interface is the filter
-----------------------------------------------------
`forward` has `policy drop`, because this container's only reason to forward is the tunnel. `input`
keeps the default accept — the WireGuard handshake itself arrives on the container's normal interface
and must not be filtered by accident — and jumps tunnel traffic to a chain that accepts only liveness
(replies and ICMP, which is what `ping 10.79.x.1` measures) and drops the rest.

Every line names the office and the app it comes from, so `nft list ruleset` on a live office reads
as the declaration it was rendered from rather than as a wall of ports.

What this module deliberately does NOT decide
---------------------------------------------
One thing a reader could wrongly conclude from an `accept` line:

1. **Where an allowed packet LANDS.** The rule says a packet from this peer to this port may pass;
   which process it reaches is DELIVERY, and the delivery half is `linkproxy.py` (it terminates the
   connection in this namespace and forwards it to the app by name, rather than a DNAT to an address
   Docker owns). What this module still owns is the SECOND half of the same question, because a
   connection that terminates here is an INPUT packet, and the `forward` chain above never sees it:
   the declared ports are therefore accepted in `from_tunnel` too. That is not a second opinion about
   permission — it is the same list, asked about the other hook — and it has to live in THIS chain:
   measured on this deployment 2026-10-01, an `accept` in an earlier base chain did not stop this
   chain's `drop` (the SYN arrived, matched the delivery chain, was accepted there, and was dropped
   here: the peer's probe timed out until this chain was flushed, and answered immediately after).
   One chain, one verdict.
2. **Identity, as opposed to reachability.** These rules are about addresses and ports. Whether an
   `X-authentik-*` header may be believed is the edge's question — `guard()`/`peer_rule()` below hand
   it the same fact (the link's own address) so the two answers cannot disagree.

Re-applying is idempotent, which the applier depends on: `nft -f` of the whole document REPLACES
`table inet dgo` (measured — the same ruleset applies twice without error), so a link that disappears
from the declaration cannot leave its `accept` behind.
"""
from __future__ import annotations

import ipaddress
import json
import re
import subprocess
import tempfile
from pathlib import Path

#: The interface a peer's rules name when the peer does not carry one of its own. One interface per
#: PAIR since 2026-10-04 (`net.iface_name(slot)` → `wg<slot>`); the default is kept because a peer
#: dict rendered without an `iface` is still legal — a single-pair render, and every older test.
WG_IF = "wg0"


def iface_of(peer: dict, default: str = WG_IF) -> str:
    """The interface a peer's packets arrive on: its own (`iface`, from the pair it belongs to)."""
    name = str((peer or {}).get("iface") or default or WG_IF).strip()
    if not re.match(r"^[a-z][a-z0-9_-]{0,14}$", name):
        raise FirewallError(f"שם ממשק לא תקין לקישור עם {(peer or {}).get('office')!r}: {name!r}")
    return name


def _iface_set(names: list[str]) -> str:
    """One interface quoted, several as an nft anonymous set — the form `nft` reads for both shapes."""
    names = sorted(set(names))
    if not names:
        return f'"{WG_IF}"'
    if len(names) == 1:
        return f'"{names[0]}"'
    return "{ " + ", ".join(f'"{n}"' for n in names) + " }"


class FirewallError(RuntimeError):
    """Rendering refused. A rule set nobody can check is worse than no rule set, so a peer we cannot
    describe the direction of is an error and not a default."""


# ── the tunnel container: nftables ──────────────────────────────────────────────────────────────
def _addr(peer: dict) -> str:
    addr = (peer or {}).get("address") or ""
    try:
        ipaddress.IPv4Address(addr)
    except ipaddress.AddressValueError:
        raise FirewallError(f"לעמית {((peer or {}).get('office'))!r} אין כתובת מנהרה תקינה ({addr!r})")
    return addr


def direction(peer: dict) -> str:
    """`serve` = the peer may reach apps HERE; `use` = the peer may not; `both` = the owner declared
    the link bidirectional, so the peer may arrive AND this office reaches it. Anything else is
    refused rather than read as `use`: a typo that silently closes a link is indistinguishable from a
    link nobody uses."""
    d = (peer or {}).get("direction") or "use"
    if d not in ("use", "serve", "both"):
        raise FirewallError(f"כיוון לא מוכר {d!r} בקישור עם {(peer or {}).get('office')!r}")
    return d


def _ports(peer: dict) -> dict:
    out = {}
    for app, port in ((peer or {}).get("ports") or {}).items():
        try:
            out[str(app)] = int(port)
        except (TypeError, ValueError):
            raise FirewallError(f"פורט לא תקין ל„{app}” בקישור עם {(peer or {}).get('office')!r}: {port!r}")
    return out


def allowed_ports(peer: dict) -> dict:
    """What this office lets THAT peer reach, as {app: port}. Public because the gate and the screen
    must be able to ask the same question the renderer answers, without re-deriving it."""
    return _ports(peer) if direction(peer) in ("serve", "both") else {}


def nft_rules(peers: list[dict], wg_if: str = WG_IF) -> list[str]:
    """The rule lines of the `forward` chain, one block per peer, in address order.

    Each block names the interface THAT PEER's packets arrive on (`iface_of`): with one pair per
    interface, a rule that named `wg0` for a peer who lives on `wg3` would be an allow-list for
    traffic that never comes, plus a `drop` that never fires.
    """
    out = []
    for p in sorted(peers, key=lambda x: _addr(x)):
        oid = (p or {}).get("office") or _addr(p)
        addr = _addr(p)
        d = direction(p)
        ports = _ports(p)
        iface = iface_of(p, wg_if)
        if d not in ("serve", "both"):
            out.append(f"# {oid}: link is `use` — nothing may arrive from it except replies")
        elif not ports:
            out.append(f"# {oid}: link is `serve` with nothing declared in `serve:` — no port opened")
        else:
            out.append(f"# {oid}: `serve` — exactly these ports, and only from {addr}")
            for app, port in sorted(ports.items(), key=lambda kv: (int(kv[1]), kv[0])):
                out.append(f'iifname "{iface}" ip saddr {addr} tcp dport {int(port)} accept   # {app}')
        out.append(f'iifname "{iface}" ip saddr {addr} drop')
    return out


def nft_document(peers: list[dict], wg_if: str = WG_IF, forward_policy: str = "drop") -> str:
    """The whole ruleset the tunnel's own namespace applies — one table, no leftover from a plan.

    Rendered in full (rather than added to) on purpose: the applier is `nft -f`, so a link that
    disappears from the declaration cannot leave its `accept` behind — and the applier must DELETE the
    table first, because `nft -f` MERGES with what is already there, so every converge adds a second
    copy of every rule (measured on vps1, 2026-10-01: each rule listed twice).

    `forward_policy` is the one thing that depends on WHERE the ruleset lands, and getting it wrong
    takes a whole office off the internet. Inside the tunnel's own container namespace the `forward`
    hook carries nothing but this link's traffic, so `drop` is the honest default: everything not
    named is refused. Applied on a MACHINE — which is what happens when the dialed office runs its
    tunnel in its own network namespace (`step_link`'s peer document) — that same `policy drop` is a
    base chain at the `filter` priority shadowing iptables' own, and a base chain's `accept` is not
    final across chains: it silently killed EVERY published container port on that host. Measured
    2026-10-01: SYNs to vps1:443 arrived (`tcpdump`) and were never answered, while the office
    reported healthy and its own loopback answered 302. On a machine the policy is `accept`; the
    link's own traffic is still policed by the explicit drops below, which are about the tunnel and
    nothing else.
    """
    if forward_policy not in ("drop", "accept"):
        raise FirewallError(f"forward_policy must be drop or accept, got {forward_policy!r}")
    peers = list(peers or [])
    allows = {((p or {}).get("office") or _addr(p)): allowed_ports(p) for p in peers}
    # ONE TABLE FOR EVERY PAIR, one interface each. The rules that are about the tunnel as a whole
    # (no relay between peers, our own connections out, the jump into `from_tunnel`) name the SET of
    # tunnel interfaces: with two interfaces, a rule naming only `wg0` would police one pair and let
    # the other relay freely. A single pair keeps the single-name form it always had, so a rendered
    # document that was green yesterday is byte-identical today.
    ifaces = [iface_of(p, wg_if) for p in peers] or [wg_if]
    iface_set = _iface_set(ifaces)
    lines = [
        "# GENERATED by dgo-extend/firewall.py from the links this office declares — DO NOT EDIT.",
        "# Direction is enforced HERE, on the receiving side: `use` opens nothing inbound, `serve`",
        "# opens exactly the declared ports, and everything else from a peer's tunnel address drops.",
    ]
    for oid in sorted(allows):
        ports = allows[oid]
        lines.append("#   %s: %s" % (oid, ", ".join(f"{a}:{p}" for a, p in sorted(ports.items()))
                                     if ports else "no inbound port"))
    lines += [
        "table inet dgo {",
        "  chain forward {",
        "    type filter hook forward priority filter; policy " + forward_policy + ";",
        "    ct state established,related accept",
        "    ct state invalid drop",
        f'    iifname {iface_set} oifname {iface_set} drop   # no relay between two peers (phase 5)',
        f'    oifname {iface_set} accept   # our own connections out; the far end enforces what arrives',
    ]
    lines += ["    " + r for r in nft_rules(peers, wg_if)]
    lines += [
        "  }",
        "  chain input {",
        "    type filter hook input priority filter; policy accept;",
        f'    iifname {iface_set} jump from_tunnel',
        "  }",
        "  # A peer may address THIS container only to ask whether it is alive: replies to what we",
        "  # opened, and ICMP — which is exactly the `ping 10.79.x.<our side>` the link is proved with.",
        "  chain from_tunnel {",
        "    ct state established,related accept",
        "    ip protocol icmp accept",
    ]
    # DELIVERY (DGO-24). A connection a `serve` link allows TERMINATES in this namespace instead of
    # being forwarded (`linkproxy.py` explains why it is a proxy and not a DNAT), so the packet is an
    # INPUT packet and the `forward` chain above never sees it. Same declaration, same list, the other
    # hook — and it must be here rather than in a chain of the delivery half's own, because a base
    # chain's `accept` is not final across chains (see this module's docstring for the measurement).
    for p in sorted(peers or [], key=_addr):
        for app, port in sorted(allowed_ports(p).items(), key=lambda kv: (int(kv[1]), kv[0])):
            lines.append(f'    iifname "{iface_of(p, wg_if)}" ip saddr {_addr(p)} tcp dport {int(port)} '
                         f'accept   # {app} — delivered to the app behind the link')
    lines += [
        "    drop",
        "  }",
        "}",
    ]
    return "\n".join(lines) + "\n"


# ── the receiving edge: only the link's own source may open a remote app's door ─────────────────
def source(peer: dict) -> str:
    """The ClientIP source of ONE link, as traefik wants it: the peer's tunnel address, `/32`."""
    return f"{_addr(peer)}/32"


def guard(peers: list[dict]) -> dict:
    """The edge fragment for the doors THIS office's own edge holds open.

    Only a peer whose link is `serve` may arrive — the same rule the firewall renders, asked about the
    HTTP door instead of the packet. `client_ip` and `rule` are the same fact in the two shapes the
    two writers need: the JSON artifact written next to the tunnel plan (checkable, no re-derivation),
    and the fragment that goes straight into a traefik rule.
    """
    sources = sorted({source(p) for p in (peers or []) if direction(p) in ("serve", "both")})
    return {"sources": sources,
            "rule": " && ".join(f"ClientIP(`{s}`)" for s in sources) or "ClientIP(`127.0.0.1/32`)"}


def peer_rule(host: str, token: str, alias: str, clients: list[str]) -> str:
    """The traefik rule of ONE remote app's door: host + the link's source + the office token + path.

    Three conditions, and each is load-bearing: the host is the office's own, `ClientIP` says the
    request arrived over the link (so a token that leaked is not enough to use it), the header is the
    office's, and the path is the one app. A request that fails any of them matches NO router, which
    is why the answer is a plain 404 and why closing the door needs no extra service to say no.
    """
    ip = " && ".join(f"ClientIP(`{c}`)" for c in (clients or []))
    return (f"Host(`{host}`) && {ip} && Header(`X-Office-Peer`, `{token}`) && PathPrefix(`/{alias}`)"
            if ip else f"Host(`{host}`) && Header(`X-Office-Peer`, `{token}`) && PathPrefix(`/{alias}`)")


# ── checking, without a tunnel ─────────────────────────────────────────────────────────────────
def _running(prefix: str) -> list[str]:
    try:
        p = subprocess.run(["docker", "ps", "--filter", f"name=^{prefix}",
                            "--format", "{{.Names}}"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [n.strip() for n in (p.stdout or "").splitlines() if n.strip()]


def nft_check(document: str, container_prefix: str = "dgo-net-") -> tuple[bool | None, str]:
    """`nft -c -f` on a rendered ruleset, inside the very container that applies it.

    `nft -c` parses and validates against the kernel WITHOUT committing, which is what makes the
    acceptance of DGO-21 measurable before a second machine exists: the rules are proved well-formed
    here, and the packet that must not pass is proved by the rules themselves.

    Returns (True, …) valid, (False, …) refused, (None, …) nft was not reachable — three states,
    because "I could not check" must never read as "it is fine".
    """
    names = _running(container_prefix)
    if not names:
        return None, f"no running {container_prefix}* container"
    tmp = Path(tempfile.mkdtemp()) / "dgo-check.rules"
    tmp.write_text(document, encoding="utf-8")
    remote = "/tmp/dgo-firewall-check.rules"
    try:
        subprocess.run(["docker", "cp", str(tmp), f"{names[0]}:{remote}"],
                       capture_output=True, text=True, timeout=60, check=True)
        r = subprocess.run(["docker", "exec", names[0], "nft", "-c", "-f", remote],
                           capture_output=True, text=True, timeout=60)
        subprocess.run(["docker", "exec", names[0], "rm", "-f", remote],
                       capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        return None, f"nft could not be run in {names[0]}: {type(e).__name__}"
    detail = (r.stdout + r.stderr).strip() or "accepted, nothing to report"
    return (r.returncode == 0), f"nft -c in {names[0]}: {detail}"


def nft_apply_check(document: str, container_prefix: str = "dgo-net-") -> tuple[bool | None, str]:
    """Apply the rendered ruleset for real — in a THROWAWAY network namespace — and read it back.

    `nft -c` proves the rules PARSE. This proves the kernel takes them whole (a base chain with
    `policy drop`, a `jump` into a chain whose last rule is a bare `drop`, a `ct state` match), and
    that `nft list ruleset` returns what was rendered rather than a repaired version of it.

    It cannot touch the live office: a fresh container has its own network namespace, so the table
    it creates dies with it. Read-only with respect to every running container; it only reads the
    image name off one.
    """
    names = _running(container_prefix)
    if not names:
        return None, f"no running {container_prefix}* container to take an image from"
    try:
        image = subprocess.run(["docker", "inspect", names[0], "--format", "{{.Config.Image}}"],
                               capture_output=True, text=True, timeout=30, check=True).stdout.strip()
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        return None, f"the image of {names[0]} could not be read ({type(e).__name__})"
    if not image:
        return None, f"{names[0]} has no image name"
    script = "nft -f /dev/stdin && nft list ruleset"
    try:
        r = subprocess.run(["docker", "run", "--rm", "-i", "--cap-add", "NET_ADMIN",
                            "--entrypoint", "sh", image, "-c", script],
                           input=document, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"the ruleset could not be applied in a throwaway namespace ({type(e).__name__})"
    if r.returncode != 0:
        return False, f"the kernel refused the rendered ruleset: {(r.stdout + r.stderr).strip()[-200:]}"
    applied = r.stdout or ""
    # `nft list ruleset` is a normalisation of what was loaded: comments are gone and the rules are
    # re-indented. Compare the RULES, one per line and comment-free, which is the claim being made.
    def norm(lines):
        out = set()
        for line in lines:
            body = line.split("#", 1)[0].strip()
            if body:
                out.add(" ".join(body.split()))
        return out
    rendered = norm(l for l in document.splitlines()
                    if l.strip() and not l.strip().startswith(("#", "table", "}", "chain")))
    got = norm(applied.splitlines())
    missing = sorted(rendered - got)
    if "policy drop" not in applied:
        missing.append("policy drop")
    return (not missing), (f"applied in a throwaway namespace from {image} · "
                           + ("read back exactly as rendered" if not missing
                              else f"NOT read back: {missing[:3]}"))



# ── the decisions, as a test that needs no machine ──────────────────────────────────────────────
def selftest() -> list[str]:
    """Every decision this module makes, checked on a two-office example. Run by the phase-1 gate and
    by `python3 apps/dgo-extend/firewall.py`; needs no docker, no tunnel and no second office."""
    problems = []
    peer_use = {"office": "vps1", "address": "10.79.2.2", "direction": "use"}
    peer_serve = {"office": "vps2", "address": "10.79.4.2", "direction": "serve",
                  "ports": {"drive": 8975, "project-pln": 8080}}
    doc = nft_document([peer_use, peer_serve])

    if "policy drop;" not in doc:
        problems.append("the forward chain must default to drop")
    if 'iifname "wg0" ip saddr 10.79.2.2 drop' not in doc:
        problems.append("a `use` link must drop everything arriving from that peer")
    if "10.79.2.2 tcp dport" in doc:
        problems.append("a `use` link must open no port for the peer")
    for app, port in (("drive", 8975), ("project-pln", 8080)):
        if f'ip saddr 10.79.4.2 tcp dport {port} accept   # {app}' not in doc:
            problems.append(f"a `serve` link must open {app}:{port} from that peer's address only")
    if "tcp dport 9999" in doc:
        problems.append("a port nobody declared must not appear in the rules")
    if doc.count("10.79.4.2") < 3:
        problems.append("`serve` must accept the declared ports AND drop the rest of that address")
    if 'iifname "wg0" oifname "wg0" drop' not in doc:
        problems.append("two peers must not be able to relay through this office")
    if "oifname \"wg0\" accept" not in doc:
        problems.append("our own connections out must be allowed, or `use` can never work")
    if "ip protocol icmp accept" not in doc:
        problems.append("the link is proved by a ping through it, so ICMP cannot be dropped")

    # DELIVERY (DGO-24): the same ports, on the INPUT path. A `serve` port that is allowed to be
    # forwarded but dropped when it terminates here is a link that passes every check but the one
    # that matters — measured from the peer: SYN in, nothing out.
    if doc.count("tcp dport 8975 accept") < 2:
        problems.append("a served port must be accepted on BOTH hooks: forwarded, and terminated "
                        "here for delivery")
    if "tcp dport 8080 accept   # project-pln — delivered" not in doc:
        problems.append("the delivery accept must name the app it delivers to")
    serving = doc.split("chain from_tunnel", 1)[1]
    if "10.79.2.2" in serving:
        problems.append("a `use` peer may not arrive, so it may not be accepted on the input hook")

    # A peer the renderer cannot describe is an error, not a silently closed link.
    for bad, why in (({"office": "x", "address": "not-an-ip", "direction": "serve"},
                      "a peer without a valid tunnel address"),
                     ({"office": "x", "address": "10.79.9.2", "direction": "sideways"},
                      "a direction that is neither use nor serve"),
                     ({"office": "x", "address": "10.79.9.2", "direction": "serve",
                       "ports": {"drive": "http"}}, "a port that is not a number")):
        try:
            nft_document([bad])
            problems.append(f"{why} must be refused")
        except FirewallError:
            pass

    # An empty peer list is a valid render: an office with no links still has a firewall.
    empty = nft_document([])
    if "policy drop;" not in empty or "ip saddr 10.79" in empty:
        problems.append("no links must render a closed firewall, not an open one")

    # ONE INTERFACE PER PAIR (2026-10-04). Two peers on two pairs: each rule names the interface its
    # peer's packets arrive on, and the rules about the tunnel AS A WHOLE name both — a relay rule
    # that named one interface would police one pair and leave the other unpoliced.
    pair_a = {"office": "vps1", "address": "10.79.2.2", "direction": "use", "iface": "wg2"}
    pair_b = {"office": "hp-laptop", "address": "10.79.3.2", "direction": "use", "iface": "wg3"}
    multi = nft_document([pair_a, pair_b])
    if 'iifname "wg2" ip saddr 10.79.2.2 drop' not in multi:
        problems.append("each peer's drop must name the interface of ITS pair")
    if 'iifname "wg3" ip saddr 10.79.3.2 drop' not in multi:
        problems.append("a second pair's peer must be policed on the second interface")
    if 'iifname { "wg2", "wg3" } oifname { "wg2", "wg3" } drop' not in multi:
        problems.append("the no-relay rule must cover every pair's interface, not just the first")
    if 'iifname { "wg2", "wg3" } jump from_tunnel' not in multi:
        problems.append("the input hook must jump from every pair's interface")
    served_multi = nft_document([{**pair_a, "direction": "serve", "ports": {"drive": 8975}},
                                 {**pair_b, "direction": "serve", "ports": {"sites": 8979}}])
    if 'iifname "wg2" ip saddr 10.79.2.2 tcp dport 8975 accept   # drive' not in served_multi:
        problems.append("a served port must be accepted on its own pair's interface")
    if 'iifname "wg3" ip saddr 10.79.3.2 tcp dport 8979 accept   # sites' not in served_multi:
        problems.append("the second pair's served port must be accepted on the second interface")
    single = nft_document([pair_a])
    if 'iifname "wg2" oifname "wg2" drop' not in single:
        problems.append("one pair must still render the single-name relay rule it always had")
    for bad_iface in ("wg 2", "wg2; drop", " "):
        try:
            iface_of({"office": "x", "iface": bad_iface})
            problems.append(f"an interface name like {bad_iface!r} must be refused")
        except FirewallError:
            pass
    if iface_of({"office": "x"}) != WG_IF:
        problems.append("a peer with no interface of its own keeps the single-pair default")

    # The edge fragment: the door answers the link's own address and nobody else. A `use` peer may
    # not arrive at all, so it opens no door — the same answer the firewall gives about its packets.
    g = guard([peer_serve])
    if g["sources"] != ["10.79.4.2/32"] or g["rule"] != "ClientIP(`10.79.4.2/32`)":
        problems.append(f"the edge guard must name the link's address alone, got {g}")
    if guard([peer_use])["sources"]:
        problems.append("a `use` link may not arrive, so it must open no door on this edge")
    rule = peer_rule("peer.staging.example", "tok", "drive", g["sources"])
    if "ClientIP(`10.79.4.2/32`)" not in rule or "Header(`X-Office-Peer`, `tok`)" not in rule \
            or "PathPrefix(`/drive`)" not in rule:
        problems.append("the remote door's rule must carry the source, the token and the app path")
    if "ClientIP" not in json.dumps(guard([])) or guard([])["sources"]:
        problems.append("no links must render an edge guard that matches nobody")
    return problems


if __name__ == "__main__":
    bad = selftest()
    for b in bad:
        print("FAIL", b)
    print("firewall.py selftest:", "PASS" if not bad else f"{len(bad)} problem(s)")
    raise SystemExit(1 if bad else 0)
