import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox doc-context api
// Nodes   : 5  |  Connections: 4
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// Webhook                            webhook
// BuildGet                           code
// CallIndoxApi                       executeWorkflow            [onError→regular] [alwaysOutput]
// Shape                              code
// Respond                            respondToWebhook
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// Webhook
//    → BuildGet
//      → CallIndoxApi
//        → Shape
//          → Respond
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: "HTTP front for mailview's doc-context join: GET /webhook/mail-api/doc-context?source_id=<gmail id> -> indoxApiRouter01 GET (SOURCE_ID contains) -> {found, docs}. Keeps the architecture rule: apps never touch the DB, only the API layer does. Network-internal caller (mailview -> http://n8n:5678).",
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Webhook":{"main":[[{"node":"Build Get","type":"main","index":0}]]},"Build Get":{"main":[[{"node":"Call Indox Api","type":"main","index":0}]]},"Call Indox Api":{"main":[[{"node":"Shape","type":"main","index":0}]]},"Shape":{"main":[[{"node":"Respond","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"333960da-8376-4dd1-8b39-c3d4b448ca86","name":"mail-app"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"cf994cba-b6d0-53fa-8729-2b8d0c21b28f","name":"app:mail"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"51804d94-1071-4213-980b-a06491a07895","name":"role:api"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:43:25.358Z","createdAt":"2026-07-30T23:43:25.358Z","role":"workflow:owner","workflowId":"mailApi01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'mailApi01',
    name: 'indox doc-context api',
    active: true,
    description:
        "HTTP front for mailview's doc-context join: GET /webhook/mail-api/doc-context?source_id=<gmail id> -> indoxApiRouter01 GET (SOURCE_ID contains) -> {found, docs}. Keeps the architecture rule: apps never touch the DB, only the API layer does. Network-internal caller (mailview -> http://n8n:5678).",
    isArchived: false,
    tags: ['mail-app', 'app:mail', 'role:api'],
    settings: {
        errorWorkflow: 'errorHandler01',
        executionOrder: 'v1',
        callerPolicy: 'workflowsFromSameOwner',
        availableInMCP: false,
    },
})
export class IndoxDocContextApiWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'mawh1',
        webhookId: 'mail-api-doc-context',
        name: 'Webhook',
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [200, 300],
    })
    Webhook = {
        httpMethod: 'GET',
        path: 'mail-api/doc-context',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'mabld1',
        name: 'Build Get',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [420, 300],
    })
    BuildGet = {
        jsCode: `// join key = SOURCE_LINK, which ends with the message id (gmail hex / local uid).
// id required + min length — an open filter would GET the whole table.
const sid = String(($json.query || {}).source_id || '').trim();
const value = sid.length >= 6 ? '%' + sid : '__no_source_id__';
// __instance selects the SCHEMA. This workflow is ENTRY-ONLY (webhook), so unlike every other
// caller of indoxApi01 it has no upstream item to inherit an instance from -- the request itself
// has to name it. Accept it from the query string or the body and pass it through; when no caller
// supplies one this is byte-identical to the previous behaviour (falls back to public), so this
// change is forward-compatible and not a behaviour change today.
// THIS IS THE LAST LIVE UNSCOPED CALLER of indoxApi01 (72 executions/24h; the other remaining
// ones are dormant probes and fixtures with 0 in 24h). Removing indoxApi01's public fallback is
// gated on a caller contract for this webhook -- whoever calls it must start sending the instance.
const q = $json.query || {};
const b = $json.body || {};
const inst = String(q.__instance || q.instance || b.__instance || b.instance || '').trim();
return [{ json: { INLINE_ACTION: 'GET', filter: { SOURCE_LINK: { op: 'contains', value } }, __instance: inst } }];`,
    };

    @node({
        id: 'macall1',
        name: 'Call Indox Api',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [640, 300],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    CallIndoxApi = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'mashape1',
        name: 'Shape',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [860, 300],
    })
    Shape = {
        jsCode: `const rows = $input.all().map(i => i.json).filter(r => r && r.ID);
return [{ json: { found: rows.length, docs: rows } }];`,
    };

    @node({
        id: 'maresp1',
        name: 'Respond',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [1080, 300],
    })
    Respond = {
        respondWith: 'json',
        responseBody: '={{ { "found": $json.found, "docs": $json.docs } }}',
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.Webhook.out(0).to(this.BuildGet.in(0));
        this.BuildGet.out(0).to(this.CallIndoxApi.in(0));
        this.CallIndoxApi.out(0).to(this.Shape.in(0));
        this.Shape.out(0).to(this.Respond.in(0));
    }
}
