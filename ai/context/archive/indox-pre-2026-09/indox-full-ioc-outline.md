# INDOX — full production IaC automation outline (what's in use, how it fits together)

Verified by reading all workflows 2026-06-26. Everything is n8n (queue mode, main + 2 workers) under `bbox`; data in self-hosted Supabase Postgres; OCR/AI in `apitools` (`http://apitools:8080`); gmail via `inbox` service (`http://mailapi:8970`). Single source of truth for sync config = the Postgres `settings` table row `sync_registry`.

## 1. The three subsystems
1. **INDOX pipeline** — ingests documents (gmail + drive), classifies, extracts fields, writes `incoming_documents`, drives each doc to COMPLETED.
2. **Label Engine** — classifies inbound gmail messages and applies the labels the gmail syncs key off.
3. **Google Workspace agent** — a Gemini chat agent that *reads* INDOX state (Sheets/Gmail/Drive via MCP). Read/Q&A layer, shares creds + the AutomationValues sheet — interference risk if ever driven to write.

## 2. Layered architecture (active workflows + ids)
```
TRIGGERS                          SYNC LAYER                         DATA/PROCESS LAYER
─────────                         ──────────                         ──────────────────
Mail Label Engine (15m)          SyncScanner00001 (15m) ──┐
 mailLabelEngine01                  SyncScanUnit0001 ─────────┤ claims units (registry-driven)
  applies DOC_TO_SYNC /             ├ drive: driveApi01 list/move
  BS_TO_SYNC / DOC_LINK_TO_SYNC     └ gmail: gmailApiRouter01 search/addLabels
        │ (labels)                        │ dispatch processor_wf:
        ▼                                 ├ SyncProcGDoc0001  (drive gdoc)
  gmail messages                          ├ SyncProcBS000001  (drive bs)
                                          ├ indoxGmailDocDownloader01  (gmail doc)
                                          ├ indoxGmailBSDownloader01  (gmail bs)
                                          └ indoxGmailLinkDownloader01  (gmail link)
                                                │ each: Process Document (indoxProcessDocument01)
                                                │       → apitools OCR + driveApi01 upload
                                                │       → Batch Upsert (indoxDocBatchUpsert01) row
                                                ▼
                              incoming_documents (Supabase)
                                                │
   indox api (indoxApiRouter01)  ◄────── data CRUD ──────────────────────┐
     ├ supabase backend indoxApiSupabase01  ── owns the REAL driver:        │
     │     "Poll Line Changes" (2 min) ──► Incoming Documents 0.1.7       │
     │                                       (sv5xxRBVGxvV0kXx)            │
     │                                        Determine-Action self-loop ─┘
     │                                        → Figure Type/Company, Query* extractors,
     │                                          Gemini invoice / BS-v2 extractors, dedup,
     │                                          BS line-linkage → mark_completed
     ├ sheets backend  indoxApiSheets01   (toggle, Redis n8n.indox.data_backend)
     └ MANAGEMENT (INLINE_ACTION RESET/STATUS/INJECT) ──► sync api (SyncApi0000000001)
                                              ├ STATUS → sync source (SyncSource000001) → drive/gmail api
                                              └ RESET  → Full reset (IndoxResetFull01) → drive/gmail reset
PRIMITIVES: driveApi01 (drive ops) · gmailApiRouter01 → gmailApiImap01 (active) / gmailApiOauth01 (fallback)
SUPPORT: indoxSettings01 (Settings/companies/queries) · indoxV2UploadApiTools01 (Upload to apitools)
EXTRACTORS: Figure Document Type indoxV2FigureDocType01 · Query{DATE 61FD…, INVOICE_ID 7vyb…, PURCHASE_ID Kwd6…,
            SHIPMENT_ID Lz6s…, TOTAL_AMOUNT b5kj…, IS_BS hgey…} · invoice Gemini indoxV2ExtractInvoiceGemini01 ·
            BS extractor v2 indoxV2ExtractBalanceSheet01 · Figure COMPANY_ID indoxV2FigureCompanyId01 · process_lock processLock01
```

