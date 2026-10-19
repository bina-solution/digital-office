# SIX-MONTH FULL SYNC — MORNING PLAN (2026-08-05)

**Goal (owner):** wake up to the INDOX app loaded with the full past-6-months legacy gsheet
documents, all syncs proven working, and every leftover unsynced document in gmail/gdrive
caught up, synced and COMPLETED.

## Current live state (probed 2026-08-05 02:xx)
- Stack healthy; `platform-os-refactor` HEAD `7fdab2fb`; mail_organizer gate 2/2 GREEN.
- Registry: 7 pipes. drive-invoices (SA conn) synced=4 to_sync=1. All other 6 pipes:
  conn=None, counts 0 — **they have no real connection/folder binding yet.**
- mailapi connections: only 2 LOCAL imap (admin/user2). **No real Gmail.**
- drive connections: SA (`drive_google_service_account-ea660043`) + 2 local. **No OAuth.**
- Legacy sheet `1Wu3hyF_4TvfU41xCGaINtJD81Or0wBSwD1djp4tVJEo` readable in browser42
  (hacohen@gmail session). Schemas already match (76 identical columns).

## Workstreams (run in parallel; wall-clock target 2h setup + overnight processing)

### A. Legacy data load (gsheet → supabase)
1. Fetch `הגדרות` tab (8 keys: DocumentsToProcessFolder etc.) → drive folder IDs.
2. Fetch `חברות`/Companies → companies table (company figuring → COMPLETED).
3. Fetch `הגדרות תגיות במייל` → tag_rules parity check.
4. Fetch `מסמכים נכנסים` (gid 542119184, 46k rows) via CSV export → filter DOC_DATE >=
   2026-02-05 (past 6 months) → bulk-load incoming_documents (direct column map).
5. Verify: counts by STATUS/TYPE in indox UI + supabase.

### B. Gmail live connection
1. Obtain person16@example.com app password (browser42 → myaccount.google.com, or stored).
2. Create mail_imap_gmail connection in mailapi; verify INBOX + labels list.
3. Bind gmail-doc / gmail-bs / gmail-link / mail-private registry entries to it
   (connection + labels to_sync/synced/failed + drive_profile_id=admin).
4. Run label engine against real gmail → past-6-months mail gets *_TO_SYNC labels.

### C. Drive live sync
1. Verify SA can LIST the hacohen folders (shared with SA) via drive app API.
2. Create/update drive-gdoc + drive-bs entries: SA connection + pairs from legacy
   settings folder IDs (to_sync/synced/failed per pair).
3. drive-invoices: push through the 1 remaining item.

### D. Run everything + prove it
1. Trigger all pipes (POST /sync/registry/<name>/run) — staggered.
2. Monitor sync_ledger + registry counts until to_sync=0.
3. browser42 QA stimulation (MSG 117): drop files into sources, send test mails,
   verify each reaches COMPLETED.
4. Morning report: per-pipe synced counts, INDOX table stats, UI screenshots.

## Time budget
| phase | work | budget |
|---|---|---|
| 0 | research dispatch + small-tab fetch | 15 min |
| 1 | gmail app password + mail conn | 25 min |
| 2 | companies/settings/tag_rules load | 20 min |
| 3 | big CSV download + 6-month load | 40 min |
| 4 | drive pairs + run-all | 20 min |
| 5 | overnight catch-up + QA | — |
| 6 | morning report + screenshots | 10 min |

## Anti-stall discipline (AGENTS.md rule 7)
- Subagents: read-only research, ≤5 min, one parallel block, cheap models.
- Browser42 driving: main thread only (shared browser), one task at a time.
- Long runs (CSV load, sync catch-up): async terminals in main thread.
