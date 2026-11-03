# DGO — the architecture review (2026-10-14)

**Asked by the owner, verbatim:** «Deeply review all the chalnges dgo faces as industry leading edge
software at this scale and how stuff where implmented, map out the dessions made and the logic across
the dgo source code and suggest the best possible architecture and patterns for the most optimal clear
clean and sharp dgo solution, everything generelised cleaned minimised and cleand, battle tested and
completion of all tasks and full plan. Deep research world leading public software architecture 2026
from high level patterns to networking to ui to api and cli and os and omni to multi binary any os base
to poblic online npm like repo on apps.net.digital-office.co.il to comprehansiv dgo state and data
layer» — and the bar: «minimal dependencies and max secure and minimal to 0 duplications and minimal
coupling and simplicity and generality. Of course with 0 feature loss. Minmal bytes in full final dgo
solution».

**How this was made.** Three read-only maps of the source as it is (layer 0: compiler/state/CLI;
links/identity/edge; UI/apps/data), one measured audit of the release machinery (tests run, binaries
built), five research briefs on the 2026 state of the art (bootstrapper+signing+size, Android, package
registries, platform-OS architecture, single-binary bases + dgo-net), and the 100 newest work items
(DGO-491…591) read in full. Every claim about the code carries `file:line` (branch `hp-dgo` @
`7347f738`, the committed files — the working tree carries other writers' uncommitted lines); every
claim about the world carries a dated source in the research briefs under `ai/context/research/`.

The one-sentence verdict: **DGO already made most of the right decisions — declared manifests, one
compiler, refusal over guessing, one writer per fact, the door proves identity — and pays for them
in the wrong currency: Python on the host, bash around Python, fifteen moving parts per linked tile,
and eighty gates asserting after the fact what a type and a binary could make unrepresentable.**
The optimal DGO is not a rewrite; it is the same contract behind ONE Go binary per machine, with the
containers kept exactly where the owner put them: layers 1–3.

---

## 1. The challenges — what "leading-edge at this scale" means here

| # | Challenge | Why it is hard for DGO specifically | Where it bit in the last two weeks |
|---|---|---|---|
| C1 | **A product that installs from a download on every OS** (Windows, macOS, Linux, a VPS, a phone) | the core is Python+bash+containers; the host needs python3+PyYAML+docker+git before the first screen; three hand-offs (cmd→WSL, Lima, sandbox) each with its own failure class | WSL's service refused every command for most of this evening (0x8007274c) while the office ran; the installer stub is 85 KB over 5 MiB; `dgo-core` exits 2 on a fresh machine (packaging audit §3) |
| C2 | **Many offices, one owner, pairs that live until unpaired** | the tunnel holds (WireGuard), the RECORD does not: 5 writers, 2 tunnel appliers, a /24 per pair, DHCP leases, sleeping laptops, NAT | 13 death modes catalogued (DGO-555); D5 silent record drop has no detector; the Mac has been off the network for days (DGO-503) |
| C3 | **Identity that crosses the link without a second password** | identity is header-based inside each office; the link door signs a header; only one app verifies it; token handoff for a PAIRED pair has no channel | DGO-545/581/589/590/591: the browser's door unpublished, vps1's identity refused (401), 200-empty doors |
| C4 | **An autonomous agent that works all day under a budget** | the harness has no resource ceiling; a round carries the whole context; the pulse revived finished goals; the container restarts in place mid-turn | $4.92/night (DGO-539); 11 cycles opened by a probe (DGO-565); a cycle killed with the container, nobody told (DGO-582) |
| C5 | **One shell for every app, every screen size, Hebrew RTL** | apps are frames of frames proxied through the console; third-party apps decide "phone" by user-agent; the simulation is a second UI | DGO-574/576 (UA), 551/552 (mobile menu), 569 (remote deep links), 525/527 (sim drift) |
| C6 | **Declared state, one writer, three agents in one tree** | `platform.state.yaml` is both a repo file and a per-office runtime record; writes are regex surgery from 6 surfaces without a lock; a live rebuild ships uncommitted code | `.env` clobbered to 43 bytes by a test (DGO-585); 102 commits unpushed because the agent's container has no git credential; vps1 47 commits apart (DGO-549) |
| C7 | **Shared blueprints as truth across offices** | `pull` from a non-canonical n8n rewrote the shared blueprint; `push` truncated a Code node silently | DGO-558, DGO-584 |
| C8 | **Quality as a system** | 81 gate numbers, 64 run, 80 lint scripts, most policing JSON by regex; blind spots read green; root-600 files written by the agent crash the suite | DGO-587: 12 static gates red on the live office |
| C9 | **Supply chain and release** | signing path complete and tested, never used: no key, no manifest host, no tag, no push-time `go test` | packaging audit §4–5 |
| C10 | **Cost of a human-shaped request** | one bug report = 31.8 min, 457 tool calls; `plan office` 3–4 min per run | DGO-559 (fixed tonight in `plan.py`: three measured causes) |

## 2. The decisions in the code — what to keep, what to move, what to retire

The three maps found **24 + 30 stated design decisions** (reason written beside the code — the repo's
own discipline). Grouped by what a 2026 redesign should do with them:

### 2.1 Keep untouched (the contract)

| Decision | Where | Why it is right |
|---|---|---|
| **The directory is the layer**; the loader refuses a mismatch | `reconcile.py:35-44`, `:495-520`; G9/G31 | "what can I uninstall" is `ls apps/`; the dependency rule needs no document |
| **One compiler, (catalog, state) → `.generated/`**, `compose_files()` the single answer to "which -f files" | `reconcile.py:1-11`, `:948-976`; `lib.sh:413 dcx` | every path asks the same function; a bare `docker compose` is a gated no-op |
| **Explicit, refusing resolver** — binding → default_provider → sole candidate → error naming all; conflicts named; cycles named; ordering only via `after` | `:760-910` | ambiguity is never resolved by position; Debian/Gateway-API semantics |
| **Three dispositions with provenance** (`enabled/disabled/archived`, `by:`) | `:217-228` | archived = images gone, data and tile kept |
| **One writer per state block**; product default split from office runtime; a silent reset refused | `:274-300`, `:526-568`; `platform.state.default.yaml` | G33 proves there is one writer; the Mac's set no longer resets another office |
| **Plan + generations**; `apply` refuses a stale plan; rollback is config-only and says so | `:1778-1878` | Nix insight without symlinks (Windows) |
| **Hooks = a file that exists** (`<app>/hooks/<verb>`), help generated from the tree, `bbox` names no app | `bbox:354-412`; `lib.sh:1052` | adding an app edits nothing in the CLI |
| **Pair from the screens; host decides who dials, once; holder-side record; token first** | `pair_api.py:577-591`, `:309-311`; `net.py:150-169` | the two real outages (NAT source port, reversed dial) are settled by these |
| **One door per link, `Host` picks the app; the door strips every `x-authentik-*` and SIGNS the mapped user** | `link-proxy.py:68-106`, `:592-627` | identity is proved, not carried; a browser over a link carries no cookie of ours |
| **Catalog = projection of the compiled registry, pulled, declared through the control plane**; peer address derived, never published | `projection.py:66-135`, `:252-258` | a bad peer catalog cannot break a compile here |
| **Receiving-side nftables rendered whole**, point-to-point only, no relay | `firewall.py:17-35`; `tunnel-entrypoint.sh:26-36` | an `accept` cannot outlive its declaration |
| **The `{ok, hop}` verdict → `link.json` → the console marks before opening** | `app.py:1451`; `peers.py:141-153` | cross-origin frames fail blind; this is the one place that does not |
| **Go port method: stdlib only, PyYAML-1.1 subset reader, Python as the oracle, `DGO_COMPILER=python` per verb** | `packaging/dgo/internal/*`; `TestEnabledAppsMatchesPython` | the only safe way to move a 3,200-line compiler: verb by verb, byte-identical |
| **A gate exists only for a defect that broke once and nothing noticed; one list, `--verify-ci`** | `GATES.md:1-6` | the registry is honest about why each gate exists |

### 2.2 Keep the decision, move the implementation (same contract, new body)

| Today | Target | The decision kept |
|---|---|---|
| compiler in Python, 20 verbs, run twice per `dc` call (`compose_args`) | the same 20 verbs native in `dgo`, byte-identical render, Python retired verb by verb | one compiler; `.generated/` never edited |
| `bbox` 1,000 lines of bash + `lib.sh` with 48 `python3` calls, a mirrored `read_env` in two languages | `dgo` = the CLI; `bbox` a one-line shim; `.env` read in one place | hooks-by-file, generated help, bbox names no app |
| app-management (Flask), connections (Python vault), console server (Flask proxies), notifications (Python) | `dgo serve`: control plane + console static files (`embed`) + vault file + notifications — one process, one port, one log | one writer of state (now behind an API with a lock instead of regex surgery from 6 surfaces) |
| `dgo-net`/`dgo-link`: an 890-line Python TCP splice + a 277-line shell sweep inside 64 MB containers; wg-quick on the host for declared offices | one Go network service (wireguard-go or kernel wg via netlink, the door, the catalog listener, the finder) — `dgo net` — the SAME layout for paired and declared offices | host decides dial; one door per link; door signs identity; receiving-side firewall |
| authentik (4 containers, 1.1 GB) + forward-auth written but unwired | forward-auth wired (the cutover window F1–F3 the review already names) | the identity service is a drop-in; passwords and sessions survive |
| 80 regex lint scripts over n8n JSON (G36–G53) | the blueprint compiler (`*.workflow.ts` → JSON) validates on write; a gate that encodes a rule the compiler now refuses is retired the same day | a defect that broke once stays unrepresentable instead of lint-shaped |

### 2.3 Retire or replace (the decision itself was a workaround)

| Decision | Why it existed | Why it goes |
|---|---|---|
| `platform.state.yaml` tracked in git as the MAC's set, skip-worktree locally (DGO-408) | one state file served as both product default and office runtime | the default is `platform.state.default.yaml` (tracked); the runtime record belongs in the office's data dir, never in the repo |
| `set-state` callable from the agent's own config, scripts, two apps | there was no API with a lock | one control-plane API; every other caller is a client |
| two tunnel appliers (host `wg-quick@wg0` for declared offices, container tunnel for pairs) | declared offices predate pairing | one applier (`dgo net`); the vps1↔Mac host-level link is the root of D5/D6 |
| `serve: {"*": {}}` on first pairing (includes app-management, computers, connections) | "my other office" | serve by capability class with an explicit allow-list; the vault and the control plane are never served by default |
| the office pulse (`pulse.sh`, still on HP) | the harness never continued a goal by itself | the seder in n8n + a budget gate in the door (vps1 already deleted the pulse — DGO-562) |
| `.claude/worktrees`, three writers in one checkout, `bbox run --build` shipping uncommitted code | one machine, three agents | each agent commits to its own branch in its own worktree and PUBLISHES; the office runs COMMITTED code only (`bbox run` from a clean tree or a tag) |

## 3. The measured reality the plan must start from (2026-10-14)

- **Tests, native on Windows (Go 1.22.3):** installer 12/12, relsign 6/6, forward-auth 28/28, dgo 39/41
  (the two failures are in an UNTRACKED work-in-progress encoder of another session — not to land as is).
  The differential oracles ran against real Python+PyYAML: 56/56 corpus files, `validate` and
  `enabled-apps` byte-identical and 2–4× faster warm.
- **Sizes (`-s -w -trimpath`, CGO=0):** dgo-install windows/amd64 5,327,872 B (+84,992 over 5 MiB),
  darwin/amd64 5,287,104 (+44,224), the other four under; `dgo` 2.58 MB; forward-auth 7.65 MB. The
  stub's weight is `net/http`+TLS; a probe over bare `crypto/tls` with a hand-rolled HTTP/1.1 GET is
  3,786,752 B — the only lever that clears 5 MB (UPX never: Defender, notarization, macOS arm64).
- **Behaviour:** a double-clicked `dgo-install.exe` prints the terms and exits 1; the payload
  `dgo-core` is the CLI shim, which exits 2 "not inside a DGO checkout" on any fresh machine. **There
  is no layer 0 to download yet.** Nothing has ever been signed or published (no key, no host, no
  tag); no push-time workflow runs `go test`.
- **Part 3 exists in Python and the plan did not name it:** `platform/manager/catalog.py` (F-Droid
  index-v2 model, detached Ed25519 index signature, deterministic app zips, `bbox catalog
  keygen|build|verify`) and `appinstall.py` (`bbox app install <id|url|path|dir>`: fetch → sha256 →
  safe unpack → validate → resolve → disclose → enable). The Go store starts from these, not from zero.
- **Code risks found in the audit:** forward-only protection against a user-writable `VERSION` file;
  manifests without expiry or sequence (an old signed manifest replays forever on a fresh machine); the
  signed message omits os/arch; redirects followed https→http; one key with no rotation; `/login` in
  forward-auth unthrottled at PBKDF2-210k; toolchain drift (go.mod 1.22 vs Dockerfile 1.23).
- **Three packaging lineages, none canonical:** the 2.2–2.5 GB BinaOS bundle (cosign, Inno Setup,
  `binaos.service`), the native-binary lane (`build-binaries.sh`, relsign), and the Python catalog.

## 4. The 2026 state of the art, per dimension the owner named

Condensed from the five research briefs (`ai/context/research/*.md`, every claim sourced and dated there).
Each row ends with what DGO adopts and what it avoids.

| Dimension | What the field converged on (2025–26) | DGO adopts | DGO avoids |
|---|---|---|---|
| **High-level pattern** | Declared desired state + a level-triggered reconciler with `generation`/`observedGeneration`, Condition-shaped status, inventory `prune`, finalizers (Kubernetes/Flux); plans as signed artifacts applied verbatim and `-refresh-only` drift with exit 2 (Terraform); generations with `switch|boot|test|--rollback` (NixOS); Compose stays the rendered layer (the spec is open; Compose v5.2 added its own observed-vs-expected plan) | all of it, literally — the compiler already has plan+generations+refusals; it gains status/conditions, drift and finalizers | a manifest dialect of its own; edge-triggered on-change hooks; partial `-target` applies; image-tag polling |
| **Product precedents** (Umbrel 2.0, CasaOS, Coolify 4, Dokploy, YunoHost, TrueNAS, Home Assistant, Nextcloud ExApps, Sandstorm, Runtipi) | digest-pinned multi-arch images, explicit port/data-root/hooks, `backup: hot|cold`, `watchdog`, `breaking_versions`, typed install questions, CI-computed quality levels, pull-before-stop rollback, a static signed index | Umbrel's image discipline, HA's backup/watchdog/breaking fields and visible security score, YunoHost's install questions, TrueNAS's `app_migrations`, Runtipi's rollback | the three failure classes every surveyed platform paid for: shell strings as the control-plane API (Coolify/Dokploy RCEs 2025–26), forward-only updates, the Docker socket as the app API; floating-tag updates; auth as a proxy flag |
| **Networking** | a per-machine WireGuard key IS the device identity; policy = signed rules over tags/service names; discovery = tunnel-scoped DNS; the node embedded in the binary (wireguard-go/netstack, tsnet); encrypted relays that cannot read traffic (DERP, peer relays); tailnet-lock so no coordination server admits a node alone (Tailscale/Headscale 0.29/NetBird/Nebula) | point-to-point WireGuard as the base (what DGO has), the node moved INTO `dgo` (netstack, no TUN on Android), a blind relay any office can host, a lock rule for admission; keep host-decides-dial, holder-side record, receiving-side firewall | a vendor root; a TURN fleet before P2P + one relay fails; unaudited meshes as trust anchor; two tunnel appliers |
| **Identity** | per-site OIDC IdP in one binary (Pocket ID passkey-only on SQLite; Ory Hydra 5–15 MB; Authelia as forward-auth companion); passkeys = Adopt (WebAuthn L3 Recommendation 2026-08-25; Windows still device-bound); forward-auth only with Traefik ≥3.7.6 after two CVSS-10 header bypasses in 2026; pairwise OpenID-Federation-shaped trust (signed entity statements, pinned `iss/aud/alg/typ`, JWKS inside the tunnel) | the already-written Go `forward-auth` as the per-office IdP step, passkeys first, pairwise signed trust over the link (the door's HMAC becomes a JWS with a nonce), strip every `X-Forwarded-*`/`Remote-*` at the edge | a central vendor IdP; SPIRE for two offices; header identity trusted inside the office network |
| **API + CLI** | Cobra (or urfave v3) with a `--json`/`--plain` contract and an explicit `apiVersion`, NO_COLOR/TTY, gh-style exit codes; the daemon as ConnectRPC (plain JSON POST the browser can call, gRPC too) over a peer-credential Unix socket / named pipe with Docker-style version negotiation; `go:embed` for the console; kardianos/service for install | exactly this shape for `dgo`; the 20 compiler verbs and the 20 control-plane routes are the frozen contract (core-native-plan §6) | "format may change" JSON; gRPC-only APIs the console cannot call; unauthenticated TCP control ports; `docker exec … python3` as an API |
| **UI** | iframes behind ONE origin as the app boundary with `frame-ancestors`, `sandbox` without `allow-same-origin`, exact-origin postMessage; Module Federation only for first-party tiles; design tokens as DTCG 2025.10 `.tokens.json` compiled by Style Dictionary v5; WCAG 2.2 AA (24×24 targets) is the EN 301 549 baseline; RTL via logical properties; PWA by manifest, never `beforeinstallprompt` | keep the same-origin frame model (it is right), make the shell's server part of `dgo`, publish Olive Grove as a DTCG token file that COMPILES theme-tokens.css (G27/G82 unchanged, one source), APG dialog + Window Splitter semantics, 24×24 everywhere (G81 asks it) | a second UI (the simulation as "specification"); per-app servers that each proxy; UA-sniffing for phone layouts |
| **OS / services / any-OS base** | one binary = CLI + `Type=notify` daemon (sd_notify, `WatchdogSec`, `StateDirectory`, `systemd-analyze security` gate) + launchd (`bootstrap`, never `load`) + Windows service via `x/sys/windows/svc`; layer 0 runs NO container engine (k0s controllers; HA dropped Supervised 2025-05-22); the engine is a dependency of the apps: WSL2 + Docker CE 28.x as a shipped `.wsl` distro with mirrored networking and a host-side keep-alive (systemd units do not keep WSL alive), Lima/VZ on macOS, Docker CE 28 on a VPS; Docker 29 stays a hard no while Traefik 3.3 pins API 1.24 | `dgo` as supervisor + `dgo be-child console|control|vault|net` (one file, several processes, the vault in its own crash domain); engine provisioning as `dgo engine` only; a `.wsl` distro of our own | `pip`/`python3` on the host; NSSM/WinSW; a single process holding the vault; Apple `container` (track only) |
| **Omni multi-binary** | one artifact per OS/arch, roles by subcommand/argv[0], assets pre-compressed before `go:embed`, modules compiled in (no runtime plugins in the core; WASM via wazero if ever), self-update = stage + verify + rename (`.old` sweep on Windows), two embedded Ed25519 roots → online signing keys → whole-manifest signature with monotonic `version`, `expires`, `min_bootstrapper` (Tailscale distsign shape, TUF rules, minisign bytes); the stub under 5 MB only WITHOUT `net/http` (measured 3.79 MB vs 5.18); UPX never; OV Authenticode (Azure Artifact Signing excludes Israel) and a stub that rarely changes; notarized `.pkg` on macOS; `curl \| sh` + signed repo on Linux; Android = layer 0 only (Termux first, wrapper APK later; two stdlib fixes: resolver + `anet`) | all of it; the 5 MB target is met by dropping `net/http` from the stub | TUF/sigstore libraries inside the stub (14 MiB); GitHub API from the stub (60 req/h); GHCR/ORAS for the stub's payload |
| **Public registry at apps.net.digital-office.co.il** | a static, signed, sparse index (Cargo sparse × npm abbreviated packument × Go proxy "a file server is a proxy") on R2+CDN with zero compute on the install path: `/v1/config.json`, `/v1/p/<name>.json`, `all-<os>-<arch>.json.zst`, TUF metadata; packages as OCI artifacts on GHCR referenced by digest; `package.yaml` fields from Helm/HA/winget/Flathub; MVS + `dgo.lock`; blueprints = packages with only `requires`; cosign attestations CI-side only; DNS split `apps./dl./img./id./relay./log.` | this exact layout — built on the Python `catalog.py` (F-Droid index-v2, Ed25519 detached signature) and `appinstall.py` that already exist, ported into `dgo install` | a custom registry server; Compose-as-OCI (refuses bind mounts, which every DGO app has); apt; a resolver beyond caret + MVS + lockfile |
| **State and data layer** | SQLite WAL (≥3.51.3, one writer process, cgo-free driver) as the single-node system of record with Litestream v0.5 replication verified by `restore -f`; one `postgres:18` per layer-3 app with in-place `pg_upgrade --link`; `pg_dump -Fc` into restic with rotating `--read-data-subset` and a scripted restore test; a JetStream R1 stream per office with leaf-node mirrors over WireGuard as the audit/sync log; age+sops for files, OS keychain for the operator key; local-first CRDT engines are NOT peer-to-peer (Electric/PowerSync/Zero need one central Postgres) | the office record (`platform.state`, pairs, catalog, verdicts, link history) moves from YAML-by-regex and JSON files into one SQLite file owned by `dgo`, replicated by Litestream; the state YAML stays the declared INPUT; backups declared per app and verified by restore, not by tar | LiteFS, cr-sqlite, central-Postgres sync engines, Vault/OpenBao on one node, secrets in environment variables |

Three measured facts that change the plan: (1) **nothing has ever been signed or published** and the
payload is a shim that needs the repo — part 1 of the binary plan has no layer 0 to download yet;
(2) **the project's GHCR packages are private** — no clean-machine install can work until they are
public; (3) `modernc.org/sqlite` lists no `android/*` target — the Android layer-0 claim needs its SQLite
path verified before it is promised.

## 5. The recommended architecture — judged against the owner's bar

The bar, verbatim: minimal dependencies · max secure · zero duplication · minimal coupling · simplicity ·
generality · zero feature loss · minimal bytes. The verdict per piece:

### 5.1 One binary, several processes, one contract

`dgo` (Go, stdlib + a short allow-list: `x/sys` for services, `wireguard-go` for the tunnel, a cgo-free
SQLite driver, `connect-go` for the daemon API) is CLI, supervisor and every layer-0 service:

| Process (`dgo be-child …`) | Replaces today | Bytes, deps, coupling |
|---|---|---|
| `control` — compiler + control plane + reconciler + state store (SQLite) | `reconcile.py` (3,200 lines), app-management (Flask), 48 `python3` calls in bash, 6 writers of the state file | one owner of state behind one API with a lock; the 20 verbs + 20 routes unchanged (zero feature loss); Python leaves the host (minus one dependency) |
| `console` — the shell's static files (`embed`) + its proxies + the route contract | console (Flask), per-app Sentry blocks | the same-origin frame model kept; one process serves what nine Flask apps served |
| `vault` — the credential plane as a file the binary owns, its own process and user | connections (Python) | max secure: its own crash domain, no socket exposed to apps, secrets never in env |
| `net` — WireGuard node (netstack), link door, catalog listener, finder/healer, firewall renderer | `dgo-net` + `dgo-link` (890-line Python splice + 277-line shell sweep in 64 MB containers) and the host-level `wg-quick` for declared offices | ONE tunnel applier for paired AND declared offices — the root of three outages removed; the door keeps proving identity, now with a nonce |
| `identity` — forward-auth (already written, 28 tests) | authentik (4 containers, 1.1 GB) | −1.1 GB, −3 containers; passkeys first |
| `notify` — notifications (upsert by source_id, levels, links) | notifications (Python) | small; could stay a container, but it must exist before apps for the agent's door — so it is layer 0 |
| `engine` — provisions WSL/Lima/dockerd when a layer-3 app is enabled | `bbox.cmd`, `bbox engine`, `need_docker`, `ccr_*` | the only place that knows an OS; layer 0 never needs it |

Everything else — traefik, postgres, redis, n8n, Plane, drive, mail, INDOX, the agent — stays a
container, exactly where the owner put them. **Zero feature loss** is enforced the way the Go port
already does it: a verb or route moves only when a differential test proves it byte-identical against
the Python oracle, and `DGO_COMPILER=python` / `BBOX_CONTROL_PLANE=container` roll it back per verb.

### 5.2 Zero duplication — where the copies are and what removes them

| Duplicate today | One owner after |
|---|---|
| `.env` read in bash and Python; node lookup in two languages; YAML parsed by hand in two scripts; container naming re-derived in `lib.sh`; the 3-file compose list hardcoded in packaging | `dgo` answers; bash is a one-line shim |
| 35 palette copies, 24 `bina-ask`, 20 `bina-said`, 12 nav copies kept identical by G27 | one DTCG token file + one `bina-ui` served by `dgo console` to every first-party tile from the same origin; G27 keeps stamping only the carriers that must stay installable alone (third-party tiles) |
| the simulation as a second UI | the simulation becomes a MODE of the real shell (`?demo` with mocked apps), built from the same sources; the committed 7.7 MB artifact goes |
| AGENTS.md + CLAUDE.md both injected into every agent session (7.2k tokens) | `DGO.md` (the office) + `AZARIA.md` (the persona) — agt-014's split |
| two tunnel appliers, two record shapes, pulse + seder | one `dgo net`; one record (SQLite); the seder in n8n, no pulse anywhere |
| 80 regex lints over n8n JSON (G36–G53) | the blueprint compiler validates on write and reads back after push (DGO-584 lands the read-back tonight); a gate whose rule the compiler refuses is retired the same day |

### 5.3 Minimal coupling and max security — the five rules

1. **The engine is a dependency of apps, never of the office.** Layer 0 runs without Docker; "apps unavailable" is a state, "office down" is not.
2. **Identity is proved at every hop, never carried.** Edge strips `X-Forwarded-*`/`Remote-*`; apps bind to the proxy's address; the link door signs a JWS with nonce and expiry; agent doors accept the door's proof (no token handoff to build).
3. **One writer per fact, behind an API with a lock** — the state record, the pair record, the catalog, `.env`'s derived lines. Text surgery from six surfaces ends.
4. **No shell strings in the control plane** — argv only; the compiler never `exec`s a string built from a manifest (the Coolify/Dokploy lesson).
5. **Secrets have a home**: the vault process; files via age; never env; backups by declared store and verified by `restore`, not by tar of a live volume.

### 5.4 Minimal bytes — the budget

| Artifact | Today | Target | How |
|---|---|---|---|
| bootstrapper | 5,327,872 B (win/amd64) | ≤ 3.9 MB | drop `net/http` (hand-rolled HTTPS GET over `crypto/tls`), two embedded roots, zenity-style native dialogs |
| `dgo` core | 2.58 MB shim | 10–15 MB with the console embedded (pre-compressed), SQLite, netstack | one file replaces authentik (1.1 GB), five Python images (~1.5 GB of layers) and the host's Python |
| a fresh office | git clone (3,600 files) + python3 + PyYAML + docker + 10–15 min build | one download → `dgo` → wizard → images pulled by digest from GHCR (CI builds them, DGO-41) | the clone exists for developers only |

## 6. The plan — same contract, new body, each step alone with proof and rollback

Aligned with `core-native-plan.md` §3 and the three parts of `binary-release-plan.md` (DGO-588); budgets in
the office's currency (₪, Azaria's rounds) and in sessions of this kind (F = Fable rounds with subagents).

| # | Step | Acceptance (measured) | Rollback | Budget |
|---|---|---|---|---|
| 0 | **Unblock publication**: make the GHCR packages public; the owner mints the release key (`relsign --keygen`, offline) and the `DGO_RELEASE_KEY` secret; push-time `go test` in CI; one `v0.1.0` tag | a clean machine pulls an image anonymously; a signed manifest exists at `digital-office.co.il/dl/`; CI red on a failing Go test | delete the tag | owner ½ h + ₪1 |
| 1 | **The stub under 5 MB with the key layer**: drop `net/http`, two embedded roots → `keys.json` → whole-manifest signature, `version`/`expires`/`min_bootstrapper`, size gate in `build-binaries.sh` | all six targets ≤ 4 MiB; a replayed old manifest refused; a forged `keys.json` refused; native dialogs on the three "next" screens | previous stub | ₪5 / 2 F |
| 2 | **`dgo` = the CLI + engine** (core-native step 1): `bbox` a shim; `dgo engine doctor|start` owns WSL/Lima/dockerd; `dgo run` on the three environments | every `bbox` acceptance passes through the shim; `bbox dgo test N`, `baseline` green | delete the shim | ₪6 / 3 F |
| 3 | **Compiler native** (step 2, in flight: `validate` + `enabled-apps` done): `compose-files`, the emitter (byte-identical `.generated/`), `set-state` behind a lock, plan/apply/generations; status conditions + `--refresh-only` drift | `go test` renders the repo's catalog with both and diffs; 60 gates unchanged; `DGO_COMPILER=python` flips any verb | per verb | ₪10 / 5 F |
| 4 | **Control plane + state store** (step 3): `dgo serve` answers app-management's 20 routes (G85) over ConnectRPC on a Unix socket + the console's same-origin door; the office record moves into SQLite with Litestream; the YAML stays the declared input | apps screen + wizard against `dgo serve`; G85 green; a linked office's 403s unchanged; `restore -f` proves the replica | `BBOX_CONTROL_PLANE=container` | ₪8 / 4 F |
| 5 | **Console in `dgo`** (step 4) + the simulation as a mode; DTCG tokens compile theme-tokens.css | ui-map + sim flows pass against `dgo console`; G27/G82 green; the 7.7 MB artifact deleted | container stays buildable | ₪6 / 3 F |
| 6 | **Vault in `dgo`** (step 5) + TOTP (DGO-572 lands the kind tonight) | connections screen works; G8 green; secrets never in env | container stays buildable | ₪6 / 3 F |
| 7 | **Identity cutover** (step 6): forward-auth wired, authentik retired, passkeys | the F1–F3 window's own sweep; no second sign-in anywhere | one file | ₪3 / 1 F + owner's window |
| 8 | **`dgo net`**: one tunnel applier, the door with JWS+nonce, agent doors accept the door's proof, finder/healer, firewall; the host-level `wg-quick` retired on vps1 | the 13 death modes each with detector+fix+recovery time (DGO-555's table) measured on the live pair; `bbox dgo test pair` green; DGO-581/589/590/591 closed by construction | containers stay buildable | ₪12 / 6 F |
| 9 | **The store** (part 3): `dgo install` from the static signed index at apps.net.digital-office.co.il, built on `catalog.py`/`appinstall.py`; `package.yaml`; MVS + `dgo.lock`; six layer-1 blueprints; `dgo bundle`/`mirror` | `dgo install bina-ds@x.y` on a clean machine from the download alone; the wizard offers the six blueprints; an air-gapped install from a bundle | the Python verbs stay | ₪15 / 7 F |
| 10 | **Layer 0 as the payload** (part 1.5 + step 7): the manifest names `dgo` per OS; download → wizard → office with no git clone; services installed (systemd notify / launchd / Windows service) | a fresh Windows, macOS and Linux machine reaches the wizard from the download alone; Android (Termux) reaches the console | previous manifest | ₪6 / 3 F + owner's three machines |
| 11 | **Retire the lint that the types replaced**; `DGO.md`/`AZARIA.md`; the agent's budget gate in the door | gate count falls with each retired rule; entry context ≤ 8k tokens; a night under budget | — | ₪4 / 2 F |

