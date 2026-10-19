import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Google Drive MCP Server - agent.hacohen
// Nodes   : 17  |  Connections: 9
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// StickyNote                         stickyNote
// StickyNote3                        stickyNote
// WhenExecutedByAnotherWorkflow      executeWorkflowTrigger
// GoogleDriveMcpServer               mcpTrigger                 [AI] [creds]
// StickyNote1                        stickyNote
// DownloadFile1                      googleDrive                [creds]
// Filetype                           switch
// Operation                          switch
// ExtractFromPdf                     extractFromFile
// ExtractFromCsv                     extractFromFile
// GetPdfResponse                     set
// GetCsvResponse                     set                        [executeOnce]
// ReadFileFromGdrive                 toolWorkflow               [ai_tool]
// SearchFilesFromGdrive              googleDriveTool            [creds] [ai_tool]
// AnalyseImage                       openAi                     [creds]
// TranscribeAudio                    openAi                     [creds]
// StickyNote2                        stickyNote
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenExecutedByAnotherWorkflow
//    → Operation
//      → DownloadFile1
//        → Filetype
//          → ExtractFromPdf
//            → GetPdfResponse
//         .out(1) → ExtractFromCsv
//            → GetCsvResponse
//         .out(2) → AnalyseImage
//         .out(3) → TranscribeAudio
//
// AI CONNECTIONS
// GoogleDriveMcpServer.uses({ ai_tool: [ReadFileFromGdrive, SearchFilesFromGdrive] })
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"FileType":{"main":[[{"node":"Extract from PDF","type":"main","index":0}],[{"node":"Extract from CSV","type":"main","index":0}],[{"node":"Analyse Image","type":"main","index":0}],[{"node":"Transcribe Audio","type":"main","index":0}],[]]},"Operation":{"main":[[{"node":"Download File1","type":"main","index":0}]]},"Download File1":{"main":[[{"node":"FileType","type":"main","index":0}]]},"Extract from CSV":{"main":[[{"node":"Get CSV Response","type":"main","index":0}]]},"Extract from PDF":{"main":[[{"node":"Get PDF Response","type":"main","index":0}]]},"Read File From GDrive":{"ai_tool":[[{"node":"Google Drive MCP Server","type":"ai_tool","index":0}]]},"Search Files from Gdrive":{"ai_tool":[[{"node":"Google Drive MCP Server","type":"ai_tool","index":0}]]},"When Executed by Another Workflow":{"main":[[{"node":"Operation","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-06T00:00:00.000Z","createdAt":"2026-08-06T00:00:00.000Z","id":"AppTagGwa000001a","name":"gwa-app"},{"updatedAt":"2026-08-06T00:00:00.000Z","createdAt":"2026-08-06T00:00:00.000Z","id":"dcb770a3-465f-4ed5-b5d4-ca1ff6dcd994","name":"lifecycle:test"},{"name":"app:google-workspace-age"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-06-29T10:06:58.177Z","createdAt":"2026-06-29T10:06:58.177Z","role":"workflow:owner","workflowId":"gDriveMcpAgent01","projectId":"Wx6WPGz1tIrghF2r","project":{"updatedAt":"2026-06-29T10:06:28.586Z","createdAt":"2026-06-29T10:02:30.215Z","id":"Wx6WPGz1tIrghF2r","name":"Shlomo Laptop <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"147f2398-75f7-4139-8132-7c477ee5cdfd"}}],
    id: 'gDriveMcpAgent01',
    name: 'Google Drive MCP Server - agent.hacohen',
    active: true,
    isArchived: false,
    tags: ['gwa-app', 'lifecycle:test'],
    settings: { executionOrder: 'v1', callerPolicy: 'workflowsFromSameOwner', availableInMCP: false },
})
export class GoogleDriveMcpServerAgentHacohenWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'fb5b682b-5e30-497e-b465-c3369bb3c2e3',
        name: 'Sticky Note',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [-32, -20],
    })
    StickyNote = {
        color: 7,
        width: 680,
        height: 660,
        content: `## 1. Set up an MCP Server Trigger
[Read more about the MCP Server Trigger](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcptrigger)`,
    };

    @node({
        id: 'cfc2c7f1-a6ee-42a9-b955-e5bce012b6e1',
        name: 'Sticky Note3',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [-40, -160],
    })
    StickyNote3 = {
        color: 5,
        width: 380,
        height: 100,
        content: `### Always Authenticate Your Server!
Before going to production, it's always advised to enable authentication on your MCP server trigger.`,
    };

    @node({
        id: '79586d35-0582-4da8-91da-5bc8451c2089',
        name: 'When Executed by Another Workflow',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [800, 360],
    })
    WhenExecutedByAnotherWorkflow = {
        workflowInputs: {
            values: [
                {
                    name: 'operation',
                },
                {
                    name: 'folderId',
                },
                {
                    name: 'fileId',
                },
            ],
        },
    };

    @node({
        id: '02aee033-58e8-4f33-a18d-b872840e81d8',
        webhookId: '7639950f-37e1-4a14-89e8-74f488badbc1',
        name: 'Google Drive MCP Server',
        type: '@n8n/n8n-nodes-langchain.mcpTrigger',
        version: 2,
        position: [160, 160],
        credentials: { httpHeaderAuth: { id: '2qKUrcv37UXZbz7u', name: 'Header Auth account [env-managed]' } },
    })
    GoogleDriveMcpServer = {
        path: 'gdrive-agent',
        authentication: 'headerAuth',
    };

    @node({
        id: 'e0e50653-d98a-4ad4-a2ed-e1b73332c380',
        name: 'Sticky Note1',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [680, -20],
    })
    StickyNote1 = {
        color: 7,
        width: 1340,
        height: 860,
        content: `## 2. Handle Multiple Binary Formats via Conversion and AI
[Read more about the PostgreSQL Node](https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.postgres/)

MCP clients (or rather, the AI agents) still expect and require text responses from our MCP server.
N8N can provide the right conversion tools to parse most text formats such as PDF, CSV and XML.
For images, audio and video, consider using multimodal LLMs to describe or transcribe the file instead.`,
    };

    @node({
        id: '6be1ff49-5edc-42d2-87de-09d207ee7733',
        name: 'Download File1',
        type: 'n8n-nodes-base.googleDrive',
        version: 3,
        position: [1160, 360],
        credentials: { googleDriveOAuth2Api: { id: 'KirWFwoFdEFmnN0R', name: 'Google Drive' } },
    })
    DownloadFile1 = {
        fileId: {
            __rl: true,
            mode: 'id',
            value: '={{ $json.fileId }}',
        },
        options: {
            googleFileConversion: {
                conversion: {
                    docsToFormat: 'text/plain',
                    slidesToFormat: 'application/pdf',
                },
            },
        },
        operation: 'download',
    };

    @node({
        id: '91b0a549-0494-48a1-bdf3-6c2b91409d01',
        name: 'FileType',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [1340, 320],
    })
    Filetype = {
        rules: {
            values: [
                {
                    outputKey: 'pdf',
                    conditions: {
                        options: {
                            version: 2,
                            leftValue: '',
                            caseSensitive: true,
                            typeValidation: 'strict',
                        },
                        combinator: 'and',
                        conditions: [
                            {
                                id: '7b6958ce-d553-4379-a5d6-743f39b342d0',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                                leftValue: '={{ $binary.data.mimeType }}',
                                rightValue: 'application/pdf',
                            },
                        ],
                    },
                    renameOutput: true,
                },
                {
                    outputKey: 'csv',
                    conditions: {
                        options: {
                            version: 2,
                            leftValue: '',
                            caseSensitive: true,
                            typeValidation: 'strict',
                        },
                        combinator: 'and',
                        conditions: [
                            {
                                id: 'd0816a37-ac06-49e3-8d63-17fcd061e33f',
                                operator: {
                                    name: 'filter.operator.equals',
                                    type: 'string',
                                    operation: 'equals',
                                },
                                leftValue: '={{ $binary.data.mimeType }}',
                                rightValue: 'text/csv',
                            },
                        ],
                    },
                    renameOutput: true,
                },
                {
                    outputKey: 'image',
                    conditions: {
                        options: {
                            version: 2,
                            leftValue: '',
                            caseSensitive: true,
                            typeValidation: 'strict',
                        },
                        combinator: 'and',
                        conditions: [
                            {
                                id: '589540e1-1439-41e3-ba89-b27f5e936190',
                                operator: {
                                    type: 'boolean',
                                    operation: 'true',
                                    singleValue: true,
                                },
                                leftValue: `={{
[
  'image/jpeg',
  'image/jpg',
  'image/png',
  'image/gif'
].some(mimeType => $binary.data.mimeType === mimeType)
}}`,
                                rightValue: '',
                            },
                        ],
                    },
                    renameOutput: true,
                },
                {
                    outputKey: 'audio',
                    conditions: {
                        options: {
                            version: 2,
                            leftValue: '',
                            caseSensitive: true,
                            typeValidation: 'strict',
                        },
                        combinator: 'and',
                        conditions: [
                            {
                                id: 'b8fc61a1-6057-4db3-960e-b8ddcbdd0f31',
                                operator: {
                                    type: 'string',
                                    operation: 'contains',
                                },
                                leftValue: '={{ $binary.data.mimeType }}',
                                rightValue: 'audio',
                            },
                        ],
                    },
                    renameOutput: true,
                },
                {
                    outputKey: 'video',
                    conditions: {
                        options: {
                            version: 2,
                            leftValue: '',
                            caseSensitive: true,
                            typeValidation: 'strict',
                        },
                        combinator: 'and',
                        conditions: [
                            {
                                id: '959d65a6-372f-4978-b2d1-f28aa1e372c6',
                                operator: {
                                    type: 'string',
                                    operation: 'contains',
                                },
                                leftValue: '={{ $binary.data.mimeType }}',
                                rightValue: 'video',
                            },
                        ],
                    },
                    renameOutput: true,
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'd88ed202-1121-41db-859d-b31d53d46292',
        name: 'Operation',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [980, 360],
    })
    Operation = {
        rules: {
            values: [
                {
                    outputKey: 'ReadFile',
                    conditions: {
                        options: {
                            version: 2,
                            leftValue: '',
                            caseSensitive: true,
                            typeValidation: 'strict',
                        },
                        combinator: 'and',
                        conditions: [
                            {
                                id: 'b03bb746-dc4e-469c-b8e6-a34c0aa8d0a6',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                                leftValue: '={{ $json.operation }}',
                                rightValue: 'readFile',
                            },
                        ],
                    },
                    renameOutput: true,
                },
            ],
        },
        options: {},
    };

    @node({
        id: '7e8791e6-24c2-441a-8efb-7f4375f2519b',
        name: 'Extract from PDF',
        type: 'n8n-nodes-base.extractFromFile',
        version: 1,
        position: [1620, 80],
    })
    ExtractFromPdf = {
        options: {},
        operation: 'pdf',
    };

    @node({
        id: '2b33623c-cea4-4a83-80ef-f852b9a3d126',
        name: 'Extract from CSV',
        type: 'n8n-nodes-base.extractFromFile',
        version: 1,
        position: [1620, 260],
    })
    ExtractFromCsv = {
        options: {
            encoding: 'utf-8',
            headerRow: false,
            relaxQuotes: true,
            includeEmptyCells: true,
        },
    };

    @node({
        id: '6ca2542d-225e-4a65-b5ce-3edafb11379c',
        name: 'Get PDF Response',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1780, 80],
    })
    GetPdfResponse = {
        options: {},
        assignments: {
            assignments: [
                {
                    id: 'a481cde3-b8ec-4d97-aa13-4668bd66c24d',
                    name: 'response',
                    type: 'string',
                    value: '={{ $json.text }}',
                },
            ],
        },
    };

    @node({
        id: '3d1c4aa6-cac1-4957-ab7e-3134368e4b53',
        name: 'Get CSV Response',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1780, 260],
        executeOnce: true,
    })
    GetCsvResponse = {
        options: {},
        assignments: {
            assignments: [
                {
                    id: 'a481cde3-b8ec-4d97-aa13-4668bd66c24d',
                    name: 'response',
                    type: 'string',
                    value: `={{
$input.all()
  .map(item => item.json.row.map(cell => \`"\${cell}"\`).join(','))
  .join('\\n')
}}`,
                },
            ],
        },
    };

    @node({
        id: '141444f9-e937-41f9-ab97-09624646ddba',
        name: 'Read File From GDrive',
        type: '@n8n/n8n-nodes-langchain.toolWorkflow',
        version: 2.1,
        position: [400, 380],
    })
    ReadFileFromGdrive = {
        name: 'ReadFile',
        workflowId: {
            __rl: true,
            mode: 'id',
            value: '={{ $workflow.id }}',
        },
        description: 'Call this tool to download and read the contents of a file within google drive.',
        workflowInputs: {
            value: {
                fileId: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('fileId', ``, 'string') }}",
                folderId: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('folderId', ``, 'string') }}",
                operation: 'readFile',
            },
            schema: [
                {
                    id: 'operation',
                    type: 'string',
                    display: true,
                    removed: false,
                    required: false,
                    displayName: 'operation',
                    defaultMatch: false,
                    canBeUsedToMatch: true,
                },
                {
                    id: 'folderId',
                    type: 'string',
                    display: true,
                    removed: false,
                    required: false,
                    displayName: 'folderId',
                    defaultMatch: false,
                    canBeUsedToMatch: true,
                },
                {
                    id: 'fileId',
                    type: 'string',
                    display: true,
                    removed: false,
                    required: false,
                    displayName: 'fileId',
                    defaultMatch: false,
                    canBeUsedToMatch: true,
                },
            ],
            mappingMode: 'defineBelow',
            matchingColumns: [],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
    };

    @node({
        id: 'b5851527-0b57-447b-ac8c-10408a684862',
        name: 'Search Files from Gdrive',
        type: 'n8n-nodes-base.googleDriveTool',
        version: 3,
        position: [240, 380],
        credentials: { googleDriveOAuth2Api: { id: 'KirWFwoFdEFmnN0R', name: 'Google Drive' } },
    })
    SearchFilesFromGdrive = {
        limit: 10,
        filter: {
            driveId: {
                mode: 'list',
                value: 'My Drive',
            },
            whatToSearch: 'files',
        },
        options: {},
        resource: 'fileFolder',
        queryString: "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Search_Query', ``, 'string') }}",
    };

    @node({
        id: '98197c91-c7e9-4fbb-a2b1-c16c873fa0a1',
        name: 'Analyse Image',
        type: '@n8n/n8n-nodes-langchain.openAi',
        version: 1.8,
        position: [1620, 440],
        credentials: { openAiApi: { id: 'xu8Y1cko7L6LmqMd', name: 'OpenAi account [env-managed]' } },
    })
    AnalyseImage = {
        modelId: {
            __rl: true,
            mode: 'list',
            value: 'gpt-4o-mini',
            cachedResultName: 'GPT-4O-MINI',
        },
        options: {},
        resource: 'image',
        inputType: 'base64',
        operation: 'analyze',
    };

    @node({
        id: 'b44a787a-c670-47e1-b87e-d880425ce610',
        name: 'Transcribe Audio',
        type: '@n8n/n8n-nodes-langchain.openAi',
        version: 1.8,
        position: [1620, 620],
        credentials: { openAiApi: { id: 'xu8Y1cko7L6LmqMd', name: 'OpenAi account [env-managed]' } },
    })
    TranscribeAudio = {
        options: {},
        resource: 'audio',
        operation: 'transcribe',
    };

    @node({
        id: '1e1a358d-769e-48c9-bf27-6a3cfaaacb14',
        name: 'Sticky Note2',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [-500, -420],
    })
    StickyNote2 = {
        width: 440,
        height: 1060,
        content: `## Try It Out!
### This n8n demonstrates how to build a simple Google Drive MCP server to search and get contents of files from Google Drive.

This MCP example is based off an official MCP reference implementation which can be found here -https://github.com/modelcontextprotocol/servers/tree/main/src/gdrive

### How it works
* A MCP server trigger is used and connected to 1x Google Drive tool and 1x Custom Workflow tool.
* The Google Drive tool is set to perform a search on files within our Google Drive folder.
* The Custom Workflow tool downloads target files found in our drive and converts the binaries to their text representation. Eg. PDFs have only their text contents extracted and returned to the MCP client.

### How to use
* This Google Drive MCP server allows any compatible MCP client to manage a person or shared Google Drive. Simple select a drive or for better control, specify a folder within the drive to scope the operations to.
* Connect your MCP client by following the n8n guidelines here - https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcptrigger/#integrating-with-claude-desktop
* Try the following queries in your MCP client:
  * "Please help me search for last month's expense reports."
 * "What does the company policy document say about cancellations and refunds?"

### Requirements
* Google Drive for documents.
* OpenAI for image and audio understanding.
* MCP Client or Agent for usage such as Claude Desktop - https://claude.ai/download

### Customising this workflow
* Add additional capabilities such as renaming, moving and/or deleting files.
* Remember to set the MCP server to require credentials before going to production and sharing this MCP server with others!`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.Filetype.out(0).to(this.ExtractFromPdf.in(0));
        this.Filetype.out(1).to(this.ExtractFromCsv.in(0));
        this.Filetype.out(2).to(this.AnalyseImage.in(0));
        this.Filetype.out(3).to(this.TranscribeAudio.in(0));
        this.Operation.out(0).to(this.DownloadFile1.in(0));
        this.DownloadFile1.out(0).to(this.Filetype.in(0));
        this.ExtractFromCsv.out(0).to(this.GetCsvResponse.in(0));
        this.ExtractFromPdf.out(0).to(this.GetPdfResponse.in(0));
        this.WhenExecutedByAnotherWorkflow.out(0).to(this.Operation.in(0));

        this.GoogleDriveMcpServer.uses({
            ai_tool: [this.ReadFileFromGdrive.output, this.SearchFilesFromGdrive.output],
        });
    }
}
