# Platform OS — target architecture and the plan to release

> **MEASURED STATE** (re-measure with `bash scripts/ci/gates.sh` and `bbox status`; do not trust this
> block if it disagrees with them):
>
> | | |
> |---|---|
> | gates | **23/23 PASS + 4 self-tests**; re-run directly 2026-07-31, same result |
> | layer-0 app references | **17** (was 67) — G31's DEBT list is **EMPTY**: layer 0 owes nothing |
> | hooks | **42** files, **0 non-executable in git**; `prepare`×5, `onboard`×3, `verify`×4 |
> | `bbox` | **717** lines; no `case` per app, no app verb in its help (both generated) |
> | INDOX schema from zero | **FIXED, and now proven on every `bbox run`** — see G1 below |
> | verification debt (G5.1) | **CLOSED 2026-07-31** — 50 CONFIRMED · 48 REFUTED · 2 DEFERRED · 2 MOOT · 2 speculative left open |
> | stack (today's baseline) | P0–P4 green (38/38 Up, gates 23/23+4, ci-verify 19/19); P5 not concluded as of last read — see G0 |
> | archives | `attic/` **0** (was 293) · `legacy/` **0 tracked, 0 non-dot entries** — also closes G6.1 |
> | python | 285/285 first-party files parse (not re-checked today) |
>
> **Release blockers remaining: none known locally**, as of 2026-07-31 — **G1.1/E1 (no INDOX schema
> from zero) is now fixed and verified**, closing what was the only bold release blocker; see §G1/§E.
> The one unproven surface is **G3.3 (VPS parity)** — everything here was verified on WSL, where
> `/mnt/c` reports every file as 755 and does not preserve symlinks. 42 hooks now depend on a mode
> only Debian enforces, and `run_app_hooks` skips a non-executable hook *silently*. Staging is the
> only thing that can answer it.
>
> **Two items are explicitly NOT done and must not be read as covered by anything above:** the
> `src/`+`workspace/`+`data/` repo restructure (**not started** — a target layout exists only as an
> unimplemented sketch) and **private-mail (inbound/outbound), unverified since 2026-07-28** — two
> full resets have happened since, and nothing in this session touched or re-checked it. See new §G7.
>
> Separately, awaiting an operator decision: **`.env.ex` ships the n8n encryption key, the n8n owner
> password and the authentik SSO admin password, all identical to live** (G5.2). Deliberate, and
> load-bearing for credential restore — so it is a product decision, not a bug fix.

The architecture this platform is converging on, and every task left to reach a release.
Findings and phase history: [platform-os-consolidation.md](platform-os-consolidation.md).

---

## Part 1 — The architecture

### Layers, and the one-way arrow

```
layer 0   bbox, scripts/            the CLI. Orchestrates. Knows NO app by name.
layer 1   platform/manager/         the compiler + installer. Owns manifests, state, catalog.
          platform-base/app-management/   the control plane. Owns the app lifecycle.
layer 2   platform-base/<id>/       core apps every deployment needs.
layer 3   apps/<id>/                installable apps.

apps/ ──uses──▶ platform-base/       platform-base/ ──never names──▶ apps/
                                     layer 0 ──never names──▶ either
```

Gate **G9** enforces the arrow for `platform-base/`. Gate **G31** enforces it for layer 0 — which
includes `scripts/onboarding`, historically the single largest concentration of app knowledge.

### One owner per fact

| Fact | Owner | Everyone else |
|---|---|---|
| What an app IS | `apps/<id>/app.json` | read it; never restate it |
| Desired state format | `reconcile.set_disposition()` / `disposition()` | call it — never regex the file |
| Which apps run | `reconcile.enabled_ids()` / `enabled-apps` | ask; never glob |
| Compiling manifests → compose | `reconcile.render` | shell to it |
| Which compose files are the stack | `reconcile.compose_files()` | never hardcode a list |
| Which images are built from source | services with a `build:` in the compiled compose | never a hand-kept name list |
| Creating/starting containers | compose, via `scripts/dc` | never docker-py, never bare `docker compose` |
| The compose binary | `BBOX_COMPOSE` | never `docker compose` (that is a plugin search) |
| The engine address | `BBOX_DOCKER_SOCK` | never `/var/run/docker.sock` |
| Repo path the daemon sees | `BBOX_REPO_HOST` | mount at the same path; never translate |
| The shared network | `ensure_network` (lib.sh) | never open-code inspect-or-create |
| An app's bootstrap | `<root>/<id>/hooks/prepare` | the CLI invokes generically |
| An app's first-run seeding | `<root>/<id>/hooks/onboard` | the CLI invokes generically |
| An app's automations | `blueprints.n8n` + `n8n/hooks/{push,unpush,present}` | one implementation, many callers |
| App lifecycle (enable/disable/install/uninstall) | `app-management` | the CLI delegates |
| Desired → actual convergence | `app-management.reconcile_once()` | — |
| Scratch paths | `BBOX_TMP` | never a fixed `/tmp` path |

### The hook mechanism

An app declares what it needs by *having a file*. `run_app_hooks <verb>` (in `scripts/lib.sh`, so
both `bbox run` and `scripts/onboarding` share one implementation) walks the **enabled** apps from
the compiler and runs `<root>/<id>/hooks/<verb>` where it exists.

| Verb | When | Example |
|---|---|---|
| `prepare` | before containers start (`bbox run`) | traefik's acme.json 0600; portainer's admin secret |
| `onboard` | after the stack is up and n8n is restored (`bbox onboarding`) | INDOX reset+seed; browser42 state restore |

Two properties matter and both were once broken:
1. **Enabled-only.** A disabled app's hook must not run. `ensure_portainer_password` minted a secret
   for an app that ships disabled; onboarding restored browser42 state for the same reason.
2. **Executable.** `run_app_hooks` skips a non-executable file *silently*. See invariant 8.

### Invariants a release must hold

1. **bbox names no app.** Layer 0 contains zero layer-3 identifiers in code position. → **G31**
2. **One writer** of `platform.state.yaml`; one parser of a disposition. → **G12 (task B2)**
3. **Every** container is created by compose with the compiled file list. → **G7**
4. **No Docker Desktop** in engine *or* toolchain. → **G13 (task B3)**
5. **A fresh clone reaches a healthy stack** with one command and no manual step. → **G11**, D1
6. **Convergence is honest**: it verifies repairs, and never reports unverified success.
7. **Every invariant above has a gate.** An invariant without a gate is a hope.
8. **A hook that exists, runs.** Every `hooks/*` file is mode 100755 *in git*. → **G31**

---

## Part 2 — What landed, and the class of bug it exposed

### The exec-bit finding — why it matters beyond the seven files

Phase 3 moved app bootstraps out of bbox into `<id>/hooks/prepare`. Seven hook files were committed
**100644**. `run_app_hooks` tests `[ -x ]`, so those hooks never ran — including the traefik and
portainer `prepare` hooks written specifically to replace `ensure_acme_perms` and
`ensure_portainer_password`. The logic left bbox and landed somewhere inert. traefik's `acme.json`
consequently never received its 0600, which is the exact failure the original code existed to
prevent: traefik silently skips the ACME resolver and serves its self-signed default cert.

It hid because **all of this work was done on WSL over `/mnt/c`**, where every file stats as 755.
`[ -x ]` is true on the dev machine and false on the Debian VPS, which checks out git's mode.

That is not a one-off. It is the shape of **D2**: a whole session's changes validated on the one
platform whose filesystem semantics differ from production. G31 now asks *git* for the mode rather
than the filesystem, and the same skepticism should be applied to every remaining path assumption
before deploy.

### Done this session

| # | Task | Proof |
|---|---|---|
| **B1** | **G31** — layer 0 may not name a layer-3 app (`scripts/refactor/layer0-lint.py`) | 7/7 self-test; wired into `ci-verify.yml` + `fresh-machine-check.sh`; row in `GATES.md` |
| **A3** | INDOX workflow id out of the CLI → `apps/indox/hooks/reset` | no n8n id in `bbox`; `--help` renders; dead `RESET_WF` in demo.py removed |
| **A4** | `CCR_FIRSTPARTY_BUILD` derived from the compiled compose | derived set = old 13 **+ `app-management`**, which the hand list had wrongly omitted |
| **A5** | One creator of `traefik-network` → `ensure_network` in lib.sh | onboarding's open-coded copy gone |
| **A9** | browser42's dump conventions → `apps/browser42/hooks/state` | `bbox b42 list` output identical (3 dumps, correct ★) |
| — | `scripts/onboarding` reduced to orchestration | −55 lines: browser42 block, INDOX block, and a *third* copy of the n8n login-and-run dance |
| — | `say` added to `lib.sh` | it lived only in `bbox` and `onboarding`; any hook sourcing the library died with `say: command not found` |
| — | all 31 hooks set 100755 in git | G31 fails on a planted 644 (verified) |
| **C1** | `routing[].auth` enum-validated — **was a real unauthenticated-route hole** | every route-opening input now rejected at compile time (below) |
| **A1** | One parser of a disposition — three inline copies in `app.py` → `reconcile.disposition()` | the disagreement is reproduced and closed (below) |

**C1 in detail.** The schema declared `enum: [sso, none, basic]`, but `validate()` only ever
hardcoded two enum checks (`kind`, `use[].strength`) — every enum nested inside an array or a
sub-object was decorative. The emitter attaches authentik's forwardAuth on an exact `auth == "sso"`,
so `"SSO"`, `"ssoo"`, `"sso "`, `""`, and an explicit `null` all compiled cleanly and published the
app with **no authentication**, on a healthy-looking stack. `basic` was worse: schema-legal,
implemented nowhere, and therefore also open. Fixed three ways — `_check_enums()` validates every
declared enum recursively (which closed `module.group` too), `basic` is gone from the schema until a
middleware exists, and the emitter raises rather than emitting a route whose auth mode it does not
implement. Verified: 6 route-opening inputs rejected, `sso`/`none` still accepted, tree clean.

**A1 in detail.** Three inline copies, all disagreeing with the compiler in the same direction —
they over-reported enabled:

| entry | `reconcile` (what RUNS) | old `app.py` (what the UI SHOWED) |
|---|---|---|
| app absent from state | disabled | **enabled** |
| `{}` present but empty | disabled | **enabled** |

`enabled_ids()` only iterates apps present in state, so an app the compiler would never start showed
as enabled in the apps screen. All three now call `reconcile.disposition()`, imported in the same
guarded block as `appinstall`/`catalog` so a broken import degrades the store instead of killing it.
There is deliberately no local fallback parser — a fallback is how the second copy appeared.

Notes on behaviour deliberately changed, not preserved:
- **Onboarding's demo inject** now goes through `hooks/demo run welcome` instead of firing the inject
  workflow bare. The bare trigger placed documents with **no** companies and **no**
  `ai_extraction_cache` seeded, so every demo doc took a live AI extraction on a system whose API
  keys are usually still `PLACEHOLDER` at onboarding time. The prompt's "30×5" was stale besides —
  `welcome` is 5 documents, one per sync.
- **browser42 state restore** now runs only when browser42 is actually enabled, because
  `run_app_hooks` walks the compiler's enabled set. On a *default* deployment browser42 ships
  disabled, so onboarding no longer restores state for an app with no containers and then warns
  about it. (On this laptop browser42 is explicitly `{state: enabled}` in `platform.state.yaml`, so
  the hook does fire here — the change is conditionality, not removal.)

> **`enabled-apps` is the resolved CLOSURE, not the declared disposition.** It includes apps pulled
> in as capability providers — supabase appears because indox uses it as a data backend, even though
> supabase itself is `{enabled: false}`. The catalog API's `enabled` flag is the *declared*
> disposition, so the two lists legitimately differ (21 vs 20 here). Both are correct; they answer
> different questions. Anything that must act on "what will be running" — `run_app_hooks` included —
> wants the closure.
- **`demo.py --reset` help text** claimed it ran "INDOX Reset + Setup". It has always called the
  local `light_reset()` (truncate + clear locks). The text now says what the code does.

---

## Part 3 — Tasks to release

**A** closes ownership · **B** makes it permanent · **C** verifies what was never checked · **D** ships.

### A — Finish the ownership consolidation

**A2. `perf-profile` runs before supabase migrates** *(reproduced twice on fresh DBs)*
`settings upsert (8 keys): ERROR: relation "settings" does not exist` — 8 settings silently dropped
on every from-scratch install.
*Accept:* a from-zero `bbox onboarding` produces zero such errors; the 8 keys are in `settings`.

**A6. n8n workers' undeclared image dependency**
`n8n-worker-1/2` declare `image: binaos/n8n:${N8N_VERSION}` with no `build:`, relying on the `n8n`
service to produce that tag — which is why they error while others only warn on a cold engine.
*Accept:* a from-zero build produces no `pull access denied … Error` for the workers.

**A7. `N8N_CONTAINER` / `PG_CONTAINER` out of the shared library** — *downgraded after measuring it*
`lib.sh` hardcodes `n8n-${DN}` and `n8n-postgres-${DN}` and exports both, plus `pgq()`.

Measured before acting: **84 occurrences across 18 files**. Almost all are legitimate — 63 are inside
`apps/n8n/hooks/*`, which is n8n's *own* tooling naming itself, and the rest are
`apps/indox/hooks/*`, which is layer 3 consuming layer 2 in the direction the arrow allows. And n8n
and postgres are **layer 2**, not layer 3: core services present in every deployment. So this is
layer 0 depending on layer 2 — untidy, not an inversion, which is why G31 does not flag it and why
it is *not* the same class of bug as A3/A4/A9.

Correct end state is still that the three live in `apps/n8n/` and lib.sh drops them. But it
touches 18 files' worth of call sites, and `bbox n8n push/pull/verify` cannot be meaningfully tested
without exercising a live n8n — so this is deliberately **not** bundled with the fast consolidation
passes. Sequence it with D2/D3, where a full baseline run actually proves it.
*Accept:* `lib.sh` exports no service-specific container name; `bbox n8n *` and `pgq()` behave
identically across a full `bbox baseline`.

**A8. One answer to "which compose files are the stack"**
`packaging/make-runtime-compose.py` hardcodes a three-file list, duplicating
`reconcile.compose_files()` — and it produces the file the **shipped artifact** boots from.
*Accept:* the packaging compiler calls the compiler; a built bundle boots.

### B — Make it permanent (gates)

**B2. `G32` — one writer of `platform.state.yaml`**
Any `re.sub`/`sed` targeting the state file outside `reconcile.set_disposition()` is a finding.
*Accept:* planting a second writer fails; the tree passes.

**B3. `G33` — no engine or compose bypass**
Bare `docker compose` (not `${BBOX_COMPOSE}`), and `/var/run/docker.sock` as a *host-side* bind
source outside the `${BBOX_DOCKER_SOCK}` default. (G7 already covers the file-list half.)
*Accept:* planting either fails; the tree passes.

**B4. Gates run in CI**
G31 is wired. Confirm G7/G9/G10/G11 and the new G32–G33 are all actually on a lane, not merely
runnable — and that **G1 is resolved** (`GATES.md` records it as wired to nothing with a stale
golden, while several documents still assert the invariant it was supposed to guarantee).
*Accept:* a PR with a planted violation goes red; `GATES.md` has no "wired to nothing" row.

### C — Verify what was never verified

**DONE 2026-07-31.** The two reviews were capped: **48 of 108** architecture claims and **44 of 139**
leak claims had been checked when this section was written. All of it is now drained: every claim ID
in `platform-architecture-review.md` (A1–A6, F1–F11, C1–C22, R1–R25) and the separate leak audit
(L1–L12) has a verdict in **[review-claims-verdicts.md](review-claims-verdicts.md)**, reproduced
against the real tree/CI invocations, not argued. **Tally (machine-counted from the file, not
hand-tallied): 50 CONFIRMED · 48 REFUTED · 2 DEFERRED (both need the live VPS/stack) · 2 MOOT
(overtaken by the archive retirement) · 2 speculative recommendations left open by design.** See §G5.1.

**C1. `routing[].auth` not enum-validated** — **DONE, and it was real.** See Part 2. The release
blocker is cleared; what remains is a **rebuild** so the running control plane carries the fix, and a
check that no deployed manifest anywhere in the estate currently uses a now-rejected value.

**C2. Credentials committed twice**, the second copy documented as gitignored but actually tracked.
**CONFIRMED** (`review-claims-verdicts.md` V2): 24 files tracked at
`apps/n8n/.credentials-state/*.json`, matching the 24 at `.../credentials/*.json`; the
`.gitignore` rule that should hide the state copy targets the pre-refactor `production/n8n/...` path
and matches nothing. Already escalated as **G5.2** (the encryption key is committed too, and decrypts
these) — operator decision recorded there: keep, do not rotate, closed.

**C3. Drain the remaining claims.** **DONE.** Every claim is now CONFIRMED, REFUTED, or explicitly
deferred with a reason — see `review-claims-verdicts.md`'s "G5.1 — CLOSED" section for the full tally
and the two results worth carrying forward: **A4** (a rendered config with every `middlewares=` line
stripped still passes the auth gate — nothing proves auth actually attaches to a route) and **V11/R12**
(the credential-broker migration is 1 of 6 apps done, `CONN_BROKER_MODE` still `warn` not `enforce`).

### E — What the fresh baseline found *(2026-07-30 run; E1 was the blocker — FIXED 2026-07-31)*

A full destroy → rebuild → `bbox run` → `bbox onboarding` from an empty engine, 2026-07-30.
**Green:** 22/22 gates, 37/38 containers (2 one-shot inits exited 0), 82 workflows / 81 active,
10 gated hosts 302, 3 ungated 200, 0 traefik middleware rejections, gallery apps stayed disabled.

**E1. A from-zero onboarding produces a deployment with NO INDOX schema.** *(was the release
blocker — now FIXED, see below)* After `bbox onboarding` completed and reported success, supabase
held **10 public tables — all `chat_*` and `drive_*`**, created by
`apps/n8n/schema/01_platform.sql`. Zero INDOX tables. `apps/indox/blueprint/fixtures/schema.sql`
(which defines the INDOX model *and* `public.settings`) was never applied, and the scheduled INDOX
workflows then failed continuously — **40 errors to 23 successes** within the first minutes, two
workflows erroring on every 30s tick.

Onboarding printed *"Reset + Setup triggered"* and moved on. Triggering is not completing: the call
returns as soon as n8n accepts the execution. This is the same class the INDOX phases were spent
eliminating — reporting an action as if it were an outcome.

**FIXED 2026-07-31.** Two things landed together and close this end to end. (1) `bbox run` gained
`ensure_converged()` — before onboarding hooks run, it calls the control plane's `POST
/api/reconcile` (reached generically via `platform/manager/reconcile.py capability-provider
--capability control-plane`, never a hardcoded app id — a real G31 violation was caught and fixed
during this work) so every enabled app's n8n blueprint is actually imported, not just imported once
at the moment the app was enabled. (2) The platform schema apply moved out of a separate
`hooks/onboard` and into `apps/n8n/hooks/push` itself, so **any** path that pushes the
blueprint (not only the interactive onboarding flow) guarantees `public.touch_updated_at()` and the
rest of `01_platform.sql` exist before an app's own onboard hook runs. `apps/indox/hooks/onboard`
still waits for `public.settings` and fails loud if it doesn't appear — but now it does appear.
Verified directly in a live baseline run (2026-07-31,
`C:\...\scratchpad\baseline-run.log`): `IndoxResetFull01 started (execution 6)` →
`[indox] Reset + Setup complete — INDOX schema present`, immediately followed by
`✓ P3 app-onboarding — every enabled app's onboard hook succeeded (schema + first-run seeding)` and
`✓ P4 ci-verify — all 19 applicable checks green`. Both `apps/indox/hooks/onboard` and
`apps/browser42/hooks/onboard` are now idempotent/self-checking (a schema-presence gate and an
empty-profile gate respectively), so they are safe to run on **every** `bbox run`, not just first-run
— closing the "bbox first run needs onboarding" gap directly.
*Accept — MET:* a from-zero `bbox onboarding`/`bbox run` ends with the INDOX schema present (verified
above). Whether the *scheduled workflows* still error post-fix was not independently re-measured this
session — the P4 ci-verify pass (19/19) is the strongest available proxy, but if a fresh count of
n8n execution successes/failures matters, re-check it explicitly.

**E2. `perf-profile`'s settings upsert has no target.** **Resolved as dead code, not fixed as a
target-restoration** — see `review-claims-verdicts.md` D12: `scripts/perf-profile-apply` now records
that `public.settings` held zero `perf%` rows and had been silently dead since commit `16b92ecd`;
`--settings-only` is kept only as an accepted no-op because `scripts/onboarding` still passes it, and
delivery is via `perf-manifest.json` node substitution instead. This decision does not depend on E1
being fixed — it was already made independently of schema presence. **G1.2 below can close.**

**E3. The baseline's own route check was wrong.** It curled `<host>.localhost` from inside WSL,
where those names do not resolve — every host read `000`, which looks identical to a total routing
failure. Re-tested with `-H "Host: …" http://127.0.0.1/`: all correct. A verification step that
cannot distinguish "broken" from "I could not look" is worse than no step.
*Accept:* `scripts/baseline.sh` uses the Host-header form, so the check works from any shell.

### F — The CLI must be generically extensible *(the deep scan)*

G31 was too permissive in two ways, and a full scan of layer 0 against **every** app id — layer 1, 2
and 3, no heredoc exemption — found **67 non-dispatch references across 11 apps**:

| app | layer | refs | dispatch | logic/help |
|---|---|---|---|---|
| indox | 3 | 26 | 6 | **20** |
| browser42 | 3 | 14 | 1 | **13** |
| glitchtip | 2 | 13 | 1 | **12** |
| notifications | 2 | 6 | 0 | 6 |
| any-concurrency | 2 | 6 | 0 | 6 |
| authentik | 1 | 5 | 0 | 5 |
| apitools, redis, postgres, traefik, supabase | — | 5 | 0 | 5 |

**The two blind spots.** (1) G31's token set was *layer-3 only*, so `ensure_glitchtip_provisioned()`
— a 19-line function in `bbox`, plus a dedicated four-service `dc up --wait` phase, plus a fallback
re-run — never tripped it. The layering rule was being enforced for installable apps and not for
core ones, which is precisely the blind spot G9 had before G31 existed. (2) G31 exempted **heredoc
bodies wholesale**, so `bbox help` hardcoding `indox reset|demo|sync|test|extract-gate` and
`b42 dump|load|list|info` passed. That exemption was wrong: help text enumerating one app's verbs
means *adding an app requires editing the CLI*, which is the defect itself.

**F1. `ensure_glitchtip_provisioned` → `platform-base/glitchtip/hooks/prepare`** — **DONE.**
`bbox` shrank by 1,503 characters and now contains zero glitchtip code (comments only); glitchtip
went 13 refs → 2. *Verified nothing was lost:* the hook provisions all 11 `*_SENTRY_DSN` values plus
`GLITCHTIP_API_TOKEN`, `.env` is byte-identical after a second run (idempotent), and `notifications`
— the consumer that cannot be healthy without an org — is healthy. An app may start the services it
owns; what it may not do is have the CLI start them on its behalf.

**F2. Generic top-level dispatch** — **DONE.** `bbox <id|alias> <verb> [args]` resolves
`<root>/<id>/hooks/<verb>` for every app, trying `""`, `.sh`, `.py`, `.mjs`. The `indox)` and `b42)`
case blocks are gone (**3,562 characters**). New schema field `cli` (the manifest had
`additionalProperties: false`, so this is a declared contract, not a convention):

- `cli.alias` — an extra CLI token. browser42 declares `b42`. bbox invents nothing.
- `cli.fallback` — a hook that receives the verb as its first argument when no `hooks/<verb>` exists.
  browser42 declares `state`, so `bbox b42 dump|load|list|info` all reach `hooks/state` **without a
  file of boilerplate per verb**.

Three indox implementations were living in `scripts/` and moved with it: `extract-gate.sh`,
`sync-v3-seed-ledger.py`, `sync-v3-coverage.py` → `apps/indox/hooks/`. Plus a new `hooks/sync`
owning the sync verb tree that used to be a nested `case` in bbox.

**F3. Generated help** — **DONE.** `bbox help` builds its app section by scanning
`<root>/<id>/hooks/*` and reading each hook's `#:` summary. 1,404 characters of hardcoded app help
deleted. Add a hook → it appears; delete an app → its help goes with it.

*Verified:* an acceptance test resolves **22/22** documented spellings (every one the usage scan
found in CI, docs and the hooks themselves) to a real file, without executing them — `bbox indox
sync`, `bbox b42 dump`, `bbox app indox doc-trace`, `bbox n8n push`, all of them. Unknown verbs fail
listing what exists; unknown apps fail cleanly. **bbox is now 720 lines.**

Three defects the gates caught during this work, each a real one:
- `extract-gate` sourced `${SELF_DIR}/lib.sh`, correct in `scripts/` and wrong in `hooks/` — it
  broke instantly and loudly, which is the good case.
- The two moved `.py` files kept mode 644 through `git mv`, so **G31's exec-bit check fired** — the
  same class as the seven hooks, caught automatically this time instead of by accident.
- **G10 caught my own new code**: two inline `python3` calls received `${REPO_ROOT}` unconverted,
  which mis-resolves on Windows. Wrapped in `npath`.

**F4. Re-tighten G31** once F2/F3 land: drop the blanket heredoc exemption (help is generated, so a
literal app verb in a heredoc is a real finding again), and extend the token set to layers 1–2 so
the glitchtip class cannot recur.
*Accept:* planting `ensure_<app>_provisioned()` in bbox fails; planting an app verb in the help
heredoc fails.

**F5. The remaining 57.** `scripts/baseline.sh` holds 28 (browser42 exclusion, glitchtip token
assertion, supabase JWT check) and `bbox` 38→ the rest. Each needs the same treatment: the assertion
belongs to the app that owns the fact.

### G — Everything still open, in the order it should be done

Every task below is either a *known defect* or a *stated invariant with no gate*. Nothing here is
speculative. **Bold = blocks release.**

#### G0 — first, because everything else is judged against it
**G0.1 — `bbox baseline` from zero, green end to end.** The 2026-07-30 run was green on 22/22 gates,
37/38 containers and 82 workflows, but **E1** made the result untrustworthy for INDOX — now fixed
(see §E). **Re-run in progress 2026-07-31**, evidence at
`C:\Users\user\AppData\Local\Temp\claude\...\scratchpad\baseline-run.log`: **P0 through P4 are all
green** — `P0 env-consistency` ✓, `P0 preflight` ✓, `P0b gates: 23/23 PASS (+4 self-tests)` ✓,
`P1 reset` ✓, `P2 build` ✓, `P3 bring-up — 38/38 containers Up; no unhealthy/crashed` ✓ (one transient
`authentik-worker` unhealthy self-healed via the existing outpost-restart retry), `P3 app-onboarding
— every enabled app's onboard hook succeeded` ✓, `P4 ci-verify — all 19 applicable checks green` ✓.
**As of the last read, the log stops at the `P5 functional suites (bbox indox test all)` header with
no further output — P5 onward had not concluded (or the run had stalled) at that point.** G0.1 is
therefore **not yet a closed proof**: everything the onboarding fix (G1.1) needed to prove is proven,
but the full baseline (P5+, ui-map, scorecard) is unconfirmed pending that log's completion. Do not
mark G0 done on this evidence alone — re-check the log or re-run.

#### G1 — the release blockers
**G1.1 (= E1). A from-zero onboarding creates no INDOX schema.** **FIXED AND VERIFIED 2026-07-31.**
See §E for the full mechanism (`ensure_converged` + schema-apply folded into
`apps/n8n/hooks/push` + idempotent onboard hooks) and the baseline-log evidence. **No longer
blocks release.**
**G1.2 (= E2). Decide `perf-profile`'s 8 settings.** **DONE** — decided as dead code, not
target-restoration; see §E and `review-claims-verdicts.md` D12. `--settings-only` stays as an
accepted no-op (`scripts/onboarding` still passes it); delivery is via `perf-manifest.json` node
substitution. **Closed, independent of G1.1.**
**G1.3. `bbox baseline` route check.** **DONE** — confirmed fixed via `review-claims-verdicts.md`
V10: no `curl` of a `.localhost` name survives anywhere in `scripts/`, `.github/` or `bbox`; every
HTTP assertion in `scripts/ci-verify.sh` now uses the `Host:` header form against the loopback edge
(e.g. `curl ... -H "Host: n8n.localhost" http://127.0.0.1/...`). The remaining `.localhost` URLs are
Playwright navigations, a different (correct) mechanism.

**G1 is fully closed as of 2026-07-31.** All three sub-items resolved; this was the section holding
the sole bold release blocker.

#### G2 — finish the layering (36 refs left, was 67)
**G2.1 (= F5).** `scripts/baseline.sh` holds 28 — browser42 exclusion, glitchtip token assertion,
supabase JWT check. Each assertion belongs to the app that owns the fact; the mechanism (a `verify`
hook per app, invoked by `run_app_hooks`) already exists.
**G2.2 (= F4). Re-tighten G31**, which still has both blind spots that hid this class: its token set
is layer-3 only (glitchtip was invisible), and it exempts heredocs wholesale (the help text was
invisible). Both are now moot in fact but not in enforcement — **the gate cannot yet catch what was
just fixed by hand.**
**G2.3.** authentik's cold-start special-casing in `bbox run` (5 refs) — the last app-specific
bring-up logic in layer 0.

#### G3 — cross-platform assumptions (the D2 class)
**G3.1. `digital-office/sim/build.mjs` cannot run under WSL** — Windows rollup binaries in
`node_modules`. Same family as the exec-bit bug. **Still open — confirmed 2026-07-31.** No commit
touches `build.mjs`, its `package.json`, or `node_modules` since this was found (§"Found, not
caused" below); `digital-office/sim/node_modules` isn't installed in this checkout so the failure
wasn't re-reproduced, but nothing records a fix either. Note for future readers: this item is
**not** "prove `bbox` runs on Windows" — that broader claim is G3.3/D2 (VPS parity is the untested
half; the WSL-backed Windows path itself has been exercised repeatedly, see
[running-on-wsl.md](running-on-wsl.md)). G3.1 is this one specific defect and stays open until it's
fixed.
**G3.2. Audit for the rest of the class**: file modes, `node_modules` platform binaries, path
separators, case sensitivity. The exec-bit bug and this one were both found by accident.
**G3.3 (= D2). VPS parity.** Still the largest untested surface; everything is proven on WSL only.

#### G4 — gates for stated-but-unenforced invariants
~~**G4.1. G1 (compose-equiv) is wired to nothing**~~ **DONE 2026-07-30 — deleted, and all six
documents amended.** Re-goldening was tried first: the current render produces **413 undeclared
diffs** against the golden, none of them relocation violations (all 23 declared old paths are gone
from the tree), and the render is **not reproducible** — two renders of the same commit differ by
326 lines across 50 keys because `scripts/ci-env.sh` mints fresh secrets into every one, so no
committed golden can match a CI run. Byte-equivalence is the wrong shape for output the compiler
regenerates on every app add/remove; the render's properties are gated instead (G0/G6 on the
rendered file, G15/G18/G21/G24/G26/G30 on its inputs). Evidence table:
`scripts/refactor/GATES.md`, "Why G1 was deleted".
**G4.2. A gate for references *into* `legacy/`.** Two are declared in `legacy/README.md`; a third
added silently would be exactly the `attic/` situation again.
~~**G4.3. G16 cannot run** — `pytest` is absent from the app-management image.~~ **WITHDRAWN — my
error.** G16 runs on the CI *runner*, not in the container: `ci-verify.yml` does
`bash scripts/ci/pip-ensure.sh pytest && python3 -m pytest platform-base/app-management/test_conditions.py`.
I had tried it inside the container and reported a defect that does not exist. Verified on the host:
**21 passed in 2.63s** — which also independently confirms the A1 disposition refactor did not
break the control plane.

#### G5 — verification debt
**G5.1 (= C3). CLOSED 2026-07-31.** ~100 review claims were never checked (48/108 architecture,
44/139 leak) as of when this item was written. All are now drained in
**[review-claims-verdicts.md](review-claims-verdicts.md)**: every claim ID in
`platform-architecture-review.md` (A1–A6, F1–F11, C1–C22, R1–R25) and the leak audit (L1–L12) has a
verdict, each reproduced against the real tree or the real CI invocation (not argued). **Grand
tally (machine-counted, not hand-tallied): 50 CONFIRMED · 48 REFUTED · 2 DEFERRED (need the live
VPS/stack) · 2 MOOT (overtaken by the archive retirement) · 2 speculative recommendations left open
by design.** Two results carry real
weight and should not get lost in the close-out: **A4** (a rendered config with every `middlewares=`
line stripped still passes the auth gate — nothing proves auth actually attaches to a route) and
**V11/R12** (credential-broker migration is 1 of 6 apps, `CONN_BROKER_MODE` still `warn`). Both are
tracked as normal recommendations now, not open verification debt.
**G5.2 (= C2). THE ENCRYPTION KEY IS COMMITTED, AND IT DECRYPTS THE TRACKED CREDENTIALS.**
**Confirmed by decryption. Blocks making this repo public. Requires credential rotation — an
operator decision, deliberately not actioned here.**

| | |
|---|---|
| `.env.ex:122` | ships a real 64-hex `N8N_ENCRYPTION_KEY` — not a placeholder. Tracked since the **Initial commit** (`2fc86544`) |
| the live `.env` | uses **that exact key** — identical SHA-256 |
| tracked credential blobs | **24/24 decrypted** with the committed key |
| recovered field names | Gmail `oauthTokenData`; `apiKey`/`host`; Header-Auth `name`/`value` (values were never printed) |
| repo visibility | **private** — unauthenticated GitHub API and web both `404` |

So the AES encryption is real and the key sits beside it in the same repository. For anyone with
read access that is equivalent to plaintext. Exposure is bounded to repo readers plus any fork,
clone, CI artifact or backup they have produced — **but `AGENTS.md` calls `main` "the always-published
state… the public project state"**, and the key is in the *initial* commit, so publishing that branch
publishes the credentials, and deleting the file later would not remove them from history.

**Root cause — corrected on the third pass, and this is the accurate reading.** It is **not** an
accidental leak. It is a **deliberate shared default**, and it is load-bearing:

- `scripts/env-consistency-check.py:70-84` reads `.env.ex`'s `N8N_ENCRYPTION_KEY` on purpose. If your
  `.env` has drifted from it, the check **tells you to copy it back**, because the committed
  blueprint credentials are encrypted under exactly that key.
- `scripts/onboarding` does `cp .env.ex .env` when no `.env` exists.
- So the shipped design is: a fresh clone gets working credentials, including restorable Google
  OAuth. That is a real product property, not an oversight.
- `scripts/ci-env.sh` already mints throwaway values for all 39 sensitive keys, so **CI was never
  exposed**. Only the human path inherits them.

The security problem is therefore **shared default credentials**, the router-with-admin/admin shape:
every deployment made from a plain clone runs with the same n8n owner password, the same authentik
SSO admin password, and the same credential-encryption key. Three secret-named values are identical
between `.env.ex` and the live `.env` (`N8N_ENCRYPTION_KEY`, `N8N_OWNER_PASSWORD`,
`AUTHENTIK_BOOTSTRAP_PASSWORD`); 27 more high-entropy secrets ship in the template and are shared by
every clone that copies it.

**Deliberately NOT fixed here.** Minting per-deployment secrets at install would break the documented
credential-restore path — the committed OAuth credentials would no longer decrypt and every
deployment would need re-authorisation. That is a **product decision** (out-of-the-box working stack
vs per-deployment secrets), not a bug fix, and it belongs to the operator. The options are:
(a) mint per-deployment secrets and accept re-auth on first run, or
(b) keep the shared default and require rotation as a documented step before any real deployment.

This ties directly to **S2** in Part 4 ("secrets are files on a host"): it is the same axis, and it is
the first thing that breaks when this goes from one deployment to many.

## OPERATOR DECISION — 2026-07-30: KEEP THE SHARED SECRETS. DO NOT ROTATE. CLOSED.

The owner's call, made explicitly: the committed values stay, they stay consistent with staging, and
they are deliberately reused so **passwords never change and redeploys never have to deal with it**.
A fixed `.env`-shaped file tracked in the repo is an accepted, wanted property here.

This is a legitimate trade for this deployment, and the conditions that make it reasonable hold
today: the repo is **private** (unauthenticated GitHub API and web both 404), there is one operator,
and the alternative — per-deployment secrets — would break credential restore and force Google OAuth
re-authorisation on every redeploy, which is exactly the friction the decision exists to avoid.

**So: no rotation, no placeholder, no history rewrite. Do not "fix" this.** A future reader who finds
`N8N_ENCRYPTION_KEY`, `N8N_OWNER_PASSWORD` and `AUTHENTIK_BOOTSTRAP_PASSWORD` committed and identical
to live should read this paragraph and leave them alone. Changing them silently breaks redeploys and
credential restore for a property nobody asked for.

**The two conditions that would reopen it**, and only these:
1. **The repo becomes public**, or that branch is pushed anywhere public. `AGENTS.md` describes `main`
   as "the public project state", and the key is in the *initial* commit — deleting the file later
   would not remove it from history.
2. **More than one tenant/operator**, where "every deployment shares one SSO admin password" stops
   being one person's convenience and becomes shared-credential risk across parties (see **S2**).

Neither holds now. Recorded so the reasoning survives the decision.

**How this was nearly missed:** the first check grepped for the key while excluding `*.md` and
`.env.ex` — it excluded the file holding the answer, then reported the absence as evidence, and I
wrote "the key is not committed — good". Twice-wrong: the earlier assessment below is retained as a
record of the error, not as a finding.

*(Superseded assessment, kept deliberately:)*
~~ASSESSED — NOT a security issue. Closed, no change made.~~

The mechanical claim is true: `.gitignore:80` still ignores `production/n8n/.credentials-state/`, the
pre-refactor path, so the 24 files at `apps/n8n/.credentials-state/` are tracked while
`apps/n8n/hooks/pull:26` calls the directory a "git-ignored full-cred cache". Seven
`production/` rules are stale the same way; only two have tracked files behind them (24
credential-state, 109 `apps/indox/storage/extraction-runs/`).

**But it is not an exposure**, and the evidence is what closes it:
- The blobs are `Salted__` — OpenSSL/CryptoJS **AES**, unreadable without `N8N_ENCRYPTION_KEY`.
- That key is **not committed anywhere** — it appears only as an env var reference
  (`${N8N_ENCRYPTION_KEY:?set in .env}`). Secrets are `.env`-driven, which is the design.
- The 25 files under `apps/n8n/credentials/` are the **intentional** encrypted blueprint —
  the old ignore rule was narrow (`*decrypted*.json`, `*.plain.json`) and no such file exists.

**Deliberately not untracked**, beyond it not being a security fix: `.credentials-state` is what lets
OAuth credentials survive a `bbox reset` when the key is unchanged. Removing it from the index during
a live staging parity deploy would destroy credential restore on the VPS — a real regression traded
for a cosmetic one. If the stale `.gitignore` paths are ever refreshed, do it **outside** a deploy
window and expect the cache to stop being shared.

#### G6 — the remaining cleanup
~~**G6.1.** Delete `legacy/n8n` (96 files) if its stale `active_workflows` entries are resolved.~~
**MOOT — confirmed 2026-07-31.** `legacy/n8n` no longer exists at all; `legacy/` itself is now an
empty directory (`git ls-files legacy/` → 0 tracked files). Emptied as part of today's archive
retirement — the `active_workflows` blueprint itself was independently re-verified as correct in
`review-claims-verdicts.md` K7 (81/81 entries resolve, 0 name a nonexistent workflow). Nothing left
to delete.
~~**G6.2.** Delete root `plan.md`.~~ **DONE** — a one-shot session hand-off ("You are a local Claude
Code session…") whose completion is already recorded in
`ai/context/central-business-system-status.md`. Removed.
**G6.3. CLOSED 2026-07-31.** State `digital-office/`'s boundary in one paragraph. Independently
re-verified this session (read in full, not just confirmed present): `CLAUDE.md`'s "What
`digital-office/` is (and is not)" section is exactly one dense paragraph and covers all three
things the item asks for — **what it is** (the design/spec workbench for the platform UI; dev-only,
never shipped, never run by CI; the two offline artifacts it produces and what builds them);
**what depends on it** (`scripts/ui-coverage/live-ui-map.py` and `sim-live-parity.py` hard-require
`sim/ui-map.py`; `pixel-diff.py` reads it for panel captions and degrades gracefully;
`apps/chat/bots/intent.js` and `apps/chat/chatapi/adapters/local.js` cite `sim/mocks/wadmin.js` in
comments as a behavioural contract; `view-profiles.yaml` is shared with the live map); and **what
it is not** (not a layer-3 app — no `app.json`/state entry/compose service/verbs; not shipped — no
Dockerfile or stage-control allowlist names it; not CI-covered — G32 skips it, only G12 touches it
as a syntax check; and explicitly not dead, with the reason why). Nothing further needed.
**G6.4. Still open — confirmed 2026-07-31, evidence expanded.** `issues/` holds 21 tracked files (20
YAML issue records + `schema.json`). Checked every gate that polices directory boundaries —
`legacy-ref-lint.py` (G34), `engine-bypass-lint.py`, `layering-lint.py`, `state-writer-lint.py` —
and all four **deliberately exclude** `issues/` from scope (`legacy-ref-lint.py:47-49,65-67`:
*"`ai/`, `.ci-cd/` and `issues/` [are] notes and plans — prose in .txt/.yaml clothing... they do not
run"*). That exclusion is sound against the attic/legacy failure mode (live code silently reading a
parked tree) — nothing executes against `issues/*.yaml`, so a G34-style reference lint would have
nothing to catch. But the demonstrated risk is a **different** failure mode: issue *content* going
stale against other authoritative docs, with nothing to catch it. K11 re-verified 2026-07-31, and the
two concrete rot instances found are now **fixed** (content, not a gate — see below):
`issues/n8n-encription-rotate.yaml` no longer blankly contradicts the operator decision — it now
states explicitly that `N8N_ENCRYPTION_KEY`/`POSTGRES_PASSWORD`/`N8N_USER_MANAGEMENT_JWT_SECRET`
rotation is declined per that decision, while the **other** items in its table (Anthropic, DeepSeek,
Telegram, Google OAuth, Google Vision — third-party keys leaked via `data/chat.json` and
`gdrive_credentials.json`, unrelated to the n8n/authentik secrets the operator decision covers)
remain genuinely `status: open` and need real off-tree revocation the operator has to do themselves.
The three stale `issues/inbox-highload-throughput.yaml` citations (`api-abstraction-refactor.md:91,102`,
`indox-full-ioc-outline.md:74`) are fixed to the real filename,
`issues/gmail-imap-highload-throughput.yaml` (confirmed via `git log --follow` — no rename ever
happened under the old name, it was simply mistyped three times and never caught).

**The class itself is still unguarded** — nothing stops the next stale reference or the next
content/decision contradiction. Verdict unchanged: a gate is warranted and does not exist. Smallest
fix that would close the class: a lint that (a) flags `issues/*.yaml` filenames cited from
`*.md`/other `issues/*.yaml` that don't resolve to a real path, and (b) cross-checks `status: open`
issues against `OPERATOR DECISION` blocks in this file for matching keywords. Not written — out of
today's scope, left as the actual open item for G6.4.
~~**G6.5.** Move `legacy/feature-validation` to `apps/apitools/hooks/test` — it validates apitools, so
it belongs to apitools, and `legacy/` stops having live consumers.~~ **MOOT — confirmed 2026-07-31,
same evidence as G6.1.** `legacy/` has zero live consumers left because it has zero tracked files
left; `apps/apitools/feature-validation/` already exists and is what CI runs
(`review-claims-verdicts.md` K1, C10/C11).

#### G7 — explicitly open; NOT done today, do not read anything above as covering these
**G7.1. The `src/`+`workspace/`+`data/` repo restructure — NOT STARTED.** A target layout (git root
holds only config; `src/` holds all current top-level source dirs; `workspace/` holds
`digital-office/`→`simulation/`, `issues/`, `ai/context/`→`context/`, `ai/obsidian/`→`obsidian/`) was
sketched during this session as an unimplemented plan only — no file has moved, no `REPO_ROOT`
computation has changed, no PR exists. Twelve categories of call sites would need updating (`.env`
reach, `reconcile.py` state-file paths, `scripts/dc` project-directory, per-app compose `env_file`
relative reaches, CI workflow paths, `.gitignore`, root wrapper scripts, and more) before this is
safe to start. Zero of them are done.
**G7.2. Private mail (inbound/outbound) — UNVERIFIED SINCE 2026-07-28.** Not touched, tested, or
re-checked in this session. Two full stack resets have happened since 2026-07-28, and mail is
exactly the class of thing that regresses silently across a reset (container/volume identity,
Postgres state, DNS/port-25 inbound routing). A prior session flagged a Hostinger port-25 inbound
block as a possible open support ticket with no confirmation it was filed or resolved. **Accept:**
re-run whatever proved inbound/outbound delivery on 2026-07-28 against the current stack, end to end,
before assuming it still works.
**G7.3. Sign-in for an app switched on at runtime — DONE on a `.localhost` office (2026-10-06):
no restart, nothing re-created, the whole install in half a minute; a fresh database comes up with no restart
either. Open for the offices this laptop is not (below).** Measured on hp-laptop.
**What was wrong, and it was ours.** A host declared after the sign-in server had started answered
404 until the server was restarted — a minute of 404/5xx on every gated host, once per app. The
outpost had not failed to hear: it had stopped listening. authentik files the outpost's
applications under `host[:port]`, and its refresh stops the application it held for a host once
per PROVIDER of that host; the second stop of the same application waits for ever (2024.12.5
`internal/outpost/proxyv2/refresh.go` + ttlcache v3.3.0 `Stop()`), so the refresh never returns and
nothing after start-up is ever loaded. The generated blueprint gave it exactly that on every office
whose edge is on `.localhost` port 80 — an app's own provider and its -local twin are one host
there (15 such hosts on this machine) — and, on offices with a port or a domain, whenever a
container with yesterday's environment applied a NEW app's `!Env` host as its `.localhost` default.
Its outpost fetched its providers at start-up, once more five minutes later, and never again, on
each of five starts. (`issues/authentik-bootstrap-unhealthy-for-fifteen-hours-two-sso-hosts-
unserved.yaml` is the same freeze, read at the time as "the websocket fails under load".)
**What changed** (`platform/manager/reconcile.py` `render_authentik`, `platform-base/authentik/`):
1. *One provider for a host.* The outpost is bound to the first provider that names a host (the
   app's own before its twin, across the committed and the generated blueprint); a twin is written
   only where it is another host; an installable app's host is a LITERAL resolved from this office's
   `.env` at compile time.
2. *Nothing of the sign-in app changes when an app is switched on.* Its containers carry only the
   variables the committed blueprint resolves (16 → 6 here) and its database none; and the sentinel
   is no longer re-created on every change of the generated blueprint (its `bbox.bootstrap-inputs`
   digest covers what only IT applies). The worker's apply — seconds after the file changes — is
   the apply.
3. *The probe asks about the hosts of THIS render.* `outpost-ready.py` reads them from the compiled
   blueprint (`context.gated_hosts`) instead of asking the database which hosts the LAST apply
   bound; no token, no API (the non-expiring admin API token it used is deleted by `bootstrap.sh`).
   A 5xx is no longer "served" (a starting server answers 502 for every host — 21 s of it in one
   re-creation, sampled each second).
4. *The hook tries what costs least first* (`hooks/refresh`): ask, and be done; wait 90 s; have the
   sentinel apply every blueprint again (a render nobody applied — minutes, no outage); only then
   restart the server. The sentinel itself no longer exits into a re-apply loop when the outpost is
   slow.
**Measured after** (the numbers behind each line are in the two commits' messages):
| | before (2026-10-05) | after |
|---|---|---|
| a first install through `POST /api/apps/<id>/enable`, to the end of its job | 6 min 15 s | **30 s, 28 s** (two runs) |
| …the new host answers 302 at the edge | after a restart of the server | 28 s after the POST |
| sign-in containers restarted or re-created by it | server (restart), sentinel, worker | **none** |
| every other gated host during it | 404/5xx for 35–65 s | 302 throughout |
| `bbox run` of the sentinel + the control plane | ~5 min | 52 s |
The slow path, live — a host this office declares that the database had lost, the case where nobody
will apply by themselves because the file has not changed (one provider taken off the outpost by
hand): the outpost forgot its host in 4 s; `./bbox authentik refresh` waited its 90 s, had the
sentinel apply again and exited 0 after 235 s (231 s the second time), the host back and the server's
start time unchanged.
And with the WORKER stopped when a host was declared (so nobody applied the render, and 20 s later the
probe already said so — it reads the hosts of the render, not of the last apply): the hook started
the worker, waited its 90 s — the worker's own start did not apply the file in that time — had the
sentinel apply, and exited 0 after 241 s, the host served and the server's start time unchanged.
A FRESH DATABASE, beside the live office (a throwaway authentik on its own network — same images,
this office's blueprints, this checkout's `bootstrap.sh` and probe; removed afterwards): from empty
to "all 27 gated hosts served" in 316 s, the server never restarted, 27 providers bound for 27
hosts and none bound twice, no probe token minted. The sentinel itself started four times in the
first two and a half minutes — authentik's own flows do not exist yet and it exits on the first
refused blueprint (`issues/authentik-bootstrap-races-migrations-on-cold-start.yaml`); it arrives.
**Still open, with what each needs.**
(a) An office with a DOMAIN and one whose edge is on a PORT (the MacBook) — the compiler's cases
are unit-tested (`test_an_office_whose_hosts_differ_from_their_twins_keeps_both`), the run is not
done: pull, `bbox run` (re-creates the four sign-in containers ONCE, their compiled environment
shrank), then one install through the API with the start times of the four compared.
(b) Every object a blueprint saves sends the outpost one update, and it now works through all of
them instead of freezing on the second: about 60 refreshes in the six minutes after a full apply
here, fewer since the sentinel stopped being a second applier of every change. Harmless, wasteful,
authentik's own.
(c) Rows the old blueprint created for the twins stay in the database, bound to nothing.

### D — Release

**D1. Out-of-the-box proof (Windows).** Clone to a *new* directory, `bbox.cmd run`, nothing else.
*Accept:* healthy stack; no manual step; `.env` the only thing carried over.

**D2. VPS parity (Debian). The largest untested surface — and the exec-bit finding is proof the
risk is real, not theoretical.** Everything this session was proven on WSL. Explicitly re-check on
Debian: git file modes (hooks), `BBOX_COMPOSE` at `/usr/libexec/docker/cli-plugins/docker-compose`
(what `debian-install.sh` installs), `BBOX_REPO_HOST` same-path mounting, and case sensitivity.
*Accept:* `bbox run` + `bbox onboarding` green on the VPS or a Debian container before deploy.

**D3. Full baseline.** `bbox baseline` — reset → build → up → ci-verify → indox tests → ui-map →
scorecard, from an empty engine.

**D4. Docs final pass.** `bbox help`, `CLAUDE.md`, `GO-LIVE.md`, `running-on-wsl.md` match reality;
the consolidation doc's "still open" section is empty or accurate.

**D5. Tag and deploy.** Release notes; deploy; verify the estate; keep the rollback path
(`reconcile.py generations` / `rollback`) tested.

---

## Sequencing

```
B1 ✔  A1 ✔  A3 ✔  A4 ✔  A5 ✔  A9 ✔  C1 ✔     landed; the gate keeps them landed
C2 ✔  C3 ✔ (= G5.1)  G1.1 ✔  G1.2 ✔  G1.3 ✔  landed 2026-07-31 — see §C, §E, §G1, §G5.1
A2, A6, A8                                    independent; any order
A7                                            with D2/D3 — only a live baseline proves it
B2, B3, B4                                    after their subjects exist
G0.1                                          re-run in progress 2026-07-31 — P0-P4 green, P5+ TBD
G7.1, G7.2                                    NOT started / NOT re-verified — do before D1/D2
D1, D2 ──▶ D3 ──▶ D4 ──▶ D5
```

**No known release blocker remains locally as of 2026-07-31** — C1 and G1.1 (the two real blockers
found) are both fixed and verified. **D2 (VPS parity) is now the largest remaining unknown**, and the
exec-bit bug is a worked example of exactly how it will fail: something true on WSL and false on
Debian, passing every check because every check ran on WSL. **G7.1/G7.2 are not blockers by prior
definition, but are unstarted/unverified and should be closed or explicitly deferred before D1/D2**,
since a restructure or a mail regression discovered post-deploy is far more expensive than one caught
here.

---

## Part 3b — Verification has one entry point

`bbox baseline` calls itself the full-system proof and ran **none** of the invariant gates, so
"baseline is green" and "the architecture holds" were unrelated claims. The gates ran only in CI —
and CI, `fresh-machine-check.sh` and the baseline each had their own idea of what the gates were.

Now: **`scripts/ci/gates.sh` owns the list.** `bbox baseline` runs it as phase **P0b**, before
anything is brought up (a layering or engine-bypass violation explains a later runtime failure, not
the reverse). `fresh-machine-check.sh` reads the same list. CI still declares one *step* per gate —
a named step is what makes a failure readable — and `gates.sh --verify-ci` asserts that enumeration
still matches, so the two cannot drift.

It found drift immediately: **G22 ran on the `fresh` lane only** and had never run in CI.

Three gates ship a `--self-test` that plants a violation and proves it fails. Running them is part
of running the gates: a gate only ever observed passing has not been tested.

### CI consolidation

| Was | Now |
|---|---|
| A ~18-line cpus-capping Python script inline in **3** workflows, already drifted | `scripts/ci/cap-cpus.py`. ui-map's copy carried a note the other two never got — that the pre-refactor globs had silently matched nothing, making the cap a no-op — which is what three copies costs |
| `SERVICES` derivation duplicated in **3** workflows | `scripts/ci/derive-services.sh` |
| `docker network create traefik-network` open-coded **4×** | `ensure_network` (lib.sh) |
| portainer's password written by hand in **2** CI steps | `apps/portainer/hooks/prepare` — which already handles the empty-`.env`, bind-created-a-directory and trailing-newline cases that neither copy knew |
| One of those steps ran in the `verify` job, where portainer is **disabled** and never starts | deleted |

---

## Part 3c — Cleanup: sharpening everything outside `apps/`

Measured, not guessed — tracked files per top-level directory:

| Dir | Files | Verdict |
|---|---|---|
| `apps/` | 1035 | the product. Not in scope. |
| **`attic/`** | **277** | **Not actually dead** — `.github/workflows/indox-e2e.yml` runs `attic/feature-validation/docker-compose.yml` as a CI step, and `bbox`, `reconcile.py`, glitchtip's blueprint and 3 lint skip-lists all reference it. A live lane depending on the attic is the problem: either feature-validation is a real app (move it to `apps/`) or the lane goes. **Decide, then delete the rest.** |
| `platform-base/` | 258 | core. In scope, already gated. |
| `digital-office/` | 202 | the offline simulation. Legitimate and separate — but it is not layered, not gated, and nothing states its relationship to the live platform except `PORT-PLAN.md`. Give it a stated boundary. |
| `ai/` | 156 | context + the obsidian vault. Mostly fine; several docs describe pre-refactor layouts. |
| `scripts/` | 98 | layer 0. Now gated by G31/G32. |
| **`legacy/`** | **92** | Referenced by exactly two files, both skip-lists (`n8n-node-coverage.py`, `layering-lint.py`). **Deletable** once those two lines go. |
| `.ci-cd/` | 89 | CI artifacts committed back into the repo. Works, but it means every green run mutates the tree. |
| `packaging/` | 43 | the shipped artifact. Real, and just had two bugs fixed (A8). |
| `issues/` | 21 | an issue tracker in git. Fine, but exempted from gates — so it is prose nothing checks. |
| `platform/` | 16 | the compiler + schema. The sharpest part of the tree. |
| `data/`, `ops/` | 19 | runtime state + runner ops. |
| `plan.md` (root) | 1 | stale root-level plan, superseded by this file. |

### Step 1 — DONE: `attic/` removed, `feature-validation` moved to `legacy/`

`attic/` held **293 files across 17 parked projects**. Sixteen had zero inbound references; one —
`feature-validation` — had four, which is why the whole tree was still alive.

| Action | Result |
|---|---|
| `attic/feature-validation` → `legacy/feature-validation` | 117 files |
| `scripts/ci-feature-validation.sh` → `legacy/feature-validation/run-suites.sh` | the harness moved *with* the thing it runs |
| `attic/` (16 other projects) deleted | −176 tracked files, + untracked `__pycache__` |
| 9 files repointed | sim build, ops permission-fixer, 3 lint skip-lists, 2 workflows, AGENTS.md, platform-operating.md |

**The CI lane was repointed, not deleted.** Those suites are the only OCR/extraction coverage the
estate has, and they are advisory (`continue-on-error`, non-gating), so retiring them would delete
real signal to satisfy a tidiness rule. `legacy/README.md` now **declares its two live consumers** in
a table — the indox-e2e lane and `digital-office/sim/build.mjs`, which reads a dashboard html from
there to keep the sim's panel indices stable. The old `attic/README.md` asserted inertness that was
false, and a reader acting on it would have broken CI; declaring the exceptions is the fix.

*Two path bugs found and fixed by the move* — both the same class, both caught because the move made
them fail loudly:
- `run-suites.sh` computed `REPO_ROOT="${SCRIPT_DIR}/.."`, correct in `scripts/`, resolving to
  `legacy/` afterwards. It would not have errored — it would have found no `.env`, fallen back to
  the default deployment name, matched no container, and reported "no feature-validation-api".
- `extract-gate` sourced `${SELF_DIR}/lib.sh` (F2, above).

**Depth is part of a script's contract with its location.** Moving a file changes it, and neither
bug was visible in the diff.

*Verified:* 22/22 gates, 27 manifests valid, compose config valid, stack healthy at 37/38, every
moved path resolves, `REPO_ROOT` reaches the real `.env`.

*Found, not caused:* `digital-office/sim/build.mjs` cannot run under WSL at all — its `node_modules`
holds Windows rollup binaries (`Cannot find module @rollup/rollup-linux-x64-gnu`). It fails while
compiling the INDOX fork, long before the dashboard path. Pre-existing, and the same family as the
exec-bit bug: an assumption true on one platform and false on the other. → task **G3**.

**Superseded since — confirmed 2026-07-31:** `feature-validation` has since moved a second time, out
of `legacy/` into `apps/apitools/feature-validation/` (CI now runs it via `apps/apitools/hooks/test`,
not the `legacy/` path this section describes — `review-claims-verdicts.md` K1). `legacy/` itself is
now empty (0 tracked files); `legacy/README.md` no longer exists — its content moved to
`ai/context/retired-code-and-workflows.md`. This section is kept as the historical record of the
first move; do not read it as describing the current location of `feature-validation`.

### The rest of the cleanup

**Proposed order** — each step is independently verifiable, and none touches `apps/`. **Status as of
2026-07-31, confirmed directly** (`ls attic`, `git ls-files legacy/`, this doc's own G4.1/G6.2
entries):

1. ~~**Decide `attic/feature-validation`.**~~ **DONE.** Moved to `apps/apitools/feature-validation/`,
   which is what CI now runs (`review-claims-verdicts.md` K1); `attic/` (all 17 subdirs) is deleted.
2. ~~**Delete `legacy/`**~~ **DONE in substance.** `legacy/` is now an empty directory — 0 tracked
   files (confirmed `git ls-files legacy/`) — its last content (`README.md`) moved to
   `ai/context/retired-code-and-workflows.md`. See G6.1/G6.5. Only the empty directory entry itself
   is left, `rmdir`-able, cosmetic.
3. ~~**Delete root `plan.md`**~~ **DONE** — recorded above as G6.2.
4. **State `digital-office/`'s boundary** in one paragraph in CLAUDE.md. **Likely already
   satisfied** — `CLAUDE.md` carries a full "What `digital-office/` is (and is not)" section — but
   not independently dated to today's work, so not claimed as newly done here.
5. ~~**Resolve G1**~~ **DONE** — recorded above as G4.1 (deleted 2026-07-30, six documents amended).
6. **Move `issues/` under gate coverage or out of the repo** — still open. See G6.4.

Of the original six steps, only **#6** (`issues/`) and the cosmetic `rmdir legacy/` from #2 remain.

---

## Part 4 — Release ≠ scale. What "billions" actually costs.

Everything in Parts 1–3 makes this OS **correct**: one owner per fact, one way to do each thing, and
a gate behind each claim. That is the precondition for scale, not scale itself. Shipping the same
artifact to a very large number of deployments adds axes this plan has not touched, and it is worth
being blunt about which ones are genuinely absent rather than merely unpolished.

Today's shape is honest: **one operator, one VPS, one estate, updated by an operator who reads
output.** Each item below is what breaks first as that assumption is relaxed.

### S1. Upgrade is unproven across versions *(blocks any second deployment)*
`reconcile.py generations` / `rollback` exist; there is no test that a deployment at version N takes
N+1 and keeps its data. Every schema change, every blueprint push, every `.env` key added is an
unversioned migration today. **Nothing else on this list matters until an upgrade is provably
non-destructive**, because without it every fix is a reinstall.
*Needs:* a versioned migration ledger, an upgrade test from a seeded N to N+1, and a rollback that
restores data, not just images.

### S2. Secrets are files on a host
`.env` is the root of trust, and `data/` holds credentials and browser profiles. That is right for
one operator and wrong for many: no rotation, no per-deployment isolation, no revocation, and a
readable disk is total compromise. `platform-base/connections` (the credential broker) is the seam
this should grow from.

### S3. One Postgres, one Redis, no replication
Every app shares one database instance with no replica, no PITR, and a backup story that is a volume
on the same host. Single-node loss is total loss. Capability `sql` already abstracts *who provides*
the database, so this is a provider change rather than an app change — which is exactly why the
capability gate (G25) mattered.

### S4. Observability is `bbox status`
There is glitchtip for errors and a healthcheck per container. There are no SLOs, no per-deployment
telemetry, and no way to answer "are 10,000 estates healthy" other than asking each one. At scale
the operator is not a person reading output; it is a query.

### S5. Tenancy is per-deployment, not per-tenant
INDOX has instance columns and G28 enforces that every tenant-table access names its instance — real
work, already done. But the *platform* is single-tenant: one authentik, one console, one state file.
Multi-tenancy inside one deployment is a different design, and choosing "many small deployments"
instead is a legitimate answer — it just has to be a decision, with S1 and S4 paid for.

### S6. No release channel
There is no update mechanism, no signing, and no staged rollout. A bad release reaches everyone at
once or no one at all. `packaging/` builds an artifact; nothing distributes or verifies it.

### Sequencing

```
D1..D5  ──▶  S1  ──▶  S2, S4     S1 first: without safe upgrade there is no second release
             S3, S6              after S1; S3 is a capability-provider swap
             S5                  a design decision, not a task — settle it before S3
```

**The reasonable next milestone is not "billions".** It is *two* deployments — this VPS and one
more — upgraded from one version to the next without data loss and observed centrally. That single
step forces S1 and S4, and it is the smallest thing that proves the model generalises. Everything
after it is capacity work on a foundation that has been shown to hold.

**One thing to carry forward:** the fixes to `app.py` and `reconcile.py` are on disk, not in the
running containers. The app-management image must be rebuilt before the live control plane reflects
A1 or C1 — verified directly in the container that `reconcile.disposition` imports there, but the
running code is still the old image.
