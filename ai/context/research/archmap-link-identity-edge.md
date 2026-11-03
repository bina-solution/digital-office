# DGO — links, identity and the edge: a decision map (read 2026-10-14, branch `hp-dgo`)

Read-only map for the architecture review. Every claim carries `file:line` from the working tree, or a
doc/issue line. "Lifetime" = `origin/vps1-dgo:ai/context/dgo-link-lifetime.md` (the 13 death modes).

## 1. Topology and data flow

```
 console tile  ─▶ traefik router (zz-serve.yaml, file provider) ─▶ alias <app>.<office> on dgo-link
   (consumer)        authentik@file · Host/Origin rewrite             (use rule, 10.79.<slot>.<peer>:900<slot>)
                                                                            ║ WireGuard wg<slot>, one /24 per pair
 serving office:   dgo-link Door :900<slot> ── Host picks app ── strips x-authentik-*, writes mapped user
                   + x-dgo-identity (HMAC, pair secret) ─▶ app container by name   ·   :8984 catalog (per asking office)
```

| Hop | Mechanism | Where |
|---|---|---|
| **Pairing** | `DGOPAIR1:`/`DGOPAIRR1:` + base64url JSON; offer = public material only; reply = grant sealed to the offer's ephemeral key, Ed25519-signed by the host, verified before use; six digits derived on both ends from ECDH + both identity keys; each office writes only on its own operator's confirmation | `ai/context/dgo-pairing-contract.md:81-111`; `apps/dgo-extend/static/connect.js:3-42`; `pair_api.py:16-22` |
| Roles | joiner POSTs `/api/pair/offer`; **host** claims, picks slot + who dials + mints the 32-byte token; both confirm with the code | contract `:86-96`; `pair_api.py:557-625` (claim), `:645-661` (host = side 1), `:522-546` (joiner confirm) |
| Dial direction | one fact on both records: the side that published a reachable UDP address listens; joiner's `listen` wins, else host's, else **409** | `pair_api.py:577-591`; contract `:56-61` |
| Slots | one `/24` (`10.79.<slot>.0/24`) per pair; `_taken_slots` = records + home slot + **every tunnel address held** + the offer's `used_slots` | `pair_api.py:256-289`, `:593-601` |
| Record | `/data/dgo/<peer>.yaml`, `kind: paired`, `side/role` describe the HOLDER; token NOT in record; same `pair_id` idempotent, else 409 until `replace` | contract `:28-77`; `pair_api.py:290-300`, `:302-338` (vault row first, record second) |
| **Tunnel** | sidecar `dgo-net` (NET_ADMIN, NET_RAW, `/dev/net/tun`); app renders `/tunnel/pairs/wg<slot>.conf`, entrypoint applies; `AllowedIPs` = single /32, no subnet routing | `docker-compose.yml:107-166`; `net.py:5-19`, `:133-147`, `:349-403` |
| Ports | pair port `WG_PORT=51820`; dialing side's own `ListenPort` = `DGO_WG_PORT`, derived `+slot`; `PersistentKeepalive = 25` on dialing side only; listener publishes `DGO_WG_PUBLISH_BIND:PORT/udp` (default loopback:51839 = nothing reachable) | `net.py:51`, `:63-106`, `:400-403`; `docker-compose.yml:141-148` |
| Who can listen | `hooks/prepare` declares LAN address on Linux/WSL-mirrored; `wsl-nat` / `engine-guest` → dial-only with a Hebrew reason; Mac engine forwards only TCP 80/443 | `hooks/prepare:50-161`; contract `:170-183` |
| Firewall | nftables rendered per peer: `accept` per served port, then `drop` per address; `forward policy drop`; no relay peer→peer | `firewall.py:17-35`, `:138-170`; `tunnel-entrypoint.sh:33-36` |
| Endpoint name | resolved **once, at render**, refused if no A record | `net.py:289-310` |
| Self-heal | 15 s loop writes `wg-state.json`; `heal_links` rotates the dialer's source port; `find_peer` sweeps the lost /24, adopting only on a handshake (constants in §4) | `tunnel-entrypoint.sh:143-256`; `app.py:452-456`, `:500-556`, `:581-640`, `:738-808` |
| **Link door** | `dgo-link` shares `dgo-net`'s netns (`network_mode: service:dgo-net`), applies `/tunnel/link-proxy.json` read-only, polls 5 s | `docker-compose.yml:168-208`; `link-proxy.py:39-42` |
| Plan | `serve` = bind own tunnel addr, deliver to local app by **name**; `use` = bind locally, deliver to peer; door `9000+slot`, control `9400+slot`, agent range `10000+16·slot` | `linkproxy.py:39-41`, `:81-137`, `:145-192` |
| Host routing | ONE listener per link; HTTP `Host` picks the app (four apps share 8080); route table = own catalog asked with `x-dgo-office`, stale-while-revalidate 30 s | `link-proxy.py:450-514`; `catalog.py:313` |
| Identity at door | strips `x-authentik-*` family and any `x-dgo-identity`; writes catalog's mapped user + `x-dgo-identity: v1 <office> <user> <ts> <hmac-sha256>` keyed by the vault's `dgo_link*` row, 300 s window, secret cached 60 s; unsigned-with-log when vault unreadable | `link-proxy.py:68-106`, `:120-175`, `:592-627` |
| Connection law | one request per connection, except a websocket after the app's `101` | `link-proxy.py:581-590`, `:659-667` |
| Agent doors | a named `agent_api_port` opens ONE extra port; `*` never includes it | `linkproxy.py:176-184`; contract `:345-349` |
| Catalog door | `:8983` on the wire (legacy) → app's `link_app` on `:8984`; serves only `/api/link/catalog`; 403 to any caller not the proxy's address; a door that cannot deliver answers a Hebrew card + `X-Dgo-Door` | `catalog.py:44-52`; `app.py:1220-1285`; `dgo-remote-apps.md:55-57`; `link-proxy.py:380-437` |
| **Catalog** | projection of `.generated/registry/office.apps.json` (one list), narrowed by `serve:` + `exclude` + `only{office}`; carries `host`, `identity.to`, `agent_api_port`, `dials` | `catalog.py:13-18`, `:96-185`, `:292-392`; `dgo-remote-apps.md:29-61` |
| **Projection** | every 60 s pull `http://<proxy>:8983/api/link/catalog` (via the proxy's `use` rule, never the tunnel address); peer address DERIVED from own address; `PUT /api/remote` to app-management (compiler validates; refusal cannot break the file); `exclude.json` hides locally | `projection.py:1-47`, `:66-135`, `:148-258`, `:475-489`; `app.py:1007-1013` |
| **Compile** | `serve.py` → `platform-base/traefik/config/zz-serve.yaml` (file provider — labels cannot point outside the engine) + `.generated/remote.override.yml` alias on `dgo-net` + registry entry `remote.<office>.<alias>.json` + authentik provider per host | `serve.py:35-46`, `:510-668`; `reconcile.py:2371`, `:3322`; `zz-serve.yaml:1-4` |
| Routers | `<alias>.<office>-console-local` (`.localhost`) and `-console` (domain, TLS); chain `authentik@file` → identity mw (`X-authentik-username: <to>`) → `Host` rewrite; `-own-origin` twin rewrites `Origin` only when it equals the host asked; `-signed-in` / `-enter` for own-host apps | `serve.py:559-562`, `:574-655`; `zz-serve.yaml:7-26` |
| Tiles | id `<alias>.<office>`, class `is-remote`; `.localhost` console frames through its own origin `/a/<alias>.<office>/` (`noNestedHost`) except own-origin apps (`through_console`); verdict `{ok, hop ∈ tunnel\|office\|door}` → `peers.d/link.json` → console marks before opening | `serve.py:408-495`; `app.py:1451`; `peers.py:141-153`; contract `:271-312` |
| **Edge** | traefik v3.3; docker provider through read-only `docker-socket-proxy` (GET/HEAD allowlist, `/events` kept); `exposedbydefault=false`; `authentik@file` middleware lives in the FILE provider so routers are never discarded | `traefik/docker-compose.yml:23-46`, `:111-127`; `socket-proxy/proxy.py:1-55`; `config/authentik-forwardauth.yaml:1-22` |
| `*.localhost` | loopback by RFC 6761: nested host cannot sign in inside a frame (`auth.localhost` is another site), handed-out links die off-machine; Docker 29 silently yields zero routers | contract `:271-281`; `issues/handed-out-links-name-the-office-local-host.yaml:2-24`; `CLAUDE.md` Docker-29 note |
| **Identity** | live: authentik server+worker+postgres, embedded outpost, one proxy provider per host (blueprints compiled by `render_authentik`); cutover target: `forward-auth` Go binary, 28 tests, reads authentik hashes as-is, legacy cookie both-or-neither — **not wired**, middleware still points at authentik | `authentik/README.md:5-13`, `:53-80`; `forward-auth/README.md:1-30`, `:99-113`; `legacy.go:1-40`; `main.go:58-92` |
| App-side verify | only Plane reads `x-dgo-identity` (own vault copy, 300 s, CSRF-exempt when verified; token API accepts proved identity) | `apps/project-pln/office_identity.py:19-22`, `:77-80`, `:223-251`; `patches/api-door-identity.py` |
| **Secrets** | vault instances (protocol `dgo_link`, created via `/api/instances`, never in `providers/*.yaml`): `dgo_link-<peer>` written by pairing on BOTH offices (same token); `dgo_link-serve-<office>-<app>-agent` written into the REMOTE vault by converge over `computers`/SSH — **declared offices only** | `pair_api.py:309-314`, `:740-742`; `converge.py:1651`, `:2709-2749`; `connections/app.py:941-1015`; `client.py:34-40`, `:118-157` |
| No handoff for a pair | a paired office has no SSH/computers door, so no `_remote_vault_put`; the only shared secret is the pair token; the chosen answer is "the door proves identity, apps need no key" | `AGENT.md:4-6`; `README.md:16`; `dgo-remote-apps.md:143-150`; `issues/plane-asks-for-a-password-over-a-link.yaml:100-134` |
| CLI reach | `bbox remote` / `bbox agent --office`: alias resolves only inside the network → delegate into a container; token by NAME from vault, never in URL/argv | `scripts/remote.py:19-33`, `:143-191`; `client.py:172-226` |

## 2. Design decisions

| Decision | Where | Reason | Rejected |
|---|---|---|---|
| Pair from the screens, no SSH, no commands | contract `:3-6`; `AGENT.md:4-6` | owner's direction; access to the machine comes *through* the link | declared-office converge over SSH (kept only for vps1, `SECOND-OFFICE.md:3-9`) |
| One interface + one /24 per pair | `net.py:16-19` | one-interface render handed two peers the same `.2`; one UDP socket per interface | one `wg0` with several peers |
| `side` is the holder's, nothing assumes `.1` | `net.py:150-169`; `serve.py:108-140` | HP dialed its own address; `serve.py` refused the one correct address, `reconcile` exited | constant `.2` peer (`projection.py:229-239`) |
| Host decides who dials, once, in the grant | `pair_api.py:577-591` | a dialer's source port is NAT-rewritten (51830→51908); a direct tunnel needs one reachable port | letting each side guess from `endpoint == ""` |
| Only the dialing side's port may move | `net.py:63-106`; `docker-compose.yml:39-45` | home NAT blackholed the 51820 flow for 15 h; the dialed port is the address + firewall name on the far side | moving both; a relay |
| Token first, record second | `pair_api.py:309-311` | a record without its token is a link nothing can authorize | record first |
| Pairing state in memory | `pair_api.py:36-39` | an offer that survives a restart would be a stored secret | durable offers |
| Firewall on the RECEIVING side, rendered whole (`nft -f` replaces) | `firewall.py:32-35`, `:59-61`; `tunnel-entrypoint.sh:26-36` | an `accept` left behind cannot outlive its declaration | incremental rules; relying on the sender |
| Delivery by proxy, not DNAT | `docker-compose.yml:168-174` | app addresses are Docker's; a rendered IP stops delivering when the app is recreated | DNAT to container IPs |
| Door shares the tunnel's netns | `docker-compose.yml:176-182` | the tunnel address exists only there; a second nft chain's `accept` is not final | separate container + routes |
| One door per link, `Host` picks the app | `linkproxy.py:71-81`; `link-proxy.py:450-459` | four apps on 8080 collide or pick a silent winner | one listener per app |
| TCP splice; consumer's edge rewrites `Host` | `dgo-remote-apps.md:86-88`; `serve.py:607-621` | websockets pass untouched; a TCP proxy cannot rewrite Host, so the knower (catalog `host`) publishes it | HTTP reverse proxy in the door |
| `-own-origin` twin rewrites `Origin` only when it equals the asked host | contract `:292-300`; `serve.py:625-653` | harnesses compare Origin to Host (403 under rewritten Host alone); no trust list needed on the serving side | rewrite every Origin; `BINA_DS_TRUSTED_HOSTS` lists |
| Routers in the file provider, alias on `dgo-net` | `serve.py:35-46`; `zz-serve.yaml:4` | labels refuse external URLs; `10.79.x` is unreachable from `traefik-network` | labels; tunnel address as backend |
| Catalog = projection of the compiled registry; part of the LINK, not of `serve:` | `catalog.py:13-18`; `dgo-remote-apps.md:58-61` | one list; a peer must read it before knowing what exists | a second hand-kept list |
| Peer address derived, never published | `projection.py:70-73` | a peer naming its own address could point this edge anywhere | trust the catalog's address |
| `remote:` written through the control plane (`PUT /api/remote`) | `projection.py:141-148`, `:252-258` | two offices in a row had no door to their own machine; a refused block can never break the file | text surgery over SSH (`REMOTE_WRITER`, retired) |
| Door strips every `x-authentik-*` and SIGNS the mapped user | `link-proxy.py:68-98`; `dgo-remote-apps.md:135-141` | a bare header is writable by any container (DGO-371 refused it); a browser over a link carries no cookie of ours | trust the header; nested SSO; a second password |
| 403 catalog from the edge; `x-dgo-office` written by the door | `app.py:1268-1274`; `link-proxy.py:475-492` | a raw splice gave a one-app pairing every dgo-extend route; one peer could ask for another's list | catalog on the app's own port |
| `serve:` is ONE map per office; `only:` narrows per peer; first pairing declares `*` | `README.md:41-49`; contract `:118-137`, `:351-354` | "this is my other office"; an empty map read as DOWN | per-peer maps (lnk-019, open) |
| Verdict `{ok, hop}`, one writer; console marks before opening | `app.py:1451`; `peers.py:141-153` | cross-origin frames fail blind; `remote.ok` was read, never written | `REMOTE_DOWN` add-only set |
| `authentik@file`, not labels | `authentik-forwardauth.yaml:1-22` | 3,718 router discards in 30 min of churn | label-defined middleware |
| Read-only socket proxy for the edge | `socket-proxy/proxy.py:1-27` | `:ro` constrains the inode, not the protocol | `:ro` mount |
| Replace authentik with one Go binary, drop-in | `forward-auth/README.md:13-30`; `main.go:3-5` | 1,132 MB / 4 containers; passwords and sessions must survive | keep authentik; reset passwords |

## 3. Invariants

1. **Point-to-point only** — peer→peer forwarding dropped by design; a triangle is three pairs (`firewall.py:27,32`; Lifetime §5).
2. **No SSH between paired offices**; everything is the two apps' own APIs through the door (`AGENT.md:4-6`; contract C4 `:357-361`).
3. **The office that OFFERS states direction about itself**; the claimer gets the mirror unless it speaks (contract `:74-75`; `pair_api.py:104`).
4. **The host decides who dials, once**; `dial == role` ⇒ this side dials (`pair_api.py:577-591`; `net.py:181-195`).
5. **One writer per fact**: `remote:` ← `projection.py` only (`SERVE_WRITER` steps aside, `dgo-remote-apps.md:299-300`); `/tunnel` ← `app.render_tunnel` only (`step_link` delegates, link-goes-dark issue task 4); `serve:` ← `converge.set_home_serve` (`converge.py:1553`).
6. **The door proves identity, not headers**: strip, map, sign (`link-proxy.py:592-627`); a signature that fails is no identity (`office_identity.py:223-251`).
7. **Tokens live in the vault by name**, never in a record, URL, catalog or argv (`contract :66-67`; `remote.py:19-24`).
8. **A peer's address is derived, never published** (`projection.py:70-73`).
9. **A refused render never breaks a running link** — control plane validates `remote:`; stale catalog kept with a verdict (`projection.py:25-43`).
10. **Both ends on one commit** for a plan-shape change (`connection-status-standard.md:82-84`).

## 4. Failure classes, last two weeks

| Class | Seen | Detector today | Fix today | Open |
|---|---|---|---|---|
| Address change (DHCP lease) — D2 | 10-07 HP `.102→.100`; 10-10 Mac still dials `.102` | no handshake ≥ `FIND_AFTER` 300 s (`app.py:547`) | `find_peer` /24 sweep, adopt on handshake (`app.py:581-640`; `tunnel-entrypoint.sh:158-232`); `dials` corrects listener (`app.py:1144`; `pair_api.py:142`); `hooks/prepare:160` follows lease | Mac branch lacks the finder (`hp-mac-link-down:205-214`); public-address change D8 has no detector |
| Source-port wedge — D1 | 10-04 (51820, 15 h), 10-06 (51832) | tx grows, no handshake ≥ 180 s (`app.py:452`) | `rotate_listen_port` → `/data/listen-ports.json`, 600 s cooldown, 6 max (`app.py:500-556`) | handshake age not on any screen until P3 (`connection-status-standard.md:P3`) |
| netns death on rebuild — D4 | 10-04 four times | `delivery.door.listening=false` | `netns_rejoin` after every `dcx up`, 33 s (`scripts/lib.sh:623-635`) | — |
| Sleeping office — D7 | Mac 10-06, 10-10 (both Mac links die together) | handshake stale → `hop: tunnel` | keepalive 25 re-establishes on wake | Mac is dial-only; no channel to its agent while asleep (`hp-mac-link-down:66-76`) |
| Silent record drop — D5 | 10-08 23:37 Mac record vanished when HP's was written | **none** | none | lnk-029; card for "an office this one used to know" |
| Wrong dial direction — D3 | 10-08 HP↔vps1 `use` reversed; 10-12 `w2` dials a private address | `verdict.hop = pair`, `net.dialable_from_here` (lnk-032) | re-pair only (both records carry one `dial`) | — |
| Two tunnels on one /24 — D6 | 10-08/09 slot 2 taken, Mac apps «Bad Gateway» behind vps1 | none after the fact | source fixed: `_taken_slots` counts held addresses (`pair_api.py:256-289`, 0e0294c7) | vps1 still holds the dead pair (first-direct-pair issue tasks); applied-vs-machine /24 check absent (Lifetime §4.2) |
| 200-empty / dead frame doors — D13 | 10-04 blank tile; 10-12 own door 502 empty body | verdict pre-flight; non-2xx is a sentence (`projection.fetch`) | door card + `X-Dgo-Door` (`link-proxy.py:380-437`); console marks from `link.json` | cross-origin watchdog on a real domain (tile-blank issue `:80-86`) |
| Missing token / identity over a link | 10-13 Plane sign-in form; vps1 agent `HTTP 404` on vault instance | — | `x-dgo-identity` + Plane reader (DGO-545, 5e895618/7e92affd/b4c4ec12) | every other app still sees only the bare header; agent Bearer for a *paired* peer has no channel |
| Rebuild mid-pairing — D10 | 10-11 claim dropped after 15 s | 404 with sentence | start again | by design (`pair_api.py:36-39`) |
| Version skew between offices | vps1 at `dad40e66`, 314 behind, no `pair_api` | 404 on `/api/pair/*` | whole-office converge (owner's call) | `a-direct-pair…yaml` blocked |

## 5. Smells and risks

| # | Smell / risk | Evidence |
|---|---|---|
| 1 | **Two tunnel appliers for one layout.** Declared offices run `wg-quick@wg0` on the HOST + a Python systemd door bridging unix sockets; paired offices run `dgo-net` + `dgo-link`. The host-side link (vps1↔Mac, slot 2) has **no record on vps1**, which is the direct source of D5/D6 and why `_taken_slots` must read addresses, `firewall.WG_IF="wg0"` lingers, and `serve.own_addresses` reads `.dgo/wg0.conf` | `converge.py:1299-1349`, `:2337`; `docker-compose.yml:200-207`; `firewall.py:72-75`; `serve.py:137-140`; Lifetime `:107-111` |
| 2 | **Layer-0 networking in Python/shell inside containers.** An 890-line TCP splice parses HTTP heads, detects websockets, signs HMACs and reads the vault, in 64 MB/0.1 CPU; a 277-line shell loop sweeps a /24 with `wg set` and `sleep 0.5`; `wg-quick` failure is logged and the loop carries on. The core-native plan (`CLAUDE.md` → `core-native-plan.md`) and `forward-auth` (Go, stdlib) show the intended shape | `link-proxy.py` (890 l.); `docker-compose.yml:209-215`; `tunnel-entrypoint.sh:81-84`, `:183-232` |
| 3 | **Moving parts per tile ≈ 15, 5 writers.** record×2, vault row×2, `wg<slot>`, nft table, published UDP port, machine firewall, door listener, catalog listener, 60 s pull, `PUT /api/remote`, `zz-serve.yaml` routers (+`-own-origin`, `-signed-in`, `-enter` twins), `remote.override.yml` alias, authentik provider per host, registry entry, `link.json` verdict. A provider missing = 404 at the outpost while the edge looks healthy | Lifetime `:14-24`; `serve.py:510-668`; `dgo-remote-apps.md:107-110` |
| 4 | **Identity is header-based inside the office network.** Every app trusts `X-authentik-*` from traefik; `BBOX_SSO=off` writes a static `akadmin`; the consuming edge writes `X-authentik-username: akadmin` toward the peer only for the door to strip it; `x-dgo-identity` defends the PEER boundary only — any container that can `GET connections:8990/api/instances/<id>/secret` can mint one, and the 300 s window has no nonce (replayable). Only Plane verifies it | `authentik-forwardauth.yaml:26-33`; `zz-serve.yaml:7-10`; `serve.py:574-587`; `link-proxy.py:141-150`, `:102`; `plane-asks…yaml:149-156` |
| 5 | **Identity estate mid-cutover.** authentik live (4 containers); `forward-auth` built and tested but unwired; two hash families; legacy sessions both-or-neither; authentik's one-provider-per-host rule freezes refresh on a duplicate | `forward-auth/README.md:109-113`; `authentik/README.md:64-68` |
| 6 | **Record half is not self-healing.** D3 needs a re-pair, D5 has no detector, D6 is prevented but not detected; the three incidents that cost a day each were here | Lifetime `:63-71` |
| 7 | **`*.localhost` offices break the browser model.** Nested host cannot sign in in a frame → remote app code runs in the console's origin ("trust statement"); handed-out links are loopback; Mac can only dial, so a Mac mesh dies with the lid | contract `:271-281`; `handed-out-links…yaml:27-33`; `hp-mac-link-down:57-61` |
| 8 | **Defaults are wide.** First pairing declares `serve: {"*": {}}` — includes app-management, computers, connections ("my other office"); `serve:` is one map for all peers, `only:` is the patch | contract `:351-354`; `README.md:41-49` |
| 9 | **Name resolved once, at render** — a VPS that moves needs a re-render on the peer (D8); `staging.digital-office.co.il` has no A record | `net.py:289-310`; `connection-status-standard.md:86-106` |
| 10 | **Version coupling across offices** with only additive guarantees (`dials`), and a Docker-28-only edge (traefik 3.3 hardcodes API 1.24) | `dgo-remote-apps.md:49-54`; `CLAUDE.md` Docker-29 note |
