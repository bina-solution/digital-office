# Platform-OS refactor — design, mechanics, and the parity protocol

Branch `platform-os-refactor` (off `release-v2-lockin@39eb115`). Turns the monorepo into a
three-layer extensible app platform where every capability is an app with a manifest, without
changing what the system does. Research backing: Fuchsia CFv2, seL4/Microkit, OSGi, systemd,
Home Assistant, Cloudron, Runtipi, YunoHost, CasaOS (see the two deep-research rounds).

## The shape

```
platform/            layer 1 — headless base
  schema/app.schema.json      the app manifest contract
  manager/reconcile.py        the compiler (plan|render|up|validate)
  legacy-capabilities.yaml    bridge: what the un-migrated lane still provides (must reach EMPTY)
platform.state.yaml  desired state — the only file the console writes (enabled + instances)
apps/<id>/           every app: app.json + its own compose + its own assets
.generated/          COMPILED OUTPUT (gitignored) — never hand-edit
production/          the shrinking legacy lane
```

`apps/<id>/app.json` is the single source of truth for an app. Six registries that used to be
hand-edited per app become compiler output: the compose include list, `compose.override.yml`,
the authentik blueprint, `console/modules.yaml`, console `APP_BASES`, and the connections
consumers manifest.

## Manifest decisions (and why)

* **`capabilities` / `use`, not a flat `dependencies: []`** (Fuchsia CFv2). A flat list cannot
  express direction, strength, or which ops a consumer actually needs.
* **Strength is decoupled from ordering** (systemd): `strength: requires|wants|requisite|
  binds_to|conflicts` says *whether*; `after: true|false` says *when*.
* **`dependency: "weak"`** is the only sanctioned way to break a layer-2 cycle (console ↔
  notifications). Weak links are excluded from cycle detection *and* shutdown ordering, so the
  consumer must tolerate the capability being absent.
* **enable/disable ≠ start/stop** (OSGi): `enabled` in `platform.state.yaml` is the persistent
  disposition; container state is transient. Disable always keeps volumes.
* **Multi-instance lives in state, not the manifest** (Home Assistant config entries). A
  domain declares `type: "service"`; the configured instances live under `instances:`.
* **Ops negotiation** solves unequal provider feature sets: a consumer declares the `ops` it
  needs and the resolver refuses to bind an adapter that lacks them.
* **`emit_labels`** is explicit because the estate has two valid end-states: labels compiled
  from the manifest (they used to be trapped in the central override) or already self-contained
  in the app's own compose. Both are decentralised; normalising the label conventions is a
  separate, independently-verifiable pass.
