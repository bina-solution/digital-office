/* «מסמכים» — WHAT A DOCUMENT SAYS WHEN IT IS OPENED (DGO-2169; the simulation ci-artifacts/dgo-2169/docs-2026.html).

   The drawer showed up to ten buttons of one weight (six «המשך: …» on a proposal) and left the owner to work out
   which one was next. Now it says where the document stands and the one step that comes next — «נשלח למילוי וחתימה
   אתמול; חתמו 1 מתוך 2», «כל הצדדים חתמו; השלב הבא: חשבונית מס» — with that step as the main button; every other
   act stays one row below it. Under it, what happened to the document, in order: made, issued, sent, opened,
   signed, paid — the ledger's trail and the links' own times in one line of time.

   Pure: each function takes what the drawer already read and gives HTML; nothing here asks the network.
   window.DocPanel.next(d, ctx) -> { html, acts: [act keys it shows] }
   window.DocPanel.timeline(events, links, ctx) -> html
   ctx: { esc, typeHe, when(ts) -> «22/11/2026 14:05», detail(text), eventHe, now: Date,
          env (the one-signer envelope, or null), fill (the «מילוי וחתימה» events, newest first, or null),
          links (the document's links, or null while they load), conversions, mayIssue(type), isCredit(d),
          signable, books } */
