# INDOX — The Solution, End to End

**What this document is:** the whole of INDOX as it actually runs on 2026-08-13 — layers, data model, identity, workflows, API routes, state machine, and the full action catalogue. Every number here was measured against the live database or read out of the deployed blueprints. Where something is inferred rather than observed, it says so.

Companion file: **[NEXT.md](NEXT.md)** — what is still broken and the ordered plan to a releasable version. This file describes the system; that one describes the work.

---

## 1. The promise

> A document arrives from somewhere the client already uses — a Drive folder, an email attachment, a WhatsApp message. Without anyone touching it, INDOX figures out **who it is from**, **what it is**, **what it says**, and **which file backs it** — then pushes it into the Priority ERP as a real accounting record. One row per real document. No one retypes anything.

Everything below exists to keep that sentence true. The three ways it can break are the three things the architecture is organised around:

| Failure | What the client sees | Where it is handled |
|---|---|---|
| The document never arrives | missing invoices | §5 ingest |
| The document arrives more than once | the same invoice twice in Priority | §4 identity |
| The document arrives but says the wrong thing | wrong supplier, wrong date, wrong amount | §6 extraction |

---

## 2. Layers

INDOX is a layer-3 app on the AutomateOS platform. It owns no infrastructure; it composes four things the platform provides.

```
┌─ PLATFORM (layer 1-2) ────────────────────────────────────────────────┐
│  traefik  ·  authentik (SSO)  ·  supabase (postgres + PostgREST)      │
│  n8n (main + 2 workers + task-runners)  ·  redis  ·  glitchtip        │
└───────────────────────────────────────────────────────────────────────┘
┌─ SHARED SERVICE APPS (layer 3, siblings) ─────────────────────────────┐
│  drive-*      Google Drive adapter    (search, fetch, list)           │
│  mailapi-*    IMAP/Gmail adapter                                      │
│  apitools     OCR + local extraction  (the non-AI extraction path)    │
└───────────────────────────────────────────────────────────────────────┘
┌─ INDOX (layer 3) ─────────────────────────────────────────────────────┐
│  incoming-documents-*   Flask BFF + React console                     │
│  64 n8n blueprints, 54 active   ← the actual pipeline                 │
│  public.incoming_documents  + 10 satellite tables                     │
└───────────────────────────────────────────────────────────────────────┘
```

**The centre of gravity is n8n, not the Flask app.** The console is a viewer and a manual-correction surface. All automated work is n8n. That is why almost every question about INDOX behaviour is answered by reading a blueprint, not application code.

---

## 3. Data model

### 3.1 `public.incoming_documents` — one row per document

~32,700 rows. Wide (100+ columns), denormalised on purpose: a document's entire lifecycle lives on its own row, so any stage can be resumed from the row alone without joining anything.

Column families:

| Family | Columns | Role |
|---|---|---|
| **Identity** | `ID` (PK), `HASH`, `COMPANY_ID`, `COMPANY_DOC_ID`, `SHORT_DOC_ID`, `DOC_ID`, `API_TOOLS_ID` | §4 |
| **Provenance** | `SOURCE_TYPE`, `SOURCE_ID`, `SOURCE_LINK`, `CONNECTION`, `SYNC_NAME`, `SOURCE_LIST` | where it came from |
| **File** | `LINK`, `LINK_CONNECTION`, `SIZE`, `NAME` | the backing file in Drive |
| **Content** | `TYPE`, `DOC_DATE`, `DOC_TOTAL_AMOUNT`, `COMPANY_NAME`, `PURCHASE_ID`, `SHIPMENT_ID` | what it says |
| **Progress** | `STATUS`, `*_COMPLETED` booleans, `ITERATION_COUNT`, `NEXT_RETRY_AT`, `RETRY_COUNT` | §9 |
| **Audit** | `ERROR`, `REQUIRED_ACTION`, `ITERATION_COUNT`, `created_at`, `updated_at`, `TIMESTAMP` (history: `indox_action_execution_log`) | §3.3 |
| **Delivery** | `PRIORITY_SYNC_COMPLETED`, `PRIORITY_SYNC_COUNT` | §8 |
| **Merge** | `MERGED_INTO`, `MERGED_AT`, `MERGE_BATCH_ID`, `STATUS_BEFORE_MERGE`, `ALSO_SEEN_AS` | §10 |
| **Balance-sheet** | `BS_EXTRACTED_LINES`, `BS_LINE_DATE`, `BS_LINE_AMOUNT`, `LINKED_BS` | §7 |

