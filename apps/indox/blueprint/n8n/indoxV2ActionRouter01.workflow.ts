import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox-v2 Action Router (main)
// Nodes   : 22  |  Connections: 27
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// RouterWebhook                      webhook                    [creds]
// WhenCalledDirectly                 executeWorkflowTrigger
// NormalizeActionLines               code
// StampEntry                         executionData
// LogActionStart                     postgres                   [creds]
// ActionsDispacher                   noOp
// Switch1                            switch
// CallIndoxV2ActionsDocBase          executeWorkflow            [alwaysOutput]
// CallIndoxV2ActionsGdoc             executeWorkflow            [alwaysOutput]
// CallIndoxV2ActionsBs               executeWorkflow            [alwaysOutput]
// CallIndoxV2ActionsShipment         executeWorkflow            [alwaysOutput]
// CallIndoxV2ActionsOrder            executeWorkflow            [alwaysOutput]
// CallIndoxV2ActionsReceipt          executeWorkflow            [alwaysOutput]
// SkipEmptyRowSheetsLegacy           noOp
// StopAndError                       stopAndError
// DispatchedLines                    code
// LogActionEnd                       postgres                   [creds]
// StampDone                          executionData
// RouterDone                         respondToWebhook           [onError→regular]
// JoinTypeBranches                   merge
// RestoreActionLines                 code
// RestoreDispatchedLines             code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// RouterWebhook
//    → NormalizeActionLines
//      → StampEntry
//        → LogActionStart
//          → RestoreActionLines
//            → ActionsDispacher
//              → Switch1
//                → CallIndoxV2ActionsDocBase
//                  → JoinTypeBranches
//                    → DispatchedLines
//                      → LogActionEnd
//                        → RestoreDispatchedLines
//                          → StampDone
//                            → RouterDone
//               .out(1) → CallIndoxV2ActionsGdoc
//                  → JoinTypeBranches.in(1) (↩ loop)
//               .out(2) → CallIndoxV2ActionsBs
//                  → JoinTypeBranches.in(2) (↩ loop)
//               .out(3) → RouterDone (↩ loop)
//               .out(4) → CallIndoxV2ActionsShipment
//                  → JoinTypeBranches.in(3) (↩ loop)
//               .out(5) → CallIndoxV2ActionsOrder
//                  → JoinTypeBranches.in(4) (↩ loop)
//               .out(6) → CallIndoxV2ActionsReceipt
//                  → JoinTypeBranches.in(5) (↩ loop)
//               .out(7) → StopAndError
// WhenCalledDirectly
//    → NormalizeActionLines (↩ loop)
// SkipEmptyRowSheetsLegacy
//    → RouterDone (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Router Webhook":{"main":[[{"node":"Normalize Action Lines","type":"main","index":0}]]},"When Called Directly":{"main":[[{"node":"Normalize Action Lines","type":"main","index":0}]]},"Normalize Action Lines":{"main":[[{"node":"Stamp Entry","type":"main","index":0}]]},"Stamp Entry":{"main":[[{"node":"Log Action Start","type":"main","index":0}]]},"Actions Dispacher":{"main":[[{"node":"Switch1","type":"main","index":0}]]},"Switch1":{"main":[[{"node":"Call indox-v2 Actions — DOC BASE","type":"main","index":0}],[{"node":"Call indox-v2 Actions — GDoc","type":"main","index":0}],[{"node":"Call indox-v2 Actions — BS","type":"main","index":0}],[{"node":"Router Done","type":"main","index":0}],[{"node":"Call indox-v2 Actions — Shipment","type":"main","index":0}],[{"node":"Call indox-v2 Actions — Order","type":"main","index":0}],[{"node":"Call indox-v2 Actions — Receipt","type":"main","index":0}],[{"node":"Stop and Error","type":"main","index":0}]]},"Call indox-v2 Actions — DOC BASE":{"main":[[{"node":"Join Type Branches","type":"main","index":0}]]},"Call indox-v2 Actions — GDoc":{"main":[[{"node":"Join Type Branches","type":"main","index":1}]]},"Call indox-v2 Actions — BS":{"main":[[{"node":"Join Type Branches","type":"main","index":2}]]},"Call indox-v2 Actions — Shipment":{"main":[[{"node":"Join Type Branches","type":"main","index":3}]]},"Join Type Branches":{"main":[[{"node":"Dispatched Lines","type":"main","index":0}]]},"Dispatched Lines":{"main":[[{"node":"Log Action End","type":"main","index":0}]]},"Skip empty_row (sheets legacy)":{"main":[[{"node":"Router Done","type":"main","index":0}]]},"Log Action Start":{"main":[[{"node":"Restore Action Lines","type":"main","index":0}]]},"Log Action End":{"main":[[{"node":"Restore Dispatched Lines","type":"main","index":0}]]},"Restore Action Lines":{"main":[[{"node":"Actions Dispacher","type":"main","index":0}]]},"Restore Dispatched Lines":{"main":[[{"node":"Stamp Done","type":"main","index":0}]]},"Stamp Done":{"main":[[{"node":"Router Done","type":"main","index":0}]]},"Call indox-v2 Actions — Order":{"main":[[{"node":"Join Type Branches","type":"main","index":4}]]},"Call indox-v2 Actions — Receipt":{"main":[[{"node":"Join Type Branches","type":"main","index":5}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-10T22:29:44.559Z","createdAt":"2026-08-10T22:29:44.559Z","role":"workflow:owner","workflowId":"indoxV2ActionRouter01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <person2@example.com>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2ActionRouter01',
    name: 'indox-v2 Action Router (main)',
    active: true,
    isArchived: false,
    tags: ['app:indox'],
    settings: {
        executionOrder: 'v1',
        callerPolicy: 'workflowsFromSameOwner',
        errorWorkflow: 'errorHandler01',
        availableInMCP: false,
        executionTimeout: 3600,
        binaryMode: 'separate',
    },
})
export class IndoxV2ActionRouterMainWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'ar-webhook',
        webhookId: 'a7c1f2e0-1111-4aaa-9bbb-actionrouter01',
        name: 'Router Webhook',
        /*__n8n__*/ notes: "Entry point 1: webhook. A webhook call creates a NEW Bull job — that is what makes group dispatch actually parallel; executeWorkflow would run integrated inside the caller slot. [completion-gated 2026-08-16, owner order] responseMode=responseNode: the caller's HTTP call now BLOCKS until Router Done responds AFTER the action workflows complete + unlock — that is the driver's wait-for-completion contract (check_next fires only after every group finished, killing the Group B stale-snapshot dups). The old onReceived note ('callers measured 125.7s of queue wait') described this same blocking as a bug; it is now the deliberate design — callers set 30-min timeouts.",
        type: 'n8n-nodes-base.webhook',
        version: 2.1,
        position: [-1120, 152],
        credentials: { httpBasicAuth: { id: 'azPhHBvOWaf9IsEA', name: 'Incoming Documents [env-managed]' } },
    })
    RouterWebhook = {
        httpMethod: 'POST',
        path: 'indox-action-router',
        authentication: 'basicAuth',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'ar-wftrigger',
        name: 'When Called Directly',
        /*__n8n__*/ notes: "Entry point 2: direct executeWorkflow, kept so tests and manual runs can drive the router without HTTP.",
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [-1120, 344],
    })
    WhenCalledDirectly = {
        workflowInputs: {
            values: [
                {
                    name: 'ACTION_LINES',
                    type: 'array',
                },
                {
                    name: 'ACTION_LINE',
                    type: 'object',
                },
                {
                    name: 'ID',
                },
                {
                    name: 'TRIGGER_TYPE',
                },
                {
                    name: 'TRIGGER_CHAIN',
                },
                {
                    name: 'ORIGIN_EXECUTION',
                },
                {
                    name: 'PARENT_EXECUTION',
                },
                {
                    name: '__instance',
                },
            ],
        },
    };

    @node({
        id: 'ar-normalise',
        name: 'Normalize Action Lines',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-896, 248],
    })
    NormalizeActionLines = {
        jsCode: `// Normalise every entry shape into one item per action line, and carry the trigger chain.
// Accepts: webhook body {ACTION_LINES|ACTION_LINE|ID}, or the same fields direct from
// executeWorkflow. TRIGGER_CHAIN accumulates so a run started by the schedule and continued
// via webhook reads "schedule>webhook>check_next" rather than losing its origin.
const out = [];
for (const item of $input.all()) {
  const src = item.json && item.json.body ? item.json.body : (item.json || {});
  const chainIn = String(src.TRIGGER_CHAIN || src.trigger_chain || "").trim();
  const thisTrigger = String(src.TRIGGER_TYPE || src.trigger_type || "webhook").trim();
  const chain = chainIn ? (chainIn + ">" + thisTrigger) : thisTrigger;
  const origin = String(src.ORIGIN_EXECUTION || src.origin_execution || "") || String($execution.id);
  const parent = String(src.PARENT_EXECUTION || src.parent_execution || "");
  const meta = { TRIGGER_CHAIN: chain, TRIGGER_TYPE: thisTrigger, ORIGIN_EXECUTION: origin, PARENT_EXECUTION: parent };
  const lines = Array.isArray(src.ACTION_LINES) ? src.ACTION_LINES
              : (src.ACTION_LINE ? [src.ACTION_LINE] : (src.ID ? [src] : []));
  for (const l of lines) out.push({ json: Object.assign({}, l, meta) });
}
if (!out.length) throw new Error("Action router received no ACTION_LINES / ACTION_LINE / ID");
// A line with no ACTION cannot be locked or routed — Switch1 would drop it into Stop and Error
// with "UnHandeled Document" and lose which caller sent it. Say so here instead.
const bad = out.filter(o => !o.json.ACTION);
if (bad.length) throw new Error("Action router received " + bad.length + " line(s) with no ACTION: " + JSON.stringify(bad.slice(0,3).map(b => b.json.ID)));
return out;`,
    };

    @node({
        id: 'ar-stamp-in',
        name: 'Stamp Entry',
        /*__n8n__*/ notes: "Highlight data: what ran, for which line ids, from which trigger, chained back to the origin execution.",
        type: 'n8n-nodes-base.executionData',
        version: 1.1,
        position: [-672, 248],
    })
    StampEntry = {
        dataToSave: {
            values: [
                {
                    key: 'exection_type',
                    value: 'executing_action',
                },
                {
                    key: 'trigger_type',
                    value: '={{ $json.TRIGGER_TYPE }}',
                },
                {
                    key: 'trigger_chain',
                    value: '={{ $json.TRIGGER_CHAIN }}',
                },
                {
                    key: 'origin_execution',
                    value: '={{ $json.ORIGIN_EXECUTION }}',
                },
                {
                    key: 'parent_execution',
                    value: '={{ $json.PARENT_EXECUTION }}',
                },
                {
                    key: 'line_count',
                    value: '={{ $input.all().length }}',
                },
                {
                    key: 'ids',
                    value: '={{ $input.all().map(i => i.json.ID).toJsonString() }}',
                },
                {
                    key: 'actions',
                    value: '={{ $input.all().map(i => i.json.ACTION).filter((v,i,a) => a.indexOf(v)===i).toJsonString() }}',
                },
                {
                    key: 'outline',
                    value: '={{ $input.first().json.ACTION }}_x_{{ $input.all().length }}_lines',
                },
            ],
        },
    };

    @node({
        id: 'ar-redis-start',
        name: 'Log Action Start',
        /*__n8n__*/ notes: "BEFORE dispatch. In the driver, start and end both hang off Actions Dispacher in parallel and write the SAME key, so whichever landed last won and the census read started=110 / ended=0. [line-hash 2026-08-26] Also stamps LINE_HASH -- the whole line as one value, carried on the item as __line_hash from indoxV2Driver01 :: 'Enrich Double Lines' (computed there ONCE per line per pass, by public.indox_line_hash). It is not recomputed here and must not be: the value the guard judged and the value the log stores have to be the same one. 'Log Action End' never touches the column.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-448, 248],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    LogActionStart = {
        operation: 'executeQuery',
        query: `=/* action dispatch bracket (start) — one row per (doc, action, execution). $1 is JSON with
   commas as chr(1) (the node splits params on ','); restored before parsing.

   [line-hash 2026-08-26, owner order] LINE_HASH is the whole document line, as one value. It is
   what makes a double action decidable: indoxV2Driver01 :: 'Dup Guard: Double Action' calls a
   repeat a fault only when this stored value still equals the line's hash at the next pass --
   same action, same content, nothing moved, so the action is not moving the document. If any
   field changed since (a corrected value, a cleared *_COMPLETED mark, an operator running the
   action by hand), the action has new inputs and the re-run is legitimate work, not a loop.

   PASSED THROUGH, NOT RECOMPUTED. The line already carries its own hash: indoxV2Driver01 ::
   'Enrich Double Lines' computes public.indox_line_hash(b.*) once per line per pass, as
   __line_hash, in the SELECT it was already running. That one value is what decide judged, what
   the guard compared, and what lands here -- so the hash is calculated in exactly ONE place,
   exactly ONCE, and the writer and the reader cannot drift apart.

   A missing __line_hash (a caller that did not come through the driver -- a test firing the
   router webhook directly) stores NULL, and NULL can never block anything: the guard needs both
   hashes to exist, the same fail-open construction as the selection hashes.

   [multi-instance 2026-08-28] The schema is resolved from __instance, which reaches this node the
   same way __line_hash does -- as a "__" field the driver put on the row. Absent (a caller that
   did not come through the driver) resolves to public, i.e. today's behaviour; once the
   compatibility views are dropped that absence becomes a loud failure rather than a silent write
   into the first instance's action log. */
INSERT INTO {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2ActionRouter01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.indox_action_execution_log
  ("ID","ACTION","EXECUTION_ID","NAME","DOC_STATUS","TRIGGER","ORIGIN_EXECUTION","LINE_HASH")
SELECT j->>'ID', j->>'ACTION', j->>'EXECUTION_ID', j->>'NAME', j->>'DOC_STATUS',
       j->>'TRIGGER', j->>'ORIGIN_EXECUTION', nullif(j->>'LINE_HASH','')
FROM (SELECT replace($1, chr(1), ',')::jsonb AS j) t
ON CONFLICT ("ID","ACTION","EXECUTION_ID") DO NOTHING`,
        options: {
            queryBatching: 'independently',
            queryReplacement:
                '={{ JSON.stringify({ "ID": $json.ID, "ACTION": $json.ACTION, "EXECUTION_ID": $execution.id, "NAME": $json.NAME, "DOC_STATUS": $json.STATUS, "TRIGGER": $json.TRIGGER_CHAIN, "ORIGIN_EXECUTION": $json.ORIGIN_EXECUTION, "LINE_HASH": $json.__line_hash || "" }).replaceAll(\',\', String.fromCharCode(1)) }}',
        },
    };

    @node({
        id: '20634b83-3e2b-448a-8958-94f47980b0b4',
        name: 'Actions Dispacher',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [0, 248],
    })
    ActionsDispacher = {};

    @node({
        id: '94c996b3-0fab-4e29-9a03-e16dd3b4302c',
        name: 'Switch1',
        type: 'n8n-nodes-base.switch',
        version: 3.3,
        position: [224, 184],
    })
    Switch1 = {
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
                                id: '8ccfa83d-d394-4a92-bbcf-f085a3e81900',
                                leftValue:
                                    '={{ [ "restart_base", "update_status_missing_company", "no_action_awaiting_company_id", "get_company_name", "update_status_unknwon_company", "no_action_awaiting_company_name", "update_status_missing_type", "update_status_double", "update_status_old_doc", "mark_max_iterations", "no_action_max_iterations", "no_action_double", "no_action_paused", "no_action_old_date", "no_action_delete_row", "no_action_unknown_document_type", "no_action_already_completed", "no_action_source_list_overflow", "extract_base_doc", "action_merge_doubles", "no_action_merged", "update_status_garbage", "no_action_garbage", "select_base" ] }}',
                                rightValue: '={{ $json.ACTION }}',
                                operator: {
                                    type: 'array',
                                    operation: 'contains',
                                    rightType: 'any',
                                },
                            },
                            {
                                id: 'sfb-prefix-0001',
                                leftValue: '={{ String($json.ACTION || "") }}',
                                rightValue: 'source_feedback_',
                                operator: {
                                    type: 'string',
                                    operation: 'startsWith',
                                },
                            },
                        ],
                        combinator: 'or',
                    },
                    renameOutput: true,
                    outputKey: 'DOC BASE Actions',
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
                                leftValue: '={{ $json.DOC_TYPE }}',
                                rightValue: 'invoice',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                                id: '2782c127-22b7-4398-b941-ed680643aca5',
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'Invoice Actions',
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
                                id: '160129db-2ecf-4d54-b677-0048307820dc',
                                leftValue: '={{ $json.DOC_TYPE }}',
                                rightValue: 'bs_doc',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                    name: 'filter.operator.equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'BS Doc Actions',
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
                                id: 'b5da17b4-9fe2-4626-b246-4b1b05994644',
                                leftValue: '={{ $json.DOC_TYPE }}',
                                rightValue: 'empty_row',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                    name: 'filter.operator.equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'empty_row',
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
                                leftValue: '={{ $json.DOC_TYPE }}',
                                rightValue: 'shipment',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'Shipment Doc Actions',
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
                                id: 'ord-doctype-0001',
                                leftValue: '={{ $json.DOC_TYPE }}',
                                rightValue: 'order',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                    name: 'filter.operator.equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'Order Actions',
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
                                id: 'rcp-doctype-0001',
                                leftValue: '={{ $json.DOC_TYPE }}',
                                rightValue: 'receipt',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                    name: 'filter.operator.equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'Receipt Actions',
                },
            ],
        },
        options: {
            fallbackOutput: 'extra',
        },
    };

    @node({
        id: 'v2call0',
        name: 'Call indox-v2 Actions — DOC BASE',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [448, -208],
        alwaysOutputData: true,
    })
    CallIndoxV2ActionsDocBase = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ActionsGlobal01',
            mode: 'id',
            cachedResultName: 'indox-v2 Actions — DOC BASE',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'v2call1',
        name: 'Call indox-v2 Actions — GDoc',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [448, -16],
        alwaysOutputData: true,
    })
    CallIndoxV2ActionsGdoc = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ActionsInv01',
            mode: 'id',
            cachedResultName: 'indox-v2 Actions — Invoice',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'v2call2',
        name: 'Call indox-v2 Actions — BS',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [448, 176],
        alwaysOutputData: true,
    })
    CallIndoxV2ActionsBs = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ActionsBS01',
            mode: 'id',
            cachedResultName: 'indox-v2 Actions — BS',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'drvcallship01',
        name: 'Call indox-v2 Actions — Shipment',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [448, 368],
        alwaysOutputData: true,
    })
    CallIndoxV2ActionsShipment = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ActionsShip01',
            mode: 'id',
            cachedResultName: 'indox-v2 Actions — Shipment',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'drvcallorder01',
        name: 'Call indox-v2 Actions — Order',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [448, 528],
        alwaysOutputData: true,
    })
    CallIndoxV2ActionsOrder = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ActionsOrd01',
            mode: 'id',
            cachedResultName: 'indox-v2 Actions — Order',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'drvcallreceipt01',
        name: 'Call indox-v2 Actions — Receipt',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [448, 688],
        alwaysOutputData: true,
    })
    CallIndoxV2ActionsReceipt = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ActionsRcp01',
            mode: 'id',
            cachedResultName: 'indox-v2 Actions — Receipt',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'skip-empty-row',
        name: 'Skip empty_row (sheets legacy)',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [1568, 512],
    })
    SkipEmptyRowSheetsLegacy = {};

    @node({
        id: '1309edd2-fd91-4ada-a81b-96646c3472e0',
        name: 'Stop and Error',
        type: 'n8n-nodes-base.stopAndError',
        version: 1,
        position: [448, 656],
    })
    StopAndError = {
        errorMessage: 'UnHandeled Document',
    };

    @node({
        id: 'ar-collect',
        name: 'Dispatched Lines',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [896, 80],
    })
    DispatchedLines = {
        jsCode: `// Which lines did the branch that just finished actually carry? $prevNode tells us which Call
// node handed control back, and Switch1 output index maps 1:1 to that Call node.
const IDX = { 'Call indox-v2 Actions — DOC BASE': 0, 'Call indox-v2 Actions — GDoc': 1,
              'Call indox-v2 Actions — BS': 2, 'Call indox-v2 Actions — Shipment': 4 };
// This node must NEVER throw. By the time it runs the action has ALREADY been executed, so an
// exception here would mark a router execution failed for work that actually succeeded — it
// would manufacture exactly the kind of false signal this whole change exists to remove.
// Three ladders down, each strictly weaker than the last, and a bare $input.all() at the bottom.
let lines = null;
const idx = IDX[($prevNode && $prevNode.name) || ""];
if (idx !== undefined) { try { lines = $("Switch1").all(idx); } catch (e) { lines = null; } }
if (!lines || !lines.length) { try { lines = $("Actions Dispacher").all(); } catch (e) { lines = null; } }
if (!lines || !lines.length) lines = $input.all();
return lines;`,
    };

    @node({
        id: 'ar-redis-end',
        name: 'Log Action End',
        /*__n8n__*/ notes: "AFTER the routers returned. Same primary key as Log Action Start by design — (\"ID\",\"ACTION\",\"EXECUTION_ID\") is the identity of one dispatch; this upsert stamps ENDED_AT, so a row without it is a dispatch that is still running or died mid-flight.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [1120, 80],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    LogActionEnd = {
        operation: 'executeQuery',
        query: `=/* action dispatch bracket (end) — upsert so an end without a start still lands.
   [multi-instance 2026-08-28] Same resolver as 'Log Action Start', and it MUST stay the same: the
   two brackets write the same primary key, so a start and an end that resolved to different
   schemas would leave an unclosed row in one instance and an orphan end in the other. */
INSERT INTO {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2ActionRouter01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.indox_action_execution_log
  ("ID","ACTION","EXECUTION_ID","NAME","DOC_STATUS","TRIGGER","ORIGIN_EXECUTION","ENDED_AT")
SELECT j->>'ID', j->>'ACTION', j->>'EXECUTION_ID', j->>'NAME', j->>'DOC_STATUS',
       j->>'TRIGGER', j->>'ORIGIN_EXECUTION', now()
FROM (SELECT replace($1, chr(1), ',')::jsonb AS j) t
ON CONFLICT ("ID","ACTION","EXECUTION_ID")
DO UPDATE SET "ENDED_AT"=now(), "DOC_STATUS"=EXCLUDED."DOC_STATUS"`,
        options: {
            queryBatching: 'independently',
            queryReplacement:
                '={{ JSON.stringify({ "ID": $json.ID, "ACTION": $json.ACTION, "EXECUTION_ID": $execution.id, "NAME": $json.NAME, "DOC_STATUS": $json.STATUS, "TRIGGER": $json.TRIGGER_CHAIN, "ORIGIN_EXECUTION": $json.ORIGIN_EXECUTION }).replaceAll(\',\', String.fromCharCode(1)) }}',
        },
    };

    @node({
        id: 'ar-stamp-done',
        name: 'Stamp Done',
        type: 'n8n-nodes-base.executionData',
        version: 1.1,
        position: [1568, 80],
    })
    StampDone = {
        dataToSave: {
            values: [
                {
                    key: 'exection_type',
                    value: 'action_completed',
                },
                {
                    key: 'completed_lines',
                    value: '={{ $input.all().length }}',
                },
                {
                    key: 'completed_ids',
                    value: '={{ $input.all().map(i => i.json.ID).toJsonString() }}',
                },
                {
                    key: 'branch',
                    value: '={{ $prevNode.name }}',
                },
            ],
        },
    };

    @node({
        id: 'ar-router-done',
        name: 'Router Done',
        /*__n8n__*/ notes: "[completion-gated 2026-08-16] The webhook response — sent only AFTER the action workflows returned (fed by Stamp Done). By then every action's UPSERT has already released its doc_action lock (indoxApi01 'API Unlock Doc' + processLock01 doc-scoped unlock — unlock lives ONLY at the upsert now; the router's own Unlock Doc Action was REMOVED 2026-08-16 by owner order: firing after Dispatched Lines, it could release a lock another driver had ALREADY taken for the doc's NEXT action — a duplication mechanism). empty_row lines respond here directly and their locks die by TTL (legacy lane, no upsert). onError continueRegularOutput so the direct executeWorkflow entry (tests, manual runs — no webhook to respond to) never fails on this node.",
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [1792, 248],
        onError: 'continueRegularOutput',
    })
    RouterDone = {
        respondWith: 'json',
        responseBody: '={{ { "completed": true, "execution": $execution.id, "lines": $input.all().length } }}',
        options: {},
    };

    @node({
        id: 'join-type-branches-0001',
        name: 'Join Type Branches',
        /*__n8n__*/ notes: "[multi-type group fix 2026-08-17, owner order] One action group can carry docs of SEVERAL DOC_TYPEs (measured: exec 3374270 carried extract_per_type for a gdoc + a shipment). Switch1 then splits into parallel Call branches, and the tail (Dispatched Lines -> ... -> Router Done) used to run PER BRANCH — the first branch's Router Done answered the caller while the other branch (and its upsert) was still running, which broke the completion-gated contract and produced the 6s duplicate-dispatch class. This merge joins ALL type branches, so the tail and the webhook response fire exactly once, after every branch finished.",
        type: 'n8n-nodes-base.merge',
        version: 3.2,
        position: [672, 48],
    })
    JoinTypeBranches = {
        numberInputs: 6,
    };

    @node({
        id: 'restore-0000-4000-8000-actlines0001',
        name: 'Restore Action Lines',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-224, 248],
    })
    RestoreActionLines = {
        jsCode: `// The postgres log node replaces the item stream with its query result
// (the redis node it replaced passed items through). Re-emit the payload
// so downstream keeps receiving the action lines, not INSERT stubs.
return $('Stamp Entry').all();`,
    };

    @node({
        id: 'restore-0000-4000-8000-displines001',
        name: 'Restore Dispatched Lines',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1344, 80],
    })
    RestoreDispatchedLines = {
        jsCode: `// The postgres log node replaces the item stream with its query result
// (the redis node it replaced passed items through). Re-emit the payload
// so downstream keeps receiving the action lines, not INSERT stubs.
return $('Dispatched Lines').all();`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.RouterWebhook.out(0).to(this.NormalizeActionLines.in(0));
        this.WhenCalledDirectly.out(0).to(this.NormalizeActionLines.in(0));
        this.NormalizeActionLines.out(0).to(this.StampEntry.in(0));
        this.StampEntry.out(0).to(this.LogActionStart.in(0));
        this.ActionsDispacher.out(0).to(this.Switch1.in(0));
        this.Switch1.out(0).to(this.CallIndoxV2ActionsDocBase.in(0));
        this.Switch1.out(1).to(this.CallIndoxV2ActionsGdoc.in(0));
        this.Switch1.out(2).to(this.CallIndoxV2ActionsBs.in(0));
        this.Switch1.out(3).to(this.RouterDone.in(0));
        this.Switch1.out(4).to(this.CallIndoxV2ActionsShipment.in(0));
        this.Switch1.out(5).to(this.CallIndoxV2ActionsOrder.in(0));
        this.Switch1.out(6).to(this.CallIndoxV2ActionsReceipt.in(0));
        this.Switch1.out(7).to(this.StopAndError.in(0));
        this.CallIndoxV2ActionsDocBase.out(0).to(this.JoinTypeBranches.in(0));
        this.CallIndoxV2ActionsGdoc.out(0).to(this.JoinTypeBranches.in(1));
        this.CallIndoxV2ActionsBs.out(0).to(this.JoinTypeBranches.in(2));
        this.CallIndoxV2ActionsShipment.out(0).to(this.JoinTypeBranches.in(3));
        this.JoinTypeBranches.out(0).to(this.DispatchedLines.in(0));
        this.DispatchedLines.out(0).to(this.LogActionEnd.in(0));
        this.SkipEmptyRowSheetsLegacy.out(0).to(this.RouterDone.in(0));
        this.LogActionStart.out(0).to(this.RestoreActionLines.in(0));
        this.LogActionEnd.out(0).to(this.RestoreDispatchedLines.in(0));
        this.RestoreActionLines.out(0).to(this.ActionsDispacher.in(0));
        this.RestoreDispatchedLines.out(0).to(this.StampDone.in(0));
        this.StampDone.out(0).to(this.RouterDone.in(0));
        this.CallIndoxV2ActionsOrder.out(0).to(this.JoinTypeBranches.in(4));
        this.CallIndoxV2ActionsReceipt.out(0).to(this.JoinTypeBranches.in(5));
    }
}
