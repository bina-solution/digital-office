import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox-v2 DOC BASE E2E Test
// Nodes   : 48  |  Connections: 50
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// RunDocBaseE2eTest                  manualTrigger
// Config                             code
// CleanupPrior                       postgres                   [creds]
// SeedCompanies                      postgres                   [creds]
// ExecuteFlows                       noOp
// EmitCases                          code
// BuildSeeds                         code
// SeedCases                          executeWorkflow            [alwaysOutput]
// BuildGetAll                        code
// GetCases                           executeWorkflow            [alwaysOutput]
// PrepCovDecide                      code
// DecideCases                        executeWorkflow            [alwaysOutput]
// AssertDocBaseCoverage              code
// EmitExecCases                      code
// BuildExecSeeds                     code
// SeedExec                           executeWorkflow            [alwaysOutput]
// BuildGetExec                       code
// GetExec                            executeWorkflow            [alwaysOutput]
// InjectExec                         code
// ActCoverage                        executeWorkflow            [alwaysOutput]
// VerifyExecStatus                   postgres                   [creds]
// AssertExecuteCoverage              code
// EmitRealFiles                      code
// ListRealFiles                      executeWorkflow            [alwaysOutput]
// ResolveRealLinks                   code
// LoopUpload                         splitInBatches
// NeedUpload                         if
// DownloadFile                       httpRequest
// UploadFile                         executeWorkflow            [alwaysOutput]
// SetFileLink                        code
// BuildBareSeed                      code
// SeedBare                           executeWorkflow            [alwaysOutput]
// BuildGetLc                         code
// GetLc                              executeWorkflow            [alwaysOutput]
// PrepLcDecide                       code
// DecideLc                           executeWorkflow            [alwaysOutput]
// LcGuard                            code
// LcDone                             if
// ActLc                              executeWorkflow            [alwaysOutput]
// VerifyFullLc                       postgres                   [creds]
// AssertFullLifecycle                code
// TestSummary                        code
// LaneWebhook                        webhook
// LaneVerdict                        code
// RespondLane                        respondToWebhook           [onError→regular]
// BuildTestConnectionsReq            code
// DriveConnections                   executeWorkflow            [alwaysOutput]
// SeedTestFixtures                   executeWorkflow            [alwaysOutput] [retry]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// RunDocBaseE2eTest
//    → SeedTestFixtures
//      → Config
//        → CleanupPrior
//          → SeedCompanies
//            → ExecuteFlows
//              → EmitCases
//                → BuildSeeds
//                  → SeedCases
//                    → BuildGetAll
//                      → GetCases
//                        → PrepCovDecide
//                          → DecideCases
//                            → AssertDocBaseCoverage
//              → EmitExecCases
//                → BuildExecSeeds
//                  → SeedExec
//                    → BuildGetExec
//                      → GetExec
//                        → InjectExec
//                          → ActCoverage
//                            → VerifyExecStatus
//                              → AssertExecuteCoverage
//              → EmitRealFiles
//                → BuildTestConnectionsReq
//                  → DriveConnections
//                    → ListRealFiles
//                      → ResolveRealLinks
//                        → LoopUpload
//                          → BuildGetLc
//                            → GetLc
//                              → PrepLcDecide
//                                → DecideLc
//                                  → LcGuard
//                                    → LcDone
//                                      → VerifyFullLc
//                                        → AssertFullLifecycle
//                                          → TestSummary
//                                            → LaneVerdict
//                                              → RespondLane
//                                     .out(1) → ActLc
//                                        → BuildGetLc (↩ loop)
//                         .out(1) → NeedUpload
//                            → DownloadFile
//                              → UploadFile
//                                → SetFileLink
//                                  → BuildBareSeed
//                                    → SeedBare
//                                      → LoopUpload (↩ loop)
//                           .out(1) → BuildBareSeed (↩ loop)
// LaneWebhook
//    → SeedTestFixtures (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"▶ Run DOC BASE E2E Test":{"main":[[{"node":"Seed Test Fixtures","type":"main","index":0}]]},"Config":{"main":[[{"node":"Cleanup Prior","type":"main","index":0}]]},"Cleanup Prior":{"main":[[{"node":"Seed Companies","type":"main","index":0}]]},"Seed Companies":{"main":[[{"node":"Execute Flows","type":"main","index":0}]]},"Emit Cases":{"main":[[{"node":"Build Seeds","type":"main","index":0}]]},"Build Seeds":{"main":[[{"node":"Seed Cases","type":"main","index":0}]]},"Seed Cases":{"main":[[{"node":"Build GET All","type":"main","index":0}]]},"Build GET All":{"main":[[{"node":"GET Cases","type":"main","index":0}]]},"GET Cases":{"main":[[{"node":"Prep Cov Decide","type":"main","index":0}]]},"Prep Cov Decide":{"main":[[{"node":"Decide Cases","type":"main","index":0}]]},"Decide Cases":{"main":[[{"node":"Assert DOC BASE Coverage","type":"main","index":0}]]},"Execute Flows":{"main":[[{"node":"Emit Cases","type":"main","index":0},{"node":"Emit Exec Cases","type":"main","index":0},{"node":"Emit Real Files","type":"main","index":0}]]},"Emit Exec Cases":{"main":[[{"node":"Build Exec Seeds","type":"main","index":0}]]},"Build Exec Seeds":{"main":[[{"node":"Seed Exec","type":"main","index":0}]]},"Seed Exec":{"main":[[{"node":"Build GET Exec","type":"main","index":0}]]},"Build GET Exec":{"main":[[{"node":"GET Exec","type":"main","index":0}]]},"GET Exec":{"main":[[{"node":"Inject Exec","type":"main","index":0}]]},"Inject Exec":{"main":[[{"node":"Act Coverage","type":"main","index":0}]]},"Act Coverage":{"main":[[{"node":"Verify Exec Status","type":"main","index":0}]]},"Verify Exec Status":{"main":[[{"node":"Assert Execute Coverage","type":"main","index":0}]]},"Emit Real Files":{"main":[[{"node":"Build Test Connections Req","type":"main","index":0}]]},"Build Test Connections Req":{"main":[[{"node":"Drive Connections","type":"main","index":0}]]},"List Real Files":{"main":[[{"node":"Resolve Real Links","type":"main","index":0}]]},"Resolve Real Links":{"main":[[{"node":"Loop Upload","type":"main","index":0}]]},"Loop Upload":{"main":[[{"node":"Build GET LC","type":"main","index":0}],[{"node":"Need Upload?","type":"main","index":0},{"node":"Loop Upload","type":"main","index":0}]]},"Need Upload?":{"main":[[{"node":"Download File","type":"main","index":0}],[{"node":"Build Bare Seed","type":"main","index":0}]]},"Download File":{"main":[[{"node":"Upload File","type":"main","index":0}]]},"Upload File":{"main":[[{"node":"Set File Link","type":"main","index":0}]]},"Set File Link":{"main":[[{"node":"Build Bare Seed","type":"main","index":0}]]},"Build Bare Seed":{"main":[[{"node":"Seed Bare","type":"main","index":0}]]},"Seed Bare":{"main":[[]]},"Build GET LC":{"main":[[{"node":"GET LC","type":"main","index":0}]]},"GET LC":{"main":[[{"node":"Prep LC Decide","type":"main","index":0}]]},"Prep LC Decide":{"main":[[{"node":"Decide LC","type":"main","index":0}]]},"Decide LC":{"main":[[{"node":"LC Guard","type":"main","index":0}]]},"LC Guard":{"main":[[{"node":"LC Done?","type":"main","index":0}]]},"LC Done?":{"main":[[{"node":"Verify Full LC","type":"main","index":0}],[{"node":"Act LC","type":"main","index":0}]]},"Act LC":{"main":[[{"node":"Build GET LC","type":"main","index":0}]]},"Verify Full LC":{"main":[[{"node":"Assert Full Lifecycle","type":"main","index":0}]]},"Assert Full Lifecycle":{"main":[[{"node":"🏁 Test Summary","type":"main","index":0}]]},"Seed Test Fixtures":{"main":[[{"node":"Config","type":"main","index":0}]]},"Drive Connections":{"main":[[{"node":"List Real Files","type":"main","index":0}]]},"Lane Webhook":{"main":[[{"node":"Seed Test Fixtures","type":"main","index":0}]]},"🏁 Test Summary":{"main":[[{"node":"Lane Verdict","type":"main","index":0}]]},"Lane Verdict":{"main":[[{"node":"Respond Lane","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"dcb770a3-465f-4ed5-b5d4-ca1ff6dcd994","name":"lifecycle:test"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"22f1e71e-91bf-48db-811f-8d3bc4e55a3e","name":"sm-refactor-v2.1"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:41:29.646Z","createdAt":"2026-07-30T23:41:29.646Z","id":"9c337cfe-7feb-4f3d-ab26-3de6439357ce","name":"sm-refactore-v2.1"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"indoxV2DocBaseTest01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2DocBaseTest01',
    name: 'indox-v2 DOC BASE E2E Test',
    active: false,
    isArchived: false,
    tags: ['lifecycle:test', 'sm-refactor-v2.1', 'app:indox', 'sm-refactore-v2.1', 'indox-app'],
    settings: { executionOrder: 'v1', executionTimeout: 1800 },
})
export class IndoxV2DocBaseE2eTestWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 't',
        name: '▶ Run DOC BASE E2E Test',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [0, 0],
    })
    RunDocBaseE2eTest = {};

    @node({
        id: 'cfg',
        name: 'Config',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [220, 0],
    })
    Config = {
        jsCode: `
const recent='01/06/2026', old='01/01/2020';
// [2026-08-21] Was a fake ACTION_LOG of 51 timestamps, back when the ceiling counted stamps in
// that string. ITERATION_COUNT is a real counter now (ceiling 15), so the seed states the
// number directly instead of encoding it in prose the test had to fabricate.
const maxiter=51;
// [pin-is-dead 2026-08-31] The suite MINTS its tenant: REST-run pins never reach a
// manualTrigger's item, so reading the trigger was reading {}. The suite's identity IS the
// test tenant (G64 R7 enforces the literal), so Config states it — and still refuses loudly
// if an upstream item somehow carries a DIFFERENT tenant.
const __up=($json||{}).__instance;
if(__up && __up!=='test') throw new Error('indoxV2DocBaseTest01: upstream carries __instance '+JSON.stringify(__up)+' - this suite only runs against the test tenant (indox_test)');
const __i='test';
return [{json:{
  __instance:'test',
  collectionId:'indoxV2ActionsGlobal01',  // router_doc_base
  decideId:'indoxV2Decide01',
  routerId:'indoxApiRouter01',
  testCompany:{id1:'999000111', name:'DocBase Test Co'},
  // seed state -> expected DECIDED action (every docBase branch). expectStatus => also execute-covered.
  // [selection 2026-08-31, aligned to the 2026-08-25 owner order] SELECT BEFORE YOU TERMINALISE:
  // the select-first gate sits ABOVE the company and type gates, so every seed that proves a
  // post-selection branch carries BASE_SELECTION_COMPLETED:true to get past it (measured drift:
  // 15 of 21 cases answered select_base, exec 3735847). Three deliberate exceptions pin the
  // precedence LAW itself: db_select_base (fully-specified doc, no flag -> select_base fires
  // FIRST), and the OLD / PAUSE / MAX_ITERATIONS seeds (no flag -> their gates beat selection).
  coverageCases:[
    {ID:'db_select_base',        expectAction:'select_base',                      seed:{ID:'db_select_base',COMPANY_ID:'C1',COMPANY_NAME:'Acme',TYPE:'INVOICE',DOC_DATE:recent,STATUS:'IN_PROGRESS'}},
    {ID:'db_missing_company',    expectAction:'update_status_missing_company',   expectStatus:'MISSING_COMPANY_ID', seed:{ID:'db_missing_company',TYPE:'INVOICE',STATUS:'IN_PROGRESS',BASE_SELECTION_COMPLETED:true}},
    {ID:'db_awaiting_company',   expectAction:'no_action_awaiting_company_id',    seed:{ID:'db_awaiting_company',TYPE:'INVOICE',STATUS:'MISSING_COMPANY_ID',BASE_SELECTION_COMPLETED:true}},
    // LINK_CONNECTION is threaded onto the doc at pickup and is NOT a column on
    // incoming_documents (the table has CONNECTION, a different field), so this
    // table-driven suite structurally cannot seed it - seeding it fails the INSERT.
    // What this case CAN prove is the drive-connection guard itself: a row holding a LINK
    // with no reachable connection must NOT enter base extraction. That guard exists
    // because such rows generated 92 drive api errors an hour, doubling every 5 minutes
    // ('requires an explicit profile_id or connection_id'). It falls to the company branch
    // and terminalizes, which is the correct answer for a file that cannot be opened.
    // The positive case - link + connection + no type -> extract_base_doc - is asserted in
    // indoxV2DecideTest01, which seeds the decide with an object and can set the field.
    {ID:'db_extract_base',       expectAction:'update_status_missing_company',    expectStatus:'MISSING_COMPANY_ID', seed:{ID:'db_extract_base',LINK:'http://x/f',STATUS:'IN_PROGRESS',BASE_SELECTION_COMPLETED:true}},
    {ID:'db_figure_company',     expectAction:'update_status_missing_company',    expectStatus:'MISSING_COMPANY_ID', seed:{ID:'db_figure_company',TYPE:'INVOICE',LINK:'http://x/f',BASE_EXTRACTION_COMPLETED:true,STATUS:'IN_PROGRESS',BASE_SELECTION_COMPLETED:true}},
    {ID:'db_get_name',           expectAction:'get_company_name',                 seed:{ID:'db_get_name',COMPANY_ID:'C1',TYPE:'INVOICE',STATUS:'IN_PROGRESS',BASE_SELECTION_COMPLETED:true}},
    {ID:'db_unknown_company',    expectAction:'update_status_unknwon_company',    expectStatus:'UNKNOWN_COMPANY',    seed:{ID:'db_unknown_company',COMPANY_ID:'C1',COMPANY_NAME:'unknown',COMPANY_NAME_COMPLETED:true,TYPE:'INVOICE',STATUS:'IN_PROGRESS',BASE_SELECTION_COMPLETED:true}},
    {ID:'db_awaiting_name',      expectAction:'no_action_awaiting_company_name',  seed:{ID:'db_awaiting_name',COMPANY_ID:'C1',COMPANY_NAME:'unknown',COMPANY_NAME_COMPLETED:true,TYPE:'INVOICE',STATUS:'UNKNOWN_COMPANY',BASE_SELECTION_COMPLETED:true}},
    {ID:'db_missing_type',       expectAction:'update_status_missing_type',       expectStatus:'MISSING_TYPE',       seed:{ID:'db_missing_type',COMPANY_ID:'C1',COMPANY_NAME:'Acme',FIGURE_TYPE_COMPLETED:true,DOC_DATE:recent,STATUS:'IN_PROGRESS',BASE_SELECTION_COMPLETED:true}},
    {ID:'db_old',                expectAction:'update_status_old_doc',            expectStatus:'OLD',                seed:{ID:'db_old',COMPANY_ID:'C1',COMPANY_NAME:'Acme',TYPE:'INVOICE',DOC_DATE:old,STATUS:'IN_PROGRESS'}},
    {ID:'db_old_noaction',       expectAction:'no_action_old_date',               seed:{ID:'db_old_noaction',COMPANY_ID:'C1',COMPANY_NAME:'Acme',TYPE:'INVOICE',DOC_DATE:old,STATUS:'OLD'}},
    {ID:'db_paused',             expectAction:'no_action_paused',                 seed:{ID:'db_paused',COMPANY_ID:'C1',COMPANY_NAME:'Acme',TYPE:'INVOICE',DOC_DATE:recent,STATUS:'PAUSE'}},
    {ID:'db_no_double',          expectAction:'__route_invoice__',                   seed:{ID:'db_no_double',COMPANY_ID:'C1',COMPANY_NAME:'Acme',TYPE:'INVOICE',DOC_DATE:recent,STATUS:'DOUBLE',BASE_SELECTION_COMPLETED:true}}, // STATUS=DOUBLE with NO current dup match must now fall through and re-route, not stay DOUBLE forever (DOUBLE self-heal fix)
    {ID:'db_maxiter',            expectAction:'mark_max_iterations',              expectStatus:'MAX_ITERATIONS',     seed:{ID:'db_maxiter',COMPANY_ID:'C1',COMPANY_NAME:'Acme',TYPE:'INVOICE',DOC_DATE:recent,STATUS:'IN_PROGRESS',ITERATION_COUNT:maxiter}},
    {ID:'db_maxiter_noaction',   expectAction:'no_action_max_iterations',         seed:{ID:'db_maxiter_noaction',COMPANY_ID:'C1',COMPANY_NAME:'Acme',TYPE:'INVOICE',DOC_DATE:recent,STATUS:'MAX_ITERATIONS',ITERATION_COUNT:maxiter}},
    {ID:'db_figure_type',        expectAction:'update_status_missing_type',       expectStatus:'MISSING_TYPE',       seed:{ID:'db_figure_type',COMPANY_ID:'C1',COMPANY_NAME:'Acme',DOC_DATE:recent,STATUS:'IN_PROGRESS',BASE_SELECTION_COMPLETED:true}},
    {ID:'db_route_invoice',         expectAction:'__route_invoice__',                   seed:{ID:'db_route_invoice',COMPANY_ID:'C1',COMPANY_NAME:'Acme',TYPE:'INVOICE',DOC_DATE:recent,STATUS:'IN_PROGRESS',BASE_SELECTION_COMPLETED:true}},
    {ID:'db_route_bs',           expectAction:'__route_bs__',                     seed:{ID:'db_route_bs',COMPANY_ID:'C1',COMPANY_NAME:'Acme',TYPE:'BALANCE_SHEET',DOC_DATE:recent,STATUS:'IN_PROGRESS',BASE_SELECTION_COMPLETED:true}},
    // [five classes 2026-08-27] ORDER and RECEIPT route to their OWN parked lanes. Before this,
    // ORDER resolved to the invoice class (and RECEIPT to none at all, landing MISSING_TYPE) —
    // so these two cases are the doc_base half of that split, asserted where routing is owned.
    {ID:'db_route_order',        expectAction:'__route_order__',                  seed:{ID:'db_route_order',COMPANY_ID:'C1',COMPANY_NAME:'Acme',TYPE:'ORDER',DOC_DATE:recent,STATUS:'IN_PROGRESS',BASE_SELECTION_COMPLETED:true}},
    {ID:'db_route_receipt',      expectAction:'__route_receipt__',                seed:{ID:'db_route_receipt',COMPANY_ID:'C1',COMPANY_NAME:'Acme',TYPE:'RECEIPT',DOC_DATE:recent,STATUS:'IN_PROGRESS',BASE_SELECTION_COMPLETED:true}},
    // [SQL doubles 2026-08-23, owner design] db_double_dec REMOVED — "one detector, one decision,
    // one place": doubles are decided ONLY in indoxV2Decide01 from the driver's SQL flags, BEFORE
    // any docBase routing, and Global01's in-memory detector is gone entirely. This suite's unit is
    // Global01's docBase decide, which by design never sees a double; the four-way doubles verdict
    // (update_status_double / no_action_double / action_merge_doubles / no_action_merge_blocked)
    // is asserted where it lives, in indoxV2DecideTest01. The docBase-owned double fact that
    // remains is db_no_double above: a stale STATUS='DOUBLE' row with no live flag re-routes.
    // The update_status_double HANDLER (not the verdict) is still execute-covered by dbe_double.
    {ID:'db_unknown_type',       expectAction:'no_action_unknown_document_type',  seed:{ID:'db_unknown_type',COMPANY_ID:'C1',COMPANY_NAME:'Acme',FIGURE_TYPE_COMPLETED:true,DOC_DATE:recent,STATUS:'MISSING_TYPE',BASE_SELECTION_COMPLETED:true}},
  ],
  // execute coverage: inject each handler's ACTION + mode=execute -> Act -> assert STATUS (ALL 9 in ONE batch)
  executeCases:[
    {ID:'dbe_missing_company', action:'update_status_missing_company', expectStatus:'MISSING_COMPANY_ID', seed:{ID:'dbe_missing_company',TYPE:'INVOICE',STATUS:'IN_PROGRESS'}},
    {ID:'dbe_unknown_company', action:'update_status_unknwon_company', expectStatus:'UNKNOWN_COMPANY',    seed:{ID:'dbe_unknown_company',COMPANY_ID:'C1',STATUS:'IN_PROGRESS'}},
    {ID:'dbe_missing_type',    action:'update_status_missing_type',    expectStatus:'MISSING_TYPE',       seed:{ID:'dbe_missing_type',COMPANY_ID:'C1',STATUS:'IN_PROGRESS'}},
    {ID:'dbe_old',             action:'update_status_old_doc',         expectStatus:'OLD',                seed:{ID:'dbe_old',COMPANY_ID:'C1',STATUS:'IN_PROGRESS'}},
    {ID:'dbe_maxiter',         action:'mark_max_iterations',           expectStatus:'MAX_ITERATIONS',     seed:{ID:'dbe_maxiter',COMPANY_ID:'C1',STATUS:'IN_PROGRESS'}},
    {ID:'dbe_double',          action:'update_status_double',          expectStatus:'DOUBLE',             seed:{ID:'dbe_double',COMPANY_ID:'C1',STATUS:'IN_PROGRESS'}, inject:{DOUBLE_CONTEXT:{match:true,matchedId:'other',idMatch:'other'}}},
    {ID:'dbe_await_company',   action:'no_action_awaiting_company_id', expectStatus:'MISSING_COMPANY_ID', seed:{ID:'dbe_await_company',TYPE:'INVOICE',STATUS:'MISSING_COMPANY_ID'}},
    {ID:'dbe_await_name',      action:'no_action_awaiting_company_name',expectStatus:'UNKNOWN_COMPANY',   seed:{ID:'dbe_await_name',COMPANY_ID:'C1',STATUS:'UNKNOWN_COMPANY'}},
    {ID:'dbe_maxiter_na',      action:'no_action_max_iterations',      expectStatus:'MAX_ITERATIONS',     seed:{ID:'dbe_maxiter_na',COMPANY_ID:'C1',STATUS:'MAX_ITERATIONS',ITERATION_COUNT:maxiter}},
  ],
  lifecycleSeed:{ID:'db_lc_1',COMPANY_ID:'999000111',TYPE:'INVOICE',DOC_DATE:recent,STATUS:'IN_PROGRESS'},
  lifecycleExpectAction:'__route_invoice__',
  lifecycleExpectName:'DocBase Test Co',
  // real demo-doc files (one per type) served at demoBase; figure-coverage runs the REAL classifier +
  // company resolver on them and asserts. Company expected from the GDoc/BS fixtures where known.
  demoBase:'http://indox-demo-docs:8088',
  figureFiles:[
    {ID:'dbf_inv', upname:'dbf_inv-agn-3.162b24.pdf',      path:'invoice/files/agn-3.dbf.pdf',            expectType:'INVOICE',       expectCompany:'511301129'},
    {ID:'dbf_ord', upname:'dbf_ord-PO25010001.fd669c.png', path:'order/files/PO25010001.dbf.png',         expectType:'ORDER',         expectCompany:'511234567'},
    {ID:'dbf_shp', upname:'dbf_shp-by-gy-4.995211.pdf',     path:'shipment/files/by-gy-4.dbf.pdf',         expectType:'SHIPMENT',      expectCompany:'514291418'},
    {ID:'dbf_bs',  upname:'dbf_bs-asyp-shr-ts-1.pdf',path:'balance_sheet/files/asyp-shr-ts-1.dbf.pdf',expectType:'BALANCE_SHEET', expectCompany:'516618881', seedCompany:'516618881'},
  ],
}}];
`,
    };

    @node({
        id: 'cl',
        name: 'Cleanup Prior',
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [440, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    CleanupPrior = {
        operation: 'executeQuery',
        query: 'DELETE FROM indox_test.incoming_documents WHERE "ID" LIKE \'db\\_%\' OR "ID" LIKE \'dbf\\_%\' OR "ID" LIKE \'dbe\\_%\';',
        options: {},
    };

    @node({
        id: 'sc',
        name: 'Seed Companies',
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [660, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    SeedCompanies = {
        operation: 'executeQuery',
        query: "INSERT INTO indox_test.companies (\"instance\", \"מזהה 1\", \"שם חברה\") VALUES ('incoming-documents-main','999000111','DocBase Test Co'),('incoming-documents-main','511301129','Fig Inv Co'),('incoming-documents-main','511234567','Fig Ord Co'),('incoming-documents-main','514291418','Fig Shp Co'),('incoming-documents-main','516618881','Asif Schar Etz') ON CONFLICT (\"instance\", \"מזהה 1\") DO UPDATE SET \"שם חברה\"=EXCLUDED.\"שם חברה\";",
        options: {},
    };

    @node({
        id: 'xf',
        name: 'Execute Flows',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [880, 0],
    })
    ExecuteFlows = {};

    @node({
        id: 'a1',
        name: 'Emit Cases',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1040, -300],
    })
    EmitCases = {
        jsCode: "return $('Config').first().json.coverageCases.map(c=>({json:c}));",
    };

    @node({
        id: 'a2',
        name: 'Build Seeds',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1260, -300],
    })
    BuildSeeds = {
        jsCode: "return $input.all().map(i=>({json:{INLINE_ACTION:'UPSERT', ...i.json.seed, __instance:'test'}}));",
    };

    @node({
        id: 'a3',
        name: 'Seed Cases',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1480, -300],
        alwaysOutputData: true,
    })
    SeedCases = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'a4',
        name: 'Build GET All',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1700, -300],
    })
    BuildGetAll = {
        jsCode: "return [{json:{INLINE_ACTION:'GET', __instance:'test', ids:$('Config').first().json.coverageCases.map(c=>c.ID).join(',')}}];",
    };

    @node({
        id: 'a5',
        name: 'GET Cases',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1920, -300],
        alwaysOutputData: true,
    })
    GetCases = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'a6',
        name: 'Prep Cov Decide',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2140, -300],
    })
    PrepCovDecide = {
        jsCode: "const byId=Object.fromEntries($('Config').first().json.coverageCases.map(c=>[c.ID,c])); return $('GET Cases').all().map(i=>{const c=byId[i.json.ID]||{}; return {json:{...i.json, mode:'decide', __instance:'test', ...(c.inject||{})}};});",
    };

    @node({
        id: 'a7',
        name: 'Decide Cases',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2360, -300],
        alwaysOutputData: true,
    })
    DecideCases = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ActionsGlobal01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'a8',
        name: 'Assert DOC BASE Coverage',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2580, -300],
    })
    AssertDocBaseCoverage = {
        jsCode: `
const cfg=$('Config').first().json;
const want=Object.fromEntries(cfg.coverageCases.map(c=>[c.ID,c.expectAction]));
const got=Object.fromEntries($input.all().map(i=>[i.json.ID,i.json.ACTION]));
const n=$input.all().length; const fails=[];
for(const [id,a] of Object.entries(want)){ if(got[id]!==a) fails.push(id+': exp '+a+' got '+(got[id]||'MISSING')); }
if(n!==cfg.coverageCases.length) fails.push('BATCH: decided '+n+' of '+cfg.coverageCases.length+' in one call');
if(fails.length) throw new Error('DOC BASE decide coverage FAIL: '+fails.join('; '));
return [{json:{result:'✅ DOC BASE DECIDE COVERAGE PASS', cases:cfg.coverageCases.length, decided_in_one_batch:n}}];
`,
    };

    @node({
        id: 'b1',
        name: 'Emit Exec Cases',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1040, 0],
    })
    EmitExecCases = {
        jsCode: "return $('Config').first().json.executeCases.map(c=>({json:c}));",
    };

    @node({
        id: 'b2',
        name: 'Build Exec Seeds',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1260, 0],
    })
    BuildExecSeeds = {
        jsCode: "return $input.all().map(i=>({json:{INLINE_ACTION:'UPSERT', ...i.json.seed, __instance:'test'}}));",
    };

    @node({
        id: 'b3',
        name: 'Seed Exec',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1480, 0],
        alwaysOutputData: true,
    })
    SeedExec = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'b4',
        name: 'Build GET Exec',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1700, 0],
    })
    BuildGetExec = {
        jsCode: "return [{json:{INLINE_ACTION:'GET', __instance:'test', ids:$('Config').first().json.executeCases.map(c=>c.ID).join(',')}}];",
    };

    @node({
        id: 'b5',
        name: 'GET Exec',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1920, 0],
        alwaysOutputData: true,
    })
    GetExec = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'b6',
        name: 'Inject Exec',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2140, 0],
    })
    InjectExec = {
        jsCode: "const byId=Object.fromEntries($('Config').first().json.executeCases.map(c=>[c.ID,c])); return $('GET Exec').all().map(i=>{const c=byId[i.json.ID]||{}; return {json:{...i.json, ACTION:c.action, mode:'execute', __instance:'test', ...(c.inject||{})}};});",
    };

    @node({
        id: 'b9',
        name: 'Act Coverage',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2360, 0],
        alwaysOutputData: true,
    })
    ActCoverage = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ActionsGlobal01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'b10',
        name: 'Verify Exec Status',
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [2580, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    VerifyExecStatus = {
        operation: 'executeQuery',
        query: '=SELECT "ID","STATUS" FROM indox_test.incoming_documents WHERE "ID" IN ({{ $(\'Config\').first().json.executeCases.map(c=>String.fromCharCode(39)+c.ID+String.fromCharCode(39)).join(\',\') }})',
        options: {},
    };

    @node({
        id: 'b11',
        name: 'Assert Execute Coverage',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2800, 0],
    })
    AssertExecuteCoverage = {
        jsCode: `
const cfg=$('Config').first().json;
const want=Object.fromEntries(cfg.executeCases.map(c=>[c.ID,c.expectStatus]));
const got=Object.fromEntries($input.all().map(i=>[i.json.ID,i.json.STATUS])); const fails=[];
for(const [id,st] of Object.entries(want)){ if(got[id]!==st) fails.push(id+': exp STATUS '+st+' got '+(got[id]||'MISSING')); }
if(fails.length) throw new Error('DOC BASE execute coverage FAIL: '+fails.join('; '));
return [{json:{result:'✅ DOC BASE EXECUTE COVERAGE PASS', handlers_executed:Object.keys(want).length}}];
`,
    };

    @node({
        id: 'c1',
        name: 'Emit Real Files',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1040, 380],
    })
    EmitRealFiles = {
        jsCode: "return $('Config').first().json.figureFiles.map(f=>({json:f}));",
    };

    @node({
        id: 'c2',
        name: 'List Real Files',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1260, 380],
        alwaysOutputData: true,
    })
    ListRealFiles = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'list',
                params: "={{ ({ nameContains: 'dbf_', includeTrashed: false, limit: 50, profile_id: 'admin' }) }}",
            },
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'c3',
        name: 'Resolve Real Links',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1480, 380],
    })
    ResolveRealLinks = {
        jsCode: "const cfg=$('Config').first().json; const byName={}; $input.all().map(i=>i.json).filter(f=>f&&f.name).forEach(f=>{byName[f.name]=f.webViewLink;}); return cfg.figureFiles.map(f=>({json:{...f, LINK:(byName[f.upname]||null), _missing:!byName[f.upname]}}));",
    };

    @node({
        id: 'c4',
        name: 'Loop Upload',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [1700, 380],
    })
    LoopUpload = {
        batchSize: 1,
        options: {},
    };

    @node({
        id: 'c5',
        name: 'Need Upload?',
        type: 'n8n-nodes-base.if',
        version: 2,
        position: [1920, 236],
    })
    NeedUpload = {
        conditions: {
            options: {
                caseSensitive: true,
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    leftValue: '={{ $json._missing }}',
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
    };

    @node({
        id: 'c6',
        name: 'Download File',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [2140, 580],
    })
    DownloadFile = {
        url: "={{ $('Config').first().json.demoBase + '/' + $('Loop Upload').item.json.path }}",
        options: {
            response: {
                response: {
                    responseFormat: 'file',
                },
            },
        },
    };

    @node({
        id: 'c7',
        name: 'Upload File',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2360, 580],
        alwaysOutputData: true,
    })
    UploadFile = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'upload',
                params: "={{ ({ name: $('Loop Upload').item.json.upname, profile_id: 'admin' }) }}",
            },
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'c8',
        name: 'Set File Link',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2580, 580],
    })
    SetFileLink = {
        jsCode: "return [{json:{...$('Loop Upload').item.json, LINK:$input.first().json.webViewLink}}];",
    };

    @node({
        id: 'c9',
        name: 'Build Bare Seed',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2360, 720],
    })
    BuildBareSeed = {
        jsCode: "/* [2026-08-21] A BARE LINK IS NOT AN OPENABLE LINK. The drive-connection guard (indoxV2ActionsGDoc01, 'A LINK WE CANNOT OPEN IS A MISSING LINK') counts a blank LINK_CONNECTION as a missing link, so these bare seeds were routed to find_link instead of entering the lifecycle - phase 3 reported 0 actions/doc for all four files. [phase-4 2026-08-31] The id is still never hardcoded (per-deployment vault hash, a fresh deploy mints a different one), but it is no longer discovered via driveApi01 op:connections - it comes from the test tenant's settings row test_connections (indoxApi01 TABLE_GET), parsed as JSON.parse(value).drive_connection_id. */ const d=$json; const __row=$('Drive Connections').all().map(i=>i.json).find(r=>r&&r.value); let __cx=null; try { __cx=(JSON.parse(__row.value)||{}).drive_connection_id||null; } catch(e) {} if(!__cx) throw new Error('no drive connection - settings row test_connections missing or unparseable (indoxApi01 TABLE_GET on indox_test)'); return [{json:{INLINE_ACTION:'UPSERT', __instance:'test', ID:d.ID, LINK:d.LINK, LINK_CONNECTION:__cx, ...(d.seedCompany?{COMPANY_ID:d.seedCompany}:{}), STATUS:'IN_PROGRESS', }}];",
    };

    @node({
        id: 'c10',
        name: 'Seed Bare',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2580, 720],
        alwaysOutputData: true,
    })
    SeedBare = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'c11',
        name: 'Build GET LC',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1900, 380],
    })
    BuildGetLc = {
        jsCode: "return [{json:{INLINE_ACTION:'GET', __instance:'test', ids:$('Config').first().json.figureFiles.map(f=>f.ID).join(',')}}];",
    };

    @node({
        id: 'c12',
        name: 'GET LC',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2120, 380],
        alwaysOutputData: true,
    })
    GetLc = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'c13',
        name: 'Prep LC Decide',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2340, 380],
    })
    PrepLcDecide = {
        jsCode: "return $input.all().map(i=>({json:{...i.json, mode:'decide', __instance:'test', _dup:{match:false}, _cfg:{old_document_months_back:240}}}));",
    };

    @node({
        id: 'c14',
        name: 'Decide LC',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2560, 380],
        alwaysOutputData: true,
    })
    DecideLc = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ActionsGlobal01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'c15',
        name: 'LC Guard',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2780, 380],
    })
    LcGuard = {
        jsCode: `
const items=$input.all().map(i=>i.json);
const act=items.filter(j=> j.ACTION && !String(j.ACTION).startsWith('__route_') && !String(j.ACTION).startsWith('no_action'));
const s=$getWorkflowStaticData('global'); s.lcIter=(s.lcIter||0)+1;
if(act.length===0 || s.lcIter>15) return [{json:{_done:true, iter:s.lcIter}}];
return act.map(j=>({json:{...j, mode:'execute', __instance:'test'}}));   // execute the actionable docs this pass ([phase-4 2026-08-31] re-stamped: decide's output rows do not carry the tenant)
`,
    };

    @node({
        id: 'c16',
        name: 'LC Done?',
        type: 'n8n-nodes-base.if',
        version: 2,
        position: [3000, 380],
    })
    LcDone = {
        conditions: {
            options: {
                caseSensitive: true,
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
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
    };

    @node({
        id: 'c17',
        name: 'Act LC',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [3000, 580],
        alwaysOutputData: true,
    })
    ActLc = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ActionsGlobal01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'c18',
        name: 'Verify Full LC',
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [3220, 380],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    VerifyFullLc = {
        operation: 'executeQuery',
        query: '=SELECT "ID","TYPE","COMPANY_ID","COMPANY_NAME","STATUS" FROM indox_test.incoming_documents WHERE "ID" IN ({{ $(\'Config\').first().json.figureFiles.map(f=>String.fromCharCode(39)+f.ID+String.fromCharCode(39)).join(\',\') }})',
        options: {},
    };

    @node({
        id: 'c19',
        name: 'Assert Full Lifecycle',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3440, 380],
    })
    AssertFullLifecycle = {
        jsCode: `
const ff=$('Config').first().json.figureFiles;
const got=Object.fromEntries($input.all().map(i=>[i.json.ID,i.json]));
const norm=s=>String(s||'').replace(/\\D/g,'').slice(-6);
const fails=[]; let acts='';
ff.forEach(f=>{ const d=got[f.ID]||{};
  if(d.TYPE!==f.expectType) fails.push(f.ID+' TYPE:'+f.expectType+'!='+(d.TYPE||'MISSING'));
  if(f.expectCompany && norm(d.COMPANY_ID)!==norm(f.expectCompany)) fails.push(f.ID+' COMPANY:'+f.expectCompany+'!='+(d.COMPANY_ID||'MISSING'));
  if(f.ID==='dbf_inv') acts=(Number(d.ITERATION_COUNT)||0)+' actions';
});
const bad=new Set(fails.map(x=>x.split(' ')[0])); const pass=ff.length-bad.size;
return [{json:{result:(fails.length?('❌ full-lifecycle '+pass+'/'+ff.length+': '+fails.join('; ')):('✅ FULL LIFECYCLE PASS '+ff.length+'/'+ff.length)), passed:pass+'/'+ff.length, fails, note:'bare link -> figure_company -> get_name -> figure_type -> route ('+acts+'/doc)'}}];
`,
    };

    @node({
        id: 'sum',
        name: '🏁 Test Summary',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3660, 380],
    })
    TestSummary = {
        jsCode: `
const g=(node,path)=>{try{const j=$(node).first().json;return path.split('.').reduce((o,k)=>o&&o[k],j);}catch(e){return undefined;}};
const cov=g('Assert DOC BASE Coverage','result'), covN=g('Assert DOC BASE Coverage','decided_in_one_batch');
const exe=g('Assert Execute Coverage','result'), exeN=g('Assert Execute Coverage','handlers_executed');
const fl=g('Assert Full Lifecycle','result'), fln=g('Assert Full Lifecycle','note');
const checks=[
  {phase:'1· Decide coverage (all branches, ONE batch)',       ok:(cov||'').includes('PASS'), detail:cov+' ('+covN+' docs / 1 Decide call)'},
  {phase:'2· Execute coverage (handlers write STATUS, batch)',  ok:(exe||'').includes('PASS'), detail:exe+' ('+exeN+' handlers)'},
  {phase:'3· Full lifecycle on REAL files (batch, all types)',  ok:(fl||'').includes('PASS'),  detail:fl+' '+(fln||'')},
];
const passed=checks.filter(c=>c.ok).length;
return [{json:{RESULT:passed===checks.length?'✅ ALL TESTS PASS':'❌ FAILURES PRESENT', passed:passed+'/'+checks.length, checks:checks.map(c=>(c.ok?'✅ ':'❌ ')+c.phase+' — '+c.detail)}}];
`,
    };

    @node({
        id: 'dbt-lane-webhook',
        webhookId: 'doc-base-e2e-lane',
        name: 'Lane Webhook',
        /*__n8n__*/ notes: "[ui-lane 2026-08-31] The console's בדיקות tab runs suites through webhook lanes (BFF _run_one_lane POSTs {lane} and reads back items whose `result` contains PASS). One lane ('all'): the same graph the CLI runs, entered here instead of the manual trigger. The body carries no tenant — Config mints 'test' (pin-is-dead).",
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [0, 200],
    })
    LaneWebhook = {
        httpMethod: 'POST',
        path: 'doc-base-e2e-lane',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'dbt-lane-verdict',
        name: 'Lane Verdict',
        /*__n8n__*/ notes: "[ui-lane 2026-08-31] Shim between the harness contract (🏁 emits RESULT/passed/checks) and the webhook contract (lowercase `result` containing PASS).",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3880, 380],
    })
    LaneVerdict = {
        jsCode: "const j=$json; return [{json:{result:String(j.RESULT||'')+' ('+String(j.passed||'')+')', checks:j.checks||[]}}];",
    };

    @node({
        id: 'dbt-lane-respond',
        name: 'Respond Lane',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [4100, 380],
        onError: 'continueRegularOutput',
    })
    RespondLane = {
        respondWith: 'allIncomingItems',
        options: {},
    };

    @node({
        id: 'dbf-cxreq',
        name: 'Build Test Connections Req',
        /*__n8n__*/ notes: "[phase-4 2026-08-31] Emits the ONE payload 'Drive Connections' sends to indoxApi01. Needed because indoxApi01's trigger is passthrough (no declared inputs), so the executeWorkflow node forwards its input items verbatim - without this shim it would forward 'Emit Real Files' four figure-file items, which carry no INLINE_ACTION and would be UPSERTed as documents.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [920, 300],
    })
    BuildTestConnectionsReq = {
        jsCode: "return [{json:{INLINE_ACTION:'TABLE_GET', table:'settings', __instance:'test', instance:'*', filter:{key:'test_connections'}}}];",
    };

    @node({
        id: 'dbf-cx',
        name: 'Drive Connections',
        /*__n8n__*/ notes: "[phase-4 2026-08-31] Retargeted from driveApi01 op:connections to indoxApi01 TABLE_GET on the test tenant's settings row test_connections - suites make zero discovery calls. Node name kept: 'Build Bare Seed' references $('Drive Connections') and now parses JSON.parse(row.value).drive_connection_id.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1080, 300],
        alwaysOutputData: true,
    })
    DriveConnections = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'fe5d0960-77e3-465a-8d64-a759ce856ddc',
        name: 'Seed Test Fixtures',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [90, -120],
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 10000,
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
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.RunDocBaseE2eTest.out(0).to(this.SeedTestFixtures.in(0));
        this.Config.out(0).to(this.CleanupPrior.in(0));
        this.CleanupPrior.out(0).to(this.SeedCompanies.in(0));
        this.SeedCompanies.out(0).to(this.ExecuteFlows.in(0));
        this.EmitCases.out(0).to(this.BuildSeeds.in(0));
        this.BuildSeeds.out(0).to(this.SeedCases.in(0));
        this.SeedCases.out(0).to(this.BuildGetAll.in(0));
        this.BuildGetAll.out(0).to(this.GetCases.in(0));
        this.GetCases.out(0).to(this.PrepCovDecide.in(0));
        this.PrepCovDecide.out(0).to(this.DecideCases.in(0));
        this.DecideCases.out(0).to(this.AssertDocBaseCoverage.in(0));
        this.ExecuteFlows.out(0).to(this.EmitCases.in(0));
        this.ExecuteFlows.out(0).to(this.EmitExecCases.in(0));
        this.ExecuteFlows.out(0).to(this.EmitRealFiles.in(0));
        this.EmitExecCases.out(0).to(this.BuildExecSeeds.in(0));
        this.BuildExecSeeds.out(0).to(this.SeedExec.in(0));
        this.SeedExec.out(0).to(this.BuildGetExec.in(0));
        this.BuildGetExec.out(0).to(this.GetExec.in(0));
        this.GetExec.out(0).to(this.InjectExec.in(0));
        this.InjectExec.out(0).to(this.ActCoverage.in(0));
        this.ActCoverage.out(0).to(this.VerifyExecStatus.in(0));
        this.VerifyExecStatus.out(0).to(this.AssertExecuteCoverage.in(0));
        this.EmitRealFiles.out(0).to(this.BuildTestConnectionsReq.in(0));
        this.BuildTestConnectionsReq.out(0).to(this.DriveConnections.in(0));
        this.ListRealFiles.out(0).to(this.ResolveRealLinks.in(0));
        this.ResolveRealLinks.out(0).to(this.LoopUpload.in(0));
        this.LoopUpload.out(0).to(this.BuildGetLc.in(0));
        this.LoopUpload.out(1).to(this.NeedUpload.in(0));
        this.NeedUpload.out(0).to(this.DownloadFile.in(0));
        this.NeedUpload.out(1).to(this.BuildBareSeed.in(0));
        this.DownloadFile.out(0).to(this.UploadFile.in(0));
        this.UploadFile.out(0).to(this.SetFileLink.in(0));
        this.SetFileLink.out(0).to(this.BuildBareSeed.in(0));
        this.BuildBareSeed.out(0).to(this.SeedBare.in(0));
        this.SeedBare.out(0).to(this.LoopUpload.in(0));
        this.BuildGetLc.out(0).to(this.GetLc.in(0));
        this.GetLc.out(0).to(this.PrepLcDecide.in(0));
        this.PrepLcDecide.out(0).to(this.DecideLc.in(0));
        this.DecideLc.out(0).to(this.LcGuard.in(0));
        this.LcGuard.out(0).to(this.LcDone.in(0));
        this.LcDone.out(0).to(this.VerifyFullLc.in(0));
        this.LcDone.out(1).to(this.ActLc.in(0));
        this.ActLc.out(0).to(this.BuildGetLc.in(0));
        this.VerifyFullLc.out(0).to(this.AssertFullLifecycle.in(0));
        this.AssertFullLifecycle.out(0).to(this.TestSummary.in(0));
        this.SeedTestFixtures.out(0).to(this.Config.in(0));
        this.DriveConnections.out(0).to(this.ListRealFiles.in(0));
        this.LaneWebhook.out(0).to(this.SeedTestFixtures.in(0));
        this.TestSummary.out(0).to(this.LaneVerdict.in(0));
        this.LaneVerdict.out(0).to(this.RespondLane.in(0));
    }
}
