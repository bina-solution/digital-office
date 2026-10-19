/* domains — חשבונות ← דומיינים ← הגדרות דומיין. Vanilla JS, כתובות יחסיות בלבד (הקונסול מגיש
 * את האפליקציה ב-/a/domains/ ומזריק <base href>).
 *
 * המסך בנוי סביב שני הניווטים שהאפליקציה באמת עושה:
 *   #/                                  → חשבונות, והדומיינים של החשבון הנבחר
 *   #/a/<account>                       → אותו מסך, עם חשבון מסוים נבחר
 *   #/a/<account>/d/<name>/<tab>        → סקירה · רשומות · תפוצה · פעולות · יומן
 *   #/a/<account>/d/<name>/records/<id> → מגירת עריכת רשומה (id או "new")
 *
 * שלוש החלטות עיצוב שהמסך הזה בנוי עליהן:
 *   1. **מגירה ולא מודאל** — עריכת רשומה היא משימה שמסתכלים בה גם על הרשימה שמאחוריה, ושמירה אחת
 *      בסוף. (הכשל הידוע בכלי DNS אחרים: מודאל שנשפך עם מחרוזת TXT ארוכה, וכפתור שמירה שדורש
 *      שמירה שנייה כדי שבאמת יישמר.)
 *   2. **diff לפני שמירה** — מה שהיה מול מה שיהיה, לפני שנוגעים במשהו.
 *   3. **תפוצה בסדר הנכון** — קודם מה שהאזור עצמו עונה, אחר כך המאחזרים, עם ה-TTL שנותר.
 */
'use strict';

const $ = (id) => document.getElementById(id);
const S = { accounts: [], active: null, domains: [], domain: null, providers: [], health: null,
            filter: '', typeFilter: '' };

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
  const r = await fetch(path, Object.assign({ headers: { 'content-type': 'application/json' } },
    opts || {})).catch(binaNoAnswer);
  // a body that is not data is the sign-in page or the edge's own error page: named by its status
  let body = await r.json().catch(() => ({ error: binaSaid(r.status) })) || {};
  if (!r.ok && !body.error && !body.detail) body = Object.assign({}, body, { error: binaSaid(r.status) });
  return { ok: r.ok, status: r.status, body };
}
const esc = Store.esc;

const ACCESS = { browser: ['מחובר בדפדפן', 'warn'], api: ['דרך API', 'plain'],
                 registry: ['רישום ציבורי', 'plain'] };
const accessChip = (a) => {
  const [txt, cls] = ACCESS[a] || [a || '—', 'plain'];
  return `<span class="chip ${cls}">${esc(txt)}</span>`;
};
function expiryCell(d) {
  const days = d.days_left;
  if (days == null) return '<span class="exp unknown">—</span>';
  const label = days < 0 ? `פג לפני ${-days} ימים` : `${days} ימים`;
  return `<span class="exp ${esc(d.expiry_state || 'unknown')}">${esc(label)}</span>
    <div class="note ltr">${esc(d.expiry_iso || '')}</div>`;
}
function out(el, text, kind) {
  if (!el) return;
  el.className = 'out ' + (kind || '');
  el.textContent = typeof text === 'string' ? text : JSON.stringify(text, null, 2);
  el.classList.remove('hidden');
}

/* ── errors: ONE renderer, ONE place, ONE vocabulary ────────────────────────────────────────────
 *
 * The same refusal used to appear in three different shapes — a browser alert() from a finished job,
 * a raw monospace box with `DomainError:` in front of it inside the drawer, and a plain string in the
 * tab — so the owner could not tell a defect from a policy, or one problem from three. Everything a
 * source refuses now goes through here: the title, what happened, why, and what to do about it,
 * including the door to do it by hand. The body comes from the server, which is the only place that
 * knows which of the three situations it is.
 */
function showError(el, body) {
  if (!el) return;
  const b = body || {};
  const message = b.error || b.message || 'הפעולה נכשלה';
  const known = b.title || b.why || b.how;
  if (!known) {                                   // an unexpected failure: say so, in one line
    el.className = 'issue err';
    el.innerHTML = `<b>${esc(message)}</b>`;
    el.classList.remove('hidden');
    return;
  }
  el.className = 'issue err';
  el.innerHTML = `
    <b>${esc(b.title || message)}</b>
    ${b.title && message !== b.title ? `<div>${esc(message)}</div>` : ''}
    ${b.why ? `<div class="note">${esc(b.why)}</div>` : ''}
    ${b.how ? `<div class="note">${esc(b.how)}</div>` : ''}
    ${b.portal_url ? `<div style="margin-top:8px">
      <a class="btn" href="${esc(b.portal_url)}" target="_blank" rel="noopener">
        פתח את הפורטל ועשה זאת ידנית ↗</a></div>` : ''}`;
  el.classList.remove('hidden');
}
/** The refusal a finished job carries, so a job failure reads exactly like a synchronous one. */
function refusalOf(job) {
  const body = ((job || {}).result || {}).error_body;
  return body && typeof body === 'object' ? body : null;
}
/** Where an error should be shown: the drawer when one is open, otherwise the tab's own box. */
function errorTarget() {
  return $('d-out') || $('op-out') || $('tab');
}
const go = (hash) => { location.hash = hash; };
window.addEventListener('hashchange', render);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });

// ── boot ─────────────────────────────────────────────────────────────────────────────────────────
async function boot() {
  $('btn-refresh').onclick = () => { Store.invalidate(''); render(); };
  $('btn-add').onclick = () => showAddAccount();
  Store.events((job) => renderJobs([job]));
  Store.onJob(() => renderJobs(Store.activeJobs()));
  const p = await api('providers');
  if (p.ok) S.providers = p.body.providers || [];
  render();
}

/* עבודות פעילות: כל פעולה שלוקחת זמן מציגה את עצמה כאן, עם ההתקדמות — כדי שאף פעולה לא תיראה תקועה. */
function renderJobs(list) {
  const box = $('jobs');
  const active = (list && list.length ? list : Store.activeJobs()).filter(
    (j) => ['queued', 'running', 'error'].includes(j.state));
  if (!active.length) { box.classList.add('hidden'); box.innerHTML = ''; return; }
  box.classList.remove('hidden');
  box.innerHTML = active.slice(0, 3).map((j) => `
    <div class="job ${j.state === 'error' ? 'bad' : ''}" role="status">
      <div class="t"><span>${esc(j.title || j.name || 'פעולה')}</span>
        ${j.state === 'running' ? `<span class="note">${Math.round(j.progress || 0)}%</span>` : ''}</div>
      <div class="m">${esc(j.message || (j.state === 'queued' ? 'בתור' : ''))}</div>
      <div class="bar"><i style="width:${Math.round(j.progress || 0)}%"></i></div>
    </div>`).join('');
}

// ── the side menu ────────────────────────────────────────────────────────────────────────────────
// One place that knows what this app's menu contains, called by every route: the address (all the
// accounts) and, once a domain is open, that domain's sections — the pill row this replaced. The
// rows are the shared component's (.bnv-item / .bnv-ic / .bnv-label), so this app contributes ids
// and labels and nothing about size, colour or hover.
const DOMAIN_TABS = [['overview', 'סקירה'], ['records', 'רשומות'],
                     ['health', 'תפוצה ובריאות'], ['ops', 'פעולות'], ['activity', 'יומן']];
