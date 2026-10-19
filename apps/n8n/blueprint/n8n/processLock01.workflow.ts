import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : process_lock
// Nodes   : 46  |  Connections: 51
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// Switch_                            switch
// StickyNote                         stickyNote
// SetProcessKey                      redis                      [creds]
// ScanProcess                        redis                      [creds]
// ScanProcessKey                     redis                      [creds]
// GetProcessKeyExecution             redis                      [creds]
// WhenExecutedByAnotherWorkflow      executeWorkflowTrigger
// IfKey                              if
// IfExecution                        if
// TestGetKey                         set
// TestGetKeyExecution                set
// TestGetAllProcessKeys              set
// TestLock                           set
// TestLock1                          set
// UnklockProcessKeyExtraction        redis                      [creds]
// ScanDocScopedLocks                 redis                      [creds]
// TestUnlockKeyExecution             set
// TestUnlockExecution                set
// If_                                if
// ScanProcessKey1                    redis                      [creds]
// Details                            set
// SplitOut                           splitOut
// DeleteResults                      redis                      [creds]
// Code                               code
// Start                              noOp
// Starttests                         noOp
// TestCechkLock                      set
// ReplaceMe                          noOp
// DeleteResults1                     redis                      [creds]
// EditFields1                        set
// SetProcessKey1                     redis                      [creds]
// GetProcessKeyExecution1            redis                      [creds]
// EditFields                         set
// IfLocked                           if
// LoopOverItems                      splitInBatches
// GetCheckProcessKeyExecution2       redis                      [creds]
// RenewNote                          stickyNote
// RenewCheckExists                   redis                      [creds]
// RenewExists                        if
// RenewProcessKey                    redis                      [creds]
// RenewResult                        code
// RenewLost                          code
// UnknownAction                      code
// FirstAcquire                       if
// StampLockTtlWinnerOnly             redis                      [creds]
// MergeLockResult                    merge
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenExecutedByAnotherWorkflow
//    → Start
//      → Switch_
//        → IfKey
//          → IfExecution
//            → GetProcessKeyExecution
//           .out(1) → ScanProcessKey
//         .out(1) → ScanProcess
//            → Code
//       .out(1) → SetProcessKey
//       .out(2) → If_
//          → UnklockProcessKeyExtraction
//          → ScanDocScopedLocks
//            → SplitOut
//              → DeleteResults
//         .out(1) → ScanProcessKey1
//            → SplitOut (↩ loop)
//       .out(3) → GetCheckProcessKeyExecution2
//          → FirstAcquire
//            → StampLockTtlWinnerOnly
//              → MergeLockResult
//                → EditFields1
//           .out(1) → MergeLockResult.in(1) (↩ loop)
//       .out(4) → RenewCheckExists
//          → RenewExists
//            → RenewProcessKey
//              → RenewResult
//           .out(1) → RenewLost
//       .out(5) → UnknownAction
//      → Details
// Starttests
//    → TestGetKeyExecution
//      → Start (↩ loop)
//    → TestGetKey
//      → Start (↩ loop)
//    → TestGetAllProcessKeys
//      → Start (↩ loop)
//    → TestLock
//      → Start (↩ loop)
//    → TestLock1
//      → Start (↩ loop)
//    → TestUnlockKeyExecution
//      → Start (↩ loop)
//    → TestUnlockExecution
//      → Start (↩ loop)
//    → TestCechkLock
//      → Start (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Switch":{"main":[[{"node":"If KEY","type":"main","index":0}],[{"node":"SET PROCESS KEY","type":"main","index":0}],[{"node":"If","type":"main","index":0}],[{"node":"GET CHECK PROCESS KEY EXECUTION2","type":"main","index":0}],[{"node":"RENEW CHECK EXISTS","type":"main","index":0}],[{"node":"Unknown Action","type":"main","index":0}]]},"When Executed by Another Workflow":{"main":[[{"node":"Start","type":"main","index":0}]]},"If KEY":{"main":[[{"node":"If EXECUTION","type":"main","index":0}],[{"node":"SCAN PROCESS *","type":"main","index":0}]]},"If EXECUTION":{"main":[[{"node":"GET PROCESS KEY EXECUTION","type":"main","index":0}],[{"node":"SCAN PROCESS KEY","type":"main","index":0}]]},"Test GET KEY EXECUTION":{"main":[[{"node":"Start","type":"main","index":0}]]},"Test GET KEY":{"main":[[{"node":"Start","type":"main","index":0}]]},"Test GET ALL PROCESS KEYS":{"main":[[{"node":"Start","type":"main","index":0}]]},"Test LOCK":{"main":[[{"node":"Start","type":"main","index":0}]]},"Test LOCK1":{"main":[[{"node":"Start","type":"main","index":0}]]},"Test UNLOCK KEY EXECUTION":{"main":[[{"node":"Start","type":"main","index":0}]]},"Test UNLOCK EXECUTION":{"main":[[{"node":"Start","type":"main","index":0}]]},"If":{"main":[[{"node":"UNKLOCK PROCESS KEY EXTRACTION","type":"main","index":0},{"node":"Scan Doc-Scoped Locks","type":"main","index":0}],[{"node":"SCAN PROCESS KEY1","type":"main","index":0}]]},"SCAN PROCESS KEY1":{"main":[[{"node":"Split Out","type":"main","index":0}]]},"Scan Doc-Scoped Locks":{"main":[[{"node":"Split Out","type":"main","index":0}]]},"Split Out":{"main":[[{"node":"DELETE RESULTS","type":"main","index":0}]]},"SET PROCESS KEY":{"main":[[]]},"SCAN PROCESS *":{"main":[[{"node":"Code","type":"main","index":0}]]},"Start":{"main":[[{"node":"Switch","type":"main","index":0},{"node":"Details","type":"main","index":0}]]},"StartTests":{"main":[[{"node":"Test GET KEY EXECUTION","type":"main","index":0},{"node":"Test GET KEY","type":"main","index":0},{"node":"Test GET ALL PROCESS KEYS","type":"main","index":0},{"node":"Test LOCK","type":"main","index":0},{"node":"Test LOCK1","type":"main","index":0},{"node":"Test UNLOCK KEY EXECUTION","type":"main","index":0},{"node":"Test UNLOCK EXECUTION","type":"main","index":0},{"node":"Test CECHK & LOCK","type":"main","index":0}]]},"Details":{"main":[[]]},"Test CECHK & LOCK":{"main":[[{"node":"Start","type":"main","index":0}]]},"Replace Me":{"main":[[]]},"SET PROCESS KEY1":{"main":[[{"node":"Edit Fields","type":"main","index":0}]]},"GET PROCESS KEY EXECUTION1":{"main":[[{"node":"If LOCKED","type":"main","index":0}]]},"Edit Fields":{"main":[[]]},"If LOCKED":{"main":[[{"node":"Edit Fields","type":"main","index":0}],[{"node":"SET PROCESS KEY1","type":"main","index":0}]]},"Loop Over Items":{"main":[[],[{"node":"GET PROCESS KEY EXECUTION1","type":"main","index":0},{"node":"Loop Over Items","type":"main","index":0}]]},"GET CHECK PROCESS KEY EXECUTION2":{"main":[[{"node":"First Acquire?","type":"main","index":0}]]},"RENEW CHECK EXISTS":{"main":[[{"node":"Renew Exists?","type":"main","index":0}]]},"Renew Exists?":{"main":[[{"node":"RENEW PROCESS KEY","type":"main","index":0}],[{"node":"Renew Lost","type":"main","index":0}]]},"RENEW PROCESS KEY":{"main":[[{"node":"Renew Result","type":"main","index":0}]]},"First Acquire?":{"main":[[{"node":"STAMP LOCK TTL (winner only)","type":"main","index":0}],[{"node":"Merge Lock Result","type":"main","index":1}]]},"STAMP LOCK TTL (winner only)":{"main":[[{"node":"Merge Lock Result","type":"main","index":0}]]},"Merge Lock Result":{"main":[[{"node":"Edit Fields1","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-07-30T23:44:12.933Z","createdAt":"2026-07-30T23:44:12.933Z","id":"12d9b7a3-e589-4bf5-aaa1-26a013cd0175","name":"shared"},{"updatedAt":"2026-07-30T23:41:29.646Z","createdAt":"2026-07-30T23:41:29.646Z","id":"9c337cfe-7feb-4f3d-ab26-3de6439357ce","name":"sm-refactore-v2.1"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"7e527add-9b38-577f-82e2-2d04f0c4d9db","name":"app:n8n"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"536fb995-3c38-4ed4-9683-ae8d07edb41e","name":"n8n-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"de8accc1-f4e8-4a42-887e-4545f489893f","name":"role:infra"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"22f1e71e-91bf-48db-811f-8d3bc4e55a3e","name":"sm-refactor-v2.1"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {"templateCredsSetupCompleted":true},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-31T01:00:42.729Z","createdAt":"2026-07-31T01:00:42.729Z","role":"workflow:owner","workflowId":"processLock01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'processLock01',
    name: 'process_lock',
    active: true,
    isArchived: false,
    tags: ['shared', 'sm-refactore-v2.1', 'app:n8n', 'n8n-app', 'role:infra', 'sm-refactor-v2.1'],
    settings: {
        executionOrder: 'v1',
        timeSavedMode: 'fixed',
        saveDataSuccessExecution: 'all',
        callerPolicy: 'workflowsFromSameOwner',
        availableInMCP: false,
        errorWorkflow: 'errorHandler01',
        saveManualExecutions: true,
    },
})
export class ProcessLockWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: '6b1ff63a-88ad-43b8-a276-de3a1531207c',
        name: 'Switch',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [176, -144],
    })
    Switch_ = {
        rules: {
            values: [
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.ACTION }}',
                                rightValue: 'check',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                                id: '091a3383-1c12-4059-85f3-7f9e2d5366fa',
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'check',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: '50fa3587-9080-486f-a888-6b2650c5e3b5',
                                leftValue: '={{ $json.ACTION }}',
                                rightValue: 'lock',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                    name: 'filter.operator.equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'lock',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: '6fc187c7-e59c-4f53-b7c8-891749e219ed',
                                leftValue: '={{ $json.ACTION }}',
                                rightValue: 'unlock',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                    name: 'filter.operator.equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'unlock',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: '8c38f910-1d4d-4b93-bb44-c129314d641d',
                                leftValue: '={{ $json.ACTION }}',
                                rightValue: 'check_and_lock',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                    name: 'filter.operator.equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'renew-action',
                                leftValue: '={{ $json.ACTION }}',
                                rightValue: 'renew',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                    name: 'filter.operator.equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'renew',
                },
            ],
        },
        options: {
            fallbackOutput: 'extra',
        },
    };

    @node({
        id: '4900e47f-74b1-47f7-94ed-2a1d7c8ebe12',
        name: 'Sticky Note',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [-1040, 80],
    })
    StickyNote = {
        content: `## ProcessLock workflow for locking asynchronos tasks that need to happen sequentionly 

action?
lock: (process=docStep, key=<doc_id>) 
check: (process, key, exec)
unlock: (process, key)

usage: get all (process=docStep, keys:(list of incoming steps), split locked,
true: sleap and go stepback 
false: lock & pass on 

end of step: unlock(p, k)
on execution fail: unlock_all(exec=<execution_id>)
 
`,
        height: 240,
        width: 400,
        color: 1,
    };

    @node({
        id: 'cea43f7e-da44-426d-860e-849cb5ef9834',
        name: 'SET PROCESS KEY',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [1104, -128],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    SetProcessKey = {
        operation: 'set',
        key: '=n8n.{{ $("Details").first().json.name }}.{{ $json.PROCESS }}.{{ $json.KEY }}.{{ $json.EXECUTION }}',
        value: '=true',
        keyType: 'string',
        expire: true,
        ttl: '={{ 600 }}',
    };

    @node({
        id: '805f99b4-ecb5-4f40-b1f8-82509a56f65c',
        name: 'SCAN PROCESS *',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [896, -288],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    ScanProcess = {
        operation: 'keys',
        keyPattern: '=n8n.{{ $("Details").first().json.name }}.{{ $json.PROCESS }}.*',
        getValues: false,
    };

    @node({
        id: 'ccd81cbb-ca21-4504-a5db-27771719f0b1',
        name: 'SCAN PROCESS KEY',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [1168, -464],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    ScanProcessKey = {
        operation: 'keys',
        keyPattern: '=n8n.{{ $("Details").first().json.name }}.{{ $json.PROCESS }}.{{ $json.KEY }}.*',
    };

    @node({
        id: 'e94de446-5093-4c78-91a3-fd258251b93a',
        name: 'GET PROCESS KEY EXECUTION',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [1168, -640],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    GetProcessKeyExecution = {
        operation: 'get',
        propertyName: 'value',
        key: '=n8n.{{ $("Details").first().json.name }}.{{ $json.PROCESS }}.{{ $json.KEY }}.{{ $json.EXECUTION }}',
        options: {},
    };

    @node({
        id: '2e4025a5-9122-4b01-9e62-4c3696e4733e',
        name: 'When Executed by Another Workflow',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [-1376, -128],
    })
    WhenExecutedByAnotherWorkflow = {
        workflowInputs: {
            values: [
                {
                    name: 'PROCESS',
                },
                {
                    name: 'KEY',
                },
                {
                    name: 'ACTION',
                },
                {
                    name: 'EXECUTION',
                },
            ],
        },
    };

    @node({
        id: 'a0103a4d-3b48-4ec5-9b9d-877c6f57b4f0',
        name: 'If KEY',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [656, -304],
    })
    IfKey = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: '5943ad91-a6eb-471a-9a8e-4164721132b7',
                    leftValue: '={{ $json.KEY }}',
                    rightValue: '',
                    operator: {
                        type: 'string',
                        operation: 'notEmpty',
                        singleValue: true,
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: 'f556d684-8603-48ba-b3fb-6428d9e3c3c5',
        name: 'If EXECUTION',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [896, -480],
    })
    IfExecution = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: '66cfcfe6-2f26-4b21-87ff-baf689c6955f',
                    leftValue: '={{ String($json.EXECUTION || "") }}',
                    rightValue: '',
                    operator: {
                        type: 'string',
                        operation: 'notEmpty',
                        singleValue: true,
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: 'd01f828d-9cab-42a6-a703-b47a24c6dd0d',
        name: 'Test GET KEY',
        /*__n8n__*/ disabled: true,
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [-416, -1616],
    })
    TestGetKey = {
        assignments: {
            assignments: [
                {
                    id: '7615b10e-9c14-485b-aa81-5182c8a31c74',
                    name: 'ACTION',
                    value: '=check',
                    type: 'string',
                },
                {
                    id: '5adbdced-5084-4af9-93a3-5d96b39966d9',
                    name: 'PROCESS',
                    value: '=doc_step',
                    type: 'string',
                },
                {
                    id: '4fd3f0ef-c828-4b66-858c-8281268ca78f',
                    name: 'KEY',
                    value: '=doc_id',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'e4764354-42fc-4086-a783-c9f545b69293',
        name: 'Test GET KEY EXECUTION',
        /*__n8n__*/ disabled: true,
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [-416, -1808],
    })
    TestGetKeyExecution = {
        assignments: {
            assignments: [
                {
                    id: '7615b10e-9c14-485b-aa81-5182c8a31c74',
                    name: 'ACTION',
                    value: '=check',
                    type: 'string',
                },
                {
                    id: '5adbdced-5084-4af9-93a3-5d96b39966d9',
                    name: 'PROCESS',
                    value: '=doc_step',
                    type: 'string',
                },
                {
                    id: '4fd3f0ef-c828-4b66-858c-8281268ca78f',
                    name: 'KEY',
                    value: '=doc_id',
                    type: 'string',
                },
                {
                    id: '7432dad4-8d24-4aa2-a3ac-269b250d72ad',
                    name: 'EXECUTION',
                    value: '=34453',
                    type: 'number',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'ae05682b-0322-41a1-b654-b97a57c005c1',
        name: 'Test GET ALL PROCESS KEYS',
        /*__n8n__*/ disabled: true,
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [-416, -1424],
    })
    TestGetAllProcessKeys = {
        assignments: {
            assignments: [
                {
                    id: '7615b10e-9c14-485b-aa81-5182c8a31c74',
                    name: 'ACTION',
                    value: '=check',
                    type: 'string',
                },
                {
                    id: '5adbdced-5084-4af9-93a3-5d96b39966d9',
                    name: 'PROCESS',
                    value: '=doc_step',
                    type: 'string',
                },
                {
                    id: '7432dad4-8d24-4aa2-a3ac-269b250d72ad',
                    name: 'EXECUTION',
                    value: '=34453',
                    type: 'number',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '2623d1b0-65d7-462a-9a8a-3eb504bda9aa',
        name: 'Test LOCK',
        /*__n8n__*/ disabled: true,
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [-416, -1168],
    })
    TestLock = {
        assignments: {
            assignments: [
                {
                    id: '7615b10e-9c14-485b-aa81-5182c8a31c74',
                    name: 'ACTION',
                    value: '=lock',
                    type: 'string',
                },
                {
                    id: '5adbdced-5084-4af9-93a3-5d96b39966d9',
                    name: 'PROCESS',
                    value: '=doc_step',
                    type: 'string',
                },
                {
                    id: '24c3714f-fcfe-4782-a68e-528580634d65',
                    name: 'KEY',
                    value: '=doc_id',
                    type: 'string',
                },
                {
                    id: '7432dad4-8d24-4aa2-a3ac-269b250d72ad',
                    name: 'EXECUTION',
                    value: '=34453',
                    type: 'number',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'c995d327-acea-4eed-b6a1-979f1f3d29b0',
        name: 'Test LOCK1',
        /*__n8n__*/ disabled: true,
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [-416, -960],
    })
    TestLock1 = {
        assignments: {
            assignments: [
                {
                    id: '7615b10e-9c14-485b-aa81-5182c8a31c74',
                    name: 'ACTION',
                    value: '=lock',
                    type: 'string',
                },
                {
                    id: '5adbdced-5084-4af9-93a3-5d96b39966d9',
                    name: 'PROCESS',
                    value: '=doc_step',
                    type: 'string',
                },
                {
                    id: '24c3714f-fcfe-4782-a68e-528580634d65',
                    name: 'KEY',
                    value: '=doc_id1',
                    type: 'string',
                },
                {
                    id: '7432dad4-8d24-4aa2-a3ac-269b250d72ad',
                    name: 'EXECUTION',
                    value: '=34453',
                    type: 'number',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'cf318bf5-fcc2-4e39-bfeb-ad0937d31d48',
        name: 'UNKLOCK PROCESS KEY EXTRACTION',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [896, 80],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    UnklockProcessKeyExtraction = {
        operation: 'delete',
        key: '=n8n.{{ $("Details").first().json.name }}.{{ $json.PROCESS }}.{{ $json.KEY }}',
    };

    @node({
        id: 'scan-doc-scoped-unlock-0001c0de',
        name: 'Scan Doc-Scoped Locks',
        /*__n8n__*/ notes: "[doc-scoped unlock 2026-08-16, owner order] A BARE key (no '::') on unlock also releases every '<KEY>::*' lock — this is what lets the upsert (indoxApi01 'API Unlock Doc', which only knows the doc ID) release the doc_action lock '<ID>::<ACTION>' without carrying the action name through every builder. The upsert unlock had been a silent NO-OP since lock keys became compound (it deleted 'n8n.process_lock.doc_action.<ID>', which never exists) — the router's late Unlock Doc Action compensated, and ITS timing could wrongly release a lock another driver had just taken for the doc's NEXT action (a dup mechanism; removed same day). Safe because at upsert time the doc's ONLY doc_action lock is the completing action's own. A COMPOUND key ('::' present) makes this pattern match nothing, so exact unlocks behave exactly as before. Feeds the existing Split Out -> DELETE RESULTS chain.",
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [896, 208],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    ScanDocScopedLocks = {
        operation: 'keys',
        keyPattern:
            "=n8n.{{ $(\"Details\").first().json.name }}.{{ $json.PROCESS }}.{{ String($json.KEY).includes('::') ? '__no_scoped_match__' : String($json.KEY) + '::*' }}",
        getValues: false,
    };

    @node({
        id: '86e9868e-9325-4a7a-a605-7dcf821cb27f',
        name: 'Test UNLOCK KEY EXECUTION',
        /*__n8n__*/ disabled: true,
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [-416, -768],
    })
    TestUnlockKeyExecution = {
        assignments: {
            assignments: [
                {
                    id: '7615b10e-9c14-485b-aa81-5182c8a31c74',
                    name: 'ACTION',
                    value: '=unlock',
                    type: 'string',
                },
                {
                    id: '5adbdced-5084-4af9-93a3-5d96b39966d9',
                    name: 'PROCESS',
                    value: '=doc_step',
                    type: 'string',
                },
                {
                    id: '24c3714f-fcfe-4782-a68e-528580634d65',
                    name: 'KEY',
                    value: '=doc_id1',
                    type: 'string',
                },
                {
                    id: '7432dad4-8d24-4aa2-a3ac-269b250d72ad',
                    name: 'EXECUTION',
                    value: '=34453',
                    type: 'number',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '4d53eaf7-6d8d-4c91-ab0e-8927aab78e0e',
        name: 'Test UNLOCK EXECUTION',
        /*__n8n__*/ disabled: true,
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [-416, -544],
    })
    TestUnlockExecution = {
        assignments: {
            assignments: [
                {
                    id: '7615b10e-9c14-485b-aa81-5182c8a31c74',
                    name: 'ACTION',
                    value: '=unlock',
                    type: 'string',
                },
                {
                    id: '5adbdced-5084-4af9-93a3-5d96b39966d9',
                    name: 'PROCESS',
                    value: '=doc_step',
                    type: 'string',
                },
                {
                    id: '7432dad4-8d24-4aa2-a3ac-269b250d72ad',
                    name: 'EXECUTION',
                    value: '=34453',
                    type: 'number',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'b68647a1-03ff-442e-bc1c-3fbf7c31f7be',
        name: 'If',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [656, 64],
    })
    If_ = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: '8e09a06d-77eb-4bbc-a604-24df02955b83',
                    leftValue: '={{ $json.KEY }}',
                    rightValue: '',
                    operator: {
                        type: 'string',
                        operation: 'notEmpty',
                        singleValue: true,
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: '98565fd4-de5e-406a-98d9-0f3ec1bf88cf',
        name: 'SCAN PROCESS KEY1',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [912, 336],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    ScanProcessKey1 = {
        operation: 'keys',
        keyPattern: '=n8n.{{ $("Details").first().json.name }}.{{ $json.PROCESS }}.*.{{ $json.EXECUTION }}',
        getValues: false,
    };

    @node({
        id: '3d335447-5e17-4ae2-b240-5ac65d6eafe7',
        name: 'Details',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [208, -368],
    })
    Details = {
        assignments: {
            assignments: [
                {
                    id: 'cbb91070-f08e-47d6-b234-44ac7537ced1',
                    name: 'name',
                    value: 'process_lock',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '3ee69ce6-6375-4257-9671-d56307f68029',
        name: 'Split Out',
        type: 'n8n-nodes-base.splitOut',
        version: 1,
        position: [1120, 336],
    })
    SplitOut = {
        fieldToSplitOut: 'keys',
        options: {},
    };

    @node({
        id: 'fce2fe92-327e-493c-a2ad-d768a6d1b45b',
        name: 'DELETE RESULTS',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [1312, 336],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    DeleteResults = {
        operation: 'delete',
        key: '={{ $json.keys }}',
    };

    @node({
        id: '96e84289-bef2-4e7a-9e06-e7be578169be',
        name: 'Code',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1184, -288],
    })
    Code = {
        jsCode: `// Loop over input items and add a new field called 'myNewField' to the JSON of each one
for (const item of $input.all()) {
  for (let i = 0; i < item.json.keys.length; i++) {
    const props = item.json.keys[i].split(".")
    item.json.keys[i] = props[3]
  }
}

return $input.all();`,
    };

    @node({
        id: 'c2c55f3e-e33e-4e64-9302-a4adcf96e13e',
        name: 'Start',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-16, -128],
    })
    Start = {};

    @node({
        id: '474e3fbb-5eab-4292-8367-e9e835323d0a',
        name: 'StartTests',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-800, -320],
    })
    Starttests = {};

    @node({
        id: 'c4ee40e9-e2c0-4e7b-a0c0-cff86616cf24',
        name: 'Test CECHK & LOCK',
        /*__n8n__*/ disabled: true,
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [-416, -336],
    })
    TestCechkLock = {
        assignments: {
            assignments: [
                {
                    id: '7615b10e-9c14-485b-aa81-5182c8a31c74',
                    name: 'ACTION',
                    value: '=check_and_lock',
                    type: 'string',
                },
                {
                    id: '5adbdced-5084-4af9-93a3-5d96b39966d9',
                    name: 'PROCESS',
                    value: '=doc_step',
                    type: 'string',
                },
                {
                    id: '7432dad4-8d24-4aa2-a3ac-269b250d72ad',
                    name: 'EXECUTION',
                    value: '=34453',
                    type: 'number',
                },
                {
                    id: 'f7a4c4e8-5546-4e0f-a78a-657586d94bfe',
                    name: 'KEY',
                    value: '001',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '8ad9026b-c985-456a-8e7c-f066741d9abf',
        name: 'Replace Me',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [128, 864],
    })
    ReplaceMe = {};

    @node({
        id: '215b833c-c619-446a-b303-70a60d87a98e',
        name: 'DELETE RESULTS1',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [2160, 464],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    DeleteResults1 = {
        operation: 'delete',
        key: "={{ 'n8n.process_lock.doc_step.001' }}",
    };

    @node({
        id: 'b754a976-a390-4569-b0fd-73ea10e1ad83',
        name: 'Edit Fields1',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1488, 560],
    })
    EditFields1 = {
        assignments: {
            assignments: [
                {
                    id: '08f3468c-bf2d-4ed8-bf41-55e6e68ead0e',
                    name: '=was_locked',
                    value: '={{ $json.values()[0] > 1}}',
                    type: 'boolean',
                },
                {
                    id: 'cbb212af-3dbc-4121-9252-c98e0f782b03',
                    name: 'KEY',
                    value: "={{ $('Start').item.json.KEY }}",
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '142ac05a-c1f0-4b07-b0d3-a99a508612dc',
        name: 'SET PROCESS KEY1',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [1328, 960],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    SetProcessKey1 = {
        operation: 'set',
        key: '=n8n.{{ $("Details").first().json.name }}.{{ $("Start").item.json.PROCESS }}.{{ $("Start").item.json.KEY }}.{{ $("Start").item.json.EXECUTION }}',
        value: '=true',
        keyType: 'string',
        expire: true,
        ttl: '={{ 600 }}',
    };

    @node({
        id: '61e08083-b183-49d8-b7ba-b8744d46c8d6',
        name: 'GET PROCESS KEY EXECUTION1',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [800, 880],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    GetProcessKeyExecution1 = {
        operation: 'keys',
        keyPattern: '=n8n.{{ $("Details").first().json.name }}.{{ $json.PROCESS }}.{{ $json.KEY }}.*',
        getValues: false,
    };

    @node({
        id: '50c18d55-78dc-46d7-9f2a-c0fa3668fb9f',
        name: 'Edit Fields',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1632, 864],
    })
    EditFields = {
        assignments: {
            assignments: [
                {
                    id: '08f3468c-bf2d-4ed8-bf41-55e6e68ead0e',
                    name: '=was_locked',
                    value: '={{!!$json.keys}}',
                    type: 'boolean',
                },
                {
                    id: 'cbb212af-3dbc-4121-9252-c98e0f782b03',
                    name: 'KEY',
                    value: "={{ $('Start').item.json.KEY }}",
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '043118d7-b10c-4fe3-923a-fcaf4d151277',
        name: 'If LOCKED',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [992, 880],
    })
    IfLocked = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: '4d9bad6d-4657-4f04-9b8d-9ed37f6f6465',
                    leftValue: '={{ !!$json.keys.length }}',
                    rightValue: '',
                    operator: {
                        type: 'boolean',
                        operation: 'true',
                        singleValue: true,
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: 'ed059c10-000a-4712-8bec-1fb36c94f72b',
        name: 'Loop Over Items',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [528, 928],
    })
    LoopOverItems = {
        batchSize: 100000,
        options: {},
    };

    @node({
        id: 'b17cd430-cffd-4418-a0e7-ff35395fc997',
        name: 'GET CHECK PROCESS KEY EXECUTION2',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [896, 560],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    GetCheckProcessKeyExecution2 = {
        operation: 'incr',
        key: '=n8n.{{ $("Details").first().json.name }}.{{ $json.PROCESS }}.{{ $json.KEY }}',
        expire: false,
        ttl: '={{ 600 }}',
    };

    @node({
        id: 'pl-renew-note',
        name: 'Renew Note',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [-1376, 1336],
    })
    RenewNote = {
        content: `## ACTION='renew' (2026-08-06, task #72) - and why 'lock' could never do it

TWO KEY SHAPES, AND THEY NEVER MEET:
  check_and_lock -> 'GET CHECK PROCESS KEY EXECUTION2' INCRs   n8n.<name>.<PROCESS>.<KEY>
  lock           -> 'SET PROCESS KEY'                  SETs    n8n.<name>.<PROCESS>.<KEY>.<EXECUTION>

The second always carries one more '.' separator, so the two can never be the same string - whatever
EXECUTION renders to, and even when it is absent. That is unconditional, not a value bug.

syncV3Main0001 acquired its reconcile mutex with check_and_lock (4 segments) and then 'renewed' it
once per unit with ACTION='lock' (5 segments), passing no EXECUTION at all. Every renewal wrote an
ORPHAN key that nothing reads and nothing deletes, and the real mutex kept counting down its own TTL
exactly as before. The sticky note in syncV3Main0001 asserting that renewal keeps the lock alive was
describing a mechanism that ran, reported success, and protected nothing - the same defect class as
tasks #66/#68/#69 (gate G48), one layer down.

'unlock' with a KEY deletes n8n.<name>.<PROCESS>.<KEY> - 4 segments - so ACQUIRE and RELEASE always
agreed with each other. Renewal was the only one out of step, which is why nothing ever errored.

WHY A NEW ACTION RATHER THAN CHANGING 'lock'. processLock01 is shared - indoxV2Driver01's per-doc
step locking alone calls it 1,700+ times/day and depends on the 5-segment, per-EXECUTION key shape
(that is what lets 'unlock' by EXECUTION clean up everything one run holds). Redefining 'lock' to fix
one caller would silently change every other caller's key. 'renew' is purely additive: no existing
ACTION, no existing key shape and no trigger-input field changes (the executeWorkflowTrigger schema
already declares ACTION, so nothing is stripped - the G39 trap does not apply).

WHY IT REFUSES TO RE-ACQUIRE. 'Renew Exists?' reads the key first and renews ONLY if it is still
there. A plain INCR would RESURRECT a lapsed lock at value 1 - and since was_locked is \`value > 1\`,
the next pass would then read 1, conclude the lock was free, and start on top of the pass that was
still running. Both would believe they held it. So a renewal that finds the lock already gone returns
status:'lock_lost' / ok:false instead: the caller learns its lock lapsed mid-pass, which is the fact
it most needs and the one thing the old renewal could never tell it.

TTL: 600s, and it is now the SAME number in this file and on the live instance. The repo blueprint
said \`{{ 60*15 }}\` (900s) while live said \`{{ 600 }}\` - two sources of truth for how long a lock
survives its holder. Live wins here for two reasons: every measurement and every note written about
this lock (syncV3Main0001's 'Renewal Note') reasons about 600s, and pushing 900s would silently
lengthen stale-lock recovery for all 1,700+/day callers as a side effect of an unrelated deploy.`,
        height: 240,
        width: 400,
        color: 1,
    };

    @node({
        id: 'pl-renew-exists',
        name: 'RENEW CHECK EXISTS',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [560, -144],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    RenewCheckExists = {
        operation: 'keys',
        keyPattern: '=n8n.{{ $("Details").first().json.name }}.{{ $json.PROCESS }}.{{ $json.KEY }}',
        getValues: false,
    };

    @node({
        id: 'pl-renew-if',
        name: 'Renew Exists?',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [944, 736],
    })
    RenewExists = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'renew-exists',
                    leftValue: '={{ !!($json.keys || []).length }}',
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
        options: {},
    };

    @node({
        id: 'pl-renew-incr',
        name: 'RENEW PROCESS KEY',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [1328, 736],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    RenewProcessKey = {
        operation: 'incr',
        key: '=n8n.{{ $("Details").first().json.name }}.{{ $("Start").item.json.PROCESS }}.{{ $("Start").item.json.KEY }}',
        expire: true,
        ttl: '={{ 5400 }}',
    };

    @node({
        id: 'pl-renew-ok',
        name: 'Renew Result',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1712, 736],
    })
    RenewResult = {
        jsCode: `// The lock was still held, and its TTL has been re-stamped.
const s=$('Start').item.json||{};
return [{json:{ok:true, status:'renewed', renewed:true,
  PROCESS:s.PROCESS||null, KEY:s.KEY||null,
  detail:'ttl re-stamped on the key check_and_lock created'}}];`,
    };

    @node({
        id: 'pl-renew-lost',
        name: 'Renew Lost',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1328, 1136],
    })
    RenewLost = {
        jsCode: `// The lock is ALREADY GONE - it expired before this renewal arrived.
// Deliberately NOT re-acquired: check_and_lock reads \`was_locked\` as \`value > 1\`, so resurrecting
// the key at 1 would read as FREE to the next pass, and two passes would both believe they held it.
// Saying so is the useful answer - the caller is the only thing that knows whether it is still
// working, and until now it had no way to find out its lock had lapsed underneath it.
const s=$('Start').item.json||{};
return [{json:{ok:false, status:'lock_lost', code:'lock_expired', renewed:false,
  PROCESS:s.PROCESS||null, KEY:s.KEY||null,
  error:'the lock this caller held has already expired; it was NOT re-acquired here'}}];`,
    };

    @node({
        id: 'pl-unknown-action',
        name: 'Unknown Action',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [560, 176],
    })
    UnknownAction = {
        jsCode: `// An ACTION this lock does not implement used to fall off the end of the Switch: no output, no
// error, no execution row for the branch - the item simply stopped existing, and the CALLER got
// whatever the last node happened to leave behind. For a mutex that is the worst possible silence,
// because "I could not lock" and "I locked it" become indistinguishable to the thing about to do
// the work. A typo'd ACTION would have read as a successful acquisition.
//
// Found 2026-08-06 while fixing #72. G41 asks every rules-mode switch for a fallbackOutput; this
// switch is CONDITIONS-mode, which G41's structural check does not cover, so it kept its gap.
// Named outcome, same vocabulary as G48: ok:false + status:'refused' + a machine-readable code.
const a = String(($json || {}).ACTION || '');
return [{json:{ok:false, status:'refused', code:'unknown_action', ACTION:a || null,
  PROCESS:($json || {}).PROCESS || null, KEY:($json || {}).KEY || null,
  error:"unknown ACTION '" + a + "' (check | lock | unlock | check_and_lock | renew)"}}];`,
    };

    @node({
        id: 'lockttl-gate-0001',
        name: 'First Acquire?',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [916, 660],
    })
    FirstAcquire = {
        conditions: {
            options: {
                caseSensitive: true,
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'win-1',
                    leftValue: '={{ $json.values()[0] }}',
                    rightValue: 1,
                    operator: {
                        type: 'number',
                        operation: 'equals',
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: 'lockttl-stamp-0001',
        name: 'STAMP LOCK TTL (winner only)',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [936, 740],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    StampLockTtlWinnerOnly = {
        operation: 'set',
        key: '=n8n.{{ $("Details").first().json.name }}.{{ $("Start").item.json.PROCESS }}.{{ $("Start").item.json.KEY }}',
        value: '=1',
        keyType: 'string',
        expire: true,
        ttl: '={{ 5400 }}',
    };

    @node({
        id: 'lock-merge-001',
        name: 'Merge Lock Result',
        /*__n8n__*/ notes: "Winners and already-held documents rejoin here so 'Edit Fields1' runs ONCE over every document. Two connections on one input made it run twice, and executeWorkflow returns only one run - which is how already-locked documents vanished from the reply and were dispatched on top of live work.",
        type: 'n8n-nodes-base.merge',
        version: 3.2,
        position: [1308, 560],
    })
    MergeLockResult = {
        mode: 'append',
        numberInputs: 2,
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.Switch_.out(0).to(this.IfKey.in(0));
        this.Switch_.out(1).to(this.SetProcessKey.in(0));
        this.Switch_.out(2).to(this.If_.in(0));
        this.Switch_.out(3).to(this.GetCheckProcessKeyExecution2.in(0));
        this.Switch_.out(4).to(this.RenewCheckExists.in(0));
        this.Switch_.out(5).to(this.UnknownAction.in(0));
        this.WhenExecutedByAnotherWorkflow.out(0).to(this.Start.in(0));
        this.IfKey.out(0).to(this.IfExecution.in(0));
        this.IfKey.out(1).to(this.ScanProcess.in(0));
        this.IfExecution.out(0).to(this.GetProcessKeyExecution.in(0));
        this.IfExecution.out(1).to(this.ScanProcessKey.in(0));
        this.TestGetKeyExecution.out(0).to(this.Start.in(0));
        this.TestGetKey.out(0).to(this.Start.in(0));
        this.TestGetAllProcessKeys.out(0).to(this.Start.in(0));
        this.TestLock.out(0).to(this.Start.in(0));
        this.TestLock1.out(0).to(this.Start.in(0));
        this.TestUnlockKeyExecution.out(0).to(this.Start.in(0));
        this.TestUnlockExecution.out(0).to(this.Start.in(0));
        this.If_.out(0).to(this.UnklockProcessKeyExtraction.in(0));
        this.If_.out(0).to(this.ScanDocScopedLocks.in(0));
        this.If_.out(1).to(this.ScanProcessKey1.in(0));
        this.ScanProcessKey1.out(0).to(this.SplitOut.in(0));
        this.ScanDocScopedLocks.out(0).to(this.SplitOut.in(0));
        this.SplitOut.out(0).to(this.DeleteResults.in(0));
        this.ScanProcess.out(0).to(this.Code.in(0));
        this.Start.out(0).to(this.Switch_.in(0));
        this.Start.out(0).to(this.Details.in(0));
        this.Starttests.out(0).to(this.TestGetKeyExecution.in(0));
        this.Starttests.out(0).to(this.TestGetKey.in(0));
        this.Starttests.out(0).to(this.TestGetAllProcessKeys.in(0));
        this.Starttests.out(0).to(this.TestLock.in(0));
        this.Starttests.out(0).to(this.TestLock1.in(0));
        this.Starttests.out(0).to(this.TestUnlockKeyExecution.in(0));
        this.Starttests.out(0).to(this.TestUnlockExecution.in(0));
        this.Starttests.out(0).to(this.TestCechkLock.in(0));
        this.TestCechkLock.out(0).to(this.Start.in(0));
        this.SetProcessKey1.out(0).to(this.EditFields.in(0));
        this.GetProcessKeyExecution1.out(0).to(this.IfLocked.in(0));
        this.EditFields.out(0).to(this.LoopOverItems.in(0));
        this.IfLocked.out(0).to(this.EditFields.in(0));
        this.IfLocked.out(1).to(this.SetProcessKey1.in(0));
        this.LoopOverItems.out(1).to(this.GetProcessKeyExecution1.in(0));
        this.GetCheckProcessKeyExecution2.out(0).to(this.FirstAcquire.in(0));
        this.RenewCheckExists.out(0).to(this.RenewExists.in(0));
        this.RenewExists.out(0).to(this.RenewProcessKey.in(0));
        this.RenewExists.out(1).to(this.RenewLost.in(0));
        this.RenewProcessKey.out(0).to(this.RenewResult.in(0));
        this.FirstAcquire.out(0).to(this.StampLockTtlWinnerOnly.in(0));
        this.FirstAcquire.out(1).to(this.MergeLockResult.in(1));
        this.StampLockTtlWinnerOnly.out(0).to(this.MergeLockResult.in(0));
        this.MergeLockResult.out(0).to(this.EditFields1.in(0));
    }
}
