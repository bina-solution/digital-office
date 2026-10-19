/* social-list — רשתות חברתיות. Vanilla JS, relative URLs only (served under /a/social-list/).
 *
 *   #/                  every network, its accounts, and how each account is connected
 *   #/a/<account>       one account: profile, recent posts, what it can do, what the office did
 *   #/matrix            the coverage matrix: op × network × implementation
 *   #/activity          every action the office performed on the owner's behalf
 *   ?connect=<network>  the connect wizard (network → how → details → verified)
 *   ?compose=<account>  a post            ?edit=<account>  the profile
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
const S = { ov: null, drawerKey: null };

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
  const r = await fetch(path, o).catch(binaNoAnswer);
  // a body that is not data is the sign-in page or the edge's own error page: named by its status
  let body = await r.json().catch(() => ({ error: binaSaid(r.status) })) || {};
  if (!r.ok && !body.error && !body.detail) body = Object.assign({}, body, { error: binaSaid(r.status) });
  return { ok: r.ok, status: r.status, body };
}
const send = (m, p, b) => api(p, { method: m, body: JSON.stringify(b || {}) });

const ICONS = {
  home: 'M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z',
  grid: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  activity: 'M3 12h4l2-5 4 10 2-5h6',
  plus: 'M12 5v14M5 12h14', x: 'M18 6 6 18M6 6l12 12', check: 'M20 6 9 17l-5-5',
  send: 'M22 2 11 13M22 2l-7 20-4-9-9-4z', refresh: 'M23 4v6h-6M1 20v-6h6M3.5 9a9 9 0 0 1 14.9-3.4L23 10M1 14l4.6 4.4A9 9 0 0 0 20.5 15',
  external: 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3',
  star: 'M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z',
  edit: 'M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z', play: 'M5 3l14 9-14 9z',
};
const ic = (n) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${ICONS[n] || ''}"/></svg>`;
const lbl = (o) => (o && (o.he || o.en)) || '';
const chip = (t, cls, title) => `<span class="chip ${cls || ''}" ${title ? `title="${esc(title)}"` : ''}>${esc(t)}</span>`;
const KIND_HE = { browser: 'דפדפן הלשכה', api: 'API רשמי' };
const KIND_CLS = { browser: 'plain', api: 'plain' };
// the network's terms about automating its site — information next to the network, never a switch
const TOS = { ban: ['התקנון אוסר אוטומציה', 'plain'], risk: ['התקנון מגביל אוטומציה', 'plain'], low: ['ללא הגבלה מיוחדת', 'plain'] };
// what a cell shows (markup: the check is drawn, never a character of the font), its class, its words
const ANS = { yes: [ic('check'), 'm-yes', 'נתמך'], limited: ['חלקי', 'm-limited', 'חלקי'], no: ['—', 'm-no', 'עוד לא'] };
const STATE_HE = { queued: 'בתור', running: 'רץ', ok: 'בוצע', error: 'נכשל', cancelled: 'בוטל',
  needs_verification: 'דורש הרצה בנוכחות', assert_failed: 'לא אומת' };
const PROBE_HE = { ok: ['מחובר', 'ok'], needs_action: ['דורש טיפול', 'owner'], unsupported: ['חיבור קריאה מוגבל', 'plain'], error: ['שגיאה', 'bad'] };
const errText = (b) => (b && (b.error || b.message)) || 'הפעולה נכשלה';
const fmtAgo = (ts) => { if (!ts) return ''; const s = Math.max(0, Date.now() / 1000 - (typeof ts === 'number' ? ts : Date.parse(ts) / 1000));
  return s < 60 ? 'עכשיו' : s < 3600 ? `לפני ${Math.round(s / 60)} דק׳` : s < 86400 ? `לפני ${Math.round(s / 3600)} שע׳` : `לפני ${Math.round(s / 86400)} ימים`; };

async function busy(btn, fn) {
  if (!btn) return fn();
  const html = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="spin"></span>${esc(btn.textContent.trim())}`;
  try { return await fn(); } finally { btn.disabled = false; btn.innerHTML = html; }
}
function issue(body) {
  const b = body || {};
  return `<div class="issue"><b>${esc(b.title || errText(b))}</b>${b.title && b.error !== b.title ? `<div>${esc(b.error)}</div>` : ''}
    ${b.why ? `<div class="note">${esc(b.why)}</div>` : ''}${b.how ? `<div class="note">${esc(b.how)}</div>` : ''}
    ${b.url ? `<div style="margin-top:6px"><a class="btn sm" href="${esc(b.url)}" target="_blank" rel="noopener">${ic('external')}פתיחה</a></div>` : ''}</div>`;
}

/* ── routing ─────────────────────────────────────────────────────────────────────────────── */
function parseHash() {
  const h = location.hash.replace(/^#/, '') || '/';
  const [path, qs] = h.split('?');
  const query = {};
  (qs || '').split('&').filter(Boolean).forEach((kv) => { const [k, v] = kv.split('='); query[decodeURIComponent(k)] = decodeURIComponent(v || ''); });
  return { path: path || '/', query };
}
function withQuery(extra) {
  const { path, query } = parseHash();
  const q = Object.assign({}, query, extra);
  const qs = Object.entries(q).filter(([, v]) => v != null && v !== '').map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&');
  location.hash = path + (qs ? '?' + qs : '');
}
window.withQuery = withQuery;
window.addEventListener('hashchange', route);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && $('drawer-root').innerHTML) closeDrawer(); });

