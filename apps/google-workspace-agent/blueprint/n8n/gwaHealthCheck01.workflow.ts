import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Google Integration Health
// Nodes   : 7  |  Connections: 8
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// GetManyMessages                    executeWorkflow
// GetRowSInSheet                     googleSheets               [creds]
// DeleteAFile                        executeWorkflow
// DownloadFile                       executeWorkflow
// CreateFileFromText                 executeWorkflow
// ScheduleTrigger                    scheduleTrigger
// ManualTrigger                      webhook                    [creds]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// ScheduleTrigger
//    → GetManyMessages
//    → CreateFileFromText
//      → DownloadFile
//        → DeleteAFile
//    → GetRowSInSheet
// ManualTrigger
//    → GetManyMessages (↩ loop)
//    → CreateFileFromText (↩ loop)
//    → GetRowSInSheet (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Download file":{"main":[[{"node":"Delete a file","type":"main","index":0}]]},"Create file from text":{"main":[[{"node":"Download file","type":"main","index":0}]]},"Schedule Trigger":{"main":[[{"node":"Get many messages","type":"main","index":0},{"node":"Create file from text","type":"main","index":0},{"node":"Get row(s) in sheet","type":"main","index":0}]]},"Manual Trigger":{"main":[[{"node":"Get many messages","type":"main","index":0},{"node":"Create file from text","type":"main","index":0},{"node":"Get row(s) in sheet","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-06T00:00:00.000Z","createdAt":"2026-08-06T00:00:00.000Z","id":"AppTagGwa000001a","name":"gwa-app"},{"updatedAt":"2026-08-06T00:00:00.000Z","createdAt":"2026-08-06T00:00:00.000Z","id":"de8accc1-f4e8-4a42-887e-4545f489893f","name":"role:infra"},{"name":"app:google-workspace-age"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {"templateCredsSetupCompleted":true},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: {"node:Schedule Trigger":{"recurrenceRules":[6]}},
    /*__n8n__*/ shared: [{"updatedAt":"2026-06-29T10:06:58.177Z","createdAt":"2026-06-29T10:06:58.177Z","role":"workflow:owner","workflowId":"gwaHealthCheck01","projectId":"Wx6WPGz1tIrghF2r","project":{"updatedAt":"2026-06-29T10:06:28.586Z","createdAt":"2026-06-29T10:02:30.215Z","id":"Wx6WPGz1tIrghF2r","name":"Shlomo Laptop <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"147f2398-75f7-4139-8132-7c477ee5cdfd"}}],
    id: 'gwaHealthCheck01',
    name: 'Google Integration Health',
    active: true,
    isArchived: false,
    tags: ['gwa-app', 'role:infra'],
    settings: {
        executionOrder: 'v1',
        callerPolicy: 'workflowsFromSameOwner',
        errorWorkflow: 'errorHandler01',
        availableInMCP: false,
    },
})
export class GoogleIntegrationHealthWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'f9cf3a62-c0b9-411e-bd09-2df852e3e0fd',
        name: 'Get many messages',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [-128, -352],
    })
    GetManyMessages = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'search',
                params: "={{ ({ query: '', limit: 3, connection_id: String($json.connection_id || '') }) }}",
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
                    id: 'params',
                    displayName: 'params',
                    required: false,
                    display: true,
                    type: 'object',
                    canBeUsedToMatch: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: '12438413-5e6a-41f6-b4fd-0f05a900d956',
        name: 'Get row(s) in sheet',
        type: 'n8n-nodes-base.googleSheets',
        version: 4.7,
        position: [-128, -176],
        credentials: { googleSheetsOAuth2Api: { id: 'e2knIZpw8YF0QBAB', name: 'Google Sheets' } },
    })
    GetRowSInSheet = {
        documentId: {
            __rl: true,
            value: '1SfWUiXCpzGcfgfqbd1xogN1sUpMIlsVajL-sKH4y11U',
            mode: 'list',
            cachedResultName: 'Incoming Documents — solutionsbina',
            cachedResultUrl: 'https://docs.google.com/spreadsheets/d/1SfWUiXCpzGcfgfqbd1xogN1sUpMIlsVajL-sKH4y11U/edit',
        },
        sheetName: {
            __rl: true,
            value: 1183063235,
            mode: 'list',
            cachedResultName: 'חברות',
            cachedResultUrl:
                'https://docs.google.com/spreadsheets/d/1SfWUiXCpzGcfgfqbd1xogN1sUpMIlsVajL-sKH4y11U/edit#gid=1183063235',
        },
        options: {},
    };

    @node({
        id: 'e163dcec-75a5-4ab4-8ed7-04ebd3075265',
        name: 'Delete a file',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [192, -16],
    })
    DeleteAFile = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'delete',
                params: '={{ ({ fileId: $json.id, profile_id: "admin" }) }}',
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
                    id: 'params',
                    displayName: 'params',
                    required: false,
                    display: true,
                    type: 'object',
                    canBeUsedToMatch: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: '0766067e-b56c-4377-ad00-48b55e041080',
        name: 'Download file',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [32, -16],
    })
    DownloadFile = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'download',
                params: '={{ ({ fileId: $json.id, fileIdMode: "id", profile_id: "admin" }) }}',
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
                    id: 'params',
                    displayName: 'params',
                    required: false,
                    display: true,
                    type: 'object',
                    canBeUsedToMatch: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: '415ef4ed-2caf-435c-a1d2-77fff8812b18',
        name: 'Create file from text',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [-128, -16],
    })
    CreateFileFromText = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'createFromText',
                params: '={{ ({ name: "Hello", content: $now.toString(), folderId: "1DBRCqqZnL7n3U0VdZ0KAR8S-YdqTLAZb", profile_id: "admin" }) }}',
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
                    id: 'params',
                    displayName: 'params',
                    required: false,
                    display: true,
                    type: 'object',
                    canBeUsedToMatch: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: '19e80a3f-980a-46d2-9aec-874b17ec4f53',
        name: 'Schedule Trigger',
        type: 'n8n-nodes-base.scheduleTrigger',
        version: 1.2,
        position: [-464, -16],
    })
    ScheduleTrigger = {
        rule: {
            interval: [{}],
        },
    };

    @node({
        id: '2fe49787-e803-4c2e-9a31-67d1722c7960',
        webhookId: 'ffb2fe8e-8843-4376-a85b-a6475798c415',
        name: 'Manual Trigger',
        type: 'n8n-nodes-base.webhook',
        version: 1.1,
        position: [-464, -192],
        credentials: { httpBasicAuth: { id: 'gBwYpBdw7cyJvg5v', name: 'CICD AUTH [env-managed]' } },
    })
    ManualTrigger = {
        httpMethod: 'POST',
        path: 'trigger-google-health',
        authentication: 'basicAuth',
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.DownloadFile.out(0).to(this.DeleteAFile.in(0));
        this.CreateFileFromText.out(0).to(this.DownloadFile.in(0));
        this.ScheduleTrigger.out(0).to(this.GetManyMessages.in(0));
        this.ScheduleTrigger.out(0).to(this.CreateFileFromText.in(0));
        this.ScheduleTrigger.out(0).to(this.GetRowSInSheet.in(0));
        this.ManualTrigger.out(0).to(this.GetManyMessages.in(0));
        this.ManualTrigger.out(0).to(this.CreateFileFromText.in(0));
        this.ManualTrigger.out(0).to(this.GetRowSInSheet.in(0));
    }
}
