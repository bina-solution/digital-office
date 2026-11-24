/* «מסמכים» — THE DOCUMENTS LIST (DGO-2169, the owner: «אני לוחץ על פריט ולא ברור מה קורה … לא מערכת של 2026»).
   The simulation is ci-artifacts/dgo-2169/docs-2026.html; the audit behind it is research_notes/DGO-2169 documents app
   2026-11-22/code-audit.md (C: «what a row click does»).

   It was a spreadsheet: a click focused a cell (a blue outline, a range on drag), the row opened only if the focus came
   within 0.4 s of the pointer, the same cell twice did nothing, and a phone got two of six columns. A list of documents
   is not a sheet — nothing in it is edited in place (an issued document never is). So each document is a LINK to its
   own address, `doc/<id>`: a click, a tap and Enter open it in the drawer at once; a middle-click or ⌘-click opens it
   in a tab of its own, as any link does; the one the drawer shows is marked. Chips filter by state and say how many
   each holds; one search matches the customer, the number, the type and the sum. On a phone each row is a card.

   window.DocList.mount(host, opts) · .set(docs) · .loading() · .failed(retry) · .mark(id)
   opts: { esc, money, typeHe, statusHe, dateOf(d) -> «22/11/2026», sortOf(d) -> number, open(id) } */
