import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox-v2 Actions — Order
// Nodes   : 10  |  Connections: 10
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenCalled                         executeWorkflowTrigger
// RouteMode                          switch
// DecideOrderAction                  code
// DedupeDocsExecute                  code
// OrderActionSwitch                  switch
// ActionMarkCompleted                noOp
// LoopOverItems                      splitInBatches
// BuildCallIncomingDocumentBatchUpdateStatusCompleted set
// UpsertCentral                      executeWorkflow
// StopAndErrorUnhandledAction        stopAndError
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → RouteMode
//      → DecideOrderAction
//     .out(1) → DedupeDocsExecute
//        → OrderActionSwitch
//          → ActionMarkCompleted
//            → LoopOverItems
//             .out(1) → BuildCallIncomingDocumentBatchUpdateStatusCompleted
//                → UpsertCentral
//             .out(1) → LoopOverItems (↩ loop)
//         .out(1) → StopAndErrorUnhandledAction
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"Route Mode","type":"main","index":0}]]},"Route Mode":{"main":[[{"node":"Decide Order Action","type":"main","index":0}],[{"node":"Dedupe Docs (execute)","type":"main","index":0}]]},"Dedupe Docs (execute)":{"main":[[{"node":"ORDER Action Switch","type":"main","index":0}]]},"ORDER Action Switch":{"main":[[{"node":"Action: Mark Completed","type":"main","index":0}],[{"node":"Stop and Error - Unhandled ACTION","type":"main","index":0}]]},"Action: Mark Completed":{"main":[[{"node":"Loop Over Items","type":"main","index":0}]]},"Loop Over Items":{"main":[[],[{"node":"Build: Call 'Incoming Document Batch Update' - STATUS COMPLETED","type":"main","index":0},{"node":"Loop Over Items","type":"main","index":0}]]},"Build: Call 'Incoming Document Batch Update' - STATUS COMPLETED":{"main":[[{"node":"Upsert (central)","type":"main","index":0}]]},"Upsert (central)":{"main":[[]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"1a1f9021-970c-46eb-8cef-4746d2dca0d0","name":"indox-state-machine-v2"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-27T14:34:51.081Z","createdAt":"2026-08-27T14:34:51.081Z","role":"workflow:owner","workflowId":"indoxV2ActionsOrd01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2ActionsOrd01',
    name: 'indox-v2 Actions — Order',
    active: true,
    isArchived: false,
    tags: ['indox-state-machine-v2', 'app:indox', 'indox-app'],
    settings: {
        executionOrder: 'v1',
        callerPolicy: 'workflowsFromSameOwner',
        errorWorkflow: 'errorHandler01',
        availableInMCP: false,
        binaryMode: 'separate',
        executionTimeout: 3600,
    },
})
export class IndoxV2ActionsOrderWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'ordv2trig',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, 0],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'ordroutemode01',
        name: 'Route Mode',
        /*__n8n__*/ notes: "Same two-mode contract every typed router carries: 'decide'/'export_decide' go to the decide node, anything else is a real dispatch. Output 0 is decide, the fallback ('extra') is execute.",
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [224, 0],
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
        id: 'ord-decide-01',
        name: 'Decide Order Action',
        /*__n8n__*/ notes: "THE order decide. Lives HERE, like every other lane's: mode='export_decide' returns { fnSrc } and indoxV2Decide01's Mega Decide rehydrates it with new Function under its own $/$execution. Decide logic lives ONLY in the routers.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [448, -112],
    })
    DecideOrderAction = {
        jsCode: `function __orderDecideFn(__items) {
// [parked lane 2026-08-27, owner order] AN ORDER IS RECORDED, NOT PROCESSED.
// Until today ORDER resolved to the 'gdoc' class and gdocDecide aliased orderDecide straight
// onto invoiceDecide, so every order ran the full invoice pipeline. Measured over the 24h
// before this change: 352 ORDER dispatches, of which 79 were priority_sync -- an order posted
// to the client's ERP as though it were a payable document, plus per-type OCR extraction for
// invoice fields an order does not carry. Base extraction already resolves COMPANY_ID / TYPE /
// DOC_DATE, and that is the whole reason these rows are kept.
//
// ONE EXECUTABLE ACTION. The driver filters every ACTION beginning 'no_action' BEFORE dispatch
// (indoxV2Driver01 :: 'If Action', notStartsWith), so no_action_already_completed is an inert
// verdict that never reaches this workflow. mark_completed is the entire executable surface.
//
// NO restart arm, deliberately. ACTION_RESTART !== 'COMPLETED', so a restarted row answers
// mark_completed and lands on the next sweep. That is NOT a double action: indox_line_hash()
// is md5(row - updated_at) and STATUS is inside it, so writing ACTION_RESTART already moved
// the hash the dup guard compares against. A restart body that cleared *_COMPLETED flags would
// have nothing to clear here -- this lane sets no extraction, selection or sync flag.
//
// MERGED stays absorbing, the one terminal signal a lane guard needs (doubles are decided in
// ONE place, indoxV2Decide01, from the driver's SQL detector).
  return __items.map(item => {
    const d = item.json;
    for (const k of Object.keys(d)) {              // supabase TEXT-boolean safety
      if (typeof d[k] === 'string') {
        const s = d[k].trim().toLowerCase();
        if (s === 'true') d[k] = true; else if (s === 'false') d[k] = false;
      }
    }
    d.ACTION = String(d.STATUS || '') === 'MERGED' ? 'no_action_merged'
             : d.STATUS !== 'COMPLETED'            ? 'mark_completed'
             :                                       'no_action_already_completed';
    d.DOC_TYPE = 'order';
    delete d.mode;                                 // clean handoff (execute call must not re-decide)
    return item;
  });
}
const __mode = String((($input.first()||{}).json||{}).mode || '');
if (__mode === 'export_decide') return [{ json: { fnSrc: __orderDecideFn.toString() } }];
return __orderDecideFn($input.all());`,
    };

    @node({
        id: 'ord-dedupe-01',
        name: 'Dedupe Docs (execute)',
        /*__n8n__*/ notes: "ONE DOCUMENT, ONE ACTION, PER DISPATCH — the same guard the GDoc lane carries. Without it a batch holding the same ID twice fires mark_completed twice inside ONE execution, and both dispatches captured the SAME line hash, so the dup guard would correctly call that a double.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [448, 112],
    })
    DedupeDocsExecute = {
        jsCode: `
// Decide mode is deliberately untouched (the caller pairs verdicts to inputs item-for-item);
// this node only ever sees the execute branch, and the mode test is kept so that stays true
// if the wiring ever changes.
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
        id: 'ord-action-switch-01',
        name: 'ORDER Action Switch',
        /*__n8n__*/ notes: "One route. Unlike the older lanes (switch v2, whose 'unhandled' arm matches a literal '__unhandled_action__' nothing emits, so an unexpected ACTION is silently DROPPED), this uses the v3 fallback so an unexpected ACTION errors loudly instead of vanishing.",
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [672, 112],
    })
    OrderActionSwitch = {
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
                                id: 'ord-act-mc-0001',
                                leftValue: '={{ $json.ACTION }}',
                                rightValue: 'mark_completed',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'mark_completed',
                },
            ],
        },
        options: {
            fallbackOutput: 'extra',
        },
    };

    @node({
        id: 'ord-action-mark-completed-01',
        name: 'Action: Mark Completed',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [896, 0],
    })
    ActionMarkCompleted = {};

    @node({
        id: 'ord-loop-01',
        name: 'Loop Over Items',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [1120, 0],
    })
    LoopOverItems = {
        batchSize: 1000,
        options: {
            reset: '={{ !String($prevNode.name).includes("Loop")  }}',
        },
    };

    @node({
        id: 'ord-build-completed-01',
        name: "Build: Call 'Incoming Document Batch Update' - STATUS COMPLETED",
        /*__n8n__*/ notes: "unlock:true is LOAD-BEARING — it releases the Redis doc_step lock. Without it every parked document snoozes for the lock's full 10-minute TTL before the next sweep can touch it.",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1344, -144],
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
                    id: 'unlock-ord0-4000-8000-00000000c0de',
                    name: 'unlock',
                    value: true,
                    type: 'boolean',
                },
                {
                    id: 'verb-ord0-4000-8000-00000000c0de',
                    name: 'INLINE_ACTION',
                    value: 'UPSERT',
                    type: 'string',
                },
                {
                    id: 'inst-ord0-4000-8000-00000000c0de',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'ord-upsert-central-01',
        name: 'Upsert (central)',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1568, 0],
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
        id: 'ord-stop-unhandled-01',
        name: 'Stop and Error - Unhandled ACTION',
        type: 'n8n-nodes-base.stopAndError',
        version: 1,
        position: [896, 224],
    })
    StopAndErrorUnhandledAction = {
        errorMessage:
            '=indoxV2ActionsOrd01: unhandled ACTION "{{ $json.ACTION }}" for ID {{ $json.ID }}. This lane handles mark_completed only — a new order action must be added here deliberately.',
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenCalled.out(0).to(this.RouteMode.in(0));
        this.RouteMode.out(0).to(this.DecideOrderAction.in(0));
        this.RouteMode.out(1).to(this.DedupeDocsExecute.in(0));
        this.DedupeDocsExecute.out(0).to(this.OrderActionSwitch.in(0));
        this.OrderActionSwitch.out(0).to(this.ActionMarkCompleted.in(0));
        this.OrderActionSwitch.out(1).to(this.StopAndErrorUnhandledAction.in(0));
        this.ActionMarkCompleted.out(0).to(this.LoopOverItems.in(0));
        this.LoopOverItems.out(1).to(this.BuildCallIncomingDocumentBatchUpdateStatusCompleted.in(0));
        this.LoopOverItems.out(1).to(this.LoopOverItems.in(0));
        this.BuildCallIncomingDocumentBatchUpdateStatusCompleted.out(0).to(this.UpsertCentral.in(0));
    }
}