function renderMenu(path) {
  const items = [{ p: '/', l: 'רשתות', i: 'home' }, { p: '/matrix', l: 'מה כל רשת יודעת', i: 'grid' }, { p: '/activity', l: 'פעילות', i: 'activity' }];
  const nAcc = S.ov ? S.ov.platforms.reduce((n, p) => n + p.accounts.length, 0) : null;
  $('menu').innerHTML = '<div class="bnv-list">' + items.map((m) => `<a class="bnv-item ${path === m.p || (m.p === '/' && path.startsWith('/a/')) ? 'is-active' : ''}" href="#${m.p}" title="${esc(m.l)}">
    <span class="bnv-ic">${ic(m.i)}</span><span class="bnv-label">${esc(m.l)}</span>
    <span class="bnv-tail">${m.p === '/' && nAcc != null ? `<span class="n">${nAcc}</span>` : ''}</span></a>`).join('') + '</div>';
  const b = S.ov && S.ov.browser;
  $('foot').innerHTML = b ? (b.available ? 'הדפדפן של הלשכה: מחובר' : `הדפדפן של הלשכה: ${esc(b.reason || 'לא זמין')}`) : '';
}

async function load() { const r = await api('api/overview'); if (r.ok) S.ov = r.body; return r; }

async function route() {
  const { path, query } = parseHash();
  if (!S.ov) await load();
  renderMenu(path);
  $('actions').innerHTML = '';
  try {
    if (path === '/') await pageNetworks();
    else if (path.startsWith('/a/')) await pageAccount(path.split('/')[2]);
    else if (path === '/matrix') await pageMatrix();
    else if (path === '/activity') await pageActivity();
  } catch (e) { $('view').innerHTML = `<div class="issue">העמוד לא נטען: ${esc(e.message || e)}</div>`; }
  syncDrawer(query);
  reportRoute();
}
function header(t, sub, actions) { $('title').textContent = t; $('sub').textContent = sub; $('actions').innerHTML = actions || ''; }

function tile(p) {
  return `<span class="mono-tile" style="background:${esc(p.color || 'var(--muted)')};font-size:${String(p.monogram || '').length > 1 ? 11 : 14}px">${esc(p.monogram || '')}</span>`;
}

/* ── networks ────────────────────────────────────────────────────────────────────────────── */
async function pageNetworks() {
  const r = await load();
  header('רשתות חברתיות', 'כל רשת שהעסק נמצא בה, מאחורי ממשק אחד — דרך הדפדפן של הלשכה, או ה-API של הרשת.',
    `<button class="btn sm ghost" id="b-self" title="מריץ את כל השרשרת מול רשת הבדיקה של הלשכה">${ic('play')}בדיקה עצמית</button>
     <button class="btn sm primary" id="b-conn">${ic('plus')}חיבור חשבון</button>`);
  $('b-conn').onclick = () => withQuery({ connect: 'pick' });
  $('b-self').onclick = () => busy($('b-self'), selftest);
  if (!r.ok) { $('view').innerHTML = issue(r.body); return; }
  const ov = r.body;
  const real = ov.platforms.filter((p) => !p.test);
  const test = ov.platforms.filter((p) => p.test);
  $('view').innerHTML = `${ov.vault_error ? `<div class="issue warn">${esc(ov.vault_error)} — החשבונות לא יוצגו עד שהשירות יחזור.</div>` : ''}
    <div class="cards">${real.concat(test).map(networkCard).join('')}</div>`;
  $('view').querySelectorAll('[data-connect]').forEach((b) => b.onclick = () => withQuery({ connect: b.dataset.connect }));
}
function networkCard(p) {
  const t = TOS[(p.tos || {}).level];
  const accts = p.accounts.map((a) => {
    const pr = a.probe ? (PROBE_HE[a.probe.state] || [a.probe.state, 'plain']) : null;
    return `<a class="pi" href="#/a/${esc(a.id)}" style="text-decoration:none;color:inherit;grid-template-columns:minmax(0,1fr) auto">
      <div style="min-width:0"><div class="c">${a.primary ? `<span title="החשבון הראשי">${ic('star')}</span> ` : ''}${esc(a.label)}</div>
        <div class="w">${esc(a.account_hint || '')}</div></div>
      <span class="row">${chip(KIND_HE[a.kind] || a.kind, KIND_CLS[a.kind])}${pr ? chip(pr[0], pr[1], a.probe.reason || '') : ''}</span></a>`;
  }).join('');
  const kinds = p.kinds.map((k) => chip(KIND_HE[k.kind] || k.kind, k.recommended ? 'ok' : 'plain', lbl(k.note))).join('');
  return `<div class="card"><h3><span class="row">${tile(p)} ${esc(lbl(p.name))}${p.test ? chip('בדיקה', 'owner') : ''}</span>
      <button class="btn sm" data-connect="${esc(p.id)}">${ic('plus')}חיבור</button></h3>
    <div class="chips" style="margin-bottom:8px">${kinds}${t ? chip(t[0], t[1], tosText(p)) : ''}</div>
    ${accts ? `<div class="plan">${accts}</div>` : '<div class="note">אין חשבון מחובר.</div>'}</div>`;
}