**The `*_COMPLETED` booleans are the real state machine.** `STATUS` is a summary; the booleans are what the router actually branches on. A document is "done" when a specific set of them is true — not when `STATUS` says `COMPLETED`.

### 3.2 What the database enforces

Measured, complete:

| Object | Key | Enforced at write? |
|---|---|---|
| `incoming_documents_pkey` | `ID` | **YES** |
| `uq_incdoc_hash` — partial unique, `WHERE HASH IS NOT NULL AND <> '' AND lower(HASH) <> 'unknown'` | `HASH` | **YES**, over 77.6% of rows |
| `incdoc_company_dockey_idx` | ≈(COMPANY_ID, COMPANY_DOC_ID) | **NO** — non-unique |
| `incdoc_connection_platform_idx` | (CONNECTION, SOURCE_ID) | **NO** |
| 6 triggers | — | hygiene only, zero identity logic |

That is the entire list. **No CHECK constraints, no RLS, no policies, no outbound FKs, and `ID` has no default** — any client with a table grant can insert a row with an ID of its choosing. Three ID shapes exist in the wild (`doc_<base36>` 26,685 · legacy epoch-prefixed 5,837 · other), proving multiple minters have run over this table's life.

**Nothing in the database ever INSERTs into or DELETEs from `incoming_documents`.** Row creation and removal are 100% application-side.

### 3.3 Per-document history — `indox_action_execution_log`

**`ACTION_LOG` was DROPPED on 2026-08-21.** It was a single TEXT column holding every action ever
taken on the row as one comma-separated string — 20 MB of a 180 MB table, 535 bytes on the average
row, paid again on every GET and every `executeWorkflow` hop. Four properties had each caused a
wrong conclusion: it was cumulative and never windowed; it carried two timestamp formats; it was
middle-trimmed past 6,000 chars so old entries silently vanished; and BS children inherited the
parent's whole log at creation, so a child's log was not the child's history.

History is now **`public.indox_action_execution_log`** — one row per (document, action, execution),
written at dispatch by `indoxV2ActionRouter01 :: 'Log Action Start'` and closed by
`'Log Action End'`. Rows, not a string: no cumulative trap, no trim, no format ambiguity, no
inheritance, and duration + completion per action for free.

The three facts the state machine used to derive from the string are columns now:

| question | answer |
|---|---|
| was this action already dispatched? | `indox_action_execution_log`, joined as `ACTION_HISTORY` (newest 10 per document) by `indoxV2Driver01 :: 'Get Action History'` |
| how many steps has this document had? | `ITERATION_COUNT` — +1 per dispatch, reset by the four restart nodes |
| were gmail labels applied / was it filed? | `GMAIL_LABELS_COMPLETED` / `FAILED_FOLDER_COMPLETED` — the last two actions that had no completion column |
| has this document been touched at all? | `ITERATION_COUNT > 0 OR BASE_EXTRACTION_COMPLETED` |

The column as it stood is archived whole in `public._actionlog_backup_20260820` (39,149 rows,
24 MB). Migration: `scripts/ops/migrations/2026-08-21_drop_action_log.sql`; full record in
`apps/indox/issues/remove-action-log-column.md`.

⚠ The dispatch log records **dispatched actions only**. Node-level labels the old string also
carried (`Extract Base Doc`, `Update NAME`, `COMPANY RESOLVER <hash>`) were never actions and have
no row. Nothing decided on them — verified across the estate before the removal — but the document
page shows less detail than it used to.

### 3.4 Satellites

