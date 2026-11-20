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
// every type the ledger holds (the house catalogue, DGO-2029: apitools src/doc_gen/house/catalogue.py)
const TYPE_HE = { PROPOSAL: 'הצעה עסקית', QUOTE: 'הצעת מחיר', SERVICE_AGREEMENT: 'הסכם שירות', NDA: 'הסכם סודיות',
  WORK_ORDER: 'הזמנת עבודה', ORDER: 'הזמנה', SHIPMENT: 'תעודת משלוח', PAYMENT_REQUEST: 'חשבון עסקה',
  INVOICE: 'חשבונית מס', INVOICE_RECEIPT: 'חשבונית מס קבלה', RECEIPT: 'קבלה', CREDIT_NOTE: 'חשבונית מס זיכוי',
  STATEMENT: 'כרטסת לקוח', LETTER: 'מכתב', REPORT: 'דוח ללקוח', BALANCE_SHEET: 'גיול חובות' };
// the documents a customer signs to close a deal (mirrors the BFF's SIGNABLE)
const SIGNABLE = new Set(['PROPOSAL', 'QUOTE', 'SERVICE_AGREEMENT', 'NDA', 'WORK_ORDER', 'ORDER']);
// a document of the books — its first download is its «מקור»
const BOOKS = new Set(['INVOICE', 'INVOICE_RECEIPT', 'CREDIT_NOTE', 'RECEIPT', 'SHIPMENT']);
const STATUS_HE = { draft: 'טיוטה', issued: 'הונפק', sent: 'נשלח', paid: 'שולם', cancelled: 'בוטל' };
const EVENT_HE = { create: 'נוצר', update: 'עודכן', issue: 'הונפק', download: 'הופק עותק', send: 'נשלח', pay: 'סומן כשולם', cancel: 'בוטל', convert: 'הומר ממסמך', converted: 'הומר למסמך', allocation: 'מספר הקצאה', consent: 'הסכמה', sign: 'נחתם דיגיטלית', import: 'יובא', 'cancel-undone': 'הביטול לא בוצע' };
// an event's detail as the ledger writes it, in Hebrew: a type's code becomes its name, a signature's level its word
// (the trail read «נוצר · PROPOSAL» and «sign · secured» — an engine's words on the owner's screen)
const SIG_HE = { secured: 'חתימה מאובטחת', certified: 'חתימה מאושרת' };
// …and the system a history was imported from, where the import writes it — «morning · <file>», «… (morning)» —
// and nowhere else: an address or a name holding the word stays as it is (DGO-2042; the trail read «import · morning ·
// 40001.pdf», and a first cut drew «person84@example.com» as «office@מורנינג.co»). The file after it keeps its own
// direction, all of it (U+2068…U+2069): in the Hebrew line «40001.pdf» was drawn «pdf.40001»
const SOURCE_HE = { morning: 'מורנינג' };
const FSI = String.fromCharCode(0x2068), PDI = String.fromCharCode(0x2069);
const evDetail = s => String(s || '').replace(/\b[A-Z][A-Z_]{2,}\b/g, w => TYPE_HE[w] || w)
  .replace(/\b(secured|certified)\b/g, w => SIG_HE[w])
  .replace(/^(morning) · (.+)$/, (m, w, f) => SOURCE_HE[w] + ' · ' + FSI + f + PDI)
  .replace(/\((morning)\)$/, (m, w) => '(' + SOURCE_HE[w] + ')').replace(/^→\s*/, 'ל');
// which target types a document may be converted into (mirrors backend CONVERSIONS)
const CONVERSIONS = {
  PROPOSAL: ['SERVICE_AGREEMENT', 'PAYMENT_REQUEST', 'WORK_ORDER', 'ORDER', 'INVOICE', 'INVOICE_RECEIPT'],
  QUOTE: ['SERVICE_AGREEMENT', 'ORDER', 'WORK_ORDER', 'PAYMENT_REQUEST', 'INVOICE', 'INVOICE_RECEIPT'],
  SERVICE_AGREEMENT: ['PAYMENT_REQUEST', 'WORK_ORDER', 'INVOICE', 'INVOICE_RECEIPT'],
  WORK_ORDER: ['PAYMENT_REQUEST', 'INVOICE', 'INVOICE_RECEIPT'],
  ORDER: ['SHIPMENT', 'PAYMENT_REQUEST', 'INVOICE', 'INVOICE_RECEIPT'],
  SHIPMENT: ['INVOICE', 'INVOICE_RECEIPT'],
  PAYMENT_REQUEST: ['RECEIPT', 'INVOICE', 'INVOICE_RECEIPT'],
  INVOICE: ['RECEIPT'],
};
// the tax documents an עוסק פטור does not issue — never offered to one, as a conversion or a new document
const VAT_ONLY = new Set(['INVOICE', 'INVOICE_RECEIPT', 'CREDIT_NOTE']);
// what the ledger reverses with a credit note when it is cancelled (store.py's _CREDITED); a credit note itself is
// not cancelled — it is the correction
const CREDITED = new Set(['INVOICE', 'INVOICE_RECEIPT']);

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
    + "#bina-tell[data-at~=top]{inset-block-start:16px;inset-block-end:auto}#bina-tell[data-at~=end]{inset-inline-start:auto;inset-inline-end:16px}"   // where it covers nothing (place())
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

  // The notice never sits on a control of the page (DGO-618): it keeps its corner while that covers nothing, and
  // otherwise takes the first corner that does — at every frame size, a desktop window of 380 x 260 included,
  // where the bottom corner is where a window keeps its buttons. With no corner free at its full width, the corners
  // again at two thirds and at half of it (a narrower notice fits over a title, beside a window's ✕); with none
  // free at all, the place that covers fewest.
  var CONTROLS = "button,a[href],input:not([type=hidden]),select,textarea,summary,[role=button],[tabindex]:not([tabindex='-1'])";
  function covered(box) {
    var b = box.getBoundingClientRect(), n = 0;
    if (b.width < 2 || b.height < 2) return 0;
    doc.querySelectorAll(CONTROLS).forEach(function (c) {
      var r = c.getBoundingClientRect();     // the cheap test first: on a screen of thousands of rows most are far away
      if (Math.min(b.right, r.right) - Math.max(b.left, r.left) <= 1 || Math.min(b.bottom, r.bottom) - Math.max(b.top, r.top) <= 1) return;
      // inside the notice, in a part of the page made inert (a window the page put over it), or not drawn: not a control here
      if (box.contains(c) || c.closest("[inert]") || (c.checkVisibility && !c.checkVisibility({ checkVisibilityCSS: true }))) return;
      n++;
    });
    return n;
  }
  function put(box, at, w) {
    if (at) box.setAttribute("data-at", at); else box.removeAttribute("data-at");
    box.style.maxWidth = w;
    // a top spot lets go of the bottom, written on the element: a page's own rule that lifts the notice off its bar
    // (`body:has(…) #bina-tell{inset-block-end:…}`) out-ranks the attribute, and the box stretched to the full height
    box.style.insetBlockEnd = at.indexOf("top") < 0 ? "" : "auto";
  }
  function place(box) {
    var best = null;
    ["", "min(280px,calc((100vw - 32px) * .66))", "min(210px,calc((100vw - 32px) * .5))"].some(function (w) {
      return ["", "end", "top", "top end"].some(function (at) {
        put(box, at, w);
        var n = covered(box);
        if (!best || n < best.n) best = { at: at, w: w, n: n };
        return n === 0;
      });
    });
    put(box, best.at, best.w);
  }
  var placing = 0;
  function replace() { var box = doc.getElementById("bina-tell"); if (box && box.firstChild) place(box); }
  window.addEventListener("resize", function () { clearTimeout(placing); placing = setTimeout(replace, 120); });

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
      go.addEventListener("click", function (e) { e.stopPropagation(); n.remove(); replace(); o.act[1](); });
      n.appendChild(go);
    }
    n.addEventListener("click", function () { n.remove(); replace(); });
    box.appendChild(n);
    place(box);
    if (!o.stay) setTimeout(function () { n.remove(); replace(); }, o.ms || (kind === "bad" ? 9000 : 5200));
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
const VIEWS = { dash: 'לוח בקרה', docs: 'מסמכים', archive: 'ארכיון', customers: 'לקוחות', items: 'פריטים', settings: 'הגדרות עסק' };