async function selftest() {
  const kinds = ['api', 'browser'];
  const out = [];
  for (const k of kinds) {
    const r = await send('POST', 'api/selftest', { kind: k });
    out.push({ k, r });
  }
  const body = out.map(({ k, r }) => `<section><h4>${esc(KIND_HE[k])} ${chip(r.ok && r.body.ok ? 'עבר' : 'נכשל', r.ok && r.body.ok ? 'ok' : 'bad')}</h4>
    <div class="plan">${((r.body || {}).steps || []).map((s) => `<div class="pi" style="grid-template-columns:auto minmax(0,1fr) auto">
      ${chip(s.ok ? 'עבר' : 'נכשל', s.ok ? 'ok' : 'bad')}<div class="c" title="${esc(s.step)}">${esc(((S.ov.ops || {})[s.step] || {}).he || s.step)}</div><span class="note num">${s.ms}ms</span></div>
      ${s.ok ? '' : issue(s.error)}`).join('') || issue(r.body)}</div></section>`).join('');
  drawer('בדיקה עצמית', 'כל השרשרת מול רשת הבדיקה של הלשכה: קריאת פרופיל → עדכון ביו → פוסט → רשימה → מחיקה', body);
  S.drawerKey = 'selftest';
}

/* ── one account ─────────────────────────────────────────────────────────────────────────── */
async function pageAccount(id) {
  const r = await api(`api/accounts/${encodeURIComponent(id)}`);
  if (!r.ok) { header('חשבון', ''); $('view').innerHTML = issue(r.body); return; }
  const a = r.body;
  const p = S.ov.platforms.find((x) => x.id === a.platform) || {};
  header(a.label, `${lbl(p.name)} · ${KIND_HE[a.kind] || a.kind}`,
    `<button class="btn sm primary" id="b-post">${ic('send')}פוסט</button>
     <button class="btn sm" id="b-edit">${ic('edit')}עריכת פרופיל</button>
     <button class="btn sm ghost" id="b-probe" title="בדיקה שהחשבון עובד עכשיו">${ic('refresh')}בדיקה</button>
     ${a.primary ? '' : '<button class="btn sm ghost" id="b-primary" title="החשבון שנבחר כשמבקשים את הרשת בלי מזהה">הפוך לראשי</button>'}
     <button class="btn sm danger" id="b-del">ניתוק</button>`);
  $('view').innerHTML = `<div class="cards">
      <div class="card" id="c-profile"><h3>פרופיל <span class="hint" id="p-age"></span></h3><div class="skel"></div></div>
      <div class="card" id="c-caps"><h3>מה החשבון הזה יודע לעשות</h3><div class="skel"></div></div>
      <div class="card" id="c-posts"><h3>פוסטים אחרונים</h3><div class="skel"></div></div>
      <div class="card" id="c-act"><h3>מה הלשכה עשתה בחשבון</h3><div class="skel"></div></div></div>`;
  $('b-post').onclick = () => withQuery({ compose: id });
  $('b-edit').onclick = () => withQuery({ edit: id });
  $('b-probe').onclick = () => busy($('b-probe'), async () => { const x = await send('POST', `api/accounts/${id}/probe`); binaTell(x.ok && x.body.probe && x.body.probe.ok ? 'החשבון עובד' : ((x.body.probe || {}).reason || errText(x.body)), x.ok && x.body.probe && x.body.probe.ok ? 'ok' : 'bad'); });
  if ($('b-primary')) $('b-primary').onclick = () => busy($('b-primary'), async () => { const x = await send('POST', `api/accounts/${id}/primary`); if (!x.ok) return binaTell(errText(x.body), 'bad'); S.ov = null; route(); });
  $('b-del').onclick = () => confirmDisconnect(a);
  loadProfile(id, false);
  loadCaps(id);
  loadPosts(id);
  loadActivity(id);
}
async function loadProfile(id, fresh) {
  const box = $('c-profile');
  const r = await api(`api/accounts/${id}/profile${fresh ? '?fresh=1' : ''}`);
  if (!box) return;
  if (!r.ok) { box.innerHTML = `<h3>פרופיל</h3>${issue(r.body)}`; return; }
  const v = r.body.value || {};
  box.innerHTML = `<h3>פרופיל <span class="hint">${r.body.stale ? 'ישן · ' : ''}${esc(fmtAgo(Date.now() / 1000 - (r.body.age || 0)))}
      <button class="btn sm ghost" id="p-fresh">${ic('refresh')}קריאה מחדש</button></span></h3>
    ${r.body.error_body ? issue(r.body.error_body) : ''}
    ${v.banner_url ? `<img class="banner" src="${esc(v.banner_url)}" alt="תמונת נושא">` : ''}
    <div class="profile">${v.avatar_url ? `<img class="av" src="${esc(v.avatar_url)}" alt="תמונת פרופיל">` : '<span class="av"></span>'}
      <div style="min-width:0"><div style="font-size:16px;font-weight:800">${esc(v.name || '—')}</div>
        <div class="note mono">${v.handle ? '@' + esc(v.handle) : ''}</div>
        <div style="margin-top:4px">${esc(v.bio || '')}</div>
        ${v.url ? `<a class="note out" href="${esc(v.url)}" target="_blank" rel="noopener">פתיחת הפרופיל${ic('external')}</a>` : ''}</div></div>`;
  $('p-fresh').onclick = () => busy($('p-fresh'), () => loadProfile(id, true));
}
async function loadCaps(id) {
  const r = await send('POST', 'capabilities', { account: id });
  const box = $('c-caps');
  if (!box) return;
  if (!r.ok) { box.innerHTML = `<h3>מה החשבון הזה יודע לעשות</h3>${issue(r.body)}`; return; }
  const ops = S.ov.ops || {};
  const script = r.body.script;
  box.innerHTML = `<h3>מה החשבון הזה יודע לעשות <span class="hint">${esc(KIND_HE[r.body.kind] || '')}</span></h3>
    <table class="matrix"><tbody>${Object.entries(r.body.ops || {}).map(([op, s]) => {
      const a = ANS[s.answer] || ANS.no;
      const st = script && script.ops && script.ops[op] ? script.ops[op].status : null;
      return `<tr><td>${esc((ops[op] || {}).he || op)}</td><td class="${a[1]}" title="${esc(s.why || a[2])}" aria-label="${esc(a[2])}">${a[0]}</td>
        <td class="note" style="text-align:start">${st ? chip(st === 'verified' ? 'תסריט מאומת' : st === 'observed' ? 'נצפה — דורש נוכחות' : 'טיוטה', st === 'verified' ? 'ok' : 'owner') : esc(s.why || '')}</td></tr>`;
    }).join('')}</tbody></table>`;
}
async function loadPosts(id) {
  const r = await api(`api/accounts/${id}/posts`);
  const box = $('c-posts');
  if (!box) return;
  if (!r.ok) { box.innerHTML = `<h3>פוסטים אחרונים</h3>${issue(r.body)}`; return; }
  const posts = r.body.value || [];
  box.innerHTML = `<h3>פוסטים אחרונים</h3>${r.body.error_body ? issue(r.body.error_body) : ''}
    ${posts.length ? `<div class="plan">${posts.map((p) => `<div class="pi" style="grid-template-columns:minmax(0,1fr) auto">
      <div style="min-width:0"><div class="c" style="font-weight:600;white-space:normal">${esc((p.text || '').slice(0, 200))}</div>
      <div class="w">${esc(fmtAgo(p.created_at))}${p.counts && p.counts.likes != null ? ` · ${p.counts.likes} לייקים` : ''}</div></div>
      ${p.url ? `<a class="btn sm ghost" href="${esc(p.url)}" target="_blank" rel="noopener">${ic('external')}</a>` : ''}</div>`).join('')}</div>` : '<div class="empty">אין פוסטים לקרוא (או שהחיבור הזה לא קורא).</div>'}`;
}
async function loadActivity(id) {
  const r = await api(`api/accounts/${id}/activity`);
  const box = $('c-act');
  if (!box) return;
  box.innerHTML = `<h3>מה הלשכה עשתה בחשבון</h3>${actList((r.body || {}).actions || [])}`;
}
function actList(rows) {
  if (!rows.length) return '<div class="empty">עוד לא בוצעה פעולה.</div>';
  const ops = (S.ov && S.ov.ops) || {};
  return `<div class="plan">${rows.map((x) => `<div class="pi" style="grid-template-columns:auto minmax(0,1fr) auto">
    ${chip(STATE_HE[x.state] || x.state, x.state === 'ok' ? 'ok' : x.state === 'needs_verification' ? 'owner' : 'bad', x.state)}
    <div style="min-width:0"><div class="c">${esc((ops[x.op] || {}).he || x.op)} ${x.summary ? `· <span class="note">${esc(x.summary)}</span>` : ''}</div>
      <div class="w">${esc(KIND_HE[x.kind] || x.kind)} · ${esc(x.actor && x.actor.startsWith('digital-assets') ? 'נכסים דיגיטליים' : x.actor === 'owner' ? 'הבעלים' : x.actor || '')}
      ${x.result && x.result.error ? ` · ${esc(x.result.error)}` : ''}</div></div>
    <span class="note">${esc(fmtAgo(x.at))}</span></div>`).join('')}</div>`;
}
async function confirmDisconnect(a) {
  // the office's own question: the action is not offered until the account's id is typed
  if (await binaAsk({ title: 'לנתק את החשבון מהלשכה?', ok: 'ניתוק', danger: true, facts: [['חשבון', a.label]],
    body: 'החשבון יוסר מהלשכה (מהכספת). בפלטפורמה עצמה לא ישתנה דבר.\nכל ערוץ ב„נכסים דיגיטליים” שקשור אליו יישאר בלי חשבון.',
    input: { label: 'להמשך, הקלד את מזהה החשבון: ' + a.id, must: a.id, dir: 'ltr' } }) == null) return;
  busy($('b-del'), async () => {
    const r = await api(`api/accounts/${encodeURIComponent(a.id)}?confirm=${encodeURIComponent(a.id)}`, { method: 'DELETE' });
    if (!r.ok) return binaTell(errText(r.body), 'bad');
    binaTell('החשבון נותק'); S.ov = null; location.hash = '#/';
  });
}

