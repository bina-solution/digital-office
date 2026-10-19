import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : [CI] Active-state webhook probe
// Nodes   : 2  |  Connections: 1
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// Webhook                            webhook                    [creds]
// Respond                            respondToWebhook
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// Webhook
//    → Respond
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: "Self-contained webhook CI pokes to prove >=1 workflow is REALLY active (trigger registered + responding). Secured with HTTP Basic auth via the env-managed 'CICD AUTH' credential (blueprint credential_overrides re-seeds it from $N8N_WEBHOOK_USER/PASS and re-encrypts under the current key, so it decrypts even under key drift). GET /webhook/ci-hello with the cicd basic-auth -> 'hello-from-n8n-ci'. See ai/context/archive/indox-pre-2026-09/workflow-state-sync.md.",
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Webhook":{"main":[[{"node":"Respond","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"9a0c3d07-81ee-4b76-a2ca-04112b1e1573","name":"ci/cd"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"dcb770a3-465f-4ed5-b5d4-ca1ff6dcd994","name":"lifecycle:test"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"536fb995-3c38-4ed4-9683-ae8d07edb41e","name":"n8n-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"de8accc1-f4e8-4a42-887e-4545f489893f","name":"role:infra"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"7e527add-9b38-577f-82e2-2d04f0c4d9db","name":"app:n8n"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:44:23.439Z","createdAt":"2026-07-30T23:44:23.439Z","role":"workflow:owner","workflowId":"ciHelloWebhook01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'ciHelloWebhook01',
    name: '[CI] Active-state webhook probe',
    active: true,
    description:
        "Self-contained webhook CI pokes to prove >=1 workflow is REALLY active (trigger registered + responding). Secured with HTTP Basic auth via the env-managed 'CICD AUTH' credential (blueprint credential_overrides re-seeds it from $N8N_WEBHOOK_USER/PASS and re-encrypts under the current key, so it decrypts even under key drift). GET /webhook/ci-hello with the cicd basic-auth -> 'hello-from-n8n-ci'. See ai/context/archive/indox-pre-2026-09/workflow-state-sync.md.",
    isArchived: false,
    tags: ['ci/cd', 'lifecycle:test', 'n8n-app', 'role:infra', 'app:n8n'],
    settings: { executionOrder: 'v1', callerPolicy: 'workflowsFromSameOwner', availableInMCP: false },
})
export class CiActiveStateWebhookProbeWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'ciwh1',
        webhookId: 'ci-hello',
        name: 'Webhook',
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [208, 304],
        credentials: { httpBasicAuth: { id: 'gBwYpBdw7cyJvg5v', name: 'CICD AUTH [env-managed]' } },
    })
    Webhook = {
        httpMethod: 'GET',
        path: 'ci-hello',
        authentication: 'basicAuth',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'ciresp1',
        name: 'Respond',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [448, 304],
    })
    Respond = {
        respondWith: 'text',
        responseBody: 'hello-from-n8n-ci',
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.Webhook.out(0).to(this.Respond.in(0));
    }
}
