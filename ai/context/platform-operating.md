# Operating the platform — run it, find its state, install/remove apps

Companion to [platform-os-refactor.md](platform-os-refactor.md) (the *why*). This is the *how*.

## The shape in one screen

```
platform/                 layer 1 MECHANISM — the schema + the compiler. No app manifests.
  schema/app.schema.json    the manifest contract
  manager/reconcile.py      the compiler:  plan | validate | render | up | compose-files
  profiles/*.yml            cross-cutting overlays (ci-images, connections-mode, perf)

platform-base/<id>/       layers 1-2 — the base every deployment needs (15).
                          traefik, authentik, redis, supabase, n8n, console, connections,
                          glitchtip, notifications, homepage, machine, any-concurrency,
                          browser42, portainer, bina-ui.  NOT a user's choice.

apps/<id>/                layer 3 ONLY — the installable surface (10).
                          indox, my-docs, mailview, drive, localmail, inbox,
                          apitools, chat, ollama, openhands.

platform.state.yaml       DESIRED STATE — the only file you edit to install/remove.
.generated/               COMPILED OUTPUT (gitignored) — never hand-edit.
legacy/                   parked. Not installed and not routed, but NOT unreferenced —
                          see legacy/README.md for its two declared live consumers.
```

Where a manifest lives **is** its layer, and `reconcile.py` enforces it: a layer-3 manifest in
`platform-base/` is a fatal load error, not a lint warning. So "what can I uninstall?" is
answered by `ls apps/`.

## Running it

```bash
./bbox run          # autodetects the host, compiles, brings up a healthy routed stack
./bbox status       # containers + n8n + credential health
./bbox stop         # containers removed, VOLUMES KEPT
./bbox reset        # DESTROYS all data (down -v) — asks to confirm
```

`bbox run` is the whole story on a fresh machine: it sizes the stack to the host's cores, starts
Docker if needed, and adapts to a proxied sandbox. Every accommodation is a no-op where it isn't
needed, so the same command is correct on Windows, the Debian VPS, and a cloud sandbox.

### The one compose rule

Services are **compiled** into `.generated/`; the root `compose.yml` holds only the shared
network. A bare `docker compose` at the repo root therefore resolves **zero services** and exits
**0** — a silent no-op. Always go through the wrapper:

```bash
./scripts/dc ps                                          # shell, CI steps, Makefiles
OVERLAYS="platform/profiles/ci-images.yml" ./scripts/dc up -d
dcx restart n8n                                          # inside a script that sourced lib.sh
```

Both `-f <compiled list>` and `--project-directory` are required, and neither has an env-var
equivalent: `COMPOSE_FILE` alone leaves project-directory defaulting to `.generated/`, where the
generated `- compose.yml` include self-resolves into `include cycle detected`. Gate **G7**
enforces this; it is how a broken `n8n-push` restart shipped once.

## Where state lives

State is deliberately in four separate places, by lifetime:

| What | Where | Lifetime | In git? |
|---|---|---|---|
| **Which apps exist / how they compose** | `apps/*/app.json`, `platform-base/*/app.json` | the repo | ✅ yes |
| **Which apps are ON, and their instances** | `platform.state.yaml` | the deployment | ✅ yes |
| **Secrets** | `.env` (+ the `connections` vault) | the machine | ❌ gitignored |
| **Runtime data** | docker volumes (`deployment-hacohen_*`) | until `bbox reset` | ❌ no |
| **Compiled artefacts** | `.generated/` | rebuilt every run | ❌ gitignored |

`platform.state.yaml` is the **only** file the console writes, and it holds exactly two kinds of
fact:

```yaml
schema_version: 1
apps:
  indox:    {enabled: true,  config: {}}
  ollama:   {enabled: false, config: {}}      # gallery: present, not installed
instances:                                     # multi-instance domains (Home Assistant model)
  drive: {active: drive, entries: [...]}
  mail:  {active: inbox, entries: [...]}
```

Two deliberate consequences:

* **Multi-instance lives in state, not the manifest.** A manifest declares *that* it provides
  `drive`; which accounts are configured is a deployment fact.
