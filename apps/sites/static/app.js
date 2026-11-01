/* sites — the sites screen. Vanilla JS on purpose: the app owns one list, one detail view with
   five tabs, and two small wizards, and a framework would be a dependency to keep patched for no
   surface. Every URL is RELATIVE — the console serves the app at /a/sites/ and injects <base href>. */
'use strict';

const $ = (id) => document.getElementById(id);
const S = { overview: null, site: null, tab: 'overview', machines: [], checks: [], stack: null,
            files: null, file: null, scanSel: null, logs: null, wizard: null };

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
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function bytes(n) {
  n = Number(n || 0);
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  if (n < 1073741824) return (n / 1048576).toFixed(1) + ' MB';
  return (n / 1073741824).toFixed(2) + ' GB';
}
function ago(ts) {
  if (!ts) return '—';
  const d = Math.max(0, Math.floor(Date.now() / 1000) - ts);
  if (d < 60) return 'לפני ' + d + ' שניות';
  if (d < 3600) return 'לפני ' + Math.floor(d / 60) + ' דקות';
  if (d < 86400) return 'לפני ' + Math.floor(d / 3600) + ' שעות';
  return 'לפני ' + Math.floor(d / 86400) + ' ימים';
}
function stateChip(site) {
  const st = site.last_state || 'unknown';
  const map = { up: ['ok', 'עולה'], down: ['bad', 'לא עונה'], unknown: ['', 'לא נבדק'] };
  const [cls, txt] = map[st] || ['', st];
  return `<span class="chip ${cls}">${txt}</span>`;
}
function sevChip(s) {
  const map = { error: ['bad', 'שגיאה'], warn: ['warn', 'אזהרה'], info: ['', 'מידע'],
                ok: ['ok', 'תקין'] };
  const [cls, txt] = map[s] || ['', s];
  return `<span class="chip ${cls}">${txt}</span>`;
}
function scoreClass(n, min) {
  if (n == null) return '';
  if (n >= (min || 70)) return 'good';
  if (n >= (min || 70) - 20) return 'mid';
  return 'bad';
}

// ── routing ──────────────────────────────────────────────────────────────────────────────────────
function go(hash) { location.hash = hash; }
window.addEventListener('hashchange', render);

async function boot() {
  $('btn-refresh').onclick = () => render(true);
  $('btn-new').onclick = () => go('#/new');
  $('btn-adopt').onclick = () => go('#/adopt');
  const m = await api('api/machines?probe=0');
  if (m.ok) S.machines = m.body.machines || [];
  const c = await api('ops');
  if (c.ok) S.checks = c.body.checks || [];
  render();
}

