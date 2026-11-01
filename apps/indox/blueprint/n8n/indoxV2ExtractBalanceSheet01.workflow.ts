import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Balance Sheet Extractor - v2- shmuel
// Nodes   : 57  |  Connections: 59
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
// ExtractFromFile2                   extractFromFile
// ResponseFormatUnsupportedFileError function
// Crypto                             crypto
// Kvstorage                          postgres                   [creds]
// Kvstorage1                         postgres                   [creds]
// End                                noOp
// BeforeStart                        noOp
// Start                              noOp
// ApiResponse1                       respondToWebhook
// If_                                if
// Code2                              code
// StickyNote2                        stickyNote
// StickyNote6                        stickyNote
// StickyNote3                        stickyNote
// If1                                if
// WhenExecutedByAnotherWorkflow      executeWorkflowTrigger
// Switch_                            switch
// DownloadLink                       executeWorkflow            [onError→regular] [retry]
// IfBinary                           if
// CodeInJavascript                   code
// CodeInJavascript1                  code
// MapLink                            set
// EvalStart                          evaluationTrigger
// StickyNote9                        stickyNote
// Evaluation1                        evaluation
// IfSuccess                          if
// IfEvalRun                          if
// Config                             set
// DocumentProcessor                  googleGemini               [creds] [retry]
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
// TextProcessor1                     googleGemini               [creds] [retry]
// DocumentOcr                        httpRequest                [retry]
// CodeInJavascript2                  code
// If2                                if
// CodeInPythonNative                 code
// Start1                             noOp
// Config11                           set
// CallSettings                       executeWorkflow            [executeOnce]
// If3                                if                         [onError→regular]
// ConfigFinal                        set
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WebhookTrigger
//    → MapLink1
//      → Switch_
//        → BeforeStart
//          → If1
//            → Crypto
//              → Kvstorage
//                → If_
//                  → CodeInJavascript1
//                    → ApiResponse1
//                 .out(1) → Code2
//                    → Start
//                      → FileTypeRouter
//                        → ExtractFromFile1
//                          → TextualInput
//                            → TextProcessor1
//                              → ExtractResponse
//                                → ParseJsonResponse
//                                  → FormatResponse
//                                    → MapResponse
//                                      → End
//                                        → ApiResponse
//                                        → IfEvalRun
//                                          → Evaluation1
//                                        → IfSuccess
//                                          → Kvstorage1
//                       .out(1) → ExtractFromFile
//                          → Code
//                            → TextualInput (↩ loop)
//                       .out(2) → ExtractFromFile2
//                          → Code (↩ loop)
//                       .out(3) → ExtractFromFile2 (↩ loop)
//                       .out(4) → Start1
//                          → DocumentProcessor
//                            → ExtractResponse (↩ loop)
//                       .out(5) → Start1 (↩ loop)
//                       .out(6) → Start1 (↩ loop)
//                       .out(7) → ResponseFormatUnsupportedFileError
//                          → End (↩ loop)
//           .out(1) → Start (↩ loop)
//          → CallSettings
//            → If3
//              → Config11
//                → Config
//                  → ConfigFinal
//             .out(1) → Config (↩ loop)
//          → Config1
//       .out(1) → DownloadLink
//          → IfBinary
//            → BeforeStart (↩ loop)
//           .out(1) → CodeInJavascript
//              → ApiResponse1 (↩ loop)
// WhenExecutedByAnotherWorkflow
//    → Switch_ (↩ loop)
// EvalStart
//    → MapLink
//      → Switch_ (↩ loop)
// ResponseFormatNoLlmOutput
//    → End (↩ loop)
// WhenClickingExecuteWorkflow
//    → DeleteCache
// DocumentOcr
//    → CodeInJavascript2
//      → If2
//        → CodeInPythonNative
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Webhook Trigger":{"main":[[{"node":"MAP LINK1","type":"main","index":0}]]},"File Type Router":{"main":[[{"node":"Extract from File1","type":"main","index":0}],[{"node":"Extract from File","type":"main","index":0}],[{"node":"Extract from File2","type":"main","index":0}],[{"node":"Extract from File2","type":"main","index":0}],[{"node":"Start1","type":"main","index":0}],[{"node":"Start1","type":"main","index":0}],[{"node":"Start1","type":"main","index":0}],[{"node":"Response Format: Unsupported File Error","type":"main","index":0}]]},"Textual Input":{"main":[[{"node":"Text Processor1","type":"main","index":0}]]},"Extract from File":{"main":[[{"node":"Code","type":"main","index":0}]]},"Code":{"main":[[{"node":"Textual Input","type":"main","index":0}]]},"Extract from File1":{"main":[[{"node":"Textual Input","type":"main","index":0}]]},"Extract from File2":{"main":[[{"node":"Code","type":"main","index":0}]]},"Response Format: Unsupported File Error":{"main":[[{"node":"End","type":"main","index":0}]]},"Crypto":{"main":[[{"node":"KVStorage","type":"main","index":0}]]},"KVStorage":{"main":[[{"node":"If","type":"main","index":0}]]},"End":{"main":[[{"node":"API Response","type":"main","index":0},{"node":"If Eval Run","type":"main","index":0},{"node":"If Success","type":"main","index":0}]]},"Before Start":{"main":[[{"node":"If1","type":"main","index":0},{"node":"Call 'Settings'","type":"main","index":0},{"node":"Config1","type":"main","index":0}]]},"Start":{"main":[[{"node":"File Type Router","type":"main","index":0}]]},"If":{"main":[[{"node":"Code in JavaScript1","type":"main","index":0}],[{"node":"Code2","type":"main","index":0}]]},"Code2":{"main":[[{"node":"Start","type":"main","index":0}]]},"If1":{"main":[[{"node":"Crypto","type":"main","index":0}],[{"node":"Start","type":"main","index":0}]]},"When Executed by Another Workflow":{"main":[[{"node":"Switch","type":"main","index":0}]]},"Switch":{"main":[[{"node":"Before Start","type":"main","index":0}],[{"node":"Download LINK","type":"main","index":0}]]},"Download LINK":{"main":[[{"node":"If Binary","type":"main","index":0}]]},"If Binary":{"main":[[{"node":"Before Start","type":"main","index":0}],[{"node":"Code in JavaScript","type":"main","index":0}]]},"Code in JavaScript1":{"main":[[{"node":"API Response1","type":"main","index":0}]]},"MAP LINK":{"main":[[{"node":"Switch","type":"main","index":0}]]},"Eval Start":{"main":[[{"node":"MAP LINK","type":"main","index":0}]]},"If Success":{"main":[[{"node":"KVStorage1","type":"main","index":0}]]},"If Eval Run":{"main":[[{"node":"Evaluation1","type":"main","index":0}]]},"Map Response":{"main":[[{"node":"End","type":"main","index":0}]]},"Extract Response":{"main":[[{"node":"Parse JSON Response","type":"main","index":0}]]},"Parse JSON Response":{"main":[[{"node":"Format Response","type":"main","index":0}]]},"Response Format: No LLM Output":{"main":[[{"node":"End","type":"main","index":0}]]},"MAP LINK1":{"main":[[{"node":"Switch","type":"main","index":0}]]},"When clicking ‘Execute workflow’":{"main":[[{"node":"Delete Cache","type":"main","index":0}]]},"Document Processor":{"main":[[{"node":"Extract Response","type":"main","index":0}]]},"Text Processor1":{"main":[[{"node":"Extract Response","type":"main","index":0}]]},"Format Response":{"main":[[{"node":"Map Response","type":"main","index":0}]]},"Document OCR":{"main":[[{"node":"Code in JavaScript2","type":"main","index":0}]]},"Code in JavaScript2":{"main":[[{"node":"If2","type":"main","index":0}]]},"If2":{"main":[[{"node":"Code in Python (Native)","type":"main","index":0}],[]]},"Start1":{"main":[[{"node":"Document Processor","type":"main","index":0}]]},"Code in Python (Native)":{"main":[[]]},"Call 'Settings'":{"main":[[{"node":"If3","type":"main","index":0}]]},"If3":{"main":[[{"node":"CONFIG1","type":"main","index":0}],[{"node":"CONFIG","type":"main","index":0}]]},"CONFIG1":{"main":[[{"node":"CONFIG","type":"main","index":0}]]},"CONFIG":{"main":[[{"node":"CONFIG FINAL","type":"main","index":0}]]},"Code in JavaScript":{"main":[[{"node":"API Response1","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"b1a4e768-96a2-4b15-958d-950999027b09","name":"indox-dev"},{"updatedAt":"2026-07-30T23:41:29.646Z","createdAt":"2026-07-30T23:41:29.646Z","id":"9c337cfe-7feb-4f3d-ab26-3de6439357ce","name":"sm-refactore-v2.1"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"38de779e-63ee-415a-94f7-63c0ca2a68ac","name":"dev"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"22f1e71e-91bf-48db-811f-8d3bc4e55a3e","name":"sm-refactor-v2.1"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-31T00:59:54.840Z","createdAt":"2026-07-31T00:59:54.840Z","role":"workflow:owner","workflowId":"indoxV2ExtractBalanceSheet01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2ExtractBalanceSheet01',
    name: 'Balance Sheet Extractor - v2- shmuel',
    active: true,
    isArchived: false,
    tags: ['app:indox', 'indox-dev', 'sm-refactore-v2.1', 'dev', 'indox-app', 'sm-refactor-v2.1'],
    settings: {
        errorWorkflow: 'errorHandler01',
        executionOrder: 'v1',
        callerPolicy: 'workflowsFromSameOwner',
        availableInMCP: false,
    },
})
export class BalanceSheetExtractorV2ShmuelWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'eaf10a59-9b9f-4e30-a7af-99b7c48b13d0',
        webhookId: 'a33c7ec8-c766-4d68-b05b-008d6e1027eb',
        name: 'Webhook Trigger',
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [-672, 880],
        credentials: { httpBasicAuth: { id: 'azPhHBvOWaf9IsEA', name: 'Incoming Documents [env-managed]' } },
    })
    WebhookTrigger = {
        httpMethod: 'POST',
        path: 'bs_ex_2_dev',
        authentication: 'basicAuth',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: '34a054df-9a34-46d6-b18e-f310f5eaa0de',
        name: 'File Type Router',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [2800, 784],
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
                                leftValue:
                                    "={{ (function(){ const b = $('Before Start').item.binary.data; const mt = String(b.mimeType || ''); const fs = String(b.fileSize || ''); if (mt.includes('pdf') && fs.endsWith(' B') && parseInt(fs) > 0 && parseInt(fs) < 300) { return 'application/x-placeholder-not-a-pdf'; } return b.mimeType; })() }}",
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
                                leftValue:
                                    "={{ (function(){ const b = $('Before Start').item.binary.data; const mt = String(b.mimeType || ''); const fs = String(b.fileSize || ''); if (mt.includes('pdf') && fs.endsWith(' B') && parseInt(fs) > 0 && parseInt(fs) < 300) { return 'application/x-placeholder-not-a-pdf'; } return b.mimeType; })() }}",
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
                                leftValue:
                                    "={{ (function(){ const b = $('Before Start').item.binary.data; const mt = String(b.mimeType || ''); const fs = String(b.fileSize || ''); if (mt.includes('pdf') && fs.endsWith(' B') && parseInt(fs) > 0 && parseInt(fs) < 300) { return 'application/x-placeholder-not-a-pdf'; } return b.mimeType; })() }}",
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
                                leftValue:
                                    "={{ (function(){ const b = $('Before Start').item.binary.data; const mt = String(b.mimeType || ''); const fs = String(b.fileSize || ''); if (mt.includes('pdf') && fs.endsWith(' B') && parseInt(fs) > 0 && parseInt(fs) < 300) { return 'application/x-placeholder-not-a-pdf'; } return b.mimeType; })() }}",
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
                                leftValue:
                                    "={{ (function(){ const b = $('Before Start').item.binary.data; const mt = String(b.mimeType || ''); const fs = String(b.fileSize || ''); if (mt.includes('pdf') && fs.endsWith(' B') && parseInt(fs) > 0 && parseInt(fs) < 300) { return 'application/x-placeholder-not-a-pdf'; } return b.mimeType; })() }}",
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
                                leftValue:
                                    "={{ (function(){ const b = $('Before Start').item.binary.data; const mt = String(b.mimeType || ''); const fs = String(b.fileSize || ''); if (mt.includes('pdf') && fs.endsWith(' B') && parseInt(fs) > 0 && parseInt(fs) < 300) { return 'application/x-placeholder-not-a-pdf'; } return b.mimeType; })() }}",
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
                                leftValue:
                                    "={{ (function(){ const b = $('Before Start').item.binary.data; const mt = String(b.mimeType || ''); const fs = String(b.fileSize || ''); if (mt.includes('pdf') && fs.endsWith(' B') && parseInt(fs) > 0 && parseInt(fs) < 300) { return 'application/x-placeholder-not-a-pdf'; } return b.mimeType; })() }}",
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
        id: '677a8a58-091d-4c93-ace5-ec86f15bccab',
        name: 'API Response',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1,
        position: [5344, 1168],
    })
    ApiResponse = {
        respondWith: 'json',
        responseBody: '={{ $json }}',
        options: {},
    };

    @node({
        id: '2445423f-e32b-4124-9488-c875d148d30e',
        name: 'Textual Input',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [3376, 544],
    })
    TextualInput = {};

    @node({
        id: '4a5b5f70-8212-46b6-8407-fecab92ab299',
        name: 'Extract from File',
        type: 'n8n-nodes-base.extractFromFile',
        version: 1,
        position: [3056, 544],
    })
    ExtractFromFile = {
        options: {},
    };

    @node({
        id: 'c5f168f7-2ec2-410f-91bf-a151100c9366',
        name: 'Code',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3216, 624],
    })
    Code = {
        jsCode: `const allData = {};
let i = 0;

for (const item of $input.all()) {
  i += 1;
  
  // תיקון "באג 1900" - מעבר על כל התאים בשורה
  for (const key in item.json) {
    const val = item.json[key];
    
    // זיהוי ערכים מספריים שמתאימים לטווח התאריכים של אקסל (שנות ה-2000 והלאה)
    if (typeof val === 'number' && val > 40000 && val < 60000) {
      // קיזוז המספר הסידורי (25569 ימים) והמרה לתאריך אמיתי
      const date = new Date((val - 25569) * 86400 * 1000);
      
      // התיקון החסר: שימוש ב-[0] כדי לחלץ אך ורק את התאריך
      item.json[key] = date.toISOString().split('T')[0]; 
    }
  }
  
  allData["line_" + i] = item.json;
}

return [{
  json: allData
}];`,
    };

    @node({
        id: '8c90f416-ee92-4af1-95ad-09496619250a',
        name: 'Sticky Note',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [1584, 400],
    })
    StickyNote = {
        content: '# Cache Check',
        height: 384,
        width: 1008,
        color: 4,
    };

    @node({
        id: '4aac49ce-8ef5-493c-8396-799d7087f03d',
        name: 'Extract from File1',
        type: 'n8n-nodes-base.extractFromFile',
        version: 1,
        position: [3056, 368],
    })
    ExtractFromFile1 = {
        operation: 'text',
        options: {},
    };

    @node({
        id: '72ac66dd-7c2d-47dd-88c6-77568f1893fb',
        name: 'Extract from File2',
        type: 'n8n-nodes-base.extractFromFile',
        version: 1,
        position: [3056, 704],
    })
    ExtractFromFile2 = {
        operation: 'xlsx',
        options: {
            readAsString: true,
        },
    };

    @node({
        id: '1b8fe4f7-5003-4ee2-9d4d-0dab1557f297',
        name: 'Response Format: Unsupported File Error',
        type: 'n8n-nodes-base.function',
        version: 1,
        position: [4736, 992],
    })
    ResponseFormatUnsupportedFileError = {
        functionCode: `// Handle unsupported file formats.
// [broken-pdf verdict 2026-08-17, owner order] A pdf-typed file can only reach this path via
// the File Type Router's placeholder gate (claimed PDF, byte-scale size = not a real PDF,
// e.g. the 28-byte sv3s test placeholders). Say THAT, not "pdf is unsupported".
const mimeType = items[0].binary?.data?.mimeType || "unknown";
const fileName = items[0].binary?.data?.fileName || "unknown";
const fileSize = items[0].binary?.data?.fileSize || "unknown size";

const isBrokenPdf = String(mimeType).includes("pdf");
return [{
  json: {
    success: false,
    error: isBrokenPdf ? "Broken PDF" : "Unsupported file format",
    details: isBrokenPdf
      ? \`PDF file is broken or empty (\${fileSize}) — not a valid PDF document, nothing can be extracted.\`
      : \`File type '\${mimeType}' is not supported. Supported formats: PDF, Word (.docx), Excel (.xlsx), JPEG, PNG\`,
    fileName: fileName,
    mimeType: mimeType,
    processedAt: new Date().toISOString()
  }
}];`,
    };

    @node({
        id: '12a8566d-f638-44eb-978b-2b7d85bb7b4a',
        name: 'Crypto',
        type: 'n8n-nodes-base.crypto',
        version: 1,
        position: [1632, 560],
    })
    Crypto = {
        binaryData: true,
        dataPropertyName: 'cached_input_key',
    };

    @node({
        id: '377b145c-d26a-4e79-9dd0-3a9264be0511',
        name: 'KVStorage',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [1808, 544],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    Kvstorage = {
        operation: 'executeQuery',
        query: "=SELECT COALESCE((SELECT value FROM ai_extraction_cache WHERE cache_key = $$bs:{{ $json.cached_input_key }}$$), '') AS bs_cached",
        options: {},
    };

    @node({
        id: '2596cd71-60d8-413b-a83d-5a402c1b705a',
        name: 'KVStorage1',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [5568, 800],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    Kvstorage1 = {
        operation: 'executeQuery',
        query: "=INSERT INTO ai_extraction_cache (cache_key, kind, value) VALUES ($$bs:{{ $('Crypto').first().json.cached_input_key }}$$, $$bs$$, $${{ JSON.stringify($json) }}$$) ON CONFLICT (cache_key) DO UPDATE SET value = EXCLUDED.value",
        options: {},
    };

    @node({
        id: 'bca0bc38-005f-4289-a626-6919951f401c',
        name: 'End',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [5104, 816],
    })
    End = {};

    @node({
        id: '5808a1d7-f5a8-421f-a0d0-7142b9a85a99',
        name: 'Before Start',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [544, 880],
    })
    BeforeStart = {};

    @node({
        id: 'd8da50be-c9c0-47ca-9a36-26518bf9382e',
        name: 'Start',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [2560, 880],
    })
    Start = {};

    @node({
        id: '35cc4269-b9c2-49ca-bf66-3694b95b4156',
        name: 'API Response1',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1,
        position: [2400, 464],
    })
    ApiResponse1 = {
        respondWith: 'json',
        responseBody: '={{ $json }}',
        options: {},
    };

    @node({
        id: '8f7ee812-e427-4761-8f5e-3b9ac13b009b',
        name: 'If',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [1968, 560],
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
                    leftValue: '={{ $json.bs_cached }}',
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
        id: '9f78f8d4-bd48-4e9b-b007-cda26b2a090d',
        name: 'Code2',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2400, 656],
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
        id: '0898ec14-f493-4a6d-8fb7-ad67600cf90e',
        name: 'Sticky Note2',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [4368, 560],
    })
    StickyNote2 = {
        content: '# Prepare Response',
        height: 656,
        width: 544,
        color: 2,
    };

    @node({
        id: '4bea3c14-cff8-46d4-aa6e-9de6f11d7f84',
        name: 'Sticky Note6',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [5312, 736],
    })
    StickyNote6 = {
        content: '# Cache Set',
        height: 224,
        width: 464,
        color: 4,
    };

    @node({
        id: 'df42776e-229f-41f0-9582-9d3f11a08c09',
        name: 'Sticky Note3',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [2720, 272],
    })
    StickyNote3 = {
        content: '# Balance Sheet Extraction',
        height: 1008,
        width: 1328,
    };

    @node({
        id: '60c85753-5b8a-46f4-9d57-30d26b71ca3e',
        name: 'If1',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [1312, 880],
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
        id: 'd19856c8-6611-4efb-ae9b-b06f45f6e14b',
        name: 'When Executed by Another Workflow',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [-752, 1088],
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
                    name: 'COMPANY_ID',
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
        id: 'fa2b34e7-cc7f-4365-bb92-208f65aa3ac6',
        name: 'Switch',
        type: 'n8n-nodes-base.switch',
        version: 3.3,
        position: [-208, 1072],
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
        id: '72401aeb-0a0d-475d-93af-82ec6cca4b67',
        name: 'Download LINK',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [128, 1088],
        onError: 'continueRegularOutput',
        retryOnFail: true,
        maxTries: 5,
        waitBetweenTries: 5000,
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
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: 'c56d38ff-6e63-4820-92f0-c951699fa38d',
        name: 'If Binary',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [320, 1088],
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
        id: 'a5c2d402-98a9-4f52-ad22-29cf6be562cc',
        name: 'Code in JavaScript',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [592, 1104],
    })
    CodeInJavascript = {
        jsCode: `// Download failed (driveApi01 returned {error} / no binary). PROPAGATE the REAL error instead of
// silently passing a broken item downstream (was: return $input.all() -> 'Invalid output format',
// and a hardcoded 'failed_to_get_gd_link' that masked the true cause -> misleading Gemini 400).
const it = $input.first();
const j = (it && it.json) || {};
const real = j.error || j.message || (j.data && j.data.error) || 'failed_to_get_gd_link';
return [{ json: {
  success: false,
  stage: 'drive_download',
  error: 'BS extraction failed at Drive download: ' + (typeof real === 'string' ? real : JSON.stringify(real)),
  ID: (j.ID != null ? j.ID : null),
  LINK: (j.LINK != null ? j.LINK : null),
} }];
`,
    };

    @node({
        id: '4af33b2e-e953-47f9-8d6c-d93869538145',
        name: 'Code in JavaScript1',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2176, 464],
    })
    CodeInJavascript1 = {
        jsCode: `for (const item of $input.all()) {
  try { item.json = JSON.parse(item.json.bs_cached); } catch (e) { item.json = {}; }
}
return $input.all();`,
    };

    @node({
        id: '1301ff52-d9a5-49b1-b5a1-ef308d3b82b7',
        name: 'MAP LINK',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [-512, 1344],
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
        id: '43e4dfaa-18f9-4baa-9771-731f39434e88',
        name: 'Eval Start',
        type: 'n8n-nodes-base.evaluationTrigger',
        version: 4.7,
        position: [-768, 1344],
    })
    EvalStart = {
        dataTableId: {
            __rl: true,
            value: 'E4fUDXr9nxDOv8o4',
            mode: 'list',
            cachedResultName: 'BALANCE_SHEET_EX_EVAL',
            cachedResultUrl: '/projects/EChUnhWXmjrEc3fG/datatables/E4fUDXr9nxDOv8o4',
        },
        filterRows: true,
        filters: {
            conditions: [
                {
                    keyName: 'RUN_COMPLETED',
                    condition: 'isFalse',
                },
            ],
        },
    };

    @node({
        id: '72a4f52e-df8e-4265-b165-1bd2e462f3bf',
        name: 'Sticky Note9',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [-176, -64],
    })
    StickyNote9 = {
        content: `# Next steps

Eval table: BALANCE_SHEET_EX_EVAL  - http://n8n:5678/projects/EChUnhWXmjrEc3fG/datatables/E4fUDXr9nxDOv8o4

##  Complete evaluation setup
- put the currect  Expected values in the eval table (where missing)
- add a few failing balance sheets from incoming documents to eval table, and enter the expected values 
- change RUN_COMPLETED to false for all lines that need to rerun 

-- Run Current prompt 
- run this workflow from "Start Eval" trigger, let it finish, go over results.


-- Develop Refined Prompt 
- write a new prompt that works for all example 
- rerun, until prompt is refined and works for all balance sheets in excel 


## Current Prompt is in the GREEN NOTE, and in the textual / visual Gemini nodes 
`,
        height: 800,
        width: 768,
        color: 2,
    };

    @node({
        id: 'a7f403da-641a-495e-bd8e-c253a8c7224f',
        name: 'Evaluation1',
        type: 'n8n-nodes-base.evaluation',
        version: 4.8,
        position: [5568, 976],
    })
    Evaluation1 = {
        dataTableId: {
            __rl: true,
            value: 'E4fUDXr9nxDOv8o4',
            mode: 'list',
            cachedResultName: 'BALANCE_SHEET_EX_EVAL',
            cachedResultUrl: '/projects/EChUnhWXmjrEc3fG/datatables/E4fUDXr9nxDOv8o4',
        },
        outputs: {
            values: [
                {
                    outputName: 'DOCUMENT_TOTAL',
                    outputValue: '={{ $json.data.summary.documentTotal }}',
                },
                {
                    outputName: 'DOCUMENT_TOTAL_MATCH',
                    outputValue:
                        "={{ $('End').item.json.data.summary.documentTotal == $('Eval Start').last().json.EXPECTED_BALANCE }}",
                },
                {
                    outputName: 'DOCUMENT_DATE',
                    outputValue: "={{ $('End').item.json.data.documentDate }}",
                },
                {
                    outputName: 'DOCUMENT_DATE_MATCH',
                    outputValue:
                        "={{ $('End').item.json.data.documentDate == $('Eval Start').last().json.EXPECTED_DOCUMENT_DATE }}",
                },
                {
                    outputName: 'FIRST_LINE_ID',
                    outputValue: "={{ $('End').item.json.data.lines[0].id }}",
                },
                {
                    outputName: 'FIRST_LINE_ID_MATCH',
                    outputValue:
                        "={{ $('End').item.json.data.lines[0].id == $('Eval Start').last().json.EXPECTED_FIRST_LINE_ID }}",
                },
                {
                    outputName: 'FIRST_LINE_DATE',
                    outputValue: "={{ $('End').item.json.data.lines[0].date }}",
                },
                {
                    outputName: 'FIRST_LINE_DATE_MATCH',
                    outputValue:
                        "={{ $('End').item.json.data.lines[0].date == $('Eval Start').last().json.EXPECTED_FIRST_LINE_DATE }}",
                },
                {
                    outputName: 'FIRST_LINE_AMOUNT',
                    outputValue: "={{ $('End').item.json.data.lines[0].amount }}",
                },
                {
                    outputName: 'FIRST_LINE_AMOUNT_MATCH',
                    outputValue:
                        "={{ $('End').item.json.data.lines[0].amount == $('Eval Start').last().json.EXPECTED_FIRST_LINE_AMOUNT }}",
                },
                {
                    outputName: 'RUN_COMPLETED',
                    outputValue: '={{ true }}',
                },
                {
                    outputName: 'VERIFIED',
                    outputValue: "={{ $('End').item.json.data.summary.totalsMatch }}",
                },
            ],
        },
    };

    @node({
        id: '94e1072c-76a3-424b-8c74-0f1d159a7f54',
        name: 'If Success',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [5344, 816],
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
        id: '812a27b4-3bee-4961-b944-925438f01a07',
        name: 'If Eval Run',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [5344, 992],
    })
    IfEvalRun = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: '3bc4fd55-3f28-40df-966d-9f1b5722ee9a',
                    leftValue: '={{ $("Eval Start").isExecuted }}',
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
        id: 'ad625bd3-9182-4760-930b-c6567fd7fff5',
        name: 'CONFIG',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1168, 736],
    })
    Config = {
        assignments: {
            assignments: [
                {
                    id: '04ce5540-a4e3-42c4-bc5c-0c34cbcd02cf',
                    name: 'prompt',
                    value: `You are an expert accounting assistant. The provided file is a balance sheet or supplier reconciliation document. These documents are typically exchanged between companies to align their accounting records. Each line item in any table found usually references a separate, distinct document (such as an invoice, shipment confirmation, receipt, order, or credit memo) and its associated cost or monetary value.

Extract the following information for each line item in any accounting table found:
1. ID (a unique identifier for the line item, often the number of the referenced document like an invoice number, order number, or transaction ID. If multiple potential IDs exist pick according to this order ["חשבונית מס", "אסמכתה", "מסמך חיוב", "מסמך", "מספר מסמך"]. Note: An abbreviation like "אסמ." is considered equivalent to "אסמכתא". If both "אסמכתא" and "אסמכתא 2" appear, use the first "אסמכתא" and not the second. If no clear ID is found, use an empty string "")If you have a column named "מסמך" and a column named "סימוכין", choose the "מסמך" column.
2. Date (the date associated with the line item or the referenced document, in YYYY-MM-DD format. If multiple potential Date's, exist pick according to this order ["תאריך אסמכתה", "תאריך מסמך", "תאריך"]. Note: "תאריך ערך" or "תאריך לתשלום" and similar terms are NOT the correct date and should be ignored. If no date is found for a line, use an empty string "").
3. Amount (Extract the monetary values associated with each line item. When possible, extract BOTH values):
   - amount: The original document amount - the full invoice or transaction value when it was created. Look for columns like "סכום בחובה", "סכום בזכות", "amount", "invoice amount", or similar terms indicating the original document value.
   - balanceAmount: The remaining balance still owed on this document. Look for columns like "יתרה לתשלום", "balance", "amount due", "outstanding", or similar terms indicating what's left to pay.
   
   **Extraction Rules:**
   - If BOTH columns exist: extract both amount and balanceAmount separately
   - If ONLY original amount exists: set amount to that value, set balanceAmount to 0
   - If ONLY balance exists: set both amount and balanceAmount to the same value (assume full amount is still owed)
   - If NO amount is found: set both to 0
   - ALWAYS IGNORE: "יתרה מצטברת" (cumulative balance), "running total", "accumulated balance" - these are running totals across multiple lines, not individual line amounts
   
   Return amounts as numbers. If an amount cannot be parsed as a number, use 0.
4. Notes (Concise and important remarks or descriptions. Capture only significant details that differentiate the line item or provide critical context, such as specific item descriptions, unique transaction details, or reasons for adjustments. Focus on important and concise information. Avoid trivial or overly verbose information. If no truly important notes are found, use an empty string "").

Additionally, identify a primary date for the entire statement or document (e.g., statement date, reconciliation period end date) in YYYY-MM-DD format. If no specific overall document date is found, use an empty string "".
Also if total amount is provided within the document extract the value and provide it in the output as documentTotalAmount.
Also, calculate the sum of all valid 'amount' values from the extracted lines. This total should reflect the sum of the individual line item costs you've identified. If no amounts are found, this total should be 0.

Strictly return ONLY the JSON object with the following structure. Do not use null values; use an empty string "" for missing string values and 0 for missing numeric values. Do not include any explanations, apologies, or conversational text outside of the JSON structure. All keys in the specified JSON structure ("documentDate", "lines", "documentTotalAmount", "totalAmount", and within "lines": "id", "date", "amount", "notes") must be present.
Ensure that any double quotes that are part of the string data itself (e.g., in company names within the 'notes' field) are properly escaped with a backslash (e.g., "Company\\"s Data Inc.").
{
  "documentDate": "YYYY-MM-DD" | "",
  "lines": [
    { 
      "id": "string" | "", 
      "date": "YYYY-MM-DD" | "", 
      "amount": number | 0,
      "balanceAmount": number | 0,
      "notes": "string" | "" 
    }
  ],
  "documentTotalAmount": number | 0,
  "totalAmount": number | 0
}
If no accounting table suitable for this kind of line-by-line document reconciliation is found, or if the document doesn't seem to contain relevant accounting data, return an empty array for "lines", an empty string "" for "documentDate", and 0 for "totalAmount", still within the specified JSON structure.
Ensure 'amount' is a numerical value (or 0 if not found). Extract only numerical values for amounts, ignore currency symbols or text.
Focus on structured tabular data representing lists of transactions or referenced documents and their individual costs.`,
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '1248e7f0-cf84-4651-b7a8-8d15168d1bef',
        name: 'Document Processor',
        type: '@n8n/n8n-nodes-langchain.googleGemini',
        version: 1,
        position: [3696, 880],
        credentials: { googlePalmApi: { id: '6mfcsdRaqQ4IdQ8Y', name: 'ai-studio-bs-extraction [env-managed]' } },
        retryOnFail: true,
        maxTries: 5,
        waitBetweenTries: 5000,
    })
    DocumentProcessor = {
        resource: 'document',
        modelId: {
            __rl: true,
            value: 'models/gemini-3.1-pro-preview',
            mode: 'list',
            cachedResultName: 'models/gemini-3.1-pro-preview',
        },
        text: '={{ $("CONFIG FINAL").last().json.prompt }}',
        inputType: 'binary',
        options: {},
    };

    @node({
        id: '8f3333d9-d031-4e86-ba7b-f74c0e4cc3d0',
        name: 'Text Processor',
        type: '@n8n/n8n-nodes-langchain.googleGemini',
        version: 1,
        position: [4736, 1456],
        credentials: { googlePalmApi: { id: '6mfcsdRaqQ4IdQ8Y', name: 'ai-studio-bs-extraction [env-managed]' } },
        retryOnFail: true,
        maxTries: 5,
        waitBetweenTries: 5000,
    })
    TextProcessor = {
        modelId: {
            __rl: true,
            value: 'models/gemini-2.5-pro',
            mode: 'list',
            cachedResultName: 'models/gemini-2.5-pro',
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
        id: 'e6ad47bc-aa33-48e0-865f-96ffceb75cb2',
        name: 'Config1',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [736, 576],
        executeOnce: true,
    })
    Config1 = {
        jsCode: `for (const item of $input.all()) {
  item.json.json_schema = {
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "JSON_SUPPLIER_RECONCILIATION_DOC",
  "type": "object",
  "description": "JSON schema for a balance sheet or supplier reconciliation document with logical pre-calculation steps.",
  "additionalProperties": false,
  "properties": {
    "valid_input": {
      "type": "boolean",
      "description": "Is the input a valid Balance Doc?"
        },
    "doc_header": {
      "type": "object",
      "description": "Metadata, structural analysis, and mathematical validation of the full document before truncation.",
      "additionalProperties": false,
      "properties": {
        "pages_count": {
          "type": "integer",
          "description": "The total number of pages in the document.",
          "minimum": 1
        },
        "company_name_he": {
          "type": "string",
          "description": "Hebrew name of the issuing company."
        },
        "statement_type_he": {
          "type": "string",
          "description": "Type of statement in Hebrew (e.g., 'דוח גיול חובות')."
        },
        "date": {
          "type": "string",
          "pattern": "^\\\\d{4}-\\\\d{2}-\\\\d{2}$|^$",
          "description": "The primary date of the ledger/balance sheet in YYYY-MM-DD format."
        },
        "column_identification": {
          "type": "object",
          "description": "The OCR headers identified to map the document logic.",
          "properties": {
            "refrence_kws":{
              "type": "array",
              "description": "Identify and extract all headers of columns containing document references or identifiers. Match headers against keywords: ['אסמכתא', 'אסמ', 'חשבונית', 'doc', 'invoice', 'מסמך', 'תעודה', 'יומן', 'סימוכין', 'פקודה', 'ref', 'voucher', 'receipt', 'slip']. If a reference column header is not visible or missing, strictly map these columns to keys: r1, r2, r3.",
              "items": {
                "type": "string"
              }
            },
            "unique_key_kw": {
              "type": "string",
              "description": "The column header text used to identify unique lines (teke first from this priority list ['אסמכתא', 'אסמ','חשבונית','doc number','invoice', 'מסמך חיוב','מסמך','מס' תעודה','מספר ת. יומן','סימוכין','מספר מסמך','פקודה']"
            },
            "credit_kw": {
              "type": "string",
              "description": "The column header text for credit amounts (e.g., 'זכות')."
            },
            "debit_kw": {
              "type": "string",
              "description": "The column header text for debit amounts (e.g., 'חובה')."
            },
            "balance_kw": {
              "type": "string",
              "description": "The column header text for the running balance (e.g., 'יתרה')."
            },
          },
          "required": [
            "refrence_kws",
            "unique_key_kw",
            "balance_kw"
            
          ]
        },
        "full_document_logic": {
          "type": "object",
          "description": "Extraction of ALL lines (including those to be ignored) to validate counts and math.",
          "properties": {
            "initial_document_balance": {
              "type": "number",
              "description": "Use the opening balance stated at the start of the document (e.g., 'יתרת פתיחה'). If no opening balance is stated, use 0."
            },
            "all_transaction_identifiers": {
              "type": "array",
              "description": "An ordered list of the unique key value for EVERY transaction line in the document (from top to bottom).",
              "items": {
                "type": [
                  "string",
                  "integer"
                ]
              }
            },
            "all_transactions_math_log": {
              "type": "array",
              "description": "A math log for EVERY line to verify balance progression. transaction_change = Credit - Debit.",
              "items": {
                "type": "object",
                "properties": {
                  "id": {
                    "type": [
                      "string",
                      "integer"
                    ],
                    "description": "Corresponds to all_transaction_identifiers"
                  },
                  "tsc": {
                    "type": "number",
                    "description": "Positive for Credit, Negative for Debit. (transaction_change)"
                  },
                  "rb": {
                    "type": "number",
                    "description": "The value in the balance column for this line. (resulting_balance)"
                  }
                },
                "required": [
                  "tsc",
                  "rb"
                ]
              }
            },
            "total_lines_count": {
              "type": "integer",
              "description": "Total number of transaction lines detected in the entire document."
            },
          },
          "required": [
            "initial_document_balance",
            "all_transaction_identifiers",
            "all_transactions_math_log",
            "total_lines_count",
          ]
        },
        "selection_logic": {
          "type": "object",
          "description": "Logic defining which lines are kept (last 60) and where the cutoff occurs.",
          "properties": {
            "selected_transaction_identifiers": {
              "type": "array",
              "description": "The subset of identifiers from 'all_transaction_identifiers' that will be fully extracted in the 'transactions' array (Max 60).",
              "items": {
                "type": [
                  "string",
                  "integer"
                ]
              }
            },
            "cutoff_transaction_identifier": {
              "type": [
                "string",
                "integer",
                "null"
              ],
              "description": "The identifier of the last line NOT selected (the line immediately before the first selected line). Null if all lines are selected."
            },
            "cutoff_accumulated_balance": {
              "type": "number",
              "description": "The 'resulting_balance' of the cutoff_transaction_identifier. This becomes the OPENING BALANCE for the selected set. 0 if no lines were cut."
            }
          },
          "required": [
            "selected_transaction_identifiers",
            "cutoff_accumulated_balance"
          ]
        }
      },
      "required": [
        "company_name_he",
        "statement_type_he",
        "column_identification",
        "full_document_logic",
        "selection_logic"
      ]
    },
    "transactions": {
      "type": "array",
      "description": "Detailed extraction of the lines listed in 'doc_header.selection_logic.selected_transaction_identifiers'. (Very Importent.. Allwase return the selected transactions)",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "properties": {
          "unique_key": {
            "type": [
              "string",
              "integer"
            ],
            "description": "The unique identifier matching the list in doc_header."
          },
          "references": {
            "type": "array",
            "minItems": 1,
            "items": {
              "type": "object",
              "properties": {
                "key": {
                  "type": "string"
                },
                "value": {
                  "type": "string"
                }
              },
              "required": [
                "key",
                "value"
              ]
            },
            "description": "List with all refrences and there values (including unique key)"
          },
          "dates": {
            "type": "array",
            "minItems": 1,
            "items": {
              "type": "object",
              "properties": {
                "key": {
                  "type": "string"
                },
                "value": {
                  "type": "string",
                  "pattern": "^\\\\d{4}-\\\\d{2}-\\\\d{2}$"
                }
              },
              "required": [
                "key",
                "value"
              ]
            }
          },
          "debit_amount": {
            "type": "number"
          },
          "credit_amount": {
            "type": "number"
          },
          "accumulated_balance": {
            "type": "number"
          },
          "transaction_description_he": {
            "type": "string"
          },
          "currency": {
            "type": "string",
            "pattern": "^[A-Z]{3}$"
          },
          "note": {
            "type": "string"
          }
        },
        "required": [
          "unique_key",
          "refrences",
          "dates",
          "accumulated_balance",
          "debit_amount",
          "credit_amount",
          "currency"
        ]
      }
    },
    "summary": {
      "type": "object",
      "description": "Summary totals based on the 'selected' lines plus the carry-over from the cutoff.",
      "additionalProperties": false,
      "properties": {
        "currency": {
          "type": "string",
          "pattern": "^[A-Z]{3}$"
        },
        "initial_document_balance": {
          "type": "number",
          "description": "Should match 'doc_header.full_document_logic.initial_document_balance' or 0"
        },
        "cutoff_accumulated_balance": {
          "type": "number",
          "description": "Should match 'doc_header.selection_logic.cutoff_accumulated_balance' or 0"
        },
        "total_debit_amount": {
          "type": "number",
          "description": "The final debit amount displayed in the document (usually at / after bottom line), (importent) leave empty if not explicitly displayed."
        },
        "total_credit_amount": {
          "type": "number",
          "description": "The final credit amount displayed in the document (usually at / after bottom line), (importent) leave empty if not explicitly displayed."
        },
        "final_accumulated_balance": {
          "type": "number",
          "description": "The final Accumulated Balance displayed in the document (usually at / after bottom line), leave empty if not displayed."
        },
        "calculated_accumulated_balance": {
          "type": "number",
          "description": "The Final Calculated Accumulated Balance of both unselected and selected."
        }
      },
      "required": [
        "currency",
        "initial_document_balance",
        "cutoff_accumulated_balance",
        "final_accumulated_balance",
        "calculated_accumulated_balance"
      ]
    },
    "valid_output": {
      "type": "boolean",
      "description": "Dose the output look good?, is there an halucination?"
    }
  },
  "required": [
    "valid_input",
    "doc_header",
    "transactions",
    "summary",
    "valid_output"
  ]};
}

return $input.all();`,
    };

    @node({
        id: '3949a707-a043-4238-87fc-04d30adbee4a',
        name: 'Map Response',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [4704, 656],
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
                {
                    id: 'd67622e5-7e75-4aa0-8206-de8e23f4b69a',
                    name: 'data.summary.totalsMatch',
                    value: true,
                    type: 'boolean',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '9edd9623-3c5d-480c-9169-245a5fbe165f',
        name: 'Extract Response',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [3856, 832],
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
        id: 'c4e2aa68-6e5a-439b-ba25-1dc40b55ec74',
        name: 'Parse JSON Response',
        type: 'n8n-nodes-base.function',
        version: 1,
        position: [4032, 832],
    })
    ParseJsonResponse = {
        functionCode: `// חילוץ התוכן הגולמי מהצומת הקודם
const raw = items[0].json.content;

// ניקוי תגיות Markdown של JSON אם קיימות
const jsonText = raw.replace(/^\`\`\`json\\n/, '').replace(/\\n\`\`\`$/, '');

try {
  const parsed = JSON.parse(jsonText);
  // החזרת האובייקט המפוענח
  return [{ json: parsed }];
} catch (error) {
  // החזרת הודעת שגיאה במקרה של JSON לא תקין
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
        id: '9523e2cf-6dc8-4a88-be85-bd99995f47c7',
        name: 'Format Response',
        type: 'n8n-nodes-base.function',
        version: 1,
        position: [4208, 832],
    })
    FormatResponse = {
        functionCode: `const item = items[0].json;

// Check if there was a parsing error
if (item.error) {
  return [{
    json: {
      success: false,
      error: item.error,
      details: item.parseError || "Unknown parsing error"
    }
  }];
}

// Validate required structure
if (!item.hasOwnProperty('lines') || !item.hasOwnProperty('totalAmount') || !item.hasOwnProperty('documentDate')) {
  return [{
    json: {
      success: false,
      error: "Invalid response structure",
      details: "Missing required fields: lines, totalAmount, or documentDate"
    }
  }];
}

const lines = item.lines || [];
const documentTotal = item.documentTotalAmount || item.totalAmount || 0;
const documentDate = item.documentDate || "";

// Calculate sums from individual line items for BOTH amount types
const calculatedAmountSum = lines.reduce((acc, line) => {
  const amount = parseFloat(line.amount) || 0;
  return acc + amount;
}, 0);

const calculatedBalanceSum = lines.reduce((acc, line) => {
  const balanceAmount = parseFloat(line.balanceAmount) || 0;
  return acc + balanceAmount;
}, 0);

// Allow $100 OR 0.1% difference, whichever is smaller
const fixedTolerance = 100;
const percentageTolerance = documentTotal * 0.001; // 0.1%
const tolerance = Math.min(fixedTolerance, percentageTolerance);

// Check if EITHER interpretation matches the document total
const amountMatches = Math.abs(calculatedAmountSum - documentTotal) <= tolerance;
const balanceMatches = Math.abs(calculatedBalanceSum - documentTotal) <= tolerance;
const totalsMatch = amountMatches || balanceMatches;

// Determine which amount type matches
let matchType = 'none';
let matchedSum = 0;
let difference = 0;

if (amountMatches && balanceMatches) {
  matchType = 'both';
  matchedSum = calculatedAmountSum; // Use amount as primary
  difference = 0;
} else if (balanceMatches) {
  matchType = 'balance';
  matchedSum = calculatedBalanceSum;
  difference = calculatedBalanceSum - documentTotal;
} else if (amountMatches) {
  matchType = 'amount';
  matchedSum = calculatedAmountSum;
  difference = calculatedAmountSum - documentTotal;
} else {
  // Neither matches - report both differences
  matchType = 'none';
  matchedSum = calculatedBalanceSum; // Default to balance for reporting
  difference = calculatedBalanceSum - documentTotal;
}

// Format response
const response = {
  success: true,
  data: {
    documentDate: documentDate,
    lines: lines.map(line => ({
      id: line.id || "",
      date: line.date || "",
      amount: parseFloat(line.amount) || 0,
      balanceAmount: parseFloat(line.balanceAmount) || 0,
      notes: line.notes || ""
    })),
    summary: {
      totalLines: lines.length,
      documentTotal: documentTotal,
      calculatedAmountSum: parseFloat(calculatedAmountSum.toFixed(2)),
      calculatedBalanceSum: parseFloat(calculatedBalanceSum.toFixed(2)),
      totalsMatch: totalsMatch,
      matchType: matchType,
      difference: parseFloat(difference.toFixed(2)),
      amountDifference: parseFloat((calculatedAmountSum - documentTotal).toFixed(2)),
      balanceDifference: parseFloat((calculatedBalanceSum - documentTotal).toFixed(2))
    }
  },
  processedAt: new Date().toISOString()
};

return [{ json: response }];`,
    };

    @node({
        id: '9dadc883-21ff-4047-9f39-129c8d898f19',
        name: 'Response Format: No LLM Output',
        type: 'n8n-nodes-base.function',
        version: 1,
        position: [4736, 816],
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
    processedAt: new Date().toISOString()
  }
}];`,
    };

    @node({
        id: '8972d962-41d3-4d57-b3f2-21a7dc3bd0a3',
        name: 'MAP LINK1',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [-448, 944],
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
                    value: '={{ $json.body.use_cache ?? true }}',
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
        id: '81108564-21ec-4392-9c76-a7125bac7ffd',
        name: 'When clicking ‘Execute workflow’',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [-864, 1568],
    })
    WhenClickingExecuteWorkflow = {};

    @node({
        id: 'b52a92d2-a7b6-4605-9900-f22a3fd838c2',
        name: 'Delete Cache',
        type: 'n8n-nodes-kv-storage.kvStorage',
        version: 1,
        position: [-592, 1568],
    })
    DeleteCache = {
        operation: 'setValue',
        key: '={{ "c565df33c7194f72ce2395956c771695" }}',
    };

    @node({
        id: '0ed41a37-6217-4e33-b540-9a22f9d71f3d',
        name: 'Text Processor1',
        type: '@n8n/n8n-nodes-langchain.googleGemini',
        version: 1,
        position: [3504, 544],
        credentials: { googlePalmApi: { id: '6mfcsdRaqQ4IdQ8Y', name: 'ai-studio-bs-extraction [env-managed]' } },
        retryOnFail: true,
        maxTries: 5,
        waitBetweenTries: 5000,
    })
    TextProcessor1 = {
        modelId: {
            __rl: true,
            value: 'models/gemini-3.1-pro-preview',
            mode: 'list',
            cachedResultName: 'models/gemini-3.1-pro-preview',
        },
        messages: {
            values: [
                {
                    content: '={{ $("CONFIG FINAL").last().json.prompt }}',
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
        id: 'b2ace030-996d-4e88-96cb-893413f8f6cd',
        name: 'Document OCR',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [3152, 1392],
        executeOnce: false,
        retryOnFail: true,
        maxTries: 5,
        waitBetweenTries: 5000,
    })
    DocumentOcr = {
        method: 'POST',
        url: 'http://apitools:8080/documentOcr',
        sendQuery: true,
        specifyQuery: 'json',
        jsonQuery: '{"truncate_from": "end", "max_pages":3}',
        sendBody: true,
        contentType: 'multipart-form-data',
        bodyParameters: {
            parameters: [
                {
                    parameterType: 'formBinaryData',
                    name: 'file',
                    inputDataFieldName: 'data',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'e33784ed-6af5-48ff-ac19-180f7a608e28',
        name: 'Code in JavaScript2',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3360, 1392],
    })
    CodeInJavascript2 = {
        jsCode: `const now = new Date();
const sixMonthsAgo = new Date(now);
sixMonthsAgo.setMonth(sixMonthsAgo.getMonth() - 6);

function extractDate(text) {
  const m = text.match(/^(\\d{2})[\\/\\-](\\d{2})[\\/\\-](\\d{2,4})$/);
  if (!m) return null;
  let [, day, month, year] = m;
  if (year.length === 2) year = '20' + year;
  const d = new Date(\`\${year}-\${month}-\${day}\`);
  return isNaN(d.getTime()) ? null : d;
}

const item = $input.first().json;
const pages = item?.ocr_json?.fullTextAnnotation?.pages || [];

const relevantPageIndices = [];

pages.forEach((page, pageIndex) => {
  const hasRecentDate = (page.blocks || []).some(block =>
    (block.paragraphs || []).some(para =>
      (para.words || []).some(word => {
        const text = (word.symbols || []).map(s => s.text).join('');
        const d = extractDate(text);
        return d && d >= sixMonthsAgo;
      })
    )
  );
  if (hasRecentDate) relevantPageIndices.push(pageIndex);
});

return [{
  json: {
    ...item,
    relevantPageIndices,
    totalPages: pages.length
  },
  binary: $input.first().binary
}];`,
    };

    @node({
        id: 'aa5b1167-9cac-4130-9bb1-2a7c2077ed8b',
        name: 'If2',
        type: 'n8n-nodes-base.if',
        version: 2.3,
        position: [3568, 1392],
    })
    If2 = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 3,
            },
            conditions: [
                {
                    id: '26cbaa75-7cd0-479e-ad04-56c506196945',
                    leftValue: '={{ $json.relevantPageIndices.length }}',
                    rightValue: 0,
                    operator: {
                        type: 'number',
                        operation: 'gt',
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: '4d0872ea-e29d-4277-9bac-ca668cb28229',
        name: 'Code in Python (Native)',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3840, 1312],
    })
    CodeInPythonNative = {
        language: 'pythonNative',
        pythonCode: `import base64
import io
from pypdf import PdfReader, PdfWriter

item = _input.first()
relevant_indices = item.json['relevantPageIndices']
pdf_binary = item.binary['data']['data']

pdf_bytes = base64.b64decode(pdf_binary)
reader = PdfReader(io.BytesIO(pdf_bytes))
writer = PdfWriter()

for i in relevant_indices:
    if i < len(reader.pages):
        writer.add_page(reader.pages[i])

out = io.BytesIO()
writer.write(out)
sliced_b64 = base64.b64encode(out.getvalue()).decode('utf-8')

return [{
    'json': item.json,
    'binary': {
        'data': {
            'data': sliced_b64,
            'mimeType': 'application/pdf',
            'fileName': 'sliced.pdf'
        }
    }
}]`,
    };

    @node({
        id: '0657d4c2-a948-45c6-800f-5bd6c607f79f',
        name: 'Start1',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [3104, 880],
    })
    Start1 = {};

    @node({
        id: 'bae0229d-4f73-4469-83f8-9c1175003ebf',
        name: 'CONFIG1',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1024, 640],
    })
    Config11 = {
        assignments: {
            assignments: [
                {
                    id: '7737cc7e-fb6c-4566-bf37-c0106ef7d8c4',
                    name: 'prompt',
                    value: "={{ $('Call \\'Settings\\'').item.json.company_prompt_bs_by_id[String($('When Executed by Another Workflow').item.json.COMPANY_ID)] }}",
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: '80ccf771-fb19-41a9-b818-85fa9d56f1ca',
        name: "Call 'Settings'",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [736, 720],
        executeOnce: true,
    })
    CallSettings = {
        workflowId: {
            __rl: true,
            value: 'indoxSettings01',
            mode: 'list',
            cachedResultUrl: '/workflow/indoxSettings01',
            cachedResultName: 'Settings',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                load_settings: false,
                load_queries: false,
                TRIGGERED_FROM: '=Balance Sheet Extractor - v2- shmuel: {{ $execution.id }}',
                __instance:
                    "={{ $json.__instance || (() => { try { return ($('When Executed by Another Workflow').first().json || {}).__instance || ''; } catch (e) {} try { return (($('Webhook Trigger').first().json || {}).body || {}).__instance || ''; } catch (e) {} return ''; })() }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'load_settings',
                    displayName: 'load_settings',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'boolean',
                    removed: false,
                },
                {
                    id: 'load_companies',
                    displayName: 'load_companies',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'boolean',
                    removed: false,
                },
                {
                    id: 'load_queries',
                    displayName: 'load_queries',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'boolean',
                    removed: false,
                },
                {
                    id: 'TRIGGERED_FROM',
                    displayName: 'TRIGGERED_FROM',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                    removed: false,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        options: {},
    };

    @node({
        id: 'e06740f2-7ad1-4055-819d-bca2b143fb11',
        name: 'If3',
        type: 'n8n-nodes-base.if',
        version: 2.3,
        position: [880, 720],
        onError: 'continueRegularOutput',
    })
    If3 = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 3,
            },
            conditions: [
                {
                    id: '73ff85e8-683e-455e-97dc-f681c9f094f1',
                    leftValue:
                        "={{ Object.keys($('Call \\'Settings\\'').item.json.company_prompt_bs_by_id).includes(String($('When Executed by Another Workflow').item.json.COMPANY_ID)) }}",
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
        id: '9762e464-086b-4c15-8a10-bc365750c2a6',
        name: 'CONFIG FINAL',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1344, 736],
    })
    ConfigFinal = {
        assignments: {
            assignments: [
                {
                    id: '04ce5540-a4e3-42c4-bc5c-0c34cbcd02cf',
                    name: 'prompt',
                    value: '={{ $json.prompt + ($("CONFIG1").isExecuted ? "\\n\\n" + $("CONFIG1").item.json.prompt : "") }}',
                    type: 'string',
                },
            ],
        },
        options: {},
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
        this.TextualInput.out(0).to(this.TextProcessor1.in(0));
        this.ExtractFromFile.out(0).to(this.Code.in(0));
        this.Code.out(0).to(this.TextualInput.in(0));
        this.ExtractFromFile1.out(0).to(this.TextualInput.in(0));
        this.ExtractFromFile2.out(0).to(this.Code.in(0));
        this.ResponseFormatUnsupportedFileError.out(0).to(this.End.in(0));
        this.Crypto.out(0).to(this.Kvstorage.in(0));
        this.Kvstorage.out(0).to(this.If_.in(0));
        this.End.out(0).to(this.ApiResponse.in(0));
        this.End.out(0).to(this.IfEvalRun.in(0));
        this.End.out(0).to(this.IfSuccess.in(0));
        this.BeforeStart.out(0).to(this.If1.in(0));
        this.BeforeStart.out(0).to(this.CallSettings.in(0));
        this.BeforeStart.out(0).to(this.Config1.in(0));
        this.Start.out(0).to(this.FileTypeRouter.in(0));
        this.If_.out(0).to(this.CodeInJavascript1.in(0));
        this.If_.out(1).to(this.Code2.in(0));
        this.Code2.out(0).to(this.Start.in(0));
        this.If1.out(0).to(this.Crypto.in(0));
        this.If1.out(1).to(this.Start.in(0));
        this.WhenExecutedByAnotherWorkflow.out(0).to(this.Switch_.in(0));
        this.Switch_.out(0).to(this.BeforeStart.in(0));
        this.Switch_.out(1).to(this.DownloadLink.in(0));
        this.DownloadLink.out(0).to(this.IfBinary.in(0));
        this.IfBinary.out(0).to(this.BeforeStart.in(0));
        this.IfBinary.out(1).to(this.CodeInJavascript.in(0));
        this.CodeInJavascript1.out(0).to(this.ApiResponse1.in(0));
        this.MapLink.out(0).to(this.Switch_.in(0));
        this.EvalStart.out(0).to(this.MapLink.in(0));
        this.IfSuccess.out(0).to(this.Kvstorage1.in(0));
        this.IfEvalRun.out(0).to(this.Evaluation1.in(0));
        this.MapResponse.out(0).to(this.End.in(0));
        this.ExtractResponse.out(0).to(this.ParseJsonResponse.in(0));
        this.ParseJsonResponse.out(0).to(this.FormatResponse.in(0));
        this.ResponseFormatNoLlmOutput.out(0).to(this.End.in(0));
        this.MapLink1.out(0).to(this.Switch_.in(0));
        this.WhenClickingExecuteWorkflow.out(0).to(this.DeleteCache.in(0));
        this.DocumentProcessor.out(0).to(this.ExtractResponse.in(0));
        this.TextProcessor1.out(0).to(this.ExtractResponse.in(0));
        this.FormatResponse.out(0).to(this.MapResponse.in(0));
        this.DocumentOcr.out(0).to(this.CodeInJavascript2.in(0));
        this.CodeInJavascript2.out(0).to(this.If2.in(0));
        this.If2.out(0).to(this.CodeInPythonNative.in(0));
        this.Start1.out(0).to(this.DocumentProcessor.in(0));
        this.CallSettings.out(0).to(this.If3.in(0));
        this.If3.out(0).to(this.Config11.in(0));
        this.If3.out(1).to(this.Config.in(0));
        this.Config11.out(0).to(this.Config.in(0));
        this.Config.out(0).to(this.ConfigFinal.in(0));
        this.CodeInJavascript.out(0).to(this.ApiResponse1.in(0));
    }
}