* **The platform never touches git.** It reads and writes plain files. You get a git-traceable
  history because the files are in the repo, not because anything auto-commits.

Nothing else is a source of truth. `.generated/` is output; delete it and `bbox run` rebuilds it.

## Install / uninstall / enable / disable

**enable ≠ start** (the OSGi distinction). `enabled` is a *persistent disposition*; container
state is transient. Disabling never destroys data.

**The apps screen — `app-management` (layer-1 control plane).** The whole lifecycle is one click at
`apps.localhost` (or the "ניהול אפליקציות" tile in the console, order 1). It reads every manifest +
`platform.state.yaml` + live docker state into a catalog, and enable / disable / uninstall / install
each apply immediately. Under the hood it does exactly what the CLI does — edit `platform.state.yaml`,
`reconcile.py render` (pure python), then apply the RUNNING state through the docker socket
(docker-py): disable=stop, enable=start, uninstall=remove + the `data.on_uninstall` policy
(purge/keep), install=CREATE (translating the app's compose to docker-py, binds resolved to the host
path). Cross-platform; core layer-1/2 apps are protected. This is where the lifecycle logic lives.

The headless/bootstrap CLI does the same disposition change without the running control plane:

```bash
# INSTALL an app: add its folder, then turn it on.
#   apps/<id>/app.json  + apps/<id>/docker-compose.yml
./bbox apps enable <id>             # flips platform.state.yaml + recompiles
./bbox run                          # converge (or use the apps screen for one-click apply)

# DISABLE (keep every byte of data — reversible)   ./bbox apps disable <id> ; ./bbox run
# RE-ENABLE (comes back with its data intact)       ./bbox apps enable <id>  ; ./bbox run
# UNINSTALL (remove + data.on_uninstall policy)     — the apps screen; the manifest declares
#   which volumes are removable; nothing is deleted implicitly.
```

The gallery pattern: `ollama` and `openhands` ship as manifests with `enabled: false`. They are
visible in the catalog and installable with one click (or a one-line state change) — no file to author.

### What the compiler does with that

`reconcile.py` resolves the enabled set into a start order and emits the compose lane:

```bash
python3 platform/manager/reconcile.py plan      # start order + why (dependency diagnostics)
python3 platform/manager/reconcile.py validate  # 25 manifests, capability inventory
python3 platform/manager/reconcile.py render    # -> .generated/
```

Dependencies are **capability**-based, not name-based (Fuchsia CFv2): an app declares the
capabilities it `use`s, with a `strength` (`requires|wants|requisite|binds_to|conflicts`) that is
decoupled from ordering (`after`), plus the `ops` it actually needs. The resolver refuses to bind
a provider that lacks a required op, and `dependency: weak` is the only sanctioned way to break a
cycle. Turning an app off therefore fails loudly if something still requires it — rather than
half-starting.

## The gates

Run before trusting anything. The full registry — one number, one gate, and which lane each runs on
— is [`scripts/refactor/GATES.md`](../../scripts/refactor/GATES.md); the canonical list CI is checked
against is `scripts/ci/gates.sh`. The ones below are wired into CI's `platform-invariants` job; the
static ones need no stack.

| | Gate | Proves |
|---|---|---|
| G0 | `paths-exist.py` | every referenced host path exists (docker silently creates empty dirs) |
| G5 | `ownership-lint.py --strict` | nothing lives outside an app dir |
| G6 | `auth-lint.py` | no unprotected router shares a rule with a protected one |
| G7 | `compose-invocation-lint.py` | no bare `docker compose` (it resolves 0 services, exit 0) |
| G8 | `registry-drift-lint.py` | no registry advertises an app the platform doesn't install |
| G2 | `bbox baseline` | full fresh proof: reset -> build -> up -> ci-verify -> indox |
| G3/G4 | `bbox ui-map` | view coverage + pixel diff (needs the Linux runner) |

G7 is self-tested four ways — a gate nobody has tried to fool is a rubber stamp.

