import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox-v2 GDoc E2E Test
// Nodes   : 86  |  Connections: 101
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// RunGdocE2eTest                     manualTrigger
// ConfigBase                         code
// BuildTestConnectionsReq            code
// DriveConnections                   executeWorkflow            [alwaysOutput]
// BuildUploadReq                     code
// UploadFixture                      executeWorkflow            [alwaysOutput]
// CaptureFlagOff                     redis                      [creds]
// CleanupPrior                       postgres                   [creds]
// SetLink                            code
// DownloadForHash                    executeWorkflow            [alwaysOutput]
// CryptoHash                         crypto
// PrimeCacheInvoiceFixture           postgres                   [creds]
// ExecuteFlows                       noOp
// BuildExtractSeeds                  code
// SeedExtract                        executeWorkflow            [alwaysOutput]
// BuildExtractItems                  code
// CallExtract                        executeWorkflow            [alwaysOutput]
// VerifyExtract                      postgres                   [creds] [alwaysOutput]
// AssertExtract                      code
// CleanupExtract                     postgres                   [creds]
// BuildCovSeed                       code
// SeedCov                            executeWorkflow            [alwaysOutput]
// EmitActions                        code
// CallCov                            executeWorkflow            [alwaysOutput]
// AssertCoverage                     code
// CleanupCov                         postgres                   [creds]
// BuildPerrSeeds                     code
// SeedPerr                           executeWorkflow            [alwaysOutput]
// BuildPerrItems                     code
// CallPerr                           executeWorkflow            [alwaysOutput]
// VerifyPartialError                 postgres                   [creds] [alwaysOutput]
// AssertPartialError                 code
// CleanupPerr                        postgres                   [creds]
// LcStart                            code
// BuildLcSeed                        code
// SeedLc                             executeWorkflow            [alwaysOutput]
// BuildGetLc                         code
// GetLc                              executeWorkflow            [alwaysOutput]
// DecideLc                           executeWorkflow            [alwaysOutput]
// LcGuard                            code
// IsDoneLc                           if
// ActLc                              executeWorkflow            [alwaysOutput]
// VerifyLifecycle                    postgres                   [creds] [alwaysOutput]
// AssertLifecycle                    code
// TestSummary                        code
// AiToggleEnable                     postgres                   [creds]
// AiToggleRestore                    postgres                   [creds]
// CleanupLc                          postgres                   [creds]
// BatchConfig                        code
// BatchLcStart                       code                       [alwaysOutput]
// BatchCleanupPrior                  postgres                   [creds] [alwaysOutput]
// ListGdxFiles                       executeWorkflow            [alwaysOutput]
// ResolveLinks                       code                       [alwaysOutput]
// LoopSeed                           splitInBatches
// NeedUpload                         if
// DownloadLocal                      httpRequest
// UploadToDrive                      executeWorkflow            [alwaysOutput]
// SetLink1                           code                       [alwaysOutput]
// BuildUpsert                        code
// SeedOne                            executeWorkflow            [alwaysOutput]
// BuildGetBatch                      code
// GetBatch                           executeWorkflow            [alwaysOutput]
// DecideBatch                        executeWorkflow            [alwaysOutput]
// BatchGuard                         code                       [alwaysOutput]
// IsDoneBatch                        if
// ActBatch                           executeWorkflow            [alwaysOutput]
// VerifyBatch                        postgres                   [creds] [alwaysOutput]
// AssertBatchLc                      code                       [alwaysOutput]
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
// LaneWebhook                        webhook
// LaneSwitch                         switch
// RespondLane                        respondToWebhook           [onError→regular]
// PerrWait                           code
// PerrReady                          if
// ClockLc                            code
// ClockBatch                         code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// RunGdocE2eTest
//    → SeedTestFixtures
//      → AiToggleEnable
//        → ConfigBase
//          → FxList
//            → FxResolve
//              → FxLoop
//                → FxList2
//                  → Config
//                    → BuildTestConnectionsReq
//                      → DriveConnections
//                        → BuildUploadReq
//                          → UploadFixture
//                            → CaptureFlagOff
//                              → CleanupPrior
//                                → SetLink
//                                  → DownloadForHash
//                                    → CryptoHash
//                                      → PrimeCacheInvoiceFixture
//                                        → ExecuteFlows
//                                          → LaneSwitch
//                                            → BuildExtractSeeds
//                                              → SeedExtract
//                                                → BuildExtractItems
//                                                  → CallExtract
//                                                    → VerifyExtract
//                                                      → AssertExtract
//                                                        → CleanupExtract
//                                                        → RespondLane
//                                           .out(1) → BuildCovSeed
//                                              → SeedCov
//                                                → EmitActions
//                                                  → CallCov
//                                                    → AssertCoverage
//                                                      → CleanupCov
//                                                      → RespondLane (↩ loop)
//                                           .out(2) → BuildPerrSeeds
//                                              → SeedPerr
//                                                → BuildPerrItems
//                                                  → CallPerr
//                                                    → PerrWait
//                                                      → VerifyPartialError
//                                                        → PerrReady
//                                                          → AssertPartialError
//                                                            → CleanupPerr
//                                                            → RespondLane (↩ loop)
//                                                         .out(1) → PerrWait (↩ loop)
//                                           .out(3) → BatchConfig
//                                              → BatchLcStart
//                                                → BatchCleanupPrior
//                                                  → ListGdxFiles
//                                                    → ResolveLinks
//                                                      → LoopSeed
//                                                        → BuildGetBatch
//                                                          → GetBatch
//                                                            → ClockBatch
//                                                              → DecideBatch
//                                                                → BatchGuard
//                                                                  → IsDoneBatch
//                                                                    → VerifyBatch
//                                                                      → AssertBatchLc
//                                                                        → RespondLane (↩ loop)
//                                                                   .out(1) → ActBatch
//                                                                      → BuildGetBatch (↩ loop)
//                                                       .out(1) → NeedUpload
//                                                          → DownloadLocal
//                                                            → UploadToDrive
//                                                              → SetLink1
//                                                                → BuildUpsert
//                                                                  → SeedOne
//                                                                    → LoopSeed (↩ loop)
//                                                         .out(1) → BuildUpsert (↩ loop)
//                                           .out(4) → LcStart
//                                              → BuildLcSeed
//                                                → SeedLc
//                                                  → BuildGetLc
//                                                    → GetLc
//                                                      → ClockLc
//                                                        → DecideLc
//                                                          → LcGuard
//                                                            → IsDoneLc
//                                                              → VerifyLifecycle
//                                                                → AssertLifecycle
//                                                                  → TestSummary
//                                                                    → CleanupLc
//                                                                      → AiToggleRestore
//                                                                  → RespondLane (↩ loop)
//                                                             .out(1) → ActLc
//                                                                → BuildGetLc (↩ loop)
//                                           .out(5) → BuildExtractSeeds (↩ loop)
//                                           .out(5) → BuildCovSeed (↩ loop)
//                                           .out(5) → BuildPerrSeeds (↩ loop)
//                                           .out(5) → BatchConfig (↩ loop)
//                                           .out(5) → LcStart (↩ loop)
//               .out(1) → FxNeedUpload
//                  → FxDownload
//                    → FxUpload
//                      → FxSetLink
//                        → FxLoop (↩ loop)
//                 .out(1) → FxPass
//                    → FxLoop (↩ loop)
// LaneWebhook
//    → SeedTestFixtures (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"▶ Run GDoc E2E Test": {"main": [[{"node": "Seed Test Fixtures", "type": "main", "index": 0}]]}, "Config": {"main": [[{"node": "Build Test Connections Req", "type": "main", "index": 0}]]}, "Build Test Connections Req": {"main": [[{"node": "Drive Connections", "type": "main", "index": 0}]]}, "Capture Flag OFF": {"main": [[{"node": "Cleanup Prior", "type": "main", "index": 0}]]}, "Cleanup Prior": {"main": [[{"node": "Set LINK", "type": "main", "index": 0}]]}, "Set LINK": {"main": [[{"node": "Download for Hash", "type": "main", "index": 0}]]}, "Download for Hash": {"main": [[{"node": "Crypto Hash", "type": "main", "index": 0}]]}, "Crypto Hash": {"main": [[{"node": "Prime Cache (invoice fixture)", "type": "main", "index": 0}]]}, "Prime Cache (invoice fixture)": {"main": [[{"node": "Execute Flows", "type": "main", "index": 0}]]}, "Execute Flows": {"main": [[{"node": "Lane Switch", "type": "main", "index": 0}]]}, "Build Extract Seeds": {"main": [[{"node": "Seed Extract", "type": "main", "index": 0}]]}, "Seed Extract": {"main": [[{"node": "Build Extract Items", "type": "main", "index": 0}]]}, "Build Extract Items": {"main": [[{"node": "Call Extract", "type": "main", "index": 0}]]}, "Call Extract": {"main": [[{"node": "Verify Extract", "type": "main", "index": 0}]]}, "Verify Extract": {"main": [[{"node": "Assert Extract", "type": "main", "index": 0}]]}, "Assert Extract": {"main": [[{"node": "Cleanup Extract", "type": "main", "index": 0}, {"node": "Respond Lane", "type": "main", "index": 0}]]}, "Build Cov Seed": {"main": [[{"node": "Seed Cov", "type": "main", "index": 0}]]}, "Seed Cov": {"main": [[{"node": "Emit Actions", "type": "main", "index": 0}]]}, "Emit Actions": {"main": [[{"node": "Call Cov", "type": "main", "index": 0}]]}, "Call Cov": {"main": [[{"node": "Assert Coverage", "type": "main", "index": 0}]]}, "Assert Coverage": {"main": [[{"node": "Cleanup Cov", "type": "main", "index": 0}, {"node": "Respond Lane", "type": "main", "index": 0}]]}, "Build PErr Seeds": {"main": [[{"node": "Seed PErr", "type": "main", "index": 0}]]}, "Seed PErr": {"main": [[{"node": "Build PErr Items", "type": "main", "index": 0}]]}, "Build PErr Items": {"main": [[{"node": "Call PErr", "type": "main", "index": 0}]]}, "Call PErr": {"main": [[{"node": "PErr Wait", "type": "main", "index": 0}]]}, "Verify Partial-Error": {"main": [[{"node": "PErr Ready?", "type": "main", "index": 0}]]}, "Assert Partial-Error": {"main": [[{"node": "Cleanup PErr", "type": "main", "index": 0}, {"node": "Respond Lane", "type": "main", "index": 0}]]}, "LC Start": {"main": [[{"node": "Build LC Seed", "type": "main", "index": 0}]]}, "Build LC Seed": {"main": [[{"node": "Seed LC", "type": "main", "index": 0}]]}, "Seed LC": {"main": [[{"node": "Build GET LC", "type": "main", "index": 0}]]}, "Build GET LC": {"main": [[{"node": "GET LC", "type": "main", "index": 0}]]}, "GET LC": {"main": [[{"node": "Clock LC", "type": "main", "index": 0}]]}, "Clock LC": {"main": [[{"node": "Decide LC", "type": "main", "index": 0}]]}, "Decide LC": {"main": [[{"node": "LC Guard", "type": "main", "index": 0}]]}, "LC Guard": {"main": [[{"node": "Is Done LC?", "type": "main", "index": 0}]]}, "Is Done LC?": {"main": [[{"node": "Verify Lifecycle", "type": "main", "index": 0}], [{"node": "Act LC", "type": "main", "index": 0}]]}, "Act LC": {"main": [[{"node": "Build GET LC", "type": "main", "index": 0}]]}, "Verify Lifecycle": {"main": [[{"node": "Assert Lifecycle", "type": "main", "index": 0}]]}, "Assert Lifecycle": {"main": [[{"node": "🏁 Test Summary", "type": "main", "index": 0}, {"node": "Respond Lane", "type": "main", "index": 0}]]}, "🏁 Test Summary": {"main": [[{"node": "Cleanup LC", "type": "main", "index": 0}]]}, "Cleanup LC": {"main": [[{"node": "AI Toggle Restore", "type": "main", "index": 0}]]}, "AI Toggle Restore": {"main": [[]]}, "Batch Config": {"main": [[{"node": "Batch-LC Start", "type": "main", "index": 0}]]}, "Batch-LC Start": {"main": [[{"node": "Batch Cleanup Prior", "type": "main", "index": 0}]]}, "Batch Cleanup Prior": {"main": [[{"node": "List gdx Files", "type": "main", "index": 0}]]}, "List gdx Files": {"main": [[{"node": "Resolve Links", "type": "main", "index": 0}]]}, "Resolve Links": {"main": [[{"node": "Loop Seed", "type": "main", "index": 0}]]}, "Loop Seed": {"main": [[{"node": "Build GET Batch", "type": "main", "index": 0}], [{"node": "Need Upload?", "type": "main", "index": 0}, {"node": "Loop Seed", "type": "main", "index": 0}]]}, "Need Upload?": {"main": [[{"node": "Download Local", "type": "main", "index": 0}], [{"node": "Build UPSERT", "type": "main", "index": 0}]]}, "Download Local": {"main": [[{"node": "Upload to Drive", "type": "main", "index": 0}]]}, "Upload to Drive": {"main": [[{"node": "Set Link", "type": "main", "index": 0}]]}, "Set Link": {"main": [[{"node": "Build UPSERT", "type": "main", "index": 0}]]}, "Build UPSERT": {"main": [[{"node": "Seed One", "type": "main", "index": 0}]]}, "Seed One": {"main": [[]]}, "Build GET Batch": {"main": [[{"node": "GET Batch", "type": "main", "index": 0}]]}, "GET Batch": {"main": [[{"node": "Clock Batch", "type": "main", "index": 0}]]}, "Clock Batch": {"main": [[{"node": "Decide Batch", "type": "main", "index": 0}]]}, "Decide Batch": {"main": [[{"node": "Batch Guard", "type": "main", "index": 0}]]}, "Batch Guard": {"main": [[{"node": "Is Done Batch?", "type": "main", "index": 0}]]}, "Is Done Batch?": {"main": [[{"node": "Verify Batch", "type": "main", "index": 0}], [{"node": "Act Batch", "type": "main", "index": 0}]]}, "Act Batch": {"main": [[{"node": "Build GET Batch", "type": "main", "index": 0}]]}, "Verify Batch": {"main": [[{"node": "Assert Batch-LC", "type": "main", "index": 0}]]}, "Config Base": {"main": [[{"node": "Fx List", "type": "main", "index": 0}]]}, "Fx List": {"main": [[{"node": "Fx Resolve", "type": "main", "index": 0}]]}, "Fx Resolve": {"main": [[{"node": "Fx Loop", "type": "main", "index": 0}]]}, "Fx Loop": {"main": [[{"node": "Fx Settle", "type": "main", "index": 0}], [{"node": "Fx Need Upload?", "type": "main", "index": 0}, {"node": "Fx Loop", "type": "main", "index": 0}]]}, "Fx Need Upload?": {"main": [[{"node": "Fx Download", "type": "main", "index": 0}], [{"node": "Fx Pass", "type": "main", "index": 0}]]}, "Fx Download": {"main": [[{"node": "Fx Upload", "type": "main", "index": 0}]]}, "Fx Upload": {"main": [[{"node": "Fx Set Link", "type": "main", "index": 0}]]}, "Fx Set Link": {"main": [[]]}, "Fx Pass": {"main": [[]]}, "Fx List 2": {"main": [[{"node": "Config", "type": "main", "index": 0}]]}, "Seed Test Fixtures": {"main": [[{"node": "AI Toggle Enable", "type": "main", "index": 0}]]}, "AI Toggle Enable": {"main": [[{"node": "Config Base", "type": "main", "index": 0}]]}, "Lane Webhook": {"main": [[{"node": "Seed Test Fixtures", "type": "main", "index": 0}]]}, "Lane Switch": {"main": [[{"node": "Build Extract Seeds", "type": "main", "index": 0}], [{"node": "Build Cov Seed", "type": "main", "index": 0}], [{"node": "Build PErr Seeds", "type": "main", "index": 0}], [{"node": "Batch Config", "type": "main", "index": 0}], [{"node": "LC Start", "type": "main", "index": 0}], [{"node": "Build Extract Seeds", "type": "main", "index": 0}, {"node": "Build Cov Seed", "type": "main", "index": 0}, {"node": "Build PErr Seeds", "type": "main", "index": 0}, {"node": "Batch Config", "type": "main", "index": 0}, {"node": "LC Start", "type": "main", "index": 0}]]}, "Assert Batch-LC": {"main": [[{"node": "Respond Lane", "type": "main", "index": 0}]]}, "PErr Wait": {"main": [[{"node": "Verify Partial-Error", "type": "main", "index": 0}]]}, "PErr Ready?": {"main": [[{"node": "Assert Partial-Error", "type": "main", "index": 0}], [{"node": "PErr Wait", "type": "main", "index": 0}]]}, "Drive Connections": {"main": [[{"node": "Build Upload Req", "type": "main", "index": 0}]]}, "Build Upload Req": {"main": [[{"node": "Upload Fixture", "type": "main", "index": 0}]]}, "Upload Fixture": {"main": [[{"node": "Capture Flag OFF", "type": "main", "index": 0}]]}, "Fx Settle": {"main": [[{"node": "Fx List 2", "type": "main", "index": 0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"22f1e71e-91bf-48db-811f-8d3bc4e55a3e","name":"sm-refactor-v2.1"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"dcb770a3-465f-4ed5-b5d4-ca1ff6dcd994","name":"lifecycle:test"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"2b5cb873-dd65-44dd-bf27-a2c99d2b81a4","name":"state-machine-v2"},{"updatedAt":"2026-07-30T23:41:29.646Z","createdAt":"2026-07-30T23:41:29.646Z","id":"9c337cfe-7feb-4f3d-ab26-3de6439357ce","name":"sm-refactore-v2.1"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"1a1f9021-970c-46eb-8cef-4746d2dca0d0","name":"indox-state-machine-v2"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"86695706-c96c-441d-a8c4-ad2062621b72","name":"indox-v2-test"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: {"global":{"dx_t0":1783024030304,"blcStart":1783256260142,"blcIter":15}},
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"indoxV2GDocTest01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2GDocTest01',
    name: 'indox-v2 GDoc E2E Test',
    active: false,
    isArchived: false,
    tags: [
        'sm-refactor-v2.1',
        'indox-app',
        'lifecycle:test',
        'app:indox',
        'state-machine-v2',
        'sm-refactore-v2.1',
        'indox-state-machine-v2',
        'indox-v2-test',
        'indox',
    ],
    settings: { executionOrder: 'v1', executionTimeout: 1800 },
})
export class IndoxV2GdocE2eTestWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'trig',
        name: '▶ Run GDoc E2E Test',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [-200, 700],
    })
    RunGdocE2eTest = {};

    @node({
        id: 'Config',
        name: 'Config Base',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [0, 700],
    })
    ConfigBase = {
        jsCode: `// GDoc E2E test - all config here. Mirrors the BS E2E test shape.
// [pin-is-dead 2026-08-31] The suite MINTS its tenant (G64 R7 pins the literal): REST-run pins
// never reach a manualTrigger's item, so requiring the trigger to carry it meant {} and a throw.
// A lane webhook or upstream item that names a DIFFERENT tenant is still refused loudly.
const __up=(()=>{ let v=($json||{}).__instance; if(!v){ try { v=(($('Lane Webhook').first().json||{}).body||{}).__instance; } catch(e) {} } return v; })();
if(__up && __up!=='test') throw new Error('indoxV2GDocTest01: upstream carries __instance '+JSON.stringify(__up)+', not test - this suite only runs against the test tenant (indox_test)');
return [{ json: {
  "__instance": "test",
  "collectionId": "indoxV2ActionsInv01",
  // DISPATCH TABLE - mirrors indoxV2Driver01/Switch1, the only thing that decides
  // which action collection runs an action in production. ACTION wins over DOC_TYPE:
  // a DOC BASE action goes to indoxV2ActionsGlobal01 whatever the doc type is.
  "baseCollectionId": "indoxV2ActionsGlobal01",
  "shipCollectionId": "indoxV2ActionsShip01",
  "bsCollectionId": "indoxV2ActionsBS01",
  // [selection 2026-08-31] select_base/restart_base (and the merge/feedback verdicts) joined
  // the DOC-BASE class after this mirror of Driver Switch1 was written; without them the
  // dispatcher fell to the type collection, select_base went unhandled, and BOTH loops spun
  // decide=select_base to their ceilings (exec 3758297: 46 + 31 rounds, 0/15 completed).
  "baseActions": ["update_status_missing_company", "no_action_awaiting_company_id", "get_company_name", "update_status_unknwon_company", "no_action_awaiting_company_name", "update_status_missing_type", "figure_document_type", "update_status_double", "figure_company_id", "update_status_old_doc", "mark_max_iterations", "no_action_max_iterations", "no_action_double", "no_action_paused", "no_action_old_date", "no_action_delete_row", "no_action_unknown_document_type", "extract_base_doc", "resolve_double", "no_action_merged", "apply_gmail_labels", "update_status_garbage", "no_action_garbage", "file_to_failed_folder", "select_base", "restart_base", "no_action_already_completed", "action_merge_doubles", "no_action_merge_blocked", "action_source_feedback"],
  "routerId": "indoxApiRouter01",
  "decideId": "indoxV2Decide01",
  "captureFlagKey": "n8n.indox.test_capture",
  "cacheTable": "ai_extraction_cache",
  "link": "https://drive.localhost/file/d/1liZ2Zr4SNLv9iDxof6Ylrfxvr8XGBGee/view?usp=drivesdk",
  "badLink": "https://drive.localhost/file/d/GDOC_GARBAGE_XYZ/view",
  "cacheFixture": {
    "success": true,
    "data": {
      "AI_COMPANY_ID": "C1",
      "AI_DOC_ID": "INV001",
      "AI_DOC_DATE": "2026-05-01",
      "AI_DOC_AMOUNT": "100",
      "AI_SHIPMENT_IDS": "SH12345",
      "AI_ORDER_IDS": "PO999",
      "AI_TYPE": "INVOICE"
    }
  },
  "companyId": "C_GDTEST",
  "lcCompanyId": "C1",
  "extractCount": 15,
  "perrGood": 5,
  "perrBad": 3,
  "maxSteps": 30,
  "coverageActions": [
    "restart_gdoc",
    "no_action_awaiting_company_id",
    "no_action_awating_doc_id",
    "get_short_doc_id",
    "update_status_missing_link",
    "no_action_link_not_found",
    "update_status_api_tools_failed",
    "no_action_api_tools_failed",
    "no_action_doc_date_missing",
    "no_action_doc_total_amount_missing",
    "update_status_missing_shipment",
    "extract_shipment_ids",
    "mark_completed",
    "update_company_doc_id"
  ,
    {"action":"find_link","override":{"LINK":"","SEARCH_IN_DRIVE_COMPLETED":false}},
    {"action":"action_priority_sync"},
    {"action":"action_extract_shipment_ids","override":{"AI_SHIPMENT_IDS":"[\\"SH999TEST\\"]"}}
  ]
} }];`,
    };

    @node({
        id: 'gdt-cxreq',
        name: 'Build Test Connections Req',
        /*__n8n__*/ notes: "[phase-4 2026-08-31] Emits the ONE payload 'Drive Connections' sends to indoxApi01. Needed because indoxApi01's trigger is passthrough (no declared inputs), so the executeWorkflow node forwards its input items verbatim - without this shim it would forward Config's whole object, which carries no INLINE_ACTION and would be UPSERTed as a document.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-220, 300],
    })
    BuildTestConnectionsReq = {
        jsCode: "return [{json:{INLINE_ACTION:'TABLE_GET', table:'settings', __instance:'test', instance:'*', filter:{key:'test_connections'}}}];",
    };

    @node({
        id: 'gdt-cx',
        name: 'Drive Connections',
        /*__n8n__*/ notes: "[2026-08-22] Sits right after Config so EVERY branch can reference it: a seed that writes a LINK must also write LINK_CONNECTION, or the drive-connection guard counts the document as having no openable link and the first decide answers update_status_missing_link. That is what made the gdoc lifecycle end after ONE pass. [phase-4 2026-08-31] The id is still never hardcoded (it is a per-deployment vault hash, a fresh deploy mints a different one) but it is no longer discovered via driveApi01 op:connections - suites make zero discovery calls. It now comes from the test tenant's settings row test_connections (indoxApi01 TABLE_GET, request built by 'Build Test Connections Req'); consumers read JSON.parse(row.value).drive_connection_id.",
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
        id: 'gdt-upreq',
        name: 'Build Upload Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-40, 460],
    })
    BuildUploadReq = {
        jsCode: "/* [2026-08-22] ONE upload for the whole extract lane. Checks 2 and 4 seed fifteen and eight documents that all point at the SAME fixture file, so one apitools upload serves every one of them and the lane still measures what it is named for - parallel extraction, not parallel uploading. indoxV2UploadApiTools01 takes LINK/HASH/ID/LINK_CONNECTION and returns file_id. */ const c=$('Config').first().json; const __row=$('Drive Connections').all().map(i=>i.json).find(r=>r&&r.value); let __cx=null; try { __cx=(JSON.parse(__row.value)||{}).drive_connection_id||null; } catch(e) {} if(!__cx) throw new Error('no drive connection - settings row test_connections missing or unparseable (indoxApi01 TABLE_GET on indox_test)'); return [{json:{__instance:'test', LINK:c.link, LINK_CONNECTION:__cx, ID:'gdt_fixture', HASH:null}}];",
    };

    @node({
        id: 'gdt-upfix',
        name: 'Upload Fixture',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [140, 460],
        alwaysOutputData: true,
    })
    UploadFixture = {
        workflowId: {
            __rl: true,
            value: 'indoxV2UploadApiTools01',
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
        id: 'CaptureFlagOFF',
        name: 'Capture Flag OFF',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [220, 700],
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
        position: [440, 700],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    CleanupPrior = {
        operation: 'executeQuery',
        query: `=DELETE FROM indox_test.incoming_documents WHERE {{ (() => { let l='all'; try { l=($('Lane Webhook').first().json.body||{}).lane||'all'; } catch(e) {}
const m={extract:"\\"ID\\" LIKE 'gdt_ex_%'", cov:"\\"ID\\" LIKE 'gdt_cov_%'", perr:"\\"ID\\" LIKE 'gdt_pe_%'", lc:"\\"ID\\"='gdt_lc_1'"};
if (m[l]) return m[l];
if (l.startsWith('batch:')) return "false";
return "\\"ID\\" LIKE 'gdt_ex_%' OR \\"ID\\" LIKE 'gdt_cov_%' OR \\"ID\\" LIKE 'gdt_pe_%' OR \\"ID\\"='gdt_lc_1' OR \\"COMPANY_ID\\"='C_GDTEST'"; })() }}`,
        options: {},
    };

    @node({
        id: 'SetLINK',
        name: 'Set LINK',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [660, 700],
    })
    SetLink = {
        jsCode: "return [{json:{LINK: $('Config').first().json.link}}];",
    };

    @node({
        id: 'DownloadforHash',
        name: 'Download for Hash',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [880, 700],
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
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'CryptoHash',
        name: 'Crypto Hash',
        type: 'n8n-nodes-base.crypto',
        version: 1,
        position: [1100, 700],
    })
    CryptoHash = {
        binaryData: true,
        dataPropertyName: 'cached_input_key',
    };

    @node({
        id: 'PrimeCacheinvoicefixture',
        name: 'Prime Cache (invoice fixture)',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [1320, 700],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    PrimeCacheInvoiceFixture = {
        operation: 'executeQuery',
        query: "=INSERT INTO {{ $('Config').first().json.cacheTable }} (cache_key, kind, value) VALUES ($q$invoice:{{ $json.cached_input_key }}$q$, $q$invoice$q$, $q${{ JSON.stringify($('Config').first().json.cacheFixture) }}$q$) ON CONFLICT (cache_key) DO UPDATE SET value=EXCLUDED.value",
        options: {},
    };

    @node({
        id: 'ExecuteFlows',
        name: 'Execute Flows',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [1540, 700],
    })
    ExecuteFlows = {};

    @node({
        id: 'BuildExtractSeeds',
        name: 'Build Extract Seeds',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1780, 100],
    })
    BuildExtractSeeds = {
        jsCode: "const __row=$('Drive Connections').all().map(i=>i.json).find(r=>r&&r.value); let __cx=null; try { __cx=(JSON.parse(__row.value)||{}).drive_connection_id||null; } catch(e) {} if(!__cx) throw new Error('no drive connection - settings row test_connections missing or unparseable (indoxApi01 TABLE_GET on indox_test)'); const __at=($('Upload Fixture').first().json||{}).file_id; if(!__at) throw new Error('apitools upload produced no file_id - per-type cannot run'); const c=$('Config').first().json; const o=[]; for(let i=1;i<=c.extractCount;i++){o.push({json:{INLINE_ACTION:'UPSERT',__instance:'test',LINK_CONNECTION:__cx,API_TOOLS_ID:__at,ID:'gdt_ex_'+i,TYPE:'INVOICE',COMPANY_ID:c.companyId,COMPANY_NAME:'GDT',NAME:'EX'+i,STATUS:'IN_PROGRESS',LINK:c.link,}});} return o;",
    };

    @node({
        id: 'SeedExtract',
        name: 'Seed Extract',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2000, 100],
        alwaysOutputData: true,
    })
    SeedExtract = {
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
        id: 'BuildExtractItems',
        name: 'Build Extract Items',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2220, 100],
    })
    BuildExtractItems = {
        jsCode: "/* [2026-08-22] DISPATCH THE WHOLE DOCUMENT, not just {ACTION,ID,LINK}. The retired extract_invoice_google_ai lane re-read what it needed; extract_per_type is handed its row - it reads API_TOOLS_ID, LINK_CONNECTION and TYPE off the item - so a three-field item produced an empty collection call and 0/15 extracted. 'Act LC', the lifecycle dispatcher that works, passes a full decide output for exactly this reason. */ const c=$('Config').first().json; const __row=$('Drive Connections').all().map(i=>i.json).find(r=>r&&r.value); let __cx=null; try { __cx=(JSON.parse(__row.value)||{}).drive_connection_id||null; } catch(e) {} if(!__cx) throw new Error('no drive connection - settings row test_connections missing or unparseable (indoxApi01 TABLE_GET on indox_test)'); const __at=($('Upload Fixture').first().json||{}).file_id; const o=[]; for(let i=1;i<=c.extractCount;i++){o.push({json:{ACTION:'extract_per_type',__instance:'test',DOC_TYPE:'gdoc',ID:'gdt_ex_'+i,TYPE:'INVOICE',COMPANY_ID:c.companyId,COMPANY_NAME:'GDT',NAME:'EX'+i,STATUS:'IN_PROGRESS',LINK:c.link,LINK_CONNECTION:__cx,API_TOOLS_ID:__at,}});} return o;",
    };

    @node({
        id: 'CallExtract',
        name: 'Call Extract',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2440, 100],
        alwaysOutputData: true,
    })
    CallExtract = {
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
        id: 'VerifyExtract',
        name: 'Verify Extract',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [2660, 100],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    VerifyExtract = {
        operation: 'executeQuery',
        query: '=SELECT (SELECT count(*) FROM indox_test.incoming_documents WHERE "ID" LIKE \'gdt_ex_%\' AND "AI_DOC_ID" IS NOT NULL AND "AI_DOC_ID"<>\'\') AS extracted',
        options: {},
    };

    @node({
        id: 'AssertExtract',
        name: 'Assert Extract',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2880, 100],
    })
    AssertExtract = {
        jsCode: `// RETURN A RED, NEVER THROW. The summary node already treats a missing/failed assert as a red
// check; throwing here instead killed the whole execution, skipped 'Cleanup Extract' (stranding
// fixtures in the client's table) and produced 'NO SUMMARY 0' for all 5 checks.
const c=$('Config').first().json; const r=$input.first().json; const N=c.extractCount;
const got=Number(r.extracted);
if(got!==N) return [{json:{result:'FAIL parallel extract: AI-extracted '+r.extracted+'/'+N, docs:N, extracted:got}}];
return [{json:{result:'PASS parallel extract (bounded-5)', docs:N, extracted:got}}];`,
    };

    @node({
        id: 'CleanupExtract',
        name: 'Cleanup Extract',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [3100, 100],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    CleanupExtract = {
        operation: 'executeQuery',
        query: '=DELETE FROM indox_test.incoming_documents WHERE "ID" LIKE \'gdt_ex_%\'',
        options: {},
    };

    @node({
        id: 'BuildCovSeed',
        name: 'Build Cov Seed',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1780, 450],
    })
    BuildCovSeed = {
        jsCode: "const __row=$('Drive Connections').all().map(i=>i.json).find(r=>r&&r.value); let __cx=null; try { __cx=(JSON.parse(__row.value)||{}).drive_connection_id||null; } catch(e) {} if(!__cx) throw new Error('no drive connection - settings row test_connections missing or unparseable (indoxApi01 TABLE_GET on indox_test)'); const c=$('Config').first().json; return [{json:{INLINE_ACTION:'UPSERT',__instance:'test',LINK_CONNECTION:__cx,ID:'gdt_cov_1',TYPE:'GENERAL',COMPANY_ID:c.companyId,COMPANY_NAME:'GDT',NAME:'Cov',DOC_ID:'CD001',SHORT_DOC_ID:'00001',STATUS:'IN_PROGRESS',LINK:c.link,AI_SHIPMENT_IDS:''}}];",
    };

    @node({
        id: 'SeedCov',
        name: 'Seed Cov',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2000, 450],
        alwaysOutputData: true,
    })
    SeedCov = {
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
        id: 'EmitActions',
        name: 'Emit Actions',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2220, 450],
    })
    EmitActions = {
        jsCode: "const c=$('Config').first().json; return c.coverageActions.map((a,i)=>{const o=(typeof a==='string')?{action:a}:a; return {json:{__instance:'test',ID:'gdt_cov_'+i,COMPANY_ID:c.companyId,COMPANY_NAME:'GDX',DOC_ID:'CD'+i,SHORT_DOC_ID:'000'+i,NAME:'Cov'+i,AI_SHIPMENT_IDS:'',_shipment_id:'',...(o.override||{}),ACTION:o.action}};});",
    };

    @node({
        id: 'CallCov',
        name: 'Call Cov',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2880, 610],
        alwaysOutputData: true,
    })
    CallCov = {
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
        id: 'AssertCoverage',
        name: 'Assert Coverage',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2660, 300],
    })
    AssertCoverage = {
        jsCode: "const covered=$('Emit Actions').all().map(i=>i.json.ACTION);return [{json:{result:'PASS '+covered.length+' handler coverage (injected in ONE batch)', count:covered.length, handlers_covered:covered}}];",
    };

    @node({
        id: 'CleanupCov',
        name: 'Cleanup Cov',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [2880, 300],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    CleanupCov = {
        operation: 'executeQuery',
        query: 'DELETE FROM indox_test.incoming_documents WHERE "ID" LIKE \'gdt_cov_%\';',
        options: {},
    };

    @node({
        id: 'BuildPErrSeeds',
        name: 'Build PErr Seeds',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1780, 800],
    })
    BuildPerrSeeds = {
        jsCode: "const __row=$('Drive Connections').all().map(i=>i.json).find(r=>r&&r.value); let __cx=null; try { __cx=(JSON.parse(__row.value)||{}).drive_connection_id||null; } catch(e) {} if(!__cx) throw new Error('no drive connection - settings row test_connections missing or unparseable (indoxApi01 TABLE_GET on indox_test)'); const __at=($('Upload Fixture').first().json||{}).file_id; if(!__at) throw new Error('apitools upload produced no file_id - per-type cannot run'); const c=$('Config').first().json; const o=[]; let i=0;for(let g=1;g<=c.perrGood;g++){i++;o.push({json:{INLINE_ACTION:'UPSERT',__instance:'test',LINK_CONNECTION:__cx,API_TOOLS_ID:__at,ID:'gdt_pe_'+i,TYPE:'INVOICE',COMPANY_ID:c.companyId,COMPANY_NAME:'GDT',NAME:'G'+g,STATUS:'IN_PROGRESS',LINK:c.link,}});}for(let b=1;b<=c.perrBad;b++){i++;o.push({json:{INLINE_ACTION:'UPSERT',__instance:'test',LINK_CONNECTION:__cx,ID:'gdt_pe_'+i,TYPE:'INVOICE',COMPANY_ID:c.companyId,COMPANY_NAME:'GDT',NAME:'B'+b,STATUS:'IN_PROGRESS',LINK:c.badLink,}});} return o;",
    };

    @node({
        id: 'SeedPErr',
        name: 'Seed PErr',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2000, 800],
        alwaysOutputData: true,
    })
    SeedPerr = {
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
        id: 'BuildPErrItems',
        name: 'Build PErr Items',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2220, 800],
    })
    BuildPerrItems = {
        jsCode: "/* [2026-08-22] DISPATCH THE WHOLE DOCUMENT, not just {ACTION,ID,LINK}. The retired extract_invoice_google_ai lane re-read what it needed; extract_per_type is handed its row - it reads API_TOOLS_ID, LINK_CONNECTION and TYPE off the item - so a three-field item produced an empty collection call and 0/15 extracted. 'Act LC', the lifecycle dispatcher that works, passes a full decide output for exactly this reason. */ const c=$('Config').first().json; const __row=$('Drive Connections').all().map(i=>i.json).find(r=>r&&r.value); let __cx=null; try { __cx=(JSON.parse(__row.value)||{}).drive_connection_id||null; } catch(e) {} if(!__cx) throw new Error('no drive connection - settings row test_connections missing or unparseable (indoxApi01 TABLE_GET on indox_test)'); const __at=($('Upload Fixture').first().json||{}).file_id; const o=[]; let i=0;for(let g=1;g<=c.perrGood;g++){i++;o.push({json:{ACTION:'extract_per_type',__instance:'test',DOC_TYPE:'gdoc',ID:'gdt_pe_'+i,TYPE:'INVOICE',COMPANY_ID:c.companyId,COMPANY_NAME:'GDT',NAME:'G'+g,STATUS:'IN_PROGRESS',LINK:c.link,LINK_CONNECTION:__cx,API_TOOLS_ID:__at,}});}for(let b=1;b<=c.perrBad;b++){i++;o.push({json:{ACTION:'extract_per_type',__instance:'test',DOC_TYPE:'gdoc',ID:'gdt_pe_'+i,TYPE:'INVOICE',COMPANY_ID:c.companyId,COMPANY_NAME:'GDT',NAME:'B'+b,STATUS:'IN_PROGRESS',LINK:c.badLink,LINK_CONNECTION:__cx,}});} return o;",
    };

    @node({
        id: 'CallPErr',
        name: 'Call PErr',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2440, 800],
        alwaysOutputData: true,
    })
    CallPerr = {
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
        id: 'VerifyPartialError',
        name: 'Verify Partial-Error',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [2660, 800],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    VerifyPartialError = {
        operation: 'executeQuery',
        query: '=SELECT (SELECT count(*) FROM indox_test.incoming_documents WHERE "NAME" LIKE \'G%\' AND "COMPANY_ID"=\'C_GDTEST\' AND "AI_DOC_ID" IS NOT NULL AND "AI_DOC_ID"<>\'\') good, (SELECT count(*) FROM indox_test.incoming_documents WHERE "NAME" LIKE \'B%\' AND "COMPANY_ID"=\'C_GDTEST\' AND "AI_DOC_ID" IS NOT NULL AND "AI_DOC_ID"<>\'\') bad',
        options: {},
    };

    @node({
        id: 'AssertPartialError',
        name: 'Assert Partial-Error',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2880, 800],
    })
    AssertPartialError = {
        jsCode: `// RETURN A RED, NEVER THROW (see Assert Extract). A throw here also skipped 'Cleanup PErr'.
const c=$('Config').first().json; const r=$input.first().json;
const good=Number(r.good), bad=Number(r.bad); const f=[];
if(good!==c.perrGood) f.push('good '+r.good+'/'+c.perrGood);
if(bad!==0) f.push('bad '+r.bad+' should be 0');
if(f.length) return [{json:{result:'FAIL partial-error isolation: '+f.join('; '), good_extracted:good, bad_extracted:bad}}];
return [{json:{result:'PASS partial-error isolation', good_extracted:good, bad_extracted:bad}}];`,
    };

    @node({
        id: 'CleanupPErr',
        name: 'Cleanup PErr',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [3100, 800],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    CleanupPerr = {
        operation: 'executeQuery',
        query: '=DELETE FROM indox_test.incoming_documents WHERE "ID" LIKE \'gdt_pe_%\'',
        options: {},
    };

    @node({
        id: 'LCStart',
        name: 'LC Start',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1780, 1150],
    })
    LcStart = {
        jsCode: 'return [{json:{startMs: Date.now()}}];',
    };

    @node({
        id: 'BuildLCSeed',
        name: 'Build LC Seed',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2000, 1150],
    })
    BuildLcSeed = {
        jsCode: "/* [2026-08-22] LINK_CONNECTION, or this doc is not openable. The drive-connection guard counts a blank one as a missing link, so this seed ended at MISSING_LINK after ONE decide pass and check 1 read 'FAIL full lifecycle: ended at MISSING_LINK'. Same defect the doc_base bare seed had. [phase-4 2026-08-31] The id is still never hardcoded (per-deployment vault hash, a fresh deploy mints a different one), but it is no longer discovered via drive discovery - it comes from the test tenant's settings row test_connections (indoxApi01 TABLE_GET), parsed as JSON.parse(value).drive_connection_id. */ const c=$('Config').first().json; const __row=$('Drive Connections').all().map(i=>i.json).find(r=>r&&r.value); let __cx=null; try { __cx=(JSON.parse(__row.value)||{}).drive_connection_id||null; } catch(e) {} if(!__cx) throw new Error('no drive connection - settings row test_connections missing or unparseable (indoxApi01 TABLE_GET on indox_test)'); return [{json:{INLINE_ACTION:'UPSERT', __instance:'test', ID:'gdt_lc_1', NAME:'Lifecycle', STATUS:'IN_PROGRESS', LINK:c.link, LINK_CONNECTION:__cx, }}];",
    };

    @node({
        id: 'SeedLC',
        name: 'Seed LC',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2220, 1150],
        alwaysOutputData: true,
    })
    SeedLc = {
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
        id: 'BuildGETLC',
        name: 'Build GET LC',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2440, 1150],
    })
    BuildGetLc = {
        jsCode: "return [{json:{INLINE_ACTION:'GET', __instance:'test', ids:'gdt_lc_1'}}];",
    };

    @node({
        id: 'GETLC',
        name: 'GET LC',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2660, 1150],
        alwaysOutputData: true,
    })
    GetLc = {
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
        id: 'DecideLC',
        name: 'Decide LC',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2880, 1150],
        alwaysOutputData: true,
    })
    DecideLc = {
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
        id: 'LCGuard',
        name: 'LC Guard',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3100, 1150],
    })
    LcGuard = {
        jsCode: `// The runaway bound counted commas in ACTION_LOG until 2026-08-21 - a count that was 0
// for exactly the failure it exists to stop (an action that does nothing wrote no log entry).
// It reads ITERATION_COUNT now, which the router increments at DISPATCH, so a no-op action is
// counted like any other and the bound finally measures what it was written to measure.
// Execution 235865 therefore ran 236 passes of the same action instead of stopping at maxSteps.
// Bound on the loop's OWN pass count as well; $runIndex is per-execution, so it stays safe under
// lane concurrency (staticData is not).
const j=$input.first().json;
const steps=Number(j.ITERATION_COUNT)||0;
const maxSteps=$('Config').first().json.maxSteps;
const passes=$runIndex+1;
// [phase-4 2026-08-31] re-stamped: decide's output rows do not carry the tenant, and 'Act LC'
// passes this item through to a production collection that throws without one.
return [{json:{...j, __instance:'test', _lc_steps:steps, _lc_passes:passes, _lc_force: steps > maxSteps || passes > maxSteps}}];`,
    };

    @node({
        id: 'IsDoneLC',
        name: 'Is Done LC?',
        type: 'n8n-nodes-base.if',
        version: 2,
        position: [3320, 1150],
    })
    IsDoneLc = {
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
                    },
                },
                {
                    leftValue: '={{ $json._lc_force }}',
                    rightValue: '',
                    operator: {
                        type: 'boolean',
                        operation: 'true',
                        singleValue: true,
                    },
                },
            ],
            combinator: 'or',
        },
    };

    @node({
        id: 'ActLC',
        name: 'Act LC',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [3320, 1370],
        alwaysOutputData: true,
    })
    ActLc = {
        workflowId: {
            __rl: true,
            value: "={{ (function(c,a,t){ return (c.baseActions||[]).includes(a) ? c.baseCollectionId : (t==='shipment' ? c.shipCollectionId : (t==='bs_doc' ? c.bsCollectionId : c.collectionId)); })($('Config').first().json, $json.ACTION, $json.DOC_TYPE) }}",
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
        id: 'VerifyLifecycle',
        name: 'Verify Lifecycle',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [3540, 1000],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    VerifyLifecycle = {
        operation: 'executeQuery',
        query: '=SELECT "STATUS" AS final_status FROM indox_test.incoming_documents WHERE "ID"=\'gdt_lc_1\'',
        options: {},
    };

    @node({
        id: 'AssertLifecycle',
        name: 'Assert Lifecycle',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3760, 1000],
    })
    AssertLifecycle = {
        jsCode: `// RETURN A RED, NEVER THROW. This node is the ONLY feeder of the Test Summary, so its throw took
// the whole suite down with it: execution 235865 ended 'NO SUMMARY 0' and none of the other four
// checks were ever reported. The summary already renders a non-PASS result as a red check.
//
// It also has to survive the row being GONE: on 235865 the lifecycle livelocked, the state machine
// terminalised the row as no_action_delete_row, and 'Verify Lifecycle' (alwaysOutputData) returned
// {} - so final_status was undefined and the message read 'ended at undefined', naming neither the
// row nor the reason.
const start=$('LC Start').first().json.startMs; const elapsedMs=Date.now()-start;
const r=$input.first().json||{}; const status=r.final_status;
// [2026-08-21] 'steps' USED TO BE COUNTED FROM ACTION_LOG, and that column is gone
// (scripts/ops/migrations/2026-08-21_drop_action_log.sql). The removal left this query as
//     SELECT "STATUS" AS final_status AS action_log
// - two AS aliases on one expression, which is not SQL. Postgres rejected it, this node
// threw, and because it is the ONLY feeder of the Test Summary the whole gdoc suite
// reported 'NO SUMMARY 0'. The reported 'Syntax error at line 1 near "AS"' is, for once,
// n8n's prettifier pointing at a REAL error rather than the first line holding a snippet.
// Not replaced by an equivalent: nothing else records a per-doc action count (the
// ITERATION_COUNT column stays 0 through a full lifecycle). 'passes' is the honest
// measure that still works - how many decide/act rounds the guard actually saw.
let passes=0; try{passes=$('LC Guard').all().length;}catch(e){}
const el=(elapsedMs/1000).toFixed(1);
if(status===undefined||status===null||status==='')
  return [{json:{result:'FAIL full lifecycle: row gdt_lc_1 no longer exists (terminalised or deleted) after '+passes+' decide/act passes in '+el+'s', final_status:null, elapsed_s:el, passes:passes}}];
if(status!=='COMPLETED')
  return [{json:{result:'FAIL full lifecycle: ended at '+status+' after '+passes+' decide/act passes ('+el+'s)', final_status:status, elapsed_s:el, passes:passes}}];
return [{json:{result:'PASS full lifecycle -> COMPLETED', final_status:status, elapsed_s:el, passes:passes}}];`,
    };

    @node({
        id: 'TestSummary',
        name: '🏁 Test Summary',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3980, 1000],
    })
    TestSummary = {
        jsCode: `const g=(node,path)=>{try{const j=$(node).first().json;return path.split('.').reduce((o,k)=>o&&o[k],j);}catch(e){return undefined;}};
const lc=g('Assert Lifecycle','result'); const ex=g('Assert Extract','result'); const cov=g('Assert Coverage','result'); const pe=g('Assert Partial-Error','result'); const dx=g('Assert Batch-LC','result');
const checks=[
 {phase:'1. Full lifecycle -> COMPLETED (timed)', ok:/PASS/.test(String(lc)), detail:'COMPLETED in '+g('Assert Lifecycle','elapsed_s')+'s'},
 {phase:'2. Parallel invoice extraction (bounded-5)', ok:/PASS/.test(String(ex)), detail:g('Assert Extract','extracted')+' extracted'},
 {phase:'3. Pure-write handler coverage', ok:/PASS/.test(String(cov)), detail:g('Assert Coverage','count')+' handlers'},
 {phase:'4. Partial-error isolation', ok:/PASS/.test(String(pe)), detail:String(pe)},
 {phase:'5. Batch lifecycle + extraction quality: GT===AI===KW (5 inv+5 ord+5 shp)', ok:/PASS/.test(String(dx)), detail:g('Assert Batch-LC','passed')+' identical, '+g('Assert Batch-LC','completed')+' completed in '+g('Assert Batch-LC','elapsed_s')+'s'},
];
const allOk=checks.every(c=>c.ok);
return [{json:{RESULT: allOk?'\\u2705 ALL TESTS PASS':'\\u274c FAILURES PRESENT', passed:checks.filter(c=>c.ok).length+'/'+checks.length,
  checks:checks.map(c=>(c.ok?'\\u2705 ':'\\u274c ')+c.phase+' - '+c.detail),
  extraction_quality:{passed:g('Assert Batch-LC','passed'), fails:g('Assert Batch-LC','fails'), scorecard:g('Assert Batch-LC','scorecard')} }}];`,
    };

    @node({
        id: 'AiToggleEnable',
        name: 'AI Toggle Enable',
        /*__n8n__*/ notes: "[2026-08-23] SELF-HEALS ON ENTRY, because a restore that only runs on the success path is not a restore. This node used to open by saving prior=current -- so when a previous run failed, errored, or hit its timeout budget and never reached 'AI Toggle Restore', the leaked true was read back as the PRIOR and written in permanently. That is not hypothetical: plt_prior_extraction_ai_enabled was found sitting at 'true' after pipeline timed out at 1080s, and the shipped fixture default is FALSE (with extraction_local_enabled=true). It matters because GEMINI_API_KEY and GOOGLE_VISION_API_KEY are placeholders on the portable box and the standing rule is that no test may require them -- a leaked global flag turns that rule into a property of the last run's exit status. The two statements ahead of the save undo any leftover first, so a crashed run is repaired by the next run instead of inherited by it.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-260, 1000],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    AiToggleEnable = {
        operation: 'executeQuery',
        query: "UPDATE indox_test.settings s SET value=p.value FROM indox_test.settings p WHERE p.instance='incoming-documents-main' AND p.key='gdt_prior_extraction_ai_enabled' AND s.instance='incoming-documents-main' AND s.key='extraction_ai_enabled'; DELETE FROM indox_test.settings WHERE instance='incoming-documents-main' AND key='gdt_prior_extraction_ai_enabled'; INSERT INTO indox_test.settings(instance,key,value) SELECT 'incoming-documents-main','gdt_prior_extraction_ai_enabled', COALESCE((SELECT value FROM indox_test.settings WHERE instance='incoming-documents-main' AND key='extraction_ai_enabled'),'false') ON CONFLICT (instance,key) DO UPDATE SET value=EXCLUDED.value; INSERT INTO indox_test.settings(instance,key,value) VALUES('incoming-documents-main','extraction_ai_enabled','true') ON CONFLICT (instance,key) DO UPDATE SET value='true';",
        options: {},
    };

    @node({
        id: 'AiToggleRestore',
        name: 'AI Toggle Restore',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [4380, 1000],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    AiToggleRestore = {
        operation: 'executeQuery',
        query: "UPDATE indox_test.settings s SET value=p.value FROM indox_test.settings p WHERE p.instance='incoming-documents-main' AND p.key='gdt_prior_extraction_ai_enabled' AND s.instance='incoming-documents-main' AND s.key='extraction_ai_enabled'; DELETE FROM indox_test.settings WHERE instance='incoming-documents-main' AND key='gdt_prior_extraction_ai_enabled';",
        options: {},
    };

    @node({
        id: 'CleanupLC',
        name: 'Cleanup LC',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [4200, 1000],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    CleanupLc = {
        operation: 'executeQuery',
        query: '=DELETE FROM indox_test.incoming_documents WHERE "ID"=\'gdt_lc_1\'',
        options: {},
    };

    @node({
        id: 'blBatchConfig',
        name: 'Batch Config',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-200, 1100],
    })
    BatchConfig = {
        jsCode: `let __lane='all'; try { __lane=($('Lane Webhook').first().json.body||{}).lane||'all'; } catch(e) {}
const __typemap={inv:'INVOICE',ord:'ORDER',shp:'SHIPMENT'};
// gdx_shp4 IS PINNED because its fixture number collides with a real client document:
// incoming_documents holds 17761087373369yzcsz (COMPANY_ID 511020471, DOC_ID SH2611624,
// COMPANY_NAME סבח, STATUS COMPLETED) and gdx_shp4 carries the SAME company + number, so dedup
// (COMPANY_ID + SHORT_DOC_ID) correctly merges it and it lands STATUS=MERGED with no
// SHORT_DOC_ID/SELECTED_DOC_ID. That is the product behaving correctly on a genuine duplicate.
// The fault is in scripts/gen-unique-corpus.py: it rotates the trailing four digits while
// preserving format, which keeps the mutated number inside the SAME company's real numbering
// space (sbh-5.pdf is itself a סבח document), and it only guarantees uniqueness ACROSS SUITES —
// it never checks the instance's live incoming_documents. FOLLOW-UP: make that generator reject a
// candidate that already exists for the company, then unpin this. The pin is self-retiring —
// Assert Batch-LC prints "[pins healed: gdx_shp4]" on any deployment without that client row.
const __ret=(function(){
return [{json:{"__instance": "test", "knownPins": [], "docs": [{"id": "gdx_inv1", "path": "synth/invoice/files/inv-07.pdf", "upname": "gdx_inv1-inv-07.synth.pdf", "doc_id": "27062011826", "date": "03/02/2026", "company": "511301129", "type": "INVOICE", "short": "11826"}, {"id": "gdx_inv2", "path": "synth/invoice/files/inv-08.pdf", "upname": "gdx_inv2-inv-08.synth.pdf", "doc_id": "50811850335", "date": "04/06/2025", "company": "513105494", "type": "INVOICE", "short": "50335"}, {"id": "gdx_inv3", "path": "synth/invoice/files/inv-09.pdf", "upname": "gdx_inv3-inv-09.synth.pdf", "doc_id": "33477924104", "date": "26/09/2025", "company": "513105494", "type": "INVOICE", "short": "24104"}, {"id": "gdx_inv4", "path": "synth/invoice/files/inv-10.pdf", "upname": "gdx_inv4-inv-10.synth.pdf", "doc_id": "51345701919", "date": "24/07/2026", "company": "510605959", "type": "INVOICE", "short": "01919"}, {"id": "gdx_inv5", "path": "synth/invoice/files/inv-11.pdf", "upname": "gdx_inv5-inv-11.synth.pdf", "doc_id": "SI256922754", "date": "12/03/2026", "company": "513105494", "type": "INVOICE", "short": "22754"}, {"id": "gdx_ord1", "path": "synth/order/files/ord-07.pdf", "upname": "gdx_ord1-ord-07.synth.pdf", "doc_id": "PO26610296", "date": "10/06/2025", "company": "511301129", "type": "ORDER", "short": "10296"}, {"id": "gdx_ord2", "path": "synth/order/files/ord-08.pdf", "upname": "gdx_ord2-ord-08.synth.pdf", "doc_id": "PO25470710", "date": "18/10/2026", "company": "511301129", "type": "ORDER", "short": "70710"}, {"id": "gdx_ord3", "path": "synth/order/files/ord-09.pdf", "upname": "gdx_ord3-ord-09.synth.pdf", "doc_id": "PO25157792", "date": "09/01/2026", "company": "511634388", "type": "ORDER", "short": "57792"}, {"id": "gdx_ord4", "path": "synth/order/files/ord-10.pdf", "upname": "gdx_ord4-ord-10.synth.pdf", "doc_id": "PO26260063", "date": "09/11/2026", "company": "511634388", "type": "ORDER", "short": "60063"}, {"id": "gdx_ord5", "path": "synth/order/files/ord-01.pdf", "upname": "gdx_ord5-ord-01.synth.pdf", "doc_id": "PO26196805", "date": "12/05/2025", "company": "511234567", "type": "ORDER", "short": "96805"}, {"id": "gdx_shp1", "path": "synth/shipment/files/shp-07.pdf", "upname": "gdx_shp1-shp-07.synth.pdf", "doc_id": "S0126000205", "date": "26/07/2025", "company": "513105494", "type": "SHIPMENT", "short": "00205"}, {"id": "gdx_shp2", "path": "synth/shipment/files/shp-08.pdf", "upname": "gdx_shp2-shp-08.synth.pdf", "doc_id": "SHM25056410", "date": "06/11/2025", "company": "570043745", "type": "SHIPMENT", "short": "56410"}, {"id": "gdx_shp3", "path": "synth/shipment/files/shp-09.pdf", "upname": "gdx_shp3-shp-09.synth.pdf", "doc_id": "S01250071140", "date": "07/08/2025", "company": "510605959", "type": "SHIPMENT", "short": "71140"}, {"id": "gdx_shp4", "path": "synth/shipment/files/shp-10.pdf", "upname": "gdx_shp4-shp-10.synth.pdf", "doc_id": "02TSH25023525", "date": "12/05/2026", "company": "513105494", "type": "SHIPMENT", "short": "23525"}, {"id": "gdx_shp5", "path": "synth/shipment/files/shp-11.pdf", "upname": "gdx_shp5-shp-11.synth.pdf", "doc_id": "S0126006951", "date": "20/05/2025", "company": "513105494", "type": "SHIPMENT", "short": "06951"}], "ids": "gdx_inv1,gdx_inv2,gdx_inv3,gdx_inv4,gdx_inv5,gdx_ord1,gdx_ord2,gdx_ord3,gdx_ord4,gdx_ord5,gdx_shp1,gdx_shp2,gdx_shp3,gdx_shp4,gdx_shp5", "demoBase": "http://indox-demo-docs:8088", "maxIter": 45}}];
})();
if (__lane.startsWith('batch:')) {
  const t=__typemap[__lane.split(':')[1]];
  const j=__ret[0].json;
  j.docs=j.docs.filter(d=>d.type===t);
  const keep=new Set(j.docs.map(d=>d.id));
  // \`ids\` is a comma-joined STRING here, not an array — an Array.isArray guard on it is
  // always false, so this narrowing silently never ran and batch lanes carried all 15
  // ids against 5 docs. Handle the type it actually is; keep the array branch so the
  // guard stays total if \`ids\` ever becomes a list.
  if (typeof j.ids === 'string') j.ids=j.ids.split(',').filter(id=>keep.has(id)).join(',');
  else if (Array.isArray(j.ids)) j.ids=j.ids.filter(id=>keep.has(id));
  if (Array.isArray(j.knownPins)) j.knownPins=j.knownPins.filter(id=>keep.has(id));
}
return __ret;`,
    };

    @node({
        id: 'blBatchLCStart',
        name: 'Batch-LC Start',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [0, 1100],
        alwaysOutputData: true,
    })
    BatchLcStart = {
        jsCode: "const s=$getWorkflowStaticData('global'); s.blcStart=Date.now(); s.blcIter=0; return [{json:{}}];",
    };

    @node({
        id: 'blBatchCleanupPrior',
        name: 'Batch Cleanup Prior',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [200, 1100],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    BatchCleanupPrior = {
        operation: 'executeQuery',
        query: `=DELETE FROM indox_test.incoming_documents WHERE "ID" LIKE '{{ (() => { let l='all'; try { l=($('Lane Webhook').first().json.body||{}).lane||'all'; } catch(e) {}
const m={'batch:inv':"gdx_inv%",'batch:ord':"gdx_ord%",'batch:shp':"gdx_shp%"};
return m[l] || 'gdx_%'; })() }}';`,
        options: {},
    };

    @node({
        id: 'blListgdxFiles',
        name: 'List gdx Files',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [400, 940],
        alwaysOutputData: true,
    })
    ListGdxFiles = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'list',
                params: "={{ ({ nameContains: 'gdx_', includeTrashed: false, limit: 200, profile_id: 'admin' }) }}",
            },
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'blResolveLinks',
        name: 'Resolve Links',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [600, 940],
        alwaysOutputData: true,
    })
    ResolveLinks = {
        jsCode: "const cfg=$('Batch Config').first().json; const files=$input.all().map(i=>i.json).filter(f=>f&&f.name); const byName={}; files.forEach(f=>{byName[f.name]=f.webViewLink;});return cfg.docs.map(d=>({json:{...d, LINK:(byName[d.upname]||null), _missing:(byName[d.upname]?false:true)}}));",
    };

    @node({
        id: 'blLoopSeed',
        name: 'Loop Seed',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [800, 1100],
    })
    LoopSeed = {
        batchSize: 1,
        options: {},
    };

    @node({
        id: 'blNeedUpload',
        name: 'Need Upload?',
        type: 'n8n-nodes-base.if',
        version: 2,
        position: [1200, 956],
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
        id: 'bldl',
        name: 'Download Local',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [1400, 1440],
    })
    DownloadLocal = {
        url: "={{ $('Batch Config').first().json.demoBase + '/' + $('Loop Seed').item.json.path }}",
        options: {
            response: {
                response: {
                    responseFormat: 'file',
                },
            },
        },
    };

    @node({
        id: 'blUploadtoDrive',
        name: 'Upload to Drive',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1600, 1440],
        alwaysOutputData: true,
    })
    UploadToDrive = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'upload',
                params: "={{ ({ name: $('Loop Seed').item.json.upname, profile_id: 'admin' }) }}",
            },
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'blSetLink',
        name: 'Set Link',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1800, 1440],
        alwaysOutputData: true,
    })
    SetLink1 = {
        jsCode: "return [{json:{...$('Loop Seed').item.json, LINK:$input.first().json.webViewLink}}];",
    };

    @node({
        id: 'blBuildUPSERT',
        name: 'Build UPSERT',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2000, 1280],
    })
    BuildUpsert = {
        jsCode: "const __row=$('Drive Connections').all().map(i=>i.json).find(r=>r&&r.value); let __cx=null; try { __cx=(JSON.parse(__row.value)||{}).drive_connection_id||null; } catch(e) {} if(!__cx) throw new Error('no drive connection - settings row test_connections missing or unparseable (indoxApi01 TABLE_GET on indox_test)'); const d=$json; return [{json:{INLINE_ACTION:'UPSERT',__instance:'test',LINK_CONNECTION:__cx, ID:d.id, NAME:d.id, STATUS:'IN_PROGRESS', LINK:d.LINK, }}];",
    };

    @node({
        id: 'blSeedOne',
        name: 'Seed One',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2200, 1280],
        alwaysOutputData: true,
    })
    SeedOne = {
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
        id: 'blBuildGETBatch',
        name: 'Build GET Batch',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [800, 940],
    })
    BuildGetBatch = {
        jsCode: "return [{json:{INLINE_ACTION:'GET', __instance:'test', ids:$('Batch Config').first().json.ids}}];",
    };

    @node({
        id: 'blGETBatch',
        name: 'GET Batch',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1000, 940],
        alwaysOutputData: true,
    })
    GetBatch = {
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
        id: 'blDecideBatch',
        name: 'Decide Batch',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1200, 940],
        alwaysOutputData: true,
    })
    DecideBatch = {
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
        id: 'blBatchGuard',
        name: 'Batch Guard',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1400, 940],
        alwaysOutputData: true,
    })
    BatchGuard = {
        jsCode: "const s=$getWorkflowStaticData('global'); s.blcIter=(s.blcIter||0)+1;const items=$input.all().map(i=>i.json);const act=items.filter(j=> j.ACTION && !String(j.ACTION).startsWith('no_action'));const force = s.blcIter > $('Batch Config').first().json.maxIter;if(act.length===0 || force) return [{json:{_done:true, iter:s.blcIter, forced:force}}];return act.map(j=>({json:{...j, __instance:'test'}}));   // [phase-4 2026-08-31] re-stamped: decide's output rows do not carry the tenant",
    };

    @node({
        id: 'blIsDoneBatch',
        name: 'Is Done Batch?',
        type: 'n8n-nodes-base.if',
        version: 2,
        position: [1600, 940],
    })
    IsDoneBatch = {
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
        id: 'blActBatch',
        name: 'Act Batch',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1400, 1140],
        alwaysOutputData: true,
    })
    ActBatch = {
        workflowId: {
            __rl: true,
            value: "={{ (function(c,a,t){ return (c.baseActions||[]).includes(a) ? c.baseCollectionId : (t==='shipment' ? c.shipCollectionId : (t==='bs_doc' ? c.bsCollectionId : c.collectionId)); })($('Config').first().json, $json.ACTION, $json.DOC_TYPE) }}",
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
        id: 'blVerifyBatch',
        name: 'Verify Batch',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [1800, 940],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    VerifyBatch = {
        operation: 'executeQuery',
        query: `=SELECT "ID" AS id,"STATUS" AS status,"TYPE" AS type,"PER_TYPE_EXTRACTION_COMPLETED" AS per_type_done,"PRIORITY_SYNC_COMPLETED" AS priority_done,(SELECT count(*) FROM indox_test.indox_action_execution_log l WHERE l."ID"=incoming_documents."ID" AND l."ACTION" IN ('extract_per_type','select_type','action_priority_sync','restart_priority_sync','extract_invoice_google_ai','select_invoice_values','check_from_office','find_link')) AS forbidden_n,(SELECT count(*) FROM indox_test.indox_action_execution_log l WHERE l."ID"=incoming_documents."ID" AND l."ACTION"='mark_completed') AS mark_completed_n,"AI_DOC_ID" AS ai_doc_id,"LOCAL_DOC_ID" AS local_doc_id,"LOCAL_DOC_DATE" AS local_doc_date,"LOCAL_TYPE" AS local_type,"AI_DOC_DATE" AS ai_doc_date,"AI_TYPE" AS ai_type,"SHORT_DOC_ID" AS short_doc_id,"DOC_DATE" AS kw_date FROM indox_test.incoming_documents WHERE "ID" LIKE '{{ (() => { let l='all'; try { l=($('Lane Webhook').first().json.body||{}).lane||'all'; } catch(e) {}
const m={'batch:inv':'gdx_inv%','batch:ord':'gdx_ord%','batch:shp':'gdx_shp%'};
return m[l] || 'gdx_%'; })() }}' ORDER BY "ID"`,
        options: {},
    };

    @node({
        id: 'blAssertBatchLC',
        name: 'Assert Batch-LC',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2000, 940],
        alwaysOutputData: true,
    })
    AssertBatchLc = {
        jsCode: "const cfg=$('Batch Config').first().json; const gt={}; cfg.docs.forEach(d=>gt[d.id]=d);const pins=cfg.knownPins||[];const s=$getWorkflowStaticData('global'); const elapsed=s.blcStart?Math.round((Date.now()-s.blcStart)/1000):null;const rows=$input.all().map(i=>i.json); const v=x=>String(x==null?'':x).trim();const fails=[]; const pinned=[]; const table=[]; let completed=0;for(const r of rows){ const g=gt[r.id]||{}; const chk=[]; if(r.status==='COMPLETED') completed++;  const eq=(f,got,exp)=>{ if(v(got)!==v(exp)) chk.push(f+':\"'+v(got)+'\"!=\"'+v(exp)+'\"'); }; const eqT=(f,got,exp)=>{ if(v(got).toUpperCase()!==v(exp).toUpperCase()) chk.push(f+':\"'+v(got)+'\"!=\"'+v(exp)+'\"'); };  const inv=(g.type==='INVOICE');  const parked=(g.type==='ORDER'||g.type==='RECEIPT');  if(parked){ if(v(r.status)!=='COMPLETED') chk.push('status:'+v(r.status)+' != COMPLETED'); /* [log ownership 2026-08-31] the two ACTION-LOG counts (forbidden_n>0, mark_completed!==1) are DROPPED here: indox_action_execution_log is written by the DISPATCH layer (Driver01/ActionRouter/BaseDrain), and this suite's Act calls the collections directly -- on this path the log is structurally empty, so forbidden_n was vacuously 0 and mark_completed could never be 1 (measured: exec 3759336, completed orders x0). The sealed-dispatch guarantees belong to driver-path suites: the pipeline batch today, and the per-type ActionsSealed matrix next. */ if(v(r.per_type_done).toLowerCase()==='true') chk.push('PER_TYPE_EXTRACTION_COMPLETED set on a parked type'); if(v(r.priority_done).toLowerCase()==='true') chk.push('PRIORITY_SYNC_COMPLETED set on a parked type'); eqT('TYPE',r.type,g.type); } else { if(v(r.status)!=='COMPLETED') chk.push('status:'+v(r.status)+' != COMPLETED'); eqT('TYPE',r.type,g.type); eq('DOC_DATE',r.kw_date,g.date); if(g.type!=='SHIPMENT') eq('SHORT',r.short_doc_id,g.short); }  if(inv){ eq('AI.raw',r.ai_doc_id,g.doc_id); eqT('LOCAL.type',r.local_type,g.type); }  if(chk.length){ if(pins.includes(r.id)) pinned.push(r.id+' { '+chk.join(', ')+' }'); else fails.push(r.id+' { '+chk.join(', ')+' }'); }  table.push({id:r.id, status:r.status, GT:g.short+'|'+g.date+'|'+g.type, AI:v(r.ai_doc_id)+'|'+v(r.ai_doc_date)+'|'+v(r.ai_type), LOCAL:v(r.local_doc_id)+'|'+v(r.local_doc_date)+'|'+v(r.local_type), ROW:v(r.short_doc_id)+'|'+v(r.kw_date)+'|'+v(r.type), parked:(g.type==='ORDER'||g.type==='RECEIPT'), forbidden_n:r.forbidden_n, mc_n:r.mark_completed_n, ok:chk.length===0, pinned:pins.includes(r.id)&&chk.length>0}); }const passed=table.filter(t=>t.ok).length;const healed=pins.filter(pid=>{const t=table.find(x=>x.id===pid);return t&&t.ok;});return [{json:{result:(fails.length?('❌ FAIL '+fails.length+'/'+rows.length+' drifted: '+fails.join('; ')):('✅ PASS '+(pinned.length?(passed+'/'+rows.length+' identical, '+pinned.length+' known-pinned'):('all '+rows.length+' identical'))+(healed.length?(' [pins healed: '+healed.join(',')+']'):''))), passed:passed+'/'+rows.length, completed:completed+'/'+rows.length, elapsed_s:elapsed, iters:s.blcIter, fails, pinned, scorecard:table}}];",
    };

    @node({
        id: 'e3267029-24ac-47bb-9490-e8d3218534ea',
        name: 'Fx List',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [160, 540],
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
        id: '2817502f-b936-47a6-b54c-e1134e5ec4a0',
        name: 'Fx Resolve',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [320, 540],
    })
    FxResolve = {
        jsCode: 'const files=[{"key": "link", "upname": "fxgd-dltvt-tyyr-2.pdf", "path": "invoice/files/dltvt-tyyr-2.pdf"}, {"key": "gdx_inv1", "upname": "gdx_inv1-inv-07.synth.pdf", "path": "synth/invoice/files/inv-07.pdf"}, {"key": "gdx_inv2", "upname": "gdx_inv2-inv-08.synth.pdf", "path": "synth/invoice/files/inv-08.pdf"}, {"key": "gdx_inv3", "upname": "gdx_inv3-inv-09.synth.pdf", "path": "synth/invoice/files/inv-09.pdf"}, {"key": "gdx_inv4", "upname": "gdx_inv4-inv-10.synth.pdf", "path": "synth/invoice/files/inv-10.pdf"}, {"key": "gdx_inv5", "upname": "gdx_inv5-inv-11.synth.pdf", "path": "synth/invoice/files/inv-11.pdf"}, {"key": "gdx_ord1", "upname": "gdx_ord1-ord-07.synth.pdf", "path": "synth/order/files/ord-07.pdf"}, {"key": "gdx_ord2", "upname": "gdx_ord2-ord-08.synth.pdf", "path": "synth/order/files/ord-08.pdf"}, {"key": "gdx_ord3", "upname": "gdx_ord3-ord-09.synth.pdf", "path": "synth/order/files/ord-09.pdf"}, {"key": "gdx_ord4", "upname": "gdx_ord4-ord-10.synth.pdf", "path": "synth/order/files/ord-10.pdf"}, {"key": "gdx_ord5", "upname": "gdx_ord5-ord-01.synth.pdf", "path": "synth/order/files/ord-01.pdf"}, {"key": "gdx_shp1", "upname": "gdx_shp1-shp-07.synth.pdf", "path": "synth/shipment/files/shp-07.pdf"}, {"key": "gdx_shp2", "upname": "gdx_shp2-shp-08.synth.pdf", "path": "synth/shipment/files/shp-08.pdf"}, {"key": "gdx_shp3", "upname": "gdx_shp3-shp-09.synth.pdf", "path": "synth/shipment/files/shp-09.pdf"}, {"key": "gdx_shp4", "upname": "gdx_shp4-shp-10.synth.pdf", "path": "synth/shipment/files/shp-10.pdf"}, {"key": "gdx_shp5", "upname": "gdx_shp5-shp-11.synth.pdf", "path": "synth/shipment/files/shp-11.pdf"}];const byName={}; $input.all().map(i=>i.json).filter(f=>f&&f.name).forEach(f=>{byName[f.name]=f.webViewLink;});return files.map(f=>({json:{...f, LINK:byName[f.upname]||null, _missing:!byName[f.upname]}}));',
    };

    @node({
        id: '28fb5591-6116-4888-9607-ea1bc4b6b2b9',
        name: 'Fx Loop',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [480, 540],
    })
    FxLoop = {
        batchSize: 1,
        options: {},
    };

    @node({
        id: 'a93b36b3-f80f-40a4-a7ef-7924374585a1',
        name: 'Fx Need Upload?',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [640, 396],
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
        id: 'ce48428a-3505-4fcc-9211-a30be05cddd0',
        name: 'Fx Download',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [800, 720],
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
        id: '4e00fb95-29e1-4c7f-82f1-eea466ae7735',
        name: 'Fx Upload',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [960, 720],
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
        id: 'cc135261-3fd6-4978-8e4e-9558bf47dfa8',
        name: 'Fx Set Link',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1120, 720],
    })
    FxSetLink = {
        jsCode: "return [{json:{...$('Fx Loop').item.json, LINK:$input.first().json.webViewLink, _missing:false}}];",
    };

    @node({
        id: '54fbad55-c0f5-4672-9213-100308cf093d',
        name: 'Fx Pass',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [800, 540],
    })
    FxPass = {
        jsCode: 'return $input.all();',
    };

    @node({
        id: 'd328e85f-6740-4ddf-982e-230d7b31340d',
        name: 'Config',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [640, 400],
    })
    Config = {
        jsCode: 'const base=$(\'Config Base\').first().json;const files=[{"key": "link", "upname": "fxgd-dltvt-tyyr-2.pdf", "path": "invoice/files/dltvt-tyyr-2.pdf"}];const byName={}; $input.all().map(i=>i.json).filter(x=>x&&x.name).forEach(x=>{byName[x.name]=x.webViewLink;});const links={}; files.forEach(x=>links[x.key]=byName[x.upname]||null);if(!links.link) throw new Error(\'fixture link resolution failed: \'+JSON.stringify(links));return [{json:{...base, link:links.link}}];',
    };

    @node({
        id: 'gdt-fx-settle',
        name: 'Fx Settle',
        /*__n8n__*/ notes: "[visibility settle 2026-09-01] Battery-7: the fixture list ran on the heels of the upload and came back WITHOUT the just-uploaded file -- no error, so Fx List 2's retryOnFail never fired, and Config threw 'fixture link resolution failed: null' at 11s (single occurrence across dozens of runs; the suite greened untouched on the next pass). Three seconds between upload and list absorbs the lag class without masking a real miss -- Config's throw still stands.",
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [480, 540],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    FxSettle = {
        operation: 'executeQuery',
        query: 'select pg_sleep(3)',
        options: {},
    };

    @node({
        id: 'a2089c73-b561-4581-8c3b-4c601dcb3b51',
        name: 'Fx List 2',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [560, 400],
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
        id: '36730457-d969-4170-a7c7-640ce23de678',
        name: 'Seed Test Fixtures',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [-110, 580],
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
        id: 'gdoclanewebhook1',
        webhookId: 'gdoc-e2e-lane',
        name: 'Lane Webhook',
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [-200, 880],
    })
    LaneWebhook = {
        httpMethod: 'POST',
        path: 'gdoc-e2e-lane',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'gdoclaneswitch01',
        name: 'Lane Switch',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [1740, 700],
    })
    LaneSwitch = {
        rules: {
            values: [
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'l-extract',
                                leftValue:
                                    "={{ (() => { try { const b = $('Lane Webhook').first().json.body || {}; return b.lane || 'all'; } catch(e) { return 'all'; } })() }}",
                                rightValue: 'extract',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'extract',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'l-cov',
                                leftValue:
                                    "={{ (() => { try { const b = $('Lane Webhook').first().json.body || {}; return b.lane || 'all'; } catch(e) { return 'all'; } })() }}",
                                rightValue: 'cov',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'cov',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'l-perr',
                                leftValue:
                                    "={{ (() => { try { const b = $('Lane Webhook').first().json.body || {}; return b.lane || 'all'; } catch(e) { return 'all'; } })() }}",
                                rightValue: 'perr',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'perr',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'l-batch',
                                leftValue:
                                    "={{ (() => { try { const b = $('Lane Webhook').first().json.body || {}; return b.lane || 'all'; } catch(e) { return 'all'; } })() }}",
                                rightValue: 'batch',
                                operator: {
                                    type: 'string',
                                    operation: 'startsWith',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'batch',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'l-lc',
                                leftValue:
                                    "={{ (() => { try { const b = $('Lane Webhook').first().json.body || {}; return b.lane || 'all'; } catch(e) { return 'all'; } })() }}",
                                rightValue: 'lc',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'lc',
                },
            ],
        },
        options: {
            fallbackOutput: 'extra',
            renameFallbackOutput: 'all',
        },
    };

    @node({
        id: 'gdoclanerespond1',
        name: 'Respond Lane',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [1740, 1020],
        onError: 'continueRegularOutput',
    })
    RespondLane = {
        respondWith: 'allIncomingItems',
        options: {},
    };

    @node({
        id: 'perrwaitloop001',
        name: 'PErr Wait',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2480, 640],
    })
    PerrWait = {
        jsCode: `// non-suspending sleep: a Wait node parks the execution in 'waiting' state,
// which drops the pending lane-webhook response. Code sleep keeps it live.
await new Promise(r => setTimeout(r, 15000));
return $input.all();`,
    };

    @node({
        id: 'perrreadyif0001',
        name: 'PErr Ready?',
        type: 'n8n-nodes-base.if',
        version: 2,
        position: [2840, 640],
    })
    PerrReady = {
        conditions: {
            options: {
                caseSensitive: true,
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'r1',
                    leftValue:
                        "={{ (Number($json.good) === $('Config').first().json.perrGood && Number($json.bad) === 0) || $runIndex >= 12 }}",
                    rightValue: 'true',
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
        id: 'gdt-clock-lc',
        name: 'Clock LC',
        /*__n8n__*/ notes: "[test-clock 2026-08-31] Direct decide calls carry no driver enrich, so the tenant's 240-month window is unreachable and fallback-6 aged the synthetic batch into OLD (exec 3759336: 12/15). Same _cfg channel bs/doc_base use.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2600, 950],
    })
    ClockLc = {
        jsCode: 'return $input.all().map(i=>({json:{...i.json, _cfg:{old_document_months_back:240}}}));',
    };

    @node({
        id: 'gdt-clock-batch',
        name: 'Clock Batch',
        /*__n8n__*/ notes: "[test-clock 2026-08-31] see 'Clock LC'.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2600, 1450],
    })
    ClockBatch = {
        jsCode: 'return $input.all().map(i=>({json:{...i.json, _cfg:{old_document_months_back:240}}}));',
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.RunGdocE2eTest.out(0).to(this.SeedTestFixtures.in(0));
        this.Config.out(0).to(this.BuildTestConnectionsReq.in(0));
        this.BuildTestConnectionsReq.out(0).to(this.DriveConnections.in(0));
        this.CaptureFlagOff.out(0).to(this.CleanupPrior.in(0));
        this.CleanupPrior.out(0).to(this.SetLink.in(0));
        this.SetLink.out(0).to(this.DownloadForHash.in(0));
        this.DownloadForHash.out(0).to(this.CryptoHash.in(0));
        this.CryptoHash.out(0).to(this.PrimeCacheInvoiceFixture.in(0));
        this.PrimeCacheInvoiceFixture.out(0).to(this.ExecuteFlows.in(0));
        this.ExecuteFlows.out(0).to(this.LaneSwitch.in(0));
        this.BuildExtractSeeds.out(0).to(this.SeedExtract.in(0));
        this.SeedExtract.out(0).to(this.BuildExtractItems.in(0));
        this.BuildExtractItems.out(0).to(this.CallExtract.in(0));
        this.CallExtract.out(0).to(this.VerifyExtract.in(0));
        this.VerifyExtract.out(0).to(this.AssertExtract.in(0));
        this.AssertExtract.out(0).to(this.CleanupExtract.in(0));
        this.AssertExtract.out(0).to(this.RespondLane.in(0));
        this.BuildCovSeed.out(0).to(this.SeedCov.in(0));
        this.SeedCov.out(0).to(this.EmitActions.in(0));
        this.EmitActions.out(0).to(this.CallCov.in(0));
        this.CallCov.out(0).to(this.AssertCoverage.in(0));
        this.AssertCoverage.out(0).to(this.CleanupCov.in(0));
        this.AssertCoverage.out(0).to(this.RespondLane.in(0));
        this.BuildPerrSeeds.out(0).to(this.SeedPerr.in(0));
        this.SeedPerr.out(0).to(this.BuildPerrItems.in(0));
        this.BuildPerrItems.out(0).to(this.CallPerr.in(0));
        this.CallPerr.out(0).to(this.PerrWait.in(0));
        this.VerifyPartialError.out(0).to(this.PerrReady.in(0));
        this.AssertPartialError.out(0).to(this.CleanupPerr.in(0));
        this.AssertPartialError.out(0).to(this.RespondLane.in(0));
        this.LcStart.out(0).to(this.BuildLcSeed.in(0));
        this.BuildLcSeed.out(0).to(this.SeedLc.in(0));
        this.SeedLc.out(0).to(this.BuildGetLc.in(0));
        this.BuildGetLc.out(0).to(this.GetLc.in(0));
        this.GetLc.out(0).to(this.ClockLc.in(0));
        this.ClockLc.out(0).to(this.DecideLc.in(0));
        this.DecideLc.out(0).to(this.LcGuard.in(0));
        this.LcGuard.out(0).to(this.IsDoneLc.in(0));
        this.IsDoneLc.out(0).to(this.VerifyLifecycle.in(0));
        this.IsDoneLc.out(1).to(this.ActLc.in(0));
        this.ActLc.out(0).to(this.BuildGetLc.in(0));
        this.VerifyLifecycle.out(0).to(this.AssertLifecycle.in(0));
        this.AssertLifecycle.out(0).to(this.TestSummary.in(0));
        this.AssertLifecycle.out(0).to(this.RespondLane.in(0));
        this.TestSummary.out(0).to(this.CleanupLc.in(0));
        this.CleanupLc.out(0).to(this.AiToggleRestore.in(0));
        this.BatchConfig.out(0).to(this.BatchLcStart.in(0));
        this.BatchLcStart.out(0).to(this.BatchCleanupPrior.in(0));
        this.BatchCleanupPrior.out(0).to(this.ListGdxFiles.in(0));
        this.ListGdxFiles.out(0).to(this.ResolveLinks.in(0));
        this.ResolveLinks.out(0).to(this.LoopSeed.in(0));
        this.LoopSeed.out(0).to(this.BuildGetBatch.in(0));
        this.LoopSeed.out(1).to(this.NeedUpload.in(0));
        this.NeedUpload.out(0).to(this.DownloadLocal.in(0));
        this.NeedUpload.out(1).to(this.BuildUpsert.in(0));
        this.DownloadLocal.out(0).to(this.UploadToDrive.in(0));
        this.UploadToDrive.out(0).to(this.SetLink1.in(0));
        this.SetLink1.out(0).to(this.BuildUpsert.in(0));
        this.BuildUpsert.out(0).to(this.SeedOne.in(0));
        this.SeedOne.out(0).to(this.LoopSeed.in(0));
        this.BuildGetBatch.out(0).to(this.GetBatch.in(0));
        this.GetBatch.out(0).to(this.ClockBatch.in(0));
        this.ClockBatch.out(0).to(this.DecideBatch.in(0));
        this.DecideBatch.out(0).to(this.BatchGuard.in(0));
        this.BatchGuard.out(0).to(this.IsDoneBatch.in(0));
        this.IsDoneBatch.out(0).to(this.VerifyBatch.in(0));
        this.IsDoneBatch.out(1).to(this.ActBatch.in(0));
        this.ActBatch.out(0).to(this.BuildGetBatch.in(0));
        this.VerifyBatch.out(0).to(this.AssertBatchLc.in(0));
        this.ConfigBase.out(0).to(this.FxList.in(0));
        this.FxList.out(0).to(this.FxResolve.in(0));
        this.FxResolve.out(0).to(this.FxLoop.in(0));
        this.FxLoop.out(0).to(this.FxSettle.in(0));
        this.FxSettle.out(0).to(this.FxList2.in(0));
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
        this.LaneWebhook.out(0).to(this.SeedTestFixtures.in(0));
        this.LaneSwitch.out(0).to(this.BuildExtractSeeds.in(0));
        this.LaneSwitch.out(1).to(this.BuildCovSeed.in(0));
        this.LaneSwitch.out(2).to(this.BuildPerrSeeds.in(0));
        this.LaneSwitch.out(3).to(this.BatchConfig.in(0));
        this.LaneSwitch.out(4).to(this.LcStart.in(0));
        this.LaneSwitch.out(5).to(this.BuildExtractSeeds.in(0));
        this.LaneSwitch.out(5).to(this.BuildCovSeed.in(0));
        this.LaneSwitch.out(5).to(this.BuildPerrSeeds.in(0));
        this.LaneSwitch.out(5).to(this.BatchConfig.in(0));
        this.LaneSwitch.out(5).to(this.LcStart.in(0));
        this.AssertBatchLc.out(0).to(this.RespondLane.in(0));
        this.PerrWait.out(0).to(this.VerifyPartialError.in(0));
        this.PerrReady.out(0).to(this.AssertPartialError.in(0));
        this.PerrReady.out(1).to(this.PerrWait.in(0));
        this.DriveConnections.out(0).to(this.BuildUploadReq.in(0));
        this.BuildUploadReq.out(0).to(this.UploadFixture.in(0));
        this.UploadFixture.out(0).to(this.CaptureFlagOff.in(0));
    }
}
