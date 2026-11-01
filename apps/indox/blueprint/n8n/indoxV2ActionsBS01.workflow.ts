import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox-v2 Actions — BS
// Nodes   : 47  |  Connections: 62
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// LoopOverItems19                    splitInBatches
// ActionRestartBs                    noOp
// Aggregate                          aggregate
// SkipUpdateDocument                 noOp
// ActionUpdateStatusExtractionFailed noOp
// StartLinkingDocuments              noOp
// JoinSearchResults                  code
// PrepareSplit                       code
// Switch2                            switch
// IfExact                            if
// LoopOverItems7                     splitInBatches
// LoopOverItems10                    splitInBatches
// LoopOverBalanceSheets              splitInBatches
// EndLinkDocument                    noOp
// _3bBsActionSwitch1                 switch
// LoopOverItems16                    splitInBatches
// ActionUpdateStatusMissingCompanyId noOp
// LoopOverItems9                     splitInBatches
// ActionMarkCompletedBs              noOp
// SplitLines1                        splitOut
// ActionLinkDocuments1               noOp
// LoopOverItems18                    splitInBatches
// WhenCalled                         executeWorkflowTrigger
// BuildCallIncomingDocumentBatchUpdateStatusMissingCompanyIdBs set
// BuildCallIncomingDocumentBatchUpdate3 set
// UpsertCallIncomingDocumentBatchUpdate3 executeWorkflow
// BuildCallIncomingDocumentBatchUpdate set
// UpsertCallIncomingDocumentBatchUpdate executeWorkflow
// BuildRestartClearCompletedFlags    code
// BuildCallIncomingDocumentBatchUpdate2 set
// UpsertCallIncomingDocumentBatchUpdate2 executeWorkflow
// BuildCallIncomingDocumentBatchUpdateStatusExtractionFailed set
// BuildCallIncomingDocumentBatchUpdateStatusCompletedBs set
// UpsertCentral                      executeWorkflow
// GetReq                             code
// CallIndoxApiGetAll                 executeWorkflow
// MatchExisting                      code
// DecideBsAction                     code
// RouteMode                          switch
// StopAndErrorUnhandledBsAction      stopAndError
// ActionExtractPerTypeBs             noOp
// CallBsdocex01                      executeWorkflow            [onError→regular]
// BuildPerTypeUpsertBs               set
// ActionSelectType                   noOp
// LoopSelectType                     splitInBatches
// CallSelecttype01                   executeWorkflow            [onError→regular]
// BuildSelectTypeUpsert              set
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → RouteMode
//      → DecideBsAction
//     .out(1) → _3bBsActionSwitch1
//        → ActionUpdateStatusMissingCompanyId
//          → LoopOverItems7
//           .out(1) → BuildCallIncomingDocumentBatchUpdateStatusMissingCompanyIdBs
//              → UpsertCentral
//           .out(1) → LoopOverItems7 (↩ loop)
//       .out(2) → ActionRestartBs
//          → LoopOverItems16
//           .out(1) → BuildRestartClearCompletedFlags
//              → UpsertCentral (↩ loop)
//           .out(1) → LoopOverItems16 (↩ loop)
//       .out(3) → ActionExtractPerTypeBs
//          → CallBsdocex01
//            → BuildPerTypeUpsertBs
//              → UpsertCentral (↩ loop)
//       .out(4) → ActionUpdateStatusExtractionFailed
//          → LoopOverItems9
//           .out(1) → BuildCallIncomingDocumentBatchUpdateStatusExtractionFailed
//              → UpsertCentral (↩ loop)
//           .out(1) → LoopOverItems9 (↩ loop)
//       .out(6) → ActionLinkDocuments1
//          → LoopOverBalanceSheets
//           .out(1) → StartLinkingDocuments
//              → BuildCallIncomingDocumentBatchUpdate2
//                → UpsertCallIncomingDocumentBatchUpdate2
//              → PrepareSplit
//                → SplitLines1
//                  → GetReq
//                    → CallIndoxApiGetAll
//                      → MatchExisting
//                        → JoinSearchResults
//                          → Switch2
//                            → IfExact
//                              → SkipUpdateDocument
//                                → EndLinkDocument
//                                  → Aggregate
//                             .out(1) → LoopOverItems18
//                                → EndLinkDocument (↩ loop)
//                               .out(1) → LoopOverItems18 (↩ loop)
//                               .out(1) → BuildCallIncomingDocumentBatchUpdate
//                                  → UpsertCallIncomingDocumentBatchUpdate
//                           .out(1) → LoopOverItems19
//                              → EndLinkDocument (↩ loop)
//                             .out(1) → LoopOverItems19 (↩ loop)
//                             .out(1) → BuildCallIncomingDocumentBatchUpdate3
//                                → UpsertCallIncomingDocumentBatchUpdate3
//           .out(1) → LoopOverBalanceSheets (↩ loop)
//       .out(7) → ActionMarkCompletedBs
//          → LoopOverItems10
//           .out(1) → BuildCallIncomingDocumentBatchUpdateStatusCompletedBs
//              → UpsertCentral (↩ loop)
//           .out(1) → LoopOverItems10 (↩ loop)
//       .out(10) → StopAndErrorUnhandledBsAction
//       .out(11) → ActionExtractPerTypeBs (↩ loop)
//       .out(14) → ActionSelectType
//          → LoopSelectType
//           .out(1) → CallSelecttype01
//              → BuildSelectTypeUpsert
//                → UpsertCentral (↩ loop)
//           .out(1) → LoopSelectType (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"Route Mode","type":"main","index":0}]]},"Loop Over Items19":{"main":[[{"node":"End Link Document","type":"main","index":0}],[{"node":"Loop Over Items19","type":"main","index":0},{"node":"Build: Call 'Incoming Document Batch Update'3","type":"main","index":0}]]},"Action: Restart BS":{"main":[[{"node":"Loop Over Items16","type":"main","index":0}]]},"Skip Update Document":{"main":[[{"node":"End Link Document","type":"main","index":0}]]},"Action: Update STATUS - EXTRACTION_FAILED":{"main":[[{"node":"Loop Over Items9","type":"main","index":0}]]},"Start Linking Documents":{"main":[[{"node":"Build: Call 'Incoming Document Batch Update'2","type":"main","index":0},{"node":"Prepare Split","type":"main","index":0}]]},"Join Search Results":{"main":[[{"node":"Switch2","type":"main","index":0}]]},"Prepare Split":{"main":[[{"node":"Split Lines1","type":"main","index":0}]]},"Switch2":{"main":[[{"node":"If Exact","type":"main","index":0}],[{"node":"Loop Over Items19","type":"main","index":0}]]},"If Exact":{"main":[[{"node":"Skip Update Document","type":"main","index":0}],[{"node":"Loop Over Items18","type":"main","index":0}]]},"Loop Over Items7":{"main":[[],[{"node":"Build: Call 'Incoming Document Batch Update' - STATUS MISSING_COMPANY_ID (BS)","type":"main","index":0},{"node":"Loop Over Items7","type":"main","index":0}]]},"Loop Over Items10":{"main":[[],[{"node":"Build: Call 'Incoming Document Batch Update' - STATUS COMPLETED (BS)","type":"main","index":0},{"node":"Loop Over Items10","type":"main","index":0}]]},"Loop Over Balance Sheets":{"main":[[],[{"node":"Start Linking Documents","type":"main","index":0},{"node":"Loop Over Balance Sheets","type":"main","index":0}]]},"End Link Document":{"main":[[{"node":"Aggregate","type":"main","index":0}]]},"3b. BS Action Switch1":{"main":[[{"node":"Action: Update STATUS - MISSING_COMPANY_ID","type":"main","index":0}],[],[{"node":"Action: Restart BS","type":"main","index":0}],[{"node":"Action: Extract Per Type (BS)","type":"main","index":0}],[{"node":"Action: Update STATUS - EXTRACTION_FAILED","type":"main","index":0}],[],[{"node":"Action: Link Documents1","type":"main","index":0}],[{"node":"Action: Mark Completed BS","type":"main","index":0}],[],[],[{"node":"Stop and Error - Unhandled BS ACTION","type":"main","index":0}],[{"node":"Action: Extract Per Type (BS)","type":"main","index":0}],[],[],[{"node":"Action: Select Type","type":"main","index":0}]]},"Action: Select Type":{"main":[[{"node":"Loop (select type)","type":"main","index":0}]]},"Loop (select type)":{"main":[[],[{"node":"Call SelectType01","type":"main","index":0},{"node":"Loop (select type)","type":"main","index":0}]]},"Call SelectType01":{"main":[[{"node":"Build Select Type Upsert","type":"main","index":0}]]},"Build Select Type Upsert":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Loop Over Items16":{"main":[[],[{"node":"Build: Restart (clear completed flags)","type":"main","index":0},{"node":"Loop Over Items16","type":"main","index":0}]]},"Action: Update STATUS - MISSING_COMPANY_ID":{"main":[[{"node":"Loop Over Items7","type":"main","index":0}]]},"Loop Over Items9":{"main":[[],[{"node":"Build: Call 'Incoming Document Batch Update' - STATUS EXTRACTION_FAILED","type":"main","index":0},{"node":"Loop Over Items9","type":"main","index":0}]]},"Action: Mark Completed BS":{"main":[[{"node":"Loop Over Items10","type":"main","index":0}]]},"Split Lines1":{"main":[[{"node":"GET Req","type":"main","index":0}]]},"Action: Link Documents1":{"main":[[{"node":"Loop Over Balance Sheets","type":"main","index":0}]]},"Loop Over Items18":{"main":[[{"node":"End Link Document","type":"main","index":0}],[{"node":"Loop Over Items18","type":"main","index":0},{"node":"Build: Call 'Incoming Document Batch Update'","type":"main","index":0}]]},"Build: Call 'Incoming Document Batch Update' - STATUS MISSING_COMPANY_ID (BS)":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Call 'Incoming Document Batch Update'3":{"main":[[{"node":"Upsert: Call 'Incoming Document Batch Update'3","type":"main","index":0}]]},"Upsert: Call 'Incoming Document Batch Update'3":{"main":[[]]},"Build: Call 'Incoming Document Batch Update'":{"main":[[{"node":"Upsert: Call 'Incoming Document Batch Update'","type":"main","index":0}]]},"Upsert: Call 'Incoming Document Batch Update'":{"main":[[]]},"Build: Restart (clear completed flags)":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Call 'Incoming Document Batch Update'2":{"main":[[{"node":"Upsert: Call 'Incoming Document Batch Update'2","type":"main","index":0}]]},"Upsert: Call 'Incoming Document Batch Update'2":{"main":[[]]},"Build: Call 'Incoming Document Batch Update' - STATUS EXTRACTION_FAILED":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Call 'Incoming Document Batch Update' - STATUS COMPLETED (BS)":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Call indox api (GET_ALL)":{"main":[[{"node":"Match Existing","type":"main","index":0}]]},"Match Existing":{"main":[[{"node":"Join Search Results","type":"main","index":0}]]},"Route Mode":{"main":[[{"node":"Decide BS Action","type":"main","index":0}],[{"node":"3b. BS Action Switch1","type":"main","index":0}]]},"GET Req":{"main":[[{"node":"Call indox api (GET_ALL)","type":"main","index":0}]]},"Action: Extract Per Type (BS)":{"main":[[{"node":"Call BsDocEx01","type":"main","index":0}]]},"Build Per Type Upsert (BS)":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Call BsDocEx01":{"main":[[{"node":"Build Per Type Upsert (BS)","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"1a1f9021-970c-46eb-8cef-4746d2dca0d0","name":"indox-state-machine-v2"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"22f1e71e-91bf-48db-811f-8d3bc4e55a3e","name":"sm-refactor-v2.1"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"2b5cb873-dd65-44dd-bf27-a2c99d2b81a4","name":"state-machine-v2"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:41:29.646Z","createdAt":"2026-07-30T23:41:29.646Z","id":"9c337cfe-7feb-4f3d-ab26-3de6439357ce","name":"sm-refactore-v2.1"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"b481a46d-6a18-4fdc-9eb5-c2d8ed3a639a","name":"role:action"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {"templateCredsSetupCompleted":true},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"indoxV2ActionsBS01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2ActionsBS01',
    name: 'indox-v2 Actions — BS',
    active: true,
    isArchived: false,
    tags: [
        'indox-state-machine-v2',
        'sm-refactor-v2.1',
        'state-machine-v2',
        'app:indox',
        'sm-refactore-v2.1',
        'role:action',
        'indox',
        'indox-app',
    ],
    settings: {
        executionOrder: 'v1',
        callerPolicy: 'workflowsFromSameOwner',
        errorWorkflow: 'errorHandler01',
        availableInMCP: false,
        timeSavedPerExecution: 30,
        timeSavedMode: 'fixed',
        executionTimeout: 3600,
        binaryMode: 'separate',
    },
})
export class IndoxV2ActionsBsWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: '08a41dc7-d04c-4472-9735-3e88c444ec9f',
        name: 'Loop Over Items19',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [5744, 7507],
    })
    LoopOverItems19 = {
        batchSize: 50,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: '6d9e7227-d317-4037-92b7-74355e8e1438',
        name: 'Action: Restart BS',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [3280, 6186],
    })
    ActionRestartBs = {};

    @node({
        id: 'ec8a3107-4305-4887-aaae-215f982cb483',
        name: 'Aggregate',
        type: 'n8n-nodes-base.aggregate',
        version: 1,
        position: [6192, 7070],
    })
    Aggregate = {
        aggregate: 'aggregateAllItemData',
        options: {},
    };

    @node({
        id: '70da6f33-6b39-436a-b2f4-ea5d224ef945',
        name: 'Skip Update Document',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [5744, 6926],
    })
    SkipUpdateDocument = {};

    @node({
        id: '4b30ae54-b8b6-4809-97bc-325e41f30421',
        name: 'Action: Update STATUS - EXTRACTION_FAILED',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [3280, 6484],
    })
    ActionUpdateStatusExtractionFailed = {};

    @node({
        id: '3be4c7fb-d9a4-47fe-8f3b-1b5ad339aeaa',
        name: 'Start Linking Documents',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [3728, 6724],
    })
    StartLinkingDocuments = {};

    @node({
        id: '8352c235-7756-4d77-9baa-6a91efcaa8c0',
        name: 'Join Search Results',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [5072, 7260],
    })
    JoinSearchResults = {
        jsCode: `// Loop over input items and add a new field called 'myNewField' to the JSON of each one
let i =0;
for (const item of $input.all()) {
  
  item.json = {
    ...$('Split Lines1').all()[i].json,

    "existing": item.json
  }
  i++;
}

return $input.all();`,
    };

    @node({
        id: '90ed58c1-5692-4ff5-903f-d7e74ede76bc',
        name: 'Prepare Split',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3952, 7260],
    })
    PrepareSplit = {
        mode: 'runOnceForEachItem',
        jsCode: `const base = $('Start Linking Documents').item.json;
// BS_EXTRACTED_LINES is TEXT in supabase (a JSON string); in other paths it may already be an object.
// Guard the parse so a missing/invalid value yields an empty line set instead of erroring the whole
// link action (best-effort enrichment must never block the doc from completing).
let parsed = base.BS_EXTRACTED_LINES;
if (typeof parsed === 'string') {
  try { parsed = JSON.parse(parsed); } catch (e) { parsed = { data: { lines: [] } }; }
}
if (!parsed || typeof parsed !== 'object') parsed = { data: { lines: [] } };
if (!parsed.data) parsed.data = { lines: [] };
if (!Array.isArray(parsed.data.lines)) parsed.data.lines = [];
// BATCH RESILIENCE: skip malformed lines (missing/blank id) so a partial-bad batch never crashes.
parsed.data.lines = parsed.data.lines.filter(l => l && l.id != null && String(l.id).trim() !== '');
return { ...base, BS_EXTRACTED_LINES: parsed };`,
    };

    @node({
        id: '34c93f5e-9b39-455a-af25-c0bd9c13f0c8',
        name: 'Switch2',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [5296, 7244],
    })
    Switch2 = {
        rules: {
            values: [
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.existing.matches.length >= 1  }}',
                                rightValue: '',
                                operator: {
                                    type: 'boolean',
                                    operation: 'true',
                                    singleValue: true,
                                },
                                id: 'cc05fc1c-164d-4582-9414-df7a1b8720c7',
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'found doc',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'cdce523d-54e5-4179-9d4c-a53ef4bb0028',
                                leftValue: '={{ $json?.error?.status == 404 || !$json?.error  }}',
                                rightValue: '0',
                                operator: {
                                    type: 'boolean',
                                    operation: 'true',
                                    singleValue: true,
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'not found',
                },
            ],
        },
        looseTypeValidation: true,
        options: {
            fallbackOutput: 'extra',
        },
    };

    @node({
        id: 'b23e08c7-2154-4e25-b863-a6d2c8930f95',
        name: 'If Exact',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [5520, 7022],
    })
    IfExact = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: '4016ce0e-5c86-44cd-b7a1-17b364c769ed',
                    leftValue: '={{ $json.existing.matches[0].LINKED_BS }}',
                    rightValue: '={{ $json.NAME }}',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                        name: 'filter.operator.equals',
                    },
                },
                {
                    id: 'f7b8d871-364d-4036-a0fc-c1adbaa43ed9',
                    leftValue: '={{ String($json.existing.matches[0].BS_LINE_AMOUNT) }}',
                    rightValue: '={{ String($json["BS_EXTRACTED_LINES.data.lines"].amount) }}',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
                {
                    id: 'dc48794d-b567-4009-8701-7867e2f05ce6',
                    leftValue: '={{ $json.existing.matches[0].BS_LINE_DATE }}',
                    rightValue: '={{ $json["BS_EXTRACTED_LINES.data.lines"].date }}',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                        name: 'filter.operator.equals',
                    },
                },
                {
                    id: '1d13cebe-e311-430f-b143-5b89c114e471',
                    leftValue: '={{ $json.existing.matches[0].BS_LINE_NOTE }}',
                    rightValue: '={{ $json["BS_EXTRACTED_LINES.data.lines"].notes }}',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                        name: 'filter.operator.equals',
                    },
                },
            ],
            combinator: 'and',
        },
        looseTypeValidation: true,
        options: {},
    };

    @node({
        id: '2f21244b-e5c0-431c-a51e-de6966a75e66',
        name: 'Loop Over Items7',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [3504, 5888],
    })
    LoopOverItems7 = {
        batchSize: 10,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: 'a556e567-bc3f-417f-997a-84ba298f10af',
        name: 'Loop Over Items10',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [3504, 7166],
    })
    LoopOverItems10 = {
        batchSize: 100,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: '12a559de-4213-4a13-b249-13ebd5014659',
        name: 'Loop Over Balance Sheets',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [3504, 6868],
    })
    LoopOverBalanceSheets = {
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: '0b11eed5-4b3f-42d4-b085-26880a1a93c5',
        name: 'End Link Document',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [5968, 7070],
    })
    EndLinkDocument = {};

    @node({
        id: 'cdcff24a-ed0f-4fdf-a9fb-61baec2e13d9',
        name: '3b. BS Action Switch1',
        type: 'n8n-nodes-base.switch',
        version: 2,
        position: [3056, 6372],
    })
    _3bBsActionSwitch1 = {
        dataType: 'string',
        value1: '={{ $json.ACTION }}',
        rules: {
            rules: [
                {
                    value2: 'update_status_missing_company',
                    outputKey: 'update_status_missing_company',
                },
                {
                    value2: 'no_action_awaiting_company_id',
                    outputKey: 'no_action_awaiting_company_id',
                },
                {
                    value2: 'restart_balance_sheet',
                    outputKey: 'restart_balance_sheet',
                },
                {
                    value2: 'extract_balance_sheet',
                    outputKey: 'extract_balance_sheet',
                },
                {
                    value2: 'update_status_extraction_failed',
                    outputKey: 'update_status_extraction_failed',
                },
                {
                    value2: 'no_action_extraction_failed',
                    outputKey: 'no_action_extraction_failed',
                },
                {
                    value2: 'link_documents',
                    outputKey: 'link_documents',
                },
                {
                    value2: 'mark_completed',
                    outputKey: 'mark_completed',
                },
                {
                    value2: 'no_action_already_completed',
                    outputKey: 'no_action_already_completed',
                },
                {
                    value2: 'no_action_unhandled_state',
                    outputKey: 'no_action_unhandled_state',
                },
                {
                    value2: '__unhandled_action__',
                    outputKey: 'Unhandled ACTION - Error',
                },
                {
                    value2: 'extract_per_type',
                    outputKey: 'extract_per_type',
                },
                {
                    value2: 'no_action_double',
                    outputKey: 'no_action_double',
                },
                {
                    value2: 'no_action_merged',
                    outputKey: 'no_action_merged',
                },
                {
                    value2: 'select_type',
                    outputKey: 'select_type',
                },
            ],
        },
        options: {
            fallbackOutput: 10,
        },
    };

    @node({
        id: '6556a921-f042-4092-855c-641190fd77b4',
        name: 'Loop Over Items16',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [3504, 6186],
    })
    LoopOverItems16 = {
        batchSize: 50,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: 'eee32500-4d46-41f3-a496-746b01454b06',
        name: 'Action: Update STATUS - MISSING_COMPANY_ID',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [3280, 5888],
    })
    ActionUpdateStatusMissingCompanyId = {};

    @node({
        id: '7de9ad5b-ff36-4e49-b715-17504503c8f8',
        name: 'Loop Over Items9',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [3504, 6484],
    })
    LoopOverItems9 = {
        batchSize: 50,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: '97e9fc03-6241-4233-9cd5-2fbcda243886',
        name: 'Action: Mark Completed BS',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [3280, 7166],
    })
    ActionMarkCompletedBs = {};

    @node({
        id: '1e0e62a2-d67f-4d72-95c3-ce75bc49d301',
        name: 'Split Lines1',
        type: 'n8n-nodes-base.splitOut',
        version: 1,
        position: [4176, 7260],
    })
    SplitLines1 = {
        fieldToSplitOut: 'BS_EXTRACTED_LINES.data.lines',
        include: 'allOtherFields',
        options: {},
    };

    @node({
        id: '49123258-0c81-44f7-9822-0b81f400e693',
        name: 'Action: Link Documents1',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [3280, 6868],
    })
    ActionLinkDocuments1 = {};

    @node({
        id: '8185ac89-cf72-4405-8d23-eb8744096600',
        name: 'Loop Over Items18',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [5744, 7118],
    })
    LoopOverItems18 = {
        batchSize: 50,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: 'bsv2trig',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [2608, 6380],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: '4ee084b8-9952-4f3f-b1ff-f3143c11983a',
        name: "Build: Call 'Incoming Document Batch Update' - STATUS MISSING_COMPANY_ID (BS)",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [3728, 5744],
    })
    BuildCallIncomingDocumentBatchUpdateStatusMissingCompanyIdBs = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: "={{ $('Action: Update STATUS - MISSING_COMPANY_ID').item.json.ID }}",
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'STATUS',
                    value: 'MISSING_COMPANY_ID',
                    type: 'string',
                },
                {
                    id: 'bw2',
                    name: 'ERROR',
                    value: '={{ $json.error || null }}',
                    type: 'string',
                },
                {
                    id: 'unlock-0003-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0008-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-tc-01-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'd8b0492d-66fa-4c0d-83a5-7b117f6fb9b2',
        name: "Build: Call 'Incoming Document Batch Update'3",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [5968, 7363],
    })
    BuildCallIncomingDocumentBatchUpdate3 = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'LINKED_BS',
                    value: '={{ $json.NAME }}',
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'BS_LINE_AMOUNT',
                    value: '={{ $json["BS_EXTRACTED_LINES.data.lines"].amount }}',
                    type: 'string',
                },
                {
                    id: 'bw2',
                    name: 'BS_LINE_DATE',
                    value: '={{ $json["BS_EXTRACTED_LINES.data.lines"].date }}',
                    type: 'string',
                },
                {
                    id: 'bw3',
                    name: 'BS_LINE_NOTE',
                    value: '={{ $json["BS_EXTRACTED_LINES.data.lines"].notes }}',
                    type: 'string',
                },
                {
                    id: 'bw4',
                    name: 'NAME',
                    value: "={{ $json.COMPANY_NAME}}-{{ String($json['BS_EXTRACTED_LINES.data.lines'].id || \"\").trim().replace(/[^a-zA-Z0-9]/g, '').slice(-5).padStart(5, '0') || '' }}",
                    type: 'string',
                },
                {
                    id: 'bw5',
                    name: 'TYPE',
                    value: 'INVOICE',
                    type: 'string',
                },
                {
                    id: 'bw6',
                    name: 'DOC_ID',
                    value: "={{ String($json['BS_EXTRACTED_LINES.data.lines'].id) }}",
                    type: 'string',
                },
                {
                    id: 'bw7',
                    name: 'COMPANY_ID',
                    value: '={{ $json.COMPANY_ID.toString() }}',
                    type: 'string',
                },
                {
                    id: 'bw13',
                    name: 'COMPANY_NAME',
                    value: '={{ $json.COMPANY_NAME || null }}',
                    type: 'string',
                },
                {
                    id: 'bw8',
                    name: 'SOURCE_TYPE',
                    value: 'BALANCE_SHEET',
                    type: 'string',
                },
                {
                    id: 'bw9',
                    name: 'SOURCE_ID',
                    value: '={{ $json.ID }}',
                    type: 'string',
                },
                {
                    id: 'bw10',
                    name: 'STATUS',
                    value: 'IN_PROGRESS',
                    type: 'string',
                },
                {
                    id: 'bw11',
                    name: 'SHORT_DOC_ID',
                    value: "={{ String($json['BS_EXTRACTED_LINES.data.lines'].id || \"\").trim().replace(/[^a-zA-Z0-9]/g, '').slice(-5).padStart(5, '0') }}",
                    type: 'string',
                },
                {
                    id: 'bw12',
                    name: 'ERROR',
                    value: '={{ $json.error || null }}',
                    type: 'string',
                },
                {
                    id: 'unlock-0000-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0005-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-tc-02-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'uc_d8b0492d-6',
        name: "Upsert: Call 'Incoming Document Batch Update'3",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [6192, 7555],
    })
    UpsertCallIncomingDocumentBatchUpdate3 = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
            cachedResultName: 'indox api',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: '45737742-09e2-4ace-83df-dfb80da37854',
        name: "Build: Call 'Incoming Document Batch Update'",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [5968, 6974],
    })
    BuildCallIncomingDocumentBatchUpdate = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: '={{ $json.existing.matches[0].ID }}',
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'LINKED_BS',
                    value: '={{ $json.NAME }}',
                    type: 'string',
                },
                {
                    id: 'bw2',
                    name: 'BS_LINE_AMOUNT',
                    value: '={{ $json["BS_EXTRACTED_LINES.data.lines"].amount }}',
                    type: 'string',
                },
                {
                    id: 'bw3',
                    name: 'BS_LINE_DATE',
                    value: '={{ $json["BS_EXTRACTED_LINES.data.lines"].date }}',
                    type: 'string',
                },
                {
                    id: 'bw4',
                    name: 'BS_LINE_NOTE',
                    value: '={{ $json["BS_EXTRACTED_LINES.data.lines"].notes }}',
                    type: 'string',
                },
                {
                    id: 'bw5',
                    name: 'ERROR',
                    value: '={{ $json.error || null }}',
                    type: 'string',
                },
                {
                    id: 'unlock-0001-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0006-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-tc-03-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'uc_45737742-0',
        name: "Upsert: Call 'Incoming Document Batch Update'",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [6192, 7363],
    })
    UpsertCallIncomingDocumentBatchUpdate = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
            cachedResultName: 'indox api',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: '8d031a7d-11ec-48a0-9843-98d926085f30',
        name: 'Build: Restart (clear completed flags)',
        /*__n8n__*/ notes: "[dynamic restart 2026-08-17, owner order] ACTION_RESTART clears EVERY *_COMPLETED flag on the row, derived from the row keys at runtime - never a hardcoded list. Values are NEVER cleared by restart (owner value+flag law): re-extraction only when BS_EXTRACTED_LINES is empty; BS_EXTRACTION_USE_CACHE=false stays so a genuine re-run extracts fresh. STATUS -> IN_PROGRESS, ERROR clears.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3728, 6042],
    })
    BuildRestartClearCompletedFlags = {
        jsCode: `// Dynamic restart: clear every *_COMPLETED key the row carries.
const out = [];
for (const item of $input.all()) {
  const j = item.json || {};
  if (j.ID == null || j.ID === '') continue;
  // ITERATION_COUNT is the step budget and ACTION_RESTART is what opens a fresh one.
  // [2026-08-20] It became a REAL counter (incremented per dispatch by indoxV2ActionRouter01 ::
  // 'Log Action Start') instead of a number derived by parsing ACTION_LOG, so the reset has to be
  // written here rather than falling out of "count the stamps after the last restart marker".
  // __instance names the SCHEMA this UPSERT lands in. This node BUILDS a new object, so anything
  // not listed is dropped and indoxApi01 falls back to public -- a restart for one instance would
  // clear another instance's row of the same ID. Document IDs are per-instance sequences.
  const o = { ID: j.ID, STATUS: 'IN_PROGRESS', ERROR: null, ITERATION_COUNT: 0, unlock: true, INLINE_ACTION: 'UPSERT', __instance: j.__instance || '' };
  for (const k of Object.keys(j)) {
    if (k.endsWith('_COMPLETED')) o[k] = false;
  }
  o.FROM_OFFICE_CHECK = false;
  o.BS_EXTRACTION_USE_CACHE = false;
  // [2026-08-20] The ACTION_LOG append that stood here went with the column. The restart's
  // own record is the dispatch row indoxV2ActionRouter01 :: 'Log Action Start' writes for
  // ACTION=restart_*, which is also what carries the restart epoch for the dup guard.
  out.push({ json: o });
}
return out;
`,
    };

    @node({
        id: '1bd62153-cfbb-4546-a41b-81da2bc874e7',
        name: "Build: Call 'Incoming Document Batch Update'2",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [3952, 7068],
    })
    BuildCallIncomingDocumentBatchUpdate2 = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: "={{ $('Start Linking Documents').item.json.ID }}",
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'BS_LINK_DOCUMENTS_COMPLETED',
                    value: '={{ true }}',
                    type: 'string',
                },
                {
                    id: 'bslink-at-0001',
                    name: 'BS_LINK_DOCUMENTS_AT',
                    value: '={{ $now.toISO() }}',
                    type: 'string',
                },
                {
                    id: 'bw2',
                    name: 'ERROR',
                    value: '={{ $json.error || null }}',
                    type: 'string',
                },
                {
                    id: 'unlock-0002-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0007-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-tc-04-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'uc_1bd62153-c',
        name: "Upsert: Call 'Incoming Document Batch Update'2",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [4176, 7068],
    })
    UpsertCallIncomingDocumentBatchUpdate2 = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
            cachedResultName: 'indox api',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
            value: {},
            matchingColumns: [],
            schema: [],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: '6c118174-f554-46f0-8820-9a579816b361',
        name: "Build: Call 'Incoming Document Batch Update' - STATUS EXTRACTION_FAILED",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [3728, 6340],
    })
    BuildCallIncomingDocumentBatchUpdateStatusExtractionFailed = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: "={{ $('Action: Update STATUS - EXTRACTION_FAILED').item.json.ID }}",
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'STATUS',
                    value: 'EXTRACTION_FAILED',
                    type: 'string',
                },
                {
                    id: 'bw2',
                    name: 'ERROR',
                    value: "={{ ($('Action: Update STATUS - EXTRACTION_FAILED').item.json.LINK && !String($('Action: Update STATUS - EXTRACTION_FAILED').item.json.LINK_CONNECTION || '').trim()) ? 'missing link connection' : ($json.error || null) }}",
                    type: 'string',
                },
                {
                    id: 'unlock-0005-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0010-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-tc-05-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'e9e3b7a4-8ade-4d62-b6fd-7f0f1a9a8759',
        name: "Build: Call 'Incoming Document Batch Update' - STATUS COMPLETED (BS)",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [3728, 7022],
    })
    BuildCallIncomingDocumentBatchUpdateStatusCompletedBs = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: '={{ $json.ID }}',
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'STATUS',
                    value: 'COMPLETED',
                    type: 'string',
                },
                {
                    id: 'bw2',
                    name: 'ERROR',
                    value: '={{ $json.error || null }}',
                    type: 'string',
                },
                {
                    id: 'unlock-0006-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0011-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-tc-06-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'v2upsertshared',
        name: 'Upsert (central)',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [3952, 6684],
    })
    UpsertCentral = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
            cachedResultName: 'indox api',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'bsgetallreq01',
        name: 'GET Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [4400, 7260],
    })
    GetReq = {
        jsCode: `// WHY this is a GET and not a GET_ALL: GET_ALL returned every row of incoming_documents and we
// matched in JS. At 45,839 rows (37MB raw, far more as JS objects, copied again at every
// executeWorkflow hop) that OOM'd the 1536MB worker on every single document — INDOX processed zero
// docs and crashed ~357x/hr. We now push the exact same lookup keys down as \`filters\` (OR of
// AND-groups) so the DB returns only rows that can possibly match. The matcher below is UNCHANGED in
// meaning: it still re-applies the full query locally, it just gets a bounded superset instead of the
// whole table.
//
// One filter group per BS line — the same {COMPANY_ID, SHORT_DOC_ID} 'Match Existing' matches on.
const lines = $input.all().map(i => i.json);
const bad = v => v === null || v === undefined || v === '';
const filters = [];
for (const ln of lines) {
  const line = ln['BS_EXTRACTED_LINES.data.lines'] || {};
  const g = {
    COMPANY_ID:   (ln.COMPANY_ID ?? '').toString(),
    SHORT_DOC_ID: (line.id ?? '').toString().replace(/[^a-zA-Z0-9]/g, '').slice(-5).padStart(5, '0'),
  };
  for (const k of Object.keys(g)) if (bad(g[k])) delete g[k];
  if (Object.keys(g).length) filters.push(g);
}
// __instance selects the SCHEMA this GET reads. Built objects drop everything not named, so
// without it the lookup runs against public and could match another instance's document.
// Read from 'When Called' (passthrough) rather than a line item, which has been rebuilt by here.
let INST = '';
try { INST = String(($('When Called').first().json || {}).__instance || ''); } catch (e) { INST = ''; }
if (!filters.length) return [{ json: { INLINE_ACTION: 'GET', filters: [{ ID: '__never__' }], __instance: INST } }];
return [{ json: { INLINE_ACTION: 'GET', filters, __instance: INST } }];
`,
    };

    @node({
        id: 'bscallgetall01',
        name: 'Call indox api (GET_ALL)',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [4624, 7260],
    })
    CallIndoxApiGetAll = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
            cachedResultName: 'indox api - supabase',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
            value: {},
            matchingColumns: [],
            schema: [],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'bsmatchexisting01',
        name: 'Match Existing',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [4848, 7260],
    })
    MatchExisting = {
        jsCode: `// Direct indox-API link search (replaces the 'Get Incoming Document' dual-backend shim).
// rows = GET_ALL result from indoxApiRouter01; queries = per-line {COMPANY_ID, SHORT_DOC_ID}
// (SHORT_DOC_ID = last-5 of the line id, exactly as the old Execute Workflow1 mapping).
// Output shape mirrors the old 'SB Match': {...matches[0], filter, matches, matchCount} — consumed
// by 'Join Search Results' as \`existing\`, zipped back onto each line by index.
// .filter(r=>r&&r.ID): a 0-row GET yields one empty placeholder item (alwaysOutputData).
const rows  = $input.all().map(i => i.json).filter(r => r && r.ID);
const lines = $('Split Lines1').all().map(i => i.json);
const bad = v => v === null || v === undefined || v === '';
const out = [];
for (const ln of lines) {
  const line = ln['BS_EXTRACTED_LINES.data.lines'] || {};
  const q = {
    COMPANY_ID:   (ln.COMPANY_ID ?? '').toString(),
    SHORT_DOC_ID: (line.id ?? '').toString().replace(/[^a-zA-Z0-9]/g, '').slice(-5).padStart(5, '0'),
  };
  const keys = Object.keys(q).filter(k => !bad(q[k]));
  // A MERGED row is a TOMBSTONE -- its document lives on the winner. Everything downstream reads
  // matches[0] and nothing else: 'If Exact' compares matches[0].LINKED_BS / BS_LINE_AMOUNT /
  // BS_LINE_DATE / BS_LINE_NOTE, and the update builds from matches[0].ID. matchCount is computed
  // and read by no node. So before this sort, a line matching both a live document and a merged
  // one linked to whichever the DB happened to return first -- and writing the tombstone means the
  // ledger line lands on a row nobody reads. Measured 2026-08-23: 480 (COMPANY_ID, SHORT_DOC_ID)
  // keys hold two or more live documents, covering 1,126 documents; the worst holds 35.
  //
  // Stable sort, MERGED last. Non-MERGED keep the DB's order among themselves, and a line whose
  // ONLY match is a tombstone still links to it rather than creating a second placeholder.
  const matches = rows
    .filter(r => keys.every(k => String(r[k]) === String(q[k])))
    .sort((a, b) => (String(a.STATUS || '') === 'MERGED' ? 1 : 0)
                  - (String(b.STATUS || '') === 'MERGED' ? 1 : 0));
  out.push({ json: { ...(matches[0] || {}), filter: q, matches, matchCount: matches.length } });
}
return out;`,
    };

    @node({
        id: 'bsdecidehead01',
        name: 'Decide BS Action',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3056, 6180],
    })
    DecideBsAction = {
        jsCode: `// __EXPORTABLE__ [owner design 2026-08-18] THE decide logic lives HERE and only here.
// Wrapped as one self-contained function so this node can EXPORT ITS OWN SOURCE:
// mode='export_decide' returns { fnSrc: __bsDecideFn.toString() } and the mega decide
// (indoxV2DecideMin01) rehydrates it with new Function('$','$execution', src)($,$execution)
// and runs it in ONE code node. Node-input accessors were replaced by the __items
// parameter; $()/$ execution references resolve in WHICHEVER context runs the function
// (router graph or mega) — $('Companies') is absent in mega by design, __CFG catches.
function __bsDecideFn(__items) {
// [resolve_double 2026-08-06] Terminal guard, mirroring 'Decide DOC BASE Action'.
// Unreachable through indoxV2Driver01 (Switch1 routes no_action_* on output 0 ahead of
// every type output), but all three per-type routers expose their own \`When Called\`
// trigger, so a direct call would otherwise act on a tombstone.
//   MERGED  -> ALWAYS inert. A merged loser is a tombstone; its document lives on the winner.
//   DOUBLE  -> NOT decided here. [2026-08-23, owner order] This guard used to read
//              DOUBLE_LINE_CONTEXT.merge_sig and return no_action_double when it was stamped.
//              merge_sig was retired on 2026-08-23 (the in-memory detector's gate went with it),
//              but this second read survived in all three lane guards and still looked
//              authoritative. Doubles are decided in ONE place -- indoxV2Decide01, from the
//              driver's SQL detector -- and Decide01 already returns no_action_double itself, so
//              the lane keeps its route. MERGED is the only terminal signal a lane guard needs.
function __terminalGuard(doc) {
  if (String(doc.STATUS || '') === 'MERGED') return 'no_action_merged';
  return null;
}

// [v2.1] router_bs — DECIDE mode. Returns this doc's next BS ACTION (no execution).
// Called by indox-v2 Decide (unlocked decide phase). Execution is a separate call.
// [dead branch removed 2026-08-27] A "docType === 'gdoc'" arm lived here listing the invoice
// lane's required fields. It was unreachable: the function's ONE caller passes the literal
// 'bs_doc'. It surfaced during the gdoc->invoice class rename, where it read as a live consumer
// of the old class name and was not one. Removed rather than renamed — a branch nothing can
// enter is a trap, not a record.
function hasAllRequiredFields(doc, docType) {
  if (docType === 'bs_doc') {
    return !!(doc.BS_EXTRACTED_LINES &&
              String(doc.BS_EXTRACTION_VERIFIED == null ? '' : doc.BS_EXTRACTION_VERIFIED).trim().toLowerCase() === 'true' &&
              String(doc.BS_LINK_DOCUMENTS_COMPLETED == null ? '' : doc.BS_LINK_DOCUMENTS_COMPLETED).trim().toLowerCase() === 'true');
  }
  return false;
}

function bsDecide(doc) {
  // [2026-08-23] RESTART IS A HEAD DECISION -- hoisted above the COMPANY_ID gate to match
  // gdocHead/shipHead, which both open with exactly this check. It has to move together with
  // the docBaseDecide change that finally routes a typed restart here: until now every
  // ACTION_RESTART was answered by 'restart_base' before this function ran, so a balance sheet
  // with no COMPANY_ID still got restarted. Left below the gate, that doc would have started
  // returning 'update_status_missing_company' instead -- the routing fix would have taken the
  // operator's Retry away from precisely the documents most likely to need it.
  if (doc.STATUS === 'ACTION_RESTART')
    return 'restart_balance_sheet';

  if (!doc.COMPANY_ID) {
    return doc.STATUS !== 'MISSING_COMPANY_ID'
      ? 'update_status_missing_company'
      : 'no_action_awaiting_company_id';
  }

  // TypeDocEx01(bs) runs early, filling DOC_DATE/TOTAL_AMOUNT (the two
  // summary scalars) via local+AI in parallel, gated on a real flag.
  //
  // [guard 2026-08-07] Do NOT fire on a doc whose BS extraction is already
  // verified or already COMPLETED. Before this guard, the API_TOOLS_ID check
  // ran unconditionally ahead of every downstream state check, so any
  // pre-existing COMPLETED balance sheet (verified TOTAL_AMOUNT from a real
  // line-item sum) that simply predates PER_TYPE_EXTRACTION_COMPLETED would
  // be re-run through the two-point scalar guess and have its verified
  // TOTAL_AMOUNT silently overwritten -- confirmed on doc
  // 17711145495219ioglt: totalsMatch=true, 38 lines summing to 218031,
  // clobbered to 200855 on 2026-08-06 while STATUS stayed COMPLETED
  // throughout. 134/136 COMPLETED BS docs were still exposed to this at
  // measurement time. In-flight docs (BS_EXTRACTION_VERIFIED not yet true
  // AND STATUS !== 'COMPLETED') are unaffected -- this guard only ever
  // subtracts a firing, never adds one.
  // [drive-connection guard 2026-08-13] NO FETCHABLE FILE, NO EXTRACTION POINT.
  // indoxV2ExtractBalanceSheet01/'Download LINK' sends { fileId: LINK, connection_id: LINK_CONNECTION }.
  // drive api no longer accepts an implicit default connection for automation calls, so a row with a
  // LINK and a blank LINK_CONNECTION fails EVERY time. Measured: all current drive api failures trace
  // to just 3 fileIds, whose documents carry LINK_CONNECTION AND CONNECTION blank in the table -- they
  // were written during the Companies Loader timeout window (06:03-06:13). One is RETRY_COUNT=18 and
  // STATUS=MAX_ITERATIONS and was still being dispatched. That is 306 drive api errors an hour from 3 rows.
  // [value+flag gate 2026-08-17, owner order] BS's sentinel VALUE is BS_EXTRACTED_LINES:
  // lines present = extraction produced, never re-runs on restart. Only null/empty lines +
  // cleared flag re-enter. Manual re-extraction = blank BS_EXTRACTED_LINES + ACTION_RESTART.
  if (doc.STATUS !== 'COMPLETED' && doc.API_TOOLS_ID && !doc.BS_EXTRACTED_LINES &&
      String(doc.PER_TYPE_EXTRACTION_COMPLETED == null ? '' : doc.PER_TYPE_EXTRACTION_COMPLETED).trim().toLowerCase() !== 'true' && (doc.LINK && String(doc.LINK_CONNECTION || '').trim() !== ''))
    return 'extract_per_type';

  if (!doc.BS_EXTRACTED_LINES) {
    // [two-point enforcement 2026-08-12] ROUTED THROUGH pt2, NOT STRAIGHT TO THE AI EXTRACTOR.
    // This branch used to return 'extract_balance_sheet', whose action chain called
    // indoxV2ExtractBalanceSheet01 DIRECTLY -- a second BS AI extraction point outside
    // BsDocEx01. Measured before this change: BS AI extractor 63 runs vs BsDocEx01 55 in 3h
    // (ratio 1.14), and 31 documents reached EXTRACTION_FAILED having run the AI extractor
    // twice -- once inside pt2, then again here purely to close the gate.
    // 'extract_per_type' reaches the same extractor through BsDocEx01, which additionally
    // runs the local JQ leg and the AI/local selection. Inputs are identical (LINK +
    // use_cache), so nothing is lost. The gate is now closed by 'Select Per Type Values (BS)'
    // whenever the AI leg actually ran, which is what makes this terminate in ONE pass.
    // [drive-connection guard 2026-08-13] THIS GATE IS A CLOSED LOOP WITHOUT A FETCHABLE FILE:
    // extraction fails -> BS_EXTRACTED_LINES never lands -> the gate re-fires on the next sweep, forever.
    if (doc.STATUS !== 'EXTRACTION_FAILED')     return 'update_status_extraction_failed';
    return 'no_action_extraction_failed';
  }

  if (String(doc.BS_EXTRACTION_VERIFIED == null ? '' : doc.BS_EXTRACTION_VERIFIED).trim().toLowerCase() !== 'true')
    return doc.STATUS !== 'EXTRACTION_FAILED'
      ? 'update_status_extraction_failed'
      : 'no_action_extraction_failed';

  // LINK ONCE. [2026-08-23, owner order] This gate briefly minted a new action name per re-link
  // round (link_documents_r1, _r2 ...) plus a BS_LINK_ROUND column, a nine-round bound and a
  // no_action_bs_link_exhausted terminal -- all of it only to get a repeat past
  // 'Dup Guard: Double Action'. The round number routed nothing: the switch stripped it again on
  // the very next node. Measured before removal: max round ever reached = 1, the bound never
  // fired once, and of 551 link_documents_r1 dispatches only 121 recorded a round -- the other
  // 430 re-emitted the SAME name, and the guard is stop-and-error, so each one discarded a whole
  // driver batch.
  //
  // Linking opens the links. It runs once and latches. A document that turns up after its balance
  // sheet was linked is a DUPLICATE, and duplicates belong to the merge -- not to a re-linking
  // loop that re-reads the ledger looking for it.
  //
  // The string compare is deliberate: BS_LINK_DOCUMENTS_COMPLETED is TEXT and the JS string
  // 'false' is truthy, so the pre-C10 form (!doc.BS_LINK_DOCUMENTS_COMPLETED) read every
  // explicitly-unlinked row as already linked.
  if (String(doc.BS_LINK_DOCUMENTS_COMPLETED == null ? '' : doc.BS_LINK_DOCUMENTS_COMPLETED).trim().toLowerCase() !== 'true')
    return 'link_documents';

  // [selection 2026-08-25, owner order] A BALANCE SHEET GETS THE SAME SELECTOR AS EVERY OTHER TYPE.
  // Its own date and total were decided inside the extractor with a reversed, AI-led tie-break;
  // that rule is preserved (SelectType01 branches on TYPE) but it now lives in one place with
  // every other type's, so a change to how a value is chosen is a change in one file.
  // Selected BEFORE mark_completed, the same order the fixture oracles specify for gdoc/shipment.
  // FAIL-SAFE: the hash arm needs BOTH hashes, so rows selected before this column existed are
  // picked up by a deliberate dispatch rather than a wave.
  {
    var _stDone = String(doc.SELECTION_COMPLETED == null ? '' : doc.SELECTION_COMPLETED)
                    .trim().toLowerCase() === 'true';
    var _stLive = doc.__selection_hash, _stStored = doc.SELECTION_VALUES_HASH;
    var _stChanged = !!_stLive && !!_stStored && String(_stLive) !== String(_stStored);
    // NO EXTRACTION-FLAG PRECONDITION. This gate used to require PER_TYPE_EXTRACTION_COMPLETED,
    // which is exactly the flag ACTION_RESTART clears -- so a restarted document skipped selection
    // entirely and went straight to priority and mark_completed with whatever finals it happened to
    // be carrying. Reproduced end-to-end on 2026-08-25 with three real documents.
    // Ordering already guarantees extraction goes first when it is owed.
    if (_stChanged || (!_stDone && doc.STATUS !== 'COMPLETED')) return 'select_type';
  }

  if (doc.STATUS !== 'COMPLETED' && hasAllRequiredFields(doc, 'bs_doc'))
    return 'mark_completed';

  if (doc.STATUS === 'COMPLETED')
    return 'no_action_already_completed';

  return 'no_action_unhandled_state';
}

return __items.map(item => {
  const d = item.json;
  for (const k of Object.keys(d)) {            // supabase TEXT-boolean safety
    if (typeof d[k] === 'string') {
      const s = d[k].trim().toLowerCase();
      if (s === 'true') d[k] = true; else if (s === 'false') d[k] = false;
    }
  }
  d.ACTION = __terminalGuard(d) || bsDecide(d);
  d.DOC_TYPE = 'bs_doc';
  delete d.mode;   // clean handoff so the execute call doesn't re-route to decide
  return item;
});

}
const __mode = String((($input.first()||{}).json||{}).mode || '');
if (__mode === 'export_decide') return [{ json: { fnSrc: __bsDecideFn.toString() } }];
return __bsDecideFn($input.all());`,
    };

    @node({
        id: 'bsroutemode01',
        name: 'Route Mode',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [2832, 6380],
    })
    RouteMode = {
        rules: {
            values: [
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.mode }}',
                                rightValue: 'decide',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                            {
                                leftValue: '={{ $json.mode }}',
                                rightValue: 'export_decide',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'or',
                    },
                    renameOutput: true,
                    outputKey: 'decide',
                },
            ],
        },
        options: {
            fallbackOutput: 'extra',
        },
    };

    @node({
        id: '1675efd6-1da6-419b-b97e-da92ea8ba7ff',
        name: 'Stop and Error - Unhandled BS ACTION',
        type: 'n8n-nodes-base.stopAndError',
        version: 1,
        position: [3280, 6676],
    })
    StopAndErrorUnhandledBsAction = {
        errorMessage:
            "=Unhandled ACTION '{{ $json.ACTION }}' in indoxV2ActionsBS01 — '3b. BS Action Switch1' matched no case and no explicit fallback. Document ID: {{ $json.ID }}. This item would otherwise have been silently dropped (G41).",
    };

    @node({
        id: 'extract-per-type-bs-entry-01',
        name: 'Action: Extract Per Type (BS)',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [3280, 7464],
    })
    ActionExtractPerTypeBs = {};

    @node({
        id: 'call-typedocex01-bs-01',
        name: 'Call BsDocEx01',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [3504, 7464],
        onError: 'continueRegularOutput',
    })
    CallBsdocex01 = {
        workflowId: {
            __rl: true,
            value: 'BsDocEx01',
            mode: 'list',
            cachedResultUrl: '/workflow/BsDocEx01',
            cachedResultName: 'Balance Sheet Document Extraction (AI-led, local supplements)',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                ID: '={{ $json.ID }}',
                API_TOOLS_ID: '={{ $json.API_TOOLS_ID || $json.HASH }}',
                LINK: '={{ $json.LINK }}',
                LINK_CONNECTION: '={{ $json.LINK_CONNECTION }}',
                __instance: '={{ $json.__instance || "" }}',
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
        id: 'build-pertype-upsert-bs-01',
        name: 'Build Per Type Upsert (BS)',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [3728, 7464],
    })
    BuildPerTypeUpsertBs = {
        assignments: {
            assignments: [
                {
                    id: 'inst-per-type-bs',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
                {
                    id: 'ptc2',
                    name: 'BS_EXTRACTED_LINES',
                    value: "={{ $json.BS_EXTRACTED_LINES || $('Action: Extract Per Type (BS)').item.json.BS_EXTRACTED_LINES || null }}",
                    type: 'string',
                },
                {
                    id: 'ptc3',
                    name: 'BS_EXTRACTION_VERIFIED',
                    value: "={{ $json.BS_EXTRACTION_VERIFIED || $('Action: Extract Per Type (BS)').item.json.BS_EXTRACTION_VERIFIED || null }}",
                    type: 'string',
                },
                {
                    id: 'unlock-0007-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0012-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
            ],
        },
        includeOtherFields: true,
        options: {},
    };

    @node({
        id: 'seltype-action-01',
        name: 'Action: Select Type',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [3280, 7800],
    })
    ActionSelectType = {};

    @node({
        id: 'seltype-loop-01',
        name: 'Loop (select type)',
        /*__n8n__*/ notes: "batchSize 200: selection is pure computation over columns already on the row, so unlike extraction there is no per-document cost to walk one at a time for. The reset expression is the standard guard against a finished batcher sending a fresh feed straight to Done.",
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [3504, 7800],
    })
    LoopSelectType = {
        batchSize: 200,
        options: {
            reset: '={{ $prevNode.name === "Action: Select Type" }}',
        },
    };

    @node({
        id: 'seltype-call-01',
        name: 'Call SelectType01',
        /*__n8n__*/ notes: "One implementation, every caller: this action, the Shipment and BS routers, fullDocEx01 and the parity harness all run the SAME workflow. A second copy would drift, and drift in a selector means two different answers about the same document.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [3728, 7656],
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
            value: {},
            matchingColumns: [],
            schema: [],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'seltype-build-01',
        name: 'Build Select Type Upsert',
        /*__n8n__*/ notes: "The selector's answer as-is, plus the two control keys the API strips. Fields it declined to decide are absent, and indoxApi01's clean() drops absent keys, so 'no answer' leaves the column untouched rather than blanking it.",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [3952, 7800],
    })
    BuildSelectTypeUpsert = {
        assignments: {
            assignments: [
                {
                    id: 'inst-select-type-bs',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
                {
                    id: 'stu1',
                    name: 'unlock',
                    value: '={{ true }}',
                    type: 'boolean',
                },
                {
                    id: 'stu2',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
            ],
        },
        includeOtherFields: true,
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenCalled.out(0).to(this.RouteMode.in(0));
        this.LoopOverItems19.out(0).to(this.EndLinkDocument.in(0));
        this.LoopOverItems19.out(1).to(this.LoopOverItems19.in(0));
        this.LoopOverItems19.out(1).to(this.BuildCallIncomingDocumentBatchUpdate3.in(0));
        this.ActionRestartBs.out(0).to(this.LoopOverItems16.in(0));
        this.SkipUpdateDocument.out(0).to(this.EndLinkDocument.in(0));
        this.ActionUpdateStatusExtractionFailed.out(0).to(this.LoopOverItems9.in(0));
        this.StartLinkingDocuments.out(0).to(this.BuildCallIncomingDocumentBatchUpdate2.in(0));
        this.StartLinkingDocuments.out(0).to(this.PrepareSplit.in(0));
        this.JoinSearchResults.out(0).to(this.Switch2.in(0));
        this.PrepareSplit.out(0).to(this.SplitLines1.in(0));
        this.Switch2.out(0).to(this.IfExact.in(0));
        this.Switch2.out(1).to(this.LoopOverItems19.in(0));
        this.IfExact.out(0).to(this.SkipUpdateDocument.in(0));
        this.IfExact.out(1).to(this.LoopOverItems18.in(0));
        this.LoopOverItems7.out(1).to(this.BuildCallIncomingDocumentBatchUpdateStatusMissingCompanyIdBs.in(0));
        this.LoopOverItems7.out(1).to(this.LoopOverItems7.in(0));
        this.LoopOverItems10.out(1).to(this.BuildCallIncomingDocumentBatchUpdateStatusCompletedBs.in(0));
        this.LoopOverItems10.out(1).to(this.LoopOverItems10.in(0));
        this.LoopOverBalanceSheets.out(1).to(this.StartLinkingDocuments.in(0));
        this.LoopOverBalanceSheets.out(1).to(this.LoopOverBalanceSheets.in(0));
        this.EndLinkDocument.out(0).to(this.Aggregate.in(0));
        this._3bBsActionSwitch1.out(0).to(this.ActionUpdateStatusMissingCompanyId.in(0));
        this._3bBsActionSwitch1.out(2).to(this.ActionRestartBs.in(0));
        this._3bBsActionSwitch1.out(3).to(this.ActionExtractPerTypeBs.in(0));
        this._3bBsActionSwitch1.out(4).to(this.ActionUpdateStatusExtractionFailed.in(0));
        this._3bBsActionSwitch1.out(6).to(this.ActionLinkDocuments1.in(0));
        this._3bBsActionSwitch1.out(7).to(this.ActionMarkCompletedBs.in(0));
        this._3bBsActionSwitch1.out(10).to(this.StopAndErrorUnhandledBsAction.in(0));
        this._3bBsActionSwitch1.out(11).to(this.ActionExtractPerTypeBs.in(0));
        this._3bBsActionSwitch1.out(14).to(this.ActionSelectType.in(0));
        this.ActionSelectType.out(0).to(this.LoopSelectType.in(0));
        this.LoopSelectType.out(1).to(this.CallSelecttype01.in(0));
        this.LoopSelectType.out(1).to(this.LoopSelectType.in(0));
        this.CallSelecttype01.out(0).to(this.BuildSelectTypeUpsert.in(0));
        this.BuildSelectTypeUpsert.out(0).to(this.UpsertCentral.in(0));
        this.LoopOverItems16.out(1).to(this.BuildRestartClearCompletedFlags.in(0));
        this.LoopOverItems16.out(1).to(this.LoopOverItems16.in(0));
        this.ActionUpdateStatusMissingCompanyId.out(0).to(this.LoopOverItems7.in(0));
        this.LoopOverItems9.out(1).to(this.BuildCallIncomingDocumentBatchUpdateStatusExtractionFailed.in(0));
        this.LoopOverItems9.out(1).to(this.LoopOverItems9.in(0));
        this.ActionMarkCompletedBs.out(0).to(this.LoopOverItems10.in(0));
        this.SplitLines1.out(0).to(this.GetReq.in(0));
        this.ActionLinkDocuments1.out(0).to(this.LoopOverBalanceSheets.in(0));
        this.LoopOverItems18.out(0).to(this.EndLinkDocument.in(0));
        this.LoopOverItems18.out(1).to(this.LoopOverItems18.in(0));
        this.LoopOverItems18.out(1).to(this.BuildCallIncomingDocumentBatchUpdate.in(0));
        this.BuildCallIncomingDocumentBatchUpdateStatusMissingCompanyIdBs.out(0).to(this.UpsertCentral.in(0));
        this.BuildCallIncomingDocumentBatchUpdate3.out(0).to(this.UpsertCallIncomingDocumentBatchUpdate3.in(0));
        this.BuildCallIncomingDocumentBatchUpdate.out(0).to(this.UpsertCallIncomingDocumentBatchUpdate.in(0));
        this.BuildRestartClearCompletedFlags.out(0).to(this.UpsertCentral.in(0));
        this.BuildCallIncomingDocumentBatchUpdate2.out(0).to(this.UpsertCallIncomingDocumentBatchUpdate2.in(0));
        this.BuildCallIncomingDocumentBatchUpdateStatusExtractionFailed.out(0).to(this.UpsertCentral.in(0));
        this.BuildCallIncomingDocumentBatchUpdateStatusCompletedBs.out(0).to(this.UpsertCentral.in(0));
        this.CallIndoxApiGetAll.out(0).to(this.MatchExisting.in(0));
        this.MatchExisting.out(0).to(this.JoinSearchResults.in(0));
        this.RouteMode.out(0).to(this.DecideBsAction.in(0));
        this.RouteMode.out(1).to(this._3bBsActionSwitch1.in(0));
        this.GetReq.out(0).to(this.CallIndoxApiGetAll.in(0));
        this.ActionExtractPerTypeBs.out(0).to(this.CallBsdocex01.in(0));
        this.BuildPerTypeUpsertBs.out(0).to(this.UpsertCentral.in(0));
        this.CallBsdocex01.out(0).to(this.BuildPerTypeUpsertBs.in(0));
    }
}
