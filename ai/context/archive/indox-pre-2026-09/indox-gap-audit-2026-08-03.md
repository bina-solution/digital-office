# INDOX production gap audit — 2026-08-03

This audit supersedes the completion claims in `indox-final-report.md` where they conflict with the
live evidence below. It reviews the Console-authored Google Drive pipe `drive-לסינכרון-3`, the BFF,
sync-v3, Drive, Supabase, and the current uncommitted editor/backend changes.

## Verdict on the previous agent's changes

The work was directionally useful but incomplete and not production-ready.

- **Accepted:** Drive selectors must persist Google folder IDs, not display paths. The TypeScript
  change does that for folders selected from an already-loaded dropdown and the frontend build
  passes.
- **Accepted:** new Console-created entries need an explicit engine. Defaulting to `engine: "v3"`
  makes SCAN see them and does not rewrite existing entries.
- **Rejected as complete:** the editor does not write `projection: "on"`, does not choose a real
  processor, and does not validate the complete registry contract.
- **Regression:** inline-created Drive folders are assigned with `r.item.path`, while the dropdown
  now uses `r.item.id`.
- **Regression:** blank archive/failure choices derive `<folder-id>/ארכיון` and
  `<folder-id>/נכשל`. These are paths made from an opaque Google ID, not folder IDs. The live
  registry already contains the malformed failure value.
- **Missing tests:** no sync registry route or editor test covers IDs, defaults, projection,
  processor selection, Gmail, legacy path values, or multiple pairs.

## Live proof

Observed on the local compiled stack on 2026-08-03:

- Google source folder `1cUnUMkKRHd7L2xSl2SSWuRJwygtc6zfg`: **5 files**.
- Google archive folder `1118ghrD6L-98vlaxafLQ2EUOZgedPvrD`: **0 files**.
- Registry: correct connection and source/archive IDs; `engine: "v3"`; no `processor_wf`; no
  `projection`; malformed `failed_folder`.
- Board API: **0 items** in every state.
- Reconcile API: `source_items: 0`, `ledger_rows: 5`, `divergent: 0` — a false green result.
- Ledger: **5 delivered** rows under
  `incoming-documents-main/drive-לסינכרון-3`.
- Document table: the five ledger `doc_id` values exist, but all five rows have the source **folder
  ID** in `SOURCE_ID`, no `TYPE`, and status `MISSING_COMPANY_ID`.
- One JPEG has size 0 and hash `d41d8cd98f00b204e9800998ecf8427e`; empty-content validation did
  not stop it from being recorded as delivered.

## Why five remote files produce zero visible items

There are four independent contracts, and only two worked:

1. **Discovery worked in n8n.** `syncV3Unit0001` listed the selected Google folder through the Drive
   service and found five files.
2. **Ledger delivery worked.** The unit claimed each file and `syncV3Deliver0001` recorded five
   delivered ledger rows. Future scans anti-join against those rows, so the five IDs are no longer
   eligible for delivery.
3. **Board discovery is a different implementation and failed.** `_drive_snapshot()` reads only
   `public.drive_files`, the local Drive inventory. It never lists the registry's selected Google
   connection. `_entry_items()`, registry counts, `/sync/items`, and reconcile all consume that
   empty snapshot, so they report zero even while Google contains five files.
4. **Projection was disabled.** With no `processor_wf`, Main selected `mode: "thin"`; thin mode sets
   `proj_on` only when `projection === "on"`. The editor never writes that field. Therefore delivery
   did not move the files to `בוצע`. The ledger now excludes them from future work even though they
   remain in `לסינכרון`.

The pipe also did not perform full INDOX processing. No `processor_wf` means thin metadata delivery.
The thin Drive row incorrectly writes `list_ctx.folderId` to `SOURCE_ID` instead of
`platform_id`, explaining why the five table rows cannot be joined back to their five files.

## Required work

