'use strict';
// my-docs SPA — talks to the /api proxy (apitools /documents + /docGen). No OCR.

const $ = (s, r = document) => r.querySelector(s);
const api = (p, opt) => fetch('api' + p, opt);
/* @bina-said:start */
var binaSaid = (status) => (!status ? "אין תשובה מהשירות"
  : status < 300 ? "התשובה אינה מה שהמסך ציפה לו — רענן את הדף"
  : status === 401 ? "הכניסה פגה — רענן את הדף" : status === 403 ? "אין הרשאה לפעולה הזאת"
  : status === 404 ? "השירות לא מכיר את הבקשה הזאת"
  : status > 501 && status < 505 ? "השירות אינו זמין כרגע" : status >= 500 ? "השירות נתקל בשגיאה"
  : "הבקשה נדחתה");
// a request that could not even be sent answers like one that was refused, with status 0
var binaNoAnswer = () => ({ ok: false, status: 0, json: async () => ({}), text: async () => "" });
/* @bina-said:end */
// A READ answers its data — or null when the service did not answer, refused, or sent what is not data. null is
// NOT "there are none". Every list here took a failed request for an empty one (`.json().catch(() => [])`), and a
// business that could not be read for one that was never set up: a service that hiccuped opened «ברוכים הבאים —
// הגדרת העסק» over a working office. What was not read is said once, by the office's notice, with the way to ask
// again; what is on the screen stays as it was.
let UNREAD = null;
const read = async (p) => {
  const r = await api(p).catch(binaNoAnswer);
  const d = r.ok ? await r.json().catch(() => null) : null;
  if (d === null && !(UNREAD && UNREAD.isConnected))
    UNREAD = binaTell('הנתונים לא נטענו', 'bad', { more: binaSaid(r.status), stay: true, act: ['נסה שוב', start] });
  return d;
};

// ── A2 · stroke icons, not characters ──────────────────────────────────────────
// ⬇ ✉ ✓ ⊘ ✕ ▪ ⇕ ▲ ▼ were doing an icon's job as text. A glyph renders in whatever the reader's font
// stack decides, so it lands at a different weight and optical size from everything around it, and
// on a Hebrew-first stack it can fall through to a fallback face entirely — which is why the same
// button read differently on two machines. Same 24×24 stroke set the console uses, inheriting
// currentColor so a button's own colour still governs.
const ICONS = {
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  send:     '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4Z"/>',
  tick:     '<polyline points="20 6 9 17 4 12"/>',
  ban:      '<circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>',
  x:        '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  plus:     '<path d="M5 12h14"/><path d="M12 5v14"/>',
  dot:      '<circle cx="12" cy="12" r="4"/>',
  updown:   '<path d="m7 15 5 5 5-5"/><path d="m7 9 5-5 5 5"/>',
  up:       '<path d="m5 15 7-7 7 7"/>',
  down:     '<path d="m19 9-7 7-7-7"/>',
};
const icon = n => ICONS[n]
  ? `<svg class="ic-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n]}</svg>`
  : '';
