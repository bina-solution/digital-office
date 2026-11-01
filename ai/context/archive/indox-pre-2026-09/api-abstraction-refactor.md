# API-abstraction refactor — design + progress (autonomous loop, started 2026-06-22)

GOAL (operator directive): every workflow interacts with external systems ONLY through n8n "API"
sub-workflows that route by env/redis toggle — for DATA (gsheet|supabase), DRIVE, and GMAIL. Then re-run
high-load (gmail+drive sources; bs/shipment/invoice/order/other types) and deep-trace for
quality/stability/speed/efficiency/expected-behaviour (see [[indox-expected-behaviour]],
[[indox-runtime-attention]]).

## Target architecture (mirror the proven gmail pattern)
- **gmail api** (router) → `gmail api - imap smtp` | `gmail api - oauth`  — DONE + verified
  ([[inbox-canonical-contract]]). Toggle = codebase constant in router "Pick Backend" (env blocked).
- **indox api** (router, NEW) → `indox api - sheets` (NEW) | `indox api - supabase` (rename of existing
  indoxApiSupabase01). Toggle = redis `n8n.indox.data_backend` (sheets|supabase) read via a **Redis node**
  in the router (n8n blocks $env in expressions; redis node works at runtime — better than gmail's constant).
- **drive api** (router/single, NEW) → Google Drive ops behind one workflow: upload, download, list,
  move, delete, createFromText, get-link. Cred KirWFwoFdEFmnN0R. (Drive has one backend; the "api" is the
  single integration point + lets us swap/instrument later.)

## DATA API contract (from existing INDOX API supabase = indoxApiSupabase01, 21 nodes)
Interface: input json with `INLINE_ACTION` (default 'UPSERT'). Switch routes 6 ops:
- **UPSERT** — upsert a row in incoming_documents (by ID / match index). 'Resolve IDs' + 'Load Match Index' + PG Upsert.
- **GET** — get incoming_documents row(s) (Build Get SQL).
- **GET_ALL** — all incoming_documents rows.
- **DELETE** — delete incoming_documents row(s).
- **TABLE_GET** — read a generic tab/table: `{table: 'settings'|'companies'|...}` (Build Table Get).
- **TABLE_UPSERT** — upsert a row in a generic table: `{table, key, value}` for settings; row for companies (Build Table Upsert).
Code nodes: Strip Control, Resolve IDs, Build Get SQL, Build Table Get, Build Table Upsert.
Also 2 scheduleTriggers (supabase-only drivers: line-change poll + recovery sweep + 15-min terminalizer)
— these stay in the supabase backend; the SHEETS backend won't have the postgres line-change trigger
(sheets has no change-feed; main is driven by scanners/poll differently — check how sheets mode drove main before).
Tenant sheet: INDOX_SHEET_ID=1SfWUiXCpzGcfgfqbd1xogN1sUpMIlsVajL-sKH4y11U. Tabs (from _gidmap.json):
מסמכים נכנסים=incoming_documents, הגדרות=settings, חברות/Companies, + log tabs.

## DATA API — EXACT contract (extracted from indoxApiSupabase01; mirror in sheets)
Trigger: passthrough (input json as-is). Switch on `INLINE_ACTION` (default UPSERT) → 6 branches:
- **UPSERT** (incoming_documents): Strip Control (del INLINE_ACTION) → Load Match Index
  (`select "ID","COMPANY_ID","COMPANY_DOC_ID","HASH" from incoming_documents`) → **Resolve IDs** (the
  DEDUP core: for each input row pick id = row.ID if set; else match by COMPANY_ID+COMPANY_DOC_ID; else by
  HASH; else generate `doc_<ts36><rand>`. "bad" values = undefined/null/''/'unknown'/'ACTION_REQUIRED')
  → PG Upsert (autoMapInputData, matchingColumns=["ID"], convertFieldsToString=true). Returns upserted row.
- **GET**: Build Get SQL → `{ids}` → ID = any(...); or `{filter:{col:val | col:{op,value}}}` ops:
  eq/neq/gt/gte/lt/lte/like/ilike/in/contains(ILIKE). → returns matching rows.
- **GET_ALL**: `select * from incoming_documents where "ID"<>'__bootstrap__'`.
- **DELETE**: `delete ... where "ID"=any(ids) returning "ID"`. input `{ids:'a,b'}` (comma string).
- **TABLE_GET**: `{table, filter?}`; ALLOW={settings,companies,trusted_suppliers}; filter col=val.
- **TABLE_UPSERT**: `{table, ...cols}`; conflict key: settings='key', companies/trusted_suppliers=insert-only.
Output = row objects keyed by column name (callers consume e.g. $json.ID, $json.STATUS, settings key/value).
SUPABASE-ONLY driver chains (NOT data ops — keep in supabase backend only): Keepalive, On New Incoming Doc
(pg trigger→main), Poll IN_PROGRESS, On Doc Change, On Line Change, Poll Line Changes→(Get Changed Docs +
Terminalize Stalled). Sheets mode drives main differently (no pg change-feed) — investigate before relying.

## SHEETS backend build (`indox api - sheets`)
Mirror the 6 INLINE_ACTIONs against Google Sheets (cred googleSheetsOAuth2Api e2knIZpw8YF0QBAB):
- incoming_documents tab "מסמכים נכנסים": UPSERT (append/update by ID column), GET (lookup by ID),
  GET_ALL (read all), DELETE (clear row by ID). Sheets has no native upsert-by-key that matches supabase
  exactly — use googleSheets appendOrUpdate (matching column = ID). Return the SAME shape the callers
  expect (the supabase API's output rows). Match output keys to supabase so the router is a true drop-in.
- TABLE_GET/TABLE_UPSERT for settings (key/value) + companies, by tab name.
NOTE the historical sheets-rate-limit bottleneck ([[incoming-docs-sheets-ratelimit-bottleneck]]): cache
settings/companies in redis; keep per-doc reads minimal.

## DRIVE API build (`drive api`)
One workflow, op-switch (op + params), mirrors googleDrive ops used across 38 nodes/27 wfs:
upload (folderId,name,binary), download (fileId)→binary, list (q/folderId)→files, move
(fileId,addParents,removeParents), delete/trash (fileId), createFromText (folderId,name,content),
get/webViewLink. Returns Gmail-router-style canonical items. Cred KirWFwoFdEFmnN0R.

## INVENTORY to refactor (deterministic transformer like data/_gmail_refactor.py)
- Drive: 38 nodes / 27 wfs (rD3hoAVD83QPxFfS=7, gwaHealthCheck01=3, AZXF28EaGfEQjZBx=2, I584=2, LDrYJ=2, +22×1).
- Sheets: 57 nodes / 17 wfs (hlsDEi=8, pqD1=8, gSheetMcpAgent=6, nSCc=5, sv5xx=5, lmcZ=4, xXeU=4, RSlx=3, TTgW=3, +…).
- Gmail: DONE (router). MCP agent workflows (gDriveMcpAgent01, gSheetMcpAgent01, amRW9 gmail) = AI tools — LEAVE.
Refactor = replace each node with executeWorkflow → the right router, op+params mapped, KEEP node id/name/
position/connections; preserve downstream output shape (backends emulate native node output, as gmail did).

## PHASES / progress
1. [DONE] discovery + contracts (this doc).
2. [PARTIAL] data layer: [DONE] renamed supabase API name→`indox api - supabase` (id kept indoxApiSupabase01);
   [DONE] `indox api` router = indoxApiRouter01.json (passthrough → Redis GET _be cred BoJE1odVZ6MBcpax key
   n8n.indox.data_backend → Strip _be → Switch(_be==sheets else supabase) → executeWorkflow Call
   Sheets(indoxApiSheets01)|Call Supabase(indoxApiSupabase01); backends passthrough so NO workflowInputs mapping);
   [TODO NEXT] build `indox api - sheets` with id `indoxApiSheets01` (router already points at it) — mirror the
   6 INLINE_ACTIONs against INDOX_SHEET tabs per the EXACT contract above. Until built, supabase mode (default) works.
3. [DONE] `drive api` = driveApi01.json (passthrough → Op Switch download/list/upload/move/update/delete/
   createFromText → googleDrive node per op, cred KirWFwoFdEFmnN0R → Done). Contract {op, params:{fileId,
   fileIdMode,folderId,name,toFolderId,newName,content,limit,whatToSearch}} + binary passthrough for upload.
4. [ ] verify each router/backend in isolation (REST manual run + service/db checks), like gmail.
5. [ ] write transformers (data + drive) → refactor all workflows; push; verify published/active.
   (drive transformer like data/_gmail_refactor.py: googleDrive node→executeWorkflow(driveApi01) op+params per
   op. data transformer: googleSheets node→executeWorkflow(indoxApiRouter01) INLINE_ACTION+fields. Keep node
   id/name/position/connections; preserve downstream output shape. Backup data/_wf_backup first.)
6. [ ] inbox throughput fixes (APPENDUID labeling + read-conn pool) — see issues/gmail-imap-highload-throughput.yaml.
7. [ ] high-load re-run (100/type, gmail+drive) + deep per-doc trace vs spec; iterate on failures.
5b. [DONE] DRIVE refactor: data/_drive_refactor.py ran on all 26 drive workflows → 43 googleDrive nodes
    replaced with executeWorkflow(driveApi01) op+params (gmail-style typed mapping). 0 leftover drive nodes
    (driveApi01 + 2 MCP agents excluded). Backups data/_wf_backup. Pushed+published.
5c. [DONE] DATA callers: 6 executeWorkflow(indoxApiSupabase01) calls across 5 wfs (bt5,lmcZ,nSCc,oomGi,sv5xx)
    repointed → indoxApiRouter01. Pushed.
5d. [TODO] DATA sheets-node unification: 57 googleSheets nodes across 17 wfs still call Sheets directly
    (these are the SHEETS-MODE path, dormant in supabase mode). Unifying them to indoxApiRouter01 is a
    STRUCTURAL refactor (dual-path If-branches, + log tabs not in the API) — higher risk, NOT load-tested
    in supabase mode. Defer / do carefully. (Drive+data-API-callers+gmail already API-only.)
6. [DONE] inbox throughput fixes (issues/gmail-imap-highload-throughput.yaml):
   - APPENDUID O(1) labeling (was O(n) Message-ID search; 3.75s→~2s/append, non-degrading).
   - READ CONNECTION POOL (GMAIL_IMAP_READ_POOL=4) for ALL ops (reads+writes pooled, bounded — no overflow
     conns). Reads now reliably concurrent (8/8 parallel ok). FINDING: Gmail throttles many simultaneous
     IMAP conns to one account → append parallelism is limited (pool>4 caused failures); injection is
     inherently ~2s/doc serial-ish. That's a TEST-harness limit (production rarely bulk-appends).
7. [IN PROGRESS] high-load re-run + deep trace (supabase mode). Inject is slow (~2s/doc IMAP) → use moderate
   load or parallel-but-≤4. Trace per indox-runtime-attention.md.

## CRITICAL FIX (2026-06-23, found via trace) — data was not landing in supabase
Two latent bugs the abstraction exposed (both now fixed + verified):
1. n8n **Redis GET node REPLACES the item** with `{_be}` — it does NOT merge into the input. So the router
   dropped the whole payload (INLINE_ACTION/ID → `{}` reached the backend). FIX: indoxApiRouter01 now has a
   **Prep** Code node after Redis that restores the original payload via `$('When Called').item.json` + attaches
   `_be`; Backend Switch reads `$json._be` (current item, 1 rule sheets + fallback→supabase); Strip `_be` per
   branch before the executeWorkflow. VERIFIED: router UPSERT lands (`router_test_1`), and a fresh 8+4 inject
   produced 11 IN_PROGRESS rows from GMAIL + GOOGLE_DRIVE_FOLDER (invoice/shipment/BS) → drive api + data
   router → supabase all green.
2. **Empty table kills the UPSERT chain**: Load Match Index (supabase) / Read Match Index (sheets) returned 0
   rows on an empty table → n8n skips downstream nodes → no upsert (the `__bootstrap__` row only masked this).
   FIX: `alwaysOutputData:true` on both match-index nodes. (Resolve IDs handles the empty index row.)
LESSON: any n8n node that can output 0 items will silently kill its branch — use alwaysOutputData or guard.
The drive refactor is fully verified live (drive api executions succeed; downloaders save via it).

## HIGH-LOAD FINDINGS (2026-06-23 run) — production-readiness blockers
Injected 8 gmail + 4 drive (supabase mode). Refactored pipeline WORKS (data lands from GMAIL +
GOOGLE_DRIVE_FOLDER via drive api + data router; 0 API errors). BUT under the BS-line load:
- **Extreme BS-line multiplier**: 4 BS docs → 563+ DISTINCT line-invoices (SOURCE_TYPE=BALANCE_SHEET),
  zero duplicates (dedup good). Realistic balance sheets have many lines → hundreds of child docs per BS.
- **CHURN / unstable COMPLETED**: COMPLETED oscillated 5→9→1 while IN_PROGRESS climbed 185→567→575.
  Docs are NOT stably completing — something resets/re-opens them. Traced line-invoice had 0 executions
  (created but never dispatched) → most of the backlog is waiting on the bounded line-change poll
  (Get Changed Docs limit=8). HYPOTHESES to check next (deep trace over time): (a) BS re-extraction
  re-opening lines each poll; (b) a partial UPSERT clobbering STATUS; (c) recovery sweep churn;
  (d) poll backlog so deep that the 15-min terminalizer flips docs. NEXT: trace 2-3 specific line-invoice
  IDs repeatedly (scripts/indox-doc-trace.py) to catch the reset; check if a COMPLETED doc reverts.
- **LOCK FIX (2026-06-23)**: process_lock workflow `processLock01` acquired doc locks with TTL 2h
  (`60*60*2`) + one 6h → stale locks from restarts/crashes froze docs for HOURS (saw 81 piled up,
  `Process Blocked Error`). REDUCED to 10min (`60*10`) + 15min — stale locks now self-clear fast. Pushed.
  (Still good to clear locks manually after a restart, but no more multi-hour freezes.)
- **REFINED**: COMPLETED docs are STABLE (sampled doc_mqpoqaqkonra21 stayed COMPLETED over 75s; count
  steady COMPLETED=1/IN_PROGRESS=575). So NOT completed-revert churn. The real issue = 575 line-invoices
  not REACHING completion fast: main ("Incoming Documents 0.1.7") ran 15x/5min but ~1 completes → per-doc
  throughput + bounded poll are the limit. (Earlier 9→1 likely the 5 drive-BS COMPLETED re-opening on
  re-extract — verify next.) NEXT: trace 2-3 line-invoices repeatedly to find the slow/gate step.
- **THROUGHPUT bound**: line-change poll limit=8 → ~8 docs/cycle; 563 lines drains in hours, not 10min.
  To hit the bar, raise the poll limit AND give the host headroom (see memory) — they're linked.
- **MEMORY (robustness)**: Docker still ~7.6GB (no .wslconfig applied; `~/.wslconfig` memory=12GB WRITTEN,
  needs `wsl --shutdown`/Docker restart — do when user can supervise). Compose limits are TOO HIGH for 8GB:
  n8n main 4G, EACH worker 6G, +supabase/apitools — 2 workers ballooning under concurrency=8 = OOM →
  THIS caused the earlier full Docker crash. FIX (supervised): right-size limits to sum < host
  (e.g. main 2.5G, worker 2G ea, supabase 2G, apitools 1.5G, inbox 512M) + N8N_WORKER_CONCURRENCY 8→5,
  THEN raise the line-change poll limit for throughput. Don't change limits unattended (too-low OOM-kills).

## BACKEND VERIFICATION (alt backends — keep defaults supabase+imap)
- **gsheet data backend (indoxApiSheets01)**: VERIFIED in isolation — TABLE_GET settings returned 9 rows
  from the live sheet (status success). Reads work. (UPSERT/dedup path uses the same Resolve IDs + sheet
  appendOrUpdate; not load-tested but built to mirror supabase.)
- **oauth gmail backend (gmailApiOauth01)**: VERIFIED in isolation — listLabels returned 55 Gmail labels
  (status success; OAuth cred 41BKgLp83YYyfEM3 works, quota OK). Both alt backends confirmed; defaults stay
  supabase+imap. (Temp test wfs: ztestData01/ztestSheets01/ztestOauth01 — delete later.)
- THROUGHPUT CONCLUSION: 573 BS line-invoices are poll-bound (each needs ~6 sequential main executions
  gated by line-change poll limit=8). Draining needs raising the poll limit, which needs host headroom
  (12GB) — SUPERVISED. Not safe to raise on 8GB unattended (OOM risk). Safe overnight work meanwhile:
  alt-backend verification, sheets-node unification, redis caching, agent review.

## SHEETS-NODE UNIFICATION — analysis + risk (2026-06-23)
53 googleSheets nodes (excl MCP), but this INCLUDES indoxApiSheets01's OWN ~8 nodes (the backend — EXCLUDE).
Real targets ~45 across the workflows. op→tab: read→incoming_docs(23), update/delete/appendOrUpdate→
incoming_docs(8), read→settings/companies(4), append→LOG tabs(4 gids: 1516989337/2035421377/2001918388/
937213418 — NOT in the data API ALLOW), + several DYNAMIC sheetName exprs (`={{ ({settings:..` , `={{
$('Config')..`) + getMany(2). RISK: (a) must exclude indoxApiSheets01; (b) log appends need new data-API
ops/ALLOW entries; (c) dynamic sheetNames don't map cleanly to INLINE_ACTION table; (d) MANY are inside
sheets-MODE If-branches (dormant in supabase mode) — replacing the dual-path is STRUCTURAL; (e) hard to
verify safely (needs flipping to sheets mode, which affects the live pipeline). DECISION: this is NOT safe
to mass-transform unattended on the dormant path. Do it SUPERVISED, incrementally (simple read/upsert to
incoming_docs/settings/companies first; handle log-tabs + dynamic names case-by-case), verifying in sheets
mode. Overnight focus instead = agent production-readiness review + redis caching (safe, high-value).
PREP for it (safe now): add the 4 LOG tab gids to the data API TABLE_GET/UPSERT ALLOW so they're ready.

## AGENT PRODUCTION-READINESS REVIEW (2026-06-23)
### Mail Label Engine (mailLabelEngine01) — active+published; coherent post-refactor
- Entry = Schedule Trigger (Gmail Trigger correctly DISABLED for IMAP); gmail ops via router; manual trigger ok.
- GAP: 2 DIRECT sheets reads remain — "Get Tags Settings"/"Get Tags Settings1" (email-tag-rules config tab
  254281882) — should route via data API (part of deferred sheets-unification; tab not in ALLOW yet).
- CHECK NEXT: Schedule Trigger interval (must poll often enough to classify incoming mail timely, since
  there's no real-time Gmail push now). The Label Engine is CRITICAL — it applies the לטיפול-אוטומציה-*
  trigger labels the scanners depend on; if it lags, gmail-source docs aren't picked up.
- VERDICT: structurally production-ready on IMAP; finish the 2 sheets reads + confirm schedule cadence.
- FIX APPLIED: Label Engine Schedule Trigger 43min → 10min (timely classification; pushed). Real-time
  Gmail push is gone (IMAP), so the schedule is the only classifier trigger — 10min is the prod default.
### Google Workspace Agent — cluster (tag google-workspace-agent, all active):
- QR6p46Wpmvo7z53c "My workflow 15" = the agent (Gemini consuming MCP tools).
- gmailMcpAgent01 Gmail MCP Server, gDriveMcpAgent01 Drive MCP Server, gSheetMcpAgent01 Sheets MCP Server
  (gmailTool/driveTool/sheetsTool nodes = AI agent tools, correctly LEFT as-is — separate from INDOX pipeline).
- gDriveMcpAgent01 / gSheetMcpAgent01 = archived duplicates (inactive — fine).
- REVIEWED: My workflow 15 = n8n AI-agent STARTER TEMPLATE — chatTrigger ("Example Chat") → lc.agent
  ("Your First AI Agent") + Gemini (lmChatGoogleGemini) + memoryBufferWindow + tools: Gmail/Drive/Sheets
  MCP clients (good) PLUS leftover DEMO tools Get News (RSS) + Get Weather (HTTP). PROD GAPS (need a product
  decision on the agent's PURPOSE before tuning): (a) generic naming; (b) remove demo News/Weather tools;
  (c) add a real system prompt + the agent's job spec; (d) decide trigger (interactive chat vs autonomous);
  (e) error handling. The 3 MCP servers use Gmail-API/OAuth tools directly — fine for the agent (separate
  from the INDOX IMAP pipeline); only revisit if the user wants the agent's Gmail also off the API.
  RECOMMENDATION: ask the user what the Workspace Agent should DO, then tune (don't redesign blindly).

## KEY FINDING (2026-06-23) — high BS-line load → FALSE NEEDS_REVIEW (the bar-failure)
After the lock-TTL fix + restarts, the 573 BS line-invoices resolved to: NEEDS_REVIEW=444, IN_PROGRESS=129,
COMPLETED=1. The 444 are FALSE NEEDS_REVIEW: the **15-min stalled terminalizer** (in indoxApiSupabase01
"Terminalize Stalled") flips docs that sit too long; with the bounded line-change poll (limit=8) unable to
drain 573 line-invoices within 15min, most get flipped to NEEDS_REVIEW despite nothing being wrong. This IS
the production bar-failure ("zero spurious NEEDS_REVIEW") and it's a pure THROUGHPUT problem.
ROOT CHAIN: BS doc → opens N line-invoices → each needs ~6 sequential main executions, gated by poll limit=8
→ drain >> 15min terminalizer window → false NEEDS_REVIEW. FIX (SUPERVISED, needs host headroom):
(1) raise the line-change poll limit (8 → e.g. 30-50) so docs drain within the window; (2) more workers /
higher effective concurrency; (3) optionally widen the terminalizer window; ALL require the 12GB Docker +
right-sized compose limits so it doesn't OOM. After tuning, re-run high-load and confirm line-invoices reach
COMPLETED (not NEEDS_REVIEW). NOTE: a real fix may also batch BS-line processing (process many lines per
main execution) instead of one-action-per-poll-cycle — biggest throughput lever, but a pipeline redesign.

## GO-FORWARD PLAN / optimizations (better/faster/stable/minimal)
- **Sheets-node unification** (finish the data abstraction): collapse each workflow's sheets-mode-branch +
  supabase-API-branch into ONE indoxApiRouter01 call; add the missing LOG-tab ops to the data API
  (TABLE_UPSERT already covers settings/companies — add log tabs to ALLOW). Removes 57 nodes + the dual-path.
- **Caching** (fixes the historical sheets rate-limit + speeds supabase too): cache settings/companies in
  redis inside indox api (TABLE_GET reads cache first, short TTL); the inbox label map already static.
- **Injection throughput** (test-harness): true high-load seeding via IMAP is capped by Gmail. Options:
  (a) seed supabase incoming_documents rows DIRECTLY (skip Gmail) for data-layer load tests; (b) keep a
  small parallel (≤4) IMAP append for gmail-source tests; (c) a dedicated seeding account.
- **Drive batching**: drive api could batch list/move; downloaders fetch attachments via gmail api /message
  already (no extra Drive call). Consider a Drive read-pool too if Drive becomes the bottleneck.
- **Stability**: host is memory-pressured (~8GB) — high load collapses n8n/workers. Run low-memory-mode or
  add RAM before 100/type/source runs; the read pool reduces IMAP contention but n8n queue mode is the limit.
- **Minimal**: gmail/data/drive now behind 3 router workflows + backends; MCP agents kept as-is. Next minimal
  win = the sheets-node unification (−57 nodes) + deleting the per-workflow dual-path code.
- **Verification cadence**: inject ≤40/type (IMAP cap), or direct-seed supabase for pure data-layer load;
  trace every doc (scripts/indox-doc-trace.py) to COMPLETED; assert no stuck IN_PROGRESS / spurious REVIEW.

## Gotchas (carry-forward)
- Push: `bbox n8n push` imports+publishes active set+restarts; sub-WFs need active+activeVersionId to be
  callable ([[n8n-executeworkflow-publish-gate]]); files need `"active": true`. After push, wait n8n healthy.
- executeWorkflow caller needs workflowInputs mappingMode=defineBelow + schema (else inputs don't pass).
- Windows: `docker exec -i ... <<heredoc` works; `--input=/path` needs MSYS_NO_PATHCONV=1; python file reads need encoding='utf-8' (Hebrew). Junctions: data/data-set-2 + data/_runs → data/exclude/*.
- Host is memory-pressured (~8GB) — high load collapses it; restart unhealthy containers; consider low-memory-mode.
- Backups of pre-refactor workflows: data/_wf_backup/ (gmail era); make fresh backups before drive/sheets refactor.
