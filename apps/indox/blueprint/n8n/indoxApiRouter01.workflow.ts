import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox api
// Nodes   : 10  |  Connections: 11
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenCalled                         executeWorkflowTrigger
// Prep                               code
// BackendSwitch                      switch
// StripSheets                        code
// StripSupabase                      code
// CallSheets                         executeWorkflow
// CallSupabase                       executeWorkflow
// Return_                            noOp
// IfManagement                       if
// CallSyncApi                        executeWorkflow
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → Prep
//      → IfManagement
//        → CallSyncApi
//          → Return_
//       .out(1) → BackendSwitch
//          → StripSheets
//            → CallSheets
//              → Return_ (↩ loop)
//         .out(1) → StripSupabase
//            → CallSupabase
//              → Return_ (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"Prep","type":"main","index":0}]]},"Prep":{"main":[[{"node":"If Management","type":"main","index":0}]]},"Backend Switch":{"main":[[{"node":"Strip (sheets)","type":"main","index":0}],[{"node":"Strip (supabase)","type":"main","index":0}]]},"Strip (sheets)":{"main":[[{"node":"Call Sheets","type":"main","index":0}]]},"Strip (supabase)":{"main":[[{"node":"Call Supabase","type":"main","index":0}]]},"Call Sheets":{"main":[[{"node":"Return","type":"main","index":0}]]},"Call Supabase":{"main":[[{"node":"Return","type":"main","index":0}]]},"If Management":{"main":[[{"node":"Call Sync Api","type":"main","index":0}],[{"node":"Backend Switch","type":"main","index":0}]]},"Call Sync Api":{"main":[[{"node":"Return","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-07-30T19:10:18.750Z","createdAt":"2026-07-30T19:10:18.750Z","id":"457918fe-6fd4-4fa4-9605-0c3702ee3244","name":"sm-refactore-v2.1"},{"updatedAt":"2026-10-13T13:42:16.546Z","createdAt":"2026-10-13T13:42:16.546Z","id":"18314833-f647-4d49-8030-629180cbfcc2","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T19:10:23.678Z","createdAt":"2026-07-30T19:10:23.678Z","role":"workflow:owner","workflowId":"indoxApiRouter01","projectId":"IwcBrWygrgE0xpis","project":{"updatedAt":"2026-07-30T19:10:08.961Z","createdAt":"2026-07-30T19:02:55.442Z","id":"IwcBrWygrgE0xpis","name":"Admin User <person2@example.com>","type":"personal","icon":null,"description":null,"creatorId":"c678e57f-b06c-4c25-a005-05e85cb56164"}}],
    id: 'indoxApiRouter01',
    name: 'indox api',
    active: true,
    isArchived: false,
    tags: ['sm-refactore-v2.1', 'app:indox'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class IndoxApiWorkflow {
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
        id: 'prep',
        name: 'Prep',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [330, 300],
    })
    Prep = {
        mode: 'runOnceForEachItem',
        jsCode: `// ── DATA BACKEND ─────────────────────────────────────────────────────
// Resolved at import time by n8n-push: .env INDOX_DATA_BACKEND, else the
// settings row backend_data, else this default. No runtime toggle — a
// backend flip is a deploy action (edit .env or settings, then push).
const BACKEND='supabase';   // 'supabase' | 'sheets'
return { json: { ...$json, _be: BACKEND } };`,
    };

    @node({
        id: 'bsw',
        name: 'Backend Switch',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [440, 300],
    })
    BackendSwitch = {
        rules: {
            values: [
                {
                    outputKey: 'sheets',
                    conditions: {
                        options: {
                            caseSensitive: true,
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: "={{ $json._be || 'supabase' }}",
                                rightValue: 'sheets',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                },
            ],
        },
        options: {
            fallbackOutput: 'extra',
        },
    };

    @node({
        id: 'stripS',
        name: 'Strip (sheets)',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [660, 180],
    })
    StripSheets = {
        mode: 'runOnceForAllItems',
        jsCode: 'return $input.all().map(i=>{const j={...i.json};delete j._be;return {json:j};});',
    };

    @node({
        id: 'stripP',
        name: 'Strip (supabase)',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [660, 420],
    })
    StripSupabase = {
        mode: 'runOnceForAllItems',
        jsCode: 'return $input.all().map(i=>{const j={...i.json};delete j._be;return {json:j};});',
    };

    @node({
        id: 'csheets',
        name: 'Call Sheets',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [900, 180],
        /*__n8n__*/ notes: "[rel-1/DGO-47 2026-10-14] the sheets backend is retired: indoxApiSheets01 moved to legacy/n8n/indox-sheets-era and no blueprint declares that id any more. `Prep` resolves BACKEND='supabase', so the switch reaches this node only if a deploy sets _be='sheets'. DISABLED, not deleted — re-enabling is the revert path if a sheets backend ever ships again (same shape as the archived Snooze call in indoxV2Driver01).",
        /*__n8n__*/ disabled: true,
    })
    CallSheets = {
        workflowId: {
            __rl: true,
            value: 'indoxApiSheets01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'csupa',
        name: 'Call Supabase',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [900, 420],
    })
    CallSupabase = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {},
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
        position: [-100, -160],
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
        position: [120, -160],
    })
    CallSyncApi = {
        workflowId: {
            __rl: true,
            value: 'SyncApi0000000001',
            mode: 'id',
        },
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenCalled.out(0).to(this.Prep.in(0));
        this.Prep.out(0).to(this.IfManagement.in(0));
        this.BackendSwitch.out(0).to(this.StripSheets.in(0));
        this.BackendSwitch.out(1).to(this.StripSupabase.in(0));
        this.StripSheets.out(0).to(this.CallSheets.in(0));
        this.StripSupabase.out(0).to(this.CallSupabase.in(0));
        this.CallSheets.out(0).to(this.Return_.in(0));
        this.CallSupabase.out(0).to(this.Return_.in(0));
        this.IfManagement.out(0).to(this.CallSyncApi.in(0));
        this.IfManagement.out(1).to(this.BackendSwitch.in(0));
        this.CallSyncApi.out(0).to(this.Return_.in(0));
    }
}
