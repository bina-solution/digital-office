import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox-v2 Actions — Shipment
// Nodes   : 58  |  Connections: 80
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// LoopOverItems15                    splitInBatches
// LoopOverItems11                    splitInBatches
// LoopOverItems6                     splitInBatches
// ActionMarkCompleted                noOp
// ActionGetShortDocId1               noOp
// MapRequest                         set
// _3aGdocActionSwitch1               switch
// ActionRestartGdoc                  noOp
// ActionUpdateStatusMissingLink      noOp
// ActionUpdateName                   noOp
// ActionFindLinkInDrive              noOp
// LoopOverItems35                    splitInBatches
// ActionRestartPrioritySync          noOp
// BuildBatchUpdateRestartPrioritySync set
// ActionPrioritySync                 noOp
// LoopOverItems5                     splitInBatches
// LoopOverItems30                    splitInBatches
// LoopOverItems1                     splitInBatches
// CallSearchFile                     executeWorkflow
// ActionUpdateDocId                  noOp
// PostPriorityTable                  httpRequest                [onError→regular] [creds]
// RestoreDocsFromOffice              code
// ActionUpdateStatusApiToolsIdFailed noOp
// LoopOverItems                      splitInBatches
// LoopOverItems2                     splitInBatches
// GetWarehouseSetting                executeWorkflow            [onError→regular] [alwaysOutput]
// ActionCheckFromOffice1             noOp
// WhReqSettings                      code
// IfFoundFile1                       if
// CallSearchFromWaerhouse            executeWorkflow            [alwaysOutput]
// WhenCalled                         executeWorkflowTrigger
// BuildCallIncomingDocumentBatchUpdateStatusMissingLink set
// BuildCallIncomingDocumentBatchUpdateSearchInDriveCompleted set
// BuildBatchUpdatePrioritySync       set
// BuildCallIncomingDocumentBatchUpdateStatusCompleted set
// BuildUpdateName                    set
// BuildCallIncomingDocumentBatchUpdateStatusApiToolsFailed1 set
// BuildRestartClearCompletedFlags    code
// BuildCallIncomingDocumentBatchUpdate4 set
// BuildCallIncomingDocumentBatchUpdate1 set
// BuildCallIncomingDocumentBatchUpdateFromOffice set
// BuildCallIncomingDocumentBatchUpdateLinkFound set
// UpsertCentral                      executeWorkflow
// DecideShipmentAction               code
// RouteMode                          switch
// StopAndErrorUnhandledAction        stopAndError
// ActionExtractPerType               noOp
// UpsertCentralPerType               executeWorkflow
// CallShipmentdocex01                executeWorkflow            [onError→regular]
// BuildPerTypeUpsert                 set
// BuildDriveRenameUpdateName         code
// DriveRenameUpdateName              executeWorkflow            [onError→regular] [alwaysOutput] [retry]
// DedupeDocsExecute                  code
// ActionSelectType                   noOp
// LoopSelectType                     splitInBatches
// CallSelecttype01                   executeWorkflow            [onError→regular]
// BuildSelectTypeUpsert              set
// LoopOverItems20                    splitInBatches
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → RouteMode
//      → DecideShipmentAction
//     .out(1) → DedupeDocsExecute
//        → _3aGdocActionSwitch1
//          → ActionUpdateName
//            → LoopOverItems15
//             .out(1) → BuildUpdateName
//                → UpsertCentral
//             .out(1) → BuildDriveRenameUpdateName
//                → DriveRenameUpdateName
//             .out(1) → LoopOverItems15 (↩ loop)
//         .out(1) → ActionRestartGdoc
//            → LoopOverItems11
//             .out(1) → BuildRestartClearCompletedFlags
//                → UpsertCentral (↩ loop)
//             .out(1) → LoopOverItems11 (↩ loop)
//         .out(4) → ActionGetShortDocId1
//            → LoopOverItems5
//             .out(1) → BuildCallIncomingDocumentBatchUpdate1
//                → UpsertCentral (↩ loop)
//             .out(1) → LoopOverItems5 (↩ loop)
//         .out(5) → ActionFindLinkInDrive
//            → LoopOverItems2
//             .out(1) → CallSearchFile
//                → IfFoundFile1
//                  → BuildCallIncomingDocumentBatchUpdateLinkFound
//                    → UpsertCentral (↩ loop)
//                 .out(1) → BuildCallIncomingDocumentBatchUpdateSearchInDriveCompleted
//                    → UpsertCentral (↩ loop)
//             .out(1) → LoopOverItems2 (↩ loop)
//         .out(6) → ActionUpdateStatusMissingLink
//            → LoopOverItems
//             .out(1) → BuildCallIncomingDocumentBatchUpdateStatusMissingLink
//                → UpsertCentral (↩ loop)
//             .out(1) → LoopOverItems (↩ loop)
//         .out(9) → ActionUpdateStatusApiToolsIdFailed
//            → LoopOverItems20
//             .out(1) → BuildCallIncomingDocumentBatchUpdateStatusApiToolsFailed1
//                → UpsertCentral (↩ loop)
//             .out(1) → LoopOverItems20 (↩ loop)
//         .out(11) → ActionCheckFromOffice1
//            → WhReqSettings
//              → GetWarehouseSetting
//                → RestoreDocsFromOffice
//                  → LoopOverItems1
//                   .out(1) → CallSearchFromWaerhouse
//                      → BuildCallIncomingDocumentBatchUpdateFromOffice
//                        → UpsertCentral (↩ loop)
//                   .out(1) → LoopOverItems1 (↩ loop)
//         .out(18) → ActionPrioritySync
//            → LoopOverItems30
//             .out(1) → LoopOverItems30 (↩ loop)
//             .out(1) → MapRequest
//                → PostPriorityTable
//                  → BuildBatchUpdatePrioritySync
//                    → UpsertCentral (↩ loop)
//         .out(20) → ActionRestartPrioritySync
//            → BuildBatchUpdateRestartPrioritySync
//              → UpsertCentral (↩ loop)
//         .out(21) → ActionMarkCompleted
//            → LoopOverItems6
//             .out(1) → BuildCallIncomingDocumentBatchUpdateStatusCompleted
//                → UpsertCentral (↩ loop)
//             .out(1) → LoopOverItems6 (↩ loop)
//         .out(22) → ActionUpdateDocId
//            → LoopOverItems35
//             .out(1) → BuildCallIncomingDocumentBatchUpdate4
//                → UpsertCentral (↩ loop)
//             .out(1) → LoopOverItems35 (↩ loop)
//         .out(24) → StopAndErrorUnhandledAction
//         .out(25) → ActionExtractPerType
//            → CallShipmentdocex01
//              → BuildPerTypeUpsert
//                → UpsertCentralPerType
//         .out(28) → ActionSelectType
//            → LoopSelectType
//             .out(1) → CallSelecttype01
//                → BuildSelectTypeUpsert
//                  → UpsertCentral (↩ loop)
//             .out(1) → LoopSelectType (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"Route Mode","type":"main","index":0}]]},"Loop Over Items15":{"main":[[],[{"node":"Build: Update NAME","type":"main","index":0},{"node":"Build Drive Rename (update_name)","type":"main","index":0},{"node":"Loop Over Items15","type":"main","index":0}]]},"Loop Over Items11":{"main":[[],[{"node":"Build: Restart (clear completed flags)","type":"main","index":0},{"node":"Loop Over Items11","type":"main","index":0}]]},"Loop Over Items6":{"main":[[],[{"node":"Build: Call 'Incoming Document Batch Update' - STATUS COMPLETED","type":"main","index":0},{"node":"Loop Over Items6","type":"main","index":0}]]},"Action: Mark Completed":{"main":[[{"node":"Loop Over Items6","type":"main","index":0}]]},"Action: Get Short Doc ID1":{"main":[[{"node":"Loop Over Items5","type":"main","index":0}]]},"Map Request":{"main":[[{"node":"Post Priority Table","type":"main","index":0}]]},"3a. GDOC Action Switch1":{"main":[[{"node":"Action: Update NAME","type":"main","index":0}],[{"node":"Action: Restart GDOC","type":"main","index":0}],[],[],[{"node":"Action: Get Short Doc ID1","type":"main","index":0}],[{"node":"Action: Find Link in Drive","type":"main","index":0}],[{"node":"Action: Update Status MISSING_LINK","type":"main","index":0}],[],[],[{"node":"Action: Update STATUS - API_TOOLS_ID_FAILED","type":"main","index":0}],[],[{"node":"Action: Check From Office1","type":"main","index":0}],[],[],[],[],[],[],[{"node":"Action: priority_sync","type":"main","index":0}],[],[{"node":"Action: restart priority_sync","type":"main","index":0}],[{"node":"Action: Mark Completed","type":"main","index":0}],[{"node":"Action: update DOC_ID","type":"main","index":0}],[],[{"node":"Stop and Error - Unhandled ACTION","type":"main","index":0}],[{"node":"Action: Extract Per Type","type":"main","index":0}],[],[],[{"node":"Action: Select Type","type":"main","index":0}]]},"Action: Select Type":{"main":[[{"node":"Loop (select type)","type":"main","index":0}]]},"Loop (select type)":{"main":[[],[{"node":"Call SelectType01","type":"main","index":0},{"node":"Loop (select type)","type":"main","index":0}]]},"Call SelectType01":{"main":[[{"node":"Build Select Type Upsert","type":"main","index":0}]]},"Build Select Type Upsert":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Action: Restart GDOC":{"main":[[{"node":"Loop Over Items11","type":"main","index":0}]]},"Action: Update Status MISSING_LINK":{"main":[[{"node":"Loop Over Items","type":"main","index":0}]]},"Action: Update NAME":{"main":[[{"node":"Loop Over Items15","type":"main","index":0}]]},"Action: Find Link in Drive":{"main":[[{"node":"Loop Over Items2","type":"main","index":0}]]},"Loop Over Items35":{"main":[[],[{"node":"Build: Call 'Incoming Document Batch Update'4","type":"main","index":0},{"node":"Loop Over Items35","type":"main","index":0}]]},"Action: priority_sync":{"main":[[{"node":"Loop Over Items30","type":"main","index":0}]]},"Loop Over Items5":{"main":[[],[{"node":"Build: Call 'Incoming Document Batch Update'1","type":"main","index":0},{"node":"Loop Over Items5","type":"main","index":0}]]},"Loop Over Items30":{"main":[[],[{"node":"Loop Over Items30","type":"main","index":0},{"node":"Map Request","type":"main","index":0}]]},"Loop Over Items1":{"main":[[],[{"node":"Call Search From Waerhouse","type":"main","index":0},{"node":"Loop Over Items1","type":"main","index":0}]]},"Call Search File":{"main":[[{"node":"If Found File1","type":"main","index":0}]]},"Action: update DOC_ID":{"main":[[{"node":"Loop Over Items35","type":"main","index":0}]]},"Post Priority Table":{"main":[[{"node":"Build: Batch Update - priority_sync","type":"main","index":0}]]},"Restore Docs (From Office)":{"main":[[{"node":"Loop Over Items1","type":"main","index":0}]]},"Action: Update STATUS - API_TOOLS_ID_FAILED":{"main":[[{"node":"Loop Over Items20","type":"main","index":0}]]},"Loop Over Items":{"main":[[],[{"node":"Build: Call 'Incoming Document Batch Update' - STATUS MISSING_LINK","type":"main","index":0},{"node":"Loop Over Items","type":"main","index":0}]]},"Loop Over Items2":{"main":[[],[{"node":"Call Search File","type":"main","index":0},{"node":"Loop Over Items2","type":"main","index":0}]]},"Loop Over Items20":{"main":[[],[{"node":"Build: Call 'Incoming Document Batch Update' - STATUS API_TOOLS_FAILED1","type":"main","index":0},{"node":"Loop Over Items20","type":"main","index":0}]]},"Get Warehouse Setting":{"main":[[{"node":"Restore Docs (From Office)","type":"main","index":0}]]},"Action: Check From Office1":{"main":[[{"node":"WH Req (settings)","type":"main","index":0}]]},"WH Req (settings)":{"main":[[{"node":"Get Warehouse Setting","type":"main","index":0}]]},"If Found File1":{"main":[[{"node":"Build: Call 'Incoming Document Batch Update' - LINK FOUND","type":"main","index":0}],[{"node":"Build: Call 'Incoming Document Batch Update' - SEARCH_IN_DRIVE_COMPLETED","type":"main","index":0}]]},"Call Search From Waerhouse":{"main":[[{"node":"Build: Call 'Incoming Document Batch Update' - FROM_OFFICE","type":"main","index":0}]]},"Build: Call 'Incoming Document Batch Update' - STATUS MISSING_LINK":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Call 'Incoming Document Batch Update' - SEARCH_IN_DRIVE_COMPLETED":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Batch Update - priority_sync":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Call 'Incoming Document Batch Update' - STATUS COMPLETED":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Update NAME":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Call 'Incoming Document Batch Update' - STATUS API_TOOLS_FAILED1":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Restart (clear completed flags)":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Call 'Incoming Document Batch Update'4":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Call 'Incoming Document Batch Update'1":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Call 'Incoming Document Batch Update' - FROM_OFFICE":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Call 'Incoming Document Batch Update' - LINK FOUND":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Route Mode":{"main":[[{"node":"Decide Shipment Action","type":"main","index":0}],[{"node":"Dedupe Docs (execute)","type":"main","index":0}]]},"Action: Extract Per Type":{"main":[[{"node":"Call ShipmentDocEx01","type":"main","index":0}]]},"Build Per Type Upsert":{"main":[[{"node":"Upsert (central) - Per Type","type":"main","index":0}]]},"Call ShipmentDocEx01":{"main":[[{"node":"Build Per Type Upsert","type":"main","index":0}]]},"Build Drive Rename (update_name)":{"main":[[{"node":"Drive Rename (update_name)","type":"main","index":0}]]},"Dedupe Docs (execute)":{"main":[[{"node":"3a. GDOC Action Switch1","type":"main","index":0}]]},"Action: restart priority_sync":{"main":[[{"node":"Build: Batch Update - restart priority_sync","type":"main","index":0}]]},"Build: Batch Update - restart priority_sync":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"b481a46d-6a18-4fdc-9eb5-c2d8ed3a639a","name":"role:action"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {"templateCredsSetupCompleted":true},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"indoxV2ActionsShip01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2ActionsShip01',
    name: 'indox-v2 Actions — Shipment',
    active: true,
    isArchived: false,
    tags: ['app:indox', 'role:action', 'indox-app'],
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
export class IndoxV2ActionsShipmentWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: '70753d80-571a-4e3b-9dd1-6cc8b3ac7a38',
        name: 'Loop Over Items15',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [4624, 4416],
    })
    LoopOverItems15 = {
        batchSize: 150,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: '720fb8ca-7abd-4cd0-ab80-c1ec3c518121',
        name: 'Loop Over Items11',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [4624, 4768],
    })
    LoopOverItems11 = {
        batchSize: 30,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: '1fdeefb1-41bc-431c-b4ff-336d854b20c1',
        name: 'Loop Over Items6',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [4624, 8000],
    })
    LoopOverItems6 = {
        batchSize: 100,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: '3e25f50d-9a43-44a9-891a-9cebdb632e6b',
        name: 'Action: Mark Completed',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [4400, 8000],
    })
    ActionMarkCompleted = {};

    @node({
        id: 'bd9036aa-0a63-43fd-a76f-6125dca1cd2a',
        name: 'Action: Get Short Doc ID1',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [4400, 5056],
    })
    ActionGetShortDocId1 = {};

    @node({
        id: 'priorityActionMapRequest',
        name: 'Map Request',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [4400, 7456],
    })
    MapRequest = {
        assignments: {
            assignments: [
                {
                    id: 'fed4050e-2006-4cee-9c9b-eaf203fc9e93',
                    name: 'IDSUP',
                    value: '={{ String($json.COMPANY_ID ?? "").trim() }}',
                    type: 'string',
                },
                {
                    id: '0eb7190e-f403-409c-8db8-b74ad03802e2',
                    name: 'DATEDOC',
                    value: '={{ (() => { const v = String($json.DOC_DATE ?? "").trim(); return v.length >= 10 ? v.substring(0, 6) + v.slice(-2) : v; })() }}',
                    type: 'string',
                },
                {
                    id: 'c76004fd-1c80-4ab1-b50b-69e5ff28d015',
                    name: 'DOCNAME',
                    value: '={{ String($json.DOC_ID ?? "").trim() }}',
                    type: 'string',
                },
                {
                    id: 'd7992977-c885-4a0f-85b7-2152c0453dfe',
                    name: 'DOCSHORT',
                    value: '={{ String($json.SHORT_DOC_ID ?? "").trim() }}',
                    type: 'string',
                },
                {
                    id: '0efd985c-2e85-424f-a963-ffe9b2543dc8',
                    name: 'TOTPRICE',
                    value: '={{ parseFloat(String($json.DOC_TOTAL_AMOUNT ?? $json.TOTAL_AMOUNT ?? "").replace(/,/g, "")) || 0 }}',
                    type: 'number',
                },
                {
                    id: '6760ce40-e6ca-4564-a980-f7c40473a2ca',
                    name: 'DOC_INV',
                    value: '={{ String($json.SHIPMENT_DOC_ID ?? "").trim() }}',
                    type: 'string',
                },
                {
                    id: 'd8b6f5a6-66e8-4715-95a0-2e616e730f0f',
                    name: 'PORDNAME',
                    value: '={{ String($json.PURCHASE_ID ?? "").trim() }}',
                    type: 'string',
                },
                {
                    id: '0d82538e-51f8-4305-a2c7-539e54ed8b22',
                    name: 'LINKDOC',
                    value: '={{ String($json.LINK ?? "").trim() }}',
                    type: 'string',
                },
                {
                    id: '6475936b-c09a-403e-ac6d-5da3f01a5839',
                    name: 'TYPEDOC',
                    value: '={{ String($json.TYPE ?? "").trim() }}',
                    type: 'string',
                },
                {
                    id: '698c899a-35cc-4a61-b291-2a288ffcfdb7',
                    name: 'SOURCE',
                    value: '={{ String($json.SOURCE_TYPE ?? "").trim() }}',
                    type: 'string',
                },
                {
                    id: '4c9c9691-a0e5-45fe-9d9c-e84bfe9928b2',
                    name: 'FROMWAREHOUSE',
                    value: "={{ String($json.FROM_OFFICE == null ? '' : $json.FROM_OFFICE).trim().toLowerCase() === 'true' ? 'Y' : \"\" }}",
                    type: 'string',
                },
                {
                    id: '51d8c251-cb6f-4298-984e-54ac4066f75b',
                    name: 'PROPORTZ_CERTAINTY',
                    value: '={{ String(parseInt($json.SELECTION_CERTAINTY) || 0) }}',
                    type: 'string',
                },
                {
                    id: '6eb8ec0e-8883-4e07-9def-001fe2b1c67c',
                    name: 'N8N_EXEID',
                    value: '={{ $execution.id }}',
                    type: 'string',
                },
                {
                    id: '8694823b-bb64-4d9c-99d9-20fdd8933436',
                    name: 'INCOMING_DOC_ID',
                    value: '={{ $json.ID || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '9ed4806f-95f7-4071-9454-2d616ed8421a',
        name: '3a. GDOC Action Switch1',
        /*__n8n__*/ notes: "[dead-arm ledger 2026-08-31] Six rules of this switch are Inv-clone residue no decide can emit for a doc routed here (the router routes by DOC_TYPE; reachable = the shipment decide's emit-set + the global decide's): no_action_awating_doc_id, no_action_doc_date_missing, no_action_doc_total_amount_missing, update_status_missing_shipment, extract_invoice_google_ai, select_invoice_values, action_extract_shipment_ids (comment-only in this decide too -- the 18-node link chain behind it was deleted 2026-09-01, same evidence as Inv's). The RULES stay in place -- deleting a rule re-indexes every output after it -- but their outputs are cleared and the one exclusive subtree (missing-shipment noOp -> Loop Over Items17 -> the MISSING_SHIPMENT build) is deleted. extract_invoice_google_ai's wire was an extra feeder into the live 'Action: Extract Per Type', removed. __unhandled_action__ stays: it is the loud-refusal guard.",
        type: 'n8n-nodes-base.switch',
        version: 2,
        position: [3280, 6048],
    })
    _3aGdocActionSwitch1 = {
        dataType: 'string',
        value1: '={{ $json.ACTION }}',
        rules: {
            rules: [
                {
                    value2: 'update_name',
                    outputKey: 'update_name',
                },
                {
                    value2: 'restart_gdoc',
                    outputKey: 'restart_gdoc',
                },
                {
                    value2: 'no_action_awaiting_company_id',
                    outputKey: 'no_action_awaiting_company_id',
                },
                {
                    value2: 'no_action_awating_doc_id',
                    outputKey: 'no_action_awating_doc_id',
                },
                {
                    value2: 'get_short_doc_id',
                    outputKey: 'get_short_doc_id',
                },
                {
                    value2: 'find_link',
                    outputKey: 'find_link',
                },
                {
                    value2: 'update_status_missing_link',
                    outputKey: 'update_status_missing_link',
                },
                {
                    value2: 'no_action_link_not_found',
                    outputKey: 'no_action_link_not_found',
                },
                {
                    value2: 'get_api_tools_id',
                    outputKey: 'get_api_tools_id',
                },
                {
                    value2: 'update_status_api_tools_failed',
                    outputKey: 'update_status_api_tools_failed',
                },
                {
                    value2: 'no_action_api_tools_failed',
                    outputKey: 'no_action_api_tools_failed',
                },
                {
                    value2: 'check_from_office',
                    outputKey: 'check_from_office',
                },
                {
                    value2: 'no_action_doc_date_missing',
                    outputKey: 'no_action_doc_date_missing',
                },
                {
                    value2: 'no_action_doc_total_amount_missing',
                    outputKey: 'no_action_doc_total_amount_missing',
                },
                {
                    value2: 'update_status_missing_shipment',
                    outputKey: 'update_status_missing_shipment',
                },
                {
                    value2: 'extract_invoice_google_ai',
                    outputKey: 'extract_invoice_google_ai',
                },
                {
                    value2: 'action_extract_shipment_ids',
                    outputKey: 'extract_shipment_ids',
                },
                {
                    value2: 'select_invoice_values',
                    outputKey: 'select_invoice_values',
                },
                {
                    value2: 'action_priority_sync',
                    outputKey: 'priority_sync',
                },
                {
                    value2: 'no_action_priority_sync_failed',
                    outputKey: 'no_action_priority_sync_failed',
                },
                {
                    value2: 'restart_priority_sync',
                    outputKey: 'restart_priority_sync',
                },
                {
                    value2: 'mark_completed',
                    outputKey: 'mark_completed',
                },
                {
                    value2: 'update_company_doc_id',
                    outputKey: 'update_company_doc_id',
                },
                {
                    value2: 'no_action_already_completed',
                    outputKey: 'no_action_already_completed',
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
            fallbackOutput: 24,
        },
    };

    @node({
        id: '46e898ca-d403-4316-ad40-ae9165fd74bc',
        name: 'Action: Restart GDOC',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [4400, 4768],
    })
    ActionRestartGdoc = {};

    @node({
        id: 'fb58d3aa-cfe8-4d29-8183-329bcb6f6c44',
        name: 'Action: Update Status MISSING_LINK',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [4400, 5728],
    })
    ActionUpdateStatusMissingLink = {};

    @node({
        id: '980994ec-6334-404a-b213-24f0bb61a4d3',
        name: 'Action: Update NAME',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [4400, 4416],
    })
    ActionUpdateName = {};

    @node({
        id: 'f3ee3008-9b2e-4aae-a6ae-b9b04e638fd4',
        name: 'Action: Find Link in Drive',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [3952, 5408],
    })
    ActionFindLinkInDrive = {};

    @node({
        id: '03306ed5-da9e-4aee-a7c1-c4a2b91b0ccd',
        name: 'Loop Over Items35',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [4624, 8592],
    })
    LoopOverItems35 = {
        batchSize: 100,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: 'restart-ps-action-0000000c0de',
        name: 'Action: restart priority_sync',
        /*__n8n__*/ notes: "[2026-08-23, owner order] A RE-SEND IS NOT A SEND. decide returns this when PRIORITY_SYNC_SIGNATURE shows the line changed since it was last delivered. It does NOT post to Priority -- it only clears PRIORITY_SYNC_COMPLETED, and the NEXT sweep's decide then returns the ordinary action_priority_sync. Two reasons it is split that way: the name starts with 'restart', which is the exemption 'Dup Guard: Double Action' already honours, so it also lands a restart marker in ACTION_HISTORY that unblocks the following action_priority_sync; and the actual send stays in exactly one place instead of being duplicated behind a second verb.",
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [4624, 7808],
    })
    ActionRestartPrioritySync = {};

    @node({
        id: 'restart-ps-build-00000000c0de',
        name: 'Build: Batch Update - restart priority_sync',
        /*__n8n__*/ notes: "Clears the flag and the stored signature so the next sweep re-sends. The signature is nulled deliberately: leaving the old one in place would let the next comparison read equal and go silent again.",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [4848, 7728],
    })
    BuildBatchUpdateRestartPrioritySync = {
        assignments: {
            assignments: [
                {
                    id: 'rps0',
                    name: 'ID',
                    value: "={{ $('Action: restart priority_sync').item.json.ID }}",
                    type: 'string',
                },
                {
                    id: 'rps1',
                    name: 'PRIORITY_SYNC_COMPLETED',
                    value: '={{ false }}',
                    type: 'string',
                },
                {
                    id: 'rps2',
                    name: 'PRIORITY_SYNC_SIGNATURE',
                    value: '={{ null }}',
                    type: 'string',
                },
                {
                    id: 'rps-unlock-0000000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'rps-verb-00000000000c0de',
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
        id: 'priorityActionEntry',
        name: 'Action: priority_sync',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [3952, 7552],
    })
    ActionPrioritySync = {};

    @node({
        id: '98970ca8-89bb-490c-830a-f1ed9aad99ab',
        name: 'Loop Over Items5',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [4624, 5056],
    })
    LoopOverItems5 = {
        batchSize: 100,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: '6a7297a0-7571-441e-98f8-0ff8f4e9ab86',
        name: 'Loop Over Items30',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [4176, 7552],
    })
    LoopOverItems30 = {
        batchSize: 15,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: '30bce948-ffff-4091-a7f6-bf367cf29b74',
        name: 'Loop Over Items1',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [4400, 6320],
    })
    LoopOverItems1 = {
        batchSize: 25,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: '346506be-233c-401d-badf-8a8f10d20229',
        name: 'Call Search File',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [4400, 5328],
    })
    CallSearchFile = {
        workflowId: {
            __rl: true,
            value: 'indoxV2SearchFile01',
            mode: 'list',
            cachedResultUrl: '/workflow/indoxV2SearchFile01',
            cachedResultName: 'Search File',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                COMPANY_NAME: "={{ $('Action: Find Link in Drive').item.json.COMPANY_NAME }}",
                SHORT_DOC_ID: "={{ $('Action: Find Link in Drive').item.json.SHORT_DOC_ID }}",
                ID: "={{ $('Action: Find Link in Drive').item.json.ID }}",
                __instance: "={{ (() => { try { return String(($('When Called').first().json||{}).__instance||''); } catch(e) { return ''; } })() }}",
            },
            matchingColumns: ['COMPANY_NAME', 'SHORT_DOC_ID'],
            schema: [
                {
                    id: 'COMPANY_NAME',
                    displayName: 'COMPANY_NAME',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    removed: false,
                },
                {
                    id: 'SHORT_DOC_ID',
                    displayName: 'SHORT_DOC_ID',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    removed: false,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        mode: 'each',
        options: {},
    };

    @node({
        id: '7772dd08-8288-4b08-aef5-ff97b659c440',
        name: 'Action: update DOC_ID',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [4400, 8592],
    })
    ActionUpdateDocId = {};

    @node({
        id: 'priorityActionPostTable',
        name: 'Post Priority Table',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.3,
        position: [4624, 7456],
        credentials: { httpBasicAuth: { id: 'LKWC9RKUhNHQWvoM', name: 'Priority Production [env-managed]' } },
        onError: 'continueRegularOutput',
    })
    PostPriorityTable = {
        method: 'POST',
        url: '={{ $("Action: priority_sync").item.json.__priority_local === false ? "https://msh.macomp.vip/odata/Priority/tabula.ini/mscohen/SHIM_RECEIVE_SUPDOC" : "http://n8n-webhook:5678/webhook/indox-priority-local" }}',
        authentication: 'genericCredentialType',
        genericAuthType: 'httpBasicAuth',
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ $json.toJsonString() }}',
        options: {
            batching: {
                batch: {
                    batchSize: 2,
                },
            },
            timeout: '={{ 30000 }}',
        },
    };

    @node({
        id: 'restoredocs01',
        name: 'Restore Docs (From Office)',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [4176, 6320],
    })
    RestoreDocsFromOffice = {
        jsCode: "return $('Action: Check From Office1').all();",
    };

    @node({
        id: 'aa17ca19-70cd-4ee2-9908-fbed50f86641',
        name: 'Action: Update STATUS - API_TOOLS_ID_FAILED',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [4400, 6016],
    })
    ActionUpdateStatusApiToolsIdFailed = {};

    @node({
        id: 'cf80b578-e88e-4639-bcd3-57768ad1c1bb',
        name: 'Loop Over Items',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [4624, 5728],
    })
    LoopOverItems = {
        batchSize: 100,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: '9d51e68c-ae5a-47fc-87f0-b18acab7942a',
        name: 'Loop Over Items2',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [4176, 5408],
    })
    LoopOverItems2 = {
        batchSize: 25,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: 'mwhset01',
        name: 'Get Warehouse Setting',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [3952, 6320],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    GetWarehouseSetting = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: '53c7eebd-2bd0-48cd-9705-e4759c836212',
        name: 'Action: Check From Office1',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [3504, 6320],
    })
    ActionCheckFromOffice1 = {};

    @node({
        id: 'wh000000-0000-0000-0000-0000000000a1',
        name: 'WH Req (settings)',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3728, 6320],
    })
    WhReqSettings = {
        jsCode: `// INSTANCE: the instance this row belongs to (phase 6.5). The chokepoint THROWS without it.
// Hardcoded to the first instance here because this is part of the v1/demo/test tail the
// plan scopes separately — these workflows seed or read fixtures for one known deployment.
// The v3 engine does NOT hardcode it: it carries the instance from the work item.
const INSTANCE='incoming-documents-main';
// [tenant carry 2026-08-31] __instance is the SCHEMA the chokepoint must serve (cutover
// throw without it -- 21 live errors/hour measured); the 'instance' field above is the row-scope
// VALUE inside that schema. Read at the boundary, never mid-chain.
var __inst=''; try{ __inst=String(($('When Called').first().json||{}).__instance||''); }catch(e){}
return [{ json: { INLINE_ACTION: 'TABLE_GET', table: 'settings', instance: INSTANCE, __instance: __inst, filter: { key: 'WarehouseScansSourceFolder' } } }];`,
    };

    @node({
        id: '75dd3710-33cb-46b8-8882-6db8813660e2',
        name: 'If Found File1',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [4624, 5328],
    })
    IfFoundFile1 = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: 'bb6d03b8-6b51-4982-bc9c-191d2f44b382',
                    leftValue: '={{ $json?.id }}',
                    rightValue: '',
                    operator: {
                        type: 'string',
                        operation: 'notEmpty',
                        singleValue: true,
                    },
                },
                {
                    id: 'a7b8c9d0-eeee-ffff-0000-okmustbetrue11',
                    leftValue: '={{ $json.ok === true }}',
                    rightValue: '',
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
        id: '236b6cb5-8f02-438f-b294-9d47392bcb0b',
        name: 'Call Search From Waerhouse',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [4624, 6288],
        alwaysOutputData: true,
    })
    CallSearchFromWaerhouse = {
        workflowId: {
            __rl: true,
            value: 'indoxV2SearchWarehouse01',
            mode: 'list',
            cachedResultUrl: '/workflow/indoxV2SearchWarehouse01',
            cachedResultName: 'Search File In Warehouse Scans',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                SHORT_DOC_ID: '={{ $json.SHORT_DOC_ID }}',
                COMPANY_NAME: '={{ $json.COMPANY_NAME }}',
                ID: '={{ $json.ID }}',
                __instance:
                    "={{ (() => { try { return String(($('When Called').first().json||{}).__instance||''); } catch(e) { return ''; } })() }}",
                WAREHOUSE_FOLDER:
                    "={{ (() => { try { const r = $('Get Warehouse Setting').first().json; const raw = (r && r.value) || ''; const m = String(raw).match(/folders\\/([A-Za-z0-9_-]+)/); if (m) return m[1]; return (raw && !String(raw).includes('/')) ? raw : ''; } catch(e) { return ''; } })() }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'COMPANY_NAME',
                    displayName: 'COMPANY_NAME',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                },
                {
                    id: 'SHORT_DOC_ID',
                    displayName: 'SHORT_DOC_ID',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        mode: 'each',
        options: {},
    };

    @node({
        id: 'gdocv2trig',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [2608, 6384],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: '802a6864-5f85-43ac-9583-7dd59c5c280c',
        name: "Build: Call 'Incoming Document Batch Update' - STATUS MISSING_LINK",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [4848, 5696],
    })
    BuildCallIncomingDocumentBatchUpdateStatusMissingLink = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: "={{ $('Action: Update Status MISSING_LINK').item.json.ID }}",
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'STATUS',
                    value: 'MISSING_LINK',
                    type: 'string',
                },
                {
                    id: 'bw2',
                    name: 'ERROR',
                    value: "={{ ($('Action: Update Status MISSING_LINK').item.json.LINK && !String($('Action: Update Status MISSING_LINK').item.json.LINK_CONNECTION || '').trim()) ? 'missing link connection' : ($json.error || 'missing link') }}",
                    type: 'string',
                },
                {
                    id: 'unlock-0006-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0057-4000-8000-00000000c0de',
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
        id: 'b617ed3a-b822-4525-b72f-b4ada005a8c9',
        name: "Build: Call 'Incoming Document Batch Update' - SEARCH_IN_DRIVE_COMPLETED",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [4848, 5424],
    })
    BuildCallIncomingDocumentBatchUpdateSearchInDriveCompleted = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: "={{ $('Action: Find Link in Drive').item.json.ID }}",
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'SEARCH_IN_DRIVE_COMPLETED',
                    value: '={{ true }}',
                    type: 'string',
                },
                {
                    id: 'bw2',
                    name: 'ERROR',
                    value: '={{ $json.error || null }}',
                    type: 'string',
                },
                {
                    id: 'unlock-0008-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0059-4000-8000-00000000c0de',
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
        id: 'priorityActionBuildUpdate',
        name: 'Build: Batch Update - priority_sync',
        /*__n8n__*/ notes: "[priority fail-proof 2026-08-23] THE ATTEMPT ALWAYS COMPLETES. PRIORITY_SYNC_COMPLETED used to be {{ !$json.error }}, so a failed sync left it 'false'; decide re-selected action_priority_sync on the next sweep and 'Dup Guard: Double Action' refused it, because signal A is existence-only and a crashed attempt buys no free re-run. The row was COMPLETED -- terminal -- so restart_all_not_completed.sh could never reach it either: a permanent deadlock that killed a whole driver batch every drain, since the raise is stop-and-error. Measured 2026-08-23: 16 such documents, and the set regrew to 85 within 12 minutes of clearing them. Now the flag records that the ATTEMPT finished, and the OUTCOME is carried by STATUS + ERROR. A failure parks as PRIORITY_SYNC_FAILED and decide returns no_action_priority_sync_failed; re-running is an explicit ACTION_RESTART, never an accident. On success STATUS is passed through unchanged -- this node still never decides a document's fate.",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [4848, 7456],
    })
    BuildBatchUpdatePrioritySync = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: "={{ $('Action: priority_sync').item.json.ID }}",
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'PRIORITY_SYNC_COMPLETED',
                    value: '={{ true }}',
                    type: 'string',
                },
                {
                    id: 'bw1b',
                    name: 'STATUS',
                    value: "={{ $json.error ? 'PRIORITY_SYNC_FAILED' : $('Action: priority_sync').item.json.STATUS }}",
                    type: 'string',
                },
                {
                    id: 'bw2',
                    name: 'PRIORITY_SYNC_COUNT',
                    value: "={{ (Number($('Action: priority_sync')?.item?.json?.PRIORITY_SYNC_COUNT) || 0) + 1 }}",
                    type: 'string',
                },
                {
                    id: 'bw2b',
                    name: 'PRIORITY_SYNC_SIGNATURE',
                    value: "={{ $json.error ? null : ($('Action: priority_sync').item.json.__priority_sig || null) }}",
                    type: 'string',
                },
                {
                    id: 'bw3',
                    name: 'ERROR',
                    value: '={{ $json.error || null }}',
                    type: 'string',
                },
                {
                    id: 'unlock-0009-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0060-4000-8000-00000000c0de',
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
        id: '5cf0c1af-8166-4353-9d27-e80b133c56e2',
        name: "Build: Call 'Incoming Document Batch Update' - STATUS COMPLETED",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [4848, 7968],
    })
    BuildCallIncomingDocumentBatchUpdateStatusCompleted = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: "={{ $('Action: Mark Completed').item.json.ID }}",
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
                    id: 'bw_docid',
                    name: 'DOC_ID',
                    value: "={{ (function(){ var r = $('Action: Mark Completed').item.json; var h = function(v){ return v !== null && v !== undefined && String(v).trim() !== '' && String(v).trim().toLowerCase() !== 'unknown'; }; if (h(r.DOC_ID)) return String(r.DOC_ID).trim(); var canon = function(v){ return String(v === null || v === undefined ? '' : v).replace(/[^a-zA-Z0-9]/g, '').toUpperCase(); }; var inv = h(r.INVOICE_ID) ? String(r.INVOICE_ID).trim() : null; return inv; })() }}",
                    type: 'string',
                },
                {
                    id: 'unlock-0010-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0061-4000-8000-00000000c0de',
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
        id: 'f7501683-2161-45c8-b099-0a35980b77a6',
        name: 'Build: Update NAME',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [4848, 4160],
    })
    BuildUpdateName = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: "={{ $('Action: Update NAME').item.json.ID }}",
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'NAME',
                    value: '={{ ($(\'Action: Update NAME\').item.json.COMPANY_NAME || "unknown") + "-" + ($(\'Action: Update NAME\').item.json.SHORT_DOC_ID || "unknown" ) }}',
                    type: 'string',
                },
                {
                    id: 'bw2',
                    name: 'ERROR',
                    value: '={{ $json.error || null }}',
                    type: 'string',
                },
                {
                    id: 'unlock-0011-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0062-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-tc-07-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '3224a2e3-8abf-4b69-9a66-ae4ed236c6a3',
        name: "Build: Call 'Incoming Document Batch Update' - STATUS API_TOOLS_FAILED1",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [4848, 5968],
    })
    BuildCallIncomingDocumentBatchUpdateStatusApiToolsFailed1 = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: "={{ $('Action: Update STATUS - API_TOOLS_ID_FAILED').item.json.ID }}",
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'STATUS',
                    value: 'API_TOOLS_FAILED',
                    type: 'string',
                },
                {
                    id: 'bw2',
                    name: 'ERROR',
                    value: '={{ $json.error || "no OCR upload id (API_TOOLS_ID): base extraction produced none for this file/link — fix the source and ACTION_RESTART" }}',
                    type: 'string',
                },
                {
                    id: 'unlock-0012-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0063-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-tc-09-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'abe47959-d9e7-4c36-aa66-72a19e30ac1b',
        name: 'Build: Restart (clear completed flags)',
        /*__n8n__*/ notes: "[dynamic restart 2026-08-17, owner order] ACTION_RESTART clears EVERY *_COMPLETED flag on the row, derived from the row keys at runtime - never a hardcoded list (the old Set node here named 11 flags and missed BASE_EXTRACTION_COMPLETED + PER_TYPE_EXTRACTION_COMPLETED, so a restart never re-ran extraction). FROM_OFFICE_CHECK is the one legacy completion flag without the suffix - kept explicitly. STATUS -> IN_PROGRESS, ERROR clears, next sweep re-walks the whole pipeline.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [4848, 4736],
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
  // [2026-08-20] The ACTION_LOG append that stood here went with the column. The restart's
  // own record is the dispatch row indoxV2ActionRouter01 :: 'Log Action Start' writes for
  // ACTION=restart_*, which is also what carries the restart epoch for the dup guard.
  out.push({ json: o });
}
return out;
`,
    };

    @node({
        id: 'f9c4811e-f8d1-4d57-8f8f-abe40949a104',
        name: "Build: Call 'Incoming Document Batch Update'4",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [4864, 8544],
    })
    BuildCallIncomingDocumentBatchUpdate4 = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: '={{ $json.ID }}',
                    type: 'string',
                },
                {
                    id: 'docid-fill-01',
                    name: 'DOC_ID',
                    value: '={{ $json.NEW_DOC_ID || $json.DOC_ID || null }}',
                    type: 'string',
                },
                {
                    id: 'bw2',
                    name: 'ERROR',
                    value: '={{ $json.error || null }}',
                    type: 'string',
                },
                {
                    id: 'unlock-0018-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0069-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-tc-12-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '109cedbf-b9fd-4a67-b3b5-aaa58c9365cb',
        name: "Build: Call 'Incoming Document Batch Update'1",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [4848, 5024],
    })
    BuildCallIncomingDocumentBatchUpdate1 = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: "={{ $('Action: Get Short Doc ID1').item.json.ID }}",
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'SHORT_DOC_ID',
                    value: `={{ String($('Action: Get Short Doc ID1').item.json.DOC_ID || '').trim().replace(/[^a-zA-Z0-9]/g, '').slice(-5).padStart(5, '0')
}}`,
                    type: 'string',
                },
                {
                    id: 'bw2',
                    name: 'ERROR',
                    value: '={{ $json.error || null }}',
                    type: 'string',
                },
                {
                    id: 'unlock-0019-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0070-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-tc-13-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '584e1745-e856-4bc9-90fa-9a833a8cc503',
        name: "Build: Call 'Incoming Document Batch Update' - FROM_OFFICE",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [4848, 6288],
    })
    BuildCallIncomingDocumentBatchUpdateFromOffice = {
        assignments: {
            assignments: [
                {
                    id: 'inst-from-office-ship',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
                {
                    id: 'bw0',
                    name: 'ID',
                    value: '={{ $json.ID }}',
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'FROM_OFFICE',
                    value: '={{ $json.ok || false}}',
                    type: 'string',
                },
                {
                    id: 'bw2',
                    name: 'FROM_OFFICE_CHECK',
                    value: '={{ true }}',
                    type: 'string',
                },
                {
                    id: 'bw3',
                    name: 'ERROR',
                    value: '={{ $json.error || null }}',
                    type: 'string',
                },
                {
                    id: 'unlock-0020-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0071-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'e8d7487c-8b4b-4541-92dc-f9477c068d49',
        name: "Build: Call 'Incoming Document Batch Update' - LINK FOUND",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [4848, 5232],
    })
    BuildCallIncomingDocumentBatchUpdateLinkFound = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: "={{ $('Action: Find Link in Drive').item.json.ID }}",
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'LINK',
                    value: "={{ $json.link || ('https://drive.google.com/file/d/' + $json.id) }}",
                    type: 'string',
                },
                {
                    id: 'bw1c',
                    name: 'LINK_CONNECTION',
                    value: '={{ $json.connection_id || "" }}',
                    type: 'string',
                },
                {
                    id: 'bw2',
                    name: 'SEARCH_IN_DRIVE_COMPLETED',
                    value: '={{ true }}',
                    type: 'string',
                },
                {
                    id: 'bw3',
                    name: 'NAME',
                    value: '={{ $json.name }}',
                    type: 'string',
                },
                {
                    id: 'bw4',
                    name: 'SOURCE_TYPE',
                    value: 'GOOGLE_DRIVE_FILE',
                    type: 'string',
                },
                {
                    id: 'bw5',
                    name: 'STATUS',
                    value: 'IN_PROGRESS',
                    type: 'string',
                },
                {
                    id: 'bw6',
                    name: 'SOURCE_ID',
                    value: '={{ $json?.id }}',
                    type: 'string',
                },
                {
                    id: 'bw7',
                    name: 'SIZE',
                    value: '={{ $json?.size || null }}',
                    type: 'string',
                },
                {
                    id: 'bw8',
                    name: 'HASH',
                    value: '={{ $json.md5Checksum }}',
                    type: 'string',
                },
                {
                    id: 'bw9',
                    name: 'SOURCE_LINK',
                    value: '=https://drive.google.com/file/d/{{ $json.id }}',
                    type: 'string',
                },
                {
                    id: 'bw10',
                    name: 'ERROR',
                    value: '={{ $json.error || null }}',
                    type: 'string',
                },
                {
                    id: 'unlock-0021-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0072-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-tc-14-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
                {
                    id: 'bwlc',
                    name: 'LINK_CONNECTION',
                    value: '={{ $json.connection_id || "" }}',
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
        position: [5072, 5232],
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
        id: 'gdocdecidehead01',
        name: 'Decide Shipment Action',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3056, 6288],
    })
    DecideShipmentAction = {
        jsCode: `// __EXPORTABLE__ [owner design 2026-08-18] THE decide logic lives HERE and only here.
