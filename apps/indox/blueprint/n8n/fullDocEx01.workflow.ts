import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : fullDocEx — full extraction on one document
// Nodes   : 12  |  Connections: 11
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// DocWebhook                         webhook                    [creds]
// WhenClickingExecute                manualTrigger
// ShapeInput                         code
// CallUpload                         executeWorkflow            [onError→regular]
// CallBase                           executeWorkflow            [onError→regular]
// RowForBaseSelect                   code
// CallSelectbase                     executeWorkflow            [onError→regular]
// CallPertype                        executeWorkflow            [onError→regular]
// RowForTypeSelect                   code
// CallSelecttype                     executeWorkflow            [onError→regular]
// BuildResult                        code
// DocRespond                         respondToWebhook           [onError→regular]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// DocWebhook
//    → ShapeInput
//      → CallUpload
//        → CallBase
//          → RowForBaseSelect
//            → CallSelectbase
//              → CallPertype
//                → RowForTypeSelect
//                  → CallSelecttype
//                    → BuildResult
//                      → DocRespond
// WhenClickingExecute
//    → ShapeInput (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Doc Webhook":{"main":[[{"node":"Shape Input","type":"main","index":0}]]},"Shape Input":{"main":[[{"node":"Call Upload","type":"main","index":0}]]},"Call Upload":{"main":[[{"node":"Call Base","type":"main","index":0}]]},"Call Base":{"main":[[{"node":"Row For Base Select","type":"main","index":0}]]},"Row For Base Select":{"main":[[{"node":"Call SelectBase","type":"main","index":0}]]},"Call SelectBase":{"main":[[{"node":"Call PerType","type":"main","index":0}]]},"Call PerType":{"main":[[{"node":"Row For Type Select","type":"main","index":0}]]},"Row For Type Select":{"main":[[{"node":"Call SelectType","type":"main","index":0}]]},"Call SelectType":{"main":[[{"node":"Build Result","type":"main","index":0}]]},"Build Result":{"main":[[{"node":"Doc Respond","type":"main","index":0}]]},"When clicking Execute":{"main":[[{"node":"Shape Input","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-18T20:11:33.802Z","createdAt":"2026-08-18T20:11:33.802Z","role":"workflow:owner","workflowId":"fullDocEx01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'fullDocEx01',
    name: 'fullDocEx — full extraction on one document',
    active: false,
    isArchived: false,
    tags: ['app:indox'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1', binaryMode: 'separate' },
})
export class FulldocexFullExtractionOnOneDocumentWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'fde-webhook-01',
        webhookId: 'f0110dc5-11ee-4ec0-9a1b-fde0000000c1',
        name: 'Doc Webhook',
        type: 'n8n-nodes-base.webhook',
        version: 2.1,
        position: [0, 0],
        credentials: { httpBasicAuth: { id: 'azPhHBvOWaf9IsEA', name: 'Incoming Documents [env-managed]' } },
    })
    DocWebhook = {
        httpMethod: 'POST',
        path: 'full-doc-ex',
        authentication: 'basicAuth',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'fde-manual-01',
        name: 'When clicking Execute',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [0, 208],
    })
    WhenClickingExecute = {};

    @node({
        id: 'fde-shape-01',
        name: 'Shape Input',
        /*__n8n__*/ notes: "Normalise the webhook body into the field names the three sub-workflows expect. Everything is optional except one of LINK / HASH -- the uploader needs a way to reach the file, and its own WRONG INPUT branch is what reports the absence.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [224, 0],
    })
    ShapeInput = {
        jsCode: `const b = ($input.first().json && $input.first().json.body) || $input.first().json || {};
const s = v => (v === undefined || v === null || v === '') ? null : String(v);
return [{
  json: {
    ID:               s(b.ID),
    LINK:             s(b.LINK),
    HASH:             s(b.HASH),
    LINK_CONNECTION:  s(b.LINK_CONNECTION),
    API_TOOLS_ID:     s(b.API_TOOLS_ID),
    TYPE:             s(b.TYPE),
    STATUS:           s(b.STATUS),
    RETRY_COUNT:      s(b.RETRY_COUNT),
    INVOICE_ID:       s(b.INVOICE_ID),
    // Pass DOC_ID through to REPRODUCE the row; send it empty to see what the extractor picks.
    DOC_ID:           s(b.DOC_ID),
    SHIPMENT_DOC_ID:  s(b.SHIPMENT_DOC_ID),
    LINKED_INVOICE_ID: s(b.LINKED_INVOICE_ID),
    // [selection 2026-08-25] The selectors read the ROW, not the file, so a caller who wants to
    // reproduce a real document's answer must be able to hand over the row's context too: the
    // filename (the third company leg), the source (the trusted-supplier lookup and the BS type
    // fallback), the company, and the supplier's own ledger line. Omit them to see what selection
    // decides with nothing but the document itself.
    NAME:             s(b.NAME),
    SOURCE_TYPE:      s(b.SOURCE_TYPE),
    COMPANY_ID:       s(b.COMPANY_ID),
    DOC_DATE:         s(b.DOC_DATE),
    BS_LINE_DATE:     s(b.BS_LINE_DATE),
    BS_LINE_AMOUNT:   s(b.BS_LINE_AMOUNT),
  },
  binary: $input.first().binary,
}];`,
    };

    @node({
        id: 'fde-upload-01',
        name: 'Call Upload',
        /*__n8n__*/ notes: "indoxV2UploadApiTools01 already handles binary vs link vs hash and returns file_id; this is deliberately NOT reimplemented here.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [448, 0],
        onError: 'continueRegularOutput',
    })
    CallUpload = {
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
            schema: [],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        options: {},
    };

    @node({
        id: 'fde-base-01',
        name: 'Call Base',
        /*__n8n__*/ notes: "The BASE point owns COMPANY and TYPE. Its resolved TYPE is what selects the per-type extractor in the next node.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [672, 0],
        onError: 'continueRegularOutput',
    })
    CallBase = {
        workflowId: {
            __rl: true,
            value: 'BaseDocEx01',
            mode: 'list',
            cachedResultUrl: '/workflow/BaseDocEx01',
            cachedResultName: 'Base Document Extraction (local + AI, parallel)',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                ID: "={{ $('Shape Input').first().json.ID }}",
                LINK: "={{ $('Shape Input').first().json.LINK }}",
                HASH: "={{ $json.file_id ?? $('Shape Input').first().json.HASH }}",
                __instance: "={{ $('Shape Input').first().json.__instance || '' }}",
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
                    id: 'LINK',
                    displayName: 'LINK',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
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
                    id: 'NAME',
                    displayName: 'NAME',
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
        options: {},
    };

    @node({
        id: 'fde-rowbase-01',
        name: 'Row For Base Select',
        /*__n8n__*/ notes: "The selectors take a ROW, and after the split a row is what the extractor returned PLUS the context the caller supplied. Assembled here rather than mapped field-by-field on the call, so adding a version column never means editing this workflow.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [880, 208],
    })
    RowForBaseSelect = {
        jsCode: `const inp  = $('Shape Input').first().json;
const base = (() => { try { return $('Call Base').first().json || {}; } catch (e) { return {}; } })();
return [{ json: { ...inp, ...base, ID: inp.ID || base.ID } }];
`,
    };

    @node({
        id: 'fde-selbase-01',
        name: 'Call SelectBase',
        /*__n8n__*/ notes: "The SAME selector the state machine's select_base action runs. Extraction produces the versions; this decides the values. fullDocEx01 calls it directly and upserts nothing, which is what makes it a safe regression harness for the selection logic.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1104, 208],
        onError: 'continueRegularOutput',
    })
    CallSelectbase = {
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
        id: 'fde-pertype-01',
        name: 'Call PerType',
        /*__n8n__*/ notes: "SHIPMENT -> ShipmentDocEx01, BALANCE_SHEET -> BsDocEx01, everything else (INVOICE / ORDER) -> InvoiceDocEx01. TYPE is taken from the BASE result first because base owns type, falling back to the TYPE supplied on the request. [non-answer 2026-08-25] The fallback tests for a REAL type, not for null: base returns the literal 'UNKNOWN' when neither engine resolved a type, and `??` does not fall back on a non-null string, so a balance sheet whose base pass came back UNKNOWN was routed to InvoiceDocEx01 and extracted as an invoice (reproduced on doc_msnsaqamlyl0jt). Same non-answer rule as realType() in 'Select Base'.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [880, 0],
        onError: 'continueRegularOutput',
    })
    CallPertype = {
        workflowId: {
            __rl: true,
            value: "={{ (() => { const real = v => { const s = String(v ?? '').trim().toUpperCase(); return (s && s !== 'UNKNOWN' && s !== 'UNKNWON') ? s : ''; }; const t = real($json.TYPE) || real($('Shape Input').first().json.TYPE); return t === 'SHIPMENT' ? 'ShipmentDocEx01' : (t === 'BALANCE_SHEET' ? 'BsDocEx01' : 'InvoiceDocEx01'); })() }}",
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                ID: "={{ $('Shape Input').first().json.ID }}",
                API_TOOLS_ID:
                    "={{ $('Call Upload').first().json.file_id ?? $('Shape Input').first().json.API_TOOLS_ID }}",
                LINK: "={{ $('Shape Input').first().json.LINK }}",
                LINK_CONNECTION: "={{ $('Shape Input').first().json.LINK_CONNECTION }}",
                STATUS: "={{ $('Shape Input').first().json.STATUS }}",
                RETRY_COUNT: "={{ $('Shape Input').first().json.RETRY_COUNT }}",
                TYPE: "={{ $json.TYPE ?? $('Shape Input').first().json.TYPE }}",
                INVOICE_ID: "={{ $('Shape Input').first().json.INVOICE_ID }}",
                DOC_ID: "={{ $('Shape Input').first().json.DOC_ID }}",
                SHIPMENT_DOC_ID: "={{ $('Shape Input').first().json.SHIPMENT_DOC_ID }}",
                LINKED_INVOICE_ID: "={{ $('Shape Input').first().json.LINKED_INVOICE_ID }}",
            },
            matchingColumns: [],
            schema: [],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        options: {},
    };

    @node({
        id: 'fde-rowtype-01',
        name: 'Row For Type Select',
        /*__n8n__*/ notes: "Same assembly as the base side, one stage later: the caller's context, base's versions, base's decision, then the per-type versions -- in that order, so the freshest value of any column wins.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1104, 416],
    })
    RowForTypeSelect = {
        jsCode: `const g = (n) => { try { return $(n).first().json || {}; } catch (e) { return {}; } };
const inp = $('Shape Input').first().json;
const row = { ...inp, ...g('Call Base'), ...g('Call SelectBase'), ...g('Call PerType') };
row.ID = inp.ID || row.ID;
return [{ json: row }];
`,
    };

    @node({
        id: 'fde-seltype-01',
        name: 'Call SelectType',
        /*__n8n__*/ notes: "The SAME selector the state machine's select_type action runs -- values, corroboration score and SELECTION_VALUES_HASH.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1328, 416],
        onError: 'continueRegularOutput',
    })
    CallSelecttype = {
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
        id: 'fde-result-01',
        name: 'Build Result',
        /*__n8n__*/ notes: "Returns the three stages separately AND a flat `resolved` view, so a caller can see WHICH stage produced a value rather than only the merged answer.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1104, 0],
    })
    BuildResult = {
        jsCode: `const g = (n) => { try { return $(n).first().json || {}; } catch (e) { return {}; } };
const inp  = $('Shape Input').first().json;
const up   = g('Call Upload');
const base = g('Call Base');
const per  = g('Call PerType');
const selb = g('Call SelectBase');
const selt = g('Call SelectType');
const pick = (...v) => v.find(x => x !== undefined && x !== null && x !== '') ?? null;
// FIVE STAGES, REPORTED SEPARATELY, plus the flat 'resolved' view. The split of extraction from
// selection is visible here: 'base'/'pertype' now carry ONLY LOCAL_*/AI_* versions, and every
// final value comes from 'selbase'/'seltype'. A caller can see not just the answer but which
// stage produced it, which is the whole point of this workflow.
// 'Call SelectType' continues on error, so a failed selection arrives here as an ordinary item and
// the result below would report a stage that never ran. Read the failure and report it with the rest.
const selectorFailure = String(g('Call SelectType').error || g('Call SelectType').errorMessage || '');
return [{ json: {
  input: inp,
  selector_error: selectorFailure,
  failed: selectorFailure !== '',
  file_id: pick(up.file_id, inp.HASH),
  upload: up,
  base,
  pertype: per,
  selbase: selb,
  seltype: selt,
  resolved: {
    TYPE:            pick(selb.TYPE, base.TYPE, per.TYPE, inp.TYPE),
    COMPANY_ID:      pick(selb.COMPANY_ID, base.COMPANY_ID, per.COMPANY_ID),
    COMPANY_NAME:    pick(base.COMPANY_NAME, per.COMPANY_NAME),
    DOC_ID:          pick(selt.DOC_ID, per.DOC_ID, inp.DOC_ID),
    AI_DOC_ID:       pick(per.AI_DOC_ID, base.AI_DOC_ID),
    SHIPMENT_DOC_ID: pick(selt.SHIPMENT_DOC_ID, per.SHIPMENT_DOC_ID, inp.SHIPMENT_DOC_ID),
    DOC_DATE:        pick(selt.DOC_DATE, selb.DOC_DATE, per.DOC_DATE, base.DOC_DATE),
    DOC_TOTAL_AMOUNT: pick(selt.DOC_TOTAL_AMOUNT, selt.TOTAL_AMOUNT, per.DOC_TOTAL_AMOUNT),
    PURCHASE_ID:     pick(selt.PURCHASE_ID, per.PURCHASE_ID),
    SELECTION_CERTAINTY: selt.SELECTION_CERTAINTY ?? null,
    SELECTION_SOURCE:    pick(selt.SELECTION_SOURCE),
    SELECTION_VALUES_HASH: pick(selt.SELECTION_VALUES_HASH),
    SELECTION_DEBUG_BASE:    pick(selb.SELECTION_DEBUG_BASE),
    SELECTION_DEBUG_PERTYPE: pick(selt.SELECTION_DEBUG_PERTYPE, per.SELECTION_DEBUG_PERTYPE),
  },
}}];`,
    };

    @node({
        id: 'fde-respond-01',
        name: 'Doc Respond',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [1328, 0],
        onError: 'continueRegularOutput',
    })
    DocRespond = {
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
        this.DocWebhook.out(0).to(this.ShapeInput.in(0));
        this.ShapeInput.out(0).to(this.CallUpload.in(0));
        this.CallUpload.out(0).to(this.CallBase.in(0));
        this.CallBase.out(0).to(this.RowForBaseSelect.in(0));
        this.RowForBaseSelect.out(0).to(this.CallSelectbase.in(0));
        this.CallSelectbase.out(0).to(this.CallPertype.in(0));
        this.CallPertype.out(0).to(this.RowForTypeSelect.in(0));
        this.RowForTypeSelect.out(0).to(this.CallSelecttype.in(0));
        this.CallSelecttype.out(0).to(this.BuildResult.in(0));
        this.BuildResult.out(0).to(this.DocRespond.in(0));
        this.WhenClickingExecute.out(0).to(this.ShapeInput.in(0));
    }
}
