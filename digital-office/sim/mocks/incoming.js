/* Mock backend for מסמכים נכנסים (incoming-documents / INDOX) — lets the REAL
   React/Vite SPA (development/incoming-documents/app/webapp/src) run standalone
   with zero real network traffic. Real UI code is untouched; only window.fetch
   is intercepted (pattern from ./any-concurrency.js and
   ./localdrive.js — in-memory store + regex route matching on the path AFTER
   the API_PREFIX marker).

   Endpoint shapes below were read directly from src/api.ts (the app's typed
   fetch wrapper) — every field name matches its TypeScript interface.

   API_PREFIX (see src/api.ts) is `<mount>/incomingDocuments`, where <mount> is
   '' when standalone or '/a/incoming' when embedded in the console. We don't
   care about the mount prefix — we just look for the '/incomingDocuments'
   marker anywhere in the URL and match everything after it.

   Endpoints mocked (method — path — response shape):
     GET  /auth/me                                    → AuthMe
     GET  /repos                                       → { repos: RepoConfig[] }
     POST /repos                                       → { repo, provisioned }
     GET  /repos/:name                                 → { repo }
     PATCH/DELETE /repos/:name                         → { repo } / { success:true }
     GET  /repos/:name/stats                           → RepoStats
     PUT  /repos/:name/documents                       → UpsertResult
     POST /repos/:name/documents/query                 → QueryResult
     GET  /repos/:name/documents/:id                   → { row }
     PATCH /repos/:name/documents/:id                  → { updated, created, events_published }
     GET  /repos/:name/documents/:id/history            → { events }
     POST /repos/:name/sync                            → { success, scanned, events_published, created, changed }
     GET  /dashboard/stats                              → DashboardStats  (recomputed live from the DOCS store)
     GET  /sync/status[?sync=]                          → SyncStatus      (per_sync counts drift every tick)
     GET  /sync/registry                                → SyncRegistryResult
     GET  /config/settings                              → ConfigSettingsResult
     PUT  /config/settings/:key                         → PutSettingResult
     GET  /config/companies | /config/tag_rules         → ConfigCompaniesResult / ConfigTagRulesResult
     PATCH/DELETE /config/:table/:id, POST /config/:table → generic row CRUD ({ok,row?})
     GET  /tests/suites                                 → TestSuitesResult
     POST /tests/run, GET /tests/run/:id                → { run_id } / TestRun (advances one case per poll)
     GET  /extraction/dataset                           → ExtractionDataset
     POST /extraction/run                               → { run_id, docs_total }
     GET  /extraction/run/:id                           → ExtractionRun     (advances one doc per poll — 1.5s cadence)
     POST /extraction/run/:id/cancel                    → { ok }
     POST /extraction/rerun/:docId[?fresh=1]            → ExtractionResult
     POST /extraction/upload (FormData)                 → ExtractionResult
     GET  /extraction/queries, PUT /extraction/queries/:key → { queries } / { success, key }
     GET  /extraction/runs, GET/DELETE /extraction/runs/:id → { runs } / ExtractionRunFull / { ok }
     GET  /extraction/history/:docId                    → { history }

   NOT intercepted (native browser resource loads, not window.fetch/XHR — same
   caveat as ./localdrive.js's api/file/<id>/content): api.extractionFileUrl /
   extractionDrawUrl / extractionTokensUrl build <img src>/<iframe src> URLs
   consumed directly by the DOM, so the document viewer, drawn-overlay and
   OCR-token panes on ExtractionDocPage/ExtractionPage card view will show
   broken images. Faking that would need a Service Worker, out of scope here.

   In-memory store (DOCS/SYNC_COUNTS/EXTRACT_RUNS/... at module scope) is
   mutated by a background ticker (every 6s, independent of any page's poll)
   so the pipeline advances even if you're just sitting on the dashboard:
   one NEEDS_REVIEW document is promoted to IN_PROGRESS, one IN_PROGRESS
   document completes, sync counters drift, and a fresh incoming document is
   occasionally spawned so the pipeline never runs dry. */