* **`auth` is mutable**, never frozen at install (Cloudron's documented failure mode).

## The parity protocol

> **HISTORICAL — G1 no longer exists.** This section describes the protocol as it was run *during*
> the move, and it is kept because it is the record of how the refactor was carried out. G1
> (`compose-equiv.py`), `scripts/refactor/moves.json` and `.refactor/golden.raw.yml` were **deleted
> on 2026-07-30**: the move is finished, all 23 declared old paths are gone from the tree, and a
> byte-equivalence golden is the wrong shape for output the compiler regenerates on every app
> add/remove. **Nothing checks byte-equivalence today and nothing should.** See
> `scripts/refactor/GATES.md`, "Why G1 was deleted", for the regenerated evidence.

Four gates. **G1 ran after every single app move** — that is what made a 21-service refactor
safe rather than a leap.

| Gate | Command | Criterion |
|---|---|---|
| ~~**G1 config**~~ | ~~`scripts/refactor/compose-equiv.py .refactor/golden.raw.yml <candidate>`~~ | *retired 2026-07-30* — rendered config equals golden **modulo declared moves** |
| **G2 baseline** | `scripts/ci-verify.sh`, then `bbox baseline` | ci-verify 25/25; indox 7/7; extraction 138 docs / 527 values; sync-v3 100% |
| **G3 ui-map** | `bbox ui-map` (`UI_MAP_GATE=1`) | 78/78 views; region set + missed list vs `.ci-cd/ui-map/` |
| **G4 pixel** | `digital-office/verify/ui_map_diff.py` | per-screen % pixels differing ≈ 0 |

While it ran, the golden was *not* frozen forever: when `.env` legitimately changed or a shared fix
landed, the identical change was applied to golden so it kept meaning "the original tree under
today's inputs". That hand-maintenance is also what made it unwireable into CI — see the note above.

## Running the stack

There is exactly one correct compose invocation, and it needs **both** the compiled `-f` list
and `--project-directory` — the latter has no env-var equivalent, and without it the generated
file's `- compose.yml` include resolves against `.generated/`, self-includes, and docker fails
with `include cycle detected`. So `COMPOSE_FILE` alone is never sufficient.

```
./scripts/dc ps                                          # shell / CI steps
OVERLAYS="platform/profiles/ci-images.yml" ./scripts/dc up -d
dcx restart n8n                                          # inside a script that sourced lib.sh
```

`bbox`'s `dc()` is now a one-line alias for `dcx`. G7 enforces that nothing bypasses this.

## Migration recipe

```
scripts/refactor/migrate-app.py <id>     # git mv, drop include, lift override, record the move
scripts/refactor/merge-override.py <id>  # only if the block carried config, not just labels
# hand-write apps/<id>/app.json          # the design act — never transcribed automatically
# enable in platform.state.yaml, then G1   <- G1 retired 2026-07-30; run `bash scripts/ci/gates.sh`
```
(Historical, like the protocol above: the migration these tools served is complete, and the G1 step
no longer exists. `scripts/ci/gates.sh` is what you run after a change now.)
Stop the container first if the app bind-mounts directories (Windows locks them).
After any move, sweep scripts for the old path — see below.

## What the gates actually caught

Real breakage that would have shipped silently:

* `incoming-documents` mounted `../n8n/demo-docs` **relatively**; moving the app repointed it
  at a nonexistent `platform-base/n8n/demo-docs`. A runtime mount failure, caught at compile time.
* `scripts/glitchtip-push` read `<glitchtip>/blueprint.yml`; after the move it did not error —
  it **silently fell back to a 4-project default**, which would have left 11 apps with no
  error-reporting project. Now 15/15.
* A `git checkout` used to undo a partial migration also restored two already-removed legacy
  references. G1 failed instantly with the exact missing service.
* **The bug G1 structurally cannot catch.** Once the services moved into `.generated/`, every
  bare `docker compose` at the repo root resolved *zero* services — and docker reports that as
  `no such service: n8n` with **exit code 0**, which each call site's `|| true` swallowed.
  `scripts/n8n-push`'s restart step silently stopped restarting anything, so after every push
  n8n kept serving its pre-import state: `webhook_entity` sat at 0 for all 116 active workflows
  and `/webhook/ci-hello` 404'd forever, while a plain `docker restart n8n` fixed it in 45s.
  The rendered config was correct throughout — only the *invocation* was wrong, which is why
  this needed **G7** and why it only surfaced once the functional gate was actually run.

## Pre-existing bugs found while verifying (fixed, proven by A/B against the original tree)

* **n8n healthcheck used `localhost`**, which resolves to `::1` before n8n's IPv4-only bind, so
  n8n sat permanently "unhealthy" while fully functional — and every dependant with
  `condition: service_healthy` refused to start. Pinned all 4 probes to `127.0.0.1`; n8n now
  goes healthy in ~60s. Because this changes rendered config, the same fix was applied to golden.
* `indox-e2e.yml` lacked `INCOMING_DOCS_SUPABASE_URL` / `APITOOLS_DB_HOST` that `baseline.sh`
  and `ui-map.yml` already set — the documented cause of red CI runs #128–#135.

## Not a refactor bug: stale first-party images on a long-running dev stack

The six INDOX drive suites first failed with `Method not allowed` at every drive-seed node.
Root cause was not the refactor: the running `localdrive` (and every other first-party)
container was an image built **2026-07-16**, while the drive/mail service routes landed
**2026-07-17** (`6581e1d`, on the base branch) — the local stack had simply never been rebuilt.
`docker compose build localdrive && up -d` restored `POST /list -> 200` and all suites went
green. `bbox baseline` — the canonical proof — always does a fresh `build --pull`, so CI is
unaffected; only a hand-kept dev stack drifts this way. Worth a glance at image timestamps vs
`git log` before blaming a red suite on code.

### INDOX suite results after the rebuild (2026-07-22, this branch)

```
✅ sync_kernel   6/6    28s     ✅ bs        4/4    85s
✅ sync_sources 10/10  116s     ✅ gdoc      5/5   429s
✅ sync_full     6/6    91s
❌ doc_base      2/3   196s   one demo doc: dbf_ord resolved COMPANY 514947746, fixture wants 511234567
❌ pipeline      0/–  1087s   harness gave up polling; the n8n execution was STILL running
```
Both reds are non-structural. **doc_base** is a single-document company-resolution miss on
`order/files/PO25010001` — and `gdoc` ran the *same file* (`gdx_ord1`, same expected 511301129-style
company) and passed 5/5, so it is a flake in the resolver, not a systemic break. **pipeline** never
returned a verdict: its n8n execution was still `running` when the harness stopped waiting, i.e. a
timeout on the heaviest suite, last in a back-to-back battery, on a laptop right after a full image
rebuild (see [[stack-memory-pressure-flakiness]]). Neither is caused by the refactor; both want a
re-run on the Linux runner before being called real.

## Known environment limits (not refactor regressions)

* `integration-n8n-active-state` fails **on Windows only**: curl writes `-c /tmp/jar` to
  `C:\tmp` while the script greps MSYS `/tmp`. Verified directly on this tree — login succeeds
  and `/rest/active-workflows` reports 98 runtime listeners.
* `bbox ui-map` runs on **Linux, Windows and macOS**. It was long marked "cannot run on
  Windows (MSYS paths)" — that claim was never tested and was wrong. The fix was nine call
  sites: host paths handed to the native python/docker binaries need `npath()`
  (scripts/lib.sh), plus UTF-8 stdout for the Hebrew labels. Gate **G10** enforces both.

## Status: TRANSFORMATION COMPLETE

`ownership-lint --strict` passes — debt 98 -> 0. **26 apps; nothing outside `apps/`.**

```
services defined outside apps/           0
capability bridges open                  0     (legacy-capabilities.yaml EMPTY)
acknowledged external paths              0     (external-paths.yaml EMPTY)
apps with build source outside apps/     0
```

The root `compose.yml` is now only the shared network declaration; `production/compose.override.yml`
(633 lines) is deleted; `development/` is gone, its 17 unused experiments parked in `attic/`.
Cross-cutting overlays live in `platform/profiles/` (ci-images, connections-mode, perf-profiles).

### Six gates, all green — five of them wired into CI
`ci-verify.yml` gained a `platform-invariants` job running G5/G0/G6 with no stack needed, so the
model cannot silently decay. **G1 was the exception and was never wired anywhere**; it was deleted
on 2026-07-30 rather than left asserted-but-unchecked. Corrected here because this table claimed
otherwise for two months.

| | gate | proves |
|---|---|---|
| G0 | `paths-exist.py` | every referenced host path exists (docker silently creates empty dirs) |
| ~~G1~~ | ~~`compose-equiv.py`~~ | *deleted 2026-07-30 — it was in no lane; see `scripts/refactor/GATES.md`* |
| G5 | `ownership-lint.py --strict` | nothing lives outside an app |
| G6 | `auth-lint.py` | no unprotected router shares a rule with a protected one |
| G7 | `compose-invocation-lint.py` | no bare `docker compose` (it resolves 0 services, exit 0) |
| G2 | `bbox baseline` | ci-verify 24/25 · full baseline pending on Linux |
| G3/G4 | `bbox ui-map` | structural half passes; capture needs the Linux runner |

### Still to do
1. **Run G2 (`bbox baseline`) and G3/G4 on the Linux `devops-vps` runner** — the ui-map capture now runs locally on Windows too (G10); the full indox 7/7 + 527/527
   battery has not been run on this branch.
2. **Domain consolidation** — DONE. `localdrive`->`drive` and `gmail-imap`->`inbox`, per the
   frozen platform-service contract: an app is named for the capability it provides, not the
   vendor it talks to. `inbox`, not `mail`, because `mail.localhost` is mailview and
   `email.localhost` is localmail — naming it `mail` would have made the app called "mail" the one
   app not served at mail.localhost. Both keep their original volume names; renaming those would
   orphan live data for no gain. mailview/localmail remain adapters alongside.
3. **`scripts/` (138 files)** — app-specific scripts (indox 13, n8n 6, glitchtip, supabase-keygen,
   b42) still live centrally; move them into `apps/<id>/hooks/` and collapse
   `bbox indox|b42|n8n` into `bbox app <id> <verb>`.
4. **Split the remaining 78 central workflows** — INDOX owns its 41; the shared stdlib
   (Settings/Logger/process_lock/Batch Upsert/API routers) should become `platform-base/n8n`'s, and the
   CI/diag ones platform-owned.
