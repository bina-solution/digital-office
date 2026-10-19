import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Sync Deliver Drive
// Nodes   : 7  |  Connections: 7
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenCalled                         executeWorkflowTrigger
// DriveRow                           code                       [onError→errorOutput]
// CallDeliver                        executeWorkflow            [onError→errorOutput]
// RecordReq                          code
// CallRecord                         executeWorkflow            [retry]
// FailReq                            code
// CallFail                           executeWorkflow            [retry]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → DriveRow
//      → CallDeliver
//        → RecordReq
//          → CallRecord
//       .out(1) → FailReq
//          → CallFail
//     .out(1) → FailReq (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: "One DRIVE item, from its sync_item row alone: the row is built from `listing` (md5, name, size, link, createdTime persisted at discovery), delivered through indoxApi01 INLINE_ACTION DELIVER, and RECORDed. On any failure FAIL bumps the retry budget. No platform read, no folder move: the user-visible verdict mark is the state machine's source_feedback action (one writer), never this lane.",
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"Drive Row","type":"main","index":0}]]},"Drive Row":{"main":[[{"node":"Call DELIVER","type":"main","index":0}],[{"node":"Fail Req","type":"main","index":0}]]},"Call DELIVER":{"main":[[{"node":"Record Req","type":"main","index":0}],[{"node":"Fail Req","type":"main","index":0}]]},"Record Req":{"main":[[{"node":"Call RECORD","type":"main","index":0}]]},"Fail Req":{"main":[[{"node":"Call FAIL","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"a659438c-0898-428d-aebd-72033caaefe4","name":"sync-v3"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"c7d4bdbd-9cb8-4595-90d4-b200420c3fd2","name":"role:sync"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: {},
    /*__n8n__*/ shared: [{"updatedAt":"2026-09-02T00:00:00.000Z","createdAt":"2026-09-02T00:00:00.000Z","role":"workflow:owner","workflowId":"syncDeliverDrive01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'syncDeliverDrive01',
    name: 'Sync Deliver Drive',
    active: true,
    isArchived: false,
    tags: ['app:indox', 'indox', 'sync-v3', 'indox-app', 'role:sync'],
    settings: {
        errorWorkflow: 'errorHandler01',
        executionOrder: 'v1',
        executionTimeout: 300,
        callerPolicy: 'workflowsFromSameOwner',
        binaryMode: 'separate',
    },
})
export class SyncDeliverDriveWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'sdd-trig',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, 0],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'sdd-row',
        name: 'Drive Row',
        /*__n8n__*/ notes: "The document row from listing metadata only (thin contract 2026-08-31, ported from syncV3Deliver0001 'Drive Row'). SYNC_NAME is the plain pipe name; LINK is what the backend reported, never a template; SOURCE_LIST is the row's provenance written at birth; the 10 MB size gate refuses without downloading and stamps BASE_EXTRACTION_COMPLETED so the next sweep does not hand the file to OCR; __instance is routing identity for indoxApi01 and never reaches the INSERT. A missing md5 is a terminal failure (error output), not a retry.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [220, 0],
        onError: 'continueErrorOutput',
    })
    DriveRow = {
        jsCode: `const j=$input.first().json; const it=j.listing||{};
const hash=it.md5||it.md5Checksum;
if(!hash) throw new Error('drive item '+j.platform_id+' has no md5 in its listing [terminal]');
const lc=j.list_ctx||{}; const fid=lc.folderId||'';
const pipe=j.pipe||String(j.source||'').split('/').slice(1).join('/')||String(j.source||'');
const row={INLINE_ACTION:'DELIVER', NAME:it.name||j.platform_id, HASH:String(hash),
  LINK:it.link||it.webViewLink||null,
  CONNECTION:j.connection||null, LINK_CONNECTION:j.connection||null,
  SOURCE_TYPE:'GOOGLE_DRIVE_FOLDER', SOURCE_ID:j.platform_id,
  SOURCE_LINK:fid?('https://drive.google.com/drive/folders/'+fid):null,
  SIZE:String(it.size||0), STATUS:j.status_override||'IN_PROGRESS', SYNC_NAME:pipe};
if(lc.type_hint) row.TYPE_BY_SOURCE=lc.type_hint;
const fb=(j.feedback&&j.feedback.mode&&j.feedback.mode!=='off')?j.feedback:null;
row.SOURCE_LIST=[{origin:'self', doc_row_id:null, first_seen:new Date().toISOString(), dup_cause:null,
  source_kind:'drive', sync_registry_name:pipe||null, source_folder_id:fid||null,
  file_id:j.platform_id||null, message_id:null, mailbox:null, link:row.LINK, hash:row.HASH,
  link_connection:row.LINK_CONNECTION||null, sync_connection:null,
  required_feedback_type:fb?fb.mode:null, feedback_on_success:fb?!!fb.on_success:false, feedback_on_failure:fb?!!fb.on_failure:false,
  sync_feedback_completed:false, sync_feedback_outcome:null, sync_feedback_dest:null, sync_feedback_error:null, sync_feedback_at:null}];
const __dd=(x)=>{const d=new Date(x);return isNaN(d)?null:(('0'+d.getDate()).slice(-2)+'/'+('0'+(d.getMonth()+1)).slice(-2)+'/'+d.getFullYear());};
const cd=(it.createdTime||it.created_at)?__dd(it.createdTime||it.created_at):null;
if(cd){row.RECEIVED_DATE=cd; row.SEND_DATE=cd;}
row.SENDER='drive-folder:'+String(fid||'');
row.ATTACHMENT_TEXT=String(it.name||'').slice(0,400);
row.SYNC_REGISTRY_ID=pipe;
const MAX_BYTES=Number(lc.max_bytes||10485760); const bytes=Number(it.size||0);
if(bytes>MAX_BYTES){ row.STATUS='EXTRACTION_FAILED'; row.BASE_EXTRACTION_COMPLETED=true;
  row.REQUIRED_ACTION='Skipping.. File too big, '+(MAX_BYTES/1048576).toFixed(0)+'mb max ('+(bytes/1048576).toFixed(1)+'mb) — not downloaded, not extracted'; }
row.__instance=String(j.__instance||'');
if(!row.__instance) throw new Error('delivery without __instance would create the document in the wrong tenant [terminal]');
return [{json:row}];`,
    };

    @node({
        id: 'sdd-deliver',
        name: 'Call DELIVER',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [440, 0],
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
        id: 'sdd-record-req',
        name: 'Record Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [660, -80],
    })
    RecordReq = {
        jsCode: `const src=$('When Called').first().json; const d=$input.first().json||{};
try{ $execution.customData.set('outline', String(src.pipe||src.source||'drive')+'_x1_delivered'); $execution.customData.set('exection_type','sync_deliver_drive'); $execution.customData.set('pipe', String(src.pipe||src.source||'')); $execution.customData.set('instance', String(src.__instance||'')); }catch(e){}
return [{json:{op:'RECORD', source:src.source, platform_id:src.platform_id, doc_id:d.ID||null, content_hash:d.HASH||null, __instance:src.__instance||''}}];`,
    };

    @node({
        id: 'sdd-record',
        name: 'Call RECORD',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [880, -80],
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
        id: 'sdd-fail-req',
        name: 'Fail Req',
        /*__n8n__*/ notes: "Every error edge lands here. An error whose message carries the [terminal] marker is promoted straight to needs_review (retrying cannot fix a listing without md5); anything else takes the equal-jitter backoff and comes back through TAKE when not_before passes. The marker is a SUFFIX on purpose: n8n's Code-node error wrapper strips a 'PREFIX: ' from thrown messages (measured 2026-09-02 — 'TERMINAL: message has no…' arrived as 'message has no… [line 19]').",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [660, 120],
    })
    FailReq = {
        jsCode: `const src=$('When Called').first().json; const e=$input.first().json||{};
const raw=e.error&&typeof e.error==='object'?(e.error.message||JSON.stringify(e.error)):(e.error||e.message||'delivery failed');
const msg=String(raw).slice(0,500);
try{ $execution.customData.set('outline', String(src.pipe||src.source||'drive')+'_x1_failed'); $execution.customData.set('exection_type','sync_deliver_drive'); $execution.customData.set('pipe', String(src.pipe||src.source||'')); $execution.customData.set('instance', String(src.__instance||'')); }catch(e2){}
return [{json:{op:'FAIL', source:src.source, platform_id:src.platform_id, error:msg, terminal:/\\[terminal\\]|\\.terminal\\.invalid/i.test(msg),
  max_attempts:Number(src.max_attempts)||5, base_backoff_s:Number(src.base_backoff_s)||60, __instance:src.__instance||''}}];`,
    };

    @node({
        id: 'sdd-fail',
        name: 'Call FAIL',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [880, 120],
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
        this.WhenCalled.out(0).to(this.DriveRow.in(0));
        this.DriveRow.out(0).to(this.CallDeliver.in(0));
        this.DriveRow.out(1).to(this.FailReq.in(0));
        this.CallDeliver.out(0).to(this.RecordReq.in(0));
        this.CallDeliver.out(1).to(this.FailReq.in(0));
        this.RecordReq.out(0).to(this.CallRecord.in(0));
        this.FailReq.out(0).to(this.CallFail.in(0));
    }
}
