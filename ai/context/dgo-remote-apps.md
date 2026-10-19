# Remote apps — the DGO extension as one layer-0 feature

**Owner, 2026-10-01 16:20:** "apps just run where they run; once you have dgo extend, their apps just appear in
app manager and are completely usable in console, CLI and API for Azaria agents — local and remote; an app
installed in both offices appears twice, once with the remote mark. Very efficient, well structured, minimal,
robust, fast — at layer 0, fully integrated into app manager, console, CLI." **First use (top priority): the
MacBook's Azaria (bina-ds) used from vps1's office.**

This replaces "placement" as the everyday model. Moving an app (`move.py`, phase 4) stays a separate, explicit act.

## The model

- A **link** (exists: identity, `dgo-net`/WireGuard 10.79.x, `firewall.py`, the `dgo-link` proxy and its door)
  joins two offices. Each side of a link is a **peer office** with a short name (`macbook`, `vps1`, `portable`).
- A **remote app** is `(office, alias)` — an app that is enabled on a linked office. It is never copied,
  installed or disabled here. It runs where it runs.
- Every enabled app of a linked office appears here unless that office's declaration excludes it
  (`serve.exclude: [alias…]`; default: nothing excluded — the owner owns both ends).

## One data path (serving side → consuming side)

> **Implemented 2026-10-01 (lane remote-core):** `apps/dgo-extend/catalog.py` (the shape and its
> refusals), `apps/dgo-extend/projection.py` (the pull and the state block), `platform/manager/serve.py`
> (routes, aliases, identity hosts), `platform/manager/reconcile.py` (the registry artifacts).
> Fixture: `apps/dgo-extend/tests/fixtures/{registry/office.apps.json,catalog.macbook.json}` — the
> second is reproduced byte-for-byte by `catalog.build()` in the phase-3 gate, so it is a spec that is
> measured rather than a spec that drifts.

1. **Catalog (serving side).** `dgo-extend` answers `GET /api/link/catalog` on the link proxy (tunnel address
   only, never on the edge):
   ```json
   {"office": "macbook", "label": {"he": "המק", "en": "MacBook"}, "commit": "<sha>",
    "generated_at": 1759330000,
    "apps": [{"alias": "bina", "app": "bina-ds",
              "title": {"he": "בינה ודעת", "en": "Bina"}, "icon": "bot", "group": "ראשי",
              "desc": "הסוכן של הלשכה", "order": 1,
              "port": 3080, "api": {"port": 3081, "auth": "bearer:vault:bina-ds"},
              "module": {"kind": "embedded", "path": "/a/bina/"}, "health": "/healthz",
              "host": "bina.localhost", "identity": {"to": "akadmin"}}]}
   ```
   Built from the office's OWN compiled registry — `.generated/registry/office.apps.json`, rendered by
   layer 0 from every enabled app's `routing[]`/`capabilities[]` — one source, no second list. Two fields
   the first draft of this contract did not carry, both measured into it:
   * `host` — the authority the serving app expects to be reached under (`sso.default_host`). The link
     proxy is TCP and cannot rewrite `Host` (see §3), so the consuming office's edge writes it (a headers
     middleware) and the value has to come from the office that knows it.
   * `identity` — the user a request should BECOME on the serving side; only that office knows its own
     vocabulary.
   And one field of the answer itself, for the office that asks (2026-10-09): `dials` — `host:port`,
   the address the answering office's tunnel reaches the asker at. It is there only when the answering
   office is the end that DIALS that pair and its handshake is alive. A listening office cannot measure
   its own address from a container; the office that has just got through to it can, and
   `pair_api.listen_now` corrects what the listener shows and offers by it (hp-laptop declared a lease
   it no longer held for eleven hours on 2026-10-08). Additive: an older office ignores it.
   The door is `catalog.py`'s: a caller that is not the link proxy's own address on the office network gets
   **403** (`_from_link`), so the catalog is never readable from the edge — measured live 2026-10-01
   (`/api/link/catalog` → 200 from the proxy's address, 403 from another container).
   **The catalog is part of the LINK, not of a `serve:` list** (`catalog.with_control`): a peer has to be
   able to read it *before* it knows which apps exist over there, so the serving office's firewall and
   delivery plan always open this app's own port (8983) to a peer that may arrive, and the consuming
   office always renders the listener that reaches it (`linkproxy.build`, `use` half).
2. **Projection (consuming side).** `dgo-extend` pulls each linked peer's catalog (on `link up`, every 60 s,
   and on demand), and writes the `remote:` block of `platform.state.yaml` — the generalisation of today's
   `serve:` block (keep reading `serve:` as an alias of it for one release). Layer 0 never reaches into
   dgo-extend's volume; it reads only `platform.state.yaml`. The block carries, per office:
   `office, label{he,en}, link, address (the peer's end of the pair — DERIVED, never published by the peer),
   commit, fetched, apps[]` where each app is the catalog entry in the compiler's own vocabulary
   (`app, alias, port, agent_api_port, name, name_en, icon, group, desc, order, module, health, host,
   identity`). Written by TEXT SURGERY through `computers` (`projection.REMOTE_WRITER`) so the file's
   comments survive, and only when the block actually changed.
   **Two exclusions, two different acts** (this is remote-ui's show/hide switch):
   * the peer's `serve.exclude` — apps it never publishes at all (applied in `catalog.build`, on the
     serving side);
   * this office's `POST /api/link/exclude {office, alias, hidden}` — "not on MY rail" (`/data/exclude.json`
     here). The app stays in the stored catalog and is reported `hidden: true` by `GET /api/link`; what
     disappears is the tile, the router and the alias. Hiding from one office must not take the app away
     from every other office linked to the same peer, which is why it is not written on the peer.
