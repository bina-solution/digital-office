# INDOX — Per-Type Fixture Architecture (config-only document types)

**Status:** design (2026-07-03). Author: INDOX lead architect.
**Goal:** an ENTIRE document type (invoice / shipment / order / balance_sheet / a future `receipt`)
is defined by config rows in the `settings` table and executed by a small set of GENERIC engine
workflows. Adding or changing a type is **config-only** — no workflow edit, no redeploy.

Companion docs: `architecture-map.md` (§3 INDOX layers, §4 API contract), `api-abstraction-refactor.md`
(DATA/DRIVE/GMAIL routers), `indox-expected-behaviour.md` (operator spec + came-to-rest bar),
`indox-demo-onboarding-architecture.md` (AI-cache→Postgres, blueprints).

This doc grounds every claim in the subsystem maps (cited inline as `[ai]`, `[selection]`, `[lifecycle]`,
`[linking]`, `[config]`, `[bs]`, `[router]`).

---

## 0. Design thesis (read this first)

INDOX already has the RIGHT engine shape, hidden under hardcoding. From `[bs]`:

> **The Driver is 100% agnostic to fixture differences.** It reads `TYPE` → calls `Decide` → gets
> `ACTION` + `DOC_TYPE` → looks up `(DOC_TYPE → collection WF)` → calls collection → collects result →
> calls Upsert → loops. No conditional logic, no per-type config in Driver.

So the engine is: **Driver (loop) → Decide (state machine) → Action collection (handlers) → Upsert → loop.**
Today the per-type variation lives in three hardcoded places:

1. **Decide** — a monolithic Code node with `gdocAction()` / `bsDocAction()` / `unknownTypeAction()`
   branches, hardcoded step order + guards `[lifecycle]`.
2. **Action handlers** — a 26-branch GDoc collection + 10-branch BS collection, each handler with
   hardcoded field mappings, endpoints, side-effects `[linking][bs]`.
3. **Extraction / selection** — invoice-coupled Gemini prompt in a Set node `[ai]`; a 130-line
   normalizer with hardcoded field lists + score tiers `[selection]`.

The per-type fixture **extracts all three into declarative `settings` rows**, and replaces the three
hardcoded sites with **generic engines that read the fixture**. The key realization from `[lifecycle]`:

> Full per-type ordered pipeline COULD be settings-driven IF expressed as
> `{ type, steps:[{action, guard, completionFlag, onFail}], routes:{STATUS→handler} }`.

The fixture makes that concrete. The one thing that CANNOT be pure config is the **BS line-spawn
algorithm** (`[bs]`: "not configuration, it's algorithm") — that stays a code primitive the fixture
*invokes* (see §G).

---

## A. The per-type fixture — JSON schema + worked examples

### A.1 Storage & load

One `settings` row per type: `key = 'fixture_<TYPE>'`, `value = <JSON string>` `[config][router]`.
Read at runtime via the DATA router — `[router]`:

```
executeWorkflow(indoxApiRouter01, {INLINE_ACTION:'TABLE_GET', table:'settings', filter:{key:'fixture_INVOICE'}})
→ rows[0].value → JSON.parse
```