const MENU_ICONS = {
  home: 'M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z',
  overview: 'M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
  records: 'M4 4h16v16H4zM8 9h8M8 13h8M8 17h5',
  health: 'M3 12h4l2-5 4 10 2-5h6',
  ops: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8a2 2 0 1 1-2.8 2.8A1.7 1.7 0 0 0 14 21a2 2 0 1 1-4 0 1.7 1.7 0 0 0-2.9-1.2a2 2 0 1 1-2.8-2.8A1.7 1.7 0 0 0 3 14a2 2 0 1 1 0-4 1.7 1.7 0 0 0 1.2-2.9a2 2 0 1 1 2.8-2.8A1.7 1.7 0 0 0 10 3a2 2 0 1 1 4 0 1.7 1.7 0 0 0 2.9 1.2a2 2 0 1 1 2.8 2.8A1.7 1.7 0 0 0 21 10a2 2 0 1 1 0 4',
  activity: 'M3 3v18h18M7 14l3-4 3 3 5-7',
  x: 'M18 6 6 18M6 6l12 12',
};
const menuIcon = (n) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${MENU_ICONS[n] || MENU_ICONS.home}"/></svg>`;
function menuRow(label, icon, active, onclick, tail) {
  const a = document.createElement('button');
  a.type = 'button';
  a.className = 'bnv-item' + (active ? ' is-active' : '');
  a.title = label;
  // The count rides in the TRAILING slot — the same place app-management puts its own. Inside the
  // label it would push a long label out of the row; two apps counting in two different places is
  // the inconsistency this whole pass exists to remove.
  a.innerHTML = `<span class="bnv-ic">${menuIcon(icon)}</span><span class="bnv-label">${esc(label)}</span>`
              + (tail == null ? '' : `<span class="bnv-tail"><span class="n">${esc(String(tail))}</span></span>`);
  a.onclick = onclick;
  return a;
}
function renderMenu(aid, name, tab) {
  const box = $('menu'); if (!box) return;
  box.innerHTML = '';
  const home = document.createElement('div'); home.className = 'bnv-list';
  home.appendChild(menuRow('כל החשבונות', 'home', !name, () => go('#/')));
  box.appendChild(home);
  if (!name) return;
  const g = document.createElement('div'); g.className = 'bnv-group'; g.textContent = name;
  box.appendChild(g);
  const list = document.createElement('div'); list.className = 'bnv-list';
  for (const [k, t] of DOMAIN_TABS) {
    list.appendChild(menuRow(
      t, k, k === tab, () => go(`#/a/${aid}/d/${encodeURIComponent(name)}/${k}`),
      k === 'records' ? ((S.domain && S.domain.records) || []).length : null));
  }
  box.appendChild(list);
}

