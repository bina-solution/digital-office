/* Mock backend for מסמכים שלי (my-docs) — the real SPA (static/app.js + vendor/bina-table.js)
   runs untouched, standalone, with no apitools/Postgres behind it. Only window.fetch is intercepted.
   Business: בינה פתרונות בע״מ (ח.פ/עוסק מורשה 514789234). All document lifecycle rules (draft → issued →
   sent → paid, cancel-with-credit-note, convert-to-new-draft, gapless per-type numbering) are re-implemented
   in-memory here so the whole app — including creating/issuing/cancelling/converting documents — works for real
   against this mock, matching production/apitools/src/doc_data/store.py + entities.py field-for-field. */
(function () {
  var realFetch = window.fetch ? window.fetch.bind(window) : null;
  var J = function (o, status) {
    return Promise.resolve(new Response(JSON.stringify(o), { status: status || 200, headers: { 'Content-Type': 'application/json' } }));
  };
  function uid(prefix) { return prefix + '_' + Date.now().toString(36).slice(-5) + Math.random().toString(36).slice(2, 8); }
  function heDate(d) { return String(d.getDate()).padStart(2, '0') + '/' + String(d.getMonth() + 1).padStart(2, '0') + '/' + d.getFullYear(); }
  function addMonths(base, n) { var d = new Date(base); d.setMonth(d.getMonth() + n); return d; }
  function addDays(base, n) { var d = new Date(base); d.setDate(d.getDate() + n); return d; }
  function parseBody(opts) { try { return JSON.parse((opts && opts.body) || '{}'); } catch (e) { return {}; } }

  // ── the single business (source: entities.get_business / _DEFAULT_SETTINGS) ─────────────
  var BIZ = {
    id: 'default', onboarded: true, name: 'בינה פתרונות בע״מ', company_id: '514789234',
    business_type: 'murshe', street: 'הברזל 3', city: 'תל אביב', zip: '6971001',
    phone: '03-6120000', fax: '', email: 'person116@example.com', logo_b64: '',
    vat_pct: 18, vat_registered: true, default_series: 'A', doc_start: 0,
    bank_name: 'בנק הפועלים', bank_branch: '690', bank_account: '123-456789',
  };

  // ── customers (source: entities._TABLES.customers) ───────────────────────────────────────
  var CUSTOMERS = [
    { id: 'cus_karton', name: 'ישראל קרטון בע״מ', company_id: '512345678', street: 'המלאכה 12', city: 'פתח תקווה', zip: '4917612', phone: '03-9231144', email: 'person182@example.com', notes: 'לקוח קבוע — שוטף+30', created_at: addMonths(new Date(), -9).toISOString() },
    { id: 'cus_bakery', name: 'מאפיית הבוקר', company_id: '032456789', street: 'העצמאות 44', city: 'רמת גן', zip: '5252233', phone: '03-6754321', email: 'person183@example.com', notes: '', created_at: addMonths(new Date(), -7).toISOString() },
    { id: 'cus_or', name: 'טכנולוגיות אור בע״מ', company_id: '515987654', street: 'החושלים 8', city: 'הרצליה', zip: '4672108', phone: '09-9541200', email: 'person184@example.com', notes: 'לקוח פרויקטים — ת.שלום מ.ר.ד', created_at: addMonths(new Date(), -11).toISOString() },
    { id: 'cus_studio', name: 'סטודיו עיצוב פנים — רחל לוי', company_id: '027654321', street: 'שינקין 21', city: 'תל אביב', zip: '6522231', phone: '050-000-0017', email: 'person185@example.com', notes: '', created_at: addMonths(new Date(), -2).toISOString() },
    { id: 'cus_musach', name: 'מוסך אבי ובניו', company_id: '300123456', street: 'התעשייה 5', city: 'חולון', zip: '5810201', phone: '03-5501122', email: 'person186@example.com', notes: '', created_at: addMonths(new Date(), -6).toISOString() },
  ];

  // ── items / catalog (source: entities._TABLES.items) ─────────────────────────────────────
  var ITEMS = [
    { id: 'itm_consult', name: 'ייעוץ עסקי (שעה)', sku: 'CONS-01', description: 'ייעוץ אסטרטגי ותפעולי', unit: 'שעה', unit_price: 350, created_at: addMonths(new Date(), -11).toISOString() },
    { id: 'itm_dev', name: 'פיתוח תוכנה (יום עבודה)', sku: 'DEV-01', description: 'פיתוח והטמעת מערכות', unit: 'יום', unit_price: 1800, created_at: addMonths(new Date(), -11).toISOString() },
    { id: 'itm_design', name: 'עיצוב גרפי — פרויקט', sku: 'DESIGN-01', description: '', unit: 'פרויקט', unit_price: 2500, created_at: addMonths(new Date(), -5).toISOString() },
    { id: 'itm_pkg', name: 'אריזות קרטון (100 יח׳)', sku: 'PKG-100', description: 'קרטונים דו-גליים מחוזקים', unit: 'קרטון', unit_price: 240, created_at: addMonths(new Date(), -9).toISOString() },
    { id: 'itm_maint', name: 'תחזוקה חודשית', sku: 'MAINT-01', description: 'תחזוקה ותמיכה שוטפת', unit: 'חודש', unit_price: 600, created_at: addMonths(new Date(), -8).toISOString() },
  ];

  // ── document store (mirrors production/apitools/src/doc_data/store.py) ───────────────────
  var TYPE_SERIES = { INVOICE: 'INV', INVOICE_RECEIPT: 'IR', RECEIPT: 'RC', QUOTE: 'QT', ORDER: 'OR', SHIPMENT: 'DN', BALANCE_SHEET: 'BS' };
  var CONVERSIONS = { QUOTE: ['ORDER', 'INVOICE', 'INVOICE_RECEIPT'], ORDER: ['SHIPMENT', 'INVOICE', 'INVOICE_RECEIPT'], SHIPMENT: ['INVOICE', 'INVOICE_RECEIPT'], INVOICE: ['RECEIPT'] };
  var SEQ = {};       // "type|series|year" -> next seq
  var DOCS = {};       // id -> full record (superset returned by GET /documents/:id)
  var EVENTS = {};     // id -> [{ts, actor, action, detail}]

  function nextSeq(docType, series, year) {
    var k = docType + '|' + series + '|' + year;
    var start = BIZ.doc_start || 1;
    SEQ[k] = (SEQ[k] || start - 1) + 1;
    return SEQ[k];
  }
  function addEvent(id, action, detail, actor) {
    (EVENTS[id] = EVENTS[id] || []).push({ ts: new Date().toISOString(), actor: actor || 'api', action: action, detail: detail || '' });
  }
  function totals(model) {
    if (model.doc_type === 'RECEIPT') return { subtotal: null, discount: null, vat: null, total: Number(model.amount || 0) };
    var sub = (model.lines || []).reduce(function (s, l) { return s + (Number(l.qty) || 0) * (Number(l.unit_price) || 0); }, 0);
    var rate = model.vat_pct != null ? Number(model.vat_pct) : 0;
    var vat = model.doc_type === 'INVOICE' || model.doc_type === 'INVOICE_RECEIPT' ? sub * rate / 100 : 0;
    return { subtotal: sub, discount: 0, vat: vat, total: sub + vat };
  }
  // ── faithful document renderer — a 1:1 JS port of the REAL production template
  //    production/apitools/src/doc_gen/htmlgen.py (the "2026 design system": deep-emerald + warm
  //    neutrals, Rubik/Heebo, RTL, header + line-items + totals ladder + digital signature + footer).
  //    The real my-docs proxies /documents/:id/download → apitools doc-gen (WeasyPrint HTML→PDF); here
  //    we render the SAME HTML directly into the SPA's preview iframe. Fonts fall back to a Hebrew
  //    system stack (Rubik/Heebo if present) instead of the bundled TTFs — layout/design is identical. */
  function renderDocHtml(rec) {
    rec = rec || {};
    var m = rec.model || {};
    var sup = { name: BIZ.name, company_id: BIZ.company_id, tax_status: BIZ.business_type,
                street: BIZ.street, city: BIZ.city, phone: BIZ.phone, email: BIZ.email };
    var cust = m.customer || { name: rec.customer_name, company_id: rec.customer_id, street: '', city: '', phone: '' };
    var docId = rec.doc_number || (rec.status === 'draft' ? '—' : (rec.id || ''));
    var docDate = m.doc_date || (rec.issued_at || '').slice(0, 10) || '';
    var label = rec.status === 'draft' ? 'טיוטה' : 'מקור';
    var lines = (m.lines || []).map(function (l) {
      var qty = Number(l.qty) || 0, up = Number(l.unit_price) || 0;
      return { description: l.description || l.name || '', sku: l.sku || '', qty: qty, unit_price: up,
               total: l.total != null ? Number(l.total) : qty * up,
               order_ref: l.order_ref || '', customer_order_ref: l.customer_order_ref || '', shipment_ref: l.shipment_ref || '' };
    });

    function e(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
    function money(v) { var n = Number(v || 0); return isNaN(n) ? '0.00' : n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
    function nis(v) { return '<span class="num">' + money(v) + '</span> <span class="cur">₪</span>'; }
    function g(v) { return String(Number(v) || 0); } // %g-style qty
    function taxLine(s) { return ({ patur: 'עוסק פטור', company: 'ח.פ', murshe: 'עוסק מורשה' }[s.tax_status] || 'עוסק מורשה') + ' ' + e(s.company_id); }
    var KIND = { RECEIPT: 'קבלה', INVOICE: 'חשבונית מס', INVOICE_RECEIPT: 'חשבונית מס קבלה', QUOTE: 'הצעת מחיר', ORDER: 'הזמנת רכש', SHIPMENT: 'תעודת משלוח', BALANCE_SHEET: 'גיול חובות' };

    function header(kind, metaRows) {
      var contact = [((e(sup.street) + ', ' + e(sup.city)).replace(/^[ ,]+|[ ,]+$/g, '')),
                     sup.phone ? 'טלפון ' + e(sup.phone) : '', sup.email ? e(sup.email) : '']
                    .filter(function (x) { return x.replace(/[ ,]/g, ''); }).join(' · ');
      var rows = metaRows.map(function (r) { return '<div class="row"><span>' + r[0] + '</span><b>' + r[1] + '</b></div>'; }).join('');
      var initial = (sup.name || 'ב').trim().charAt(0);
      return '<div class="head"><div class="brandbox"><div class="mono">' + e(initial) + '</div><div>' +
        '<div class="bizname">' + e(sup.name) + '</div><div class="bizmeta"><b>' + taxLine(sup) + '</b></div>' +
        '<div class="bizmeta">' + contact + '</div></div></div>' +
        '<div class="docchip"><div class="kind">' + kind + '</div><div class="no">' + e(docId) + '</div>' + rows + '</div></div><div class="rule"></div>';
    }
    function customer(extra) {
      var det = [(e(cust.street) + ' ' + e(cust.city)).trim(), cust.company_id ? 'ח.פ ' + e(cust.company_id) : '', cust.phone ? 'טלפון ' + e(cust.phone) : '']
                .filter(function (x) { return x.trim(); }).join(' · ');
      return '<div class="band"><div class="to"><div class="eyebrow">לכבוד</div><div class="who">' + e(cust.name) + '</div>' +
        (det ? '<div class="det">' + det + '</div>' : '') + '</div><div>' + (extra || '') + '</div></div>';
    }
    function signature() {
      return '<div class="sign"><div class="seal"><div class="nm">' + e(sup.name) + '</div><div class="hr"></div>' +
        '<div class="sm">' + taxLine(sup) + '</div></div><div class="sig"><div class="line"></div>' +
        '<div class="eyebrow">חתימה וחותמת</div><div class="digital">✓ נחתם דיגיטלית — מסמך ממוחשב</div></div></div>';
    }
    function footer(kind) {
      var ts = new Date(); var p = function (n) { return String(n).padStart(2, '0'); };
      var tss = p(ts.getDate()) + '/' + p(ts.getMonth() + 1) + '/' + ts.getFullYear() + ' ' + p(ts.getHours()) + ':' + p(ts.getMinutes());
      return '<div class="foot"><div class="l"><b>' + e(sup.name) + '</b> · ' + kind + ' ' + e(docId) + ' · ' + label + '</div>' +
        '<div>מסמך ממוחשב · נשמר 7 שנים · הופק ב־' + tss + '</div></div>';
    }
    function skeleton(body, foot, watermark) {
      // FLUID, fills-to-width layout (no JS scaling — the preview iframe blocks inline scripts, and a
      // fluid page can never clip/overflow regardless of pane width). The A4 print design is preserved;
      // only the fixed page width becomes responsive (max A4, shrinks to fit). Footer flows at the end.
      return '<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><style>' + CSS + '</style></head>' +
        '<body><div class="page">' + (watermark || '') + '<main>' + body + '</main>' + foot + '</div></body></html>';
    }
    function linesDoc(kind, subtitle, extra) {
      var meta = [['תאריך', e(docDate)]];
      if (m.valid_until) meta.push(['בתוקף עד', e(m.valid_until)]);
      var head = header(kind, meta);
      var rows = lines.map(function (l) {
        var sku = l.sku ? '<div class="sku">' + e(l.sku) + '</div>' : '';
        var rp = [];
        if (l.order_ref) rp.push('הזמנה ' + e(l.order_ref));
        if (l.customer_order_ref) rp.push('הזמנתכם ' + e(l.customer_order_ref));
        if (l.shipment_ref) rp.push('תעודה ' + e(l.shipment_ref));
        var refs = rp.length ? '<div class="sku">' + rp.join(' · ') + '</div>' : '';
        return '<tr><td class="desc">' + e(l.description) + sku + refs + '</td><td class="n">' + g(l.qty) +
          '</td><td class="n">' + money(l.unit_price) + '</td><td class="n">' + money(l.total) + '</td></tr>';
      }).join('');
      var table = '<table class="lines"><thead><tr><th>תיאור</th><th class="n">כמות</th><th class="n">מחיר יחידה</th><th class="n">סכום</th></tr></thead><tbody>' + rows + '</tbody></table>';
      var sub = rec.subtotal, vat = rec.vat, vatPct = m.vat_pct || 0;
      var total = rec.total != null ? rec.total : (m.amount || 0);
      var tr = '<div class="tl"><span class="k">סכום ביניים</span>' + nis(sub != null ? sub : total) + '</div>';
      if (rec.discount) tr += '<div class="tl"><span class="k">הנחה</span>' + nis(rec.discount) + '</div>';
      if (vatPct) tr += '<div class="tl"><span class="k">מע״מ ' + g(vatPct) + '%</span>' + nis(vat) + '</div>';
      var totals = '<div class="totwrap"><div class="totals">' + tr + '<div class="tl grand"><span class="k">' +
        (kind !== 'הצעת מחיר' ? 'סה״כ לתשלום' : 'סה״כ להצעה') + '</span>' + nis(total) + '</div></div></div>';
      var tail = kind === 'הצעת מחיר' ? '<div class="note muted">הצעת מחיר זו אינה מהווה מסמך חשבונאי.</div>' : '';
      var body = head + customer('') + '<div class="sec"><div class="eyebrow">' + (subtitle || 'פירוט') + '</div>' + table + totals + '</div>' + (extra || '') + tail + signature();
      return skeleton(body, footer(kind));
    }
    function paymentBlock() {
      var method = m.payment_method || 'מזומן', paid = m.amount_paid != null ? m.amount_paid : (rec.total || 0);
      var cells = [['אמצעי תשלום', e(method)], ['סכום ששולם', nis(paid)]];
      var grid = cells.map(function (c) { return '<div class="cell"><div class="k">' + c[0] + '</div><div class="v">' + c[1] + '</div></div>'; }).join('');
      return '<div class="sec"><div class="eyebrow">פרטי תשלום (קבלה)</div><div class="grid">' + grid + '</div></div>';
    }
    function receipt() {
      var head = header('קבלה', [['תאריך', e(docDate)]]);
      var method = m.payment_method || 'מזומן';
      var cells = [['אמצעי תשלום', e(method)], ['תאריך תשלום', e(docDate)]];
      var grid = cells.map(function (c) { return '<div class="cell"><div class="k">' + c[0] + '</div><div class="v">' + c[1] + '</div></div>'; }).join('');
      var nature = e(m.nature || '');
      var amt = m.amount != null ? m.amount : (rec.total || 0);
      var body = head + customer('<span class="pill">מסמך ממוחשב</span>') +
        '<div class="hero"><div class="lbl"><span class="tick">✓</span>סכום שהתקבל</div><div class="amt"><span class="num">' + money(amt) + '</span> ₪</div></div>' +
        '<div class="grid">' + grid + '</div>' + (nature ? '<div class="note"><span class="muted">עבור:</span> ' + nature + '</div>' : '') + signature();
      return skeleton(body, footer('קבלה'));
    }

    var dt = rec.doc_type;
    if (dt === 'RECEIPT') return receipt();
    if (dt === 'INVOICE_RECEIPT') return linesDoc(KIND[dt], '', paymentBlock());
    return linesDoc(KIND[dt] || dt, '');
  }
  // CSS ported verbatim from htmlgen._css() (fonts swapped for a Hebrew system stack; a screen .page
  // wrapper + absolute footer/watermark replace the print @page/fixed constructs).
  var CSS = ':root{--ink:#16211D;--brand:#0E5A48;--brand-deep:#0A3F33;--accent:#2FA98A;--wash:#EAF3EF;--wash-line:#CFE6DC;--muted:#7C8781;--line:#E9E5DB;--paper:#FFFFFF;--tint:#FBFAF6}' +
    '*{box-sizing:border-box;margin:0;padding:0}' +
    'html{font-family:Rubik,Heebo,Assistant,"Segoe UI","Noto Sans Hebrew",Arial,sans-serif;color:var(--ink);font-size:10.5pt;line-height:1.5}' +
    'body{direction:rtl;background:#e9edf0;margin:0;padding:16px 0;overflow-x:hidden}' +
    '.page{position:relative;width:100%;max-width:210mm;margin:0 auto;background:#fff;padding:30px clamp(20px,3.5vw,42px) 40px;box-shadow:0 6px 30px rgba(10,20,16,.14)}' +
    '.num{direction:ltr;unicode-bidi:isolate;font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1;white-space:nowrap}' +
    '.rubik{font-family:Rubik,Heebo,sans-serif}.muted{color:var(--muted)}' +
    '.eyebrow{font-size:8pt;letter-spacing:.12em;color:var(--muted);font-weight:600}' +
    '.head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}' +
    '.brandbox{display:flex;gap:12px;align-items:flex-start}' +
    '.mono{width:46px;height:46px;border-radius:13px;background:var(--brand);color:#fff;font-family:Rubik;font-weight:700;font-size:24pt;display:flex;align-items:center;justify-content:center;flex:none}' +
    '.bizname{font-family:Rubik;font-weight:700;font-size:19pt;color:var(--brand-deep);letter-spacing:-.01em;line-height:1.15}' +
    '.bizmeta{font-size:9pt;color:var(--muted);margin-top:3px}.bizmeta b{color:var(--ink);font-weight:600}' +
    '.docchip{border:1px solid var(--line);border-radius:14px;padding:13px 18px 15px;min-width:168px;background:var(--tint);text-align:left}' +
    '.docchip .kind{font-family:Rubik;font-weight:600;font-size:13pt;color:var(--brand)}' +
    '.docchip .no{font-family:Heebo;font-weight:800;font-size:21pt;color:var(--ink);letter-spacing:.01em;margin-top:1px}' +
    '.docchip .row{display:flex;justify-content:space-between;gap:14px;font-size:9pt;margin-top:7px;color:var(--muted)}.docchip .row b{color:var(--ink);font-weight:600}' +
    '.rule{height:2px;background:linear-gradient(90deg,var(--brand) 0%,var(--accent) 55%,transparent 100%);border-radius:2px;margin:16px 0 4px}' +
    '.band{display:flex;justify-content:space-between;gap:20px;margin-top:14px}' +
    '.to .who{font-size:13pt;font-weight:700;color:var(--ink);margin-top:2px}.to .det{font-size:9.5pt;color:var(--muted);margin-top:1px}' +
    '.sec{margin-top:20px}.sec>.eyebrow{margin-bottom:8px}' +
    '.hero{background:var(--wash);border:1px solid var(--wash-line);border-radius:16px;padding:18px 22px;display:flex;justify-content:space-between;align-items:center;margin-top:16px}' +
    '.hero .lbl{font-size:11pt;color:var(--brand-deep);font-weight:600;display:inline-flex;align-items:center;gap:9px;white-space:nowrap}' +
    '.hero .tick{width:24px;height:24px;border-radius:50%;background:var(--brand);color:#fff;display:inline-flex;align-items:center;justify-content:center;font-size:12pt;font-weight:700}' +
    '.hero .amt{font-family:Heebo;font-weight:800;font-size:26pt;color:var(--brand-deep)}' +
    '.grid{display:flex;flex-wrap:wrap;gap:10px 34px;margin-top:16px}.grid .cell{min-width:150px}' +
    '.grid .k{font-size:8.5pt;color:var(--muted);letter-spacing:.04em}.grid .v{font-size:11pt;color:var(--ink);font-weight:600;margin-top:1px}' +
    '.note{margin-top:14px;font-size:10pt;color:var(--ink)}' +
    'table.lines{width:100%;border-collapse:collapse;margin-top:6px}' +
    'table.lines thead th{font-size:8.5pt;color:var(--brand-deep);font-weight:700;text-align:right;padding:0 8px 8px;border-bottom:1.5px solid var(--brand);letter-spacing:.03em}' +
    'table.lines thead th.n{text-align:left}' +
    'table.lines tbody td{padding:9px 8px;font-size:10.5pt;border-bottom:1px solid var(--line);vertical-align:top}' +
    'table.lines td.n{text-align:left;white-space:nowrap}table.lines td.desc{color:var(--ink)}table.lines td .sku{font-size:8.5pt;color:var(--muted)}' +
    '.totwrap{display:flex;justify-content:flex-start;margin-top:16px}.totals{width:52%}' +
    '.totals .tl{display:flex;justify-content:flex-start;gap:12px;padding:5px 2px;font-size:10.5pt}.totals .tl .k{color:var(--muted)}' +
    '.totals .grand{margin-top:8px;background:var(--wash);border:1px solid var(--wash-line);border-radius:12px;padding:12px 16px}' +
    '.totals .grand .k{color:var(--brand-deep);font-weight:700;font-size:11.5pt}.totals .grand .num{font-family:Heebo;font-weight:800;font-size:15pt;color:var(--brand-deep)}' +
    '.pill{display:inline-block;font-size:8.5pt;font-weight:700;letter-spacing:.06em;padding:3px 11px;border-radius:999px;border:1px solid var(--wash-line);color:var(--brand-deep);background:var(--wash)}' +
    '.watermark{position:absolute;top:38%;left:0;right:0;text-align:center;font-family:Rubik;font-weight:800;font-size:90pt;color:rgba(14,90,72,.06);letter-spacing:.1em;transform:rotate(-18deg)}' +
    '.sign{display:flex;justify-content:space-between;align-items:flex-end;margin-top:48px;padding-top:34px;gap:24px}' +
    '.seal{width:104px;height:104px;border-radius:50%;border:2px solid var(--brand);box-shadow:inset 0 0 0 3px #fff,inset 0 0 0 4.5px var(--accent);color:var(--brand-deep);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:14px;line-height:1.2;opacity:.5;transform:rotate(-8deg);flex:none;margin-left:6px}' +
    '.seal .nm{font-family:Rubik;font-weight:700;font-size:9pt}.seal .sm{font-size:6.5pt;font-weight:600;letter-spacing:.05em;margin-top:3px}.seal .hr{width:42px;height:1px;background:var(--brand);opacity:.6;margin:4px 0}' +
    '.sig{text-align:center;min-width:210px}.sig .line{border-bottom:1.4px solid var(--ink);height:30px;margin-bottom:6px}.sig .digital{font-size:8pt;color:var(--accent);font-weight:600}' +
    '.foot{margin-top:40px;padding-top:9px;border-top:1px solid var(--line);font-size:8pt;color:var(--muted);display:flex;justify-content:space-between;gap:12px}.foot .l b{color:var(--brand-deep);font-weight:600}';

  // create() — a fresh DRAFT (source: store.create). `when` lets the seed data backdate
  // created_at so the dashboard's 12-month chart has real spread; live creates omit it (= now).
  function createDoc(model, actor, when) {
    model = Object.assign({}, model);
    if (!model.doc_date) model.doc_date = heDate(when || new Date());
    var id = uid('doc');
    var t = totals(model);
    var rec = {
      id: id, doc_number: null, doc_type: model.doc_type, status: 'draft', series: null, tax_year: null, seq_number: null,
      issuer_id: BIZ.company_id, customer_id: (model.customer && model.customer.company_id) || null,
      customer_name: (model.customer && model.customer.name) || '', currency: 'ILS',
      subtotal: t.subtotal, discount: t.discount, vat: t.vat, total: t.total,
      allocation_number: '', allocation_status: 'none', model: model, truth: null, file_ext: 'pdf',
      original_served_at: null, cancels: null, cancelled_by: null, converted_from: null,
      created_at: (when || new Date()).toISOString(), updated_at: (when || new Date()).toISOString(), issued_at: null,
    };
    DOCS[id] = rec;
    addEvent(id, 'create', model.doc_type, actor);
    return rec;
  }
  // issue() — DRAFT -> ISSUED with a gapless per-(type,series,year) number (source: store.issue)
  function issueDoc(id, when, actor) {
    var rec = DOCS[id]; if (!rec) throw new Error('not_found');
    if (rec.status !== 'draft') return rec;
    var series = TYPE_SERIES[rec.doc_type] || 'A';
    var d = when || new Date();
    var year = String(d.getFullYear());
    var seq = nextSeq(rec.doc_type, series, year);
    rec.doc_number = BIZ.doc_start ? String(seq) : series + '-' + year + '-' + String(seq).padStart(5, '0');
    rec.series = series; rec.tax_year = year; rec.seq_number = seq;
    rec.status = 'issued'; rec.issued_at = d.toISOString(); rec.updated_at = d.toISOString();
    addEvent(id, 'issue', rec.doc_number, actor);
    return rec;
  }
  function transition(id, toStatus, action, detail, actor) {
    var rec = DOCS[id]; if (!rec) throw new Error('not_found');
    rec.status = toStatus; rec.updated_at = new Date().toISOString();
    addEvent(id, action, detail, actor);
    return rec;
  }
  // cancel() — ISSUED/SENT/PAID -> CANCELLED, auto-issuing a reversing credit invoice (source: store.cancel)
  function cancelDoc(id, reason, actor) {
    var rec = DOCS[id]; if (!rec) throw new Error('not_found');
    var credit = null;
    if (rec.status !== 'draft') {
      var cm = Object.assign({}, rec.model, {
        doc_type: 'INVOICE', doc_id: '', centralized: false,
        details_note: 'חשבונית זיכוי כנגד ' + (rec.doc_number || rec.id) + ' — ' + (reason || ''),
        lines: (rec.model.lines || []).map(function (l) { return Object.assign({}, l, { unit_price: -Math.abs(Number(l.unit_price) || 0) }); }),
      });
      credit = createDoc(cm, actor);
      credit = issueDoc(credit.id, new Date(), actor);
    }
    rec.status = 'cancelled'; rec.cancelled_by = credit ? credit.id : null; rec.updated_at = new Date().toISOString();
    addEvent(id, 'cancel', reason || '', actor);
    if (credit) credit.cancels = id;
    var out = Object.assign({}, rec);
    out.credit_document = credit || null;
    return out;
  }
  // convert() — build a fresh DRAFT of `toType` carrying customer+lines (source: store.convert)
  function convertDoc(id, toType, actor) {
    var src = DOCS[id]; if (!src) throw new Error('not_found');
    var allowed = CONVERSIONS[src.doc_type] || [];
    if (allowed.indexOf(toType) === -1) throw new Error('cannot convert ' + src.doc_type + ' -> ' + toType);
    var sm = src.model, m;
    if (toType === 'RECEIPT') {
      m = { doc_type: toType, doc_date: sm.doc_date, customer: sm.customer, amount: Number(src.total || 0),
            nature: 'תשלום ע"ח ' + (src.doc_number || ''), payment_method: sm.payment_method || 'מזומן' };
    } else {
      m = { doc_type: toType, doc_date: sm.doc_date, customer: sm.customer, lines: sm.lines || [] };
      if (toType === 'INVOICE' || toType === 'INVOICE_RECEIPT') { m.issued_at_shipping = true; m.vat_pct = sm.vat_pct != null ? sm.vat_pct : BIZ.vat_pct; }
    }
    var draft = createDoc(m, actor);
    draft.converted_from = src.doc_number || src.id;
    addEvent(draft.id, 'convert', 'מ-' + (src.doc_number || src.id) + ' (' + src.doc_type + ')', actor);
    addEvent(id, 'converted', '→ ' + toType, actor);
    return draft;
  }
  // GET /documents list projection (source: store.query — a BARE array, not {data,total})
  function listDocs(params) {
    var rows = Object.keys(DOCS).map(function (k) { return DOCS[k]; });
    if (params.get('type')) rows = rows.filter(function (r) { return r.doc_type === params.get('type'); });
    if (params.get('status')) rows = rows.filter(function (r) { return r.status === params.get('status'); });
    if (params.get('customer_id')) rows = rows.filter(function (r) { return r.customer_id === params.get('customer_id'); });
    rows.sort(function (a, b) { return new Date(b.created_at) - new Date(a.created_at); });
    var offset = Number(params.get('offset') || 0), limit = Number(params.get('limit') || 100);
    return rows.slice(offset, offset + limit).map(function (r) {
      return { id: r.id, doc_number: r.doc_number, doc_type: r.doc_type, status: r.status, customer_name: r.customer_name,
               total: r.total, currency: r.currency, allocation_number: r.allocation_number, issued_at: r.issued_at,
               created_at: r.created_at, doc_date: r.model.doc_date };
    });
  }

  // ── seed a realistic, populated ledger (13 documents spanning ~11 months incl. a full
  //    quote→order→shipment→invoice conversion chain, a paid receipt, and a cancel+credit-note) ──
  (function seed() {
    var C = {}; CUSTOMERS.forEach(function (c) { C[c.id] = c; });
    function party(cid) { var c = C[cid]; return { name: c.name, company_id: c.company_id, street: c.street, city: c.city }; }
    function lines(items) { return items.map(function (it) { return { description: it[0], qty: it[1], unit_price: it[2], sku: it[3] || '' }; }); }
    var now = new Date();

    // 1) quote -> invoice conversion chain (טכנולוגיות אור)
    var t1 = addMonths(now, -8);
    var q1 = createDoc({ doc_type: 'QUOTE', customer: party('cus_or'), lines: lines([['פיתוח תוכנה (יום עבודה)', 6, 1800, 'DEV-01']]),
      valid_until: heDate(addDays(t1, 30)) }, 'api', t1);
    issueDoc(q1.id, t1);
    var t1b = addDays(t1, 12);
    var inv1 = convertDoc(q1.id, 'INVOICE', 'api');
    inv1.model.vat_pct = BIZ.vat_pct; inv1.model.doc_date = heDate(t1b); inv1.created_at = t1b.toISOString();
    Object.assign(inv1, totals(inv1.model));
    issueDoc(inv1.id, t1b);
    transition(inv1.id, 'sent', 'send', 'person184@example.com');
    transition(inv1.id, 'paid', 'pay', 'העברה בנקאית');

    // 2) invoice, paid (ישראל קרטון)
    var t2 = addMonths(now, -6);
    var inv2 = createDoc({ doc_type: 'INVOICE', customer: party('cus_karton'), vat_pct: BIZ.vat_pct, issued_at_shipping: true,
      lines: lines([['אריזות קרטון (100 יח׳)', 40, 240, 'PKG-100']]) }, 'api', t2);
    issueDoc(inv2.id, t2); transition(inv2.id, 'sent', 'send', 'person182@example.com');
    transition(inv2.id, 'paid', 'pay', 'שיק');

    // 3) invoice, sent — awaiting payment (ישראל קרטון)
    var t3 = addMonths(now, -1);
    var inv3 = createDoc({ doc_type: 'INVOICE', customer: party('cus_karton'), vat_pct: BIZ.vat_pct, issued_at_shipping: true,
      lines: lines([['אריזות קרטון (100 יח׳)', 25, 240, 'PKG-100'], ['תחזוקה חודשית', 1, 600, 'MAINT-01']]) }, 'api', t3);
    issueDoc(inv3.id, t3); transition(inv3.id, 'sent', 'send', 'person182@example.com');

    // 4) invoice-receipt, paid (מאפיית הבוקר)
    var t4 = addMonths(now, -3);
    var ir1 = createDoc({ doc_type: 'INVOICE_RECEIPT', customer: party('cus_bakery'), vat_pct: BIZ.vat_pct, issued_at_shipping: true,
      payment_method: 'כרטיס אשראי', paid_amount: 0,
      lines: lines([['ייעוץ עסקי (שעה)', 4, 350, 'CONS-01']]) }, 'api', t4);
    ir1.model.paid_amount = totals(ir1.model).total; ir1.total = ir1.model.paid_amount;
    issueDoc(ir1.id, t4); transition(ir1.id, 'paid', 'pay', 'כרטיס אשראי');

    // 5) plain receipt for a cash payment (מאפיית הבוקר)
    var t5 = addDays(t4, 20);
    var rc1 = createDoc({ doc_type: 'RECEIPT', customer: party('cus_bakery'), amount: 900,
      nature: 'תחזוקה חודשית — יולי', payment_method: 'מזומן' }, 'api', t5);
    issueDoc(rc1.id, t5);

    // 6-8) purchase-order -> shipment -> invoice chain (מוסך אבי ובניו)
    var t6 = addMonths(now, -5);
    var ord1 = createDoc({ doc_type: 'ORDER', customer: party('cus_musach'),
      lines: lines([['פיתוח תוכנה (יום עבודה)', 2, 1800, 'DEV-01']]) }, 'api', t6);
    issueDoc(ord1.id, t6);
    var t6b = addDays(t6, 5);
    var dn1 = convertDoc(ord1.id, 'SHIPMENT', 'api'); dn1.created_at = t6b.toISOString(); dn1.model.doc_date = heDate(t6b);
    issueDoc(dn1.id, t6b);
    var t6c = addDays(t6b, 3);
    var inv4 = convertDoc(dn1.id, 'INVOICE', 'api');
    inv4.model.vat_pct = BIZ.vat_pct; inv4.model.doc_date = heDate(t6c); inv4.created_at = t6c.toISOString();
    Object.assign(inv4, totals(inv4.model));
    issueDoc(inv4.id, t6c); transition(inv4.id, 'sent', 'send', 'person186@example.com');

    // 9) fresh drafts awaiting action (סטודיו עיצוב פנים — רחל לוי)
    var t7 = addDays(now, -14);
    createDoc({ doc_type: 'QUOTE', customer: party('cus_studio'),
      lines: lines([['עיצוב גרפי — פרויקט', 1, 2500, 'DESIGN-01']]), valid_until: heDate(addDays(t7, 30)) }, 'api', t7);
    var t8 = addDays(now, -6);
    createDoc({ doc_type: 'INVOICE', customer: party('cus_studio'), vat_pct: BIZ.vat_pct, issued_at_shipping: true,
      lines: lines([['עיצוב גרפי — פרויקט', 1, 2500, 'DESIGN-01']]) }, 'api', t8);

    // 10) an invoice, later cancelled — auto-issues a reversing credit invoice (ישראל קרטון)
    var t9 = addMonths(now, -4);
    var inv5 = createDoc({ doc_type: 'INVOICE', customer: party('cus_karton'), vat_pct: BIZ.vat_pct, issued_at_shipping: true,
      lines: lines([['אריזות קרטון (100 יח׳)', 15, 240, 'PKG-100']]) }, 'api', t9);
    issueDoc(inv5.id, t9);
    cancelDoc(inv5.id, 'הזמנה בוטלה על ידי הלקוח', 'api');
  })();

  // ── entity CRUD helpers (customers/items — source: entities._crud) ───────────────────────
  function findEntity(list, id) { for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i]; return null; }
  function crudList(list, q) {
    if (!q) return list.slice();
    q = String(q).toLowerCase();
    return list.filter(function (r) {
      return (r.name || '').toLowerCase().indexOf(q) !== -1
        || (r.company_id || '').toLowerCase().indexOf(q) !== -1
        || (r.sku || '').toLowerCase().indexOf(q) !== -1;
    });
  }
  function crudCreate(list, cols, body) {
    var row = { id: uid(list === CUSTOMERS ? 'cus' : 'itm'), created_at: new Date().toISOString() };
    cols.forEach(function (c) { row[c] = body[c] != null ? body[c] : ''; });
    list.push(row);
    return row;
  }
  function crudUpdate(list, id, cols, body) {
    var row = findEntity(list, id); if (!row) return null;
    cols.forEach(function (c) { if (c in body) row[c] = body[c]; });
    row.updated_at = new Date().toISOString();
    return row;
  }
  function crudDelete(list, id) {
    for (var i = 0; i < list.length; i++) if (list[i].id === id) { list.splice(i, 1); break; }
    return { deleted: id };
  }
  var CUSTOMER_COLS = ['name', 'company_id', 'street', 'city', 'zip', 'phone', 'email', 'notes'];
  var ITEM_COLS = ['name', 'sku', 'description', 'unit', 'unit_price'];

  // ── router ─────────────────────────────────────────────────────────────────────────────
  // app.js calls fetch('api' + path, opt) — always a *relative* URL — so we resolve it
  // against location.href to safely read query params, then dispatch on the path segments
  // that follow "api/".
  window.fetch = function (url, opts) {
    var u = String(url);
    var m = u.match(/api\/([^?#]*)/);
    if (!m) return realFetch ? realFetch(url, opts) : Promise.reject(new Error('mock: no route ' + u));
    var full;
    try { full = new URL(u, location.href); } catch (e) { full = null; }
    var params = full ? full.searchParams : new URLSearchParams();
    var segs = m[1].replace(/\/+$/, '').split('/').filter(Boolean);
    var method = ((opts && opts.method) || 'GET').toUpperCase();
    var body = parseBody(opts);

    try {
      // /api/me
      if (segs[0] === 'me') {
        return J({ user: 'akadmin', email: 'person133@example.com', name: 'מיכל לוי', groups: ['staff'] });
      }
      // /api/business
      if (segs[0] === 'business') {
        if (method === 'PUT' || method === 'POST') {
          Object.keys(body).forEach(function (k) { if (k in BIZ) BIZ[k] = body[k]; });
          BIZ.doc_start = parseInt(BIZ.doc_start, 10) || 0;
          if (BIZ.business_type === 'patur') { BIZ.vat_pct = 0; BIZ.vat_registered = false; }
          BIZ.onboarded = !!(BIZ.name && BIZ.company_id);
        }
        return J(BIZ);
      }
      // /api/customers[/:id], /api/items[/:id]
      if (segs[0] === 'customers' || segs[0] === 'items') {
        var list = segs[0] === 'customers' ? CUSTOMERS : ITEMS;
        var cols = segs[0] === 'customers' ? CUSTOMER_COLS : ITEM_COLS;
        var rid = segs[1];
        if (!rid) {
          if (method === 'POST') return J(crudCreate(list, cols, body), 201);
          return J(crudList(list, params.get('q')));
        }
        if (method === 'GET') { var row = findEntity(list, rid); return row ? J(row) : J({ error: 'not_found' }, 404); }
        if (method === 'PATCH') { var upd = crudUpdate(list, rid, cols, body); return upd ? J(upd) : J({ error: 'not_found' }, 404); }
        if (method === 'DELETE') return J(crudDelete(list, rid));
        return J({ error: 'not_found' }, 404);
      }
      // /api/documents ...
      if (segs[0] === 'documents') {
        if (segs.length === 1) {
          if (method === 'POST') {
            var rec = createDoc(body, 'api');
            if (params.get('issue') === '1' || params.get('issue') === 'true') rec = issueDoc(rec.id);
            return J(rec, 201);
          }
          return J(listDocs(params));
        }
        var did = segs[1];
        // /documents/consent and /documents/verify are apitools-level utility routes — not
        // called anywhere by app.js — but are handled here (not as a doc id) for completeness.
        if (did === 'consent' && segs.length === 2) return J({ ok: true });
        if (did === 'verify' && segs.length === 2) return J({ sequence: { ok: true }, chain: { ok: true }, signer: { status: 'ok' } });
        if (segs.length === 2) {
          if (method === 'GET') { var d = DOCS[did]; return d ? J(d) : J({ error: 'not_found' }, 404); }
          if (method === 'PATCH') {
            var doc = DOCS[did]; if (!doc) return J({ error: 'not_found' }, 404);
            if (doc.status !== 'draft') return J({ error: 'PermissionError', message: 'document is ' + doc.status + ' and immutable' }, 409);
            doc.model = Object.assign({}, doc.model, body);
            Object.assign(doc, totals(doc.model));
            doc.customer_name = (doc.model.customer && doc.model.customer.name) || doc.customer_name;
            doc.updated_at = new Date().toISOString();
            addEvent(did, 'update', Object.keys(body).sort().join(','));
            return J(doc);
          }
          return J({ error: 'not_found' }, 404);
        }
        var action = segs[2];
        if (!DOCS[did] && action !== 'consent' && action !== 'verify') return J({ error: 'not_found' }, 404);
        if (action === 'events') return J(EVENTS[did] || []);
        if (action === 'download') {
          // The SPA loads this into a same-origin preview <iframe src> (and window.open). The real
          // backend proxies to apitools doc-gen (WeasyPrint HTML→PDF); we serve the SAME document
          // HTML (faithful port of htmlgen.py) directly — real Hebrew, RTL, the 2026 emerald design.
          return Promise.resolve(new Response(renderDocHtml(DOCS[did] || {}), {
            status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' }
          }));
        }
        if (action === 'issue') { try { return J(issueDoc(did, new Date())); } catch (e) { return J({ error: 'not_compliant', message: String(e.message || e) }, 422); } }
        if (action === 'send') return J(transition(did, 'sent', 'send', body.to || ''));
        if (action === 'pay') return J(transition(did, 'paid', 'pay', body.detail || ''));
        if (action === 'cancel') return J(cancelDoc(did, body.reason || ''));
        if (action === 'convert') {
          try { return J(convertDoc(did, body.to_type, 'api'), 201); }
          catch (e) { return J({ error: 'ValueError', message: String(e.message || e) }, 400); }
        }
        if (action === 'allocation') {
          var dd = DOCS[did]; dd.allocation_number = body.allocation_number || ''; dd.allocation_status = body.status || 'granted';
          return J(dd);
        }
        if (action === 'consent') return J({ ok: true });
        if (action === 'verify') return J({ sequence: { ok: true }, chain: { ok: true }, signer: { status: 'ok' } });
        return J({ error: 'not_found' }, 404);
      }
    } catch (e) {
      return J({ error: 'mock_error', message: String(e && e.message || e) }, 500);
    }
    // any other /api/... — empty-but-valid so the UI never throws
    return J(method === 'GET' ? [] : {});
  };
})();
