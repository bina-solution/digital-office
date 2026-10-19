/* version control — the office's OWN two screens, and nothing that displays a repository.
 *
 * The owner's direction (DGO-57) is that 99% of the display is the open-source one: Forgejo is the
 * shell's tile and it renders repositories, diffs, issues, PRs and releases far better than anything
 * written here. So what is left in this app is exactly what only the OFFICE knows and Forgejo cannot:
 * the ACCOUNTS it acts with (GitHub, GitLab, the local forge — tokens in the credential plane) and
 * the MIRRORS it declares (which external repository is copied into the forge for browsing).
 *
 * There is deliberately NO repository list, NO file tree, NO issue/PR/release view and NO code
 * viewer here. An earlier version had all of them; it went into history in DGO-4 and was removed
 * again in DGO-57, because two places that show repositories is one place too many.
 *
 * Vanilla JS, relative URLs (the console serves this app and injects <base href>), no build step.
 */
'use strict';

const $ = (id) => document.getElementById(id);

/* ── helpers ─────────────────────────────────────────────────────────────────────────────────── */
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
/* `when` is what the service gives: unix SECONDS for a mirror's last run (the registry's own
 * clock), an ISO string elsewhere. Parsing the number as a date string gave no time at all, so
 * every mirror row read " · 1.25GB" — a separator with nothing before it — since the day it shipped. */
function timeAgo(when) {
  if (!when) return '';
  const t = typeof when === 'number' ? when * 1000 : Date.parse(when);
  if (!t) return '';
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 60) return 'עכשיו';
  if (s < 3600) return `לפני ${Math.round(s / 60)} דק׳`;
  if (s < 86400) return `לפני ${Math.round(s / 3600)} שע׳`;
  if (s < 2592000) return `לפני ${Math.round(s / 86400)} ימים`;
  return new Date(t).toLocaleDateString('he-IL');
}
function bytes(n) {
  if (!n && n !== 0) return '';
  if (n > 1024 ** 3) return (n / 1024 ** 3).toFixed(2) + 'GB';
  if (n > 1024 ** 2) return Math.round(n / 1024 ** 2) + 'MB';
  if (n > 1024) return Math.round(n / 1024) + 'KB';
  return n + 'B';
}
const PROVIDER_HE = { github: 'GitHub', gitlab: 'GitLab', forgejo: "פורג' מקומי", generic: 'מארח אחר' };
/* The states the service really reports (accounts.probe_instance: ok | git_only | needs_action), plus
 * `unknown` — what the CHEAP list returns before anything is probed. Each one is a different sentence
 * to the owner, so each is its own chip; a state this app has not been taught is shown as itself
 * rather than coloured green. */
const STATE_HE = {
  ok: ['מחובר', 'ok'],
  git_only: ['קוד בלבד', ''],
  needs_action: ['דורש טיפול', 'bad'],
  unknown: ['לא נבדק', ''],
};
const MIRROR_HE = { ok: ['מסונכרן', 'ok'], new: ['עוד לא סונכרן', ''], error: ['הסנכרון נכשל', 'bad'] };
function stateChip(a) {
  const [txt, cls] = STATE_HE[a.state] || [a.state || 'לא ידוע', ''];
  return `<span class="chip ${cls}">${esc(txt)}</span>`;
}
const ICO = {
  branch: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="6" cy="5" r="2.5"/><circle cx="6" cy="19" r="2.5"/><circle cx="18" cy="9" r="2.5"/><path d="M6 7.5v9M18 11.5c0 4-6 2.5-6 6"/></svg>',
  sync: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 11a8 8 0 0 0-14-5M4 13a8 8 0 0 0 14 5"/><path d="M4 6v5h5M20 18v-5h-5"/></svg>',
  plus: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 5v14M5 12h14"/></svg>',
  ext: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 5h5v5M19 5l-8 8M12 5H7a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5"/></svg>',
};

/* ── api ─────────────────────────────────────────────────────────────────────────────────────── */
async function jget(path) {
  try {
    const r = await fetch(path, { headers: { accept: 'application/json' } });
    return await r.json();
  } catch (e) {
    return { ok: false, error: 'השירות אינו מגיב' };   // (it added the error's type — «(TypeError)» — which names nothing a person can act on)
  }
}
/* ── state ───────────────────────────────────────────────────────────────────────────────────── */
const S = { accounts: [], active: null, loaded: false, vault_error: null, mirrors: null,
            wiz: { provider: null, method: null } };

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