/* ── matrix & activity ───────────────────────────────────────────────────────────────────── */
async function pageMatrix() {
  header('מה כל רשת יודעת', 'כל פעולה × כל רשת × כל דרך חיבור, מתוך קטלוג הפלטפורמות (נבדק מול התיעוד הרשמי, 2026-09-29).');
  const r = await api('api/catalog');
  if (!r.ok) { $('view').innerHTML = issue(r.body); return; }
  const plats = r.body.platforms.filter((p) => !p.test);
  const ops = r.body.ops;
  const cell = (p, op, kind) => {
    const k = p.kinds.find((x) => x.kind === kind);
    if (!k) return '<td class="m-no">·</td>';
    const e = (p.ops || {})[op] || {};
    // the browser column also says how far its script is: verified / observed / draft — and an op
    // with no script yet is "not yet", whatever the network allows
    const scripted = !(kind === 'browser') || !!(p.script && p.script.ops && p.script.ops[op]);
    const a = ANS[e.na || !scripted ? 'no' : (e[kind] || 'no')] || ANS.no;
    const st = kind === 'browser' && scripted ? p.script.ops[op].status : null;
    const tip = [scripted ? (lbl(e.why) || a[2]) : 'עוד אין תסריט דפדפן לפעולה הזו', st ? SCRIPT_HE[st] : ''].filter(Boolean).join(' · ');
    return `<td class="${a[1]}" title="${esc(tip)}" aria-label="${esc(a[2])}">${a[0]}${st === 'verified' ? '' : st ? '<sup>*</sup>' : ''}</td>`;
  };
  $('view').innerHTML = `<div class="card" style="overflow:auto"><table class="matrix"><thead><tr><th>פעולה</th>${plats.map((p) =>
    `<th colspan="2" title="${esc(lbl(p.name))}">${tile(p)}</th>`).join('')}</tr>
    <tr><th></th>${plats.map(() => '<th>דפדפן</th><th>API</th>').join('')}</tr></thead>
    <tbody>${Object.keys(ops).map((op) => `<tr><td>${esc(ops[op].he)}</td>${plats.map((p) => cell(p, op, 'browser') + cell(p, op, 'api')).join('')}</tr>`).join('')}</tbody></table>
    <div class="note legend" style="margin-top:8px">${ic('check')} נתמך · חלקי · — עוד לא. <sup>*</sup> תסריט הדפדפן עוד לא אומת: פעולת כתיבה רצה בפעם הראשונה כשהבעלים צופה בתצוגת הדפדפן.</div></div>`;
}
async function pageActivity() {
  header('פעילות', 'כל פעולה שהלשכה ביצעה בשמכם: מי ביקש, מה רץ, ומה הפלטפורמה ענתה.');
  const r = await api('api/activity');
  $('view').innerHTML = `<div class="card">${actList((r.body || {}).actions || [])}</div>`;
}

