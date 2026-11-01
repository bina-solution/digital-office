
## 2026-08-17 09:35 — TWO-POINT RULE FULLY ENFORCED (owner order: fold everything, cleanup, proof)
All four out-of-band extractors are gone from decide, live:
1. **figure_company_offline → MOVED INTO BASE**: BaseDocEx01 gained a NAME input (callers
   updated), a 'NAME Company Match (Offline)' PG node (B31 query ported VERBATIM — anchored
   prefix, ≥5 chars, unambiguous only, longest wins), and Select Base uses it as the FILL-ONLY
   third company leg (only when LOCAL+AI both null). Global01's action lane physically removed
   (last switch rule — no renumbering risk).
2. **figure_document_type REMOVED from decide**: TYPE resolves at base only (LOCAL JQ + Gemini
   legs + pick). unknownTypeAction now goes straight to MISSING_TYPE.
3. **extract_invoice_google_ai standalone fallback REMOVED** (Global01 + GDoc + Ship ×2):
   per-type posts to the same invoice_extractor webhook and stamps AI_EXTRACTION_COMPLETED
   itself (2026-08-11 note); base has its own embedded Gemini leg.
4. **action_extract_shipment_ids REMOVED** (GDoc + Ship): it was the re-branded
   query_shipment_id lane calling indoxV2QueryShipmentId01. Per-type emits LOCAL_/AI_SHIPMENT_IDS;
   Selection & Scoring PREFERS AI_SHIPMENT_IDS over the lane's field; the link path parses
   AI_SHIPMENT_IDS directly; EXTRACT_SHIPMENT_COMPLETED's only readers were the removed gates.
Base stamps FIGURE_COMPANY_COMPLETED + FIGURE_TYPE_COMPLETED unconditionally (both sites).
PROOF EXECUTED: (1) matcher resolves 'Fig Ord Co חשבונית 123.pdf' → company_id=511234567,
candidates=1; (2) restarted MISSING_COMPANY_ID doc driven live → decide dispatched ONLY
update_status_missing_company (zero figure/AI/shipment dispatches). Full remaining
extraction-action vocabulary: extract_base_doc, extract_per_type, extract_balance_sheet (+
select_invoice_values selection, get_* derivations) — the two points and nothing else.
CORPSE PASS still owed (physical strip, needs switch renumbering care): 5 query_* lanes in
GDoc+Ship, Query{TotalAmt,DocDate,PurchaseId,ShipmentId}01 + FigureCompanyId01 +
FigureDocType01 workflows (all dead-but-active; the Figure pair must stay active until their
dead lanes are stripped — publish-validation references).
ERROR-HANDLER STORM explained: 1,194 canceled indoxV2UploadApiTools01 executions (its OWN
executionTimeout=420 — third tight timeout, now 3600) fired errorHandler once each; the
"crazy" activity after was queue backlog draining. Generation stopped: 0 new cancellations.
