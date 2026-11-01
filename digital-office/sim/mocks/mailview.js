/* Mock backend for מייל (mailview) — a live-looking Hebrew business inbox for "בינה פתרונות בע״מ",
   served from an in-memory store so the LIVE app's own frontend (apps/mail/mailview/static:
   index.html, rules-lib.js, app.js) runs with no backend. Real UI code is untouched; only
   window.fetch is intercepted (the app never uses XHR — every call goes through jf() → fetch()).

   It answers what the live SERVICE answers — the shapes below are read off apps/mail/mailview/app.py
   (the screen's own BFF) and the mail service behind it (apps/mail/mailapi/{service,options,
   mailsetup,connections_api}.py, apps/mail/mailboxd/mailboxd.py), not off what a page happened to
   read. Its refusals are the service's too, in the service's words: a primary mailbox is not
   deleted, a local profile is not removed as an account, and the engine's PROCESSED row is not
   dropped or renamed without `confirm_processed`.

   The mailbox (method — response):
     GET  api/account                    -> { user, mode: "local"|"gmail" }
     GET  api/labels                     -> { labels: [] }      POST {name} -> { ok, name }
     GET  api/label-map                  -> { gmail: { labels: { KEY: {name, …} }, rows } }  (the rule store's vocabulary)
     GET  api/messages?limit=&view=&label=&q=&before_uid=&win=&tz=&test=
             view = attention|sent|drafts|spam|trash|starred|important|all|unread|archived (omitted = the INBOX folder)
             win  = all|30m|1h|today|month — cut on the corpus's own clock, since its newest mail is its "now"
                                         -> { messages, count, total, has_more, next_cursor,
                                              test_total, test_hidden, win, since_ts }
     GET  api/thread/<threadId>          -> { threadId, messages: [full, …] } oldest-first
     GET  api/message/<id>               -> the full message
     GET  api/doc-context/<id>           -> { found, docs: [...] }
     POST api/tag  { id, add|remove }    -> { ok }
     POST api/mark { id|ids, mark: starred|important|unread|archived, on } -> { ok, count, mark, on }
             (archived is the one that is not a label ADD: it REMOVES INBOX, as the service does)
     POST api/send { to, subject, body } -> { ok, id }           (appends to the active mailbox's SENT)
     GET  api/attachment/<id>/<index>    -> bytes (the UI opens this as a link, not a fetch)
   The rule store and the mailbox's own settings:
     GET  api/organizer/defaults         -> { defaults: { mail: { organizer: { mode, rules } } }, rollback }
     PUT  api/organizer/defaults         -> 200 { ok, defaults, rollback, ignored } | 400 { error, problems }
                                            | 409 { error, confirm_with } for a PROCESSED row dropped or renamed
     GET  api/connections                -> { active, connections: [{id, protocol, label, account_hint, status}] }
     POST api/connections                -> 201 { id, … }        DELETE api/connections/<id> -> { ok, id } | 409
     GET  api/connections/<id>/probe     -> { ok, reason, id, account_hint }
     POST api/connections/select {id}    -> { ok, active }
     GET  api/mailboxes                  -> { available, domain, primary, mailboxes: [...], count }
     POST api/mailboxes {local,password} -> 201 { ok, address }  DELETE api/mailboxes/<address> -> { ok } | 409
     GET  api/setup/status               -> { mode, domain, selector, checks: [...] }
     GET  api/providers                  -> { providers: [...] }  (the service's two: the local server, Gmail)
   For the simulation's own account switcher (overlay/switcher.js), over the same accounts:
     GET  api/accounts · POST api/account/select · POST api/account/add · GET api/mail-providers
*/
(function () {
  var realFetch = window.fetch ? window.fetch.bind(window) : null;

  /* ── connected mail instances (local-first + providers). One active at a time; "all" = unified. ──
     `protocol` is the service's name for how an account is reached (connections_client.PROTOCOLS);
     the local server's account also carries the ADDRESS of its mailbox, which is what the service
     reports as its hint. The rest (`provider`, `color`, `log`) is the simulation's switcher's. */
  var MAIL_DOMAIN = "bina.localhost";                     // a local-only domain: the install the service calls mode "local"
  var MAIL_ACCOUNTS = [
    { id: "local", provider: "local", protocol: "mail_imap_local", address: "office@" + MAIL_DOMAIN,
      label: "דואר מקומי", identity: "מקומי · מובנה", mode: "local", color: "var(--olive)", status: "ok", builtin: true,
      checked: 2, log: [{ mins: 2, level: "info", msg: "תיבה מקומית זמינה" }] },
    { id: "gmail_office", provider: "gmail", protocol: "mail_gmail_oauth", label: "Gmail", identity: "person127@example.com", mode: "gmail", color: "#ea4335", status: "ok",
      checked: 4, log: [{ mins: 4, level: "info", msg: "סנכרון הושלם — 12 הודעות חדשות" }, { mins: 1440, level: "info", msg: "אסימון הגישה חודש אוטומטית" }, { mins: 20160, level: "info", msg: "החשבון חובר בהצלחה" }] },
    { id: "outlook_admin", provider: "outlook", protocol: "mail_imap_app_password", label: "Outlook", identity: "person133@example.com", mode: "outlook", color: "#0078d4", status: "warning",
      reason: "אימות Microsoft יפוג בעוד 3 ימים — מומלץ לחדש את החיבור", checked: 33,
      log: [{ mins: 33, level: "warn", msg: "אסימון הגישה מתקרב לפקיעה (3 ימים)" }, { mins: 2880, level: "info", msg: "סנכרון הושלם — 4 הודעות" }, { mins: 43200, level: "info", msg: "החשבון חובר בהצלחה" }] },
  ];
  var MAIL_ACTIVE = "gmail_office", nextAcctId = 1;
  function activeAcct() { return MAIL_ACCOUNTS.filter(function (a) { return a.id === MAIL_ACTIVE; })[0] || MAIL_ACCOUNTS[0]; }
  function isLocal(a) { return !!a && a.protocol === "mail_imap_local"; }
  // api/account, as the screen's own service answers it: the active connection's hint, and one of the
  // two modes it knows (mailview/app.py `account`)
  function accountInfo() {
    if (MAIL_ACTIVE === "all") return { user: "כל התיבות", mode: "gmail" };
    var a = activeAcct(); return { user: a.address || a.identity, mode: isLocal(a) ? "local" : "gmail" };
  }
  // a row of the connection catalog (mailapi `GET /connections`)
  function connRow(a) { return { id: a.id, protocol: a.protocol, label: a.label, account_hint: a.address || a.identity, status: "ok" }; }
  function connActive() { return MAIL_ACTIVE === "all" ? MAIL_ACCOUNTS[0].id : MAIL_ACTIVE; }

  /* ── the addresses at the local domain (mailboxd `GET /mailboxes`). One at a fresh install: the
     primary, which is the local account above. Each further address is created WITH its account, in
     one act, and removed with it — the service's rule (profiles.create_profile / delete_profile). ── */
  var MAILBOXES = [{ address: "office@" + MAIL_DOMAIN, primary: true, maildir_exists: true, size_bytes: 1289000 }];
  function mailboxRow(m) {
    return { address: m.address, domain: MAIL_DOMAIN, primary: !!m.primary, maildir: "/var/mail/" + MAIL_DOMAIN + "/" + m.address.split("@")[0] + "/",
             maildir_exists: !!m.maildir_exists, size_bytes: m.size_bytes || 0 };
  }
  // the admin ring (profiles.require_admin): an address is made and removed AS a profile of the local server
  var NOT_LOCAL = "ניהול תיבות דואר מחייב לפעול כפרופיל של שרת הדואר המקומי. בחר חשבון מקומי בסרגל החשבונות ונסה שוב.";
  var MAIL_PROVIDERS = [
    { name: "דואר מקומי", provider: "local", icon: "mail", builtin: true, description: "תיבת דואר מקומית מובנית",
      auth_methods: [{ label: "שימוש בדואר המקומי", protocol: "local", recommended: true, can: "קריאה ושליחה מקומית" }] },
    { name: "Gmail", provider: "gmail", icon: "mail", description: "חשבון Google Gmail",
      auth_methods: [{ label: "התחברות עם Google", protocol: "gmail", recommended: true, start_url: "sim-oauth:gmail",
        can: "קריאה, שליחה ותוויות", explain: "נפתח חלון אישור מאובטח של Google — הסיסמה שלך אינה עוברת דרך המערכת." }] },
    { name: "Outlook", provider: "outlook", icon: "mail", description: "חשבון Microsoft Outlook",
      auth_methods: [{ label: "התחברות עם Microsoft", protocol: "outlook", recommended: true, start_url: "sim-oauth:outlook",
        can: "קריאה ושליחה", explain: "נפתח חלון אישור של Microsoft." }] },
    { name: "IMAP", provider: "imap", icon: "mail", description: "חשבון IMAP כללי (כל ספק)",
      auth_methods: [{ label: "חיבור עם פרטי IMAP", protocol: "imap", needs: ["server", "username", "password"], can: "קריאה ושליחה דרך IMAP/SMTP" }] },
  ];
  /* The catalog the SERVICE answers (mailapi `GET /providers`): its two providers, in its words. The
     screen's own guided connect (settings › חיבור חשבון) reads this one; the list above is the
     simulation's switcher's. Google's consent window cannot open offline, so its address is the
     `sim-oauth:` hand-off below. */
  var SERVICE_PROVIDERS = [
    { id: "local", name: "תיבת דואר מקומית", icon: "server", builtin: true,
      description: "שרת הדואר שמובנה במערכת. מחבר את התיבה הקיימת לקריאה — יצירת כתובת חדשה נעשית במסך „הוספת כתובת דואר בחברה”.",
      auth_methods: [{ id: "builtin", label: "מובנה — לא נדרש חיבור", protocol: "mail_imap_local", needs: [], recommended: true,
                       can: "קריאת דואר, חיפוש, תוויות ושליחה בתוך התיבה המקומית." }] },
    { id: "gmail", name: "Gmail", icon: "mail",
      description: "החשבון שלך ב־Google. הדואר נשאר ב־Gmail; המערכת עובדת עליו ישירות דרך IMAP.",
      auth_methods: [
        { id: "oauth", label: "התחברות עם Google", protocol: "mail_gmail_oauth", needs: [], recommended: true,
          can: "קריאה, חיפוש, תוויות ושליחה בחשבון שתאשר.",
          explain: "נפתח חלון של Google. לאחר האישור החשבון נוצר כאן ואפשר לבדוק אותו ולהפעיל אותו. אפשר לסגור את החלון בכל שלב — לא ייווצר חיבור.",
          start_url: "sim-oauth:mail_gmail_oauth" },
        { id: "app_password", label: "סיסמת אפליקציה", protocol: "mail_imap_app_password", needs: ["username", "password"],
          can: "קריאה, חיפוש, תוויות ושליחה — בלי חלון אישור.",
          explain: "דורש אימות דו־שלבי פעיל בחשבון Google, ואז יצירת סיסמת אפליקציה בת 16 תווים. הזן את כתובת המייל המלאה ואת הסיסמה שנוצרה.",
          help_url: "https://myaccount.google.com/apppasswords" }] },
  ];
  // the switcher's names for a way in, and the service's
  var PROTO_OF = { local: "mail_imap_local", gmail: "mail_gmail_oauth", outlook: "mail_imap_app_password", imap: "mail_imap_app_password" };
  function addMailAccount(protocol, label, hint) {
    var svc = PROTO_OF[protocol] || protocol || "mail_imap_app_password";
    var prov = PROTO_OF[protocol] ? protocol : svc === "mail_imap_local" ? "local" : "gmail";
    var id = (protocol || "acct") + "_" + (nextAcctId++);
    var acc = { id: id, provider: prov, protocol: svc, label: label || protocol || "חשבון",
                identity: hint || prov + "@example.com", mode: svc === "mail_imap_local" ? "local" : prov,
                color: "var(--plum)", status: "ok" };
    MAIL_ACCOUNTS.push(acc); return acc;
  }
  // OAuth handoff (offline): the connect flow's window.open(sim-oauth:<provider>) provisions the account
  // after a short "consent" delay; whoever asked (the switcher, or the screen's own guided connect, which
  // polls api/connections for an account that was not there before) then picks up the new one.
  try {
    var _open = window.open ? window.open.bind(window) : null;
    window.open = function (u) {
      var mm = String(u || "").match(/^sim-oauth:(\w+)/);
      if (mm) {
        var proto = mm[1];
        var pr = MAIL_PROVIDERS.filter(function (p) { return p.provider === proto; })[0];
        setTimeout(function () {
          if (proto === "mail_gmail_oauth") addMailAccount(proto, "Gmail", "person144@example.com");
          else addMailAccount(proto, pr ? pr.name : proto);
        }, 1400);
        return { closed: false, close: function () {}, focus: function () {}, blur: function () {} };
      }
      return _open ? _open.apply(null, arguments) : null;
    };
  } catch (e) {}

  /* ── the rule store (mailapi options.py): ONE document for every mailbox. These are this office's
     own rules, written in the engine's vocabulary — the KEYs the label engine and this screen's triage
     dot look up (DOC_TO_SYNC / SYNCED_DOC / FAILED_DOC), the system rows that carry no rule of their
     own, and PROCESSED, the engine's only cursor. ── */
  var NEVER_MATCH = "__NEVER_MATCH_SYNC_STATE__";
  function sysRow(n, key, label) {
    return { EVENT: "SYSTEM", KEY: key, LABEL: label, RULE: 'contains(email.text, "' + NEVER_MATCH + '")', TYPE: key, row_number: n, enabled: true };
  }
  function evRow(n, key, label, rule, enabled) {
    return { EVENT: "ON_CREATE", KEY: key, LABEL: label, RULE: rule, TYPE: "ON_CREATE_EVENT", row_number: n, enabled: enabled !== false };
  }
  var ORGANIZER = { mail: { organizer: { mode: "default", rules: [
    evRow(1, "SUPPLIER_MAIL", "ספקים", 'inList(email.from, ["person130@example.com", "person145@example.com", "person128@example.com", "person146@example.com"])'),
    evRow(2, "CLIENT_MAIL", "לקוחות", 'inList(email.from, ["person147@example.com", "person148@example.com", "person149@example.com"])'),
    evRow(3, "FINANCE", "כספים", 'containsAny(email.text, ["דוח תנועות", "מע״מ", "חשבונית מס"])'),
    evRow(4, "URGENT", "דחוף", 'containsAny(email.subject, ["דחוף", "בהול"])'),
    evRow(5, "NEWSLETTER", "-INBOX", 'containsAny(email.text, ["ביטול הרשמה", "unsubscribe"])', false),
    evRow(6, "DOC_TO_SYNC", "אינדוקס - לטיפול", 'attachments.length > 0 && includes(email.labels, "ספקים")'),
    sysRow(7, "IN_PROGRESS", "אינדוקס - בעיבוד"),
    sysRow(8, "SYNCED_DOC", "אינדוקס - טופל"),
    sysRow(9, "FAILED_DOC", "אינדוקס - נכשל"),
    sysRow(10, "PROCESSED", "תוויות-טופל"),
  ] } } };
  var ORGANIZER_PREV = null;                               // the document before the last save (the service's `rollback`)
  function rulesOf(doc) { return (((doc || {}).mail || {}).organizer || {}).rules || []; }
  function processedRow(doc) { return rulesOf(doc).filter(function (r) { return r && r.KEY === "PROCESSED"; })[0] || null; }
  /* PUT's two refusals, as options.py makes them: the document's own faults (400, each pinned to a row
     and a field), and the guard on the engine's cursor (409 unless the request says it is meant). The
     rule's SYNTAX is the screen's own check (rules-lib.js) and the service's tokenizer; this mock reads
     only what a document can get wrong by its shape. */
  function organizerProblems(doc) {
    var org = ((doc || {}).mail || {}).organizer, out = [], seen = {};
    if (!org || !Array.isArray(org.rules)) return [{ row: null, field: "mail.organizer.rules", message: "rules must be a list" }];
    org.rules.forEach(function (r, i) {
      var key = r && r.KEY;
      if (typeof key !== "string" || !key.trim()) out.push({ row: i, field: "KEY", message: "KEY is required" });
      else if (!/^[A-Z][A-Z0-9_]*$/.test(key)) out.push({ row: i, field: "KEY", message: "KEY must be UPPER_SNAKE_CASE (A-Z, 0-9, _; starts with a letter)" });
      else if (key in seen) out.push({ row: i, field: "KEY", message: "duplicate KEY '" + key + "' (also row " + seen[key] + ")" });
      else seen[key] = i;
      if (typeof r.LABEL !== "string" || !r.LABEL.trim()) out.push({ row: i, field: "LABEL", message: "LABEL is required" });
      else if (r.LABEL.trim() === "-") out.push({ row: i, field: "LABEL", message: '"-" names nothing to remove' });
      if (typeof r.RULE !== "string" || !r.RULE.trim()) out.push({ row: i, field: "RULE", message: "RULE must be a non-empty expression" });
      if (r.TYPE === "ON_CREATE_EVENT") { /* an event rule */ }
      else if (typeof r.TYPE === "string" && r.TYPE && r.TYPE === key) {
        if (String(r.RULE || "").indexOf(NEVER_MATCH) === -1)
          out.push({ row: i, field: "TYPE", message: 'TYPE == KEY marks a SYSTEM row, whose RULE must be the never-match sentinel contains(email.text, "' + NEVER_MATCH + '")' });
      } else out.push({ row: i, field: "TYPE", message: "TYPE must be ON_CREATE_EVENT, or equal to KEY for a system mark" });
      if ("enabled" in r && typeof r.enabled !== "boolean") out.push({ row: i, field: "enabled", message: "enabled must be true or false" });
    });
    return out;
  }
  function processedGuard(next) {
    var old = processedRow(ORGANIZER), now = processedRow(next);
    if (!now) return "no PROCESSED row: the label engine stamps it on every message it finishes and uses it as its only cursor, so without it every tick re-processes the whole mailbox. Add the row back, or send {\"confirm_processed\": true} with the document to remove it anyway.";
    var a = String(old && old.LABEL || "").trim(), b = String(now.LABEL || "").trim();
    if (old && a !== b) return "renaming PROCESSED from '" + a + "' to '" + b + "' orphans every message already stamped with the old name — the engine would treat all of them as unprocessed. Send {\"confirm_processed\": true} with the document to rename it anyway.";
    return "";
  }
  // KEY -> label, the lookup the engine and the triage dot share (mailapi `GET /organizer/settings`)
  function organizerSettings() {
    var labels = {}, rows = [];
    rulesOf(ORGANIZER).slice().sort(function (a, b) { return (a.row_number || 0) - (b.row_number || 0); }).forEach(function (r) {
      if (!r || !r.KEY) return;
      var en = r.enabled !== false;
      rows.push(Object.assign({}, r, { enabled: en }));
      labels[r.KEY] = { name: String(r.LABEL || "").trim(), label_id: r.label_id || null, event: r.EVENT || null, rule: r.RULE || null, row_number: r.row_number, enabled: en };
    });
    return { gmail: { labels: labels, rows: rows } };
  }

  /* ── labels: what the mailbox holds. The reader's own come first; the pipeline's live in the same
        list, as they do on a real mailbox, and it is the SCREEN that keeps them out of its surfaces
        (one namespace rule, app.js `isMachineLabel`) — not this list. ── */
  var LABELS = [
    "INBOX", "SENT", "DRAFT", "TRASH", "SPAM", "STARRED", "IMPORTANT", "UNREAD", "SENT-COPY",
    "לקוחות",
    "ספקים",
    "דחוף",
    "מעקב",
    "כספים",
    // the labels the rule store names: the pipeline's (which the screen keeps out of every surface by
    // its namespace rule) and the engine's own mark
    "אינדוקס - לטיפול", "אינדוקס - בעיבוד", "אינדוקס - טופל", "אינדוקס - נכשל", "תוויות-טופל"
  ];

  /* ── messages (mutable in-memory store — tag add/remove persists across calls) ── */
  // Build a supplier-invoice message from the shared business spine (window.__biz). The literal
  // objects below stay as a fallback; when the spine is present they are overwritten from it (see the
  // override just after the array) so mail, INDOX and notifications show ONE canonical document set.
  function bizMsg(key, id) {
    var d = window.__biz && window.__biz.byKey(key);
    if (!d) return null;
    // Plain mail labels only — no INDOX/sync vocabulary (mail is decoupled from INDOX in its own UI).
    var labels = ["INBOX"];
    if (d.unread) labels.push("UNREAD");
    labels.push("ספקים");
    var msg = {
      id: id, threadId: id, from: d.supplier + " <" + d.email + ">", to: "person127@example.com",
      subject: d.subject, date: d.date, labels: labels, hasAttachment: true,
      attachments: [{ filename: d.file, size: d.size }], snippet: d.snippet,
    };
    if (d.body_html) msg.body_html = d.body_html; else msg.body_text = d.body_text;
    return msg;
  }


  /* ══ Ten-year corpus ═══════════════════════════════════════════════════════════════════════════
     The hand-written messages above are the *hero* set: every pipeline state, every doc-context
     case, the ones the UI map is meant to show. But a mail client that has only fifteen messages
     never has to prove anything — every list fits, no counter ever gets big, no date group is ever
     long, threads are never deep, and search always returns everything.

     So: on top of the hero set we synthesise ~10,000 messages spanning ten years of one Israeli
     accounting office — invoices, receipts, bank statements, VAT filings, client threads with
     real reply chains, newsletters, system noise, spam and deleted mail. It is generated, not
     stored, so the simulation file stays small; and it is generated from a SEEDED PRNG so every
     run, every screenshot and every CI capture sees byte-identical data.

     What this exists to prove: pagination and infinite scroll, unread counters in the hundreds,
     day-grouping across a decade, thread collapse at depth, label volume, attachment variety, and
     that none of the new chrome (rail counts, select-all, filters) falls over at real scale. */
  var LOAD = { messages: 9800 };          // tune here; everything below scales off it
  function LCG(seed) {                    // deterministic — Math.random would break screenshot diffs
    var s = seed >>> 0;
    return function () { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
  }
  var GEN_SUPPLIERS = [
    ["חברת חשמל לישראל", "person130@example.com", "חשבון חשמל", "חשבונית"],
    ["בזק בינלאומי", "person145@example.com", "חשבונית אינטרנט וטלפוניה", "חשבונית"],
    ["ישראל קרטון בע\"מ", "person128@example.com", "חשבונית מס", "חשבונית"],
    ["ספק הענן בע\"מ", "person146@example.com", "קבלה על מנוי חודשי", "קבלה"],
    ["מי אביבים", "person150@example.com", "חשבון מים", "חשבונית"],
    ["דואר ישראל", "person151@example.com", "אישור משלוח", "קבלה"],
    ["ספק משרדי — דפי הדפסה בע\"מ", "person152@example.com", "אישור הזמנה", "חשבונית"],
    ["פלאפון", "person153@example.com", "חשבונית סלולר", "חשבונית"],
    ["שכירות — נכסי הרצל", "person154@example.com", "חשבונית שכירות חודשית", "חשבונית"],
    ["ביטוח לאומי", "person155@example.com", "אישור תשלום", "קבלה"],
    ["בנק הפועלים", "person156@example.com", "דוח תנועות חשבון", "דוח בנק"],
    ["בנק לאומי", "person157@example.com", "דוח תנועות חשבון", "דוח בנק"],
    ["רשות המסים", "person158@example.com", "תזכורת הגשת דוח מע\"מ", "דוח"],
    ["מכבי שירותי בריאות", "person159@example.com", "חשבונית שירותי בריאות", "חשבונית"],
    ["אמזון AWS", "person160@example.com", "AWS Invoice", "חשבונית"],
    ["Google Workspace", "payments-noreply@google.com", "Google Workspace Invoice", "חשבונית"]
  ];
  var GEN_CLIENTS = [
    ["טכנולוגיות אור בע\"מ", "person147@example.com", "דנה לוי"],
    ["סבח סוכנויות", "person148@example.com", "מוחמד סבח"],
    ["רו\"ח דנה כהן", "person149@example.com", "דנה כהן"],
    ["עמית לוי — תמיכה טכנית", "person161@example.com", "עמית לוי"],
    ["מרפאת שיניים ד\"ר שגב", "person162@example.com", "ד\"ר שגב"],
    ["בית קפה ״ארומה רוטשילד״", "person163@example.com", "יוסי מזרחי"],
    ["אולפני הקלטה נובה", "person164@example.com", "נועה ברק"],
    ["מוסך מרכזי חיפה", "person165@example.com", "רמי אבוטבול"]
  ];
  var GEN_THREADS = [
    ["בקשה להצעת מחיר", "נשמח לקבל הצעת מחיר מעודכנת לשירותי הנהלת חשבונות לשנה הקרובה."],
    ["סטטוס הגשת הדוח", "מה הסטטוס של הדוח הרבעוני? הרו\"ח מבקש עדכון."],
    ["מסמכים חסרים לחודש", "חסרים לנו שלוש קבלות מהחודש הקודם — אפשר לשלוח שוב?"],
    ["פגישת סיכום שנה", "נקבע פגישת סיכום? אני פנוי ביום שלישי או חמישי אחה\"צ."],
    ["עדכון פרטי חשבון בנק", "עדכנו אצלנו מספר חשבון חדש — מצורף אישור ניהול חשבון."],
    ["תיאום ביקורת", "רואה החשבון מבקש לתאם ביקורת מלאי לרבעון הקרוב."],
    ["שאלה על חיוב", "יש חיוב שלא זיהינו בכרטסת — אפשר לבדוק?"],
    ["אישור קבלת מסמכים", "קיבלנו, תודה. נעדכן לאחר הבדיקה."]
  ];
  var GEN_NEWSLETTER = [
    ["חדשות המסים", "person166@example.com", "עדכוני חקיקה — מה השתנה החודש"],
    ["Google Cloud", "cloud-noreply@google.com", "What's new in Google Cloud"],
    ["לשכת רואי החשבון", "person167@example.com", "הודעות הלשכה לחברים"],
    ["מרכז העסקים", "person168@example.com", "וובינר: התייעלות תפעולית לעסקים קטנים"]
  ];
  var GEN_SPAM = [
    ["Winner Notification", "prize@lotto-intl.biz", "You have WON $1,000,000 — claim now"],
    ["פרסום", "sale@deals4u.biz", "מבצע בלעדי — 90% הנחה, היום בלבד!"],
    ["Security", "person169@example.com", "Your account will be suspended"]
  ];
  var GEN_ATT = [
    [".pdf", "application/pdf", 180000], [".pdf", "application/pdf", 940000],
    [".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 62000],
    [".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 41000],
    [".jpg", "image/jpeg", 2450000], [".png", "image/png", 780000],
    [".zip", "application/zip", 8400000], [".csv", "text/csv", 12000],
    [".eml", "message/rfc822", 26000]
  ];
  var GEN_ACCTS = ["gmail_office", "gmail_office", "gmail_office", "outlook_admin", "local"];
  var HE_MONTH = ["ינואר","פברואר","מרץ","אפריל","מאי","יוני","יולי","אוגוסט","ספטמבר","אוקטובר","נובמבר","דצמבר"];

  function pad2(n) { return String(n).padStart(2, "0"); }
  function genCorpus() {
    var rnd = LCG(20260727), out = [], uid = 0;
    var today = new Date("2026-07-27T09:00:00");
    var n = LOAD.messages;
    for (var i = 0; i < n; i++) {
      // spread over ~10 years, denser recently — a real mailbox is not uniform
      var skew = Math.pow(rnd(), 2.1);                    // 0..1, biased to 0 (= recent)
      var daysAgo = Math.round(skew * 3650) + 1;
      var d = new Date(today.getTime() - daysAgo * 86400000);
      d.setHours(7 + Math.floor(rnd() * 12), Math.floor(rnd() * 60), 0, 0);
      var date = d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate()) +
                 "T" + pad2(d.getHours()) + ":" + pad2(d.getMinutes()) + ":00";
      var acct = GEN_ACCTS[Math.floor(rnd() * GEN_ACCTS.length)];
      var roll = rnd(), id = "g" + (++uid);
      var labels = [], msg = null;

      if (roll < 0.46) {                                   // supplier document — the bread and butter
        var sp = GEN_SUPPLIERS[Math.floor(rnd() * GEN_SUPPLIERS.length)];
        var att = GEN_ATT[Math.floor(rnd() * 4)];
        var num = 10000 + Math.floor(rnd() * 89999);
        var amount = (50 + rnd() * 9500).toFixed(2);
        labels = ["INBOX", "ספקים"];
        if (rnd() < 0.22) labels.push("כספים");
        // the sync pipeline's own labels, in the proportions a real mailbox shows them — by the names the
        // rule store gives them (SYNCED_DOC / DOC_TO_SYNC / FAILED_DOC), which is how the list's triage
        // dot and the «דורש טיפול» view find them
        var sr = rnd();
        if (sr < 0.62) labels.push("אינדוקס - טופל");
        else if (sr < 0.80) labels.push("אינדוקס - לטיפול");
        else if (sr < 0.88) labels.push("אינדוקס - נכשל");
        msg = { id: id, threadId: id, acct: acct, from: sp[0] + " <" + sp[1] + ">",
                to: "person127@example.com",
                subject: sp[2] + " " + num + " — " + HE_MONTH[d.getMonth()] + " " + d.getFullYear(),
                date: date, labels: labels, hasAttachment: true,
                attachments: [{ filename: sp[3] + "_" + num + att[0], size: att[2], mime: att[1] }],
                snippet: "סכום לתשלום: " + amount + " ₪ · מס׳ מסמך " + num,
                body_text: "מצ\"ב " + sp[2] + " מס' " + num + ".\nסכום לתשלום: " + amount +
                           " ₪ (כולל מע\"מ).\nתנאי תשלום: שוטף+30.\n\nבברכה,\n" + sp[0] };
      } else if (roll < 0.70) {                            // client conversation — with real replies
        var cl = GEN_CLIENTS[Math.floor(rnd() * GEN_CLIENTS.length)];
        var th = GEN_THREADS[Math.floor(rnd() * GEN_THREADS.length)];
        var depth = 1 + Math.floor(rnd() * 4);             // 1–4 messages in the chain
        labels = ["INBOX", "לקוחות"];
        if (rnd() < 0.15) labels.push("דחוף");
        if (rnd() < 0.2) labels.push("מעקב");
        for (var k = 0; k < depth; k++) {
          var kid = k === 0 ? id : id + "_" + k;
          var kd = new Date(d.getTime() + k * 3600000 * (2 + Math.floor(rnd() * 20)));
          var mine = k % 2 === 1;                          // the office answers on odd turns
          out.push({
            id: kid, threadId: id, acct: acct, uidx: 0,
            from: mine ? "בינה · מנהל <person127@example.com>" : cl[2] + " <" + cl[1] + ">",
            to: mine ? cl[1] : "person127@example.com",
            subject: (k ? "Re: " : "") + th[0] + " — " + cl[0],
            date: kd.getFullYear() + "-" + pad2(kd.getMonth() + 1) + "-" + pad2(kd.getDate()) +
                  "T" + pad2(kd.getHours()) + ":" + pad2(kd.getMinutes()) + ":00",
            labels: mine ? ["SENT", "לקוחות"] : labels.slice(),
            hasAttachment: !mine && rnd() < 0.35,
            attachments: !mine && rnd() < 0.35 ? [{ filename: "מסמך_מצורף.pdf", size: 210000, mime: "application/pdf" }] : [],
            snippet: th[1].slice(0, 90),
            body_text: (k ? "בהמשך להתכתבות שלנו,\n\n" : "") + th[1] + "\n\nבברכה,\n" + (mine ? "בינה" : cl[2])
          });
        }
        i += depth - 1;
        continue;
      } else if (roll < 0.80) {                            // internal / system
        labels = ["INBOX"];
        msg = { id: id, threadId: id, acct: acct,
                from: "מערכת בינה <person170@example.com>", to: "person127@example.com",
                subject: "סיכום פעילות יומי — " + d.getDate() + " ב" + HE_MONTH[d.getMonth()],
                date: date, labels: labels, hasAttachment: false,
                snippet: "סונכרנו " + (5 + Math.floor(rnd() * 90)) + " מסמכים, " + Math.floor(rnd() * 4) + " נכשלו.",
                body_text: "דוח פעילות אוטומטי.\nמסמכים שסונכרנו: " + (5 + Math.floor(rnd() * 90)) };
      } else if (roll < 0.90) {                            // newsletters
        var nl = GEN_NEWSLETTER[Math.floor(rnd() * GEN_NEWSLETTER.length)];
        msg = { id: id, threadId: id, acct: acct, from: nl[0] + " <" + nl[1] + ">",
                to: "person127@example.com", subject: nl[2], date: date,
                labels: ["INBOX"], hasAttachment: false,
                snippet: "הרשמה לניוזלטר · ביטול הרשמה בתחתית ההודעה",
                body_html: "<div style='font-family:sans-serif;padding:18px;line-height:1.7'><h3>" +
                           nl[2] + "</h3><p>תוכן הניוזלטר החודשי.</p><p style='color:#888;font-size:12px'>ביטול הרשמה</p></div>" };
      } else if (roll < 0.955) {                           // sent (not part of a thread)
        var cl2 = GEN_CLIENTS[Math.floor(rnd() * GEN_CLIENTS.length)];
        msg = { id: id, threadId: id, acct: acct,
                from: "בינה · מנהל <person127@example.com>", to: cl2[1],
                subject: "העברת מסמכים — " + cl2[0], date: date,
                labels: ["SENT"], hasAttachment: true,
                attachments: [{ filename: "ריכוז_מסמכים.zip", size: 4200000, mime: "application/zip" }],
                snippet: "מצ\"ב ריכוז המסמכים שביקשת.", body_text: "מצ\"ב ריכוז המסמכים שביקשת.\n\nבברכה,\nבינה" };
      } else if (roll < 0.98) {                            // spam
        var sm = GEN_SPAM[Math.floor(rnd() * GEN_SPAM.length)];
        msg = { id: id, threadId: id, acct: acct, from: sm[0] + " <" + sm[1] + ">",
                to: "person127@example.com", subject: sm[2], date: date,
                labels: ["SPAM"], hasAttachment: false, snippet: "הודעה שסווגה כספאם.",
                body_text: sm[2] };
      } else {                                             // deleted
        msg = { id: id, threadId: id, acct: acct, from: "ישן <person171@example.com>",
                to: "person127@example.com", subject: "הודעה שנמחקה — " + d.getFullYear(),
                date: date, labels: ["TRASH"], hasAttachment: false, snippet: "נמחק.",
                body_text: "הודעה שנמחקה." };
      }
      // unread thins out with age, exactly like a mailbox that was actually worked through
      if (msg.labels.indexOf("INBOX") !== -1 && rnd() < (daysAgo < 21 ? 0.42 : daysAgo < 120 ? 0.06 : 0.01))
        msg.labels.push("UNREAD");
      // cross-cutting marks — a real box has a few hundred stars and a lot more "important"
      if (rnd() < 0.035) msg.labels.push("STARRED");
      if (rnd() < 0.09) msg.labels.push("IMPORTANT");
      // a handful of unfinished drafts, which is what every real mailbox has
      if (rnd() < 0.004) { msg.labels = ["DRAFT"]; msg.subject = "טיוטה — " + msg.subject; }
      out.push(msg);
    }
    return out;
  }

  var MESSAGES = [
    {
      id: "m1", threadId: "m1",
      from: "בנק הפועלים <person156@example.com>", to: "person127@example.com",
      subject: "דוח תנועות חודשי מוכן לצפייה",
      date: "2026-07-21T07:15:00",
      labels: ["INBOX", "UNREAD", "כספים"],
      hasAttachment: false,
      snippet: "דוח התנועות החודשי לחשבון העסקי שלך מוכן לצפייה באזור האישי.",
      body_text: "לקוח יקר,\n\nדוח התנועות החודשי לחשבון העסקי (יוני 2026) מוכן לצפייה והורדה באזור האישי באתר הבנק.\n\nיתרה נכון לסוף החודש: 28,340.00 ₪.\n\nבברכה,\nבנק הפועלים"
    },
    {
      id: "m2", threadId: "m2",
      from: "ישראל קרטון בע״מ <person128@example.com>", to: "person127@example.com",
      subject: "חשבונית מס 20458 - אספקת קרטונים לחודש יולי",
      date: "2026-07-21T09:42:00",
      labels: ["INBOX", "UNREAD", "ספקים"],
      hasAttachment: true,
      attachments: [{ filename: "חשבונית_20458.pdf", size: 184320 }],
      snippet: "מצורפת חשבונית מס 20458 בגין אספקת קרטונים לחודש יולי 2026, סך 3,450.00 ₪.",
      body_html: "<div dir=\"rtl\" style=\"font-family:Arial,sans-serif\">מצ\"ב חשבונית מס <b>20458</b> בגין אספקת קרטונים לחודש יולי 2026.<br>סכום לתשלום: <b>3,450.00 ₪</b> (כולל מע\"מ).<br>תנאי תשלום: שוטף+30.<br><br>בברכה,<br>מחלקת הנהלת חשבונות<br>ישראל קרטון בע\"מ</div>"
    },
    {
      id: "m3", threadId: "m3",
      from: "רשות המסים <person172@example.com>", to: "person127@example.com",
      subject: "תזכורת: הגשת דוח מע״מ לחודש יוני 2026",
      date: "2026-07-20T14:05:00",
      labels: ["INBOX", "UNREAD", "דחוף"],
      hasAttachment: false,
      snippet: "תזכורת אוטומטית — מועד הגשת דוח המע\"מ התקופתי חל בעוד 5 ימים.",
      body_text: "לכבוד העוסק,\n\nזוהי תזכורת אוטומטית כי מועד הגשת דוח המע\"מ התקופתי לחודש 06/2026 חל בעוד 5 ימים.\n\nניתן להגיש באמצעות האתר המקוון של רשות המסים.\n\nרשות המסים בישראל — הודעה אוטומטית"
    },
    {
      id: "m4", threadId: "m4",
      from: "ספק הענן בע״מ <person129@example.com>", to: "person127@example.com",
      subject: "קבלה #88213 עבור מנוי ענן - יולי 2026",
      date: "2026-07-20T11:20:00",
      labels: ["INBOX", "ספקים"],
      hasAttachment: true,
      attachments: [{ filename: "קבלה_88213.pdf", size: 92160 }],
      snippet: "קבלה על תשלום חודשי עבור שירותי אחסון ענן — 412.00 ₪.",
      body_html: "<div dir=\"rtl\" style=\"font-family:Arial,sans-serif\">תודה על התשלום! מצ\"ב קבלה מס' 88213 עבור מנוי הענן החודשי (יולי 2026), סך <b>412.00 ₪</b>.<br><br>ספק הענן בע\"מ</div>"
    },
    {
      id: "m5", threadId: "m5",
      from: "חברת חשמל לישראל <person130@example.com>", to: "person127@example.com",
      subject: "חשבון חשמל - מספר לקוח 44521 - תקופה 6",
      date: "2026-07-19T16:48:00",
      labels: ["INBOX", "UNREAD"],
      hasAttachment: true,
      attachments: [{ filename: "חשבון_חשמל_44521.pdf", size: 65536 }],
      snippet: "חשבון חשמל עבור תקופה 6/2026, סך 1,205.60 ₪.",
      body_html: "<div dir=\"rtl\" style=\"font-family:Arial,sans-serif\">חשבון החשמל שלך עבור מספר לקוח 44521, תקופה 6/2026, מצורף.<br>סכום לתשלום: <b>1,205.60 ₪</b>.<br><br>חברת חשמל לישראל בע\"מ</div>"
    },
    {
      id: "m6", threadId: "m6",
      from: "בזק בינלאומי <person131@example.com>", to: "person127@example.com",
      subject: "חשבונית אינטרנט וטלפוניה - יולי 2026",
      date: "2026-07-19T10:03:00",
      labels: ["INBOX", "UNREAD"],
      hasAttachment: true,
      attachments: [{ filename: "חשבונית_בזק_יולי.pdf", size: 71200 }],
      snippet: "חשבונית עבור שירותי אינטרנט וטלפוניה לחודש יולי 2026 — 289.90 ₪.",
      body_text: "לקוח יקר,\n\nמצורפת חשבונית עבור שירותי אינטרנט וטלפוניה לחודש 07/2026.\nסכום לתשלום: 289.90 ₪.\n\nבזק בינלאומי"
    },
    {
      id: "m7", threadId: "m7",
      from: "רו״ח דנה כהן <person173@example.com>", to: "person127@example.com",
      subject: "בקשה למסמכים לצורך הגשת דוח שנתי",
      date: "2026-07-18T13:27:00",
      labels: ["INBOX", "UNREAD"],
      hasAttachment: false,
      snippet: "לצורך הכנת הדוח השנתי אבקש להעביר את יתרות הבנק וכרטסת הספקים לרבעון האחרון.",
      body_text: "שלום רב,\n\nלקראת הגשת הדוח השנתי, אשמח אם תוכלו להעביר בהקדם:\n1. יתרות בנק לסוף רבעון 2\n2. כרטסת ספקים מעודכנת\n3. פירוט הוצאות רכב לשנה החולפת\n\nתודה,\nדנה כהן, רו\"ח"
    },
    {
      id: "m8", threadId: "th-100",
      from: "דואר תעופה בע״מ <person174@example.com>", to: "person127@example.com",
      subject: "בקשה להצעת מחיר - משלוח בינלאומי",
      date: "2026-07-17T09:00:00",
      labels: ["INBOX", "לקוחות"],
      hasAttachment: false,
      snippet: "נבקש הצעת מחיר למשלוח בינלאומי של 3 משטחים לגרמניה.",
      body_text: "שלום,\n\nנבקש הצעת מחיר עבור משלוח בינלאומי של 3 משטחים ליעד גרמניה, משקל כולל כ-450 ק\"ג.\n\nבתודה,\nדואר תעופה בע\"מ"
    },
    {
      id: "m9", threadId: "th-100",
      from: "בינה פתרונות בע״מ <person127@example.com>", to: "person174@example.com",
      subject: "Re: בקשה להצעת מחיר - משלוח בינלאומי",
      date: "2026-07-17T15:30:00",
      labels: ["SENT", "SENT-COPY", "לקוחות"],
      hasAttachment: false,
      snippet: "מצורפת הצעת מחיר עבור המשלוח המבוקש, בתוקף ל-14 יום.",
      body_text: "שלום,\n\nמצורפת הצעת מחיר עבור המשלוח המבוקש (3 משטחים, גרמניה). ההצעה בתוקף ל-14 יום.\n\nבברכה,\nבינה פתרונות בע\"מ"
    },
    {
      id: "m10", threadId: "m10",
      from: "ביטוח לאומי <person175@example.com>", to: "person127@example.com",
      subject: "אישור תשלום דמי ביטוח - יוני 2026",
      date: "2026-07-16T08:45:00",
      labels: ["INBOX"],
      hasAttachment: true,
      attachments: [{ filename: "אישור_ביטוח_לאומי.pdf", size: 45000 }],
      snippet: "אישור על תשלום דמי ביטוח לאומי עבור חודש 06/2026, סך 2,830.00 ₪.",
      body_text: "לכבוד המעסיק,\n\nמצ\"ב אישור תשלום דמי ביטוח לאומי עבור חודש 06/2026, סך 2,830.00 ₪.\n\nהמוסד לביטוח לאומי"
    },
    {
      id: "m11", threadId: "m11",
      from: "בנק הפועלים - עסקים <person176@example.com>", to: "person127@example.com",
      subject: "דוח תנועות חשבון - יוני 2026",
      date: "2026-07-15T18:10:00",
      labels: ["INBOX"],
      hasAttachment: true,
      attachments: [{ filename: "דוח_תנועות_יוני.pdf", size: 210000 }],
      snippet: "דוח תנועות חשבון עסקי לחודש יוני 2026 מוכן להורדה.",
      body_text: "לקוח יקר,\n\nדוח תנועות החשבון העסקי לחודש 06/2026 מצורף לעיונך.\n\nבנק הפועלים בע\"מ"
    },
    {
      id: "m12", threadId: "m12",
      from: "Google Workspace <no-reply@google.com>", to: "person127@example.com",
      subject: "[בדיקה] הודעת בדיקה — נא להתעלם",
      date: "2026-07-15T06:00:00",
      labels: ["INBOX", "UNREAD"],
      hasAttachment: false,
      isTest: true,
      snippet: "זוהי הודעת בדיקה שנשלחה לאימות תיבת הדואר.",
      body_text: "זוהי הודעת בדיקה שנשלחה לאימות הגדרות תיבת הדואר. אין צורך בפעולה."
    },
    {
      id: "m13", threadId: "m13",
      from: "עמית לוי - תמיכה טכנית <person177@example.com>", to: "person127@example.com",
      subject: "עדכון: תקלת שרת דואר תוקנה",
      date: "2026-07-14T12:00:00",
      labels: ["INBOX", "מעקב"],
      hasAttachment: false,
      snippet: "התקלה בשרת הדואר מהבוקר תוקנה, כל ההודעות שהתעכבו סונכרנו.",
      body_text: "שלום,\n\nהתקלה בשרת הדואר שדווחה הבוקר תוקנה. כל ההודעות שהתעכבו סונכרנו בהצלחה.\n\nעמית לוי, תמיכה טכנית"
    },
    {
      id: "m14", threadId: "m14",
      from: "ספק משרדי - דפי הדפסה בע״מ <person178@example.com>", to: "person127@example.com",
      subject: "אישור הזמנה #5521 - ציוד משרדי",
      date: "2026-07-13T10:30:00",
      labels: ["INBOX", "UNREAD", "ספקים"],
      hasAttachment: true,
      attachments: [{ filename: "אישור_הזמנה_5521.pdf", size: 38000 }],
      snippet: "אישור הזמנה מס' 5521 עבור ציוד משרדי, סך 560.00 ₪.",
      body_html: "<div dir=\"rtl\" style=\"font-family:Arial,sans-serif\">הזמנתך מס' 5521 אושרה ותישלח בתוך 3 ימי עסקים.<br>סכום ההזמנה: <b>560.00 ₪</b>.<br><br>דפי הדפסה בע\"מ</div>"
    }
  ];

  // Single-source the 4 supplier-invoice messages from the business spine (same documents INDOX
  // processes and notifications alerts about). Falls back to the literals above if the spine is absent.
  if (window.__biz) {
    [["m2", "karton_20458"], ["m4", "cloud_88213"], ["m5", "iec_44521"], ["m6", "bezeq_jul"]].forEach(function (p) {
      var m = bizMsg(p[1], p[0]);
      if (!m) return;
      for (var i = 0; i < MESSAGES.length; i++) { if (MESSAGES[i].id === p[0]) { MESSAGES[i] = m; break; } }
    });
  }

  // Mail for the OTHER connected instances (so switching accounts shows a different mailbox). The
  // legacy messages above are the Gmail-office box; these belong to Outlook (admin) and the local box.
  MESSAGES.push(
    { id: "ol1", threadId: "ol1", acct: "outlook_admin", from: "Microsoft 365 <person179@example.com>", to: "person133@example.com",
      subject: "סיכום פעילות חשבון — יולי 2026", date: "2026-07-21T08:30:00", labels: ["INBOX", "UNREAD"], hasAttachment: false,
      snippet: "סיכום הפעילות החודשי של חשבון ה-Microsoft 365 שלך מוכן.", body_text: "שלום,\n\nסיכום הפעילות החודשי של חשבון ה-Microsoft 365 שלך מוכן לצפייה.\n\nMicrosoft 365" },
    { id: "ol2", threadId: "ol2", acct: "outlook_admin", from: "לשכת עורכי הדין <person180@example.com>", to: "person133@example.com",
      subject: "עדכון רגולציה — חתימה דיגיטלית", date: "2026-07-20T12:10:00", labels: ["INBOX"], hasAttachment: true,
      attachments: [{ filename: "עדכון_רגולציה.pdf", size: 128000 }], snippet: "עדכון בנוגע לדרישות חתימה דיגיטלית למסמכים עסקיים.", body_text: "לקוח יקר,\n\nמצורף עדכון רגולציה בנוגע לחתימה דיגיטלית.\n\nבברכה" },
    { id: "ol3", threadId: "ol3", acct: "outlook_admin", from: "Teams <person181@example.com>", to: "person133@example.com",
      subject: "פספסת שיחה מצוות הכספים", date: "2026-07-19T15:40:00", labels: ["INBOX", "UNREAD"], hasAttachment: false,
      snippet: "פספסת שיחה מצוות הכספים ב-Teams.", body_text: "פספסת שיחה מצוות הכספים ב-Microsoft Teams." },
    { id: "lo1", threadId: "lo1", acct: "local", from: "גיבוי מקומי <backup@localhost>", to: "מקומי",
      subject: "גיבוי תיבת דואר הושלם", date: "2026-07-21T03:00:00", labels: ["INBOX"], hasAttachment: false,
      snippet: "גיבוי מקומי של תיבת הדואר הושלם בהצלחה.", body_text: "גיבוי מקומי של תיבת הדואר הושלם בהצלחה ב-03:00." },
    { id: "lo2", threadId: "lo2", acct: "local", from: "טיוטות <drafts@localhost>", to: "מקומי",
      subject: "טיוטה שמורה — מכתב ללקוח", date: "2026-07-18T20:15:00", labels: ["INBOX", "DRAFT"], hasAttachment: false,
      snippet: "טיוטה מקומית שמורה — מכתב ללקוח.", body_text: "טיוטה מקומית: מכתב ללקוח (טרם נשלח)." }
  );

  /* The hero set stays FIRST in insertion order and newest by date, so every curated case is still
     what the UI map lands on; the ten-year corpus fills in behind it. */
  MESSAGES = MESSAGES.concat(genCorpus());

  /* ── doc-context: what the document system knows of a message, shown in the reader. The rows are the
        document system's own (its STATUS and TYPE are its enums, DOC_ID the document's number). ── */
  var DOC_CONTEXT = {
    m2: { found: 1, docs: [{ STATUS: "IN_PROGRESS", NAME: "חשבונית 20458", TYPE: "INVOICE", COMPANY_NAME: "ישראל קרטון בע\"מ", DOC_TOTAL_AMOUNT: "3,450.00", DOC_ID:"20458", LINK: "https://drive.google.com/drive/folders/bina-invoices-20458" }] },
    m4: { found: 1, docs: [{ STATUS: "COMPLETED", NAME: "קבלה 88213", TYPE: "RECEIPT", COMPANY_NAME: "ספק הענן בע\"מ", DOC_TOTAL_AMOUNT: "412.00", DOC_ID:"88213", LINK: "https://drive.google.com/drive/folders/bina-receipts-88213" }] },
    m5: { found: 1, docs: [{ STATUS: "NEEDS_REVIEW", NAME: "חשבון חשמל 44521", TYPE: "INVOICE", COMPANY_NAME: "חברת חשמל לישראל", DOC_TOTAL_AMOUNT: "1,205.60", DOC_ID:"44521", ERROR: JSON.stringify({ message: "מספר עוסק מורשה לא תואם לרשומה הקיימת במערכת" }) }] },
    // (the document system's OWN statuses and types: this said PROCESSING, PENDING, MISSING and BANK_REPORT — nobody's)
    m6: { found: 1, docs: [{ STATUS: "IN_PROGRESS", NAME: "חשבונית בזק יולי", TYPE: "INVOICE", COMPANY_NAME: "בזק בינלאומי", DOC_TOTAL_AMOUNT: "289.90", DOC_ID:"BZ-77410" }] },
    m10: { found: 1, docs: [{ STATUS: "TO_EXTRACT", NAME: "אישור תשלום ביטוח לאומי", TYPE: "RECEIPT", COMPANY_NAME: "ביטוח לאומי", DOC_TOTAL_AMOUNT: "2,830.00", DOC_ID:"BTL-0626", LINK: "https://drive.google.com/drive/folders/bina-receipts-btl0626" }] },
    m11: { found: 1, docs: [{ STATUS: "COMPLETED", NAME: "דוח תנועות יוני", TYPE: "UNKNOWN", COMPANY_NAME: "בנק הפועלים", DOC_ID:"HAP-0626", LINK: "https://drive.google.com/drive/folders/bina-bank-hap0626" }] },
    m14: { found: 1, docs: [{ STATUS: "MISSING_TYPE", NAME: "אישור הזמנה 5521", TYPE: "", COMPANY_NAME: "ספק משרדי - דפי הדפסה בע\"מ", DOC_TOTAL_AMOUNT: "560.00", DOC_ID:"5521", ERROR: JSON.stringify({ message: "לא זוהה סוג מסמך תואם — נדרש סיווג ידני" }) }] }
  };

  /* ── helpers ── */
  function json(obj, status) {
    return Promise.resolve(new Response(JSON.stringify(obj), { status: status || 200, headers: { "Content-Type": "application/json" } }));
  }
  function qs(u) { var i = u.indexOf("?"); return new URLSearchParams(i >= 0 ? u.slice(i + 1) : ""); }
  function findMsg(id) { for (var i = 0; i < MESSAGES.length; i++) if (MESSAGES[i].id === id) return MESSAGES[i]; return null; }

  /* «דורש טיפול»: the union of the mailbox's failure labels (mailview/app.py FAIL_RE) */
  function isAttention(m) {
    var L = m.labels || [];
    return L.some(function (l) { return /נכשל|לא מזוהה/.test(l); });
  }
  function matchesQuery(m, q) {
    var hay = [m.subject, m.from, m.snippet, m.body_text || "", m.labels.join(" ")].join(" ").toLowerCase();
    var toks = q.trim().split(/\s+/).filter(Boolean);
    return toks.every(function (t) {
      var low = t.toLowerCase();
      if (low.indexOf("label:") === 0) return (m.labels || []).some(function (l) { return l.indexOf(t.slice(6)) !== -1; });
      if (low === "is:unread") return (m.labels || []).indexOf("UNREAD") !== -1;
      return hay.indexOf(low) !== -1;
    });
  }
  /* No counts per view: the mail service reports none (a number computed from the loaded page of a
     10,000-message box is a plausible-looking lie), so the screen's menu shows none and this answers none. */

  function has(m, l) { return (m.labels || []).indexOf(l) !== -1; }

  function toListItem(m) {
    return { id: m.id, threadId: m.threadId, from: m.from, subject: m.subject, date: m.date, labels: m.labels.slice(),
             snippet: m.snippet || "", hasAttachment: !!m.hasAttachment };
  }

  /* The mailbox's own clock: a moment after its newest message. The corpus is dated to one fixed day, so
     that every build shows the same mailbox — and a window cut on the reader's real clock («30 דק׳»,
     «היום») would then be empty for ever. */
  var CLOCK = MESSAGES.reduce(function (t, m) { return Math.max(t, new Date(m.date).getTime() || 0); }, 0) + 10 * 60000;
  function sinceOf(win) {                                 // mailview/app.py `_since_ts`: null = no window
    if (win === "30m") return CLOCK - 30 * 60000;
    if (win === "1h") return CLOCK - 60 * 60000;
    if (win !== "today" && win !== "month") return null;
    var d = new Date(CLOCK); d.setHours(0, 0, 0, 0); if (win === "month") d.setDate(1);
    return d.getTime();
  }

  function bodyOf(opts) { try { return JSON.parse((opts && opts.body) || "{}") || {}; } catch (e) { return {}; } }

  /* ── the rule store and the mailbox's own settings — the planes behind the screen's «חוקי תיוג» and
     «הגדרות תיבה». Returns a response, or null for a path that is not one of theirs. ── */
  function settingsPlane(path, method, opts) {
    var m, b;
    if (/(^|\/)api\/label-map$/.test(path)) return json(organizerSettings());
    if (/(^|\/)api\/organizer\/defaults$/.test(path)) {
      var rollback = function () {                       // options.public_view: what there is to go back to
        return { available: !!ORGANIZER_PREV, saved_at: ORGANIZER_PREV ? ORGANIZER_PREV.saved_at || null : null, rules: ORGANIZER_PREV ? rulesOf(ORGANIZER_PREV).length : 0 };
      };
      if (method !== "PUT") return json({ defaults: ORGANIZER, rollback: rollback() });
      b = bodyOf(opts);
      var confirm = !!b.confirm_processed; delete b.confirm_processed;
      var problems = organizerProblems(b);
      if (problems.length) return json({ error: problems.length + " problem(s) in the rule document", problems: problems }, 400);
      var why = confirm ? "" : processedGuard(b);
      if (why) return json({ error: why, confirm_with: { confirm_processed: true } }, 409);
      var rules = rulesOf(b).map(function (r, i) { return Object.assign({}, r, { row_number: i + 1, enabled: r.enabled !== false }); });
      ORGANIZER_PREV = ORGANIZER;
      ORGANIZER = { mail: { organizer: { mode: "default", rules: rules } }, saved_at: new Date().toISOString() };
      return json({ ok: true, defaults: ORGANIZER, rollback: rollback(), ignored: [] });
    }
    if (/(^|\/)api\/providers$/.test(path)) return json({ providers: SERVICE_PROVIDERS });
    if (/(^|\/)api\/setup\/status$/.test(path)) {
      var addrs = MAILBOXES.map(function (x) { return x.address; });
      var chk = function (id, title, status, detail, observed, fix) {
        return { id: id, title: title, status: status, detail: detail, expected: null, observed: observed || null, record: null, fix: fix || null };
      };
      return json({ domain: MAIL_DOMAIN, fqdn: "mail." + MAIL_DOMAIN, selector: "mail", public_ip: null, public_ip_source: null,
        mode: "local", ready: true, mailboxes: { available: true, count: addrs.length, primary: addrs[0], addresses: addrs },
        checks: [
          chk("mailbox", "תיבת הדואר המקומית", "ok", "השרת המקומי עונה ותיבת הדואר פעילה."),
          chk("mailboxes", "תיבות דואר בדומיין", "ok", (addrs.length === 1 ? "קיימת תיבת דואר אחת." : "קיימות " + addrs.length + " תיבות דואר.") +
              " הוספת תיבה נוספת אינה דורשת שום שינוי ב-DNS — הרשומות של הדומיין כבר מכסות כל כתובת בו.", addrs.join(", ")),
          chk("dkim_key", "מפתח החתימה (DKIM)", "ok", "קיים מפתח חתימה פרטי עבור " + MAIL_DOMAIN + " (מזהה: mail)."),
          chk("public", "דואר ציבורי", "unknown", "ההתקנה משתמשת בדומיין מקומי (" + MAIL_DOMAIN + "), ולכן אינה יכולה לקבל או לשלוח דואר מהאינטרנט. כל השאר עובד: דואר פנימי, חיפוש, תוויות ואוטומציות.", null,
              "כדי לפתוח דואר ציבורי, הגדר MAIL_DOMAIN ו-MAIL_FQDN לדומיין אמיתי ופרסם את הרשומות.") ] });
    }
    // ── the connection catalog ──
    if (/(^|\/)api\/connections\/select$/.test(path) && method === "POST") {
      b = bodyOf(opts);
      if (!b.id) return json({ ok: false, error: "id required" }, 400);
      if (!MAIL_ACCOUNTS.some(function (a) { return a.id === b.id; })) return json({ ok: false, error: "unknown connection id", id: b.id }, 404);
      MAIL_ACTIVE = b.id;
      return json({ ok: true, active: b.id });
    }
    if ((m = path.match(/(^|\/)api\/connections\/([^/]+)\/probe$/))) {
      var pa = MAIL_ACCOUNTS.filter(function (a) { return a.id === decodeURIComponent(m[2]); })[0];
      if (!pa) return json({ ok: false, error: "unknown connection '" + decodeURIComponent(m[2]) + "'" }, 404);
      return json({ ok: true, reason: "", id: pa.id, account_hint: pa.address || pa.identity });
    }
    if ((m = path.match(/(^|\/)api\/connections\/([^/]+)$/)) && method === "DELETE") {
      var cid = decodeURIComponent(m[2]), ca = MAIL_ACCOUNTS.filter(function (a) { return a.id === cid; })[0];
      if (!ca) return json({ ok: false, error: "unknown connection id", id: cid }, 404);
      if (isLocal(ca))                                    // a profile of the local server is removed with its mailbox, never as an account
        return json({ ok: false, id: cid, profile: ca.address.split("@")[0], error: "זהו פרופיל של שרת הדואר המקומי. הסרה נעשית במסך תיבות הדואר (מחיקת התיבה מסירה גם את החיבור); התיבה עצמה נשמרת על הדיסק.",
                      delete_at: "DELETE /mailboxes/" + ca.address }, 409);
      MAIL_ACCOUNTS.splice(MAIL_ACCOUNTS.indexOf(ca), 1);
      if (MAIL_ACTIVE === cid) MAIL_ACTIVE = MAIL_ACCOUNTS[0].id;     // the service clears the pointer; the default it then resolves is the local one
      return json({ ok: true, id: cid });
    }
    if (/(^|\/)api\/connections$/.test(path)) {
      if (method !== "POST") return json({ active: connActive(), connections: MAIL_ACCOUNTS.map(connRow) });
      b = bodyOf(opts);
      if (!b.protocol || !b.label) return json({ ok: false, error: "protocol and label required" }, 400);
      if (["mail_imap_local", "mail_imap_app_password", "mail_gmail_oauth"].indexOf(b.protocol) === -1)
        return json({ ok: false, error: "unsupported protocol", protocol: b.protocol, supported: ["mail_imap_local", "mail_imap_app_password", "mail_gmail_oauth"] }, 400);
      if (b.protocol === "mail_imap_local")
        return json({ ok: false, error: "חשבון של שרת הדואר המקומי נוצר במסך תיבות הדואר, לא כאן — יצירת תיבה יוצרת גם את החיבור שלה.", protocol: b.protocol, create_at: "POST /mailboxes" }, 400);
      var na = addMailAccount(b.protocol, b.label, b.account_hint || (b.secret && b.secret.username) || "");
      return json({ id: na.id, protocol: na.protocol, label: na.label, account_hint: na.identity, status: "ok" }, 201);
    }
    // ── the addresses at the domain ──
    if ((m = path.match(/(^|\/)api\/mailboxes(?:\/(.+))?$/))) {
      if (method === "GET" && !m[2])
        return json({ available: true, domain: MAIL_DOMAIN, primary: MAILBOXES[0].address, mailboxes: MAILBOXES.map(mailboxRow), count: MAILBOXES.length });
      if (!isLocal(activeAcct())) return json({ error: NOT_LOCAL }, 403);
      if (method === "POST") {
        b = bodyOf(opts);
        var local = String(b.local || "").trim().toLowerCase().split("@")[0];
        if (!local) return json({ error: "שם תיבה נדרש" }, 400);
        // (the refusals are mailboxd's own sentences, and a name is held to its pattern: apps/mail/mailboxd/mailboxd.py)
        if (!/^[a-z0-9](?:[a-z0-9._-]{0,61}[a-z0-9])?$/.test(local)) return json({ error: "שם תיבה לא תקין — אותיות לטיניות קטנות, ספרות, נקודה, מקף וקו תחתון; בקצוות אות או ספרה" }, 400);
        if (String(b.password || "").length < 8) return json({ error: "הסיסמה קצרה מדי — לפחות 8 תווים", min: 8 }, 400);
        var addr = local + "@" + MAIL_DOMAIN;
        if (MAILBOXES.some(function (x) { return x.address === addr; })) return json({ error: "התיבה כבר קיימת", address: addr }, 409);
        MAILBOXES.push({ address: addr, primary: false, maildir_exists: false, size_bytes: 0 });
        MAIL_ACCOUNTS.push({ id: "mail_imap_local-" + local, provider: "local", protocol: "mail_imap_local", address: addr, label: local,
                             identity: addr, mode: "local", color: "var(--olive)", status: "ok" });
        return json({ ok: true, profile: local, address: addr, maildir: mailboxRow({ address: addr }).maildir }, 201);
      }
      if (method === "DELETE" && m[2]) {
        var da = decodeURIComponent(m[2]).toLowerCase(), box = MAILBOXES.filter(function (x) { return x.address === da; })[0];
        if (!box) return json({ error: "אין תיבה כזאת", address: da }, 404);
        if (box.primary) return json({ error: "התיבה הראשית אינה נמחקת", address: da }, 409);
        MAILBOXES.splice(MAILBOXES.indexOf(box), 1);
        var gone = MAIL_ACCOUNTS.filter(function (a) { return a.address === da; })[0];
        if (gone) { MAIL_ACCOUNTS.splice(MAIL_ACCOUNTS.indexOf(gone), 1); if (MAIL_ACTIVE === gone.id) MAIL_ACTIVE = MAIL_ACCOUNTS[0].id; }
        return json({ ok: true, profile: da.split("@")[0], address: da, maildir: mailboxRow(box).maildir, size_bytes: box.size_bytes || 0 });
      }
    }
    return null;
  }

  /* ── route table ── */
  window.fetch = function (url, opts) {
    var u = String(url);
    var method = String((opts && opts.method) || "GET").toUpperCase();
    var plane = settingsPlane(u.split(/[?#]/)[0], method, opts);
    if (plane) return plane;

    // ── multi-account instance endpoints (consumed by the sim switcher overlay) ──
    if (u.indexOf("api/accounts") !== -1) return json({ accounts: MAIL_ACCOUNTS, active: MAIL_ACTIVE });
    if (u.indexOf("api/account/select") !== -1 && opts && opts.method === "POST") {
      var sb; try { sb = JSON.parse(opts.body || "{}"); } catch (e) { sb = {}; }
      if (sb.id) MAIL_ACTIVE = sb.id;
      return json({ ok: true, active: MAIL_ACTIVE });
    }
    if (u.indexOf("api/account/add") !== -1 && opts && opts.method === "POST") {
      var ab; try { ab = JSON.parse(opts.body || "{}"); } catch (e) { ab = {}; }
      var na = addMailAccount(ab.protocol, ab.label);
      return json({ ok: true, id: na.id });
    }
    if (u.indexOf("api/mail-providers") !== -1) return json({ providers: MAIL_PROVIDERS });
    // compose/send — appends a real message to the active mailbox's SENT (so it persists + is coherent)
    if (u.indexOf("api/send") !== -1 && opts && opts.method === "POST") {
      var sb2; try { sb2 = JSON.parse(opts.body || "{}"); } catch (e) { sb2 = {}; }
      var acc = activeAcct();
      var id = "sent" + Date.now();
      MESSAGES.unshift({ id: id, threadId: id, acct: MAIL_ACTIVE, from: (acc.address || acc.identity || "אני") + " (אני)",
        to: sb2.to || "", subject: sb2.subject || "(ללא נושא)", date: new Date().toISOString().slice(0, 19),
        labels: ["SENT"], hasAttachment: false, snippet: (sb2.body || "").slice(0, 90),
        body_text: sb2.body || "" });
      return json({ ok: true, id: id });
    }
    if (u.indexOf("api/account") !== -1) return json(accountInfo());

    if (u.indexOf("api/labels") !== -1) {
      if (method !== "POST") return json({ labels: LABELS.slice() });
      // the mail app is the one place a tag is made; an existing label answers as existing
      var ln = String(bodyOf(opts).name || "").trim();
      if (!ln) return json({ error: "name required" }, 400);
      if (LABELS.indexOf(ln) === -1) LABELS.push(ln);
      return json({ ok: true, name: ln });
    }

    /* The intent, stated once (mailview/app.py MARK_LABELS): starring, importance and unread are a label
       put on or taken off; archiving is the one that is not an add — it REMOVES INBOX, and un-archiving
       puts it back. */
    if (u.indexOf("api/mark") !== -1 && method === "POST") {
      var mb = bodyOf(opts), ids = mb.ids || (mb.id ? [mb.id] : []), what = String(mb.mark || "").trim().toLowerCase();
      var MARKS = { starred: ["STARRED", null], important: ["IMPORTANT", null], unread: ["UNREAD", null], archived: [null, "INBOX"] };
      var on = mb.on == null ? true : !!mb.on;
      if (!ids.length) return json({ error: "id or ids required" }, 400);
      if (!MARKS[what]) return json({ error: "unknown mark '" + what + "'", known: Object.keys(MARKS).sort() }, 400);
      var put = MARKS[what][0] && on ? MARKS[what][0] : MARKS[what][1] && !on ? MARKS[what][1] : null;
      var take = MARKS[what][0] && !on ? MARKS[what][0] : MARKS[what][1] && on ? MARKS[what][1] : null;
      ids.forEach(function (id) {
        var mm = findMsg(id); if (!mm) return;
        mm.labels = (mm.labels || []).filter(function (l) { return l !== take; });
        if (put && mm.labels.indexOf(put) === -1) mm.labels.push(put);
      });
      return json({ ok: true, count: ids.length, mark: what, on: on });
    }

    if (u.indexOf("api/tag") !== -1 && opts && opts.method === "POST") {
      var body; try { body = JSON.parse(opts.body); } catch (e) { return json({ error: "bad body" }, 400); }
      var m = findMsg(body.id);
      if (!m) return json({ error: "not found" }, 404);
      (body.add || []).forEach(function (l) { if (m.labels.indexOf(l) === -1) m.labels.push(l); });
      if (body.remove && body.remove.length) m.labels = m.labels.filter(function (l) { return body.remove.indexOf(l) === -1; });
      return json({ ok: true });
    }

    // what the document system knows of a message — the reader asks for every one it opens, and most are not documents
    if (u.indexOf("api/doc-context/") !== -1) {
      var did = decodeURIComponent(u.split("api/doc-context/")[1].split(/[?#]/)[0]);
      return json(DOC_CONTEXT[did] || { found: 0, docs: [] });
    }

    if (u.indexOf("api/attachment/") !== -1) {
      /* NOTE: the real UI opens this via <a target="_blank" href="api/attachment/<id>/<i>">,
         i.e. a real browser navigation — not a fetch() call — so this handler is never actually
         reached in the running app. Kept for completeness in case anything calls it via fetch. */
      var rest = u.split("api/attachment/")[1].split(/[?#]/)[0].split("/");
      var mm = findMsg(decodeURIComponent(rest[0]));
      var idx = parseInt(rest[1], 10) || 0;
      var att = mm && mm.attachments && mm.attachments[idx];
      var name = att ? att.filename : "attachment.pdf";
      return Promise.resolve(new Response("%PDF-1.4 (mock attachment content for " + name + ")", {
        status: 200, headers: { "Content-Type": "application/pdf", "Content-Disposition": "inline; filename=\"" + name + "\"" }
      }));
    }

    if (u.indexOf("api/message/") !== -1) {
      var mid = decodeURIComponent(u.split("api/message/")[1].split(/[?#]/)[0]);
      var msg = findMsg(mid);
      if (!msg) return json({ error: "not found" }, 404);
      return json(msg);
    }

    // a conversation is a first-class thing to fetch — the UI should never have to reassemble one
    // from whatever pages of the list happen to be in memory
    var tm = u.match(/api\/thread\/([^/?]+)/);
    if (tm) {
      var tid = decodeURIComponent(tm[1]);
      var chain = MESSAGES.filter(function (m) { return (m.threadId || m.id) === tid; })
                          .sort(function (a, b) { return new Date(a.date) - new Date(b.date); });
      return json({ threadId: tid, messages: chain });
    }

    if (u.indexOf("api/messages") !== -1) {
      var p = qs(u);
      var limit = parseInt(p.get("limit"), 10) || 100;
      var view = p.get("view") || "";
      var label = p.get("label") || "";
      var q = p.get("q") || "";
      var beforeUid = parseInt(p.get("before_uid"), 10) || 0;
      var testParam = p.get("test"); // null = default (hide test mail), "1" = show, "0" = hide

      var pre = MESSAGES.slice().sort(function (a, b) { return new Date(b.date) - new Date(a.date); });
      // scope to the active mail instance (untagged legacy messages belong to the Gmail office box);
      // "all" = unified inbox across every connected account.
      if (MAIL_ACTIVE !== "all") pre = pre.filter(function (m) { return (m.acct || "gmail_office") === MAIL_ACTIVE; });
      if (label) pre = pre.filter(function (m) { return (m.labels || []).indexOf(label) !== -1; });
      if (view === "attention") pre = pre.filter(isAttention);
      /* Server-side system views (mailview/app.py VIEW_QUERIES). At ~10k messages a client-side filter
         over the loaded page is indistinguishable from "this view is empty": SENT is <5% of the box,
         so the first 100 inbox-ordered rows contain almost none of it. The view has to be a query. */
      else if (view === "sent")   pre = pre.filter(function (m) { return has(m, "SENT"); });
      else if (view === "drafts" || view === "draft") pre = pre.filter(function (m) { return has(m, "DRAFT"); });
      else if (view === "spam")   pre = pre.filter(function (m) { return has(m, "SPAM"); });
      else if (view === "trash")  pre = pre.filter(function (m) { return has(m, "TRASH"); });
      else if (view === "starred")   pre = pre.filter(function (m) { return has(m, "STARRED") && !has(m, "TRASH"); });
      else if (view === "important") pre = pre.filter(function (m) { return has(m, "IMPORTANT") && !has(m, "TRASH"); });
      else if (view === "unread")   pre = pre.filter(function (m) { return has(m, "UNREAD") && !has(m, "TRASH") && !has(m, "SPAM"); });
      else if (view === "archived") pre = pre.filter(function (m) { return !has(m, "INBOX") && !has(m, "SENT") && !has(m, "DRAFT") && !has(m, "TRASH") && !has(m, "SPAM"); });
      else if (view === "all")    pre = pre.filter(function (m) { return !has(m, "TRASH") && !has(m, "SPAM"); });
      else if (!label && !q)      // THE INBOX IS A FOLDER, not a filter: what was archived (INBOX taken off) is not in it
        pre = pre.filter(function (m) { return has(m, "INBOX") && !has(m, "SPAM") && !has(m, "TRASH"); });
      if (q) pre = pre.filter(function (m) { return matchesQuery(m, q); });
      // the time window — an absolute instant, ANDed into the same search
      var win = (p.get("win") || "all").toLowerCase(), since = sinceOf(win);
      if (since == null) win = "all"; else pre = pre.filter(function (m) { return new Date(m.date).getTime() >= since; });

      var showTest = testParam === "1";
      var testHiddenMsgs = pre.filter(function (m) { return m.isTest; });
      var visible = showTest ? pre : pre.filter(function (m) { return !m.isTest; });

      var page = visible.slice(beforeUid, beforeUid + limit);
      var hasMore = beforeUid + limit < visible.length;

      return json({
        messages: page.map(toListItem),
        count: page.length,
        total: visible.length,
        has_more: hasMore,
        next_cursor: hasMore ? beforeUid + limit : 0,
        test_total: showTest ? 0 : testHiddenMsgs.length,
        test_hidden: !showTest && testHiddenMsgs.length > 0,
        win: win,
        since_ts: since == null ? null : Math.round(since / 1000)
      });
    }

    return realFetch ? realFetch(url, opts) : Promise.reject(new Error("mock: no route " + u));
  };
})();