async function render() {
  const parts = (location.hash || '#/').replace(/^#/, '').split('/').filter(Boolean);
  if (parts[0] === 'a' && parts[1] && parts[2] === 'd' && parts[3]) {
    const name = decodeURIComponent(parts[3]);
    const tab = parts[4] || 'overview';
    renderMenu(parts[1], name, tab);
    const rid = parts[5] ? decodeURIComponent(parts[5]) : null;
    await domainView(parts[1], name, tab);
    if (rid) openDrawer(parts[1], name, rid);
    else closeDrawer();
    return;
  }
  closeDrawer();
  renderMenu(null, null, null);
  return homeView(parts[1] || null);
}

// ── home: accounts on the side, that account's domains in the middle ─────────────────────────────
async function homeView(accountId) {
  $('view').innerHTML = `<div class="layout"><div><section class="card"><h3>חשבונות</h3>
    ${Store.skeleton(3)}</section></div><div><section class="card"><h3>הדומיינים של החשבון</h3>
    ${Store.skeleton(4)}</section></div></div>`;
  const a = await Store.res('accounts', 'api/accounts', { ttl: 30 });
  if (!a.ok) {
    const raw = await api('api/accounts');
    if (!raw.ok) return fail(raw);
  }
  S.accounts = (a.value || {}).connections || [];
  S.active = (a.value || {}).active;
  const chosen = accountId || S.active || (S.accounts[0] || {}).id || null;
  const chosenLabel = (S.accounts.find((x) => x.id === chosen) || {}).label || '';
  $('title').textContent = 'דומיינים';
  $('sub').textContent = 'חשבונות של ספקי דומיינים, והדומיינים שבתוכם — עם כל מה שאפשר לעשות בכל אחד.';
  $('state').className = 'live';
  $('state').innerHTML = Store.fresh(a) + ' ';
  $('state').textContent = S.accounts.length
    ? `${S.accounts.length} חשבונות · ${chosenLabel}` : 'אין חשבונות';

  const cards = S.accounts.map((x) => `
    <div class="acct ${x.id === chosen ? 'active' : ''}" data-aid="${esc(x.id)}">
      <div class="top">
        <div><div class="name">${esc(x.label || x.provider)}</div>
          <div class="meta">${esc(x.login || x.account_hint || '')}</div></div>
        <span class="chip ${x.ok ? 'ok' : x.state === 'needs_action' ? 'warn' : 'bad'}">
          ${x.ok ? 'מחובר' : esc(x.state === 'needs_action' ? 'דורש טיפול' : (x.state || 'לא נבדק'))}</span>
      </div>
      <div class="meta" style="margin-top:6px">${accessChip(x.access)}
        <span class="chip plain">${x.domains_watched || 0} דומיינים במעקב</span>
        ${x.id === S.active ? '<span class="chip ok">פעיל</span>' : ''}</div>
      ${x.reason ? `<div class="meta" style="color:var(--red)">${esc(x.reason)}</div>` : ''}
      <div class="actions-row" style="margin-top:8px">
        ${x.id === S.active ? '' : '<span class="link" data-act="use">הפעל</span>'}
        <span class="link" data-act="probe">בדיקה</span>
        <span class="link" data-act="drop" style="color:var(--red)">נתק</span>
      </div>
    </div>`).join('');

  $('view').innerHTML = `
    <div class="layout">
      <div><section class="card"><h3>חשבונות <span class="hint">ספקי דומיינים</span></h3>
        ${cards || '<div class="note">עוד אין חשבונות. „הוספת חשבון” בוחר ספק — דרך API או דרך התחברות בדפדפן.</div>'}
      </section></div>
      <div><section class="card" id="domains-card"></section></div>
    </div>`;

  document.querySelectorAll('[data-aid]').forEach((el) => {
    el.onclick = async (ev) => {
      const act = ev.target.dataset ? ev.target.dataset.act : null;
      const aid = el.dataset.aid;
      if (act === 'use') {
        await api(`api/accounts/${encodeURIComponent(aid)}/activate`, { method: 'POST' });
        return go('#/a/' + aid);
      }
      if (act === 'probe') { await api(`api/accounts/${encodeURIComponent(aid)}/probe`); return render(); }
      if (act === 'drop') {
        if (!await binaAsk({ title: 'לנתק את החשבון?', ok: 'ניתוק', danger: true,
                             body: 'הסוד נמחק מהכספת; הדומיינים ימשיכו להיות במעקב.' })) return;
        await api(`api/accounts/${encodeURIComponent(aid)}`, { method: 'DELETE' });
        return homeView(null);
      }
      go('#/a/' + aid);
    };
  });
  if (chosen) loadAccountDomains(chosen);
  else $('domains-card').innerHTML = '<h3>הדומיינים</h3><div class="note">בחר חשבון.</div>';
}

async function loadAccountDomains(aid, sync) {
  const box = $('domains-card');
  if (!box) return;
  box.innerHTML = `<h3>הדומיינים של החשבון <span class="hint">נקרא מהספק — עשוי לקחת רגעים</span></h3>
    ${Store.skeleton(4)}`;
  let r;
  if (sync) {
    const a = await api(`api/accounts/${encodeURIComponent(aid)}/domains?sync=1`);
    r = { ok: a.ok, body: a.body };
    Store.invalidate(`domains:${aid}`);
  } else {
    const cached = await Store.res(`domains:${aid}`, `api/accounts/${encodeURIComponent(aid)}/domains`,
                                   { ttl: 180 });
    r = { ok: cached.ok, body: cached.value || {} };
    if (cached.ok) r.body._fresh = Store.fresh(cached);
  }
  if (!r.ok || r.body.error) {
    box.innerHTML = `<h3>הדומיינים של החשבון</h3>
      <div class="out err">${esc(r.body.error || binaSaid(r.status))}</div>
      ${r.body.how ? `<div class="note" style="margin-top:8px">${esc(r.body.how)}</div>` : ''}`;
    return;
  }
  S.domains = r.body.domains || [];
  const src = { browser: 'נקרא מהפורטל בדפדפן של הלשכה', api: 'נקרא מה-API של הספק',
                registry: 'נקרא מהרישום הציבורי' }[r.body.source] || r.body.source;
  box.innerHTML = `
    <h3>הדומיינים של החשבון ${r.body._fresh || ''}
      <span class="hint">${esc(src)} · ${S.domains.length} דומיינים</span>
      <button class="btn" id="do-sync">סנכרן למעקב</button></h3>
    ${sync && r.body.synced ? `<div class="out ok">נוספו: ${esc((r.body.synced.added || []).join(', ') || '—')} · עודכנו: ${esc((r.body.synced.updated || []).join(', ') || '—')}</div>` : ''}
    <table class="grid-t"><thead><tr><th>דומיין</th><th>תוקף</th><th>שרתי שמות</th>
      <th>במעקב</th><th></th></tr></thead><tbody>
      ${S.domains.map((d) => `<tr class="click" data-d="${esc(d.name)}">
        <td><span class="dname">${esc(d.name)}</span>
          ${d.contact || d.status ? `<div class="note">${esc(d.contact || d.status)}</div>` : ''}</td>
        <td>${expiryCell({ days_left: d.days_left, expiry_state: d.expiry_state,
                           expiry_iso: d.expiry_iso })}</td>
        <td class="ltr note">${esc((d.nameservers || []).slice(0, 2).join(', ') || '—')}</td>
        <td>${d.watched ? '<span class="chip ok">כן</span>' : '<span class="chip plain">לא</span>'}</td>
        <td class="note">הגדרות ←</td></tr>`).join('')
        || '<tr><td colspan="5" class="note">לא נמצאו דומיינים בחשבון הזה.</td></tr>'}
    </tbody></table>`;
  if ($('do-sync')) $('do-sync').onclick = () => loadAccountDomains(aid, true);
  document.querySelectorAll('[data-d]').forEach((tr) => {
    tr.onclick = () => go(`#/a/${aid}/d/${encodeURIComponent(tr.dataset.d)}`);
  });
}

// ── one domain ──────────────────────────────────────────────────────────────────────────────────
async function domainView(aid, name, tab) {
  const url = `api/accounts/${encodeURIComponent(aid)}/domains/${encodeURIComponent(name)}`;
  if (!Store.peek('domain:' + aid + ':' + name)) {
    $('view').innerHTML = `<section class="card"><h3>${esc(name)}</h3>${Store.skeleton(5)}</section>`;
  }
  const res = await Store.res('domain:' + aid + ':' + name, url, { ttl: 180 });
  const d = res.value || {};
  if (!res.ok && !d.domain) {
    const raw = await api(url);
    if (!raw.ok) return fail(raw);
    return domainView(aid, name, tab);
  }
  d._fresh = Store.fresh(res);
  S.domain = d;
  $('title').textContent = name;
  $('sub').textContent = `${(d.account || {}).label || aid} · ${(d.account || {}).provider || ''}`;
  const errors = (d.conflicts || []).filter((c) => c.severity === 'error');
  // the chip says this view's own fact: opened by its address it went on saying «טוען…» over a loaded domain
  $('state').className = 'live' + (errors.length ? ' bad' : '');
  const many = (n, one, more) => (n === 1 ? one : `${n} ${more}`);
  $('state').textContent = errors.length ? many(errors.length, 'בעיה אחת', 'בעיות')
    : many((d.records || []).length, 'רשומה אחת', 'רשומות');
  $('view').innerHTML = `
    <section class="card">
      <h3><span class="link" id="back">← חזרה לדומיינים</span>
        <span class="hint">${d._fresh || ''} ${esc((d.registry || {}).registrar || '')}</span></h3>
      <div class="grid2">
        <div><div class="note">תוקף</div><div>${expiryCell({ days_left: (d.registry || {}).days_left,
          expiry_state: (d.registry || {}).expiry_state,
          expiry_iso: (d.registry || {}).expiry_date })}</div></div>
        <div><div class="note">סטטוס ברישום</div><div>${esc((d.registry || {}).status || '—')}</div></div>
        <div><div class="note">מי מחזיק ב-Zone</div><div>${esc((d.zone_holder || {}).zone_holder || '—')}</div></div>
        <div><div class="note">רשומות</div><div>${(d.records || []).length} (${esc(d.records_source || '—')})</div></div>
      </div>
      ${errors.length ? `<div class="issues" style="margin-top:10px">${errors.map((c) => `
        <div class="issue err"><b>${esc(c.title)}</b><div class="note">${esc(c.why || '')}</div>
          <div class="note">${esc(c.fix || '')}</div></div>`).join('')}</div>` : ''}
      <div id="tab"></div>
    </section>`;
  $('back').onclick = () => go('#/a/' + aid);
  renderMenu(aid, name, tab);
  ({ overview: tabOverview, records: tabRecords, health: tabHealth, ops: tabOps,
     activity: tabActivity }[tab] || tabOverview)(d);
}

function tabOverview(d) {
  const z = d.zone_holder || {}, w = d.world_dns || {}, reg = d.registry || {};
  const zoneRows = Object.entries(z).map(([k, v]) => `<tr><td class="note">${esc(k)}</td>
     <td class="ltr">${esc(Array.isArray(v) ? v.join(', ') : (v || '—'))}</td></tr>`).join('');
  const dnsRows = Object.entries(w.records || {}).map(([t, vals]) =>
    `<tr><td>${esc(t)}</td><td class="ltr">${esc((vals || []).join(', ') || '—')}</td></tr>`).join('');
  $('tab').innerHTML = `
    <div class="grid2">
      <div><h3 style="font-size:14px">הרישום (WHOIS)</h3>
        <div class="kv">
          <div class="k">רשם</div><div>${esc(reg.registrar || '—')}</div>
          <div class="k">תוקף</div><div class="ltr">${esc(reg.expiry_date || '—')}</div>
          <div class="k">שרתי שמות</div><div class="ltr">${esc((reg.nameservers || []).join(', ') || '—')}</div>
          <div class="k">נבדק</div><div>${esc(reg.last_whois ? new Date(reg.last_whois * 1000).toLocaleString('he-IL') : '—')}</div>
        </div></div>
      <div><h3 style="font-size:14px">ה-Zone ומי שמחזיק בו</h3>
        <table class="grid-t"><tbody>${zoneRows || '<tr><td class="note">—</td></tr>'}</tbody></table>
        ${z.action ? `<div class="note" style="margin-top:8px">${esc(z.action)}</div>` : ''}</div>
    </div>
    <h3 style="font-size:14px;margin-top:14px">מה שהעולם מקבל (1.1.1.1 — לא הספק)</h3>
    <table class="grid-t"><tbody>${dnsRows || '<tr><td class="note">אין תשובה</td></tr>'}</tbody></table>`;
}

// ── records: a table you scan, a drawer you edit in ─────────────────────────────────────────────
const TTL_PRESETS = ['300', '3600', '86400'];

/** A record's identity in the URL: its provider id when it has one, else name+type. */
function recordKey(r) {
  return r.id ? `id:${r.id}` : `nt:${r.type}:${r.name}`;
}
function findRecord(d, key) {
  if (key === 'new') return { type: 'A', name: '@', content: '', ttl: '3600', _new: true };
  const recs = d.records || [];
  if (key.startsWith('id:')) return recs.find((r) => String(r.id) === key.slice(3)) || null;
  const parts = key.split(':');
  return recs.find((r) => r.type === parts[1] && r.name === parts[2]) || null;
}
function shortName(name, domain) {
  if (!name) return '@';
  let n = String(name).replace(/\.$/, '');
  if (domain && n === domain) return '@';
  if (domain && n.endsWith('.' + domain)) n = n.slice(0, -(domain.length + 1));
  return n || '@';
}

function tabRecords(d) {
  const recs = d.records || [];
  const editable = !d.records_read_only;
  $('tab').innerHTML = `
    <div class="bar-row">
      <h3 style="font-size:14px;margin:0">רשומות ה-DNS
        <span class="hint">${esc(d.records_source || '')}${d.records_read_only ? ' · לקריאה בלבד' : ''}</span>
      </h3>
      ${editable ? '<button class="btn primary" id="rec-new">הוספת רשומה</button>' : ''}
    </div>
    ${d.records_stale ? `<div class="issue warn"><b>הקריאה האחרונה מהפאנל נכשלה — זו הרשימה שנקראה לאחרונה</b>
      <div class="note">${esc(d.records_error || '')}</div></div>` : ''}
    ${d.records_error && !d.records_stale ? `<div class="out err">${esc(d.records_error)}</div>` : ''}
    ${writeNotice(d)}
    ${(d.conflicts || []).length ? `<div class="issues">${d.conflicts.map((c) => `
      <div class="issue ${c.severity === 'error' ? 'err' : 'warn'}"><b>${esc(c.title)}</b>
        <div class="note">${esc(c.why || '')} ${esc(c.fix || '')}</div></div>`).join('')}</div>` : ''}
    <div class="filters">
      <input id="f-text" placeholder="סינון לפי שם או ערך…" value="${esc(S.filter)}">
      <select id="f-type"><option value="">כל הסוגים</option>
        ${[...new Set(recs.map((r) => r.type))].sort().map((t) =>
          `<option ${S.typeFilter === t ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select>
      <span class="note" id="f-count"></span>
    </div>
    <div class="scroll-x"><table class="grid-t recs"><thead><tr>
      <th>סוג</th><th>שם</th><th>ערך</th><th>TTL</th><th></th></tr></thead>
      <tbody id="rec-body"></tbody></table></div>`;
  const paint = () => {
    const q = S.filter.trim().toLowerCase();
    const rows = recs.filter((r) => (!S.typeFilter || r.type === S.typeFilter)
      && (!q || `${r.name} ${r.content}`.toLowerCase().includes(q)));
    $('f-count').textContent = `${rows.length} מתוך ${recs.length}`;
    const body = $('rec-body');
    if (!body) return;
    body.innerHTML = rows.map((r) => `
      <tr class="click" data-key="${esc(recordKey(r))}" tabindex="0">
        <td><span class="rtype">${esc(r.type || '')}</span></td>
        <td class="ltr">${esc(shortName(r.name, d.domain))}</td>
        <td class="ltr val">${esc(r.content || '')}
          ${r.priority ? `<span class="note"> · עדיפות ${esc(r.priority)}</span>` : ''}</td>
        <td class="ltr note">${esc(r.ttl || '—')}</td>
        <td class="row-actions">${editable ? '<span class="link">עריכה</span>' : ''}
          <button class="copy" title="העתקת הערך" aria-label="העתקת הערך"
            data-copy="${esc(r.content || '')}">⧉</button></td>
      </tr>`).join('') || '<tr><td colspan="5" class="note">אין רשומות שמתאימות לסינון.</td></tr>';
    body.querySelectorAll('[data-key]').forEach((tr) => {
      const open = () => go(`#/a/${d.account.id}/d/${encodeURIComponent(d.domain)}/records/`
                            + encodeURIComponent(tr.dataset.key));
      tr.onclick = (ev) => { if (!ev.target.dataset.copy) open(); };
      tr.onkeydown = (ev) => { if (ev.key === 'Enter') open(); };
    });
    body.querySelectorAll('[data-copy]').forEach((b) => {
      b.onclick = (ev) => { ev.stopPropagation(); Store.copy(b.dataset.copy, b); };
    });
  };
  $('f-text').oninput = (e) => { S.filter = e.target.value; paint(); };
  $('f-type').onchange = (e) => { S.typeFilter = e.target.value; paint(); };
  if ($('rec-new')) $('rec-new').onclick = () =>
    go(`#/a/${d.account.id}/d/${encodeURIComponent(d.domain)}/records/new`);
  paint();
}


