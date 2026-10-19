import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Incoming Documents v2
// Nodes   : 53  |  Connections: 52
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// IfNotLocked                        if
// JoinLocked                         code
// CheckLocked                        executeWorkflow
// RunById                            noOp
// WhenExecutedByAnotherWorkflow      executeWorkflowTrigger
// IfAction                           if
// ExecuteAction                      noOp
// IfGroupAction                      if
// IfDry                              if
// DrySkipPark                        noOp
// ReadActionCaps                     postgres                   [onError→regular] [creds] [alwaysOutput] [executeOnce]
// GroupByAction                      code
// Switch_                            switch
// StopAndError1                      stopAndError
// IfNotSameActionTwice               if
// Webhook                            webhook                    [creds]
// CodeInJavascript                   code
// MapIdMatchLineData                 code
// MapId                              set
// EnrichDoubleLines                  postgres                   [creds] [alwaysOutput] [executeOnce]
// GetActionHistory                   postgres                   [creds] [alwaysOutput] [executeOnce]
// AttachActionHistory                code
// CallIndoxV2Decide                  executeWorkflow
// JoinCompanyId1                     code
// Start                              noOp
// LoopKeeper                         noOp
// PriorityTableError                 stopAndError
// ActionFilter                       filter
// TakingAction                       noOp
// RespondToWebhook                   respondToWebhook
// ExecutionData1                     executionData
// ExecutionData4                     executionData
// LockMapClear                       redis                      [creds]
// PostActionRouterGroup              httpRequest                [onError→regular] [creds]
// CollapseAllLines                   code
// PostActionRouterAllLines           httpRequest                [onError→regular] [creds]
// ExecutionDataSubworkflow           executionData
// GetLineReq                         code
// CallIndoxApiGetLine                executeWorkflow
// GetLineMatch                       code
// DupGuardDoubleAction               code
// LoopOverItems                      splitInBatches
// CallIndoxApiGetLine1               executeWorkflow
// NextPageReq                        code
// PageRows                           code
// PageCursor                         code
// WhenClickingExecuteWorkflow        manualTrigger
// ExecutionDataManual                executionData
// EditFields                         set
// SpawnNextPageSelf                  executeWorkflow            [onError→regular]
// Main2kBatch                        splitInBatches
// DoubleBlockedPark                  code
// RaiseDoubleBlocked                 code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenExecutedByAnotherWorkflow
//    → ExecutionDataSubworkflow
//    → CodeInJavascript
//      → Switch_
//        → RunById
//          → MapId
//            → GetLineReq
//              → CallIndoxApiGetLine
//                → GetLineMatch
//                  → MapIdMatchLineData
//                    → Start
//                      → ReadActionCaps
//                      → Main2kBatch
//                        → RaiseDoubleBlocked
//                       .out(1) → LoopKeeper
//                          → Main2kBatch (↩ loop)
//                       .out(1) → EnrichDoubleLines
//                          → GetActionHistory
//                            → AttachActionHistory
//                              → CallIndoxV2Decide
//                                → DupGuardDoubleAction
//                                  → IfNotSameActionTwice
//                                    → IfAction
//                                      → ActionFilter
//                                        → IfDry
//                                          → DrySkipPark
//                                         .out(1) → TakingAction
//                                            → JoinLocked
//                                              → IfNotLocked
//                                                → ExecuteAction
//                                                  → IfGroupAction
//                                                    → GroupByAction
//                                                      → LoopOverItems
//                                                       .out(1) → PostActionRouterGroup
//                                                          → LoopOverItems (↩ loop)
//                                                   .out(1) → CollapseAllLines
//                                                      → PostActionRouterAllLines
//                                                  → ExecutionData1
//                                            → CheckLocked
//                                   .out(1) → DoubleBlockedPark
//       .out(1) → Start (↩ loop)
//       .out(2) → NextPageReq
//          → CallIndoxApiGetLine1
//            → PageRows
//              → Start (↩ loop)
//            → PageCursor
//              → SpawnNextPageSelf
//       .out(3) → StopAndError1
// Webhook
//    → CodeInJavascript (↩ loop)
//    → ExecutionData4
//    → RespondToWebhook
// WhenClickingExecuteWorkflow
//    → ExecutionDataManual
//    → EditFields
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"If NOT LOCKED":{"main":[[{"node":"Execute Action","type":"main","index":0}],[]]},"Join LOCKED":{"main":[[{"node":"If NOT LOCKED","type":"main","index":0}]]},"Run By ID":{"main":[[{"node":"MAP ID","type":"main","index":0}]]},"When Executed by Another Workflow":{"main":[[{"node":"Execution Data SubWorkflow","type":"main","index":0},{"node":"Code in JavaScript","type":"main","index":0}]]},"If ACTION":{"main":[[{"node":"If Dry?","type":"main","index":0}],[]]},"Execute Action":{"main":[[{"node":"Group By ACTION","type":"main","index":0},{"node":"Execution Data1","type":"main","index":0}]]},"If Dry?":{"main":[[{"node":"Dry Skip (park)","type":"main","index":0}],[{"node":"Taking Action","type":"main","index":0}]]},"Dry Skip (park)":{"main":[[]]},"Group By ACTION":{"main":[[{"node":"Loop Over Items","type":"main","index":0}]]},"Switch":{"main":[[{"node":"Run By ID","type":"main","index":0}],[{"node":"Start","type":"main","index":0}],[{"node":"Stop and Error1","type":"main","index":0}]]},"IF NOT SAME ACTION TWICE":{"main":[[{"node":"If ACTION","type":"main","index":0}],[{"node":"Double Blocked (park)","type":"main","index":0}]]},"Webhook":{"main":[[{"node":"Code in JavaScript","type":"main","index":0},{"node":"Execution Data4","type":"main","index":0},{"node":"Respond to Webhook","type":"main","index":0}]]},"Code in JavaScript":{"main":[[{"node":"Switch","type":"main","index":0}]]},"Map ID Match Line Data":{"main":[[{"node":"Start","type":"main","index":0}]]},"MAP ID":{"main":[[{"node":"Get Line Req","type":"main","index":0}]]},"Enrich Double Lines":{"main":[[{"node":"Get Action History","type":"main","index":0}]]},"Start":{"main":[[{"node":"Read Action Caps","type":"main","index":0},{"node":"Main 2k batch","type":"main","index":0}]]},"Loop keeper":{"main":[[]]},"Taking Action":{"main":[[{"node":"Join LOCKED","type":"main","index":0},{"node":"Check LOCKED","type":"main","index":0}]]},"Call indox-v2 Decide":{"main":[[{"node":"Dup Guard: Double Action","type":"main","index":0}]]},"Execution Data SubWorkflow":{"main":[[]]},"Get Line Req":{"main":[[{"node":"Call indox api (Get Line)","type":"main","index":0}]]},"Call indox api (Get Line)":{"main":[[{"node":"Get Line Match","type":"main","index":0}]]},"Get Line Match":{"main":[[{"node":"Map ID Match Line Data","type":"main","index":0}]]},"Dup Guard: Double Action":{"main":[[{"node":"IF NOT SAME ACTION TWICE","type":"main","index":0}]]},"Loop Over Items":{"main":[[],[{"node":"POST Action Router (group)","type":"main","index":0},{"node":"Loop Over Items","type":"main","index":0}]]},"POST Action Router (group)":{"main":[[]]},"Main 2k batch":{"main":[[{"node":"Raise Double Blocked","type":"main","index":0}],[{"node":"Loop keeper","type":"main","index":0},{"node":"Enrich Double Lines","type":"main","index":0},{"node":"Main 2k batch","type":"main","index":0}]]},"Double Blocked (park)":{"main":[[]]},"Raise Double Blocked":{"main":[[]]},"Get Action History":{"main":[[{"node":"Attach Action History","type":"main","index":0}]]},"Attach Action History":{"main":[[{"node":"Call indox-v2 Decide","type":"main","index":0}]]},"Read Action Caps":{"main":[[]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"1a1f9021-970c-46eb-8cef-4746d2dca0d0","name":"indox-state-machine-v2"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"22f1e71e-91bf-48db-811f-8d3bc4e55a3e","name":"sm-refactor-v2.1"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"2b5cb873-dd65-44dd-bf27-a2c99d2b81a4","name":"state-machine-v2"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:41:29.646Z","createdAt":"2026-07-30T23:41:29.646Z","id":"9c337cfe-7feb-4f3d-ab26-3de6439357ce","name":"sm-refactore-v2.1"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {"templateCredsSetupCompleted":true},
    /*__n8n__*/ pinData: {"Webhook":[{"json":{"headers":{"accept":"application/json,text/html,application/xhtml+xml,application/xml,text/*;q=0.9, image/*;q=0.8, */*;q=0.7","content-type":"application/json","user-agent":"axios/1.13.5","content-length":"72284","accept-encoding":"gzip, compress, deflate, br","host":"n8n:5678","authorization":{"__redacted":true,"reason":"node_defined_field","canReveal":false},"connection":"close"},"params":{},"query":{},"body":{"IDS":"[\"test01\"]","TRIGGER_TYPE":"drain_lane6_g1","DRAINER_TYPE":"drainer_lane6","DRAINER_ID":"lane6:3403183","DRAINER_CHAIN":"lane6:3403183","ORIGIN_EXECUTION":"3403183","PARENT_EXECUTION":"3403183"},"webhookUrl":"http://n8n.localhost/webhook/incoming-documents-017","executionMode":"production"}}],"When Executed by Another Workflow":[{"json":{"run_page":true,"after":"1780503618785ctd84b"}}]},
    /*__n8n__*/ staticData: {},
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"indoxV2Driver01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2Driver01',
    name: 'Incoming Documents v2',
    active: true,
    isArchived: false,
    tags: [
        'indox-state-machine-v2',
        'sm-refactor-v2.1',
        'state-machine-v2',
        'app:indox',
        'sm-refactore-v2.1',
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
export class IncomingDocumentsV2Workflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: '8af1a43b-96b9-473a-a3a2-070e911bd768',
        name: 'If NOT LOCKED',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [-688, 2864],
    })
    IfNotLocked = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: '382b40ae-7471-45e2-8960-af7c47362961',
                    leftValue: '={{ $json.LOCKED  }}',
                    rightValue: '',
                    operator: {
                        type: 'boolean',
                        operation: 'false',
                        singleValue: true,
                    },
                },
                {
                    id: '227a6000-2c29-40a7-8a75-c8c895d06586',
                    leftValue: '={{ $execution.mode }}',
                    rightValue: 'test',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
            ],
            combinator: 'or',
        },
        options: {},
    };

    @node({
        id: 'b18a3380-57c6-4cff-83a1-54c6fa9d8b54',
        name: 'Join LOCKED',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-912, 2864],
    })
    JoinLocked = {
        jsCode: `// Matched on the composite <ID>::<ACTION>, because that is now the lock KEY. Matching on ID
// alone would mark every line of a document locked as soon as any one of its actions was held.
// Fail-open is inherited and deliberate: fail-closed would starve a line for the whole TTL
// whenever a mutex reply came back incomplete.
//
// ABSENT REPLY IS A DIFFERENT CASE FROM AN INCOMPLETE ONE, and it must fail CLOSED.
// 'Check LOCKED' calls processLock01 with ACTION=check_and_lock -- it ACQUIRES the lock, it does
// not merely report it. Under executionOrder v1 this node and 'Check LOCKED' are both children of
// 'Taking Action' output 0; when this one is reached first, $('Check LOCKED') has no run data and
// n8n throws "Node 'Check LOCKED' hasn't been executed" (measured: a burst of 709 failures, 27%
// of driver executions, ending 14:54Z 2026-08-11).
// If the reply is missing entirely then NO lock was acquired for ANY item, so treating them as
// unlocked would process them with no mutex held -- precisely what the lock exists to prevent.
// Skipping costs one sweep of latency: every driver pass re-checks, so no work is lost.
let locked = null;
try {
  locked = $('Check LOCKED').all().map( x => x.json.was_locked ? x.json.KEY : null)
} catch (e) {
  locked = null;
}
for (const item of $input.all()) {
  item.json.LOCKED = (locked === null)
    ? true
    : locked.includes(String(item.json.ID) + "::" + String(item.json.ACTION))
}
return $input.all();`,
    };

    @node({
        id: 'f37ca374-4434-4084-8346-65eef3cfc439',
        name: 'Check LOCKED',
        /*__n8n__*/ notes: "PROCESS=doc_action, KEY=<ID>::<ACTION>. Was doc_step/<ID>, a per-document mutex that blocks a document's NEXT action for the full 600s TTL because nothing on this path releases it.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [-912, 2672],
        executeOnce: false,
    })
    CheckLocked = {
        workflowId: {
            __rl: true,
            value: 'processLock01',
            mode: 'list',
            cachedResultUrl: '/workflow/processLock01',
            cachedResultName: 'process_lock',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                PROCESS: 'doc_action',
                ACTION: 'check_and_lock',
                KEY: '={{ $json.ID && $json.ACTION ? String($json.ID) + "::" + String($json.ACTION) : null }}',
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'PROCESS',
                    displayName: 'PROCESS',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                },
                {
                    id: 'KEY',
                    displayName: 'KEY',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                    removed: false,
                },
                {
                    id: 'ACTION',
                    displayName: 'ACTION',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                },
                {
                    id: 'EXECUTION',
                    displayName: 'EXECUTION',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                    removed: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        options: {},
    };

    @node({
        id: 'c3d64dd3-8c48-4d79-9827-765834fe09b2',
        name: 'Run By ID',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-4496, 2848],
    })
    RunById = {};

    @node({
        id: '03ac8ec2-2b5a-4561-acdb-1b249c7538c5',
        name: 'When Executed by Another Workflow',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [-5184, 3152],
    })
    WhenExecutedByAnotherWorkflow = {
        workflowInputs: {
            values: [
                {
                    name: 'ID',
                },
                {
                    name: 'body',
                    type: 'any',
                },
                {
                    name: 'ACTION_LINE',
                    type: 'object',
                },
                {
                    name: 'ACTION_LINES',
                    type: 'array',
                },
                {
                    name: 'DRAINER_TYPE',
                },
                {
                    name: 'DRAINER_ID',
                },
                {
                    name: 'DRAINER_CHAIN',
                },
                {
                    name: 'run_page',
                    type: 'boolean',
                },
                {
                    name: 'after',
                },
                {
                    name: '__instance',
                },
            ],
        },
    };

    @node({
        id: 'f8fc4500-52b5-40e6-bd47-86f8106e6bcc',
        name: 'If ACTION',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [-1584, 2768],
    })
    IfAction = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: '87d03b0f-3296-4dff-afc4-89448dc75356',
                    leftValue: '={{ $json.ACTION }}',
                    rightValue: 'no_action',
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
        id: '37100221-09c5-4b7d-a518-2794d4eabbf8',
        name: 'Execute Action',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-464, 2864],
    })
    ExecuteAction = {};


    @node({
        id: 'drv-if-dry',
        name: 'If Dry?',
        /*__n8n__*/ notes: "DRY RUN GATE. Sits between 'Action Filter' and 'Taking Action' -- i.e. BEFORE the redis doc_action lock, not after it. It was first placed after 'Execute Action', which still covered both dispatch paths but let dry runs ACQUIRE LOCKS: a lock is a side effect, and a 10-minute TTL on every document a dry run touched silently lock-skipped the next real run (measured 2026-08-21 -- a wet proof run decided update_status_missing_company for all 5 documents, then 'If NOT LOCKED' routed 0 of 5 to 'Execute Action' because the preceding dry run still held them). From here a dry run does decide, the dup guard and the action filter, then parks: no lock, no dispatch, nothing to clean up. It still covers BOTH dispatch paths -- the grouped lane ('Group By ACTION' -> 'POST Action Router (group)') and the all-lines lane ('Collapse All Lines' -> 'POST Action Router (all lines)'). Everything upstream still runs for real: decide, the double-action guard, and 'Log Action Start'. Only the router POST is skipped, so a dry run exercises selection, batching, locking and decide while writing no actions. Reads DRY from whichever ENTRY ran, not from $json, because the row payload is replaced downstream by 'Call indox api (Get Line)' and the flag would not survive.",
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [-1140, 2768],
    })
    IfDry = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'drv-cond-dry',
                    leftValue:
                        "={{ (function(){ try { var w = $('Webhook').first().json.body; if (w && (w.DRY === true || String(w.DRY).toLowerCase() === 'true')) return 'dry'; } catch(e){} try { var t = $('When Executed by Another Workflow').first().json.body; if (t && (t.DRY === true || String(t.DRY).toLowerCase() === 'true')) return 'dry'; } catch(e){} return 'wet'; })() }}",
                    rightValue: 'dry',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
            ],
            combinator: 'and',
        },
        looseTypeValidation: true,
        options: {},
    };

    @node({
        id: 'drv-dry-park',
        name: 'Dry Skip (park)',
        /*__n8n__*/ notes: "Terminal for dry runs. Deliberately a NoOp and NOT wired onward: the grouped-dispatch loop must not turn over in dry mode, or 'Log Action End' would stamp dispatches that never happened.",
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-920, 2628],
    })
    DrySkipPark = {};

    @node({
        id: 'drv-read-action-caps',
        name: 'Read Action Caps',
        /*__n8n__*/ notes: "Per-action router batch caps, read once per driver run. Hangs off 'Start' and its y is ABOVE 'Main 2k batch' on purpose: executionOrder v1 runs sibling branches topmost-first, so this resolves before anything reaches 'Group By ACTION', which reads it by name. Keys are indox.statemachine.action_router.max (default) and indox.statemachine.action_router.<action>.max (override). alwaysOutputData plus a COALESCE means a missing settings row falls back to the built-in default rather than dark-stopping the lane.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-2932, 2700],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
        executeOnce: true,
    })
    ReadActionCaps = {
        operation: 'executeQuery',
        query: `=SELECT COALESCE(jsonb_object_agg(key, value), '{}'::jsonb)::text AS caps
FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2Driver01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.settings
WHERE key LIKE 'indox.statemachine.action_router.%'`,
        options: {},
    };

    @node({
        id: '957ad843-b0aa-49bc-803e-1268825c2b39',
        name: 'Group By ACTION',
        /*__n8n__*/ notes: "[predictable scaling 2026-08-16, owner order] ONE GROUP PER ACTION — no 25-item chunking, no batch fan-out. The driver never splits: a run's parallelism is exactly its distinct-action count (typically 2-3 lanes), each lane = one blocking router call carrying ALL of that action's lines. The ACTION WORKFLOWS own their internal batching (their loops decide 25-per-search, 5k-per-join-upsert, etc.). SCALE-UP IS PRE-DRIVER, NEVER IN-DRIVER: split the id list and run N drivers in parallel (N=1 baseline, then N=4) — total parallelism is always N x action-lanes, fully predictable. The drainer is the only component that fans out.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-16, 2768],
    })
    GroupByAction = {
        jsCode: `// Split each ACTION into router-sized groups, then INTERLEAVE them.
//
// WHY SPLIT AT ALL (owner design 2026-08-21). The router sends ONE blocking POST per group and
// 'Log Action End' only runs if that call returns, so a group wider than the router's 3600 s
// executionTimeout is killed and closes ZERO dispatches -- measured: 142 extract_base_doc
// dispatched, 51 documents extracted, 0 rows closed, all 142 left IN_PROGRESS. Fitted against
// width, extract_base_doc costs 149s + 42.455s/line, i.e. 23.6 HOURS at 2,000 lines. It is the
// only genuinely per-document action; every update_status_* collapses to one batched upsert and
// is flat in width (raw evidence: update_status_garbage ran width 23 in 2 s while width 12 ranged
// 2 s to 1580 s -- that variance is queue contention, not marginal cost).
//
// This does NOT change the driver:router fan-out ratio. 'Loop Over Items' still walks the groups
// two at a time; there are simply more, smaller groups.
//
// WHY INTERLEAVE. With groups emitted action-by-action, a pair taken by the loop would usually be
// two chunks of the SAME action, so both concurrent router calls would land on the same Actions
// sub-workflow and contend. Round-robin across actions makes each pair naturally different --
// (a1, a2, a3, a1, a2, a3) rather than (a1, a1, a2, a2) -- so the two lanes spread across
// different Actions workflows.
let caps = {};
try { caps = JSON.parse(($('Read Action Caps').first().json || {}).caps || '{}'); } catch (e) {}
const PFX = 'indox.statemachine.action_router.';
const DEFAULT_CAP = Number(caps[PFX + 'max']) > 0 ? Number(caps[PFX + 'max']) : 2000;
function capFor(action) {
  const v = Number(caps[PFX + action + '.max']);
  return v > 0 ? v : DEFAULT_CAP;
}

const byAction = new Map();
for (const { json } of $input.all()) {
  const a = json.ACTION;
  if (!byAction.has(a)) byAction.set(a, []);
  byAction.get(a).push(json);
}

// Preserve the existing update_status-first bias as the round-robin order.
// [selection 2026-08-25] select_* joins that first group. The bias exists to let the CHEAP,
// flat-cost actions through ahead of the ones that download and OCR a file, and a selection is the
// cheapest action in the machine -- it reads columns already on the row and calls nothing. Leaving
// it in the default group would queue a millisecond of arithmetic behind a 40-second extraction.
const cheapFirst = (n) => (n.startsWith('update_status') || n.startsWith('select_')) ? 1 : 0;
const order = [...byAction.keys()].sort(function (a, b) {
  return cheapFirst(b) - cheapFirst(a);
});

const chunks = new Map();
for (const a of order) {
  const items = byAction.get(a);
  const cap = capFor(a);
  const list = [];
  for (let i = 0; i < items.length; i += cap) list.push(items.slice(i, i + cap));
  chunks.set(a, list);
}

const out = [];
let requestId = 1;
for (let round = 0, more = true; more; round++) {
  more = false;
  for (const a of order) {
    const list = chunks.get(a);
    if (round < list.length) {
      out.push({ json: { requestId: requestId++, action: a, items: list[round], chunk: round + 1, chunks: list.length, cap: capFor(a) } });
      more = true;
    }
  }
}
return out;`,
    };

    @node({
        id: 'c53548f4-3bd5-405c-9d75-b75a238b1117',
        name: 'Switch',
        type: 'n8n-nodes-base.switch',
        version: 3.3,
        position: [-4704, 2944],
    })
    Switch_ = {
        rules: {
            values: [
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.ID }}',
                                rightValue: '',
                                operator: {
                                    type: 'string',
                                    operation: 'exists',
                                    singleValue: true,
                                },
                                id: 'da75dca9-3a66-440a-95bc-51c8e4d133a7',
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'run_by_id',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'fc111a81-3ff8-4794-8099-88ea7a60b25e',
                                leftValue: '={{ $json.LINES }}',
                                rightValue: '',
                                operator: {
                                    type: 'array',
                                    operation: 'exists',
                                    singleValue: true,
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'run_lines',
                },
            ],
        },
        options: {
            fallbackOutput: 'extra',
        },
    };

    @node({
        id: '0b3b9d64-b9d4-4326-a4a2-da21f459dfad',
        name: 'Stop and Error1',
        type: 'n8n-nodes-base.stopAndError',
        version: 1,
        position: [-4496, 3136],
    })
    StopAndError1 = {
        errorMessage: 'Invalid execution input ',
    };

    @node({
        id: 'c058cfc7-153a-4bb9-b078-6b7b1ca99b9e',
        name: 'IF NOT SAME ACTION TWICE',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [-1808, 2816],
    })
    IfNotSameActionTwice = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: 'd20-dup-in-log-0001',
                    leftValue: '={{ $json.__dup_in_log === true }}',
                    rightValue: '',
                    operator: {
                        type: 'boolean',
                        operation: 'false',
                        singleValue: true,
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: '30b902b1-99ce-41c2-b5fe-28972b45ee52',
        webhookId: '0dcc82ae-53ff-477d-89ec-b9d29841cc57',
        name: 'Webhook',
        type: 'n8n-nodes-base.webhook',
        version: 2.1,
        position: [-5184, 2960],
        credentials: { httpBasicAuth: { id: 'azPhHBvOWaf9IsEA', name: 'Incoming Documents [env-managed]' } },
    })
    Webhook = {
        httpMethod: 'POST',
        path: 'incoming-documents-017',
        authentication: 'basicAuth',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: '384383f2-9a1b-4a3f-a8c3-262a4bfdeac0',
        name: 'Code in JavaScript',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-4960, 2960],
    })
    CodeInJavascript = {
        jsCode: `// Fan a chunked check-next POST back out into one item per document.
// The run_by_id path downstream is already multi-item safe (the 5-minute sweep drives it
// with ~80 items per run), so expanding here restores batching with no topology change.
// Falls back to the original single-ID shape when IDS is absent or unparseable; anything
// dropped that way is re-picked by the 5-minute change sweep.
const out = [];
for (const item of $input.all()) {
  const b = (item.json && item.json.body) || {};
  let ids = null;
  if (b.IDS) {
    try {
      const parsed = typeof b.IDS === 'string' ? JSON.parse(b.IDS) : b.IDS;
      if (Array.isArray(parsed) && parsed.length) ids = parsed.map(String).filter(Boolean);
    } catch (e) { ids = null; }
  }
  const dry = (b.DRY === true || String(b.DRY).toLowerCase() === 'true');
  // [multi-instance 2026-08-28] THIS NODE IS WHERE THE INSTANCE WAS LOST, and it is worth being
  // precise about why, because everything upstream and downstream was already correct.
  // The drain sends __instance on the body (indoxV2BaseDrain01 :: 'Fire Lanes'), and every SQL
  // node downstream resolves its schema from $json.__instance. But this node does not forward the
  // body — it CONSTRUCTS a new item from four named fields, so any field not named here simply
  // ceases to exist from this point on. Traced 2026-08-28: 'When Called' and 'Normalize Request'
  // in the drain both carried 'hacohen'/'levi' correctly, and 'Enrich Double Lines' one hop later
  // saw nothing. A rebuild like this is a silent field filter.
  const inst = String(b.__instance || '');
  if (ids && ids.length) {
    for (const id of ids) {
      out.push({ json: { ACTION_LINE: b.ACTION_LINE, ACTION_LINES: b.ACTION_LINES, ID: id, DRY: dry, __instance: inst } });
    }
  } else {
    out.push({ json: { ACTION_LINE: b.ACTION_LINE, ACTION_LINES: b.ACTION_LINES, ID: b.ID, DRY: dry, __instance: inst } });
  }
}
// CIRCUIT-BREAKER, not flow control -- it must never fire in normal operation, because the
// drainer already bounds every lane to indox.statemachine.driver.batch. MAX arrives in the
// body from indox.statemachine.driver.max; a direct caller falls back to the same default.
//
// Why a cap exists at all: n8n retains EVERY node's output for the whole execution, so heap
// grows with lane WIDTH and is released only when the lane ends. Measured 2026-08-21 -- two
// 9,790-doc lanes resident on one worker peaked at 2,316 MB and tripped V8's ceiling
// (NODE_OPTIONS=--max-old-space-size=2600), which aborts the process instantly: no error
// handler, no partial result, and it killed every OTHER execution on that worker as well
// (concurrency 20). Throwing turns a fleet-wide abort into one caller-visible error.
// Truncating instead would silently drop documents, which is worse.
const firstBody = ($input.first() && $input.first().json && $input.first().json.body) || {};
const LANE_MAX = Number(firstBody.MAX) > 0 ? Number(firstBody.MAX) : 2000;
if (out.length > LANE_MAX) {
  throw new Error('Driver lane too wide: ' + out.length + ' documents in one call, max is ' +
    LANE_MAX + '. Chunk the caller. See apps/indox/issues/drain-pool-consolidation-plan.md');
}
// [2026-08-21] THIS FALLBACK WAS DEAD, and it is the whole reason a direct caller could not
// reach the driver. The guard used to be
//     Object.values(out?.[0]?.json || {}).some(v => v !== undefined) ? out : $input.all()
// meaning "if the body produced nothing, keep the caller's own items". But every row built
// above carries DRY, and DRY is computed as a BOOLEAN - false, never undefined - so .some()
// was always true and the fallback never once fired.
//
// The cost: this workflow's trigger DECLARES ID as an input, so an executeWorkflow caller
// passing {ID} at the top level is using the documented contract. With no body present the
// loop above built {ACTION_LINE: undefined, ACTION_LINES: undefined, ID: undefined, DRY: false},
// the dead guard returned it as-is, and the Switch below - which routes on $json.ID existing -
// dropped it to the fallback output and into 'Stop and Error1'. The caller saw only
// "Invalid execution input", a message that names neither the field nor this node.
// Measured: indoxV2PipelineTest01 passed {ID:'plc_missing_company'}, the trigger received it
// intact, and the Switch's run_by_id output was empty.
//
// Decide on the fields the body was supposed to supply, and leave DRY out of it: DRY is
// DERIVED, so it can never be evidence about what arrived.
const fromBody = out.some(o => o.json.ID !== undefined ||
                              o.json.ACTION_LINE !== undefined ||
                              o.json.ACTION_LINES !== undefined);
return fromBody ? out : $input.all();`,
    };

    @node({
        id: '6faa0f06-08ca-43ea-bc61-5b3d60012ab0',
        name: 'Map ID Match Line Data',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-3376, 2848],
    })
    MapIdMatchLineData = {
        jsCode: `// Unresolvable ids are SKIPPED, never thrown.
//
// This node used to throw Error('No matches found for the given lineId') on the FIRST item whose
// line lookup came back empty, which turns one stale id into the loss of a whole driver lane.
// Measured 2026-08-18 on the scale-4 cycle: ALL FOUR drivers died within 91s, every one on this
// node. Its input held 1,261 of 6,262 ids (20.1%) shaped {filter, matches: [], matchCount: 0}
// instead of a line -- rows the pipeline had already moved to OLD, whose line is gone, and which a
// status-flip drain legitimately re-offers. 6,262 rows of work were discarded per lane over that.
//
// A row whose line cannot be found is not an error condition for the other 5,001 rows in the lane.
// It is skipped and left in whatever status it already had -- nothing is mutated here.
// FOLLOW-UP (owner call, deliberately NOT taken here): an id that can never resolve will be
// re-offered by every future drain forever. Marking it terminal is a state-machine decision.
// The instance this driver run is acting for. Read from the entry normalizer, which carries it for
// both the webhook and the sub-workflow paths; the item arriving here has been through the api call
// and no longer has it.
let drvInstance = '';
// BOTH entry paths -- see 'Get Line Req'. 'Code in JavaScript' only exists on the WEBHOOK path;
// sub-workflow calls arrive through 'When Executed by Another Workflow' and would silently
// resolve to public.
try { drvInstance = String(($('When Executed by Another Workflow').first().json || {}).__instance || ''); } catch (e) { drvInstance = ''; }
if (!drvInstance) { try { drvInstance = String(($('Code in JavaScript').first().json || {}).__instance || ''); } catch (e) { drvInstance = ''; } }
const all = $input.all();
const out = [];
let skipped = 0;
for (const item of all) {
  const m = item.json && item.json.matches;
  if (!m || m.length === 0) { skipped++; continue; }
  // [multi-instance 2026-08-28] Replacing item.json with the API row drops every request-side
  // field, __instance included, and every SQL node downstream resolves its schema from it.
  m[0].__instance = drvInstance;
  item.json = m[0];
  out.push(item);
}
if (skipped) console.log('Map ID Match Line Data: skipped ' + skipped + ' of ' + all.length + ' unresolvable id(s)');
return out;`,
    };

    @node({
        id: '53f9ac03-a993-4bae-9bf4-320f393cb183',
        name: 'MAP ID',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [-4272, 2848],
    })
    MapId = {
        assignments: {
            assignments: [
                {
                    id: '12450d6c-7d20-472e-83d6-8f54ed4a940d',
                    name: '=ID',
                    value: '={{ $json.ID }}',
                    type: 'string',
                },
                {
                    id: 'unlock-0000-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-0078-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-tc-drv-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'drv-enrich-doubles',
        name: 'Enrich Double Lines',
        /*__n8n__*/ notes: "[renamed 2026-08-20, owner order] Was 'Enrich Doubles'. A DOUBLE LINE is a data-quality fact about the table -- two rows are the same document -- and the answer is a MERGE. That is this node. It is NOT a DOUBLE ACTION EXECUTION (the same action dispatched twice with no ACTION_RESTART between), which is a state-machine health fault owned by 'Dup Guard: Double Action' and must error loudly. Both used to be called 'doubles'. --- [SQL doubles 2026-08-18, owner design] ONE pass over the whole set this driver is holding, BEFORE decide sees anything. Adds IS_DOUBLE / IS_MAIN_DOUBLE / LINES_TO_MERGE, so decide keeps its one-shot view of duplicates while being fed in 3k slices. Survivor = LAST created (created_at DESC, ID DESC); MERGED rows are excluded, which is what makes a merged loser disappear from the next sweep. Also carries __merge_enabled (settings key indoxDoubleMergeOn) so the merge itself stays blocked until it is trusted. IDs are pipe-joined because n8n splits the Query Parameters field on commas. executeOnce: the node must run ONCE for the batch, not once per row.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-2480, 2816],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
        executeOnce: true,
    })
    EnrichDoubleLines = {
        operation: 'executeQuery',
        query: `=WITH input AS (SELECT unnest(string_to_array($1, '|')) AS "ID"
), toggle AS (
  -- [instance is RECEIVED, not chosen — 2026-08-28] This driver is webhook-triggered by the drain,
  -- so it is a RECEIVER. It was briefly made to read the instance registry itself and pick the
  -- enabled instance; that turned a receiver into a chooser, which is precisely the layering the
  -- entry-point census exists to prevent. Enumeration belongs to the four SCHEDULED entry points
  -- (BaseDrain Tick, syncV3Main Schedule, syncLedgerApi Reaper, indoxHealth) — they fan out one
  -- item per enabled instance, and everything downstream is told which one it is acting for.
  --
  -- So the instance arrives on the request and is passed straight through as "__instance". It is
  -- the instance IDENTITY ('hacohen'), never the storage location ('indox_hacohen'): indoxApi01 is
  -- the single place that maps identity to schema, so the indox_<id> convention lives in one file
  -- rather than in every producer.
  SELECT COALESCE((SELECT lower(value) = 'true' FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2Driver01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.settings
                   WHERE key = 'indoxDoubleMergeOn' LIMIT 1), false) AS merge_on,
  -- [source feedback 2026-08-21] Same shape and same reason as merge_on: the action moves a
  -- client's Drive files and tags their mail, so it stays blocked until it is trusted. A missing
  -- settings row COALESCEs to false, so the gate can never dark-start.
         COALESCE((SELECT lower(value) = 'true' FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2Driver01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.settings
                   WHERE key = 'indoxSourceFeedbackOn' LIMIT 1), false) AS feedback_on,
  -- [priority gate 2026-08-21] THE SETTING HAD NO WAY TO REACH THE GATE THAT READS IT.
  -- indoxV2ActionsGDoc01/Ship01 decide with:
  --     _priorityActive = __CFG().activePrioritySync === true
  -- but __CFG() reads $('Companies') or an injected _cfg, and NEITHER router has a Companies
  -- node and nothing injects _cfg -- so __CFG() is {} on the decide path and _priorityActive was
  -- ALWAYS false. Measured 2026-08-21: action_priority_sync has 0 dispatches all-time, and the
  -- 4,749 rows carrying PRIORITY_SYNC_COMPLETED were written by the v1 processors, not by this
  -- action. Flipping activePrioritySync would have sent the client nothing, silently.
  -- Carried on the row like __merge_enabled and __source_feedback_enabled, for the same reason.
         COALESCE((SELECT lower(value) = 'true' FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2Driver01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.settings
                   WHERE key = 'activePrioritySync' LIMIT 1), false) AS priority_on,
  -- [local priority endpoint 2026-08-22] Sends the payload to priorityLocalApi01 instead of the
  -- client's ERP, so action_priority_sync can be switched on and exercised against real documents
  -- with nothing reaching the client. Carried on the row for the same reason as the three above:
  -- the routers have no way to read settings on the decide path.
  -- NOTE THE INVERTED DEFAULT. The other gates COALESCE to false because false is their safe
  -- state. Here the safe state is TRUE -- a missing settings row must mean "keep it local", never
  -- "post to the client". Losing this row should cost a test run, not a duplicated ERP.
         COALESCE((SELECT lower(value) = 'true' FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2Driver01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.settings
                   WHERE key = 'indox.actions.priority_sync.local' LIMIT 1), true) AS priority_local,
  -- [row-carried settings 2026-08-31] The ageing window, same reason as every gate above: the
  -- decide path has no Companies node and no _cfg, so OldDocumentMonthsBack could never reach
  -- anyOldDate there and the fn's hardcoded 6 always won (the live row also says 6, so prod
  -- behaviour is byte-identical). NULL when the row is absent or non-numeric — decide then
  -- falls back exactly as before. What this changes in practice: the operator's number is
  -- finally honoured, and the clock-independent test tenant (240) stops ageing real demo files.
         (SELECT NULLIF(regexp_replace(value, '[^0-9]', '', 'g'), '')::int FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2Driver01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.settings
                   WHERE key = 'OldDocumentMonthsBack' LIMIT 1) AS old_months
), bad_docid AS (
  /* A DOC_ID USED BY THREE OR MORE COMPANIES IS NOT A DOCUMENT ID.
     [2026-08-23] This rule already existed -- in 'Adjudicate Merge', which skips any group whose
     doc-id is shared across 3+ companies rather than merge documents that only look alike. The
     DETECTOR did not know about it, and that asymmetry is a group with no terminal state: the
     driver raises it, the adjudicator refuses it, nothing is written, and it is raised again on
     the next sweep. Five mains reached 146 action_merge_doubles dispatches this way.
     Every one of the last 10 duplicate groups on the table was this and only this. The worst
     offender, DOC_ID 515561520, is a company registration number appearing under FIFTEEN
     companies across 68 rows; another, 02-6333155, is a phone number under 5. They are not
     duplicates -- they are different documents whose id was mis-extracted.
     Table-wide: 49 such doc-ids, 258 rows.
     Quarantining at the KEY, not after grouping, is what gives them a terminal state: they simply
     stop being duplicates. A row still gets its hash or comp key, so a genuine duplicate hiding
     behind a bad doc-id is still caught by the tiers below -- this narrows the biz tier only.
     Threshold and predicate are copied from the adjudicator so the two cannot disagree again. */
  SELECT btrim("DOC_ID") AS did
  FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2Driver01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.incoming_documents
  WHERE coalesce(btrim("DOC_ID"), '') <> ''
    AND length(regexp_replace(btrim("DOC_ID"), '[^a-zA-Z0-9]', '', 'g')) >= 3
  GROUP BY btrim("DOC_ID")
  HAVING count(DISTINCT btrim("COMPANY_ID")) >= 3
), live AS (
  SELECT d.* FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2Driver01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.incoming_documents d JOIN input i USING ("ID")
  WHERE d."STATUS" IS DISTINCT FROM 'MERGED'
), keyed AS (
  SELECT l.*, COALESCE(
    CASE WHEN l."COMPANY_ID" IS NOT NULL AND l."COMPANY_ID" <> '' AND lower(l."COMPANY_ID") <> 'unknown'
          AND l."DOC_ID" IS NOT NULL AND l."DOC_ID" <> ''
          AND lower(btrim(l."DOC_ID")) NOT IN ('unknown','action_required','null','none')
          AND length(regexp_replace(btrim(l."DOC_ID"),'[^a-zA-Z0-9]','','g')) >= 3
          AND regexp_replace(btrim(l."DOC_ID"),'[^a-zA-Z0-9]','','g') !~ '^0+$'
          AND btrim(l."COMPANY_ID") <> btrim(l."DOC_ID")
          AND btrim(l."DOC_ID") NOT IN (SELECT did FROM bad_docid)
         THEN 'biz' || chr(1) || btrim(l."COMPANY_ID") || chr(1) || btrim(l."DOC_ID") END,
    CASE WHEN l."HASH" IS NOT NULL AND l."HASH" <> '' AND lower(l."HASH") <> 'unknown'
          AND (l."LINKED_BS" IS NULL OR l."LINKED_BS" = '' OR lower(l."LINKED_BS") = 'unknown')
         THEN 'hash' || chr(1) || l."HASH" END,
    CASE WHEN l."COMPANY_ID" IS NOT NULL AND l."COMPANY_ID" <> ''
          AND l."SHORT_DOC_ID" IS NOT NULL AND l."SHORT_DOC_ID" <> ''
          AND btrim(l."SHORT_DOC_ID") !~ '^0+$'
         THEN 'comp' || chr(1) || l."COMPANY_ID" || chr(1) || l."SHORT_DOC_ID" END
  ) AS dup_key FROM live l
), keys AS (
  SELECT DISTINCT dup_key FROM keyed WHERE dup_key IS NOT NULL
), universe AS (
  /* DETECTION IS TABLE-WIDE, ACTION STAYS ON THE PIPED LINES [owner order 2026-08-19].
     Every CTE below used to derive from 'live', i.e. the driver's own id list, so a document
     could only be found double against another document IN THE SAME BATCH. 'universe' widens the
     comparison to every still-open row sharing one of the input's keys, so grp_n and rn are
     table-wide facts and "newest is main" holds globally. The final SELECT still JOINs 'input',
     so only the lines this driver piped in are returned and acted on. LINES_TO_MERGE may name
     rows outside the batch: that is information for the merge action, not a licence to touch
     them.

     [detector simplified 2026-08-23, owner order] Two changes, both about keeping this a pure
     DETECTOR. (1) dup_key was spelled out TWICE -- once in the SELECT, once in the WHERE -- so
     the same twenty-line COALESCE had to be edited in two places to stay correct. It is now
     computed once in a derived table and filtered by name. (2) The universe excludes MERGED, and
     ONLY MERGED. Terminal status is the stop condition -- self-enforcing, and it cannot go stale
     the way the merge_sig fingerprint it replaces did (that stamp broke the moment a member's
     HASH arrived after stamping, which is how 74 dispatches landed on one document).

     DOUBLE IS NOT EXCLUDED, AND MUST NOT BE. An earlier draft of this comment said it was, from
     the design where DOUBLE meant "reviewed, genuinely different, kept apart". The owner removed
     keep-apart on 2026-08-23: there is one outcome now, and a conflict is RECORDED in DUP_CAUSE
     and merged anyway. DOUBLE is therefore a transient marker on a non-main that is waiting for
     its main to merge it, not a resolution. Dropping it from the universe would take every
     non-main out of its own group, the main would see grp_n = 1, and NOTHING would ever merge.
     The code has always been right here; only this comment was wrong. */
  SELECT u.* FROM (
    SELECT d.*, COALESCE(
      CASE WHEN d."COMPANY_ID" IS NOT NULL AND d."COMPANY_ID" <> '' AND lower(d."COMPANY_ID") <> 'unknown'
            AND d."DOC_ID" IS NOT NULL AND d."DOC_ID" <> ''
            AND lower(btrim(d."DOC_ID")) NOT IN ('unknown','action_required','null','none')
            AND length(regexp_replace(btrim(d."DOC_ID"),'[^a-zA-Z0-9]','','g')) >= 3
            AND regexp_replace(btrim(d."DOC_ID"),'[^a-zA-Z0-9]','','g') !~ '^0+$'
            AND btrim(d."COMPANY_ID") <> btrim(d."DOC_ID")
            AND btrim(d."DOC_ID") NOT IN (SELECT did FROM bad_docid)
           THEN 'biz' || chr(1) || btrim(d."COMPANY_ID") || chr(1) || btrim(d."DOC_ID") END,
      CASE WHEN d."HASH" IS NOT NULL AND d."HASH" <> '' AND lower(d."HASH") <> 'unknown'
            AND (d."LINKED_BS" IS NULL OR d."LINKED_BS" = '' OR lower(d."LINKED_BS") = 'unknown')
           THEN 'hash' || chr(1) || d."HASH" END,
      CASE WHEN d."COMPANY_ID" IS NOT NULL AND d."COMPANY_ID" <> ''
            AND d."SHORT_DOC_ID" IS NOT NULL AND d."SHORT_DOC_ID" <> ''
            AND btrim(d."SHORT_DOC_ID") !~ '^0+$'
           THEN 'comp' || chr(1) || d."COMPANY_ID" || chr(1) || d."SHORT_DOC_ID" END
    ) AS dup_key
    FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2Driver01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.incoming_documents d
    WHERE d."STATUS" IS DISTINCT FROM 'MERGED'
  ) u
  WHERE u.dup_key IN (SELECT dup_key FROM keys)
), grp AS (
  SELECT *, count(*) OVER (PARTITION BY dup_key) AS grp_n,
            row_number() OVER (PARTITION BY dup_key ORDER BY created_at DESC, "ID" DESC) AS rn
  FROM universe WHERE dup_key IS NOT NULL
), dbl AS (
  -- PURE DETECTION. A group is live when more than one member is still unmerged.
  --
  -- There is no marker, no fingerprint and no settled-flag, because none is needed: the merge
  -- writes STATUS='MERGED' on the losers, MERGED is excluded from the universe above, so the
  -- next sweep sees grp_n = 1 and the main is simply not double any more. The stop condition IS
  -- the terminal status, and it cannot go stale.
  -- (Replaces DOUBLE_LINE_CONTEXT.merge_sig, which fingerprinted ID:HASH per member and broke
  -- the moment a HASH arrived after stamping -- 74 action_merge_doubles dispatches on one
  -- document, 2026-08-23 -- and the DUP_CAUSE gate that replaced it, which could not be
  -- satisfied for a group split across driver batches.)
  SELECT * FROM grp WHERE grp_n > 1
), losers AS (
  SELECT dup_key, jsonb_agg(to_jsonb(d) - 'dup_key' - 'grp_n' - 'rn' ORDER BY d."ID") AS lines
  FROM dbl d WHERE d.rn > 1 GROUP BY dup_key
)
, feed AS (
  -- [source feedback 2026-08-21] THE LOWEST-INDEX SOURCE THAT STILL OWES FEEDBACK, per document.
  --
  -- Computed HERE, in the one SQL pass that already runs per batch, and never in decide. Two
  -- reasons, both measured: SOURCE_LIST is now the FATTEST COLUMN ON THE TABLE (26 MB total,
  -- avg 692 B, 1.37 MB per 2,000-row decide slice), and the last time a fat column was parsed
  -- per row in the decide path it was ACTION_LOG, which is exactly what the 2026-08-17 slimming
  -- removed. Decide gets two scalars instead: an index and an identity.
  --
  -- ONE PER DOCUMENT PER PASS, not all of them. Feedback action names are per-source
  -- (source_feedback_0, _1, ...) so the double-action guard can tell them apart, which means
  -- they take DIFFERENT doc_action locks — n8n.process_lock.doc_action.<ID>::<ACTION>. Emitting
  -- two at once would let two executions upsert the same row concurrently, and the loser's
  -- SOURCE_LIST write would be clobbered; that source then re-decides, finds its own name
  -- already in ACTION_HISTORY with no restart between, and is parked as DOUBLE ACTION BLOCKED
  -- forever. A document with three sources simply takes three sweeps. Only 1,025 of 39,160 rows
  -- have more than one source, and the drain runs continuously.
  SELECT DISTINCT ON (b."ID") b."ID",
         (e.ord - 1)::int AS idx,
         -- The identity the action re-verifies before acting. The index is a dispatch label;
         -- this is what proves the element under it is still the same source.
         COALESCE(e.el->>'source_kind','') || '|' ||
         COALESCE(e.el->>'file_id', e.el->>'message_id', '') AS fkey
    FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2Driver01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.incoming_documents b
    JOIN input i3 ON i3."ID" = b."ID",
         LATERAL jsonb_array_elements(b."SOURCE_LIST") WITH ORDINALITY e(el, ord)
   WHERE jsonb_typeof(b."SOURCE_LIST") = 'array'
     AND e.el->>'required_feedback_type' IS NOT NULL
     AND COALESCE((e.el->>'sync_feedback_completed')::boolean, false) = false
   ORDER BY b."ID", e.ord
)
SELECT b.*,
       (x."ID" IS NOT NULL)                AS "IS_DOUBLE",
       COALESCE(x.rn = 1, false)           AS "IS_MAIN_DOUBLE",
       CASE WHEN x.rn = 1 THEN l.lines END AS "LINES_TO_MERGE",
       (SELECT merge_on FROM toggle)             AS "__merge_enabled",
       (SELECT feedback_on FROM toggle)          AS "__source_feedback_enabled",
       (SELECT priority_on FROM toggle)          AS "__priority_sync_enabled",
       (SELECT priority_local FROM toggle)       AS "__priority_local",
       (SELECT old_months FROM toggle)           AS "__old_months",
       -- [fan-out landed 2026-08-28] The value the driver was HANDED, passed straight through.
       -- It is the instance IDENTITY ('hacohen'), never the storage location ('indox_hacohen') —
       -- indoxApi01 stays the single place that maps identity to schema. Still empty when the
       -- caller supplies nothing (a manual webhook probe), which resolves to 'public' exactly as
       -- before; once the compatibility views are dropped that absence becomes a loud failure
       -- rather than a silent write into the first instance.
       '{{ $json.__instance || "" }}'::text      AS "__instance",
       fd.idx                                    AS "__feedback_idx",
       fd.fkey                                   AS "__feedback_key",
       -- [phase 5 2026-08-22] What the Priority payload for this row WOULD hash to right now.
       -- decide compares it against the stored "PRIORITY_SYNC_SIGNATURE" (what was last sent):
       -- equal => the client's record is already correct, stay silent; different => the line
       -- changed, re-send it. Computed here rather than in decide for the same reason
       -- __feedback_idx is -- decide is a pure function over one row -- and, more importantly,
       -- so that the formula has exactly ONE definition (the function), shared by this SELECT,
       -- the writeback and the verifier. A JS copy would drift, and drift here means either
       -- duplicate records in the client's ERP or a correction that never reaches them.
       public.indox_priority_signature(b.*)      AS "__priority_sig",
       -- [selection 2026-08-25] What the two selectors WOULD be deciding from right now. decide
       -- compares each against the hash stored when the selection last ran: equal => the decision
       -- still stands, different => a version changed underneath it (an aging report linked and
       -- wrote BS_LINE_*, a restart re-extracted, an operator corrected a field) and the selection
       -- is re-dispatched. Cheap by construction -- re-deciding reads no file and calls no model.
       -- Same one-definition rule as the priority signature above: the formula lives in the SQL
       -- function, and SelectBase01/SelectType01 reproduce it exactly when they write.
       public.indox_base_selection_hash(b.*)     AS "__base_selection_hash",
       public.indox_selection_hash(b.*)          AS "__selection_hash",
       -- [line-hash 2026-08-26, owner order] THE WHOLE LINE AS ONE VALUE, computed ONCE per line
       -- per pass, here, in a SELECT that was already running. It rides the line from this point
       -- on: decide passes it through, 'Dup Guard: Double Action' compares it against each
       -- ACTION_HISTORY entry, and indoxV2ActionRouter01 :: 'Log Action Start' stores it on the
       -- dispatch row -- so the value the guard judged and the value the log keeps are the same
       -- value, and nothing recomputes it anywhere. Cost measured on this table: ~0.2 ms/row.
       public.indox_line_hash(b.*)               AS "__line_hash"
FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2Driver01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.incoming_documents b
JOIN input i2 ON i2."ID" = b."ID"
LEFT JOIN dbl x ON x."ID" = b."ID"
LEFT JOIN losers l ON l.dup_key = x.dup_key AND x.rn = 1
LEFT JOIN feed fd ON fd."ID" = b."ID"
ORDER BY b."ID"`,
        options: {
            queryReplacement: "={{ $input.all().map(i => i.json.ID).join('|') }}",
        },
    };

    @node({
        id: 'drv-get-action-history',
        name: 'Get Action History',
        /*__n8n__*/ notes: "[action history 2026-08-20, owner order] The newest 16 dispatches per document, from public.indox_action_execution_log, as ACTION_HISTORY, each carrying the LINE_HASH the router stamped at dispatch time. This is what replaces reading the ACTION_LOG string: 'Dup Guard: Double Action' and decide's _log both key on it. DELIBERATELY ITS OWN NODE, not folded into 'Enrich Double Lines' -- that node answers 'is this row a duplicate DOCUMENT' (data quality, answered by a merge); this one answers 'what has this document already been DISPATCHED' (state-machine health). Same reason the two were renamed apart. Cost measured 2026-08-20: 33 ms for 2,000 documents (PK index, avg 8.4 rows/doc, p95 17, max 344). IDs are pipe-joined because n8n splits Query Parameters on commas. executeOnce: once for the batch, not once per row.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-2256, 3040],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
        executeOnce: true,
    })
    GetActionHistory = {
        operation: 'executeQuery',
        query: `=WITH input AS (SELECT unnest(string_to_array($1, '|')) AS "ID")
SELECT i."ID", COALESCE(h.hist, '[]'::jsonb) AS "ACTION_HISTORY",
       -- the step budget's counter (2026-09-02): dispatches since the last restart_* dispatch.
       -- ITERATION_COUNT on the row is only ever RESET (to 0 by the restart builders) and was
       -- never incremented anywhere, so decide's ceiling compared 0 < 15 forever; this count is
       -- what the ceiling was always meant to read, computed where the dispatch log is.
       COALESCE(c.n, 0)::int AS "__dispatches_since_restart"
FROM input i
LEFT JOIN LATERAL (
  SELECT count(*) AS n
  FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2Driver01: no valid __instance'); } return 'indox_' + i; })() }}.indox_action_execution_log y
  WHERE y."ID" = i."ID"
    AND y."STARTED_AT" > COALESCE((SELECT max(z."STARTED_AT") FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2Driver01: no valid __instance'); } return 'indox_' + i; })() }}.indox_action_execution_log z
                                   WHERE z."ID" = i."ID" AND z."ACTION" LIKE 'restart%'), '-infinity'::timestamptz)
) c ON true
LEFT JOIN LATERAL (
  -- 'h' is the LINE_HASH the router stamped when that dispatch opened. 'Dup Guard: Double
  -- Action' calls a repeat a double only when it still equals the line's hash now, so a
  -- dispatch row without one (written before 2026-08-26) can never block anything.
  SELECT jsonb_agg(jsonb_build_object(
           'a', e."ACTION", 's', e."STARTED_AT", 'e', e."ENDED_AT", 'h', e."LINE_HASH")
           ORDER BY e."STARTED_AT" DESC) AS hist
  -- 16, not 10: signal B (the completion-flag table) is gone, so this window is now the guard's
  -- ONLY reach back. 15 is the epoch's own step ceiling and the deepest last-restart measured
  -- 2026-08-20 was 13, so 16 closes the residue signal B used to cover.
  FROM (SELECT x."ACTION", x."STARTED_AT", x."ENDED_AT", x."LINE_HASH"
        FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2Driver01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.indox_action_execution_log x
        WHERE x."ID" = i."ID"
        ORDER BY x."STARTED_AT" DESC
        LIMIT 16) e
) h ON true`,
        options: {
            queryReplacement: "={{ $input.all().map(i => i.json.ID).join('|') }}",
        },
    };

    @node({
        id: 'drv-attach-action-history',
        name: 'Attach Action History',
        /*__n8n__*/ notes: "[action history 2026-08-20] Puts ACTION_HISTORY back onto the enriched rows. A postgres node REPLACES its input items, so 'Get Action History' cannot both read the log and carry 'Enrich Double Lines' computed columns (IS_DOUBLE / IS_MAIN_DOUBLE / LINES_TO_MERGE / __merge_enabled) through -- those exist only in that node's SQL output. The alternative is shipping all 2,000 full rows to the DB and back to re-attach one key, which costs far more than the 33 ms join. ORDER IS LOAD-BEARING: the history must be attached AFTER 'Enrich Double Lines', because that node re-selects b.* from incoming_documents and would drop anything attached before it. A document with no dispatches gets [], never undefined, so every consumer can read .length without a guard.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-2032, 3040],
    })
    AttachActionHistory = {
        jsCode: `// Map ID -> ACTION_HISTORY from the SQL node, then re-emit the enriched rows.
const hist = new Map(), disp = new Map();
for (const it of $input.all()) {
  const j = it.json || {};
  if (j.ID == null) continue;                     // alwaysOutputData placeholder on a 0-row result
  hist.set(String(j.ID), Array.isArray(j.ACTION_HISTORY) ? j.ACTION_HISTORY : []);
  disp.set(String(j.ID), Number(j.__dispatches_since_restart) || 0);
}
const rows = $('Enrich Double Lines').all();
return rows.map(it => {
  const j = { ...it.json, ACTION_HISTORY: hist.get(String(it.json.ID)) || [],
              __dispatches_since_restart: disp.get(String(it.json.ID)) || 0 };
  // [source feedback 2026-08-21] SOURCE_LIST NEVER ENTERS THE DECIDE PAYLOAD.
  // Measured today it is the FATTEST COLUMN ON THE TABLE -- 26 MB total, avg 692 B/row,
  // 1.37 MB per 2,000-row slice -- and it is pure ballast here: 'Enrich Double Lines' has
  // already reduced it to the two scalars decide actually needs (__feedback_idx and
  // __feedback_key). This is the same trade the 2026-08-17 slimming made for ACTION_LOG, and
  // it matters for the same reason: the worker aborts at Node's 2,600 MB V8 ceiling long
  // before the 4 GB container limit, so a fat column on a hot path shows up as OOM, not as
  // slowness. The ACTION lane re-reads SOURCE_LIST for its own group (<=150 documents) --
  // which is also fresher than a copy carried since decide.
  delete j.SOURCE_LIST;
  return { json: j };
});
`,
    };

    @node({
        id: '4216c82f-0307-4af9-a383-22205b82f691',
        name: 'Call indox-v2 Decide',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [-2256, 2816],
    })
    CallIndoxV2Decide = {
        workflowId: {
            __rl: true,
            value: 'indoxV2Decide01',
            mode: 'id',
            cachedResultName: 'indox-v2 Decide',
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
        id: '5159ba0c-d5a5-433d-8f48-30fefa75394a',
        name: 'Start',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-3152, 2960],
    })
    Start = {};

    @node({
        id: '4ab80998-4a9c-45ac-8521-3ead2c94f8f5',
        name: 'Loop keeper',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-2704, 2816],
    })
    LoopKeeper = {};



    @node({
        id: 'afe1789a-1214-4850-b105-ffbe78065a02',
        name: 'Taking Action',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-1136, 2768],
    })
    TakingAction = {};

    @node({
        id: '4d3bed48-4d48-450c-b300-84dc6cf387c7',
        name: 'Respond to Webhook',
        /*__n8n__*/ notes: "POSITION IS LOAD-BEARING. executionOrder v1 runs sibling branches TOPMOST-FIRST, so this node's y must stay ABOVE 'Code in JavaScript' (2960) and 'Execution Data4' (2768) for the webhook to ACK BEFORE the pipeline runs. It sat at y=3152 -- the lowest sibling -- until 2026-08-21, which meant the caller's POST blocked for the WHOLE driver run. Measured: lanes of 2,000 documents took 206-388 s against the drainer's 30 s HTTP timeout, so every lane came back with no execution id, the pool could not track a single one, and backpressure silently degraded to firing every batch at once. The response is the drainer's ONLY handle on the lane it just started; it must arrive immediately. Renamed 'completed' -> 'accepted' because responding first makes 'completed' a lie.",
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [-4960, 2600],
    })
    RespondToWebhook = {
        respondWith: 'json',
        responseBody: `={{ 
{
  "accepted": true,
  "execution": $execution.id
}
}}`,
        options: {},
    };

    @node({
        id: '535ac64a-555b-41d4-852c-1cd71e681bd1',
        name: 'Execution Data1',
        type: 'n8n-nodes-base.executionData',
        version: 1.1,
        position: [-240, 2672],
    })
    ExecutionData1 = {
        dataToSave: {
            values: [
                {
                    key: 'line_count',
                    value: '={{ $input.all().length}}',
                },
                {
                    key: 'actions',
                    value: '={{ $input.all().map(item => item.json.ACTION).filter((v, i, array) => array.indexOf(v) === i).toJsonString() }}',
                },
                {
                    key: 'exection_type',
                    value: 'planning_action',
                },
                {
                    key: 'has',
                    value: 'TRUE',
                },
                {
                    key: 'outline',
                    value: '=planning_{{ $input.all().map(item => item.json.ACTION).filter((v, i, array) => array.indexOf(v) === i).length }}_actions',
                },
                {
                    key: 'trigger_chain',
                    value: "={{ (() => { try { const b = $('Webhook').first().json.body || {};   if (b.TRIGGER_CHAIN) return String(b.TRIGGER_CHAIN) + '>' + String(b.TRIGGER_TYPE || 'webhook');   if (b.TRIGGER_TYPE) return String(b.TRIGGER_TYPE); } catch (e) {} try { const b = $('When Executed by Another Workflow').first().json.body || {};   if (b.TRIGGER_CHAIN) return String(b.TRIGGER_CHAIN) + '>' + String(b.TRIGGER_TYPE || 'executeWorkflow');   if (b.TRIGGER_TYPE) return String(b.TRIGGER_TYPE); } catch (e) {} try { if ($('Webhook').isExecuted) return 'webhook'; } catch (e) {} try { if ($('Schedule Trigger').isExecuted) return 'schedule'; } catch (e) {} try { if ($('When Executed by Another Workflow').isExecuted) return 'executeWorkflow'; } catch (e) {} try { if ($('When clicking ‘Execute workflow’').isExecuted) return 'manual'; } catch (e) {} return 'unknown'; })() }}",
                },
                {
                    key: 'origin_execution',
                    value: "={{ (() => { try { const o = ($('Webhook').first().json.body || {}).ORIGIN_EXECUTION; if (o) return String(o); } catch (e) {} try { const o = ($('When Executed by Another Workflow').first().json.body || {}).ORIGIN_EXECUTION; if (o) return String(o); } catch (e) {} return String($execution.id); })() }}",
                },
            ],
        },
    };

    @node({
        id: 'e2311e79-b6db-4ddb-8314-7048daf34b01',
        name: 'Execution Data4',
        type: 'n8n-nodes-base.executionData',
        version: 1.1,
        position: [-4960, 2768],
    })
    ExecutionData4 = {
        dataToSave: {
            values: [
                {
                    key: 'trigger_type',
                    value: "={{ (() => { try { const t = ($('Webhook').first().json.body || {}).TRIGGER_TYPE; if (t) return String(t); } catch (e) {} try { return String(($('When Executed by Another Workflow').first().json.body || {}).TRIGGER_TYPE || 'executeWorkflow'); } catch (e) { return 'webhook'; } })() }}",
                },
                {
                    key: 'trigger_chain',
                    value: "={{ (() => { try { const b = $('Webhook').first().json.body || {};   if (b.TRIGGER_CHAIN) return String(b.TRIGGER_CHAIN) + '>' + String(b.TRIGGER_TYPE || 'webhook');   if (b.TRIGGER_TYPE) return String(b.TRIGGER_TYPE); } catch (e) {} try { const b = $('When Executed by Another Workflow').first().json.body || {};   if (b.TRIGGER_CHAIN) return String(b.TRIGGER_CHAIN) + '>' + String(b.TRIGGER_TYPE || 'executeWorkflow');   if (b.TRIGGER_TYPE) return String(b.TRIGGER_TYPE); } catch (e) {} try { if ($('Webhook').isExecuted) return 'webhook'; } catch (e) {} try { if ($('Schedule Trigger').isExecuted) return 'schedule'; } catch (e) {} try { if ($('When Executed by Another Workflow').isExecuted) return 'executeWorkflow'; } catch (e) {} try { if ($('When clicking ‘Execute workflow’').isExecuted) return 'manual'; } catch (e) {} return 'unknown'; })() }}",
                },
                {
                    key: 'origin_execution',
                    value: "={{ (() => { try { const o = ($('Webhook').first().json.body || {}).ORIGIN_EXECUTION; if (o) return String(o); } catch (e) {} try { const o = ($('When Executed by Another Workflow').first().json.body || {}).ORIGIN_EXECUTION; if (o) return String(o); } catch (e) {} return String($execution.id); })() }}",
                },
                {
                    key: 'parent_execution',
                    value: "={{ (() => { try { const p = ($('Webhook').first().json.body || {}).PARENT_EXECUTION; if (p) return String(p); } catch (e) {} try { return String(($('When Executed by Another Workflow').first().json.body || {}).PARENT_EXECUTION || ''); } catch (e) { return ''; } })() }}",
                },
                {
                    key: 'drainer_type',
                    value: "={{ (() => { try { const b = $('Webhook').first().json.body || {}; if (b.DRAINER_TYPE) return String(b.DRAINER_TYPE); if (b.DRAINER_ID) return 'inherited'; if (b.TRIGGER_TYPE) return 'manual_webhook'; } catch (e) {} try { const b = $('When Executed by Another Workflow').first().json.body || {}; if (b.DRAINER_TYPE) return String(b.DRAINER_TYPE); if (b.DRAINER_ID) return 'inherited'; if (b.TRIGGER_TYPE) return 'manual_webhook'; } catch (e) {} return 'unknown_webhook'; })() }}",
                },
                {
                    key: 'drainer_id',
                    value: "={{ (() => { try { const b = $('Webhook').first().json.body || {}; if (b.DRAINER_ID) return String(b.DRAINER_ID); if (b.TRIGGER_TYPE) return String(b.TRIGGER_TYPE); } catch (e) {} try { const b = $('When Executed by Another Workflow').first().json.body || {}; if (b.DRAINER_ID) return String(b.DRAINER_ID); if (b.TRIGGER_TYPE) return String(b.TRIGGER_TYPE); } catch (e) {} return 'unknown_webhook'; })() }}",
                },
                {
                    key: 'drainer_chain',
                    value: "={{ (() => { let c = 'unknown_webhook'; try { const b = $('Webhook').first().json.body || {}; c = String(b.DRAINER_CHAIN || b.DRAINER_ID || b.TRIGGER_TYPE || ''); } catch (e) {} if (!c || c === 'unknown_webhook') { try { const b = $('When Executed by Another Workflow').first().json.body || {}; c = String(b.DRAINER_CHAIN || b.DRAINER_ID || b.TRIGGER_TYPE || 'unknown_webhook'); } catch (e) { c = c || 'unknown_webhook'; } } return (c || 'unknown_webhook') + '>' + $execution.id; })() }}",
                },
            ],
        },
    };


    @node({
        id: 'drv-post-router-group',
        name: 'POST Action Router (group)',
        /*__n8n__*/ notes: "[one lane per action 2026-08-16, owner order] Fed directly by Group By ACTION (the batching loop was removed): ONE blocking POST per ACTION, each carrying ALL of that action's lines. The node runs once per group item — the 2-3 action lanes fire concurrently (HTTP batching) and the node completes only when EVERY lane's router execution finished (webhook is responseNode, responds after actions + unlock). The Check Next lane (positioned BELOW this dispatch lane; v1 lane order = height of each lane's first node) therefore runs only after all lanes completed. timeout ~58 min per lane (router executionTimeout is 3600s — a lane that would exceed it means the id set is too big for one driver: split the ids across N drivers, the owner's scaling model). onError continueRegularOutput so one failed lane never blocks the others.",
        type: 'n8n-nodes-base.httpRequest',
        version: 4.3,
        position: [480, 2624],
        credentials: { httpBasicAuth: { id: 'azPhHBvOWaf9IsEA', name: 'Incoming Documents [env-managed]' } },
        onError: 'continueRegularOutput',
    })
    PostActionRouterGroup = {
        method: 'POST',
        url: 'http://n8n-webhook:5678/webhook/indox-action-router',
        authentication: 'genericCredentialType',
        genericAuthType: 'httpBasicAuth',
        sendBody: true,
        bodyParameters: {
            parameters: [
                {
                    name: 'ACTION_LINES',
                    value: '={{ $json.items.map(i => { const { mode, ...rest } = i; return rest; }) }}',
                },
                {
                    name: 'TRIGGER_TYPE',
                    value: 'group_action',
                },
                {
                    name: 'TRIGGER_CHAIN',
                    value: "={{ (() => { try { const b = $('Webhook').first().json.body || {};   if (b.TRIGGER_CHAIN) return String(b.TRIGGER_CHAIN) + '>' + String(b.TRIGGER_TYPE || 'webhook');   if (b.TRIGGER_TYPE) return String(b.TRIGGER_TYPE); } catch (e) {} try { const b = $('When Executed by Another Workflow').first().json.body || {};   if (b.TRIGGER_CHAIN) return String(b.TRIGGER_CHAIN) + '>' + String(b.TRIGGER_TYPE || 'executeWorkflow');   if (b.TRIGGER_TYPE) return String(b.TRIGGER_TYPE); } catch (e) {} try { if ($('Webhook').isExecuted) return 'webhook'; } catch (e) {} try { if ($('Schedule Trigger').isExecuted) return 'schedule'; } catch (e) {} try { if ($('When Executed by Another Workflow').isExecuted) return 'executeWorkflow'; } catch (e) {} try { if ($('When clicking ‘Execute workflow’').isExecuted) return 'manual'; } catch (e) {} return 'unknown'; })() }}",
                },
                {
                    name: 'ORIGIN_EXECUTION',
                    value: "={{ (() => { try { const o = ($('Webhook').first().json.body || {}).ORIGIN_EXECUTION; if (o) return String(o); } catch (e) {} try { const o = ($('When Executed by Another Workflow').first().json.body || {}).ORIGIN_EXECUTION; if (o) return String(o); } catch (e) {} return String($execution.id); })() }}",
                },
                {
                    name: 'PARENT_EXECUTION',
                    value: '={{ $execution.id }}',
                },
            ],
        },
        options: {
            batching: {
                batch: {
                    batchSize: 10,
                    batchInterval: 250,
                },
            },
            timeout: 3500000,
        },
    };



    @node({
        id: 'drv-stamp-subwf',
        name: 'Execution Data SubWorkflow',
        /*__n8n__*/ notes: "Without this, only the webhook entry stamped trigger_type and an execution could not be traced to its origin.",
        type: 'n8n-nodes-base.executionData',
        version: 1.1,
        position: [-4752, 2768],
    })
    ExecutionDataSubworkflow = {
        dataToSave: {
            values: [
                {
                    key: 'trigger_type',
                    value: 'executeWorkflow',
                },
                {
                    key: 'trigger_chain',
                    value: "={{ (() => { try { const b = $('Webhook').first().json.body || {};   if (b.TRIGGER_CHAIN) return String(b.TRIGGER_CHAIN) + '>' + String(b.TRIGGER_TYPE || 'webhook');   if (b.TRIGGER_TYPE) return String(b.TRIGGER_TYPE); } catch (e) {} try { const b = $('When Executed by Another Workflow').first().json.body || {};   if (b.TRIGGER_CHAIN) return String(b.TRIGGER_CHAIN) + '>' + String(b.TRIGGER_TYPE || 'executeWorkflow');   if (b.TRIGGER_TYPE) return String(b.TRIGGER_TYPE); } catch (e) {} try { if ($('Webhook').isExecuted) return 'webhook'; } catch (e) {} try { if ($('Schedule Trigger').isExecuted) return 'schedule'; } catch (e) {} try { if ($('When Executed by Another Workflow').isExecuted) return 'executeWorkflow'; } catch (e) {} try { if ($('When clicking ‘Execute workflow’').isExecuted) return 'manual'; } catch (e) {} return 'unknown'; })() }}",
                },
                {
                    key: 'origin_execution',
                    value: "={{ (() => { try { const o = ($('Webhook').first().json.body || {}).ORIGIN_EXECUTION; if (o) return String(o); } catch (e) {} try { const o = ($('When Executed by Another Workflow').first().json.body || {}).ORIGIN_EXECUTION; if (o) return String(o); } catch (e) {} return String($execution.id); })() }}",
                },
                {
                    key: 'drainer_type',
                    value: "={{ (() => { try { const w = $('When Executed by Another Workflow').first().json || {}; return String(w.DRAINER_TYPE || 'unknown_executeworkflow'); } catch (e) { return 'unknown_executeworkflow'; } })() }}",
                },
                {
                    key: 'drainer_id',
                    value: "={{ (() => { try { const w = $('When Executed by Another Workflow').first().json || {}; return String(w.DRAINER_ID || 'unknown_executeworkflow'); } catch (e) { return 'unknown_executeworkflow'; } })() }}",
                },
                {
                    key: 'drainer_chain',
                    value: "={{ (() => { let c = 'unknown_executeworkflow'; try { const w = $('When Executed by Another Workflow').first().json || {}; c = String(w.DRAINER_CHAIN || w.DRAINER_ID || 'unknown_executeworkflow'); } catch (e) {} return c + '>' + $execution.id; })() }}",
                },
            ],
        },
    };

    @node({
        id: 'foldget-get-line-req',
        name: 'Get Line Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-4048, 2848],
    })
    GetLineReq = {
        jsCode: `
// Field projection, VERBATIM in meaning from indoxDocGet01's trigger (inputSource:jsonExample).
// Keys outside this set were dropped by n8n before any node ran; the api is passthrough, so we
// must drop them here or they would silently become filters.
const DECLARED = ['ID','COMPANY_ID','SHORT_DOC_ID','TYPE','TYPE__in'];
const project = o => { const r = {}; for (const k of DECLARED) if (o[k] !== undefined) r[k] = o[k]; return r; };
// convertFieldsToString:true on the original executeWorkflow mapping -> values arrived as strings.
const asStr = o => { const r = {}; for (const [k,v] of Object.entries(o)) r[k] = (v===null||v===undefined) ? v : String(v); return r; };
// The original mapping was exactly {ID: $json.ID}. Reproduce it, then project.
// [multi-instance 2026-08-28] The instance travels WITH the request. It is not a filter: indoxApi01
// reads it to choose the SCHEMA and excludes it from column lists and filter pairs, so it is safe to
// send. Without it every api read from this driver resolved to 'public'.
// Read from a TRIGGER node, not from the MAP ID items — MAP ID is a Set node that projects
// fields and would drop it.
// TWO ENTRY PATHS, and reading only one was a live bug (2026-08-28): 'Code in JavaScript'
// normalises the WEBHOOK path, but this workflow is also called as a sub-workflow through
// 'When Executed by Another Workflow' — which is how the drain and the action router drive it,
// i.e. the overwhelming majority of real traffic. On that path $('Code in JavaScript') THROWS,
// the catch swallowed it, reqInstance was '', and every api read resolved to public. It only
// surfaced once indoxApi01's public fallback became a hard error. Try both, in order.
let reqInstance = '';
try { reqInstance = String(($('When Executed by Another Workflow').first().json || {}).__instance || ''); } catch (e) { reqInstance = ''; }
if (!reqInstance) { try { reqInstance = String(($('Code in JavaScript').first().json || {}).__instance || ''); } catch (e) { reqInstance = ''; } }
const queriesOf = items => items.map(i => project(asStr({ ID: i.json.ID })));

// --- below this line: logic of indoxDocGet01/'SB Get Req', unchanged in meaning ---
const IN_SUFFIX = '__in';
const queries = queriesOf($('MAP ID').all()).map(q => reqInstance ? Object.assign(q, { __instance: reqInstance }) : q);
const bad = v => v === null || v === undefined || v === '';
const filters = [];
for (const q of queries) {
  const base = {};
  const ins = [];
  for (const [k, v] of Object.entries(q)) {
    if (bad(v) || k === 'field_contains' || k === '__force_backend' || k === '_be') continue;
    if (k.endsWith(IN_SUFFIX)) {
      const col = k.slice(0, -IN_SUFFIX.length);
      const vals = String(v).split(',').map(s => s.trim()).filter(s => s !== '');
      if (col && vals.length) ins.push([col, vals]);
      continue;
    }
    base[k] = String(v);
  }
  let groups = [base];
  for (const [col, vals] of ins) {
    const next = [];
    for (const g of groups) for (const val of vals) next.push({ ...g, [col]: val });
    groups = next;
  }
  for (const g of groups) if (Object.keys(g).length) filters.push(g);
}
// Every query empty -> an impossible filter, so the matcher reports matchCount 0 rather than
// returning an ARBITRARY document (which is what a whole-table GET_ALL used to do).
if (!filters.length) return [{ json: { INLINE_ACTION: 'GET', filters: [{ ID: '__never__' }] } }];
return [{ json: { INLINE_ACTION: 'GET', filters } }];
`,
    };

    @node({
        id: 'foldget-call-indox-api-get-line-',
        name: 'Call indox api (Get Line)',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [-3824, 2848],
    })
    CallIndoxApiGetLine = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {},
    };

    @node({
        id: 'foldget-get-line-match',
        name: 'Get Line Match',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-3600, 2848],
    })
    GetLineMatch = {
        jsCode: `
// Field projection, VERBATIM in meaning from indoxDocGet01's trigger (inputSource:jsonExample).
// Keys outside this set were dropped by n8n before any node ran; the api is passthrough, so we
// must drop them here or they would silently become filters.
const DECLARED = ['ID','COMPANY_ID','SHORT_DOC_ID','TYPE','TYPE__in'];
const project = o => { const r = {}; for (const k of DECLARED) if (o[k] !== undefined) r[k] = o[k]; return r; };
// convertFieldsToString:true on the original executeWorkflow mapping -> values arrived as strings.
const asStr = o => { const r = {}; for (const [k,v] of Object.entries(o)) r[k] = (v===null||v===undefined) ? v : String(v); return r; };
// The original mapping was exactly {ID: $json.ID}. Reproduce it, then project.
const queriesOf = items => items.map(i => project(asStr({ ID: i.json.ID })));

// --- below this line: logic of indoxDocGet01/'SB Match', unchanged in meaning ---
// ORDER IS PART OF THE CONTRACT: the caller takes matches[0].
const IN_SUFFIX='__in';
const allRows=$input.all().map(i=>i.json).filter(r=>r&&r.ID);
const queries=queriesOf($('MAP ID').all());
const bad=v=>v===null||v===undefined||v==='';
const listOf=v=>String(v).split(',').map(s=>s.trim()).filter(s=>s!=='');
// [quadratic 2026-08-13] INDEX ONCE INSTEAD OF RESCANNING PER QUERY.
// This loop was O(queries x rows). \`queriesOf\` only ever emits {ID: ...} (it is literally
// \`{ID: i.json.ID}\` then projected), so every query rescanned the WHOLE row set to find one id.
// Measured 43.3 s at N=100. The hourly full-table sweep hands the driver 30,000 ids in one
// execution, which is 90,000x that work: both sweep firings died here with
//   "Task execution aborted because runner became unresponsive"
//   -> "Increase the memory available to the task runner with N8N_RUNNERS_MAX_OLD_SPACE_SIZE"
// against runners capped at 1.6 GB. No memory setting fixes a quadratic; the sweep had therefore
// NEVER dispatched a single action, and it also killed two healthy in-flight driver executions
// as collateral, losing the check-next hop for 140 documents.
//
// SEMANTICS ARE UNCHANGED. The fast path is taken ONLY when the query is exactly {ID}, which is
// the shape this node actually receives; anything else falls through to the original filter, so
// the __in ranking, multi-key matching and the empty-keys "match everything" case all behave
// exactly as before. Insertion order into each bucket preserves DB order, which the contract
// depends on ("the caller takes matches[0]").
const byId = new Map();
for (const r of allRows) {
  const k = String(r.ID);
  let bucket = byId.get(k);
  if (!bucket) { bucket = []; byId.set(k, bucket); }
  bucket.push(r);
}

const out=[];
for(const q of queries){ const qq={...q}; delete qq.__force_backend; delete qq._be;
  const keys=Object.keys(qq).filter(k=>!bad(qq[k]) && k!=='field_contains');
  const matches=(keys.length===1 && keys[0]==='ID')
    ? (byId.get(String(qq.ID)) || []).slice()
    : allRows.filter(r=> keys.every(k=>{
    if(k.endsWith(IN_SUFFIX)){
      const col=k.slice(0,-IN_SUFFIX.length);
      return listOf(qq[k]).includes(String(r[col]));
    }
    return String(r[k])===String(qq[k]);
  }));
  const inKeys=keys.filter(k=>k.endsWith(IN_SUFFIX));
  if(inKeys.length){
    const rank=r=>inKeys.reduce((acc,k)=>{
      const col=k.slice(0,-IN_SUFFIX.length);
      const vals=listOf(qq[k]);
      const i=vals.indexOf(String(r[col]));
      return acc + (i<0 ? vals.length : i);
    },0);
    matches.sort((a,b)=>rank(a)-rank(b));   // stable in V8: ties keep DB order
  }
  out.push({json:{...(matches[0]||{}), filter:q, matches, matchCount:matches.length}}); }
return out;
`,
    };

    @node({
        id: 'd20guard-0001-4000-8000-dupactionlog1',
        name: 'Dup Guard: Double Action',
        /*__n8n__*/ notes: "[renamed 2026-08-20, owner order] Was 'Dup Guard: Check ACTION_LOG'. A DOUBLE ACTION EXECUTION is a state-machine health fault -- the same action dispatched twice on one document with no ACTION_RESTART between -- which means the action is not changing state, or the machine is looping on it. It must error loudly; it is never merged and never retried quietly. Do NOT confuse it with a DOUBLE LINE (two rows are the same document, a data-quality fact answered by a merge), which is 'Enrich Double Lines'. The two shared the word 'double' and got read as one concept; the names now keep them apart.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-2032, 2816],
    })
    DupGuardDoubleAction = {
        jsCode: `// [#20 dup-action guard 2026-08-15, re-sourced 2026-08-20] A DOUBLE ACTION EXECUTION is the
// same action dispatched twice ON AN UNCHANGED LINE with no ACTION_RESTART between. It means the
// action is not changing state, or the machine is looping on it, so it is raised loudly and never
// retried quietly. (Not to be confused with a DOUBLE LINE -- two rows being the same document --
// which is 'Enrich Double Lines' and is answered by a merge.)
//
// The source is ACTION_HISTORY, the newest 16 rows of public.indox_action_execution_log, attached
// by 'Attach Action History'. It used to be substring matching over the ACTION_LOG column: a
// per-action list of literal log anchors (', Extract Base Doc, ' and friends) ANDed with the row's
// completion flag, because a log entry only appeared once the action's upsert had landed and was
// therefore not trustworthy on its own. The dispatch log records the dispatch itself, so the
// anchors have no job left -- every dispatch has a row. Dual-run before the switch: 6,354 rows
// across two full cycles, ZERO disagreements with the old string logic.
// [line-hash 2026-08-26, owner order] THE COMPLETION-FLAG TABLE IS GONE, AND WITH IT SIGNAL B.
// RULES used to answer "the row still carries this action's completion evidence", as a second,
// window-independent reason to call a repeat a double. Under the unchanged-line law below that
// evidence is not independent any more: every *_COMPLETED flag, and STATUS, and both selection
// hashes, ARE PART OF THE LINE. An action that stamped its flag changed the line, so its hash no
// longer matches and it has earned its re-run; an action that stamped nothing is already caught
// by the hash compare. What the flag added on top was only harm -- a COMPLETED document whose
// line an operator then corrected still read mark_completed.done === true, so decide's perfectly
// legitimate re-proposal was refused on evidence about a line that no longer exists.
// The residue signal B was covering -- a repeat deeper than the fetched window -- is closed by
// the window instead: 'Get Action History' now takes the newest 16 rather than 10, against a
// 15-step epoch ceiling (measured 2026-08-20: 8 of 27,256 documents had their last restart
// deeper than 10, max 13).

for (const item of $input.all()) {
  const j = item.json || {};
  const act = String(j.ACTION || '');
  let dup = false, why = '';

  // supported manual restart is never a duplicate
  const isRestart = act.indexOf('restart') === 0 || String(j.STATUS || '') === 'ACTION_RESTART';

  // ---- ACTION_HISTORY -- the newest 16 dispatch rows, newest first. ----
  // Entries are { a: ACTION, s: STARTED_AT, e: ENDED_AT, h: LINE_HASH }, attached by
  // 'Attach Action History' from public.indox_action_execution_log.
  //
  // [line-hash 2026-08-26, owner order] THE LINE MUST BE UNCHANGED, OR IT IS NOT A DOUBLE.
  // 'h' is the LINE_HASH stamped on that dispatch by indoxV2ActionRouter01 :: 'Log Action Start'
  // -- the whole line as one value, carried to it on the item. __line_hash is that same value for
  // the line NOW, computed once per line per pass by 'Enrich Double Lines'. Only an entry whose
  // 'h' still equals __line_hash counts: the action ran against exactly this content, and the
  // content has not moved since -- which IS the loop this guard exists to catch. A line that DID
  // change hands the action new inputs (a corrected field, a cleared *_COMPLETED mark, an operator
  // running the action by hand), so re-running it is work, not a fault, and the guard stays out of
  // the way.
  //
  // This replaces EXISTENCE ONLY (2026-08-20), which could not tell those two apart and refused
  // both. Measured 2026-08-26: an ad-hoc DOC_DATE normalisation (1 statement, 2,503 rows) left
  // 1,306 lines carrying a stale BASE_SELECTION_HASH, so decide re-proposed select_base every
  // sweep and this guard failed the lane every sweep -- 256 of 256 driver failures in 24 h,
  // 7,216 blocked lines across 1,180 documents, and not one of them a real loop.
  //
  // 'e' (ENDED_AT) is still never consulted for the VERDICT -- a crashed attempt buys no free
  // re-run, the 2026-08-20 law is untouched -- only below, to tell a live race from a stuck loop.
  // FAIL-OPEN, AND BOTH HASHES MUST EXIST: a dispatch row written before this landed carries no
  // 'h' and can never block anything, and neither can a line that arrived without a hash. Same
  // construction as the selection hashes, and it is what clears the backlog above with no
  // backfill and no mass ACTION_RESTART -- those rows re-arm on their next dispatch.
  //
  // Timestamps are ISO with a fixed +00:00 offset, so a string compare is chronological.
  const hist = Array.isArray(j.ACTION_HISTORY) ? j.ACTION_HISTORY : [];
  const nowHash = j.__line_hash == null ? '' : String(j.__line_hash);
  let lastSameAt = '', lastRestartAt = '', lastSameOpen = false;
  for (const h of hist) {                    // newest first, so the first hit IS the newest
    const a = String((h && h.a) || '');
    const s = String((h && h.s) || '');
    const lh = (h && h.h == null) ? '' : String(h.h);
    if (!lastRestartAt && a.indexOf('restart') === 0) lastRestartAt = s;
    // The newest same-action dispatch TAKEN ON THIS EXACT LINE -- not "the newest same-action
    // dispatch, if its hash happens to match". A matching dispatch with a changed one in between
    // is still a repeat on this content: the line came back to where that action already saw it,
    // so running it again produces what it produced then.
    if (!lastSameAt && a === act && nowHash && lh && lh === nowHash) {
      lastSameAt = s; lastSameOpen = !(h && h.e);
    }
  }
  if (!isRestart && act && act.indexOf('restart') !== 0) {
    // The only signal now: this action already ran against this exact line, and no restart since.
    // No blind spot on the restart side -- the window is the NEWEST 16, so if the matched dispatch
    // is in it, everything that happened after it is in it too.
    if (lastSameAt && (!lastRestartAt || lastSameAt > lastRestartAt)) {
      dup = true;
      why = act + ' already dispatched on this exact line (LINE_HASH ' + nowHash.slice(0, 8) +
            ', no restart after it)';
    }
  }

  // In-flight collision: both feeds dispatched the same doc and the row is mid-action
  // (STATUS=IN_PROGRESS). Concurrency is the lock's domain, not a double-run -- drop this
  // item silently onto the no_action path (like a lock-skip) instead of erroring. The loud
  // error stays for true dups: token/evidence present on a row NOT currently executing.
  // [in-flight by bracket 2026-08-25, double-action hunt] STATUS alone misses the race: a
  // pend doc's row stays COMPLETED while its send is mid-flight (STATUS is written by the
  // action's own upsert at the END), so two overlapping drains selecting the same doc parked
  // it as a dup and reported it every lane (measured: doc_msm94xrfo3umf2 blocked at 22:45:56
  // while its own dispatch, started 22:43:41, was still open until 22:46:17). The dispatch
  // log's OPEN bracket is the truthful in-flight signal: newest same-action entry with no
  // ENDED_AT and started within 20 minutes = live race, not a stuck loop. This consults 'e'
  // ONLY to classify skip-vs-park -- the line is dropped either way, so the 2026-08-20
  // existence-only law (no free re-run without ACTION_RESTART) is untouched.
  const raceWindowMs = 20 * 60 * 1000;
  const sameStartedMs = lastSameAt ? Date.parse(lastSameAt) : 0;
  const liveRace = lastSameOpen && sameStartedMs > 0 && (Date.now() - sameStartedMs) < raceWindowMs;
  // [strand re-run 2026-08-31, the driver's half of the rescue law] The inflight arm below
  // skipped on STATUS=IN_PROGRESS with NO age bound, so a doc whose driver died mid-action
  // (worker OOM/restart; bracket later closed by the 65-min reaper) was skipped FOREVER:
  // the drain's rescue clause re-selected it, decide re-answered the same action, and this
  // guard called that a live collision. Measured on hacohen: 173 IN_PROGRESS rows frozen
  // 6-72h. Past 70 minutes (over the router's own 3600s executionTimeout and the reaper
  // horizon -- the same dead-owner doctrine as 'Poll Progress' and the drain clause) the
  // dispatch provably has no live owner, and the action DID NOT COMPLETE (a completed action
  // writes its own terminal status; the row still says IN_PROGRESS). Re-running it is not a
  // double action -- the LINE_HASH law guards completed work, not work whose owner died.
  const ownerlessMs = 70 * 60 * 1000;
  const staleStrand = String(j.STATUS || '') === 'IN_PROGRESS' && sameStartedMs > 0 &&
    (Date.now() - sameStartedMs) >= ownerlessMs;
  if (dup && staleStrand && !liveRace) {
    dup = false; why = '';
    item.json.__strand_rerun = true; // forensics: this dispatch is a dead-owner re-run
  } else if (dup && (String(j.STATUS || '') === 'IN_PROGRESS' || liveRace)) {
    dup = false; why = '';
    item.json.ACTION = 'no_action_inflight_skip';
    item.json.__inflight_skip = true;
  }
  // [verdict-not-crash 2026-08-17, owner order] a blocked double is a VERDICT about the
  // doc, not a driver failure: rewrite to a no_action so the filter drops it from dispatch
  // and the run continues green. __dup_reason stays on the item for execution-data forensics.
  if (dup) { item.json.ACTION = 'no_action_double_action_blocked'; }
  item.json.__dup_in_log = dup;
  item.json.__dup_reason = dup
    ? ('DOUBLE ACTION on ' + String(j.ID || '?') + ': ' + why +
       ' -- only ACTION_RESTART may re-run it')
    : '';
}
return $input.all();
`,
    };

    @node({
        id: '88c06cc2-218e-4286-8de2-a0ab00d81f76',
        name: 'Loop Over Items',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [208, 2768],
    })
    LoopOverItems = {
        batchSize: 2,
        options: {
            reset: '={{ $prevNode.name.includes("Group By") }}',
        },
    };









    @node({
        id: 'ef499bef-0984-4f34-905e-146efd14bf6a',
        name: 'Main 2k batch',
        /*__n8n__*/ notes: "LINES per decide pass — not documents, and NOT an OCR bound. Verified from the graph: this loop feeds Start -> Enrich Double Lines -> Get Action History -> Attach Action History -> Call indox-v2 Decide (indoxV2Decide01), i.e. the state-machine decide step, which is pure JS over row data. Document/OCR concurrency is bounded downstream in the action lane itself (apitools admission control, APITOOLS_MAX_CONCURRENT_OCR), which is where it belongs. The only purpose of a bound HERE is to stop the decide step ingesting ~20k rows in one gulp; 5000 lines per pass is the owner's standing figure. A prior note on this node claimed 4 == apitools OCR concurrency and that this was the in-flight dispatch bound — that was wrong on both counts and throttled the whole state machine to 4 rows per sweep.",
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [-2928, 2960],
    })
    Main2kBatch = {
        batchSize: 2000,
        options: {},
    };

    @node({
        id: 'dupblock-park-0001',
        name: 'Double Blocked (park)',
        /*__n8n__*/ notes: "[deferred guard 2026-08-19, owner order] Replaces the immediate throw on the dup guard's false branch. The guard is NOT weakened -- by the time an item reaches here 'Dup Guard: Double Action' has ALREADY rewritten its ACTION to 'no_action_double_blocked', i.e. it decided the line should be PARKED, exactly like no_action_merge_blocked or a lock-skip. Throwing here overrode that park with a fatal and aborted the whole lane: measured 2026-08-19 exec 3431500, ONE poisoned document out of a 2,000-line batch killed a driver holding 9,765 ids, so the remaining 7,765 -- where that run's 672 actionable rows lived -- were never decided. Four lanes died the same way and the cycle made zero progress. This node records the offender and lets the lane finish; 'Raise Double Blocked' on the batch loop's DONE branch re-raises ALL of them at the end, so the run still fails loudly and nothing is silenced.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-1584, 3056],
    })
    DoubleBlockedPark = {
        jsCode: `// Park the line, keep the evidence. NO throw here -- 'Raise Double Blocked' re-raises ALL of them on the
// batch loop's done branch once every batch has been processed.
const out = [];
for (const item of $input.all()) {
  const j = item.json || {};
  const why = j.__dup_reason ||
    ('Action ' + j.ACTION + ' decided twice in one run on ' + j.ID + ' -- possible endless loop.');
  out.push({ json: { ...j, __double_blocked: true, __dup_reason: why } });
}
return out;
`,
    };

    @node({
        id: 'dupblock-raise-0001',
        name: 'Raise Double Blocked',
        /*__n8n__*/ notes: "[deferred guard 2026-08-19, owner order] Sits on 'Main 2k batch' output 0 (DONE) -- previously unconnected -- so it runs exactly once, after every batch of the lane has been decided and dispatched. Collects the offenders from EVERY run of 'Double Blocked (park)' and raises them together. An If + expression cannot do this: an expression sees only ONE run of a referenced node, and the park node runs once per 2k batch that contained a double, so an If would report whichever batch happened to be last. The guard is NOT weakened -- the run still ends in error and every offending line is named; it just fails AFTER the lane finished instead of instead of it. Before this, one poisoned document aborted a driver holding 9,765 ids (exec 3431500) and the cycle made zero progress.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-2720, 2656],
    })
    RaiseDoubleBlocked = {
        jsCode: `// Gather every line the dup guard parked, across ALL batches of this lane, and raise them
// together. .all(branch, run) throws once the run index is past the last run, and referencing a
// node that never executed throws too -- both mean "nothing was blocked", so both are caught.
const offenders = [];
for (let r = 0; r < 10000; r++) {
  let items;
  try { items = $('Double Blocked (park)').all(0, r); } catch (e) { break; }
  if (!items || !items.length) break;
  for (const it of items) offenders.push(it.json || {});
}
if (offenders.length) {
  const detail = offenders
    .map(j => (j.ID || '?') + ' :: ' + (j.__dup_reason || ('ACTION=' + j.ACTION)))
    .join(' | ');
  throw new Error('DOUBLE ACTION BLOCKED -- ' + offenders.length +
    ' line(s) in this run (raised after the lane finished its batches): ' + detail);
}
return $input.all();
`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.IfNotLocked.out(0).to(this.ExecuteAction.in(0));
        this.JoinLocked.out(0).to(this.IfNotLocked.in(0));
        this.RunById.out(0).to(this.MapId.in(0));
        this.WhenExecutedByAnotherWorkflow.out(0).to(this.ExecutionDataSubworkflow.in(0));
        this.WhenExecutedByAnotherWorkflow.out(0).to(this.CodeInJavascript.in(0));
        this.ExecuteAction.out(0).to(this.ExecutionData1.in(0));
        this.IfDry.out(0).to(this.DrySkipPark.in(0));
        this.IfDry.out(1).to(this.TakingAction.in(0));
        this.GroupByAction.out(0).to(this.LoopOverItems.in(0));
        this.Switch_.out(0).to(this.RunById.in(0));
        this.Switch_.out(1).to(this.Start.in(0));
        this.Switch_.out(2).to(this.StopAndError1.in(0));
        this.IfNotSameActionTwice.out(0).to(this.IfAction.in(0));
        this.IfNotSameActionTwice.out(1).to(this.DoubleBlockedPark.in(0));
        this.Webhook.out(0).to(this.CodeInJavascript.in(0));
        this.Webhook.out(0).to(this.ExecutionData4.in(0));
        this.Webhook.out(0).to(this.RespondToWebhook.in(0));
        this.CodeInJavascript.out(0).to(this.Switch_.in(0));
        this.MapIdMatchLineData.out(0).to(this.Start.in(0));
        this.MapId.out(0).to(this.GetLineReq.in(0));
        this.EnrichDoubleLines.out(0).to(this.GetActionHistory.in(0));
        this.Start.out(0).to(this.ReadActionCaps.in(0));
        this.Start.out(0).to(this.Main2kBatch.in(0));
        this.LoopKeeper.out(0).to(this.Main2kBatch.in(0));
        this.TakingAction.out(0).to(this.JoinLocked.in(0));
        this.TakingAction.out(0).to(this.CheckLocked.in(0));
        this.CallIndoxV2Decide.out(0).to(this.DupGuardDoubleAction.in(0));
        this.GetLineReq.out(0).to(this.CallIndoxApiGetLine.in(0));
        this.CallIndoxApiGetLine.out(0).to(this.GetLineMatch.in(0));
        this.GetLineMatch.out(0).to(this.MapIdMatchLineData.in(0));
        this.DupGuardDoubleAction.out(0).to(this.IfNotSameActionTwice.in(0));
        this.LoopOverItems.out(1).to(this.PostActionRouterGroup.in(0));
        this.PostActionRouterGroup.out(0).to(this.LoopOverItems.in(0));
        this.Main2kBatch.out(0).to(this.RaiseDoubleBlocked.in(0));
        this.Main2kBatch.out(1).to(this.LoopKeeper.in(0));
        this.Main2kBatch.out(1).to(this.EnrichDoubleLines.in(0));
        this.GetActionHistory.out(0).to(this.AttachActionHistory.in(0));
        this.AttachActionHistory.out(0).to(this.CallIndoxV2Decide.in(0));
    }
}
