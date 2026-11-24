/* «מסמכים» — «חתימות»: EVERY LINK THE OFFICE SENT, IN ONE PLACE (DGO-2169, step 4; the simulation
   ci-artifacts/dgo-2169/signatures-sim.html). The owner: «זה לא אמור להיות אפלקציה נפרדת זה הכל פיצר מובנה של מסמכים».

   A link to sign, to fill and sign («מילוי וחתימה»), or to look — each a row: what (the document, or the file that
   went out on its own), to whom, its state, when. A link of a document opens that document, whose drawer holds its
   links and their acts; a file's link opens a card with its own (the signed copy, a new link, close it). Chips say
   how many wait for a signature; one search; a phone's card, as the documents list. «חתימה על קובץ» sends a PDF of
   the office's own to be signed — what esign's separate screen did before its tile left the home.

   window.SigList.mount(host, opts) · .set(rows) · .loading() · .failed(retry)
   opts: { esc, when(ts) -> «22/11/2026 14:05», openDoc(id), openLink(row) } */
(function () {
  'use strict';
  const KIND = { sign: 'לחתימה', fill: 'מילוי וחתימה', view: 'לצפייה' };
  const STATE = { sent: 'נשלח', opened: 'נפתח', signing: 'נחתם עכשיו', signed: 'נחתם', closed: 'נסגר', expired: 'פג תוקף' };
  const CHIP = { sent: 'issued', opened: 'sent', signing: 'sent', signed: 'paid', closed: 'cancelled', expired: 'cancelled' };   // the app's chip colours
  const waits = r => r.kind !== 'view' && (r.state === 'sent' || r.state === 'opened' || r.state === 'signing');
  // A ROW IS A DOCUMENT'S WHEN IT HAS A REF — a ref is only ever a ledger id — and the document opens; its title is
  // the document's when the ledger named it, else the link's own name. Decided by the title, a «מילוי וחתימה» row of
  // a document older than the ledger's newest 500 reached a file's card and its envelope acts (the reader)
  const isDoc = r => !!r.ref;
  const FILTERS = [
    ['all', 'הכל', () => true],
    ['wait', 'ממתינים לחתימה', waits],
    ['signed', 'נחתמו', r => r.state === 'signed'],
    ['view', 'לצפייה', r => r.kind === 'view' && (r.state === 'sent' || r.state === 'opened')],
    ['closed', 'סגורים', r => r.state === 'closed' || r.state === 'expired'],
  ];
  const S = { host: null, o: null, rows: null, more: false, filter: 'all', q: '' };
  const norm = s => String(s == null ? '' : s).toLowerCase().replace(/[֑-ׇ"'״׳.,\s-]/g, '');

  function frame() {
    S.host.innerHTML =
      '<div class="lst-tools"><label class="lst-search"><span class="lst-mag" aria-hidden="true"></span>' +
      '<input type="search" placeholder="חיפוש לפי מסמך, קובץ או מי שחותם" autocomplete="off" aria-label="חיפוש קישורים"/></label>' +
      '<button type="button" class="primary sm sig-new">חתימה על קובץ</button></div>' +
      '<div class="lst-chips" role="toolbar" aria-label="סינון לפי מצב"></div>' +
      '<p class="lst-count muted" aria-live="polite"></p><div class="lst-rows"></div>';
    const input = S.host.querySelector('.lst-search input');
    input.value = S.q;
    let t = null;
    input.oninput = () => { clearTimeout(t); t = setTimeout(() => { S.q = input.value; draw(); }, 120); };
    S.host.querySelector('.sig-new').onclick = () => S.o.signAFile();
    S.host.querySelector('.lst-rows').addEventListener('click', e => {
      const a = e.target.closest('a.lst-row');
      if (!a || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      const r = S.rows[+a.dataset.i];
      if (r && isDoc(r)) S.o.openDoc(r.ref); else if (r) S.o.openLink(r);
    });
  }

  function chips() {
    const box = S.host.querySelector('.lst-chips');
    const had = box.contains(document.activeElement) && document.activeElement.dataset.f;
    box.innerHTML = FILTERS.map(([k, label, f]) =>
      `<button type="button" class="lst-chip" data-f="${k}" aria-pressed="${S.filter === k}">${label}` +
      `<span class="lst-c num">${S.rows ? S.rows.filter(f).length : ''}</span></button>`).join('');
    box.querySelectorAll('[data-f]').forEach(b => b.onclick = () => { S.filter = b.dataset.f; draw(); });
    if (had) { const b = box.querySelector(`[data-f="${had}"]`); if (b) b.focus(); }
  }

  function row(r, i) {
    const e = S.o.esc, title = r.doc || r.name || '—';
    const href = isDoc(r) ? 'doc/' + encodeURIComponent(r.ref) : 'signatures';
    const of = r.kind === 'fill' && r.parties ? ' · ' + r.signed + ' מתוך ' + r.parties : '';
    return `<a class="lst-row" href="${href}" data-i="${i}">` +
      `<span class="lst-t"><b>${e(title)}</b><span class="lst-when">${isDoc(r) ? 'מסמך' : 'קובץ'} · ${e(KIND[r.kind] || r.kind)}${e(of)}</span></span>` +
      `<span class="lst-cust">${e(r.who || '—')}</span>` +
      `<span class="lst-amt num">${e(S.o.when(r.created_at).split(' ')[0])}</span>` +
      `<span class="chip ${CHIP[r.state] || ''} lst-st">${e(STATE[r.state] || r.state)}</span></a>`;
  }

  function draw() {
    if (!S.host || !S.rows) return;
    chips();
    const f = (FILTERS.find(x => x[0] === S.filter) || FILTERS[0])[2], q = norm(S.q);
    const shown = S.rows.map((r, i) => [r, i]).filter(([r]) => f(r) && (!q || norm([r.doc, r.name, r.who].join(' ')).includes(q)));
    const n = shown.length;
    // a reading full to its limit holds the newest only: said, so a count never reads as all there is (the reader)
    S.host.querySelector('.lst-count').textContent = !S.rows.length ? ''
      : (n === 1 ? 'קישור אחד' : n + ' קישורים') + (S.more ? ' — האחרונים בלבד' : '');
    const box = S.host.querySelector('.lst-rows');
    if (!S.rows.length) {
      box.innerHTML = '<div class="lst-empty">עוד לא נשלח קישור.<br>«חתימה על קובץ» שולחת קובץ לחתימה; מסמך נשלח לחתימה מהמסמך עצמו.</div>';
      return;
    }
    box.innerHTML = n ? shown.map(([r, i]) => row(r, i)).join('')
      : `<div class="lst-empty">אין כאן קישורים${S.q.trim() ? ' שמתאימים ל«' + S.o.esc(S.q.trim()) + '»' : ''}.</div>`;
  }

  window.SigList = {
    mount(host, opts) {
      S.o = opts;
      if (S.host === host && host.querySelector('.lst-rows')) return;
      S.host = host;
      frame();
    },
    loading() {
      if (!S.host || S.rows) return;
      S.host.querySelector('.lst-rows').innerHTML = '<div class="lst-sk" aria-label="טוען">' + '<div></div>'.repeat(5) + '</div>';
    },
    failed(retry, message) {
      if (!S.host) return;
      const box = S.host.querySelector('.lst-rows');
      box.innerHTML = `<div class="lst-empty">${S.o.esc(message || 'הרשימה לא נטענה.')} <button type="button" class="ghost sm">נסו שוב</button></div>`;
      box.querySelector('button').onclick = retry;
    },
    set(rows, more) { S.rows = rows || []; S.more = !!more; draw(); },
    STATE, KIND,
  };
})();