/** Can the office write here at all? Asked BEFORE a click, because a refusal after one reads as a bug.
 *
 * Deliberately an informational box and not an error: nothing has gone wrong, and the sentence says
 * what WOULD unlock it. It is the same three lines the server returns on a refusal, from the same
 * payload field — one situation, one wording, wherever it is met.
 */
function writeNotice(d) {
  const w = d.write || {};
  if (!w.enabled) {
    return `<div class="issue warn" id="write-notice">
      <b>${esc(w.title || 'הלשכה עוד לא כותבת במקור הזה')}</b>
      ${w.why ? `<div class="note">${esc(w.why)}</div>` : ''}
      ${w.how ? `<div class="note">${esc(w.how)}</div>` : ''}
      ${(w.missing || []).length ? `<div class="note">עוד לא ממופה כאן: ${esc(w.missing.join(', '))}</div>` : ''}
      ${w.portal_url ? `<div style="margin-top:8px">
        <a class="btn" href="${esc(w.portal_url)}" target="_blank" rel="noopener">
          פתח את הפורטל ועשה זאת ידנית ↗</a></div>` : ''}
    </div>`;
  }
  if ((w.missing || []).length) {
    return `<div class="issue warn" id="write-notice">
      <b>${esc(w.title)}</b>
      <div class="note">${esc(w.why)}</div>
      <div class="note">${esc(w.how)}</div></div>`;
  }
  return '';
}
/** One action's availability, so the button says it before it is pressed. */
function actionAllowed(d, action) {
  const w = d.write || {};
  if (w.enabled === undefined) return true;
  if (w.actions && w.actions[action] === false) return false;
  return !!w.enabled || (w.actions || {})[action] === true;
}

