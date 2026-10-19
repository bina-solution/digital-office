import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Balance Sheet Document Extraction (AI-led, local supplements)
// Nodes   : 14  |  Connections: 16
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// DocIn                              executeWorkflowTrigger
// CheckAiEnabledBs                   postgres                   [creds]
// IfAiDisabledBs                     if
// BuildAiSkippedBs                   set
// ExtractViaWebhookBs                executeWorkflow            [onError→regular] [creds]
// BuildAiResultBs                    code
// CheckLocalEnabledBs                postgres                   [creds]
// IfLocalDisabledBs                  if
// BuildLocalSkippedBs                set
// CallBsJqExV3                       executeWorkflow            [onError→regular]
// BuildLocalResultBs                 set
// MergeAiLocalBs                     merge
// SelectBs                           code
// Return_                            set
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// DocIn
//    → CheckAiEnabledBs
//      → IfAiDisabledBs
//        → BuildAiSkippedBs
//          → MergeAiLocalBs
//            → SelectBs
//              → Return_
//       .out(1) → ExtractViaWebhookBs
//          → BuildAiResultBs
//            → MergeAiLocalBs (↩ loop)
//    → CheckLocalEnabledBs
//      → IfLocalDisabledBs
//        → BuildLocalSkippedBs
//          → MergeAiLocalBs.in(1) (↩ loop)
//       .out(1) → CallBsJqExV3
//          → BuildLocalResultBs
//            → MergeAiLocalBs.in(1) (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Doc In":{"main":[[{"node":"Check AI Enabled (BS)","type":"main","index":0},{"node":"Check Local Enabled (BS)","type":"main","index":0}]]},"Check AI Enabled (BS)":{"main":[[{"node":"If AI Disabled (BS)","type":"main","index":0}]]},"If AI Disabled (BS)":{"main":[[{"node":"Build AI Skipped (BS)","type":"main","index":0}],[{"node":"Extract via Webhook (BS)","type":"main","index":0}]]},"Extract via Webhook (BS)":{"main":[[{"node":"Build AI Result (BS)","type":"main","index":0}]]},"Check Local Enabled (BS)":{"main":[[{"node":"If Local Disabled (BS)","type":"main","index":0}]]},"If Local Disabled (BS)":{"main":[[{"node":"Build Local Skipped (BS)","type":"main","index":0}],[{"node":"Call BS JQ Ex V3","type":"main","index":0}]]},"Call BS JQ Ex V3":{"main":[[{"node":"Build Local Result (BS)","type":"main","index":0}]]},"Build AI Skipped (BS)":{"main":[[{"node":"Merge AI + Local (BS)","type":"main","index":0}]]},"Build AI Result (BS)":{"main":[[{"node":"Merge AI + Local (BS)","type":"main","index":0}]]},"Build Local Skipped (BS)":{"main":[[{"node":"Merge AI + Local (BS)","type":"main","index":1}]]},"Build Local Result (BS)":{"main":[[{"node":"Merge AI + Local (BS)","type":"main","index":1}]]},"Merge AI + Local (BS)":{"main":[[{"node":"Select (BS)","type":"main","index":0}]]},"Select (BS)":{"main":[[{"node":"Return","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"f5d175fb-c738-4607-8ef0-bf03c48e8a0b","name":"role:extractor"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-06T12:30:31.436Z","createdAt":"2026-08-06T12:30:31.436Z","role":"workflow:owner","workflowId":"BsDocEx01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'BsDocEx01',
    name: 'Balance Sheet Document Extraction (AI-led, local supplements)',
    active: true,
    isArchived: false,
    tags: ['indox-app', 'role:extractor', 'app:indox'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class BalanceSheetDocumentExtractionAiLedLocalSupplementsWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'bsde-trigger-01',
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
                    name: 'BS_EXTRACTION_USE_CACHE',
                },
                {
                    name: 'LINK_CONNECTION',
                },
                {
                    name: '__instance',
                },
            ],
        },
    };

    @node({
        id: 'bsde-check-ai-01',
        name: 'Check AI Enabled (BS)',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [280, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    CheckAiEnabledBs = {
        operation: 'executeQuery',
        query: "=SELECT COALESCE((SELECT value FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('BsDocEx01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.settings WHERE key='extraction_ai_enabled'), 'true') AS ai_enabled",
        options: {},
    };

    @node({
        id: 'bsde-if-ai-01',
        name: 'If AI Disabled (BS)',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [560, 0],
    })
    IfAiDisabledBs = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: 'bsde-ai-cond-01',
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
        id: 'bsde-ai-skip-01',
        name: 'Build AI Skipped (BS)',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [840, -120],
    })
    BuildAiSkippedBs = {
        mode: 'manual',
        assignments: {
            assignments: [
                {
                    id: 'bsda0',
                    name: 'AI_DOC_DATE',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'bsda1',
                    name: 'AI_DOC_AMOUNT',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'bsda2',
                    name: 'BS_EXTRACTED_LINES',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'bsda3',
                    name: 'BS_EXTRACTION_VERIFIED',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'bsda4',
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
        id: 'bsde-extract-ai-01',
        name: 'Extract via Webhook (BS)',
        /*__n8n__*/ notes: "Converted httpRequest -> executeWorkflow 2026-08-11. The webhook transport created a new Bull job while this execution already held a slot, so it burned its full 600000ms timeout waiting behind the queue — measured 601s avg. Same fix as ShipmentDocEx01/InvoiceDocEx01 (602s -> 2-4s). LINK and use_cache carried over verbatim from the original body.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [840, 120],
        credentials: { httpBasicAuth: { id: 'azPhHBvOWaf9IsEA', name: 'Incoming Documents [env-managed]' } },
        onError: 'continueRegularOutput',
    })
    ExtractViaWebhookBs = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ExtractBalanceSheet01',
            mode: 'id',
            cachedResultName: 'Balance Sheet Extractor',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                LINK: "={{ $('Doc In').item.json.LINK }}",
                use_cache: "={{ String($('Doc In').item.json.BS_EXTRACTION_USE_CACHE ?? true) }}",
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
                {
                    id: '__instance',
                    displayName: '__instance',
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
        id: 'bsde-ai-result-01',
        name: 'Build AI Result (BS)',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1120, 120],
    })
    BuildAiResultBs = {
        jsCode: `const raw = $json;
const out = { AI_DOC_DATE: null, AI_DOC_AMOUNT: null, BS_EXTRACTED_LINES: null,
              BS_EXTRACTION_VERIFIED: null, AI_STATUS: 'ran' };
if (raw.ai_disabled) {
  out.AI_STATUS = 'skipped: ' + (raw.error || 'ai_disabled');
} else if (raw.success) {
  out.AI_DOC_DATE = raw.data?.documentDate || null;
  out.AI_DOC_AMOUNT = raw.data?.summary?.documentTotal || null;
  out.BS_EXTRACTED_LINES = JSON.stringify(raw);
  out.BS_EXTRACTION_VERIFIED = raw.data?.summary?.totalsMatch ?? null;
} else {
  // 'failed: ' is the prefix the per-type lanes and the base leg share (2026-09-03): the Select
  // node turns it into ERROR = 'per-type extraction: ai failed: <reason>' on the row.
  out.AI_STATUS = 'failed: ' + (raw.error || 'extraction failed');
}
return [{ json: out }];
`,
    };

    @node({
        id: 'bsde-check-local-01',
        name: 'Check Local Enabled (BS)',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [280, 560],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    CheckLocalEnabledBs = {
        operation: 'executeQuery',
        query: "=SELECT COALESCE((SELECT value FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('BsDocEx01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.settings WHERE key='extraction_local_enabled'), 'true') AS local_enabled",
        options: {},
    };

    @node({
        id: 'bsde-if-local-01',
        name: 'If Local Disabled (BS)',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [560, 560],
    })
    IfLocalDisabledBs = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: 'bsde-local-cond-01',
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
        id: 'bsde-local-skip-01',
        name: 'Build Local Skipped (BS)',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [840, 440],
    })
    BuildLocalSkippedBs = {
        mode: 'manual',
        assignments: {
            assignments: [
                {
                    id: 'bsdl0',
                    name: 'LOCAL_DOC_DATE',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'bsdl1',
                    name: 'LOCAL_DOC_AMOUNT',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'bsdl2',
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
        id: 'bsde-call-jqex-01',
        name: 'Call BS JQ Ex V3',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [840, 680],
        onError: 'continueRegularOutput',
        retryOnFail: false,
    })
    CallBsJqExV3 = {
        workflowId: {
            __rl: true,
            value: 'JQExV3BS00000001',
            mode: 'list',
            cachedResultUrl: '/workflow/JQExV3BS00000001',
            cachedResultName: 'BS JQ Ex V3',
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
        id: 'bsde-local-result-01',
        name: 'Build Local Result (BS)',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1120, 680],
    })
    BuildLocalResultBs = {
        mode: 'manual',
        assignments: {
            assignments: [
                {
                    id: 'bsdr0',
                    name: 'LOCAL_DOC_DATE',
                    value: '={{ $json.DOC_DATE || null }}',
                    type: 'string',
                },
                {
                    id: 'bsdr1',
                    name: 'LOCAL_DOC_AMOUNT',
                    value: '={{ $json.BALANCE || null }}',
                    type: 'string',
                },
                {
                    id: 'bsdr2',
                    name: 'LOCAL_STATUS',
                    value: 'ran',
                    type: 'string',
                },
            ],
        },
        includeOtherFields: false,
        options: {},
    };

    @node({
        id: 'bsde-merge-01',
        name: 'Merge AI + Local (BS)',
        type: 'n8n-nodes-base.merge',
        version: 3.2,
        position: [1400, 300],
    })
    MergeAiLocalBs = {
        mode: 'combine',
        combineBy: 'combineByPosition',
        options: {},
    };

    @node({
        id: 'bsde-select-01',
        name: 'Select (BS)',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1680, 300],
    })
    SelectBs = {
        jsCode: `// Select (BsDocEx01) -- AI-led: BS_EXTRACTED_LINES has no local
// equivalent (a local q_v3 query can't do per-line table extraction), so
// it passes through from AI untouched. For the two summary scalars
// (date/balance), local supplements 'where it helps': single source
// wins outright as everywhere else, but on disagreement AI wins, not
// local -- the deliberate reversal of Invoice/Shipment/Base's tie-break,
// per the owner's 'AI-led, local pass where it helps' framing.
const has = v => v !== null && v !== undefined && String(v).trim() !== '';
// [B34 2026-08-09] Amounts are compared NUMERICALLY: \`10,069.00\` and \`10069.00\` are the
// same amount, and comparing raw strings recorded 15 false DISAGREE verdicts in 92 pairs.
// Equality only -- the value written is still the raw winner.
const canonAmount = v => String(v).replace(/[\\s,]/g, '');
// [B34 2026-08-09] EQUALITY IS DETECTED ON THE CANONICAL FORM, NEVER ON THE RAW STRING.
// \`canon\` is optional and touches ONLY the equality test -- pick() still returns the raw
// winner, so this changes provenance LABELS and can never change a written value.
// It is passed PER FIELD, never blanket, and every choice is evidence-led (measured live
// over the 7,332-row non-fixture fleet, tmp/b34/m1-baseline.sql):
//   TYPE        169 two-leg pairs, 0 exact, 158 caseless -- the local leg emits \`shipment\`,
//               Gemini emits \`SHIPMENT\`, so AGREE was structurally unreachable and every
//               two-legged row was mislabelled DISAGREE_PREFER_LOCAL (final-indox.md B33.6).
//   DOC_AMOUNT   92 pairs, 48 exact, 63 ignoring thousands separators -- 15 false
//               disagreements of the form \`10,069.00\` vs \`10069.00\`.
//   COMPANY_ID  140 pairs, 131 exact, 131 caseless -- folding changes NOTHING here and
//               could mask a real difference, so NO canon is passed. DOC_ID likewise
//               (68 exact = 68 caseless of 130). DOC_DATE likewise (66 = 66 of 155: not a
//               single punctuation-only pair exists), so no date normaliser is invented.
function pick(ai, local, canon) {
  const a = has(ai) ? String(ai).trim() : null;
  const l = has(local) ? String(local).trim() : null;
  if (a && l) return { val: a, source: (canon ? canon(a) === canon(l) : a === l) ? 'AGREE' : 'DISAGREE_PREFER_AI' };
  if (a) return { val: a, source: 'AI_ONLY' };
  if (l) return { val: l, source: 'LOCAL_ONLY' };
  return { val: null, source: 'NONE' };
}
// [pure extraction 2026-08-25, owner order] THIS POINT REPORTS WHAT ITS ENGINES SAW. NOTHING ELSE.
// DOC_DATE and TOTAL_AMOUNT are no longer decided here: SelectType01 does it, with the balance
// sheet's AI-led tie-break preserved exactly (it branches on TYPE) but living in one place with
// every other type's rule. The picks are still computed because the provenance of a leg is a fact
// about the extraction; the VALUE is not this point's to write.
return $input.all().map(item => {
  const d = item.json;
  return { json: {
    ID: $('Doc In').item.json.ID,
    BS_EXTRACTED_LINES: d.BS_EXTRACTED_LINES || null,
    BS_EXTRACTED_LINES_COMPLETED: !!d.BS_EXTRACTED_LINES,
    BS_EXTRACTION_VERIFIED: d.BS_EXTRACTION_VERIFIED,
    BS_LINK_DOCUMENTS_COMPLETED: false,
    LOCAL_DOC_DATE: d.LOCAL_DOC_DATE || null, LOCAL_DOC_AMOUNT: d.LOCAL_DOC_AMOUNT || null,
    AI_DOC_DATE: d.AI_DOC_DATE || null, AI_DOC_AMOUNT: d.AI_DOC_AMOUNT || null,
    // [two-point completion 2026-08-11] CARRY THE LEG STATUSES OUT AS REAL KEYS.
    // They existed only inside the SELECTION_DEBUG_PERTYPE string, which the router's
    // 'Select Per Type Values' overwrites with its own -- so the router could not tell
    // "ran and found nothing" (an ANSWER, which must close the field's gate) from
    // "leg disabled" (not an answer, which must not). Without this the completion markers
    // the router stamps are unreachable and the single-value fallbacks never terminalise.
    LOCAL_STATUS: d.LOCAL_STATUS || null,
    AI_STATUS: d.AI_STATUS || null,
    PER_TYPE_EXTRACTION_COMPLETED: true,
    // [2026-09-03] a leg that failed is written on the row, the same shape the invoice and
    // shipment lanes use — the BS lane never surfaced an AI failure before.
    ...((() => { const f = []; if (String(d.LOCAL_STATUS || '').indexOf('failed:') === 0) f.push('local ' + String(d.LOCAL_STATUS).slice(0, 160)); if (String(d.AI_STATUS || '').indexOf('failed:') === 0) f.push('ai ' + String(d.AI_STATUS).slice(0, 160)); return f.length ? { ERROR: ('per-type extraction: ' + f.join(' | ')).slice(0, 500) } : {}; })()),
  }};
});
`,
    };

    @node({
        id: 'bsde-return-01',
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
        this.DocIn.out(0).to(this.CheckAiEnabledBs.in(0));
        this.DocIn.out(0).to(this.CheckLocalEnabledBs.in(0));
        this.CheckAiEnabledBs.out(0).to(this.IfAiDisabledBs.in(0));
        this.IfAiDisabledBs.out(0).to(this.BuildAiSkippedBs.in(0));
        this.IfAiDisabledBs.out(1).to(this.ExtractViaWebhookBs.in(0));
        this.ExtractViaWebhookBs.out(0).to(this.BuildAiResultBs.in(0));
        this.CheckLocalEnabledBs.out(0).to(this.IfLocalDisabledBs.in(0));
        this.IfLocalDisabledBs.out(0).to(this.BuildLocalSkippedBs.in(0));
        this.IfLocalDisabledBs.out(1).to(this.CallBsJqExV3.in(0));
        this.CallBsJqExV3.out(0).to(this.BuildLocalResultBs.in(0));
        this.BuildAiSkippedBs.out(0).to(this.MergeAiLocalBs.in(0));
        this.BuildAiResultBs.out(0).to(this.MergeAiLocalBs.in(0));
        this.BuildLocalSkippedBs.out(0).to(this.MergeAiLocalBs.in(1));
        this.BuildLocalResultBs.out(0).to(this.MergeAiLocalBs.in(1));
        this.MergeAiLocalBs.out(0).to(this.SelectBs.in(0));
        this.SelectBs.out(0).to(this.Return_.in(0));
    }
}