/* ── accounts ────────────────────────────────────────────────────────────────────────────────── */
const acctById = (id) => S.accounts.find((a) => a.id === id) || null;
/** A mirror names its source by vault id; a person reads labels. */
const _acctLabel = (id) => {
  const a = acctById(id);
  return a ? (a.label || a.login || id) : (id || '—');
};

async function loadAccounts(force, probe) {
  if (S.loaded && !force) return;
  const d = await jget('connections?probe=' + (probe ? 1 : 0));
  if (d && d.connections) {
    S.accounts = d.connections;
    S.active = d.active || null;
    S.loaded = true;
    /* A failing vault is not an empty vault: /connections answers 200 with a `reason` when it cannot be
     * read, and reporting that as "no accounts" would send the owner to connect one all over again. A
     * read that SUCCEEDS clears the previous complaint, or a fixed vault keeps showing its old error. */
    S.vault_error = d.reason || null;
  } else if (d && d.error) {
    S.vault_error = d.error;
  }
  renderTop();
  renderNav();
}

function renderTop() {
  /* The account line lives in the MENU's brand now, not in a top bar of our own: navigation is the
     component's, and the one thing this line must say is which credential the office is acting as. */
  if (NAV) NAV.setBrand({ sub: brandSub() });
}

async function viewAccounts() {
  $('main').innerHTML = `<div class="card"><div class="skel">טוען חשבונות…</div></div>`;
  await loadAccounts(true, false);
  const p = await jget('providers');
  const provs = (p && p.providers) || [];
  renderAccounts(provs);
  /* The cheap list paints instantly (it is what makes the screen feel alive); the REAL state of each
   * credential is probed right after, and the chips are corrected. Both matter: a screen that shows
   * "not checked" for a live token, and one that shows a green chip it never earned, are the same bug
   * seen from the owner's side. The second paint is skipped if he has left this screen meanwhile. */
  loadAccounts(true, true).then(() => {
    if (parseHash().parts[0] !== 'mirrors') renderAccounts(provs);
  }).catch(() => {});
}

/* Two accounts of ONE user at one provider look like one row drawn twice (they are two tokens — the
 * vault keeps both, and an account connected again is added, not replaced). Each says whose twin it
 * is, so the owner can tell a duplicate from a mistake of the screen and disconnect the one he
 * does not need. */
function twinsOf(a) {
  const who = (x) => x.provider + '|' + String(x.login || x.account_hint || '').split('@')[0].toLowerCase();
  if (who(a).endsWith('|')) return [];
  return S.accounts.filter((x) => x.id !== a.id && who(x) === who(a)).map((x) => x.label || x.login);
}

function renderAccounts(provs) {
  $('main').innerHTML = `
    <div class="card">
      ${S.accounts.map((a) => `
        <div class="item-row">
          <span class="avatar">${esc(((a.login || a.label || '?')).slice(0, 1).toUpperCase())}</span>
          <div class="grow">
            <div class="ttl">${esc(a.label || a.login)} ${a.id === S.active ? '<span class="chip ok">פעיל</span>' : ''}</div>
            <div class="sub">
              <span>${esc(PROVIDER_HE[a.provider] || a.provider || '')}</span>
              <span class="ltr">${esc(a.login || a.account_hint || '')}</span>
              ${stateChip(a)}
            </div>
            ${a.reason || a.note ? `<div class="note">${esc(a.reason || a.note)}</div>` : ''}
            ${twinsOf(a).length ? `<div class="note">אותו משתמש כמו ${twinsOf(a).map((l) => '„' + esc(l) + '”').join(', ')}</div>` : ''}
          </div>
          <div class="row">
            ${a.id === S.active ? '' : `<button class="btn sm" data-act="select" data-id="${esc(a.id)}">בחר כפעיל</button>`}
            <button class="btn sm" data-act="probe" data-id="${esc(a.id)}">בדוק</button>
            <button class="btn sm danger" data-act="del" data-id="${esc(a.id)}">נתק</button>
          </div>
        </div>`).join('') || `<div class="empty">${S.vault_error
          ? 'לא ניתן להציג את החשבונות — ראו את השגיאה למטה.'
          : 'לא מחובר אף חשבון. חבר אחד למטה.'}</div>`}
    </div>
    ${S.vault_error ? `<div class="card"><div class="body"><div class="err">לא ניתן לקרוא את מאגר
      החשבונות: ${esc(S.vault_error)}</div></div></div>` : ''}
    <div class="card">
      <header><h2>חיבור חשבון חדש</h2></header>
      <div class="body">
        <div class="row" id="prov">${provs.map((x) => `<button class="btn" data-p="${esc(x.id)}">${esc(x.name)}</button>`).join('')}</div>
        <div id="method" class="hidden"></div>
        <div id="fields" class="hidden"></div>
      </div>
    </div>`;

  $('main').querySelectorAll('[data-act]').forEach((b) => {
    b.onclick = async () => {
      const id = b.dataset.id;
      if (b.dataset.act === 'select') {
        await fetch('connections/select', {
          method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ id }),
        });
        await loadAccounts(true); viewAccounts();
      } else if (b.dataset.act === 'probe') {
        b.disabled = true;
        await fetch('api/accounts/' + encodeURIComponent(id) + '/probe');
        await loadAccounts(true); viewAccounts();
      } else {
        if (!await binaAsk({ title: 'לנתק את החשבון?', body: 'הטוקן יימחק מהכספת.', ok: 'ניתוק', danger: true })) return;
        await fetch('api/accounts/' + encodeURIComponent(id), { method: 'DELETE' });
        await loadAccounts(true); viewAccounts();
      }
    };
  });
  $('main').querySelectorAll('[data-p]').forEach((b) => {
    b.onclick = () => {
      S.wiz.provider = provs.find((x) => x.id === b.dataset.p);
      S.wiz.method = null;
      const box = $('method');
      box.classList.remove('hidden');
      box.innerHTML = `<div class="note">איך להתחבר:</div>` +
        (S.wiz.provider.auth_methods || []).map((m) => `
          <div class="pick" data-m="${esc(m.id)}">
            <div class="ttl">${esc(m.label)}${m.recommended ? ' · מומלץ' : ''}</div>
            <div class="note">${esc(m.explain || '')}</div>
          </div>`).join('');
      box.querySelectorAll('[data-m]').forEach((row) => {
        row.onclick = () => {
          S.wiz.method = (S.wiz.provider.auth_methods || []).find((m) => m.id === row.dataset.m);
          renderWizard();
        };
      });
    };
  });
}

