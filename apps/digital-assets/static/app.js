/* digital-assets — נכסים דיגיטליים. Vanilla JS, relative URLs only (the console serves the app at
 * /a/digital-assets/ and injects the base).
 *
 * Routes (every screen is a URL; a drawer is `?slot=` / `?post=` / `?bp=` / `?ch=` on top of it):
 *   #/                 overview — the identity at a glance, the channels, what waits for the owner
 *   #/s/identity       identification slots, grouped      #/s/content   content slots
 *   #/media            the media timeline (phases → units), `#/media/gallery`, `#/media/posts`
 *   #/channels         where the business appears, and which account/site each one is
 *   #/blueprints       ready-made slot sets               #/activity    what changed, by whom
 *
 * The one flow the app is built around: a slot's drawer → add a version → "make active" → the PLAN
 * (every channel, what will happen there and why) → publish → each channel's delivery, live.
 */
'use strict';

/* ── the console bridge ──────────────────────────────────────────────────────────────────────
 * Inside the console this app lives at /a/<alias>/, and the shell's address bar carries the app's
 * inner route (#/m/<alias>/matrix?connect=x). The shell hands that route over as a PATH — the frame
 * loads /a/<alias>/matrix?connect=x — and mirrors whatever route the app reports (`bina:route`).
 * This app routes by hash, so a path on arrival becomes the hash, and every route is reported back
 * as a path: the console URL is always a deep link that reopens this exact screen. */
const MOUNT = (() => {
  try { const p = new URL(document.baseURI).pathname; return p.endsWith('/') ? p : p.replace(/[^/]*$/, ''); }
  catch (e) { return '/'; }
})();
(function adoptPathRoute() {
  const rest = location.pathname.startsWith(MOUNT) ? location.pathname.slice(MOUNT.length) : '';
  if ((rest && rest !== 'index.html') || location.search) {
    history.replaceState(null, '', MOUNT + '#/' + rest + location.search);
  }
})();
function reportRoute() {
  if (window.parent === window) return;
  const inner = location.hash.replace(/^#/, '') || '/';
  try { window.parent.postMessage({ type: 'bina:route', path: inner.startsWith('/') ? inner : '/' + inner }, location.origin); }
  catch (e) { /* an opaque parent — nothing to mirror */ }
}

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const S = { ov: null, route: '', query: {}, slotCache: {}, drawerKey: null };

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
async function api(path, opts) {
  const o = Object.assign({ headers: { 'content-type': 'application/json' } }, opts || {});
  if (o.body instanceof FormData) delete o.headers;
  const r = await fetch(path, o).catch(binaNoAnswer);
  // a body that is not data is the sign-in page or the edge's own error page: named by its status
  let body = await r.json().catch(() => ({ error: binaSaid(r.status) })) || {};
  if (!r.ok && !body.error && !body.detail) body = Object.assign({}, body, { error: binaSaid(r.status) });
  return { ok: r.ok, status: r.status, body };
}
const post = (p, b) => api(p, { method: 'POST', body: JSON.stringify(b || {}) });
const put = (p, b) => api(p, { method: 'PUT', body: JSON.stringify(b || {}) });

/* ── icons (Feather, one path each) ────────────────────────────────────────────────────────── */
const ICONS = {
  home: 'M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z',
  id: 'M3 5h18v14H3zM7 9h4M7 13h6M15 10a2 2 0 1 0 4 0 2 2 0 0 0-4 0M14 16c.5-1.5 5.5-1.5 6 0',
  text: 'M4 7V4h16v3M9 20h6M12 4v16',
  image: 'M3 5h18v14H3zM8.5 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3M21 15l-5-5L5 19',
  share: 'M18 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6M6 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6M18 22a3 3 0 1 0 0-6 3 3 0 0 0 0 6M8.6 13.5l6.8 4M15.4 6.5l-6.8 4',
  layers: 'M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5',
  activity: 'M3 12h4l2-5 4 10 2-5h6',
  plus: 'M12 5v14M5 12h14',
  check: 'M20 6 9 17l-5-5',
  x: 'M18 6 6 18M6 6l12 12',
  send: 'M22 2 11 13M22 2l-7 20-4-9-9-4z',
  upload: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12',
  link: 'M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7',
  copy: 'M9 9h11v11H9zM5 15H4V4h11v1',
  refresh: 'M23 4v6h-6M1 20v-6h6M3.5 9a9 9 0 0 1 14.9-3.4L23 10M1 14l4.6 4.4A9 9 0 0 0 20.5 15',
  calendar: 'M3 4h18v18H3zM16 2v4M8 2v4M3 10h18',
  star: 'M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z',
  external: 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3',
  download: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3',
  archive: 'M21 8v13H3V8M1 3h22v5H1zM10 12h4',
  search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16M21 21l-4.3-4.3',
};
const ic = (n) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${ICONS[n] || ''}"/></svg>`;

/* ── the vocabulary: every enum the server sends has a Hebrew label here, the key in the title ── */
const SECTION_HE = { identity: 'זיהוי', content: 'תוכן', media: 'מדיה' };
const KIND_HE = { text: 'טקסט', richtext: 'טקסט ארוך', image: 'תמונה', video: 'וידאו', animation: 'אנימציה',
  file: 'קובץ', document: 'מסמך', color: 'צבע', palette: 'פלטה', link: 'קישור', handle: 'שם משתמש',
  list: 'רשימה', 'price-list': 'מחירון', hours: 'שעות', address: 'כתובת', phone: 'טלפון', email: 'דוא״ל',
  set: 'סט מדיה', page: 'עמוד', thread: 'שרשור', email_msg: 'דוא״ל', livestream: 'שידור חי' };
const FILE_KINDS = new Set(['image', 'video', 'animation', 'file', 'document']);
const STATE_HE = { planned: 'מתוכנן', queued: 'בתור', running: 'רץ', ok: 'בוצע',
  needs_owner: 'ממתין לך', failed: 'נכשל', skipped: 'דולג', partial: 'חלקי', done: 'הושלם' };
const STATE_CLS = { queued: '', running: 'run', ok: 'ok', done: 'ok', needs_owner: 'owner',
  failed: 'bad', partial: 'run', skipped: 'plain' };
const ACTION_HE = { push: 'אוטומטי', manual: 'ידני', live: 'מיידי', skip: 'לא ישתנה' };
const ACTION_CLS = { push: '', manual: 'owner', live: 'ok', skip: 'plain' };
const SOURCE_HE = { upload: 'הועלה', agent: 'נוצר ע״י עזריה', import: 'יובא', url: 'מקישור' };
const KINDCH_HE = { social: 'רשת חברתית', website: 'אתר', listing: 'רישום', print: 'דפוס ומסמכים' };
const GROUP_HE = { logo: 'לוגו', name: 'שמות', names: 'שמות', legal: 'פרטים משפטיים', contact: 'יצירת קשר',
  hours: 'שעות פעילות', description: 'תיאורים', color: 'צבעים', theme: 'עיצוב', illustration: 'איור וסגנון',
  profile: 'פרופילים ברשתות', listing: 'רישומים ומדריכים', slug: 'מזהה', domain: 'דומיין', tagline: 'סלוגן',
  terminology: 'מונחים', 'opening-date': 'תאריך פתיחה', product: 'המוצר', handles: 'שמות משתמש', voice: 'קול וטון',
  press: 'עיתונות', people: 'אנשים', about: 'אודות', catalog: 'קטלוג ומחירים', faq: 'שאלות ותשובות',
  website: 'אתר', docs: 'מסמכים ותיעוד', reviews: 'ביקורות', gbp: 'פרופיל Google', newsletter: 'ניוזלטר',
  whatsapp: 'וואטסאפ', news: 'חדשות', vision: 'חזון', 'app-store': 'חנות האפליקציות', releases: 'גרסאות',
  community: 'קהילה', menu: 'תפריטים', kosher: 'כשרות', license: 'רישוי', signage: 'שילוט', table: 'שולחן',
  delivery: 'משלוחים', reservations: 'הזמנת מקומות', events: 'אירועים', specials: 'מנות היום',
  catering: 'קייטרינג', restaurant: 'המסעדה', links: 'קישורים', photo: 'צילומים', image: 'תמונות',
  video: 'וידאו', food: 'צילומי אוכל', inbox: 'לא משובץ', calendar: 'לוח שנה' };
const grpHe = (g) => GROUP_HE[g] || g || 'כללי';
const lbl = (o) => (o && (o.he || o.en)) || '';
const fmtDate = (iso) => { if (!iso) return ''; const [y, m, d] = String(iso).split('-'); return `${d}.${m}.${String(y).slice(2)}`; };
const fmtAgo = (ts) => {
  if (!ts) return '';
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return 'עכשיו';
  if (s < 3600) return `לפני ${Math.round(s / 60)} דק׳`;
  if (s < 86400) return `לפני ${Math.round(s / 3600)} שע׳`;
  return `לפני ${Math.round(s / 86400)} ימים`;
};
const chip = (text, cls, title) => `<span class="chip ${cls || ''}" ${title ? `title="${esc(title)}"` : ''}>${esc(text)}</span>`;
const stateChip = (st) => chip(STATE_HE[st] || st, STATE_CLS[st] || '', st);

/* (the one notice channel is the office's: `binaTell`, in the copied block above) */
async function busy(btn, fn) {
  if (!btn) return fn();
  const html = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="spin"></span>${esc(btn.textContent.trim())}`;
  try { return await fn(); } finally { btn.disabled = false; btn.innerHTML = html; }
}
const errText = (b) => (b && (b.error || b.message)) || 'הפעולה נכשלה';

/* ── routing ───────────────────────────────────────────────────────────────────────────────── */
function parseHash() {
  const h = location.hash.replace(/^#/, '') || '/';
  const [path, qs] = h.split('?');
  const query = {};
  (qs || '').split('&').filter(Boolean).forEach((kv) => {
    const [k, v] = kv.split('=');
    query[decodeURIComponent(k)] = decodeURIComponent(v || '');
  });
  return { path: path || '/', query };
}
function go(path, query) {
  const qs = Object.entries(query || {}).filter(([, v]) => v != null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&');
  location.hash = path + (qs ? '?' + qs : '');
}
function withQuery(extra) {
  const { path, query } = parseHash();
  const q = Object.assign({}, query, extra);
  Object.keys(q).forEach((k) => { if (q[k] == null || q[k] === '') delete q[k]; });
  go(path, q);
}
window.addEventListener('hashchange', route);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && $('drawer-root').innerHTML) closeDrawer(); });

const MENU = [
  { path: '/', label: 'סקירה', icon: 'home' },
  { path: '/s/identity', label: 'זיהוי', icon: 'id', count: 'identity' },
  { path: '/s/content', label: 'תוכן', icon: 'text', count: 'content' },
  { path: '/media', label: 'מדיה', icon: 'image', count: 'media' },
  { path: '/channels', label: 'ערוצים', icon: 'share', count: 'channels' },
  { path: '/blueprints', label: 'תבניות', icon: 'layers' },
  { path: '/activity', label: 'פעילות', icon: 'activity' },
];
/* The menu is the office's shared component (BinaNav, spliced into index.html by gate G27): this
 * app DECLARES its rows. A section's fill is the row's second column, what waits for the owner is
 * its pill; the rail, the drawer on a phone and the active tint are the component's. */
let NAV = null;
function mountNav() {
  if (NAV || typeof BinaNav === 'undefined') return NAV;
  NAV = BinaNav.mount($('sideNav'), {
    id: 'digital-assets',
    brand: { name: 'נכסים דיגיטליים', avatar: 'נ' },
    sections: [{ id: 'pages', items: MENU.map((m) => ({ id: m.path, label: m.label, icon: m.icon, href: '#' + m.path, title: m.label })) }],
  });
  const t = $('navToggle');
  if (NAV && t && !t.innerHTML.trim()) t.innerHTML = BinaNav.svg('menu');
  return NAV;
}
function renderMenu(active) {
  const nav = mountNav();
  if (!nav) return;
  const ov = S.ov || {};
  const secs = ov.sections || {};
  for (const m of MENU) {
    if (secs[m.count]) nav.setMeta(m.path, `${secs[m.count].filled}/${secs[m.count].slots}`);
    else if (m.count === 'channels' && ov.channels) {
      const core = ov.channels.filter((c) => c.core);
      nav.setMeta(m.path, `${core.filter((c) => c.bound).length}/${core.length}`);
    }
  }
  nav.setBadge('/', (ov.pending || []).length ? String(ov.pending.length) : '');
  const on = MENU.find((m) => m.path !== '/' && active.startsWith(m.path));
  nav.setActive(on ? on.path : '/');
  if (nav.isOpen()) nav.close();
}

async function loadOverview() {
  const r = await api('api/overview');
  if (r.ok) S.ov = r.body;
  return r;
}

async function route() {
  if (!S.ov) await loadOverview();
  const { path, query } = parseHash();
  S.route = path;
  S.query = query;
  renderMenu(path);
  const view = $('view');
  const same = view.dataset.path === path;
  if (!same) view.innerHTML = '<div class="skel"></div><div class="skel"></div><div class="skel"></div>';
  view.dataset.path = path;
  $('actions').innerHTML = '';
  try {
    if (path === '/') await pageOverview();
    else if (path.startsWith('/s/')) await pageSection(path.split('/')[2]);
    else if (path.startsWith('/media')) await pageMedia(path.split('/')[2] || 'timeline');
    else if (path === '/channels') await pageChannels();
    else if (path === '/blueprints') await pageBlueprints();
    else if (path === '/activity') await pageActivity();
    else view.innerHTML = '<div class="empty">אין עמוד כזה.</div>';
  } catch (e) {
    view.innerHTML = `<div class="issue">העמוד לא נטען: ${esc(e.message || e)}</div>`;
  }
  renderMenu(path);
  syncDrawer(query);
  reportRoute();
}

function header(title, sub, actions) {
  $('title').textContent = title;
  $('sub').textContent = sub;
  $('actions').innerHTML = actions || '';
}

/* ── overview ─────────────────────────────────────────────────────────────────────────────── */
async function pageOverview() {
  const r = await loadOverview();
  header('נכסים דיגיטליים', 'כל מה שהעסק מציג לעולם — זהות, תוכן ומדיה — במקום אחד, ומשם לכל ערוץ.',
    `<button class="btn sm ghost" id="b-refresh" title="טען מחדש את כל הנתונים">${ic('refresh')}רענון</button>`);
  $('b-refresh').onclick = () => route();
  if (!r.ok) { $('view').innerHTML = `<div class="issue">${esc(errText(r.body))}</div>`; return; }
  const ov = r.body;
  const secs = ov.sections || {};
  const anyApplied = (ov.blueprints || []).some((b) => b.applied);
  const core = (ov.channels || []).filter((c) => c.core);
  const bound = core.filter((c) => c.bound).length;
  const cell = (k, v, sub, pct, href, cls) => `<button class="cell" onclick="location.hash='${href}'" title="${esc(k)}">
      <div class="k">${esc(k)}</div><div class="v ${cls || ''}">${v}${sub ? ` <small>${sub}</small>` : ''}</div>
      ${pct != null ? `<div class="bar"><i style="width:${Math.round(pct)}%"></i></div>` : ''}</button>`;
  const secCell = (key) => {
    const s = secs[key] || { slots: 0, filled: 0, required: 0, required_filled: 0 };
    return cell(SECTION_HE[key], `${s.filled}`, `מתוך ${s.slots}`,
      s.slots ? (100 * s.filled / s.slots) : 0, `#/${key === 'media' ? 'media' : 's/' + key}`);
  };
  const waiting = (ov.pending || []).length;
  let html = `<div class="strip">
    ${secCell('identity')}${secCell('content')}${secCell('media')}
    ${cell('ערוצים מחוברים', `${bound}`, `מתוך ${core.length}`, core.length ? 100 * bound / core.length : 0, '#/channels')}
    ${cell('ממתין לך', `${waiting}`, waiting ? 'פעולות' : 'אין', null, '#/?pending=1', waiting ? 'owner' : 'ok')}
  </div>`;
  if (!anyApplied) {
    html += `<div class="issue info"><b>מתחילים מתבנית.</b> תבנית יוצרת בבת אחת את כל המשבצות שעסק מהסוג שלכם צריך —
      „עסק בסיסי”, „מסעדה” או „זנב סטארט־אפ” (סדרת המדיה של מוצר צעיר, מתוך מחקר על umbrelOS, n8n ו-Notion).
      <div style="margin-top:8px"><a class="btn sm primary" href="#/blueprints">${ic('layers')}בחירת תבנית</a></div></div>`;
  }
  html += `<div class="cards">
    <div class="card" id="c-brand"><h3>הזהות הפעילה <span class="hint">מה שכל ערוץ מציג עכשיו</span></h3>${brandCard(ov)}</div>
    <div class="card"><h3>ערוצים <a class="btn sm ghost" href="#/channels">ניהול ערוצים</a></h3>${channelsMini(core)}</div>
    <div class="card"><h3>ממתין לך <span class="hint">עדכונים ידניים והרצות שמחכות לך</span></h3>${pendingList(ov.pending || [])}</div>
    <div class="card"><h3>הבא בציר הזמן <a class="btn sm ghost" href="#/media">כל ציר המדיה</a></h3>${upcomingList(ov)}</div>
    <div class="card"><h3>פעילות אחרונה <a class="btn sm ghost" href="#/activity">הכל</a></h3>${eventsList(ov.events || [])}</div>
  </div>`;
  if (ov.social_error) html = `<div class="issue">${esc(ov.social_error)} — חשבונות הרשתות לא נקראים עד שהוא עונה.</div>` + html;
  $('view').innerHTML = html;
  bindPendingActions();
}

