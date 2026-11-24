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
// one verb for issuing, the buttons' own: «הפקה» issues, and what was issued «הופק» (the chip said «הונפק» beside
// a sentence saying «הופקה» — DGO-2169); a download is «הורד», never «הופק עותק», which read as a second issuing
const STATUS_HE = { draft: 'טיוטה', issued: 'הופק', sent: 'נשלח', paid: 'שולם', cancelled: 'בוטל' };
const EVENT_HE = { create: 'נוצר', update: 'עודכן', issue: 'הופק', download: 'הורד עותק', send: 'נשלח', pay: 'סומן כשולם', cancel: 'בוטל', convert: 'הומר ממסמך', converted: 'הומר למסמך', allocation: 'מספר הקצאה', consent: 'הסכמה', sign: 'נחתם דיגיטלית', import: 'יובא', 'cancel-undone': 'הביטול לא בוצע' };
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
function today() { const [y, m, d] = todayIL().split('-'); return `${d}/${m}/${y}`; }   // Israel's day (A.13)

// ── navigation ──────────────────────────────────────────────
const VIEWS = { dash: 'לוח בקרה', docs: 'מסמכים', signatures: 'חתימות', archive: 'ארכיון', customers: 'לקוחות', items: 'פריטים', settings: 'הגדרות עסק' };

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
// BACK, FORWARD AND ✕ AGREE (the code audit, A.10/A.11). An address this page writes on top of another remembers
// which one (`from`), and closing a drawer or the editor goes BACK to it: a replaced address left the same view twice
// in the history, so Back seemed to do nothing, and after a save it reopened an empty editor. The editor is ONE entry
// (the gallery and the form replace each other), so Back leaves it — asking first when something was typed.
const showRoute = (route, replace) => {
  const next = MOUNT + (route ? "/" + route : "/");
  if (location.pathname + location.search === next) return;
  if (replace) { history.replaceState(history.state, "", next); return; }
  history.pushState({ from: routeOf() }, "", next);
  // the history's length WITH this entry, read after the push (a push drops the entries ahead of it first)
  history.replaceState(Object.assign({}, history.state, { len: history.length }), "", next);
};
/** Going back one entry is ours to do: the entry is this page's own, and — in a frame, where the console's windows and
 *  its focus mode share ONE history with it — nothing was added after it (the reader: a ✕ in one window undid another
 *  window's step). Otherwise closing writes the address in place. */
const backIsOurs = from => !!(history.state && history.state.from === from &&
  (window.top === window || history.length === history.state.len));
/** ✕ on what was opened over `view`: back to that view's own entry when it is the one behind, else in place. */
function leaveTo(view) {
  if (backIsOurs(view)) history.back();
  else showRoute(view, true);
}
/** The editor's own address as it stands — null for a customer's or an item's editor, which has none. */
const editorRoute = () => !$('#typeGallery') ? null
  : EDIT_DOC ? 'doc/' + EDIT_DOC.id + '/edit' : DOC_TYPE ? 'new/' + DOC_TYPE : 'new';
/** The one reader: the URL decides the view, and a `doc/<id>` route opens that document's drawer. */
let _askingToLeave = false;
async function applyRoute() {
  let route = routeOf();
  if (!$('#editor').classList.contains('hidden')) {
    if (route === editorRoute()) return;                       // its own address again: nothing to draw
    // a second Back while «לצאת בלי לשמור?» is up waits for that answer: two questions acted each on its own old
    // address, and «חזרה לעריכה» on the older one wrote `/new` with no editor (the reader)
    if (_askingToLeave) return;
    const back = editorRoute();
    _askingToLeave = true;
    let leave;
    try { leave = await mayLeaveEditor(); } finally { _askingToLeave = false; }
    if ($('#editor').classList.contains('hidden')) return;    // closed meanwhile, by its own ✕
    if (!leave) { showRoute(back); return; }                   // it stays, and so does its address
    closeEditor(true);
    route = routeOf();                                         // where the address is NOW, after the question
  }
  // `doc/<id>/edit` is a draft back in its editor (DGO-2047): the link a person keeps to go on writing it
  const edit = /^doc\/(.+)\/edit$/.exec(route);
  if (edit) { editDoc(edit[1]); return; }
  if (route.startsWith("doc/")) { openDoc(route.slice(4)); return; }
  if (route === "new" || route.startsWith("new/")) { openEditor(route.slice(4)); return; }
  closeDrawer(true);
  if (VIEWS[route]) { if (route !== filter.view) show(route); return; }
  showRoute(filter.view || 'dash', true);
}
window.addEventListener("popstate", applyRoute);

function show(view) {
  filter.view = view;
  document.querySelectorAll('.side nav a').forEach(a => a.classList.toggle('active', a.dataset.view === view));
  Object.keys(VIEWS).forEach(v => $('#view-' + v).classList.toggle('hidden', v !== view));
  $('#viewTitle').textContent = VIEWS[view];
  if (!routeOf().startsWith('doc/')) showRoute(view, true);
  ({ dash: loadDash, docs: loadDocs, signatures: loadSignatures, archive: loadArchive, customers: loadCustomers, items: loadItems, settings: loadSettings }[view] || loadDash)();
}

// ── «ארכיון»: every document the office has — issued, incoming, its files in «קבצים» — one Hebrew search (DGO-2029) ──
const ARCH_DIR = [['', 'הכל'], ['out', 'שהעסק הנפיק'], ['in', 'שנכנסו'], ['file', 'קבצים']];
// each source by the name of its tile (DGO-2169: the app is «מסמכים», INDOX's tile «נכנסים», the files' «קבצים»)
const ARCH_FROM = { local: 'מסמכים', indox: 'נכנסים', drive: 'קבצים' };
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
    rows.map((d, i) => `<tr data-i="${i}" tabindex="0" title="${esc(d.provider === 'drive' ? (d.ref && d.ref.path) || '' : d.id)}">
      <td>${esc(d.type_name || TYPE_HE[d.type] || d.type || '')}</td>
      <td class="${d.provider === 'drive' ? '' : 'num'}"><bdi>${esc(d.number || '—')}</bdi></td>
      <td>${esc(d.party || '')}${d.provider === 'drive' && d.state ? `<div class="muted arch-path">${esc(d.state)}</div>` : ''}</td>
      <td class="num">${esc(/^\d{4}-\d{2}-\d{2}/.test(d.date || '') ? d.date.slice(8, 10) + '/' + d.date.slice(5, 7) + '/' + d.date.slice(0, 4) : (d.date || ''))}</td>
      <td><span class="chip ${d.provider === 'local' ? 'issued' : d.provider === 'drive' ? 'draft' : 'sent'}">${esc(ARCH_FROM[d.provider] || d.provider)}</span></td>
    </tr>`).join('')}</tbody></table>${rows.length >= 200
      ? '<div class="muted arch-more">מוצגות 200 התוצאות האחרונות — חיפוש מצמצם את הרשימה</div>' : ''}`;
  $('#archTable').querySelectorAll('tr[data-i]').forEach(tr => tr.onclick = async () => {
    const d = rows[+tr.dataset.i];
    if (d.provider === 'local' && d.ref && d.ref.id) return openFromList(d.ref.id);
    const where = d.provider === 'drive' ? (d.ref && d.ref.path) || '' : d.id;
    await binaAsk({ title: d.number || d.type_name || 'מסמך', ok: 'העתקת המיקום', cancel: 'סגירה',
                    body: d.provider === 'drive' ? 'הקובץ נמצא ב«קבצים».' : 'המסמך נמצא ב«נכנסים» (INDOX).',
                    facts: [['מיקום', where], ['תאריך', d.date || '—']] }) &&
      navigator.clipboard.writeText(where).then(() => binaTell('המיקום הועתק'), () => binaTell('ההעתקה נכשלה', 'warn'));
  });
  // a row takes the keyboard as it takes a click: Tab reaches it, Enter or Space opens it (the audit)
  $('#archTable').onkeydown = e => {
    // (a held key repeats: Enter held on a «קבצים» row opened its card and then pressed «העתקת המיקום» — the reader)
    const tr = (e.key === 'Enter' || e.key === ' ') && !e.repeat && e.target.closest('tr[data-i]');
    if (tr) { e.preventDefault(); tr.click(); }
  };
}

// the view is the address: switching screens writes it, and the shell mirrors it

// ── onboarding + business settings ──────────────────────────
function bizFieldHTML(f, val) {
  const [k, label, type, req] = f;
  if (type === 'select')
    return `<label>${label}<select name="${k}">${Object.entries(BUSINESS_TYPES).map(([v, t]) => `<option value="${v}" ${val === v ? 'selected' : ''}>${t}</option>`).join('')}</select></label>`;
  const it = type === 'number' ? 'number' : 'text';
  const hint = k === 'doc_start' ? '<small style="display:block;font-size:11px;color:var(--muted);margin-top:3px">להמשך סדרת מספור קיימת (ריק = החל מ־1)</small>' : '';
  // escaped: «… בע"מ» was shown as «… בע» and the cut name was saved back (the code audit, A.4)
  return `<label>${label}${req ? ' *' : ''}<input type="${it}" name="${k}" value="${esc(val == null ? '' : val)}"/>${hint}</label>`;
}
async function loadBiz() {
  const biz = await read('/business');
  if (!biz) return null;                 // not read: BIZ stays what it was, and nobody is sent to set a business up
  BIZ = biz;
  // each part only when it is there («ח.פ undefined» stood in the header of a business with no number yet)
  $('#bizHint').textContent = BIZ.onboarded
    ? [BIZ.name, BUSINESS_TYPES[BIZ.business_type], BIZ.company_id ? 'ח.פ ' + BIZ.company_id : ''].filter(Boolean).join(' · ')
    : 'הגדירו את פרטי העסק';
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
    + '<div class="editor-b"><div class="row2">' + fields.map(f => `<label>${f[1]}<input name="${f[0]}" value="${esc(row[f[0]] != null ? row[f[0]] : '')}"/></label>`).join('') + '</div></div>'
    + '<div class="editor-f"><button class="primary" id="entSave">שמירה</button></div>';
  $('#editor').innerHTML = html;
  $('#overlay').classList.remove('hidden'); $('#editor').classList.remove('hidden'); setSplit();   // (modal: no split)
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
/** EVERY document of the ledger, page by page. The list and the dashboard read the newest 500 and said nothing of the
 *  rest — past them, the year's income was wrong and older documents gone from the list and its search (the code
 *  audit, B; an imported history passes 500). Null when a page does not come: never a part read as the whole. */
let DOCS_CAP = 20000, _capSaid = null;
async function readAllDocs() {
  const all = [], seen = new Set();
  for (let off = 0; off < DOCS_CAP; off += 500) {
    const page = await read('/documents?limit=500&offset=' + off);
    if (!page) return null;
    // a document written between two pages moves every row down one, and the row at a page's edge came again: the
    // dashboard counted it twice (the second reader; the ledger orders a tie by id since, so the pages are one order)
    page.forEach(d => { if (!seen.has(d.id)) { seen.add(d.id); all.push(d); } });
    if (page.length < 500) return all;
  }
  // more than the screen reads: said, never a part shown as the whole (the second reader)
  if (!(_capSaid && _capSaid.isConnected))
    _capSaid = binaTell('מוצגים המסמכים האחרונים בלבד', 'warn', { more: 'בלשכה יותר מסמכים ממה שהמסך קורא — הישנים מהם אינם ברשימה ובסיכומים' });
  return all;
}
let _dashSeq = 0, _docsSeq = 0;                    // the newest read draws: an older, slower one is no one's (the reader)
async function loadDash() {
  const seq = ++_dashSeq;
  const docs = await readAllDocs();
  if (seq !== _dashSeq || !docs) return;
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
  const [cy, cm] = todayIL().split('-').map(Number);   // this month and year are Israel's (A.13; the reader)
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
        ${kpi('₪' + (Math.round(avg) || 0).toLocaleString('he-IL'), patur ? 'קבלה ממוצעת' : 'חשבונית ממוצעת')}
        ${kpi(new Set(live.map(d => d.customer_name)).size, 'לקוחות')}
        ${kpi(docs.length, 'סה״כ מסמכים')}
      </div>
    </div>
    <div class="chart-card">
      <div class="cc-head"><span>${patur ? 'תקבולים לפי חודש' : 'הכנסות לפי חודש, לפני מע״מ'}</span><span class="muted">12 חודשים</span></div>
      <div class="bars">${bars.map(b => `<div class="bar-col"><div class="bar-wrap"><div class="bar" style="height:${Math.round(b.v / maxV * 100)}%" title="₪${money(b.v)}"></div></div><div class="bar-lbl">${b.lbl}</div></div>`).join('')}</div>
    </div>`;
  $('#recent').innerHTML = table(docs.slice(0, 8));
  wireRows($('#recent'));
}

