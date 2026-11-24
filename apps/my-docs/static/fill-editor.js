/* my-docs — «מילוי וחתימה» (DGO-2139): the office's side of one signing link.
 *
 * From a document's drawer the office opens its pages with the places the document asks for — who signs, what each
 * side fills, where each signature goes — proposed from the document itself and changed here: a question's words, its
 * kind, whose it is, a new place by a tap on the page. «יצירת הקישור» freezes the document and its map into one event
 * in esign and gives ONE link for every side. Self-contained: it needs only window.FillEditor.open(doc) from app.js,
 * and talks to my-docs' own API (api/fill/…), which talks to esign.
 */
(function () {
  'use strict';
  var TYPES = [
    ['name', 'שם מלא'], ['text', 'טקסט'], ['id_number', 'מספר זהות'], ['company_number', 'ח.פ. / ע.מ.'],
    ['phone', 'טלפון'], ['email', 'דוא״ל'], ['date', 'תאריך'], ['number', 'מספר'], ['checkbox', 'סימון ✓'],
    ['choice', 'בחירה מרשימה'], ['signature', 'חתימה'], ['initials', 'ראשי תיבות'], ['date_signed', 'תאריך החתימה']
  ];
  var TYPE_HE = {}; TYPES.forEach(function (t) { TYPE_HE[t[0]] = t[1]; });
  /** a new place's size on its page (fractions of the page), by what it holds */
  var SIZE = { signature: [0.18, 0.05], initials: [0.07, 0.035], date_signed: [0.1, 0.021], checkbox: [0.025, 0.018] };
  var ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return ESC[c]; }); }
  var PATHS = {
    x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    pen: '<path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/>',
    check: '<polyline points="20 6 9 17 4 12"/>', info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
    target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/>', send: '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>'
  };
  function ic(n) { return '<svg class="fe-ic" viewBox="0 0 24 24" aria-hidden="true">' + PATHS[n] + '</svg>'; }
  function call(path, opt) {
    return fetch('api/fill' + path, opt).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { j.status = r.status; return j; });
    }).catch(function () { return { ok: false, status: 0, message: 'אין חיבור לשרת' }; });
  }
  function post(path, body, method) {
    return call(path, { method: method || 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  }

  var E = null, el = null;
  function pidx(pid) { for (var i = 0; i < E.parties.length; i++) if (E.parties[i].id === pid) return i; return 0; }
  function pno(pid) { return (pidx(pid) % 4) + 1; }
  function field(fid) { return E.fields.filter(function (f) { return f.id === fid; })[0]; }
  function uid(p) { return p + Math.random().toString(36).slice(2, 7); }
  function dateHe(iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? m[3] + '.' + m[2] + '.' + m[1] : ''; }

  // ── open: the document's pages and the places proposed from it ──────────────────────────────────────
  function open(doc) {
    close();
    el = document.createElement('div');
    el.className = 'fe-scrim';
    // the preparing card can be left: it waits up to two minutes for the PDF and esign, and had no way out but a
    // reload (the code audit of DGO-2169, A.12) — «ביטול» or Escape closes it, and its answer then draws nothing
    el.innerHTML = '<div class="fe" role="dialog" aria-modal="true" aria-label="מילוי וחתימה" dir="rtl"><div class="fe-load">' +
      '<span class="fe-spin" aria-hidden="true"></span>מכינים את המסמך ומזהים בו את מקומות המילוי והחתימה…' +
      '<button type="button" class="ghost sm" data-fe="close">ביטול</button></div></div>';
    document.body.appendChild(el);
    document.addEventListener('keydown', onKey);
    var mine = el;
    post('/' + encodeURIComponent(doc.id) + '/prepare', {}).then(function (r) {
      if (el !== mine) return;                                       // closed, or another document opened since
      if (!r.ok) { fail(r.message || 'המסמך לא הוכן לחתימה'); return; }
      E = { doc: doc, event: r.event, parties: r.parties || [], fields: r.fields || [], found: r.found || null,
            sel: null, placing: null, link: null, busy: false,
            settings: { expires: r.event.expires || '', order: r.event.order || 'any' } };
      render();
      // the page that holds the places, not the cover: where the office has something to check
      // (by number: a plain sort is by text, and page 10 came before page 2)
      var first = E.fields.filter(function (f) { return f.box; }).map(function (f) { return f.page; })
        .sort(function (a, b) { return a - b; })[0];
      var pg = first && el.querySelector('.fe-page[data-page="' + first + '"]');
      if (pg) {
        var img = pg.querySelector('img'), go = function () { pg.scrollIntoView({ block: 'start' }); };
        if (img.complete) go(); else img.addEventListener('load', go);
      }
    });
  }
  function fail(msg) {
    el.querySelector('.fe').innerHTML = '<div class="fe-load bad">' + ic('info') + esc(msg) +
      '<button type="button" class="ghost sm" data-fe="close">סגירה</button></div>';
  }
  function close() {
    if (el) el.remove();
    el = null; E = null;
    document.removeEventListener('keydown', onKey);
  }
  function onKey(e) {
    if (e.key !== 'Escape') return;
    if (!E) { if (el) close(); return; }                             // (still preparing, or failed: Escape closes)
    if (E.placing) { E.placing = null; render(); } else if (E.sel) { E.sel = null; render(); } else close();
  }

  // ── drawing ─────────────────────────────────────────────────────────────────────────────────────────
  function render() {
    if (!el || !E) return;
    var box = el.querySelector('.fe');
    if (E.link) { box.innerHTML = head() + sent(); return; }
    // a redraw keeps both scrolls where the person left them (the pages jumped back to the cover on every tap)
    var keep = ['.fe-pages', '.fe-side', '.fe-b'].map(function (s) { var n = box.querySelector(s); return n ? n.scrollTop : 0; });
    box.innerHTML = head() + '<div class="fe-b"><aside class="fe-side">' + found() + parties() + settings() + '</aside>' +
      '<section class="fe-pages' + (E.placing ? ' placing' : '') + '" aria-label="דפי המסמך">' + placingBar() + pages() + '</section></div>' + foot();
    ['.fe-pages', '.fe-side', '.fe-b'].forEach(function (s, i) { var n = box.querySelector(s); if (n) n.scrollTop = keep[i]; });
    place();
    var s = E.sel && box.querySelector('.fe-box[data-id="' + E.sel + '"]');
    if (s && E.scrollTo) { s.scrollIntoView({ block: 'center' }); E.scrollTo = false; }
  }
  function head() {
    return '<header class="fe-h"><div><b>מילוי וחתימה</b><span>' + esc(E.event.title || E.doc.doc_number || '') + '</span></div>' +
      '<button type="button" class="ghost sm" data-fe="close" aria-label="סגירה">' + ic('x') + '</button></header>';
  }
  function found() {
    if (!E.found) return '';
    var n = E.fields.filter(function (f) { return f.box; }).length;
    // one is said as one (G89): «צד אחד», «מקום אחד» — never «1 צדדים»
    var one = function (k, single, many) { return k === 1 ? single : k + ' ' + many; };
    return '<div class="fe-found">' + ic('check') + '<div>זיהינו במסמך <b>' + one(E.parties.length, 'צד אחד', 'צדדים') +
      '</b> ו-<b>' + one(n, 'מקום אחד', 'מקומות') + '</b> למילוי ולחתימה' + (E.found.page ? ' (עמוד ' + E.found.page + ')' : '') +
      '. בדקו את השאלות, ושנו מה שצריך.</div></div>';
  }
  function parties() {
    var h = '<h3 class="fe-sec">הצדדים במסמך</h3>';
    h += E.parties.map(function (p, i) {
      var mine = E.fields.filter(function (f) { return f.party === p.id; });
      return '<div class="fe-party" data-p="' + ((i % 4) + 1) + '">' +
        '<div class="fe-ph"><span class="dot" aria-hidden="true"></span>' +
        '<input class="fe-pname" data-pid="' + esc(p.id) + '" data-k="label" value="' + esc(p.label) + '" aria-label="שם הצד">' +
        (E.parties.length > 1 ? '<button type="button" class="fe-iconbtn" data-fe="delparty" data-pid="' + esc(p.id) + '" title="הסרת הצד">' + ic('trash') + '</button>' : '') +
        '</div><input class="fe-pnote" data-pid="' + esc(p.id) + '" data-k="note" value="' + esc(p.note || '') + '" placeholder="למשל: בשם הלקוח" aria-label="הערה לצד">' +
        '<ol class="fe-fields">' + mine.map(row).join('') + '</ol>' +
        '<div class="fe-adds"><button type="button" class="ghost sm" data-fe="add" data-pid="' + esc(p.id) + '" data-type="text">' + ic('plus') + 'שאלה</button>' +
        '<button type="button" class="ghost sm" data-fe="add" data-pid="' + esc(p.id) + '" data-type="signature">' + ic('pen') + 'מקום חתימה</button></div>' +
        '<label class="fe-code"><input type="checkbox" data-fe="code" data-pid="' + esc(p.id) + '"' + (p.code ? ' checked' : '') + '>' +
        'קוד אישי לצד הזה' + (p.code ? ': <bdi class="fe-mono">' + esc(p.code) + '</bdi>' : '') + '</label></div>';
    }).join('');
    h += '<button type="button" class="ghost sm fe-addparty" data-fe="addparty">' + ic('plus') + 'צד נוסף</button>';
    return h;
  }
  function row(f) {
    var on = E.sel === f.id;
    var where = f.box ? 'עמ׳ ' + f.page : 'בשאלון בלבד';
    var r = '<li class="fe-row' + (on ? ' on' : '') + '"><button type="button" class="fe-rowb" data-fe="sel" data-id="' + esc(f.id) + '">' +
      '<span class="t">' + esc(TYPE_HE[f.type] || f.type) + '</span><span class="q">' + esc(f.label) + '</span>' +
      '<span class="w">' + esc(where) + (f.required ? '' : ' · לא חובה') + '</span></button>';
    if (on) r += editor(f);
    return r + '</li>';
  }
  function editor(f) {
    var opts = TYPES.map(function (t) { return '<option value="' + t[0] + '"' + (t[0] === f.type ? ' selected' : '') + '>' + t[1] + '</option>'; }).join('');
    var who = E.parties.map(function (p) { return '<option value="' + esc(p.id) + '"' + (p.id === f.party ? ' selected' : '') + '>' + esc(p.label) + '</option>'; }).join('');
    var asks = !/^(signature|initials|date_signed)$/.test(f.type);
    return '<div class="fe-ed">' +
      '<label>' + (asks ? 'השאלה, כפי שהממלא יראה אותה' : 'שם המקום') + '<input data-fid="' + esc(f.id) + '" data-k="label" value="' + esc(f.label) + '"></label>' +
      (asks ? '<label>הסבר קצר מתחת לשאלה <span class="opt">(לא חובה)</span><input data-fid="' + esc(f.id) + '" data-k="help" value="' + esc(f.help || '') + '"></label>' : '') +
      '<div class="fe-two"><label>סוג<select data-fid="' + esc(f.id) + '" data-k="type">' + opts + '</select></label>' +
      '<label>של מי<select data-fid="' + esc(f.id) + '" data-k="party">' + who + '</select></label></div>' +
      (f.type === 'choice' ? '<label>האפשרויות, אחת בכל שורה<textarea data-fid="' + esc(f.id) + '" data-k="options">' + esc((f.options || []).join('\n')) + '</textarea></label>' : '') +
      '<div class="fe-edfoot"><label class="fe-req"><input type="checkbox" data-fid="' + esc(f.id) + '" data-k="required"' + (f.required ? ' checked' : '') + '>חובה</label>' +
      '<button type="button" class="ghost sm" data-fe="move" data-id="' + esc(f.id) + '">' + ic('target') + (f.box ? 'מיקום אחר במסמך' : 'מיקום במסמך') + '</button>' +
      '<button type="button" class="ghost sm danger-t" data-fe="del" data-id="' + esc(f.id) + '">' + ic('trash') + 'הסרה</button></div></div>';
  }
  function settings() {
    return '<h3 class="fe-sec">הקישור</h3><div class="fe-set">' +
      '<label>בתוקף עד<input type="date" data-set="expires" value="' + esc(E.settings.expires) + '"></label>' +
      '<label>סדר החתימה<select data-set="order"><option value="any"' + (E.settings.order === 'any' ? ' selected' : '') + '>כל צד, מתי שנוח לו</option>' +
      '<option value="seq"' + (E.settings.order === 'seq' ? ' selected' : '') + '>לפי סדר הצדדים</option></select></label></div>';
  }
  function placingBar() {
    if (!E.placing) return '';
    var f = field(E.placing);
    return '<div class="fe-placing" role="status">' + ic('target') + 'לחצו במסמך במקום שבו «' + esc(f ? f.label : '') + '» צריך להופיע' +
      '<button type="button" class="ghost sm" data-fe="unplace">ביטול</button></div>';
  }
  function pages() {
    return (E.event.pages || []).map(function (pg, i) {
      var n = i + 1;
      var boxes = E.fields.filter(function (f) { return f.page === n && f.box; }).map(function (f) {
        return '<div class="fe-box' + (E.sel === f.id ? ' on' : '') + '" data-id="' + esc(f.id) + '" data-p="' + pno(f.party) + '" data-box="' + f.box.join(',') + '" ' +
          'title="' + esc(f.label) + '"><span>' + esc(f.label) + '</span>' + (E.sel === f.id ? '<i class="fe-grip" data-grip="1" aria-hidden="true"></i>' : '') + '</div>';
      }).join('');
      return '<div class="fe-page" data-page="' + n + '"><img alt="עמוד ' + n + '" draggable="false" src="' + esc(pg.src || ('api/fill/event/' + E.event.id + '/page/' + n)) + '">' +
        boxes + '<span class="fe-pno">עמוד ' + n + '</span></div>';
    }).join('');
  }
  function foot() {
    var empty = E.parties.filter(function (p) { return !E.fields.some(function (f) { return f.party === p.id && /^(signature|initials)$/.test(f.type) && f.box; }); });
    var why = empty.length ? 'לצד «' + empty[0].label + '» אין עדיין מקום חתימה במסמך' : '';
    return '<footer class="fe-f"><span class="fe-why">' + esc(why) + '</span>' +
      '<button type="button" class="ghost" data-fe="close">ביטול</button>' +
      '<button type="button" class="primary" data-fe="send"' + (why || E.busy ? ' disabled' : '') + '>' +
      (E.busy ? '<span class="fe-spin" aria-hidden="true"></span>יוצרים…' : ic('link') + 'יצירת קישור למילוי וחתימה') + '</button></footer>';
  }
  function sent() {
    var wa = 'https://wa.me/?text=' + encodeURIComponent((E.event.title || '') + ' — למילוי ולחתימה: ' + E.link);
    return '<div class="fe-sent"><div class="ok">' + ic('check') + '</div><h2>הקישור מוכן</h2>' +
      '<p>קישור אחד לכל הצדדים. כל אחד פותח אותו, בוחר את הצד שלו, ממלא וחותם.</p>' +
      '<div class="fe-linkbox"><bdi dir="ltr">' + esc(E.link) + '</bdi></div>' +
      '<div class="fe-acts"><button type="button" class="primary" data-fe="copy">' + ic('copy') + 'העתקת הקישור</button>' +
      '<a class="ghost fe-a" href="' + esc(wa) + '" target="_blank" rel="noopener">' + ic('send') + 'שליחה בוואטסאפ</a>' +
      '<a class="ghost fe-a" href="' + esc(E.link) + '" target="_blank" rel="noopener">' + ic('link') + 'פתיחת הקישור</a></div>' +
      '<ul class="fe-left">' + E.parties.map(function (p, i) {
        return '<li data-p="' + ((i % 4) + 1) + '"><span class="dot"></span><b>' + esc(p.label) + '</b><span class="chip sent">ממתין לחתימה</span>' +
          (p.code ? '<span class="fe-mono">קוד: ' + esc(p.code) + '</span>' : '') + '</li>';
      }).join('') + '</ul>' +
      '<p class="fe-note">' + ic('info') + 'המצב של כל צד מופיע במגירה של המסמך. כשכולם חותמים, העותק החתום נשמר ב«קבצים» ומופיע כאן.' +
      (E.settings.expires ? ' הקישור בתוקף עד ' + esc(dateHe(E.settings.expires)) + '.' : '') + '</p>' +
      '<div class="fe-acts"><button type="button" class="ghost" data-fe="close">סגירה</button></div></div>';
  }
  /** Boxes in their places: fractions of the page from its top-left (a page has a left edge in any language). */
  function place() {
    Array.prototype.forEach.call(el.querySelectorAll('.fe-box'), function (b) {
      var v = b.getAttribute('data-box').split(',').map(Number);
      b.style.left = v[0] * 100 + '%'; b.style.top = v[1] * 100 + '%';
      b.style.width = v[2] * 100 + '%'; b.style.height = v[3] * 100 + '%';
    });
  }

  // ── acting ──────────────────────────────────────────────────────────────────────────────────────────
  function onClick(e) {
    if (!el || !E && !e.target.closest('[data-fe="close"]')) return;
    var t = e.target.closest('[data-fe]');
    if (t) {
      var a = t.getAttribute('data-fe');
      if (a === 'close') return close();
      if (a === 'sel') { E.sel = E.sel === t.getAttribute('data-id') ? null : t.getAttribute('data-id'); E.scrollTo = true; return render(); }
      if (a === 'add') return add(t.getAttribute('data-pid'), t.getAttribute('data-type'));
      if (a === 'move') { E.placing = t.getAttribute('data-id'); return render(); }
      if (a === 'unplace') { E.placing = null; return render(); }
      if (a === 'del') { E.fields = E.fields.filter(function (f) { return f.id !== t.getAttribute('data-id'); }); E.sel = null; return render(); }
      if (a === 'addparty') {
        var p = { id: uid('p'), label: 'צד ' + (E.parties.length + 1), note: '' };
        E.parties.push(p); return add(p.id, 'signature');
      }
      if (a === 'delparty') {
        var pid = t.getAttribute('data-pid');
        E.parties = E.parties.filter(function (x) { return x.id !== pid; });
        E.fields = E.fields.filter(function (f) { return f.party !== pid; });
        return render();
      }
      if (a === 'send') return send();
      if (a === 'copy') {
        (navigator.clipboard ? navigator.clipboard.writeText(E.link) : Promise.reject()).then(function () {
          t.innerHTML = ic('check') + 'הקישור הועתק';
        }, function () {   // no clipboard here: the link in a field to copy, asked inside the page (never prompt())
          if (window.binaAsk) window.binaAsk({ title: 'העתיקו את הקישור', ok: 'סגירה', input: { label: 'הקישור', value: E.link } });
        });
        return;
      }
      return;
    }
    // a tap on a page while a place is being chosen: the place is there
    var pg = E && E.placing && e.target.closest('.fe-page');
    if (pg) {
      var r = pg.getBoundingClientRect(), f = field(E.placing);
      var sz = SIZE[f.type] || [0.2, 0.024];
      var x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      f.page = +pg.getAttribute('data-page');
      f.box = [clamp(x - sz[0] / 2, 0, 1 - sz[0]), clamp(y - sz[1], 0, 1 - sz[1]), sz[0], sz[1]];
      E.sel = f.id; E.placing = null; render();
    }
  }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  /** A personal code: six digits from the browser's cryptographic source (a 4-digit Math.random code was 9,000
   *  guesses — the second reader); esign doubles the lock after every five wrong ones. */
  function newCode() {
    var a = new Uint32Array(1);
    (window.crypto || window.msCrypto).getRandomValues(a);
    return String(100000 + (a[0] % 900000));
  }
  function add(pid, type) {
    var p = E.parties[pidx(pid)];
    var f = { id: uid('f'), party: pid, type: type, label: type === 'signature' ? 'חתימה' : 'שאלה חדשה', help: '', required: true, page: null, box: null };
    if (type !== 'signature') f.group = 'הפרטים של ' + p.label;
    E.fields.push(f);
    E.sel = f.id; E.placing = f.id;
    render();
  }
  function onInput(e) {
    var t = e.target;
    if (!E) return;
    if (t.hasAttribute('data-pid') && t.getAttribute('data-k')) {
      E.parties[pidx(t.getAttribute('data-pid'))][t.getAttribute('data-k')] = t.value;
      if (e.type === 'change') render();
      return;
    }
    if (t.hasAttribute('data-set')) { E.settings[t.getAttribute('data-set')] = t.value; return; }
    if (t.getAttribute('data-fe') === 'code') {
      var p = E.parties[pidx(t.getAttribute('data-pid'))];
      p.code = t.checked ? newCode() : '';
      return render();
    }
    var fid = t.getAttribute('data-fid'), k = t.getAttribute('data-k');
    if (!fid || !k) return;
    var f = field(fid);
    if (k === 'required') f.required = t.checked;
    else if (k === 'options') f.options = t.value.split('\n').map(function (s) { return s.trim(); }).filter(Boolean);
    else f[k] = t.value;
    if (e.type === 'change' && (k === 'type' || k === 'party' || k === 'required')) render();
    else {
      var b = el.querySelector('.fe-box[data-id="' + fid + '"] span');
      if (b && k === 'label') b.textContent = t.value;
    }
  }
  // dragging a place to move it, its corner to size it — with a mouse or a finger
  var drag = null;
  function onDown(e) {
    var b = E && !E.placing && e.target.closest('.fe-box');
    if (!b) return;
    var f = field(b.getAttribute('data-id')), pg = b.closest('.fe-page').getBoundingClientRect();
    if (E.sel !== f.id) { E.sel = f.id; render(); return; }
    e.preventDefault();
    drag = { f: f, grip: !!e.target.getAttribute('data-grip'), x: e.clientX, y: e.clientY, w: pg.width, h: pg.height, box: f.box.slice(), node: b };
    b.setPointerCapture && b.setPointerCapture(e.pointerId);
  }
  function onMove(e) {
    if (!drag) return;
    var dx = (e.clientX - drag.x) / drag.w, dy = (e.clientY - drag.y) / drag.h, v = drag.box.slice();
    if (drag.grip) { v[2] = clamp(v[2] + dx, 0.015, 1 - v[0]); v[3] = clamp(v[3] + dy, 0.012, 1 - v[1]); }
    else { v[0] = clamp(v[0] + dx, 0, 1 - v[2]); v[1] = clamp(v[1] + dy, 0, 1 - v[3]); }
    drag.f.box = v;
    drag.node.setAttribute('data-box', v.join(','));
    place();
  }
  function onUp() { drag = null; }

  // ── the link ────────────────────────────────────────────────────────────────────────────────────────
  function send() {
    if (E.busy) return;
    E.busy = true; render();
    post('/event/' + encodeURIComponent(E.event.id) + '/send', {
      title: E.event.title, parties: E.parties, fields: E.fields, settings: E.settings
    }).then(function (r) {
      E.busy = false;
      if (!r.ok) { render(); if (window.binaTell) window.binaTell(r.message || 'הקישור לא נוצר', 'bad', { stay: true }); return; }
      E.link = r.link; render();
      if (typeof window.FillEditorSent === 'function') window.FillEditorSent(E.doc, r);
      else status(E.doc);                                         // the drawer behind shows the sides at once
    });
  }

  // ── the drawer: each event of the document, each side's state, the signed copy when there is one ───────────
  var STATE_HE = { waiting: 'ממתין', filling: 'בתהליך מילוי', signed: 'נחתם' };
  function status(doc) {
    var host = document.querySelector('#drawer .events');
    if (!host || !doc) return;
    var box = host.querySelector('.fe-st');
    if (!box) { box = document.createElement('div'); box.className = 'fe-st'; host.insertBefore(box, host.firstChild); }
    box.innerHTML = '';
    box.setAttribute('data-doc', doc.id);
    call('/' + encodeURIComponent(doc.id)).then(function (r) {
      if (box.getAttribute('data-doc') !== doc.id) return;          // another document was opened meanwhile
      if (!r.ok) { box.innerHTML = '<h3>מילוי וחתימה</h3><p class="fe-mut">' + esc(r.message || 'אפליקציית החתימות לא ענתה') + '</p>'; return; }
      var evs = (r.events || []).filter(function (e) { return e.status !== 'cancelled'; });
      if (!evs.length) return;
      // the document's own chip says where its signing stands — the newest link's, read here (the drawer's header
      // knew only the one-signer envelopes)
      var chip = document.getElementById('dSign'), e0 = evs[0];
      if (chip) {
        var n = e0.parties.filter(function (p) { return p.state === 'signed'; }).length;
        chip.className = 'chip ' + (e0.status === 'complete' ? 'paid' : 'sent');
        chip.textContent = e0.status === 'complete' ? 'נחתם · כל הצדדים'
          : e0.status === 'completing' ? 'נחתם · העותק מופק' : 'במילוי וחתימה · ' + n + ' מתוך ' + e0.parties.length;
        chip.title = e0.parties.map(function (p) { return p.label + ': ' + (STATE_HE[p.state] || p.state); }).join(' · ');
      }
      box.innerHTML = '<h3>מילוי וחתימה</h3>' + evs.slice(0, 3).map(function (e) {
        var done = e.status === 'complete' && e.final_state === 'ok';
        var pend = /^pending/.test(e.drive_state || '');
        var failed = /^failed/.test(e.final_state || '');
        return '<div class="fe-ev"><ul>' + e.parties.map(function (p, i) {
          var when = p.signed_at ? ' · ' + p.signed_at.slice(8, 10) + '.' + p.signed_at.slice(5, 7) : '';
          return '<li data-p="' + ((i % 4) + 1) + '"><span class="dot"></span><b>' + esc(p.label) + '</b>' +
            '<span class="chip ' + (p.state === 'signed' ? 'paid' : p.state === 'filling' ? 'issued' : 'sent') + '">' +
            esc(STATE_HE[p.state] || p.state) + esc(when) + '</span></li>';
        }).join('') + '</ul><div class="fe-evacts">' + (done
          // made but not delivered to «קבצים»: said on a line of its own, and delivered again from here (round 4)
          ? (pend ? '<span class="fe-mut">העותק החתום לא נמסר ל«קבצים»</span>'
            : e.drive_state === 'delivering' ? '<span class="fe-mut">העותק החתום נמסר ל«קבצים»…</span>' : '') +
            '<a class="ghost sm" href="api/fill/event/' + esc(e.id) + '/download" target="_blank" rel="noopener">העותק החתום</a>' +
            (pend ? '<button type="button" class="ghost sm" data-fe-reseal="' + esc(e.id) + '" data-busy="מוסרים…" ' +
              'data-fail="העותק לא נמסר" title="מוסר שוב את העותק החתום ל«קבצים»">מסירה מחדש</button>' : '')
          : e.status === 'open'
            ? '<button type="button" class="ghost sm" data-fe-relink="' + esc(e.id) + '" title="מנפיק קישור חדש; הקישור שנשלח קודם מפסיק לעבוד">קישור חדש</button>' +
              '<button type="button" class="ghost sm danger-t" data-fe-cancel="' + esc(e.id) + '" title="הקישור נסגר; מי שכבר חתם נשאר ביומן">ביטול הקישור</button>'
            : failed
              // the copy failed to be made: said, and made again from here (it waited for a restart — round 2)
              ? '<span class="fe-mut">כל הצדדים חתמו · הפקת העותק נכשלה</span>' +
                '<button type="button" class="ghost sm" data-fe-reseal="' + esc(e.id) + '" title="מפיק שוב את העותק החתום מהחתימות השמורות">הפקה מחדש</button>'
              : '<span class="fe-mut">כל הצדדים חתמו · העותק החתום מופק</span>') +
          '</div></div>';
      }).join('');
    });
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-fe-reseal]');
    if (!b) return;
    b.disabled = true; b.textContent = b.getAttribute('data-busy') || 'מפיקים…';
    post('/event/' + encodeURIComponent(b.getAttribute('data-fe-reseal')) + '/complete', {}).then(function (r) {
      var doc = b.closest('.fe-st') && b.closest('.fe-st').getAttribute('data-doc');
      if (!r.ok && window.binaAsk) window.binaAsk({ title: b.getAttribute('data-fail') || 'העותק לא הופק',
        body: r.message || '', ok: 'סגירה' });
      // the copy is made beside the request: the drawer reads the state again a few times while it is
      [0, 6000, 20000].forEach(function (ms) { setTimeout(function () { if (doc) status({ id: doc }); }, ms); });
    });
  });
  document.addEventListener('click', function (e) {
    var c = e.target.closest && e.target.closest('[data-fe-cancel]');
    if (!c) return;
    var id = c.getAttribute('data-fe-cancel');
    var go = window.binaAsk ? window.binaAsk({ title: 'ביטול הקישור', ok: 'ביטול הקישור',
      body: 'הקישור ייסגר ואי אפשר יהיה למלא ולחתום בו. מי שכבר חתם נשאר רשום ביומן. אפשר לשלוח אחר כך קישור חדש.' })
      : Promise.resolve(true);
    go.then(function (yes) {
      if (!yes) return;
      post('/event/' + encodeURIComponent(id) + '/cancel', {}).then(function (r) {
        var doc = c.closest('.fe-st') && c.closest('.fe-st').getAttribute('data-doc');
        if (!r.ok && window.binaAsk) window.binaAsk({ title: 'הקישור לא בוטל', body: r.message || '', ok: 'סגירה' });
        if (doc) status({ id: doc });
      });
    });
  });
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-fe-relink]');
    if (!b) return;
    var eid = b.getAttribute('data-fe-relink');
    var go = window.binaAsk ? window.binaAsk({ title: 'קישור חדש', ok: 'הנפקת קישור חדש',
      body: 'הקישור שנשלח קודם יפסיק לעבוד. מי שכבר חתם נשאר חתום, וכל הצדדים ממשיכים בקישור החדש.' }) : Promise.resolve(true);
    go.then(function (yes) {
      if (!yes) return;
      post('/event/' + encodeURIComponent(eid) + '/link', {}).then(function (r) {
        if (!r.ok) { if (window.binaAsk) window.binaAsk({ title: 'הקישור לא הונפק', body: r.message || '', ok: 'סגירה' }); return; }
        (navigator.clipboard ? navigator.clipboard.writeText(r.link) : Promise.reject()).then(function () {
          b.textContent = 'הקישור החדש הועתק';
        }, function () {
          if (window.binaAsk) window.binaAsk({ title: 'הקישור החדש', ok: 'סגירה', input: { label: 'הקישור', value: r.link } });
        });
      });
    });
  });

  document.addEventListener('click', function (e) { if (el && el.contains(e.target)) onClick(e); });
  document.addEventListener('input', function (e) { if (el && el.contains(e.target)) onInput(e); });
  document.addEventListener('change', function (e) { if (el && el.contains(e.target)) onInput(e); });
  document.addEventListener('pointerdown', function (e) { if (el && el.contains(e.target)) onDown(e); });
  document.addEventListener('pointermove', onMove);
  document.addEventListener('pointerup', onUp);
  window.FillEditor = { open: open, close: close, status: status };
})();
