import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Upload Doc To API TOOLS
// Nodes   : 20  |  Connections: 28
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// DownloadFile3                      executeWorkflow            [onError→regular] [retry]
// DocumentOcr2                       httpRequest                [onError→out(1)] [retry]
// Return_                            set
// RenderThumbnail                    httpRequest                [onError→regular] [retry]
// RenameThumbnailResult              set
// MergeUploadThumbnail               merge
// Start                              executeWorkflowTrigger
// Switch_                            switch
// CheckHash                          httpRequest                [retry]
// IfExists                           if
// Binary                             noOp
// IfBinaryTest                       if
// DownloadFile                       executeWorkflow            [retry]
// WrongInput                         set
// FileNotFound                       set
// IfMissingLink                      if
// GdriveFail                         set
// IfNoBinary                         if
// LockMapSetRetryScope               redis                      [onError→regular] [creds]
// OcrShed                            code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// Start
//    → IfBinaryTest
//      → DownloadFile
//        → Switch_
//          → CheckHash
//            → IfExists
//              → Return_
//             .out(1) → IfMissingLink
//                → FileNotFound
//                  → Return_ (↩ loop)
//               .out(1) → DownloadFile3
//                  → IfNoBinary
//                    → GdriveFail
//                      → Return_ (↩ loop)
//                   .out(1) → DocumentOcr2
//                      → MergeUploadThumbnail
//                        → Return_ (↩ loop)
//                      → RenderThumbnail
//                        → RenameThumbnailResult
//                          → MergeUploadThumbnail.in(1) (↩ loop)
//                     .out(1) → OcrShed
//                        → Return_ (↩ loop)
//         .out(1) → DownloadFile3 (↩ loop)
//         .out(2) → Binary
//            → DocumentOcr2 (↩ loop)
//         .out(3) → WrongInput
//            → Return_ (↩ loop)
//     .out(1) → Switch_ (↩ loop)
//    → LockMapSetRetryScope
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Download file3":{"main":[[{"node":"If No Binary","type":"main","index":0}],[]]},"Start":{"main":[[{"node":"Switch","type":"main","index":0},{"node":"Lock Map Set (retry scope)","type":"main","index":0}]]},"Document OCR2":{"main":[[{"node":"Return","type":"main","index":0}],[{"node":"OCR Shed","type":"main","index":0}]]},"Switch":{"main":[[{"node":"Check HASH","type":"main","index":0}],[{"node":"Download file3","type":"main","index":0}],[{"node":"Binary","type":"main","index":0}],[{"node":"WRONG INPUT","type":"main","index":0}]]},"Check HASH":{"main":[[{"node":"If Exists","type":"main","index":0}]]},"If Exists":{"main":[[{"node":"Return","type":"main","index":0}],[{"node":"If MISSING Link","type":"main","index":0}]]},"Binary":{"main":[[{"node":"Document OCR2","type":"main","index":0}]]},"WRONG INPUT":{"main":[[{"node":"Return","type":"main","index":0}]]},"FILE_NOT_FOUND":{"main":[[{"node":"Return","type":"main","index":0}]]},"If MISSING Link":{"main":[[{"node":"FILE_NOT_FOUND","type":"main","index":0}],[{"node":"Download file3","type":"main","index":0}]]},"Return":{"main":[[]]},"GDRIVE FAIL":{"main":[[{"node":"Return","type":"main","index":0}]]},"If No Binary":{"main":[[{"node":"GDRIVE FAIL","type":"main","index":0}],[{"node":"Document OCR2","type":"main","index":0}]]},"OCR Shed":{"main":[[{"node":"Return","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"56de2cdd-1d32-4a04-b009-b7d1928bf34d","name":"extractors"},{"updatedAt":"2026-07-30T23:41:29.646Z","createdAt":"2026-07-30T23:41:29.646Z","id":"9c337cfe-7feb-4f3d-ab26-3de6439357ce","name":"sm-refactore-v2.1"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"51804d94-1071-4213-980b-a06491a07895","name":"role:api"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"f5d175fb-c738-4607-8ef0-bf03c48e8a0b","name":"role:extractor"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"22f1e71e-91bf-48db-811f-8d3bc4e55a3e","name":"sm-refactor-v2.1"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {"templateCredsSetupCompleted":true},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-31T00:59:54.840Z","createdAt":"2026-07-31T00:59:54.840Z","role":"workflow:owner","workflowId":"indoxV2UploadApiTools01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2UploadApiTools01',
    name: 'Upload Doc To API TOOLS',
    active: true,
    isArchived: false,
    tags: [
        'app:indox',
        'indox',
        'extractors',
        'sm-refactore-v2.1',
        'indox-app',
        'role:api',
        'role:extractor',
        'sm-refactor-v2.1',
    ],
    settings: { executionOrder: 'v1', errorWorkflow: 'errorHandler01', executionTimeout: 3600 },
})
export class UploadDocToApiToolsWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: '0eb061dc-18a4-4aec-aa8c-6dfab93e46bb',
        name: 'Download file3',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [304, 1008],
        onError: 'continueRegularOutput',
        retryOnFail: true,
        maxTries: 4,
        waitBetweenTries: 3000,
    })
    DownloadFile3 = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'download',
                params: "={{ ({ fileId: $('Start').item.json.LINK, fileIdMode: \"url\", connection_id: $('Start').item.json.LINK_CONNECTION }) }}",
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
        id: 'abf609cb-ab71-4561-a9ff-b5a61d561561',
        name: 'Document OCR2',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [704, 1088],
        onError: 'continueErrorOutput',
        executeOnce: false,
        retryOnFail: true,
        maxTries: 5,
        waitBetweenTries: 5000,
    })
    DocumentOcr2 = {
        method: 'POST',
        url: 'http://apitools:8080/documentOcr',
        sendQuery: true,
        queryParameters: {
            parameters: [
                {
                    name: 'dont_return_ocr',
                    value: '={{true}}',
                },
            ],
        },
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
        options: {
            timeout: 600000,
        },
    };

    @node({
        id: '8c2f21ce-e1e7-4440-8a5e-2560a1416199',
        name: 'Return',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1040, 672],
    })
    Return_ = {
        assignments: {
            assignments: [
                {
                    id: '8616dea3-a800-41ed-83c8-b149d059d407',
                    name: 'file_id',
                    value: '={{ $json.file_hash || $json.file_id || null}}',
                    type: 'string',
                },
                {
                    id: '70159040-f94b-4d44-9bc5-6be062f1edd5',
                    name: 'ok',
                    value: '={{ !$json.error }}',
                    type: 'boolean',
                },
                {
                    id: 'th-return-0002',
                    name: 'ID',
                    value: "={{ (() => { try { return $('Start').item.json.ID || null; } catch (e) { return null; } })() }}",
                    type: 'string',
                },
            ],
        },
        includeOtherFields: true,
        options: {},
    };






    @node({
        id: '6bbe529a-84ed-42ba-8323-aeb47760afdc',
        name: 'Start',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [-1008, 1072],
    })
    Start = {
        workflowInputs: {
            values: [
                {
                    name: 'LINK',
                    type: 'any',
                },
                {
                    name: 'HASH',
                },
                {
                    name: 'ID',
                    type: 'any',
                },
                {
                    name: 'LINK_CONNECTION',
                },
            ],
        },
    };

    @node({
        id: 'f8211be0-3fb2-4fa1-bb1e-4651fde9eddd',
        name: 'Switch',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [-480, 1056],
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
                                id: 'a70fb07d-438c-4218-976c-ed0d6ad8ccb3',
                                leftValue: '={{ !!$json.HASH && !$input.item.binary }}',
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
                    outputKey: 'hash',
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
                                id: '8cd2bb61-153c-40a4-a499-c4830a249685',
                                leftValue: '={{ !!$json.LINK && !$input.item.binary }}',
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
                                leftValue: '={{ !!$input.item.binary }}',
                                rightValue: '',
                                operator: {
                                    type: 'boolean',
                                    operation: 'true',
                                    singleValue: true,
                                },
                                id: 'e8a8ee5b-8823-43b4-87f9-b12b684982eb',
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'binary',
                },
            ],
        },
        options: {
            fallbackOutput: 'extra',
        },
    };

    @node({
        id: 'a83984d6-a0c8-4261-a133-c71c324e61ea',
        name: 'Check HASH',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [-256, 688],
        executeOnce: false,
        retryOnFail: true,
        maxTries: 5,
        waitBetweenTries: 5000,
    })
    CheckHash = {
        url: 'http://apitools:8080/docExists',
        sendBody: true,
        bodyParameters: {
            parameters: [
                {
                    name: 'file_id',
                    value: '={{ $json.HASH }}',
                },
            ],
        },
        options: {
            timeout: 120000,
        },
    };

    @node({
        id: 'c37d7c65-e2e1-493f-a1f6-d5f8aeaf4bcf',
        name: 'If Exists',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [-48, 688],
    })
    IfExists = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: '21ec0d81-6d00-44dd-a5df-1800474db253',
                    leftValue: '={{ $json.exists || false }}',
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
        id: '0969981e-0fd0-462e-a04a-0a3d6f55a03a',
        name: 'Binary',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [464, 1184],
    })
    Binary = {};



    @node({
        id: '4e10aa39-fc4b-425c-95be-9fc07b694aa9',
        name: 'WRONG INPUT',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [704, 1344],
    })
    WrongInput = {
        assignments: {
            assignments: [
                {
                    id: '8616dea3-a800-41ed-83c8-b149d059d407',
                    name: 'error',
                    value: '=wrong_input',
                    type: 'string',
                },
            ],
        },
        includeOtherFields: true,
        options: {},
    };

    @node({
        id: '2b8b0b07-d8a1-425a-b9e8-3a93a3d3079f',
        name: 'FILE_NOT_FOUND',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [704, 768],
    })
    FileNotFound = {
        assignments: {
            assignments: [
                {
                    id: '96028b67-15c2-4dfa-ad8f-0019b9cc7b8d',
                    name: 'error',
                    value: 'file_not_found',
                    type: 'string',
                },
            ],
        },
        includeOtherFields: true,
        options: {},
    };

    @node({
        id: 'aca064fe-dada-4d00-9864-e8f46896aeb5',
        name: 'If MISSING Link',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [128, 784],
    })
    IfMissingLink = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: 'ce9d3c14-15e7-4b10-949a-8dd91f3dd696',
                    leftValue: "={{ !$('Start').item.json.LINK  }}",
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
        id: 'f72c3305-980d-443f-b845-5ee3629c7aae',
        name: 'GDRIVE FAIL',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [704, 928],
    })
    GdriveFail = {
        assignments: {
            assignments: [
                {
                    id: '355c1caf-2c38-45e0-a0e2-864b949c54e3',
                    name: 'error',
                    value: '={{ `Failed to download google drive link: ${$("Start").item.json.LINK}, error: ${$json.error || \'\'}`  }}',
                    type: 'string',
                },
            ],
        },
        includeOtherFields: true,
        options: {},
    };

    @node({
        id: 'd3f5e689-d064-4bc0-892f-6a887458197b',
        name: 'If No Binary',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [464, 1008],
    })
    IfNoBinary = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: '8b04ee70-69f9-4a58-a0c2-db8331936ff1',
                    leftValue: '={{ !($input.item.binary || null) }}',
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
        id: 'lockmap-indoxv2uploadapito',
        name: 'Lock Map Set (retry scope)',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [-848, 752],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
        onError: 'continueRegularOutput',
    })
    LockMapSetRetryScope = {
        operation: 'set',
        key: '=n8n.exec.{{ $execution.id }}.docmap',
        value: "={{ $input.all().length === 1 ? ($json.ID ?? '') : '' }}",
        keyType: 'string',
        expire: true,
        ttl: '={{ 60*20 }}',
    };

    @node({
        id: 'g5ocrshed000000001',
        name: 'OCR Shed',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [884, 1258],
    })
    OcrShed = {
        jsCode: `// [g5 2026-08-09] A shed request must not kill the document.
// apitools' admission-control bulkhead answers 429 \`server_busy\` BY DESIGN -- that half is
// correct and is left alone. What was wrong is the consequence: the whole document failed,
// and it took \`Base Document Extraction\` down with it.
// Retrying harder is not available: n8n CLAMPS waitBetweenTries to 5s and maxTries to 5 in
// workflow-execute.js, so this node's configured 15000ms backoff has always actually run as 5s.
// Past those tries we degrade through this workflow's OWN convention -- an item carrying
// \`error\`, which \`Return\` already turns into ok:false -- instead of throwing.
//
// [2026-08-10] FIXED: THIS NODE READ THE WRONG FIELDS, SO IT NEVER SHED ANYTHING.
// On the error output of an n8n HTTP Request node the item is \`{...inputJson, error: E}\`.
// The failure detail lives under \`error\`, NOT at the top level, and E is either:
//   * an OBJECT for a real HTTP failure -- {message, name, code, status: 429, stack}, i.e.
//     the status is at \`error.status\`, and for 429 n8n REPLACES the upstream body with its
//     own hint "Try spacing your requests out using the batching settings under 'Options'",
//     so the words \`server_busy\` never reach us; or
//   * a plain STRING for apitools' own 200-with-error-body responses, e.g.
//     "File type not allowed: ...".
// The old code read \`e.httpCode || e.statusCode || e.status\` and \`e.message\` at the TOP
// level -- all undefined in both shapes -- so \`status\` was always 0 and the regex never
// matched. Result: every OCR failure of any kind threw the same uninformative
// "document OCR failed (no status)". MEASURED over one hour: 218 such throws, with a 429
// present in 214 of the 230 failing executions and in 0 of the 1,535 successful ones --
// i.e. the shed path fired exactly never. Each throw also failed the parent
// \`Base Document Extraction\` (double-counting the same failure) and cost an errorHandler01 run.
const item = $input.first().json || {};
const raw = item.error !== undefined ? item.error : item;
const asObj = (raw && typeof raw === 'object') ? raw : {};

const status = Number(
  asObj.status || asObj.httpCode || asObj.statusCode ||
  item.status || item.httpCode || item.statusCode || 0
);

const message = (typeof raw === 'string')
  ? raw
  : (asObj.message || item.message || '');

// Match on everything we can see, including n8n's own 429 phrasing.
const text = (JSON.stringify(item) || '').toLowerCase();
// [413 shed 2026-08-12] A PERMANENT REFUSAL MUST DEGRADE, NOT THROW.
  // 429 is transient; 413 is not - the file exceeds apitools' MAX_CONTENT_LENGTH (50MB) and no
  // retry can succeed. Throwing also kills the parent chain before 'Select Base Values' stamps
  // BASE APITOOLS RETRY, so the decide rule re-fires for ever: the error that should end the
  // document is what keeps it looping. Shedding lets the pass finish, stamps the bound, and
  // records the reason on the row.
  const shed = status === 429 || status === 413 ||
    /server_busy|too many requests|try spacing your requests out/.test(text) ||
    /request entity too large|exceeds the capacity limit/.test(text);

if (!shed) {
  // Surface the REAL cause. A bare "(no status)" told us nothing for a whole day.
  // [clear passthrough 2026-08-17, owner order] apitools puts its verdict in the response
  // body error field, e.g. OCR processing failed plus the reason. Extract that instead of
  // throwing the raw status-plus-json dump, which n8n truncates to an unreadable tail.
  let clear = message;
  try {
    const s0 = String(message);
    const a = s0.indexOf('{'), z = s0.lastIndexOf('}');
    if (a >= 0 && z > a) {
      const b = JSON.parse(s0.slice(a, z + 1));
      if (b && b.error) clear = String(b.error);
    }
  } catch (e) {}
  throw new Error(clear || ('document OCR failed (' + (status || 'no status') + ')'));
}

return [{ json: {
  error: 'ocr_server_busy',
  retryable: true,
  needs_review: false,
  http_status: status || 429,
  details: 'apitools shed this request (admission control); the document is untouched and the '
         + 'next sweep should retry it',
} }];
`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.Start.out(0).to(this.Switch_.in(0));
        this.DownloadFile3.out(0).to(this.IfNoBinary.in(0));
        this.Start.out(0).to(this.LockMapSetRetryScope.in(0));
        this.DocumentOcr2.out(0).to(this.Return_.in(0));
        this.DocumentOcr2.out(1).to(this.OcrShed.in(0));
        this.Switch_.out(0).to(this.CheckHash.in(0));
        this.Switch_.out(1).to(this.DownloadFile3.in(0));
        this.Switch_.out(2).to(this.Binary.in(0));
        this.Switch_.out(3).to(this.WrongInput.in(0));
        this.CheckHash.out(0).to(this.IfExists.in(0));
        this.IfExists.out(0).to(this.Return_.in(0));
        this.IfExists.out(1).to(this.IfMissingLink.in(0));
        this.Binary.out(0).to(this.DocumentOcr2.in(0));
        this.WrongInput.out(0).to(this.Return_.in(0));
        this.FileNotFound.out(0).to(this.Return_.in(0));
        this.IfMissingLink.out(0).to(this.FileNotFound.in(0));
        this.IfMissingLink.out(1).to(this.DownloadFile3.in(0));
        this.GdriveFail.out(0).to(this.Return_.in(0));
        this.IfNoBinary.out(0).to(this.GdriveFail.in(0));
        this.IfNoBinary.out(1).to(this.DocumentOcr2.in(0));
        this.OcrShed.out(0).to(this.Return_.in(0));
    }
}