// ── documents view: a LIST of documents, each a link to its own address (doc-list.js, DGO-2169) ──────────────────
// It was the shared spreadsheet: a click focused a cell and opened the row only when the focus came within 0.4 s of
// the pointer, and a phone got two of six columns. A document is not edited in a list (an issued one never is), so
// the list is what the owner reads and taps — chips with their counts, one search, a card on a phone. The whole
// ledger is read at once and filtered here (it is well under a few thousand rows).
function heDateSort(s) {   // dd/mm/yyyy -> sortable yyyymmdd number (0 when absent)
  const p = String(s || '').split('/');
  return p.length === 3 ? Number(p[2]) * 10000 + Number(p[1]) * 100 + Number(p[0]) : 0;
}
async function loadDocs() {
  const seq = ++_docsSeq;
  DocList.mount($('#docsTable'), {
    esc, money, typeHe: t => TYPE_HE[t] || '', statusHe: s => STATUS_HE[s] || '',
    dateOf: d => d.doc_date || '', sortOf: d => heDateSort(d.doc_date), open: id => openFromList(id),
  });
  DocList.loading();
  const docs = await readAllDocs();
  if (seq !== _docsSeq) return;
  if (!docs) return DocList.failed(loadDocs);
  DocList.set(docs);
  if (routeOf().startsWith('doc/')) DocList.mark(routeOf().slice(4));
}

/** After an act, the view ON SCREEN is read again — the archive's or «חתימות»' too; it was the hidden dashboard
 *  whenever the act was not from «מסמכים» (the code audit, A.15). Customers, items and settings hold no document. */
function refreshView() {
  const f = { dash: loadDash, docs: loadDocs, signatures: loadSignatures, archive: loadArchive }[filter.view];
  if (f) f();
}
/** A link made, renewed or closed in a drawer: «חתימות», when it is the view on screen, lists it — it stayed as it was
 *  (the second reader). The ledger is not touched by a link, so no other view changes. */
function linksChanged() { if (filter.view === 'signatures') loadSignatures(); }
/** «מילוי וחתימה» sent its link — and the ledger recorded the send: the drawer of that document is drawn again (its
 *  next step, its sides) and the view on screen read again; «חתימות» stayed without it (the second reader). */
window.FillEditorSent = d => {
  const shown = d && !$('#drawer').classList.contains('hidden') && $('#dLinks') && $('#dLinks').dataset.doc === d.id;
  if (shown) openDoc(d.id, true); else if (window.FillEditor && d) FillEditor.status(d);
  refreshView();
};
// ── «חתימות»: every link the office sent, in one place (sig-list.js, DGO-2169 step 4) ───────────────────────────────
async function loadSignatures() {
  SigList.mount($('#sigTable'), { esc, when: whenFullHe, openDoc: id => openFromList(id), openLink: linkCardOf, signAFile });
  SigList.loading();
  const j = await read('/signatures');
  if (!j || j.ok === false) return SigList.failed(loadSignatures, (j && j.message) || 'הרשימה לא נטענה.');
  SigList.set(j.links, j.more);
}
/** A link of a file of the office's own (no document holds it): where it stands, and its acts — the signed copy, a new
 *  link, closing it. A link of a document opens the document instead, whose drawer holds its links. */
async function linkCardOf(r) {
  const open = r.state === 'sent' || r.state === 'opened';
  const view = r.kind === 'view', fill = r.kind === 'fill';
  // each kind through its own routes: a «מילוי וחתימה» event is not an envelope (its id on an envelope route answered
  // a 404, «the link is closed», «it was signed» — all untrue: the reader)
  const route = fill ? { copy: 'api/fill/event/' + encodeURIComponent(r.id) + '/download', again: '/fill/event/' + encodeURIComponent(r.id) + '/link',
                         revoke: '/fill/event/' + encodeURIComponent(r.id) + '/cancel' }
                     : { copy: 'api/sign/envelope/' + encodeURIComponent(r.id) + '/download', again: '/links/' + encodeURIComponent(r.id) + '/again',
                         revoke: '/links/' + encodeURIComponent(r.id) + '/revoke' };
  const say = r.state === 'signed' ? 'נחתם' + (r.signed_at ? ' ב־' + whenFullHe(r.signed_at) : '') + '. העותק החתום — המסמך, החתימה ותעודת החתימה.'
    : r.state === 'signing' ? 'החתימה מתבצעת עכשיו — העותק החתום מופק.'
    : r.state === 'opened' ? 'הקישור נפתח' + (r.opened_at ? ' ב־' + whenFullHe(r.opened_at) : '') + (view ? '.' : ', והחתימה עוד לא התקבלה.')
    : r.state === 'sent' ? 'הקישור נשלח ועוד לא נפתח.'
    : r.state === 'expired' ? 'תוקף הקישור עבר. מי שיפתח אותו יראה שאינו בתוקף.' : 'הקישור נסגר. מי שיפתח אותו יראה שאינו בתוקף.';
  // its own card, one button per act: Escape or «סגירה» only closes the card (a two-answer question read Escape as
  // «סגירת הקישור»)
  const facts = [['אל', r.who || '—'], ['נשלח', whenFullHe(r.created_at) || '—']]
    .concat(open ? [['בתוקף עד', whenFullHe(r.expires_at) || '—']] : []);
  const acts = (r.state === 'signed' ? [['copy', 'העותק החתום', 'primary']] : [])
    .concat(open ? [['again', 'קישור חדש', 'primary'], ['revoke', 'סגירת הקישור', 'ghost danger-t']] : []);
  const a = await new Promise(resolve => {
    const scrim = document.createElement('div'); scrim.className = 'lcard-scrim';
    scrim.innerHTML = `<div class="lcard" role="dialog" aria-modal="true" dir="rtl" tabindex="-1">
        <h2>${esc(r.name || 'קישור לחתימה')}</h2><p class="muted">${esc(say)}</p>
        <dl>${facts.map(f => `<dt>${esc(f[0])}</dt><dd dir="auto">${esc(f[1])}</dd>`).join('')}</dl>
        <div class="lc-acts">${acts.map(([k, l, c]) => `<button type="button" class="${c} sm" data-a="${k}">${l}</button>`).join('')}
          <span class="lc-sp"></span><button type="button" class="ghost sm" data-a="close">סגירה</button></div></div>`;
    document.body.appendChild(scrim);
    const done = v => { document.removeEventListener('keydown', key, true); scrim.remove(); resolve(v); };
    const key = e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(null); } };
    document.addEventListener('keydown', key, true);
    scrim.addEventListener('mousedown', e => { if (e.target === scrim) done(null); });
    scrim.querySelectorAll('[data-a]').forEach(b => b.onclick = () => done(b.dataset.a === 'close' ? null : b.dataset.a));
    scrim.querySelector('.lcard').focus();
  });
  if (!a) return;
  if (a === 'copy') { window.open(route.copy, '_blank'); return; }
  if (a === 'again') {                             // a new link: the one sent before stops working (esign keeps no link)
    if (!await binaAsk({ title: 'קישור חדש?', ok: 'קישור חדש', body: 'הקישור שנשלח קודם יפסיק לעבוד מיד, והחדש יחליף אותו.' })) return;
    const res = await api(route.again, { method: 'POST' }).catch(binaNoAnswer);
    const k = await res.json().catch(() => ({}));
    if (!res.ok || !k.link) return binaTell(k.message || 'לא נוצר קישור חדש', 'bad', { more: binaSaid(res.status) });
    await linkCard({ title: view ? 'הקישור לצפייה — חדש' : fill ? 'הקישור למילוי וחתימה — חדש' : 'הקישור לחתימה — חדש',
                     link: k.link, to: 'out', subject: r.name || '', name: r.who || '' });
    return loadSignatures();
  }
  if (!await binaAsk({ title: 'לסגור את הקישור?', ok: 'סגירה', danger: true, body: 'מי שיפתח אותו יראה שהקישור אינו בתוקף.' })) return;
  const res = await api(route.revoke, { method: 'POST' }).catch(binaNoAnswer);
  if (!res.ok) return binaTell('הקישור לא נסגר', 'bad', { more: binaSaid(res.status) });
  binaTell('הקישור נסגר'); loadSignatures();
}
/** «חתימה על קובץ»: a PDF of the office's own, who signs it, for how long — then the link, sent WhatsApp first. */
function signAFile() {
  const scrim = document.createElement('div'); scrim.className = 'lcard-scrim';
  scrim.innerHTML = `<form class="lcard" role="dialog" aria-modal="true" dir="rtl" novalidate>
      <h2>חתימה על קובץ</h2>
      <p class="muted">נוצר קישור אישי. החותם פותח אותו, מקליד את שמו ומאשר, והעותק החתום חוזר לכאן ול«קבצים».</p>
      <label>קובץ PDF<input name="file" type="file" accept="application/pdf,.pdf" required/></label>
      <label>מי חותם<input name="signer" required/></label>
      <label>טלפון לוואטסאפ (רשות)<input name="phone" inputmode="tel" dir="ltr"/></label>
      <label>דוא״ל (רשות)<input name="email" type="email" dir="ltr"/></label>
      <label>בתוקף לימים<input name="days" type="number" min="1" max="365" value="14" dir="ltr"/></label>
      <label>סיסמה (רשות)<input name="password" placeholder="נמסרת בנפרד מהקישור"/></label>
      <p class="lc-warn" hidden></p>
      <div class="lc-acts"><span class="lc-sp"></span><button type="button" class="ghost sm" data-a="cancel">ביטול</button>
        <button type="submit" class="primary sm">יצירת הקישור</button></div></form>`;
  document.body.appendChild(scrim);
  const form = scrim.querySelector('form'), warn = scrim.querySelector('.lc-warn');
  const done = () => { document.removeEventListener('keydown', key, true); scrim.remove(); };
  const key = e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(); } };
  document.addEventListener('keydown', key, true);
  scrim.querySelector('[data-a=cancel]').onclick = done;
  form.onsubmit = async e => {
    e.preventDefault();
    const f = form.file.files[0], signer = form.signer.value.trim();
    const say = t => { warn.textContent = t; warn.hidden = false; };
    if (!f) return say('בוחרים קובץ PDF.');
    if (!signer) return say('נא למלא מי חותם.');
    const btn = form.querySelector('[type=submit]'); btn.disabled = true; btn.textContent = 'יוצר…';
    const fd = new FormData();
    fd.append('file', f, f.name); fd.append('signer', signer);
    fd.append('email', form.email.value.trim()); fd.append('days', form.days.value || '14');
    if (form.password.value) fd.append('password', form.password.value);
    const r = await api('/signatures/file', { method: 'POST', body: fd }).catch(binaNoAnswer);
    const j = await r.json().catch(() => ({}));
    btn.disabled = false; btn.textContent = 'יצירת הקישור';
    if (!r.ok || !j.link) return say(j.message || 'הקישור לא נוצר — ' + binaSaid(r.status));
    const phone = form.phone.value.trim(), email = form.email.value.trim();
    done();
    await linkCard({ title: 'הקישור לחתימה מוכן', link: j.link, to: 'out', email, phone, name: signer, subject: f.name,
                     note: form.password.value ? 'את הסיסמה מוסרים בנפרד מהקישור — בשיחה או בהודעה אחרת.' : '',
                     facts: [['קובץ', f.name], ['בתוקף עד', (j.envelope && whenFullHe(j.envelope.expires_at)) || '—']] });
    if (filter.view === 'signatures') loadSignatures();
  };
  form.signer.focus();
}