Tasks are ordered by dependency. Do not reset ledger rows or move files until task 0 preserves the
current evidence and the repair path is proven on one item.

### P0 — repair the current five without duplication

- [ ] Export the affected registry entry, five ledger rows, five document rows, and both remote
  folder listings to a timestamped evidence artifact.
- [ ] Define the intended document processor/type policy for this pipe. A generic Console pipe must
  never silently mean thin test mode.
- [ ] Correct the five document rows' per-file identity (`SOURCE_ID`) or re-drive through the real
  processor with idempotent matching. Preserve the existing hashes and ledger evidence.
- [ ] Add a projection-repair operation that moves only ledger-delivered IDs still present in the
  configured source folder to the configured archive. It must not re-deliver documents.
- [ ] Prove one file: document row valid, ledger still one row, source absent, archive present,
  board/reconcile consistent. Then repair the remaining four.
- [ ] Quarantine or replace the zero-byte JPEG; never call an empty payload delivered.

### P0 — one live source adapter for every reader

- [ ] Replace `_drive_snapshot()` for registry Drive pipes with live listing through the Drive
  service using `(connection, folder_id)`. Keep local Drive as one connection, not as a special
  Supabase-only path.
- [ ] Use the same adapter in registry enrichment, `/sync/status`, `/sync/items`, reconcile, move
  origin detection, and run diagnostics.
- [ ] Key bounded caches by instance, connection, folder, and state; invalidate after run, move,
  registry edit, or projection repair.
- [ ] Return `checked: false` with the service error when a source cannot be listed. Never convert
  an unreachable remote source into zero items or `divergent: 0`.
- [ ] For delivered-but-unmoved IDs, show a divergence state rather than ordinary waiting or synced.

### P0 — make the registry contract valid at the server boundary

- [ ] Define and validate source-specific schemas for Drive and Gmail entries. Reject unknown,
  missing, inaccessible, or cross-connection locations.
- [ ] For Drive, persist IDs for every role: `to_sync`, `synced`, `failed`, and optional
  `in_progress`. Never derive a child path from an ID.
- [ ] Fix inline creation to select the returned Drive folder ID; keep Gmail label paths unchanged.
- [ ] Make archive and failure destinations explicit required selections, or create them through
  the owning service and persist their returned IDs.
- [ ] Add an explicit post-success behavior control and persist `projection: "on"|"off"`. Default
  production document pipes to move/archive; require confirmation for read-only behavior.
- [ ] Reject conflicting alias pairs (`from != to_sync`, `to != synced`,
  `failed_to != failed`) instead of preserving an ambiguous row.
- [ ] Validate `connection` consistently. Fix Gmail's `connection` versus `connection_id` split in
  Main and the editor/API contract.
- [ ] Disallow pipe rename while ledger/cursor/attempt/state rows exist, or implement one atomic
  identity migration. A warning is not sufficient.
- [ ] Make registry writes concurrency-safe; the current settings-blob read/modify/write can lose
  simultaneous edits or engine state updates.

### P0 — production processing semantics

- [ ] Remove thin mode from the ordinary Console creation path. Keep it test-only and visibly
  labelled, or require an explicit advanced choice.
- [ ] Add processor templates by source/document class and require a valid `processor_wf` for a
  production pipe. Validate that the workflow exists, is published, and supports the source.
- [ ] Fix thin Drive `SOURCE_ID` to the file `platform_id`; store folder identity separately.
- [ ] Define delivered as both a valid downstream document result and a durable ledger record.
  Metadata-only rows with `MISSING_COMPANY_ID` must not look like completed ingestion.
- [ ] Validate non-empty bytes, content hash, supported MIME, and processor result before RECORD.
- [ ] Make projection failure explicit. The current move uses continue-on-error after RECORD; the
  run must report `delivered_not_moved` and retain a repairable state.
- [ ] Define ordering/compensation for document write, ledger RECORD, and source projection so every
  partial failure is detectable and idempotently repairable.

