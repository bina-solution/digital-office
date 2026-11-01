import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Mail Label Engine
// Nodes   : 38  |  Connections: 39
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// OnCreateSettings                   code
// GetManyLabels                      executeWorkflow
// LoopOverItems                      splitInBatches
// CreateALabel                       executeWorkflow            [onError→regular]
// LabelsToCreate                     code
// CreateLabelsStart                  noOp
// SplitSettings                      splitOut
// AddLabelToMessage                  executeWorkflow
// GetFinalLabels                     executeWorkflow
// FinalLabelIds                      code
// End                                noOp
// StartGetTagSettings                noOp
// GetMailThread                      executeWorkflow
// StartMailItem                      noOp
// GetAMessage                        executeWorkflow            [onError→regular]
// WhenClickingExecuteWorkflow        manualTrigger
// IfShouldApply                      if
// RemoveLabelFromMessage             executeWorkflow
// TargetSpecificMailTextSearch       executeWorkflow
// PrepareContext                     noOp                       [executeOnce]
// Start                              noOp
// Batching1                          splitInBatches
// AddRemoveLabel                     if
// LableEngine                        code
// LoadSettingsRules                  httpRequest
// TagRows                            code
// LoadSettingsManual                 httpRequest
// AggAddLabels                       code
// AggRemoveLabels                    code
// SubTrigger                         executeWorkflowTrigger
// SubSearch                          executeWorkflow            [onError→out(1)]
// FetchOk                            if
// SkippedFetchFailed                 noOp
// BootstrapProcessedLabel            executeWorkflow            [onError→regular]
// ConnManual                         code
// ConnSub                            code
// MailConnection                     code
// StampOutline                       executionData
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenClickingExecuteWorkflow
//    → LoadSettingsManual
//      → ConnManual
//        → TargetSpecificMailTextSearch
//          → MailConnection
//            → GetAMessage
//              → FetchOk
//                → Start
//                  → PrepareContext
//                    → CreateLabelsStart
//                      → GetManyLabels
//                        → LabelsToCreate
//                          → LoopOverItems
//                           .out(1) → CreateALabel
//                              → LoopOverItems (↩ loop)
//                    → GetFinalLabels
//                      → FinalLabelIds
//                    → StartGetTagSettings
//                      → LoadSettingsRules
//                        → TagRows
//                          → OnCreateSettings
//                            → SplitSettings
//                  → Batching1
//                    → End
//                   .out(1) → Batching1 (↩ loop)
//                   .out(1) → StartMailItem
//                      → GetMailThread
//                      → LableEngine
//                        → IfShouldApply
//                          → AddRemoveLabel
//                            → AggAddLabels
//                              → AddLabelToMessage
//                           .out(1) → AggRemoveLabels
//                              → RemoveLabelFromMessage
//               .out(1) → SkippedFetchFailed
// SubTrigger
//    → ConnSub
//      → SubSearch
//        → MailConnection (↩ loop)
//        → StampOutline
//       .out(1) → BootstrapProcessedLabel
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Conn (manual)":{"main":[[{"node":"Target specific mail (text search)","type":"main","index":0}]]},"Conn (sub)":{"main":[[{"node":"Sub Search","type":"main","index":0}]]},"Mail Connection":{"main":[[{"node":"Get a message","type":"main","index":0}]]},"On Create Settings":{"main":[[{"node":"Split Settings","type":"main","index":0}]]},"Get many labels":{"main":[[{"node":"Labels to create","type":"main","index":0}]]},"Loop Over Items":{"main":[[],[{"node":"Create a label","type":"main","index":0},{"node":"Loop Over Items","type":"main","index":0}]]},"Create a label":{"main":[[]]},"Labels to create":{"main":[[{"node":"Loop Over Items","type":"main","index":0}]]},"Create Labels Start":{"main":[[{"node":"Get many labels","type":"main","index":0}]]},"Get final labels":{"main":[[{"node":"Final Label Ids","type":"main","index":0}]]},"Start Get Tag Settings":{"main":[[{"node":"Load Settings (rules)","type":"main","index":0}]]},"Start Mail Item":{"main":[[{"node":"Get Mail Thread","type":"main","index":0},{"node":"Lable Engine","type":"main","index":0}]]},"Get a message":{"main":[[{"node":"Fetch OK?","type":"main","index":0}]]},"When clicking ‘Execute workflow’":{"main":[[{"node":"Load Settings (manual)","type":"main","index":0}]]},"If Should Apply":{"main":[[{"node":"Add / Remove Label","type":"main","index":0}]]},"Target specific mail (text search)":{"main":[[{"node":"Mail Connection","type":"main","index":0}]]},"Prepare Context":{"main":[[{"node":"Create Labels Start","type":"main","index":0},{"node":"Get final labels","type":"main","index":0},{"node":"Start Get Tag Settings","type":"main","index":0}]]},"Start":{"main":[[{"node":"Prepare Context","type":"main","index":0},{"node":"Batching 1","type":"main","index":0}]]},"Batching 1":{"main":[[{"node":"End","type":"main","index":0}],[{"node":"Batching 1","type":"main","index":0},{"node":"Start Mail Item","type":"main","index":0}]]},"Add / Remove Label":{"main":[[{"node":"Agg Add Labels","type":"main","index":0}],[{"node":"Agg Remove Labels","type":"main","index":0}]]},"Lable Engine":{"main":[[{"node":"If Should Apply","type":"main","index":0}]]},"Load Settings (rules)":{"main":[[{"node":"Tag Rows","type":"main","index":0}]]},"Tag Rows":{"main":[[{"node":"On Create Settings","type":"main","index":0}]]},"Load Settings (manual)":{"main":[[{"node":"Conn (manual)","type":"main","index":0}]]},"Agg Add Labels":{"main":[[{"node":"Add label to message","type":"main","index":0}]]},"Agg Remove Labels":{"main":[[{"node":"Remove label from message","type":"main","index":0}]]},"Sub Trigger":{"main":[[{"node":"Conn (sub)","type":"main","index":0}]]},"Sub Search":{"main":[[{"node":"Mail Connection","type":"main","index":0},{"node":"Stamp Outline","type":"main","index":0}],[{"node":"Bootstrap PROCESSED Label","type":"main","index":0}]]},"Bootstrap PROCESSED Label":{"main":[[]]},"Fetch OK?":{"main":[[{"node":"Start","type":"main","index":0}],[{"node":"Skipped - Fetch Failed","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"13169fca-0f90-403c-8cbc-cd5ef852d145","name":"label-engine"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"333960da-8376-4dd1-8b39-c3d4b448ca86","name":"mail-app"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"40f9d46a-019f-433c-b1b6-bab80e6f115a","name":"gmail"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"cf994cba-b6d0-53fa-8729-2b8d0c21b28f","name":"app:mail"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {"templateCredsSetupCompleted":true},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"mailLabelEngine01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'mailLabelEngine01',
    name: 'Mail Label Engine',
    active: true,
    isArchived: false,
    tags: ['label-engine', 'mail-app', 'gmail', 'app:mail', 'indox'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1', binaryMode: 'separate',
        // [own budget 2026-08-31] WITHOUT this the engine inherits mail01's 300s scheduler
        // budget and a slow-IMAP pass is CANCELLED mid-labeling every tick (measured 16:30 +
        // 16:45 on a quiet box: 'Add label to message', 'cancelled because it timed out').
        // Same remedy indoxV2BaseDrain01 uses for the same inheritance. 840s < the 15-min
        // tick, so passes cannot stack.
        // [measured 2026-09-02, laptop] this value is NOT enough on its own: n8n hands the
        // PARENT's deadline down (a child's limit = min(own, parent's remaining)), and with
        // mail01 at executionTimeout 300 every one of the 42 error runs of the last 3 days was
        // 'TimeoutExecutionCancelledError' at 300-330 s despite the 840 here. The root of the
        // dispatch chain (mail01) must carry a limit >= this one for it to take effect.
        executionTimeout: 840,
    },
})
export class MailLabelEngineWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: '92f20a7b-2d27-4468-b29d-8166e0244015',
        name: 'On Create Settings',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [816, -176],
    })
    OnCreateSettings = {
        jsCode: `var on_create_settings = $input.all()
  .map(i => i.json)
  .filter(i => i.TYPE === "ON_CREATE_EVENT")
  .map(i => ({ ...i, LABEL: i.LABEL.trim() }));

return { on_create_settings };`,
    };

    @node({
        id: '75cff7d9-cd68-4326-b52d-eff99fe76a95',
        name: 'Get many labels',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [368, -208],
    })
    GetManyLabels = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'listLabels',
                params: "={{ ({ connection_id: $('Mail Connection').first().json.connection_id }) }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'op',
                    displayName: 'op',
                    required: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                },
                {
                    id: 'params',
                    displayName: 'params',
                    required: false,
                    display: true,
                    type: 'object',
                    canBeUsedToMatch: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: '03a5bd55-4fcb-40e1-8963-b1b8da02711d',
        name: 'Loop Over Items',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [816, 16],
    })
    LoopOverItems = {
        options: {},
    };

    @node({
        id: '33ed5068-a798-4e67-bff8-8397fd08f7bb',
        name: 'Create a label',
        /*__n8n__*/ continueOnFail: true,
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1040, 0],
        onError: 'continueRegularOutput',
    })
    CreateALabel = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'createLabel',
                params: "={{ ({ name: $json.label, connection_id: $('Mail Connection').first().json.connection_id }) }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'op',
                    displayName: 'op',
                    required: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                },
                {
                    id: 'params',
                    displayName: 'params',
                    required: false,
                    display: true,
                    type: 'object',
                    canBeUsedToMatch: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: 'f62dd378-d3c7-4326-b570-9ca7fda291cf',
        name: 'Labels to create',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [592, -208],
    })
    LabelsToCreate = {
        jsCode: `const labels = $input.all().map((item) => (item.json.name||'').trim());
let settingsLables = [];
// [N2 2026-09-02] a rule the editor disabled (enabled === false) gets no label created - the
// evaluator skips it too. Absent/null = enabled: the store predates the flag.
try { settingsLables = $("Tag Rows").all().filter((item) => !(item.json && item.json.enabled === false)).map((item) => (item.json.LABEL||'').trim()); } catch (e) { settingsLables = []; }
const labelsToAdd = settingsLables
  .filter((n) => n && !n.startsWith("-"))
  .filter((n) => !labels.includes(n))
  .map((n) => ({ label: n }));
return labelsToAdd;`,
    };

    @node({
        id: '67c0bbd2-6dbe-48bd-8105-2118f0a172d1',
        name: 'Create Labels Start',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [144, -208],
    })
    CreateLabelsStart = {};

    @node({
        id: 'f65b085a-3e91-42c7-b9b4-b4465e03b023',
        name: 'Split Settings',
        type: 'n8n-nodes-base.splitOut',
        version: 1,
        position: [1040, -176],
    })
    SplitSettings = {
        fieldToSplitOut: '=on_create_settings',
        options: {},
    };

    @node({
        id: 'd94b2109-786b-4805-b123-bfeeb3419822',
        name: 'Add label to message',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1264, 496],
    })
    AddLabelToMessage = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'addLabels',
                params: "={{ ({ id: $json.id, labelIds: $json.labelIds, connection_id: $('Mail Connection').first().json.connection_id }) }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'op',
                    displayName: 'op',
                    required: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                },
                {
                    id: 'params',
                    displayName: 'params',
                    required: false,
                    display: true,
                    type: 'object',
                    canBeUsedToMatch: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: '572c4474-eb17-4d68-8618-8d39b2389f94',
        name: 'Get final labels',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [144, -16],
    })
    GetFinalLabels = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'listLabels',
                params: "={{ ({ connection_id: $('Mail Connection').first().json.connection_id }) }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'op',
                    displayName: 'op',
                    required: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                },
                {
                    id: 'params',
                    displayName: 'params',
                    required: false,
                    display: true,
                    type: 'object',
                    canBeUsedToMatch: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: '8854987f-9fff-411b-a46c-a70371a8c44d',
        name: 'Final Label Ids',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [368, -16],
    })
    FinalLabelIds = {
        jsCode: `

const final_lable_ids_by_name = {}
for (const item of $input.all()) {
  final_lable_ids_by_name[item.json.name] = item.json.id
}
return [{final_lable_ids_by_name}];`,
    };

    @node({
        id: '5c4b8c9a-cd2b-4d62-a1bd-737e4c1f8278',
        name: 'End',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [144, 176],
    })
    End = {};

    @node({
        id: 'cb6f3861-4f10-4f62-ac51-f4b4b0974ba1',
        name: 'Start Get Tag Settings',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [144, -400],
    })
    StartGetTagSettings = {};

    @node({
        id: 'a12904e2-4c12-4d61-b680-3085473c7d64',
        name: 'Get Mail Thread',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [368, 272],
    })
    GetMailThread = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'getThread',
                params: "={{ ({ id: $('Start Mail Item').item.json.threadId, connection_id: $('Mail Connection').first().json.connection_id }) }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'op',
                    displayName: 'op',
                    required: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                },
                {
                    id: 'params',
                    displayName: 'params',
                    required: false,
                    display: true,
                    type: 'object',
                    canBeUsedToMatch: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: '627506a8-1292-4532-a938-54e939f10986',
        name: 'Start Mail Item',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [144, 368],
    })
    StartMailItem = {};

    @node({
        id: '186ec54e-f52c-4d5a-888f-1565d251f790',
        name: 'Get a message',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [-544, -304],
        onError: 'continueRegularOutput',
    })
    GetAMessage = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'get',
                params: "={{ ({ id: $json.id, attachments: false, meta: true, connection_id: $('Mail Connection').first().json.connection_id }) }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'op',
                    displayName: 'op',
                    required: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                },
                {
                    id: 'params',
                    displayName: 'params',
                    required: false,
                    display: true,
                    type: 'object',
                    canBeUsedToMatch: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        mode: 'each',
        options: {},
    };

    @node({
        id: '4a0d83d9-f523-4a37-8711-36bb3ffcb84a',
        name: 'When clicking ‘Execute workflow’',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [-1424, -80],
    })
    WhenClickingExecuteWorkflow = {};

    @node({
        id: '053966cd-d31b-4364-bc85-b50817732442',
        name: 'If Should Apply',
        type: 'n8n-nodes-base.if',
        version: 2.3,
        position: [592, 464],
    })
    IfShouldApply = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 3,
            },
            conditions: [
                {
                    id: '76dbab84-cf97-4c0e-9fa3-0a33c0367ed6',
                    leftValue: '={{ $json.shouldApplyLabel }}',
                    rightValue: false,
                    operator: {
                        type: 'boolean',
                        operation: 'true',
                        singleValue: true,
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: 'e4c8563f-f3c7-49b2-86f7-f58323205ed2',
        name: 'Remove label from message',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1264, 688],
    })
    RemoveLabelFromMessage = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'removeLabels',
                params: "={{ ({ id: $json.id, labelIds: $json.labelIds, connection_id: $('Mail Connection').first().json.connection_id }) }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'op',
                    displayName: 'op',
                    required: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                },
                {
                    id: 'params',
                    displayName: 'params',
                    required: false,
                    display: true,
                    type: 'object',
                    canBeUsedToMatch: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: 'f9173450-db8f-4724-953a-f48b6a7aeca2',
        name: 'Target specific mail (text search)',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [-912, -80],
    })
    TargetSpecificMailTextSearch = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'search',
                params: "={{ (() => { const L = ((($('Load Settings (manual)').first().json||{}).gmail)||{}).labels||{}; /* [one marker 2026-09-02, owner rule] the manual run searches exactly what the scheduled one does — exclude ONLY the completion label. INDOX's TO_SYNC / IN_PROGRESS marks are not this engine's business, and naming a label a mailbox lacks makes mailapi refuse the whole search. [N3 2026-09-02] limit 50 = the scheduled batch mail01 dispatches, so a manual run drains the same slice. */ const p = (L.PROCESSED && L.PROCESSED.name) ? L.PROCESSED.name : 'תוויות-טופל'; return ({ folder: '[Gmail]/All Mail', query: \"-in:scheduled -label:\" + p.replace(/ /g,'-'), limit: 50, connection_id: $('Conn (manual)').first().json.connection_id }); })() }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'op',
                    displayName: 'op',
                    required: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                },
                {
                    id: 'params',
                    displayName: 'params',
                    required: false,
                    display: true,
                    type: 'object',
                    canBeUsedToMatch: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    // [worker-only 2026-08-27, owner order] THE SCHEDULE TRIGGER LIVED HERE AND IS GONE.
    // This workflow used to schedule itself and, in the first version of the fan-out, call
    // itself once per connection - self-recursion bounded only by the accident that Sub Trigger's
    // path never reached the fan-out. One new edge and depth-1 would have become unbounded.
    // Scheduling now lives in mail01, a separate scheduler that enumerates mail connections and
    // invokes this workflow once per mailbox, exactly as indox01 does over indox_instances.
    // This is a pure worker now: it runs from Sub Trigger (per-connection, from mail01) or from
    // the manual trigger. It has no cadence of its own and must not regain one.
    // [N3 2026-09-02] the orphaned remains of that lane - 'Load Settings (sched)', 'Conn (sched)'
    // and 'Get many messages', islands with no connection since the trigger left - are deleted.
    // NOTE the deleted node was a SCHEDULE trigger: n8n keeps firing a removed schedule from
    // main's memory until main restarts, so expect ghost ticks of the old lane until then.

    @node({
        id: '59619a9b-1314-4cb4-aaab-80b9cefbc618',
        name: 'Prepare Context',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-80, -208],
        executeOnce: true,
    })
    PrepareContext = {};

    @node({
        id: 'a7bac185-c0f2-4ac3-8b7c-e6ecaede9cf0',
        name: 'Start',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-304, -304],
    })
    Start = {};

    @node({
        id: 'ee062998-ba0b-486c-bfb7-b593577a3f13',
        name: 'Batching 1',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [-96, 432],
    })
    Batching1 = {
        options: {},
    };

    @node({
        id: '750ea140-8c97-4be4-8042-d35cd82d4e3a',
        name: 'Add / Remove Label',
        type: 'n8n-nodes-base.if',
        version: 2.3,
        position: [816, 592],
    })
    AddRemoveLabel = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 3,
            },
            conditions: [
                {
                    id: '1addd2d0-7061-4177-a84b-f2361cd60e25',
                    leftValue: '={{ $json.labelToApply }}',
                    rightValue: '-',
                    operator: {
                        type: 'string',
                        operation: 'notStartsWith',
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: '44e1ecd9-9d33-40f3-b3a9-2fca2bb4b5e3',
        name: 'Lable Engine',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [368, 464],
    })
    LableEngine = {
        jsCode: `// Gmail Label Rule Engine for n8n - GENERIC v6.2 OPTIMIZED
// Pure JavaScript expressions with preprocessed data objects
// Minimal code, maximum flexibility
// UPDATED: Skip existing labels + auto-apply the PROCESSED marker (name resolved from settings/Tag Rows)

// ═══════════════════════════════════════════════════════════════════════════
// PART 1: UTILITY FUNCTIONS (Reusable Library)
// ═══════════════════════════════════════════════════════════════════════════

// ─── STRING UTILITIES ───────────────────────────────────────────────────────
const contains = (str, search) =>
  !!(str && search) && String(str).toLowerCase().includes(String(search).toLowerCase());

const containsAny = (str, searches) =>
  Array.isArray(searches) && searches.some(s => contains(str, s));

const containsAll = (str, searches) =>
  Array.isArray(searches) && searches.every(s => contains(str, s));

const startsWith = (str, prefix) =>
  !!(str && prefix) && String(str).toLowerCase().startsWith(String(prefix).toLowerCase());

const endsWith = (str, suffix) =>
  !!(str && suffix) && String(str).toLowerCase().endsWith(String(suffix).toLowerCase());

const matches = (str, regex) => {
  try {
    return new RegExp(regex, "i").test(str || "");
  } catch (e) {
    console.error("Invalid regex:", regex, e);
    return false;
  }
};

const isEmpty = (val) =>
  !val || (Array.isArray(val) && val.length === 0) || val === "";

const isNotEmpty = (val) => !isEmpty(val);

const hasHebrew = (str) => /[\\u0590-\\u05FF]/.test(str || "");

const hasNonHebrewChars = (str) => /[^\\u0590-\\u05FF0-9]/.test(str || "");

const noHebrew = (str) => !hasHebrew(str) && hasNonHebrewChars(str);

// ─── ARRAY UTILITIES ────────────────────────────────────────────────────────
const includes = (arr, item) =>
  Array.isArray(arr) && arr.includes(item);

const includesAny = (arr, items) =>
  Array.isArray(arr) && Array.isArray(items) && items.some(i => arr.includes(i));

const includesAll = (arr, items) =>
  Array.isArray(arr) && Array.isArray(items) && items.every(i => arr.includes(i));

const len = (arr) => (Array.isArray(arr) ? arr.length : 0);

// Note: filter, some, every are native JS and work directly

// ─── EMAIL UTILITIES ────────────────────────────────────────────────────────
const isDomain = (emailAddr, domain) => {
  if (!emailAddr || !domain) return false;
  const cleanDomain = String(domain).replace(/^@/, "").toLowerCase();
  return String(emailAddr).toLowerCase().endsWith(cleanDomain);
};

const isAnyDomain = (emailAddr, domains) =>
  Array.isArray(domains) && domains.some(d => isDomain(emailAddr, d));

const inList = (emailAddr, list) => {
  if (!emailAddr || !Array.isArray(list)) return false;
  const lower = String(emailAddr).toLowerCase();
  return list.some(item => {
    const itemStr = String(item);
    return itemStr.includes("@")
      ? lower === itemStr.toLowerCase()
      : isDomain(emailAddr, itemStr);
  });
};

// ═══════════════════════════════════════════════════════════════════════════
// PART 2: DATA OBJECT BUILDERS
// ═══════════════════════════════════════════════════════════════════════════

// ─── ATTACHMENT ENRICHMENT (From v5) ───────────────────────────────────────
const HEBREW_REGEX = /[\\u0590-\\u05FF]/;
const UNITS = Object.freeze({
  b: 1, kb: 1024, mb: 1024 * 1024, gb: 1024 * 1024 * 1024, tb: 1024 * 1024 * 1024 * 1024
});

const EXT_TO_MIME = Object.freeze({
  ".pdf": "application/pdf", ".doc": "application/msword",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".xls": "application/vnd.ms-excel",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
  ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
  ".svg": "image/svg+xml", ".zip": "application/zip",
  ".rar": "application/x-rar-compressed", ".7z": "application/x-7z-compressed",
  ".tar": "application/x-tar", ".gz": "application/gzip"
});

const TYPE_RULES = Object.freeze([
  ["logo", (name) => /logo|brand/i.test(name)],
  ["signature", (name) => /signature|\\bsig\\b/i.test(name)],
  ["pdf", (name, mime) => name.endsWith(".pdf") || mime === "application/pdf"],
  ["doc", (name, mime) => /\\.docx?$/.test(name) || /word/i.test(mime)],
  ["excel", (name, mime) => /\\.xlsx?$/.test(name) || /spreadsheet|excel/i.test(mime)],
  ["image", (name, mime) => /\\.(png|jpe?g|gif|bmp|webp|svg|tiff?)$/i.test(name) || /^image\\//i.test(mime)],
  ["archive", (name, mime) => /\\.(zip|rar|7z|tar|gz)$/i.test(name) || /zip|archive/i.test(mime)]
]);

function parseFileSize(raw) {
  if (typeof raw === "number") return raw;
  if (!raw || typeof raw !== "string") return 0;
  const match = raw.trim().match(/^([\\d.]+)\\s*(b|kb|mb|gb|tb)?$/i);
  if (!match) return 0;
  const value = parseFloat(match[1]);
  const unit = (match[2] || "b").toLowerCase();
  return Math.round(value * (UNITS[unit] || 1));
}

function isLikelyInline(att) {
  const name = String(att.fileName || att.filename || "").toLowerCase();
  const mime = String(att.mimeType || "").toLowerCase();
  const size = parseFileSize(att.fileSize || att.size);
  
  let score = 0;
  if (/\\b(logo|brand|company|corp)\\b/.test(name)) score += 80;
  if (/\\b(signature|signed|\\bsig\\b)\\b/.test(name)) score += 80;
  if (/^(image\\d+|cid_|ii_)/.test(name)) score += 75;
  if (mime.startsWith("image/")) score += 20;
  if (size > 0 && size < 20 * 1024) score += 15;
  if (size > 0 && size < 50 * 1024) score += 10;
  if (!mime.startsWith("image/")) score -= 50;
  if (size > 200 * 1024) score -= 30;
  if (size > 500 * 1024) score -= 40;
  
  return score >= 60;
}

function enrichAttachments(rawAttachments) {
  return (rawAttachments || []).map((att) => {
    const rawName = att.fileName || att.filename || "";
    const name = String(rawName).toLowerCase();
    const extMatch = name.match(/(\\.[^.]+)$/);
    const ext = extMatch ? extMatch[1] : (att.fileExtension ? \`.\${att.fileExtension}\` : "");
    const mime = String(att.mimeType || EXT_TO_MIME[ext] || "application/octet-stream").toLowerCase();
    const size = parseFileSize(att.fileSize || att.size);
    
    let type = "other";
    for (const [typeName, testFn] of TYPE_RULES) {
      if (testFn(name, mime)) {
        type = typeName;
        break;
      }
    }
    
    const inline = isLikelyInline(att);
    
    return { name, ext, mime, size, type, inline };
  });
}

// ─── BUILD EMAIL OBJECT ─────────────────────────────────────────────────────
function buildEmail(emailJson, labelIdToName) {
  const resolvedLabels = (emailJson.labelIds || [])
    .map(id => labelIdToName[id])
    .filter(Boolean);
  
  const subject = emailJson.subject || "";
  const body = emailJson.text || emailJson.textPlain || "";
  const html = emailJson.html || emailJson.textHtml || "";
  const text = emailJson.text || emailJson.textPlain || emailJson.textHtml || "";
  const fullText = [subject, text].filter(Boolean).join(" ");
  
  return {
    // Text content
    subject,
    body,
    html,
    text: fullText,
    full_text: fullText, // Alias for easier rule writing
    
    // Participants
    from: emailJson.from?.value?.[0]?.address || "",
    to: (emailJson.to?.value || []).map(t => t.address || ""),
    cc: (emailJson.cc?.value || []).map(t => t.address || ""),
    bcc: (emailJson.bcc?.value || []).map(t => t.address || ""),
    replyTo: emailJson.replyTo?.value?.[0]?.address || "",
    
    // Metadata
    date: emailJson.date ? new Date(emailJson.date) : new Date(),
    age: emailJson.date ? Math.floor((Date.now() - new Date(emailJson.date)) / (1000 * 60 * 60)) : 0,
    ageDays: emailJson.date ? Math.floor((Date.now() - new Date(emailJson.date)) / (1000 * 60 * 60 * 24)) : 0,
    size: emailJson.sizeEstimate || 0,
    
    // Labels
    labels: resolvedLabels,
    
    // IDs
    threadId: emailJson.threadId || "",
    messageId: emailJson.id || ""
  };
}

// ─── BUILD THREAD OBJECT ────────────────────────────────────────────────────
function buildThread(threadJson) {
  const messages = threadJson?.messages || [];
  const firstMsg = messages[0] || {};
  
  let threadFrom = "";
  if (typeof firstMsg.From === "string") {
    const match = firstMsg.From.match(/<([^>]+)>/);
    threadFrom = match ? match[1] : firstMsg.From.replace(/["'\\s]/g, "");
  } else if (firstMsg.from) {
    threadFrom = firstMsg.from;
  } else if (firstMsg.FROM) {
    threadFrom = firstMsg.FROM;
  }
  
  const firstDate = firstMsg.date ? new Date(firstMsg.date) : new Date();
  
  // Build enriched messages array with full text access
  const enrichedMessages = messages.map((msg) => ({
    from: msg.from || msg.From || msg.FROM || "",
    subject: msg.subject || msg.Subject || msg.SUBJECT || "",
    body: msg.text || msg.textPlain || msg.body || "",
    html: msg.html || msg.textHtml || "",
    text: [
      msg.subject || msg.Subject || msg.SUBJECT,
      msg.text || msg.textPlain || msg.body,
      msg.html || msg.textHtml
    ].filter(Boolean).join(" "),
    date: msg.date ? new Date(msg.date) : new Date(),
    id: msg.id || msg.messageId || ""
  }));
  
  return {
    id: threadJson?.id || "",
    from: threadFrom,
    count: messages.length,
    age: Math.floor((Date.now() - firstDate) / (1000 * 60 * 60)),
    ageDays: Math.floor((Date.now() - firstDate) / (1000 * 60 * 60 * 24)),
    isFirst: messages.length === 1,
    participants: [...new Set(messages.map(m => m.from || m.From || m.FROM || "").filter(Boolean))],
    messages: enrichedMessages
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// PART 3: RULE EVALUATOR
// ═══════════════════════════════════════════════════════════════════════════

function evaluateRule(ruleString, email, thread, attachments) {
  try {
    // Create evaluation function with safe context
    const fn = new Function(
      "email", "thread", "attachments",
      // String utilities
      "contains", "containsAny", "containsAll", "startsWith", "endsWith",
      "matches", "isEmpty", "isNotEmpty", "hasHebrew", "hasNonHebrewChars", "noHebrew",
      // Array utilities
      "includes", "includesAny", "includesAll", "len",
      // Email utilities
      "isDomain", "isAnyDomain", "inList",
      \`"use strict"; return (\${ruleString});\`
    );
    
    // Execute with data objects and utilities
    const result = fn(
      email, thread, attachments,
      contains, containsAny, containsAll, startsWith, endsWith,
      matches, isEmpty, isNotEmpty, hasHebrew, hasNonHebrewChars, noHebrew,
      includes, includesAny, includesAll, len,
      isDomain, isAnyDomain, inList
    );
    
    return !!result;
  } catch (error) {
    console.error("Rule evaluation error:", ruleString, error);
    return false;
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// PART 4: MAIN EXECUTION
// ═══════════════════════════════════════════════════════════════════════════

// ─── INPUT DATA ─────────────────────────────────────────────────────────────
const emailJson = $("Start Mail Item").last().json;
const binaryData = $("Start Mail Item").last().binary;
const threadJson = $("Get Mail Thread").last().json;
// [N2 2026-09-02] a rule the editor disabled (enabled === false) is skipped here and in
// 'Labels to create'. Absent/null = enabled: the store predates the flag. The PROCESSED marker
// below is NOT a rule and never subject to it - it is this engine's only state.
const allRules = $("Split Settings").all().filter((r) => !(r.json && r.json.enabled === false));
const finalLabelIds = $("Final Label Ids").last().json.final_lable_ids_by_name;

// ─── PRE-COMPUTED LOOKUPS ───────────────────────────────────────────────────
const labelIdToName = Object.fromEntries(
  Object.entries(finalLabelIds).map(([name, id]) => [id, name])
);

const baseLabels = new Set(
  (emailJson.labelIds || [])
    .map(id => labelIdToName[id])
    .filter(Boolean)
);

// ─── BUILD DATA OBJECTS (ONE TIME) ──────────────────────────────────────────
const _metaAtts = emailJson.attachmentsMeta;  // attachment name/mime/size without bytes (meta fetch)
emailJson.attachments = (Array.isArray(_metaAtts) && _metaAtts.length) ? _metaAtts : Object.values(binaryData || {});
const attachments = enrichAttachments(emailJson.attachments);
const email = buildEmail(emailJson, labelIdToName);
const thread = buildThread(threadJson);

// ─── EVALUATE ALL RULES ─────────────────────────────────────────────────────
const labelsAppliedInThisRun = [];
const PROCESSED_LABEL = (() => { try { const r = $('Tag Rows').all().map(i=>i.json).find(x => x.KEY === 'PROCESSED'); return r ? (r.LABEL||'').trim() : null; } catch (e) { return null; } })();

const results = allRules.map((ruleItem) => {
  const rule = ruleItem.json;
  
  // Update email.labels with dynamically applied labels
  email.labels = [...baseLabels, ...labelsAppliedInThisRun];
  
  // OPTIMIZATION 1: Check if label already exists
  const labelAlreadyExists =  (!rule.LABEL.startsWith("-") && email.labels.includes(rule.LABEL)) || (rule.LABEL.startsWith("-") && !email.labels.includes(rule.LABEL.slice(1)))
  
  let shouldApplyLabel = false;
  let info = null;
  
  if (labelAlreadyExists) {
    shouldApplyLabel = false;
    info = "Label already exists";
  } else {
    // Only evaluate rule if label doesn't exist
    shouldApplyLabel = evaluateRule(rule.RULE, email, thread, attachments);
    
    if (shouldApplyLabel) {
      labelsAppliedInThisRun.push(rule.LABEL);
    }
  }
  
  const output = {
    json: {
      emailId: email.messageId,
      threadId: email.threadId,
      shouldApplyLabel,
      labelToApply: rule.LABEL,
      rule: rule.RULE,
      ruleType: rule.TYPE,
      rowNumber: rule.row_number,
      appliedLabels: email.labels,
      attachments: emailJson.attachments,
      enrichedAttachments: attachments,
      labelsAppliedInThisRun: [...labelsAppliedInThisRun],
      info
    }
  };

  return output;
});

// ─── OPTIMIZATION 2: Add the PROCESSED marker (name from settings/Tag Rows) ───
// Add the processed label to every email that went through the engine
const processedLabelEntry = {
  json: {
    emailId: email.messageId,
    threadId: email.threadId,
    shouldApplyLabel: !!PROCESSED_LABEL && !baseLabels.has(PROCESSED_LABEL) && !labelsAppliedInThisRun.includes(PROCESSED_LABEL),
    labelToApply: PROCESSED_LABEL,
    rule: "AUTO_PROCESSED",
    ruleType: "SYSTEM",
    rowNumber: 0,
    appliedLabels: email.labels,
    attachments: emailJson.attachments,
    enrichedAttachments: attachments,
    labelsAppliedInThisRun: [...labelsAppliedInThisRun],
    info: baseLabels.has(PROCESSED_LABEL) ? "Label already exists" : "Auto-applied processed marker",
    email_debug: email
  }
};

// Prepend the processed label entry so it applies first
return [processedLabelEntry, ...results];`,
    };

    @node({
        id: 'load-settings-rules',
        name: 'Load Settings (rules)',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [368, -400],
    })
    LoadSettingsRules = {
        url: 'http://mailapi:8970/organizer/settings',
        options: {
            timeout: 15000,
        },
    };

    @node({
        id: 'tag-rows',
        name: 'Tag Rows',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [592, -400],
    })
    TagRows = {
        jsCode: `// tag rules served THROUGH settings (settings.gmail.rows) — single loader, no direct table read.
// [guard 2026-09-02] a degraded settings payload (transient chain failure) yields NO rules
// instead of a TypeError that kills the pass - the same degrade the search lanes get. With no
// rules nothing is stamped, so the next tick sees the same mail again; a store that genuinely
// lost its PROCESSED row is refused upstream by mail01 before any pass is dispatched.
return (((($('Load Settings (rules)').first().json||{}).gmail)||{}).rows || []).map(r => ({ json: r }));`,
    };

    @node({
        id: 'load-settings-manual',
        name: 'Load Settings (manual)',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [-1248, -80],
    })
    LoadSettingsManual = {
        url: 'http://mailapi:8970/organizer/settings',
        options: {
            timeout: 15000,
        },
    };

    @node({
        id: 'agg-add-labels-01',
        name: 'Agg Add Labels',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1040, 496],
    })
    AggAddLabels = {
        jsCode: `// OVERQUOTA fix: batch ALL add-labels for this message into ONE addLabels call
// (was one executeWorkflow + one IMAP STORE per label). imap applies a list in one STORE.
const map = $("Final Label Ids").last().json.final_lable_ids_by_name || {};
const id = $('Start Mail Item').first().json.id;
const ids = [];
for (const it of $input.all()) {
  const v = map[it.json.labelToApply];
  if (v != null && v !== '' && !ids.includes(v)) ids.push(v);
}
return ids.length ? [{ json: { id, labelIds: ids } }] : [];`,
    };

    @node({
        id: 'agg-rem-labels-01',
        name: 'Agg Remove Labels',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1040, 688],
    })
    AggRemoveLabels = {
        jsCode: `// OVERQUOTA fix: batch ALL remove-labels for this message into ONE removeLabels call.
const map = $("Final Label Ids").last().json.final_lable_ids_by_name || {};
const id = $('Start Mail Item').first().json.id;
const ids = [];
for (const it of $input.all()) {
  const name = String(it.json.labelToApply || '').slice(1);
  const v = map[name];
  if (v != null && v !== '' && !ids.includes(v)) ids.push(v);
}
return ids.length ? [{ json: { id, labelIds: ids } }] : [];`,
    };

    @node({
        id: 'mailorg-sub-trigger',
        name: 'Sub Trigger',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [-1296, -560],
    })
    SubTrigger = {
        workflowInputs: {
            values: [
                {
                    name: 'query',
                },
                {
                    name: 'limit',
                    type: 'number',
                },
                {
                    name: 'connection_id',
                },
                {
                    name: 'processed_label',
                },
            ],
        },
    };

    @node({
        id: 'mailorg-sub-search',
        name: 'Sub Search',
        /*__n8n__*/ notes: "[bootstrap 2026-08-27, owner order] onError is continueErrorOutput so a mailbox that does NOT yet have the PROCESSED label routes to 'Bootstrap PROCESSED Label' instead of killing the run. mailapi refuses a query naming an unknown label rather than answering total:0, and label creation lives DOWNSTREAM of this node - so a mailbox that has never been labelled could never get past here to create the very label it is filtered on. The error output breaks that circle: create the label now, and the next tick's search succeeds.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [-1056, -560],
        onError: 'continueErrorOutput',
    })
    SubSearch = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'search',
                params: "={{ ({ folder: '[Gmail]/All Mail', query: $json.query, limit: $json.limit || 50, connection_id: $('Conn (sub)').first().json.connection_id }) }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'op',
                    displayName: 'op',
                    required: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                },
                {
                    id: 'params',
                    displayName: 'params',
                    required: false,
                    display: true,
                    type: 'object',
                    canBeUsedToMatch: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: 'b4f5e001-0a1a-4a1a-9a1a-mle-fetchok01',
        name: 'Fetch OK?',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [-416, -304],
    })
    FetchOk = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'fetch-ok-1',
                    leftValue: '={{ $json.error }}',
                    rightValue: '',
                    operator: {
                        type: 'string',
                        operation: 'empty',
                        singleValue: true,
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: 'b4f5e002-0a1a-4a1a-9a1a-mle-skipfail01',
        name: 'Skipped - Fetch Failed',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-336, -80],
    })
    SkippedFetchFailed = {};

    // [worker-only 2026-08-27] 'Call Per Connection' lived here and is GONE with the
    // Schedule Trigger. It made this workflow call ITSELF once per mail connection; the
    // fan-out now lives in mail01 so nothing here is recursive.

    @node({
        id: 'mle01-bootstrap-processed',
        name: 'Bootstrap PROCESSED Label',
        /*__n8n__*/ notes: "[bootstrap 2026-08-27, owner order] Creates the PROCESSED label in a mailbox that does not have it, so the NEXT tick's search succeeds. Reached only from 'Sub Search' error output. Why it is needed: mailapi refuses a query naming an unknown label rather than answering total:0, and the normal label-creation path (Get many labels -> Labels to create -> Create a label) runs AFTER the search - so a fresh mailbox died at the search before it could ever create the label it was being filtered on. Measured on the 00:45 tick: 2 of 6 connections failed exactly this way. The label name is taken from processed_label, which mail01 puts on every item - NOT parsed back out of the query, because the query hyphenates spaces and this label already contains a hyphen. connection_id comes from Conn (sub) rather than Mail Connection, because Mail Connection sits downstream of the search and has not run on this path. onError:continueRegularOutput: if creation itself fails (permissions, a mailbox that is gone) this run ends quietly rather than turning a skipped mailbox into a hard failure - the tick still reports every other connection.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [-856, -432],
        onError: 'continueRegularOutput',
    })
    BootstrapProcessedLabel = {
        workflowId: {
            __rl: true,
            mode: 'id',
            value: 'gmailApiImap01',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'createLabel',
                params: "={{ ({ name: $('Conn (sub)').first().json.processed_label, connection_id: $('Conn (sub)').first().json.connection_id }) }}",
            },
        },
        options: {},
    };

    @node({
        id: 'c0nnmanu-2b3c-4d4e-9f5a-mle01manual1',
        name: 'Conn (manual)',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-1088, -80],
    })
    ConnManual = {
        jsCode: `// Resolve THE mailbox this run acts on. One call to resolve; every mail op below then
// names that id explicitly. Owner mandate (2026-08-07): "every workflow acting on the
// mail should know which connection it's working on ... never act blindly, no fallbacks
// or so-called selected connection at mail app level" - and where a selected connection
// IS used it must be two separate calls: this node is the resolve call, the mail nodes
// are the act calls. mailapi refuses any canonical op that names no connection (400),
// which is what failed every run of this workflow from 10:30 on 2026-08-09.
//
// GET /connections, NOT /engine/profiles. The test suites resolve through /engine/profiles
// on purpose: it lists only the LOCAL dovecot engine accounts, so a suite physically
// cannot seed fixture mail into a real mailbox. This workflow is the opposite case - it
// is the client's production labeller and its mailbox IS a real Gmail connection, absent
// from /engine/profiles entirely. Resolving here through profiles would not 400; it would
// silently label admin@local.test instead, which is worse than the outage it fixes.
// /data/active.json is never read: \`active\` arrives as DATA on this resolve call and is
// handed back explicitly, which is exactly the two-call shape the mandate requires.

const r = await this.helpers.httpRequest({ method: 'GET',
  url: 'http://mailapi:8970/connections', json: true, timeout: 15000 });
const list = (r && r.connections) ? r.connections : [];
const sel = (r && typeof r.active === 'string') ? r.active.trim() : '';
const hit = list.filter(c => c && c.id === sel)[0];
// No usable id stops the run here, with a reason. Never '' and never a guess: an empty
// connection_id is the precise shape the guard rejects, and a guessed one would label a
// mailbox nobody named - the failure mode the guard exists to prevent.
if (!hit) throw new Error('mailLabelEngine01: mailapi resolved no usable selected'
  + ' connection (active=' + JSON.stringify(sel) + ', ' + list.length + ' configured).'
  + ' Refusing to run: a mail op must name its mailbox.');
const cid = hit.id;
return $input.all().map(i => ({ json: { ...i.json, connection_id: cid } }));
`,
    };

    @node({
        id: 'c0nnsub0-3c4d-4e5f-a06b-mle01sub0001',
        name: 'Conn (sub)',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-1184, -560],
    })
    ConnSub = {
        jsCode: `// The sub-call's resolve node (the scheduled lane and its 'Conn (sched)' are gone: mail01
// enumerates the registry and names the mailbox on every call). A caller invokes this workflow through
// Sub Trigger and names the mailbox itself (mailOrgTest00001 passes its local dovecot id).
// Honour that id: a suite run must stay on its own mailbox and must NOT be redirected to
// whatever the deployment currently has selected. Only a call that named nothing at all
// resolves, and it resolves by ASKING mailapi (two calls) - never by letting mailapi infer.
const raw = $input.first().json.connection_id;
let cid = (typeof raw === 'string') ? raw.trim() : '';
// n8n renders an unresolved expression to '' and a missing key to 'undefined'/'null'.
// Those are ABSENT, not a connection named 'undefined'. Normalise before deciding.
if (['', 'undefined', 'null', 'none'].indexOf(cid.toLowerCase()) !== -1) cid = '';
if (!cid) {
  const r = await this.helpers.httpRequest({ method: 'GET',
    url: 'http://mailapi:8970/connections', json: true, timeout: 15000 });
  const list = (r && r.connections) ? r.connections : [];
  const sel = (r && typeof r.active === 'string') ? r.active.trim() : '';
  const hit = list.filter(c => c && c.id === sel)[0];
  if (!hit) throw new Error('mailLabelEngine01: sub-call named no connection_id and'
    + ' mailapi resolved no usable selected connection (active='
    + JSON.stringify(sel) + ').');
  cid = hit.id;
}
return $input.all().map(i => ({ json: { ...i.json, connection_id: cid } }));
`,
    };

    @node({
        id: 'ma1lc0nn-4d5e-4f60-b17c-mle01shared1',
        name: 'Mail Connection',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-688, -304],
    })
    MailConnection = {
        jsCode: `// The one node name every mail op downstream reads for its mailbox.
// Two entry paths can reach here (manual / sub-call from mail01) and each resolved the
// mailbox at its own head. The search node in between returns Gmail-SHAPED message items
// (id/threadId/labels) that carry no connection_id, so the id is republished here rather
// than threaded through a shape this workflow does not own.
// $('<node>') throws for a node that did not run in this execution - that throw IS the
// routing test, so no separate 'which trigger fired' flag has to be kept in sync.
function ran(n) { try { return $(n).first().json; } catch (e) { return null; } }
let cid = '';
for (const n of ['Conn (manual)', 'Conn (sub)']) {
  const j = ran(n);
  if (j && typeof j.connection_id === 'string' && j.connection_id) { cid = j.connection_id; break; }
}
if (!cid) throw new Error('mailLabelEngine01: no entry path resolved a mailbox - refusing'
  + ' to run mail ops unnamed.');
return $input.all().map(i => ({ json: { ...i.json, connection_id: cid } }));
`,
    };

    @node({
        id: 'mle-stamp-outline',
        name: 'Stamp Outline',
        /*__n8n__*/ notes: "Highlight data for the concurrency board (execution_metadata key `outline`). The label engine runs once PER CONNECTION, so without the connection id on the board six concurrent runs are six anonymous identical bars.",
        type: 'n8n-nodes-base.executionData',
        version: 1,
        position: [-836, -400],
    })
    StampOutline = {
        dataToSave: {
            values: [
                {
                    key: 'outline',
                    value: "={{ ($('Sub Trigger').first().json.connection_id || 'label-engine') + '_x' + $input.all().length + '_threads' }}",
                },
                {
                    key: 'exection_type',
                    value: 'mail_label_engine',
                },
                {
                    key: 'connection_id',
                    value: "={{ $('Sub Trigger').first().json.connection_id }}",
                },
                {
                    key: 'threads',
                    value: '={{ $input.all().length }}',
                },
            ],
        },
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.ConnManual.out(0).to(this.TargetSpecificMailTextSearch.in(0));
        this.ConnSub.out(0).to(this.SubSearch.in(0));
        this.MailConnection.out(0).to(this.GetAMessage.in(0));
        this.OnCreateSettings.out(0).to(this.SplitSettings.in(0));
        this.GetManyLabels.out(0).to(this.LabelsToCreate.in(0));
        this.LoopOverItems.out(1).to(this.CreateALabel.in(0));
        this.CreateALabel.out(0).to(this.LoopOverItems.in(0));
        this.LabelsToCreate.out(0).to(this.LoopOverItems.in(0));
        this.CreateLabelsStart.out(0).to(this.GetManyLabels.in(0));
        this.GetFinalLabels.out(0).to(this.FinalLabelIds.in(0));
        this.StartGetTagSettings.out(0).to(this.LoadSettingsRules.in(0));
        this.StartMailItem.out(0).to(this.GetMailThread.in(0));
        this.StartMailItem.out(0).to(this.LableEngine.in(0));
        this.GetAMessage.out(0).to(this.FetchOk.in(0));
        this.WhenClickingExecuteWorkflow.out(0).to(this.LoadSettingsManual.in(0));
        this.IfShouldApply.out(0).to(this.AddRemoveLabel.in(0));
        this.TargetSpecificMailTextSearch.out(0).to(this.MailConnection.in(0));
        this.PrepareContext.out(0).to(this.CreateLabelsStart.in(0));
        this.PrepareContext.out(0).to(this.GetFinalLabels.in(0));
        this.PrepareContext.out(0).to(this.StartGetTagSettings.in(0));
        this.Start.out(0).to(this.PrepareContext.in(0));
        this.Start.out(0).to(this.Batching1.in(0));
        this.Batching1.out(0).to(this.End.in(0));
        this.Batching1.out(1).to(this.Batching1.in(0));
        this.Batching1.out(1).to(this.StartMailItem.in(0));
        this.AddRemoveLabel.out(0).to(this.AggAddLabels.in(0));
        this.AddRemoveLabel.out(1).to(this.AggRemoveLabels.in(0));
        this.LableEngine.out(0).to(this.IfShouldApply.in(0));
        this.LoadSettingsRules.out(0).to(this.TagRows.in(0));
        this.TagRows.out(0).to(this.OnCreateSettings.in(0));
        this.LoadSettingsManual.out(0).to(this.ConnManual.in(0));
        this.AggAddLabels.out(0).to(this.AddLabelToMessage.in(0));
        this.AggRemoveLabels.out(0).to(this.RemoveLabelFromMessage.in(0));
        this.SubTrigger.out(0).to(this.ConnSub.in(0));
        this.SubSearch.out(0).to(this.MailConnection.in(0));
        this.SubSearch.out(0).to(this.StampOutline.in(0));
        this.SubSearch.out(1).to(this.BootstrapProcessedLabel.in(0));
        this.FetchOk.out(0).to(this.Start.in(0));
        this.FetchOk.out(1).to(this.SkippedFetchFailed.in(0));
    }
}