| Table | Rows | Joins by | Purpose |
|---|---|---|---|
| `sync_ledger` | 25,687 | `doc_id`→`ID`, `content_hash`→`HASH` | what each sync has already seen. **Own PK `(source, platform_id)` — a third identity notion** |
| `ocr_cache` | 21,113 | `file_hash`→`HASH` | OCR results, keyed by content |
| `merge_audit` | 3,520 | `winner_id`/`loser_id`→`ID` | every merge decision. **All rows `dry_run=true`** |
| `indox_merge_groups` / `_members` | 4,173 / 9,622 | →`ID` | duplicate detection output |
| `incoming_documents_premerge_20260813` | 32,565 | — | pre-merge snapshot |
| `bs_extracted_lines` | **0** | `document_id`→`ID` | **the only FK in the estate**; nothing writes it |
| `business_document_events` | **0** | — | dormant |

---

## 4. Identity — the hardest part of the system

Everything that has ever gone materially wrong in INDOX traces to this section.

### 4.1 The four keys and their certainty

| Key | Certainty | Why |
|---|---|---|
| `ID` | **CERTAIN** | primary key, 0 violations |
| `HASH` | **CERTAIN** | content hash, unique-enforced, 0 duplicates — but **22.4% of rows have none** |
| `(COMPANY_ID, COMPANY_DOC_ID)` | **INFERRED** | 4,152 duplicate groups; wrong ~12% on dates |
| `(COMPANY_ID, SHORT_DOC_ID)` | **INFERRED** | 4,283 groups; a lossy last-5-alphanumeric truncation of an already-unreliable field; wrong ~25% on amounts |

**`COMPANY_DOC_ID` is frequently not a document number at all.** The five largest duplicate groups hold 31, 24, 18, 15 and 14 rows — each with as many *distinct hashes* as rows, i.e. genuinely different files. Their "doc ids" are a company registration number, a **supplier name**, a **date**, and a **phone number**. Any rule that fuses on this key fuses unrelated documents.

**`(COMPANY_ID, SHORT_DOC_ID)` is used by nothing in the database** — no index, no constraint, no function. It exists purely as an application-layer guess.

### 4.2 Six notions of identity in production

| Implementation | Rules | Rule-1 guard | Rule-2 guard | Scope |
|---|---|---|---|---|
| n8n `Resolve IDs` | ID→CD→CS→HASH | full `docIdOk` | **none** | batch + company scoped |
| Flask `compute_diff` | ID→CD→CS→HASH | **none** | **none** | whole table |
| DB `indox_doc_key()` | DOC_ID→CD | full | **never used** | whole table |
| `Build Deliver` | HASH only | — | — | atomic |
| Flask fallback-type | (CONNECTION, SOURCE_ID) | — | — | may match many |
| `sync_ledger` | (source, platform_id) | — | — | per-sync |

They disagree on precedence, on guards, and on the quarantine threshold. **The certain key is checked last** in both matchers that have all four.

### 4.3 The write path, verbatim

```js
function logicalMatch(row){
  if(docIdOk(row.COMPANY_ID,row.COMPANY_DOC_ID)){ … return byCD[k]; }   // INFERRED
  if(!bad(row.COMPANY_ID)&&!bad(row.SHORT_DOC_ID)){ … return byCS[k]; } // INFERRED, unguarded
  if(!bad(row.HASH)&&byHash[…]!==undefined) return byHash[…];           // CERTAIN — last
  return null;                                                          // → mints a new row
}
```

On a match, **the entire incoming item is written onto the matched row** (`autoMapInputData`, every non-empty field). There is no absorb-only-if-missing logic on this path — an incoming `LINK`, `SOURCE_ID`, `SOURCE_TYPE`, `NAME` or `STATUS` overwrites the existing one. Contrast `Build Merge Write`, which has exactly that protection.

**Creation is not a decision anyone makes** — it is what happens when three guesses fail.

### 4.4 Who can create and who can re-target

**13 distinct paths can create a row**, reaching 2 nodes (`PG Upsert`, `PG Deliver Insert`). Plus a 14th nobody counts: `PG Upsert` is `ON CONFLICT ("ID") DO UPDATE`, so **any caller passing a deleted or merged-loser ID re-creates that row**. There is no update-only verb except `MERGE` and `DELETE`.

**Ten paths can silently re-target onto a different row.** The dangerous class is exactly four — the *spawners*, which pass neither `ID` nor `HASH`:

