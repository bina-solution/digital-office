import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox-v2 Sealed Actions — SHIPMENT
//
// WHAT THIS SUITE IS (2026-08-31, the ActionsSealed matrix). Every state-machine ACTION gets its
// own sealed lane: seed documents in the exact pre-action state (recipes lifted verbatim from
// indoxV2DecideTest01's case table — the decide contract and this suite must agree by
// construction), fire the DRIVER over the whole set through its production WEBHOOK entry (the
// same POST shape indoxV2BaseDrain01's 'Fire Lanes' sends, so the action log lives and the
// pagination/grouping machinery runs), then assert TWO facts per lane: the action-log rows exist
// and ENDED, and the action's EFFECT is on the rows. Batch 1 AND batch 100 per lane — the 100s
// are what exercise the driver's group widths and page machinery that no other suite reaches.
//
// Lanes are WAVE 1: actions whose effects are pure row writes (no drive-file dependency).
// update_name (drive rename), find_link / get_api_tools_id (search+upload), and the
// link-shipments arm are WAVE 2 — they need seeded drive files to be honest.
//
// ROUTING: Trigger/Lane Webhook -> Seed Test Fixtures -> Config -> Cleanup Prior -> Emit Seeds
// -> Seed Docs (api UPSERT) -> Build Fire -> Fire Driver (webhook, ACKs in ms) -> Watch loop
// (log ENDED counts) -> Verify -> Assert -> 🏁 -> Lane Verdict -> Respond Lane
// </workflow-map>

