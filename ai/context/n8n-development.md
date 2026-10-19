# n8n development on Platform OS — the complete outline

One page that holds the whole model: how automation development works here, for humans and
agents together. Deep dives: [n8n-as-code-migration.md](n8n-as-code-migration.md) (design,
phases, proofs), [n8n-cli.md](n8n-cli.md) (raw n8n CLI/REST/DB appendix — inspection and
emergencies only).

## The model in four sentences

Every app's automation layer is n8n workflows, and those workflows have TWO writers: humans in
the live editor (n8n.localhost), agents in code files — so **live is the source of truth** and
code is the always-fresh working surface. Blueprints are **code**: `apps/<app>/blueprint/n8n/
<id>.workflow.ts` (central: `apps/n8n/blueprint/n8n/`), owned per app via `app.json`
`blueprints.n8n` and routed by each live workflow's `app:<id>` tag. **bbox is the only
interface** — agents never touch live directly and never need another script. Safety is
**optimistic concurrency** (push checks its base against live `updatedAt`; stale = per-workflow
CONFLICT exit 4 with the recovery spelled out) — never a lock, never a prompt, never a loss.

## The CLI (everything an automation developer uses)

```
DEV LOOP (agent default: named workflows, pull first, push immediately)
  bbox n8n pull <app> <wfId> [...]   live → code, just those (~6s). Whole app when no ids
                                     (mirrors live; SKIPs files with unpushed local edits).
  bbox n8n push <app> <wfId> [...]   code → live via API: update + activate, no restart.
                                     Named = never vetoed by cache. No ids = changed-only.
                                     --all force app · --dry-run plan · --force override CAS
  bbox n8n status                    the co-op radar: [sync] names workflows humans changed
                                     live since your last sync + stale published drafts.
TEST & DIAGNOSE (vendored n8n-as-code facade; exit 0 = do NOT block, 1 = agent iterates)
  bbox n8n test <app> <wfId> [--prod] [--data <json>]   trigger via webhook/chat/form + verdict
                                     (Class A config gap → exit 0 inform · runtime state →
                                      exit 0 don't edit blindly · Class B wiring → exit 1 fix)
  bbox n8n plan <app> <wfId> [--json] infer HOW to test + a suggested payload (heuristic)
  bbox n8n exec list|get [...]        execution diagnosis via the API (psql stays for forensics)
AUTHORING INTELLIGENCE (offline — 537 node schemas, docs, guides)
  bbox n8n code validate <file.ts>    schema-lint a workflow file BEFORE pushing
  bbox n8n code info <node>           full node parameter interface as TypeScript
  bbox n8n code search <query>        paste-ready @node snippets · docs/guides likewise
  bbox n8n code render|compile|verify the transformer pipeline (verify = round-trip gate, CI)
ESTATE (instance-level; rare)
  bbox n8n pull all                   everything + credentials + blueprint.yml manifest
  bbox n8n push all                   FULL reconciler: owner/creds/schema/import/publish/RESTART
  bbox n8n verify · clean-recreate · load-dump · automations reset      (unchanged)
```

Exit codes everywhere: **0** ok / don't block · **1** real failure (iterate) · **2** usage ·
**4** sync conflict — pull first. Zero prompts, zero interactivity, idempotent verbs, every
error names the exact next command. First use self-provisions: toolchain `npm ci` (ext4-cached
under WSL), API key minted from the `.env` owner with scope discovery, facade env configured —
a fresh clone needs only `bbox run`.

## The code files (`*.workflow.ts`)

- Generated `<workflow-map>` header: node index + routing map — the workflow at a glance.
- `@workflow({...})` / `@node({...})` decorators; `jsCode`/SQL as real template literals.
- `/*__n8n__*/` marker lines carry what the upstream transformer drops (round-trip proven
  81/81): **`connections:` is the authoritative graph** (edit routing there — the links() DSL
  below is a generated view); `notes:` under each node's `name:` is its documentation; plus
  description/tags/meta/disabled/…
