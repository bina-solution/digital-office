/* esign — «מילוי וחתימה» (DGO-2139): the page behind one signing link.
 *
 * One link, every party of the document: whoever opens it picks their side, answers only that side's questions, sees
 * the answers in their places on the real page, and signs where the document has its line. The page is plain script,
 * no framework: a phone on 4G opens it at once. The server gives the first state inline (#fill-boot) and answers four
 * calls under the link's own path — claim, answers, sign, state. A token is the only key: nothing here reaches any other
 * part of the office.
 */
(function () {
  'use strict';
  var root = document.getElementById('fill');
  if (!root) return;
  var BOOT = JSON.parse((document.getElementById('fill-boot') || {}).textContent || '{}');
  var BASE = BOOT.base || location.pathname.replace(/\/+$/, '');

  // ── state ─────────────────────────────────────────────────────────────────────────────────────────
  var S = {
    ev: BOOT.event || {}, parties: BOOT.parties || [], fields: BOOT.fields || [], office: BOOT.office || {},
    me: BOOT.me || null,          // the party this browser took, once it took one
    view: 'home', step: 0, values: {}, errors: {}, sig: null, stamp: null, typed: '', mode: 'draw',
    consent: false, busy: false, note: null, sheet: false, took: null
  };
  (BOOT.mine || []).forEach(function (v) { S.values[v.field] = v.value; });

  // ── small tools ───────────────────────────────────────────────────────────────────────────────────
  var ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return ESC[c]; }); }
  var PATHS = {
    lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
    back: '<polyline points="9 18 15 12 9 6"/>', fwd: '<polyline points="15 18 9 12 15 6"/>',
    check: '<polyline points="20 6 9 17 4 12"/>', x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    dl: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    edit: '<path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>',
    undo: '<polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>',
    alert: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>',
    info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
    camera: '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>'
  };
  function ic(n) { return '<svg class="f-ic" viewBox="0 0 24 24" aria-hidden="true">' + PATHS[n] + '</svg>'; }
  function party(id) { for (var i = 0; i < S.parties.length; i++) if (S.parties[i].id === id) return S.parties[i]; return null; }
  /** A page's picture: the address the server named for it (a version in it, so a cache never shows an old page). */
  function pageSrc(n) { var p = (S.ev.pages || [])[n - 1]; return (p && p.src) || BASE + '/f/page/' + n; }
  function pno(p) { return (S.parties.indexOf(p) % 4) + 1; }
  function fieldsOf(pid) { return S.fields.filter(function (f) { return f.party === pid; }); }
  var SIGN_TYPES = { signature: 1, initials: 1 };
  var AUTO_TYPES = { date_signed: 1 };
  function asks(f) { return !SIGN_TYPES[f.type] && !AUTO_TYPES[f.type] && f.type !== 'stamp'; }
  function today() { var d = new Date(); return pad2(d.getDate()) + '.' + pad2(d.getMonth() + 1) + '.' + d.getFullYear(); }
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function when(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d)) return iso;
    return pad2(d.getDate()) + '.' + pad2(d.getMonth() + 1) + ' · ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  }
  function dateHe(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
    return m ? m[3] + '.' + m[2] + '.' + m[1] : (iso || '');
  }
  function api(path, body) {
    return fetch(BASE + path, {
      method: body ? 'POST' : 'GET', credentials: 'same-origin',
      headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { j.status = r.status; return j; });
    }).catch(function () { return { ok: false, status: 0, message: 'אין חיבור לרשת. בדקו את החיבור ונסו שוב.' }; });
  }

  // ── what each answer must be ───────────────────────────────────────────────────────────────────────
  function digits(v) { return String(v || '').replace(/\D/g, ''); }
  /** Israel's check digit, the same for a person's ת.ז. and a company's ח.פ./ע.מ. */
  function checkDigitOk(v) {
    var s = digits(v);
    if (!s || s.length > 9) return false;
    while (s.length < 9) s = '0' + s;
    var sum = 0;
    for (var i = 0; i < 9; i++) { var d = +s[i] * ((i % 2) + 1); sum += d > 9 ? d - 9 : d; }
    return sum % 10 === 0;
  }
  function phoneNorm(v) {
    var s = digits(v);
    if (s.indexOf('972') === 0) s = '0' + s.slice(3);
    return s;
  }
  var CHECK = {
    id_number: function (v) { return checkDigitOk(v) ? '' : 'מספר הזהות אינו תקין — בדקו את 9 הספרות'; },
    // a company's number: nine digits, and no more is demanded — its check digit is not proven for every registry
    // (research 01, §6), so a wrong one is pointed at in WARN, never a wall
    company_number: function (v) { return /^\d{8,9}$/.test(digits(v)) ? '' : 'כתבו את 9 הספרות של המספר'; },
    phone: function (v) { return /^0(5\d|7\d|[2-489])\d{7}$/.test(phoneNorm(v)) ? '' : 'מספר הטלפון אינו תקין'; },
    email: function (v) { return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(String(v).trim()) ? '' : 'כתובת הדוא״ל אינה תקינה'; },
    name: function (v) { return String(v).trim().length >= 2 ? '' : 'כתבו שם מלא'; },
    number: function (v) { return /^-?\d+([.,]\d+)?$/.test(String(v).trim()) ? '' : 'כתבו מספר'; }
  };
  function problem(f, v) {
    var empty = v == null || v === '' || v === false;
    if (empty) return f.required ? (f.type === 'checkbox' ? 'יש לסמן כדי להמשיך' : 'זה שדה חובה') : '';
    return CHECK[f.type] ? CHECK[f.type](v) : '';
  }
  /** What is worth a second look but does not stop anyone. */
  var WARN = {
    company_number: function (v) { return checkDigitOk(v) ? '' : 'ספרת הביקורת לא מתאימה. כדאי לבדוק את המספר שוב.'; }
  };
  function hint(f, v) { return v && WARN[f.type] && !problem(f, v) ? WARN[f.type](v) : ''; }
  /** What a value looks like where it is drawn on the page. */
  function shown(f, v) {
    if (v == null || v === '') return '';
    if (f.type === 'date') return dateHe(v);
    if (f.type === 'checkbox') return v ? '✓' : '';
    if (f.type === 'phone') return phoneNorm(v).replace(/^(\d{3})(\d+)$/, '$1-$2');
    return String(v);
  }

  // ── the steps of the side this browser took ────────────────────────────────────────────────────────
  function steps() {
    var mine = fieldsOf(S.me).filter(asks), out = [], by = {};
    mine.forEach(function (f) {
      var g = f.group || '';
      if (!(g in by)) { by[g] = out.length; out.push({ title: g, fields: [] }); }
      out[by[g]].fields.push(f);
    });
    // no groups named by the office: up to three questions to a screen, so a short form is one screen
    if (out.length === 1 && !out[0].title && out[0].fields.length > 3) {
      var all = out[0].fields; out = [];
      for (var i = 0; i < all.length; i += 3) out.push({ title: '', fields: all.slice(i, i + 3) });
    }
    return out;
  }
  function totalSteps() { return steps().length + 2; }       // the questions, the check, the signature

  // ── rendering ──────────────────────────────────────────────────────────────────────────────────────
  // the office's mark beside «הלשכה הדיגיטלית» (DGO-1846): the page's own <template>, kept identical to the brand by G27
  var BRAND = (document.getElementById('fill-brand') || {}).innerHTML || '';
  function top() {
    var name = S.office.name ? '<span>' + esc(S.office.name) + '</span>' : '';
    // what the last tap answered, under the band of EVERY view (it was drawn on the signing view only, so a refused
    // side, a lost connection or a side taken elsewhere looked like a tap that did nothing — the second reader)
    var note = S.note && S.view !== 'sign'    // the signing view says it by its button, where a phone's eye is
      ? '<div class="f-note warn" role="alert">' + ic('info') + '<div>' + esc(S.note) + '</div></div>' : '';
    return '<header class="f-top"><div class="who">' + name + (BRAND ? '<span class="dgo">' + BRAND + '</span>' : '') + '</div>' +
      '<div class="lock" title="הקישור פותח את המסמך הזה בלבד">' + ic('lock') + 'קישור אישי ומאובטח</div></header>' + note;
  }
  function docCard() {
    var n = (S.ev.pages || []).length;
    return '<section class="f-doc"><div class="thumb"><img alt="" src="' + esc(pageSrc(1)) + '" loading="lazy"></div><div>' +
      '<h1>' + esc(S.ev.title || S.ev.doc_name) + '</h1>' +
      '<p class="meta">' + (S.ev.sender ? 'נשלח על ידי ' + esc(S.ev.sender) : '') +
      (S.ev.expires ? ' · בתוקף עד ' + esc(dateHe(S.ev.expires)) : '') + '</p>' +
      '<button type="button" class="f-link" data-act="sheet">' + ic('eye') + 'צפייה במסמך' +
      (n ? ' (' + (n === 1 ? 'עמוד אחד' : n + ' עמודים') + ')' : '') +   // one is said as one (G89)
      '</button></div></section>';
  }
  function pill(p) {
    if (p.state === 'signed') return '<span class="f-pill done">' + ic('check') + 'נחתם' + (p.signed_at ? ' · ' + esc(when(p.signed_at)) : '') + '</span>';
    if (S.me === p.id) return '<span class="f-pill mine">התחלתם כאן · להמשך</span>';
    if (p.state === 'filling') return '<span class="f-pill busy">בתהליך מילוי</span>';
    if (p.blocked) return '<span class="f-pill wait">יחתום אחרי ' + esc(p.blocked) + '</span>';
    return '<span class="f-pill wait">ממתין לחתימה</span>';
  }
  function partyCard(p) {
    var off = p.state === 'signed' || !!p.blocked;
    var who = p.state === 'signed' && p.signer ? 'חתם/ה: ' + p.signer : (p.note || '');
    return '<li><button type="button" class="f-party" data-act="pick" data-id="' + esc(p.id) + '" data-p="' + pno(p) + '"' +
      (off ? ' aria-disabled="true"' : '') + '><span class="dot" aria-hidden="true"></span><span class="txt">' +
      '<span class="name">' + esc(p.label) + '</span><span class="note">' + esc(who) + '</span>' + pill(p) + '</span>' +
      (off ? '' : '<span class="go">' + ic('fwd') + '</span>') + '</button></li>';
  }
  function complete() { return S.ev.status === 'complete'; }
  function homeView() {
    var left = S.parties.filter(function (p) { return p.state !== 'signed'; }).length;
    var mineCount = 0;
    var h = top() + docCard();
    if (complete()) {
      // the copy is offered when it IS ready: «complete» is also the moment it is being made, or a moment it failed
      h += S.ev.final_ready
        ? '<div class="f-note">' + ic('check') + '<div><b>המסמך נחתם בידי כל הצדדים.</b> העותק החתום, עם תעודת החתימה, מוכן להורדה.</div></div>'
        : S.ev.final_failed
          ? '<div class="f-note warn">' + ic('info') + '<div><b>כל הצדדים חתמו.</b> העותק החתום מתעכב, והלשכה כבר יודעת על כך. הוא יופיע כאן, בקישור הזה.</div></div>'
          : '<div class="f-note">' + ic('info') + '<div><b>כל הצדדים חתמו.</b> מכינים את העותק החתום עם תעודת החתימה. זה לוקח כמה שניות…</div></div>';
    } else if (S.ev.status === 'closed') {
      h += '<div class="f-note bad">' + ic('alert') + '<div>הקישור הזה נסגר, ולא ניתן לחתום בו עוד.</div></div>';
    }
    h += '<h2 class="f-h2">' + (complete() ? 'החותמים' : 'מי אתם במסמך הזה?') + '</h2>';
    if (!complete()) h += '<p class="f-lead">בחרו את הצד שלכם. תמלאו רק את הפרטים שלו, ותחתמו במקום שלו במסמך.</p>';
    h += '<ul class="f-parties">' + S.parties.map(partyCard).join('') + '</ul>';
    if (!complete() && left) {
      S.fields.forEach(function (f) { if (asks(f)) mineCount++; });
      h += '<div class="f-how"><div><b>1 · בוחרים צד</b>מי אתם במסמך</div><div><b>2 · ממלאים</b>רק את הפרטים שלכם</div>' +
        '<div><b>3 · חותמים</b>במקום שלכם במסמך</div></div>';
    }
    h += '<p class="f-foot">' + (S.office.name ? esc(S.office.name) + ' שלח/ה לכם את הקישור הזה. ' : '') +
      'הפרטים שתמלאו נשמרים רק לצורך המסמך הזה ותעודת החתימה שלו.</p>';
    return h;
  }
  function sideHead(n) {
    var p = party(S.me);
    var bars = '';
    for (var i = 0; i < totalSteps(); i++) bars += '<i class="' + (i <= n ? 'on' : '') + '"></i>';
    return top() + '<div class="f-side" data-p="' + pno(p) + '"><span class="sw"></span>' +
      'ממלאים בשם <b>' + esc(p.label) + '</b>' + (p.note ? ' · ' + esc(p.note) : '') + '</div>' +
      '<div class="f-prog" aria-hidden="true">' + bars + '</div>' +
      '<p class="f-step">שלב ' + (n + 1) + ' מתוך ' + totalSteps() + '</p>';
  }
  function input(f) {
    var v = S.values[f.id] == null ? '' : S.values[f.id];
    var id = 'q-' + f.id, err = S.errors[f.id];
    var attrs = ' id="' + id + '" name="' + esc(f.id) + '" data-field="' + esc(f.id) + '"' +
      (err ? ' aria-invalid="true" aria-describedby="' + id + '-e"' : '') + (f.required ? ' required' : '');
    var ctl;
    switch (f.type) {
      case 'name': ctl = '<input type="text" dir="auto" autocomplete="name"' + attrs + ' value="' + esc(v) + '">'; break;
      case 'id_number': case 'company_number':
        ctl = '<input type="text" class="ltr" inputmode="numeric" pattern="[0-9]*" maxlength="9" autocomplete="off"' + attrs + ' value="' + esc(v) + '">'; break;
      case 'phone': ctl = '<input type="tel" class="ltr" inputmode="tel" autocomplete="tel"' + attrs + ' value="' + esc(v) + '">'; break;
      case 'email': ctl = '<input type="email" class="ltr" inputmode="email" autocomplete="email" spellcheck="false"' + attrs + ' value="' + esc(v) + '">'; break;
      case 'date': ctl = '<input type="date"' + attrs + ' value="' + esc(v) + '">'; break;
      case 'number': ctl = '<input type="text" class="ltr" inputmode="decimal"' + attrs + ' value="' + esc(v) + '">'; break;
      case 'textarea': ctl = '<textarea' + attrs + '>' + esc(v) + '</textarea>'; break;
      case 'checkbox':
        return '<div class="f-q' + (err ? ' bad' : '') + '"><label class="f-check"><input type="checkbox"' + attrs + (v ? ' checked' : '') + '>' +
          '<span>' + esc(f.label) + (f.required ? '' : ' <span class="opt">(לא חובה)</span>') + '</span></label>' + why(id, err) + '</div>';
      case 'choice':
        ctl = '<div class="f-choice" role="radiogroup">' + (f.options || []).map(function (o, i) {
          return '<label><input type="radio" name="' + esc(f.id) + '" data-field="' + esc(f.id) + '" value="' + esc(o) + '"' +
            (v === o ? ' checked' : '') + '>' + esc(o) + '</label>';
        }).join('') + '</div>'; break;
      default:
        ctl = '<input type="text" dir="auto" autocomplete="' + esc(f.autocomplete || 'off') + '"' + attrs + ' value="' + esc(v) + '">';
    }
    var w = !err && hint(f, v);
    return '<div class="f-q' + (err ? ' bad' : '') + '"><label for="' + id + '">' + esc(f.label) +
      (f.required ? '' : ' <span class="opt">(לא חובה)</span>') + '</label>' +
      (f.help ? '<span class="help">' + esc(f.help) + '</span>' : '') + ctl + why(id, err) +
      (w ? '<p class="why soft" id="' + id + '-w">' + ic('info') + esc(w) + '</p>' : '') + '</div>';
  }
  function why(id, err) { return err ? '<p class="why" id="' + id + '-e" role="alert">' + ic('alert') + esc(err) + '</p>' : ''; }
  function qView() {
    var st = steps()[S.step];
    var h = sideHead(S.step);
    if (S.took) h += '<div class="f-note warn">' + ic('info') + '<div>' + esc(S.took) + '</div></div>';
    h += '<h2 class="f-title" tabindex="-1">' + esc(st.title || (S.step ? 'עוד כמה פרטים' : 'הפרטים שלכם למסמך')) + '</h2>';
    if (!S.step) h += '<p class="f-sub">מה שתכתבו יופיע במסמך, בדיוק במקום שלו. אפשר לבדוק הכול לפני החתימה.</p>';
    h += '<form id="q" novalidate>' + st.fields.map(input).join('') + '</form>';
    return h;
  }
  function boxHtml(f, p, mineNow) {
    var v = S.values[f.id], cls = 'f-box', inner = '';
    var isMine = mineNow && f.party === S.me;
    if (f.type === 'signature' || f.type === 'initials') {
      var img = isMine ? S.sig : f.image;
      if (img) { cls += ' sig'; inner = '<img alt="חתימה" src="' + esc(img) + '">'; }
      else if (isMine || p.state !== 'signed') { cls += ' todo'; inner = '<span>' + (isMine ? 'כאן חותמים' : esc(p.label)) + '</span>'; }
    } else if (f.type === 'date_signed') {
      var d = f.value || (isMine ? today() : '');
      if (d) inner = '<span>' + esc(d) + '</span>';
    } else {
      var val = isMine ? shown(f, v) : (f.value == null ? '' : shown(f, f.value));
      if (val) inner = '<span>' + esc(val) + '</span>';
      else if (isMine && f.required) { cls += ' todo'; inner = '<span>' + esc(f.label) + '</span>'; }
    }
    if (isMine) cls += ' mine';
    if (!inner) return '';
    return '<div class="' + cls + '" data-p="' + pno(p) + '" data-box="' + f.box.join(',') + '" title="' + esc(f.label) + '">' + inner + '</div>';
  }
  function pageHtml(n, mineNow) {
    var boxes = S.fields.filter(function (f) { return f.page === n && f.box; }).map(function (f) {
      return boxHtml(f, party(f.party), mineNow);
    }).join('');
    return '<div class="f-page" data-page="' + n + '"><img alt="עמוד ' + n + ' במסמך" src="' + esc(pageSrc(n)) + '">' +
      boxes + '<span class="pno">עמוד ' + n + '</span></div>';
  }
  /** The part of a page where this side writes and signs, large enough to read on a phone: the page itself, cut to the
   *  side's own boxes and a margin around them (a whole A4 page on a phone is 6-pixel text). */
  function cropHtml(n) {
    var mine = fieldsOf(S.me).filter(function (f) { return f.page === n && f.box; });
    if (!mine.length) return pageHtml(n, true);
    var x0 = 1, y0 = 1, x1 = 0, y1 = 0;
    mine.forEach(function (f) {
      x0 = Math.min(x0, f.box[0]); y0 = Math.min(y0, f.box[1]);
      x1 = Math.max(x1, f.box[0] + f.box[2]); y1 = Math.max(y1, f.box[1] + f.box[3]);
    });
    // the margin takes in what names the place on the page (a card's title above, the label under a line)
    x0 = Math.max(0, x0 - 0.07); x1 = Math.min(1, x1 + 0.07); y0 = Math.max(0, y0 - 0.08); y1 = Math.min(1, y1 + 0.05);
    var pg = (S.ev.pages || [])[n - 1] || { w: 595, h: 842 }, cw = x1 - x0, ch = y1 - y0;
    return '<div class="f-crop" data-crop="' + [x0, y0, cw, ch].join(',') + '" data-ratio="' + (cw * pg.w) / (ch * pg.h) + '">' +
      pageHtml(n, true) + '</div>';
  }
  function myPages() {
    var seen = {};
    fieldsOf(S.me).forEach(function (f) { if (f.box) seen[f.page] = 1; });
    return Object.keys(seen).map(Number).sort(function (a, b) { return a - b; });
  }
  function reviewView() {
    var n = steps().length, asked = fieldsOf(S.me).filter(asks);
    var h = sideHead(n) + (asked.length
      ? '<h2 class="f-title" tabindex="-1">כך זה ייראה במסמך</h2>' +
        '<p class="f-sub">הפרטים שלכם מסומנים במסמך עצמו. אם משהו לא נכון, אפשר לתקן לפני החתימה.</p>'
      : '<h2 class="f-title" tabindex="-1">המקום שלכם במסמך</h2>' +
        '<p class="f-sub">כאן תופיע החתימה בשם ' + esc(party(S.me).label) + '. בשלב הבא חותמים.</p>');
    h += '<div class="f-pages">' + myPages().map(cropHtml).join('') + '</div>';
    if (myPages().length) h += '<p class="f-more"><button type="button" class="f-link" data-act="sheet">' + ic('eye') + 'הצגת המסמך כולו</button></p>';
    if (!asked.length) return h;
    h += '<ul class="f-sum">' + asked.map(function (f) {
      var v = shown(f, S.values[f.id]), ltr = /^(email|phone|id_number|company_number|number)$/.test(f.type);
      return '<li><span class="k">' + esc(f.label) + '</span><span class="v"' + (ltr ? ' dir="ltr"' : '') + '>' +
        (v ? esc(v) : '<span class="opt">לא מולא</span>') + '</span>' +
        '<button type="button" class="f-link e" data-act="edit" data-id="' + esc(f.id) + '" aria-label="שינוי: ' + esc(f.label) + '">' + ic('edit') + 'שינוי</button></li>';
    }).join('') + '</ul>';
    return h;
  }
  function signView() {
    var n = steps().length + 1, p = party(S.me);
    var sigField = fieldsOf(S.me).filter(function (f) { return f.type === 'signature'; })[0] || {};
    var stampable = /חותמת/.test(sigField.label || '');
    var h = sideHead(n) + '<h2 class="f-title" tabindex="-1">החתימה שלכם</h2>' +
      '<p class="f-sub">החתימה תופיע במסמך במקום «' + esc(sigField.label || 'חתימה') + '» של ' + esc(p.label) + '.</p>';
    h += '<div class="f-tabs" role="tablist"><button type="button" role="tab" data-act="mode" data-mode="draw" aria-selected="' + (S.mode === 'draw') + '">' +
      'ציור באצבע</button><button type="button" role="tab" data-act="mode" data-mode="type" aria-selected="' + (S.mode === 'type') + '">הקלדת השם</button></div>';
    if (S.mode === 'draw') {
      h += '<div class="f-pad' + (S.sig ? ' inked' : '') + '" id="pad"><canvas aria-label="משטח חתימה: חתמו באצבע או בעכבר"></canvas>' +
        '<span class="x" aria-hidden="true">✕</span><span class="base" aria-hidden="true"></span><span class="hint">חתמו כאן באצבע</span></div>' +
        '<div class="f-padbar"><button type="button" class="f-link" data-act="undo">' + ic('undo') + 'ביטול הקו האחרון</button>' +
        '<button type="button" class="f-link" data-act="clear">' + ic('x') + 'ניקוי</button></div>';
    } else {
      h += '<div class="f-q f-typed"><label for="typed">השם שלכם, כפי שיופיע כחתימה</label><input type="text" id="typed" autocomplete="name" value="' + esc(S.typed) + '"></div>' +
        '<div class="f-pad inked" id="typedpad"><canvas aria-hidden="true"></canvas></div><div class="f-padbar"><span>כך תיראה החתימה במסמך</span><span></span></div>';
    }
    if (stampable) {
      h += '<div class="f-q"><label for="stamp">חותמת העסק <span class="opt">(לא חובה)</span></label>' +
        '<span class="help">צלמו את החותמת על דף לבן. היא תופיע ליד החתימה.</span>' +
        '<label class="f-btn ghost f-wide" for="stamp">' + ic('camera') + (S.stamp ? 'החלפת החותמת' : 'צילום או בחירת תמונה') + '</label>' +
        '<input type="file" id="stamp" accept="image/*" capture="environment" hidden></div>';
    }
    // where it lands: the side's own part of the page, its signature drawn in as the pad is inked
    var at = myPages();
    if (at.length) h += '<p class="f-step">כך החתימה תיראה במסמך</p><div class="f-pages f-preview">' + cropHtml(at[at.length - 1]) + '</div>';
    h += '<label class="f-consent"><input type="checkbox" id="consent"' + (S.consent ? ' checked' : '') + '><span>' +
      'קראתי את המסמך, ואני מסכים/ה לחתום עליו אלקטרונית בשם ' + esc(p.label) + '. החתימה תיצמד למסמך, ותירשם עם מועד החתימה, ' +
      'כתובת הרשת והמכשיר שממנו נחתם.</span></label>';
    if (S.note) h += '<div class="f-note bad" role="alert">' + ic('alert') + '<div>' + esc(S.note) + '</div></div>';
    return h;
  }
  function doneView() {
    var p = party(S.me) || {};
    var others = S.parties.filter(function (x) { return x.id !== S.me; });
    var h = top() + '<div class="f-done"><div class="ok">' + ic('check') + '</div>' +
      '<h2 tabindex="-1">' + (complete() ? 'המסמך חתום במלואו' : 'נחתם. תודה!') + '</h2>' +
      '<p>חתמתם בשם ' + esc(p.label) + ' על «' + esc(S.ev.title || S.ev.doc_name) + '».</p></div>';
    if (others.length) {
      h += '<ul class="f-left">' + others.map(function (x) {
        return '<li><span>' + esc(x.label) + '</span>' + (x.state === 'signed'
          ? '<span class="f-pill done">' + ic('check') + 'נחתם</span>' : '<span class="f-pill wait">ממתין לחתימה</span>') + '</li>';
      }).join('') + '</ul>';
    }
    if (!complete()) {
      h += '<div class="f-note">' + ic('info') + '<div>כשכל הצדדים יחתמו, העותק החתום יהיה זמין להורדה כאן, בקישור הזה. ' +
        'שמרו את הקישור. אין צורך לעשות דבר נוסף.</div></div>';
    } else if (S.ev.final_failed) {
      h += '<div class="f-note warn">' + ic('info') + '<div>החתימות נשמרו. העותק החתום מתעכב, והלשכה כבר יודעת על כך. ' +
        'הוא יופיע כאן, בקישור הזה.</div></div>';
    } else if (!S.ev.final_ready) {
      h += '<div class="f-note">' + ic('info') + '<div>מכינים את העותק החתום עם תעודת החתימה. זה לוקח כמה שניות…</div></div>';
    }
    return h;
  }
  function sheetHtml() {
    var n = (S.ev.pages || []).length;
    var pages = '';
    for (var i = 1; i <= n; i++) pages += pageHtml(i, !!S.me && S.view !== 'home');
    return '<div class="f-sheet" role="dialog" aria-modal="true" aria-label="המסמך"><div class="hd"><b>' + esc(S.ev.title || S.ev.doc_name) + '</b>' +
      '<button type="button" class="f-btn ghost" data-act="unsheet" aria-label="סגירת המסמך">' + ic('x') + 'סגירה</button></div>' +
      '<div class="f-pages">' + pages + '</div></div>';
  }
  function bar() {
    var b = '';
    if (S.view === 'home') {
      if (complete() && S.ev.final_ready) b = '<a class="f-btn" href="' + esc(BASE) + '/f/final" download>' + ic('dl') + 'הורדת העותק החתום</a>';
      else if (S.me && party(S.me) && party(S.me).state !== 'signed') b = '<button type="button" class="f-btn" data-act="resume">להמשך המילוי ' + ic('fwd') + '</button>';
      else return '';
    } else if (S.view === 'q') {
      b = '<button type="button" class="f-btn ghost" data-act="back" aria-label="חזרה">' + ic('back') + '</button>' +
        '<button type="button" class="f-btn" data-act="next">המשך ' + ic('fwd') + '</button>';
    } else if (S.view === 'review') {
      b = '<button type="button" class="f-btn ghost" data-act="back" aria-label="חזרה">' + ic('back') + '</button>' +
        '<button type="button" class="f-btn" data-act="tosign">לחתימה ' + ic('fwd') + '</button>';
    } else if (S.view === 'sign') {
      b = '<button type="button" class="f-btn ghost" data-act="back" aria-label="חזרה">' + ic('back') + '</button>' +
        '<button type="button" class="f-btn" data-act="sign"' + (S.busy ? ' disabled' : '') + '>' +
        (S.busy ? '<span class="spin" aria-hidden="true"></span>חותמים…' : ic('edit') + 'חתימה על המסמך') + '</button>';
    } else if (S.view === 'done') {
      b = complete() && S.ev.final_ready
        ? '<a class="f-btn" href="' + esc(BASE) + '/f/final" download>' + ic('dl') + 'הורדת העותק החתום</a>'
        : '<button type="button" class="f-btn ghost f-wide" data-act="sheet">' + ic('eye') + 'צפייה במסמך שחתמתם</button>';
    }
    return '<div class="f-bar"><div class="in">' + b + '</div></div>';
  }

  var pad = null;
  function render(focus) {
    var body = S.view === 'home' ? homeView() : S.view === 'q' ? qView() : S.view === 'review' ? reviewView()
      : S.view === 'sign' ? signView() : doneView();
    root.innerHTML = body + bar() + (S.sheet ? sheetHtml() : '');
    placeBoxes();
    if (S.view === 'sign') wireSign();
    if (focus) {
      var t = root.querySelector(S.sheet ? '.f-sheet .f-btn' : '.f-title,.f-done h2,.f-h2');
      if (t) { if (!t.hasAttribute('tabindex')) t.setAttribute('tabindex', '-1'); t.focus({ preventScroll: true }); }
      window.scrollTo(0, 0);
    }
  }
  /** A box's place on its page: fractions of the page from its top-left corner, and a text size from the box's height
   *  that then shrinks until the text fits the box's width — a value is never cut. A crop shows a part of its page:
   *  the page is drawn larger, moved so the part fills the frame. */
  function placeBoxes() {
    Array.prototype.forEach.call(root.querySelectorAll('.f-crop'), function (cr) {
      var c = cr.getAttribute('data-crop').split(',').map(Number), pg = cr.querySelector('.f-page');
      cr.style.aspectRatio = String(cr.getAttribute('data-ratio'));
      pg.style.width = (100 / c[2]) + '%';
      pg.style.left = (-c[0] / c[2] * 100) + '%';
      pg.style.top = (-c[1] / c[3] * 100) + '%';
    });
    Array.prototype.forEach.call(root.querySelectorAll('.f-page'), function (pg) {
      var img = pg.querySelector('img');
      var size = function () {
        var hpx = img.clientHeight || 0;
        Array.prototype.forEach.call(pg.querySelectorAll('.f-box'), function (el) {
          var b = el.getAttribute('data-box').split(',').map(Number);
          el.style.left = (b[0] * 100) + '%'; el.style.top = (b[1] * 100) + '%';
          el.style.width = (b[2] * 100) + '%'; el.style.height = (b[3] * 100) + '%';
          var fs = Math.max(6, Math.min(b[3] * hpx * 0.66, 40)), sp = el.querySelector('span');
          el.style.fontSize = fs + 'px';
          if (sp && el.clientWidth) {
            for (var i = 0; i < 12 && sp.scrollWidth > el.clientWidth && fs > 6; i++) {
              fs = Math.max(6, fs * el.clientWidth / sp.scrollWidth * 0.97); el.style.fontSize = fs + 'px';
            }
          }
        });
      };
      if (img.complete && img.naturalWidth) size(); else img.addEventListener('load', size);
      pg._size = size;
    });
  }
  window.addEventListener('resize', function () {
    Array.prototype.forEach.call(root.querySelectorAll('.f-page'), function (pg) { if (pg._size) pg._size(); });
  });

  /** Two inks, read at run time. On the PAD the screen's own ink (--ink), so a hand shows on a dark pad too; in the
   *  picture that goes on the PAGE paper's ink (--paper-ink, the same in every theme), so the preview over the white
   *  page shows it — and the server keeps every hand in its print ink whatever arrives (the second reader, round 2:
   *  paper's ink on a dark pad drew an invisible hand). */
  function ink() {
    return (getComputedStyle(root).getPropertyValue('--ink') || '').trim() || getComputedStyle(document.body).color;
  }
  function paperInk() {
    return (getComputedStyle(root).getPropertyValue('--paper-ink') || '').trim() || ink();
  }
  // ── the signature pad: strokes, smoothed, on a canvas sized to the device's pixels ─────────────────
  /** Strokes are kept in CSS pixels of the pad and drawn scaled to its device pixels, so a pad that changes size (the
   *  phone turned) redraws the same hand, neither stretched nor cut (the second reader). */
  function Pad(canvas, onInk) {
    var ctx = canvas.getContext('2d'), strokes = [], cur = null, dpr = Math.max(1, window.devicePixelRatio || 1);
    function fit() {
      var r = canvas.getBoundingClientRect();
      canvas.width = Math.round(r.width * dpr); canvas.height = Math.round(r.height * dpr);
      redraw();
    }
    function pt(e) { var r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
    function line(s, g, k, color) {
      g = g || ctx; k = k || dpr;
      g.lineWidth = 2.6 * k; g.lineCap = 'round'; g.lineJoin = 'round';
      g.strokeStyle = color || ink();
      g.beginPath(); g.moveTo(s[0][0] * k, s[0][1] * k);
      if (s.length === 1) { g.lineTo(s[0][0] * k + 0.1, s[0][1] * k + 0.1); }
      for (var i = 1; i < s.length - 1; i++) {
        var mx = (s[i][0] + s[i + 1][0]) / 2, my = (s[i][1] + s[i + 1][1]) / 2;
        g.quadraticCurveTo(s[i][0] * k, s[i][1] * k, mx * k, my * k);
      }
      if (s.length > 1) g.lineTo(s[s.length - 1][0] * k, s[s.length - 1][1] * k);
      g.stroke();
    }
    function redraw() { ctx.clearRect(0, 0, canvas.width, canvas.height); strokes.forEach(function (s) { line(s); }); }
    canvas.addEventListener('pointerdown', function (e) {
      e.preventDefault();
      try { canvas.setPointerCapture(e.pointerId); } catch (x) { /* a pointer the browser no longer tracks: ink anyway */ }
      cur = [pt(e)]; strokes.push(cur); redraw();
    });
    canvas.addEventListener('pointermove', function (e) { if (!cur) return; e.preventDefault(); cur.push(pt(e)); redraw(); });
    function end() { if (cur) { cur = null; onInk(strokes.length ? png() : null); } }
    canvas.addEventListener('pointerup', end); canvas.addEventListener('pointercancel', end);
    /** The ink only, cropped to what was drawn, in paper's ink on transparent: the PDF draws it in the signature's
     *  box (drawn at twice the CSS size, whatever the screen, so every hand reaches the server the same). */
    function png() {
      var xs = [], ys = [], k = 2;
      strokes.forEach(function (s) { s.forEach(function (p) { xs.push(p[0]); ys.push(p[1]); }); });
      if (!xs.length) return null;
      var m = 6, x0 = Math.max(0, Math.min.apply(null, xs) - m), y0 = Math.max(0, Math.min.apply(null, ys) - m);
      var x1 = Math.max.apply(null, xs) + m, y1 = Math.max.apply(null, ys) + m;
      var out = document.createElement('canvas');
      out.width = Math.max(1, Math.round((x1 - x0) * k)); out.height = Math.max(1, Math.round((y1 - y0) * k));
      var o = out.getContext('2d');
      o.translate(-x0 * k, -y0 * k);
      var paper = paperInk();
      strokes.forEach(function (s) { line(s, o, k, paper); });
      return out.toDataURL('image/png');
    }
    this.clear = function () { strokes = []; redraw(); onInk(null); };
    this.undo = function () { strokes.pop(); redraw(); onInk(strokes.length ? png() : null); };
    this.fit = fit;
    this.canvas = canvas;
    fit();
  }
  window.addEventListener('resize', function () { if (pad && root.contains(pad.canvas)) pad.fit(); });
  /** A typed name drawn as a signature, a hand's slant: shown on the pad in the screen's ink, sent in paper's ink. */
  function typedPng(text, canvas) {
    var dpr = Math.max(1, window.devicePixelRatio || 1), r = canvas.getBoundingClientRect();
    canvas.width = Math.round(r.width * dpr); canvas.height = Math.round(r.height * dpr);
    var c = canvas.getContext('2d');
    c.clearRect(0, 0, canvas.width, canvas.height);
    if (!text.trim()) return null;
    var family = getComputedStyle(root).fontFamily, size = 54 * dpr;
    c.font = '500 ' + size + 'px Heebo, ' + family;
    while (c.measureText(text).width > canvas.width * 0.86 && size > 18) { size -= 2; c.font = '500 ' + size + 'px Heebo, ' + family; }
    var draw = function (g, color) {
      g.font = '500 ' + size + 'px Heebo, ' + family;
      g.fillStyle = color;
      g.textAlign = 'center'; g.textBaseline = 'alphabetic'; g.direction = 'rtl';
      g.setTransform(1, 0, -0.18, 1, canvas.height * 0.1, 0);
      g.fillText(text, canvas.width / 2, canvas.height * 0.62);
      g.setTransform(1, 0, 0, 1, 0, 0);
    };
    draw(c, ink());
    var paper = document.createElement('canvas');
    paper.width = canvas.width; paper.height = canvas.height;
    draw(paper.getContext('2d'), paperInk());
    var w = Math.ceil(c.measureText(text).width) + 30 * dpr;
    var out = document.createElement('canvas'); out.width = Math.min(canvas.width, w); out.height = Math.round(size * 1.5);
    out.getContext('2d').drawImage(paper, (canvas.width - out.width) / 2, canvas.height * 0.62 - size * 1.05, out.width, out.height, 0, 0, out.width, out.height);
    return out.toDataURL('image/png');
  }
  function wireSign() {
    if (S.mode === 'draw') {
      var cv = root.querySelector('#pad canvas');
      pad = new Pad(cv, function (img) {
        S.sig = img; root.querySelector('#pad').classList.toggle('inked', !!img); S.note = null; preview();
      });
    } else {
      var t = root.querySelector('#typed'), tc = root.querySelector('#typedpad canvas');
      var draw = function () { S.typed = t.value; S.sig = typedPng(t.value, tc); preview(); };
      t.addEventListener('input', draw); draw();
    }
    var c = root.querySelector('#consent');
    if (c) c.addEventListener('change', function () { S.consent = c.checked; });
    var st = root.querySelector('#stamp');
    if (st) st.addEventListener('change', function () {
      var f = st.files && st.files[0];
      if (!f) return;
      shrink(f, 600, function (url) { S.stamp = url; render(false); });
    });
  }
  /** The preview under the pad follows the ink: the same boxes, redrawn with the signature as it is now. */
  function preview() {
    var box = root.querySelector('.f-preview');
    if (!box) return;
    var at = myPages();
    box.innerHTML = cropHtml(at[at.length - 1]);
    placeBoxes();
  }
  /** A photo of a stamp, made small enough to send from a phone. */
  function shrink(file, max, done) {
    var r = new FileReader();
    r.onload = function () {
      var im = new Image();
      im.onload = function () {
        var k = Math.min(1, max / Math.max(im.width, im.height)), cv = document.createElement('canvas');
        cv.width = Math.round(im.width * k); cv.height = Math.round(im.height * k);
        cv.getContext('2d').drawImage(im, 0, 0, cv.width, cv.height);
        done(cv.toDataURL('image/jpeg', 0.85));
      };
      im.src = r.result;
    };
    r.readAsDataURL(file);
  }

  // ── moving through it ──────────────────────────────────────────────────────────────────────────────
  function readForm() {
    var form = root.querySelector('#q');
    if (!form) return;
    Array.prototype.forEach.call(form.querySelectorAll('[data-field]'), function (el) {
      var id = el.getAttribute('data-field');
      if (el.type === 'checkbox') S.values[id] = el.checked;
      else if (el.type === 'radio') { if (el.checked) S.values[id] = el.value; }
      else S.values[id] = el.value.trim();
    });
  }
  function validStep() {
    readForm();
    S.errors = {};
    var ok = true;
    steps()[S.step].fields.forEach(function (f) {
      var e = problem(f, S.values[f.id]);
      if (e) { S.errors[f.id] = e; ok = false; }
    });
    return ok;
  }
  /** A question on the page itself (never the browser's prompt): a title, a sentence, maybe one field to type in. */
  function ask(o) {
    return new Promise(function (resolve) {
      var d = document.createElement('div');
      d.className = 'f-modal';
      d.innerHTML = '<div class="f-dlg" role="dialog" aria-modal="true" aria-labelledby="f-dlg-t" dir="rtl">' +
        '<h2 id="f-dlg-t">' + esc(o.title) + '</h2>' + (o.body ? '<p>' + esc(o.body) + '</p>' : '') +
        (o.input ? '<div class="f-q"><label for="f-dlg-i">' + esc(o.input) + '</label><input id="f-dlg-i" type="text" ' +
          'class="ltr" inputmode="numeric" autocomplete="one-time-code" maxlength="8"></div>' : '') +
        (o.error ? '<p class="why" role="alert">' + ic('alert') + esc(o.error) + '</p>' : '') +
        '<div class="f-dlg-acts"><button type="button" class="f-btn" data-v="ok">' + esc(o.ok || 'אישור') + '</button>' +
        '<button type="button" class="f-btn ghost" data-v="no">' + esc(o.cancel || 'ביטול') + '</button></div></div>';
      document.body.appendChild(d);
      var inp = d.querySelector('input');
      (inp || d.querySelector('[data-v=ok]')).focus();
      var done = function (v) { d.remove(); resolve(v); };
      d.addEventListener('click', function (e) {
        var b = e.target.closest('[data-v]');
        if (b) done(b.getAttribute('data-v') === 'ok' ? (inp ? inp.value.trim() : true) : null);
        else if (e.target === d) done(null);
      });
      d.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') done(null);
        if (e.key === 'Enter') { e.preventDefault(); done(inp ? inp.value.trim() : true); }
      });
    });
  }
  function pick(id, code, take) {
    var p = party(id);
    if (!p || p.state === 'signed' || p.blocked || S.busy) return;
    if (S.me === id && !code && !take) return resume();
    S.busy = true;
    api('/f/claim', { party: id, code: code || '', take: !!take }).then(function (r) {
      S.busy = false;
      if (r.need_code) {
        return ask({ title: 'קוד אישי', body: 'הצד «' + p.label + '» מוגן בקוד שהלשכה מסרה לכם בנפרד מהקישור.',
          input: 'הקוד', ok: 'המשך', error: code ? r.message : '' }).then(function (c) { if (c) pick(id, c, take); });
      }
      if (r.busy) {
        return ask({ title: 'הצד הזה פתוח במכשיר אחר', ok: 'להמשיך כאן', cancel: 'חזרה',
          body: 'מישהו התחיל למלא את הצד «' + p.label + '» לפני כמה דקות. אם זה אתם, ממכשיר אחר, אפשר להמשיך כאן. ' +
            'מה שמולא שם לא יעבור לכאן.' }).then(function (yes) { if (yes) pick(id, code, true); });
      }
      if (!r.ok) { flash(r.message || 'לא ניתן לבחור את הצד הזה כרגע.'); return; }
      S.me = id; S.values = {}; S.errors = {}; S.note = null;
      S.took = r.took_over ? 'הצד הזה נפתח קודם במכשיר אחר. ממשיכים כאן, מההתחלה.' : null;
      (r.values || []).forEach(function (v) { S.values[v.field] = v.value; });
      if (r.parties) S.parties = r.parties;
      resume();
    });
  }
  /** The side was taken on another device meanwhile: back to the sides, saying so. */
  function lost(r) {
    if (!r || !r.lost) return false;
    S.me = null; S.view = 'home'; S.note = null;
    render(true);
    flash(r.message || 'הצד הזה נפתח במכשיר אחר. בחרו אותו שוב כדי להמשיך.');
    return true;
  }
  function resume() {
    S.step = 0;
    var st = steps();
    for (var i = 0; i < st.length; i++) {
      if (st[i].fields.some(function (f) { return problem(f, S.values[f.id]); })) { S.step = i; break; }
      S.step = i + 1;
    }
    S.view = S.step < st.length ? 'q' : 'review';
    render(true);
  }
  function save() {
    var v = {};
    fieldsOf(S.me).filter(asks).forEach(function (f) { if (S.values[f.id] != null) v[f.id] = S.values[f.id]; });
    return api('/f/answers', { party: S.me, values: v }).then(function (r) { lost(r); return r; });
  }
  var flashT;
  function flash(msg) {
    S.note = msg; render(false);
    clearTimeout(flashT);
    flashT = setTimeout(function () { if (S.note === msg) { S.note = null; if (S.view === 'home') render(false); } }, 8000);
  }
  function next() {
    if (!validStep()) { render(false); var b = root.querySelector('[aria-invalid="true"]'); if (b) b.focus(); return; }
    save();                                  // progress kept on the server: another device, or later, continues here
    S.step++;
    S.view = S.step < steps().length ? 'q' : 'review';
    render(true);
  }
  function back() {
    if (S.view === 'q') { readForm(); if (S.step) { S.step--; render(true); } else { S.view = 'home'; render(true); } }
    else if (S.view === 'review') { S.step = Math.max(0, steps().length - 1); S.view = steps().length ? 'q' : 'home'; render(true); }
    else if (S.view === 'sign') { S.view = 'review'; render(true); }
  }
  function sign() {
    if (S.busy) return;
    if (!S.sig) { S.note = S.mode === 'draw' ? 'חתמו בתוך המסגרת, באצבע או בעכבר.' : 'הקלידו את השם שלכם.'; render(false); return; }
    if (!S.consent) { S.note = 'כדי לחתום, סמנו שקראתם את המסמך ושאתם מסכימים לחתום עליו.'; render(false); return; }
    S.busy = true; S.note = null; render(false);
    var v = {};
    fieldsOf(S.me).filter(asks).forEach(function (f) { if (S.values[f.id] != null) v[f.id] = S.values[f.id]; });
    api('/f/sign', { party: S.me, values: v, consent: true,
      signature: { kind: S.mode, image: S.sig, text: S.mode === 'type' ? S.typed : '' }, stamp: S.stamp || null })
      .then(function (r) {
        S.busy = false;
        if (lost(r)) return;
        if (!r.ok) {
          if (r.errors) {
            S.errors = r.errors;
            var st = steps(), at = 0;
            for (var i = 0; i < st.length; i++) if (st[i].fields.some(function (f) { return r.errors[f.id]; })) { at = i; break; }
            S.step = at; S.view = 'q'; render(true); return;
          }
          S.note = r.message || 'החתימה לא נשמרה. נסו שוב בעוד רגע.'; render(false); return;
        }
        if (r.parties) S.parties = r.parties;
        if (r.fields) S.fields = r.fields;
        if (r.event) S.ev = r.event;
        S.view = 'done'; render(true);
        if (!S.ev.final_ready) poll();
      });
  }
  var pollT;
  function poll() {
    clearTimeout(pollT);
    pollT = setTimeout(function () {
      api('/f/state').then(function (r) {
        if (r.parties) S.parties = r.parties;
        if (r.fields) S.fields = r.fields;
        if (r.event) S.ev = r.event;
        // the whole document open on top is not redrawn under the reader (it jumped back to page 1 every 4 s)
        if ((S.view === 'done' || S.view === 'home') && !S.sheet) render(false);
        if (!(S.ev.status === 'complete' && S.ev.final_ready) && document.visibilityState !== 'hidden') poll();
      });
    }, 4000);
  }

  root.addEventListener('click', function (e) {
    var t = e.target.closest('[data-act]');
    if (!t || !root.contains(t)) return;
    var a = t.getAttribute('data-act');
    if (a === 'pick') pick(t.getAttribute('data-id'));
    else if (a === 'resume') resume();
    else if (a === 'next') next();
    else if (a === 'back') back();
    else if (a === 'tosign') { save(); S.view = 'sign'; S.note = null; prefillTyped(); render(true); }
    else if (a === 'edit') {
      var id = t.getAttribute('data-id'), st = steps();
      for (var i = 0; i < st.length; i++) if (st[i].fields.some(function (f) { return f.id === id; })) S.step = i;
      S.view = 'q'; render(true);
      var el = root.querySelector('[data-field="' + id + '"]'); if (el) el.focus();
    }
    else if (a === 'mode') { S.mode = t.getAttribute('data-mode'); S.sig = null; prefillTyped(); render(false); }
    else if (a === 'clear') { if (pad) pad.clear(); }
    else if (a === 'undo') { if (pad) pad.undo(); }
    else if (a === 'sign') sign();
    else if (a === 'sheet') { S.sheet = true; render(false); }
    else if (a === 'unsheet') { S.sheet = false; render(false); }
  });
  /** The name already given is the typed signature's first draft: one tap to confirm it, never typed twice. */
  function prefillTyped() {
    if (S.typed) return;
    var n = fieldsOf(S.me).filter(function (f) { return f.type === 'name'; })[0];
    if (n && S.values[n.id]) S.typed = String(S.values[n.id]);
  }
  /** A field is judged when the person leaves it, never while they type: one field redrawn, the focus where it went. */
  root.addEventListener('focusout', function (e) {
    var el = e.target, id = el && el.getAttribute && el.getAttribute('data-field');
    if (!id || S.view !== 'q' || el.type === 'checkbox' || el.type === 'radio') return;
    var f = S.fields.filter(function (x) { return x.id === id; })[0];
    if (!f) return;
    S.values[id] = el.value.trim();
    var was = S.errors[id] || '', now = S.values[id] ? problem(f, S.values[id]) : '';
    if (now === was && !hint(f, S.values[id])) return;
    if (now) S.errors[id] = now; else delete S.errors[id];
    var box = el.closest('.f-q');
    if (!box) return;
    var tmp = document.createElement('div');
    tmp.innerHTML = input(f);
    box.parentNode.replaceChild(tmp.firstChild, box);
  });
  root.addEventListener('submit', function (e) { e.preventDefault(); next(); });
  root.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && S.sheet) { S.sheet = false; render(false); }
    if (e.key === 'Enter' && S.view === 'q' && e.target.tagName === 'INPUT' && e.target.type !== 'checkbox') { e.preventDefault(); next(); }
  });
  // back on the page (from WhatsApp, the camera, another app): the poll runs again on EVERY view — it is what keeps a
  // side being filled from looking quiet to the next visitor; it redraws only the sides' and the end's views
  document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'visible') poll(); });

  render(false);
  // «opened» is said by a person's browser, never by a GET: WhatsApp's preview bot fetches every link it is sent
  api('/f/seen', { party: S.me || '' });
  if (S.ev.status !== 'complete' || !S.ev.final_ready) poll();
  window.__fill = S;                                      // the simulation's handle; nothing on the page reads it
})();
