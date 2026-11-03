# Platform architecture review — understand, clear, minimise, and scale honestly

Written 2026-07-29 against branch `platform-os-refactor` (4 commits ahead of origin, working tree
dirty). Research only: **nothing in the repo was changed to produce this document**, no stack was
started, and no `reconcile.py render` was run (which would have rewritten `.generated/`).

## How to read the numbers in here

Every figure is tagged. There are only three kinds:

| Tag | Meaning |
|---|---|
| **DECLARED** | read out of config text in this repo (compose limits, manifests, `.env`). Says what the system asks for, not what it uses. |
| **MEASURED** | someone ran something against a live stack and wrote the output down. Cited with date and source. |
| **DERIVED** | computed by me from repo contents during this review; the method is stated inline so you can re-run it. |

**Assumptions I could not verify are listed in [§0.2](#02-assumptions-i-could-not-verify).** An
unverified claim in this document would be worse than an omission, so where I could not prove
something I say "unclear" and say what I checked.

---

## 0.1 What I actually read

`AGENTS.md`, `CLAUDE.md`, `README.md`, `platform/manager/reconcile.py` (all 1250 lines),
`platform/schema/app.schema.json`, `platform.state.yaml`, `platform/manager/catalog.py` and
`appinstall.py` headers, `platform-base/connections/README.md`, every `app.json` (27),
every enabled `docker-compose.yml` (19), the gate sources for G0/G5/G7/G9/G18/G25,
`.github/workflows/ci-verify.yml`, `scripts/fresh-machine-check.sh`, `packaging/OPTIMISATION.md`,
`packaging/ROADMAP.md`, `ai/context/low-memory-mode.md`, `attic/README.md`, `legacy/README.md`.
I also **ran** the read-only gates G5, G9 and G25 locally.

## 0.2 Assumptions I could not verify

| # | Assumption | Why it matters | What I checked |
|---|---|---|---|
| A1 | `packaging/OPTIMISATION.md`'s "4.7 GB / 33 containers" is the closest thing to current truth | It is the entire empirical basis of §3 | Dated 2026-07-29 (today). But the **current render is 41 services** (DERIVED, §3.1), not 33. The measurement was taken against the installed Linux artifact, which almost certainly had a different app set. I did not reconcile the two. |
| A2 | The live hacohen VPS runs the same app set as `platform.state.yaml` in this tree | §3 and §4 assume it | I have no access to the VPS from this session. `.env` says `PERFORMANCE_PROFILE=prod` (`.env:409`), which `bbox:147-153` picks for an 8-core host — but `ai/context/low-memory-mode.md:3` says "~8 GB total". A `prod` profile on an 8 GB host is itself worth checking. |
| A3 | `.generated/` on disk matches what `render` would produce today | `.generated/compose.runtime.yml` is dated 2026-07-28 while `.generated/compose.yml` is 2026-07-29 and lists a different service set (`compose.runtime.yml` contains `inbox` and `whatsapp-hacohanim`, neither of which is defined in any current compose file). **Treat `compose.runtime.yml` as stale.** I used the source composes instead. |
| A4 | No live user-count, request-rate or DB-size data exists anywhere | §4's ceilings are structural, not empirical | Searched `ci-artifacts/`, `data/reports/`, `ai/context/`. Found only RAM/latency snapshots. There is **no traffic or tenant-count measurement in this repo at all**, so every "when does this break" in §4 is an argument from structure, not from a curve. |
| A5 | ~~`attic/` and `legacy/` are genuinely inert~~ | — | **DISPROVEN during this review.** Both READMEs assert it; both are wrong in a specific way. See §2.3. |
| A6 | The untracked-file sweep is incomplete | §2 | Reference analysis used `git grep` (tracked files only). A full `rg --no-ignore` over 5 GB of `dist/` + `data/` + `attic/` timed out twice at 5 min. A local untracked wrapper script could still invoke something listed as zero-reference in §2.2 (C21). |

---

# PART 1 — The map

## 1.1 The shape in one paragraph

There is no hand-written stack. `platform/manager/reconcile.py` is a **compiler**: it reads 27
manifests (`*/app.json`) plus one desired-state file (`platform.state.yaml`), resolves a capability
dependency graph, and emits `.generated/` — a compose include chain plus four overlays and four
registries. Everything downstream (bbox, CI, the gates, the console) consumes `.generated/`. The
root `compose.yml` is now **only** the shared external network (`compose.yml:1-6`); it defines zero
services. That is the whole design: *the stack is a pure function of (catalog, state)*, stated at
`platform/manager/reconcile.py:5-6`.

## 1.2 The three layers, and why the directory IS the layer

| Directory | Layer | Contains | Enforced by |
|---|---|---|---|
| `platform/` | 1 (mechanism) | the schema + the compiler. **No app manifests.** | `reconcile.py:38` — `CATALOG_ROOTS` does not include it |
| `platform-base/` | 1–2 | the chassis every deployment needs: edge, identity, state, automation, the shell. 13 manifests. | `reconcile.py:193-196` — a `layer: 3` manifest found here is a **fatal** load error |
| `apps/` | 3 | the installable surface. 14 manifests. | same check, inverted |

`reconcile.py:191-192` additionally makes `app.json`'s `id` == the directory name a fatal error, so
"uninstall app X" and "delete directory X" can never diverge. `reconcile.py:197-198` rejects a
duplicate id across both roots.

The payoff is stated at `reconcile.py:33-36`: *"what can I uninstall?" is answered by `ls apps/`
rather than by reading 25 manifests.*

## 1.3 The compile pipeline — `app.json` → `.generated/`

```
apps/*/app.json  ─┐
platform-base/*/  ├─► load_catalog()  ─► validate()  ─► resolve()  ─► render()  ─► .generated/
   */app.json    ─┤      :180              :213          :288         :797
platform.state.yaml ┘
```

| Stage | Fn:line | What it does | Fails how |
|---|---|---|---|
| **load** | `reconcile.py:180-200` | glob `*/app.json` under the two roots; enforce id==dirname, layer==root, no duplicate ids | `sys.exit` — fatal, no partial catalog |
| **validate** | `:213-284` | structural + **type** check against `platform/schema/app.schema.json`; capability/strength sanity; `compose:` path exists; route-host and console-tile **conflict detection** | returns error list; `main()` prints all and exits 1 (`:917-921`) |
| **resolve** | `:288-438` | transitive closure over hard `use[]`, provider selection, conflicts, topological order | diags list; errors block `apply` |
| **plan** | `:722-744` | writes `.generated/plans/NNNN.yaml` with an `inputs_digest` (`:710`) | applying a stale plan is refused |
| **archive** | `:767-779` | copies current `.generated/` to `.generated/generations/NNNN` before overwriting, keeps 20 | — |
| **render** | `:797-863` | writes the include chain + overlays + registries | — |

### What `render()` emits, and why each file exists

| Artifact | Emitted by | Purpose | Why it is a *separate* file |
|---|---|---|---|
| `.generated/compose.yml` | `:814-836` | the `include:` list — root network first, then one line per enabled app that owns containers | this is the canonical stack definition |
| `.generated/routing.override.yml` | `render_routing :630` | traefik labels from `routing[]`, plus `contributes.env` / `contributes.volumes` merged onto base services, plus `PLATFORM_SERVICES` for console | `include:` requires **disjoint** service sets; overlays merge. Explained at `:838-840` |
| `.generated/connections.override.yml` | `render_broker :575` | per-app credential-broker cutover: entrypoint shim, blanked env, `depends_on: connections healthy` | must come **last** in the `-f` list because it blanks vars the app's own compose sets (`:465-468`) |
| `.generated/glitchtip.projects.yml` | `render_glitchtip :866` | error-tracking project list derived from each app's `observability{}` | so a layer-2 app stops naming layer-3 consumers |
| `.generated/registry/console.modules.yaml`, `console.app_bases.json`, `connections.consumers.yaml`, `connections.providers.yaml`, `connections.probes.json` | `render_registries :1062` | the tile list, the `/a/<alias>/` proxy table, and the per-service secret manifest — all **derived** and mounted read-only by console and connections | same reason: the base app reads them, never authors them |
| `platform-base/authentik/blueprints/zz-generated-apps.yaml` | `render_authentik :1138` | one authentik proxy provider + application per layer-3 app declaring `routing[].sso`, **plus the embedded-outpost entry listing every provider** | written *into* authentik's existing bind-mount so no compose change is needed; `zz-` prefix because authentik applies blueprints in filename order |
| `.generated/resolved.json` | `:859-862` | the order, the migrated set, the configured instances | machine-readable answer to "what is installed" |

The **one** place that answers "which `-f` files are the stack" is `compose_files()`
(`:460-471`). It deliberately does not validate or resolve, so it stays usable while a manifest is
broken (`:906`). Every shell consumer reads it.

### One subtlety worth knowing

`write()` (`:441-457`) forces LF on every platform. `pathlib.write_text(encoding=...)` uses the
*platform* newline, so a Windows-rendered `.generated/` and a Linux-rendered one differed
byte-for-byte from identical source — which silently broke the reproducibility of the signed
release artifact. Found by rendering twice on the same commit and diffing.

## 1.4 Capability resolution — the `use[]` graph

This is the load-bearing algorithm. `resolve()` at `reconcile.py:288-438`.

**Strengths** (`:44`, documented in `ai/context/build-your-first-app.md:78-89`):

| Strength | Pulls provider in? | Ordering edge? |
|---|---|---|
| `requires` | yes | yes (unless `after:false`) |
| `requisite` | no — must already be present | yes |
| `binds_to` | yes, to one instance | yes |
| `wants` | **never** | optional |
| `conflicts` | n/a — refuses the plan naming both apps (`:394-409`) | n/a |

**The closure loop** (`:326-385`): start from every `enabled` app (or from `--for <app>` roots),
walk hard `use[]` edges, pull providers in transitively.

**Provider selection is the part most systems get wrong, and this one gets right** (`:353-382`).
The order is explicit and matches mature package managers:

1. an admin binding in `platform.state.yaml` `bindings.<cap>` — Debian's `update-alternatives`
2. the consumer's `default_provider` — Snap's default-provider
3. the only candidate

Ambiguity with no rule **fails the plan and names every candidate** rather than guessing.
Before this, `ok[:1]` picked whatever the dict yielded first — silent and non-deterministic.

**Ops negotiation** (`:341-352`): a `use[]` entry may list `ops`. A provider missing a required op
is rejected *by name* with the missing ops printed. This turns a capability into a contract rather
than a label.

**Ordering** (`:411-437`): only `after` edges, never through `dependency: weak`. Cycles are
reported with the full path and the hint `break it with dependency:'weak'`.

### The graph as it stands today (DERIVED — read from `.generated/resolved.json`)

20 apps in the resolved closure, 19 of which own containers (`bina-ui` is `kind: library`, no
compose). Start order:

```
postgres → redis → any-concurrency → connections → apitools → app-management → authentik
→ bina-ui → n8n → chat → console → supabase → drive → glitchtip → mail → indox → machine
→ my-docs → notifications → traefik
```

**Note the third-from-last entry.** `supabase` is `enabled: false` in `platform.state.yaml:47-50`
— it is a *gallery* app — but it is in the running closure, because `apps/indox/app.json:48-55`
declares `use: data-api (requires, ops:[rest])` and `apps/supabase/app.json` is the only provider.
Five containers (`rest, storage, kong, meta, studio`) run on an 8 GB host because one app needs
`rest`. This is the resolver behaving **correctly** — and it is also a real minimisation target
(§3.4).

## 1.5 The credential plane — `platform-base/connections`

Two distinct things live in one app, and the distinction is the design.

**(a) The catalog.** `providers/*.yaml` (4 files) describes every connection in the estate — kind,
the `.env` key that seeds it, its consumers, a live probe, wizard behaviour. Resolution order is
`vault store → .env seed → install-wizard prompt`. Adding a connection is a catalog entry, not
code. `manifests/consumers.yaml` plus the **generated** `.generated/registry/connections.consumers.yaml`
say what each service requires.

**(b) The broker.** The security-relevant half. An app declaring a `broker` block in its `app.json`
gets compiled into `.generated/connections.override.yml` (`render_broker :575-627`), which:

| Line emitted | Effect |
|---|---|
| `entrypoint: [inject.sh, …]` | wraps the app's command; the shim proves container identity, leases only this app's declared connections, exports, execs |
| `environment: KEY=` (empty, **not** bare `KEY`) | blanks the secret. `:605-606` — a bare `KEY` re-imports from the host env and would silently undo the cutover |
| `depends_on: connections healthy` | fail-closed |
| `volumes: inject.sh:ro` | the shim |

**Identity has two factors** (`platform-base/connections/README.md`, §"Identity"):
1. source IP → container, via the Docker Engine API (`identity.py`)
2. the caller reads its own 64-hex container id from `/proc/self/mountinfo` and presents it; the
   broker refuses unless that container actually holds the source address

The README is unusually honest about what this does **not** prove: containers keep `NET_RAW`, so a
shared bridge IP is forgeable; the docker socket in that container is host root and the
GET-only restraint is *our code, not the kernel*; the container table is cached 2s and an ip-only
lookup can name a dead container's service inside that window.

**Current state of the rollout (DECLARED, from that README):**

| | |
|---|---|
| Apps migrated to the broker | `drive` (the worked example) |
| Apps still holding standing plaintext env | `indox`, `apitools`, `mail`, `my-docs`, `chat` — five |
| `CONN_BROKER_MODE` default | `warn` — an unidentifiable caller is still **served** |
| `GET /api/export-all` | closed (loopback only) in every mode but `off` |

So the mechanism is built, proven on one app, and **not yet the default**. Policy *is* enforced in
`warn` mode (an identified app can never obtain another's secrets); what `warn` permits is an
*unidentified* caller. G14 in CI (`ci-verify.yml:250`) proves the refusals hermetically.

## 1.6 The edge — traefik + authentik forward-auth

`platform-base/traefik/docker-compose.yml`. traefik v3.3, four entrypoints:

| Entrypoint | Port | Used by |
|---|---|---|
| `web` | 80 | all HTTP routers + ACME http-challenge |
| `websecure` | 443 | all TLS routers, `myresolver` (Let's Encrypt) |
| `postgres` | 5432 | **`n8n-postgres` via `HostSNI`** (`platform-base/n8n/docker-compose.yml:87-92`) |
| `redis` | 6379 | `redis` via `HostSNI` (`platform-base/redis/docker-compose.yml:44-49`) |

Both TCP routers carry an ipallowlist middleware and TLS. Still: **two datastores are published on
the public edge**, guarded by whatever `${N8N_DB_HOST}` / `${REDIS_HOST}` resolve to plus an
allowlist. `packaging/OPTIMISATION.md` Finding 5 flags this and explicitly declines to fix it in a
packaging study. It is unresolved. See R6.

### Label emission — the app declares intent, the compiler writes the labels

`routing_labels()` (`:529-572`) emits exactly three routers per host, per the Runtipi model:

| Router | Rule | Entrypoint | Auth middleware |
|---|---|---|---|
| `<name>-local` | `Host(<host>.localhost)` | web | yes if `auth: sso` |
| `<name>-http` | `Host(${<APP>_BASE_URL:-<host>.${DEPLOYMENT_DOMAIN}})` | web | yes if `auth: sso` |
| `<name>-https` | same host | websecure + TLS | yes if `auth: sso` |

Two decisions here are security-load-bearing and are commented as such:

- `:563-567` — the `-http` router historically carried **no** middleware, on the assumption that
  `${APP}_BASE_URL` is a distinct public domain. On a `DEPLOYMENT_DOMAIN=localhost` deployment it
  resolves to the *same* host as `-local` and traefik may serve the unprotected one. Auth must
  never depend on which of two identical rules traefik picks. Gate **G6** (`auth-lint.py`) enforces
  this against the rendered config.
- `:542-547` — an unset `${APP}_BASE_URL` used to render an empty `Host()`, which traefik treats as
  malformed and **drops the whole container's routers**, 404-ing the app even though its `-local`
  rule was fine. Hence the `:-` fallback.

### The forward-auth chain, and its failure mode

The middleware itself is defined on the **authentik-server container's labels**
(`platform-base/authentik/docker-compose.yml:92-94`):

```
traefik.http.middlewares.authentik.forwardauth.address=http://authentik-server:9000/outpost.goauthentik.io/auth/traefik
```

Consequence, confirmed in `ai/context/low-memory-mode.md:25`: **stopping authentik does not produce
a 502 — it 404s every SSO-gated route**, because a router referencing a middleware traefik can no
longer see is dropped entirely. That reads like a routing bug, not an auth outage. This is a real
operational sharp edge and it is documented only in a low-memory runbook.

`render_authentik()` compiles the provider/application pair per layer-3 app **and** the embedded
outpost entry, because the outpost inherently must list every provider by reference — the one entry
that cannot avoid knowing the whole app set. Base providers are looked up by `!Find` (DB lookup)
because `!KeyOf` only resolves within one file (`:1215-1222`).

## 1.7 How a layer-3 app plugs in

Four files, one directory, zero registration steps:

```
apps/<id>/
  app.json            the manifest — the ONLY thing the platform reads about you
  docker-compose.yml  your services
  Dockerfile          if you build
  blueprint/n8n/*.json  optional automations, imported on enable, removed on disable
```

Then one line in `platform.state.yaml` (`<id>: { enabled: true }`), which is also the only file the
console writes. `ai/context/build-your-first-app.md` walks this field by field using
`apps/hello-bina/` as the worked example.

What the app gets **for free** by declaring, rather than wiring:

| Declare | Get |
|---|---|
| `routing[].host/port/auth` | 3 traefik routers + the SSO middleware |
| `routing[].sso{}` | an authentik proxy provider, application, and outpost registration |
| `routing[].module{}` | a console tile and a `/a/<alias>/` proxy entry |
| `connections[]` | rows in the install wizard + the broker's per-app policy |
| `broker{}` | secrets blanked from `docker inspect` and leased at boot |
| `observability.sentry_platform` | a GlitchTip project |
| `blueprints.n8n` | workflows imported on enable, removed on disable |
| `contributes.env` / `contributes.volumes` | env/mounts merged onto a **base** app without the base app naming you |
| `use[]` | ordered bring-up and provider resolution |

`contributes` is the mechanism that makes G9 (layering) survivable: `any-concurrency` needs
`APITOOLS_CONTAINER`, `console` needs `APITOOLS_URL`, but a layer-2 app may not name a layer-3 app.
The consumer declares it, the compiler merges it. The **rendered** config is identical either way —
only the source of the declaration moves, which is why it costs nothing at G1 (`:630-638`).

Installing from **outside** the tree is also built: `platform/manager/catalog.py` implements an
F-Droid index-v2-style signed catalog (Ed25519 detached envelope, one signature covering the whole
hash chain), and `appinstall.py` does fetch → verify-hash → traversal-safe unpack → validate against
the real catalog with the candidate spliced in → resolve → **disclose** → place+enable, with
rollback if step 7 fails. Steps 1–6 mutate nothing.

## 1.8 Load-bearing invariants and the gates that enforce them

The invariants, stated as the system states them:

| # | Invariant | Why it is load-bearing |
|---|---|---|
| I1 | The rendered stack is a pure function of (catalog, state) | rollback, reproducibility, and the whole plan/apply model depend on it |
| I2 | Where a manifest lives IS its layer | `ls apps/` answers "what can I uninstall" |
| I3 | Nothing lives outside an app | otherwise the platform regrows a second home for services |
| I4 | A base app may never name a layer-3 app | otherwise uninstalling an app leaves a dangling reference in the chassis |
| I5 | A declared capability is actually consumed | otherwise the graph — which orders everything — is decorative |
| I6 | Only `dcx()` invokes compose | a bare `docker compose` at the root resolves **zero** services and exits **0** |
| I7 | Every host path the config references exists | docker silently creates an empty bind dir and the service comes up "healthy" reading nothing |
| I8 | A healthcheck probes the app, not itself | a probe naming a missing binary reports unhealthy forever while serving 200s |
| I9 | Auth cannot depend on which of two identical router rules traefik picks | silent SSO bypass |
| I10 | A tenant-scoped query names its instance | a missing predicate returns/overwrites another client's config, silently |

### The gate registry as CI actually runs it

Source: `.github/workflows/ci-verify.yml:218-361` (job `platform-invariants`, no stack needed) plus
`scripts/fresh-machine-check.sh:100-107`.

| Gate | Script | Enforces | Runs in CI? |
|---|---|---|---|
| **G0** | `paths-exist.py` | I7 — every host path in the rendered compose exists | yes `:359` |
| ~~**G1**~~ | ~~`compose-equiv.py`~~ | ~~rendered config == golden, modulo `moves.json`~~ | **DELETED 2026-07-30** — R7 resolved by deletion; see §1.9(a) |
| G5 | `ownership-lint.py --strict` | I3 | yes `:224` |
| G6 | `auth-lint.py` | I9 | yes `:361` |
| **G7** | `compose-invocation-lint.py` | I6 | yes `:226` |
| G8 | `registry-drift-lint.py` | no registry advertises an uninstalled app | yes `:241` |
| **G9** | `layering-lint.py --strict` | I4 | yes `:228` |
| G10 | `portability-lint.py` | Linux/Windows/macOS host paths | yes `:239` |
| G11 | `fresh-clone-lint.py` | a bare clone has everything tracked files need | yes `:243` |
| G12 | `compile-lint.py` | every first-party `.py` parses | yes `:245` |
| G13 | `blueprint-dep-lint.py --strict` | an app shipping automations depends on the engine | yes `:247` |
| G14 | `connections/test_broker.py` | the broker's **refusals** (hermetic) | yes `:250` |
| G15 | `image-pin-lint.py` | every third-party image pinned | yes `:328` |
| G16 | `app-management/test_conditions.py` | the status/`conditions[].reason` contract | yes `:253` |
| G17 | `platform/manager/test_resolve.py` | **the resolver refuses what it must** | yes `:256` |
| **G18** | `healthcheck-lint.py` | I8 | yes `:272` |
| G19 | `workflow-input-lint.py` | no `executeWorkflow` below typeVersion 1.2 silently passes null | yes `:278` |
| G20 | `sso-provider-lint.py` | `auth: sso` implies an authentik provider exists | yes `:297` |
| G21 | `theme-token-lint.py` | bundled theme copies match source | yes `:305` |
| G21 *(dup)* | `route-claim-lint.py` | routed hosts declared, routers namespaced | yes `:326` |
| G22 | `tenancy-lint.py` | I10 | yes `:285` |
| G22 *(dup)* | `profile-gate-lint.py` | no compose `profiles:` as a second on/off switch | fresh-machine only |
| G23 | `apps/indox/scripts/gen-engine-manifest.py --check` | the drawn engine matches the built engine | yes `:290` |
| G23 *(dup)* | `gallery-default-lint.py` | gallery apps ship disabled | yes `:324` |
| G24 | `external-resource-lint.py` | `external: true` names something the platform provides | yes `:322` |
| **G25** | `capability-use-lint.py --strict` | I5 | yes `:237` |
| — | `charset-first-lint.py` | every served page declares charset in the first bytes | **NO — zero references anywhere** |
| — | `scripts/fresh-machine-check.sh` | a bare clone compiles, renders and gates green | yes `:333` |

I ran three of these locally. All pass with zero debt:

```
G5  PASS — services outside an app: 0 · legacy bridges: 0 · external paths: 0 · builds outside: 0
G9  PASS — base config naming L3: 0 · L3 overrides under base: 0 · app workflows in base: 0
G25 PASS — 27 apps; 4 declared own_instance (authentik/sql, glitchtip/sql, glitchtip/kv, n8n/sql), each with a reason
```

**This is a genuinely strong test estate.** The gates are not lint-for-lint's-sake: nearly every one
carries a docstring naming the *specific production incident* it exists to prevent, and several
(G18, G19, G22, G24) catch failure modes whose only symptom is silence. G22's first run found 26
offending nodes, "including two written the same week". That is the correct reason to build a gate.

## 1.9 What is wrong with the gate registry itself

Four defects, in descending severity.

**(a) G1 is not wired into anything.** `compose-equiv.py` — the gate the entire strangler refactor
was declared safe under, described at `ai/context/platform-os-refactor.md:49-55` as *"G1 runs after
every single app move — that is what makes a 21-service refactor safe"* — appears in **no workflow
and no script**. Its only four references in the tree are prose (`ai/context/platform-operating.md:151,164`,
`ai/context/platform-os-refactor.md:54,178`). Its golden input `.refactor/golden.raw.yml` is dated
2026-07-26 and `.refactor/candidate.yml` 2026-07-23. Evidence: `grep -rn "compose-equiv"` over the
tree returns only those four doc lines. **The invariant "rendering is byte-identical modulo declared
moves" is currently unchecked.**

> **RESOLVED 2026-07-30 — by deletion (R7's second option).** `compose-equiv.py`, `moves.json` and
> `.refactor/golden.raw.yml` are gone, and every document that asserted the invariant was amended in
> the same change, so nothing claims it any more. Re-goldening was tried first and does not work:
> the render on the current tree produces **413 undeclared diffs** against the golden, of which zero
> are relocation violations (all 23 declared old paths — `production/`, `development/`, `traefik/` —
> have 0 tracked files; the diffs are G21 router namespacing, G32's socket move, the deleted
> homepage app's labels, and a docker-compose output-shape change). And it could not have been wired
> into CI even re-goldened: **two renders of the same commit differ by 326 lines across 50 keys**
> because `scripts/ci-env.sh` mints fresh secrets into every render. Byte-equivalence is the wrong
> shape for compiled output; the render's *properties* are gated by G0/G6 (against the rendered
> file) and G15/G18/G21/G24/G26/G30 (against its inputs). Full reasoning and the diff table:
> `scripts/refactor/GATES.md`, "Why G1 was deleted".

**(b) Gate numbers collide.** G21 is both `theme-token-lint` and `route-claim-lint`; G22 is both
`tenancy-lint` (CI) and `profile-gate-lint` (its own docstring, `scripts/refactor/profile-gate-lint.py:2`);
G23 is both `gen-engine-manifest --check` and `gallery-default-lint`. There is **no single registry
file**; the numbering exists only as step names in `ci-verify.yml` and docstrings. "G21 failed" is
currently ambiguous.

**(c) `charset-first-lint.py` is unreferenced.** Zero hits outside its own file. Either wire it or
move it out.

**(d) Three one-shot migration tools remain in the gate directory.** `migrate-app.py`,
`merge-override.py`, `inject-labels.py` are strangler-migration helpers referenced only at
`ai/context/platform-os-refactor.md:81-82`. The migration is complete (G5 reports 0 debt). They read
as gates because of where they live.

---

# PART 2 — Clearance

## 2.1 The honest headline

**The obvious clearance work has already been done, and done better than I would have done it.**
`legacy/README.md` moves workflows on *measured* evidence — `scripts/n8n-node-coverage.py` run
against a 6,689-execution baseline, with a "Deliberately NOT moved" section explaining why five
zero-execution workflows stay (a deploy-time switch's unselected half, a workflow the live chat
container POSTs to, a v1 rollback lane, extractors whose callers are the Python BFF, and production
surface the baseline simply never drove). That last category — *"the fix is coverage, not deletion"*
— is the right instinct and it is rarer than it should be.

So this section is short on "delete this" and longer on "this is untracked junk", "this is
unwired", and — the genuinely useful part — **"this archive's own README is wrong about itself"**
(§2.3).

**Method.** `git ls-files` to separate tracked from untracked; `git grep` for reference analysis;
`git check-ignore` for ignore status; `du -sh` for sizes. Reference checks are **tracked-files-only**
— see assumption A6.

## 2.2 Candidates, with evidence

### Disk-only (untracked build/scratch output) — pure reclaim, zero code risk

| # | Path | Size | Tracked | Evidence | Verdict |
|---|---|---|---|---|---|
| C1 | `dist/` | **2.1 GB** | 0 | gitignored (`.gitignore:116`). Holds `BinaOS-Setup-2026.07.28-r5.exe` (2.18 GB), `wsl_update_x64.msi`, `manifest.json`. CI's `release-bundle.yml` writes `dist/images.tar.zst` — a *different* artifact. Nothing reads these three. | **DEAD** — single biggest reclaim in the repo |
| C2 | `data/` untracked bulk | **~1.3 GB** | 15 of 3308 | `data/exclude` 887 MB, `data/browser42` 250 MB, `data/ui-map` 106 MB, 3 `browser42-state-*.tar.gz.enc` (55 MB). 20 gitignore rules cover these (`.gitignore:31-72`). `fresh-clone-lint.py:26` lists `data/` as EXEMPT. | **DEAD**; **keep the 15 tracked** `data/reports/*` — they are the only historical measurements that exist |
| C3 | `attic/feature-validation` untracked benchmark output | **~700 MB** | 117 of ~800 | 705 MB on disk vs 117 tracked files. `ops/prejob_fixperms.sh:12` exists *because* CI writes root-owned output here the runner cannot delete. | **DEAD output** — but see C9: **the tracked source is LIVE** |
| C4 | `apps/chat/node_modules` + `digital-office/sim/apps/indox/node_modules` | **558 MB** | 0 (`git ls-files \| grep -c node_modules` = **0**) | ignored at `.gitignore:18` | **DEAD** — regenerable |
| C5 | `ci-artifacts/` contents | **215 MB** | 0 | gitignored (`.gitignore:77`). The **directory** is live (written/read by all 3 workflows, `apps/indox/hooks/test.py`, `digital-office/verify/*`); the 641 files in it (`battery-lanes*.log` from Jul 8–9, `concurrency-1h.png`…) are stale output. | **DEAD contents, LIVE dir** |
| C6 | `.tmp-indox-v2-ct/` | 31 MB | 0 | gitignored (`.gitignore:84`) | **DEAD** |
| C7 | 66 untracked `scripts/_*.py` | small | 2 of 68 tracked | `ls scripts/_*.py` = 68; `git ls-files scripts/ \| grep -c 'scripts/_'` = 2. One-shot debugging scripts (`_drvlist.py`, `_oauth_probe.py`, `_mkfold_verify3.py`…) making `scripts/` unreadable — 126 entries of which 68 are scratch. | **DEAD (local)** |
| C8 | 10 root `.env.bak*` / `.env.pre*` / `.env.ci-baseline*` + `env.secrets-temp` | 209 KB | 0 (`.env.ex` is the only tracked `.env*`) | gitignored (`.gitignore:23-27`) | **DEAD — and a security item, see §2.5 and R2** |

**Reclaim total: ~4.9 GB, with zero code risk.**

### Tracked material — the part that needs judgement

| # | Path | Size / tracked | Evidence | Risk of removal | Gate protection | Verdict |
|---|---|---|---|---|---|---|
| C9 | `attic/feature-validation` **source** | 117 tracked | **4 live inbound references**: `.github/workflows/indox-e2e.yml:320` (`docker compose -f attic/feature-validation/docker-compose.yml up -d --build feature-validation-api`), `digital-office/sim/build.mjs:40`, `ops/prejob_fixperms.sh:12`, `ops/README.md:22` | **HIGH** — breaks the INDOX E2E workflow and the sim build | none — no gate covers `attic/` (`ownership-lint.py:40` and `compile-lint.py:23` explicitly exclude it) | **LIVE — DO NOT CLEAR.** See §2.3 |
| C10 | `attic/` — the other 16 subdirs | ~6 MB, ~176 tracked | `git grep "attic/<name>"` outside `attic/` → **0 refs** for all 16 (chess, librechat, rocketchat, searxng, snake99, open-pilot, ktivayehudit-clone2, supabase, agent-runner, incoming-documents, hello-world, log-collector, security-service, filesystem-mcp-sse, plane-mcp-sse, playwright-mcp-sse) | low | none | **DEAD-BY-EVIDENCE** — but keeping them is a deliberate, documented choice with near-zero cost. Recommend **keep**, and fix the README (§2.3) |
| C11 | `legacy/` | 24 MB, 97 tracked | No path reference from `platform/`, `apps/`, `scripts/`, `bbox`, `.github/`, `.ci-cd/`. The 4 string mentions are an output label (`scripts/n8n-node-coverage.py:171`), an *exclusion* filter (`layering-lint.py:326`), and 2 prose lines. | low | **G13** (blueprint-dep) + the `blueprints.n8n` manifest path make accidental import structurally impossible | **LIVE-BY-INTENT** — the evidence-based archive is genuinely valuable. **But see §2.3** |
| C12 | `digital-office/sim/` | 126 MB, 81 tracked | **NOT CI-wired** (`grep digital-office .github/` → 0 hits; `grep -E "digital-office\|flow-qa\|verify-sim" bbox` → 0 hits). **But live dev/spec tooling**: `scripts/ui-coverage/live-ui-map.py:119`, `pixel-diff.py:118`, `sim-live-parity.py:15,59-60` (which *imports* `sim/ui-map.py`), `CLAUDE.md:25-29,87`, and `apps/chat/bots/intent.js:4` + `apps/chat/chatapi/adapters/local.js:15` cite `sim/mocks/wadmin.js` **as the contract** | **HIGH** | — | **LIVE.** Clearable part is only the 111 MB `node_modules` and the 12 tracked minified `sim/apps/indox/dist/assets/*` build outputs |
| C13 | `digital-office/tooling/` | 1.7 MB, 107 tracked | Only 2 references exist and **both are inside `digital-office/` itself** (`digital-office/context/ENGINE-CONTRACT.md:3-4`). Nothing in `scripts/`, `apps/`, `platform*/`, `.github/`, or `bbox` names it. 107 tracked HTML fragments + `assemble.js` with no external consumer. | unknown | none | **UNCLEAR — strong DEAD candidate, not provable.** `assemble.js` may be run by hand and `frag/*.html` may assemble into `platform-mockup.html`; I did not diff them |
| C14 | `apps/chat/trash/` | 9 KB, 3 tracked | `csv_generator.js`, `users_sheet.js`, `vcf_generator.js`. `git grep -E "csv_generator\|users_sheet\|vcf_generator"` outside the dir → **0 hits** | none | G11 (fresh-clone) + G12 (compile-lint) would catch a needed file | **DEAD** — cleanest removal in the repo |
| C15 | `.refactor/` | 253 KB, 8 tracked | ~~**`golden.raw.yml` is LIVE input**: `compose-equiv.py:12` reads it~~ — **its only reader was G1, now deleted.** `auth-lint.py:35` and `paths-exist.py:116` still default to `.refactor/candidate.yml`, a gitignored local render, so the *directory* stays. The 6 `*.log` files + `outpost.block` are tracked but referenced only by `legacy/README.md:28`. | low | — | **RESOLVED 2026-07-30** — `golden.raw.yml` deleted with G1 (§1.9a, R7); directory kept for the gitignored `candidate.yml` default. Logs still **DEAD** |
| C16 | `next-7h/` | 112 KB, 0 tracked | Gitignored (`.gitignore:83`) **but two tracked scripts touch it**: `scripts/automations-reset.py:229` **reads** `next-7h/pre-reset-snapshot.json`; `scripts/google-api-audit.py:71` **writes** `next-7h/GOOGLE-API-AUDIT.md` | **deleting it breaks `automations-reset.py` at runtime** | none | **LIVE INPUT** — a gitignored directory that tracked code depends on. That combination is itself the bug: a fresh clone cannot run `automations-reset.py`. **G11 (fresh-clone-lint) should catch this and does not.** |
| C17 | `platform-base/n8n/_archive/bdchh5urW9lBzudZ.json` ("Snooze Incoming Document") | 8 KB, 1 tracked | Referenced by `apps/indox/blueprint/n8n/indoxV2Driver01.json:753`, node `Call 'Snooze Incoming Document'`, **`disabled: true`**. 5 further references treat it as deliberately retained (`ai/context/indox-full-ioc-outline.md:71` literally calls it "dangling ref: pruned but still referenced by a disabled node") | deleting leaves a dangling pointer in a live workflow file | none — no gate checks sub-workflow target resolution | **KEEP + resolve the reference.** See R9 |
| C18 | `platform-base/n8n/workflows/*.json` (6 files) | 168 KB, all tracked | All 6 verified LIVE: `RqAY1Z1i2F7ZaPbe` (error handler, referenced from ≥5 blueprints), `ciHelloWebhook01` (`scripts/ci-verify.sh:149`), `ilrs3Nl5eKmOLWFQ` (process_lock), `sAjhxlLTUq9vEL8L` (`platform-base/n8n/hooks/push:353`), `xXeUYAtl1bODJSrD` (called from 3 indox blueprints), `HwFalPFB7gLyd4d8` (named in `blueprint.yml:30`) | — | — | **LIVE — zero orphans** |
| C19 | `scripts/refactor/charset-first-lint.py` | 3.7 KB tracked | zero references outside itself; absent from `fresh-machine-check.sh:101`'s roster; no lint runner discovers `scripts/refactor/*.py` by glob (`grep -E "scripts/refactor\|\*-lint\|glob" bbox` → 0 hits) | none | n/a | **DEAD (unwired gate)** — wire it or move it |
| C20 | `scripts/refactor/{migrate-app,merge-override,inject-labels}.py` | 10 KB tracked | referenced only at `ai/context/platform-os-refactor.md:81-82`; the migration they served is complete (G5 = 0 debt) | none | n/a | **SUPERSEDED** — move out of the gate directory |
| C21 | Zero-reference scripts (6 more) | small, tracked | `scripts/_inject_drive_local.py`, `scripts/b42-call.sh`, `scripts/b42mcp.js`, `scripts/google-api-audit.py`, `scripts/ui-coverage/pixel-diff-montage.py`, `scripts/ui-coverage/UI-INVENTORY.md` — all zero inbound references from tracked files | low | none | **UNCLEAR** — see assumption A6; an untracked local wrapper could invoke any of them |
| C22 | `README.md:48-72` + `AGENTS.md:22-32` — the `production/`+`development/` architecture | doc, tracked | **neither directory exists** (`ls -d production development` → no such file; `git ls-files \| grep -c '^production/\|^development/'` → **0**). README also documents `production/n8n/workflows/` for `scripts/n8n-pull/push`. | **the two entry-point documents describe a deleted architecture** and never mention `platform/manager/reconcile.py` | none | **STALE — highest-value doc fix in the repo. See R1** |

## 2.3 Two archive READMEs that are wrong about themselves

This is the most useful thing in Part 2, because both files are *load-bearing claims* that a future
cleanup will act on.

**(a) `attic/README.md` says:** *"Nothing here is installed, routed, or referenced by
`platform.state.yaml`; the reconciler does not see it and gate G5 deliberately ignores it."*

Every clause is true **and the conclusion a reader draws is false.** `attic/feature-validation` has
**four live inbound references** (C9), including a `docker compose` invocation inside
`.github/workflows/indox-e2e.yml:320`. Deleting `attic/` — which the README invites — breaks the
INDOX E2E workflow and the digital-office sim build. G5 cannot catch it, *by design*: G5 checks
"is a service defined outside an app dir", and this is a workflow file reaching *into* attic, which
is the opposite direction. **Nothing in the gate estate covers this.**

**(b) `legacy/README.md` says:** *"It is deliberately NOT referenced by any manifest, so
`blueprints.n8n` never resolves into it and no push can import it."*

True as stated — and the move left a residue in the file it moved things out of.
`platform-base/n8n/blueprint.yml:19` `active_workflows:` has **89 entries, of which 29 name a
workflow no enabled blueprint provides** (DERIVED — I resolved every entry against every enabled
app's `blueprints.n8n` directory):

| | count | examples |
|---|---|---|
| entries resolving to a live blueprint | 60 | — |
| entries whose only on-disk copy is in `legacy/` | **25** | `Balance Sheet Extractor`, `BS_EX_1`, the 8 `_diag_*` probes, the 4 `[FV] Test Integration - *`, `Gmail Documents Scanner`, `Google Integration Health`, `My workflow 15`, `_pdbg`, `_pgs` |
| entries resolving to **nothing anywhere** | **4** | `Gmail MCP Server`, `drive api - local`, `gmail api - oauth`, `ztest gmail api` |
| duplicated entries | 2 | `Google Drive MCP Server - agent.hacohen`, `Google Sheets MCP Server - agent.hacohen` each appear twice |

**Severity: LOW, and the reason is worth stating precisely.** `active_workflows` is **written** by
`platform-base/n8n/hooks/pull:172` — it is a *snapshot of the live n8n instance*, not authored
config — and **read by nothing**: `grep -rn "active_workflows"` returns the declaration, the
pull-hook writer, one exclusion in `layering-lint.py:100`, and prose. So these 29 entries are stale
telemetry, not broken wiring.

But: `data/reports/before-release-report.md:101,148` already flagged this in June 2026 —
*"`active_workflows:` list is **never consumed**"*, severity MEDIUM — and it is still here, now
33% wrong. A committed snapshot that nothing reads and that drifts silently is exactly the shape of
thing this repo's gate philosophy exists to eliminate. `platform-base/n8n/workflows/.n8n_push_hashes`
carries the same problem: ~57 of its entries are hash-cache rows for workflow ids that now live only
in `legacy/`.

## 2.4 Two stale pointers found incidentally

Both are one-line fixes and neither is caught by anything:

1. **`.github/workflows/local-hebrew-doc-ex.yml:26`** path-triggers on
   `platform-base/n8n/workflows/JQExV3*.json`. **That glob matches no file on disk** (verified:
   `ls platform-base/n8n/workflows/JQExV3*` → no such file). The JQExV3 family lives under
   `apps/indox/blueprint/n8n/`. The workflow's own trigger cannot fire on the files it means to
   watch — though `apps/indox/**` on the next line happens to cover it, which is why nobody noticed.
2. **C17** — the disabled `executeWorkflow` node pointing into `_archive/`.

## 2.5 The security item that outranks everything else in this document

`issues/n8n-encription-rotate.yaml` — **`severity: critical`, `status: open`, opened 2026-06-14**
(45 days ago):

> Credentials were committed to git and pushed to GitHub; files were removed but the values MUST be
> rotated (git removal alone does NOT make them safe).

The issue states the values were present in `origin/main` (the default branch) and `origin/COPILOT`,
and lists nine secret classes to rotate — including `N8N_ENCRYPTION_KEY` (which, together with the
committed `db-dumps/n8n-pg-dump.sql`, exposes **every stored n8n credential**), `POSTGRES_PASSWORD`,
`N8N_USER_MANAGEMENT_JWT_SECRET`, Anthropic/DeepSeek API keys, a Telegram bot token, a Google OAuth
client secret + refresh token, and a hardcoded Google Vision key.

`data/reports/before-release-report-v2.0.1.md:34` records it as a merge blocker, *"deferred by owner
to post-release rotation"*.

**This is not a clearance item and it is not an architecture item — it is the single highest-severity
open finding in the repository, and it has been open for six weeks.** The ten untracked `.env.bak*`
files (C8) are a *different, smaller* problem; deleting them does not touch this one. See R0.

## 2.6 What I could NOT prove and am therefore not recommending

- `digital-office/tooling/` (C13) — 107 tracked files, no external consumer found, but I did not
  diff `frag/*.html` against `platform-mockup.html`. **Unclear.**
- The 6 zero-reference scripts (C21) — `git grep` is tracked-only and the untracked sweep timed out
  (A6). **Unclear.**
- Whether any of `attic/`'s remaining 176 tracked files is imported from an enabled path. The
  `attic/feature-validation` case proves this class of reference exists, so the other 16 subdirs'
  "0 refs" should be re-checked with an untracked sweep before anyone acts on it. **Unclear enough
  that I recommend keeping all of `attic/`.**

## 2.7 One genuinely clean result worth recording

I scanned every workflow in every enabled app's `blueprints.n8n` directory (82 importable workflows
across `platform-base/n8n/workflows`, `apps/{chat,drive,indox,mail}/blueprint/n8n`) for
`executeWorkflow` nodes whose target id is not provided by any installed blueprint.

**Exactly one dangling reference exists, and it is disabled** (C17). For a system with 82 workflows
and this much churn, that is a good number, and it is the kind of thing that only stays good if
something checks it — which nothing currently does (R9).

---

# PART 3 — Minimisation

## 3.1 The numbers, carefully separated

**DERIVED (by me, 2026-07-29).** Method: parse `.generated/compose.yml`'s `include:` list, load each
listed compose file, sum `deploy.resources.limits.memory` across all services, substituting the
`${VAR:-default}` default.

| | value |
|---|---|
| Compose services in the currently-enabled render | **41** |
| …with a memory limit | 36 |
| …**with no limit at all** | 5 — `authentik-bootstrap`, `chat`, `mailapi`, `mailserver-init`, `indox-demo-docs` |
| Sum of declared limits (using `APITOOLS_MEM` default 4G) | **35,200 MiB = 34.4 GiB** |
| Sum with `.env`'s actual `APITOOLS_MEM=8G` (`.env:432`) | **39,296 MiB = 38.4 GiB** |

**MEASURED (`packaging/OPTIMISATION.md`, 2026-07-29, on the installed Linux artifact).**

| | value |
|---|---|
| Actual RAM, whole estate | **4.7 GB across 33 containers** |
| Layer 1 (chassis) | 1.56 GB / 9 containers |
| Layer 2 (base apps) | 1.56 GB / 15 containers |
| Layer 3 (installed apps) | 1.55 GB / 9 containers |
| Image store on disk | 11.05 GB (3.36 GB reclaimable) |
| Shipped artifact | 2.10 GB |

**The delta, stated honestly.** Declared 38.4 GiB against ~8 GB of host, against ~4.7 GB actually
used. Two separate facts:

1. **Declared limits are ~5× the host and ~8× actual usage.** They are not a sizing decision; they
   are a collection of independently-chosen ceilings that nobody has ever summed. Under Docker's
   default (non-swarm) compose, `deploy.resources.limits` is a *cap*, not a reservation, so this
   does not by itself cause OOM — but it means the caps provide **no protection whatsoever**: at
   38 GiB of caps on an 8 GB host, the host OOM-killer fires long before any cgroup limit does. The
   limits are decoration.
2. **`reservations` are different and do matter.** 6.75 GiB of declared reservations (per the
   resource sweep) against ~8 GB. Reservations are advisory in compose-without-swarm, so today this
   is also inert — but it is inert by accident, and it would become a scheduling failure the moment
   anyone moves this to swarm/k8s.

⚠️ **Caveat (A1):** 41 services (my count) vs 33 containers (the measurement) do not reconcile. Do
not compute a per-container average from these two figures. The right next step is a fresh
`docker stats --no-stream` against the *current* render — a ~30-second job that this repo does not
contain the output of.

## 3.2 The single biggest structural waste: four Postgres servers

**MEASURED + DECLARED.** Confirmed independently by me from the composes:

| Server | Image | Version | Declared limit | Owner | Why |
|---|---|---|---|---|---|
| `db` (`supabase-db`) | `supabase/postgres:15.8.1.085` | 15.8 | 2 GiB | `platform-base/postgres` | **the actual `sql` provider** |
| `n8n-postgres` | `postgres:17` | 17 | 3 GiB | `platform-base/n8n` | own migration runner, pinned to 17 |
| `authentik-postgres` | `postgres:16-alpine` | 16 | 512 MiB | `platform-base/authentik` | own migrations, pinned major |
| `glitchtip-postgres` | `postgres:16-alpine` | 16 | 1 GiB | `platform-base/glitchtip` | Django, Docker-only upstream |

Three apps declared `use: sql (requires)`, the resolver pulled `postgres` in and ordered it first,
and all three then connected somewhere else. G25 now makes each of those an **explicit
`own_instance` + `reason`** rather than a silent accident — I ran it and all four are declared with
reasons pointing at `packaging/OPTIMISATION.md` phases.

That is the right fix *for the drift*. It does not remove the cost:

| Cost | Amount |
|---|---|
| Extra containers | 3 |
| Extra RAM (measured) | ~325 MB |
| Extra base images in the signed artifact | 2 |
| Postgres majors to patch | 3 (15, 16, 17) |
| Separate backup/restore stories | 4 — **and none of them exists**, see R3 |

The pattern that proves consolidation works is already in-tree: `kv`. Both authentik and n8n point
at the layer-1 `redis`. One server, two consumers.

## 3.3 The single biggest consumer: authentik

**MEASURED** (`packaging/OPTIMISATION.md`): 1132 MB across 4 containers = **24% of the entire
platform's memory**, for identity on a single-company deployment. The study's recommendation —
replace with Authelia (one Go binary, ~50 MB) rather than port — is the highest-value single move in
the estate and I agree with it, with one addition the study does not make:

**Replacing authentik also removes the 404-on-outage failure mode** described in §1.6, *if* the
replacement's forward-auth middleware is defined in traefik's file provider
(`platform-base/traefik/config/traefik-dynamic.yaml`) rather than on the auth container's own
labels. That is a routing change worth making **independently of, and before,** any auth
replacement — it converts "auth down = every app 404s and looks like a routing bug" into "auth down
= 502, which is legible". See R5.

## 3.4 Services that could become optional or merge

| Target | Today | Proposal | Saving | Confidence |
|---|---|---|---|---|
| **supabase** (`rest, storage, kong, meta, studio`) | 5 containers, 2.0 GiB declared, pulled into the closure by `indox`'s `use: data-api ops:[rest]` even though `platform.state.yaml:47-50` marks it disabled | Only `rest` (PostgREST) satisfies the declared op. `studio` is a UI, `meta` serves Studio, `kong` is a gateway, `storage` serves `object-storage` which nothing declares a `use` for. **Split a minimal `postgrest` adapter app** providing `data-api ops:[rest]`, leave the full supabase in the gallery for people who want Studio. | **−3 to −4 containers, −1.3 GiB declared.** Actual saving unmeasured. | High on structure, unmeasured on RAM |
| **glitchtip** | 4 containers, 4.25 GiB declared (`glitchtip` 2G + worker 1G + postgres 1G + valkey 256M), 325 MB measured | Nothing `requires` error-tracking — only `wants`. Move to the gallery, ship disabled. | −4 containers, −325 MB from a default install | High — this is `packaging/OPTIMISATION.md` phase 4 |
| **console + notifications + machine + any-concurrency** | 4 containers, 4 Python interpreters, 4 framework baselines; 521 MB measured for six services | Merge the four read-mostly observability surfaces into one ASGI app with four routers. **Explicitly keep `connections` and `app-management` separate** — the first because isolation *is* its security control, the second because it must restart everything else without restarting itself. | −3 containers, ~−370 MB | High — and the study is right to recommend *against* a Go/Rust rewrite of these |
| **n8n workers** | `n8n`, `n8n-worker-1`, `n8n-worker-2` + 3 runner sidecars = 6 containers, 12 GiB declared | Two questions, both unanswered by any measurement in this repo: (a) does a single-company deployment need two workers? (b) n8n's *internal* task runners would remove 3 sidecars. | potentially −3 to −4 containers | **Low — do not act without measurement.** See R11 |
| **`indox-demo-docs`** | a caddy container serving `blueprint/demo-docs` read-only, **no memory limit** | It is demo/fixture infrastructure in the default install. Should be gated behind the demo/onboarding path, not shipped running. | −1 container | Medium — I did not verify whether the extraction gate depends on it at runtime |

## 3.5 Images that could share a base

**DERIVED** from the Dockerfile `FROM` lines:

| Base | First-party builds |
|---|---|
| `python:3.12-slim` | **12** — apitools, drive, indox, mailapi, mailview, my-docs, any-concurrency, app-management, connections, console, machine, notifications |
| `node:22-alpine` | 2 — openhands/agent-proxy, openhands/dispatcher |
| `node:22-slim` | 1 — chat |
| `node:20-alpine` | 1 — indox builder stage |
| `alpine:3.20` | 1 |
| `n8nio/n8n:${N8N_VERSION}` | 1 |

Python is already consolidated (`OPTIMISATION.md` phase 0 moved `any-concurrency` and `machine` off
3.13). **Node is not**: three tags for four builds. Unifying costs nothing and removes two base
images from the artifact.

**The reproducibility hole matters more than the size.** `OPTIMISATION.md` Finding 3 is precise
about it: G15 pins every *third-party* `image:` and exempts first-party builds on the grounds that
"their content is pinned by the commit". Two inputs float free — the base tag (`FROM python:3.12-slim`
is mutable) and the dependency set (`app-management` requires `Flask>=3.0 gunicorn>=21 PyYAML>=6.0
docker>=7.0`; `notifications` similar; four others pin direct deps but float `sentry-sdk>=2.0` and
pin no transitives). **The artifact is signed.** A signature attesting to a build nobody can
reproduce is a weaker claim than it appears to be.

## 3.6 Three Docker clients, one platform

`OPTIMISATION.md` Finding 4, which I consider under-rated:

| Service | Client | Weight |
|---|---|---|
| `app-management`, `machine` | `docker` PyPI SDK | +32 MB, drags requests + urllib3 + websocket-client |
| `any-concurrency` | `aiodocker` | async, lighter |
| `connections` (`identity.py`) | hand-rolled `http.client` over `AF_UNIX`, ~80 lines | **zero dependencies, GET-only by construction** |

`machine` is a read-only observability surface holding a client capable of `POST /containers/create`.
Moving it onto `identity.py`'s client is smaller, faster to build, and converts a security property
from *assumed* to *checkable*. `app-management` genuinely mutates and keeps the SDK.

## 3.7 Where the memory limits should actually come from

The perf-profile system (`platform/profiles/perf-profiles.yml`, applied by `bbox:147-153`
`ensure_perf_profile`) sizes **CPU and concurrency** to the host across four profiles — but
parameterises **memory for exactly one service** (`APITOOLS_MEM`). The other 35 limits are
host-independent literals scattered across 19 compose files.

That is the root cause of the 38 GiB sum: nobody chose it, because nobody could see it. The
structural fix is not to hand-tune 36 numbers — it is to make the sum **visible and gated**:
a lint that reads the enabled render, sums the limits, and fails if the total exceeds
`N ×` the profile's declared host memory. See R4.

---

# PART 4 — "Billion users", answered honestly

## 4.1 What scale means for THIS product

This is a **single-VPS, one-deployment-per-company** product. `packaging/ROADMAP.md` makes that
explicit: the shipped artifact is a 2.1 GB single-file executable (`.run` on Linux, `.exe` on
Windows) that installs its own Docker engine on its own socket and brings up the whole stack. One
company gets one deployment. `BUSINESS_NAME` → `COMPANY_SLUG` → every hostname
(`reconcile.py:47-66`) — the company identity is a *build-time constant of the deployment*.

So "a billion users" decomposes into two completely different problems, and the architecture's
answers to them are opposite:

| Axis | What it means here | Does the architecture support it? |
|---|---|---|
| **More companies** | more deployments, each on its own host | **Largely YES, and this is the real product.** The compiler makes a deployment reproducible from (catalog, state); the packaging pipeline makes it installable by a non-engineer; the signed catalog makes apps distributable. What is missing is *fleet* — see 4.2. |
| **More users per company** | more people inside one deployment | **NO, and mostly it does not need to.** A company has tens to hundreds of employees, not millions. But there are two places where "per company" ceilings bite well below that, and they are real — see 4.2. |

**The honest framing: this is not a system that serves a billion users. It is a system that could
serve a billion users' worth of *companies*, one deployment at a time, if the fleet story existed.**
Those are different engineering problems and only one of them is worth working on now.

## 4.2 Genuine single points of failure and hard ceilings TODAY

### Structural, verified

| # | Ceiling | Evidence | When it bites |
|---|---|---|---|
| F1 | **Every service has an explicit `container_name`** | 41 of 41 in the enabled render (`grep -c container_name` across every compose file: authentik 4, n8n 7, glitchtip 5, mail 5, supabase 5, …) | `docker compose up --scale` **refuses** to scale a service with a `container_name`. There is no horizontal scaling of anything, at all, today — not even in principle. Scale-out exists only as copy-paste: `n8n-worker-1` and `n8n-worker-2` are two hand-written services, not `replicas: 2`. |
| F2 | **Zero `replicas:` / `deploy.mode: replicated` anywhere** | grep across all composes returns nothing | same |
| F3 | **One traefik, one host, ports 80/443/5432/6379** | `platform-base/traefik/docker-compose.yml:45-50` | the edge is the host. No LB, no second node, no failover. Single VPS reboot = full outage. |
| F4 | **Forward-auth middleware defined on the authentik container's labels** | `platform-base/authentik/docker-compose.yml:92-94` | authentik down ⇒ traefik drops every gated router ⇒ **404, not 502**. Documented only in `ai/context/low-memory-mode.md:25`. Reads as a routing bug during an incident. |
| F5 | **`CHAT_SELF_USER` is process-wide** | `apps/chat/chatapi/db/index.js:36` (`process.env.CHAT_SELF_USER \|\| 'me'`), set at `apps/chat/docker-compose.yml:61`. The compose comment says it plainly: *"every operator shares one identity"* | **hard ceiling of one operator identity for local chat.** Not a scale problem — a correctness problem the moment a company has two people. Already ranked "2.0 — the most dangerous existing gap" at `ai/context/chat-backend-research.md:432`. |
| F6 | **The WhatsApp bot is an in-process Baileys socket bound to one phone number**, with its pairing session in a host bind (`${WHATSAPP_DATA_DIR:-./data}:/app/data`) | `apps/chat/docker-compose.yml:73-74` | single-writer file state. Cannot be replicated (two containers on one session = logout). One number per deployment. |
| F7 | **Four Postgres servers, no replica, no pooler, no backup** | §3.2; `git ls-files \| grep -i backup` → **0 results**; the only `pg_dump` mention in the whole repo is prose at `platform-base/glitchtip/README.md:206` | any of the four is a total-loss SPOF for its subsystem, and there is **no restore path in the repo**. Compounding: §2.5's open credential-rotation issue requires re-encrypting every n8n credential, which is exactly the operation you must not perform without a restore path. |
| F8 | **`data.volumes` in the manifests is already drifting from reality** | `apps/drive/app.json` declares `volumes: []` while `apps/drive/docker-compose.yml` declares the named volume `localdrive_data`. `indox` and `apitools` declare `volumes: []` while holding state in binds (`apps/indox/docker-compose.yml` `./storage:/app/.storage`; `apps/apitools/docker-compose.yml` `./storage`, `./logs`). `chat` declares `wa_media` but not the `./data` bind holding the WhatsApp session. | the declaration that *should* drive a backup is wrong, and **no gate checks it**. Whoever writes the backup tool from `data.volumes` will silently skip INDOX's storage and the WhatsApp session. |
| F9 | **n8n `max_connections=100`, `work_mem=32MB`** | `platform-base/n8n/docker-compose.yml:15,37` | 100 × 32 MB worst case = 3.2 GB against a 3 GiB cap. Not a bug today (work_mem is per-sort, not per-connection), but there is no pooler and nothing measures connection count. |
| F10 | **The traefik v3.3 / Docker 28.x pin is a countdown** | `CLAUDE.md:60-69` — v3.3 hardcodes docker client API 1.24; Docker 29 raised the daemon floor to 1.40; traefik then discovers **zero** routers while reporting healthy | not a scale ceiling — a *lifespan* ceiling. Every distro moves to Docker 29 eventually. The failure is silent and looks like a hundred unrelated test failures. |
| F11 | **The multi-tenant story exists only inside INDOX, and only as a column** | `scripts/refactor/tenancy-lint.py:1-35` — `settings`, `companies`, `tag_rules` carry an `instance` discriminator; documents are table-per-instance | so *some* multi-company-within-one-deployment already works, guarded by G22. But it is INDOX-specific. `drive`, `mail`, `chat` use `platform.state.yaml` `instances:` for *connection* multiplicity, not tenancy. There is no platform-wide tenant concept. |

### Not a ceiling, contrary to what you might assume

- **SQLite / file state**: I searched. There is **no SQLite anywhere** (`git ls-files | grep -iE '\.sqlite|\.db$'` → empty). `chat` talks to the layer-1 Postgres directly, and the compose comment explains why it bypasses PostgREST (one query with three LATERALs would become an N+1 of HTTP calls). File state is limited to the WhatsApp session (F6), `apps/{indox,apitools}/storage`, and the connections Fernet vault.
- **The compiler**: `reconcile.py` is a pure function over ~27 manifests. It will not be a bottleneck at 10,000 apps, let alone at scale.

## 4.3 What would have to be true, in order, for 10× / 100× / 1000×

I am reading "×" as **companies**, because that is what this product sells. Baseline: assume the
order of a hundred deployments today (I could not verify the actual number — A4).

### 10× companies — the first thing that breaks is **operations, not architecture**

Nothing in the compiled stack needs to change. What breaks first:

1. **Backup/restore.** At 10× you will lose someone's Postgres, and today there is no tool. (R3)
2. **Fleet visibility.** You cannot answer "which deployments are on which version, and which are
   unhealthy" — there is no fleet plane, only per-deployment `app-management`.
3. **Update rollout.** `bbox` + the signed catalog give you *per-deployment* install; there is no
   staged rollout, no canary, no "roll back deployment 47".
4. The 38 GiB of declared limits (§3.1) start producing support tickets on smaller hosts, because
   nothing gates the sum against the host.

**None of these require a rewrite. All four are tooling.** This is where the effort belongs.

### 100× companies — the first thing that breaks is **the secrets and identity model**

1. **`CONN_BROKER_MODE=warn` is not shippable at 100×.** Five apps still hold standing plaintext
   env. The broker exists and is proven on `drive`; the migration has to finish and the mode has to
   flip to `enforce`.
2. **The traefik/Docker pin (F10).** At 100× deployments across customer-controlled hosts, you no
   longer control the Docker version. This becomes a support catastrophe with a silent symptom.
3. **Reproducible builds (§3.5).** At 100× you must be able to say "this customer is running exactly
   this artifact" and rebuild it. Floating `FROM` tags and floating pip deps make that untrue today.
4. **Per-user identity within a deployment (F5).** At 100× companies, the number of companies with
   >1 operator approaches 100%.

### 1000× companies — the first thing that breaks is **the single-host assumption itself**

Only here does architecture change. And even then, the honest answer is probably **not** "make one
deployment horizontally scalable" but "make deployments cheap enough to be dense" — several small
companies per host, isolated by deployment, rather than one company across several hosts. The
per-deployment footprint (§3, target ~3.0 GB / 23 containers) is what makes that possible or not.

If you genuinely needed one company to outgrow one host, the order would be:
Postgres consolidation → external managed Postgres → drop `container_name` → replicas for the
stateless tier (`apitools`, `console`, `drive`, `my-docs`) → traefik behind a real LB →
session/state extraction from `chat`. That is a k8s-shaped project. **Nothing in this repo suggests
you are close to needing it.**

## 4.4 What is premature to build now — say it plainly

| Do not build | Why not |
|---|---|
| Horizontal replicas / k8s / a service mesh | You have one host per customer and no measured request-rate data at all (A4). Building for replicas would delete the property that makes this product work: a whole company's system as one `docker compose` include chain that a compiler generates and a gate proves. |
| A multi-tenant rewrite (many companies in one deployment) | The single-deployment-per-company model is the *product*, not a limitation. It is what makes the signed artifact, the offline install, and the "your data is on your machine" claim true. INDOX's `instance` column already covers the one case that genuinely needed within-deployment multiplicity. |
| Rewriting the Python services in Go/Rust | `packaging/OPTIMISATION.md` already measured this: ~80 MB beyond what process consolidation gives, for weeks of work and a second toolchain. The study recommends against it and is right. |
| Compiling Python to binaries | Keeps the interpreter. Buys startup time you are not short of. |
| Sharding, read replicas, connection pooling | You have no measurement showing a single Postgres is under pressure. `pgbouncer` before `pg_dump` would be absurd. |
| Treating the n8n triple build as a build-time problem | Measured: the layers dedup, builds 2 and 3 are cache hits. Fix it for clarity, not speed. |

**The honest summary of Part 4:** the architecture is well-suited to the scale it will actually
meet, and its real risks are not scale risks. They are *durability* risks — no backups, secrets in
plaintext in five apps, a version pin with a fuse on it, and a manifest field (`data.volumes`) that
already lies about where the state is. Fix those and this system is solid. Build for a billion
concurrent users and you will break the thing that makes it good.

---

# PART 5 — Ranked recommendations

Rows are in priority order (value ÷ risk); the **R-numbers are stable identifiers, not ranks** —
R23–R25 were added late and sit where they belong, not at the number they carry. Items marked
*(speculative)* are ideas I could not fully justify from evidence in this repo. "Gate?" answers
*would an existing gate protect this change*.

**Sequencing constraint that overrides the ordering:** R4 → R3 → R0 must run in that order, and
R3 must precede R13 (Postgres consolidation) and R21 (authentik replacement). You cannot safely
migrate or re-encrypt a database you have no restore path for.

| # | Recommendation | Prevents / removes | Risk | Effort (dev-days) | Gate? |
|---|---|---|---|---|---|
| **R0** | **Execute `issues/n8n-encription-rotate.yaml`.** Rotate all nine secret classes; re-encrypt every n8n credential after the new `N8N_ENCRYPTION_KEY`; revoke the Google refresh token and the Telegram token; remove the hardcoded Vision key fallback. | §2.5 — a `severity: critical`, `status: open` issue, six weeks old, stating that credentials including the n8n master key **and** a Postgres dump of every encrypted credential were pushed to `origin/main`. Everything else in this document is an optimisation next to this. | **Medium execution risk, unbounded risk of inaction.** Rotating `N8N_ENCRYPTION_KEY` makes existing credentials undecryptable, so it must be sequenced: new key → re-enter every credential → verify workflows. Needs a maintenance window. | **2–3** | No gate can help. But **R3 (backups) should land first** so the re-encryption step is reversible. |
| **R1** | **Rewrite `README.md` §Architecture and `AGENTS.md` §Layout to describe `platform/` + `platform-base/` + `apps/` and the compiler.** Both currently document `production/` and `development/`, which do not exist (§2.2 C22). **Also correct `attic/README.md` and `legacy/README.md`** (§2.3) — both make inertness claims that are wrong in ways a future cleanup will act on. | The two documents a new engineer reads first describe a deleted architecture and never mention `reconcile.py`. Plus: `attic/README.md` invites a deletion that would break `.github/workflows/indox-e2e.yml:320`. | **None** — docs only | **0.5** | No. Consider a docs-lint asserting every path named in README/AGENTS exists — trivially derivable from `paths-exist.py`. |
| **R2** | **Delete the 10 root `.env.bak*` / `env.secrets-temp` files; add one `ops/env-snapshot` helper writing to a single gitignored dir with a retention count.** | 10 plaintext copies of production secrets in the working tree, and no way to tell which is current (§2.2 C8). **Note: this does not resolve R0** — these files were never committed. | Low — verify `.env` is current first | **0.5** | No. Add a `fresh-clone-lint` rule: no `.env*` at repo root except `.env`, `.env.ex`. |
| **R3** | **Ship `bbox backup` / `bbox restore`, derived from each app's `data.volumes` + its stateful binds.** | **There is no backup or restore tooling in this repo.** `git ls-files \| grep -i backup` returns zero. `AGENTS.md:18` says "back up before destruction" and provides no mechanism. Four Postgres servers, zero restore paths. | Medium — must be proven by an actual restore into a scratch deployment, not by the script exiting 0 | **4–6** | No — and it **needs R4's companion gate first** (see next row), because `data.volumes` is already wrong. |
| **R4** | **Add gate G26: `data.volumes` in `app.json` must match the app's compose (named volumes + stateful host binds).** | F8 — `drive` declares `[]` but has `localdrive_data`; `indox`/`apitools` hold state in `./storage` binds declared nowhere; `chat` omits the WhatsApp session bind. Whoever writes R3 from `data.volumes` silently skips them. | Low — pure static check, same shape as G0 | **1** | It *becomes* the gate. Model it on `paths-exist.py` (G0), which already walks every host path in the rendered config. |
| **R5** | **Move the `authentik` forward-auth middleware definition from the authentik container's labels into `platform-base/traefik/config/traefik-dynamic.yaml`.** | F4 — authentik down currently **404s** every gated route instead of 502-ing, because traefik drops routers whose middleware vanished. Turns an auth outage into what looks like a routing bug, during an incident. | **Medium** — touches every gated route. Must be verified against G6 (`auth-lint`) and a real auth-down test. | **1–2** | **Yes — G6** (`auth-lint.py`) checks no unprotected router shares a rule with a protected one; **G21** (`route-claim-lint`) checks router namespacing. Neither proves the middleware still attaches, so add an assertion to the baseline. |
| **R6** | **Decide and record: are the `postgres`/`redis` TCP entrypoints (:5432/:6379) on the public edge intentional?** If yes, write the reason next to the rule. If vestigial, remove the entrypoints. | Two datastores published by SNI on the public edge (`platform-base/n8n/docker-compose.yml:87-92`, `platform-base/redis/docker-compose.yml:44-49`). Flagged in `packaging/OPTIMISATION.md` Finding 5 and never resolved. | Low to record; **medium to remove** (unknown external consumers) | **0.5** to record, **1** to remove | No. Worth a gate: "no TCP router without a documented reason + an ipallowlist". |
| **R7** | ~~**Wire G1 (`compose-equiv.py`) back into CI with a fresh golden, or delete it and say so.**~~ **DONE 2026-07-30 — deleted, docs amended.** Re-goldening was attempted and rejected on evidence: 413 undeclared diffs, none of them relocation violations, and the render is not reproducible run-to-run (326 lines / 50 keys differ between two renders of one commit, because CI mints fresh secrets into it). Byte-equivalence is the wrong shape for compiled output. | §1.9(a) — the gate the whole refactor was declared safe under ran nowhere. The invariant "rendering is byte-identical modulo declared moves" was asserted in six documents and checked by nothing; all six now say it is not checked. | Low. The risk was *inaction*: a half-believed gate is worse than a deleted one. | **0.25** (delete + amend the docs) — spent | Replaced by property gates over the render: G0/G6 on the rendered file, G15/G18/G21/G24/G26/G30 on its inputs. |
| **R8** | **Create `scripts/refactor/GATES.md` — one table, one number per gate — and make `ci-verify.yml` step names reference it.** Resolve the G21/G22/G23 collisions (§1.9b). | Three duplicate numbers today. "G21 failed" is ambiguous. The registry currently exists only as CI step names and docstrings. | None | **0.5** | No. A tiny lint asserting every `scripts/refactor/*.py` appears exactly once in GATES.md and once in a workflow would also catch C19 (`charset-first-lint`, unwired). |
| **R9** | **Add gate G27: every non-disabled `executeWorkflow` target resolves to a workflow some enabled app's blueprint imports.** | The class of bug where an automation calls a sub-workflow the platform never installs — silent, and the exact shape G19 already guards a sibling of. Today the estate is clean (1 dangling ref, disabled — §2.7), which is precisely when to add the gate. | Low — I wrote and ran the scan in ~20 lines during this review | **0.5–1** | It *becomes* the gate. Pairs naturally with G19 (`workflow-input-lint.py`). |
| **R10** | **Add gate G28: the sum of `deploy.resources.limits.memory` over the enabled render must not exceed `N ×` the active perf profile's host memory.** | §3.1/§3.7 — 38.4 GiB of declared caps on an ~8 GB host. Nobody chose this; nobody could see it. The caps provide zero protection (the host OOM-killer fires first) and would become a hard scheduling failure under swarm/k8s. | Low — static sum. Choosing `N` needs one judgement call (overcommit is legitimate; 5× is not). | **1** | It *becomes* the gate. Also: give the 5 uncapped services (`chat`, `mailapi`, `authentik-bootstrap`, `mailserver-init`, `indox-demo-docs`) limits, or make "uncapped" an explicit declared decision like `own_instance`. |
| **R11** | **Take one `docker stats --no-stream` against the current 41-service render and commit it as `ci-artifacts/`-adjacent evidence.** | A1/A3 — the only measurements in the repo are from a 33-container artifact run and from April–June estate reports describing services now in `attic/`. Every minimisation decision below this line is currently reasoning from a mismatched baseline. | None | **0.25** | No — but consider making `bbox baseline` emit it, so the number is never stale again. |
| **R12** | **Finish the broker migration: `indox`, `apitools`, `mail`, `my-docs`, `chat` each get a `broker` block; then flip `CONN_BROKER_MODE` to `enforce` once `GET /api/broker/audit` shows no `unidentified` grants.** | Five apps hold standing plaintext credentials. One compromised app is currently every credential it holds, permanently. `drive` is the proven worked example — the mechanism is built and gated (G14). | **Medium** — each cutover changes an entrypoint; a wrong `blank_env` list fails the app at boot. But it fails *loudly and immediately*, which is the good failure mode. | **1 per app + 1 to flip = 6** | **Yes — G14** proves the refusals hermetically; G0 proves `inject.sh` is mounted; `depends_on: connections healthy` makes it fail-closed. |
| **R13** | **Postgres consolidation, phase 1: fold `glitchtip-postgres` into the shared `db`** (the easiest of the three — glitchtip is heading to the gallery anyway). | §3.2 — −1 container, −1 GiB declared, −1 Postgres major to patch. | **Medium-high** — it is a data migration. Needs a dump/restore + a row-count gate, which is why **R3 must land first.** | **3–4** | **Yes — G25** now enforces that the `own_instance` declaration matches reality, so removing the instance and the declaration together is checked. |
| **R14** | **Split a minimal `postgrest` adapter app providing `data-api ops:[rest]`; leave full supabase in the gallery.** | §3.4 — 5 containers and 2.0 GiB declared run on the default install because `indox` needs `rest`. `studio`/`meta`/`storage` serve nothing anyone declares. | Medium — `indox`'s data path is load-bearing; needs the INDOX E2E suite green (`bbox indox test`) | **2–3** | **Yes** — G25 (capability actually consumed), G23 (gallery apps ship disabled), G8 (registry drift). The resolver will pick the new provider only if `bindings.data-api` or `default_provider` says so — which is exactly the reviewable-decision path §1.4 describes. |
| **R15** | **Move `glitchtip` to the gallery (`enabled: false`).** | §3.4 — −4 containers, −325 MB measured, from a default install. Nothing `requires` error-tracking; only `wants`. | Low — `wants` never pulls anything in, so the resolver handles it correctly by construction | **1** | **Yes — G23** (`gallery-default-lint`) enforces gallery apps ship disabled; `render_glitchtip` already derives the project list from enabled apps, so it degrades cleanly. |
| **R16** | **Unify the Node base images (`node:22-alpine` / `node:22-slim` / `node:20-alpine` → one tag) and extend G15 to first-party `FROM` lines + require a dependency lockfile.** | §3.5 — the signed artifact is not reproducible: mutable base tags plus floating pip deps in `app-management` and `notifications`. | Low for the base unification; **medium** for lockfiles (a bad pin breaks a build loudly) | **1** + **2–3** | **Yes — G15** is exactly the gate; this extends it. G12 (compile-lint) and G11 (fresh-clone) catch collateral. |
| **R17** | **Merge `console` + `notifications` + `machine` + `any-concurrency` into one ASGI app.** Keep `connections` and `app-management` separate. | §3.4 — −3 containers, ~−370 MB, one interpreter instead of four. | Medium — four HTTP surfaces move; every route and every console tile must still answer | **5–8** | **Yes** — G21 (`route-claim-lint`, router namespacing), G0 (paths), G18 (healthchecks), and `bbox ui-map` / G3-G4 pixel diff would all catch regressions. This is well-protected. |
| **R18** | **Move `machine` onto `identity.py`'s dependency-free, GET-only Docker client.** | §3.6 — a read-only observability surface currently holds a client capable of `POST /containers/create`. Converts a security property from assumed to checkable. | Low | **1–2** | No existing gate. Worth one: "only `app-management` may import a mutating docker client." |
| **R19** | **Move `migrate-app.py` / `merge-override.py` / `inject-labels.py` out of `scripts/refactor/`; wire or remove `charset-first-lint.py`.** | §2.2 C19/C20 — three completed one-shot migration tools and one unwired lint read as gates. | None | **0.25** | Falls out of R8. |
| **R23** | **Reclaim ~4.9 GB of untracked build output** (`dist/` 2.1 GB, `data/` untracked 1.3 GB, `attic/feature-validation` output 700 MB, `node_modules` 558 MB, `ci-artifacts/` 215 MB, `.tmp-indox-v2-ct/` 31 MB, 66 `scripts/_*.py`). Delete `apps/chat/trash/` (3 tracked files, zero references). | §2.2 C1–C8, C14 — disk, and a `scripts/` directory where 68 of 126 entries are scratch. | **None** for the untracked set. | **0.5** | No — but every one of these is untracked or zero-reference, so G11/G12 would catch a mistake on the tracked deletion (`apps/chat/trash/`). |
| **R24** | **Fix the three stale pointers**: `active_workflows` in `platform-base/n8n/blueprint.yml` (29 of 89 entries wrong) + the ~57 stale `.n8n_push_hashes` rows; the `JQExV3*` path trigger at `.github/workflows/local-hebrew-doc-ex.yml:26` that matches no file; and `next-7h/` being a gitignored directory that tracked code (`scripts/automations-reset.py:229`) reads. | §2.3, §2.4, §2.2 C16. Individually small; collectively they are the drift this repo's whole method exists to prevent. `active_workflows` was already flagged MEDIUM in June 2026 and is now 33% wrong. | Low | **1** | **G11 (`fresh-clone-lint`) should already have caught the `next-7h` case and does not** — a fresh clone cannot run `automations-reset.py`. Extending G11 to "no tracked script reads a gitignored path" is the real fix. |
| **R25** | **Add a gate covering references *into* `attic/` and `legacy/`** — either forbid them, or require them to be declared. | §2.3(a) — `.github/workflows/indox-e2e.yml:320` runs `docker compose` against a file in `attic/`, which every existing gate is designed to ignore. The archive READMEs tell readers this cannot happen. | Low | **0.5** | It *becomes* the gate. Natural extension of G5 (`ownership-lint.py`), which today only checks the outbound direction. |
| **R20** *(speculative)* | **Plan the traefik ≥ 3.6.2 upgrade** (a release whose docker provider negotiates the API version). | F10 — the Docker-28 pin is a countdown with a silent failure mode: traefik reports healthy, discovers zero routers, every host 404s. | **High** — needs validation across every route and the entire authentik forward-auth chain. `CLAUDE.md:66-69` deliberately declines to bundle it. | **3–5**, plus a full baseline | **Yes — G6, G21, G3/G4 (ui-map + pixel diff)** are collectively a strong regression net for exactly this change. That net existing is what makes the upgrade tractable. |
| **R21** *(speculative)* | **`authentik` → Authelia.** | §3.3 — the single largest consumer: 1132 MB / 4 containers / 24% of the estate, plus one of the four Postgres servers. | **High** — replaces identity for every route. Blueprint-driven SSO provisioning (`render_authentik`) would need a Authelia-shaped equivalent. | **10–15** | Partially — G20 (`sso-provider-lint`) and G6 would need rewriting for the new model, which is itself part of the work. **Do R5 first** so the outage failure mode is already legible before you change the thing that fails. |
| **R22** *(speculative — do not act without R11)* | **Reduce n8n to one worker and adopt n8n's internal task runners** (−3 to −4 containers). | §3.4 — 6 containers, 12 GiB declared, for one company's automation. | Medium — throughput regression is possible and would show up as INDOX documents processing slower, which is the business. | **2–3** | Partially — `bbox indox test` and the 527/527 extraction gate (`scripts/baseline.sh:206-219`) would catch a throughput cliff, but only if you *look* at duration, not just pass/fail. |

## 5.1 If you only do five things

1. **R4 → R3 → R0** — in that order. A gate that makes `data.volumes` true, then a backup tool built
   on it, then the credential rotation that has been open since 14 June. R0 is the highest-severity
   item in the repo; R3 must precede it because rotating `N8N_ENCRYPTION_KEY` makes every stored
   credential undecryptable and there is currently **no restore path**. These three are one
   sequence, not three items.
2. **R1** — the front door describes a deleted architecture, and two archive READMEs invite a
   deletion that would break CI. Half a day.
3. **R10** — make the 38 GiB of declared limits visible and gated, so it can never silently regrow.
4. **R5** — turn "auth down = mysterious 404s across every app" into "auth down = 502".
5. **R12** — finish the broker migration and flip `CONN_BROKER_MODE` to `enforce`. The mechanism is
   built, proven on `drive`, and gated by G14; it is currently a security control running in `warn`.

Everything in §3 (minimisation) is real value and none of it is urgent. `packaging/OPTIMISATION.md`
already has the right plan and the right order for it.

## 5.2 A note on what is already right

It is worth being explicit, because a review that only lists problems misrepresents the system.

The compiler is genuinely good. `reconcile.py` is 1250 lines with a comment-to-code ratio that
would be indulgent if the comments were describing *what* the code does — they aren't; they
describe **the incident that made each line necessary**, and several of those (`ok[:1]` picking a
provider non-deterministically, `KEY` vs `KEY=` re-importing a blanked secret, the empty `Host()`
dropping a container's whole router set, `write_text` emitting CRLF into a signed artifact) are
subtle enough that most systems would have shipped them permanently.

The gate estate is the strongest thing here. Twenty-five gates, nearly all of them cheap enough to
run without a stack, nearly all of them traceable to a specific silent failure. The pattern
"we found a bug → we wrote the gate → the gate found 26 more" (G22) is what a durable system looks
like from the inside.

And `packaging/OPTIMISATION.md` is a better optimisation document than this one is, because its
numbers are measured and mine are mostly derived. The correct reading of Part 3 is: *that study is
right, its phase order is right, and the main thing this review adds is that R3/R4 (backups) belong
before its phase 1 (Postgres consolidation), because you cannot safely migrate a database you have
no restore path for.*
