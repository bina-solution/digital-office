# INDOX Sync Control Plane — optimal design (sync-refactor-v2)

> Goal: make everything INDOX (settings / sync / management / observability) **solid, well-organised, minimal, fully consolidated**. Single source of truth = `sync_registry`. One front door = `indox api`. One source primitive used by every consumer.

## The core insight
There is exactly **one** generic operation against a sync's source: act on the items in a given **state**. It decomposes per source type and is driven entirely by `sync_registry`:

| primitive | drive (state = folder) | gmail (state = label) | table (downstream) |
|---|---|---|---|
| **LIST**(sync, state) | `drive op:list` folderId = `pairs[].{state}` | `gmail op:search` `label:{to_sync} -label:{others}` | `indox GET filter` |
| **CLAIM**(sync, items → in_progress) | `drive op:move` → `in_progress` | `gmail op:addLabels` `[in_progress]` (batched) | `UPSERT STATUS=IN_PROGRESS` |
| **ADVANCE**(sync, items → synced/failed) | `drive op:move` → `synced`/`failed` | `gmail op:removeLabels in_progress` + `addLabels synced/failed` | `UPSERT STATUS=…` |
| **INJECT**(sync, items → to_sync) | `drive op:upload`/`createFromText` → `to_sync` | `gmail op:append` + `addLabels to_sync` | `UPSERT` |

Today this primitive is **scattered and re-implemented 4×**:
- LIST(to_sync)+CLAIM → inside `SyncScanUnit0001` (the only good copy).
- ADVANCE(synced/failed) → **duplicated across all 5 processors** (drive move / gmail addLabels terminal writes — `SyncProcGDoc0001`, `SyncProcBS000001`, `9NWA`, `sEcV`, `LDrY`).
- LIST(per state, counts) → re-done in `sync api` STATUS **against the table** (wrong layer).
- LIST(in_progress/synced/failed)+ADVANCE(→to_sync) → re-done in `IndoxResetDrv001` against **raw Drive HTTP** (not `drive api`).

**Centralize the primitive → every consumer reuses it → the duplication collapses.** This is what "the sync search can be done by getting the api/sync status" was pointing at: the scanner's search and the status' search are the same `LIST`.

## Target architecture (layers)
```
sync_registry (settings row)         ← single source of truth
        │  drive: pairs[]{to_sync,in_progress,synced,failed} (folder IDs)
        │  gmail: labels{to_sync,in_progress,synced,failed} (KEYs) + dest_folder + search_extra + claim_label + processor_wf + batch
        ▼
indox api  (front door, INLINE_ACTION)
   • DATA verbs  (UPSERT/GET/GET_ALL/DELETE/TABLE_*) → data backend (supabase | sheets)
   • SYNC verbs  (SCAN/STATUS/RESET/INJECT)          → sync api
        ▼
sync api   (webhook /indox-manage + executeWorkflow; reads sync_registry)
   verbs, ALL implemented via the one primitive below:
     SCAN   = for each sync: LIST(to_sync) → CLAIM → dispatch processor → ADVANCE(synced|failed)
     STATUS = for each sync × state: LIST → count   → {sync:{to_sync,in_progress,synced,failed}}
     RESET  = for each sync × {in_progress,synced,failed}: LIST → ADVANCE(→to_sync)  [+ table clear + locks + execs]
     INJECT = INJECT(sync, items → to_sync)   [drive upload / gmail append]
        ▼
sync source  (THE primitive: LIST / CLAIM / ADVANCE / INJECT, keyed by (sync, state))
   resolves registry + gmail label names (KEY→name) + spaces→hyphens-for-search
        │                                   │
        ▼                                   ▼
   drive api (driveApi01)            gmail api (gmailApiRouter01 → imap|oauth)
   list/move/upload/...              search/addLabels/removeLabels/append/...
```

