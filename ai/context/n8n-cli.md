# n8n — operate (CLI · REST API · DB), tested against n8n 2.0.3

> **AS-CODE FLIP (2026-08-16)** — workflows are now CODE: `*.workflow.ts` per app blueprint,
> managed ONLY through bbox (`bbox n8n pull <app>|all`, `bbox n8n push <app>` rapid API path,
> `bbox n8n push all` full reconciler, `bbox n8n code render|compile|verify`). The legacy
> `scripts/n8n-pull`/`n8n-push` and `scripts/ops/deploy-workflow.sh` are retired. Design +
> phases: [n8n-as-code-migration.md](n8n-as-code-migration.md). Everything below about raw
> CLI/REST/DB operation remains valid for INSPECTION and emergencies; deployment goes through
> bbox, full stop.

Full access to the production n8n instance via `docker exec` (CLI/DB) and the REST API.
Production-first, read-mostly. General compose ops: [deployment-context.txt](deployment-context.txt).
Deep "what the workflows do" map: `obsidian/Projects/deployment-hacohen/n8n System Map.md`.

## Safety rules
1. Treat as production. Prefer REST API / CLI for changes; Postgres is read-only inspection.
2. Don't change DB schema; don't write tables unless there's no safe API/CLI path (state the reason).
3. Never commit API keys, OAuth secrets, refresh tokens, or decrypted credential blobs.
4. Before changing a live workflow: export it to `/tmp`. After: verify, then export back to `production/n8n/workflows/`.
5. Activate/deactivate active workflows through the REST API (so webhooks register correctly).
6. Never expose large sheet/bulk output to an agent via raw MCP — compact/filter inside the workflow first.
7. Per [../AGENTS.md](../AGENTS.md): file edits are fine, but don't `git add/commit/push` on your own.

## Environment
```bash
DEPLOY_DIR=/root/deployment-hacohen
N8N_PUBLIC_URL=https://n8n.hacohen.bina-solutions.co.il
N8N_API_BASE=https://n8n.hacohen.bina-solutions.co.il/api/v1
```
- Containers: `n8n-bina-deployment` (main/webhook), `n8n-worker-{1,2}-bina-deployment` (workers), `n8n-task-runners-bina-deployment` (code nodes), `n8n-postgres-bina-deployment` (PG17), `redis-bina-deployment`.
- Workflow files mounted at **`/home/node/workflows`** ↔ host `production/n8n/workflows/`.
- Prod MCP endpoint: `…/mcp/<path>` (the `/mcp-test/<path>` form only works while the editor test listener is active).
- Credential overwrite data read from `/docker-cfg/n8n.credentials.json` in-container ← host `production/n8n/n8n.credentials.json`.
- **API key:** in repo `.env` as `N8N_API_KEY`. Load into `$KEY`, never print/commit:
  `KEY=$(grep -E '^N8N_API_KEY=' .env | tail -1 | cut -d= -f2-); curl -sS -H "X-N8N-API-KEY: $KEY" "$N8N_API_BASE/workflows?limit=1"`

## CLI — invoke
```bash
docker exec n8n-bina-deployment n8n <command> [flags]
```
stdout is noisy — filter when parsing: `… 2>/dev/null | grep -vE 'Error tracking disabled|Puppeteer node|dockerenv'`.
`n8n --help` lists commands; `n8n <cmd> --help` shows flags. `n8n --version` → `2.0.3`.

### SAFE — read-only (verified)
| Command | Purpose |
|---|---|
| `n8n list:workflow` | List all (`id\|name`). 144 in DB. |
| `n8n list:workflow --active=true --onlyId` | Active IDs only (`--active=false` for inactive). |
| `n8n export:workflow --id=<id> --output=/tmp/<id>.json --pretty` | Export one workflow (reads DB → /tmp). |
| `n8n export:workflow --backup --output=/tmp/wf/` | `--backup` = `--all --pretty --separate` (used by `bbox n8n pull all`). |
| `n8n export:entities --outputDir=/tmp/ent` | Export DB entities (add `--includeExecutionHistoryDataTables=true` — large). |
| `n8n audit` | Security audit (unused/risky credentials, DB, risky/community nodes). |
| `n8n license:info` / `n8n export:nodes --output=/tmp/nodes.json` | License info / dump node types. |

> `export:credentials --decrypted` writes **plaintext secrets** — never to inspect or commit; key-rotation migration only, outside the repo.

