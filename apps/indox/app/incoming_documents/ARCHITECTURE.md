# Incoming Documents — System Architecture (Old vs New)

> Companion to [plan.txt](plan.txt) · [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) · [TESTING-STRATEGY.md](TESTING-STRATEGY.md).
>
> Visual side-by-side of the **current n8n-only system** and the **target Python+Kafka+multi-backend system**.

---

## 1. OLD system (today, in production)

```mermaid
flowchart LR
    subgraph Trigger["Triggers"]
        GST["Google Sheets Trigger<br/>(poll מסמכים נכנסים)"]
        SCH["Schedule Trigger<br/>(periodic sweep)"]
        WH06["Webhook (0.1.6 only)"]
    end

    subgraph Orch["n8n Orchestrator"]
        ID016["Incoming Documents 0.1.6<br/>xWM5NQjGxl0qAhHg<br/>213 nodes · ~32 batch-upsert sites"]
    end

    subgraph Helpers["Helper subworkflows (n8n)"]
        SETT["Settings"]
        FT["Figure Document Type"]
        FC["Figure Document COMPANY_ID"]
        Q["Query SHIPMENT_ID / PURCHASE_ID /<br/>DOCUMENT_DATE / TOTAL_AMOUNT /<br/>INVOICE_ID / IS_BALANCE_SHEET"]
        SF["Search File / Warehouse Scans"]
        BSE["Balance Sheet Extractor v2"]
        INV["Invoice Extractor (Gemini)"]
        UDT["Upload Doc To API TOOLS"]
    end

    subgraph DataIO["Data-side workflows (BEING REPLACED)"]
        BU["Batch Upsert<br/>indoxDocBatchUpsert01<br/>(diff + GSheet batchUpdate/append)"]
        GET["Get Incoming Document<br/>indoxDocGet01<br/>(single / by_ids / filter / all)"]
    end

    subgraph LockSvc["Locking (stays)"]
        PL["process_lock<br/>processLock01"]
        REDIS[("Redis")]
    end

    subgraph External["External services"]
        GSHEET[("Google Sheet<br/>AutomationValues<br/>מסמכים נכנסים<br/>52 cols × 39,582 rows")]
        APITOOLS[("apitools<br/>/documentOcr<br/>/documentJsonQuery")]
        GEMINI[("Gemini / Vision")]
    end

    GST --> ID016
    SCH --> ID016
    WH06 --> ID016

    ID016 --> SETT
    ID016 --> FT
    ID016 --> FC
    ID016 --> SF
    ID016 --> BSE
    ID016 --> INV
    ID016 -- "~32 call sites" --> BU
    ID016 -- "Get Line By ID /<br/>Execute Workflow1" --> GET

    FT --> Q
    FT --> UDT
    FC --> UDT
    Q --> UDT
    UDT --> APITOOLS
    BSE --> APITOOLS
    INV --> GEMINI

    BU --> PL
    BU --> GSHEET
    GET --> GSHEET
    PL --> REDIS

    classDef replace fill:#fde2e2,stroke:#c0392b,stroke-width:2px,color:#000
    classDef stay fill:#e6f4ea,stroke:#2e7d32,color:#000
    classDef ext fill:#eef2ff,stroke:#3949ab,color:#000
    class BU,GET,GST replace
    class PL,REDIS,SETT,FT,FC,Q,SF,BSE,INV,UDT stay
    class GSHEET,APITOOLS,GEMINI ext
```

**Legend (old):**
- 🟥 red = removed / replaced in the new system (`Batch Upsert`, `Get Incoming Document`, GSheet trigger).
- 🟩 green = stays exactly as-is (`process_lock`, all helper/extraction subworkflows).
- 🟦 blue = external services.

**Pain points of the old system:**
1. `Batch Upsert` and `Get Incoming Document` are bound to a **single** GSheet — no abstraction, no Supabase path.
2. The GSheet trigger does row-level polling (high latency, sheet-quota pressure, cannot replay).
3. ~32 call sites × diff-engine logic embedded in n8n Code nodes → hard to test, hard to evolve.
4. No durable event log of "what was processed when".

