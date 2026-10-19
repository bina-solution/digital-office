# n8n-as-code migration — code files only, bbox only

> **STATUS: SHIPPED 2026-08-16 (P0–P4 in one pass, owner-driven).** Backup of the JSON era:
> `legacy/blueprints-json-20260816/` + `data/_registry_backup/blueprints-json-20260816.tar.gz`
> (81 files). Live proofs: wrap round-trip **81/81 lossless**; `bbox n8n pull all` rendered
> **92 live workflows to code** routed by `app:*` tags (0 fallbacks); `bbox n8n push indox`
> no-op = "0 pushed"; bare `push` = hard error; a `.workflow.ts` note edit landed live via
> `push indox --wf indoxV2DecideTest01` through the API with no restart, key auto-minted.
> Retired: `scripts/ops/deploy-workflow.sh`, the JSON blueprints, the blueprint_as_code eval
> folder (legacy `scripts/n8n-pull|push` were already gone). KNOWN BOUNDARY: the fast path's
> API PUT carries name/nodes/connections/settings(+activation); workflow-root metadata
> (description/tags) travels on `pull` / `push all` only. OPEN UPSTREAM: file the transformer
> PR (notes/tags/connections/… passthrough) so the `/*__n8n__*/` graft can retire.
>
> **WAVE 2 (same day, owner's OSS semantics):** LIVE is the source of truth — humans develop
> in the UI, agents only through code, loop = pull(named) → edit → push(named) immediately.
> Positional grammar shipped: `pull <app> [wfId...]` (new fast hook `pull-app`: one CLI export,
> normalize, render named ids, sync the push cache), `push <app> <wfId...>` (named = never
> vetoed by cache), `--all` = force whole app, no-ids push = changed-only. Push cache rows now
> carry the live versionId; `bbox n8n status` gained a `[sync]` section naming every workflow
> a human changed live since the agent's last sync ("pull before editing") and flagging stale
> published drafts with the fix command; its blueprint count now uses enabled apps only
> (92==92 proven). Proofs: single-wf pull ~6s; positional push ok; status full+brief green.

**Owner mandate (2026-08-16):** bbox is THE development interface. `bbox n8n push` bare is
forbidden — `bbox n8n push all` for the estate, `bbox n8n push <app>` (e.g. `indox`) is the
normal verb. `pull` renders live → local **code files**; `push` compiles code files → n8n.
Locally we work ONLY with code files. This document is the complete plan to get there from
today's JSON blueprints and the un-unified CLI landscape (bbox hooks + `scripts/ops/
deploy-workflow.sh` + legacy `scripts/n8n-pull|push`).

Engine: [n8n-as-code](https://github.com/EtienneLescot/n8n-as-code) — `n8nac` CLI +
`@n8n-as-code/transformer`, both MIT, both on npm. We WRAP it inside bbox; we do not rebuild
it. Evaluation evidence: `apps/indox/blueprint_as_code/README.md` (64/64 convert, generated
routing maps, code as template literals; round-trip loss measured at exactly three field
classes: `nodes[*].notes`, id'd `tags`, `versionMetadata`).

> **WAVE 4 (same day): the rest of the toolkit, surveyed and selectively adopted.** Every
> n8nac subcommand was help-surveyed + the winners proven live through bbox: `test`/`test-plan`
> (agent exit semantics: config gap→0 inform, runtime state→0 don't edit blindly, wiring→1
> iterate), `execution list/get`, offline `skills` (validate accepts our grafted .ts —
> verified; node-info/search/docs, 537 schemas) — wired as `bbox n8n test|plan|exec` +
> `bbox n8n code validate|info|search|docs` via `hooks/test-app` and the wrap skills
> passthrough. Facade env self-configures headlessly (env add/auth/use → 127.0.0.1:5678,
> already loopback-published); key mint now discovers the instance's scope enum
> (GET /rest/api-keys/scopes — scopes are MANDATORY and role-filtered, measured) with
> fallback chains. NOT adopted, with reasons in ai/context/n8n-development.md: their
> pull/push/resolve sync model, n8n-manager, credentials recipes, MCP servers (CLI-first),
> promote (later candidate). Full consolidated outline: **ai/context/n8n-development.md**.

## The two-writer model (WAVE 3, 2026-08-16 — the concurrency contract)

The hard problem of "an automation layer humans edit live at n8n.localhost AND agents edit by
chat" is the classic LOST UPDATE: two writers, two representations (live DB vs code files), no
lock allowed (never block a human's editor or an agent's loop), no merge allowed (workflow
graphs don't three-way-merge, and manual resolution is banned). The mature pattern for exactly
this — kubernetes `resourceVersion`, HTTP `If-Match`, git fast-forward-only push — is
**optimistic concurrency**: every write names the base it was built on; a stale write is
cheaply rejected, never silently applied. What makes it fully non-blocking HERE is that the
rejected party is an AI: re-applying its own edit onto a fresh base is a seconds-long
mechanical step the CLI itself dictates. So:

- **Base token = live `updatedAt` (epoch ms)**, recorded per workflow in the push-cache at
  every pull/push. (NOT `versionId` — measured on n8n 2.17: versionId is stable across both
  API PUT and editor PATCH saves; updatedAt bumps on every save. Evidence in this repo's
  session, 2026-08-16.)
- **Push = CAS**: base ≠ live → `CONFLICT <id> — changed LIVE (HH:MM…) … Fix: pull → re-apply
  → push`, **exit 4**, per-workflow (non-conflicting ids in the same push still land). Nothing
  overwritten in either direction — the agent's edit stays in the file + git diff, a forced
  overwrite's loser stays in n8n's own version chain (`--force` exists, is loud, and is safe).
- **Whole-app pull = mirror with a guard**: files holding UNPUSHED local edits are SKIPPED
  loudly (never clobbered by the agent's own pull); pulling by name is the explicit discard.
  (First proof run caught the stale-cleanup deleting the very file the guard skipped — fixed:
  cleanup compares against the FULL live set.)
- **`status [sync]` is the radar**: names every workflow a human saved live since the agent's
  last sync, per app, with the exact pull command — plus stale published drafts.
- **Discipline that makes conflicts rare instead of merely safe**: agents ALWAYS
  pull(named) → edit → push(named) immediately; the conflict window is seconds wide.

Proven live end-to-end (2026-08-16): editor-save → agent push = exit 4 with instructions;
pull→re-apply→push = clean; whole-app pull skipped the edited file and the file survived;
`--dry-run` lists without sending; status full+brief read true after re-prime.

## Target state

```
apps/<app>/blueprint/n8n/*.workflow.ts      ← the ONLY human surface (git source of truth)
platform-base/n8n/workflows/*.workflow.ts   ← central/platform workflows, same form
.generated/n8n/<app>/*.json                 ← compiled import JSON (gitignored, build output)

bbox n8n pull  <app>|all    live → export → normalize → route to owners → render .workflow.ts
bbox n8n push  <app>        compile changed .ts → per-workflow n8n API push + activate (NO restart)
bbox n8n push  all          compile everything → full instance reconciler (owner/creds/schema/
                            gates/bulk import/publish/restart — today's hooks/push semantics)
bbox n8n push               ← HARD ERROR: prints enabled apps + 'all' and exits 2
bbox n8n status|verify      unchanged surface, ts-aware (drift = compile(ts) vs live export)
```

- One toolchain owner: `platform-base/n8n/tooling/` holds a pinned `package.json`
  (`n8nac@2.5.x`, `@n8n-as-code/transformer@2.0.x`) + `wrap.mjs` — the ONLY place that calls
  n8nac. Every bbox hook and CI gate goes through it. MIT allows vendoring; pin exact versions.
- **The lossless fix lives in the wrapper until upstream merges it.** `wrap.mjs render`
  post-processes the generated `.ts`: injects each node's `notes`/`notesInFlow` into its
  `@node({...})` decorator object and workflow `tags`/`versionMetadata` into `@workflow({...})`
  (extra decorator keys are inert to their compiler). `wrap.mjs compile` extracts those keys
  first, runs their `convert --format json`, then grafts the extracted fields back. Result:
  **notes are edited in the .ts like everything else**, and round-trip equality is a CI gate,
  not a hope. In parallel: file the upstream issue + PR (notes/tags/versionMetadata
  passthrough); delete the graft when merged.
- n8nac **API** push/activate is what retires the two standing failure classes: bare
  `import:workflow` deactivation (took `indoxV2FigureDocType01` down on 2026-08-16) and
  deploy≠live for schedule triggers (API activation registers live — `deploy-workflow.sh`'s
  documented caveat). `N8N_API_KEY` already lives in `.env`.

## Every consumer of blueprint JSON (found by reading, must be repointed at compile output)

| consumer | today | after |
|---|---|---|
| `platform-base/n8n/hooks/push` staging | copies `blueprints.n8n` dir JSONs | calls `tooling/wrap.mjs compile <dir>` → stages from `.generated` |
| `platform-base/n8n/hooks/pull` | exports + routes JSON into app dirs | + renders `.ts` via wrapper; JSON never lands in git |
| `bbox run` convergence (`ensure_converged` → `hooks/push --app`) | bare-import risk | same compile path; **must go through publish-model activation, never bare import** (fixes the standing bug regardless of migration) |
| app-management `_blueprint_apply` | reads app blueprint dir | reads compiled `.generated` (same wrapper) |
| `scripts/ops/deploy-workflow.sh` | import+SQL-reactivate one id | shim to `bbox n8n push <app> --wf <id>`, then deleted |
| legacy `scripts/n8n-pull|push` + `production/n8n/workflows/` (VPS docs in `ai/context/n8n-cli.md`) | parallel universe | deleted; n8n-cli.md rewritten around bbox verbs |
| parity / drift checks, `bbox n8n status` | compare repo JSON vs live | compare compile(ts) vs normalized live export |
| `gen-engine-manifest.py` → `engine-manifest.json` (mounted into incoming-documents) | reads blueprint JSONs | reads `.generated` JSONs (one path change) |
| CI gates (G12/G32-class, credential-blank-lint G63) | lint JSON/scripts | + new gates below |
| fixtures/schema loaders | untouched (not workflow JSON) | untouched |

## Phases (each shippable, each with acceptance numbers, each revertible by git revert)

**P0 — vendor + wrapper, zero behavior change.**
Add `platform-base/n8n/tooling/{package.json,wrap.mjs}`; hidden verbs `bbox n8n code render|
compile` for evaluation. Acceptance: whole estate (all `blueprints.n8n` dirs + platform-base
workflows) renders to `.ts` and compiles back **deep-equal, N/N** against the pull-normalized
JSON (volatile fields already stripped by pull: updatedAt/createdAt/versionId/activeVersionId/
versionCounter/triggerCount). The INDOX 64 already convert 64/64; equality is the wrapper's
graft to prove.

**P1 — verb grammar (breaking, announced).**
`bbox n8n push` bare → usage error naming enabled apps + `all`; `bbox n8n push all` = current
full reconciler; `bbox n8n push <app>` = current scoped reconciler (still heavy — that changes
in P2); old `bbox n8n <app> push` order kept as alias. Update every in-repo caller: `bbox
onboarding` (bbox:434), `ensure_converged`, docs, CI. Acceptance: `grep -r "bbox n8n push"`
shows zero bare invocations; onboarding + baseline green.

**P2 — per-app push goes API-grade (the dev-loop win).**
`push <app>`: compile app's `.ts` → sha-diff against last-push cache (the legacy script's good
idea) → for each changed workflow: n8n API upsert + activate via wrapper (n8nac env "Local"
auto-provisioned from `.env`'s `N8N_API_KEY`; base URL from deployment domain). No restart, no
instance-global steps. `--wf <id>` narrows to one workflow; `deploy-workflow.sh` becomes a
2-line shim. Acceptance: `bbox n8n push indox` after editing the drainer — active=true,
**schedule trigger proven live WITHOUT restart** (next 2-min tick fires on the new graph),
content parity 0 drift, zero error burst (vs T-9's historical 27-282), push completes in
seconds not minutes.

**P3 — THE FLIP: code files become the source of truth.**
`bbox n8n pull all` rewrites every blueprint dir to `.workflow.ts`; committed workflow JSONs
are deleted in the same commit; `.generated/` gitignored; all consumers from the table above
repointed. Lint gate: any `*.json` inside a `blueprints.n8n` dir fails CI. Update NEXT.md
working rules ("repo is source of truth" now names the `.ts`), CLAUDE.md table, the three
skills (n8n-as-code / bbox-n8n-push / indox-dev). Acceptance: **fresh-machine `bbox run` →
`bbox baseline` green from a ts-only repo**; `git ls-files 'apps/*/blueprint/n8n/*.json'`
returns nothing; a full `push all` + `pull all` cycle is a no-op diff (determinism).

**P4 — retire + upstream.**
Delete `scripts/n8n-pull`, `scripts/n8n-push`, `scripts/ops/deploy-workflow.sh`; rewrite
`ai/context/n8n-cli.md` (bbox verbs + raw-CLI appendix for emergencies); file/track the
upstream PR; optional: `bbox n8n promote <app> --to prod` wrapping `n8nac promote`
(laptop→VPS with credential remap) + second env in the wrapper. Acceptance: one CLI in every
doc; `bbox help` is the whole n8n story.

**New CI gates (from P1 on):** round-trip determinism (compile(render(x)) deep-equal x, N/N) ·
transformer schema validation per workflow (`n8nac`'s 537-node schema catches bad
typeVersion/params — replaces the planned check_js gate with something stronger) · no-JSON-in-
blueprint-dirs (P3+) · the existing credential-blank/drift gates unchanged.

## Risks and their handles

- **Transformer edge cases on exotic nodes** (LangChain nodes, community nodes baked in our
  image): the P0 N/N equality gate is the filter — any file that fails equality BLOCKS the
  flip and gets an upstream issue; the estate flips only at N/N.
- **Upstream drift/abandonment**: versions pinned; MIT lets us vendor a fork under
  `platform-base/n8n/tooling/` if it ever comes to that. The wrapper is ~150 lines; the
  dependency surface is the transformer's convert functions + the CLI's API client.
- **n8n API availability during pushes**: per-app push requires a healthy main (API). The
  `all` path keeps the CLI/SQL machinery for instance-birth when the API isn't up yet.
- **Queue-mode worker staleness** (workers cache workflow graphs): API activation publishes
  pub/sub reload events (unlike CLI import) — verify in P2 acceptance; if a stale-worker case
  survives, `push <app>` gains a targeted worker-restart flag rather than restoring the
  full-fleet restart.
- **CRLF/Windows**: `.gitattributes` already pins workflow files to LF; extend to
  `*.workflow.ts`.

## Sizing (honest, based on the read code)

P0 ~1 day (wrapper + gates). P1 ~half day (grammar + caller sweep). P2 ~1-2 days (API pusher +
sha cache + proofs). P3 ~1 day plus a full baseline run. P4 ~half day. The order is strict;
each phase lands green or reverts clean.
