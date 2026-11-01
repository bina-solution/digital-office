import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : SelectParityTest01 — selection parity harness (TEST ONLY, not product)
// Nodes   : 7  |  Connections: 6
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// Hook                               webhook                    [creds]
// FetchRows                          postgres                   [creds]
// CallBase                           executeWorkflow            [onError→regular]
// RestoreForType                     code
// CallType                           executeWorkflow            [onError→regular]
// Compare                            code
// Respond                            respondToWebhook
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// Hook
//    → FetchRows
//      → CallBase
//        → RestoreForType
//          → CallType
//            → Compare
//              → Respond
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Hook":{"main":[[{"node":"Fetch Rows","type":"main","index":0}]]},"Fetch Rows":{"main":[[{"node":"Call Base","type":"main","index":0}]]},"Call Base":{"main":[[{"node":"Restore For Type","type":"main","index":0}]]},"Restore For Type":{"main":[[{"node":"Call Type","type":"main","index":0}]]},"Call Type":{"main":[[{"node":"Compare","type":"main","index":0}]]},"Compare":{"main":[[{"node":"Respond","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-25T15:04:52.467Z","createdAt":"2026-08-25T15:04:52.467Z","role":"workflow:owner","workflowId":"SelectParityTest01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'SelectParityTest01',
    name: 'SelectParityTest01 — selection parity harness (TEST ONLY, not product)',
    active: true,
    isArchived: false,
    tags: ['app:indox'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class Selectparitytest01SelectionParityHarnessTestOnlyNotProductWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'sp-hook-01',
        webhookId: 'f0110dc5-11ee-4ec0-9a1b-fde0000000d1',
        name: 'Hook',
        /*__n8n__*/ notes: "Read-only. It fetches real rows, runs them through the LIVE selector workflows and compares the answer with the values the old code already wrote to those same rows. Nothing is upserted, so it can be run against production as often as needed.",
        type: 'n8n-nodes-base.webhook',
        version: 2.1,
        position: [0, 0],
        credentials: { httpBasicAuth: { id: 'azPhHBvOWaf9IsEA', name: 'Incoming Documents [env-managed]' } },
    })
    Hook = {
        httpMethod: 'POST',
        path: 'select-parity-test',
        authentication: 'basicAuth',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'sp-fetch-01',
        name: 'Fetch Rows',
        /*__n8n__*/ notes: "The comparison cohort: rows the OLD path already decided, so both answers exist side by side. Body params: limit (default 400), type (optional TYPE filter).",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [224, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    FetchRows = {
        operation: 'executeQuery',
        query: `-- THE COHORT IS THE POPULATION THE GATE WOULD ACTUALLY FIRE ON, which means rows that
-- have BEEN through both extraction points. Without that restriction the harness also picks up
-- rows whose finals arrived at INGEST and never went through extraction at all (measured: their
-- PER_TYPE_EXTRACTION_COMPLETED is null and SELECTION_DEBUG_PERTYPE is empty) -- comparing a
-- selector's answer against a value no selector ever wrote is not a parity test.
-- [phase-4 2026-08-31] The cohort is the TEST tenant's rows, and every row is stamped
-- __instance='test' here so both 'Call Base' and 'Call Type' (which re-emits these same items via
-- 'Restore For Type') feed the selectors tenant-named input -- their settings/queries reads throw
-- without it. 'Compare' ignores the extra key.
SELECT *, 'test' AS "__instance" FROM indox_test.incoming_documents
WHERE "STATUS" NOT IN ('MERGED','GARBAGE')
  AND coalesce("TYPE",'') LIKE $2
  AND lower(coalesce("BASE_EXTRACTION_COMPLETED",'')) = 'true'
  AND lower(coalesce("PER_TYPE_EXTRACTION_COMPLETED",'')) = 'true'
ORDER BY "updated_at" DESC
LIMIT $1::int;`,
        options: {
            queryReplacement: "={{ $json.body.limit || 400 }},{{ $json.body.type || '%' }}",
        },
    };

    @node({
        id: 'sp-callbase-01',
        name: 'Call Base',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [448, 0],
        onError: 'continueRegularOutput',
    })
    CallBase = {
        workflowId: {
            __rl: true,
            value: 'SelectBase01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'sp-restore-01',
        name: 'Restore For Type',
        /*__n8n__*/ notes: "'Call Base' returns the BASE selector's decision, not the row. The two selectors are independent and each must see the ORIGINAL row, so it is re-emitted here.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [672, 0],
    })
    RestoreForType = {
        jsCode: `// A parity test compares what the two paths produced — and 'Call Base' continues on error, so a
// failed base call would leave the comparison with nothing and the test could still pass. Read the
// failure and refuse to compare: a test that cannot fail on a broken input is not a test.
const base = (() => { try { return $('Call Base').first().json || {}; } catch (e) { return {}; } })();
const failed = String(base.error || base.errorMessage || '');
if (failed) throw new Error('Call Base failed, so there is no base to compare against: ' + failed.slice(0, 300));
return $('Fetch Rows').all();
`,
    };

    @node({
        id: 'sp-calltype-01',
        name: 'Call Type',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [896, 0],
        onError: 'continueRegularOutput',
    })
    CallType = {
        workflowId: {
            __rl: true,
            value: 'SelectType01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'sp-compare-01',
        name: 'Compare',
        /*__n8n__*/ notes: "For every field: MATCH when the selector's answer equals what the old path stored, SILENT when the selector declines to write (the upsert would leave the column untouched, so nothing can regress), FILL when the column was empty and the selector supplies a value, and DRIFT when both exist and differ. DRIFT is the only number that has to be zero before the old path is switched off.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1120, 0],
    })
    Compare = {
        jsCode: `const rows = $('Fetch Rows').all().map(i => i.json);
const baseOut = $('Call Base').all().map(i => i.json);
const typeOut = $input.all().map(i => i.json);

const byId = (arr) => { const m = {}; arr.forEach(o => { if (o && o.ID) m[String(o.ID)] = o; }); return m; };
const B = byId(baseOut), T = byId(typeOut);

const norm = (v) => {
  if (v === null || v === undefined) return '';
  const s = String(v).trim();
  return (s.toLowerCase() === 'null' || s.toLowerCase() === 'undefined') ? '' : s;
};
const normAmt = (v) => { const s = norm(v).replace(/[\\s,]/g, ''); const n = parseFloat(s); return isNaN(n) ? s : n.toFixed(2); };
// A FORMAT DIFFERENCE IS NOT A DRIFT. Three shapes on this table mean the same thing and would
// otherwise dominate the count: dates stored as ISO or as a full timestamp vs the dd/mm/yyyy the
// selectors emit, and single-element JSON arrays vs the bare id inside them. Only differences that
// survive canonicalisation are real.
const normDate = (v) => {
  const s = norm(v);
  if (!s) return '';
  let m = s.match(/^(\\d{4})-(\\d{2})-(\\d{2})/);
  if (m) return m[3] + '/' + m[2] + '/' + m[1];
  m = s.match(/^(\\d{1,2})[\\/.\\-](\\d{1,2})[\\/.\\-](\\d{2,4})$/);
  if (m) {
    const y = m[3].length === 2 ? '20' + m[3] : m[3];
    return m[1].padStart(2, '0') + '/' + m[2].padStart(2, '0') + '/' + y;
  }
  return s;
};
const normList = (v) => {
  let s = norm(v);
  if (!s) return '';
  try { const a = JSON.parse(s); if (Array.isArray(a)) s = a.length ? String(a[0]) : ''; } catch (e) {}
  return String(s).trim();
};

const FIELDS = [
  { k: 'COMPANY_ID', from: 'base' },
  { k: 'TYPE',       from: 'base' },
  { k: 'DOC_DATE',   from: 'base', alsoType: true, cmp: normDate },
  { k: 'DOC_ID',            from: 'type' },
  { k: 'DOC_TOTAL_AMOUNT',  from: 'type', cmp: normAmt },
  { k: 'TOTAL_AMOUNT',      from: 'type', cmp: normAmt },
  { k: 'SHIPMENT_DOC_ID',   from: 'type', cmp: normList },
  { k: 'PURCHASE_ID',       from: 'type', cmp: normList },
  { k: 'SELECTION_CERTAINTY', from: 'type', audit: true },
];

// The live version columns behind each final, for the staleness test below.
const LEGS = {
  COMPANY_ID:       ['LOCAL_COMPANY_ID', 'AI_COMPANY_ID'],
  TYPE:             ['LOCAL_TYPE', 'AI_TYPE'],
  DOC_DATE:         ['LOCAL_DOC_DATE', 'AI_DOC_DATE', 'BS_LINE_DATE'],
  DOC_ID:           ['LOCAL_DOC_ID', 'AI_DOC_ID'],
  DOC_TOTAL_AMOUNT: ['LOCAL_DOC_AMOUNT', 'AI_DOC_AMOUNT', 'BS_LINE_AMOUNT'],
  TOTAL_AMOUNT:     ['LOCAL_DOC_AMOUNT', 'AI_DOC_AMOUNT', 'BS_LINE_AMOUNT'],
  SHIPMENT_DOC_ID:  ['LOCAL_SHIPMENT_IDS', 'AI_SHIPMENT_IDS', 'LOCAL_DOC_ID'],
  PURCHASE_ID:      ['LOCAL_ORDER_IDS', 'AI_ORDER_IDS'],
};

const tally = {};
const samples = {};
FIELDS.forEach(f => { tally[f.k] = { match: 0, silent: 0, fill: 0, drift: 0, drift_live: 0, drift_stale: 0 }; samples[f.k] = []; });

let missingBase = 0, missingType = 0;
rows.forEach(r => {
  const id = String(r.ID);
  const b = B[id], t = T[id];
  if (!b) missingBase++;
  if (!t) missingType++;
  FIELDS.forEach(f => {
    const src = (f.from === 'base') ? b : t;
    let got = src ? src[f.k] : undefined;
    // DOC_DATE is written by BOTH selectors; the per-type answer wins when it has one, which is
    // exactly the precedence the two extraction points already have on the live row.
    if (f.alsoType && t && norm(t[f.k]) !== '') got = t[f.k];
    const cmp = f.cmp || norm;
    const g = cmp(got), s = cmp(r[f.k]);
    const bucket = tally[f.k];
    if (g === '') { bucket.silent++; return; }
    if (s === '') { bucket.fill++; return; }
    if (g === s) { bucket.match++; return; }
    bucket.drift++;
    // THE DECIDING QUESTION FOR EVERY DRIFT: can the stored value have come from the versions the
    // row holds NOW? If it matches none of them, no selector reading this row could ever have
    // produced it -- it is a value from an older extraction, an older code version or the ingest,
    // and the selector's answer is the current truth rather than a regression. Only a drift whose
    // stored value IS one of the live legs is a genuine difference of opinion.
    const legs = (LEGS[f.k] || []).map(c => cmp(r[c])).filter(x => x !== '');
    if (legs.indexOf(s) < 0) bucket.drift_stale++; else bucket.drift_live++;
    if (samples[f.k].length < 5) {
      samples[f.k].push({ ID: id, TYPE: r.TYPE, stored: String(r[f.k]).slice(0, 40), got: String(got).slice(0, 40),
                          stale: legs.indexOf(s) < 0 });
    }
  });
});

return [{ json: {
  cohort: rows.length,
  missing_from_base: missingBase,
  missing_from_type: missingType,
  tally: tally,
  drift_samples: samples,
}}];
`,
    };

    @node({
        id: 'sp-respond-01',
        name: 'Respond',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [1344, 0],
    })
    Respond = {
        respondWith: 'text',
        responseBody: '={{ JSON.stringify($json) }}',
        options: {
            responseHeaders: {
                entries: [
                    {
                        name: 'content-type',
                        value: 'application/json; charset=utf-8',
                    },
                ],
            },
        },
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.Hook.out(0).to(this.FetchRows.in(0));
        this.FetchRows.out(0).to(this.CallBase.in(0));
        this.CallBase.out(0).to(this.RestoreForType.in(0));
        this.RestoreForType.out(0).to(this.CallType.in(0));
        this.CallType.out(0).to(this.Compare.in(0));
        this.Compare.out(0).to(this.Respond.in(0));
    }
}
