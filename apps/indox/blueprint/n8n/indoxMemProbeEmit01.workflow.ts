import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox mem probe — emitter
// Nodes   : 2  |  Connections: 1
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenExecutedByAnotherWorkflow      executeWorkflowTrigger
// Emit                               code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenExecutedByAnotherWorkflow
//    → Emit
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Executed by Another Workflow":{"main":[[{"node":"Emit","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-18T10:08:40.740Z","createdAt":"2026-08-18T10:08:40.740Z","role":"workflow:owner","workflowId":"indoxMemProbeEmit01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxMemProbeEmit01',
    name: 'indox mem probe — emitter',
    active: true,
    isArchived: false,
    tags: ['app:indox'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1', saveDataSuccessExecution: 'all' },
})
export class IndoxMemProbeEmitterWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'mpe-trigger-01',
        name: 'When Executed by Another Workflow',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, 0],
    })
    WhenExecutedByAnotherWorkflow = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'mpe-emit-01',
        name: 'Emit',
        /*__n8n__*/ notes: "Generates n items of width w. Field values are ~30 chars so w=110 lands near the real INDOX row (measured 1,983 B/row).",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [220, 0],
    })
    Emit = {
        jsCode: `const p = ($input.first() || {}).json || {};
const n = Number(p.n || 1000);
const w = Number(p.w || 1);
const pad = 'xxxxxxxxxxxxxxxxxxxxxxxxx';
const out = new Array(n);
for (let i = 0; i < n; i++) {
  const o = { ID: 'id-' + i };
  for (let k = 1; k < w; k++) o['F' + k] = 'v' + i + '_' + k + '_' + pad;
  out[i] = { json: o };
}
return out;
`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenExecutedByAnotherWorkflow.out(0).to(this.Emit.in(0));
    }
}
