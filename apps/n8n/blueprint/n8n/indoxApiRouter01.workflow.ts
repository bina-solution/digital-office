import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox api router (RETIRED 2026-08-12 - folded into indoxApiSupabase01)
// Nodes   : 5  |  Connections: 5
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenCalled                         executeWorkflowTrigger
// Return_                            noOp
// IfManagement                       if
// CallSyncApi                        executeWorkflow
// CallSupabase                       executeWorkflow
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → IfManagement
//      → CallSyncApi
//        → Return_
//     .out(1) → CallSupabase
//        → Return_ (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"If Management","type":"main","index":0}]]},"If Management":{"main":[[{"node":"Call Sync Api","type":"main","index":0}],[{"node":"Call Supabase","type":"main","index":0}]]},"Call Sync Api":{"main":[[{"node":"Return","type":"main","index":0}]]},"Call Supabase":{"main":[[{"node":"Return","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-07-30T23:41:29.646Z","createdAt":"2026-07-30T23:41:29.646Z","id":"9c337cfe-7feb-4f3d-ab26-3de6439357ce","name":"sm-refactore-v2.1"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"51804d94-1071-4213-980b-a06491a07895","name":"role:api"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"22f1e71e-91bf-48db-811f-8d3bc4e55a3e","name":"sm-refactor-v2.1"},{"name":"app:n8n"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"indoxApiRouter01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxApiRouter01',
    name: 'indox api router (RETIRED 2026-08-12 - folded into indoxApiSupabase01)',
    active: false,
    isArchived: false,
    tags: ['sm-refactore-v2.1', 'indox-app', 'role:api', 'sm-refactor-v2.1'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class IndoxApiRouterRetired20260812FoldedIntoIndoxapisupabase01Workflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'trig',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, 300],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'done',
        name: 'Return',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [1140, 300],
    })
    Return_ = {};

    @node({
        id: 'if-mgmt',
        name: 'If Management',
        type: 'n8n-nodes-base.if',
        version: 2,
        position: [330, 300],
    })
    IfManagement = {
        conditions: {
            options: {
                caseSensitive: true,
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'm1',
                    leftValue: '={{ $json.INLINE_ACTION }}',
                    rightValue: 'RESET',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
                {
                    id: 'm2',
                    leftValue: '={{ $json.INLINE_ACTION }}',
                    rightValue: 'STATUS',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
                {
                    id: 'm3',
                    leftValue: '={{ $json.INLINE_ACTION }}',
                    rightValue: 'INJECT',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
                {
                    id: 'm4',
                    leftValue: '={{ $json.INLINE_ACTION }}',
                    rightValue: 'SCAN',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
            ],
            combinator: 'or',
        },
    };

    @node({
        id: 'call-sync-api',
        name: 'Call Sync Api',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [660, 140],
    })
    CallSyncApi = {
        workflowId: {
            __rl: true,
            value: 'SyncApi0000000001',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'csupa',
        name: 'Call Supabase',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [660, 460],
    })
    CallSupabase = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenCalled.out(0).to(this.IfManagement.in(0));
        this.IfManagement.out(0).to(this.CallSyncApi.in(0));
        this.IfManagement.out(1).to(this.CallSupabase.in(0));
        this.CallSyncApi.out(0).to(this.Return_.in(0));
        this.CallSupabase.out(0).to(this.Return_.in(0));
    }
}