- Identity: filename = workflow id = stable forever (executeWorkflow references).
- New workflow: copy a small `.ts`, fresh unique id, ensure the `app:<app>` tag rides in the
  tags marker; first push creates via import+publish (new SCHEDULE triggers register on next
  main restart — the only create-time caveat; every update is hot).
- Fast-path boundary: API updates carry name/nodes/connections/settings(+activation);
  workflow-root metadata (description/tags) syncs on `pull` / `push all`.

## What runs underneath (one owner per fact)

| part | path | job |
|---|---|---|
| toolchain | `apps/n8n/tooling/` (`wrap.mjs` + pinned n8nac 2.5 / transformer 2.0, MIT) | the ONLY caller of n8n-as-code; render/compile graft; skills passthrough |
| rapid verbs | `hooks/push-app`, `hooks/pull-app`, `hooks/test-app` | API push+activate w/ CAS · fast pull w/ unpushed-edit guard · test/plan/exec facade |
| reconciler | `hooks/push` (`push all`) | owner, credentials (create-if-missing + env reseed), platform schema, tag pre-create, bulk import + publish, restart |
| estate pull | `hooks/pull` (`pull all`) | export, normalize volatile fields, tag-route to owners, render to code, blueprint.yml |
| radar | `hooks/status` | counts (enabled apps only), published parity, key/cred health, [sync] co-op signals |
| sync state | `apps/n8n/.push-cache/<app>.tsv` (gitignored) | per-workflow: compiled sha · id · live updatedAt-ms base (the CAS token) |
| convergence | `bbox run` → app-management `_blueprint_apply` → the same hooks | apps' automations exist because their manifest says so |

## Context files & skills (who reads what)

| audience | artifact |
|---|---|
| any agent doing n8n work | skill **n8n-as-code** — the contract: live-truth, pull→edit→push, grammar, markers, two-writer safety, exit codes |
| instance/deploy questions | skill **bbox-n8n-push** — reconciler anatomy, publish model, footguns |
| INDOX app work | skill **indox-dev** — state-machine laws, deploy ritual, tests, settings |
| design + evidence | `ai/context/n8n-as-code-migration.md` |
| this outline | `ai/context/n8n-development.md` |
| raw n8n CLI/REST/DB appendix | `ai/context/n8n-cli.md` (inspection/emergency only) |

## n8n-as-code (EtienneLescot, MIT): adopted vs deliberately not

**Adopted (wrapped, never called directly):** transformer JSON⇄TS (with our lossless graft —
upstream PR pending retires it) · `test`/`test-plan` (agent-grade exit semantics) ·
`execution list/get` · offline `skills` (validate/node-info/search/docs/guides — 537 schemas,
7,700+ templates) · headless env facade (`env add/auth/use` against 127.0.0.1:5678).
**Not adopted, with reasons:** their `pull/push/resolve` sync (whole-file keep-current/
keep-incoming — our CAS + agent-as-merge is stronger and non-interactive) · `n8n-manager`
(bbox runs the stack) · `promote` (laptop→VPS candidate for later; bbox would wrap it) ·
`credentials recipes` (our `.env`-driven `credential_overrides` reseed is instance-coherent) ·
their MCP servers (we are CLI-first for agents by owner decision; humans who want a visual
canvas over the code files can use their VS Code extension — optional, reads the same files).

## The dual-development story, end to end

Human: opens n8n.localhost, edits, saves — done (their saves land in live truth immediately,
version history keeps everything). Agent: `status` (anything I must pull?) → `pull <app> <wf>`
→ edit code (validate offline) → `push <app> <wf>` → `test`/`exec` to verify → report numbers.
If they cross: push answers CONFLICT exit 4 naming the human's edit time and the three-command
recovery; whole-app pulls skip the agent's unpushed work. Nobody waits, nobody merges by hand,
nothing is ever lost — and both are always looking at the same truth, seconds apart.
