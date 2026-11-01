import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : INDOX Reset + Setup
// Nodes   : 18  |  Connections: 18
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenClickingExecute                manualTrigger
// WhenCalled                         executeWorkflowTrigger
// KillMainExecutions                 postgres                   [onError→regular] [creds]
// Norm1                              code
// ClearTable                         postgres                   [onError→regular] [creds]
// Norm2                              code
// CallDriveReset                     executeWorkflow            [onError→regular] [alwaysOutput]
// Norm3                              code
// CallGmailReset                     code
// Norm4                              code
// LockKeys                           redis                      [onError→regular] [creds]
// SplitLockKeys                      splitOut
// DeleteLock                         redis                      [onError→regular] [creds]
// ResetScope                         code
// DriveScope                         code
// GmailScope                         code
// NeedSetup                          if
// SeedFixtures                       executeWorkflow            [alwaysOutput]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenClickingExecute
//    → ResetScope
//      → NeedSetup
//        → SeedFixtures
//          → KillMainExecutions
//            → Norm1
//              → ClearTable
//                → Norm2
//                  → DriveScope
//                    → CallDriveReset
//                      → Norm3
//                        → GmailScope
//                          → CallGmailReset
//                            → Norm4
//                              → LockKeys
//                                → SplitLockKeys
//                                  → DeleteLock
//       .out(1) → KillMainExecutions (↩ loop)
// WhenCalled
//    → ResetScope (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When clicking Execute":{"main":[[{"node":"Reset Scope","type":"main","index":0}]]},"When Called":{"main":[[{"node":"Reset Scope","type":"main","index":0}]]},"Kill Main Executions":{"main":[[{"node":"Norm1","type":"main","index":0}]]},"Norm1":{"main":[[{"node":"Clear Table","type":"main","index":0}]]},"Clear Table":{"main":[[{"node":"Norm2","type":"main","index":0}]]},"Norm2":{"main":[[{"node":"Drive Scope","type":"main","index":0}]]},"Call Drive Reset":{"main":[[{"node":"Norm3","type":"main","index":0}]]},"Norm3":{"main":[[{"node":"Gmail Scope","type":"main","index":0}]]},"Call Gmail Reset":{"main":[[{"node":"Norm4","type":"main","index":0}]]},"Norm4":{"main":[[{"node":"Lock Keys","type":"main","index":0}]]},"Lock Keys":{"main":[[{"node":"Split Lock Keys","type":"main","index":0}]]},"Split Lock Keys":{"main":[[{"node":"Delete Lock","type":"main","index":0}]]},"Call Supabase Setup":{"main":[[{"node":"Config Seed","type":"main","index":0}]]},"Reset Scope":{"main":[[{"node":"Need Setup?","type":"main","index":0}]]},"Drive Scope":{"main":[[{"node":"Call Drive Reset","type":"main","index":0}]]},"Gmail Scope":{"main":[[{"node":"Call Gmail Reset","type":"main","index":0}]]},"Need Setup?":{"main":[[{"node":"Seed Fixtures","type":"main","index":0}],[{"node":"Kill Main Executions","type":"main","index":0}]]},"Seed Fixtures":{"main":[[{"node":"Kill Main Executions","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"de8accc1-f4e8-4a42-887e-4545f489893f","name":"role:infra"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-31T00:59:54.840Z","createdAt":"2026-07-31T00:59:54.840Z","role":"workflow:owner","workflowId":"IndoxResetFull01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'IndoxResetFull01',
    name: 'INDOX Reset + Setup',
    active: true,
    isArchived: false,
    tags: ['indox-app', 'role:infra', 'app:indox'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class IndoxResetSetupWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'c1000000-0000-0000-0000-000000000001',
        name: 'When clicking Execute',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [0, 0],
    })
    WhenClickingExecute = {};

    @node({
        id: 'c1000000-0000-0000-0000-000000000002',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1,
        position: [0, 200],
    })
    WhenCalled = {};

    @node({
        id: 'c1000000-0000-0000-0000-000000000003',
        name: 'Kill Main Executions',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [1420, 100],
        credentials: { postgres: { id: 'tJ195ajNq1kQveRG', name: 'N8N DB [env-managed]' } },
        onError: 'continueRegularOutput',
    })
    KillMainExecutions = {
        operation: 'executeQuery',
        query: "=update execution_entity set status='canceled', \"stoppedAt\"=now() where {{ $('Reset Scope').first().json.kill_execs === false ? 'false' : 'true' }} and status='running' and \"workflowId\" in (select id from workflow_entity where name like 'Incoming Documents%')",
        options: {},
    };

    @node({
        id: 'c1000000-0000-0000-0000-000000000004',
        name: 'Norm1',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1620, 100],
    })
    Norm1 = {
        jsCode: "return [{ json: { step: 'execs-killed', __instance: $('Reset Scope').first().json.__instance } }];",
    };

    @node({
        id: 'c1000000-0000-0000-0000-000000000005',
        name: 'Clear Table',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [1820, 100],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        onError: 'continueRegularOutput',
    })
    ClearTable = {
        operation: 'executeQuery',
        query: '=delete from {{ (() => { const i = String($json.__instance || ""); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error("IndoxResetFull01: no valid __instance — public fallback removed at the 2026-08-31 cutover"); } return "indox_" + i; })() }}.incoming_documents where "ID" <> \'__bootstrap__\'',
        options: {},
    };

    @node({
        id: 'c1000000-0000-0000-0000-000000000006',
        name: 'Norm2',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2020, 100],
    })
    Norm2 = {
        jsCode: "return [{ json: { step: 'table-cleared', __instance: $('Reset Scope').first().json.__instance } }];",
    };

    @node({
        id: 'c1000000-0000-0000-0000-000000000007',
        name: 'Call Drive Reset',
        /*__n8n__*/ notes: "[sync item 2026-09-02] The full reset is ONE call now: the Sync Item API's RESET with purge:true deletes every sync item and cursor of the tenant (scoped to `sync` when the reset names one pipe), so the next pass re-discovers what sits in each pipe's source scope and delivers it afresh. Nothing at the source is moved or relabelled — files and mails stay where the user put them (owner rule: marks are user-visible only). The two old reset workflows (INDOX Reset - Drive Sync tVzFMkz18pCsXRyw / Gmail Sync IndoxResetGml001) that walked Drive and Gmail to move things back are retired.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [2220, 100],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    CallDriveReset = {
        workflowId: {
            __rl: true,
            value: 'syncLedgerApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'RESET',
                source: "={{ (() => { const s = $('Reset Scope').first().json || {}; return String(s.sync || '').trim() || undefined; })() }}",
                source_like:
                    "={{ (() => { const s = $('Reset Scope').first().json || {}; return String(s.sync || '').trim() ? undefined : '%'; })() }}",
                purge: true,
                __instance: "={{ $('Reset Scope').first().json.__instance }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'op',
                    displayName: 'op',
                    required: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                },
                {
                    id: 'source',
                    displayName: 'source',
                    required: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                },
                {
                    id: 'source_like',
                    displayName: 'source_like',
                    required: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                },
                {
                    id: 'purge',
                    displayName: 'purge',
                    required: false,
                    display: true,
                    type: 'boolean',
                    canBeUsedToMatch: true,
                },
                {
                    id: '__instance',
                    displayName: '__instance',
                    required: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'c1000000-0000-0000-0000-000000000008',
        name: 'Norm3',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2420, 100],
    })
    Norm3 = {
        jsCode: "return [{ json: { step: 'drive-reset', __instance: $('Reset Scope').first().json.__instance } }];",
    };

    @node({
        id: 'c1000000-0000-0000-0000-000000000009',
        name: 'Call Gmail Reset',
        /*__n8n__*/ notes: "[sync item 2026-09-02] Folded into 'Call Drive Reset': one RESET purge covers every pipe of the tenant, drive and gmail alike. Kept as a pass-through so the reset's step chain (Norm3 -> Gmail Scope -> here -> Norm4 -> locks) reads the same in the execution log.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2620, 100],
    })
    CallGmailReset = {
        jsCode: "return [{ json: { step: 'gmail-reset', folded_into: 'Call Drive Reset (RESET purge, all pipes)', __instance: $('Reset Scope').first().json.__instance } }];",
    };

    @node({
        id: 'c1000000-0000-0000-0000-000000000010',
        name: 'Norm4',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2820, 100],
    })
    Norm4 = {
        jsCode: "return [{ json: { step: 'gmail-reset', __instance: $('Reset Scope').first().json.__instance } }];",
    };

    @node({
        id: 'c1000000-0000-0000-0000-000000000011',
        name: 'Lock Keys',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [3020, 100],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
        onError: 'continueRegularOutput',
    })
    LockKeys = {
        operation: 'keys',
        keyPattern:
            "={{ $('Reset Scope').first().json.kill_execs === false ? 'n8n.process_lock.__reset_skipped__' : 'n8n.process_lock.*' }}",
        getValues: false,
    };

    @node({
        id: 'c1000000-0000-0000-0000-000000000012',
        name: 'Split Lock Keys',
        type: 'n8n-nodes-base.splitOut',
        version: 1,
        position: [3220, 100],
    })
    SplitLockKeys = {
        fieldToSplitOut: 'keys',
        options: {},
    };

    @node({
        id: 'c1000000-0000-0000-0000-000000000013',
        name: 'Delete Lock',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [3420, 100],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
        onError: 'continueRegularOutput',
    })
    DeleteLock = {
        operation: 'delete',
        key: '={{ $json.keys }}',
    };

    @node({
        id: 'c1000000-0000-0000-0000-0000000000b1',
        name: 'Reset Scope',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [110, -160],
    })
    ResetScope = {
        jsCode: `const scope=(()=>{try{return $('When Called').first().json||{};}catch(e){return {};}})();

// [reset guard 2026-08-27] THIS WORKFLOW EMPTIES THE DOCUMENT TABLE.
//
// 'Clear Table' runs \`delete from incoming_documents where "ID" <> '__bootstrap__'\` — every
// document of the instance it is pointed at. It is ACTIVE, it has a manual trigger, and it is
// reachable by executeWorkflow from the test path. Nothing asked for confirmation.
//
// On 2026-08-26 three test workflows were run by hand from the editor and their fixture seeder
// re-asserted live configuration; that cost 213 documents a wrong ERP route. The same gesture
// aimed one workflow to the left would have emptied the table instead. The guard is here rather
// than on the delete node because this is the first node on BOTH entry paths, so a refusal costs
// nothing downstream.
//
// The token names the instance on purpose: a confirmation you can copy from another deployment's
// runbook and paste here is not a confirmation. Callers must state which instance they mean.
const REQUIRED = 'RESET-INSTANCE:' + String(scope.instance || '');
if (!scope.instance) {
  throw new Error('INDOX Reset refused: no \`instance\`. This deletes every document of an ' +
    'instance, so it must be told which one. Pass { instance, confirm: "RESET-INSTANCE:<id>" }.');
}
if (String(scope.confirm || '') !== REQUIRED) {
  throw new Error('INDOX Reset refused: confirm token missing or wrong. To empty instance "' +
    scope.instance + '", pass confirm: "' + REQUIRED + '". Nothing was deleted.');
}

// [tenancy cutover 2026-08-31] Every schema resolution downstream (Clear Table's delete, the
// seeder, both sub-resets) reads __instance and the public fallback is gone. Mint it HERE,
// validated, so the Norm chain re-emits a schema-safe value and both Call * Reset passthroughs
// deliver it — an entry refusal still costs nothing downstream.
if (!/^[a-z][a-z0-9_]*$/.test(String(scope.instance))) {
  throw new Error('IndoxResetFull01: no valid __instance — public fallback removed at the 2026-08-31 cutover');
}

return [{ json: { limit: scope.limit||null, ids: scope.ids||null, setup: scope.setup!==false,
                  kill_execs: scope.kill_execs!==false,
                  instance: scope.instance, __instance: String(scope.instance) } }];`,
    };

    @node({
        id: 'c1000000-0000-0000-0000-0000000000b2',
        name: 'Drive Scope',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2110, 160],
    })
    DriveScope = {
        jsCode: "return [ $('Reset Scope').first().json ];",
    };

    @node({
        id: 'c1000000-0000-0000-0000-0000000000b3',
        name: 'Gmail Scope',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2510, 160],
    })
    GmailScope = {
        jsCode: "return [ $('Reset Scope').first().json ];",
    };

    @node({
        id: 'c1000000-0000-0000-0000-0000000000c1',
        name: 'Need Setup?',
        type: 'n8n-nodes-base.if',
        version: 2,
        position: [330, -160],
    })
    NeedSetup = {
        conditions: {
            options: {
                caseSensitive: true,
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'setup1',
                    leftValue: '={{ $json.setup }}',
                    rightValue: true,
                    operator: {
                        type: 'boolean',
                        operation: 'true',
                        singleValue: true,
                    },
                },
            ],
            combinator: 'and',
        },
    };

    @node({
        id: '51ea57a8-0264-4565-8a57-3511da5746d3',
        name: 'Seed Fixtures',
        /*__n8n__*/ notes: "ONE seeding implementation everywhere: schema + storage bucket + settings/tag_rules/ai-cache fixtures (INDOX Seed Fixtures / indoxV2TestFixtures01) — same workflow the E2E suites call.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [220, -160],
        alwaysOutputData: true,
    })
    SeedFixtures = {
        workflowId: {
            __rl: true,
            value: 'indoxV2TestFixtures01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenClickingExecute.out(0).to(this.ResetScope.in(0));
        this.WhenCalled.out(0).to(this.ResetScope.in(0));
        this.KillMainExecutions.out(0).to(this.Norm1.in(0));
        this.Norm1.out(0).to(this.ClearTable.in(0));
        this.ClearTable.out(0).to(this.Norm2.in(0));
        this.Norm2.out(0).to(this.DriveScope.in(0));
        this.CallDriveReset.out(0).to(this.Norm3.in(0));
        this.Norm3.out(0).to(this.GmailScope.in(0));
        this.CallGmailReset.out(0).to(this.Norm4.in(0));
        this.Norm4.out(0).to(this.LockKeys.in(0));
        this.LockKeys.out(0).to(this.SplitLockKeys.in(0));
        this.SplitLockKeys.out(0).to(this.DeleteLock.in(0));
        this.ResetScope.out(0).to(this.NeedSetup.in(0));
        this.DriveScope.out(0).to(this.CallDriveReset.in(0));
        this.GmailScope.out(0).to(this.CallGmailReset.in(0));
        this.NeedSetup.out(0).to(this.SeedFixtures.in(0));
        this.NeedSetup.out(1).to(this.KillMainExecutions.in(0));
        this.SeedFixtures.out(0).to(this.KillMainExecutions.in(0));
    }
}
