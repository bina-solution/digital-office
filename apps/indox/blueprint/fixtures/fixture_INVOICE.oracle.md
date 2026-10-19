# fixture_INVOICE — Step-0 diff oracle

Verbatim extraction from the live workflows. This is the **diff target** the migration is shadow-diffed against (design §H). Nothing reads it yet. Companion: `fixture_INVOICE.json` (the config); `ai/context/indox-per-type-fixture-architecture.md` (design).

## 1. AI extraction — VERBATIM Gemini prompt

Source: `indoxV2ExtractInvoiceGemini01.json` node `CONFIG` → assignment `prompt`. The generic `aiExtract01` must template a prompt from `ai_extract.response_schema` that reproduces this behaviour (Step 3 shadow-diff target). Note the **ordered field-priority instructions** (date pick-order, doc-id pick-order) and the credit-note→negative rule — these are behaviour the per-field `desc` alone must preserve (§J correction 5).

```text
You are an expert accounting assistant. The provided file is a business document, typically an invoice ("חשבונית מס"), receipt, or related document.

Extract the strictly required fields below from the document based on these guidelines:

1. **AI_COMPANY_ID**: The company identification number or VAT number (e.g., ח.פ, עוסק מורשה, מספר תאגיד) of the issuing company. **CRITICAL: Do NOT extract or use our company's VAT number (515561520 / הכהנים חומרי בניין בע"מ). This is the recipient's ID and must be completely ignored.** If not found, use "".
2. **AI_DOC_AMOUNT**: The total amount of the document including VAT (סה"כ כולל מע"מ / סכום כולל / סה"כ לתשלום / לתשלום). Return amounts as strings. CRITICAL: Do NOT confuse the total amount with the order number ("הזמנה"). If not found, use "". IMPORTANT: If the document is a credit note (חשבונית זיכוי / זיכוי / credit note / credit memo / חשבון זיכוי / מסמך זיכוי / ת. זיכוי / תעודת זיכוי or any similar credit indication), the amount MUST always be returned as a NEGATIVE number (e.g., "-1500.00"), regardless of how it appears in the document.
3. **AI_DOC_DATE**: The date of the document in DD/MM/YYYY format. If multiple potential Dates exist, pick according to this strict order: 1. "תאריך הפקה", 2. "תאריך חשבונית", 3. "תאריך מסמך", 4. "תאריך". Do NOT use the payment date ("תאריך תשלום") or the pay-by date ("לתשלום עד"). If not found, use "".
4. **AI_DOC_ID**: The full document number. If multiple potential IDs exist, pick according to this strict order: 1. "חשבונית מס", 2. "מס' חשבונית", 3. "מסמך", 4. "מספר מסמך", 5. "מסמך חיוב". If not found, use "".
5. **AI_ORDER_IDS**: Purchase Order ID: For documents of type INVOICE, extract the purchase order number as it appears in the customer's records (e.g., "מספר הזמנת לקוח", "מס' הזמנת מקור", "הזמנת רכש", etc.) rather than the issuer's internal order reference. If multiple order numbers are listed, extract only the first one. If not found, use "".
6. **AI_SHIPMENT_IDS**: The linked shipment document numbers (מספר תעודת משלוח / ת. משלוח). Extract all unique shipment numbers and return them as an array of strings. Do not repeat the same number. If not found, return an empty array [].
7. **AI_TYPE**: Identify the type of the document and classify it into exactly one of the following labels:
   - If the document is an invoice or bill, return INVOICE.
   - If it is a shipping document or delivery note, return SHIPMENT.
   - If it is a financial balance sheet (including screenshots of balance sheets), return BALANCE_SHEET.
   - If it is a purchase order, return ORDER.
   - If the document is irrelevant, return IRRELEVANT.

Strictly return ONLY the JSON object with the following structure. Do not use null values; use an empty string "" for missing string values. Do not include any explanations, apologies, or conversational text outside of the JSON structure. Ensure that any double quotes that are part of the string data itself are properly escaped with a backslash.

{
  "AI_COMPANY_ID": "string" | "",
  "AI_DOC_AMOUNT": "string" | "",
  "AI_DOC_DATE": "DD/MM/YYYY" | "",
  "AI_DOC_ID": "string" | "",
  "AI_ORDER_IDS": "string" | "",
  "AI_SHIPMENT_IDS": ["string"] | [],
  "AI_TYPE": "INVOICE" | "SHIPMENT" | "BALANCE_SHEET" | "ORDER" | "IRRELEVANT"
}
```

### AI cache (LIVE, faithful)

- key: `invoice:{crypto_hash(binary)}`  (hash algo LIVE = **UNSPECIFIED in node params -> n8n crypto node DEFAULT (MD5), NOT sha256**)

- LIVE cache key does NOT include version or model -> does NOT invalidate on prompt/model change. (Draft proposed sha256 + version/model bust; PROPOSED change, not live.)

## 2. Selection tiers (LIVE, exact — Step 4 diff target)

- `idMismatch` → score **0** (ID_MISMATCH)

- `aiBsMatch` → score **100** (AI+BS)

- `!dataMismatch && allFourConfirmed` → score **100** (OTHER)

- `!dataMismatch` → score **50** (OTHER)

- `default` → score **0** (OTHER)


## 3. Pipeline action sequence (LIVE gdocAction order — Step 5 action-log-diff target)

`restart_gdoc → get_short_doc_id → update_name → check_from_office → find_link → update_status_missing_link → no_action_link_not_found → get_api_tools_id → query_invoice_id → query_doc_date → query_doc_total_amount → query_purchase_id → query_shipment_id → extract_invoice_google_ai → update_company_doc_id → action_extract_shipment_ids → select_invoice_values → action_priority_sync → mark_completed → no_action_already_completed`


> Per design §J: the global classifier + `figure_company_id`(gated by `!!LINK`)/`get_company_name`/dup-detection/old-date run in the ENGINE PRE-ROUTER before this gdoc sequence — they are intentionally NOT in `pipeline.steps`.


## 4. Faithfulness & drift notes

- Completion-flag names are the LIVE names (INVOICE_ID_COMPLETED, DOC_DATE_COMPLETED, DOC_TOTAL_AMOUNT_COMPLETED, PURCHASE_ID_COMPLETED, SHIPMENT_ID_COMPLETED), NOT the draft's QUERY_*_COMPLETED.

- Pre-router steps (figure_company_id, get_company_name, old-date, duplicate, pause, max-iter) are ENGINE PRE-ROUTER and are recorded under pipeline.pre_router (NOT pipeline.steps) per architecture doc J.1.

- Each KW query is INLINED (verbatim) rather than $ref'd to a q_* row, per J.7. The seed q_* rows were verified byte-identical to these nodes (see oracle DRIFT section).

- AI response_schema is DERIVED from the live prompt (CONFIG node) + the live JSON_INVOICE_EXTRACTION json_schema (Config1 node). LIVE AI_TYPE enum has NO 'RECEIPT'.


### q_* vs hardcoded drift

The fixture **inlines the hardcoded query bodies** (`query_after`/`query_below` per field) rather than `$ref`-ing the `q_*` settings rows — per §J correction 7, avoiding shipping an unvalidated `$ref`. The `q_*` rows remain orphaned; retire or overwrite-from-live in a later step.
