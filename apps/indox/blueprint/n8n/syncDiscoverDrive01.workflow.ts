import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Sync Discover Drive
// Nodes   : 6  |  Connections: 5
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenCalled                         executeWorkflowTrigger
// ListReq                            code
// List                               executeWorkflow            [alwaysOutput] [retry]
// UpsertReq                          code
// CallUpsert                         executeWorkflow            [alwaysOutput] [retry]
// Result                             code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → ListReq
//      → List
//        → UpsertReq
//          → CallUpsert
//            → Result
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: "The DISCOVERY stage for one drive pipe: list the to_sync folder — the folder is the pipe's SCOPE and nothing more — bounded by age at this level (OldDocumentMonthsBack, passed on the unit by Main), and UPSERT every file as a sync item with its listing metadata. on conflict do nothing: a file already discovered, claimed, delivered or failed is untouched; its lifecycle no longer depends on where it sits. Nothing is delivered here.",
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"List Req","type":"main","index":0}]]},"List Req":{"main":[[{"node":"List","type":"main","index":0}]]},"List":{"main":[[{"node":"Upsert Req","type":"main","index":0}]]},"Upsert Req":{"main":[[{"node":"Call UPSERT","type":"main","index":0}]]},"Call UPSERT":{"main":[[{"node":"Result","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"a659438c-0898-428d-aebd-72033caaefe4","name":"sync-v3"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"c7d4bdbd-9cb8-4595-90d4-b200420c3fd2","name":"role:sync"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: {},
    /*__n8n__*/ shared: [{"updatedAt":"2026-09-02T00:00:00.000Z","createdAt":"2026-09-02T00:00:00.000Z","role":"workflow:owner","workflowId":"syncDiscoverDrive01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'syncDiscoverDrive01',
    name: 'Sync Discover Drive',
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
export class SyncDiscoverDriveWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'sdrv-trig',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, 0],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'sdrv-list-req',
        name: 'List Req',
        /*__n8n__*/ notes: "createdAfter is the age bound AT DISCOVERY (owner rule): a file older than OldDocumentMonthsBack is never listed, let alone claimed. `months` arrives on the unit from Main's one config read, so a settings change takes effect on the next pass with no redeploy. `limit` caps the WHOLE window (the drive app pages internally, newest first): 2000 default / 5000 max — never one page, or the oldest files of a big folder would never be discovered. Identity is the pipe's connection_id (catalog) or profile_id (local).",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [220, 0],
    })
    ListReq = {
        jsCode: `const u=$input.first().json||{};
for(const k of ['source','list_ctx']) if(!u[k]) throw new Error('syncDiscoverDrive01: unit missing '+k);
const lc=u.list_ctx||{};
if(!lc.folderId) throw new Error('syncDiscoverDrive01: unit for '+u.source+' has no to_sync folderId');
const identity=lc.connection_id?{connection_id:lc.connection_id}:(lc.profile_id?{profile_id:lc.profile_id}:{});
const months=Number(u.months)>0?Number(u.months):6;
const cutoff=new Date(); cutoff.setUTCMonth(cutoff.getUTCMonth()-months);
// THE CAP IS THE WHOLE WINDOW, NOT ONE PAGE: the drive app pages internally (nextPageToken) up to
// \`limit\` and lists newest-first, so a cap smaller than the folder would silently hide the OLDEST
// files — forever, when a pipe has no destination folder to move delivered files out of scope
// (dest is optional). 2000 by default, 5000 at most; the age bound keeps the window finite.
const limit=Math.max(1,Math.min(5000,Number(u.page_size)||2000));
return [{json:{op:'list', params:{folderId:lc.folderId, limit, whatToSearch:'files', createdAfter:cutoff.toISOString(), ...identity}}}];`,
    };

    @node({
        id: 'sdrv-list',
        name: 'List',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [440, 0],
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    List = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: '={{ $json.op }}',
                params: '={{ ({ ...$json.params, ...($json.params.connection_id ? { connection_id: $json.params.connection_id } : ($json.params.profile_id ? { profile_id: $json.params.profile_id } : {})) }) }}',
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
        id: 'sdrv-upsert-req',
        name: 'Upsert Req',
        /*__n8n__*/ notes: "The listing persisted on the row is exactly what Deliver needs and nothing more (md5, name, size, link, createdTime, mimeType) — never the full Drive resource (~10 KB/file, which is what OOM-killed passes in the v3 unit).",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [660, 0],
    })
    UpsertReq = {
        jsCode: `const u=$('When Called').first().json||{};
const files=[];
for(const i of $input.all()){ const j=i&&i.json; if(!j) continue;
  if(Array.isArray(j.files)) files.push(...j.files); else if(Array.isArray(j.items)) files.push(...j.items); else if(j.id) files.push(j); }
// DEFENCE IN DEPTH ON THE AGE BOUND: the list request already carries createdAfter, but an
// engine that ignored it must still never put an old file into sync state (owner rule). A file
// older than OldDocumentMonthsBack by its own createdTime is dropped here; a file without a
// parseable createdTime is kept (the listing's bound already vouched for it).
const months=Number(u.months)>0?Number(u.months):6;
const cutoff=new Date(); cutoff.setUTCMonth(cutoff.getUTCMonth()-months);
const tooOld=(f)=>{ const t=Date.parse(f.createdTime||f.created_at||''); return Number.isFinite(t) && t < cutoff.getTime(); };
const dropped=files.filter(f=>f&&f.id&&tooOld(f)).length;
const items=files.filter(f=>f&&f.id&&!tooOld(f)).map(f=>({platform_id:String(f.id), listing:{id:String(f.id), name:f.name||null, md5:f.md5Checksum||f.md5||null,
  size:f.size!=null?Number(f.size):null, link:f.webViewLink||f.link||null, createdTime:f.createdTime||f.created_at||null, mimeType:f.mimeType||null}}));
return [{json:{op:'UPSERT', source:u.source, instance:u.instance||null, items, _listed:files.length, _too_old:dropped, __instance:String(u.__instance||'')}}];`,
    };

    @node({
        id: 'sdrv-upsert',
        name: 'Call UPSERT',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [880, 0],
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    CallUpsert = {
        workflowId: {
            __rl: true,
            value: 'syncLedgerApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'sdrv-result',
        name: 'Result',
        /*__n8n__*/ notes: "Echoes the unit (so Main can hand the same unit to Run) with the pass counts, and stamps the outline <pipe>_x<discovered>_of<listed>.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1100, 0],
    })
    Result = {
        jsCode: `const u=$('When Called').first().json||{}; const r=$input.first().json||{};
const listed=Number(($('Upsert Req').first().json||{})._listed)||0; const disc=Number(r.discovered)||0;
const cap=Number(($('List Req').first().json||{}).params?.limit)||0; const truncated=cap>0&&listed>=cap;
try{ $execution.customData.set('outline', String(u.pipe||u.source||'drive')+'_x'+disc+'_of'+listed+'_discovered'+(truncated?'_TRUNCATED':'')); $execution.customData.set('exection_type','sync_discover_drive'); $execution.customData.set('pipe', String(u.pipe||u.source||'')); $execution.customData.set('instance', String(u.__instance||'')); }catch(e){}
return [{json:{...u, _listed:listed, _discovered:disc, _truncated:truncated}}];`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenCalled.out(0).to(this.ListReq.in(0));
        this.ListReq.out(0).to(this.List.in(0));
        this.List.out(0).to(this.UpsertReq.in(0));
        this.UpsertReq.out(0).to(this.CallUpsert.in(0));
        this.CallUpsert.out(0).to(this.Result.in(0));
    }
}
