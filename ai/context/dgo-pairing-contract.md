# Pairing two installed offices from their screens — the contract (2026-10-04)

**Owner's direction (2026-10-04):** an office is installed on the target machine first, and is then
linked to the main office *from inside the offices* — no SSH, no commands. Access to the machine comes
*through* the link afterwards. Both orders ("machine first, then office" via `computers`, and "office
first, then link" via this pairing) must end in the same result.

This file is the interface between the two lanes that build it. A change to a field is a commit here.

| Lane | Owns |
|---|---|
| **pairing** (Claude Code on the HP office) | `apps/dgo-extend/{pairing.py, pair_api.py, declaration.py (validate_paired), static/connect.*}`, `tests/pair_contract.py`, the `dgo-net` port publication in `docker-compose.yml`, the three guards in `app.py` |
| **tunnel** (עזריה on the MacBook office) | `apps/dgo-extend/{net.py, tunnel-entrypoint.sh, firewall.py, linkproxy.py, link-proxy.py, projection.py, converge.py}`, `platform/manager/serve.py`, and in `app.py`: `render_tunnel`, `render_link_proxy`, `api_link` |

## What was measured before any of this was written

* `POST /api/pair/offer` and `/api/pair/claim` → **404** on both offices; `pairing.py` was imported by
  nothing but its own gate; `connect.js` spoke `dgo1:` (`office_id`, `identity_pubkey`, …) while
  `pairing.py` wrote `DGOPAIR1:` (`offer_id`, `office`, `identity`, …). Two passing selftests, and a
  pairing that could not start — no test crossed the two languages.
* A peer could not be stored without a machine: `validate()` requires `machine` + a real domain.
* The Mac engine accepts nothing inbound (Lima forwards TCP 80/443 to loopback only); Windows drops
  every inbound packet until an administrator adds a rule (Hyper-V firewall, default inbound Block).
  ICMP Mac → HP answers; TCP/UDP do not.
* `net.render` cannot render two peers on different slots (`same=False` → `pair=None` → `NetError` on
  the peer that shares the home slot). A second link needs an interface per pair.

## A — the paired record (`kind: paired`)

Written by `pair_api` through `declaration.validate_paired()` into `/data/dgo/<peer id>.yaml`:

```yaml
id: hp-laptop                 # the PEER's office id
label: "HP"
kind: paired                  # explicit — every reader of declarations() branches on it
pair_id: 7f3a…                # the offer's id; the same pairing confirmed twice is idempotent
identity: {ed25519: …, wg: …, fingerprint: 3A4B-3343-4492-5A1A}   # the PEER's public identity
tunnel:
  slot: 3                     # the pair's /24 (10.79.<slot>.0/24), free on BOTH offices
  side: 1                     # THIS office's side of the pair: host = 1, joiner = 2
  role: host                  # THIS office's role in the pairing: host (it read the offer) | joiner
  dial: host                  # who dials: host | joiner | relay — ONE fact, identical on both ends
  endpoint: 192.168.16.102    # the LISTENING side's host/IP (no scheme, no port); "" when relayed
  port: 51830                 # the LISTENING side's published UDP port; null when relayed
  listen_port: null           # THIS office's own UDP port in the pair: = port on the side that
                              # listens, null on the side that dials (derived by validate_paired)
links: [{office: macbook, direction: serve}]   # ONE link, to this office, from the PEER's point of view
paired_at: 1791140000
```

* **`side` and `role` describe the office that HOLDS the file — not the peer the file is about.**
  On hp-laptop the record `macbook.yaml` says `side: 2, role: joiner`: hp-laptop is `10.79.<slot>.2`
  and macbook is `.1`. (Measured 2026-10-04 on hp-laptop against a test host: the first multi-pair
  render read `side` as the PEER's and produced `self: 10.79.3.1` with `dial: home` toward the
  office's own address.)
* This office **dials** iff `tunnel.dial == tunnel.role`. Otherwise it **listens**, on
  `tunnel.listen_port` (= `tunnel.port`; compose publishes it — see C).
* `endpoint`/`port` are the LISTENER's address on BOTH records — identical on the two ends. They are
  never "empty means the peer dials": on the listener's own record they name the listener itself, and
  dialing them would be dialing oneself. Who dials is `dial` vs `role`, and nothing else.
* This office's tunnel address is `10.79.<slot>.<side>`, the peer's is the other one. Nothing may
  assume `.1`.
* No `machine`, `domain`, `path`, `source`: `validate()` never sees these records; `PUT
  /api/office/<id>`, `DELETE /api/office/<id>` and `/converge` refuse them (409) and name the right
  route.
* The link token is **not** in the record. It is the vault instance **`dgo_link-<peer id>`**
  (protocol `dgo_link`), same value on both offices.
* A paired record's slot counts as used (`pair_api._taken_slots` unions every record's slot with the
  home slot, and the host also avoids the joiner's `used_slots`) — and so does the slot of every
  tunnel ADDRESS the office holds. The far end of a link another office converged has the tunnel on
  its machine and no record of it: its offer named nothing, and the first direct pair hp-laptop↔vps1
  landed on slot 2, the slot of vps1's link with the MacBook — two tunnels on one /24 there, and
  every app of the MacBook's behind vps1 answered «Bad Gateway» (2026-10-08).
* The direction is said by the office that OFFERS, about itself (`offer {direction: "use"}` = "I
  will use"); the office that claims gets the mirror unless it says its own.
* A pairing never overwrites a record silently: same `pair_id` → idempotent; anything else under that
  id (another pairing, or an office installed through `computers`) → 409 until `replace: true`.

## B — the pairing (`/api/pair/*`), visual in both directions

Format: `pairing.py` is the source of truth. `DGOPAIR1:` + base64url(JSON) is an **offer**,
`DGOPAIRR1:` + base64url(JSON) is a **reply**. Whitespace anywhere is ignored (the screen shows six
groups). `tests/pair_contract.py` runs the server's output through the page's reader and back, and is
check `c_pair_contract` of `bbox dgo test 3`.

| Step | Who | Call | Answer |
|---|---|---|---|
| 1 | joiner | `POST /api/pair/offer {direction?}` | `{rendezvous_id, text, offer, expires_at, listens}` |
| 2 | host | `POST /api/pair/claim {text, direction?, replace?}` | `{rendezvous_id, code, peer, reply_text, tunnel, expires_at}` |
| 3 | joiner | `POST /api/pair/reply {text}` (or `/api/pair/offer/<rid>/reply`) | `{state: claimed, rendezvous_id, code, peer}` |
| 4a | host | `POST /api/pair/claim/<rid> {confirm: true, code}` | `{ok, link, render}` |
| 4b | joiner | `POST /api/pair/offer/<rid>/confirm {code}` | `{ok, link, render}` |
| — | joiner | `GET /api/pair/offer/<rid>` | `{state: waiting\|claimed\|confirmed\|expired, code?, peer?}` |
| — | either | `GET /api/pair` · `DELETE /api/pair/<office>` | `{home, listen, items[]}` · unpair (record + token + re-render) |
| — | either | `POST /api/pair/home {label}` | `{ok, home}` — names THIS office (1–60 chars; see "The name" below) |
| — | either | `GET /api/pair/giving` · `POST /api/pair/giving {mode, apps[]}` | what THIS office gives (see "What an office gives" below) |

* **Offer** (public only): `offer_id, office, label, identity{ed25519,wg,fingerprint}, ephemeral,
  endpoints[], listen{endpoint,port}?, used_slots[], direction?, created_at, expires_at`.
* **Reply**: `offer_id, ephemeral, identity{…}, sealed{iv,ct,tag}, sig, host_sas`. `sealed` is the
  grant — `{offer_id, joiner, host, direction, token, host_ed25519, label, tunnel{slot, dial,
  endpoint, port}}` — encrypted to the offer's ephemeral key; `sig` is the host's Ed25519 signature
  over `sealed` and **is verified** before anything is derived.
* **Who dials** is decided once, by the host, in step 2: the joiner's `listen` if it published one
  (`dial: host`), else the host's own (`dial: joiner`), else **409** — a direct tunnel needs one
  reachable UDP port, and the refusal says which two variables set it. A dialing side's own port is
  never published (a home NAT rewrites it — measured 51830 → 51908).
* **…and "published" is not "reachable from here"** (2026-10-12, lnk-032; the pairing lane's
  `pair_api.claim`, the predicate in the tunnel lane's `net.dialable_from_here`). A peer at home
  publishes the address its own LAN knows it by, and no packet of a cloud office arrives there: with
  the joiner's address taken unconditionally, the office that no one can reach was made the listener
  and the public office the dialer, and the pair could never handshake while both screens said
  "paired" (measured on vps1 ↔ hp-laptop). So a PRIVATE address of the joiner's is chosen only when
  this office declares a private address of its own; otherwise this office listens and the joiner
  dials the address this office published (which the grant carries), and when neither is possible the
  claim is refused with the same 409, saying which address could not be used. An office that declared
  nothing keeps the old answer — it can only dial, and its peer's address is then the only one there
  is (the macOS engine).
* **The six digits** are computed independently on both sides from the ECDH secret and both identity
  keys. Each office writes **only on its own operator's confirmation**: the record, then the token,
  then `render_tunnel()`. A wrong code writes nothing.
* **Half pair**: one side confirmed, the other did not. It is a visible state (the record exists, the
  tunnel never handshakes) and is undone with `DELETE /api/pair/<office>` on the side that wrote.
* **State is in memory**, ten minutes. A restart of `dgo-extend` drops live offers and claims.
* `direction` is the **host's** sentence (`use`: the host uses the joiner's apps). The joiner's wish
  travels in the offer and is honoured (mirrored) when the host says nothing; default `both`.

### What an office gives (2026-10-05)

The owner's rule: *first choose give, take or both — and if give, which apps.* `direction` is the
first half; the second is the office's own `serve:` map in `home.json` — ONE declaration for the
whole office (it is not per peer), written only by `converge.set_home_serve`.

* `serve:` is what opens the catalog and the door on the tunnel side. An office that gives in a link
  and declared nothing answers nothing there, and its peer shows it as DOWN over a healthy tunnel
  (measured: the HP on the MacBook). So **confirming a pairing in which this office gives, when it
  has declared nothing and nobody chose, declares `{"*": {}}`** — the answer carries `gave_all: true`.
* An empty map means two things — "nobody was asked" and "the owner chose nothing" — so the choice is
  remembered apart from it (`/data/giving-chosen`). An office that chose, in either way, is left alone
  by every later pairing.
* `GET /api/pair/giving` → `{mode: all|some|none, chosen, count, total, apps: [{alias, app, name,
  given}]}`. `POST /api/pair/giving {mode, apps[]}`: `all` → `{"*": {}}` (apps installed later
  included); `some` → exactly the named apps, keyed by app id with the registry's `port` (and
  `agent_api_port`), keeping what was already declared about an app that stays given; `none` → `{}`.
* Tunnel lane: nothing new is asked of it — the same map, the same writer, the same render. What it
  already agreed to change is separate: a peer that gives nothing should read as "publishes nothing",
  not "down" (the catalog door open even when `serve:` is empty).

### The name (2026-10-05)

`home.json` holds „הלשכה הזאת” until somebody names the office — that is the office's word for
ITSELF. Published as-is it titled the peer's card and every served tile "this office" (measured: the
HP, which nobody had named, on the MacBook's screen). So:

* **An unnamed office publishes its id.** `pair_api.own_label(home)` is the one rule, and both the
  pairing (the offer's and the grant's `label`) and the catalog (`app._home_label`) go through it.
  `pair_api.UNNAMED` lists what does not count as a name.
* `GET /api/pair` → `home: {id, label, named, fingerprint}`. `named: false` means `label` is the id;
  the screen then says "this office has no name yet" instead of showing an id as if it were chosen.
* A **paired** card's title is what the peer publishes NOW (its catalog's `label.he`), then what it
  said when it paired (the record's `label`), then its id — and the placeholder is never believed
  (`Pairing._peer_label`). This is the opposite order from an INSTALLED office, whose label is this
  office's owner's own word. `GET /api/link` still answers the record's label first; a reader that
  shows a paired office to a person should take `GET /api/pair`'s.

## C — listening

An office that can be dialed declares it in `.env` (a container cannot learn its machine's address):

```
DGO_WG_ENDPOINT=192.168.16.102   # what the other office dials
DGO_WG_PUBLISH_PORT=51830        # UDP, published for dgo-net
DGO_WG_PUBLISH_BIND=0.0.0.0      # default 127.0.0.1 = nothing reachable
DGO_WG_PORT=51830                # the interface listens where the mapping lands
```

and its machine's firewall must allow that UDP port (Windows: one Hyper-V firewall rule, once, by an
administrator). An office that sets none of these only dials.

### Who can be dialed, and what an office says when it cannot (2026-10-05)

A tunnel needs ONE side that can be dialed. **Two offices that only dial cannot be paired** — and the
owner's test is "any two fresh offices on one network". What is true today, per kind of machine:

| The office runs on | Can it be dialed out of the box? | Why / what makes it so |
|---|---|---|
| Linux (a server, a desktop) | **yes** — a LOCAL office declares its LAN address by itself (`hooks/prepare`); a public server when its owner declares the address | nothing in the way |
| Windows, WSL in `mirrored` networking | **yes** — same hook; `bbox.cmd run` opens the UDP port in the Hyper-V firewall (one consent prompt) | mirrored mode shares the machine's ports with the distro |
| Windows, WSL in NAT (the Windows default) | **no — one command away** | nothing on the LAN reaches the distro. `bbox.cmd dialable` (`scripts/windows/wsl-mirrored.ps1`) writes `networkingMode=mirrored` under `[wsl2]` in the user's `.wslconfig` and restarts WSL (Windows 11 22H2+). It is a VERB, never part of `bbox run`: the file is the user's and governs every distro, and the restart stops everything in WSL — so it asks for a typed YES, keeps the file as it was (`-Undo`), and `-Check` only reports. Measured: its editing rules (self-test), `-Check`, and apply/undo on a scratch file. **The restart itself was not executed on the machine it was written on** (that machine hosts other stacks in the same WSL) |
| macOS (the Lima engine) | **no — one command away, on the Mac** | the engine forwards TCP 80/443 and nothing else, and its `portForwards` live in the INSTANCE's config — Lima refuses to edit a running instance, so an engine that predates the rule needs stop → edit → start. `engine.yaml` declares the tunnel's UDP port and `./bbox engine forwards --apply` applies it to the engine you have (then `bbox run`); `forwards` and `doctor` print the chain — instance declared · guest listening · Mac socket — and name the open link. See "the engine's half" below |

So today: Windows(mirrored)↔anything, Linux↔anything work from the screens with nothing typed
(HP↔MacBook is the proven case). Mac↔Mac, Mac↔Windows(NAT) and Windows(NAT)↔Windows(NAT) do not.

**How "fresh" is tested.** `bbox dgo test fresh` (`apps/dgo-extend/tests/fresh-offices.sh`) starts two
throwaway containers of this office's own app image — no network, state on tmpfs, an identity minted
on the spot — and carries the codes between them and the live office by hand: an office with no
identity refuses in words (409, the sentence names `bbox dgo identity mint`); two fresh offices get
different ids and say why they only dial; a fresh office and the live one arrive at the same six
digits; two offices that only dial are refused in plain words. Nothing is confirmed, so nothing is
written. It is the test that found an identity-less office answering every pairing route with a bare
500 (2026-10-05).

**An office that cannot be dialed says so, with why and what would change it** — before any code is
shown, not as a refusal after both codes were exchanged:

* `hooks/prepare` records the reason it declared no address: `DGO_WG_DIAL_ONLY=wsl-nat` or
  `=engine-guest`, in `.env`, under the same rule as the address (only for a local office, only when
  nothing else is declared, cleared on the first run in which the machine can receive). It never
  REMOVES a declared address — a detector that fails must not take a working office off the network.
  And it decides nothing when it is run from INSIDE a container (`/.dockerenv` — the office's own
  agent runs `bbox run` from its harness): there `ip route` answers a docker-bridge address and
  neither WSL's mode nor the engine's hand-off is visible, so only a run from the machine itself
  declares or records anything.
* `GET /api/pair` answers `dial_only: {why, reason, fix}` (`null` when `listen` is set). `why` is
  `wsl-nat`, `engine-guest`, `declared` (the owner's `DGO_WG_AUTO=0`) or `undeclared`; `reason` and
  `fix` are the sentences both screens show (`pair_api.DIAL_ONLY_HE`; a `backticked` run in them is a
  token to type).
* The pairing screen shows it under the office's own line, and when it READS an offer that names no
  address while this office is dial-only it says "both only dial" there and offers no button that
  would be refused. The server's refusal (409) stays as the backstop, in plain words.

**The engine's half (macOS) — what would make a Mac office dialable.** The hook already has
everything it needs except two facts the guest cannot see. If the engine forwards a UDP port from the
Mac's LAN interfaces into the guest, it says so in the guest's environment:

```
BBOX_HOST_LAN_ADDR=192.168.16.100   # the Mac's LAN IPv4 — what another machine on the network dials
BBOX_HOST_UDP_PORT=51830            # the UDP port the engine forwards to the same port in the guest
```

and `hooks/prepare` then treats the guest as a machine that can receive: it declares
`DGO_WG_ENDPOINT=$BBOX_HOST_LAN_ADDR`, `DGO_WG_PUBLISH_PORT=$BBOX_HOST_UDP_PORT` (bind `0.0.0.0`,
`DGO_WG_PORT` the same) and clears `DGO_WG_DIAL_ONLY`. Without both variables nothing changes: the
guest is `engine-guest`, as now.

**Built on both sides (2026-10-05).** `packaging/macos/engine.yaml` declares the rule —
`guestPort`/`hostPort` 51830, `hostIP: "0.0.0.0"`, `proto: udp`; UDP needs Lima's GRPC forwarder,
the default since v1.1.0, and 2.2.0 is the version this lane pins. `engine.sh` hands the two
variables across in the same `limactl shell` every command already goes through, and it hands them
over when the **instance** declares that rule and the Mac has an address — it does NOT wait for the
Mac to hold the socket, because the chain closes in one direction: rule → the office publishes the
port (the hook, which needs the hand-off) → something in the guest listens → Lima opens the Mac's
socket (only a `static: true` rule is bound at startup, and that path is TCP-only; every other rule
reaches the forwarder through a guest **port event**). Gating the hand-off on the socket would be a
closed loop, and a fresh Mac would stay `engine-guest` forever. The socket is a measurement instead,
and `forwards` prints the chain and names the open link. An engine created before the rule keeps its
old config (Lima stores a copy per instance, and refuses to edit a running one), so:

```
./bbox engine forwards           # the chain: instance declared · guest listening · Mac socket (+ the gap)
./bbox engine forwards --apply   # stop → edit → start → `bbox run`; run from the Mac's own Terminal
./bbox engine doctor             # the same facts beside versions and sizing
```

`--apply` converges the declaration only: an instance that already declares the rule costs no
downtime, and the socket follows on its own once the office publishes the port. A first `--apply`
takes the office down for the length of a boot (nothing in this stack declares a restart policy, so
no container returns on its own — the same run brings it back with `bbox run`), and macOS may ask for
incoming-connection consent on the first packet. Until it has run on a Mac, that Mac office is
`engine-guest` exactly as before: the template changes what the NEXT engine gets.

## What the tunnel lane needs to honour (from the record above)

1. interface per pair; own address from `tunnel.side`; the peer's `Endpoint` from
   `tunnel.endpoint:tunnel.port` when this office dials, `ListenPort = tunnel.port` when it listens;
2. every reader of `declarations()` handles `kind: paired` (no `machine` — nothing may SSH to it);
3. the live link to vps1 does not move.

## C2 — what a pairing makes visible, and how it is applied (2026-10-05)

* **What linked offices give is desired state, and `bbox run` converges it.** `hooks/project`
  (`bbox dgo project [--check] [--quiet]`, called by `hooks/prepare`) runs ON the machine: it asks the
  app for the block the projection wants (`sync()` answers `desired`) and runs the projection's own
  reader/writer payloads locally. An office with a working door to its own machine is still projected
  every minute by the app; one without (a Windows host has no sshd; a changed host key) is projected on
  every `bbox run`. Nothing is started or left running by it.
* **A second pair needs this office's own plan.** In the projected block, `address` (the peer's end of
  the pair's /24) and `link_port` (OUR door for that pair) come from `/tunnel/link-proxy.json`
  (`projection.own_plan` / `apply_plan`). What the peer publishes as `link.port` is ITS primary pair's
  door and is only a fallback.
* **On a `*.localhost` office a remote app is framed through the console's own origin**
  (`/a/<alias>.<office>/`, the console's same-origin proxy), because the nested host cannot authorize
  inside a frame there (`auth.localhost` is another site). The same answer holds wherever the nested
  host resolves nowhere — a console reached by a bare service name (`console:8000`, how anything
  inside the office's network reaches it, the office's own browser included) or by an IP address:
  the shell asks one question of its hostname (`noNestedHost`). The tile carries `proxy` and `door`
  (`serve.module_entries`); the console sends the mapped identity and the app's Host and strips this
  office's own sign-in cookies. **Trust statement:** on such an office, a paired office's app code
  runs in this console's origin, like a local app. Real-domain offices keep the nested host and the
  browser's origin isolation.
* **…except an app that owns its origin, which keeps its nested host on every console**
  (`serve.through_console`). The office agent's browser code addresses `/api`, `/plugins`, `/assets`
  and a websocket at the ROOT of its origin; on a console's origin that root belongs to the LOCAL
  agent (its `mount: root` passthrough). Measured 2026-10-05: the MacBook's בינה tile on hp-laptop
  loaded its page from the Mac and listed hp-laptop's two conversations — a message typed there would
  have run on the wrong machine — and the MacBook's המרכז tile drew a console inside the console
  that listed hp-laptop's apps. Three facts make the rule, each compiled and none hand-set:
  1. the serving office publishes `module.kind: external` for an app that is external at home, **is
     not embedded at home at all (`embed: false` — the console itself), or claims a root mount**
     (`reconcile._own_host_only`), and a consumer gives `proxy`/`door` only to an app that is
     embedded at home **and** names the authority it answers under (`host`);
  2. **the Origin goes with the Host.** A harness that checks who is calling compares `Origin` with
     `Host` (403 under a rewritten Host alone, 200 under `Host` + `Origin` of its own authority). So
     each remote router that rewrites the Host has an `-own-origin` twin: a request whose `Origin` is
     exactly the host it was sent to gets both rewritten; any other `Origin` arrives untouched and is
     the app's to refuse (measured on traefik v3.3 with the generated file: another site, a sibling
     app of another office and the same name on another port all keep their own Origin). With it, an
     app that publishes its authority needs no trust list on the serving office. An app published
     with NO `host` is still reached under the consumer's own authority, and then the serving office
     must have declared that authority itself (`BINA_DS_TRUSTED_HOSTS`);
  3. on a console where a frame cannot sign in (`noNestedHost`), the shell asks before framing: the
     tile names `signed_in` (`/.dgo/signed-in`), a path this office's edge answers itself — a
     redirect for an unsigned browser, an empty answer for a signed one, readable only by this
     office's console. Unsigned, the shell takes the browser there itself: a top-level load of the
     tile's `enter` path (`/.dgo/enter/<route>`), answered by this office's edge with its own
     sign-in — silent while that sign-in is alive — and then with the console again at that route.
     Once a minute per host; a host that still asks gets a card whose one button is the same trip.
     **The gate is never dropped to spare that trip:** the link's door trusts the office it serves,
     so this office's sign-in is the ONLY authentication between whatever reaches this machine's
     edge — any local process, any page open in a browser on it — and the other office's apps under
     the mapped identity;
  4. **an app that redirects to its own configured origin answers on the origin that was asked.**
     The browser is on the consumer's nested host, and a redirect to the app's home name leaves the
     session behind and lands on a name that is another office's, or nobody's (measured 2026-10-06:
     Plane's sign-in, `Location: http://plane.localhost/…` for every Host). It is fixed where the
     redirect is made — the app's own front (`apps/project-pln/Caddyfile`, `asked`), from the
     `X-Forwarded-Proto`/`-Host` the consuming edge sends — never by routing the home name on the
     consumer, which would give one name to two offices' apps.
* **A fresh office can be paired with nothing typed first:** `hooks/prepare` mints the identity when
  there is none; an office with no id gets `converge.default_office_id` (machine name, else key
  fingerprint) instead of `local`; a LOCAL office on a machine that can receive declares its LAN
  address in `.env` (`DGO_WG_AUTO=0` opts out; never for a real domain, the macOS engine or WSL NAT).

## C3 — what a linked office can reach, and as whom (2026-10-05)

A link has exactly two ways in, and each is closed to everything it was not made for.

* **The control door** (`<tunnel address>:8983`) leads to dgo-extend's LINK LISTENER
  (`catalog.LINK_PORT`, `app.link_app`), which serves the catalog and nothing else. It is a raw
  splice with no opinion about paths, and it used to lead to the app's own port: a pairing that
  gave ONE app handed the peer every route of dgo-extend, unauthenticated — declare and converge
  offices, move apps, read the stored login of an installed office. What a peer may ask is now a
  route on that listener, added there on purpose. The port on the wire did not change, so an office
  that predates this still pulls the catalog.
* **The door** (`9000+slot`, Host picks the app) reaches the apps this office GIVES, and the door —
  not the peer — says who is calling: every `X-authentik-*` header of the request is removed and
  the catalog's mapped user is written. Only `X-authentik-username` used to be replaced, so groups,
  e-mail and the signed token arrived as the other office's identity provider wrote them.
* **One request per connection, except a websocket** — decided from the whole handshake (`GET`,
  `Upgrade: websocket`, `Connection: upgrade`) and only once the app has answered `101`. The word
  `upgrade` alone used to keep the connection, and a second request on it was never rewritten.
* **The proxy follows the plan while it runs**: a rule that changes releases its port before the
  new listener binds, and a listener that could not bind is tried again — `plan applied` counts
  what is listening (`tests/phase3.py`: `c_proxy_reload`, `c_door_identity`, `c_link_listener`).
* **An agent API is a third way in, and only when it is named.** `serve: {"bina-ds": {"port": 3080,
  "agent_api_port": 3081}}` opens that one port to the peer's tunnel address — a CLI addresses a
  port, and the door cannot tell an adapter from the UI that shares its name. `*` does NOT include
  it, and the catalog publishes an `agent_api_port` only for an app whose `serve:` entry carries
  one: a port in the catalog is a port a peer builds a listener for (`c_catalog_served`).
* **Still the owner's decision, and worth knowing:** the first pairing declares `serve: {"*": {}}`,
  and `*` includes the apps that OPERATE the office — `app-management` (install and run apps),
  `computers` (commands on its machines), `connections` (its keys). That is "this is my other
  office". An office paired with somebody else's should name what it gives.

## C4 — an app on a linked office: placing it there, moving it there (2026-10-05)

**No shell, no SSH, no command on the other machine.** An office that GIVES its `app-management`
can have apps placed on it, and one that also gives its `data-management` can have an app's data
fetched from it. Everything below is those two apps' own APIs, called through the door a tile
already uses (`/a/<alias>.<office>/` on the calling office's console) — there is no second plane.

* **Enabling an app is its whole bring-up** (`POST /api/apps/<id>/enable`): `prepare` hook →
  containers (`scripts/dc`, built when the image is not there) → wait until they answer → sign-in
  for a host it gates (the sign-in app's own `hooks/refresh`) → `onboard` hook → automations. It is
  a JOB: the call answers within 20 s or says `202` with the step it is at, and
  `GET /api/apps/<id>/job` then answers exactly what the call would have.
* **Arriving with data**: `enable {"restore": {"archive": <name>}}`. Between the first answer and
  `onboard`, the office fetches that archive from the office that asked (`data-management`
  `POST /api/pull` — one GET per artifact, hashed against the manifest, the manifest written last)
  and restores it (`scripts/deployment-archive.py import --app`, the app's own `hooks/restore`,
  facts compared one by one). WHICH office is the link's answer: the door stamps `X-DGO-Office`
  on every request it carries, and that wins over anything in the body. Refused (`409`) when the
  office already holds data of that app.
* **Moving** (`POST /api/apps/<id>/move {"to": <office>}`, asked of the office that HOLDS the app):
  export here → `enable {restore}` there → switch off here. Nothing is deleted on either side; every
  failure before the last step leaves the app as it was found. The data is read from the app's
  RUNNING stores, so an app that is switched off here is refused (`409`) unless the call says
  `"wake": true` — then it is switched on for the read by the ordinary bring-up, and switched off
  again whether the move succeeds or fails. The apps screen says so before it asks.
* **Room.** `GET /api/apps/<id>/room` is an office's own answer to "would this app fit here now":
  what the app declares it needs (`resources` in its manifest, else the limits its compose file
  gives its services) plus 20% against the memory that is free, the load per core, and the disk
  left afterwards — read by the control plane from inside its own container, with no door to the
  machine. A refusal is a Hebrew sentence with the numbers in it (`admission.py`); an app that
  declares nothing is said to declare nothing, not to fit. The apps screen shows the answer under
  every office it offers and does not offer a linked office that says no; a move asks the
  destination before it exports a byte and is refused (`409`) unless the call says `"force": true`.
* **An app that an enabled app requires is not taken from under it.** The compiler keeps a required
  provider's services in the compiled office whatever its own line says (`reconcile.py required-by
  --app <id>` is the resolver's own answer to "who cannot run without this"). So the control plane
  refuses (`409`, naming them) to archive, remove or MOVE such an app, and switching it off writes
  the line and leaves its containers running — the answer carries `required_by`.
* **What an app-scoped archive may touch** is decided by the RECEIVING office's manifest of that
  app — its declared volumes, paths and databases — never by the archive's own word.
* **What an app must provide to be movable between offices**: a data directory of its own database
  carries the password it was initialised with, so the database travels as a DUMP that
  `hooks/restore` loads into the receiving office's own cluster (`apps/project-pln/hooks/` is the
  worked example: `backup` claims the db volume, `restore`, `facts`).
* **An office reaches its OWN state through its control plane**, not through a door to its machine:
  the projection reads and writes the `remote:` block at `GET/PUT /api/remote` (the compiler
  validates before it writes) and applies with `POST /api/apps/dgo-extend/apply`. A request that
  crossed a link may not write that block.
* **A door carries an answer however long it takes.** The head's read timeout used to stay on the
  socket and cut everything slower than five seconds — which is every one of the calls above.

Proven by the first move (project-pln, MacBook → hp-laptop, 2026-10-05): 40.7 MB over the link,
nine facts equal, the source's copy switched off with its volumes kept, the agent's own API key
still working against the app on the other office. `ci-artifacts/dgo-pair-proof/app-move/`.

## D — the invite: ONE code that carries the address and an access key (DESIGN — not built)

**Owner's model (2026-10-04):** the reachable office shows a barcode, or hands over a code as text,
that holds *the address and an access key*, valid for a time chosen when it is made (default one
week, or unlimited). The other office reads it and is connected — both then show a connected office.
It must be the same implementation on a private LAN and for a public VPS.

Why the two-code pairing (B) does not already do this: it needs both screens at the same moment and
two transfers, because nothing may cross a network before the tunnel exists. An invite removes the
second transfer by putting into the code the one thing the host otherwise has to learn first — a
WireGuard key it can pre-authorize.

**The invite is a bearer secret.** Whoever holds it can link an office to the inviting one until it
expires or is used. That is the owner's stated model; the screen must say it in those words, an
invite is single-use, and it is listed (and revocable) on the inviting office until redeemed.

### Format

`DGOINV1:` + base64url(JSON), whitespace ignored — the third prefix beside `DGOPAIR1:`/`DGOPAIRR1:`:

```
invite_id      32 hex
office, label  the INVITING office (own_label)
identity       {ed25519, wg, fingerprint}        the inviting office's public identity
endpoint, port where its tunnel is dialed (its `listen`) — an office that cannot be dialed cannot invite
slot           the pair's /24, chosen by the inviter from 100–250 at random among its free slots
               (it cannot know the reader's slots; a clash is refused on redeem with "ask for a new one")
key            a WireGuard PRIVATE key minted for this invite — the access key. The inviter keeps only
               its public half, in the pending record
token          the link token (same role as in a reply's grant)
direction      the INVITER's sentence: use | serve | both
expires_at     unix time, or 0 = unlimited
sig            Ed25519 over the canonical JSON of everything above, by the inviting office's identity
```

### Flow

| Step | Who | What |
|---|---|---|
| 1 | inviter | `POST /api/pair/invite {direction, ttl_seconds}` → writes a **pending** paired record under the placeholder id `invite-<8 hex>` (`identity.wg` = the invite key's PUBLIC half, `tunnel: {slot, side: 1, role: host, dial: joiner, endpoint, port}`, `invite: {id, expires_at}`), stores the token, renders. Answers `{text, invite_id, expires_at}` once — the private key is in `text` and nowhere else |
| 2 | reader | `POST /api/pair/invite/accept {text}` → verifies `sig`, the expiry, a free `slot`; writes its paired record of the inviter (`side: 2, role: joiner`, `tunnel.key: invite`), stores the token and the invite key in the vault (`dgo_link-<office>`, `dgo_invitekey-<office>`), renders — and its tunnel dials with THAT key |
| 3 | reader → inviter, **over the tunnel** | `POST /api/pair/invite/redeem {invite_id, office, label, identity, sig}` through the pair's control door. The inviter checks the caller came from the link on that pair's address, the invite is live and unused, and the signature; renames the pending record to the reader's office id, stores its public identity, marks the invite used |
| — | inviter | `GET /api/pair/invite` (pending, with expiry) · `DELETE /api/pair/invite/<id>` (revoke: record + token + render) · expiry is enforced on render: an expired pending record is removed |

Both offices then hold an ordinary `kind: paired` record of each other; unpair is the same act as today.

### What it needs from the tunnel lane (two things, both small)

1. **A per-pair private key.** A record with `tunnel.key: invite` is rendered with the private key the
   vault holds for that pair (`dgo_invitekey-<peer>`), written to `/tunnel/keys/wg<slot>.key` (0600),
   instead of the office's identity key. Every other pair keeps the identity key. The invite key stays
   the pair's key for the life of the pair — nothing is swapped, so there is no moment when the
   tunnel has to be re-keyed over itself.
2. **The control door is open for a pending pair** (8983 from the pair's peer address) even when this
   office gives nothing — the redeem call is the first packet the reader sends, and it must not depend
   on `serve:`.

A gate for each: a rendered pair with `tunnel.key: invite` uses the pair's key file and no other pair
does; and pair → revoke → no peer, no listener, no key file.

### Not decided here

An invite for an office that cannot be dialed (the Mac engine) — it would need a relay or a third
office; out of scope until an office of that kind has to invite.

## E — §9 the trust boundary of a paired office (security) (2026-10-09)

sec-010: the MacBook's agent read hp-laptop's `/api/instances` through the link (2026-10-04). That is
the trust two paired offices of one owner have **by design** — and this section writes down exactly
what a `kind: paired` office may READ and DO in the office that holds its record, so the design is a
choice and not a surprise. It consolidates C3 (the two doors) and C4 (lifecycle); each fact below is
guarded by the test named in brackets.

* **The record grants no machine.** A paired record carries no `machine`/`domain`/`path`/`source`
  (section A), so **nothing may SSH to a peer** ("What the tunnel lane needs to honour" #2) and
  `PUT`/`DELETE /api/office/<id>` and `/converge` refuse it (409). A peer's machine is reached only
  through the two tunnel doors below. [`declaration.selftest_paired`]
* **Door 1 — the control door (`<tunnel>:8983` → `catalog.LINK_PORT`) serves ONE thing: the catalog.**
  `link_app` exposes exactly `GET /api/link/catalog`, scoped to the calling office (`x-dgo-office`,
  written by the link proxy, never taken from the peer). A route not on that listener does not exist
  for a peer. This is the fix (2026-10-05) for the hole where the door led to dgo-extend's own port
  and a pairing that gave ONE app handed the peer every route — unauthenticated, the stored login of
  an installed office included. **So a peer cannot read `/api/instances`, the vault, or any dgo-extend
  control route through the control door.** [`tests/phase3.py: c_link_listener`]
* **Door 2 — the app door (`9000+slot`, Host picks the app) reaches ONLY the apps this office SERVES,
  as the mapped identity.** The `serve:` map (`home.json`, `converge.set_home_serve`) is the whole of
  it; the door — not the peer — says who is calling (every `X-authentik-*` header stripped, the
  catalog's mapped user written). An agent-API port is reached only when `serve:` names it; `*` does
  not include it. [`catalog.selftest: c_catalog_served`; `tests/phase3.py: c_door_identity`;
  `tests/test_link_security.py`: the door's own route table refuses a name that is not served, the
  mapped user is written per app from the catalog, and the consuming edge puts `authentik@file`
  BEFORE the mapping — which is why a forged `X-authentik-username` is irrelevant, not trusted]
* **The identity mapping is published by the SERVING office and read by the far edge.** What crosses
  is `identity.to` (a user vocabulary) and `identity.from` — never a credential; the catalog is an
  allow-list over the registry, so a secret in an app's row does not cross at all, and an agent API
  publishes the NAME of a vault entry (`bearer:vault:<app>`), not its value. **`from` crosses in a
  shape the far end cannot read, measured 2026-10-11 (DGO-49): `catalog.build` publishes it as a
  LIST (`apps/dgo-extend/catalog.py:161`) while `platform/manager/serve.py:357` reads one header
  string, so an office that declares a `from` makes the consuming office raise
  `TypeError: unhashable type: 'list'` instead of compiling. Kept as a FAILING test and reported:
  [`tests/test_link_security.py`: xfail “the identity mapping crosses the link in the shape the far end
  reads”].** [`tests/test_link_security.py`: no secret crosses]
* **What this means for secrets, `/api/instances`, and the machine plane.** A peer reads the vault
  (`/api/instances`, the `connections` app), installs and runs apps (`app-management`), or runs
  commands on machines (`computers`) **only if that app is in `serve:`** — and **`serve: {"*": {}}`
  includes all three.** That is the owner's "this is my other office", and precisely why the MacBook
  read hp-laptop's `/api/instances`: the two offices paired with `{"*": {}}`. **An office paired with
  someone ELSE'S must name what it gives, narrowly, and never `*`** — a serve that names apps gives
  only those, never the control/vault/machine plane. [`tests/pair_contract.py: §9 paired boundary`;
  `tests/test_link_security.py` asks the same question of the door itself, and of the plan's listeners]
* **Lifecycle verbs** (enable / move / remove an app on a linked office) are the `app-management` +
  `data-management` APIs (C4), reachable only when those apps are served. A request that **crossed a
  link cannot write this office's OWN state**: `PUT /api/remote` and `POST /api/apps/dgo-extend/apply`
  refuse it, a move is never handed on from a request that itself arrived over a link, and a required
  provider is never taken from under a dependent (409). **MEASURED AND HALF-CLOSED, 2026-10-09
  (DGO-49): `PUT /api/remote` always carried the guard; `POST /api/apps/<id>/apply` did NOT
  (`platform-base/app-management/app.py:api_apply`), so a peer served `app-management` could make
  this office recompile and recreate containers — the guard was added the same day, it now answers a
  linked caller 403, and the claim is ASSERTED rather than xfail:
  [`tests/test_link_security.py`: “a request that crossed a link cannot write this office's own
  state”]. **CLOSED FOR THE WHOLE CLASS, 2026-10-11 (DGO-49):** the route's eight siblings answered a
  linked caller — `enable` without `restore`, `disable`, `archive`, `unarchive`, `uninstall`, `move`
  (`move` is exactly the one this sentence names), `catalog/install` and `POST /api/reconcile` — and
  every one of them now refuses it in the same shape as `api_apply`, each with its own sentence. The
  list is not kept by hand any more: **G85 (`scripts/refactor/link-write-guard-lint.py`)** reads
  `app.py`, takes every route from the file with `ast`, computes the class (a call-graph walk to the
  file's write sinks, plus every write verb) and FAILS for any of them that neither refuses a linked
  caller nor carries a written justification — it named all eight on the pre-fix file. One route is
  deliberately still reachable from a peer, and that is the exception §9 needs: `enable` **with**
  `restore`, because a move places an app here with its data (`app.py:_move` → `POST
  /api/apps/<id>/enable {"restore": …}`); a plain switch-on from a linked caller is refused, which is
  the difference between a read of the header and a refusal on it.**

**In one sentence:** a paired office may read and do **exactly what this office's `serve:` map names,
as the mapped identity, plus always the catalog — and nothing of this office's own control plane,
machine, or state**; with `{"*": {}}` that "exactly what is named" becomes everything, including the
vault and the machine-command plane, which is the trust two offices of one owner choose on purpose.

<!-- tunnel lane: add your section below -->
