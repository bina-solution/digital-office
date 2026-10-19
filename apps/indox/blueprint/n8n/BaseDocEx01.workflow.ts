import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Base Document Extraction (local + AI, parallel)
// Nodes   : 17  |  Connections: 19
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// DocIn                              executeWorkflowTrigger
// NameCompanyMatchOffline            postgres                   [onError→regular] [creds] [alwaysOutput]
// UploadOcr                          executeWorkflow
// CheckLocalEnabledBase              postgres                   [creds]
// IfLocalDisabledBase                if
// BuildLocalSkippedBase              set
// CallJqexv3Base                     executeWorkflow            [onError→regular]
// BuildLocalResultBase               set
// CheckAiEnabledBase                 postgres                   [creds]
// IfAiDisabledBase                   if
// BuildAiSkippedBase                 set
// ExtractBaseViaWebhook              executeWorkflow            [onError→regular] [retry]
// BuildAiResultBase                  set
// MergeLocalAiBase                   merge
// SelectBase                         code
// Return_                            set
// LockMapSetRetryScope               redis                      [onError→regular] [creds]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// DocIn
//    → LockMapSetRetryScope
//      → UploadOcr
//        → CheckLocalEnabledBase
//          → IfLocalDisabledBase
//            → BuildLocalSkippedBase
//              → MergeLocalAiBase
//                → NameCompanyMatchOffline
//                  → SelectBase
//                    → Return_
//           .out(1) → CallJqexv3Base
//              → BuildLocalResultBase
//                → MergeLocalAiBase (↩ loop)
//        → CheckAiEnabledBase
//          → IfAiDisabledBase
//            → BuildAiSkippedBase
//              → MergeLocalAiBase.in(1) (↩ loop)
//           .out(1) → ExtractBaseViaWebhook
//              → BuildAiResultBase
//                → MergeLocalAiBase.in(1) (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Doc In":{"main":[[{"node":"Lock Map Set (retry scope)","type":"main","index":0}]]},"Upload+OCR":{"main":[[{"node":"Check Local Enabled (Base)","type":"main","index":0},{"node":"Check AI Enabled (Base)","type":"main","index":0}]]},"Check Local Enabled (Base)":{"main":[[{"node":"If Local Disabled (Base)","type":"main","index":0}]]},"If Local Disabled (Base)":{"main":[[{"node":"Build Local Skipped (Base)","type":"main","index":0}],[{"node":"Call JQExV3 Base","type":"main","index":0}]]},"Call JQExV3 Base":{"main":[[{"node":"Build Local Result (Base)","type":"main","index":0}]]},"Check AI Enabled (Base)":{"main":[[{"node":"If AI Disabled (Base)","type":"main","index":0}]]},"If AI Disabled (Base)":{"main":[[{"node":"Build AI Skipped (Base)","type":"main","index":0}],[{"node":"Extract Base via Webhook","type":"main","index":0}]]},"Extract Base via Webhook":{"main":[[{"node":"Build AI Result (Base)","type":"main","index":0}]]},"Build Local Skipped (Base)":{"main":[[{"node":"Merge Local + AI (Base)","type":"main","index":0}]]},"Build Local Result (Base)":{"main":[[{"node":"Merge Local + AI (Base)","type":"main","index":0}]]},"Build AI Skipped (Base)":{"main":[[{"node":"Merge Local + AI (Base)","type":"main","index":1}]]},"Build AI Result (Base)":{"main":[[{"node":"Merge Local + AI (Base)","type":"main","index":1}]]},"Merge Local + AI (Base)":{"main":[[{"node":"NAME Company Match (Offline)","type":"main","index":0}]]},"NAME Company Match (Offline)":{"main":[[{"node":"Select Base","type":"main","index":0}]]},"Select Base":{"main":[[{"node":"Return","type":"main","index":0}]]},"Lock Map Set (retry scope)":{"main":[[{"node":"Upload+OCR","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"f5d175fb-c738-4607-8ef0-bf03c48e8a0b","name":"role:extractor"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-06T12:30:31.436Z","createdAt":"2026-08-06T12:30:31.436Z","role":"workflow:owner","workflowId":"BaseDocEx01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'BaseDocEx01',
    name: 'Base Document Extraction (local + AI, parallel)',
    active: true,
    isArchived: false,
    tags: ['indox-app', 'role:extractor', 'app:indox'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class BaseDocumentExtractionLocalAiParallelWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'bde-trigger-01',
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
                    name: 'LINK',
                    type: 'any',
                },
                {
                    name: 'HASH',
                },
                {
                    name: 'LINK_CONNECTION',
                },
                {
                    name: 'NAME',
                },
                {
                    name: '__instance',
                },
            ],
        },
    };

    @node({
        id: 'bde-name-match-01',
        name: 'NAME Company Match (Offline)',
        /*__n8n__*/ notes: "[two-point rule 2026-08-17, owner order] The filename company matcher, MOVED here from indoxV2ActionsGlobal01's figure_company_offline action (query ported verbatim, B31 2026-08-09 semantics intact: anchored prefix, min length 5, unambiguous only, longest match wins, mirrors indoxSettings01/'Companies' identity construction). Runs for every doc in the base pass; Select Base uses it as the FILL-ONLY third company leg when both OCR legs (LOCAL/AI) produced nothing. Exactly one result row per input item — Select Base pairs by index and refuses a count mismatch.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [1100, 520],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    NameCompanyMatchOffline = {
        operation: 'executeQuery',
        query: `=-- [B31 2026-08-09, moved 2026-08-17] Link-independent company resolution from the FILENAME.
-- Anchored prefix only, min length 5, unambiguous only, longest match wins.
-- Mirrors indoxSettings01/'Companies' map construction (identifier fields + blacklist,
-- primary = first non-blank) so this and the settings map cannot drift on identity.
-- [multi-instance 2026-08-28] Schema resolved from __instance; absent resolves to public, which
-- is today's behaviour and becomes a loud failure once the compatibility views are dropped.
with idents as (
  select c.id as cid, c."שם חברה" as cname, v.ord, v.ident
  from {{ (() => { const i = String($('Doc In').item.json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('BaseDocEx01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.companies c,
       lateral (values (1, c."מזהה 1"), (2, c."מזהה 2"), (3, c."שם ספק מפריוריטי")) v(ord, ident)
  where v.ident is not null and v.ident <> ''
    and position('פריוריטי' in v.ident) = 0
),
prim as (
  select distinct on (cid) cid, cname, ident as primary_ident
  from idents order by cid, ord
),
hit as (
  select p.primary_ident, p.cname, length(p.cname) as len
  from prim p
  where p.cname is not null
    and length(p.cname) >= 5
    and position(p.cname in coalesce($1, '')) = 1
)
select
  case when (select count(distinct primary_ident) from hit) = 1
       then (select primary_ident from hit order by len desc limit 1) end as company_id,
  case when (select count(distinct primary_ident) from hit) = 1
       then (select cname from hit order by len desc limit 1) end as matched_name,
  (select count(distinct primary_ident) from hit) as candidates;`,
        options: {
            queryBatching: 'independently',
            queryReplacement: "={{ $json.NAME || $('Doc In').item.json.NAME || '' }}",
        },
    };

    @node({
        id: 'bde-upload-01',
        name: 'Upload+OCR',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [280, 300],
    })
    UploadOcr = {
        workflowId: {
            __rl: true,
            value: 'indoxV2UploadApiTools01',
            mode: 'list',
            cachedResultUrl: '/workflow/indoxV2UploadApiTools01',
            cachedResultName: 'Upload Doc To API TOOLS',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                LINK: '={{ $json.LINK }}',
                HASH: '={{ $json.HASH }}',
                ID: '={{ $json.ID }}',
                LINK_CONNECTION: '={{ $json.LINK_CONNECTION }}',
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
                },
                {
                    id: 'HASH',
                    displayName: 'HASH',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                },
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
        id: 'bde-check-local-01',
        name: 'Check Local Enabled (Base)',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [560, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    CheckLocalEnabledBase = {
        operation: 'executeQuery',
        query: "=SELECT COALESCE((SELECT value FROM {{ (() => { const i = String($('Doc In').item.json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('BaseDocEx01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.settings WHERE key='extraction_local_enabled'), 'true') AS local_enabled",
        options: {},
    };

    @node({
        id: 'bde-if-local-01',
        name: 'If Local Disabled (Base)',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [840, 0],
    })
    IfLocalDisabledBase = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: 'bde-local-cond-01',
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
        id: 'bde-local-skip-01',
        name: 'Build Local Skipped (Base)',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1120, -120],
    })
    BuildLocalSkippedBase = {
        mode: 'manual',
        assignments: {
            assignments: [
                {
                    id: 'bdel0',
                    name: 'LOCAL_COMPANY_ID',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'bdel1',
                    name: 'LOCAL_TYPE',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'bdel2',
                    name: 'LOCAL_DOC_DATE',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'bdel3',
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
        id: 'bde-call-jqex-base-01',
        name: 'Call JQExV3 Base',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1120, 120],
        onError: 'continueRegularOutput',
        retryOnFail: false,
    })
    CallJqexv3Base = {
        workflowId: {
            __rl: true,
            value: 'JQExV3Base000001',
            mode: 'list',
            cachedResultUrl: '/workflow/JQExV3Base000001',
            cachedResultName: 'DocBase JQ Ex V3',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                ID: "={{ $('Doc In').item.json.ID }}",
                API_TOOLS_ID: "={{ $('Upload+OCR').item.json.file_id }}",
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
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'bde-local-result-01',
        name: 'Build Local Result (Base)',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1400, 120],
    })
    BuildLocalResultBase = {
        mode: 'manual',
        assignments: {
            assignments: [
                {
                    id: 'bder0',
                    name: 'LOCAL_COMPANY_ID',
                    value: '={{ $json.COMPANY_ID || null }}',
                    type: 'string',
                },
                {
                    id: 'bder1',
                    // [type case 2026-08-31, owner order] UPPERCASE AT THE WRITE.
                    // The local engine's answer is whatever `q_v3_type` names in its `returns`
                    // fields, and those are spelled lowercase ('invoice', 'balance_sheet') while
                    // the AI leg and the canonical TYPE column are UPPERCASE. Every selector
                    // already folds case before comparing (SelectBase01's canonType,
                    // SelectType01's normalizeDocType), so nothing DECIDED wrongly — but the
                    // document screen's engine matrix compares the two legs as text, so a
                    // document both engines agreed on rendered as "1 אי-הסכמות" forever. Fixing
                    // it only in the UI would leave the column holding two spellings of one
                    // value for the next reader to trip over. Normalized here, at the single
                    // writer, so the stored value matches AI_TYPE and TYPE by construction.
                    name: 'LOCAL_TYPE',
                    value: '={{ $json.TYPE ? String($json.TYPE).trim().toUpperCase() : null }}',
                    type: 'string',
                },
                {
                    id: 'bder2',
                    name: 'LOCAL_DOC_DATE',
                    value: '={{ $json.DOC_DATE || null }}',
                    type: 'string',
                },
                {
                    id: 'bder3',
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
        id: 'bde-check-ai-01',
        name: 'Check AI Enabled (Base)',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [560, 560],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    CheckAiEnabledBase = {
        operation: 'executeQuery',
        query: "=SELECT COALESCE((SELECT value FROM {{ (() => { const i = String($('Doc In').item.json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('BaseDocEx01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.settings WHERE key='extraction_ai_enabled'), 'true') AS ai_enabled",
        options: {},
    };

    @node({
        id: 'bde-if-ai-01',
        name: 'If AI Disabled (Base)',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [840, 560],
    })
    IfAiDisabledBase = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: 'bde-ai-cond-01',
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
        id: 'bde-ai-skip-01',
        name: 'Build AI Skipped (Base)',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1120, 440],
    })
    BuildAiSkippedBase = {
        mode: 'manual',
        assignments: {
            assignments: [
                {
                    id: 'bdea0',
                    name: 'AI_COMPANY_ID',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'bdea1',
                    name: 'AI_TYPE',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'bdea2',
                    name: 'AI_DOC_DATE',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'bdea3',
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
        id: 'bde-extract-ai-01',
        name: 'Extract Base via Webhook',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1120, 680],
        onError: 'continueRegularOutput',
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 5000,
    })
    ExtractBaseViaWebhook = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ExtractInvoiceGemini01',
            mode: 'list',
            cachedResultName: 'invoice Extractor - Gemini 3.1 pro',
            cachedResultUrl: '/workflow/indoxV2ExtractInvoiceGemini01',
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
                },
                {
                    id: 'use_cache',
                    displayName: 'use_cache',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'boolean',
                },
                {
                    id: 'FIELDS',
                    displayName: 'FIELDS',
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
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'bde-ai-result-01',
        name: 'Build AI Result (Base)',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1400, 680],
    })
    BuildAiResultBase = {
        mode: 'manual',
        assignments: {
            assignments: [
                {
                    id: 'bdear0',
                    name: 'AI_COMPANY_ID',
                    value: '={{ $json.data?.AI_COMPANY_ID || null }}',
                    type: 'string',
                },
                {
                    id: 'bdear1',
                    name: 'AI_TYPE',
                    value: '={{ $json.data?.AI_TYPE || null }}',
                    type: 'string',
                },
                {
                    id: 'bdear2',
                    name: 'AI_DOC_DATE',
                    value: '={{ $json.data?.AI_DOC_DATE || null }}',
                    type: 'string',
                },
                {
                    id: 'bdear3',
                    name: 'AI_STATUS',
                    value: "={{ $json.ai_disabled ? ('skipped: ' + ($json.error || 'ai_disabled')) : ($json.success === false ? ('failed: ' + String($json.error || $json.ERROR || 'ai_extraction_failed')) : 'ran') }}",
                    type: 'string',
                },
            ],
        },
        includeOtherFields: false,
        options: {},
    };

    @node({
        id: 'bde-merge-01',
        name: 'Merge Local + AI (Base)',
        type: 'n8n-nodes-base.merge',
        version: 3.2,
        position: [1680, 300],
    })
    MergeLocalAiBase = {
        mode: 'combine',
        combineBy: 'combineByPosition',
        options: {},
    };

    @node({
        id: 'bde-select-01',
        name: 'Select Base',
        /*__n8n__*/ notes: "[A1 date guard 2026-08-13] AI_ONLY dates in the future are refused (stored as null) instead of\nbeing written. Cause of the corruption is the Gemini extractor mis-reading 2-digit years; this\nnode is where the value is accepted. The other half of A1 -- LOCAL_DOC_DATE arriving after\nDOC_DATE is written and never triggering a re-derive (222 year-disagreements, LOCAL plausible\nin 202 of them) -- is NOT fixed here.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1960, 300],
    })
    SelectBase = {
        jsCode: `// Select Base (BaseDocEx01) -- one authoritative pass for COMPANY_ID/TYPE/
// DOC_DATE. Merge already combined LOCAL_*/AI_* onto ONE item, so this reads
// $json directly (no cross-branch named lookback needed). Single source
// present wins outright, no confidence contest, never a blocked document.
const has = v => v !== null && v !== undefined && String(v).trim() !== '';
// [#23 OCR-failure gate 2026-08-15] An extraction failure must FAIL this node, never flow into a
// pick. Both engine calls are onError=continueRegularOutput, so when apitools returns an error
// body (disk-full 08:40Z: 'OCR processing failed [Errno 5] Input/output error') the text arrives
// here as DATA and, before this gate, 195 documents were success-stamped with no extraction
// behind them -- the dup guard's first live catch. Scoped to the proven signatures only; a
// document that legitimately extracts nothing is NOT a failure and passes untouched.
{
  const __sigs = ['OCR processing failed', 'workflow error:', '[Errno 5]'];
  for (const __it of $input.all()) {
    const __blob = JSON.stringify(__it.json || {});
    const __hit = __sigs.find(s => __blob.indexOf(s) >= 0);
    if (__hit) {
      throw new Error('base extraction failed upstream (signature: ' + __hit + ') on ' +
        String((__it.json || {}).ID || 'unknown doc') +
        ' -- refusing to select values from an error payload; Record Base Doc Failure owns this.');
    }
  }
}
// [B34 2026-08-09] A TYPE OF 'unknown' IS A NON-ANSWER, NOT A VALUE. docBaseDecide's own
// isBlank() in this same workflow already says so; pick()'s has() did not, so the two halves
// of the router disagreed about what a value is and a local \`unknown\` beat a confident AI
// type -- the AI answer was discarded (final-indox.md B33.7). Measured live: 124 rows carry
// a literal 'unknown' LOCAL_TYPE, 3 of them had a real AI type and lost it.
// canonType is the SAME canonicalisation the TYPE write below already applies, and the same
// one 'Selection & Scoring Logic1'/normalizeDocType applies -- not a second normaliser.
const canonType = v => String(v).trim().toUpperCase();
const NON_ANSWER_TYPE = ['UNKNOWN', 'UNKNWON'];   // both spellings occur in this schema
const realType = v => (has(v) && NON_ANSWER_TYPE.indexOf(canonType(v)) < 0) ? v : null;
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
function pick(local, ai, canon) {
  const l = has(local) ? String(local).trim() : null;
  const a = has(ai) ? String(ai).trim() : null;
  if (l && a) return { val: l, source: (canon ? canon(l) === canon(a) : l === a) ? 'AGREE' : 'DISAGREE_PREFER_LOCAL' };
  if (l) return { val: l, source: 'LOCAL_ONLY' };
  if (a) return { val: a, source: 'AI_ONLY' };
  return { val: null, source: 'NONE' };
}
// [dup-id 2026-08-10] PAIR BY POSITION -- never the .item accessor on Upload+OCR here.
// This node runs in "Run Once for All Items" mode, so there is no per-iteration current
// item: a named-node .item accessor resolves against the node's ONE current item and
// cannot vary inside this .map(). 'Doc In' is this workflow's trigger and its paired-item
// chain survives, so ID stayed correct. 'Upload+OCR' is an executeWorkflow node left on
// the default "run once with ALL items" mode; when it is handed N documents its N returned
// items come back with the paired-item trace collapsed, so that accessor served ITEM 0's
// file_id to every one of them.
// While the router calls this workflow with mode:'each' each execution carries exactly one
// document and the defect is invisible. On 2026-08-09, 10:00-22:00 UTC, it was not: 601
// documents were stamped with another file's API_TOOLS_ID in n8n-batch-shaped groups
// (50/50/50/49/48/44/41...), exactly ONE rightful owner per group -- 152 base extractions
// in the 18:00 hour collapsed to 4 distinct file ids. A broadcast, not a shuffle. Every
// per-type field is then extracted faithfully FROM THE WRONG FILE, which is how 432
// documents across 228 ids came to hold another company's document number.
// Index pairing is valid because Merge Local + AI (Base) is combineByPosition over the
// order Doc In produced. It is NOT valid if a leg dropped an item -- 'Document OCR2' in
// indoxV2UploadApiTools01 is onError:continueErrorOutput and sheds 429s away from the
// merge, so a shed run returns FEWER items than it was given. That case is refused
// outright below rather than guessed at: a loud failure is recoverable, a silent
// re-attribution of one client's document number to another client is not.
// [two-point rule 2026-08-17] Input is now the NAME matcher's rows (one per doc, same order);
// the merged docs come from the named lookback on the merge node — same index-pairing
// contract and the same refusal on any count mismatch.
const __in = $('Merge Local + AI (Base)').all();
const __nm = $input.all();
const __up = $('Upload+OCR').all();
const __docIn = $('Doc In').all();
if (__up.length !== __in.length || __docIn.length !== __in.length || __nm.length !== __in.length) {
  throw new Error('Select Base: item-count mismatch (merged=' + __in.length +
    ', NAME match=' + __nm.length +
    ', Upload+OCR=' + __up.length + ', Doc In=' + __docIn.length + '). Refusing to pair by ' +
    'index. This is the exact shape that stamped one document\\'s API_TOOLS_ID onto 601 others.');
}
return __in.map((item, __i) => {
  const d = item.json;
  let companyPick = pick(d.LOCAL_COMPANY_ID, d.AI_COMPANY_ID);
  // [two-point rule 2026-08-17, owner order] FILL-ONLY third company leg: the filename
  // matcher (ported from figure_company_offline, B31 semantics). Only consulted when BOTH
  // OCR legs produced nothing, so it can never override an extracted value.
  const __nmRow = (__nm[__i] && __nm[__i].json) || {};
  if (!companyPick.val && __nmRow.company_id) {
    companyPick = { val: String(__nmRow.company_id), source: 'NAME_MATCH ' + String(__nmRow.matched_name || '') };
  }
  // [A1 date guard 2026-08-13] Reject an AI date that is IMPOSSIBLE, not merely surprising.
  // Measured: 631 of 713 rows with a year <= 2024 have DOC_DATE == AI_DOC_DATE, and the model
  // mis-reads 2-digit years two ways -- order flip (23/06/26 -> 26/06/2023) and wrong decade
  // (25 -> 2015). \`pick\` already prefers LOCAL when both legs answer, so these all came down the
  // AI_ONLY branch with LOCAL_DOC_DATE empty at this moment (it is filled later by another writer,
  // and DOC_DATE is never re-derived -- that half is still open, see NEXT.md A1).
  // Only a FUTURE date is refused: a document cannot be dated after the instant it is extracted.
  // 35 such rows exist, up to 68 years ahead. No threshold, so nothing legitimate is discarded --
  // an "implausibly old" bound was considered and rejected, because 308 rows sit at a 2-3 year gap
  // and may be genuine back-filed invoices.
  const __dateImpossible = (s) => {
    if (!has(s)) return false;
    const m = String(s).trim().match(/^(\\d{1,2})\\/(\\d{1,2})\\/(\\d{4})$/);
    if (!m) return false;                       // not our shape -- leave it alone
    const dd = +m[1], mm = +m[2], yy = +m[3];
    if (mm < 1 || mm > 12 || dd < 1 || dd > 31) return false;  // malformed, not our concern here
    const when = new Date(yy, mm - 1, dd);
    if (isNaN(when.getTime())) return false;
    // one day of slack absorbs timezone skew between the extractor and this node
    return when.getTime() > Date.now() + 86400000;
  };
  let datePick = pick(d.LOCAL_DOC_DATE, d.AI_DOC_DATE);
  if (datePick.source === 'AI_ONLY' && __dateImpossible(datePick.val)) {
    // Store nothing rather than a date we know is wrong. A missing date re-opens the document
    // for another pass; a wrong one is silently terminal -- it can age the row out as OLD, and
    // OLD never re-evaluates.
    datePick = { val: null, source: 'AI_REFUSED_FUTURE_DATE' };
  }
  // [B34 2026-08-09] TYPE is picked on REAL answers first, so a confident AI type beats a
  // local non-answer. THE FALLBACK PRESERVES THE OLD BEHAVIOUR EXACTLY when NEITHER leg
  // gave a real type: the raw pick returns the same value and the same source it always
  // did, so out.TYPE and the CONDITIONAL STAMP below are byte-identical for those rows.
  // Without it, the 121 rows already settled on UNKNOWN would lose FIGURE_TYPE_COMPLETED
  // and be re-opened into figure_document_type -- a resolver measured at 0 usable types in
  // 77 runs (final-indox.md B33.3). This fix rescues answers; it does not re-open settled
  // rows, and the stamp still fires only on a genuine resolution.
  let typePick = pick(realType(d.LOCAL_TYPE), realType(d.AI_TYPE), canonType);
  if (!typePick.val) typePick = pick(d.LOCAL_TYPE, d.AI_TYPE, canonType);
  const upload = (__up[__i] && __up[__i].json) || {};
  // [pure extraction 2026-08-25, owner order] THIS POINT REPORTS WHAT ITS ENGINES SAW.
  // COMPANY_ID / TYPE / DOC_DATE are decided by select_base (SelectBase01), a separate action that
  // reads the whole row -- both engines, the filename, the settings-driven type priority, and the
  // values the row already holds. The picks above are still computed because the answer/failure
  // test below is a fact about THIS extraction: whether anything was read at all. The two guards
  // that lived here, the NAME_MATCH company leg and the future-date refusal, moved into
  // SelectBase01 -- they are selection rules, and they were being silently overwritten anyway by
  // the router's copy of this logic, which never had them.
  return { json: {
    ID: ((__docIn[__i] && __docIn[__i].json) || {}).ID,
    LOCAL_COMPANY_ID: d.LOCAL_COMPANY_ID || null,
    LOCAL_TYPE: d.LOCAL_TYPE || null,
    LOCAL_DOC_DATE: d.LOCAL_DOC_DATE || null,
    AI_COMPANY_ID: d.AI_COMPANY_ID || null,
    AI_TYPE: d.AI_TYPE || null,
    AI_DOC_DATE: d.AI_DOC_DATE || null,
    // [base-point API_TOOLS_ID 2026-08-09] FILL-ONLY BY OMISSION. This is the one
    // place every lane inherits the apitools id from -- the BS router has no
    // get_api_tools_id of its own, so a balance sheet can only ever get an id here.
    // Writing an explicit null was harmless (the UPSERT Adapter strips null keys),
    // but writing THIS run's id unconditionally could replace an id the document
    // already held: 5,694 rows hold one and are still queued for extract_base_doc.
    // Omitting the key on null is the same idiom the FIGURE_*_COMPLETED stamps below
    // use -- the upsert then leaves the column exactly as it was. The router
    // ('Select Base Values') carries the fill-only precedence against the
    // pre-extraction row, which this workflow cannot see (Doc In takes ID/LINK/HASH).
    ...(upload.file_id ? { API_TOOLS_ID: upload.file_id } : {}),
    // [HASH 2026-08-19, owner order] BASE OWNS THE HASH. Nothing wrote this column: it was only
    // ever set by the ingestion paths, so a line created from a LINK alone finished extraction
    // with HASH null while the identical value sat in API_TOOLS_ID -- measured on test01
    // (API_TOOLS_ID 69a77f29..., HASH null) and again on the 2026-08-19 driver-path run. The
    // uploader's file_id IS the file's md5, which is exactly what the 'hash' dedup key needs, so
    // a null HASH silently removes a document from hash-based double detection. Same
    // fill-only-by-omission idiom as the id above: omit on null, never overwrite.
    ...(upload.file_id ? { HASH: upload.file_id } : {}),
    BASE_EXTRACTION_COMPLETED: true,
    // [two-point rule 2026-08-17, owner order] BOTH stamps are UNCONDITIONAL: base is the
    // only sanctioned resolution point for COMPANY_ID and TYPE. The legacy resolvers
    // (figure_company_id, figure_document_type, the standalone extract_invoice_google_ai
    // action) never fire again; unresolved values terminalize via MISSING_COMPANY_ID /
    // MISSING_TYPE instead of churning out-of-band extractors.
    FIGURE_COMPANY_COMPLETED: true,
    FIGURE_TYPE_COMPLETED: true,
    // CARRY THE LEG STATUSES OUT AS REAL KEYS. They used to exist only inside the debug string,
    // which the router then overwrote with its own -- so the failure classifier downstream read
    // undefined and every unextractable document got the same generic reason. SELECTION_DEBUG_BASE
    // itself is written by SelectBase01 now, where the decision it describes is actually made.
    LOCAL_STATUS: d.LOCAL_STATUS || null,
    AI_STATUS: d.AI_STATUS || null
  }};
});
`,
    };

    @node({
        id: 'bde-return-01',
        name: 'Return',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [2240, 300],
    })
    Return_ = {
        mode: 'manual',
        assignments: {
            assignments: [],
        },
        includeOtherFields: true,
        options: {},
    };

    @node({
        id: 'a1c7f0de-base-4d21-9f0e-lockmapset01',
        name: 'Lock Map Set (retry scope)',
        /*__n8n__*/ notes: "[dead-letter scope 2026-08-10] Publishes n8n.exec.<execution>.docmap so a FAILURE in this workflow reaches errorHandler01's 'Get Lock Map' -> 'If Has Lock' gate. Without it, 'Backoff + Dead-letter' never increments RETRY_COUNT (so a document never reaches the >=5 NEEDS_REVIEW dead-letter) and 'EH Unlock Doc' never runs (so the doc_step lock is held for its full 600s TTL and every sweep bounces off it). indoxV2UploadApiTools01 and indoxV2FigureCompanyId01 already carry this node verbatim; BaseDocEx01 was the only action sub-workflow missing it, and it is the largest single error source in the fleet (532 errors/hour, all 'Upload+OCR timed out'). [2026-08-23] `?? ''` is not defensive style, it is the fix for a measured document-destroying bug. The Redis node stringifies this value; when $json.ID was undefined it threw \"Cannot read properties of undefined (reading 'toString')\", and because the node is onError:continueRegularOutput the ERROR OBJECT replaced the item -- so HASH and LINK were gone by the time Upload+OCR ran, the uploader correctly answered wrong_input, JQExV3 correctly answered missing_file_id, and the document still finished COMPLETED with COMPANY_ID/TYPE/DOC_DATE all null. Traced in sync_sources exec 20325/20326/20327: the file itself was uploaded and OCR'd fine (Map Extractions read invoice_id SI9720129 off it), so the ONLY thing that nulled the base pass was this telemetry node erasing the payload. A node that exists to make failures visible must never be able to cause one. ID stays optional here on purpose -- an absent ID now costs the dead-letter path its attribution for that document, which is a known and much smaller loss than blanking the document.",
        /*__n8n__*/ notesInFlow: false,
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [180, 460],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
        onError: 'continueRegularOutput',
    })
    LockMapSetRetryScope = {
        operation: 'set',
        key: '=n8n.exec.{{ $execution.id }}.docmap',
        value: "={{ $input.all().length === 1 ? ($json.ID ?? '') : '' }}",
        keyType: 'string',
        expire: true,
        ttl: '={{ 60*20 }}',
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.DocIn.out(0).to(this.LockMapSetRetryScope.in(0));
        this.UploadOcr.out(0).to(this.CheckLocalEnabledBase.in(0));
        this.UploadOcr.out(0).to(this.CheckAiEnabledBase.in(0));
        this.CheckLocalEnabledBase.out(0).to(this.IfLocalDisabledBase.in(0));
        this.IfLocalDisabledBase.out(0).to(this.BuildLocalSkippedBase.in(0));
        this.IfLocalDisabledBase.out(1).to(this.CallJqexv3Base.in(0));
        this.CallJqexv3Base.out(0).to(this.BuildLocalResultBase.in(0));
        this.CheckAiEnabledBase.out(0).to(this.IfAiDisabledBase.in(0));
        this.IfAiDisabledBase.out(0).to(this.BuildAiSkippedBase.in(0));
        this.IfAiDisabledBase.out(1).to(this.ExtractBaseViaWebhook.in(0));
        this.ExtractBaseViaWebhook.out(0).to(this.BuildAiResultBase.in(0));
        this.BuildLocalSkippedBase.out(0).to(this.MergeLocalAiBase.in(0));
        this.BuildLocalResultBase.out(0).to(this.MergeLocalAiBase.in(0));
        this.BuildAiSkippedBase.out(0).to(this.MergeLocalAiBase.in(1));
        this.BuildAiResultBase.out(0).to(this.MergeLocalAiBase.in(1));
        this.MergeLocalAiBase.out(0).to(this.NameCompanyMatchOffline.in(0));
        this.NameCompanyMatchOffline.out(0).to(this.SelectBase.in(0));
        this.SelectBase.out(0).to(this.Return_.in(0));
        this.LockMapSetRetryScope.out(0).to(this.UploadOcr.in(0));
    }
}