(function () {
  var realFetch = window.fetch ? window.fetch.bind(window) : null;

  // ---------------------------------------------------------------- helpers
  function rid(prefix) { return prefix + Math.random().toString(36).slice(2, 9); }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function nowIso() { return new Date().toISOString(); }
  function nowSec() { return Math.floor(Date.now() / 1000); }
  function isoAgo(ms) { return new Date(Date.now() - ms).toISOString(); }
  function pad(n) { return String(n).padStart(2, '0'); }
  function dateStr(d) {
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }
  function today() { return dateStr(new Date()); }
  function j(body, status) {
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: status || 200, headers: { 'Content-Type': 'application/json' },
    }));
  }
  function parseBody(opts) {
    try { return opts && typeof opts.body === 'string' ? JSON.parse(opts.body) : {}; }
    catch (e) { return {}; }
  }

  var REPO_NAME = 'incoming-documents-main';

  // ------------------------------------------------------------ repo config
  var COLUMNS = [
    { name: 'ID', type: 'string', nullable: false },
    { name: 'NAME', type: 'string' },
    { name: 'COMPANY_ID', type: 'string' },
    { name: 'COMPANY_NAME', type: 'string' },
    { name: 'SHORT_DOC_ID', type: 'string' },
    { name: 'TYPE', type: 'string' },
    { name: 'STATUS', type: 'string' },
    { name: 'REQUIRED_ACTION', type: 'string', nullable: true },
    { name: 'DOC_DATE', type: 'date' },
    { name: 'DOC_TOTAL_AMOUNT', type: 'number' },
    { name: 'SOURCE_TYPE', type: 'string' },
    { name: 'TIMESTAMP', type: 'timestamp' },
  ];

  /* HOW THE DATA READS — as the server says it. The live app serves each column with its heading and, for a
     value domain, the word and the colour of each value: its display catalog (apps/indox/blueprint/schema/
     display.json) merged into the columns of `GET /repos/<r>` (api/__init__.py, by this same list of keys).
     This mock is that server here, so it merges the SAME file the same way — the build hands it over
     (build.mjs `catalog`). A mock opened with no catalog serves its columns as they are. */
  var CATALOG = window.__catalog || {};
  function reads(columns) {
    var meta = (((CATALOG.tables || {}).incoming_documents || {}).columns) || {}, enums = CATALOG.enums || {};
    return (columns || []).map(function (c) {
      var m = meta[c.name] || {}, col = Object.assign({}, c);
      ['label', 'enum', 'visible', 'searchable', 'align', 'deprecated', 'description', 'ui_type'].forEach(function (k) {
        if (m[k] != null) col[k] = m[k];
      });
      if (col.enum && enums[col.enum]) col.enum_values = enums[col.enum];
      return col;
    });
  }
  // …on every answer that carries a repo's columns
  function said(o) {
    var served = function (r) { return r && r.columns ? Object.assign({}, r, { columns: reads(r.columns) }) : r; };
    if (!o) return o;
    o = Object.assign({}, o);
    if (o.repo) o.repo = served(o.repo);
    if (o.repos) o.repos = o.repos.map(served);
    if (Array.isArray(o.columns)) o.columns = reads(o.columns);
    return o;
  }

  var REPOS = [{
    name: REPO_NAME,
    backend: 'supabase',
    primary_key: 'ID',
    columns: COLUMNS,
    priority_sync_columns: ['STATUS', 'REQUIRED_ACTION'],
    active: true,
    poll_interval_seconds: 30,
    supabase: { schema: 'public', table: 'incoming_documents', rls: true, service_key_env: 'SUPABASE_SERVICE_KEY' },
    created_at: isoAgo(45 * 86400000),
    updated_at: isoAgo(2 * 3600000),
  }];
  function findRepo(name) { return REPOS.find(function (r) { return r.name === name; }); }
  // Creating a repo creates a whole INSTANCE (own table + settings + registry) — see addInstance below.
  function createRepo(cfg) {
    cfg = cfg || {};
    var inst = addInstance({
      id: cfg.name, label: cfg.label || cfg.name, company: cfg.company || cfg.label || cfg.name,
      color: cfg.color, backend: cfg.backend,
      table: (cfg.supabase && cfg.supabase.table) || (cfg.gsheet && cfg.gsheet.sheet_name),
      columns: cfg.columns, poll_interval_seconds: cfg.poll_interval_seconds, registry: cfg.registry,
    });
    activate(ACTIVE);                                        // refresh the REPOS listing
    return { repo: inst.repo, provisioned: { storage: true } };
  }
  function deleteRepo(name) { return removeInstance(name); }
  function patchRepo(name, patch) {
    var r = findRepo(name); if (!r) return null;
    Object.assign(r, patch); r.updated_at = nowIso();
    return { repo: r };
  }

  // ------------------------------------------------------------- documents
  var COMPANY_POOL = [
    { id: '514236789', name: 'סבח סוכנויות בע״מ' },
    { id: '512987654', name: 'אגן שיווק' },
    { id: '513765432', name: 'ישראל קרטון' },
    { id: '515443322', name: 'דגן תעשיות בע״מ' },
    { id: '516554433', name: 'מ. פרידמן בע״מ' },
  ];


  /* ══ Ten years of documents ════════════════════════════════════════════════════════════════════
     The curated rows above are the hero set — one document per pipeline state, wired to the shared
     business spine so mail, INDOX and notifications agree. On top of them the repo carries the
     ~14,000 documents an accounting office actually accumulates over a decade.

     This is what makes the table an OPERATOR table rather than a demo: paging has to work, sorting
     has to work on a real distribution, the dashboard counters have to be big, search has to find a
     needle, and the status mix has to include the long tail of failures that only shows up at
     volume. Seeded PRNG — identical on every run and in every screenshot.

     Volume is per instance: סבח carries the decade, אגן is a young second company. That difference
     is the point — switching instances has to visibly change scale, not just names. */
  function ILCG(seed) { var x = seed >>> 0; return function () { x = (x * 1664525 + 1013904223) >>> 0; return x / 4294967296; }; }
  var GEN_CO = [
    ['סבח סוכנויות בע״מ', '514236789'], ['אגן שיווק', '512987654'], ['ישראל קרטון', '513765432'],
    ['דגן תעשיות בע״מ', '515443322'], ['מ. פרידמן בע״מ', '516554433'], ['חברת חשמל לישראל', '500001234'],
    ['בזק בינלאומי', '520043215'], ['ספק הענן בע״מ', '514998877'], ['נכסי הרצל', '511223344'],
    ['דפי הדפסה בע״מ', '513004455'], ['מי אביבים', '500778899'], ['פלאפון', '520011223'],
    ['ביטוח לאומי', '500000001'], ['בנק הפועלים', '520000118'], ['בנק לאומי', '520018078'],
    ['אמזון AWS', '999000111'], ['Google Workspace', '999000222'], ['מוסך מרכזי חיפה', '514667788']
  ];
  var GEN_DTYPE = [
    ['INVOICE',  'חשבונית',        'INV', 46],
    ['RECEIPT',  'קבלה',           'RC',  27],
    ['ORDER',    'הזמנה',          'ORD', 11],
    ['SHIPMENT', 'תעודת משלוח',    'SHP',  9],
    // (the pipeline's own types: it has no «BANK» and no «CREDIT». A bank's statement is a document it does not
    //  recognise, and a credit invoice is an invoice)
    ['UNKNOWN',  'דוח בנק',        'BK',   4],
    ['INVOICE',  'חשבונית זיכוי',  'CRD',  3]
  ];
  var GEN_DW = (function () { var t = 0; GEN_DTYPE.forEach(function (d) { t += d[3]; }); return t; })();
  /* the long tail of failure reasons an operator actually meets — each one needs a different action,
     which is why REQUIRED_ACTION is a sentence and not a code */
  var GEN_FAIL = [
    ['EXTRACTION_FAILED', 'בדיקה ידנית — OCR נכשל'],
    ['EXTRACTION_FAILED', 'הקובץ פגום ולא נפתח'],
    ['NEEDS_REVIEW',      'בדיקת התאמת סכום'],
    ['NEEDS_REVIEW',      'חסר קישור להזמנה'],
    ['NEEDS_REVIEW',      'מספר עוסק מורשה לא תואם'],
    ['NEEDS_REVIEW',      'מסמך כפול — קיים במערכת'],
    // (a status of the pipeline's own: this said 'MISSING', which no screen has a word for, and the dashboard showed it raw)
    ['MISSING_TYPE',      'לא זוהה סוג מסמך תואם — נדרש סיווג ידני']
  ];
  function genDocs(seed, count, endYear, years) {
    var r = ILCG(seed), rows = [], n = 0;
    var end = new Date(endYear, 6, 27).getTime();
    for (var i = 0; i < count; i++) {
      var skew = Math.pow(r(), 1.35);                       // more recent than old, but a real tail
      var daysAgo = Math.round(skew * years * 365) + 1;
      var d = new Date(end - daysAgo * 86400000);
      var pick = r() * GEN_DW, t = GEN_DTYPE[0];
      for (var k = 0; k < GEN_DTYPE.length; k++) { pick -= GEN_DTYPE[k][3]; if (pick <= 0) { t = GEN_DTYPE[k]; break; } }
      var co = GEN_CO[Math.floor(r() * GEN_CO.length)];
      var num = 10000 + Math.floor(r() * 89999);
      // old documents are almost all done; the churn lives in the last few weeks
      var fresh = daysAgo < 30;
      var roll = r();
      var status = 'COMPLETED', action = null, amount = Math.round((80 + r() * 24000) * 100) / 100;
      if (fresh && roll < 0.06) { status = 'TO_EXTRACT'; action = 'ממתין לטיפול'; }   // (the pipeline's resting state; 'PENDING' is nobody's)
      else if (fresh && roll < 0.10) { status = 'IN_PROGRESS'; }
      else if (roll < (fresh ? 0.20 : 0.035)) {
        var f = GEN_FAIL[Math.floor(r() * GEN_FAIL.length)];
        status = f[0]; action = f[1];
        if (status !== 'NEEDS_REVIEW') amount = 0;
      }
      var id = t[2] + '-' + num + '-' + (++n);
      rows.push({
        ID: id, NAME: t[1] + ' ' + num + ' - ' + co[0],
        COMPANY_ID: co[1], COMPANY_NAME: co[0], SHORT_DOC_ID: String(num),
        TYPE: t[0], STATUS: status, REQUIRED_ACTION: action,
        DOC_DATE: d.toISOString().slice(0, 10),
        DOC_TOTAL_AMOUNT: amount,
        SOURCE_TYPE: r() < 0.58 ? 'GMAIL' : 'GOOGLE_DRIVE_FILE',   // (the pipeline's own names for where a document came in)
        TIMESTAMP: d.toISOString().replace('T', ' ').slice(0, 19)
      });
    }
    return rows;
  }

  var DOCS = [
    { ID: 'INV-58231', NAME: 'חשבונית 58231 - סבח סוכנויות', COMPANY_ID: '514236789', COMPANY_NAME: 'סבח סוכנויות בע״מ', SHORT_DOC_ID: '58231', TYPE: 'INVOICE', STATUS: 'COMPLETED', REQUIRED_ACTION: null, DOC_DATE: '2026-07-18', DOC_TOTAL_AMOUNT: 12430.50, SOURCE_TYPE: 'GMAIL', TIMESTAMP: isoAgo(2 * 86400000) },
    { ID: 'ORD-77410', NAME: 'הזמנה 77410 - אגן שיווק', COMPANY_ID: '512987654', COMPANY_NAME: 'אגן שיווק', SHORT_DOC_ID: '77410', TYPE: 'ORDER', STATUS: 'COMPLETED', REQUIRED_ACTION: null, DOC_DATE: '2026-07-17', DOC_TOTAL_AMOUNT: 5230, SOURCE_TYPE: 'GOOGLE_DRIVE_FILE', TIMESTAMP: isoAgo(3 * 86400000) },
    { ID: 'SHP-33012', NAME: 'תעודת משלוח 33012 - ישראל קרטון', COMPANY_ID: '513765432', COMPANY_NAME: 'ישראל קרטון', SHORT_DOC_ID: '33012', TYPE: 'SHIPMENT', STATUS: 'NEEDS_REVIEW', REQUIRED_ACTION: 'בדיקת התאמת סכום', DOC_DATE: '2026-07-20', DOC_TOTAL_AMOUNT: 0, SOURCE_TYPE: 'GOOGLE_DRIVE_FILE', TIMESTAMP: isoAgo(3600000) },
    { ID: 'INV-58244', NAME: 'חשבונית 58244 - סבח סוכנויות', COMPANY_ID: '514236789', COMPANY_NAME: 'סבח סוכנויות בע״מ', SHORT_DOC_ID: '58244', TYPE: 'INVOICE', STATUS: 'IN_PROGRESS', REQUIRED_ACTION: null, DOC_DATE: '2026-07-21', DOC_TOTAL_AMOUNT: 8760.25, SOURCE_TYPE: 'GMAIL', TIMESTAMP: isoAgo(20 * 60000) },
    { ID: 'INV-58198', NAME: 'חשבונית 58198 - דגן תעשיות', COMPANY_ID: '515443322', COMPANY_NAME: 'דגן תעשיות בע״מ', SHORT_DOC_ID: '58198', TYPE: 'INVOICE', STATUS: 'EXTRACTION_FAILED', REQUIRED_ACTION: 'בדיקה ידנית - OCR נכשל', DOC_DATE: '2026-07-15', DOC_TOTAL_AMOUNT: 0, SOURCE_TYPE: 'GMAIL', TIMESTAMP: isoAgo(6 * 86400000) },
    { ID: 'ORD-77355', NAME: 'הזמנה 77355 - מ. פרידמן', COMPANY_ID: '516554433', COMPANY_NAME: 'מ. פרידמן בע״מ', SHORT_DOC_ID: '77355', TYPE: 'ORDER', STATUS: 'COMPLETED', REQUIRED_ACTION: null, DOC_DATE: '2026-07-14', DOC_TOTAL_AMOUNT: 3120, SOURCE_TYPE: 'GOOGLE_DRIVE_FILE', TIMESTAMP: isoAgo(7 * 86400000) },
    { ID: 'SHP-33067', NAME: 'תעודת משלוח 33067 - אגן שיווק', COMPANY_ID: '512987654', COMPANY_NAME: 'אגן שיווק', SHORT_DOC_ID: '33067', TYPE: 'SHIPMENT', STATUS: 'NEEDS_REVIEW', REQUIRED_ACTION: 'חסר קישור להזמנה', DOC_DATE: '2026-07-19', DOC_TOTAL_AMOUNT: 0, SOURCE_TYPE: 'GOOGLE_DRIVE_FILE', TIMESTAMP: isoAgo(5 * 3600000) },
  ];
  // Pull the shared business spine's incoming supplier documents into this repo, so a supplier invoice
  // that arrives in mail (and that notifications alerts about) is the SAME document INDOX shows here —
  // matching supplier, number, amount and status (a failed one shows EXTRACTION_FAILED with 0 amount).
  if (window.__biz) {
    var PFX = { invoice: 'INV', receipt: 'RC', bank: 'BK' };
    var bizDocs = window.__biz.incoming.map(function (d) {
      var failed = d.status === 'failed';
      return {
        ID: (PFX[d.kind] || 'DOC') + '-' + d.number,
        NAME: window.__biz.kindHeOne(d.kind) + ' ' + d.number + ' - ' + d.supplier,
        COMPANY_ID: d.supplier_id, COMPANY_NAME: d.supplier, SHORT_DOC_ID: String(d.number),
        TYPE: window.__biz.kindIndox(d.kind), STATUS: window.__biz.statusIndox(d.status),
        REQUIRED_ACTION: failed ? d.fail_reason : (d.status === 'to_handle' ? 'ממתין לטיפול' : null),
        DOC_DATE: d.date.slice(0, 10), DOC_TOTAL_AMOUNT: failed ? 0 : d.amount,
        SOURCE_TYPE: 'GMAIL', TIMESTAMP: d.date,
      };
    });
    DOCS = bizDocs.concat(DOCS);
  }
  var HISTORY = {}; // ID -> [{event_type, occurred_at, row}]  (newest first)
  DOCS.forEach(function (d) { HISTORY[d.ID] = [{ event_type: 'insert', occurred_at: d.TIMESTAMP, row: clone(d) }]; });
  function pushHistory(d, type) {
    (HISTORY[d.ID] = HISTORY[d.ID] || []).unshift({ event_type: type, occurred_at: d.TIMESTAMP, row: clone(d) });
  }

  var PIPELINE_SEQ = 1;
  function spawnIncoming() {
    var c = COMPANY_POOL[Math.floor(Math.random() * COMPANY_POOL.length)];
    var types = ['INVOICE', 'ORDER', 'SHIPMENT'];
    var t = types[Math.floor(Math.random() * types.length)];
    var prefix = t === 'INVOICE' ? 'INV' : t === 'ORDER' ? 'ORD' : 'SHP';
    var num = 58300 + PIPELINE_SEQ++;
    var typeLabel = t === 'INVOICE' ? 'חשבונית' : t === 'ORDER' ? 'הזמנה' : 'תעודת משלוח';
    var doc = {
      ID: prefix + '-' + num, NAME: typeLabel + ' ' + num + ' - ' + c.name,
      COMPANY_ID: c.id, COMPANY_NAME: c.name, SHORT_DOC_ID: String(num), TYPE: t,
      STATUS: 'NEEDS_REVIEW', REQUIRED_ACTION: 'ממתין לעיבוד', DOC_DATE: today(),
      DOC_TOTAL_AMOUNT: 0, SOURCE_TYPE: Math.random() < 0.5 ? 'GMAIL' : 'GOOGLE_DRIVE_FILE', TIMESTAMP: nowIso(),
    };
    DOCS.unshift(doc);
    HISTORY[doc.ID] = [{ event_type: 'insert', occurred_at: doc.TIMESTAMP, row: clone(doc) }];
    return doc;
  }

  function groupOf(status) {
    if (status === 'COMPLETED') return 'done';
    if (status === 'NEEDS_REVIEW') return 'attention';
    if (status === 'EXTRACTION_FAILED') return 'failed';
    return 'other';
  }

  function findDoc(id) { return DOCS.find(function (d) { return d.ID === id; }); }

  function patchDocument(id, patch) {
    var d = findDoc(id); if (!d) return null;
    Object.assign(d, patch);
    d.TIMESTAMP = nowIso();
    pushHistory(d, 'update');
    return { updated: [d], created: [], events_published: 1 };
  }

  function upsertRows(rows) {
    var created = [], updated = [];
    rows.forEach(function (r) {
      var pk = r.ID;
      if (pk == null || pk === '') { pk = 'DOC-' + Math.random().toString(36).slice(2, 8).toUpperCase(); }
      var existing = findDoc(pk);
      if (existing) {
        Object.assign(existing, r, { ID: pk }); existing.TIMESTAMP = nowIso();
        pushHistory(existing, 'update'); updated.push(existing);
      } else {
        var doc = Object.assign({
          ID: pk, NAME: pk, COMPANY_ID: '', COMPANY_NAME: '', SHORT_DOC_ID: pk, TYPE: 'INVOICE',
          STATUS: 'NEEDS_REVIEW', REQUIRED_ACTION: null, DOC_DATE: today(), DOC_TOTAL_AMOUNT: 0,
          SOURCE_TYPE: '', TIMESTAMP: nowIso(),          // (a row a person wrote came in from nowhere: 'manual' was nobody's word)
        }, r, { ID: pk });
        DOCS.unshift(doc);
        HISTORY[pk] = [{ event_type: 'insert', occurred_at: doc.TIMESTAMP, row: clone(doc) }];
        created.push(doc);
      }
    });
    return {
      success: true, updated: updated, created: created, skipped: [],
      stats: { incoming: rows.length, updated: updated.length, created: created.length, noop: 0, events_published: updated.length + created.length },
    };
  }

  function queryDocs(body) {
    body = body || {};
    var rows = DOCS.slice();
    if (Array.isArray(body.ids) && body.ids.length) {
      var idset = {}; body.ids.forEach(function (i) { idset[i] = 1; });
      rows = rows.filter(function (r) { return idset[r.ID]; });
    }
    if (body.filter && typeof body.filter === 'object') {
      Object.keys(body.filter).forEach(function (k) {
        var v = body.filter[k];
        rows = rows.filter(function (r) { return String(r[k]) === String(v); });
      });
    }
    if (body.search) {
      var q = String(body.search).toLowerCase();
      var cols = (body.search_columns && body.search_columns.length) ? body.search_columns : COLUMNS.map(function (c) { return c.name; });
      rows = rows.filter(function (r) {
        return cols.some(function (c) { return String(r[c] == null ? '' : r[c]).toLowerCase().indexOf(q) !== -1; });
      });
    }
    var total = rows.length;
    if (Array.isArray(body.order) && body.order.length) {
      var ord = body.order[0];
      rows.sort(function (a, b) {
        var av = a[ord.col], bv = b[ord.col];
        if (av == null) av = ''; if (bv == null) bv = '';
        if (av < bv) return ord.dir === 'desc' ? 1 : -1;
        if (av > bv) return ord.dir === 'desc' ? -1 : 1;
        return 0;
      });
    }
    var offset = body.offset || 0, limit = body.limit == null ? 50 : body.limit;
    var page = rows.slice(offset, offset + limit);
    return {
      rows: page, count: page.length,
      total: body.with_count ? total : null,
      truncated: offset + limit < total,
      next_offset: offset + limit < total ? offset + limit : null,
    };
  }

  function syncRepoAction() {
    var scanned = 3 + Math.floor(Math.random() * 5);
    var createdCount = Math.random() < 0.4 ? 1 : 0;
    if (createdCount) spawnIncoming();
    return { success: true, scanned: scanned, events_published: scanned, created: createdCount, changed: Math.max(0, scanned - createdCount - 1) };
  }

  // ----------------------------------------------------------------- auth
  var AUTH_ME = { authenticated: true, username: 'demo', email: 'demo@hacohen.local', groups: ['admin'], is_admin: true };

  // ---------------------------------------------------------------- dashboard
  function computeDashboard() {
    var total = DOCS.length;
    var groups = { done: 0, attention: 0, failed: 0, other: 0 };
    var byStatus = {}, byType = {}, byCompany = {};
    DOCS.forEach(function (d) {
      groups[groupOf(d.STATUS)]++;
      byStatus[d.STATUS] = (byStatus[d.STATUS] || 0) + 1;
      byType[d.TYPE] = (byType[d.TYPE] || 0) + 1;
      byCompany[d.COMPANY_NAME] = (byCompany[d.COMPANY_NAME] || 0) + 1;
    });
    var by_status = Object.keys(byStatus).map(function (s) { return { status: s, count: byStatus[s], group: groupOf(s) }; });
    var by_type = Object.keys(byType).map(function (t) { return { type: t, count: byType[t] }; });
    var top_companies = Object.keys(byCompany)
      .map(function (n) { return { name: n, count: byCompany[n] }; })
      .sort(function (a, b) { return b.count - a.count; });
    var extractionFields = [
      { key: 'COMPANY_ID', label: 'מזהה חברה', pct: Math.min(97, 70 + groups.done * 4) },
      { key: 'DOC_DATE', label: 'תאריך מסמך', pct: Math.min(96, 65 + groups.done * 4) },
      { key: 'DOC_TOTAL_AMOUNT', label: 'סכום', pct: Math.min(94, 55 + groups.done * 5) },
      { key: 'TYPE', label: 'סוג מסמך', pct: 96 },
    ];
    var overall = Math.round(extractionFields.reduce(function (a, f) { return a + f.pct; }, 0) / extractionFields.length);
    var recent = DOCS.slice()
      .sort(function (a, b) { return new Date(b.TIMESTAMP) - new Date(a.TIMESTAMP); })
      .slice(0, 6)
      .map(function (d) { return { id: d.ID, name: d.NAME, status: d.STATUS, type: d.TYPE, company: d.COMPANY_NAME, date: d.DOC_DATE }; });
    return {
      reachable: true, total: total, completed: groups.done, attention: groups.attention, failed: groups.failed,
      companies: Object.keys(byCompany).length, groups: groups, by_status: by_status, by_type: by_type,
      top_companies: top_companies, extraction: { fields: extractionFields, overall: overall }, recent: recent,
    };
  }

  // ------------------------------------------------------------------- sync
  // Eight pipes across FOUR real connections (two mail accounts, two drives) — the shape a company
  // pushing 3,000+ documents a month actually runs. Every `connection` id and every label/folder path
  // below exists in the shared spine, i.e. in the Drive and Mail UIs.
  //
  // `fallback_type` is the operator's most useful lever and is NOT a cosmetic tag: when extraction
  // cannot determine a document's type, the pipe's own location tells you what it must be — anything
  // dropped in נכנס/קבלות is a receipt. That is the real bs-gdrive-sync case, and it converts a whole
  // class of "סוג לא זוהה" failures into a one-click fix.
  var REGISTRY = [
    { name: 'gmail-invoices', source: 'gmail', engine: 'n8n', processor_wf: 'ingest-gmail-invoices',
      connection: 'gmail_office', type_hint: 'INVOICE', fallback_type: 'INVOICE', enabled: true,
      batch: { take: 40, chunk: 10, timeout_min: 10, schedule_min: 5 },
      labels: { to_sync: 'אינדוקס - חשבוניות - לטיפול', synced: 'אינדוקס - חשבוניות - טופל', failed: 'אינדוקס - נכשל' },
      claim_label: 'אינדוקס - חשבוניות - בעיבוד' },
    { name: 'gmail-receipts', source: 'gmail', engine: 'n8n', processor_wf: 'ingest-gmail-receipts',
      connection: 'gmail_office', type_hint: 'RECEIPT', fallback_type: 'RECEIPT', enabled: true,
      batch: { take: 40, chunk: 10, timeout_min: 10, schedule_min: 10 },
      labels: { to_sync: 'אינדוקס - קבלות - לטיפול', synced: 'אינדוקס - קבלות - טופל', failed: 'אינדוקס - נכשל' },
      claim_label: 'אינדוקס - קבלות - בעיבוד' },
    { name: 'gmail-bank', source: 'gmail', engine: 'n8n', processor_wf: 'ingest-gmail-bank',
      // (no fixed type: the pipeline has no «BANK_REPORT» — a bank's statement is typed by detection, or not at all)
      connection: 'gmail_office', type_hint: null, fallback_type: null, enabled: true,
      batch: { take: 20, chunk: 5, timeout_min: 15, schedule_min: 60 },
      labels: { to_sync: 'אינדוקס - דוחות בנק - לטיפול', synced: 'אינדוקס - חשבוניות - טופל', failed: 'אינדוקס - נכשל' },
      claim_label: 'אינדוקס - דוחות בנק - בעיבוד' },
    { name: 'outlook-suppliers', source: 'gmail', engine: 'n8n', processor_wf: 'ingest-outlook-suppliers',
      connection: 'outlook_admin', type_hint: 'INVOICE', fallback_type: 'INVOICE', enabled: true,
      batch: { take: 25, chunk: 5, timeout_min: 12, schedule_min: 15 },
      labels: { to_sync: 'ספקים', synced: 'הנהלת חשבונות', failed: 'דוחות גיול' },
      claim_label: 'ספקים/בעיבוד' },
    // the real case: a folder that IS its type. Anything here is a receipt, detected or not.
    { name: 'bs-gdrive-sync', source: 'drive', engine: 'n8n', processor_wf: 'ingest-bs-gdrive',
      connection: 'acc_office', type_hint: 'RECEIPT', fallback_type: 'RECEIPT', enabled: true,
      batch: { take: 50, chunk: 10, timeout_min: 8, schedule_min: 10 },
      pairs: [{ from: 'נכנס/קבלות', to: 'ארכיון/קבלות' }], dest_folder: 'ארכיון/קבלות',
      failed_folder: 'ארכיון/נכשל' },
    { name: 'gdrive-invoices', source: 'drive', engine: 'n8n', processor_wf: 'ingest-gdrive-invoices',
      connection: 'acc_office', type_hint: 'INVOICE', fallback_type: 'INVOICE', enabled: true,
      batch: { take: 50, chunk: 10, timeout_min: 8, schedule_min: 10 },
      pairs: [{ from: 'נכנס/חשבוניות', to: 'ארכיון/חשבוניות' }], dest_folder: 'ארכיון/חשבוניות',
      failed_folder: 'ארכיון/נכשל' },
    { name: 'gdrive-shipments', source: 'drive', engine: 'n8n', processor_wf: 'ingest-gdrive-shipments',
      connection: 'acc_office', type_hint: 'SHIPMENT', fallback_type: 'SHIPMENT', enabled: true,
      batch: { take: 30, chunk: 10, timeout_min: 8, schedule_min: 20 },
      pairs: [{ from: 'נכנס/תעודות משלוח', to: 'ארכיון/חשבוניות' }], dest_folder: 'ארכיון/חשבוניות' },
    // parked on a connection the spine marks `error` — this is the pipe that strands items in an
    // unknown state, which is exactly the situation the board has to make obvious and recoverable.
    { name: 'dropbox-archive', source: 'drive', engine: 'n8n', processor_wf: 'ingest-dropbox',
      connection: 'acc_dropbox', type_hint: 'INVOICE', fallback_type: 'INVOICE', enabled: true,
      batch: { take: 20, chunk: 5, timeout_min: 10, schedule_min: 30 },
      pairs: [{ from: 'Inbox', to: 'Archive/2026' }], dest_folder: 'Archive/2026' },
  ];

  // ── the sync engine works on ITEMS, not counters ────────────────────────────────────────────────
  // Counts used to be four integers per sync that drifted randomly. You cannot build "move an item to
  // another state" on integers — there is nothing to move, and a moved count would be contradicted by
  // the next random tick. So each pipe owns a queue of real items and every count is DERIVED from it:
  // one source of truth, so a move, a run and the bar can never disagree. See sim/INDOX-SYNC.md §3.
  var STATES = ['to_sync', 'in_progress', 'synced', 'failed'];
  var ITEM_SEQ = 1;

  // Failure REASONS, not one blob of text. An operator at 3,000 docs/month never fixes failures one by
  // one — they fix a *cause* and re-queue everything behind it. So every failure carries a machine
  // code the board can group and bulk-act on, plus whether re-running could plausibly help:
  //   fixable   — re-queue after the cause is addressed (or immediately, for transient ones)
  //   type      — extraction couldn't classify it; the pipe's fallback_type answers it in one click
  //   terminal  — re-running changes nothing (duplicate/corrupt); the honest action is skip
  var FAIL_KINDS = [
    { code: 'ocr',        he: 'OCR נכשל — קובץ מטושטש',            group: 'fixable',  w: 22 },
    { code: 'type',       he: 'סוג המסמך לא זוהה',                  group: 'type',     w: 26 },
    { code: 'company',    he: 'חסר מזהה חברה / חברה לא מזוהה',      group: 'fixable',  w: 16 },
    { code: 'connection', he: 'החיבור נותק באמצע — מצב לא ידוע',    group: 'fixable',  w: 14 },
    { code: 'timeout',    he: 'פסק זמן בעיבוד',                     group: 'fixable',  w: 8 },
    { code: 'duplicate',  he: 'כפילות — המסמך כבר קיים בטבלה',      group: 'terminal', w: 9 },
    { code: 'corrupt',    he: 'קובץ פגום / לא נתמך',                group: 'terminal', w: 5 },
  ];
  function pickFail(forceCode) {
    if (forceCode) return FAIL_KINDS.filter(function (f) { return f.code === forceCode; })[0] || FAIL_KINDS[0];
    var tot = FAIL_KINDS.reduce(function (a, f) { return a + f.w; }, 0), r = Math.random() * tot;
    for (var i = 0; i < FAIL_KINDS.length; i++) { r -= FAIL_KINDS[i].w; if (r <= 0) return FAIL_KINDS[i]; }
    return FAIL_KINDS[0];
  }
  var SUBJECTS = {
    INVOICE: ['חשבונית מס', 'חשבונית עסקה', 'חשבונית זיכוי'],
    RECEIPT: ['קבלה', 'קבלה על תשלום', 'אישור תשלום'],
    ORDER: ['הזמנת רכש', 'הזמנה', 'אישור הזמנה'],
    SHIPMENT: ['תעודת משלוח', 'תעודת משלוח מרוכזת'],
    BALANCE_SHEET: ['דוח גיול', 'מאזן בוחן'],
    UNKNOWN: ['מסמך סרוק', 'קובץ ללא סיווג', 'דוח בנק', 'תנועות עו״ש'],
  };
  function mkItem(entry, state, opts) {
    opts = opts || {};
    var hinted = state === 'failed' && opts.fail === 'type';
    // An unclassified document shows as UNKNOWN until something resolves it. A pipe with no
    // type_hint has no location-implied answer, so its documents are typed by detection alone —
    // modelled here by picking from the plausible set rather than assuming one.
    var DETECTED = ['INVOICE', 'RECEIPT', 'ORDER', 'SHIPMENT'];
    var type = hinted ? 'UNKNOWN'
      : (entry.type_hint || DETECTED[Math.floor(Math.random() * DETECTED.length)]);
    var subs = SUBJECTS[type] || SUBJECTS.INVOICE;
    var sup = COMPANY_POOL[Math.floor(Math.random() * COMPANY_POOL.length)];
    var num = 10000 + Math.floor(Math.random() * 89999);
    var ageMin = state === 'synced' ? 60 + Math.random() * 40000
      : state === 'to_sync' ? Math.random() * 240
      : state === 'failed' ? 30 + Math.random() * 6000
      : Math.random() * 200;
    var f = state === 'failed' ? pickFail(opts.fail) : null;
    return {
      id: 'it-' + (ITEM_SEQ++) + '-' + Math.random().toString(36).slice(2, 6),
      sync: entry.name,
      title: subs[Math.floor(Math.random() * subs.length)] + ' ' + num + ' — ' + sup.name,
      company: sup.name,
      kind: type,
      detected: !hinted,                       // false ⇒ the fallback_type is what would classify it
      source: entry.source || 'drive',
      connection: entry.connection || null,
      size_kb: 40 + Math.floor(Math.random() * 900),
      state: state,
      updated_at: isoAgo(Math.round(ageMin * 60000)),
      claimed_at: state === 'in_progress' ? isoAgo(Math.round(Math.random() * 200 * 60000)) : null,
      error: f ? f.he : null,
      error_code: f ? f.code : null,
      error_group: f ? f.group : null,
    };
  }
  /** Seed a pipe's queue from a {state: n} shape. `failMix` forces specific failure codes. */
  function seedItems(entry, shape, failMix) {
    var out = [];
    STATES.forEach(function (st) {
      for (var i = 0; i < (shape[st] || 0); i++) {
        var forced = (st === 'failed' && failMix) ? failMix[i % failMix.length] : null;
        out.push(mkItem(entry, st, { fail: forced }));
      }
    });
    return out;
  }
  /** An item claimed longer ago than the pipe's timeout is STUCK — nothing is coming back for it. */
  function isStuck(entry, it) {
    if (it.state !== 'in_progress' || !it.claimed_at) return false;
    var mins = (Date.now() - new Date(it.claimed_at).getTime()) / 60000;
    return mins > ((entry.batch && entry.batch.timeout_min) || 10);
  }
  function itemsOf(inst, name) { return (inst.items && inst.items[name]) || []; }
  function countsOf(inst, name) {
    var c = { to_sync: 0, in_progress: 0, synced: 0, failed: 0 };
    itemsOf(inst, name).forEach(function (it) { if (c[it.state] != null) c[it.state]++; });
    return c;
  }
  /** One tick of the pipeline for ONE instance: claimed work completes, occasionally fails, and new
   *  material arrives at enabled pipes. Only ever moves items — never invents counts. */
  function advanceSync(inst) {
    (inst.registry || []).forEach(function (entry) {
      var list = itemsOf(inst, entry.name);
      var inprog = list.filter(function (i) { return i.state === 'in_progress'; });
      inprog.forEach(function (it) {
        if (Math.random() < 0.55) {
          it.state = Math.random() < 0.93 ? 'synced' : 'failed';
          it.updated_at = nowIso();
          /* a failure has to carry its taxonomy, not just a string: the board groups by error_group
             (fixable / type / terminal) to decide which action it can even offer */
          var f = it.state === 'failed' ? pickFail() : null;
          it.error = f ? f.he : null;
          it.error_code = f ? f.code : null;
          it.error_group = f ? f.group : null;
        }
      });
      if (entry.enabled !== false) {
        // scheduled pickup: the pipe claims its own backlog without anyone pressing Run
        var waiting = list.filter(function (i) { return i.state === 'to_sync'; });
        if (waiting.length && Math.random() < 0.5) {
          waiting.slice(0, 1 + Math.floor(Math.random() * 2)).forEach(function (it) {
            it.state = 'in_progress'; it.updated_at = nowIso();
          });
        }
        if (Math.random() < 0.3) { list.push(mkItem(entry, 'to_sync')); }
      }
    });
  }
  /** Claim up to `take` waiting items — this IS what "running" means (to_sync → in_progress). */
  function runPipe(inst, entry) {
    var list = itemsOf(inst, entry.name);
    var take = (entry.batch && entry.batch.take) || 20;
    var claimed = 0;
    list.forEach(function (it) {
      if (claimed < take && it.state === 'to_sync') { it.state = 'in_progress'; it.updated_at = nowIso(); claimed++; }
    });
    entry.last_run = nowIso();
    return claimed;
  }
  function computeSyncStatus(inst, sync) {
    var per_sync = {}, waiting = 0, inprog = 0;
    (inst.registry || []).forEach(function (e) {
      var c = countsOf(inst, e.name);
      per_sync[e.name] = c; waiting += c.to_sync; inprog += c.in_progress;
    });
    if (sync && per_sync[sync]) { var only = {}; only[sync] = per_sync[sync]; per_sync = only; }
    return { ok: true, action: 'status', at_rest: waiting === 0 && inprog === 0,
      waiting: waiting, in_progress: inprog, per_sync: per_sync, source: 'supabase' };
  }
  /** Registry entries enriched with their live state — config and state travel together (§2). */
  function registryWithLive(inst) {
    return (inst.registry || []).map(function (e) {
      var list = itemsOf(inst, e.name);
      var fails = {};
      list.forEach(function (it) {
        if (it.state === 'failed' && it.error_code) {
          fails[it.error_code] = fails[it.error_code] || { code: it.error_code, he: it.error, group: it.error_group, n: 0 };
          fails[it.error_code].n++;
        }
      });
      var conn = connById(e.connection);
      return Object.assign({}, e, {
        enabled: e.enabled !== false,
        counts: countsOf(inst, e.name),
        // stuck = claimed longer ago than this pipe's timeout; nothing is coming back for it
        stuck: list.filter(function (it) { return isStuck(e, it); }).length,
        // failures grouped by CAUSE, so the board can offer one action per cause instead of per item
        failures: Object.keys(fails).map(function (k) { return fails[k]; }).sort(function (x, y) { return y.n - x.n; }),
        // the pipe is only as healthy as the account it pulls from (spine-owned status)
        connection_label: conn ? conn.label : null,
        connection_identity: conn ? conn.identity : null,
        connection_status: conn ? conn.status : 'ok',
        connection_reason: conn ? (conn.reason || '') : '',
      });
    });
  }

  // ------------------------------------------------------------- extraction
  var EXTRACT_TYPES = { invoice: 'חשבונית', shipment: 'תעודת משלוח', balance_sheet: 'דוח גיול' };
  function fieldsForType(type) {
    if (type === 'invoice') return ['invoice_id', 'date', 'amount', 'company'];
    if (type === 'shipment') return ['shipment_id', 'date', 'linked_order'];
    if (type === 'balance_sheet') return ['date', 'amount'];
    return ['company'];
  }
  function makeExtractionResult(doc) {
    var truth = doc.truth || {};
    var fields = fieldsForType(doc.type);
    var values = fields.map(function (f) {
      var want = truth[f] != null ? String(truth[f]) : null;
      var miss = Math.random() < 0.08;
      var got = want == null ? null : (miss ? want + '?' : want);
      return { field: f, got: got, want: want, ok: want == null ? null : (got === want) };
    });
    var ok = values.filter(function (v) { return v.ok === true; }).length;
    var total = values.filter(function (v) { return v.ok !== null; }).length;
    return {
      id: doc.id, type: doc.type, file: doc.file,
      hash: 'sha1:' + Math.random().toString(16).slice(2, 10),
      detected_type: doc.type, type_ok: true,
      values: values, ok: ok, total: total,
      elapsed_s: Math.round((1.2 + Math.random() * 2.4) * 10) / 10,
      at: nowSec(), error: null,
      ops: {
        ocr_engine: 'tesseract-heb+eng', ocr_ms: 400 + Math.floor(Math.random() * 600),
        ocr_at: nowIso(), ocr_apitools_version: '1.14.2', apitools_version: '1.14.2',
        base_hook_s: 0.4, type_hook_s: 0.6,
        value_ms: values.reduce(function (acc, v) { acc[v.field] = 150 + Math.floor(Math.random() * 300); return acc; }, {}),
      },
      draw_category: doc.type === 'balance_sheet' ? 'bs' : doc.type,
    };
  }
  var EXTRACT_DOCS = [
    { id: 'invoice/inv_1042.pdf', type: 'invoice', type_label: 'חשבונית', file: 'inv_1042.pdf', truth: { invoice_id: '1042', date: '01/06/2026', amount: '4320.00', company: '514236789' }, result: null },
    { id: 'invoice/inv_1077.pdf', type: 'invoice', type_label: 'חשבונית', file: 'inv_1077.pdf', truth: { invoice_id: '1077', date: '14/06/2026', amount: '980.00', company: '512987654' }, result: null },
    { id: 'shipment/shp_881.pdf', type: 'shipment', type_label: 'תעודת משלוח', file: 'shp_881.pdf', truth: { shipment_id: '881', date: '20/06/2026', linked_order: '77410' }, result: null },
    { id: 'shipment/shp_902.pdf', type: 'shipment', type_label: 'תעודת משלוח', file: 'shp_902.pdf', truth: { shipment_id: '902', date: '22/06/2026', linked_order: '77355' }, result: null },
    { id: 'balance_sheet/bs_q1.pdf', type: 'balance_sheet', type_label: 'דוח גיול', file: 'bs_q1.pdf', truth: { date: '31/03/2026', amount: '128400.00' }, result: null },
    { id: 'balance_sheet/bs_q2.pdf', type: 'balance_sheet', type_label: 'דוח גיול', file: 'bs_q2.pdf', truth: { date: '30/06/2026', amount: '156900.00' }, result: null },
  ];
  EXTRACT_DOCS[0].result = makeExtractionResult(EXTRACT_DOCS[0]);
  EXTRACT_DOCS[4].result = makeExtractionResult(EXTRACT_DOCS[4]);
  var EXTRACT_UPLOADS = [];
  var EXTRACT_HISTORY = {}; // docId -> [{run_id, scope, run_status, started, result}]
  var EXTRACT_RUNS = []; // newest first; each has _queue/_results (stripped by publicRun)

  function allExtractDocs() { return EXTRACT_DOCS.concat(EXTRACT_UPLOADS); }
  function findExtractDoc(id) { return allExtractDocs().find(function (d) { return d.id === id; }); }

  function startExtractionRun(ids) {
    var docs = (ids && ids.length) ? ids.map(findExtractDoc).filter(Boolean) : EXTRACT_DOCS.slice();
    var run = {
      run_id: rid('run_'), status: 'running', scope: (ids && ids.length) ? 'selected' : 'all',
      docs_total: docs.length, done: 0, ok: 0, total: 0, errors: 0,
      current: docs.length ? docs[0].id : null, started: nowSec(), finished: null,
      _queue: docs.map(function (d) { return d.id; }), _results: {},
    };
    EXTRACT_RUNS.unshift(run);
    return run;
  }
  function tickExtractionRun(run) {
    if (run.status !== 'running') return run;
    if (run._queue.length === 0) { run.status = 'done'; run.finished = nowSec(); run.current = null; return run; }
    var docId = run._queue.shift();
    var doc = findExtractDoc(docId);
    if (doc) {
      var res = makeExtractionResult(doc);
      doc.result = res;
      run._results[docId] = res;
      run.ok += res.ok; run.total += res.total;
      if (res.error) run.errors++;
      (EXTRACT_HISTORY[docId] = EXTRACT_HISTORY[docId] || []).unshift({ run_id: run.run_id, scope: run.scope, run_status: 'done', started: res.at, result: res });
    }
    run.done++;
    run.current = run._queue.length ? run._queue[0] : null;
    if (run.done >= run.docs_total) { run.status = 'done'; run.finished = nowSec(); run.current = null; }
    return run;
  }
  function publicRun(run) {
    return {
      run_id: run.run_id, status: run.status, scope: run.scope, docs_total: run.docs_total,
      done: run.done, ok: run.ok, total: run.total, errors: run.errors, current: run.current,
      started: run.started, finished: run.finished,
    };
  }
  function cancelExtractionRun(id) {
    var run = EXTRACT_RUNS.find(function (r) { return r.run_id === id; });
    if (run && run.status === 'running') { run.status = 'cancelled'; run.finished = nowSec(); run.current = null; run._queue = []; }
  }
  function rerunExtractionDoc(docId, fresh) {
    var doc = findExtractDoc(docId); if (!doc) return null;
    var res = makeExtractionResult(doc);
    doc.result = res;
    (EXTRACT_HISTORY[docId] = EXTRACT_HISTORY[docId] || []).unshift({ run_id: rid(fresh ? 'fresh_' : 'rerun_'), scope: 'single', run_status: 'done', started: res.at, result: res });
    return res;
  }
  function handleUpload(fd) {
    var file = fd && fd.get ? fd.get('file') : null;
    var name = (file && file.name) || ('upload_' + Date.now() + '.pdf');
    var id = 'upload/' + name;
    var doc = { id: id, type: 'upload', type_label: 'העלאה', file: name, truth: {}, result: null };
    EXTRACT_UPLOADS.unshift(doc);
    var res = makeExtractionResult(Object.assign({}, doc, { type: 'invoice', truth: {} }));
    res.id = id; res.type = 'upload'; res.detected_type = 'invoice'; res.type_ok = null;
    doc.result = res;
    (EXTRACT_HISTORY[id] = EXTRACT_HISTORY[id] || []).unshift({ run_id: 'upload', scope: 'upload', run_status: 'done', started: res.at, result: res });
    return res;
  }

  var QUERIES = {
    q_v3_type: { action: 'find option', action_value: ['חשבונית', 'תעודת משלוח', 'הזמנה', 'דוח גיול'], scope: 'block' },
    q_v3_company: { action: 'find after', action_value: ['ח.פ', 'עוסק מורשה'], scope: 'row', value_regex: '\\d{8,9}', fallbacks: [{ action: 'find regex', action_value: '\\d{9}', fulltext_fallback: true }] },
    q_v3_date_base: { action: 'find after', action_value: ['תאריך'], scope: 'row', value_regex: '\\d{2}/\\d{2}/\\d{4}' },
    q_v3_invoice_id: { action: 'find after', action_value: ['חשבונית מס'], scope: 'row' },
    q_v3_date_invoice: { action: 'find after', action_value: ['תאריך חשבונית'], scope: 'row' },
    q_v3_amount_invoice: { action: 'find near', action_value: ['סה"כ לתשלום'], scope: 'block', select: 'nearest', value_validations: [{ validation_type: 'is_money' }] },
    q_v3_shipment_id: { action: 'find after', action_value: ['תעודת משלוח מס'], scope: 'row' },
    q_v3_date_shipment: { action: 'find after', action_value: ['תאריך'], scope: 'row' },
    q_v3_amount_shipment: { action: 'find near', action_value: ['סה"כ'], scope: 'block' },
    q_v3_linked_shipment: { action: 'find after', action_value: ['תעודת משלוח מקושרת'], scope: 'row' },
    q_v3_linked_order: { action: 'find after', action_value: ['הזמנתכם'], scope: 'row' },
    q_v3_order_id: { action: 'find after', action_value: ['הזמנה מס'], scope: 'row' },
    q_v3_date_bs: { action: 'find after', action_value: ['לתאריך'], scope: 'row' },
    q_v3_amount_bs: { action: 'find near', action_value: ['יתרה'], scope: 'block' },
    q_v3_routing: {
      base: { TYPE: 'q_v3_type', COMPANY_ID: 'q_v3_company', DATE: 'q_v3_date_base' },
      invoice: { INVOICE_ID: 'q_v3_invoice_id', DATE: 'q_v3_date_invoice', AMOUNT: 'q_v3_amount_invoice' },
      shipment: { SHIPMENT_ID: 'q_v3_shipment_id', DATE: 'q_v3_date_shipment', LINKED_ORDER: 'q_v3_linked_shipment' },
      bs: { DATE: 'q_v3_date_bs', AMOUNT: 'q_v3_amount_bs' },
    },
  };

  // -------------------------------------------------------------- settings
  var EDITABLE_KEYS = ['auto_sync_enabled', 'max_ocr_retries', 'extraction_timeout_s'];
  var SETTINGS = [
    { key: 'auto_sync_enabled', value: 'true' },
    { key: 'max_ocr_retries', value: '3' },
    { key: 'extraction_timeout_s', value: '45' },
    { key: 'pipeline_version', value: 'v3.4.1' },
    { key: 'q_v3_type', value: JSON.stringify(QUERIES.q_v3_type) },
    { key: 'q_v3_company', value: JSON.stringify(QUERIES.q_v3_company) },
    { key: 'q_v3_routing', value: JSON.stringify(QUERIES.q_v3_routing) },
  ];
  var COMPANIES = [
    { id: '1', 'שם חברה': 'סבח סוכנויות בע״מ', 'מזהה 1': '514236789', 'מזהה 2': '', 'מייל 1': 'person138@example.com', 'מייל 2': '', 'שם ספק מפריוריטי': 'SABAH', 'הוראות לAI לחילוץ דוח גיול': '', TRUSTED_SOURCE_TYPES: 'gmail,drive', extra: '', created_at: '2026-01-12' },
    { id: '2', 'שם חברה': 'אגן שיווק', 'מזהה 1': '512987654', 'מזהה 2': '', 'מייל 1': 'person139@example.com', 'מייל 2': '', 'שם ספק מפריוריטי': 'AGAN', 'הוראות לAI לחילוץ דוח גיול': '', TRUSTED_SOURCE_TYPES: 'drive', extra: '', created_at: '2026-02-03' },
    { id: '3', 'שם חברה': 'ישראל קרטון', 'מזהה 1': '513765432', 'מזהה 2': '', 'מייל 1': '', 'מייל 2': '', 'שם ספק מפריוריטי': '', 'הוראות לAI לחילוץ דוח גיול': '', TRUSTED_SOURCE_TYPES: 'drive', extra: '', created_at: '2026-03-21' },
  ];
  var TAG_RULES = [
    { id: '1', EVENT: 'on_ingest', KEY: 'TYPE', LABEL: 'סיווג לפי מילת מפתח', RULE: 'contains:חשבונית->INVOICE', TYPE: 'classify', 'VALIDATION STATUS': 'ok', 'VALIDATION ERRORS': '', created_at: '2026-01-05', row_number: 1, label_id: '' },
    { id: '2', EVENT: 'on_ingest', KEY: 'TYPE', LABEL: 'סיווג תעודת משלוח', RULE: 'contains:תעודת משלוח->SHIPMENT', TYPE: 'classify', 'VALIDATION STATUS': 'ok', 'VALIDATION ERRORS': '', created_at: '2026-01-05', row_number: 2, label_id: '' },
  ];
  function tableStore(table) { if (table === 'companies') return COMPANIES; if (table === 'tag_rules') return TAG_RULES; return null; }
  function patchConfigRow(table, id, key, value) {
    var store = tableStore(table); if (!store) return { ok: false, error: 'unknown table' };
    var row = store.find(function (r) { return String(r.id) === String(id); });
    if (!row) return { ok: false, error: 'not found' };
    row[key] = value; return { ok: true, row: row };
  }
  function addConfigRow(table, seed) {
    var store = tableStore(table); if (!store) return { ok: false, error: 'unknown table' };
    var row = Object.assign({ id: String(Date.now()), created_at: today() }, seed || {});
    store.unshift(row); return { ok: true, row: row };
  }
  function deleteConfigRow(table, id) {
    var store = tableStore(table); if (!store) return { ok: false, error: 'unknown table' };
    var idx = store.findIndex(function (r) { return String(r.id) === String(id); });
    if (idx === -1) return { ok: false, error: 'not found' };
    store.splice(idx, 1); return { ok: true };
  }

  // ═══════════════════════════════════════════════════════════════════════════════════════════════
  // INSTANCES — a full INDOX per company, not just a repo per company.
  // ═══════════════════════════════════════════════════════════════════════════════════════════════
  // An instance owns EVERYTHING that makes an INDOX what it is: its final table (repo config +
  // documents + history), its sync registry, AND its settings — meaning the settings key/value store,
  // the companies table, the tag-rules table and the extraction queries. Switching instance swaps all
  // of them together, so two companies never share a table, a rule, or a setting.
  //
  // Mechanism: the module-scope stores above (DOCS/HISTORY/REGISTRY/SETTINGS/COMPANIES/TAG_RULES/
  // QUERIES/REPOS) stay the *live* pointers every handler already reads; `activate()` re-points them at
  // the chosen instance. Arrays are held by reference, so in-place mutation (DOCS.unshift, splice, …)
  // writes through to the owning instance with no per-handler change.
  function mkInstance(spec) {
    return {
      id: spec.id, label: spec.label, company: spec.company, color: spec.color,
      status: spec.status || 'ok', reason: spec.reason || '', builtin: !!spec.builtin,
      created_at: spec.created_at || nowIso(),
      repo: spec.repo, docs: spec.docs, history: spec.history || {}, registry: spec.registry,
      settings: spec.settings, editableKeys: spec.editableKeys || EDITABLE_KEYS.slice(),
      companies: spec.companies, tagRules: spec.tagRules, queries: spec.queries,
    };
  }

  // ── instance 1 — סבח סוכנויות (the seed data defined above; supabase-backed, gmail+drive) ────────
  var INST_SABACH = mkInstance({
    id: REPO_NAME, label: 'סבח סוכנויות', company: 'סבח סוכנויות בע״מ', color: '#56693f',   // the office's olive, as a value (an instance's colour is data: a colour field edits it)
    builtin: true, status: 'ok', created_at: isoAgo(45 * 86400000),
    repo: REPOS[0], docs: DOCS, history: HISTORY, registry: REGISTRY,
    settings: SETTINGS, companies: COMPANIES, tagRules: TAG_RULES, queries: QUERIES,
  });

  // ── instance 2 — אגן שיווק (a genuinely different INDOX: gsheet backend, own table + column set,
  //    drive-only registry, own settings values, own companies/tag-rules) ───────────────────────────
  var AGAN_COLUMNS = [
    { name: 'ID', type: 'string', nullable: false },
    { name: 'NAME', type: 'string' },
    { name: 'COMPANY_NAME', type: 'string' },
    { name: 'TYPE', type: 'string' },
    { name: 'STATUS', type: 'string' },
    { name: 'REQUIRED_ACTION', type: 'string', nullable: true },
    { name: 'DOC_DATE', type: 'date' },
    { name: 'DOC_TOTAL_AMOUNT', type: 'number' },
    { name: 'SOURCE_TYPE', type: 'string' },
    { name: 'TIMESTAMP', type: 'timestamp' },
  ];
  var AGAN_DOCS = [
    { ID: 'AG-ORD-4471', NAME: 'הזמנה 4471 - ספקי אריזה', COMPANY_ID: '512987654', COMPANY_NAME: 'אגן שיווק', SHORT_DOC_ID: '4471', TYPE: 'ORDER', STATUS: 'COMPLETED', REQUIRED_ACTION: null, DOC_DATE: '2026-07-22', DOC_TOTAL_AMOUNT: 18240, SOURCE_TYPE: 'GOOGLE_DRIVE_FILE', TIMESTAMP: isoAgo(86400000) },
    { ID: 'AG-SHP-1188', NAME: 'תעודת משלוח 1188 - מחסן צפון', COMPANY_ID: '512987654', COMPANY_NAME: 'אגן שיווק', SHORT_DOC_ID: '1188', TYPE: 'SHIPMENT', STATUS: 'NEEDS_REVIEW', REQUIRED_ACTION: 'חסרה חתימת מקבל', DOC_DATE: '2026-07-23', DOC_TOTAL_AMOUNT: 0, SOURCE_TYPE: 'GOOGLE_DRIVE_FILE', TIMESTAMP: isoAgo(4 * 3600000) },
    { ID: 'AG-ORD-4468', NAME: 'הזמנה 4468 - חומרי גלם', COMPANY_ID: '512987654', COMPANY_NAME: 'אגן שיווק', SHORT_DOC_ID: '4468', TYPE: 'ORDER', STATUS: 'COMPLETED', REQUIRED_ACTION: null, DOC_DATE: '2026-07-16', DOC_TOTAL_AMOUNT: 9615.75, SOURCE_TYPE: 'GOOGLE_DRIVE_FILE', TIMESTAMP: isoAgo(8 * 86400000) },
    { ID: 'AG-SHP-1174', NAME: 'תעודת משלוח 1174 - מחסן דרום', COMPANY_ID: '512987654', COMPANY_NAME: 'אגן שיווק', SHORT_DOC_ID: '1174', TYPE: 'SHIPMENT', STATUS: 'IN_PROGRESS', REQUIRED_ACTION: null, DOC_DATE: '2026-07-24', DOC_TOTAL_AMOUNT: 0, SOURCE_TYPE: 'GOOGLE_DRIVE_FILE', TIMESTAMP: isoAgo(45 * 60000) },
  ];
  var AGAN_HISTORY = {};
  AGAN_DOCS.forEach(function (d) { AGAN_HISTORY[d.ID] = [{ event_type: 'insert', occurred_at: d.TIMESTAMP, row: clone(d) }]; });
  var AGAN_QUERIES = clone(QUERIES);
  var INST_AGAN = mkInstance({
    id: 'indox-agan-shivuk', label: 'אגן שיווק', company: 'אגן שיווק', color: '#1a73e8',
    status: 'ok', created_at: isoAgo(11 * 86400000),
    repo: {
      name: 'indox-agan-shivuk', backend: 'gsheet', primary_key: 'ID', columns: AGAN_COLUMNS,
      priority_sync_columns: ['STATUS'],
      active: true, poll_interval_seconds: 60,
      gsheet: { sheet_name: 'INDOX_AGAN', spreadsheet_id: '1AgAnShIvUk_sim_sheet_id', spreadsheet_title: 'אגן שיווק — מסמכים נכנסים', gid: 0, editors: ['person139@example.com'] },
      created_at: isoAgo(11 * 86400000), updated_at: isoAgo(5 * 3600000),
    },
    docs: AGAN_DOCS, history: AGAN_HISTORY,
    registry: [{
      name: 'drive-agan-orders', source: 'drive', engine: 'n8n', processor_wf: 'ingest-drive-agan-orders',
      connection: 'drive-local', fallback_type: 'ORDER', enabled: true,
      type_hint: 'ORDER', batch: { take: 25, chunk: 5, timeout_min: 12, schedule_min: 15 },
      pairs: [{ from: 'אגן/נכנס/הזמנות', to: 'אגן/ארכיון/הזמנות' }], dest_folder: 'אגן/ארכיון/הזמנות',
    }, {
      name: 'drive-agan-shipments', source: 'drive', engine: 'n8n', processor_wf: 'ingest-drive-agan-shipments',
      connection: 'drive-local', fallback_type: 'SHIPMENT', enabled: true,
      type_hint: 'SHIPMENT', batch: { take: 15, chunk: 5, timeout_min: 8, schedule_min: 20 },
      pairs: [{ from: 'אגן/נכנס/משלוחים', to: 'אגן/ארכיון/משלוחים' }], dest_folder: 'אגן/ארכיון/משלוחים',
    }],
    settings: [
      { key: 'auto_sync_enabled', value: 'false' },
      { key: 'max_ocr_retries', value: '5' },
      { key: 'extraction_timeout_s', value: '90' },
      { key: 'pipeline_version', value: 'v3.4.1' },
      { key: 'q_v3_type', value: JSON.stringify(AGAN_QUERIES.q_v3_type) },
      { key: 'q_v3_company', value: JSON.stringify(AGAN_QUERIES.q_v3_company) },
      { key: 'q_v3_routing', value: JSON.stringify(AGAN_QUERIES.q_v3_routing) },
    ],
    companies: [
      { id: '1', 'שם חברה': 'אגן שיווק', 'מזהה 1': '512987654', 'מזהה 2': '', 'מייל 1': 'person139@example.com', 'מייל 2': '', 'שם ספק מפריוריטי': 'AGAN', 'הוראות לAI לחילוץ דוח גיול': '', TRUSTED_SOURCE_TYPES: 'drive', extra: '', created_at: '2026-02-03' },
      { id: '2', 'שם חברה': 'ספקי אריזה בע״מ', 'מזהה 1': '517889900', 'מזהה 2': '', 'מייל 1': 'person140@example.com', 'מייל 2': '', 'שם ספק מפריוריטי': 'ARIZOT', 'הוראות לAI לחילוץ דוח גיול': '', TRUSTED_SOURCE_TYPES: 'drive', extra: '', created_at: '2026-05-14' },
    ],
    tagRules: [
      { id: '1', EVENT: 'on_ingest', KEY: 'TYPE', LABEL: 'סיווג הזמנת רכש', RULE: 'contains:הזמנת רכש->ORDER', TYPE: 'classify', 'VALIDATION STATUS': 'ok', 'VALIDATION ERRORS': '', created_at: '2026-02-05', row_number: 1, label_id: '' },
    ],
    queries: AGAN_QUERIES,
  });

  // Connections available as sync sources (see the /connections route). The spine is the single source
  // of truth across Drive / Mail / INDOX; this list degrades gracefully when it isn't present.
  // ── connections + their locations come from the SHARED SPINE ────────────────────────────────────
  // INDOX used to carry its own connection list and its own folder/label tables, so the sync editor
  // could offer accounts and folders that Drive and Mail had never heard of. The spine
  // (sim/business.js) is now the single catalog all three read, so what you pick here is exactly what
  // you see in the Drive and Mail UIs — same accounts, same folders, same labels, same health.
  function allConnections() {
    if (window.__biz && window.__biz.connections) return window.__biz.connections;
    return [{ id: 'local', source: 'gmail', label: 'דואר מקומי', identity: 'מקומי', color: 'var(--olive)', status: 'ok' }];
  }
  function connById(id) {
    return allConnections().filter(function (c) { return c.id === id; })[0] || null;
  }
  function locationsFor(connId) {
    if (window.__biz && window.__biz.locations) {
      var L = window.__biz.locations(connId);
      return { kind: L.kind, items: L.items.map(function (p, i) { return { id: connId + '-' + i, path: p, count: 0 }; }) };
    }
    return { kind: 'folders', items: [] };
  }
  function addLocation(connId, path) {
    if (window.__biz && window.__biz.addLocation) return window.__biz.addLocation(connId, path);
    return false;
  }

  // Every pipe gets a real queue. Seeded to match the counts the old integer store used to fake, so
  // the board looks the same on first paint — but now every number is backed by items you can open.
  // ~3,100 documents already through the pipe this month, spread over 8 sources — the scale where a
  // board has to stay usable. The failure mixes are deliberate, so every operator case is present:
  //  · gmail-invoices   a healthy high-volume pipe with a normal spread of failures
  //  · gmail-receipts   a pile of unclassified docs — one fallback_type click clears them
  //  · outlook-suppliers a mail pipe full of irrelevant mail the operator just wants to skip to done
  //  · dropbox-archive  a pipe on a BROKEN connection: everything failed with 'connection'
  INST_SABACH.items = {
    'gmail-invoices': seedItems(REGISTRY[0], { to_sync: 14, in_progress: 3, synced: 842, failed: 9 }),
    'gmail-receipts': seedItems(REGISTRY[1], { to_sync: 8, in_progress: 2, synced: 517, failed: 12 },
                                ['type', 'type', 'type', 'ocr']),
    'gmail-bank': seedItems(REGISTRY[2], { to_sync: 2, in_progress: 0, synced: 96, failed: 1 }),
    'outlook-suppliers': seedItems(REGISTRY[3], { to_sync: 23, in_progress: 1, synced: 288, failed: 6 },
                                   ['duplicate', 'duplicate', 'corrupt']),
    'bs-gdrive-sync': seedItems(REGISTRY[4], { to_sync: 11, in_progress: 4, synced: 604, failed: 15 },
                                ['type', 'type', 'type', 'type', 'company']),
    'gdrive-invoices': seedItems(REGISTRY[5], { to_sync: 6, in_progress: 2, synced: 471, failed: 7 }),
    'gdrive-shipments': seedItems(REGISTRY[6], { to_sync: 4, in_progress: 1, synced: 233, failed: 3 }),
    'dropbox-archive': seedItems(REGISTRY[7], { to_sync: 19, in_progress: 0, synced: 41, failed: 11 },
                                 ['connection']),
  };
  INST_AGAN.items = {
    'drive-agan-orders': seedItems(INST_AGAN.registry[0], { to_sync: 4, in_progress: 1, synced: 61, failed: 1 }),
    'drive-agan-shipments': seedItems(INST_AGAN.registry[1], { to_sync: 2, in_progress: 0, synced: 28, failed: 0 }),
  };

  /* Volume, per instance. סבח is a decade-old client, אגן was onboarded eighteen months ago —
     switching between them has to change the SCALE of the table, not only the names in it. */
  INST_SABACH.docs = INST_SABACH.docs.concat(genDocs(20260727, 13800, 2026, 10));
  INST_AGAN.docs = INST_AGAN.docs.concat(genDocs(880511, 1450, 2026, 2));
  [INST_SABACH, INST_AGAN].forEach(function (inst) {
    inst.docs.forEach(function (d) {
      if (!inst.history[d.ID]) inst.history[d.ID] = [{ event_type: 'insert', occurred_at: d.TIMESTAMP, row: clone(d) }];
    });
  });

  var INSTANCES = [INST_SABACH, INST_AGAN];
  var ACTIVE = INST_SABACH.id;
  function instById(id) { return INSTANCES.find(function (i) { return i.id === id; }) || null; }
  function curInst() { return instById(ACTIVE) || INSTANCES[0]; }

  // Re-point every live store at `inst`. This is what makes an instance a *full* INDOX rather than a
  // repo picker: table, history, registry, settings, companies, tag rules and queries all move together.
  function activate(id) {
    var inst = instById(id); if (!inst) return false;
    ACTIVE = id;
    DOCS = inst.docs; HISTORY = inst.history; REGISTRY = inst.registry;
    SETTINGS = inst.settings; EDITABLE_KEYS = inst.editableKeys;
    COMPANIES = inst.companies; TAG_RULES = inst.tagRules; QUERIES = inst.queries;
    REPO_NAME = inst.repo.name;
    REPOS = INSTANCES.map(function (i) { return i.repo; });   // every instance's repo stays listable
    return true;
  }
  activate(ACTIVE);

  // Account shape shared with Drive/Mail/Chat, so overlay/switcher.js stays generic (see
  // CONNECTED-INSTANCES.md). `identity` shows the instance's actual target table — the thing that
  // makes two instances visibly different.
  function instTarget(inst) {
    return inst.repo.backend === 'gsheet'
      ? ((inst.repo.gsheet && inst.repo.gsheet.sheet_name) || 'gsheet')
      : ((inst.repo.supabase && inst.repo.supabase.table) || 'supabase');
  }
  function instAccount(inst) {
    return {
      id: inst.id, provider: 'indox', label: inst.label, identity: instTarget(inst),
      color: inst.color, builtin: inst.builtin, status: inst.status, reason: inst.reason,
      docs: inst.docs.length, registry: inst.registry.length, backend: inst.repo.backend,
      settings_count: inst.settings.length, companies: inst.companies.length,
      tag_rules: inst.tagRules.length, created_at: inst.created_at, log: [],
    };
  }
  function addInstance(spec) {
    spec = spec || {};
    var id = String(spec.id || ('indox-' + Date.now()));
    var backend = spec.backend === 'gsheet' ? 'gsheet' : 'supabase';
    var table = String(spec.table || ('indox_' + id.replace(/[^a-z0-9]+/gi, '_').toLowerCase()));
    var repo = {
      name: id, backend: backend, primary_key: 'ID',
      columns: (spec.columns && spec.columns.length) ? spec.columns : clone(COLUMNS),
      priority_sync_columns: ['STATUS', 'REQUIRED_ACTION'],
      active: true, poll_interval_seconds: Number(spec.poll_interval_seconds) || 30,
      created_at: nowIso(), updated_at: nowIso(),
    };
    if (backend === 'gsheet') repo.gsheet = { sheet_name: table, spreadsheet_title: spec.label || id, gid: 0, editors: [] };
    else repo.supabase = { schema: 'public', table: table, rls: true, service_key_env: 'SUPABASE_SERVICE_KEY' };
    // A brand-new instance starts EMPTY — its own blank table, its own default settings, and only the
    // sync registries chosen during creation.
    var inst = mkInstance({
      id: id, label: spec.label || id, company: spec.company || spec.label || id,
      color: spec.color || '#56693f', status: 'ok', repo: repo,
      docs: [], history: {}, registry: (spec.registry || []).slice(),
      settings: [
        { key: 'auto_sync_enabled', value: 'true' },
        { key: 'max_ocr_retries', value: '3' },
        { key: 'extraction_timeout_s', value: '45' },
        { key: 'pipeline_version', value: 'v3.4.1' },
      ],
      companies: [], tagRules: [], queries: clone(QUERIES),
    });
    inst.items = {};
    (inst.registry || []).forEach(function (e) { inst.items[e.name] = []; });
    INSTANCES.push(inst);
    return inst;
  }
  function removeInstance(id) {
    var inst = instById(id);
    if (!inst || inst.builtin) return { success: false, error: 'builtin' };
    INSTANCES = INSTANCES.filter(function (i) { return i.id !== id; });
    if (ACTIVE === id) activate(INSTANCES[0].id);
    else activate(ACTIVE);                                   // refresh the REPOS listing
    return { success: true };
  }

  // ----------------------------------------------------------- test suites
  var SUITES = [
    { name: 'sync_kernel', label: 'ליבת סנכרון', group: 'sync', description: 'בדיקות קליטה וסנכרון gmail/drive', case_count: 5, cases_passed: 5, all_passed: true, last_run: isoAgo(3600000), failures: [] },
    { name: 'sync_dedupe', label: 'זיהוי כפילויות', group: 'sync', description: 'זיהוי מסמכים כפולים בין מקורות', case_count: 3, cases_passed: 3, all_passed: true, last_run: isoAgo(7200000), failures: [] },
    { name: 'statemachine_core', label: 'מכונת מצבים - ליבה', group: 'statemachine', description: 'מעברי סטטוס ותנאי כשל', case_count: 6, cases_passed: 5, all_passed: false, last_run: isoAgo(1800000), failures: ['action_router_timeout'] },
    { name: 'statemachine_actions', label: 'מנתבי פעולות', group: 'statemachine', description: 'ניתוב REQUIRED_ACTION', case_count: 4, cases_passed: 4, all_passed: true, last_run: isoAgo(5400000), failures: [] },
  ];
  var TEST_GROUPS = { sync: 'סנכרון', statemachine: 'מכונת מצבים' };
  var TEST_RUNS = {};
  function startTestRun(opts) {
    var scoped = opts && opts.suite ? SUITES.filter(function (s) { return s.name === opts.suite; })
      : opts && opts.group ? SUITES.filter(function (s) { return s.group === opts.group; })
      : SUITES.slice();
    var caseNames = [];
    scoped.forEach(function (s) { for (var i = 0; i < (s.case_count || 1); i++) caseNames.push({ suite: s.name, name: s.name + '_case_' + (i + 1) }); });
    var run = {
      run_id: rid('trun_'), suite: (opts && opts.suite) || null, status: 'running', started: nowIso(), finished: null,
      cases_total: caseNames.length, cases_done: 0, passed: 0, failed: 0, per_case: [], _queue: caseNames, _suites: scoped,
    };
    TEST_RUNS[run.run_id] = run;
    return { run_id: run.run_id };
  }
  function tickTestRun(run) {
    if (run.status !== 'running') return run;
    if (run._queue.length === 0) { run.status = 'done'; run.finished = nowIso(); finishTestRun(run); return run; }
    var c = run._queue.shift();
    var passed = Math.random() < 0.88;
    run.per_case.push({
      suite: c.suite, name: c.name, status: passed ? 'passed' : 'failed', passed: passed,
      assertions_passed: passed ? 4 : 3, assertions_total: 4, duration_s: Math.round((0.3 + Math.random() * 1.2) * 10) / 10,
      failed_assertions: passed ? [] : [{ name: 'expected_status', expected: 'COMPLETED', actual: 'NEEDS_REVIEW', operator: 'equals' }],
    });
    run.cases_done++; if (passed) run.passed++; else run.failed++;
    if (run.cases_done >= run.cases_total) { run.status = 'done'; run.finished = nowIso(); finishTestRun(run); }
    return run;
  }
  function finishTestRun(run) {
    (run._suites || []).forEach(function (s) {
      var mine = run.per_case.filter(function (c) { return c.suite === s.name; });
      if (!mine.length) return;
      s.cases_passed = mine.filter(function (c) { return c.passed; }).length;
      s.all_passed = mine.every(function (c) { return c.passed; });
      s.last_run = run.finished;
    });
  }
  function publicTestRun(run) {
    return {
      run_id: run.run_id, suite: run.suite, status: run.status, started: run.started, finished: run.finished,
      cases_total: run.cases_total, cases_done: run.cases_done, passed: run.passed, failed: run.failed,
      per_case: run.per_case, error: null,
    };
  }


  // ------------------------------------------------------- background ticker
  // Keeps the pipeline moving (NEEDS_REVIEW -> IN_PROGRESS -> COMPLETED) and
  // sync counters drifting even when no page is actively polling.
  setInterval(function () {
    var inprog = DOCS.filter(function (d) { return d.STATUS === 'IN_PROGRESS'; });
    inprog.forEach(function (d) {
      d.STATUS = 'COMPLETED'; d.REQUIRED_ACTION = null;
      if (!d.DOC_TOTAL_AMOUNT) d.DOC_TOTAL_AMOUNT = Math.round((500 + Math.random() * 15000) * 100) / 100;
      d.TIMESTAMP = nowIso();
      pushHistory(d, 'update');
    });
    var needsReview = DOCS.filter(function (d) { return d.STATUS === 'NEEDS_REVIEW'; });
    if (needsReview.length) {
      var d = needsReview[0];
      d.STATUS = 'IN_PROGRESS'; d.REQUIRED_ACTION = null; d.TIMESTAMP = nowIso();
      pushHistory(d, 'update');
    }
    if (Math.random() < 0.5) {
      var nd = spawnIncoming();
    }
    INSTANCES.forEach(advanceSync);
  }, 6000);

  // --------------------------------------------------------------- fetch
  var MARKER = '/incomingDocuments';
  window.fetch = function (url, opts) {
    var full = String(url);
    var qIdx = full.indexOf('?');
    var rawPath = qIdx === -1 ? full : full.slice(0, qIdx);
    var params = new URLSearchParams(qIdx === -1 ? '' : full.slice(qIdx + 1));
    var mIdx = rawPath.indexOf(MARKER);
    if (mIdx === -1) return realFetch ? realFetch(url, opts) : Promise.reject(new Error('mock: no route ' + full));
    var path = rawPath.slice(mIdx + MARKER.length); // '' or starts with '/'
    var method = ((opts && opts.method) || 'GET').toUpperCase();
    var body = (opts && typeof opts.body === 'string') ? parseBody(opts) : null;

    // ---- auth ----
    if (/^\/auth\/me$/.test(path)) return j(AUTH_ME);

    // ---- repos ----
    // Connections a new instance can sync FROM. These are the same Drive/Mail accounts the rest of the
    // platform shows — an INDOX instance pulls from connections, it doesn't own them. Sourced from the
    // shared business spine so Drive, Mail and INDOX can't drift apart; falls back to a static list if
    // the spine isn't loaded.
    if (/^\/connections$/.test(path) && method === 'GET') return j({ connections: allConnections() });

    // ── instance switching, in the shared Drive/Mail/Chat accounts contract ──────────────────────
    if (/^\/accounts$/.test(path) && method === 'GET') {
      return j({ accounts: INSTANCES.map(instAccount), active: ACTIVE });
    }
    if (/^\/account\/select$/.test(path) && method === 'POST') {
      var selId = (body && (body.id || body.account)) || '';
      if (!activate(selId)) return j({ success: false, error: 'unknown instance' }, 404);
      return j({ success: true, active: ACTIVE, account: instAccount(curInst()) });
    }
    if (/^\/account\/add$/.test(path) && method === 'POST') {
      var ni = addInstance(body || {});
      activate(ACTIVE);
      return j({ success: true, account: instAccount(ni), accounts: INSTANCES.map(instAccount), active: ACTIVE });
    }
    if (/^\/account\/remove$/.test(path) && method === 'POST') {
      var rm = removeInstance((body && body.id) || '');
      return j(Object.assign(rm, { accounts: INSTANCES.map(instAccount), active: ACTIVE }));
    }
    // Everything an instance owns, for the switcher's details panel (replaces RepoDetailPage).
    if (/^\/account\/detail$/.test(path) && method === 'GET') {
      var di = curInst();
      return j(said({
        account: instAccount(di), repo: di.repo, target: instTarget(di),
        columns: di.repo.columns, registry: di.registry, settings: di.settings,
        counts: { docs: di.docs.length, registry: di.registry.length, settings: di.settings.length,
                  companies: di.companies.length, tag_rules: di.tagRules.length },
      }));
    }

    if (/^\/repos$/.test(path)) {
      if (method === 'GET') return j(said({ repos: REPOS }));
      if (method === 'POST') return j(said(createRepo(body || {})));
    }
    var mStats = path.match(/^\/repos\/([^/]+)\/stats$/);
    if (mStats && method === 'GET') {
      var rn = decodeURIComponent(mStats[1]);
      var repoS = findRepo(rn);
      if (!repoS) return j({ error: 'not found' }, 404);
      var instS = instById(rn);
      return j({ name: repoS.name, backend: repoS.backend, row_count: instS ? instS.docs.length : 0, columns: repoS.columns, row_count_stale: false });
    }
    var mUpsert = path.match(/^\/repos\/([^/]+)\/documents$/);
    if (mUpsert && method === 'PUT') return j(upsertRows(Array.isArray(body) ? body : []));
    var mQuery = path.match(/^\/repos\/([^/]+)\/documents\/query$/);
    if (mQuery && method === 'POST') return j(queryDocs(body || {}));
    var mDocHist = path.match(/^\/repos\/([^/]+)\/documents\/([^/]+)\/history$/);
    if (mDocHist && method === 'GET') {
      var hId = decodeURIComponent(mDocHist[2]);
      return j({ events: HISTORY[hId] || [] });
    }
    var mDoc = path.match(/^\/repos\/([^/]+)\/documents\/([^/]+)$/);
    if (mDoc) {
      var docId = decodeURIComponent(mDoc[2]);
      if (method === 'GET') {
        var row = findDoc(docId);
        return row ? j({ row: row }) : j({ error: 'not found' }, 404);
      }
      if (method === 'PATCH') {
        var pres = patchDocument(docId, body || {});
        return pres ? j(pres) : j({ error: 'not found' }, 404);
      }
    }
    var mSync2 = path.match(/^\/repos\/([^/]+)\/sync$/);
    if (mSync2 && method === 'POST') return j(syncRepoAction());
    var mRepo = path.match(/^\/repos\/([^/]+)$/);
    if (mRepo) {
      var name = decodeURIComponent(mRepo[1]);
      if (method === 'GET') { var r2 = findRepo(name); return r2 ? j(said({ repo: r2 })) : j({ error: 'not found' }, 404); }
      if (method === 'PATCH') { var pr = patchRepo(name, body || {}); return pr ? j(said(pr)) : j({ error: 'not found' }, 404); }
      if (method === 'DELETE') return j(deleteRepo(name));
    }

    // ---- dashboard ----
    if (/^\/dashboard\/stats$/.test(path)) return j(computeDashboard());

    // ---- sync (one surface: config + live state + actions) — see sim/INDOX-SYNC.md ----
    if (/^\/sync\/status$/.test(path)) return j(computeSyncStatus(curInst(), params.get('sync')));

    // registry now carries each pipe's LIVE counts, so config and state never need two round-trips.
    if (/^\/sync\/registry$/.test(path) && method === 'GET')
      return j({ registry: registryWithLive(curInst()), reachable: true });

    if (/^\/sync\/registry$/.test(path) && method === 'POST') {
      var ci = curInst(), spec = body || {};
      var nm = String(spec.name || ((spec.source || 'drive') + '-' + Date.now()));
      if (ci.registry.some(function (e) { return e.name === nm; }))
        return j({ success: false, error: 'שם המקור כבר קיים' }, 409);
      var ent = {
        name: nm, source: spec.source === 'gmail' ? 'gmail' : 'drive', engine: 'n8n',
        // type is OPTIONAL. A mixed folder/label has no single correct type, and defaulting one would
        // mislabel everything in it. Only set it when the LOCATION implies the type.
        processor_wf: 'ingest-' + nm, type_hint: spec.type_hint || null,
        fallback_type: spec.fallback_type || spec.type_hint || null,
        connection: spec.connection || null, enabled: spec.enabled !== false,
        batch: Object.assign({ take: 20, chunk: 5, timeout_min: 10, schedule_min: 10 }, spec.batch || {}),
      };
      if (ent.source === 'gmail') { ent.labels = spec.labels || {}; ent.claim_label = spec.claim_label || ((ent.labels.to_sync || 'INDOX') + '/בעיבוד'); }
      else { ent.pairs = spec.pairs || []; ent.dest_folder = spec.dest_folder || ((ent.pairs[0] && ent.pairs[0].to) || ''); }
      ci.registry.push(ent);
      ci.items[ent.name] = [];
      return j({ success: true, entry: ent, registry: registryWithLive(ci) });
    }

    var mReg = path.match(/^\/sync\/registry\/([^/]+)$/);
    if (mReg && (method === 'PATCH' || method === 'DELETE')) {
      var ri = curInst(), rn = decodeURIComponent(mReg[1]);
      var idx = ri.registry.findIndex(function (e) { return e.name === rn; });
      if (idx === -1) return j({ success: false, error: 'not found' }, 404);
      if (method === 'DELETE') {
        ri.registry.splice(idx, 1); delete ri.items[rn];
        return j({ success: true, registry: registryWithLive(ri) });
      }
      var patch = body || {};
      // renaming has to carry the queue with it, or the pipe's history silently vanishes
      if (patch.name && patch.name !== rn) {
        ri.items[patch.name] = ri.items[rn] || []; delete ri.items[rn];
        (ri.items[patch.name] || []).forEach(function (it) { it.sync = patch.name; });
      }
      Object.assign(ri.registry[idx], patch);
      return j({ success: true, entry: ri.registry[idx], registry: registryWithLive(ri) });
    }

    var mRun = path.match(/^\/sync\/registry\/([^/]+)\/run$/);
    if (mRun && method === 'POST') {
      var ui = curInst(), un = decodeURIComponent(mRun[1]);
      var ue = ui.registry.filter(function (e) { return e.name === un; })[0];
      if (!ue) return j({ success: false, error: 'not found' }, 404);
      return j({ success: true, claimed: runPipe(ui, ue), registry: registryWithLive(ui) });
    }
    if (/^\/sync\/run$/.test(path) && method === 'POST') {
      var ai = curInst(), tot = 0;
      ai.registry.forEach(function (e) { if (e.enabled !== false) tot += runPipe(ai, e); });
      return j({ success: true, claimed: tot, registry: registryWithLive(ai) });
    }

    if (/^\/sync\/items$/.test(path) && method === 'GET') {
      var gi = curInst(), gs = params.get('sync'), gst = params.get('state');
      var gcode = params.get('code'), gq = (params.get('q') || '').trim();
      var gStuck = params.get('stuck') === '1';
      var limit = Math.min(Number(params.get('limit')) || 200, 500);
      var offset = Number(params.get('offset')) || 0;
      var byName = {};
      (gi.registry || []).forEach(function (e) { byName[e.name] = e; });
      var all = gs ? itemsOf(gi, gs)
        : gi.registry.reduce(function (a, e) { return a.concat(itemsOf(gi, e.name)); }, []);
      if (gst) all = all.filter(function (it) { return it.state === gst; });
      if (gcode) all = all.filter(function (it) { return it.error_code === gcode; });
      if (gStuck) all = all.filter(function (it) { return isStuck(byName[it.sync] || {}, it); });
      if (gq) {
        var q = gq.toLowerCase();
        all = all.filter(function (it) {
          return (it.title || '').toLowerCase().indexOf(q) !== -1
            || (it.company || '').toLowerCase().indexOf(q) !== -1;
        });
      }
      all = all.slice().sort(function (a, b) { return b.updated_at < a.updated_at ? -1 : 1; });
      var page = all.slice(offset, offset + limit).map(function (it) {
        return Object.assign({}, it, {
          stuck: isStuck(byName[it.sync] || {}, it),
          fallback_type: (byName[it.sync] || {}).fallback_type || null,
        });
      });
      // ids of the WHOLE filtered set, so "select all N matching" can act beyond the loaded page
      return j({ items: page, total: all.length, all_ids: all.map(function (x) { return x.id; }) });
    }

    // One-click resolution for the biggest failure class: an unclassified document in a pipe whose
    // LOCATION already tells you the type (anything in נכנס/קבלות is a receipt). Applies the pipe's
    // fallback_type and re-queues, turning a pile of "סוג לא זוהה" into work that will actually pass.
    if (/^\/sync\/items\/apply-fallback-type$/.test(path) && method === 'POST') {
      var fi = curInst(), fb = body || {}, fids = fb.ids || [];
      var fe = (fi.registry || []).filter(function (e) { return e.name === fb.sync; })[0];
      if (!fe) return j({ success: false, error: 'unknown sync' }, 404);
      var ft = fe.fallback_type || fe.type_hint;
      if (!ft) return j({ success: false, error: 'לא הוגדר סוג ברירת מחדל למקור זה' }, 400);
      var applied = 0;
      itemsOf(fi, fb.sync).forEach(function (it) {
        if (fids.indexOf(it.id) === -1) return;
        it.kind = ft; it.detected = true;
        it.state = 'to_sync'; it.error = null; it.error_code = null; it.error_group = null;
        it.updated_at = nowIso();
        applied++;
      });
      return j({ success: true, applied: applied, type: ft, registry: registryWithLive(fi) });
    }

    // Move items between states. Guarded by the legal-transition table (INDOX-SYNC.md §4): the UI
    // only offers legal targets, and the mock refuses the rest so a bad caller can't invent a claim.
    if (/^\/sync\/items\/move$/.test(path) && method === 'POST') {
      var mi = curInst(), mv = body || {}, to = mv.to, ids = mv.ids || [];
      var LEGAL = { to_sync: ['synced'], in_progress: ['to_sync'], synced: ['to_sync'], failed: ['to_sync'] };
      if (STATES.indexOf(to) === -1) return j({ success: false, error: 'unknown state' }, 400);
      var pool = mv.sync ? itemsOf(mi, mv.sync)
        : mi.registry.reduce(function (a, e) { return a.concat(itemsOf(mi, e.name)); }, []);
      var moved = 0, refused = 0;
      pool.forEach(function (it) {
        if (ids.indexOf(it.id) === -1) return;
        if ((LEGAL[it.state] || []).indexOf(to) === -1) { refused++; return; }
        it.state = to; it.updated_at = nowIso();
        if (to !== 'failed') it.error = null;
        moved++;
      });
      return j({ success: true, moved: moved, refused: refused, registry: registryWithLive(mi) });
    }

    // ---- connections: what actually exists inside one (labels / folders) ----
    var mLoc = path.match(/^\/connections\/([^/]+)\/locations$/);
    if (mLoc) {
      var cid = decodeURIComponent(mLoc[1]), loc = locationsFor(cid);
      if (method === 'GET') return j({ kind: loc.kind, items: loc.items });
      if (method === 'POST') {
        var np = String((body && body.path) || '').trim();
        if (!np) return j({ success: false, error: 'path required' }, 400);
        var dup = loc.items.filter(function (i) { return i.path === np; })[0];
        if (dup) return j({ success: true, item: dup, created: false });
        addLocation(cid, np);                       // writes into the SPINE, so Drive/Mail see it too
        return j({ success: true, item: { id: 'n' + Date.now(), path: np, count: 0 }, created: true });
      }
    }

    // ---- config ----
    if (/^\/config\/settings$/.test(path) && method === 'GET') return j({ settings: SETTINGS, editable_keys: EDITABLE_KEYS, reachable: true });
    var mSetKey = path.match(/^\/config\/settings\/([^/]+)$/);
    if (mSetKey && method === 'PUT') {
      var skey = decodeURIComponent(mSetKey[1]);
      var sval = body && ('value' in body) ? body.value : null;
      var sstr = typeof sval === 'boolean' ? String(sval) : (sval == null ? null : String(sval));
      var srow = SETTINGS.find(function (s) { return s.key === skey; });
      if (srow) srow.value = sstr; else { srow = { key: skey, value: sstr }; SETTINGS.push(srow); }
      return j({ success: true, setting: srow, reachable: true });
    }
    if (/^\/config\/companies$/.test(path) && method === 'GET') return j({ companies: COMPANIES, reachable: true });
    if (/^\/config\/tag_rules$/.test(path) && method === 'GET') return j({ tag_rules: TAG_RULES, reachable: true });
    var mCfgRow = path.match(/^\/config\/([^/]+)\/([^/]+)$/);
    if (mCfgRow) {
      var ctable = decodeURIComponent(mCfgRow[1]), crid = decodeURIComponent(mCfgRow[2]);
      if (method === 'PATCH') return j(patchConfigRow(ctable, crid, body && body.key, body && body.value));
      if (method === 'DELETE') return j(deleteConfigRow(ctable, crid));
    }
    var mCfgTable = path.match(/^\/config\/([^/]+)$/);
    if (mCfgTable && method === 'POST') return j(addConfigRow(decodeURIComponent(mCfgTable[1]), body || {}));

    // ---- tests ----
    if (/^\/tests\/suites$/.test(path)) return j({ suites: SUITES, groups: TEST_GROUPS, reachable: true });
    if (/^\/tests\/run$/.test(path) && method === 'POST') return j(startTestRun(body || {}));
    var mTestRun = path.match(/^\/tests\/run\/([^/]+)$/);
    if (mTestRun) {
      var trun = TEST_RUNS[decodeURIComponent(mTestRun[1])];
      if (!trun) return j({ error: 'not found' }, 404);
      tickTestRun(trun);
      return j(publicTestRun(trun));
    }

    // ---- extraction ----
    if (/^\/extraction\/dataset$/.test(path)) {
      return j({ docs: EXTRACT_DOCS, uploads: EXTRACT_UPLOADS, dataset_dir: '/srv/incoming-documents/extraction-dataset', available: true, types: EXTRACT_TYPES });
    }
    if (/^\/extraction\/run$/.test(path) && method === 'POST') {
      var erun0 = startExtractionRun(body && body.ids);
      return j({ run_id: erun0.run_id, docs_total: erun0.docs_total });
    }
    var mExtCancel = path.match(/^\/extraction\/run\/([^/]+)\/cancel$/);
    if (mExtCancel && method === 'POST') { cancelExtractionRun(decodeURIComponent(mExtCancel[1])); return j({ ok: true }); }
    var mExtRun = path.match(/^\/extraction\/run\/([^/]+)$/);
    if (mExtRun) {
      var erun = EXTRACT_RUNS.find(function (r) { return r.run_id === decodeURIComponent(mExtRun[1]); });
      if (!erun) return j({ error: 'not found' }, 404);
      tickExtractionRun(erun);
      return j(publicRun(erun));
    }
    if (/^\/extraction\/upload$/.test(path) && method === 'POST') return j(handleUpload(opts && opts.body));
    var mRerun = path.match(/^\/extraction\/rerun\/(.+)$/);
    if (mRerun && method === 'POST') {
      var rdocId = decodeURIComponent(mRerun[1]);
      var rres = rerunExtractionDoc(rdocId, params.get('fresh') === '1');
      return rres ? j(rres) : j({ error: 'not found' }, 404);
    }
    if (/^\/extraction\/queries$/.test(path) && method === 'GET') return j({ queries: QUERIES });
    var mPutQ = path.match(/^\/extraction\/queries\/([^/]+)$/);
    if (mPutQ && method === 'PUT') {
      var qkey = decodeURIComponent(mPutQ[1]);
      QUERIES[qkey] = body && body.value;
      return j({ success: true, key: qkey });
    }
    if (/^\/extraction\/runs$/.test(path) && method === 'GET') return j({ runs: EXTRACT_RUNS.map(publicRun) });
    var mRunsId = path.match(/^\/extraction\/runs\/([^/]+)$/);
    if (mRunsId) {
      var frun = EXTRACT_RUNS.find(function (r) { return r.run_id === decodeURIComponent(mRunsId[1]); });
      if (!frun) return j({ error: 'not found' }, 404);
      if (method === 'DELETE') { EXTRACT_RUNS = EXTRACT_RUNS.filter(function (r) { return r !== frun; }); return j({ ok: true }); }
      return j(Object.assign(publicRun(frun), { results: frun._results }));
    }
    var mExtHist = path.match(/^\/extraction\/history\/(.+)$/);
    if (mExtHist) return j({ history: EXTRACT_HISTORY[decodeURIComponent(mExtHist[1])] || [] });

    // document images: original page, extraction "draw" (fields boxed), and OCR tokens map.
    // The sim's resource shim routes these <img>/<iframe> loads through this mock -> a rendered
    // SVG invoice page (renders real Hebrew, unlike a PDF), so the extraction viewer is populated.
    var mImg = path.match(/^\/extraction\/(file|draw|tokens)\/([^/]+)\/([^/]+)$/);
    if (mImg) {
      var mode = mImg[1], nm = decodeURIComponent(mImg[3]);
      var e = function (s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); };
      var num = (nm.match(/\d+/) || ['1042'])[0];
      var box = function (x, y, w, h, col) { return '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" fill="none" stroke="' + col + '" stroke-width="2" rx="2"/>'; };
      var tag = function (x, y, t, col) { return '<rect x="' + x + '" y="' + (y - 14) + '" width="' + (t.length * 6 + 10) + '" height="14" fill="' + col + '"/><text x="' + (x + 5) + '" y="' + (y - 3) + '" font-size="10" fill="#fff" font-family="monospace">' + e(t) + '</text>'; };
      var rows = '';
      ['ייעוץ עסקי · 10 שעות', 'רישוי חודשי · שנתי', 'התקנה באתר'].forEach(function (t, i) { rows += '<text x="470" y="' + (300 + i * 34) + '" font-size="13" text-anchor="end">' + e(t) + '</text><text x="120" y="' + (300 + i * 34) + '" font-size="13">' + ((i + 1) * 1200) + '.00</text><line x1="70" y1="' + (312 + i * 34) + '" x2="530" y2="' + (312 + i * 34) + '" stroke="#eee"/>'; });
      var overlay = '';
      if (mode === 'draw') {
        overlay = box(360, 150, 130, 24, '#0e9f6e') + tag(360, 150, 'invoice_id', '#0e9f6e')
          + box(360, 186, 130, 24, '#2b7fb8') + tag(360, 186, 'date', '#2b7fb8')
          + box(150, 470, 140, 26, '#0e9f6e') + tag(150, 470, 'amount', '#0e9f6e')
          + box(320, 220, 170, 24, '#c0567a') + tag(320, 220, 'company_id', '#c0567a');
      } else if (mode === 'tokens') {
        var t = '';
        for (var r = 0; r < 22; r++) { var yy = 150 + r * 26; for (var c = 0; c < 5; c++) { var xx = 90 + c * 88 + (r % 2 ? 8 : 0); if (Math.abs((r * 7 + c * 3) % 11) > 3) t += '<rect x="' + xx + '" y="' + (yy - 12) + '" width="' + (36 + (c * 7) % 30) + '" height="15" fill="none" stroke="#c9a227" stroke-width="1"/>'; } }
        overlay = t;
      }
      var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="560" height="760" viewBox="0 0 560 760" direction="rtl">'
        + '<rect width="560" height="760" fill="#fff"/><rect x="1" y="1" width="558" height="758" fill="none" stroke="#e2e6e4"/>'
        + '<text x="530" y="70" font-size="26" font-weight="700" text-anchor="end" font-family="Arial">חשבונית מס</text>'
        + '<text x="530" y="96" font-size="13" fill="#667" text-anchor="end" font-family="Arial">בינה פתרונות בע״מ · ע.מ 514789234</text>'
        + '<text x="490" y="168" font-size="14" text-anchor="end" font-family="Arial">מספר: INV-2026-' + e(('00000' + num).slice(-5)) + '</text>'
        + '<text x="490" y="204" font-size="14" text-anchor="end" font-family="Arial">תאריך: 01/06/2026</text>'
        + '<text x="490" y="238" font-size="14" text-anchor="end" font-family="Arial">לקוח: ישראל קרטון בע״מ · 514236789</text>'
        + '<line x1="60" y1="270" x2="500" y2="270" stroke="#12241d" stroke-width="1.5"/>'
        + '<text x="490" y="290" font-size="12" fill="#889" text-anchor="end">תיאור</text><text x="120" y="290" font-size="12" fill="#889">סכום</text>'
        + rows
        + '<text x="490" y="474" font-size="15" font-weight="700" text-anchor="end" font-family="Arial">סה״כ לתשלום</text>'
        + '<text x="150" y="474" font-size="15" font-weight="700" font-family="Arial">₪ 4,320.00</text>'
        + '<text x="280" y="720" font-size="11" fill="#aab" text-anchor="middle" font-family="monospace">' + e(nm) + (mode === 'draw' ? ' · documentDraw' : mode === 'tokens' ? ' · OCR tokens' : ' · original') + '</text>'
        + overlay + '</svg>';
      return Promise.resolve(new Response(svg, { status: 200, headers: { 'Content-Type': 'image/svg+xml' } }));
    }

    // never let anything escape to the real network
    return j({});
  };
})();
