# Supervised tuning runbook — INDOX throughput + 8-16GB robustness (do WITH user present)

Goal: eliminate the false-NEEDS_REVIEW bar-failure (BS line-invoices flipped by the 15-min terminalizer
because the bounded line-change poll can't drain them in time) + make the host robust so high-load can't
OOM-collapse Docker. Pre-reqs verified: full API abstraction live + 0-error; data-landing + lock-TTL fixes
in. See ai/context/api-abstraction-refactor.md (KEY FINDING).

## Step 1 — give Docker the RAM (the #1 lever; needs a restart)
`~/.wslconfig` already written (memory=12GB, processors=6, swap=6GB). Apply:
1. (optional) `bbox n8n push` is NOT needed here.
2. `wsl --shutdown`  (stops the WSL VM; the next `bbox.cmd <cmd>` starts it again — nothing
   auto-restarts it, and Docker Desktop is not involved: see ai/context/running-on-wsl.md)
3. Wait ~30-60s, then `docker ps` until the engine responds; containers auto-start (restart:unless-stopped).
4. Verify: `docker exec n8n-shlomo-laptop sh -c 'free -m|head -2'` → total should now be ~12000MB (was 7768).
5. Clear stale doc_step locks (restart leaves them):
   `RP=$(grep -E '^REDIS_PASSWORD=' .env|cut -d= -f2-|tr -d '\r"'); for k in $(docker exec redis-shlomo-laptop redis-cli -a "$RP" --no-auth-warning --scan --pattern 'n8n.process_lock.doc_step.*'|tr -d '\r'); do docker exec redis-shlomo-laptop redis-cli -a "$RP" --no-auth-warning del "$k">/dev/null; done`

## Step 2 — right-size compose memory limits (prevents OOM-collapse on any host)
Edit production/n8n/docker-compose.yml deploy.resources.limits (currently TOO HIGH — workers 6G each, main 4G):
- n8n (main): memory 4G → 2.5G
- n8n-worker-1 / n8n-worker-2: memory 6G → 2G each   (tune up if workers OOM-kill on large docs — watch)
- supabase-db: keep ~2G; apitools: ~1.5G; inbox: 512M; redis: 512M
Sum should sit < 12G with headroom for Windows. Also set in .env: `N8N_WORKER_CONCURRENCY=5` (was 8).
Apply: `docker compose -f production/compose.yml up -d` (recreates only changed services). Watch
`docker stats` under load — if a worker hits its limit + gets OOM-killed (137), bump that limit.

## Step 3 — raise INDOX throughput (so line-invoices drain within the terminalizer window)
- In indoxApiSupabase01 ("indox api - supabase"): node "Get Changed Docs" line-change poll `limit 8` → 30-50.
  Optionally node "Poll IN_PROGRESS Schedule"/recovery sweep limit similarly. (Memory warns: don't over-raise
  or it storms the host — with 12GB + the mem limits this is safe; start at 30, watch host mem.)
- Optionally widen the terminalizer window in "Terminalize Stalled" (15min → 30min) so slow-but-progressing
  docs aren't prematurely flipped.
- `bbox n8n push` (re-imports + publishes + restarts) → then CLEAR stale locks again (Step 1.5 command).

## Step 4 — clean state + real high-load run
- `bbox n8n automations reset --force` (clears incoming_documents + trashes folder files + strips labels +
  re-seeds bootstrap; note: alwaysOutputData fix means bootstrap no longer strictly required).
- Inject 100/type/source: `python3 scripts/fresh-company-test-state-inject.py --gmail 400 --drive 100`
  (IMAP append ~2s/doc serial — budget ~10-15min; or reduce to 25/type for a faster pass). Note: real BS
  files explode into many line-invoices, so even a modest BS count creates a large line load — that's the
  real test of Step 3.

## Step 5 — deep trace + acceptance
- Watch drain: `docker exec supabase-db-... psql -U postgres -d postgres -c "select \"STATUS\",count(*) from incoming_documents where \"ID\"<>'__bootstrap__' group by \"STATUS\";"` every ~1-2min.
- Per-doc trace: `python3 scripts/indox-doc-trace.py --status IN_PROGRESS --limit 10` ; trace stuck docs.
- ACCEPTANCE (ai/context/indox-expected-behaviour.md): 100+/type/source reach COMPLETED in ~10min; ZERO
  errors; zero stuck IN_PROGRESS; ZERO spurious NEEDS_REVIEW; BS lines all linked; dedup holds (no dup
  COMPANY_ID+COMPANY_DOC_ID). If line-invoices still flip to NEEDS_REVIEW → raise poll limit more / widen
  terminalizer / consider the BIG lever below.

## BIG lever (if poll-tuning isn't enough) — batch BS-line processing
Today each BS line needs ~6 sequential main executions, one action per line-change poll cycle. The deepest
throughput win is to process many lines per main execution (batch the BS-line actions) instead of
one-action-per-poll. This is a pipeline redesign in the main workflow (sv5xxRBVGxvV0kXx / the BS link path) —
do only if Step 3 tuning can't hit the 10-min bar at scale.

## Execution-pruning gap (verify + fix; needs a restart)
n8n DB has 12.7k executions and GROWING (not dropping to max_count). The compose sets
`N8N_EXECUTIONS_DATA_PRUNE=true` / `N8N_EXECUTIONS_DATA_MAX_AGE=168` / `N8N_EXECUTIONS_DATA_PRUNE_MAX_COUNT=2000`
— but n8n's config keys for this are historically UN-prefixed: `EXECUTIONS_DATA_PRUNE`,
`EXECUTIONS_DATA_MAX_AGE`, `EXECUTIONS_DATA_PRUNE_MAX_COUNT`. The N8N_-prefixed forms are likely NOT
recognized → pruning effectively OFF → unbounded execution_entity growth. FIX (supervised): add the
un-prefixed vars (keep the N8N_ ones too for safety) in production/n8n/docker-compose.yml + worker compose,
`docker compose up -d` n8n+workers, then verify the count drops toward 2000 over the next prune cycle
(`select count(*) from execution_entity;`). VERIFY FIRST against this n8n version's docs (2.x may accept N8N_
prefix — if the count is dropping on its own, no fix needed; it was NOT dropping as of 2026-06-23 01:00).

