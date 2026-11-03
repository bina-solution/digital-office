/* The gallery (#/gallery) — ONE visual library, its files in «קבצים» under /נכסים דיגיטליים/<folder>,
 * read through this app's own proxy (gallery.py). Shows the thing itself, opens it large, and puts an
 * item into a slot as a new version. Uses app.js's helpers ($, esc, api, ic, header, go, S, lbl,
 * FILE_KINDS, binaTell) at call time only — this file loads first and declares nothing global but
 * window.pageGallery / window.gxIcon / window.gxPic / window.gxPickFor. */
(function () {
  'use strict';
  const P = {
    folder: 'M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z',
    pen: 'M12 19l7-7 3 3-7 7-3-3zM18 13l-1.5-7.5L2 2l3.5 14.5L13 18l5-5zM2 2l7.6 7.6M11 11a2 2 0 1 0 0-4 2 2 0 0 0 0 4',
    box: 'M21 16V8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4a2 2 0 0 0 1-1.7zM3.3 7 12 12l8.7-5M12 22V12',
    file: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M16 13H8M16 17H8',
    code: 'M16 18l6-6-6-6M8 6l-6 6 6 6',
    phone: 'M7 2h10a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zM12 18h.01',
    star: 'M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z',
    award: 'M12 15a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM8.2 13.9 7 23l5-3 5 3-1.2-9.1',
    image: 'M3 5h18v14H3zM8.5 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3M21 15l-5-5L5 19',
    next: 'M15 18l-6-6 6-6', prev: 'M9 18l6-6-6-6', x: 'M18 6 6 18M6 6l12 12',
    off: 'M22.6 17A5 5 0 0 0 18 10h-1.3a8 8 0 0 0-7-6M5 5a8 8 0 0 0 4 15h9a5 5 0 0 0 1.7-.3M1 1l22 22',
    ext: 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3',
    slot: 'M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z',
  };
  const gi = (n) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${P[n] || P.file}"/></svg>`;
  const FICON = { logos: 'award', designs: 'pen', mockups: 'phone', images: 'image', icons: 'star', '3d': 'box', pdf: 'file', html: 'code' };
  const KIND = { image: 'תמונה', svg: 'SVG', pdf: 'PDF', html: 'HTML', model: 'תלת־ממד', video: 'וידאו', file: 'קובץ' };
  const G = { meta: null, folder: '', items: [], at: -1, back: null };
  const u = (id, what) => `api/gallery/file/${encodeURIComponent(id)}/${what}`;

  function stateBox(cls, icon, title, why, action) {
    return `<div class="gx-state ${cls || ''}" role="status">${gi(icon)}<b>${esc(title)}</b>
      <div class="why">${esc(why || '')}</div>${action || ''}</div>`;
  }
  // the picture of an item — the thing itself, never a name in a box
  function pic(it, size) {
    const s = size || 480;
    if (it.kind === 'svg') return `<img loading="lazy" alt="${esc(it.name)}" src="${u(it.id, 'content')}">`;  /* drive has no picture of an SVG: it IS one */
    if (it.kind === 'image' || it.kind === 'pdf') {
      const fb = it.kind === 'pdf' ? `this.replaceWith(Object.assign(document.createElement('span'),{className:'gx-kind',innerHTML:window.gxIcon('file')+'PDF'}))`
        : `this.onerror=null;this.src='${u(it.id, 'content')}'`;
      return `<img loading="lazy" alt="${esc(it.name)}" src="${u(it.id, 'thumb')}?s=${s}" onerror="${fb}">`;
    }
    if (it.kind === 'html') return `<iframe sandbox="" loading="lazy" tabindex="-1" aria-hidden="true" title="${esc(it.name)}" src="${u(it.id, 'content')}"></iframe>`;
    if (it.kind === 'model' && it.ext === 'stl') return `<span class="gx-kind" data-model="${esc(it.id)}">${gi('box')}${KIND.model}</span>`;
    return `<span class="gx-kind">${gi(it.kind === 'model' ? 'box' : 'file')}${esc(KIND[it.kind] || it.ext.toUpperCase())}</span>`;
  }
  async function drawModels(root) {
    for (const el of root.querySelectorAll('[data-model]')) {
      const r = await api(u(el.dataset.model, 'model'));
      if (!r.ok) continue;
      const b = r.body;
      el.outerHTML = `<svg class="gx-3d" viewBox="-2 -2 ${b.w + 4} ${b.h + 4}" role="img" aria-label="מודל תלת־ממד">${b.polys.map((p) =>
        `<path d="M${p[0]} ${p[1]}L${p[2]} ${p[3]}L${p[4]} ${p[5]}Z" fill-opacity="${p[6]}"/>`).join('')}</svg>`;
    }
  }

  async function pageGallery() {
    const q = S.query || {};
    header('גלריה', 'כל מה שהעסק נראה בו — לוגו, עיצובים, הדמיות, מודלים ו‑PDF. הקבצים עצמם שמורים ב«קבצים».',
      `<button class="btn sm ghost" id="gx-refresh" title="טעינה מחדש">${ic('refresh')}רענון</button>`);
    $('gx-refresh').onclick = () => route();
    const view = $('view');
    const r = await api('api/gallery');
    if (!r.ok) { view.innerHTML = stateBox('bad', 'off', 'הגלריה לא נטענה', errText(r.body)); return; }
    G.meta = r.body;
    if (!r.body.drive.ok) {
      view.innerHTML = stateBox('bad', 'off', 'הגלריה לא זמינה כרגע', `${r.body.drive.reason}. הגלריה שמורה שם, ולכן אין מה להציג עד שהוא חוזר — שאר הנכסים הדיגיטליים עובדים כרגיל.`,
        `<button class="gx-ib" id="gx-retry">${ic('refresh')}לנסות שוב</button>`);
      $('gx-retry').onclick = () => route();
      return;
    }
    if (!r.body.exists) {
      view.innerHTML = stateBox('', 'folder', 'לגלריה עוד אין תיקיות', `התיקיות נוצרות ב«קבצים» תחת ${r.body.root}: ${r.body.folders.map((f) => f.name).join(' · ')}.`,
        `<button class="gx-ib primary" id="gx-setup">${gi('folder')}יצירת התיקיות</button>`);
      $('gx-setup').onclick = async (e) => {
        const s = await busy(e.currentTarget, () => post('api/gallery/setup'));
        if (!s.ok) { binaTell(errText(s.body), 'bad'); return; }
        binaTell('התיקיות נוצרו ב«קבצים»'); route();
      };
      return;
    }
    const fs = r.body.folders;
    const cur = fs.find((f) => f.id === q.f) || fs.find((f) => f.count) || fs[0];
    G.folder = cur.id;
    const pickFor = q.pick ? ((S.slotCache.identity || []).find((s) => s.key === q.pick) || { key: q.pick }) : null;
    view.innerHTML = `${pickFor ? `<div class="gx-pickbar" role="status">${gi('slot')}<b>בוחרים פריט עבור «${esc(lbl(pickFor.label) || pickFor.key)}» — לחצו על פריט ואז «שיבוץ כאן», והוא יהפוך לגרסה הפעילה</b>
        <button class="gx-ib" id="gx-unpick">ביטול</button></div>` : ''}
      <div class="gx-folders" role="toolbar" aria-label="תיקיות הגלריה">${fs.map((f) => `<button class="gx-folder" data-f="${esc(f.id)}" aria-pressed="${f.id === cur.id}">
        ${gi(FICON[f.id])}<span>${esc(f.name)}</span><span class="n">${num(f.count)}</span></button>`).join('')}</div>
      <div id="gx-body"><div class="skel"></div></div>`;
    view.querySelectorAll('.gx-folder').forEach((b) => { b.onclick = () => withQuery({ f: b.dataset.f }); });
    if ($('gx-unpick')) $('gx-unpick').onclick = () => { location.hash = q.back || '/gallery'; };  /* back to where the pick began */
    const fr = await api(`api/gallery/folder/${encodeURIComponent(cur.id)}`);
    const body = $('gx-body');
    if (!body) return;
    if (!fr.ok || !fr.body.drive.ok) { body.innerHTML = stateBox('bad', 'off', 'התיקייה לא נקראה', fr.ok ? fr.body.drive.reason : errText(fr.body)); return; }
    G.items = fr.body.items;
    if (!G.items.length) {
      body.innerHTML = stateBox('', FICON[cur.id], `התיקייה «${cur.name}» ריקה`, `מה שנשמר ב«קבצים» בתיקייה ${cur.path} מופיע כאן מיד.`);
      return;
    }
    body.innerHTML = `<div class="gx-grid">${G.items.map((it, i) => `<button class="gx-tile" data-i="${i}" title="${esc(it.name)}">
      <span class="gx-pic">${pic(it)}</span><span class="gx-cap"><span class="nm" dir="auto">${esc(it.name.replace(/\.[^.]+$/, ''))}</span>
      <span class="gx-tag">${esc(KIND[it.kind] || it.ext)}</span></span></button>`).join('')}</div>`;
    body.querySelectorAll('.gx-tile').forEach((b) => { b.onclick = () => openLB(Number(b.dataset.i), b); });
    drawModels(body);
    if (q.open) { const i = G.items.findIndex((x) => x.id === q.open); if (i >= 0) openLB(i); }
  }

  /* ── the large view ─────────────────────────────────────────────────────────────────────── */
  function stage(it) {
    if (it.kind === 'image' || it.kind === 'svg') return `<img alt="${esc(it.name)}" src="${u(it.id, 'content')}">`;
    if (it.kind === 'pdf') return `<img alt="${esc(it.name)}" src="${u(it.id, 'thumb')}?s=1400" onerror="this.outerHTML='<iframe title=&quot;PDF&quot; src=&quot;${u(it.id, 'content')}&quot;></iframe>'">`;
    if (it.kind === 'html') return `<iframe sandbox="" title="${esc(it.name)}" src="${u(it.id, 'content')}"></iframe>`;
    return pic(it, 1400);
  }
  function lbHTML() {
    const it = G.items[G.at];
    const pickFor = (S.query || {}).pick;
    return `<div class="gx-lb" role="dialog" aria-modal="true" aria-label="${esc(it.name)}">
      <div class="gx-lb-top"><span class="ttl" dir="auto" title="${esc(it.name)}">${esc(it.name.replace(/\.[^.]+$/, ''))}</span><span class="gx-tag">${esc(KIND[it.kind] || it.ext)}</span>
        <button class="gx-ib" id="gx-close" aria-label="סגירה" title="סגירה (Esc)">${gi('x')}</button></div>
      <div class="gx-lb-stage" id="gx-stage">${stage(it)}</div>
      <div class="gx-lb-foot">
        <button class="gx-ib" id="gx-prev" aria-label="הקודם" ${G.at ? '' : 'disabled'}>${gi('prev')}</button>
        <span class="note" style="font-variant-numeric:tabular-nums">${num(G.at + 1)} / ${num(G.items.length)}</span>
        <button class="gx-ib" id="gx-next" aria-label="הבא" ${G.at < G.items.length - 1 ? '' : 'disabled'}>${gi('next')}</button>
        <span class="sp"></span>
        <a class="gx-ib" href="${u(it.id, 'content')}" target="_blank" rel="noopener">${gi('ext')}פתיחה בלשונית</a>
        <button class="gx-ib primary" id="gx-pick">${gi('slot')}${pickFor ? 'שיבוץ כאן' : 'שיבוץ במשבצת'}</button>
      </div></div>`;
  }
  function openLB(i, from) {
    G.at = i;
    if (from) G.back = from;
    let root = $('gx-lb-root');
    if (!root) { root = document.createElement('div'); root.id = 'gx-lb-root'; document.body.appendChild(root); }
    root.innerHTML = lbHTML();
    drawModels(root);
    $('gx-close').onclick = closeLB;
    $('gx-prev').onclick = () => openLB(G.at - 1);
    $('gx-next').onclick = () => openLB(G.at + 1);
    $('gx-pick').onclick = () => { const k = (S.query || {}).pick; k ? doPick(k, null, true) : chooseSlot(); };
    $('gx-close').focus();
  }
  function closeLB() {
    const root = $('gx-lb-root');
    if (root) root.innerHTML = '';
    G.at = -1;
    if (G.back && document.contains(G.back)) G.back.focus();
  }
  document.addEventListener('keydown', (e) => {
    if (G.at < 0 || !$('gx-lb-root') || !$('gx-lb-root').innerHTML) return;
    if (e.key === 'Escape') { e.stopPropagation(); closeLB(); }
    else if (e.key === 'ArrowLeft' && G.at < G.items.length - 1) openLB(G.at + 1);
    else if (e.key === 'ArrowRight' && G.at > 0) openLB(G.at - 1);
  }, true);

  async function chooseSlot() {
    const st = $('gx-stage');
    st.innerHTML = '<div class="skel" style="width:100%"></div>';
    const lists = await Promise.all(['identity', 'content', 'media'].map((s) => api(`api/slots?section=${s}`)));
    const slots = lists.filter((r) => r.ok).flatMap((r) => r.body.slots || []).filter((s) => FILE_KINDS.has(s.kind));
    if (!slots.length) {
      st.innerHTML = stateBox('', 'slot', 'אין עדיין משבצות לקבצים', 'משבצות נוצרות מתבנית לפי סוג העסק (בעמוד «תבניות»).', `<a class="gx-ib primary" href="#/blueprints">${ic('layers')}לתבניות</a>`);
      return;
    }
    st.innerHTML = `<div style="width:min(100%,560px)"><b>לאיזו משבצת להוסיף את הפריט?</b> <span class="note">הוא נוסף כגרסה — הפעילה לא משתנה.</span>
      <div class="gx-pick">${slots.map((s) => `<button data-k="${esc(s.key)}">${esc(lbl(s.label) || s.key)}<span class="s" dir="ltr">${esc(s.key)}</span></button>`).join('')}</div></div>`;
    st.querySelectorAll('[data-k]').forEach((b) => { b.onclick = () => doPick(b.dataset.k, b); });
  }
  /* activate = the pick began at a slot («בחירה מהגלריה»): the item becomes that slot's active
   * version and the slot opens where the pick began, at its publish plan — the same as «הוספה
   * והפיכה לפעילה». Without it (from the gallery itself) the item is only added as a version. */
  async function doPick(key, btn, activate) {
    const it = G.items[G.at];
    const b = btn || $('gx-pick');
    const q = S.query || {};
    await busy(b, async () => {
      const res = await fetch(u(it.id, 'content')).catch(() => null);
      if (!res || !res.ok) { binaTell('הקובץ לא נקרא מ«קבצים»', 'bad'); return; }
      const fd = new FormData();
      fd.append('file', new File([await res.blob()], it.name, { type: it.mime || res.headers.get('content-type') || 'application/octet-stream' }));
      fd.append('title', it.name.replace(/\.[^.]+$/, ''));
      if (activate) fd.append('activate', '1');
      const r = await api(`api/slots/${encodeURIComponent(key)}/assets`, { method: 'POST', body: fd });
      if (!r.ok) { binaTell(errText(r.body), 'bad'); return; }
      closeLB();
      S.slotCache = {};
      S.ov = null;  /* the menu's counts follow on the next route */
      if (activate) {
        binaTell('שובץ — זו עכשיו הגרסה הפעילה. זו תכנית הפרסום');
        go(String(q.back || '/').split('?')[0] || '/', { slot: key, plan: r.body.asset.id });
      } else {
        binaTell('הפריט נוסף כגרסה במשבצת — בחרו בה אם להפוך אותו לפעיל');
        go('/', { slot: key });
      }
    });
  }
  /* the one way into a pick: from a slot's drawer or the map's empty logo; `back` is where it began */
  function pickFor(key, folder) {
    go('/gallery', { pick: key, f: folder || null, back: location.hash.replace(/^#/, '') || '/' });
  }

  /* ── TINY WINDOW = WIDGET: one item at a time, or the logo ────────────────────────────── */
  const T = { items: [], at: 0 };
  async function tinyFill() {
    let host = $('gx-tiny');
    if (!host) { host = document.createElement('div'); host.id = 'gx-tiny'; document.body.appendChild(host); }
    if (!T.items.length) {
      const r = await api('api/gallery').catch(() => null);
      T.items = (r && r.ok && r.body.drive.ok) ? r.body.folders.flatMap((f) => f.covers) : [];
    }
    if (!T.items.length) {
      const r = await api('api/slots?section=identity');
      const by = Object.fromEntries(((r.ok && r.body.slots) || []).map((s) => [s.key, s]));
      const lg = ['identity.logo.square', 'identity.logo.primary'].map((k) => by[k] && by[k].active).find((a) => a && a.thumb);
      const nm = ['identity.name.brand-he', 'identity.name.brand-en'].map((k) => by[k] && by[k].active).find(Boolean);
      host.innerHTML = `<div class="st">${lg ? `<img alt="לוגו" src="${esc(lg.thumb)}">` : stateBox('', 'award', 'אין עדיין לוגו', '')}</div>
        <div class="bar"><span class="nm">${esc(nm ? nm.text : 'נכסים דיגיטליים')}</span></div>`;
      return;
    }
    const it = T.items[T.at % T.items.length];
    host.innerHTML = `<div class="st" id="gx-t-open" title="${esc(it.name)}">${it.kind === 'html' || it.kind === 'model' ? pic(it, 600) : stage(it)}</div>
      <div class="bar"><button class="gx-ib" id="gx-t-prev" aria-label="הקודם">${gi('prev')}</button>
        <span class="nm" dir="auto">${esc(it.name.replace(/\.[^.]+$/, ''))}</span><span class="ct">${num(T.at % T.items.length + 1)}/${num(T.items.length)}</span>
        <button class="gx-ib" id="gx-t-next" aria-label="הבא">${gi('next')}</button></div>`;
    drawModels(host);
    $('gx-t-prev').onclick = () => { T.at = (T.at - 1 + T.items.length) % T.items.length; tinyFill(); };
    $('gx-t-next').onclick = () => { T.at = (T.at + 1) % T.items.length; tinyFill(); };
    $('gx-t-open').onclick = () => binaTiny.say({ open: '#/gallery?f=' + it.folder + '&open=' + it.id });
    binaTiny.say({ title: it.name });
  }
  window.addEventListener('DOMContentLoaded', () => {
    if (window.binaTiny) window.binaTiny((t) => { if (t) tinyFill(); });
  });

  window.pageGallery = pageGallery;
  window.gxPickFor = pickFor;
  window.gxIcon = gi;
  window.gxPic = pic;
  window.gxState = stateBox;
  window.gxDrawModels = drawModels;
})();