function renderWizard() {
  const box = $('fields');
  const f = (S.wiz.method.fields || []).filter((x) => x.name !== 'readonly');
  box.classList.remove('hidden');
  box.innerHTML = `<div class="field"><label>שם לחיבור (לא חובה)</label><input id="w-label"></div>` +
    f.map((x) => `<div class="field"><label>${esc(x.label)}${x.required ? ' *' : ''}</label>
      <input id="w-${esc(x.name)}" type="${x.type === 'password' ? 'password' : 'text'}"
             placeholder="${esc(x.placeholder || '')}" ${x.dir === 'ltr' ? 'dir="ltr"' : ''}></div>`).join('') +
    `<button class="btn primary" id="w-save">אמת ושמור</button>`;
  $('w-save').onclick = async () => {
    const payload = { provider: S.wiz.provider.id, method: S.wiz.method.id, label: ($('w-label') || {}).value || '' };
    f.forEach((x) => { const el = $('w-' + x.name); if (el) payload[x.name] = el.value; });
    $('w-save').disabled = true; $('w-save').textContent = 'מאמת…';
    const r = await fetch('api/accounts', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload),
    });
    const j = await r.json().catch(() => ({}));
    if (r.ok && j.ok !== false) { binaTell('החשבון אומת ונשמר'); await loadAccounts(true); viewAccounts(); }
    else { binaTell(j.error || 'האימות נכשל', 'bad'); $('w-save').disabled = false; $('w-save').textContent = 'אמת ושמור'; }
  };
}

/* ── mirrors ─────────────────────────────────────────────────────────────────────────────────── */
async function loadMirrors() {
  const d = await jget('api/mirrors');
  S.mirrors = (d && d.mirrors) || [];
  return d || {};
}