## What each component becomes
- **`sync source`** (new, or a labelled section of `sync api`): the only place that knows how a `(sync, state)` maps to drive-folder vs gmail-label, and the only place that builds the gmail query (label→hyphen) and resolves label KEY→name. Inputs: `{sync_def | sync_name, state, op:list|claim|advance|inject, items?, to_state?}`.
- **`sync api`**: thin verb dispatcher over `sync source`. STATUS/RESET/INJECT/SCAN are all loops over registry calling the primitive. Webhook `/indox-manage` for external (debug-run); executeWorkflow for `indox api`.
- **Scanner** (`SyncScanner00001`/`SyncScanUnit0001`): collapses into `sync api SCAN` (schedule trigger → SCAN). The Scan Unit's LIST+CLAIM move into `sync source`; the per-source branching lives there once.
- **Processors** (5): become **pure** — download + process (apitools/main) + register row (`indox UPSERT`). They **stop** doing claim/tag/move (remove T1–T5). The sync layer calls `ADVANCE(synced|failed)` based on the processor's success/failure return. → 5 processors lose their terminal source-writes; gmail dest-folder + outcome-label logic moves to `sync source`/registry.
- **Reset** (`IndoxResetFull/Drv/Gml`): retire — RESET becomes `sync source ADVANCE(→to_sync)` over the non-to_sync states + the table/locks/execs steps inside `sync api`. (Drive reset's raw-HTTP list → `drive api list`; gmail reset already moved to `gmail api`.)

## Verb contracts (sync api)
- `SCAN`            `{INLINE_ACTION:'SCAN', sync?}` → run the pipeline (all syncs or one).
- `STATUS`          `{INLINE_ACTION:'STATUS', sync?}` → `{per_sync:{name:{to_sync,in_progress,synced,failed}}, at_rest:(all in_progress==0)}` from **real source** (drive list / gmail search), optionally the table view too.
- `RESET`           `{INLINE_ACTION:'RESET', scope}` scope ∈ `full` | `{sync}` | `{sync,count:N}` (last N) | `{items:[id…]}`.
- `INJECT`          `{INLINE_ACTION:'INJECT', sync, items}` → source-inject into `to_sync` (drive upload / gmail append+label). `mode:demo` seeds companies/settings + a demo set.

## Scoping (RESET/STATUS/INJECT)
The primitive already takes `(sync, state)`; scoping is just filtering the LIST before ADVANCE:
- by **sync name**: pick one registry entry.
- by **count N** (last N): LIST then take newest N (drive: order by modifiedTime; gmail: search newest N).
- by **items**: skip LIST, act on the given ids directly.

## Came-to-rest signal (debug-run)
`STATUS.at_rest` = every sync's `in_progress` (source) == 0 AND table `IN_PROGRESS` == 0 AND no table updates in the last poll window. The debug-run loops STATUS until at_rest, reporting per-sync `to_sync→synced` drain rate (sync speed) + table COMPLETED growth rate (main speed).

## Migration plan (incremental, each step pushed + verified)
0. (done) `sync api` scaffold + webhook + `indox api` management dispatch; drive/gmail reset registry-driven; STATUS/INJECT built against wrong layer (table) — **to be replaced**.
1. **Build `sync source`** primitive (LIST/CLAIM/ADVANCE/INJECT, registry-driven, drive+gmail). Unit-test each op on one sync.
2. **STATUS → real source**: reimplement via `sync source LIST` per state. Verify counts match drive folders / gmail labels.
3. **RESET → primitive + scoping**: reimplement via `sync source ADVANCE(→to_sync)` + table/locks/execs; add sync/count/items scope. Retire `IndoxResetFull/Drv/Gml`. (Fixes the current executeWorkflow-nesting bug too.)
4. **INJECT → source-mode**: drive upload / gmail append via primitive; + demo-company.
5. **SCAN consolidation**: `sync api SCAN` calls LIST+CLAIM+dispatch; move ADVANCE(synced|failed) out of the 5 processors into the scan flow; processors become pure. (Biggest change — do last, behind a flag, battle-test heavily.)
6. **Cleanup**: retire redundant scripts (`reset-indox-state.py`, `supabase-reset.py`, `fresh-company-test-state-inject.py`, `_inject_*.py`, `_reg_*.sql`); de-hardcode `highload-inject*` to read registry + route through sync api; collapse the 3 ID sources (registry / flat settings / demo-company-state.yml) onto `sync_registry`.

## Patterns / principles
- **One source of truth** (`sync_registry`); **one front door** (`indox api`); **one source primitive** (`sync source`).
- **State lives in the source** (folder/label), the **table is downstream** — never conflate (the STATUS/INJECT mistake).
- **State transitions owned by the sync layer**, not processors — processors are pure transforms.
- **Label name resolution + spaces→hyphens** live in the primitive layer only (gmail api stays a dumb executor).
- **Batched gmail writes** (one addLabels STORE for all ids) — OVERQUOTA discipline.
- **executeWorkflow sub-WFs must be active+published** (publish-gate) — prefer fewer nesting levels; flatten where possible.

## Key IDs (current)
- Front door: `indoxApiRouter01`; data backends `indoxApiSupabase01` (supabase), `indoxApiSheets01`.
- sync api: `SyncApi0000000001` (webhook `/indox-manage`).
- Primitives: `driveApi01` (op:list/move/upload/download/update/delete/createFromText), `gmailApiRouter01`→`gmailApiImap01`/`gmailApiOauth01` (op:search/get/addLabels/removeLabels/listLabels/createLabel/append/send).
- Scanner: `SyncScanner00001`→`SyncScanUnit0001`. Processors: `SyncProcGDoc0001`, `SyncProcBS000001`, `indoxGmailDocDownloader01` (gmail doc), `indoxGmailBSDownloader01` (gmail bs), `indoxGmailLinkDownloader01` (gmail link). Batch Upsert `indoxDocBatchUpsert01`. Settings loader `indoxSettings01`.
- Registry: `settings.value where key='sync_registry'` — the live row is authoritative; the
  **declarative** source is `apps/indox/blueprint/fixtures/sync_registry.json` (config only),
  converged onto every deployment by `apps/indox/hooks/sync-registry-converge.py` from the
  `onboard` hook on every `bbox run`. Config from the fixture wins; the engine's runtime keys
  (`last_run`, `last_run_execution`, `last_run_url`) are never written; pipes absent from the
  fixture are never deleted. Regenerate with `--emit`, prove it offline with `--selftest`.
  (The former "canonical copy" `scripts/_reg.json` was untracked, stale and read by nothing —
  retired 2026-08-06 to `data/_registry_backup/`.)
</content>
