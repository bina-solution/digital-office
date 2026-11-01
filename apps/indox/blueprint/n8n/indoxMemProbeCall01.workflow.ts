import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox mem probe — caller
// Nodes   : 5  |  Connections: 4
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// ProbeWebhook                       webhook                    [creds]
// Shape                              set
// CallEmitter                        executeWorkflow
// Count                              code
// ProbeRespond                       respondToWebhook           [onError→regular]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// ProbeWebhook
//    → Shape
//      → CallEmitter
//        → Count
//          → ProbeRespond
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Probe Webhook":{"main":[[{"node":"Shape","type":"main","index":0}]]},"Shape":{"main":[[{"node":"Call Emitter","type":"main","index":0}]]},"Call Emitter":{"main":[[{"node":"Count","type":"main","index":0}]]},"Count":{"main":[[{"node":"Probe Respond","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-18T10:08:35.361Z","createdAt":"2026-08-18T10:08:35.361Z","role":"workflow:owner","workflowId":"indoxMemProbeCall01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxMemProbeCall01',
    name: 'indox mem probe — caller',
    active: true,
    isArchived: false,
    tags: ['app:indox'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1', saveDataSuccessExecution: 'none' },
})
export class IndoxMemProbeCallerWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'mpc-webhook-01',
        webhookId: 'b7c1e2d4-5a6f-4b8c-9d0e-1f2a3b4c5d6e',
        name: 'Probe Webhook',
        type: 'n8n-nodes-base.webhook',
        version: 2.1,
        position: [0, 0],
        credentials: { httpBasicAuth: { id: 'azPhHBvOWaf9IsEA', name: 'Incoming Documents [env-managed]' } },
    })
    ProbeWebhook = {
        httpMethod: 'POST',
        path: 'indox-mem-probe',
        authentication: 'basicAuth',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'mpc-shape-01',
        name: 'Shape',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [220, 0],
    })
    Shape = {
        mode: 'manual',
        includeOtherFields: false,
        assignments: {
            assignments: [
                {
                    id: 'sh0',
                    name: 'n',
                    value: '={{ $json.body && $json.body.n ? $json.body.n : 1000 }}',
                    type: 'number',
                },
                {
                    id: 'sh1',
                    name: 'w',
                    value: '={{ $json.body && $json.body.w ? $json.body.w : 1 }}',
                    type: 'number',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'mpc-call-01',
        name: 'Call Emitter',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [440, 0],
    })
    CallEmitter = {
        workflowId: {
            __rl: true,
            value: 'indoxMemProbeEmit01',
            mode: 'id',
            cachedResultName: 'indox mem probe — emitter',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'mpc-count-01',
        name: 'Count',
        /*__n8n__*/ notes: "Counts only — nothing large leaves this workflow, so a failure here is the RETURN cost and nothing else.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [660, 0],
    })
    Count = {
        jsCode: `const items = $input.all();
const first = (items[0] || {}).json || {};
return [{ json: { items: items.length, widthSeen: Object.keys(first).length } }];
`,
    };

    @node({
        id: 'mpc-respond-01',
        name: 'Probe Respond',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [880, 0],
        onError: 'continueRegularOutput',
    })
    ProbeRespond = {
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
        this.ProbeWebhook.out(0).to(this.Shape.in(0));
        this.Shape.out(0).to(this.CallEmitter.in(0));
        this.CallEmitter.out(0).to(this.Count.in(0));
        this.Count.out(0).to(this.ProbeRespond.in(0));
    }
}