3. **Compile (layer 0, `platform/manager/serve.py` generalised).** For every remote app the compiler emits:
   - **edge route** (traefik FILE provider — labels cannot point outside the engine, measured 2026-09-30):
     `<alias>.<office>.console.<domain>` plus the `.localhost:<port>` twin → the link proxy → peer tunnel
     address:port, under THIS office's SSO (one authentik provider per host), the identity a request arrives
     with written by the door (`link-proxy.py`, `Door.rewrite`). **Measured 2026-10-01 17:50 (coordinator): two-label nesting works on vps1** — the DNS
     wildcard answers at any depth (`bina.macbook.console.staging.digital-office.co.il` → 31.97.196.82), and
     vps1's traefik issues Let's Encrypt certificates per exact host (CN = the host), so the file-provider
     router only needs `tls.certresolver: myresolver` and gets its own certificate on first request.
     **The link proxy is TCP** (`link-proxy.py` pumps sockets): websockets pass untouched, but it cannot
     rewrite `Host` — the serving app sees the consuming office's host, so a DSH-based app (bina-ds) must list
     that host in `DSH_TRUSTED_HOSTS` (one `self-update.sh` of bina-ds per new consuming host).
   - **network alias** on the link proxy: `<alias>.<office>` → the same peer address:port, so CLI, hooks and
     agents inside the engine call `http://bina.macbook:3081/…` like any local service.
     **The alias, and not the tunnel address, is what the router points at** — this is a correction of the
     first draft, and it is the difference between a tile that opens and a tile that 502s: `10.79.x.2`
     exists only inside the tunnel container's namespace, and the edge lives on `traefik-network` with no
     route to it. So `serve.render()` writes `http://<alias>.<office>:<port>` as the backend and
     `serve.render_aliases()` writes the compose overlay that puts the alias on the container whose
     namespace the link proxy shares (`dgo-net`, `network_mode: service:dgo-net`) —
     `.generated/remote.override.yml`, included by `compose_files()` and applied by `dc up -d`. The
     listener the name resolves to is the delivery plan's `use` rule, which binds that port in that
     namespace and forwards to the peer's tunnel address.
   - **registry entry** `.generated/registry/remote.<office>.<alias>.json`: the app's own entry plus
     `"remote": {"office": "macbook", "label": {…}, "link": "<link-id>", "address", "commit"}` and module
     `external` with `host = <alias>.<office>`. The console's `peers.d` merge stays for placements; remote
     entries come through the registry.
   Same alias local AND remote → two entries, two tiles (the remote one marked). The tile id is
   `<alias>.<office>` — never the bare alias — so a local `bina` keeps its own tile and both are listed;
   `serve.module_entries()` no longer suppresses a remote tile because a local app owns the alias.
   **Identity layer:** one authentik proxy provider per remote host is emitted by `render_authentik` from
   `serve.sso_hosts()` — the nested host on a real domain, and on `.localhost` both forms the browser's own
   origin can derive (port-less for the office browser, `:<console port>` for a browser on the host). A
   router without it answers 404 at the outpost while the edge looks healthy.
4. **Console.** Desktop bar, rail and launcher render any entry with `remote` with the class `is-remote`:
   a corner outline in the logo's **apps line** colour — `--io-apps: #7ecfad` (`.logo .a` in
   `platform-base/console/static/style.css`) — and the tooltip `<title> · <office label>`. A remote office
   that does not answer → the tile says so in Hebrew (`<office> לא זמינה כרגע`), never a blank frame.
5. **App manager** (`platform-base/app-management`). The apps list shows remote apps in the same list with the
   same mark and an office column/filter; a **"לשכות מחוברות"** section lists linked offices (from
   dgo-extend), per office: its apps, an on/off per app (writes `serve.exclude` through dgo-extend), and
   **"חיבור לשכה"** → dgo-extend's connect screens (`static/connect.*`: computers / QR / paste).
6. **CLI** (`bbox`). `bbox apps list` prints remote apps with an office column; `bbox agent --office <office> …`
   (DGO-32) resolves the provider through the link (`http://bina.<office>:3081`, Bearer from the vault
   instance the catalog names); `bbox remote <office> <alias> <path>` is a plain authenticated GET/POST
   through the link proxy for anything else.
7. **API for Azaria.** Inside the engine every remote app is `http://<alias>.<office>:<port>` (step 3's
   alias). The office-operations skill documents it: local `http://bina:3081`, remote `http://bina.macbook:3081`.

## Security (unchanged rules, one place each)

Direction enforced on the RECEIVING side (`firewall.py` opens only catalogued ports, peer → us only);
identity headers are never taken from a peer — the door removes every one and writes the catalog's
mapped user (`link-proxy.py`); SSO of the office you are in protects every
remote host; tokens live in the vault (`dgo_link-<office>`), never in a catalog or a URL.

## Acceptance (the owner's first use, then the general case)

1. On vps1, `console.staging.digital-office.co.il`: a "בינה ודעת · MacBook" tile with the corner mark opens the
   MacBook's Azaria; a chat round-trips (websocket through the frame); MacBook asleep → Hebrew message.
2. On vps1: `bbox agent --office macbook list` shows the Mac's sessions; an Azaria session ON vps1 calls
   `http://bina.macbook:3081/v1/sessions` with the vault Bearer → 200.
3. On the Mac: vps1's apps appear marked; an app enabled in both (e.g. `n8n`) appears twice; the remote one opens vps1's.
4. `bbox dgo test 3` (phase-3 gate) green, extended with the catalog → projection → registry → route chain.

## Lanes (2026-10-01 16:30) and who owns which file

| Lane | Owns | Items |
|---|---|---|
| **remote-core** | `platform/manager/serve.py`, `platform/manager/reconcile.py`, `apps/dgo-extend/{catalog.py,app.py routes for /api/link/*}`, link-proxy aliases | catalog → projection → compile (routes, aliases, registry, providers) |
| **remote-ui** | `platform-base/app-management`, `platform-base/console/static/*` | remote mark, app-manager list + "לשכות מחוברות" |
| **remote-control** | `apps/dgo-extend/converge.py`, `scripts/bbox_agent`, bina-ds trusted hosts / self-update | DGO-32, acceptance 1–2 on vps1 (converge vps1 at head) |
| **portable** | the portable machine | DGO-35: the home laptop becomes an office linked to the Mac; heavy apps run THERE and appear here as remote apps |

