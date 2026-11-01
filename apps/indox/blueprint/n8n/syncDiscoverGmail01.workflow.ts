import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Sync Discover Gmail
// Nodes   : 10  |  Connections: 9
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenCalled                         executeWorkflowTrigger
// CursorReq                          code
// CallCursorGet                      executeWorkflow            [alwaysOutput] [retry]
// SearchReq                          code
// Search                             executeWorkflow            [alwaysOutput] [retry]
// UpsertReq                          code
// CallUpsert                         executeWorkflow            [alwaysOutput] [retry]
// CursorSetReq                       code
// CallCursorSet                      executeWorkflow            [retry]
// Result                             code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → CursorReq
//      → CallCursorGet
//        → SearchReq
//          → Search
//            → UpsertReq
//              → CallUpsert
//                → CursorSetReq
//                  → CallCursorSet
//                    → Result
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: "The DISCOVERY stage for one mail pipe — mailDiscovery01's UID walk folded into the sync architecture (replaces it). Read the pipe's cursor, search the mailbox ONCE with since_uid (history is walked forward from the bottom, never anchored at the top: a brand-new pipe starts at uid 1 and arrives at steady state on its own, page_size matches per pass), UPSERT every match as a sync item keyed by MESSAGE ID with its listing (uid, subject, sender, date), then advance the cursor to the highest uid actually observed, clamped to the service's own next_cursor. A UIDVALIDITY change is not a branch: the pass keeps what it found (message ids do not change) and re-anchors the walk at the bottom for the next pass. The label is the pipe's SCOPE and nothing else — nothing here writes a label, moves a message or delivers anything.",
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"Cursor Req","type":"main","index":0}]]},"Cursor Req":{"main":[[{"node":"Call CURSOR_GET","type":"main","index":0}]]},"Call CURSOR_GET":{"main":[[{"node":"Search Req","type":"main","index":0}]]},"Search Req":{"main":[[{"node":"Search","type":"main","index":0}]]},"Search":{"main":[[{"node":"Upsert Req","type":"main","index":0}]]},"Upsert Req":{"main":[[{"node":"Call UPSERT","type":"main","index":0}]]},"Call UPSERT":{"main":[[{"node":"Cursor Set Req","type":"main","index":0}]]},"Cursor Set Req":{"main":[[{"node":"Call CURSOR_SET","type":"main","index":0}]]},"Call CURSOR_SET":{"main":[[{"node":"Result","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"a659438c-0898-428d-aebd-72033caaefe4","name":"sync-v3"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"c7d4bdbd-9cb8-4595-90d4-b200420c3fd2","name":"role:sync"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: {},
    /*__n8n__*/ shared: [{"updatedAt":"2026-09-02T00:00:00.000Z","createdAt":"2026-09-02T00:00:00.000Z","role":"workflow:owner","workflowId":"syncDiscoverGmail01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'syncDiscoverGmail01',
    name: 'Sync Discover Gmail',
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
export class SyncDiscoverGmailWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'sdgm-trig',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, 0],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'sdgm-cursor-req',
        name: 'Cursor Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [220, 0],
    })
    CursorReq = {
        jsCode: `const u=$input.first().json||{};
for(const k of ['source','list_ctx']) if(!u[k]) throw new Error('syncDiscoverGmail01: unit missing '+k);
if(!(u.list_ctx||{}).to_sync_label && !(u.list_ctx||{}).query) throw new Error('syncDiscoverGmail01: pipe '+u.source+' has no to_sync label — the registry entry needs labels.to_sync (a tag_rules key or the label name itself); a test unit may pass list_ctx.query instead');
return [{json:{op:'CURSOR_GET', source:u.source, __instance:String(u.__instance||'')}}];`,
    };

    @node({
        id: 'sdgm-cursor-get',
        name: 'Call CURSOR_GET',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [440, 0],
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    CallCursorGet = {
        workflowId: {
            __rl: true,
            value: 'syncLedgerApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'sdgm-search-req',
        name: 'Search Req',
        /*__n8n__*/ notes: "ONE search shape (mailDiscovery01's 2026-08-09 lesson kept verbatim): since_uid = the stored cursor, or 1 when there is none — never a no-since search, whose newest-first truncation plants the mark at the top of the mailbox and buries the history under it. Query = label:<to_sync name, spaces as hyphens> + the pipe's search_extra; newer_than:<OldDocumentMonthsBack>m is appended when search_extra does not carry its own window, so the age bound holds at discovery. limit = page_size: the walk advances that many matches per pass.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [660, 0],
    })
    SearchReq = {
        jsCode: `const u=$('When Called').first().json||{}; const lc=u.list_ctx||{};
const cur=($input.first().json)||{}; const hasCursor=!!cur.source;
const walkToken=hasCursor&&cur.walk_token!=null?String(cur.walk_token):null;
const steady=hasCursor?parseInt(cur.steady_cursor||'0',10):0;
// the SCOPE: the pipe's to_sync tag; a unit without one (a test driving a raw query) searches the query alone
const parts=lc.to_sync_label?['label:'+String(lc.to_sync_label).trim().replace(/\\s+/g,'-')]:[];
if(lc.query) parts.push(String(lc.query).trim());
if(lc.search_extra) parts.push(String(lc.search_extra).trim());
// THE AGE BOUND IS THE SETTING'S, ALWAYS (owner rule 2026-09-02): OldDocumentMonthsBack rides on
// the unit as 'months' and is appended on every search. A pipe's own search_extra may carry a
// newer_than of its own — both terms are ANDed by the search, so a pipe can only TIGHTEN the
// window, never widen it past the setting.
const months=Number(u.months)>0?Number(u.months):6;
parts.push('newer_than:'+months+'m');
const q=parts.filter(Boolean).join(' ');
const limit=Math.max(1,Math.min(1000,Number(u.page_size)||50));
const params={folder:'[Gmail]/All Mail', query:q, limit, since_uid:(steady>0?steady:1)};
if(lc.connection_id) params.connection_id=lc.connection_id;
return [{json:{op:'searchRaw', params, _cursor:{walk_token:walkToken, steady_cursor:(steady>0?String(steady):null)}}}];`,
    };

    @node({
        id: 'sdgm-search',
        name: 'Search',
        /*__n8n__*/ notes: "[2026-09-02] SOFT-FAIL AFTER THE RETRIES: a search that still fails (the client's mailbox answers a 6-month label search in 50–125 s; one crossed the HTTP timeout at 06:23) reaches Upsert Req as an error item and ends this unit with its own 'search failed' error — a normal sub-execution failure Main's continueRegularOutput absorbs into the pass — instead of an n8n-internal crash of the whole pass. The next pass retries the unit.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [880, 0],
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 3000,
        onError: 'continueRegularOutput',
    })
    Search = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'sdgm-upsert-req',
        name: 'Upsert Req',
        /*__n8n__*/ notes: "Items keyed by MESSAGE ID (what Deliver's get uses; uids are per-mailbox and rotate on UIDVALIDITY). Listing = uid, subject, from, date, hasAttachment — evidence Deliver may reuse, never a body. The next cursor is decided here too: highest uid observed, clamped to next_cursor (an unsolicited FETCH can carry a message far above the page — measured, execution 520781), never moved backwards, kept when the page is empty, uidnext-1 only when the service confirms nothing is left AND there was no cursor. On a UIDVALIDITY change the stored numbers belong to a namespace that no longer exists: keep the messages (ids are stable), write the new token, and re-anchor at 1 so the next pass walks the new space from the bottom.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1100, 0],
    })
    UpsertReq = {
        jsCode: `const u=$('When Called').first().json||{};
const req=$('Search Req').first().json||{}; const prev=req._cursor||{};
const resp=$input.first().json||{};
if(resp.error&&!Array.isArray(resp.messages)) throw new Error('search failed: '+String(resp.error&&resp.error.message||resp.error).slice(0,300));
const msgs=Array.isArray(resp.messages)?resp.messages:[];
// DEFENCE IN DEPTH ON THE AGE BOUND: the search already carries newer_than, but a backend that
// ignored it (or a message with a far-off Date header) must still never enter sync state. A
// message older than OldDocumentMonthsBack by its own date is dropped here; an unparseable date
// is kept (the search's bound already vouched for it).
const months=Number(u.months)>0?Number(u.months):6;
const cutoff=new Date(); cutoff.setUTCMonth(cutoff.getUTCMonth()-months);
const tooOld=(m)=>{ const t=Date.parse(m.date||m.internalDate||''); return Number.isFinite(t) && t < cutoff.getTime(); };
const dropped=msgs.filter(m=>m&&tooOld(m)).length;
const items=msgs.filter(m=>m&&(m.id!==undefined&&m.id!==null&&m.id!=='')&&!tooOld(m)).map(m=>({platform_id:String(m.id),
  listing:{id:String(m.id), uid:(typeof m.uid==='number')?m.uid:null, threadId:m.threadId||null, subject:m.subject||null,
    from:(m.from&&typeof m.from==='object')?((m.from.value&&m.from.value[0]&&m.from.value[0].address)||m.from.text||null):(m.from||null),
    date:m.date||null, hasAttachment:!!m.hasAttachment}}));
const uids=msgs.map(m=>m&&m.uid).filter(x=>typeof x==='number');
const observedMax=uids.length?Math.max(...uids):null;
const prevSteady=prev.steady_cursor!=null?parseInt(prev.steady_cursor,10):null;
const caughtUp=resp.has_more===false;
const newToken=(resp.uidvalidity!==undefined&&resp.uidvalidity!==null)?String(resp.uidvalidity):null;
const invalidated=!!(prev.walk_token&&newToken&&prev.walk_token!==newToken);
let anchor=observedMax;
if(typeof resp.next_cursor==='number'&&anchor!=null) anchor=Math.min(anchor,resp.next_cursor);
if(anchor==null) anchor=prevSteady;
if(anchor==null&&caughtUp&&resp.uidnext) anchor=resp.uidnext-1;
if(prevSteady!=null&&anchor!=null&&anchor<prevSteady) anchor=prevSteady;
if(invalidated) anchor=1;
const cursorSet={op:'CURSOR_SET', source:u.source, mode:(invalidated||!caughtUp)?'walk':'steady',
  walk_token:newToken||prev.walk_token||null, steady_cursor:anchor!=null?String(anchor):null, __instance:String(u.__instance||'')};
return [{json:{op:'UPSERT', source:u.source, instance:u.instance||null, items, __instance:String(u.__instance||''),
  _listed:msgs.length, _too_old:dropped, _has_more:resp.has_more===true, _backlog:resp.total!=null?resp.total:null, _invalidated:invalidated, _cursor_set:cursorSet}}];`,
    };

    @node({
        id: 'sdgm-upsert',
        name: 'Call UPSERT',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [1320, 0],
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
        id: 'sdgm-cursor-set-req',
        name: 'Cursor Set Req',
        /*__n8n__*/ notes: "Written only AFTER the upsert succeeded: a cursor that advanced past rows that were never written would bury them for good. If UPSERT failed, this node is never reached and the next pass re-lists the same page.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1540, 0],
    })
    CursorSetReq = {
        jsCode: `const up=$('Upsert Req').first().json||{}; const r=$input.first().json||{};
const cs=up._cursor_set||{};
if(!cs.source) throw new Error('no cursor decision on the upsert request');
return [{json:{...cs, _discovered:Number(r.discovered)||0}}];`,
    };

    @node({
        id: 'sdgm-cursor-set',
        name: 'Call CURSOR_SET',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [1760, 0],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    CallCursorSet = {
        workflowId: {
            __rl: true,
            value: 'syncLedgerApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'sdgm-result',
        name: 'Result',
        /*__n8n__*/ notes: "Echoes the unit (Main hands the same unit to Run) with the pass counts; outline <pipe>_x<discovered>_of<listed>_<walk|steady>.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1980, 0],
    })
    Result = {
        jsCode: `const u=$('When Called').first().json||{}; const up=$('Upsert Req').first().json||{}; const cs=$('Cursor Set Req').first().json||{};
const listed=Number(up._listed)||0; const disc=Number(cs._discovered)||0;
try{ $execution.customData.set('outline', String(u.pipe||u.source||'gmail')+'_x'+disc+'_of'+listed+'_'+String(cs.mode||'walk')); $execution.customData.set('exection_type','sync_discover_gmail'); $execution.customData.set('pipe', String(u.pipe||u.source||'')); $execution.customData.set('instance', String(u.__instance||'')); }catch(e){}
return [{json:{...u, _listed:listed, _discovered:disc, _walk_mode:cs.mode||null, _cursor_after:cs.steady_cursor||null, _has_more:up._has_more===true, _backlog:up._backlog, _invalidated:up._invalidated===true}}];`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenCalled.out(0).to(this.CursorReq.in(0));
        this.CursorReq.out(0).to(this.CallCursorGet.in(0));
        this.CallCursorGet.out(0).to(this.SearchReq.in(0));
        this.SearchReq.out(0).to(this.Search.in(0));
        this.Search.out(0).to(this.UpsertReq.in(0));
        this.UpsertReq.out(0).to(this.CallUpsert.in(0));
        this.CallUpsert.out(0).to(this.CursorSetReq.in(0));
        this.CursorSetReq.out(0).to(this.CallCursorSet.in(0));
        this.CallCursorSet.out(0).to(this.Result.in(0));
    }
}