(function () {
  'use strict';
  const BILL = ['INVOICE', 'PAYMENT_REQUEST'];        // what a signed deal is billed with, in this order of preference
  // the types whose Hebrew name is feminine — «הצעת מחיר הופקה», «הסכם שירות הופק». A person's is never guessed: a
  // sentence about the signer says what the LINK did («הקישור נפתח»), not what he or she did
  const FEM = new Set(['PROPOSAL', 'QUOTE', 'WORK_ORDER', 'ORDER', 'SHIPMENT', 'INVOICE', 'INVOICE_RECEIPT', 'RECEIPT',
                       'CREDIT_NOTE', 'STATEMENT']);
  const g = (type, m, f) => (FEM.has(type) ? f : m);
  const naive = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;
  const ms = ts => { const s = String(ts || '').trim(), t = Date.parse(naive.test(s) ? s.replace(' ', 'T') + 'Z' : s); return isNaN(t) ? 0 : t; };

  /** «היום ב־14:05», «אתמול ב־09:12», «לפני 3 ימים» — in Israel, as when() says it; '' when there is no time */
  function ago(ts, ctx) {
    const w = ctx.when(ts);                            // «22/11/2026 14:05»
    if (!w) return '';
    const [dmy, hm] = w.split(' '), [dd, mm, yy] = dmy.split('/').map(Number);
    const today = ctx.when(ctx.now.toISOString()).split(' ')[0].split('/').map(Number);
    const days = Math.round((Date.UTC(today[2], today[1] - 1, today[0]) - Date.UTC(yy, mm - 1, dd)) / 864e5);
    if (days <= 0) return 'היום ב־' + hm;
    if (days === 1) return 'אתמול ב־' + hm;
    if (days === 2) return 'שלשום';
    if (days < 8) return 'לפני ' + days + ' ימים';
    return 'ב־' + dmy;
  }
  const at = (ts, ctx) => { const a = ago(ts, ctx); return a ? ' ' + a : ''; };

  /** «ל» / «מ» before a name: «לקבוצת אורן», «ל־ACME» before a Latin one, and «ללקוח» / «מהלקוח» with no name */
  function to(pfx, name, e) {
    const n = String(name || '').trim();
    if (!n) return pfx === 'מ' ? 'מהלקוח' : 'ללקוח';
    return pfx + (/^[A-Za-z0-9"'(]/.test(n) ? '־' : '') + e(n);
  }

  function button(ctx, act, label, kind) {
    return `<button type="button" class="${kind} sm" data-act="${ctx.esc(act)}">${label}</button>`;
  }

  /** The document's state in one sentence, and the step that comes next as its main act. */
  function next(d, ctx) {
    const e = ctx.esc, type = d.doc_type, cust = d.customer_name;
    const name = e(ctx.typeHe(type) || 'המסמך'), env = ctx.env, live = !['draft', 'cancelled'].includes(d.status);
    const conv = (ctx.conversions && ctx.conversions[type]) || [];
    const may = t => conv.includes(t) && ctx.mayIssue(t);
    const bill = BILL.find(may);                       // only what this type converts into, and this business issues
    const cont = t => ['convert:' + t, 'המשך: ' + e(ctx.typeHe(t)), 'primary'];   // a new DRAFT of t, said as such
    const fill = (ctx.fill || []).filter(f => f.status !== 'cancelled');
    const f0 = fill[0];                                // the newest «מילוי וחתימה» link
    // the view links still open — one closed or past its date sent nothing that stands (the reader)
    const views = (ctx.links || []).filter(l => l.kind === 'view' && ['sent', 'opened'].includes(l.state))
      .sort((a, b) => ms(b.created_at) - ms(a.created_at));
    let say = '', acts = [];
    if (d.status === 'cancelled') {
      say = 'המסמך בוטל. הוא נשמר כפי שהיה, ואינו נשלח עוד.';
    } else if (d.status === 'draft') {
      if (ctx.signable.has(type)) {
        say = 'טיוטה. כשהיא מוכנה — מפיקים אותה ושולחים ' + to('ל', cust, e) + ' לחתימה. אחרי ההפקה היא אינה נערכת עוד.';
        acts = [['issuefill', 'הפקה ושליחה לחתימה', 'primary'], ['edit', 'עריכה', 'ghost']];
      } else {
        say = 'טיוטה. בהפקה היא מקבלת מספר, ואחריה אינה נערכת עוד.';
        acts = [['issue', 'הפקה', 'primary'], ['edit', 'עריכה', 'ghost']];
      }
    } else if (ctx.signable.has(type)) {
      if (f0 && (f0.status === 'complete' || f0.status === 'completing')) {
        const last = (f0.parties || []).map(p => p.signed_at).filter(Boolean).sort((a, b) => ms(b) - ms(a))[0];
        say = 'כל הצדדים חתמו' + at(last, ctx) + '.' + (bill ? ' השלב הבא: ' + e(ctx.typeHe(bill)) + ' עם אותן שורות.' : '') +
              (f0.status === 'completing' ? ' העותק החתום מופק עכשיו.' : '');
        acts = bill ? [cont(bill)] : [];
      } else if (f0) {
        const parties = f0.parties || [], n = parties.filter(p => p.state === 'signed').length;
        say = 'נשלח למילוי וחתימה' + at(f0.created_at, ctx) + '. ' +
              (n ? 'חתמו ' + n + ' מתוך ' + parties.length + '.' : 'עוד אף צד לא חתם.') +
              ' המצב של כל צד והקישור — תחת «מילוי וחתימה».';
      } else if (env && env.status === 'signed') {
        say = 'החתימה התקבלה' + at(env.signed_at, ctx) + ' ' + to('מ', env.signer_name || cust, e) + '.' +
              (bill ? ' השלב הבא: ' + e(ctx.typeHe(bill)) + ' עם אותן שורות.' : '');
        acts = (bill ? [cont(bill)] : []).concat([['signed:' + env.id, 'העותק החתום', bill ? 'ghost' : 'primary']]);
      } else if (env && env.status === 'opened') {
        say = 'הקישור לחתימה נפתח' + at(env.opened_at || env.created_at, ctx) + ', והחתימה עוד לא התקבלה.';
      } else if (env && env.status === 'sent') {
        say = 'הקישור לחתימה נשלח' + at(env.created_at, ctx) + ' ועוד לא נפתח.';
      } else if (d.status === 'sent') {
        say = name + ' ' + g(type, 'נשלח', 'נשלחה') + ' ' + to('ל', cust, e) + '. לחתימה — שולחים קישור «מילוי וחתימה».';
        acts = [['fill', 'מילוי וחתימה', 'ghost']];
      } else {
        say = name + ' ' + g(type, 'הופק', 'הופקה') + '. השלב הבא: לשלוח ' + to('ל', cust, e) + ' לחתימה.';
        acts = [['fill', 'שליחה לחתימה', 'primary'], ['share', 'קישור לצפייה', 'ghost']];
      }
    } else if (ctx.isCredit(d)) {
      say = 'חשבונית זיכוי היא התיקון עצמו: היא אינה מבוטלת ואינה משולמת. שולחים אותה ' + to('ל', cust, e) + '.';
      acts = [['share', 'שליחה ' + to('ל', cust, e), 'primary']];
    } else if (type === 'INVOICE' || type === 'PAYMENT_REQUEST') {
      if (d.status === 'paid') {
        say = 'התשלום התקבל.' + (may('RECEIPT') ? ' השלב הבא: קבלה עליו.' : ' אין כאן עוד מה לעשות.');
        acts = may('RECEIPT') ? [cont('RECEIPT')] : [['share', 'שליחת עותק', 'ghost']];
      } else if (d.status === 'sent' || views.length) {
        // sent — by the ledger's mark, or by a view link: the step is the payment, never «send» again
        say = (views.length ? 'נשלח קישור לצפייה' + at(views[0].created_at, ctx) + ' ' + to('ל', views[0].signer_name || cust, e)
                            : name + ' ' + g(type, 'נשלח', 'נשלחה') + ' ' + to('ל', cust, e)) + '. כשהתשלום מתקבל — מסמנים.';
        acts = [['pay', 'סימון כשולם', 'primary'], ['share', 'קישור נוסף', 'ghost']];
      } else {
        say = name + ' ' + g(type, 'הופק', 'הופקה') + '. השלב הבא: לשלוח ' + to('ל', cust, e) + '.';
        acts = [['share', 'שליחה ' + to('ל', cust, e), 'primary'], ['pay', 'סימון כשולם', 'ghost']];
      }
    } else if (type === 'SHIPMENT' && bill) {
      say = 'תעודת המשלוח הופקה. השלב הבא: ' + e(ctx.typeHe(bill)) + '.';
      acts = [cont(bill), ['share', 'שליחה ' + to('ל', cust, e), 'ghost']];
    } else if (live) {
      if (views.length) {
        say = 'נשלח קישור לצפייה' + at(views[0].created_at, ctx) + ' ' + to('ל', views[0].signer_name || cust, e) + '.';
        acts = [['share', 'קישור נוסף', 'ghost']];
      } else {
        say = name + ' ' + g(type, 'הופק', 'הופקה') + '. שולחים ' + g(type, 'אותו', 'אותה') + ' ' + to('ל', cust, e) + '.';
        acts = [['share', 'שליחה ' + to('ל', cust, e), 'primary']];
      }
    }
    const html = say ? `<div class="dp-next" role="status"><p>${say}</p>` +
      (acts.length ? `<div class="dp-acts">${acts.map(([a, l, k]) => button(ctx, a, l, k)).join('')}</div>` : '') + '</div>' : '';
    return { html, acts: acts.map(a => a[0]) };
  }

  /** What happened to the document, oldest first: the ledger's trail and each link's sent / opened / signed. A send
   *  the ledger recorded for a link that is listed is said once — by the link, which knows its own times. */
  function timeline(events, links, ctx) {
    const e = ctx.esc, rows = [], ids = new Set((links || []).map(l => String(l.id)));
    (events || []).forEach(ev => {
      const tail = String(ev.detail || '').split(' · ').pop().trim();
      if (ev.action === 'send' && tail && ids.has(tail)) return;
      const label = (ctx.eventHe[ev.action] || ev.action || '');
      rows.push({ ts: ev.ts, label: e(label), detail: ev.detail ? e(ctx.detail(ev.detail)) : '' });
    });
    (links || []).forEach(l => {
      const who = e(l.signer_name || '');
      const what = l.kind === 'view' ? 'קישור לצפייה' : 'קישור לחתימה';
      if (l.created_at) rows.push({ ts: l.created_at, label: 'נשלח ' + what, detail: who ? 'אל ' + who : '' });
      if (l.opened_at) rows.push({ ts: l.opened_at, label: 'הקישור נפתח', detail: who });
      if (l.signed_at) rows.push({ ts: l.signed_at, label: 'החתימה התקבלה', detail: who });
    });
    rows.sort((a, b) => ms(a.ts) - ms(b.ts));
    if (!rows.length) return '<p class="muted">עוד לא קרה דבר עם המסמך.</p>';
    const waiting = (ctx.env && ['sent', 'opened'].includes(ctx.env.status)) || (ctx.fill || []).some(f => f.status === 'open');
    return '<ol class="dp-tl">' + rows.map((r, i) =>
      `<li class="${waiting && i === rows.length - 1 ? 'now' : 'done'}"><span class="dp-dot" aria-hidden="true"></span>` +
      `<span><b>${r.label}</b>${r.detail ? ' · ' + r.detail : ''}</span><small class="num">${e(ctx.when(r.ts))}</small></li>`).join('') +
      '</ol>';
  }

  /** WhatsApp to the customer's own number when the document holds one («050-123-4567», «+972 50…», «972…»), with
   *  the words ready; without a number, WhatsApp opens on the words and the owner picks the chat. An Israeli number
   *  is the only one rewritten (0 → 972); another country's is used as written, digits only. */
  function waLink(phone, text) {
    let n = String(phone || '').replace(/[^\d+]/g, '');
    if (n.startsWith('+')) n = n.slice(1);
    else if (n.startsWith('00')) n = n.slice(2);
    else if (/^0\d{8,9}$/.test(n)) n = '972' + n.slice(1);
    if (!/^\d{8,15}$/.test(n)) n = '';
    return 'https://wa.me/' + n + '?text=' + encodeURIComponent(text || '');
  }

  window.DocPanel = { next, timeline, ago, waLink, to };
})();
