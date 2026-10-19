# INDOX sync completeness vs ground truth (lz_census) — 2026-08-25

## Ground truth
`public.lz_census` (8,862 rows, `label`+`fid`) — the past-6-months collection of every real
client item the syncs saw: `scanned_synced` 4,634 · `chat_synced` 2,296 · `scanned_failed_real`
918 · `chat_failed` 891 · `scanned_failed_registry` 101 · `scanned_source` 20 · `chat_source` 2.

## Reconciliation (fid ↔ docs by SOURCE_ID + LINK-embedded id, hash-join over all docs)
| label | matched | missing |
|---|---|---|
| scanned_synced | 3,134 | **1,500** |
| chat_synced | 1,892 | **404** |
| scanned_failed_real | 582 | 336 |
| chat_failed | 542 | 349 |
| scanned_failed_registry | 90 | 11 |
| scanned_source / chat_source | 3 / 0 | 17 / 2 |

## Proof the scanned_synced misses are REAL losses (2026-08-25)
Sampled 5 missing fids: **all 5 exist on Google Drive (HTTP 200 via the drive service,
service-account connection; 404 on local)** — live, downloadable client files (1.0–1.9MB).
Content-hash cross-check on 3: downloaded bytes' md5 matches **NO document HASH** in
`incoming_documents` — the files are genuinely unrepresented, not merely unmatchable
(rules out moved-id and merge-tombstone explanations).

## Root cause (best-supported)
The census marked them synced when their docs existed; the doc rows were later destroyed by
dev-era resets/wipes (cf. `sync_cursor_bak_20260809_gmail_backfill` era). The files were
already MOVED to dest folders by the original sync, and the sync registry/cursor holds them
as done — so the folder scans will never re-deliver them. Silent permanent loss without a
recovery feed.

## Also verified this pass (clean)
- Months-back compliance: `old_document_months_back=6` + `OldDocumentMonthsBack=6`; 0 docs
  created in the last 7 days carry a DOC_DATE older than the cutoff.
- No restartable parked failures remain: EXTRACTION_FAILED / MAX_ITERATIONS /
  ACTION_REQUIRED / API_TOOLS_FAILED all hold **0 rows** (the 2026-08-24 mass ACTION_RESTART
  wave consumed the dev-era backlog).
- Gmail intake leak (368 conn-less docs/14d) FIXED at the source: both downloaders now
  deliver `LINK_CONNECTION` (live-verified; purely additive — every sync-era field the wrap
  produces, company/type/ids/hints, is preserved; extraction stays with the state machine).

## Repair plan (in progress)
1. **Recovery feed** for the missing synced fids: walk each fid, fetch bytes+meta via the
   drive service (service-account connection), and deliver through the SAME central upsert
   the syncs use (`indoxDocBatchUpsert01`) with full sync-wrap fields (LINK,
   LINK_CONNECTION, NAME, HASH, SIZE, SOURCE_TYPE, SYNC_NAME='census-recovery-2026-08-25')
   — existing mechanism, no new heuristics; the state machine takes over from there.
   Blocker to resolve first: a metadata route for name (the /download op returns bytes only).
2. chat_synced 404 misses: same treatment after fid→chat-store attribution.
3. failed_real/chat_failed (336+349 unmatched): these were failures at census time — feed
   them through the same recovery (they never synced at all).
4. Mail Label Engine verification + labeled-mail→doc coverage: pending (engine health query
   in this pass had a bug; rerun and extend the census mail-by-mail).

## Status
- **Recovery LIVE (2026-08-25 night)**: `indoxCensusRecovery01` (new blueprint workflow,
  webhook `indox-census-recovery`) delivers each missing file through the central upsert
  (`indoxApi01`) with full sync-wrap fields; TYPE deliberately absent → base extraction claims
  it. Pilot 25/25 delivered (`STATUS=IN_PROGRESS`, first doc typed within minutes); full feed
  for `scanned_synced` + `scanned_failed_real` misses running in batches of 50 (idempotent —
  deterministic `rec_<fid>` ids). chat-class location probe included; chat recovery follows
  attribution.
- Name metadata came free: the drive service's `/download` passes the adapter's
  `Content-Disposition` through (verified: real supplier filenames, UTF-8).

## Latent findings surfaced by the recovery build (for follow-up)
- `indoxV2Upsert01` ("indox-v2 Upsert (central)") is **active=false, unpublished** — every
  lane's `Upsert (central)` runs it via published-parent semantics only. New workflows cannot
  reference it; publish-model repair recommended.
- The workflow id `indoxDocBatchUpsert01` **does not exist** — downloader nodes carry it in
  stale `cachedResult*` fields while their real `value` resolves to `indoxApi01`. Cosmetic but
  misleading; clean on next touch.
- n8n activation refuses new workflows referencing unpublished subs — the mechanism that
  exposed both of the above.
The priority-table final cycle (separate) runs concurrently and is unaffected.

## Night finding: Gmail IMAP concurrency saturation (2026-08-25 ~00:40)
The completion wave (thousands of docs finishing → per-doc Apply-Gmail-Labels + discovery all
through the Gmail IMAP connection) saturated **Gmail's 15-simultaneous-connections cap**:
`imaplib [ALERT] Too many simultaneous connections` → mail api / mail discovery 500s in bursts.
Ruled out: local dovecot (doveadm who = 0 sessions, limit 10 untouched); mailapi container
health (restarted clean, re-erred — the cap is at Gmail). Self-limiting: label actions are
post-completion cosmetics, discovery is cursor-based (delayed, not lost). **Morning fix:**
a small IMAP connection pool/semaphore in mailapi (cap ~8 concurrent Gmail sessions,
queue the rest) so completion waves can never starve discovery.
