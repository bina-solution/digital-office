/* «מסמכים» — SENDING A LINK (DGO-2169; the simulation ci-artifacts/dgo-2169/docs-2026.html, «שליחה»).

   A link was handed over in a card with «העתקה» first and WhatsApp last, opened on no number: the owner copied, went
   to WhatsApp, found the customer and pasted. The customers live in WhatsApp, so it comes first — to the customer's
   own number when the document holds one, the words ready — then the phone's own share sheet (any app), the mail,
   and the link to copy. On a phone it is a sheet from the bottom; on a wide screen a card. Nothing is sent by the
   office itself: each way opens the owner's own app with the message ready, and he sends it.

   window.SendSheet.open({ title, link, to, phone, email, subject, note, facts }) -> Promise (resolves when closed)
   Needs window.DocPanel.waLink; binaTell for the copy's answer when it is there. */
(function () {
  'use strict';
  const WA = '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true"><path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2Zm5.3 14.2c-.2.6-1.3 1.2-1.8 1.2-.5.1-1 .2-3.3-.7-2.8-1.1-4.6-4-4.7-4.2-.1-.2-1.1-1.5-1.1-2.9s.7-2.1 1-2.4c.3-.3.6-.3.8-.3h.6c.2 0 .4 0 .6.5l.9 2.1c.1.2.1.4 0 .6l-.4.6-.4.4c-.1.2-.3.3-.1.6.2.3.8 1.4 1.8 2.2 1.2 1.1 2.2 1.4 2.5 1.6.3.1.5.1.7-.1l.9-1.1c.2-.3.4-.2.7-.1l2 1c.3.1.5.2.6.3.1.2.1.8-.1 1.4Z"/></svg>';
  const SHARE = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/></svg>';
  const MAIL = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>';
  const COPY = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>';

  // its own escaper: app.js's `esc` is a top-level const — no property of window
  const e = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function open(o) {
    const words = (o.subject ? o.subject + '\n' : '') + o.link;
    const wa = DocPanel.waLink(o.phone, words);
    const toNumber = /^https:\/\/wa\.me\/\d/.test(wa);   // the number is said only when WhatsApp opens on it
    const canShare = typeof navigator.share === 'function';
    return new Promise(resolve => {
      const scrim = document.createElement('div');
      scrim.className = 'ss-scrim';
      scrim.innerHTML =
        `<div class="ss" role="dialog" aria-modal="true" aria-labelledby="ssT" dir="rtl" tabindex="-1">
          <div class="ss-grab" aria-hidden="true"></div>
          <h2 id="ssT">${e(o.title)}</h2>
          ${o.note ? `<p class="ss-note">${e(o.note)}</p>` : ''}
          ${o.facts && o.facts.length ? `<dl class="ss-facts">${o.facts.map(f => `<dt>${e(f[0])}</dt><dd dir="auto">${e(f[1])}</dd>`).join('')}</dl>` : ''}
          <div class="ss-opts">
            <a class="ss-opt ss-wa" data-s="wa" target="_blank" rel="noopener" href="${e(wa)}">
              <span class="ss-ic">${WA}</span><span><b>${o.to ? 'וואטסאפ ' + DocPanel.to('ל', o.to, e) : 'וואטסאפ'}</b>
              <span class="${toNumber ? 'num' : ''}">${toNumber ? e(o.phone) : 'בוחרים את השיחה בוואטסאפ'}</span></span></a>
            ${canShare ? `<button type="button" class="ss-opt" data-s="share"><span class="ss-ic">${SHARE}</span><span><b>שיתוף…</b><span>כל אפליקציה בטלפון</span></span></button>` : ''}
            <a class="ss-opt" data-s="mail" href="mailto:${encodeURIComponent(o.email || '')}?subject=${encodeURIComponent(o.subject || '')}&body=${encodeURIComponent(words)}">
              <span class="ss-ic">${MAIL}</span><span><b>מייל</b><span class="${o.email ? 'num' : ''}">${o.email ? e(o.email) : 'בוחרים את הנמען בתוכנת המייל'}</span></span></a>
            <button type="button" class="ss-opt" data-s="copy"><span class="ss-ic">${COPY}</span><span><b>העתקת הקישור</b><span>להדבקה בכל מקום</span></span></button>
          </div>
          <input class="ss-link num" readonly dir="ltr" value="${e(o.link)}" aria-label="הקישור"/>
          <div class="ss-foot"><a class="ghost sm btn" target="_blank" rel="noopener" href="${e(o.link)}">פתיחת הקישור</a>
            <button type="button" class="ghost sm" data-s="close">סגירה</button></div>
        </div>`;
      document.body.appendChild(scrim);
      const card = scrim.querySelector('.ss'), input = scrim.querySelector('.ss-link');
      const done = () => { document.removeEventListener('keydown', key, true); scrim.remove(); resolve(); };
      const key = ev => { if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); done(); } };
      document.addEventListener('keydown', key, true);
      scrim.addEventListener('mousedown', ev => { if (ev.target === scrim) done(); });
      input.addEventListener('focus', () => input.select());
      const tell = (t, k) => (window.binaTell ? window.binaTell(t, k) : null);
      scrim.querySelector('[data-s=close]').onclick = done;
      scrim.querySelector('[data-s=copy]').onclick = async () => {
        try { await navigator.clipboard.writeText(o.link); tell('הקישור הועתק'); done(); }
        catch (err) { input.focus(); input.select(); tell('ההעתקה נחסמה — הקישור מסומן, העתיקו אותו', 'warn'); }
      };
      const sh = scrim.querySelector('[data-s=share]');
      if (sh) sh.onclick = async () => {
        try { await navigator.share({ title: o.subject || o.title, text: o.subject || '', url: o.link }); done(); }
        catch (err) { /* the owner closed the phone's sheet: this one stays */ }
      };
      // WhatsApp and the mail open the owner's own app — and the sheet stays: when the app did not open (no mail
      // client, no WhatsApp on this computer) the link is still here to copy (the reader: it closed, and a lost link
      // can only be minted again, which kills the one sent)
      requestAnimationFrame(() => scrim.classList.add('on'));
      card.focus();
    });
  }

  window.SendSheet = { open };
})();
