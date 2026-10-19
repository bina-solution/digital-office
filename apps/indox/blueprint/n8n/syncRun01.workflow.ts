import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Sync Run
// Nodes   : 8  |  Connections: 7
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenCalled                         executeWorkflowTrigger
// TakeReq                            code
// CallTake                           executeWorkflow            [alwaysOutput] [retry]
// BuildPayloads                      code
// RouteKind                          switch
// DeliverDriveEach                   executeWorkflow            [onError→regular]
// DeliverGmailEach                   executeWorkflow            [onError→regular]
// DeliverLinkEach                    executeWorkflow            [onError→regular]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → TakeReq
//      → CallTake
//        → BuildPayloads
//          → RouteKind
//            → DeliverDriveEach
//           .out(1) → DeliverGmailEach
//           .out(2) → DeliverLinkEach
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: "The SYNC stage for one pipe: TAKE min(take,chunk) pending sync items (status discovered/failed, not_before passed, attempts under budget) — claimed in the same race-safe statement — and fan them out to the per-source Deliver workflows without waiting (n8n's worker pool is the backpressure). No listing, no search, no platform read: everything a delivery needs rides on the row's `listing`. Discovery is a separate stage (syncDiscover*), which is what makes the queue inspectable before anything is processed.",
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"Take Req","type":"main","index":0}]]},"Take Req":{"main":[[{"node":"Call TAKE","type":"main","index":0}]]},"Call TAKE":{"main":[[{"node":"Build Payloads","type":"main","index":0}]]},"Build Payloads":{"main":[[{"node":"Route Kind","type":"main","index":0}]]},"Route Kind":{"main":[[{"node":"Deliver Drive Each","type":"main","index":0}],[{"node":"Deliver Gmail Each","type":"main","index":0}],[{"node":"Deliver Link Each","type":"main","index":0}],[]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"a659438c-0898-428d-aebd-72033caaefe4","name":"sync-v3"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"c7d4bdbd-9cb8-4595-90d4-b200420c3fd2","name":"role:sync"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: {},
    /*__n8n__*/ shared: [{"updatedAt":"2026-09-01T21:25:50.519Z","createdAt":"2026-09-01T21:25:50.519Z","role":"workflow:owner","workflowId":"syncRun01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'syncRun01',
    name: 'Sync Run',
    active: true,
    description:
        "The SYNC stage for one pipe: TAKE min(take,chunk) pending sync items (status discovered/failed, not_before passed, attempts under budget) — claimed in the same race-safe statement — and fan them out to the per-source Deliver workflows without waiting (n8n's worker pool is the backpressure). No listing, no search, no platform read: everything a delivery needs rides on the row's `listing`. Discovery is a separate stage (syncDiscover*), which is what makes the queue inspectable before anything is processed.",
    isArchived: false,
    tags: ['app:indox', 'indox', 'sync-v3', 'indox-app', 'role:sync'],
    settings: {
        errorWorkflow: 'errorHandler01',
        executionOrder: 'v1',
        executionTimeout: 300,
        callerPolicy: 'workflowsFromSameOwner',
        binaryMode: 'separate',
    },
})
export class SyncRunWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'srn-trig',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, 0],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'srn-take-req',
        name: 'Take Req',
        /*__n8n__*/ notes: "min(take, chunk) is the per-pass bound; raising take alone never raises throughput once take > chunk. __instance is carried explicitly because this node builds a new item.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [220, 0],
    })
    TakeReq = {
        jsCode: `const u=$input.first().json||{};
for(const k of ['source','src_kind']) if(!u[k]) throw new Error('syncRun01: unit missing '+k);
const bound=Math.max(1,Math.min(Number(u.take)||25, Number(u.chunk)||25));
// months = OldDocumentMonthsBack, from Main's one config read: TAKE expires (needs_review) any
// still-owed item whose own source time fell out of the window since it was discovered — the
// "zombie" of a narrowed window is retired explicitly instead of delivered years late.
const months=Number(u.months)>0?Number(u.months):null;
return [{json:{op:'TAKE', source:u.source, limit:bound, ...(months?{months}:{}), __instance:String(u.__instance||'')}}];`,
    };

    @node({
        id: 'srn-take',
        name: 'Call TAKE',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [440, 0],
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    CallTake = {
        workflowId: {
            __rl: true,
            value: 'syncLedgerApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'srn-payloads',
        name: 'Build Payloads',
        /*__n8n__*/ notes: "One Deliver payload per row TAKE returned. Rows are filtered on platform_id so the API's zero-row envelope is never mistaken for work. The unit's context (connection, list_ctx, budget, feedback) rides on every payload; __instance is stamped here because it is the last node every delivery passes — a delivery without it would create the document in the wrong tenant.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [660, 0],
    })
    BuildPayloads = {
        jsCode: `const u=$('When Called').first().json||{};
const rows=$input.all().map(i=>i&&i.json).filter(r=>r&&r.platform_id);
const inst=String(u.__instance||'');
try{ $execution.customData.set('outline', String(u.pipe||u.source||'run')+'_x'+rows.length+'_taken'); $execution.customData.set('exection_type','sync_run'); $execution.customData.set('pipe', String(u.pipe||u.source||'')); $execution.customData.set('taken', String(rows.length)); $execution.customData.set('instance', inst); }catch(e){}
if(!rows.length) return [{json:{_empty:true, src_kind:'none', source:u.source, pipe:u.pipe||null}}];
return rows.map(r=>({json:{source:u.source, platform_id:String(r.platform_id), listing:r.listing||{}, attempts:Number(r.attempts)||0,
  src_kind:u.src_kind, connection:u.connection||null, profile_id:(u.list_ctx||{}).profile_id||null, conn_kind:u.conn_kind||null,
  pipe:u.pipe||null, instance:u.instance||null, list_ctx:u.list_ctx||{}, feedback:u.feedback||null,
  status_override:u.status_override||null, max_attempts:Number(u.max_attempts)||5, base_backoff_s:Number(u.base_backoff_s)||60,
  __instance:inst}}));`,
    };

    @node({
        id: 'srn-route',
        name: 'Route Kind',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [880, 0],
    })
    RouteKind = {
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
                                id: 'rk-drive',
                                leftValue: '={{ $json.src_kind }}',
                                rightValue: 'drive',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'drive',
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
                                id: 'rk-gmail',
                                leftValue: '={{ $json.src_kind }}',
                                rightValue: 'gmail',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'gmail',
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
                                id: 'rk-link',
                                leftValue: '={{ $json.src_kind }}',
                                rightValue: 'gmail-link',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'link',
                },
            ],
        },
        options: {
            fallbackOutput: 'extra',
            renameFallbackOutput: 'none',
        },
    };

    @node({
        id: 'srn-deliver-drive',
        name: 'Deliver Drive Each',
        /*__n8n__*/ notes: "waitForSubWorkflow:false — every delivery is its own queued execution, paced by the worker pool. Each fired Deliver runs RECORD/FAIL itself from inside its own execution.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [1100, -160],
        onError: 'continueRegularOutput',
    })
    DeliverDriveEach = {
        workflowId: {
            __rl: true,
            value: 'syncDeliverDrive01',
            mode: 'id',
        },
        mode: 'each',
        options: {
            waitForSubWorkflow: false,
        },
    };

    @node({
        id: 'srn-deliver-gmail',
        name: 'Deliver Gmail Each',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [1100, 0],
        onError: 'continueRegularOutput',
    })
    DeliverGmailEach = {
        workflowId: {
            __rl: true,
            value: 'syncDeliverGmail01',
            mode: 'id',
        },
        mode: 'each',
        options: {
            waitForSubWorkflow: false,
        },
    };

    @node({
        id: 'srn-verify-delivery',
        name: 'Verify Delivery',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1980, 240],
    })
    VerifyDelivery = {
        jsCode: `// The three deliveries continue on error, so a unit that failed to be delivered left the pass
// looking clean. Read them by name and fail the pass: a delivery nobody notices is no delivery.
const calls = ['Deliver Drive Each','Deliver Gmail Each','Deliver Link Each'];
const failed = [];
for (const n of calls) {
  let items = [];
  try { items = $('' + n).all(); } catch (e) { continue; }
  for (const i of items) {
    const j = (i && i.json) || {};
    if (j.error || j.errorMessage) failed.push(n + ': ' + String(j.error || j.errorMessage).slice(0, 160));
  }
}
if (failed.length) throw new Error('delivery failed in ' + failed.length + ' call(s) — ' + failed.join(' | '));
return [{ json: { delivered: true, calls: calls.length } }];`,
    };

    @node({
        id: 'srn-deliver-link',
        name: 'Deliver Link Each',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [1100, 160],
        onError: 'continueRegularOutput',
    })
    DeliverLinkEach = {
        workflowId: {
            __rl: true,
            value: 'syncDeliverLink01',
            mode: 'id',
        },
        mode: 'each',
        options: {
            waitForSubWorkflow: false,
        },
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenCalled.out(0).to(this.TakeReq.in(0));
        this.TakeReq.out(0).to(this.CallTake.in(0));
        this.CallTake.out(0).to(this.BuildPayloads.in(0));
        this.BuildPayloads.out(0).to(this.RouteKind.in(0));
        this.RouteKind.out(0).to(this.DeliverDriveEach.in(0));
        this.RouteKind.out(1).to(this.DeliverGmailEach.in(0));
        this.RouteKind.out(2).to(this.DeliverLinkEach.in(0));
        this.DeliverDriveEach.out(0).to(this.VerifyDelivery.in(0));
        this.DeliverGmailEach.out(0).to(this.VerifyDelivery.in(0));
        this.DeliverLinkEach.out(0).to(this.VerifyDelivery.in(0));
    }
}