// ── the drawer: ONE record, edited in place, saved once ─────────────────────────────────────────
function drawerEl() {
  let el = $('drawer');
  if (!el) {
    el = document.createElement('div');
    el.id = 'drawer';
    el.className = 'drawer hidden';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    document.body.appendChild(el);
  }
  return el;
}
function closeDrawer() {
  const el = $('drawer');
  if (el) { el.classList.add('hidden'); el.innerHTML = ''; }
  document.body.classList.remove('drawer-open');
}
function openDrawer(aid, domain, key) {
  const d = S.domain || {};
  if (!d.domain || d.domain !== domain) return;
  const rec = findRecord(d, key);
  if (!rec) { closeDrawer(); return; }
  const isNew = !!rec._new;
  const el = drawerEl();
  document.body.classList.add('drawer-open');
  el.className = 'drawer';
  el.innerHTML = `
    <div class="drawer-head">
      <div><div class="dtitle">${isNew ? 'רשומה חדשה' : esc(rec.type) + ' · ' + esc(shortName(rec.name, domain))}</div>
        <div class="note">${esc(domain)} · ${esc(d.records_source || '')}</div></div>
      <button class="btn ghost" id="d-close" aria-label="סגירה" title="סגירה (Esc)">${menuIcon('x')}</button>
    </div>
    <div class="drawer-body" id="drawer-body">
      ${writeNotice(d)}
      <label for="d-type">סוג</label>
      <select id="d-type" ${isNew ? '' : 'disabled'}>
        ${['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS', 'SRV', 'CAA'].map((t) =>
          `<option ${t === rec.type ? 'selected' : ''}>${t}</option>`).join('')}</select>
      <label for="d-name">שם <span class="note">@ = הדומיין עצמו</span></label>
      <input id="d-name" class="ltr" value="${esc(rec.name == null ? '@' : rec.name)}">
      <label for="d-content">ערך</label>
      <input id="d-content" class="ltr" value="${esc(rec.content || '')}">
      <div id="d-extra"></div>
      <label for="d-ttl">TTL</label>
      <input id="d-ttl" class="ltr" list="ttl-presets" value="${esc(rec.ttl || '')}">
      <datalist id="ttl-presets">${TTL_PRESETS.map((v) => `<option value="${v}">`).join('')}</datalist>
      <div class="note" id="d-ttl-why"></div>
      <div id="d-warn"></div>
      <div id="d-diff"></div>
      <div id="d-out" class="out hidden"></div>
    </div>
    <div class="drawer-foot">
      ${isNew ? '' : `<button class="btn danger" id="d-del" ${actionAllowed(d, 'delete') ? '' : 'disabled'}
        title="${actionAllowed(d, 'delete') ? '' : 'עוד לא ממופה בפורטל הזה — ראו ההסבר למעלה'}">מחיקה…</button>`}
      <span style="flex:1"></span>
      <button class="btn" id="d-cancel">ביטול</button>
      <button class="btn primary" id="d-save" ${actionAllowed(d, isNew ? 'create' : 'update') ? '' : 'disabled'}>שמירה</button>
    </div>`;
  $('d-close').onclick = closeDrawer;
  $('d-cancel').onclick = closeDrawer;
  const read = () => ({ type: $('d-type').value, name: $('d-name').value.trim() || '@',
                        content: $('d-content').value.trim(), ttl: $('d-ttl').value.trim(),
                        priority: ($('d-prio') || {}).value });
  const refresh = () => {
    const v = read();
    paintTtlWhy(v);
    paintExtra(v, d, rec, isNew, refresh);
    paintWarnings(d, rec, v, isNew);
    paintDiff(rec, v, isNew);
  };
  ['d-type', 'd-name', 'd-content', 'd-ttl'].forEach((id) => {
    $(id).oninput = refresh;
    $(id).onchange = refresh;
  });
  $('d-save').onclick = async () => {
    const v = read();
    const btn = $('d-save');
    btn.disabled = true;
    const body = { action: isNew ? 'create' : 'update', type: v.type, name: v.name,
                   content: v.content, ttl: v.ttl ? Number(v.ttl) : null, id: rec.id,
                   before: isNew ? null : { id: rec.id, type: rec.type, name: rec.name,
                                            content: rec.content, ttl: rec.ttl } };
    if (v.priority) body.priority = Number(v.priority);
    const res = await Store.run(
      `api/accounts/${encodeURIComponent(aid)}/domains/${encodeURIComponent(domain)}/records`,
      body, { title: `${isNew ? 'הוספת' : 'עדכון'} רשומה · ${domain}` });
    if (res.queued) {
      out($('d-out'), 'הפעולה רצה כעבודה — ההתקדמות מוצגת בפינת המסך.', '');
      Store.invalidate('');
      renderJobs();
      waitForJob(res.id, () => {
        Store.invalidate('');
        go(`#/a/${aid}/d/${encodeURIComponent(domain)}/records`);
      });
      return;
    }
    btn.disabled = false;
    if (res.ok && res.body.ok !== false) {
      out($('d-out'), 'נשמר — והרשומות נקראו חזרה מהספק.', 'ok');
      Store.invalidate('');
      setTimeout(() => go(`#/a/${aid}/d/${encodeURIComponent(domain)}/records`), 700);
    } else {
      showError($('d-out'), res.body);
    }
  };
  if ($('d-del')) $('d-del').onclick = () => typedDelete(rec, async (why) => {
    const res = await Store.run(
      `api/accounts/${encodeURIComponent(aid)}/domains/${encodeURIComponent(domain)}/records`,
      { action: 'delete', type: rec.type, name: rec.name, content: rec.content, id: rec.id,
        before: { id: rec.id, type: rec.type, name: rec.name, content: rec.content, ttl: rec.ttl },
        reason: why },
      { title: `מחיקת רשומה · ${domain}` });
    if (res.queued) {
      renderJobs();
      waitForJob(res.id, () => {
        Store.invalidate('');
        go(`#/a/${aid}/d/${encodeURIComponent(domain)}/records`);
      });
      return;
    }
    if (res.ok && res.body.ok !== false) {
      Store.invalidate('');
      go(`#/a/${aid}/d/${encodeURIComponent(domain)}/records`);
    } else showError($('d-out'), res.body);
  });
  refresh();
  $('d-content').focus();
}