async function render(force) {
  const h = (location.hash || '#/').replace(/^#/, '');
  const parts = h.split('/').filter(Boolean);          // ['', 's', '<id>', '<tab>']
  $('title').textContent = 'אתרים';
  $('sub').textContent = 'האתרים של העסק — מי רץ, מי לא עונה, ומה צריך תיקון.';
  if (parts[0] === 's' && parts[1]) return detail(parts[1], parts[2] || 'overview', force);
  renderMenu(null, null);                 // the address, with no site open
  if (parts[0] === 'new') return wizard();
  if (parts[0] === 'adopt') return adopt();
  return overview(force);
}

// ── overview ─────────────────────────────────────────────────────────────────────────────────────
async function overview(force) {
  const r = await api('api/overview');
  if (!r.ok) return fail(r);
  const d = r.body;
  S.overview = d;
  const sites = d.sites || [];
  const down = sites.filter((s) => s.last_state === 'down').length;
  $('state').className = 'live' + (down ? ' bad' : '');
  $('state').textContent = sites.length
    ? `${sites.length} אתרים · ${down ? down + ' לא עונים' : 'הכל עונה'}`
    : 'אין אתרים עדיין';

  const machErr = d.machines_error
    ? `<div class="finding warn"><div class="ft">שירות המחשבים אינו זמין</div>
         <div class="fd">${esc(d.machines_error)}</div></div>` : '';
  const cards = sites.map((s) => {
    const up = s.uptime || {};
    const f = s.findings || {};
    const v = s.visits || {};
    return `<div class="site ${esc(s.last_state || 'unknown')}" data-id="${esc(s.id)}">
      <div class="top">
        <div>
          <div class="name">${esc(s.label || s.id)}</div>
          <div class="host">${esc((s.hosts || []).join(' · ') || 'ללא דומיין')}</div>
        </div>
        ${stateChip(s)}
      </div>
      <div class="stats">
        <div><b>${up.uptime_pct == null ? '—' : up.uptime_pct + '%'}</b>זמינות 24ש׳</div>
        <div><b>${up.avg_ms == null ? '—' : up.avg_ms + 'ms'}</b>זמן תגובה</div>
        <div><b>${v.hits || 0}</b>ביקורים 7 ימים</div>
        <div><b>${f.error || 0}</b>שגיאות פתוחות</div>
        <div><b>${f.warn || 0}</b>אזהרות</div>
      </div>
      <div class="stats"><span class="badge">${esc(s.kind)}</span>
        <span class="badge">${esc(s.source)}</span>
        <span class="badge ltr">${esc(s.machine)}</span>
        <span class="badge">${esc(ago(s.last_checked))}</span></div>
      ${s.last_error ? `<div class="finding error" style="margin:0"><div class="fd">${esc(s.last_error)}</div></div>` : ''}
    </div>`;
  }).join('');

  $('view').innerHTML = `
    ${machErr}
    ${sites.length ? `<div class="grid">${cards}</div>` : emptyState()}
    <section class="card" style="margin-top:16px">
      <h3>מה האפליקציה עושה מעצמה
        <span class="hint">הבדיקות רצות ברקע; אפשר להריץ ידנית בכל אתר</span></h3>
      <div class="kv">
        <div class="k">בדיקת זמינות</div><div>כל דקה, מכל שם אתר — התראה נשלחת רק כשהמצב משתנה</div>
        <div class="k">איסוף ביקורים</div><div>כל 5 דקות, מתוך לוג השרת של האתר עצמו</div>
        <div class="k">סריקות</div><div>פעם ביום (03:00): אבטחה, SEO וציון יופי — כל אחת בקצב שלה</div>
        <div class="k">סבב אחרון</div><div class="ltr">${esc(ago((d.scheduler || {}).last_uptime))} · איסוף ${esc(ago((d.scheduler || {}).last_collect))}</div>
        <div class="k">הבדיקות</div><div>${(d.checks || []).map((c) => `<span class="badge">${esc(c.title)}</span>`).join(' ')}</div>
      </div>
    </section>`;
  [...document.querySelectorAll('.site')].forEach((el) => {
    el.onclick = () => go('#/s/' + el.dataset.id);
  });
}

function emptyState() {
  return `<section class="card">
    <h3>עוד אין אתרים בניהול</h3>
    <p class="note">אפשר ליצור אתר חדש (הלשכה תפרוס אותו על מחשב שתבחר), או לאמץ אתר קיים —
      קונטיינר שכבר רץ על אחד המחשבים — ואז לראות אותו כאן עם זמינות, ביקורים וסריקות.</p>
    <div class="actions-row"><button class="btn primary" onclick="location.hash='#/new'">אתר חדש</button>
      <button class="btn" onclick="location.hash='#/adopt'">אימוץ אתר קיים</button></div>
  </section>`;
}

// A screen that could not be read says so the way this screen says a finding - what, why, what to do - and the
// heading's chip stops saying «טוען…». It was drawn as command output (the log's box: a code font, red on red,
// under the one word «שגיאה»), and the chip went on saying «טוען…» beside it for as long as the page stayed open.
function fail(r) {
  $('state').className = 'live bad';
  $('state').textContent = 'לא נטען';
  $('view').innerHTML = `<div class="finding error"><div class="ft">המסך לא נטען</div>
    <div class="fd">${esc((r.body && (r.body.error || r.body.detail)) || binaSaid(r.status))}</div>
    <div class="fx">«רענון» קורא אותו שוב.</div></div>`;
}

// ── site detail ──────────────────────────────────────────────────────────────────────────────────
// ── the side menu ────────────────────────────────────────────────────────────────────────────────
// One place that knows what this app's menu contains, called by every route: the address (all the
// sites) and, when a site is open, that site's sections. The rows are the shared component's
// (.bnv-item / .bnv-ic / .bnv-label), so this app contributes ids and labels — never a size.
const SITE_TABS = [['overview', 'סקירה'], ['scans', 'סריקות'], ['visits', 'ביקורים'],
                   ['ops', 'פריסה ולוגים'], ['settings', 'הגדרות']];
// The app's own glyphs (Feather paths), so the menu never paints a Unicode character where an
// icon belongs — those render in whatever font the browser finds and sit off-baseline in Hebrew.
const ICONS = {
  home: 'M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z',
  eye: 'M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
  search: 'M21 21l-4.35-4.35M19 11a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  chart: 'M3 3v18h18M7 15l3-4 3 3 5-7',
  server: 'M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01',
  gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2 2 2 0 1 1-4 0 1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 3 15a2 2 0 1 1 0-4 1.7 1.7 0 0 0 1.2-2.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 10 4.6a2 2 0 1 1 4 0 1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1A1.7 1.7 0 0 0 21 11a2 2 0 1 1 0 4z',
};
const MENU_ICONS = { overview: 'eye', scans: 'search', visits: 'chart', ops: 'server', settings: 'gear' };
const menuIcon = (n) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${ICONS[n] || ICONS.home}"/></svg>`;
function menuRow(label, icon, active, onclick) {
  const a = document.createElement('button');
  a.type = 'button';
  a.className = 'bnv-item' + (active ? ' is-active' : '');
  a.title = label;
  a.innerHTML = `<span class="bnv-ic">${menuIcon(icon)}</span><span class="bnv-label">${esc(label)}</span>`;
  a.onclick = onclick;
  return a;
}
function renderMenu(siteId, tab) {
  const box = $('menu'); if (!box) return;
  box.innerHTML = '';
  const home = document.createElement('div'); home.className = 'bnv-list';
  home.appendChild(menuRow('כל האתרים', 'home', !siteId, () => go('#/')));
  box.appendChild(home);
  if (!siteId) return;
  const g = document.createElement('div'); g.className = 'bnv-group'; g.textContent = 'האתר';
  box.appendChild(g);
  const list = document.createElement('div'); list.className = 'bnv-list';
  for (const [k, t] of SITE_TABS) {
    list.appendChild(menuRow(t, MENU_ICONS[k], k === tab, () => go(`#/s/${siteId}/${k}`)));
  }
  box.appendChild(list);
}

async function detail(id, tab, force) {
  const r = await api('api/sites/' + encodeURIComponent(id));
  if (!r.ok) return fail(r);
  const s = r.body;
  S.site = s;
  S.tab = tab;
  const st = s.status || {};
  $('title').textContent = s.label || id;
  $('sub').textContent = (s.hosts || []).join(' · ') || 'ללא דומיין';
  const up = s.uptime || {};
  $('state').className = 'live' + (s.last_state === 'down' ? ' bad' : '');
  $('state').textContent = s.last_state === 'down' ? 'לא עונה'
    : (up.uptime_pct == null ? 'אין דגימות' : up.uptime_pct + '% זמינות');

  $('view').innerHTML = `
    <section class="card">
      <h3>${esc(s.label || s.id)}
        <span class="hint">${esc(s.machine)} · ${esc(s.container)} ·
          ${st.present ? (st.running ? 'הקונטיינר רץ' : 'הקונטיינר כבוי') : 'הקונטיינר לא נמצא'}</span></h3>
      <div class="vitals">
        <div class="vital"><div class="k">זמינות 24 שעות</div>
          <div class="v">${up.uptime_pct == null ? '—' : up.uptime_pct + '%'}</div>
          <div class="note">${up.up || 0} עונה · ${up.down || 0} לא</div></div>
        <div class="vital"><div class="k">זמן תגובה ממוצע</div>
          <div class="v">${up.avg_ms == null ? '—' : up.avg_ms + 'ms'}</div></div>
        <div class="vital"><div class="k">ביקורים 7 ימים</div>
          <div class="v">${(s.visits || {}).hits || 0}</div>
          <div class="note">${(s.visits || {}).uniques || 0} מבקרים · ${(s.visits || {}).bots || 0} בוטים</div></div>
        <div class="vital"><div class="k">ממצאים פתוחים</div>
          <div class="v">${(s.findings || {}).error || 0} שגיאות</div>
          <div class="note">${(s.findings || {}).warn || 0} אזהרות · ${(s.findings || {}).info || 0} מידע</div></div>
      </div>
      <div class="actions-row" style="margin-top:12px">
        ${s.url ? `<a class="btn" href="${esc(s.url)}" target="_blank" rel="noopener">פתח אתר ↗</a>` : ''}
        <button class="btn" data-act="probe">בדוק עכשיו</button>
        <button class="btn" data-act="collect">אסוף ביקורים</button>
        <button class="btn" data-act="scan">הרץ סריקות</button>
        ${st.running ? `<button class="btn" data-act="stop">כבה</button>`
                     : `<button class="btn" data-act="start">הפעל</button>`}
        <button class="btn" data-act="restart">הפעל מחדש</button>
        ${s.managed ? `<button class="btn primary" data-act="deploy">פרוס מחדש</button>` : ''}
      </div>
      <div id="act-out" class="out hidden"></div>
    </section>
    <div id="tab"></div>`;

  renderMenu(id, tab);
  document.querySelectorAll('[data-act]').forEach((b) => { b.onclick = () => act(b.dataset.act, b); });
  await { overview: tabOverview, scans: tabScans, visits: tabVisits, ops: tabOps,
          settings: tabSettings }[tab]?.(s);
}

async function act(action, btn) {
  if (action === 'deploy' && !await binaAsk({ title: 'לפרוס את האתר מחדש?', ok: 'פריסה',
      body: 'הפעולה כותבת את קבצי הדפוס על המחשב ומרימה את הקונטיינר.' })) return;
  btn.disabled = true;
  const out = $('act-out');
  out.className = 'out';
  out.classList.remove('hidden');
  out.textContent = 'פועל…';
  const r = await api(`api/sites/${encodeURIComponent(S.site.id)}/${action}`, { method: 'POST',
    body: JSON.stringify({}) });
  out.className = 'out ' + (r.ok ? 'ok' : 'err');
  out.textContent = r.ok ? JSON.stringify(r.body.result || r.body, null, 2)
                         : ((r.body && r.body.error) || binaSaid(r.status));
  btn.disabled = false;
}

// ── tab: overview ────────────────────────────────────────────────────────────────────────────────
async function tabOverview(s) {
  const u = await api(`api/sites/${encodeURIComponent(s.id)}/uptime?hours=24`);
  const samples = (u.ok && u.body.samples) || [];
  const byCheck = {};
  (s.runs || []).forEach((r) => { if (!byCheck[r.check]) byCheck[r.check] = r; });
  const events = (s.events || []).map((e) => `<tr><td class="ltr">${esc(ago(e.ts))}</td>
      <td>${esc(e.kind)}</td><td>${esc(e.message)}</td></tr>`).join('');
  $('tab').innerHTML = `
    <section class="card"><h3>זמינות — 24 השעות האחרונות
      <span class="hint">${samples.length} דגימות</span></h3>
      ${sparkline(samples)}
      <div class="note">כל עמודה = דקה. אדום = לא ענה.</div>
      <div class="kv" style="margin-top:10px">
        <div class="k">7 ימים</div><div>${(s.uptime_7d || {}).uptime_pct == null ? '—'
          : (s.uptime_7d || {}).uptime_pct + '%'} (${(s.uptime_7d || {}).samples || 0} דגימות)</div>
        <div class="k">דגימה אחרונה</div><div class="ltr">${esc(ago((s.uptime || {}).last_sample))}</div>
        <div class="k">מקור הביקורים</div><div>${esc((s.log_source || '') === 'file'
          ? 'לוג ה-JSON של האתר (' + s.root + '/logs/access.log)'
          : 'לוג הקונטיינר — האתר טרם הועבר לדפוס הקבוע')}</div>
      </div>
    </section>
    <section class="card"><h3>מצב הבדיקות</h3>
      <table class="grid-t"><thead><tr><th>בדיקה</th><th>מצב</th><th>מתי</th><th>סיכום</th></tr></thead>
      <tbody>${(S.checks || []).map((c) => {
        const r = byCheck[c.name];
        return `<tr><td>${esc(c.title)}</td>
          <td>${r ? sevChip(r.state === 'warn' ? 'warn' : r.state) : '<span class="chip">טרם רצה</span>'}</td>
          <td class="ltr">${esc(r ? ago(r.finished_at) : '—')}</td>
          <td>${esc(r ? summaryLine(r.summary) : c.question)}</td></tr>`;
      }).join('')}</tbody></table>
    </section>
    <section class="card"><h3>יומן</h3>
      <table class="grid-t"><tbody>${events || '<tr><td class="note">אין אירועים</td></tr>'}</tbody></table>
    </section>`;
}

function summaryLine(sum) {
  if (!sum) return '';
  const bits = [];
  if (sum.scores) bits.push('ציונים: ' + Object.entries(sum.scores).map(([k, v]) => `${k} ${v}`).join(', '));
  if (sum.worst) bits.push('הגרוע: ' + sum.worst + ' (' + sum.worst_viewport + ')');
  if (sum.pages_crawled != null) bits.push(sum.pages_crawled + ' עמודים נסרקו');
  if (sum.errors != null) bits.push(sum.errors + ' שגיאות, ' + (sum.warnings || 0) + ' אזהרות');
  if (sum.exposed && sum.exposed.length) bits.push('חשוף: ' + sum.exposed.join(', '));
  if (sum.tls) bits.push('TLS ' + (sum.tls.verified ? 'תקף' : 'לא תקף')
    + (sum.tls.days_left != null ? ` (${sum.tls.days_left} ימים)` : ''));
  if (sum.unavailable) bits.push(sum.unavailable);
  return bits.join(' · ');
}

function sparkline(samples) {
  if (!samples.length) return '<div class="note">אין דגימות עדיין.</div>';
  const w = 600, h = 40, n = samples.length;
  const bw = Math.max(1, w / n);
  const rects = samples.map((s, i) => {
    const x = i * bw;
    const hh = s.ok ? h : h;
    return `<rect x="${x.toFixed(1)}" y="0" width="${Math.max(0.6, bw - 0.4).toFixed(1)}"
      height="${hh}" fill="${s.ok ? 'var(--accent)' : 'var(--red)'}" opacity="${s.ok ? 0.75 : 1}"></rect>`;
  }).join('');
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${rects}</svg>`;
}

// ── tab: scans ───────────────────────────────────────────────────────────────────────────────────
async function tabScans(s) {
  const r = await api(`api/sites/${encodeURIComponent(s.id)}/findings`);
  const findings = (r.ok && r.body.findings) || [];
  const runs = (r.ok && r.body.runs) || [];
  const groups = {};
  findings.forEach((f) => { (groups[f.check] = groups[f.check] || []).push(f); });
  const names = { security: 'אבטחת האתר', seo: 'SEO', beauty: 'ציון יופי' };
  const beautyRun = runs.find((x) => x.check === 'beauty' && x.state !== 'error');
  const shots = (beautyRun && beautyRun.summary && beautyRun.summary.views) || [];

  $('tab').innerHTML = `
    <section class="card"><h3>הרצת סריקה
      <span class="hint">חלק מהבדיקות איטיות: היופי מריץ דפדפן, ה-SEO סורק עד 20 עמודים</span></h3>
      <div class="actions-row" id="scan-row">
        ${(S.checks || []).filter((c) => c.kind === 'scan').map((c) =>
          `<label class="row" style="gap:6px"><input type="checkbox" data-check="${esc(c.name)}"
            ${c.name === 'security' ? 'checked' : ''} style="width:auto"> ${esc(c.title)}</label>`).join('')}
        <button class="btn primary" id="scan-go">הרץ</button>
      </div>
      <div id="scan-out" class="out hidden"></div>
    </section>
    ${shots.length ? `<section class="card"><h3>הצילומים של סריקת היופי האחרונה</h3>
      <div class="shots">${shots.map((v) => v.screenshot ? `
        <div class="shot"><img loading="lazy" alt="${esc(v.viewport)}"
            src="api/sites/${encodeURIComponent(s.id)}/shot?file=${encodeURIComponent(v.screenshot)}">
          <div class="cap"><span>${esc(v.viewport)}</span>
            <span class="score ${scoreClass(v.score, (beautyRun.summary || {}).min)}">${v.score}</span></div>
        </div>` : '').join('')}</div></section>` : ''}
    ${Object.keys(groups).length ? Object.entries(groups).map(([check, list]) => `
      <section class="card"><h3>${esc(names[check] || check)}
        <span class="hint">${list.filter((f) => f.severity === 'error').length} שגיאות ·
          ${list.filter((f) => f.severity === 'warn').length} אזהרות</span></h3>
        ${list.map(findingHtml).join('')}</section>`).join('')
      : `<section class="card"><h3>אין ממצאים פתוחים</h3>
          <p class="note">או שהבדיקות עוד לא רצו. לחץ „הרץ” כדי לסרוק את האתר עכשיו.</p></section>`}
    <section class="card"><h3>היסטוריה</h3>
      <table class="grid-t"><thead><tr><th>בדיקה</th><th>מתי</th><th>מצב</th><th>סיכום</th></tr></thead>
      <tbody>${runs.map((x) => `<tr><td>${esc(names[x.check] || x.check)}</td>
        <td class="ltr">${esc(ago(x.finished_at || x.started_at))}</td><td>${sevChip(x.state)}</td>
        <td>${esc(x.error || summaryLine(x.summary))}</td></tr>`).join('')}</tbody></table></section>`;

  $('scan-go').onclick = async (e) => {
    const picked = [...document.querySelectorAll('[data-check]')]
      .filter((c) => c.checked).map((c) => c.dataset.check);
    if (!picked.length) return;
    const out = $('scan-out');
    out.className = 'out';
    out.classList.remove('hidden');
    out.textContent = 'סורק… (היופי מריץ דפדפן, זה לוקח עד דקה)';
    e.target.disabled = true;
    const res = await api(`api/sites/${encodeURIComponent(s.id)}/scan`, { method: 'POST',
      body: JSON.stringify({ checks: picked }) });
    e.target.disabled = false;
    out.className = 'out ' + (res.ok ? 'ok' : 'err');
    out.textContent = res.ok ? JSON.stringify(res.body.result.checks, null, 2)
                             : ((res.body && res.body.error) || 'שגיאה');
    if (res.ok) render(true);
  };
}

function findingHtml(f) {
  return `<div class="finding ${esc(f.severity)}">
    <div class="ft"><span>${esc(f.title)}</span>
      <span>${sevChip(f.severity)} <span class="badge">${esc(f.check)}</span></span></div>
    ${f.detail ? `<div class="fd">${esc(f.detail)}</div>` : ''}
    ${f.fix ? `<div class="fx">תיקון: ${esc(f.fix)}</div>` : ''}
    ${f.url ? `<div class="fd ltr">${esc(f.url)}</div>` : ''}
  </div>`;
}

// ── tab: visits ──────────────────────────────────────────────────────────────────────────────────
async function tabVisits(s) {
  const r = await api(`api/sites/${encodeURIComponent(s.id)}/visits?days=7`);
  if (!r.ok) return fail(r);
  const d = r.body;
  const series = d.series || [];
  const max = Math.max(1, ...series.map((x) => x.hits));
  const bars = series.length ? series.map((x) => {
    const h = Math.max(2, Math.round((x.hits / max) * 90));
    return `<div class="b" style="height:${h}px" title="${new Date(x.hour * 1000).toLocaleString('he-IL')} — ${x.hits} פניות"></div>`;
  }).join('') : '';
  const t = d.totals || {};
  $('tab').innerHTML = `
    <section class="card"><h3>ביקורים — 7 ימים
      <span class="hint">מתוך ${esc((d.source || {}).kind === 'file' ? 'לוג האתר' : 'לוג הקונטיינר')}</span></h3>
      <div class="vitals">
        <div class="vital"><div class="k">פניות (hits)</div><div class="v">${t.hits || 0}</div></div>
        <div class="vital"><div class="k">מבקרים ייחודיים</div><div class="v">${t.uniques || 0}</div>
          <div class="note">לפי IP, בשעה</div></div>
        <div class="vital"><div class="k">בוטים וסורקים</div><div class="v">${t.bots || 0}</div>
          <div class="note">נספרים בנפרד — לא נכנסים לספירת האנשים</div></div>
        <div class="vital"><div class="k">שגיאות 4xx/5xx</div><div class="v">${t.errors || 0}</div></div>
        <div class="vital"><div class="k">תעבורה</div><div class="v">${bytes(t.bytes)}</div></div>
      </div>
      <div class="bars">${bars}</div>
      <div class="note">כל עמודה = שעה. ${series.length ? 'מ-' + new Date(series[0].hour * 1000).toLocaleString('he-IL') : 'אין נתונים עדיין.'}</div>
    </section>
    <div class="grid">
      <section class="card"><h3>העמודים הנצפים</h3>
        <table class="grid-t"><tbody>${(d.paths || []).map((p) =>
          `<tr><td class="ltr">${esc(p.path)}</td><td style="width:70px">${p.hits}</td></tr>`).join('')
          || '<tr><td class="note">אין נתונים</td></tr>'}</tbody></table></section>
      <section class="card"><h3>מאיפה הגיעו</h3>
        <table class="grid-t"><tbody>${(d.refs || []).map((p) =>
          `<tr><td class="ltr">${esc(p.ref)}</td><td style="width:70px">${p.hits}</td></tr>`).join('')
          || '<tr><td class="note">אין נתוני הפניות</td></tr>'}</tbody></table></section>
    </div>`;
}

// ── tab: ops (the pattern, the stack, the logs) ───────────────────────────────────────────────────
async function tabOps(s) {
  $('tab').innerHTML = `
    <section class="card"><h3>הדפוס שעל המחשב</h3>
      <div class="kv">
        <div class="k">מחשב</div><div class="ltr">${esc(s.machine)}</div>
        <div class="k">תיקייה</div><div class="ltr">${esc(s.root)}</div>
        <div class="k">פרויקט compose</div><div class="ltr">${esc(s.project)}</div>
        <div class="k">קונטיינר</div><div class="ltr">${esc(s.container)}</div>
        <div class="k">סוג</div><div>${esc(s.kind)} · ${esc((s.content || {}).type || '')}
          ${s.managed ? '' : '<span class="chip warn">נלקח כמו שהוא — לא מנוהל על ידי הלשכה</span>'}</div>
        <div class="k">קצה</div><div class="ltr">${esc(JSON.stringify(s.edge || {}))}</div>
      </div>
      <div class="actions-row" style="margin-top:12px">
        <button class="btn" id="show-stack">הצג את הקבצים שייכתבו</button>
        <button class="btn" id="show-logs">לוג הקונטיינר</button>
        <button class="btn" id="show-audit">אבטחת המחשב שמארח את האתר</button>
      </div>
      <div id="audit-box"></div>
      <div id="ops-out" class="out hidden"></div>
    </section>`;
  /* The SITE's security is one question and the HOST's is another — a perfectly hardened site on a
     server that accepts SSH passwords is still a business about to have a bad week. The second
     answer belongs to the computers app; this asks it there and shows it here, because the person
     looking at a site is the person who needs it. */
  $('show-audit').onclick = async (e) => {
    e.target.disabled = true;
    $('audit-box').innerHTML = '<div class="note">בודק את המחשב…</div>';
    const r = await api('api/machines/' + encodeURIComponent(s.machine) + '/audit');
    e.target.disabled = false;
    if (!r.ok) {
      $('audit-box').innerHTML = `<div class="out err">${esc((r.body && r.body.error) || 'שגיאה')}</div>`;
      return;
    }
    const d = r.body;
    const he = { error: 'שגיאה', warn: 'אזהרה', info: 'מידע', ok: 'תקין' };
    const must = (d.findings || []).filter((f) => f.severity === 'error' || f.severity === 'warn');
    $('audit-box').innerHTML = `
      <div class="finding ${d.counts.error ? 'error' : d.counts.warn ? 'warn' : 'ok'}" style="margin-top:12px">
        <div class="ft"><span>המחשב ${esc(d.label || d.host)} — ${d.counts.error} שגיאות,
          ${d.counts.warn} אזהרות</span>
          <span class="btn" style="cursor:default">נבדק ${esc(ago(d.checked_at))}</span></div>
        ${must.map((f) => `<div class="fd"><b>${esc(he[f.severity])}:</b> ${esc(f.title)}
          ${f.fix ? ` — <span class="fx">${esc(f.fix)}</span>` : ''}</div>`).join('')
          || '<div class="fd">לא נמצאו בעיות אבטחה במחשב.</div>'}
        <div class="fd">הפירוט המלא במסך „מחשבים” → אבטחה.</div>
      </div>`;
  };
  $('show-stack').onclick = async () => {
    const r = await api(`api/sites/${encodeURIComponent(s.id)}/stack`);
    const out = $('ops-out');
    out.classList.remove('hidden');
    if (!r.ok) { out.className = 'out err'; out.textContent = r.body.error; return; }
    S.stack = r.body.files;
    out.className = 'out ok';
    out.innerHTML = '';
    const box = document.createElement('div');
    box.innerHTML = `<div class="files">${Object.keys(S.stack).map((f) =>
      `<button class="btn" data-f="${esc(f)}">${esc(f)}</button>`).join('')}</div>
      <pre class="code" id="file-body"></pre>`;
    out.appendChild(box);
    const show = (f) => { $('file-body').textContent = S.stack[f]; };
    box.querySelectorAll('[data-f]').forEach((b) => { b.onclick = () => show(b.dataset.f); });
    show(Object.keys(S.stack)[0]);
  };
  $('show-logs').onclick = async () => {
    const r = await api(`api/sites/${encodeURIComponent(s.id)}/logs?lines=200`);
    const out = $('ops-out');
    out.classList.remove('hidden');
    out.className = 'out ' + (r.ok ? '' : 'err');
    out.textContent = r.ok ? r.body.logs : (r.body.error || 'שגיאה');
  };
}

// ── tab: settings ────────────────────────────────────────────────────────────────────────────────
async function tabSettings(s) {
  const cfg = s.checks || {};
  $('tab').innerHTML = `
    <section class="card"><h3>הגדרות האתר</h3>
      <div class="grid">
        <div><label>שם</label><input id="f-label" value="${esc(s.label || '')}"></div>
        <div><label>דומיינים (שורה לכל אחד, הראשון הוא הראשי)</label>
          <textarea id="f-hosts">${esc((s.hosts || []).join('\n'))}</textarea></div>
        <div><label>מחשב</label><select id="f-machine">
          ${(S.machines.length ? S.machines : [{ id: s.machine, label: s.machine }]).map((m) =>
            `<option value="${esc(m.id)}" ${m.id === s.machine ? 'selected' : ''}>${esc(m.label || m.id)}</option>`).join('')}
        </select></div>
        <div><label>תיקייה על המחשב</label><input id="f-root" class="ltr" value="${esc(s.root)}"></div>
        <div><label>נתיב בדיקת חיים</label><input id="f-health" class="ltr" value="${esc(s.health_path)}"></div>
        <div><label>סף ציון יופי</label><input id="f-bmin" type="number" value="${esc(cfg.beauty_min || 70)}"></div>
        <div><label>עמודי SEO בסריקה</label><input id="f-seopages" type="number" value="${esc(cfg.seo_pages || 20)}"></div>
        <div><label>תדירות סריקת אבטחה (שעות)</label><input id="f-sech" type="number" value="${esc(cfg.security_hours || 24)}"></div>
      </div>
      <label class="row" style="margin-top:12px"><input type="checkbox" id="f-monitor"
        ${s.monitor ? 'checked' : ''} style="width:auto"> לנטר זמינות כל דקה</label>
      <div class="actions-row" style="margin-top:12px">
        <button class="btn primary" id="save">שמור</button>
        <button class="btn" id="redetect">זהה קצה מחדש</button>
        ${s.managed ? '' : `<button class="btn" id="migrate">העבר לדפוס הקבוע</button>`}
      </div>
      <div id="set-out" class="out hidden"></div>
    </section>
    <section class="card"><h3>נתיב ציבורי</h3>
      <p class="note">הנתיב הציבורי הוא הכתובת שהעולם רואה: דומיין (מתוך „דומיינים”) ונתיב בתוכו.
        במצב <b>הלשכה</b> האתר מוגש מהלשכה עצמה — בלי SSO, ישירות מהקצה — והקונטיינר של האתר
        במכונה נעצר. במצב <b>המכונה</b> החבילה שעל המכונה ממשיכה להגיש אותו כמו היום.
        הטקסטים, התמונות והלוגו נאספים תמיד מ„נכסים דיגיטליים”.</p>
      <div class="grid">
        <div><label>מי מגיש את האתר</label><select id="f-pmode">
          <option value="container" ${(s.public || {}).mode === 'office' ? '' : 'selected'}>המכונה (הקונטיינר של האתר)</option>
          <option value="office" ${(s.public || {}).mode === 'office' ? 'selected' : ''}>הלשכה (הנתיב הציבורי)</option>
        </select></div>
      </div>
      <div id="pub-entries" style="margin-top:10px"></div>
      <datalist id="datalist-domains"></datalist>
      <div class="actions-row" style="margin-top:10px">
        <button class="btn" id="pub-add">הוסף נתיב</button>
        <button class="btn primary" id="pub-save">שמור נתיב ציבורי</button>
        <button class="btn" id="pub-sync">אסוף את התוכן ללשכה</button>
        <button class="btn" id="pub-slots">מה כבר נכס דיגיטלי</button>
      </div>
      <div id="pub-out" class="out hidden"></div>
      <div id="pub-slots-out"></div>
    </section>
    <section class="card"><h3>הסרה מהניהול</h3>
      <p class="note">הסרה מוציאה את האתר מהמסך. הפעולה <b>לא</b> מוחקת את תוכן האתר ולא את
        הפריסה שלו — אלא אם תבחר במפורש למחוק.</p>
      <div class="actions-row">
        <button class="btn danger" id="del">הסר מהניהול</button>
        <button class="btn danger" id="del-purge">הסר ומחק את תיקיית האתר</button>
      </div>
      <div id="del-out" class="out hidden"></div>
    </section>`;
  $('save').onclick = async () => {
    const payload = {
      label: $('f-label').value.trim(),
      hosts: $('f-hosts').value.split(/\s*[,\n]\s*/).filter(Boolean),
      machine: $('f-machine').value,
      root: $('f-root').value.trim(),
      health_path: $('f-health').value.trim() || '/',
      monitor: $('f-monitor').checked,
      checks: { ...cfg, beauty_min: Number($('f-bmin').value) || 70,
                seo_pages: Number($('f-seopages').value) || 20,
                security_hours: Number($('f-sech').value) || 24 },
    };
    const r = await api(`api/sites/${encodeURIComponent(s.id)}`, { method: 'PATCH',
      body: JSON.stringify(payload) });
    showOut('#set-out', r, 'נשמר. שינוי שנגע בקצה או בדומיין דורש „פרוס מחדש”.');
  };
  $('redetect').onclick = async () => {
    const r = await api(`api/machines/${encodeURIComponent($('f-machine').value)}/edge`);
    if (!r.ok) return showOut('#set-out', r, '');
    const e = (r.body.edges || [])[0];
    showOut('#set-out', { ok: true, body: { found: !!e, edge: e } },
      'אם נמצא קצה — שמור אותו ב„הגדרות” ואז פרוס מחדש.');
  };
  if ($('migrate')) $('migrate').onclick = async () => {
    if (!await binaAsk({ title: 'להעביר את האתר לדפוס הקבוע?', ok: 'העברה', facts: [['תיקייה', s.root]],
      body: 'הלשכה תרנדר חבילת אתר ותרים אותה לצד הפריסה הקיימת. הפריסה הישנה לא נעצרת עד שתאשר.' })) return;
    const r = await api(`api/sites/${encodeURIComponent(s.id)}/deploy`, { method: 'POST',
      body: JSON.stringify({}) });
    showOut('#set-out', r, 'אם האתר החדש עולה — אפשר לעצור את הפריסה הקיימת ולעדכן source.');
  };
  // ── the public path ────────────────────────────────────────────────────────────────────────────
  // The record's own default (one entry per host, the www twin as a redirect) is mirrored here so
  // the screen shows what would be published even before anyone edits it.
  const pub = s.public || {};
  let entries = (Array.isArray(pub.entries) && pub.entries.length) ? pub.entries.map((e) => ({ ...e }))
    : (s.hosts || []).map((h, i) => ({
        domain: h, path: '/',
        redirect: !!(s.edge && s.edge.canonical_redirect) && i > 0 &&
          h === ((s.hosts[0] || '').startsWith('www.') ? s.hosts[0].slice(4) : 'www.' + s.hosts[0]),
      }));
  let domainNames = (s.hosts || []).slice();
  const paintEntries = () => {
    const list = domainNames.map((d) => `<option value="${esc(d)}"></option>`).join('');
    $('datalist-domains').innerHTML = list;
    $('pub-entries').innerHTML = entries.map((e, i) => `
      <div class="grid" style="margin-top:6px">
        <div><label>דומיין ${i === 0 ? '(ראשי)' : ''}</label>
          <input class="ltr pub-domain" data-i="${i}" list="datalist-domains" value="${esc(e.domain || '')}"></div>
        <div><label>נתיב</label>
          <input class="ltr pub-path" data-i="${i}" value="${esc(e.path || '/')}"></div>
        <div><label>הפניה לדומיין הראשי</label>
          <label class="row" style="margin-top:6px"><input type="checkbox" class="pub-redirect"
            data-i="${i}" ${e.redirect ? 'checked' : ''} style="width:auto"> 301</label></div>
        <div><label>&nbsp;</label><button class="btn pub-del" data-i="${i}">הסר</button></div>
      </div>`).join('');
    document.querySelectorAll('.pub-domain').forEach((el) => el.oninput = () => {
      entries[+el.dataset.i].domain = el.value.trim().toLowerCase(); });
    document.querySelectorAll('.pub-path').forEach((el) => el.oninput = () => {
      entries[+el.dataset.i].path = el.value.trim(); });
    document.querySelectorAll('.pub-redirect').forEach((el) => el.onchange = () => {
      entries[+el.dataset.i].redirect = el.checked; });
    document.querySelectorAll('.pub-del').forEach((el) => el.onclick = () => {
      entries.splice(+el.dataset.i, 1); paintEntries(); });
  };
  paintEntries();
  api('api/domains').then((r) => {
    const names = (r.ok && (r.body.domains || []).map((d) => d.name)) || [];
    domainNames = [...new Set([...(s.hosts || []), ...names])];
    paintEntries();
  });
  $('pub-add').onclick = () => { entries.push({ domain: '', path: '/', redirect: false }); paintEntries(); };
  $('pub-save').onclick = async () => {
    if (!entries.length) return showOut('#pub-out', { ok: false, body: { error: 'צריך לפחות נתיב אחד' } }, '');
    const r = await api(`api/sites/${encodeURIComponent(s.id)}`, { method: 'PATCH',
      body: JSON.stringify({ public: { mode: $('f-pmode').value, entries } }) });
    const conv = (r.body && r.body.public) || {};
    const hint = conv.mode === 'office'
      ? 'הלשכה מגישה את האתר. אם הקונטיינר נעצר והקצה פורסם — האתר זמין בכתובת שבדומיין.'
      : 'האתר נשאר מוגש מהמכונה; הראוטרים של הלשכה הוסרו.';
    showOut('#pub-out', r, hint);
  };
  $('pub-sync').onclick = async () => {
    const r = await api(`api/sites/${encodeURIComponent(s.id)}/sync`, { method: 'POST',
      body: JSON.stringify({ force: true }) });
    showOut('#pub-out', r, 'התוכן נאסף מהמכונה למטמון של הלשכה.');
  };
  $('pub-slots').onclick = async () => {
    const r = await api(`api/sites/${encodeURIComponent(s.id)}/slots`);
    if (!r.ok) return showOut('#pub-out', r, '');
    const b = r.body || {};
    const mapped = (b.pages || []).reduce((n, p) => n + (p.mapped || []).length, 0);
    const free = (b.unmapped || []).length;
    $('pub-slots-out').innerHTML = `<p class="note">${mapped} ערכים כבר נכסים דיגיטליים ·
      ${free} טקסטים/תמונות שעוד כתובים ביד · עודכן ${esc(ago(b.synced_at))}</p>`;
  };
  $('del').onclick = () => del(s, false);
  $('del-purge').onclick = () => del(s, true);
}

async function del(s, purge) {
  let confirmToken = '';
  if (purge) {
    // the action is not offered until the site's id is typed: deleting a directory is for good
    const typed = await binaAsk({ title: 'למחוק את תיקיית האתר?', body: 'המחיקה אינה הפיכה.', ok: 'מחיקה לצמיתות',
      danger: true, facts: [['תיקייה', s.root], ['מחשב', s.machine]],
      input: { label: 'להמשך, הקלד את מזהה האתר: ' + s.id, must: s.id, dir: 'ltr' } });
    if (typed == null) return;
    confirmToken = s.id;
  } else if (!await binaAsk({ title: 'להסיר את האתר מהניהול?', ok: 'הסרה', danger: true,
                             body: 'הקונטיינר ייעצר, התוכן יישאר.' })) return;
  const r = await api(`api/sites/${encodeURIComponent(s.id)}?purge_files=${purge ? 1 : 0}` +
    `&confirm=${encodeURIComponent(confirmToken)}&stop=1`, { method: 'DELETE' });
  if (r.ok) { go('#/'); return; }
  showOut('#del-out', r, '');
}

function showOut(sel, r, okMsg) {
  const el = $(sel);
  el.classList.remove('hidden');
  el.className = 'out ' + (r.ok ? 'ok' : 'err');
  el.textContent = r.ok ? (okMsg || JSON.stringify(r.body, null, 2))
                        : ((r.body && (r.body.error || r.body.detail)) || binaSaid(r.status));
}

// ── new site wizard ──────────────────────────────────────────────────────────────────────────────
async function wizard() {
  if (!S.machines.length) {
    const m = await api('api/machines?probe=1');
    if (m.ok) S.machines = m.body.machines || [];
  }
  $('title').textContent = 'אתר חדש';
  $('sub').textContent = 'הלשכה תרנדר חבילת אתר על המחשב שתבחר ותרים אותה.';
  if (!S.machines.length) {
    $('view').innerHTML = `<section class="card"><h3>אין מחשבים זמינים</h3>
      <p class="note">כדי להרים אתר צריך מחשב ברשימת „מחשבים”. הוסף מחשב שם (ואשר את המפתח),
        ואז חזור לכאן.</p></section>`;
    return;
  }
  const kinds = [['static', 'אתר סטטי', 'קבצים שיושבים בתיקייה ונמסרים על ידי nginx'],
                 ['static-built', 'אתר שנבנה מקוד', 'מאגר git שנבנה (Eleventy/Vite/…) ואז נמסר'],
                 ['proxy', 'פרוקסי', 'האתר רץ במקום אחר וה-nginx של הלשכה מגיש אותו']];
  $('view').innerHTML = `
    <section class="card"><h3>פרטי האתר</h3>
      <div class="grid">
        <div><label>מזהה (אנגלית, מקפים)</label><input id="n-id" class="ltr" placeholder="my-site"></div>
        <div><label>שם</label><input id="n-label" placeholder="האתר שלי"></div>
        <div><label>דומיינים (שורה לכל אחד; הראשון ראשי)</label>
          <textarea id="n-hosts" class="ltr" placeholder="example.co.il\nwww.example.co.il"></textarea></div>
        <div><label>מחשב</label><select id="n-machine">${S.machines.map((m) =>
          `<option value="${esc(m.id)}">${esc(m.label || m.id)} — ${esc(m.host || '')}</option>`).join('')}</select></div>
        <div><label>תיקייה על המחשב (ריק = /opt/bina-sites/&lt;id&gt;)</label>
          <input id="n-root" class="ltr"></div>
      </div>
      <label style="margin-top:14px">סוג האתר</label>
      <div class="grid" id="n-kinds">${kinds.map(([k, t, d], i) =>
        `<div class="prov ${i === 0 ? 'sel' : ''}" data-kind="${k}">
          <div class="name">${t}</div><div class="meta">${d}</div></div>`).join('')}</div>
      <div id="n-content" style="margin-top:10px"></div>
      <div class="actions-row" style="margin-top:14px">
        <button class="btn primary" id="n-create">צור אתר</button>
        <label class="row" style="gap:6px"><input type="checkbox" id="n-deploy" checked
          style="width:auto"> ופרוס אותו על המחשב מיד</label>
        <button class="btn ghost" onclick="location.hash='#/'">ביטול</button>
      </div>
      <div id="n-out" class="out hidden"></div>
    </section>`;
  let kind = 'static';
  const contentFor = (k) => {
    if (k === 'static') return `<label>תיקיית התוכן בתוך תיקיית האתר</label>
      <input id="n-dir" class="ltr" value="site">`;
    if (k === 'static-built') return `<div class="grid">
      <div><label>מאגר git</label><input id="n-repo" class="ltr" placeholder="https://github.com/…"></div>
      <div><label>ענף</label><input id="n-branch" class="ltr" value="main"></div>
      <div><label>פקודת הבנייה (בתוך הקונטיינר)</label>
        <input id="n-build" class="ltr" value="npm ci && npm run build"></div></div>`;
    return `<label>כתובת ה-upstream</label>
      <input id="n-upstream" class="ltr" placeholder="http://host:port">`;
  };
  $('n-content').innerHTML = contentFor('static');
  document.querySelectorAll('[data-kind]').forEach((el) => {
    el.onclick = () => {
      kind = el.dataset.kind;
      document.querySelectorAll('[data-kind]').forEach((x) => x.classList.toggle('sel', x === el));
      $('n-content').innerHTML = contentFor(kind);
    };
  });
  $('n-create').onclick = async (e) => {
    const id = $('n-id').value.trim().toLowerCase();
    const body = {
      id, label: $('n-label').value.trim() || id, kind,
      hosts: $('n-hosts').value.split(/\s*[,\n]\s*/).filter(Boolean),
      machine: $('n-machine').value,
      root: $('n-root').value.trim() || undefined,
      deploy: $('n-deploy').checked,
      content: kind === 'static'
        ? { type: 'dir', dir: $('n-dir').value.trim() || 'site' }
        : kind === 'static-built'
          ? { type: 'git', repo: $('n-repo').value.trim(), branch: $('n-branch').value.trim() || 'main',
              build: { command: $('n-build').value.trim() } }
          : { type: 'dir', upstream: $('n-upstream').value.trim() },
    };
    e.target.disabled = true;
    const r = await api('api/sites', { method: 'POST', body: JSON.stringify(body) });
    e.target.disabled = false;
    showOut('#n-out', r, '');
    if (r.ok) go('#/s/' + id);
  };
}

// ── adoption ─────────────────────────────────────────────────────────────────────────────────────
async function adopt() {
  if (!S.machines.length) {
    const m = await api('api/machines?probe=0');
    if (m.ok) S.machines = m.body.machines || [];
  }
  $('title').textContent = 'אימוץ אתר קיים';
  $('sub').textContent = 'קונטיינר שכבר מגיש אתר על אחד המחשבים — הלשכה תנהל אותו כמו את שלה.';
  $('view').innerHTML = `
    <section class="card"><h3>מה לאמץ</h3>
      <div class="grid">
        <div><label>מחשב</label><select id="a-machine">${S.machines.map((m) =>
          `<option value="${esc(m.id)}">${esc(m.label || m.id)} — ${esc(m.host || '')}</option>`).join('')}</select></div>
        <div><label>שם הקונטיינר</label><input id="a-container" class="ltr" placeholder="my-site-web"></div>
      </div>
      <div class="actions-row" style="margin-top:12px">
        <button class="btn" id="a-inspect">בדוק מה רץ שם</button>
        <button class="btn ghost" onclick="location.hash='#/'">ביטול</button>
      </div>
      <div id="a-out" class="out hidden"></div>
    </section>
    <div id="a-form"></div>`;
  $('a-inspect').onclick = async (e) => {
    e.target.disabled = true;
    const r = await api(`api/machines/${encodeURIComponent($('a-machine').value)}/inspect`,
      { method: 'POST', body: JSON.stringify({ container: $('a-container').value.trim() }) });
    e.target.disabled = false;
    showOut('#a-out', r, '');
    if (!r.ok) return;
    const c = r.body;
    if (!c.found) { $('a-form').innerHTML = ''; return; }
    $('a-form').innerHTML = `
      <section class="card"><h3>מה נמצא</h3>
        <div class="kv">
          <div class="k">image</div><div class="ltr">${esc(c.image)}</div>
          <div class="k">פרויקט</div><div class="ltr">${esc(c.project || '—')}</div>
          <div class="k">תיקייה</div><div class="ltr">${esc(c.working_dir || '—')}</div>
          <div class="k">דומיינים בתוויות</div><div class="ltr">${esc((c.hosts || []).join(' · ') || '—')}</div>
          <div class="k">mounts</div><div class="ltr">${esc((c.mounts || []).map((m) => m.source + ' → ' + m.dest).join('\n'))}</div>
        </div>
        <div class="grid" style="margin-top:12px">
          <div><label>מזהה האתר בלשכה</label><input id="a-id" class="ltr"></div>
          <div><label>שם</label><input id="a-label"></div>
        </div>
        <div class="actions-row" style="margin-top:12px">
          <button class="btn primary" id="a-create">אמץ את האתר</button>
        </div>
        <div id="a-2" class="out hidden"></div>
      </section>`;
    $('a-create').onclick = async (ev) => {
      const id = $('a-id').value.trim().toLowerCase();
      const body = {
        id, label: $('a-label').value.trim() || id,
        machine: $('a-machine').value, hosts: c.hosts || [], kind: 'static',
        source: 'adopted', monitor: true,
        legacy: { container: c.container, project: c.project, dir: c.working_dir,
                  compose: c.compose_files },
        root: c.working_dir || (`/opt/bina-sites/` + id), project: c.project || ('site-' + id),
        notes: 'נלקח כמו שהוא — הפריסה נשארת אצל מי שהקים אותה עד שמועבר לדפוס הקבוע',
      };
      ev.target.disabled = true;
      const r2 = await api('api/sites', { method: 'POST', body: JSON.stringify(body) });
      ev.target.disabled = false;
      showOut('#a-2', r2, '');
      if (r2.ok) go('#/s/' + id);
    };
  };
}

boot();