/* ── drawers: connect, compose, edit ─────────────────────────────────────────────────────── */
function drawer(title, sub, body, foot) {
  document.body.classList.add('drawer-open');
  $('drawer-root').innerHTML = `<div class="scrim" id="scrim"></div><aside class="drawer" role="dialog" aria-modal="true" aria-label="${esc(title)}">
    <div class="drawer-head"><div style="min-width:0"><div class="dtitle">${esc(title)}</div><div class="note">${sub || ''}</div></div>
      <button class="icbtn" id="d-close" title="סגירה (Esc)">${ic('x')}</button></div>
    <div class="drawer-body" id="d-body">${body}</div>${foot ? `<div class="drawer-foot" id="d-foot">${foot}</div>` : ''}</aside>`;
  $('scrim').onclick = closeDrawer; $('d-close').onclick = closeDrawer;
}
function closeDrawer() {
  document.body.classList.remove('drawer-open'); $('drawer-root').innerHTML = ''; S.drawerKey = null;
  withQuery({ connect: null, compose: null, edit: null });
}
function syncDrawer(q) {
  if (q.connect) { if (S.drawerKey !== 'connect:' + q.connect) connectDrawer(q.connect); }
  else if (q.compose) { if (S.drawerKey !== 'compose:' + q.compose) composeDrawer(q.compose); }
  else if (q.edit) { if (S.drawerKey !== 'edit:' + q.edit) editDrawer(q.edit); }
  else if ($('drawer-root').innerHTML && S.drawerKey && S.drawerKey !== 'selftest') { document.body.classList.remove('drawer-open'); $('drawer-root').innerHTML = ''; S.drawerKey = null; }
}