Contract first: remote-core publishes the registry/catalog shape above (with a fixture under
`apps/dgo-extend/tests/fixtures/`) before remote-ui renders it; a change to the shape is a commit to this file.

## What remote-ui reads — the consuming half, spelled out (added 2026-10-01, remote-ui lane)

> **Delivered by remote-core, 2026-10-01:** all three items below exist.
> `POST /api/link/exclude {office, alias, hidden}` (writes this office's `/data/exclude.json`, then
> re-projects at once and answers the new state); `GET /api/link` items now carry
> `label`, `state` (`up`/`down`/`unknown` from `/data/remote-status.json`, i.e. the LAST pull, not a
> guess), `state_at`, `state_error`, `commit`, and `apps: [{alias, app, title, icon, port, api, hidden,
> ok}]` — **including the hidden ones**. The registry entry carries `id = <alias>.<office>`, `label`,
> `remote.office/link/address/commit/port/api_port` and `module.kind = external` with
> `module.host = <alias>.<office>`. `remote.ok`/`state` is NOT emitted in the registry: it would be a
> fact of the moment frozen into compiled output, and the shell already decides it from a frame that
> never rendered.

The console renders a remote app from the **module entry** the compiler emits; the app manager renders the
**same entries** (through the console's own `/api/modules` — one list, so the screen and the rail cannot
disagree) plus the link plane from dgo-extend. What remote-ui needs from remote-core, exactly:

1. **The registry entry** needs, besides the fields step 3 lists: a **unique `id`** — that IS the
   two-tiles requirement (see below) — the office's `label` (a string or `{he,en}`; the tooltip is
   `<title> · <label>` and the phone tile prints it under the name, so the short `office` id is never
   what a person reads), and, optionally, `remote.ok: false` (or `state: "down"`) so a tile says
   `<label> לא זמינה כרגע` **before** anything is opened. The shell also decides this for itself, from a
   remote frame that never rendered — the field is an improvement, not a requirement.
   **Same alias local and remote → two ids** (`<alias>.<office>` when the local app owns the alias):
   the shell addresses a tile by id (`#/m/<id>`), so two entries sharing one id are one unreachable tile.
   The console keeps the first and warns rather than drawing two identical rows.
2. **`GET /api/link`** (dgo-extend), per item: `label` (the office's own name), `state`
   (`up` / `down` / absent), and `apps: [{alias, title, icon, port, hidden, ok}]` — **including the hidden
   ones**, which the registry by construction cannot show (a hidden app has no tile).
3. **`POST /api/link/exclude {office, alias, hidden}`** — the app manager's show/hide switch:
   `hidden: true` = this console no longer shows that office's app (the app keeps running there;
   `serve.exclude` is remote-core's key to name). Until the route exists the switch is drawn, refuses the
   change on 404/501 and **reverts the box**: an exclusion that silently does nothing is worse than one
   that is not offered yet.
4. **The connect button** opens dgo-extend's own screens in a tab — `/a/dgo-extend/connect`
   (`static/connect.*`, the computers / QR / paste flow).

The three cases remote-ui's screenshots assert are the same three: a marked tile, **two** tiles for one
alias, and an office that does not answer.

## remote-core: what is verified, and what is not (2026-10-01, lane remote-core)

**Verified by running it:**
* `catalog.py`, `projection.py`, `serve.py`, `linkproxy.py`, `firewall.py`, `net.py` — each
  module's selftest passes, and the phase-3 gate (`bbox dgo test 3`) passes the six checks that can be
  decided without a live link: the plane's refusals, the nested host + alias backend + SSO + identity
  mapping, the office-namespaced tile (and the two-tiles rule), the fixture reproducing byte-for-byte,
  the full chain `catalog → projection → registry → route` on the fixture, and the per-app registry
  record (including that a stale one is removed with the entry that produced it).
* Live, on this office's own dgo-extend: `GET /api/link/catalog` answers the real catalog (10 apps,
  aliases/ports from the compiled registry) **from the link proxy's address**, and answers **403** to a
  caller on the office network — the catalog is not readable from the edge.
* The delivery plan: after `dc up --build dgo-extend dgo-link`, the proxy logs three listeners
  (`10.79.2.1:3080`, `:3081`, `:8983` → `bina-ds`/`dgo-extend`) and `bbox reconcile` renders
  `office.apps.json` with the agent's second door (`bina-ds: 3080` + `api 3081`) and its authority.

**Verified by reading a real failure (found by running it, fixed):**
* `linkproxy.write()` did not forward the new keyword → `/api/link/serve` raised `TypeError` on the live
  app. Fixed (`write(..., control_bind=)`), rebuilt, and the route answers again.
* A local curl to `10.79.2.1:8983` from the tunnel's own namespace is DROPPED — by design: the input
  chain accepts only the peer's address. The control door is therefore proved from the proxy's address,
  not from the tunnel address.

**Not verified (blocked, and named rather than implied):**
* The cross-office hop (vps1 pulls this Mac's catalog, renders the tile, and the frame opens עזריה):
  it needs vps1 converged at a commit that contains this lane — remote-control's converge (DGO-32).
  The mechanisms it depends on (the firewall accept, the proxy's delivery, the two-label DNS + per-host
  certificate) are measured separately and recorded above.
* vps1's own rendering of the nested host and the alias overlay on a machine that consumes: nothing
  on THIS office consumes anything today (this office is the serving side of the only live link), so
  `remote.override.yml` and the `use` half are exercised by the gate and by the fixture, not live.

### The runbook was RUN, and the lane is committed (2026-10-01 19:0x)

The session's shell came back (`/dev/null` had been deleted inside `bina-ds`; the coordinator restored
it). Everything below was executed in this order, from the repo root:

