# INDOX Consolidation Plan — 2026-08-05

Status: **COMPLETE.** Companion to `INDOX-CODEBASE-MAP-2026-08-05.md` (read that first for full
evidence). All five research agents this plan drew on have returned; remaining `[PENDING]`/
`[UNVERIFIED]` markers below are genuine open questions the evidence gathered could not settle, each
stated with what would settle it — not placeholders for missing agent output.

## The spine: 87,405 lines of n8n vs 72,232 lines of Python

More business logic lives in n8n workflow JSON than in the typed Python service. Confirmed directly
(`ls blueprint/n8n/*.json | wc -l` → 66; `wc -l blueprint/n8n/*.json` → 87,405 total lines; Python
`apps/indox/app/incoming_documents` → 171 files, 72,232 lines per the task's prior scan). That is the
central structural fact this whole plan responds to: **the same documents are governed by two
divergent rule systems, encoded in two different technologies, evolving independently.**

**Working position (from the coordinator, tested against evidence below): n8n is right for
integrations, wrong for a per-document state machine.** Evidence found so far that supports this,
each a failure mode *typed, tested code structurally does not have*:

1. **Silent no-op on unknown input, instead of an error.** `runSyncEntry`'s manage webhook "answers
   HTTP 200 for a verb it does not implement, so the only way to know a run happened is to read the
   flag" (`apps/indox/app/webapp/src/api.ts:859-864`, direct read). The `indoxV2Driver01` `Switch1`
   node is **confirmed** a hardcoded 18-action allowlist with the same shape of risk (unmatched action
   ⇒ falls to the `fallbackOutput: "extra"` branch rather than erroring) — verbatim node contents in
   Doc 1 §1c, including a typo (`"update_status_unknwon_company"`) proving the list is hand-maintained
   copy-paste, not generated from a shared source. A typed
   dispatcher (Python `match`/dict-of-handlers with an `else: raise`) cannot silently swallow an
   unrecognized case without someone deliberately writing that bug; n8n's Switch node's default
   behavior *is* silent fallthrough unless every branch is deliberately wired to an error path.
2. **Declared schema, unenforced writes — CONFIRMED by live query, and worse than "unpopulated": it's
   an always-true no-op gate.** `NEXT_RETRY_AT` = 0 of 6,196 rows, confirmed exactly
   (`COUNT(*)=6196, COUNT("NEXT_RETRY_AT")=0`). This is not merely a dead column — it is **actively
   read as a gating predicate in production**: `blueprint/n8n/indoxApiSupabase01.json:520,606` gate
   the poller's candidate-selection and stall-termination queries on `"NEXT_RETRY_AT" is null or
   "NEXT_RETRY_AT" <= now()`. Because the column is always null, that predicate is always true — the
   retry-delay mechanism the query was written to express has never once actually delayed a retry.
   The only write site anywhere in the n8n workflows (`indoxDocBatchUpsert01.json:11`) hardcodes it to
   `null` in a template. Five more columns share this always-empty property (`EMPTY`, `EX_INVOICE_ID`,
   `EX_IS_BS`, `EX_IS_BS_COMPLETED`, and a Hebrew-named column). Of the 88 columns on
   `incoming_documents`, **39 have zero Python source references at all** — including
   `NEXT_RETRY_AT`/`RETRY_COUNT` themselves: the retry/claim state machine is **entirely n8n's
   responsibility, and it silently does not work.** A column a Python model declares but nothing
   writes is at least visible to a type checker; a column an n8n gating query reads but that no node
   ever computes is invisible until someone runs exactly the query this task ran.
3. **Three divergent identity formulas for `SHORT_DOC_ID` — CONFIRMED, with exact code.** One
   canonical formula (documented in a comment at `indoxV2Decide01.json:23-24`:
   `String(rawId).replace(/[^a-zA-Z0-9]/g,'').slice(-5).padStart(5,'0')`, used correctly in
   `indoxV2Driver01.json:3235,4108` and the GDoc/Shipment action workflows) plus two divergent variants
   producing **different output for the same input**: `indoxV2ActionsBS01.json:1197,1239` skips the
   alphanumeric-strip step (its own comment at line 1239 admits this is deliberate: *"exactly as the
   old Execute Workflow1 mapping"*), and `indoxGmailLinkDownloader01.json:467` skips both the strip
   *and* the zero-pad. This is exactly the *default* outcome n8n's execution model produces unless
   someone factors the expression into a shared subworkflow and every caller is disciplined about
   using it — there is no import system, no single function, just copy-pasted Function-node
   JavaScript across workflow files, and one of the three copies has an explicit comment acknowledging
   it diverges on purpose. Python has an import system; the fix in Python is "one function,
   everyone imports it" and a lint/grep can prove convergence. The fix in n8n requires a shared
   subworkflow *and* an audit that nothing still inlines the old expression.

**Confirmed, load-bearing finding that sharpens all of the above**: the caller-mapping agent found
that of the 66 n8n blueprints, **only one file** (`indoxV2GenerateThumbnail01.json`, calling `POST
/documents/thumbnail`) makes an actual HTTP call into the Flask API. Every other n8n workflow that
touches indox data **writes directly to Postgres** — raw SQL or `INLINE_ACTION`/`TABLE_GET`/
`TABLE_UPSERT` nodes against `public.settings`/`companies`/`tag_rules`/`sync_pipe_state` — or goes
through n8n's own `/webhook/indox-manage`, which the Flask API calls into (not the reverse). This means
every validation/normalization guarantee the Python side builds (`_normalise_entry`'s vocabulary
repair, `_validate_sync_entry`, the `_EDITABLE_SETTINGS_KEYS` allowlist, `_paged_select`'s
truncation-safety) protects **only the one workflow that happens to route through Flask**. The other
65 have direct write access to the same tables with none of those guarantees. This is not "two rule
systems evolving independently" as an abstract risk — it is **two rule systems with independent,
unmediated write access to the same rows**, which is strictly worse. See Doc 1 §1a for the full
citation.

None of these three are things n8n cannot do correctly — they are things n8n's execution model makes
*easy to get wrong silently* (no compiler, no type system, copy-paste-first workflow authoring, an
HTTP-200-by-default trigger contract) in exactly the place where a document's lifecycle state must be
unambiguous. That is the principle for the Python-vs-n8n split (Doc 2 §2b), not a per-workflow
case-by-case call:

> **Put a rule in n8n if its job is to reach an external system whose behavior n8n already models well
> (OAuth refresh, retry/backoff on transient HTTP failure, polling a mailbox/folder, calling
> apitools/Gemini). Put a rule in Python if its job is to decide or mutate the document's own state**
> (identity, current STATUS, next STATUS, whether a write should happen) — because that decision needs
> to be typed, unit-testable without any external system running, and impossible to silently no-op.

## 2a. Dead code and duplication

### Confirmed duplication / two-sources-of-truth, with direct evidence

- **`context-collection/n8n-workflows/` — CONFIRMED DEAD.** A frozen Phase-1 planning snapshot of
  `Incoming Documents 0.1.6`, self-documented in its own `README.md` as "context required for phases
  2-6 of the migration plan" — explicitly a planning artifact, not runnable. Confirmed: grepping all
  66 live `blueprint/n8n/*.json` files for the old-generation names (`incoming-documents-0.1.6`,
  `batch-upsert_lmcZgw2TU8KOBXgs`, `indoxApiSheets01`, `indoxDocCreate01`, `indoxSetupWF001`) returns
  zero cross-references. **Verdict: DEAD (documentation artifact) — safe to remove; bloats the "what
  n8n logic exists" surface for anyone auditing by directory listing**, a real cost given this task's
  own starting confusion was exactly "how much n8n logic is there."
- **`legacy/n8n/indox-sheets-era/` — MIXED, one file is a live production landmine.** 4 of the 5 files
  (`indoxApiSheets01`, `indoxDocCreate01`, `indoxSetupWF001`, `logger01`) have zero cross-references in
  `blueprint/n8n/*` and no matching live DB row by that id — dead. **But `indoxDocUploader01`
  (DocumentUploader) is a live, `active=true` row in the n8n production database today** (n8n agent's
  DB cross-reference, Doc 1 §1c) — the only DB workflow whose `updatedAt` (2026-08-04 17:44) predates
  every other row's (2026-08-05 13:50), and whose only source in the repo is this `legacy/` folder.
  **This is not safe to delete or treat as dead documentation** — it is currently running in
  production despite living in a directory named "legacy." Flagged for a dedicated follow-up (out of
  this task's scope to resolve, since deciding whether to retire it requires understanding what
  currently depends on it in production, which is a live-system question this static/DB audit cannot
  fully answer) — **do not act on this one without further investigation.**
- **Two things named "registry", not the same thing** — confirmed by direct read of
  `apps/indox/app/incoming_documents/core/registry.py` (full file read) vs
  `apps/indox/app/webapp/src/api.ts` (`SyncRegistryEntry`, `/sync/registry*` routes,
  `getSyncRegistry()`):
  - **Repo registry** (`core/registry.py`, `RepoRegistry` class): a **file-backed** JSON store,
    `.storage/incoming_documents/repos.json` by default (`INCOMING_DOCS_REPO_REGISTRY` env override),
    mtime+size-stamped hot-reload, atomic `os.replace` writes. Answers "what repos (backend targets)
    exist" — one entry per `RepoConfig`.
  - **Sync registry** (`settings.sync_registry`, a DB-backed JSON blob read/written through
    `/sync/registry` routes in `api/__init__.py`): answers "what sync pipes exist, their engine,
    connection, schedule, folder mapping" (`SyncRegistryEntry` fields in `api.ts:199-238`: `source`,
    `engine`, `processor_wf`, `batch{}`, `pairs[]`, `labels{}`, `dest_folder`, `failed_folder`,
    `connection`, `enabled`...).
  This is not necessarily a *defect* — they're legitimately different concerns (storage backend vs.
  sync-pipe config) — but the shared name "registry" for two config sources with two different
  storage mechanisms (file vs. DB row) is exactly the kind of naming collision the task's "one config
  source of truth for the registry" ask is probably pointing at. **The consolidation target is not
  "merge them" (they model different things) but "rename one so `grep -ri registry` stops returning
  two unrelated systems"** — see §2c.
- **The dual transport backend (`gsheet` vs `supabase`) — RESOLVED, see Target 5.** Both are still
  first-class, exported, unguarded code (`backends/__init__.py` exports both with no deprecation
  marker; `repo_factory.py:169-198` dispatches on `RepoConfig.backend` with no warning for `"gsheet"`),
  and the webapp's UI still offers it (`InstanceSwitcher.tsx:347-351`). But this is now **confirmed**,
  not inferred: two of the repo's own architecture docs state gsheet is dead
  (`ai/context/indox-final-architecture-2026-08-04.md:101-102`, `ai/context/retired-code-and-workflows.md:123-126`),
  and the live production registry (`storage/incoming_documents/repos.json:3`) has exactly one repo,
  pinned to `"backend":"supabase"`. The data-layer agent additionally found the gsheet transport
  **silently drops any column not already in the sheet header row** (`backends/gsheet.py:363-367,396-401`,
  its own comment: *"unknown column → skip silently to mirror n8n tolerance"*) while the supabase
  transport hard-errors instead — meaning gsheet isn't just unused, it's a worse-behaved write path
  than the one it would otherwise coexist with. See Target 5 for the deletion plan.

### Confirmed dead code (final, cross-agent-verified)

| Item | Evidence | Verdict |
|---|---|---|
| `POST/PUT /documents`, `POST /documents/upload`, `POST /repos/<repo>/documents/upload` | Caller-mapping agent: zero references in webapp, sim, n8n (66/66 checked), hooks, scripts, or tests | **DEAD — safe to remove** |
| `GET /repos/<repo>/kafka/tail` (SSE) | Implemented + tested (`test_facade_routes.py`), documented in `IMPLEMENTATION-PLAN.md`, but no `EventSource`/`fetch` call anywhere in webapp or sim | **Live-but-unused — built ahead of UI. Decide: wire it up or remove it; do not leave a tested-but-orphaned endpoint indefinitely.** |
| `GET /openapi.json`, blueprint-level `GET /health` | Only pytest calls them for real | **Low-priority cleanup — keep `/health` (cheap, harmless liveness surface) but note it's redundant with the real app-level `/health` in `app/main.py:85`; `/openapi.json` either wire into a real generated-client flow or drop the pretense** |
| `webapp/src/components/DataGrid.tsx` (788 lines) | Module-map agent: zero import matches anywhere in `app/webapp/src` (only unrelated CSS comment references) | **DEAD — confirmed superseded by `BinaTable.tsx`. Safe to remove.** |
| `blueprint/fixtures/field_defs.json`, `fixture_INVOICE.json` (+`.oracle.md`), `REFACTOR-OUTLINE.md`, `ROUTERS-ARCHITECTURE.md`, `tools/shadow_diff.py`, `types/fixture_*.json` (7 files/dirs, part of a stalled generic-engine redesign) | Module-map agent: `tools/shadow_diff.py` hardcodes paths (`production/n8n/fixtures`, `production/n8n/lib/normalizers.js`) that no longer exist post-refactor; the rest is self-referential only within this dead family | **DEAD — a stalled refactor attempt, never cut over. Safe to remove as a group; keep `schema.sql`, `settings.json`, `tag_rules.json`, `ai-extraction-cache.json` (confirmed live).** |
| `blueprint/fixtures/tag_rules.json` | Pre-existing finding in `ai/context/AUDIT-FINDINGS-2026-08-05.md`: byte-identical duplicate of `apps/mail/mailapi/fixtures/tag_rules.json` | **DUPLICATE across apps, not just within indox — out of this task's direct scope (mail app) but worth a cross-app follow-up: one canonical `tag_rules.json`, not two copies that can silently drift.** |
| `apps/indox/app/incoming_documents/context-collection/` | Self-described "Phase 1 — Done" planning snapshot; nothing imports it | **DEAD (documentation artifact) — see §0 of Doc 1. Low priority; mainly a "don't be confused by this directory" flag for future auditors, not a functional risk.** |
| `sync_cursor` table + its `CURSOR_GET`/`CURSOR_SET`/`RESET` API in `syncLedgerApi01.json` | Data-layer agent: 0 rows; grepped every n8n workflow for callers, found only the handler itself and one test suite (`syncV3KernelTest01.json`) — no production sync workflow calls it | **Live-but-unused (built ahead of adoption) — same shape as the `kafka/tail` route finding. Decide: wire the production sync workflows to use it, or remove the unused CRUD surface. Do not silently leave a fully-built, zero-caller feature indefinitely — it's a maintenance cost with no payoff either way.** |
| `backends/gsheet.py`, `backends/gsheet_transport.py` | See Target 5 below — **PARTIALLY-LIVE, do not delete without the explicit decision in Target 5** |
| `legacy/n8n/indox-sheets-era/indoxDocUploader01.json` | n8n agent: `active=true` in the live n8n DB, the one workflow-row with a stale `updatedAt` predating every other row | **NOT DEAD — flagged, not resolved. Do not delete; needs a dedicated live-system investigation this audit could not complete (see §2a note above).** |

### Full pagination-defect tally (cross-agent)

10-11 confirmed silent-truncation-risk call sites so far: 6 in `api/__init__.py` group A
(`_CONFIG_READ_LIMIT=2000` sites), 1 in group B (`sync_runs`, hardcoded `limit=500`), 1 unverified in
group C (`batch_query`'s `truncated` flag), 2 in group D (60k-row hardcoded ceilings), plus
`backends/supabase.py:172-175`'s `SupabaseRepo.fetch_all()` (no limit/offset at all — the base-layer
version of the same bug, only worked around per-call-site by `poller.py:37-61`, never fixed at the
source). This accounts for roughly 55-60% of the task's ~18-instance estimate from Python alone;
the remainder is expected in `extraction.py` and/or the n8n workflows — pending the n8n agent.

### Identity/dedup landscape (Python side confirmed; n8n side pending)

**No `SHORT_DOC_ID` and no hash-generation function exists in `api/__init__.py`** (confirmed by direct
grep — zero matches for `hashlib|md5|sha1|sha256|SHORT_DOC_ID`). The module-map agent found five-plus
*different* identity/match implementations elsewhere in Python, each solving a genuinely different
sub-problem: `core/diff.py`'s `compute_diff` (PK → composite match-rule → same-batch merge),
`backends/{gsheet,supabase}.py`'s `fetch_by_match_rules` (composite-key lookup), `hooks/migrate-legacy.py`'s
HASH-group ranking (one-off legacy dedup), `hooks/sync-seed-ledger.py`'s `platform_id`/`content_hash`
derivation (ledger backfill), and `extraction.py`'s `_ocr_hash`/`_ocr_file_id` (a **different concept**
— OCR-cache key, not document identity, with the file's own comment documenting that conflating the two
was a historical bug source). **None of these is `SHORT_DOC_ID`.** Whatever computes `SHORT_DOC_ID`
lives in n8n or `apitools` — pending the n8n agent's exact formula count/text. This means Target 2
below cannot be "pick the best of 3 Python functions" — it has to be "identify which n8n/apitools
formula(s) are the real divergence, and decide whether Python should own identity at all or whether
this one concept correctly belongs to n8n/apitools as the layer closest to the source bytes."

### A second, independent dual-generation risk: sync registry v1 vs v3 engine split

Distinct from the repo-registry/sync-registry naming collision above: within the sync registry itself,
`hooks/sync-state:37-51` documents a v1 (in-memory scanner walk) vs. v3 (Postgres `sync_ledger`) split,
and `hooks/sync-engine:5-13` documents the **live risk of the v1 scanner double-claiming items** because
it isn't engine-aware — guarded only by a runtime check in `sync-engine:39-53` before allowing a v1→v3
flip. A single `sync_registry` entry's `engine` field selects between two structurally different
reconciliation code paths over the same row. This is the same "declared concept, divergent
implementation" pattern as the identity-function and pagination findings, but entirely within
Python/hooks rather than Python-vs-n8n — worth its own consolidation target (see new Target 6 below).

### n8n blueprint agent — final results (all four questions resolved)

- **Blueprint-vs-DB cross-reference: 0 never-pushed files, 0 true orphans.** All 66 blueprint files
  match a live DB row; the 12 DB workflows with no blueprint file inside `apps/indox/blueprint/n8n/`
  all resolve to real files elsewhere in the repo (cross-app shared workflows), except
  `indoxDocUploader01` — see the `legacy/n8n/indox-sheets-era/` flag above, the one genuine loose end.
- **Test/fixture workflows shipping in production: CONFIRMED, the worst case named in the task.** 9
  E2E/test/fixture blueprints are `active=true` and executed *today* in the same n8n instance as
  production traffic, zero environment separation (`indoxV2TestFixtures01` — 19 executions today alone).
  See Doc 1 §1c full table. **This is a new, independently-actionable finding, added as Target 7 below.**
- **`SHORT_DOC_ID`: 3 divergent formulas, confirmed with exact code** — folded into the spine
  argument above and Target 2 below.
- **`indoxV2Driver01`'s `Switch1`: confirmed** hardcoded 18-action allowlist, typo included — folded
  into the spine argument above.
- **`errorWorkflow` "41 dangling": REFUTED.** Real count is 23, all pointing to the identical value
  `errorHandler01`, which is a real, live, `active=true` (78 executions) shared platform workflow at
  `platform-base/n8n/workflows/errorHandler01.json` — not dangling, just outside the `apps/indox/`
  folder the original observation apparently scoped its search to. **No action item results from this
  one** — it is a correction to the task's premise, not a defect. Included here specifically because
  the task's own standard demands reporting a refutation as prominently as a confirmation.

## 2b. Consolidation targets

`[STRUCTURE FINAL, specifics pending fold-in]`

### Target 1 — split `api/__init__.py` along its real seams

Pending the deep-audit agent's seam proposal (route-by-route + helper-by-helper clustering). Principle
committed now: seams should follow **resource + backend dependency**, not file-size balancing, because
the actual defect this fixes is "you cannot reason about the documents-CRUD code path without also
loading 5,265 lines of sync/registry/extraction/test-runner code into your head." A split that
produces 5 files of ~1,000 lines each but where every file still imports every other file's helpers
buys nothing. **What it makes structurally impossible, not merely fixed:** a correctly-scoped split
(each module importing only `core/*` + its own concerns, never reaching into another resource module's
private helpers) makes it impossible to accidentally couple, say, the extraction-run endpoints to the
sync-registry's internal cache invalidation — today, sharing one module-global namespace, nothing
prevents that coupling from creeping in silently.

### Target 2 — one canonical `SHORT_DOC_ID` formula

Now fully evidenced: the canonical formula is known
(`String(rawId).replace(/[^a-zA-Z0-9]/g,'').slice(-5).padStart(5,'0')`, documented at
`indoxV2Decide01.json:23-24` and used correctly in 4+ workflows), the two divergent variants are known
with exact file:line, and — critically — **`SHORT_DOC_ID` is computed nowhere in Python** (confirmed
absent from `api/__init__.py` and from every other Python identity/match function found). Given that
"of 66 n8n workflows, only 1 calls the Flask API over HTTP" (Doc 1 §1a), routing every `SHORT_DOC_ID`
computation through a Python HTTP call is not the pragmatic target — it would add a network round-trip
to a currently-synchronous string transform, in the one part of the system that is demonstrably
n8n-native today. **Revised target: a single n8n subworkflow (`indoxUtilShortDocId01` or similar) that
implements exactly the canonical formula, called via `executeWorkflow` node (n8n-native subworkflow
call, not HTTP) from every one of the 20 files that currently compute it inline** — including
`indoxV2ActionsBS01.json` and `indoxGmailLinkDownloader01.json`, whose divergent formulas must be
retired, not just deprecated alongside the canonical one. Add a companion Python function in `core/`
too (even though nothing calls it today) **only if/when the runtime-architecture companion document's
identity design calls for Python to own document identity** — do not add unused Python surface
speculatively. **What this makes impossible:** a fourth divergent formula appearing next quarter,
because n8n's `executeWorkflow` call is the one mechanism in this codebase that gives workflows an
"import," the same structural role Python's import system already plays — the fix targets the actual
medium the bug lives in, rather than routing around it into a layer that currently has zero stake in
this computation.

### Target 3 — one config source of truth for "the registry"

Given §2a's finding that "registry" currently names two different systems (file-backed repo registry,
DB-backed sync registry), the fix is **not** a merge but a **rename + single-accessor pattern per
concept**:
- Rename `core/registry.py`'s `RepoRegistry` references in code/docs to "repo registry" consistently
  (already accurate in the class name, inconsistent in the task/doc prose that just says "registry").
- The **sync registry** (DB-backed) gets the same `core/`-level treatment the repo registry already
  has: today it's read/written ad hoc through `api/__init__.py` route handlers directly against
  Supabase (per `api.ts`'s `/sync/registry*` methods) with no equivalent to `RepoRegistry`'s
  mtime-cached, atomically-written, single-class ownership. **What this makes impossible:** two
  different route handlers in `api/__init__.py` reading/writing `settings.sync_registry` with
  slightly different serialization or caching assumptions — a real risk in a 5,265-line file with many
  hands, and exactly the kind of thing a single owning class (like `RepoRegistry` already models)
  structurally prevents by being the only code path allowed to touch the row.

### Target 4 — one pagination accessor that cannot silently truncate

The task names `PGRST_DB_MAX_ROWS=1000` as an ~18-instance defect class; `api.ts:765-776` independently
documents the exact failure mode in production (`monthIndex` exists *because* the naive client-side
loop silently stopped after page 1). Target: **a single `paged_select(table, columns, filter, ...)`
helper in `core/` (not `api/`) that (a) always follows PostgREST's `Content-Range` response header to
know the *server's* real page size rather than assuming the requested `limit` was honored, and (b)
returns `(rows, truncated: bool, sampled: bool)` as a structural part of its return type — never a bare
list.** **What this makes impossible, not merely fixed:** any caller silently treating a partial result
as complete, because the type signature itself forces the caller to handle `truncated`/`sampled` —
today, an unpaged `.select()` call *type-checks identically* to a correctly-paged one; nothing at the
call site distinguishes them, which is exactly how ~18 instances of the same bug accumulated
independently. A shared accessor with an honest return type turns "did I remember to page this" from a
per-call-site discipline problem into a compiler-enforced one.

### Target 5 — the two-transport backend question (RESOLVED: PARTIALLY-LIVE)

**Confirmed, not inferred.** Two of this repo's own architecture docs already state the verdict in
plain language: `ai/context/indox-final-architecture-2026-08-04.md:101-102` — *"backends/supabase*.py
— the live backend (gsheet*.py retained but unreachable; backend: supabase is pinned)"* — and
`ai/context/retired-code-and-workflows.md:123-126` — *"Google Sheets is fully legacy... the
`INDOX_DATA_BACKEND` toggle was removed... so nothing can point a deployment [at gsheet]."* The live
production registry (`storage/incoming_documents/repos.json:3`) has exactly one repo, pinned to
`"backend":"supabase"`. But the code is **not** guarded: `repo_factory.py:169-177` will construct a
real `GoogleApiTransport`-backed `GSheetRepo` the moment any `RepoConfig.backend=="gsheet"` is
registered, and the webapp's `InstanceSwitcher.tsx:347-351` still offers a "Google Sheets (גיליון)"
option in the new-instance form.

**Target state: delete, in this order, not as one PR:**
1. Remove the `gsheet` option from `InstanceSwitcher.tsx`'s new-instance form (UI-level — stops new
   instances from ever choosing it; zero backend risk, purely subtractive).
2. Narrow `RepoConfig.backend` to `Literal["supabase"]` (Python) / `'supabase'` (TS in `api.ts`), so
   `POST /repos`/`/account/add` reject `"gsheet"` at the validation layer rather than silently
   accepting and constructing a working-but-unmaintained repo.
3. Delete `backends/gsheet.py`, `backends/gsheet_transport.py`, and
   `tests/integration/gsheet/test_gsheet_repo.py` (289 lines of real coverage for code that will no
   longer be reachable — keeping it would just be dead-code coverage of dead code).
4. Delete the `gsheet{}` sub-config type and `repoSource()`'s gsheet branch in `api.ts`.

**What this makes impossible, not merely fixed:** a new repo ever being silently misconfigured onto an
architecturally-declared-dead backend — today `POST /repos` will accept `backend: "gsheet"` and
nothing in the request path warns the caller it's the cold path; two docs already say it's dead, but
nothing enforces that at the one place (`RepoConfig` validation) that could make it structurally true.
**Risk: low** — this is deleting code two other documents already declare unreachable, confirmed by a
production-registry read showing zero live gsheet repos. **Verify:** full existing test suite still
green after removing `test_gsheet_repo.py`; `POST /repos {"backend":"gsheet",...}` returns a 4xx
validation error post-change, not a 200.

### Target 6 — sync registry v1/v3 engine split (new — surfaced by the module-map agent)

Independent of Target 3's registry-naming fix, the **sync registry's own `engine` field** currently
selects between two structurally different reconciliation implementations over the same row:
`hooks/sync-state:37-51` documents the split (v1 in-memory scanner walk vs. v3 Postgres `sync_ledger`),
and `hooks/sync-engine:5-13` documents that v1 is not engine-aware and can **double-claim** items —
guarded today only by a runtime check in `sync-engine:39-53` gating the v1→v3 flip. Target: retire v1
entirely (v3/ledger-based reconciliation is the documented direction — see the runtime-architecture
companion document for the target sync design) once every registered pipe has been flipped, and delete
the flip-guard/dual-path code rather than maintaining it indefinitely. **What this makes impossible:**
a pipe silently running the double-claim-prone v1 path because nobody flipped it — today that is a
config-value choice with a runtime guard against the worst outcome; the target state removes the choice
entirely. **Risk:** medium — this is live sync logic, not dead code; sequence behind Doc 1's sync
runtime-design companion document, which owns the target sync architecture question. **Do not schedule
this before the 13,760-doc backfill** unless every pipe is already confirmed on v3 — flipping engines
mid-backfill is exactly the kind of change that should not race a large data operation.

### Target 7 — stop test/E2E/fixture n8n workflows from running against production (new, n8n-agent-confirmed)

9 test/fixture blueprints are confirmed `active=true` and executing today in the same n8n instance as
production traffic (Doc 1 §1c), with no directory/environment separation from the ~47 confirmed
production workflows. Target: **either (a) move test workflows to a separate n8n instance/project with
its own credentials and its own database, or (b), if a second n8n instance isn't feasible short-term,
at minimum namespace them clearly (a `test/`/`qa/` id/name prefix enforced by CI) and confirm none of
them write to the same `settings`/`companies`/`tag_rules`/`incoming_documents` rows a production
workflow also touches** (i.e., confirm the test fixtures use isolated `instance` values in the
tenant-scoping scheme documented in Doc 1 §1b, rather than relying on luck). **What this makes
impossible:** a test run mutating production data because it happened to share a database with
production — today that is prevented only by the test workflows' own care in scoping their writes,
and whether they're properly instance-scoped was not directly verified by this audit (worth a
follow-up check before treating this as low-risk). **Risk:** low to investigate, but the underlying
fix (environment separation) is a real infra change — sequence as its own project, not a quick PR.
**Do not treat as blocking the backfill**, but resolve the "are test workflows instance-scoped"
question before the backfill if any test workflow's target instance is ambiguous.

## 2c. Target file/module structure

`[DRAFT — will be refined once the api/__init__.py seam proposal returns; shape below is the
committed direction, not final file boundaries]`

```
apps/indox/app/incoming_documents/
├── api/
│   ├── __init__.py            # Flask app factory + blueprint registration ONLY (no route bodies)
│   ├── documents.py           # documents CRUD: query, get, patch, history, upsert, month-index
│   ├── sync.py                # sync/status, sync/registry*, sync/items*, sync/runs, sync/engine,
│   │                          #   sync/reconcile, sync/origin — the sync control-plane surface
│   ├── config.py              # /config/settings, /config/companies, /config/tag_rules (generic
│   │                          #   table read/patch/add/delete)
│   ├── connections.py         # /connections, /connections/:id/locations
│   ├── extraction.py          # /extraction/* (thin route layer; heavy lifting stays in
│   │                          #   ../extraction.py, unchanged)
│   ├── instances.py           # /accounts, /account/*, /repos* (repo/instance provisioning)
│   ├── tests_.py              # /tests/* (E2E-suite runner surface — named tests_ to avoid
│   │                          #   shadowing the tests/ package)
│   └── dashboard.py           # /dashboard/stats, /auth/me
├── core/
│   ├── registry.py            # unchanged — repo registry (file-backed)
│   ├── sync_registry.py       # NEW — DB-backed sync-registry owner, same ownership discipline
│   │                          #   as registry.py (Target 3)
│   ├── identity.py            # NEW — the one SHORT_DOC_ID / doc-identity function (Target 2)
│   ├── pagination.py          # NEW — the one paged_select() accessor (Target 4)
│   ├── models.py / repo.py / errors.py / diff.py / provisioning.py / types.py   # unchanged
├── backends/
│   └── supabase.py, supabase_transport.py         # gsheet/* removed IF §2a confirms dead (Target 5)
├── extraction.py, poller.py, repo_factory.py, n8n_credentials.py, webapp_blueprint.py   # unchanged
├── kafka/                      # unchanged (already correctly Null-object-gated)
└── tests/                      # mirrors the new api/ split 1:1 (test_documents.py, test_sync.py, …)
```

Each `api/*.py` module imports only `core/*` + stdlib/framework — never another `api/*.py` module's
private helpers. That single rule is what makes the god-module's implicit coupling structurally
impossible rather than just reorganized-but-still-tangled.

## 2d. Ordered migration

`[DRAFT — sequencing is evidence-independent and can be finalized now; specific step contents for
steps 3-5 will tighten once the pending agent findings land]`

| # | Step | Buys | Risk | Verify | Reversible | Blocks the 13,760-doc backfill? |
|---|---|---|---|---|---|---|
| 1 | Add `core/pagination.py`'s `paged_select()`; migrate the ~18 unpaged-select call sites to it one PR at a time, starting with the ones already touching `public.incoming_documents` (the table the backfill writes) | Removes the single defect class most likely to make the backfill's own verification queries lie (a "did it all land" check that silently truncates is worse than no check) | Low — additive, old call sites keep working until migrated | Unit test with a fixture forcing `Content-Range` to a clamped value; assert `truncated=True` propagates | Yes (per call site) | **Yes — should run BEFORE the backfill**, so the backfill's own progress/verification reads are trustworthy |
| 2 | Gsheet backend liveness — CONFIRMED (§2a Target 5, two architecture docs + a live-registry read); proceed directly to deletion, no further confirmation step needed | Unblocks the delete decision immediately, no additional verification cost | None (already read-only confirmed) | N/A | N/A | No |
| 3 | Delete `backends/gsheet*.py` + `test_gsheet_repo.py`, narrow `RepoConfig.backend` to `Literal["supabase"]`, remove the gsheet option from `InstanceSwitcher.tsx` and `api.ts`'s type | Removes an architecturally-declared-dead, worse-behaved (silent column drop) code path from the surface a backfill could accidentally touch | Low — confirmed dead by two docs + a live-registry read, not inference | Full test suite green after `test_gsheet_repo.py` removal; `POST /repos {"backend":"gsheet"}` now 4xxs | No (delete), reversible via git | No |
| 4 | Build the `indoxUtilShortDocId01` n8n subworkflow with the canonical formula (`indoxV2Decide01.json:23-24`'s documented expression); migrate all 20 files that currently compute `SHORT_DOC_ID` inline — starting with the 2 confirmed-divergent ones (`indoxV2ActionsBS01.json`, `indoxGmailLinkDownloader01.json`) — to call it via `executeWorkflow`, one workflow at a time | Closes the 3-formula divergence — directly relevant to the backfill, since 13,760 documents computing identity via 3 different formulas is a duplicate-row risk at exactly backfill scale. No Python change needed — the computation is n8n-native today and should stay there (Target 2) | Medium — n8n workflow edits carry execution risk; do behind the existing test suites (`hooks/test.py`, `hooks/v2-decide-test.mjs`, `JQExV3*`/`syncV3*Test*` blueprints) before touching production workflows | Run the existing n8n E2E suites pre/post each workflow migration; diff `SHORT_DOC_ID` output on a sample of real rows before/after, prioritizing rows that hit the 2 divergent formulas | Workflow edits are reversible via n8n version history | **Yes — should run BEFORE the backfill**, this is the highest-leverage pre-backfill fix given the task's own framing of identity divergence as a duplicate-row risk |
| 5 | Split `api/__init__.py` per §2c | Makes future changes (including whatever the backfill needs) safe to review in isolation instead of against a 5,265-line diff surface | Low-medium — mechanical if done via move + import-fix, verified by the existing route test suite (`tests/`, 2,291 lines) hitting every route before/after | Full existing pytest suite + a route-inventory diff (same 55 routes present, same paths) pre/post | Yes (it's a pure refactor if tests hold) | No — cosmetic to the backfill, do any time |
| 6 | Sync registry ownership consolidation (`core/sync_registry.py`, Target 3) | Removes the "two registries" naming collision and the multi-handler-touches-one-row risk | Low — same pattern already proven by `core/registry.py` | Existing `/sync/registry*` route tests | Yes | No |
| 7 | **Quick-win dead-code removal** (can run anytime, any order, independently of the above): delete `POST/PUT /documents`, `/documents/upload` + repo-scoped alias (confirmed zero callers); delete `webapp/src/components/DataGrid.tsx` (confirmed zero imports); delete the stalled-refactor `blueprint/fixtures/` family (`field_defs.json`, `fixture_INVOICE.json`+`.oracle.md`, `REFACTOR-OUTLINE.md`, `ROUTERS-ARCHITECTURE.md`, `tools/shadow_diff.py`, `types/fixture_*.json`) | Shrinks the surface a new contributor (or the backfill work itself) has to read past; removes a broken tool (`shadow_diff.py` references paths that no longer exist) before someone tries to run it | Very low — every item has cross-agent-confirmed zero live references | `grep` for each symbol/path one more time immediately before deleting (belt-and-suspenders); full test suite green after | Yes (trivial revert) | No |
| 8 | Gsheet backend removal, Target 5, staged as its own 4-sub-step sequence (UI option → type narrowing → delete backend files+its test → delete webapp gsheet types) | Removes an architecturally-declared-dead code path the codebase's own docs already call unreachable, closing the gap between "documented dead" and "structurally impossible to select" | Low — confirmed dead by two docs + a live-registry read, not by inference | Full suite green after `test_gsheet_repo.py` removal; `POST /repos {"backend":"gsheet"}` now 4xxs | Reversible via git, but treat as a one-way architectural decision once merged | No |
| 9 | Sync registry v1/v3 engine consolidation, Target 6 | Removes the double-claim risk path entirely rather than guarding it | Medium — live sync logic; coordinate with the runtime-architecture companion document's target sync design | Confirm every registered pipe is on `engine:v3` first (`hooks/sync-state` output), then remove v1 code + the flip guard | Partially — safe once no pipe references v1 | **Do NOT schedule before/during the backfill** — do this either well before or well after, never concurrent with it |
| 10 | Test/E2E n8n environment separation, Target 7 — first confirm the 9 active test workflows are instance-scoped (read-only check), then execute whichever of (a)/(b) is feasible | Removes the "test mutates production data" risk class entirely, rather than trusting each test workflow's author got the scoping right | Low to investigate; medium to execute (infra change if pursuing a second n8n instance) | Confirm test workflows' `instance` values never collide with the production instance's; post-change, confirm test executions no longer appear in production-instance query results | Yes | Resolve the instance-scoping *question* before the backfill if ambiguous; the full separation project itself does not need to block it |

**Sequencing logic:** steps 1 and 4 are ordered before the backfill because they directly address the
two failure modes most dangerous *at 13,760-row scale* — a verification query that silently truncates,
and duplicate rows from divergent identity formulas. Steps 2/3/5/6 are architecture hygiene that
improve reviewability and reduce future defect surface but do not change backfill correctness, so they
can run in parallel with or after it.

---

*(End of current draft. Remaining fold-ins: exact seam boundaries for api/__init__.py split from the
audit agent; exact SHORT_DOC_ID formula count/text and Switch1/errorWorkflow findings from the n8n
agent; exact unused-route list from the caller-mapping agent; exact column-level data-layer findings;
exact gsheet-liveness verdict once directly confirmed.)*
