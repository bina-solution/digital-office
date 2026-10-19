# bbox / deployment-hacohen — architecture map (domains · dependency tree · INDOX inner layers · consolidation)

Living map of the whole deployment, with deep focus on INDOX. Companion to the API-routing rule:
**nothing talks to a datastore directly outside the API layer** (see §4).

---

## 1. Domains (subsystems)

| Domain | Purpose | Containers | Entry / route |
|---|---|---|---|
| **Edge** | reverse proxy, TLS, ForwardAuth | `traefik` | `*.${DOMAIN}` :80/:443 |
| **SSO** | identity, gates apps | `authentik-{server,worker,postgres,bootstrap}` | `auth.*` |
| **n8n** | workflow engine (queue mode) | `n8n`, `n8n-postgres`, `n8n-task-runners`, `n8n-worker-{1,2}` | `n8n.*` (+local :5678) |
| **INDOX** | doc ingestion→extract→complete (see §3) | *(runs inside n8n)* | webhooks `/indox-api`, `/indox-manage` |
| **Supabase** | Postgres+REST+storage = INDOX data backend | `supabase-{db,meta,rest,kong,storage,studio}` | `supabase-studio.dev` |
| **Redis** | cache, queue, locks | `redis`, `redisinsight` | `redisinsight.*` |
| **apitools** | Hebrew OCR / field extraction (in-tree) | `apitools` | `apitools.*` :8080 |
| **inbox** | Gmail bridge (app-pw, no OAuth quota) | `inbox` | internal :8970 |
| **browser42** | stealth Chromium + Playwright MCP | `browser42-{browser,mcp,caddy}` | `browser42.*` |
| **glitchtip** | error tracking (Sentry-compat) | `glitchtip`, `glitchtip-{postgres,worker,valkey}` | `glitchtip.*` |
| **observability** | timeline / host metrics | `any-concurrency`, `machine` | `any-concurrency.*`, `machine.*` |
| **ops UIs** | container mgmt / dashboard | `portainer`, `homepage` | `portainer.*`, `home.*` |
| **whatsapp** | bot I/O | `chat` | `chat.*` |
| **dev-only** | agent + rewrites + tests | `openhands*`, `incoming-documents`+`redpanda`, `feature-validation*` | `*.dev.*` |

Naming: `<service>-${DEPLOYMENT_NAME}`. Routes: prod `svc.${DOMAIN}` · dev `svc.dev.${DOMAIN}` · local `svc.localhost`.

---

## 2. Infra dependency tree

```
TRAEFIK (edge, TLS, ForwardAuth)
├─ authentik-server/worker ─→ authentik-postgres, redis
├─ redis ─→ redisinsight
├─ n8n (main) ─→ n8n-postgres, redis(queue), n8n-task-runners, n8n-worker-1/2
│      └─(uses)→ supabase-db, apitools:8080, mailapi:8970, Google Drive/Sheets (OAuth)
├─ supabase-db ─→ supabase-{meta,rest,storage} ─→ supabase-kong
├─ apitools         (needs GEMINI key)
├─ inbox       (needs GMAIL_IMAP_USER/APP_PW)
├─ browser42-browser ─→ browser42-mcp ─→ browser42-caddy
├─ glitchtip ─→ glitchtip-postgres, glitchtip-valkey, glitchtip-migrate
├─ any-concurrency ─(reads)→ n8n-postgres, redis, docker.sock
├─ machine / portainer / homepage ─(read)→ docker.sock
└─ (dev) openhands ─→ llm-gateway ─→ dispatcher ; incoming-documents ─→ redpanda

networks: traefik-network (public hub) · per-domain internal nets
  (authentik-internal · n8n-internal · supabase-net · glitchtip-internal · browser42-internal)
critical data deps: n8n-postgres(workflow state) · supabase-db(INDOX tables) · redis(locks/queue)
```

---

## 3. INDOX inner architecture (the moving parts)