| Spawner | Rows it has made |
|---|---|
| `indoxV2ActionsBS01 :: Upsert…'Batch Update'3` | 6,465 |
| `indoxV2ActionsGDoc01 :: Upsert: Create New Shipment Row1` | — |
| `indoxV2ActionsShip01 :: Upsert: Create New Shipment Row1` | — |
| `indoxV2Driver01 :: Create New Shipment Row` | 662 |

Measured damage: **1,359 keys contested** between a spawner row and a sync-delivered row; **≥65 real documents already overwritten** (55 → `BALANCE_SHEET`, 10 → `INVOICE`). A floor, not a ceiling — a spawner landing on another spawner's row leaves no trace.

GDoc and Ship **already search first** (`Shipment GET_ALL`), then discard the answer and let the upsert re-resolve against a differently-scoped index. Textbook TOCTOU.

### 4.5 The boundary is not singular

"All writes go through `indoxApi01`" is false in six places: `errorHandler01`, `Record Base Doc Failure`, the **Flask BFF** (direct PostgREST with the service-role key, its own copy of the rules with zero guards), `apps/chat` (via Flask *or* an n8n webhook fallback — two different matchers), **ops scripts that write identity keys**, and `indox_execute_merge_group()`.

The console can hand-edit every key the other five match on: `patch_document` has no allowlist and no identity guard. The lint gate that enforced the boundary (`G42`) was added known-failing and **retired before the callers were rewired**.

---

## 5. Ingestion — how documents arrive

Four lanes, all converging on the same table.

| Lane | Workflow | Carries `HASH`? | Carries `ID`? |
|---|---|---|---|
| Drive folder scan | `SyncProcGDoc0001` | yes | **no** |
| Gmail attachments | `indoxGmailDocDownloader01` | yes | no (test fixtures only) |
| Gmail balance sheets | `indoxGmailBSDownloader01` | yes | no |
| Gmail links | `indoxGmailLinkDownloader01` | yes | no |
| Sync v3 (all sources) | `syncV3Deliver0001` → `DELIVER` | **mandatory, throws without** | generated |

**Sync v3 is the modern lane and the only structurally safe one.** `DELIVER` is hash-keyed, `ON CONFLICT ("HASH") DO NOTHING`, and — uniquely — **tells the caller which row it got** via a follow-up fetch. Every other lane writes and never learns where the write landed.

Live distribution: `GOOGLE_DRIVE_FOLDER` 16,712 · `BALANCE_SHEET` 6,464 · `MAIL_ATTACHMENT` 5,222 · `GMAIL` 2,851 · `INVOICE` 665 · `GOOGLE_DRIVE_FILE` 597 · `WHATSAPP` 43.

`sync_ledger` prevents re-ingesting what a sync has already seen, keyed on `(source, platform_id)` — independent of document identity, which is why it cannot prevent duplicates arriving from *different* sources.

---

## 6. Extraction — exactly two points

A hard architectural rule, enforced and verified live (all single-value extractors sit at 0/hr):

```
POINT 1  base extraction   → COMPANY_ID, COMPANY_NAME, DOC_DATE, TYPE
POINT 2  per-type extract  → the fields that type needs (amount, shipment id, purchase id, …)
```

Nothing else may extract. Single-value extractors (`query_doc_date`, `query_doc_total_amount`, `query_shipment_id`, `query_purchase_id`) exist in the action catalogue as **legacy fallbacks that must stay at zero** — each one is a third extraction point and a chance for two reads of the same document to disagree.

Two engines feed both points:

- **AI path** — `indoxV2ExtractInvoiceGemini01` → `BaseDocEx01 :: Build AI Result` → `Select Base`
- **Local path** — `apitools` OCR, anchored `unifyDocDate` in the `JQExV3*` `Collect` nodes

`Select Base` runs `pick(d.LOCAL_DOC_DATE, d.AI_DOC_DATE)` — local first, AI as fallback. Its own comment records the design choice that leaves it undefended: *"so no date normaliser is invented."*

