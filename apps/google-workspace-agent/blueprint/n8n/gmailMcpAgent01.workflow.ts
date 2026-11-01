import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Gmail MCP Server
// Nodes   : 27  |  Connections: 0
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// Addlabels                          gmailTool                  [creds] [ai_tool]
// Delete_                            gmailTool                  [creds] [ai_tool]
// Get                                gmailTool                  [creds] [ai_tool]
// Search                             gmailTool                  [creds] [ai_tool]
// Markasread                         gmailTool                  [creds] [ai_tool]
// Markasunread                       gmailTool                  [creds] [ai_tool]
// Reply                              gmailTool                  [creds] [ai_tool]
// Removelabels                       gmailTool                  [creds] [ai_tool]
// StickyNote                         stickyNote
// Getlabels                          gmailTool                  [creds] [ai_tool]
// Getlabel                           gmailTool                  [creds] [ai_tool]
// Deletelabel                        gmailTool                  [creds] [ai_tool]
// Createlabel                        gmailTool                  [creds] [ai_tool]
// StickyNote1                        stickyNote
// Deletedraft                        gmailTool                  [creds] [ai_tool]
// Createdraft                        gmailTool                  [creds] [ai_tool]
// Getdraft                           gmailTool                  [creds] [ai_tool]
// Getmanydrafts                      gmailTool                  [creds] [ai_tool]
// StickyNote2                        stickyNote
// Getmanythreads                     gmailTool                  [creds] [ai_tool]
// Getthread                          gmailTool                  [creds] [ai_tool]
// Addlabelthread                     gmailTool                  [creds] [ai_tool]
// Removelabelthread                  gmailTool                  [creds] [ai_tool]
// Replythread                        gmailTool                  [creds] [ai_tool]
// StickyNote3                        stickyNote
// StickyNote4                        stickyNote
// McpServerTrigger                   mcpTrigger                 [AI] [creds]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
//
// AI CONNECTIONS
// McpServerTrigger.uses({ ai_tool: [Get, Reply, Delete_, Search, Getdraft, Getlabel, Addlabels, Getlabels, Getthread, Markasread, Createdraft, Createlabel, Deletedraft, Deletelabel, Replythread, Markasunread, Removelabels, Getmanydrafts, Addlabelthread, Getmanythreads, Removelabelthread] })
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"get":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"reply":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"delete":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"search":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"getDraft":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"getLabel":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"addLabels":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"getLabels":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"getThread":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"markAsRead":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"createDraft":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"createLabel":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"deleteDraft":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"deleteLabel":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"replyThread":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"markAsUnread":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"removeLabels":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"getManyDrafts":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"addLabelThread":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"getManyThreads":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]},"removeLabelThread":{"ai_tool":[[{"node":"MCP Server Trigger","type":"ai_tool","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-06T00:00:00.000Z","createdAt":"2026-08-06T00:00:00.000Z","id":"AppTagGwa000001a","name":"gwa-app"},{"updatedAt":"2026-08-06T00:00:00.000Z","createdAt":"2026-08-06T00:00:00.000Z","id":"dcb770a3-465f-4ed5-b5d4-ca1ff6dcd994","name":"lifecycle:test"},{"name":"app:google-workspace-age"}],
    /*__n8n__*/ versionMetadata: {"name":"Version 73ec6a60","description":""},
    /*__n8n__*/ meta: {"templateCredsSetupCompleted":true},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-06-29T10:06:58.177Z","createdAt":"2026-06-29T10:06:58.177Z","role":"workflow:owner","workflowId":"gmailMcpAgent01","projectId":"Wx6WPGz1tIrghF2r","project":{"updatedAt":"2026-06-29T10:06:28.586Z","createdAt":"2026-06-29T10:02:30.215Z","id":"Wx6WPGz1tIrghF2r","name":"Shlomo Laptop <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"147f2398-75f7-4139-8132-7c477ee5cdfd"}}],
    id: 'gmailMcpAgent01',
    name: 'Gmail MCP Server',
    active: true,
    isArchived: false,
    tags: ['gwa-app', 'lifecycle:test'],
    settings: { executionOrder: 'v1' },
})
export class GmailMcpServerWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: '9aa6060e-1340-4157-af8d-edfef493c0aa',
        webhookId: '81d61988-8213-4175-b75d-76cb67ce4a3b',
        name: 'addLabels',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [256, 864],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Addlabels = {
        descriptionType: 'manual',
        toolDescription:
            'Add one or more labels to an email message. AI-configurable parameters: Message_ID (string) - the ID of the message to label; Label_Names_or_IDs (string) - comma-separated label names or IDs to apply.',
        operation: 'addLabels',
        messageId: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Message_ID', ``, 'string') }}",
        labelIds: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Label_Names_or_IDs', ``, 'string') }}",
    };

    @node({
        id: 'bbdb522b-d733-46f8-b1d7-9a9a841caac5',
        webhookId: '03319c28-ef88-40f4-897c-f44c21dbdf1f',
        name: 'delete',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [-32, 672],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Delete_ = {
        descriptionType: 'manual',
        toolDescription:
            'Delete an email message. AI-configurable parameters: Message_ID (string) - the ID of the message to delete.',
        operation: 'delete',
        messageId: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Message_ID', ``, 'string') }}",
    };

    @node({
        id: 'a9f0a3fc-1e86-46b5-87e6-d94977d264f2',
        webhookId: 'cf5acbf3-a08f-4da6-9f14-9751eed6e5b8',
        name: 'get',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [96, 672],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Get = {
        descriptionType: 'manual',
        toolDescription:
            'Retrieve details of an email message. AI-configurable parameters: Message_ID (string) - the ID of the message to retrieve.',
        operation: 'get',
        messageId: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Message_ID', ``, 'string') }}",
    };

    @node({
        id: '1fe5a8ef-7a36-4b32-8d29-58b27a03f734',
        webhookId: 'cb3d028a-6cab-4946-b368-aa56bf271af9',
        name: 'search',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [224, 672],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Search = {
        descriptionType: 'manual',
        toolDescription:
            'Retrieve multiple email messages based on filters. AI-configurable parameters: Return_All (boolean) - whether to return all matching messages; Search (string) - Gmail query string to filter messages; Received_After (string) - datetime (RFC3339) after which messages are received; Received_Before (string) - datetime before which messages are received; Sender (string) - email address of the sender.',
        operation: 'getAll',
        returnAll: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Return_All', ``, 'boolean') }}",
        filters: {
            q: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Search', ``, 'string') }}",
            receivedAfter: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Received_After', ``, 'string') }}",
            receivedBefore: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Received_Before', ``, 'string') }}",
            sender: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Sender', ``, 'string') }}",
        },
    };

    @node({
        id: '781a6f67-57da-461b-a56a-4f2bdf05d33d',
        webhookId: 'e769b7cf-9622-434d-b98d-4bde7653238d',
        name: 'markAsRead',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [-192, 864],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Markasread = {
        descriptionType: 'manual',
        toolDescription:
            'Mark an email message as read. AI-configurable parameters: Message_ID (string) - the ID of the message to mark as read.',
        operation: 'markAsRead',
        messageId: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Message_ID', ``, 'string') }}",
    };

    @node({
        id: '62ff44fb-b407-485a-8f92-95d6e04f3442',
        webhookId: 'c26a8635-4329-498e-b293-4350baed493d',
        name: 'markAsUnread',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [-32, 864],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Markasunread = {
        descriptionType: 'manual',
        toolDescription:
            'Mark an email message as unread. AI-configurable parameters: Message_ID (string) - the ID of the message to mark as unread.',
        operation: 'markAsUnread',
        messageId: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Message_ID', ``, 'string') }}",
    };

    @node({
        id: 'd69d30b8-21f9-4c2f-8ea3-5a4725238658',
        webhookId: 'fbd30b84-25ac-4bab-8a66-5366b9b7a0be',
        name: 'reply',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [-160, 672],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Reply = {
        descriptionType: 'manual',
        toolDescription:
            'Reply to an email message. AI-configurable parameters: Message_ID (string) - the ID of the message; Message (string) - the reply content; Attachment_Field_Name (string) - input field name containing attachments; BCC (string) - comma-separated BCC recipients; CC (string) - comma-separated CC recipients.',
        operation: 'reply',
        messageId: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Message_ID', ``, 'string') }}",
        emailType: 'text',
        message: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Message', ``, 'string') }}",
        options: {
            appendAttribution: false,
            attachmentsUi: {
                attachmentsBinary: [
                    {
                        property:
                            "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Attachment_Field_Name', ``, 'string') }}",
                    },
                ],
            },
            bccList: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('BCC', ``, 'string') }}",
            ccList: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('CC', ``, 'string') }}",
        },
    };

    @node({
        id: '5aeb698d-15bc-4cb5-a9c7-aa2ebdd9effc',
        webhookId: 'e83fb7ee-2716-444b-9a4e-208eea215728',
        name: 'removeLabels',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [128, 864],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Removelabels = {
        descriptionType: 'manual',
        toolDescription:
            'Remove one or more labels from an email message. AI-configurable parameters: Message_ID (string) - the ID of the message; Label_Names_or_IDs (string) - comma-separated label names or IDs to remove.',
        operation: 'removeLabels',
        messageId: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Message_ID', ``, 'string') }}",
        labelIds: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Label_Names_or_IDs', ``, 'string') }}",
    };

    @node({
        id: '6ccfc9b6-f480-4f41-9ed4-bfd1cd8f55a1',
        name: 'Sticky Note',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [-272, 592],
    })
    StickyNote = {
        content: `## Message Tools
`,
        height: 460,
        width: 660,
    };

    @node({
        id: '6380650f-6c07-4b08-89e3-a8cbe2b75a12',
        webhookId: '1f107973-fe4a-440c-aaef-f35e1e8a555a',
        name: 'getLabels',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [544, 688],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Getlabels = {
        descriptionType: 'manual',
        toolDescription:
            'Retrieve a list of labels. AI-configurable parameters: Return_All (boolean) - whether to return all labels.',
        resource: 'label',
        returnAll: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Return_All', ``, 'boolean') }}",
    };

    @node({
        id: 'f5a8818c-4466-456c-92fd-5c2271bef215',
        webhookId: 'e9d3b2c0-50ea-4b3b-8509-f89dc4f20fb5',
        name: 'getLabel',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [688, 688],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Getlabel = {
        descriptionType: 'manual',
        toolDescription:
            'Retrieve details of a specific label. AI-configurable parameters: Label_ID (string) - the ID of the label to retrieve.',
        resource: 'label',
        operation: 'get',
        labelId: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Label_ID', ``, 'string') }}",
    };

    @node({
        id: '4e464cae-067e-4190-aebe-d7e94ef518fe',
        webhookId: '80a61a7c-f7a0-4fc9-a0a8-edd5846b4e11',
        name: 'deleteLabel',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [544, 896],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Deletelabel = {
        descriptionType: 'manual',
        toolDescription:
            'Delete a label. AI-configurable parameters: Label_ID (string) - the ID of the label to delete.',
        resource: 'label',
        operation: 'delete',
        labelId: "={{ $fromAI('Label_ID', ``, 'string') }}",
    };

    @node({
        id: '00cbd273-6dfc-4692-b8ea-66af855e2124',
        webhookId: 'd24d1672-4f76-4f58-912b-9345d23ba922',
        name: 'createLabel',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [704, 896],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Createlabel = {
        descriptionType: 'manual',
        toolDescription:
            'Create a new label. AI-configurable parameters: Label_ID (string) - the name of the label to create.',
        resource: 'label',
        operation: 'create',
        name: "={{ $fromAI('Label_ID', ``, 'string') }}",
        options: {},
    };

    @node({
        id: '97940c14-7af2-47a4-ba3d-07cf5f81e7b6',
        name: 'Sticky Note1',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [464, 592],
    })
    StickyNote1 = {
        content: `## Label Tools

`,
        height: 440,
        width: 380,
        color: 4,
    };

    @node({
        id: 'dbc99ff8-4a7b-411a-96b7-9deb195b68c6',
        webhookId: '8eb35ae4-6517-421b-b54f-ba0610cf58f4',
        name: 'deleteDraft',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [1008, 352],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Deletedraft = {
        descriptionType: 'manual',
        toolDescription:
            'Delete an email draft. AI-configurable parameters: Draft_ID (string) - the ID of the draft to delete.',
        resource: 'draft',
        operation: 'delete',
        messageId: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Draft_ID', ``, 'string') }}",
    };

    @node({
        id: '5d8d9869-bdd7-4e95-994f-7822a1a28bfe',
        webhookId: '1cca6c42-ccd9-4144-a2b1-6266d848f6ab',
        name: 'createDraft',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [1008, 176],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Createdraft = {
        descriptionType: 'manual',
        toolDescription:
            'Create an email draft. AI-configurable parameters: Subject (string) - the subject of the draft; Message (string) - the body of the draft; Attachment_Field_Name__in_Input_ (string) - input field name containing attachments; BCC (string) - comma-separated BCC recipients; CC (string) - comma-separated CC recipients.',
        resource: 'draft',
        subject: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Subject', ``, 'string') }}",
        message: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Message', ``, 'string') }}",
        options: {
            attachmentsUi: {
                attachmentsBinary: [
                    {
                        property:
                            "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Attachment_Field_Name__in_Input_', ``, 'string') }}",
                    },
                ],
            },
            bccList: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('BCC', ``, 'string') }}",
            ccList: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('CC', ``, 'string') }}",
        },
    };

    @node({
        id: 'fa476eb8-7611-47d3-a7c4-b698a6193bc2',
        webhookId: '80eadc8e-9d6b-42e7-9ac4-5b26d21fb3c5',
        name: 'getDraft',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [1184, 176],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Getdraft = {
        descriptionType: 'manual',
        toolDescription:
            'Retrieve an email draft. AI-configurable parameters: Draft_ID (string) - the ID of the draft to retrieve.',
        resource: 'draft',
        operation: 'get',
        messageId: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Draft_ID', ``, 'string') }}",
        options: {},
    };

    @node({
        id: '47c3cf3a-05a6-4bb9-b686-b395a42c0f17',
        webhookId: '6aaf2777-d1c1-490b-a82f-eaab6caefe85',
        name: 'getManyDrafts',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [1184, 352],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Getmanydrafts = {
        descriptionType: 'manual',
        toolDescription:
            'Retrieve multiple email drafts. AI-configurable parameters: Return_All (boolean) - whether to return all drafts; Include_Spam_and_Trash (boolean) - whether to include drafts in spam or trash.',
        resource: 'draft',
        operation: 'getAll',
        returnAll: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Return_All', ``, 'boolean') }}",
        options: {
            includeSpamTrash:
                "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Include_Spam_and_Trash', ``, 'boolean') }}",
        },
    };

    @node({
        id: '26447ca5-85c3-4fa9-aee1-c41be3892edf',
        name: 'Sticky Note2',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [928, 64],
    })
    StickyNote2 = {
        content: `## Draft Tools


`,
        height: 440,
        width: 380,
        color: 5,
    };

    @node({
        id: '2bb09813-4bd5-4c2d-9707-065ba2a03390',
        webhookId: '233fb55f-2575-4cbd-a327-e27858e98cd9',
        name: 'getManyThreads',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [960, 688],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Getmanythreads = {
        descriptionType: 'manual',
        toolDescription:
            'Retrieve multiple email threads based on filters. AI-configurable parameters: Return_All (boolean) - whether to return all threads; Search (string) - Gmail query string to filter threads; Received_After (string) - datetime after which threads are received; Received_Before (string) - datetime before which threads are received.',
        resource: 'thread',
        returnAll: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Return_All', ``, 'boolean') }}",
        filters: {
            q: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Search', ``, 'string') }}",
            receivedAfter: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Received_After', ``, 'string') }}",
            receivedBefore: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Received_Before', ``, 'string') }}",
        },
    };

    @node({
        id: '5231438f-727e-4793-8ff9-d79e244a5df7',
        webhookId: '9ecfaf0c-8d43-4b46-86bb-de5117b657c1',
        name: 'getThread',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [1120, 688],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Getthread = {
        descriptionType: 'manual',
        toolDescription:
            'Retrieve details of an email thread. AI-configurable parameters: Thread_ID (string) - the ID of the thread to retrieve.',
        resource: 'thread',
        operation: 'get',
        threadId: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Thread_ID', ``, 'string') }}",
        options: {
            returnOnlyMessages: true,
        },
    };

    @node({
        id: '94d12a63-5559-4ac0-8630-98c06d8c3ba7',
        webhookId: 'c7a99e26-cb22-4675-b5a8-fb7acd302983',
        name: 'addLabelThread',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [1280, 688],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Addlabelthread = {
        descriptionType: 'manual',
        toolDescription:
            'Add one or more labels to an email thread. AI-configurable parameters: Thread_ID (string) - the ID of the thread; Label_Names_or_IDs (string) - comma-separated label names or IDs to apply.',
        resource: 'thread',
        operation: 'addLabels',
        threadId: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Thread_ID', ``, 'string') }}",
        labelIds: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Label_Names_or_IDs', ``, 'string') }}",
    };

    @node({
        id: '58b12420-2033-43be-a091-66eb55ab4610',
        webhookId: 'cb63a038-73ba-4488-b70e-e3b8c48ee1b6',
        name: 'removeLabelThread',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [960, 864],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Removelabelthread = {
        descriptionType: 'manual',
        toolDescription:
            'Remove one or more labels from an email thread. AI-configurable parameters: Thread_ID (string) - the ID of the thread; Label_Names_or_IDs (string) - comma-separated label names or IDs to remove.',
        resource: 'thread',
        operation: 'removeLabels',
        threadId: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Thread_ID', ``, 'string') }}",
        labelIds: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Label_Names_or_IDs', ``, 'string') }}",
    };

    @node({
        id: 'f809fe2f-806f-45ef-ad86-1b4e09429c05',
        webhookId: 'b10a9bfd-eca1-40fd-817e-3ab1caf94d97',
        name: 'replyThread',
        type: 'n8n-nodes-base.gmailTool',
        version: 2.1,
        position: [1120, 864],
        credentials: { gmailOAuth2: { id: '41BKgLp83YYyfEM3', name: 'Gmail' } },
    })
    Replythread = {
        descriptionType: 'manual',
        toolDescription:
            'Reply to an email thread. AI-configurable parameters: Thread_ID (string) - the ID of the thread; Message (string) - the reply content; BCC (string) - comma-separated BCC recipients; CC (string) - comma-separated CC recipients.',
        resource: 'thread',
        operation: 'reply',
        threadId: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Thread_ID', ``, 'string') }}",
        message: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Message', ``, 'string') }}",
        options: {
            bccList: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('BCC', ``, 'string') }}",
            ccList: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('CC', ``, 'string') }}",
        },
    };

    @node({
        id: '58cc8db7-616f-4a90-8d9d-7ab39bdbf191',
        name: 'Sticky Note3',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [928, 592],
    })
    StickyNote3 = {
        content: `## Thread Tools


`,
        height: 440,
        width: 520,
        color: 7,
    };

    @node({
        id: '1fea451a-31d2-403d-8bf4-fee5d0e17006',
        name: 'Sticky Note4',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [-304, 64],
    })
    StickyNote4 = {
        content: `## USAGE

Open the Gmail MCP Server node to obtain the SSE server URL.

Use that to configure an N8N AI Agent flow or other AI tool.`,
        height: 240,
        width: 280,
        color: 6,
    };

    @node({
        id: 'c32a94f5-6b20-4aa6-a002-113a49aad147',
        webhookId: '02728abc-405a-41ca-8de2-6706c3265bef',
        name: 'MCP Server Trigger',
        type: '@n8n/n8n-nodes-langchain.mcpTrigger',
        version: 2,
        position: [560, 112],
        credentials: { httpHeaderAuth: { id: '2qKUrcv37UXZbz7u', name: 'Header Auth account [env-managed]' } },
    })
    McpServerTrigger = {
        authentication: 'headerAuth',
        path: 'gmail-enhanced',
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.McpServerTrigger.uses({
            ai_tool: [
                this.Get.output,
                this.Reply.output,
                this.Delete_.output,
                this.Search.output,
                this.Getdraft.output,
                this.Getlabel.output,
                this.Addlabels.output,
                this.Getlabels.output,
                this.Getthread.output,
                this.Markasread.output,
                this.Createdraft.output,
                this.Createlabel.output,
                this.Deletedraft.output,
                this.Deletelabel.output,
                this.Replythread.output,
                this.Markasunread.output,
                this.Removelabels.output,
                this.Getmanydrafts.output,
                this.Addlabelthread.output,
                this.Getmanythreads.output,
                this.Removelabelthread.output,
            ],
        });
    }
}
