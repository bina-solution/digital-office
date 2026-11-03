# The herd from anywhere: every office reaches every office, wherever the laptop is

The owner, 2026-11-01, from a coffee shop (verbatim on DGO-1094, plan `herd-anywhere`):
«next time when I'm working out of home, I want really VPS to serve my entire office herd, like to be
able to also use all the compute we have on Dell and on the HP, and of course create tickets … this
should be solved once and for good … it will be mapping either to the in-network connection between HP
and Mac, or it will be via the VPS … no matter where I am, everything keeps working and I have control
over the full herd».

This doc covers what was measured, what landed that day, the lasting design and the order of work. The
link itself (its parts, how it dies and the mesh's shape) is [dgo-link-lifetime.md](dgo-link-lifetime.md).

## 1. What was measured, 2026-11-01, with the MacBook out of the house

- **The pairs are two by two.** A pair is point-to-point WireGuard, with one interface per pair. Traffic
  from one peer to another is dropped by design (`apps/dgo-extend/firewall.py`, "Relaying is phase 5").
- **Which pairs held:**
  - Mac ⇄ vps1: up.
  - Mac ⇄ fireplace: up.
  - vps1 ⇄ hp-laptop: up. The HP dials vps1's door, so this pair never needed the Mac.
  - Mac ⇄ hp-laptop and Mac ⇄ Dell: down. Both are found by a LAN scan, and there is no LAN.
  - Dell ⇄ vps1: never paired. `plans/dgo-herd.yaml` decided that the public server keeps no path to
    the heavy box.
- **The roaming laptop.** The Lima/vz NAT kept the old network's mapping for WireGuard's fixed listen
  port, and the 25 s keepalives kept that dead mapping alive. Fixed by hand by moving the listen port.
  The issue is `issues/a-mac-that-changes-networks-keeps-its-tunnels-dead-on-a-stale-nat-mapping.yaml`.
- **The result.** Two things were one hop from vps1, yet unreachable from the Mac:
  - the tickets (Plane runs on the HP);
  - the HP's agent.

## 2. Step 1, landed the same day (3ea60879): the hub, and `bbox via`

- **The hub is declared.** `apps/computers/herd.yaml` has `hub: vps1`: the public office that every
  office keeps a pair with.
- **`bbox via <office> [--put FILE]… <bbox args…>`** (`scripts/via.py`):
  - runs any bbox verb on a linked office, in that office's own checkout;
  - goes through the office's Computers app over the pair, with the link's own credential;
  - carries files with `--put` (gzip+base64, at most 100 KiB, which is one argument through the link);
  - marks every command that arrives through it with `BBOX_VIA=1`, so the command never takes a second hop.
- **project-pln falls back by itself** (`apps/project-pln/where.sh`). Its door is probed first. When
  nothing answers, or the link proxy answers 502/503/504, `tasks` and `plan` re-run the same verb on the
  hub. `attach` and `plan` carry their files. `report` goes through `plan` and `tasks`, so it works too.
  Measured from the coffee shop:
  - `tasks show` takes 32–40 s;
  - `plan --only` takes 15.7 s and created DGO-1093;
  - the work item links point at vps1's console, which opens from anywhere.
- **What step 1 is not:**
  - It is a relay of commands, not a path. Only project-pln falls back by itself. Every other verb
    has to be given `bbox via vps1 …`.
  - The HP's tiles open on vps1's console, not on the Mac's.
  - A call takes 30–40 s: an 8 s probe, then an exec over two pairs.
  - The Dell is not reached at all: it has no pair with vps1 and nothing relays.

## 3. The lasting answer: the hub relays ciphertext (phase 5)

This has the shape of Tailscale's DERP, built from parts the carrier already has.

**What is there today.** The carrier (`apps/dgo-extend/carrier/`) can already ride a pair over a
WebSocket at an HTTPS edge (`dial: relay`, `ws.go`, `door.go`). The pair is proved by its own handshake
(`wire.go`: a tag made from the two public keys, then a proof from their shared secret). Its rule
**"one connection per pair, the newest wins"** is what lets a peer come back from a new address with no
coordination.

**What is added.** The hub's door learns one thing: to **splice** two carrier connections of a pair that
the hub itself is not part of.

- **The accepting side parks.** An office at home (HP, Dell) holds a standing WebSocket at the hub's door
  for each of its pairs that may be relayed. It names the pair by its tag, which is already on the wire
  and reveals no key.
- **The dialing side splices in.** The Mac, away, dials the hub's door for the same tag when its direct
  ways to the peer fail. The door pipes the two sockets together, byte for byte.
- **End to end.** The carrier's handshake and WireGuard run between the Mac and the HP themselves:
  - the hub sees only ciphertext;
  - it holds no key of the pair;
  - its `forward` chain stays `policy drop`, so nothing is routed at the IP layer.

  The security rule "no relay between two peers" therefore stays true where it was written.
- **Declared, not open.** The hub splices only the pairs it declares:
  - on the hub, `tunnel.relay_for: [hp-laptop, portable-ubuntu, macbook]`, a field that
    `declaration.py` already validates;
  - on each of the pair's two offices, `fallback_relay: <the hub's door>`.

  An undeclared tag is refused, and the refusal is counted.
- **Path selection, per pair, in the carrier** (`carry.go` `find()`):
  1. the last address that worked;
  2. the declared addresses;
  3. the LAN scan;
  4. the hub relay.

  While a pair is relayed, the scan keeps running every 30 s. When it finds the peer directly, the
  newest-wins rule swaps the relayed session for the direct one. That is the upgrade back when the laptop
  comes home, and it needs no new mechanism.
- **Roaming.** On a network change, or when a handshake has been missing for `HEAL_AFTER`, the sidecar
  first moves the WireGuard listen port to a fresh source port. That is today's hand fix, as code.
- **What it gives:**
  - Every pair the herd declares works from anywhere, with no hop of commands.
  - The Mac's own console opens the HP's and the Dell's tiles away from home.
  - project-pln's direct path just works. The hub fallback of step 1 stays as the second line, for the
    day the relay itself is down.
  - `bbox via hp-laptop …` and `bbox via dell …` reach their compute directly.
- **The Dell keeps the herd's decision.** vps1 still gets no pair with the Dell and no path into its
  apps. The relay carries Mac ⇄ Dell and HP ⇄ Dell ciphertext, nothing more. The Dell only parks.

## 4. The herd's compute, from anywhere

- **Today:**
  - `bbox via <office> <verb>` runs any verb on any office it reaches;
  - each office's Computers app runs a shell on its own machine, capped at 600 s per call.
- **Next:**
  - `bbox computers run --role heavy -- <cmd>` picks the office by its `herd.yaml` role and by its own
    measured load;
  - the work runs there as a detached job, with its log and `bbox computers jobs`, because the exec
    stops at 600 s;
  - the heavy-work rule (one build at a time, load and disk checked first) is enforced by the office
    that runs the job, not trusted to the caller.

## 5. Nothing is lost when there is no path at all

- **Writes go to an outbox.** A ticket write (`tasks start|done|comment`, `plan`) that finds no path
  (direct, relay or hub) is written to this office's outbox (`.state/outbox/project-pln/`). It is
  replayed in order when a path is back. The reply says «queued, N waiting» instead of failing.
- **Reads say so.** A read says «offline since …», so a stale answer never passes as a live one.

## 6. Control from anywhere

- vps1's console is the herd's door from a phone or a borrowed laptop. It already shows every office's
  tiles.
- It adds the link map, one line per pair:
  - its path (direct, LAN, relay or down);
  - since when;
  - its history (`dgo-link-lifetime.md` §4.4).

## 7. At scale

- **A herd is its offices plus a hub.** Being the hub is a declaration, and any public office can hold
  it. A herd may declare two hubs, so one can take over from the other.
- **The relay is a dumb pipe:**
  - it addresses pairs by tag;
  - it keeps no state that matters, no key and no data;
  - so many instances' herds can share regional relays run by DGO cloud;
  - each pair picks the nearest relay by measured round trip, and more relays are added side by side
    as the load grows.
- **No central plane holds keys or data:**
  - each instance's declarations live in its own git;
  - a pairing is an offer and a claim between two offices;
  - the keys of a pair exist only on its two offices.

  That is what lets the same design serve a laptop at a café and a billion users without changing the
  security model.

## 8. The order of work

Plan `apps/project-pln/plans/herd-anywhere.yaml`, project DGO, keys `any-*`:

| key | what | needs |
|---|---|---|
| any-000 | the owner's words | — |
| any-001 | step 1: hub + `bbox via` + project-pln fallback | done, 3ea60879 |
| any-101 | roaming: a fresh source port when a handshake stalls | — |
| any-102 | the relay: the door splices declared pairs; parked connections; `relay_for` / `fallback_relay` | carrier Go tests |
| any-103 | path selection and the upgrade back to direct; `bbox dgo link status` shows the path | any-102 |
| any-104 | the HP and the Dell park at the hub | any-102, the machines at home once |
| any-201 | project-pln outbox | — |
| any-301 | `bbox computers run --role heavy` with detached jobs | — |
| any-401 | the link map with paths and history on vps1's console | any-103 |
| any-501 | the drill: the Mac on a phone hotspot opens tickets, the HP's tiles and Dell compute; back home, the pair is direct again within 60 s | all of the above |