**This is where the live date corruption comes from.** When a document prints a 2-digit year, the model may read `DD/MM/YY` as `YY/MM/DD` (`23/06/26` → stored `26/06/2023`) or expand the decade wrongly (`25` → `2015`). Nothing downstream reorders anything — the value is stored exactly as emitted. 200 rows provably corrupt; the local path gets the same documents right in 100 of 130 cases, which is both the proof and the fix.

---

## 7. Linking and balance sheets

**Linking** = finding the Drive file that backs a document row. `find_link` → `indoxV2SearchFile01` → the drive service, matching on company and document number. Success writes `LINK` + `LINK_CONNECTION`.

`MISSING_LINK` (6,175 rows) is **a legitimate terminal success**, not a failure. The row still carries its extracted content and still goes to Priority. It is excluded from "requires attention" for exactly this reason.

**Balance sheets** are a document type that contains *other documents*. `extract_balance_sheet` reads the sheet into `BS_EXTRACTED_LINES`, then `link_documents` spawns one child row per line. Children are **ordinary invoices that happen to have been listed on a balance sheet** — they have no relationship to their parent's file, they search Drive for their own, and 6,464 exist.

The child spawner is the largest single source of duplicate rows, because it matches on `(COMPANY_ID, SHORT_DOC_ID)` — and **`SHORT_DOC_ID` is the last column written**, median 2.43h after base extraction (p90 18.27h). `= $2` never matches NULL, so the twin is invisible during that window and a child is created instead of linked. This accounts for **518 of 518** "twin existed" cases; there is no residual class of genuine matcher misses.

---

## 8. Delivery to Priority

The point of the whole system. `PRIORITY_SYNC_COMPLETED` + `PRIORITY_SYNC_COUNT` track it.

**This is the largest open gap.** Of 32,700 rows, 4,463 `COMPLETED` rows have ever been pushed. June-onward the rate is **8.8%**. It is not failing — there are no errors on this path. It is not running.

`PRIORITY_SYNC_COUNT > 1` on 2,992 rows (worst: 6). Whether that means repeated *pushes* or repeated *attempts* is unresolved, and it bounds how much duplicate data Priority already holds.

**Ordering constraint:** merge before bulk-pushing, or 5,535 duplicate rows land in Priority and no INDOX-side merge retracts them.

---

## 9. The state machine

### 9.1 Live status census

| Status | n | with LINK | base done | pushed |
|---|---:|---:|---:|---:|
| `COMPLETED` | 21,350 | 20,929 | 20,929 | 4,463 |
| `MISSING_LINK` | 6,175 | 1 | 1 | 0 |
| `MISSING_COMPANY_ID` | 1,634 | 1,476 | 1,360 | 15 |
| `DOUBLE` | 1,360 | 1,307 | 1,133 | 145 |
| `OLD` | 704 | 589 | 589 | 0 |
| `MERGED` | 394 | 360 | 222 | 85 |
| `MAX_ITERATIONS` | 367 | 358 | 325 | 18 |
| `MISSING_TYPE` | 290 | 290 | 290 | 8 |
| `UNKNOWN_COMPANY` | 180 | 180 | 180 | 2 |
| `GARBAGE` | 99 | 99 | 99 | 0 |
| `TO_EXTRACT` | 53 | 12 | 12 | 0 |
| `EXTRACTION_FAILED` | 37 | 36 | 37 | 0 |
| `PAUSE` | 34 | 34 | 0 | 31 |
| `IN_PROGRESS` | 33 | 28 | 25 | 12 |
| `ACTION_REQUIRED` | 2 | 2 | 2 | 1 |
| `NEEDS_REVIEW` | 1 | 1 | 1 | 0 |

### 9.2 Simplified lifecycle

```
                     ┌──────────────┐
   ingest  ─────────▶│  IN_PROGRESS │◀──── retry / restart
                     └──────┬───────┘
                            │  figure_company_id
                ┌───────────┼───────────┐
                ▼           ▼           ▼
     MISSING_COMPANY_ID  UNKNOWN_    (company known)
                         COMPANY          │
                                          │ figure_document_type
                             ┌────────────┼────────────┐
                             ▼            ▼            ▼
                       MISSING_TYPE   GARBAGE    (type known)
                                                       │
                                          POINT 1  extract_base_doc
                                                       │
                                          POINT 2  extract_per_type
                                                       │
                                                  find_link
                                          ┌────────────┴────────┐
                                          ▼                     ▼
                                   LINK found            MISSING_LINK
                                          │                     │
                                          └──────────┬──────────┘
                                                     │ mark_completed
                                                     ▼
                                                 COMPLETED ──▶ Priority
```

