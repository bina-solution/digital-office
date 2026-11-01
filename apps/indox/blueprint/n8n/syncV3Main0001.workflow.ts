import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Sync Main
// Nodes   : 10  |  Connections: 11
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenCalled                         executeWorkflowTrigger
// TryLock                            executeWorkflow            [alwaysOutput] [retry]
// LockAcquired                       if
// ReadConfig                         postgres                   [creds] [retry]
// BuildPipes                         code
// RouteSource                        switch
// DiscoverDriveEach                  executeWorkflow            [onError→regular] [alwaysOutput]
// DiscoverGmailEach                  executeWorkflow            [onError→regular] [alwaysOutput]
// RunEach                            executeWorkflow            [onError→regular] [alwaysOutput]
// Unlock                             executeWorkflow            [onError→regular] [alwaysOutput] [retry]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → TryLock
//      → LockAcquired
//       .out(1) → ReadConfig
//          → BuildPipes
//            → RouteSource
//              → DiscoverDriveEach
//                → RunEach
//                  → Unlock
//             .out(1) → DiscoverGmailEach
//                → RunEach (↩ loop)
//             .out(2) → Unlock (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: "The sync pass for one tenant, called by indox01 (the only clock) with __instance. Under the reconcile mutex: ONE config read (indoxSyncOn + the registry + the age bound, straight off the tenant's settings table the way the drainer reads its own gate), build one unit per enabled v3 pipe (drive: one per pair), run DISCOVERY for each (waited), then hand the same units to RUN (not waited). Nothing else: no run-state stamping, no continue-pass loop, no diff — the queue lives in sync_ledger and is inspectable between the two stages.",
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"Try Lock","type":"main","index":0}]]},"Try Lock":{"main":[[{"node":"Lock Acquired?","type":"main","index":0}]]},"Lock Acquired?":{"main":[[],[{"node":"Read Config","type":"main","index":0}]]},"Read Config":{"main":[[{"node":"Build Pipes","type":"main","index":0}]]},"Build Pipes":{"main":[[{"node":"Route Source","type":"main","index":0}]]},"Route Source":{"main":[[{"node":"Discover Drive Each","type":"main","index":0}],[{"node":"Discover Gmail Each","type":"main","index":0}],[{"node":"Unlock","type":"main","index":0}]]},"Discover Drive Each":{"main":[[{"node":"Run Each","type":"main","index":0}]]},"Discover Gmail Each":{"main":[[{"node":"Run Each","type":"main","index":0}]]},"Run Each":{"main":[[{"node":"Unlock","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"a659438c-0898-428d-aebd-72033caaefe4","name":"sync-v3"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"c7d4bdbd-9cb8-4595-90d4-b200420c3fd2","name":"role:sync"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: {},
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"syncV3Main0001","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'syncV3Main0001',
    name: 'Sync Main',
    active: true,
    isArchived: false,
    tags: ['app:indox', 'indox', 'sync-v3', 'indox-app', 'role:sync'],
    settings: {
        errorWorkflow: 'errorHandler01',
        executionOrder: 'v1',
        executionTimeout: 900,
        callerPolicy: 'workflowsFromSameOwner',
    },
})
export class SyncMainWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'smn-trig',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, 0],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'smn-try-lock',
        name: 'Try Lock',
        /*__n8n__*/ notes: "Reconcile mutex per tenant (key reconcile:<instance>; a suite passes lock_key to hold its own). Redis ttl is the backstop if a pass dies without unlocking.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [220, 0],
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    TryLock = {
        workflowId: {
            __rl: true,
            value: 'processLock01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                ACTION: 'check_and_lock',
                PROCESS: 'syncV3Main0001',
                KEY: "={{ (() => { try { const t = $('When Called').first().json || {}; const base = t.lock_key ? String(t.lock_key) : 'reconcile'; const inst = String(t.__instance || ''); return inst ? base + ':' + inst : base; } catch (e) { return 'reconcile'; } })() }}",
            },
            matchingColumns: [],
            schema: [],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: 'smn-lock-acquired',
        name: 'Lock Acquired?',
        /*__n8n__*/ notes: "true output = a pass is already running for this tenant: stop here, do NOT unlock (we do not hold it). false output = proceed.",
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [440, 0],
    })
    LockAcquired = {
        conditions: {
            options: { caseSensitive: true, typeValidation: 'loose', version: 2 },
            conditions: [ { id: 'smn-already-running', leftValue: '={{ $json.was_locked === true }}', rightValue: true, operator: { type: 'boolean', operation: 'true', singleValue: true } } ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: 'smn-read-config',
        name: 'Read Config',
        /*__n8n__*/ notes: "ONE read, the tenant's own settings table (schema indox_<__instance>; an empty __instance makes the schema name invalid and the pass fails loudly — there is no public fallback). Returns: sync_on (indoxSyncOn, COALESCE 'true' so a missing row can never dark-stop sync — the drainer's own doctrine), months (OldDocumentMonthsBack, default 24 — the age bound discovery applies), and every registry row for this tenant under the requested key (registry_key on the trigger for suites; default sync_registry).",
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [660, 80],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 1000,
    })
    ReadConfig = {
        operation: 'executeQuery',
        query: "={{ (() => { const t = $('When Called').first().json || {}; const inst = String(t.__instance || '').trim(); if (!/^[a-z][a-z0-9_]*$/.test(inst)) { throw new Error('sync pass carries no valid __instance — refusing to read a registry (no public fallback)'); } const key = String(t.registry_key || 'sync_registry').replace(/'/g, \"''\"); const S = 'indox_' + inst; return \"select coalesce((select value from \" + S + \".settings where key='indoxSyncOn' order by updated_at desc nulls last limit 1),'true') as sync_on, coalesce((select value from \" + S + \".settings where key='indoxOn' order by updated_at desc nulls last limit 1),'true') as indox_on, coalesce((select value from \" + S + \".settings where key='OldDocumentMonthsBack' order by updated_at desc nulls last limit 1),'6') as months, coalesce((select jsonb_agg(jsonb_build_object('instance', s.instance, 'value', s.value)) from \" + S + \".settings s where s.key='\" + key + \"'), '[]'::jsonb) as registries\"; })() }}",
        options: {},
    };

    @node({
        id: 'smn-build-pipes',
        name: 'Build Pipes',
        /*__n8n__*/ notes: "One unit per enabled v3 pipe — drive: one per pair (list_ctx.folderId = the pair's to_sync, the SCOPE); gmail / gmail-link: one per entry with its label keys, search, upload identity and attachment filters. The unit carries __instance (tenant schema — the only tenant boundary), months (age bound), and the delivery context every stage needs, so no stage has to read config again. indoxSyncOn=false or nothing enabled -> a single 'none' item that goes straight to Unlock. Scope: {sync} / {syncs[]} on the trigger runs one pipe (suites).",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [880, 80],
    })
    BuildPipes = {
        jsCode: `const cfg=$input.first().json||{};
let t={}; try{ t=$('When Called').first().json||{}; }catch(e){}
const inst=String(t.__instance||'').trim();
// OldDocumentMonthsBack: THE age bound every discovery applies (owner rule: an older item is
// never even listed into sync state). The fixture seeds 6; a missing row reads as 6 as well.
const months=Number(cfg.months)>0?Number(cfg.months):6;
// indoxOn is THE master (owner 2026-09-02): off = no sync AND no drain, whatever the two lane
// switches say; both lanes read it beside their own switch, so a lane switched off stays off when
// the master comes back. A missing row reads as on (COALESCE 'true'), like the lane switches.
const indoxOn=String(cfg.indox_on==null?'true':cfg.indox_on).toLowerCase()==='true';
const syncOn=indoxOn && String(cfg.sync_on==null?'true':cfg.sync_on).toLowerCase()==='true';
// label KEY -> Gmail label NAME (tag_rules). A key with no rule is used literally, so a registry
// that already stores the label name (the phase-3 editor's shape) resolves without any rule row.
// label KEY -> Gmail label NAME from the ONE rules store (the mail app's organizer settings,
// owner Decision N1 2026-09-03) — never a Postgres copy. A key with no rule is used literally, so
// a registry that already stores the label name resolves without any rule row.
let lmap={};
try{ const o=await this.helpers.httpRequest({method:'GET', url:'http://mailapi:8970/organizer/settings', json:true, timeout:15000});
  const L=(((o||{}).gmail||{}).labels)||{}; for(const [k,v] of Object.entries(L)){ if(v&&v.name) lmap[k]=String(v.name); } }
catch(e){ lmap={}; }
const lname=k=>{ if(k===undefined||k===null||k==='') return null; const n=lmap[String(k)]; return String((n&&String(n).trim())||k).trim(); };
let scope=null; if(Array.isArray(t.syncs)&&t.syncs.length) scope=t.syncs.map(String); else if(t.sync) scope=[String(t.sync)];
const regs=[];
let rows=cfg.registries; if(typeof rows==='string'){ try{rows=JSON.parse(rows);}catch(e){rows=[];} }
for(const r of (Array.isArray(rows)?rows:[])){
  if(!r||r.value===undefined||r.value===null||r.value==='') continue;
  const comp=String(r.instance||'').trim(); if(!comp) throw new Error('settings row carries a registry but no instance column — refusing to guess');
  let entries=r.value; if(typeof entries==='string'){ try{entries=JSON.parse(entries);}catch(e){entries=[];} }
  for(const e of (Array.isArray(entries)?entries:[])) regs.push({comp, s:e});
}
const units=[]; const skipped={scope:0,disabled:0,engine:0};
if(syncOn){
 for(const {comp,s} of regs){
  if(!s||!s.name) continue;
  if(scope&&!scope.includes(String(s.name))){ skipped.scope++; continue; }
  if(s.enabled===false){ skipped.disabled++; continue; }
  if(s.engine!=='v3'){ skipped.engine++; continue; }
  const common={__instance:inst, source:comp+'/'+s.name, pipe:s.name, instance:comp, months,
    connection:s.connection||null, conn_kind:s.source||null, label_keys:s.labels||{},
    feedback:(s.feedback&&s.feedback.mode)?s.feedback:null,
    take:(s.batch&&s.batch.take)||25, chunk:(s.batch&&s.batch.chunk)||25, page_size:(s.batch&&s.batch.page_size)||50,
    max_attempts:s.max_attempts||5, base_backoff_s:s.base_backoff_s||60, status_override:s.status_override||null};
  const kind=s.v3_kind||(String(s.name||'').includes('gmail-link')?'gmail-link':s.source);
  if(kind==='drive'){
    for(const p of (s.pairs||[])) units.push({json:{...common, src_kind:'drive',
      list_ctx:{folderId:p.to_sync||p.from, pair:p, type_hint:s.type_hint||null, connection_id:s.connection||null, profile_id:s.profile_id||null, max_bytes:Number(s.max_bytes||10485760)}}});
  } else if(kind==='gmail'||kind==='gmail-link'){
    units.push({json:{...common, src_kind:kind,
      list_ctx:{to_sync_label:lname((s.labels||{}).to_sync), query:s.v3_query||null, search_extra:s.search_extra||null,
        upload_folder_id:s.dest_folder||null, type_hint:s.type_hint||null,
        connection_id:s.connection||s.connection_id||null,
        drive_connection_id:s.drive_connection_id||null, drive_profile_id:s.drive_profile_id||null,
        skip_inline_attachments:s.skip_inline_attachments===true, att_exts:s.att_exts||null, att_max_bytes:s.att_max_bytes||null,
        source_type:s.source_type||null, message_link_base:(s.message_link_base!==undefined?s.message_link_base:null)}}});
  }
 }
}
try{ $execution.customData.set('outline', 'sync-main_x'+units.length+'_units'+(syncOn?'':'_OFF')); $execution.customData.set('exection_type','sync_main'); $execution.customData.set('instance', inst); $execution.customData.set('units', String(units.length)); }catch(e){}
if(!units.length) return [{json:{_no_units:true, status:'noop', src_kind:'none', sync_on:syncOn, _seen:regs.length, _skipped:skipped, __instance:inst}}];
return units;`,
    };

    @node({
        id: 'smn-route',
        name: 'Route Source',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [1100, 80],
    })
    RouteSource = {
        rules: {
            values: [
                {
                    conditions: {
                        options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 },
                        conditions: [ { id: 'smn-drive', leftValue: '={{ $json.src_kind }}', rightValue: 'drive', operator: { type: 'string', operation: 'equals' } } ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'drive',
                },
                {
                    conditions: {
                        options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 },
                        conditions: [ { id: 'smn-gmail', leftValue: '={{ $json.src_kind }}', rightValue: 'gmail', operator: { type: 'string', operation: 'startsWith' } } ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'gmail',
                },
            ],
        },
        options: {
            fallbackOutput: 'extra',
            renameFallbackOutput: 'none',
        },
    };

    @node({
        id: 'smn-discover-drive',
        name: 'Discover Drive Each',
        /*__n8n__*/ notes: "Waited: the unit's rows must exist before Run takes them. The Discover workflow echoes the unit back, which is what Run receives.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [1320, -80],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    DiscoverDriveEach = {
        workflowId: {
            __rl: true,
            value: 'syncDiscoverDrive01',
            mode: 'id',
        },
        mode: 'each',
        options: {},
    };

    @node({
        id: 'smn-discover-gmail',
        name: 'Discover Gmail Each',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [1320, 80],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    DiscoverGmailEach = {
        workflowId: {
            __rl: true,
            value: 'syncDiscoverGmail01',
            mode: 'id',
        },
        mode: 'each',
        options: {},
    };

    @node({
        id: 'smn-run-each',
        name: 'Run Each',
        /*__n8n__*/ notes: "Not waited: each Run is its own execution and fans its deliveries out further. The pass returns as soon as every unit is dispatched; the mutex is released right after.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [1540, 0],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    RunEach = {
        workflowId: {
            __rl: true,
            value: 'syncRun01',
            mode: 'id',
        },
        mode: 'each',
        options: {
            waitForSubWorkflow: false,
        },
    };

    @node({
        id: 'smn-unlock',
        name: 'Unlock',
        /*__n8n__*/ notes: "executeOnce: one release however many units flowed in. onError:continueRegularOutput so a failed unlock falls through to the Redis ttl instead of throwing the pass into its errorWorkflow.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1760, 80],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
        executeOnce: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    Unlock = {
        workflowId: {
            __rl: true,
            value: 'processLock01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                ACTION: 'unlock',
                PROCESS: 'syncV3Main0001',
                KEY: "={{ (() => { try { const t = $('When Called').first().json || {}; const base = t.lock_key ? String(t.lock_key) : 'reconcile'; const inst = String(t.__instance || ''); return inst ? base + ':' + inst : base; } catch (e) { return 'reconcile'; } })() }}",
            },
            matchingColumns: [],
            schema: [],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenCalled.out(0).to(this.TryLock.in(0));
        this.TryLock.out(0).to(this.LockAcquired.in(0));
        this.LockAcquired.out(1).to(this.ReadConfig.in(0));
        this.ReadConfig.out(0).to(this.BuildPipes.in(0));
        this.BuildPipes.out(0).to(this.RouteSource.in(0));
        this.RouteSource.out(0).to(this.DiscoverDriveEach.in(0));
        this.RouteSource.out(1).to(this.DiscoverGmailEach.in(0));
        this.RouteSource.out(2).to(this.Unlock.in(0));
        this.DiscoverDriveEach.out(0).to(this.RunEach.in(0));
        this.DiscoverGmailEach.out(0).to(this.RunEach.in(0));
        this.RunEach.out(0).to(this.Unlock.in(0));
    }
}
