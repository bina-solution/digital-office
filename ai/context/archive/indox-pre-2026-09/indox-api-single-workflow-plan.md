# INDOX — the final backend plan: one API workflow, zero backend codebase

**Owner's decisions (2026-08-12).**
1. The backend is n8n. INDOX's own code is the frontend.
2. **One fat `indoxApi01`** owns everything — table API, sync, settings, ledger. No router hop.
3. The word *supabase* leaves the architecture. It named a finished migration away from Google
   Sheets. What is left is a database and an API.
4. **No cross-app coupling.** INDOX does not read mail's tables.

Every number below is measured from the tree on 2026-08-12.

---

## PART A — WHERE THINGS STAND

### A.1 n8n: 71 workflows · 2,313 nodes · 177 Postgres nodes

| Where the Postgres nodes are | Nodes | Verdict |
|---|---|---|
| Test / fixture / reset workflows | **~105** | **legitimate — stays.** Tests assert DB state directly; `syncV3SourcesTest01` alone holds 46 |
| API workflows | 29 | `syncLedgerApi01` 14 · `indoxApiSupabase01` 13 · `SyncApi` 2 → merge |
| Production pipeline workflows | ~43 | **the real migration surface** — route behind the single writer |

### A.2 The Python service: 13,377 lines (excluding tests)

| Module | Lines | Fate |
|---|---|---|
| `api/__init__.py` | 7,031 | → `indoxApi01` |
| `extraction.py` | 1,416 | **not backend** — a developer OCR workbench; split out, do not migrate |
| `backends/supabase_transport.py` | 931 | delete with the data layer |
| `backends/gsheet.py` + `gsheet_transport.py` | **933** | **DEAD — delete now** |
| `backends/supabase.py` | 320 | delete |
| `core/*` (models, registry, diff, repo, types, month_key) | ~1,120 | logic becomes ops |
| `kafka/*` | **370** | **DEAD — delete now** (compose: "There is no message broker in this platform") |
| `poller.py` | **245** | **DEAD — delete now** ("disabled — n8n owns the pipeline") |
| `repo_factory.py`, `n8n_credentials.py` | 382 | delete / fold |

Frontend: **12,293 lines** of TS/TSX — kept. That is the product.

### A.3 The three layers that exist today

1. **~43 production workflow Postgres nodes** — direct SQL
2. **`indoxApiSupabase01` + `indoxApiRouter01`** — the intended data layer, `executeWorkflow`-only
3. **The Flask service** — 74 routes, 22 direct DB reads, 9 direct writes

The UI talks only to layer 3. There is no single door. `indoxApiRouter01` is 5 nodes whose entire
job is one `If Management` boolean — and it is **already bypassed**: 20 workflows call it, 7 call
`indoxApiSupabase01` directly.

---

## PART B — THE TARGET

### B.1 `indoxApi01` — what merges

| Merging in | Nodes | Brings |
|---|---|---|
| `indoxApiSupabase01` | 34 | table API, match-index/ID resolution, changed-doc poller, stalled-row terminaliser |
| `indoxSettings01` | 69 | settings · companies · queries, already HTTP, + its config cache |
| `SyncApi0000000001` | 26 | sync management + **registry** |
| `syncLedgerApi01` | 37 | cursors, claims, gates, quarantine, 5-min reaper |
| `indoxApiRouter01` | — | **deleted** |
| **`indoxApi01`** | **~171** | one door |

171 nodes is workable here — `syncV3SourcesTest01` is 190, `indoxV2Driver01` is 137.

### B.2 Shape