(function () {
  'use strict';
  const FILTERS = [
    ['all', 'הכל', () => true],
    ['draft', 'טיוטות', d => d.status === 'draft'],
    ['open', 'פתוחים', d => d.status === 'issued' || d.status === 'sent'],
    ['paid', 'שולמו', d => d.status === 'paid'],
    ['cancelled', 'בוטלו', d => d.status === 'cancelled'],
  ];
  const PAGE = 100;                                 // rows drawn at once: «עוד» draws the next hundred
  const S = { host: null, o: null, docs: null, filter: 'all', q: '', shown: PAGE, current: null };

  const norm = s => String(s == null ? '' : s).toLowerCase().replace(/[֑-ׇ"'״׳.,\s-]/g, '');
  function matches(d, q) {
    if (!q) return true;
    const o = S.o;
    return norm([d.customer_name, d.doc_number, o.typeHe(d.doc_type), d.total, d.total != null ? o.money(d.total) : '',
                 o.dateOf(d)].join(' ')).includes(q);
  }

  function frame() {
    S.host.innerHTML =
      '<div class="lst-tools"><label class="lst-search"><span class="lst-mag" aria-hidden="true"></span>' +
      '<input type="search" placeholder="חיפוש לפי לקוח, מספר או סכום" autocomplete="off" aria-label="חיפוש מסמכים"/></label>' +
      '<button type="button" class="ghost sm lst-export" title="הרשימה כפי שהיא מסוננת, כקובץ לאקסל">ייצוא</button></div>' +
      '<div class="lst-chips" role="toolbar" aria-label="סינון לפי מצב"></div>' +
      // the rows are links and keep a link's role; what a reader hears on each search is the one count line
      '<p class="lst-count muted" aria-live="polite"></p><div class="lst-rows"></div>';
    const input = S.host.querySelector('.lst-search input');
    input.value = S.q;
    let t = null;
    input.oninput = () => { clearTimeout(t); t = setTimeout(() => { S.q = input.value; S.shown = PAGE; draw(); }, 120); };
    S.host.querySelector('.lst-export').onclick = exportCsv;
    // ONE listener for every row: a plain click or Enter opens the drawer; a click with a key held, or the middle
    // button, is left to the browser — the row is a real link, and that opens it in a tab of its own
    S.host.querySelector('.lst-rows').addEventListener('click', e => {
      const more = e.target.closest('[data-more]');
      if (more) { e.preventDefault(); S.shown += PAGE; draw(); return; }
      const a = e.target.closest('a.lst-row');
      if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      S.o.open(a.dataset.id);
    });
  }

  function chips() {
    const box = S.host.querySelector('.lst-chips');
    const had = box.contains(document.activeElement) && document.activeElement.dataset.f;   // the keyboard's chip
    box.innerHTML = FILTERS.map(([k, label, f]) =>
      `<button type="button" class="lst-chip" data-f="${k}" aria-pressed="${S.filter === k}">${label}` +
      `<span class="lst-c num">${S.docs ? S.docs.filter(f).length : ''}</span></button>`).join('');
    box.querySelectorAll('[data-f]').forEach(b => b.onclick = () => { S.filter = b.dataset.f; S.shown = PAGE; draw(); });
    if (had) { const b = box.querySelector(`[data-f="${had}"]`); if (b) b.focus(); }   // redrawn, it keeps its place
  }

  function row(d) {
    const o = S.o, e = o.esc, st = d.status || '';
    const name = o.typeHe(d.doc_type) || d.doc_type || 'מסמך';
    return `<a class="lst-row" href="doc/${encodeURIComponent(d.id)}" data-id="${e(d.id)}"` +
      ` aria-current="${S.current === d.id}">` +
      `<span class="lst-t"><b>${e(name)}${d.doc_number ? ` <span class="num">${e(d.doc_number)}</span>` : ''}</b>` +
      `<span class="lst-when num">${e(o.dateOf(d))}</span></span>` +
      `<span class="lst-cust">${e(d.customer_name || '—')}</span>` +
      `<span class="lst-amt num">${d.total != null ? '₪' + e(o.money(d.total)) : ''}</span>` +
      `<span class="chip ${e(st)} lst-st">${e(o.statusHe(st) || st)}</span></a>`;
  }

  /** The rows the chips and the search show now — what is drawn, and what «ייצוא» writes. */
  function current() {
    const f = (FILTERS.find(x => x[0] === S.filter) || FILTERS[0])[2], q = norm(S.q);
    return S.docs.filter(f).filter(d => matches(d, q));
  }

  /** «ייצוא»: the list as it is filtered, as a file Excel opens in Hebrew (UTF-8 with its mark). The spreadsheet that
   *  was here had it, and the list must not lose it (DGO-2169). A cell that begins like a formula is written as text:
   *  a customer's name is never run by the program that opens it. */
  function exportCsv() {
    if (!S.docs) return;
    const o = S.o;
    const cell = v => {
      let s = String(v == null ? '' : v);
      if (/^[=+\-@\t\r]/.test(s) && !/^-?\d+(\.\d+)?$/.test(s)) s = "'" + s;   // (a negative sum stays a number)
      return '"' + s.replace(/"/g, '""') + '"';
    };
    const head = ['סוג', 'מספר', 'לקוח', 'סכום', 'מצב', 'תאריך'];
    const rows = current().map(d => [o.typeHe(d.doc_type) || d.doc_type, d.doc_number || '', d.customer_name || '',
                                     d.total != null ? Number(d.total).toFixed(2) : '', o.statusHe(d.status) || d.status, o.dateOf(d)]);
    const csv = String.fromCharCode(0xFEFF) + [head].concat(rows).map(r => r.map(cell).join(',')).join('\r\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    a.download = 'מסמכים.csv';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function draw() {
    if (!S.host || !S.docs) return;
    chips();
    const list = current();
    const box = S.host.querySelector('.lst-rows');
    const n = list.length;
    S.host.querySelector('.lst-count').textContent = !S.docs.length ? '' : n === 1 ? 'מסמך אחד' : n + ' מסמכים';
    if (!S.docs.length) {
      box.innerHTML = '<div class="lst-empty">אין מסמכים עדיין.<br>«מסמך חדש» יוצר את הראשון.</div>';
      return;
    }
    if (!list.length) {
      box.innerHTML = `<div class="lst-empty">אין כאן מסמכים${S.q.trim() ? ' שמתאימים ל«' + S.o.esc(S.q.trim()) + '»' : ''}.</div>`;
      return;
    }
    const left = list.length - S.shown;
    box.innerHTML = list.slice(0, S.shown).map(row).join('') +
      (left > 0 ? `<button type="button" class="lst-more" data-more="1">עוד <span class="num">${Math.min(left, PAGE)}</span>` +
                  ` מתוך <span class="num">${left}</span></button>` : '');
  }

  window.DocList = {
    mount(host, opts) {
      if (S.host === host && host.querySelector('.lst-rows')) return;
      S.host = host; S.o = opts;
      frame();
    },
    loading() {
      if (!S.host || S.docs) return;              // a refresh keeps what is shown until the new list is here
      S.host.querySelector('.lst-rows').innerHTML =
        '<div class="lst-sk" aria-label="טוען">' + '<div></div>'.repeat(6) + '</div>';
    },
    failed(retry) {
      if (!S.host || S.docs) return;              // the list shown stays; the corner notice says the rest
      const box = S.host.querySelector('.lst-rows');
      box.innerHTML = '<div class="lst-empty">הרשימה לא נטענה. <button type="button" class="ghost sm">נסו שוב</button></div>';
      box.querySelector('button').onclick = retry;
    },
    set(docs) {
      const o = S.o;
      S.docs = docs.slice().sort((a, b) => (o.sortOf(b) - o.sortOf(a)) || String(b.created_at || '').localeCompare(String(a.created_at || '')));
      draw();
    },
    mark(id) {
      S.current = id || null;
      if (!S.host) return;
      S.host.querySelectorAll('a.lst-row').forEach(a => a.setAttribute('aria-current', String(a.dataset.id === S.current)));
    },
  };
})();