// table()/wireRows() still power the dashboard's "recent documents" list (#recent).
function table(docs) {
  if (!docs.length) return '<div class="empty">אין מסמכים עדיין — צרו מסמך חדש.</div>';
  return `<table class="data"><thead><tr>
    <th>מספר</th><th>סוג</th><th>לקוח</th><th>סכום</th><th>סטטוס</th></tr></thead><tbody>${
    // every value escaped: a customer's name was markup here (the code audit, A.4)
    docs.map(d => `<tr data-id="${esc(d.id)}" tabindex="0">
      <td class="num">${esc(d.doc_number || '—')}</td>
      <td>${esc(TYPE_HE[d.doc_type] || d.doc_type)}</td>
      <td>${esc(d.customer_name || '')}</td>
      <td class="num">${d.total != null ? '₪' + money(d.total) : ''}</td>
      <td><span class="chip ${esc(d.status)}">${esc(STATUS_HE[d.status] || d.status)}</span></td>
    </tr>`).join('')}</tbody></table>`;
}
// a row opens on a click, a tap or Enter — a row the keyboard can reach (the code audit, C)
function wireRows(root) {
  // (from a list beside an open document, a row takes its place: one history entry — the reader)
  root.querySelectorAll('tr[data-id]').forEach(tr => {
    tr.onclick = () => openFromList(tr.dataset.id);
    tr.onkeydown = e => { if (e.key === 'Enter') openFromList(tr.dataset.id); };
  });
}

// ── editor (create) ─────────────────────────────────────────
// ── a new document: pick its type, fill its form, and watch the document itself (DGO-2029) ──────────
let DOC_EDITOR_HTML = '';   // captured at boot so the entity editor can share #editor
let DOC_TYPE = '';          // the type being written
let EDIT_DOC = null;        // the draft being written again — null for a new document (DGO-2047)
let _savedJson = '';        // that draft's form as last saved: leaving with another asks first
let _typed = false;         // a new document's form was typed in since it opened: leaving it asks first (A.11)
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

async function openEditor(type, existing) {
  $('#editor').innerHTML = DOC_EDITOR_HTML;   // restore the document editor markup
  EDIT_DOC = existing || null;
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
  if ($('#fDate')) $('#fDate').value = todayIL();  // default today, Israel's day (editable)
  $('#overlay').classList.remove('hidden'); $('#editor').classList.remove('hidden'); setSplit();   // (modal: no split)
  if (EDIT_DOC) { await pickType(EDIT_DOC.doc_type, EDIT_DOC.model || {}); return; }
  if (type && FORM[type] && mayIssue(type)) await pickType(type); else showGallery();
}

/** A draft, back in the editor: its own form from its own model, saved where it is — the edit link opens here
 *  (DGO-2047). An issued document is not written again: it opens as itself, and its drawer says how it goes on. */
async function editDoc(id) {
  const d = await read('/documents/' + id);
  if (!d) return;
  if (d.status !== 'draft') {
    binaTell('מסמך שהופק אינו נערך עוד', 'warn', { more: 'ממשיכים ממנו למסמך הבא, או מבטלים אותו ומפיקים חדש' });
    return openDoc(id, true);   // in the edit address's place: Back went to it, and it pushed the drawer again (the reader)
  }
  closeDrawer(true);
  await openEditor(d.doc_type, d);
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
  _typed = false;
  showRoute('new', routeOf().startsWith('new'));   // «חזרה לסוגים» takes the form's place, never a second entry
}

/** Step 2 — the form of one type, beside its document; a narrative type starts from its template, and a draft
 *  written again from its own model (`model`, DGO-2047). */
let _pickSeq = 0;                                  // the newest choice of a type: a template that answers late is no one's
async function pickType(code, model) {
  const seq = ++_pickSeq, form = $('#docForm'), foot = $('#editorFoot');
  // the form AND its buttons: «הפק מסמך» under a waiting form issued what the template was about to replace (the reader)
  const waiting = on => { form.inert = foot.inert = on; if (on) form.setAttribute('aria-busy', 'true'); else form.removeAttribute('aria-busy'); };
  DOC_TYPE = code;
  waiting(false);
  setEdShow('form');                               // a narrow screen opens on the form
  $('#fType').value = code;
  const f = FORM[code] || {};
  $('#typeGallery').classList.add('hidden');
  ['#stage', '#editorFoot', '#backToTypes'].forEach(s => $(s).classList.remove('hidden'));
  $('#editor').classList.add('wide');
  $('#editorTitle').textContent = TYPE_HE[code];
  if (model) {
    // a draft keeps its type: what was written is in the ledger under it (a type is chosen once, for a new one)
    $('#backToTypes').classList.add('hidden');
    $('#editorTitle').textContent = 'טיוטה · ' + (TYPE_HE[code] || code);
    $('#saveDraft').textContent = 'שמירה';
    $('#editLinkBtn').classList.remove('hidden');
    $('#savedAt').textContent = EDIT_DOC && EDIT_DOC.updated_at ? 'נשמרה ' + whenHe(EDIT_DOC.updated_at) : '';
  }
  $('#docForm').querySelectorAll('[data-for]').forEach(el => {
    const k = el.dataset.for;
    const on = k === 'price' ? !f.noprice : !!f[k];
    el.classList.toggle('hidden', !on);
  });
  $('#linesLegend').textContent = f.noprice ? 'מה נמסר' : 'שורות';
  if (model) applyModel(model);
  else {
    // the template is on its way: what is typed meanwhile it would write over, so the form waits for it (A.14)
    waiting(true);
    const tpl = await read('/docGen/house/template?type=' + code);
    // another type, a draft, the gallery or ✕ since — or the editor's markup replaced (a customer's form)
    if (seq !== _pickSeq || DOC_TYPE !== code || !form.isConnected) return;
    waiting(false);
    applyTemplate(tpl && tpl.ok ? tpl.document || {} : {});     // no template: the fields are emptied all the same
  }
  renderLines();
  // the form takes the gallery's place (one entry: Back leaves the editor); a draft's editor goes over its drawer
  showRoute(EDIT_DOC ? 'doc/' + encodeURIComponent(EDIT_DOC.id) + '/edit' : 'new/' + code, !EDIT_DOC && routeOf().startsWith('new'));
  if (EDIT_DOC) _savedJson = JSON.stringify(buildModel());
  _typed = false;                                  // the template is not typing: leaving it asks nothing
  schedulePreview();
}

/** The reverse of buildModel: a draft's own model back in the form (DGO-2047). Every field is set — empty where the
 *  model says nothing, as applyTemplate does — so nothing of another document rides along. What the form does not
 *  show (the supplier, the bank, the VAT rate, a converted document's own fields) stays in the ledger: a save
 *  MERGES into the stored model (store.update), it does not replace it. */