```
 ENTRY ─┬─ When Called (executeWorkflowTrigger) ← 27 internal callers, contract UNCHANGED
        ├─ HTTP In     (webhook /indox-api)     ← the frontend
        └─ Schedules   (keepalive · changed-doc · ledger reaper)
                 └── Normalize {op|INLINE_ACTION, table, filter, values, instance}
                                     │
                                ┌────▼────┐  ONE switch
                                │ Action  │
                                └────┬────┘
  ┌─────────┬─────────┬─────────┬───┴─────┬─────────┬─────────┐
  ▼         ▼         ▼         ▼         ▼         ▼         ▼
DOCUMENTS TABLES    QUERY   AGGREGATES  SYNC     LEDGER    CONFIG
                                     │
                                ┌────▼────┐
                                │ Respond │  {ok, rows, count, error}
                                └─────────┘
```

**Two entry points, one body** is what stops this becoming two implementations again: internal
callers and the browser converge on the same Normalize step and the same switch.

### B.3 The op catalogue

**Existing (unchanged contract — all 27 callers keep working):**
`UPSERT` · `GET` · `GET_ALL` · `DELETE` · `TABLE_GET` · `TABLE_UPSERT` · `DELIVER` · `MERGE`
(`op` accepted as a synonym for `INLINE_ACTION`.)

**New — the actual work, 7 ops covering ~12 routes:**

| Op | Replaces | Why it is not a plain table read |
|---|---|---|
| `QUERY` | `POST …/documents/query` | filter + search + sort + page + exact count; **must page past PostgREST's silent 1000-row cap** (that cap produced a 6–9× undercount once) |
| `MONTH_INDEX` | `POST …/documents/month-index` | paged read of one date column, bucketed; splits empty vs unparseable |
| `DASHBOARD` | `GET /dashboard/stats` | the heaviest port — §B.5 |
| `STATS` | `GET /repos/<r>/stats` | counts + columns + last event |
| `HISTORY` | `GET …/documents/<id>/history` | per-document trail |
| `SYNC_ITEMS` | `/sync/items`, `…/move`, `…/apply-fallback-type` | triage; one of these currently writes `incoming_documents` **from Flask** |
| `TESTS` | `/tests/suites`, `/tests/run*` | enumerate + status; the lanes already exist as webhooks |

**Absorbed with no new logic (~30 routes):** all `/config/*`, `/repos*`, `/accounts`, `/account/*`,
`/sync/registry*` → `TABLE_GET`/`TABLE_UPSERT`/`TABLE_DELETE`; document get/patch/upsert →
`GET`/`UPSERT`.

### B.4 Gmail labelling — decoupled, no shared table