function brandCard(ov) {
  // the brand at a glance — read from the slots, so a click goes straight to the slot's drawer
  const slots = S.slotCache.identity || [];
  const by = Object.fromEntries(slots.map((s) => [s.key, s]));
  if (!slots.length) {
    api('api/slots?section=identity').then((r) => {
      if (r.ok) { S.slotCache.identity = r.body.slots; const c = $('c-brand'); if (c) c.innerHTML = '<h3>הזהות הפעילה <span class="hint">מה שכל ערוץ מציג עכשיו</span></h3>' + brandCard(ov); }
    });
    return '<div class="skel"></div>';
  }
  const pick = (...keys) => keys.map((k) => by[k]).find((s) => s && s.active) || by[keys[0]];
  const logo = pick('identity.logo.square', 'identity.logo.primary');
  const name = pick('identity.name.brand-he', 'identity.product.name', 'identity.name.brand-en');
  const desc = pick('identity.description.short', 'identity.product.one-liner', 'identity.tagline');
  const colors = ['identity.color.primary', 'identity.color.secondary', 'identity.color.neutral']
    .map((k) => by[k] && by[k].active && by[k].active.text).filter(Boolean);
  const la = logo && logo.active;
  const mark = la && la.file ? `<img src="${esc(la.thumb)}" alt="${esc(lbl(logo.label))}">` : '<div class="empty-mark">אין עדיין לוגו</div>';
  return `<div class="brandline">
      <button class="mark" title="${esc(lbl(logo && logo.label) || 'לוגו')}" onclick="openSlot('${esc(logo ? logo.key : 'identity.logo.square')}')">${mark}</button>
      <div class="who">
        <div class="nm">${name && name.active ? esc(name.active.text) : '<span class="note">שם המותג טרם נקבע</span>'}</div>
        <div class="ds">${desc && desc.active ? esc(desc.active.text) : 'תיאור קצר טרם נקבע'}</div>
        <div class="swatches">${colors.map((c) => `<span class="swatch" style="background:${esc(c)}" title="${esc(c)}"></span>`).join('')}</div>
      </div></div>
    <div class="row" style="margin-top:12px">
      <button class="btn sm" onclick="openSlot('identity.logo.square')" title="החלפת הלוגו — ותכנית פרסום לכל הערוצים">${ic('image')}החלפת לוגו</button>
      <button class="btn sm ghost" onclick="openSlot('identity.name.brand-he')" title="שינוי שם המותג">שם</button>
      <button class="btn sm ghost" onclick="openSlot('identity.description.short')" title="שינוי התיאור הקצר">תיאור</button>
      <button class="btn sm ghost" onclick="openSlot('identity.slug')" title="המזהה ושמות המשתמש ברשתות">מזהה</button>
    </div>`;
}

function monoTile(c) {
  // A network's tile is the NETWORK's colour — its own mark, the one colour here that is not the
  // office's (gate G82 allows these by name). The business's own website is the office's olive.
  const colors = { facebook: '#1877f2', instagram: '#d62976', x: '#0f1419', youtube: '#ff0000', github: '#24292f',
    discord: '#5865f2', whatsapp: '#25d366', linkedin: '#0a66c2', tiktok: '#010101',
    telegram: '#229ed9', threads: '#000000', website: 'var(--olive)' };
  const letters = { facebook: 'f', instagram: 'i', x: 'X', youtube: 'YT', github: 'G', discord: 'D', whatsapp: 'W',
    website: 'www', linkedin: 'in', tiktok: 'T', telegram: 'TG', threads: '@' };
  const id = c.platform || c.id;
  return `<span class="mono-tile" style="background:${colors[id] || 'var(--muted)'};font-size:${(letters[id] || '').length > 2 ? 10 : 13}px">${esc(letters[id] || (lbl(c.label) || c.id).slice(0, 1))}</span>`;
}