function connectDrawer(pid) {
  S.drawerKey = 'connect:' + pid;
  const plats = S.ov.platforms;
  if (pid === 'pick') {
    drawer('חיבור חשבון', 'שלב 1 מתוך 3 — איזו רשת', `<div class="chgrid">${plats.map((p) => `<button class="kindcard" data-p="${esc(p.id)}">
      <div class="row">${tile(p)}<b>${esc(lbl(p.name))}</b>${p.test ? chip('בדיקה', 'owner') : ''}</div></button>`).join('')}</div>`);
    $('d-body').querySelectorAll('[data-p]').forEach((b) => b.onclick = () => withQuery({ connect: b.dataset.p }));
    return;
  }
  const p = plats.find((x) => x.id === pid);
  if (!p) return binaTell('רשת לא מוכרת', 'bad');
  drawer(`חיבור ${lbl(p.name)}`, 'שלב 2 מתוך 3 — איך הלשכה תדבר עם החשבון', `
    ${p.kinds.map((k) => `<button class="kindcard" data-k="${esc(k.kind)}">
      <div class="row"><b>${esc(KIND_HE[k.kind] || k.kind)}</b>${k.recommended ? chip('מומלץ', 'ok') : ''}</div>
      <div class="note" style="margin-top:4px">${esc(lbl(k.note) || kindExplain(k.kind))}</div></button>`).join('')}
    ${p.tos && p.tos.level !== 'low' ? `<div class="note" style="margin-top:8px">${esc(tosText(p))}</div>` : ''}
    <div id="k-form"></div>`);
  $('d-body').querySelectorAll('[data-k]').forEach((b) => b.onclick = () => {
    $('d-body').querySelectorAll('[data-k]').forEach((x) => x.classList.toggle('sel', x === b));
    kindForm(p, p.kinds.find((k) => k.kind === b.dataset.k));
  });
}
function kindExplain(k) {
  return { api: 'ה-API הרשמי של הפלטפורמה, עם טוקן שנשמר בכספת של הלשכה.',
    browser: 'הבעלים מתחבר פעם אחת בתצוגת הדפדפן של הלשכה, ומכאן הלשכה פועלת בחשבון כמו אדם — בקצב של אדם, רק בפעולות שהבעלים יזם.' }[k] || '';
}
const SCRIPT_HE = { verified: 'תסריט מאומת', observed: 'תסריט שנצפה — הרצה ראשונה בנוכחות', draft: 'תסריט בטיוטה' };
function tosText(p) {
  const lv = (p.tos || {}).level;
  return { ban: 'תנאי השימוש של הרשת אוסרים אוטומציה של האתר — הלשכה פועלת בקצב של אדם, רק בפעולות שהבעלים יזם.',
    risk: 'תנאי השימוש מגבילים גישה אוטומטית — הלשכה פועלת בקצב של אדם, רק בפעולות שהבעלים יזם.',
    low: 'אין הגבלה מיוחדת על פעולות מעטות מחשבון הבעלים.' }[lv] || '';
}
const NEED_HE = { page_id: 'מזהה העמוד', page_token: 'טוקן העמוד', ig_user_id: 'מזהה משתמש אינסטגרם', access_token: 'טוקן גישה',
  token: 'טוקן', org: 'שם הארגון (לא חובה)', repo: 'מאגר לפרסום owner/name (לא חובה)', bot_token: 'טוקן הבוט', guild_id: 'מזהה השרת',
  channel_id: 'מזהה הערוץ', phone_number_id: 'מזהה מספר הטלפון', channel: 'ערוץ', handle: 'שם המשתמש (בלי @)', phone: 'מספר טלפון בינלאומי' };
