import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : JQExV3 Run invoice
// Nodes   : 4  |  Connections: 3
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// Hook                               webhook
// Docs                               code
// CallV3                             executeWorkflow
// Respond                            respondToWebhook
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// Hook
//    → Docs
//      → CallV3
//        → Respond
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Hook":{"main":[[{"node":"Docs","type":"main","index":0}]]},"Docs":{"main":[[{"node":"Call V3","type":"main","index":0}]]},"Call V3":{"main":[[{"node":"Respond","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d0491649-2c07-43cd-9070-884fbcb8f086","name":"JsonQueryExV3"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"0b14850d-472a-4fdf-a00c-ef07a5623099","name":"json-query-ex-v3"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"JQExV3RunInv0001","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'JQExV3RunInv0001',
    name: 'JQExV3 Run invoice',
    active: true,
    isArchived: false,
    tags: ['JsonQueryExV3', 'app:indox', 'indox-app', 'json-query-ex-v3'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class Jqexv3RunInvoiceWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'dddd0000-0000-0000-0000-536780800001',
        webhookId: 'jqexv3-run-invoice',
        name: 'Hook',
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [0, 0],
    })
    Hook = {
        httpMethod: 'POST',
        path: 'jqexv3-run-invoice',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'dddd1111-0000-0000-0000-000000000002',
        name: 'Docs',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [220, 0],
    })
    Docs = {
        jsCode: 'const b=$json.body||{}; const docs=b.docs||[]; return docs.map(d=>({json:d}));',
    };

    @node({
        id: 'dddd2222-0000-0000-0000-000000000003',
        name: 'Call V3',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [440, 0],
    })
    CallV3 = {
        workflowId: {
            value: 'JQExV3Invoice001',
            mode: 'list',
            cachedResultName: 'Invoice JQ Ex V3',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                ID: '={{ $json.ID }}',
                API_TOOLS_ID: '={{ $json.API_TOOLS_ID }}',
                __instance: '={{ $json.__instance || "" }}',
            },
        },
    };

    @node({
        id: 'dddd3333-0000-0000-0000-000000000004',
        name: 'Respond',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [660, 0],
    })
    Respond = {
        respondWith: 'allIncomingItems',
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.Hook.out(0).to(this.Docs.in(0));
        this.Docs.out(0).to(this.CallV3.in(0));
        this.CallV3.out(0).to(this.Respond.in(0));
    }
}
