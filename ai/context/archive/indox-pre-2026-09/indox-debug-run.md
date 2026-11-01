# INDOX debug-run — fast reset → drive → came-to-rest verification

Goal: quickly take the INDOX system from a known state to **came-to-rest**, watching runtime in small batches, and report sync + main processing **speed**. Run this to validate the current state on stable ground before/after any change, and as the loop for high-load optimization work.

> Pre-req gotcha: any n8n Execute Workflow node must be `typeVersion: 1.1` (v1 throws "Workflow does not exist"). See memory `n8n-executeworkflow-typeversion-gotcha`.

## Control plane (live)
One webhook entry, registry-driven, routed `indox api → sync api → sync source → drive/gmail api`:

- **Webhook:** `POST http://localhost:5678/webhook/indox-manage` with `{"INLINE_ACTION": "<verb>"}` (also reachable internally via `indox api` `INLINE_ACTION` dispatch).
- **`RESET`** → full reset: kill INDOX execs + clear `incoming_documents` (keep `__bootstrap__`) + clear redis `n8n.process_lock.*` + reverse drive/gmail per `sync_registry` (drive: move `in_progress/synced/failed`→`to_sync`; gmail: strip those labels). Slow when gmail is OVERQUOTA-throttled.
- **`STATUS`** → real per-sync source state `{per_sync:{<sync>:{to_sync,in_progress,synced,failed}}, waiting, in_progress, at_rest}` via live drive `list` + gmail `search`. **Slow** (12 serial IMAP searches under throttle ≈ minutes) — use as a start/end snapshot, NOT for tight polling.
- **`INJECT`** → source-mode (drive upload to `to_sync` / gmail append+label) is the next phase; for now inject via the existing scripts (below).

Key ids: `SyncApi0000000001` (sync api), `SyncSource000001` (sync source), `indoxApiRouter01`, `IndoxResetFull01`(IndoxResetFull01)→`IndoxResetDrv001`/`IndoxResetGml001`, `driveApi01`, `gmailApiRouter01`. Registry: `settings.sync_registry` (5 syncs: drive-gdoc, drive-bs, gmail-doc, gmail-bs, gmail-link).

## The run
All commands run from repo root. SB = `docker exec supabase-db-shlomo-laptop psql -U postgres -d postgres -tAc`. n8n DB = `docker exec n8n-postgres-shlomo-laptop sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "…"'`. Redis needs `-a $REDIS_PASSWORD`.

### 1. RESET (always start here)
```
docker exec n8n-shlomo-laptop sh -lc 'wget -qO- --header="Content-Type: application/json" --post-data="{\"INLINE_ACTION\":\"RESET\"}" --timeout=600 http://localhost:5678/webhook/indox-manage'
```
Verify reversal: table → ~0 (`SB "select count(*) from incoming_documents where \"ID\"<>'__bootstrap__'"`), locks → 0, no running INDOX execs. (Optional rich check: `STATUS` → all `synced`≈0, `to_sync` repopulated.)

### 2. Inject (only when you need fresh data — reset reuses existing source artifacts)
Use existing scripts (source-mode api inject is pending): `bbox indox inject-demo-company-state` (blueprint-driven, routed through indox api) or `scripts/highload-inject.py` / `highload-inject-links.py` for high-load. Reset reverses sync state so you can re-drive without re-injecting.

### 3. Trigger syncs
```
# trigger the scanner (drive + gmail) — fans out per sync_registry unit
docker exec n8n-shlomo-laptop sh -lc 'wget -qO- --post-data="" http://localhost:5678/<scanner trigger>'   # or bbox b42 / the scheduled run (every 15m)
```
(Scanner `SyncScanner00001` runs on a 15m schedule; trigger manually to start immediately.)

### 4. Monitor loop — 30s batches, read→think→continue until rest
Each batch run ALL of:
```
# running execs by workflow
<n8n DB> "select w.name,e.status,count(*) from execution_entity e join workflow_entity w on w.id=e.\"workflowId\" where e.\"startedAt\">now()-interval '2 min' group by 1,2 order by 1"
# table state (FAST came-to-rest signal)
SB "select \"STATUS\",count(*) from incoming_documents where \"ID\"<>'__bootstrap__' group by 1 order by 2 desc"
# in-flight + recent completion rate (speed)
SB "select count(*) filter(where \"STATUS\"='IN_PROGRESS') inprog, count(*) filter(where \"STATUS\"='COMPLETED' and updated_at>now()-interval '1 min') completed_last_min from incoming_documents"
# errors (exclude known gmail OVERQUOTA family)
<n8n DB> "select w.name,count(*) from execution_entity e join workflow_entity w on w.id=e.\"workflowId\" where e.status in ('error','crashed') and e.\"startedAt\">now()-interval '2 min' group by 1 order by 2 desc"
# any-concurrency runtime + glitchtip (if needed): check any-concurrency dashboard / glitchtip projects
```
Sleep ~30s between batches. Stop when **came-to-rest**: `IN_PROGRESS = 0` AND no `COMPLETED` in the last poll window AND no new errors (gmail OVERQUOTA excepted — needs user login). Optionally confirm with one `STATUS` snapshot (all `in_progress`=0 at source).

### 5. Report speed (every run)
- **Sync speed:** `to_sync → synced` drain rate (docs/min) from STATUS deltas, or drive/gmail processed counts/min.
- **Main speed:** `COMPLETED` growth rate (docs/min) from the table over the run.
- Time-to-rest, peak concurrency, error families seen.

## Known constraints
- Gmail (3 of 5 syncs) is OVERQUOTA-throttled under heavy/long sessions → STATUS + gmail reset + gmail reprocess are slow; drive + table paths are fast. For rest-polling use the **table** signal (fast), not gmail STATUS.
- Memory: host gives Docker ~12.5G; n8n heaps capped < cgroup (see `stack-memory-pressure-flakiness`). Don't pile manual triggers on scheduled runs.
- Restarts leave doc_step locks — RESET clears them; if a run stalls, check `n8n.process_lock.doc_step.*`.

## Next to finish this control plane
Source-mode `INJECT` (drive upload/gmail append via the primitive), scoped `RESET` (by sync / last-N / item ids), a fast `STATUS` variant for polling, and retiring redundant reset/inject scripts onto `sync_registry`. Design: `ai/context/indox-sync-control-plane.md`.