// Wrapped as one self-contained function so this node can EXPORT ITS OWN SOURCE:
// mode='export_decide' returns { fnSrc: __shipDecideFn.toString() } and the mega decide
// (indoxV2DecideMin01) rehydrates it with new Function('$','$execution', src)($,$execution)
// and runs it in ONE code node. Node-input accessors were replaced by the __items
// parameter; $()/$ execution references resolve in WHICHEVER context runs the function
// (router graph or mega) — $('Companies') is absent in mega by design, __CFG catches.
function __shipDecideFn(__items) {
// [DOC_ID consolidation 2026-08-11] THE CONSOLIDATED ID IS DERIVABLE, AND 1,752 SETTLED

// [retired 2026-08-17, owner order] DOC_ID CONSOLIDATE one-shot removed: the one-time SQL
// backfill consolidated all derivable rows, and Build Per Type Upsert now writes DOC_ID on
// every pass. the legacy doc-number parameter is retired fleet-wide (DOC_ID is canonical).
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

// [v2.1] router_gdoc — DECIDE mode. Returns this doc's next gdoc ACTION (no execution).
// Called by indox-v2 Decide (unlocked). invoice/shipment/order share gdocHead/gdocTail.
// [perf 2026-08-18] memoized per invocation: when $('Companies') is absent (mega context)
// the un-memoized version threw+caught one exception PER ROW. Deterministic within a run.
let __CFG_C; function __CFG(){ if (__CFG_C !== undefined) return __CFG_C; let c={}; try{ c=$('Companies').first().json||{}; }catch(e){} try{ const x=(__items[0]||{json:{}}).json._cfg; if(x&&typeof x==='object') c={...c,...x}; }catch(e){} __CFG_C = c; return c; }


function isBlank(val) {
  return [null, undefined, '', 'unknown'].includes(
    (String(val ?? '')).toLowerCase()
  );
}

function parseAiShipmentIds(value) {
  if (!value || value === 'empty') return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) && parsed.length > 0 ? parsed : [];
  } catch {
    return [];
  }
}

