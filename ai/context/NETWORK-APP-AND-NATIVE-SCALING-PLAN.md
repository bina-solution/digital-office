# Platform-OS Network App & Native Scaling — design plan

**Status:** proposal for review. Written 2026-08-11 after a full day of operating the hand-rolled
version, so every design choice below is answerable to a specific failure that actually happened.

> **PARTIALLY SUPERSEDED (2026-09-29).** The fleet/remote-office work now lives in
> `digital-office-network-plan.md` (rev 2) + `digital-office-network-architecture.md`.
>
> **Still authoritative here, and not repeated there:** §1 (the seven measured incidents), the
> transport evaluation in §2 that chose WireGuard over `ssh -R`, and §5's failure semantics — each
> written from a real outage.
>
> **Replaced:** §3's addressing/transport shape where it disagrees with the newer plan — specifically
> **any "one static catch-all router" idea** (the newer plan uses one exact `Host()` router per node,
> and a reserved-host list: a catch-all `HostRegexp` would preempt the live `console.staging` /
> `auth.staging` routers and ACME cannot issue for a regexp), and the enrollment flow in §4 (the
> **gateway** now issues the authorization, behind its own SSO; a joining node may not mint its own).
> The n8n/apitools/indox scaling sections (§3 L4, §9–§12) remain unbuilt proposals and are untouched
> by the newer plan.

---

## 0. The thesis

Today's cross-machine scaling is **per-port SSH forwards driven by shell scripts**. Every serious
outage today came from that one choice. The fix is not better scripts — it is to stop forwarding
ports and start joining networks.

**Recommendation: a WireGuard overlay owned by a first-class "Network" app, with service-level
addressing, a published service catalog, and scaling UIs that read and write real config.**

---

## 1. What actually broke today — this is the requirements list

Each of these is a measured incident, not a hypothetical.

| # | Failure | Root cause | What it implies for the design |
|---|---|---|---|
| 1 | Tunnel supervisors died permanently; **1,334 ssh spawn/exit cycles in 10 min** | An ssh `ControlMaster auto` stanza matched the supervisors (they connect by literal IP), turning them into mux slaves whose `-R` forwards leaked into one master and were never released | **No multiplexed, session-oriented transport.** |
| 2 | Orphaned `sshd-session` processes held `-R` listener ports 19001–19021; supervisors with `ExitOnForwardFailure=yes` exited instantly, forever | WiFi drop killed the client without a FIN; sshd kept the session half-open | **No per-port listeners, and no session state that can be half-open.** |
| 3 | **6-hour silent OCR split-brain**: 5,296 fallback warnings, 1,171 orphaned cache rows | A watchdog rebuilt the tunnel with only the `-L 18080` traffic leg, silently dropping `-R 19118` (the shared-cache leg). haproxy saw a healthy traffic leg and kept sending 81.6% of traffic | **A link is atomic — you have the network or you don't. Never a partial leg set. And health must reflect *reachability*, not liveness.** |
| 4 | Remote workers worth ~16% of local; remote jobs 6× slower | A portable worker reached apitools via `socat → ssh -R → HOST haproxy → ssh -L → back to the portable`. **A double WiFi crossing to reach a process on the same machine.** | **Service addressing must be topology-aware: local-first, peer-fallback.** |
| 5 | A worker consumed **zero jobs for 2 hours** while Docker reported it `healthy` | Healthcheck was `pgrep -f 'n8n worker'` — process existence | **Health = "is it doing its job", never "is the process alive".** |
| 6 | Scaling config lived in ssh configs, socat args, and scratchpad shell loops that **die with the session** | No config model, no persistence, no UI | **Config is data in the platform, not arguments in scripts.** |
| 7 | Killed apitools for ~70s: `pkill -f "socat.*bind=127.0.0.10"` **matched its own ssh argv** | Hand-rolled process management | **The platform manages lifecycle; no ad-hoc pkill.** |

---

## 2. Protocol evaluation

| Option | Model | Fixes #1–3? | NAT | Discovery | Verdict |
|---|---|---|---|---|---|
| **SSH `-L`/`-R`** (today) | per-port forwards over a session | ✗ — *is* the cause | outbound only | none | **Reject as foundation** |
| **frp / rathole / bore** | reverse proxy, per-port config | partly (still per-port) | good | none | Reject — repeats #2/#3 |
| **WireGuard** | cryptokey-routed L3 overlay, one UDP port | ✓ no sessions, no per-port state, roams across IP change | needs one reachable endpoint or relay | build on top | **Recommended transport** |
| **Tailscale / Headscale** | WireGuard + control plane + DERP relays + MagicDNS | ✓ | ✓ excellent | ✓ built-in | Strong alternative; heavier, second control plane, less ownership |
| **Nebula** | cert-based mesh, lighthouse discovery | ✓ | ✓ good | partial | Good fit; own CA to run; smaller ecosystem |
| **ZeroTier** | L2 overlay, controller | ✓ | ✓ | ✓ | L2 semantics unnecessary here |
| **Docker Swarm overlay** | VXLAN + gossip, native container networking | ✓ | poor across NAT/WAN | ✓ | Would force Swarm adoption |
| **Service mesh** (Consul/Linkerd) | mTLS sidecars | ✓ | ✓ | ✓ | Far too heavy for 2–3 nodes |

