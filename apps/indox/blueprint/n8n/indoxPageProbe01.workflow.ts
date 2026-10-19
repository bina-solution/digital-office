import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox GET_ALL pagination probe
// Nodes   : 27  |  Connections: 29
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// ProbeWebhook                       webhook                    [creds]
// RouteMode                          if
// LegacyReq                          code
// CallApiLegacy                      executeWorkflow
// LegacyCount                        code
// ContractMode                       if
// C1Req                              code
// CallC1                             executeWorkflow
// S1OffsetP0                         code
// CallC2                             executeWorkflow
// S2OffsetP1                         code
// CallC3                             executeWorkflow
// S3KeysetEqualsOffset               code
// CallC4                             executeWorkflow
// S4Desc                             code
// CallC5                             executeWorkflow
// S5EmptyPage                        code
// CallC6MustFail                     executeWorkflow            [onError→regular]
// S6Mutex                            code
// NextPageReq                        code
// CallApiPage                        executeWorkflow
// PageRows                           code
// RowsTail                           code
// MorePages                          if
// PageCursor                         code
// Report                             code
// ProbeRespond                       respondToWebhook           [onError→regular]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// ProbeWebhook
//    → RouteMode
//      → LegacyReq
//        → CallApiLegacy
//          → LegacyCount
//            → ProbeRespond
//     .out(1) → ContractMode
//        → C1Req
//          → CallC1
//            → S1OffsetP0
//              → CallC2
//                → S2OffsetP1
//                  → CallC3
//                    → S3KeysetEqualsOffset
//                      → CallC4
//                        → S4Desc
//                          → CallC5
//                            → S5EmptyPage
//                              → CallC6MustFail
//                                → S6Mutex
//                                  → ProbeRespond (↩ loop)
//       .out(1) → NextPageReq
//          → CallApiPage
//            → PageRows
//              → RowsTail
//                → MorePages
//                 .out(1) → Report
//                    → ProbeRespond (↩ loop)
//            → PageCursor
//              → NextPageReq (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Probe Webhook":{"main":[[{"node":"Route Mode","type":"main","index":0}]]},"Route Mode":{"main":[[{"node":"Legacy Req","type":"main","index":0}],[{"node":"Contract Mode?","type":"main","index":0}]]},"Legacy Req":{"main":[[{"node":"Call API (legacy)","type":"main","index":0}]]},"Call API (legacy)":{"main":[[{"node":"Legacy Count","type":"main","index":0}]]},"Legacy Count":{"main":[[{"node":"Probe Respond","type":"main","index":0}]]},"Next Page Req":{"main":[[{"node":"Call API (page)","type":"main","index":0}]]},"Call API (page)":{"main":[[{"node":"Page Rows","type":"main","index":0},{"node":"Page Cursor","type":"main","index":0}]]},"Page Rows":{"main":[[{"node":"Rows Tail","type":"main","index":0}]]},"Rows Tail":{"main":[[{"node":"More Pages?","type":"main","index":0}]]},"More Pages?":{"main":[[],[{"node":"Report","type":"main","index":0}]]},"Page Cursor":{"main":[[{"node":"Next Page Req","type":"main","index":0}]]},"Report":{"main":[[{"node":"Probe Respond","type":"main","index":0}]]},"Contract Mode?":{"main":[[{"node":"C1 Req","type":"main","index":0}],[{"node":"Next Page Req","type":"main","index":0}]]},"C1 Req":{"main":[[{"node":"Call C1","type":"main","index":0}]]},"Call C1":{"main":[[{"node":"S1 offset p0","type":"main","index":0}]]},"S1 offset p0":{"main":[[{"node":"Call C2","type":"main","index":0}]]},"Call C2":{"main":[[{"node":"S2 offset p1","type":"main","index":0}]]},"S2 offset p1":{"main":[[{"node":"Call C3","type":"main","index":0}]]},"Call C3":{"main":[[{"node":"S3 keyset equals offset","type":"main","index":0}]]},"S3 keyset equals offset":{"main":[[{"node":"Call C4","type":"main","index":0}]]},"Call C4":{"main":[[{"node":"S4 desc","type":"main","index":0}]]},"S4 desc":{"main":[[{"node":"Call C5","type":"main","index":0}]]},"Call C5":{"main":[[{"node":"S5 empty page","type":"main","index":0}]]},"S5 empty page":{"main":[[{"node":"Call C6 must fail","type":"main","index":0}]]},"Call C6 must fail":{"main":[[{"node":"S6 mutex","type":"main","index":0}]]},"S6 mutex":{"main":[[{"node":"Probe Respond","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-18T20:33:22.683Z","createdAt":"2026-08-18T20:33:22.683Z","role":"workflow:owner","workflowId":"indoxPageProbe01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxPageProbe01',
    name: 'indox GET_ALL pagination probe',
    active: true,
    isArchived: false,
    tags: ['app:indox'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class IndoxGetAllPaginationProbeWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'pp-webhook-01',
        webhookId: 'f4a1c9d2-3e57-4b16-8c90-2d7ba5e1f083',
        name: 'Probe Webhook',
        type: 'n8n-nodes-base.webhook',
        version: 2.1,
        position: [0, 0],
        credentials: { httpBasicAuth: { id: 'azPhHBvOWaf9IsEA', name: 'Incoming Documents [env-managed]' } },
    })
    ProbeWebhook = {
        httpMethod: 'POST',
        path: 'indox-page-probe',
        authentication: 'basicAuth',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'pp-route-01',
        name: 'Route Mode',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [220, 0],
    })
    RouteMode = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'legacy',
                    leftValue: '={{ $json.body && $json.body.legacy === true }}',
                    rightValue: true,
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
        id: 'pp-legacy-req-01',
        name: 'Legacy Req',
        /*__n8n__*/ notes: "Exactly what every pre-existing GET_ALL caller sends: the action and nothing else. If pagination changed the legacy contract at all, it shows up here.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [440, -240],
    })
    LegacyReq = {
        jsCode: `// __instance selects the SCHEMA. This lane is ENTRY-ONLY (Probe Webhook), so the request has
// to name the instance -- there is no upstream item to inherit it from. Pass ?__instance=levi to
// probe levi, omit it to keep the previous behaviour (public). Every builder in this workflow
// reads it the same way, so a probe run cannot half-target two instances.
// This matters beyond the probe: these were the last builders blocking removal of indoxApi01's
// public fallback, after which an unnamed instance becomes a hard error rather than a silent
// read of whichever tenant public points at.
let PI=''; try{ PI=String(($('Probe Webhook').first().json.query||{}).__instance||''); }catch(e){ PI=''; }
return [{ json: { INLINE_ACTION: 'GET_ALL', __instance: PI } }];
`,
    };

    @node({
        id: 'pp-legacy-call-01',
        name: 'Call API (legacy)',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [660, -240],
    })
    CallApiLegacy = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'pp-legacy-count-01',
        name: 'Legacy Count',
        /*__n8n__*/ notes: "Reduces the whole-table answer to a count immediately - the probe never holds it longer than the call itself. envelopeItems MUST be 0: an unpaginated GET_ALL gets no page envelope, which is the whole backward-compatibility claim.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [880, -240],
    })
    LegacyCount = {
        jsCode: `const items = $input.all();
const first = items.length ? (items[0].json || {}) : {};
return [{ json: {
  mode: 'legacy',
  legacyItems: items.length,
  envelopeItems: items.filter(i => i.json && i.json._indoxApi === 'GET_ALL_PAGE').length,
  firstKeyCount: Object.keys(first).length,
  firstHasTotalKey: Object.prototype.hasOwnProperty.call(first, '_total'),
  firstId: first.ID === undefined ? null : String(first.ID),
} }];
`,
    };

    @node({
        id: 'pp-contract-mode-01',
        name: 'Contract Mode?',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [440, -80],
    })
    ContractMode = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'contract',
                    leftValue: '={{ $json.body && $json.body.contract === true }}',
                    rightValue: true,
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
        id: 'pp-c1-req-01',
        name: 'C1 Req',
        /*__n8n__*/ notes: "Step 1 of the contract chain: OFFSET mode, page 0.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [660, -480],
    })
    C1Req = {
        jsCode: `// __instance from the probe request -- see 'Legacy Req' for why.
let PI=''; try{ PI=String(($('Probe Webhook').first().json.query||{}).__instance||''); }catch(e){ PI=''; }
return [{ json: { INLINE_ACTION: 'GET_ALL', limit: 5, page: 0, __instance: PI } }];
`,
    };

    @node({
        id: 'pp-c1-call-01',
        name: 'Call C1',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [880, -480],
    })
    CallC1 = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'pp-s1-01',
        name: 'S1 offset p0',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1100, -480],
    })
    S1OffsetP0 = {
        jsCode: `const all = $input.all().map(i => i.json || {});
const env = all.find(j => j._indoxApi === 'GET_ALL_PAGE') || {};
const rows = all.filter(j => j._indoxApi !== 'GET_ALL_PAGE' && Object.keys(j).length);
const ids = rows.map(r => String(r.ID));
const checks = {
  c1_mode_offset: env.mode === 'offset',
  c1_rows_5: rows.length === 5,
  c1_page_0: env.page === 0,
  c1_nextPage_1: env.nextPage === 1,
  c1_nextOffset_5: env.nextOffset === 5,
  c1_hasMore: env.hasMore === true,
  c1_total_null_without_withTotal: env.total === null,
};
// __instance from the probe request -- see 'Legacy Req'.
let PI=''; try{ PI=String(($('Probe Webhook').first().json.query||{}).__instance||''); }catch(e){ PI=''; }
return [{ json: { INLINE_ACTION: 'GET_ALL', limit: 5, page: 1, _checks: checks, _r1Ids: ids, _r1Last: ids[ids.length - 1], __instance: PI } }];
`,
    };

    @node({
        id: 'pp-c2-call-01',
        name: 'Call C2',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1320, -480],
    })
    CallC2 = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'pp-s2-01',
        name: 'S2 offset p1',
        /*__n8n__*/ notes: "Builds the KEYSET request that must be equivalent to offset page 1: after = last ID of offset page 0.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1540, -480],
    })
    S2OffsetP1 = {
        jsCode: `const prev = $('S1 offset p0').first().json;
const all = $input.all().map(i => i.json || {});
const env = all.find(j => j._indoxApi === 'GET_ALL_PAGE') || {};
const rows = all.filter(j => j._indoxApi !== 'GET_ALL_PAGE' && Object.keys(j).length);
const ids = rows.map(r => String(r.ID));
const checks = Object.assign({}, prev._checks, {
  c2_rows_5: rows.length === 5,
  c2_page_1: env.page === 1,
  c2_offset_5: env.offset === 5,
  c2_nextPage_2: env.nextPage === 2,
  c2_disjoint_from_p0: ids.every(id => prev._r1Ids.indexOf(id) === -1),
});
// __instance from the probe request -- see 'Legacy Req'.
let PI=''; try{ PI=String(($('Probe Webhook').first().json.query||{}).__instance||''); }catch(e){ PI=''; }
return [{ json: { INLINE_ACTION: 'GET_ALL', limit: 5, after: prev._r1Last, _checks: checks, _r2Ids: ids, __instance: PI } }];
`,
    };

    @node({
        id: 'pp-c3-call-01',
        name: 'Call C3',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1760, -480],
    })
    CallC3 = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'pp-s3-01',
        name: 'S3 keyset equals offset',
        /*__n8n__*/ notes: "The equivalence that proves both modes page the SAME ordering: keyset after=<last id of offset page 0> must return exactly offset page 1.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [660, -240],
    })
    S3KeysetEqualsOffset = {
        jsCode: `const prev = $('S2 offset p1').first().json;
const all = $input.all().map(i => i.json || {});
const env = all.find(j => j._indoxApi === 'GET_ALL_PAGE') || {};
const rows = all.filter(j => j._indoxApi !== 'GET_ALL_PAGE' && Object.keys(j).length);
const ids = rows.map(r => String(r.ID));
const checks = Object.assign({}, prev._checks, {
  c3_mode_keyset: env.mode === 'keyset',
  c3_keyset_equals_offset_page1: JSON.stringify(ids) === JSON.stringify(prev._r2Ids),
});
// __instance from the probe request -- see 'Legacy Req'.
let PI=''; try{ PI=String(($('Probe Webhook').first().json.query||{}).__instance||''); }catch(e){ PI=''; }
return [{ json: { INLINE_ACTION: 'GET_ALL', limit: 1, order: 'desc', _checks: checks, __instance: PI } }];
`,
    };

    @node({
        id: 'pp-c4-call-01',
        name: 'Call C4',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [880, -240],
    })
    CallC4 = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'pp-s4-01',
        name: 'S4 desc',
        /*__n8n__*/ notes: "desc order gives the MAX id, which is then used as a cursor to force a genuinely empty page.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1100, -240],
    })
    S4Desc = {
        jsCode: `const prev = $('S3 keyset equals offset').first().json;
const all = $input.all().map(i => i.json || {});
const env = all.find(j => j._indoxApi === 'GET_ALL_PAGE') || {};
const rows = all.filter(j => j._indoxApi !== 'GET_ALL_PAGE' && Object.keys(j).length);
const maxId = rows.length ? String(rows[0].ID) : null;
const checks = Object.assign({}, prev._checks, {
  c4_order_desc: env.order === 'desc',
  c4_rows_1: rows.length === 1,
  c4_hasMore: env.hasMore === true,
});
// __instance from the probe request -- see 'Legacy Req'.
let PI=''; try{ PI=String(($('Probe Webhook').first().json.query||{}).__instance||''); }catch(e){ PI=''; }
return [{ json: { INLINE_ACTION: 'GET_ALL', limit: 5, after: maxId, _checks: checks, _maxId: maxId, __instance: PI } }];
`,
    };

    @node({
        id: 'pp-c5-call-01',
        name: 'Call C5',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1320, -240],
    })
    CallC5 = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'pp-s5-01',
        name: 'S5 empty page',
        /*__n8n__*/ notes: "A cursor past the last row must give a clean empty page - 0 rows, hasMore false - not a placeholder row and not an error.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1540, -240],
    })
    S5EmptyPage = {
        jsCode: `const prev = $('S4 desc').first().json;
const all = $input.all().map(i => i.json || {});
const env = all.find(j => j._indoxApi === 'GET_ALL_PAGE') || {};
const rows = all.filter(j => j._indoxApi !== 'GET_ALL_PAGE' && Object.keys(j).length);
const checks = Object.assign({}, prev._checks, {
  c5_empty_rows: rows.length === 0,
  c5_count_0: env.count === 0,
  c5_hasMore_false: env.hasMore === false,
  c5_nextCursor_null: env.nextCursor === null,
});
// __instance from the probe request -- see 'Legacy Req'.
let PI=''; try{ PI=String(($('Probe Webhook').first().json.query||{}).__instance||''); }catch(e){ PI=''; }
return [{ json: { INLINE_ACTION: 'GET_ALL', limit: 5, after: prev._maxId, page: 1, _checks: checks, __instance: PI } }];
`,
    };

    @node({
        id: 'pp-c6-call-01',
        name: 'Call C6 must fail',
        /*__n8n__*/ notes: "Asks for a cursor AND an offset page at once. onError continueRegularOutput so the probe can assert the refusal instead of dying on it.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1760, -240],
        onError: 'continueRegularOutput',
    })
    CallC6MustFail = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'pp-s6-01',
        name: 'S6 mutex',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [660, 480],
    })
    S6Mutex = {
        jsCode: `const prev = $('S5 empty page').first().json;
const all = $input.all().map(i => i.json || {});
const env = all.find(j => j._indoxApi === 'GET_ALL_PAGE');
const rows = all.filter(j => j._indoxApi !== 'GET_ALL_PAGE' && j.ID !== undefined);
const checks = Object.assign({}, prev._checks, {
  c6_mutex_refused: !env && rows.length === 0,
});
const failed = Object.keys(checks).filter(k => checks[k] !== true);
// 'Call C6 must fail' continues on error, so its failure arrives here as an ordinary item — and the
// check above only sees the EFFECT (no rows), the same whether the call was refused or simply
// broken. Read the failure itself and report how the refusal happened.
const c6Errors = all.filter(j => j.error || j.errorMessage)
  .map(j => String(j.error || j.errorMessage).slice(0, 200));
return [{ json: { mode: 'contract', ok: failed.length === 0, failed, checks,
  c6_errors: c6Errors, c6_refused_by_error: c6Errors.length > 0 } }];
`,
    };

    @node({
        id: 'pp-next-req-01',
        name: 'Next Page Req',
        /*__n8n__*/ notes: "Same request builder indoxV2Driver01 uses, plus withTotal so the probe has an independent ground truth to compare its walk against.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [440, 160],
    })
    NextPageReq = {
        jsCode: `const PAGE_SIZE = 1000;
const MAX_PAGES = 200;
if ($runIndex >= MAX_PAGES) {
  throw new Error('probe: refusing to request page ' + ($runIndex + 1) + ' (MAX_PAGES=' + MAX_PAGES + ')');
}
const src = $input.first() ? ($input.first().json || {}) : {};
const after = (src.after === null || src.after === undefined || src.after === '') ? null : String(src.after);
// __instance from the probe request -- see 'Legacy Req'. Carried forward from the page we were
// handed first, so a multi-page sweep cannot switch instance halfway through.
const req = { INLINE_ACTION: 'GET_ALL', limit: PAGE_SIZE, withTotal: true };
let PI = String(src.__instance || '');
if (!PI) { try { PI = String(($('Probe Webhook').first().json.query || {}).__instance || ''); } catch (e) { PI = ''; } }
req.__instance = PI;
if (after !== null) req.after = after;
return [{ json: req }];
`,
    };

    @node({
        id: 'pp-page-call-01',
        name: 'Call API (page)',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [660, 160],
    })
    CallApiPage = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'pp-page-rows-01',
        name: 'Page Rows',
        /*__n8n__*/ notes: "TOP branch of the fan-out - same node as the driver's. Position matters: n8n executionOrder v1 runs whole branches in top-to-bottom order of their first node, so this one must sit ABOVE 'Page Cursor'.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [880, 60],
    })
    PageRows = {
        jsCode: `const out = [];
for (const it of $input.all()) {
  const j = it.json || {};
  if (j._indoxApi === 'GET_ALL_PAGE') continue;
  if (!Object.keys(j).length) continue;
  out.push({ json: j });
}
return out;
`,
    };

    @node({
        id: 'pp-rows-tail-01',
        name: 'Rows Tail',
        /*__n8n__*/ notes: "Stands in for the whole state machine the driver hangs off this branch: its only job is to be a node that runs AFTER 'Page Rows', so 'Page Cursor' can assert the branch completed. Running total needs no accumulator - while hasMore is true a page is EXACTLY PAGE_SIZE rows.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1100, 60],
    })
    RowsTail = {
        jsCode: `const PAGE_SIZE = 1000;
const rows = $input.all();
const env = $('Call API (page)').all().map(i => i.json || {}).find(j => j._indoxApi === 'GET_ALL_PAGE');
if (!env) throw new Error('probe: no GET_ALL_PAGE envelope on the call output');
const first = rows.length ? rows[0].json : {};
return [{ json: {
  pageIndex: $runIndex,
  pageRows: rows.length,
  envCount: env.count,
  hasMore: env.hasMore === true,
  runningTotal: $runIndex * PAGE_SIZE + rows.length,
  apiTotal: env.total,
  lastId: rows.length ? String(rows[rows.length - 1].json.ID) : null,
  rowHasTotalKey: rows.length ? Object.prototype.hasOwnProperty.call(first, '_total') : null,
  envelopeLeakedIntoRows: rows.some(r => r.json && r.json._indoxApi !== undefined),
} }];
`,
    };

    @node({
        id: 'pp-more-01',
        name: 'More Pages?',
        /*__n8n__*/ notes: "Gates the REPORT only - the loop itself is closed by 'Page Cursor' returning zero items. false output (index 1) = last page = report.",
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [1320, 60],
    })
    MorePages = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'more',
                    leftValue: '={{ $json.hasMore }}',
                    rightValue: true,
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
        id: 'pp-page-cursor-01',
        name: 'Page Cursor',
        /*__n8n__*/ notes: "BOTTOM branch of the fan-out, and where the ordering claim is ASSERTED: at cursor run r the rows branch must already have completed r+1 runs. If n8n ever ran this branch first, paging would still be CORRECT but would stop bounding memory - every page would be in flight at once. A green probe run is the proof that it does not.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [880, 320],
    })
    PageCursor = {
        jsCode: `const env = $input.all().map(i => i.json || {}).find(j => j._indoxApi === 'GET_ALL_PAGE');
if (!env) throw new Error('probe: no GET_ALL_PAGE envelope in the response');

// Count completed runs of the rows branch. n8n throws (or yields nothing) for a run index that
// has not happened yet, which is exactly the signal we want.
let tailRuns = 0;
for (let r = 0; r <= $runIndex; r++) {
  let done = false;
  try { const a = $('Rows Tail').all(0, r); done = !!(a && a.length); } catch (e) { done = false; }
  if (!done) break;
  tailRuns = r + 1;
}
if (tailRuns !== $runIndex + 1) {
  throw new Error('ORDERING: at cursor run ' + $runIndex + ' the rows branch had completed ' +
    tailRuns + ' run(s), expected ' + ($runIndex + 1) + '. The rows branch is NOT finishing ' +
    'before the next page is requested, so paging is not bounding memory.');
}

if (!env.hasMore) return [];
if (!env.nextCursor) return [];
return [{ json: { after: env.nextCursor } }];
`,
    };

    @node({
        id: 'pp-report-01',
        name: 'Report',
        /*__n8n__*/ notes: "ok === true is the assertion: the pages walked add up to the API's own count of the whole table, so the sweep covered every row exactly once.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1540, 60],
    })
    Report = {
        jsCode: `const j = $json;
const apiTotal = j.apiTotal === null || j.apiTotal === undefined ? null : Number(j.apiTotal);
return [{ json: {
  mode: 'paged',
  ok: apiTotal !== null && j.runningTotal === apiTotal && j.envelopeLeakedIntoRows === false,
  pages: j.pageIndex + 1,
  rowsWalked: j.runningTotal,
  apiTotal,
  lastPageRows: j.pageRows,
  lastId: j.lastId,
  rowsCarryTotalKey: j.rowHasTotalKey,
  envelopeLeakedIntoRows: j.envelopeLeakedIntoRows,
  orderingAssertedPerPage: true,
} }];
`,
    };

    @node({
        id: 'pp-respond-01',
        name: 'Probe Respond',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [1760, -80],
        onError: 'continueRegularOutput',
    })
    ProbeRespond = {
        respondWith: 'text',
        responseBody: '={{ JSON.stringify($json) }}',
        options: {
            responseHeaders: {
                entries: [
                    {
                        name: 'content-type',
                        value: 'application/json; charset=utf-8',
                    },
                ],
            },
        },
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.ProbeWebhook.out(0).to(this.RouteMode.in(0));
        this.RouteMode.out(0).to(this.LegacyReq.in(0));
        this.RouteMode.out(1).to(this.ContractMode.in(0));
        this.LegacyReq.out(0).to(this.CallApiLegacy.in(0));
        this.CallApiLegacy.out(0).to(this.LegacyCount.in(0));
        this.LegacyCount.out(0).to(this.ProbeRespond.in(0));
        this.NextPageReq.out(0).to(this.CallApiPage.in(0));
        this.CallApiPage.out(0).to(this.PageRows.in(0));
        this.CallApiPage.out(0).to(this.PageCursor.in(0));
        this.PageRows.out(0).to(this.RowsTail.in(0));
        this.RowsTail.out(0).to(this.MorePages.in(0));
        this.MorePages.out(1).to(this.Report.in(0));
        this.PageCursor.out(0).to(this.NextPageReq.in(0));
        this.Report.out(0).to(this.ProbeRespond.in(0));
        this.ContractMode.out(0).to(this.C1Req.in(0));
        this.ContractMode.out(1).to(this.NextPageReq.in(0));
        this.C1Req.out(0).to(this.CallC1.in(0));
        this.CallC1.out(0).to(this.S1OffsetP0.in(0));
        this.S1OffsetP0.out(0).to(this.CallC2.in(0));
        this.CallC2.out(0).to(this.S2OffsetP1.in(0));
        this.S2OffsetP1.out(0).to(this.CallC3.in(0));
        this.CallC3.out(0).to(this.S3KeysetEqualsOffset.in(0));
        this.S3KeysetEqualsOffset.out(0).to(this.CallC4.in(0));
        this.CallC4.out(0).to(this.S4Desc.in(0));
        this.S4Desc.out(0).to(this.CallC5.in(0));
        this.CallC5.out(0).to(this.S5EmptyPage.in(0));
        this.S5EmptyPage.out(0).to(this.CallC6MustFail.in(0));
        this.CallC6MustFail.out(0).to(this.S6Mutex.in(0));
        this.S6Mutex.out(0).to(this.ProbeRespond.in(0));
    }
}
