import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox-v2 Decide
// Nodes   : 15  |  Connections: 14
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenCalled                         executeWorkflowTrigger
// ExportSeedDocBase                  set                        [executeOnce]
// CallExportDocBase                  executeWorkflow
// ExportSeedGdoc                     set                        [executeOnce]
// CallExportGdoc                     executeWorkflow
// ExportSeedShipment                 set                        [executeOnce]
// CallExportShipment                 executeWorkflow
// ExportSeedBs                       set                        [executeOnce]
// CallExportBs                       executeWorkflow
// ExportSeedOrder                    set                        [executeOnce]
// CallExportOrder                    executeWorkflow
// ExportSeedReceipt                  set                        [executeOnce]
// CallExportReceipt                  executeWorkflow
// LoadCompanyResolverGen             postgres                   [onError→regular] [creds] [alwaysOutput] [executeOnce]
// MegaDecide                         code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → ExportSeedDocBase
//      → CallExportDocBase
//        → ExportSeedGdoc
//          → CallExportGdoc
//            → ExportSeedShipment
//              → CallExportShipment
//                → ExportSeedBs
//                  → CallExportBs
//                    → ExportSeedOrder
//                      → CallExportOrder
//                        → ExportSeedReceipt
//                          → CallExportReceipt
//    → LoadCompanyResolverGen
//      → MegaDecide
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"Export Seed (doc_base)","type":"main","index":0},{"node":"Load Company Resolver Gen","type":"main","index":0}]]},"Export Seed (doc_base)":{"main":[[{"node":"Call Export (doc_base)","type":"main","index":0}]]},"Call Export (doc_base)":{"main":[[{"node":"Export Seed (gdoc)","type":"main","index":0}]]},"Export Seed (gdoc)":{"main":[[{"node":"Call Export (gdoc)","type":"main","index":0}]]},"Call Export (gdoc)":{"main":[[{"node":"Export Seed (shipment)","type":"main","index":0}]]},"Export Seed (shipment)":{"main":[[{"node":"Call Export (shipment)","type":"main","index":0}]]},"Call Export (shipment)":{"main":[[{"node":"Export Seed (bs)","type":"main","index":0}]]},"Export Seed (bs)":{"main":[[{"node":"Call Export (bs)","type":"main","index":0}]]},"Call Export (bs)":{"main":[[{"node":"Export Seed (order)","type":"main","index":0}]]},"Load Company Resolver Gen":{"main":[[{"node":"Mega Decide","type":"main","index":0}]]},"Export Seed (order)":{"main":[[{"node":"Call Export (order)","type":"main","index":0}]]},"Call Export (order)":{"main":[[{"node":"Export Seed (receipt)","type":"main","index":0}]]},"Export Seed (receipt)":{"main":[[{"node":"Call Export (receipt)","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"1a1f9021-970c-46eb-8cef-4746d2dca0d0","name":"indox-state-machine-v2"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"22f1e71e-91bf-48db-811f-8d3bc4e55a3e","name":"sm-refactor-v2.1"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"2b5cb873-dd65-44dd-bf27-a2c99d2b81a4","name":"state-machine-v2"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:41:29.646Z","createdAt":"2026-07-30T23:41:29.646Z","id":"9c337cfe-7feb-4f3d-ab26-3de6439357ce","name":"sm-refactore-v2.1"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {"templateCredsSetupCompleted":true},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"indoxV2Decide01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2Decide01',
    name: 'indox-v2 Decide',
    active: true,
    isArchived: false,
    tags: [
        'indox-state-machine-v2',
        'sm-refactor-v2.1',
        'state-machine-v2',
        'app:indox',
        'sm-refactore-v2.1',
        'indox',
        'indox-app',
    ],
    settings: { executionOrder: 'v1', errorWorkflow: 'errorHandler01', binaryMode: 'separate' },
})
export class IndoxV2DecideWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'v2d-trig',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, -128],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'exp-seed-doc_base',
        name: 'Export Seed (doc_base)',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [224, -128],
        executeOnce: true,
    })
    ExportSeedDocBase = {
        assignments: {
            assignments: [
                {
                    id: 's1',
                    name: 'mode',
                    value: 'export_decide',
                    type: 'string',
                },
                {
                    id: 's-instance',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'exp-call-doc_base',
        name: 'Call Export (doc_base)',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [448, -128],
    })
    CallExportDocBase = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ActionsGlobal01',
            mode: 'id',
            cachedResultName: 'indox-v2 Actions — DOC BASE',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'exp-seed-gdoc',
        name: 'Export Seed (gdoc)',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [672, -128],
        executeOnce: true,
    })
    ExportSeedGdoc = {
        assignments: {
            assignments: [
                {
                    id: 's1',
                    name: 'mode',
                    value: 'export_decide',
                    type: 'string',
                },
                {
                    id: 's-instance',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'exp-call-gdoc',
        name: 'Call Export (gdoc)',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [896, -128],
    })
    CallExportGdoc = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ActionsInv01',
            mode: 'id',
            cachedResultName: 'indox-v2 Actions — Invoice',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
            value: {},
            matchingColumns: [],
            schema: [],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'exp-seed-shipment',
        name: 'Export Seed (shipment)',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1120, -128],
        executeOnce: true,
    })
    ExportSeedShipment = {
        assignments: {
            assignments: [
                {
                    id: 's1',
                    name: 'mode',
                    value: 'export_decide',
                    type: 'string',
                },
                {
                    id: 's-instance',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'exp-call-shipment',
        name: 'Call Export (shipment)',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1344, -128],
    })
    CallExportShipment = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ActionsShip01',
            mode: 'id',
            cachedResultName: 'indox-v2 Actions — Shipment',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'exp-seed-bs',
        name: 'Export Seed (bs)',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1568, -128],
        executeOnce: true,
    })
    ExportSeedBs = {
        assignments: {
            assignments: [
                {
                    id: 's1',
                    name: 'mode',
                    value: 'export_decide',
                    type: 'string',
                },
                {
                    id: 's-instance',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'exp-call-bs',
        name: 'Call Export (bs)',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1792, -128],
    })
    CallExportBs = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ActionsBS01',
            mode: 'id',
            cachedResultName: 'indox-v2 Actions — BS',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'exp-seed-order',
        name: 'Export Seed (order)',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [2016, -128],
        executeOnce: true,
    })
    ExportSeedOrder = {
        assignments: {
            assignments: [
                {
                    id: 's1',
                    name: 'mode',
                    value: 'export_decide',
                    type: 'string',
                },
                {
                    id: 's-instance',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'exp-call-order',
        name: 'Call Export (order)',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2240, -128],
    })
    CallExportOrder = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ActionsOrd01',
            mode: 'id',
            cachedResultName: 'indox-v2 Actions — Order',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'exp-seed-receipt',
        name: 'Export Seed (receipt)',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [2464, -128],
        executeOnce: true,
    })
    ExportSeedReceipt = {
        assignments: {
            assignments: [
                {
                    id: 's1',
                    name: 'mode',
                    value: 'export_decide',
                    type: 'string',
                },
                {
                    id: 's-instance',
                    name: '__instance',
                    value: '={{ $(\'When Called\').first().json.__instance || "" }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'exp-call-receipt',
        name: 'Call Export (receipt)',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [2688, -128],
    })
    CallExportReceipt = {
        workflowId: {
            __rl: true,
            value: 'indoxV2ActionsRcp01',
            mode: 'id',
            cachedResultName: 'indox-v2 Actions — Receipt',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'mega-resolver-gen',
        name: 'Load Company Resolver Gen',
        /*__n8n__*/ notes: "Mirror of the doc_base router's resolver-gen load so __RESGEN() inside the rehydrated doc_base decide resolves identically. executeOnce; 1-row output — the batch rides $('When Called').",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [208, 80],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
        executeOnce: true,
    })
    LoadCompanyResolverGen = {
        operation: 'executeQuery',
        query: "=SELECT COALESCE((SELECT resolver_gen FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2Decide01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.extraction_queries WHERE key='q_v3_company'), '') AS resolver_gen_company",
        options: {},
    };

    @node({
        id: 'mega-decide-01',
        name: 'Mega Decide',
        /*__n8n__*/ notes: "[prod port 2026-08-18, owner design] The whole decide in ONE code task — rehydrated router functions, full-row contract unchanged. Why: 8 concurrent graph-path decides took 15.5 min each (runner-task saturation) and blew the drivers' Bull locks; one task per decide removes that burst. See code header.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [432, 80],
    })
    MegaDecide = {
        jsCode: `// [decide-prod mega port 2026-08-18, owner design] THE production decide, one-hop.
// Decide logic lives ONLY in the four routers; the Call Export nodes fetched each node's own
// source (mode='export_decide') and new Function rehydrates them here with this node's
// $/$execution. OUTPUT CONTRACT UNCHANGED: the full normalized rows with ACTION/DOC_TYPE
// (+IS_OLD/OLD_REASON/_dup where written) — exactly what the graph path returned.
// Why: at split 8/16 the old graph path (~6 full-batch code tasks per decide) saturated the
// task runners — 8 concurrent decides took 15.5 min EACH and the drivers blew their Bull
// locks (cycle 2026-08-18, drivers error at ~2950s). One task per decide removes that burst.
const __mkFn = (src, name) => new Function('$', '$execution', src + '; return ' + name + ';')($, $execution);
const __run_doc_base = __mkFn($('Call Export (doc_base)').first().json.fnSrc, '__docBaseDecideFn');
const __run_gdoc = __mkFn($('Call Export (gdoc)').first().json.fnSrc, '__gdocDecideFn');
const __run_shipment = __mkFn($('Call Export (shipment)').first().json.fnSrc, '__shipDecideFn');
const __run_bs = __mkFn($('Call Export (bs)').first().json.fnSrc, '__bsDecideFn');
// [five classes 2026-08-27] ORDER and RECEIPT are their own lanes now — parked types whose
// decide is one line each, but rehydrated through exactly the same export contract as the
// other four so decide logic still lives ONLY in the routers.
const __run_order = __mkFn($('Call Export (order)').first().json.fnSrc, '__orderDecideFn');
const __run_receipt = __mkFn($('Call Export (receipt)').first().json.fnSrc, '__receiptDecideFn');

const __runDetermine = async function(__b) {
// [mega-decide 2026-08-18] Determine Action, re-authored ASYNC + CHUNKED from the folded
// production version (same semantics, same order: stamp -> normalize -> census -> per-row
// dedup/_log/mode/drop). Chunked with event-loop yields so the runner launcher's liveness
// pings are answered during 100k-row passes. Dedup maps and the bizKey census are
// batch-stateful: state lives across chunks; iteration order is unchanged.
const __DA_CHUNK = 10000;
const __daYield = () => new Promise(r => setImmediate(r));

// ---- stamp (was the 'Execution Data (decide)' node; computed once, raw first item) ----
{
  const __a = __b;
  const __f = (__a[0] || {}).json || {};
  const __ids = __a.map(i => String((i.json && i.json.ID) != null ? i.json.ID : '')).filter(Boolean);
  const __s = __ids.slice().sort();
  let __h = 2166136261;
  for (const __v of __s) { for (let __k = 0; __k < __v.length; __k++) { __h ^= __v.charCodeAt(__k); __h = Math.imul(__h, 16777619); } }
  const __u = [...new Set(__a.map(i => String((i.json && i.json.ACTION) != null ? i.json.ACTION : '')).filter(Boolean))];
  const __sj = __u.join(',');
  let __m = 'execute'; try { __m = String(__f.mode || 'execute'); } catch (e) { __m = 'execute'; }
  const __cap = (v) => String(v).slice(0, 500);
  $execution.customData.setAll({
    exection_type: 'decide',
    trigger_type: __cap(__f.TRIGGER_TYPE || __f.trigger_type || 'sub_workflow'),
    trigger_chain: __cap(__f.TRIGGER_CHAIN || 'driver>decide'),
    origin_execution: __cap(__f.ORIGIN_EXECUTION || $execution.id),
    parent_execution: __cap(__f.PARENT_EXECUTION || ''),
    line_count: String(__a.length),
    ids: __cap('n=' + __ids.length + ' h=' + (__h >>> 0).toString(16) + ' s=' + __s.slice(0, 3).join(',')),
    actions: __cap(__sj.length > 380 ? (__u.length + ' actions: ' + __sj.slice(0, 360) + '...') : __sj),
    outline: __cap('decide_' + __m + '_x_' + __a.length + '_lines_x_' + __u.length + '_actions'),
  });
}
await __daYield();

const processedDocs = { byId:new Map(), byHash:new Map(), byCompanyShortDoc:new Map() };
function isBlank(val) {
  return [null, undefined, '', 'unknown'].includes(
    (String(val ?? '')).toLowerCase()
  );
}
function isPlaceholderDocId(val) {
  if (isBlank(val)) return false;
  return /^0+$/.test(String(val).trim());
}
function compositeKey(companyId, shortDocId) {
  return companyId + '_' + shortDocId;
}
function checkDuplicate(doc) {
  const id   = doc.ID   ? processedDocs.byId.get(doc.ID)     : undefined;
  const hash = (doc.HASH && isBlank(doc.LINKED_BS)) ? processedDocs.byHash.get(doc.HASH) : undefined;
  const comp = (doc.COMPANY_ID && doc.SHORT_DOC_ID && !isPlaceholderDocId(doc.SHORT_DOC_ID))
    ? processedDocs.byCompanyShortDoc.get(compositeKey(doc.COMPANY_ID, doc.SHORT_DOC_ID))
    : undefined;
  const matchedId = id ?? hash ?? comp;
  return { idMatch: id, hashMatch: hash, compShortDocMatch: comp, match: matchedId !== undefined, matchedId };
}
function trackDoc(doc) {
  const id = String(doc.ID);
  if (doc.ID)                              processedDocs.byId.set(doc.ID, id);
  if (doc.HASH && isBlank(doc.LINKED_BS)) processedDocs.byHash.set(doc.HASH, id);
  if (doc.COMPANY_ID && doc.SHORT_DOC_ID && !isPlaceholderDocId(doc.SHORT_DOC_ID))
    processedDocs.byCompanyShortDoc.set(compositeKey(doc.COMPANY_ID, doc.SHORT_DOC_ID), id);
}
function excelSerialToDate(serial) {
  const excelEpoch = new Date(Date.UTC(1899, 11, 30));
  const msPerDay = 24 * 60 * 60 * 1000;
  const date = new Date(excelEpoch.getTime() + serial * msPerDay);
  const day = String(date.getUTCDate()).padStart(2, "0");
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const year = date.getUTCFullYear();
  return day + '/' + month + '/' + year;
}

// ---- normalization (the two production passes fused into ONE key loop; same outcomes:
// blank/undefined -> null, "true"/"false" -> bool, numeric *DATE* -> excel date) ----
const __items = __b;
for (let __i = 0; __i < __items.length; __i++) {
  const item = __items[__i];
  for (const key of Object.keys(item.json)) {
    const value = item.json[key];
    if (value === "" || value === undefined) { item.json[key] = null; continue; }
    if (typeof value === "string") {
      const _s = value.trim().toLowerCase();
      if (_s === "true") item.json[key] = true; else if (_s === "false") item.json[key] = false;
    } else if (typeof value === "number" && !isNaN(value) && key.toUpperCase().includes("DATE")) {
      item.json[key] = excelSerialToDate(value);
    }
  }
  if (__i % __DA_CHUNK === __DA_CHUNK - 1) await __daYield();
}
await __daYield();

const BIZ_SEP = '';
function bizDocIdOf(doc) {
  const v = !isBlank(doc.DOC_ID) ? doc.DOC_ID : null;
  if (isBlank(v)) return null;
  const s = String(v).trim();
  if (['unknown','action_required','null','none'].includes(s.toLowerCase())) return null;
  const alnum = s.replace(/[^a-zA-Z0-9]/g, '');
  if (alnum.length < 3 || /^0+$/.test(alnum)) return null;
  if (!isBlank(doc.COMPANY_ID) && String(doc.COMPANY_ID).trim() === s) return null;
  return s;
}

// ---- bizKey census REMOVED: doubles are detected by the driver's SQL ----

// ---- per-row: mode + _log (preserve caller-derived) + drop cols + dedup + bizCollision ----
// [dead 2026-08-21] __DROP_COLS was declared here and never read -- the '[prod port] NO column
// drop' note below says why: single-node execution keeps no inter-node copies, so nothing was
// ever dropped. It named ACTION_LOG first, which is what surfaced it during that column's
// removal. Removed rather than edited: an unused list of column names is a trap, not a record.
const __out = [];
for (let __i = 0; __i < __items.length; __i++) {
  const item = __items[__i];
  item.json.mode = 'decide';
  // [_log removed 2026-08-20] This block used to precompute a doc._log = {gmailLabeled,
  // failedFoldered, iterCount} and hand it to indoxV2ActionsGlobal01 :: __logInfo, purely so that
  // ACTION_LOG -- the fattest column on the table, 20MB of 73MB -- was parsed once per row here
  // instead of again there. All three are plain column reads now
  // (GMAIL_LABELS_COMPLETED / FAILED_FOLDER_COMPLETED / ITERATION_COUNT), so there is nothing left
  // to precompute and the indirection is pure cost: __logInfo reads the same three columns off the
  // row it already has. Deleting it also removes the failure mode the old comment warned about --
  // __logInfo preferred doc._log when present, so a _log that drifted out of step silently beat the
  // correct value.
  // [prod port] NO column drop: single-node execution retains no inter-node copies,
  // and the caller contract is the full normalized row.
  // [perf] the production version spread item.json into a fresh nd just to stringify ID —
  // 100k big-object allocations. Stringify in place instead: every consumer (dup maps,
  // verdict output, caller join) already stringifies ID, so the observable contract is equal.
  const nd = item.json;
  if (nd.ID != null) nd.ID = String(nd.ID);
  // [SQL doubles 2026-08-18, owner design] Detection is the DRIVER's SQL (IS_DOUBLE /
  // IS_MAIN_DOUBLE / LINES_TO_MERGE arrive on the row). _dup is neutralised so the routers'
  // in-memory detector can never fire alongside it. This is what removes decide's last
  // batch-stateful dependency: every remaining line is per-row, so batch size cannot change
  // a verdict (proven 1k vs 5k vs one-shot -> identical verdict hash 53ed22b3).
  item.json._dup = (nd.STATUS === 'MERGED') ? { match: false, merged: true } : { match: false };
  __out.push(item);
  if (__i % __DA_CHUNK === __DA_CHUNK - 1) await __daYield();
}
return __out;
};

const __CHUNK = 10000;
const __yield = () => new Promise(r => setImmediate(r));
function __pushAll(dst, src) { for (const x of src) dst.push(x); }
const __T = { start: Date.now() };
const __batch = $('When Called').all();
const __norm = await __runDetermine(__batch);
await __yield();
__T.da = Date.now();
// [SQL doubles 2026-08-18, owner design] The LAST-created line of a duplicate group is the
// survivor: it merges the others into itself. Older lines are parked on
// no_action_waiting_for_merge and do nothing until the survivor marks them MERGED — after
// which the detector stops seeing them and Determine Action returns no_action_merged.
// The merge itself is behind a settings toggle (__merge_enabled, carried on the row by the
// driver's enrich query). While it is off the survivor returns no_action_merge_blocked, so a
// full drain can reach a final state on every line WITHOUT any merge writing data yet.
const __toRoute = [], __dblOut = [];
const __B = (x) => (x === true || x === 'true' || x === 't');
for (const __it of __norm) {
  const __j = (__it && __it.json) || {};
  if (__B(__j.IS_DOUBLE)) {
    // [owner rule 2026-08-23] The whole doubles gate:
    //   main     -> merge (or no_action_merge_blocked while the toggle is off)
    //   not main -> flag it DOUBLE once, then say nothing further
    // A non-main used to sit on no_action_waiting_for_merge, which is invisible in the table:
    // the row looked like ordinary in-flight work with no indication it was a parked duplicate.
    // Flagging STATUS='DOUBLE' makes the wait legible without changing termination, which is
    // still the terminal status: the survivor writes MERGED on the others, MERGED leaves the
    // detector's universe, grp_n falls to 1, and nobody is double any more.
    // MERGED IS ABSORBING, AND NOTHING MAY TOUCH IT. Today a merged row cannot reach here --
    // the detector's universe excludes MERGED, so IS_DOUBLE is never true for one -- but that is
    // a property of a SQL query two workflows away, and if it ever changes this ternary would
    // write STATUS='DOUBLE' over a MERGED row. That un-merges it, puts it back in the universe,
    // and the group re-forms: merge -> DOUBLE -> merge, forever, with the merge provenance
    // (MERGED_INTO / MERGE_BATCH_ID) still on the row claiming it was absorbed. Guard it here so
    // the invariant holds locally and does not depend on a distant query staying correct.
    const __st = String(__j.STATUS || '');
    __j.ACTION = (__st === 'MERGED')
      ? 'no_action_merged'
      : __B(__j.IS_MAIN_DOUBLE)
        ? (__B(__j.__merge_enabled) ? 'action_merge_doubles' : 'no_action_merge_blocked')
        : (__st === 'DOUBLE' ? 'no_action_double' : 'update_status_double');
    __dblOut.push(__it);
  } else {
    __toRoute.push(__it);
  }
}
__norm.length = 0;
for (const __x of __toRoute) __norm.push(__x);

const __base = [];
for (let __i = 0; __i < __norm.length; __i += __CHUNK) {
  __pushAll(__base, __run_doc_base(__norm.slice(__i, __i + __CHUNK)));
  await __yield();
}
__T.docbase = Date.now();
// [five classes 2026-08-27] '__route_gdoc__' is '__route_invoice__' — the class held INVOICE
// and ORDER, ORDER left, so the name now says what is in it. Two new sentinels for the two
// parked lanes. The split is a plain map lookup so a sixth class cannot be added to the
// sentinel table (indoxV2ActionsGlobal01 :: _ROUTE) and forgotten here.
const __byRoute = {
  __route_bs__: [], __route_invoice__: [], __route_shipment__: [],
  __route_order__: [], __route_receipt__: [],
};
const __direct = [];
for (const it of __base) {
  const a = ((it && it.json) || {}).ACTION;
  if (__byRoute[a]) __byRoute[a].push(it);
  else __direct.push(it);
}
const __outs = __direct;
for (const __d of __dblOut) __outs.push(__d);
for (const [__fn, __rows] of [
  [__run_bs, __byRoute.__route_bs__],
  [__run_gdoc, __byRoute.__route_invoice__],
  [__run_shipment, __byRoute.__route_shipment__],
  [__run_order, __byRoute.__route_order__],
  [__run_receipt, __byRoute.__route_receipt__],
]) {
  for (let __i = 0; __i < __rows.length; __i += __CHUNK) {
    __pushAll(__outs, __fn(__rows.slice(__i, __i + __CHUNK)));
    await __yield();
  }
}
__T.out = Date.now();
$execution.customData.set('timings', ('n=' + __batch.length
  + ' da=' + (__T.da - __T.start)
  + ' docbase=' + (__T.docbase - __T.da)
  + ' pertype+out=' + (__T.out - __T.docbase)
  + ' totalms=' + (__T.out - __T.start)).slice(0, 500));
// ── MINIMAL RETURN CONTRACT [owner order 2026-08-18] ────────────────────────────────────────
// Decide returns the DECISION, not the document. The caller keeps the rows it sent and merges
// these keys onto them by ID (indoxV2Driver01 -> "Merge Verdicts").
//
// Why: under the old full-row contract the caller had to hold TWO copies of the set — the one
// it sent and the one it got back. Measured on this table: 38,955 rows = 74MB on disk, ~1,983
// B/row, which inflates ~25-35x as JS objects, so each copy is 1.5-2GB. The caller died at the
// Call Decide step at 2.5G, 3.25G, 4G AND 6G ceilings (six runs) while decide itself succeeded
// every time in 47-88s. Returning ~5 short keys instead of ~110 columns removes the second copy.
//
// The list is DECISIONS only, and it is MEASURED, not guessed. A field-level diff of decide's
// own input vs output over all 38,958 rows (execution 3398360) found 38 fields differing. 30 of
// them differ by TYPE COERCION ONLY — Postgres returns the flags as the strings 'true'/'false'
// and decide casts them to booleans. Verified transition census, e.g.:
//     BASE_EXTRACTION_COMPLETED   'true' -> true (27,951)   'false' -> false (3,981)
//     COMPANY_NAME_COMPLETED      'true' -> true (28,702)   'false' -> false (6,276)
// ZERO false->true transitions in 38,958 rows: decide never DECIDES a *_COMPLETED flag, it only
// reads them as gates (see docBaseRouterDecide, the not-BASE_EXTRACTION_COMPLETED test). The caller
// holds the same values already and the routers re-coerce when they act, so returning them is
// ~30 columns/row of zero information.
// What IS decided and therefore returned: ACTION + DOC_TYPE (added on 100% of rows), TYPE
// ('UNKNOWN' -> a real type, 107 rows), IS_OLD (null -> true, 179 rows beyond the coercion),
// OLD_REASON, DOUBLE_CONTEXT, ITERATION_COUNT, SOURCE_LIST (rewritten by the merge path, 1,025
// rows), PRIORITY_SYNC_COUNT and SELECTION_VALUES_HASH (11 rows each).
// Re-measure with scratchpad/diff_fields.py + sample_vals.py if decide's logic changes.
// [full-line contract restored 2026-08-18, owner order] Decide returns the WHOLE line, so the
// driver needs no rejoin. The transient dedup columns are the only things stripped.
for (const it of __outs) {
  if (!it || !it.json) continue;
  delete it.json.__merge_enabled;
}
return __outs;
`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenCalled.out(0).to(this.ExportSeedDocBase.in(0));
        this.WhenCalled.out(0).to(this.LoadCompanyResolverGen.in(0));
        this.ExportSeedDocBase.out(0).to(this.CallExportDocBase.in(0));
        this.CallExportDocBase.out(0).to(this.ExportSeedGdoc.in(0));
        this.ExportSeedGdoc.out(0).to(this.CallExportGdoc.in(0));
        this.CallExportGdoc.out(0).to(this.ExportSeedShipment.in(0));
        this.ExportSeedShipment.out(0).to(this.CallExportShipment.in(0));
        this.CallExportShipment.out(0).to(this.ExportSeedBs.in(0));
        this.ExportSeedBs.out(0).to(this.CallExportBs.in(0));
        this.CallExportBs.out(0).to(this.ExportSeedOrder.in(0));
        this.LoadCompanyResolverGen.out(0).to(this.MegaDecide.in(0));
        this.ExportSeedOrder.out(0).to(this.CallExportOrder.in(0));
        this.CallExportOrder.out(0).to(this.ExportSeedReceipt.in(0));
        this.ExportSeedReceipt.out(0).to(this.CallExportReceipt.in(0));
    }
}
