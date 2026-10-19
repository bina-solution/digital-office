/* Mock backend for the drive (דרייב) — lets the LIVE app's own frontend (apps/drive/static: app.js +
   index.html) run standalone, with zero real network traffic. Real UI code is untouched; only
   window.fetch and window.XMLHttpRequest are intercepted (pattern from ./any-concurrency.js,
   extended for XHR because the drive's upload path uses XMLHttpRequest, not fetch).

   It answers what the live SERVICE answers (apps/drive/app.py and adapters/local.py) — the shapes
   below are read off that code, not off what a page happened to read. Where this mock answered a
   shape of its own, the simulation showed what no office does: a storage meter fed by `total`, a
   field no adapter has ever sent.

   Endpoints mocked (method — response shape):
     GET  api/folders                 → { folders: [{id,name,parent,count,owner,owner_id,mine}, ...],
                                          connection: {id,protocol,label,profile_id,is_private} }
     POST api/folders {name,parent}   → 201 { folder: {id,name,parent} }  (mutates: a new folder)
     GET  api/files?folder=<id>       → { files: [{id,name,size,created,mime,folder,owner,owner_id,
                                                   mine,shared[],starred,opened}, ...], folders: [], view }
     GET  api/files?trash=1           → { files: [...] }                (same shape, trashed items)
     GET  api/files?view=recent|starred|shared → { files: [...] }       (cross-cutting views)
     POST api/star   {ids,starred?}   → { ok:true }                     (toggle when starred omitted)
     GET  api/storage                 → { files, used, limit, percent } (storage meter; `limit` is the
                                          ceiling an office configures — a meter with none is bytes only)
     GET  api/search?q=<q>            → { files: [...] }                (same shape, all folders)
   A time is `YYYY-MM-DD HH:MM` in UTC, as the service writes it; the page places it in the reader's zone.
     POST api/move    {ids,to}        → { ok:true }                     (mutates: files' `folder`)
     POST api/rename  {id,name}       → { ok:true }                     (mutates: file's `name`)
     POST api/trash   {id|ids,restore?} → { ok:true }                   (mutates: `trashed` flag)
     POST api/delete  {ids}           → { ok:true }                     (mutates: removes from store)
     POST api/upload  FormData(folder,files[]) via XHR → 200 (see below)
     GET  api/file/<id>/content       → raw bytes (best-effort; see caveat in report)
     GET  connections / readyz / connections/select / extensions?slot=rail / providers
                                       → small fixed shapes so the sidebar's account bar + the
                                         rail extension an app registers via /extensions render
                                         instead of showing "service unavailable".

   In-memory store (FOLDERS/FILES at module scope) so move/rename/trash/delete/upload really
   mutate what subsequent api/files & api/folders calls return — dragging a row onto a sidebar
   folder actually moves it, renaming actually renames it, etc. */