**Terminal states:** `COMPLETED`, `MISSING_LINK`, `OLD`, `DOUBLE`, `MERGED`, `GARBAGE`, `MAX_ITERATIONS`, `PAUSE`.

Two terminals are **not actually terminal**, and both are open defects:
- `COMPLETED` — 1,903 rows have left it (831 fully extracted and file-backed)
- `OLD` — self-confirming: it is assigned from a date, and once assigned the row is never re-evaluated, so a corrupted date becomes a permanently hidden document

### 9.3 Retry and give-up

`ITERATION_COUNT` increments per pass; `mark_max_iterations` terminalises at the cap. `NEXT_RETRY_AT` parks a row that has nothing to do right now, so the drainer stops re-picking it — this is what turned a busy-loop into a queue. `Terminalize Stalled` sweeps rows stuck by wall-clock.

---

## 10. The action catalogue

The unit of work. The driver picks a row, the decider names one action, a router executes it. **49 actions**, in six families.

**Identity & classification** — `figure_company_id` · `figure_company_offline` · `get_company_name` · `figure_document_type` · `get_short_doc_id` · `update_company_doc_id` · `get_api_tools_id`

**Extraction (the two points)** — `extract_base_doc` · `extract_per_type` · `extract_invoice_google_ai` · `extract_balance_sheet` · `select_invoice_values`

**Single-value legacy — must stay at 0** — `query_doc_date` · `query_doc_total_amount` · `query_shipment_id` · `query_purchase_id`

**Files & linking** — `find_link` · `update_name` · `check_from_office` · `link_documents`

**Status transitions** — `mark_completed` · `mark_max_iterations` · `update_status_missing_company` · `update_status_missing_link` · `update_status_missing_type` · `update_status_unknwon_company` *(sic)* · `update_status_double` · `update_status_extraction_failed` · `resolve_double`

**Restarts** — `restart_gdoc` · `restart_balance_sheet` · `restart_doc_base`

**Parked verdicts (`no_action_*`)** — 16 of them: `already_completed` · `double` · `merged` · `awaiting_company_id` · `awaiting_company_name` · `awating_doc_id` *(sic)* · `link_not_found` · `extraction_failed` · `paused` · `unknown_document_type` · `garbage` · `max_iterations` · `old_date` · `api_tools_failed` · `shipment_id_missing` · `unhandled_state`

A `no_action_*` verdict is not a no-op — it parks the row via `NEXT_RETRY_AT` so the drainer stops burning capacity on it. Getting these right is most of what made the pipeline stop thrashing.

---

## 11. The drain loop

```
indoxV2BaseDrain01  (schedule, every 300s)
  ├─ Check Capacity        ── in-flight executions vs gear
  ├─ classify open rows into lanes (cls_a … cls_d)
  ├─ Sweep Gate (1/hour)   ── full-table pass, currently HELD
  └─▶ indoxV2Driver01
        ├─ processLock01        ── per-(doc, action) lock
        ├─ indoxDocGet01        ── load the row
        ├─ indoxV2Decide01      ── name ONE action
        └─▶ indoxV2Actions{GDoc, BS, Ship, Global}01
                └─▶ indoxApi01  ── the write
```

**Class selection is the whole game.** A row that matches no class is invisible to the drainer forever — and a pass that emits zero rows renders in n8n as `{success: true}`, so it looks healthy. That exact failure hid 1,178 of 1,197 open rows until `cls_d` was added.

**Lock skip is correct by design.** A row already being worked is skipped, not queued. Skips are not errors and must not be counted as blockage.

**Concurrency is pinned at 8 workers.** The host is 6 cores / ~10 GB with the stack using ~8 GB; raising width drives swap and *reduces* throughput (measured: 359/min → 9/min at 4 parallel agents).

---

## 12. `indoxApi01` — the API