function paintTtlWhy(v) {
  const box = $('d-ttl-why');
  if (!box) return;
  const n = Number(v.ttl || 0);
  box.textContent = !v.ttl ? 'בלי TTL — הספק יחליט (לרוב 3600).'
    : n <= 300 ? `שינוי ייראה תוך עד ${Store.seconds(n)} — ובתמורה יותר שאילתות.`
    : n >= 86400 ? `שינוי ייקח עד ${Store.seconds(n)} להתפשט לכל העולם.`
    : `שינוי ייקח עד ${Store.seconds(n)} להתפשט.`;
}
function paintExtra(v, d, rec, isNew, refresh) {
  const box = $('d-extra');
  if (!box) return;
  const needsPrio = ['MX', 'SRV'].includes(v.type);
  if (needsPrio && !$('d-prio')) {
    box.innerHTML = `<label for="d-prio">עדיפות</label>
      <input id="d-prio" class="ltr" value="${esc(v.priority || '10')}">`;
    $('d-prio').oninput = refresh;
  } else if (!needsPrio && $('d-prio')) {
    box.innerHTML = '';
  }
}
/** The same rules the server enforces (`_record_conflicts`), said BEFORE the save rather than after. */
function paintWarnings(d, rec, v, isNew) {
  const box = $('d-warn');
  if (!box) return;
  const recs = (d.records || []).filter((r) => !(!isNew && r.id != null && r.id === rec.id));
  const sameName = shortName(v.name, d.domain);
  const others = recs.filter((r) => shortName(r.name, d.domain) === sameName);
  const warn = [];
  if (v.type === 'CNAME' && others.length) {
    warn.push(['err', `ל-${sameName} כבר יש רשומות אחרות (${[...new Set(others.map((o) => o.type))].join(', ')}) — אסור CNAME לצדן.`]);
  }
  if (v.type !== 'CNAME' && others.some((o) => o.type === 'CNAME')) {
    warn.push(['err', `ל-${sameName} יש CNAME — אי אפשר להוסיף רשומה נוספת באותו שם.`]);
  }
  if (v.content && others.some((o) => o.type === v.type && (o.content || '').trim() === v.content)) {
    warn.push(['warn', 'רשומה זהה כבר קיימת — זו כפילות.']);
  }
  if (['MX', 'SRV'].includes(v.type) && !v.priority) warn.push(['warn', 'MX/SRV חייבות עדיפות.']);
  if (v.type === 'A' && v.content && !/^\d{1,3}(\.\d{1,3}){3}$/.test(v.content)) {
    warn.push(['err', 'A מקבלת כתובת IPv4 בלבד.']);
  }
  if (v.type === 'AAAA' && v.content && !v.content.includes(':')) {
    warn.push(['err', 'AAAA מקבלת כתובת IPv6 בלבד.']);
  }
  box.innerHTML = warn.map(([k, t]) =>
    `<div class="issue ${k === 'err' ? 'err' : 'warn'}">${esc(t)}</div>`).join('');
  const save = $('d-save');
  if (save) save.disabled = warn.some(([k]) => k === 'err') || !v.content;
}
/** What the change will BE, before it is made — the single most useful block in a DNS editor. */
function paintDiff(rec, v, isNew) {
  const box = $('d-diff');
  if (!box) return;
  const before = isNew ? ['—', '—', '—'] : [rec.type, shortName(rec.name, ''), rec.content || ''];
  const rows = [['סוג', before[0], v.type], ['שם', before[1], v.name],
                ['ערך', before[2], v.content], ['TTL', isNew ? '—' : (rec.ttl || '—'), v.ttl || 'ספק']];
  const changed = rows.filter(([, a, b]) => String(a) !== String(b));
  box.innerHTML = `<div class="diff">
    <div class="note" style="margin-bottom:6px">${isNew ? 'הרשומה שתיווצר'
      : (changed.length ? `${changed.length} שדות משתנים` : 'אין שינוי')}</div>
    <table>${rows.map(([k, a, b]) => `<tr class="${String(a) === String(b) ? '' : 'chg'}">
      <td class="note">${esc(k)}</td><td class="ltr old">${esc(a)}</td>
      <td class="ltr new">${String(a) === String(b) ? '' : '→ ' + esc(b)}</td></tr>`).join('')}</table></div>`;
}
/** A destructive action asks for the WORD, not for a click: "מחיקה" typed by hand. */
function typedDelete(rec, run) {
  const body = $('drawer-body');
  const old = body.innerHTML;
  body.innerHTML = `
    <div class="issue err"><b>מחיקת ${esc(rec.type)} ${esc(rec.name)}</b>
      <div class="note">הערך: <span class="ltr">${esc(rec.content || '')}</span></div>
      <div class="note">למחיקה אין ביטול אוטומטי — היא נרשמת ביומן עם הערך שהיה, ומשם אפשר להחזיר.</div></div>
    <label for="d-why">למה? (נרשם ביומן)</label>
    <input id="d-why" placeholder="למשל: ניקוי רשומה ישנה">
    <label for="d-confirm">הקלד <span class="mono">מחיקה</span> כדי לאשר</label>
    <input id="d-confirm" class="ltr">
    <div class="actions-row" style="margin-top:12px">
      <button class="btn danger" id="d-yes" disabled>מחק</button>
      <button class="btn" id="d-no">ביטול</button></div>
    <div id="d-del-out" class="out hidden"></div>`;
  $('d-confirm').oninput = (e) => { $('d-yes').disabled = e.target.value.trim() !== 'מחיקה'; };
  $('d-no').onclick = () => { body.innerHTML = old; };
  $('d-yes').onclick = async () => {
    $('d-yes').disabled = true;
    try { await run(($('d-why') || {}).value || ''); } catch (e) { body.innerHTML = old; }
  };
  $('d-confirm').focus();
}

/** Follow a job to its end, then do `then` — the screen never guesses that a job finished. */
function waitForJob(id, then) {
  const tick = setInterval(() => {
    const j = Store.jobById(id);
    if (!j) return;
    if (j.state === 'ok') { clearInterval(tick); then && then(j); }
    if (j.state === 'error' || j.state === 'cancelled') {
      clearInterval(tick);
      showError(errorTarget(), refusalOf(j) ||
        { error: j.error || j.message || 'העבודה נכשלה' });
    }
  }, 800);
  return tick;
}

// ── health: the authority first, then the resolvers, then the drift ─────────────────────────────
async function tabHealth(d) {
  const aid = d.account.id, name = d.domain;
  $('tab').innerHTML = `<div class="note">שואל את שרתי השמות של האזור ואת המאחזרים…</div>
    ${Store.skeleton(4)}`;
  const key = `health:${aid}:${name}`;
  const res = await Store.res(key,
    `api/accounts/${encodeURIComponent(aid)}/domains/${encodeURIComponent(name)}/health`,
    { ttl: 45 });
  const h = res.value || {};
  if (!res.ok || !h.domain) {
    $('tab').innerHTML = `<div class="out err">${esc((res.value || {}).error || 'הבדיקה נכשלה')}</div>`;
    return;
  }
  S.health = h;
  const auth = h.authority || {}, rs = h.resolvers || {};
  const nsRows = (auth.nameservers || []).map((ns) => `<tr><td class="ltr">${esc(ns)}</td>
     <td class="ltr note">${esc((auth.ip || {})[ns] || '—')}</td>
     <td>${(auth.apex_ns || []).includes(ns)
        ? '<span class="chip ok">משיב</span>' : '<span class="chip warn">לא מפרסם את עצמו</span>'}</td></tr>`).join('');
  const types = [...new Set(Object.keys(auth.records || {}).concat(['A']))].sort();
  const resolverRows = (rs.resolvers || []).map((r) => {
    const row = (rs.per_resolver || {})[r] || {};
    return `<tr><td class="ltr">${esc(r)}</td>${types.map((t) => {
      const vals = (row.records || {})[t] || [];
      const ttls = ((row.ttls || {})[t]) || {};
      return `<td class="ltr">${vals.length ? vals.map((v) => `${esc(v)}
        <span class="note">${ttls[v] != null ? Store.seconds(ttls[v]) : ''}</span>`).join('<br>')
        : '<span class="note">—</span>'}</td>`;
    }).join('')}</tr>`;
  }).join('');
  const issued = (h.issues || []).map((i) => `<div class="issue ${i.level === 'error' ? 'err' : 'warn'}">
      <b>${esc(i.title)}</b><div class="note">${esc(i.detail || '')}</div>
      ${i.fix ? `<div class="note">${esc(i.fix)}</div>` : ''}</div>`).join('');
  const extraRows = [
    ...((h.world_only || []).map((x) => `<tr><td>${esc(x.type)}</td>
      <td class="note">—</td><td class="ltr">${esc((x.observed || []).join(', '))}</td>
      <td class="note">קיים בעולם; הפאנל הזה לא מציג את הסוג הזה</td></tr>`)),
    ...((h.panel_only || []).map((x) => `<tr><td>${esc(x.type)}</td>
      <td class="ltr">${esc((x.expected || []).join(', '))}</td><td class="note">—</td>
      <td class="note">שמור אצל הספק ואינו נענה מהעולם</td></tr>`)),
  ].join('');
  const drift = (h.drift || []).map((dd) => `<tr><td>${esc(dd.type)}</td>
      <td class="ltr">${esc((dd.expected || []).join(', ') || '—')}</td>
      <td class="ltr">${esc((dd.observed || []).join(', ') || '—')}</td>
      <td class="note">${dd.missing && dd.missing.length ? 'חסר: ' + esc(dd.missing.join(', ')) : ''}
        ${dd.extra && dd.extra.length ? 'עודף: ' + esc(dd.extra.join(', ')) : ''}</td></tr>`).join('');
  $('tab').innerHTML = `
    <div class="bar-row">
      <h3 style="font-size:14px;margin:0">תפוצה ובריאות
        <span class="hint">${Store.fresh(res)} · נבדק ${esc(new Date((h.checked_at || 0) * 1000)
          .toLocaleTimeString('he-IL'))}</span></h3>
      <button class="btn" id="h-again">בדוק שוב</button>
    </div>
    ${issued || '<div class="issue ok">לא נמצאו בעיות: האזור, הרישום והמאחזרים מסכימים.</div>'}
    <h3 style="font-size:14px;margin-top:14px">1 · מה שהאזור עצמו עונה
      <span class="hint">האמת — נשאל ישירות לפי IP, לא דרך מטמון</span></h3>
    <table class="grid-t"><thead><tr><th>שרת שמות</th><th>כתובת</th><th>מצב</th></tr></thead>
      <tbody>${nsRows || '<tr><td colspan="3" class="note">לא נמצאו שרתי שמות</td></tr>'}</tbody></table>
    <h3 style="font-size:14px;margin-top:14px">2 · מה שהמאחזרים משיבים
      <span class="hint">כל תא נושא את ה-TTL שנשאר לו</span></h3>
    <div class="scroll-x"><table class="grid-t"><thead><tr><th>מאחזר</th>
      ${types.map((t) => `<th>${esc(t)}</th>`).join('')}</tr></thead>
      <tbody>${resolverRows || '<tr><td class="note">אין תשובה</td></tr>'}</tbody></table></div>
    <h3 style="font-size:14px;margin-top:14px">3 · פער בין האזור למה שנשאל
      <span class="hint">מה שהפאנל מחזיק בשם הדומיין עצמו</span></h3>
    <table class="grid-t"><thead><tr><th>סוג</th><th>באזור</th><th>בעולם</th><th></th></tr></thead>
      <tbody>${(drift + extraRows) || '<tr><td colspan="4" class="note">אין פער.</td></tr>'}</tbody></table>
    <div class="note" style="margin-top:10px">${esc((h.caching || {}).note || '')}
      ${(h.caching || {}).min_ttl != null ? ` · TTL מינימלי: ${Store.seconds(h.caching.min_ttl)}` : ''}</div>`;
  $('h-again').onclick = () => { Store.invalidate(key); tabHealth(d); };
}