### Why WireGuard specifically

It is the only option where **failures #1, #2 and #3 are structurally impossible**:

- **No sessions.** Cryptokey routing is connectionless — there is no half-open state for a WiFi drop to strand, so #2 cannot recur.
- **No multiplexing.** There is no `ControlMaster` concept, so #1 cannot recur.
- **No per-service forwards.** You route a subnet. There is no "leg set" to partially rebuild, so #3 cannot recur — the interface is up or down, atomically.
- **Roaming.** A peer's endpoint may change (WiFi reconnect, DHCP); the next authenticated packet re-binds it. Today's link is 2.4GHz WiFi with measured jitter (avg 11.8ms, max 50.7ms); roaming tolerance matters.
- **One UDP port per node.** No port map to maintain, no collisions.

Cost: it is L3 only (fine — all our traffic is TCP/UDP over IP), and it needs key + address management. **That management is exactly what the Network app is for.**

**Headscale remains a credible fallback** if NAT traversal turns out to be hard in a future topology; it can be adopted later *underneath* the same Network app UI without changing the app model.

---

## 3. Architecture

### L0 — Node identity
Every platform install generates on first boot:
- `node_id` (stable ULID), `node_name` (human, e.g. `shlomo-laptop`, `portable`)
- a WireGuard keypair; private key in the platform secret store, never in git

### L1 — Transport: the `Network` app
A container with `NET_ADMIN` owning a `pos0` WireGuard interface. Running it as a container (rather
than host WireGuard) keeps it a **platform app** — installed, upgraded, observed like any other — and
sidesteps host kernel-module differences (notably Docker-in-WSL on this laptop).

**Addressing:** each node gets a deterministic `/24` from `10.79.0.0/16`, derived from `node_id` with
collision detection at registration time. Node-local services get stable IPs inside that `/24`.

### L2 — Service addressing (the fix for #4)
Services get overlay IPs, **not** machines. A tiny per-node L4 proxy binds `10.79.<node>.<svc>:<port>`
and forwards to the local container. Consequences:

- no `172.18.x` subnet collisions between nodes
- a service keeps one address regardless of which node it lives on
- **local-first resolution is natural**: `apitools.pos` resolves to the *local* instance when one
  exists, peer instances otherwise. This produces, by construction, the on-box routing we hand-hacked
  today (measured **38.4ms → 4.8ms**, and remote job duration 79.3s → 20.7s).

### L3 — Discovery: catalog + DNS
Each node publishes a signed catalog:

```json
{ "node": "portable", "services": [
  { "name": "apitools", "kind": "http", "ip": "10.79.2.10", "port": 8080,
    "health": "/readyz", "version": "…", "labels": {"scaling.pool": "apitools"} },
  { "name": "n8n-worker-r3", "kind": "n8n-worker", "concurrency": 8,
    "labels": {"scaling.pool": "n8n-workers"} } ] }
```

The Network app syncs peer catalogs over the overlay and serves DNS for `<service>.<network>.pos`.
**The catalog is what makes the scaling UIs possible** — it is the list of remote workers the user
wants to see and activate.

### L4 — The management UIs

**`console > apps > n8n > management > scaling`**
- workers table: node, container, concurrency, **current occupancy (`mine=N/8`)**, jobs/min, last pickup
- queue: `wait` / `active` / `delayed`, and per-worker pickup rate
- remote: registered networks → available workers → **activate / deactivate** (N workers on that node)
- guardrails surfaced as first-class config: max workers per node, concurrency pinned at 8 with the
  OOM history shown as the reason

