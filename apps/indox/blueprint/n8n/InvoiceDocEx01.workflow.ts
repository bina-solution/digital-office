import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Invoice Document Extraction (local + AI, parallel)
// Nodes   : 14  |  Connections: 16
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// DocIn                              executeWorkflowTrigger
// CheckLocalEnabled                  postgres                   [creds]
// IfLocalDisabled                    if
// BuildLocalSkipped                  set
// CallInvoiceJqExV3                  executeWorkflow            [onError→regular]
// BuildLocalResult                   code
// CheckAiEnabled                     postgres                   [creds]
// IfAiDisabled                       if
// BuildAiSkipped                     set
// ExtractViaWebhook                  executeWorkflow            [onError→regular] [creds]
// BuildAiResult                      set
// MergeLocalAi                       merge
// Select                             code
// Return_                            set
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// DocIn
//    → CheckLocalEnabled
//      → IfLocalDisabled
//        → BuildLocalSkipped
//          → MergeLocalAi
//            → Select
//              → Return_
//       .out(1) → CallInvoiceJqExV3
//          → BuildLocalResult
//            → MergeLocalAi (↩ loop)
//    → CheckAiEnabled
//      → IfAiDisabled
//        → BuildAiSkipped
//          → MergeLocalAi.in(1) (↩ loop)
//       .out(1) → ExtractViaWebhook
//          → BuildAiResult
//            → MergeLocalAi.in(1) (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Doc In":{"main":[[{"node":"Check Local Enabled","type":"main","index":0},{"node":"Check AI Enabled","type":"main","index":0}]]},"Check Local Enabled":{"main":[[{"node":"If Local Disabled","type":"main","index":0}]]},"If Local Disabled":{"main":[[{"node":"Build Local Skipped","type":"main","index":0}],[{"node":"Call Invoice JQ Ex V3","type":"main","index":0}]]},"Call Invoice JQ Ex V3":{"main":[[{"node":"Build Local Result","type":"main","index":0}]]},"Check AI Enabled":{"main":[[{"node":"If AI Disabled","type":"main","index":0}]]},"If AI Disabled":{"main":[[{"node":"Build AI Skipped","type":"main","index":0}],[{"node":"Extract via Webhook","type":"main","index":0}]]},"Extract via Webhook":{"main":[[{"node":"Build AI Result","type":"main","index":0}]]},"Build Local Skipped":{"main":[[{"node":"Merge Local + AI","type":"main","index":0}]]},"Build Local Result":{"main":[[{"node":"Merge Local + AI","type":"main","index":0}]]},"Build AI Skipped":{"main":[[{"node":"Merge Local + AI","type":"main","index":1}]]},"Build AI Result":{"main":[[{"node":"Merge Local + AI","type":"main","index":1}]]},"Merge Local + AI":{"main":[[{"node":"Select","type":"main","index":0}]]},"Select":{"main":[[{"node":"Return","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"f5d175fb-c738-4607-8ef0-bf03c48e8a0b","name":"role:extractor"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-06T12:30:31.436Z","createdAt":"2026-08-06T12:30:31.436Z","role":"workflow:owner","workflowId":"InvoiceDocEx01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'InvoiceDocEx01',
    name: 'Invoice Document Extraction (local + AI, parallel)',
    active: true,
    isArchived: false,
    tags: ['app:indox', 'indox-app', 'role:extractor'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class InvoiceDocumentExtractionLocalAiParallelWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'invoicedocex01-trigger-01',
        name: 'Doc In',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, 300],
    })
    DocIn = {
        workflowInputs: {
            values: [
                {
                    name: 'ID',
                },
                {
                    name: 'API_TOOLS_ID',
                },
                {
                    name: 'LINK',
                    type: 'any',
                },
                {
                    name: 'LINK_CONNECTION',
                },
                {
                    name: 'STATUS',
                },
                {
                    name: 'TYPE',
                },
                {
                    name: 'DOC_ID',
                },
                {
                    name: 'SHIPMENT_DOC_ID',
                },
                {
                    name: 'LINKED_INVOICE_ID',
                },
                {
                    name: '__instance',
                },
                {
                    name: 'INVOICE_ID',
                },
            ],
        },
    };

    @node({
        id: 'invoicedocex01-check-local-01',
        name: 'Check Local Enabled',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [280, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    CheckLocalEnabled = {
        operation: 'executeQuery',
        query: "=SELECT COALESCE((SELECT value FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('InvoiceDocEx01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.settings WHERE key='extraction_local_enabled'), 'true') AS local_enabled",
        options: {},
    };

    @node({
        id: 'invoicedocex01-if-local-01',
        name: 'If Local Disabled',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [560, 0],
    })
    IfLocalDisabled = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: 'invoicedocex01-local-cond-01',
                    leftValue: '={{ $json.local_enabled }}',
                    rightValue: 'false',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: 'invoicedocex01-local-skip-01',
        name: 'Build Local Skipped',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [840, -120],
    })
    BuildLocalSkipped = {
        mode: 'manual',
        assignments: {
            assignments: [
                {
                    id: 'dl_LOCAL_DOC_AMOUNT',
                    name: 'LOCAL_DOC_AMOUNT',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'dl_LOCAL_DOC_DATE',
                    name: 'LOCAL_DOC_DATE',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'dl_LOCAL_DOC_ID',
                    name: 'LOCAL_DOC_ID',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'dl_LOCAL_ORDER_IDS',
                    name: 'LOCAL_ORDER_IDS',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'dl_LOCAL_SHIPMENT_IDS',
                    name: 'LOCAL_SHIPMENT_IDS',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'dl_status',
                    name: 'LOCAL_STATUS',
                    value: 'skipped: extraction_local_enabled=false',
                    type: 'string',
                },
            ],
        },
        includeOtherFields: false,
        options: {},
    };

    @node({
        id: 'invoicedocex01-call-jqex-01',
        name: 'Call Invoice JQ Ex V3',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [840, 120],
        onError: 'continueRegularOutput',
        retryOnFail: false,
    })
    CallInvoiceJqExV3 = {
        workflowId: {
            __rl: true,
            value: 'JQExV3Invoice001',
            mode: 'list',
            cachedResultUrl: '/workflow/JQExV3Invoice001',
            cachedResultName: 'Invoice JQ Ex V3',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                ID: "={{ $('Doc In').item.json.ID }}",
                API_TOOLS_ID: "={{ $('Doc In').item.json.API_TOOLS_ID }}",
                LINK: "={{ $('Doc In').item.json.LINK }}",
                __instance: "={{ $('Doc In').item.json.__instance || '' }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'ID',
                    displayName: 'ID',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                },
                {
                    id: 'API_TOOLS_ID',
                    displayName: 'API_TOOLS_ID',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                },
                {
                    id: 'LINK',
                    displayName: 'LINK',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                },
                {
                    id: 'LINK_CONNECTION',
                    displayName: 'LINK_CONNECTION',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                    removed: false,
                },
                {
                    id: 'STATUS',
                    displayName: 'STATUS',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                    removed: false,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        mode: 'each',
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'invoicedocex01-local-result-01',
        name: 'Build Local Result',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1120, 120],
    })
    BuildLocalResult = {
        jsCode: `// Map this type's JQExV3 workflow's raw field names onto the LOCAL_* triad.
const raw = $json;
const out = { LOCAL_DOC_AMOUNT: null, LOCAL_DOC_DATE: null, LOCAL_DOC_ID: null, LOCAL_ORDER_IDS: null, LOCAL_SHIPMENT_IDS: null };
// A LEG THAT DIED MUST NOT REPORT 'ran'. 'Call Invoice JQ Ex V3' carries onError:
// continueRegularOutput, so its failure arrives here as an ordinary item with .error set and this
// node used to fall straight through to LOCAL_STATUS='ran' with every LOCAL_* null -- identical
// output to a leg that genuinely ran and found nothing. Measured 2026-08-18 on line test01: the
// JQ call died in 45ms with "Invalid input for 'the retry counter' ... expects a string but we got '0'",
// the row recorded LOCAL_STATUS 'ran', every pick degraded to AI_ONLY, and nothing anywhere said
// an extraction had failed. 'ran' is an ASSERTION that the query answered; only say it when true.
const __rawErr = raw && (raw.error || raw.errorMessage);
if (__rawErr) {
  const __m = (__rawErr && (__rawErr.message || __rawErr.description)) || __rawErr;
  out.LOCAL_STATUS = 'failed: ' + String(__m).slice(0, 300);
  return [{ json: out }];
}
  out.LOCAL_DOC_ID = raw.INVOICE_ID || null;
  out.LOCAL_DOC_DATE = raw.DOC_DATE || null;
  out.LOCAL_DOC_AMOUNT = raw.DOC_TOTAL_AMOUNT || null;
  out.LOCAL_SHIPMENT_IDS = raw.SHIPMENT_ID || null;
  out.LOCAL_ORDER_IDS = raw.PURCHASE_ID || null;
out.LOCAL_STATUS = 'ran';
return [{ json: out }];
`,
    };

    @node({
        id: 'invoicedocex01-check-ai-01',
        name: 'Check AI Enabled',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [280, 560],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    CheckAiEnabled = {
        operation: 'executeQuery',
        query: "=SELECT COALESCE((SELECT value FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('InvoiceDocEx01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.settings WHERE key='extraction_ai_enabled'), 'true') AS ai_enabled",
        options: {},
    };

    @node({
        id: 'invoicedocex01-if-ai-01',
        name: 'If AI Disabled',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [560, 560],
    })
    IfAiDisabled = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: 'invoicedocex01-ai-cond-01',
                    leftValue: '={{ $json.ai_enabled }}',
                    rightValue: 'false',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: 'invoicedocex01-ai-skip-01',
        name: 'Build AI Skipped',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [840, 440],
    })
    BuildAiSkipped = {
        mode: 'manual',
        assignments: {
            assignments: [
                {
                    id: 'da0',
                    name: 'AI_DOC_ID',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'da1',
                    name: 'AI_DOC_DATE',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'da2',
                    name: 'AI_DOC_AMOUNT',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'da3',
                    name: 'AI_SHIPMENT_IDS',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'da4',
                    name: 'AI_ORDER_IDS',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'da5',
                    name: 'AI_STATUS',
                    value: 'skipped: extraction_ai_enabled=false',
                    type: 'string',
                },
            ],
        },
        includeOtherFields: false,
        options: {},
    };

    @node({
        id: 'invoicedocex01-extract-ai-01',
        name: 'Extract via Webhook',
        /*__n8n__*/ notes: "Converted httpRequest -> executeWorkflow 2026-08-11. The webhook transport created a NEW Bull job while this execution already held one of 16 slots, so it waited out its own 600000ms timeout behind the queue — measured 601s avg here vs 28s in BaseDocEx01, which already calls the extractor this way. FIELDS=\"\" matches BaseDocEx01 and today's effective behaviour (the webhook path dropped FIELDS anyway).",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [840, 680],
        credentials: { httpBasicAuth: { id: 'azPhHBvOWaf9IsEA', name: 'Incoming Documents [env-managed]' } },
        onError: 'continueRegularOutput',
    })
    ExtractViaWebhook = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ExtractInvoiceGemini01',
            mode: 'id',
            cachedResultName: 'invoice Extractor - Gemini 3.1 pro',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                LINK: "={{ $('Doc In').item.json.LINK }}",
                use_cache: '={{ true }}',
                FIELDS: '',
                LINK_CONNECTION: "={{ $('Doc In').item.json.LINK_CONNECTION }}",
                __instance: "={{ $('Doc In').item.json.__instance || '' }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'LINK',
                    displayName: 'LINK',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                    removed: false,
                },
                {
                    id: 'use_cache',
                    displayName: 'use_cache',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'boolean',
                    removed: false,
                },
                {
                    id: 'FIELDS',
                    displayName: 'FIELDS',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                    removed: false,
                },
                {
                    id: 'LINK_CONNECTION',
                    displayName: 'LINK_CONNECTION',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                    removed: false,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'invoicedocex01-ai-result-01',
        name: 'Build AI Result',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1120, 680],
    })
    BuildAiResult = {
        mode: 'manual',
        assignments: {
            assignments: [
                {
                    id: 'dar0',
                    name: 'AI_DOC_ID',
                    value: '={{ $json.data?.AI_DOC_ID || null }}',
                    type: 'string',
                },
                {
                    id: 'dar1',
                    name: 'AI_DOC_DATE',
                    value: '={{ $json.data?.AI_DOC_DATE || null }}',
                    type: 'string',
                },
                {
                    id: 'dar2',
                    name: 'AI_DOC_AMOUNT',
                    value: '={{ $json.data?.AI_DOC_AMOUNT || null }}',
                    type: 'string',
                },
                {
                    id: 'dar3',
                    name: 'AI_SHIPMENT_IDS',
                    value: '={{ $json.data?.AI_SHIPMENT_IDS || null }}',
                    type: 'string',
                },
                {
                    id: 'dar4',
                    name: 'AI_ORDER_IDS',
                    value: '={{ $json.data?.AI_ORDER_IDS || null }}',
                    type: 'string',
                },
                {
                    id: 'dar5',
                    name: 'AI_STATUS',
                    value: "={{ $json.ai_disabled ? ('skipped: ' + ($json.error || 'ai_disabled')) : ($json.success === false ? ('failed: ' + String($json.ERROR || $json.error || 'ai_extraction_failed')) : 'ran') }}",
                    type: 'string',
                },
                {
                    id: 'aifail-20260813-1',
                    name: 'ai_failed',
                    value: '={{ $json.success === false }}',
                    type: 'boolean',
                },
                {
                    id: 'aifail-20260813-2',
                    name: 'ai_extraction_error',
                    value: "={{ ($json.success === false) ? String($json.ERROR || $json.error || 'ai_extraction_failed') : '' }}",
                    type: 'string',
                },
            ],
        },
        includeOtherFields: false,
        options: {},
    };

    @node({
        id: 'invoicedocex01-merge-01',
        name: 'Merge Local + AI',
        type: 'n8n-nodes-base.merge',
        version: 3.2,
        position: [1400, 300],
    })
    MergeLocalAi = {
        mode: 'combine',
        combineBy: 'combineByPosition',
        options: {},
    };

    @node({
        id: 'invoicedocex01-select-01',
        name: 'Select',
        /*__n8n__*/ notes: "[A1 per-type date guard 2026-08-13] Per-type no longer emits DOC_DATE when its own pick is\nAI_ONLY. Established from persisted pick sources: base resolved the date from LOCAL, per-type\nthen ran with an empty local leg and overwrote it with the raw AI value -- 221 of 222\ndisagreeing rows have DOC_DATE == AI_DOC_DATE and zero have DOC_DATE == LOCAL_DOC_DATE.\nCost: 60 rows where base produced no date now complete with an empty one rather than an\nunverified AI read.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1680, 300],
    })
    Select = {
        jsCode: `// Select -- THE PER-TYPE EXTRACTION POINT'S OWN VERDICT. Merge already combined
// LOCAL_*/AI_* onto ONE item. Single source present wins outright, never a blocked
// document (owner ruling).
//
// [two-point selection 2026-08-12] SELECTION LIVES INSIDE THE EXTRACTION POINT.
// Owner's ruling: "selection allwase inside the extraction point ... i think invoice action
// router dose seperate selection step.. should be exact like it but inside the per type
// extraction point". This node is that step, carried over VERBATIM from
// indoxV2ActionsGDoc01/'Select Per Type Values' -- same pick() precedence, same [gap-1]/
// [gap-2] fallbacks, same DOC_ID consolidation, same completion-flag rules, same bounded
// stage-miss backoff. Nothing is re-derived and nothing is invented here.
//
// WHAT THE MOVE REMOVES, and why it is a simplification rather than a relocation:
//   * The router node ran in "Run Once for All Items" mode over a BATCH, so it could not use
//     a named-node .item accessor and had to pair the extractor's returns to the
//     pre-extraction rows BY INDEX -- with an explicit refusal when the lengths disagreed,
//     because 'Call <X>DocEx01' has onError=continueRegularOutput and a shed extractor
//     returns fewer items than were sent. Here that whole class of defect is structurally
//     absent: 'Call InvoiceDocEx01'/'Call ShipmentDocEx01' run mode=each, so ONE execution
//     of this workflow handles exactly ONE document and 'Doc In' holds exactly one item.
//     The pairing is identity. The invariant is asserted below rather than assumed.
//   * The router had to read TYPE/INVOICE_ID/DOC_ID/SHIPMENT_DOC_ID/LINKED_INVOICE_ID/
//     STATUS/the retry counter off a separate pre-extraction node; here they arrive on the
//     'Doc In' contract, which already carries all seven.
//
// ONE THING DELIBERATELY DOES NOT MOVE: the 'PER TYPE GATE REOPEN' ACTION_LOG marker.
// ACTION_LOG is not on the contract and does not belong on it -- it is an append-only column
// (trg_incdoc_action_log_append) whose pre-extraction value the router already reads inside
// 'Build Per Type Upsert' to build the log entry. The marker is appended there, in the node
// that already owns that field, instead of widening this sub-workflow's input by a large
// text column purely to hand it straight back.

// [stage-retry 2026-08-10] A STAGE THAT PRODUCED NO ANSWER MUST NOT STAMP, AND MUST BE BOUNDED.
// Un-stamping alone is an unbounded loop, which is strictly worse than the freeze it replaces.
// This is errorHandler01/'Backoff + Dead-letter' verbatim, expressed in JS because the value is
// carried out through the existing upsert rather than a second postgres node:
//   the retry counter | NEXT_RETRY_AT = now() + 5*3^(old count) minutes, ALWAYS a real time
//   | at >=5 the row retires to STATUS 'MAX_ITERATIONS' | never touches COMPLETED or OLD.
// STATE IS READ FROM \`src\`, NOT FROM THE OBJECT BEING WRITTEN: the object under construction
// carries provenance columns only -- no STATUS and no the retry counter. Reading the counter off it
// would restart the count at 1 on every pass (an unbounded 5-minute loop) and would silently
// bypass the COMPLETED/OLD guard. \`src\` is the pre-extraction row, here the 'Doc In' contract.
// [always-complete 2026-08-17] __recordStageMiss removed (owner: no miss-retry machinery).

const has = v => v !== null && v !== undefined && String(v).trim() !== '';
// [B34 2026-08-09] Amounts are compared NUMERICALLY: \`10,069.00\` and \`10069.00\` are the
// same amount, and comparing raw strings recorded 15 false DISAGREE verdicts in 92 pairs.
// Equality only -- the value written is still the raw winner.
const canonAmount = v => String(v).replace(/[\\s,]/g, '');
// [B34 2026-08-09] AN EMPTY JSON ARRAY IS A NON-ANSWER, NOT A VALUE. The AI leg returns the
// literal string \`[]\` when it finds no shipment/order ids -- 2,213 live rows carry it -- and
// has() counted that as present. On a row where only the AI leg answered, pick() therefore
// returned \`[]\` and it was WRITTEN INTO the value column. It also silently disabled the
// [gap-1] fallback below, which exists precisely to fill a shipment's own id in that
// situation.
const realList = v => (has(v) && String(v).trim() !== '[]') ? v : null;
// [B34 2026-08-09] EQUALITY IS DETECTED ON THE CANONICAL FORM, NEVER ON THE RAW STRING.
// \`canon\` is optional and touches ONLY the equality test -- pick() still returns the raw
// winner, so this changes provenance LABELS and can never change a written value.
// It is passed PER FIELD, never blanket, and every choice is evidence-led (measured live
// over the 7,332-row non-fixture fleet, tmp/b34/m1-baseline.sql):
//   DOC_AMOUNT   92 pairs, 48 exact, 63 ignoring thousands separators -- 15 false
//               disagreements of the form \`10,069.00\` vs \`10069.00\`.
//   COMPANY_ID  140 pairs, 131 exact, 131 caseless -- folding changes NOTHING here and
//               could mask a real difference, so NO canon is passed. DOC_ID likewise
//               (68 exact = 68 caseless of 130). DOC_DATE likewise (66 = 66 of 155: not a
//               single punctuation-only pair exists), so no date normaliser is invented.
// \`prefer\` exists ONLY because BsDocEx01/'Select (BS)' deliberately reverses the tie-break:
// balance sheets are AI-led with local supplementing 'where it helps', per the owner's
// framing. That reversal is a PARAMETER, not a fourth copy of this function.
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

// TYPE comes from the pre-extraction row: this node's input is the merged provenance payload,
// which carries LOCAL_*/AI_* but not TYPE.
const ROUTER_DEFAULT_TYPE = 'INVOICE';

// ONE DOCUMENT PER EXECUTION -- asserted, not assumed. 'Call <X>DocEx01' runs mode=each, so
// 'Doc In' holds exactly one item and it is the pre-extraction row for every item here. If the
// caller is ever switched to mode=once this stops being true, and a silently wrong pairing
// writes ANOTHER document's values into this row -- far worse than a refused sweep the state
// machine simply retries. So it fails loudly instead.
const __docIn = $('Doc In').all();
if (__docIn.length !== 1) {
  throw new Error('Per-type extractor expects exactly one document per execution (Doc In=' +
    __docIn.length + '). Caller must run mode=each. Refusing to guess the pairing.');
}
const prev = __docIn[0].json || {};

return $input.all().map(item => {
  const d = item.json;
  const docType = String(prev.TYPE || ROUTER_DEFAULT_TYPE).toUpperCase();
  void docType;

  // The picks survive the split for ONE reason: the completion flags below must distinguish
  // "the query ran and found nothing" from "the query never ran", and that is a fact about the
  // EXTRACTION, not about the value. Nothing here is written to the row any more -- the [A1]
  // date guard, the shipment fallback, the DOC_ID fill and the provenance string all moved to
  // SelectType01 with the decision they belong to.
  const idPick     = pick(d.LOCAL_DOC_ID,      d.AI_DOC_ID,        'LOCAL');
  const datePick   = pick(d.LOCAL_DOC_DATE,    d.AI_DOC_DATE,      'LOCAL');
  const amountPick = pick(d.LOCAL_DOC_AMOUNT,  d.AI_DOC_AMOUNT,    'LOCAL', canonAmount);
  const shipPick   = pick(realList(d.LOCAL_SHIPMENT_IDS), realList(d.AI_SHIPMENT_IDS), 'LOCAL');
  const purchPick  = pick(realList(d.LOCAL_ORDER_IDS),   realList(d.AI_ORDER_IDS),     'LOCAL');

  // [pure extraction 2026-08-25, owner order] THIS POINT REPORTS WHAT ITS ENGINES SAW. NOTHING ELSE.
  // Deciding which reading becomes the document's value is a different job, done by a different
  // action (select_type -> SelectType01) that sees things this one cannot: the supplier's ledger
  // line, the filename, the trusted-supplier list, and the values the row already holds. It also
  // has to be re-runnable when one of those changes, which extraction is not -- extraction depends
  // on the file, and the file does not change.
  // So the finals that used to be written here -- DOC_DATE, DOC_TOTAL_AMOUNT, SHIPMENT_DOC_ID,
  // PURCHASE_ID, DOC_ID, LINKED_INVOICE_ID -- and the provenance string that explained them are
  // gone from this object. The picks below are still computed, because the completion flags and
  // the failure surfacing genuinely depend on whether anything was read.
  const out = {
    ID: prev.ID,
    LOCAL_DOC_ID: d.LOCAL_DOC_ID || null, LOCAL_DOC_DATE: d.LOCAL_DOC_DATE || null,
    LOCAL_DOC_AMOUNT: d.LOCAL_DOC_AMOUNT || null, LOCAL_SHIPMENT_IDS: d.LOCAL_SHIPMENT_IDS || null,
    LOCAL_ORDER_IDS: d.LOCAL_ORDER_IDS || null,
    AI_DOC_ID: d.AI_DOC_ID || null, AI_DOC_DATE: d.AI_DOC_DATE || null,
    AI_DOC_AMOUNT: d.AI_DOC_AMOUNT || null, AI_SHIPMENT_IDS: d.AI_SHIPMENT_IDS || null,
    AI_ORDER_IDS: d.AI_ORDER_IDS || null,
    // CARRY THE LEG STATUSES OUT AS REAL KEYS. They gate the completion markers below and
    // must survive to the upsert so downstream can tell "ran and found nothing" (an ANSWER,
    // which closes the field's gate) from "leg disabled" (not an answer, which must not).
    LOCAL_STATUS: d.LOCAL_STATUS || null,
    AI_STATUS: d.AI_STATUS || null
  };

  // [gap-1] moved to SelectType01 with the rest of the value decisions: filling a shipment's own
  // id into SHIPMENT_DOC_ID when neither list leg answered is a CHOICE about what the value should
  // be, and every such choice now has exactly one author.

  // [gap-2] INVOICE/ORDER-ONLY, FILL-ONLY. invoiceDecide gates query_invoice_id on
  // \`!doc.INVOICE_ID\`, a column no extractor path writes -- the extractor writes
  // the doc number (now DOC_ID; COMPANY_DOC_ID retired 2026-08-17) -- so the gate could never be satisfied. Deliberately does
  // NOT stamp INVOICE_ID_COMPLETED: the query stays available as a fallback if this ever
  // resolves nothing. INACTIVE on SHIPMENT (a shipment's own id is not an invoice number).
  // [gap-2 CLOSED 2026-08-19] INVOICE_ID RETIRED. It was written here fill-only from idPick and
  // read back three lines later as the rule-C tie-breaker -- the same function both authoring and
  // consulting it. Nothing else consumed it: the decide gate it was meant to satisfy
  // (query_invoice_id on !doc.INVOICE_ID) is legacy, the routers only passed it through, and on
  // every live row it was a verbatim copy of DOC_ID (measured 2026-08-19 on test01:
  // INVOICE_ID = DOC_ID = INV/2026/05771). DOC_ID is the one document-number column.

  // [DOC_ID 2026-08-10] WRITE THE CONSOLIDATED DOCUMENT ID.
  // DOC_ID was created and backfilled by the 2026-08-06 consolidation migration
  // (scripts/ops/migrations/2026-08-06_doc_id_consolidation.sql) but NO node was ever
  // taught to write it. Precedence is carried VERBATIM from the migration so the column
  // keeps ONE definition:
  //   SHIPMENT    -> the document's OWN id (idPick). Its linked invoice goes to
  //                  LINKED_INVOICE_ID rather than being discarded -- the migration found
  //                  211 of 212 shipment rows held DIFFERENT documents in the two columns.
  //   other TYPEs -> rule C: when AI agrees with INVOICE_ID and NOT with the own id,
  //                  take INVOICE_ID; otherwise the own id, else INVOICE_ID.
  // FILL-ONLY, mirroring the migration's \`where coalesce("DOC_ID",'') = ''\`: an existing
  // DOC_ID is never overwritten, so this can only supply a missing value.
  // Rule C collapsed with INVOICE_ID's retirement: it existed only to arbitrate between this
  // point's own pick and INVOICE_ID, and its canonical comparison could never fire for a
  // structured reference anyway -- canon('INV/2026/05771') is 'INV202605771', which can never
  // equal a bare number, so the branch was dead for every Odoo-style id. The document's own
  // resolved id is now the single source, still FILL-ONLY (an existing DOC_ID is never
  // overwritten), which is what let 2016 survive on 1771420485406c1b684.
  // The DOC_ID fill and the shipment's LINKED_INVOICE_ID carry both moved to SelectType01 -- they
  // are decisions about identity, and identity is exactly what must have one author. The C11
  // junk-id rejector lives there too, which is the point its own note made and the old shape
  // could not honour: it guarded SELECTED_DOC_ID while this line wrote DOC_ID unchecked.

  // [completion-flags 2026-08-10] STAMP THE ANSWER, NOT THE ATTEMPT.
  // This was an unconditional \`= true\` in this very node, so a pass that resolved nothing
  // asserted that per-type extraction was done: the decide gate
  //   (STATUS!=='COMPLETED' && API_TOOLS_ID && !PER_TYPE_EXTRACTION_COMPLETED)
  // then closed for good and the document fell through to the legacy single-value Query*
  // extractors, which is why those could not reach zero by deletion. Proven by the owner: 10
  // invoices with SELECTION_DEBUG_PERTYPE.DOC_ID='NONE' were re-queried with q_v3_invoice_id
  // against the SAME API_TOOLS_ID and hit 10/10. The query works; the flag lied.
  // "An answer" mirrors 'Select Base Values' exactly -- ANY resolved field counts as progress,
  // because each one independently unblocks a downstream gate.
  const __answered = !!(idPick.val || datePick.val || amountPick.val || shipPick.val
                        || purchPick.val);
  // [always-complete 2026-08-17, owner order] EVERY action ALWAYS sets its *_COMPLETED
  // flag. A pass that resolved nothing is an ANSWER about the document (unresolved fields
  // stay ABSENT per the two-point doctrine); ACTION_RESTART is the only re-run and the
  // restart action resets the flags, so one extraction per epoch, ever. The miss-retry
  // machinery (__recordStageMiss / the retry counter bookkeeping / NEXT_RETRY_AT parks) is
  // REMOVED — the legacy Query* fallbacks it protected are gone from decide, so a miss
  // terminalizes honestly instead of looping.
  out.PER_TYPE_EXTRACTION_COMPLETED = true;
  void __answered;

  // [two-point completion 2026-08-11] CLOSE THE GATES THIS STAGE OWNS -- INCLUDING ON A MISS.
  // "We looked and there is none" is an ANSWER, not a failure. Without this the four
  // single-value Query* extractors can never reach zero by deletion: per-type resolves
  // nothing for a field, leaves the *_COMPLETED column NULL, and shipmentDecide/invoiceDecide
  // fall straight through to the legacy fallback on the very next sweep -- forever.
  // Measured on the live table 2026-08-10: SHIPMENT amount, 351 queries ran and 97 returned a
  // value (72% confirmed-empty); only 258 of 1048 shipments (24.6%) carry an amount at all,
  // because a delivery note structurally has no total.
  // The test is "is the downstream resolver stronger than this one?" -- for all four it is NOT:
  // per-type runs the settings-driven q_v3_* query for this TYPE, each a primary plus a
  // \`fallbacks\` chain carrying value_regex and value_validations; the Query* workflows fire a
  // FLAT action_value list with no fallback chain against the SAME API_TOOLS_ID.
  // INVOICE_ID is deliberately NOT stamped -- [gap-2] above records why.
  // STAMPED ONLY WHEN THE QUERY ACTUALLY RAN. 'Build Local Skipped' sets LOCAL_STATUS
  // 'skipped: extraction_local_enabled=false'; nothing looked, so nothing may be asserted.
  if (String(out.LOCAL_STATUS || '') === 'ran') {
    out.DOC_DATE_COMPLETED         = true;
    out.DOC_TOTAL_AMOUNT_COMPLETED = true;
    out.PURCHASE_ID_COMPLETED      = true;
    out.SHIPMENT_ID_COMPLETED      = true;
  }

  // [two-point completion 2026-08-11] AI_EXTRACTION_COMPLETED BELONGS AT THIS POINT.
  // \`extract_invoice_google_ai\` POSTs to http://n8n-webhook:5678/webhook/invoice_extractor. So does
  // this workflow's 'Extract via Webhook' -- the SAME endpoint, the same Google Document AI
  // processor. This point has therefore ALREADY done the AI extraction by the time this node
  // runs. The legacy action was never more than a second identical call whose only unique
  // effect was setting this flag. AI_COMPANY_ID / AI_TYPE are not this point's business and
  // are NOT lost: the BASE point owns company and type and stamps FIGURE_COMPANY_COMPLETED /
  // FIGURE_TYPE_COMPLETED from its own AI leg. Stamped only when the AI leg RAN -- 'Build AI
  // Skipped' sets AI_STATUS 'skipped: ...', and asserting completion there would be a lie.
  if (String(out.AI_STATUS || '') === 'ran') out.AI_EXTRACTION_COMPLETED = true;

  // BUILT FROM THE NORMALISED LEG STATUSES (out.*), NOT THE RAW ONES (d.*). 'Merge Local + AI'
  // can omit the key entirely, and JSON.stringify DROPS an undefined value rather than emitting
  // null -- so reading d.* here produced a debug string missing "LOCAL_STATUS":null on exactly
  // those rows, while the router (which only ever saw this node's normalised output) emitted it.
  // Caught by differential fuzz, not in production: 13,904 of 40,000 generated rows differed.
  // SURFACE A FAILED LEG ON THE DOCUMENT LINE. ai_failed / ai_extraction_error were already
  // computed by 'Build AI Result' but died at the merge, which carries only the two *_STATUS
  // keys -- so a failure was visible nowhere: the sub-workflow ends 'success' (both leg calls
  // continue on error), and the ERROR column is only ever written by the action layer on a
  // FAILED action. Writing it here is the only point that knows a leg died.
  const __legFail = [];
  if (String(out.LOCAL_STATUS || '').indexOf('failed:') === 0) __legFail.push('local ' + out.LOCAL_STATUS);
  if (String(out.AI_STATUS    || '').indexOf('failed:') === 0) __legFail.push('ai ' + out.AI_STATUS);
  if (__legFail.length) out.ERROR = 'per-type extraction: ' + __legFail.join(' | ');

  // SELECTION_DEBUG_PERTYPE is written by SelectType01 now -- it records which source won each
  // value, and this point no longer decides that. Two writers for one provenance string would
  // mean the string sometimes described a decision that had since been re-made.
  return { json: out };
});
`,
    };

    @node({
        id: 'invoicedocex01-return-01',
        name: 'Return',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1960, 300],
    })
    Return_ = {
        mode: 'manual',
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
        this.DocIn.out(0).to(this.CheckLocalEnabled.in(0));
        this.DocIn.out(0).to(this.CheckAiEnabled.in(0));
        this.CheckLocalEnabled.out(0).to(this.IfLocalDisabled.in(0));
        this.IfLocalDisabled.out(0).to(this.BuildLocalSkipped.in(0));
        this.IfLocalDisabled.out(1).to(this.CallInvoiceJqExV3.in(0));
        this.CallInvoiceJqExV3.out(0).to(this.BuildLocalResult.in(0));
        this.CheckAiEnabled.out(0).to(this.IfAiDisabled.in(0));
        this.IfAiDisabled.out(0).to(this.BuildAiSkipped.in(0));
        this.IfAiDisabled.out(1).to(this.ExtractViaWebhook.in(0));
        this.ExtractViaWebhook.out(0).to(this.BuildAiResult.in(0));
        this.BuildLocalSkipped.out(0).to(this.MergeLocalAi.in(0));
        this.BuildLocalResult.out(0).to(this.MergeLocalAi.in(0));
        this.BuildAiSkipped.out(0).to(this.MergeLocalAi.in(1));
        this.BuildAiResult.out(0).to(this.MergeLocalAi.in(1));
        this.MergeLocalAi.out(0).to(this.Select.in(0));
        this.Select.out(0).to(this.Return_.in(0));
    }
}