---

## 2. NEW system (target, after phase 6)

```mermaid
flowchart LR
    subgraph Producers["Event producers"]
        PUB["External producer<br/>(scripts / other services)"]
        BACKFILL["Migration / backfill CLI"]
    end

    subgraph Bus["Message bus"]
        RP[("Redpanda<br/>${KAFKA_TOPIC_PREFIX}.&lt;repo&gt;<br/>3 partitions · 7d retention")]
    end

    subgraph WorkerSvc["apitools-incoming-docs-worker (NEW container)"]
        KCON["Kafka Consumer<br/>group: incoming-documents-orchestrator"]
    end

    subgraph N8N["n8n (slimmer)"]
        WH06N["Incoming Documents 0.1.6<br/>(Webhook trigger only)"]
        BUW["Batch Upsert wrapper (NEW)<br/>= acquire process_lock →<br/>HTTP PUT Python API →<br/>release process_lock"]
        GETW["Get Incoming Document wrapper (NEW)<br/>= HTTP POST Python API"]
        PL["process_lock (unchanged)"]
        SETT["Settings, Figure*, Query*,<br/>Search File, Extractors<br/>(unchanged)"]
        REDIS[("Redis")]
    end

    subgraph Apitools["apitools (Flask blueprint /incomingDocuments — NEW)"]
        REPOS["RepoRegistry<br/>.storage/incoming_documents/<br/>repos.json"]
        DIFF["DiffEngine<br/>(pure python,<br/>backend-agnostic,<br/>priority_sync rule)"]
        GSREPO["GSheetRepo"]
        SBREPO["SupabaseRepo"]
        KPROD["Kafka Producer<br/>+ topic ensure"]
        ROUTES["HTTP routes:<br/>PUT /repos/&lt;r&gt;/documents<br/>POST /repos/&lt;r&gt;/documents/query<br/>POST /repos/&lt;r&gt;/schema/ensure<br/>POST /repos/&lt;r&gt;/kafka/publish"]
    end

    subgraph Backends["Document repositories (pluggable)"]
        GSHEET[("Google Sheet<br/>(prod_gsheet — kept as primary<br/>during migration)")]
        SUPA[("Supabase / Postgres<br/>(new repos &amp; future primary)")]
    end

    subgraph ExtSvc["External services (unchanged)"]
        APITOOLS_OCR[("apitools OCR<br/>existing routes")]
        GEMINI[("Gemini / Vision")]
    end

    PUB --> RP
    BACKFILL --> ROUTES
    GSHEET -. "future:<br/>change-data publisher" .-> RP

    RP --> KCON
    KCON -- "HTTP POST event" --> WH06N

    WH06N --> SETT
    WH06N -- "~32 call sites<br/>(unchanged)" --> BUW
    WH06N --> GETW

    BUW -- "1. acquire" --> PL
    BUW -- "2. PUT /repos/&lt;r&gt;/documents" --> ROUTES
    BUW -- "3. release" --> PL
    GETW -- "POST /repos/&lt;r&gt;/documents/query" --> ROUTES

    PL --> REDIS

    ROUTES --> REPOS
    ROUTES --> DIFF
    DIFF --> GSREPO
    DIFF --> SBREPO
    ROUTES --> KPROD
    KPROD --> RP

    GSREPO --> GSHEET
    SBREPO --> SUPA

    SETT --> APITOOLS_OCR
    SETT --> GEMINI

    classDef new fill:#dff5e1,stroke:#1b5e20,stroke-width:2px,color:#000
    classDef stay fill:#eef2ff,stroke:#3949ab,color:#000
    classDef store fill:#fff3e0,stroke:#e65100,color:#000
    class RP,KCON,REPOS,DIFF,GSREPO,SBREPO,KPROD,ROUTES,BUW,GETW new
    class WH06N,PL,SETT,REDIS,APITOOLS_OCR,GEMINI stay
    class GSHEET,SUPA store
```