function gdocHead(doc) {
  if (doc.STATUS === 'ACTION_RESTART')
    return 'restart_gdoc';

  if (!isBlank(doc.DOC_ID)) {
    const expectedShort = String(doc.DOC_ID ?? '')
      .trim()
      .replace(/[^a-zA-Z0-9]/g, '')
      .slice(-5)
      .padStart(5, '0');
    if (!doc.SHORT_DOC_ID || String(doc.SHORT_DOC_ID) !== expectedShort)
      return 'get_short_doc_id';

    const expectedName = \`\${doc.COMPANY_NAME ?? 'unknown'}-\${doc.SHORT_DOC_ID ?? 'unknown'}\`;
    if (doc.NAME !== expectedName)
      return 'update_name';

    if (isBlank(doc.FROM_OFFICE_CHECK))
      return 'check_from_office';
  }
  return null;
}

function gdocTail(doc) {
  // [two-point 2026-08-07] RESTORED. The v2.1 state-machine rewrite dropped this
  // line; the pre-rewrite decide (context-collection/incoming-documents-0.1.6)
  // returned it between extract_invoice_google_ai and action_priority_sync. Without
  // it the switch case (output 21), the whole handler chain, indoxV2Driver01 own
  // self-test case and every fixture oracle expect an action no decide can produce.
  //
  // Placed in gdocTail, not in invoiceDecide, because all three oracles put it in
  // exactly this slot -- immediately before priority_sync/mark_completed:
  //   invoice  : ... action_extract_shipment_ids -> select_values -> priority_sync
  //   shipment : ... update_company_doc_id       -> select_values -> priority_sync
  //   order    : ...                                select_values -> mark_completed
  //
  // The PRIORITY_SYNC_COMPLETED half of the guard MIRRORS the skip at the top of
  // Selection & Scoring Logic1. Without it a row that is already ERP-synced would be
  // asked to select, be skipped by the computer, never get SELECTION_COMPLETED
  // written, and be asked again -- a livelock ending in MAX_ITERATIONS. Measured
  // 2026-08-07: 21 rows sit in that cell today (all MISSING_COMPANY_ID). This does
  // NOT reset anyone sync flag; it only declines to re-open a settled document.
  //
  // The STATUS !== 'COMPLETED' half keeps this to documents still FLOWING THROUGH.
  // Without it the step also re-opens documents long since settled at
  // no_action_already_completed: measured 2026-08-07 over all 7095 live rows, that
  // is 453 rows on gdoc / 436 on shipment, versus 26 / 17 with this guard. Those
  // settled rows are the selection BACKLOG, and clearing the backlog is a separate,
  // deliberate, gated backfill -- not a side effect of restoring reachability.
  // Note this is why a document must be selected BEFORE it is marked completed,
  // which is exactly the order all three fixture oracles specify.
  // [selection 2026-08-25, owner order] select_invoice_values IS RETIRED. It was a SECOND opinion
  // that wrote only SELECTED_* -- a parallel set of values with inverted precedence that no gate
  // ever read and that the ERP payload then preferred over the document's own fields. Its two
  // useful halves, the corroboration score and the trusted-supplier override, moved into
  // SelectType01 where the values they judge are actually decided.

  // THE SELECTION IS RE-MADE WHEN ITS INPUTS CHANGE. Unlike the step it replaces, select_type can
  // run again: its inputs are hashed, so an aging report that links a month after the document was
  // completed writes BS_LINE_*, the live hash stops matching the stored one, and the decision is
  // re-made without opening the file or calling a model. Deliberately NO STATUS term on the hash
  // arm -- a COMPLETED document is exactly the case that is broken today.
  // FAIL-SAFE: a difference counts only when BOTH hashes exist, so rows selected before this
  // column existed are picked up by a deliberate dispatch, never by a wave nobody asked for.
  {
    var _stDone = String(doc.SELECTION_COMPLETED == null ? '' : doc.SELECTION_COMPLETED)
                    .trim().toLowerCase() === 'true';
    var _stLive = doc.__selection_hash, _stStored = doc.SELECTION_VALUES_HASH;
    var _stChanged = !!_stLive && !!_stStored && String(_stLive) !== String(_stStored);
    // NO EXTRACTION-FLAG PRECONDITION. This gate used to require PER_TYPE_EXTRACTION_COMPLETED,
    // which is exactly the flag ACTION_RESTART clears -- so a restarted document skipped selection
    // entirely and went straight to priority and mark_completed with whatever finals it happened to
    // be carrying. Reproduced end-to-end on 2026-08-25 with three real documents: restart_gdoc ->
    // action_priority_sync -> mark_completed, no extraction and no selection in between.
    // Ordering already guarantees extraction goes first when it is owed: __needsPerType returns
    // ahead of this function, so reaching here means extraction is either done or not owed. And a
    // selection over a row with no versions yet is a no-op that stamps its flag and its hash --
    // when extraction later fills the versions the hash changes and the decision is re-made.
    if (_stChanged || (!_stDone && doc.STATUS !== 'COMPLETED')) return 'select_type';
  }

  // [priority gate 2026-08-21] READ THE FLAG THE DRIVER CARRIES, NOT __CFG().
  //
  // This used to be __CFG().activePrioritySync -- but __CFG() reads $('Companies') or an injected
  // _cfg, and this workflow has NO Companies node and nothing injects _cfg, so __CFG() is {} here
  // and _priorityActive was always false. The setting could be flipped to true and nothing would
  // happen: action_priority_sync had 0 dispatches all-time, and every row carrying
  // PRIORITY_SYNC_COMPLETED was written by the v1 processors instead. __CFG() is kept as a
  // fallback so a caller that DOES populate it (the mega/manual paths) still works.
  let _priorityActive = false;
  try {
    const _drv = doc.__priority_sync_enabled;
    if (_drv === true || _drv === 'true' || _drv === 't') _priorityActive = true;
    else {
      const _ps = __CFG().activePrioritySync;
      _priorityActive = _ps === true || _ps === 'true';
    }
  } catch (e) { _priorityActive = false; }
  // [phase 5 2026-08-22] Re-send when the LINE CHANGED, not only when it was never sent.
  // Priority is keyed by business content, so a second POST of the same document becomes a
  // second record in the client's ERP -- which is why this cannot simply re-send on every sweep.
  //
  // FAIL-SAFE BY CONSTRUCTION: a difference counts only when BOTH signatures are present.
  //   never sent            -> send (unchanged behaviour)
  //   sent, sig equal       -> silent
  //   sent, sig different   -> re-send, the whole point of the feature
  //   sent, sig UNKNOWN     -> SILENT, not "changed"
  // That last line is the one that matters. The 4,749 rows v1 already delivered carry
  // PRIORITY_SYNC_COMPLETED=true and no signature, and there is no priority-sent timestamp
  // anywhere to reconstruct one. Treating "unknown" as changed would re-send all 4,749 on the
  // first sweep after the toggle and duplicate every one of them in the client's ERP. Treating
  // it as unchanged preserves exactly today's one-shot behaviour for those rows, so this change
  // can never make the ERP worse than it already is. Same reasoning if the driver is older than
  // this code and carries no __priority_sig at all.
  var _sentSig = doc.PRIORITY_SYNC_SIGNATURE;
  var _nowSig = doc.__priority_sig;
  var _sigChanged = !!_nowSig && !!_sentSig && String(_nowSig) !== String(_sentSig);
  // [2026-08-23] PRIORITY_SYNC_COMPLETED IS TEXT, NOT A BOOLEAN, and this gate read it as one.
  // In JS the string 'false' is TRUTHY, so a bare truthiness test was false for every row
  // explicitly marked not-synced. Census of the 10,210 COMPLETED documents when the toggle was
  // first switched on:
  //     'false'   5,770   <- read as ALREADY SYNCED. Could never be sent. Ever.
  //     'true'    3,455
  //     NULL        976   <- the only rows the gate could fire for
  // So flipping activePrioritySync appeared to do nothing: it dispatched zero of a 20-document
  // COMPLETED cohort, because every one of them carried the string 'false'.
  // Normalised the same way every other boolean-in-text column on this row is handled.
  var _sent = String(doc.PRIORITY_SYNC_COMPLETED == null ? '' : doc.PRIORITY_SYNC_COMPLETED)
                .trim().toLowerCase() === 'true';
  // [priority fail-proof 2026-08-23] A FAILED SYNC PARKS. IT DOES NOT LOOP.
  // 'Build: Batch Update - priority_sync' now records a failure as STATUS=PRIORITY_SYNC_FAILED with
  // the error, and always marks the ATTEMPT complete. Without this branch the row would fall through
  // to mark_completed and lose the failure; with it the document stops here, visibly, until someone
  // issues an ACTION_RESTART.
  if (String(doc.STATUS == null ? '' : doc.STATUS) === 'PRIORITY_SYNC_FAILED') {
    return 'no_action_priority_sync_failed';
  }

  // A RE-SEND IS A RESTART, NOT A REPEAT.
  // _sigChanged means the line genuinely changed and Priority must be told again -- but that is a
  // SECOND dispatch of the same action with no restart between it and the first, which is exactly
  // what 'Dup Guard: Double Action' signal A forbids. Measured 2026-08-23: doc_msm9ed2n4t4in0 carried
  // PRIORITY_SYNC_COMPLETED=true, had synced cleanly, and was still blocked on its re-send. The guard
  // already exempts any action whose name starts with 'restart', so the re-send says so in its name
  // instead of asking the guard to make an exception for this one action.
  // [priority skip 2026-08-23, owner order] PRIORITY_SKIP=true opts this line out of priority
  // sync entirely -- it falls through to mark_completed exactly as if the sync had happened.
  // Two writers set it: the owner (console, with a BLOCKLIST_* reason) and the 2026-08-23
  // backfill marking every line the PREVIOUS deployment already delivered to the ONLINE Priority
  // ('synced in last version' -- re-sending those would duplicate records in the client's ERP).
  // The column is boolean, but String(true)==='true' so the TEXT-boolean normalisation used
  // everywhere else on this row works unchanged.
  var _skip = String(doc.PRIORITY_SKIP == null ? '' : doc.PRIORITY_SKIP).trim().toLowerCase() === 'true';
  // [identity guard 2026-08-25, owner order] NEVER SEND A LINE THE ERP CANNOT IDENTIFY.
  // 'Map Request' casts with a raw String(), so a null SELECTED_* becomes the literal text 'null'
  // and a missing amount becomes 0. Measured 2026-08-25: ~440 rows in indox_priority_local carry
  // IDSUP='null' with no document number at all. Such a line is unmatchable in Priority -- it
  // cannot be reconciled by supplier and it cannot be reconciled by invoice number -- and it
  // cannot be cleaned up afterwards either. That is not a sync failure, it is an incomplete
  // document, so it parks visibly here instead of polluting the ERP. Both the legacy and the final
  // field are accepted, because during the SELECTED_* retirement either one may be the live source.
  var _idOk = function (v) {
    var s = String(v == null ? '' : v).trim().toLowerCase();
    return s !== '' && s !== 'null' && s !== 'undefined' && s !== 'none';
  };
  // [SELECTED_* retired 2026-09-02] the base selector's COMPANY_ID / DOC_ID are the only identity
  var _hasSupplier = _idOk(doc.COMPANY_ID);
  var _hasNumber = _idOk(doc.SHORT_DOC_ID) ||
                   _idOk(doc.AI_DOC_ID) || _idOk(doc.DOC_ID);
  if (_priorityActive && !_skip && !(_hasSupplier && _hasNumber)) {
    return 'no_action_priority_sync_missing_identity';
  }
  if (_priorityActive && _sent && _sigChanged && !_skip) {
    return 'restart_priority_sync';
  }
  if (_priorityActive && !_sent && !_skip) {
    return 'action_priority_sync';
  }

  if (doc.STATUS !== 'COMPLETED') return 'mark_completed';
  return 'no_action_already_completed';
}


// [no state-machine retries 2026-08-17, owner order] The 'PER TYPE GATE REOPEN' one-shot
// (2026-08-11 backlog re-open, ACTION_LOG-marker bound) is REMOVED: decide never re-dispatches
// a completed action. PER_TYPE_EXTRACTION_COMPLETED is the whole gate; ACTION_RESTART is the
// only re-run.
// [value+flag gate 2026-08-17, owner order] Per-type's sentinel VALUE is DOC_ID — see the
// GDoc twin for the full rule. Null/empty DOC_ID + cleared flag re-enters; anything else
// counts as produced and never re-runs on restart.
function __needsPerType(doc) {
  if (doc.STATUS === 'COMPLETED' || !doc.API_TOOLS_ID) return false;
  if (doc.DOC_ID) return false;
  return String(doc.PER_TYPE_EXTRACTION_COMPLETED == null ? '' : doc.PER_TYPE_EXTRACTION_COMPLETED).trim().toLowerCase() !== 'true';
}


function shipmentDecide(doc) {
  const h = gdocHead(doc); if (h) return h;

  // [missing link connection 2026-08-24, owner order] blank LINK_CONNECTION = missing link
  // (same clause as gdocDecide since 2026-08-13): the file cannot be fetched, so re-search it.
  const linkMissing = !doc.LINK || ['MISSING', '', undefined, null].includes(doc.LINK)
    || !String(doc.LINK_CONNECTION || '').trim();
  if (linkMissing) {
    if (String(doc.SEARCH_IN_DRIVE_COMPLETED == null ? '' : doc.SEARCH_IN_DRIVE_COMPLETED).trim().toLowerCase() !== 'true' && doc.SHORT_DOC_ID && doc.COMPANY_NAME)
      return 'find_link';
    // shipment is NOT dead-ended on a missing link.
  }

  // File-backed steps run only when a link exists AND is fetchable (linkless shipment skips them;
  // [missing link connection 2026-08-24] a link with no connection is not fetchable).
  if (doc.LINK && String(doc.LINK_CONNECTION || '').trim()) {
    // [C1 2026-08-21] API_TOOLS_ID HAS ONE OWNER: BaseDocEx01, via extract_base_doc.
    // This gate used to return 'get_api_tools_id' -- a SECOND uploader reachable only from the
    // per-type stage. It is vestigial: 3 dispatches ever, none since 2026-08-17, because base
    // extraction now sets the id before a document can get here. Reaching per-type with a real
    // LINK and no id means base extraction did not produce one, and per-type cannot run without
    // it -- so the row goes BACK to the owner rather than to a parallel path. That terminates:
    // base extraction either sets the id or marks the row EXTRACTION_FAILED with its own reason
    // ('unextractable: no field extracted and no upload id').
    if (isBlank(doc.API_TOOLS_ID) && String(doc.API_TOOLS_ID_COMPLETED == null ? '' : doc.API_TOOLS_ID_COMPLETED).trim().toLowerCase() !== 'true') {
      // [restart_base ping-pong 2026-08-25] base's extract gate accepts only TYPE-less docs
      // (value+flag rule, 2026-08-17), so a TYPED doc sent 'back to the owner' bounces between
      // this gate and base forever -- measured tonight: 19 docs at 118 restart_base/hour each.
      // For typed docs the lane owns the verdict: park visibly as API_TOOLS_FAILED; manual
      // re-extraction stays the documented recipe (blank TYPE + ACTION_RESTART).
      if (doc.TYPE) return doc.STATUS !== 'API_TOOLS_FAILED' ? 'update_status_api_tools_failed' : 'no_action_api_tools_failed';
      return 'restart_base';
    }

    // [terminal guard 2026-08-09] STATUS!=='COMPLETED', the guard 'Decide BS Action'
    // already carries and 'Decide GDoc Action' now does: PER_TYPE_EXTRACTION_COMPLETED
    // landed after the corpus was processed (NULL on 6742 of 7381 live rows), so without
    // it a settled shipment is re-opened for extraction on every sweep and never reaches
    // no_action_already_completed. Subtracts firings only; never adds one.
    if (__needsPerType(doc))
      return 'extract_per_type';

    // [two-point completion 2026-08-11] TERMINAL GUARD ON THE SINGLE-VALUE GATES.
    // This block had no STATUS check, so a document that is already COMPLETED re-entered the
    // legacy per-field extractors on EVERY sweep and could never fall through to
    // gdocTail -> no_action_already_completed. Measured live over the 45 minutes to
    // 2026-08-10 22:55Z: of the documents dispatching 'Doc Total Amount', 8 of 19 carried
    // STATUS = 'COMPLETED' -- settled shipments paying for a second OCR pass forever.
    // This is the SAME guard, for the SAME reason, that 'extract_per_type' above already
    // carries ("without it a settled shipment is re-opened for extraction on every sweep and
    // never reaches no_action_already_completed") and that gdocTail carries on
    // select_invoice_values. Re-extracting settled documents stays a deliberate, gated
    // backfill -- not a side effect of the state machine sweeping. Subtracts firings only;
    // it can never add one.
    if (doc.API_TOOLS_ID && doc.STATUS !== 'COMPLETED') {
      // [two-point 2026-08-10] query_invoice_id REMOVED FROM THE SHIPMENT GATE.
      // Not a fallback that was being reached because extraction failed -- a gate for a
      // field this TYPE does not own, copied here when shipment was forked out of the
      // invoice control flow. It could never be satisfied by extraction and therefore
      // fired on every shipment forever:
      //   * the per-type extraction contract has no invoice id for this type --
      //     settings q_v3_routing.shipment is {DOC_DATE, PURCHASE_ID, SHIPMENT_ID,
      //     DOC_TOTAL_AMOUNT}, and ShipmentDocEx01/'Build Local Result' files the
      //     shipment's OWN number under LOCAL_DOC_ID (from q_v3_shipment_id).
      //   * the per-type extractor's 'Select' [gap-2] is deliberately !isShipment for the same
      //     reason: a shipment's own id is not an invoice number, so it must never be
      //     written into INVOICE_ID.
      //   * ROUTERS-ARCHITECTURE.md §4 lists no invoice-id step for router_shipment,
      //     and the sibling copy of shipmentDecide in indoxV2ActionsGDoc01 does not
      //     carry this line either -- this copy had drifted.
      //   * nothing consumes it: 'Selection & Scoring Logic1' reads DOC_ID /
      //     AI_DOC_ID / INV_ID_FOR_SHIP, the Priority payload ('Map Request') has no
      //     INVOICE_ID field, and invoice->shipment linking writes INV_ID_FOR_SHIP.
      // Measured before removal: 2339 shipments carried INVOICE_ID_COMPLETED and 2074
      // of them (89%) came back blank -- a full second OCR pass per shipment for a
      // column no consumer reads. The shipment's own id is already covered upstream
      // (DOC_ID + SHIPMENT_DOC_ID via [gap-1]), so no work is lost.
    }

    // [two-point completion 2026-08-11] SAME TERMINAL GUARD FOR THE AI FALLBACK.
    // Unguarded, a COMPLETED document with a null AI_EXTRACTION_COMPLETED returned
    // extract_invoice_google_ai on every single sweep, forever -- it is the last statement
    // in this block, so there was no path past it. Simulated against the 25 documents that
    // actually re-dispatched a single-value action in the 45 minutes to 2026-08-10 22:55Z,
    // this line was the verdict for 7 of them. Documents still flowing through are
    // unaffected: they reach per-type extraction first (__needsPerType), which posts to the
    // very same invoice_extractor webhook and now stamps AI_EXTRACTION_COMPLETED itself.
    // [two-point rule 2026-08-17, owner order] standalone extract_invoice_google_ai fallback
    // REMOVED: per-type extraction posts to the same invoice_extractor webhook and stamps
    // AI_EXTRACTION_COMPLETED itself; a field point 2 did not produce stays ABSENT.
  }

  // Resolve the doc number (works with OR without a link).
  if (!doc.DOC_ID) {
    const resolvedId = doc.SHIPMENT_DOC_ID || parseAiShipmentIds(doc.AI_SHIPMENT_IDS)?.[0] || null;
    if (resolvedId) {
      doc.NEW_DOC_ID = resolvedId;
      return 'update_company_doc_id';
    }
  }

  // A linkless shipment must have ATTEMPTED a Drive search before select/sync.
  if (linkMissing && String(doc.SEARCH_IN_DRIVE_COMPLETED == null ? '' : doc.SEARCH_IN_DRIVE_COMPLETED).trim().toLowerCase() !== 'true') {
    if (doc.SHORT_DOC_ID && doc.COMPANY_NAME) return 'find_link';
    return 'no_action_link_not_found';
  }

  return gdocTail(doc);
}


function gdocDecide(doc){
  // This lane decides SHIPMENT only. INVOICE has its own lane (indoxV2ActionsInv01) and ORDER /
  // RECEIPT are parked classes with one-action routers; a document of another type reaching here
  // is a routing defect and must fail loudly rather than run a stale copy of another lane's ladder
  // (the dormant invoiceDecide/orderDecide copies this file carried were removed 2026-09-02).
  const t = String(doc.TYPE || '').toUpperCase();
  if (t && t !== 'SHIPMENT') throw new Error('indoxV2ActionsShip01: TYPE ' + t + ' has its own lane and must not route here [terminal]');
  return shipmentDecide(doc);
}

return __items.map(item => {
  const d = item.json;
  for (const k of Object.keys(d)) {              // supabase TEXT-boolean safety
    if (typeof d[k] === 'string') {
      const s = d[k].trim().toLowerCase();
      if (s === 'true') d[k] = true; else if (s === 'false') d[k] = false;
    }
  }
  d.ACTION = __terminalGuard(d) || shipmentDecide(d);   // router_shipment: shipment flow only
  d.DOC_TYPE = 'shipment';
  delete d.mode;                                 // clean handoff (execute call must not re-decide)
  return item;
});

}
const __mode = String((($input.first()||{}).json||{}).mode || '');
if (__mode === 'export_decide') return [{ json: { fnSrc: __shipDecideFn.toString() } }];
return __shipDecideFn($input.all());`,
    };

    @node({
        id: 'gdocroutemode01',
        name: 'Route Mode',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [2832, 6384],
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
        id: '525af5e0-385f-4e77-a4a3-eb40e5f90451',
        name: 'Stop and Error - Unhandled ACTION',
        type: 'n8n-nodes-base.stopAndError',
        version: 1,
        position: [3504, 6512],
    })
    StopAndErrorUnhandledAction = {
        errorMessage:
            "=Unhandled ACTION '{{ $json.ACTION }}' in indoxV2ActionsShip01.json — '3a. GDOC Action Switch1' matched no case and no explicit fallback. Document ID: {{ $json.ID }}. This item would otherwise have been silently dropped (G41).",
    };

    @node({
        id: 'extract-per-type-entry-01',
        name: 'Action: Extract Per Type',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [3504, 6704],
    })
    ActionExtractPerType = {};

    @node({
        id: 'select-pertype-upsert-01',
        name: 'Upsert (central) - Per Type',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [4176, 6704],
    })
    UpsertCentralPerType = {
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
        id: 'call-typedocex01-01',
        name: 'Call ShipmentDocEx01',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [3728, 6704],
        onError: 'continueRegularOutput',
    })
    CallShipmentdocex01 = {
        workflowId: {
            __rl: true,
            value: 'ShipmentDocEx01',
            mode: 'list',
            cachedResultUrl: '/workflow/ShipmentDocEx01',
            cachedResultName: 'Shipment Document Extraction (local + AI, parallel)',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                ID: '={{ $json.ID }}',
                API_TOOLS_ID: '={{ $json.API_TOOLS_ID }}',
                LINK: '={{ $json.LINK }}',
                LINK_CONNECTION: '={{ $json.LINK_CONNECTION }}',
                TYPE: '={{ $json.TYPE }}',
                INVOICE_ID: '={{ $json.INVOICE_ID }}',
                DOC_ID: '={{ $json.DOC_ID }}',
                SHIPMENT_DOC_ID: '={{ $json.SHIPMENT_DOC_ID }}',
                LINKED_INVOICE_ID: '={{ $json.LINKED_INVOICE_ID }}',
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
                {
                    id: 'TYPE',
                    displayName: 'TYPE',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                    removed: false,
                },
                {
                    id: 'INVOICE_ID',
                    displayName: 'INVOICE_ID',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                    removed: false,
                },
                {
                    id: 'DOC_ID',
                    displayName: 'DOC_ID',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                    removed: false,
                },
                {
                    id: 'SHIPMENT_DOC_ID',
                    displayName: 'SHIPMENT_DOC_ID',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                    removed: false,
                },
                {
                    id: 'LINKED_INVOICE_ID',
                    displayName: 'LINKED_INVOICE_ID',
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
        id: 'build-pertype-upsert-01',
        name: 'Build Per Type Upsert',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [3952, 6704],
    })
    BuildPerTypeUpsert = {
        assignments: {
            assignments: [
                {
                    id: 'inst-per-type-ship',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
                {
                    id: 'pertype-error-20260819',
                    name: 'ERROR',
                    value: '={{ $json.ERROR || null }}',
                    type: 'string',
                },
                {
                    id: 'unlock-0022-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0073-4000-8000-00000000c0de',
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
        id: 'b1drvrenamebuild01',
        name: 'Build Drive Rename (update_name)',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [4848, 4352],
    })
    BuildDriveRenameUpdateName = {
        jsCode: `// [B1 thin-sync 2026-08-06] update_name now ALSO renames the Drive file itself.
// Under thin sync the processor workflow (SyncProcGDoc0001 'Rename File') never
// runs, so the state machine owns the rename. Ordering: the NAME-column lane
// ('Build: Update NAME' at [10128,4320] -> Upsert (central)) is scheduled first
// under executionOrder v1 (smaller x at equal y), so a failed rename can never
// block the column update.
// Idempotent: update_name only fires while NAME != COMPANY_NAME-SHORT_DOC_ID,
// and renaming a file to its current name is a harmless no-op.
//
// [ext-parity 2026-08-07] THE FILE KEEPS ITS EXTENSION; THE COLUMN DOES NOT.
// v1 named the file \`<company>-<docid>.<ext>\` (SyncProcGDoc0001 'Filename' node:
// \`... .{{ $('Loop Over Items').first().json.name.split(".").last() }}\`). This
// node dropped it, and 8 real client files in the synced folder were renamed
// extension-less before it was caught. Restored here, under two rules that are
// NOT interchangeable:
//   FILE   gets \`.<ext>\` - what the operator sees in Drive; v1 parity.
//   COLUMN stays bare    - 'Decide' dispatches update_name while
//                          NAME != COMPANY_NAME-SHORT_DOC_ID. An extension in
//                          the column could never satisfy that comparison, so
//                          update_name would re-fire every sweep, forever.
//                          Measured on the live table: 2405 of 2580 COMPLETED
//                          drive rows already carry no extension in NAME.
//                          'Build: Update NAME' is therefore left untouched.
// SOURCE OF THE EXTENSION is d.NAME, which on the single pass where update_name
// fires is still the source filename: 'Build: Update NAME' is
// includeOtherFields:false and reads $('Action: Update NAME').item, so it never
// mutates this lane's item.
// THE REGEX IS DELIBERATELY STRICTER THAN v1's split('.').last(). Company names
// contain dots: on the live row \`סימנט אי.אס.-12012\` that v1 expression returns
// '-12012', which would be appended as an "extension". Anchoring to a trailing
// run of alphanumerics refuses that and every case shaped like it.
// NO EXTENSION FOUND => no suffix, i.e. exactly today's behaviour. This node can
// add a correct extension; it can never invent a wrong one.
//
// [rename-scope 2026-08-07] WHICH ROWS THIS MAY RENAME.
// Was \`SOURCE_TYPE === 'GOOGLE_DRIVE_FOLDER'\`, which is narrower than the set of
// rows that have a renameable Drive file. Live SOURCE_TYPE values that do:
// GOOGLE_DRIVE_FOLDER (3541), GMAIL (2316, the legacy proc gmail rows),
// GOOGLE_DRIVE_FILE (183), MAIL_ATTACHMENT (92, the thin gmail rows) — all of
// them point at a file in a drive backend, because the gmail lanes UPLOAD the
// attachment to Drive before recording it. \`source_type\` is registry-settable per
// pipe, so this is a shape test, not a fixed list.
// THE FILE ID IS NOW HOST-AGNOSTIC. The old pattern required \`drive.google.com\`,
// but a thin gmail row's LINK is \`http://drive.localhost/file/d/<id>/view\` (the
// local drive backend) — so the previous node would have refused every one of
// them even with the guard widened. The \`/file/d/<id>\` path segment is what
// identifies the file on both backends.
// IDENTITY IS THE REMAINING GATE, AND IT IS DELIBERATE. For a drive-sourced row
// LINK_CONNECTION *is* the Drive connection. For a mail-sourced row LINK_CONNECTION is the
// MAILBOX (syncV3Deliver0001 'Gmail Row' writes \`j.connection\`), while the
// uploaded copy lives under the pipe's \`drive_profile_id\` / \`drive_connection_id\`
// — which no column carries. Handing driveApi01 a mailbox id as \`connection_id\`
// would address the wrong backend, so a mail-sourced row is skipped here rather
// than renamed against the wrong account. Ineligible docs emit NO item, so the
// driveApi01 call does not run at all for them.
const EXT_RE = /\\.([A-Za-z0-9]{1,5})$/;
const FILE_ID_RE = /\\/(?:file\\/d\\/|open\\?id=|uc\\?id=)([A-Za-z0-9_-]{20,})/;
const RENAMEABLE = /^(GOOGLE_DRIVE_FOLDER|GOOGLE_DRIVE_FILE|GMAIL|GMAIL_ATTACHMENT|GMAIL_LINK|MAIL_ATTACHMENT|MAIL_LINK)$/;
const out = [];
for (const it of $input.all()) {
  const d = it.json || {};
  const st = String(d.SOURCE_TYPE || '').toUpperCase();
  if (!RENAMEABLE.test(st)) continue;
  const m = String(d.LINK || '').match(FILE_ID_RE);
  if (!m) continue;
  // Only a drive-sourced row's LINK_CONNECTION addresses a drive backend (see above).
  const driveIdentity = st.indexOf('GOOGLE_DRIVE_') === 0 ? (d.LINK_CONNECTION || null) : null;
  if (!driveIdentity) continue;
  // EXACTLY the value 'Build: Update NAME' writes to the NAME column (fallback
  // strings included, both now 'unknown' — the column writer used to say
  // 'unknwon' while 'Decide' compares against 'unknown', so a doc that ever
  // reached update_name without a company or a short id could never converge and
  // would re-fire update_name on every sweep. No live row has hit it (0 rows named
  // 'unknown-unknwon', max update_name count across the table is 1), so this closes
  // a latent loop rather than an active one.
  const base = (d.COMPANY_NAME || 'unknown') + '-' + (d.SHORT_DOC_ID || 'unknown');
  const em = String(d.NAME || '').match(EXT_RE);
  const ext = em ? em[1] : '';
  const named = (ext && !base.toLowerCase().endsWith('.' + ext.toLowerCase()))
    ? base + '.' + ext
    : base;
  out.push({ json: {
    ID: d.ID,
    RENAME_FILE_ID: m[1],
    RENAME_NEW_NAME: named,
    RENAME_CONNECTION_ID: driveIdentity
  } });
}
return out;`,
    };

    @node({
        id: 'b1drvrenamecall01',
        name: 'Drive Rename (update_name)',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [5072, 4352],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
        retryOnFail: true,
        waitBetweenTries: 5000,
    })
    DriveRenameUpdateName = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'update',
                params: '={{ ({ fileId: $json.RENAME_FILE_ID, newName: $json.RENAME_NEW_NAME, connection_id: $json.RENAME_CONNECTION_ID }) }}',
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
        id: 'dedupe-docs-execute-01',
        name: 'Dedupe Docs (execute)',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3056, 6480],
    })
    DedupeDocsExecute = {
        jsCode: `
// [batch dedupe 2026-08-10] ONE DOCUMENT, ONE ACTION, PER DISPATCH.
// The action batch arriving here carries the same document id repeatedly, and every copy runs
// the full action -- for extract_base_doc that is a complete OCR + Gemini pass each time.
// Measured on the live table before this landed: 2,424 'Extract Base Doc' markers in 60 minutes
// from 92 executions over 188 documents (~26 per execution), and 88% of consecutive markers on
// one document less than 10 seconds apart. Hour 16 ran 19.2 base extractions per distinct
// document, hour 12 ran 80.4. That repetition -- not the state machine's gates -- is what was
// consuming the dispatch budget, which is why documents whose next step is a free table lookup
// (680 of today's intake sit at get_company_name with the gate OPEN and the flag unset) were
// never reached.
// DECIDE MODE IS DELIBERATELY UNTOUCHED: the caller pairs decide's output with its input
// item-for-item, so dropping items there would re-attribute verdicts between documents -- the
// same class of defect the per-type pairing guard refuses to guess about.
// First occurrence wins; a duplicate carrying a different ACTION is not lost, it is simply
// taken on the next sweep.
const __all = $('When Called').all();
const __mode = String((__all[0] && __all[0].json && __all[0].json.mode) || '');
if (__mode === 'decide') return __all;
const __seen = new Set();
const __out = [];
for (const __it of __all) {
  const __id = (__it && __it.json && __it.json.ID != null) ? String(__it.json.ID) : '';
  if (__id !== '') { if (__seen.has(__id)) continue; __seen.add(__id); }
  __out.push(__it);
}
return __out;
`,
    };

    @node({
        id: 'seltype-action-01',
        name: 'Action: Select Type',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [4176, 8288],
    })
    ActionSelectType = {};

    @node({
        id: 'seltype-loop-01',
        name: 'Loop (select type)',
        /*__n8n__*/ notes: "batchSize 200: selection is pure computation over columns already on the row, so unlike extraction there is no per-document cost to walk one at a time for. The reset expression is the standard guard against a finished batcher sending a fresh feed straight to Done.",
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [4400, 8288],
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
        position: [4624, 8240],
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
        id: 'seltype-build-01',
        name: 'Build Select Type Upsert',
        /*__n8n__*/ notes: "The selector's answer as-is, plus the two control keys the API strips. Fields it declined to decide are absent, and indoxApi01's clean() drops absent keys, so 'no answer' leaves the column untouched rather than blanking it.",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [4832, 8240],
    })
    BuildSelectTypeUpsert = {
        assignments: {
            assignments: [
                {
                    id: 'inst-select-type-ship',
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

    @node({
        id: '0221d329-f00f-4708-9760-09e96da9b571',
        name: 'Loop Over Items20',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [4624, 6016],
    })
    LoopOverItems20 = {
        batchSize: 100,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenCalled.out(0).to(this.RouteMode.in(0));
        this.LoopOverItems15.out(1).to(this.BuildUpdateName.in(0));
        this.LoopOverItems15.out(1).to(this.BuildDriveRenameUpdateName.in(0));
        this.LoopOverItems15.out(1).to(this.LoopOverItems15.in(0));
        this.LoopOverItems11.out(1).to(this.BuildRestartClearCompletedFlags.in(0));
        this.LoopOverItems11.out(1).to(this.LoopOverItems11.in(0));
        this.LoopOverItems6.out(1).to(this.BuildCallIncomingDocumentBatchUpdateStatusCompleted.in(0));
        this.LoopOverItems6.out(1).to(this.LoopOverItems6.in(0));
        this.ActionMarkCompleted.out(0).to(this.LoopOverItems6.in(0));
        this.ActionGetShortDocId1.out(0).to(this.LoopOverItems5.in(0));
        this.MapRequest.out(0).to(this.PostPriorityTable.in(0));
        this._3aGdocActionSwitch1.out(0).to(this.ActionUpdateName.in(0));
        this._3aGdocActionSwitch1.out(1).to(this.ActionRestartGdoc.in(0));
        this._3aGdocActionSwitch1.out(4).to(this.ActionGetShortDocId1.in(0));
        this._3aGdocActionSwitch1.out(5).to(this.ActionFindLinkInDrive.in(0));
        this._3aGdocActionSwitch1.out(6).to(this.ActionUpdateStatusMissingLink.in(0));
        this._3aGdocActionSwitch1.out(9).to(this.ActionUpdateStatusApiToolsIdFailed.in(0));
        this._3aGdocActionSwitch1.out(11).to(this.ActionCheckFromOffice1.in(0));
        this._3aGdocActionSwitch1.out(18).to(this.ActionPrioritySync.in(0));
        this._3aGdocActionSwitch1.out(20).to(this.ActionRestartPrioritySync.in(0));
        this._3aGdocActionSwitch1.out(21).to(this.ActionMarkCompleted.in(0));
        this._3aGdocActionSwitch1.out(22).to(this.ActionUpdateDocId.in(0));
        this._3aGdocActionSwitch1.out(24).to(this.StopAndErrorUnhandledAction.in(0));
        this._3aGdocActionSwitch1.out(25).to(this.ActionExtractPerType.in(0));
        this._3aGdocActionSwitch1.out(28).to(this.ActionSelectType.in(0));
        this.ActionSelectType.out(0).to(this.LoopSelectType.in(0));
        this.LoopSelectType.out(1).to(this.CallSelecttype01.in(0));
        this.LoopSelectType.out(1).to(this.LoopSelectType.in(0));
        this.CallSelecttype01.out(0).to(this.BuildSelectTypeUpsert.in(0));
        this.BuildSelectTypeUpsert.out(0).to(this.UpsertCentral.in(0));
        this.ActionRestartGdoc.out(0).to(this.LoopOverItems11.in(0));
        this.ActionUpdateStatusMissingLink.out(0).to(this.LoopOverItems.in(0));
        this.ActionUpdateName.out(0).to(this.LoopOverItems15.in(0));
        this.ActionFindLinkInDrive.out(0).to(this.LoopOverItems2.in(0));
        this.LoopOverItems35.out(1).to(this.BuildCallIncomingDocumentBatchUpdate4.in(0));
        this.LoopOverItems35.out(1).to(this.LoopOverItems35.in(0));
        this.ActionPrioritySync.out(0).to(this.LoopOverItems30.in(0));
        this.LoopOverItems5.out(1).to(this.BuildCallIncomingDocumentBatchUpdate1.in(0));
        this.LoopOverItems5.out(1).to(this.LoopOverItems5.in(0));
        this.LoopOverItems30.out(1).to(this.LoopOverItems30.in(0));
        this.LoopOverItems30.out(1).to(this.MapRequest.in(0));
        this.LoopOverItems1.out(1).to(this.CallSearchFromWaerhouse.in(0));
        this.LoopOverItems1.out(1).to(this.LoopOverItems1.in(0));
        this.CallSearchFile.out(0).to(this.IfFoundFile1.in(0));
        this.ActionUpdateDocId.out(0).to(this.LoopOverItems35.in(0));
        this.PostPriorityTable.out(0).to(this.BuildBatchUpdatePrioritySync.in(0));
        this.RestoreDocsFromOffice.out(0).to(this.LoopOverItems1.in(0));
        this.ActionUpdateStatusApiToolsIdFailed.out(0).to(this.LoopOverItems20.in(0));
        this.LoopOverItems.out(1).to(this.BuildCallIncomingDocumentBatchUpdateStatusMissingLink.in(0));
        this.LoopOverItems.out(1).to(this.LoopOverItems.in(0));
        this.LoopOverItems2.out(1).to(this.CallSearchFile.in(0));
        this.LoopOverItems2.out(1).to(this.LoopOverItems2.in(0));
        this.LoopOverItems20.out(1).to(this.BuildCallIncomingDocumentBatchUpdateStatusApiToolsFailed1.in(0));
        this.LoopOverItems20.out(1).to(this.LoopOverItems20.in(0));
        this.GetWarehouseSetting.out(0).to(this.RestoreDocsFromOffice.in(0));
        this.ActionCheckFromOffice1.out(0).to(this.WhReqSettings.in(0));
        this.WhReqSettings.out(0).to(this.GetWarehouseSetting.in(0));
        this.IfFoundFile1.out(0).to(this.BuildCallIncomingDocumentBatchUpdateLinkFound.in(0));
        this.IfFoundFile1.out(1).to(this.BuildCallIncomingDocumentBatchUpdateSearchInDriveCompleted.in(0));
        this.CallSearchFromWaerhouse.out(0).to(this.BuildCallIncomingDocumentBatchUpdateFromOffice.in(0));
        this.BuildCallIncomingDocumentBatchUpdateStatusMissingLink.out(0).to(this.UpsertCentral.in(0));
        this.BuildCallIncomingDocumentBatchUpdateSearchInDriveCompleted.out(0).to(this.UpsertCentral.in(0));
        this.BuildBatchUpdatePrioritySync.out(0).to(this.UpsertCentral.in(0));
        this.BuildCallIncomingDocumentBatchUpdateStatusCompleted.out(0).to(this.UpsertCentral.in(0));
        this.BuildUpdateName.out(0).to(this.UpsertCentral.in(0));
        this.BuildCallIncomingDocumentBatchUpdateStatusApiToolsFailed1.out(0).to(this.UpsertCentral.in(0));
        this.BuildRestartClearCompletedFlags.out(0).to(this.UpsertCentral.in(0));
        this.BuildCallIncomingDocumentBatchUpdate4.out(0).to(this.UpsertCentral.in(0));
        this.BuildCallIncomingDocumentBatchUpdate1.out(0).to(this.UpsertCentral.in(0));
        this.BuildCallIncomingDocumentBatchUpdateFromOffice.out(0).to(this.UpsertCentral.in(0));
        this.BuildCallIncomingDocumentBatchUpdateLinkFound.out(0).to(this.UpsertCentral.in(0));
        this.RouteMode.out(0).to(this.DecideShipmentAction.in(0));
        this.RouteMode.out(1).to(this.DedupeDocsExecute.in(0));
        this.ActionExtractPerType.out(0).to(this.CallShipmentdocex01.in(0));
        this.BuildPerTypeUpsert.out(0).to(this.UpsertCentralPerType.in(0));
        this.CallShipmentdocex01.out(0).to(this.BuildPerTypeUpsert.in(0));
        this.BuildDriveRenameUpdateName.out(0).to(this.DriveRenameUpdateName.in(0));
        this.DedupeDocsExecute.out(0).to(this._3aGdocActionSwitch1.in(0));
        this.ActionRestartPrioritySync.out(0).to(this.BuildBatchUpdateRestartPrioritySync.in(0));
        this.BuildBatchUpdateRestartPrioritySync.out(0).to(this.UpsertCentral.in(0));
    }
}