function channelsMini(core) {
  if (!core.length) return '<div class="empty">אין ערוצים.</div>';
  return `<div class="chgrid" style="grid-template-columns:repeat(auto-fill,minmax(200px,1fr))">${core.map((c) => {
    const st = chState(c);
    return `<div class="ch" style="cursor:pointer" onclick="openChannel('${esc(c.id)}')" title="חיבור / החלפת החשבון">
      <div class="top">${monoTile(c)}<div style="min-width:0;flex:1"><div class="name">${esc(lbl(c.label))}</div>
      <div class="acct" dir="auto" title="${esc(st.who)}">${esc(st.who)}</div></div>${chip(st.he, st.cls, st.tip)}</div></div>`;
  }).join('')}</div>`;
}
// ONE reading of a channel's connection, for every place that draws it. A website is connected when
// a site is chosen; a network when its account can be named. A network that is bound while the
// networks' service gave no answer is neither — the binding is there, the account cannot be read
// now — and the tile used to say both ("מחובר" beside "לא מחובר"). `who` is a NAME (the site, the
// account) or nothing: a second line that only rewords the chip is cut to "לא מח…" on a narrow tile.
// What the chip cannot say in two words is its tooltip (`tip`).
function chState(c) {
  const acc = c.account;
  if (c.kind === 'website') return c.site_id ? { he: 'מחובר', cls: 'ok', who: `אתר: ${c.site_id}` } : { he: 'לא מחובר', cls: 'plain', who: '', tip: 'לא נבחר אתר' };
  if (acc) return { he: kindHe(acc.kind), cls: 'ok', who: accName(acc) + (acc.test ? ' · בדיקה' : '') };
  return c.bound ? { he: 'לא זמין כרגע', cls: 'plain', who: '', tip: 'החשבון מחובר — שירות הרשתות לא ענה' } : { he: 'לא מחובר', cls: 'plain', who: '' };
}
// an account's own name, without the network prefix the card already shows ("פייסבוק · Bina Solutions")
const accName = (acc) => ((acc.label || '').replace(/^[^·]*·\s*/, '') || acc.account_hint || '');
const kindHe = (k) => ({ api: 'API', browser: 'דפדפן הלשכה' }[k] || 'מחובר');

function pendingList(rows) {
  if (!rows.length) return '<div class="empty">אין מה לעשות כרגע — כל השינויים הגיעו ליעדם.</div>';
  return `<div class="plan">${rows.slice(0, 8).map((p) => `<div class="pi">
      ${stateChip(p.state)}
      <div style="min-width:0"><div class="c">${esc(p.slot_label)} ← ${esc(p.channel_label)}${p.field_label ? ` · ${esc(p.field_label)}` : ''}</div>
        <div class="w">${esc(pubWhy(p))}</div></div>
      <div class="row">${p.state === 'needs_owner' ? `
        <button class="btn sm" data-open="${esc(p.slot_key)}" title="פתיחת המשבצת">פתיחה</button>
        <button class="btn sm ghost" data-done="${esc(p.id)}" title="סימון שביצעתם את השינוי בערוץ הזה">${ic('check')}בוצע</button>` : ''}</div>
    </div>`).join('')}</div>`;
}
function pubWhy(p) {
  const r = p.result || {};
  if (p.state === 'needs_owner') return r.why || r.error || 'עדכון ידני';
  if (p.state === 'failed') return r.error || 'נכשל';
  return r.why || '';
}
function bindPendingActions(root) {
  (root || document).querySelectorAll('[data-open]').forEach((b) => b.onclick = () => openSlot(b.dataset.open));
  (root || document).querySelectorAll('[data-done]').forEach((b) => b.onclick = () => busy(b, async () => {
    const r = await post(`api/publications/${b.dataset.done}/done`, {});
    if (!r.ok) return binaTell(errText(r.body), 'bad');
    binaTell('סומן כבוצע');
    refreshSoon();
  }));
}

function upcomingList(ov) {
  const up = ov.upcoming || [];
  if (!(ov.settings || {}).launch_date) {
    return `<div class="empty">ציר הזמן מתוארך מיום ההשקה. ${(ov.blueprints || []).some((b) => b.id === 'startup-tail' && b.applied)
      ? '<a href="#/media">קבעו את יום ההשקה</a>' : 'החילו את „זנב סטארט־אפ” וקבעו יום השקה.'}</div>`;
  }
  if (!up.length) return '<div class="empty">אין יחידות מדיה מתוארכות שעוד ריקות.</div>';
  return `<div>${up.map((u) => `<div class="unit" onclick="openSlot('${esc(u.key)}')">
      <div class="due ${new Date(u.due) < new Date() ? 'past' : ''}">${esc(fmtDate(u.due))}</div>
      <div style="min-width:0"><div class="nm">${esc(lbl(u.label))}</div><div class="sub">${esc(lbl(u.phase))}</div></div>
      <div class="end">${chip(`${(u.channels || []).length} ערוצים`, 'plain')}</div></div>`).join('')}</div>`;
}

function eventsList(ev) {
  if (!ev.length) return '<div class="empty">עוד לא קרה כלום.</div>';
  return `<div class="plan">${ev.map((e) => `<div class="pi" style="grid-template-columns:minmax(0,1fr) auto">
      <div style="min-width:0"><div class="c" style="font-weight:600">${esc(e.summary)}</div>
      <div class="w">${e.slot_key ? `<a href="javascript:openSlot('${esc(e.slot_key)}')">${esc(e.slot_key)}</a> · ` : ''}${esc(actorHe(e.actor))}</div></div>
      <span class="note">${esc(fmtAgo(e.at))}</span></div>`).join('')}</div>`;
}
const actorHe = (a) => !a ? '' : a.startsWith('agent') ? 'עזריה' : a === 'owner' ? 'הבעלים' : a.startsWith('digital-assets') ? 'הלשכה' : a;

/* ── a section: identity / content ────────────────────────────────────────────────────────── */
async function pageSection(sec) {
  const title = SECTION_HE[sec] || sec;
  const subs = { identity: 'מי העסק: לוגו, שמות, מזהה, תיאורים, מונחים, צבעים, עיצוב ואיור — כל משבצת יודעת לאן היא מגיעה.',
    content: 'מה העסק אומר: אודות, תיעוד ומדריכים, חנות האפליקציות, האתר, פוסטים, ניוזלטר, חדשות, גרסאות וחזון.' };
  header(title, subs[sec] || '', `<input id="q" type="search" placeholder="חיפוש משבצת" value="${esc(S.query.q || '')}" style="width:220px" aria-label="חיפוש">
    <button class="btn sm" id="b-add" title="משבצת משלכם, שאינה בתבנית">${ic('plus')}משבצת חדשה</button>`);
  const r = await api(`api/slots?section=${encodeURIComponent(sec)}`);
  if (!r.ok) { $('view').innerHTML = `<div class="issue">${esc(errText(r.body))}</div>`; return; }
  S.slotCache[sec] = r.body.slots;
  const q = $('q');
  q.oninput = () => { clearTimeout(q._t); q._t = setTimeout(() => withQuery({ q: q.value }), 250); };
  $('b-add').onclick = () => newSlotDrawer(sec);
  let slots = r.body.slots;
  const needle = (S.query.q || '').trim().toLowerCase();
  if (needle) slots = slots.filter((s) => s.key.includes(needle) || lbl(s.label).toLowerCase().includes(needle));
  if (!slots.length) {
    $('view').innerHTML = `<div class="card"><div class="empty">${needle ? 'לא נמצאה משבצת כזו.' :
      'אין עדיין משבצות בקטע הזה. <a href="#/blueprints">החילו תבנית</a> או הוסיפו משבצת.'}</div></div>`;
    return;
  }
  const groups = {};
  slots.forEach((s) => (groups[s.grp || ''] = groups[s.grp || ''] || []).push(s));
  $('view').innerHTML = `<div class="cards">${Object.entries(groups).map(([g, list]) => {
    const filled = list.filter((s) => s.active).length;
    return `<div class="card"><h3>${esc(grpHe(g))} <span class="hint">${filled} מתוך ${list.length} מולאו</span></h3>
      <div class="slots">${list.map(slotRow).join('')}</div></div>`;
  }).join('')}</div>`;
  $('view').querySelectorAll('.slot').forEach((el) => {
    el.onclick = () => openSlot(el.dataset.key);
    el.onkeydown = (e) => { if (e.key === 'Enter') openSlot(el.dataset.key); };
  });
}