// ── activity: every change, with the before/after, and an undo ──────────────────────────────────
async function tabActivity(d) {
  const aid = d.account.id, name = d.domain;
  $('tab').innerHTML = Store.skeleton(4);
  const key = `activity:${aid}:${name}`;
  const res = await Store.res(key,
    `api/accounts/${encodeURIComponent(aid)}/domains/${encodeURIComponent(name)}/activity`,
    { ttl: 20 });
  const evs = ((res.value || {}).events) || [];
  const KIND = { dns_create: 'נוצרה רשומה', dns_update: 'עודכנה רשומה', dns_delete: 'נמחקה רשומה',
                 dns_write: 'כתיבה ברשומות', revert: 'בוטל שינוי', sync: 'סנכרון',
                 account_connected: 'חיבור חשבון', whois: 'בדיקת תוקף', remove: 'הסרה מהמעקב' };
  $('tab').innerHTML = `
    <div class="bar-row"><h3 style="font-size:14px;margin:0">יומן שינויים
      <span class="hint">${Store.fresh(res)} · ${evs.length} רשומות</span></h3></div>
    ${evs.length ? evs.map((e) => {
      const m = e.meta || {};
      const a = m.after || {}, b = m.before || {};
      const dns = ['dns_create', 'dns_update', 'dns_delete'].includes(e.kind);
      const diff = dns && (a.content || b.content) ? `<div class="diff-mini ltr">
          ${b.content ? `<span class="old">${esc([b.type, b.name, b.content].filter(Boolean).join(' '))}</span>` : ''}
          ${a.content ? `<span class="new">${esc([a.type, a.name, a.content].filter(Boolean).join(' '))}</span>` : ''}
        </div>` : '';
      return `<div class="ev">
        <div class="ev-t"><b>${esc(KIND[e.kind] || e.kind)}</b>
          <span class="note">${esc(new Date((e.ts || 0) * 1000).toLocaleString('he-IL'))}</span></div>
        <div class="note">${esc(e.message || '')}</div>
        ${diff}
        ${m.revertible ? `<button class="btn" data-revert="${e.id}">החזר למצב הקודם</button>` : ''}
      </div>`;
    }).join('') : '<div class="note">עוד לא נרשמו שינויים לדומיין הזה.</div>'}`;
  document.querySelectorAll('[data-revert]').forEach((b) => {
    b.onclick = async () => {
      if (!await binaAsk({ title: 'לבטל את השינוי הזה?', ok: 'החזר למצב הקודם', cancel: 'השאר כך',
                           body: 'הפעולה תיכתב בחזרה לספק ותירשם ביומן.' })) return;
      b.disabled = true;
      const r = await Store.run(
        `api/accounts/${encodeURIComponent(aid)}/domains/${encodeURIComponent(name)}/activity/${b.dataset.revert}/revert`,
        {}, { title: 'ביטול שינוי' });
      Store.invalidate('');
      if (r.queued) { renderJobs(); waitForJob(r.id, () => tabActivity(d)); }
      else if (r.ok) tabActivity(d);
      else {
        b.disabled = false;
        const box = document.createElement('div');
        box.className = 'issue err';
        b.after(box);
        showError(box, r.body || { error: 'הביטול נכשל' });
      }
    };
  });
}

// ── ops ─────────────────────────────────────────────────────────────────────────────────────────
function tabOps(d) {
  const money = ['registerDomain', 'renewDomain', 'transferDomain'];
  $('tab').innerHTML = `
    <h3 style="font-size:14px">מה אפשר לעשות עם הדומיין הזה
      <span class="hint">כל פעולה — או שהיא רצה, או שהיא אומרת מה חסר</span></h3>
    <table class="grid-t"><thead><tr><th>פעולה</th><th>מצב</th><th>איך / מה חסר</th><th></th></tr></thead>
    <tbody>${(d.ops || []).map((o) => {
      const why = o.supported ? (o.how === 'browser' ? 'דרך הדפדפן של הלשכה' : 'דרך ה-API')
        : (o.needs === 'connection' ? 'צריך לחבר את החשבון שמחזיק באזור' : (o.reason || 'לא זמין'));
      return `<tr><td>${esc(o.label)}${money.includes(o.id) ? ' <span class="chip warn">בתשלום</span>' : ''}</td>
        <td><span class="chip ${o.supported ? 'ok' : 'plain'}">${o.supported ? 'זמין' : 'לא זמין'}</span></td>
        <td class="note">${esc(why)}</td>
        <td>${o.supported ? `<button class="btn" data-op="${esc(o.id)}">הרץ</button>` : ''}</td></tr>`;
    }).join('')}</tbody></table>
    <div id="op-out" class="out hidden"></div>`;
  document.querySelectorAll('[data-op]').forEach((el) => {
    el.onclick = async () => {
      const op = el.dataset.op;
      const moneyOp = money.includes(op);
      if (moneyOp && !await binaAsk({ title: 'זו פעולה בתשלום — להמשיך?', ok: 'המשך',
                                      facts: [['פעולה', op], ['דומיין', d.domain]] })) return;
      el.disabled = true;
      const body = { op, params: {} };
      if (moneyOp) body.confirm = `${d.domain}:${op}`;
      const res = await Store.run(
        `api/accounts/${encodeURIComponent(d.account.id)}/domains/${encodeURIComponent(d.domain)}/op`,
        body, { title: `${op} · ${d.domain}` });
      el.disabled = false;
      if (res.queued) { renderJobs(); waitForJob(res.id, () => { Store.invalidate(''); tabOps(d); }); }
      else if (res.ok && res.body.ok !== false) out($('op-out'), res.body.result, 'ok');
      else showError($('op-out'), res.body);
    };
  });
}

