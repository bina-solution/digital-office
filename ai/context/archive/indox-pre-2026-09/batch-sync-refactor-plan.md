# INDOX batch-sync refactor plan (2026-06-23)

Goal: make the document SYNC layer (discover → OCR-analyze → name → upsert) fully batch-correct +
efficient, with ONE source of truth for naming, decoupled from Drive/Sheets/Gmail. Implement step-by-step,
verify each. Authored from a deep Plan-agent analysis.

## Naming bug root cause (the `unknown-11644` signature)
- `Mannual Documents Namer` rD3hoAVD83QPxFfS is the GDoc-sync processor (Get Files List → Loop Over Items
  splitInBatches(1) → Verify → Download → Map settings → **Process Document** (executeWorkflow mode=each,
  onError=continueErrorOutput, sub dy664984) → **Filename** (`{{$json.company_name||"unknown"}}-{{$json.document_id?.padStart(5,'0').slice(-5)||'unknown'}}.ext`)
  → Rename File → Move → **Pre Log - Rename End** (code) → **Call 'Batch UPSERT'**).
- BUG: `Pre Log - Rename End` & `Call 'Batch UPSERT'` read `$('Filename').item` / `$('Process Document').item`
  AFTER the Rename/Move executeWorkflow boundary → paired-item linkage breaks → resolves to item-0's value →
  every row stores item-0's `document_id` (=11644) + empty company → `unknown-11644`.
- DEEPER: TWO sources of truth for the short id — sync NAME uses OCR `document_id`; main pipeline
  (RSlxF4ztnpwSTdgE/sv5xxRBVGxvV0kXx) derives SHORT_DOC_ID from COMPANY_DOC_ID via `slice(-5).padStart(5,'0')`.

## Per-item anti-patterns inventory (fix all)
- rD3hoAVD83QPxFfS: `If Sucsessful` ($('Process Document').item.is_ok), `Pre Log - Rename End`
  ($('Process Document').item, $('Filename').item), `Call 'Batch UPSERT'` ($('Process Document').item.purchase_id,
  $('Download File').item.createdTime) — all stale across sub-call boundaries.
- dy664984 `Map Extractions`: 4 chained `$('...').item` reads — safe only because invoked mode=each (1 item); fragile.
- AZXF28EaGfEQjZBx (BS): `$('Loop Over Pairs').first()` inside loop (item-0-applied-to-all); `$('Start').item` post sub-calls.
- indoxGmailDocDownloader01 (Gmail Documents Downloader) `Output Filename`: same `company-doc` construction + `.item` merge fragility.
- indoxDocBatchUpsert01 Batch Upsert is BATCH-SAFE (reads `.all()`); keep as the upsert sink.

## Per-item-correctness pattern (the rule)
Never read a per-item value via `$('Node').item`/`.first()` across an executeWorkflow/driveApi/HTTP boundary.
Instead: (1) pass keys INTO sub-wfs + read them back; (2) re-join sub-call output with carried context via a
Merge (by position/key); (3) `$('Start').first()` ONLY for loop-invariant settings (sanctioned); (4) for
mode=each sub-wfs, consume the single returned item via `$json` downstream, not `.item` re-reads.

## Ordered change list (smallest first, verify each)
1. rD3hoAVD83QPxFfS `Filename`: derive short id from the canonical id (carry company_doc_id or align OCR
   document_id) using `slice(-5).padStart(5,'0')`; keep `company_name||"unknown"`. Verify: מצרפלס/CIMT251022660 → `מצרפלס-22660`.
2. rD3hoAVD83QPxFfS `Call 'Batch UPSERT'` mapping: replace `$('Process Document').item`/`$('Download File').item`
   with values carried on `$json`. Verify: multi-file batch → each row's COMPANY_DOC_ID/SHORT_DOC_ID/NAME consistent + distinct.
3. rD3hoAVD83QPxFfS `Pre Log - Rename End` + `If Sucsessful`: read from merged `$json`, not `.item`. Verify: log rows 1:1, no repeated document_id.
4. Insert Merge(by position) after Process Document (and after Rename/Move) to formalize the carried record; remove remaining `.item`. Verify: 10+ files, no shared document_id.
5. indoxGmailDocDownloader01 `Output Filename` + Code merge: same short-id fix + harden. Verify: gmail naming == gdoc naming.
6. AZXF28EaGfEQjZBx (BS): `$('Loop Over Pairs').first()` → per-item; post-sub-call `$('Start').item` → merged `$json`. Verify: BS per-line SHORT_DOC_ID.

## Efficiency pass
- dy664984: 3-4 separate apitools HTTP calls (invoice/shipment/purchase/company) per doc — batch/combine into one documentJsonQuery; fold `Call 'Figure Document COMPANY_ID'` into the OCR result (one sub-wf spin-up instead of two).
- Logging: switch per-item `Log Document Process` (mode=each) to one batched call at end of run.
- `Get Files List` limit:100 with no seen-hash filter → add pre-OCR "already in incoming_documents by hash" short-circuit so 5-min reruns don't re-OCR unmoved files.
- Settings: pass a settings handle/id + load once instead of stringifying the big company map into every invocation.

## Files
rD3hoAVD83QPxFfS (Namer/GDoc processor), dy664984 (Process Document/OCR), indoxGmailDocDownloader01 (Gmail Docs
Downloader), AZXF28EaGfEQjZBx (BS processor), indoxDocBatchUpsert01 (Batch Upsert sink).
