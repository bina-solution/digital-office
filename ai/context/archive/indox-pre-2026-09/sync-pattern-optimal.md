# Optimal INDOX sync pattern (deep-think + refactor plan)

## The principle: thin DISCOVER+REGISTER syncs; the INDOX table is the state machine

The Namer ("Mannual Documents Namer") is legacy: it was the *main processor* (per-file
download → OCR → name → rename drive file → move → upsert), built for single small batches.
Since then the **incoming_documents table became the processing state machine** (realtime
postgres trigger on row change + poll backstop → main "Incoming Documents 0.1.7" runs an action
loop: Process Document/OCR, figure_company_id, figure_document_type, get_company_name,
update_name = rename the drive file, find_link, check_from_office, extract_balance_sheet,
link_documents, query_* OCR fields, mark_completed). So the Namer's heavy work is now
**redundant** with the state machine and serializes badly under load.

### Optimal pattern (applies to ALL syncs)
**SYNC = thin discovery + idempotent batch-register. STATE MACHINE = all processing.**

1. **Discover** (cheap): `driveApi d:list` the source folder. The list response already includes
   `id, name, md5Checksum, createdTime, size, webViewLink, parents` (fields:["*"]) — so we can
   build identity + dedup hash WITHOUT downloading the file (no OCR, no binary fetch in the sync).
2. **Register** (batch of 25): build one row per file
   `{ ID(derived), NAME(original), SOURCE_TYPE:'GOOGLE_DRIVE_FILE', SOURCE_ID:id,
     LINK:drive-file-link, HASH:md5Checksum, SIZE, CREATED_AT:createdTime, STATUS:'IN_PROGRESS' }`
   and **batch-upsert in chunks of 25** via the existing UPSERT (dedup by HASH and by
   COMPANY_ID+SHORT_DOC_ID once known). Re-running is idempotent: same md5 → HASH dedup skips.
3. **Process** (state machine): the realtime trigger/poll picks up the new rows and the main
   action loop OCRs (via LINK), names (`update_name` renames the drive file in place; md5 unchanged
   so still dedup-safe), links, completes — exactly as it already does for gmail + BS-line rows.
4. **Move/cleanup** (decoupled): moving source→dest is NOT in the discovery sync (that per-file
   rename+move is what caused the Rename-File 404 churn). Either the state machine moves the file
   on `mark_completed`, or a separate idempotent cleanup pass moves only COMPLETED files. Leaving
   files in source is safe meanwhile (HASH dedup prevents re-register).

### Why batches of 25
- One `d:list` (up to 1000) → chunk into 25-row upserts: bounded payloads, bounded DB writes,
  bounded realtime-trigger fan-out per chunk → smooth high load instead of one giant or N tiny ops.
- The expensive step (OCR/Gemini) happens ONCE per doc in the state machine and is **cached** (BS
  extractor Crypto-hash → KVStorage expire:false; see [[indox-reset-workflows]] — cache must NOT be
  wiped by resets so re-runs don't re-bill AI). Discovery never OCRs.

### Per-sync application
- **GDoc/GDrive (general docs):** Runner builds sync pairs → per pair, list source → batch-25
  register GOOGLE_DRIVE_FILE rows. Retire the Namer's download/OCR/rename/move. (PRIMARY refactor.)
- **BS sync:** list BS source → batch-25 register BALANCE_SHEET rows; state machine runs
  extract_balance_sheet (cached) → link_documents (lines). Same thin pattern.
- **Gmail scanners/downloaders:** scanner tags unprocessed messages; downloader fetches +
  batch-25 registers GMAIL rows with the message link + hash; state machine processes. Keep
  scanners overlap-paced (see [[n8n-batch-concurrency-guards]]); gmail uses Gmail API quota
  (IMAP OVERQUOTA is separate — [[inbox-overquota-from-recycles]]).

### Correctness invariants (carry over)
- Dedup: same HASH → update; same COMPANY_ID+SHORT_DOC_ID → update. md5 from list = stable hash.
- Per-item refs: NEVER `$('<executeWorkflowNode>').first()` after an executeWorkflow boundary
  (stale/item-0 — the Rename-File 404 root); reference the splitInBatches loop driver or carry the
  field on the wire. See [[n8n-paired-item-batch-correctness]].
- State-machine rule: every action ends with a state-changing upsert (else lock leak / no progress).