> **G1 (`compose-equiv.py`) was deleted on 2026-07-30.** It asserted the rendered config was
> byte-equivalent to `.refactor/golden.raw.yml` modulo declared moves. **Nothing asserts that now,
> and nothing should**: the render is compiled from the manifests, so it changes on every app
> add/remove/enable, and it is not even reproducible run-to-run (CI mints fresh secrets into it).
> The render's *properties* are gated instead — G0 and G6 below run against the rendered file
> itself. Full reasoning: `scripts/refactor/GATES.md`, "Why G1 was deleted".

```bash
python3 platform/manager/reconcile.py render
./scripts/dc config > /tmp/cand.yml
python3 scripts/refactor/paths-exist.py /tmp/cand.yml
python3 scripts/refactor/auth-lint.py /tmp/cand.yml
python3 scripts/refactor/ownership-lint.py --strict
python3 scripts/refactor/compose-invocation-lint.py
python3 scripts/refactor/registry-drift-lint.py
```

## What the fully-clean fresh run found

`bbox reset --force && bbox run` on an emptied machine (20 volumes destroyed) reached a
converged stack in **~10 minutes** — 34 healthy, 0 unhealthy, 119 workflows and 25 credentials
restored from the blueprint, 52 webhooks registered. It also surfaced three real bugs that only
a first-ever bring-up can expose, each a *silent* failure:

1. **`perf-profile-apply` read a path that moved.** It raised `FileNotFoundError` and both
   callers wrapped it in `|| true`. The host was therefore never sized — and since that step is
   what caps `deploy.resources.limits.cpus` to the host, a fresh install on a small box would
   have aborted with "range of CPUs is from 0.01 to 2.00".
2. **A fresh deploy ended up with no owner account.** `n8n` binds IPv4-only and `localhost`
   inside the container resolves to `::1` first — the same defect fixed in the healthcheck, still
   present in four more places. All 20 probe retries failed, so the owner bootstrap was skipped,
   the credential reseed then had no owner to log in as, and all 21 env-driven credentials were
   silently skipped. The stack came up "successfully" with no way to log into n8n and every
   basic-auth webhook unauthenticated.
3. **`bbox run`'s default `--wait` is too short for a cold start.** Authentik's migrations +
   blueprint + outpost sync exceed the 300s default (CI already overrides to 600), so the very
   first run printed "not all services healthy within 300s" and then converged anyway a few
   minutes later — cosmetic, but it makes the one-command promise look broken. Now the timeout is
   chosen by probing authentik's own database volume: absent = cold = 600s, present = warm = 300s.

All three are fixed. Re-running ci-verify against that same fresh stack afterwards:
**24/25**, the single remaining failure being the documented Windows-only curl cookie-jar
path issue (`integration-n8n-active-state`), which is an environment limit, not a defect. All three share a shape worth internalising: *a failure that is
swallowed reads exactly like success.*

## Still hand-maintained (the honest gap)

The plan called for **six** registries to become compiler output. Three are:

* the compose include list → `.generated/compose.yml`
* the central `compose.override.yml` (633 lines) → `.generated/routing.override.yml`, deleted
* traefik router + auth labels → compiled from each manifest's `routing[]`

Those three are **now compiled too** — the reconciliation the earlier blocker described is done:

* `.generated/registry/console.modules.yaml` — the console's module tiles, from each app's
  `routing[].module` (`platform-base/console/modules.yaml` keeps only the shell's own built-ins as
  a fallback).
* `.generated/registry/console.app_bases.json` — the `/a/<alias>/` proxy table, read by
  `console/app.py`; the base app no longer hardcodes a layer-3 name (G9 `--strict`).
* `platform-base/authentik/blueprints/zz-generated-apps.yaml` — SSO providers + applications, from
  `routing[].sso`; plus `.generated/registry/connections.consumers.yaml` from each app's
  `connections[]`.

They used to drift, and they did: `feature-validation` was parked in `attic/` yet the console still
shipped a tile and a proxy target for it — the tile rendered and the click 502'd, with nothing
failing. **G8** makes that a build failure; generating the registries from the manifests removes the
second hand-written copy entirely, so there is nothing left to drift.

