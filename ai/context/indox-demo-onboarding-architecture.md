# INDOX clean onboarding + demo architecture (ship target)

**Goal:** a clean, fully-declarative, machine-reproducible deployment where, after `bbox reset` (full wipe)
+ `bbox onboarding`, you can reach a *rest* state via either path, repeatably:
- **3× welcome-to-rest** (default 5×1 self-generated docs)
- **3× small-demo-to-rest** (5×5 fixture)
all fast (no live Gemini), deterministic, no host-side injection.

Build from a **clean wipe** (state is currently polluted from testing). Validate = `bbox reset --force →
bbox onboarding → trigger the cycle → docs reach COMPLETED + system at rest`, ×3 each.

---

## 1. AI extraction cache → Postgres + indox API  (foundational; do first)

Today (both extractors, `indoxV2ExtractInvoiceGemini01` invoice + `indoxV2ExtractBalanceSheet01` BS):
`Crypto (hash binary → cached_input_key)` → `KVStorage` redis GET `n8n.indox.{inv,bs}cache.<key>` →
`If inv_cached/bs_cached notEmpty` → hit: parse cached JSON / miss: Gemini → `KVStorage1` redis SET.

Migrate:
1. **Table** (add to the inline `Ensure Schema` DDL in `IndoxResetFull01`):
   `create table if not exists public.ai_extraction_cache (cache_key text primary key, kind text, value text, created_at timestamptz default now());`
2. **API ALLOW** — in `indoxApiSupabase01` `Build Table Get` + `Build Table Upsert`, add
   `ai_extraction_cache:'cache_key'` to the ALLOW map (conflict on cache_key).
3. **Rewire each extractor** (replace the 2 redis nodes; preserve binary+key via `$('Crypto')`):
   - GET: `Crypto → [Req code {INLINE_ACTION:'TABLE_GET',table:'ai_extraction_cache',filter:{cache_key:'<kind>:'+key}}] → [executeWorkflow indoxApiRouter01] → [Map code {inv_cached:(rows[0]?.value)||'', cached_input_key:$('Crypto').first().json.cached_input_key, binary:$('Crypto').first().binary}] → If`
   - SET: after Gemini, `[Upsert code {INLINE_ACTION:'TABLE_UPSERT',table:'ai_extraction_cache',cache_key:'<kind>:'+key,kind,value:$json.toJsonString()}] → executeWorkflow indoxApiRouter01`
   - cache_key = `'invoice:'+hash` / `'bs:'+hash` (kind column too). Crypto algo = the node's default (SHA256 of binary).
4. **Redis** then holds only n8n queue/locks (no app cache) — matches "redis only for ai cache… actually move to pg".

**Pre-populate the cache for demo files** (so demo = 0 Gemini calls, deterministic): for each demo file,
the cache_key is `'<kind>:'+SHA256(file bytes)`. Build a one-time step (in the blueprint setup) that
upserts `{cache_key, kind, value}` for every demo file — value = the extraction captured once (run Gemini
once during blueprint authoring, freeze it into the blueprint). Ship the cache rows IN the blueprint.

---

## 2. Three declarative blueprints  (consolidate ALL current demo impls into these)

Location: `production/n8n/demo/` (git-tracked). Each is a self-contained fixture: yaml + files + cache.
Retire/replace: host scripts (`highload-inject*`, `_inject_gmail_direct`, `indox-*-company-state`),
`IndoxInjectDemo01`, `production/indox/demo-company-state.yml`.

### a. `default-welcome` (5×1, self-generated) — the zero-dependency baseline
- 1 doc per sync (gmail-doc, gmail-bs, gmail-link, drive-gdoc, drive-bs) = 5 docs.
- **Self-generated**: synthesize 5 tiny PDFs at setup (deterministic text → known company/amount/date),
  so NO real client files needed → portable to any machine. Ship their frozen AI-cache entries too.
- `welcome.yml`: 1 company (demo), the 5 docs (type, sync, synthetic-content spec), cache keys.

### b. `small-demo` (5×5) — the main demo fixture
- `demo-blueprint.yml` (the fixture) + a `files/` folder with the 25 attachments (curated from
  `production/n8n/demo-docs`, 5 per sync, distinct → no hash-dedup collisions).
- Declares per-sync: the 5 docs, attachment paths, expected company (seed companies block),
  AND the frozen AI-extraction-cache rows for all 25 files.
- Includes a `setup:` block (settings/sync_registry already seeded by Reset+Setup; this adds the
  demo companies + the cache).

### c. `large-demo` (30×5) — load/scale via the API
- `large-demo.yml` = the desired state (30 per sync) + file refs. `bbox indox demo large` reads it and
  uses the **indox API** to append the desired state (TABLE_UPSERT companies + the doc rows / gmail+drive
  fixture refs), + loads the AI cache. Built to exercise scale, not portability.

---

## 3. "Reset sync state" (declarative, no injection)

The demo content is a **fixture that already exists** in gmail (labeled) + drive (files in source folders)
+ the table/cache. "reset sync state" = re-queue the fixture to its initial to_sync/IN_PROGRESS state so
the pipeline reprocesses it — NOT host append. Implement as an n8n workflow action (driven by the chosen
blueprint): clear table → restore each sync's to_sync labels/folders for the blueprint's docs → seed
companies + AI cache → let the scanner drain. `bbox indox reset-sync-state <welcome|small|large>`.

On a full wipe, gmail/drive (external) persist → the fixture survives; only volumes (table/redis/n8n) are
wiped + rebuilt by onboarding → so reset-sync-state re-drives the persistent fixture. (For a brand-new
Google account, the fixture must be (re)created once — the blueprint's setup creates the gmail labels +
uploads the files; thereafter wipes don't touch them.)

---

## 4. bbox surface (consolidated)
- `bbox onboarding` → already auto Reset+Setup (inline schema seeds config + ai_extraction_cache table).
- `bbox indox demo <welcome|small|large>` → load that blueprint's companies+cache, ensure fixture, reset-sync-state, drain.
- `bbox indox reset` → INDOX Reset + Setup (clear-to-initial + config).
- Old host inject/reset scripts → deleted (logic lives in the blueprints + n8n).

## 5. Validation loop (the /goal)
```
for run in 1..3:  bbox reset --force; bbox onboarding (INDOX_DEMO=welcome); assert 5 docs COMPLETED + rest
for run in 1..3:  bbox reset --force; bbox onboarding (INDOX_DEMO=small);   assert 25 docs COMPLETED + rest
```
"rest" = no running execs, table all COMPLETED (no IN_PROGRESS/REVIEW/MISSING), 0 errors, within target time.

## What's already done this session (feeds into the above)
- Config + schema fully via Reset+Setup (inline `Ensure Schema`/`Ensure Buckets`; Supabase Setup retired); config seeded via API.
- OAuth on solutionsbina (re-cached, survives wipe); creds renamed account-agnostic.
- Selection routed through the Settings WF (no gsheet); trusted-supplier feature moved to `companies` (SELECTION_CERTAINTY/TRUSTED_SOURCE_TYPES).
- RECEIVED_DATE robust (gmail received / drive upload). SYNC_NAME wired end-to-end (incl the `jsonExample` boundary fix). Warehouse setting via API.
- git-tracked `production/n8n/demo-docs/` (90 inv + 15 ship + 60 bs) + served by `indox-demo-docs` http service.
See [[fresh-clone-onboarding-findings]] [[indox-api-routing-and-architecture]].
