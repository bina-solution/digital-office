import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : invoice Extractor - Gemini 3.1 pro
// Nodes   : 59  |  Connections: 66
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WebhookTrigger                     webhook                    [creds]
// FileTypeRouter                     switch
// ApiResponse                        respondToWebhook
// TextualInput                       noOp
// ExtractFromFile                    extractFromFile
// Code                               code
// StickyNote                         stickyNote
// ExtractFromFile1                   extractFromFile
// ExtractFromFile2                   extractFromFile            [onError→out(1)]
// ResponseFormatUnsupportedFileError function
// Crypto                             crypto
// Kvstorage                          postgres                   [creds]
// Kvstorage1                         postgres                   [creds]
// End                                noOp
// BeforeStart                        noOp
// ResolveFields                      code
// Start                              noOp
// ApiResponse1                       respondToWebhook
// If_                                if
// Code2                              code
// StickyNote2                        stickyNote
// StickyNote6                        stickyNote
// If1                                if
// WhenExecutedByAnotherWorkflow      executeWorkflowTrigger
// Switch_                            switch
// DownloadLink                       executeWorkflow            [onError→regular] [alwaysOutput]
// IfBinary                           if
// CodeInJavascript                   code
// CodeInJavascript1                  code
// MapLink                            set
// IfSuccess                          if
// Config                             set
// GoogleGeminiChatModel              lmChatGoogleGemini         [creds]
// DocumentProcessor                  googleGemini               [onError→out(1)] [creds] [retry]
// TextProcessor                      googleGemini               [creds] [retry]
// Config1                            code                       [executeOnce]
// MapResponse                        set
// ExtractResponse                    set
// ParseJsonResponse                  function
// FormatResponse                     function
// ResponseFormatNoLlmOutput          function
// MapLink1                           set
// WhenClickingExecuteWorkflow        manualTrigger
// DeleteCache                        kvStorage
// HttpRequest                        httpRequest                [creds]
// CodeInJavascript2                  code
// CodeInJavascript3                  code
// Start1                             noOp
// End2                               noOp
// CheckAiEnabledSetting              postgres                   [creds]
// IfAiDisabled                       if
// ApiResponseAiDisabled              respondToWebhook
// LoadV3ConfigAi                     postgres                   [creds] [alwaysOutput]
// BuildPromptFromQueries             code
// CheckDocBytes                      code
// DocBytesOk                         if
// ReportUnusableDocument             code
// ReportMissingLink                  code
// DecodeCsvText                      code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WebhookTrigger
//    → MapLink1
//      → Switch_
//        → BeforeStart
//          → ResolveFields
//            → Config1
//              → LoadV3ConfigAi
//                → BuildPromptFromQueries
//                  → Config
//            → If1
//              → Crypto
//                → Kvstorage
//                  → If_
//                    → CodeInJavascript1
//                      → ApiResponse1
//                   .out(1) → CheckAiEnabledSetting
//                      → IfAiDisabled
//                        → ApiResponseAiDisabled
//                       .out(1) → Code2
//                          → Start
//                            → FileTypeRouter
//                              → ExtractFromFile1
//                                → TextualInput
//                                  → TextProcessor
//                                    → ExtractResponse
//                                      → ParseJsonResponse
//                                        → FormatResponse
//                                          → MapResponse
//                                            → End
//                                              → ApiResponse
//                                              → IfSuccess
//                                                → Kvstorage1
//                                              → End2
//                             .out(1) → ExtractFromFile
//                                → DecodeCsvText
//                                  → Code
//                                    → TextualInput (↩ loop)
//                             .out(2) → ExtractFromFile2
//                                → Code (↩ loop)
//                               .out(1) → ResponseFormatUnsupportedFileError
//                                  → End (↩ loop)
//                             .out(3) → ExtractFromFile2 (↩ loop)
//                             .out(4) → Start1
//                                → CheckDocBytes
//                                  → DocBytesOk
//                                    → DocumentProcessor
//                                      → ExtractResponse (↩ loop)
//                                     .out(1) → ResponseFormatNoLlmOutput
//                                        → End (↩ loop)
//                                   .out(1) → ReportUnusableDocument
//                                      → End (↩ loop)
//                             .out(5) → Start1 (↩ loop)
//                             .out(6) → Start1 (↩ loop)
//                             .out(7) → ResponseFormatUnsupportedFileError (↩ loop)
//             .out(1) → Start (↩ loop)
//       .out(1) → DownloadLink
//          → IfBinary
//            → BeforeStart (↩ loop)
//           .out(1) → CodeInJavascript
//              → End (↩ loop)
//       .out(2) → ReportMissingLink
//          → End (↩ loop)
// WhenExecutedByAnotherWorkflow
//    → Switch_ (↩ loop)
// MapLink
//    → Switch_ (↩ loop)
// WhenClickingExecuteWorkflow
//    → DeleteCache
// CodeInJavascript3
//    → HttpRequest
//      → CodeInJavascript2
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Webhook Trigger":{"main":[[{"node":"MAP LINK1","type":"main","index":0}]]},"File Type Router":{"main":[[{"node":"Extract from File1","type":"main","index":0}],[{"node":"Extract from File","type":"main","index":0}],[{"node":"Extract from File2","type":"main","index":0}],[{"node":"Extract from File2","type":"main","index":0}],[{"node":"Start1","type":"main","index":0}],[{"node":"Start1","type":"main","index":0}],[{"node":"Start1","type":"main","index":0}],[{"node":"Response Format: Unsupported File Error","type":"main","index":0}]]},"Textual Input":{"main":[[{"node":"Text Processor","type":"main","index":0}]]},"Extract from File":{"main":[[{"node":"Decode CSV Text","type":"main","index":0}]]},"Code":{"main":[[{"node":"Textual Input","type":"main","index":0}]]},"Extract from File1":{"main":[[{"node":"Textual Input","type":"main","index":0}]]},"Extract from File2":{"main":[[{"node":"Code","type":"main","index":0}],[{"node":"Response Format: Unsupported File Error","type":"main","index":0}]]},"Response Format: Unsupported File Error":{"main":[[{"node":"End","type":"main","index":0}]]},"Crypto":{"main":[[{"node":"KVStorage","type":"main","index":0}]]},"End":{"main":[[{"node":"API Response","type":"main","index":0},{"node":"If Success","type":"main","index":0},{"node":"End2","type":"main","index":0}]]},"Before Start":{"main":[[{"node":"Resolve Fields","type":"main","index":0}]]},"KVStorage":{"main":[[{"node":"If","type":"main","index":0}]]},"Start":{"main":[[{"node":"File Type Router","type":"main","index":0}]]},"If":{"main":[[{"node":"Code in JavaScript1","type":"main","index":0}],[{"node":"Check AI Enabled Setting","type":"main","index":0}]]},"Code2":{"main":[[{"node":"Start","type":"main","index":0}]]},"If1":{"main":[[{"node":"Crypto","type":"main","index":0}],[{"node":"Start","type":"main","index":0}]]},"When Executed by Another Workflow":{"main":[[{"node":"Switch","type":"main","index":0}]]},"Switch":{"main":[[{"node":"Before Start","type":"main","index":0}],[{"node":"Download LINK","type":"main","index":0}],[{"node":"Report Missing Link","type":"main","index":0}]]},"Download LINK":{"main":[[{"node":"If Binary","type":"main","index":0}]]},"If Binary":{"main":[[{"node":"Before Start","type":"main","index":0}],[{"node":"Code in JavaScript","type":"main","index":0}]]},"Code in JavaScript1":{"main":[[{"node":"API Response1","type":"main","index":0}]]},"MAP LINK":{"main":[[{"node":"Switch","type":"main","index":0}]]},"If Success":{"main":[[{"node":"KVStorage1","type":"main","index":0}]]},"Google Gemini Chat Model":{"ai_languageModel":[[]]},"Map Response":{"main":[[{"node":"End","type":"main","index":0}]]},"Extract Response":{"main":[[{"node":"Parse JSON Response","type":"main","index":0}]]},"Parse JSON Response":{"main":[[{"node":"Format Response","type":"main","index":0}]]},"Response Format: No LLM Output":{"main":[[{"node":"End","type":"main","index":0}]]},"MAP LINK1":{"main":[[{"node":"Switch","type":"main","index":0}]]},"When clicking ‘Execute workflow’":{"main":[[{"node":"Delete Cache","type":"main","index":0}]]},"Document Processor":{"main":[[{"node":"Extract Response","type":"main","index":0}],[{"node":"Response Format: No LLM Output","type":"main","index":0}]]},"Format Response":{"main":[[{"node":"Map Response","type":"main","index":0}]]},"Text Processor":{"main":[[{"node":"Extract Response","type":"main","index":0}]]},"HTTP Request":{"main":[[{"node":"Code in JavaScript2","type":"main","index":0}]]},"Code in JavaScript2":{"main":[[]]},"Code in JavaScript3":{"main":[[{"node":"HTTP Request","type":"main","index":0}]]},"Start1":{"main":[[{"node":"Check Doc Bytes","type":"main","index":0}]]},"Check AI Enabled Setting":{"main":[[{"node":"If AI Disabled","type":"main","index":0}]]},"If AI Disabled":{"main":[[{"node":"API Response - AI Disabled","type":"main","index":0}],[{"node":"Code2","type":"main","index":0}]]},"Load V3 Config (AI)":{"main":[[{"node":"Build Prompt From Queries","type":"main","index":0}]]},"Build Prompt From Queries":{"main":[[{"node":"CONFIG","type":"main","index":0}]]},"Config1":{"main":[[{"node":"Load V3 Config (AI)","type":"main","index":0}]]},"Check Doc Bytes":{"main":[[{"node":"Doc Bytes OK?","type":"main","index":0}]]},"Doc Bytes OK?":{"main":[[{"node":"Document Processor","type":"main","index":0}],[{"node":"Report Unusable Document","type":"main","index":0}]]},"Report Unusable Document":{"main":[[{"node":"End","type":"main","index":0}]]},"Resolve Fields":{"main":[[{"node":"Config1","type":"main","index":0},{"node":"If1","type":"main","index":0}]]},"Report Missing Link":{"main":[[{"node":"End","type":"main","index":0}]]},"Code in JavaScript":{"main":[[{"node":"End","type":"main","index":0}]]},"Decode CSV Text":{"main":[[{"node":"Code","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"22f1e71e-91bf-48db-811f-8d3bc4e55a3e","name":"sm-refactor-v2.1"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"b3a3da17-1411-451c-8372-59d4c758937a","name":"ai-invoice"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"f5d175fb-c738-4607-8ef0-bf03c48e8a0b","name":"role:extractor"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"56de2cdd-1d32-4a04-b009-b7d1928bf34d","name":"extractors"},{"updatedAt":"2026-07-30T23:41:29.646Z","createdAt":"2026-07-30T23:41:29.646Z","id":"9c337cfe-7feb-4f3d-ab26-3de6439357ce","name":"sm-refactore-v2.1"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-31T00:59:54.840Z","createdAt":"2026-07-31T00:59:54.840Z","role":"workflow:owner","workflowId":"indoxV2ExtractInvoiceGemini01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2ExtractInvoiceGemini01',
    name: 'invoice Extractor - Gemini 3.1 pro',
    active: true,
    isArchived: false,
    tags: [
        'sm-refactor-v2.1',
        'ai-invoice',
        'indox-app',
        'role:extractor',
        'app:indox',
        'indox',
        'extractors',
        'sm-refactore-v2.1',
    ],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class InvoiceExtractorGemini31ProWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'ed361653-6367-4574-80ea-776522d99c97',
        webhookId: 'a33c7ec8-c766-4d68-b05b-008d6e1027eb',
        name: 'Webhook Trigger',
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [-208, 848],
        credentials: { httpBasicAuth: { id: 'azPhHBvOWaf9IsEA', name: 'Incoming Documents [env-managed]' } },
    })
    WebhookTrigger = {
        httpMethod: 'POST',
        path: 'invoice_extractor',
        authentication: 'basicAuth',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: '91a438bb-7330-4c59-a9d8-7d6c15018e49',
        name: 'File Type Router',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [2784, 752],
    })
    FileTypeRouter = {
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
                                id: 'word-doc-condition',
                                leftValue: '={{ (() => { const b = $("Before Start").item.binary.data || {}; const m = String(b.mimeType || "").toLowerCase().split(";")[0].trim(); if (m && m !== "application/octet-stream") return m; const n = String(b.fileName || "").toLowerCase(); if (n.endsWith(".pdf")) return "application/pdf"; if (/\\.jpe?g$/.test(n)) return "image/jpeg"; if (n.endsWith(".png")) return "image/png"; if (n.endsWith(".txt")) return "text/plain"; if (n.endsWith(".csv")) return "text/csv"; if (n.endsWith(".xlsx")) return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"; if (n.endsWith(".xls")) return "application/vnd.ms-excel"; return m || "application/octet-stream"; })() }}',
                                rightValue: 'text/plain',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'Text',
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
                                id: '2cd928a5-7364-4d43-8ff5-89ea6407ad38',
                                leftValue: '={{ (() => { const b = $("Before Start").item.binary.data || {}; const m = String(b.mimeType || "").toLowerCase().split(";")[0].trim(); if (m && m !== "application/octet-stream") return m; const n = String(b.fileName || "").toLowerCase(); if (n.endsWith(".pdf")) return "application/pdf"; if (/\\.jpe?g$/.test(n)) return "image/jpeg"; if (n.endsWith(".png")) return "image/png"; if (n.endsWith(".txt")) return "text/plain"; if (n.endsWith(".csv")) return "text/csv"; if (n.endsWith(".xlsx")) return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"; if (n.endsWith(".xls")) return "application/vnd.ms-excel"; return m || "application/octet-stream"; })() }}',
                                rightValue: 'text/csv',
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
                    outputKey: 'CSV',
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
                                id: 'excel-condition',
                                leftValue: '={{ (() => { const b = $("Before Start").item.binary.data || {}; const m = String(b.mimeType || "").toLowerCase().split(";")[0].trim(); if (m && m !== "application/octet-stream") return m; const n = String(b.fileName || "").toLowerCase(); if (n.endsWith(".pdf")) return "application/pdf"; if (/\\.jpe?g$/.test(n)) return "image/jpeg"; if (n.endsWith(".png")) return "image/png"; if (n.endsWith(".txt")) return "text/plain"; if (n.endsWith(".csv")) return "text/csv"; if (n.endsWith(".xlsx")) return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"; if (n.endsWith(".xls")) return "application/vnd.ms-excel"; return m || "application/octet-stream"; })() }}',
                                rightValue: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'GSheet',
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
                                id: 'e8209c9b-c736-44bf-a25f-5b1cd62f0d58',
                                leftValue: '={{ (() => { const b = $("Before Start").item.binary.data || {}; const m = String(b.mimeType || "").toLowerCase().split(";")[0].trim(); if (m && m !== "application/octet-stream") return m; const n = String(b.fileName || "").toLowerCase(); if (n.endsWith(".pdf")) return "application/pdf"; if (/\\.jpe?g$/.test(n)) return "image/jpeg"; if (n.endsWith(".png")) return "image/png"; if (n.endsWith(".txt")) return "text/plain"; if (n.endsWith(".csv")) return "text/csv"; if (n.endsWith(".xlsx")) return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"; if (n.endsWith(".xls")) return "application/vnd.ms-excel"; return m || "application/octet-stream"; })() }}',
                                rightValue: 'application/vnd.ms-excel',
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
                    outputKey: 'Excel',
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
                                leftValue: '={{ (() => { const b = $("Before Start").item.binary.data || {}; const m = String(b.mimeType || "").toLowerCase().split(";")[0].trim(); if (m && m !== "application/octet-stream") return m; const n = String(b.fileName || "").toLowerCase(); if (n.endsWith(".pdf")) return "application/pdf"; if (/\\.jpe?g$/.test(n)) return "image/jpeg"; if (n.endsWith(".png")) return "image/png"; if (n.endsWith(".txt")) return "text/plain"; if (n.endsWith(".csv")) return "text/csv"; if (n.endsWith(".xlsx")) return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"; if (n.endsWith(".xls")) return "application/vnd.ms-excel"; return m || "application/octet-stream"; })() }}',
                                rightValue: 'image/jpeg',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                                id: 'jpeg-condition',
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'JPEG',
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
                                leftValue: '={{ (() => { const b = $("Before Start").item.binary.data || {}; const m = String(b.mimeType || "").toLowerCase().split(";")[0].trim(); if (m && m !== "application/octet-stream") return m; const n = String(b.fileName || "").toLowerCase(); if (n.endsWith(".pdf")) return "application/pdf"; if (/\\.jpe?g$/.test(n)) return "image/jpeg"; if (n.endsWith(".png")) return "image/png"; if (n.endsWith(".txt")) return "text/plain"; if (n.endsWith(".csv")) return "text/csv"; if (n.endsWith(".xlsx")) return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"; if (n.endsWith(".xls")) return "application/vnd.ms-excel"; return m || "application/octet-stream"; })() }}',
                                rightValue: 'image/png',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                                id: 'png-condition',
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'PNG',
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
                                id: 'pdf-condition',
                                leftValue: '={{ (() => { const b = $("Before Start").item.binary.data || {}; const m = String(b.mimeType || "").toLowerCase().split(";")[0].trim(); if (m && m !== "application/octet-stream") return m; const n = String(b.fileName || "").toLowerCase(); if (n.endsWith(".pdf")) return "application/pdf"; if (/\\.jpe?g$/.test(n)) return "image/jpeg"; if (n.endsWith(".png")) return "image/png"; if (n.endsWith(".txt")) return "text/plain"; if (n.endsWith(".csv")) return "text/csv"; if (n.endsWith(".xlsx")) return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"; if (n.endsWith(".xls")) return "application/vnd.ms-excel"; return m || "application/octet-stream"; })() }}',
                                rightValue: 'application/pdf',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'PDF',
                },
            ],
        },
        options: {
            fallbackOutput: 'extra',
        },
    };

    @node({
        id: '5fc8262d-6860-4f81-91a0-5df1d7d7641e',
        name: 'API Response',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1,
        position: [5744, 1024],
    })
    ApiResponse = {
        respondWith: 'json',
        responseBody: '={{ $json }}',
        options: {},
    };

    @node({
        id: '31d60122-277c-4723-b7c4-7f4809740f1c',
        name: 'Textual Input',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [3360, 512],
    })
    TextualInput = {};

    @node({
        id: 'e2c22349-8efb-43da-91ee-4a30c0569dc4',
        name: 'Extract from File',
        /*__n8n__*/ notes: "CSV here is windows-1255 Hebrew and contains bare quotes inside unquoted fields (בע\"מ). relaxQuotes stops csv-parse aborting the file; latin1 is byte-preserving so 'Decode CSV Text' can recover the real CP1255 text.",
        /*__n8n__*/ notesInFlow: false,
        type: 'n8n-nodes-base.extractFromFile',
        version: 1,
        position: [3040, 512],
    })
    ExtractFromFile = {
        options: {
            relaxQuotes: true,
            encoding: 'latin1',
        },
    };

    @node({
        id: '1c98500a-8baf-49cb-9d4f-ed4218b82b77',
        name: 'Code',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3200, 592],
    })
    Code = {
        jsCode: `// Loop over input items and add a new field called 'myNewField' to the JSON of each one
const allData = {};
let i = 0;
for (const item of $input.all()) {
  i += 1;
  allData["line_" + i] = item.json;
  // Object.assign(allData, item.json);
}

return [{
  json: allData
}];`,
    };

    @node({
        id: '1a2ce0ee-fb72-43f9-a7ae-38bda3dafec3',
        name: 'Sticky Note',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [1568, 368],
    })
    StickyNote = {
        content: '# Cache Check',
        height: 384,
        width: 1008,
        color: 4,
    };

    @node({
        id: '7fade8d7-2e21-4fc9-b62d-f121439a1de4',
        name: 'Extract from File1',
        type: 'n8n-nodes-base.extractFromFile',
        version: 1,
        position: [3040, 336],
    })
    ExtractFromFile1 = {
        operation: 'text',
        binaryPropertyName: 'data',
        destinationKey: 'data',
        options: {},
    };

    @node({
        id: '40696eb0-375b-4dba-b7f6-bc76bdf3c6bb',
        name: 'Extract from File2',
        type: 'n8n-nodes-base.extractFromFile',
        version: 1,
        position: [3040, 672],
        onError: 'continueErrorOutput',
    })
    ExtractFromFile2 = {
        operation: 'xlsx',
        binaryPropertyName: 'data',
        options: {},
    };

    @node({
        id: '0ca303a8-86ad-4933-acf6-708e2550774f',
        name: 'Response Format: Unsupported File Error',
        type: 'n8n-nodes-base.function',
        version: 1,
        position: [4720, 960],
    })
    ResponseFormatUnsupportedFileError = {
        functionCode: `// Handle unsupported file formats
const mimeType = items[0].binary?.data?.mimeType || "unknown";
const fileName = items[0].binary?.data?.fileName || "unknown";

return [{
  json: {
    success: false,
    error: "Unsupported file format",
    details: \`File type '\${mimeType}' is not supported. Supported formats: PDF, Word (.docx), Excel (.xlsx), JPEG, PNG\`,
    fileName: fileName,
    mimeType: mimeType,
    processedAt: new Date().toISOString(),
    // [completion contract 2026-08-13] AN ACTION THAT CANNOT SUCCEED MUST STILL RECORD THAT IT RAN.
    // Returning success:false without a completion flag makes the execution look SUCCESSFUL to n8n
    // while leaving PER_TYPE_EXTRACTION_COMPLETED unset, so Decide GDoc/Shipment re-dispatches this
    // document on every sweep with no error ever surfacing. Measured before this landed: 761 runs
    // (39.3% of 1,934) dead-ended on these two branches across only 37 documents, ~20 futile
    // retries each, and 1,934 executions covered just 179 distinct documents (90.7% redundant).
    // The gate closes because the work IS finished -- there is nothing further to extract from this
    // file -- and ERROR carries the reason so the row reads as failed, not as silently complete.
    PER_TYPE_EXTRACTION_COMPLETED: true,
    ERROR: 'unsupported_file_format'
  }
}];`,
    };

    @node({
        id: '267e539f-3bae-4b5f-ae0b-e00f00594cd1',
        name: 'Crypto',
        type: 'n8n-nodes-base.crypto',
        version: 1,
        position: [1616, 528],
    })
    Crypto = {
        binaryData: true,
        dataPropertyName: 'cached_input_key',
    };

    @node({
        id: '71da29ea-ba0f-4873-af17-595c82c07c77',
        name: 'KVStorage',
        /*__n8n__*/ notes: "Cache HIT only if the stored entry COVERS every field this call asked for. Rows written before fields_v existed default to all 7 -- true for every extraction ever run here (3,697/3,697 prompts on 2026-08-10 asked for all 7), so no legacy row turns into a miss and no extra Gemini call is bought by this change.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [1792, 512],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    Kvstorage = {
        operation: 'executeQuery',
        query: '=SELECT COALESCE((SELECT json_agg(value::json) FROM ai_extraction_cache WHERE cache_key = $$invoice:{{ $json.cached_input_key }}$$ AND COALESCE((value::jsonb) -> \'fields_v\', $$["AI_COMPANY_ID","AI_DOC_AMOUNT","AI_DOC_DATE","AI_DOC_ID","AI_ORDER_IDS","AI_SHIPMENT_IDS","AI_TYPE"]$$::jsonb) @> $${{ JSON.stringify($(\'Resolve Fields\').first().json.requested_fields) }}$$::jsonb), \'[]\'::json) AS val',
        options: {},
    };

    @node({
        id: '67c9687b-94f1-46bc-b9ff-7b85a04944a1',
        name: 'KVStorage1',
        /*__n8n__*/ notes: "MERGE, not clobber. Only the fields this run actually asked for (fields_v) overwrite the stored data; every other field keeps the value a previous run proved. fields_v is stored as the union, so coverage only ever grows. The old 'SET value = EXCLUDED.value' let a narrower extraction erase a wider one's answers.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [5968, 768],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    Kvstorage1 = {
        operation: 'executeQuery',
        query: "=INSERT INTO ai_extraction_cache (cache_key, kind, value) VALUES ($$invoice:{{ $('Start').first().json.cached_input_key }}$$, $$invoice$$, $${{ JSON.stringify(Object.assign({}, $json, { fields_v: $('Resolve Fields').first().json.requested_fields })) }}$$) ON CONFLICT (cache_key) DO UPDATE SET value = ((EXCLUDED.value::jsonb) || jsonb_build_object('data', COALESCE((ai_extraction_cache.value::jsonb) -> 'data', '{}'::jsonb) || COALESCE((SELECT jsonb_object_agg(s.k, s.v) FROM (SELECT t.k AS k, ((EXCLUDED.value::jsonb) -> 'data') -> t.k AS v FROM jsonb_array_elements_text(COALESCE((EXCLUDED.value::jsonb) -> 'fields_v', '[]'::jsonb)) AS t(k)) s WHERE s.v IS NOT NULL), '{}'::jsonb), 'fields_v', COALESCE((SELECT jsonb_agg(DISTINCT f ORDER BY f) FROM jsonb_array_elements_text(COALESCE((ai_extraction_cache.value::jsonb) -> 'fields_v', '[\"AI_COMPANY_ID\",\"AI_DOC_AMOUNT\",\"AI_DOC_DATE\",\"AI_DOC_ID\",\"AI_ORDER_IDS\",\"AI_SHIPMENT_IDS\",\"AI_TYPE\"]'::jsonb) || COALESCE((EXCLUDED.value::jsonb) -> 'fields_v', '[]'::jsonb)) AS t2(f)), '[]'::jsonb)))::text",
        options: {},
    };

    @node({
        id: '3889af3c-c5ce-4553-a17a-81e0d7d74d4d',
        name: 'End',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [5504, 784],
    })
    End = {};

    @node({
        id: 'cae0c891-3085-427e-885f-32479b7afee0',
        name: 'Before Start',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [1072, 832],
    })
    BeforeStart = {};

    @node({
        id: 'g6resolvefields0001',
        name: 'Resolve Fields',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1200, 832],
    })
    ResolveFields = {
        jsCode: `// [g6 2026-08-10] ONE canonical answer to "which fields did THIS call ask for", computed on the
// single node BOTH downstream branches descend from -- the cache gate (If1 -> Crypto -> KVStorage)
// and the prompt builder (Config1 -> Load V3 Config (AI) -> Build Prompt From Queries). Before
// this, only the prompt knew the field set and the cache did not, so an entry produced for one
// field set was served verbatim to a caller that had asked for a different one: a silent blank,
// never a miss. Putting the parse HERE, once, is what makes the two halves unable to disagree --
// 'Build Prompt From Queries' now reads this value instead of re-deriving it.
//
// MEASURED 2026-08-10, not inferred: FIELDS does not currently reach this workflow on the webhook
// path at all -- 'MAP LINK1' is a Set node with options:{} (no "include other input fields"), so it
// forwards only LINK / use_cache / full_response, and the request body's FIELDS is discarded before
// 'Switch'. The one executeWorkflow caller (BaseDocEx01) sends FIELDS:"". Proof from production
// execution data over 2026-08-10 17:15-19:12Z: of 3,697 extractor executions that built a prompt,
// 3,697 contained all seven **AI_*** markers -- ZERO partial prompts. So \`wanted\` is ALL for every
// call today and this node changes no behaviour now; it makes the cache self-describing so that
// restoring FIELDS forwarding (another lane's call to make) cannot poison it later.
const ALL = ['AI_COMPANY_ID','AI_DOC_AMOUNT','AI_DOC_DATE','AI_DOC_ID','AI_ORDER_IDS','AI_SHIPMENT_IDS','AI_TYPE'];

let raw = '';
// executeWorkflow transport: FIELDS is a declared workflow input. A named lookback to a trigger that
// did not fire THROWS ("hasn't been executed"), so the webhook path MUST fall through the catch.
try { raw = ($('When Executed by Another Workflow').first().json.FIELDS || '').toString().trim(); } catch (e) {}
// webhook transport: inert today (MAP LINK1 drops FIELDS), correct the moment it stops dropping it.
if (!raw) { try { raw = (($input.first().json || {}).FIELDS || '').toString().trim(); } catch (e) {} }

let wanted;
try {
  const parsed = raw ? (raw.startsWith('[') ? JSON.parse(raw) : raw.split(',')) : [];
  const norm = (Array.isArray(parsed) ? parsed : [])
    .map(f => String(f).trim().toUpperCase())
    .filter(f => f.length > 0)
    .map(f => f.indexOf('AI_') === 0 ? f : 'AI_' + f)
    .filter(f => ALL.indexOf(f) >= 0);
  // an empty or entirely-unrecognised FIELDS means ALL 7 -- fail OPEN to a full extraction, never
  // to a narrower one, so a typo can only cost a little money, never silently drop a field.
  wanted = norm.length ? norm : ALL;
} catch (e) { wanted = ALL; }

// CANONICAL FORM: de-duplicated + sorted, so "TYPE,COMPANY_ID" and "COMPANY_ID,TYPE" are the SAME
// request to both the @> containment gate in KVStorage and the fields_v stamp in KVStorage1.
wanted = Array.from(new Set(wanted)).sort();

return $input.all().map(it => ({
  json: Object.assign({}, it.json, { requested_fields: wanted }),
  binary: it.binary,
  pairedItem: it.pairedItem,
}));
`,
    };

    @node({
        id: 'b3c01bf2-13e4-49d7-b1c3-5b911a48b3c0',
        name: 'Start',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [2544, 848],
    })
    Start = {};

    @node({
        id: 'c0bd3725-4c0f-4153-853a-2e467d628dfb',
        name: 'API Response1',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1,
        position: [2384, 432],
    })
    ApiResponse1 = {
        respondWith: 'json',
        responseBody: '={{ $json }}',
        options: {},
    };

    @node({
        id: 'c65d9441-a27b-4ca3-9c13-c81e8c14728a',
        name: 'If',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [1952, 528],
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
                    id: '30391b3a-9b77-4a8a-9004-56c86cb2328a',
                    leftValue: '={{ $input.item.json?.val[0] }}',
                    rightValue: '',
                    operator: {
                        type: 'object',
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
        id: '2e0428d6-2cbc-4e47-8cc9-2645492ce3a3',
        name: 'Code2',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2384, 624],
    })
    Code2 = {
        mode: 'runOnceForEachItem',
        jsCode: `return {
  "json": {
    "cached_input_key": $('Crypto').item.json.cached_input_key
  },
  "binary": $("Before Start").item.binary
}`,
    };

    @node({
        id: '9616211b-1a41-4e5a-925e-365b793d86c4',
        name: 'Sticky Note2',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [4480, 512],
    })
    StickyNote2 = {
        content: '# Prepare Response',
        height: 656,
        width: 544,
        color: 2,
    };

    @node({
        id: '07bcc383-70b8-4db3-b185-db30acb7558f',
        name: 'Sticky Note6',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [5296, 704],
    })
    StickyNote6 = {
        content: '# Cache Set',
        height: 224,
        width: 464,
        color: 4,
    };

    @node({
        id: '027eb084-cce6-405e-a191-f7fae7790f8c',
        name: 'If1',
        /*__n8n__*/ notesInFlow: false,
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [1456, 832],
    })
    If1 = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: 'eea89e5c-53d2-47c6-b259-0ce0eee65e2d',
                    leftValue: '={{ $json.use_cache}}',
                    rightValue: false,
                    operator: {
                        type: 'boolean',
                        operation: 'notEquals',
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: 'a337c705-08fd-4011-b28c-36978f535ee0',
        name: 'When Executed by Another Workflow',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [-208, 1056],
    })
    WhenExecutedByAnotherWorkflow = {
        workflowInputs: {
            values: [
                {
                    name: 'LINK',
                },
                {
                    name: 'use_cache',
                    type: 'boolean',
                },
                {
                    name: 'FIELDS',
                },
                {
                    name: 'LINK_CONNECTION',
                },
                {
                    name: '__instance',
                },
            ],
        },
    };

    @node({
        id: 'd21cec96-1397-4a3e-80f4-5bc48ec50667',
        name: 'Switch',
        type: 'n8n-nodes-base.switch',
        version: 3.3,
        position: [256, 1040],
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
                                leftValue: '={{ $binary }}',
                                rightValue: '',
                                operator: {
                                    type: 'object',
                                    operation: 'notEmpty',
                                    singleValue: true,
                                },
                                id: 'e8da54be-a09f-43e1-9bc5-0d9bbf76e518',
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'binary',
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
                                id: 'ab565658-14a3-4a04-90fe-9ee67f27888c',
                                leftValue: '={{ !!$json.LINK }}',
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
                    renameOutput: true,
                    outputKey: 'link',
                },
            ],
        },
        options: {
            fallbackOutput: 'extra',
        },
    };

    @node({
        id: 'fec1b314-59fa-4773-a25d-b456c5fde724',
        name: 'Download LINK',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [592, 1056],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    DownloadLink = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'download',
                params: '={{ ({ fileId: $json.LINK, fileIdMode: "url", connection_id: $json.LINK_CONNECTION }) }}',
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
            convertFieldsToString: true,
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'c951712a-4a74-47d0-9fc7-63b20da2820d',
        name: 'If Binary',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [784, 1056],
    })
    IfBinary = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: '8551a8b2-ce2b-4f77-912a-8cdbece9d709',
                    leftValue: '={{ $binary }}',
                    rightValue: '',
                    operator: {
                        type: 'object',
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
        id: 'f3a3e61f-c363-4080-b6ff-de6caf96ef4e',
        name: 'Code in JavaScript',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1056, 1072],
    })
    CodeInJavascript = {
        jsCode: `// Failure report for a download that produced no binary. Do NOT forward the input items:
// on the webhook path they carry a nested \`json\` key and re-emitting them fails with
// "Invalid output format" -- the one branch that must REPORT failure crashed instead of
// reporting it (measured on every bad-link doc once this branch became reachable).
// [g2 2026-08-11] This node was itself a dead end -- correct payload, no outgoing
// connection -- so the report never reached a respond node and the caller saw HTTP 200
// with an empty body. Now wired to \`End\`. Fields aligned with the other failure reports;
// \`error\` deliberately unchanged, it is a contract string consumers already match on.
return [{
  json: {
    success: false,
    error: 'failed_to_get_gd_link',
    details: 'Download LINK returned no binary for the supplied link',
    needs_review: true,
    processedAt: new Date().toISOString(),
  },
}];
`,
    };

    @node({
        id: 'e134ac75-25a4-43f5-a92f-dcea1ec268dd',
        name: 'Code in JavaScript1',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2160, 432],
    })
    CodeInJavascript1 = {
        jsCode: `for (const item of $input.all()) {
  item.json = item.json.val[0] || {};
}

return $input.all();`,
    };

    @node({
        id: 'd328ec89-6618-4287-911f-15140740aab1',
        name: 'MAP LINK',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [-208, 1312],
    })
    MapLink = {
        assignments: {
            assignments: [
                {
                    id: '37f1c08b-d334-4c58-a5e8-1b3cdd4b207e',
                    name: 'LINK',
                    value: '={{ $json.GDRIVE_LINK }}',
                    type: 'string',
                },
                {
                    id: '41af91b8-f273-48eb-8a50-afa497b5a1ac',
                    name: 'use_cache',
                    value: false,
                    type: 'boolean',
                },
                {
                    id: 'lc-map-link',
                    name: 'LINK_CONNECTION',
                    value: '={{ $json.LINK_CONNECTION }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '4cd47531-d4b8-47a6-80f8-27ead961f7fd',
        name: 'If Success',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [5744, 784],
    })
    IfSuccess = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: '223f1807-7549-49b0-881d-7d5e6facff81',
                    leftValue: '={{ $json.success }}',
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
        id: 'b45fd12f-6aca-4534-a44b-4a4dccb01366',
        name: 'CONFIG',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1280, 576],
    })
    Config = {
        assignments: {
            assignments: [
                {
                    id: '04ce5540-a4e3-42c4-bc5c-0c34cbcd02cf',
                    name: 'prompt',
                    value: '={{ $json.prompt }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '834413da-e727-429f-bb1b-28efa5215055',
        name: 'Google Gemini Chat Model',
        type: '@n8n/n8n-nodes-langchain.lmChatGoogleGemini',
        version: 1,
        position: [3728, 240],
        credentials: { googlePalmApi: { id: '6mfcsdRaqQ4IdQ8Y', name: 'ai-studio-bs-extraction [env-managed]' } },
    })
    GoogleGeminiChatModel = {
        modelName: 'models/gemini-3.1-pro-preview',
        options: {},
    };

    @node({
        id: 'e05337c0-5b61-45d7-8f5c-296864ceed2f',
        name: 'Document Processor',
        type: '@n8n/n8n-nodes-langchain.googleGemini',
        version: 1,
        position: [3296, 816],
        credentials: { googlePalmApi: { id: '6mfcsdRaqQ4IdQ8Y', name: 'ai-studio-bs-extraction [env-managed]' } },
        onError: 'continueErrorOutput',
        retryOnFail: true,
        maxTries: 3,
    })
    DocumentProcessor = {
        resource: 'document',
        modelId: {
            __rl: true,
            value: 'models/gemini-3.1-pro-preview',
            mode: 'list',
            cachedResultName: 'models/gemini-3.1-pro-preview',
        },
        text: '={{ $("CONFIG").last().json.prompt }}',
        inputType: 'binary',
        options: {},
    };

    @node({
        id: 'd2baeff7-4841-4e1b-a136-f6f52051fe14',
        name: 'Text Processor',
        type: '@n8n/n8n-nodes-langchain.googleGemini',
        version: 1,
        position: [3504, 528],
        credentials: { googlePalmApi: { id: '6mfcsdRaqQ4IdQ8Y', name: 'ai-studio-bs-extraction [env-managed]' } },
        retryOnFail: true,
        maxTries: 3,
    })
    TextProcessor = {
        modelId: {
            __rl: true,
            value: 'models/gemini-3-flash-preview',
            mode: 'list',
            cachedResultName: 'models/gemini-3-flash-preview',
        },
        messages: {
            values: [
                {
                    content: '={{ $("CONFIG").last().json.prompt }}',
                    role: 'model',
                },
                {
                    content: '=textxtual fileinput: {{ JSON.stringify( $json )}}',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '6523cf82-575e-4711-91c6-581b24c73d40',
        name: 'Config1',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1312, 416],
        executeOnce: true,
    })
    Config1 = {
        jsCode: `for (const item of $input.all()) {
  item.json.json_schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "JSON_INVOICE_EXTRACTION",
    "type": "object",
    "description": "Extraction of required fields from a business document.",
    "additionalProperties": false,
    "properties": {
      "AI_COMPANY_ID": {
        "type": "string",
        "description": "The company identification number or VAT number. Ignore 515561520 / הכהנים חומרי בניין בע\\"מ."
      },
      "AI_DOC_AMOUNT": {
        "type": "string",
        "description": "The total amount of the document including VAT (סה\\"כ כולל מע\\"מ / סכום כולל / סה\\"כ לתשלום / לתשלום). Do NOT confuse with order number. IMPORTANT: If the document is a credit note (חשבונית זיכוי or any similar credit indication), always return the amount as a NEGATIVE number."
      },
      "AI_DOC_DATE": {
        "type": "string",
        "description": "The date of the document in DD/MM/YYYY format. Preference: 1. תאריך הפקה, 2. תאריך חשבונית, 3. תאריך מסמך, 4. תאריך. Do NOT use payment date."
      },
      "AI_DOC_ID": {
        "type": "string",
        "description": "The full document number. Preference: 1. חשבונית מס, 2. מס' חשבונית, 3. מסמך, 4. מספר מסמך, 5. מסמך חיוב."
      },
      "AI_ORDER_IDS": {
        "type": "string",
        "description": "Purchase Order ID (מספר הזמנת לקוח, הזמנת רכש, etc.). If multiple, extract only the first."
      },
      "AI_SHIPMENT_IDS": {
        "type": "array",
        "items": {
          "type": "string"
        },
        "uniqueItems": true,
        "description": "Array of unique linked shipment document numbers (מספר תעודת משלוח / ת. משלוח). If not found, use an empty array."
      },
      "AI_TYPE": {
        "type": "string",
        "enum": ["INVOICE", "SHIPMENT", "BALANCE_SHEET", "ORDER", "RECEIPT", "IRRELEVANT"],
        "description": "Document classification based on guidelines."
      }
    },
    "required": [
      "AI_COMPANY_ID",
      "AI_DOC_AMOUNT",
      "AI_DOC_DATE",
      "AI_DOC_ID",
      "AI_ORDER_IDS",
      "AI_SHIPMENT_IDS",
      "AI_TYPE"
    ]
  };
}

return $input.all();`,
    };

    @node({
        id: '0fe60c09-aa10-4841-b6a3-5b6c222d7eaa',
        name: 'Map Response',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [4720, 592],
    })
    MapResponse = {
        assignments: {
            assignments: [
                {
                    id: 'df08253d-0222-4aa7-8fea-581221d8be2c',
                    name: 'data',
                    value: '={{ $json.data }}',
                    type: 'object',
                },
                {
                    id: '7f276377-3f35-441a-ba8d-7a63c21b182b',
                    name: 'success',
                    value: '={{ $json.success }}',
                    type: 'boolean',
                },
                {
                    id: '2d9b8e06-4afe-481a-8369-0115210121fe',
                    name: 'processedAt',
                    value: '={{ $json.processedAt }}',
                    type: 'string',
                },
                {
                    id: '3a4c0b6a-5c97-4e2e-9eeb-0a0187f1ff13',
                    name: 'evalMetadata',
                    value: "={{ $('Start').last().json.full_response ? $json.evalMetadata : {} }}",
                    type: 'object',
                },
                {
                    id: '522bc164-f726-4087-9013-f6933b67f350',
                    name: 'fullResponse',
                    value: "={{ $('Start').last().json.full_response ? $json : {} }}",
                    type: 'object',
                },
            ],
        },
        options: {
            ignoreConversionErrors: false,
        },
    };

    @node({
        id: 'd701e3eb-5e7c-40cc-81c3-103e4bdd2cdd',
        name: 'Extract Response',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [3792, 576],
    })
    ExtractResponse = {
        assignments: {
            assignments: [
                {
                    id: 'extract-content',
                    name: 'content',
                    value: '={{ $json.content.parts[0].text }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'd72a8499-1f81-450d-9e17-1dd5d7c1973e',
        name: 'Parse JSON Response',
        type: 'n8n-nodes-base.function',
        version: 1,
        position: [3952, 592],
    })
    ParseJsonResponse = {
        functionCode: `const raw = items[0].json.content;
const jsonText = raw.replace(/^\`\`\`json\\n/, '').replace(/\\n\`\`\`$/, '');

try {
  const parsed = JSON.parse(jsonText);
  return [{ json: parsed }];
} catch (error) {
  // Return error response for invalid JSON
  return [{
    json: {
      error: "Failed to parse AI response as JSON",
      rawResponse: raw,
      parseError: error.message
    }
  }];
}`,
    };

    @node({
        id: 'eb0f76d2-b1c8-4372-afcb-130741dc3e77',
        name: 'Format Response',
        type: 'n8n-nodes-base.function',
        version: 1,
        position: [4112, 592],
    })
    FormatResponse = {
        functionCode: `const item = items[0].json;

// במקרה של שגיאת פענוח
if (item.error) {
  return[{
    json: {
      success: false,
      error: item.error,
      details: item.parseError || "Unknown parsing error"
    }
  }];
}

// קריאת המערך של תעודות המשלוח, ובמידה וריק יוגדר כמערך ריק
let shipmentIdsRaw = Array.isArray(item.AI_SHIPMENT_IDS) ? item.AI_SHIPMENT_IDS :[];
// מחיקת כפילויות ליתר ביטחון למקרה שהמודל טעה
let uniqueShipmentIds =[...new Set(shipmentIdsRaw)];

// סידור הנתונים שחזרו למבנה התקין בהתאם להגדרות החדשות
const response = {
  success: true,
  data: {
    AI_COMPANY_ID: item.AI_COMPANY_ID || "",
    AI_DOC_ID: item.AI_DOC_ID || "",
    AI_DOC_DATE: item.AI_DOC_DATE || "",
    AI_DOC_AMOUNT: item.AI_DOC_AMOUNT || "",
    AI_SHIPMENT_IDS: uniqueShipmentIds, // כאן הוכנס המערך המסונן
    AI_ORDER_IDS: item.AI_ORDER_IDS || "",
    AI_TYPE: item.AI_TYPE || ""
  },
  processedAt: new Date().toISOString()
};

return[{ json: response }];`,
    };

    @node({
        id: 'e9f55d73-0449-4f4b-afdf-b2d1e06260b5',
        name: 'Response Format: No LLM Output',
        type: 'n8n-nodes-base.function',
        version: 1,
        position: [4720, 784],
    })
    ResponseFormatNoLlmOutput = {
        functionCode: `// Handle unsupported file formats
const mimeType = items[0].binary?.data?.mimeType || "unknown";
const fileName = items[0].binary?.data?.fileName || "unknown";

return [{
  json: {
    success: false,
    error: "LLM Faild",
    details: \`Faild getting output from llm.\`,
    fileName: fileName,
    mimeType: mimeType,
    processedAt: new Date().toISOString(),
    // [completion contract 2026-08-13] AN ACTION THAT CANNOT SUCCEED MUST STILL RECORD THAT IT RAN.
    // Returning success:false without a completion flag makes the execution look SUCCESSFUL to n8n
    // while leaving PER_TYPE_EXTRACTION_COMPLETED unset, so Decide GDoc/Shipment re-dispatches this
    // document on every sweep with no error ever surfacing. Measured before this landed: 761 runs
    // (39.3% of 1,934) dead-ended on these two branches across only 37 documents, ~20 futile
    // retries each, and 1,934 executions covered just 179 distinct documents (90.7% redundant).
    // The gate closes because the work IS finished -- there is nothing further to extract from this
    // file -- and ERROR carries the reason so the row reads as failed, not as silently complete.
    PER_TYPE_EXTRACTION_COMPLETED: true,
    ERROR: 'llm_no_output'
  }
}];`,
    };

    @node({
        id: 'f04f9eb0-b235-4360-bcc1-bed2446e0ac0',
        name: 'MAP LINK1',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [16, 912],
    })
    MapLink1 = {
        assignments: {
            assignments: [
                {
                    id: '37f1c08b-d334-4c58-a5e8-1b3cdd4b207e',
                    name: 'LINK',
                    value: '={{ $json.body.LINK }}',
                    type: 'string',
                },
                {
                    id: '41af91b8-f273-48eb-8a50-afa497b5a1ac',
                    name: 'use_cache',
                    value: '={{ $json.body.use_cache || true }}',
                    type: 'boolean',
                },
                {
                    id: 'bc93fbae-3f3e-4522-bfb4-1e2af2b75f64',
                    name: 'full_response',
                    value: '={{ $json.body.full_response || false }}',
                    type: 'boolean',
                },
                {
                    id: 'lc-map-link1',
                    name: 'LINK_CONNECTION',
                    value: '={{ $json.body.LINK_CONNECTION }}',
                    type: 'string',
                },
                {
                    id: 'inst-map-link1',
                    name: '__instance',
                    value: '={{ $json.body.__instance || $json.body.instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '2e58f32c-1a56-4a71-a67e-0289f95eddeb',
        name: 'When clicking ‘Execute workflow’',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [-560, 1536],
    })
    WhenClickingExecuteWorkflow = {};

    @node({
        id: '9624fc38-9ae2-436e-9b16-e4b23d10cea4',
        name: 'Delete Cache',
        type: 'n8n-nodes-kv-storage.kvStorage',
        version: 1,
        position: [-288, 1536],
    })
    DeleteCache = {
        operation: 'setValue',
        key: '={{ "c565df33c7194f72ce2395956c771695" }}',
    };

    @node({
        id: '7723729d-6060-4115-8014-bc2ff8bbb180',
        name: 'HTTP Request',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.3,
        position: [3344, 1040],
        credentials: { googleApi: { id: 'wxbv5yj5lnKDuvmN', name: 'Document AI Connection [env-managed]' } },
    })
    HttpRequest = {
        method: 'POST',
        url: 'https://us-documentai.googleapis.com/v1/projects/928205450024/locations/us/processors/55409bca20033969/processorVersions/fb6558662229489c:process',
        authentication: 'predefinedCredentialType',
        nodeCredentialType: 'googleApi',
        sendBody: true,
        contentType: 'json',
        bodyParameters: {
            parameters: [
                {
                    name: 'rawDocument.mimeType',
                    value: '={{ $binary.data.mimeType }}',
                },
                {
                    name: '=rawDocument.content',
                    value: '={{ $json.fileBase64 }}',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '8cf86dcd-1a6e-49f1-a5bd-0b3ce6a61b19',
        name: 'Code in JavaScript2',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3536, 1040],
    })
    CodeInJavascript2 = {
        jsCode: `// שולפים את כל הפריטים שהגיעו מ-Google Document AI
const items = $input.all();

return items.map(item => {
  const entities = item.json.document.entities || [];

  const extractedData = {
    COMPANY_ID: "",
    SHIPMENT_DOC_ID: "",
    DOC_TOTAL_AMOUNT: "",
    DOC_DATE: "",
    PURCHASE_ID: ""
  };

  for (const entity of entities) {
    const type = entity.type;
    const value = entity.mentionText || "";

    if (extractedData[type] !== undefined) {
      extractedData[type] = value;
    }
  }

  return {
    json: {
      success: true,
      data: extractedData,
      processedAt: new Date().toISOString()
    }
  };
});`,
    };

    @node({
        id: '81b1b59b-3940-45a9-b1df-922190266faf',
        name: 'Code in JavaScript3',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3152, 1040],
    })
    CodeInJavascript3 = {
        jsCode: `const items = $input.all();

for (let i = 0; i < items.length; i++) {
  // בודקים שיש בכלל קובץ בינארי
  if (items[i].binary && items[i].binary.data) {
    // שולפים את הקובץ מהזיכרון/דיסק של n8n
    const buffer = await this.helpers.getBinaryDataBuffer(i, 'data');
    // ממירים אותו ל-Base64 ושומרים בתוך שדה חדש ב-JSON
    items[i].json.fileBase64 = buffer.toString('base64');
  }
}

return items;`,
    };

    @node({
        id: 'b369d56f-76c8-45eb-b28e-44215da06b52',
        name: 'Start1',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [2992, 896],
    })
    Start1 = {};

    @node({
        id: 'd1deaaa7-c200-40ef-9c91-3bedb1394a1c',
        name: 'End2',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [5744, 1232],
    })
    End2 = {};

    @node({
        id: 'ai-kill-switch-check-01',
        name: 'Check AI Enabled Setting',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [32, 1088],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    CheckAiEnabledSetting = {
        operation: 'executeQuery',
        query: "=SELECT COALESCE((SELECT value FROM {{ (() => { let i = String($json.__instance || ''); if (!i) { try { i = String(($('When Executed by Another Workflow').first().json || {}).__instance || ''); } catch (e) { i = ''; } } if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2ExtractInvoiceGemini01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.settings WHERE key='extraction_ai_enabled'), 'true') AS ai_enabled",
        options: {},
    };

    @node({
        id: 'ai-kill-switch-if-01',
        name: 'If AI Disabled',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [272, 1168],
    })
    IfAiDisabled = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: 'ai-kill-switch-cond-01',
                    leftValue: '={{ $json.ai_enabled }}',
                    rightValue: 'false',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: 'ai-kill-switch-response-01',
        name: 'API Response - AI Disabled',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1,
        position: [512, 1168],
    })
    ApiResponseAiDisabled = {
        respondWith: 'json',
        responseBody:
            '={{ { success: true, ai_disabled: true, data: { AI_COMPANY_ID: "", AI_DOC_AMOUNT: "", AI_DOC_DATE: "", AI_DOC_ID: "", AI_ORDER_IDS: "", AI_SHIPMENT_IDS: [], AI_TYPE: "" } } }}',
        options: {},
    };

    @node({
        id: 'ai-load-v3-config-01',
        name: 'Load V3 Config (AI)',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [1312, 992],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    LoadV3ConfigAi = {
        operation: 'executeQuery',
        query: `=-- SINGLE SOURCE. extraction_queries (schema.sql) returns each q_v3_*
-- settings row with every @registry_* sentinel already substituted from the
-- companies table, so this node no longer builds a registry of its own and
-- there is exactly one definition of "what the company option lists are".
-- 'Fan Fields' keeps its bindRegistry pass as an ASSERT: after this query no
-- sentinel should survive, and if one does it throws instead of sending the
-- literal string "@registry_ids" to apitools as a silent-green no-match.
select coalesce(jsonb_object_agg(key, query), '{}'::jsonb) as cfg
  from {{ (() => { let i = String($json.__instance || ''); if (!i) { try { i = String(($('When Executed by Another Workflow').first().json || {}).__instance || ''); } catch (e) { i = ''; } } if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2ExtractInvoiceGemini01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.extraction_queries`,
        options: {},
    };

    @node({
        id: 'ai-build-prompt-from-queries-01',
        name: 'Build Prompt From Queries',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1552, 992],
    })
    BuildPromptFromQueries = {
        jsCode: `// Build Prompt From Queries -- the AI prompt's WHERE-TO-LOOK instructions are
// compiled from the SAME q_v3_* settings rows JQExV3Base000001/Invoice001 use
// for local extraction (q_v3_routing.base + q_v3_routing.invoice), not a
// second, hand-maintained keyword list -- one definition per value, per the
// owner's design ('ai just maps the local ex as prompt to what value where
// looking for so we manage only the local json query per value'). What
// CANNOT be derived from a local query (output JSON shape, credit-note sign
// flip, excluding our own company) stays static prose below -- those are
// business rules a local query object has no field for.

const cfg = ($('Load V3 Config (AI)').first().json.cfg) || {};
const routing = cfg.q_v3_routing || {};
const base = routing.base || {};
const invoice = routing.invoice || {};

function isLabelish(arr) {
  return Array.isArray(arr) && arr.length > 0 && arr.every(v => typeof v === 'string' && !/^\\d+$/.test(v));
}
function labelsFromQuery(q) {
  const out = [];
  (function walk(node) {
    if (!node || typeof node !== 'object') return;
    if (isLabelish(node.action_value)) out.push(...node.action_value);
    if (Array.isArray(node.fallbacks)) node.fallbacks.forEach(walk);
  })(q);
  return [...new Set(out)];
}
function typeReturnsFromQuery(q) {
  const out = [];
  (function walk(node) {
    if (!node || typeof node !== 'object') return;
    if (node.returns && isLabelish(node.action_value)) out.push(\`\${String(node.returns).toUpperCase()}: \${node.action_value.join(', ')}\`);
    if (Array.isArray(node.fallbacks)) node.fallbacks.forEach(walk);
  })(q);
  return out;
}
function excludeNearFromQuery(q) {
  const out = [];
  (function walk(node) {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node.exclude_near)) out.push(...node.exclude_near);
    if (Array.isArray(node.fallbacks)) node.fallbacks.forEach(walk);
  })(q);
  return [...new Set(out)];
}
function hintLine(label, key, category) {
  const qk = category[key];
  const q = qk ? cfg[qk] : null;
  if (!q) return \`(no \${key} query configured in settings -- falling back to general judgement)\`;
  const labels = labelsFromQuery(q);
  return labels.length ? \`look for a value following/near one of these labels (from the local query definition, q_v3_\${qk.replace('q_v3_','')}): \${labels.join(', ')}\` : '(query configured but has no label list -- use general judgement)';
}

const companyExclude = excludeNearFromQuery(cfg[base.COMPANY_ID] || {});
const typeHints = typeReturnsFromQuery(cfg[base.TYPE] || {});

// which fields this call was asked for. [g6 2026-08-10] SINGLE SOURCE: 'Resolve Fields' (the one
// node both this branch and the cache branch descend from) already parsed FIELDS into a canonical,
// sorted, de-duplicated list. Reading it here instead of re-parsing the trigger is what guarantees
// the prompt and the cache gate cannot disagree about the field set -- a second parser is exactly
// how a cached 3-field object came to be handed to a 5-field caller. Default stays ALL 7, so any
// caller that passes no FIELDS (all of them, today) is unaffected.
const ALL = ['AI_COMPANY_ID','AI_DOC_AMOUNT','AI_DOC_DATE','AI_DOC_ID','AI_ORDER_IDS','AI_SHIPMENT_IDS','AI_TYPE'];
let wanted;
try { wanted = $('Resolve Fields').first().json.requested_fields; } catch (e) {}
if (!Array.isArray(wanted) || !wanted.length) wanted = ALL;
const want = (f) => wanted.includes(f);

const items = [];
if (want('AI_COMPANY_ID')) items.push(
  \`**AI_COMPANY_ID**: The company identification number or VAT number (e.g., \` +
  \`\\u05e2\\u05d5\\u05e1\\u05e7 \\u05de\\u05d5\\u05e8\\u05e9\\u05d4, \\u05d7.\\u05e4, \\u05de\\u05e1\\u05e4\\u05e8 \\u05ea\\u05d0\\u05d2\\u05d9\\u05d3) of the issuing company. \` +
  \`CRITICAL: Do NOT extract or use our own company's VAT number/name\` +
  (companyExclude.length ? \` (excluded, from the local query's own exclude_near list: \${companyExclude.join(', ')})\` : '') +
  \`. This is the recipient's ID and must be completely ignored. If not found, use "".\`
);
if (want('AI_DOC_AMOUNT')) items.push(
  \`**AI_DOC_AMOUNT**: The total amount of the document including VAT -- \${hintLine('amount', 'DOC_TOTAL_AMOUNT', invoice)}. \` +
  \`Return amounts as strings. CRITICAL: Do NOT confuse the total amount with the order number. If not found, use "". \` +
  \`IMPORTANT: If the document is a credit note (\\u05d7\\u05e9\\u05d1\\u05d5\\u05e0\\u05d9\\u05ea \\u05d6\\u05d9\\u05db\\u05d5\\u05d9 / credit note / credit memo or any similar credit indication), \` +
  \`the amount MUST always be returned as a NEGATIVE number (e.g., "-1500.00"), regardless of how it appears in the document.\`
);
if (want('AI_DOC_DATE')) items.push(
  \`**AI_DOC_DATE**: The date of the document in DD/MM/YYYY format -- \${hintLine('date', 'DOC_DATE', base)}. \` +
  \`Do NOT use the payment date or the pay-by date. If not found, use "".\`
);
if (want('AI_DOC_ID')) items.push(
  \`**AI_DOC_ID**: The full document number -- \${hintLine('doc id', 'INVOICE_ID', invoice)}. If not found, use "".\`
);
if (want('AI_ORDER_IDS')) items.push(
  \`**AI_ORDER_IDS**: Purchase Order ID -- \${hintLine('order id', 'PURCHASE_ID', invoice)}. \` +
  \`Extract the purchase order number as it appears in the CUSTOMER's records, not the issuer's internal reference. \` +
  \`If multiple, extract only the first. If not found, use "".\`
);
if (want('AI_SHIPMENT_IDS')) items.push(
  \`**AI_SHIPMENT_IDS**: The linked shipment document numbers -- \${hintLine('shipment id', 'SHIPMENT_ID', invoice)}. \` +
  \`Extract all unique shipment numbers and return them as an array of strings. If not found, return an empty array [].\`
);
if (want('AI_TYPE')) items.push(
  \`**AI_TYPE**: Identify the type of the document and classify it into exactly one of: INVOICE, SHIPMENT, BALANCE_SHEET, ORDER, RECEIPT, IRRELEVANT.\` +
  (typeHints.length ? \` Local-query classification cues (from q_v3_type, the same signal the local classifier uses): \${typeHints.join(' | ')}.\` : '') +
  \` If the document is a financial balance sheet (including screenshots), return BALANCE_SHEET.\` +
  // [RECEIPT 2026-08-27] The one distinction the local query cannot express, so it is stated
  // here: an Israeli combined tax-invoice-receipt IS an invoice. Only a standalone payment
  // acknowledgement -- no tax-invoice line items -- is a RECEIPT. Same split the anchor order
  // in q_v3_type enforces, where the 'heshbonit mas' rule is evaluated before the receipt rule.
  \` A document titled with a combined tax-invoice/receipt heading is an INVOICE, not a RECEIPT; return RECEIPT only for a standalone payment confirmation that itemises no tax-invoice charges. If irrelevant, return IRRELEVANT.\`
);

const shape = {};
for (const f of wanted) {
  shape[f] = f === 'AI_SHIPMENT_IDS' ? '["string"] | []' : (f === 'AI_TYPE' ? '"INVOICE" | "SHIPMENT" | "BALANCE_SHEET" | "ORDER" | "RECEIPT" | "IRRELEVANT"' : '"string" | ""');
}

const prompt =
\`You are an expert accounting assistant. The provided file is a business document, typically an invoice, receipt, or related document.

Extract the strictly required fields below from the document based on these guidelines:

\${items.map((t, i) => \`\${i + 1}. \${t}\`).join('\\n')}

Strictly return ONLY the JSON object with the following structure. Do not use null values; use an empty string "" for missing string values. Do not include any explanations, apologies, or conversational text outside of the JSON structure. Ensure that any double quotes that are part of the string data itself are properly escaped with a backslash.

\${JSON.stringify(shape, null, 2)}\`;

return [{ json: { prompt, requested_fields: wanted } }];
`,
    };

    @node({
        id: 'g2guardbytes000001',
        name: 'Check Doc Bytes',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3152, 896],
    })
    CheckDocBytes = {
        jsCode: `// [g2 2026-08-09] Do not hand Gemini something that is not a document.
// 18 of the window's 82 errors were this node's upstream: SIX stub fixtures with forged
// extensions -- a 0-byte \`unknown-unknown.jpg\` and 32-39 byte "PDFs" whose entire content is one
// line of ASCII like \`sv3f mixed mail attachment 99464\` -- each retried 3x. Google answered
// 400 INVALID_ARGUMENT for the tiny PDFs and 404 NOT_FOUND for the empty JPEG (its File resource
// never materialises). It was never quota and never auth: the same credential and the same
// models/gemini-3.1-pro-preview succeeded 507 times in the same three-hour window, including on
// a 9.21 MB scan. A file this size cannot be a document under any encoding, so the call is pure
// cost and the refusal is knowable here, locally, before spending it.
//
// [g5 2026-08-10] THE SIZE PROBE WAS READING THE STORAGE-MODE MARKER AS THE DOCUMENT.
// This n8n runs with filesystem-backed binary data, and in that mode an item's \`binary.data.data\`
// is NOT base64 -- it is the literal string "filesystem-v2" (13 chars), with the real payload
// behind \`binary.data.id\` and the true size already on the item as \`bytes\` (integer) and
// \`fileSize\` ("82.4 kB"). The old order tested \`b.data\` FIRST, so floor(13 * 3 / 4) = 9 was
// returned for every single document and the guard rejected all of them as "9 bytes".
// Measured, not inferred: over a 90-minute window, 1073 of 1073 documents that reached this node
// were rejected -- true sizes min 33 B, median 840 kB, max 1.8 MB -- Gemini was called 0 times,
// nothing was ever written to ai_extraction_cache (only 4 new rows in 4 hours against 4,356
// extractor executions), and because a \`success:false\` never reaches 'If Success'/KVStorage1 the
// same documents re-entered the gate every sweep: 17.2 extractor executions per document.
// Fix = ask n8n for the size it already knows, and only measure base64 for a genuinely in-memory
// item (one with no \`id\` reference). The stub fixtures above are still caught: they carry
// bytes 0 / 35 / 39 and fall below MIN_BYTES on their real size, not on a marker's length.
const MIN_BYTES = 1024;

function bytesOf(b) {
  if (!b) return 0;
  // 1. exact size, present on every filesystem-backed item
  if (typeof b.bytes === 'number' && isFinite(b.bytes)) return b.bytes;
  // 2. formatted size ("35 B", "82.4 kB", "9.21 MB")
  const m = String(b.fileSize || '').match(/^([\\d.]+)\\s*(B|KB|MB|GB)?$/i);
  if (m) {
    const mult = { B: 1, KB: 1024, MB: 1048576, GB: 1073741824 }[(m[2] || 'B').toUpperCase()];
    return Math.round(parseFloat(m[1]) * mult);
  }
  // 3. only now may \`data\` be base64 -- and only when the item is really in memory.
  //    An item with an \`id\` is a reference; its \`data\` is the storage-mode marker.
  if (!b.id && typeof b.data === 'string' && b.data) return Math.floor(b.data.length * 3 / 4);
  // 4. size unknowable -> fail OPEN (isNaN is treated as ok below), never block a real document.
  return NaN;
}

return $input.all().map(it => {
  const b = (it.binary || {}).data;
  const n = bytesOf(b);
  const ok = !b ? false : (isNaN(n) ? true : n >= MIN_BYTES);
  return {
    json: Object.assign({}, it.json, {
      _doc_bytes: isNaN(n) ? null : n,
      _doc_bytes_ok: ok,
      _doc_reject_reason: ok ? null
        : (!b ? 'no binary on the item'
             : 'document is ' + n + ' bytes (min ' + MIN_BYTES + ') - not a real document'),
    }),
    binary: it.binary,
    pairedItem: it.pairedItem,
  };
});
`,
    };

    @node({
        id: 'g2ifbytes00000001',
        name: 'Doc Bytes OK?',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [3312, 896],
    })
    DocBytesOk = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'g2condbytes00001',
                    leftValue: '={{ $json._doc_bytes_ok }}',
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
        id: 'g2reportunusable01',
        name: 'Report Unusable Document',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3472, 1086],
    })
    ReportUnusableDocument = {
        jsCode: `// [g2 2026-08-09] The honest terminal state for a document Gemini was never asked about.
// Mirrors the shape of 'Response Format: No LLM Output' so every consumer of this workflow keeps
// reading the same fields. \`error\` is deliberately NOT 'LLM Faild': the LLM was not called, and
// blaming it would send the next reader to the wrong place. needs_review, because a document that
// arrives as 35 bytes is an ingest fault a human must look at -- not something a retry can fix
// (all 18 of these had already burned three API round-trips each proving that).
return $input.all().map(it => ({
  json: {
    success: false,
    error: 'unusable_document',
    details: it.json._doc_reject_reason || 'document failed the pre-AI size check',
    needs_review: true,
    bytes: it.json._doc_bytes === undefined ? null : it.json._doc_bytes,
    fileName: ((it.binary || {}).data || {}).fileName || 'unknown',
    mimeType: ((it.binary || {}).data || {}).mimeType || 'unknown',
    processedAt: new Date().toISOString(),
  },
}));
`,
    };

    @node({
        id: 'b1e7c4a2-9f30-4d61-8c55-2a7d61f0aa11',
        name: 'Report Missing Link',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [592, 1296],
    })
    ReportMissingLink = {
        jsCode: `// [g2 2026-08-11] The Switch fallback (\`fallbackOutput: "extra"\`) used to be an unconnected
// dead end. A request whose body carried no usable LINK matched neither rule -- no $binary,
// and !!$json.LINK false -- so the execution finished 'success' having never reached a respond
// node, and the caller got HTTP 200 with an EMPTY body. Measured 2026-08-10: 180 of 582
// successful webhook extractions ended here, 179 of them without even running Download LINK.
// indoxV2ActionsGlobal01 read that {} as a result and wrote AI_COMPANY_ID / AI_DOC_ID /
// AI_DOC_DATE / AI_DOC_AMOUNT / AI_SHIPMENT_IDS / AI_ORDER_IDS / AI_TYPE all NULL with
// AI_EXTRACTION_COMPLETED 'true' -- a silent wrong answer, which is worse than a loud failure.
// Do NOT forward the input items: on the webhook path they carry a nested \`json\` key and
// re-emitting them fails with "Invalid output format" (the same trap 'Code in JavaScript' hit).
// Shape mirrors 'Report Unusable Document' / 'Response Format: No LLM Output' so every consumer
// of this workflow keeps reading the same fields.
return $input.all().map(it => {
  const j = it.json || {};
  return {
    json: {
      success: false,
      error: 'missing_link',
      details: 'request matched no Switch route: no binary attached and no usable LINK in the body',
      needs_review: true,
      LINK: j.LINK === undefined || j.LINK === '' ? null : j.LINK,
      processedAt: new Date().toISOString(),
    },
  };
});
`,
    };

    @node({
        id: 'c5d1255a-0000-4000-8000-00000000c515',
        name: 'Decode CSV Text',
        /*__n8n__*/ notes: "CP1255 -> Unicode. CSV branch only; the XLSX branch is already Unicode.",
        /*__n8n__*/ notesInFlow: true,
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3120, 448],
    })
    DecodeCsvText = {
        jsCode: `// CP1255 -> Unicode for the CSV branch.
//
// WHY THIS NODE EXISTS
// The Sonol/Hebrew CSV exports this pipeline receives are windows-1255 (CP1255), not UTF-8:
// the bytes f7 e5 e3 are "קוד", which is not valid UTF-8 at all. n8n's Extract from File can
// only decode Node buffer encodings (ascii/latin1/ucs2/utf8) -- windows-1255 is not offered --
// so decoding as UTF-8 turned every Hebrew character into U+FFFD. That silently destroyed the
// header row and every Hebrew value before the AI ever saw them.
//
// So Extract from File is set to \`latin1\`, which is byte-PRESERVING: byte 0xNN becomes codepoint
// U+00NN, losing nothing. This node recovers those bytes and decodes them properly: real UTF-8
// when the file really was UTF-8 (4 of the 15 CSVs in the corpus are), CP1255 otherwise.
//
// It sits only on the CSV branch. The XLSX branch feeds the same downstream Code node but arrives
// as proper Unicode already, so it must NOT pass through here.

const HIGH = {
  0x80: '€', 0x82: '‚', 0x83: 'ƒ', 0x84: '„', 0x85: '…', 0x86: '†', 0x87: '‡',
  0x88: 'ˆ', 0x89: '‰', 0x8b: '‹', 0x91: '‘', 0x92: '’', 0x93: '“', 0x94: '”',
  0x95: '•', 0x96: '–', 0x97: '—', 0x98: '˜', 0x99: '™', 0x9b: '›', 0xa0: ' ',
  0xa1: '¡', 0xa2: '¢', 0xa3: '£', 0xa4: '₪', 0xa5: '¥', 0xa6: '¦', 0xa7: '§',
  0xa8: '¨', 0xa9: '©', 0xaa: '×', 0xab: '«', 0xac: '¬', 0xad: '­', 0xae: '®',
  0xaf: '¯', 0xb0: '°', 0xb1: '±', 0xb2: '²', 0xb3: '³', 0xb4: '´', 0xb5: 'µ',
  0xb6: '¶', 0xb7: '·', 0xb8: '¸', 0xb9: '¹', 0xba: '÷', 0xbb: '»', 0xbc: '¼',
  0xbd: '½', 0xbe: '¾', 0xbf: '¿', 0xd3: 'װ', 0xd4: 'ױ', 0xd5: 'ײ', 0xd6: '׳',
  0xd7: '״', 0xfd: '‎', 0xfe: '‏',
};

function cp1255(buf) {
  let out = '';
  for (const b of buf) {
    if (b < 0x80) out += String.fromCharCode(b);
    else if (b >= 0xe0 && b <= 0xfa) out += String.fromCharCode(0x05d0 + (b - 0xe0)); // א..ת
    else if (b >= 0xc0 && b <= 0xd2) out += String.fromCharCode(0x05b0 + (b - 0xc0)); // niqqud
    else out += HIGH[b] !== undefined ? HIGH[b] : '�';
  }
  return out;
}

function decode(s) {
  const buf = Buffer.from(s, 'latin1');
  // A lossless UTF-8 decode re-encodes to the identical bytes; a wrong one does not.
  if (Buffer.compare(Buffer.from(buf.toString('utf8'), 'utf8'), buf) === 0) return buf.toString('utf8');
  return cp1255(buf);
}

return $input.all().map((item, i) => {
  const out = {};
  for (const [k, v] of Object.entries(item.json)) {
    out[decode(k)] = typeof v === 'string' ? decode(v) : v;
  }
  return { json: out, pairedItem: item.pairedItem !== undefined ? item.pairedItem : { item: i } };
});
`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WebhookTrigger.out(0).to(this.MapLink1.in(0));
        this.FileTypeRouter.out(0).to(this.ExtractFromFile1.in(0));
        this.FileTypeRouter.out(1).to(this.ExtractFromFile.in(0));
        this.FileTypeRouter.out(2).to(this.ExtractFromFile2.in(0));
        this.FileTypeRouter.out(3).to(this.ExtractFromFile2.in(0));
        this.FileTypeRouter.out(4).to(this.Start1.in(0));
        this.FileTypeRouter.out(5).to(this.Start1.in(0));
        this.FileTypeRouter.out(6).to(this.Start1.in(0));
        this.FileTypeRouter.out(7).to(this.ResponseFormatUnsupportedFileError.in(0));
        this.TextualInput.out(0).to(this.TextProcessor.in(0));
        this.ExtractFromFile.out(0).to(this.DecodeCsvText.in(0));
        this.Code.out(0).to(this.TextualInput.in(0));
        this.ExtractFromFile1.out(0).to(this.TextualInput.in(0));
        this.ExtractFromFile2.out(0).to(this.Code.in(0));
        this.ExtractFromFile2.out(1).to(this.ResponseFormatUnsupportedFileError.in(0));
        this.ResponseFormatUnsupportedFileError.out(0).to(this.End.in(0));
        this.Crypto.out(0).to(this.Kvstorage.in(0));
        this.End.out(0).to(this.ApiResponse.in(0));
        this.End.out(0).to(this.IfSuccess.in(0));
        this.End.out(0).to(this.End2.in(0));
        this.BeforeStart.out(0).to(this.ResolveFields.in(0));
        this.Kvstorage.out(0).to(this.If_.in(0));
        this.Start.out(0).to(this.FileTypeRouter.in(0));
        this.If_.out(0).to(this.CodeInJavascript1.in(0));
        this.If_.out(1).to(this.CheckAiEnabledSetting.in(0));
        this.Code2.out(0).to(this.Start.in(0));
        this.If1.out(0).to(this.Crypto.in(0));
        this.If1.out(1).to(this.Start.in(0));
        this.WhenExecutedByAnotherWorkflow.out(0).to(this.Switch_.in(0));
        this.Switch_.out(0).to(this.BeforeStart.in(0));
        this.Switch_.out(1).to(this.DownloadLink.in(0));
        this.Switch_.out(2).to(this.ReportMissingLink.in(0));
        this.DownloadLink.out(0).to(this.IfBinary.in(0));
        this.IfBinary.out(0).to(this.BeforeStart.in(0));
        this.IfBinary.out(1).to(this.CodeInJavascript.in(0));
        this.CodeInJavascript1.out(0).to(this.ApiResponse1.in(0));
        this.MapLink.out(0).to(this.Switch_.in(0));
        this.IfSuccess.out(0).to(this.Kvstorage1.in(0));
        this.MapResponse.out(0).to(this.End.in(0));
        this.ExtractResponse.out(0).to(this.ParseJsonResponse.in(0));
        this.ParseJsonResponse.out(0).to(this.FormatResponse.in(0));
        this.ResponseFormatNoLlmOutput.out(0).to(this.End.in(0));
        this.MapLink1.out(0).to(this.Switch_.in(0));
        this.WhenClickingExecuteWorkflow.out(0).to(this.DeleteCache.in(0));
        this.DocumentProcessor.out(0).to(this.ExtractResponse.in(0));
        this.DocumentProcessor.out(1).to(this.ResponseFormatNoLlmOutput.in(0));
        this.FormatResponse.out(0).to(this.MapResponse.in(0));
        this.TextProcessor.out(0).to(this.ExtractResponse.in(0));
        this.HttpRequest.out(0).to(this.CodeInJavascript2.in(0));
        this.CodeInJavascript3.out(0).to(this.HttpRequest.in(0));
        this.Start1.out(0).to(this.CheckDocBytes.in(0));
        this.CheckAiEnabledSetting.out(0).to(this.IfAiDisabled.in(0));
        this.IfAiDisabled.out(0).to(this.ApiResponseAiDisabled.in(0));
        this.IfAiDisabled.out(1).to(this.Code2.in(0));
        this.LoadV3ConfigAi.out(0).to(this.BuildPromptFromQueries.in(0));
        this.BuildPromptFromQueries.out(0).to(this.Config.in(0));
        this.Config1.out(0).to(this.LoadV3ConfigAi.in(0));
        this.CheckDocBytes.out(0).to(this.DocBytesOk.in(0));
        this.DocBytesOk.out(0).to(this.DocumentProcessor.in(0));
        this.DocBytesOk.out(1).to(this.ReportUnusableDocument.in(0));
        this.ReportUnusableDocument.out(0).to(this.End.in(0));
        this.ResolveFields.out(0).to(this.Config1.in(0));
        this.ResolveFields.out(0).to(this.If1.in(0));
        this.ReportMissingLink.out(0).to(this.End.in(0));
        this.CodeInJavascript.out(0).to(this.End.in(0));
        this.DecodeCsvText.out(0).to(this.Code.in(0));
    }
}
