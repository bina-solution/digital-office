# INDOX — expected behaviour (operator spec)
# Reconsolidated 2026-06-26 from the full 6-day build session + the design docs
# (indox-sync-control-plane.md, sync-pattern-optimal.md, indox-runtime-attention.md,
# indox-debug-run.md). Canonical runtime spec; the product goal lives in ai/context/goals.txt.

Backend: **supabase** (Redis toggle `n8n.indox.data_backend = supabase`). Tenant: person2@example.com.
Goal: lightning-fast, out-of-the-box, high-load-proven. A fresh demo state at high load must reach
**all COMPLETED within ~10 minutes** — no errors, no human review, no spurious MISSING_TYPE.

## Architecture in one line
Single source of truth = **`sync_registry`** (a Settings row). One front door = **`indox api`**. One source
primitive = **`sync source`**. Full design: `ai/context/indox-sync-control-plane.md` + `sync-pattern-optimal.md`.

## The 5 syncs and their states
- 5 syncs, all registry-driven, all following the SAME config-driven pattern:
  **drive-gdoc, drive-bs, gmail-doc, gmail-bs, gmail-link**.
- Each sync has 4 states **in its SOURCE** (drive = folders, gmail = labels):
  **to_sync -> in_progress -> synced / failed**. State lives in the source; the table is downstream.
- The one generic operation is "act on the items in a given state", decomposed by the primitive:
  - **LIST**(sync, state)   — drive list folder / gmail search label / table GET.
  - **CLAIM**(items -> in_progress) — drive move / gmail addLabel(in_progress) / UPSERT IN_PROGRESS.
  - **ADVANCE**(items -> synced|failed) — drive move / gmail re-label.
  - **INJECT**(items -> to_sync) — drive upload / gmail append+label.
- A scanner reads the registry's 3 working tags/folders (to_sync / in_progress / synced[+failed]) and runs
  `LIST(to_sync) -> CLAIM -> dispatch processor -> ADVANCE(synced|failed)`.

## Thin sync, table is the state machine
- **SYNC = thin discover + idempotent batch-register.** Discovery does NOT OCR — it uses the drive `list`
  md5Checksum (or gmail message id) to build identity + HASH/dedup without downloading the file.
- Register in **chunks of 25** via UPSERT (dedup by HASH, and by COMPANY_ID+SHORT_DOC_ID once known).
  Re-running is idempotent (same md5 -> HASH dedup skips).
- **STATE MACHINE = all processing** (the main loop): OCR, figure_document_type, figure_company_id,
  get_company_name, update_name (renames the drive file in place), find_link, check_from_office,
  extract_balance_sheet, link_documents, query_* OCR fields, mark_completed.
- **Processors are PURE** (download + process + register row). State transitions are owned by the sync layer,
  NOT the processors. Label-name resolution and spaces->hyphens live in the primitive only.
- **Move/cleanup is decoupled** from discovery (per-file rename+move caused the Rename-File 404 churn). Files
  left in source are safe meanwhile — HASH dedup prevents re-register.

## Sources & per-case behaviour

### Gmail (tenant inbox, label-driven)
- **Invoice** -> add to INDOX table, fully process to COMPLETED. If the doc already exists (prior file / BS)
  -> **update the existing row**, never duplicate.
- **Shipment** -> same (process to COMPLETED; update existing row if present).
- **Invoice + shipment in one mail** -> download both, verify both, both fully processed.
- **Garbage (e.g. logo) + invoice** -> download the invoice; ignore junk if identifiable; if junk can't be
  identified, save it as `TYPE = UNKNOWN` (must NOT block the invoice).
- **Link to an invoice** (URL, not attachment) -> save and fully process.
- **Balance sheet (BS)** -> save -> extract -> open/update (link) document lines for **all** BS lines ->
  COMPLETED. A BS lists invoices to be paid; every line is extracted and linked (`main -> bs -> link_documents`).
- **BS + invoice in one mail** -> save both, process both properly.
- **Up to 10 attachments in one mail** -> all processed properly.

### Google Drive sync folders (settings-driven source/dest pairs, up to 10 each)
- **GDoc sync** (GeneralDocs source -> dest): invoices / shipments / other docs fully processed to COMPLETED.
- **BS sync** (BalanceSheet source -> dest): fully processed to COMPLETED.
- Source files move to their paired dest folder on completion (decoupled cleanup, not in discovery).

### Line / table
- Adding a line with just a **link** is a first-class source — save and fully process.

## Document types
INVOICE, SHIPMENT (delivery note), BALANCE_SHEET, ORDER/PURCHASE, UNKNOWN. A test's doc-type mix must span
these — not only balance sheets and not only from Google Drive.

## Dedup / update rules (must hold across all sources)
- Same **document HASH** -> update the existing row (never duplicate). md5 from `list` = stable hash.
- Same **COMPANY_ID + SHORT_DOC_ID** -> update the existing row.

## Balance-sheet linkage (core requirement)
- All lines of a balance sheet are opened into the main INDOX table (`main -> bs -> link_documents`); each
  BS line becomes / links to an invoice row; the BS reaches COMPLETED.

## Main loop / action dispatcher
- A realtime Postgres trigger on row change (+ a poll backstop) drives the main workflow. Main has a
  **built-in loop**: after executing actions it loops back to GET-by-id and find the next actions, until the
  doc is fully processed.
- **Every action ENDS with a state-changing upsert** (else lock leak / no progress).
- **max-actions-per-doc** guard in Settings (e.g. 50) — a safety stop against infinite action loops.

## Lock protocol (intended)
- Main **locks on action start**; the action runs; **Batch Upsert writes the row and UNLOCKS** — lock per
  action, unlock on the row update. The line-change drives the next action.