/* ── the screen in the address bar (the console's route contract) ────────────────────────────────
   The tail of the console's hash is this app's own URL — `#/m/my-docs/<route>` is
   `/a/my-docs/<route>` — and the shell mirrors whatever this page's URL says, so nothing here talks
   to the console. Two screens are worth an address: a VIEW (`dash` · `docs` · `customers` · `items` ·
   `settings`) and a DOCUMENT (`doc/<id>`, the drawer). "Look at this invoice" is what a person
   sends. See ai/context/build-your-first-app.md § "the address is the state". */
const MOUNT = new URL(document.baseURI).pathname.replace(/\/+$/, "");
const routeOf = () => {
  const p = location.pathname;
  if (!MOUNT) return p === "/" ? "" : p.replace(/^\/+/, "");
  if (p === MOUNT || p === MOUNT + "/") return "";
  return p.startsWith(MOUNT + "/") ? decodeURIComponent(p.slice(MOUNT.length + 1)) : "";
};
const showRoute = (route, replace) => {
  const next = MOUNT + (route ? "/" + route : "/");
  if (location.pathname + location.search !== next) history[replace ? "replaceState" : "pushState"]({}, "", next);
};
/** The one reader: the URL decides the view, and a `doc/<id>` route opens that document's drawer. */
function applyRoute() {
  const route = routeOf();
  if (route.startsWith("doc/")) { openDoc(route.slice(4)); return; }
  if (route === "new" || route.startsWith("new/")) { openEditor(route.slice(4)); return; }
  if (VIEWS[route]) { show(route); return; }
  closeDrawer();
}
window.addEventListener("popstate", applyRoute);

function show(view) {
  filter.view = view;
  document.querySelectorAll('.side nav a').forEach(a => a.classList.toggle('active', a.dataset.view === view));
  Object.keys(VIEWS).forEach(v => $('#view-' + v).classList.toggle('hidden', v !== view));
  $('#viewTitle').textContent = VIEWS[view];
  if (!routeOf().startsWith('doc/')) showRoute(view, true);
  ({ dash: loadDash, docs: loadDocs, archive: loadArchive, customers: loadCustomers, items: loadItems, settings: loadSettings }[view] || loadDash)();
}

// ── «ארכיון»: every document the office has — issued, incoming, its files in «קבצים» — one Hebrew search (DGO-2029) ──
const ARCH_DIR = [['', 'הכל'], ['out', 'שהעסק הנפיק'], ['in', 'שנכנסו'], ['file', 'קבצים']];
const ARCH_FROM = { local: 'מסמכים שלי', indox: 'נכנס', drive: 'קבצים' };
let archDir = '', _archTimer = null, _archSeq = 0;
function loadArchive() {
  $('#archDir').innerHTML = ARCH_DIR.map(([v, l]) => `<button class="${v === archDir ? 'on' : ''}" data-d="${v}">${l}</button>`).join('');
  $('#archDir').querySelectorAll('[data-d]').forEach(b => b.onclick = () => { archDir = b.dataset.d; loadArchive(); });
  $('#archQ').oninput = () => { clearTimeout(_archTimer); _archTimer = setTimeout(runArchive, 300); };
  runArchive();
}
async function runArchive() {
  const seq = ++_archSeq, q = $('#archQ').value.trim();
  const p = new URLSearchParams({ limit: '200' });
  if (q.length >= 2) p.set('q', q);
  if (archDir) p.set('direction', archDir);
  const r = await api('/archive?' + p.toString()).catch(binaNoAnswer);
  if (seq !== _archSeq) return;                         // a newer keystroke already asked
  const j = r.ok ? await r.json().catch(() => null) : null;
  if (!j || !j.data) {
    $('#archTable').innerHTML = `<div class="empty">הארכיון לא נטען — ${binaSaid(r.status)}</div>`;
    $('#archStatus').textContent = '';
    return;
  }
  const rows = j.data.rows || [];
  $('#archStatus').innerHTML = (j.data.status || []).map(s => `<span class="arch-src">${esc(ARCH_FROM[s.provider] || s.provider)} · ${esc(s.said || '')}</span>`).join('');
  if (!rows.length) {
    $('#archTable').innerHTML = `<div class="empty">${q ? 'לא נמצא דבר עבור «' + esc(q) + '»' : 'אין עדיין מסמכים בארכיון'}</div>`;
    return;
  }
  // a file's name keeps its own direction (<bdi>): in the Hebrew cell «40001.pdf» was drawn «pdf.40001», and every
  // name that starts in Latin or a digit the same (DGO-2029, seen on our 559 files)
  $('#archTable').innerHTML = `<table class="data"><thead><tr><th>סוג</th><th>שם או מספר</th><th>לקוח · תיקייה</th><th>תאריך</th><th>מקור</th></tr></thead><tbody>${
    rows.map((d, i) => `<tr data-i="${i}" title="${esc(d.provider === 'drive' ? (d.ref && d.ref.path) || '' : d.id)}">
      <td>${esc(d.type_name || TYPE_HE[d.type] || d.type || '')}</td>
      <td class="${d.provider === 'drive' ? '' : 'num'}"><bdi>${esc(d.number || '—')}</bdi></td>
      <td>${esc(d.party || '')}${d.provider === 'drive' && d.state ? `<div class="muted arch-path">${esc(d.state)}</div>` : ''}</td>
      <td class="num">${esc(/^\d{4}-\d{2}-\d{2}/.test(d.date || '') ? d.date.slice(8, 10) + '/' + d.date.slice(5, 7) + '/' + d.date.slice(0, 4) : (d.date || ''))}</td>
      <td><span class="chip ${d.provider === 'local' ? 'issued' : d.provider === 'drive' ? 'draft' : 'sent'}">${esc(ARCH_FROM[d.provider] || d.provider)}</span></td>
    </tr>`).join('')}</tbody></table>${rows.length >= 200
      ? '<div class="muted arch-more">מוצגות 200 התוצאות האחרונות — חיפוש מצמצם את הרשימה</div>' : ''}`;
  $('#archTable').querySelectorAll('tr[data-i]').forEach(tr => tr.onclick = async () => {
    const d = rows[+tr.dataset.i];
    if (d.provider === 'local' && d.ref && d.ref.id) return openDoc(d.ref.id);
    const where = d.provider === 'drive' ? (d.ref && d.ref.path) || '' : d.id;
    await binaAsk({ title: d.number || d.type_name || 'מסמך', ok: 'העתקת המיקום', cancel: 'סגירה',
                    body: d.provider === 'drive' ? 'הקובץ נמצא ב«קבצים».' : 'המסמך נמצא ב-INDOX, המסמכים הנכנסים.',
                    facts: [['מיקום', where], ['תאריך', d.date || '—']] }) &&
      navigator.clipboard.writeText(where).then(() => binaTell('המיקום הועתק'), () => binaTell('ההעתקה נכשלה', 'warn'));
  });
}

