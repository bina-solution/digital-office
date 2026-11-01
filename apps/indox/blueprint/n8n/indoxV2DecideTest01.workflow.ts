import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox-v2 Decide Tests
// Nodes   : 8  |  Connections: 7
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// RunTests                           manualTrigger
// DetermineActionTests               code
// ExecuteDecide                      executeWorkflow
// DetermineActionTestAssertions      code
// TestSummary                        code
// LaneWebhook                        webhook
// LaneVerdict                        code
// RespondLane                        respondToWebhook           [onError→regular]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// RunTests
//    → DetermineActionTests
//      → ExecuteDecide
//        → DetermineActionTestAssertions
//          → TestSummary
//            → LaneVerdict
//              → RespondLane
// LaneWebhook
//    → DetermineActionTests (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Run Tests":{"main":[[{"node":"Determine Action Tests","type":"main","index":0}]]},"Determine Action Tests":{"main":[[{"node":"Execute Decide","type":"main","index":0}]]},"Execute Decide":{"main":[[{"node":"Determine Action Test Assertions","type":"main","index":0}]]},"Determine Action Test Assertions":{"main":[[{"node":"🏁 Test Summary","type":"main","index":0}]]},"Lane Webhook":{"main":[[{"node":"Determine Action Tests","type":"main","index":0}]]},"🏁 Test Summary":{"main":[[{"node":"Lane Verdict","type":"main","index":0}]]},"Lane Verdict":{"main":[[{"node":"Respond Lane","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"dcb770a3-465f-4ed5-b5d4-ca1ff6dcd994","name":"lifecycle:test"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"1a1f9021-970c-46eb-8cef-4746d2dca0d0","name":"indox-state-machine-v2"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"2b5cb873-dd65-44dd-bf27-a2c99d2b81a4","name":"state-machine-v2"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {"templateCredsSetupCompleted":true},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"indoxV2DecideTest01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2DecideTest01',
    name: 'indox-v2 Decide Tests',
    active: false,
    isArchived: false,
    tags: ['indox-app', 'lifecycle:test', 'app:indox', 'indox', 'indox-state-machine-v2', 'state-machine-v2'],
    settings: { executionOrder: 'v1' },
})
export class IndoxV2DecideTestsWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'v2t-man',
        name: 'Run Tests',
        /*__n8n__*/ notes: "Edited as code and pushed via `bbox n8n push indox --wf indoxV2DecideTest01` — the as-code proof note (2026-08-16). cas-check. v2.",
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [0, 0],
    })
    RunTests = {};

    @node({
        id: 'v2t-cases',
        name: 'Determine Action Tests',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [240, 0],
    })
    DetermineActionTests = {
        jsCode: `// ─── Test Case Generator for determineAction ─────────────────────────────────
// Each output item has:
//   json.expected_action  — the action determineAction should return
//   json.doc_type         — expected DOC_TYPE
//   json.label            — human-readable test name
//   json.* — all doc fields to feed into determineAction

const BASE = {
  ID: '1001',
  TYPE: 'INVOICE',
  STATUS: '',
  COMPANY_ID: 'C01',
  COMPANY_NAME: 'Acme',
  // DOC_ID, SHORT_DOC_ID, and NAME are removed from BASE 
  // because we will generate them dynamically to satisfy validation rules.
  LINK: 'https://drive.google.com/file/abc',
  // [missing-link rule 2026-08-24] A LINK with no LINK_CONNECTION IS a missing link (find_link).
  // Every case that is not ABOUT that rule carries a connection; the dedicated no-connection
  // cases override this to ''.
  LINK_CONNECTION: 'drive_local-test0',
  API_TOOLS_ID: 'at-999',
  FROM_OFFICE_CHECK: 'yes',
  DOC_DATE: new Date(Date.now()-30*86400000).toISOString().slice(0,10), // [v2] always recent so the old-date guard doesn't mask cases
  DOC_TOTAL_AMOUNT: '5000',
  PURCHASE_ID: 'PO-555',
  SHIPMENT_DOC_ID: 'SHP-001',
  HASH: null,
  BASE_EXTRACTION_COMPLETED: true,
  PER_TYPE_EXTRACTION_COMPLETED: true,
  FIGURE_COMPANY_COMPLETED: true,
  COMPANY_NAME_COMPLETED: true,
  FIGURE_TYPE_COMPLETED: true,
  AI_EXTRACTION_COMPLETED: true,
  SELECTION_COMPLETED: true,
  // [select-first 2026-08-31] docBaseDecide's selection gate answers select_base for any
  // non-COMPLETED doc without this flag — its name evolved past bare SELECTION_COMPLETED, and
  // without it every downstream-branch case measured select_base instead of its target
  // (measured: 50/61 uniform failures). Cases that TEST selection override it to false.
  BASE_SELECTION_COMPLETED: true,
  TYPE_SELECTION_COMPLETED: true,
  SEARCH_IN_DRIVE_COMPLETED: false,
  API_TOOLS_ID_COMPLETED: false,
  DOC_DATE_COMPLETED: false,
  DOC_TOTAL_AMOUNT_COMPLETED: false,
  PURCHASE_ID_COMPLETED: false,
  SHIPMENT_ID_COMPLETED: false,
  BS_EXTRACTED_LINES: null,
  BS_EXTRACTED_LINES_COMPLETED: false,
  BS_EXTRACTION_VERIFIED: false,
  BS_LINK_DOCUMENTS_COMPLETED: false,

};

function doc(label, expected_action, overrides, doc_type = 'invoice') {
  const id = overrides.ID !== undefined ? overrides.ID : BASE.ID;
  const companyName = overrides.COMPANY_NAME !== undefined ? overrides.COMPANY_NAME : BASE.COMPANY_NAME;
  
  let paddedId = 'EMPTY';
  let companyDocId = 'INV-EMPTY';
  let name = \`\${companyName}-EMPTY\`;

  if (id) {
    // Pad the ID to 5 digits so slice(-5) evaluates to just the numbers (e.g. 1001 -> 01001)
    paddedId = id.toString().padStart(5, '0');
    companyDocId = \`INV-\${paddedId}\`;
    name = \`\${companyName}-\${paddedId}\`;
  }

  // Prevent false positives for validations like get_short_doc_id and update_name
  // by ensuring default combos match what determineAction expects.
  const uniqueDefaults = {
    DOC_ID: companyDocId,
    SHORT_DOC_ID: paddedId,
    NAME: name,
    HASH: id ? \`hash-\${id}\` : null,
  };

  return {
    json: {
      label,
      expected_action,
      doc_type,
      ...BASE,
      ...uniqueDefaults,
      ...overrides,
      // [phase-4 2026-08-31] EVERY case names the test tenant: the Export Seed chain into
      // indoxV2Decide01 reads it, and Decide01's extraction_queries read now throws without it.
      __instance: 'test',
    }
  };
}

const cases = [

  // ── Base extraction gate (runs before every other docBase branch) ──
  // [value-based completion] __needsPerType answers false the moment a DOC_ID exists — the value
  // the extraction produces IS its completion, the flag is advisory. The helper mints DOC_ID from
  // the ID, so the case must blank it to reach the gate it asserts (2026-09-02: it did not, and
  // measured mark_completed — the machine was right, the fixture was stale).
  doc('has api_tools_id, per-type extraction not done → extract_per_type', 'extract_per_type',
    { PER_TYPE_EXTRACTION_COMPLETED: false, DOC_ID: '' }, 'invoice'),
  // [ping-pong rule 2026-08-25] base's extract gate accepts only TYPE-LESS docs — a typed doc
  // never re-runs base. The case is TYPE-less so it actually reaches the gate it asserts.
  // [typed-at-birth 2026-09-02] the gate's sentinel VALUE is now API_TOOLS_ID (a typed-at-birth
  // document still needs its upload + OCR), so the case must arrive WITHOUT one — BASE carries
  // 'at-999', and with it the honest verdict is missing-type, not another base pass.
  doc('TYPE-less with link, base not done → extract_base_doc', 'extract_base_doc',
    { TYPE: '', API_TOOLS_ID: '', BASE_EXTRACTION_COMPLETED: false, FIGURE_TYPE_COMPLETED: false }, 'unknown'),

  // ── Setup (Required for duplicate tests) ───────────────────────────────────
  // Process an initial doc so the subsequent duplicate tests have a target to match
  doc('setup doc -> process normally', 'mark_completed',
    { ID: '1001', STATUS: 'PROCESSING' }, 'invoice'),

  // ── No ID ──────────────────────────────────────────────────────────────────
  doc('no id → no_action_delete_row', 'no_action_delete_row',
    { ID: '' }, 'empty'),

  // ── Duplicate detection ────────────────────────────────────────────────────
  // Because these share ID: '1001', doc() will give them the same DOC_ID 
  // ('INV-01001') as the setup doc, correctly triggering the duplicate logic.
  // [SQL doubles 2026-08-18/23, owner design] Doubles are decided ONCE, in Decide01, from the
  // DRIVER's SQL flags (IS_DOUBLE / IS_MAIN_DOUBLE) — the in-memory detector is neutralised, so
  // a HASH/ID collision inside the case set proves nothing. The cases carry the flags the
  // driver would have stamped.
  doc('driver-flagged double, non-main, unmarked → update_status_double', 'update_status_double',
    { ID: '1001', IS_DOUBLE: true, IS_MAIN_DOUBLE: false, STATUS: '' }, null),  // doubles exit BEFORE routing — no DOC_TYPE stamped, by design

  doc('driver-flagged double, non-main, already DOUBLE → no_action_double', 'no_action_double',
    { ID: '1001', IS_DOUBLE: true, IS_MAIN_DOUBLE: false, STATUS: 'DOUBLE' }, null),

  // ── Status guards (pre-routing) ────────────────────────────────────────────
  // [resolve_double 2026-08-06] DOUBLE is terminal only while its EVIDENCE holds.
  // This row's STATUS says DOUBLE but nothing corroborates it: no duplicate in the
  // batch, and its (COMPANY_ID, DOC_ID) has never been adjudicated. Re-asserting
  // DOUBLE from the stale column alone is what made a WRONGLY-flagged row permanently
  // unrecoverable, so the row is now sent to adjudication instead. Terminality is NOT
  // lost: the 'duplicate already marked' case above still returns no_action_double
  // (dup.match holds), and so does an already-adjudicated row (merge_key stamped).
  doc('driver-flagged MAIN double, merge on → action_merge_doubles', 'action_merge_doubles',
    { ID: '9001', IS_DOUBLE: true, IS_MAIN_DOUBLE: true, __merge_enabled: true }, null),

  // The merge master toggle off = the survivor parks legibly instead of writing.
  doc('driver-flagged MAIN double, merge OFF → no_action_merge_blocked', 'no_action_merge_blocked',
    { ID: '9002b', IS_DOUBLE: true, IS_MAIN_DOUBLE: true, __merge_enabled: false }, null),

  doc('status=PAUSE → no_action_paused', 'no_action_paused',
    { ID: '9002', STATUS: 'PAUSE' }, 'invoice'),

  // ── No COMPANY_ID ──────────────────────────────────────────────────────────
  // [two-point rule 2026-08-17, asserted 2026-08-31] figure_company_id is RETIRED: company
  // resolution lives in the base pass only, so a companyless doc terminalizes
  // MISSING_COMPANY_ID regardless of the legacy flag. The flag staying false is the point of
  // this case now: it proves the flag no longer re-opens the legacy resolver.
  doc('no company (figure retired) → update_status_missing_company', 'update_status_missing_company',
    { ID: '9003', COMPANY_ID: '', FIGURE_COMPANY_COMPLETED: false }, 'invoice'),

  doc('no company, completed, wrong status → update_status_missing_company',
    'update_status_missing_company',
    { ID: '9004', COMPANY_ID: '', FIGURE_COMPANY_COMPLETED: true, STATUS: 'SOMETHING_ELSE' }, 'invoice'),

  doc('no company, completed, correct status → no_action_awaiting_company_id',
    'no_action_awaiting_company_id',
    { ID: '9005', COMPANY_ID: '', FIGURE_COMPANY_COMPLETED: true, STATUS: 'MISSING_COMPANY_ID' }, 'invoice'),

  // [restart precedence 2026-08-31] a typed doc's ACTION_RESTART is its own head's first rung.
  doc('no company, ACTION_RESTART → restart_gdoc (typed head first)', 'restart_gdoc',
    { ID: '9006', COMPANY_ID: '', FIGURE_COMPANY_COMPLETED: true, STATUS: 'ACTION_RESTART' }, 'invoice'),

  // ── No COMPANY_NAME ────────────────────────────────────────────────────────
  doc('no company name, not completed → get_company_name', 'get_company_name',
    { ID: '9007', COMPANY_NAME: '', COMPANY_NAME_COMPLETED: false }, 'invoice'),

  doc('no company name, completed, not unknown → update_status_unknwon_company',
    'update_status_unknwon_company',
    { ID: '9008', COMPANY_NAME: 'unknown', COMPANY_NAME_COMPLETED: true, STATUS: '' }, 'invoice'),

  doc('no company name, completed, status=UNKNOWN_COMPANY → no_action_awaiting_company_name',
    'no_action_awaiting_company_name',
    { ID: '9009', COMPANY_NAME: null, COMPANY_NAME_COMPLETED: true, STATUS: 'UNKNOWN_COMPANY' }, 'invoice'),

  // ── Unknown doc type ───────────────────────────────────────────────────────
  // [two-point rule 2026-08-17, asserted 2026-08-31] figure_document_type is RETIRED — the
  // TYPE stamp is unconditional in the base pass; an unknown type terminalizes MISSING_TYPE.
  doc('unknown type (figure retired) → update_status_missing_type', 'update_status_missing_type',
    { ID: '9010', TYPE: 'UNKNOWN_TYPE', FIGURE_TYPE_COMPLETED: false }, 'unknown'),

  // [restart precedence 2026-08-31] ACTION_RESTART is the FIRST rung: for a TYPE-less doc the
  // answer is restart_base (a fresh epoch — clears the *_COMPLETED flags, resets the budget),
  // and figure_document_type is what the FOLLOWING sweep answers once the flags are clear. The
  // old expectation predated restart-first and measured the gate order, not the design.
  doc('unknown type, ACTION_RESTART → restart_base (fresh epoch first)', 'restart_base',
    { ID: '9011', TYPE: 'UNKNOWN_TYPE', FIGURE_TYPE_COMPLETED: true, STATUS: 'ACTION_RESTART' }, 'unknown'),

  doc('unknown type, completed, wrong status → update_status_missing_type',
    'update_status_missing_type',
    { ID: '9012', TYPE: 'UNKNOWN_TYPE', FIGURE_TYPE_COMPLETED: true, STATUS: '' }, 'unknown'),

  doc('unknown type, status=MISSING_TYPE → no_action_unknown_document_type',
    'no_action_unknown_document_type',
    { ID: '9013', TYPE: 'UNKNOWN_TYPE', FIGURE_TYPE_COMPLETED: true, STATUS: 'MISSING_TYPE' }, 'unknown'),

  // ── gdoc branch ───────────────────────────────────────────────────────────
  // [asserted 2026-08-31] no_action_awating_doc_id is DEAD — a switch case nothing returns.
  // gdocHead's identity gates fire only when DOC_ID is present; a doc without one that is
  // otherwise done completes (the number is selection's to supply, not a completion blocker).
  doc('gdoc: no DOC_ID, otherwise done → mark_completed', 'mark_completed',
    { ID: '2001', DOC_ID: '', DOC_ID: '' }),

  doc('gdoc: STATUS=ACTION_RESTART → restart_gdoc', 'restart_gdoc',
    { ID: '2002', STATUS: 'ACTION_RESTART' }),

  doc('gdoc: DOC_ID present, wrong SHORT_DOC_ID → get_short_doc_id', 'get_short_doc_id',
    { ID: '2003', DOC_ID: 'INV/2026/12345', SHORT_DOC_ID: '99999' }),

  doc('gdoc: DOC_ID+SHORT canonical, wrong NAME → update_name', 'update_name',
    { ID: '2004', DOC_ID: 'INV/2026/12345', SHORT_DOC_ID: '12345', NAME: 'WrongName-00123' }),

  doc('gdoc: link=MISSING, drive not searched → find_link', 'find_link',
    { ID: '2005', LINK: 'MISSING', SEARCH_IN_DRIVE_COMPLETED: false }),

  doc('gdoc: link=MISSING, drive searched, wrong status → update_status_missing_link',
    'update_status_missing_link',
    { ID: '2006', LINK: 'MISSING', SEARCH_IN_DRIVE_COMPLETED: true, STATUS: 'OTHER' }),

  doc('gdoc: link=MISSING, drive searched, status=MISSING_LINK → no_action_link_not_found',
    'no_action_link_not_found',
    { ID: '2007', LINK: 'MISSING', SEARCH_IN_DRIVE_COMPLETED: true, STATUS: 'MISSING_LINK' }),

  // [missing link connection 2026-08-24, owner order] A LINK WITH NO LINK_CONNECTION IS A
  // MISSING LINK: drive api refuses automation calls without an explicit connection, so the
  // doc must re-search or park — never reach a file-backed step. These pin the clause in
  // every decide copy (gdoc had it since 08-13; shipment/invoice copies gained it today).
  doc('gdoc: link present, NO connection, not searched → find_link', 'find_link',
    { ID: '2007b', LINK: 'https://drive.google.com/file/d/x/view', LINK_CONNECTION: '',
      SEARCH_IN_DRIVE_COMPLETED: false }),

  doc('gdoc: link present, NO connection, searched, wrong status → update_status_missing_link',
    'update_status_missing_link',
    { ID: '2007c', LINK: 'https://drive.google.com/file/d/x/view', LINK_CONNECTION: '',
      SEARCH_IN_DRIVE_COMPLETED: true, STATUS: 'OTHER' }),

  doc('shipment: link present, NO connection, not searched → find_link', 'find_link',
    { ID: '2007d', TYPE: 'SHIPMENT', LINK: 'https://drive.google.com/file/d/x/view',
      LINK_CONNECTION: '', SEARCH_IN_DRIVE_COMPLETED: false }, 'shipment'),

  // [two-point rule 2026-08-12/17 + parking 2026-08-25, asserted 2026-08-31] The whole
  // per-field tail is RETIRED: get_api_tools_id (vestigial second uploader), the single-value
  // extractors (query_doc_date / query_doc_total_amount / query_purchase_id /
  // query_shipment_id — a THIRD extraction point beside pt2, measured dead), and the
  // missing-shipment status trio. Live design: a missing upload id PARKS as API_TOOLS_FAILED
  // when the flag is false; a flag set true means "the step ran" and absent per-field values
  // are ABSENT — never completion blockers. Re-extraction is an operator restart.
  doc('gdoc: no API_TOOLS_ID, flag false → parks as API_TOOLS_FAILED',
    'update_status_api_tools_failed',
    { ID: '2008', API_TOOLS_ID: null, API_TOOLS_ID_COMPLETED: false }),

  doc('gdoc: no API_TOOLS_ID, flag true → absent value does not block → mark_completed',
    'mark_completed',
    { ID: '2009', API_TOOLS_ID: null, API_TOOLS_ID_COMPLETED: true, STATUS: 'OTHER' }),

  doc('gdoc: parked API_TOOLS_FAILED, flag false → rests (no_action)',
    'no_action_api_tools_failed',
    { ID: '2010', API_TOOLS_ID: null, API_TOOLS_ID_COMPLETED: false, STATUS: 'API_TOOLS_FAILED' }),

  // [typed at birth 2026-09-03, owner Decision N8] The live shape of שריזלי-01010: born from a
  // balance-sheet line typed INVOICE, its file found in Drive, no OCR upload id yet, base never
  // run. Base's gate is now "no API_TOOLS_ID yet" (not "no TYPE"), so the document goes to base
  // extraction — upload + OCR + both legs — instead of parking as API_TOOLS_FAILED with no reason.
  doc('gdoc: typed at birth, linked, no API_TOOLS_ID, base not run → extract_base_doc',
    'extract_base_doc',
    { ID: '2010b', TYPE: 'INVOICE', API_TOOLS_ID: null, API_TOOLS_ID_COMPLETED: false,
      BASE_EXTRACTION_COMPLETED: false, BASE_SELECTION_COMPLETED: false }),

  // check_from_office lives in gdocHead's identity block — reachable only with a DOC_ID.
  doc('gdoc: DOC_ID set, no FROM_OFFICE_CHECK → check_from_office', 'check_from_office',
    { ID: '2011', DOC_ID: 'INV/2026/12345', SHORT_DOC_ID: '12345', NAME: 'Acme-12345',
      FROM_OFFICE_CHECK: null }),

  doc('gdoc: absent per-field values (date/amount/po/shipment) never block → mark_completed',
    'mark_completed',
    { ID: '2012', DOC_DATE: null, DOC_TOTAL_AMOUNT: null, PURCHASE_ID: null,
      SHIPMENT_DOC_ID: null }),

  doc('gdoc: all fields present, not completed → mark_completed', 'mark_completed',
    { ID: '2018', STATUS: 'PROCESSING' }),

  doc('gdoc: status=COMPLETED → no_action_already_completed', 'no_action_already_completed',
    { ID: '2019', STATUS: 'COMPLETED' }),

  // [two-point 2026-08-12, asserted 2026-08-31] extract_invoice_google_ai is RETIRED as a
  // standalone step: AI runs INSIDE point 1 (BaseDocEx01, local+AI in parallel), so a stale
  // AI flag alone no longer dispatches anything — the doc completes.
  doc('invoice: AI folded into base — stale AI flag alone → mark_completed', 'mark_completed',
    { ID: '20191', TYPE: 'INVOICE', AI_EXTRACTION_COMPLETED: false}),

  // [selection architecture] per-type selection is select_type (SelectType01) — the old
  // select_invoice_values name retired with the per-type split.
  doc('invoice: type selection owed → select_type', 'select_type',
    { ID: '20192', TYPE: 'INVOICE', SELECTION_COMPLETED: false, TYPE_SELECTION_COMPLETED: false }),
  
  // ── bs_doc branch ─────────────────────────────────────────────────────────
  doc('bs_doc: STATUS=ACTION_RESTART → restart_balance_sheet', 'restart_balance_sheet',
    { ID: '3001', TYPE: 'BALANCE_SHEET', STATUS: 'ACTION_RESTART',
      BS_EXTRACTED_LINES: null }, 'bs_doc'),

  // [two-point enforcement 2026-08-12, asserted 2026-08-31] extract_balance_sheet is RETIRED:
  // BS extraction is pt2's (BsDocEx01). With pt2 done and no lines, the honest answer is the
  // failed terminal — a second direct-AI extraction point is exactly what 08-12 removed.
  doc('bs_doc: no lines, pt2 done → update_status_extraction_failed', 'update_status_extraction_failed',
    { ID: '3002', TYPE: 'BALANCE_SHEET', BS_EXTRACTED_LINES: null,
      BS_EXTRACTED_LINES_COMPLETED: false }, 'bs_doc'),

  doc('bs_doc: no lines, completed, wrong status → update_status_extraction_failed',
    'update_status_extraction_failed',
    { ID: '3003', TYPE: 'BALANCE_SHEET', BS_EXTRACTED_LINES: null,
      BS_EXTRACTED_LINES_COMPLETED: true, STATUS: 'OTHER' }, 'bs_doc'),

  doc('bs_doc: no lines, status=EXTRACTION_FAILED → no_action_extraction_failed',
    'no_action_extraction_failed',
    { ID: '3004', TYPE: 'BALANCE_SHEET', BS_EXTRACTED_LINES: null,
      BS_EXTRACTED_LINES_COMPLETED: true, STATUS: 'EXTRACTION_FAILED' }, 'bs_doc'),

  doc('bs_doc: lines present, not verified → update_status_extraction_failed',
    'update_status_extraction_failed',
    { ID: '3005', TYPE: 'BALANCE_SHEET', BS_EXTRACTED_LINES: '...data...',
      BS_EXTRACTION_VERIFIED: false, STATUS: 'OTHER' }, 'bs_doc'),

  doc('bs_doc: verified, docs not linked → link_documents', 'link_documents',
    { ID: '3006', TYPE: 'BALANCE_SHEET', BS_EXTRACTED_LINES: '...data...',
      BS_EXTRACTION_VERIFIED: true, BS_LINK_DOCUMENTS_COMPLETED: false }, 'bs_doc'),

  doc('bs_doc: all done, not completed → mark_completed', 'mark_completed',
    { ID: '3007', TYPE: 'BALANCE_SHEET', BS_EXTRACTED_LINES: '...data...',
      BS_EXTRACTION_VERIFIED: true, BS_LINK_DOCUMENTS_COMPLETED: true,
      STATUS: 'PROCESSING' }, 'bs_doc'),

  doc('bs_doc: status=COMPLETED → no_action_already_completed', 'no_action_already_completed',
    { ID: '3008', TYPE: 'BALANCE_SHEET', BS_EXTRACTED_LINES: '...data...',
      BS_EXTRACTION_VERIFIED: true, BS_LINK_DOCUMENTS_COMPLETED: true,
      STATUS: 'COMPLETED' }, 'bs_doc'),

  // ── parked lanes: order + receipt ─────────────────────────────────────────
  // [five classes 2026-08-27] These types are RECORDED, not PROCESSED: base resolves
  // COMPANY_ID/TYPE/DOC_DATE and the lane does nothing else. The cases below pin the whole
  // contract — one executable action, the right class, and no path back into the invoice
  // pipeline. The 'no per-type, no sync' half is proven by ABSENCE, so it is asserted E2E in
  // indoxV2GDocTest01's batch:ord / batch:rcp lanes (no extract_per_type / select_type /
  // action_priority_sync row in indox_action_execution_log), not here.
  doc('order: not completed → mark_completed', 'mark_completed',
    { ID: '4001', TYPE: 'ORDER', STATUS: 'PROCESSING' }, 'order'),

  doc('order: status=COMPLETED → no_action_already_completed', 'no_action_already_completed',
    { ID: '4002', TYPE: 'ORDER', STATUS: 'COMPLETED' }, 'order'),

  // The restart contract: no restart_* action exists in a parked lane, and none is needed.
  // ACTION_RESTART !== 'COMPLETED', so the lane answers mark_completed and the row LANDS.
  // Writing ACTION_RESTART already moved indox_line_hash(), so this is not a double action.
  doc('order: STATUS=ACTION_RESTART → mark_completed (terminates, no ping-pong)', 'mark_completed',
    { ID: '4003', TYPE: 'ORDER', STATUS: 'ACTION_RESTART' }, 'order'),

  doc('order: STATUS=MERGED → no_action_merged (MERGED stays absorbing)', 'no_action_merged',
    { ID: '4004', TYPE: 'ORDER', STATUS: 'MERGED' }, 'order'),

  doc('receipt: not completed → mark_completed', 'mark_completed',
    { ID: '5001', TYPE: 'RECEIPT', STATUS: 'PROCESSING' }, 'receipt'),

  doc('receipt: status=COMPLETED → no_action_already_completed', 'no_action_already_completed',
    { ID: '5002', TYPE: 'RECEIPT', STATUS: 'COMPLETED' }, 'receipt'),

  doc('receipt: STATUS=ACTION_RESTART → mark_completed (terminates)', 'mark_completed',
    { ID: '5003', TYPE: 'RECEIPT', STATUS: 'ACTION_RESTART' }, 'receipt'),

  doc('receipt: STATUS=MERGED → no_action_merged', 'no_action_merged',
    { ID: '5004', TYPE: 'RECEIPT', STATUS: 'MERGED' }, 'receipt'),

  // The class rename, asserted: INVOICE must land on 'invoice', never the retired 'gdoc'.
  doc('invoice: class is invoice, not gdoc', 'mark_completed',
    { ID: '4101', TYPE: 'INVOICE', STATUS: 'PROCESSING' }, 'invoice'),

  // And an unrecognised type still terminalises — the unknown fallback is unchanged.
  doc('unknown type: still → update_status_missing_type', 'update_status_missing_type',
    { ID: '4102', TYPE: 'SOMETHING_ELSE', STATUS: 'PROCESSING' }, 'unknown'),

];

return cases;`,
    };

    @node({
        id: 'v2t-call',
        name: 'Execute Decide',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [480, 0],
    })
    ExecuteDecide = {
        workflowId: {
            __rl: true,
            value: 'indoxV2Decide01',
            mode: 'id',
            cachedResultName: 'indox-v2 Decide',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {},
    };

    @node({
        id: 'v2t-assert',
        name: 'Determine Action Test Assertions',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [720, 0],
    })
    DetermineActionTestAssertions = {
        jsCode: `// ─── Assertion node (runs after determineAction) ──────────────────────────
// [DOC_TYPE asserted 2026-08-27] Every case has always carried doc_type -- the header comment
// calls it "expected DOC_TYPE" -- and nothing ever compared it. DOC_TYPE is what
// indoxV2ActionRouter01's Switch1 routes on, so a wrong class does not fail here, it dispatches
// the document to the WRONG LANE in production. That gap is why this is asserted now: the
// five-class split (invoice/shipment/bs_doc/order/receipt) is exactly a DOC_TYPE change, and a
// suite that only checks ACTION would have called it green either way.
return $input.all().map(item => {
  const expected = item.json.expected_action;
  const actual   = item.json.ACTION;
  const expType  = item.json.doc_type;
  const actType  = item.json.DOC_TYPE;
  const actOk    = actual === expected;
  const typeOk   = expType == null || actType === expType;
  const pass     = actOk && typeOk;

  const why = actOk
    ? \`✗ FAIL — DOC_TYPE expected: \${expType}, got: \${actType}\`
    : \`✗ FAIL — expected: \${expected}, got: \${actual}\`;

  return {
    json: {
      pass,
      result: pass ? '✓ PASS' : why,
      ...item.json,


    }
  };
});`,
    };

    @node({
        id: 'v2t-summary',
        name: '🏁 Test Summary',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [940, 0],
    })
    TestSummary = {
        jsCode: `// The harness contract (apps/indox/hooks/test.py fetch_summary): a node named with 🏁 /
// 'Test Summary' returning ONE item {RESULT, passed:'N/M', checks:[...]} — same shape as
// DocBaseTest01's. Without it the scorecard reports ❌ NO SUMMARY on a suite whose every case
// passed, which is how this suite's first post-cutover run read as dead while executions
// 3735063-3735070 (decide + all five typed lanes) were green.
const items = $input.all().map(i => i.json);
const fails = items.filter(x => !x.pass);
const checks = items.map(x => (x.pass ? '✅ ' : '❌ ') + (x.label || x.expected_action) + (x.pass ? '' : ' — ' + x.result));
return [{ json: {
  RESULT: fails.length ? ('❌ ' + fails.length + ' OF ' + items.length + ' DECIDE CASES FAILED') : '✅ ALL TESTS PASS',
  passed: (items.length - fails.length) + '/' + items.length,
  checks,
} }];`,
    };

    @node({
        id: 'v2t-lane-webhook',
        webhookId: 'decide-e2e-lane',
        name: 'Lane Webhook',
        /*__n8n__*/ notes: "[ui-lane 2026-08-31] The console's בדיקות tab runs suites through webhook lanes (BFF _run_one_lane POSTs {lane} and reads back items whose `result` contains PASS). This suite is one lane ('all'): same graph the CLI runs, entered here instead of the manual trigger. The body carries no tenant — Config-side logic mints 'test' (pin-is-dead).",
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [0, 200],
    })
    LaneWebhook = {
        httpMethod: 'POST',
        path: 'decide-e2e-lane',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'v2t-lane-verdict',
        name: 'Lane Verdict',
        /*__n8n__*/ notes: "[ui-lane 2026-08-31] Shim between the harness contract (🏁 emits RESULT/passed/checks for fetch_summary) and the webhook contract (the BFF looks for lowercase `result` containing PASS). One item in, one item out.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1160, 200],
    })
    LaneVerdict = {
        jsCode: "const j=$json; return [{json:{result:String(j.RESULT||'')+' ('+String(j.passed||'')+')', checks:j.checks||[]}}];",
    };

    @node({
        id: 'v2t-lane-respond',
        name: 'Respond Lane',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [1380, 200],
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
        this.RunTests.out(0).to(this.DetermineActionTests.in(0));
        this.DetermineActionTests.out(0).to(this.ExecuteDecide.in(0));
        this.ExecuteDecide.out(0).to(this.DetermineActionTestAssertions.in(0));
        this.DetermineActionTestAssertions.out(0).to(this.TestSummary.in(0));
        this.LaneWebhook.out(0).to(this.DetermineActionTests.in(0));
        this.TestSummary.out(0).to(this.LaneVerdict.in(0));
        this.LaneVerdict.out(0).to(this.RespondLane.in(0));
    }
}