- A doc found stuck/locked means a **bug in the process**, not something to unlock by hand (except a new run).
- Best-effort link: the link action marks `BS_LINK_DOCUMENTS_COMPLETED` and unlocks early so a flaky search
  never strands a doc.
- (History: a "gridlock" was root-caused to **check_from_office** — a warehouse Search with 0 input that
  skipped — NOT the lock itself. Watch for 0-input skips, not just locks.)

## States & final state
- Flow: BOOTSTRAP -> IN_PROGRESS -> (MISSING_COMPANY_ID / MISSING_TYPE / NEEDS_REVIEW / error-parking) -> **COMPLETED**.
- **COMPLETED** = type figured, company resolved, fields extracted, BS lines linked — terminal success.
- **NEEDS_REVIEW** = flagged for a human; must be rare/eliminated — never from the pipeline being too slow.
- **MISSING_TYPE** only for genuinely unidentifiable documents.
- **Error-parking** (e.g. `BS_EXTRACTION_FAILED`, `API_TOOLS_FAILED`) is GOOD, deterministic behaviour — a
  clean stop, not a crash.

## Error-handling policy
- Every step that cannot complete **raises an error** — visible in **GlitchTip** and **n8n executions**.
  No silent failures.
- On a failed OCR / AI extraction (null / bad result): **view the document yourself** and decide bug vs
  genuinely-unextractable before "fixing".

## Observability columns (in the INDOX table)
- **`ERRORS`** (renamed from REQUIRED_ACTION): each failed action appends its error here.
- **action-history**: appended at the end of every action's existing upsert — `(ACTION, timestamp, execution_id)`.

## Settings-driven everything (no hardcoding)
- Settings holds: `sync_registry`, companies, `tag_rules`, the label table (KEY -> name, label_id), the full
  **JSON queries** (not just keywords), from-office logic (redis-key), old-document cutoff, max-actions, doc mix.
- **Labels: fully Hebrew, consolidated.** Never declare a label by NAME — only its **KEY**; resolve the name via
  Settings (tag_rules `TYPE`->`KEY`; KEY->name cached in the label table). `תוויות-טופל` = the
  "label-engine has processed this mail" tag.
- Old-document cutoff is a Setting (e.g. ~2 years back) so nothing is missed and no functionality is lost.

## Reset / inject / status (control-plane verbs, native in n8n)
Routed `indox api -> sync api` (webhook `/indox-manage`), registry-driven — not scripts.
- **RESET** (scope: full | by sync | last-N | item ids): reverse source state (drive move
  in_progress/synced/failed -> to_sync; gmail strip those labels) + clear the table (keep `__bootstrap__`) +
  clear `n8n.process_lock.*` + kill running INDOX execs. Lets you re-drive without re-injecting.
- **INJECT** (source-mode): drive upload / gmail append+label -> to_sync; `mode:demo` seeds companies/settings
  + a demo set.
- **STATUS**: real per-sync source state `{to_sync, in_progress, synced, failed}` + `at_rest`.
- **AI-extraction cache** (BS/invoice Crypto-hash -> KVStorage, expire:false) MUST survive resets — never wipe
  it, or re-runs re-bill the AI.

## Performance / quality bar
- Lightning fast. At high load, **all docs COMPLETED within ~10 minutes**.
- Zero errors, zero stuck IN_PROGRESS, zero unnecessary NEEDS_REVIEW, zero spurious MISSING_TYPE.
- High-load test profiles: e.g. **200 docs (10 BS, rest mixed)**, monitored from empty table to rest; or
  25 BS (10 gmail / 10 drive / 5 link) + 50 each invoice/shipment/unknown per source. Stretch: 100+/type/source.

## Came-to-rest & verification (debug-run)
- **came-to-rest** = every sync's source `in_progress` == 0 AND table `IN_PROGRESS` == 0 AND no table updates
  in the last poll window.
- Loop (`ai/context/indox-debug-run.md`): RESET -> inject -> trigger syncs -> 30s monitor batches (read->think
  ->continue) until rest -> report **sync speed** (to_sync->synced drain/min) + **main speed** (COMPLETED/min)
  + time-to-rest + error families.
- Poll the **table** signal for rest (fast). gmail STATUS is slow under OVERQUOTA — use it only as a snapshot.
- Don't passively wait on status counts — build the EXACT per-doc execution trace
  (`python3 scripts/indox-doc-trace.py`) and verify behaviour/stability/speed per document.

## Known constraints / gotchas
- **Gmail OVERQUOTA**: 3 of 5 syncs (gmail-doc/bs/link) get throttled by Google under heavy/long sessions ->
  gmail paths slow. This is Google throttling, not our bug; drive + table paths stay fast. System must work
  correctly under slow responses and never over-quota.
- **executeWorkflow nodes must be `typeVersion: 1.1`** (v1 throws "Workflow does not exist").
- **Never `$('<executeWorkflowNode>').first()`** after an executeWorkflow boundary (stale item-0 = the
  Rename-File 404 root) — reference the splitInBatches loop driver or carry the field on the wire.
- Supabase TEXT columns store booleans as strings — Determine Action normalises string booleans
  (`indox-supabase-text-boolean-bug`); else `if(!doc.X_COMPLETED)` gates silently fail.
- n8n 2.17 publish gate: main + every executeWorkflow sub-WF MUST stay active + activeVersionId or the poll
  can't dispatch. Re-verify active state after any import/restart (DNS flakes during `publish:workflow` can
  deactivate it).
- Restart leaves stale `n8n.process_lock.doc_step.*` locks -> docs freeze at "Process Blocked Error"; RESET
  clears them (long-term: shorter TTL or a boot hook). Host gives Docker ~12.5G.
