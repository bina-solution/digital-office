# DGO Extend — remote offices, links and placement (design + plan)

Owner decision document, 2026-09-30. The readable copy with the drawings is the owner's Claude doc
"DGO Extend — remote offices, links and placement: design and decisions"; this file is the same
content in the repository, the working reference for agents implementing it. Facts below were
verified in this checkout and on the two live machines (MacBook engine, vps1 31.97.196.82) on
2026-09-30; research sources are linked in §4.

**Read §13 first.** The sections below are the decision as it was taken on 2026-09-30 and are kept
as written. Three of its decisions were changed in the work (placement, the alias proxy, how an
office on a Windows machine joins) — §13 says which, why, and what stands in their place.

## 0. Summary

DGO Extend is one app in the office (today `apps/offices`, "לשכות נוספות") that creates, connects
and runs other digital offices, and it makes every requested feature out of one mechanism: **an
office is a declaration, a link is a one-way trust between two offices, and an app placed on a
linked office appears at home as one more connection of the same capability.** Every app already
follows "abstract API + several connections with different implementations" (drive, mail,
computers, git), so a remote instance is just another connection.

Connect vps1 to the MacBook → heavy apps run on the VPS while the console and עזריה use them as if
local. Connect the MacBook to vps1 as well → on `staging.digital-office.co.il` the Bina tile is
*declared* as running on the MacBook's office and served through the link. Two one-way links, each
side gets the other's apps. The portable machine on the LAN joins the same way.

Decisions in one screen (details in §11):

1. Transport: one WireGuard tunnel per office pair, dialed by whichever side can reach the other; a
   public office relays for two that cannot reach each other.
2. Link ≠ tunnel: a link is authorization + routing in one direction; the tunnel is shared.
3. Remote apps appear local by docker network alias through one proxy container per link.
4. A placed app is a `connections` instance tagged with the office it runs on.
5. Pairing: via `computers` (SSH, zero-touch), by QR (the joiner shows public material, the host scans
   and sends the grant encrypted, 6-digit confirmation), or by pasting the same offer as text.
6. Identity: one Ed25519 key + one WireGuard key per office in a backed-up `kind: secret` volume;
   per-link tokens in the vault, revocable in one converge.
7. Scaling by placement: stateless apps move by declaration; stateful apps move with data
   (backup → transfer → restore → switch, rollback); shared services are reached over the link.
8. Release-readiness: first-party images are built off the office (CI) and pulled.

## 1. What exists today (verified 2026-09-30)

| Piece | Where | State |
| --- | --- | --- |
| Remote office as a declaration | `apps/offices` (`/data/offices/<id>.yaml`), converge `machine → dns → backup → code → engine → env → state → run → health → publish` | vps1 runs `5d6fa5f1`, 43 containers, 0 unhealthy, backup `/root/backup-20260930-013725-pre-upgrade` |
| Placement v1 | `apps/offices/peers.py`, step `publish`, console peer registry | `hello-bina` runs on vps1, opens from the MacBook console; door without token → 404. Over HTTPS + header token, not yet a tunnel |
| Fleet | `apps/computers` | MacBook, vps1; portable-machine (192.168.16.103, Docker 29) not yet registered |
| Credential plane | `platform-base/connections` | live |
| Abstract API + connections | `ai/context/platform-service-contract.md` | drive, mail, computers, git, offices follow it |
| Agent API | `agent.v1` (`ai/context/agent-contract.md`), adapter in bina-ds, `bbox agent` | built 2026-09-30; image rebuild pending a quiet box |
| One heavy job at a time | `heavy_admit`, `scripts/lib.sh` (`e1290f75`) | live |
| Network plans | `ai/context/digital-office-network-plan.md`, `-architecture.md` | documents; this plan adopts and narrows their transport design |