## Plan audit — what is done and what is not

| Plan item | State |
|---|---|
| Three-layer split, enforced by the loader | ✅ `platform/` · `platform-base/` (15) · `apps/` (10) |
| Every service lives in an app; nothing outside | ✅ G5 `--strict`, debt 98 → 0 |
| `development/` gone, experiments parked | ✅ `attic/`, 17 items, not installed |
| Central `compose.override.yml` (633 lines) | ✅ deleted → compiled `routing.override.yml` |
| Compose include list compiled | ✅ `.generated/compose.yml` |
| Traefik router + auth labels compiled | ✅ from each manifest's `routing[]` |
| One compose invocation, enforced | ✅ `./scripts/dc` / `dcx`, gate G7 |
| Capability-based deps (strength, ops, weak) | ✅ resolver + `plan` diagnostics |
| enable/disable ≠ start/stop; disable keeps data | ✅ `platform.state.yaml` |
| Gallery apps installable by one line | ✅ `ollama`, `openhands` |
| INDOX owns its container **and** its workflows | ✅ one app, `apps/indox` |
| **console `modules.yaml` compiled** | ✅ `.generated/registry/console.modules.yaml` (app.json `routing[].module`); committed fallback only |
| **console `APP_BASES` compiled** | ✅ `.generated/registry/console.app_bases.json`; base app no longer names a layer-3 app (G9 --strict) |
| **`PLATFORM_SERVICES` compiled** | ✅ from each app's `capabilities` with `contract: platform-service.v1` |
| **authentik blueprint + connections consumers compiled** | ✅ `zz-generated-apps.yaml` (from `routing[].sso`) + `connections.consumers.yaml` (from `connections[]`) |
| **app-specific `scripts/` → `apps/<id>/hooks/`** | ✅ primary tooling migrated — `apps/indox/hooks/{test,demo}`, `platform-base/{n8n,glitchtip,supabase}/hooks/*`. A tail of ~15 CI/extraction dev utilities (extract-gate, sync-v3-*, acceptance-*) stays under `scripts/` as the shared test harness invoked by `ci-verify`/`baseline` |
| **`bbox indox\|b42\|n8n` → `bbox app <id> <verb>`** | ✅ `bbox app <id> <verb>` is the mechanism (runs `<root>/<id>/hooks/<verb>`); the three named groups remain as thin per-app grammar wrappers |
| **domain renames + consolidation** | ✅ `localdrive`→`drive`, `gmail-imap`→`inbox`; `apps/mail` = inbox+mailview+localmail in one app; drive already whole |
| **workflow ownership** | ✅ G9 `--strict` = 0 — no base app names a layer-3 app in config, code, or workflow; the 29 workflows left in `platform-base/n8n/` are shared stdlib (Error Handler, Batch API GSheet Cache, …) |
| G2 full baseline + G3/G4 ui-map | ✅ runs on Linux, Windows and macOS |

So "nothing stays outside" is true for **services, workflows, and the derived registries**, all
gate-enforced. The only deliberate residue is the shared CI/test harness under `scripts/` — tooling
that spans apps (baseline, ci-verify) or is a cross-app dev utility, which is where it belongs.

## The layering rule — a base app may never name a layer-3 app

The split is only real if it constrains dependencies. The arrow points one way:

```
apps/ (layer 3)  ---- uses ---->  platform-base/ (layers 1-2)
platform-base/   -- NEVER names ->  apps/
```

A base app that hardcodes a layer-3 name is broken by definition: uninstall that app and the
base still refers to it. `platform-base/glitchtip/blueprint.yml` enumerating `my-docs`,
`localdrive`, `mailview`, `apitools` was the canonical case — and it still listed `librechat`
and `feature-validation` long after both were parked in `attic/`.

**The fix is never to delete the reference — it is to invert it.** The layer-3 app declares what
it wants in its own `app.json`, and the compiler emits that into the base app's config:

```json
"observability": { "sentry_platform": "python" }            // -> .generated/glitchtip.projects.yml
"observability": { "sentry_project": "incoming-docs",       // legacy DSN env-var spelling
                   "sentry_platform": "python" }
```

