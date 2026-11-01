# INDOX per-type fixture refactor — final config + workflows outline

Goal: an entire document type is defined by config, executed by generic engines, **with the existing
state machine kept intact** (same actions, same order, same completion flags — just data-driven).

## 1. The config (what lives in `settings`)

| Row | Role |
|---|---|
| **`fixture_GLOBAL`** | **Base — applied FIRST to every doc.** Normalizes, classifies `TYPE`, resolves `COMPANY_ID`/`COMPANY_NAME`, and runs dedup / old-date / max-iter / pause. (Was the engine "pre-router" — now config.) |
| `fixture_INVOICE` | gdoc · id,date,amount,shipment,purchase + AI + full pipeline *(matches today)* |
| `fixture_SHIPMENT` | gdoc · id,date,purchase,shipment · no amount · no AI *(matches today)* |
| `fixture_BALANCE_SHEET` | bs · AI line-extract + verify + spawn invoices *(matches today)* |
| `fixture_ORDER` | gdoc · id,date,amount + AI **(NEW — today ORDER→MISSING_TYPE)** |
| `fixture_RECEIPT` | gdoc · id,date,amount,payment_method + AI **(NEW — config-only demo)** |
| `field_defs` | **shared** OCR query bodies (invoice_id, date, amount, purchase, shipment, order_id, receipt_id, payment_method). Fixtures reference a field by name. |
| `normalizers` | shared cleanup fns by name (`docid_last5`, `companyid_last6`, `amount_2dp`, `date_ddmmyyyy`, `id_clean`, `trim`, `uppercase`, `has`). |

A fixture is pure data: `{ base, type, doc_class, detect, kw_extract, ai_extract, select, pipeline, side_effects }`.
Files: `production/n8n/fixtures/types/fixture_*.json` + `field_defs.json` + `lib/normalizers.js`.
(`fixture_INVOICE.json` at the top level is the verbatim **Step-0 oracle**; `types/fixture_INVOICE.json` is the clean field-ref form.)

## 2. The engines (generic workflows) — the state machine, unchanged in shape

The live loop **Driver → Decide → action-collection → Upsert → loop** stays exactly as-is. Only the *inside*
of Decide changes from a hardcoded `gdocAction()/bsDocAction()` to a fixture reader. Five generic engines:

| Engine | Replaces | Reads |
|---|---|---|
| `kwGlobalClassifier01` | Figure-Type + Figure-Company | `fixture_GLOBAL` + every fixture's `detect` |
| `kwExtract01` | the 5 per-field query sub-WFs | `fixture[TYPE].kw_extract` + `field_defs` |
| `aiExtract01` | invoice_extractor / bs_ex (prompt templated from schema) | `fixture[TYPE].ai_extract` |
| `select01` | "Selection & Scoring Logic1" | `fixture[TYPE].select` + `normalizers` |
| `pipelineRunner01` | `gdocAction()/bsDocAction()` — returns ONE action/loop | `fixture_GLOBAL.pipeline` then `fixture[TYPE].pipeline` |

The Driver and the `doc_class → collection` dispatch map (`gdoc`/`bs`) are **untouched**. Handlers (the actual
`find_link` Drive search, `link_documents` spawn, `priority_sync` POST) **stay as code**; the fixture only says
*whether/when* they run and supplies their mapping.

## 3. The flow (one document)

```
doc arrives → Driver GET+lock → DECIDE:
    run fixture_GLOBAL.pipeline   (normalize · classify TYPE · company · name · dedup · old-date)   ← §pre-router, now config
        │  TYPE resolved
        ▼
    load fixture[TYPE] → pipelineRunner01 returns the next ACTION (one per loop, same guards as today)
        ▼
    dispatch ACTION by doc_class → collection handler runs it → Upsert (sets completion flag) → loop
        │  kw_extract → kwExtract01 · ai_extract → aiExtract01 · select_* → select01
        ▼
    all steps done + complete_when → mark_completed
```

BS diverges only at `doc_class:bs` (extract→verify→spawn); its spawned rows are `TYPE=INVOICE` and re-enter
the invoice fixture (guarded by `isBsLine` = no LINK/AI).

## 4. Every issue — resolved

| Issue | Resolution | Where |
|---|---|---|
| **Pre-router (company/type/dedup/old-date)** duplicated / engine-owned | Now **`fixture_GLOBAL`**, applied first to all docs — config, not code. | fixture_GLOBAL |
| **Shipment query is built at runtime** (`not_ends_with last5(COMPANY_DOC_ID)`) | Declared as `query_after_dynamic` in `field_defs`; the engine applies the append. Named, not inlined. | field_defs.SHIPMENT_DOC_ID |
| **Amount is INVOICE-gated inside a shared block** | Per-field `guard: "…&& TYPE=='INVOICE'"` on the amount field. | fixture_INVOICE kw_extract |
| **Selection is ~10% real code** (resolveDate outlier, shipment/order output rules) | `select.normalizers`/`outputs` reference **named engine fns**; `resync_fields` (the 14-field hash), `mismatch_mode`, tiers are config. | select block |
| **Duplicate detection is batch-scoped stateful** | Kept an **engine capability** (not a doc-local guard); GLOBAL lists it as `_engine` step. | fixture_GLOBAL |
| **BS line-spawn is an algorithm** | `link_documents` stays code; fixture supplies `spawn` **params** only. | fixture_BALANCE_SHEET |
| **AI prompt invoice-coupled + MD5 cache** | Prompt **templated from `response_schema`**; per-type schema; cache keyed `prefix:version:model:hash`. | ai_extract |
| **`q_*` orphaned / could drift** | `field_defs` is the single source (seeded from live once, shadow-diff validated). | field_defs |
| **ORDER unhandled** (→MISSING_TYPE) | `fixture_ORDER` + `resolveDocType` extended so ORDER/RECEIPT → `gdoc`. | fixture_ORDER |

## 5. Per-type summary

| Type | doc_class | KW fields | AI | Pipeline steps | Matches today? |
|---|---|---|---|---|---|
| GLOBAL (base) | — | — (classify+company) | fallback | 10 | yes (was pre-router) |
| INVOICE | gdoc | 5 | ✅ | 20 | yes |
| SHIPMENT | gdoc | 4 (no amount) | ❌ | 14 | yes |
| BALANCE_SHEET | bs | 0 (AI lines) | ✅ (bs_ex) | 4 + spawn | yes |
| ORDER | gdoc | 3 | ✅ | 10 | **new** |
| RECEIPT | gdoc | 4 | ✅ | 11 | **new** |

## 6. Adding / changing a type = config only

- **Add receipt** → one `fixture_RECEIPT` row + add `RECEIPT` to the AI_TYPE enum + a receipt keyword row. No workflow edit.
- **Change invoice date logic** → edit `field_defs.DOC_DATE` (shared) or the invoice fixture's field entry.
- **New field on a type** → add one `field_defs.X` row + reference it in that fixture's `kw_extract`.
- The only non-config extension point is a genuinely new **engine family** (a new `doc_class` beyond gdoc/bs) — rare (spawning meta-types).

## 7. State machine — intact

`pipelineRunner01` returns the **same action, in the same order, gated by the same `*_COMPLETED` flags** as
`gdocAction()/bsDocAction()` today — it just reads the sequence from `fixture.pipeline.steps` instead of a
hardcoded switch. `resolveDocType` and the Driver loop are unchanged (only extended to route ORDER/RECEIPT→gdoc).
Migration is shadow-diffed per engine and gated on the 15-doc E2E producing an identical action-log per doc.