function slotThumb(s) {
  const a = s.active;
  if (a && a.file && (a.kind === 'image' || a.kind === 'animation' || /^image\//.test(a.mime || ''))) return `<img class="thumb" src="${esc(a.thumb)}" alt="">`;
  if (a && s.kind === 'color' && a.text) return `<span class="thumb color" style="background:${esc(a.text)}"></span>`;
  const icon = FILE_KINDS.has(s.kind) ? 'image' : 'text';
  return `<span class="thumb empty">${ic(icon)}</span>`;
}
function slotValue(s) {
  const a = s.active;
  if (!a) return s.count ? `${s.count} גרסאות · אין פעילה` : 'ריק';
  if (a.text) return a.text.replace(/\s+/g, ' ').slice(0, 140);
  return a.title || KIND_HE[a.kind] || a.kind;
}
function slotRow(s) {
  const reach = (s.targets || []).filter((t) => t.channel !== 'brand').length;
  return `<div class="slot" data-key="${esc(s.key)}" tabindex="0" title="${esc(s.key)}">
    <div class="t">${slotThumb(s)}<div class="tx"><div class="lbl">${esc(lbl(s.label))}</div>
      <div class="val">${esc(slotValue(s))}</div></div></div>
    <div class="end">${s.required && !s.active ? chip('חובה', 'req') : ''}
      ${reach ? chip(`${reach} ערוצים`, 'plain', 'לאן הנכס מגיע') : ''}
      ${s.active ? chip('פעיל', 'ok') : ''}</div></div>`;
}

/* ── the slot drawer: versions → active → plan → publish ──────────────────────────────────── */
function openSlot(key) { withQuery({ slot: key, post: null, bp: null, ch: null }); }
window.openSlot = openSlot;

function drawer(title, sub, body, foot, onClose) {
  document.body.classList.add('drawer-open');
  $('drawer-root').innerHTML = `<div class="scrim" id="scrim"></div>
    <aside class="drawer" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="drawer-head"><div style="min-width:0"><div class="dtitle">${title}</div><div class="note">${sub || ''}</div></div>
        <button class="icbtn" id="d-close" title="סגירה (Esc)">${ic('x')}</button></div>
      <div class="drawer-body" id="d-body">${body}</div>
      ${foot ? `<div class="drawer-foot" id="d-foot">${foot}</div>` : ''}
    </aside>`;
  $('scrim').onclick = closeDrawer;
  $('d-close').onclick = closeDrawer;
  S.onClose = onClose || null;
}
function closeDrawer() {
  document.body.classList.remove('drawer-open');
  $('drawer-root').innerHTML = '';
  S.drawerKey = null;
  withQuery({ slot: null, post: null, bp: null, ch: null, plan: null });
}
function syncDrawer(q) {
  if (q.slot) { if (S.drawerKey !== 'slot:' + q.slot + (q.plan || '')) slotDrawer(q.slot, q.plan); }
  else if (q.post) { if (S.drawerKey !== 'post:' + q.post) postDrawer(q.post); }
  else if (q.bp) { if (S.drawerKey !== 'bp:' + q.bp) blueprintDrawer(q.bp); }
  else if (q.ch) { if (S.drawerKey !== 'ch:' + q.ch) channelDrawer(q.ch); }
  else if (q.pending) { if (S.drawerKey !== 'pending') pendingDrawer(); }
  else if ($('drawer-root').innerHTML) { document.body.classList.remove('drawer-open'); $('drawer-root').innerHTML = ''; S.drawerKey = null; }
}

async function slotDrawer(key, planFor) {
  S.drawerKey = 'slot:' + key + (planFor || '');
  const r = await api(`api/slots/${encodeURIComponent(key)}`);
  if (!r.ok) { binaTell(errText(r.body), 'bad'); return; }
  const s = r.body;
  const isMedia = s.section === 'media';
  const cons = s.constraints || {};
  const facts = [['סוג', KIND_HE[s.kind] || s.kind], s.lang ? ['שפה', s.lang === 'he' ? 'עברית' : 'אנגלית'] : null,
    cons.max_len ? ['אורך מרבי', `${cons.max_len} תווים`] : null, cons.aspect ? ['יחס', cons.aspect] : null,
    dims(cons.rec_px) ? ['מידות מומלצות', dims(cons.rec_px)] : null, dims(cons.min_px) ? ['מידות מינימום', dims(cons.min_px)] : null,
    cons.formats ? ['פורמט', (cons.formats || []).join(' · ')] : null,
    s.expires && s.expires !== 'none' ? ['חידוש', s.expires] : null,
    (s.plan || {}).due ? ['מועד', fmtDate(s.plan.due)] : null, (s.plan || {}).timing && !(s.plan || {}).due ? ['תזמון', s.plan.timing] : null,
    ['מקור', (s.sources || []).length ? (s.sources || []).map(bpName).join(' · ') : 'משבצת שלכם']].filter(Boolean);
  const active = s.active;
  const body = `
    <section>${active ? assetPreview(active) : `<div class="empty">אין עדיין גרסה פעילה${s.required ? ' — המשבצת הזו חובה' : ''}.</div>`}
      <div class="kv">${facts.map(([k, v]) => `<div><div class="k">${esc(k)}</div><div class="v" title="${esc(v)}">${esc(v)}</div></div>`).join('')}</div>
      ${cons.note ? `<details class="research"><summary>הערת מחקר (באנגלית)</summary><div>${esc(cons.note)}</div></details>` : ''}
      ${s.brief && s.brief.he ? `<div class="note" style="margin-top:6px">${esc(s.brief.he)}</div>` : ''}</section>
    ${isMedia ? mediaUnitSection(s) : ''}
    <section id="d-plan">${planFor ? '<div class="skel"></div>' : targetsSummary(s)}</section>
    <section><h4>גרסאות <span class="note">${(s.assets || []).length}</span></h4>${versionsList(s)}</section>
    <section><h4>הוספת גרסה</h4>${addForm(s)}</section>
    ${(s.publications || []).length ? `<section><h4>איפה זה עכשיו</h4>${publicationsList(s.publications)}</section>` : ''}
    ${isMedia && (s.posts || []).length ? `<section><h4>פוסטים מהמשבצת</h4>${postsList(s.posts)}</section>` : ''}`;
  const foot = active
    ? `<button class="btn sm primary" id="f-publish" title="תכנית פרסום של הגרסה הפעילה לכל הערוצים">${ic('send')}פרסום לכל הערוצים</button>
       ${isMedia ? `<button class="btn sm" id="f-post" title="פוסט עם המדיה של המשבצת">${ic('share')}פוסט</button>` : ''}
       <span class="spacer"></span><span class="note" title="${esc(key)}">${esc(fmtAgo(s.active_since))}</span>`
    : `${isMedia ? `<button class="btn sm" id="f-post" title="פוסט עם המדיה של המשבצת">${ic('share')}פוסט</button>` : ''}<span class="note">בחרו או הוסיפו גרסה כדי לפרסם</span>`;
  drawer(esc(lbl(s.label)), `${esc(SECTION_HE[s.section])} · ${esc(grpHe(s.grp))} · <span class="mono">${esc(key)}</span>`, body, foot);
  wireSlotDrawer(s);
  if (planFor) showPlan(key, planFor === '1' ? null : planFor);
}

function assetPreview(a) {
  const media = a.file ? (a.kind === 'video' || /^video\//.test(a.mime || '')
    ? `<video src="${esc(a.file)}" controls muted></video>` : (/^image\//.test(a.mime || '') ? `<img src="${esc(a.thumb)}" alt="">`
      : `<a class="btn sm" href="${esc(a.file)}" target="_blank" rel="noopener">${ic('download')}פתיחת הקובץ</a>`)) : '';
  const txt = a.text ? (a.kind === 'color' ? `<span class="swatch" style="background:${esc(a.text)};width:40px;height:40px"></span> <span class="mono">${esc(a.text)}</span>` : esc(a.text)) : '';
  return `<div class="preview">${media}<div class="txt">${txt || `<b>${esc(a.title || '')}</b>`}
    <div class="note" style="margin-top:4px">${esc(SOURCE_HE[a.source] || a.source)} · ${esc(fmtAgo(a.created_at))}${a.width ? ` · <span class="num">${a.width}×${a.height}</span>` : ''}</div></div></div>`;
}

function dims(v) {
  // only the language-neutral part of a research spec ("1024x1024 master (Apple minimum)" → 1024×1024)
  const m = String(v || '').match(/(\d{2,5})\s*[x×]\s*(\d{2,5})/);
  return m ? `${m[1]}×${m[2]}` : '';
}
function bpName(id) {
  const b = ((S.ov && S.ov.blueprints) || []).find((x) => x.id === id);
  return b ? lbl(b.name) : id;
}

function mediaUnitSection(s) {
  const p = s.plan || {};
  if (!p.unit && s.key !== 'media.inbox') return '';
  const specs = (p.assets || []).map((a) => `<div class="spec"><span class="chip plain">${esc(KIND_HE[a.kind] || a.kind)}</span>
      <span class="ltr note" title="${esc(a.spec || '')}">${esc(a.spec || '')}</span>${a.count > 1 ? `<span class="note">× ${a.count}</span>` : ''}</div>`).join('');
  const research = [p.copy ? `<b>copy:</b> ${esc(p.copy)}` : '', lbl(s.brief) ? `<b>purpose:</b> ${esc(lbl(s.brief))}` : '',
    p.timing ? `<b>timing:</b> ${esc(p.timing)}` : '',
    ...(p.examples || []).map((e) => { const m = String(e).match(/https?:\/\/\S+/); return m ? `<a href="${esc(m[0])}" target="_blank" rel="noopener">${esc(e)}</a>` : esc(e); })]
    .filter(Boolean).join('<br>');
  return `<section><h4>מה היחידה הזו כוללת</h4>
    ${specs ? `<div class="speclist">${specs}</div>` : ''}
    ${(p.channels || []).length ? `<div class="chips" style="margin-top:8px">${p.channels.map((c) => chip(chName(c), 'plain', c)).join('')}</div>` : ''}
    ${research ? `<details class="research"><summary>מבנה הטקסט, תזמון ודוגמאות מהמחקר (באנגלית)</summary><div class="examples">${research}</div></details>` : ''}</section>`;
}
function chName(id) {
  const c = ((S.ov && S.ov.channels) || []).find((x) => x.id === id);
  return c ? lbl(c.label) : id;
}

function targetsSummary(s) {
  const t = (s.targets || []);
  if (!t.length) return '<h4>לאן זה מגיע</h4><div class="note">המשבצת לא מחוברת לאף ערוץ — היא נשמרת כאן בלבד.</div>';
  // "updated automatically" only where the office can DO it: a social network or a website; a
  // listing or a printed surface with the same field is updated by hand, and says so
  const kindOf = (id) => ((S.ov && S.ov.channels) || []).find((c) => c.id === id)?.kind;
  const auto = (x) => x.field && ['social', 'website'].includes(kindOf(x.channel) || 'social');
  const pushed = t.filter(auto).map((x) => chName(x.channel));
  const manual = t.filter((x) => x.field && !auto(x)).map((x) => chName(x.channel));
  const used = t.filter((x) => !x.field && x.channel !== 'brand').map((x) => chName(x.channel));
  const brand = t.some((x) => x.channel === 'brand');
  return `<h4>לאן זה מגיע <button class="btn sm ghost" id="b-plan" title="מה ישתנה בכל ערוץ אם תפרסמו עכשיו">תכנית פרסום</button></h4>
    ${pushed.length ? `<div class="note">מתעדכן בפרופיל: ${esc([...new Set(pushed)].join(' · '))}</div>` : ''}
    ${manual.length ? `<div class="note">עדכון ידני: ${esc([...new Set(manual)].join(' · '))}</div>` : ''}
    ${used.length ? `<div class="note">בשימוש גם ב: ${esc([...new Set(used)].join(' · '))}</div>` : ''}
    ${brand ? '<div class="note">המוצרים של הלשכה קוראים אותו ישירות</div>' : ''}`;
}

function versionsList(s) {
  const list = s.assets || [];
  if (!list.length) return '<div class="note">אין גרסאות עדיין.</div>';
  const act = s.active && s.active.id;
  return `<div class="versions">${list.map((a) => {
    const pic = a.file && /^image\//.test(a.mime || '') ? `<img src="${esc(a.thumb)}" alt="">` : `<span class="sq">${ic(FILE_KINDS.has(a.kind) ? 'image' : 'text')}</span>`;
    const line = a.text ? a.text.replace(/\s+/g, ' ').slice(0, 120) : (a.title || KIND_HE[a.kind]);
    return `<div class="ver ${a.id === act ? 'active' : ''}">${pic}
      <div class="body"><div class="x" title="${esc(a.text || a.title || '')}">${esc(line)}</div>
        <div class="note">${esc(SOURCE_HE[a.source] || a.source)} · ${esc(fmtAgo(a.created_at))}${a.width ? ` · <span class="num">${a.width}×${a.height}</span>` : ''}</div></div>
      <div class="row">${a.id === act ? chip('פעילה', 'ok')
        : `<button class="btn sm primary" data-activate="${esc(a.id)}" title="הפיכה לגרסה הפעילה — ואז תכנית פרסום">הפיכה לפעילה</button>
           <button class="icbtn" data-archive="${esc(a.id)}" title="העברה לארכיון">${ic('archive')}</button>`}</div></div>`;
  }).join('')}</div>`;
}

function addForm(s) {
  const k = s.kind;
  const fileish = FILE_KINDS.has(k) || k === 'set';
  const textish = !FILE_KINDS.has(k);
  const cons = s.constraints || {};
  const max = cons.max_len ? `maxlength="${cons.max_len}"` : '';
  let input = '';
  if (k === 'color') input = `<div class="row"><input type="color" id="f-color" value="#56693f"><input id="f-text" class="mono" placeholder="#56693f" style="flex:1"></div>`;
  else if (['richtext', 'list', 'price-list', 'hours', 'address'].includes(k) || k === 'set') input = `<textarea id="f-text" ${max} placeholder="${k === 'list' || k === 'price-list' ? 'פריט בכל שורה' : k === 'set' ? 'טקסט לפוסט / כיתוב (אופציונלי)' : 'הטקסט'}"></textarea>`;
  else if (textish) input = `<input id="f-text" ${max} placeholder="${esc(KIND_HE[k] || 'ערך')}">`;
  return `${textish ? input : ''}
    ${fileish ? `<div class="drop" id="f-drop" tabindex="0" title="בחירת קובץ">${ic('upload')} גררו לכאן קובץ, או לחצו לבחירה
      <input type="file" id="f-file" hidden></div><div class="note" id="f-picked"></div>` : ''}
    ${k === 'document' ? '<label for="f-exp">בתוקף עד</label><input type="date" id="f-exp">' : ''}
    ${textish && cons.max_len ? `<div class="note" id="f-count">0 / ${cons.max_len}</div>` : ''}
    <div class="row" style="margin-top:10px">
      <button class="btn sm primary" id="f-add-act" title="הוספה והפיכה לפעילה — ואז תכנית פרסום">${ic('check')}הוספה והפיכה לפעילה</button>
      <button class="btn sm" id="f-add" title="שמירה כגרסה נוספת, בלי לשנות את הפעילה">שמירה כגרסה</button></div>`;
}

function wireSlotDrawer(s) {
  const d = $('d-body');
  d.querySelectorAll('[data-activate]').forEach((b) => b.onclick = () => busy(b, async () => {
    const r = await post(`api/assets/${b.dataset.activate}/activate`, {});
    if (!r.ok) return binaTell(errText(r.body), 'bad');
    binaTell('הגרסה פעילה — זו תכנית הפרסום');
    withQuery({ slot: s.key, plan: b.dataset.activate });
  }));
  d.querySelectorAll('[data-archive]').forEach((b) => b.onclick = () => busy(b, async () => {
    const r = await api(`api/assets/${b.dataset.archive}`, { method: 'DELETE' });
    if (!r.ok) return binaTell(errText(r.body), 'bad');
    binaTell('הועבר לארכיון');
    S.drawerKey = null; slotDrawer(s.key);
  }));
  const bp = $('b-plan');
  if (bp) bp.onclick = () => withQuery({ slot: s.key, plan: '1' });
  const fp = $('f-publish');
  if (fp) fp.onclick = () => withQuery({ slot: s.key, plan: '1' });
  const fpost = $('f-post');
  if (fpost) fpost.onclick = () => { S.postPrefill = { slot: s.key, assets: s.active ? [s.active.id] : [] }; withQuery({ slot: null, plan: null, post: s.key }); };
  const text = $('f-text');
  const count = $('f-count');
  if (text && count) text.oninput = () => { count.textContent = `${text.value.length} / ${(s.constraints || {}).max_len}`; };
  const color = $('f-color');
  if (color && text) { color.oninput = () => { text.value = color.value; }; text.oninput = () => { if (/^#[0-9a-f]{6}$/i.test(text.value)) color.value = text.value; }; }
  const drop = $('f-drop'), file = $('f-file');
  let picked = null;
  if (drop) {
    drop.onclick = () => file.click();
    drop.onkeydown = (e) => { if (e.key === 'Enter') file.click(); };
    file.onchange = () => { picked = file.files[0]; $('f-picked').textContent = picked ? `נבחר: ${picked.name} (${Math.round(picked.size / 1024)}KB)` : ''; };
    drop.ondragover = (e) => { e.preventDefault(); drop.classList.add('over'); };
    drop.ondragleave = () => drop.classList.remove('over');
    drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove('over'); picked = e.dataTransfer.files[0]; $('f-picked').textContent = picked ? `נבחר: ${picked.name}` : ''; };
  }
  const submit = (activate) => async () => {
    const fd = new FormData();
    if (picked) fd.append('file', picked);
    if (text && text.value.trim()) fd.append('text', text.value.trim());
    if (!picked && !(text && text.value.trim())) return binaTell('אין מה לשמור — הקלידו ערך או בחרו קובץ', 'warn');
    const exp = $('f-exp');
    if (exp && exp.value) fd.append('expires_at', exp.value);
    if (picked) fd.append('title', picked.name.replace(/\.[^.]+$/, ''));
    if (activate) fd.append('activate', '1');
    const r = await api(`api/slots/${encodeURIComponent(s.key)}/assets`, { method: 'POST', body: fd });
    if (!r.ok) return binaTell(errText(r.body), 'bad');
    binaTell(activate ? 'נוסף והפך לפעיל — זו תכנית הפרסום' : 'נשמר כגרסה');
    S.drawerKey = null;
    if (activate) withQuery({ slot: s.key, plan: r.body.asset.id }); else slotDrawer(s.key);
    refreshSoon();
  };
  const a1 = $('f-add-act'), a2 = $('f-add');
  if (a1) a1.onclick = () => busy(a1, submit(true));
  if (a2) a2.onclick = () => busy(a2, submit(false));
  bindPendingActions(d);
  d.querySelectorAll('[data-pubdone]').forEach((b) => b.onclick = () => busy(b, async () => {
    const r = await post(`api/publications/${b.dataset.pubdone}/done`, {});
    if (!r.ok) return binaTell(errText(r.body), 'bad');
    binaTell('סומן כבוצע'); S.drawerKey = null; slotDrawer(s.key);
  }));
  wireCopy(d);
  wirePostDone(d, () => { S.drawerKey = null; slotDrawer(s.key); });
}

async function showPlan(key, assetId) {
  const box = $('d-plan');
  if (!box) return;
  const r = await api(`api/slots/${encodeURIComponent(key)}/plan${assetId ? `?asset_id=${encodeURIComponent(assetId)}` : ''}`);
  if (!r.ok) { box.innerHTML = `<div class="issue">${esc(errText(r.body))}</div>`; return; }
  const pl = r.body;
  const go = pl.items.filter((it) => it.action !== 'skip' && it.action !== 'manual');
  const manual = pl.items.filter((it) => it.action === 'manual').length;
  box.innerHTML = `<h4>תכנית פרסום <span class="note">${go.length} ערוצים ישתנו${manual ? ` · ${manual} עדכונים ידניים (סמנו כדי לעקוב)` : ''} · ${pl.items.length - go.length - manual} לא</span></h4>
    <div class="plan">${pl.items.map((it) => `<label class="pi ${it.action === 'skip' ? 'off' : ''}" style="margin:0">
      <input type="checkbox" data-i="${it.i}" ${it.action === 'skip' ? 'disabled' : (it.action === 'manual' ? '' : 'checked')} aria-label="כלול ${esc(it.channel_label)}">
      <div style="min-width:0"><div class="c">${esc(it.channel_label)}${it.field_label ? ` · ${esc(it.field_label)}` : ''}</div>
        <div class="w" title="${esc(it.why || '')}">${esc(it.why || (it.action === 'push' ? 'יעודכן אוטומטית ויאומת בקריאה חוזרת' : ''))}</div></div>
      <span>${chip(ACTION_HE[it.action], ACTION_CLS[it.action], it.action)}${it.needs === 'bind' ? ` <a class="btn sm ghost" href="javascript:openChannel('${esc(it.channel)}')">חיבור</a>` : ''}</span>
    </label>`).join('')}</div>
    <label class="row note" style="margin:10px 0 0" title="לתסריט דפדפן שעוד לא אומת: הבעלים צופה בדפדפן של הלשכה"><input type="checkbox" id="p-watch" style="width:auto"> אני צופה בדפדפן הלשכה (לתסריט דפדפן שעוד לא אומת)</label>`;
  // while a plan is open, the drawer's primary action IS "publish this plan" — one button, in the footer
  const foot = $('d-foot');
  if (foot) foot.innerHTML = `<button class="btn sm primary" id="p-go" title="שליחה לכל הערוצים המסומנים">${ic('send')}פרסום לערוצים המסומנים</button>
    <button class="btn sm ghost" id="p-cancel" title="סגירת התכנית בלי לפרסם">לא עכשיו</button>
    <span class="spacer"></span><span class="note">כל ערוץ מקבל את הגודל והמגבלות שלו</span>`;
  const cancel = $('p-cancel');
  if (cancel) cancel.onclick = () => withQuery({ slot: key, plan: null });
  box.scrollIntoView({ block: 'start', behavior: 'smooth' });
  $('p-go').onclick = () => busy($('p-go'), async () => {
    const choose = [...box.querySelectorAll('input[data-i]:checked')].map((x) => +x.dataset.i);
    if (!choose.length) return binaTell('לא סומן אף ערוץ', 'warn');
    const r2 = await post(`api/slots/${encodeURIComponent(key)}/publish`, { asset_id: pl.asset_id, choose, watch: $('p-watch').checked });
    if (!r2.ok) return binaTell(errText(r2.body), 'bad');
    binaTell(`הפרסום יצא ל-${choose.length} ערוצים — ההתקדמות כאן`);
    S.drawerKey = null;
    withQuery({ slot: key, plan: null });
    refreshSoon();
  });
}

function publicationsList(rows) {
  return `<div class="plan">${rows.map((p) => {
    const r = p.result || {};
    const manual = p.state === 'needs_owner' ? `<div class="row" style="margin-top:6px">${r.url ? `<a class="btn sm" href="${esc(r.url)}" target="_blank" rel="noopener">${ic('external')}פתיחה</a>` : ''}
      <button class="btn sm ghost" data-pubdone="${esc(p.id)}" title="סימון שביצעתם את העדכון">${ic('check')}בוצע</button></div>` : '';
    const verify = p.state === 'ok' && r.verify ? Object.entries(r.verify).map(([f, v]) => v && v.match ? chip('אומת בקריאה חוזרת', 'ok', f) : '').join('') : '';
    return `<div class="pi" style="grid-template-columns:auto minmax(0,1fr)"><span>${stateChip(p.state)}</span>
      <div style="min-width:0"><div class="c">${esc(p.channel_label)}${p.field_label ? ` · ${esc(p.field_label)}` : ''} ${verify}
        ${r.url && p.state === 'ok' ? `<a href="${esc(r.url)}" target="_blank" rel="noopener" class="note">צפייה</a>` : ''}</div>
        ${p.state === 'failed' ? `<div class="w" style="white-space:normal;color:var(--red)">${esc(r.error || 'נכשל')}${r.how ? ` — ${esc(r.how)}` : ''}</div>` : ''}
        ${manual}</div></div>`;
  }).join('')}</div>`;
}

// A listing or print channel (Product Hunt, Google Business, a printed menu) has no automation yet:
// the card carries the text and the files, and the owner marks it done. Social networks never get
// this card — they go through the office browser (social-list).
function manualCard(h, postDone) {
  const files = (h.files || []).map((f) => f.file_url ? `<a class="btn sm" href="${esc(f.file_url)}" download>${ic('download')}קובץ</a>` : '').join('');
  return `<div class="manualcard"><div class="c">${esc(h.title || 'עדכון ידני')}</div>
    <div class="note">${esc(h.instructions || '')}</div>
    ${h.text ? `<div class="copybox" style="margin:6px 0"><code>${esc(h.text)}</code><button class="icbtn" data-copy="${esc(h.text)}" title="העתקה">${ic('copy')}</button></div>` : ''}
    <div class="row">${h.url ? `<a class="btn sm" href="${esc(h.url)}" target="_blank" rel="noopener">${ic('external')}פתיחת העמוד</a>` : ''}${files}
      ${postDone ? `<button class="btn sm ghost" data-postdone="${esc(postDone)}" title="סימון שפרסמתם בערוץ הזה">${ic('check')}בוצע</button>` : ''}</div></div>`;
}
function wireCopy(root) {
  root.querySelectorAll('[data-copy]').forEach((b) => b.onclick = async () => {
    try { await navigator.clipboard.writeText(b.dataset.copy); binaTell('הועתק'); } catch (e) { binaTell('ההעתקה נחסמה בדפדפן', 'bad'); }
  });
}

function postsList(posts) {
  return `<div class="plan">${posts.map((p) => `<div class="pi" style="grid-template-columns:auto minmax(0,1fr)">${stateChip(p.state)}
    <div style="min-width:0"><div class="c">${esc((p.text || '').slice(0, 90) || 'פוסט')}</div>
    <div class="chips" style="margin-top:4px">${Object.entries(p.results || {}).map(([c, r]) => chip(`${chName(c)}: ${STATE_HE[r.state] || r.state}`, STATE_CLS[r.state] || '', r.error || '')).join('')}</div>
    ${Object.entries(p.results || {}).filter(([, r]) => r.state === 'needs_owner' && r.manual).map(([c, r]) => manualCard(r.manual, `${p.id}|${c}`)).join('')}</div></div>`).join('')}</div>`;
}
function wirePostDone(root, after) {
  root.querySelectorAll('[data-postdone]').forEach((b) => b.onclick = () => busy(b, async () => {
    const [pid, ch] = b.dataset.postdone.split('|');
    const r = await post(`api/posts/${pid}/done`, { channel: ch });
    if (!r.ok) return binaTell(errText(r.body), 'bad');
    binaTell('סומן כבוצע');
    after();
  }));
}

async function newSlotDrawer(sec) {
  S.drawerKey = 'new';
  drawer('משבצת חדשה', `בקטע ${esc(SECTION_HE[sec])}`, `
    <label for="n-label">שם המשבצת</label><input id="n-label" placeholder="למשל: כותרת עמוד האודות">
    <label for="n-key">מפתח (מופיע בעמודי האתר כ-data-da)</label><input id="n-key" class="mono" value="${esc(sec)}." >
    <label for="n-kind">סוג</label><select id="n-kind">${Object.entries(KIND_HE).filter(([k]) => !['page', 'thread', 'email_msg', 'livestream'].includes(k)).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select>
    <label class="row" style="margin-top:12px"><input type="checkbox" id="n-site" style="width:auto" checked> מופיע באתר</label>`,
  `<button class="btn sm primary" id="n-save">${ic('plus')}יצירה</button>`);
  $('n-save').onclick = () => busy($('n-save'), async () => {
    const r = await post('api/slots', { key: $('n-key').value.trim(), label: $('n-label').value.trim(), kind: $('n-kind').value,
      targets: $('n-site').checked ? [{ channel: 'website' }] : [] });
    if (!r.ok) return binaTell(errText(r.body), 'bad');
    binaTell('המשבצת נוצרה');
    openSlot(r.body.key);
  });
}

/* ── media: timeline, gallery, posts ──────────────────────────────────────────────────────── */
async function pageMedia(tab) {
  header('מדיה', 'ציר הזמן של היחידות שהתבניות הגדירו, הגלריה של כל מה שנוצר — כולל מה שעזריה יצרה — והפוסטים.',
    `<div class="tabs" style="margin:0">
      <a class="btn sm ${tab === 'timeline' ? 'on' : ''}" href="#/media">${ic('calendar')}ציר זמן</a>
      <a class="btn sm ${tab === 'gallery' ? 'on' : ''}" href="#/media/gallery">${ic('image')}גלריה</a>
      <a class="btn sm ${tab === 'posts' ? 'on' : ''}" href="#/media/posts">${ic('send')}פוסטים</a></div>`);
  if (!S.ov) await loadOverview();
  if (tab === 'gallery') return mediaGallery();
  if (tab === 'posts') return mediaPosts();
  return mediaTimeline();
}

async function mediaTimeline() {
  const r = await api('api/slots?section=media');
  if (!r.ok) { $('view').innerHTML = `<div class="issue">${esc(errText(r.body))}</div>`; return; }
  const slots = r.body.slots;
  const d0 = (S.ov.settings || {}).launch_date || '';
  const tailApplied = (S.ov.blueprints || []).some((b) => b.id === 'startup-tail' && b.applied);
  const phases = {};
  slots.forEach((s) => {
    const p = s.plan || {};
    const id = p.phase || s.grp || 'other';
    const ph = phases[id] = phases[id] || { id, name: p.phase_name || { he: grpHe(id) }, order: p.phase_order || (id === 'inbox' ? -1 : id === 'calendar' ? 90 : 50), window: p.window, units: [] };
    ph.units.push(s);
  });
  const list = Object.values(phases).sort((a, b) => a.order - b.order);
  const bar = tailApplied ? `<div class="card"><div class="row"><b>יום ההשקה (D0)</b>
      <input type="date" id="d0" value="${esc(d0)}" style="width:180px" aria-label="יום ההשקה">
      <button class="btn sm primary" id="d0-save" title="מתארך מחדש את כל היחידות של זנב הסטארט־אפ">${ic('calendar')}עדכון התאריכים</button>
      <span class="note">כל יחידה בציר מתוארכת ממנו (D−180 … D+365).</span></div></div>` : '';
  // (no early return for an empty timeline: the date bar above it is shown either way, and its button was
  // bound only further down — shown and dead)
  $('view').innerHTML = bar + (list.map((ph) => {
    const filled = ph.units.filter((u) => u.count).length;
    return `<div class="card"><h3>${esc(lbl(ph.name))} <span class="hint">${ph.window ? `<span class="mono">${esc(ph.window)}</span> · ` : ''}${filled} מתוך ${ph.units.length} התחילו</span></h3>
      <div>${ph.units.map((u) => {
        const p = u.plan || {};
        const due = p.due ? `<div class="due ${new Date(p.due) < new Date() && !u.count ? 'past' : ''}">${esc(fmtDate(p.due))}</div>` : `<div class="due none">${p.recurring ? 'קבוע' : (p.timing ? 'לפי אירוע' : '—')}</div>`;
        const specs = (p.assets || []).map((a) => KIND_HE[a.kind] || a.kind);
        return `<div class="unit" data-key="${esc(u.key)}" tabindex="0" title="${esc(u.key)}">${due}
          <div style="min-width:0"><div class="nm">${esc(lbl(u.label))}</div><div class="sub">${esc([...new Set(specs)].join(' · ') || lbl(u.brief))}</div></div>
          <div class="end">${u.count ? chip(`${u.count} פריטים`, 'ok') : chip('ריק', 'plain')}${(p.channels || []).length ? chip(`${p.channels.length} ערוצים`, 'plain') : ''}</div></div>`;
      }).join('')}</div></div>`;
  }).join('') || '<div class="card"><div class="empty">אין עדיין יחידות מדיה. <a href="#/blueprints">החילו תבנית</a>.</div></div>');
  $('view').querySelectorAll('.unit').forEach((el) => { el.onclick = () => openSlot(el.dataset.key); el.onkeydown = (e) => { if (e.key === 'Enter') openSlot(el.dataset.key); }; });
  const save = $('d0-save');
  if (save) save.onclick = () => busy(save, async () => {
    const v = $('d0').value;
    if (!v) return binaTell('בחרו תאריך', 'warn');
    const r2 = await post('api/blueprints/startup-tail/apply', { params: { launch_date: v } });
    if (!r2.ok) return binaTell(errText(r2.body), 'bad');
    binaTell('התאריכים עודכנו'); S.ov = null; await loadOverview(); route();
  });
}

async function mediaGallery() {
  const r = await api('api/media');
  if (!r.ok) { $('view').innerHTML = `<div class="issue">${esc(errText(r.body))}</div>`; return; }
  const items = r.body.assets;
  S.sel = S.sel || new Set();
  if (!items.length) { $('view').innerHTML = '<div class="card"><div class="empty">הגלריה ריקה. מדיה שעזריה יוצרת נכנסת לכאן, וכל קובץ שמעלים ליחידת מדיה.</div></div>'; return; }
  $('view').innerHTML = `<div class="card"><h3>הגלריה <span class="hint">${items.length} פריטים · סמנו כדי לפרסם יחד</span>
      <button class="btn sm primary" id="g-post" title="פוסט עם הפריטים המסומנים">${ic('send')}פוסט עם המסומנים</button></h3>
    <div class="gallery">${items.map((a) => `<button class="tile ${S.sel.has(a.id) ? 'sel' : ''}" data-id="${esc(a.id)}" data-slot="${esc(a.slot_key)}" title="${esc(a.slot_label || a.slot_key)}">
      <div class="pic">${a.file && /^image\//.test(a.mime || '') ? `<img src="${esc(a.thumb)}" alt="" loading="lazy">`
        : a.file && /^video\//.test(a.mime || '') ? `<video src="${esc(a.file)}" muted></video>` : `<div class="txt">${esc((a.text || a.title || '').slice(0, 220))}</div>`}</div>
      <div class="meta"><b>${esc(a.title || a.slot_label || KIND_HE[a.kind])}</b><span class="note">${esc(a.slot_label || '')}</span>
      <span>${chip(SOURCE_HE[a.source] || a.source, a.source === 'agent' ? 'owner' : 'plain')}</span></div></button>`).join('')}</div></div>`;
  $('view').querySelectorAll('.tile').forEach((t) => {
    t.onclick = (e) => {
      if (e.shiftKey || e.metaKey || S.sel.size) { S.sel.has(t.dataset.id) ? S.sel.delete(t.dataset.id) : S.sel.add(t.dataset.id); t.classList.toggle('sel'); return; }
      openSlot(t.dataset.slot);
    };
    t.oncontextmenu = (e) => { e.preventDefault(); S.sel.has(t.dataset.id) ? S.sel.delete(t.dataset.id) : S.sel.add(t.dataset.id); t.classList.toggle('sel'); };
  });
  $('g-post').onclick = () => {
    if (!S.sel.size) return binaTell('סמנו פריטים (Shift+לחיצה) או פתחו יחידה ולחצו „פוסט”', 'warn');
    S.postPrefill = { assets: [...S.sel] };
    withQuery({ post: 'new' });
  };
}

async function mediaPosts() {
  const r = await api('api/posts');
  if (!r.ok) { $('view').innerHTML = `<div class="issue">${esc(errText(r.body))}</div>`; return; }
  const posts = r.body.posts;
  $('view').innerHTML = `<div class="card"><h3>פוסטים <button class="btn sm primary" id="p-new">${ic('plus')}פוסט חדש</button></h3>
    ${posts.length ? postsList(posts) : '<div class="empty">עוד לא פורסם פוסט.</div>'}</div>`;
  $('p-new').onclick = () => { S.postPrefill = { assets: [] }; withQuery({ post: 'new' }); };
  wireCopy($('view'));
  wirePostDone($('view'), () => route());
}

async function postDrawer(which) {
  S.drawerKey = 'post:' + which;
  const pre = S.postPrefill || {};
  if (!S.ov) await loadOverview();
  const slotKey = which && which !== 'new' ? which : pre.slot;
  let assets = [];
  let unitChannels = new Set();
  if (slotKey) {
    const r = await api(`api/slots/${encodeURIComponent(slotKey)}`);
    if (r.ok) { assets = r.body.assets || []; unitChannels = new Set(((r.body.plan || {}).channels) || []); }
  } else if ((pre.assets || []).length) {
    const r = await api('api/media');
    if (r.ok) assets = r.body.assets.filter((a) => pre.assets.includes(a.id));
  }
  const chosen = new Set(pre.assets && pre.assets.length ? pre.assets : assets.filter((a) => a.file).slice(0, 1).map((a) => a.id));
  const textAsset = assets.find((a) => a.text && !a.file);
  const channels = (S.ov.channels || []).filter((c) => c.kind === 'social' || c.kind === 'listing');
  const socials = channels.filter((c) => c.kind === 'social');
  drawer('פוסט', slotKey ? `מהמשבצת <span class="mono">${esc(slotKey)}</span>` : 'מהגלריה', `
    <label for="pt">הטקסט</label><textarea id="pt" placeholder="מה לפרסם">${esc(textAsset ? textAsset.text : '')}</textarea>
    <div class="note" id="pt-n"></div>
    ${assets.filter((a) => a.file).length ? `<label>מדיה</label><div class="gallery" style="grid-template-columns:repeat(auto-fill,minmax(96px,1fr))">${assets.filter((a) => a.file).map((a) => `
      <button class="tile ${chosen.has(a.id) ? 'sel' : ''}" data-pick="${esc(a.id)}" title="${esc(a.title || '')}"><div class="pic">${/^image\//.test(a.mime || '') ? `<img src="${esc(a.thumb)}" alt="">` : `<div class="txt">${esc(KIND_HE[a.kind] || a.kind)}</div>`}</div></button>`).join('')}</div>` : ''}
    <label>ערוצים</label>
    <div class="plan">${socials.map((c) => `<label class="pi ${c.bound ? '' : 'off'}" style="margin:0"><input type="checkbox" data-ch="${esc(c.id)}" ${c.bound && (unitChannels.size ? unitChannels.has(c.id) : true) ? 'checked' : ''} ${c.bound ? '' : 'disabled'}>
      <div style="min-width:0"><div class="c">${esc(lbl(c.label))}</div><div class="w">${esc(chState(c).he)}</div></div>${monoTile(c)}</label>`).join('')}
    ${channels.filter((c) => c.kind === 'listing' && unitChannels.has(c.id)).map((c) => `<label class="pi" style="margin:0"><input type="checkbox" data-ch="${esc(c.id)}">
      <div style="min-width:0"><div class="c">${esc(lbl(c.label))}</div><div class="w">ידני — הטקסט והקבצים מוכנים בכרטיס</div></div><span></span></label>`).join('')}</div>
    <label class="row note" style="margin-top:10px"><input type="checkbox" id="p-watch2" style="width:auto"> אני צופה בדפדפן הלשכה (לתסריט דפדפן שעוד לא אומת)</label>`,
  `<button class="btn sm primary" id="pt-go">${ic('send')}פרסום</button><span class="note">כל ערוץ מקבל את הגודל והמגבלות שלו</span>`);
  const t = $('pt');
  const count = () => { $('pt-n').textContent = `${t.value.length} תווים${t.value.length > 280 ? ' · ב-X ייחתך ל-280' : ''}`; };
  t.oninput = count; count();
  $('d-body').querySelectorAll('[data-pick]').forEach((b) => b.onclick = () => { chosen.has(b.dataset.pick) ? chosen.delete(b.dataset.pick) : chosen.add(b.dataset.pick); b.classList.toggle('sel'); });
  $('pt-go').onclick = () => busy($('pt-go'), async () => {
    const chans = [...$('d-body').querySelectorAll('input[data-ch]:checked')].map((x) => x.dataset.ch);
    if (!chans.length) return binaTell('לא נבחר ערוץ', 'warn');
    const r = await post('api/posts', { slot: slotKey || null, asset_ids: [...chosen], text: t.value, channels: chans, watch: $('p-watch2').checked });
    if (!r.ok) return binaTell(errText(r.body), 'bad');
    binaTell('הפוסט יצא — ההתקדמות בעמוד הפוסטים');
    S.sel = new Set();
    closeDrawer();
    go('/media/posts');
  });
}

/* ── channels ─────────────────────────────────────────────────────────────────────────────── */
function openChannel(id) { withQuery({ ch: id, slot: null, plan: null }); }
window.openChannel = openChannel;

async function pageChannels() {
  header('ערוצים', 'איפה העסק מופיע, ואיזה חשבון או אתר עומד מאחורי כל ערוץ. החשבונות עצמם מחוברים באפליקציית „רשתות חברתיות”.',
    `<a class="btn sm" href="../social-list/" target="_top" title="חיבור חשבונות ברשתות החברתיות">${ic('external')}רשתות חברתיות</a>`);
  const r = await api('api/channels');
  if (!r.ok) { $('view').innerHTML = `<div class="issue">${esc(errText(r.body))}</div>`; return; }
  await loadOverview();
  const all = (S.ov.channels || []);
  const core = all.filter((c) => c.core);
  const other = all.filter((c) => !c.core);
  $('view').innerHTML = `${r.body.social_error ? `<div class="issue">${esc(r.body.social_error)}</div>` : ''}
    <div class="card"><h3>הערוצים הראשיים <span class="hint">${core.filter((c) => c.bound).length} מתוך ${core.length} מחוברים</span></h3>
      <div class="chgrid">${core.map((c) => channelCard(c)).join('')}</div></div>
    ${other.length ? `<div class="card"><h3>עוד מקומות שהעסק מופיע בהם <span class="hint">רישומים, דפוס ומסמכים — הלשכה עוקבת, העדכון ידני</span></h3>
      <div class="tscroll"><table class="t"><thead><tr><th>ערוץ</th><th>סוג</th><th>כתובת</th><th></th></tr></thead><tbody>${other.map((c) => `<tr>
        <td><b>${esc(lbl(c.label))}</b></td><td>${esc(KINDCH_HE[c.kind] || c.kind)}</td>
        <td>${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener" class="mono">${esc(c.url.replace(/^https?:\/\//, '').slice(0, 40))}</a>` : '<span class="note">—</span>'}</td>
        <td><button class="btn sm ghost" onclick="openChannel('${esc(c.id)}')">עריכה</button></td></tr>`).join('')}</tbody></table></div></div>` : ''}`;
}
function channelCard(c) {
  const acc = c.account, st = chState(c);
  return `<div class="ch"><div class="top">${monoTile(c)}<div style="min-width:0;flex:1"><div class="name">${esc(lbl(c.label))}</div>
      <div class="acct" dir="auto" title="${esc(st.who)}">${esc(st.who)}</div></div>
      ${chip(st.he, st.cls, st.tip)}</div>
    <div class="row">${acc && acc.test ? chip('רשת בדיקה', 'owner', 'חזרה גנרלית לפני החשבון האמיתי') : ''}${chip(c.lang === 'en' ? 'אנגלית' : 'עברית', 'plain', 'שפת הערוץ')}
      <span class="spacer"></span><button class="btn sm" onclick="openChannel('${esc(c.id)}')">${c.bound ? 'החלפה' : 'חיבור'}</button></div></div>`;
}

async function channelDrawer(id) {
  S.drawerKey = 'ch:' + id;
  const r = await api('api/channels');
  if (!r.ok) return binaTell(errText(r.body), 'bad');
  const c = r.body.channels.find((x) => x.id === id);
  if (!c) return binaTell('ערוץ לא נמצא', 'bad');
  let bind = '';
  if (c.kind === 'social') {
    const accs = (r.body.accounts || []).filter((a) => a.platform === c.platform || a.test);
    bind = `<label for="c-acc">החשבון</label><select id="c-acc"><option value="">— ללא —</option>${accs.map((a) => `<option value="${esc(a.id)}" ${a.id === c.account_id ? 'selected' : ''}>${esc(accName(a))} · ${esc(kindHe(a.kind))}${a.test ? ' · רשת בדיקה' : ''}</option>`).join('')}</select>
      <div class="note" style="margin-top:6px">${accs.length ? '' : 'אין עדיין חשבון לפלטפורמה הזו. '}חשבונות מחברים ב<a href="../social-list/" target="_top">רשתות חברתיות</a> — דרך API, דרך הדפדפן של הלשכה, או כהכנה ולחיצה.</div>`;
  } else if (c.kind === 'website') {
    const sites = r.body.sites || [];
    bind = `<label for="c-site">האתר</label><select id="c-site"><option value="">— ללא —</option>${sites.map((s) => `<option value="${esc(s.id)}" ${s.id === c.site_id ? 'selected' : ''}>${esc(s.name || s.id)}</option>`).join('')}</select>
      <div class="note" style="margin-top:6px">${sites.length ? '' : 'אפליקציית האתרים לא החזירה אתרים. '}כל טקסט ותמונה באתר שמסומנים ב-<span class="mono">data-da="מפתח"</span> מתעדכנים מהמשבצת באותו מפתח.</div>
      <label for="c-url">כתובת האתר</label><div class="row"><input id="c-url" class="mono" value="${esc(c.url || '')}" placeholder="https://" style="flex:1">
      <button class="btn sm" id="c-scan" title="אילו טקסטים ותמונות בעמוד כבר ממופים למשבצות, ואילו עוד כתובים ביד">סריקת העמוד</button></div>
      <div id="c-scan-out"></div>`;
  } else {
    bind = `<label for="c-url">כתובת</label><input id="c-url" class="mono" value="${esc(c.url || '')}" placeholder="https://">`;
  }
  drawer(esc(lbl(c.label)), esc(KINDCH_HE[c.kind] || c.kind), `${bind}
    <label for="c-lang">שפת הערוץ</label><select id="c-lang"><option value="he" ${c.lang !== 'en' ? 'selected' : ''}>עברית</option><option value="en" ${c.lang === 'en' ? 'selected' : ''}>אנגלית</option></select>
    <div class="note" style="margin-top:4px">קובע איזו גרסת שם ותיאור (עברית או אנגלית) מגיעה לערוץ הזה.</div>
    <label class="row" style="margin-top:12px"><input type="checkbox" id="c-en" style="width:auto" ${c.enabled ? 'checked' : ''}> הערוץ פעיל</label>`,
  `<button class="btn sm primary" id="c-save">${ic('check')}שמירה</button>`);
  const scanBtn = $('c-scan');
  if (scanBtn) scanBtn.onclick = () => busy(scanBtn, async () => {
    const url = $('c-url').value.trim();
    if (!url) return binaTell('הקלידו את כתובת האתר', 'warn');
    const r2 = await post('api/site-kit/scan', { url });
    if (!r2.ok) return binaTell(errText(r2.body), 'bad');
    $('c-scan-out').innerHTML = siteScanView(r2.body);
  });
  $('c-save').onclick = () => busy($('c-save'), async () => {
    const body = { lang: $('c-lang').value, enabled: $('c-en').checked };
    if ($('c-acc')) body.account_id = $('c-acc').value || null;
    if ($('c-site')) body.site_id = $('c-site').value || null;
    if ($('c-url')) body.url = $('c-url').value.trim() || null;
    const r2 = await put(`api/channels/${encodeURIComponent(id)}`, body);
    if (!r2.ok) return binaTell(errText(r2.body), 'bad');
    binaTell('הערוץ נשמר'); closeDrawer(); S.ov = null; route();
  });
}

function siteScanView(sc) {
  const WHAT = { text: 'טקסט', src: 'תמונה', href: 'קישור', content: 'מטא', alt: 'טקסט חלופי' };
  const mapped = sc.mapped || [];
  const un = sc.unmapped || [];
  return `<section><h4>ממופה למשבצות <span class="note">${mapped.length}</span></h4>
    ${mapped.length ? `<div class="plan">${mapped.map((m) => `<div class="pi" style="grid-template-columns:auto minmax(0,1fr) auto">
      ${chip(WHAT[m.what] || m.what, 'plain')}<div style="min-width:0"><div class="c">${esc(m.label || m.key)}</div>
      <div class="w" title="${esc(m.current)}">באתר: ${esc(m.current || '—')}</div></div>
      ${!m.known ? chip('משבצת לא קיימת', 'bad', m.key) : m.active == null ? chip('אין ערך פעיל', 'plain') : chip('יתעדכן', 'ok')}</div>`).join('')}</div>`
      : '<div class="note">העמוד עוד לא מסמן אף טקסט או תמונה ב-data-da.</div>'}</section>
    <section><h4>עוד כתוב ביד <span class="note">${un.length} טקסטים ותמונות שאינם משבצות</span></h4>
    ${un.length ? `<div class="plan">${un.slice(0, 40).map((u) => `<div class="pi" style="grid-template-columns:auto minmax(0,1fr)">
      ${chip(WHAT[u.what] || u.what, 'plain', u.tag)}<div class="w" style="white-space:normal" title="${esc(u.current)}">${esc(u.current)}</div></div>`).join('')}</div>` : '<div class="note">הכל ממופה.</div>'}</section>`;
}

async function pendingDrawer() {
  S.drawerKey = 'pending';
  await loadOverview();
  drawer('ממתין לך', 'עדכונים ידניים והרצות שמחכות לך', pendingList(S.ov.pending || []));
  bindPendingActions($('d-body'));
}

/* ── blueprints ───────────────────────────────────────────────────────────────────────────── */
async function pageBlueprints() {
  header('תבניות', 'סט מוכן של משבצות לסוג העסק — מתוך מחקר. תבנית מוסיפה משבצות וערוצים, ולעולם לא נוגעת בנכסים שכבר בחרתם.');
  const r = await api('api/blueprints');
  if (!r.ok) { $('view').innerHTML = `<div class="issue">${esc(errText(r.body))}</div>`; return; }
  $('view').innerHTML = `<div class="cards">${r.body.blueprints.map((b) => {
    const c = b.counts;
    return `<div class="card bp"><h3>${esc(lbl(b.name))} ${b.applied ? chip('הוחלה', 'ok', 'הוחלה ' + fmtAgo(b.applied.applied_at)) : ''}</h3>
      <div>${esc(lbl(b.summary))}</div>
      <div class="kv">${[['זיהוי', c.by_section.identity || 0], ['תוכן', c.by_section.content || 0], ['מדיה', c.by_section.media || 0],
        c.phases ? ['שלבים', c.phases] : null, b.extends.length ? ['מרחיבה את', b.extends.join(', ')] : null].filter(Boolean)
        .map(([k, v]) => `<div><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join('')}</div>
      <div class="note">מקורות: ${b.sources.map((s) => `<span class="mono">${esc(s.replace('research/', ''))}</span>`).join(' · ')}</div>
      <div class="row" style="margin-top:10px"><button class="btn sm primary" data-apply="${esc(b.id)}" title="יצירת המשבצות של התבנית">${ic('layers')}${b.applied ? 'החלה מחדש' : 'החלת התבנית'}</button>
        <button class="btn sm ghost" onclick="withQuery({bp:'${esc(b.id)}'})">פרטים</button></div></div>`;
  }).join('')}</div>`;
  $('view').querySelectorAll('[data-apply]').forEach((btn) => btn.onclick = () => withQuery({ bp: btn.dataset.apply }));
}
window.withQuery = withQuery;

async function blueprintDrawer(id) {
  S.drawerKey = 'bp:' + id;
  const r = await api(`api/blueprints/${encodeURIComponent(id)}`);
  if (!r.ok) return binaTell(errText(r.body), 'bad');
  const b = r.body;
  const needsD0 = (b.params || []).some((p) => p.id === 'launch_date');
  const d0 = ((b.applied || {}).params || {}).launch_date || (S.ov && S.ov.settings && S.ov.settings.launch_date) || '';
  drawer(esc(lbl(b.name)), esc(lbl(b.summary)), `
    <section><div class="kv">${[['משבצות', b.counts.slots], ['יחידות מדיה', b.counts.units], ['לוח שנה', b.counts.calendar], ['שרשרת', b.chain.join(' ← ')]]
      .map(([k, v]) => `<div><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join('')}</div>
      ${needsD0 ? `<label for="bp-d0">יום ההשקה (D0) — ממנו מתוארכות היחידות</label><input type="date" id="bp-d0" value="${esc(d0)}">` : ''}</section>
    ${(b.phases || []).length ? `<section><h4>השלבים</h4>${b.phases.map((p) => `<div class="pi" style="grid-template-columns:minmax(0,1fr) auto;margin-bottom:6px">
      <div style="min-width:0"><div class="c">${esc(lbl(p.name))}</div><div class="w">${esc((p.units || []).map((u) => lbl(u.name)).join(' · '))}</div></div>
      <span class="mono note">${esc(p.window || '')}</span></div>`).join('')}</section>` : ''}
    ${(b.slots || []).length ? `<section><h4>המשבצות של התבנית עצמה <span class="note">${b.slots.length}</span></h4>
      <div class="chips">${b.slots.slice(0, 60).map((s) => chip(lbl(s.label), 'plain', s.key)).join('')}${b.slots.length > 60 ? chip(`ועוד ${b.slots.length - 60}`, 'plain') : ''}</div></section>` : ''}
    ${(b.calendar || []).length ? `<section><h4>לוח השנה</h4><div class="chips">${b.calendar.map((c) => chip(lbl(c.name), 'plain', c.trigger)).join('')}</div></section>` : ''}`,
  `<button class="btn sm primary" id="bp-apply">${ic('layers')}${b.applied ? 'החלה מחדש' : 'החלת התבנית'}</button><span class="note">מוסיפה ומעדכנת הגדרות — לא מוחקת ולא משנה נכסים</span>`);
  $('bp-apply').onclick = () => busy($('bp-apply'), async () => {
    const params = {};
    if ($('bp-d0') && $('bp-d0').value) params.launch_date = $('bp-d0').value;
    const r2 = await post(`api/blueprints/${encodeURIComponent(id)}/apply`, { params });
    if (!r2.ok) return binaTell(errText(r2.body), 'bad');
    binaTell(`התבנית הוחלה: ${r2.body.created} משבצות חדשות, ${r2.body.refreshed} עודכנו`);
    closeDrawer(); S.ov = null; S.slotCache = {}; go('/');
  });
}

/* ── activity ─────────────────────────────────────────────────────────────────────────────── */
async function pageActivity() {
  header('פעילות', 'כל שינוי: מי, מה, ומתי — הבעלים, עזריה או הלשכה עצמה.');
  const r = await api('api/activity');
  if (!r.ok) { $('view').innerHTML = `<div class="issue">${esc(errText(r.body))}</div>`; return; }
  $('view').innerHTML = `<div class="card">${eventsList(r.body.events)}</div>`;
}

/* ── live updates: one change feed ────────────────────────────────────────────────────────── */
let refreshTimer = null;
function refreshSoon() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(async () => {
    S.ov = null; S.slotCache = {};
    await route();
    const q = parseHash().query;
    if (q.slot && !q.plan) { S.drawerKey = null; slotDrawer(q.slot); }
  }, 600);
}
function listen() {
  try {
    const es = new EventSource('api/events');
    es.onmessage = (m) => {
      let ev = {};
      try { ev = JSON.parse(m.data); } catch (e) { return; }
      if (['run', 'publication', 'post', 'asset', 'active'].includes(ev.type)) refreshSoon();
    };
  } catch (e) { /* no live feed: every action still refreshes its own screen */ }
}

route();
listen();