function applyModel(m) {
  const set = (sel, v) => { const el = $(sel); if (el) el.value = v == null ? '' : (Array.isArray(v) ? v.join('\n') : v); };
  const iso = he => { const p = String(he || '').split('/'); return p.length === 3 ? p[2] + '-' + p[1].padStart(2, '0') + '-' + p[0].padStart(2, '0') : ''; };
  const c = m.customer || {}, cover = m.cover || {};
  set('#cName', c.name); set('#cId', c.company_id); set('#cStreet', c.street); set('#cCity', c.city);
  set('#cPerson', c.contact_person); set('#cEmail', c.email);
  set('#fDate', iso(m.doc_date) || todayIL());
  set('#fValid', iso(m.valid_until)); set('#fDue', iso(m.payment_due)); set('#fDelivery', iso(m.delivery_date));
  set('#fCoverTitle', cover.title); set('#fCoverSub', cover.subtitle);
  set('#fSubject', m.subject); set('#fIntro', m.intro); set('#fTerms', m.terms); set('#fNotes', m.notes);
  set('#fAgrTitle', m.title); set('#fRecitals', m.recitals);
  set('#fLtSubject', m.subject); set('#fLtBody', m.body);
  set('#fAmount', m.amount); set('#fNature', m.nature);
  set('#fPayRef', m.cheque_number); set('#fPayBank', m.cheque_bank);
  set('#fPay', m.payment_method || 'העברה בנקאית');
  if ($('#fPayBankBox')) $('#fPayBankBox').classList.toggle('hidden', $('#fPay').value !== 'המחאה');
  SECTIONS = (m.sections || []).map(s => ({ title: s.title || '', body: s.body || '', pricing: !!s.pricing }));
  CLAUSES = (m.clauses || []).map(k => ({ title: k.title || '', text: k.text || '', items: (k.items || []).join('\n') }));
  // each line keeps its whole stored self (`orig`): what the form does not show goes back with it (buildModel)
  lines = (m.lines || []).map(l => ({ description: l.description || '', qty: l.qty == null ? 1 : Number(l.qty),
                                      unit_price: Number(l.unit_price) || 0, sku: l.sku || '', period: l.period || '', orig: l }));
  if (!lines.length) lines = [{ description: '', qty: 1, unit_price: 0, sku: '' }];
  renderSections(); renderClauses();
}
// ISRAEL'S CLOCK, whatever the device's (the code audit, A.13): the log printed the server's UTC as it came, and a new
// document's date was UTC's day — between midnight and 02:00/03:00 a document made today was dated yesterday. The
// ledger keeps the same clock for itself (store.py's israel_now). A time with no zone is the database's own UTC.
const IL_TZ = 'Asia/Jerusalem';
const _ilParts = (ts, opts) => {
  const s = String(ts == null ? '' : ts).trim();
  const d = new Date(/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(s) ? s.replace(' ', 'T') + 'Z' : s);
  if (!s || isNaN(d)) return null;
  const o = {};
  new Intl.DateTimeFormat('en-GB', Object.assign({ timeZone: IL_TZ, hourCycle: 'h23' }, opts)).formatToParts(d).forEach(p => { o[p.type] = p.value; });
  return o;
};
/** today's date in Israel, as the form's YYYY-MM-DD */
function todayIL() {
  const o = _ilParts(new Date().toISOString(), { year: 'numeric', month: '2-digit', day: '2-digit' });
  return o.year + '-' + o.month + '-' + o.day;
}
/** «19/11 22:23» — the day and the time, in Israel */
function whenHe(ts) {
  const o = _ilParts(ts, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  return o ? o.day + '/' + o.month + ' ' + o.hour + ':' + o.minute : '';
}
/** «19/11/2026 22:23» — the log's time, with its year */
function whenFullHe(ts) {
  const o = _ilParts(ts, { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  return o ? o.day + '/' + o.month + '/' + o.year + ' ' + o.hour + ':' + o.minute : '';
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
// A NARROW SCREEN SHOWS THE FORM OR THE DOCUMENT (DGO-2169; style.css `.stage[data-show]`): while the form is shown the
// document is not drawn on every pause (the audit: it was, out of sight, 420 ms after each keystroke) — it is drawn
// when it is shown. On a wide desk both stand and the document follows the typing as before.
let _pvDirty = false;
const edShowsForm = () => !!(window.matchMedia && matchMedia('(max-width:1100px)').matches && $('#stage') && $('#stage').dataset.show === 'form');
function setEdShow(t) {
  const st = $('#stage');
  if (!st) return;
  st.dataset.show = t;
  st.querySelectorAll('.ed-seg [data-t]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.t === t)));
  if (t === 'doc') { if (_pvDirty) schedulePreview(true); else fitPreview(); }
}
function schedulePreview(now) {
  if (!DOC_TYPE) return;
  clearTimeout(_pvTimer);
  if (edShowsForm()) { _pvDirty = true; return; }
  _pvDirty = false;
  _pvTimer = setTimeout(async () => {
    const seq = ++_pvSeq;
    $('#pvState').textContent = 'מעדכן…';
    const r = await api('/docGen/house?format=html&label=' + encodeURIComponent('טיוטה') + '&fonts=api/docGen/house/fonts/', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(buildModel()),
    }).catch(binaNoAnswer);
    if (seq !== _pvSeq) return;                 // a newer keystroke already asked
    // a refused drawing is drawn again the next time the document is shown, not left standing (the reader)
    if (!r.ok) { _pvDirty = true; $('#pvState').textContent = 'התצוגה לא עודכנה — ' + binaSaid(r.status); return; }
    const html = await r.text();
    if (seq !== _pvSeq) return;                 // (and again after the body: a slow one never covers a newer one)
    const fr = $('#pvFrame');
    fr.onload = () => fitPreview();
    fr.srcdoc = html;
    $('#pvState').textContent = '';
  }, now === true ? 0 : 420);
}
/** A sheet is 210mm wide; the pane is what it is — the sheet is scaled to it, never scrolled sideways. */
function fitPreview() {
  const fr = $('#pvFrame'), box = $('#pvBox');
  if (!fr || !box || !fr.contentDocument || !fr.contentDocument.documentElement) return;
  if (box.clientWidth <= 8) return;               // hidden («טופס» on a phone): 0px wide — a negative scale (DGO-2042)
  const w = 860, s = Math.min(1, (box.clientWidth - 8) / w);
  const h = fr.contentDocument.documentElement.scrollHeight;
  fr.style.width = w + 'px'; fr.style.height = h + 'px';
  fr.style.transform = 'scale(' + s + ')';
  fr.parentElement.style.setProperty('--pv-h', Math.ceil(h * s) + 'px');
}
// (a window that widens shows a document not drawn while it was hidden: it is drawn now)
window.addEventListener('resize', () => { if (DOC_TYPE) { if (_pvDirty && !edShowsForm()) schedulePreview(true); else fitPreview(); } });
function wireDocEditor() {
  $('#closeEditor').onclick = leaveEditor;
  $('#stage').querySelectorAll('.ed-seg [data-t]').forEach(b => b.onclick = () => setEdShow(b.dataset.t));
  $('#editLinkBtn').onclick = () => EDIT_DOC && copyLink('הקישור לעריכה', linkTo('doc/' + encodeURIComponent(EDIT_DOC.id) + '/edit'),
    'הקישור פותח את הטיוטה הזאת בעורך, בלשכה — למי שנכנס אליה. ללקוח שולחים «קישור לצפייה» או «מילוי וחתימה».');
  $('#backToTypes').onclick = showGallery;
  $('#addLine').onclick = () => { lines.push({ description: '', qty: 1, unit_price: 0, sku: '', period: '' }); renderLines(); };
  $('#addSection').onclick = () => { SECTIONS.push({ title: '', body: '' }); renderSections(); };
  $('#addClause').onclick = () => { CLAUSES.push({ title: '', text: '', items: '' }); renderClauses(); };
  $('#saveDraft').onclick = () => save(false);
  $('#issueNow').onclick = () => save(true);
  // a cheque asks its bank too (a receipt for one is refused without it: §5(b))
  $('#fPay').addEventListener('change', () => $('#fPayBankBox').classList.toggle('hidden', $('#fPay').value !== 'המחאה'));
  // every field of the form redraws the document beside it — and is typing, which leaving asks about (A.11)
  $('#docForm').addEventListener('input', e => { _typed = true; if (!e.target.closest('#lines')) schedulePreview(); });
  $('#docForm').addEventListener('change', () => schedulePreview());
}
/** Closes the editor; `keepRoute` (true) when the caller writes the address itself. */
function closeEditor(keepRoute) {
  DOC_TYPE = ''; _typed = false;
  const was = EDIT_DOC; EDIT_DOC = null; _savedJson = '';
  $('#overlay').classList.add('hidden'); $('#editor').classList.add('hidden'); $('#editor').classList.remove('wide');
  setSplit();                                      // a document still open goes back beside the list
  const cl = document.getElementById('custList'); if (cl) cl.remove();
  if (keepRoute === true) return;                                    // (a click passes an event: not «keep»)
  // a document still open beside the list is where the address goes back to — the editor was opened over it
  // («מסמך חדש» from a split view); the list's own address would leave it open under a wrong one (the reader)
  const beside = !$('#drawer').classList.contains('hidden') && $('#dLinks') && $('#dLinks').dataset.doc;
  if (routeOf().startsWith('new') || (was && /\/edit$/.test(routeOf()))) leaveTo(beside ? 'doc/' + beside : (filter.view || 'dash'));
}
/** Something typed that leaving would lose: a draft's form since its last save, a new document's since it opened. */
function editorDirty() {
  if (!DOC_TYPE || $('#editor').classList.contains('hidden')) return false;
  return EDIT_DOC ? JSON.stringify(buildModel()) !== _savedJson : _typed;
}
/** Leaving the editor by ✕, the overlay or Back: what was typed is not dropped without a word (DGO-2047, A.11). */
async function mayLeaveEditor() {
  if (!editorDirty()) return true;
  return !!await binaAsk({ title: 'לצאת בלי לשמור?', ok: 'יציאה', cancel: 'חזרה לעריכה', danger: true,
    body: EDIT_DOC ? 'השינויים מאז השמירה האחרונה לא יישמרו.' : 'המסמך שהתחלתם לכתוב לא יישמר. «שמור טיוטה» שומר אותו בלי להפיק.' });
}
/** Back to the drawer of `id`: its own entry when the editor was opened from it, else the drawer in the editor's place. */
function toDrawer(id) {
  if (backIsOurs('doc/' + id)) history.back(); else openDoc(id, true);
}
/** ✕ in the editor: a draft written again goes back to its drawer. */
async function leaveEditor() {
  const id = EDIT_DOC && EDIT_DOC.id;
  if (!await mayLeaveEditor()) return;
  if (!id) { closeEditor(); return; }
  closeEditor(true); toDrawer(id);
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
      // another item: the stored line it replaces keeps nothing of its own (its unit is the item's now)
      if (it) { l.unit_price = Number(it.unit_price) || 0; l.sku = it.sku || ''; l.orig = it.unit ? { unit: it.unit } : null; renderLines(); }
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
  if (!f.lines || f.noprice) {                     // (no prices, no total — never the last type's)
    box.classList.add('hidden'); if ($('#edTotal')) { $('#edTotal').textContent = ''; $('#edTotal').dataset.said = ''; } return;
  }
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
  // …and the total in the buttons' row: in sight however long the form, whichever of form and document is shown —
  // a monthly line's too (a retainer alone read «₪0.00»), and written only when it changes: a live region read the
  // same sum aloud after every letter of a description (the reader)
  const t = $('#edTotal');
  const said = 'סה״כ ₪' + money(tot) + (monthly.length ? ' + ₪' + money(mon * (1 + rate / 100)) + ' לחודש' : '');
  if (t && t.dataset.said !== said) {
    t.dataset.said = said;
    t.innerHTML = `סה״כ <span class="num">₪${money(tot)}</span>` +
      (monthly.length ? ` + <span class="num">₪${money(mon * (1 + rate / 100))}</span> לחודש` : '');
  }
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
  // WHAT THE FORM DOES NOT SHOW IS KEPT (the second reader of DGO-2047). The ledger merges a draft's top-level keys
  // only, and `customer` and `lines` go whole: the first «שמירה» of a draft made by «המשך» or by an agent dropped the
  // customer's phone, zip, VAT file and number, and each line's unit, order refs and detail. The same customer (its
  // name or its number) keeps the rest of its stored self; another customer is only what the form says.
  const was = (EDIT_DOC && EDIT_DOC.model && EDIT_DOC.model.customer) || {};
  const cust = { name: val('#cName'), company_id: val('#cId'), street: val('#cStreet'), city: val('#cCity'),
                 contact_person: val('#cPerson'), email: val('#cEmail') };
  if (was.name && (was.name === cust.name || (was.company_id && was.company_id === cust.company_id)))
    Object.keys(was).forEach(k => { if (!(k in cust)) cust[k] = was[k]; });
  const m = { doc_type: type, doc_date: isoToHe($('#fDate') && $('#fDate').value), customer: cust };  // the supplier is the business: the ledger fills it
  if (f.valid) m.valid_until = he('#fValid');
  if (f.due) m.payment_due = he('#fDue');
  if (f.delivery) m.delivery_date = he('#fDelivery');
  if (f.lines) m.lines = lines.filter(l => l.description).map(l => {
    const o = Object.assign({}, l.orig || {}, { description: l.description, qty: l.qty });   // (the reader, above)
    delete o.sku;
    if (!f.noprice) o.unit_price = l.unit_price;
    if (l.sku) o.sku = l.sku;
    if (f.period) { delete o.period; if (l.period) o.period = 'month'; }
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
  if (($('#docForm') || {}).inert) return;   // (nor while the type's template is on its way: it would be written over)
  const model = buildModel();                // one is in flight — that is how duplicate documents happen.
  if (EDIT_DOC) return saveExisting(issue, model);
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
    if (r.status >= 400) {
      // A REFUSED «הפק» LEFT A DRAFT (the code audit, A.5): the ledger made it, then would not number it (422, the
      // draft in its body), and every retry made another one. The editor now goes on writing THAT draft: the next
      // «הפק» saves it where it is and issues it (saveExisting)
      const left = d.document && d.document.id ? d.document : null;
      if (left) {
        EDIT_DOC = left; _savedJson = JSON.stringify(model);
        $('#editorTitle').textContent = 'טיוטה · ' + (TYPE_HE[model.doc_type] || model.doc_type);
        $('#backToTypes').classList.add('hidden'); $('#saveDraft').textContent = 'שמירה';
        $('#editLinkBtn').classList.remove('hidden');
        showRoute('doc/' + encodeURIComponent(left.id) + '/edit', true);
      }
      binaTell(d.message || 'המסמך לא נוצר', 'bad', left ? { more: 'הוא נשמר כטיוטה — משלימים את החסר ומפיקים שוב' } : { more: binaSaid(r.status) });
      return;
    }
    binaTell(issue ? `הופק ${d.doc_number}` : 'נשמרה טיוטה');
    closeEditor(true); openDoc(d.id, true); show(filter.view);   // the new document takes the editor's entry
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

/** A draft saved where it is (PATCH — the ledger merges the model and counts again), and «הפק» issues that same
 *  draft: no second document is ever made from one being written (DGO-2047). The view links of it follow it. */
async function saveExisting(issue, model) {
  const id = EDIT_DOC.id;
  if (issue && !await binaAsk({ title: 'להפיק את המסמך?', ok: 'הפקה',
      body: 'המסמך יקבל מספר וייחתם דיגיטלית. אחרי ההפקה הוא אינו נערך עוד.',
      facts: [['מסמך', TYPE_HE[model.doc_type] || model.doc_type], ['לקוח', (model.customer && model.customer.name) || '—']] })) return;
  _saving = true;
  const btns = [$('#saveDraft'), $('#issueNow')].filter(Boolean);
  const clicked = issue ? $('#issueNow') : $('#saveDraft');
  const orig = clicked ? clicked.innerHTML : '';
  btns.forEach(b => { b.disabled = true; });
  if (clicked) { clicked.textContent = issue ? 'מנפיק…' : 'שומר…'; clicked.classList.add('is-loading'); }
  try {
    let r = await api('/documents/' + encodeURIComponent(id), { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                                                              body: JSON.stringify(model) }).catch(binaNoAnswer);
    let d = await r.json().catch(() => ({}));
    if (!r.ok) return binaTell(d.message || 'השמירה נכשלה', 'bad', { more: binaSaid(r.status) });
    const followed = (r.headers && r.headers.get && r.headers.get('X-Views-Followed')) || '';
    _savedJson = JSON.stringify(model); EDIT_DOC = d;
    $('#savedAt').textContent = 'נשמרה ' + whenHe(d.updated_at || new Date().toISOString());
    if (!issue) {
      const [n, of] = followed.split('/').map(Number);
      binaTell('נשמרה', 'ok', of ? { more: n === of ? (of > 1 ? 'הקישורים לצפייה מראים' : 'הקישור לצפייה מראה') + ' את הגרסה הזאת'
                                                    : 'קישור לצפייה לא עודכן — נסו לשמור שוב' } : undefined);
      return;
    }
    r = await api('/documents/' + encodeURIComponent(id) + '/issue', { method: 'POST', headers: { 'Content-Type': 'application/json' } }).catch(binaNoAnswer);
    d = await r.json().catch(() => ({}));
    if (!r.ok) return binaTell(d.message || 'ההפקה נכשלה', 'bad', { more: binaSaid(r.status) + ' — הטיוטה נשמרה' });
    binaTell('הופק ' + (d.doc_number || ''));
    closeEditor(true); toDrawer(id); show(filter.view);
  } finally {
    _saving = false;
    btns.forEach(b => { b.disabled = false; });
    if (clicked) { clicked.innerHTML = orig; clicked.classList.remove('is-loading'); }
  }
}

// ── links: the edit link (inside the office), the view link and the signing link (to the customer) — DGO-2047 ──────
/** A route of this app as the ONE link a person is given (DGO-1433): `/go/<tile>/<route>` on the console this screen
 *  is framed in, whose tile is this app's mount there (`/a/my-docs.hp-laptop/` on the herd's hub) — so it opens this
 *  very screen wherever that console is reached. Outside a console: this page's own address. */
function linkTo(route) {
  const tile = /^\/a\/([^/]+)$/.exec(MOUNT);
  return location.origin + (tile ? '/go/' + tile[1] : MOUNT) + '/' + route;
}
const localHost = h => /(^|\.)localhost$|^127\.|^\[?::1\]?$/.test(h);
/** A link, shown whole, with the ways to send it — copy, WhatsApp, e-mail — and to open it as its reader will. The
 *  sending is the person's own act: these open HIS apps with the words filled in; nothing leaves from here. */
function linkCard({ title, link, note, facts, to, email, subject, phone, name }) {
  // a link that goes OUT to a customer is sent, WhatsApp first and to his own number (send-sheet.js, DGO-2169); a
  // link of the office's own (the edit link) stays a card to copy
  const local = (() => { try { return localHost(new URL(link).hostname); } catch (e) { return false; } })();
  if (to === 'out' && window.SendSheet && !local)
    return SendSheet.open({ title, link, note, facts, email, subject, phone, to: name || '' });
  return new Promise(resolve => {
    const local = (() => { try { return localHost(new URL(link).hostname); } catch (e) { return false; } })();
    const words = (subject ? subject + ' — ' : '') + link;
    const scrim = document.createElement('div'); scrim.className = 'lcard-scrim';
    scrim.innerHTML = `<div class="lcard" role="dialog" aria-modal="true" dir="rtl" tabindex="-1">
      <h2>${esc(title)}</h2>
      ${note ? `<p class="muted">${esc(note)}</p>` : ''}
      ${facts && facts.length ? `<dl>${facts.map(f => `<dt>${esc(f[0])}</dt><dd>${esc(f[1])}</dd>`).join('')}</dl>` : ''}
      <div class="lc-link"><input readonly dir="ltr" value="${esc(link)}" aria-label="הקישור"/><button class="primary sm" data-a="copy">העתקה</button></div>
      ${local ? '<p class="lc-warn">זה קישור של המחשב הזה (localhost) — מחוץ לו הוא לא נפתח. פתחו את המסמך דרך הלשכה המרכזית והעתיקו משם.</p>' : ''}
      <div class="lc-acts">
        ${to === 'out' ? `<a class="ghost sm btn" data-a="wa" target="_blank" rel="noopener" href="https://wa.me/?text=${encodeURIComponent(words)}">וואטסאפ</a>
        <a class="ghost sm btn" data-a="mail" href="mailto:${encodeURIComponent(email || '')}?subject=${encodeURIComponent(subject || '')}&body=${encodeURIComponent(words)}">דוא״ל</a>` : ''}
        <a class="ghost sm btn" data-a="open" target="_blank" rel="noopener" href="${esc(link)}">פתיחה</a>
        <span class="lc-sp"></span><button class="ghost sm" data-a="close">סגירה</button>
      </div></div>`;
    document.body.appendChild(scrim);
    const card = scrim.querySelector('.lcard'), input = scrim.querySelector('input');
    const done = () => { document.removeEventListener('keydown', key, true); scrim.remove(); resolve(); };
    const key = e => { if (e.key === 'Escape') { e.preventDefault(); done(); } };
    document.addEventListener('keydown', key, true);
    scrim.addEventListener('mousedown', e => { if (e.target === scrim) done(); });
    input.addEventListener('focus', () => input.select());
    scrim.querySelector('[data-a=close]').onclick = done;
    scrim.querySelector('[data-a=copy]').onclick = async () => {
      try { await navigator.clipboard.writeText(link); binaTell('הקישור הועתק'); }
      catch (e) { input.focus(); input.select(); binaTell('ההעתקה נחסמה — הקישור מסומן, העתיקו אותו', 'warn'); }
    };
    card.focus();
  });
}
const copyLink = (title, link, note) => linkCard({ title, link, note });
/** A short form in the same frame: the fields a link needs (who, how long, a password) — or null when not given. */
function formCard({ title, body, fields, ok }) {
  return new Promise(resolve => {
    const scrim = document.createElement('div'); scrim.className = 'lcard-scrim';
    scrim.innerHTML = `<form class="lcard" role="dialog" aria-modal="true" dir="rtl" novalidate>
      <h2>${esc(title)}</h2>${body ? `<p class="muted">${esc(body)}</p>` : ''}
      ${fields.map(f => `<label>${esc(f.label)}<input name="${f.name}" type="${f.type || 'text'}" value="${esc(f.value == null ? '' : f.value)}"
         ${f.dir ? `dir="${f.dir}"` : ''} ${f.min ? `min="${f.min}"` : ''} ${f.max ? `max="${f.max}"` : ''} placeholder="${esc(f.placeholder || '')}"/>
         ${f.hint ? `<small>${esc(f.hint)}</small>` : ''}</label>`).join('')}
      <p class="lc-said" role="alert"></p>
      <div class="lc-acts"><span class="lc-sp"></span><button type="button" class="ghost sm" data-a="cancel">ביטול</button>
        <button type="submit" class="primary sm">${esc(ok)}</button></div></form>`;
    document.body.appendChild(scrim);
    const form = scrim.querySelector('form');
    const done = v => { document.removeEventListener('keydown', key, true); scrim.remove(); resolve(v); };
    const key = e => { if (e.key === 'Escape') { e.preventDefault(); done(null); } };
    document.addEventListener('keydown', key, true);
    scrim.addEventListener('mousedown', e => { if (e.target === scrim) done(null); });
    scrim.querySelector('[data-a=cancel]').onclick = () => done(null);
    form.onsubmit = e => {
      e.preventDefault();
      const v = {}; fields.forEach(f => { v[f.name] = form.elements[f.name].value.trim(); });
      const miss = fields.find(f => f.must && !v[f.name]);
      if (miss) { scrim.querySelector('.lc-said').textContent = 'חסר: ' + miss.label; form.elements[miss.name].focus(); return; }
      done(v);
    };
    (form.querySelector('input') || form).focus();
  });
}
const LINK_STATE = { sent: 'פתוח · טרם נפתח', opened: 'נפתח', signed: 'נחתם', cancelled: 'בוטל', expired: 'פג תוקף', declined: 'נדחה', signing: 'נחתם עכשיו' };
/** The drawer's «קישורים»: every link this document went out in, newest first, with its state and its two acts. */
/** …and gives back the rows it drew (the timeline adds their times), or null when it drew none of this document's. */
async function loadLinks(d) {
  const host = $('#dLinks');
  if (!host) return null;
  host.innerHTML = '';
  host.dataset.doc = d.id;
  const j = await read('/links/' + encodeURIComponent(d.id));
  // another document opened meanwhile: its links are its own (A's late answer drew A's «סגירת הקישור» in B's drawer)
  if (host.dataset.doc !== d.id || $('#drawer').classList.contains('hidden')) return null;
  const rows = (j && j.links) || [];
  if (!rows.length) { host.innerHTML = j && j.ok === false ? '<h3>קישורים</h3><p class="muted">אפליקציית החתימות לא ענתה — הקישורים לא נטענו.</p>' : ''; return j && j.ok === false ? null : rows; }
  host.innerHTML = '<h3>קישורים</h3><ul>' + rows.map((e, i) => {
    const open = ['sent', 'opened'].includes(e.state);
    return `<li><div class="lk-h"><b>${e.kind === 'view' ? 'לצפייה' : 'לחתימה'}</b> · ${esc(e.signer_name || '—')}
        <span class="chip ${e.state === 'signed' ? 'paid' : e.state === 'opened' ? 'sent' : open ? 'issued' : 'cancelled'}">${LINK_STATE[e.state] || esc(e.state)}</span></div>
      <div class="t">נוצר ${whenHe(e.created_at)}${e.opened_at ? ' · נפתח ' + whenHe(e.opened_at) : ''}${e.signed_at ? ' · נחתם ' + whenHe(e.signed_at) : ''}${open ? ' · בתוקף עד ' + whenHe(e.expires_at) : ''}${e.password ? ' · בסיסמה' : ''}</div>
      ${open ? `<div class="lk-acts"><button class="ghost sm" data-again="${i}" title="הקישור הקודם יפסיק לעבוד">קישור חדש</button><button class="ghost sm danger-t" data-revoke="${i}">סגירת הקישור</button></div>` : ''}</li>`;
  }).join('') + '</ul>';
  host.querySelectorAll('[data-again]').forEach(b => b.onclick = () => guard(b, async () => {
    const e = rows[+b.dataset.again];
    if (!await binaAsk({ title: 'קישור חדש?', ok: 'קישור חדש', body: 'הקישור שנשלח קודם יפסיק לעבוד מיד, והחדש יחליף אותו. לשלוח אותו שוב למי שקיבל את הקודם.' })) return;
    const r = await api('/links/' + e.id + '/again', { method: 'POST' }).catch(binaNoAnswer);
    const k = await r.json().catch(() => ({}));
    if (!r.ok || !k.link) return binaTell(k.message || 'לא נוצר קישור חדש', 'bad', { more: binaSaid(r.status) });
    const cu = (d.model && d.model.customer) || {};
    await linkCard({ title: e.kind === 'view' ? 'הקישור לצפייה — חדש' : 'קישור החתימה — חדש', link: k.link, to: 'out',
                     email: cu.email || '', subject: docTitle(d), phone: cu.phone || await customerPhone(d),
                     name: e.signer_name || cu.name || '' });
    loadLinks(d); linksChanged();
  }));
  host.querySelectorAll('[data-revoke]').forEach(b => b.onclick = () => guard(b, async () => {
    const e = rows[+b.dataset.revoke];
    if (!await binaAsk({ title: 'לסגור את הקישור?', ok: 'סגירה', danger: true, body: 'מי שיפתח אותו יראה שהקישור אינו בתוקף. המסמך עצמו לא משתנה.',
                         facts: [['קישור', e.kind === 'view' ? 'לצפייה' : 'לחתימה'], ['אל', e.signer_name || '—']] })) return;
    const r = await api('/links/' + e.id + '/revoke', { method: 'POST' }).catch(binaNoAnswer);
    if (!r.ok) return binaTell('הקישור לא נסגר', 'bad', { more: binaSaid(r.status) });
    binaTell('הקישור נסגר'); loadLinks(d); linksChanged();
  }));
  return rows;
}
/** The customer's phone for WhatsApp, read from «לקוחות» when the link is sent — by the document's customer id, else
 *  by its name. Never written into the document: its customer block is printed, phone and all (the reader of
 *  DGO-2169: carried into the model, every new document — an invoice's «מקור» too — printed a phone nobody asked for). */
async function customerPhone(d) {
  const custs = await api('/customers').then(r => (r.ok ? r.json() : [])).catch(() => []);
  const c = (custs || []).find(x => (d.customer_id && x.id === d.customer_id)) ||
            (custs || []).find(x => x.name && x.name === d.customer_name);
  return (c && c.phone) || '';
}
const docTitle = d => (TYPE_HE[d.doc_type] || 'מסמך') + (d.doc_number ? ' ' + d.doc_number : '') + (d.customer_name ? ' — ' + d.customer_name : '');
/** «קישור לצפייה»: for whom, for how long, a password if wanted — then the link, ready to send. */
async function shareDoc(d) {
  const c = (d.model && d.model.customer) || {};
  // a document of the books carries what a download carries: its «מקור» the first time it is served, «העתק» after —
  // the link is that serving, so the form says which before the link is made (Instruction 36)
  const books = BOOKS.has(d.doc_type) && d.status !== 'draft';
  const v = await formCard({ title: 'קישור לצפייה', ok: 'צור קישור',
    body: 'מי שמקבל את הקישור רואה את המסמך ויכול להוריד אותו, בלי כניסה ללשכה. הקישור אינו חותם על דבר, ונסגר בתאריכו או כשסוגרים אותו.'
          + (d.status === 'draft' ? ' טיוטה נשלחת כ«טיוטה», והקישור יראה כל שמירה שלה עד שתופק.' : '')
          + (books ? (d.original_served_at ? ' המסמך יוצא כ«העתק»: המקור שלו כבר הופק.'
                                           : ' זה מסמך חשבונאי שהמקור שלו טרם הופק: הקישור הזה נושא את ה«מקור» — שולחים אותו ללקוח. כל הפקה אחריו היא «העתק».') : ''),
    fields: [{ name: 'to', label: 'אל', value: c.contact_person || c.name || d.customer_name || '' },
             { name: 'days', label: 'בתוקף לימים', type: 'number', value: 30, min: 1, max: 365, dir: 'ltr' },
             { name: 'password', label: 'סיסמה למסמך (רשות)', placeholder: 'נמסרת בנפרד מהקישור', hint: 'מי שפותח את הקישור מתבקש להזין אותה' }] });
  if (!v) return;
  const r = await api('/share/' + encodeURIComponent(d.id), { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ to: v.to, days: Number(v.days) || 30, password: v.password }) }).catch(binaNoAnswer);
  const j = await r.json().catch(() => ({}));
  if (!r.ok || !j.link) return binaTell(j.message || 'הקישור לא נוצר', 'bad', { more: binaSaid(r.status) });
  await linkCard({ title: 'הקישור לצפייה מוכן', link: j.link, to: 'out', email: c.email || '', subject: docTitle(d),
                   phone: c.phone || await customerPhone(d), name: v.to || c.contact_person || c.name || '',
                   note: v.password ? 'את הסיסמה מוסרים בנפרד מהקישור — בשיחה או בהודעה אחרת.' : '',
                   // the date the link itself keeps (esign's), never the number typed: 500 was said, 365 was kept — and
                   // «1 ימים» (the reader; G89 does not see a count inside brackets)
                   facts: [['אל', v.to || '—'], ['בתוקף עד', (j.envelope && whenFullHe(j.envelope.expires_at)) || '—']] });
  loadLinks(d); linksChanged();
}
/** «הפק ושלח לחתימה» from a draft: one question, the draft issued — a signature is on a document that no longer
 *  changes — and then «מילוי וחתימה» opens on it, the office's one signing link for every side (DGO-2139). */
async function issueThenFill(d) {
  if (!await binaAsk({ title: 'להפיק ולשלוח לחתימה?', ok: 'הפקה והמשך לחתימה',
      body: 'המסמך יקבל מספר וייחתם דיגיטלית, ולא ייערך עוד — הלקוח חותם על מה שהופק. אחר כך נפתח «מילוי וחתימה».',
      facts: [['מסמך', docTitle(d)]] })) return;
  const r = await api('/documents/' + encodeURIComponent(d.id) + '/issue', { method: 'POST', headers: { 'Content-Type': 'application/json' } }).catch(binaNoAnswer);
  const nd = await r.json().catch(() => ({}));
  if (!r.ok) return binaTell(nd.message || 'ההפקה נכשלה', 'bad', { more: binaSaid(r.status) });
  binaTell('הופק ' + (nd.doc_number || ''));
  await openDoc(d.id);
  refreshView();
  if (window.FillEditor) FillEditor.open(Object.assign({}, d, nd));
}

// ── document drawer ─────────────────────────────────────────
// THE DRAWER OPENS AT ONCE (DGO-2169, the owner: «אני לוחץ על פריט ולא ברור מה קורה»). It waited for the document,
// then its preview, then its signing state, then its events — one after another, four or five calls — and only then
// showed anything, so a click looked like nothing. Now the drawer and its address come first, every part with a
// placeholder; the document, its preview and its events are asked for together; and only the LATEST open draws:
// two quick clicks drew one document's buttons over the other's page (the code audit, A.3).
let _openSeq = 0;
/** `replace`: the drawer takes the current entry's place (the editor that made the document), not a new one. */
async function openDoc(id, replace) {
  const seq = ++_openSeq, live = () => seq === _openSeq;
  $('#dNum').textContent = '…'; $('#dStatus').className = 'chip'; $('#dStatus').textContent = 'נטען';
  $('#dConv').textContent = ''; $('#dSign').textContent = ''; $('#dSign').className = 'chip'; $('#dSign').title = '';
  $('#dHead').innerHTML = '<div class="lst-sk dp-sk" aria-label="טוען"><div></div><div></div></div>';
  $('#dNext').innerHTML = ''; $('#dActions').innerHTML = ''; $('#dMore').hidden = true;
  $('#dEvents').innerHTML = '<p class="muted">טוען…</p>';
  if (window.DocList) DocList.mark(id);            // the list marks the row it opened
  // the previous document's links and «מילוי וחתימה» rows go too, and their boxes are THIS document's at once: their
  // «סגירת הקישור» stayed live in the next drawer while it loaded, and a late answer of theirs drew into it (the reader)
  const links = $('#dLinks'); if (links) { links.innerHTML = ''; links.dataset.doc = id; }
  const fill = document.querySelector('#drawer .fe-st'); if (fill) { fill.innerHTML = ''; fill.setAttribute('data-doc', id); }
  const fr = $('#dPdf');
  fr.onload = () => fitDrawer();
  fr.srcdoc = '<p style="font:14px sans-serif;padding:24px" dir="rtl">טוען את המסמך…</p>';
  $('#overlay').classList.remove('hidden'); $('#drawer').classList.remove('hidden');
  setSplit();                                      // beside the list on a wide screen
  showRoute('doc/' + encodeURIComponent(id), replace === true);
  // the document itself, as its house HTML — a look is not a download: it uses up no «מקור» (it did, DGO-2029:
  // opening the drawer downloaded the PDF, and an invoice's original was spent on a glance)
  const [d, pv, evs] = await Promise.all([
    read('/documents/' + id),
    api('/documents/' + id + '/preview?fonts=api/docGen/house/fonts/').catch(binaNoAnswer),
    read('/documents/' + id + '/events')]);
  if (!live()) return;
  if (!d) {
    $('#dNum').textContent = 'המסמך לא נטען'; $('#dStatus').textContent = '';
    $('#dHead').innerHTML = '';
    $('#dNext').innerHTML = '<div class="dp-next"><p>המסמך לא נטען. נסו לפתוח אותו שוב מהרשימה.</p></div>';
    $('#dEvents').innerHTML = '';
    fr.srcdoc = '<p style="font:14px sans-serif;padding:24px" dir="rtl">המסמך לא נטען.</p>';
    return;
  }
  $('#dNum').textContent = d.doc_number || '';     // a draft has none yet: the head under it names its type
  $('#dStatus').className = 'chip ' + d.status; $('#dStatus').textContent = STATUS_HE[d.status] || d.status;
  $('#dConv').textContent = d.converted_from ? 'הומר מ־' + d.converted_from : '';
  // the head: what it is, for whom, how much — the three things a person looks for first
  $('#dHead').innerHTML = `<span class="dp-k">${esc(TYPE_HE[d.doc_type] || d.doc_type)}` +
    `${d.doc_number ? ' <span class="num">' + esc(d.doc_number) + '</span>' : ''}${d.doc_date ? ' · <span class="num">' + esc(d.doc_date) + '</span>' : ''}</span>` +
    `<h2 class="dp-cust" id="dCust">${esc(d.customer_name || '—')}</h2>` +
    (d.total != null ? `<div class="dp-sum"><span class="dp-big num">₪${money(d.total)}</span></div>` : '');
  const page = pv.ok ? await pv.text() : `<p style="font:14px sans-serif;padding:24px" dir="rtl">התצוגה לא נטענה — ${binaSaid(pv.status)}</p>`;
  if (!live()) return;
  fr.srcdoc = page;
  let env = null, fillEvents = null;
  if (SIGNABLE.has(d.doc_type) && !['draft', 'cancelled'].includes(d.status)) {
    // the one-signer envelopes and the «מילוי וחתימה» links, together: the next step reads both (the reader of
    // DGO-2169: it read the old envelopes alone, and a proposal every side signed by «מילוי וחתימה» still said
    // «שליחה לחתימה»). A «מילוי וחתימה» that does not answer is said by its own box; the step reads none
    const [s, f] = await Promise.all([read('/sign/' + id),
      fetch('api/fill/' + encodeURIComponent(id)).then(r => r.json()).catch(() => null)]);
    if (!live()) return;
    fillEvents = f && f.ok !== false && Array.isArray(f.events) ? f.events : null;
    // a signed envelope first: a later link that was never used must not hide the signature the deal has
    env = s && s.envelopes && (s.envelopes.find(e => e.status === 'signed') || s.envelopes[0]);
    if (env) {
      const signed = env.status === 'signed';
      $('#dSign').className = 'chip ' + (signed ? 'paid' : 'sent');
      $('#dSign').textContent = signed ? 'נחתם' : env.status === 'opened' ? 'נפתח · ממתין לחתימה' : 'ממתין לחתימה';
      $('#dSign').title = (env.signer_name || '') + (env.signed_at ? ' · ' + whenFullHe(env.signed_at) : '');
    }
  }
  // WHERE IT STANDS AND WHAT COMES NEXT (doc-panel.js): one sentence, its step as the main button; every other act
  // one row below, under «עוד פעולות» — never ten buttons of one weight
  // the step and the timeline are drawn now, and again once the links are here: a link sent is a step taken (the
  // reader: an invoice sent by a view link still said «השלב הבא: לשלוח»)
  const draw = links => {
    const ctx = panelCtx(env, fillEvents, links);
    $('#dEvents').innerHTML = DocPanel.timeline(evs, links, ctx);
    // an act in flight keeps its buttons as they are: redrawn, a disabled «סימון כשולם» came back live and a second
    // click posted /pay twice (the reader). The next opening of the document draws them fresh
    if (links && $('#drawer').querySelector('#dNext [data-act]:disabled, #dActions [data-act]:disabled, [data-act].is-loading')) return;
    const nx = DocPanel.next(d, ctx);
    $('#dNext').innerHTML = nx.html;
    const rest = actions(d, env, nx.acts);
    const wasOpen = links ? $('#dMore').open : !nx.acts.length;   // a redraw keeps «עוד פעולות» as the owner left it
    $('#dActions').innerHTML = rest; $('#dMore').hidden = !rest; $('#dMore').open = wasOpen;
    $('#drawer').querySelectorAll('#dNext [data-act], #dActions [data-act]').forEach(b => b.onclick = () => act(id, b.dataset.act, b, d, env));
  };
  draw(null);
  if (window.FillEditor) FillEditor.status(d);   // each side's state of the document's «מילוי וחתימה» links (DGO-2139)
  loadLinks(d).then(rows => { if (live() && rows) draw(rows); });
  fitDrawer();   // the drawer is shown already: its sheet fits its pane once both are there (DGO-2042)
}
/** What doc-panel.js needs to say a document: the app's own names and rules, Israel's clock, and what was read. */
function panelCtx(env, fill, links) {
  return { esc, typeHe: t => TYPE_HE[t] || '', when: whenFullHe, detail: evDetail, env, fill, links, mayIssue,
           conversions: CONVERSIONS, isCredit, signable: SIGNABLE, books: BOOKS, eventHe: EVENT_HE, now: new Date() };
}
/** A WIDE SCREEN PUTS THE DOCUMENT BESIDE THE LIST (style.css `body.split`, DGO-2169): no overlay, the list keeps its
 *  clicks. Decided by the width and by whether a document is open — and never under the editor, which is modal. */
// (1280px: from 1200 a dashboard beside the drawer had 580px for its 643px — the reader)
const WIDE = window.matchMedia ? matchMedia('(min-width:1280px)') : { matches: false };
function setSplit() {
  // the bar's HEIGHT: in split it stays at the top (sticky), and the drawer starts under it — never its place in the
  // window, which a scrolled list made negative (the reader)
  const bar = document.querySelector('.side');
  if (bar) document.documentElement.style.setProperty('--bar-h', bar.offsetHeight + 'px');
  const open = !$('#drawer').classList.contains('hidden');
  document.body.classList.toggle('split', WIDE.matches && open && $('#editor').classList.contains('hidden'));
  if (open) fitDrawer();                           // in split or out of it, the sheet fits its new pane
}
let _splitFrame = 0;
window.addEventListener('resize', () => { cancelAnimationFrame(_splitFrame); _splitFrame = requestAnimationFrame(setSplit); });
/** From a list beside an open document, another row takes the open one's place: one entry, ✕ goes back to the list. */
const openFromList = id => openDoc(id, document.body.classList.contains('split') && routeOf().startsWith('doc/'));
/** The drawer's sheet, scaled to its pane like the editor's. */
function fitDrawer() {
  const fr = $('#dPdf'), box = $('#dPdfBox');
  // a page committed but not parsed yet has no root: return, its own onload fits it — and openDoc goes on to its
  // route (it threw here, and the address never named the document — DGO-2156)
  if (!fr || !box || !fr.contentDocument || !fr.contentDocument.documentElement) return;
  // the frame can load before openDoc shows the drawer (it awaits two more calls first): a hidden box is 0px wide, and
  // its fit was a negative scale and a 0px page — every drawer blank on the live HP (DGO-2042). Not now: openDoc
  // fits again once the drawer is shown
  if (box.clientWidth <= 8) return;
  const w = 860, s = Math.min(1, (box.clientWidth - 8) / w), h = fr.contentDocument.documentElement.scrollHeight;
  fr.style.width = w + 'px'; fr.style.height = h + 'px'; fr.style.transform = 'scale(' + s + ')';
  box.style.setProperty('--pv-h', Math.ceil(h * s) + 'px');
}
function closeDrawer(keepRoute) {
  _openSeq++;                                      // a document still loading draws nothing into a closed drawer
  if (window.DocList) DocList.mark(null);          // and the list marks no row (the reader: it kept the closed one)
  $('#overlay').classList.add('hidden'); $('#drawer').classList.add('hidden');
  setSplit();
  if (keepRoute === true) return;                  // (a click passes an event: not «keep»)
  if (routeOf().startsWith('doc/')) leaveTo(filter.view || 'dash'); else showRoute(filter.view || 'dash', true);
}
/** A credit note — or one from before it had a type (an INVOICE in series CN, negative) — is the correction itself: it
 *  is not cancelled, paid or carried on (DGO-2029, the second reader); store.py's is_credit says the same. One rule,
 *  for the acts and for «הצעד הבא» alike (the reader of DGO-2169: the step offered «סימון כשולם» on an old credit). */
const isCredit = d => d.doc_type === 'CREDIT_NOTE' || !!d.cancels
  || (d.doc_type === 'INVOICE' && d.series === 'CN' && Number(d.total) < 0);
/** Every act the document takes, the primary first — less `skip`, the ones «הצעד הבא» already shows. */
function actions(d, env, skip) {
  // one family: the primary act first, the rest ghost, the destructive one last
  const b = [];
  const live = !['draft', 'cancelled'].includes(d.status);
  const credit = isCredit(d);                      // (the one rule, above)
  // a draft is written on (DGO-2047): «עריכה» opens it in the editor, and its link is the way back to it
  if (d.status === 'draft') {
    b.push(['edit', 'עריכה', 'primary', 'פתיחת הטיוטה בעורך — היא נשמרת במקומה']);
    b.push(['issue', 'הפק מסמך', 'ghost', 'מקבל מספר ונחתם דיגיטלית — לא ניתן לערוך אחרי']);
    if (SIGNABLE.has(d.doc_type)) b.push(['issuefill', icon('send') + ' הפק ושלח לחתימה', 'ghost', 'מפיק את המסמך ופותח «מילוי וחתימה» — קישור אחד לכל הצדדים']);
    b.push(['editlink', 'קישור לעריכה', 'ghost', 'הקישור שפותח את הטיוטה הזאת בעורך, בלשכה']);
  }
  // every side signs on one link — also a document an old one-signer link already closed (DGO-2139)
  if (live && SIGNABLE.has(d.doc_type))
    b.push(['fill', icon('send') + ' מילוי וחתימה', b.length ? 'ghost' : 'primary', 'קישור אחד לכל הצדדים: כל אחד בוחר את הצד שלו, ממלא וחותם (DGO-2139)']);
  if (d.status !== 'cancelled') b.push(['share', 'קישור לצפייה', 'ghost', 'קישור שהלקוח פותח בלי כניסה: רואה את המסמך ומוריד אותו']);
  if (env && env.status === 'signed') b.push(['signed:' + env.id, icon('download') + ' העותק החתום', 'ghost', 'המסמך, החתימה ותעודת החתימה']);
  b.push(['download', icon('download') + ' PDF', 'ghost',
          BOOKS.has(d.doc_type) && live ? 'ההורדה הראשונה היא ה«מקור»; כל הורדה אחריה — «העתק»' : 'הורדת המסמך']);
  // each mark only while it still says something: «סימון כנשלח» on an issued document, «סימון כשולם» until it is paid —
  // both stayed after they were done, and the ledger takes a second pay on a paid document (the code audit, A.9)
  if (d.status === 'issued' && !SIGNABLE.has(d.doc_type)) b.push(['send', icon('send') + ' סימון כנשלח', 'ghost', 'רושם ביומן שהמסמך נשלח ולמי']);
  if (live && d.status !== 'paid' && !credit && ['INVOICE', 'PAYMENT_REQUEST', 'INVOICE_RECEIPT'].includes(d.doc_type)) b.push(['pay', icon('tick') + ' סימון כשולם', 'ghost', 'רושם ביומן שהכסף התקבל']);
  // the deal's next step — what this document becomes, in the order the deal goes
  if (live && !credit)              // a draft is issued first: what follows names its number
    for (const t of (CONVERSIONS[d.doc_type] || []).filter(mayIssue)) b.push(['convert:' + t, 'המשך: ' + TYPE_HE[t], 'ghost', 'טיוטה חדשה מהמסמך הזה']);
  if (live && !credit)
    b.push(['cancel', icon('ban') + ' ביטול', 'ghost danger-t', CREDITED.has(d.doc_type) ? 'תופק חשבונית זיכוי' : 'המסמך יסומן כמבוטל — הוא נשמר ואינו נמחק']);
  // under «עוד פעולות» every act is of one weight: the next step's main button is the only primary
  return b.filter(([a]) => !(skip || []).includes(a))
    .map(([a, l, c, t]) => `<button class="${skip ? (/danger/.test(c) ? 'ghost danger-t' : 'ghost') : c} sm" data-act="${a}" title="${esc(t || '')}">${l}</button>`).join('');
}
async function act(id, a, btn, d, env) {
  if (a === 'fill') return window.FillEditor && FillEditor.open(d);   // «מילוי וחתימה» (DGO-2139): fill-editor.js
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
    openDoc(id); refreshView();
  });
  // the living document's acts (DGO-2047): write the draft on, its edit link, a view link, and a draft to signing
  if (a === 'edit') { closeDrawer(true); return openEditor(d.doc_type, d); }
  if (a === 'editlink') return copyLink('הקישור לעריכה', linkTo('doc/' + encodeURIComponent(id) + '/edit'),
    'הקישור פותח את הטיוטה הזאת בעורך, בלשכה — למי שנכנס אליה. ללקוח שולחים «קישור לצפייה» או «מילוי וחתימה».');
  if (a === 'share') return guard(btn, () => shareDoc(d));
  if (a === 'issuefill') return guard(btn, () => issueThenFill(d));
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
      refreshView();
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
      // it RECORDS a send; it sends nothing — the dialog said «שליחה ללקוח» with a «שליחה» button (the code audit, C)
      const to = await binaAsk({ title: 'סימון כנשלח', ok: 'סימון',
        body: 'נרשם ביומן שהמסמך נשלח, ואל מי. מכאן הוא לא נשלח — לשליחה ללקוח יש «קישור לצפייה».',
        input: { label: 'אל מי נשלח — דוא״ל או שם', dir: 'auto' } });
      if (to == null) return;
      opt.body = JSON.stringify({ to });
    }
    // issuing is final — a number and a digital signature: asked first, here as in the editor (the reader of DGO-2169:
    // «הפקה» became the one main button of a draft, and one click issued it)
    if (a === 'issue' && !await binaAsk({ title: 'להפיק את המסמך?', ok: 'הפקה',
        body: 'המסמך יקבל מספר וייחתם דיגיטלית. אחרי ההפקה הוא אינו נערך עוד.',
        facts: [['מסמך', TYPE_HE[d.doc_type] || d.doc_type], ['לקוח', d.customer_name || '—']] })) return;
    const r = await api(`/documents/${id}/${a}`, opt).catch(binaNoAnswer);
    const res = await r.json().catch(() => ({}));
    if (r.status >= 400 || !r.ok) return binaTell(res.message || 'הפעולה נכשלה', 'bad', { more: binaSaid(r.status) });
    binaTell({ issue: 'הופק ' + (res.doc_number || ''), send: 'נרשם כנשלח', pay: 'סומן כשולם',
               cancel: res.credit_document ? 'בוטל · הופקה חשבונית זיכוי ' + (res.credit_document.doc_number || '') : 'המסמך סומן כמבוטל' }[a] || 'בוצע');
    openDoc(id); refreshView();
  });
}

