# INDOX — moving the whole backend into n8n workflows

**Owner's decision (2026-08-12):** the backend is n8n workflows; INDOX's own code is the frontend.
This document maps what that means concretely — every capability the Python service performs
today, which workflow owns it afterwards, and exactly what does not exist yet.

Measured, not assumed. Every count below came from the tree on 2026-08-12.

---

## 0. What "BFF" means, and what it is here

**BFF = Backend For Frontend** — a service that exists to serve exactly one UI: it talks to the
real backends, reshapes their data into what the screens need, and gives the frontend one origin
to call. It is meant to be a *thin* adapter.

In INDOX that name has stopped being accurate. `apps/indox/app/incoming_documents/` is a **Flask
service of ~15,750 lines exposing 74 HTTP routes**, and it is not adapting a backend — it *is* one:
it reads `public.incoming_documents` through PostgREST directly (22 call sites) and writes the
database directly (9 call sites), including a write to the documents table itself. It also serves
the built React SPA.

So "the BFF" today = **the React app's server + a second, independent data layer**. The second
half is what moves.

---

## 1. What actually drives INDOX right now

Three data layers exist in parallel. Nothing routes through a single door.

| # | Layer | Size | Reaches the DB how |
|---|---|---|---|
| 1 | n8n workflows with their own Postgres node | **33 of 71** indox workflows | direct SQL |
| 2 | `indoxApiSupabase01` (+ `indoxApiRouter01` dispatcher) | 34 + 5 nodes | direct SQL, called by `executeWorkflow` |
| 3 | The Flask service | 74 routes | PostgREST, direct |

The UI talks **only to layer 3**.

**The single-writer gateway does not exist.** [INDOX-UNIFIED-N8N-SPEC.md](INDOX-UNIFIED-N8N-SPEC.md)
§1 records that `indoxDataGateway01` "was invented by an agent lane, rejected by the owner as 'not
part of the existing architecture', never executed once, and disarmed on 2026-08-07". The file is
in `data/_attic_agent_drafts/`, not in the blueprint.

**Dead tooling to delete:** `scripts/refactor/gen-gateway-trigger-schema.py` calls itself "the
documented way to add a column" and regenerates
`apps/indox/blueprint/n8n/indoxDataGateway01.json` — **a path that does not exist**. It is a
generator for a phantom, and it is cited as authoritative in `indox-column-consolidation.sql` and
`EXTRACTION-REFACTOR-PLAN.md`.

**Schema is the one healthy part.** `apps/indox/blueprint/fixtures/schema.sql` is a real single
owner: idempotent DDL, applied everywhere, 112 columns declared vs 108 live. It stays exactly as
it is. What drifted is the Flask service's *hand-maintained copy* of the column list
(`repos.json`, 47 of 108) — which disappears with the service.

---

## 2. What is already HTTP-callable in n8n

For n8n to be the backend, a workflow must answer HTTP. Today 16 do:

| Workflow | Webhook path | Covers |
|---|---|---|
| `indoxSettings01` | `settings`, `all_settings`, `company`, `query`, `queries`, `settings/invalidate-cache` | **config: settings, companies, extraction queries** |
| `SyncApi0000000001` | `indox-manage` | sync management (partial) |
| `indoxV2ActionRouter01` | `indox-action-router` | state-machine actions |
| `indoxHealth00001` | `trigger-indox-health` | health |
| `indoxV2Driver01` | `incoming-documents-016/017` | pipeline drive |
| `indoxV2ExtractInvoiceGemini01`, `indoxV2ExtractBalanceSheet01` | `invoice_extractor`, `bs_ex_2_dev` | extraction legs |
| `JQExV3Run{Base,Inv,Ship,BS}` | `jqexv3-run-*` | per-type extraction |
| 5 × `*Test01` | `*-e2e-lane` | test lanes |

**The data layer is the gap:** `indoxApiSupabase01` and `indoxApiRouter01` — the workflows that
already own document reads/writes — have **`executeWorkflowTrigger` only**. They are internal.
Nothing outside n8n can call them.

---

## 3. The target backend — every workflow, and its status

**Legend:** ✅ exists and is HTTP-callable · 🟡 exists but internal-only or partial · ❌ missing

### 3.1 Data plane — the core gap

| Target workflow | Owns | Replaces (Flask routes) | Status |
|---|---|---|---|
| `indoxApiDocs01` | document read: query/filter/sort/page, get one, history | `POST /repos/<r>/documents/query`, `GET …/<id>`, `GET …/<id>/history`, `GET /repos/<r>/stats` | 🟡 logic in `indoxApiSupabase01`, **no webhook** |
| `indoxApiDocsWrite01` | document write: patch, upsert, status transition | `PATCH /repos/<r>/documents/<id>`, `PUT /repos/<r>/documents` | 🟡 same |
| `indoxApiMonthIndex01` | the month aggregate behind the date filter | `POST /repos/<r>/documents/month-index` | ❌ **missing** |
| `indoxApiDashboard01` | the dashboard aggregate + its maintained read model | `GET /dashboard/stats` | ❌ **missing** (see §4) |

### 3.2 Config plane — nearly done

| Target workflow | Owns | Replaces | Status |
|---|---|---|---|
| `indoxSettings01` | settings, companies, tag_rules, extraction queries | `GET/PUT /config/*`, `GET /extraction/queries` | ✅ **already HTTP** |
| `indoxApiConfigWrite01` | generic config row add/patch/delete | `POST/PATCH/DELETE /config/<table>[/<row>]` | 🟡 partial in `indoxSettings01` |