**`console > apps > apitools > management > scaling`**
- instances across all networks, with `/readyz` state and RTT measured *over the overlay*
- LB policy: local-first weight, spillover `maxconn`, retry-on rules
- shared-cache backend health, and a **strict-mode toggle** so a cache-backend failure fails loudly
  rather than forking to local files (fix for #3)

**`console > indox > scaling`**
- drain interval, batch size, per-stage quotas, candidate ordering (`created_at DESC`)
- backpressure policy (skip/reduce when in-flight exceeds threshold)
- live per-stage queue depths and rates next to the knobs that control them

These write to a **config store the workflows read**, not to shell scripts.

---

## 4. Enrollment — the share/register flow

Mapping the user's flow onto WireGuard:

**On machine2 (sharing):** `network > add share` →
```
pos://portable@203.0.113.7:51820/#<base64 pubkey>.<invite-id>.<hmac>
```
plus a one-time secret. The invite carries endpoint, public key, offered subnet, scope, expiry
(default 10 min, single-use).

**On machine1 (registering):** `network > add` → paste URL + secret →
1. POST its own public key to machine2's enrollment endpoint, authenticated by HMAC over the invite
2. machine2 allocates it a `/24`, adds it as a peer, returns its catalog endpoint and any shared
   secrets required for the scope (e.g. `N8N_ENCRYPTION_KEY` when the scope includes `n8n-workers`)
3. both sides bring up the peer; handshake completes; catalogs sync

**Authorization:** every registration carries a **scope** — which service pools are exposed. Default
deny-all-but-listed. Revocation removes the peer; traffic stops on the next packet.

**Secret distribution matters and must be explicit:** remote n8n workers require the *same*
`N8N_ENCRYPTION_KEY` as the main instance. That is a real secret crossing machines and must be
delivered through enrollment, scoped and revocable — never copied by hand as it is today.

---

## 5. Failure semantics — the part most likely to be skipped, and the part that bit us

1. **Health is end-to-end.** A service is healthy when it can *serve*, not when its process exists
   (#5) — apitools by `/readyz` including shared-cache reachability, n8n workers by *pickup progress*,
   not `pgrep`.
2. **Degradation is loud.** Any component that can fall back to a local substitute (the OCR cache is
   the known one) must either fail the request or mark itself degraded so the LB stops routing to it.
   Six hours of silent divergence must be impossible to repeat (#3).
3. **Link health is a first-class signal.** WireGuard has no connection state, so health =
   `last handshake < 3 × keepalive`. Surface it per peer in the UI.
4. **No hand-rolled watchdogs restarting subsets.** One interface, one lifecycle, owned by the app.
5. **Backpressure before dispatch.** The drain must check in-flight depth before adding load — today
   `wait=13` with `mine=8/8` was reached precisely because nothing checked.

---

## 6. Phasing

Each phase is independently useful; nothing requires the next.

| Phase | Deliverable | Proves |
|---|---|---|
| **1** | Network app: node identity, `pos0` WireGuard, share/register, peer health | two machines reach each other with no ssh, no port maps; survives a WiFi drop |
| **2** | Service addressing + catalog + DNS | `apitools.pos` resolves local-first; the double-crossing (#4) is structurally gone |
| **3** | n8n scaling UI (read-only observability first) | workers, occupancy, queue depth visible — the picture we had to reconstruct by hand all day |
| **4** | n8n remote worker activate/deactivate | one click replaces the ssh + socat + env choreography |
| **5** | apitools scaling UI (LB policy, strict-mode toggle) | #3 cannot recur |
| **6** | indox scaling UI (drain/batching config) | the drain becomes configuration, not a workflow edit needing a restart |

**Phase 1 + 2 alone retire every failure in §1.**

---

## 7. Data model

Five entities. Kept deliberately small — this is a network manager, not a service mesh.

```
Node            id, name, pubkey, overlay_cidr, endpoints[], version, created_at
Network         id, name, kind: local | docker | remote,
                cidr, owner_node_id, created_at
                # every install has: "machine" (local) + "platform" (the traefik docker net)
Registration    id, network_id, peer_node_id, direction: shared_by_us | registered_from_them,
                scope[], state: pending | active | revoked,
                last_handshake_at, rx_bytes, tx_bytes
Service         id, node_id, name, kind: http | tcp | n8n-worker | queue | db,
                overlay_ip, port, health_path, version, labels{}, last_seen_at
ScalingPolicy   id, app: n8n | apitools | indox, node_id | null (null = global),
                json config, updated_by, updated_at
```

`ScalingPolicy` is the piece that retires failure #6 — the drain interval, batch sizes, LB weights and
worker counts stop being script arguments and become rows the UIs edit and the services read.

## 8. API surface

Enrollment (only endpoint reachable *outside* the overlay; everything else is overlay-only):

```
POST /net/invite            → { url, secret, expires_at }        # machine2, "add share"
POST /net/enroll            ← { invite_id, pubkey, node_name, hmac }
                            → { assigned_cidr, peer_pubkey, endpoint, scope[], secrets{} }
DELETE /net/peer/:node_id                                        # revoke → traffic stops
```

Over the overlay:

```
GET  /net/catalog           → { node, services[] }               # what §3 L3 syncs
GET  /net/health            → { peers: [{node, last_handshake_s, rtt_ms, rx, tx}] }
GET  /scaling/:app          → ScalingPolicy
PUT  /scaling/:app          ← policy patch                       # the three UIs write here
POST /scaling/n8n/workers   ← { node_id, desired: N }            # activate/deactivate
```

Two rules worth stating explicitly, both learned today:

- **`/net/health` reports reachability, not liveness.** A peer is healthy when its last WireGuard
  handshake is recent *and* its catalog fetch succeeds — not when a process exists (#5).
- **`/scaling/*` is the only writer.** No shell script mutates scaling state. That is what makes the
  config survive a session (#6).

## 9. What "activate 3 remote workers" actually does

The payoff, concretely — this replaces the ssh + socat + env choreography that took a day to debug.

```
UI: apps > n8n > management > scaling > remote
    network "portable-platform-os" → workers: 5 available, 0 active → set 3 → Apply
```

1. `POST /scaling/n8n/workers { node_id: portable, desired: 3 }`
2. main node resolves the worker's dependencies **to overlay addresses**, not tunnels:
   - `QUEUE_BULL_REDIS_HOST = redis.shlomo-laptop.pos`
   - `DB_POSTGRESDB_HOST    = n8n-postgres.shlomo-laptop.pos`
   - `N8N_ENCRYPTION_KEY`   ← delivered at enrollment, scoped to `n8n-workers`
   - apitools ← resolved **local-first** on the portable, so a worker there uses the apitools on its
     own box (the 38.4ms → 4.8ms win) with peer fallback through the LB
3. portable's platform starts 3 worker containers with that env
4. workers appear in the catalog; the UI shows occupancy (`mine=N/8`) and pickup rate per worker
5. deactivate = scale to 0; revoking the registration removes reachability entirely

No port map. No socat. No watchdog. No `ExitOnForwardFailure`. The pieces that broke today are not
merely fixed — they no longer exist in the design.

## 10. Migration — what today's manual work becomes

Nothing built today is wasted. The transport is replaced; the **policies we discovered by suffering
are promoted to configuration**; the domain logic stays where it is.

### Replaced outright (deleted, not ported)

| Today | Why it goes |
|---|---|
| `tunnel.sh` + all leg definitions (`-L 18080`, `-R 19118/19019/19120/19018/19028`, mesh `19001-19021`) | one interface replaces every leg; there is no partial leg set to rebuild |
| `apitools_tunnel_watchdog.sh`, `meshtunnel_watchdog.sh` | nothing to watch — WireGuard has no session to strand |
| socat shims (`127.0.0.10:8080` → tunnel) | service overlay IPs make the indirection unnecessary |
| the whole 19xxx port map | subnets, not ports |
| ssh config stanzas (`ControlMaster no`/`ControlPath none` workaround) | no ssh in the data path at all |

### Promoted to platform features (logic survives, home changes)

| Today | Becomes |
|---|---|
| `apitools-lb` haproxy `be_split` / `be_localfile` + `haproxy-portable.cfg` | haproxy stays as the **data plane**, but its config is *generated* from `ScalingPolicy(apitools)`. "local-first with `maxconn 12` spillover, no affinity" becomes a policy field, not a hand-edited file. |
| `OCR_CACHE_STRICT`, `/readyz`, 500→503 rewrite, `/dev/shm` cross-worker health marker | the **standard service-health contract** every platform app implements. This is the #3 fix, generalized. |
| `drift-check.sh` (must-match vars, signer hash, deployed `src` fingerprint, `/readyz` both sides) | the platform's **cross-node drift check** — already the right shape for multi-node; just needs to iterate the peer list from the catalog |
| `reapnow.sh` / `reaploop.sh` (running>30m, new>60m) | an n8n-app **stalled-execution policy**, with the thresholds as config (they were derived from a measured 1,709s worst legitimate queue wait — that derivation belongs in the UI as the explanation) |
| `incdocguard.sh` (recycle at 90% when idle) | a **container memory policy**: recycle at N% when CPU < M%, min interval. Keeps the crucial idle-check that the naive `GUNICORN_MAX_REQUESTS` fix lacks. |
| `memwatch.sh` | node health telemetry in the catalog |
| `perf-profiles.yml` (concurrency pinned 8) | `ScalingPolicy` **defaults**, per-node (see §12 — 8 is a property of *this* node's RAM, not a universal constant) |
| `reconcile-orphans.py`, `ocr-cache-retention.py` | scheduled maintenance jobs owned by the apitools app |

### Unchanged

`bbox` (it *deploys* the network app), the INDOX drains and driver (domain logic — the indox scaling
UI configures them), the extraction workflows.

**The honest summary:** today's manual scaling was a working prototype whose failures constitute the
specification. The overlay deletes the transport; everything else is a home-change.

## 11. Limitations — what stops this working out of the box

Grouped by whether they are solvable, mitigable, or genuinely blocking. This section matters more than
the architecture: a design that only works on *this* laptop is not a feature.

### A. Kernel and host

| # | Limitation | Reality | Mitigation |
|---|---|---|---|
| A1 | WireGuard kernel module | in-tree since Linux 5.6; WSL2's kernel has it; Docker Desktop's LinuxKit VM and macOS do **not** | ship `wireguard-go` userspace fallback in the app image, detect at boot, **report which mode is active in the UI** (userspace is ~3-5× slower — the user must be able to see that) |
| A2 | `NET_ADMIN` capability | required to create `pos0`; forbidden on some managed/PaaS hosts | detect at startup and **fail loudly with a specific message**, never degrade silently |
| A3 | `/dev/net/tun` availability | absent in some hardened runtimes | same — explicit precondition check |

### B. Network topology — the genuinely blocking ones

| # | Limitation | Reality | Mitigation |
|---|---|---|---|
| B1 | **Both nodes behind NAT, neither reachable** | direct WireGuard is *impossible*; this is not a tuning problem | requires a relay. Either one node must have a reachable endpoint (VPS — the common case), or adopt **Headscale/DERP**. **Document this as a hard precondition.** |
| B2 | **UDP blocked** (corporate, hotel, some mobile) | WireGuard is UDP-only | TCP fallback (`wstunnel`/`udp2raw`) as an explicit, slower mode; surface it in the UI as degraded |
| B3 | CGNAT on both sides | same as B1 | relay required |
| B4 | **MTU / path-MTU black holes** | WireGuard adds ~60-80 bytes. Symptom: small requests fine, **large uploads hang** — and apitools uploads documents. This is the single most likely "it works until it doesn't" bug | set MTU 1420 by default, run a **large-payload probe during enrollment**, and store the working MTU per peer |
| B5 | Roaming endpoint changes | handled natively (this is a WireGuard strength) | `PersistentKeepalive=25` on the NATed side |

### C. Address space

| # | Limitation | Mitigation |
|---|---|---|
| C1 | Overlay CIDR colliding with a corporate LAN or docker pools (`172.17-31`, `192.168.x`) | `10.79.0.0/16` default, **configurable**, with a collision check against local routes *and* the peer's routes at registration — refuse, don't guess |
| C2 | Two nodes deriving the same `/24` from `node_id` hash | detect at enrollment; reallocate |

### D. Identity and secrets

| # | Limitation | Reality |
|---|---|---|
| D1 | **`N8N_ENCRYPTION_KEY` must match across n8n nodes** | a worker on a node with a different key cannot decrypt credentials. Enrollment must deliver it, scoped — and there must be an explicit **"worker-only node"** deployment profile |
| D2 | n8n ties workflows/credentials to owner user/project IDs | fine for worker-only nodes (they execute, they don't own). Running a *full* n8n on a second node creates divergent IDs — **not supported**; say so |
| D3 | Clock skew | WireGuard tolerates it; Bull timing, JWTs and log correlation do not. We already lost time today to **host UTC+3 vs portable UTC**. Require NTP, surface measured skew per peer |

### E. Data plane — the class that actually bit us

| # | Limitation | Why it generalizes |
|---|---|---|
| E1 | **Silent local fallback** | the OCR cache fell back to a local JSON file for **6 hours** while haproxy kept routing 81.6% of traffic to it. **Any service with a local substitute will do this.** The platform must require each app to *declare* its shared-state dependencies and fail loudly when one is unreachable |
| E2 | **Endpoint locality** | measured: `/documentJsonQuery` resolves cross-node, `/documentImage` returns 404 — byte artifacts are node-local (host 13GB/12,529 files vs portable 4GB/3,687, nearly disjoint). The catalog needs a **per-endpoint locality flag** (`shared` \| `node-local`), and the LB must not route node-local endpoints to a peer |
| E3 | **Connection budget** | more nodes ⇒ more DB connections. Supabase `max_connections=100` (32 in use today). 5 remote workers × concurrency 8 can exhaust it | `ScalingPolicy` must model a connection budget and refuse allocations that exceed it |
| E4 | Shared filesystem assumptions | there is none, and there should not be one over WiFi. Anything needing shared bytes must go through an object store or the owning node |

### F. n8n-specific ceilings the platform cannot fix

| # | Limitation | Consequence |
|---|---|---|
| F1 | **`maxStalledCount: 0` is hardcoded** (`dist/scaling/scaling.service.js:89`) | a stalled job fails permanently with zero retries. Higher-latency remote workers stall *more*. Surface stall rate per node; treat it as a placement input |
| F2 | **Scheduled-workflow definitions are cached at registration** | changing a scheduled workflow needs an n8n restart — proven repeatedly today. The platform cannot fix this, but the indox scaling UI **keeps drain config outside the workflow** so tuning never needs a restart |
| F3 | Worker concurrency 8 | this is a property of *this* node's RAM and OOM history — **not a universal constant**. Per-node, memory-derived defaults |

### G. Operations

| # | Limitation | Mitigation |
|---|---|---|
| G1 | Version skew between nodes | version the catalog and control API; refuse incompatible enrollment with a clear message |
| G2 | Upgrade ordering (master upgraded, workers old) | drain workers before upgrade; the UI owns the sequence |
| G3 | Federated observability | logs/metrics are per-node. Minimum viable: the catalog carries health + rates, and the UI aggregates. Full log federation is out of scope |
| G4 | Control-plane split-brain | exactly one node holds `master` role per network; enrollment records it; refuse a second |

### H. Security

| # | Limitation | Mitigation |
|---|---|---|
| H1 | Leaked invite = unauthorized join | single-use, 10-min expiry, HMAC-bound to the inviting node's key |
| H2 | Over-broad access after joining | **scope is default-deny**; a registration grants named service pools only |
| H3 | Revocation | remove peer ⇒ traffic stops at the next packet; UI must show it took effect, not just that the row was deleted |

## 12. Multi-node: a master and many scaling nodes

The target topology the user described — one master registering many networks, each offering capacity.

### Topology: hub-and-spoke, not full mesh

The master registers every node. Spokes do **not** need to reach each other: a worker on node B needs
redis/postgres on the **master**, and apitools **locally**. `AllowedIPs` enforces this, which also
keeps the security surface small. Full mesh stays possible later without redesign.

### Scaling slots as a first-class concept

Each node advertises capacity, and the master allocates against it:

```
Node.capacity = {
  cores, ram_mb, ram_available_mb,
  slot_size_mb,                  # memory per worker slot, measured not guessed
  slots_total, slots_used,
  slots_ceiling_observed,        # see below — the important one
  link: { rtt_ms, jitter_ms, mode: direct|relay|tcp-fallback }
}
```

**The ceiling must be measured, not computed.** We learned empirically today that a **6th and 7th
remote worker *reduced* total throughput** — arithmetic from cores and RAM would have predicted the
opposite. So the platform should:

1. allocate slots incrementally,
2. measure completed-work rate after each step,
3. record the knee where throughput stops improving as `slots_ceiling_observed`,
4. **refuse or warn past it**, showing the measurement as the reason.

That turns a painful discovery into a permanent, per-node property — and it is a genuinely novel
feature rather than a port of a script.

### Placement policy

Placement is driven by locality, not just free capacity:

- **apitools** → local-first always (measured 38.4ms → 4.8ms, remote job duration 79.3s → 20.7s)
- **n8n workers** → anywhere, but weighted by measured redis RTT; a node on a 58ms link is worth a
  fraction of a local slot and the UI should say so numerically
- **extraction** → only on nodes that have a local apitools
- **node-local endpoints** (E2) → never routed to a peer

### Deployment profiles

The user's flow — "deploy platform os on portable (basic apps + apitools, no indox)" — is a
**profile**: `worker-node` = network app + apitools + n8n workers, no indox, no console-facing apps.
`master` = everything. Profiles make the out-of-the-box path a single choice at install time rather
than a manual pruning exercise.

## 13. The primary case, solved: two laptops on one LAN

This is the case that must work out of the box, and it is the **easy** one — §11/B1 (both behind NAT,
no reachable endpoint) **does not apply**. Two machines on the same WiFi are on one broadcast domain:
they address each other directly, no relay, no rendezvous, no hole punching.

**Committed mechanism: WireGuard, direct peer-to-peer over the LAN, discovered by mDNS.**

### Single codebase, role is per-registration

Both installs are byte-identical. Two things vary:

- **Profile** — which apps run (`master` = everything; `worker-node` = network app + apitools + n8n
  workers, no indox, no console-facing apps). A profile is an install-time choice, not a fork.
- **Role** — `master` or `member`, and it is a property of a **registration**, not of an install.
  Every node ships the full share *and* register feature set. A node can be master of one network and
  a member of another. This is what makes "one master registering many networks" (§12) fall out
  without a second build.

### Discovery — this is the "magic", and it removes the IP typing

Each node advertises over mDNS/DNS-SD on the LAN:

```
_platformos._udp.local
  TXT: node_id, name, role, profile, wg_port, wg_pubkey_fp, api_port, version
```

The Network app UI then shows **"Nodes on this network"** with no configuration at all — the portable
appears in the master's list the moment it boots on the same WiFi. Pairing becomes:

```
master:   Network > LAN nodes > [portable] > Register     → shows a 6-digit code
portable: Network > shows incoming request                → confirm the same code
          (or pre-authorize: Network > Share > "allow next request", 10-min window)
```

Public keys exchange over the LAN, authenticated by the short code — the same shape as Bluetooth
pairing, and immune to a typo'd IP. **The paste-a-URL-and-secret flow stays** as the manual path for
a VPS or a node on another network; it is the fallback, not the primary UX.

### Addressing and roaming

The WireGuard endpoint is the peer's LAN IP, learned from mDNS and refreshed as it re-advertises.
DHCP churn is handled twice over: mDNS re-advertises, and WireGuard updates a peer's endpoint on the
next authenticated packet from a new source address. `PersistentKeepalive=25` keeps NAT-less LAN
sessions warm and makes roaming recovery immediate.

**This is the concrete fix for the failure that dominated today.** A WiFi drop currently strands an
`sshd` session holding `-R` ports, and the supervisor with `ExitOnForwardFailure=yes` then exits
forever. WireGuard has no session and no per-port listener: after a drop, the first authenticated
packet simply resumes. Nothing to reap, nothing to rebind, nothing to watchdog.

### The real limitation on a LAN is the access point, not the protocol

Measured on this pair today: **RTT 11.8ms avg, 50.7ms max, ~0.70 MB/s** between the laptops, while
each reaches the router in 1–2ms. The AP is decrypting, re-encrypting and retransmitting every byte —
it crosses the air twice through a low-end CPU. WireGuard will not change that ceiling; **~0.70 MB/s
is roughly 2.5 GB/hour of cross-machine traffic, and that is the real budget.**

So the design must *minimise bytes crossing the link*, which is exactly what §3/L2 service locality
does:

- apitools resolves **local-first** on each node — the measured 38.4ms → 4.8ms, and the reason remote
  job duration fell 79.3s → 20.7s. Documents never cross the air to be OCR'd.
- only **control traffic** (Bull job messages, postgres queries, catalog syncs) crosses — small and
  latency-sensitive, which is what the link is actually good at.
- node-local endpoints (§11/E2 — rasters, byte artifacts) are never routed to a peer.

If more cross-link throughput is ever needed, the answer is physical (5GHz, or a cable), not
protocol. The UI should show the measured link budget so that is obvious rather than mysterious.

### Failure modes specific to same-LAN, and what the app does about each

| Symptom | Cause | App behaviour |
|---|---|---|
| Peer visible in mDNS, handshake never completes | **AP client/AP isolation** — the one genuinely blocking LAN case | detect (visible but no handshake in 30s) and say exactly that: *"your access point is blocking device-to-device traffic — disable AP isolation / client isolation"*. Actionable, not a dead end. |
| mDNS shows nothing | multicast filtered, or different VLAN/SSID | fall back to the manual paste-URL flow; hint the likely cause |
| Peer IP changed | DHCP lease / reconnect | mDNS re-advertise + WireGuard endpoint roaming; no user action |
| Large uploads hang, small requests fine | **MTU black hole** (§11/B4) | enrollment runs a large-payload probe and pins the working MTU per peer |
| Link fine, throughput poor | the AP ceiling above | surface measured RTT/throughput in the UI as the link budget, with placement already local-first |

### Why this is both the most efficient and the most stable choice here

- **Efficient**: kernel-level crypto, one UDP flow, no relay, no double-crossing of the AP, no
  userspace copy per packet. On a LAN it is as close to raw as an encrypted overlay gets.
- **Stable**: connectionless (nothing to half-open), roams across IP change, one interface that is up
  or down rather than a set of legs that can be partially rebuilt — which is precisely the class of
  failure that produced a 6-hour silent split-brain today.

## 14. The second case: a scaling slot on a VPS

Same codebase, same app, same profiles. The only thing that changes is **discovery**, because there is
no shared broadcast domain — which is exactly why the paste-a-link flow exists.

### It works, and it is the easiest topology of the three

A laptop behind NAT talking to a VPS with a public IP is the canonical WireGuard deployment:

- the **VPS is the reachable endpoint**; the laptop dials out
- NAT keeps the mapping open via `PersistentKeepalive=25`
- once the handshake completes the tunnel is **fully bidirectional** — the VPS can reach services on
  the laptop through it, despite the laptop having no public address

### The one structural rule: the reachable side issues the invite

WireGuard needs at least one side with a known endpoint. A NATed laptop has none, so:

> **The invite carries the inviter's endpoint. The inviter must be reachable.**

For a VPS slot that means the **VPS shares** and the laptop registers — precisely the flow described:
open the VPS's Network app → *Share* → it returns a link + secret → paste into the local machine's
Network app → *Register*.

The app enforces this rather than letting it fail mysteriously: at invite time it checks whether it
has a reachable endpoint (public IP, or same-LAN peer). If not, it refuses with the specific reason —
*"this node is not reachable from outside; share from the other node instead"* — instead of minting a
link that can never complete a handshake.

### Secrets are delivered after the handshake, never in the link

The invite link travels through an untrusted channel (copy-paste, chat, email). So it carries only
what is safe to leak for 10 minutes: endpoint, public key, invite id, HMAC, expiry.

Everything sensitive — notably the **`N8N_ENCRYPTION_KEY`** a remote worker needs (§11/D1) — is
delivered **over the established encrypted tunnel**, after the peer has proven possession of the
invite secret. This matters far more over the internet than on a LAN.

### A VPS slot may be *faster* than a LAN slot

Worth stating plainly, because it is counter-intuitive and it changes placement decisions:

| link | RTT | throughput |
|---|---|---|
| laptop ↔ laptop over the AP | 11.8ms avg, 50.7ms max | **~0.70 MB/s** (AP-bottlenecked, measured) |
| laptop ↔ VPS over the internet | typically 5–40ms | typically **10–100+ MB/s** |

The LAN wins on latency; the VPS usually wins on bandwidth by two orders of magnitude. Since the
scaling policy weights placement by **measured** RTT and throughput (§12), neither is hardcoded as
"better" — the platform measures both links and decides.

But the locality rule is unchanged and matters more here, not less: **a VPS worker must have apitools
local to it**, so documents are never shipped across the internet to be OCR'd. That is the same
`worker-node` profile as the portable laptop — apitools + n8n workers + network app, no indox.

### VPS-specific considerations

| Item | Detail |
|---|---|
| **Firewall** | one inbound rule: UDP 51820 (configurable). Nothing else needs to be exposed — all platform APIs live on the overlay, not the public interface |
| **Scanning surface** | WireGuard does not respond to unauthenticated packets at all. The port is effectively invisible to scanners — a real security gain over exposing an SSH tunnel endpoint |
| **Egress cost / data residency** | local-first apitools keeps document bytes on the node that holds them; only control traffic crosses. Relevant for both billing and compliance |
| **Clock skew** | NTP required; skew surfaced per peer (we lost time today to host UTC+3 vs portable UTC) |
| **Provider reboots / IP change** | an elastic/static IP is preferable; if the IP does change, re-issue the invite. mDNS cannot help across the internet |

### Mixed topology falls out for free

A master can hold several registrations at once — the portable over the LAN *and* a VPS over the
internet — because a registration is per-peer and role is per-registration (§13). The scaling UI then
shows one pool of slots across both networks, each annotated with its measured link characteristics,
and placement picks per the policy. No special case, no second mechanism.

## 15. Risks and open questions

- **WireGuard in Docker-in-WSL on the Windows host.** Container with `NET_ADMIN` is the intended
  path; needs a spike to confirm on this specific setup. (Fallback: `wireguard-go` userspace.)
- **Both nodes behind NAT with no public endpoint.** Direct WireGuard needs one reachable side. Same
  WiFi ✓; laptop↔VPS ✓; two roaming laptops on different networks ✗ → would need a relay (DERP-style,
  or adopt Headscale).
- **UDP blocked** on some networks. Mitigation: WireGuard-over-TCP shim, or fall back to Headscale's
  relays.
- **Overlay-subnet collisions** with existing docker networks — deliberate use of `10.79.0.0/16` and
  a collision check at registration.
- **Who owns service→overlay-IP allocation** when the same service runs on several nodes: proposed
  answer is per-node IPs plus a *virtual* service name resolved local-first, not an anycast IP.
- **Scope creep into a service mesh.** Explicitly out of scope: retries, circuit breaking, tracing.
  The LB already covers what we need.
- **n8n's own limits remain.** Scheduled-workflow definitions are cached at registration and need a
  restart to change (proven today); `maxStalledCount: 0` is hardcoded. The Network app does not fix
  those and must not pretend to — but the indox scaling UI should keep drain config *outside* the
  workflow so tuning it stops requiring a restart at all.