| step | result |
|---|---|
| `catalog.py`, `projection.py`, `linkproxy.py`, `serve.py` selftests | **PASS** (4/4) |
| `reconcile.py validate` + `render` | 39 manifests valid; `office.apps.json` rendered with `bina-ds`'s second door (`api 3081`) and its authority |
| `bbox dgo test 3` | **14 PASS**, 2 FAIL — and both failures are the live-link checks that say so themselves (`DGO-18/30`, `DGO-18/32`) |
| `./scripts/dc up -d --build dgo-extend dgo-link` | rebuilt and recreated; the tunnel came back (wg0 present, `addressing.peers` = vps1 `10.79.2.2`) |
| `GET /api/link` | the enriched shape is live: per office `label`, `state`, `commit`, and `apps[]` (empty for vps1 — this office consumes nothing, so `state` is honestly `unknown`) |
| `GET /api/link/catalog` from the proxy's address | **200**, the real catalog (10 apps) |
| `GET /api/link/catalog` from anywhere else | **403** with the Hebrew sentence and the caller's address |
| `POST /api/link/exclude` hide → file → refusal → unhide | `{"vps1":["bina"]}` written to `/data/exclude.json`; `office: "VPS 1"` → **400**; unhide → `{}` |

Two commits, and this is the head the vps1 converge should name:

* `06a71ada` — **DGO-37**: the catalog a linked office pulls, and the projection that writes it back
  (`apps/dgo-extend/{catalog.py,projection.py,app.py,linkproxy.py,docker-compose.yml,tests/}`).
* `e65ca9eb` — **DGO-37**: compile the remote plane — routes on the nested host, the link proxy's
  alias, the registry (`platform/manager/{serve.py,reconcile.py}`).