Gate **G9** (`layering-lint.py`) is the scoreboard, split by how each category inverts:

| Category | Inversion | Debt |
|---|---|---|
| base config naming a layer-3 app | declare in `app.json`, compile it in | 60 -> **1** |
| layer-3 override files under a base app | move the file into the app | **0** ✅ |
| app-specific workflows in `platform-base` | move to `apps/<id>/blueprint/n8n/` | 44 -> **4** |

Everything a base app used to hand-author is now compiled — see
[platform-apps.md](platform-apps.md) for the full table. What remains is 4 shared stdlib
workflows whose bodies mention indox's redis-key namespace (coupling, not ownership) and one
secret whose `id` happens to be `localmail`.

Started at 60 files. **glitchtip is fully inverted**, the 5 connections rollout overrides moved
into their apps, and 48 workflows moved to the app that owns them — ownership decided by *caller
analysis*, not name-matching (`Batch Upsert` looked shared until the other indox workflows left,
at which point indox was its only caller).

The remaining 4 workflows are genuine stdlib (`Settings`, `Error Handler`, `Batch API GSheet
Cache`, the Sheets MCP server) that merely *mention* an indox redis-key namespace in their
content — coupling worth removing, but not ownership.

### What the remaining 10 config files need

All of them are registries a base app reads from **inside its own image**, so inverting them needs
one shared mechanism: the compiler emits the registry into `.generated/`, and the base app mounts
it. That is a genuine change to rendered config (three new mounts on console, connections and
authentik), so it must be applied to **both** sides of G1 as an intentional shared change — the
same way the n8n IPv4 healthcheck and the five auth gates were.

| File | Registry | Derive from |
|---|---|---|
| `console/modules.yaml` | module tiles | `routing[].module{}` |
| `console/app.py` `APP_BASES` | `/a/<alias>/` proxy table | `routing[]` + an `alias` |
| `authentik/blueprints/deployment-apps.yaml` | SSO providers + applications | `routing[].auth == "sso"` |
| `connections/manifests/consumers.yaml` | per-service secret requirements | each app's `connections[]` |
| `connections/providers/*.yaml` | `consumers:` back-links | the same |
| `any-concurrency`, `console`, `connections` compose | `WA_CONTAINER`, `APITOOLS_URL`, `WA_BOT_URL` | a `contributes{}` block |
| `n8n/blueprint.yml` | active-workflow list | the staged union |

## `bbox ui-map` runs on Linux, Windows and macOS

It was marked "cannot run on Windows (MSYS paths)" for weeks. That was never tested and was
wrong. Verified end to end on Windows, stable tree, zero tracebacks / zero `command not found` /
zero drift:

```
UI inventory        96 views across 18 apps (86 first-party, 10 third-party)
capture             307s, 4 shards
merged              78 view results (78 captured), coverage for 9 apps
output              ci-artifacts/ui-map/ui-map.png
```

Four portability bugs stood between it and that result, every one failing on exactly one OS:

| Bug | Fix |
|---|---|
| host paths to native python/docker (`/c/…` → `C:\c\…`) | `npath()` — `cygpath -m`, identity elsewhere |
| Hebrew/bidi output → `UnicodeEncodeError` | `PYTHONIOENCODING=utf-8` in `lib.sh` |
| `nproc` absent on macOS → 12-core Mac sized to `ci-small` | `ncores()` |
| `timeout` is `gtimeout` on macOS | `timeout_bin()`, degrades to uncapped |

Gate **G10** (`portability-lint.py`) enforces the first two classes and is self-tested against
the real bugs. It caught a fresh instance in `scripts/first-party-images` within an hour of
existing.

Two swallowed failures surfaced alongside them, and both are the reason this went unnoticed:
`die` was **never defined**, so `|| die "UI inventory has drift"` printed `die: command not
found` and carried on; and the success line counted `ls *.png`, so a run whose shards all failed
still reported the *previous* run's screenshots and exited 0. Both fixed.
