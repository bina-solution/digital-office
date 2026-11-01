import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox-v2 Actions — DOC BASE
// Nodes   : 64  |  Connections: 86
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// ActionUpdateStatusUnknownCompany   noOp
// ActionRestartBase                  noOp
// BuildRestartClearCompletedFlags    code
// LoopStatusOld                      splitInBatches
// LoopHandleDoubles                  splitInBatches
// ActionUpdateStatusMissingCompanyId noOp
// ActionGetCompanyName               noOp
// DocBaseActionSwitch                switch
// Companies                          executeWorkflow            [executeOnce]
// ActionUpdateStatusMissingType      noOp
// LoopCompanyName                    splitInBatches
// ActionUpdateStatusOld              noOp
// ActionHandleDoubles                noOp
// LoopMissingType                    splitInBatches
// JoinCompanyName                    code
// LoopMissingCompany                 splitInBatches
// WhenCalled                         executeWorkflowTrigger
// BuildMarkMaxIterations             set
// BuildStatusOldCompleted            set
// BuildStatusUnknownCompany          set
// BuildStatusMissingCompanyId        set
// BuildStatusMissingType             set
// BuildCompanyName                   set
// BuildStatusMissingCompanyIdDoubles set
// UpsertCentral                      executeWorkflow
// DecideDocBaseAction                code
// RouteMode                          switch
// StopAndErrorUnhandledDocBaseAction stopAndError
// ActionExtractBaseDoc               noOp
// CallBasedocex01                    executeWorkflow            [onError→regular]
// BuildBaseDocUpsert                 set
// ActionResolveDouble                noOp
// BuildGroupFetch                    code
// FetchGroup                         executeWorkflow            [alwaysOutput] [retry]
// AdjudicateMerge                    code
// MergeOrUpdate                      if
// CallMerge                          executeWorkflow            [retry]
// ActionUpdateStatusGarbage          noOp
// LoopGarbage                        splitInBatches
// BuildStatusGarbage                 set
// ActionSourceFeedback               noOp
// RegistryReqFeedback                code
// GetRegistryFeedback                executeWorkflow            [onError→regular] [alwaysOutput]
// TagRulesReqFeedback                code
// GetTagRulesFeedback                executeWorkflow            [onError→regular] [alwaysOutput]
// LinesReqFeedback                   code
// GetLinesFeedback                   executeWorkflow            [onError→regular] [alwaysOutput]
// BuildFeedbackOps                   code
// LoopFeedback                       splitInBatches
// RouteFeedbackOp                    switch
// MoveToFeedbackFolder               executeWorkflow            [onError→regular] [alwaysOutput] [retry]
// ApplyFeedbackLabel                 executeWorkflow            [onError→regular] [alwaysOutput] [retry]
// BuildSourceFeedback                code
// SelectBaseValues                   code
// LoopBaseDoc                        splitInBatches
// BaseDocProducedAnAnswer            if
// UpsertCentralBaseDoc               executeWorkflow            [onError→regular] [alwaysOutput]
// RecordBaseDocFailure               postgres                   [onError→regular] [creds] [alwaysOutput]
// LoadCompanyResolverGen             postgres                   [onError→regular] [creds] [alwaysOutput] [executeOnce]
// RestoreRouterPayload               code
// ActionSelectBase                   noOp
// LoopSelectBase                     splitInBatches
// CallSelectbase01                   executeWorkflow            [onError→regular]
// BuildSelectBaseUpsert              set
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → LoadCompanyResolverGen
//      → RestoreRouterPayload
//        → RouteMode
//          → DecideDocBaseAction
//         .out(1) → DocBaseActionSwitch
//            → ActionRestartBase
//              → BuildRestartClearCompletedFlags
//                → UpsertCentral
//           .out(1) → ActionHandleDoubles
//              → LoopHandleDoubles
//               .out(1) → LoopHandleDoubles (↩ loop)
//               .out(1) → BuildStatusMissingCompanyIdDoubles
//                  → UpsertCentral (↩ loop)
//           .out(2) → ActionResolveDouble
//              → BuildGroupFetch
//                → FetchGroup
//                  → AdjudicateMerge
//                    → MergeOrUpdate
//                      → CallMerge
//                     .out(1) → UpsertCentral (↩ loop)
//           .out(3) → ActionUpdateStatusMissingCompanyId
//              → LoopMissingCompany
//               .out(1) → LoopMissingCompany (↩ loop)
//               .out(1) → BuildStatusMissingCompanyId
//                  → UpsertCentral (↩ loop)
//           .out(4) → ActionGetCompanyName
//              → Companies
//              → JoinCompanyName
//                → LoopCompanyName
//                 .out(1) → BuildCompanyName
//                    → UpsertCentral (↩ loop)
//                 .out(1) → LoopCompanyName (↩ loop)
//           .out(5) → ActionUpdateStatusUnknownCompany
//              → BuildStatusUnknownCompany
//                → UpsertCentral (↩ loop)
//           .out(6) → ActionUpdateStatusMissingType
//              → LoopMissingType
//               .out(1) → LoopMissingType (↩ loop)
//               .out(1) → BuildStatusMissingType
//                  → UpsertCentral (↩ loop)
//           .out(7) → ActionUpdateStatusOld
//              → LoopStatusOld
//               .out(1) → LoopStatusOld (↩ loop)
//               .out(1) → BuildStatusOldCompleted
//                  → UpsertCentral (↩ loop)
//           .out(8) → BuildMarkMaxIterations
//              → UpsertCentral (↩ loop)
//           .out(9) → ActionExtractBaseDoc
//              → LoopBaseDoc
//               .out(1) → CallBasedocex01
//                  → SelectBaseValues
//                    → BaseDocProducedAnAnswer
//                      → BuildBaseDocUpsert
//                        → UpsertCentralBaseDoc
//                          → LoopBaseDoc (↩ loop)
//                     .out(1) → RecordBaseDocFailure
//                        → LoopBaseDoc (↩ loop)
//           .out(10) → ActionUpdateStatusGarbage
//              → LoopGarbage
//               .out(1) → LoopGarbage (↩ loop)
//               .out(1) → BuildStatusGarbage
//                  → UpsertCentral (↩ loop)
//           .out(11) → ActionSourceFeedback
//              → RegistryReqFeedback
//                → GetRegistryFeedback
//                  → TagRulesReqFeedback
//                    → GetTagRulesFeedback
//                      → LinesReqFeedback
//                        → GetLinesFeedback
//                          → BuildFeedbackOps
//                            → LoopFeedback
//                             .out(1) → RouteFeedbackOp
//                                → MoveToFeedbackFolder
//                                  → BuildSourceFeedback
//                                    → UpsertCentral (↩ loop)
//                               .out(1) → ApplyFeedbackLabel
//                                  → BuildSourceFeedback (↩ loop)
//                               .out(2) → BuildSourceFeedback (↩ loop)
//                             .out(1) → LoopFeedback (↩ loop)
//           .out(12) → StopAndErrorUnhandledDocBaseAction
//           .out(13) → ActionSelectBase
//              → LoopSelectBase
//               .out(1) → CallSelectbase01
//                  → BuildSelectBaseUpsert
//                    → UpsertCentral (↩ loop)
//               .out(1) → LoopSelectBase (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"Load Company Resolver Gen","type":"main","index":0}]]},"Action: Update Status UNKNOWN_COMPANY":{"main":[[{"node":"Build: Status UNKNOWN_COMPANY","type":"main","index":0}]]},"Loop (status old)":{"main":[[],[{"node":"Loop (status old)","type":"main","index":0},{"node":"Build: Status OLD / COMPLETED","type":"main","index":0}]]},"Loop (handle doubles)":{"main":[[],[{"node":"Loop (handle doubles)","type":"main","index":0},{"node":"Build: Status MISSING_COMPANY_ID (doubles)","type":"main","index":0}]]},"Action: Update Status MISSING_COMPANY_ID":{"main":[[{"node":"Loop (missing company)","type":"main","index":0}]]},"Action: Get Company Name":{"main":[[{"node":"Companies","type":"main","index":0},{"node":"Join COMPANY_NAME","type":"main","index":0}]]},"DOC BASE Action Switch":{"main":[[{"node":"Action: Restart Base","type":"main","index":0}],[{"node":"Action: Handle Doubles","type":"main","index":0}],[{"node":"Action: Resolve Double","type":"main","index":0}],[{"node":"Action: Update Status MISSING_COMPANY_ID","type":"main","index":0}],[{"node":"Action: Get Company Name","type":"main","index":0}],[{"node":"Action: Update Status UNKNOWN_COMPANY","type":"main","index":0}],[{"node":"Action: Update Status MISSING_TYPE","type":"main","index":0}],[{"node":"Action: Update Status OLD","type":"main","index":0}],[{"node":"Build: Mark MAX_ITERATIONS","type":"main","index":0}],[{"node":"Action: Extract Base Doc","type":"main","index":0}],[{"node":"Action: Update Status GARBAGE","type":"main","index":0}],[{"node":"Action: Source Feedback","type":"main","index":0}],[{"node":"Stop and Error - Unhandled DOC BASE ACTION","type":"main","index":0}],[{"node":"Action: Select Base","type":"main","index":0}]]},"Action: Select Base":{"main":[[{"node":"Loop (select base)","type":"main","index":0}]]},"Loop (select base)":{"main":[[],[{"node":"Call SelectBase01","type":"main","index":0},{"node":"Loop (select base)","type":"main","index":0}]]},"Call SelectBase01":{"main":[[{"node":"Build Select Base Upsert","type":"main","index":0}]]},"Build Select Base Upsert":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Action: Update Status MISSING_TYPE":{"main":[[{"node":"Loop (missing type)","type":"main","index":0}]]},"Loop (company name)":{"main":[[],[{"node":"Build: Company Name","type":"main","index":0},{"node":"Loop (company name)","type":"main","index":0}]]},"Action: Update Status OLD":{"main":[[{"node":"Loop (status old)","type":"main","index":0}]]},"Action: Handle Doubles":{"main":[[{"node":"Loop (handle doubles)","type":"main","index":0}]]},"Loop (missing type)":{"main":[[],[{"node":"Loop (missing type)","type":"main","index":0},{"node":"Build: Status MISSING_TYPE","type":"main","index":0}]]},"Join COMPANY_NAME":{"main":[[{"node":"Loop (company name)","type":"main","index":0}]]},"Loop (missing company)":{"main":[[],[{"node":"Loop (missing company)","type":"main","index":0},{"node":"Build: Status MISSING_COMPANY_ID","type":"main","index":0}]]},"Build: Mark MAX_ITERATIONS":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Status OLD / COMPLETED":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Status UNKNOWN_COMPANY":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Status MISSING_COMPANY_ID":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Status MISSING_TYPE":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Company Name":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Build: Status MISSING_COMPANY_ID (doubles)":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Route Mode":{"main":[[{"node":"Decide DOC BASE Action","type":"main","index":0}],[{"node":"DOC BASE Action Switch","type":"main","index":0}]]},"Action: Extract Base Doc":{"main":[[{"node":"Loop (base doc)","type":"main","index":0}]]},"Call BaseDocEx01":{"main":[[{"node":"Select Base Values","type":"main","index":0}]]},"Build Base Doc Upsert":{"main":[[{"node":"Upsert (central) - Base Doc","type":"main","index":0}]]},"Action: Resolve Double":{"main":[[{"node":"Build Group Fetch","type":"main","index":0}]]},"Build Group Fetch":{"main":[[{"node":"Fetch Group","type":"main","index":0}]]},"Fetch Group":{"main":[[{"node":"Adjudicate Merge","type":"main","index":0}]]},"Adjudicate Merge":{"main":[[{"node":"Merge or Update?","type":"main","index":0}]]},"Merge or Update?":{"main":[[{"node":"Call MERGE","type":"main","index":0}],[{"node":"Upsert (central)","type":"main","index":0}]]},"Action: Update Status GARBAGE":{"main":[[{"node":"Loop (garbage)","type":"main","index":0}]]},"Action: Restart Base":{"main":[[{"node":"Build: Restart (clear completed flags)","type":"main","index":0}]]},"Build: Restart (clear completed flags)":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Loop (garbage)":{"main":[[],[{"node":"Loop (garbage)","type":"main","index":0},{"node":"Build: Status GARBAGE","type":"main","index":0}]]},"Build: Status GARBAGE":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Select Base Values":{"main":[[{"node":"Base Doc Produced An Answer?","type":"main","index":0}]]},"Loop (base doc)":{"main":[[],[{"node":"Call BaseDocEx01","type":"main","index":0},{"node":"Loop (base doc)","type":"main","index":0}]]},"Base Doc Produced An Answer?":{"main":[[{"node":"Build Base Doc Upsert","type":"main","index":0}],[{"node":"Record Base Doc Failure","type":"main","index":0}]]},"Upsert (central) - Base Doc":{"main":[[]]},"Record Base Doc Failure":{"main":[[]]},"Load Company Resolver Gen":{"main":[[{"node":"Restore Router Payload","type":"main","index":0}]]},"Restore Router Payload":{"main":[[{"node":"Route Mode","type":"main","index":0}]]},"Action: Source Feedback":{"main":[[{"node":"Registry Req (Feedback)","type":"main","index":0}]]},"Registry Req (Feedback)":{"main":[[{"node":"Get Registry (Feedback)","type":"main","index":0}]]},"Get Registry (Feedback)":{"main":[[{"node":"Tag Rules Req (Feedback)","type":"main","index":0}]]},"Tag Rules Req (Feedback)":{"main":[[{"node":"Lines Req (Feedback)","type":"main","index":0}]]},"Lines Req (Feedback)":{"main":[[{"node":"Get Lines (Feedback)","type":"main","index":0}]]},"Get Lines (Feedback)":{"main":[[{"node":"Build Feedback Ops","type":"main","index":0}]]},"Build Feedback Ops":{"main":[[{"node":"Loop (feedback)","type":"main","index":0}]]},"Loop (feedback)":{"main":[[],[{"node":"Route Feedback Op","type":"main","index":0},{"node":"Loop (feedback)","type":"main","index":0}]]},"Route Feedback Op":{"main":[[{"node":"Move To Feedback Folder","type":"main","index":0}],[{"node":"Apply Feedback Label","type":"main","index":0}],[{"node":"Build: Source Feedback","type":"main","index":0}]]},"Move To Feedback Folder":{"main":[[{"node":"Build: Source Feedback","type":"main","index":0}]]},"Apply Feedback Label":{"main":[[{"node":"Build: Source Feedback","type":"main","index":0}]]},"Build: Source Feedback":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"1a1f9021-970c-46eb-8cef-4746d2dca0d0","name":"indox-state-machine-v2"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"22f1e71e-91bf-48db-811f-8d3bc4e55a3e","name":"sm-refactor-v2.1"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"2b5cb873-dd65-44dd-bf27-a2c99d2b81a4","name":"state-machine-v2"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:41:29.646Z","createdAt":"2026-07-30T23:41:29.646Z","id":"9c337cfe-7feb-4f3d-ab26-3de6439357ce","name":"sm-refactore-v2.1"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"b481a46d-6a18-4fdc-9eb5-c2d8ed3a639a","name":"role:action"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {"templateCredsSetupCompleted":true},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"indoxV2ActionsGlobal01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2ActionsGlobal01',
    name: 'indox-v2 Actions — DOC BASE',
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
export class IndoxV2ActionsDocBaseWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'c167ceb8-8f99-4226-b1e7-92f8aa2c9bb0',
        name: 'Action: Update Status UNKNOWN_COMPANY',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-400, 896],
    })
    ActionUpdateStatusUnknownCompany = {};

    @node({
        id: 'action-restart-base-0001-000000000001',
        name: 'Action: Restart Base',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-400, 2080],
    })
    ActionRestartBase = {};

    @node({
        id: 'build-restart-base-0001-000000000001',
        name: 'Build: Restart (clear completed flags)',
        /*__n8n__*/ notes: "[dynamic restart 2026-08-17, owner order] Base-stage twin of the typed routers' restart build: clears EVERY *_COMPLETED flag on the row, derived from the row keys at runtime - never a hardcoded list. FROM_OFFICE_CHECK is the one legacy completion flag without the suffix - kept explicitly. STATUS -> IN_PROGRESS, ERROR clears, next sweep re-walks the whole pipeline (base extraction included).",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-144, 2080],
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
  // __instance names the SCHEMA this UPSERT lands in. This node BUILDS a new object, so every
  // field not listed here is dropped and indoxApi01 falls back to public -- i.e. a restart issued
  // for one instance would clear the completed flags on another instance's row of the same ID.
  // Document IDs are per-instance sequences, so that collision is ordinary, not exotic.
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
        id: '2cfb6987-314d-4cef-8966-3f8f8e1e71a1',
        name: 'Loop (status old)',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [-144, 1280],
    })
    LoopStatusOld = {
        batchSize: 5000,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: '33a854a3-f222-43b0-9812-cb2a9f87aee3',
        name: 'Loop (handle doubles)',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [-144, 128],
    })
    LoopHandleDoubles = {
        batchSize: 1000,
        options: {},
    };

    @node({
        id: '70faa9f1-72ce-4471-b3ef-310efa9f8a9f',
        name: 'Action: Update Status MISSING_COMPANY_ID',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-400, 512],
    })
    ActionUpdateStatusMissingCompanyId = {};

    @node({
        id: '7196fbca-5330-4807-9938-80abf2c92185',
        name: 'Action: Get Company Name',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-400, 704],
    })
    ActionGetCompanyName = {};

    @node({
        id: '90ec9279-ab68-4ba0-8d04-8a59c7b592b5',
        name: 'DOC BASE Action Switch',
        type: 'n8n-nodes-base.switch',
        version: 2,
        position: [-880, 1200],
    })
    DocBaseActionSwitch = {
        dataType: 'string',
        value1: '={{ String($json.ACTION || "").startsWith("source_feedback_") ? "source_feedback" : (String($json.ACTION || "") === "action_merge_doubles" ? "resolve_double" : $json.ACTION) }}',
        rules: {
            rules: [
                {
                    value2: 'restart_base',
                    outputKey: 'restart_base',
                },
                {
                    value2: 'update_status_double',
                    outputKey: 'update_status_double',
                },
                {
                    value2: 'resolve_double',
                    outputKey: 'resolve_double',
                },
                {
                    value2: 'update_status_missing_company',
                    outputKey: 'update_status_missing_company',
                },
                {
                    value2: 'get_company_name',
                    outputKey: 'get_company_name',
                },
                {
                    value2: 'update_status_unknwon_company',
                    outputKey: 'update_status_unknwon_company',
                },
                {
                    value2: 'update_status_missing_type',
                    outputKey: 'update_status_missing_type',
                },
                {
                    value2: 'update_status_old_doc',
                    outputKey: 'update_status_old_doc',
                },
                {
                    value2: 'mark_max_iterations',
                    outputKey: 'mark_max_iterations',
                },
                {
                    value2: 'extract_base_doc',
                    outputKey: 'extract_base_doc',
                },
                {
                    value2: 'update_status_garbage',
                    outputKey: 'update_status_garbage',
                },
                {
                    value2: 'source_feedback',
                    outputKey: 'source_feedback',
                },
                {
                    value2: '__unhandled_action__',
                    outputKey: 'Unhandled ACTION - Error',
                },
                {
                    value2: 'select_base',
                    outputKey: 'select_base',
                },
            ],
        },
        options: {
            fallbackOutput: 12,
        },
    };

    @node({
        id: '006e7278-548d-4b95-9fe6-c05c69a93f83',
        name: 'Companies',
        /*__n8n__*/ notes: "[settings-driven ageing 2026-08-13] load_settings flipped false -> true.\nThis node is the ONLY source __CFG() reads, and with load_settings:false the value\nold_document_months_back never arrived — so anyOldDate() silently fell back to 24 months while\npublic.settings has held OldDocumentMonthsBack = 6 since 2026-07-30. Measured before the flip:\n9,704 documents in the 6-24 month band, exactly 4 tagged OLD. Owner decision: ageing must be\nsettings-driven at 6 months. Expected effect ~4,913 additional rows aging out — see the node\nnotes on Decide DOC BASE Action for why this must not ship before the date corruption is fixed.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [-144, 640],
        executeOnce: true,
    })
    Companies = {
        workflowId: {
            __rl: true,
            value: 'indoxSettings01',
            mode: 'list',
            cachedResultUrl: '/workflow/indoxSettings01',
            cachedResultName: 'Settings',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                load_settings: true,
                load_companies: true,
                load_queries: true,
                __instance: '={{ $json.__instance || "" }}',
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'load_settings',
                    displayName: 'load_settings',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'boolean',
                },
                {
                    id: 'load_companies',
                    displayName: 'load_companies',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'boolean',
                },
                {
                    id: 'load_queries',
                    displayName: 'load_queries',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'boolean',
                },
                {
                    id: 'TRIGGERED_FROM',
                    displayName: 'TRIGGERED_FROM',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        options: {},
    };

    @node({
        id: 'e05fbf53-c2c0-4302-8df3-c340af0bdbf8',
        name: 'Action: Update Status MISSING_TYPE',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-400, 1088],
    })
    ActionUpdateStatusMissingType = {};

    @node({
        id: '0413a0cc-89c3-4b4b-96ff-c61798dd6a04',
        name: 'Loop (company name)',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [112, 704],
    })
    LoopCompanyName = {
        batchSize: 5000,
        options: {},
    };

    @node({
        id: 'af2d0408-e9c2-4c8d-a86a-91d565bfd8cc',
        name: 'Action: Update Status OLD',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-400, 1280],
    })
    ActionUpdateStatusOld = {};

    @node({
        id: '0b64998b-0c07-445d-8c66-dcef01f7c939',
        name: 'Action: Handle Doubles',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-400, 128],
    })
    ActionHandleDoubles = {};

    @node({
        id: '5daa9e12-88ef-44af-9fa8-cc8a9d98eb84',
        name: 'Loop (missing type)',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [-144, 1088],
    })
    LoopMissingType = {
        batchSize: 1000,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: 'e344903c-e8f6-4c9a-a38a-785155d17bba',
        name: 'Join COMPANY_NAME',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-144, 704],
    })
    JoinCompanyName = {
        jsCode: `// get_company_name: resolve COMPANY_NAME from the settings value or the company map.
// [always-complete 2026-08-17, owner order] EVERY action ALWAYS sets its *_COMPLETED flag:
// a simple join — resolve from settings value or the company map; no answer IS the answer
// (decide terminalizes UNKNOWN_COMPANY next pass). A missing Companies map is a REAL failure
// and fails LOUDLY. No RETRY_COUNT, no backoff, no re-fire: ACTION_RESTART resets the flag
// and is the only re-run.
let map = {};
try { map = ($('Companies').last().json.company_name_by_identifier) || {}; }
catch (e) { throw new Error("get_company_name: Companies map unavailable — failing loudly (owner rule 2026-08-17): " + (e && e.message)); }
for (const item of $input.all()) {
  const cid = item.json.COMPANY_ID;
  const resolved = item.json.COMPANY_NAME;
  item.json.COMPANY_NAME = (resolved != null && resolved !== '') ? resolved
    : (cid != null && cid !== '' && map[cid] != null ? map[cid] : null);
  item.json.COMPANY_NAME_COMPLETED = true;
}
return $input.all();
`,
    };

    @node({
        id: 'e4fc00c0-23c1-41a3-811f-8bd3dbb18f84',
        name: 'Loop (missing company)',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [-144, 512],
    })
    LoopMissingCompany = {
        batchSize: 1000,
        options: {},
    };

    @node({
        id: 'globalv2trig',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [-2080, -16],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'a10c7100-0000-4000-8000-maxiter00001',
        name: 'Build: Mark MAX_ITERATIONS',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [-400, 1472],
    })
    BuildMarkMaxIterations = {
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
                    value: 'MAX_ITERATIONS',
                    type: 'string',
                },
                {
                    id: 'bw3',
                    name: 'ERROR',
                    value: "={{ 'max actions per doc reached' }}",
                    type: 'string',
                },
                {
                    id: 'unlock-0000-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0036-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-0036-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '681c6986-a2f2-423b-9515-66156cfd80d1',
        name: 'Build: Status OLD / COMPLETED',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [112, 1136],
    })
    BuildStatusOldCompleted = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: "={{ $('Action: Update Status OLD').item.json.ID }}",
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'IS_OLD',
                    value: 'TRUE',
                    type: 'string',
                },
                {
                    id: 'bw2',
                    name: 'STATUS',
                    value: 'OLD',
                    type: 'string',
                },
                {
                    id: 'bw3',
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
                    id: 'verb-0037-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-0037-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
                {
                    id: 'old-reason-0001',
                    name: 'OLD_REASON',
                    value: '={{ $json.OLD_REASON || null }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '3cc79214-b982-4b8a-9509-d9bc3c5919e8',
        name: 'Build: Status UNKNOWN_COMPANY',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [-144, 896],
    })
    BuildStatusUnknownCompany = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: "={{ $('Action: Update Status UNKNOWN_COMPANY').item.json.ID }}",
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'STATUS',
                    value: 'UNKNOWN_COMPANY',
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
                    id: 'verb-0038-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-0038-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'aacc7016-e6be-489c-a581-8b960cb1af72',
        name: 'Build: Status MISSING_COMPANY_ID',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [112, 368],
    })
    BuildStatusMissingCompanyId = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: "={{ $('Action: Update Status MISSING_COMPANY_ID').item.json.ID }}",
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
                    id: 'verb-0039-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-0039-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'c1b629b1-5a69-49d7-bafb-b65f468c860c',
        name: 'Build: Status MISSING_TYPE',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [112, 944],
    })
    BuildStatusMissingType = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: "={{ $('Action: Update Status MISSING_TYPE').item.json.ID }}",
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'STATUS',
                    value: 'MISSING_TYPE',
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
                    id: 'verb-0042-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-0042-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'ac8021d5-c890-496b-b30c-8b43a6d43dc3',
        name: 'Build: Company Name',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [368, 560],
    })
    BuildCompanyName = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: "={{ $('Action: Get Company Name').item.json.ID }}",
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'COMPANY_NAME',
                    value: "={{ $json.COMPANY_NAME || 'unknown' }}",
                    type: 'string',
                },
                {
                    id: 'bw2',
                    name: 'COMPANY_NAME_COMPLETED',
                    value: "={{ $json.COMPANY_NAME_COMPLETED === true || $json.COMPANY_NAME_COMPLETED === 'true' ? true : null }}",
                    type: 'string',
                },
                {
                    id: 'bw3',
                    name: 'ERROR',
                    value: '={{ $json.error || null }}',
                    type: 'string',
                },
                {
                    id: 'bw5',
                    name: 'STATUS',
                    value: '={{ $json.STATUS || null }}',
                    type: 'string',
                },
                {
                    id: 'unlock-0007-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'inst-0043-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
                {
                    id: 'verb-0043-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '1b155642-2722-4296-8349-968931fa1164',
        name: 'Build: Status MISSING_COMPANY_ID (doubles)',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [112, -16],
    })
    BuildStatusMissingCompanyIdDoubles = {
        assignments: {
            assignments: [
                {
                    id: 'bw0',
                    name: 'ID',
                    value: "={{ $('Action: Handle Doubles').item.json.ID }}",
                    type: 'string',
                },
                {
                    id: 'bw1',
                    name: 'STATUS',
                    value: 'DOUBLE',
                    type: 'string',
                },
                {
                    id: 'bw2',
                    name: 'DOUBLE_LINE_CONTEXT',
                    value: '={{ JSON.stringify({ source: "sql_doubles", key: ($json.COMPANY_ID || "") + "|" + ($json.DOC_ID || ""), at: $now.toISO() }) }}',
                    type: 'string',
                },
                {
                    id: 'bw3',
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
                    id: 'verb-0044-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-0044-4000-8000-00000000c0de',
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
        position: [1920, 1200],
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
        id: 'dbdecidehead01',
        name: 'Decide DOC BASE Action',
        /*__n8n__*/ notes: "P1 2026-08-11: attempt counting is DISTINCT, not occurrence-based. ACTION_LOG duplicates itself: incdoc_action_log_append re-appends the whole history when the row moved since dispatch (position(old_log in new_log)=0 -> old_log || new_log), and concurrent actions per document are by design because the lock key is ID::ACTION. Measured on the 351 MAX_ITERATIONS rows: 7,938 distinct (action,timestamp,execution) triples across 43,710 occurrences = 5.51x inflation, worst 67x, so 82% of the counted budget was text no execution wrote. 405 docs were over the cap by occurrence, 8 by distinct count. ",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-880, -208],
    })
    DecideDocBaseAction = {
        jsCode: `// __EXPORTABLE__ [owner design 2026-08-18] THE decide logic lives HERE and only here.
// Wrapped as one self-contained function so this node can EXPORT ITS OWN SOURCE:
// mode='export_decide' returns { fnSrc: __docBaseDecideFn.toString() } and the mega decide
// (indoxV2DecideMin01) rehydrates it with new Function('$','$execution', src)($,$execution)
// and runs it in ONE code node. Node-input accessors were replaced by the __items
// parameter; $()/$ execution references resolve in WHICHEVER context runs the function
// (router graph or mega) — $('Companies') is absent in mega by design, __CFG catches.
function __docBaseDecideFn(__items) {
// [v2.1] router_doc_base — DECIDE mode. The pre-type "determine action":
// empty-id / max-iter guards + docBaseDecide (company·name·type·old-date·double)
// + resolves the type route. The stateful dedup result arrives on doc._dup.
// [perf 2026-08-18] memoized per invocation: when $('Companies') is absent (mega context)
// the un-memoized version threw+caught one exception PER ROW. Deterministic within a run.
let __CFG_C; function __CFG(){ if (__CFG_C !== undefined) return __CFG_C; let c={}; try{ c=$('Companies').first().json||{}; }catch(e){} try{ const x=(__items[0]||{json:{}}).json._cfg; if(x&&typeof x==='object') c={...c,...x}; }catch(e){} __CFG_C = c; return c; }

// [resolver generation 2026-08-10] THE COMPANY RESOLVER'S OWN GENERATION.
// \`public.extraction_queries\` carries one generation per query key (16 keys live); this is
// the one for \`q_v3_company\` ONLY -- it says nothing about type, date or amount resolvers,
// and must never be treated as a global "resolvers changed" signal.
// PREFERENCE ORDER IS DELIBERATE. __CFG() first, so that if/when the _cfg channel is
// genuinely populated this node uses it and the DB read below becomes dead weight rather
// than a competing source of truth. Today it is not populated: \`resolver_gen\` exists in
// exactly one active workflow (indoxSettings01), neither caller of this workflow injects
// \`_cfg\`, and 0 of 96 sampled executions carried it -- which also means every existing
// __CFG() consumer here has been silently using its hardcoded fallback.
// EMPTY MUST MEAN "GATE OFF". If the generation cannot be read, the term below is false and
// behaviour is byte-identical to before this patch. A blank generation must never re-open
// every document forever -- that is the same unbounded loop this lane just removed.
function __RESGEN(){
  let g = '';
  try { g = String(__CFG().resolver_gen_company || '').trim(); } catch(e) { g = ''; }
  if (!g) { try { g = String(($('Load Company Resolver Gen').first().json || {}).resolver_gen_company || '').trim(); } catch(e) { g = ''; } }
  return g;
}
const __RESOLVER_GEN_COMPANY = __RESGEN();


function isBlank(val) {
  return [null, undefined, '', 'unknown'].includes(
    (String(val ?? '')).toLowerCase()
  );
}

// [decide 30k slim 2026-08-17] ACTION_LOG is the fattest column on the table (20MB of 73MB)
// and THIS node is its only decide-path reader — three derived facts, nothing else.
// indoxV2Decide01's 'Determine Action' now precomputes those three facts as doc._log and
// DROPS ACTION_LOG from the batch it sends here (restored verbatim at decide's exit, so the
// caller's contract is unchanged). When _log is absent (any other caller, or execute-path
// reuse), the same three facts are derived inline from ACTION_LOG — behaviour is
// byte-identical either way.
function __logInfo(doc) {
  // [2026-08-20, owner order] EVERY field here is a plain column read off the row.
  //
  // The name is now a fossil: this used to parse ACTION_LOG, and indoxV2Decide01 used to hand in a
  // precomputed doc._log so the 20MB column was only parsed once. Both are gone -- the _log
  // indirection with them, along with its failure mode (a stale _log silently beat the correct
  // value, because it was preferred whenever present).
  //
  // The two flags read *_COMPLETED columns, like the other twenty actions, NOT ACTION_HISTORY.
  // History answers "was this DISPATCHED" -- the double-action question, owned by
  // 'Dup Guard: Double Action'. These gates ask "is this work DONE", which is a fact the action
  // itself writes on the row. Reading history here was tried on 2026-08-20 and re-dispatched
  // file_to_failed_folder on already-filed documents; Google Drive answered "File not found",
  // because the move is not idempotent. Columns backfilled by
  // scripts/ops/migrations/2026-08-20_gmail_failedfolder_completion_flags.sql.
  const T = (v) => String(v == null ? '' : v).trim().toLowerCase() === 'true';
  return {
    // [source feedback 2026-08-21] gmailLabeled / failedFoldered are GONE, with the two gates
    // that read them. Per-source completion now lives where the source does -- on the
    // SOURCE_LIST element (sync_feedback_completed) -- because a ROW-level flag cannot answer
    // "has THIS source been told" for a document that has two of them, which is exactly what a
    // merge produces. The columns are left on the table read-only for one cycle as the migration
    // source, then dropped. The lesson the old flags encode is kept and still applies: this asks
    // "is the work DONE", a fact the action writes, NOT "was it dispatched" -- reading history
    // here was tried on 2026-08-20 and re-dispatched file_to_failed_folder on already-filed
    // documents, and a Drive move is not idempotent.
    // [2026-09-02] iterCount = DISPATCHES SINCE THE LAST RESTART, counted by the driver from
    // indox_action_execution_log and carried on the row as __dispatches_since_restart. The
    // column ITERATION_COUNT was only ever reset (to 0 by the restart builders) and never
    // incremented by anything, so the ceiling below compared 0 against its budget forever and
    // mark_max_iterations was unreachable (the 2026-08-20 comment here claimed the router
    // incremented it; it never did — 'Log Action Start' only inserts the log row). The restart
    // epoch is the last restart_* dispatch, which is exactly the boundary the count uses.
    iterCount: Number(doc && doc.__dispatches_since_restart) || Number(doc && doc.ITERATION_COUNT) || 0,
  };
}

// [source feedback 2026-08-21, owner rule] IS THIS DOCUMENT FINISHED, AND DID IT FINISH WELL?
//
// The owner's definition of success, verbatim: "if has both ex points completed and company +
// doc_id values its success else fail". Both extraction points, plus the two identity fields --
// a document the machine calls COMPLETED but that carries no DOC_ID did not actually succeed,
// and it is filed as a failure. That is the rule as given.
//
// TERMINALITY IS AN ADDITIONAL GUARD, not a softening of it. Without it every in-flight document
// -- one waiting on extraction, on a company lookup, on a retry -- would read as "not complete"
// and be filed as a FAILURE on its very first sweep, moving a client's file into the failed
// folder while the pipeline was still working on it. So a document that has not reached a
// terminal state yields 'pending' and no feedback is decided at all. The failure list is the one
// the old file_to_failed_folder gate used, unchanged.
function __feedbackOutcome(doc) {
  const T = (v) => String(v == null ? '' : v).trim().toLowerCase() === 'true';
  const st = String((doc && doc.STATUS) || '').toUpperCase();
  if (st === 'COMPLETED') {
    // [type-aware success 2026-09-02] A balance sheet has no document id — its content is its
    // lines — so demanding DOC_ID filed EVERY completed aging report as a failure (measured on the
    // real runs: gmail-bs → FAILED_BS label, drive-bs → the failed folder, both with base, per-type
    // and lines all complete and a company found). Success = the extraction the type owns is done
    // and the company is known; the document id is required only where the type carries one.
    const isBs = String(doc.TYPE || '').toUpperCase() === 'BALANCE_SHEET';
    const complete = T(doc.BASE_EXTRACTION_COMPLETED) && T(doc.PER_TYPE_EXTRACTION_COMPLETED)
                     && !isBlank(doc.COMPANY_ID) && (isBs || !isBlank(doc.DOC_ID));
    return complete ? 'success' : 'failure';
  }
  if (['MISSING_TYPE', 'EXTRACTION_FAILED', 'GARBAGE', 'MAX_ITERATIONS',
       'NEEDS_REVIEW'].includes(st)) return 'failure';
  return 'pending';
}

// [five classes 2026-08-27, owner order] ORDER AND RECEIPT LEFT THE INVOICE LANE.
// ORDER used to resolve to 'gdoc' and gdocDecide aliased orderDecide straight onto
// invoiceDecide, so an order ran the WHOLE invoice pipeline -- per-type extraction,
// selection, and an ERP priority_sync. Measured over the 24h before this change: 352 ORDER
// dispatches, 79 of them priority_sync, for values nobody reads off an order. RECEIPT did
// not resolve at all (-> 'unknown' -> MISSING_TYPE) and could not: neither engine could
// emit it. Both are RECORDED, not PROCESSED -- base resolves COMPANY_ID/TYPE/DOC_DATE and
// that is the whole point of keeping them -- so each gets its own class and its own
// one-action router (indoxV2ActionsOrd01 / indoxV2ActionsRcp01).
// 'gdoc' is renamed 'invoice' because with those two gone that is all it holds.
// ONE MAP, not a ternary chain: this function and BOTH its routing call sites read the same
// two objects, so a sixth class cannot be added to one and forgotten in the other. The
// unknown fallback is unchanged -- anything not named here still terminalises MISSING_TYPE.
const _DOC_CLASS = {
  INVOICE: 'invoice',
  SHIPMENT: 'shipment',
  BALANCE_SHEET: 'bs_doc',
  ORDER: 'order',
  RECEIPT: 'receipt',
};
const _ROUTE = {
  invoice:  '__route_invoice__',
  shipment: '__route_shipment__',
  bs_doc:   '__route_bs__',
  order:    '__route_order__',
  receipt:  '__route_receipt__',
};
function resolveDocType(type = '') {
  return _DOC_CLASS[String(type ?? '').toUpperCase()] || 'unknown';
}

function anyOldDate(dates, monthsOld, names) {
  // [settings-driven ageing 2026-08-13] NO SILENT 24-MONTH FALLBACK.
  // This line read \`|| 24\` and, because the Companies node was calling indoxSettings01 with
  // load_settings:false, the configured value never arrived and 24 won every time -- invisibly,
  // for as long as the setting has existed. A hardcoded default that silently overrides operator
  // configuration is worse than no default: nothing in the logs or the UI said the number was
  // being ignored. If the setting cannot be read, that is now a stated fact rather than a guess,
  // and the document is left alone instead of being aged out against an invented threshold.
  if (monthsOld === undefined) {
    let _cfgMonths;
    try { _cfgMonths = Number(__CFG().old_document_months_back); } catch (e) { _cfgMonths = undefined; }
    if (!Number.isFinite(_cfgMonths) || _cfgMonths <= 0) {
      // Refuse to age anything rather than apply a number nobody configured.
      return null;
    }
    monthsOld = _cfgMonths;
  }
  const cutoff = new Date();
  cutoff.setMonth(cutoff.getMonth() - monthsOld);


  // Two-digit years: JS \`new Date(y, ...)\` maps 0-99 to 1900+y, so \`07/07/26\` silently
  // became 1926 and every such document was terminalised OLD -- real data loss, since
  // client documents routinely print dd/mm/yy. Sliding pivot: YY is 20YY unless that is
  // more than one year in the future, then 19YY. Sliding (not a fixed constant) so it
  // stays right as the deployment ages.
  function fullYear(y) {
    y = Number(y);
    if (!Number.isFinite(y)) return NaN;
    if (y >= 100) return y;
    const nextYear = new Date().getFullYear() + 1;
    return (2000 + y <= nextYear) ? 2000 + y : 1900 + y;
  }

  function parseDate(val) {
    if (!val || String(val).toUpperCase() === "MISSING") return null;
    // [owner 2026-08-15] client documents also print dd.mm.yyyy -- normalise the separator so the
    // dd/mm branch below handles both. Proven need: the all-rows census left ~100 old docs
    // unaged purely because their dates used dots.
    if (typeof val === "string") val = val.trim().replace(/\\./g, "/");

    // Excel serial number (e.g. 46127)
    if (!isNaN(val) && Number(val) > 1000) {
      const excelEpoch = new Date(Date.UTC(1899, 11, 30));
      const parsed = new Date(excelEpoch.getTime() + Number(val) * 86400000);
      return isNaN(parsed.getTime()) ? null : parsed;
    }

    // DD/MM/YYYY format (e.g. 15/04/2026)
    if (typeof val === "string" && val.includes("/")) {
      const parts = val.split("/");
      if (parts.length === 3) {
        const [day, month, year] = parts.map(Number);
        const parsed = new Date(fullYear(year), month - 1, day);
        return isNaN(parsed.getTime()) ? null : parsed;
      }
    }

    // YYYY-MM-DD format (e.g. 2026-05-04)
    if (typeof val === "string" && /^\\d{4}-\\d{2}-\\d{2}$/.test(val)) {
      const [year, month, day] = val.split("-").map(Number);
      const parsed = new Date(fullYear(year), month - 1, day);
      return isNaN(parsed.getTime()) ? null : parsed;
    }

    // ISO 8601 timestamp (e.g. 2026-01-01T07:39:25.231Z)
    if (typeof val === "string" && /^\\d{4}-\\d{2}-\\d{2}T/.test(val)) {
      const parsed = new Date(val);
      return isNaN(parsed.getTime()) ? null : parsed;
    }

    // Fallback for standard JS-supported formats
    const parsed = new Date(val);
    return isNaN(parsed.getTime()) ? null : parsed;
  }

  // [owner 2026-08-15] Corruption-aware selection -- ALL fields stay in play:
  //   * PLAUSIBLE years only (2015..now+2): the audit found pre-2015 values are #39 swap
  //     fallout (52 on AI alone), and nothing legitimate lives there.
  //   * SWAP-MANGLE rejection: 898 documents carry AI/SELECTED = day/year swap of a plausible
  //     sibling (26/06/2018 <- 18/06/2026). A candidate whose (day, yy) mirror a plausible
  //     sibling's (yy, day) with the same month is the mangle, not a real date -- skip it.
  const rawList = (Array.isArray(dates) ? dates : [dates]);
  const parsedAll = rawList.map(parseDate);
  const yNow = new Date().getFullYear();
  const plausible = (dt) => dt && dt.getFullYear() >= 2015 && dt.getFullYear() <= yNow + 2;
  const sane = parsedAll.filter(plausible);
  // Asymmetric on purpose: the swap relation is symmetric, so testing it both ways would kill
  // BOTH halves of the pair (proven by case s7). The mangle is the EARLIER year -- a swap moves a
  // day-number (1..31) into the year, always landing in the past -- so keep the later sibling.
  const isSwapOfSibling = (dt) => sane.some((sib) => sib !== dt &&
    sib.getFullYear() > dt.getFullYear() &&
    dt.getMonth() === sib.getMonth() &&
    dt.getFullYear() % 100 === sib.getDate() &&
    dt.getDate() === sib.getFullYear() % 100);
  // [year-misread rejection 2026-08-25] Same corruption family as the swap above, different
  // mangle: an extractor reads the right DAY and MONTH off the page and the WRONG YEAR.
  // 31/07/2024 beside a sibling 31/07/2026 is not a second date, it is the same date misread --
  // and because the verdict is .some, that one bad candidate ages out a document the sibling
  // proves is current. Measured: doc_mt8u8wm386tnr5, an aging report mailed 2026-08-25
  // (RECEIVED_DATE 25/08/2026, LOCAL_DOC_DATE 31/07/2026), terminalised OLD on AI_DOC_DATE
  // 31/07/2024 alone. Identical day AND month with a strictly later plausible sibling is the
  // signature; a genuinely older date almost never lands on the same day-of-year as another
  // date on the same document. Asymmetric like the swap rule, and for the same reason: only
  // the earlier of the pair is dropped, so the pair can never annihilate itself.
  // Known trade: a true annual series carrying both 31/07/2024 and 31/07/2026 on ONE document
  // would lose the older leg. No such document exists in the estate today; if one appears it
  // shows up as a doc that will not age, not as data loss.
  const isYearMisreadOfSibling = (dt) => sane.some((sib) => sib !== dt &&
    sib.getFullYear() > dt.getFullYear() &&
    dt.getMonth() === sib.getMonth() &&
    dt.getDate() === sib.getDate());
  const parsedDates = parsedAll.filter((dt) => plausible(dt) && !isSwapOfSibling(dt)
    && !isYearMisreadOfSibling(dt));

  // [OLD_REASON owner 2026-08-15] Return the WHY, not just the verdict. Truthy object = old
  // (legacy \`if (anyOldDate(...))\` callers unaffected); null = not old. Records which field(s)
  // crossed the cutoff, every value considered, and what was skipped as corrupt and why.
  {
    const _nm = (i) => (names && names[i]) || ('date_' + (i + 1));
    const hits = [], considered = [], skipped = [];
    parsedAll.forEach((dt, i) => {
      const raw = rawList[i];
      if (raw === null || raw === undefined || String(raw).trim() === '') return;
      if (!dt) { skipped.push({ field: _nm(i), value: String(raw), why: 'unparseable' }); return; }
      if (!plausible(dt)) { skipped.push({ field: _nm(i), value: String(raw), why: 'implausible_year' }); return; }
      if (isSwapOfSibling(dt)) { skipped.push({ field: _nm(i), value: String(raw), why: 'swap_mangle_of_sibling' }); return; }
      if (isYearMisreadOfSibling(dt)) { skipped.push({ field: _nm(i), value: String(raw), why: 'year_misread_of_sibling' }); return; }
      const isOld = dt < cutoff;
      considered.push({ field: _nm(i), value: String(raw), old: isOld });
      if (isOld) hits.push({ field: _nm(i), value: String(raw) });
    });
    if (parsedDates.length > 0 && parsedDates.some(d => d < cutoff)) {
      return { rule: 'any_date_older_than_' + monthsOld + '_months',
               cutoff: cutoff.toISOString().slice(0, 10), hits, considered, skipped };
    }
    return null;
  }

  // [owner 2026-08-15] .some, not .every -- the function is NAMED anyOldDate but required EVERY
  // date to be old, so one recent (or #39-corrupt future) date vetoed ageing: a doc with
  // DOC_DATE 02/07/2025 and SELECTED_DOC_DATE 16/09/2026 routed on forever. Proven by replaying
  // row 129855666rsqj3a through this code solo. ANY old date now means old, as the name always said.
  // (unreachable -- the reason block above is the return path now)
}

function docBaseDecide(doc, dup) {
  // [dynamic restart 2026-08-17, owner order] Base-stage docs get the same native restart the
  // typed routers have: one action that clears every *_COMPLETED flag dynamically, sets
  // IN_PROGRESS, and lets the next sweep re-walk the whole pipeline. Decided FIRST, like
  // gdocHead/shipHead/bsHead. Stamps ACTION=restart_base (prefix-matches the dup guard's
  // restart ordering and re-arms the iteration ceiling's epoch anchor).
  //
  // [2026-08-23] ... AND ONLY FOR A DOC THAT HAS NO TYPED ROUTER. The line above used to be an
  // unconditional 'return restart_base', and because doc_base runs FIRST in the decide fan-out
  // (indoxV2Decide01 :: __run_doc_base, then the __route_* split), it claimed the restart of
  // EVERY document -- which made all three typed restart heads dead code the day they were
  // written. Verified by execution search: no indoxV2ActionsBS01 execution has ever contained
  // 'Build: Restart (clear completed flags)'; the BS coverage case cov_restart sat in
  // ACTION_RESTART untouched because decide answered 'restart_base' and the BS switch has no
  // such route.
  //
  // That was not cosmetic. The four restart bodies are NOT interchangeable: BS's sets
  // BS_EXTRACTION_USE_CACHE=false and the others do not, and its own note says why -- "so a
  // genuine re-run extracts fresh". So the operator's Retry button on a balance sheet cleared
  // every *_COMPLETED flag, re-ran the extraction, and got the CACHED answer back. The one
  // action whose whole purpose is "do it again, properly" was the one that could not.
  //
  // The routing returns below are the same '__route_*__' sentinels this function already
  // returns 380 lines down for ordinary type dispatch -- same mechanism, same consumer, no new
  // path. Each typed router decides its own restart first (gdocHead/shipHead, and bsDecide's
  // hoisted check), so this hands the decision over rather than making it.
  // [five classes 2026-08-27] Reads _ROUTE, so order/receipt hand their restart to their own
  // lane like every other type. Those lanes answer 'mark_completed' (ACTION_RESTART !==
  // 'COMPLETED'), which terminates: writing STATUS already moved indox_line_hash(), so the
  // dup guard does not see a repeat.
  if (doc.STATUS === 'ACTION_RESTART') {
    return _ROUTE[resolveDocType(doc.TYPE)] || 'restart_base';
  }
  // [pre-extraction OLD gate 2026-08-15] RECEIVED_DATE exists AT INGEST, so an out-of-scope
  // document is aged out BEFORE it can spend an extraction. Measured cause: 1,398 of 1,445
  // documents ingested in one 6h window were >6 months old by RECEIVED_DATE, 1,392 of them got
  // base extraction and 0 got OLD -- because the late gate below only sees post-extraction dates
  // and sits after the extract_base_doc returns. The late gate stays for dates extraction reveals.
  // [owner 2026-08-15: "simply filter all old"] ONE gate, ALL dates, no status conditions
  // except already-OLD. Threshold: config when reachable; otherwise the owner's stated 6 --
  // explicit here because on the DECIDE path the Companies node never runs, __CFG() is {}, and
  // the config-only version silently never aged anything (proven from live run data, exec 3143473).
  const OLD_MONTHS = (() => {
    // [row-carried settings 2026-08-31] The driver's enrich stamps __old_months on every row
    // (settings key OldDocumentMonthsBack), the SAME mechanism as __merge_enabled — because on
    // the decide path Companies never runs and __CFG() is {}. Row first, then __CFG for the
    // execute path where Companies does run, then the owner's stated 6.
    try { const r = Number(doc.__old_months); if (Number.isFinite(r) && r > 0) return r; } catch (e) {}
    try { const v = Number(__CFG().old_document_months_back); if (Number.isFinite(v) && v > 0) return v; } catch (e) {}
    return 6;
  })();
  // [2026-08-25] LOCAL_DOC_DATE joins the candidate set. It is not here to add another way to
  // be old (.some means every added field can only age MORE documents) -- it is here because
  // the corruption rules inside anyOldDate work by comparing a candidate against its SIBLINGS,
  // and with the local extractor's value withheld the AI's mangles had nothing to be caught
  // against. Both OLD documents in the 2026-08-25 E2E run were AI year-misreads whose local
  // sibling carried the right year and was not in the list.
  const __lateOldReason = anyOldDate([doc.RECEIVED_DATE, doc.DOC_DATE, doc.AI_DOC_DATE, doc.BS_LINE_DATE, doc.LOCAL_DOC_DATE], OLD_MONTHS,
    ['RECEIVED_DATE', 'DOC_DATE', 'AI_DOC_DATE', 'BS_LINE_DATE', 'LOCAL_DOC_DATE']);
  if (__lateOldReason) {
    if (doc.STATUS != "OLD") { doc.IS_OLD = true; doc.OLD_REASON = JSON.stringify(__lateOldReason); return 'update_status_old_doc'; }
    return 'no_action_old_date';
  }
  // [resolve_double 2026-08-06] validity-passing (COMPANY_ID, DOC_ID) collision.
  // 'Determine Action' (indoxV2Decide01) stamps _dup.bizDocMatch/bizSig on every member
  // of a 2+ group; 'Adjudicate Merge' stamps the adjudicated signature into
  // DOUBLE_LINE_CONTEXT.merge_sig. Fire only when the composition CHANGED since the
  // last adjudication: a kept winner with an unchanged signature falls through to
  // normal processing, a confirmed DOUBLE with an unchanged signature stays queued.
  // [resolve_double, single-row 2026-08-06] Fire when this row carries a usable
  // business key that has NOT yet been adjudicated for THAT key. 'Adjudicate Merge'
  // does the DB lookup and stamps {merge_key, merge_sig} into DOUBLE_LINE_CONTEXT,
  // which is what silences this gate afterwards -- so the cost is ONE extra dispatch
  // per (document, business-key), once, ever. Re-fires only if the key itself CHANGES
  // (e.g. extraction corrects a wrong DOC_ID), which is exactly when re-adjudication
  // is owed. A merge leaves the winner unstamped for one more sweep on purpose: it
  // then re-runs, finds its twin now MERGED (and excluded), and converges via the
  // promote branch -- a free re-verification, and it terminates.
  // [double storm 2026-08-09] EVIDENCE, NOT KEY-PRESENCE. The gate below used to fire on
  // \`dup.bizKey\` alone, i.e. on every document carrying a business key -- 6071 of 7231 live
  // rows, 5769 of them with no twin in existence. It now needs \`dup.bizCollision\` (a second
  // live row on the same (COMPANY_ID, DOC_ID) in this sweep, stamped by 'Determine Action')
  // or an existing DOUBLE flag to adjudicate. The DOUBLE clause is what drains the backlog:
  // each of the 631 flagged rows is adjudicated exactly once, the 439 that turn out to have
  // no twin are promoted back to IN_PROGRESS by 'Adjudicate Merge', and the flag is then
  // gone for good.
  // The final \`else\` branch sets bizAdjudicated on a row that holds a REAL business key with
  // no collision, which also silences the weak SHORT_DOC_ID/HASH detector below for that row
  // -- deliberately. That detector keys on the last 5 alphanumerics of a document id and is
  // the source of the over-detection the owner asked to stop: if a document has a full,
  // unique (COMPANY_ID, DOC_ID) and nothing else in the table shares it, a 5-character tail
  // coincidence is not grounds to mark it DOUBLE. Rows with no usable business key are
  // untouched and still fall through to that detector.
  // [2026-08-23] THE merge_sig GATE IS GONE. Doubles are decided in ONE place: indoxV2Decide01,
  // from the driver's SQL detector (IS_DOUBLE / IS_MAIN_DOUBLE), before any other routing.
  // This block was the in-memory detector's gate and it could not fire on the live path --
  // Decide01 sets _dup={match:false} precisely so the two detectors can never both run -- yet it
  // stayed in the file looking authoritative, and cost hours of debugging aimed at code that
  // never executes. It also read DOUBLE_LINE_CONTEXT.merge_sig, the fingerprint that broke when a
  // member's HASH arrived after stamping.
  // The only caller that still supplied a live _dup was indoxV2DecideMin01: published, and 0
  // executions in 7 days against Decide01's 760. Its in-memory detector is therefore inert here;
  // if it is ever revived it must read the SQL flags like everything else.
  // [2026-08-23] THE IN-MEMORY DOUBLES DETECTOR IS GONE FROM THIS NODE, ENTIRELY.
  // Doubles are decided once, in indoxV2Decide01, from the driver's SQL flags (IS_DOUBLE /
  // IS_MAIN_DOUBLE) and BEFORE any routing below. What used to sit here -- bizAdjudicated, the
  // dup.match branch and the DOUBLE_CONTEXT it stamped -- could never fire: Decide01 sets
  // _dup={match:false} on every row precisely so two detectors can never disagree. It stayed in
  // the file looking authoritative and cost this session hours of edits to code that never ran,
  // and its DOUBLE_CONTEXT write is what made 'Build: Status MISSING_COMPANY_ID (doubles)' throw
  // on undefined once non-mains finally reached that lane.
  // One detector, one decision, one place.
  if (doc.STATUS === 'PAUSE')  return 'no_action_paused';

  // BaseDocEx01 (local+AI in parallel) runs first, gated on a REAL
  // completion flag -- never on whether COMPANY_ID already has a value,
  // since ingestion (indoxProcessDocument01) pre-fills it on 87% of rows.
  // Once this lands, figure_company_id's own '!doc.COMPANY_ID' guard below
  // goes false on its own -- no edit needed there, it just stops firing.
  // [drive-connection guard 2026-08-13] A LINK WE CANNOT REACH IS NOT AN EXTRACTABLE FILE.
    // drive api stopped honouring the deployment's active connection as an implicit default for
    // automation calls, so a row holding a LINK with a blank LINK_CONNECTION fails EVERY drive call:
    // 'requires an explicit profile_id or connection_id'. Measured before landing this: 13 such rows
    // (all SYNC_NAME='gmail-link', 13 of 186 in that pipe; every other pipe had zero) were generating
    // 92 drive api errors an hour, ~7 doomed attempts each, and the count doubled every 5 minutes.
    // Gating extract alone only RELOCATED the churn to figure_company_id, which threads
    // LINK_CONNECTION downstream too -- so figure_company_id is gated as well and the row falls to
    // figure_company_offline, the deliberately link-independent resolver, which is the correct
    // answer for a document whose file cannot be opened. It carries its own ACTION_LOG re-fire
    // guard, so this is bounded at one pass, not a loop.
    // This does NOT paper over the root: the connection must be threaded at Link Row (see #29 part 1).
    // [value+flag gate 2026-08-17, owner order] Base's sentinel VALUE used to be TYPE: only a doc
    // whose TYPE was empty re-entered base. [typed at birth 2026-09-03, owner Decision N8] A
    // document typed by its source (registry type_hint / fallback_type / TYPE_BY_SOURCE, a
    // balance-sheet line's INVOICE child) never got an OCR upload id this way, and the per-type
    // gate then parked it as API_TOOLS_FAILED — 67 of 87 such parks in one week carried no
    // reason. The sentinel VALUE is now API_TOOLS_ID: base runs (upload + OCR + both legs) for
    // any linked document that has no upload id yet, and SelectBase01 keeps the source's type
    // authority (decisive outranks both readers). The flag still closes the gate after one pass;
    // ACTION_RESTART clears it, exactly as before.
    if (doc.LINK && !isBlank(doc.LINK_CONNECTION) && isBlank(doc.API_TOOLS_ID) && String(doc.BASE_EXTRACTION_COMPLETED == null ? '' : doc.BASE_EXTRACTION_COMPLETED).trim().toLowerCase() !== 'true') return 'extract_base_doc';

  // [no state-machine retries 2026-08-17, owner order] The 'BASE APITOOLS RETRY' one-shot
  // (2026-08-09, re-dispatched extract_base_doc past a set BASE_EXTRACTION_COMPLETED, bounded
  // by an ACTION_LOG marker only a COMPLETED pass wrote) is REMOVED. It crash-looped: a doc
  // whose retry crashed never got the marker and re-fired until the iteration ceiling
  // (doc_msly5hcz9p9ngj, execs 3366364/3367824/3368000, retired MAX_ITERATIONS 2026-08-17).
  // BASE_EXTRACTION_COMPLETED is the whole gate; a base pass with no apitools id keeps its
  // verdict and ACTION_RESTART is the only re-run.

  // [selection 2026-08-25, owner order] SELECT BEFORE YOU TERMINALISE.
  // This gate MUST stay above the company and type gates below, and the reason is structural, not
  // stylistic. Extraction no longer writes COMPANY_ID or TYPE -- it writes only what its engines
  // saw -- so a freshly extracted document reaches this function with those columns still empty.
  // The next two gates read exactly those columns and park the row MISSING_COMPANY_ID /
  // MISSING_TYPE, and both statuses are EXCLUDED from the pickup's eligibility (indoxApi01), so
  // the row would leave the pool before the selection that fills them could ever be dispatched.
  // Selecting first keeps the document IN_PROGRESS and eligible, and terminalisation stays exactly
  // as honest as it was -- it just happens after the selector has spoken instead of before.
  //
  // The re-selection arm is the other half. A hash mismatch means a VERSION changed underneath a
  // decision that has already been made (a restart re-extracted, an operator corrected a field),
  // so the decision is re-made -- reading no file and calling no model, because selection is a
  // pure function of the row.
  // FAIL-SAFE BY CONSTRUCTION, same rule the priority signature already follows: a difference
  // counts only when BOTH hashes exist. Every row extracted before this column existed carries no
  // stored hash, and treating "unknown" as "changed" would re-select the entire estate on the
  // first sweep after deploy. Those rows are picked up deliberately instead -- a select_base
  // dispatch from the console over whatever selector the operator chooses -- never by a wave
  // nobody asked for.
  {
    var _bsDone = String(doc.BASE_SELECTION_COMPLETED == null ? '' : doc.BASE_SELECTION_COMPLETED)
                    .trim().toLowerCase() === 'true';
    var _bsLive = doc.__base_selection_hash, _bsStored = doc.BASE_SELECTION_HASH;
    var _bsChanged = !!_bsLive && !!_bsStored && String(_bsLive) !== String(_bsStored);
    // NO EXTRACTION-FLAG PRECONDITION -- see the per-type gate for the failure this caused.
    // ACTION_RESTART clears BASE_EXTRACTION_COMPLETED, so requiring it here meant a restarted
    // document was never re-selected. The extract_base_doc gate sits above this one, so reaching
    // here means base extraction is either done or not owed.
    if (_bsChanged || (!_bsDone && doc.STATUS !== 'COMPLETED')) return 'select_base';
  }

  if (!doc.COMPANY_ID) {
    // [resolver generation 2026-08-10] A REBUILT RESOLVER DESERVES ONE MORE PASS.
    // FIGURE_COMPANY_COMPLETED means "this document has been through the resolver", not
    // "this document has no company". When q_v3_company itself is rebuilt, that flag is
    // answering a question about the OLD resolver, so a document whose company is now
    // derivable stays at MISSING_COMPANY_ID forever with nothing able to re-open it.
    // Measured before landing this: 386 documents are re-opened by this term and no others
    // (345 MISSING_COMPANY_ID, 28 API_TOOLS_FAILED, 9 ACTION_REQUIRED, 7 NEEDS_REVIEW,
    // 3 TO_EXTRACT). The other 7,349 companyless-with-link rows already fire on
    // !FIGURE_COMPANY_COMPLETED today, so this adds nothing for them.
    // BOUND IS ONE DISPATCH PER (DOCUMENT, GENERATION), and it is STRUCTURAL: 'Join
    // COMPANY_ID' stamps \`COMPANY RESOLVER <gen>\` unconditionally on every document the
    // resolver returns for, success or failure, so a failing document cannot re-fire on
    // this term. Same marker mechanism as BASE APITOOLS RETRY and FIGURE COMPANY OFFLINE;
    // no new column. It re-arms only when the generation itself changes, which is exactly
    // when another pass is owed.
    // [two-point rule 2026-08-17, owner order] figure_company_id is LEGACY and never fires:
    // company resolution lives in the base extraction point only. The whole dispatch branch
    // is REMOVED — including its ACTION_RESTART bypass and resolver-generation re-arm, which
    // kept re-opening the legacy resolver (the 08:18 wave dispatched it 969 times through
    // the restart bypass). Base stamps FIGURE_COMPANY_COMPLETED unconditionally now; docs
    // not yet through base are claimed by extract_base_doc above. A companyless doc falls
    // through HERE to figure_company_offline (filename, no OCR) and then terminalizes
    // MISSING_COMPANY_ID — the operator's verdict, not an OCR churn loop.
    // [B31 2026-08-09] LINK-INDEPENDENT FILENAME RESOLUTION -- the last resort before
    // MISSING_COMPANY_ID. Both resolvers above need \`doc.LINK\`; a linkless document was
    // terminalised here with NO company resolution ever attempted (measured: 62 of 63
    // such rows had a completely empty ACTION_LOG). The company is in the filename, which
    // needs no link and no OCR. Sits AFTER figure_company_id on purpose: that resolver is
    // strictly stronger, so this only runs once it is exhausted or unavailable.
    // FILL-ONLY by construction -- it is inside \`if (!doc.COMPANY_ID)\`, so it can never
    // overwrite an existing value. Re-fire guard is the ACTION_LOG marker, the same
    // mechanism the gmail label gate uses; no new column.
    // [two-point rule 2026-08-17, owner order] figure_company_offline REMOVED as an action:
    // the filename matcher now lives INSIDE BaseDocEx01 ('NAME Company Match (Offline)',
    // query ported verbatim) as the fill-only third company leg of the base pass. A doc
    // still companyless after base has had OCR-local, OCR-AI and NAME all tried —
    // MISSING_COMPANY_ID is the honest terminal.
    // [terminal guard 2026-08-25, double-action hunt] a COMPLETED document is settled — re-marking
    // it MISSING_COMPANY_ID re-opens ancient history: its original missing_company dispatch sits
    // unpaired in ACTION_HISTORY forever, so every re-emission is parked by the dup guard and
    // reported at end-of-lane, every sweep, endlessly (measured 2026-08-25: the blanket re-arm
    // resurrected exactly this class). Same doctrine as the 08-09/08-11 terminal guards.
    if (doc.STATUS === 'COMPLETED') return 'no_action_already_completed';
    if (doc.STATUS !== 'MISSING_COMPANY_ID')
      return 'update_status_missing_company';
    return 'no_action_awaiting_company_id';
  }

  if (isBlank(doc.COMPANY_NAME)) {
    // [company-retry bound 2026-08-13] MAX_ITERATIONS IS FOR RUNAWAYS, NOT FOR "WE CANNOT NAME IT".
    // Without a bound here this branch is taken on EVERY pass -- 'Join COMPANY_NAME' writes
    // COMPANY_NAME_COMPLETED = null whenever it has no answer (deliberate, [stage-retry 2026-08-10]),
    // so the two returns below were unreachable by construction and UNKNOWN_COMPANY could never be
    // reached. Each retry appends an ACTION_LOG stamp that counts toward _iter, so the document
    // eventually crossed the 50-action cap and was stamped MAX_ITERATIONS -- a company-resolution
    // failure reported as a runaway.
    // Measured before landing: 359 rows carry COMPANY_NAME='unknown', 342 of them (95%) MAX_ITERATIONS
    // and ZERO COMPLETED; get_company_name ran 26.7x per stuck document (12,875 stamps / 482 docs),
    // 51% of all work those documents ever received.
    // Bound is RETRY_COUNT, which 'Join COMPANY_NAME' already increments on every miss -- no new column.
    // 10 chosen against the resolvers' real behaviour: documents that DO resolve need p50=0, p90=0,
    // p99=8 retries. A cap of 10 blocks 41 of 5,000 real completions (0.8%) and gives 412 of the 482
    // stuck documents an honest UNKNOWN_COMPANY terminal instead of a false MAX_ITERATIONS (85%).
    // [always-complete 2026-08-17, owner order] one name attempt per epoch: the action
    // always stamps COMPANY_NAME_COMPLETED; the restart action resets it. No RETRY bound,
    // no ACTION_RESTART bypass — both removed with the miss-retry machinery.
    if (String(doc.COMPANY_NAME_COMPLETED == null ? '' : doc.COMPANY_NAME_COMPLETED).trim().toLowerCase() !== 'true')
      return 'get_company_name';
    return doc.STATUS !== 'UNKNOWN_COMPANY'
      ? 'update_status_unknwon_company'
      : 'no_action_awaiting_company_name';
  }

  // [dead code removed 2026-08-20] A second old-date gate lived here behind an if(false), disabled
  // by the owner on 2026-08-15 when it was folded into the single top gate (the one driven by
  // anyOldDate() at the head of this function). It had been dead for five days. Its one surviving
  // rule -- COMPLETED is excluded from the OLD transition as well as OLD itself, because the pickup
  // skips OLD and a finished document moved there could never be recovered -- is enforced by the
  // top gate and by _terminalKeep below, so nothing was lost with it.

  return null;
}

function unknownTypeAction(doc) {
  // [two-point rule 2026-08-17, owner order] figure_document_type and the standalone
  // extract_invoice_google_ai fallback are REMOVED: TYPE is resolved at the base point only
  // (BaseDocEx01 LOCAL leg + embedded Gemini AI leg, picked in 'Select Base'; base stamps
  // FIGURE_TYPE_COMPLETED unconditionally now). A doc still typeless after base
  // terminalizes MISSING_TYPE — no out-of-band type resolvers, no restart bypass.
  if (doc.STATUS !== 'MISSING_TYPE')
    return 'update_status_missing_type';
  return 'no_action_unknown_document_type';
}

function docBaseRouterDecide(doc) {
  const normDoc = { ...doc, ID: doc.ID != null ? String(doc.ID) : doc.ID };
  {
    const _t = String(normDoc.TYPE || '').toUpperCase();
    const _ai = String(normDoc.AI_TYPE || '').toUpperCase();
    if ((!_t || _t === 'UNKNOWN' || _t === 'UNKNWON') && _ai && _ai !== 'UNKNOWN' && _ai !== 'UNKNWON') normDoc.TYPE = _ai;
  }
  if (!normDoc.ID) return { json: { ACTION: 'no_action_delete_row', DOC_TYPE: 'empty', ...normDoc } };
  // [resolve_double 2026-08-06] A MERGED loser is a TOMBSTONE - nothing may act on it.
  // MUST stay the first gate after the empty-ID check. It sits above the B2 gmail-label
  // gate and the A5 GARBAGE gate deliberately: A5 returns 'update_status_garbage' for any
  // TYPE='GARBAGE' row whose STATUS is not already 'GARBAGE', which would OVERWRITE
  // STATUS='MERGED' and destroy the tombstone - the row would then re-enter
  // indoxV2Decide01's identity maps (they skip on STATUS==='MERGED') and could re-collide
  // with its own winner. The winner carries the document; the loser is inert by design.
  if (normDoc.STATUS === 'MERGED') return { json: { ACTION: 'no_action_merged', DOC_TYPE: resolveDocType(normDoc.TYPE), ...normDoc } };
  // [B2 thin-sync 2026-08-06] Gmail outcome labels moved off the sync processors'
  // delivery-time Switch5 (indoxGmailDocDownloader01 - dies under thin sync) into
  // the state machine. Fires ONCE per gmail-sourced doc: on the TYPE verdict
  // (saved-invoice / saved-shipment), and MANDATORILY when the doc terminalises
  // without a type (MISSING_TYPE / EXTRACTION_FAILED / GARBAGE / MAX_ITERATIONS)
  // - a mail must never stay silently unlabelled. Sits BEFORE the A5 GARBAGE
  // terminal gate on purpose: a garbage doc gets its FOUND_UNKNOWN label exactly
  // once, then the gate holds it terminal forever. The ACTION_LOG marker is the
  // re-fire guard; Gmail re-adding an already-present label is a harmless no-op.
  // SOURCE_TYPE matched by inclusion ('GMAIL', thin 'GMAIL_ATTACHMENT' /
  // 'GMAIL_LINK') - same normalisation 'Selection & Scoring Logic1' applies.
  // BALANCE_SHEET-typed docs are excluded: the BS pipes own their mail labels.
  // [resolve_double 2026-08-06] ADJUDICATE BEFORE LABELLING. True while this row still
  // owes a merge decision for its current business key. A row about to be merged must not
  // be labelled first: the loser becomes a tombstone (labelling it is false), and the
  // winner's TYPE is only final after the merge. Defers B2's gate by exactly one sweep;
  // it fires normally once merge_key is stamped, so no mail ends up unlabelled.
  const __mergePending = (function () {
    const d = normDoc._dup;
    if (!d || !d.bizKey) return false;
    // [perf 2026-08-18] blank guard: JSON.parse('') ALWAYS throws; returning true here is
    // byte-identical to that catch path, without a thrown exception per context-less row.
    if (!normDoc.DOUBLE_LINE_CONTEXT) return true;
    try {
      const c = JSON.parse(normDoc.DOUBLE_LINE_CONTEXT || '');
      return !(c && c.merge_sig && c.merge_key === d.bizKey);
    } catch (e) { return true; }
  })();
  // [source feedback 2026-08-21] ONE GATE, replacing the separate gmail-label and failed-folder
  // gates that used to sit here. Those two answered the same question -- "tell the source what
  // happened to its document" -- in two vocabularies, each hardcoding half the answer: the mail
  // half could only say "saved" or "unknown", the drive half could only say "failed", and NEITHER
  // could speak for a source the row acquired through a merge, because both read the row's single
  // SOURCE_* columns. This one reads SOURCE_LIST, so it speaks for every source a document has.
  //
  // WHAT DECIDE IS AND IS NOT DOING HERE. It does not parse SOURCE_LIST -- 'Enrich Double Lines'
  // already reduced it to __feedback_idx (the lowest-index source still owing feedback) and
  // __feedback_key (that element's identity). Decide's own job is the half SQL cannot answer:
  // is this document FINISHED, and did it finish well?
  //
  // POSITION IS LOAD-BEARING, and is the position the two old gates held: after the MERGED
  // tombstone gate (a loser must never file as its own source -- its sources feed back through
  // the winner) and BEFORE the A5 GARBAGE terminal gate, so a garbage document is filed exactly
  // once before that gate holds it terminal forever. Deferred while __mergePending for the same
  // reason as before: a row about to become a tombstone must not report a verdict it will not own.
  if (!__mergePending
      && normDoc.__source_feedback_enabled === true
      && normDoc.__feedback_idx !== null && normDoc.__feedback_idx !== undefined) {
    const _o = __feedbackOutcome(normDoc);
    if (_o !== 'pending') {
      const _i = Number(normDoc.__feedback_idx);
      // The index becomes part of the action NAME, which the double-action guard keys on, so it
      // must stay small and bounded. A row with 20+ sources is a data fault, not a workload.
      if (!(_i >= 0 && _i < 20))
        return { json: { ACTION: 'no_action_source_list_overflow', DOC_TYPE: resolveDocType(normDoc.TYPE), ...normDoc } };
      return { json: { ACTION: 'source_feedback_' + _i,
                       SOURCE_IDX: _i,
                       SOURCE_KEY: normDoc.__feedback_key || '',
                       FEEDBACK_OUTCOME: _o,
                       DOC_TYPE: resolveDocType(normDoc.TYPE), ...normDoc } };
    }
  }
  // [failed-folder 2026-08-07] THE DRIVE HALF OF THE SAME SIGNAL.
  // Blind sync moves a file to \`synced\` at DELIVERY, before any verdict exists, and
  // syncV3Deliver0001's 'Fail Label Route' excludes src_kind 'drive' outright — so a
  // document that ends badly leaves NO trace in Drive at all and \`synced\` asserts the
  // opposite of the truth. v1 filed it in the pair's \`failed\` folder (SyncProcGDoc0001
  // 'Move To Processed Documents - Fails'); this restores that from the only place that
  // knows the verdict. NEEDS_REVIEW files too: it is where a retry-exhausted document
  // comes to rest, and it is exactly the pile an operator goes to Drive to find.
  // Sits BESIDE the gmail-label gate, before the A5 GARBAGE terminal gate, for the same
  // reason it does: a GARBAGE document must be filed once before that gate holds it
  // terminal forever.
  // DEFERRED WHILE A MERGE IS PENDING, same as the label gate — a loser about to become
  // a tombstone must not be filed as this pipe's failure.
  // THIN ONLY, and that is scope, not a limitation: the folder is resolved from
  // settings.sync_registry BY SYNC_NAME, and only a thin delivery writes SYNC_NAME —
  // SyncProcGDoc0001 hardcodes 'drive-gdoc' for all three gdoc pipes, so a proc row
  // cannot say which pipe, or which failed folder, it belongs to.
  // (the drive half of that signal is the same gate above -- see 'source feedback 2026-08-21')
  {
    // [A5] GARBAGE is terminal — strictly before every other gate. Base extraction
    // marks <3-word documents TYPE='GARBAGE' (blank page / unreadable fragment); such
    // a document must never be dispatched again: not to figure_company_id (there is no
    // company on a blank page), not to extract_base_doc (never re-OCR'd), not to type
    // routing. If its STATUS is anything sweepable (e.g. someone flipped it to
    // ACTION_RESTART or IN_PROGRESS in a bulk re-drive), re-terminalize it via
    // update_status_garbage; once STATUS='GARBAGE' it is a pure no-op.
    const _tg = String(normDoc.TYPE || '').toUpperCase();
    if (_tg === 'GARBAGE')
      return { json: { ACTION: normDoc.STATUS === 'GARBAGE' ? 'no_action_garbage' : 'update_status_garbage', DOC_TYPE: 'garbage', ...normDoc } };
  }
  {
    // [restart epoch 2026-08-17, owner order] _iter counts stamps AFTER the last restart marker,
    // not lifetime: ACTION_RESTART is the sanctioned re-run and opens a fresh 25-step budget
    // (the dup-guard already treats the last restart as an epoch boundary — same semantics).
    // Before this, restarts never reset the counter, so bulk restart cycles permanently consumed
    // doc budgets: 194 docs retired to MAX_ITERATIONS in one day of scale tests with RETRY_COUNT=0.
    // A genuine runaway still burns >= _maxIter distinct attempts INSIDE its epoch and still stops.
    const _iter = __logInfo(normDoc).iterCount;

    // [#24 owner 2026-08-15] ONE ceiling: 25 steps per line, ever. Canonical key first, legacy
  // key second, explicit 25 last -- config never reaches the decide path (proven), so the
  // literal IS the owner's number, not a silent default.
  // [2026-09-02] 25 dispatches since the last restart. The counter is REAL now (the driver
  // computes it from the dispatch log; see __logInfo), so the number matters again: an invoice's
  // full happy path is ~13 distinct dispatches (base, select_base, name, short id, rename, office
  // check, link, per-type, doc id, select_type, priority, completed, feedback), and the double-
  // action guard already blocks a repeat of the same action on an unchanged line — so 25 is a
  // runaway ceiling, never a budget a healthy document can exhaust. Wrongly retiring a document
  // to MAX_ITERATIONS is the failure that has actually bitten here (194 in one day), so it errs high.
  let _maxIter = 25; try { _maxIter = Number(__CFG().max_iterations_per_doc) || Number(__CFG().max_actions_per_doc) || 25; } catch (e) {}
// [P3 2026-08-11] Conditional, was unconditional. _maxIter moved above this guard so the
// ceiling can be TESTED here rather than assumed. With P1's distinct counting live, 348 of
// the 356 parked rows are under the cap -- 289 finishers, 336 typed and companied -- retired
// by log duplication (5.5-6.2x, worst 67x), not by genuinely exhausting 50 attempts.
// A real runaway still has >= _maxIter DISTINCT attempts and still stops here.
// [dead-letter honoured 2026-08-13] THE STATUS THE ERROR HANDLER WROTE MUST BE BELIEVED.
// _iter and RETRY_COUNT are two DIFFERENT counters and only one of them was consulted here.
// RETRY_COUNT is incremented by the failure handlers themselves -- errorHandler01/'Backoff +
// Dead-letter' and indoxV2ActionsGlobal01/'Record Base Doc Failure' -- and BOTH of them stamp
// STATUS='MAX_ITERATIONS' the moment it reaches 5. _iter counts distinct ACTION_LOG stamps and
// is written by nobody; 'mark_max_iterations' (below) sets the same STATUS without ever touching
// RETRY_COUNT. So the two ways into MAX_ITERATIONS are cleanly separable, and this gate was only
// honouring the second one.
// Consequence measured live 2026-08-13: doc_msly5hcz9p9ngj (a 235-byte, ZERO-PAGE PDF that OCR
// can never read -- "the first page (1) can not be after the last page (0)") sat at
// STATUS='MAX_ITERATIONS' with RETRY_COUNT 47->56 while _iter was 15. 15 < 50, so this gate fell
// through and the driver re-dispatched it every ~4 minutes FOREVER, two failed n8n executions per
// cycle (Base Document Extraction + Upload Doc To API TOOLS), ~30/hour of permanent error floor.
// It was not alone: 22 MAX_ITERATIONS rows were re-dispatched in the last hour, RETRY_COUNT 9..95.
// The drainer already excludes MAX_ITERATIONS from pickup, so these rows were never meant to run;
// they only kept running because the driver's continuation loop re-decides them here.
// THRESHOLD IS NOT A NEW NUMBER. 5 is exactly the count at which the estate's own handlers write
// this STATUS, so honouring it introduces no policy -- the gate simply believes the dead-letter it
// was already given.
// P3's RESCUE SET IS PRESERVED. [P3 2026-08-11] made this conditional to save rows falsely parked
// by log duplication rather than genuine exhaustion. Measured across all 362 MAX_ITERATIONS rows:
// every row carrying a 'STATUS COMPLETED' stamp (11 of them) sits at RETRY_COUNT = 0, as do 27
// rows in total, plus 10 more at 1-4 -- all of them below this bound and all still rescued.
// The 325 rows at RETRY_COUNT >= 5 have no completion stamp between them.
// ACTION_RESTART remains the operator's per-document escape hatch, so this stays reversible.
let _maxRetry = 25; try { _maxRetry = Number(__CFG().max_iterations_per_doc) || Number(__CFG().max_retries_per_doc) || 25; } catch (e) {}
if (normDoc.STATUS === 'MAX_ITERATIONS' && (_iter >= _maxIter || Number(normDoc.RETRY_COUNT || 0) >= _maxRetry))
      return { json: { ACTION: 'no_action_max_iterations', DOC_TYPE: resolveDocType(normDoc.TYPE), ...normDoc, ITERATION_COUNT: _iter } };    // [completed-not-reversible 2026-08-10] THE CEILING MUST NEVER UN-FINISH A DOCUMENT.
    // _iter counts 13-digit timestamps in ACTION_LOG, i.e. every action the document has
    // EVER received -- not how many are still owed. A document that legitimately needed
    // many steps crosses 50 and was then terminalised INTO MAX_ITERATIONS AFTER it had
    // already completed. Measured live 2026-08-10: 12 rows sit in MAX_ITERATIONS carrying
    // a 'STATUS COMPLETED' stamp and in 10 of them the completion stamp comes FIRST in the
    // append-only ACTION_LOG, so the order is evidence, not inference (most recent
    // doc_msmqlyointleaa, 15:10:03Z -- ongoing, not historical). MAX_ITERATIONS is excluded
    // from pickup eligibility, so each reversal is permanent and destroys finished client work.
    //
    // The two protected states are exactly the pair errorHandler01/'Backoff + Dead-letter'
    // already refuses to touch (STATUS NOT IN ('COMPLETED','OLD')) -- the estate's existing
    // terminal-protection set, not a new one. MERGED and GARBAGE are already guarded above.
    //
    // DELIBERATELY a suppression of this gate only, NOT an early return. A COMPLETED row is
    // re-admitted by the pickup's s_adj slice on purpose, for double adjudication; returning
    // 'no_action_already_completed' here would cut that off, and that action has no output on
    // 'DOC BASE Action Switch' (checked -- it would fall through to Stop and Error).
    // Suppressing the ceiling instead makes a COMPLETED row behave exactly as it already does
    // when its ACTION_LOG happens to be shorter, which is the behaviour that is not broken.
    const _terminalKeep = ['COMPLETED', 'OLD'].includes(String(normDoc.STATUS || '').toUpperCase());
    // [restart grant 2026-08-17, owner order] STATUS='ACTION_RESTART' IS the epoch grant.
    // The bulk flip is plain SQL and stamps nothing, so _iter still counts the OLD epoch and
    // this ceiling fired before the restart action could stamp 'ACTION=restart' — a circular
    // trap that re-retired 310 docs inside one wave (flip → mark_max_iterations in one hop).
    // An explicitly restarted doc gets to run its restart action; that stamp anchors the new
    // epoch and the ceiling re-arms for everything after it. Genuine runaways still burn
    // >= _maxIter distinct stamps INSIDE the fresh epoch and still stop here.
    const _restartGrant = String(normDoc.STATUS || '').toUpperCase() === 'ACTION_RESTART';
    if (_iter >= _maxIter && !_terminalKeep && !_restartGrant)
      return { json: { ACTION: 'mark_max_iterations', DOC_TYPE: resolveDocType(normDoc.TYPE), ...normDoc, ITERATION_COUNT: _iter } };
  }
  const dup = doc._dup || { match: false };
  const docBaseAction = docBaseDecide(normDoc, dup);
  if (docBaseAction) return { json: { ACTION: docBaseAction, DOC_TYPE: resolveDocType(normDoc.TYPE), ...normDoc } };
  const docType = resolveDocType(normDoc.TYPE);
  const typeAction = _ROUTE[docType] || unknownTypeAction(normDoc);
  return { json: { ACTION: typeAction, DOC_TYPE: docType, ...normDoc } };
}

return __items.map(item => {
  // [B6 2026-08-06] supabase TEXT-boolean safety -- the SAME normalisation
  // 'Decide GDoc Action' has always had, and this node never did. Every
  // *_COMPLETED column is TEXT, so the literal string 'false' arrives here as
  // a NON-EMPTY string, and every guard in docBaseDecide/unknownTypeAction is
  // written as \`!doc.X_COMPLETED\` -- JS truthiness. 'false' is truthy, so an
  // explicitly-not-completed row read as COMPLETED and silently skipped its
  // step. Measured at the time of the fix: FIGURE_COMPANY_COMPLETED='false'
  // on 878 rows (all already had a COMPANY_ID, so zero impact on that gate
  // today), COMPANY_NAME_COMPLETED='false' on 911, FIGURE_TYPE_COMPLETED=
  // 'false' on 874 -- those two feed get_company_name and
  // figure_document_type through this same unnormalised decider. Same class
  // as the conditional-stamp bug: harmless only until the column is written
  // with an explicit false.
  const d = item.json;
  for (const k of Object.keys(d)) {
    if (typeof d[k] === 'string') {
      const s = d[k].trim().toLowerCase();
      if (s === 'true') d[k] = true; else if (s === 'false') d[k] = false;
    }
  }
  // [owner 2026-08-15: "simply filter all old"] THE gate, at THE entry -- before any routing,
  // for every status except the three tombstones. Proven necessary by the all-rows decide census:
  // with the gate one function deeper, 2,255 old docs (373 already OLD) still routed to type
  // routers and kept being processed.
  const __oldMonths = (() => {
    // [row-carried settings 2026-08-31] Same chain as the late gate's OLD_MONTHS: the row value
    // the driver's enrich stamped (__old_months) first, __CFG second, the owner's 6 last.
    try { const r = Number(d.__old_months); if (Number.isFinite(r) && r > 0) return r; } catch (e) {}
    try { const v = Number(__CFG().old_document_months_back); if (Number.isFinite(v) && v > 0) return v; } catch (e) {}
    return 6;   // the owner's stated scope -- explicit because Companies never runs on this path
  })();
  const __tomb = ['MERGED', 'GARBAGE', 'DOUBLE'].includes(String(d.STATUS || '').toUpperCase());
  // [owner 2026-08-15] ALL date fields, corruption-aware: anyOldDate itself now rejects
  // implausible years and per-document swap-mangles, so every field participates and corrupt
  // values can neither forge old nor block ageing. (Reverts the trusted-fields narrowing.)
  // [2026-08-25] LOCAL_DOC_DATE added here for the same reason as the late gate: it gives the
  // corruption rules the sibling they need to recognise an AI year-misread. See anyOldDate.
  const __oldReason = __tomb ? null : anyOldDate(
    [d.RECEIVED_DATE, d.DOC_DATE, d.AI_DOC_DATE, d.BS_LINE_DATE, d.LOCAL_DOC_DATE], __oldMonths,
    ['RECEIVED_DATE', 'DOC_DATE', 'AI_DOC_DATE', 'BS_LINE_DATE', 'LOCAL_DOC_DATE']);
  if (__oldReason) {
    const act = (String(d.STATUS || '') === 'OLD') ? 'no_action_old_date' : 'update_status_old_doc';
    const o = { json: { ACTION: act, DOC_TYPE: resolveDocType(d.TYPE), ...d, IS_OLD: true,
                        OLD_REASON: JSON.stringify(__oldReason) } };
    delete o.json.mode;
    delete o.json._dup;
    return o;
  }
  const out = docBaseRouterDecide(d);
  delete out.json.mode;
  delete out.json._dup;
  return out;
});

}
const __mode = String((($input.first()||{}).json||{}).mode || '');
if (__mode === 'export_decide') return [{ json: { fnSrc: __docBaseDecideFn.toString() } }];
return __docBaseDecideFn($input.all());`,
    };

    @node({
        id: 'dbroutemode01',
        name: 'Route Mode',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [-1120, -16],
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
        id: '339f4197-d2a0-4a0d-b3dd-fdc52c9cb9eb',
        name: 'Stop and Error - Unhandled DOC BASE ACTION',
        type: 'n8n-nodes-base.stopAndError',
        version: 1,
        position: [-400, 2528],
    })
    StopAndErrorUnhandledDocBaseAction = {
        errorMessage:
            "=Unhandled ACTION '{{ $json.ACTION }}' in indoxV2ActionsGlobal01 — 'DOC BASE Action Switch' matched no case and no explicit fallback. Document ID: {{ $json.ID }}. This item would otherwise have been silently dropped (G41).",
    };

    @node({
        id: 'extract-base-doc-entry-01',
        name: 'Action: Extract Base Doc',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-400, 1664],
    })
    ActionExtractBaseDoc = {};

    @node({
        id: 'call-basedocex01-01',
        name: 'Call BaseDocEx01',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [112, 1520],
        onError: 'continueRegularOutput',
    })
    CallBasedocex01 = {
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
                ID: '={{ $json.ID }}',
                LINK: '={{ $json.LINK }}',
                HASH: '={{ $json.HASH }}',
                LINK_CONNECTION: '={{ $json.LINK_CONNECTION }}',
                NAME: '={{ $json.NAME }}',
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
        id: 'build-base-doc-upsert-01',
        name: 'Build Base Doc Upsert',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [880, 1664],
    })
    BuildBaseDocUpsert = {
        assignments: {
            assignments: [
                {
                    id: 'unlock-0014-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0050-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'bdu-instance',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        includeOtherFields: true,
        options: {},
    };

    @node({
        id: 'rd-noop-resolve-double-0001',
        name: 'Action: Resolve Double',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-400, 320],
    })
    ActionResolveDouble = {};

    @node({
        id: 'rd-code-build-group-fetch-01',
        name: 'Build Group Fetch',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-144, 320],
    })
    BuildGroupFetch = {
        jsCode: `// [resolve_double] One bounded GET covering every group this dispatch implicates.
// The (COMPANY_ID, DOC_ID) regroup happens client-side in 'Adjudicate Merge' (DOC_ID is not
// whitelisted yet); a partially-pushed-down filter group is always a SUPERSET of the true match
// set, so fetching wider than the key is safe -- fetching NARROWER than it is not.
//
// [2026-08-23] FETCH BY HASH TOO, or a hash-keyed duplicate can never be adjudicated.
// The detector (driver dbl CTE) groups on biz -> hash -> comp. This node asked only by
// COMPANY_ID, so a pair whose ONLY shared key is HASH -- no COMPANY_ID, no DOC_ID -- produced
// zero filters, returned _empty, and the adjudicator saw no rows: no group, no verdict, no
// status written, and the detector raised the same pair again on the very next sweep. Proven
// with a two-row hash-only fixture: the non-main reached DOUBLE and the main sat in
// ACTION_RESTART across repeated drains, forever.
// biz and comp both require a COMPANY_ID, so the company filter still covers them; this only
// adds the hash tier. Both filters are emitted when a row has both -- a twin may share the hash
// under a DIFFERENT company, which a company-only fetch would also have missed.
// HASH is on the api's COLS whitelist, so this pushes down to SQL rather than widening the scan.
const companies = new Set();
const hashes = new Set();
const blank = v => v === undefined || v === null || String(v).trim() === '';
for (const it of $input.all()) {
  const j = (it && it.json) || {};
  if (!blank(j.COMPANY_ID)) companies.add(String(j.COMPANY_ID).trim());
  // Mirror the detector's hash predicate exactly: a real hash, and not a balance-sheet line
  // (a BS line legitimately shares its document's hash and must never be merged away).
  const h = blank(j.HASH) ? '' : String(j.HASH).trim();
  if (h !== '' && h.toLowerCase() !== 'unknown' && blank(j.LINKED_BS)) hashes.add(h);
}
const filters = [...companies].map(c => ({ COMPANY_ID: c }))
  .concat([...hashes].map(h => ({ HASH: h })));
// __instance selects the SCHEMA. This fetch feeds the duplicate detector, so unscoped it would
// pull another instance's rows into a merge group -- and MERGE below deletes losers.
let INST = '';
try { INST = String(($('When Called').first().json || {}).__instance || ''); } catch (e) { INST = ''; }
if (!filters.length) return [{ json: { _empty: true } }];
return [{ json: { INLINE_ACTION: 'GET', filters: filters, __instance: INST } }];
`,
    };

    @node({
        id: 'rd-exec-fetch-group-000001',
        name: 'Fetch Group',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [112, 320],
        alwaysOutputData: true,
        retryOnFail: true,
    })
    FetchGroup = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
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
        id: 'rd-code-adjudicate-merge-01',
        name: 'Adjudicate Merge',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [368, 320],
    })
    AdjudicateMerge = {
        jsCode: `// [resolve_double 2026-08-06] adjudicate every implicated (COMPANY_ID, DOC_ID) group.
// Inputs: $input = fresh rows for every implicated company (from 'Fetch Group');
//         $('Action: Resolve Double') = the ACTION lines that triggered this dispatch.
// Verdicts (final-indox.md CHANGE 3):
//   <=1 live candidate                                -> promote (collision resolved elsewhere)
//   <=1 distinct REAL hash across the group           -> auto-merge  (no contradicting content
//                                                        evidence; two distinct non-blank hashes
//                                                        cannot coexist under uq_incdoc_hash, so
//                                                        this is the same-hash tier)
//   exactly 2 rows agreeing on TYPE+DOC_DATE+amount   -> auto-merge  (blank agrees with anything)
//   otherwise                                         -> confirm DOUBLE, queue for review
// A merge NEVER deletes: the MERGE op is executed by the api writer, losers keep their rows.
// Every member gets DOUBLE_LINE_CONTEXT.merge_sig so the decide gate stays silent until the
// group's composition changes again.
const trig = $('Action: Resolve Double').all().map(i => i.json);
const rows = $input.all().map(i => i.json).filter(r => r && r.ID !== undefined && r.ID !== null && r.ID !== '' && !r._empty);
const SEP = '';
const isBlank = v => [null, undefined, '', 'unknown'].includes((String(v ?? '')).toLowerCase());
function bizDocIdOf(doc) {
  const v = !isBlank(doc.DOC_ID) ? doc.DOC_ID : null;
  if (isBlank(v)) return null;
  const s = String(v).trim();
  if (['unknown','action_required','null','none'].includes(s.toLowerCase())) return null;
  const alnum = s.replace(/[^a-zA-Z0-9]/g, '');
  if (alnum.length < 3 || /^0+$/.test(alnum)) return null;
  if (!isBlank(doc.COMPANY_ID) && String(doc.COMPANY_ID).trim() === s) return null;
  return s;
}
// [2026-08-23] THE GROUPING KEY MUST MIRROR THE DETECTOR, or a group can be raised forever and
// never adjudicated. The driver's dbl CTE matches on biz -> hash -> comp, in that order. This
// node grouped on the BUSINESS key alone, so a row with a HASH but no COMPANY_ID/DOC_ID (18 of
// them live, measured 2026-08-23) was skipped at the continue below: no group formed, the
// verdict emitted nothing, no status was written, and the detector raised it again next sweep --
// 8 action_merge_doubles dispatches per row and no possible end.
// Same precedence, same predicates as the SQL.
function groupKeyOf(doc) {
  const v = bizDocIdOf(doc);
  if (v !== null && !isBlank(doc.COMPANY_ID)) return 'biz' + SEP + String(doc.COMPANY_ID).trim() + SEP + v;
  const h = String(doc.HASH == null ? '' : doc.HASH).trim();
  if (h !== '' && h.toLowerCase() !== 'unknown' && isBlank(doc.LINKED_BS)) return 'hash' + SEP + h;
  const sd = String(doc.SHORT_DOC_ID == null ? '' : doc.SHORT_DOC_ID).trim();
  if (!isBlank(doc.COMPANY_ID) && sd !== '' && !/^0+$/.test(sd)) {
    return 'comp' + SEP + String(doc.COMPANY_ID).trim() + SEP + sd;
  }
  return null;
}
const targets = new Set();
for (const t of trig) {
  const k = groupKeyOf(t);
  if (k !== null) targets.add(k);
}
// quarantine re-check on the FRESH rows: doc-id under 3+ companies never auto-adjudicates
const companiesPerDocId = new Map();
for (const r of rows) {
  const v = bizDocIdOf(r);
  if (v === null || isBlank(r.COMPANY_ID)) continue;
  if (!companiesPerDocId.has(v)) companiesPerDocId.set(v, new Set());
  companiesPerDocId.get(v).add(String(r.COMPANY_ID).trim());
}
const groups = new Map();
for (const r of rows) {
  if (String(r.STATUS || '') === 'MERGED') continue;
  const k = groupKeyOf(r);
  if (k === null) continue;
  // the 3+ companies quarantine is a BUSINESS-key rule: one doc id shared across three companies
  // is a bad id, not a duplicate. It cannot apply to a hash key, where a shared hash is the same
  // bytes and says nothing about companies.
  if (k.startsWith('biz' + SEP)) {
    const v = bizDocIdOf(r);
    if (v !== null && (companiesPerDocId.get(v) || new Set()).size >= 3) continue;
  }
  if (!targets.has(k)) continue;
  if (!groups.has(k)) groups.set(k, []);
  groups.get(k).push(r);
}
const completeness = r => Object.entries(r).reduce((n, [k, v]) => n + (/_COMPLETED$/.test(k) && String(v).toLowerCase() === 'true' ? 1 : 0), 0);
// [2026-08-23] STATUS RANK OUTRANKS COMPLETENESS, and the order matters more than it looks.
// It used to sort completeness FIRST, so an OLD row that had been fully extracted before it aged
// (3 completion flags) beat a COMPLETED row with 1 -- and the merge demoted a deliverable
// document to OLD. Measured at volume: 54 COMPLETED rows absorbed into non-COMPLETED survivors,
// 52 of them into OLD, all reverted from STATUS_BEFORE_MERGE. No extraction was lost (the
// survivor was always as complete or more) but the document dropped out of the deliverable set,
// which is the outcome that reaches the client.
// COMPLETED is the terminus a document is meant to reach; nothing merges it backwards.
const statusRank = r => (r.STATUS === 'COMPLETED' ? 2 : (r.STATUS === 'OLD' ? 0 : 1));
const pickWinner = cands => [...cands].sort((a, b) =>
  (statusRank(b) - statusRank(a)) ||
  (completeness(b) - completeness(a)) ||
  String(a.created_at || '~').localeCompare(String(b.created_at || '~')) ||
  String(a.ID).localeCompare(String(b.ID)))[0];
// [C4 2026-08-21] THE NORMALISERS ARE DEFINED ONCE, HERE, AND BOTH SIDES USE THEM.
//
// They were written on 2026-08-13 for the conflict veto and left declared INSIDE the loop below,
// so fieldsAgree -- twenty lines above, out of scope -- kept comparing RAW STRINGS. The two halves
// of the same decision therefore disagreed about what "the same value" means: the veto knew that
// '07/07/2025' and '2025-07-07T09:12:00' are one day and that 'INVOICE' and 'invoice' are one
// type, while fieldsAgree read both as a disagreement and withheld the merge.
//
// That asymmetry is worth 1,229 duplicate groups on this table -- auto-merge goes 2,127 -> 3,356
// once the two sides agree on the vocabulary. Hoisting them is the whole fix; the bodies are
// unchanged, and now a group can never be simultaneously "not conflicted" and "does not agree".
const _dkey = (r) => {
  const raw = String(r.DOC_DATE ?? '').trim() || String(r.BS_LINE_DATE ?? '').trim();
  if (!raw) return null;
  let m = raw.match(/^(\\d{4})-(\\d{2})-(\\d{2})/);            // ISO / ISO-with-time
  if (m) return m[1] + '-' + m[2] + '-' + m[3];
  m = raw.match(/^(\\d{1,2})[\\/.](\\d{1,2})[\\/.](\\d{4})/);   // D/M/YYYY or D.M.YYYY
  if (m) return m[3] + '-' + String(m[2]).padStart(2,'0') + '-' + String(m[1]).padStart(2,'0');
  return null;                                                // unparseable -> unknown, not a veto
};
const _akey = (r) => {
  const raw = String((isBlank(r.DOC_TOTAL_AMOUNT) ? r.TOTAL_AMOUNT : r.DOC_TOTAL_AMOUNT) ?? '').trim()
           || String(r.BS_LINE_AMOUNT ?? '').trim();
  if (!raw) return null;
  const s = raw.replace(/[^0-9.\\-]/g, '');
  if (!/^-?[0-9]+(\\.[0-9]+)?$/.test(s)) return null;          // '1.414.00' etc -> unknown
  return Math.abs(Math.round(parseFloat(s) * 100) / 100).toFixed(2);
};
// [C5 2026-08-21] WHY THIS DOCUMENT EVER HAD A TWIN.
//
// Merging removes a duplicate; it does not explain one. Without a cause the backlog is an
// undifferentiated pile of 4,714 groups, and the preventions cannot be prioritised or, afterwards,
// shown to have worked. DUP_CAUSE is stamped on the WINNER before anything is absorbed, so it
// survives the merge and turns the pile into a ranked defect list.
//
// The rules are ordered by how much they PROVE, strongest first, and every one of them is derived
// from the row data alone -- the same derivation that produced the offline census, so the live
// stamp and that census cannot drift.
//
// LOWER-BOUND CAVEAT, stated rather than hidden: 'Fetch Group' pulls rows for the companies in THIS
// dispatch, so the cross-company doc-id test can only see those companies. It under-reports
// BAD_DOC_ID and never over-reports it -- a doc id shared across companies outside this dispatch
// falls through to a later rule instead. The shape tests below need no such context.
const DUP_CAUSES = ['SAME_FILE_SAME_CHANNEL','SAME_FILE_CROSS_CHANNEL','RESCAN','BLIND_WINDOW',
                    'BS_LINE_PAIR','BAD_DOC_ID','CONFLICT_REAL_DOCS','UNCLASSIFIED'];
const _JUNK_DOCID = [
  [/^d{1,2}[./-]d{1,2}[./-]d{2,4}$/, 'a date'],
  [/^d{4}-d{2}-d{2}/,                   'a date'],
  [/^5d{8}$/,                             'a company number'],
  [/^[A-Za-z]+$/,                          'purely alphabetic'],
];
const _NO_ID_AT_BIRTH = ['GOOGLE_DRIVE_FOLDER','GOOGLE_DRIVE_FILE','MAIL_ATTACHMENT','WHATSAPP'];
const _isBsLine = (r) => String(r.SOURCE_TYPE || '').toUpperCase() === 'BALANCE_SHEET'
                      || (isBlank(r.HASH) && !isBlank(r.BS_LINE_AMOUNT));
function dupCause(cands, coCount) {
  const docid = String((cands[0] || {}).DOC_ID || '').trim();
  if (coCount >= 3) return 'BAD_DOC_ID';
  for (const [rx] of _JUNK_DOCID) if (rx.test(docid)) return 'BAD_DOC_ID';
  const alnum = docid.replace(/[^0-9A-Za-z]/g, '');
  if (alnum.length < 3) return 'BAD_DOC_ID';

  // A demonstrated disagreement means these are DIFFERENT documents that merely share a key.
  // Same evidence the conflict veto uses, so a group can never be both merged and CONFLICT.
  const ds = new Set(), as = new Set();
  for (const c of cands) { const d = _dkey(c); if (d) ds.add(d); const a = _akey(c); if (a) as.add(a); }
  if (ds.size > 1 || as.size > 1) return 'CONFLICT_REAL_DOCS';

  const someBs = cands.some(_isBsLine), allBs = cands.every(_isBsLine);
  if (someBs && !allBs) return 'BS_LINE_PAIR';   // a ledger line and its document: LINK, never merge-away

  const hashes = new Set(cands.filter(c => !isBlank(c.HASH)).map(c => String(c.HASH).trim()));
  const types  = new Set(cands.map(c => String(c.SOURCE_TYPE || '').toUpperCase()));
  if (hashes.size === 1 && cands.length > 1)
    return types.size > 1 ? 'SAME_FILE_CROSS_CHANNEL' : 'SAME_FILE_SAME_CHANNEL';
  if (hashes.size > 1 && ds.size && as.size) return 'RESCAN';  // different bytes, one document
  for (const t of types) if (_NO_ID_AT_BIRTH.indexOf(t) >= 0) return 'BLIND_WINDOW';
  return 'UNCLASSIFIED';
}
const fieldsAgree = (a, b) => {
  // Only a value present on BOTH sides and genuinely different disagrees. A missing value is
  // UNKNOWN, never agreement and never a veto -- the same rule the conflict check applies.
  const t = r => String(r.TYPE ?? '').trim().toUpperCase();
  const ta = t(a), tb = t(b);
  if (ta && tb && ta !== tb) return false;
  const da = _dkey(a), db = _dkey(b);
  if (da && db && da !== db) return false;
  const aa = _akey(a), ab = _akey(b);
  if (aa && ab && aa !== ab) return false;
  return true;
};
// A single trigger row is the NORMAL case now (single-row trigger): \`groups\` then holds
// that row plus every DB twin sharing its key. One candidate => promote + stamp, which
// is what stops the gate re-firing forever on a document that simply has no twin.
const out = [];
// [winner status 2026-08-22, owner order] The winner is the line decide ACTS ON, so the action
// must leave it somewhere the state machine can continue from. Emitting only
// DOUBLE_LINE_CONTEXT left it in the status it arrived in, so the gate handed it the same
// action next sweep -- 3,352 documents pinned in ACTION_RESTART, some since 2026-08-18.
// Only PARKED statuses resume: a winner that is COMPLETED or OLD has finished its lifecycle
// and must not be dragged back into the pipeline by a duplicate verdict.
const RESUME = s => ['DOUBLE','ACTION_RESTART'].indexOf(String(s || '').toUpperCase()) >= 0;
const nowMs = Date.now();
const execId = (typeof $execution !== 'undefined' && $execution.id) || '';
for (const [k, cands] of groups) {
  const sig = cands.map(c => String(c.ID) + ':' + String(c.HASH || '')).sort().join('|');
  // [owner rule 2026-08-23] NO PROMOTE. One candidate means nothing to merge; the row is simply
  // not double and decide will route it normally on the next sweep. Emitting a "promoted" verdict
  // was a third outcome that existed only to carry a marker, and the marker is gone.
  if (cands.length < 2) continue;
  const realHashes = new Set(cands.map(c => c.HASH).filter(h => h && String(h).trim() !== '' && String(h).toLowerCase() !== 'unknown'));
  const winner = pickWinner(cands);
  const losers = cands.filter(c => String(c.ID) !== String(winner.ID));
  const sameHash = realHashes.size <= 1;
  const twoAgree = cands.length === 2 && fieldsAgree(cands[0], cands[1]);

  // [conflict veto 2026-08-13] A DEMONSTRATED DISAGREEMENT OUTRANKS EVERY MERGE RULE.
  // Normalised, and BS-aware: a balance-sheet line keeps its date in BS_LINE_DATE and its amount
  // in BS_LINE_AMOUNT, so comparing only DOC_* reads them as blank and blank was being treated as
  // agreement. Dates are compared as parsed calendar days because the same day is stored as
  // '07/07/2025' by Drive and '2025-07-07T..' by Gmail; amounts as abs(round(x,2)) because 39
  // pairs are sign-flipped and thousands separators vary. Only a value present on BOTH sides and
  // genuinely different vetoes -- a missing value is unknown, never agreement.
  // (_dkey / _akey are defined once at the top of this node — see the C4 note there. They used to
  // be declared here, which is exactly why fieldsAgree could not see them.)
  const _distinct = (fn) => { const s = new Set(); for (const c of cands) { const v = fn(c); if (v !== null) s.add(v); } return s.size; };
  const conflicted = _distinct(_dkey) > 1 || _distinct(_akey) > 1;

  // How many companies this dispatch has seen using this doc id (see the lower-bound caveat on
  // dupCause). The rows array is every row the group fetch returned for the implicated companies.
  const _docid = String((cands[0] || {}).DOC_ID || '').trim();
  const _coCount = _docid
    ? new Set(rows.filter(r => String(r.DOC_ID || '').trim() === _docid)
                  .map(r => String(r.COMPANY_ID || '').trim()).filter(Boolean)).size
    : 0;
  const _cause = dupCause(cands, _coCount);

  // [owner rule 2026-08-23] ALWAYS MERGE. There is one outcome, not four.
  // The double action does not carry the complexity of deciding whether a duplicate is "real":
  // conflicted values and bad doc-ids are RECORDED in dup_cause and merged anyway. reason keeps
  // the tier for the audit trail. Removed with this: the conflicted veto, the keep-apart branch
  // that parked losers as DOUBLE, and the promote branch above -- three ways for a group to end
  // without ending, each of which needed a marker to stop it being re-raised.
  // __instance selects the SCHEMA. MERGE is the most destructive op in this file -- it folds
  // losers into a winner -- so an unscoped one would merge across tenants. Read from the trigger.
  let _inst = '';
  try { _inst = String(($('When Called').first().json || {}).__instance || ''); } catch (e) { _inst = ''; }
  out.push({ json: { INLINE_ACTION: 'MERGE', winner_id: String(winner.ID),
    loser_ids: losers.map(l => String(l.ID)),
    reason: sameHash ? 'same-hash' : (twoAgree ? 'two-rows-agree' : 'forced'),
    conflicted: conflicted,
    dup_cause: _cause, __instance: _inst } });

}
// Every target key that produced NO adjudicable group (quarantined doc-id, or every
// candidate already MERGED) must STILL be stamped, or the decide gate sees an
// unstamped key and re-dispatches resolve_double on every sweep forever - the _noop
// path writes no ACTION_LOG, so the max-iterations guard never trips either.
for (const k of targets) {
  if (groups.has(k)) continue;
  const t = trig.find(x => {
    const v = bizDocIdOf(x);
    return v !== null && !isBlank(x.COMPANY_ID)
        && (String(x.COMPANY_ID).trim() + SEP + v) === k;
  });
  if (!t || !t.ID) continue;
  out.push({ json: { ID: String(t.ID),
    // [2026-08-23] DUP_CAUSE, not just the context blob. This branch has always stamped
    // merge_sig -- which is precisely what the OLD gate read. The gate now reads DUP_CAUSE
    // (a fingerprint cannot survive a member's HASH arriving late), so stamping only the blob
    // left this exit unmarked and it re-dispatched forever: doc_mso9vde17abj30 took
    // action_merge_doubles 5x in 5 minutes with DUP_CAUSE NULL and
    // {"unadjudicable":"no eligible candidate group"} in its context. Same failure the comment
    // above predicts, reached through the one branch that was not updated with the gate.
    DUP_CAUSE: 'BAD_DOC_ID',
    DOUBLE_LINE_CONTEXT: JSON.stringify({ merge_sig: 'none', merge_key: k,
      unadjudicable: 'no eligible candidate group (quarantined doc-id, or all candidates merged)' }) } });
}
if (!out.length) return [{ json: { _noop: true } }];
return out;`,
    };

    @node({
        id: 'rd-if-merge-or-update-0001',
        name: 'Merge or Update?',
        type: 'n8n-nodes-base.if',
        version: 2,
        position: [624, 320],
    })
    MergeOrUpdate = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'rd-if-merge',
                    leftValue: "={{ $json.INLINE_ACTION === 'MERGE' }}",
                    rightValue: true,
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
        id: 'rd-exec-call-merge-000001',
        name: 'Call MERGE',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [880, 320],
        retryOnFail: true,
    })
    CallMerge = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
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
        id: 'a5-garbage-noop-0000-000000000001',
        name: 'Action: Update Status GARBAGE',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-400, 1952],
    })
    ActionUpdateStatusGarbage = {};

    @node({
        id: 'a5-garbage-loop-0000-000000000002',
        name: 'Loop (garbage)',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [-144, 1952],
    })
    LoopGarbage = {
        batchSize: 1000,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: 'a5-garbage-build-0000-00000000003',
        name: 'Build: Status GARBAGE',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [112, 1808],
    })
    BuildStatusGarbage = {
        assignments: {
            assignments: [
                {
                    id: 'gw0',
                    name: 'ID',
                    value: "={{ $('Action: Update Status GARBAGE').item.json.ID }}",
                    type: 'string',
                },
                {
                    id: 'gw1',
                    name: 'STATUS',
                    value: 'GARBAGE',
                    type: 'string',
                },
                {
                    id: 'gw2',
                    name: 'ERROR',
                    value: '={{ $json.error || null }}',
                    type: 'string',
                },
                {
                    id: 'unlock-0010-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0046-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-0046-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'sfb-act-0001',
        name: 'Action: Source Feedback',
        /*__n8n__*/ notes: "[source feedback 2026-08-21] REPLACES 'Action: Apply Gmail Labels' AND 'Action: File To Failed Folder'. Those two answered the same question -- tell the source what happened to its document -- in two vocabularies, each hardcoding half the answer: the mail half could only say 'saved' or 'unknown', the drive half could only say 'failed', and NEITHER could speak for a source the row acquired through a merge, because both read the row's single SOURCE_* columns. This lane reads SOURCE_LIST, so it speaks for every source a document has, and the DESTINATION comes from settings.sync_registry -- the pipe's own synced/failed folder or labels.synced/labels.failed key -- so re-pointing a pipe re-points the feedback with it.",
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-400, 2528],
    })
    ActionSourceFeedback = {};

    @node({
        id: 'sfb-regreq-0002',
        name: 'Registry Req (Feedback)',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-144, 2528],
    })
    RegistryReqFeedback = {
        jsCode: `// The pipe's destinations live in settings.sync_registry -- the SAME row syncV3Main0001 reads --
// so a Drive folder id or a label key is never hardcoded here.
// INSTANCE is the row-level app instance (a settings COLUMN); __instance is the TENANT that
// selects the schema. [tenant-carry 2026-08-31] The old note here claimed these v2 lanes "do
// not carry one yet" -- they do now: every caller stamps the batch, and post-cutover a
// TABLE_GET on a per-instance table without __instance is refused, which silently killed all
// source feedback (this executor continues-on-fail). Read it from the request boundary.
const INSTANCE = 'incoming-documents-main';
let __inst = ''; try { __inst = String(($('When Called').first().json || {}).__instance || ''); } catch (e) {}
return [{ json: { INLINE_ACTION: 'TABLE_GET', table: 'settings', instance: INSTANCE,
                  __instance: __inst, filter: { key: 'sync_registry' } } }];`,
    };

    @node({
        id: 'sfb-regget-0003',
        name: 'Get Registry (Feedback)',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [112, 2528],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    GetRegistryFeedback = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'sfb-rulesreq-0004',
        name: 'Tag Rules Req (Feedback)',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [368, 2528],
    })
    TagRulesReqFeedback = {
        jsCode: `// The label VOCABULARY lives in ONE store: the mail app's organizer settings (owner Decision N1
// 2026-09-03) — the same store the label engine evaluates and mailapi's search resolves through.
// The registry names the KEY (labels.synced = 'SYNCED_DOC'); the store turns it into the Hebrew
// label the mailbox actually carries. Hebrew names are NEVER hardcoded in a workflow. Emits one
// {KEY, LABEL} row per key, the shape the tag_rules TABLE_GET used to answer with.
let rows = [];
try {
  const o = await this.helpers.httpRequest({ method: 'GET', url: 'http://mailapi:8970/organizer/settings', json: true, timeout: 15000 });
  const L = (((o || {}).gmail || {}).labels) || {};
  for (const [k, v] of Object.entries(L)) if (v && v.name) rows.push({ json: { KEY: String(k), LABEL: String(v.name) } });
} catch (e) {
  rows = [{ json: { KEY: null, LABEL: null, error: 'organizer settings unreachable: ' + String((e && e.message) || e).slice(0, 200) } }];
}
return rows.length ? rows : [{ json: { KEY: null, LABEL: null } }];`,
    };


    @node({
        id: 'sfb-linesreq-0006',
        name: 'Lines Req (Feedback)',
        /*__n8n__*/ notes: "SOURCE_LIST is re-read HERE rather than carried from decide. Two reasons. (1) SIZE: it is the fattest column on the table -- 26 MB total, avg 692 B/row, 1.37 MB per 2,000-row decide slice -- and the driver deliberately strips it from the decide payload, because the worker aborts at Node's 2,600 MB V8 ceiling long before the container's 4 GB and a fat column on a hot path shows up as OOM rather than as slowness. (2) FRESHNESS: this group is at most 150 documents, and a copy carried since decide could have been overtaken by another action. The action must act on what the row says NOW.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [880, 2528],
    })
    LinesReqFeedback = {
        jsCode: `const ids = [];
for (const it of $('Action: Source Feedback').all()) {
  const id = it.json && it.json.ID;
  if (id && ids.indexOf(String(id)) < 0) ids.push(String(id));
}
// An impossible filter rather than an unfiltered GET: a whole-table read here would return an
// ARBITRARY document and the lane would act on it.
// __instance selects the SCHEMA. Without it this reads public, and since document IDs are
// per-instance sequences an ID filter can match a DIFFERENT tenant's document of the same id --
// which is the same failure the '__never__' guard above exists to prevent, one level subtler.
let INST = '';
try { INST = String(($('When Called').first().json || {}).__instance || ''); } catch (e) { INST = ''; }
if (!ids.length) return [{ json: { INLINE_ACTION: 'GET', filters: [{ ID: '__never__' }], __instance: INST } }];
return [{ json: { INLINE_ACTION: 'GET', filters: ids.map(id => ({ ID: id })), __instance: INST } }];`,
    };

    @node({
        id: 'sfb-linesget-0007',
        name: 'Get Lines (Feedback)',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1136, 2528],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    GetLinesFeedback = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'sfb-ops-0008',
        name: 'Build Feedback Ops',
        /*__n8n__*/ notes: "One item per document, each carrying the op for ONE source -- the element at SOURCE_IDX. THE INDEX IS A DISPATCH LABEL, NOT A PROOF: decide also stamped SOURCE_KEY (source_kind|file_id-or-message_id) and this node refuses to act unless the element still under that index matches it, because SOURCE_LIST is a jsonb array and an action that trusted a stale index would tag the wrong mail or move the wrong file. Every refusal is RECORDED on the element and the action still completes -- 'stamp the marker anyway and record why' is the contract that stopped the 2026-08-21 trap, where a permanently-failing move never wrote its flag, was re-decided every sweep, and was then parked as DOUBLE ACTION BLOCKED on 19 documents.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1392, 2528],
    })
    BuildFeedbackOps = {
        jsCode: `// ---- registry ----------------------------------------------------------------
let registry = [];
for (const r of $('Get Registry (Feedback)').all().map(i => i.json).filter(Boolean)) {
  if (String(r.key || '') !== 'sync_registry') continue;
  try { const v = r.value; registry = typeof v === 'string' ? JSON.parse(v) : (v || []); } catch (e) {}
}
// If the registry read failed or returned nothing, emit NOTHING. No document may be marked fed
// back when no destination could even be resolved -- the gate simply re-fires on a later sweep.
// Same contract the two lanes this replaces used.
if (!Array.isArray(registry) || !registry.length) return [];
const entryBy = {};
for (const e of registry) if (e && e.name) entryBy[String(e.name)] = e;

// ---- label vocabulary ---------------------------------------------------------
const byKey = {};
for (const r of $('Tag Rules Req (Feedback)').all().map(i => i.json).filter(x => x && x.KEY)) {
  byKey[String(r.KEY)] = String(r.LABEL || '').trim();
}

// ---- fresh rows ---------------------------------------------------------------
const fresh = new Map();
for (const it of $input.all()) {
  const j = it.json || {};
  if (j.ID) fresh.set(String(j.ID), j);
}

// The type-specific success keys the gmail lane has always used. Only consulted when the pipe's
// registry entry does not name its own labels.synced -- so a pipe that wants one flat "synced"
// label gets it, and a pipe that says nothing keeps today's SAVED_INVOICE / SAVED_SHIPMENT.
const typeKey = (t) => {
  const u = String(t || '').toUpperCase();
  if (['INVOICE', 'ORDER', 'CENTRALIZED_INVOICE'].includes(u)) return 'SAVED_INVOICE';
  if (u === 'SHIPMENT') return 'SAVED_SHIPMENT';
  return 'FOUND_UNKNOWN';
};

const out = [];
for (const it of $('Action: Source Feedback').all()) {
  const d = it.json || {};
  const id = String(d.ID || '');
  const idx = Number(d.SOURCE_IDX);
  const want = String(d.SOURCE_KEY || '');
  const outcome = String(d.FEEDBACK_OUTCOME || '');
  const row = fresh.get(id) || d;
  const list = Array.isArray(row.SOURCE_LIST) ? row.SOURCE_LIST : [];
  const el = list[idx] || null;
  const emit = (err, op, dest) => out.push({ json: {
    ID: id, SOURCE_IDX: idx, FEEDBACK_OUTCOME: outcome,
    FEEDBACK_OP: op || null, FEEDBACK_DEST: dest || null, FEEDBACK_ERROR: err || null,
    // The whole list travels to the Build node so it can patch ONE element and write the array
    // back without re-reading. Null when there is no element to patch.
    FEEDBACK_LIST: el ? list : null,
  } });

  if (!Number.isFinite(idx) || idx < 0) { emit('decide sent no usable SOURCE_IDX'); continue; }
  if (!el) { emit('SOURCE_LIST[' + idx + '] does not exist on the row (it has ' + list.length + ' source(s))'); continue; }

  // IDENTITY CHECK. SOURCE_LIST is append-only by contract, but a contract is not a guarantee:
  // if anything ever reorders it, acting on the index alone would file the wrong document.
  const got = String(el.source_kind || '') + '|' + String(el.file_id || el.message_id || '');
  if (want && got !== want) {
    emit('the source at index ' + idx + ' changed since decide (expected ' + want + ', found ' +
         got + ') -- refusing to act on a different source'); continue;
  }
  if (el.sync_feedback_completed === true) { emit(null, null, el.sync_feedback_dest || null); continue; }

  const mode = String(el.required_feedback_type || '');
  if (!mode) { emit('this source has no feedback channel'); continue; }
  if (outcome === 'success' && el.feedback_on_success !== true) { emit("pipe does not report successes"); continue; }
  if (outcome === 'failure' && el.feedback_on_failure !== true) { emit("pipe does not report failures"); continue; }

  const entry = entryBy[String(el.sync_registry_name || '')];
  if (!entry) { emit("sync_registry has no entry named '" + String(el.sync_registry_name || '') + "'"); continue; }

  if (mode === 'drive_move') {
    const pairs = entry.pairs || [];
    // WHICH PAIR. A pipe may scan several folder pairs and each has its own synced/failed, so the
    // document must say which one it came from. source_folder_id is that discriminator. Falling
    // back to the single pair is safe only when there IS only one; with several and no match the
    // lane REFUSES rather than guessing -- the same rule the failed-folder lane adopted on
    // 2026-08-21, kept because it is the one that cannot file a document into a stranger's folder.
    let pair = pairs.filter(p => p && String(p.to_sync || p.from || '') === String(el.source_folder_id || ''))[0];
    if (!pair && pairs.length === 1) pair = pairs[0];
    if (!pair) {
      emit("cannot tell which of " + pairs.length + " pairs of pipe '" + entry.name +
           "' this document came from (source_folder_id=" + String(el.source_folder_id || '-') +
           ") -- refusing to guess"); continue;
    }
    const dest = outcome === 'success' ? (pair.synced || pair.to) : (pair.failed || pair.failed_to);
    if (!dest) { emit("pipe '" + entry.name + "' has no " + (outcome === 'success' ? 'synced' : 'failed') + " folder"); continue; }
    // Already where it belongs: complete with the destination recorded and no Drive call. This is
    // the whatsapp-bot / drive-bs shape, where to_sync and the outcome folder are the same folder.
    if (String(dest) === String(el.source_folder_id || '')) { emit(null, null, String(dest)); continue; }
    if (!el.file_id) { emit('no Drive file id on this source'); continue; }
    if (!el.link_connection) { emit('no Drive connection on this source'); continue; }
    emit(null, { kind: 'drive_move', op: 'move', params: {
      fileId: String(el.file_id), toFolderId: String(dest),
      connection_id: String(el.link_connection) } }, String(dest));
  } else if (mode === 'mail_tag') {
    const labels = entry.labels || {};
    const key = outcome === 'success' ? (labels.synced || typeKey(row.TYPE))
                                      : (labels.failed || 'FOUND_UNKNOWN');
    // a key with no rule is used literally (the same rule syncV3Main0001's lname() applies):
    // the registry editor picks keys from the organizer store, and a suite's own label
    // (sv3i_synced) is its own name.
    const label = byKey[key] || String(key);
    if (!label) { emit("no label key on this pipe for outcome " + outcome); continue; }
    if (!el.message_id) { emit('no message id on this source, so there is nothing to tag'); continue; }
    // The MAILBOX must come from the work item, never from mailapi's process-wide active pointer:
    // an implicit fallback is how a client's mail got labelled from the wrong account before.
    const conn = el.sync_connection || entry.connection || entry.connection_id;
    if (!conn) { emit('no mailbox connection for this source'); continue; }
    // The to-sync label is the pipe's SCOPE ("waiting for the automation"); a handled message leaves
    // it the way a drive file leaves to_sync for synced. One call: mailapi's /labels/add takes a
    // 'remove' list (2026-09-03). Never remove the label just written, and nothing when the pipe
    // has no to-sync key (a suite's own registry).
    const toSyncKey = String(labels.to_sync || '');
    const toSyncLabel = toSyncKey ? (byKey[toSyncKey] || toSyncKey) : '';
    const remove = (toSyncLabel && toSyncLabel !== label) ? [toSyncLabel] : [];
    emit(null, { kind: 'mail_tag', op: 'addLabels', params: {
      id: String(el.message_id), labelIds: [label], remove, connection_id: String(conn) } }, key);
  } else {
    emit("unknown feedback mode '" + mode + "'");
  }
}
return out;`,
    };

    @node({
        id: 'sfb-loop-0009',
        name: 'Loop (feedback)',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [1648, 2528],
    })
    LoopFeedback = {
        batchSize: 150,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: 'sfb-route-0010',
        name: 'Route Feedback Op',
        type: 'n8n-nodes-base.switch',
        version: 3.3,
        position: [1904, 2384],
    })
    RouteFeedbackOp = {
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
                                id: 'sfb-r1',
                                leftValue: '={{ ($json.FEEDBACK_OP || {}).kind }}',
                                rightValue: 'drive_move',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'drive_move',
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
                                id: 'sfb-r2',
                                leftValue: '={{ ($json.FEEDBACK_OP || {}).kind }}',
                                rightValue: 'mail_tag',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'mail_tag',
                },
            ],
        },
        options: {
            fallbackOutput: 'extra',
        },
    };

    @node({
        id: 'sfb-move-0011',
        name: 'Move To Feedback Folder',
        /*__n8n__*/ notes: "[onError from day one, 2026-08-21] THE ACTION MUST ALWAYS COMPLETE. Its predecessor 'Move To Failed Folder' shipped without onError and that single omission became the trap of 2026-08-21: driveApi01 threw, the branch aborted before the Build node, so the completion flag was never written, the gate re-decided the same action next sweep, and the double-action guard parked 19 documents -- while one bad destination failed a whole batch of 10 across three pipes, 9 of which had healthy destinations. continueRegularOutput means the failure is recorded on the element and the lane moves on.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [2160, 2432],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
        retryOnFail: true,
        waitBetweenTries: 5000,
    })
    MoveToFeedbackFolder = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'move',
                params: '={{ ({ fileId: $json.FEEDBACK_OP.params.fileId, toFolderId: $json.FEEDBACK_OP.params.toFolderId, connection_id: $json.FEEDBACK_OP.params.connection_id }) }}',
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
        id: 'sfb-label-0012',
        name: 'Apply Feedback Label',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [2160, 2624],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
        retryOnFail: true,
        waitBetweenTries: 5000,
    })
    ApplyFeedbackLabel = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'addLabels',
                params: '={{ ({ id: $json.FEEDBACK_OP.params.id, labelIds: $json.FEEDBACK_OP.params.labelIds, remove: $json.FEEDBACK_OP.params.remove || [], connection_id: $json.FEEDBACK_OP.params.connection_id }) }}',
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
        id: 'sfb-build-0013',
        name: 'Build: Source Feedback',
        /*__n8n__*/ notes: "Patches ONE element of SOURCE_LIST and writes the array back. THE ORDERING CONSTRAINT THIS NODE USED TO CARRY IS RETIRED (2026-08-21): a whole-array write is no longer a read-modify-write race, because indoxApi01's 'Build Bulk Upsert SQL' now writes SOURCE_LIST through public.indox_merge_source_list instead of EXCLUDED -- an incoming element patches the element with the same source identity, new ones are appended, and an element the incoming array does not mention is KEPT. Proven on a live row 2026-08-21: seed a second source, upsert an array naming only the first, result length 2 with element 0 patched and element 1 intact (EXCLUDED semantics would have left length 1). So merging and source feedback can now be enabled together; the append this node would once have erased survives.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2416, 2528],
    })
    BuildSourceFeedback = {
        jsCode: `// One upsert payload per document: the patched SOURCE_LIST, the lock release, nothing else.
// The action ALWAYS completes -- a refusal or an API failure is recorded on the element rather
// than left for the gate to re-decide, which is what turns a broken destination into a permanent
// double-action park instead of a visible, explained error.
const out = [];
for (const it of $input.all()) {
  const j = it.json || {};
  // $json.error is set by the executeWorkflow nodes under onError:continueRegularOutput.
  const src = $('Build Feedback Ops').item.json || {};
  const apiErr = j.error ? String(j.error.message || j.error) : null;
  const err = apiErr || src.FEEDBACK_ERROR || null;
  const list = Array.isArray(src.FEEDBACK_LIST) ? src.FEEDBACK_LIST.slice() : null;
  const idx = Number(src.SOURCE_IDX);
  const now = new Date().toISOString();

  if (!list || !list[idx]) {
    // No element to patch (it vanished, or decide sent an index the row does not have). Record
    // the fact on the row and release the lock -- writing a SOURCE_LIST here would invent one.
    out.push({ json: { ID: src.ID, ERROR: err || 'source element missing at upsert time',
                       unlock: true, INLINE_ACTION: 'UPSERT' } });
    continue;
  }
  list[idx] = Object.assign({}, list[idx], {
    sync_feedback_completed: true,
    // 'refused' is deliberately distinct from success/failure: it records that the lane declined
    // to act, not that the document failed.
    sync_feedback_outcome: err ? 'refused' : String(src.FEEDBACK_OUTCOME || ''),
    sync_feedback_dest: src.FEEDBACK_DEST || null,
    sync_feedback_error: err,
    sync_feedback_at: now,
  });
  // __instance selects the SCHEMA this UPSERT writes to. Built objects drop everything not named.
  let _inst = '';
  try { _inst = String(($('When Called').first().json || {}).__instance || ''); } catch (e) { _inst = ''; }
  out.push({ json: { ID: src.ID, SOURCE_LIST: list, ERROR: err || null,
                     unlock: true, INLINE_ACTION: 'UPSERT', __instance: _inst } });
}
return out;`,
    };

    @node({
        id: 'select-base-values-stage1',
        name: 'Select Base Values',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [368, 1664],
    })
    SelectBaseValues = {
        jsCode: `// [two-point STAGE 1 2026-08-07] ROUTER-OWNED SELECTION STEP.
//
// The extractor's only job is provenance (LOCAL_*/AI_*); the ROUTER owns the verdict.
// This node sits AFTER the extractor call and BEFORE the upsert build, in the base
// router and in every per-type router -- the same shape in all four.
//
// STAGE 1 is deliberately redundant: BaseDocEx01/InvoiceDocEx01/ShipmentDocEx01/
// BsDocEx01 still run their own \`Select\` and still emit the VAL columns. This node
// recomputes them from the same LOCAL_*/AI_* inputs with the same precedence, so the
// answer is identical and the move can be proven before the extractor side is stripped
// in Stage 2. The equivalence oracle is SELECTION_DEBUG_BASE / SELECTION_DEBUG_PERTYPE:
// its distribution must not change.
//
// PRECEDENCE -- carried verbatim from BaseDocEx01/'Select Base'. Single source present
// wins outright, no confidence contest, never a blocked document. \`prefer\` exists ONLY
// because BsDocEx01/'Select (BS)' deliberately reverses the tie-break: balance sheets
// are AI-led with local supplementing 'where it helps', per the owner's framing. That
// reversal is a PARAMETER, not a fourth copy of this function.
const has = v => v !== null && v !== undefined && String(v).trim() !== '';
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

// [commit-per-document 2026-08-10] DETERMINISTIC PAIRING, NEVER \`.item\` FROM A
// run-once-for-ALL-items CODE NODE.
// This node runs in "Run Once for All Items" mode, so \`$('X').item\` has no current
// item to pair against and resolves to item 0 of X's run for EVERY iteration of the
// .map() below. That is the same footgun 'Select Base' (BaseDocEx01) documents: it
// broadcast one document's API_TOOLS_ID onto 601 others on 2026-08-09. It was latent
// here for exactly the same reason -- \`Action: Extract Base Doc\` carried the whole
// batch (13 items in execution 846218), so __prevRow was item 0's row 13 times over,
// and __prevRow feeds the fill-only API_TOOLS_ID precedence and the retry marker.
//
// 'Loop (base doc)' is a splitInBatches with batchSize 1, so its CURRENT RUN holds
// exactly the one document this iteration is about. Index pairing against it is exact,
// not inferred. If the counts ever disagree the pairing is REFUSED rather than guessed,
// and the ID equality guard below makes a silent re-attribution impossible.
const __rows = $input.all();
let __loop = null;
try { __loop = $('Loop (base doc)').all(); } catch (e) { __loop = null; }
function __prevFor(i, d) {
  let p = null;
  if (__loop && __loop.length === __rows.length) {
    p = (__loop[i] && __loop[i].json) || {};
  } else if (__rows.length === 1) {
    // no loop in front of this node: a single item makes \`.item\` unambiguous.
    try { p = $('Action: Extract Base Doc').item.json || {}; } catch (e) { p = {}; }
  } else {
    throw new Error('Select Base Values: item-count mismatch (input=' + __rows.length +
      ', Loop Base Doc=' + (__loop ? __loop.length : 'unavailable') + '). Refusing to pair ' +
      'by index -- this is the shape that stamps one document\\'s values onto another.');
  }
  if (p && p.ID != null && d && d.ID != null && String(p.ID) !== String(d.ID)) {
    throw new Error('Select Base Values: identity mismatch (row=' + p.ID + ', extractor=' +
      d.ID + '). Refusing to write one document\\'s extraction onto another.');
  }
  return p || {};
}
// Sanitisers for the failure record. Single quotes are STRIPPED, not escaped, so the
// value can never terminate the SQL literal in 'Record Base Doc Failure'.
const __sqlText = v => String(v == null ? '' : v).replace(/[^\\x20-\\x7E]/g, ' ').replace(/'/g, '').slice(0, 180);
const __sqlId   = v => String(v == null ? '' : v).replace(/[^A-Za-z0-9_.:-]/g, '');

// Base router: COMPANY_ID / TYPE / DOC_DATE.
return __rows.map((item, __i) => {
  const d = item.json || {};
  const __prevRow = __prevFor(__i, d);

  // [commit-per-document 2026-08-10] A STAGE THAT PRODUCED NO ANSWER IS A FAILURE,
  // AND A FAILURE MUST BE RECORDED. Three ways this pass can come back empty:
  //   * the sub-call itself failed -- 'Call BaseDocEx01' is onError:continueRegularOutput,
  //     so a thrown sub-workflow (or a cancellation) arrives here as { error: ... };
  //   * the extractor returned an item with no identity;
  //   * the extractor succeeded but the upload leg produced no API_TOOLS_ID and no field
  //     was extracted -- e.g. apitools shed the OCR with HTTP 429, or the file is gone.
  // Previously ALL THREE were stamped BASE_EXTRACTION_COMPLETED = true, which asserts an
  // ANSWER on behalf of a stage that only ATTEMPTED one
  // (issues/completion-flags-record-attempts-not-answers.yaml), or -- when the parent
  // timed out first -- were never written at all. Both leave the row unchanged and
  // unrecorded, so the pickup re-dispatches it forever with RETRY_COUNT still 0.
  const __subErr = (d.error === undefined || d.error === null)
    ? null : String((d.error && d.error.message) || d.error);
  const __fail = (reason) => ({ json: {
    ID: __sqlId(__prevRow.ID != null ? __prevRow.ID : d.ID),
    BASE_FAIL_REASON: __sqlText(reason),
  }});
  if (__subErr) return __fail('sub-workflow error: ' + __subErr);
  if (!has(d.ID)) return __fail('extractor returned no document identity');

  const out = { ...d };

  const companyPick = pick(d.LOCAL_COMPANY_ID, d.AI_COMPANY_ID, 'LOCAL');
  const datePick    = pick(d.LOCAL_DOC_DATE,   d.AI_DOC_DATE,   'LOCAL');
  // [B34 2026-08-09] TYPE is picked on REAL answers first, so a confident AI type beats a
  // local non-answer. THE FALLBACK PRESERVES THE OLD BEHAVIOUR EXACTLY when NEITHER leg
  // gave a real type: the raw pick returns the same value and the same source it always
  // did, so out.TYPE and the CONDITIONAL STAMP below are byte-identical for those rows.
  // Without it, the 121 rows already settled on UNKNOWN would lose FIGURE_TYPE_COMPLETED
  // and be re-opened into figure_document_type -- a resolver measured at 0 usable types in
  // 77 runs (final-indox.md B33.3). This fix rescues answers; it does not re-open settled
  // rows, and the stamp still fires only on a genuine resolution.
  let typePick = pick(realType(d.LOCAL_TYPE), realType(d.AI_TYPE), 'LOCAL', canonType);
  // [type-priority 2026-08-24, owner order] indox.extraction.type_priority (settings row,
  // loaded by 'Load Company Resolver Gen'; LOCAL = the historical behaviour and the safe
  // default when the row or the read is missing). AI overrides the pick ONLY when BOTH
  // engines returned a REAL type and they disagree -- a lone answer still wins as before,
  // whatever the setting says. Recorded in SELECTION_DEBUG_BASE as DISAGREE_PREFER_AI.
  let __typePri = 'LOCAL';
  try { __typePri = String($('Load Company Resolver Gen').first().json.type_priority || 'LOCAL').toUpperCase(); } catch (e) {}
  if (__typePri === 'AI' && typePick.val) {
    const __lt = canonType(realType(d.LOCAL_TYPE));
    const __at = canonType(realType(d.AI_TYPE));
    if (__lt && __at && String(__lt) !== String(__at)) typePick = { val: __at, source: 'DISAGREE_PREFER_AI' };
  }
  if (!typePick.val) typePick = pick(d.LOCAL_TYPE, d.AI_TYPE, 'LOCAL', canonType);

  // [pure extraction 2026-08-25, owner order] THIS NODE NO LONGER WRITES THE FINALS.
  // It kept a second, diverged copy of the base selection -- one that overwrote the extractor's
  // answer while silently dropping the extractor's two guards (the NAME_MATCH company leg and the
  // future-date refusal). Both copies are gone: select_base owns the decision, this node owns what
  // it is actually good at, which is deciding whether the extraction pass produced ANYTHING and
  // classifying the failure when it did not. The picks below are computed for exactly that test.

  // [two-point rule 2026-08-17, owner order] UNCONDITIONAL STAMP. Extraction happens at
  // exactly TWO points — base (BaseDocEx01) and per-type — and a document that has been
  // through base HAS been through the only sanctioned company resolution. The legacy
  // indoxV2FigureCompanyId01 (its own Upload+OCR + sender/NAME maps) must never fire
  // again; a companyless doc after base falls to figure_company_offline (filename, no
  // OCR) and then terminalizes MISSING_COMPANY_ID for the operator. Previous behaviour
  // (stamp only on resolved value, so the "stronger resolver" still ran) is the
  // two-point violation the owner closed. TYPE keeps the conditional stamp: its
  // fallback IS a sanctioned per-type route (extract_invoice_google_ai).
  out.FIGURE_COMPANY_COMPLETED = true;
  // [two-point rule 2026-08-17] TYPE stamp unconditional too: figure_document_type and the
  // standalone AI fallback are removed from decide; base is the only type resolver.
  out.FIGURE_TYPE_COMPLETED = true;

  // [base-point API_TOOLS_ID 2026-08-09] FILL-ONLY. BaseDocEx01/'Select Base'
  // already supplies the apitools id (it starts at Upload+OCR, and the /docExists
  // hash short-circuit returns file_id too, so both upload paths yield one). It is
  // the ONLY source for a balance sheet -- indoxV2ActionsBS01 has no
  // get_api_tools_id. What it must never do is REPLACE an id the row already has:
  // 5,694 rows carry one and are still queued for extract_base_doc. Precedence is
  // existing-value-wins, read from the pre-extraction row exactly the way the
  // sibling 'Build Base Doc Upsert' node reads it. On neither side present the key
  // is DELETED, not nulled, so the upsert leaves the column untouched.
  const __atid = (has(__prevRow.API_TOOLS_ID) ? String(__prevRow.API_TOOLS_ID).trim()
                : has(d.API_TOOLS_ID)         ? String(d.API_TOOLS_ID).trim()
                : null);
  if (__atid) out.API_TOOLS_ID = __atid; else delete out.API_TOOLS_ID;

  // [no state-machine retries 2026-08-17, owner order] The 'BASE APITOOLS RETRY' marker stamp
  // is gone with the docBaseDecide retry branch it bounded.

  // [commit-per-document 2026-08-10] NO ANSWER -> NO COMPLETION FLAG, A RECORDED REASON
  // INSTEAD. An API_TOOLS_ID is an answer in its own right (it is what unlocks the AI
  // path and it is the ONLY source a balance sheet ever gets one from), so any one of
  // the four is enough to count this pass as progress.
  if (!__atid && !companyPick.val && !typePick.val && !datePick.val)
    {
    // [clear-reasons 2026-08-17, owner order] every unextractable doc carries a CLASSIFIED
    // cause, not a generic shrug. The leg statuses hold the real error text — classify it.
    const __legs = (String(d.LOCAL_STATUS || '') + ' | ' + String(d.AI_STATUS || ''));
    let __why = 'no field extracted and no upload id';
    if (/Unsupported file format/i.test(__legs)) __why = 'bad file type (OCR: unsupported format)';
    else if (/source_gone|File not found|404/i.test(__legs)) __why = 'broken link (source file gone from drive)';
    else if (/too large|exceeds|413/i.test(__legs)) __why = 'file too big for OCR';
    else if (/429|shed/i.test(__legs)) __why = 'apitools overloaded (request shed)';
    else if (/DNS|offline|aborted|ECONN|ETIMEDOUT/i.test(__legs)) __why = 'network/service unreachable during extraction';
    else if (/Bad request/i.test(__legs)) __why = 'apitools rejected the request (bad parameters)';
    else if (/first page .1. can not be after|zero.?page/i.test(__legs)) __why = 'corrupt/empty PDF (zero pages)';
    return __fail('unextractable: ' + __why + ' [legs: ' + __legs.slice(0, 100) + ']');
    }

  out.BASE_EXTRACTION_COMPLETED = true;

  // [commit-per-document 2026-08-10] CARRY THE PRE-EXTRACTION VALUES FORWARD HERE.
  // 'Build Base Doc Upsert' used to reach back to the branch head with a named-node
  // .item accessor for exactly these four. That accessor is now upstream of a loop and,
  // worse, its source node holds the whole batch -- so the fallback is resolved HERE
  // instead, against the identity-checked __prevRow. The computed values are
  // byte-identical to what that Set node produced; only the provenance of the fallback
  // changed, from inferred to exact.
  // The carry-forward that used to sit here is unnecessary now and was, in fact, the same act as
  // writing nothing: a field this node does not write is a key the upsert never sees, and
  // indoxApi01's clean() leaves such a column exactly as it was. SELECTION_DEBUG_BASE moved with
  // the decision it describes.
  // [a leg that failed is written on the row 2026-09-03] The pass produced an answer (so it is
  // not a failure), but a leg that answered 'failed: <reason>' must not vanish into a status
  // column nobody reads: 736 completed documents had no AI values and no error text because the
  // base AI leg recorded 'ran' on a rejected file. Same shape as the per-type lanes' ERROR.
  const __legFail = [];
  if (String(d.LOCAL_STATUS || '').indexOf('failed:') === 0) __legFail.push('local ' + String(d.LOCAL_STATUS).slice(0, 160));
  if (String(d.AI_STATUS || '').indexOf('failed:') === 0) __legFail.push('ai ' + String(d.AI_STATUS).slice(0, 160));
  if (__legFail.length) out.ERROR = ('base extraction: ' + __legFail.join(' | ')).slice(0, 500);
  return { json: out };
});
`,
    };

    @node({
        id: 'loop-base-doc-commit-01',
        name: 'Loop (base doc)',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [-144, 1664],
    })
    LoopBaseDoc = {
        options: {
            reset: "={{ $prevNode.name === 'Action: Extract Base Doc' }}",
        },
    };

    @node({
        id: 'basedoc-wrote-if-01',
        name: 'Base Doc Produced An Answer?',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [624, 1664],
    })
    BaseDocProducedAnAnswer = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: 'basedoc-wrote-cond-01',
                    leftValue:
                        '={{ String($json.BASE_EXTRACTION_COMPLETED == null ? "" : $json.BASE_EXTRACTION_COMPLETED).trim().toLowerCase() === "true" }}',
                    rightValue: 'true',
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
        id: 'v2upsert-basedoc-loop',
        name: 'Upsert (central) - Base Doc',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1136, 1664],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    UpsertCentralBaseDoc = {
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
        id: 'record-base-failure-01',
        name: 'Record Base Doc Failure',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [880, 1792],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    RecordBaseDocFailure = {
        operation: 'executeQuery',
        query: "=UPDATE {{ (() => { const i = String($('When Called').first().json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2ActionsGlobal01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.incoming_documents SET \"BASE_EXTRACTION_COMPLETED\" = 'true', \"STATUS\" = 'EXTRACTION_FAILED', \"REQUIRED_ACTION\" = 'base extraction produced no answer (see ERROR) - fix the file/link; ACTION_RESTART re-attempts once', \"ERROR\" = LEFT('extract_base_doc: {{ String($json.BASE_FAIL_REASON || '').replace(/['\",]/g, ';') }} @exec {{ $execution.id }}', 500) WHERE \"ID\" = '{{ $json.ID }}' AND \"STATUS\" NOT IN ('COMPLETED','OLD');",
        options: {},
    };

    @node({
        id: 'load-company-resolver-gen-01',
        name: 'Load Company Resolver Gen',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-1600, -16],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
        executeOnce: true,
    })
    LoadCompanyResolverGen = {
        operation: 'executeQuery',
        query: "=SELECT COALESCE((SELECT resolver_gen FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2ActionsGlobal01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.extraction_queries WHERE key='q_v3_company'), '') AS resolver_gen_company, UPPER(COALESCE((SELECT value FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2ActionsGlobal01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.settings WHERE key='indox.extraction.type_priority'), 'LOCAL')) AS type_priority",
        options: {},
    };

    @node({
        id: 'restore-router-payload-01',
        name: 'Restore Router Payload',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-1360, -16],
    })
    RestoreRouterPayload = {
        jsCode: `// The postgres node above replaces the router's items with its query row. Restore the
// documents before routing. Same idiom as indoxV2Upsert01/'Restore Payload'.
// 'When Called' has exactly one run, so this is exact, not inferred.

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

// [decide 30k 2026-08-17] Execution stamp, folded in from the retired 'Execution Data
// (router_doc_base)' node. That node re-evaluated every value-expression PER ITEM; four
// expressions scanned $input.all(), so cost was items^2 — hours at a 39k full-table
// decide batch. Folding it HERE adds zero node passes and zero retained copies: this node
// already materializes $('When Called').all(). Same keys, same execution_metadata table.
{
  const __f = (__all[0] || {}).json || {};
  const __ids = __all.map(i => String((i.json && i.json.ID) != null ? i.json.ID : '')).filter(Boolean);
  const __s = __ids.slice().sort();
  let __h = 2166136261;
  for (const __v of __s) { for (let __k = 0; __k < __v.length; __k++) { __h ^= __v.charCodeAt(__k); __h = Math.imul(__h, 16777619); } }
  const __u = [...new Set(__all.map(i => String((i.json && i.json.ACTION) != null ? i.json.ACTION : '')).filter(Boolean))];
  const __sj = __u.join(',');
  const __m = __mode || 'execute';
  const __cap = (v) => String(v).slice(0, 500);
  $execution.customData.setAll({
    exection_type: 'router_doc_base',
    trigger_type: __cap(__f.TRIGGER_TYPE || __f.trigger_type || 'sub_workflow'),
    trigger_chain: __cap(__f.TRIGGER_CHAIN || 'driver>router_doc_base'),
    origin_execution: __cap(__f.ORIGIN_EXECUTION || $execution.id),
    parent_execution: __cap(__f.PARENT_EXECUTION || ''),
    line_count: String(__all.length),
    ids: __cap('n=' + __ids.length + ' h=' + (__h >>> 0).toString(16) + ' s=' + __s.slice(0, 3).join(',')),
    actions: __cap(__sj.length > 380 ? (__u.length + ' actions: ' + __sj.slice(0, 360) + '...') : __sj),
    outline: __cap('router_doc_base_' + __m + '_x_' + __all.length + '_lines_x_' + __u.length + '_actions'),
  });
}
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
        id: 'selbase-action-01',
        name: 'Action: Select Base',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-400, 2200],
    })
    ActionSelectBase = {};

    @node({
        id: 'selbase-loop-01',
        name: 'Loop (select base)',
        /*__n8n__*/ notes: "batchSize 200: selection is pure computation over columns the row already holds, so it costs nothing per document and there is no reason to walk one at a time the way the extraction loop must. The reset expression is the standard guard against a finished batcher routing a fresh feed straight to Done.",
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [-176, 2200],
    })
    LoopSelectBase = {
        batchSize: 200,
        options: {
            reset: '={{ $prevNode.name === "Action: Select Base" }}',
        },
    };

    @node({
        id: 'selbase-call-01',
        name: 'Call SelectBase01',
        /*__n8n__*/ notes: "The selector itself lives in its own workflow so that exactly one implementation answers for every caller: this action, fullDocEx01, and the parity harness. That is the same rule the priority signature already follows -- a second copy drifts, and drift in a selector means two different answers about the same document.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [48, 2056],
        onError: 'continueRegularOutput',
    })
    CallSelectbase01 = {
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
        id: 'selbase-build-01',
        name: 'Build Select Base Upsert',
        /*__n8n__*/ notes: "The selector's answer, passed through as-is plus the two control keys the API strips. It writes ONLY fields it actually decided -- a value it declined to choose is absent, and indoxApi01's clean() drops absent keys, so 'no answer' leaves the column exactly as it was instead of blanking it.",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [272, 2200],
    })
    BuildSelectBaseUpsert = {
        assignments: {
            assignments: [
                {
                    id: 'sbu1',
                    name: 'unlock',
                    value: '={{ true }}',
                    type: 'boolean',
                },
                {
                    id: 'sbu2',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'sbu3',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
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
        this.WhenCalled.out(0).to(this.LoadCompanyResolverGen.in(0));
        this.ActionUpdateStatusUnknownCompany.out(0).to(this.BuildStatusUnknownCompany.in(0));
        this.LoopStatusOld.out(1).to(this.LoopStatusOld.in(0));
        this.LoopStatusOld.out(1).to(this.BuildStatusOldCompleted.in(0));
        this.LoopHandleDoubles.out(1).to(this.LoopHandleDoubles.in(0));
        this.LoopHandleDoubles.out(1).to(this.BuildStatusMissingCompanyIdDoubles.in(0));
        this.ActionUpdateStatusMissingCompanyId.out(0).to(this.LoopMissingCompany.in(0));
        this.ActionGetCompanyName.out(0).to(this.Companies.in(0));
        this.ActionGetCompanyName.out(0).to(this.JoinCompanyName.in(0));
        this.DocBaseActionSwitch.out(0).to(this.ActionRestartBase.in(0));
        this.DocBaseActionSwitch.out(1).to(this.ActionHandleDoubles.in(0));
        this.DocBaseActionSwitch.out(2).to(this.ActionResolveDouble.in(0));
        this.DocBaseActionSwitch.out(3).to(this.ActionUpdateStatusMissingCompanyId.in(0));
        this.DocBaseActionSwitch.out(4).to(this.ActionGetCompanyName.in(0));
        this.DocBaseActionSwitch.out(5).to(this.ActionUpdateStatusUnknownCompany.in(0));
        this.DocBaseActionSwitch.out(6).to(this.ActionUpdateStatusMissingType.in(0));
        this.DocBaseActionSwitch.out(7).to(this.ActionUpdateStatusOld.in(0));
        this.DocBaseActionSwitch.out(8).to(this.BuildMarkMaxIterations.in(0));
        this.DocBaseActionSwitch.out(9).to(this.ActionExtractBaseDoc.in(0));
        this.DocBaseActionSwitch.out(10).to(this.ActionUpdateStatusGarbage.in(0));
        this.DocBaseActionSwitch.out(11).to(this.ActionSourceFeedback.in(0));
        this.DocBaseActionSwitch.out(12).to(this.StopAndErrorUnhandledDocBaseAction.in(0));
        this.DocBaseActionSwitch.out(13).to(this.ActionSelectBase.in(0));
        this.ActionSelectBase.out(0).to(this.LoopSelectBase.in(0));
        this.LoopSelectBase.out(1).to(this.CallSelectbase01.in(0));
        this.LoopSelectBase.out(1).to(this.LoopSelectBase.in(0));
        this.CallSelectbase01.out(0).to(this.BuildSelectBaseUpsert.in(0));
        this.BuildSelectBaseUpsert.out(0).to(this.UpsertCentral.in(0));
        this.ActionUpdateStatusMissingType.out(0).to(this.LoopMissingType.in(0));
        this.LoopCompanyName.out(1).to(this.BuildCompanyName.in(0));
        this.LoopCompanyName.out(1).to(this.LoopCompanyName.in(0));
        this.ActionUpdateStatusOld.out(0).to(this.LoopStatusOld.in(0));
        this.ActionHandleDoubles.out(0).to(this.LoopHandleDoubles.in(0));
        this.LoopMissingType.out(1).to(this.LoopMissingType.in(0));
        this.LoopMissingType.out(1).to(this.BuildStatusMissingType.in(0));
        this.JoinCompanyName.out(0).to(this.LoopCompanyName.in(0));
        this.LoopMissingCompany.out(1).to(this.LoopMissingCompany.in(0));
        this.LoopMissingCompany.out(1).to(this.BuildStatusMissingCompanyId.in(0));
        this.BuildMarkMaxIterations.out(0).to(this.UpsertCentral.in(0));
        this.BuildStatusOldCompleted.out(0).to(this.UpsertCentral.in(0));
        this.BuildStatusUnknownCompany.out(0).to(this.UpsertCentral.in(0));
        this.BuildStatusMissingCompanyId.out(0).to(this.UpsertCentral.in(0));
        this.BuildStatusMissingType.out(0).to(this.UpsertCentral.in(0));
        this.BuildCompanyName.out(0).to(this.UpsertCentral.in(0));
        this.BuildStatusMissingCompanyIdDoubles.out(0).to(this.UpsertCentral.in(0));
        this.RouteMode.out(0).to(this.DecideDocBaseAction.in(0));
        this.RouteMode.out(1).to(this.DocBaseActionSwitch.in(0));
        this.ActionExtractBaseDoc.out(0).to(this.LoopBaseDoc.in(0));
        this.CallBasedocex01.out(0).to(this.SelectBaseValues.in(0));
        this.BuildBaseDocUpsert.out(0).to(this.UpsertCentralBaseDoc.in(0));
        this.ActionResolveDouble.out(0).to(this.BuildGroupFetch.in(0));
        this.BuildGroupFetch.out(0).to(this.FetchGroup.in(0));
        this.FetchGroup.out(0).to(this.AdjudicateMerge.in(0));
        this.AdjudicateMerge.out(0).to(this.MergeOrUpdate.in(0));
        this.MergeOrUpdate.out(0).to(this.CallMerge.in(0));
        this.MergeOrUpdate.out(1).to(this.UpsertCentral.in(0));
        this.ActionUpdateStatusGarbage.out(0).to(this.LoopGarbage.in(0));
        this.ActionRestartBase.out(0).to(this.BuildRestartClearCompletedFlags.in(0));
        this.BuildRestartClearCompletedFlags.out(0).to(this.UpsertCentral.in(0));
        this.LoopGarbage.out(1).to(this.LoopGarbage.in(0));
        this.LoopGarbage.out(1).to(this.BuildStatusGarbage.in(0));
        this.BuildStatusGarbage.out(0).to(this.UpsertCentral.in(0));
        this.SelectBaseValues.out(0).to(this.BaseDocProducedAnAnswer.in(0));
        this.LoopBaseDoc.out(1).to(this.CallBasedocex01.in(0));
        this.BaseDocProducedAnAnswer.out(0).to(this.BuildBaseDocUpsert.in(0));
        this.BaseDocProducedAnAnswer.out(1).to(this.RecordBaseDocFailure.in(0));
        this.UpsertCentralBaseDoc.out(0).to(this.LoopBaseDoc.in(0));
        this.RecordBaseDocFailure.out(0).to(this.LoopBaseDoc.in(0));
        this.LoadCompanyResolverGen.out(0).to(this.RestoreRouterPayload.in(0));
        this.RestoreRouterPayload.out(0).to(this.RouteMode.in(0));
        this.ActionSourceFeedback.out(0).to(this.RegistryReqFeedback.in(0));
        this.RegistryReqFeedback.out(0).to(this.GetRegistryFeedback.in(0));
        this.GetRegistryFeedback.out(0).to(this.TagRulesReqFeedback.in(0));
        this.TagRulesReqFeedback.out(0).to(this.LinesReqFeedback.in(0));
        this.LinesReqFeedback.out(0).to(this.GetLinesFeedback.in(0));
        this.GetLinesFeedback.out(0).to(this.BuildFeedbackOps.in(0));
        this.BuildFeedbackOps.out(0).to(this.LoopFeedback.in(0));
        this.LoopFeedback.out(1).to(this.RouteFeedbackOp.in(0));
        this.LoopFeedback.out(1).to(this.LoopFeedback.in(0));
        this.RouteFeedbackOp.out(0).to(this.MoveToFeedbackFolder.in(0));
        this.RouteFeedbackOp.out(1).to(this.ApplyFeedbackLabel.in(0));
        this.RouteFeedbackOp.out(2).to(this.BuildSourceFeedback.in(0));
        this.MoveToFeedbackFolder.out(0).to(this.BuildSourceFeedback.in(0));
        this.ApplyFeedbackLabel.out(0).to(this.BuildSourceFeedback.in(0));
        this.BuildSourceFeedback.out(0).to(this.UpsertCentral.in(0));
    }
}