(function () {
  var RealXHR = window.XMLHttpRequest;

  // ── Multi-account Google Drive (sim). Each connection is a Google account with its own Drive
  //    content; switching the active account (connections/select) swaps the folders + files the app
  //    sees. No INDOX/sync coupling — a plain modern Drive with Docs/Sheets/Slides/PDF/image types. ──
  var now = Date.now();
  // h:m of the reader's own day, `daysAgo` days back — written the way the service writes a time
  // (UTC, to the minute), so the page that places it in the reader's zone shows h:m again
  function isoish(daysAgo, h, m) {
    var d = new Date(now - daysAgo * 86400000);
    d.setHours(h, m, 0, 0);
    return d.toISOString().slice(0, 16).replace("T", " ");
  }
  var GDOC = "application/vnd.google-apps.document",
      GSHEET = "application/vnd.google-apps.spreadsheet",
      GSLIDE = "application/vnd.google-apps.presentation",
      XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      PDF = "application/pdf";
  var DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation";
  /* A drive file is not just (name, size, date). Everything Drive shows in the details pane and
     everything its "Shared with me / Recent / Starred" views are built on lives on the record:
       owner   — who owns it. Drives the avatar and the "Shared with me" view.
       shared  — people it is shared WITH (names). Drives the shared-icon and the share dialog.
       opened  — last-opened timestamp. Drives "Recent" (Drive sorts by opened, NOT by created).
       starred — the user's own cross-cutting mark.
     `opt` carries them so the ~90 existing F() rows stay valid. */
  var ME = "בינה · מנהל";
  function F(id, name, mime, folder, size, daysAgo, h, m, opt) {
    opt = opt || {};
    return { id: id, name: name, mime: mime, folder: folder, size: size,
             created: isoish(daysAgo, h, m), trashed: false,
             owner: opt.owner || ME,
             shared: opt.shared || [],
             starred: !!opt.starred,
             opened: isoish(opt.openedDays == null ? Math.max(0, daysAgo - 1) : opt.openedDays, h, m) };
  }


  /* ══ Ten-year drive ════════════════════════════════════════════════════════════════════════════
     The hand-written files above are the hero set. On top of them we synthesise the archive an
     accounting office actually accumulates over ten years: a year/month tree under ארכיון, per-client
     folders, thousands of scans and invoices, and the full spread of formats a real office collects
     (PDF, Docs/Sheets/Slides, Office files, images, CAD-ish blobs, archives, CSV, email exports).

     Generated, not stored, so the simulation file stays small — and from a SEEDED PRNG so every run
     and every screenshot sees identical content.

     What this exists to prove: the tree survives hundreds of folders, the list survives thousands of
     rows, breadcrumbs go deep, filter chips and sorting stay useful at volume, the storage meter
     shows a believable number, and the grid does not melt. */
  var DLOAD = { years: 10, perMonth: 26 };
  function DLCG(seed) { var x = seed >>> 0; return function () { x = (x * 1664525 + 1013904223) >>> 0; return x / 4294967296; }; }
  var HE_MON = ["ינואר","פברואר","מרץ","אפריל","מאי","יוני","יולי","אוגוסט","ספטמבר","אוקטובר","נובמבר","דצמבר"];
  var GTYPES = [
    { ext: "",       mime: GDOC,        w: 10, name: function (r, i) { return "סיכום פגישה " + i; } },
    { ext: "",       mime: GSHEET,      w: 10, name: function (r, i) { return "כרטסת " + i; } },
    { ext: "",       mime: GSLIDE,      w: 3,  name: function (r, i) { return "מצגת סטטוס " + i; } },
    { ext: ".pdf",   mime: PDF,         w: 34, name: function (r, i) { return "חשבונית_" + (10000 + i); } },
    { ext: ".pdf",   mime: PDF,         w: 16, name: function (r, i) { return "קבלה_" + (20000 + i); } },
    { ext: ".pdf",   mime: PDF,         w: 8,  name: function (r, i) { return "סריקה_" + String(i).padStart(4, "0"); } },
    { ext: ".xlsx",  mime: XLSX_MIME,   w: 7,  name: function (r, i) { return "דוח_מעמ_" + i; } },
    { ext: ".docx",  mime: DOCX_MIME,   w: 5,  name: function (r, i) { return "מכתב_" + i; } },
    { ext: ".pptx",  mime: PPTX_MIME,   w: 2,  name: function (r, i) { return "מצגת_" + i; } },
    { ext: ".jpg",   mime: "image/jpeg", w: 6, name: function (r, i) { return "צילום_מסמך_" + i; } },
    { ext: ".png",   mime: "image/png",  w: 3, name: function (r, i) { return "צילום_מסך_" + i; } },
    { ext: ".csv",   mime: "text/csv",   w: 3, name: function (r, i) { return "יצוא_תנועות_" + i; } },
    { ext: ".zip",   mime: "application/zip", w: 2, name: function (r, i) { return "ארכיון_" + i; } },
    { ext: ".txt",   mime: "text/plain", w: 1, name: function (r, i) { return "הערות_" + i; } }
  ];
  var GWEIGHT = (function () { var t = 0; for (var i = 0; i < GTYPES.length; i++) t += GTYPES[i].w; return t; })();
  function pickType(r) {
    var n = r() * GWEIGHT;
    for (var i = 0; i < GTYPES.length; i++) { n -= GTYPES[i].w; if (n <= 0) return GTYPES[i]; }
    return GTYPES[0];
  }
  var GOWNERS = ["בינה · מנהל", "בינה · מנהל", "בינה · מנהל", "רו״ח דנה כהן", "עמית לוי", "דנה לוי"];
  var GPEOPLE = ["דנה כהן", "עמית לוי", "רו״ח דנה כהן", "מוחמד סבח", "נועה ברק"];

  /* size in bytes, realistic per format — a 4 kB "scan" would make the storage meter a lie */
  function sizeFor(mime, r) {
    if (/google-apps/.test(mime)) return 1024 + Math.floor(r() * 30000);
    if (mime === PDF) return 60000 + Math.floor(r() * 1400000);
    if (/^image\/jpe?g/.test(mime)) return 800000 + Math.floor(r() * 4200000);
    if (/^image\/png/.test(mime)) return 200000 + Math.floor(r() * 2400000);
    if (/zip/.test(mime)) return 2000000 + Math.floor(r() * 40000000);
    if (/spreadsheetml|wordprocessingml|presentationml/.test(mime)) return 25000 + Math.floor(r() * 900000);
    return 1000 + Math.floor(r() * 120000);
  }

  function genDrive(seed, thisYear) {
    var r = DLCG(seed), folders = [], files = [], n = 0;
    folders.push({ id: "ar", name: "ארכיון", parent: "", count: 0 });
    for (var y = thisYear - DLOAD.years + 1; y <= thisYear; y++) {
      var yid = "ar_" + y;
      folders.push({ id: yid, name: String(y), parent: "ar", count: 0 });
      var lastMonth = y === thisYear ? 6 : 11;      // the current year is only partly through
      for (var mo = 0; mo <= lastMonth; mo++) {
        var mid = yid + "_" + (mo + 1);
        folders.push({ id: mid, name: HE_MON[mo] + " " + y, parent: yid, count: 0 });
        var per = Math.round(DLOAD.perMonth * (0.55 + r()));
        for (var k = 0; k < per; k++) {
          var t = pickType(r), id = "gx" + (++n);
          var daysAgo = Math.max(0, Math.round((new Date(thisYear, 6, 27) - new Date(y, mo, 1 + Math.floor(r() * 27))) / 86400000));
          var owner = GOWNERS[Math.floor(r() * GOWNERS.length)];
          var shared = r() < 0.14 ? [GPEOPLE[Math.floor(r() * GPEOPLE.length)]] : [];
          files.push(F(id, t.name(r, n) + t.ext, t.mime, mid, sizeFor(t.mime, r),
                       daysAgo, 8 + Math.floor(r() * 10), Math.floor(r() * 60),
                       { owner: owner, shared: shared, starred: r() < 0.012,
                         openedDays: Math.max(0, daysAgo - Math.floor(r() * 30)) }));
        }
      }
    }
    return { folders: folders, files: files };
  }

  // Connected drive instances the switcher lists — LOCAL-FIRST: the built-in local drive is the home
  // instance, with Google Drive / Dropbox / (future providers) as additional connected instances.
  // `provider`/`email`/`color` are extra fields (the app ignores them; the sim switcher polish reads
  // them). One instance is active at a time; switching swaps the folders + files the app sees.
  var ACCOUNTS = [
    { id: "drive-local", provider: "local", protocol: "drive_local", label: "אחסון מקומי", email: null, account_hint: "מקומי · מובנה", color: "var(--olive)", status: "ok", builtin: true,
      checked: 1, log: [{ mins: 1, level: "info", msg: "אחסון מקומי זמין" }] },
    { id: "acc_office", provider: "gdrive", protocol: "gdrive", label: "Google Drive · בינה", email: "person127@example.com", account_hint: "person127@example.com", color: "#1a73e8", status: "ok",
      checked: 6, log: [{ mins: 6, level: "info", msg: "מסונכרן — 14 קבצים" }, { mins: 2880, level: "info", msg: "אסימון הגישה חודש" }, { mins: 30240, level: "info", msg: "החשבון חובר בהצלחה" }] },
    { id: "acc_personal", provider: "gdrive", protocol: "gdrive", label: "Google Drive · אישי", email: "person132@example.com", account_hint: "person132@example.com", color: "#e8710a", status: "warning",
      reason: "מכסת האחסון כמעט מלאה (92% מתוך 15GB)", checked: 45,
      log: [{ mins: 45, level: "warn", msg: "מכסת אחסון גבוהה — 92%" }, { mins: 4320, level: "info", msg: "מסונכרן — 5 קבצים" }] },
    { id: "acc_dropbox", provider: "dropbox", protocol: "dropbox", label: "Dropbox", email: "person127@example.com", account_hint: "Dropbox · office@bina", color: "#0061ff", status: "error",
      reason: "החיבור נותק — נדרש אימות מחדש (שגיאת הרשאה 401)", checked: 62,
      log: [{ mins: 62, level: "error", msg: "אימות נכשל — שגיאה 401 (הרשאה בוטלה)" }, { mins: 75, level: "warn", msg: "ניתוקים חוזרים מהשירות" }, { mins: 10080, level: "info", msg: "החשבון חובר בהצלחה" }] },
  ];
  var ACTIVE_ID = "drive-local";

  // Per-account Drive content (folder ids namespaced per account).
  var DRIVE = {
    acc_office: {
      folders: [
        { id: "of_clients",   name: "לקוחות",           parent: "", count: 0 },
        { id: "of_docs",      name: "חשבוניות ומסמכים", parent: "", count: 0 },
        { id: "of_finance",   name: "כספים 2026",       parent: "", count: 0 },
        { id: "of_contracts", name: "חוזים",            parent: "", count: 0 },
        { id: "of_decks",     name: "מצגות",            parent: "", count: 0 },
        /* NESTED folders exist so the breadcrumb is a real path, not decoration. A drive whose
           tree is one level deep can't demonstrate navigation, and "one level deep" was the single
           loudest tell that this wasn't a real drive. */
        { id: "of_cl_or",     name: "טכנולוגיות אור",   parent: "of_clients",  count: 0 },
        { id: "of_cl_sabah",  name: "סבח סוכנויות",     parent: "of_clients",  count: 0 },
        { id: "of_fin_q1",    name: "רבעון 1",          parent: "of_finance",  count: 0 },
        { id: "of_fin_q2",    name: "רבעון 2",          parent: "of_finance",  count: 0 },
        { id: "of_doc_inv",   name: "חשבוניות ספקים",   parent: "of_docs",     count: 0 },
      ],
      files: [
        F("o1", "סדר יום — ישיבת הנהלה", GDOC, "", 2048, 0, 8, 40, { starred: true, shared: ["דנה כהן", "עמית לוי"] }),
        F("o2", "מעקב משימות שבועי", GSHEET, "", 4096, 0, 9, 12, { shared: ["דנה כהן"] }),
        F("o3", "הצעת מחיר — טכנולוגיות אור", GDOC, "of_cl_or", 3072, 1, 14, 5, { starred: true }),
        F("o4", "מעקב לקוחות 2026", GSHEET, "of_clients", 8192, 2, 10, 20, { shared: ["דנה כהן", "רו״ח דנה כהן"] }),
        F("o5", "פרטי קשר לקוחות", GSHEET, "of_clients", 5120, 6, 11, 0),
        F("o6", "חשבונית_2048.pdf", PDF, "of_doc_inv", 251900, 3, 11, 20),
        F("o7", "קבלה_771.pdf", PDF, "of_docs", 91238, 0, 8, 42),
        F("o8", "תקציב שנתי 2026", GSHEET, "of_finance", 12288, 4, 13, 30, { starred: true, shared: ["רו״ח דנה כהן"] }),
        F("o9", "דוח רווח והפסד Q2", GSHEET, "of_fin_q2", 10240, 1, 9, 45, { owner: "רו״ח דנה כהן", shared: [ME] }),
        F("o10", "מאזן_בוחן.xlsx", XLSX_MIME, "of_fin_q1", 58800, 7, 12, 0, { owner: "רו״ח דנה כהן", shared: [ME] }),
        F("o11", "חוזה שירות — סבח סוכנויות", GDOC, "of_cl_sabah", 6144, 9, 16, 15),
        F("o12", "חוזה_שכירות.pdf", PDF, "of_contracts", 348210, 12, 16, 5),
        F("o13", "מצגת מוצר Q3", GSLIDE, "of_decks", 20480, 3, 15, 30, { starred: true, shared: ["עמית לוי"] }),
        F("o14", "לוגו_חברה.png", "image/png", "of_decks", 84210, 20, 10, 0),
        /* volume: a real office drive has dozens of files per folder, and density is what makes
           list-vs-grid, sorting and filter chips worth having at all */
        F("o15", "פרוטוקול ישיבת דירקטוריון — יולי", GDOC, "", 5300, 1, 17, 10),
        F("o16", "מצגת_משקיעים_2026.pptx", PPTX_MIME, "of_decks", 4210000, 5, 11, 45, { shared: ["עמית לוי", "דנה כהן"] }),
        F("o17", "תבנית_הצעת_מחיר.docx", DOCX_MIME, "of_clients", 38400, 14, 9, 0),
        F("o18", "חשבונית_2049.pdf", PDF, "of_doc_inv", 240100, 2, 15, 12),
        F("o19", "חשבונית_2050.pdf", PDF, "of_doc_inv", 198220, 1, 10, 5),
        F("o20", "אישור_ניכוי_מס.pdf", PDF, "of_docs", 74300, 8, 13, 40),
        F("o21", "תזרים מזומנים — יולי", GSHEET, "of_fin_q2", 15400, 0, 7, 55, { starred: true }),
        F("o22", "דוח מע״מ יוני", GSHEET, "of_fin_q2", 9200, 3, 12, 20, { owner: "רו״ח דנה כהן", shared: [ME] }),
        F("o23", "דוח מע״מ מרץ", GSHEET, "of_fin_q1", 8900, 40, 12, 20, { owner: "רו״ח דנה כהן", shared: [ME] }),
        F("o24", "סקיצות_מיתוג.png", "image/png", "of_decks", 1840000, 26, 16, 30),
        F("o25", "צילום_משרד.jpg", "image/jpeg", "of_decks", 3120000, 33, 9, 15),
        F("o26", "מפרט טכני — מערכת אינדוקס", GDOC, "of_cl_or", 11200, 6, 14, 25, { shared: ["עמית לוי"] }),
        F("o27", "לוח זמנים הטמעה", GSHEET, "of_cl_or", 6400, 4, 10, 40),
        F("o28", "סיכום פגישה — סבח", GDOC, "of_cl_sabah", 3300, 11, 18, 5),
        F("o29", "הסכם_סודיות.pdf", PDF, "of_contracts", 128400, 19, 11, 10),
        F("o30", "רשימת ספקים פעילים", GSHEET, "of_docs", 7700, 9, 8, 30),
      ],
    },
    acc_dropbox: {
      folders: [
        { id: "db_shared",   name: "Shared",    parent: "", count: 0 },
        { id: "db_projects", name: "פרויקטים",  parent: "", count: 0 },
      ],
      files: [
        F("d1", "מצגת_משקיעים.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", "", 1800000, 7, 14, 0),
        F("d2", "חוזה_שותפות.pdf", PDF, "db_shared", 210000, 10, 9, 0),
        F("d3", "תכנית_עבודה.xlsx", XLSX_MIME, "db_projects", 44000, 3, 16, 0),
        F("d4", "לוגו_שותף.png", "image/png", "db_shared", 62000, 12, 10, 0),
      ],
    },
    acc_personal: {
      folders: [
        { id: "pe_docs",   name: "מסמכים אישיים", parent: "", count: 0 },
        { id: "pe_photos", name: "תמונות",        parent: "", count: 0 },
      ],
      files: [
        F("p1", "רשימת קניות", GSHEET, "", 1024, 0, 19, 30),
        F("p2", "ביטוח_רכב.pdf", PDF, "pe_docs", 142000, 15, 13, 0),
        F("p3", "חוזה_דירה.pdf", PDF, "pe_docs", 221000, 40, 17, 45),
        F("p4", "חופשה_2026.jpg", "image/jpeg", "pe_photos", 2450000, 22, 12, 0),
        F("p5", "משפחה.png", "image/png", "pe_photos", 1820000, 30, 15, 10),
      ],
    },
    "drive-local": {
      folders: [
        { id: "lc_docs",   name: "מסמכים",  parent: "", count: 0 },
        { id: "lc_scans",  name: "סריקות",  parent: "", count: 0 },
        { id: "lc_backup", name: "גיבויים", parent: "", count: 0 },
        { id: "lc_sc_jul", name: "יולי 2026", parent: "lc_scans", count: 0 },
        { id: "lc_sc_jun", name: "יוני 2026", parent: "lc_scans", count: 0 },
        { id: "lc_doc_forms", name: "טפסים", parent: "lc_docs", count: 0 },
      ],
      files: [
        F("l1", "דוח_שנתי_2025.pdf", PDF, "", 412000, 3, 10, 0, { starred: true }),
        F("l2", "טופס_פתיחת_ספק.pdf", PDF, "lc_doc_forms", 64000, 9, 11, 30),
        F("l3", "הערות_ישיבה.txt", "text/plain", "lc_docs", 1200, 1, 22, 0),
        F("l4", "סריקה_001.pdf", PDF, "lc_sc_jul", 88000, 0, 7, 10),
        F("l5", "סריקה_002.pdf", PDF, "lc_sc_jul", 91200, 0, 7, 12),
        F("l6", "תמונת_קבלה.jpg", "image/jpeg", "lc_scans", 1245000, 5, 18, 22),
        F("l7", "גיבוי_מסמכים.zip", "application/zip", "lc_backup", 5400000, 2, 3, 0),
        F("l8", "סריקה_003.pdf", PDF, "lc_sc_jul", 79400, 0, 7, 14),
        F("l9", "סריקה_004.pdf", PDF, "lc_sc_jul", 102300, 1, 9, 2),
        F("l10", "סריקה_060.pdf", PDF, "lc_sc_jun", 66800, 34, 8, 45),
        F("l11", "סריקה_061.pdf", PDF, "lc_sc_jun", 71100, 33, 8, 47),
        F("l12", "טופס_101.pdf", PDF, "lc_doc_forms", 51200, 21, 12, 0),
        F("l13", "טופס_ניכוי_במקור.pdf", PDF, "lc_doc_forms", 47800, 21, 12, 5),
        F("l14", "רשימת_מלאי.xlsx", XLSX_MIME, "lc_docs", 92400, 7, 15, 20, { starred: true }),
        F("l15", "מכתב_ללקוח.docx", DOCX_MIME, "lc_docs", 27600, 13, 10, 10),
        F("l16", "גיבוי_מיילים.zip", "application/zip", "lc_backup", 8900000, 9, 3, 0),
        F("l17", "צילום_חשבונית.jpg", "image/jpeg", "lc_scans", 2210000, 2, 19, 40),
        // …and what every real drive holds beside its Hebrew names: files named left to right — one
        // of them longer than a card or a phone's row, which is where a name loses a part
        F("l18", "office-browser-first-run-2026-10-05.png", "image/png", "lc_scans", 318000, 0, 8, 2),
        F("l19", "pairing-offer-vps1.jsonl", "application/json", "lc_docs", 4200, 0, 8, 5),
      ],
    },
  };

  // The office Drive carries the full ten-year archive; the local disk carries a smaller one (three
  // years of scans), because a local box is not where a decade lives. The personal and Dropbox
  // accounts stay small on purpose — the switcher has to show a real difference in scale.
  (function () {
    var big = genDrive(20260727, 2026);
    DRIVE.acc_office.folders = DRIVE.acc_office.folders.concat(big.folders);
    DRIVE.acc_office.files = DRIVE.acc_office.files.concat(big.files);
    var small = genDrive(770231, 2026);
    var keep = {};
    small.folders = small.folders.filter(function (f) {
      var ok = f.id === "ar" || /^ar_(2024|2025|2026)/.test(f.id);
      if (ok) keep[f.id] = 1;
      return ok;
    });
    small.files = small.files.filter(function (f) { return keep[f.folder]; });
    DRIVE["drive-local"].folders = DRIVE["drive-local"].folders.concat(small.folders);
    DRIVE["drive-local"].files = DRIVE["drive-local"].files.concat(small.files);
  })();

  // FOLDERS/FILES are pointers into the ACTIVE account's content, so every existing route/mutation
  // (move/rename/trash/delete/upload, folderCounts) operates on the current account and persists there.
  var FOLDERS, FILES;
  function useAccount(id) {
    if (!DRIVE[id]) DRIVE[id] = { folders: [], files: [] };
    ACTIVE_ID = id; FOLDERS = DRIVE[id].folders; FILES = DRIVE[id].files;
  }
  useAccount(ACTIVE_ID);
  var nextId = 1000;

  function hintFor(p) {
    return ({ gdrive: "person141@example.com", gdrive_sa: "svc@project.iam", dropbox: "person142@example.com",
              dropbox_token: "אסימון •••••", onedrive: "person143@example.com", s3: "bucket · region" })[p] || "demo@local";
  }
  // Connect a fresh instance (starts with an empty Drive) — used by the connect flow + OAuth hook below.
  function addAccount(protocol, label) {
    var id = (protocol || "custom") + "-" + (nextId++);
    var acc = { id: id, provider: protocol || "custom", protocol: protocol || "custom",
                label: label || protocol || "חשבון", email: hintFor(protocol),
                account_hint: hintFor(protocol), color: "var(--plum)", status: "ok" };
    ACCOUNTS.push(acc); DRIVE[id] = { folders: [], files: [] };
    return acc;
  }
  // Cloud providers offered by the connect flow (icon/name/description + per-method auth). OAuth methods
  // carry a `sim-oauth:<protocol>` start_url that the window.open hook below turns into a real handoff.
  var PROVIDERS = [
    { name: "אחסון מקומי", icon: "hard-drive", builtin: true, description: "אחסון מובנה על השרת — מוכן לשימוש",
      auth_methods: [{ label: "שימוש באחסון המקומי", protocol: "drive_local", recommended: true, can: "קריאה וכתיבה של קבצים מקומיים" }] },
    { name: "Google Drive", icon: "cloud", description: "סנכרון קבצים ותיקיות מ-Google Drive",
      auth_methods: [
        { label: "התחברות עם Google", protocol: "gdrive", recommended: true, start_url: "sim-oauth:gdrive",
          can: "גישה לקבצים ולתיקיות", explain: "נפתח חלון אישור מאובטח של Google — הסיסמה שלך אינה עוברת דרך המערכת." },
        { label: "חשבון שירות (Service Account)", protocol: "gdrive_sa", can: "גישת שרת-לשרת ללא דפדפן",
          needs: ["client_email", "private_key"], help_url: "https://console.cloud.google.com/iam-admin/serviceaccounts" }] },
    { name: "Dropbox", icon: "cloud", description: "חיבור לתיקיות Dropbox",
      auth_methods: [
        { label: "התחברות עם Dropbox", protocol: "dropbox", recommended: true, start_url: "sim-oauth:dropbox",
          can: "גישה לקבצים", explain: "נפתח חלון אישור של Dropbox." },
        { label: "אסימון גישה", protocol: "dropbox_token", needs: ["access_token"], can: "חיבור מהיר עם אסימון" }] },
    { name: "OneDrive", icon: "cloud", description: "חיבור ל-Microsoft OneDrive",
      auth_methods: [
        { label: "התחברות עם Microsoft", protocol: "onedrive", recommended: true, start_url: "sim-oauth:onedrive",
          can: "גישה לקבצים ולתיקיות", explain: "נפתח חלון אישור של Microsoft." }] },
    { name: "Amazon S3 (ותואמי S3)", icon: "database", description: "דלי אחסון S3 או תואם (MinIO, R2)",
      auth_methods: [
        { label: "מפתחות גישה", protocol: "s3", recommended: true, needs: ["access_key_id", "secret_access_key", "bucket", "region"],
          can: "קריאה וכתיבה לדלי", help_url: "https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html" }] },
  ];
  // The connect flow hands OAuth off via window.open(start_url). Real consent can't run offline, so
  // recognize our `sim-oauth:<protocol>` marker, provision the connection after a short "consent" delay
  // (the app polls GET connections and picks up the fresh one), and return a stub window.
  try {
    var _open = window.open ? window.open.bind(window) : null;
    window.open = function (u) {
      var m = String(u || "").match(/^sim-oauth:(\w+)/);
      if (m) {
        var proto = m[1];
        var prov = PROVIDERS.filter(function (p) { return (p.auth_methods || []).some(function (a) { return a.protocol === proto; }); })[0];
        setTimeout(function () { addAccount(proto, prov ? prov.name : proto); }, 1400);
        return { closed: false, close: function () {}, focus: function () {}, blur: function () {} };
      }
      return _open ? _open.apply(null, arguments) : null;
    };
  } catch (e) {}

  // `mine` and `owner_id` are the service's, not the page's guess: the page says «אני» only where the
  // service says the row is the reader's own, and a row with no owner at all reads «לא ידוע».
  var ME_OWNER = "בינה · מנהל";
  function owned(by) { var mine = (by || ME_OWNER) === ME_OWNER; return { owner: by || ME_OWNER, owner_id: mine ? "admin" : "", mine: mine }; }
  function publicFile(f) {
    return Object.assign({ id: f.id, name: f.name, size: f.size, created: f.created, mime: f.mime, folder: f.folder,
                           shared: (f.shared || []).slice(), starred: !!f.starred, opened: f.opened }, owned(f.owner));
  }
  /* The three cross-cutting views. They are QUERIES over the same files, not places — which is why
     a file can be in Recent and Starred and a folder all at once, and why moving it changes none
     of them. Recent sorts by OPENED (Drive's rule), not created. */
  function viewFiles(view) {
    var live = FILES.filter(function (f) { return !f.trashed; });
    if (view === "starred") return live.filter(function (f) { return f.starred; });
    if (view === "shared")  return live.filter(function (f) { return f.owner !== ME_OWNER; });
    if (view === "recent")  return live.slice().sort(function (a, b) {
      return String(b.opened || b.created).localeCompare(String(a.opened || a.created));
    }).slice(0, 25);
    return live;
  }
  // a folder has an owner too — the account whose drive this is
  function folderCounts() {
    return FOLDERS.map(function (fo) {
      fo.count = FILES.filter(function (f) { return f.folder === fo.id && !f.trashed; }).length;
      return Object.assign({}, fo, owned());
    });
  }
  function idsOf(b) {
    if (Array.isArray(b.ids)) return b.ids.slice();
    if (b.id != null) return [b.id];
    return [];
  }
  function parseBody(opts) {
    try { return opts && opts.body ? JSON.parse(opts.body) : {}; }
    catch (e) { return {}; }
  }
  function j(body, status) {
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: status || 200, headers: { "Content-Type": "application/json" },
    }));
  }

  window.fetch = function (url, opts) {
    var u = String(url);
    var qIdx = u.indexOf("?");
    var path = (qIdx === -1 ? u : u.slice(0, qIdx)).replace(/^\/+/, "");
    var params = new URLSearchParams(qIdx === -1 ? "" : u.slice(qIdx + 1));

    if (/(^|\/)api\/folders$/.test(path)) {
      if (opts && opts.method === "POST") {                 // a new folder, under the one it was made in
        var nb = parseBody(opts), nname = String(nb.name || "").trim();
        if (!nname) return j({ error: "folder name required" }, 400);
        var nf = { id: "nf" + (nextId++), name: nname, parent: nb.parent || "", count: 0 };
        FOLDERS.push(nf);
        return j({ folder: { id: nf.id, name: nf.name, parent: nf.parent || null } }, 201);
      }
      var act = ACCOUNTS.filter(function (a) { return a.id === ACTIVE_ID; })[0] || {};
      return j({ folders: folderCounts(),
                 connection: { id: act.id, protocol: act.protocol, label: act.label, profile_id: null, is_private: false } });
    }
    if (/(^|\/)api\/files$/.test(path)) {
      var files, view = params.get("view") || "";
      if (params.get("trash") === "1") files = FILES.filter(function (f) { return f.trashed; });
      else if (view) files = viewFiles(view);
      else {
        var fid = params.get("folder");
        files = FILES.filter(function (f) { return f.folder === fid && !f.trashed; });
      }
      return j({ files: files.map(publicFile), folders: [], view: view });
    }
    // starring is a per-file toggle, not a move — it never changes where the file lives
    if (/(^|\/)api\/star$/.test(path)) {
      var sb = parseBody(opts), sids = idsOf(sb);
      FILES.forEach(function (f) {
        if (sids.indexOf(f.id) === -1) return;
        f.starred = sb.starred == null ? !f.starred : !!sb.starred;
      });
      return j({ ok: true });
    }
    // quota — the storage meter is the one place a drive tells you its own limits
    if (/(^|\/)api\/storage$/.test(path)) {
      var used = FILES.reduce(function (n, f) { return n + (f.size || 0); }, 0);
      var acc = ACCOUNTS.filter(function (a) { return a.id === ACTIVE_ID; })[0] || {};
      // local storage is disk-bound, cloud accounts carry the provider's plan quota
      var total = acc.provider === "local" ? 250 * 1e9 : acc.id === "acc_personal" ? 15 * 1e9 : 2 * 1e12;
      // the personal account's warning ("92% מלא") has to be TRUE, so bias its baseline to match
      var baseline = acc.id === "acc_personal" ? 13.6e9 : acc.provider === "local" ? 41e9 : 388e9;
      return j({ files: FILES.length, used: baseline + used, limit: total,
                 percent: Math.round(10000 * (baseline + used) / total) / 100 });
    }
    if (/(^|\/)api\/search$/.test(path)) {
      var q = (params.get("q") || "").toLowerCase();
      var found = FILES.filter(function (f) { return !f.trashed && f.name.toLowerCase().indexOf(q) !== -1; });
      return j({ files: found.map(publicFile) });
    }
    if (/(^|\/)api\/move$/.test(path)) {
      var mb = parseBody(opts), mids = idsOf(mb);
      FILES.forEach(function (f) { if (mids.indexOf(f.id) !== -1) f.folder = mb.to; });
      return j({ ok: true });
    }
    if (/(^|\/)api\/rename$/.test(path)) {
      var rb = parseBody(opts);
      var rf = FILES.find(function (f) { return f.id === rb.id; });
      if (rf && rb.name) rf.name = rb.name;
      return j({ ok: true });
    }
    if (/(^|\/)api\/trash$/.test(path)) {
      var tb = parseBody(opts), tids = idsOf(tb);
      FILES.forEach(function (f) {
        if (tids.indexOf(f.id) === -1) return;
        if (tb.restore) { f.trashed = false; if (f._prevFolder) { f.folder = f._prevFolder; delete f._prevFolder; } }
        else { f.trashed = true; f._prevFolder = f.folder; }
      });
      return j({ ok: true });
    }
    if (/(^|\/)api\/delete$/.test(path)) {
      var db = parseBody(opts), dids = idsOf(db);
      FILES = FILES.filter(function (f) { return dids.indexOf(f.id) === -1; });
      return j({ ok: true });
    }
    var cm = path.match(/api\/file\/([^/]+)\/content$/);
    if (cm) {
      // best-effort only: real previews/downloads set <iframe src>/<a href> directly, which the
      // browser fetches as a native resource load, never through window.fetch/XHR — see report.
      var cf = FILES.find(function (f) { return f.id === decodeURIComponent(cm[1]); });
      var body = cf ? ("תוכן לדוגמה עבור " + cf.name) : "קובץ לא נמצא";
      return Promise.resolve(new Response(body, {
        status: cf ? 200 : 404, headers: { "Content-Type": "text/plain; charset=utf-8" },
      }));
    }
    if (/(^|\/)connections\/[^/]+\/probe$/.test(path)) {
      var probeId = (path.match(/connections\/([^/]+)\/probe/) || [])[1];
      var pc = ACCOUNTS.filter(function (c) { return c.id === probeId; })[0];
      return j({ ok: true, account_hint: pc ? pc.account_hint : "demo@local" });
    }
    if (/(^|\/)connections\/[^/]+$/.test(path) && opts && opts.method === "DELETE") {
      var delId = (path.match(/connections\/([^/]+)$/) || [])[1];
      ACCOUNTS = ACCOUNTS.filter(function (c) { return c.id !== delId; });
      delete DRIVE[delId];
      if (ACTIVE_ID === delId) useAccount((ACCOUNTS[0] && ACCOUNTS[0].id) || "drive-local");
      return j({ ok: true });
    }
    if (/(^|\/)connections\/select$/.test(path)) {
      var selB = parseBody(opts); if (selB.id && DRIVE[selB.id]) useAccount(selB.id);
      return j({ ok: true, active: ACTIVE_ID });
    }
    if (/(^|\/)connections$/.test(path) && opts && opts.method === "POST") {
      var addB = parseBody(opts); var nc = addAccount(addB.protocol, addB.label);
      return j({ ok: true, id: nc.id });
    }
    if (/(^|\/)connections$/.test(path)) return j({ connections: ACCOUNTS, active: ACTIVE_ID });
    if (/(^|\/)readyz$/.test(path)) return j({ ready: true });
    // No INDOX/sync rail — this is a plain multi-account drive. Return zero extensions so the sidebar
    // shows only the account's own folder tree (the app renders an empty #railMount cleanly).
    if (/(^|\/)extensions$/.test(path) && params.get("slot") === "rail") return j({ extensions: [] });
    if (/(^|\/)providers$/.test(path)) return j({ providers: PROVIDERS });

    // never let anything escape to the real network — unknown routes get a harmless empty 200
    return j({});
  };

  /* ── XHR shim: only api/upload uses XMLHttpRequest in app.js (for xhr.upload.onprogress),
     everything else goes through fetch above. A Proxy wraps a real XHR instance so any other/
     future XHR usage still works untouched; only requests whose URL matches api/upload are
     diverted into the synthetic multipart handler below. ── */
  function mockUpload(state, uploadState, body) {
    var folder = (body && body.get) ? body.get("folder") : null;
    var incoming = (body && body.getAll) ? body.getAll("files") : [];
    var total = incoming.reduce(function (n, f) { return n + (f.size || 0); }, 0) || 1;
    var loaded = 0;
    var steps = Math.max(1, Math.min(5, incoming.length || 1));
    var i = 0;
    function tick() {
      i++;
      loaded = Math.round((total * i) / steps);
      if (uploadState.onprogress) {
        uploadState.onprogress({ lengthComputable: true, loaded: Math.min(loaded, total), total: total });
      }
      if (i < steps) { setTimeout(tick, 60); return; }
      // commit: append each real File (with its real name/size/type) into the live store
      incoming.forEach(function (file) {
        FILES.push({
          id: "u" + (nextId++), name: file.name || "קובץ", size: file.size || 0,
          mime: file.type || "application/octet-stream", folder: folder || (FOLDERS[0] && FOLDERS[0].id),
          created: isoish(0, new Date().getHours(), new Date().getMinutes()), trashed: false,
        });
      });
      state.status = 200; state.readyState = 4;
      state.responseText = JSON.stringify({ ok: true, uploaded: incoming.length });
      state.response = state.responseText;
      if (state.onload) state.onload();
    }
    setTimeout(tick, 60);
  }

  function XHRShim() {
    var real = new RealXHR();
    var mocking = false;
    // `state`/`uploadState` are single stable objects, always exposed as the same reference for
    // status/readyState/responseText/response/onload/onerror/.upload — app.js assigns its handlers
    // (xhr.upload.onprogress, xhr.onload, xhr.onerror) BEFORE calling xhr.open(), i.e. before this
    // shim knows yet whether the request will be mocked. So routing can't switch objects based on
    // `mocking` at get/set time; instead the real XHR's own events are wired, once, to forward into
    // these same objects — passthrough (non-upload) requests behave exactly as a real XHR would.
    var state = { status: 0, readyState: 0, responseText: "", response: "", onload: null, onerror: null };
    var uploadState = { onprogress: null };
    function syncFromReal() {
      state.status = real.status; state.readyState = real.readyState;
      state.responseText = real.responseText; state.response = real.response;
    }
    try { real.upload.onprogress = function (e) { if (uploadState.onprogress) uploadState.onprogress(e); }; }
    catch (e) { /* some environments restrict this pre-open; harmless */ }
    real.onload = function () { syncFromReal(); if (state.onload) state.onload(); };
    real.onerror = function () { syncFromReal(); if (state.onerror) state.onerror(); };
    real.onreadystatechange = function () { syncFromReal(); };

    var STATE_PROPS = { status: 1, readyState: 1, responseText: 1, response: 1, onload: 1, onerror: 1 };
    var proxy = new Proxy({}, {
      get: function (_t, prop) {
        if (prop === "open") {
          return function (method, url) {
            mocking = /api\/upload(\?|$)/.test(String(url));
            if (!mocking) return real.open.apply(real, arguments);
          };
        }
        if (prop === "setRequestHeader") {
          return function () { if (!mocking) return real.setRequestHeader.apply(real, arguments); };
        }
        if (prop === "send") {
          return function (body) {
            if (!mocking) return real.send.apply(real, arguments);
            mockUpload(state, uploadState, body);
          };
        }
        if (prop === "upload") return uploadState;
        if (STATE_PROPS.hasOwnProperty(prop)) return state[prop];
        var v = real[prop];
        return typeof v === "function" ? v.bind(real) : v;
      },
      set: function (_t, prop, value) {
        if (STATE_PROPS.hasOwnProperty(prop)) { state[prop] = value; return true; }
        try { real[prop] = value; } catch (e) { /* some XHR props are read-only pre-open */ }
        return true;
      },
    });
    return proxy;
  }
  XHRShim.prototype = RealXHR.prototype;
  window.XMLHttpRequest = XHRShim;
})();