**Legend (new):**
- 🟩 green = newly built in this project (Python module + Redpanda + Kafka worker + 2 thin n8n wrappers).
- 🟦 blue = unchanged n8n / external services.
- 🟧 orange = data stores (one or many; selectable per repo).

---

## 3. Side-by-side mapping

| Concern | OLD | NEW |
|---|---|---|
| Trigger | Google Sheets polling trigger inside `0.1.6` | **Kafka topic** `${prefix}.<repo>` → consumer worker → existing Webhook of `0.1.6` |
| Batch upsert (data side) | `Batch Upsert` workflow: GSheet read → Code-node diff → `googleapis batchUpdate` + `append` | `PUT /incomingDocuments/repos/<r>/documents` → `DiffEngine` → `GSheetRepo` **or** `SupabaseRepo` |
| Batch get | `Get Incoming Document` workflow: switch (single/all/complex/custom-filter) → `googleapis values.get` | `POST /incomingDocuments/repos/<r>/documents/query` → unified `Query` translated per-backend |
| Locking | `process_lock` (Redis) inside n8n | **Unchanged** — wrappers acquire/release around the HTTP call. Python API never locks. |
| Schema mgmt | implicit (sheet header is the schema) | `POST /repos/<r>/schema/ensure` (no-op for GSheet, real DDL for Supabase, modeled on the Supabase reference workflow) |
| Backend choice | Hard-coded to one Google Sheet | `RepoConfig.backend ∈ {gsheet, supabase}` per repo, in registry JSON |
| Concurrency model | Per-row Redis lock + sequential GSheet writes | Same per-row lock + per-batch atomic upsert (Supabase) / batchUpdate (GSheet) |
| Observability | n8n executions UI | Sentry (existing) + Redpanda console + structured logs in apitools |
| Replay | Not possible | Re-consume from Kafka offset |
| Helper workflows (Settings/Figure*/Query*/Extractors) | n8n | **Unchanged** — still in n8n, called from `0.1.6` exactly as today |

---

## 4. Migration boundary (zoom)

```mermaid
sequenceDiagram
    autonumber
    participant T as 0.1.6 trigger node<br/>(call site, e.g. "STATUS COMPLETED")
    participant W as Batch Upsert wrapper (NEW)
    participant L as process_lock (Redis)
    participant A as apitools<br/>PUT /repos/&lt;r&gt;/documents
    participant D as DiffEngine
    participant R as GSheetRepo / SupabaseRepo
    participant S as Sheet / Supabase

    T->>W: { rows: [...] }
    W->>L: lock(IDs)
    L-->>W: ok
    W->>A: PUT body=rows
    A->>D: diff(current, incoming)
    D->>R: fetch_by_ids(IDs)
    R->>S: read
    S-->>R: current rows
    R-->>D: current
    D-->>A: { updates, creates, noops }
    A->>R: batch_update(updates)
    R->>S: batchUpdate / upsert
    A->>R: batch_create(creates)
    R->>S: append / upsert
    A-->>W: { success, updated, created, stats }
    W->>L: unlock(IDs)
    L-->>W: ok
    W-->>T: response
```

This sequence is the **only** place the system shape changes. Every other arrow in section 1's diagram is preserved verbatim in section 2.

---

## 5. Phased cut-over view

```mermaid
gantt
    title Cut-over timeline (per phase)
    dateFormat  X
    axisFormat  P%d

    section Phase 1
    Context collection           :done, p1, 0, 1
    section Phase 2
    Implementation + Test plan   :done, p2, after p1, 1
    section Phase 3
    Build & test (both backends) :active, p3, after p2, 4
    section Phase 4
    New n8n wrappers + Kafka swap :p4, after p3, 2
    Parity capture (n8n tee)     :p4b, after p3, 1
    section Phase 5
    Review + improvements        :p5, after p4, 1
    section Phase 6
    Human verification & migration :p6, after p5, 1
```

Throughout phases 3–5 the **old system stays primary** (feature flag `INCOMING_DOCS_ENABLED=false` for production traffic). Phase 6 is the only phase that changes which workflow ID `0.1.6`'s `executeWorkflow` nodes target.