## New error signature observed (2026-06-23 ~03:05, monitoring) — drive api 404 on file update
A burst of errors_5m=5 traced to ONE root cause: `drive api` (×3) + its callers `INDOX BS Sync (Runner)`
/`INDOX GDoc Sync (Runner)` (×1 each) hit Google Drive **404 "resource could not be found"** on a file
**update** op (`Google/Drive/v2/actions/file/update.operation.ts:266`). Distinct from the GDrive-trigger
DNS flake — here the abstraction works and Google legitimately 404s a stale file ID (a sync-pair source/dest
file was trashed/moved). Data-level, not infra; no restart needed. SUPERVISED FIX options: (a) make the
sync runner tolerant — on 404 from `drive api` update, re-resolve the dest by name or skip+log instead of
erroring; (b) refresh the GeneralDocs*/BalanceSheet* sync-pair file IDs in settings. Watch: if it recurs every
cycle it's a permanently stale pair; if it was a one-off it's a file deleted mid-sync (benign).
CONFIRMED 2026-06-23 ~03:08: recurs every cycle (GDoc Sync Runner re-attempts the dead dest file ID each
scheduled run) → it's a PERMANENTLY STALE PAIR, not a one-off. Each cycle: drive api ×3 (404) + GDoc Sync ×1
(+ occasionally "Mannual Documents Namer" ×1). Steady-state errors_5m≈5 now, all this one root cause. Promote
to a supervised fix: prefer (a) 404-tolerant runner (re-resolve dest by name or skip+log) since it also hardens
against future trashed files; (b) refresh the stale GeneralDocs*/BalanceSheet* pair file ID in settings is the
quick unblock. Both are workflow edits → publish + restart (restart-requiring), so deferred to supervised.
ADDENDUM 2026-06-23 ~07:05: same Google-resource 404 family also seen once on "Google Integration Health"
(Gmail "Get many messages" → 404) — a scheduled health probe; transient/benign, same root family (a referenced
Gmail/Drive resource missing). When the stale-pair cluster + this probe + a DNS flake coincide, errors_5m can
briefly read up to ~7; that's still the known baseline, not new infra drift. Raise the heartbeat investigate
threshold accordingly (investigate only if errors_5m ABOVE ~7, or any NEW workflow name beyond this set).