`DGO-37` is the lane's own numbering of this chain (the contract's lane table names the items, not the
numbers); the coordinator syncs it to Plane. `catalog.py` and `projection.py` had already been carried
into `d81fb93b` (remote-control's DGO-32 commit) while this session's shell was down; the two commits
above are the rest of it.

### What is left for remote-control, exactly

1. **Converge vps1 at `e65ca9eb`** (or a later head that contains it) — both sides on one commit — so
   vps1's `dgo-extend` runs this code. Its `bbox run` rebuilds the app from the checkout.
2. Then, on vps1, the chain should appear by itself within one projection pass (60 s): its
   `GET /api/link` lists this office with its apps, and `platform.state.yaml` gains a `remote:` block
   naming `local` with `bina`, `n8n`, … .
3. The proof to bring back: `bbox dgo test 3` green on vps1 (the two live checks flip to PASS), and
   `curl -s http://bina.macbook:3080/` (or the console tile) answering from inside vps1's engine.
4. If anything in steps 2–3 fails, the sentence to capture is the one from `/api/link`'s `state_error`
   or the delivery plan's `refused` — both name the field.

## remote-control: prepared, and why it is not running (2026-10-01, lane remote-control)

Same failure as remote-core's: **this session's shell is dead** (`Error: spawn bash ENOENT` on every
command, including a fresh subagent's) — no docker, no git, no curl. Everything below was written with
file tools only and is **uncommitted and unrun**; the coordinator holds the push.

* `scripts/bbox_agent/{client.py,cli.py}` — **`bbox agent --office <office>`** (acceptance 2).
  Discovery reads `remote:` and the legacy `serve:` (one meaning; `projection.py` owns the writer),
  takes the peer's tunnel address from the block plus the app's second door (`agent_api_port`, or
  `api.port`, or the manifest's `office-agent` capability) → `http://<address>:<port>`. The vault
  instance is tried in order — what the catalog names, `dgo_link-serve-<office>-<app>-agent` (what
  `converge._handoff_agents` writes), `dgo_link-<office>` (what this contract names) — and a miss lists
  every name it tried. A remote office's URL/token are cached under `<repo>::<office>`, never under the
  local agent's key, and a declared address always beats a cache.
* `apps/dgo-extend/converge.py` — `SERVE_WRITER` **steps aside when a non-empty `remote:` is present**,
  so the legacy writer cannot fight the projection for one meaning.
* `apps/bina-ds/{docker-compose.yml,.env,.env.ex}` — `DSH_TRUSTED_HOSTS` gains a declared
  `${BINA_DS_TRUSTED_HOSTS:-}` term and this office names the nested host vps1 frames it under. It
  needs one `self-update.sh` to land; **the acceptance does not depend on it** — the route already
  sends the app the authority it answers under (`serve.render`'s `host`, measured 200).
* `office-operations` skill (image side) — documents the linked office, its credential, and
  `http://bina.macbook:3081` inside the engine.

Steps left for whoever holds a shell, in order: rebuild `dgo-extend` from a **consistent committed
revision** (a build from a half-written tree already produced an image whose `app.py` called
`linkproxy.write(control_bind=…)` before that file had it → `/api/link/serve` 500), converge vps1 at
the new head (both sides on one commit, DGO-40), prove the tile + `bbox agent --office macbook list`,
then `bbox dgo test 3`. Full detail: `ai/context/dgo-extend-azaria-runbook.md`.

**remote-core is done and committed — the converge has something to point at (2026-10-01 19:1x):**
`06a71ada` (the catalog + projection), `e65ca9eb` (the compiler half), `ca485c1c` (this record).
Converge vps1 at **`e65ca9eb` or later** and the chain should land by itself within one projection pass
(60 s): vps1's `GET /api/link` lists this office with its apps, `platform.state.yaml` gains a `remote:`
block naming `local`, and its `serve.render`/`render_aliases` emit the nested host + the link proxy's
alias. Everything that could be proved without vps1 has been (see the table above): the catalog serves
200 to the link proxy and 403 to everyone else, the gate is 14 PASS with only the two live-link checks
failing by design, and the exclude switch round-trips live.



### remote-control: the one fact that stops acceptance 1–2, measured live (2026-10-01 19:2x)

**The pair's sides are the opposite way round from what both consuming-side assumptions expect.**
Measured on the live link: this office (MacBook) is **`10.79.2.1`** — it dialed, so it owns the pair's
`.1` (`net.py`: the end that renders the pair is side 1) — and vps1 is `10.79.2.2`
(`ip route get 10.79.2.1` on vps1 → `dev wg0 src 10.79.2.2`; `curl http://10.79.2.1:3080` from vps1 →
200). Two hardcoded assumptions then disagree with reality, on the consuming side:

* `projection.py:79` — `address = f"10.79.{slot}.2"`: on vps1 that is **vps1 itself**, so the catalog
  pull (`GET http://10.79.<slot>.2:8983/api/link/catalog`) would call vps1's own dgo-extend, not this
  office. No `remote:` block can ever appear.
* `serve.py:169` — refuses any peer address ending in `.1` ("x.1 היא הכתובת של הלשכה הזו בצמד"), so even
  a hand-written block naming the real peer is refused: `serve.plan` → `serve[0] (local).address
  10.79.2.1: x.0/x.255 … x.1 היא הכתובת של הלשכה הזו בצמד`. And `reconcile render` **exits** on that
  error, so vps1's `bbox run` would fail with an invalid block in its state file — which is why vps1 is
  NOT converged yet, deliberately, rather than converged into a broken state.

Either fix unblocks the chain; both are one fact about the pair:

1. **remote-core's files, preferred** — derive the peer's address from the pair instead of a constant:
   the consuming office knows its OWN address (`addressing.json` in the `dgo_tunnel` volume, `self`);
   the peer is the other end of that /24. `serve.plan`'s refusal then becomes "not this office's own
   address" instead of "not `.1`", which is also true for pairs where the consumer owns `.1`.
2. **remote-control's files, if the coordinator prefers it** — flip the pair in `step_link` (home =
   side 2, peer = side 1): this office becomes `10.79.2.2` and vps1 `10.79.2.1`, which makes BOTH
   hardcoded assumptions true (the consumer owns `.1`, the peer is `.2`) without touching remote-core's
   code. It re-addresses a live, working tunnel — one converge, and the link proxy/firewall are all
   derived from the same `addressing`, but it is a change to a working link and not mine to choose.

Everything else on this lane is done and measured: the writer bug is fixed (`ed6eb1cb`), the CLI is
committed (`d81fb93b`), and the transport is proven from vps1 — `3080 → 200` with
`Host: bina.localhost` + `X-authentik-username: akadmin`, `3081 → 401` without a token (the adapter
answers 200 with one), `8983 → 200`, three listeners on `10.79.2.1`, firewall accepting only `10.79.2.2`.

## remote-cli: §6 and §7 are implemented, and what they still cannot prove (2026-10-01, lane remote-cli)

**Delivered:** `bbox apps list` and `bbox remote [<office> [<alias> [<path>]]]`, plus the Azaria skill
section that tells an agent how to reach the same apps from inside the engine.

* **One list, an office per row.** `reconcile.py plan` (i.e. `bbox apps list`) prints every app this
  office SHOWS: its own enabled apps from the compiled registry row (`_office_apps`) and every linked
  office's app from `remote_records` — the same builder the `remote.<office>.<alias>.json` registry
  files are written from, so the CLI, the app manager and the routes cannot disagree. A local `bina`
  and a remote `bina.macbook` are **two rows** with two ids, which is the owner's own rule and not a
  duplicate; `--json` carries `apps[]` (each row with `office` and `remote`), `remote[]` per linked
  office, and the plan it wrote.
* **`bbox remote`** — no argument: the linked offices and the apps they publish, read from the link
  plane's `GET /api/link` (state `up`/`down`/`unknown`, `hidden`, commits). `<office> <alias> <path>`:
  one request through **`http://<alias>.<office>:<port><path>`** — the link proxy's network alias,
  built from the port the SERVING office published, never the tunnel address. `-X`/`-d`/`-H`, `--api`
  for the app's second door, `--json`.
* **The token is never an argument and never in a URL.** The NAME comes from the catalog's `api.auth`
  (`bearer:vault:<instance>`), then the converge conventions (`dgo_link-serve-<office>-<app>-agent`,
  `dgo_link-<office>`); the value is read from the vault on the far side of the reach decision, and a
  miss names every instance it tried.
* **Reach is decided, not assumed.** `<alias>.<office>` is a **docker network alias**, so it resolves
  only for a process attached to the office network. When the CLI is not (on the office's own machine),
  it re-runs itself inside a container that is — the source and args travel as one base64 payload,
  because the Mac path re-parses the command line twice (Lima's shell, then sudo) and anything quoted
  is a coin toss.
* **Measured here:** `./bbox dgo test 3` is green on the three new checks — the apps-list twin rule
  through `reconcile.main()` against the real state + the fixture `remote:` block, `resolve()`'s URL for
  both doors plus the refusal of a host in a path, and `bbox remote --json` against the LIVE link plane
  (`home local · vps1=unknown(0 apps)`). The delegated path was exercised for real: a call issued from a
  borrowable container on the office network returned `HTTP 200` from a live service, and the vault
  reader returned a real token by name.

**What this lane cannot prove on the Mac:** the alias itself. No `remote:` block is projected HERE (this
office is the SERVING side of the only link, and the consuming side is blocked by the `.1`/`.2` fact
above), so no `<alias>.<office>` alias exists on this machine to call. That check belongs to vps1's
converge, and it is the same one remote-control's list already carries.

**The alias MECHANISM, measured (2026-10-01, lane remote-cli).** A throwaway container on
`traefik-network` with `--network-alias bina.vps1` — a real dotted `<alias>.<office>` name, not a
stand-in — was reached by BOTH paths this CLI takes:

* from inside the network (what an agent in a container does): `HTTP 200 GET http://bina.vps1:3080/healthz`;
* from a process that is NOT on the network (what a run on the office's own machine does — `_resolves`
  reported False, so the whole command was handed to a container that is): the same `HTTP 200`, the
  same body, through the base64 payload.

The container carried no traefik labels (so no route was ever created for it) and was removed
immediately. What still waits on the consuming office is therefore narrower than "does a dotted alias
resolve and can the CLI reach it" — that is measured — and is now exactly "is one rendered there for a
given app at all", which is `projection.py` + `serve.py` and the pair-sides fix below.

**Acceptance 3 ON THE MAC needs nothing from this lane — it needs the LINK, and here is which part is
missing (measured 2026-10-01 20:0x).** Acceptance 3 is "on the Mac, vps1's apps appear marked; `bina`
local + `bina.vps1` remote = two rows/tiles", so the Mac must CONSUME vps1. Today it does not:

* the Mac's link proxy carries only `serve` rules toward vps1 (`GET /api/link/proxy`: `bina-ds:3080`,
  `:3081`, `dgo-extend:8983`, every one `direction: serve`) — there is no `use` rule, so the Mac has no
  door to vps1's apps or its catalog;
* vps1's declaration as held here is `links: [{office: local, direction: use}]`, and `mirror("use")` is
  `serve`; `projection.peers()` pulls only a peer whose apps this office CONSUMES. So vps1 is not a
  peer: `POST /api/link/remote/sync` answers `peers: []`, `pulled: []`, writes no block, and
  `platform.state.yaml` gains no `remote:` (and therefore no `remote.vps1.*.json` record);
* vps1's own `/api/link` answered **HTTP 500** when this was measured, and `10.79.2.2:8983` times out
  from this office's tunnel namespace — its catalog does not answer yet either, which is the trigger
  this lane's CLI work is waiting on.

The order that unblocks it is unchanged and is remote-control's converge, not this lane's code: vps1
converged with a declaration that SERVES its apps to `local` → the Mac's next projection pass writes
`remote:` + the registry records → `bbox reconcile render` (the routes) and a `dgo-net` recreate (the
`<alias>.vps1` network alias) → then `bbox remote`, `bbox apps list` and
`<alias>.vps1.console.localhost` (302 to SSO) are the proof, and all three commands already work.

**The route check, ready to run, with its baseline taken (same measurement, 2026-10-01 20:1x).** On
this Mac's own edge — asked through `computers` on `computer_local-local`, one `curl -H "Host: …"` per
name against `http://localhost/`:

| host | today | after the converge |
|---|---|---|
| `console.localhost` | 302 → `auth.localhost:8080/application/o/authorize/…` | unchanged (the control) |
| `bina.localhost` | 302 → the same SSO door | unchanged (the control) |
| `bina.vps1.console.localhost` | **404** — no router for it exists | **302**, the same SSO door |

The port matters and the item's `:8080` is not it: on this Mac the edge is published as `80:80`
(`docker port traefik-local`), and `:8080` is where the SSO it redirects to answers
(`auth.localhost:8080`). So the check is `http://<alias>.vps1.console.localhost/` — port-less on the
Mac — and the assertion is 404 → 302, not "a 200".





### remote-control: acceptance 2 is PROVEN on vps1 (2026-10-01 19:5x)

`./bbox agent --office macbook list` **on vps1** lists the MacBook's sessions — including the lane
running it (`DGO · שליטה מרחוק — עזריה של ה-Mac מתוך vps1 (DGO-32 …)`) and its siblings. The path it
took, each step measured:

1. `link` step (remote-control): tunnel up, ping back, delivery probe from the far machine
   `{bina-ds: 3080 open, bina-ds:agent: 3081 open, dgo-extend: 8983 open}`.
2. The Mac's agent token was handed into **vps1's vault** as
   `dgo_link-serve-local-bina-ds-agent` (`{office: local, label: MacBook, peer: vps1, app: bina-ds,
   address: 10.79.2.1, port: 3081}`).
3. From `dgo-net-staging`'s namespace — where vps1's link proxy lives — `http://10.79.2.1:3080/` → 200
   with `Host: bina.localhost` + the mapped identity, `:3081` → 200 with that token, and
   `GET /v1/sessions` → **130 sessions**.
4. `bbox agent --office macbook list` resolves the office from the credential plane and prints them.

**Three fixes were needed, all in remote-control's files** (found by running it, not by reading):
the token read must ask every container carrying the app's compose label (a self-update helper carries
the same label and no `AGENT_TOKEN_FILE`); the vault write must POST `/api/instances` without a
trailing slash (the vault's router 404s with one); and discovery needs the vault fallback for a machine
whose compiler chain has not caught up.

**What remains for the CLI to work on vps1 by itself:** the commit that carries it must be **pushed**
and vps1 converged at it (its checkout is at `281409fd`; the measured run used the two files copied in
for the test, which the `code` step will stash on the next converge).

**Acceptance 1 (the tile) is still blocked** on the pair-sides fact above: the consuming office owns
`.2` in this pair while `serve.py` assumes it owns `.1`, and `projection.py` derives the peer as `.2`
(itself, on vps1). Until one of those two is fixed, vps1's `platform.state.yaml` can carry neither a
`serve:` nor a `remote:` block, so there is no tile to open.

### BOTH acceptances are green on vps1 (2026-10-01 21:0x, lane remote-control)

vps1 was converged at `94229819` (code → state → run → link → health → publish) and measured:

* **The tile.** `https://bina.macbook.console.staging.digital-office.co.il/` answers **302** to this
  office's SSO, with a **valid certificate** (the same request without `-k` succeeds); traefik's
  rendered file carries the router, `authentik@file` + the identity mapping + the app's own `Host`,
  and `.generated/registry/remote.macbook.{bina,dgo-extend}.json` are in the console's registry. The
  `health` step reports **23/23 addresses answering**, and the SSO outpost was restarted onto the new
  gated host in the same pass (`✓ SSO: outpost now serves every gated host`).
* **The CLI.** `./bbox agent --office macbook list` **on vps1**, from its own checkout at that commit
  (no copied files), prints the MacBook's sessions — including this lane's own session.
* **The link.** `link`: tunnel up, ping back, delivery probe `{bina-ds 3080, bina-ds:agent 3081,
  dgo-extend 8983}` all open, and the credential handed into vps1's vault as
  `dgo_link-serve-macbook-bina-ds-agent` (`address 10.79.2.1`, `port 3081`).

What the measurement does **not** cover: an authenticated round-trip inside the frame (a chat message
over the websocket) — that needs a browser session on the owner's SSO. Everything under it is
measured: the route, the certificate, the SSO gate, the identity mapping, and the backend answering
200 through the tunnel from the proxy's own namespace.

The fix that made it possible (this lane, after remote-core's LANE-DONE): `serve.own_addresses()` and
`projection.read_own_address()`/`peer_side()` read which end of the pair this office holds from the
link's own record on the machine (`.dgo/addressing.json`, `.dgo/wg0.conf`), instead of assuming `.1`
and `.2`; and this office's name is declared (`DGO_OFFICE_ID=macbook`), so the host is
`bina.macbook.console…` and not `bina.local.console…`.

### Past the SSO gate: what the 302 was hiding (2026-10-01 22:30–23:35, coordinator)

The acceptance above stopped at the gate (302) and at `GET /` through the tunnel address. Behind the
gate, the tile would have failed twice. Both failures were measured on vps1 and are now fixed (`a6cb8e47`,
`b0885823`, `598d5aff`, `6893740e`). vps1 converged at `6893740e` with every step green, and 24/24
addresses answer.

1. **Nothing listened on `bina.macbook:3080`.** vps1's link proxy logged "no plan rendered yet". vps1's
   dgo-extend cannot render one: it holds no declaration of the MacBook, and its `/identity` volume is
   empty, because the converge mints the far end's keys into `.dgo/` for the host tunnel. The end that
   dials already renders and ships the far end's tunnel. It now ships the far end's delivery plan too
   (`converge._remote_delivery`):
   * the plan is rendered with `linkproxy.build(side=2, halves=("use",))`. The far end holds `.2`, and its
     tunnel is on the machine, so a `serve` rule there would bind an address its proxy lacks.
   * it is written atomically through the far office's own dgo-extend container and stamped
     `rendered_by`. `render_link_proxy()` leaves such a plan alone on an office with no declarations.
   * it is probed by name through `dgo-net`. Measured: 3080=401, 3081=401, 8983=200.
2. **Every API call of the framed page would get 403.** Bina's harness accepts `/api` only when
   `Origin == Host` (`isTrustedApiRequest`). The route rewrote Host to `bina.localhost` while the browser
   sends the nested host as Origin. A served app may now declare `host: ""` in the serving office's
   `serve:`, meaning it trusts the consumer's own name, and the far edge passes the browser's Host
   through. The serving app's own list carries that name (`BINA_DS_TRUSTED_HOSTS` in the MacBook's
   `.env`). Measured from vps1 through the tunnel:

   | Host / Origin | Answer |
   |---|---|
   | nested / nested, with identity | passes the fence and the login |
   | `bina.localhost` / nested (the old route) | 403 |
   | nested / foreign | 403 |
   | nested / nested, no identity | 401 |

   Stripping Origin at the edge would also have "worked". It was rejected because any same-site page on
   the consuming office could then drive the agent.

Two more faults surfaced on the way:
* the link proxy keyed listeners by port, so 4 rules became 3 listeners and the serve door on 8983 was
  lost. It now keys by (bind, port).
* five readers tested `serve`/`use` without `both`. Because of that, the converge wrote an EMPTY `serve:`
  block (route gone), `POST /api/link/serve` rendered a firewall with no ports, and the MacBook never
  pulled vps1's catalog.

`step_run` now exports `BBOX_WAIT_TIMEOUT=900`. vps1's recreated authentik bootstrap needs 6–8 minutes,
and the 300 s default failed `run` and skipped `link` and `health`.

**Left:** the owner's own login on `https://bina.macbook.console.staging.digital-office.co.il/` (the gate,
the page and the API are measured; only a human session is not). **Acceptance 3** (the MacBook shows
vps1's apps) needs vps1's `serve` half on its HOST, where its tunnel is: today `10.79.2.2:8983` answers
nothing, so the MacBook's pull fails and its projection honestly reports vps1 as not answering.

### Acceptance 3 (the MacBook shows vps1's apps): measured blockers and the recommended design (2026-10-02, coordinator)

The far end's tunnel is now a systemd service, with its firewall in PostUp/PreDown (`05d35c45`). A
stop/start of `wg-quick@wg0` on vps1 brings both back. The reverse direction is blocked by three facts
measured on vps1. These are design issues, not bugs to patch:

1. **vps1's dgo-extend does not know who it is.** Its `/identity` volume is empty (the keys live in
   `.dgo/identity.json` for the host tunnel) and `DGO_OFFICE_ID` is unset, so `home_office()` raises and
   `GET /api/link/catalog` cannot answer. The fix is small. The converge seeds the far office's identity
   volume from `.dgo/identity.json` (same machine, over stdin, mode 600), and its `.env` gains
   `DGO_OFFICE_ID=<declaration id>`.
2. **One port per app on the tunnel address cannot hold vps1's apps.** vps1's registry has 4 apps on
   8080, 2 on 8000 and 2 on 8977. The delivery plan keys a door by address and port, so serving them
   renders a clash and the whole plan is refused. The consumer has the same problem: every `use`
   listener binds the one dgo-net address.
3. **The catalog lists every app, while delivery opens only the served ones.** The MacBook publishes 10
   apps and serves 2. A consumer running the projection would render 8 tiles that cannot open.

**Recommended design: one door per link, Host routing on the serving edge.**
* The serving office answers its peer on ONE tunnel port: a `link` entrypoint of its own traefik, bound
  only to the tunnel side.
* The compiler emits, for each served app, a router on that entrypoint. It carries the link's identity
  mapping (the door's — `link-proxy.py`) instead of `authentik@file`. Apps keep their own ports; Host picks the app.
* The consumer needs one `use` listener per peer, and every remote route targets it with the app's
  serving-side Host. No per-app port allocation, no clash.
* On a host-tunnel far end (vps1, hp-laptop), that one door is the only listener needed on the host:
  `10.79.x.2:<link port>` → the edge. A small host service bound to `wg-quick@wg0` can bridge into the
  office network through a unix socket in a shared volume, so delivery stays by name.
* The catalog lists the served apps only (plus the control door), so a tile always means a door.

"All apps appear" (the owner's words) then becomes `serve: "*"` minus `serve.exclude`. Which apps are
served stays a declaration of the serving office.

### Acceptance 3: the door is built and measured (2026-10-02, `80fda283`)

The three blockers above are fixed in code, and the serving half is measured live on this office.

**One door per link, and the Host header picks the app.** The serving office answers its peer on ONE
port, derived from the PAIR's own slot (`door_port = 9000 + slot`, `linkproxy.py`): both ends compute it
from a fact they already share, so there is no allocation to keep in step. Behind the door the app is
chosen by the authority the consuming edge wrote, and the door's route table is the office's OWN
published catalog, asked over loopback (`GET /api/link/catalog`) and cached for 30 s — never shipped,
because "which apps do I serve" is a declaration on that side and a copy would be a second answer to
it. The door REPLACES the identity header rather than forwarding it: what the app sees is the mapping
this office published for that app (`identity.to`), and the peer's own claim is dropped.

The consumer gets ONE listener per peer, and the compiled route targets the door port the serving
office published (`catalog.build(link_port=…)` → `link.port` → `projection.state_block` →
`remote: … link_port:` → `serve.render`, the registry record, and `bbox remote`), falling back to the
app's own port for a peer whose catalog predates the door. An agent app's adapter keeps an explicit
port rule — a CLI addresses a port, and the door cannot tell an adapter from the UI that shares its
authority.

**The far end's half.** A machine whose tunnel runs on the HOST (vps1, hp-laptop) cannot bind its tunnel
address from a container, so its serving doors are rendered as UNIX SOCKETS plus the address they stand
for (`linkproxy._serve_doors(host_doors=True)`), and `converge.REMOTE_DOOR` installs a systemd unit
(`dgo-link-door.service`) that listens on that address and bridges into the socket directory the
compose now mounts (`${BBOX_REPO_HOST}/.dgo/doors`). Delivery stays by name on both sides of the
bridge; the service is ordered after `wg-quick@wg0` and restarted by systemd, not by a converge.

**Measured** (`dgo-link`, i.e. inside `dgo-net`'s namespace, against the live office): the route table
was read from the office's own catalog (19 names); `Host: bina.localhost` → 200;
`Host: bina.macbook.console.localhost` — the nested name a consuming office's edge writes for a
pass-through app — → 200; an unknown name → 404, not a hang. Module selftests PASS;
`bbox dgo test 3` 20/22, both reds being live facts this commit fixes in code.

**What is left, and the one order that matters.** The plan SHAPE changed, so the two offices must not
straddle it: a new-code Mac shipping a socket plan to an old-code vps1 makes its link proxy exit on an
address it cannot bind. So the order is (1) converge vps1 to the commit that carries this — which needs
the commit PUSHED, the coordinator's step — and only then (2) rebuild this office's `dgo-extend` and
`dgo-link`. Until then the Mac keeps serving the old per-app ports, which is exactly what vps1's current
plan expects. After both, the remaining proof is the owner's own: vps1's tiles on this console, under
this office's SSO, with `serve: {"*": {}}` set on vps1 (`POST /api/link/serve`).

### The door in production, both directions (2026-10-02 14:00–15:45, coordinator)

Rolled out in the order the lane recorded (vps1 first, then the MacBook). Both offices now run
`96967f9e`. `accept-remote.sh` (13 checks) is green:
* **vps1 uses the MacBook's Bina.** The route targets `bina.macbook:9002` (the door). Measured: page
  200, the API fence passes vps1's own Origin and refuses a foreign one, and
  `bbox agent --office macbook list` on vps1 lists the MacBook's sessions.
* **The MacBook shows vps1's apps.** vps1 declares `serve: {"*": {}}`. The MacBook pulls its catalog
  (14 apps) and projects the `remote:` block; the compile renders 14 routers, registry entries and
  dgo-net aliases. Measured: `drive`/`machine` 200 through the door, and
  `drive.vps1.console.localhost` → 302 to the MacBook's own SSO.

Faults found on the way, each fixed and measured (commits on `dgo`):

| Fault | Commit |
|---|---|
| The far end's door port came from its HOME slot (9001), not the pair's (9002) | `db2a4681` |
| A far end with no link of its own could render a peer-less tunnel over the shipped one | `db2a4681` |
| The `*` wildcard was refused by the serve API (400) and its writer (`int(None)`) | `db2a4681` |
| The legacy `serve:` block carried no `link_port`, so the route would have stayed on 3080 | `db2a4681` |
| The door turned a POST body into a header (every API call 400), and kept-alive requests kept the peer's identity | `c1302efc` |
| SERVE_WRITER ended a block at a column-0 list item, so every second write corrupted the state file | `c1302efc` |
| A state repair restored the tracked file and left undeclared apps enabled (31 on vps1) | `c1302efc` |
| An empty door route table was cached for the full 30 s after one refused fetch | `72d04fd8` |
| A unix-socket door clashed with a TCP door that shares only the port number | `dd847955` |
| `TCP_NODELAY` on an AF_UNIX socket killed the connection thread (socket doors hung) | `3602b129` |
| The far end's firewall opened `office.serve` (empty) instead of what the far office serves; ufw dropped the tunnel twice | `89c949be` |
| REMOTE_WRITER started python without its block (empty `remote:`, reported as written) | `6cdbc24c` |
| The far office kept the default label "הלשכה הזאת" | `9315265d` |
| The host door's probe took `*` for an app and reported working doors as down | `3326f8c8` |
| A contribution to a DISABLED app left a serviceless entry, so the whole compose project failed | `96967f9e` |
| A stalled route-table refresh (catalog, then git over SSH) hung live requests through the door | `3f148c04` |
| Re-declaring an app's ports erased its identity mapping and host pass-through (Bina tile 401), and wildcard apps had no identity | `466a8318` |
| `home_office()` rebuilt the home record from a torn read and wrote it back, losing `serve:`, the slot and the name (both directions down) | `2506dee0` |

**Both directions are now complete.** vps1 pulls the MacBook's catalog from its own plan (`b3dcb7e4`, the owner's agent) and shows 7 MacBook apps. The MacBook shows vps1's 14. The rail keeps app names whole (`160de6cc`).

**Open:**
* `serve: {"*": {}}` on vps1 includes `computers` and `connections`; the owner can narrow it with
  `serve.exclude`.
* The bina-ds DSH "remotes" client polls `/api/remote.mux` on vps1's console every ~10 s (400). It is
  noise from a page, not from this chain.