The existing **KW Config Postgres Loader** `[config]` (`indoxSettings01`) already aggregates settings
once per execution; extend its `WHERE key IN (...) OR key LIKE 'q_%'` to also match `key LIKE 'fixture_%'`,
so all fixtures land in the merged `settings.fixtures` map in a single query — no extra round-trip per doc.
Cache in redis with a short TTL inside the router `[config]` ("cache settings/companies in redis; keep
per-doc reads minimal") so the fixture read is effectively free under load.

**A fixture MUST be a pure data object** — no code, no expressions that need eval beyond a tiny declared
guard-DSL (§E.2). This keeps it seedable via `TABLE_UPSERT` `[config]` and diffable in git.

### A.2 The schema (annotated)

```jsonc
{
  "type": "INVOICE",              // canonical TYPE value written to the row
  "doc_class": "gdoc",            // engine family → selects action collection (gdoc | bs | line). §G
  "version": 3,                   // bump to invalidate downstream caches keyed on it. §D.4

  // (1) ── TYPE DETECTION ─────────────────────────────────────────────────
  // Consumed by the generic classifier (§B.1). Mirrors today's *_kws / *_strong settings [config].
  "detect": {
    "keywords":        ["חשבונית מס", "חשבונית מס/קבלה", "חשבונית זיכוי"],  // any-match → candidate
    "strong_keywords": ["חשבונית מס"],   // high-confidence subset; wins ties [config]
    "priority": 40,   // tie-break weight when multiple types match one doc (higher wins)
    "ai_type_map": ["INVOICE"]   // which AI_TYPE enum labels resolve to this type (from [ai] prompt)
  },

  // (2) ── KW EXTRACTION ───────────────────────────────────────────────────
  // Consumed by the generic kw-extract engine (§B.2). Each field = ONE apitools documentJsonQuery
  // (single-query, cap-2) [given]. This REPLACES the orphaned q_* rows — the fixture becomes
  // authoritative; the engine reads fields[].query from here, not hardcoded query nodes [given].
  "kw_extract": {
    "fields": [
      {
        "target": "INVOICE_ID",                 // column written on the row
        "query": {                              // exact apitools shape (verified in rD3hoAVD…) [linking]
          "action": "find after",               // find-after | find-below | find-option
          "action_value": ["חשבונית מס מספר:", "חשבונית מס מספר", "חשבונית מס'"],
          "value_validations": [
            { "validation_type": "has_number" },
            { "validation_type": "length_greater_than", "validation_value": 3 },
            { "validation_type": "length_less_than",    "validation_value": 20 }
          ],
          "is_rtl": true
        },
        "normalizer": "docid_last5",            // named normalizer from the shared registry (§E.1)
        "completionFlag": "QUERY_INVOICE_ID_COMPLETED"
      },
      { "target": "DOC_DATE",  "query": { "$ref": "q_date_after" },   "normalizer": "date_ddmmyyyy", "completionFlag": "QUERY_DATE_COMPLETED" },
      { "target": "DOC_TOTAL_AMOUNT", "query": { "$ref": "q_amount_below" }, "normalizer": "amount_2dp", "completionFlag": "QUERY_AMOUNT_COMPLETED" },
      { "target": "PURCHASE_ID", "query": { "$ref": "q_purchase_id_after" }, "normalizer": "trim", "completionFlag": "QUERY_PURCHASE_COMPLETED" },
      { "target": "SHIPMENT_DOC_ID", "query": { "$ref": "q_shipment_id_below" }, "normalizer": "trim", "completionFlag": "QUERY_SHIPMENT_COMPLETED" }
    ]
  },

  // (3) ── AI EXTRACTION ──────────────────────────────────────────────────
  // Consumed by the generic ai-extract engine (§D). The prompt is TEMPLATED from response_schema,
  // not hardcoded [ai]. Model / cache strategy are fields, not node config.
  "ai_extract": {
    "enabled": true,
    "model": "gemini-3.1-pro-preview",
    "cache": { "prefix": "invoice", "key": "sha256_binary", "bust_on": ["version", "model"] },  // §D.4
    "system_preamble": "You extract structured data from a single Israeli business document.",
    "constants": { "own_company_vat": "515561520" },   // was hardcoded in the invoice prompt [ai]
    "response_schema": {
      "AI_TYPE":        { "type": "enum", "values": ["INVOICE","SHIPMENT","BALANCE_SHEET","ORDER","RECEIPT","IRRELEVANT"], "desc": "document type" },
      "AI_COMPANY_ID":  { "type": "string", "desc": "issuer VAT/ח.פ, EXCLUDING {{own_company_vat}}", "hint": "ע.מ / ח.פ" },
      "AI_DOC_ID":      { "type": "string", "desc": "invoice number (חשבונית מס)" },
      "AI_DOC_DATE":    { "type": "date:DD/MM/YYYY", "desc": "invoice date" },
      "AI_DOC_AMOUNT":  { "type": "string:decimal", "desc": "total incl VAT (סכום כולל / יתרה לתשלום); NEGATIVE if credit note" },
      "AI_ORDER_IDS":   { "type": "string", "desc": "customer PO (מספר הזמנת לקוח)" },
      "AI_SHIPMENT_IDS":{ "type": "array<string>", "desc": "delivery-note numbers referenced" }
    }
  },

  // (4) ── SELECTION / RECONCILIATION ─────────────────────────────────────
  // Consumed by the generic select engine (§E). Declares WHICH dimensions to reconcile, each
  // dimension's sources + priority + normalizer, and the scoring rules [selection].
  "select": {
    "dimensions": [
      { "name": "company_id", "sources": ["AI_COMPANY_ID","KW:COMPANY_ID"],           "normalizer": "companyid_last6", "confirm": "id"   },
      { "name": "doc_id",     "sources": ["AI_DOC_ID","KW:INVOICE_ID"],                "normalizer": "docid_last5",     "confirm": "id"   },
      { "name": "date",       "sources": ["AI_DOC_DATE","BS:BS_LINE_DATE","KW:DOC_DATE"], "normalizer": "date_ddmmyyyy", "confirm": "data" },
      { "name": "amount",     "sources": ["AI_DOC_AMOUNT","BS:BS_LINE_AMOUNT","KW:DOC_TOTAL_AMOUNT"], "normalizer": "amount_2dp", "confirm": "data" },
      { "name": "doc_type",   "sources": ["AI_TYPE","KW:TYPE"],                          "normalizer": "uppercase",       "confirm": "id"   }
    ],
    "scoring": {                                  // hoisted from hardcoded 0/50/100 tiers [selection]
      "tiers": [
        { "when": "idMismatch",                       "score": 0 },
        { "when": "aiBsMatch",                        "score": 100 },
        { "when": "!dataMismatch && allConfirmed",    "score": 100 },
        { "when": "!dataMismatch",                    "score": 50 },
        { "default": true,                            "score": 0 }
      ],
      "date_outlier_days": 180,                   // was SIX_MONTHS_MS hardcode [selection]
      "trusted_supplier": { "table": "companies", "match": ["companyId","sourceType"], "boost_to": 100 }
    },
    "outputs": [                                  // SELECTED_* mapping; AI||BS||KW fallback per dim
      { "target": "SELECTED_COMPANY_ID", "from": "company_id" },
      { "target": "SELECTED_DOC_ID",     "from": "doc_id" },
      { "target": "SELECTED_DOC_DATE",   "from": "date" },
      { "target": "SELECTED_DOC_AMOUNT", "from": "amount" },
      { "target": "SELECTED_DOC_TIPE",   "from": "doc_type" },
      { "target": "SELECTED_DOC_SHIPMENT_ID", "rule": "shipment_id" },  // named helper (§E.3)
      { "target": "SELECTED_DOC_ORDER_ID",    "rule": "first_or:AI_ORDER_IDS,PURCHASE_ID" }
    ]
  },

  // (5) ── ACTION PIPELINE (lifecycle) ────────────────────────────────────
  // Consumed by the generic action-pipeline runner (§F). Ordered steps; each has a guard, the
  // handler action name, the completionFlag it sets, and an onFail terminal route. The runner
  // returns ONE action per Driver iteration (matches today's one-action-per-loop) [lifecycle].
  "pipeline": {
    "pre_guards": [                               // global gates, evaluated before type steps [lifecycle]
      { "when": "isDouble",     "route": "update_status_double" },
      { "when": "isOldDoc",     "route": "update_status_old" },
      { "when": "iterExceeded", "route": "no_action_max_iterations" }
    ],
    "steps": [
      { "action": "figure_company_id",  "guard": "!FIGURE_COMPANY_COMPLETED", "sets": "FIGURE_COMPANY_COMPLETED", "onFail": "no_action_awaiting_company_id" },
      { "action": "get_company_name",   "guard": "COMPANY_ID && !COMPANY_NAME_COMPLETED", "sets": "COMPANY_NAME_COMPLETED" },
      { "action": "update_company_doc_id","guard": "!COMPANY_DOC_ID", "from": ["INVOICE_ID","AI_DOC_ID"], "onFail": "no_action_awaiting_doc_id" },
      { "action": "update_name",        "guard": "COMPANY_NAME && SHORT_DOC_ID && !NAME_COMPLETED", "sets": "NAME_COMPLETED" },
      { "action": "get_api_tools_id",   "guard": "LINK && !API_TOOLS_ID_COMPLETED", "sets": "API_TOOLS_ID_COMPLETED", "onFail": "update_status_api_tools_failed" },
      { "action": "find_link",          "guard": "!LINK && !SEARCH_IN_DRIVE_COMPLETED", "sets": "SEARCH_IN_DRIVE_COMPLETED", "onFail": "no_action_link_not_found" },
      { "action": "check_from_office",  "guard": "!FROM_OFFICE_CHECK_COMPLETED", "sets": "FROM_OFFICE_CHECK_COMPLETED" },
      { "action": "kw_extract",         "guard": "API_TOOLS_ID && !KW_EXTRACT_COMPLETED", "sets": "KW_EXTRACT_COMPLETED" },   // runs §B.2 over kw_extract.fields
      { "action": "ai_extract",         "guard": "LINK && !AI_EXTRACTION_COMPLETED", "sets": "AI_EXTRACTION_COMPLETED" },     // runs §D
      { "action": "extract_shipment_ids","guard": "AI_SHIPMENT_IDS && !EXTRACT_SHIPMENT_COMPLETED", "sets": "EXTRACT_SHIPMENT_COMPLETED" },
      { "action": "select_values",      "guard": "hashChanged(SELECTION_VALUES_HASH)", "sets": "SELECTION_COMPLETED", "resets_downstream": ["PRIORITY_SYNC_COMPLETED"] },
      { "action": "priority_sync",      "guard": "SELECTION_COMPLETED && activePrioritySync && !PRIORITY_SYNC_COMPLETED", "sets": "PRIORITY_SYNC_COMPLETED" }
    ],
    "complete_when": ["FIGURE_TYPE_COMPLETED","FIGURE_COMPANY_COMPLETED","SELECTION_COMPLETED"],  // → mark_completed
    "on_complete": "mark_completed"
  },

  // (6) ── SIDE-EFFECTS (which handlers apply / how they map) ──────────────
  // Only handlers listed here are enabled for the type; each supplies its type-specific mapping
  // so the generic handler stays type-agnostic [linking].
  "side_effects": {
    "priority_sync": {
      "endpoint": "https://msh.macomp.vip/odata/Priority/tabula.ini/mscohen/SHIM_RECEIVE_SUPDOC",
      "id_field": "SELECTED_DOC_ID",            // INVOICE_ID for invoices; SHIPMENT_ID for shipments [linking]
      "field_map": { "SUPNAME":"SELECTED_COMPANY_ID", "IVNUM":"SELECTED_DOC_ID", "CURDATE":"SELECTED_DOC_DATE", "QPRICE":"SELECTED_DOC_AMOUNT" /* …13 fields */ }
    },
    "update_name": { "pattern": "${COMPANY_NAME}-${SHORT_DOC_ID}" },   // universal Drive rename [linking]
    "extract_shipment_ids": { "source_field": "AI_SHIPMENT_IDS", "min_rows": 2, "child_type": "SHIPMENT" }
  }
}
```

### A.3 Worked example — `receipt` (NEW type, config-only)

A receipt is a payment confirmation: it has a transaction/receipt id, a company, a date, an amount, and a
payment method. It needs KW + AI extraction and selection, but **no shipment/order linking and no Priority
sync** (or a different Priority table). Adding it is ONE new `settings` row `fixture_RECEIPT` — no engine
change, no workflow deploy `[config][lifecycle]`.

```jsonc
{
  "type": "RECEIPT",
  "doc_class": "gdoc",           // reuses the gdoc collection + Driver [bs]
  "version": 1,

  "detect": {
    "keywords":        ["קבלה", "קבלה מס'", "אישור תשלום", "receipt"],
    "strong_keywords": ["קבלה מס'"],
    "priority": 35,              // lower than invoice(40) so "חשבונית מס/קבלה" resolves to INVOICE first
    "ai_type_map": ["RECEIPT"]
  },

  "kw_extract": {
    "fields": [
      { "target": "RECEIPT_ID",   "query": { "action":"find after", "action_value":["קבלה מספר:","קבלה מס'","קבלה מספר"], "value_validations":[{"validation_type":"has_number"},{"validation_type":"length_greater_than","validation_value":2},{"validation_type":"length_less_than","validation_value":20}], "is_rtl":true }, "normalizer":"docid_last5", "completionFlag":"QUERY_RECEIPT_ID_COMPLETED" },
      { "target": "DOC_DATE",         "query": { "$ref":"q_date_after" },   "normalizer":"date_ddmmyyyy", "completionFlag":"QUERY_DATE_COMPLETED" },
      { "target": "DOC_TOTAL_AMOUNT", "query": { "$ref":"q_amount_below" }, "normalizer":"amount_2dp",    "completionFlag":"QUERY_AMOUNT_COMPLETED" },
      { "target": "PAYMENT_METHOD",   "query": { "action":"find after", "action_value":["אמצעי תשלום","שולם ב"], "value_validations":[{"validation_type":"length_greater_than","validation_value":1}], "is_rtl":true }, "normalizer":"trim", "completionFlag":"QUERY_PAYMENT_METHOD_COMPLETED" }
    ]
  },

  "ai_extract": {
    "enabled": true,
    "model": "gemini-3.1-pro-preview",
    "cache": { "prefix": "receipt", "key": "sha256_binary", "bust_on": ["version","model"] },
    "system_preamble": "You extract structured data from a single Israeli payment receipt.",
    "constants": { "own_company_vat": "515561520" },
    "response_schema": {
      "AI_TYPE":       { "type":"enum", "values":["INVOICE","SHIPMENT","BALANCE_SHEET","ORDER","RECEIPT","IRRELEVANT"], "desc":"document type" },
      "AI_COMPANY_ID": { "type":"string", "desc":"issuer VAT/ח.פ, EXCLUDING {{own_company_vat}}" },
      "AI_DOC_ID":     { "type":"string", "desc":"receipt number (קבלה)" },
      "AI_DOC_DATE":   { "type":"date:DD/MM/YYYY", "desc":"receipt date" },
      "AI_DOC_AMOUNT": { "type":"string:decimal", "desc":"amount paid" },
      "AI_PAYMENT_METHOD": { "type":"string", "desc":"payment method (מזומן/אשראי/העברה/צ'ק)" }
    }
  },

  "select": {
    "dimensions": [
      { "name":"company_id", "sources":["AI_COMPANY_ID","KW:COMPANY_ID"], "normalizer":"companyid_last6", "confirm":"id" },
      { "name":"doc_id",     "sources":["AI_DOC_ID","KW:RECEIPT_ID"],     "normalizer":"docid_last5",     "confirm":"id" },
      { "name":"date",       "sources":["AI_DOC_DATE","KW:DOC_DATE"],     "normalizer":"date_ddmmyyyy",   "confirm":"data" },
      { "name":"amount",     "sources":["AI_DOC_AMOUNT","KW:DOC_TOTAL_AMOUNT"], "normalizer":"amount_2dp","confirm":"data" },
      { "name":"doc_type",   "sources":["AI_TYPE","KW:TYPE"],             "normalizer":"uppercase",       "confirm":"id" }
    ],
    "scoring": {
      "tiers": [
        { "when":"idMismatch", "score":0 },
        { "when":"!dataMismatch && allConfirmed", "score":100 },
        { "when":"!dataMismatch", "score":50 },
        { "default":true, "score":0 }
      ],
      "date_outlier_days": 90,     // receipts cluster tighter than invoices — per-type override [selection]
      "trusted_supplier": { "table":"companies", "match":["companyId","sourceType"], "boost_to":100 }
    },
    "outputs": [
      { "target":"SELECTED_COMPANY_ID", "from":"company_id" },
      { "target":"SELECTED_DOC_ID",     "from":"doc_id" },
      { "target":"SELECTED_DOC_DATE",   "from":"date" },
      { "target":"SELECTED_DOC_AMOUNT", "from":"amount" },
      { "target":"SELECTED_DOC_TIPE",   "from":"doc_type" }
      // no shipment/order outputs — receipts don't reference them
    ]
  },

  "pipeline": {
    "pre_guards": [
      { "when":"isDouble",     "route":"update_status_double" },
      { "when":"isOldDoc",     "route":"update_status_old" },
      { "when":"iterExceeded", "route":"no_action_max_iterations" }
    ],
    "steps": [
      { "action":"figure_company_id",   "guard":"!FIGURE_COMPANY_COMPLETED", "sets":"FIGURE_COMPANY_COMPLETED", "onFail":"no_action_awaiting_company_id" },
      { "action":"get_company_name",    "guard":"COMPANY_ID && !COMPANY_NAME_COMPLETED", "sets":"COMPANY_NAME_COMPLETED" },
      { "action":"update_company_doc_id","guard":"!COMPANY_DOC_ID", "from":["RECEIPT_ID","AI_DOC_ID"], "onFail":"no_action_awaiting_doc_id" },
      { "action":"update_name",         "guard":"COMPANY_NAME && SHORT_DOC_ID && !NAME_COMPLETED", "sets":"NAME_COMPLETED" },
      { "action":"get_api_tools_id",    "guard":"LINK && !API_TOOLS_ID_COMPLETED", "sets":"API_TOOLS_ID_COMPLETED", "onFail":"update_status_api_tools_failed" },
      { "action":"find_link",           "guard":"!LINK && !SEARCH_IN_DRIVE_COMPLETED", "sets":"SEARCH_IN_DRIVE_COMPLETED", "onFail":"no_action_link_not_found" },
      { "action":"check_from_office",   "guard":"!FROM_OFFICE_CHECK_COMPLETED", "sets":"FROM_OFFICE_CHECK_COMPLETED" },
      { "action":"kw_extract",          "guard":"API_TOOLS_ID && !KW_EXTRACT_COMPLETED", "sets":"KW_EXTRACT_COMPLETED" },
      { "action":"ai_extract",          "guard":"LINK && !AI_EXTRACTION_COMPLETED", "sets":"AI_EXTRACTION_COMPLETED" },
      { "action":"select_values",       "guard":"hashChanged(SELECTION_VALUES_HASH)", "sets":"SELECTION_COMPLETED" }
      // no extract_shipment_ids, no priority_sync
    ],
    "complete_when": ["FIGURE_TYPE_COMPLETED","FIGURE_COMPANY_COMPLETED","SELECTION_COMPLETED"],
    "on_complete": "mark_completed"
  },

  "side_effects": {
    "update_name": { "pattern": "${COMPANY_NAME}-${SHORT_DOC_ID}" }
    // priority_sync omitted → handler never enabled for RECEIPT
  }
}
```

**Seeding it** `[config]`: `executeWorkflow(indoxApiRouter01, {INLINE_ACTION:'TABLE_UPSERT', table:'settings',
key:'fixture_RECEIPT', value:<the JSON above, stringified>})`. Because the classifier, kw-extract, ai-extract,
select, and pipeline runner all read fixtures generically, RECEIPT is now a first-class type with zero
engine edits. The 15-doc E2E test (§H) picks it up the moment a receipt document appears.

---

## B. The generic engine workflows

Five engines replace the hardcoded sites. Each reads the fixture (from the merged `settings.fixtures` map)
and is **type-agnostic**. All data access is via `indoxApiRouter01` `[router]`; all Drive/Gmail via
`driveApi01` / `gmailApiRouter01` `[router]`.

### B.1 `kwGlobalClassifier01` — type + company detection (generic)

Today: "Figure Document Type" (`indoxV2FigureDocType01`) uses `find option` over `invoice_kws/shipment_kws/bs_kws/
order_kws` `[lifecycle]`; company via `find option` on `all_companies_identifiers` (`indoxV2FigureCompanyId01`).
These are ALREADY config-driven `[lifecycle]` ("Figure-Type and Figure-Company ARE already config-driven").

Generic form: build the `find option` keyword set by **iterating every fixture** and emitting
`{option: <keyword>, type: fixture.type, strong: bool, priority: fixture.detect.priority}`. One apitools
`find option` call `[given]` returns the matched option → resolve to `type`. Ties broken by
`strong_keywords` then `detect.priority` `[config]`. Company detection is unchanged (already generic over
`companies` identifiers). On no keyword match → fall back to `ai_extract` and read `AI_TYPE`, mapping via
`detect.ai_type_map` `[lifecycle]` ("falls back to extract_invoice_google_ai … terminates at MISSING_TYPE
if still unresolved"). Adding RECEIPT keywords to the option set is automatic — they come from the fixture.

**Sets:** `TYPE`, `FIGURE_TYPE_COMPLETED`. Reused by every type.

### B.2 `kwExtract01` — apitools field extraction (generic)

Today: per-field hardcoded query nodes (invoice_id/date/amount/purchase/shipment) `[config]`; the `q_*`
settings are ORPHANED — hardcoded queries are authoritative `[given]`. This engine **rewires them**: it
reads `fixture.kw_extract.fields[]`, and for each field runs ONE apitools `documentJsonQuery` with
`field.query` (resolving `$ref` against the shared `q_*` settings, or using the inline query object).

Because apitools is **single-query, concurrency cap 2** `[given]`, the engine iterates fields with a
`splitInBatches(2)` loop — never more than 2 concurrent apitools calls. Each result is passed through
`field.normalizer` from the shared normalizer registry (§E.1) and written to `field.target`; the field's
`completionFlag` is set. This makes the `q_*` rows finally authoritative (they are referenced by fixtures)
and kills the hardcoded query nodes `[given][config]`.

**Reads:** `fixture.kw_extract`. **Sets:** the target columns + per-field completion flags + `KW_EXTRACT_COMPLETED`.

### B.3 `aiExtract01` — Gemini extraction (generic, schema-templated)

Replaces the two invoice/BS extractor workflows' hardcoded CONFIG Set node `[ai]`. Given
`fixture.ai_extract`, it: (a) hashes the binary (Crypto) → cache key `<prefix>:<hash>` `[ai]`; (b) checks
`ai_extraction_cache` via the DATA router `[router][demo-onboarding §1]`; (c) on miss, **templates the
prompt from `response_schema`** (§D) and calls `model`; (d) validates + writes each schema field to its
column; (e) upserts the cache row via the router. Model, cache prefix, and constants are fixture fields —
so RECEIPT extraction is the same workflow with a different fixture `[ai]` ("would reuse invoice extractor
with different prompt").

**Reads:** `fixture.ai_extract`. **Sets:** `AI_*` columns + `AI_EXTRACTION_COMPLETED`.

### B.4 `select01` — reconciliation (generic, config-driven)

Replaces the 130-line hardcoded normalizer `[selection][linking]`. Reads `fixture.select`, builds the
dimensions array from `select.dimensions` (sources/normalizer/confirm per dimension), applies the shared
scoring rules from `select.scoring`, and writes `select.outputs`. Normalizers and the `has()` predicate
come from the shared registry (§E.1) so they stay universal `[selection]` ("Normalization is UNIVERSAL").
Per-type overrides (e.g. `date_outlier_days`, dimension source lists, which outputs exist) all come from
the fixture — see §E.

**Reads:** `fixture.select`. **Sets:** `SELECTED_*`, `SELECTION_CERTAINTY`, `SELECTION_SOURCE`,
`SELECTION_VALUES_HASH`, `SELECTION_COMPLETED`.

### B.5 `pipelineRunner01` — the action-pipeline runner (generic state machine)

Replaces the `gdocAction()/bsDocAction()` Decide branches `[lifecycle]`. Given the doc + `fixture.pipeline`,
it returns **exactly one ACTION per Driver iteration** (preserving today's one-action-per-loop contract
`[lifecycle]`):

1. Evaluate `pre_guards` in order; first match → return its `route` (double/old/max-iter) `[lifecycle]`.
2. Walk `steps` in order; for the first step whose `guard` is TRUE and whose `sets` flag is FALSE, return
   `step.action`. If the step's precondition fails in a terminal way, return `step.onFail`.
3. If all steps' flags are set and `complete_when` flags are all TRUE → return `on_complete`
   (`mark_completed`).
4. Else → `no_action` (waiting on an async flag from a prior action).

The runner does NOT execute the action — it names it. The Driver dispatches the named action to the
`doc_class` collection (gdoc/bs/line) `[bs]`, which runs the handler and upserts (setting the `sets` flag),
then loops `[lifecycle][bs]`. This is exactly the shape `[lifecycle]` proposed
(`steps:[{action,guard,completionFlag,onFail}]`).

**Reads:** `fixture.pipeline`. **Returns:** `{ACTION, DOC_CLASS}` for the Driver.

### B.6 How the Driver stays unchanged

The Driver `[bs]` already does GET-by-id → lock → Decide → dispatch-by-`doc_class` → Upsert → loop with
**no per-type logic**. Only Decide changes: instead of the monolithic Code node, Decide = "load fixture for
`TYPE` → call `pipelineRunner01(doc, fixture)`". The dispatch map `{doc_class → collection WF}` `[bs]`
stays a 3-entry registry (gdoc / bs / line). Adding RECEIPT touches neither Driver nor the map (RECEIPT is
`doc_class:gdoc`).

---

## C. End-to-end flow (one document)

```
SYNC LAYER (unchanged) — scanner LIST(to_sync)→CLAIM→processor→register row IN_PROGRESS  [expected-behaviour]
        │  (thin discover; md5/msg-id HASH dedup; NO OCR)
        ▼
incoming_documents row (supabase)  →  pg trigger + 2-min poll backstop  [architecture-map]
        ▼
DRIVER (indoxV2Driver01) loop:  GET-by-id → acquire doc_step lock  [bs]
        ▼
  DECIDE = load fixtures (settings.fixtures, redis-cached) → pipelineRunner01(doc, fixture[TYPE])   ← §B.5
        │      • if TYPE unknown → kwGlobalClassifier01 (find-option over ALL fixtures' keywords) → TYPE  ← §B.1
        │      • pre_guards: double / old / max-iter
        │      • first ready step → ACTION
        ▼
  DISPATCH by doc_class → action collection (gdoc | bs | line)  [bs]
        │   figure_company_id · get_company_name · update_company_doc_id · update_name ·
        │   get_api_tools_id · find_link · check_from_office ·
        │   kw_extract (→ kwExtract01, reads fixture.kw_extract)          ← §B.2
        │   ai_extract (→ aiExtract01, schema-templated prompt)           ← §B.3
        │   extract_shipment_ids (if side_effects lists it)               ← §A.2(6)
        │   select_values (→ select01, reads fixture.select)              ← §B.4
        │   priority_sync (if side_effects.priority_sync)                 ← §A.2(6)
        ▼
  Every action ENDS with a state-changing Batch Upsert → writes row + UNLOCKS  [expected-behaviour]
        ▼
  pg line-change → Driver re-enters GET-by-id → next ACTION … until complete_when satisfied
        ▼
  on_complete → mark_completed → STATUS=COMPLETED (terminal)  [lifecycle]
```

Balance sheets diverge only at `doc_class:bs` (extraction + line-spawn) — see §G. BS-spawned line records
are `TYPE=INVOICE` and re-enter this exact flow as ordinary invoices `[bs]`.

---

## D. Making AI prompts per-type (schema-driven prompt templating)

Today the invoice prompt is a hardcoded string in a Set node, tightly coupled to invoice semantics: it
bakes in `515561520` (own VAT to ignore), and references `חשבונית מס`, `יתרה לתשלום`, `סכום כולל`,
`מספר הזמנת לקוח` `[ai]`. To make prompts per-type WITHOUT a workflow per type, we **generate the prompt
from `fixture.ai_extract`** at runtime inside `aiExtract01` (§B.3).

### D.1 The template function (in `aiExtract01`, one Code node)

Input: `fixture.ai_extract` (`system_preamble`, `constants`, `response_schema`). Output: a prompt string +
a JSON response schema for the Gemini node. Algorithm:

```
prompt =
  interpolate(system_preamble, constants) + "\n\n" +
  "Return ONLY JSON matching this schema. For each field, extract the described value or 'unknown'.\n" +
  for each (name, spec) in response_schema:
      "- " + name + " (" + spec.type + "): " + interpolate(spec.desc, constants) +
             (spec.hint ? "  [look near: " + spec.hint + "]" : "") +
             (spec.values ? "  one of: " + spec.values.join("|") : "") + "\n"
responseSchema = compile(response_schema)   // {type:'object', properties:{…}} for Gemini structured output
```

`interpolate` replaces `{{own_company_vat}}` etc. from `constants`. So the invoice prompt's
"issuer VAT, EXCLUDING 515561520" is produced from `AI_COMPANY_ID.desc = "issuer VAT/ח.פ, EXCLUDING
{{own_company_vat}}"` + `constants.own_company_vat = "515561520"` `[ai]`. The RECEIPT fixture yields a
receipt-specific prompt from the same code — no new node.

### D.2 Type-shape (flat vs nested)

Invoice is flat 7-field JSON; BS is nested `[ai]`. The template handles both: a `response_schema` value can
itself be `{type:"array<object>", items:{…}}` or `{type:"object", properties:{…}}`. BS's nested
`transactions[]`/`summary`/`doc_header` schema is expressed the same declarative way (§G). SHIPMENT/ORDER/
RECEIPT stay flat. This resolves `[ai]`'s open question ("keep flat or new nested schema?") — **the fixture
decides per type**; the engine supports both.

### D.3 Structured output (correctness)

Pass the compiled `responseSchema` to Gemini's structured-output mode so the model returns valid JSON
against the schema (removes the parse-fragility of a hand-written schema string) `[ai]`. Validate each field
against its declared `type` (date format, enum membership, decimal) before writing; on validation failure,
write the field as `unknown` and append to `ERRORS` `[expected-behaviour]` rather than crashing.

### D.4 Cache keying (avoid stale extractions)

Today the cache key is `(doctype:hash)` — it does NOT invalidate on prompt/model change `[ai]`. The fixture
fixes this: `cache.key = sha256_binary`, `cache.prefix = <type>`, and `cache.bust_on = ["version","model"]`.
The effective key becomes `<prefix>:<fixture.version>:<model>:<hash>` — so bumping `version` (after a schema
edit) or changing `model` **auto-invalidates** without a manual cache clear `[ai]`. Demo/frozen cache rows
`[demo-onboarding §1]` are seeded under the same composite key, so they stay hits as long as the fixture
version is pinned. The AI cache survives resets `[expected-behaviour]` — never wiped.

---

## E. Making selection config-driven without losing correctness

`[selection]` shows selection is 90% universal + 10% per-type. The split:

### E.1 Universal (stays in a shared normalizer registry, referenced by name)

`normalizeDocID(last-5)`, `normalizeCompanyID(last-6)`, `normalizeDate(DD/MM/YYYY via Excel serial + regex)`,
`normalizeAmount(2dp)`, `normalizeDocType(uppercase)`, and the `has()` predicate (rejects null/''/'unknown')
`[selection]`. These are a fixed library inside `select01` (and reused by `kwExtract01`). The fixture
references them BY NAME (`normalizer:"docid_last5"`), never inlines code — preserving the universal
guarantee `[selection]` while letting a type pick a different one (e.g. a future regional type could use
`companyid_last8`, listed as a hardcoded_should_be_config item `[selection]`).

### E.2 Guard / condition DSL (tiny, evaluable, safe)

Guards (`!FIGURE_COMPANY_COMPLETED`, `COMPANY_ID && !COMPANY_NAME_COMPLETED`, `hashChanged(SELECTION_VALUES_HASH)`)
and scoring `when` clauses (`idMismatch`, `!dataMismatch && allConfirmed`) are a **small declarative DSL**,
not arbitrary JS. The engine exposes a fixed vocabulary of doc-derived booleans (`idMismatch`, `dataMismatch`,
`aiBsMatch`, `allConfirmed`, `isDouble`, `isOldDoc`, `iterExceeded`, `hashChanged(field)`) plus field-truthy
checks. A guard is parsed into this vocabulary + `&&/||/!` — cheap to evaluate, impossible to inject code,
and it handles the string-boolean normalization `[expected-behaviour]` (Supabase TEXT `"false"` is truthy)
centrally `[lifecycle]` ("Guard evaluation must handle string boolean conversions"). This keeps fixtures
pure data (§A.1) while expressing real conditions.

### E.3 Per-type config (from `fixture.select`)

- **Which dimensions + each dimension's sources/priority** — `select.dimensions` (invoice reconciles
  company/doc/date/amount/type with AI+BS+KW; receipt drops BS sources; a type could add a dimension)
  `[selection]` ("Field lists … are hardcoded — per-type fixture should declare mapping").
- **`confirm` mode per dimension** — `id` (2-source AI==KW) vs `data` (3-source AI/BS/KW) — hoists the
  special-cased `idMismatch`/`dataMismatch`/`allFourConfirmed` logic into per-dimension config
  `[selection]`.
- **Score tiers** — `select.scoring.tiers` (data-driven `when→score`) replaces the hardcoded 0/50/100 and
  allows intermediate tiers per type `[selection]`.
- **`date_outlier_days`** — replaces the 180-day `SIX_MONTHS_MS` constant; per-type (BS spans fiscal years;
  receipts tighter) `[selection]`.
- **Trusted-supplier override** — now a `companies`-table lookup `[demo-onboarding]` (already moved off
  sheet3), matched on `[companyId, sourceType]`, boosting to 100 `[selection]`.
- **Type-specific output rules** — `SELECTED_DOC_SHIPMENT_ID` uses the named `shipment_id` rule
  (`TYPE==='SHIPMENT'` → `INV_ID_FOR_SHIP`, else `extractFirstShipmentID(AI_SHIPMENT_IDS)`) `[selection]`;
  receipts omit it entirely.

**Correctness is preserved** because: (a) normalizers stay a fixed universal library (no behavioral drift);
(b) the confirm/mismatch/score semantics are the SAME algorithm, just parameterized — the invoice fixture
reproduces today's exact tiers, so invoice behavior is bit-identical (proven by the E2E test, §H); (c) the
guard DSL centralizes the string-boolean normalization that today is a known footgun `[expected-behaviour]`.

---

## F. Can the action SEQUENCE be data-driven? Yes.

`[lifecycle]` explicitly says the ordered pipeline CAN be settings-driven if expressed as
`steps:[{action, guard, completionFlag, onFail}]` — which is exactly `fixture.pipeline.steps` (§A.2(5)).
The runner (§B.5) walks that array. Requirements from `[lifecycle]`, all met:

- **Each step declares** action, guard, completion-flag (`sets`), fallback (`onFail`) — present.
- **Guards synchronously evaluable on the doc** — the DSL (§E.2) evaluates against the row, handling
  string-booleans/null/Excel-dates `[lifecycle]`.
- **Ordering sensitivity** (COMPANY_ID before TYPE for shipments; TYPE before extraction; LINK gates
  extraction for invoices but NOT shipments) `[lifecycle]` — encoded as **step order + guards per fixture**.
  Shipments' fixture simply omits `ai_extract` and puts `find_link` behind `!isBsLine`; invoices keep it.
  The order IS the config.
- **Selection gate as re-sync point** — `select_values` guard `hashChanged(SELECTION_VALUES_HASH)` with
  `resets_downstream:[PRIORITY_SYNC_COMPLETED]` `[lifecycle]` ("gating PRIORITY_SYNC and COMPLETED; serves
  as re-sync point").
- **Completion-flag pattern** — every step's `sets` flag distinguishes "not run" from "ran, found nothing"
  `[lifecycle]` ("without *_COMPLETED, system cannot distinguish").
- **Infinite-loop / status gates** — `pre_guards` + `max_actions_per_doc` from settings `[lifecycle][config]`.

**What is NOT pure data:** the handler bodies (the actual `find_link` Drive search, the `priority_sync`
HTTP POST). Those stay as handler nodes in the collection; the fixture only decides *whether/when* they run
and supplies their type-specific mapping via `side_effects` (§A.2(6)). This matches `[linking]`
("action_priority_sync must be configured per-type … parameter mapping differs") and keeps universal
plumbing (`find_link`, `update_name`, `check_from_office`, `update_company_doc_id`) in the base collection
`[linking]` ("belong in base workflow — no type variance").

**Branching by type** `[lifecycle]` ("Branching BY TYPE requires if-then structure") is achieved by giving
each type its OWN `steps` array rather than one array with embedded conditionals — cleaner and diffable.
Where a single type needs an internal branch (e.g. shipment with vs without LINK), the guard on the step
expresses it (`find_link` guard `!LINK && !isBsLine`).

---

## G. How Balance Sheet fits (same fixture shell, special `doc_class`)

`[bs]` is emphatic: **BS is NOT a simple type-fixture variant — it is a document-spawning meta-type**
(1 doc → N line-records → N completions). A fixture that models `decide()→write()` cannot express
`decide-once, then spawn-N-and-loop-each`. The resolution:

### G.1 BS uses the SAME fixture shell but `doc_class:"bs"`

The `doc_class` field routes the Driver to the **BS action collection** (`indoxV2ActionsBS01`) `[bs]`,
which contains the irreducible `link_documents` algorithm (split lines → 1 GET_ALL → per-line match →
create/update INVOICE row → aggregate → batch upsert). That algorithm stays **code, not config** `[bs]`
("line-spawning logic … is not configuration, it's algorithm"). The fixture supplies its *parameters*:

```jsonc
{
  "type": "BALANCE_SHEET",
  "doc_class": "bs",
  "version": 2,
  "detect": { "keywords": ["<bs_kws…>"], "strong_keywords": ["<bs_strong…>"], "priority": 60, "ai_type_map": ["BALANCE_SHEET"] },

  "bs_extract": {                              // BS-specific extraction block (nested schema) [ai][bs]
    "extractor_endpoint": "bs_ex_2_dev",       // webhook (indoxV2ExtractBalanceSheet01) [bs]
    "model": "gemini-3.1-pro-preview",
    "cache": { "prefix": "bs", "key": "sha256_binary", "bust_on": ["version","model"] },
    "response_schema": {                       // nested — the template (§D.2) compiles this too
      "doc_header":     { "type":"object", "properties": { /* company, statement type, date, column_ids, full_document_logic */ } },
      "selection_logic":{ "type":"object", "properties": { /* last-N kept, cutoff balance */ } },
      "transactions":   { "type":"array<object>", "items": { "unique_key":"string","references":"string","date":"date","debit":"string","credit":"string","accumulated_balance":"string","notes":"string" } },
      "summary":        { "type":"object", "properties": { "documentTotal":"string","documentDate":"date","totalsMatch":"boolean","currency":"string" } }
    },
    "verify": { "gate": "summary.totalsMatch == true" }   // BS_EXTRACTION_VERIFIED [bs]
  },

  "spawn": {                                   // parameters for the code link_documents primitive [bs]
    "lines_field": "BS_EXTRACTED_LINES.data.lines",
    "child_type": "INVOICE",
    "match_query": { "COMPANY_ID": "$parent.COMPANY_ID", "SHORT_DOC_ID": "last5($line.id)" },
    "child_field_map": {                       // BS line + parent → new INVOICE row [bs]
      "NAME": "${COMPANY_NAME}-${SHORT_DOC_ID}", "TYPE": "INVOICE",
      "COMPANY_DOC_ID": "$line.id", "LINKED_BS": "$parent.NAME",
      "BS_LINE_AMOUNT": "$line.amount", "BS_LINE_DATE": "$line.date", "BS_LINE_NOTE": "$line.notes",
      "STATUS": "IN_PROGRESS", "SOURCE_TYPE": "BALANCE_SHEET", "SOURCE_ID": "$parent.ID"
    }
  },

  "pipeline": {                                // BS has a 3-gate pipeline [bs]
    "pre_guards": [ { "when":"isDouble","route":"update_status_double" }, { "when":"iterExceeded","route":"no_action_max_iterations" } ],
    "steps": [
      { "action":"figure_company_id", "guard":"!FIGURE_COMPANY_COMPLETED", "sets":"FIGURE_COMPANY_COMPLETED", "onFail":"no_action_awaiting_company_id" },
      { "action":"extract_balance_sheet", "guard":"!BS_EXTRACTED_LINES", "sets":"BS_EXTRACTED_LINES_COMPLETED", "onFail":"update_status_bs_extraction_failed" },
      { "action":"verify_balance_sheet",  "guard":"BS_EXTRACTED_LINES && !BS_EXTRACTION_VERIFIED", "sets":"BS_EXTRACTION_VERIFIED" },
      { "action":"link_documents", "guard":"BS_EXTRACTION_VERIFIED && !BS_LINK_DOCUMENTS_COMPLETED", "sets":"BS_LINK_DOCUMENTS_COMPLETED" }
    ],
    "complete_when": ["BS_EXTRACTED_LINES_COMPLETED","BS_EXTRACTION_VERIFIED","BS_LINK_DOCUMENTS_COMPLETED"],
    "on_complete": "mark_completed"
  }
}
```

### G.2 Why this is consistent, not a special case

- The **fixture shell is uniform** (`type`/`doc_class`/`detect`/`pipeline`) — the Driver, classifier, and
  pipelineRunner treat BS identically (load fixture → run pipeline → dispatch by `doc_class`) `[bs]`
  ("Engine does NOT need to be BS-aware beyond type routing").
- BS just adds two blocks (`bs_extract`, `spawn`) that only the `bs` collection reads, and its `pipeline`
  lists BS-specific actions (`extract_balance_sheet`, `verify_balance_sheet`, `link_documents`). The
  **algorithm** behind `link_documents` remains a dedicated handler `[bs]`.
- **Crucially, BS-spawned INVOICE rows route through the INVOICE fixture** (`doc_class:gdoc`), not a special
  BS-line fixture `[bs]` ("BS creates virtual invoices; those invoices then self-complete via the normal
  GDoc engine. No new type needed"). `SOURCE_TYPE=BALANCE_SHEET` is metadata (a guard input `isBsLine`),
  not a routing signal. So the invoice fixture's steps just need `find_link`/`ai_extract` guarded by
  `!isBsLine` (BS lines have no file) `[lifecycle][bs]`.

**Verdict:** BS uses the same fixture format with a `doc_class` that selects a code-backed collection for
its one irreducible algorithm. Not a separate mechanism — a parameterized one.

---

## H. Incremental migration path (each step shippable, guarded by the 15-doc E2E)

The existing 15-doc E2E test (mixed types × sources → all COMPLETED at rest, 0 errors/review/missing-type
`[expected-behaviour]`) is the guardrail. Every step below is behavior-preserving and independently
shippable; run the E2E after each and gate on green. Sequence chosen so the riskiest structural change
(pipelineRunner) comes last, on top of already-proven generic engines.

**Step 0 — Snapshot + harness.** Freeze the current invoice+BS fixture VALUES by extracting them from the
live workflows into `settings.fixtures.*` rows (no engine reads them yet). Assert the E2E baseline is green
and record per-doc traces (`scripts/indox-doc-trace.py` `[runtime-attention]`). This is the diff oracle.

**Step 1 — Shared normalizer registry (no behavior change).** Extract the 5 normalizers + `has()` into a
reusable Code library used by BOTH the current selection node and (later) the new engines. Re-run E2E:
byte-identical selection expected. Ships alone.

**Step 2 — `kwExtract01` generic engine, invoice only.** Build it reading `fixture_INVOICE.kw_extract`
(rewiring the orphaned `q_*` refs so the fixture is authoritative `[given]`). Run it in **shadow**: compute
fields into `*_SHADOW` columns and diff against the live hardcoded query nodes over the E2E set. When the
diff is empty, flip invoice's `kw_extract` step to the engine and delete the hardcoded query nodes. Cap-2
concurrency preserved via `splitInBatches(2)` `[given]`. Ship.

**Step 3 — `aiExtract01` generic engine + schema-templated prompt, invoice only.** Template the invoice
prompt from `fixture_INVOICE.ai_extract.response_schema` (§D). Shadow-diff the generated prompt's output vs
the live hardcoded prompt over the E2E set (cache OFF for the diff run to force real extraction; then seed
frozen cache `[demo-onboarding §1]`). Introduce the composite cache key with `version`/`model` bust `[ai]`.
When outputs match, cut over. Ship.

**Step 4 — `select01` generic engine, invoice only.** Reproduce today's exact tiers from
`fixture_INVOICE.select`. Shadow-diff `SELECTED_*`/`SELECTION_CERTAINTY` over the E2E set until identical
`[selection]`. Cut over. Move trusted-supplier lookup to `companies` `[demo-onboarding]`. Ship.

**Step 5 — `pipelineRunner01`, invoice only (behind a flag).** Implement the runner + guard DSL (§E.2).
Add a Decide branch: `if settings.use_pipeline_runner && TYPE==='INVOICE' → pipelineRunner01, else legacy
gdocAction()`. The runner must emit the SAME ACTION sequence the legacy Decide emits for every E2E invoice
(compare action logs per doc — the traces from Step 0). When action-for-action identical across the E2E set,
default the flag on for INVOICE. Ship. (This is the one structural change; the flag makes it instantly
reversible.)

**Step 6 — Extend runner to SHIPMENT + ORDER.** Author `fixture_SHIPMENT` / `fixture_ORDER`; enable the
flag for them. SHIPMENT's fixture omits `ai_extract`, allows no-LINK via guards, and keeps `priority_sync`
with `id_field:SHIPMENT_ID` `[linking]`. ORDER gets a real pipeline instead of falling through to
`unknownTypeAction`/`MISSING_TYPE` `[lifecycle]`. E2E must still be green AND ORDER docs must now reach
COMPLETED (a strict improvement). Ship.

**Step 7 — Generic classifier `kwGlobalClassifier01`.** Build the option set from ALL fixtures'
`detect.keywords` (§B.1). Shadow-diff resolved TYPE vs the current per-type keyword nodes over the E2E set.
Cut over. Now adding a type's keywords is fixture-only. Ship.

**Step 8 — BS onto the fixture shell (`doc_class:bs`).** Author `fixture_BALANCE_SHEET` with `bs_extract`
(nested schema via the §D template) + `spawn` params; point the BS collection's `link_documents` at
`spawn.*` instead of hardcoded mappings `[bs]`. The `link_documents` ALGORITHM is unchanged — only its
inputs become fixture-sourced. E2E (which includes BS + its spawned invoices) must stay green: same line
count, same dedup, same COMPLETED `[bs]`. Ship.

**Step 9 — Config-only new type proof: `RECEIPT`.** Add ONLY the `fixture_RECEIPT` row (§A.3) via
`TABLE_UPSERT` — no workflow edit. Add 2-3 receipt docs to the E2E fixture. Assert they classify, extract,
select, and reach COMPLETED with zero engine changes. **This step is the acceptance proof of the whole
design**: a type added by config alone, guarded by the same E2E. Ship.

**Step 10 — Cleanup.** Delete the legacy `gdocAction()/bsDocAction()` branches and hardcoded query/prompt
nodes now that the flag has been on across full high-load runs (200-doc profile `[expected-behaviour]`).
Bump all fixture `version`s and re-freeze demo caches. Final E2E + high-load-to-rest.

Each step: shadow-diff or action-log-diff against Step 0's oracle → cut over only on empty diff → E2E green
→ ship. No step requires more than one engine to change at once.

---

## I. Open risks & decisions

1. **Guard DSL scope creep.** The DSL (§E.2) must stay a fixed, safe vocabulary. Risk: a future type needs a
   condition the DSL can't express, tempting arbitrary-JS guards (reintroduces code-in-config + injection
   surface). **Decision:** extend the vocabulary deliberately (add a named boolean to the engine) rather than
   allowing eval; if a type truly needs custom logic, it gets a custom `doc_class` collection (like BS), not
   a code guard. The string-boolean normalization `[expected-behaviour]` MUST live in the DSL evaluator, not
   in fixtures.

2. **`q_*` rewire correctness `[given]`.** The `q_*` settings are currently orphaned; hardcoded queries are
   authoritative. Step 2's shadow-diff is the ONLY thing proving the fixture's `$ref`-resolved queries match
   the hardcoded ones. Risk: a `q_*` row drifted from the live query. **Decision:** in Step 0, extract the
   fixtures FROM the live query nodes (not from the stale `q_*` rows), making the fixture authoritative by
   construction; retire `q_*` or keep them only as `$ref` targets that the fixture defines.

3. **apitools cap-2 under the generic engine `[given]`.** `kwExtract01` fans fields into apitools; a type
   with many KW fields could serialize slowly (single-query, cap-2). **Decision:** `splitInBatches(2)` and
   accept the serial cost; KW field counts are small (≤6). This is orthogonal to the known throughput
   bottleneck (BS-line poll limit `[api-abstraction §HIGH-LOAD]`), which stays a separate lever.

4. **AI nested vs flat schema drift `[ai]`.** Letting each fixture choose flat/nested (§D.2) is powerful but
   means the prompt template must correctly compile both. **Decision:** template supports `object` /
   `array<object>` recursively; validate the compiled `responseSchema` against Gemini structured-output
   limits at fixture-load time (fail fast on an unsupported schema), not per-doc.

5. **Selection `confirm`-mode parameterization vs today's special-cases `[selection]`.** doc_type is
   special-cased (AI==KW, no BS); reproducing it as `confirm:"id"` must exactly match. Risk: a subtle tier
   difference. **Decision:** Step 4's shadow-diff over the full E2E set is the gate; do NOT cut over on a
   non-empty diff. Keep the invoice fixture's tiers literally equal to today's until proven.

6. **BS `spawn` as params vs algorithm boundary `[bs]`.** We parameterize `link_documents` inputs but keep
   the algorithm as code. Risk: someone tries to make the algorithm itself config (split/match/branch/
   aggregate) and reintroduces fragility. **Decision:** hold the line — `spawn` is params only; the
   algorithm is a versioned handler. A genuinely different spawning behavior = a new `doc_class`, not more
   config.

7. **Multi-type classification ambiguity.** `חשבונית מס/קבלה` matches both INVOICE and RECEIPT keywords.
   Handled by `detect.priority` + `strong_keywords` (§B.1), but priorities are global tie-breaks. Risk:
   adding a type perturbs another's classification. **Decision:** the classifier shadow-diff (Step 7) + the
   E2E must catch regressions; keep `strong_keywords` narrow and priorities documented in one place.

8. **Fixture load cost under high load `[config]`.** Per-doc fixture reads must not re-hit Postgres. **Decision:**
   the KW Config Loader already loads all settings once per execution; extend its WHERE to `fixture_%` and
   redis-cache with short TTL `[config]`. Editing a fixture requires a cache bump/TTL expiry to take effect —
   acceptable (matches today's "re-run Settings WF to pick up edits" `[config]`).

9. **Publish/active gate `[expected-behaviour]`.** Five new engine sub-WFs must be active + activeVersionId or
   executeWorkflow callers throw `[n8n-executeworkflow-publish-gate]`. **Decision:** push via `bbox n8n push`
   (not raw import), verify published+active after each migration step, and keep `typeVersion:1.1` on every
   executeWorkflow node `[expected-behaviour]`.

10. **`doc_class` registry is the only non-config extension point.** Adding a type that needs a genuinely new
    engine family (beyond gdoc/bs/line) requires a new collection + registry entry — NOT config-only. **Decision:**
    this is by design and acceptable: 99% of new types are `doc_class:gdoc` (invoice/shipment/order/receipt);
    only meta-types (spawning, multi-doc) need a new class. The fixture design delivers "config-only" for the
    common case and a clean, bounded code path for the rare structural case.

---

## Summary

The engine INDOX already runs (Driver → Decide → collection → Upsert → loop `[bs]`) is the right shape; the
per-type fixture just **lifts the three hardcoded sites** (Decide branches, action handlers' mappings,
extraction/selection code) into declarative `settings.fixture_<TYPE>` rows read by five generic engines
(classifier, kw-extract, ai-extract, select, pipeline-runner). Prompts become per-type by templating from a
declared response schema (§D); selection becomes per-type by parameterizing a universal normalizer library +
scoring DSL (§E); the action sequence becomes a declarative step array with a guard DSL (§F); BS fits the
same shell via a `doc_class` that keeps its one irreducible spawn algorithm as a parameterized handler (§G).
The migration (§H) is a 10-step, shadow-diffed, E2E-guarded path where each step ships independently and the
final proof is adding `RECEIPT` by a single config row. Remaining risk is concentrated in the guard/scoring
DSL boundary and the shadow-diff cutovers — both mitigated by holding fixtures to pure data and gating every
cutover on an empty diff against the Step-0 oracle.

---

## J. Adversarial-review corrections (verified against `indoxV2Decide01` + `Selection & Scoring Logic1`)

The §A–I draft was reviewed against the live code and corrected on eight load-bearing points. These
override the draft where they conflict — apply them before implementation.

1. **Split the state machine: fixed pre-router vs per-type pipeline.** `figure_company_id` (gated by
   **`&& !!LINK`** — a linkless doc never attempts company resolution), `get_company_name`, the old-date
   guard, PAUSE, and duplicate detection run in the **main router BEFORE type dispatch**, identically for
   gdoc/bs/unknown. They are **engine pre-router**, not `pipeline.steps`/`pre_guards`. Fixtures supply only
   thresholds (e.g. `old_document_months_back`). Remove them from every fixture's steps. *(gap G1 — the
   draft's §A.2(5) pipeline is not a faithful model of the machine.)*

2. **Duplicate detection is an engine capability, not a doc-local guard.** `isDouble` uses cross-item
   stateful `byId/byHash/byCompanyShortDoc` Maps (batch-scoped) + a `LINKED_BS`-blank hash rule — irreducible
   engine state. Specify it in §B as a pre-router capability; it cannot be a fixture boolean. *(G6)*

3. **Selection schema needs hybrid modes + an explicit resync-field set.** Replace the single per-dimension
   `confirm` with **`mismatch_mode` + `confirm_mode`** (doc_type is AI==KW with no BS — not the same as the
   id/data split the draft assumes), and add **`select.resync_fields`** — the real ~14-field input to
   `SELECTION_VALUES_HASH`, distinct from `dimensions`. Without this, the Step 4/5 shadow-diffs can never go
   empty. *(G7, G13)*

4. **Unify the two spawn paths.** `extract_shipment_ids` (invoice → SHIPMENT rows) is the **same
   code-primitive-with-params as BS line-spawn**, not a flat `side_effects` entry. Model both via the
   `spawn` block (§G). Also: shipment `COMPANY_DOC_ID` resolution (`SHIPMENT_DOC_ID || parseAiShipmentIds(
   AI_SHIPMENT_IDS)[0]`) is a distinct algorithm the fixture can only *name*, not express as a field-list. *(G9, G3)*

5. **Re-order the AI cutover to protect the frozen cache + extraction quality.** Re-seed the AI cache under
   the new composite key **before** flipping; expand the prompt-templating shadow-diff **beyond** the 15-doc
   E2E (extraction quality is the top silent risk — see [[local-ocr-dpi-root-cause]], [[gemini-billing-dunning-403]]);
   preserve invoice-body **disambiguation** instructions, not just per-field `desc`. *(G11, G12)*

6. **Add per-field `guard` to `kw_extract.fields[]`.** Reproduces the live `TYPE=='INVOICE'` gate on the
   amount query (which fires only for INVOICE even inside the shared extract block). And treat the cap-2
   loop as a **1→2 concurrency change** to action-log-diff, not just value-diff. *(G2, G10)*

7. **Kill `$ref` drift.** In Step 0, overwrite the `q_*` rows FROM the live query nodes (or inline the
   queries into the fixtures and retire `q_*`). Never ship a fixture that `$ref`s an unvalidated `q_*` row —
   they are currently orphaned/possibly drifted. *(G14)*

8. **Pin the fixture-threading contract.** The Driver fetches the fixture **once** and passes it **inline**
   in every `executeWorkflow` payload to the 5 engines — never a per-engine re-fetch — to avoid a
   Sheets-429-class per-doc read fan-out under load (see [[indox-sheets-ratelimit-bottleneck]]). *(G15)*

**Net:** the design holds — lift the three hardcoded sites into `settings.fixture_<TYPE>` rows read by five
generic engines — but the **pre-router/pipeline split (1)**, the **duplicate-detection engine capability (2)**,
and the **selection hybrid-mode + resync-field schema (3)** are prerequisites without which the migration's
shadow-diffs cannot reach parity. Start migration Step 0 only after the fixture schema absorbs corrections
1–3, 6, 7.