## Other supervised items (separate)
- Define the Google Workspace Agent (My workflow 15) PURPOSE → then drop demo tools (News/Weather), add a
  system prompt, name it. (Currently the n8n starter template.)
- Sheets-node unification (57 nodes) — structural; do incrementally in sheets mode with verification.
- Redis caching of settings/companies in the data API TABLE_GET (speeds reads; fixes sheets rate-limit).

## DATA-QUALITY issues (from full-table audit 2026-06-24; roots found, fixes need publish+restart=supervised)
Found by reading all ~721 rows. Each has a confirmed root + concrete fix. Apply via edit → `bbox n8n push` →
clear stale locks → recycle syncs → verify the specific docs reach COMPLETED with the field populated.

1. **Type-classifier returns UNKNOWN for clear (credit) invoices** → docs park in MISSING_TYPE.
   ROOT: `Figure Document Type` (indoxV2FigureDocType01) is keyword-substring matching via apitools "find option".
   `invoice_kws` has `"חשבונית מס זיכוי"` (WITH מס) but real credit invoices print `"חשבונית זיכוי"` (NO מס)
   — viewed a-ptyh-1.pdf (Fetaya IK25003271) confirms. Substring miss → UNKNOWN. Brittle to every variant.
   FIX (pick): (a) quick — add variant kws to `Keywords` node: `"חשבונית זיכוי"`, `"זיכוי"`, `"קבלה"` etc.;
   (b) ROBUST — fix the AI_TYPE fallback (see #1b) so Gemini classifies whatever keywords miss.
1b. **AI_TYPE fallback never fires for UNKNOWN docs** (the robust fix's blocker).
   ROOT: `Determine Action` HAS the path (`UNKNOWN → return 'extract_invoice_google_ai'` → sets AI_TYPE →
   adopted as TYPE next loop, guarded by `if(STATUS!=='MISSING_TYPE')`). But stuck docs show AI_TYPE=null →
   the doc is set to MISSING_TYPE BEFORE the Gemini extract runs (chicken-egg), so the extract that would set
   AI_TYPE is gated out. FIX: when keyword type=UNKNOWN, route to `extract_invoice_google_ai` FIRST (set
   AI_TYPE) and only fall to MISSING_TYPE if AI_TYPE also comes back UNKNOWN/empty. Verify a known credit
   invoice flows UNKNOWN→AI classify→TYPE=INVOICE→COMPLETED.

2. **MISSING_COMPANY_ID on registered companies** (e.g. Fetaya — IS registered: companies id=40 "א. פתיה",
   מזהה1=510564693). ROOT: two gaps. (i) tax-id extractor `Company Id AFTER Query` (in figure_company_id
   indoxV2FigureCompanyId01) does "find after" only for labels `["ח.פ","ע.מ"]`, but Fetaya's invoice prints its
   number after `"עוסק מורשה"` (authorized-dealer) → tax-id never extracted. (ii) name match via `all_companies_
   identifiers` is exact-substring so `"א פתיה"` (no period) ≠ `"א. פתיה"` (registry, with period).
   FIX: add `"עוסק מורשה","עוסק פטור","מספר עוסק"` to the AFTER labels; AND normalize names (strip periods/
   collapse spaces) on both sides before the identifier match. Tax-id match should win over name match.

3. **Doubled filenames `X.X`** (e.g. `unknown-11644.unknown-11644`). ROOT: the RETIRED `Mannual Documents
   Namer` re-rename — `base + "." + name.split('.').last()` where `name` was already the renamed base (stale
   `$('Download File').first()` ref). STATUS: **already fixed** — Namer retired; GDoc→v2 (no extension-append
   rename). Verified 0 new `X.X` rows in last 3h. Remaining `X.X` rows are stale DOUBLE artifacts — harmless;
   optionally purge `WHERE NAME ~ '(.+)\.\1'`.

4. **EXTRACTION_FAILED on clear BS docs** (מצרפלס, טיח הארץ). ROOT: not yet isolated to bug-vs-transient —
   most EXTRACTION_FAILED during the audit window coincided with gmail/GDrive OVERQUOTA + DNS flake (external).
   FIX/NEXT: on a clean recovered run, re-trace the specific failed BS doc (scripts/indox-doc-trace.py); only
   if it fails with good network + clear OCR is it a real extractor bug — then VIEW the doc per standing rule.

5. **Completed invoices "missing" DOC_DATE/amount** — **NOT data loss.** The amount IS captured in
   `AI_DOC_AMOUNT` (e.g. 60623.68, 91129) — only the canonical `DOC_TOTAL_AMOUNT`/`TOTAL_AMOUNT` are null.
   ROOT: when the keyword extractor finds no total, the Gemini value isn't copied into the canonical field.
   FIX: in the extract/map step, `DOC_TOTAL_AMOUNT = DOC_TOTAL_AMOUNT ?? AI_DOC_AMOUNT` (same for DOC_DATE ?? AI
   date). Low-risk field coalesce. (Same likely applies to the 17 missing DOC_DATE.)

6. **Doubling / DOUBLE-status proliferation** (user-flagged). ROOT: mostly CORRECT dedup — 33/37 hash-bearing
   DOUBLE rows genuinely share their HASH with a live row. The 14 no-hash DOUBLE rows can't be hash-deduped;
   confirm they're company+shortdoc dups (the 2nd dedup rule) not spurious. The real "doubling" BUG was #3
   (doubled filenames), already fixed. FIX/NEXT: spot-check the 14 no-hash DOUBLE for a genuine company+shortdoc
   twin; if any distinct doc was wrongly marked DOUBLE, tighten the no-hash dedup key.

## High-load OCR churn (found 2026-06-24 mid-load verify; SUPERVISED fix)
Under high load (BS explosion -> ~520 line-invoices + ~76 standalone gdoc), apitools /documentOcr returns
500 "Unsupported image format/type" (fast-fail ~55ms at pytesseract.prepare) for a subset of docs. Root:
DPI200 PDF->jpg conversion (pdf2image/poppler + cv2 + temp) FAILS under CONCURRENCY (MAX_CONCURRENT_OCR=2),
producing a bad/empty image. NOT bad files (same files OCR fine single-threaded: date 17/07/25 proven) and
NOT my logic. Effect: the doc's OCR step errors -> main WF retries next poll -> updated_at refreshes ->
the 15-min "Terminalize Stalled" never fires (doc never goes stale) -> INFINITE CHURN holding doc_step
locks (77 observed) -> degrades whole-pipeline throughput (BS drain slows too). NEEDS_REVIEW stays 0
because churn keeps updated_at fresh.
FIXES (pick; supervised, needs apitools rebuild/restart + maybe main-WF edit):
 1. ROBUST CONVERSION: in pdf_to_jpg_from_path validate output image; retry once; on failure return a
    clear error so the OCR step can mark the doc EXTRACTION_FAILED (not 500-loop).
 2. TERMINALIZE-AFTER-N: track OCR attempt count on the doc; after 3 failed OCRs -> EXTRACTION_FAILED so
    it STOPS churning + releases the lock (this is the real churn-stopper; the terminalizer's updated_at
    staleness check is defeated by retries).
 3. THROUGHPUT: DPI200 conversion is heavier; under load consider APITOOLS_PDF_DPI=150 (sweep: digits ok
    from 120, amount/type plateau at 150) to cut conversion memory/temp pressure; and/or raise
    APITOOLS_MAX_CONCURRENT_OCR cautiously (more parallel poppler = more memory).
NOTE: this only manifests at the accidental high load (1 BS -> ~520 lines). The CORE pipeline + all OCR/
dedup fixes are PROVEN (280+ COMPLETED with 100% company+date+amount, 0 spurious-dup, 0 doubled-name).