async function viewMirrors() {
  $('main').innerHTML = `<div class="card"><div class="skel">טוען מראות…</div></div>`;
  await loadAccounts();
  const meta = await loadMirrors();
  if (meta.forge) FORGE_URL = meta.forge;
  renderNav();
  const rows = S.mirrors;
  const interval = meta.interval_seconds ? Math.round(meta.interval_seconds / 60) + ' דק׳' : '';
  $('main').innerHTML = `
    <div class="card">
      <header><span class="note">עותק של מאגר חיצוני בפורג'${interval ? ' · מסונכרן אוטומטית כל ' + esc(interval) : ''}</span>
        <a class="btn sm end" id="open-forge" href="${esc(FORGE_URL)}" target="_blank" rel="noopener">${ICO.ext} פתח את הפורג'</a></header>
      ${rows.map((m) => `
        <div class="item-row">
          ${ICO.branch}
          <div class="grow">
            <div class="ttl ltr">${esc(m.source_repo)}</div>
            <div class="sub">
              <span class="chip ${(MIRROR_HE[m.last_status] || ['', 'bad'])[1]}">${esc((MIRROR_HE[m.last_status] || [m.last_status || 'לא ידוע'])[0])}</span>
              <span class="ltr">עותק: ${esc(m.target_owner + '/' + m.target_repo)}</span>
              <span>מקור: ${esc(_acctLabel(m.source_account))}</span>
              <span>${esc([timeAgo(m.last_run), m.bytes ? bytes(m.bytes) : ''].filter(Boolean).join(' · '))}</span>
            </div>
            ${m.last_error ? `<div class="err">${esc(m.last_error)}</div>` : ''}
          </div>
          <div class="row">
            <a class="btn sm" href="${esc(m.browse_url)}" target="_blank" rel="noopener">${ICO.ext} פתח</a>
            <button class="btn sm" data-sync="${esc(m.id)}">${ICO.sync} סנכרן</button>
            <button class="btn sm danger" data-del="${esc(m.id)}">הסר</button>
          </div>
        </div>`).join('') || '<div class="empty">אין מראות עדיין.</div>'}
    </div>
    <div class="card">
      <header><h2>הצהרת מראה חדשה</h2></header>
      <div class="body">
        <div class="field"><label>חשבון מקור</label>
          <select id="m-acct">${S.accounts.filter((a) => a.provider !== 'forgejo')
            .map((a) => `<option value="${esc(a.id)}">${esc(a.label || a.login)} — ${esc(PROVIDER_HE[a.provider] || a.provider)}</option>`).join('')}</select></div>
        <div class="field"><label>מאגר (owner/repo)</label>
          <input id="m-repo" dir="ltr" placeholder="solomonBoltin/deployment-hacohen"></div>
        <div class="field check"><input type="checkbox" id="m-private" checked><label for="m-private">עותק פרטי בפורג'</label></div>
        <div class="row"><button class="btn primary" id="m-add">${ICO.plus} צור מראה</button>
          <span class="note">המאגר יימשך מהספק דרך ה-proxy של הלשכה — הטוקן לא נשמר בפורג'.</span></div>
      </div>
    </div>`;

  $('m-add').onclick = async () => {
    const acct = $('m-acct').value;
    const repo = $('m-repo').value.trim();
    if (!acct) { binaTell('אין חשבון מקור — חבר חשבון GitHub/GitLab.', 'bad'); return; }
    if (!repo.includes('/')) { binaTell('צורת המאגר: owner/repo', 'bad'); return; }
    $('m-add').disabled = true;
    const r = await fetch('api/mirrors', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ source_account: acct, repo, private: $('m-private').checked }),
    });
    const j = await r.json().catch(() => ({}));
    $('m-add').disabled = false;
    if (!r.ok || j.ok === false) { binaTell(j.error || 'יצירת המראה נכשלה', 'bad'); return; }
    binaTell('המראה נוצרה — הסנכרון רץ ברקע');
    viewMirrors();
  };
  $('main').querySelectorAll('[data-sync]').forEach((b) => {
    b.onclick = async () => {
      b.disabled = true; const busy = binaTell('מסנכרן…');
      const r = await fetch(`api/mirrors/${encodeURIComponent(b.dataset.sync)}/sync`, { method: 'POST' }).catch(() => null);
      const j = r ? await r.json().catch(() => ({})) : {};
      busy.remove(); b.disabled = false;
      // «הסנכרון הופעל» used to be said whatever came back - also when nothing did
      if (r && r.ok && j.ok !== false) binaTell('הסנכרון הופעל'); else binaTell(j.error || 'הפעלת הסנכרון נכשלה', 'bad');
    };
  });
  $('main').querySelectorAll('[data-del]').forEach((b) => {
    b.onclick = async () => {
      if (!await binaAsk({ title: 'להסיר את המראה?', body: "העותק בפורג' נשאר.", ok: 'הסרה', danger: true })) return;
      await fetch(`api/mirrors/${encodeURIComponent(b.dataset.del)}`, { method: 'DELETE' }).catch(() => null);
      viewMirrors();
    };
  });
}

/* ── router: two screens, and that is the whole app ──────────────────────────────────────────── */
/* The forge's browser-facing origin is NOT hardcoded here: /api/mirrors reports it (mirrors.public_base,
   which is the one place that knows whether the office is on localhost or a real domain), and this is
   only the fallback for the moment before that answer arrives. */
let FORGE_URL = 'http://forge.localhost:8080';

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, '');
  const [pathPart, queryPart] = raw.split('?');
  return { parts: pathPart.split('/').filter((x) => x !== '').map(decodeURIComponent),
           q: new URLSearchParams(queryPart || '') };
}