Three layers, all orchestrated inside n8n; data in Supabase. Config auto-discovered from `settings.sync_registry`.

```
                         ┌──────────────────────── CONFIG (supabase) ───────────────────────┐
                         │ settings(sync_registry, q_* queries, kw arrays, folder/label roles,│
                         │ toggles) · companies · tag_rules · trusted_suppliers              │
                         └───────────────────────────────────────────────────────────────────┘
   sources                         ▲ read via API (TABLE_GET)            ▲
   ┌───────────────┐      LAYER 1 — SYNC (register source → row)        │
   │ Drive folders │  SyncScanner00001 (sched) → SyncScanUnit0001 (LIST→CLAIM→dispatch, mode=each)
   │ Gmail labels  │     └─ processors: SyncProcGDoc / SyncProcBS / 9NWA(gmail-doc) /
   └──────┬────────┘                    sEcV(gmail-bs) / LDrY(gmail-link)
          │                              → Process Document (apitools OCR) → Batch Upsert(row, IN_PROGRESS)
          ▼
   incoming_documents ──── LAYER 2 — MAIN state machine ──────────────────────────────────
   (supabase table)   indoxApiSupabase01 "Poll Line Changes"(2min) + table trigger
                      → Incoming Documents 0.1.7 (sv5xxRBVGxvV0kXx): "Determine Action" self-loop
                        one ACTION/iteration → update row → re-enter, until STATUS=COMPLETED
                        gdoc path:  figure_company→name→short_id→update_name→find_link→
                                    check_from_office→date/purchase/shipment→ (AI extract: Gemini) →mark_completed
                        bs path:    extract_balance_sheet(Gemini)→link_documents(BS lines↔invoices)→mark_completed
                        dedup: ID / HASH / (COMPANY_ID,SHORT_DOC_ID) → STATUS=DOUBLE
                      extraction: apitools OCR + Gemini query sub-WFs (date/invoice_id/purchase/shipment/amount/type)

   LAYER 3 — API / MANAGEMENT (the ONLY thing that touches a backend) — see §4
```

Tables: `incoming_documents`(ID + ~80 TEXT cols, status/type/company/extraction flags), `settings`(key/value),
`companies`(tenant), `tag_rules`(KEY+EVENT+label_id gmail labels), `trusted_suppliers`, `app_logs`.

Adjacent: **Mail Label Engine** (`mailLabelEngine01`, evaluates `tag_rules` → applies DOC/BS/LINK sync labels);
**Google-Workspace agent** (Gemini chat + Gmail/Drive/Sheets MCP, shares OAuth).

---

## 4. The API layer (canonical data access — route EVERYTHING here)

**Rule: no workflow may hit Postgres / Sheets / Drive / Gmail directly. It calls a router.**

### DATA — `indoxApiRouter01`  (dispatch on `INLINE_ACTION`)
- backend toggle: redis `n8n.indox.data_backend` (`supabase`*|`sheets`) → `Backend Switch`
  - supabase backend = **`indoxApiSupabase01`** (cred `INDOX Supabase Postgres` yY8FYvp6Kz86pt2t)
  - sheets backend   = `indoxApiSheets01` (cred Google Sheets e2knIZpw8YF0QBAB)
- management actions `RESET|STATUS|INJECT` → `SyncApi0000000001`
- **contract (identical both backends):**

| INLINE_ACTION | params | does |
|---|---|---|
| `UPSERT` | row fields | upsert `incoming_documents` by ID (match-index + hash dedup) |
| `GET` | `ids` \| `filter{col=val\|col:{op,value}}` | read rows |
| `GET_ALL` | — | all rows (excl `__bootstrap__`) |
| `DELETE` | `ids` | delete rows |
| `TABLE_GET` | `table`, `filter` | read `settings\|companies\|tag_rules\|trusted_suppliers` |
| `TABLE_UPSERT` | `table`, fields | upsert (settings conflict=`key`; others **insert-only** ⚠) |