## 3. End-to-end data flow (the one true path)
1. **Email arrives** → Label Engine (15m) classifies via `tag_rules` and applies a routing label.
2. **Sync Scanner** (15m) reads `sync_registry`, fans one **Scan Unit** per sync; the unit **searches** (`label:<to_sync> -label:<in_progress/synced/failed>`) and **claims** (gmail: add IN_PROGRESS; drive: move to in_progress folder) then dispatches the sync's **processor**.
3. **Processor** downloads bytes → `Process Document` (apitools OCR + company/type) → uploads renamed file to Drive (or tags gmail synced) → **Batch Upsert** a row into `incoming_documents` (IN_PROGRESS).
4. **Supabase poll** (every 2 min, inside `indoxApiSupabase01`) picks up the new/changed row → runs **Incoming Documents 0.1.7**, whose **Determine Action** loop resolves one field per pass (type, company, date, amount, invoice/shipment/purchase id, Gemini extraction, dedup, BS-line linkage), each writing via Batch Upsert (which releases the doc's process_lock) and re-entering itself until **mark_completed**.

## 4. Label routing (Label Engine → syncs) — the classifier rules
`tag_rules` rows (EVENT=ON_CREATE) the engine evaluates; the 3 routing labels:
| label (KEY / Label_NN) | rule (decisive condition) | → sync |
|---|---|---|
| **BS_TO_SYNC** (Label_10) | `attachments>0 && !promo && containsAny(thread[0].text, ["דוח גיול","כרטסת"])` | gmail-bs (sEcV) |
| **DOC_TO_SYNC** (Label_11) | `attachments>0 && not already BS/promo` | gmail-doc (9NWA) |
| **DOC_LINK_TO_SYNC** (Label_12) | `inList(from, [morning, ezcount, rivhit, …]) && attachments==0` | gmail-link (LDrY) |
SYSTEM labels (applied by workflows, not classifier): IN_PROGRESS, SYNCED_DOC, SYNCED_BS, FAILED_BS, SAVED_INVOICE, PROCESSED. Engine auto-applies PROCESSED to every scanned message; scanner search excludes claimed/done via the in_progress/synced/failed labels.

## 5. Google Workspace agent (separate, read-layer)
- **My workflow 15** (`QR6p46Wpmvo7z53c`, active) — Gemini-3.5-flash chat agent, public chatTrigger, system-prompted as the "Hacohen Google Workspace + Incoming Documents ops agent" (query AutomationValues sheet first, fall back to Gmail/Drive).
- Tools = 3 MCP servers (all active): **Gmail MCP** `gmailMcpAgent01` (21 tools incl. label add/remove/create), **Drive MCP** `gDriveMcpAgent01`, **Sheets MCP** `gSheetMcpAgent01` (incl. AutomationValues query nodes on sheet `1SfW…y11U`).
- **Interference risk:** shares the same OAuth creds (`hacohen.agent` Sheets/Drive, `hachohen` Gmail) and the AutomationValues sheet/Gmail-label surface as INDOX. Intended read-only, but the MCP servers expose write/label tools → an errant agent action could mutate INDOX data or labels. Keep it read-only; consider removing write tools from the MCP servers.

## 6. What's IN USE vs DEAD (codify the live set; prune the rest)
**LIVE (keep):** SyncScanner00001, SyncScanUnit0001, SyncProcGDoc0001, SyncProcBS000001, indoxGmailDocDownloader01, indoxGmailBSDownloader01, indoxGmailLinkDownloader01, sv5xxRBVGxvV0kXx, indoxApiRouter01, indoxApiSupabase01, indoxApiSheets01, SyncApi0000000001, SyncSource000001, driveApi01, gmailApiRouter01, gmailApiImap01, gmailApiOauth01, indoxDocBatchUpsert01, indoxSettings01, mailLabelEngine01, indoxV2FigureDocType01, indoxProcessDocument01, indoxV2UploadApiTools01, the 6 Query* extractors, indoxV2ExtractInvoiceGemini01, indoxV2ExtractBalanceSheet01, indoxV2FigureCompanyId01, processLock01, indoxDocGet01, the 3 reset WFs (IndoxResetFull01/tVzFMkz18pCsXRyw/IndoxResetGml001), the GWS-agent cluster (4).
**DEAD/legacy (prune candidates):** RSlxF4ztnpwSTdgE (0.1.4), 8TedFahagr7xPfuA (archived Query INVOICE_ID dup), BLtx8hJDmox8wSCz / AZXF28EaGfEQjZBx / IndoxGDocSyncV2x / IndoxBSSyncV2xx / IndoxBSRunV2xxx (superseded runners), vBcSCddTDnvbuOZi / m52MK8jdeU1KvJX0 / errpzoZI8QWC1B0f / indoxGmailActionsScanner01 (legacy scanners), 2grPBFAmWfiUm79F (old orchestrator), 7IyawEU5uf3MCwml, TTgW5l6qnQjsLwfM, pqD1bjLaiTcHRyCj, rD3hoAVD83QPxFfS, indoxSetupWF001, gDriveMcpAgent01/gSheetMcpAgent01 (archived MCP dups), WnPDtdEYoPz9kpCP (BS extractor v1 — main WF uses v2 yN6…), diag/debug stubs. Plus dangling ref: bdchh5urW9lBzudZ (Snooze, pruned but still referenced by a disabled node in 0.1.7).

## 7. Known issues / hardening backlog (for the optimization phase)
- **Gmail OVERQUOTA throttle (~19s/IMAP op)** — the #1 throughput bottleneck; aggravated by reset-recycling. `issues/gmail-imap-highload-throughput.yaml`. Single IMAP connection serializes everything.
- **STATUS is slow** (12 serial gmail searches) — use the *table* signal for came-to-rest polling; STATUS for snapshots. Add a fast variant.
- **Shared gmail in_progress/failed labels** across syncs → STATUS over-reports those per-sync (only to_sync/synced are per-sync-meaningful).
- **Confirm canonical BS extractor** (yN6… v2 vs WnP… v1).
- **GWS-agent write tools** on shared creds — lock down to read-only.
- **Multi-tenant**: hardcoded AutomationValues sheet + single Google account + flat redis keys (see prior audit).

## 8. Reset / debug-run (the operational entrypoint)
`POST /webhook/indox-manage {INLINE_ACTION: RESET|STATUS}`. RESET reverses drive (move synced/failed→to_sync, loop-free via driveApi01) + gmail (strip labels) per registry, clears table+locks+execs. Then trigger Sync Scanner, monitor the table to came-to-rest (in_progress=0, no recent updates), report sync (to_sync→synced rate) + main (COMPLETED rate) speed. Full guide: `ai/context/indox-debug-run.md`. Control-plane design: `ai/context/indox-sync-control-plane.md`.