### MUTATING — confirm first, export the target before running
| Command | Effect |
|---|---|
| `n8n import:workflow --input=<file>` / `--separate --input=<dir>` | Overwrite live workflow(s) by ID (used by `bbox n8n push all`). |
| `n8n import:credentials --input=<file>` / `n8n import:entities` | Import credentials / DB entities. |
| `n8n publish:workflow --id=<id> [--versionId=<v>]` / `n8n unpublish:workflow --id=<id>` | Publish(activate)/unpublish a version (n8n 2.x replaced deprecated `update:workflow`). |

### DANGEROUS — only on explicit, specific user request
- `n8n execute --id=<id>` / `execute-batch` — runs workflows for real. **Tested: does NOT work inside the live queue-mode container** — tries to bind task-broker port 5679 (held by the running instance); overriding the port just hangs waiting for a runner. **Run an automation by triggering it** (call its webhook / activate a schedule), not via this command.
- `n8n db:revert` (reverts last DB migration), `user-management:reset`, `ldap:reset`, `mfa:disable`, `license:clear`.

## REST API — automation lifecycle (tested end-to-end)
Full create→develop→activate→execute→delete cycle verified working:
- **Create:** `POST /workflows` with `{name,nodes,connections,settings}` → returns `id` (created inactive).
- **Develop:** `PUT /workflows/<id>` with the same minimal body (export to `/tmp/<id>-before.json` first). For node-only metadata, strip API-rejected fields.
- **Activate / deactivate:** `POST /workflows/<id>/activate` | `/deactivate` (registers/removes the trigger's `webhook_entity` row). The public API has **no run/execute endpoint** and **no delete-via-CLI**.
- **Execute:** trigger it — webhook workflow: `curl https://n8n.hacohen.bina-solutions.co.il/webhook/<path>`; confirm via `GET /executions?workflowId=<id>` (`status:"success"`).
- **Delete:** `DELETE /workflows/<id>` (deactivate first). Returns the deleted workflow.

## Known workflows & credential IDs (no secret material)
| Workflow ID | Name / purpose | MCP / webhook path |
|---|---|---|
| `QR6p46Wpmvo7z53c` | Chat agent (public) + Gmail/Drive/Sheets MCP clients | `e5616171-e3b5-4c39-81d4-67409f9fa60a/chat` |
| `gmailMcpAgent01` | Gmail MCP Server | `gmail-enhanced` |
| `gDriveMcpAgent01` | Google Drive MCP Server - agent.hacohen | `gdrive-agent` |
| `gSheetMcpAgent01` | Google Sheets MCP Server - agent.hacohen | `gsheet-agent` |

| Credential ID | Purpose |
|---|---|
| `41BKgLp83YYyfEM3` | Gmail production credential |
| `jft0CdgvgPNvaLNn` | Older Gmail credential; may be stale |
| `KirWFwoFdEFmnN0R` / `e2knIZpw8YF0QBAB` | Google Drive / Sheets credential (agent.hacohen) |
| `2qKUrcv37UXZbz7u` / `77wJNJ6sYrGsfH9B` | MCP server / agent client header auth |

## Versioning (repo ↔ live) — bbox only (as-code flip 2026-08-16)
- **Pull (live → code):** `./bbox n8n pull <app> [wfId ...]` (fast) / `./bbox n8n pull all` (estate + credentials + manifest). Workflows land as `*.workflow.ts`, routed by their `app:*` tag.
- **Push (code → live):** `./bbox n8n push <app> <wfId ...>` (API update+activate, sha-cache, CAS conflict guard, `--dry-run`) / `./bbox n8n push all` (full reconciler + restart).
- Full model: [n8n-development.md](n8n-development.md). Raw `export:workflow` below is for inspection only — never a deployment path.

## Investigation procedure
Identify (workflow/execution/MCP path/prompt) → export current workflow to `/tmp` → check running executions →
read logs for the window → one hypothesis + cheap validation → patch only the relevant slice → reactivate via REST →
verify (webhook/API/browser) → export live workflows to `production/n8n/workflows/` → final read-only checks.

### Read-only DB checks
```bash
# state + webhooks
docker exec n8n-postgres-bina-deployment psql -U hacohen -d n8n -c "
SELECT id,name,active,\"triggerCount\" FROM workflow_entity
WHERE id IN ('QR6p46Wpmvo7z53c','gmailMcpAgent01','gDriveMcpAgent01','gSheetMcpAgent01') ORDER BY id;
SELECT \"webhookPath\",method,\"workflowId\" FROM webhook_entity
WHERE \"webhookPath\" IN ('gmail-enhanced','gdrive-agent','gsheet-agent','e5616171-e3b5-4c39-81d4-67409f9fa60a/chat') ORDER BY 1,2;"
# running executions
docker exec n8n-postgres-bina-deployment psql -U hacohen -d n8n -c "
SELECT id,\"workflowId\",status,mode,\"startedAt\",\"stoppedAt\" FROM execution_entity WHERE status='running' ORDER BY id::bigint DESC LIMIT 20;"
# logs since a timestamp
START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
docker logs n8n-bina-deployment --since "$START" 2>&1 | grep -iE 'MCP error|Request timed out|invalid_grant|Got request|webhook|gsheet-agent|gdrive-agent|gmail-enhanced' | tail -120
```

## Lessons
**Gmail MCP failures:** client points at `/mcp-test/` not `/mcp/`; Gmail tool nodes not wired to the MCP trigger via `ai_tool`; Google OAuth app in *Testing* mode (refresh tokens expire ~7 days); runtime resolves an older credential ID after a visible swap.
- `invalid_grant`: confirm which credential ID nodes reference → check `workflow_dependency` for stale IDs → reauthorize/swap via UI or API → if runtime still uses stale ID, investigate dependency/cache before DB repair. **Long-term fix: publish the Google OAuth consent screen to production.**

**Drive/Sheets MCP:** import official n8n templates (Drive `templates/workflows/3634`, Sheets `templates/workflows/5424`) via `POST /workflows` (minimal body), set MCP path + creds, activate, verify webhooks. Avoid raw CLI import for active MCP workflows.
- Sheets pitfalls: `$fromAI('Data_To_Add',…,'object')` can break tool advertisement — use `string`; some ops need gid not tab name. **AutomationValues gids:** `749586510` = `חברות`, `542119184` = `מסמכים נכנסים`.

**Sheets MCP timeouts:** a full AutomationValues read ≈1.6M tokens → `MCP error -32001: Request timed out`. Don't expose big tabs via raw MCP read. Use a `toolWorkflow` tool that filters/summarizes inside the workflow and returns compact JSON; bound generic reads to ~`A1:Z200`. Working tool: **`AutomationValuesQuery`** (ops: `lastCompaniesRows`, `countIncomingDocumentsForCompany`; for Hebrew "כמה מסמכים נקלטו…" pass company name, default `monthsBack=2`).

## Verify (chat webhook)
```bash
CHAT='https://n8n.hacohen.bina-solutions.co.il/webhook/e5616171-e3b5-4c39-81d4-67409f9fa60a/chat'
curl -sS -m 180 -X POST "$CHAT" -H 'Content-Type: application/json' -d '{"sessionId":"verify","action":"sendMessage","chatInput":"<prompt>"}'
```
Pass = quick response, logs show `Got request for AutomationValues_Query`, no `Request timed out`, small payload.

## Final checklist
Workflow active · `triggerCount` correct · webhooks in `webhook_entity` · no `running` executions left ·
failing prompt re-verified · prior error gone from logs · live workflows exported to `production/n8n/workflows/` ·
`git status --short` shows only intended files.

## State sync — the blueprint (`bbox n8n pull all` · `bbox n8n push all`)

n8n is **Community Edition** (requires **>= 2.17.0** — the `import:entities` JSON bug is fixed there;
the version is centralized in `.env` as `N8N_VERSION`). State travels through git declaratively. The
entry point is **`apps/n8n/blueprint.yml`** — a manifest that points at every part:

| Part | Path | Format | Notes |
|---|---|---|---|
| Workflows | `apps/n8n/blueprint/n8n/<id>.workflow.ts` + each app's `blueprints.n8n` dir | **code** (as-code flip 2026-08-16) | rendered by pull via `tooling/wrap.mjs`; compiled back to import JSON on push |
| Credentials | `apps/n8n/credentials/<id>.json` | **human-readable** entity | `export:credentials`; id/name/type readable, secret **AES-encrypted** with `N8N_ENCRYPTION_KEY` |
| Owner | `.env` → `N8N_OWNER_*` | env (not stored in repo state) | bootstrapped on push (see below); **not** carried in any snapshot |

The blueprint is **fully human-readable** — no encrypted state blob. `blueprint.yml` records `schema`
(`n8n-blueprint/v2`), `n8n_version`, `encryption_key_fingerprint` (first 16 hex of sha256(key) — the
mismatch detector), `owner: {source: env}`, per-part pointers + counts, and the `active_workflows` list.

```bash
./bbox n8n pull all           # export running instance -> blueprint as code + credentials (review git diff, commit)
./bbox n8n push all           # blueprint -> instance: bootstrap owner, import creds + workflows (upsert), publish, restart
```

**`push all` is non-destructive and self-sufficient from `.env`.** On a fresh instance it:
1. **Bootstraps the owner** from `N8N_OWNER_EMAIL`/`N8N_OWNER_PASSWORD`/`_FIRSTNAME`/`_LASTNAME`
   (idempotent — n8n has no native owner env var, so the script POSTs `/rest/owner/setup` only when no
   owner exists yet; skipped otherwise). Password rules: 8–64 chars, ≥1 number, ≥1 capital.
2. *Upserts* credentials + workflows (never deletes extras) via `import:credentials` / `import:workflow`,
   which re-own everything to the current owner (so ownership stays coherent on any machine).
3. Re-activates the active set via `publish:workflow` (no API key / auth), then restarts n8n so the
   triggers register. Result: owner login + workflows + running active workflows, all from `.env` + git.

> **Why no encrypted entities backstop?** An earlier design committed an `export:entities` zip for the
> owner/instance-settings. It was dropped: the owner must come from `.env` (single source, known
> password), and an entities snapshot **minus** the owner is incoherent — n8n ties workflow/credential
> ownership to the owner's user/project IDs, which the `.env` bootstrap regenerates, so restored sharing
> rows would point at a phantom user. The human-readable import path re-owns cleanly and needs no blob.

To move another machine's n8n env here: copy `apps/n8n/{blueprint.yml,workflows,credentials}` into
the repo, set the **same `N8N_ENCRYPTION_KEY`** in `.env` (recreate n8n so it picks it up) + your
`N8N_OWNER_*`, then run `./bbox n8n push all`. The matching key is mandatory — workflows restore
regardless, but credential **secrets** won't decrypt without it (re-auth each credential in the UI).

## Onboarding failure modes & the guards in place
Things that bit us (and how the setup/scripts now handle them):

| # | Failure | Guard / fix |
|---|---|---|
| 1 | **CRLF (Windows `autocrlf`)** rewrites workflow JSON → push sees every file "changed", noisy diffs | `.gitattributes` pins these files to `eol=lf`; run `git add --renormalize .` once on the canonical repo |
| 2 | **Encryption-key mismatch** → credentials import but silently won't decrypt | `encryption_key_fingerprint` recorded in `blueprint.yml`; push warns loudly if the instance key differs (pin `N8N_ENCRYPTION_KEY` in `.env` so it survives a volume wipe) |
| 3 | **n8n 2.0.x import bugs** (`import:workflow` FK crash on `active:true`; `import:entities` "invalid input syntax for type json") | fixed upstream in **2.17.0**; `N8N_VERSION` is pinned there. `import:workflow` now imports cleanly (deactivates), then push re-activates with `publish:workflow` |
| 4 | **Re-activation needs auth / active workflows don't run without an owner** | push uses the CLI `publish:workflow --id` (no API key / session); and it bootstraps the owner from `.env` (`N8N_OWNER_*`) first, so active workflows actually run after the restart |
| 5 | **Non-workflow JSON** in `workflows/` (e.g. `kafka-trigger-credential.json` is a credential; `glitchtip-error-reporter.json` is hand-authored) | push skips files with no `nodes` array and reports them; clean these out of `workflows/` |
| 6 | **Slow import** (~2.5 s/workflow CLI startup; 146 ≈ 11 min) looks hung | single in-container loop + `PROGRESS i/total` every 25 |
| 7 | **Container name** depends on `DEPLOYMENT_NAME` | scripts derive `n8n-${DEPLOYMENT_NAME}` from `.env` (override with `N8N_CONTAINER`) |
| 8 | **Queue mode**: importing on container boot would race across main+workers and clobber data | sync is **manual/explicit only** — never an init hook; pull cleans stale local files before export |
| 9 | **Push is additive** — a workflow deleted from the repo is NOT deleted in n8n | by design (safe); delete in the UI/API if intended |

## Community Edition constraints (do NOT use enterprise features)
Verified: `/rest/settings` reports `saml/ldap/oidc = false`. Keep it that way — avoid relying on:
- **Team projects** (multiple) and **folders** — CE has only the single *personal* project.
- **RBAC / custom roles**, **external secrets**, **environments / git source-control**, **log streaming**, **variables** (enterprise subset), **SSO** (SAML/LDAP/OIDC).

This is why the sync scripts deliberately use only CE-safe mechanisms (`export:workflow` + `export:credentials`)
and do **not** use `export:entities` — that bundle is encrypted/opaque *and* carries enterprise constructs
(projects, roles, sharing) that would fail or be meaningless on CE.
