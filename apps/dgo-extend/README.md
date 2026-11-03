# dgo-extend — הרחבת הלשכה

Other digital offices, linked to this one. An office is one `./bbox run` on one machine; this app
is where a second office is **paired** or **declared**, where the link between two offices is
rendered and kept true, and where the apps the other office gives are turned into tiles here.

Agents operating it read [AGENT.md](AGENT.md) (verbs, endpoints, traps). This file is the map: what
the app is made of, which file owns which fact, and what is no longer true.

## Two kinds of linked office

| | **paired** | **office** (declared) |
|---|---|---|
| What it is | an office installed on its own machine, by its own owner | a machine in `computers` that THIS office installs |
| How it joins | the pairing screen (`/connect`): QR, camera, or the same offer pasted as text; both screens show the same six digits | a declaration (`/data/dgo/<id>.yaml`) converged over SSH |
| Who runs it | itself. Nothing here installs, converges or reaches its machine. **No SSH.** | this office: `machine → dns → backup → code → engine → env → login → state → run → accounts → link → health → publish` (`converge.STEPS`) |
| Example | hp-laptop ⇄ MacBook (paired 2026-10-04) | vps1 |

Both kinds get the same link.

### A third way in: JOINED, by declaration (join_api.py, 2026-10-19)

An office that can only dial and has nobody at its screen — a Claude cloud sandbox, CI, a laptop on a
hotel network — **declares** the office it belongs to, and links itself when it is up:

```bash
DGO_JOIN=DGOJOIN1:…                                  # an invite: joins with nobody looking
DGO_JOIN=https://link.staging.digital-office.co.il   # asks; a person approves it on that office's screen
DGO_JOIN_PIN=CHANGE_ME                     # that office's fingerprint: a reply from any other is refused
DGO_JOIN_DIRECTION=both                              # what it asks for (the host decides)
```

in `.env` or in the environment it runs in (a cloud environment's variables). What runs is the
pairing above — the joiner's offer, the host's sealed and signed reply, the same records and tokens —
carried over HTTPS to the host's **link door** (`link.<domain>`, `DGO_LINK_HOST`), with the one human
step replaced: an **invite** (an Ed25519 key in the code; the host keeps only its public half; one
office id, one direction, an expiry, single-use or reusable for a sandbox reborn with new keys,
revocable) or a person's **approval** of the request (the device-code pattern; no secret anywhere —
the fingerprint shown on both sides is what is compared). The pair rides the carriers' TCP path
through the same door (`wss://link.<domain>/carry`), so any number of offices join on 443. A password
is never accepted: why is in join_api.py's docstring.

## The link, hop by hop

```
 this office                                                   the other office
 ┌──────────────┐   wg<slot> · 10.79.<slot>.0/24 · one /32 per side   ┌──────────────┐
 │ console tile │──▶ door (dgo-link) ══▶ tunnel (dgo-net) ══════════▶ │ door ─▶ app  │
 └──────────────┘                                                     └──────────────┘
```

* **Tunnel** — one WireGuard interface per pair (`wg<slot>`, `10.79.<slot>.0/24`, `.1` and `.2`).
  It routes no subnets: a peer's `AllowedIPs` is its own single address. One side listens (a
  published UDP port, `DGO_WG_PUBLISH_BIND` / `DGO_WG_PUBLISH_PORT` in `.env`, and the machine's own
  firewall must let it in); the other dials and needs no open port. The dialing office tells the
  listening one where it reached it (`dials`, in its catalog answer), so a listener whose lease
  moved shows and offers the address it really has before its next run re-declares it.
