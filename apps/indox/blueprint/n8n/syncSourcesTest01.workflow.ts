import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Sync Sources Test
// Nodes   : 9  |  Connections: 8
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// RunSyncSourcesTest                 manualTrigger
// LaneWebhook                        webhook
// SeedTestFixtures                   executeWorkflow            [alwaysOutput] [retry]
// Config                             code
// Inject                             executeWorkflow            [onError→regular] [alwaysOutput]
// Settle                             wait
// Inspect                            postgres                   [creds] [alwaysOutput]
// Assert                             code
// RespondLane                        respondToWebhook           [onError→regular]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// RunSyncSourcesTest
//    → SeedTestFixtures
//      → Config
//        → Inject
//          → Settle
//            → Inspect
//              → Assert
//                → RespondLane
// LaneWebhook
//    → SeedTestFixtures (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: "Per-source END TO END on the test tenant (2026-09-02): the injector (sv3Inject3x001) plants 3 documents in every test source — two local drive folders, and three tags on the local mailbox — and runs the REAL sync pass (syncV3Main0001 → Discover → Run → Deliver) against its own sv3i_ registry. After the deliveries settle, one query reads what the SYNC ITEM says happened and which documents exist for each source, and the lane asserts it: a drive pipe delivers all 3 of its files; a mail pipe delivers every attachment it sees and marks the attachment-less link mails needs_review at once (terminal, no retry storm); the link pipe delivers its 3 linked files and needs-reviews the 6 attachment mails. Lanes: drive-gdoc | drive-bs | gmail-doc | gmail-bs | gmail-link | all. Webhook: POST /webhook/sync-sources-e2e-lane {lane, __instance:'test'}.",
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Run Sync Sources Test":{"main":[[{"node":"Seed Test Fixtures","type":"main","index":0}]]},"Lane Webhook":{"main":[[{"node":"Seed Test Fixtures","type":"main","index":0}]]},"Seed Test Fixtures":{"main":[[{"node":"Config","type":"main","index":0}]]},"Config":{"main":[[{"node":"Inject","type":"main","index":0}]]},"Inject":{"main":[[{"node":"Broken Item","type":"main","index":0}]]},"Broken Item":{"main":[[{"node":"Call UPSERT (broken)","type":"main","index":0}]]},"Call UPSERT (broken)":{"main":[[{"node":"Unlisted Row","type":"main","index":0}]]},"Unlisted Row":{"main":[[{"node":"Broken Run","type":"main","index":0}]]},"Broken Run":{"main":[[{"node":"Call Run (broken)","type":"main","index":0}]]},"Call Run (broken)":{"main":[[{"node":"Settle","type":"main","index":0}]]},"Settle":{"main":[[{"node":"Inspect","type":"main","index":0}]]},"Inspect":{"main":[[{"node":"Check","type":"main","index":0}]]},"Check":{"main":[[{"node":"Settled?","type":"main","index":0}]]},"Settled?":{"main":[[{"node":"Assert","type":"main","index":0}],[{"node":"Wait More","type":"main","index":0}]]},"Wait More":{"main":[[{"node":"Inspect","type":"main","index":0}]]},"Assert":{"main":[[{"node":"🏁 Test Summary","type":"main","index":0}]]},"🏁 Test Summary":{"main":[[{"node":"Respond Lane","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"a659438c-0898-428d-aebd-72033caaefe4","name":"sync-v3"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {},
    /*__n8n__*/ pinData: {"Run Sync Sources Test":[{"json":{"__instance":"test","lane":"all"}}]},
    /*__n8n__*/ staticData: {},
    /*__n8n__*/ shared: [{"updatedAt":"2026-09-02T00:00:00.000Z","createdAt":"2026-09-02T00:00:00.000Z","role":"workflow:owner","workflowId":"syncSourcesTest01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'syncSourcesTest01',
    name: 'Sync Sources Test',
    active: true,
    isArchived: false,
    tags: ['app:indox', 'indox', 'sync-v3', 'indox-app'],
    settings: {
        errorWorkflow: 'errorHandler01',
        executionOrder: 'v1',
        executionTimeout: 900,
        callerPolicy: 'workflowsFromSameOwner',
    },
})
export class SyncSourcesTestWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'sst-manual',
        name: 'Run Sync Sources Test',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [-600, 200],
    })
    RunSyncSourcesTest = {};

    @node({
        id: 'sst-webhook',
        webhookId: 'sst-lane-webhook-0001',
        name: 'Lane Webhook',
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [-600, 420],
    })
    LaneWebhook = {
        httpMethod: 'POST',
        path: 'sync-sources-e2e-lane',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'sst-seed',
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
        id: 'sst-config',
        name: 'Config',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-160, 320],
    })
    Config = {
        jsCode: `let lane='all';
try{ const b=$('Lane Webhook').first().json||{}; const p=(b.body&&typeof b.body==='object')?b.body:b; if(p.lane) lane=String(p.lane); }catch(e){}
try{ const m=$('Run Sync Sources Test').first().json||{}; if(m.lane && lane==='all') lane=String(m.lane); }catch(e){}
const LANES=['drive-gdoc','drive-bs','gmail-doc','gmail-bs','gmail-link'];
if(lane!=='all' && !LANES.includes(lane)) throw new Error('unknown lane '+lane);
// started_at bounds the Inspect: only rows THIS run discovered count — a previous run's sv3i_ rows
// (the sweep leaves them for the injector's own owner) must not double every number.
return [{json:{__instance:'test', lane, lanes: lane==='all'?LANES:[lane], exec:String($execution.id), started_at:new Date(Date.now()-5000).toISOString()}}];`,
    };

    @node({
        id: 'sst-inject',
        name: 'Inject',
        /*__n8n__*/ notes: "sv3Inject3x001: seeds the sv3i_ test registry (2 local drive pipes + 3 local-mail pipes sharing one to_sync tag), generates 3 documents per source through apitools docGen, plants them (drive upload / mail append + tag), and runs the REAL syncV3Main0001 against that registry. Its teardown removes the registry rows; the ledger rows and documents stay for the assertions and are swept by fixture-sweep.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [60, 320],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    Inject = {
        workflowId: {
            __rl: true,
            value: 'sv3Inject3x001',
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
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'sst-broken-item',
        name: 'Broken Item',
        /*__n8n__*/ notes: "[2026-09-02] THE DRIVE DELIVERY'S FAIL PATH, deterministically: one sync item on its own sv3i_ source whose listing carries NO md5. syncDeliverDrive01's Drive Row refuses it with a [terminal] error before any drive call, so Fail Req → Call FAIL run and the row ends needs_review — the two nodes no real fixture had ever reached (71% node coverage on that workflow). Same sv3i_ prefix = the fixture sweep owns it.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [60, 480],
    })
    BrokenItem = {
        jsCode: `const cfg=$('Config').first().json||{};
const src=String(cfg.__instance||'test')+'/sv3i_drive-broken';
return [{json:{op:'UPSERT', source:src, instance:'incoming-documents-main', __instance:String(cfg.__instance||'test'),
  items:[{platform_id:'sv3i-broken-'+String(cfg.exec||'x'), listing:{id:'sv3i-broken-'+String(cfg.exec||'x'), name:'sv3i-broken.pdf', size:1, link:null, createdTime:new Date().toISOString(), mimeType:'application/pdf'}}]}}];`,
    };

    @node({
        id: 'sst-broken-upsert',
        name: 'Call UPSERT (broken)',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [260, 480],
        alwaysOutputData: true,
    })
    CallUpsertBroken = {
        workflowId: {
            __rl: true,
            value: 'syncLedgerApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'sst-unlisted-row',
        name: 'Unlisted Row',
        /*__n8n__*/ notes: "[2026-09-02] THE TAKE-TIME DEAD-LETTER, deterministically: a legacy sync item on the broken source with an EMPTY listing, discovered two days ago — the shape eight live rows had after their files left the source folder (they sat in 'failed' for four weeks, because TAKE never takes an empty listing and discovery never re-listed them). The broken unit's Run → TAKE must retire it to needs_review with the [unlisted] reason instead of leaving it waiting.",
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [360, 620],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    UnlistedRow = {
        operation: 'executeQuery',
        query: `=insert into indox_test.sync_ledger (source, platform_id, status, discovered_at, listing, instance)
values ('{{ $('Config').first().json.__instance }}/sv3i_drive-broken', 'sv3i-unlisted-{{ $('Config').first().json.exec }}', 'discovered', now() - interval '2 days', '{}'::jsonb, 'incoming-documents-main')
on conflict (source, platform_id) do update set status='discovered', listing='{}'::jsonb, discovered_at=now() - interval '2 days', attempts=0, not_before=null, claimed_at=null, last_error=null
returning platform_id`,
        options: {},
    };

    @node({
        id: 'sst-broken-run',
        name: 'Broken Run',
        /*__n8n__*/ notes: "One Run unit for the broken source (the shape Main builds): TAKE takes the item (its listing is non-empty), Deliver Drive refuses it as terminal.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [460, 480],
    })
    BrokenRun = {
        jsCode: `const cfg=$('Config').first().json||{};
const inst=String(cfg.__instance||'test');
return [{json:{source:inst+'/sv3i_drive-broken', pipe:'sv3i_drive-broken', src_kind:'drive', conn_kind:'drive', connection:null,
  instance:'incoming-documents-main', take:5, chunk:5, months:6, list_ctx:{folderId:'sv3i-broken-folder'}, feedback:{mode:'off'},
  max_attempts:5, base_backoff_s:60, __instance:inst}}];`,
    };

    @node({
        id: 'sst-broken-call-run',
        name: 'Call Run (broken)',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [660, 480],
        alwaysOutputData: true,
        onError: 'continueRegularOutput',
    })
    CallRunBroken = {
        workflowId: {
            __rl: true,
            value: 'syncRun01',
            mode: 'id',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'sst-settle',
        name: 'Settle',
        /*__n8n__*/ notes: "Deliveries are their own executions (Run dispatches without waiting). A fresh injector pass measured 12s end to end; a run that re-discovers accumulated fixtures fans out ~80 deliveries and 2 of them were still in flight at 60s — 120s is headroom for that shape, not hope.",
        type: 'n8n-nodes-base.wait',
        version: 1.1,
        position: [280, 320],
    })
    Settle = {
        amount: 120,
        unit: 'seconds',
    };

    @node({
        id: 'sst-inspect',
        name: 'Inspect',
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [500, 320],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    Inspect = {
        operation: 'executeQuery',
        query: `=select regexp_replace(l.source,'^[^/]*/','') as pipe,
       count(*)::int as total,
       count(*) filter (where l.status='delivered')::int as delivered,
       count(*) filter (where l.status='needs_review')::int as needs_review,
       count(*) filter (where l.status='failed')::int as failed,
       count(*) filter (where l.status in ('discovered','claimed'))::int as pending,
       count(*) filter (where l.listing <> '{}'::jsonb)::int as with_listing,
       count(distinct d."ID") filter (where l.status='delivered')::int as documents,
       count(*) filter (where l.status='delivered' and d."ID" is null)::int as delivered_without_doc,
       count(*) filter (where l.status='needs_review' and l.last_error like '[unlisted]%')::int as unlisted,
       true as fresh
  from indox_test.sync_ledger l
  left join indox_test.incoming_documents d on d."ID" = l.doc_id
 where l.source like '%/sv3i\\_%'
   and (l.discovered_at >= '{{ $('Config').first().json.started_at }}'::timestamptz
        or l.platform_id = 'sv3i-unlisted-{{ $('Config').first().json.exec }}')
 group by 1 order by 1`,
        options: {},
    };

    @node({
        id: 'sst-check',
        name: 'Check',
        /*__n8n__*/ notes: "SETTLEMENT, NOT A CLOCK. Deliveries serialise per mailbox (one IMAP socket per account, by owner rule), and the injector's test mailbox accumulates a run's messages forever, so the fan-out grows with every run. The lane waits until no item is pending — polling the ledger every 30s, at most 10 more times — instead of guessing a duration.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [610, 320],
    })
    Check = {
        jsCode: `const rows=$input.all().map(i=>i&&i.json).filter(r=>r&&r.pipe);
const pending=rows.reduce((a,r)=>a+(Number(r.pending)||0),0);
let tries=0; try{ tries=$runIndex; }catch(e){}
return [{json:{settled: pending===0 || tries>=20, pending, tries, pipes:rows.length}}];`,
    };

    @node({
        id: 'sst-settled',
        name: 'Settled?',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [720, 320],
    })
    Settled = {
        conditions: {
            options: { caseSensitive: true, typeValidation: 'loose', version: 2 },
            conditions: [ { id: 'sst-settled-c', leftValue: '={{ $json.settled === true }}', rightValue: true, operator: { type: 'boolean', operation: 'true', singleValue: true } } ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: 'sst-wait-more',
        name: 'Wait More',
        type: 'n8n-nodes-base.wait',
        version: 1.1,
        position: [720, 520],
    })
    WaitMore = {
        amount: 30,
        unit: 'seconds',
    };

    @node({
        id: 'sst-assert',
        name: 'Assert',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [940, 220],
    })
    Assert = {
        jsCode: `const cfg=$('Config').first().json;
// the rows come from the LAST inspect (the settled one), not from the Settled? item
const rows=$('Inspect').all().map(i=>i&&i.json).filter(r=>r&&r.pipe);
const by={}; for(const r of rows) by[r.pipe]=r;
let inj={}; try{ inj=$('Inject').first().json||{}; }catch(e){}
const out=[]; let pass=0, fail=0;
const check=(name, ok, saw)=>{ if(ok) pass++; else fail++; out.push({json:{lane:cfg.lane, result:(ok?'PASS ':'FAIL ')+name+(ok?'':' — saw '+JSON.stringify(saw).slice(0,240))}}); };
// the injector's reply is its LAST node (the config teardown) — a run that reached teardown ran
check('injector ran to its teardown without error', !inj.error && !inj.errorMessage && (inj.registry_rows_removed!==undefined || inj.injected!==undefined), inj);
const n=(v)=>Number(v)||0;
// SCOPE-ROBUST EXPECTATIONS. The injector never empties its test folders or mailbox, and a
// global fixture sweep (bbox run) drops the sv3i_ ledger rows — so a run can legitimately
// RE-discover earlier runs' fixtures (measured: exactly 3x after three runs). What must hold for
// every discovered item is the contract, whatever the count: a listing, then delivered with a
// document or terminal (needs_review) — nothing pending, nothing retrying; and THIS run's three
// are the floor.
for(const lane of cfg.lanes){
  const r=by['sv3i_'+lane]||{};
  const isDrive=lane.startsWith('drive');
  const settled = n(r.pending)===0 && n(r.failed)===0 && n(r.with_listing)===n(r.total) && n(r.delivered_without_doc)===0;
  if(isDrive){
    check(lane+': at least the 3 injected files discovered, every one with a listing', n(r.total)>=3 && n(r.with_listing)===n(r.total), r);
    check(lane+': every discovered file delivered with a document (>=3), none pending/failed', settled && n(r.delivered)===n(r.total) && n(r.documents)===n(r.delivered) && n(r.delivered)>=3, r);
  } else if(lane==='gmail-link'){
    // the three mail pipes share one to_sync tag on the test mailbox, so every pipe sees every
    // message: the link pipe delivers the linked mails; attachment mails carry no link and are
    // terminal (needs_review) at once — never a retry storm.
    check(lane+': at least the 9 injected messages discovered, every one with a listing', n(r.total)>=9 && n(r.with_listing)===n(r.total), r);
    check(lane+': the linked mails delivered with documents (>=3)', n(r.delivered)>=3 && n(r.documents)===n(r.delivered) && n(r.delivered_without_doc)===0, r);
    check(lane+': every link-less mail is needs_review (terminal): delivered + needs_review = total, none pending/retrying', settled && n(r.delivered)+n(r.needs_review)===n(r.total) && n(r.needs_review)>=6, r);
  } else {
    check(lane+': at least the 9 injected messages discovered, every one with a listing', n(r.total)>=9 && n(r.with_listing)===n(r.total), r);
    check(lane+': the attachment mails delivered with documents (>=6)', n(r.delivered)>=6 && n(r.documents)===n(r.delivered) && n(r.delivered_without_doc)===0, r);
    check(lane+': every attachment-less mail is needs_review (terminal): delivered + needs_review = total, none pending', settled && n(r.delivered)+n(r.needs_review)===n(r.total) && n(r.needs_review)>=3, r);
  }
}
// the drive delivery's FAIL path (Broken Item): a listing with no md5 is terminal at delivery —
// needs_review at once, no document, no retry, no drive call.
// the broken source carries exactly two rows this run: the md5-less item and the unlisted legacy row.
{ const r=by['sv3i_drive-broken']||{};
  check('drive-broken: a drive item whose listing has no md5 is terminal at delivery (needs_review, no document, no retry)', n(r.total)===2 && n(r.needs_review)===2 && n(r.delivered)===0 && n(r.pending)===0 && n(r.failed)===0, r);
  // the take-time dead-letter: an empty listing a day after discovery is the source no longer
  // listing the item — TAKE retires it with the [unlisted] reason instead of leaving it waiting.
  check('drive-unlisted: a legacy row with no listing a day after discovery is dead-lettered at take time (needs_review, [unlisted] reason), never taken', n(r.unlisted)===1, r); }
out.push({json:{lane:cfg.lane, result:(fail?'FAIL ':'PASS ')+'summary '+pass+'/'+(pass+fail)+' checks', pass, fail, rows, execution_id:String($execution.id)}});
return out;`,
    };

    @node({
        id: 'sst-summary',
        name: '🏁 Test Summary',
        /*__n8n__*/ notes: "The harness contract (apps/indox/hooks/test.py fetch_summary): a node named with 🏁 returning {RESULT, passed:'N/M', checks:[...]} as its FIRST item; the Assert lines follow for the lane webhook.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [830, 320],
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
        id: 'sst-respond',
        name: 'Respond Lane',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [940, 320],
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
        this.RunSyncSourcesTest.out(0).to(this.SeedTestFixtures.in(0));
        this.LaneWebhook.out(0).to(this.SeedTestFixtures.in(0));
        this.SeedTestFixtures.out(0).to(this.Config.in(0));
        this.Config.out(0).to(this.Inject.in(0));
        this.Inject.out(0).to(this.BrokenItem.in(0));
        this.BrokenItem.out(0).to(this.CallUpsertBroken.in(0));
        this.CallUpsertBroken.out(0).to(this.UnlistedRow.in(0));
        this.UnlistedRow.out(0).to(this.BrokenRun.in(0));
        this.BrokenRun.out(0).to(this.CallRunBroken.in(0));
        this.CallRunBroken.out(0).to(this.Settle.in(0));
        this.Settle.out(0).to(this.Inspect.in(0));
        this.Inspect.out(0).to(this.Check.in(0));
        this.Check.out(0).to(this.Settled.in(0));
        this.Settled.out(0).to(this.Assert.in(0));
        this.Settled.out(1).to(this.WaitMore.in(0));
        this.WaitMore.out(0).to(this.Inspect.in(0));
        this.Assert.out(0).to(this.TestSummary.in(0));
        this.TestSummary.out(0).to(this.RespondLane.in(0));
    }
}
