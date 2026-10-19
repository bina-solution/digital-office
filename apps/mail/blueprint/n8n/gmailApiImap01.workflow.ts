import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : mail api
// Nodes   : 18  |  Connections: 26
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenCalled                         executeWorkflowTrigger
// OpSwitch                           switch
// HttpSearch                         httpRequest
// HttpGet                            httpRequest
// HttpAddlabels                      httpRequest
// HttpRemovelabels                   httpRequest
// HttpListlabels                     httpRequest
// HttpCreatelabel                    httpRequest
// HttpAppend                         httpRequest
// HttpSend                           httpRequest
// ShapeSearch                        code
// ShapeLabelret                      code
// ShapeListlabels                    code
// ShapeGet                           code
// Done                               noOp
// HttpSearchraw                      httpRequest
// HttpGetthread                      httpRequest
// ShapeGetthread                     code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → OpSwitch
//      → HttpSearch
//        → ShapeSearch
//          → Done
//     .out(1) → HttpGet
//        → ShapeGet
//          → Done (↩ loop)
//     .out(2) → HttpAddlabels
//        → ShapeLabelret
//          → Done (↩ loop)
//     .out(3) → HttpRemovelabels
//        → ShapeLabelret (↩ loop)
//     .out(4) → HttpListlabels
//        → ShapeListlabels
//          → Done (↩ loop)
//     .out(5) → HttpCreatelabel
//        → Done (↩ loop)
//     .out(6) → HttpAppend
//        → Done (↩ loop)
//     .out(7) → HttpSend
//        → Done (↩ loop)
//     .out(8) → HttpGetthread
//        → ShapeGetthread
//          → Done (↩ loop)
//     .out(9) → HttpSearchraw
//        → Done (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"Op Switch","type":"main","index":0}]]},"Op Switch":{"main":[[{"node":"http:search","type":"main","index":0}],[{"node":"http:get","type":"main","index":0}],[{"node":"http:addLabels","type":"main","index":0}],[{"node":"http:removeLabels","type":"main","index":0}],[{"node":"http:listLabels","type":"main","index":0}],[{"node":"http:createLabel","type":"main","index":0}],[{"node":"http:append","type":"main","index":0}],[{"node":"http:send","type":"main","index":0}],[{"node":"http:getThread","type":"main","index":0}],[{"node":"http:searchRaw","type":"main","index":0}]]},"http:search":{"main":[[{"node":"shape:search","type":"main","index":0}]]},"shape:search":{"main":[[{"node":"Done","type":"main","index":0}]]},"http:get":{"main":[[{"node":"shape:get","type":"main","index":0}]]},"shape:get":{"main":[[{"node":"Done","type":"main","index":0}]]},"http:addLabels":{"main":[[{"node":"shape:labelRet","type":"main","index":0}]]},"http:removeLabels":{"main":[[{"node":"shape:labelRet","type":"main","index":0}]]},"shape:labelRet":{"main":[[{"node":"Done","type":"main","index":0}]]},"http:listLabels":{"main":[[{"node":"shape:listLabels","type":"main","index":0}]]},"shape:listLabels":{"main":[[{"node":"Done","type":"main","index":0}]]},"http:createLabel":{"main":[[{"node":"Done","type":"main","index":0}]]},"http:append":{"main":[[{"node":"Done","type":"main","index":0}]]},"http:send":{"main":[[{"node":"Done","type":"main","index":0}]]},"http:getThread":{"main":[[{"node":"shape:getThread","type":"main","index":0}]]},"shape:getThread":{"main":[[{"node":"Done","type":"main","index":0}]]},"http:searchRaw":{"main":[[{"node":"Done","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"333960da-8376-4dd1-8b39-c3d4b448ca86","name":"mail-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"51804d94-1071-4213-980b-a06491a07895","name":"role:api"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"cf994cba-b6d0-53fa-8729-2b8d0c21b28f","name":"app:mail"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:43:25.358Z","createdAt":"2026-07-30T23:43:25.358Z","role":"workflow:owner","workflowId":"gmailApiImap01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'gmailApiImap01',
    name: 'mail api',
    active: true,
    isArchived: false,
    tags: ['mail-app', 'role:api', 'app:mail'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class MailApiWorkflow {
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
                    type: 'string',
                },
                {
                    name: 'params',
                    type: 'object',
                },
            ],
        },
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
                    outputKey: 'search',
                    conditions: {
                        options: {
                            caseSensitive: true,
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'search',
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
                    outputKey: 'get',
                    conditions: {
                        options: {
                            caseSensitive: true,
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'get',
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
                    outputKey: 'addLabels',
                    conditions: {
                        options: {
                            caseSensitive: true,
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'addLabels',
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
                    outputKey: 'removeLabels',
                    conditions: {
                        options: {
                            caseSensitive: true,
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'removeLabels',
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
                    outputKey: 'listLabels',
                    conditions: {
                        options: {
                            caseSensitive: true,
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'listLabels',
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
                    outputKey: 'createLabel',
                    conditions: {
                        options: {
                            caseSensitive: true,
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'createLabel',
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
                    outputKey: 'append',
                    conditions: {
                        options: {
                            caseSensitive: true,
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'append',
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
                    outputKey: 'send',
                    conditions: {
                        options: {
                            caseSensitive: true,
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'send',
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
                    outputKey: 'getThread',
                    conditions: {
                        options: {
                            caseSensitive: true,
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'getThread',
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
                    outputKey: 'searchRaw',
                    conditions: {
                        options: {
                            caseSensitive: true,
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'searchRaw',
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
        id: 'httpsearch',
        name: 'http:search',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [480, 80],
        retryOnFail: false,
    })
    HttpSearch = {
        method: 'POST',
        url: 'http://mailapi:8970/search',
        options: {
            timeout: 120000,
        },
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ $json.params }}',
    };

    @node({
        id: 'httpget',
        name: 'http:get',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [480, 190],
        retryOnFail: false,
    })
    HttpGet = {
        method: 'GET',
        url: "=http://mailapi:8970/message/{{ $json.params.uid || 0 }}?id={{ $json.params.id || '' }}&folder={{ $json.params.folder || 'INBOX' }}&attachments={{ $json.params.attachments==false?'false':'true' }}&meta={{ $json.params.meta?'true':'false' }}&connection_id={{ $json.params.connection_id || '' }}",
        options: {
            // 300 s, was 120 s (2026-09-02, measured on the server): ONE IMAP connection per mailbox
            // is the rule, so N parallel deliveries queue on it inside mailapi — the last fetch of a
            // batch legitimately waits for the others (attachments, tens of seconds each). A 120 s
            // wait aborted the queued calls ("connection was aborted") and cancelled the deliveries;
            // the reaper then re-queued the same items for the same outcome. Waiting is correct here;
            // the registry's batch.chunk bounds how many wait.
            timeout: 300000,
        },
    };

    @node({
        id: 'httpaddlabels',
        name: 'http:addLabels',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [480, 300],
        retryOnFail: false,
    })
    HttpAddlabels = {
        method: 'POST',
        url: 'http://mailapi:8970/labels/add',
        options: {
            timeout: 120000,
        },
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ $json.params }}',
    };

    @node({
        id: 'httpremovelabels',
        name: 'http:removeLabels',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [480, 410],
        retryOnFail: false,
    })
    HttpRemovelabels = {
        method: 'POST',
        url: 'http://mailapi:8970/labels/remove',
        options: {
            timeout: 120000,
        },
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ $json.params }}',
    };

    @node({
        id: 'httplistlabels',
        name: 'http:listLabels',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [480, 520],
        retryOnFail: false,
    })
    HttpListlabels = {
        method: 'GET',
        url: "=http://mailapi:8970/labels?connection_id={{ ($json.params || {}).connection_id || '' }}",
        options: {
            timeout: 120000,
        },
    };

    @node({
        id: 'httpcreatelabel',
        name: 'http:createLabel',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [480, 630],
        retryOnFail: false,
    })
    HttpCreatelabel = {
        method: 'POST',
        url: 'http://mailapi:8970/labels/create',
        options: {
            timeout: 120000,
        },
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ $json.params }}',
    };

    @node({
        id: 'httpappend',
        name: 'http:append',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [480, 740],
        retryOnFail: false,
    })
    HttpAppend = {
        method: 'POST',
        url: 'http://mailapi:8970/append',
        options: {
            timeout: 120000,
        },
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ $json.params }}',
    };

    @node({
        id: 'httpsend',
        name: 'http:send',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [480, 850],
        retryOnFail: false,
    })
    HttpSend = {
        method: 'POST',
        url: 'http://mailapi:8970/send',
        options: {
            timeout: 120000,
        },
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ $json.params }}',
    };

    @node({
        id: 'shapesearch',
        name: 'shape:search',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [620, 80],
    })
    ShapeSearch = {
        mode: 'runOnceForAllItems',
        jsCode: `// reshape service /search ({messages:[...]}) -> N items in Gmail getAll shape (one per message).
// Scanners loop these and read $json.id, so emit one item per message with id present.
const r = $input.first().json;
const msgs = (r && r.messages) || [];
return msgs.map(m => ({ json: {
  id: m.id, threadId: m.threadId,
  labelIds: m.labels || [], labels: m.labels || [],
  From: m.from, Subject: m.subject, date: m.date,
  hasAttachment: !!m.hasAttachment, uid: m.uid
} }));`,
    };

    @node({
        id: 'shapelabelret',
        name: 'shape:labelRet',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [620, 340],
    })
    ShapeLabelret = {
        mode: 'runOnceForAllItems',
        jsCode: `// add/remove labels: surface the message id at top level (Gmail's addLabels returns the
// message, so downstream nodes read $json.id after a tag step). Service returns {ok,uids,...}.
const t = $('When Called').first().json.params || {};
const id = t.id || (Array.isArray(t.ids) ? t.ids[0] : '') || '';
return [{ json: { id, ...$input.first().json } }];`,
    };

    @node({
        id: 'shapelist',
        name: 'shape:listLabels',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [620, 520],
    })
    ShapeListlabels = {
        mode: 'runOnceForAllItems',
        jsCode: `// reshape service /labels ({labels:[names]}) -> N items {id,name} like Gmail label getAll.
// Labels are name-keyed in the imap backend (the service maps names<->X-GM-LABELS), so id=name:
// any downstream name->id map then resolves name->name, and addLabels by that 'id' applies the name.
const r = $input.first().json;
const names = (r && r.labels) || [];
return names.map(n => ({ json: { id: n, name: n } }));`,
    };

    @node({
        id: 'shapeget',
        name: 'shape:get',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [620, 190],
    })
    ShapeGet = {
        mode: 'runOnceForAllItems',
        jsCode: `// reshape service /message -> Gmail get(simple=false) shape incl $binary, so downstream
// downloader nodes ($json.from.value[0].address, $json.text, $json.headers.subject, $binary) are untouched.
const j = $input.first().json;
const addr = s => { const m = (s||'').match(/<([^>]+)>/); return m ? m[1] : (s||'').trim(); };
const name = s => (s||'').replace(/<[^>]*>/,'').replace(/"/g,'').trim();
const bin = {};
const atts = j.attachments || [];
for (let i=0;i<atts.length;i++){ const a=atts[i]; if(!a.data_base64) continue; bin['attachment_'+i] = await this.helpers.prepareBinaryData(Buffer.from(a.data_base64, 'base64'), a.filename||('attachment_'+i), a.mimeType||'application/octet-stream'); }
// attachment METADATA (name/mime/size) — present in BOTH full and meta mode; the Label Engine
// classifies on these (never the bytes), so meta mode skips the multi-MB attachment download.
// \`inline\` = the HTML body embeds this part by its Content-ID (<img src="cid:...">). That, not
// Content-Disposition, is what separates a signature/notification logo from a document: Gmail's
// own bounce mail sends its 5.7 KB icon.png as disposition=ATTACHMENT with a cid the body uses.
// Decided here because this is the one layer that sees both; the flag is additive and false
// unless BOTH are present, so no existing caller can notice it.
const html = (j.body_html||'') + (j.body_text||'');
const cidUsed = c => !!c && html.toLowerCase().includes('cid:'+String(c).toLowerCase());
const attachmentsMeta = atts.map((a,i)=>({ fileName:a.filename||('attachment_'+i), mimeType:a.mimeType||'application/octet-stream', fileSize:a.size||0, contentId:a.content_id||'', inline:cidUsed(a.content_id) }));
return [{ json: {
  id: j.id, threadId: j.threadId,
  From: j.from, To: j.to,
  from: { value: [{ address: addr(j.from), name: name(j.from) }], text: j.from },
  to: { value: [{ address: addr(j.to), name: name(j.to) }], text: j.to },
  subject: j.subject,
  headers: { subject: j.subject, from: j.from, to: j.to, date: j.date },
  date: j.date,
  text: j.body_text || '', textPlain: j.body_text || '', html: j.body_html || '', textHtml: j.body_html || '',
  labels: j.labels || [], labelIds: j.labels || [],
  attachmentsMeta
}, binary: bin }];`,
    };

    @node({
        id: 'done',
        name: 'Done',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [920, 400],
    })
    Done = {};

    @node({
        id: 'httpsearchraw',
        name: 'http:searchRaw',
        /*__n8n__*/ notes: "Same call as http:search, but wired straight to Done — no shape:search reshape. shape:search collapses the /search envelope into N per-message items and drops uidvalidity/uidnext/has_more/next_cursor in the process, which is fine for every existing 'search' caller (they only ever wanted the messages) but wrong for an incremental-cursor caller that needs those fields to detect a UID-space invalidation (INDOX-UNIFIED-N8N-SPEC.md §3 — see mailDiscovery01). Additive-only: no existing op's path changes.",
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [480, 1120],
        retryOnFail: false,
    })
    HttpSearchraw = {
        method: 'POST',
        url: 'http://mailapi:8970/search',
        options: {
            timeout: 120000,
        },
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ $json.params }}',
    };

    @node({
        id: '50118644-8466-460c-baf7-d8c8418dc4a9',
        name: 'http:getThread',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [480, 960],
    })
    HttpGetthread = {
        method: 'GET',
        url: "=http://mailapi:8970/thread/{{ $json.params.id || $json.params.tid || 0 }}?connection_id={{ ($json.params || {}).connection_id || '' }}",
        options: {
            timeout: 120000,
        },
    };

    @node({
        id: 'c9fba44d-9335-4e11-93db-24e1e8ccdcf0',
        name: 'shape:getThread',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [620, 960],
    })
    ShapeGetthread = {
        mode: 'runOnceForAllItems',
        jsCode: `// reshape service /thread -> add the Gmail-cased aliases the rule engine's buildThread()
// already falls back to (From/Subject/text/textPlain/html/textHtml), so BS_TO_SYNC /
// CORRESPONDENCE_STARTED / BS_REPORT_REQUEST see the real subject+body instead of nothing.
// mailapi's own field names (from/subject/body_text/body_html) are left in place too —
// this is additive, not a rename, so nothing that already reads the lowercase fields breaks.
const j = $input.first().json;
const messages = (j.messages || []).map(m => ({
  ...m,
  From: m.from, Subject: m.subject,
  text: m.body_text || '', textPlain: m.body_text || '',
  html: m.body_html || '', textHtml: m.body_html || ''
}));
return [{ json: { ...j, messages } }];`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenCalled.out(0).to(this.OpSwitch.in(0));
        this.OpSwitch.out(0).to(this.HttpSearch.in(0));
        this.OpSwitch.out(1).to(this.HttpGet.in(0));
        this.OpSwitch.out(2).to(this.HttpAddlabels.in(0));
        this.OpSwitch.out(3).to(this.HttpRemovelabels.in(0));
        this.OpSwitch.out(4).to(this.HttpListlabels.in(0));
        this.OpSwitch.out(5).to(this.HttpCreatelabel.in(0));
        this.OpSwitch.out(6).to(this.HttpAppend.in(0));
        this.OpSwitch.out(7).to(this.HttpSend.in(0));
        this.OpSwitch.out(8).to(this.HttpGetthread.in(0));
        this.OpSwitch.out(9).to(this.HttpSearchraw.in(0));
        this.HttpSearch.out(0).to(this.ShapeSearch.in(0));
        this.ShapeSearch.out(0).to(this.Done.in(0));
        this.HttpGet.out(0).to(this.ShapeGet.in(0));
        this.ShapeGet.out(0).to(this.Done.in(0));
        this.HttpAddlabels.out(0).to(this.ShapeLabelret.in(0));
        this.HttpRemovelabels.out(0).to(this.ShapeLabelret.in(0));
        this.ShapeLabelret.out(0).to(this.Done.in(0));
        this.HttpListlabels.out(0).to(this.ShapeListlabels.in(0));
        this.ShapeListlabels.out(0).to(this.Done.in(0));
        this.HttpCreatelabel.out(0).to(this.Done.in(0));
        this.HttpAppend.out(0).to(this.Done.in(0));
        this.HttpSend.out(0).to(this.Done.in(0));
        this.HttpGetthread.out(0).to(this.ShapeGetthread.in(0));
        this.ShapeGetthread.out(0).to(this.Done.in(0));
        this.HttpSearchraw.out(0).to(this.Done.in(0));
    }
}