const money = n => (n == null ? '' : Number(n).toLocaleString('he-IL', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const TYPE_HE = { INVOICE: 'חשבונית מס', INVOICE_RECEIPT: 'חשבונית מס קבלה', RECEIPT: 'קבלה', QUOTE: 'הצעת מחיר', ORDER: 'הזמנת רכש', SHIPMENT: 'תעודת משלוח', BALANCE_SHEET: 'גיול חובות' };
const STATUS_HE = { draft: 'טיוטה', issued: 'הונפק', sent: 'נשלח', paid: 'שולם', cancelled: 'בוטל' };
const EVENT_HE = { create: 'נוצר', update: 'עודכן', issue: 'הונפק', download: 'הופק עותק', send: 'נשלח', pay: 'סומן כשולם', cancel: 'בוטל', convert: 'הומר ממסמך', converted: 'הומר למסמך', allocation: 'מספר הקצאה', consent: 'הסכמה' };
// which target types a document may be converted into (mirrors backend CONVERSIONS)
const CONVERSIONS = {
  QUOTE: ['ORDER', 'INVOICE', 'INVOICE_RECEIPT'],
  ORDER: ['SHIPMENT', 'INVOICE', 'INVOICE_RECEIPT'],
  SHIPMENT: ['INVOICE', 'INVOICE_RECEIPT'],
  INVOICE: ['RECEIPT'],
};

let BIZ = { onboarded: false, vat_pct: 18 };   // the single business (from /api/business)
let filter = { status: '', view: 'dash' };
let lines = [];
let catalog = [];   // items for line autocomplete
let _saving = false;   // re-entrancy guard: a document create/issue in flight (prevents duplicates)
let _docKey = null;    // per-editor-session idempotency key (stable across retries of the same doc)

const BUSINESS_TYPES = { patur: 'עוסק פטור', murshe: 'עוסק מורשה', company: 'חברה בע"מ' };
const BIZ_FIELDS = [
  ['name', 'שם העסק', 'text', true], ['company_id', 'ח.פ / עוסק מורשה', 'text', true],
  ['business_type', 'סוג עוסק', 'select', false], ['email', 'דוא"ל', 'text', false],
  ['phone', 'טלפון', 'text', false], ['street', 'רחוב ומספר', 'text', false],
  ['city', 'עיר', 'text', false], ['zip', 'מיקוד', 'text', false],
  ['doc_start', 'מספר מסמך הבא', 'number', false],
];

/* @bina-ask:start */
var binaAsk, binaTell;
(function () {
  var doc = document;
  var CSS = ".bask{position:fixed;inset:0;z-index:2147483000;display:grid;grid-template:minmax(0,1fr)/minmax(0,1fr);place-items:center;padding:16px;background:var(--scrim)}"
    + ".bask-card{display:flex;flex-direction:column;width:min(440px,100%);max-height:100%;overflow:auto;box-sizing:border-box;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:var(--shadow-lg);font:14px/1.5 var(--font,system-ui,sans-serif);text-align:start;outline:0}"
    + ".bask-card h2{margin:0 0 8px;font-size:16px;font-weight:800;line-height:1.35}"
    + ".bask-read{overflow:auto}.bask-read:not(:empty){min-height:19px}"   // never squeezed to nothing: a line of it stays, and past that the card itself scrolls
    + ".bask-card p{margin:0 0 6px;font-size:13px;color:var(--muted)}"
    + ".bask-read p:last-child{margin:0}"
    + ".bask-facts{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:10px 0 0;padding:10px 12px;background:var(--surface-2);border:1px solid var(--line);border-radius:9px}"
    + ".bask-facts dt{color:var(--muted);font-size:11px;font-weight:600;line-height:1.7}"
    + ".bask-facts dd{margin:0;font-size:12.5px;font-weight:600;overflow-wrap:anywhere;unicode-bidi:plaintext;text-align:right}"
    + ".bask-field{display:grid;gap:5px;margin-top:10px;font-size:12px;font-weight:600;color:var(--muted)}"
    + ".bask-field input{font:inherit;font-size:13px;font-weight:400;height:36px;padding:0 10px;border:1px solid var(--line);border-radius:9px;background:var(--surface);color:var(--ink)}"
    + ".bask-said{margin-top:10px;padding:8px 12px;border-radius:9px;border-inline-start:4px solid var(--red);background:color-mix(in srgb,var(--red) 14%,var(--surface));font-size:12.5px;overflow-wrap:anywhere}"
    + ".bask-said:empty{display:none}"
    + ".bask-acts{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}"
    + ".bask-btn{height:34px;padding:0 16px;border-radius:9px;border:1px solid var(--line);background:transparent;color:var(--ink);font:inherit;font-size:13px;font-weight:700;cursor:pointer}"
    + ".bask-btn.primary{background:var(--accent);border-color:transparent;color:var(--accent-ink)}"
    + ".bask-btn.danger{background:var(--red);border-color:transparent;color:var(--surface)}"
    + ".bask-btn:disabled{opacity:.5;cursor:default}"
    + ".bask-field input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}"
    + "@media (pointer:coarse){.bask-btn{height:44px}.bask-field input{height:44px}}"
    + "@media (max-height:399px){.bask{padding:8px}.bask-card{padding:12px}.bask-acts{margin-top:10px}}"   // the side menu's own short frame
    + "#bina-tell{position:fixed;inset-block-end:16px;inset-inline-start:16px;z-index:2147483001;display:grid;gap:8px;max-width:min(420px,calc(100vw - 32px))}"
    + ".btell{--c:var(--ok);padding:10px 14px;border-radius:12px;background:color-mix(in srgb,var(--c) 14%,var(--surface));color:var(--ink);border:1px solid color-mix(in srgb,var(--c) 38%,var(--surface));border-inline-start:4px solid var(--c);font:13px/1.45 var(--font,system-ui,sans-serif);box-shadow:var(--shadow-lg);cursor:pointer;text-align:start}"
    + ".btell.warn{--c:var(--lime)}.btell.bad{--c:var(--red)}"   // --ok and --red, not the bare hues: they are the steps that are lifted on the dark ground
    + ".btell small{display:block;margin-top:2px;font-size:11.5px;color:var(--muted);overflow-wrap:anywhere;unicode-bidi:plaintext}"
    + ".btell button{margin-inline-start:12px;padding:0;border:0;background:none;font:inherit;font-weight:800;color:var(--blue);text-decoration:underline;cursor:pointer}";

  function el(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function style() {
    if (doc.getElementById("bina-ask-css")) return;
    var s = el("style", "", CSS);
    s.id = "bina-ask-css";
    doc.head.appendChild(s);
  }

  binaAsk = function (q) {
    style();
    return new Promise(function (resolve) {
      var back = doc.activeElement, field = null, must = q.input && q.input.must;
      var scrim = el("div", "bask"), card = el("div", "bask-card"), read = el("div", "bask-read"), said = el("div", "bask-said");
      card.setAttribute("role", "alertdialog");
      card.setAttribute("aria-modal", "true");
      card.setAttribute("dir", "rtl");
      card.setAttribute("tabindex", "-1");
      said.setAttribute("role", "alert");
      card.appendChild(el("h2", "", q.title));
      card.appendChild(read);
      String(q.body || "").split(/\n+/).forEach(function (line) { if (line.trim()) read.appendChild(el("p", "", line)); });
      if (q.facts && q.facts.length) {
        var dl = el("dl", "bask-facts");
        q.facts.forEach(function (f) { dl.appendChild(el("dt", "", f[0])); dl.appendChild(el("dd", "", f[1])); });
        read.appendChild(dl);
      }
      if (q.input) {
        var lab = el("label", "bask-field", q.input.label || "");
        field = el("input");
        field.value = q.input.value || "";
        if (q.input.dir) field.setAttribute("dir", q.input.dir);
        lab.appendChild(field);
        card.appendChild(lab);
      }
      var acts = el("div", "bask-acts"), no = el("button", "bask-btn", q.cancel || "ביטול"),
          yes = el("button", "bask-btn " + (q.danger ? "danger" : "primary"), q.ok || "אישור");
      no.setAttribute("type", "button");
      yes.setAttribute("type", "button");
      acts.appendChild(no);
      acts.appendChild(yes);
      card.appendChild(said);
      card.appendChild(acts);
      scrim.appendChild(card);
      doc.body.appendChild(scrim);

      function fit() { if (must) yes.disabled = field.value.trim() !== must; }
      function home() { (field || (q.danger ? no : yes)).focus(); }
      function done(v) {
        doc.removeEventListener("keydown", key, true);
        scrim.remove();
        if (back && back.focus) back.focus();
        resolve(v);
      }
      function cancel() { if (!no.disabled) done(field ? null : false); }
      function agree() {
        if (yes.disabled) return;
        var v = field ? field.value : true;
        if (!q.run) return done(v);
        yes.disabled = no.disabled = true;                // in flight: busy, and there is nothing left to cancel
        yes.textContent = "מבצע…";
        said.textContent = "";
        card.focus();
        Promise.resolve(v).then(q.run).then(function () { done(v); }, function (e) {
          yes.textContent = q.ok || "אישור";
          yes.disabled = no.disabled = false;
          fit();
          said.textContent = (e && e.message) || "הפעולה נכשלה";
          home();
        });
      }
      function key(e) {
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancel(); }
        else if (e.key === "Enter" && field && doc.activeElement === field) { e.preventDefault(); agree(); }
        else if (e.key === "Tab") {                       // the page behind is not reachable while asked
          var ring = [field, no, yes].filter(function (n) { return n && !n.disabled; });
          var i = ring.indexOf(doc.activeElement);
          e.preventDefault();
          if (ring.length) ring[(i + (e.shiftKey ? ring.length - 1 : 1)) % ring.length].focus();
        }
        else if (/^(Arrow|Page)(Up|Down)$/.test(e.key) && doc.activeElement !== field && read.scrollHeight > read.clientHeight) {
          e.preventDefault();                               // the focus lives on the buttons, outside what scrolls
          read.scrollTop += (/Up$/.test(e.key) ? -1 : 1) * (/^Page/.test(e.key) ? read.clientHeight : 40);
        }
      }
      yes.addEventListener("click", agree);
      no.addEventListener("click", cancel);
      scrim.addEventListener("mousedown", function (e) { if (e.target === scrim) cancel(); });
      if (field) field.addEventListener("input", fit);
      doc.addEventListener("keydown", key, true);
      fit();
      home();
    });
  };

  // The third word is how long the notice stays (ms) — or what more it carries: { ms, more, act, stay }.
  //   more  the service's own sentence, on a line of its own under the notice's words
  //   act   [label, fn] — one way on from the notice (an undo, a refresh): pressing it runs fn and takes the notice down
  //   stay  no clock: the notice is there until it is pressed
  binaTell = function (text, kind, opt) {
    style();
    var o = opt && typeof opt === "object" ? opt : { ms: opt };
    var box = doc.getElementById("bina-tell");
    if (!box) { box = el("div"); box.id = "bina-tell"; doc.body.appendChild(box); }
    var n = el("div", "btell " + (kind || "ok"), text);
    n.setAttribute("role", kind === "bad" ? "alert" : "status");
    n.setAttribute("dir", "rtl");
    if (o.more) n.appendChild(el("small", "", o.more));
    if (o.act) {
      var go = el("button", "", o.act[0]);
      go.setAttribute("type", "button");
      go.addEventListener("click", function (e) { e.stopPropagation(); n.remove(); o.act[1](); });
      n.appendChild(go);
    }
    n.addEventListener("click", function () { n.remove(); });
    box.appendChild(n);
    if (!o.stay) setTimeout(function () { n.remove(); }, o.ms || (kind === "bad" ? 9000 : 5200));
    return n;
  };
})();
/* @bina-ask:end */
// BANK-STANDARD re-entrancy guard for the OTHER mutating buttons (business settings, entity save,
// document actions): disable the button while its request is in flight so a double-click / slow
// response can't fire the same mutation twice. Always re-enables (and restores its label) in finally.
async function guard(btn, fn, loadingLabel) {
  if (!btn || btn.disabled) return;
  const orig = btn.innerHTML;           // its markup, not its text: a button's label may hold a drawn mark
  btn.disabled = true; btn.classList.add('is-loading');
  if (loadingLabel) btn.textContent = loadingLabel;
  try { return await fn(); }
  catch (e) { binaTell('הפעולה לא הושלמה', 'bad', { more: binaSaid(0) }); }   // no answer has ONE name in the office (it said «שגיאת רשת — נסו שוב»)
  finally { btn.disabled = false; btn.classList.remove('is-loading'); if (loadingLabel) btn.innerHTML = orig; }
}
let _entKey = null;   // per-open idempotency key for entity (customer/item) creation
function today() { const d = new Date(); return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`; }

// ── navigation ──────────────────────────────────────────────
const VIEWS = { dash: 'לוח בקרה', docs: 'מסמכים', customers: 'לקוחות', items: 'פריטים', settings: 'הגדרות עסק' };
function show(view) {
  filter.view = view;
  document.querySelectorAll('.side nav a').forEach(a => a.classList.toggle('active', a.dataset.view === view));
  Object.keys(VIEWS).forEach(v => $('#view-' + v).classList.toggle('hidden', v !== view));
  $('#viewTitle').textContent = VIEWS[view];
  ({ dash: loadDash, docs: loadDocs, customers: loadCustomers, items: loadItems, settings: loadSettings }[view] || loadDash)();
}

// ── onboarding + business settings ──────────────────────────
function bizFieldHTML(f, val) {
  const [k, label, type, req] = f;
  if (type === 'select')
    return `<label>${label}<select name="${k}">${Object.entries(BUSINESS_TYPES).map(([v, t]) => `<option value="${v}" ${val === v ? 'selected' : ''}>${t}</option>`).join('')}</select></label>`;
  const it = type === 'number' ? 'number' : 'text';
  const hint = k === 'doc_start' ? '<small style="display:block;font-size:11px;color:var(--muted);margin-top:3px">להמשך סדרת מספור קיימת (ריק = החל מ־1)</small>' : '';
  return `<label>${label}${req ? ' *' : ''}<input type="${it}" name="${k}" value="${val || ''}"/>${hint}</label>`;
}
async function loadBiz() {
  const biz = await read('/business');
  if (!biz) return null;                 // not read: BIZ stays what it was, and nobody is sent to set a business up
  BIZ = biz;
  $('#bizHint').textContent = BIZ.onboarded ? `${BIZ.name} · ${BUSINESS_TYPES[BIZ.business_type] || ''} · ח.פ ${BIZ.company_id}` : 'הגדירו את פרטי העסק';
  return BIZ;
}
function collectForm(formSel) {
  const o = {};
  $(formSel).querySelectorAll('input,select').forEach(i => o[i.name] = i.value);
  return o;
}
async function saveBiz(o, fromOnboard) {
  if (!o.name || !o.company_id) return binaTell('נא למלא שם וח.פ', 'warn');
  const r = await api('/business', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(o) });
  if (r.status >= 400) return binaTell('שמירת ההגדרות נכשלה', 'bad');
  BIZ = await r.json().catch(() => BIZ);
  binaTell('נשמר');
  if (fromOnboard) { $('#onboard').classList.add('hidden'); }
  await loadBiz();
}
function loadSettings() {
  $('#bizForm').innerHTML = '<div class="row2">' + BIZ_FIELDS.map(f => bizFieldHTML(f, BIZ[f[0]])).join('') + '</div>'
    + '<button type="button" class="primary" id="bizSave">שמירת הגדרות</button>';
  $('#bizSave').onclick = () => guard($('#bizSave'), () => saveBiz(collectForm('#bizForm'), false), 'שומר…');
}
function openOnboarding() {
  $('#onboardForm').innerHTML = '<div class="row2">' + BIZ_FIELDS.map(f => bizFieldHTML(f, BIZ[f[0]])).join('') + '</div>';
  $('#onboard').classList.remove('hidden');
  $('#onboardSave').onclick = () => guard($('#onboardSave'), () => saveBiz(collectForm('#onboardForm'), true), 'שומר…');
}

// ── customers & items — bina-table (platform-standard grid): row click opens
// the editor drawer, per-row ✕ action deletes (with confirm), built-in search.
let custGrid = null, itemGrid = null;
function entityGrid(kind, host, rows, columns) {
  return BinaTable.create(host, {
    tableId: 'my-docs:' + kind,
    rowKey: 'id',
    height: 440,
    columns,
    data: rows,
    searchPlaceholder: kind === 'customers' ? 'חיפוש לקוח…' : 'חיפוש פריט…',
    onRowClick: r => editEntity(kind, r),
    actions: [{
      key: 'del', label: icon('x'), title: 'מחיקה', kind: 'danger',
      onClick: async r => {
        if (!await binaAsk({ title: 'למחוק את הרשומה?', ok: 'מחיקה', danger: true, facts: [['שם', r.name || '—']] })) return;
        // (a removal that failed was silent: the list was read again, and the row stood there with no word why)
        const a = await api('/' + kind + '/' + r.id, { method: 'DELETE' }).catch(binaNoAnswer);
        if (!a.ok) return binaTell('המחיקה נכשלה', 'bad', { more: (await a.json().catch(() => ({}))).message || binaSaid(a.status) });
        (kind === 'customers' ? loadCustomers : loadItems)();
      },
    }],
    emptyText: 'אין רשומות עדיין.',
    noMatchText: 'לא נמצאו רשומות תואמות.',
  });
}
async function loadCustomers() {
  const rows = await read('/customers');
  if (!rows) return;
  const host = $('#custTable'); host.classList.remove('tablewrap');
  const columns = [
    { key: 'name', label: 'שם', width: 220 },
    { key: 'company_id', label: 'ח.פ', width: 140 },
    { key: 'city', label: 'עיר', width: 140 },
    { key: 'email', label: 'דוא"ל', width: 220 },
    { key: 'phone', label: 'טלפון', width: 150 },
  ];
  if (custGrid) custGrid.setData(rows);
  else custGrid = entityGrid('customers', host, rows, columns);
}
async function loadItems() {
  const rows = await read('/items');
  if (!rows) return;
  const host = $('#itemTable'); host.classList.remove('tablewrap');
  const columns = [
    { key: 'name', label: 'שם', width: 260 },
    { key: 'sku', label: 'מק"ט', width: 140 },
    { key: 'unit', label: 'יחידה', width: 120 },
    { key: 'unit_price', label: 'מחיר', width: 130, align: 'end',
      html: v => (v != null && v !== '' ? '<span class="num">₪' + money(v) + '</span>' : ''),
      compare: (a, b) => (Number(a.unit_price) || 0) - (Number(b.unit_price) || 0) },
  ];
  if (itemGrid) itemGrid.setData(rows);
  else itemGrid = entityGrid('items', host, rows, columns);
}
const ENTITY_FIELDS = {
  customers: [['name', 'שם'], ['company_id', 'ח.פ'], ['street', 'רחוב'], ['city', 'עיר'], ['email', 'דוא"ל'], ['phone', 'טלפון']],
  items: [['name', 'שם'], ['sku', 'מק"ט'], ['unit', 'יחידה'], ['unit_price', 'מחיר']],
};
function editEntity(kind, row) {
  row = row || {};
  const fields = ENTITY_FIELDS[kind];
  const html = '<div class="editor-h"><h2>' + (row.id ? 'עריכה' : (kind === 'customers' ? 'לקוח חדש' : 'פריט חדש')) + '</h2><button class="ghost" id="entX">' + icon('x') + '</button></div>'
    + '<div class="editor-b"><div class="row2">' + fields.map(f => `<label>${f[1]}<input name="${f[0]}" value="${row[f[0]] != null ? row[f[0]] : ''}"/></label>`).join('') + '</div></div>'
    + '<div class="editor-f"><button class="primary" id="entSave">שמירה</button></div>';
  $('#editor').innerHTML = html;
  $('#overlay').classList.remove('hidden'); $('#editor').classList.remove('hidden');
  // fresh idempotency key per open editor so a double-click on "save" can't mint two entities
  _entKey = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : 'e' + Date.now() + Math.random().toString(36).slice(2);
  $('#entX').onclick = closeEditor;
  $('#entSave').onclick = () => guard($('#entSave'), async () => {
    const o = {}; $('#editor').querySelectorAll('input').forEach(i => o[i.name] = i.value);
    const path = '/' + kind + (row.id ? '/' + row.id : '');
    const headers = { 'Content-Type': 'application/json' };
    if (!row.id) headers['Idempotency-Key'] = _entKey || '';   // create path — dedupe on the BFF
    const r = await api(path, { method: row.id ? 'PATCH' : 'POST', headers, body: JSON.stringify(o) });
    if (r.status >= 400) return binaTell('השמירה נכשלה', 'bad');
    binaTell('נשמר'); closeEditor(); (kind === 'customers' ? loadCustomers : loadItems)();
  }, 'שומר…');
}

// ── data views ──────────────────────────────────────────────
const MONTHS_HE = ['ינו', 'פבר', 'מרץ', 'אפר', 'מאי', 'יונ', 'יול', 'אוג', 'ספט', 'אוק', 'נוב', 'דצמ'];
async function loadDash() {
  const docs = await read('/documents?limit=500');
  if (!docs) return;
  const num = v => Number(v || 0);
  const live = docs.filter(d => ['issued', 'sent', 'paid'].includes(d.status));
  const ym = d => { const p = (d.doc_date || '').split('/'); return p.length === 3 ? { y: +p[2], m: +p[1] } : null; };
  const now = new Date(), cy = now.getFullYear(), cm = now.getMonth() + 1;
  let net = 0, yearSum = 0, monthSum = 0; const byMonth = {};
  live.forEach(d => {
    const t = num(d.total); net += t; const k = ym(d);
    if (k) { if (k.y === cy) yearSum += t; if (k.y === cy && k.m === cm) monthSum += t;
      const key = k.y + '-' + String(k.m).padStart(2, '0'); byMonth[key] = (byMonth[key] || 0) + t; }
  });
  const posCount = live.filter(d => num(d.total) > 0).length;
  const avg = posCount ? net / posCount : 0;
  const bars = []; for (let i = 11; i >= 0; i--) { const dt = new Date(cy, cm - 1 - i, 1);
    bars.push({ key: dt.getFullYear() + '-' + String(dt.getMonth() + 1).padStart(2, '0'), lbl: MONTHS_HE[dt.getMonth()], v: 0 }); }
  bars.forEach(b => b.v = byMonth[b.key] || 0);
  const maxV = Math.max(1, ...bars.map(b => b.v));
  const kpi = (v, l) => `<div class="kpi"><div class="kv">${v}</div><div class="kl">${l}</div></div>`;
  $('#stats').innerHTML = `
    <div class="dash-top">
      <div class="hero-card">
        <div class="hc-label">סך התקבולים</div>
        <div class="hc-amount"><span class="num">₪${money(net)}</span></div>
        <div class="hc-sub">השנה <b class="num">₪${money(yearSum)}</b> · החודש <b class="num">₪${money(monthSum)}</b></div>
      </div>
      <div class="kpi-strip">
        ${kpi(posCount, 'קבלות')}
        ${kpi('₪' + money(avg), 'קבלה ממוצעת')}
        ${kpi(new Set(live.map(d => d.customer_name)).size, 'לקוחות')}
        ${kpi(docs.length, 'סה״כ מסמכים')}
      </div>
    </div>
    <div class="chart-card">
      <div class="cc-head"><span>תקבולים לפי חודש</span><span class="muted">12 חודשים</span></div>
      <div class="bars">${bars.map(b => `<div class="bar-col"><div class="bar-wrap"><div class="bar" style="height:${Math.round(b.v / maxV * 100)}%" title="₪${money(b.v)}"></div></div><div class="bar-lbl">${b.lbl}</div></div>`).join('')}</div>
    </div>`;
  $('#recent').innerHTML = table(docs.slice(0, 8));
  wireRows($('#recent'));
}

// ── documents view: bina-table (the platform-standard grid) ──────────────
// The documents view is a business LEDGER — sortable/searchable/paginated,
// row→detail drawer, but NOT inline-editable (issued documents are immutable).
// Status chips live INSIDE the grid (quick-filters with live counts) — the full
// set is fetched once and filtered client-side (the ledger is well under the
// grid's 10k client-mode ceiling).
const STATUS_ORDER = { draft: 0, issued: 1, sent: 2, paid: 3, cancelled: 4 };
function heDateSort(s) {   // dd/mm/yyyy -> sortable yyyymmdd number (null when absent)
  if (!s) return null;
  const p = String(s).split('/');
  if (p.length !== 3) return null;
  return Number(p[2]) * 10000 + Number(p[1]) * 100 + Number(p[0]);
}
const DOC_COLUMNS = [
  { key: 'doc_number', label: 'מספר', width: 120,
    html: v => '<span class="num">' + (v || '—') + '</span>',
    compare: (a, b) => (Number(a.doc_number) || 0) - (Number(b.doc_number) || 0) },
  { key: 'doc_type', label: 'סוג', width: 170, format: v => TYPE_HE[v] || v || '' },
  { key: 'customer_name', label: 'לקוח', width: 220 },
  { key: 'total', label: 'סכום', width: 130, align: 'end',
    html: v => (v != null ? '<span class="num">₪' + money(v) + '</span>' : ''),
    compare: (a, b) => (Number(a.total) || 0) - (Number(b.total) || 0) },
  { key: 'doc_date', label: 'תאריך', width: 120,
    compare: (a, b) => (heDateSort(a.doc_date) || 0) - (heDateSort(b.doc_date) || 0) },
  { key: 'status', label: 'סטטוס', width: 110,
    html: v => '<span class="chip ' + v + '">' + (STATUS_HE[v] || v) + '</span>',
    compare: (a, b) => (a.status in STATUS_ORDER ? STATUS_ORDER[a.status] : 99)
                     - (b.status in STATUS_ORDER ? STATUS_ORDER[b.status] : 99) },
];
let docsGrid = null;   // persisted grid instance — keeps sort/search/chip across reloads

async function loadDocs() {
  const docs = await read('/documents?limit=500');
  if (!docs) return;
  $('#filters').innerHTML = '';         // chips render inside the grid now
  const host = $('#docsTable');
  host.classList.remove('tablewrap');   // the grid supplies its own framed container
  if (docsGrid) {
    docsGrid.setData(docs);   // refresh rows, preserve the user's sort/search/chip
    return;
  }
  docsGrid = BinaTable.create(host, {
    tableId: 'my-docs:docs',
    rowKey: 'id',
    columns: DOC_COLUMNS,
    data: docs,
    pageSize: 25,
    height: 620,
    quickFilters: ['draft', 'issued', 'sent', 'paid', 'cancelled'].map(st => ({
      key: st, label: STATUS_HE[st], fn: r => r.status === st,
    })),
    onRowClick: d => openDoc(d.id),
    searchPlaceholder: 'חיפוש לפי מספר, לקוח…',
    emptyText: 'אין מסמכים עדיין — צרו מסמך חדש.',
    noMatchText: 'לא נמצאו מסמכים תואמים.',
  });
}

// table()/wireRows() still power the dashboard's "recent documents" list (#recent).
function table(docs) {
  if (!docs.length) return '<div class="empty">אין מסמכים עדיין — צרו מסמך חדש.</div>';
  return `<table class="data"><thead><tr>
    <th>מספר</th><th>סוג</th><th>לקוח</th><th>סכום</th><th>סטטוס</th></tr></thead><tbody>${
    docs.map(d => `<tr data-id="${d.id}">
      <td class="num">${d.doc_number || '—'}</td>
      <td>${TYPE_HE[d.doc_type] || d.doc_type}</td>
      <td>${d.customer_name || ''}</td>
      <td class="num">${d.total != null ? '₪' + money(d.total) : ''}</td>
      <td><span class="chip ${d.status}">${STATUS_HE[d.status] || d.status}</span></td>
    </tr>`).join('')}</tbody></table>`;
}
function wireRows(root) { root.querySelectorAll('tr[data-id]').forEach(tr => tr.onclick = () => openDoc(tr.dataset.id)); }

// ── editor (create) ─────────────────────────────────────────
let DOC_EDITOR_HTML = '';   // captured at boot so the entity editor can share #editor
async function openEditor() {
  $('#editor').innerHTML = DOC_EDITOR_HTML;   // restore the document editor markup
  // an עוסק פטור is not VAT-registered and may not issue tax documents
  // (חשבונית מס / חשבונית מס קבלה) — offer only the types they may legally produce
  if (BIZ.business_type === 'patur') {
    ['INVOICE', 'INVOICE_RECEIPT'].forEach(v => {
      const o = $('#fType option[value="' + v + '"]'); if (o) o.remove();
    });
    const rc = $('#fType option[value="RECEIPT"]'); if (rc) $('#fType').value = 'RECEIPT';
  }
  wireDocEditor();
  // customer + item pickers (datalists) from the catalog
  const [custs, its] = (await Promise.all([read('/customers'), read('/items')])).map(rows => rows || []);
  catalog = its;
  const cd = document.createElement('datalist'); cd.id = 'custList';
  cd.innerHTML = custs.map(c => `<option value="${c.name}" data-id="${c.id}"></option>`).join('');
  document.body.appendChild(cd);
  window.__custs = custs;
  $('#cName').setAttribute('list', 'custList');
  $('#cName').oninput = () => {
    const c = custs.find(x => x.name === $('#cName').value);
    if (c) { $('#cId').value = c.company_id || ''; $('#cStreet').value = c.street || ''; $('#cCity').value = c.city || ''; }
  };
  lines = [{ description: '', qty: 1, unit_price: 0, sku: '' }];
  // fresh idempotency key for this create session — the server dedupes on it, so a retry
  // (double-click, network re-send, two tabs) can never mint a second document.
  _docKey = (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
            : 'k' + Date.now() + Math.random().toString(36).slice(2);
  ['cName', 'cId', 'cStreet', 'cCity'].forEach(id => { const el = $('#' + id); if (el) el.value = ''; });
  if ($('#fDate')) $('#fDate').value = new Date().toISOString().slice(0, 10);  // default today (editable)
  renderLines();
  $('#overlay').classList.remove('hidden'); $('#editor').classList.remove('hidden');
}
function wireDocEditor() {
  $('#closeEditor').onclick = closeEditor;
  $('#addLine').onclick = () => { lines.push({ description: '', qty: 1, unit_price: 0, sku: '' }); renderLines(); };
  $('#saveDraft').onclick = () => save(false);
  $('#issueNow').onclick = () => save(true);
}
function closeEditor() {
  $('#overlay').classList.add('hidden'); $('#editor').classList.add('hidden');
  const cl = document.getElementById('custList'); if (cl) cl.remove();
}

function renderLines() {
  const catOpts = catalog.map(it => `<option value="${it.name}"></option>`).join('');
  $('#lines').innerHTML = lines.map((l, i) => `<tr>
    <td><input data-i="${i}" data-k="description" list="itemList" value="${l.description}" placeholder="תיאור / בחר פריט"/></td>
    <td style="width:64px"><input data-i="${i}" data-k="qty" type="number" step="1" value="${l.qty}"/></td>
    <td style="width:92px"><input data-i="${i}" data-k="unit_price" type="number" step="0.01" value="${l.unit_price}"/></td>
    <td class="lt">₪${money(l.qty * l.unit_price)}</td>
    <td><button class="x" data-del="${i}">${icon('x')}</button></td></tr>`).join('')
    + `<datalist id="itemList">${catOpts}</datalist>`;
  $('#lines').querySelectorAll('input').forEach(inp => inp.oninput = () => {
    const l = lines[inp.dataset.i];
    if (inp.dataset.k === 'description') {
      l.description = inp.value;
      const it = catalog.find(x => x.name === inp.value);   // autofill price from catalog
      if (it) { l.unit_price = Number(it.unit_price) || 0; l.sku = it.sku || ''; renderLines(); }
    } else { l[inp.dataset.k] = Number(inp.value); }
    renderTotals(); if (inp.dataset.k !== 'description') renderLineTotal(inp);
  });
  $('#lines').querySelectorAll('[data-del]').forEach(b => b.onclick = () => { lines.splice(b.dataset.del, 1); if (!lines.length) lines.push({ description: '', qty: 1, unit_price: 0, sku: '' }); renderLines(); });
  renderTotals();
}
function renderLineTotal(inp) { const tr = inp.closest('tr'); const l = lines[inp.dataset.i]; tr.querySelector('.lt').textContent = '₪' + money(l.qty * l.unit_price); }
function renderTotals() {
  const sub = lines.reduce((s, l) => s + l.qty * l.unit_price, 0);
  const rate = Number(BIZ.vat_pct != null ? BIZ.vat_pct : 18);
  const vat = sub * rate / 100, tot = sub + vat;
  $('#editorTotals').innerHTML = `<div class="tl"><span>סכום ביניים</span><span>₪${money(sub)}</span></div>`
    + (rate ? `<div class="tl"><span>מע״מ ${rate}%</span><span>₪${money(vat)}</span></div>` : '')
    + `<div class="tl grand"><span>סה״כ לתשלום</span><span>₪${money(tot)}</span></div>`;
}

function isoToHe(iso) {   // yyyy-mm-dd -> dd/mm/yyyy
  if (!iso) return today();
  const [y, m, d] = iso.split('-');
  return `${d}/${m}/${y}`;
}
function buildModel() {
  const type = $('#fType').value;
  const rate = Number(BIZ.vat_pct != null ? BIZ.vat_pct : 18);
  const sub = lines.reduce((s, l) => s + l.qty * l.unit_price, 0);
  const pay = ($('#fPay') && $('#fPay').value) || 'מזומן';
  const m = {   // no supplier — backend fills it from business settings
    doc_type: type, doc_date: isoToHe($('#fDate') && $('#fDate').value),
    customer: { name: $('#cName').value, company_id: $('#cId').value, street: $('#cStreet').value, city: $('#cCity').value },
    lines: lines.filter(l => l.description).map(l => ({ description: l.description, qty: l.qty, unit_price: l.unit_price, sku: l.sku || '' })),
  };
  if (type === 'INVOICE' || type === 'INVOICE_RECEIPT') { m.vat_pct = rate; m.style = 'white'; m.issued_at_shipping = true; }
  if (type === 'INVOICE_RECEIPT') { m.payment_method = pay; m.paid_amount = sub * (1 + rate / 100); }
  if (type === 'RECEIPT') {   // receipt = a payment: amount + what-for (from the line) + method
    m.amount = sub * (1 + rate / 100);
    m.nature = (lines.find(l => l.description) || {}).description || '';
    m.payment_method = pay;
    delete m.lines;           // a Receipt records a payment, not line items
  }
  if (type === 'QUOTE') { const d = new Date(Date.now() + 30 * 864e5); m.valid_until = `${String(d.getDate()).padStart(2,'0')}/${String(d.getMonth()+1).padStart(2,'0')}/${d.getFullYear()}`; }
  return m;
}

async function save(issue) {
  if (_saving) return;                       // BANK-STANDARD: never let a second submit fire while
  const model = buildModel();                // one is in flight — that is how duplicate documents happen.
  if (!model.customer.name) return binaTell('נא למלא שם לקוח', 'warn');
  if (model.doc_type === 'RECEIPT') {
    if (!(model.amount > 0 || model.amount < 0)) return binaTell('נא למלא סכום', 'warn');
  } else if (!model.lines || !model.lines.length) {
    return binaTell('נא להוסיף לפחות שורה אחת', 'warn');
  }
  _saving = true;
  const btns = [$('#saveDraft'), $('#issueNow')].filter(Boolean);
  const clicked = issue ? $('#issueNow') : $('#saveDraft');
  const orig = clicked ? clicked.innerHTML : '';
  btns.forEach(b => { b.disabled = true; });
  if (clicked) { clicked.textContent = issue ? 'מנפיק…' : 'שומר…'; clicked.classList.add('is-loading'); }
  try {
    const r = await api('/documents' + (issue ? '?issue=1' : ''), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': _docKey || '' },
      body: JSON.stringify(model),
    });
    const d = await r.json().catch(() => ({}));
    if (r.status >= 400) { binaTell(d.message || 'שגיאה ביצירת המסמך', 'bad'); return; }
    binaTell(issue ? `הונפק ${d.doc_number}` : 'נשמרה טיוטה');
    closeEditor(); show(filter.view); openDoc(d.id);
  } catch (e) {
    // network failure: the document may or may not have been created. The idempotency key means a
    // retry is safe — the server returns the same document rather than creating a duplicate.
    binaTell('לא התקבל אישור לשמירה', 'bad', { more: binaSaid(0) + ' — אפשר לשמור שוב: לא ייווצר כפל מסמכים' });
  } finally {
    _saving = false;
    btns.forEach(b => { b.disabled = false; });
    if (clicked) { clicked.innerHTML = orig; clicked.classList.remove('is-loading'); }
  }
}

// ── document drawer ─────────────────────────────────────────
async function openDoc(id) {
  const d = await read('/documents/' + id);
  if (!d) return;
  $('#dNum').textContent = d.doc_number || TYPE_HE[d.doc_type];
  $('#dStatus').className = 'chip ' + d.status; $('#dStatus').textContent = STATUS_HE[d.status];
  $('#dConv').textContent = d.converted_from ? 'הומר מ־' + d.converted_from : '';
  $('#dPdf').src = 'api/documents/' + id + '/download';
  $('#dActions').innerHTML = actions(d);
  $('#dActions').querySelectorAll('button').forEach(b => b.onclick = () => act(id, b.dataset.act, b));
  const ev = (await read('/documents/' + id + '/events')) || [];
  $('#dEvents').innerHTML = ev.map(e => `<li><b>${EVENT_HE[e.action] || e.action}</b>${e.detail ? ' · ' + e.detail : ''}<div class="t">${(e.ts || '').replace('T', ' ').slice(0, 16)}</div></li>`).join('') || '<li class="muted">—</li>';
  $('#overlay').classList.remove('hidden'); $('#drawer').classList.remove('hidden');
}
function closeDrawer() { $('#overlay').classList.add('hidden'); $('#drawer').classList.add('hidden'); }
function actions(d) {
  const b = [];
  if (d.status === 'draft') b.push(['issue', 'הפק מסמך', 'primary']);
  b.push(['download', icon('download') + ' הורדה', 'ghost']);
  if (['issued', 'sent'].includes(d.status)) b.push(['send', icon('send') + ' שליחה', 'ghost'], ['pay', icon('tick') + ' סמן כשולם', 'ghost']);
  if (d.status !== 'cancelled' && d.status !== 'draft') b.push(['cancel', icon('ban') + ' ביטול', 'ghost']);
  // conversions — offer each valid target type for a non-cancelled document
  if (d.status !== 'cancelled') {
    for (const t of CONVERSIONS[d.doc_type] || []) b.push(['convert:' + t, 'המר ל' + TYPE_HE[t], 'ghost']);
  }
  return b.map(([a, l, c]) => `<button class="${c}" data-act="${a}">${l}</button>`).join('');
}
async function act(id, a, btn) {
  if (a === 'download') { window.open('api/documents/' + id + '/download', '_blank'); return; }
  // guard every state-changing action so a double-click can't issue/send/pay/cancel/convert twice
  return guard(btn, async () => {
    // convert:<TARGET_TYPE> — create a new draft of the target type from this document
    if (a.startsWith('convert:')) {
      const to = a.slice('convert:'.length);
      const r = await api(`/documents/${id}/convert`, {
        // create path: a stable per-(doc,target) key lets the BFF dedupe a double-convert into ONE draft
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': `conv-${id}-${to}` },
        body: JSON.stringify({ to_type: to }),
      });
      const nd = await r.json();
      if (r.status >= 400) return binaTell(nd.message || 'ההמרה נכשלה', 'bad');
      binaTell('נוצרה טיוטת ' + TYPE_HE[to]);
      if (filter.view === 'docs') loadDocs(); else loadDash();
      return openDoc(nd.id);            // jump to the new draft
    }
    let opt = { method: 'POST', headers: { 'Content-Type': 'application/json' } };
    if (a === 'cancel') {
      const reason = await binaAsk({ title: 'לבטל את המסמך?', body: 'תופק חשבונית זיכוי.', ok: 'ביטול המסמך', cancel: 'חזרה',
                                     danger: true, input: { label: 'סיבת הביטול' } });
      if (reason == null) return;
      opt.body = JSON.stringify({ reason });
    }
    if (a === 'send') {       // «ביטול» used to send anyway, to an empty address
      const to = await binaAsk({ title: 'שליחה ללקוח', ok: 'שליחה', input: { label: 'כתובת דוא״ל של הלקוח', dir: 'ltr' } });
      if (to == null) return;
      opt.body = JSON.stringify({ to });
    }
    const r = await api(`/documents/${id}/${a}`, opt);
    const d = await r.json();
    if (r.status >= 400) return binaTell(d.message || 'הפעולה נכשלה', 'bad');
    binaTell({ issue: 'הונפק ' + (d.doc_number || ''), send: 'נשלח ללקוח', pay: 'סומן כשולם', cancel: 'בוטל · הופקה חשבונית זיכוי' }[a] || 'בוצע');
    openDoc(id); if (filter.view === 'docs') loadDocs(); else loadDash();
  });
}

// ── boot ────────────────────────────────────────────────────
DOC_EDITOR_HTML = $('#editor').innerHTML;   // capture before any entity-editor swap
document.querySelectorAll('.side nav a').forEach(a => a.onclick = e => { e.preventDefault(); show(a.dataset.view); });
$('#newBtn').onclick = openEditor;
$('#closeDrawer').onclick = closeDrawer;
$('#overlay').onclick = () => { closeEditor(); closeDrawer(); };
$('#addCust').onclick = () => editEntity('customers');
$('#addItem').onclick = () => editEntity('items');

api('/me').then(r => r.json()).then(u => { $('#userBox').innerHTML = `מחובר/ת<br><b>${u.name}</b>`; }).catch(() => {});

// (a function of its own, not one run in place: the notice's «נסה שוב» starts the screen again)
async function start() {
  const biz = await loadBiz();
  if (biz && !biz.onboarded) { openOnboarding(); }
  show(filter.view || 'dash');
}
start();