// ── boot ────────────────────────────────────────────────────
DOC_EDITOR_HTML = $('#editor').innerHTML;   // capture before any entity-editor swap
document.querySelectorAll('.side nav a').forEach(a => a.onclick = e => { e.preventDefault(); show(a.dataset.view); });
$('#newBtn').onclick = () => openEditor();
$('#closeDrawer').onclick = closeDrawer;
// a tap outside: the editor asks before it drops what was typed (the second reader of DGO-2047, A.11)
$('#overlay').onclick = () => { if (!$('#editor').classList.contains('hidden')) leaveEditor(); else closeDrawer(); };
// Escape closes what is open — a dialog of its own closes itself first (it stops the key)
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || e.defaultPrevented || document.querySelector('.lcard-scrim, .fe-scrim, .bask, [aria-modal="true"]')) return;
  if (!$('#editor').classList.contains('hidden')) leaveEditor();
  else if (!$('#drawer').classList.contains('hidden')) closeDrawer();
});
$('#addCust').onclick = () => editEntity('customers');
$('#addItem').onclick = () => editEntity('items');
// ⌘S / Ctrl-S saves the draft being written again where it is (DGO-2047) — never the browser's «save page»
document.addEventListener('keydown', e => {
  // the KEY, not its letter: on the Hebrew layout S is «ד», and «ס» is X — ⌘X saved and its cut was lost (the reader)
  // (a Latin «s» wherever the layout puts it — Dvorak's is not on KeyS; on a layout without Latin letters, the S key)
  const isS = (e.key || '').toLowerCase() === 's' || (e.code === 'KeyS' && !/^[a-z]$/i.test(e.key || ''));
  if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && isS && EDIT_DOC && DOC_TYPE) { e.preventDefault(); save(false); }
});

api('/me').then(r => r.json()).then(u => { $('#userBox').innerHTML = `מחובר/ת<br><b>${esc(u.name)}</b>`; }).catch(() => {});

// (a function of its own, not one run in place: the notice's «נסה שוב» starts the screen again)
async function start() {
  const biz = await loadBiz();
  if (biz && !biz.onboarded) { openOnboarding(); }
  show(filter.view || 'dash');
}
applyRoute();   // …and then the URL decides (a deep link lands on its view or its document)
start();