function kindForm(p, k) {
  const box = $('k-form');
  const needs = (k.needs || []).slice();
  if (k.kind === 'api' && p.id === 'github') needs.push('org', 'repo');
  if (k.kind === 'browser') {
    box.innerHTML = `<section><h4>שלב 3 — התחברות פעם אחת</h4>
      <div class="note">הלשכה תפתח את ${esc(lbl(p.name))} בדפדפן שלה ותקרא את הפרופיל כהוכחה. אם תופיע בקשת התחברות — התחברו בתצוגת הדפדפן, וחזרו לכאן.</div>
      ${needs.map((n) => `<label for="k-${n}">${esc(NEED_HE[n] || n)}</label><input id="k-${n}" class="mono">`).join('')}
      <label for="k-label">שם לחשבון (לא חובה)</label><input id="k-label" placeholder="${esc(lbl(p.name))} של העסק"></section>`;
  } else {
    box.innerHTML = `<section><h4>שלב 3 — הפרטים</h4>
      ${needs.map((n) => `<label for="k-${n}">${esc(NEED_HE[n] || n)}</label><input id="k-${n}" class="mono" ${/token/.test(n) ? 'type="password" autocomplete="off"' : ''}>`).join('')}
      <label for="k-label">שם לחשבון (לא חובה)</label><input id="k-label">
      ${k.help_url ? `<div class="note" style="margin-top:6px"><a class="out" href="${esc(k.help_url)}" target="_blank" rel="noopener">מאיפה מביאים את הפרטים${ic('external')}</a></div>` : ''}</section>`;
  }
  $('d-body').insertAdjacentHTML('afterend', '');
  const foot = document.querySelector('.drawer-foot') || (() => { const f = document.createElement('div'); f.className = 'drawer-foot'; f.id = 'd-foot'; document.querySelector('.drawer').appendChild(f); return f; })();
  foot.innerHTML = `<button class="btn sm primary" id="k-go">${ic('check')}${k.kind === 'browser' ? 'חיבור ובדיקה' : k.kind === 'api' ? 'אימות ושמירה' : 'שמירה'}</button><span class="note" id="k-state"></span>`;
  $('k-go').onclick = () => busy($('k-go'), async () => {
    const secret = {};
    needs.forEach((n) => { const v = ($(`k-${n}`) || {}).value; if (v) secret[n] = v.trim(); });
    const body = { platform: p.id, kind: k.kind, label: ($('k-label') || {}).value || '', secret };
    const r = await send('POST', k.kind === 'browser' ? 'api/accounts/browser' : 'api/accounts', body);
    const b = r.body || {};
    if (b.step === 'connected') { binaTell('החשבון מחובר'); S.ov = null; closeDrawer(); location.hash = `#/a/${b.id}`; return; }
    if (b.step === 'needs_human_login') {
      $('k-state').innerHTML = '';
      box.insertAdjacentHTML('beforeend', `<div class="issue warn"><b>צריך להתחבר פעם אחת</b><div class="note">${esc(b.how || '')}</div>
        <div class="row" style="margin-top:6px"><a class="btn sm" href="${esc(b.live_view || '/a/browser42/')}" target="_blank" rel="noopener">${ic('external')}תצוגת הדפדפן של הלשכה</a>
        <span class="note">אחרי ההתחברות — לחצו שוב „חיבור ובדיקה”.</span></div></div>`);
      return;
    }
    box.insertAdjacentHTML('beforeend', issue(b));
  });
}

