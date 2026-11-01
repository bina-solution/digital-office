import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox-v2 BS E2E Test
// Nodes   : 77  |  Connections: 73
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// NConfig                            stickyNote
// RunBsE2eTest                       manualTrigger
// ConfigBase                         code
// NSetup                             stickyNote
// CaptureFlagOff                     redis                      [creds]
// CleanupPrior                       postgres                   [creds]
// BuildSeed                          code
// SeedBsDoc                          executeWorkflow            [alwaysOutput]
// BuildExistingInvoices              code
// SeedExistingInvoices               executeWorkflow            [alwaysOutput]
// NPrime                             stickyNote
// SetLink                            code
// DownloadForHash                    executeWorkflow            [alwaysOutput]
// CryptoHash                         crypto
// PrimeCacheFixture                  postgres                   [creds]
// NExec                              stickyNote
// ExecuteFlows                       noOp
// NLife                              stickyNote
// BuildGet                           code
// GetDoc                             executeWorkflow            [alwaysOutput]
// Decide                             executeWorkflow            [alwaysOutput]
// IsNoAction                         if
// ActBsCollection                    executeWorkflow            [alwaysOutput]
// AssertCompleted                    if
// LifecycleOk                        noOp
// FailLifecycle                      code
// VerifyLinkBranches                 postgres                   [creds] [alwaysOutput]
// AssertLinkBranches                 code
// NCov                               stickyNote
// CoverageCases                      code
// BuildCaseSeed                      code
// SeedCase                           executeWorkflow            [alwaysOutput]
// BuildGetCase                       code
// GetCase                            executeWorkflow            [alwaysOutput]
// DecideCase                         executeWorkflow            [alwaysOutput]
// ActCase                            executeWorkflow            [alwaysOutput]
// VerifyCoverage                     postgres                   [creds] [alwaysOutput]
// AssertCoverage                     code
// CleanupCoverageDocs                postgres                   [creds]
// NFail                              stickyNote
// BuildFailSeed                      code
// SeedFail                           executeWorkflow            [alwaysOutput]
// SetFailLink                        code
// DownloadFail                       executeWorkflow            [alwaysOutput]
// CryptoFail                         crypto
// PrimeFailCache                     postgres                   [creds]
// BuildFailGet                       code
// GetFail                            executeWorkflow            [alwaysOutput]
// DecideFail                         executeWorkflow            [alwaysOutput]
// IsNoActionFail                     if
// ActFail                            executeWorkflow            [alwaysOutput]
// AssertFailStatus                   if
// FailFlowOkExtractionFailed         noOp
// FailExtractFailure                 code
// TestSummary                        code
// LaneWebhook                        webhook
// LaneVerdict                        code
// RespondLane                        respondToWebhook           [onError→regular]
// BuildTestConnectionsReq            code
// DriveConnections                   executeWorkflow            [alwaysOutput]
// FxList                             executeWorkflow            [alwaysOutput] [retry]
// FxResolve                          code
// FxLoop                             splitInBatches
// FxNeedUpload                       if
// FxDownload                         httpRequest                [retry]
// FxUpload                           executeWorkflow            [alwaysOutput] [retry]
// FxSetLink                          code
// FxPass                             code
// Config                             code
// FxList2                            executeWorkflow            [alwaysOutput] [retry]
// SeedTestFixtures                   executeWorkflow            [alwaysOutput] [retry]
// AiToggleEnable                     postgres                   [creds]
// AiToggleRestore                    postgres                   [creds]
// CleanupFinal                       postgres                   [creds]
// ClockLc                            code
// ClockFail                          code
// ClockCase                          code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// RunBsE2eTest
//    → SeedTestFixtures
//      → AiToggleEnable
//        → ConfigBase
//          → BuildTestConnectionsReq
//            → DriveConnections
//              → FxList
//                → FxResolve
//                  → FxLoop
//                    → FxList2
//                      → Config
//                        → CaptureFlagOff
//                          → CleanupPrior
//                            → BuildSeed
//                              → SeedBsDoc
//                                → BuildExistingInvoices
//                                  → SeedExistingInvoices
//                                    → SetLink
//                                      → DownloadForHash
//                                        → CryptoHash
//                                          → PrimeCacheFixture
//                                            → ExecuteFlows
//                                              → BuildGet
//                                                → GetDoc
//                                                  → ClockLc
//                                                    → Decide
//                                                      → IsNoAction
//                                                        → AssertCompleted
//                                                          → LifecycleOk
//                                                            → VerifyLinkBranches
//                                                              → AssertLinkBranches
//                                                         .out(1) → FailLifecycle
//                                                       .out(1) → ActBsCollection
//                                                          → BuildGet (↩ loop)
//                                              → CoverageCases
//                                                → BuildCaseSeed
//                                                  → SeedCase
//                                                    → BuildGetCase
//                                                      → GetCase
//                                                        → ClockCase
//                                                          → DecideCase
//                                                            → ActCase
//                                                              → VerifyCoverage
//                                                                → AssertCoverage
//                                                                  → CleanupCoverageDocs
//                                              → BuildFailSeed
//                                                → SeedFail
//                                                  → SetFailLink
//                                                    → DownloadFail
//                                                      → CryptoFail
//                                                        → PrimeFailCache
//                                                          → BuildFailGet
//                                                            → GetFail
//                                                              → ClockFail
//                                                                → DecideFail
//                                                                  → IsNoActionFail
//                                                                    → AssertFailStatus
//                                                                      → FailFlowOkExtractionFailed
//                                                                        → TestSummary
//                                                                          → CleanupFinal
//                                                                            → AiToggleRestore
//                                                                          → LaneVerdict
//                                                                            → RespondLane
//                                                                     .out(1) → FailExtractFailure
//                                                                   .out(1) → ActFail
//                                                                      → BuildFailGet (↩ loop)
//                   .out(1) → FxNeedUpload
//                      → FxDownload
//                        → FxUpload
//                          → FxSetLink
//                            → FxLoop (↩ loop)
//                     .out(1) → FxPass
//                        → FxLoop (↩ loop)
// LaneWebhook
//    → SeedTestFixtures (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Cleanup Final":{"main":[[{"node":"AI Toggle Restore","type":"main","index":0}]]},"AI Toggle Restore":{"main":[[]]},"▶ Run BS E2E Test":{"main":[[{"node":"Seed Test Fixtures","type":"main","index":0}]]},"Config":{"main":[[{"node":"Capture Flag OFF","type":"main","index":0}]]},"Capture Flag OFF":{"main":[[{"node":"Cleanup Prior","type":"main","index":0}]]},"Cleanup Prior":{"main":[[{"node":"Build Seed","type":"main","index":0}]]},"Build Seed":{"main":[[{"node":"Seed BS Doc","type":"main","index":0}]]},"Seed BS Doc":{"main":[[{"node":"Build Existing Invoices","type":"main","index":0}]]},"Build Existing Invoices":{"main":[[{"node":"Seed Existing Invoices","type":"main","index":0}]]},"Seed Existing Invoices":{"main":[[{"node":"Set LINK","type":"main","index":0}]]},"Set LINK":{"main":[[{"node":"Download for Hash","type":"main","index":0}]]},"Download for Hash":{"main":[[{"node":"Crypto Hash","type":"main","index":0}]]},"Crypto Hash":{"main":[[{"node":"Prime Cache (fixture)","type":"main","index":0}]]},"Prime Cache (fixture)":{"main":[[{"node":"Execute Flows","type":"main","index":0}]]},"Execute Flows":{"main":[[{"node":"Build GET","type":"main","index":0},{"node":"Coverage Cases","type":"main","index":0},{"node":"Build Fail Seed","type":"main","index":0}]]},"Build Fail Seed":{"main":[[{"node":"Seed Fail","type":"main","index":0}]]},"Seed Fail":{"main":[[{"node":"Set Fail LINK","type":"main","index":0}]]},"Set Fail LINK":{"main":[[{"node":"Download Fail","type":"main","index":0}]]},"Download Fail":{"main":[[{"node":"Crypto Fail","type":"main","index":0}]]},"Crypto Fail":{"main":[[{"node":"Prime Fail Cache","type":"main","index":0}]]},"Prime Fail Cache":{"main":[[{"node":"Build Fail GET","type":"main","index":0}]]},"Build Fail GET":{"main":[[{"node":"GET Fail","type":"main","index":0}]]},"GET Fail":{"main":[[{"node":"Clock Fail","type":"main","index":0}]]},"Clock Fail":{"main":[[{"node":"Decide Fail","type":"main","index":0}]]},"Decide Fail":{"main":[[{"node":"Is No-Action Fail?","type":"main","index":0}]]},"Is No-Action Fail?":{"main":[[{"node":"Assert Fail Status","type":"main","index":0}],[{"node":"Act Fail","type":"main","index":0}]]},"Act Fail":{"main":[[{"node":"Build Fail GET","type":"main","index":0}]]},"Assert Fail Status":{"main":[[{"node":"Fail Flow OK (EXTRACTION_FAILED)","type":"main","index":0}],[{"node":"FAIL extract-failure","type":"main","index":0}]]},"Build GET":{"main":[[{"node":"GET Doc","type":"main","index":0}]]},"GET Doc":{"main":[[{"node":"Clock LC","type":"main","index":0}]]},"Clock LC":{"main":[[{"node":"Decide","type":"main","index":0}]]},"Decide":{"main":[[{"node":"Is No-Action?","type":"main","index":0}]]},"Is No-Action?":{"main":[[{"node":"Assert COMPLETED","type":"main","index":0}],[{"node":"Act BS collection","type":"main","index":0}]]},"Act BS collection":{"main":[[{"node":"Build GET","type":"main","index":0}]]},"Assert COMPLETED":{"main":[[{"node":"Lifecycle OK","type":"main","index":0}],[{"node":"FAIL lifecycle","type":"main","index":0}]]},"Lifecycle OK":{"main":[[{"node":"Verify Link Branches","type":"main","index":0}]]},"Verify Link Branches":{"main":[[{"node":"Assert Link Branches","type":"main","index":0}]]},"Coverage Cases":{"main":[[{"node":"Build Case Seed","type":"main","index":0}]]},"Build Case Seed":{"main":[[{"node":"Seed Case","type":"main","index":0}]]},"Seed Case":{"main":[[{"node":"Build GET Case","type":"main","index":0}]]},"Build GET Case":{"main":[[{"node":"GET Case","type":"main","index":0}]]},"GET Case":{"main":[[{"node":"Clock Case","type":"main","index":0}]]},"Clock Case":{"main":[[{"node":"Decide Case","type":"main","index":0}]]},"Decide Case":{"main":[[{"node":"Act Case","type":"main","index":0}]]},"Act Case":{"main":[[{"node":"Verify Coverage","type":"main","index":0}]]},"Verify Coverage":{"main":[[{"node":"Assert Coverage","type":"main","index":0}]]},"Assert Coverage":{"main":[[{"node":"Cleanup Coverage Docs","type":"main","index":0}]]},"Fail Flow OK (EXTRACTION_FAILED)":{"main":[[{"node":"🏁 Test Summary","type":"main","index":0}]]},"Config Base":{"main":[[{"node":"Build Test Connections Req","type":"main","index":0}]]},"Build Test Connections Req":{"main":[[{"node":"Drive Connections","type":"main","index":0}]]},"Fx List":{"main":[[{"node":"Fx Resolve","type":"main","index":0}]]},"Fx Resolve":{"main":[[{"node":"Fx Loop","type":"main","index":0}]]},"Fx Loop":{"main":[[{"node":"Fx List 2","type":"main","index":0}],[{"node":"Fx Need Upload?","type":"main","index":0},{"node":"Fx Loop","type":"main","index":0}]]},"Fx Need Upload?":{"main":[[{"node":"Fx Download","type":"main","index":0}],[{"node":"Fx Pass","type":"main","index":0}]]},"Fx Download":{"main":[[{"node":"Fx Upload","type":"main","index":0}]]},"Fx Upload":{"main":[[{"node":"Fx Set Link","type":"main","index":0}]]},"Fx Set Link":{"main":[[]]},"Fx Pass":{"main":[[]]},"Fx List 2":{"main":[[{"node":"Config","type":"main","index":0}]]},"Seed Test Fixtures":{"main":[[{"node":"AI Toggle Enable","type":"main","index":0}]]},"AI Toggle Enable":{"main":[[{"node":"Config Base","type":"main","index":0}]]},"🏁 Test Summary":{"main":[[{"node":"Cleanup Final","type":"main","index":0},{"node":"Lane Verdict","type":"main","index":0}]]},"Drive Connections":{"main":[[{"node":"Fx List","type":"main","index":0}]]},"Lane Webhook":{"main":[[{"node":"Seed Test Fixtures","type":"main","index":0}]]},"Lane Verdict":{"main":[[{"node":"Respond Lane","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"1a1f9021-970c-46eb-8cef-4746d2dca0d0","name":"indox-state-machine-v2"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"86695706-c96c-441d-a8c4-ad2062621b72","name":"indox-v2-test"},{"updatedAt":"2026-07-30T23:41:29.646Z","createdAt":"2026-07-30T23:41:29.646Z","id":"9c337cfe-7feb-4f3d-ab26-3de6439357ce","name":"sm-refactore-v2.1"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"dcb770a3-465f-4ed5-b5d4-ca1ff6dcd994","name":"lifecycle:test"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"22f1e71e-91bf-48db-811f-8d3bc4e55a3e","name":"sm-refactor-v2.1"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"2b5cb873-dd65-44dd-bf27-a2c99d2b81a4","name":"state-machine-v2"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {"templateCredsSetupCompleted":true},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"indoxV2BSTest01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2BSTest01',
    name: 'indox-v2 BS E2E Test',
    active: false,
    isArchived: false,
    tags: [
        'indox',
        'indox-state-machine-v2',
        'indox-v2-test',
        'sm-refactore-v2.1',
        'app:indox',
        'indox-app',
        'lifecycle:test',
        'sm-refactor-v2.1',
        'state-machine-v2',
    ],
    settings: { executionOrder: 'v1', executionTimeout: 1800 },
})
export class IndoxV2BsE2eTestWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'NConfig',
        name: 'N Config',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [-60, -180],
    })
    NConfig = {
        content: `## ⚙ Config
All test data lives in the Config node.
Pretty-printed & editable: doc · cache fixture (3 lines) · pre-seeded invoices · coverage cases.`,
        height: 270,
        width: 360,
        color: 5,
    };

    @node({
        id: 'trig',
        name: '▶ Run BS E2E Test',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [0, 160],
    })
    RunBsE2eTest = {};

    @node({
        id: 'Config',
        name: 'Config Base',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [260, 160],
    })
    ConfigBase = {
        jsCode: `// All test data lives here — edit to retarget the doc, cache fixture, coverage cases, or link-branch invoices.
// [pin-is-dead 2026-08-31] This suite runs ONLY against the permanent test tenant (schema
// indox_test), and it MINTS that tenant itself (G64 R7 pins the literal): REST-run pins never
// reach a manualTrigger's item, so requiring the trigger to carry it meant undefined and a
// throw. An upstream item that names a DIFFERENT tenant is still refused loudly.
const __up = (() => { try { return $('▶ Run BS E2E Test').first().json.__instance; } catch (e) { return undefined; } })();
if (__up && __up !== 'test') throw new Error('indoxV2BSTest01 is pinned to the test tenant: upstream carries __instance=' + JSON.stringify(__up));
return [{ json: {
  "__instance": "test",
  "collectionId": "indoxV2ActionsBS01",
  "decideId": "indoxV2Decide01",
  "routerId": "indoxApiRouter01",
  "cacheTable": "ai_extraction_cache",
  "captureFlagKey": "n8n.indox.test_capture",
  "doc": {
    "ID": "bse2e_bs1",
    "TYPE": "BALANCE_SHEET",
    "COMPANY_ID": "C1",
    "COMPANY_NAME": "Acme",
    "NAME": "Acme-BSE2E",
    "LINK": "https://drive.localhost/file/d/1liZ2Zr4SNLv9iDxof6Ylrfxvr8XGBGee/view?usp=drivesdk",
    // [bs-fixture 2026-08-07] LINK points at a REAL client balance sheet, so without this
    // flag the base stage runs BaseDocEx01 and 'Select Base Values' overwrites the fixture's
    // COMPANY_ID 'C1' with the company resolved from the actual PDF (511744898). The BS
    // line-linker then searches existing invoices by the RESOLVED id, so the seeded
    // ex_upd/ex_skp (still 'C1') can never match: matchCount=0 and the CREATE branch ran for
    // every line. That is why 'SKP03 duplicated (2)' fired -- and why the UPDATE and SKIP
    // branches of this suite had never once been exercised.
    // Verified against the deployed 'Decide DOC BASE Action': without the flag the doc
    // decides extract_base_doc; with it, __route_bs__. The other three completion flags are
    // NOT needed -- figure_company_id/get_company_name/figure_document_type are already
    // guarded by the seeded COMPANY_ID/COMPANY_NAME/TYPE (each verified by removing that
    // field and watching the corresponding action fire).
    "BASE_EXTRACTION_COMPLETED": true,
    // [selection 2026-08-31] Same reason one law later: the select-first gate (2026-08-25)
    // sits ABOVE the type route, and select_base is a DOC-BASE action this suite's Act node
    // structurally cannot execute (it drives indoxV2ActionsBS01 directly; base actions live
    // in Global01). Without the flag the lifecycle loop spun decide=select_base 637 times to
    // its budget (exec 3750869). Base selection is owned and covered by doc_base/decide;
    // this suite tests the BS chain, so the seed enters PAST the gate.
    "BASE_SELECTION_COMPLETED": true
  },
  "cacheFixture": {
    "success": true,
    "data": {
      "lines": [
        {
          "id": "NEW01",
          "amount": "1000",
          "date": "2026-05-01",
          "notes": "new"
        },
        {
          "id": "UPD02",
          "amount": "2000",
          "date": "2026-05-02",
          "notes": "upd"
        },
        {
          "id": "SKP03",
          "amount": "3000",
          "date": "2026-05-03",
          "notes": "skip"
        }
      ],
      "summary": {
        "totalsMatch": true,
        "documentTotal": 6000
      },
      "documentDate": "2026-05-01"
    }
  },
  "existingInvoices": [
    {
      "ID": "ex_upd",
      "COMPANY_ID": "C1",
      "COMPANY_NAME": "Acme",
      "SHORT_DOC_ID": "UPD02",
      "DOC_ID": "UPD02",
      "TYPE": "INVOICE",
      "NAME": "Acme-UPD02",
      "STATUS": "IN_PROGRESS"
    },
    {
      "ID": "ex_skp",
      "COMPANY_ID": "C1",
      "COMPANY_NAME": "Acme",
      "SHORT_DOC_ID": "SKP03",
      "DOC_ID": "SKP03",
      "TYPE": "INVOICE",
      "NAME": "Acme-SKP03",
      "LINKED_BS": "Acme-BSE2E",
      "BS_LINE_AMOUNT": "3000",
      "BS_LINE_DATE": "2026-05-03",
      "BS_LINE_NOTE": "skip",
      "STATUS": "IN_PROGRESS"
    }
  ],
  "lifecycleExpectStatus": "COMPLETED",
  // [selection 2026-08-31] Every seed enters PAST the select-first gate (flag below):
  // these cases assert decide+handler for BS-class verdicts, and base selection is owned
  // by doc_base/decide -- an unflagged seed just decides select_base, which this suite's
  // Act node cannot execute (measured: exec 3758028, cov lane died in 10s).
  "coverageCases": [
    {
      "ID": "cov_missing_company",
      "act": "update_status_missing_company",
      "expect": "MISSING_COMPANY_ID",
      "seed": {
        "BASE_SELECTION_COMPLETED": true,
        "ID": "cov_missing_company",
        "TYPE": "BALANCE_SHEET",
        "STATUS": "IN_PROGRESS"
      }
    },
    {
      "ID": "cov_awaiting_company",
      "act": "no_action_awaiting_company_id",
      "expect": "MISSING_COMPANY_ID",
      "seed": {
        "BASE_SELECTION_COMPLETED": true,
        "ID": "cov_awaiting_company",
        "TYPE": "BALANCE_SHEET",
        "STATUS": "MISSING_COMPANY_ID"
      }
    },
    {
      "ID": "cov_restart",
      "act": "restart_balance_sheet",
      "expect": "IN_PROGRESS",
      "seed": {
        "BASE_SELECTION_COMPLETED": true,
        "ID": "cov_restart",
        "TYPE": "BALANCE_SHEET",
        "COMPANY_ID": "C1",
        "COMPANY_NAME": "Acme",
        "STATUS": "ACTION_RESTART"
      }
    },
    {
      "ID": "cov_ext_failed",
      "act": "update_status_extraction_failed",
      "expect": "EXTRACTION_FAILED",
      "seed": {
        "BASE_SELECTION_COMPLETED": true,
        "ID": "cov_ext_failed",
        "TYPE": "BALANCE_SHEET",
        "COMPANY_ID": "C1",
        "COMPANY_NAME": "Acme",
        "STATUS": "IN_PROGRESS",
        "BS_EXTRACTED_LINES": "{\\"data\\":{\\"lines\\":[{\\"id\\":\\"x\\"}]}}",
        "BS_EXTRACTION_VERIFIED": "false"
      }
    },
    {
      "ID": "cov_no_ext_failed",
      "act": "no_action_extraction_failed",
      "expect": "EXTRACTION_FAILED",
      "seed": {
        "BASE_SELECTION_COMPLETED": true,
        "ID": "cov_no_ext_failed",
        "TYPE": "BALANCE_SHEET",
        "COMPANY_ID": "C1",
        "COMPANY_NAME": "Acme",
        "STATUS": "EXTRACTION_FAILED",
        "BS_EXTRACTED_LINES": "{\\"data\\":{\\"lines\\":[{\\"id\\":\\"x\\"}]}}",
        "BS_EXTRACTION_VERIFIED": "false"
      }
    },
    {
      "ID": "cov_already_completed",
      "act": "no_action_already_completed",
      "expect": "COMPLETED",
      "seed": {
        "BASE_SELECTION_COMPLETED": true,
        "ID": "cov_already_completed",
        "TYPE": "BALANCE_SHEET",
        "COMPANY_ID": "C1",
        "COMPANY_NAME": "Acme",
        "STATUS": "COMPLETED",
        "BS_EXTRACTED_LINES": "{\\"data\\":{\\"lines\\":[{\\"id\\":\\"x\\"}]}}",
        "BS_EXTRACTION_VERIFIED": "true",
        "BS_LINK_DOCUMENTS_COMPLETED": "true"
      }
    }
  ],
  "failDoc": {
    "ID": "bse2e_fail",
    "TYPE": "BALANCE_SHEET",
    "COMPANY_ID": "C1",
    "COMPANY_NAME": "Acme",
    "NAME": "Acme-FAIL",
    "BASE_EXTRACTION_COMPLETED": true,
    "BASE_SELECTION_COMPLETED": true,
    "LINK": "https://drive.localhost/file/d/1e-0EKP8OVC3aJpkwdCHm8-3iVeoJ_r31/view"
  },
  "failCacheFixture": {
    "success": false,
    "error": "seeded extraction failure"
  },
  "failExpectStatus": "EXTRACTION_FAILED",
  "lifecycleActions": [
    "extract_balance_sheet",
    "link_documents",
    "mark_completed",
    "no_action_already_completed"
  ]
} }];`,
    };

    @node({
        id: 'NSetup',
        name: 'N Setup',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [500, -180],
    })
    NSetup = {
        content: `## 1 · Setup + Seed
flag off · cleanup · seed BS doc (no lines) · seed the 2 pre-existing invoices (for link update/skip branches).`,
        height: 270,
        width: 470,
        color: 4,
    };

    @node({
        id: 'CaptureFlagOFF',
        name: 'Capture Flag OFF',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [530, 160],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    CaptureFlagOff = {
        operation: 'delete',
        key: "={{ $('Config').first().json.captureFlagKey }}",
    };

    @node({
        id: 'CleanupPrior',
        name: 'Cleanup Prior',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [750, 160],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    CleanupPrior = {
        operation: 'executeQuery',
        query: "=DELETE FROM indox_test.incoming_documents WHERE \"LINKED_BS\"=$q${{ $('Config').first().json.doc.NAME }}$q$ OR \"SOURCE_ID\"=$q${{ $('Config').first().json.doc.ID }}$q$ OR \"ID\" IN ({{ [$('Config').first().json.doc.ID,$('Config').first().json.failDoc.ID].concat($('Config').first().json.existingInvoices.map(i=>i.ID)).map(id=>String.fromCharCode(39)+id+String.fromCharCode(39)).join(',') }})",
        options: {},
    };

    @node({
        id: 'BuildSeed',
        name: 'Build Seed',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [970, 160],
    })
    BuildSeed = {
        jsCode: "const d=$('Config').first().json.doc; return [{json:{__instance:'test', INLINE_ACTION:'UPSERT', STATUS:'IN_PROGRESS', BS_EXTRACTION_USE_CACHE:'true', ...d}}];",
    };

    @node({
        id: 'SeedBSDoc',
        name: 'Seed BS Doc',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1190, 160],
        alwaysOutputData: true,
    })
    SeedBsDoc = {
        workflowId: {
            __rl: true,
            value: "={{ $('Config').first().json.routerId }}",
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
        id: 'BuildExistingInvoices',
        name: 'Build Existing Invoices',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1410, 160],
    })
    BuildExistingInvoices = {
        jsCode: "return $('Config').first().json.existingInvoices.map(inv=>({json:{__instance:'test', INLINE_ACTION:'UPSERT', STATUS:'IN_PROGRESS', ...inv}}));",
    };

    @node({
        id: 'SeedExistingInvoices',
        name: 'Seed Existing Invoices',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1630, 160],
        alwaysOutputData: true,
    })
    SeedExistingInvoices = {
        workflowId: {
            __rl: true,
            value: "={{ $('Config').first().json.routerId }}",
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
        id: 'NPrime',
        name: 'N Prime',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [1800, -180],
    })
    NPrime = {
        content: `## 2 · Prime Cache
download → Crypto hash → UPSERT ai_extraction_cache['bs:<hash>'] = fixture (3 lines). Cache HIT, no Gemini.`,
        height: 270,
        width: 460,
        color: 6,
    };

    @node({
        id: 'SetLINK',
        name: 'Set LINK',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1830, 160],
    })
    SetLink = {
        jsCode: "return [{json:{LINK:$('Config').first().json.doc.LINK}}];",
    };

    @node({
        id: 'dl',
        name: 'Download for Hash',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2050, 160],
        alwaysOutputData: true,
    })
    DownloadForHash = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'download',
                params: '={{ ({ fileId: $json.LINK, fileIdMode: "url", profile_id: \'admin\' }) }}',
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'op',
                    displayName: 'op',
                    type: 'string',
                    display: true,
                    canBeUsedToMatch: true,
                },
                {
                    id: 'params',
                    displayName: 'params',
                    type: 'object',
                    display: true,
                    canBeUsedToMatch: true,
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'crypto',
        name: 'Crypto Hash',
        type: 'n8n-nodes-base.crypto',
        version: 1,
        position: [2270, 160],
    })
    CryptoHash = {
        binaryData: true,
        dataPropertyName: 'cached_input_key',
    };

    @node({
        id: 'PrimeCachefixture',
        name: 'Prime Cache (fixture)',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [2490, 160],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    PrimeCacheFixture = {
        operation: 'executeQuery',
        query: "=INSERT INTO {{ $('Config').first().json.cacheTable }} (cache_key, kind, value) VALUES ($q$bs:{{ $json.cached_input_key }}$q$, $q$bs$q$, $q${{ JSON.stringify($('Config').first().json.cacheFixture) }}$q$) ON CONFLICT (cache_key) DO UPDATE SET value = EXCLUDED.value; UPDATE indox_test.incoming_documents SET \"API_TOOLS_ID\" = $q${{ $json.cached_input_key }}$q$ WHERE \"ID\" LIKE $q$bse2e_%$q$ AND coalesce(\"API_TOOLS_ID\",'') = ''",
        options: {},
    };

    @node({
        id: 'NExec',
        name: 'N Exec',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [2700, -180],
    })
    NExec = {
        content: `## Execute Flows
fan out: lifecycle (§3) and coverage loop (§4) run in parallel.`,
        height: 270,
        width: 320,
        color: 7,
    };

    @node({
        id: 'ExecuteFlows',
        name: 'Execute Flows',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [2730, 160],
    })
    ExecuteFlows = {};

    @node({
        id: 'NLife',
        name: 'N Life',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [2940, -560],
    })
    NLife = {
        content: `## 3 · Lifecycle drive + link-branch check
GET → Decide → Act loop → COMPLETED. Then verify link ran create + update-existing + skip, BS doc untouched.`,
        height: 270,
        width: 520,
        color: 4,
    };

    @node({
        id: 'BuildGET',
        name: 'Build GET',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2970, -320],
    })
    BuildGet = {
        jsCode: "const s=$getWorkflowStaticData('global'); s.bsLcIter=(s.bsLcIter||0)+1; if(s.bsLcIter>40){ let last=''; try{ last=String(($('Decide').first().json||{}).ACTION||''); }catch(e){} throw new Error('BS lifecycle did not converge in 40 rounds - decide keeps answering '+JSON.stringify(last)+' which Act BS collection never resolves'); } return [{json:{__instance:'test', INLINE_ACTION:'GET', ids:$('Config').first().json.doc.ID}}];",
    };

    @node({
        id: 'GETDoc',
        name: 'GET Doc',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [3190, -320],
        alwaysOutputData: true,
    })
    GetDoc = {
        workflowId: {
            __rl: true,
            value: "={{ $('Config').first().json.routerId }}",
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
        id: 'Decide',
        name: 'Decide',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [3410, -320],
        alwaysOutputData: true,
    })
    Decide = {
        workflowId: {
            __rl: true,
            value: "={{ $('Config').first().json.decideId }}",
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
        id: 'IsNo-Action',
        name: 'Is No-Action?',
        type: 'n8n-nodes-base.if',
        version: 2,
        position: [3630, -320],
    })
    IsNoAction = {
        conditions: {
            options: {
                caseSensitive: true,
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    leftValue: '={{ $json.ACTION }}',
                    rightValue: 'no_action',
                    operator: {
                        type: 'string',
                        operation: 'startsWith',
                        singleValue: false,
                    },
                },
            ],
            combinator: 'and',
        },
    };

    @node({
        id: 'ActBScollection',
        name: 'Act BS collection',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [3630, -120],
        alwaysOutputData: true,
    })
    ActBsCollection = {
        workflowId: {
            __rl: true,
            value: "={{ $('Config').first().json.collectionId }}",
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
        id: 'AssertCOMPLETED',
        name: 'Assert COMPLETED',
        type: 'n8n-nodes-base.if',
        version: 2,
        position: [3850, -420],
    })
    AssertCompleted = {
        conditions: {
            options: {
                caseSensitive: true,
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    leftValue: '={{ $json.STATUS }}',
                    rightValue: "={{ $('Config').first().json.lifecycleExpectStatus }}",
                    operator: {
                        type: 'string',
                        operation: 'equals',
                        singleValue: false,
                    },
                },
            ],
            combinator: 'and',
        },
    };

    @node({
        id: 'LifecycleOK',
        name: 'Lifecycle OK',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [4070, -520],
    })
    LifecycleOk = {};

    @node({
        id: 'FAILlifecycle',
        name: 'FAIL lifecycle',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [4070, -320],
    })
    FailLifecycle = {
        jsCode: "throw new Error('Lifecycle did not reach '+$('Config').first().json.lifecycleExpectStatus+', got '+$json.STATUS);",
    };

    @node({
        id: 'VerifyLinkBranches',
        name: 'Verify Link Branches',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [4290, -520],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    VerifyLinkBranches = {
        operation: 'executeQuery',
        query: '=SELECT "ID","TYPE","DOC_ID","SHORT_DOC_ID","LINKED_BS","BS_LINE_AMOUNT","COMPANY_ID","COMPANY_NAME" FROM indox_test.incoming_documents WHERE "ID"=$q${{ $(\'Config\').first().json.doc.ID }}$q$ OR "SOURCE_ID"=$q${{ $(\'Config\').first().json.doc.ID }}$q$ OR "ID" IN ($q$ex_upd$q$,$q$ex_skp$q$)',
        options: {},
    };

    @node({
        id: 'AssertLinkBranches',
        name: 'Assert Link Branches',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [4510, -520],
    })
    AssertLinkBranches = {
        jsCode: `const bsName=$('Config').first().json.doc.NAME;
const rows=$input.all().map(i=>i.json);
const byId=Object.fromEntries(rows.map(r=>[r.ID,r]));
const invByDoc={}; rows.forEach(r=>{ if(r.TYPE==='INVOICE'){ (invByDoc[r.DOC_ID]=invByDoc[r.DOC_ID]||[]).push(r); } });
const f=[];
const bs=byId[$('Config').first().json.doc.ID];
if(!bs||bs.TYPE!=='BALANCE_SHEET') f.push('BS doc missing/wrong type');
if(bs&&bs.LINKED_BS) f.push('BS doc wrongly got LINKED_BS='+bs.LINKED_BS);
const nw=invByDoc['NEW01']||[];
if(nw.length!==1||nw[0].LINKED_BS!==bsName) f.push('CREATE: NEW01 not opened as 1 linked invoice ('+nw.length+')');
const up=byId['ex_upd'];
if(!up||up.LINKED_BS!==bsName||String(up.BS_LINE_AMOUNT)!=='2000') f.push('UPDATE: ex_upd not linked/updated');
if((invByDoc['UPD02']||[]).length!==1) f.push('UPDATE: UPD02 duplicated instead of updating existing ('+(invByDoc['UPD02']||[]).length+')');
const sk=byId['ex_skp'];
if(!sk||sk.LINKED_BS!==bsName) f.push('SKIP: ex_skp lost its link');
if((invByDoc['SKP03']||[]).length!==1) f.push('SKIP: SKP03 duplicated ('+(invByDoc['SKP03']||[]).length+')');
// [company-name-at-birth 2026-08-24] The CREATE branch used to open the row with COMPANY_ID but
// no COMPANY_NAME, so a BS-born line showed a company in its NAME and an empty company column
// until a later get_company_name pass filled it in. The name is in scope at INSERT; assert it.
const bsCid=$('Config').first().json.doc.COMPANY_ID;
const bsCname=$('Config').first().json.doc.COMPANY_NAME;
if(nw.length===1&&nw[0].COMPANY_NAME!==bsCname) f.push('CREATE: NEW01 born without COMPANY_NAME (got '+JSON.stringify(nw[0].COMPANY_NAME)+', want '+JSON.stringify(bsCname)+')');
if(nw.length===1&&String(nw[0].COMPANY_ID)!==String(bsCid)) f.push('CREATE: NEW01 born with wrong COMPANY_ID (got '+JSON.stringify(nw[0].COMPANY_ID)+', want '+JSON.stringify(bsCid)+')');
if(f.length) throw new Error('LINK BRANCH FAIL: '+f.join('; '));
return [{json:{result:'✅ LINK BRANCHES PASS', create:'NEW01 opened as '+nw[0].COMPANY_NAME+' / '+nw[0].COMPANY_ID, update:'ex_upd linked ('+up.BS_LINE_AMOUNT+')', skip:'ex_skp kept', bs_untouched:!bs.LINKED_BS}}];`,
    };

    @node({
        id: 'NCov',
        name: 'N Cov',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [2940, 320],
    })
    NCov = {
        content: `## 4 · Coverage loop
seed each remaining BS action's precondition → Decide → Act; batch-verify STATUS → 100% handler coverage.`,
        height: 270,
        width: 520,
        color: 3,
    };

    @node({
        id: 'CoverageCases',
        name: 'Coverage Cases',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2970, 560],
    })
    CoverageCases = {
        jsCode: "return $('Config').first().json.coverageCases.map(c=>({json:c}));",
    };

    @node({
        id: 'BuildCaseSeed',
        name: 'Build Case Seed',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3410, 760],
    })
    BuildCaseSeed = {
        jsCode: "return $input.all().map(i=>({json:{__instance:'test', INLINE_ACTION:'UPSERT', ...i.json.seed}}));",
    };

    @node({
        id: 'SeedCase',
        name: 'Seed Case',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [3630, 760],
        alwaysOutputData: true,
    })
    SeedCase = {
        workflowId: {
            __rl: true,
            value: "={{ $('Config').first().json.routerId }}",
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
        id: 'BuildGETCase',
        name: 'Build GET Case',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3850, 760],
    })
    BuildGetCase = {
        jsCode: "return [{json:{__instance:'test', INLINE_ACTION:'GET', ids:$('Config').first().json.coverageCases.map(c=>c.ID).join(',')}}];",
    };

    @node({
        id: 'GETCase',
        name: 'GET Case',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [4070, 760],
        alwaysOutputData: true,
    })
    GetCase = {
        workflowId: {
            __rl: true,
            value: "={{ $('Config').first().json.routerId }}",
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
        id: 'DecideCase',
        name: 'Decide Case',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [4290, 760],
        alwaysOutputData: true,
    })
    DecideCase = {
        workflowId: {
            __rl: true,
            value: "={{ $('Config').first().json.decideId }}",
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
        id: 'ActCase',
        name: 'Act Case',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [4510, 760],
        alwaysOutputData: true,
    })
    ActCase = {
        workflowId: {
            __rl: true,
            value: "={{ $('Config').first().json.collectionId }}",
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
        id: 'VerifyCoverage',
        name: 'Verify Coverage',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [3410, 440],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    VerifyCoverage = {
        operation: 'executeQuery',
        query: '=SELECT "ID","STATUS" FROM indox_test.incoming_documents WHERE "ID" IN ({{ $(\'Config\').first().json.coverageCases.map(c => String.fromCharCode(39)+c.ID+String.fromCharCode(39)).join(\',\') }}) ORDER BY "ID"',
        options: {},
    };

    @node({
        id: 'AssertCoverage',
        name: 'Assert Coverage',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3630, 440],
    })
    AssertCoverage = {
        jsCode: `const cfg=$('Config').first().json;
const want=Object.fromEntries(cfg.coverageCases.map(c=>[c.ID,c.expect]));
const rows=Object.fromEntries($input.all().map(i=>[i.json.ID,i.json.STATUS]));
const fails=[];
for(const [id,st] of Object.entries(want)){ if(rows[id]!==st) fails.push(id+': expected '+st+' got '+(rows[id]||'MISSING')); }
if(fails.length) throw new Error('BS coverage FAIL: '+fails.join('; '));
const covered=cfg.lifecycleActions.concat(cfg.coverageCases.map(c=>c.act));
return [{json:{result:'✅ 100% BS COVERAGE PASS', handlers_covered:covered, count:covered.length, note:'action_old_date is a dead switch output (brain never emits it)'}}];`,
    };

    @node({
        id: 'CleanupCoverageDocs',
        name: 'Cleanup Coverage Docs',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [3850, 440],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    CleanupCoverageDocs = {
        operation: 'executeQuery',
        query: "=DELETE FROM indox_test.incoming_documents WHERE \"ID\" IN ({{ $('Config').first().json.coverageCases.map(c => String.fromCharCode(39)+c.ID+String.fromCharCode(39)).join(',') }})",
        options: {},
    };

    @node({
        id: 'NFail',
        name: 'N Fail',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [2940, 1120],
    })
    NFail = {
        content: `## 3b · Extract-FAILURE
prime {success:false} for a 2nd file → extractor fails → hits the extract-fail writer + EXTRACTION_FAILED.`,
        height: 240,
        width: 520,
        color: 4,
    };

    @node({
        id: 'BuildFailSeed',
        name: 'Build Fail Seed',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2970, 1360],
    })
    BuildFailSeed = {
        jsCode: "const d=$('Config').first().json.failDoc; return [{json:{__instance:'test', INLINE_ACTION:'UPSERT', STATUS:'IN_PROGRESS', BS_EXTRACTION_USE_CACHE:'true', ...d}}];",
    };

    @node({
        id: 'SeedFail',
        name: 'Seed Fail',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [3190, 1360],
        alwaysOutputData: true,
    })
    SeedFail = {
        workflowId: {
            __rl: true,
            value: "={{ $('Config').first().json.routerId }}",
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
        id: 'SetFailLINK',
        name: 'Set Fail LINK',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3410, 1360],
    })
    SetFailLink = {
        jsCode: "return [{json:{LINK:$('Config').first().json.failDoc.LINK}}];",
    };

    @node({
        id: 'dlf',
        name: 'Download Fail',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [3630, 1360],
        alwaysOutputData: true,
    })
    DownloadFail = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'download',
                params: '={{ ({ fileId: $json.LINK, fileIdMode: "url", profile_id: \'admin\' }) }}',
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'op',
                    displayName: 'op',
                    type: 'string',
                    display: true,
                    canBeUsedToMatch: true,
                },
                {
                    id: 'params',
                    displayName: 'params',
                    type: 'object',
                    display: true,
                    canBeUsedToMatch: true,
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'cryptof',
        name: 'Crypto Fail',
        type: 'n8n-nodes-base.crypto',
        version: 1,
        position: [3850, 1360],
    })
    CryptoFail = {
        binaryData: true,
        dataPropertyName: 'cached_input_key',
    };

    @node({
        id: 'PrimeFailCache',
        name: 'Prime Fail Cache',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [4070, 1360],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    PrimeFailCache = {
        operation: 'executeQuery',
        query: "=INSERT INTO {{ $('Config').first().json.cacheTable }} (cache_key, kind, value) VALUES ($q$bs:{{ $json.cached_input_key }}$q$, $q$bs$q$, $q${{ JSON.stringify($('Config').first().json.failCacheFixture) }}$q$) ON CONFLICT (cache_key) DO UPDATE SET value = EXCLUDED.value; UPDATE indox_test.incoming_documents SET \"API_TOOLS_ID\" = $q${{ $json.cached_input_key }}$q$ WHERE \"ID\" LIKE $q$bse2e_%$q$ AND coalesce(\"API_TOOLS_ID\",'') = ''",
        options: {},
    };

    @node({
        id: 'BuildFailGET',
        name: 'Build Fail GET',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [4290, 1360],
    })
    BuildFailGet = {
        jsCode: "return [{json:{__instance:'test', INLINE_ACTION:'GET', ids:$('Config').first().json.failDoc.ID}}];",
    };

    @node({
        id: 'GETFail',
        name: 'GET Fail',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [4510, 1360],
        alwaysOutputData: true,
    })
    GetFail = {
        workflowId: {
            __rl: true,
            value: "={{ $('Config').first().json.routerId }}",
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
        id: 'DecideFail',
        name: 'Decide Fail',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [4730, 1360],
        alwaysOutputData: true,
    })
    DecideFail = {
        workflowId: {
            __rl: true,
            value: "={{ $('Config').first().json.decideId }}",
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
        id: 'IsNo-ActionFail',
        name: 'Is No-Action Fail?',
        type: 'n8n-nodes-base.if',
        version: 2,
        position: [4950, 1360],
    })
    IsNoActionFail = {
        conditions: {
            options: {
                caseSensitive: true,
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    leftValue: '={{ $json.ACTION }}',
                    rightValue: 'no_action',
                    operator: {
                        type: 'string',
                        operation: 'startsWith',
                        singleValue: false,
                    },
                },
            ],
            combinator: 'and',
        },
    };

    @node({
        id: 'ActFail',
        name: 'Act Fail',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [4950, 1560],
        alwaysOutputData: true,
    })
    ActFail = {
        workflowId: {
            __rl: true,
            value: "={{ $('Config').first().json.collectionId }}",
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
        id: 'AssertFailStatus',
        name: 'Assert Fail Status',
        type: 'n8n-nodes-base.if',
        version: 2,
        position: [5170, 1260],
    })
    AssertFailStatus = {
        conditions: {
            options: {
                caseSensitive: true,
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    leftValue: '={{ $json.STATUS }}',
                    rightValue: "={{ $('Config').first().json.failExpectStatus }}",
                    operator: {
                        type: 'string',
                        operation: 'equals',
                        singleValue: false,
                    },
                },
            ],
            combinator: 'and',
        },
    };

    @node({
        id: 'FailFlowOKEXTRACTION_FAI',
        name: 'Fail Flow OK (EXTRACTION_FAILED)',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [5390, 1160],
    })
    FailFlowOkExtractionFailed = {};

    @node({
        id: 'FAILextract-failure',
        name: 'FAIL extract-failure',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [5390, 1360],
    })
    FailExtractFailure = {
        jsCode: "throw new Error('extract-failure flow did not reach '+$('Config').first().json.failExpectStatus+', got '+$json.STATUS);",
    };

    @node({
        id: 'bse2esummary01',
        name: '🏁 Test Summary',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [5630, 1160],
    })
    TestSummary = {
        jsCode: `// End-of-run scorecard — reads all 4 phase asserts and prints ONE consolidated verdict.
// Runs only on the all-green path (an earlier assert that throws stops the run → execution goes red,
// and you'll see which Assert node threw). This node is the "everything passed" summary.
const g = (node, path) => { try { const j = $(node).first().json; return path.split('.').reduce((o,k)=>o&&o[k], j); } catch (e) { return undefined; } };
const lifecycle  = g("Assert COMPLETED", "STATUS");
const link       = g("Assert Link Branches", "result");
const coverage   = g("Assert Coverage", "result");
const covCount   = g("Assert Coverage", "count");
const failStatus = g("Assert Fail Status", "STATUS");
const checks = [
  { phase: "1· Lifecycle → COMPLETED",                 ok: lifecycle === "COMPLETED",           detail: "STATUS=" + lifecycle },
  { phase: "2· Link branches (create/update/skip)",    ok: /PASS/.test(String(link)),           detail: String(link) },
  { phase: "3· Handler coverage",                      ok: /PASS/.test(String(coverage)),       detail: String(coverage) + " (" + covCount + " handlers)" },
  { phase: "4· Failure path → EXTRACTION_FAILED",      ok: failStatus === "EXTRACTION_FAILED",  detail: "STATUS=" + failStatus },
];
const allOk = checks.every(c => c.ok);
return [{ json: {
  RESULT: allOk ? "✅ ALL TESTS PASS" : "❌ FAILURES PRESENT",
  passed: checks.filter(c => c.ok).length + "/" + checks.length,
  checks: checks.map(c => (c.ok ? "✅ " : "❌ ") + c.phase + " — " + c.detail),
} }];`,
    };

    @node({
        id: 'bse-lane-webhook',
        webhookId: 'bs-e2e-lane',
        name: 'Lane Webhook',
        /*__n8n__*/ notes: "[ui-lane 2026-08-31] The console's בדיקות tab runs suites through webhook lanes (BFF _run_one_lane POSTs {lane} and reads back items whose `result` contains PASS). One lane ('all'): the same graph the CLI runs, entered here instead of the manual trigger. The body carries no tenant — Config Base mints 'test' (pin-is-dead).",
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [-680, 300],
    })
    LaneWebhook = {
        httpMethod: 'POST',
        path: 'bs-e2e-lane',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'bse-lane-verdict',
        name: 'Lane Verdict',
        /*__n8n__*/ notes: "[ui-lane 2026-08-31] Shim between the harness contract (🏁 emits RESULT/passed/checks) and the webhook contract (lowercase `result` containing PASS).",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [5850, 1300],
    })
    LaneVerdict = {
        jsCode: "const j=$json; return [{json:{result:String(j.RESULT||'')+' ('+String(j.passed||'')+')', checks:j.checks||[]}}];",
    };

    @node({
        id: 'bse-lane-respond',
        name: 'Respond Lane',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [6070, 1300],
        onError: 'continueRegularOutput',
    })
    RespondLane = {
        respondWith: 'allIncomingItems',
        options: {},
    };

    @node({
        id: 'bse-cxreq',
        name: 'Build Test Connections Req',
        /*__n8n__*/ notes: "[phase-4 2026-08-31] Emits the ONE payload 'Drive Connections' sends to indoxApi01. Needed because indoxApi01's trigger is passthrough (no declared inputs), so the executeWorkflow node forwards its input items verbatim - without this shim it would forward Config Base's whole object, which carries no INLINE_ACTION and would be UPSERTed as a document.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-200, 300],
    })
    BuildTestConnectionsReq = {
        jsCode: "return [{json:{INLINE_ACTION:'TABLE_GET', table:'settings', __instance:'test', instance:'*', filter:{key:'test_connections'}}}];",
    };

    @node({
        id: 'bse-cx',
        name: 'Drive Connections',
        /*__n8n__*/ notes: "[2026-08-22] Placed between 'Config Base' and 'Fx List' on purpose: 'Config' reads $input.all() to build its uploaded-file map, so this could NOT go on the edge feeding it without replacing that input. 'Fx List' takes static params, so it is indifferent to what arrives here, and $('Drive Connections') is a named reference every later node can use. [phase-4 2026-08-31] Retargeted from driveApi01 op:connections to indoxApi01 TABLE_GET on the test tenant's settings row test_connections - suites make zero discovery calls. Node name kept: 'Config' references $('Drive Connections') and now parses JSON.parse(row.value).drive_connection_id.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [-40, 300],
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
        id: '4e77e7d6-0ae0-42b7-88f4-7047642cce78',
        name: 'Fx List',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [420, 0],
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 10000,
    })
    FxList = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'list',
                params: "={{ ({ limit: 100, profile_id: 'admin' }) }}",
            },
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'd0db5d46-5373-4fb2-82b6-76f1673282b7',
        name: 'Fx Resolve',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [580, 0],
    })
    FxResolve = {
        jsCode: 'const files=[{"key": "docLink", "upname": "fxbs-main-lvyrvn-3.pdf", "path": "balance_sheet/files/lvyrvn-3.pdf"}, {"key": "failLink", "upname": "fxbs-fail-lvyrvn-5.pdf", "path": "balance_sheet/files/lvyrvn-5.pdf"}];const byName={}; $input.all().map(i=>i.json).filter(f=>f&&f.name).forEach(f=>{byName[f.name]=f.webViewLink;});return files.map(f=>({json:{...f, LINK:byName[f.upname]||null, _missing:!byName[f.upname]}}));',
    };

    @node({
        id: '2ad26eab-11f3-47f4-9248-ed902f102d19',
        name: 'Fx Loop',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [740, 0],
    })
    FxLoop = {
        batchSize: 1,
        options: {},
    };

    @node({
        id: 'ed336678-7224-4ba0-8a1a-3705d037a140',
        name: 'Fx Need Upload?',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [900, -144],
    })
    FxNeedUpload = {
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
        id: '4cff6922-9bf3-407c-bb44-6f9e3a45817a',
        name: 'Fx Download',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [1060, 180],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 10000,
    })
    FxDownload = {
        url: "={{ 'http://indox-demo-docs:8088/' + $('Fx Loop').item.json.path }}",
        options: {
            response: {
                response: {
                    responseFormat: 'file',
                },
            },
        },
    };

    @node({
        id: '90d573ad-ec82-45f8-b559-cc12c95f26bd',
        name: 'Fx Upload',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1220, 180],
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 10000,
    })
    FxUpload = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'upload',
                params: "={{ ({ name: $('Fx Loop').item.json.upname, profile_id: 'admin' }) }}",
            },
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'f63dff03-719f-432b-ac51-4ae5ea1fa722',
        name: 'Fx Set Link',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1380, 180],
    })
    FxSetLink = {
        jsCode: "return [{json:{...$('Fx Loop').item.json, LINK:$input.first().json.webViewLink, _missing:false}}];",
    };

    @node({
        id: '3846d860-8637-4873-8a0a-8b6552545a75',
        name: 'Fx Pass',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1060, 0],
    })
    FxPass = {
        jsCode: 'return $input.all();',
    };

    @node({
        id: 'a9d115c6-15fc-4937-8c74-ac98aeea1d64',
        name: 'Config',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [900, -140],
    })
    Config = {
        jsCode: 'const base=$(\'Config Base\').first().json;const files=[{"key": "docLink", "upname": "fxbs-main-lvyrvn-3.pdf", "path": "balance_sheet/files/lvyrvn-3.pdf"}, {"key": "failLink", "upname": "fxbs-fail-lvyrvn-5.pdf", "path": "balance_sheet/files/lvyrvn-5.pdf"}];const byName={}; $input.all().map(i=>i.json).filter(x=>x&&x.name).forEach(x=>{byName[x.name]=x.webViewLink;});const links={}; files.forEach(x=>links[x.key]=byName[x.upname]||null);if(!links.docLink||!links.failLink) throw new Error(\'fixture link resolution failed: \'+JSON.stringify(links));const __row=$(\'Drive Connections\').all().map(i=>i.json).find(r=>r&&r.value); let __cx=null; try { __cx=(JSON.parse(__row.value)||{}).drive_connection_id||null; } catch(e) {} if(!__cx) throw new Error(\'no drive connection - settings row test_connections missing or unparseable (indoxApi01 TABLE_GET on indox_test)\'); return [{json:{...base, doc:{...base.doc, LINK:links.docLink, LINK_CONNECTION:__cx}, failDoc:{...base.failDoc, LINK:links.failLink, LINK_CONNECTION:__cx}}}];',
    };

    @node({
        id: '2e2ab21f-f112-433b-805f-a8b4e6fc3fbb',
        name: 'Fx List 2',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [820, -140],
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 10000,
    })
    FxList2 = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'list',
                params: "={{ ({ limit: 100, profile_id: 'admin' }) }}",
            },
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: '4a89eeae-bcb2-4086-9db7-9f41a448ab5c',
        name: 'Seed Test Fixtures',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [90, 40],
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

    @node({
        id: 'bstAiToggleEnable',
        name: 'AI Toggle Enable',
        /*__n8n__*/ notes: "[2026-08-23] SELF-HEALS ON ENTRY, because a restore that only runs on the success path is not a restore. This node used to open by saving prior=current -- so when a previous run failed, errored, or hit its timeout budget and never reached 'AI Toggle Restore', the leaked true was read back as the PRIOR and written in permanently. That is not hypothetical: plt_prior_extraction_ai_enabled was found sitting at 'true' after pipeline timed out at 1080s, and the shipped fixture default is FALSE (with extraction_local_enabled=true). It matters because GEMINI_API_KEY and GOOGLE_VISION_API_KEY are placeholders on the portable box and the standing rule is that no test may require them -- a leaked global flag turns that rule into a property of the last run's exit status. The two statements ahead of the save undo any leftover first, so a crashed run is repaired by the next run instead of inherited by it.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-320, 1200],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    AiToggleEnable = {
        operation: 'executeQuery',
        query: "UPDATE indox_test.settings s SET value=p.value FROM indox_test.settings p WHERE p.instance='incoming-documents-main' AND p.key='bst_prior_extraction_ai_enabled' AND s.instance='incoming-documents-main' AND s.key='extraction_ai_enabled'; DELETE FROM indox_test.settings WHERE instance='incoming-documents-main' AND key='bst_prior_extraction_ai_enabled'; INSERT INTO indox_test.settings(instance,key,value) SELECT 'incoming-documents-main','bst_prior_extraction_ai_enabled', COALESCE((SELECT value FROM indox_test.settings WHERE instance='incoming-documents-main' AND key='extraction_ai_enabled'),'false') ON CONFLICT (instance,key) DO UPDATE SET value=EXCLUDED.value; INSERT INTO indox_test.settings(instance,key,value) VALUES('incoming-documents-main','extraction_ai_enabled','true') ON CONFLICT (instance,key) DO UPDATE SET value='true';",
        options: {},
    };

    @node({
        id: 'bstAiToggleRestore',
        name: 'AI Toggle Restore',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [5200, 1200],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    AiToggleRestore = {
        operation: 'executeQuery',
        query: "UPDATE indox_test.settings s SET value=p.value FROM indox_test.settings p WHERE p.instance='incoming-documents-main' AND p.key='bst_prior_extraction_ai_enabled' AND s.instance='incoming-documents-main' AND s.key='extraction_ai_enabled'; DELETE FROM indox_test.settings WHERE instance='incoming-documents-main' AND key='bst_prior_extraction_ai_enabled';",
        options: {},
    };

    @node({
        id: 'CleanupFinal',
        name: 'Cleanup Final',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [5870, 1160],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    CleanupFinal = {
        operation: 'executeQuery',
        query: "=DELETE FROM indox_test.incoming_documents WHERE \"LINKED_BS\"=$q${{ $('Config').first().json.doc.NAME }}$q$ OR \"SOURCE_ID\"=$q${{ $('Config').first().json.doc.ID }}$q$ OR \"ID\" IN ({{ [$('Config').first().json.doc.ID,$('Config').first().json.failDoc.ID].concat($('Config').first().json.existingInvoices.map(i=>i.ID)).map(id=>String.fromCharCode(39)+id+String.fromCharCode(39)).join(',') }})",
        options: {},
    };

    @node({
        id: 'bse-clock-lc',
        name: 'Clock LC',
        /*__n8n__*/ notes: "[test-clock 2026-08-31] This suite's decide calls go straight to the mega (indoxV2Decide01) with NO driver enrich, so the tenant's OldDocumentMonthsBack=240 is unreachable and the fn's fallback-6 aged the REAL fixture PDF (LOCAL_DOC_DATE 10/09/2025) into update_status_old_doc -- a Global01 action this suite's Act node cannot execute, so the lifecycle spun to the 40-round ceiling (exec 3757543). Same channel doc_base's LC lane uses: _cfg on the item, first preference of __CFG().",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [700, 900],
    })
    ClockLc = {
        jsCode: 'return $input.all().map(i=>({json:{...i.json, _cfg:{old_document_months_back:240}}}));',
    };

    @node({
        id: 'bse-clock-fail',
        name: 'Clock Fail',
        /*__n8n__*/ notes: "[test-clock 2026-08-31] This suite's decide calls go straight to the mega (indoxV2Decide01) with NO driver enrich, so the tenant's OldDocumentMonthsBack=240 is unreachable and the fn's fallback-6 aged the REAL fixture PDF (LOCAL_DOC_DATE 10/09/2025) into update_status_old_doc -- a Global01 action this suite's Act node cannot execute, so the lifecycle spun to the 40-round ceiling (exec 3757543). Same channel doc_base's LC lane uses: _cfg on the item, first preference of __CFG().",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [900, 1500],
    })
    ClockFail = {
        jsCode: 'return $input.all().map(i=>({json:{...i.json, _cfg:{old_document_months_back:240}}}));',
    };

    @node({
        id: 'bse-clock-case',
        name: 'Clock Case',
        /*__n8n__*/ notes: "[test-clock 2026-08-31] This suite's decide calls go straight to the mega (indoxV2Decide01) with NO driver enrich, so the tenant's OldDocumentMonthsBack=240 is unreachable and the fn's fallback-6 aged the REAL fixture PDF (LOCAL_DOC_DATE 10/09/2025) into update_status_old_doc -- a Global01 action this suite's Act node cannot execute, so the lifecycle spun to the 40-round ceiling (exec 3757543). Same channel doc_base's LC lane uses: _cfg on the item, first preference of __CFG().",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1100, 1800],
    })
    ClockCase = {
        jsCode: 'return $input.all().map(i=>({json:{...i.json, _cfg:{old_document_months_back:240}}}));',
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.CleanupFinal.out(0).to(this.AiToggleRestore.in(0));
        this.RunBsE2eTest.out(0).to(this.SeedTestFixtures.in(0));
        this.Config.out(0).to(this.CaptureFlagOff.in(0));
        this.CaptureFlagOff.out(0).to(this.CleanupPrior.in(0));
        this.CleanupPrior.out(0).to(this.BuildSeed.in(0));
        this.BuildSeed.out(0).to(this.SeedBsDoc.in(0));
        this.SeedBsDoc.out(0).to(this.BuildExistingInvoices.in(0));
        this.BuildExistingInvoices.out(0).to(this.SeedExistingInvoices.in(0));
        this.SeedExistingInvoices.out(0).to(this.SetLink.in(0));
        this.SetLink.out(0).to(this.DownloadForHash.in(0));
        this.DownloadForHash.out(0).to(this.CryptoHash.in(0));
        this.CryptoHash.out(0).to(this.PrimeCacheFixture.in(0));
        this.PrimeCacheFixture.out(0).to(this.ExecuteFlows.in(0));
        this.ExecuteFlows.out(0).to(this.BuildGet.in(0));
        this.ExecuteFlows.out(0).to(this.CoverageCases.in(0));
        this.ExecuteFlows.out(0).to(this.BuildFailSeed.in(0));
        this.BuildFailSeed.out(0).to(this.SeedFail.in(0));
        this.SeedFail.out(0).to(this.SetFailLink.in(0));
        this.SetFailLink.out(0).to(this.DownloadFail.in(0));
        this.DownloadFail.out(0).to(this.CryptoFail.in(0));
        this.CryptoFail.out(0).to(this.PrimeFailCache.in(0));
        this.PrimeFailCache.out(0).to(this.BuildFailGet.in(0));
        this.BuildFailGet.out(0).to(this.GetFail.in(0));
        this.GetFail.out(0).to(this.ClockFail.in(0));
        this.ClockFail.out(0).to(this.DecideFail.in(0));
        this.DecideFail.out(0).to(this.IsNoActionFail.in(0));
        this.IsNoActionFail.out(0).to(this.AssertFailStatus.in(0));
        this.IsNoActionFail.out(1).to(this.ActFail.in(0));
        this.ActFail.out(0).to(this.BuildFailGet.in(0));
        this.AssertFailStatus.out(0).to(this.FailFlowOkExtractionFailed.in(0));
        this.AssertFailStatus.out(1).to(this.FailExtractFailure.in(0));
        this.BuildGet.out(0).to(this.GetDoc.in(0));
        this.GetDoc.out(0).to(this.ClockLc.in(0));
        this.ClockLc.out(0).to(this.Decide.in(0));
        this.Decide.out(0).to(this.IsNoAction.in(0));
        this.IsNoAction.out(0).to(this.AssertCompleted.in(0));
        this.IsNoAction.out(1).to(this.ActBsCollection.in(0));
        this.ActBsCollection.out(0).to(this.BuildGet.in(0));
        this.AssertCompleted.out(0).to(this.LifecycleOk.in(0));
        this.AssertCompleted.out(1).to(this.FailLifecycle.in(0));
        this.LifecycleOk.out(0).to(this.VerifyLinkBranches.in(0));
        this.VerifyLinkBranches.out(0).to(this.AssertLinkBranches.in(0));
        this.CoverageCases.out(0).to(this.BuildCaseSeed.in(0));
        this.BuildCaseSeed.out(0).to(this.SeedCase.in(0));
        this.SeedCase.out(0).to(this.BuildGetCase.in(0));
        this.BuildGetCase.out(0).to(this.GetCase.in(0));
        this.GetCase.out(0).to(this.ClockCase.in(0));
        this.ClockCase.out(0).to(this.DecideCase.in(0));
        this.DecideCase.out(0).to(this.ActCase.in(0));
        this.ActCase.out(0).to(this.VerifyCoverage.in(0));
        this.VerifyCoverage.out(0).to(this.AssertCoverage.in(0));
        this.AssertCoverage.out(0).to(this.CleanupCoverageDocs.in(0));
        this.FailFlowOkExtractionFailed.out(0).to(this.TestSummary.in(0));
        this.ConfigBase.out(0).to(this.BuildTestConnectionsReq.in(0));
        this.BuildTestConnectionsReq.out(0).to(this.DriveConnections.in(0));
        this.FxList.out(0).to(this.FxResolve.in(0));
        this.FxResolve.out(0).to(this.FxLoop.in(0));
        this.FxLoop.out(0).to(this.FxList2.in(0));
        this.FxLoop.out(1).to(this.FxNeedUpload.in(0));
        this.FxNeedUpload.out(0).to(this.FxDownload.in(0));
        this.FxNeedUpload.out(1).to(this.FxPass.in(0));
        this.FxDownload.out(0).to(this.FxUpload.in(0));
        this.FxUpload.out(0).to(this.FxSetLink.in(0));
        this.FxSetLink.out(0).to(this.FxLoop.in(0));
        this.FxPass.out(0).to(this.FxLoop.in(0));
        this.FxList2.out(0).to(this.Config.in(0));
        this.SeedTestFixtures.out(0).to(this.AiToggleEnable.in(0));
        this.AiToggleEnable.out(0).to(this.ConfigBase.in(0));
        this.TestSummary.out(0).to(this.CleanupFinal.in(0));
        this.TestSummary.out(0).to(this.LaneVerdict.in(0));
        this.DriveConnections.out(0).to(this.FxList.in(0));
        this.LaneWebhook.out(0).to(this.SeedTestFixtures.in(0));
        this.LaneVerdict.out(0).to(this.RespondLane.in(0));
    }
}
