/* The map (#/) — the business's digital assets as a MAP: the basics first (identity), then the
 * blueprint per business type, then the gallery's folders. Pictures, not paragraphs. Uses app.js's
 * helpers at call time; declares only window.pageMap. */
(function () {
  'use strict';
  const FACTS = [
    ['identity.name.brand-he', 'שם העסק'], ['identity.description.short', 'תיאור קצר', 'wide'],
    ['identity.description.long', 'תיאור מלא', 'wide'], ['identity.contact.phone', 'טלפון'],
    ['identity.contact.email', 'אימייל'], ['identity.contact.address', 'כתובת'], ['identity.contact.website-url', 'אתר'],
  ];
  async function pageMap() {
    header('נכסים דיגיטליים', 'המפה של העסק: הבסיס, התבנית לפי סוג העסק, והגלריה.',
      `<a class="btn sm primary" href="#/gallery">${ic('image')}לגלריה</a>`);
    const [ids, bps, gal] = await Promise.all([api('api/slots?section=identity'), api('api/blueprints'), api('api/gallery')]);
    const slots = (ids.ok && ids.body.slots) || [];
    S.slotCache.identity = slots;
    const by = Object.fromEntries(slots.map((s) => [s.key, s]));
    const act = (k) => by[k] && by[k].active;
    const logoKey = ['identity.logo.square', 'identity.logo.primary'].find((k) => act(k) && act(k).thumb) || (by['identity.logo.primary'] ? 'identity.logo.primary' : 'identity.logo.square');
    const lg = act(logoKey);
    const fact = ([k, label, cls]) => {
      const a = act(k);
      const txt = a && (a.text || a.title);
      return `<button class="gx-fact ${cls || ''} ${txt ? '' : 'empty'}" onclick="openSlot('${esc(k)}')"><span class="k">${esc(label)}</span>
        <span class="v" dir="auto">${txt ? esc(txt) : 'חסר — הוספה'}</span></button>`;
    };
    const colors = ['identity.color.primary', 'identity.color.secondary', 'identity.color.neutral'].map((k) => act(k) && act(k).text).filter(Boolean);
    let html = `<section class="gx-sec" aria-labelledby="gx-h1"><h2 id="gx-h1">${ic('id')}הבסיס — זהות העסק</h2>
      <div class="gx-id"><button class="gx-logo" onclick="${lg ? `openSlot('${esc(logoKey)}')` : by[logoKey] ? `gxPickFor('${esc(logoKey)}','logos')` : `go('/blueprints')`}" aria-label="לוגו">
        ${lg ? `<img alt="הלוגו הפעיל" src="${esc(lg.thumb)}">` : `<span class="gx-ph">${gxIcon('award')}<b>אין עדיין לוגו</b><span>${by[logoKey] ? 'בחירה מהגלריה' : 'קודם בוחרים תבנית'}</span></span>`}</button>
        <div class="gx-facts">${FACTS.map(fact).join('')}
          <button class="gx-fact" onclick="openSlot('identity.color.primary')"><span class="k">צבעים</span>
            ${colors.length ? `<span class="gx-sw">${colors.map((c) => `<span style="background:${esc(c)}" title="${esc(c)}"></span>`).join('')}</span>` : '<span class="v">חסר — הוספה</span>'}</button>
        </div></div>
      ${slots.length ? '' : `<div class="note" style="margin-top:8px">המשבצות של הזהות נוצרות מתבנית — בחרו את סוג העסק למטה.</div>`}</section>`;
    const pend = (S.ov && S.ov.pending) || [];
    if (pend.length) html += `<section class="gx-sec"><h2>${ic('check')}ממתין לך</h2><div class="card">${pendingList(pend)}</div></section>`;
    const list = (bps.ok && bps.body.blueprints) || [];
    html += `<section class="gx-sec" aria-labelledby="gx-h2"><h2 id="gx-h2">${ic('layers')}תבנית לפי סוג העסק<a class="btn sm ghost gx-more" href="#/blueprints">כל התבניות</a></h2>
      <div class="gx-bps">${list.filter((b) => !/^content-/.test(b.id)).map((b) => `<a class="gx-bp ${b.applied ? 'on' : ''}" href="#/blueprints?bp=${encodeURIComponent(b.id)}">
        ${ic(b.applied ? 'check' : 'layers')}<span><span class="t">${esc(lbl(b.name))}</span><br><span class="s">${b.applied ? 'בשימוש · ' : ''}${one((b.counts || {}).slots || 0, 'משבצת אחת', 'משבצות')}</span></span></a>`).join('')}</div></section>`;
    html += `<section class="gx-sec" aria-labelledby="gx-h3"><h2 id="gx-h3">${gxIcon('folder')}הגלריה<a class="btn sm ghost gx-more" href="#/gallery">פתיחה</a></h2><div id="gx-mapgal"></div></section>`;
    $('view').innerHTML = html;
    if (pend.length) bindPendingActions();
    const box = $('gx-mapgal');
    if (!gal.ok || !gal.body.drive.ok) { box.innerHTML = gxState('bad', 'off', 'הגלריה לא זמינה כרגע', gal.ok ? gal.body.drive.reason : errText(gal.body)); return; }
    if (!gal.body.exists) { box.innerHTML = gxState('', 'folder', 'לגלריה עוד אין תיקיות', 'פתחו את הגלריה כדי ליצור אותן ב«קבצים».'); return; }
    box.innerHTML = `<div class="gx-grid">${gal.body.folders.map((f) => `<a class="gx-tile" href="#/gallery?f=${encodeURIComponent(f.id)}" style="text-decoration:none">
      <span class="gx-pic">${f.covers[0] ? gxPic(f.covers[0], 320) : `<span class="gx-kind">${gxIcon('folder')}ריקה</span>`}</span>
      <span class="gx-cap"><span class="nm">${esc(f.name)}</span><span class="gx-tag">${num(f.count)}</span></span></a>`).join('')}</div>`;
    gxDrawModels(box);
  }
  window.pageMap = pageMap;
})();