async function composeDrawer(id) {
  S.drawerKey = 'compose:' + id;
  drawer('פוסט', 'דרך החשבון הזה — בחיבור שלו (דפדפן הלשכה או API)', `
    <label for="c-text">הטקסט</label><textarea id="c-text"></textarea><div class="note" id="c-n"></div>
    <label for="c-file">תמונה (לא חובה)</label><input type="file" id="c-file" accept="image/*">
    <label class="row note" style="margin-top:10px"><input type="checkbox" id="c-watch" style="width:auto"> אני צופה בדפדפן הלשכה (לתסריט שעוד לא אומת)</label>
    <div id="c-out"></div>`, `<button class="btn sm primary" id="c-go">${ic('send')}פרסום</button>`);
  $('c-text').oninput = () => { $('c-n').textContent = `${$('c-text').value.length} תווים`; };
  $('c-go').onclick = () => busy($('c-go'), async () => {
    const media = [];
    const f = $('c-file').files[0];
    if (f) {
      const b64 = await new Promise((res) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1]); r.readAsDataURL(f); });
      media.push({ kind: 'image', data_base64: b64, mime: f.type, name: f.name });
    }
    const r = await send('POST', `api/accounts/${id}/posts`, { post: { text: $('c-text').value, media }, watch: $('c-watch').checked, wait: 20, client: 'ui-' + Date.now() });
    showJob(r, $('c-out'));
  });
}
async function editDrawer(id) {
  S.drawerKey = 'edit:' + id;
  const pr = await api(`api/accounts/${id}/profile`);
  const v = (pr.body || {}).value || {};
  drawer('עריכת פרופיל', 'רק שדות שתשנו יישלחו. לשינוי זהות שמגיע לכל הרשתות — עדיף מתוך „נכסים דיגיטליים”.', `
    <label for="e-name">שם תצוגה</label><input id="e-name" value="${esc(v.name || '')}">
    <label for="e-bio">תיאור קצר</label><textarea id="e-bio">${esc(v.bio || '')}</textarea>
    <label for="e-av">תמונת פרופיל חדשה</label><input type="file" id="e-av" accept="image/*">
    <label class="row note" style="margin-top:10px"><input type="checkbox" id="e-watch" style="width:auto"> אני צופה בדפדפן הלשכה</label>
    <div id="e-out"></div>`, `<button class="btn sm primary" id="e-go">${ic('check')}שמירה</button>`);
  $('e-go').onclick = () => busy($('e-go'), async () => {
    const changes = {};
    if ($('e-name').value !== (v.name || '')) changes.name = $('e-name').value;
    if ($('e-bio').value !== (v.bio || '')) changes.bio = $('e-bio').value;
    const f = $('e-av').files[0];
    if (f) {
      const b64 = await new Promise((res) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1]); r.readAsDataURL(f); });
      changes.avatar = { kind: 'image', data_base64: b64, mime: f.type, name: f.name };
    }
    if (!Object.keys(changes).length) return binaTell('לא שונה דבר', 'warn');
    const r = await send('PATCH', `api/accounts/${id}/profile`, { changes, watch: $('e-watch').checked, wait: 25, client: 'ui-' + Date.now() });
    showJob(r, $('e-out'));
  });
}
function showJob(r, box) {
  const b = r.body || {};
  if (b.state === 'ok') {
    const res = b.result || {};
    box.innerHTML = `<div class="issue info" style="border-inline-start-color:var(--accent);background:var(--ok-soft)"><b>בוצע ואומת</b>
      ${res.url ? `<div><a class="out" href="${esc(res.url)}" target="_blank" rel="noopener">צפייה${ic('external')}</a></div>` : ''}</div>`;
    binaTell('בוצע'); S.ov = null;
    return;
  }
  if (b.state === 'queued' || b.state === 'running' || r.status === 202) { box.innerHTML = '<div class="issue info">עדיין רץ — התוצאה תופיע ביומן הפעילות.</div>'; return; }
  box.innerHTML = issue(b);
}
route();
try { const es = new EventSource('api/events'); es.onmessage = (m) => { try { const ev = JSON.parse(m.data); if (ev.type === 'job' && ['ok', 'error'].includes(ev.state)) { S.ov = null; } } catch (e) { /* */ } }; } catch (e) { /* */ }