### 3.3 Sync plane

| Target workflow | Owns | Replaces | Status |
|---|---|---|---|
| `SyncApi0000000001` | registry CRUD, run, status, inventory | `GET/POST/PATCH/DELETE /sync/registry*`, `/sync/run`, `/sync/status` | ✅ HTTP, 🟡 partial coverage |
| `syncLedgerApi01` | ledger, runs, reconcile, origin | `GET /sync/runs`, `/sync/reconcile`, `/sync/origin` | 🟡 internal-only |
| `indoxApiSyncItems01` | item triage: list, move, fallback-type | `GET /sync/items`, `POST /sync/items/move`, `…/apply-fallback-type` | ❌ **missing** |

### 3.4 Instances / connections

| Target workflow | Owns | Replaces | Status |
|---|---|---|---|
| `indoxApiInstances01` | instance list/add/remove/select, active scope | `GET /accounts`, `POST /account/*`, `/repos` CRUD | ❌ **missing** |
| `indoxApiConnections01` | connection list + locations | `GET/POST /connections*` | ❌ **missing** (the `connections` app owns the credentials themselves) |

### 3.5 Test / QA plane

| Target workflow | Owns | Replaces | Status |
|---|---|---|---|
| `indoxV2*Test01`, `syncV3*Test01` | the E2E lanes | `POST /tests/run`, `GET /tests/suites`, `/tests/run/<id>` | ✅ lanes exist, ❌ **no list/status API** |

---

## 4. What should NOT move — and why saying so matters

A migration that pretends everything fits in n8n will stall on these four. Each is a deliberate
exception, not an omission.

1. **Serving the SPA.** Static assets and the `/a/incoming/` mount stay in a web server. n8n is not
   an asset host.
2. **Auth identity (`GET /auth/me`).** It reads Authentik's `X-authentik-*` forward-auth headers,
   which only exist at the Traefik edge. Moving it into n8n would mean re-implementing trust.
3. **Binary streaming** — thumbnails, document files, OCR token overlays, `draw` renders
   (`POST /documents/thumbnail`, `GET /documents/<id>/file|tokens|draw`). n8n passes binaries
   through its execution store; at page-of-thumbnails volume that is the wrong shape.
   **apitools already serves these** — the frontend should call apitools directly.
4. **The extraction workbench** (20 routes: dataset, run, compare, draw, rerun, upload). This is a
   *developer* tool for tuning OCR, not business backend. It should be recognised as such and
   split out, not migrated.

**Everything else — all document reads and writes, the dashboard, sync, config, instances — moves.**

---

## 5. What exactly is missing

Ordered by what blocks the most.

| # | Missing piece | Why it blocks | Size |
|---|---|---|---|
| 1 | **An HTTP front for the data routers.** `indoxApiSupabase01`/`indoxApiRouter01` are `executeWorkflow`-only. | Nothing outside n8n can read or write a document. This is *the* blocker — every other item assumes it. | 1 webhook workflow dispatching to the existing router |
| 2 | **The dashboard aggregate.** Today it is Python: a maintained read model in `indox_dashboard_stats`, a DB trigger flipping `dirty`, a background refresher, plus live windowed computation. | The main screen. | The heaviest single item — the trigger + table already exist, the *computation* must be ported |
| 3 | **Month index.** A full paged read of one date column, bucketed. | The documents table's date filter. | Small, but must page correctly (the PostgREST 1000-row cap already bit this once) |
| 4 | **Sync item triage** (list/move/apply-fallback-type). | The סנכרון screen. | Medium; one of these already writes `incoming_documents` directly |
| 5 | **Instances/accounts API.** | Multi-instance switching; the chip on every screen. | Medium |
| 6 | **Tests list/status API.** | The בדיקות screen. | Small — the lanes exist, only enumeration and status are missing |
| 7 | **Connections API.** | The connections screen. | Small — mostly proxying the `connections` app |
| 8 | **A single-writer invariant with a gate that can pass.** The spec's own note: the invariant "may still be worth having — against `indoxApiSupabase01`, the REAL writer, under a new number." | Without it, 33 workflows keep writing directly and the split rots again. | Lint + one gate |

### Cleanup that comes free
- delete `scripts/refactor/gen-gateway-trigger-schema.py` and the phantom it regenerates
- delete `repos.json`'s hand-maintained column list (the drift disappears with the service)
- retire `apps/indox/app/incoming_documents/` down to: static SPA serving + `/auth/me`
- fold the 33 workflows' direct Postgres nodes into the data router, one at a time, behind the gate

---

## 6. Sequencing

Each step leaves the product working; nothing is a flag-day.

1. **Webhook front for the data router** (§5.1) — nothing changes for users; the capability exists.
2. **Frontend reads through it**, one screen at a time, starting with the documents table. The
   Flask route stays until its screen is switched, so a bad port is one revert.
3. **Dashboard** (§5.2) — the big one, done alone.
4. **Sync, instances, tests, connections** (§5.4–7).
5. **Delete the Flask data layer**; keep SPA serving + `/auth/me`. Point thumbnails/files at
   apitools; split out the extraction workbench.
6. **Re-arm the single-writer gate** against `indoxApiSupabase01` and migrate the 33 direct
   writers behind it.

**Definition of done:** the Flask service contains zero `transport.*` calls, and
`bbox indox ui-qa` (the 73-check UI harness) still passes against the n8n-backed API — the same
assertions, a different backend, which is what proves the port rather than declares it.
