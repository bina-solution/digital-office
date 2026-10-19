# The link's lifetime — every way it dies, who notices, who repairs it, and what a lasting link still needs

The owner, 2026-10-12: «תחקור לעומק כמה אנחנו בטוחים שהחיבור הזה יחזיק לאורך זמן בתקווה שלא נצטרך
לחבר שוב, וגם איך אנחנו מגיעים למצב שאנחנו מחברים את המק לשתיי הלשכות ואז יהיה חיבור משולש שכולם
מחוברים לכולם». This is the answer for one pair (vps1 ↔ hp-laptop, measured live on 2026-10-12
16:00–19:40) and the plan for the third office (macbook).

It is the deliverable of hub item `lnk-030` (was `lnk-022` before the 2026-10-12 renumbering) and it
exists because the alternative was a screenshot that says "up". Everything below is either a
measurement taken here or a fact read out of the code, with the file named.

## 1. What "the link" is made of

A link is not one thing. It is six things that must all be right, owned by five different writers —
so a failure has to be attributed before it can be repaired.

| Piece | Where it lives | Who writes it | What it fails as |
|---|---|---|---|
| The pair record (one per end) | `/data/dgo/<office>.yaml` on each office | `pair_api` + `converge.save_declaration` (one writer for link fields) | a dial target that cannot be reached, a missing peer |
| The WireGuard interface | `dgo-net` container, `/tunnel/pairs/wg<slot>.conf` | `net.py` renders, `tunnel-entrypoint.sh` applies | no handshake, no traffic |
| The published UDP port | the machine's edge → the container (`51830`) | `.env` (`DGO_WG_ENDPOINT`/`DGO_WG_PUBLISH_PORT`), ufw, docker's port map | a dial that arrives nowhere |
| The door + the catalog listener | `dgo-link` container (shares `dgo-net`'s netns) | `linkproxy.py` from the app's own plan | a live tunnel that delivers nothing |
| The catalog pull + the projection | `dgo-extend`, every 60 s (`PROJECTION_SECONDS`) | `projection.py` → `platform.state.yaml` `remote:` → `serve.py` → traefik | tiles missing or marked down |
| The record of the link's state | `/data/peers/link.json` (read by the console) | `peers.publish_link()` from the verdict | a screen that says the wrong thing |

## 2. Every way it dies, and what happens next

Measured cases are marked with their date and the numbers seen. "Automatic" means no human, no
command — the platform notices and repairs itself.

| # | Death mode | Evidence | Detector today | Repair today | Recovery |
|---|---|---|---|---|---|
| D1 | A home NAT/router **blackholes the dialer's source port** (the flow just stops crossing) | 2026-10-04 port 51820, 2026-10-06 port 51832: `wg` counts initiations sent, the far side's `tcpdump` sees none; the same machine's other flows cross fine | no handshake while `tx` grows (`wg show`) — `heal_links` clock starts after `HEAL_AFTER=180 s` | a fresh source port for that pair (`rotate_listen_port` → `/data/listen-ports.json`), one per `HEAL_COOLDOWN=600 s`, at most `HEAL_MAX=6` times | measured 10-04/10-06: handshake within seconds of the port move; ~3–4 min including the detector |
| D2 | The **listening office's LAN address moved** (DHCP lease) | 2026-10-07: hp-laptop came back as `192.168.16.100` while the record said `.102`; six port rotations changed nothing | same "no handshake" signal after `FIND_AFTER=300 s` | a bounded, nearest-first search of the lost address's own /24 (`find_peer`, `FIND_CANDIDATES=64`, one per `FIND_COOLDOWN=900 s`, at most `FIND_MAX=3`); the address is adopted **only on a completed handshake** — only the key's owner answers one | measured 2026-10-12 (a full /24 with no peer at all): 8 min 37 s to sweep 64 addresses and say "nothing" |
| D3 | The pair was **written the wrong way round** — the office that can be reached became the dialer of a private address it is not on | 2026-10-12: `w2` peer `192.168.16.100:51830`, `0 B received`, `1.45 KiB sent`, two port rotations and one /24 sweep proved nothing | `verdict.hop = "pair"` + `find_peer` refusing the sweep + no rotation (`net.dialable_from_here`, lnk-032) | **none from this side** — both records carry the same `dial`; the pair is replaced by a fresh pairing (the codes flow again) | measured 2026-10-12: ~3 min with both offices' agents (offer 19:50:53 → handshake 19:53:5x) |
| D4 | **`dgo-net` recreated without `dgo-link`** — the door stays in a dead network namespace | 2026-10-04, four cases in one day: the tunnel was up, every app of the peer answered RST, traefik said 502 | `delivery.door.listening=false`, catalog pull 502 | `dcx`'s `netns_rejoin` on every bring-up: a container whose netns belongs to a recreated container is recreated with it (nothing is declared per pair) | measured: 33 s, automatic (seen again today: `[bbox] recreating dgo-link — the container whose network it lives in was replaced`) |
| D5 | **The record left without a word** (a peer known through the older machine-level model, or dropped while another pair was written) | 2026-10-08 23:37: the Mac's record vanished from `/data/dgo` in the same second the HP's was written; the Mac's tiles stopped being rendered and no screen said so. The machine-level `wg0` still dials nothing (last handshake 2026-10-11 01:23 — 1 d 18 h before today's reading) | **none** — the console has a card for "an office that does not answer", none for "an office this one used to know" | none | never, by itself (lnk-029) |
| D6 | **Two tunnels on one `/24`** — a new pair took the slot of an older link | 2026-10-08/09: the HP pair took slot 2, which is vps1's link with the MacBook; every Mac app behind vps1 answered «Bad Gateway» from that minute; the pair was also D3 | none at the time; the *source* is fixed — an offer now names the slot of **every tunnel address its office holds** (`_taken_slots` + the machine's own `.dgo/addressing.json`), so today's offer said `used_slots: [1, 2]` and the pair took slot 3 | re-pair or retire the older link | the Mac link never came back by itself (lnk-029, and `issues/the-first-direct-pair-took-the-slot-of-vps1s-link-with-the-macbook.yaml`) |
| D7 | A **laptop that sleeps** (the HP, the Mac) | the Mac's link: handshakes stop for hours, then resume when the lid opens | no handshake in the measurement (the verdict says `tunnel`, the tiles are drawn off) | nothing is needed: the dialing side's `PersistentKeepalive = 25` re-establishes the moment the machine is awake, and the listener learns the new source address from the first packet | seconds after wake (the same minute's projection pass puts the tiles back) |
| D8 | **This office's public address changed** | not measured here (a fixed-IP VPS) | none on the *peer's* side: the dialing side resolves `console.staging.digital-office.co.il` **when the pair is rendered** (`net.endpoint_address`) and writes the address | a re-render on the peer (or a re-pair) | until something re-renders — the one hole that grows with a dynamic address |
| D9 | **The identity is lost** (the `dgo_identity` volume wiped) | not measured | the peer's record holds the old public key; a handshake never completes | a new key is a new office: re-pair | manual (the volume is declared in `app.json` `data.volumes`, so `bbox export`/backup carries it) |
| D10 | A **rebuild of `dgo-extend` in the middle of a pairing** | 2026-10-11 09:04: the claim was dropped 15 s after it was made (offers and claims live in memory for 10 minutes) | the screen answers 404 with a sentence; `err.said` shows the server's own words | start the pairing again | a minute (the codes are short) |
| D11 | The **tunnel's own measurement goes quiet** (its 15-second loop is inside a long `/24` sweep) | 2026-10-12: the sweep ran 13:14:59→13:23:36 and `wg-state.json` was not written; the verdict then said «המנהרה אליה פעילה, אבל הלשכה עצמה לא עונה» over a tunnel that had never handshaken | fixed at the source: the sweep is refused for a pair this office cannot dial (`find_peer`), so it only runs where it can be meaningful | the verdict now calls an unmeasured tunnel `tunnel`, never "alive" | — |
| D12 | The **peer gives nothing** (`serve:` empty) | measured 2026-10-04: the HP on the MacBook showed as DOWN over a healthy tunnel | `publishes_nothing` — a state, not a fault | the pairing declares `{"*": {}}` when the office gives and nobody chose | — |
| D13 | The **catalog pull ends in a non-2xx** | 2026-10-12: this office's own door answered 502 with an empty body, and the tooltip read «catalog.office None אינו מזהה לשכה תקין» — a sentence about a document's shape, for a peer that never spoke | fixed: a non-2xx is «הלשכה האחרת לא ענתה (HTTP 502)» (`projection.fetch`) | the next pass (60 s) | ≤ 60 s |

## 3. How sure are we — the honest answer

**Sure, with numbers.** The pair vps1 ↔ hp-laptop, after the 2026-10-12 repair:

```
wg show wg3   listening port: 51830 · peer endpoint 79.177.165.212:60670
              latest handshake: 36 s ago · transfer 56856 B received, 43988 B sent
/api/link     state up · verdict {ok: true} · delivery {door listening, catalog ok}
              apps: ["plane"]  ·  handshake_age_s 114 · alive true
the door      curl -H 'Host: plane.hp-laptop' http://plane.hp-laptop:9003/  → 200 (0.16 s)
```

* The transport is self-healing for the two failures that actually happened to us (D1, D2): the
  detector is the absence of a handshake, the repairs are a source-port move (~3 min) and a bounded
  `/24` sweep (~9 min worst case), and both are automatic.
* The delivery half is self-healing since 2026-10-04 (D4, 33 s, automatic).
* The record half is **not** self-healing at all: D3 (wrong shape) needs a re-pairing, D5 (a record
  that leaves) has no detector, D6 (a slot collision) is prevented at the source but not detected.
  Every one of the three incidents that cost a day or more on this line was in this half.
* The keepalive is 25 s (the dialing side only), and WireGuard rekeys every ~2 minutes while a
  session is live; the projection pass is 60 s. Those are the clocks a person experiences as
  "the link is back".

So: **the tunnel will hold across NATs, sleep, DHCP and a rebuilt container without a human. What
will not hold by itself is the record** — and that is where the next repair work belongs.

## 4. The four things to add, in the order they would fail

1. **A peer this office used to know** (D5). The office must remember every peer it has EVER held and
   say so where the link's state is read — "a card for a peer whose record is gone, with the evidence
   on the machine (a machine-level `wg0` still carrying its key)". Acceptance: a peer that leaves the
   record store appears on «לשכות מחובות» as a named card that says what remains of it.
2. **A second tunnel on one `/24`, detected** (D6). The render knows every address this office holds
   (that is how today's offer named `used_slots: [1, 2]`); nothing checks that the *applied* plan and
   the *machine* do not both hold the same `/24`. Acceptance: `bbox dgo link status` names the
   condition ("10.79.2.0/24 is held by `wg0` on the machine AND by `wg3` in the container").
3. **A name that re-resolves without a re-render** (D8). A VPS whose address moves must not need the
   peer to re-render a file to be found again. Acceptance: the sidecar re-resolves the endpoint name
   when a handshake has been missing for `HEAL_AFTER`, before asking for a port move.
4. **A history of the link's state** (the measurement for all of the above). Today every surface says
   "now"; nothing says "it died at 03:12 and came back at 03:15, repaired by a source-port move".
   Acceptance: `./bbox dgo link history` prints the transitions with their cause.

## 5. The mesh — vps1 + hp-laptop + macbook

The owner's model (2026-10-01, `ai/context/dgo-remote-apps.md`): *apps run where they run*. A link is
**point-to-point**: an office publishes its own apps to a peer and reaches the peer's apps through
its own door. Peer→peer traffic is dropped **by design** (the Mac's firewall: `iifname {wg2, wg4}
oifname {wg2, wg4} drop`, forward `policy drop`), so *there is no chain vps1 → macbook → hp-laptop*
and none can be made. **A triangle is therefore three pairs, not one route** — each office holds its
own record per peer:

```
vps1 ──pair(slot 3, door 9003)── hp-laptop        ← live today, HP dials vps1:51830
vps1 ──pair(slot ?, door 9???)── macbook          ← to be paired; the Mac dials vps1 (it cannot listen)
macbook ──pair────────────────── hp-laptop        ← the home pair (already exists on both ends)
```

Measured consequences of that shape, from today's live pair:

* **Slots.** One `/24` per pair, one interface per pair, and the same WG keypair on all of an
  office's interfaces (the key is the office's identity — `ka9q…` on both `wg0` and `wg3` here).
  Our records: home slot 1, hp-laptop slot 3. The Mac's link with vps1 is **slot 2** — and it lives
  on the *machine* (`/etc/wireguard/wg0`, `10.79.2.2`, peer `10.79.2.1`), not in the app's records,
  which is why the app must keep naming it as used (it does: today's offer said `used_slots: [1, 2]`).
* **Ports.** The listener answers on the published `51830` (`DGO_WG_PUBLISH_BIND=0.0.0.0`,
  `DGO_WG_PUBLISH_PORT=51830`, ufw `51830/udp ALLOW`, `DOCKER-USER … RETURN udp dpt:51830`) — measured
  end to end at 16:0x: a WireGuard listener on that port completed a handshake against a dial to
  `31.97.196.82:51830`. A **second** pair that this office must listen for would need its own
  published UDP port (one wg socket per interface — the collision measured 2026-10-04); with the Mac,
  this office listens for *nobody* (the Mac can only dial), so one port is enough today.
* **What each office gives.** `serve:` is ONE map for the whole office, not per peer (that limit is
  `lnk-019` on the shared line: "what an office gives is one for all linked offices"). vps1 gives
  everything (`serve: {"*": {}}`); hp-laptop gives `plane` today. A third office does not change
  that, but the day the Mac must be given *less* than the HP is the day `lnk-019` must land.
* **The console and the door follow, not the tunnel.** A third pair adds: one `remote:` block, its
  tiles on every console, one traefik router per app per office (`<alias>.<office>.<console host>`),
  and one listener per pair on the door. All of it is compiled from the catalog — nothing to do by
  hand (measured today: tile + router + 302 to the identity provider within a minute of the tunnel).

**The Mac's pair with vps1 — what completing it needs** (the owner's next step, "through the
browsers"):

1. One of the two offices shows an offer and the other claims it. The Mac has to be the **dialer**
   (its engine forwards nothing inbound — `DGO_WG_DIAL_ONLY=engine-guest` unless `BBOX_HOST_LAN_ADDR`
   and `BBOX_HOST_UDP_PORT` say a UDP port is forwarded). vps1 publishes `console.staging…:51830` and
   listens. Either direction of the flow ends the same way, because the decision asks who can be
   reached (`pair_api.claim` + `net.dialable_from_here`, lnk-032).
2. The Mac's record must not already exist here (it does not — that is D5), and the Mac must hold no
   `vps1` record (its 2026-10-08 record was removed on the HP's side; ours was never written). If a
   record does exist on either end, the pairing replaces it (`replace: true`) — that is `lnk-028`.
3. Nothing else: no port to open on the home side, no firewall step, no command on the Mac's machine.

## 6. How to prove it over time

```bash
./bbox dgo link status                  # per pair: tunnel, handshake age, door, catalog (now)
./bbox dgo link history                 # the transitions, with the cause (to be built — §4.4)
curl -s http://dgo-extend:8983/api/link | jq '.items[] | {office, verdict, tunnel, delivery}'
./bbox dgo test fresh                   # the pairing decision, on the live office, against throwaways
```

The acceptance this document sets for itself: a link that survives a week without a human, and a
record that says, for each minute of that week, whether the link was up and who repaired it.
