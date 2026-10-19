import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : drive api
// Nodes   : 16  |  Connections: 23
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenCalled                         executeWorkflowTrigger
// GuardConnection                    code
// OpSwitch                           switch
// Done                               noOp
// DDownload                          httpRequest                [onError→out(1)] [retry]
// ShapeDownload                      code
// DList                              httpRequest                [retry]
// ShapeList                          code
// DConnections                       httpRequest                [retry]
// ShapeConnections                   code
// DUpload                            httpRequest                [retry]
// DMove                              httpRequest                [retry]
// DUpdate                            httpRequest                [retry]
// DDelete                            httpRequest                [retry]
// DCreatefromtext                    httpRequest                [retry]
// DownloadMiss                       code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → GuardConnection
//      → OpSwitch
//        → DDownload
//          → ShapeDownload
//            → Done
//         .out(1) → DownloadMiss
//            → Done (↩ loop)
//       .out(1) → DList
//          → ShapeList
//            → Done (↩ loop)
//       .out(2) → DUpload
//          → Done (↩ loop)
//       .out(3) → DMove
//          → Done (↩ loop)
//       .out(4) → DUpdate
//          → Done (↩ loop)
//       .out(5) → DDelete
//          → Done (↩ loop)
//       .out(6) → DCreatefromtext
//          → Done (↩ loop)
//       .out(7) → DConnections
//          → ShapeConnections
//            → Done (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: "drive api — the seven canonical ops (contract ai/context/platform-service-contract.md §3), each one HTTP Request to the drive service. n8n holds NO Google credential: the service owns the connection and reports it on /readyz, so an op either runs on the account the operator selected or fails 503 naming why.",
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"Guard Connection","type":"main","index":0}]]},"Op Switch":{"main":[[{"node":"d:download","type":"main","index":0}],[{"node":"d:list","type":"main","index":0}],[{"node":"d:upload","type":"main","index":0}],[{"node":"d:move","type":"main","index":0}],[{"node":"d:update","type":"main","index":0}],[{"node":"d:delete","type":"main","index":0}],[{"node":"d:createFromText","type":"main","index":0}],[{"node":"d:connections","type":"main","index":0}],[{"node":"d:ensureFolder","type":"main","index":0}]]},"d:ensureFolder":{"main":[[{"node":"Done","type":"main","index":0}]]},"d:download":{"main":[[{"node":"Shape download","type":"main","index":0}],[{"node":"Download Miss","type":"main","index":0}]]},"Shape download":{"main":[[{"node":"Done","type":"main","index":0}]]},"d:list":{"main":[[{"node":"Shape list","type":"main","index":0}]]},"Shape list":{"main":[[{"node":"Done","type":"main","index":0}]]},"d:upload":{"main":[[{"node":"Done","type":"main","index":0}]]},"d:move":{"main":[[{"node":"Done","type":"main","index":0}]]},"d:update":{"main":[[{"node":"Done","type":"main","index":0}]]},"d:delete":{"main":[[{"node":"Done","type":"main","index":0}]]},"d:createFromText":{"main":[[{"node":"Done","type":"main","index":0}]]},"Download Miss":{"main":[[{"node":"Done","type":"main","index":0}]]},"d:connections":{"main":[[{"node":"Shape connections","type":"main","index":0}]]},"Shape connections":{"main":[[{"node":"Done","type":"main","index":0}]]},"Guard Connection":{"main":[[{"node":"Op Switch","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"a1a0a2fd-ef82-5345-afb9-c3bc4bd93dc9","name":"app:drive"},{"updatedAt":"2026-07-30T23:41:29.646Z","createdAt":"2026-07-30T23:41:29.646Z","id":"9c337cfe-7feb-4f3d-ab26-3de6439357ce","name":"sm-refactore-v2.1"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"22f1e71e-91bf-48db-811f-8d3bc4e55a3e","name":"sm-refactor-v2.1"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"51804d94-1071-4213-980b-a06491a07895","name":"role:api"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"9c184b54-c105-4772-af0c-7cc6b603005c","name":"drive-app"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:41:36.846Z","createdAt":"2026-07-30T23:41:36.846Z","role":"workflow:owner","workflowId":"driveApi01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'driveApi01',
    name: 'drive api',
    active: true,
    description:
        'drive api — the seven canonical ops (contract ai/context/platform-service-contract.md §3), each one HTTP Request to the drive service. n8n holds NO Google credential: the service owns the connection and reports it on /readyz, so an op either runs on the account the operator selected or fails 503 naming why.',
    isArchived: false,
    tags: ['app:drive', 'sm-refactore-v2.1', 'sm-refactor-v2.1', 'role:api', 'drive-app'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1', binaryMode: 'separate' },
})
export class DriveApiWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'trig',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, 400],
    })
    WhenCalled = {
        workflowInputs: {
            values: [
                {
                    name: 'op',
                },
                {
                    name: 'params',
                    type: 'object',
                },
            ],
        },
    };

    @node({
        id: 'guard-connection-2026-08-24',
        name: 'Guard Connection',
        /*__n8n__*/ notes: "[missing link connection 2026-08-24, owner order] EARLY DETECTION lives HERE, once, for every caller. The drive service refuses automation calls without an explicit profile_id/connection_id (apps/drive/app.py, since 2026-08-21) — but a caller that passes connection_id: undefined drops the key silently, gets the refusal AFTER an HTTP round-trip, and its retry loops re-fire forever (measured 2026-08-24: 97 refusals from ONE document via extract_base_doc). This node names the failure BEFORE any HTTP: the error is 'missing link connection', the same phrase the lanes' MISSING_LINK/EXTRACTION_FAILED builds write, so a doc-side ERROR and a drive-side refusal read as one class. op:connections is exempt — it is the identity-FREE discovery op by design (caught live within minutes of the first guard deploy).",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [176, 400],
    })
    GuardConnection = {
        jsCode: `// Every FILE op an automation caller runs targets a specific drive — none can
// succeed without an explicit identity. 'connections' is the one identity-FREE op by design:
// it exists precisely so a caller with no connection can discover one (65ba24fd: "naming a
// connection was mandatory, discovering one impossible") — guarding it would re-create that
// deadlock.
for (const item of $input.all()) {
  if (String(item.json.op || '') === 'connections') continue;
  const p = item.json.params || {};
  if (!String(p.profile_id || '').trim() && !String(p.connection_id || '').trim()) {
    throw new Error('missing link connection: drive call requires explicit profile_id or connection_id (op=' + (item.json.op || '?') + ')');
  }
}
return $input.all();`,
    };

    @node({
        id: 'sw',
        name: 'Op Switch',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [240, 400],
    })
    OpSwitch = {
        rules: {
            values: [
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'download',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
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
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'list',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
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
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'upload',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
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
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'move',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
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
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'update',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
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
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'delete',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
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
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'createFromText',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
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
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'connections',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
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
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'ensureFolder',
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
        options: {},
    };

    @node({
        id: 'done',
        name: 'Done',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [768, 400],
    })
    Done = {};

    @node({
        id: 'ddl',
        name: 'd:download',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [512, 64],
        onError: 'continueErrorOutput',
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    DDownload = {
        method: 'POST',
        url: 'http://drive:8975/download',
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ JSON.stringify({ ...($json.params || {}), connection_id: ($json.params || {}).connection_id, profile_id: ($json.params || {}).profile_id }) }}',
        options: {
            timeout: 180000,
            response: {
                response: {
                    responseFormat: 'file',
                    outputPropertyName: 'data',
                },
            },
        },
    };

    @node({
        id: 'shdl',
        name: 'Shape download',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [700, 64],
    })
    ShapeDownload = {
        jsCode: `// preserve the GoogleDrive node's json passthrough ({op, params}) next to the
// binary. One item per driveApi01 call, so .first() is correct here.
const src=$('When Called').first().json;
return $input.all().map(i=>({json:{op:src.op, params:src.params}, binary:i.binary}));`,
    };

    @node({
        id: 'dls',
        name: 'd:list',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [512, 192],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    DList = {
        method: 'POST',
        url: 'http://drive:8975/list',
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ JSON.stringify({ ...($json.params || {}), connection_id: ($json.params || {}).connection_id, profile_id: ($json.params || {}).profile_id }) }}',
        options: {
            timeout: 180000,
        },
    };

    @node({
        id: 'shls',
        name: 'Shape list',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [700, 192],
    })
    ShapeList = {
        jsCode: `// one item per file — what fileFolder:search returned. Items are Drive's own
// resources, passed through untouched (callers read md5Checksum/createdTime/
// size/webViewLink/parents straight off them).
return ($input.first().json.files || []).map(f=>({json:f}));`,
    };

    @node({
        id: 'dcx',
        name: 'd:connections',
        /*__n8n__*/ notes: "[2026-08-21] Since the 2026-08-06 incident every drive op MUST name a profile_id or connection_id — an op with neither is refused rather than silently running against whichever account a human last picked in the console. That made naming mandatory and left no way to DISCOVER a name: automations that store a connection on a row (incoming_documents.LINK_CONNECTION, written at ingest by syncV3Deliver0001) had to be handed the id out of band, and a test or a fresh deployment had none to hand. GET /connections is the vault's own inventory; this exposes it through the same api layer as every other drive op, so nothing has to reach past driveApi01 to answer 'which connection is profile admin'.",
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [512, 900],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    DConnections = {
        method: 'GET',
        url: 'http://drive:8975/connections',
        options: {
            timeout: 30000,
        },
    };

    @node({
        id: 'shcx',
        name: 'Shape connections',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [700, 900],
    })
    ShapeConnections = {
        jsCode: `// One item per connection, plus the binding's own view so a caller can tell "the
// selected one" from "one that exists". Shaped like the other list ops (one item per thing)
// rather than returned as an envelope, so a caller filters with the same idioms it already uses:
//     items.filter(i => i.json.profile_id === 'admin')[0].json.connection_id
const j = $input.first().json || {};
const active = j.active || null;
return (j.connections || j.instances || []).map(c => ({json: {
  connection_id: c.id || c.connection_id || null,
  profile_id:    c.profile_id || null,
  kind:          c.kind || c.type || null,
  title:         c.title || c.label || null,
  is_active:     !!(active && (c.id || c.connection_id) === active),
}}));`,
    };

    @node({
        id: 'dup',
        name: 'd:upload',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [512, 320],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    DUpload = {
        method: 'POST',
        url: 'http://drive:8975/upload',
        sendBody: true,
        contentType: 'multipart-form-data',
        bodyParameters: {
            parameters: [
                {
                    name: 'name',
                    value: '={{ $json.params.name || $binary.data.fileName }}',
                },
                {
                    name: 'folderId',
                    value: "={{ $json.params.folderId || '' }}",
                },
                {
                    name: 'connection_id',
                    value: "={{ $json.params.connection_id || '' }}",
                },
                {
                    name: 'profile_id',
                    value: "={{ $json.params.profile_id || '' }}",
                },
                {
                    parameterType: 'formBinaryData',
                    name: 'file',
                    inputDataFieldName: 'data',
                },
            ],
        },
        options: {
            timeout: 180000,
        },
    };

    @node({
        id: 'dmv',
        name: 'd:move',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [512, 464],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    DMove = {
        method: 'POST',
        url: 'http://drive:8975/move',
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ JSON.stringify({ ...($json.params || {}), connection_id: ($json.params || {}).connection_id, profile_id: ($json.params || {}).profile_id }) }}',
        options: {
            timeout: 180000,
        },
    };

    @node({
        id: 'densure',
        name: 'd:ensureFolder',
        /*__n8n__*/ notes: "get-or-create a folder PATH on the named identity (drive app POST /ensureFolder, 2026-09-02) — {path:'automations/thumbnails', profile_id|connection_id} -> {id, path, created}. The folder primitive INDOX's BFF used to walk /api/folders for; automations ask here now.",
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [512, 720],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    DEnsurefolder = {
        method: 'POST',
        url: 'http://drive:8975/ensureFolder',
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ JSON.stringify({ ...($json.params || {}), connection_id: ($json.params || {}).connection_id, profile_id: ($json.params || {}).profile_id }) }}',
        options: {
            timeout: 60000,
        },
    };

    @node({
        id: 'dud',
        name: 'd:update',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [512, 592],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    DUpdate = {
        method: 'POST',
        url: 'http://drive:8975/update',
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ JSON.stringify({ ...($json.params || {}), connection_id: ($json.params || {}).connection_id, profile_id: ($json.params || {}).profile_id }) }}',
        options: {
            timeout: 180000,
        },
    };

    @node({
        id: 'ddel',
        name: 'd:delete',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [512, 720],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    DDelete = {
        method: 'POST',
        url: 'http://drive:8975/delete',
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ JSON.stringify({ ...($json.params || {}), connection_id: ($json.params || {}).connection_id, profile_id: ($json.params || {}).profile_id }) }}',
        options: {
            timeout: 180000,
        },
    };

    @node({
        id: 'dctx',
        name: 'd:createFromText',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [512, 848],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    DCreatefromtext = {
        method: 'POST',
        url: 'http://drive:8975/createFromText',
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ JSON.stringify({ ...($json.params || {}), connection_id: ($json.params || {}).connection_id, profile_id: ($json.params || {}).profile_id }) }}',
        options: {
            timeout: 180000,
        },
    };

    @node({
        id: 'g1downloadmiss0001',
        name: 'Download Miss',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [702, -66],
    })
    DownloadMiss = {
        jsCode: `// [g1 2026-08-09] A file that is not there is an ANSWER. Everything else still throws.
// 20 of the window's 82 errors were this node reporting \`Google Drive: File not found: <id>\`, and
// n8n logged every one as a failed execution -- so a source that has simply gone looked identical
// to the service being down, and the same id was re-attempted five times in a row. The owner's
// standing rule for the equivalent gmail-link case is \`needs_review\`, not an exception: a vanished
// source cannot be fixed by retrying, and an exception buys nothing but retries.
// Callers already cope with a binary-less result -- they gate on \`If Binary\` / \`If No Binary\` and
// route to their own FILE_NOT_FOUND branch -- so this is the shape they are already written for.
// A 5xx, a timeout or an auth refusal is NOT this and is re-thrown untouched: those are
// transient or operational, and the caller's retry is the correct response to them.
const e = $input.first().json || {};
const status = Number(e.httpCode || e.statusCode || e.status || (e.error || {}).code || 0);
const text = JSON.stringify(e).toLowerCase();
const notFound = status === 404
  || /file not found|could not be found|\\u05d4\\u05e7\\u05d5\\u05d1\\u05e5 \\u05d0\\u05d9\\u05e0\\u05d5/.test(text);
if (!notFound) {
  throw new Error(e.message || (e.error && e.error.message)
    || ('drive download failed (' + (status || 'no status') + ')'));
}
const src = $('When Called').first().json;
return [{ json: {
  ok: false,
  error: 'source_gone',
  needs_review: true,
  http_status: status || 404,
  op: src.op,
  params: src.params,
  message: e.message || 'the drive file this row points at does not resolve on the connection it names',
} }];
`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenCalled.out(0).to(this.GuardConnection.in(0));
        this.OpSwitch.out(0).to(this.DDownload.in(0));
        this.OpSwitch.out(1).to(this.DList.in(0));
        this.OpSwitch.out(2).to(this.DUpload.in(0));
        this.OpSwitch.out(3).to(this.DMove.in(0));
        this.OpSwitch.out(4).to(this.DUpdate.in(0));
        this.OpSwitch.out(5).to(this.DDelete.in(0));
        this.OpSwitch.out(6).to(this.DCreatefromtext.in(0));
        this.OpSwitch.out(7).to(this.DConnections.in(0));
        this.DDownload.out(0).to(this.ShapeDownload.in(0));
        this.DDownload.out(1).to(this.DownloadMiss.in(0));
        this.ShapeDownload.out(0).to(this.Done.in(0));
        this.DList.out(0).to(this.ShapeList.in(0));
        this.ShapeList.out(0).to(this.Done.in(0));
        this.DUpload.out(0).to(this.Done.in(0));
        this.DMove.out(0).to(this.Done.in(0));
        this.DUpdate.out(0).to(this.Done.in(0));
        this.DDelete.out(0).to(this.Done.in(0));
        this.DCreatefromtext.out(0).to(this.Done.in(0));
        this.OpSwitch.out(8).to(this.DEnsurefolder.in(0));
        this.DEnsurefolder.out(0).to(this.Done.in(0));
        this.DownloadMiss.out(0).to(this.Done.in(0));
        this.DConnections.out(0).to(this.ShapeConnections.in(0));
        this.ShapeConnections.out(0).to(this.Done.in(0));
        this.GuardConnection.out(0).to(this.OpSwitch.in(0));
    }
}