37 nodes, live byte-identical to the blueprint. Three entry points, eight verbs. **81 call sites across the fleet — the most-called workflow in INDOX.**

```
ENTRY
  When Called          executeWorkflowTrigger   ← the only real door
  Keepalive            schedule → NoOp
  Poll Line Changes    schedule → Get Changed Docs → Process Changed Doc

DISPATCH   If Management → [0] Call Sync Api   [1] Action (switch)

ROUTES
  [0] UPSERT       Strip Control → UPSERT Adapter → Build Match Index SQL → Load Match Index
                     → Resolve IDs → PG Upsert → API Emit IDs → API Unlock Doc
  [1] GET_ALL      PG Get All → Guard Get Size
  [2] GET          Build Get SQL → PG Get → Guard Get Size
  [3] DELETE       PG Delete                                    ← hard delete by ID
  [4] TABLE_GET    Build Table Get → PG Table Get
  [5] TABLE_UPSERT Build Table Upsert → PG Table Upsert          ON CONFLICT ("key")
  [6] DELIVER      Build Deliver → PG Deliver Insert → Deliver Fetch Req → PG Deliver Fetch
                                                                 ON CONFLICT ("HASH")
  [7] MERGE        Build Merge Read → PG Merge Read → Build Merge Write → PG Merge Write
```

`TABLE_UPSERT` **cannot touch `incoming_documents`** — its allow-list covers only `ai_extraction_cache`, `tag_rules`, `settings`, `companies`, `trusted_suppliers`, `sync_pipe_state`.

**Route quality, honestly graded:**

| Route | Identity | Grade |
|---|---|---|
| `DELIVER` | HASH, atomic, returns the row it got | **correct** |
| `MERGE` | explicit winner/loser IDs, re-read fresh, `NEVER`-list protects identity fields | **correct** |
| `DELETE` | explicit ID list | correct, but see below |
| `UPSERT` | 4 rules, inferred keys first, creates on failure, never reports where it landed | **the problem** |

**Performance note:** both hot lookups seq-scan 32k rows on every call — `Build Match Index SQL`'s `"HASH" in (…)` and `Build Deliver`'s `where "HASH" = $1`. The partial index is unusable unless the query repeats its predicate. Adding it converts both to index scans.

---

## 13. Where the promise holds, and where it breaks

**Holds:**
- Documents arrive from four lanes and land in one table
- Two-point extraction is enforced; all single-value extractors are at 0
- Typing works at 98%, base extraction at 77%
- The pipeline runs clean — 0 errors against ~4,000 successes/5min
- 64% of documents reach `COMPLETED`, 60% fully done
- Content-identity ingestion (`DELIVER`) is genuinely correct

**Breaks:**

| # | Break | Size |
|---|---|---|
| 1 | **Delivery to Priority is not running** | 8.8% of June-onward |
| 2 | **Duplicate rows** — inferred keys drive writes | 5,535 excess |
| 3 | **The AI mis-reads 2-digit years** | 200 rows (floor) |
| 4 | **Spawners silently overwrite real documents** | ≥65 confirmed |
| 5 | **Six writers, three matchers, no enforced boundary** | architectural |
| 6 | **`OLD` and `COMPLETED` are not truly terminal** | 1,903 + 704 |

Every one of these is an identity or delivery problem. None is an extraction-quality problem — the engines work. **INDOX's difficulty is not reading documents; it is knowing which document it is holding.**

---

## 14. The invariants that must hold

1. **Never let an inferred key drive a write.** `ID` and `HASH` may target a write. `(COMPANY_ID, COMPANY_DOC_ID)` and `(COMPANY_ID, SHORT_DOC_ID)` may *detect* and *suggest*, never *write*.
2. **Creation is an explicit decision**, never the fallback when matching fails.
3. **Every writer learns which row it wrote.** Today only `DELIVER` does.
4. **Exactly two extraction points.**
5. **One matcher.** Not three.
6. **Terminal means terminal** — except `OLD`, which must re-evaluate when its date changes.
7. **A zero on an idle workflow proves nothing.** Pair every error count with a success count.
8. **Never fix a symptom in the database.** Fix the pipeline; a hand-edited row hides the defect and it recurs.