### DRIVE — `driveApi01`  `{op, params}` : `download|list|upload|move|update|delete|createFromText` (cred KirWFwoFdEFmnN0R)
### GMAIL — `gmailApiRouter01` `{op, params}` → `gmailApiImap01`* | `gmailApiOauth01` (code-const toggle `BACKEND='imap'`)

**Setup/config seeding therefore routes as:** `executeWorkflow(indoxApiRouter01, {INLINE_ACTION:'TABLE_UPSERT', table:'settings', key, value})`
per row, and `TABLE_GET` to read. (tag_rules needs a conflict-update path — see §5 gap.)

---

## 5. Consolidation assessment

| Domain | State |
|---|---|
| Edge + SSO | ✅ unified (one Traefik + Authentik ForwardAuth) |
| Drive ops | ✅ 100% via `driveApi01` |
| Gmail ops | ✅ 100% via `gmailApiRouter01` (imap) |
| **DATA ops** | ⚠️ ~95% of MAIN pipeline routed; **bypasses remain** (below) |
| Sync state | ⚠️ dual source-of-truth (Drive folders/Gmail labels **and** the table) — reset must touch both |
| Reset paths | ⚠️ being consolidated → `INDOX Reset + Setup` (IndoxResetFull01) calls Drive/Gmail reset sub-WFs |
| Backends | ⚠️ supabase live, **sheets legacy** still wired (dormant) |
| Legacy WFs | ⚠️ archived versions present (0.1.4, BS/GDoc V2 runners) — prune candidates |

### Direct-DB **bypasses** to migrate onto the API (audit):
- **postgres bypasses (non-router):** `pqD1bjLaiTcHRyCj` (cache table, 16 nodes — biggest), `SyncSource000001`, `SyncScanner00001`, `indoxSettings01`(Settings), `IndoxBSSyncV2`, `IndoxGDocSyncV2`, `errorHandler01`(Error Handler), `IndoxResetGml001`/`IndoxResetDrv001` (read `settings`/`tag_rules` directly), **`INDOX Reset + Setup` config-seed (NEW — must move to API)**.
- **MCP servers** (`gDriveMcpAgent01` drive, `gSheetMcpAgent01` sheets, `gDriveMcpAgent01`) — intentionally standalone (agent tools), lower priority.
- **sheets bypasses:** mostly dormant sheets-mode branches in main/upsert/get + loggers.

### Gaps blocking "route ALL setup through the API":
1. `TABLE_UPSERT` is **insert-only** for non-settings tables → re-seeding `tag_rules` won't update. Fix: extend supabase backend `Build Table Upsert` to add `tag_rules` ON CONFLICT (id), or seed tag_rules only-when-empty.
2. Schema/table **DDL** is infrastructure (lives in `vg3yeWT8iJHQh0Nq` Supabase Setup) — keep there, but it currently **omits `tag_rules`** (DDL was a stale loose `scripts/_tag_rules.sql`). Fold current tag_rules DDL into Supabase Setup.

---

## 6. Reset / Setup / Inject (target consolidated shape)

- **`INDOX Reset + Setup`** (IndoxResetFull01): ensure schema (call Supabase Setup) → **seed config via API** (TABLE_UPSERT) → clear table → Drive/Gmail reset sub-WFs → clear redis locks. = clear-to-initial **+** ensure-config.
- **`INDOX Inject Demo Company`** (to build): companies + 30×5 docs (gmail-doc/bs/link + drive-gdoc/bs) from the git-tracked **`production/n8n/demo-docs/`** set (90 invoice + 15 shipment + 60 BS, 10MB).
- **onboarding**: after n8n push → trigger Reset+Setup → prompt "inject demo company?" → Inject → ends onboarded + processing.
- host scripts (`highload-inject*`, `_inject_gmail_direct`, `indox-*-company-state`, `automations-reset`) → thin wrappers that call these WFs via `/indox-manage`.