async function router() {
  const mirrors = parseHash().parts[0] === 'mirrors';
  const t = $('viewTitle');
  if (t) t.textContent = mirrors ? 'מראות' : 'חשבונות';
  document.title = mirrors ? 'ניהול גרסאות — מראות' : 'ניהול גרסאות — חשבונות';
  markRoute();
  return mirrors ? viewMirrors() : viewAccounts();
}

/* ── the menu: DECLARED, never hand-built ──────────────────────────────────────────────────────
 * The shell owns navigation (DGO-52/53). This app hands the shared component a DESCRIPTION of what
 * it has — its two screens, the mirrors it declares, the account it is acting as — and the component
 * builds every row, owns the breakpoints (full menu / rail / drawer) and remembers the rail the
 * owner chose. There is no menu markup in index.html and no row is built here; the five promises an
 * adopter makes are executed by `node platform-base/bina-ui/test_bina_nav.mjs`, and gate G27 keeps the
 * component byte-identical in every app that carries it. */
let NAV = null;

/** Which account the app is acting as — the brand's context line, as bina-ds has it. */
function brandSub() {
  const a = acctById(S.active) || S.accounts[0];
  if (!a) return 'אין חשבון מחובר';
  return (a.login || a.label) + ' · ' + (PROVIDER_HE[a.provider] || a.provider || '');
}
function openForge() { if (FORGE_URL) window.open(FORGE_URL, '_blank', 'noopener'); }
/** The one action this app always has: connect an account. It lands ON the wizard, not near it. */
function startConnect() {
  location.hash = '#/accounts';
  setTimeout(() => {
    const b = document.querySelector('#prov [data-p]');
    if (b) { b.scrollIntoView({ block: 'center' }); b.focus(); }
  }, 500);
}

function navSections() {
  const sections = [{
    id: 'screens',
    title: 'מסכים',
    items: [
      { id: 'accounts', label: 'חשבונות', icon: 'key', meta: String(S.accounts.length || '') },
      { id: 'mirrors', label: 'מראות', icon: 'repo', meta: String((S.mirrors || []).length || '') },
    ],
  }];
  /* The mirrors are this app's working objects, so they are rows — with the state the service
     reported, and a badge only when something is WRONG (a menu that decorates every row with a
     count nobody asked for is noise). */
  const rows = (S.mirrors || []).map((m) => ({
    id: 'mirror:' + m.id, label: m.source_repo, icon: 'git',
    meta: m.last_status === 'ok' ? 'מסונכרן' : (m.last_status || ''),
    badge: m.last_status === 'error' ? '!' : '',
  }));
  if (rows.length) sections.push({ id: 'mirrors', title: 'מראות', items: rows });
  return sections;
}

function markRoute() {
  if (NAV) NAV.setActive(parseHash().parts[0] === 'mirrors' ? 'mirrors' : 'accounts');
}

/** Mount (and re-mount when the data changes) — a remount is safe: the component reads the rail
 *  state out of localStorage at mount, so nothing the owner chose is lost by rebuilding the rows. */
let NAV_SIG = '';
function renderNav() {
  const el = $('sideNav');
  if (!el || typeof BinaNav === 'undefined') return null;
  /* Remounting closes an open drawer, so it happens only when the DECLARATION really changed — the
     second paint of the accounts screen (the probed states) must not slam a phone's menu shut. */
  const sig = JSON.stringify([brandSub(), navSections()]);
  if (NAV && sig === NAV_SIG) { renderTop(); markRoute(); return NAV; }
  NAV_SIG = sig;
  el.innerHTML = '';
  el.classList.remove('bnv');
  NAV = BinaNav.mount(el, {
    id: 'git',
    brand: { name: 'ניהול גרסאות', sub: brandSub(), avatar: 'ג' },
    primary: { label: 'חבר חשבון', icon: 'plus', onClick: startConnect },
    sections: navSections(),
    footer: { items: [{ id: 'forge', label: "פתח את הפורג'", icon: 'repo', onClick: openForge }] },
    onPick: (id) => {
      if (id === 'accounts') location.hash = '#/accounts';
      else if (id === 'mirrors' || String(id).indexOf('mirror:') === 0) location.hash = '#/mirrors';
    },
  });
  const t = $('navToggle');
  if (t && !t.innerHTML.trim()) t.innerHTML = BinaNav.svg('menu');
  markRoute();
  return NAV;
}

/* ── wiring ──────────────────────────────────────────────────────────────────────────────────── */
window.addEventListener('hashchange', router);

(async function boot() {
  renderNav();
  await loadAccounts();
  renderNav();
  await router();
})();