// ── adding an account ───────────────────────────────────────────────────────────────────────────
function showAddAccount() {
  const browser = S.providers.find((p) => p.flow === 'browser') || {};
  const apiProviders = S.providers.filter((p) => p.flow !== 'browser');
  $('view').innerHTML = `
    <section class="card"><h3>הוספת חשבון
      <span class="hint">בוחרים ספק — ומכאן זה או API או התחברות בדפדפן</span></h3>
      <div class="grid2">
        ${browser.id ? `<div class="prov sel" data-prov="${esc(browser.id)}">
          <div class="name">${esc(browser.name)}</div>
          <div class="note">${esc(browser.description || '')}</div>
          <div class="meta" style="margin-top:6px">${accessChip('browser')} דרך הדפדפן של הלשכה</div>
        </div>` : ''}
        ${apiProviders.map((p) => `<div class="prov" data-prov="${esc(p.id)}">
          <div class="name">${esc(p.name)}</div>
          <div class="note">${esc(p.reads || p.description || '')}</div>
          <div class="meta" style="margin-top:6px">${accessChip('api')}</div>
        </div>`).join('')}
      </div>
      <div id="add-body" style="margin-top:14px"></div>
      <div class="actions-row" style="margin-top:12px"><button class="btn" id="add-cancel">ביטול</button></div>
    </section>`;
  $('add-cancel').onclick = () => go('#/');
  document.querySelectorAll('[data-prov]').forEach((el) => {
    el.onclick = () => {
      document.querySelectorAll('[data-prov]').forEach((x) => x.classList.toggle('sel', x === el));
      const p = S.providers.find((x) => x.id === el.dataset.prov);
      return p && p.flow === 'browser' ? browserFlow(p) : apiFlow(p);
    };
  });
  if (browser.id) browserFlow(browser);
}

async function browserFlow(p) {
  const body = $('add-body');
  body.innerHTML = '<div class="note">בודק אם הדפדפן של הלשכה כבר מחובר לספק…</div>';
  const r = await api('api/accounts/browser', { method: 'POST', body: JSON.stringify({ provider: p.id }) });
  const d = r.body || {};
  if (d.step === 'connected') {
    const n = (d.evidence || {}).count;
    body.innerHTML = `<div class="out ok">החשבון מחובר ומאומת${n ? ` — נקראו ${n} דומיינים מהחשבון` : ''}.</div>`;
    setTimeout(() => go('#/'), 1200);
    return;
  }
  if (d.step === 'needs_human_login') {
    body.innerHTML = `
      <div class="out">${esc(d.hint || 'צריך התחברות בדפדפן')}${d.page && d.page.url ? '\n' + esc(d.page.url) : ''}</div>
      <div class="actions-row" style="margin-top:10px">
        <a class="btn primary" href="${esc(d.live_view || '/a/browser42/')}" target="_blank" rel="noopener">פתח את הדפדפן והתחבר ↗</a>
        <button class="btn" id="again">בדקתי — בדוק שוב</button>
        <span class="note">אני בודק לבד כל 5 שניות…</span>
      </div>`;
    $('again').onclick = () => browserFlow(p);
    let n = 0;
    const t = setInterval(async () => {
      n += 1;
      if (n > 60 || !document.getElementById('again')) return clearInterval(t);
      const rr = await api('api/accounts/browser', { method: 'POST', body: JSON.stringify({ provider: p.id }) });
      if (rr.body && rr.body.step === 'connected') { clearInterval(t); browserFlow(p); }
    }, 5000);
    return;
  }
  body.innerHTML = `<div class="out err">${esc(d.error || d.reason || 'החיבור לא הושלם')}${d.page ? '\n' + esc(d.page.url || '') : ''}</div>
    <div class="actions-row" style="margin-top:8px"><button class="btn" id="again2">נסה שוב</button></div>`;
  $('again2').onclick = () => browserFlow(p);
}

function apiFlow(p) {
  const body = $('add-body');
  const methods = p.auth_methods || [];
  body.innerHTML = `
    <div class="grid2">${methods.map((m) => `<div class="prov" data-m="${esc(m.id)}">
      <div class="name">${esc(m.label)}</div><div class="note">${esc(m.explain || '')}</div>
      <div class="meta">${esc(m.can || '')}</div>
      ${m.help_url ? `<div class="note ltr">${esc(m.help_url)}</div>` : ''}
    </div>`).join('')}</div>
    <div id="m-body"></div>`;
  document.querySelectorAll('[data-m]').forEach((el) => {
    el.onclick = () => {
      const m = methods.find((x) => x.id === el.dataset.m);
      const fields = (m.needs || []).concat(m.optional || []);
      $('m-body').innerHTML = `
        <form id="f">
          <div class="grid2">${fields.map((f) => `<div>
            <label for="f-${esc(f)}">${esc(f)}${(m.needs || []).includes(f) ? ' *' : ''}</label>
            <input id="f-${esc(f)}" class="ltr" autocomplete="off"></div>`).join('')}
            <div><label for="f-label">שם לתצוגה</label><input id="f-label"></div></div>
          <div class="actions-row" style="margin-top:12px">
            <button class="btn primary" type="submit">אמת ושמור</button></div>
        </form>
        <div id="a-out" class="out hidden"></div>`;
      $('f').onsubmit = async (ev) => {
        ev.preventDefault();
        const payload = { provider: p.id, method: m.id, label: $('f-label').value.trim() };
        fields.forEach((f) => { const el2 = $('f-' + f); if (el2 && el2.value.trim()) payload[f] = el2.value.trim(); });
        const res = await api('api/accounts', { method: 'POST', body: JSON.stringify(payload) });
        if (res.ok && res.body.stored) { out($('a-out'), 'החשבון אומת ונשמר.', 'ok'); setTimeout(() => go('#/'), 900); }
        else showError($('a-out'), res.body);
      };
    };
  });
  if (methods.length === 1) document.querySelector('[data-m]').click();
}

// A screen that could not be read says so the way this screen says an issue - what, why, what to do - and the
// heading's chip stops saying «טוען…». It was drawn as command output (the log's box: a code font, red on red,
// under the one word «שגיאה»), and the chip went on saying «טוען…» beside it for as long as the page stayed open.
function fail(r) {
  $('state').className = 'live bad';
  $('state').textContent = 'לא נטען';
  $('view').innerHTML = `<div class="issues"><div class="issue err"><b>המסך לא נטען</b>
    <div class="note">${esc((r.body && (r.body.error || r.body.detail)) || binaSaid(r.status))}</div>
    <div class="note">«רענון» קורא אותו שוב.</div></div></div>`;
}

boot();
