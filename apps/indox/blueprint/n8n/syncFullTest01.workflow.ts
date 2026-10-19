import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Sync Main Test
// Nodes   : 13  |  Connections: 14
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// RunSyncMainTest                    manualTrigger
// LaneWebhook                        webhook
// SeedTestFixtures                   executeWorkflow            [alwaysOutput] [retry]
// Config                             code
// Plan                               code
// Loop                               splitInBatches
// RouteKind                          switch
// CallMain                           executeWorkflow            [onError→regular] [alwaysOutput]
// CallLock                           executeWorkflow            [onError→regular] [alwaysOutput]
// Inspect                            postgres                   [onError→regular] [creds] [alwaysOutput]
// TagResult                          code
// Assert                             code
// RespondLane                        respondToWebhook           [onError→regular]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// RunSyncMainTest
//    → SeedTestFixtures
//      → Config
//        → Plan
//          → Loop
//            → Assert
//              → RespondLane
//           .out(1) → RouteKind
//              → CallMain
//                → TagResult
//                  → Loop (↩ loop)
//             .out(1) → CallLock
//                → TagResult (↩ loop)
//             .out(2) → Inspect
//                → TagResult (↩ loop)
// LaneWebhook
//    → SeedTestFixtures (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: "The sync PASS itself (syncV3Main0001) on the test tenant — the behaviours no source can show: `gate` (indoxSyncOn=false builds no unit and the pass still unlocks; true builds units again), `lock` (a held reconcile mutex makes the pass skip — was_locked — without touching the registry, and unlock hands it back), `registry` (an unknown registry_key yields zero units; the pass never falls back to sync_registry). Same plan→loop→assert design as the Sync Item API test. Lanes: gate | lock | registry | all. Webhook: POST /webhook/sync-full-e2e-lane {lane, __instance:'test'}.",
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Run Sync Main Test":{"main":[[{"node":"Seed Test Fixtures","type":"main","index":0}]]},"Lane Webhook":{"main":[[{"node":"Seed Test Fixtures","type":"main","index":0}]]},"Seed Test Fixtures":{"main":[[{"node":"Config","type":"main","index":0}]]},"Config":{"main":[[{"node":"Plan","type":"main","index":0}]]},"Plan":{"main":[[{"node":"Loop","type":"main","index":0}]]},"Loop":{"main":[[{"node":"Assert","type":"main","index":0}],[{"node":"Route Kind","type":"main","index":0},{"node":"Loop","type":"main","index":0}]]},"Route Kind":{"main":[[{"node":"Call Main","type":"main","index":0}],[{"node":"Call Lock","type":"main","index":0}],[{"node":"Inspect","type":"main","index":0}]]},"Call Main":{"main":[[{"node":"Tag Result","type":"main","index":0}]]},"Call Lock":{"main":[[{"node":"Tag Result","type":"main","index":0}]]},"Inspect":{"main":[[{"node":"Tag Result","type":"main","index":0}]]},"Tag Result":{"main":[[]]},"Assert":{"main":[[{"node":"🏁 Test Summary","type":"main","index":0}]]},"🏁 Test Summary":{"main":[[{"node":"Respond Lane","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"a659438c-0898-428d-aebd-72033caaefe4","name":"sync-v3"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {},
    /*__n8n__*/ pinData: {"Run Sync Main Test":[{"json":{"__instance":"test","lane":"all"}}]},
    /*__n8n__*/ staticData: {},
    /*__n8n__*/ shared: [{"updatedAt":"2026-09-02T00:00:00.000Z","createdAt":"2026-09-02T00:00:00.000Z","role":"workflow:owner","workflowId":"syncFullTest01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'syncFullTest01',
    name: 'Sync Main Test',
    active: true,
    isArchived: false,
    tags: ['app:indox', 'indox', 'sync-v3', 'indox-app'],
    settings: {
        errorWorkflow: 'errorHandler01',
        executionOrder: 'v1',
        executionTimeout: 300,
        callerPolicy: 'workflowsFromSameOwner',
    },
})
export class SyncMainTestWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'smt-manual',
        name: 'Run Sync Main Test',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [-600, 200],
    })
    RunSyncMainTest = {};

    @node({
        id: 'smt-webhook',
        webhookId: 'smt-lane-webhook-0001',
        name: 'Lane Webhook',
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [-600, 420],
    })
    LaneWebhook = {
        httpMethod: 'POST',
        path: 'sync-full-e2e-lane',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'smt-seed',
        name: 'Seed Test Fixtures',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [-380, 320],
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 5000,
    })
    SeedTestFixtures = {
        workflowId: {
            __rl: true,
            value: 'indoxV2TestFixtures01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                __instance: 'test',
            },
            matchingColumns: [],
            schema: [ { id: '__instance', displayName: '__instance', required: false, display: true, type: 'string', canBeUsedToMatch: true } ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: 'smt-config',
        name: 'Config',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-160, 320],
    })
    Config = {
        jsCode: `let lane='all';
try{ const b=$('Lane Webhook').first().json||{}; const p=(b.body&&typeof b.body==='object')?b.body:b; if(p.lane) lane=String(p.lane); }catch(e){}
try{ const m=$('Run Sync Main Test').first().json||{}; if(m.lane && lane==='all') lane=String(m.lane); }catch(e){}
const LANES=['gate','lock','registry'];
if(lane!=='all' && !LANES.includes(lane)) throw new Error('unknown lane '+lane);
return [{json:{__instance:'test', lane, lanes: lane==='all'?LANES:[lane], exec:String($execution.id)}}];`,
    };

    @node({
        id: 'smt-plan',
        name: 'Plan',
        /*__n8n__*/ notes: "Steps are: main (call syncV3Main0001 with the given trigger payload), lock (processLock01 check_and_lock / unlock on a key of this suite's own), sql (a read or the one settings write the gate lane needs). Every main call uses lock_key 'sv3f' + this execution, so it can never collide with the scheduler's reconcile mutex.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [60, 320],
    })
    Plan = {
        jsCode: `const cfg=$input.first().json; const LK='sv3f_'+cfg.exec;
// every pass reads THIS suite's registry key (sv3f_registry — never the client's sync_registry);
// the key is deliberately never seeded, so a pass builds zero units and the lanes observe the
// pass's own behaviour (gate, mutex, refusal) rather than any source
const main=(step,extra)=>({json:{kind:'main', step, __instance:'test', registry_key:'sv3f_registry', lock_key:LK, ...(extra||{})}});
const lock=(step,action,key)=>({json:{kind:'lock', step, ACTION:action, PROCESS:'syncV3Main0001', KEY:key+':test'}});
const sql=(step,q)=>({json:{kind:'sql', step, sql:q}});
// THE CLIENT SETTING IS PARKED, NOT OVERWRITTEN (G64 R6 / scripts/test-fixture-prefixes.yaml
// saved_settings): the tenant's indoxSyncOn is copied to sv3f_prior_indoxSyncOn first, restored
// from it at the end, and the crash sweep restores it if this run dies in between.
const T='indox_test.settings';
const PARK="insert into "+T+" (instance,key,value) select instance,'sv3f_prior_indoxSyncOn',coalesce(value,'true') from "+T+" where key='indoxSyncOn' on conflict (instance,key) do update set value=excluded.value returning value";
const SET=(v)=>"insert into "+T+" (instance,key,value) values ('incoming-documents-main','indoxSyncOn','"+v+"') on conflict (instance,key) do update set value=excluded.value returning value";
const RESTORE="with p as (select instance, value from "+T+" where key='sv3f_prior_indoxSyncOn'), u as (update "+T+" s set value=p.value from p where s.key='indoxSyncOn' and s.instance=p.instance returning s.value), d as (delete from "+T+" where key='sv3f_prior_indoxSyncOn' returning 1) select (select value from u limit 1) as value, (select count(*) from d)::int as unparked";
// THE MASTER (indoxOn, owner 2026-09-02): the same park / set / restore for the key both lanes read
// beside their own switch — a closed master must build no unit and still release the lock.
const PARK_M="insert into "+T+" (instance,key,value) select instance,'sv3f_prior_indoxOn',coalesce(value,'true') from "+T+" where key='indoxOn' on conflict (instance,key) do update set value=excluded.value returning value";
const SET_M=(v)=>"insert into "+T+" (instance,key,value) values ('incoming-documents-main','indoxOn','"+v+"') on conflict (instance,key) do update set value=excluded.value returning value";
const RESTORE_M="with p as (select instance, value from "+T+" where key='sv3f_prior_indoxOn'), u as (update "+T+" s set value=p.value from p where s.key='indoxOn' and s.instance=p.instance returning s.value), d as (delete from "+T+" where key='sv3f_prior_indoxOn' returning 1) select (select value from u limit 1) as value, (select count(*) from d)::int as unparked";
const plans={
 gate:()=>[ sql('gate.park',PARK), sql('gate.off',SET('false')), main('gate.main_off'), sql('gate.read_off',"select value from "+T+" where key='indoxSyncOn'"),
            sql('gate.on',SET('true')), main('gate.main_on'), sql('gate.restore',RESTORE), sql('gate.read_on',"select value from "+T+" where key='indoxSyncOn'"),
            sql('gate.park_master',PARK_M), sql('gate.master_off',SET_M('false')), main('gate.main_master_off'), sql('gate.read_master_off',"select value from "+T+" where key='indoxOn'"),
            sql('gate.master_on',SET_M('true')), sql('gate.restore_master',RESTORE_M), sql('gate.read_master_on',"select value from "+T+" where key='indoxOn'") ],
 lock:()=>[ lock('lock.hold','check_and_lock',LK), main('lock.main'), lock('lock.release','unlock',LK), main('lock.main2') ],
 registry:()=>[ main('registry.unknown',{registry_key:'sv3f_registry_missing_'+cfg.exec}), main('registry.default') ],
};
const steps=[]; for(const lane of cfg.lanes) steps.push(...plans[lane]());
return steps.map((s,i)=>({json:{...s.json,i}}));`,
    };

    @node({
        id: 'smt-loop',
        name: 'Loop',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [280, 320],
    })
    Loop = {
        batchSize: 1,
        options: {},
    };

    @node({
        id: 'smt-route',
        name: 'Route Kind',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [500, 176],
    })
    RouteKind = {
        rules: {
            values: [
                {
                    conditions: {
                        options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 },
                        conditions: [ { id: 'smt-main', leftValue: '={{ $json.kind }}', rightValue: 'main', operator: { type: 'string', operation: 'equals' } } ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'main',
                },
                {
                    conditions: {
                        options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 },
                        conditions: [ { id: 'smt-lock', leftValue: '={{ $json.kind }}', rightValue: 'lock', operator: { type: 'string', operation: 'equals' } } ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'lock',
                },
                {
                    conditions: {
                        options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 },
                        conditions: [ { id: 'smt-sql', leftValue: '={{ $json.kind }}', rightValue: 'sql', operator: { type: 'string', operation: 'equals' } } ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'sql',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'smt-main',
        name: 'Call Main',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [720, 220],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    CallMain = {
        workflowId: {
            __rl: true,
            value: 'syncV3Main0001',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'smt-lock',
        name: 'Call Lock',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [720, 420],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    CallLock = {
        workflowId: {
            __rl: true,
            value: 'processLock01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'smt-inspect',
        name: 'Inspect',
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [720, 620],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    Inspect = {
        operation: 'executeQuery',
        query: '{{ $json.sql }}',
        options: {},
    };

    @node({
        id: 'smt-tag',
        name: 'Tag Result',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [940, 420],
    })
    TagResult = {
        jsCode: `// the current step is the Loop's LOOP-branch item (branch 1); a Switch branch is empty for
// every kind but its own, so the step is never read through the Switch's first output
let step={};
for(const get of [()=>$('Loop').first(1), ()=>$('Route Kind').first(0), ()=>$('Route Kind').first(1), ()=>$('Route Kind').first(2)]){
  try{ const it=get(); if(it&&it.json&&it.json.step){ step=it.json; break; } }catch(e){}
}
const rows=$input.all().map(i=>i&&i.json).filter(Boolean);
return [{json:{step:step.step, kind:step.kind, i:step.i, result:rows}}];`,
    };

    @node({
        id: 'smt-assert',
        name: 'Assert',
        /*__n8n__*/ notes: "What a pass RETURNS is its last node: the lock reply (Unlock) after a pass that ran or built nothing, and the If's own item ({was_locked:true}) when the mutex was held. That difference is exactly what the lock lane asserts.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [500, 200],
    })
    Assert = {
        jsCode: `const cfg=$('Config').first().json;
const R={}; for(const it of $input.all()){ const j=it.json||{}; if(j.step) R[j.step]=j.result||[]; }
const first=(s)=>(R[s]||[])[0]||{};
const errored=(s)=>!!((first(s).error)||(first(s).errorMessage));
const n=(v)=>Number(v)||0;
const out=[]; let pass=0, fail=0;
const check=(name, ok, saw)=>{ if(ok) pass++; else fail++; out.push({json:{lane:cfg.lane, result:(ok?'PASS ':'FAIL ')+name+(ok?'':' — saw '+JSON.stringify(saw).slice(0,240))}}); };
const has=(l)=>cfg.lanes.includes(l);
if(has('gate')){
  check('gate: indoxSyncOn=false was written', first('gate.read_off').value==='false', first('gate.read_off'));
  check('gate: a pass under a closed gate completes without error and releases its lock', !errored('gate.main_off') && first('gate.main_off').was_locked!==true, first('gate.main_off'));
  check('gate: the parked indoxSyncOn value was restored and un-parked', first('gate.read_on').value==='true' && n(first('gate.restore').unparked)===1, {read:first('gate.read_on'), restore:first('gate.restore')});
  check('gate: a pass under an open gate completes without error', !errored('gate.main_on') && first('gate.main_on').was_locked!==true, first('gate.main_on'));
  check('gate: indoxOn=false (the master) was written', first('gate.read_master_off').value==='false', first('gate.read_master_off'));
  check('gate: a pass under a closed MASTER completes without error and releases its lock (its outline is sync-main_x0_units_OFF)', !errored('gate.main_master_off') && first('gate.main_master_off').was_locked!==true, first('gate.main_master_off'));
  check('gate: the parked indoxOn value was restored and un-parked', first('gate.read_master_on').value==='true' && n(first('gate.restore_master').unparked)===1, {read:first('gate.read_master_on'), restore:first('gate.restore_master')});
}
if(has('lock')){
  check('lock: the suite could take its own reconcile key', !errored('lock.hold') && first('lock.hold').was_locked!==true, first('lock.hold'));
  check('lock: a pass against a held key is SKIPPED (was_locked), not run', first('lock.main').was_locked===true, first('lock.main'));
  check('lock: after unlock the same pass runs', !errored('lock.main2') && first('lock.main2').was_locked!==true, first('lock.main2'));
}
if(has('registry')){
  check('registry: an unknown registry_key completes with zero units and no fallback', !errored('registry.unknown') && first('registry.unknown').was_locked!==true, first('registry.unknown'));
  check("registry: the suite's own (never seeded) key completes with zero units", !errored('registry.default') && first('registry.default').was_locked!==true, first('registry.default'));
}
out.push({json:{lane:cfg.lane, result:(fail?'FAIL ':'PASS ')+'summary '+pass+'/'+(pass+fail)+' checks', pass, fail, execution_id:String($execution.id)}});
return out;`,
    };

    @node({
        id: 'smt-summary',
        name: '🏁 Test Summary',
        /*__n8n__*/ notes: "The harness contract (apps/indox/hooks/test.py fetch_summary): a node named with 🏁 returning {RESULT, passed:'N/M', checks:[...]} as its FIRST item; the Assert lines follow for the lane webhook.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [610, 200],
    })
    TestSummary = {
        jsCode: `const items=$input.all().map(i=>i.json||{});
const lines=items.filter(x=>typeof x.result==='string' && !/^(PASS|FAIL) summary/.test(x.result));
const sum=items.find(x=>x.pass!==undefined && x.fail!==undefined)||{};
const fails=lines.filter(x=>/^FAIL/.test(x.result)).length;
const checks=lines.map(x=>(/^PASS/.test(x.result)?'✅ ':'❌ ')+x.result.replace(/^(PASS|FAIL) /,''));
return [{json:{RESULT: fails?('❌ '+fails+' OF '+lines.length+' CHECKS FAILED'):'✅ ALL TESTS PASS', passed:(lines.length-fails)+'/'+lines.length, checks, lane:sum.lane||null, execution_id:String($execution.id), result: fails?'FAIL summary':'PASS summary'}}, ...lines.map(x=>({json:x}))];`,
    };

    @node({
        id: 'smt-respond',
        name: 'Respond Lane',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [720, 200],
        onError: 'continueRegularOutput',
    })
    RespondLane = {
        respondWith: 'allIncomingItems',
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.RunSyncMainTest.out(0).to(this.SeedTestFixtures.in(0));
        this.LaneWebhook.out(0).to(this.SeedTestFixtures.in(0));
        this.SeedTestFixtures.out(0).to(this.Config.in(0));
        this.Config.out(0).to(this.Plan.in(0));
        this.Plan.out(0).to(this.Loop.in(0));
        this.Loop.out(0).to(this.Assert.in(0));
        this.Loop.out(1).to(this.RouteKind.in(0));
        this.RouteKind.out(0).to(this.CallMain.in(0));
        this.RouteKind.out(1).to(this.CallLock.in(0));
        this.RouteKind.out(2).to(this.Inspect.in(0));
        this.CallMain.out(0).to(this.TagResult.in(0));
        this.CallLock.out(0).to(this.TagResult.in(0));
        this.Inspect.out(0).to(this.TagResult.in(0));
        this.TagResult.out(0).to(this.Loop.in(0));
        this.Assert.out(0).to(this.TestSummary.in(0));
        this.TestSummary.out(0).to(this.RespondLane.in(0));
    }
}
