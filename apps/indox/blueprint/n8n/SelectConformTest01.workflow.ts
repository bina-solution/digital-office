import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : SelectConformTest01 — selector conformance (TEST ONLY, not product)
// Nodes   : 5  |  Connections: 4
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// Hook                               webhook                    [creds]
// Cases                              code
// CallSelecttype01                   executeWorkflow            [onError→regular]
// Assert                             code
// Respond                            respondToWebhook
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// Hook
//    → Cases
//      → CallSelecttype01
//        → Assert
//          → Respond
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Hook":{"main":[[{"node":"Cases","type":"main","index":0}]]},"Cases":{"main":[[{"node":"Call SelectType01","type":"main","index":0}]]},"Call SelectType01":{"main":[[{"node":"Assert","type":"main","index":0}]]},"Assert":{"main":[[{"node":"Respond","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-25T22:15:39.057Z","createdAt":"2026-08-25T22:15:39.057Z","role":"workflow:owner","workflowId":"SelectConformTest01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'SelectConformTest01',
    name: 'SelectConformTest01 — selector conformance (TEST ONLY, not product)',
    active: true,
    isArchived: false,
    tags: ['app:indox'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class Selectconformtest01SelectorConformanceTestOnlyNotProductWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'sct-hook-01',
        webhookId: 'f0110dc5-11ee-4ec0-9a1b-fde0000000e1',
        name: 'Hook',
        /*__n8n__*/ notes: "Feeds SYNTHETIC rows into the LIVE SelectType01 and asserts the answer. Nothing is read from or written to incoming_documents -- the ids are fictional -- so this exercises every branch of the selector, including the ones real data almost never reaches, without touching a document.",
        type: 'n8n-nodes-base.webhook',
        version: 2.1,
        position: [0, 0],
        credentials: { httpBasicAuth: { id: 'azPhHBvOWaf9IsEA', name: 'Incoming Documents [env-managed]' } },
    })
    Hook = {
        httpMethod: 'POST',
        path: 'select-conform-test',
        authentication: 'basicAuth',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'sct-cases-01',
        name: 'Cases',
        /*__n8n__*/ notes: "One row per condition the selector has to survive. Each carries `_case` (the name) and `_expect` (what the answer must be) so the assertion travels with the input instead of living in a separate table that can drift from it.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [224, 0],
    })
    Cases = {
        jsCode: `// Conformance cases. Field naming is the real row's, so these are indistinguishable from a
// document as far as the selector is concerned.
const C = [
  { _case: 'local only',
    TYPE: 'INVOICE', LOCAL_DOC_ID: 'INV-1001', LOCAL_DOC_AMOUNT: '100.00', LOCAL_DOC_DATE: '01/02/2026',
    _expect: { DOC_ID: 'INV-1001', DOC_TOTAL_AMOUNT: '100.00', DOC_DATE: '01/02/2026' } },

  { _case: 'ai only — amount taken, DATE SUPPRESSED (A1 guard)',
    TYPE: 'INVOICE', AI_DOC_ID: 'INV-1002', AI_DOC_AMOUNT: '200.00', AI_DOC_DATE: '02/02/2026',
    _expect: { DOC_ID: 'INV-1002', DOC_TOTAL_AMOUNT: '200.00', DOC_DATE: null } },

  { _case: 'both agree',
    TYPE: 'INVOICE', LOCAL_DOC_ID: 'INV-1003', AI_DOC_ID: 'INV-1003',
    LOCAL_DOC_AMOUNT: '300.00', AI_DOC_AMOUNT: '300.00',
    _expect: { DOC_ID: 'INV-1003', DOC_TOTAL_AMOUNT: '300.00' } },

  { _case: 'amount conflict, no ledger — LOCAL wins',
    TYPE: 'INVOICE', LOCAL_DOC_ID: 'INV-1004', AI_DOC_ID: 'INV-1004',
    LOCAL_DOC_AMOUNT: '400.00', AI_DOC_AMOUNT: '999.00',
    _expect: { DOC_TOTAL_AMOUNT: '400.00' } },

  { _case: 'amount conflict, ledger sides with AI — AI wins',
    TYPE: 'INVOICE', LOCAL_DOC_ID: 'INV-1005', AI_DOC_ID: 'INV-1005',
    LOCAL_DOC_AMOUNT: '400.00', AI_DOC_AMOUNT: '999.00', BS_LINE_AMOUNT: '999',
    _expect: { DOC_TOTAL_AMOUNT: '999.00' } },

  { _case: 'amount conflict, ledger sides with LOCAL — LOCAL wins',
    TYPE: 'INVOICE', LOCAL_DOC_ID: 'INV-1006', AI_DOC_ID: 'INV-1006',
    LOCAL_DOC_AMOUNT: '400.00', AI_DOC_AMOUNT: '999.00', BS_LINE_AMOUNT: '400',
    _expect: { DOC_TOTAL_AMOUNT: '400.00' } },

  { _case: 'thousands separator is not a disagreement',
    TYPE: 'INVOICE', LOCAL_DOC_ID: 'INV-1007', LOCAL_DOC_AMOUNT: '10,069.00', AI_DOC_AMOUNT: '10069.00',
    _expect: { DOC_TOTAL_AMOUNT: '10,069.00' } },

  { _case: 'junk id — date shaped, rejected',
    TYPE: 'INVOICE', LOCAL_DOC_ID: '12/03/2026', _expect: { DOC_ID: null } },
  { _case: 'junk id — company number shaped, rejected',
    TYPE: 'INVOICE', LOCAL_DOC_ID: '515463354', _expect: { DOC_ID: null } },
  { _case: 'junk id — purely alphabetic, rejected',
    TYPE: 'INVOICE', LOCAL_DOC_ID: 'INVOICE', _expect: { DOC_ID: null } },
  { _case: 'junk id — under 3 alphanumerics, rejected',
    TYPE: 'INVOICE', LOCAL_DOC_ID: '-7', _expect: { DOC_ID: null } },
  { _case: 'junk id — all zeros, rejected',
    TYPE: 'INVOICE', LOCAL_DOC_ID: '0000', _expect: { DOC_ID: null } },
  { _case: 'junk id — equals the company id, rejected',
    TYPE: 'INVOICE', COMPANY_ID: '514725599', LOCAL_DOC_ID: '514725599', _expect: { DOC_ID: null } },
  { _case: 'good id that merely CONTAINS digits of a date is kept',
    TYPE: 'INVOICE', LOCAL_DOC_ID: 'INV-12032026', _expect: { DOC_ID: 'INV-12032026' } },

  { _case: 'existing DOC_ID is never overwritten (fill-only)',
    TYPE: 'INVOICE', DOC_ID: 'ALREADY-THERE', LOCAL_DOC_ID: 'INV-1008',
    _expect: { DOC_ID: null } },

  { _case: 'balance sheet is AI-led and writes TOTAL_AMOUNT',
    TYPE: 'BALANCE_SHEET', LOCAL_DOC_AMOUNT: '11.00', AI_DOC_AMOUNT: '22.00',
    _expect: { TOTAL_AMOUNT: '22.00', DOC_TOTAL_AMOUNT: null } },

  { _case: 'shipment fills its own id when no list leg answered',
    TYPE: 'SHIPMENT', LOCAL_DOC_ID: 'SH-2001',
    _expect: { SHIPMENT_DOC_ID: 'SH-2001' } },

  { _case: 'shipment list leg is unwrapped, not stored as JSON',
    TYPE: 'INVOICE', LOCAL_SHIPMENT_IDS: '["SH-2002"]',
    _expect: { SHIPMENT_DOC_ID: 'SH-2002' } },

  { _case: 'empty JSON array is a non-answer',
    TYPE: 'INVOICE', AI_SHIPMENT_IDS: '[]', _expect: { SHIPMENT_DOC_ID: null } },

  { _case: 'ledger fills a date nobody read',
    TYPE: 'INVOICE', BS_LINE_DATE: '15/04/2026', _expect: { DOC_DATE: '15/04/2026' } },

  { _case: 'completely empty row still stamps its flag',
    TYPE: 'INVOICE', _expect: { SELECTION_COMPLETED: true } },
];
// [phase-4 2026-08-31] Synthetic rows only: each names the test tenant so SelectType01's
// settings/queries reads resolve against indox_test. Nothing else in this suite touches a table.
return C.map((c, i) => ({ json: { ID: '__conform_' + i, __instance: 'test', ...c } }));
`,
    };

    @node({
        id: 'sct-call-01',
        name: 'Call SelectType01',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [448, 0],
        onError: 'continueRegularOutput',
    })
    CallSelecttype01 = {
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
        id: 'sct-assert-01',
        name: 'Assert',
        /*__n8n__*/ notes: "`null` in _expect means the selector must write NOTHING for that field — which for this pipeline is a real answer, not an omission: a key the selector leaves out is a column the upsert leaves alone.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [672, 0],
    })
    Assert = {
        jsCode: `const cases = $('Cases').all().map(i => i.json);
const got = {};
for (const it of $input.all()) { const j = it.json || {}; if (j.ID) got[String(j.ID)] = j; }

const norm = v => (v === null || v === undefined) ? null : String(v).trim();
const pass = [], fail = [];
for (const c of cases) {
  const g = got[String(c.ID)] || {};
  const bad = [];
  for (const [k, want] of Object.entries(c._expect || {})) {
    const have = (g[k] === undefined) ? null : g[k];
    const ok = (want === null) ? (have === null || have === undefined || have === '')
             : (typeof want === 'boolean') ? (have === want)
             : (norm(have) === norm(want));
    if (!ok) bad.push(k + ': want ' + JSON.stringify(want) + ' got ' + JSON.stringify(have));
  }
  if (g.SELECTION_COMPLETED !== true) bad.push('SELECTION_COMPLETED not stamped');
  if (!g.SELECTION_VALUES_HASH) bad.push('SELECTION_VALUES_HASH not written');
  (bad.length ? fail : pass).push({ case: c._case, problems: bad });
}
return [{ json: {
  total: cases.length, passed: pass.length, failed: fail.length,
  failures: fail, passed_cases: pass.map(p => p.case),
}}];
`,
    };

    @node({
        id: 'sct-respond-01',
        name: 'Respond',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [896, 0],
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
        this.Hook.out(0).to(this.Cases.in(0));
        this.Cases.out(0).to(this.CallSelecttype01.in(0));
        this.CallSelecttype01.out(0).to(this.Assert.in(0));
        this.Assert.out(0).to(this.Respond.in(0));
    }
}