// the view is the address: switching screens writes it, and the shell mirrors it

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
  // income is the documents that ARE income — receipts for an עוסק פטור, tax invoices (less their credits)
  // for a VAT-registered business; a proposal, a quote or a payment request is not money yet (DGO-2029:
  // with the deal documents in the ledger, a sum of every type counted one sale three times)
  const INCOME = BIZ.business_type === 'patur' ? ['RECEIPT'] : ['INVOICE', 'INVOICE_RECEIPT', 'CREDIT_NOTE'];
  // a cancelled tax invoice stays in the sum: the credit note that cancelled it is in it too, and the two make
  // nothing — the credit alone showed a cancelled sale as negative income (DGO-2029, the second reader)
  // …and so does one another document cancelled — a receipt Morning cancelled with a negative one (DGO-2042)
  const credited = d => d.status === 'cancelled' && d.doc_number && (CREDITED.has(d.doc_type) || d.cancelled_by);
  const live = docs.filter(d => INCOME.includes(d.doc_type) && (['issued', 'sent', 'paid'].includes(d.status) || credited(d)));
  const ym = d => { const p = (d.doc_date || '').split('/'); return p.length === 3 ? { y: +p[2], m: +p[1] } : null; };
  const now = new Date(), cy = now.getFullYear(), cm = now.getMonth() + 1;
  let net = 0, yearSum = 0, monthSum = 0; const byMonth = {};
  live.forEach(d => {
    const t = num(d.total) - num(d.vat); net += t; const k = ym(d);   // income is before VAT: the VAT is the state's
    if (k) { if (k.y === cy) yearSum += t; if (k.y === cy && k.m === cm) monthSum += t;
      const key = k.y + '-' + String(k.m).padStart(2, '0'); byMonth[key] = (byMonth[key] || 0) + t; }
  });
  const posCount = live.filter(d => num(d.total) > 0 && d.status !== 'cancelled').length;
  const avg = posCount ? net / posCount : 0;
  const bars = []; for (let i = 11; i >= 0; i--) { const dt = new Date(cy, cm - 1 - i, 1);
    bars.push({ key: dt.getFullYear() + '-' + String(dt.getMonth() + 1).padStart(2, '0'), lbl: MONTHS_HE[dt.getMonth()], v: 0 }); }
  bars.forEach(b => b.v = byMonth[b.key] || 0);
  const maxV = Math.max(1, ...bars.map(b => b.v));
  const kpi = (v, l) => `<div class="kpi"><div class="kv">${v}</div><div class="kl">${l}</div></div>`;
  const patur = BIZ.business_type === 'patur';
  $('#stats').innerHTML = `
    <div class="dash-top">
      <div class="hero-card">
        <div class="hc-label">${patur ? 'סך התקבולים' : 'סך ההכנסות, לפני מע״מ'}</div>
        <div class="hc-amount"><span class="num">₪${money(net)}</span></div>
        <div class="hc-sub">השנה <b class="num">₪${money(yearSum)}</b> · החודש <b class="num">₪${money(monthSum)}</b></div>
      </div>
      <div class="kpi-strip">
        ${kpi(posCount, patur ? 'קבלות' : 'חשבוניות')}
        ${kpi('₪' + money(avg), patur ? 'קבלה ממוצעת' : 'חשבונית ממוצעת')}
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
const DOC_COLUMNS_WIDE = [
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
// A NARROW SCREEN — a phone, a small window. The six columns need ~920px of card and the shared table never shrinks a
// column, so a phone showed only «מספר» and «סוג», the rest behind a sideways scroll (issues/my-docs-documents-list-
// on-a-phone-shows-only-number-and-type.yaml). There each document is a two-line row in two cells: number · type over
// the client; the status over the amount. The six columns stay, hidden, for the search (it matches every declared
// column) and the column picker, under a table id of their own so a small window's choices never reach the wide
// list. Chosen when the list is built: a window that changes its width follows on reload
const NARROW_DOCS = !!(window.matchMedia && matchMedia('(max-width:999px)').matches);   // wide fits from ~982px
const DOC_COLUMNS = NARROW_DOCS ? [
  // two cells of composite content: no column filter (it would look up a field no row has — the second reader: «מכיל»
  // emptied the list), no export (they would export empty), and the density switch is hidden (two lines need 44px)
  { key: '_doc', label: 'מסמך · לקוח', width: 180, filter: false,
    html: (v, d) => '<div class="dlw"><div class="dl"><b class="num">' + esc(d.doc_number || '—') + '</b> · ' +
      esc(TYPE_HE[d.doc_type] || d.doc_type || '') + '</div><div class="dl dl2">' + esc(d.customer_name || '') + '</div></div>',
    compare: (a, b) => (Number(a.doc_number) || 0) - (Number(b.doc_number) || 0) },
  { key: '_sum', label: 'סטטוס · סכום', width: 120, align: 'end', filter: false,
    html: (v, d) => '<div class="dlw"><div class="dl"><span class="chip ' + esc(d.status) + '">' + esc(STATUS_HE[d.status] || d.status) +
      '</span></div><div class="dl dl2"><span class="num">' + (d.total != null ? '₪' + money(d.total) : '') + '</span></div></div>',
    compare: (a, b) => (Number(a.total) || 0) - (Number(b.total) || 0) },
  ...DOC_COLUMNS_WIDE.map(c => Object.assign({}, c, { hidden: true })),
] : DOC_COLUMNS_WIDE;
let docsGrid = null;   // persisted grid instance — keeps sort/search/chip across reloads

async function loadDocs() {
  const docs = await read('/documents?limit=500');
  if (!docs) return;
  $('#filters').innerHTML = '';         // chips render inside the grid now
  const host = $('#docsTable');
  host.classList.remove('tablewrap');   // the grid supplies its own framed container
  host.classList.toggle('docs-narrow', NARROW_DOCS);
  if (docsGrid) {
    docsGrid.setData(docs);   // refresh rows, preserve the user's sort/search/chip
    return;
  }
  docsGrid = BinaTable.create(host, {
    tableId: NARROW_DOCS ? 'my-docs:docs-narrow' : 'my-docs:docs',
    rowKey: 'id',
    columns: DOC_COLUMNS,
    data: docs,
    pageSize: 25,
    height: 620,
    exportable: !NARROW_DOCS,
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
// ── a new document: pick its type, fill its form, and watch the document itself (DGO-2029) ──────────
let DOC_EDITOR_HTML = '';   // captured at boot so the entity editor can share #editor
let DOC_TYPE = '';          // the type being written
let _pvTimer = null, _pvSeq = 0;
// what each type's form shows — the catalogue's flags, as this form needs them
const FORM = {
  PROPOSAL:          { cover: 1, sections: 1, lines: 1, period: 1, valid: 1 },
  QUOTE:             { subject: 1, lines: 1, terms: 1, valid: 1 },
  SERVICE_AGREEMENT: { cover: 1, agreement: 1 },
  NDA:               { agreement: 1 },
  WORK_ORDER:        { subject: 1, lines: 1, terms: 1, valid: 1 },
  ORDER:             { subject: 1, lines: 1, terms: 1, delivery: 1 },
  SHIPMENT:          { lines: 1, noprice: 1, terms: 1, delivery: 1 },
  PAYMENT_REQUEST:   { subject: 1, lines: 1, terms: 1, due: 1 },
  INVOICE:           { lines: 1, terms: 1, due: 1 },
  INVOICE_RECEIPT:   { lines: 1, payments: 1, terms: 1 },
  RECEIPT:           { payments: 1, amount: 1, terms: 1 },
  REPORT:            { cover: 1, sections: 1 },
  LETTER:            { letter: 1 },
};
// the gallery: the documents a person starts, grouped the way a business thinks of them
const GALLERY = [
  ['עסקאות', 'מההצעה ועד החתימה', ['PROPOSAL', 'QUOTE', 'SERVICE_AGREEMENT', 'NDA', 'WORK_ORDER', 'ORDER']],
  ['חשבונות ותשלומים', 'דרישת תשלום, חשבונית וקבלה', ['PAYMENT_REQUEST', 'INVOICE', 'INVOICE_RECEIPT', 'RECEIPT']],
  ['משלוח, דוחות ומכתבים', 'מה שנמסר, מה שנכתב', ['SHIPMENT', 'REPORT', 'LETTER']],
];
let CATALOG = null;         // code -> {he, summary}: the house catalogue, read once
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const mayIssue = code => !(BIZ.business_type === 'patur' && VAT_ONLY.has(code));

async function openEditor(type) {
  $('#editor').innerHTML = DOC_EDITOR_HTML;   // restore the document editor markup
  wireDocEditor();
  if (!CATALOG) {
    const t = await read('/docGen/house/types');
    CATALOG = {};
    ((t && t.types) || []).forEach(r => { CATALOG[r.code] = r; });
  }
  // customer + item pickers (datalists) from the catalog
  const [custs, its] = (await Promise.all([read('/customers'), read('/items')])).map(rows => rows || []);
  catalog = its;
  const cd = document.createElement('datalist'); cd.id = 'custList';
  cd.innerHTML = custs.map(c => `<option value="${esc(c.name)}" data-id="${esc(c.id)}"></option>`).join('');
  document.body.appendChild(cd);
  window.__custs = custs;
  $('#cName').setAttribute('list', 'custList');
  $('#cName').oninput = () => {
    const c = custs.find(x => x.name === $('#cName').value);
    if (c) { $('#cId').value = c.company_id || ''; $('#cStreet').value = c.street || ''; $('#cCity').value = c.city || '';
             $('#cEmail').value = c.email || ''; }
    schedulePreview();
  };
  lines = [{ description: '', qty: 1, unit_price: 0, sku: '' }];
  // fresh idempotency key for this create session — the server dedupes on it, so a retry
  // (double-click, network re-send, two tabs) can never mint a second document.
  _docKey = (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
            : 'k' + Date.now() + Math.random().toString(36).slice(2);
  ['cName', 'cId', 'cStreet', 'cCity', 'cPerson', 'cEmail'].forEach(id => { const el = $('#' + id); if (el) el.value = ''; });
  if ($('#fDate')) $('#fDate').value = new Date().toISOString().slice(0, 10);  // default today (editable)
  $('#overlay').classList.remove('hidden'); $('#editor').classList.remove('hidden');
  if (type && FORM[type] && mayIssue(type)) await pickType(type); else showGallery();
}

/** Step 1 — every document this business issues, as cards in strips (the catalogue's names and words). */
function showGallery() {
  DOC_TYPE = '';
  $('#editor').classList.remove('wide');
  ['#stage', '#editorFoot', '#backToTypes'].forEach(s => $(s).classList.add('hidden'));
  $('#typeGallery').classList.remove('hidden');
  $('#editorTitle').textContent = 'מסמך חדש';
  $('#typeGallery').innerHTML = GALLERY.map(([title, sub, codes]) => {
    const cards = codes.filter(c => FORM[c] && mayIssue(c));
    if (!cards.length) return '';
    const pad = (3 - cards.length % 3) % 3;   // a strip is always whole: never a lone floating card
    return `<section class="tgroup"><div class="tg-h"><h3>${title}</h3><span class="muted">${sub}</span></div>
      <div class="tcards">${cards.map(c => `<button class="tcard" data-type="${c}" title="${esc((CATALOG[c] || {}).summary || '')}">
        <span class="tc-n">${TYPE_HE[c]}</span><span class="tc-s">${esc((CATALOG[c] || {}).summary || '')}</span></button>`).join('')
        }${'<span class="tcard blank" aria-hidden="true"></span>'.repeat(pad)}</div></section>`;
  }).join('') + (BIZ.business_type === 'patur'
    ? '<p class="muted tg-note">חשבונית מס, חשבונית מס קבלה וחשבונית זיכוי — לעוסק מורשה ולחברה. עוסק פטור מוציא חשבון עסקה וקבלה.</p>' : '');
  $('#typeGallery').querySelectorAll('.tcard[data-type]').forEach(b => b.onclick = () => pickType(b.dataset.type));
  showRoute('new');
}

/** Step 2 — the form of one type, beside its document; a narrative type starts from its template. */
async function pickType(code) {
  DOC_TYPE = code;
  $('#fType').value = code;
  const f = FORM[code] || {};
  $('#typeGallery').classList.add('hidden');
  ['#stage', '#editorFoot', '#backToTypes'].forEach(s => $(s).classList.remove('hidden'));
  $('#editor').classList.add('wide');
  $('#editorTitle').textContent = TYPE_HE[code];
  $('#docForm').querySelectorAll('[data-for]').forEach(el => {
    const k = el.dataset.for;
    const on = k === 'price' ? !f.noprice : !!f[k];
    el.classList.toggle('hidden', !on);
  });
  $('#linesLegend').textContent = f.noprice ? 'מה נמסר' : 'שורות';
  const tpl = await read('/docGen/house/template?type=' + code);
  applyTemplate(tpl && tpl.ok ? tpl.document || {} : {});     // no template: the fields are emptied all the same
  renderLines();
  showRoute('new/' + code);
  schedulePreview();
}

/** The type's starting content — a proposal's chapters, an agreement's clauses, a letter's greeting. */
function applyTemplate(t) {
  // every field is set — empty where the new type's template says nothing — so nothing of the type left behind
  // rides along (a quote's «ההצעה בתוקף 30 יום» ended up on an invoice; DGO-2029, the second reader)
  const set = (sel, v) => { const el = $(sel); if (el) el.value = v == null ? '' : (Array.isArray(v) ? v.join('\n') : v); };
  set('#fCoverTitle', (t.cover || {}).title); set('#fCoverSub', (t.cover || {}).subtitle);
  set('#fSubject', t.subject); set('#fIntro', t.intro); set('#fTerms', t.terms); set('#fNotes', t.notes);
  set('#fAgrTitle', t.title); set('#fRecitals', t.recitals); set('#fLtSubject', t.subject); set('#fLtBody', t.body);
  SECTIONS = (t.sections || []).map(s => ({ title: s.title || '', body: s.body || '', pricing: !!s.pricing }));
  CLAUSES = (t.clauses || []).map(c => ({ title: c.title || '', text: c.text || '', items: (c.items || []).join('\n') }));
  if (t.lines && t.lines.length) lines = t.lines.map(l => ({ description: l.description || '', qty: l.qty || 1, unit_price: l.unit_price || 0,
                                                              sku: '', period: l.period || '' }));
  renderSections(); renderClauses();
}

let SECTIONS = [], CLAUSES = [];
function renderSections() {
  const host = $('#sections'); if (!host) return;
  host.innerHTML = SECTIONS.map((s, i) => `<div class="part-ed">
    <div class="pe-h"><input data-s="${i}" data-k="title" value="${esc(s.title)}" placeholder="שם הפרק"/>
      <button class="x" data-sdel="${i}" title="הסרת הפרק">${icon('x')}</button></div>
    ${s.pricing ? '<div class="muted pe-note">כאן יופיעו השורות והסכומים שבטבלת השורות</div>'
               : `<textarea data-s="${i}" data-k="body" rows="4" placeholder="פסקאות · - לנקודה · **מודגש**">${esc(s.body)}</textarea>`}
  </div>`).join('');
  host.querySelectorAll('[data-s]').forEach(el => el.oninput = () => { SECTIONS[el.dataset.s][el.dataset.k] = el.value; schedulePreview(); });
  host.querySelectorAll('[data-sdel]').forEach(b => b.onclick = () => { SECTIONS.splice(+b.dataset.sdel, 1); renderSections(); schedulePreview(); });
}
function renderClauses() {
  const host = $('#clauses'); if (!host) return;
  host.innerHTML = CLAUSES.map((c, i) => `<div class="part-ed">
    <div class="pe-h"><span class="pe-n num">${i + 1}.</span><input data-c="${i}" data-k="title" value="${esc(c.title)}" placeholder="שם הסעיף"/>
      <button class="x" data-cdel="${i}" title="הסרת הסעיף">${icon('x')}</button></div>
    <textarea data-c="${i}" data-k="text" rows="2" placeholder="נוסח הסעיף">${esc(c.text)}</textarea>
    <textarea data-c="${i}" data-k="items" rows="2" placeholder="תתי־סעיפים — שורה לכל אחד">${esc(c.items)}</textarea>
  </div>`).join('');
  host.querySelectorAll('[data-c]').forEach(el => el.oninput = () => { CLAUSES[el.dataset.c][el.dataset.k] = el.value; schedulePreview(); });
  host.querySelectorAll('[data-cdel]').forEach(b => b.onclick = () => { CLAUSES.splice(+b.dataset.cdel, 1); renderClauses(); schedulePreview(); });
}

/** The document beside the form: the house renderer's own HTML, redrawn a moment after the last keystroke. */
function schedulePreview() {
  if (!DOC_TYPE) return;
  clearTimeout(_pvTimer);
  _pvTimer = setTimeout(async () => {
    const seq = ++_pvSeq;
    $('#pvState').textContent = 'מעדכן…';
    const r = await api('/docGen/house?format=html&label=' + encodeURIComponent('טיוטה') + '&fonts=api/docGen/house/fonts/', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(buildModel()),
    }).catch(binaNoAnswer);
    if (seq !== _pvSeq) return;                 // a newer keystroke already asked
    if (!r.ok) { $('#pvState').textContent = 'התצוגה לא עודכנה — ' + binaSaid(r.status); return; }
    const html = await r.text();
    const fr = $('#pvFrame');
    fr.onload = () => fitPreview();
    fr.srcdoc = html;
    $('#pvState').textContent = '';
  }, 420);
}
/** A sheet is 210mm wide; the pane is what it is — the sheet is scaled to it, never scrolled sideways. */
function fitPreview() {
  const fr = $('#pvFrame'), box = $('#pvBox');
  if (!fr || !box || !fr.contentDocument) return;
  const w = 860, s = Math.min(1, (box.clientWidth - 8) / w);
  const h = fr.contentDocument.documentElement.scrollHeight;
  fr.style.width = w + 'px'; fr.style.height = h + 'px';
  fr.style.transform = 'scale(' + s + ')';
  fr.parentElement.style.setProperty('--pv-h', Math.ceil(h * s) + 'px');
}
window.addEventListener('resize', () => { if (DOC_TYPE) fitPreview(); });
function wireDocEditor() {
  $('#closeEditor').onclick = closeEditor;
  $('#backToTypes').onclick = showGallery;
  $('#addLine').onclick = () => { lines.push({ description: '', qty: 1, unit_price: 0, sku: '', period: '' }); renderLines(); };
  $('#addSection').onclick = () => { SECTIONS.push({ title: '', body: '' }); renderSections(); };
  $('#addClause').onclick = () => { CLAUSES.push({ title: '', text: '', items: '' }); renderClauses(); };
  $('#saveDraft').onclick = () => save(false);
  $('#issueNow').onclick = () => save(true);
  // a cheque asks its bank too (a receipt for one is refused without it: §5(b))
  $('#fPay').addEventListener('change', () => $('#fPayBankBox').classList.toggle('hidden', $('#fPay').value !== 'המחאה'));
  // every field of the form redraws the document beside it
  $('#docForm').addEventListener('input', e => { if (!e.target.closest('#lines')) schedulePreview(); });
  $('#docForm').addEventListener('change', () => schedulePreview());
}
function closeEditor() {
  DOC_TYPE = '';
  $('#overlay').classList.add('hidden'); $('#editor').classList.add('hidden'); $('#editor').classList.remove('wide');
  const cl = document.getElementById('custList'); if (cl) cl.remove();
  if (routeOf().startsWith('new')) showRoute(filter.view || 'dash', true);
}

function renderLines() {
  const f = FORM[DOC_TYPE] || {};
  const catOpts = catalog.map(it => `<option value="${esc(it.name)}"></option>`).join('');
  $('#lines').innerHTML = lines.map((l, i) => `<tr>
    <td><input data-i="${i}" data-k="description" list="itemList" value="${esc(l.description)}" placeholder="תיאור / בחר פריט"/></td>
    <td style="width:64px"><input data-i="${i}" data-k="qty" type="number" step="1" value="${esc(l.qty)}"/></td>
    ${f.noprice ? '' : `<td style="width:92px"><input data-i="${i}" data-k="unit_price" type="number" step="0.01" value="${esc(l.unit_price)}"/></td>
    <td class="lt">₪${money(l.qty * l.unit_price)}</td>`}
    ${f.period ? `<td class="per-c"><input type="checkbox" data-i="${i}" data-k="period" ${l.period ? 'checked' : ''} title="שורה שחוזרת כל חודש"/></td>` : ''}
    <td><button class="x" data-del="${i}" title="הסרת השורה">${icon('x')}</button></td></tr>`).join('')
    + `<datalist id="itemList">${catOpts}</datalist>`;
  $('#lines').querySelectorAll('input').forEach(inp => inp.oninput = () => {
    const l = lines[inp.dataset.i];
    if (inp.dataset.k === 'description') {
      l.description = inp.value;
      const it = catalog.find(x => x.name === inp.value);   // autofill price from catalog
      if (it) { l.unit_price = Number(it.unit_price) || 0; l.sku = it.sku || ''; renderLines(); }
    } else if (inp.dataset.k === 'period') { l.period = inp.checked ? 'month' : ''; }
    else { l[inp.dataset.k] = Number(inp.value); }
    renderTotals(); if (!['description', 'period'].includes(inp.dataset.k) && !f.noprice) renderLineTotal(inp);
    schedulePreview();
  });
  $('#lines').querySelectorAll('[data-del]').forEach(b => b.onclick = () => { lines.splice(b.dataset.del, 1); if (!lines.length) lines.push({ description: '', qty: 1, unit_price: 0, sku: '' }); renderLines(); schedulePreview(); });
  renderTotals();
}
function renderLineTotal(inp) { const tr = inp.closest('tr'); const l = lines[inp.dataset.i]; tr.querySelector('.lt').textContent = '₪' + money(l.qty * l.unit_price); }
function renderTotals() {
  // the document beside the form shows the totals as they will be printed; this box says only what is due
  // once (a monthly line is its own total there). A form without prices has no box.
  const f = FORM[DOC_TYPE] || {};
  const box = $('#editorTotals');
  if (!box) return;
  if (!f.lines || f.noprice) { box.classList.add('hidden'); return; }
  box.classList.remove('hidden');
  const once = lines.filter(l => !l.period), monthly = lines.filter(l => l.period);
  const sub = once.reduce((s, l) => s + l.qty * l.unit_price, 0);
  const rate = BIZ.business_type === 'patur' ? 0 : Number(BIZ.vat_pct != null ? BIZ.vat_pct : 18);
  const vat = sub * rate / 100, tot = sub + vat;
  const mon = monthly.reduce((s, l) => s + l.qty * l.unit_price, 0);
  box.innerHTML = (rate ? `<div class="tl"><span>סכום ביניים</span><span class="num">₪${money(sub)}</span></div>`
    + `<div class="tl"><span>מע״מ ${rate}%</span><span class="num">₪${money(vat)}</span></div>` : '')
    + `<div class="tl grand"><span>סה״כ</span><span class="num">₪${money(tot)}</span></div>`
    + (monthly.length ? `<div class="tl"><span>ובכל חודש</span><span class="num">₪${money(mon * (1 + rate / 100))}</span></div>` : '');
}

function isoToHe(iso) {   // yyyy-mm-dd -> dd/mm/yyyy
  if (!iso) return today();
  const [y, m, d] = iso.split('-');
  return `${d}/${m}/${y}`;
}
/** The document as the ledger takes it (and the house renderer draws it): only the fields its type has. */
function buildModel() {
  const type = DOC_TYPE || $('#fType').value;
  const f = FORM[type] || {};
  const rate = Number(BIZ.vat_pct != null ? BIZ.vat_pct : 18);
  const val = sel => (($(sel) && $(sel).value) || '').trim();
  const listOf = sel => val(sel).split('\n').map(s => s.trim()).filter(Boolean);
  const he = sel => (val(sel) ? isoToHe(val(sel)) : '');
  const cust = { name: val('#cName'), company_id: val('#cId'), street: val('#cStreet'), city: val('#cCity'),
                 contact_person: val('#cPerson'), email: val('#cEmail') };
  const m = { doc_type: type, doc_date: isoToHe($('#fDate') && $('#fDate').value), customer: cust };  // the supplier is the business: the ledger fills it
  if (f.valid) m.valid_until = he('#fValid');
  if (f.due) m.payment_due = he('#fDue');
  if (f.delivery) m.delivery_date = he('#fDelivery');
  if (f.lines) m.lines = lines.filter(l => l.description).map(l => {
    const o = { description: l.description, qty: l.qty };
    if (!f.noprice) o.unit_price = l.unit_price;
    if (l.sku) o.sku = l.sku;
    if (f.period && l.period) o.period = 'month';
    return o;
  });
  if (f.subject) { m.subject = val('#fSubject'); m.intro = val('#fIntro'); }
  if (f.terms) { m.terms = listOf('#fTerms'); m.notes = val('#fNotes'); }
  if (f.cover) m.cover = { title: val('#fCoverTitle'), subtitle: val('#fCoverSub') };
  if (f.sections) {
    m.title = val('#fCoverTitle').replace(/\s*\n\s*/g, ' ') || TYPE_HE[type];
    m.sections = SECTIONS.filter(s => s.title || s.body || s.pricing)
      .map(s => s.pricing ? { title: s.title, pricing: true } : { title: s.title, body: s.body });
    m.sign_off = BIZ.signatory ? { name: BIZ.signatory, title: BIZ.signatory_title || BIZ.name } : null;
  }
  if (f.agreement) {
    const nda = type === 'NDA';
    const [a1, a2] = nda ? ['הצד הראשון', 'הצד השני'] : ['הספק', 'הלקוח'];
    const tax = { patur: 'עוסק פטור', murshe: 'עוסק מורשה', company: 'ח.פ.' }[BIZ.business_type] || 'ע.מ.';
    const addr = p => [p.street, p.city].filter(Boolean).join(', ');
    m.title = val('#fAgrTitle') || TYPE_HE[type];
    m.recitals = listOf('#fRecitals');
    m.clauses = CLAUSES.filter(c => c.title || c.text).map(c => ({ title: c.title, text: c.text,
      items: String(c.items || '').split('\n').map(s => s.trim()).filter(Boolean) }));
    m.parties = [
      { label: 'בין:', text: `${BIZ.name || ''}, ${tax} ${BIZ.company_id || ''}${addr(BIZ) ? ', ' + addr(BIZ) : ''} (להלן: **«${a1}»**)` },
      { label: 'לבין:', text: `${cust.name || '…'}${cust.company_id ? ', ח.פ. ' + cust.company_id : ''}${addr(cust) ? ', ' + addr(cust) : ''} (להלן: **«${a2}»**)` },
    ];
    m.signatures = [
      { party: nda ? (BIZ.name || a1) : a1, name: BIZ.signatory || BIZ.name || '', title: BIZ.signatory_title || '' },
      { party: nda ? (cust.name || a2) : a2, name: cust.contact_person || cust.name, title: cust.contact_person ? cust.name : '', stamp: true },
    ];
  }
  if (f.letter) { m.subject = val('#fLtSubject'); m.body = ($('#fLtBody') && $('#fLtBody').value) || ''; }
  const pay = val('#fPay') || 'העברה בנקאית', ref = val('#fPayRef'), chequeBank = val('#fPayBank');
  if (type === 'INVOICE' || type === 'INVOICE_RECEIPT') { m.vat_pct = rate; m.issued_at_shipping = true; }
  if (type === 'INVOICE_RECEIPT') {
    m.payment_method = pay;
    if (pay === 'המחאה') { if (ref) m.cheque_number = ref; if (chequeBank) m.cheque_bank = chequeBank; }
  }
  if (type === 'RECEIPT') {   // a receipt records a payment: how much, by what means, for what
    m.amount = Number(val('#fAmount')) || 0;
    m.nature = val('#fNature');
    m.payment_method = pay;
    if (pay === 'המחאה') { if (ref) m.cheque_number = ref; if (chequeBank) m.cheque_bank = chequeBank; }
  }
  // a delivery note is signed by its sender (§8): the business, in its signatory's name
  if (type === 'SHIPMENT') m.sender_signature = BIZ.signatory || BIZ.name || '';
  return m;
}

async function save(issue) {
  if (_saving) return;                       // BANK-STANDARD: never let a second submit fire while
  const model = buildModel();                // one is in flight — that is how duplicate documents happen.
  const f = FORM[model.doc_type] || {};
  if (!model.customer.name) return binaTell('נא למלא שם לקוח', 'warn');
  if (model.doc_type === 'RECEIPT') {
    if (!(model.amount > 0 || model.amount < 0)) return binaTell('נא למלא סכום', 'warn');
  } else if (f.lines && !f.sections && (!model.lines || !model.lines.length)) {
    return binaTell('נא להוסיף לפחות שורה אחת', 'warn');
  } else if (f.agreement && !(model.clauses || []).length) {
    return binaTell('נא להוסיף לפחות סעיף אחד', 'warn');
  } else if (f.letter && !String(model.body || '').trim()) {
    return binaTell('נא לכתוב את גוף המכתב', 'warn');
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
  // the document itself, as its house HTML — a look is not a download: it uses up no «מקור» (it did, DGO-2029:
  // opening the drawer downloaded the PDF, and an invoice's original was spent on a glance)
  $('#dSign').textContent = ''; $('#dSign').className = 'chip';
  const pv = await api('/documents/' + id + '/preview?fonts=api/docGen/house/fonts/').catch(binaNoAnswer);
  const fr = $('#dPdf');
  fr.onload = () => fitDrawer();
  fr.srcdoc = pv.ok ? await pv.text() : `<p style="font:14px sans-serif;padding:24px" dir="rtl">התצוגה לא נטענה — ${binaSaid(pv.status)}</p>`;
  let env = null;
  if (SIGNABLE.has(d.doc_type) && !['draft', 'cancelled'].includes(d.status)) {
    const s = await read('/sign/' + id);
    // a signed envelope first: a later link that was never used must not hide the signature the deal has
    env = s && s.envelopes && (s.envelopes.find(e => e.status === 'signed') || s.envelopes[0]);
    if (env) {
      const signed = env.status === 'signed';
      $('#dSign').className = 'chip ' + (signed ? 'paid' : 'sent');
      $('#dSign').textContent = signed ? 'נחתם' : env.status === 'opened' ? 'נפתח · ממתין לחתימה' : 'ממתין לחתימה';
      $('#dSign').title = (env.signer_name || '') + (env.signed_at ? ' · ' + env.signed_at.replace('T', ' ').slice(0, 16) : '');
    }
  }
  $('#dActions').innerHTML = actions(d, env);
  $('#dActions').querySelectorAll('button').forEach(b => b.onclick = () => act(id, b.dataset.act, b, d, env));
  const ev = (await read('/documents/' + id + '/events')) || [];
  $('#dEvents').innerHTML = ev.map(e => `<li><b>${EVENT_HE[e.action] || e.action}</b>${e.detail ? ' · ' + esc(evDetail(e.detail)) : ''}<div class="t">${(e.ts || '').replace('T', ' ').slice(0, 16)}</div></li>`).join('') || '<li class="muted">אין עדיין פעולות</li>';
  $('#overlay').classList.remove('hidden'); $('#drawer').classList.remove('hidden');
  fitDrawer();   // the page may have loaded while the drawer was hidden, 0px wide (DGO-2042)
  showRoute('doc/' + encodeURIComponent(id));
}
/** The drawer's sheet, scaled to its pane like the editor's. */
function fitDrawer() {
  const fr = $('#dPdf'), box = $('#dPdfBox');
  if (!fr || !box || !fr.contentDocument) return;
  // the frame can load before openDoc shows the drawer (it awaits two more calls first): a hidden box is 0px wide, and
  // its fit was a negative scale and a 0px page — every drawer blank on the live HP (DGO-2042). Not now: openDoc
  // fits again once the drawer is shown
  if (box.clientWidth <= 8) return;
  const w = 860, s = Math.min(1, (box.clientWidth - 8) / w), h = fr.contentDocument.documentElement.scrollHeight;
  fr.style.width = w + 'px'; fr.style.height = h + 'px'; fr.style.transform = 'scale(' + s + ')';
  box.style.setProperty('--pv-h', Math.ceil(h * s) + 'px');
}
function closeDrawer() { $('#overlay').classList.add('hidden'); $('#drawer').classList.add('hidden'); showRoute(filter.view || 'dash', true); }
function actions(d, env) {
  // one family: the primary act first, the rest ghost, the destructive one last
  const b = [];
  const live = !['draft', 'cancelled'].includes(d.status);
  // a credit note — or one from before it had a type (an INVOICE in series CN) — is the correction itself: it is not
  // cancelled, paid or carried on (DGO-2029, the second reader); store.py's is_credit says the same
  const credit = d.doc_type === 'CREDIT_NOTE' || !!d.cancels
    || (d.doc_type === 'INVOICE' && d.series === 'CN' && Number(d.total) < 0);
  if (d.status === 'draft') b.push(['issue', 'הפק מסמך', 'primary', 'מקבל מספר ונחתם דיגיטלית — לא ניתן לערוך אחרי']);
  if (live && SIGNABLE.has(d.doc_type) && !(env && env.status === 'signed'))
    b.push(['sign', icon('send') + ' שליחה לחתימה', b.length ? 'ghost' : 'primary', 'קישור חתימה אישי ללקוח — החתימה סוגרת את העסקה']);
  if (env && env.status === 'signed') b.push(['signed:' + env.id, icon('download') + ' העותק החתום', 'ghost', 'המסמך, החתימה ותעודת החתימה']);
  b.push(['download', icon('download') + ' PDF', 'ghost',
          BOOKS.has(d.doc_type) && live ? 'ההורדה הראשונה היא ה«מקור»; כל הורדה אחריה — «העתק»' : 'הורדת המסמך']);
  if (live && !SIGNABLE.has(d.doc_type)) b.push(['send', icon('send') + ' סימון כנשלח', 'ghost', 'רושם ביומן שהמסמך נשלח ולמי']);
  if (live && !credit && ['INVOICE', 'PAYMENT_REQUEST', 'INVOICE_RECEIPT'].includes(d.doc_type)) b.push(['pay', icon('tick') + ' סמן כשולם', 'ghost', 'רושם ביומן שהכסף התקבל']);
  // the deal's next step — what this document becomes, in the order the deal goes
  if (live && !credit)              // a draft is issued first: what follows names its number
    for (const t of (CONVERSIONS[d.doc_type] || []).filter(mayIssue)) b.push(['convert:' + t, 'המשך: ' + TYPE_HE[t], 'ghost', 'טיוטה חדשה מהמסמך הזה']);
  if (live && !credit)
    b.push(['cancel', icon('ban') + ' ביטול', 'ghost danger-t', CREDITED.has(d.doc_type) ? 'תופק חשבונית זיכוי' : 'המסמך יסומן כמבוטל — הוא נשמר ואינו נמחק']);
  return b.map(([a, l, c, t]) => `<button class="${c} sm" data-act="${a}" title="${esc(t || '')}">${l}</button>`).join('');
}
async function act(id, a, btn, d, env) {
  if (a === 'download') {
    if (BOOKS.has(d.doc_type) && !['draft', 'cancelled'].includes(d.status)) {
      const go = await binaAsk({ title: 'הורדת המסמך', body: 'ההורדה הראשונה של מסמך חשבונאי היא ה«מקור». כל הורדה אחריה מסומנת «העתק».', ok: 'הורדה' });
      if (!go) return;
    }
    window.open('api/documents/' + id + '/download', '_blank'); return;
  }
  if (a.startsWith('signed:')) { window.open('api/sign/envelope/' + a.slice(7) + '/download', '_blank'); return; }
  if (a === 'sign') return guard(btn, async () => {
    const who = await binaAsk({ title: 'שליחה לחתימה', ok: 'צור קישור',
      body: 'נוצר קישור חתימה אישי ל' + (TYPE_HE[d.doc_type] || 'מסמך') + ' ' + (d.doc_number || '') + '. את הקישור שולחים ללקוח — המערכת אינה שולחת אותו בעצמה.',
      input: { label: 'שם החותם', value: (d.model && d.model.customer && (d.model.customer.contact_person || d.model.customer.name)) || '' } });
    if (who == null || !String(who).trim()) return;
    const r = await api('/sign/' + id, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ signer: String(who).trim(), email: (d.model && d.model.customer && d.model.customer.email) || '' }) }).catch(binaNoAnswer);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) return binaTell(j.message || 'הקישור לא נוצר', 'bad', { more: binaSaid(r.status) });
    const copy = await binaAsk({ title: 'קישור החתימה מוכן', ok: 'העתקת הקישור', cancel: 'סגירה',
      body: 'הקישור פותח את המסמך הזה בלבד, לחותם, למשך 14 יום. החתימה נרשמת ביומן, והעותק החתום נשמר ב«קבצים».',
      facts: [['החותם', String(who).trim()], ['הקישור', j.link]] });
    if (copy) { try { await navigator.clipboard.writeText(j.link); binaTell('הקישור הועתק'); } catch (e) { binaTell('ההעתקה נכשלה — סמנו את הקישור והעתיקו', 'warn'); } }
    openDoc(id); if (filter.view === 'docs') loadDocs(); else loadDash();
  });
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
      const reason = await binaAsk({ title: 'לבטל את המסמך?', ok: 'ביטול המסמך', cancel: 'חזרה', danger: true,
                                     body: CREDITED.has(d.doc_type) ? 'תופק חשבונית זיכוי שמבטלת אותו, עם הפניה אליו ולסיבה.'
                                                                     : 'המסמך יסומן כמבוטל. הוא נשמר עם מספרו ואינו נמחק.',
                                     facts: [['מסמך', (TYPE_HE[d.doc_type] || '') + ' ' + (d.doc_number || '')], ['לקוח', d.customer_name || '—']],
                                     input: { label: 'סיבת הביטול' } });
      if (reason == null) return;
      opt.body = JSON.stringify({ reason });
    }
    if (a === 'send') {       // «ביטול» used to send anyway, to an empty address
      const to = await binaAsk({ title: 'שליחה ללקוח', ok: 'שליחה', input: { label: 'כתובת דוא״ל של הלקוח', dir: 'ltr' } });
      if (to == null) return;
      opt.body = JSON.stringify({ to });
    }
    const r = await api(`/documents/${id}/${a}`, opt).catch(binaNoAnswer);
    const res = await r.json().catch(() => ({}));
    if (r.status >= 400 || !r.ok) return binaTell(res.message || 'הפעולה נכשלה', 'bad', { more: binaSaid(r.status) });
    binaTell({ issue: 'הונפק ' + (res.doc_number || ''), send: 'נרשם כנשלח', pay: 'סומן כשולם',
               cancel: res.credit_document ? 'בוטל · הופקה חשבונית זיכוי ' + (res.credit_document.doc_number || '') : 'המסמך סומן כמבוטל' }[a] || 'בוצע');
    openDoc(id); if (filter.view === 'docs') loadDocs(); else loadDash();
  });
}

// ── boot ────────────────────────────────────────────────────
DOC_EDITOR_HTML = $('#editor').innerHTML;   // capture before any entity-editor swap
document.querySelectorAll('.side nav a').forEach(a => a.onclick = e => { e.preventDefault(); show(a.dataset.view); });
$('#newBtn').onclick = () => openEditor();
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
applyRoute();   // …and then the URL decides (a deep link lands on its view or its document)
start();
