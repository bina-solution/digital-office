/* «ישויות» — the screen (DGO-2101). Everyone the business works with, people and organizations, and the roles each
 * holds. The vocabulary (kinds, roles, their fields) is the server's (GET api/patterns): this file draws it.
 * Routes, kept in the app's own address (G83): ROOT (all) · ROOT r/<role> · ROOT e/<id> (one entity's card). */
/* what a failed request is called when the service sent no sentence of its own — the office's words (G27) */
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
(function () {
  'use strict';
  const ROOT = window.ENT_ROOT || '/';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const ICON = {
    organization: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 21h18M5 21V5l7-2v18M19 21V9l-7-2"/></svg>',
    person: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/></svg>',
  };
  let P = null, ALL = [], role = '', q = '', openId = '';

  async function api(method, path, body) {
    const r = await fetch(ROOT + 'api/' + path, {
      method, credentials: 'same-origin',
      headers: body !== undefined ? { 'content-type': 'application/json' } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }).catch(binaNoAnswer);
    let data = {};
    try { data = await r.json(); } catch (e) { data = {}; }
    if (!r.ok) throw new Error(data.detail || binaSaid(r.status));
    return data;
  }
  // a notice in the page; with `undo`, a way back on it for a while (a role taken off comes back with its fields)
  function toast(t, undo) {
    const el = $('toast');
    el.innerHTML = esc(t) + (undo ? ' <button class="btn sm" type="button" id="toast-undo">ביטול</button>' : '');
    el.hidden = false;
    if (undo) $('toast-undo').onclick = () => { el.hidden = true; undo(); };
    clearTimeout(toast.t); toast.t = setTimeout(() => { el.hidden = true; }, undo ? 9000 : 2600);
  }
  const roleName = (r) => (P.roles[r] || {}).he || r;
  const roleChip = (r) => `<span class="role r-${esc(r)}">${esc(roleName(r))}</span>`;

  // ── the address is the state ─────────────────────────────────────────────────────────────────────
  function readRoute() {
    const rest = location.pathname.slice(ROOT.length);
    const m = /^(r|e)\/([^/]+)/.exec(rest);
    role = m && m[1] === 'r' ? decodeURIComponent(m[2]) : (m && m[1] === 'e' ? role : '');
    openId = m && m[1] === 'e' ? decodeURIComponent(m[2]) : '';
  }
  function go(next, replace) {
    history[replace ? 'replaceState' : 'pushState'](null, '', ROOT + next);
    readRoute(); render();
  }
  window.addEventListener('popstate', () => { readRoute(); render(); });

  // ── the list ─────────────────────────────────────────────────────────────────────────────────────
  async function load() {
    try { ALL = (await api('GET', 'entities')).entities; } catch (e) { ALL = []; toast(e.message); }
  }
  function counts() {
    const c = { '': ALL.length };
    Object.keys(P.roles).forEach((r) => { c[r] = ALL.filter((e) => e.roles.includes(r)).length; });
    return c;
  }
  function render() {
    if (role && !P.roles[role]) role = '';                    // a link to a role this office does not know: all
    const c = counts();
    $('title').textContent = role ? 'ישויות · ' + P.roles[role].plural_he : 'ישויות';
    $('chips').innerHTML = [['', 'הכל'], ...Object.entries(P.roles).map(([k, v]) => [k, v.plural_he])]
      .map(([k, lab]) => `<button class="chip" type="button" data-role="${esc(k)}" aria-pressed="${role === k}">${esc(lab)} · ${c[k] || 0}</button>`).join('');
    $('chips').querySelectorAll('[data-role]').forEach((b) => { b.onclick = () => go(b.dataset.role ? 'r/' + b.dataset.role : ''); });
    const ql = q.trim().toLowerCase();
    const rows = ALL.filter((e) => (!role || e.roles.includes(role)) &&
      (!ql || [e.name, e.key, e.phone, e.email].join(' ').toLowerCase().includes(ql)));
    $('list').innerHTML = `<div class="row head" role="presentation"><span></span><span>שם</span><span>תפקידים</span><span>מזהה וטלפון</span></div>` +
      (rows.length ? rows.map((e) => `<button class="row" type="button" role="listitem" data-id="${esc(e.id)}">
        <span class="kind" title="${esc(P.kinds[e.kind].he)}">${ICON[e.kind]}</span>
        <span style="min-width:0"><span class="name">${esc(e.name)}</span><span class="sub">${esc(P.kinds[e.kind].he)}</span></span>
        <span class="roles c-roles">${e.roles.map(roleChip).join('')}</span>
        <span class="c-key" style="min-width:0"><span class="sub ltr">${esc(e.key)}</span><span class="sub ltr">${esc(e.phone)}</span></span></button>`).join('')
      : `<div class="pg-empty" style="padding:22px">${ALL.length ? 'אין ישות שמתאימה. אפשר להוסיף: «+ ישות חדשה».'
          : 'עוד אין כאן אף ישות. מוסיפים את הראשונה ב«+ ישות חדשה»: לקוח, ספק, חברה, איש מכירות או איש קשר.'}</div>`);
    $('list').querySelectorAll('[data-id]').forEach((b) => { b.onclick = () => go('e/' + encodeURIComponent(b.dataset.id)); });
    if (openId) openCard(openId); else $('layer').innerHTML = '';
  }

  // ── one entity's card ────────────────────────────────────────────────────────────────────────────
  function fieldInputs(defs, values, prefix) {
    return defs.map((f) => {
      const id = prefix + f.key, v = values[f.key] || '';
      const input = f.choices
        ? `<select id="${id}" data-k="${esc(f.key)}"><option value=""></option>${f.choices.map((c) => `<option ${c === v ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select>`
        : f.key === 'notes'                                   // notes run long: read whole, not cut at one line
          ? `<textarea id="${id}" data-k="${esc(f.key)}" rows="3" dir="auto">${esc(v)}</textarea>`
          : `<input id="${id}" data-k="${esc(f.key)}" value="${esc(v)}" dir="auto">`;
      return `<label for="${id}">${esc(f.he)}</label>${input}`;
    }).join('');
  }
  const collect = (box) => { const o = {}; box.querySelectorAll('[data-k]').forEach((i) => { o[i.dataset.k] = i.value.trim(); }); return o; };

  async function openCard(id) {
    let e, party;
    try { [e, party] = await Promise.all([api('GET', 'entities/' + encodeURIComponent(id)), api('GET', 'entities/' + encodeURIComponent(id) + '/party')]); }
    catch (err) { toast(err.message); go(role ? 'r/' + role : '', true); return; }
    if (openId !== id) return;
    const free = Object.entries(P.roles).filter(([k, v]) => !e.roles[k] && v.kinds.includes(e.kind));
    const people = e.relations.filter((r) => r.kind === 'works_at');
    const orgs = ALL.filter((x) => x.kind === 'organization' && x.id !== e.id);
    $('layer').innerHTML = `<div class="scrim" data-close></div>
      <aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="d-t">
        <div class="d-head"><span class="kind">${ICON[e.kind]}</span><div style="min-width:0">
          <h2 id="d-t">${esc(e.name)}</h2>
          <div class="roles" style="margin-top:6px">${Object.keys(e.roles).map(roleChip).join('')}
            ${free.map(([k, v]) => `<button class="role r-${esc(k)}" type="button" data-add="${esc(k)}" style="cursor:pointer;opacity:.7">+ ${esc(v.he)}</button>`).join('')}</div></div>
          <button class="x" type="button" data-close aria-label="סגירה">×</button></div>
        <div class="d-body">
          <section class="sec" id="sec-self"><h3>פרטים<button class="btn sm end" type="button" data-save="self">שמירה</button></h3>
            <div class="kv"><label for="f-kind">סוג</label><select id="f-kind">${Object.entries(P.kinds).map(([k, v]) => `<option value="${esc(k)}"${k === e.kind ? ' selected' : ''}>${esc(v.he)}</option>`).join('')}</select><label for="f-name">שם</label><input id="f-name" value="${esc(e.name)}" dir="auto">${fieldInputs(P.entity_fields, e.fields, 'f-')}</div></section>
          ${Object.entries(e.roles).map(([r, vals]) => `<section class="sec" data-role-sec="${esc(r)}">
            <h3>${roleChip(r)}<button class="btn sm end" type="button" data-save="${esc(r)}">שמירה</button>
              <button class="btn sm danger" type="button" data-drop="${esc(r)}">הסרה</button></h3>
            <div class="kv">${fieldInputs(P.roles[r].fields, vals, 'r-' + r + '-')}</div></section>`).join('')}
          <section class="sec"><h3>${e.kind === 'organization' ? 'אנשים בארגון' : 'קשרים'}</h3>
            ${e.relations.length ? e.relations.map((r) => `<div class="rel">${ICON[r.other.kind] || ''}<span>${esc(r.other.name)}${r.title ? ' · ' + esc(r.title) : ''}</span>
              <span class="sub">${esc((P.relations[r.kind] || {}).he || r.kind)}</span>
              <button class="btn sm end" type="button" data-unrel="${esc(r.id)}">הסרה</button></div>`).join('') : '<div class="sub">אין עדיין קשרים.</div>'}
            ${e.kind === 'person' && orgs.length ? `<div class="kv" style="margin-top:8px"><label for="rel-org">עובד/ת ב</label>
              <select id="rel-org"><option value=""></option>${orgs.map((o) => `<option value="${esc(o.id)}">${esc(o.name)}</option>`).join('')}</select>
              <label for="rel-title">תפקיד</label><input id="rel-title" dir="auto"></div>
              <div class="foot"><button class="btn sm" type="button" id="rel-add">הוספת קשר</button></div>` : ''}
            ${e.kind === 'organization' && !people.length ? '<div class="pg-note">אדם שעובד כאן מתקשר מהכרטיס שלו: «עובד/ת ב».</div>' : ''}</section>
          <section class="sec"><h3>כך המסמכים מדפיסים אותו</h3>
            <div class="party"><b>${esc(party.name)}</b>${party.company_id ? `<br><span class="ltr" style="display:inline-block">${esc(party.company_id)}</span>` : ''}
              ${[party.street, party.city].filter(Boolean).length ? '<br>' + esc([party.street, party.city].filter(Boolean).join(', ')) : ''}
              ${party.phone || party.email ? '<br>' + esc([party.phone, party.email].filter(Boolean).join(' · ')) : ''}
              ${party.contact_person ? '<br>לידי ' + esc(party.contact_person) + (party.contact_title ? ', ' + esc(party.contact_title) : '') : ''}</div>
            <div class="sub" style="white-space:normal;margin-top:6px">«מסמכים» לוקחת את זה מכאן לפי מזהה. מסמך שהונפק שומר את הפרטים מיום ההנפקה.</div></section>
          <section class="sec"><h3>מה השתנה</h3><div id="hist" class="sub" style="white-space:normal">…</div></section>
          <div class="foot"><button class="btn sm danger" type="button" id="archive">${e.archived ? 'החזרה מהארכיון' : 'העברה לארכיון'}</button></div>
        </div></aside>`;
    wireCard(e);
    api('GET', 'events?entity=' + encodeURIComponent(e.id)).then((d) => {
      const box = $('hist'); if (!box) return;
      box.innerHTML = d.events.length ? d.events.slice(0, 12).map((v) => `<div class="ev">${esc(new Date(v.at * 1000).toLocaleString('he-IL'))} · ${esc(v.summary)}${v.actor ? ` · <bdi>${esc(v.actor)}</bdi>` : ''}${changed(v)}</div>`).join('') : 'אין עדיין שינויים.';
    }).catch(() => {});
  }
  // what a change was, field by field: «before ← after»; a role taken off keeps what it held
  function changed(v) {
    const d = v.detail || {}, lines = [];
    const lab = (k, defs) => (k === 'name' ? 'שם' : k === 'kind' ? 'סוג' : ((defs || []).find((f) => f.key === k) || {}).he || k);
    // a kind is stored as its value (person / organization), and said in words
    const say = (k, s) => (k === 'kind' && P.kinds[s] ? P.kinds[s].he : s) || '—';
    const pair = (k, x, defs) => `${esc(lab(k, defs))}: <bdi>${esc(say(k, x[0]))}</bdi> ← <bdi>${esc(say(k, x[1]))}</bdi>`;
    if (v.kind === 'updated') Object.entries(d).forEach(([k, x]) => { if (Array.isArray(x)) lines.push(pair(k, x, P.entity_fields)); });
    if (v.kind === 'role') Object.entries(d).forEach(([r, obj]) => {
      if (r === 'removed') Object.entries(obj || {}).forEach(([rr, f]) => Object.entries(f || {}).forEach(([k, val]) =>
        lines.push(`${esc(lab(k, (P.roles[rr] || {}).fields))}: <bdi>${esc(val)}</bdi>`)));
      else if (P.roles[r]) Object.entries(obj || {}).forEach(([k, x]) => { if (Array.isArray(x)) lines.push(pair(k, x, P.roles[r].fields)); });
    });
    return lines.length ? `<div class="ev-d">${lines.join('<br>')}</div>` : '';
  }
  function wireCard(e) {
    const L = $('layer');
    const close = () => go(role ? 'r/' + role : '');
    L.querySelectorAll('[data-close]').forEach((b) => { b.onclick = close; });
    const act = async (fn, msg, refused) => { try { await fn(); await load(); toast(msg); render(); } catch (err) { toast(err.message); if (refused) refused(); } };
    L.querySelectorAll('[data-add]').forEach((b) => { b.onclick = () => act(() => api('PUT', `entities/${e.id}/roles/${b.dataset.add}`, { fields: {} }), `נוסף התפקיד «${roleName(b.dataset.add)}»`); });
    L.querySelectorAll('[data-drop]').forEach((b) => {
      b.onclick = async () => {                               // off at once, and back with one click (its fields too)
        const r = b.dataset.drop, kept = e.roles[r] || {};
        try { await api('DELETE', `entities/${e.id}/roles/${r}`); await load(); render(); }
        catch (err) { toast(err.message); return; }
        toast(`התפקיד «${roleName(r)}» הוסר`, () => act(() => api('PUT', `entities/${e.id}/roles/${r}`, { fields: kept }), `התפקיד «${roleName(r)}» הוחזר`));
      };
    });
    L.querySelectorAll('[data-save]').forEach((b) => {
      b.onclick = () => {
        const r = b.dataset.save;
        if (r === 'self') {
          // a kind the store refused goes back to the stored one: left as chosen, every later save of «פרטים» would
          // carry it again and be refused whole (the second reader, DGO-2101); what was typed elsewhere stays
          const kind = $('f-kind').value;
          return act(() => api('PATCH', `entities/${e.id}`, { name: $('f-name').value, fields: collect($('sec-self')), ...(kind !== e.kind ? { kind } : {}) }),
            'נשמר', () => { if (kind !== e.kind) $('f-kind').value = e.kind; });
        }
        return act(() => api('PUT', `entities/${e.id}/roles/${r}`, { fields: collect(L.querySelector(`[data-role-sec="${r}"]`)) }), 'נשמר');
      };
    });
    L.querySelectorAll('[data-unrel]').forEach((b) => { b.onclick = () => act(() => api('DELETE', 'relations/' + b.dataset.unrel), 'הקשר הוסר'); });
    const add = $('rel-add');
    if (add) add.onclick = () => { const to = $('rel-org').value; if (!to) return toast('בחרו ארגון');
      act(() => api('POST', 'relations', { from: e.id, to, kind: 'works_at', title: $('rel-title').value }), 'הקשר נוסף'); };
    $('archive').onclick = () => act(() => api('POST', `entities/${e.id}/archive`, { archived: !e.archived }), e.archived ? 'הוחזר' : 'הועבר לארכיון');
    const x = L.querySelector('.x'); if (x) x.focus();
  }

  // ── a new entity ─────────────────────────────────────────────────────────────────────────────────
  function newEntity() {
    let kind = 'organization', first = 'customer';
    const draw = () => {
      const roles = Object.entries(P.roles).filter(([, v]) => v.kinds.includes(kind));
      if (!roles.some(([k]) => k === first)) first = roles[0][0];
      $('layer').innerHTML = `<div class="scrim" data-close></div><div class="modal" role="dialog" aria-modal="true" aria-labelledby="m-t"><div class="card">
        <h2 id="m-t">ישות חדשה</h2><div class="sub" style="white-space:normal">אדם או ארגון, ותפקיד ראשון. תמיד אפשר להוסיף תפקידים בכרטיס.</div>
        <div class="picks">${Object.entries(P.kinds).map(([k, v]) => `<button class="pick" type="button" data-kind="${k}" aria-pressed="${kind === k}"><b>${esc(v.he)}</b></button>`).join('')}</div>
        <div class="chips">${roles.map(([k, v]) => `<button class="chip" type="button" data-first="${k}" aria-pressed="${first === k}">${esc(v.he)}</button>`).join('')}</div>
        <div class="field"><label for="n-name">שם</label><input id="n-name" dir="auto" required></div>
        <div class="kv" id="n-self">${fieldInputs(P.entity_fields.filter((f) => ['phone', 'email', 'street', 'city'].includes(f.key)), {}, 'n-')}</div>
        <div class="kv" id="n-role" style="margin-top:10px">${fieldInputs(P.roles[first].fields, {}, 'nr-')}</div>
        <div class="err" id="n-err" hidden></div>
        <div class="foot"><button class="btn" type="button" data-close>ביטול</button><button class="btn primary" type="button" id="n-save">הוספה</button></div>
      </div></div>`;
      const L = $('layer');
      L.querySelectorAll('[data-close]').forEach((b) => { b.onclick = () => { L.innerHTML = ''; }; });
      L.querySelectorAll('[data-kind]').forEach((b) => { b.onclick = () => { kind = b.dataset.kind; draw(); }; });
      L.querySelectorAll('[data-first]').forEach((b) => { b.onclick = () => { first = b.dataset.first; draw(); }; });
      $('n-save').onclick = async () => {
        try {
          const e = await api('POST', 'entities', { kind, name: $('n-name').value, fields: collect($('n-self')),
            roles: { [first]: collect($('n-role')) } });
          await load(); toast(`«${e.name}» נוסף/ה`); go('e/' + encodeURIComponent(e.id));
        } catch (err) { const box = $('n-err'); box.textContent = err.message; box.hidden = false; }
      };
      $('n-name').focus();
    };
    draw();
  }

  $('q').oninput = (ev) => { q = ev.target.value; render(); };
  $('new').onclick = newEntity;
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape' && openId) go(role ? 'r/' + role : ''); });
  (async () => {
    try { P = await api('GET', 'patterns'); } catch (e) { $('list').innerHTML = `<div class="pg-empty" style="padding:22px">${esc(e.message)}</div>`; return; }
    readRoute(); await load(); render();
  })();
})();
