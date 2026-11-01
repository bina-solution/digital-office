import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Sync Item API Test
// Nodes   : 12  |  Connections: 13
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// RunSyncItemApiTest                 manualTrigger
// LaneWebhook                        webhook
// SeedTestFixtures                   executeWorkflow            [alwaysOutput] [retry]
// Config                             code
// Plan                               code
// Loop                               splitInBatches
// RouteKind                          switch
// CallApi                            executeWorkflow            [onError→regular] [alwaysOutput]
// Inspect                            postgres                   [onError→regular] [creds] [alwaysOutput]
// TagResult                          code
// Assert                             code
// RespondLane                        respondToWebhook           [onError→regular]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// RunSyncItemApiTest
//    → SeedTestFixtures
//      → Config
//        → Plan
//          → Loop
//            → Assert
//              → RespondLane
//           .out(1) → RouteKind
//              → CallApi
//                → TagResult
//                  → Loop (↩ loop)
//             .out(1) → Inspect
//                → TagResult (↩ loop)
// LaneWebhook
//    → SeedTestFixtures (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: "The kernel suite for the SYNC ITEM (2026-09-02): every op of the Sync Item API (syncLedgerApi01) proven against the test tenant — UPSERT (idempotent, refreshes a non-delivered listing), TAKE (bounded, oldest-first, claimed, skips rows with no listing), RECORD, FAIL (equal-jitter backoff, [terminal] and max_attempts promote to needs_review), RESET (statuses filter, cursor kept on a scoped retry, purge), REAP (stuck claims released with backoff), CURSOR_GET/SET and GATE. One design instead of 94 nodes: a lane is a PLAN of steps; one loop runs each step through the API (or a read-only inspect query), one Assert reads the results by step name. Lanes: upsert | take | record | fail | reset | reap | cursor | gate | all. Lane webhook: POST /webhook/sync-kernel-e2e-lane {lane, __instance:'test'}.",
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Run Sync Item API Test":{"main":[[{"node":"Seed Test Fixtures","type":"main","index":0}]]},"Lane Webhook":{"main":[[{"node":"Seed Test Fixtures","type":"main","index":0}]]},"Seed Test Fixtures":{"main":[[{"node":"Config","type":"main","index":0}]]},"Config":{"main":[[{"node":"Plan","type":"main","index":0}]]},"Plan":{"main":[[{"node":"Loop","type":"main","index":0}]]},"Loop":{"main":[[{"node":"Assert","type":"main","index":0}],[{"node":"Route Kind","type":"main","index":0},{"node":"Loop","type":"main","index":0}]]},"Route Kind":{"main":[[{"node":"Call API","type":"main","index":0}],[{"node":"Inspect","type":"main","index":0}]]},"Call API":{"main":[[{"node":"Tag Result","type":"main","index":0}]]},"Inspect":{"main":[[{"node":"Tag Result","type":"main","index":0}]]},"Tag Result":{"main":[[]]},"Assert":{"main":[[{"node":"🏁 Test Summary","type":"main","index":0}]]},"🏁 Test Summary":{"main":[[{"node":"Respond Lane","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"a659438c-0898-428d-aebd-72033caaefe4","name":"sync-v3"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {},
    /*__n8n__*/ pinData: {"Run Sync Item API Test":[{"json":{"__instance":"test","lane":"all"}}]},
    /*__n8n__*/ staticData: {},
    /*__n8n__*/ shared: [{"updatedAt":"2026-09-02T00:00:00.000Z","createdAt":"2026-09-02T00:00:00.000Z","role":"workflow:owner","workflowId":"syncItemApiTest01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'syncItemApiTest01',
    name: 'Sync Item API Test',
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
export class SyncItemApiTestWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'siat-manual',
        name: 'Run Sync Item API Test',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [-600, 200],
    })
    RunSyncItemApiTest = {};

    @node({
        id: 'siat-webhook',
        webhookId: 'siat-lane-webhook-0001',
        name: 'Lane Webhook',
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [-600, 420],
    })
    LaneWebhook = {
        httpMethod: 'POST',
        path: 'sync-kernel-e2e-lane',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'siat-seed',
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
        id: 'siat-config',
        name: 'Config',
        /*__n8n__*/ notes: "The lane comes from the webhook body ({lane}) or the manual trigger's pin. The tenant is ALWAYS test: this suite writes rows and must never touch a client's ledger.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-160, 320],
    })
    Config = {
        jsCode: `let lane='all';
try{ const b=$('Lane Webhook').first().json||{}; const p=(b.body&&typeof b.body==='object')?b.body:b; if(p.lane) lane=String(p.lane); }catch(e){}
try{ const m=$('Run Sync Item API Test').first().json||{}; if(m.lane && lane==='all') lane=String(m.lane); }catch(e){}
const LANES=['upsert','take','record','fail','reset','reap','cursor','gate'];
if(lane!=='all' && !LANES.includes(lane)) throw new Error('unknown lane '+lane+' — one of '+LANES.join('|')+'|all');
return [{json:{lane, lanes: lane==='all'?LANES:[lane], __instance:'test', exec:String($execution.id)}}];`,
    };

    @node({
        id: 'siat-plan',
        name: 'Plan',
        /*__n8n__*/ notes: "One PLAN per lane: an ordered list of steps, each either an API op ({kind:'api', ...request}) or a read-only inspect ({kind:'sql', sql}). Sources are sv3k_<lane> under the test tenant; every step name is unique so Assert can read its result. The plan begins and ends with a purge of every sv3k_ source, so a lane can be re-run forever.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [60, 320],
    })
    Plan = {
        jsCode: `const cfg=$input.first().json; const I='test'; const T='indox_test.sync_ledger';
const src=(lane)=>'incoming-documents-main/sv3k_'+lane;
const L=(id,name)=>({id, name:name||id, md5:'md5-'+id, size:10, link:'http://x/'+id, createdTime:'2026-09-01T00:00:00Z'});
// __instance is the test tenant unless a step deliberately sends another value (the one
// refusal check below sends null — never a string literal, so the suite stays pinned to test)
const api=(step,req)=>({json:{kind:'api', step, ...req, __instance:('__instance' in req)?req.__instance:I}});
const sql=(step,q)=>({json:{kind:'sql', step, sql:q}});
const purge=(step)=>api(step,{op:'RESET', source_like:'sv3k_%', purge:true});
const plans={
 upsert:(S)=>[
  api('upsert.1',{op:'UPSERT', source:S, items:[{platform_id:'a',listing:L('a')},{platform_id:'b',listing:L('b')},{platform_id:'c',listing:L('c')}]}),
  api('upsert.2',{op:'UPSERT', source:S, items:[{platform_id:'a',listing:L('a')},{platform_id:'b',listing:L('b')},{platform_id:'c',listing:L('c')}]}),
  api('upsert.3',{op:'UPSERT', source:S, items:[{platform_id:'a',listing:L('a','a-renamed')}]}),
  api('upsert.gate',{op:'GATE', source:S}),
  sql('upsert.row',"select listing->>'name' as name, status from "+T+" where source='"+S+"' and platform_id='a'")],
 take:(S)=>[
  api('take.seed',{op:'UPSERT', source:S, items:[{platform_id:'n1',listing:L('n1')},{platform_id:'n2',listing:L('n2')},{platform_id:'n3',listing:L('n3')},{platform_id:'n4',listing:L('n4')},{platform_id:'n5',listing:L('n5')},{platform_id:'n0',listing:{}}]}),
  api('take.1',{op:'TAKE', source:S, limit:2}),
  api('take.2',{op:'TAKE', source:S, limit:10}),
  api('take.3',{op:'TAKE', source:S, limit:10}),
  api('take.gate',{op:'GATE', source:S})],
 record:(S)=>[
  api('record.seed',{op:'UPSERT', source:S, items:[{platform_id:'r1',listing:L('r1')},{platform_id:'r2',listing:L('r2')}]}),
  api('record.take',{op:'TAKE', source:S, limit:2}),
  api('record.1',{op:'RECORD', source:S, platform_id:'r1', doc_id:'doc_r1', content_hash:'h1'}),
  api('record.2',{op:'RECORD', source:S, platform_id:'r1', doc_id:'doc_r1b', content_hash:'h1'}),
  api('record.3',{op:'RECORD', source:S, platform_id:'r2', status:'needs_review'}),
  api('record.4',{op:'RECORD', source:S, platform_id:'r9', doc_id:'doc_r9', content_hash:'h9'}),
  api('record.gate',{op:'GATE', source:S}),
  sql('record.row',"select platform_id, status, doc_id, attempts from "+T+" where source='"+S+"' order by 1")],
 fail:(S)=>[
  api('fail.seed',{op:'UPSERT', source:S, items:[{platform_id:'f1',listing:L('f1')},{platform_id:'f2',listing:L('f2')}]}),
  api('fail.take',{op:'TAKE', source:S, limit:2}),
  api('fail.1',{op:'FAIL', source:S, platform_id:'f1', error:'boom', max_attempts:5, base_backoff_s:60}),
  sql('fail.row1',"select status, attempts, (not_before > now()) as backing, last_error from "+T+" where source='"+S+"' and platform_id='f1'"),
  api('fail.2',{op:'FAIL', source:S, platform_id:'f2', error:'no attachment [terminal]', terminal:true, max_attempts:5}),
  api('fail.3',{op:'FAIL', source:S, platform_id:'f1', error:'boom2', max_attempts:5}),
  api('fail.4',{op:'FAIL', source:S, platform_id:'f1', error:'boom3', max_attempts:5}),
  api('fail.5',{op:'FAIL', source:S, platform_id:'f1', error:'boom4', max_attempts:5}),
  api('fail.6',{op:'FAIL', source:S, platform_id:'f1', error:'boom5', max_attempts:5}),
  sql('fail.rows',"select platform_id, status, attempts from "+T+" where source='"+S+"' order by 1")],
 reset:(S)=>[
  api('reset.seed',{op:'UPSERT', source:S, items:[{platform_id:'x1',listing:L('x1')},{platform_id:'x2',listing:L('x2')},{platform_id:'y0',listing:{}}]}),
  api('reset.cur',{op:'CURSOR_SET', source:S, mode:'walk', walk_token:'v1', steady_cursor:'7'}),
  api('reset.take',{op:'TAKE', source:S, limit:5}),
  api('reset.f',{op:'FAIL', source:S, platform_id:'x1', error:'x [terminal]', terminal:true}),
  api('reset.r',{op:'RECORD', source:S, platform_id:'x2', doc_id:'doc_x2'}),
  api('reset.1',{op:'RESET', source:'sv3k_reset', statuses:['failed','needs_review']}),
  api('reset.gate1',{op:'GATE', source:S}),
  api('reset.cur1',{op:'CURSOR_GET', source:S}),
  api('reset.2',{op:'RESET', source:'sv3k_reset'}),
  api('reset.gate2',{op:'GATE', source:S}),
  api('reset.cur2',{op:'CURSOR_GET', source:S}),
  api('reset.3',{op:'RESET', source:'sv3k_reset', purge:true}),
  api('reset.gate3',{op:'GATE', source:S})],
 reap:(S)=>[
  api('reap.seed',{op:'UPSERT', source:S, items:[{platform_id:'p1',listing:L('p1')},{platform_id:'p2',listing:L('p2')}]}),
  api('reap.take',{op:'TAKE', source:S, limit:2}),
  sql('reap.age',"update "+T+" set claimed_at = now() - interval '3 minutes' where source='"+S+"' and platform_id='p1' returning platform_id"),
  api('reap.1',{op:'REAP', timeout_min:1}),
  sql('reap.rows',"select platform_id, status, attempts, (not_before > now()) as backing from "+T+" where source='"+S+"' order by 1")],
 cursor:(S)=>[
  api('cursor.0',{op:'CURSOR_GET', source:S}),
  api('cursor.1',{op:'CURSOR_SET', source:S, mode:'walk', walk_token:'t1', steady_cursor:'10'}),
  api('cursor.2',{op:'CURSOR_GET', source:S}),
  api('cursor.3',{op:'CURSOR_SET', source:S, mode:'steady', walk_token:'t1', steady_cursor:'20'}),
  api('cursor.4',{op:'CURSOR_GET', source:S})],
 gate:(S)=>[
  api('gate.seed',{op:'UPSERT', source:S, items:[{platform_id:'g1',listing:L('g1')},{platform_id:'g2',listing:L('g2')},{platform_id:'g3',listing:L('g3')}]}),
  api('gate.take',{op:'TAKE', source:S, limit:1}),
  api('gate.1',{op:'GATE', source:S}),
  api('gate.bad',{op:'GATE', source:S, __instance:null})],
};
const steps=[purge('purge.0')];
for(const lane of cfg.lanes){ steps.push(...plans[lane](src(lane))); }
steps.push(purge('purge.1'));
return steps.map((s,i)=>({json:{...s.json, i}}));`,
    };

    @node({
        id: 'siat-loop',
        name: 'Loop',
        /*__n8n__*/ notes: "batchSize 1: one step per iteration, in plan order. Every branch returns exactly one item to this node (Call API / Inspect are alwaysOutputData + continue-on-error, Tag Result always emits one), so the loop can never die on an empty iteration.",
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [280, 320],
    })
    Loop = {
        batchSize: 1,
        options: {},
    };

    @node({
        id: 'siat-route',
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
                        conditions: [ { id: 'siat-api', leftValue: '={{ $json.kind }}', rightValue: 'api', operator: { type: 'string', operation: 'equals' } } ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'api',
                },
                {
                    conditions: {
                        options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 },
                        conditions: [ { id: 'siat-sql', leftValue: '={{ $json.kind }}', rightValue: 'sql', operator: { type: 'string', operation: 'equals' } } ],
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
        id: 'siat-call',
        name: 'Call API',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [720, 320],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    CallApi = {
        workflowId: {
            __rl: true,
            value: 'syncLedgerApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'siat-inspect',
        name: 'Inspect',
        /*__n8n__*/ notes: "Read-only look at the TEST tenant's rows between API calls (plus the one deliberate write the reap lane needs: aging a claim). Test-only door — production reads the ledger through the API alone.",
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [720, 520],
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
        id: 'siat-tag',
        name: 'Tag Result',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [940, 420],
    })
    TagResult = {
        jsCode: `// the current step is the Loop's LOOP-branch item (branch 1); the Switch's branch 0 is empty on
// a sql step, which is why $('Route Kind').first() is not the way to read it
let step={};
for(const get of [()=>$('Loop').first(1), ()=>$('Route Kind').first(0), ()=>$('Route Kind').first(1)]){
  try{ const it=get(); if(it&&it.json&&it.json.step){ step=it.json; break; } }catch(e){}
}
const rows=$input.all().map(i=>i&&i.json).filter(Boolean);
return [{json:{step:step.step, kind:step.kind, op:step.op||null, i:step.i, result:rows}}];`,
    };

    @node({
        id: 'siat-assert',
        name: 'Assert',
        /*__n8n__*/ notes: "Reads every tagged result by step name and states each expectation as one PASS/FAIL line (the lane runner greps for PASS). A lane's expectations are spelled here, explicitly — no eval, no generic matcher — so a red line names the op AND the number it saw.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [500, 200],
    })
    Assert = {
        jsCode: `const cfg=$('Config').first().json;
const R={}; for(const it of $input.all()){ const j=it.json||{}; if(j.step) R[j.step]=j.result||[]; }
const first=(s)=>(R[s]||[])[0]||{};
const rowsOf=(s)=>(R[s]||[]).filter(r=>r&&r.platform_id!==undefined);
const n=(v)=>Number(v)||0;
const out=[]; let pass=0, fail=0;
const check=(name, ok, saw)=>{ if(ok) pass++; else fail++; out.push({json:{lane:cfg.lane, result:(ok?'PASS ':'FAIL ')+name+(ok?'':' — saw '+JSON.stringify(saw).slice(0,200))}}); };
const has=(lane)=>cfg.lanes.includes(lane);
if(has('upsert')){
  check('upsert: 3 new items discovered', n(first('upsert.1').discovered)===3 && n(first('upsert.1').listed)===3, first('upsert.1'));
  check('upsert: re-listing the same items is free (0 discovered, 0 refreshed)', n(first('upsert.2').discovered)===0 && n(first('upsert.2').refreshed)===0, first('upsert.2'));
  check('upsert: a changed listing refreshes a non-delivered row', n(first('upsert.3').refreshed)===1 && n(first('upsert.3').discovered)===0, first('upsert.3'));
  check('upsert: gate counts 3 discovered', n(first('upsert.gate').discovered)===3 && n(first('upsert.gate').total)===3, first('upsert.gate'));
  check('upsert: the refreshed name is stored', first('upsert.row').name==='a-renamed' && first('upsert.row').status==='discovered', first('upsert.row'));
}
if(has('take')){
  check('take: limit bounds the claim (2 of 5)', rowsOf('take.1').length===2, rowsOf('take.1').map(r=>r.platform_id));
  check('take: the rest follow, a row with no listing is never taken (3)', rowsOf('take.2').length===3 && !rowsOf('take.2').some(r=>r.platform_id==='n0'), rowsOf('take.2').map(r=>r.platform_id));
  check('take: nothing left -> zero rows (envelope)', rowsOf('take.3').length===0 && n(first('take.3').rows)===0, first('take.3'));
  check('take: gate sees 5 claimed + 1 discovered', n(first('take.gate').claimed)===5 && n(first('take.gate').discovered)===1, first('take.gate'));
  const taken=rowsOf('take.1').concat(rowsOf('take.2')).map(r=>r.platform_id);
  check('take: no row handed out twice', new Set(taken).size===taken.length, taken);
}
if(has('record')){
  check('record: a claimed row becomes delivered', first('record.1').status==='delivered', first('record.1'));
  check('record: recording a delivered row again is a no-op', rowsOf('record.2').length===0, R['record.2']);
  check('record: needs_review is a recordable outcome', first('record.3').status==='needs_review', first('record.3'));
  check('record: an unknown item is inserted as delivered', first('record.4').status==='delivered', first('record.4'));
  check('record: gate = 2 delivered + 1 needs_review', n(first('record.gate').delivered)===2 && n(first('record.gate').needs_review)===1, first('record.gate'));
  const r1=(R['record.row']||[]).find(r=>r.platform_id==='r1')||{};
  check('record: doc_id stored and attempts cleared', r1.doc_id==='doc_r1' && n(r1.attempts)===0, r1);
}
if(has('fail')){
  check('fail: first failure -> failed, attempts 1, backing off', first('fail.row1').status==='failed' && n(first('fail.row1').attempts)===1 && first('fail.row1').backing===true, first('fail.row1'));
  check('fail: [terminal] -> needs_review at once', first('fail.2').status==='needs_review' && n(first('fail.2').attempts)===1, first('fail.2'));
  const f1=(R['fail.rows']||[]).find(r=>r.platform_id==='f1')||{};
  check('fail: the 5th attempt promotes to needs_review', f1.status==='needs_review' && n(f1.attempts)===5, f1);
}
if(has('reset')){
  check('reset: scoped retry flips exactly the failed/needs_review row', n(first('reset.1').reset)===1 && n(first('reset.1').cursors_deleted)===0, first('reset.1'));
  check('reset: gate after scoped retry = 1 discovered(+y0) 1 delivered', n(first('reset.gate1').discovered)===2 && n(first('reset.gate1').delivered)===1, first('reset.gate1'));
  check('reset: a scoped retry keeps the cursor', first('reset.cur1').steady_cursor==='7', first('reset.cur1'));
  check('reset: full re-drive flips the delivered row too and drops the cursor', n(first('reset.2').reset)===1 && n(first('reset.2').cursors_deleted)===1, first('reset.2'));
  check('reset: a row with no listing is reported skipped, not flipped', n(first('reset.2').skipped_no_listing)===0 && n(first('reset.gate2').discovered)===3, {reset2:first('reset.2'), gate2:first('reset.gate2')});
  check('reset: cursor gone after a full re-drive', rowsOf('reset.cur2').length===0 && !first('reset.cur2').source, first('reset.cur2'));
  check('reset: purge deletes every row', n(first('reset.3').purged)===3 && n(first('reset.gate3').total)===0, {p:first('reset.3'), g:first('reset.gate3')});
}
if(has('reap')){
  check('reap: the aged claim is released with backoff (1), the fresh one kept', n(first('reap.1').released)===1 && n(first('reap.1').promoted_needs_review)===0, first('reap.1'));
  const p1=(R['reap.rows']||[]).find(r=>r.platform_id==='p1')||{}; const p2=(R['reap.rows']||[]).find(r=>r.platform_id==='p2')||{};
  check('reap: p1 failed/attempts 1/backing, p2 still claimed', p1.status==='failed' && n(p1.attempts)===1 && p1.backing===true && p2.status==='claimed', {p1,p2});
}
if(has('cursor')){
  check('cursor: absent reads as zero rows', rowsOf('cursor.0').length===0 && !first('cursor.0').source, first('cursor.0'));
  check('cursor: set then get returns token + mark', first('cursor.2').walk_token==='t1' && first('cursor.2').steady_cursor==='10' && first('cursor.2').mode==='walk', first('cursor.2'));
  check('cursor: a second set moves the mark', first('cursor.4').steady_cursor==='20' && first('cursor.4').mode==='steady', first('cursor.4'));
}
if(has('gate')){
  check('gate: counts add up (1 claimed + 2 discovered = 3)', n(first('gate.1').claimed)===1 && n(first('gate.1').discovered)===2 && n(first('gate.1').total)===3, first('gate.1'));
  check('gate: a request without __instance is refused (no public fallback)', !!(first('gate.bad').error||first('gate.bad').errorMessage) || rowsOf('gate.bad').length===0 && first('gate.bad').total===undefined, first('gate.bad'));
}
check('teardown: every sv3k_ row purged', n(first('purge.1').purged)>=0 && first('purge.1').purge===true, first('purge.1'));
out.push({json:{lane:cfg.lane, result:(fail?'FAIL ':'PASS ')+'summary '+pass+'/'+(pass+fail)+' checks', pass, fail, execution_id:String($execution.id)}});
return out;`,
    };

    @node({
        id: 'siat-summary',
        name: '🏁 Test Summary',
        /*__n8n__*/ notes: "The harness contract (apps/indox/hooks/test.py fetch_summary): a node named with 🏁 returning {RESULT, passed:'N/M', checks:[...]} as its FIRST item. The Assert lines follow it unchanged so the lane webhook still answers with one `result` per check.",
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
        id: 'siat-respond',
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
        this.RunSyncItemApiTest.out(0).to(this.SeedTestFixtures.in(0));
        this.LaneWebhook.out(0).to(this.SeedTestFixtures.in(0));
        this.SeedTestFixtures.out(0).to(this.Config.in(0));
        this.Config.out(0).to(this.Plan.in(0));
        this.Plan.out(0).to(this.Loop.in(0));
        this.Loop.out(0).to(this.Assert.in(0));
        this.Loop.out(1).to(this.RouteKind.in(0));
        this.RouteKind.out(0).to(this.CallApi.in(0));
        this.RouteKind.out(1).to(this.Inspect.in(0));
        this.CallApi.out(0).to(this.TagResult.in(0));
        this.Inspect.out(0).to(this.TagResult.in(0));
        this.TagResult.out(0).to(this.Loop.in(0));
        this.Assert.out(0).to(this.TestSummary.in(0));
        this.TestSummary.out(0).to(this.RespondLane.in(0));
    }
}