**Rejected:** indox reading `tag_rules` (mail's table). That is the coupling.

**Target:**
- INDOX settings hold plain label strings — `label_invoice`, `label_shipment`, `label_bs_saved`.
  Ordinary settings rows, edited on the INDOX settings screen, served by `TABLE_GET`.
- Applying a label is **one call to mail-api**: `labels.add` with `createIfMissing: true`. Mail
  owns creation, naming, ids and caching. INDOX never learns a label id.

**What is missing:** mail-api has `labels_add` and `labels_create` as *separate* ops.
`labels_create` is already idempotent (it swallows "already exists"), so this is a **small
mail-api addition** — `createIfMissing` on `labels_add`, which calls create then add — not a new
subsystem.

**Then delete from INDOX:** the `Tag Rules Req (Gmail Labels)` / `Get Tag Rules` nodes in
`indoxV2ActionsGlobal01`, the `tag_rules` reads in `indoxSettings01`/`indoxApiSupabase01`, the
`GET /config/tag_rules` route, and the tag-rules tab in the settings UI.

### B.5 The dashboard — the one genuinely hard port

Today: a maintained read model in `indox_dashboard_stats`, a DB trigger flipping `dirty`, a
**background refresher thread**, live computation for narrow windows, plus a short cache. That
shape exists because naive per-request aggregation was unbounded at 180,000 rows.

n8n has no background thread. **Recommendation: a `scheduleTrigger` recompute** — the pattern
`indoxApiSupabase01` already runs for its keepalive and changed-doc polling. `DASHBOARD` then reads
the table; windowed views compute live. (Alternative: a Postgres materialized view — fewer moving
parts, but the status grouping and extraction scoring must be re-expressed in SQL.)

### B.6 What deliberately does NOT move (~32 routes)

| Stays | Why |
|---|---|
| SPA serving | n8n is not an asset host |
| `GET /auth/me` | reads Authentik `X-authentik-*`, which exist only at the Traefik edge |
| thumbnails, files, OCR tokens, `draw` | binary streaming through n8n's execution store is the wrong shape at page-of-thumbnails volume — **apitools already serves these; the frontend should call it directly** |
| the 20 `/extraction/*` routes | a developer OCR-tuning workbench, not business backend |

---

## PART C — EXECUTION

### Step 0 — delete the dead code (~1,548 lines) · *independent of everything else*
`gsheet.py` + `gsheet_transport.py` (933) · `kafka/*` (370) · `poller.py` (245).

⚠️ **Not free-standing.** They are imported by `api/__init__.py` and `core/provisioning.py`, so
this also removes: the `backend == "gsheet"` branches, `KafkaConfig` from `models.py`, the
`/repos/<r>/kafka/tail` route, and the `start_polling` call. That is surgery inside the file that
gets deleted at the end — worth doing anyway, because it shrinks the port surface and removes two
dead concepts (a second repo backend; a message broker) from every later decision.

### Step 1 — rename + absorb
`indoxApiSupabase01` → `indoxApi01`; fold in the router's management branch. The 7 direct callers
are done at this step.

### Step 2 — repoint the 20 router callers
`indoxApiRouter01` becomes a 2-node shim, then is deleted.

### Step 3 — absorb settings, sync, ledger
Keep their existing webhook paths alive so nothing outside notices.

### Step 4 — add the `/indox-api` webhook entry
No user-visible change; the capability now exists.

### Step 5 — decouple Gmail labelling
mail-api `createIfMissing`; INDOX settings label strings; delete the `tag_rules` reads.

### Step 6 — move the frontend, one screen at a time
Documents table first. Each Flask route stays until its screen is switched, so a bad port is one
revert.

### Step 7 — dashboard (§B.5), alone

### Step 8 — delete the backend codebase
Criteria, all three:
1. **zero `transport.*` calls** remain (today: 22 reads + 9 writes)
2. **`bbox indox ui-qa` passes** against the n8n-backed API — the same 73 UI assertions, a
   different backend. That proves the port instead of declaring it.
3. what remains is only static SPA serving + `GET /auth/me`

**Result: ~13,377 lines of Python deleted. 12,293 lines of frontend kept.**

### Step 9 — re-arm the single-writer gate
Against `indoxApi01`, and migrate the ~43 production pipeline Postgres nodes behind it. Test
workflows keep theirs.

### Deleted along the way
`indoxApiRouter01` · `repos.json`'s hand-maintained column list (drifted to **47 of 108**; the real
schema `apps/indox/blueprint/fixtures/schema.sql` is healthy at 112 and stays) ·
`scripts/refactor/gen-gateway-trigger-schema.py`, which regenerates
`apps/indox/blueprint/n8n/indoxDataGateway01.json` — **a file that does not exist** (that gateway
was rejected by the owner and never ran) · the indox tag-rules UI · the word *supabase*.

---

## PART D — WHAT THIS PLAN DOES NOT PRETEND

- **n8n webhook latency is not free.** The dashboard polls every 15s and the grid pages
  interactively. The §B.5 read model is what makes that acceptable; without it, this trade is
  worse than today.
- **`executeWorkflowTrigger` silently drops undeclared fields** — exactly how `THUMBNAIL`,
  `CONNECTION`, `NEXT_RETRY_AT` and `RETRY_COUNT` were lost before (G39 exists for it). Every
  field the fat workflow accepts must be declared on its trigger schema.
- **171 nodes in one workflow** is a real editor and blast-radius cost, and it inherits **three
  schedule triggers** that must not interfere with request handling. Accepted deliberately in
  exchange for one door; the 73-check harness is the net.