**Total:** ≈ ₪80 of office rounds + ≈ 40 Fable rounds, in the order above; steps 0–1 this week, 2–4 the
backbone, 5–7 remove the heavy containers, 8–10 make the product a download, 11 is the dividend.
Nothing is removed before its replacement has run the office for a day (core-native-plan's rule).

## 7. What only the owner can decide (recorded, not waited on)

| # | Decision | Default taken if silent |
|---|---|---|
| D1 | The release key: `relsign --keygen` on his machine, the public halves into the stub, the private half offline + as the CI secret | step 1 ships with a TEMPORARY key pair that step 0 replaces before any public release |
| D2 | Make the GHCR packages public (or choose R2 for packages too) | packages stay private → no clean-machine install; the plan stops at step 9's acceptance |
| D3 | Windows code signing: an OV certificate (~$150–300/yr + token) or accept SmartScreen warnings for the first weeks | unsigned stub; reputation builds per hash — the stub must then never change |
| D4 | macOS: the $99/yr developer program for a notarized `.pkg`, or `curl \| sh` only | `curl \| sh` only on macOS |
| D5 | Does layer 0 require Docker? | No — layer 0 runs as processes; the engine is provisioned when the first layer-3 app is enabled |
| D6 | Android: promise "pocket console" (layer 0 only) or nothing | pocket console via Termux, after the two stdlib fixes |
| D7 | The merge of `vps1-dgo` (47 commits) into `hp-dgo` and the office-per-branch model | cherry-pick by path what items need; the full merge waits for a quiet tree or his word |
| D8 | Daily budget for the office's autonomous work (Azaria asked ₪30/day; the cycle runs at ₪5/day) | ₪5/day until he says otherwise |

**Sources and maps.** The decision maps (`ai/context/research/archmap-*.md`), the packaging audit
(`packaging-state.md`) and the five briefs (`architecture-2026.md`, `bootstrapper-signing-size.md`,
`omni-binary-and-registry.md`, `package-registry.md`, `android-path.md`) are committed beside this
document; every `file:line` in §2 is in the maps, every dated URL in the briefs.
