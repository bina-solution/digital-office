import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : sync api
// Nodes   : 11  |  Connections: 10
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// Webhook                            webhook
// WhenCalled                         executeWorkflowTrigger
// Normalize                          code
// Action                             switch
// ScanReq                            code
// CallMain                           executeWorkflow            [onError→regular] [alwaysOutput]
// ScanReply                          code
// ResetReq                           code
// CallLedger                         executeWorkflow            [onError→regular] [alwaysOutput]
// ResetReply                         code
// UnknownAction                      code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// Webhook
//    → Normalize
//      → Action
//        → ScanReq
//          → CallMain
//            → ScanReply
//       .out(1) → ResetReq
//          → CallLedger
//            → ResetReply
//       .out(2) → UnknownAction
// WhenCalled
//    → Normalize (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: "The INDOX control plane's ONE door into the sync engine (POST /webhook/indox-manage, called by the INDOX BFF and by bbox). Two verbs, both scoped by __instance: SCAN runs one sync pass now (syncV3Main0001, optionally one pipe) and reports ran | skipped (the reconcile mutex was held) | error; RESET re-drives sync items from OUR rows through the Sync Item API (statuses selectable — the board's 'retry failed' sends failed+needs_review). Every reply carries the execution that produced it. RELEASE and INJECT are gone with the item board and the source-mode injector.",
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Webhook":{"main":[[{"node":"Normalize","type":"main","index":0}]]},"When Called":{"main":[[{"node":"Normalize","type":"main","index":0}]]},"Normalize":{"main":[[{"node":"Action","type":"main","index":0}]]},"Action":{"main":[[{"node":"Scan Req","type":"main","index":0}],[{"node":"Reset Req","type":"main","index":0}],[{"node":"Unknown Action","type":"main","index":0}]]},"Scan Req":{"main":[[{"node":"Call Main","type":"main","index":0}]]},"Call Main":{"main":[[{"node":"Scan Reply","type":"main","index":0}]]},"Reset Req":{"main":[[{"node":"Call Ledger","type":"main","index":0}]]},"Call Ledger":{"main":[[{"node":"Reset Reply","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"51804d94-1071-4213-980b-a06491a07895","name":"role:api"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"c7d4bdbd-9cb8-4595-90d4-b200420c3fd2","name":"role:sync"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"SyncApi0000000001","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'SyncApi0000000001',
    name: 'sync api',
    active: true,
    isArchived: false,
    tags: ['app:indox', 'indox-app', 'role:api', 'role:sync'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class SyncApiWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'hook',
        webhookId: 'a1b2c3d4-e5f6-47a8-9b0c-1d2e3f4a5b6c',
        name: 'Webhook',
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [-620, 0],
    })
    Webhook = {
        httpMethod: 'POST',
        path: 'indox-manage',
        responseMode: 'lastNode',
        options: {},
    };

    @node({
        id: 'wc',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [-620, 180],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'normalize',
        name: 'Normalize',
        /*__n8n__*/ notes: "Webhook bodies arrive under $json.body, executeWorkflow calls arrive flat; both become one flat request. __instance is REQUIRED — every verb below is tenant-scoped and there is no public fallback.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-420, 90],
    })
    Normalize = {
        jsCode: `const j=$json||{};const p=(j.body&&typeof j.body==='object')?j.body:j;
const action=String(p.INLINE_ACTION||p.action||p.op||'').toUpperCase();
const inst=String(p.__instance||'').trim();
if(!/^[a-z][a-z0-9_]*$/.test(inst)) return [{json:{...p,INLINE_ACTION:'INVALID',_error:'no valid __instance — every sync verb is tenant-scoped (no public fallback)'}}];
return[{json:{...p,INLINE_ACTION:action,__instance:inst}}];`,
    };

    @node({
        id: 'action',
        name: 'Action',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [-200, 90],
    })
    Action = {
        rules: {
            values: [
                {
                    conditions: {
                        options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 },
                        conditions: [ { id: 'SCAN', leftValue: '={{ $json.INLINE_ACTION }}', rightValue: 'SCAN', operator: { type: 'string', operation: 'equals' } } ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'SCAN',
                },
                {
                    conditions: {
                        options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 },
                        conditions: [ { id: 'RESET', leftValue: '={{ $json.INLINE_ACTION }}', rightValue: 'RESET', operator: { type: 'string', operation: 'equals' } } ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'RESET',
                },
            ],
        },
        options: {
            fallbackOutput: 'extra',
            renameFallbackOutput: 'other',
        },
    };

    @node({
        id: 'scan-req',
        name: 'Scan Req',
        /*__n8n__*/ notes: "The pass request: __instance always; `sync` (one pipe) when the caller named one. The registry is NOT re-read here — Main reads it under its own lock and refuses on its own terms (indoxSyncOn=false, a disabled pipe, an unknown name all yield 0 units).",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [40, -40],
    })
    ScanReq = {
        jsCode: `const p=$json||{};
const only=String(p.sync||p.source||'').trim();
const req={__instance:p.__instance};
if(only) req.sync=only;
return [{json:req}];`,
    };

    @node({
        id: 'call-main',
        name: 'Call Main',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [260, -40],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    CallMain = {
        workflowId: {
            __rl: true,
            value: 'syncV3Main0001',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'scan-reply',
        name: 'Scan Reply',
        /*__n8n__*/ notes: "The run report the BFF branches on: status 'ran' (a pass was dispatched — deliveries continue asynchronously, so there is no claimed count to promise), 'skipped' (the reconcile mutex was held: NOT a failure and NOT a run — Main's Lock Acquired? true branch is the last node in that case), or 'error'. execution_id/workflow_id point at THIS execution; Main's own execution is one click further in.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [480, -40],
    })
    ScanReply = {
        jsCode: `const req=$('Scan Req').first().json||{};
const items=$input.all().map(i=>i&&i.json).filter(Boolean);
const top=items[0]||{};
const stamp={execution_id:String($execution.id), workflow_id:String($workflow.id), action:'SCAN', sync:req.sync||null};
// The reply contract (gate G48): 'status' is what a caller branches on; 'ok' is DERIVED from it
// ('ran' only), never a literal next to a skip marker.
let r;
if(top.error||top.errorMessage){
  const e=top.error; r={...stamp, status:'error', code:'reconciler_error', error:String((e&&(e.message||e.description))||top.errorMessage||e||'the sync pass failed')};
} else if(top.was_locked===true){
  r={...stamp, status:'skipped', skipped:true, code:'lock_held', error:'דילוג — ריצת סנכרון אחרת עדיין פעילה', detail:'the reconcile mutex is held by a running pass; the next tick retries'};
} else {
  r={...stamp, status:'ran', units:null, detail:'sync pass dispatched — discovery ran, deliveries continue in their own executions'};
}
r.ok=(r.status==='ran');
return [{json:r}];`,
    };

    @node({
        id: 'reset-req',
        name: 'Reset Req',
        /*__n8n__*/ notes: "RESET through the Sync Item API — never SQL here. `sync` = one pipe (else every pipe of the tenant); `statuses` = which rows to flip back to discovered (the board sends failed+needs_review; absent = every non-discovered row, the CLI's full re-drive); `purge` is refused on this door (test teardown only, by the hook).",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [40, 200],
    })
    ResetReq = {
        jsCode: `const p=$json||{};
const only=String(p.sync||p.source||'').trim();
const st=Array.isArray(p.statuses)?p.statuses.map(String):[];
// purge is allowed ONLY for one named pipe (the BFF's registry delete removes the pipe's rows
// with its config, owner 2026-09-03); a tenant-wide purge stays refused on this door.
const req={op:'RESET', __instance:p.__instance, purge:(p.purge===true && !!only)};
if(only) req.source=only; else req.source_like='%';
if(st.length) req.statuses=st;
return [{json:req}];`,
    };

    @node({
        id: 'call-ledger',
        name: 'Call Ledger',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [260, 200],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    CallLedger = {
        workflowId: {
            __rl: true,
            value: 'syncLedgerApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'reset-reply',
        name: 'Reset Reply',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [480, 200],
    })
    ResetReply = {
        jsCode: `const req=$('Reset Req').first().json||{};
const top=($input.all().map(i=>i&&i.json).filter(Boolean)[0])||{};
const stamp={execution_id:String($execution.id), workflow_id:String($workflow.id), action:'RESET', sync:req.source||null, statuses:req.statuses||null};
if(top.error||top.errorMessage){ const e=top.error; return [{json:{...stamp, ok:false, status:'error', error:String((e&&(e.message||e.description))||top.errorMessage||e||'reset failed')}}]; }
return [{json:{...stamp, ok:true, status:'ran', reset:Number(top.reset)||0, no_listing:Number(top.no_listing)||0, purged:Number(top.purged)||0, cursors_deleted:Number(top.cursors_deleted)||0}}];`,
    };

    @node({
        id: 'unknown-action',
        name: 'Unknown Action',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [40, 400],
    })
    UnknownAction = {
        jsCode: `const j=$json||{};
return [{json:{ok:false, status:'refused', code:j.INLINE_ACTION==='INVALID'?'no_instance':'unknown_action', action:j.INLINE_ACTION||null,
  error:j._error||('unknown action '+JSON.stringify(j.INLINE_ACTION||null)+' — this door knows SCAN and RESET'),
  execution_id:String($execution.id), workflow_id:String($workflow.id)}}];`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.Webhook.out(0).to(this.Normalize.in(0));
        this.WhenCalled.out(0).to(this.Normalize.in(0));
        this.Normalize.out(0).to(this.Action.in(0));
        this.Action.out(0).to(this.ScanReq.in(0));
        this.Action.out(1).to(this.ResetReq.in(0));
        this.Action.out(2).to(this.UnknownAction.in(0));
        this.ScanReq.out(0).to(this.CallMain.in(0));
        this.CallMain.out(0).to(this.ScanReply.in(0));
        this.ResetReq.out(0).to(this.CallLedger.in(0));
        this.CallLedger.out(0).to(this.ResetReply.in(0));
    }
}