### P1 — operator truth and recovery

- [ ] Show source count, claimed count, delivered count, projected count, failed count, and
  divergence count as distinct facts.
- [ ] Show the last run's discovered/claimed/delivered/failed/projected numbers and execution link.
- [ ] Add safe actions for retry failed, release stale claim, project delivered item, and reconcile
  one pipe. Enforce legal transitions server-side.
- [ ] Surface structured processor failure codes and actionable Hebrew messages; do not infer all
  failures only from document `STATUS` prose.
- [ ] Make per-pipe `schedule_min` real through `sync_pipe_state`, or remove/disable the editable
  field. Main currently sweeps every enabled v3 pipe every 15 minutes.
- [ ] Show missing/inaccessible folder and connection ownership/permission errors before save and
  on every pipe card.
- [ ] Add paging and bounded listing for large folders without making a count silently partial.

### P1 — complete authoring and tenancy

- [ ] Build a real multi-pair editor; preserving hidden pairs is safer than deleting them but is not
  complete authoring.
- [ ] Create and configure the `דוחות גיול/לסינכרון` and `דוחות גיול/בוצע` pipe through Console
  using an identity that can create the folders. Prove it independently before scaling.
- [ ] Finish self-service instance provisioning (`public.run_sql` replacement or a safe owned DDL
  service); the UI creation flow is still not end to end.
- [ ] Make active instance per authenticated operator, not one deployment-wide JSON pointer.
- [ ] Remove the remaining v1/label-tail literal instance pins and prove two instances on different
  connections concurrently.
- [ ] Route document writes through one repo-scoped delivery contract; retire the duplicated diff
  implementation across direct n8n nodes.

### P1 — consolidation

- [ ] Choose one authoritative state model. The current system uses ledger state for scheduling,
  source locations for the board design, and separate local inventory for Drive reads.
- [ ] Consolidate LIST/CLAIM/ADVANCE/PROJECT behind one source service used by scanner, status,
  board, reconcile, reset, repair, and tests.
- [ ] Move source transitions out of legacy processors; processors should return a structured
  processing result and never independently move/label items.
- [ ] Retire v1 scanner/reset paths only after parity tests prove every live processor through v3.
- [ ] Move mail label-rule ownership to Mail and remove the INDOX-to-Mail layer inversion.
- [ ] Remove stale comments/docs that claim local `drive_files` is live remote state or that all
  final-plan phases are complete.

### P1 — tests and release gates

- [ ] Add BFF tests for registry create/patch validation, Drive IDs, Gmail labels, inline creation,
  aliases, projection, processor selection, rename protection, multiple pairs, and degraded writes.
- [ ] Add adapter contract tests proving local Drive and Google Drive return one canonical item and
  folder shape.
- [ ] Add sync-v3 tests for remote list, zero-byte rejection, thin-mode isolation, processor
  delivery, projection success/failure, RECORD failure, retries, crashes, and idempotent repair.
- [ ] Add integration tests asserting board/status/reconcile/n8n all observe the same remote files.
- [ ] Add an end-to-end Console test: create pipe, upload document, run, observe four states,
  validate document fields, verify remote move, refresh, and rerun with no duplicate.
- [ ] Run the same E2E for Gmail, local Drive, Google OAuth Drive, and Google Service Account Drive.
- [ ] Gate release on `bbox indox test`, flow QA desktop/mobile, tenancy proof, source/ledger
  reconciliation, and a real one-document production canary.

## Definition of done

INDOX is not complete when the ledger is green. It is complete when one Console-authored pipe can be
proved from source to archive: the same remote item is visible everywhere; it is claimed once;
processed by the intended processor; written once with per-file provenance, type, company, hash,
connection, and resolvable origin; projected once; recoverable after every partial failure; isolated
between instances; and represented identically by the card, board, status, reconcile, ledger, and
document table.