* **The TCP path** (2026-10-19) — for a pair whose machines can never exchange a UDP packet (the
  MacBook's engine takes none in, the HP's Windows drops every one), the record says
  `tunnel.transport: tcp` on BOTH offices (`./bbox dgo link transport <office> tcp`). Nothing else
  about the pair changes: each end's interface sends to its own carrier (`dgo-carry`, `carrier/`,
  `Endpoint = 127.0.0.1:41800+slot`), and the two carriers hold one TCP connection between them.
  The office that can be reached accepts on 51443 (`DGO_CARRY_ACCEPT=1`; a MacBook through its
  engine's LAN door, `packaging/macos/lan-door.py`); the other dials the pair's address, or searches
  its own /24 for the peer when it has none. A carrier answers nothing to a connection that cannot
  name the pair and admits nobody who cannot prove its key, and WireGuard still encrypts every
  packet end to end. The carrier redials and searches on its own clock, so `heal_links` leaves a
  `tcp` pair alone; `carry-state.json` is what it measured, and the verdict's `carry` hop says it.
* **Permission** — a firewall rendered from the declaration and enforced where the packet ARRIVES.
  A token proves who is calling, not what they may do.
* **Delivery** — the door. It answers only for the apps this office `serve:`s, by host name, and a
  request arrives as the mapped user. A door that cannot deliver answers for itself: a card for a
  page request, a bare status for a call, and `X-Dgo-Door: no-app | app-down | unreachable` either way
  (`bad-head`, 400: a header line with a bare CR or LF in it, which an app would read as two headers).
* **What ONE office is given** — `serve:` is the office's one list, and two reserved keys narrow it:
  `exclude` (published to nobody) and `only` (`{"vps1": ["plane"]}`: that office is given exactly
  those; an empty list is "linked, and given nothing"; an office not named is given the list).
  It is enforced on the serving side alone, where the request arrives: each pair's door asks for
  its route table in its own office's name, so a name that office was not given is `no-app` there,
  and the catalog that office pulls lists only its own. The door writes which office is asking
  (`x-dgo-office`) and removes whatever the peer wrote — an office cannot ask for another's list.
  `POST /api/link/serve {"serve": {"*": {}, "only": {…}}}`; re-declaring `serve` without `only`
  keeps the narrowing, `"only": {}` clears it.
* **What it hands on** (2026-10-19) — a third reserved key, `shared`, gives the linked offices the
  apps OTHER offices gave this one: `"shared": "*"` or `["hp-laptop"]`, the two forms an older
  office that drives this one's far plan still reads (a map refuses that plan); absent hands on
  nothing. The link stays point-to-point
  (peer→peer packets are still dropped): the catalog grows a `shared` section per origin, the door
  answers each such app under ONE exact name, `<alias>.<origin>`, and hands the request to this
  office's own door to the origin with the Host the origin expects — so claude-cloud, linked to vps1
  only, opens `plane.hp-laptop` and `bbox project-pln tasks list` reaches the HP's Plane through
  vps1. ONE hop by construction (a section is built from what the origin published as its OWN apps),
  never back to the origin, never this app, an agent port or an identity (the origin's door writes
  that), and only an app that names its authority (`host: ""` trusts the consuming office's own,
  which the office in the middle cannot pass on); `only` narrows it by `<alias>.<origin>`. A
  two-label name the door does not hold is no-app, never its own app of that first label — a share
  that is gone does not open this office's Drive in its place. The origin sees the office in the
  middle (its mapping for it, `x-dgo-office`), so that office answers for what it hands on.
  `tests/test_reshare.py` runs it on two real doors.
* **A door with no tile** (DGO-945) — a fourth reserved key, `services`, gives a linked office a
  capability another office's machines call, not a screen: the transcriber, Meet's recordings, n8n's
  webhook receiver (an app's `capabilities[]` with `link: true`). Named or not given, never under
  `*`: `"services": {"workflow-hooks": {"to": ["vps1"], "paths": ["/webhook/meet-recordings"]}}`.
  `to` is who gets it (absent: `only` narrows it like an app); `paths` is all the door answers, held
  on the raw request line (no dot segment, no escape, no absolute-form target), and a bad path
  publishes no door at all. The catalog carries it as `services`, never in `apps`, so no tile, route
  or sign-in is drawn for it; the far office gets the alias `<capability>.<this office>` on its link
  proxy and nothing else. The service behind it sees no identity and no forwarding header from the
  peer, only `x-dgo-office`. Re-declaring `serve` without `services` keeps them;
  `"services": {}` clears them, and so does the screen's "give nothing". An office that gives only
  doors has chosen what it gives: a pairing never widens it to `*`. A path ending in `/` admits what
  is under it; any other path is that path alone. Declare a door only once both ends of the link
  run code that knows the key (an older office driving this one's far plan reads it as an app).
  `tests/test_link_security.py` (the door with no tile) runs it on the real door.
* **What is shown** — every 60 s the consuming side pulls each peer's **catalog** (a projection of
  that office's own compiled registry — never a second list) and declares it as the `remote:` block
  of `platform.state.yaml` through the control plane. Tiles are `<alias>.<office>`.
* **Is it up** — one verdict per office, used by every surface: `{ok, hop, why}` with `hop` one of
  `tunnel` (no catalog, and no handshake for three minutes **or nothing measured** — unmeasured is
  not "alive"), `office` (silent behind a MEASURED handshake), `door` (this side's door is not
  listening) or `pair` (this office dials a private address it is not on: the pair was written the
  wrong way round, and no repair here helps). `why` is the same answer for a person (`app.py:_HOP_HE`),
  and the console marks that office's tiles from it. An office that has only just gone silent is asked
  again every 8 s for five passes (`QUICK_RETRIES`), and until they are spent it is unmeasured
  (`ok: null`, «ממתינה לחיבור») — one failed pull is not a verdict. `tunnel.handshake_age_s`,
  `delivery` and `state_error` sit beside it.

### The door's signature (DGO-545)

The door writes the mapped user for every request that crosses a link (`x-authentik-username`), and
any container on this office's network can write that header too — so an app that has to believe it
cannot trust the bare header. Over a link there is no cookie to ask this office's provider about: the
person was authenticated by the OTHER office, whose answer is not ours to verify. So the door PROVES
what it writes, with the pair's own secret from the credential plane (`dgo_link*` — the value the
pairing exchanged, or the one a converge wrote for a declared office; both ends hold it):

```
x-dgo-identity: v1 <office> <user> <unix-seconds> <hex hmac-sha256 of "v1\n<office>\n<user>\n<ts>">
```

* The door strips any incoming `x-dgo-identity` and the whole `x-authentik-*` family first, then
  writes its own — a peer cannot supply one, and a container in this office cannot compute one.
* 300 s is as long as a signature is good for; a pair whose secret cannot be read is written UNSIGNED
  and says so in the log (an identity nobody can check is not an identity — the app asks for a
  sign-in instead, which is the state before this existed).
* The reader is `apps/project-pln/office_identity.py` (its own copy of the secret, from its own
  vault): it signs the mapped person into Plane, which is what makes «ניהול פרויקטים» open from a
  linked office's console with no form — and what lets that office's agent read and write work items
  here with no token. Any app needing the same thing reads the header the same way: this format is
  the contract, and `apps/project-pln/hooks/verify` asserts both halves of it
  (`project-pln-link-identity`, `project-pln-link-identity-forged`).

## Who owns what

| File | Owns |
|---|---|
| `app.py` | the HTTP API and the screens; the verdict (`_verdict`), and every route of the link plane |
| `identity.py` | one Ed25519 key and one WireGuard key per office, in the `dgo_identity` volume — declared in `app.json` → `data.volumes`, the inventory `bbox export` tars (`scripts/deployment-archive.py`, `declared_volumes`) |
| `pairing.py`, `pair_api.py` | the pairing offer (public material only — a QR is a photograph), the rendezvous, the six-digit confirmation, the grant |
| `declaration.py` | the rules a declaration must satisfy, as pure functions (slots, sides, ports) |
| `links.py` | the token of ONE direction of ONE link — a row in the credential plane, never in a file |
| `net.py` | what the tunnel must be: interface, addresses, listen port, per pair |
| `firewall.py` | what one link ALLOWS (permission), rendered as nftables rules |
| `linkproxy.py` | the delivery PLAN: which door listens where, for which app (`link-proxy.json`) |
| `link-proxy.py` | the process that APPLIES that plan in the tunnel's network namespace (the `dgo-link` container) |
| `catalog.py` | what an office says about its own apps (serving side), and what a peer accepts it saying (consuming side) |
| `projection.py` | pull each peer's catalog; write `remote:` here through the control plane |
| `converge.py` | the fixed, idempotent steps that install and update a DECLARED office over SSH |
| `move.py` | the SSH mover for a declared machine: stop → volumes → start there → health → rollback |
| `peers.py` | the published link state the console reads (`peers.publish_link` → `/data/peers/link.json`, one row per office, rewritten after every projection pass) — and the **retired** model: placement (an app that runs there behind a token door). Do not add placements |

`linkproxy.py` and `link-proxy.py` are two halves on purpose: the one that plans has an opinion and
no network; the one that applies has the network and no opinion, so a change of plan is a re-render
and never a new container.

## Containers

| Service | What it is |
|---|---|
| `dgo-extend` | the app: API on 8983, the two screens (`static/index.html`, `static/connect.html`) |
| `dgo-net` | the tunnel: holds the `wg<slot>` interfaces (`NET_ADMIN`, `/dev/net/tun`), publishes the one UDP port of an office that listens |
| `dgo-link` | the door: lives in `dgo-net`'s network (`network_mode: service:dgo-net`) and applies the delivery plan |
| `dgo-carry` | the TCP path of a `tcp` pair (`carrier/`, Go, stdlib only, a scratch image): lives in `dgo-net`'s network, reads `carry.json`, writes `carry-state.json`; on an office with a link host it is also the **link door** (`door.go`, 51445, never published, behind the edge's `link.<domain>`): a carrier's websocket on `/carry`, join requests on `/join` passed to the app, 404 for everything else |

The first three run the same image; `dgo-carry` is built from `carrier/` and tests itself in its build. `scripts/dc` re-creates `dgo-link` whenever `dgo-net` is replaced —
a container that lives in another's network follows it. After rebuilding the image, bring the
tunnel's two containers onto it too (`./scripts/dc up -d dgo-net dgo-link`); re-creating `dgo-net`
drops the learned endpoint until the dialing side handshakes again.

Volumes: `dgo_extend_state` (declarations, pulled catalogs), `dgo_extend_peers` (the published link
state), `dgo_identity` (the keys — read-only to the app), `dgo_tunnel` (the rendered tunnel,
firewall and delivery documents).

## Verbs

```bash
./bbox dgo                        # this office and its linked offices
./bbox dgo link status            # per pair: the link as DECLARED (office, slot, endpoint, direction, fingerprint) and what is MEASURED (answers, handshake age — DEAD when stale)
./bbox dgo link up|down <office>  # kind: office only — a paired office is refused (409, _PAIRED_REFUSAL) and is unpaired on its own screen
./bbox dgo link transport <office> tcp|udp   # the pair rides the carriers' TCP path, or WireGuard's own UDP — said on BOTH offices
./bbox dgo join                   # the link door, the join requests waiting, the invites, who joined
./bbox dgo join approve|refuse <office>      # a request that asked without an invite
./bbox dgo join invite <office> [--reusable] [--direction both] [--ttl 7d]   # prints DGO_JOIN=… once
./bbox dgo join status            # where DGO_JOIN is declared: waiting / joined, and the fingerprint to compare
./bbox dgo identity fingerprint   # who this office is
./bbox dgo project [--check]      # pull the catalogs now / say whether the state file is current
./bbox remote <office> <alias> [path]   # that app's doors; with a path, one authenticated call
```

Each verb is a hook under `hooks/` and runs on the machine: `state` (the default), `link`,
`identity`, `project`, `test`; `prepare` and `migrate` run at bring-up (the rename from `offices`).

## Tests

| Run | What it holds |
|---|---|
| `./bbox dgo test 0` | phase 0, and the frame every phase uses (`tests/phase0.py` is the runner: a check returns ok + what was measured, every check runs, the exit code is the answer) |
| `./bbox dgo test 1` | tunnel and link: a stable identity that is in the backup, both ends answer a ping THROUGH the tunnel, a forged source drops, a revoke takes the peer down on both sides, the door says why when it cannot deliver |
| `./bbox dgo test 2` | the portable office: a machine on the LAN becomes a linked office |
| `./bbox dgo test 3` | the reverse direction and pairing: the `serve:` rules and their refusals, and §9's trust boundary (`tests/test_link_security.py`) |
| `./bbox dgo test fresh` | two brand-new offices, as real processes, pair through the real API |
| `./bbox dgo test pair` | the same two throwaway offices, paired the way a PERSON does it — each one's `/connect` page, the buttons the owner presses, recorded to a film (`tests/pair-video.sh`) |
| `python3 apps/dgo-extend/tests/pair_contract.py` | the pairing codes, through BOTH languages (server and screen) |
| `python3 apps/dgo-extend/tests/test_link_security.py` | §9 of the pairing contract, one test per claim — prints `XFAIL` with the code path for a claim the code does not hold |
| `node apps/dgo-extend/tests/connect-selftest.mjs` | the offer format the screen reads and writes (gate G72 runs it) |
| `tests/move_acceptance.py`, `tests/move_back.py` | an app moves to another office WITH its data, and back — on real machines |

`./bbox dgo test <n>` for n ≥ 1 runs REAL link verbs on the live office. Read the phase file first.

**§9's trust boundary: all fourteen claims hold.** They are tests here, not prose:
`tests/test_link_security.py` prints an open claim as `XFAIL` with the code path named, and every
`PASS` line is a claim that does hold. Last run, 2026-10-14, on a fresh
`git clone --no-hardlinks` of `vps1-dgo`: `14 claim(s), 14 pass, 0 xfail (documented gap(s) still
open), 0 fail` (exit 0), at `3d3c8b77` (the commit that fixes the mapping) and again at `37b51a23`
(once this paragraph was corrected) — a claim that only holds on the desk it was measured on is not
a passing claim, so the clone is the run that counts.

* **Closed** — a `serve:` identity's `from` used to cross the link in a shape the far end could not
  read: `catalog.build` publishes it as a LIST (`catalog.py:161`) while `platform/manager/serve.py`
  built a set out of it and sorted that (`"from": sorted({…})`, line 392 today), so it raised
  `TypeError: unhashable type: 'list'` and the consuming office could not compile the peer at all.
  Closed at `serve.plan`'s own intake of the mapping, which reads both shapes — committed as
  `3d3c8b77`. Until that commit the fix lived only in an uncommitted work tree, so the claim passed
  on the desk it was measured on and failed on the tip anyone else would clone: the claim reads
  `PASS` now, from a fresh clone of the pushed tip.
* **Closed** — `POST /api/apps/<id>/apply` used to carry no link guard while its twin `PUT /api/remote`
  (`platform-base/app-management/app.py:api_remote_put`) refused the same caller with 403. Since
  `e5f8dbac` (2026-10-09) `api_apply` answers 403 to a request that carries the link's office header:
  «a request that crossed a link cannot write this office's own state».
* **Not the red one** — this section used to name the door claim as the failing one. It is not: with
  `serve: {"drive": {"port": 8975}}` the real door (`link-proxy.py`'s `Door`, its route table built by
  `catalog.build`) routes `drive.localhost` to `drive:8975` and answers `HTTP/1.1 404` with
  `X-Dgo-Door: no-app` for `connections.localhost`, `apps.localhost`, `computers.localhost` and
  `bina.localhost` — the claim `PASS`es. The one claim that failed was the mapping above, and an
  accusation aimed at a module that is correct costs the next reader the time it takes to find that
  out for themselves.

A fix that closes one turns it into `XPASS`, which FAILS until the marker is removed — a gap cannot
be closed quietly, and a marker cannot be left behind.

`AGENT.md` is the brief the compiler injects into every agent session, under a 6000-byte budget
(`reconcile.MAX_BRIEF_BYTES`, `reconcile.py:60`). This app's is 5985 (`wc -c`, 2026-10-14) — 15 bytes
of room, so anything added there has to be paid for by cutting something else, or `reconcile validate`
refuses the whole catalog.

## What is no longer true

* **Placement** (`peers.py`, the `placement:` key): an app that ran on a remote office and was shown
  here through a token door. Retired on 2026-10-01 — "apps just run where they run"
  ([dgo-remote-apps.md](../../ai/context/dgo-remote-apps.md)). New work uses `serve:` + the catalog.
* **SSH to a second office machine** ([SECOND-OFFICE.md](SECOND-OFFICE.md)): that office joined by pairing and
  runs no SSH server, by its owner's ruling. The document stays as the record of the declared route.
* **The state file written through `computers`**: `remote:` is written through the control plane
  (`PUT /api/remote` on app-management); an office with no door to its own machine still projects.

## Further reading

[ai/context/dgo-extend-plan.md](../../ai/context/dgo-extend-plan.md) — the design and its decisions ·
[dgo-pairing-contract.md](../../ai/context/dgo-pairing-contract.md) — what the two sides of a pairing
exchange · [dgo-remote-apps.md](../../ai/context/dgo-remote-apps.md) — the model of an app that runs
elsewhere and the whole data path.
