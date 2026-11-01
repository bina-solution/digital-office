import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : SelectType01 — per-type selection + scoring
// Nodes   : 5  |  Connections: 4
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// RowIn                              executeWorkflowTrigger
// LoadCompanies                      postgres                   [onError→regular] [creds] [alwaysOutput] [executeOnce]
// RestoreRow                         code
// Select                             code
// Return_                            set
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// RowIn
//    → LoadCompanies
//      → RestoreRow
//        → Select
//          → Return_
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Row In":{"main":[[{"node":"Load Companies","type":"main","index":0}]]},"Load Companies":{"main":[[{"node":"Restore Row","type":"main","index":0}]]},"Restore Row":{"main":[[{"node":"Select","type":"main","index":0}]]},"Select":{"main":[[{"node":"Return","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-25T13:36:11.806Z","createdAt":"2026-08-25T13:36:11.806Z","role":"workflow:owner","workflowId":"SelectType01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'SelectType01',
    name: 'SelectType01 — per-type selection + scoring',
    active: true,
    isArchived: false,
    tags: ['app:indox'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class Selecttype01PerTypeSelectionScoringWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'selt-in-01',
        name: 'Row In',
        /*__n8n__*/ notes: "THE WHOLE ROW ARRIVES HERE. Selection is a pure function of the document row: every version of every datum (LOCAL_*, AI_*, BS_LINE_*) plus the row's own context (TYPE, NAME, SOURCE_TYPE, COMPANY_ID) and the values it already holds. It reads no file, calls no model and touches no OCR -- which is what makes re-selection cheap enough to run again whenever a version changes.",
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, 0],
    })
    RowIn = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'selt-companies-01',
        name: 'Load Companies',
        /*__n8n__*/ notes: "The trusted-supplier list, read DIRECTLY. This used to call indoxSettings01 with load_companies, which walks all 1,180 companies and builds nine lookup maps to answer one yes/no question — measured over 15 runs before this change: 1,591ms of a 1,905ms selection, 84% of every single one. A selection is otherwise 142ms of arithmetic. The query below returns only companies that actually declare trusted source types, which is the one thing the override needs. NOTE what that measurement also exposed: indoxSettings01 gates the list on `parseInt(SELECTION_CERTAINTY)===100`, and the companies table HAS NO SUCH COLUMN (verified: 1,180 rows, 0 with the key anywhere including `extra`) — so trusted_suppliers has always been an empty array and the override has never once fired. The gate here is a non-empty TRUSTED_SOURCE_TYPES, which is what that column exists to say. It stays inert today (0 companies declare one) and starts working the moment the operator fills it in.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [224, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
        executeOnce: true,
    })
    LoadCompanies = {
        operation: 'executeQuery',
        query: `=-- Companies that declare a trusted source type, and the identifiers they are known by.
-- Identifier construction mirrors indoxSettings01/'Companies' (the three id fields, minus the
-- 'פריוריטי' blacklist) so this and the settings map cannot drift on identity.
-- [multi-instance 2026-08-28] Schema resolved from __instance; absent resolves to public, which
-- is today's behaviour and becomes a loud failure once the compatibility views are dropped.
-- [fixed certainty 2026-09-02, owner Decision 5] SELECTION_CERTAINTY is the company's own
-- floor for the corroboration score (0-100); a row that declares one is loaded whether or not it
-- also declares trusted source types.
SELECT c."מזהה 1" AS id1, c."מזהה 2" AS id2, c."שם ספק מפריוריטי" AS id3,
       c."TRUSTED_SOURCE_TYPES" AS sts,
       c."SELECTION_CERTAINTY" AS certainty
FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('SelectType01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.companies c
WHERE coalesce(btrim(c."TRUSTED_SOURCE_TYPES"), '') NOT IN ('', '[]')
   OR c."SELECTION_CERTAINTY" IS NOT NULL;`,
        options: {},
    };

    @node({
        id: 'selt-restore-01',
        name: 'Restore Row',
        /*__n8n__*/ notes: "'Load Companies' REPLACES the item stream with the settings payload, so the document rows are re-emitted from the trigger here. Same idiom as 'Restore Router Payload' in indoxV2ActionsGlobal01 and 'Attach Action History' in the driver.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [448, 0],
    })
    RestoreRow = {
        jsCode: `return $('Row In').all();
`,
    };

    @node({
        id: 'selt-select-01',
        name: 'Select',
        /*__n8n__*/ notes: "ONE selector for every per-type datum. Ported VERBATIM from InvoiceDocEx01/'Select' (the value picks), BsDocEx01/'Select (BS)' (the AI-led balance-sheet reversal) and indoxV2ActionsGDoc01/'Selection & Scoring Logic1' (the corroboration score, the report and the trusted-supplier override) so one document's answer has exactly ONE author. Three deliberate differences from the code it replaces, each recorded inline: BS_LINE_* is a real leg (fill-only for values, full leg for the score), the C11 junk-id rejector's three broken regexes are fixed, and SELECTION_VALUES_HASH is finally computed -- over the POST-write state, which is what makes the re-selection gate converge instead of oscillating.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [672, 0],
    })
    Select = {
        jsCode: `// SelectType01/Select -- the per-type selector. PURE: row in, decision out.
// No file, no OCR, no model. Everything here is a function of columns the row already holds,
// which is the property that lets the state machine re-run it for pennies when a late
// BS_LINE_* arrives from an aging report.

const has = v => v !== null && v !== undefined && String(v).trim() !== '';
// 'unknown' is a NON-ANSWER everywhere in this schema (docBaseDecide's isBlank says so, and so
// does BaseDocEx01/'Select Base'). The scorer's own has() folded it in; keep both meanings
// separate and explicit rather than having two subtly different emptiness tests.
const hasReal = v => has(v) && String(v).trim().toLowerCase() !== 'unknown';
const canonAmount = v => String(v).replace(/[\\s,]/g, '');
// An empty JSON array is a NON-ANSWER: the AI leg returns the literal string '[]' when it finds
// no shipment/order ids and 2,213 live rows carry it.
const realList = v => (has(v) && String(v).trim() !== '[]') ? v : null;

// pick() -- ported verbatim from InvoiceDocEx01. 'prefer' exists only because balance sheets are
// AI-led (BsDocEx01's deliberate reversal); it is a PARAMETER, not a second copy of the function.
// 'canon' touches ONLY the equality test, so it can change a provenance LABEL but never a value.
function pick(local, ai, prefer, canon) {
  const l = has(local) ? String(local).trim() : null;
  const a = has(ai) ? String(ai).trim() : null;
  if (l && a) {
    if (canon ? canon(l) === canon(a) : l === a) return { val: l, source: 'AGREE' };
    return prefer === 'AI'
      ? { val: a, source: 'DISAGREE_PREFER_AI' }
      : { val: l, source: 'DISAGREE_PREFER_LOCAL' };
  }
  if (prefer === 'AI') {
    if (a) return { val: a, source: 'AI_ONLY' };
    if (l) return { val: l, source: 'LOCAL_ONLY' };
  } else {
    if (l) return { val: l, source: 'LOCAL_ONLY' };
    if (a) return { val: a, source: 'AI_ONLY' };
  }
  return { val: null, source: 'NONE' };
}

// ── normalisers, ported verbatim from 'Selection & Scoring Logic1' ──
function normalizeDate(val) {
  if (!hasReal(val)) return null;
  let s = String(val).trim().replace(/\\s+/g, '');
  let day, month, year, match;
  if (/^\\d{5}(\\.\\d+)?$/.test(s)) {
    const dateObj = new Date(Math.round((parseFloat(s) - 25569) * 86400 * 1000));
    day = String(dateObj.getDate()).padStart(2, '0');
    month = String(dateObj.getMonth() + 1).padStart(2, '0');
    year = dateObj.getFullYear();
  } else if (match = s.match(/^(\\d{1,2})[\\/\\.\\-](\\d{1,2})[\\/\\.\\-](\\d{2,4})$/)) {
    day = match[1].padStart(2, '0');
    month = match[2].padStart(2, '0');
    year = match[3].length === 2 ? '20' + match[3] : match[3];
  } else if (match = s.match(/^(\\d{4})[\\/\\.\\-](\\d{1,2})[\\/\\.\\-](\\d{1,2})$/)) {
    year = match[1]; month = match[2].padStart(2, '0'); day = match[3].padStart(2, '0');
  } else {
    const parsed = new Date(s);
    if (isNaN(parsed.getTime())) return s;
    day = String(parsed.getDate()).padStart(2, '0');
    month = String(parsed.getMonth() + 1).padStart(2, '0');
    year = parsed.getFullYear();
  }
  return day + '/' + month + '/' + year;
}
function normalizeAmount(val) {
  if (!hasReal(val)) return null;
  const num = parseFloat(String(val).replace(/[^\\d.-]/g, ''));
  return isNaN(num) ? null : num.toFixed(2);
}
// [six-digit collision 2026-09-02, owner Decision 5] The company key is the FULL significant digit
// string, not the last six. Truncating to six let two unrelated companies whose numbers share a
// tail read as the same company — in the corroboration test (a false "agree") and in the trusted
// lookup (the wrong company vouched for). Leading zeros are dropped so '050-000-0016' and
// '514855800' still meet, which is the only tolerance the truncation was buying.
function normalizeCompanyID(val) {
  if (!hasReal(val)) return null;
  const digits = String(val).replace(/\\D/g, '').replace(/^0+/, '');
  return digits || null;
}
function normalizeDocID(val) {
  if (!hasReal(val)) return null;
  return String(val).replace(/\\D/g, '').slice(-5).padStart(5, '0');
}
function normalizeDocType(val) {
  if (!hasReal(val)) return null;
  return String(val).trim().toUpperCase();
}
function isEmptyOrEmptyArray(val) {
  if (!hasReal(val)) return true;
  const s = String(val).trim();
  return s === '[]' || s === '';
}
function extractFirstShipmentID(val) {
  if (!hasReal(val)) return null;
  const s = String(val).trim();
  try {
    const arr = JSON.parse(s);
    if (Array.isArray(arr) && arr.length > 0) return String(arr[0]).trim();
  } catch (e) {}
  if (s.indexOf(',') >= 0) return s.split(',')[0].trim();
  return s.replace(/^\\[|\\]$/g, '').replace(/"/g, '').trim() || null;
}

// The 180-day outlier rule: when the candidates disagree by more than half a year, prefer a
// non-future one rather than the newest. Ported verbatim.
function resolveDate(dateAI, dateBS, dateKW) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const SIX_MONTHS_MS = 180 * 24 * 60 * 60 * 1000;
  function parseDDMMYYYY(str) {
    if (!str) return null;
    const parts = String(str).split('/');
    if (parts.length !== 3) return null;
    const dt = new Date(Number(parts[2]), Number(parts[1]) - 1, Number(parts[0]));
    return isNaN(dt.getTime()) ? null : dt;
  }
  const candidates = [
    { label: 'AI', val: dateAI },
    { label: 'BS', val: dateBS },
    { label: 'KW', val: dateKW },
  ].filter(c => hasReal(c.val))
   .map(c => ({ label: c.label, val: c.val, dt: parseDDMMYYYY(c.val) }))
   .filter(c => c.dt !== null);
  if (candidates.length === 0) return null;
  if (candidates.length === 1) return candidates[0].val;
  const uniqueVals = [];
  candidates.forEach(c => { if (uniqueVals.indexOf(c.val) < 0) uniqueVals.push(c.val); });
  if (uniqueVals.length === 1) return uniqueVals[0];
  candidates.sort((a, b) => b.dt - a.dt);
  const oldest = candidates[candidates.length - 1];
  const gap = candidates[0].dt - oldest.dt;
  if (gap > SIX_MONTHS_MS) {
    const nonFuture = candidates.filter(c => c.dt <= today);
    if (nonFuture.length > 0) return nonFuture[0].val;
    return oldest.val;
  }
  return dateAI || dateBS || dateKW;
}

// ── the ledger breaks a tie between the two engines ──
// When LOCAL and AI disagree, the answer is decided by a fixed preference order and the third
// reading is ignored -- even though the supplier's own ledger line is sitting on the same row
// saying which of the two is right. Two independent sources agreeing is better evidence than a
// preference order, so when BS_LINE matches one of them (compared on the canonical form, never the
// raw string) that one wins. Fires ONLY on a genuine disagreement, so it can never change a row
// where the engines already agree or where only one of them answered.
// Real example, doc_mspco59ao08t0n: LOCAL 9,099.00 vs AI 8666.00, ledger 8666 -- the preference
// order wrote 9,099.00 over two sources that agree with each other.
function ledgerPick(localVal, aiVal, p, bs, canon) {
  if (!p || (p.source !== 'DISAGREE_PREFER_LOCAL' && p.source !== 'DISAGREE_PREFER_AI')) return p;
  if (!hasReal(bs)) return p;
  const c = canon || ((v) => String(v == null ? '' : v).trim());
  const b = c(bs);
  if (b && c(localVal) === b) return { val: String(localVal).trim(), source: 'LOCAL_AGREES_LEDGER' };
  if (b && c(aiVal) === b) return { val: String(aiVal).trim(), source: 'AI_AGREES_LEDGER' };
  return p;
}

// The source-type vocabulary, in ONE place. The trusted list and the document being judged must
// be normalised the same way or the comparison silently never matches -- which, given the list has
// always been empty, is a failure nobody would have noticed.
function normSource(v) {
  const s = String(v == null ? '' : v).toUpperCase();
  return s.indexOf('DRIVE') >= 0 ? 'DRIVE' : (s.indexOf('GMAIL') >= 0 ? 'GMAIL' : s.trim());
}

// The trusted-supplier list, built once for the whole batch from the rows 'Load Companies' returns.
// Identifier expansion is indoxSettings01's, verbatim: each of the three id fields becomes an entry
// (skipping the 'פריוריטי' blacklist), crossed with every declared source type, and the company id
// is compared on its last six digits.
let TRUSTED = [];
// [fixed certainty 2026-09-02, owner Decision 5] company key -> the FIXED certainty the operator
// set on the company row (companies.SELECTION_CERTAINTY). Applied below as
// max(computed corroboration, fixed): a supplier the operator vouches for at 100 needs no
// machine corroboration; one vouched for at 70 is never scored under 70. The old membership
// list (TRUSTED_SOURCE_TYPES + a gate over a column that never existed) is subsumed by this
// number and kept only as the source-typed override it always was.
const FIXED = {};
try {
  for (const it of $('Load Companies').all()) {
    const r = it.json || {};
    let sts = [];
    try {
      const p = JSON.parse(r.sts || '[]');
      sts = Array.isArray(p) ? p : (p ? [p] : []);
    } catch (e) {
      sts = String(r.sts || '').split(/[,;]/).map(s => s.trim()).filter(Boolean);
    }
    const fixed = (r.certainty === null || r.certainty === undefined || r.certainty === '') ? null : Number(r.certainty);
    for (const idf of [r.id1, r.id2, r.id3]) {
      if (!idf || String(idf).indexOf('פריוריטי') >= 0) continue;
      // the SAME key the document side uses (normalizeCompanyID): full digits, no leading zeros
      const cid = normalizeCompanyID(idf);
      if (!cid) continue;
      for (const st of sts) TRUSTED.push({ companyId: cid, sourceType: normSource(st) });
      if (Number.isFinite(fixed)) FIXED[cid] = Math.max(FIXED[cid] || 0, Math.min(100, Math.max(0, fixed)));
    }
  }
} catch (e) { TRUSTED = []; }

// The 14 selection inputs, in the order fixture_INVOICE.json's resync_fields declares them.
// THE HASH IS COMPUTED OVER THE POST-WRITE STATE. This is the whole reason the designed
// re-selection trigger was never safe to switch on: six of the fourteen fields are values this
// very node writes, so a hash taken over the INPUT row differs from the row that exists one
// millisecond later -- decide would see a mismatch on the very next sweep, re-dispatch the same
// action with no restart between, and the dup guard would (correctly) raise DOUBLE ACTION.
// 'eff' resolves each field the way the upsert will: indoxApi01's clean() drops null and '', so a
// field this node declines to write KEEPS the value already on the row.
function selectionHash(row, out) {
  const eff = (k) => (out[k] !== undefined && out[k] !== null && String(out[k]) !== '')
    ? out[k] : row[k];
  const vals = [
    row.AI_COMPANY_ID, row.COMPANY_ID,
    row.AI_DOC_ID, eff('DOC_ID'),
    row.AI_DOC_DATE, row.BS_LINE_DATE, eff('DOC_DATE'),
    row.AI_DOC_AMOUNT, row.BS_LINE_AMOUNT, eff('DOC_TOTAL_AMOUNT'),
    row.AI_SHIPMENT_IDS, row.AI_ORDER_IDS,
    eff('SHIPMENT_DOC_ID'), eff('PURCHASE_ID'),
  ];
  return vals.map(v => (v === null || v === undefined) ? '' : String(v)).join('|');
}

return $input.all().map(item => {
  const d = item.json || {};
  const docType = String(d.TYPE || 'INVOICE').toUpperCase();
  const isShipment = docType === 'SHIPMENT';
  const isBs = docType === 'BALANCE_SHEET';
  // Balance sheets are AI-led with the local leg supplementing 'where it helps' -- the owner's
  // framing, implemented in BsDocEx01 as a reversed tie-break. Everything else is LOCAL-led.
  const prefer = isBs ? 'AI' : 'LOCAL';

  const out = { ID: d.ID };

  const idPick     = pick(d.LOCAL_DOC_ID,     d.AI_DOC_ID,     prefer);
  const datePick   = pick(d.LOCAL_DOC_DATE,   d.AI_DOC_DATE,   prefer);
  const amountPick = pick(d.LOCAL_DOC_AMOUNT, d.AI_DOC_AMOUNT, prefer, canonAmount);
  const shipPick   = pick(realList(d.LOCAL_SHIPMENT_IDS), realList(d.AI_SHIPMENT_IDS), prefer);
  const purchPick  = pick(realList(d.LOCAL_ORDER_IDS),   realList(d.AI_ORDER_IDS),     prefer);

  // [A1 per-type date guard 2026-08-13] An AI-only per-type date must not overwrite the date base
  // resolved from a local read -- measured: base_had_LOCAL x per-type AI_ONLY = 219 corruptions of
  // 5,877, every other source 0.00%. Returning null keeps DOC_DATE out of the upsert entirely.
  const ptDate = (p) => (p && p.source === 'AI_ONLY') ? null : (p ? p.val : null);

  const datePickL   = ledgerPick(d.LOCAL_DOC_DATE,   d.AI_DOC_DATE,   datePick,   d.BS_LINE_DATE,   normalizeDate);
  const amountPickL = ledgerPick(d.LOCAL_DOC_AMOUNT, d.AI_DOC_AMOUNT, amountPick, d.BS_LINE_AMOUNT, normalizeAmount);

  let dateVal = ptDate(datePickL);
  let dateSource = datePickL.source;
  let amountVal = amountPickL.val;
  let amountSource = amountPickL.source;

  // ── the ledger leg ──
  // BS_LINE_DATE / BS_LINE_AMOUNT are this document's line as the SUPPLIER's own ledger records
  // it, written onto the row by the aging-report linker (indoxV2ActionsBS01, 'Build: Call
  // Incoming Document Batch Update'). It is a third independent reading of the same two data, and
  // until now nothing in the selection path could see it -- it fed the corroboration score in the
  // legacy stage and nothing else.
  // FILL-ONLY for the VALUE: it supplies a date or an amount only where both engines came back
  // empty, so it can never overwrite something read off the document itself. It is a full leg for
  // the SCORE below, where its whole value lies -- an independent source agreeing with the AI is
  // exactly what 'aiBsMatch' certifies at 100.
  if (!has(dateVal) && hasReal(d.BS_LINE_DATE)) {
    dateVal = String(d.BS_LINE_DATE).trim();
    dateSource = 'BS_LINE_ONLY';
  }
  if (!has(amountVal) && hasReal(d.BS_LINE_AMOUNT)) {
    amountVal = String(d.BS_LINE_AMOUNT).trim();
    amountSource = 'BS_LINE_ONLY';
  }

  // DOC_DATE IS A BASE FIELD, AND THIS POINT ONLY FILLS IT. A1 named the doctrine ("DOC_DATE is a
  // BASE field") but enforced it for exactly one case, the AI_ONLY per-type read. The other case
  // is just as real and 40x more common: LOCAL_DOC_DATE and AI_DOC_DATE are SHARED columns -- base
  // writes them and so does per-type -- so on a balance sheet, whose per-type tie-break is
  // deliberately AI-led, this selector re-decided base's own two legs under the opposite rule and
  // replaced base's answer. Measured over a 400-row cohort before this line existed: 124 rows
  // changed date, every one of them a BS row where the stored value was the LOCAL leg. Writing
  // only into an empty column keeps base the single author of the date and leaves the ledger leg
  // free to fill one where base found none.
  // [uniform DOC_DATE 2026-08-26, owner order] Select is the only writer of DOC_DATE, so it is
  // also the only place that can guarantee its shape -- and the legs do not share one. LOCAL_/AI_
  // are dd/mm/yyyy while BS_LINE_DATE, the leg this very line feeds from, is yyyy-mm-dd; a value
  // that has round-tripped through the derived doc_date_norm column comes back as a full ISO
  // timestamp. Map Request assumes dd/mm/yyyy and truncates anything longer to "2026-00Z", which
  // is what the ERP was being sent. normalizeDate is the normaliser this node already carries;
  // it returns the input untouched when it cannot parse it, so this can never erase a real date.
  if (has(dateVal) && !has(d.DOC_DATE)) out.DOC_DATE = normalizeDate(dateVal) || dateVal;
  else if (has(d.DOC_DATE)) dateSource = 'BASE_KEPT';
  // Balance sheets file their own total under TOTAL_AMOUNT; every other type uses
  // DOC_TOTAL_AMOUNT. Two columns, two meanings -- schema.sql :53 / :55.
  if (has(amountVal)) { if (isBs) out.TOTAL_AMOUNT = amountVal; else out.DOC_TOTAL_AMOUNT = amountVal; }

  // SHIPMENT_DOC_ID HOLDS ONE ID, NOT A LIST. The extractor legs answer with a JSON array
  // (LOCAL_SHIPMENT_IDS / AI_SHIPMENT_IDS are lists by construction) and the column that receives
  // the pick is single-valued -- the legacy scorer unwrapped it with extractFirstShipmentID and
  // the extractor did not, which is why a raw '["203SH26003560"]' could reach the column at all.
  // Measured over a 400-row cohort before this line existed: 92 rows differed from the stored
  // value by exactly the brackets and quotes. Unwrap once, here, where the value is decided.
  if (!isBs) {
    if (has(shipPick.val))  out.SHIPMENT_DOC_ID = extractFirstShipmentID(shipPick.val);
    if (has(purchPick.val)) out.PURCHASE_ID = extractFirstShipmentID(purchPick.val);
  }

  let shipSource = shipPick.source;
  // [gap-1] SHIPMENT-ONLY, FILL-ONLY. ShipmentDocEx01 files the shipment's own id under
  // LOCAL_DOC_ID and never emits LOCAL_SHIPMENT_IDS, so the pick above is permanently NONE on the
  // local leg. Engages only when both provenance sources are blank AND the row has no
  // SHIPMENT_DOC_ID yet. INACTIVE on INVOICE/ORDER, where SHIPMENT_DOC_ID means the LINKED
  // shipment and a document's own id must never be written into it.
  if (isShipment && !shipPick.val && !realList(d.SHIPMENT_DOC_ID) && has(d.LOCAL_DOC_ID)) {
    out.SHIPMENT_DOC_ID = String(d.LOCAL_DOC_ID).trim();
    shipSource = 'LOCAL_DOC_ID_FALLBACK';
  }

  // ── dimensions: three independent readings per datum ──
  // AI = the model's answer, BS = the supplier's ledger line, KW = the local query engine.
  // KW READS THE LOCAL LEG, NOT THE STORED FINAL. The legacy scorer read COMPANY_ID / DOC_ID /
  // DOC_DATE / DOC_TOTAL_AMOUNT here -- the columns the extractor had already written from these
  // very picks. When only the AI leg had answered, the final WAS the AI value, so the KW leg
  // handed the AI answer back to itself and the score counted a document as corroborated by
  // comparing it with itself. Reading LOCAL_* makes the three legs genuinely independent, which
  // is the only thing the number was ever supposed to mean.
  const dimensions = {
    company_id: { label: 'ח.פ / חברה', AI: normalizeCompanyID(d.AI_COMPANY_ID), BS: null,
                  KW: normalizeCompanyID(d.LOCAL_COMPANY_ID) },
    doc_id:     { label: 'מספר מסמך',  AI: normalizeDocID(d.AI_DOC_ID), BS: null,
                  KW: normalizeDocID(d.LOCAL_DOC_ID) },
    date:       { label: 'תאריך',      AI: normalizeDate(d.AI_DOC_DATE),
                  BS: normalizeDate(d.BS_LINE_DATE), KW: normalizeDate(d.LOCAL_DOC_DATE) },
    amount:     { label: 'סכום',       AI: normalizeAmount(d.AI_DOC_AMOUNT),
                  BS: normalizeAmount(d.BS_LINE_AMOUNT), KW: normalizeAmount(d.LOCAL_DOC_AMOUNT) },
    doc_type:   { label: 'סוג מסמך',   AI: normalizeDocType(d.AI_TYPE), BS: null,
                  // BS line records have no extractor legs by construction (measured over the
                  // cohort: LOCAL_TYPE 0/213, AI_TYPE 1/213, TYPE 213/213) -- their TYPE is
                  // ledger-assigned at ingest, which is what the row IS rather than a guess about
                  // what was read off a page, so it is a legitimate source THERE and only there.
                  KW: normalizeDocType(hasReal(d.LOCAL_TYPE) ? d.LOCAL_TYPE
                        : (d.SOURCE_TYPE === 'BALANCE_SHEET' ? d.TYPE : null)) },
  };

  // ── the corroboration score ──
  let idMismatch = false, dataMismatch = false, allFourConfirmed = true;
  const distinct = (arr) => { const o = []; arr.forEach(v => { if (o.indexOf(v) < 0) o.push(v); }); return o; };

  ['company_id', 'doc_id'].forEach(key => {
    const vals = [dimensions[key].AI, dimensions[key].KW].filter(v => hasReal(v));
    if (distinct(vals).length > 1) idMismatch = true;
  });
  ['date', 'amount'].forEach(key => {
    const vals = [dimensions[key].AI, dimensions[key].BS, dimensions[key].KW].filter(v => hasReal(v));
    if (distinct(vals).length > 1) dataMismatch = true;
  });
  const typeAI = dimensions.doc_type.AI, typeKW = dimensions.doc_type.KW;
  if (hasReal(typeAI) && hasReal(typeKW) && typeAI !== typeKW) dataMismatch = true;

  ['company_id', 'doc_id', 'date', 'amount'].forEach(key => {
    const dim = dimensions[key];
    const vals = [dim.AI, dim.BS, dim.KW].filter(v => hasReal(v));
    if (distinct(vals).length !== 1 || vals.length < 2) allFourConfirmed = false;
  });
  if (!hasReal(typeAI) || !hasReal(typeKW) || typeAI !== typeKW) allFourConfirmed = false;

  const aiBsMatch =
    hasReal(dimensions.date.AI) && hasReal(dimensions.date.BS) && dimensions.date.AI === dimensions.date.BS &&
    hasReal(dimensions.amount.AI) && hasReal(dimensions.amount.BS) && dimensions.amount.AI === dimensions.amount.BS;

  let finalScore = 0, summaryText = '';
  if (idMismatch) {
    finalScore = 0; summaryText = 'נכשל: סתירה במזהי המסמך (חברה או מספר מסמך).';
  } else if (aiBsMatch) {
    finalScore = 100; summaryText = 'הצלחה: התאמה מושלמת בין AI ל-BS.';
  } else if (!dataMismatch && allFourConfirmed) {
    finalScore = 100; summaryText = 'הצלחה: כל המדדים תואמים ומוצלבים.';
  } else if (!dataMismatch) {
    finalScore = 50; summaryText = 'חלקי: אין סתירות, אך חסר מידע מצליב.';
  } else {
    finalScore = 0; summaryText = 'נכשל: נמצאה סתירה בנתוני התאריך, הסכום או סוג המסמך.';
  }

  const cell = (v) => hasReal(v) ? String(v) : '---';
  let report = '=== דוח אימות נתונים (' + finalScore + '%) ===\\n';
  report += 'סיכום: ' + summaryText + '\\n\\n';
  report += 'מדד      | AI (בינה)   | BS (כרטסת)  | KW (מקומי)\\n';
  report += '----------------------------------------------\\n';
  Object.keys(dimensions).forEach(key => {
    const dim = dimensions[key];
    report += dim.label.padEnd(10) + ' | ' + cell(dim.AI).padEnd(11) + ' | ' +
              cell(dim.BS).padEnd(11) + ' | ' + cell(dim.KW) + '\\n';
  });
  if (hasReal(typeAI) && hasReal(typeKW) && typeAI !== typeKW) {
    report += '\\n>>> סתירת סוג מסמך: AI="' + typeAI + '" אל מול KW="' + typeKW + '"';
  } else if (hasReal(typeAI) && hasReal(typeKW)) {
    report += '\\n>>> סוג מסמך: התאמה מלאה (' + typeAI + ')';
  } else if (hasReal(typeAI) || hasReal(typeKW)) {
    report += '\\n>>> סוג מסמך: מקור יחיד — ' +
      (hasReal(typeAI) ? 'AI="' + typeAI + '"' : 'KW="' + typeKW + '"') + ' (אין סתירה)';
  } else {
    report += '\\n>>> סוג מסמך: לא זוהה בשום מקור';
  }

  // ── the document's own number ──
  // [C11 2026-08-21] A DOC NUMBER MAY ONLY BECOME IDENTITY IF IT CAN IDENTIFY SOMETHING.
  // When extraction cannot find a document number it does not return nothing -- it returns the
  // most number-shaped thing on the page: a date, the company number, a stray word. Each of those
  // collides with every other document read the same way (78 duplicate groups, one doc-id shared
  // across 21 unrelated documents). A rejected value is simply ABSENT, which the machine already
  // handles -- the document routes to the missing-doc-id path instead of quietly acquiring a
  // shared identity. The reason is recorded, never a silent drop.
  // THE THREE REGEXES BELOW WERE BROKEN IN THE ORIGINAL: /^d{1,2}.../ matches the LETTER d, not a
  // digit -- the backslashes were lost. As committed, the date rejector and the company-number
  // rejector could never fire on any real id. They are correct here.
  // Rejection now applies to DOC_ID itself. In the old shape C11 guarded SELECTED_DOC_ID while
  // the extractor wrote DOC_ID with no check at all, so the junk it existed to stop reached
  // identity by the other door -- exactly what its own note said must not happen.
  let ownId = idPick.val;
  let idRejected = null;
  {
    const raw = String(ownId == null ? '' : ownId).trim();
    const alnum = raw.replace(/[^0-9A-Za-z]/g, '');
    const company = String(d.COMPANY_ID || d.AI_COMPANY_ID || '').trim();
    if (raw) {
      if (/^\\d{1,2}[.\\/-]\\d{1,2}[.\\/-]\\d{2,4}$/.test(raw) || /^\\d{4}-\\d{2}-\\d{2}/.test(raw))
        idRejected = 'looks like a date';
      else if (/^5\\d{8}$/.test(raw)) idRejected = 'looks like a company number';
      else if (/^[A-Za-z]+$/.test(raw)) idRejected = 'purely alphabetic';
      else if (alnum.length < 3) idRejected = 'fewer than 3 alphanumerics';
      else if (/^0+$/.test(alnum)) idRejected = 'all zeros';
      else if (company && company === raw) idRejected = 'equal to the company id';
    }
    if (idRejected) ownId = null;
  }
  // FILL-ONLY, carried verbatim from the 2026-08-06 consolidation migration's
  // \`where coalesce("DOC_ID",'') = ''\`: an existing DOC_ID is never overwritten.
  if (!isBs && !has(d.DOC_ID) && has(ownId)) out.DOC_ID = String(ownId).trim();
  // Shipment only: preserve the linked invoice instead of losing it to the id consolidation.
  if (isShipment && !has(d.LINKED_INVOICE_ID) && has(d.INVOICE_ID)) {
    out.LINKED_INVOICE_ID = String(d.INVOICE_ID).trim();
  }

  out.SELECTION_CERTAINTY = finalScore;
  out.SELECTION_SOURCE = idMismatch ? 'ID_MISMATCH' : (aiBsMatch ? 'AI+BS' : 'OTHER');
  out.SELECTION_SCORE_DEBUG = report;

  // ── the company's own floor ──
  // [fixed certainty 2026-09-02, owner Decision 5] max(computed, fixed). The fixed value is the
  // operator's statement about the SUPPLIER ("ספקים עם אחוז ודאות גבוה"), so it raises the
  // score and never lowers it; the report says so when it changed the answer.
  {
    const key = normalizeCompanyID(d.COMPANY_ID || d.AI_COMPANY_ID || d.LOCAL_COMPANY_ID);
    const fixed = key ? FIXED[key] : undefined;
    if (Number.isFinite(fixed) && fixed > out.SELECTION_CERTAINTY) {
      out.SELECTION_CERTAINTY = fixed;
      out.SELECTION_SOURCE = 'FIXED_CERTAINTY';
      out.SELECTION_SCORE_DEBUG += '\\n>>> אחוז הוודאות הועלה ל-' + fixed +
        ' לפי הוודאות הקבועה שנקבעה לחברה (' + key + ').';
    }
  }

  // ── trusted supplier ──
  // A supplier the operator has vouched for, arriving through a vouched-for source, does not need
  // machine corroboration. Ported verbatim, including the Hebrew line appended to the report.
  if (out.SELECTION_CERTAINTY !== 100) {
    const normalizedCurrent = normalizeCompanyID(d.COMPANY_ID || d.AI_COMPANY_ID);
    const currentSource = normSource(d.SOURCE_TYPE);
    const isTrusted = TRUSTED.some(s => s.companyId === normalizedCurrent && s.sourceType === currentSource);
    if (isTrusted) {
      out.SELECTION_CERTAINTY = 100;
      out.SELECTION_SOURCE = 'TRUSTED_SUPPLIER';
      out.SELECTION_SCORE_DEBUG += '\\n>>> אחוז הוודאות שונה ל-100 מכיוון שהחברה (' +
        normalizedCurrent + ') היא חברה מאושרת עם מקור מאושר (' + currentSource + ').';
    }
  }

  // SELECTION_COMPLETED is the STATE-MACHINE FLAG, not a verdict on the score. Every action always
  // stamps its own completion -- a pass that resolved nothing is still an answer about the
  // document, and the alternative is the livelock recorded at indoxV2ActionsGDoc01 :2982-2994,
  // where decide re-dispatched the same selection forever. The score lives in SELECTION_CERTAINTY,
  // which is where every consumer already reads it.
  out.SELECTION_COMPLETED = true;
  out.SELECTION_VALUES_HASH = selectionHash(d, out);
  out.SELECTION_DEBUG_PERTYPE = JSON.stringify({
    DOC_ID: idRejected ? ('REJECTED: ' + idRejected) : idPick.source,
    DOC_DATE: dateSource, AMOUNT: amountSource,
    SHIPMENT: shipSource, PURCHASE: purchPick.source,
    LOCAL_STATUS: d.LOCAL_STATUS || null, AI_STATUS: d.AI_STATUS || null,
  });
  return { json: out };
});
`,
    };

    @node({
        id: 'selt-return-01',
        name: 'Return',
        /*__n8n__*/ notes: "Pure passthrough, mirroring the extractors' own 'Return'. The caller decides what to do with the decision: the router upserts it, fullDocEx01 just reports it.",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [896, 0],
    })
    Return_ = {
        assignments: {
            assignments: [],
        },
        includeOtherFields: true,
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.RowIn.out(0).to(this.LoadCompanies.in(0));
        this.LoadCompanies.out(0).to(this.RestoreRow.in(0));
        this.RestoreRow.out(0).to(this.Select.in(0));
        this.Select.out(0).to(this.Return_.in(0));
    }
}