@workflow({
    /*__n8n__*/ connections: {"▶ Run SHIPMENT Sealed Test": {"main": [[{"node": "Seed Test Fixtures", "type": "main", "index": 0}]]}, "Lane Webhook": {"main": [[{"node": "Seed Test Fixtures", "type": "main", "index": 0}]]}, "Seed Test Fixtures": {"main": [[{"node": "Config", "type": "main", "index": 0}]]}, "Config": {"main": [[{"node": "Cleanup Prior", "type": "main", "index": 0}]]}, "Cleanup Prior": {"main": [[{"node": "Emit Seeds", "type": "main", "index": 0}]]}, "Emit Seeds": {"main": [[{"node": "Seed Docs", "type": "main", "index": 0}]]}, "Seed Docs": {"main": [[{"node": "Build Fire", "type": "main", "index": 0}]]}, "Build Fire": {"main": [[{"node": "Fire Driver", "type": "main", "index": 0}]]}, "Fire Driver": {"main": [[{"node": "SL Watch", "type": "main", "index": 0}]]}, "SL Watch": {"main": [[{"node": "SL Guard", "type": "main", "index": 0}]]}, "SL Guard": {"main": [[{"node": "SL Ready?", "type": "main", "index": 0}]]}, "SL Ready?": {"main": [[{"node": "Quiesce Fixtures", "type": "main", "index": 0}], [{"node": "SL Sleep", "type": "main", "index": 0}]]}, "SL Sleep": {"main": [[{"node": "SL Watch", "type": "main", "index": 0}]]}, "Verify": {"main": [[{"node": "Assert Sealed", "type": "main", "index": 0}]]}, "Assert Sealed": {"main": [[{"node": "🏁 Test Summary", "type": "main", "index": 0}]]}, "🏁 Test Summary": {"main": [[{"node": "Lane Verdict", "type": "main", "index": 0}]]}, "Lane Verdict": {"main": [[{"node": "Respond Lane", "type": "main", "index": 0}]]}, "Quiesce Fixtures": {"main": [[{"node": "Verify", "type": "main", "index": 0}]]}},
    /*__n8n__*/ tags: [{"id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    id: 'indoxV2SealedShip01',
    name: 'indox-v2 Sealed Actions — SHIPMENT',
    active: true,
    isArchived: false,
    tags: ['app:indox'],
    settings: {
        executionOrder: 'v1',
        errorWorkflow: 'errorHandler01',
        executionTimeout: 1500,
        binaryMode: 'separate',
    },
})
export class IndoxV2SealedActionsShipmentWorkflow {

    @node({
        id: 'sls-trig',
        name: '▶ Run SHIPMENT Sealed Test',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [-1000, 0],
    })
    RunIndoxV2SealedActionsShipment = {};

    @node({
        id: 'sls-lane-webhook',
        webhookId: 'sealed-ship-e2e-lane',
        name: 'Lane Webhook',
        /*__n8n__*/ notes: "The console's בדיקות tab runs suites through webhook lanes (BFF _run_one_lane POSTs {lane} and reads back items whose `result` contains PASS). One lane ('all'): same graph the CLI runs.",
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [-1000, 200],
    })
    LaneWebhook = {
        httpMethod: 'POST',
        path: 'sealed-ship-e2e-lane',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'sls-fixtures',
        name: 'Seed Test Fixtures',
        /*__n8n__*/ notes: "Companies + test-clock + settings for the test tenant. Mint model: REST-run pins never reach a manualTrigger's item, so the tenant is stated here, not read from the trigger.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [-780, 100],
        alwaysOutputData: true,
    })
    SeedTestFixtures = {
        workflowId: {
            __rl: true,
            value: 'indoxV2TestFixtures01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: { __instance: 'test' },
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'sls-config',
        name: 'Config',
        /*__n8n__*/ notes: "The lane table. Seeds are the decide suite's OWN recipes (BASE + the case's overrides, verbatim) so decide's contract and this suite cannot drift apart. Effects are chosen STABLE under continuation: the driver spawns the doc's next action after the target runs, so a lane asserts a field the later rounds never rewrite (SHORT_DOC_ID, FROM_OFFICE_CHECK) or a status that terminal-holds (MISSING_LINK, API_TOOLS_FAILED, COMPLETED).",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-560, 100],
    })
    Config = {
        jsCode: `const __up=(()=>{try{const b=($('Lane Webhook').first().json.body||{}); if(b.__instance) return String(b.__instance);}catch(e){} return '';})();
if(__up && __up!=='test') throw new Error("indoxV2SealedShip01: lane webhook carries __instance "+JSON.stringify(__up)+" -- this suite runs only against the test tenant (indox_test).");
// decide-suite BASE, verbatim in meaning: an all-complete recent invoice one step from done.
const BASE={
  TYPE:'SHIPMENT', STATUS:'', COMPANY_ID:'C01', COMPANY_NAME:'Acme',
  LINK:'https://drive.google.com/file/abc', LINK_CONNECTION:'drive_local-test0',
  API_TOOLS_ID:'at-999', FROM_OFFICE_CHECK:'yes',
  DOC_DATE:new Date(Date.now()-30*86400000).toISOString().slice(0,10),
  DOC_TOTAL_AMOUNT:'5000', PURCHASE_ID:'PO-555', SHIPMENT_DOC_ID:'SHP-001',
  BASE_EXTRACTION_COMPLETED:true, PER_TYPE_EXTRACTION_COMPLETED:true,
  FIGURE_COMPANY_COMPLETED:true, COMPANY_NAME_COMPLETED:true, FIGURE_TYPE_COMPLETED:true,
  AI_EXTRACTION_COMPLETED:true, SELECTION_COMPLETED:true,
  BASE_SELECTION_COMPLETED:true,
  SEARCH_IN_DRIVE_COMPLETED:false, API_TOOLS_ID_COMPLETED:false,
  DOC_DATE_COMPLETED:false, DOC_TOTAL_AMOUNT_COMPLETED:false,
  PURCHASE_ID_COMPLETED:false, SHIPMENT_ID_COMPLETED:false,
};
// One lane per ACTION. seed = decide-case overrides; effect = SQL predicate over the row.
const LANES=[
  {action:'mark_completed',
   seed:{STATUS:'PROCESSING'},
   effect:'"STATUS"=\\'COMPLETED\\''},
  {action:'get_short_doc_id',
   seed:{SHORT_DOC_ID:'99999', STATUS:'PROCESSING'},
   effect:'"SHORT_DOC_ID"=right("DOC_ID",5)'},
  // update_status_missing_link is NOT in decide's SHIPMENT contract (the one typed case
  // is find_link; a linkless all-else-complete shipment simply completes -- measured:
  // the seeds rode the mark_completed batch, exec 3791841). The Ship01 switch arm for it
  // is Inv-clone residue, recorded for the dead-arm cleanup; a sealed lane must not
  // assert a transition the decider cannot answer.
  {action:'update_status_api_tools_failed',
   seed:{API_TOOLS_ID:null, API_TOOLS_ID_COMPLETED:false, STATUS:'PROCESSING'},
   effect:'"STATUS"=\\'API_TOOLS_FAILED\\''},
  {action:'check_from_office',
   seed:{FROM_OFFICE_CHECK:null, STATUS:'PROCESSING'},
   effect:'coalesce("FROM_OFFICE_CHECK",\\'\\')<>\\'\\''},
];
const BATCHES=[1,100];
return [{json:{__instance:'test', BASE, LANES, BATCHES,
  expect_per_lane:BATCHES.reduce((a,b)=>a+b,0)}}];`,
    };

    @node({
        id: 'sls-cleanup',
        name: 'Cleanup Prior',
        /*__n8n__*/ notes: "Prefix sls_ is registered in scripts/test-fixture-prefixes.yaml (columns: ID). Underscore escaped -- `_` is a LIKE wildcard. The action log goes too: LINE_HASH history from a prior run would trip the dup guard and every lane would report no_action_double_action_blocked instead of running.",
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [-340, 100],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    CleanupPrior = {
        operation: 'executeQuery',
        query: "delete from indox_test.indox_action_execution_log where \"ID\" like 'sls\\_%'; delete from indox_test.incoming_documents where \"ID\" like 'sls\\_%';",
        options: {},
    };

    @node({
        id: 'sls-emit-seeds',
        name: 'Emit Seeds',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-120, 100],
    })
    EmitSeeds = {
        jsCode: `const c=$('Config').first().json;
const out=[];
let seq=0;
// [doubles are a FEATURE 2026-08-31] 505 clones sharing DOC_ID/amount/date measured straight
// into update_status_double (driver 3786451) -- decide's SQL doubles detector working as
// designed. Every doc therefore gets a globally unique identity BEFORE the lane's overrides:
// unique DOC_ID/SHORT/NAME/HASH and a varied amount, so no two seeds look like the same
// real-world document. A lane override (get_short's stale SHORT) still wins afterwards.
for(const lane of c.LANES){
  for(const n of c.BATCHES){
    for(let i=0;i<n;i++){
      seq++;
      const sq=String(20000+seq); // per-SUITE offset: identities must be unique ACROSS the sealed
      // family, not just within one run -- in the battery the earlier suites' rows are still
      // in the table (one sweep at battery END), and repeating DOC_ID/amounts clustered five
      // suites into no_action_merge_blocked (measured: driver 3806930, 101/101 blocked).
      const id='sls_'+lane.action+'_b'+n+'_'+String(i).padStart(3,'0');
      const uniq={
        DOC_ID:'INV/2026/'+sq,
        SHORT_DOC_ID:sq,
        NAME:'Acme-'+sq,
        HASH:'hash-'+id,
        DOC_TOTAL_AMOUNT:String(1000+seq),
        // [dup immunity 2026-08-31] The doubles detector's comp-arm key is
        // COMPANY_ID+SHORT_DOC_ID. A shared company means any SHORT collision -- a lane's
        // deliberately-stale '99999', a neighbor suite's rows still in the table mid-battery --
        // clusters into no_action_merge_blocked and zero brackets (battery-2: inv mark 0/101,
        // ship/bs/ord/rcp cascade). A per-doc company makes the key unique BY CONSTRUCTION,
        // whatever else sits in the table; decide only requires it non-empty.
        COMPANY_ID:'CSL'+sq,
        COMPANY_NAME:'Sealed Co '+sq,
      };
      const doc=Object.assign({}, c.BASE, uniq, lane.seed, {ID:id});
      // NAME must agree with the FINAL company+short (lane overrides included): shipment's
      // decide runs its name gate before several targets, so a mismatched NAME steals the
      // lane into update_name (battery-6: three ship lanes, 101x each).
      if(!('NAME' in lane.seed)) doc.NAME=String(doc.COMPANY_NAME)+'-'+String(doc.SHORT_DOC_ID);
      out.push({json:Object.assign({INLINE_ACTION:'UPSERT', __instance:'test'}, doc)});
    }
  }
}
return out;`,
    };

    @node({
        id: 'sls-seed-docs',
        name: 'Seed Docs',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [100, 100],
        alwaysOutputData: true,
    })
    SeedDocs = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {
            waitForSubWorkflow: true,
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
    };

    @node({
        id: 'sls-build-fire',
        name: 'Build Fire',
        /*__n8n__*/ notes: "The drain's 'Fire Lanes' contract, one batch: IDS as a JSON string, tenant on the payload (the driver resolves its schema from __instance -- nothing is inherited over HTTP).",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [320, 100],
    })
    BuildFire = {
        jsCode: `const c=$('Config').first().json;
const ids=[];
for(const lane of c.LANES) for(const n of c.BATCHES) for(let i=0;i<n;i++)
  ids.push('sls_'+lane.action+'_b'+n+'_'+String(i).padStart(3,'0'));
return [{json:{IDS_JSON:JSON.stringify(ids), MAX:2000, DRY:false, __instance:'test', total:ids.length}}];`,
    };

    @node({
        id: 'sls-fire-driver',
        name: 'Fire Driver',
        /*__n8n__*/ notes: "The driver's production webhook entry -- same POST indoxV2BaseDrain01 'Fire Lanes' sends. ACKs in milliseconds ('Respond to Webhook' hangs directly off its 'Webhook'); the work happens in the driver execution the ACK names. The watch loop below is what waits.",
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [540, 100],
        credentials: { httpBasicAuth: { id: 'azPhHBvOWaf9IsEA', name: 'Incoming Documents [env-managed]' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    FireDriver = {
        method: 'POST',
        url: 'http://n8n-webhook:5678/webhook/incoming-documents-017',
        authentication: 'genericCredentialType',
        genericAuthType: 'httpBasicAuth',
        sendBody: true,
        bodyParameters: {
            parameters: [
                { name: 'IDS', value: '={{ $json.IDS_JSON }}' },
                { name: '__instance', value: 'test' },
                { name: 'MAX', value: '={{ $json.MAX }}' },
                { name: 'DRY', value: '={{ $json.DRY }}' },
                { name: 'TRIGGER_TYPE', value: 'sealed-sls' },
                { name: 'DRAINER_TYPE', value: 'sealed_suite' },
                { name: 'DRAINER_ID', value: '={{ "sealed-sls:" + $execution.id }}' },
                { name: 'DRAINER_CHAIN', value: '={{ "sealed-sls:" + $execution.id }}' },
                { name: 'ORIGIN_EXECUTION', value: '={{ $execution.id }}' },
                { name: 'PARENT_EXECUTION', value: '={{ $execution.id }}' },
            ],
        },
        options: {
            timeout: 30000,
        },
    };

    @node({
        id: 'sls-watch',
        name: 'SL Watch',
        /*__n8n__*/ notes: "The completion oracle is the ACTION LOG, and the count is PER LANE, not per action-name: a bracket counts only when its doc-id prefix matches its own lane (starts_with(ID, pfx_ACTION_b)). Counting by action name alone let OTHER lanes' continuation rounds (a rolled doc eventually reaches mark_completed too) fill a lane's quota -- battery-2: inv closed at 151s on cross-lane mark rows while its own mark group (dispatched LAST, router exec 3805442) had not yet run, and Verify then truthfully said 0/101.",
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [760, 100],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 1000,
    })
    SlWatch = {
        operation: 'executeQuery',
        query: "select \"ACTION\" as action, count(*) filter (where \"ENDED_AT\" is not null and starts_with(\"ID\", 'sls_'||\"ACTION\"||'_b'))::int as done from indox_test.indox_action_execution_log where \"ID\" like 'sls\\_%' group by 1",
        options: {},
    };

    @node({
        id: 'sls-guard',
        name: 'SL Guard',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [980, 100],
        alwaysOutputData: true,
    })
    SlGuard = {
        jsCode: `const c=$('Config').first().json;
const rows=$input.all().map(i=>i.json||{});
const by={}; for(const r of rows) if(r&&r.action) by[String(r.action)]=Number(r.done||0);
const want=Number(c.expect_per_lane||101);
const missing=c.LANES.filter(l=>Number(by[l.action]||0)<want).map(l=>l.action+':'+(by[l.action]||0)+'/'+want);
const iter=$runIndex+1, INTERVAL=10, MAX_S=900;
const waited=(iter-1)*INTERVAL;
const ok=missing.length===0;
const timeout=!ok&&waited>=MAX_S;
return [{json:{_watch:'SL', _ok:ok, _timeout:timeout, _done:ok||timeout,
  _iter:iter, _waited_s:waited, _missing:missing, _by:by}}];`,
    };

    @node({
        id: 'sls-ready',
        name: 'SL Ready?',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [1200, 100],
    })
    SlReady = {
        conditions: {
            options: {
                caseSensitive: true,
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'sls-ready-c',
                    leftValue: '={{ $json._done }}',
                    rightValue: '',
                    operator: {
                        type: 'boolean',
                        operation: 'true',
                        singleValue: true,
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: 'sls-sleep',
        name: 'SL Sleep',
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [1180, 240],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    SlSleep = {
        operation: 'executeQuery',
        query: 'select pg_sleep(10)',
        options: {},
    };

    @node({
        id: 'sls-quiesce',
        name: 'Quiesce Fixtures',
        /*__n8n__*/ notes: "[battery tail 2026-08-31] The asserts close on the TARGET action's bracket, but the docs keep ROLLING -- decide answers their next action, and 400-500 continuation dispatches bleed into the NEXT suite's window. Standalone that tail is invisible; in the full battery it starved the following sealed suites into 600s watch timeouts (ship -1/4, bs 0/3, ord/rcp harness-expired, battery 16:2x-17:0x). PAUSE is terminal: the next driver round answers no_action_paused per doc and the tail collapses to cheap no-ops. Runs AFTER the watch closed (the target brackets are in) and BEFORE Verify (whose effect predicates never read the statuses this touches -- COMPLETED/MISSING_LINK/API_TOOLS_FAILED rows are already terminal and are not selected by the not-in filter).",
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [1320, 100],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    QuiesceFixtures = {
        operation: 'executeQuery',
        query: "update indox_test.incoming_documents set \"STATUS\"='PAUSE' where starts_with(\"ID\",'sls_') and \"STATUS\" not in ('COMPLETED','MERGED','OLD','GARBAGE','PAUSE','MAX_ITERATIONS','MISSING_LINK','MISSING_COMPANY_ID','MISSING_TYPE','UNKNOWN_COMPANY','EXTRACTION_FAILED','API_TOOLS_FAILED','PRIORITY_SYNC_FAILED','ACTION_REQUIRED','NEEDS_REVIEW')",
        options: {},
    };

    @node({
        id: 'sls-verify',
        name: 'Verify',
        /*__n8n__*/ notes: "One row per lane: log_done (closed brackets for the lane's action on its own docs) and effect (the lane's SQL predicate over its own docs). Composed from Config's lane table via expressions so a new lane needs no SQL edit here.",
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [1420, 100],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    Verify = {
        operation: 'executeQuery',
        query: `={{ (() => {
const DQ = String.fromCharCode(34); // literal " -- escapes get eaten by the transformer, so none are used
const q = (col) => DQ + col + DQ;
const c = $('Config').first().json;
const parts = c.LANES.map(l => {
  const pfx = 'sls_' + l.action + '_b';
  return "select '" + l.action + "' as action, " +
    "(select count(*)::int from indox_test.indox_action_execution_log " +
    " where starts_with(" + q('ID') + ", '" + pfx + "') and " + q('ACTION') + "='" + l.action + "' and " + q('ENDED_AT') + " is not null) as log_done, " +
    "(select count(*)::int from indox_test.incoming_documents " +
    " where starts_with(" + q('ID') + ", '" + pfx + "') and (" + l.effect + ")) as effect_n, " +
    "(select count(*)::int from indox_test.incoming_documents " +
    " where starts_with(" + q('ID') + ", '" + pfx + "')) as seeded_n";
});
return parts.join(' union all ');
})() }}`,
        options: {},
    };

    @node({
        id: 'sls-assert',
        name: 'Assert Sealed',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1640, 100],
    })
    AssertSealed = {
        jsCode: `const c=$('Config').first().json;
const want=Number(c.expect_per_lane||101);
const rows=$input.all().map(i=>i.json||{});
const by={}; for(const r of rows) if(r&&r.action) by[String(r.action)]=r;
const g=(()=>{try{return $('SL Guard').first().json;}catch(e){return {};}})();
const fails=[];
if(g._timeout) fails.push('WATCH TIMED OUT after '+g._waited_s+'s; still short: '+JSON.stringify(g._missing));
const checks=[];
for(const l of c.LANES){
  const r=by[l.action]||{};
  const seeded=Number(r.seeded_n||0), log=Number(r.log_done||0), eff=Number(r.effect_n||0);
  const lf=[];
  if(seeded!==want) lf.push('seeded '+seeded+'/'+want);
  if(log!==want) lf.push('action-log closed '+log+'/'+want);
  if(eff!==want) lf.push('effect '+eff+'/'+want);
  if(lf.length){ fails.push(l.action+': '+lf.join(', ')); checks.push('\\u274c '+l.action+' \\u2014 '+lf.join(', ')); }
  else checks.push('\\u2705 '+l.action+' \\u2014 sealed at batch 1+100 ('+log+' brackets, '+eff+' effects)');
}
return [{json:{fails, checks, lanes:c.LANES.length, want}}];`,
    };

    @node({
        id: 'sls-summary',
        name: '🏁 Test Summary',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1860, 100],
    })
    TestSummary = {
        jsCode: `const a=$input.first().json;
const passed=(a.lanes - a.fails.length)+'/'+a.lanes;
return [{json:{
  RESULT: a.fails.length? ('\\u274c SEALED SHIPMENT '+a.fails.length+' lane(s) red: '+a.fails.join('; ')) : '\\u2705 ALL TESTS PASS',
  passed, checks:a.checks,
}}];`,
    };

    @node({
        id: 'sls-lane-verdict',
        name: 'Lane Verdict',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2080, 100],
    })
    LaneVerdict = {
        jsCode: "const j=$json; return [{json:{result:String(j.RESULT||'')+' ('+String(j.passed||'')+')', checks:j.checks||[]}}];",
    };

    @node({
        id: 'sls-respond',
        name: 'Respond Lane',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [2300, 100],
        onError: 'continueRegularOutput',
    })
    RespondLane = {
        options: {},
    };

    @links()
    defineRouting() {
        this.RunIndoxV2SealedActionsShipment.out(0).to(this.SeedTestFixtures.in(0));
        this.LaneWebhook.out(0).to(this.SeedTestFixtures.in(0));
        this.SeedTestFixtures.out(0).to(this.Config.in(0));
        this.Config.out(0).to(this.CleanupPrior.in(0));
        this.CleanupPrior.out(0).to(this.EmitSeeds.in(0));
        this.EmitSeeds.out(0).to(this.SeedDocs.in(0));
        this.SeedDocs.out(0).to(this.BuildFire.in(0));
        this.BuildFire.out(0).to(this.FireDriver.in(0));
        this.FireDriver.out(0).to(this.SlWatch.in(0));
        this.SlWatch.out(0).to(this.SlGuard.in(0));
        this.SlGuard.out(0).to(this.SlReady.in(0));
        this.SlReady.out(0).to(this.QuiesceFixtures.in(0));
        this.QuiesceFixtures.out(0).to(this.Verify.in(0));
        this.SlReady.out(1).to(this.SlSleep.in(0));
        this.SlSleep.out(0).to(this.SlWatch.in(0));
        this.Verify.out(0).to(this.AssertSealed.in(0));
        this.AssertSealed.out(0).to(this.TestSummary.in(0));
        this.TestSummary.out(0).to(this.LaneVerdict.in(0));
        this.LaneVerdict.out(0).to(this.RespondLane.in(0));
    }
}