Missing, specified here: the tunnel, links in a chosen direction, the alias proxy, remote apps as
connections, the reverse case (vps1 shows the MacBook's Bina), QR/paste pairing, key backup, tests.

## 2. The model

| Noun | Meaning | Owner |
| --- | --- | --- |
| Office (DGO) | one `./bbox run` on one machine: its own edge, authentik, vault, apps; Ed25519 identity + WireGuard key minted at first run | its checkout + `dgo-identity` volume |
| Tunnel | WireGuard connectivity between two offices, dialed by whoever can reach; one per pair, shared by every link | the dialing side's declaration |
| Link | one-way trust "A may use B's apps": authorizes A's requests at B, routes B's placed apps into A; the reverse is a second link | consuming office A (declaration + `dgo_link` vault row); B holds the grant |
| Placement | "app X of A runs on B": A keeps X's tile and connection; B runs X; X disabled at A | A's declaration |
| Connection | an instance of a capability in the vault; a placed app appears at A as one, tagged `office: B` | A's vault |

Direction and dialing are separate: the NAT'd MacBook dials the tunnel; the link vps1→MacBook
rides it the other way. WireGuard is symmetric once handshaked and the NAT'd side keeps the mapping
alive with `PersistentKeepalive 25`. Apps never know where a provider runs; a name resolves either
to a local container or to a link proxy.

## 3. The four topologies

| Case | Who dials | Link | Result | Needs |
| --- | --- | --- | --- | --- |
| MacBook → vps1 (offload) | MacBook dials vps1 | MacBook uses vps1's apps | browser42, OCR/n8n workers, Plane on vps1; tiles and names unchanged at home | tunnel, link proxy at home |
| vps1 → MacBook (remote access to Bina) | same tunnel | vps1 uses the MacBook's apps | Bina tile on `console.staging` declared as placed on the MacBook, streamed over the tunnel; `bbox agent` on vps1 reaches the MacBook's agent; "not reachable" when the MacBook sleeps | reverse link; vps1's authentik is the login; MacBook's bina-ds trusts identity headers from that link only |
| MacBook → portable (LAN) | MacBook dials 192.168.16.103 | MacBook uses portable's apps | browser + OCR on the 15 GB laptop | portable office via `computers` (Docker 28 first) |
| vps1 ↔ vps2 | either | any | same flows, no relay | nothing new |

Relay (phase 5): two offices that cannot reach each other route through vps1 (`relay_for`).

## 4. Research (sources opened 2026-09-30)

| System | Pairing | Appears local by | Direction | We take |
| --- | --- | --- | --- | --- |
| [Skupper](https://skupper.io/docs/overview/index.html) | [AccessGrant](https://skupper.io/resources/access-grant.html): 1 redemption, 15 min; mints mTLS cert → [Link](https://skupper.io/resources/link.html) | [Listener ↔ Connector](https://skupper.io/resources/listener.html) by routing key | private dials public; exposure either way | claim shape; exposure by name |
| [Liqo](https://docs.liqo.io/en/stable/features/peering.html) | `liqoctl peer`; [gateway server reachable, client outbound](https://docs.liqo.io/en/stable/advanced/peering/inter-cluster-network.html); [single-cluster strategy](https://docs.liqo.io/en/stable/advanced/peering-strategies.html) | EndpointSlice reflection | **unidirectional peering**; bidirectional = two | our link exactly |
| [Tailscale](https://tailscale.com/blog/how-tailscale-works)/[Headscale](https://github.com/juanfont/headscale) | [auth keys](https://tailscale.com/kb/1085/auth-keys); Headscale [pre-auth 1 h/1 use](https://headscale.net/stable/usage/getting-started/) | MagicDNS | [directional ACLs](https://tailscale.com/kb/1018/acls) | token ≠ permission; public node relays |
| [NetBird](https://docs.netbird.io/about-netbird/how-netbird-works) | [setup keys](https://docs.netbird.io/how-to/register-machines-using-setup-keys) with auto-groups | names | explicit [uni/bidirectional flag](https://docs.netbird.io/how-to/manage-network-access) | the direction flag |
| [Nebula](https://github.com/slackhq/nebula) | offline CA signs host certs ([quick start](https://nebula.defined.net/docs/guides/quick-start/)); [relays](https://nebula.defined.net/docs/config/relay/) | own IPs | separate inbound/outbound [firewall](https://nebula.defined.net/docs/config/firewall/) | trusted side signs the joiner |
| [WireGuard](https://www.wireguard.com/) | two pubkeys + AllowedIPs | — | symmetric; NAT side sets Endpoint + [keepalive 25](https://www.wireguard.com/quickstart/) | one public endpoint suffices |
| [Signal](https://signal.org/blog/a-synchronized-start-for-linked-devices/)/[WhatsApp](https://engineering.fb.com/2021/07/14/security/whatsapp-multi-device/) linking | new device shows QR of public material; primary scans and sends secrets encrypted | — | primary authorizes | QR carries public material only |
| [Bluetooth NC](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core-54/out/en/host/security-manager-specification.html), [Matrix SAS](https://matrix.org/docs/older/e2ee-cross-signing/) | 6 digits from ECDH on both screens | — | — | the confirmation code |
| [Open Cloud Mesh](https://datatracker.ietf.org/doc/html/draft-ietf-ocm-open-cloud-mesh-00) | out-of-band invite token, signed requests | per-share bearer | mutual after invite | invite → mutual contact |
| [snitun](https://github.com/NabuCasa/snitun) | instance dials out; SNI proxy | public hostname for a NAT'd instance | one way | the "NAT'd office reachable via public one" shape (kept as later option) |
| [Matrix federation](https://spec.matrix.org/latest/server-server-api/) | published time-limited keys, signed requests | — | any↔any | key hygiene only |

Browser: native [`BarcodeDetector`](https://developer.chrome.com/docs/capabilities/shape-detection)
exists on Chrome macOS/ChromeOS/Android only ([caniuse](https://caniuse.com/mdn-api_barcodedetector));
bundle [nimiq/qr-scanner](https://github.com/nimiq/qr-scanner) or the [ZXing-wasm polyfill](https://github.com/Sec-ant/barcode-detector).
Compose: shared [`aliases`](https://docs.docker.com/reference/compose-file/services/#aliases) resolve
to an unspecified container ([moby#22389](https://github.com/moby/moby/issues/22389)) — one proxy
per link owns its aliases; replicas balance on the remote office.

## 5. Transport

Self-run WireGuard, `dgo0` per office, one peer per linked office, dialed by whoever can reach.
`dgo-net` container (NET_ADMIN, /dev/net/tun, kernel module on Ubuntu 24.04 / Debian 12,
`wireguard-go` fallback) on `traefik-network`. Addresses `10.79.<slot>.0/24` (office `.1`, link
proxies `.2–.254`); slots assigned at link creation and recorded on both sides. Reachable side
publishes `endpoint: host:51820` UDP; the other sets `PersistentKeepalive = 25`. Only link-proxy
traffic and DGO Extend control calls ride the tunnel; the remote's `dgo-net` forwards only to
allow-listed app ports (nftables rendered from the declaration). Rejected: Tailscale/Headscale,
Nebula, NetBird (second control plane/trust root), Swarm/k3s (replace compose), Cloudflare Tunnel
(third party), SSH tunnels (1,334 reconnects/10 min, split-brain — measured).

## 6. Apps across offices

One generated container per link, `dgo-link-<office>`, joins the home `traefik-network` carrying
the remote apps' service names as aliases and forwards each name's port across the tunnel (TCP-level:
HTTP, Postgres, Redis, WebSockets). Callers (`http://apitools:8080` hard-coded 37 times in n8n, the
console's `/a/<alias>/`, health probes) are unchanged.

| Concern | How | Owner |
| --- | --- | --- |
| Which apps run where | `placements:` in the home declaration; remote `platform.state.yaml` derived | DGO Extend |
| Home stops the app | `state: disabled, by: offices`, containers stopped | DGO Extend |
| Names at home | proxy aliases rendered by `reconcile.py` into service `dgo-link-<remote>` | compiler (layer 0) |
| Reaching the app | proxy → tunnel → remote `dgo-net` → allow-listed port | dgo-net both sides |
| Tile | unchanged module URL; office badge from the peer registry | console |
| Health | `remote-healthy` / `remote-unhealthy` / `link-down` | link proxy |
| SSO/identity | home authentik guards the tile; `X-authentik-*` accepted by the remote app only from the link's source address (nftables + traefik rule) | dgo-net rules + remote edge |
| App as connection | instance of its capability in the home vault with `office: <remote>` and the proxy endpoint | connections |
| Removal | delete the placement → next converge removes alias, badge, instance, remote containers (data kept) | DGO Extend |

Bina case from vps1's side: vps1's declaration for the MacBook places `bina-ds`; `dgo-link-macbook`
carries alias `bina-ds`; the tile on `console.staging` proxies to it; the MacBook's bina-ds trusts
vps1's identity headers from that link; `bbox agent` on vps1 uses
`BBOX_AGENT_URL=http://dgo-link-macbook:3081`. MacBook asleep → the tile and the vault instance say
"not reachable".

## 7. Scaling patterns

| Pattern | Apps | Scales by | Moves |
| --- | --- | --- | --- |
| Stateless, movable | browser42, apitools OCR, ui-map capture, sites-render | `placement` (+ `replicas` on the remote) | nothing |
| Workers of a home service | n8n workers, OCR workers | placed remotely, reach home `redis`/`postgres`/`apitools` by alias via the reverse direction of the link | nothing (`N8N_ENCRYPTION_KEY` via vault; clocks checked) |
| Stateful singleton | indox, mail, drive, Plane, git | `move: with-data` (backup → stream volumes through `computers` → restore → health → switch; rollback) | volumes, once |
| Shared substrate | postgres, redis, authentik, connections | never placed; reached by alias | nothing |

Rules: memory-aware admission before placement (`MemAvailable`, cores, disk via `computers`; refuse
under `BBOX_HEAVY_MIN_MB`); `heavy_admit` per office; health has three states; data has one home;
same commit for placements (reads tolerate drift). Expected on the MacBook: ~3.7 GB (browser42)
+ ~1 GB (Plane) + capture containers freed.

## 8. Connect flows

1. **Through `computers` (zero-touch):** converge step `link` after `run`: read the remote's identity
   + WireGuard pubkey (`bbox dgo identity`), write the home's keys and the grant into the remote's
   declaration, bring both peers up, verify a round trip. The flow every test uses.
2. **QR — the remote shows, the host scans:** the remote mints a **pairing offer**
   `{office_id, identity_pubkey, ephemeral_pubkey, endpoints[], rendezvous_id, expires 10 min}`
   (public material only) as QR + 6-group text; the host scans in the browser (`getUserMedia`,
   bundled `qr-scanner`), tries endpoints LAN-first, POSTs `/dgo/v1/claim` with its keys, the link
   direction and the link token it minted — encrypted to the ephemeral key, signed with its identity;
   both screens show a 6-digit ECDH confirmation code; the operator confirms on the host; the remote
   signs back and stores the grant. Unreachable remote → reverse QR (roles swapped, same format).
3. **Paste code:** the same offer as text; same properties.

Result everywhere: `identity`, `tunnel`, `links[]` in the host declaration; a `dgo_link` vault
instance; the mirror on the remote; peers, allow-lists, proxies rendered; revocation = the same file
edited the other way, one converge.

## 9. Security model

| Asset | Where | Backup |
| --- | --- | --- |
| Office identity (Ed25519) | `dgo-identity` volume, root-only | in `bbox export`, `kind: secret` (closes issues/network-state-holds-a-private-key…) |
| WireGuard key | same | same |
| Link token (256-bit per link per direction) | vault, protocol `dgo_link` | vault backup |
| Pairing offer | remote's memory, 10 min | none |

**The link's identity, as implemented (DGO-31, 2026-09-30).** Two offices authenticate their own
users; the link carries the SENDING office's answer. So on the sending side the served tile is behind
that office's own `authentik@file` — which overwrites every `X-authentik-*` header before the identity
middleware writes the mapped username, so a browser cannot forge one — and on the receiving side the
link is terminated by the DOOR (`link-proxy.py`), which is the only thing that knows where a request
came from: it listens on the pair's tunnel address for that peer alone, routes only to apps this
office serves, removes every `X-authentik-*` header the request carries and writes the user the
catalog maps the link to (`serve[].identity.to`, else this office's own SSO user). One link, one
identity — and it is never the peer's word. The rule was first written as a pure function with a
401 for an unmapped name (`trust.py`, `decide()`) while that front did not exist; the door does not
map names, it replaces them, and the module was removed on 2026-10-05 once nothing called it
(`tests/phase3.py`: `c_door_identity`, `c_link_listener`).

Threats → mitigations: internet reach via vps1 → apps reachable only through the tunnel from the
link's source; adapter and link API never on `0.0.0.0` (link API listens on `dgo0` and on the
endpoint only during a pairing window). Stolen token → useless without the peer's WireGuard key;
revoke = remove link. Forged identity headers → dropped unless from the link proxy's address
(nftables + traefik). Rogue office by QR → single-use, 10-min offer, confirmation code both screens
derive. Lost keys → in the backup set; a new key means announced re-pairing. Wrong direction →
enforced on the receiving side (`use` vs `serve`). Commit drift → placements refused. Audit → offices
run log + connections events + computers command log. Not done: shared passwords, authentik
federation, any public port besides WireGuard UDP on a reachable office.

## 10. Declarative model

```yaml
# offices/vps1.yaml — declared at the MacBook office
id: vps1
machine: computer_ssh-b154fa0c        # absent for a QR-paired office
domain: staging.digital-office.co.il
path: /root/deployment-hacohen
source: {repo: …, branch: dgo, commit: 5d6fa5f1, account: git_github_token-1d2d52f4}
apps: {console: enabled, n8n: enabled, chat: disabled, …}
identity: {office_key: ed25519:…, wg_pubkey: wg:…, fingerprint: 7K3M-Q2ZP}
tunnel: {slot: 2, endpoint: 31.97.196.82:51820, dial: home, relay_for: []}
links:
  - {direction: use,   token_ref: dgo_link-a1b2c3}
  - {direction: serve, token_ref: dgo_link-d4e5f6, trust_identity_headers: true}
placements:
  browser42: {replicas: 1}
  n8n-worker: {replicas: 2}
  project-pln: {move: with-data}
serve:
  bina-ds: {}
```

Rendered at home by `reconcile.py`: `dgo-net` peer + nftables allow-list; `dgo-link-<office>`
service with aliases/ports from `app.json`; `state: disabled, by: offices` for placed apps; vault
instances with `office:`. Rendered on the remote by its converge: the mirror peer; UDP 51820 only if
dialed; grants; `dgo-link-<home>` for `serve:` apps and their tiles.

Platform changes (one owner each): `app.schema.json` gains only an optional
`remote: {stateful, ports}` hint (placement is an office's decision, not an app's);
`reconcile.py` gains the `dgo-net` and `dgo-link-<office>` emitters; `connections/providers/40-apps.yaml`
gains protocol `dgo_link` and the `office` field; `apps/offices` → `apps/dgo-extend` (decision 1)
gains `link`, `publish`, `move`, pairing endpoints, QR screens, identity mint; traefik unchanged.

## 11. Decisions

1. **Rename `apps/offices` → `apps/dgo-extend` (הרחבת הלשכה, alias `dgo`) — owner.** Rejected: keep
   `offices` (wrong noun; renaming later costs a migration on every office).
2. **Self-run WireGuard, one tunnel per pair.** Rejected: Tailscale/Headscale, NetBird, Nebula, SSH
   tunnels, Cloudflare Tunnel, Swarm/k3s.
3. **A link is a directed edge; the tunnel is shared.** Rejected: a bidirectional flag.
4. **Aliases through one proxy per link.** Rejected: sidecar per app, host DNS rewriting, re-pointing
   URL envs.
5. **A placed app is a vault connection.** Rejected: a separate registry.
6. **Reverse case served by the remote console under the remote's SSO.** Rejected for now:
   snitun-style SNI pass-through of the home's own hostnames.
7. **Three pairing flows, one result; offers 10 min, single-use, public material only, encrypted
   grant, confirmation code.** Rejected: a secret inside the QR; host-shows-QR as the only flow.
8. **One Ed25519 + one WireGuard key per office, backed up as `kind: secret`.** Rejected: a per-network
   CA (revisit above ~10 peers).
9. **Direction enforced on the receiving side in nftables + traefik rules.** Rejected: token-only trust.
10. **Scaling by declared pattern; admission before placement; no automatic scheduler this release.**
11. **Same commit on both sides for placements.** Rejected: version-negotiated placements.
12. **First-party images built off the office (CI) and pulled — owner.** Today's hour-long pnpm
    install on the 5 GiB engine wedged the daemon and took the edge down.
13. **Relay is phase 5.**
14. **Agent questions answered in the UI this release; `bbox agent` shows them.**

## 12. Implementation plan

| Phase | Builds | Files | Gate (`bbox dgo test N`) |
| --- | --- | --- | --- |
| 1 · Tunnel + link | identity mint; `dgo-net`; step `link` over `computers`; `links[]`/`tunnel`; `dgo_link` protocol; rename + migration hook | `apps/dgo-extend/{converge.py,identity.py,net/}`, `connections/providers/40-apps.yaml`, `reconcile.py` (dgo-net emitter), `platform/data-volumes-waivers.yaml` | ping 10.79.x.1 both ways MacBook↔vps1 (MacBook NAT'd); forged packet dropped; revoke removes peer both sides in one converge; `bbox export` holds the identity volume |
| 2 · Placement | link-proxy emitter; placement → vault connection; console badge; 3 health states; admission | `reconcile.py`, `apps/dgo-extend/{peers.py,proxy/}`, `console/app.py`, `connections` | browser42 placed on vps1 opens from the MacBook console; an n8n worker at home reaches it by name; ≥ 3 GB freed on the MacBook; placement refused on low memory; unplacing brings it home |
| 3 · Reverse + QR | `serve:` + reverse link; per-link header trust; QR/paste/reverse-QR screens; portable via `computers` | `apps/dgo-extend/static/{connect.*,vendor/qr-scanner}`, `pairing.py`, traefik labels | Bina tile on `console.staging` opens the MacBook's agent; `bbox agent list` on vps1 lists MacBook sessions; MacBook asleep → tile says so; QR pairing MacBook→portable under 2 min, photographed QR redeems nothing; wrong code aborts |
| 4 · Moves + scale | `move: with-data` with rollback; `replicas`; same-commit check; CI-built images | `move.py`, `computers.v1 stream`, `.github/workflows/images.yml`, `packaging/` | Plane moves to vps1 with its data; forced mid-move failure rolls back; two n8n workers on vps1 drain the home queue; a fresh office pulls images, builds nothing |
| 5 · Relay + polish | `relay_for`; `bbox agent answer`; audit screen | `converge.py`, `static/`, `bina-ds/adapter` (`$events`) | portable↔MacBook exchange traffic away from home; a CLI answer reaches the agent's question |

Release proof beyond the gates: `bbox baseline` green on both offices; `flow-qa.py --url` against
vps1 with a placed app; §9 checks as tests; a fresh clone on a fourth machine reaching phase 3 with
no hand steps. Phase 1 starts when the bina-ds recreate lands and the box is quiet; phase 3's
portable case waits for the portable machine to be on the network.

**Owner decisions 2026-09-30:** "complete the full plan" — decisions 1 and 12 taken as proposed
(rename to `dgo-extend`; CI-built images). **The task breakdown is data**:
[apps/project-pln/plans/dgo-dev.yaml](../../apps/project-pln/plans/dgo-dev.yaml) → Plane project
`DGO` («הלשכה הדיגיטלית», the hub of all development) via `./bbox project-pln plan dgo-dev` — one module per phase (plus שלב 0 · יסודות,
the unified-navigator mandate and the Forgejo-as-tile correction), every gate a work item labeled
שער, every item assigned to the office agent, who moves it to בוצע himself
(`bbox project-pln tasks`, the `plane-tasks` skill, `bbox agent do DGO-n`); both the agent's sessions
and the items appear on כל מקביל (any-concurrency). Item numbers: DGO-1…15 שלב 0, 16…23 phase 1,
24…29 phase 2, 30…36 phase 3, 37…42 phase 4, 43…46 phase 5, 47…51 release, 52…56 UI, 57…59 git.

## 13. Results — what was built, what changed, what is open (2026-10-07)

**Built as decided**

| Decision | Where it lives now |
| --- | --- |
| 1 · rename to `dgo-extend` (alias `dgo`) | `apps/dgo-extend`; `hooks/migrate` + `hooks/prepare` carry an office that knew `offices` |
| 2 · self-run WireGuard, one tunnel per pair | `net.py`: one interface per pair (`wg<slot>`, `10.79.<slot>.0/24`, a `/32` per side — no routed subnets); containers `dgo-net` (tunnel) and `dgo-link` (door) |
| 3 · a link is a directed edge | `declaration.py` (the rules), `links.py` (the token of one direction, a row in the credential plane) |
| 7 · three pairing flows, one result | `pairing.py`, `pair_api.py`, the screen at `/connect`; the contract is [dgo-pairing-contract.md](dgo-pairing-contract.md) |
| 8 · one Ed25519 + one WireGuard key per office, in the backup | `identity.py`, volume `dgo_identity` |
| 9 · direction enforced on the receiving side | `firewall.py` (permission), `linkproxy.py` + `link-proxy.py` (delivery) |

**Decided differently since**

* **Placement is retired (decisions 4, 5, 11; phase 2 as written).** Owner, 2026-10-01: *apps just
  run where they run.* An app is not "placed" on another office and shown here through a token door;
  it runs in its own office, and what crosses the link is a **catalog** — a projection of that
  office's own compiled registry (`catalog.py`). The consuming side declares it as the `remote:`
  block of `platform.state.yaml` (`projection.py`, through the control plane) and the tiles are
  `<alias>.<office>`. The model and the data path: [dgo-remote-apps.md](dgo-remote-apps.md).
  `peers.py` and the `placement:` key remain only so that an old declaration still reads.
* **No alias proxy per link (decision 4).** The door delivers by host name, per app the office
  `serve:`s, and a door that cannot deliver answers for itself — a card for a page, a status for a
  call, `X-Dgo-Door` either way (2026-10-07).
* **An office does not need SSH to be linked.** The plan's zero-touch path goes through `computers`.
  hp-laptop (Windows + WSL) was installed by its own owner and **paired** from the screen on
  2026-10-04; by the owner's ruling it runs no SSH server, and "only offices that hold the code can
  reach it". It listens on one UDP port and the MacBook dials. Everything the link needs on such an
  office is declarative: the state is written through the control plane, never through a shell.
* **One answer to "is it up".** Not in the plan, and needed the first week: `GET /api/link` gives one
  verdict per office — `{ok, hop, why}`, `hop` = `tunnel` / `office` / `door` — and the console
  marks that office's tiles from it.

**Gates.** `./bbox dgo test 0…3` and `./bbox dgo test fresh` (two brand-new offices through the
real pairing API) exist and run REAL link verbs. The phases' gate items are open work, not passed
claims — see the hub.

**Open** (Plane project DGO; the breakdown is `apps/project-pln/plans/dgo-dev.yaml` and
`plans/office.yaml`): the gates of phases 2, 4 and 5 (DGO-29, 42, 46); `stream` for moving volumes
(DGO-38); replicas (DGO-39); relay (DGO-43); the audit screen (DGO-45); §9 as automated tests
(DGO-49); `flow-qa.py --url` against a live linked office (DGO-48). Two items were written for the
retired placement model and have to be re-read against the catalog model before anyone builds them:
placement as a vault connection (DGO-25) and the same-commit check (DGO-40). Found in use: the link does not
come back by itself after the listening side's Wi-Fi reconnects (DGO-404), and a laptop office that
sleeps takes the link down with it until it wakes (DGO-410, the owner's setting on that machine).

The app's own map — which file owns which fact — is [apps/dgo-extend/README.md](../../apps/dgo-extend/README.md).
