import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Sync Deliver Link
// Nodes   : 10  |  Connections: 12
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenCalled                         executeWorkflowTrigger
// GetLinkMsg                         executeWorkflow            [onError→errorOutput]
// DownloadLink                       httpRequest                [onError→errorOutput] [retry]
// UploadLinkDoc                      executeWorkflow            [onError→errorOutput]
// LinkRow                            code                       [onError→errorOutput]
// CallDeliver                        executeWorkflow            [onError→errorOutput]
// RecordReq                          code
// CallRecord                         executeWorkflow            [retry]
// FailReq                            code
// CallFail                           executeWorkflow            [retry]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → GetLinkMsg
//      → DownloadLink
//        → UploadLinkDoc
//          → LinkRow
//            → CallDeliver
//              → RecordReq
//                → CallRecord
//             .out(1) → FailReq
//                → CallFail
//           .out(1) → FailReq (↩ loop)
//         .out(1) → FailReq (↩ loop)
//       .out(1) → FailReq (↩ loop)
//     .out(1) → FailReq (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: "One LINKED document: read the originating message, download the first http(s) link in its body, upload the file to the pipe's dest_folder, build the row from the uploaded copy plus the mail's evidence, DELIVER, RECORD. The feedback handle is the ORIGINATING MESSAGE. A message with no link is terminal. No label is written here.",
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"Get Link Msg","type":"main","index":0}]]},"Get Link Msg":{"main":[[{"node":"Download Link","type":"main","index":0}],[{"node":"Fail Req","type":"main","index":0}]]},"Download Link":{"main":[[{"node":"Upload Link Doc","type":"main","index":0}],[{"node":"Fail Req","type":"main","index":0}]]},"Upload Link Doc":{"main":[[{"node":"Link Row","type":"main","index":0}],[{"node":"Fail Req","type":"main","index":0}]]},"Link Row":{"main":[[{"node":"Call DELIVER","type":"main","index":0}],[{"node":"Fail Req","type":"main","index":0}]]},"Call DELIVER":{"main":[[{"node":"Record Req","type":"main","index":0}],[{"node":"Fail Req","type":"main","index":0}]]},"Record Req":{"main":[[{"node":"Call RECORD","type":"main","index":0}]]},"Fail Req":{"main":[[{"node":"Call FAIL","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"a659438c-0898-428d-aebd-72033caaefe4","name":"sync-v3"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"c7d4bdbd-9cb8-4595-90d4-b200420c3fd2","name":"role:sync"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: {},
    /*__n8n__*/ shared: [{"updatedAt":"2026-09-02T00:00:00.000Z","createdAt":"2026-09-02T00:00:00.000Z","role":"workflow:owner","workflowId":"syncDeliverLink01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'syncDeliverLink01',
    name: 'Sync Deliver Link',
    active: true,
    isArchived: false,
    tags: ['app:indox', 'indox', 'sync-v3', 'indox-app', 'role:sync'],
    settings: {
        errorWorkflow: 'errorHandler01',
        executionOrder: 'v1',
        executionTimeout: 600,
        callerPolicy: 'workflowsFromSameOwner',
        binaryMode: 'separate',
    },
})
export class SyncDeliverLinkWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'sdl-trig',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, 0],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'sdl-get',
        name: 'Get Link Msg',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [220, 0],
        onError: 'continueErrorOutput',
    })
    GetLinkMsg = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'get',
                params: '={{ ({ id: $json.platform_id, attachments: false, ...(($json.list_ctx||{}).connection_id ? { connection_id: $json.list_ctx.connection_id } : {}) }) }}',
            },
            matchingColumns: [],
            schema: [
                { id: 'op', displayName: 'op', required: false, display: true, type: 'string', canBeUsedToMatch: true },
                { id: 'params', displayName: 'params', required: false, display: true, type: 'object', canBeUsedToMatch: true },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: 'sdl-download',
        name: 'Download Link',
        /*__n8n__*/ notes: "The first http(s) URL in the message text/html, extracted in the url expression itself. No URL -> the expression yields the reserved host no-link-in-message.terminal.invalid (.invalid never resolves), the request fails with that host in its message, and Fail Req reads '.terminal.invalid' as the terminal marker -> needs_review at once, no retries. (An expression that THROWS is swallowed by n8n into undefined — measured: 'URL parameter must be a string, got undefined' — which is why the sentinel host, not a throw.)",
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [440, 0],
        onError: 'continueErrorOutput',
        retryOnFail: true,
        maxTries: 2,
        waitBetweenTries: 2000,
    })
    DownloadLink = {
        url: "={{ (() => { const t = String($json.text||'') + ' ' + String($json.html||''); const m = t.match(/https?:\\/\\/[^\\s\"'<>\\)]+/); return m ? m[0] : 'http://no-link-in-message.terminal.invalid/'; })() }}",
        options: {
            response: {
                response: {
                    responseFormat: 'file',
                },
            },
            timeout: 60000,
        },
    };

    @node({
        id: 'sdl-upload',
        name: 'Upload Link Doc',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [660, 0],
        onError: 'continueErrorOutput',
    })
    UploadLinkDoc = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'upload',
                params: "={{ ({ name: 'linked_'+$('When Called').first().json.platform_id, folderId: $('When Called').first().json.list_ctx.upload_folder_id, ...((($('When Called').first().json.list_ctx||{}).drive_connection_id) ? { connection_id: ($('When Called').first().json.list_ctx||{}).drive_connection_id } : ((($('When Called').first().json.list_ctx||{}).drive_profile_id) ? { profile_id: ($('When Called').first().json.list_ctx||{}).drive_profile_id } : {})) }) }}",
            },
            matchingColumns: [],
            schema: [
                { id: 'op', displayName: 'op', required: false, display: true, type: 'string', canBeUsedToMatch: true },
                { id: 'params', displayName: 'params', required: false, display: true, type: 'object', canBeUsedToMatch: true },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: 'sdl-row',
        name: 'Link Row',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [880, 0],
        onError: 'continueErrorOutput',
    })
    LinkRow = {
        jsCode: `const j=$('When Called').first().json; const up=$input.first().json||{};
const hash=up.md5Checksum||up.md5;
if(!hash) throw new Error('link upload returned no md5 for '+j.platform_id);
const lc=j.list_ctx||{};
const pipe=j.pipe||String(j.source||'').split('/').slice(1).join('/')||String(j.source||'');
const row={INLINE_ACTION:'DELIVER', NAME:up.name||('linked_'+j.platform_id), HASH:String(hash), LINK:up.webViewLink||up.link||null,
  CONNECTION:j.connection||null, SYNC_CONNECTION:j.connection||null, LINK_CONNECTION:lc.drive_connection_id||null,
  SOURCE_TYPE:'GMAIL_LINK', SOURCE_ID:j.platform_id, SOURCE_LINK:'https://mail.google.com/mail/u/0/#inbox/'+j.platform_id,
  SIZE:String(up.size||0), STATUS:j.status_override||'IN_PROGRESS', SYNC_NAME:pipe};
if(lc.type_hint) row.TYPE_BY_SOURCE=lc.type_hint;
try{
  const m=$('Get Link Msg').first().json||{};
  const subj=String(m.subject||'').trim(); const body=String(m.text||'').trim().slice(0,100);
  row.ATTACHMENT_TEXT=(subj+(body?' | '+body:'')).slice(0,400);
  const RE=/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z][A-Za-z]+/g;
  const SYS=['no-reply','noreply','mailer-daemon','donotreply','postmaster'];
  const f=m.from;
  const rawFrom=String((f&&f.value&&f.value[0]&&f.value[0].address)||f||'').trim().toLowerCase();
  const dispName=String((f&&f.value&&f.value[0]&&f.value[0].name)||'');
  const isSys=a=>SYS.some(x=>a.indexOf(x)>=0);
  const chain=[]; const push=a=>{ if(a&&!isSys(a)&&chain.indexOf(a)<0) chain.push(a); };
  if(isSys(rawFrom)){ const dn=(dispName.match(RE)||[])[0]; if(dn) push(dn.toLowerCase()); }
  (String(m.text||'').match(RE)||[]).forEach(a=>{ const l=a.toLowerCase(); if(l!==rawFrom) push(l); });
  push(rawFrom);
  if(chain.length) row.SENDER=chain.join(',');
  const __dd=(x)=>{const d=new Date(x);return isNaN(d)?null:(('0'+d.getDate()).slice(-2)+'/'+('0'+(d.getMonth()+1)).slice(-2)+'/'+d.getFullYear());};
  const rd=__dd(m.internalDate||m.date||m.received||null); const sd=__dd(m.date||m.internalDate||null);
  if(rd) row.RECEIVED_DATE=rd; if(sd) row.SEND_DATE=sd;
}catch(e){}
row.SYNC_REGISTRY_ID=pipe;
const fb=(j.feedback&&j.feedback.mode&&j.feedback.mode!=='off')?j.feedback:null;
row.SOURCE_LIST=[{origin:'self', doc_row_id:null, first_seen:new Date().toISOString(), dup_cause:null,
  source_kind:'mail', sync_registry_name:pipe||null, source_folder_id:null,
  file_id:up.id||null, message_id:j.platform_id||null, mailbox:j.connection||null, link:row.LINK, hash:row.HASH,
  link_connection:row.LINK_CONNECTION||null, sync_connection:row.SYNC_CONNECTION||null,
  required_feedback_type:fb?fb.mode:null, feedback_on_success:fb?!!fb.on_success:false, feedback_on_failure:fb?!!fb.on_failure:false,
  sync_feedback_completed:false, sync_feedback_outcome:null, sync_feedback_dest:null, sync_feedback_error:null, sync_feedback_at:null}];
row.__instance=String(j.__instance||'');
if(!row.__instance) throw new Error('delivery without __instance would create the document in the wrong tenant [terminal]');
return [{json:row}];`,
    };

    @node({
        id: 'sdl-deliver',
        name: 'Call DELIVER',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [1100, 0],
        onError: 'continueErrorOutput',
    })
    CallDeliver = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'sdl-record-req',
        name: 'Record Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1320, -80],
    })
    RecordReq = {
        jsCode: `const src=$('When Called').first().json; const d=$input.first().json||{};
try{ $execution.customData.set('outline', String(src.pipe||src.source||'link')+'_x1_delivered'); $execution.customData.set('exection_type','sync_deliver_link'); $execution.customData.set('pipe', String(src.pipe||src.source||'')); $execution.customData.set('instance', String(src.__instance||'')); }catch(e){}
return [{json:{op:'RECORD', source:src.source, platform_id:src.platform_id, doc_id:d.ID||null, content_hash:d.HASH||null, __instance:src.__instance||''}}];`,
    };

    @node({
        id: 'sdl-record',
        name: 'Call RECORD',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [1540, -80],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    CallRecord = {
        workflowId: {
            __rl: true,
            value: 'syncLedgerApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'sdl-fail-req',
        name: 'Fail Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1320, 140],
    })
    FailReq = {
        jsCode: `const src=$('When Called').first().json; const e=$input.first().json||{};
const raw=e.error&&typeof e.error==='object'?(e.error.message||JSON.stringify(e.error)):(e.error||e.message||'delivery failed');
const msg=String(raw).slice(0,500);
try{ $execution.customData.set('outline', String(src.pipe||src.source||'link')+'_x1_failed'); $execution.customData.set('exection_type','sync_deliver_link'); $execution.customData.set('pipe', String(src.pipe||src.source||'')); $execution.customData.set('instance', String(src.__instance||'')); }catch(e2){}
return [{json:{op:'FAIL', source:src.source, platform_id:src.platform_id, error:msg, terminal:/\\[terminal\\]|\\.terminal\\.invalid/i.test(msg),
  max_attempts:Number(src.max_attempts)||5, base_backoff_s:Number(src.base_backoff_s)||60, __instance:src.__instance||''}}];`,
    };

    @node({
        id: 'sdl-fail',
        name: 'Call FAIL',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [1540, 140],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    CallFail = {
        workflowId: {
            __rl: true,
            value: 'syncLedgerApi01',
            mode: 'id',
        },
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenCalled.out(0).to(this.GetLinkMsg.in(0));
        this.GetLinkMsg.out(0).to(this.DownloadLink.in(0));
        this.GetLinkMsg.out(1).to(this.FailReq.in(0));
        this.DownloadLink.out(0).to(this.UploadLinkDoc.in(0));
        this.DownloadLink.out(1).to(this.FailReq.in(0));
        this.UploadLinkDoc.out(0).to(this.LinkRow.in(0));
        this.UploadLinkDoc.out(1).to(this.FailReq.in(0));
        this.LinkRow.out(0).to(this.CallDeliver.in(0));
        this.LinkRow.out(1).to(this.FailReq.in(0));
        this.CallDeliver.out(0).to(this.RecordReq.in(0));
        this.CallDeliver.out(1).to(this.FailReq.in(0));
        this.RecordReq.out(0).to(this.CallRecord.in(0));
        this.FailReq.out(0).to(this.CallFail.in(0));
    }
}
