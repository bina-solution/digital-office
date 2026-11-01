import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Shipment JQ Ex V3
// Nodes   : 5  |  Connections: 4
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// DocIn                              executeWorkflowTrigger
// LoadV3Config                       postgres                   [creds] [alwaysOutput]
// FanFields                          code
// QueryApitools                      httpRequest                [onError→regular] [alwaysOutput] [retry]
// Collect                            code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// DocIn
//    → LoadV3Config
//      → FanFields
//        → QueryApitools
//          → Collect
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Doc In":{"main":[[{"node":"Load V3 Config","type":"main","index":0}]]},"Load V3 Config":{"main":[[{"node":"Fan Fields","type":"main","index":0}]]},"Fan Fields":{"main":[[{"node":"Query apitools","type":"main","index":0}]]},"Query apitools":{"main":[[{"node":"Collect","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"56de2cdd-1d32-4a04-b009-b7d1928bf34d","name":"extractors"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d0491649-2c07-43cd-9070-884fbcb8f086","name":"JsonQueryExV3"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"0b14850d-472a-4fdf-a00c-ef07a5623099","name":"json-query-ex-v3"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"f5d175fb-c738-4607-8ef0-bf03c48e8a0b","name":"role:extractor"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"JQExV3Ship000001","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'JQExV3Ship000001',
    name: 'Shipment JQ Ex V3',
    active: true,
    isArchived: false,
    tags: ['extractors', 'indox', 'JsonQueryExV3', 'app:indox', 'indox-app', 'json-query-ex-v3', 'role:extractor'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class ShipmentJqExV3Workflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: '11111111-0000-0000-0000-808132716900',
        name: 'Doc In',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, 0],
    })
    DocIn = {
        workflowInputs: {
            values: [
                {
                    name: 'ID',
                },
                {
                    name: 'API_TOOLS_ID',
                },
                {
                    name: 'LINK',
                },
                {
                    name: '__instance',
                },
            ],
        },
    };

    @node({
        id: '22222222-0000-0000-0000-139965759837',
        name: 'Load V3 Config',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [240, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    LoadV3Config = {
        operation: 'executeQuery',
        query: `=-- SINGLE SOURCE. extraction_queries (schema.sql) returns each q_v3_*
-- settings row with every @registry_* sentinel already substituted from the
-- companies table, so this node no longer builds a registry of its own and
-- there is exactly one definition of "what the company option lists are".
-- 'Fan Fields' keeps its bindRegistry pass as an ASSERT: after this query no
-- sentinel should survive, and if one does it throws instead of sending the
-- literal string "@registry_ids" to apitools as a silent-green no-match.
select coalesce(jsonb_object_agg(key, query), '{}'::jsonb) as cfg
  from {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('JQExV3Ship000001: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.extraction_queries`,
        options: {},
    };

    @node({
        id: '33333333-0000-0000-0000-093054418667',
        name: 'Fan Fields',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [480, 0],
    })
    FanFields = {
        jsCode: `// BATCHED FAN-OUT: one item per DOCUMENT carrying every field's query, instead of one
// item per (document, field). The HTTP node downstream therefore makes ONE
// /documentJsonQuery call per document rather than one per field.
//
// WHY (measured 2026-08-10, in the apitools container, real documents):
// every per-field call re-entered OcrObject.from_file_id, which builds a FRESH OcrQuery
// -- and OcrQuery carries the per-document memos this engine depends on
// (_text_match_memo and the annotations_aligned_with_annotation geometry memo).
// Rebuilding per field threw that work away between fields. cProfile put 82% of a
// q_v3_type call inside find_texts_matching_annotations_via_alignment (50,063
// BoundingBox.check_alingment calls) -- pure geometry over annotations that never change
// for a document. Batching lets every field after the first reuse it.
//   base    (3 fields): 3 calls -> 1, 9.36s/doc -> 6.12s/doc
//   invoice (5 fields): 5 calls -> 1, 9.43s/doc -> 5.95s/doc
//   extraction results identical on 28/28 documents A/B'd (0 mismatches).
const CATEGORY = "shipment";
const docs = $('Doc In').all();
const cfg = ($('Load V3 Config').first().json.cfg) || {};
const routing = (cfg.q_v3_routing || {})[CATEGORY] || {};
const fields = Object.keys(routing);
// REGISTRY BINDING. A query may write "@registry_ids" anywhere a literal action_value
// would go (including inside \`fallbacks\`); it is replaced here with the live company
// registry loaded by 'Load V3 Config'. This is what makes company identification a
// KEYED LOOKUP against every company the instance actually has, instead of a whitelist
// frozen into the settings row -- the frozen list held 57 of 1183 companies (4.8%),
// and apitools truncates a find-option list to APITOOLS_FIND_OPTION_MAX_TEXTS (25),
// so that lane could only ever resolve 25 of them.
//
// It THROWS rather than passing the sentinel through: an unresolved "@registry_ids"
// would reach apitools as the literal string "@registry_ids", match nothing, and come
// back as a perfectly successful "no company found" -- the silent-green failure this
// pipeline is already prone to. Fail loudly instead.
const REGISTRY = { '@registry_ids': Array.isArray(cfg._registry_ids) ? cfg._registry_ids : null };
function bindRegistry(q, where) {
  if (typeof q === 'string' && Object.prototype.hasOwnProperty.call(REGISTRY, q)) {
    if (!REGISTRY[q] || !REGISTRY[q].length)
      throw new Error(q + ' is empty or missing in Load V3 Config output (at ' + where + ') -- the company registry did not load');
    return REGISTRY[q];
  }
  if (Array.isArray(q)) return q.map(function (x, i) { return bindRegistry(x, where + '[' + i + ']'); });
  if (q && typeof q === 'object') {
    const o = {};
    for (const [k, v] of Object.entries(q)) o[k] = bindRegistry(v, where + '.' + k);
    return o;
  }
  return q;
}

const out = [];
for (let d = 0; d < docs.length; d++) {
  const j = docs[d].json;
  const fid = j.API_TOOLS_ID || j.file_id || j.HASH || j.file_hash;
  const queries = [];
  for (const field of fields) {
    queries.push({ field: field, qkey: routing[field],
                   ocr_json_query: bindRegistry(cfg[routing[field]] || null, routing[field]) });
  }
  out.push({ json: { ID: j.ID, TYPE: CATEGORY, fid: fid, queries: queries } });
}
return out;
`,
    };

    @node({
        id: '44444444-0000-0000-0000-709949116467',
        name: 'Query apitools',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [720, 0],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
    })
    QueryApitools = {
        method: 'POST',
        url: 'http://apitools:8080/documentJsonQuery',
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ JSON.stringify({ file_id: $json.fid, ocr_json_queries: $json.queries }) }}',
        options: {
            timeout: 300000,
        },
    };

    @node({
        id: '55555555-0000-0000-0000-127041682385',
        name: 'Collect',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [960, 0],
    })
    Collect = {
        jsCode: `// Regroup the BATCHED apitools responses into one record per document.
// There is now ONE response item per document (not one per field); its \`results\` array
// is in the same order as the \`queries\` array we sent, so pair by position.
// httpRequest preserves item order 1:1, so pair documents by index with 'Fan Fields'.
//
// NO SILENT FAILURES: with onError=continueRegularOutput a failed HTTP call (e.g.
// AxiosError: timeout) yields an item whose json is {error: ...} and NO results. That
// must not read as "value not on the document" -- a whole-call failure is recorded
// against EVERY field in _ERRORS. Per-field failures inside a successful batch
// (query_timeout / query_failed / batch_budget_exhausted) are recorded per field.
//
// PROVENANCE: _TIMINGS[field] = that field's own elapsed_ms from the batch response,
// and _META carries {ocr_engine, apitools_version} -- reported once per document now
// instead of repeated per field, which is where it always belonged.
// DOC_DATE CANONICALISATION -- restores what the v1 date query (indoxV2QueryDocDate01,
// "Parse Date Result" -> unifyDateFormat) always did and the v3 port dropped: DD/MM/YYYY,
// zero-padded, 2-digit years expanded to 20YY, dot separators folded to slashes.
//
// It is needed HERE because this is where a raw apitools match first becomes a stored field.
// The v3 settings regex (\\d{1,2}[./]\\d{1,2}[./]\\d{2,4}) deliberately accepts every spelling a
// document might print, so without this the column holds whichever one the page used --
// measured live: 445 rows DD/MM/YY, ~30 dot-separated, a handful unpadded. The AI extractor
// emits DD/MM/YYYY, so \`Select Base\`'s pick() then scored two identical dates as
// DISAGREE_PREFER_LOCAL purely on spelling.
//
// A value that is not a date shape is passed through UNCHANGED rather than nulled: nulling
// would make a bad extraction indistinguishable from an absent one.
const DOC_DATE_RE = /^(\\d{1,2})[./](\\d{1,2})[./](\\d{2}|\\d{4})$/;
function unifyDocDate(s) {
  if (s === null || s === undefined) return s;
  const m = DOC_DATE_RE.exec(String(s).trim());
  if (!m) return s;
  let d = m[1], mo = m[2], y = m[3];
  if (d.length === 1) d = '0' + d;
  if (mo.length === 1) mo = '0' + mo;
  if (y.length === 2) y = '20' + y;
  return d + '/' + mo + '/' + y;
}
// AMOUNT CANONICALISATION -- the same argument as DOC_DATE above, for the same reason and in the
// same place: this is where a raw apitools match first becomes a stored field.
//
// The page sometimes prints, or the OCR sometimes reads, the decimal point as a comma:
// '16,583,00'. Nothing downstream can recover it, because every consumer strips thousands
// separators before parsing -- so the value becomes 1658300 and the client's ERP is sent 100x
// the invoice. Measured on doc_msm30ay0w8ea6a (ברסיס IN264026271): the scan reads 16,583.00,
// the AI leg read 16,583.00, this leg read '16,583,00', and Priority holds 1,658,300 at LINE
// 23002. Across the table the AI leg agrees with the corrected reading on 63 of 70 such rows
// and the supplier's own ledger on 28 of 30; neither agrees with the 100x reading even once.
//
// The test is deliberately narrow -- ends in ',dd' AND contains no '.' anywhere -- so a genuine
// thousands separator ('1,234.56', '1,180') can never be mistaken for a decimal one. Proven
// before shipping over every amount value in the table, 14,306 distinct: 14,249 returned
// byte-identical, 57 changed, every one of them this shape and every one landing on the AI leg's
// number. The dotted variants ('7.633.00', '1.222.052.152.') are a DIFFERENT defect and are
// deliberately left alone rather than half-guessed.
//
// Unrecognised input is passed through UNCHANGED, for the same reason unifyDocDate does it.
function unifyDocAmount(s) {
  if (s === null || s === undefined) return s;
  const v = String(s).trim();
  if (!/,\\d{2}$/.test(v) || v.indexOf('.') !== -1) return s;
  return v.replace(/,(\\d{2})$/, '.$1');
}
const reqs = $('Fan Fields').all();
const resps = $input.all();
const out = [];
for (let i = 0; i < reqs.length; i++) {
  const rq = reqs[i].json;
  const rp = (resps[i] && resps[i].json) || {};
  const rec = { ID: rq.ID, TYPE: rq.TYPE, API_TOOLS_ID: rq.fid };
  const results = Array.isArray(rp.results) ? rp.results : [];
  const callErr = rp && rp.error ? (rp.error.message || rp.error.description || String(rp.error)) : null;
  const qs = Array.isArray(rq.queries) ? rq.queries : [];
  for (let q = 0; q < qs.length; q++) {
    const field = qs[q].field;
    const item = results[q] || {};
    let r = item.result ? item.result.result : undefined;
    let val = null;
    if (r && typeof r === 'object' && Array.isArray(r.matches)) val = (r.matches[0] || {}).option ?? null;
    else val = (r === undefined ? null : r);
    if (field === 'DOC_DATE') val = unifyDocDate(val);
    if (field === 'DOC_TOTAL_AMOUNT' || field === 'BALANCE') val = unifyDocAmount(val);
    rec[field] = val;
    if (typeof item.elapsed_ms === 'number') {
      if (!rec._TIMINGS) rec._TIMINGS = {};
      rec._TIMINGS[field] = item.elapsed_ms;
    }
    // a field is only an ERROR if it produced no result: either the whole call died
    // (callErr) or this specific query failed inside an otherwise-good batch.
    const fieldErr = item.error
      ? (item.message || item.error)
      : (callErr && r === undefined ? callErr : null);
    if (fieldErr && r === undefined) {
      if (!rec._ERRORS) rec._ERRORS = {};
      rec._ERRORS[field] = String(fieldErr).slice(0, 200);
    }
  }
  if (rp.ocr_engine || rp.apitools_version) {
    // OCR provenance rides inside the ocr_json (stamped at OCR time, cache-persistent):
    // engine + build + timestamp + duration of the ORIGINAL OCR, plus the build serving now.
    rec._META = {
      ocr_engine: rp.ocr_engine || null,
      ocr_ms: (typeof rp.ocr_ms === 'number' ? rp.ocr_ms : null),
      ocr_at: rp.ocr_at || null,
      ocr_apitools_version: rp.ocr_apitools_version || null,
      apitools_version: rp.apitools_version || null,
    };
  }
  out.push({ json: rec });
}
return out;
`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.DocIn.out(0).to(this.LoadV3Config.in(0));
        this.LoadV3Config.out(0).to(this.FanFields.in(0));
        this.FanFields.out(0).to(this.QueryApitools.in(0));
        this.QueryApitools.out(0).to(this.Collect.in(0));
    }
}
