/* sim overlay · connected-instances switcher — injected into every embedded app after its mock.
   Gives Drive, Mail and Chat a VISIBLE, prominent instance switcher + connect entry point at the top of
   the sidebar (the one place these apps share). Sim-only; edits no real source.
   • Drive: delegates switch/connect to the app's proven native account controls (#acctBtn/.acct-pick/
     .acct-add) — so the working-but-hidden connect flow finally has visible UI.
   • Mail: fully custom — reads api/accounts, switches via api/account/select (+ reloads the inbox),
     and opens its own connect modal (providers → method → OAuth/form) against the mail mock.
   • Chat: same generic accounts API as Mail (api/accounts / account/select / account/add) with the
     api/chat-providers catalog; post-switch it re-boots the chat client via window.__chatReload.
   No-ops in any app that is neither Drive, Mail nor Chat. See sim/CONNECTED-INSTANCES.md. */
(function () {
  function ready(fn) { if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn); else fn(); }
  var ic = window.__simIcon || function () { return ''; };     // the overlay's one icon pack (icons.js)
  ready(function () {
    var isDrive = !!(document.getElementById('treeList') || document.getElementById('railMount'));
    var isMail = !isDrive && !!(document.getElementById('msgTable') || document.getElementById('inboxLink'));
    var isChat = !isDrive && !isMail && !!document.getElementById('convList');
    // INDOX is a React SPA: at DOMContentLoaded its DOM is still just <div id="root"></div>, so detect
    // it from markup that exists BEFORE React mounts (the root node + the document title) rather than
    // from rendered UI, which wouldn't be there yet.
    var isIndox = !isDrive && !isMail && !isChat &&
      !!document.getElementById('root') && /מסמכים נכנסים/.test(document.title || '');
    if (!isDrive && !isMail && !isChat && !isIndox) {
      // A screen with no instances takes the LAST screen's chip off the console's top bar. This returned and
      // left it: «מכונה», «אפליקציות» and «אימות מערכת» stood under INDOX's «סבח סוכנויות» (seen 2026-10-10).
      try {
        var pd = window.parent.document, left = pd.querySelector('.topbar .tb-right .dosw-top'), band = pd.getElementById('acctBar');
        if (left) left.remove();
        if (band && band.querySelector('.dosw-top')) {                 // …or off the band, where a console with no top bar keeps it
          band.innerHTML = ''; band.classList.add('hidden');
          var ew = pd.getElementById('embedwrap'); if (ew) ew.classList.remove('has-bar');
        }
      } catch (e) {}
      return;
    }
    // Mail, Chat and INDOX share the generic accounts API (accounts / account/select / account/add);
    // only the API prefix, the provider catalog and the post-switch reload differ. Treat them together
    // where they align. INDOX serves that contract under its own /incomingDocuments prefix.
    var acctApi = isMail || isChat || isIndox;
    var API = isIndox ? '/incomingDocuments/' : 'api/';
    var side = document.querySelector('aside.side');
    // Single, TOP-LEVEL switcher: mount into the console's top service bar (#acctBar) in the same-origin
    // parent (the console's own per-service bar is disabled). Fall back to the app sidebar if unreachable.
    var pdoc = null, pbar = null, embedwrap = null;
    /* Mount target, in order of preference:
         1. the console's own TOP BAR (.tb-right) — the row that already carries the global
            controls, and where every product a person has ever used keeps the account.
         2. the #acctBar band below it — the original home, kept only as a fallback.
       The band was a full-width strip whose entire job was to hold one chip: it cost every app
       ~56px of vertical space forever so that ~15% of one row could be used. The top bar has the
       room already. */
    var ptop = null;
    try {
      if (window.parent && window.parent !== window) {
        pdoc = window.parent.document;
        ptop = pdoc.querySelector('.topbar .tb-right');
        pbar = pdoc.getElementById('acctBar');
        embedwrap = pdoc.getElementById('embedwrap');
      }
    } catch (e) {}
    var topMode = !!(ptop || pbar);
    if (!topMode && !side) return;
    var mdoc = topMode ? pdoc : document;

    // A provider's tile is the PROVIDER'S colour — its mark, not the office's. What is the office's own
    // (the built-in local store, and a connection that names no provider) wears the office's olive.
    var OFFICE = 'var(--olive)';
    var PROV = {
      local: { name: 'מקומי', color: OFFICE }, gdrive: { name: 'Google Drive', color: '#1a73e8' },
      dropbox: { name: 'Dropbox', color: '#0061ff' }, onedrive: { name: 'OneDrive', color: '#0078d4' },
      s3: { name: 'S3', color: '#e8710a' }, gmail: { name: 'Gmail', color: '#ea4335' },
      outlook: { name: 'Outlook', color: '#0078d4' }, imap: { name: 'IMAP', color: 'var(--plum)' }   // a protocol has no mark of its own
    };
    function norm(c) {
      return { id: c.id, provider: c.provider || c.protocol || 'local', label: c.label || c.name || c.id,
        identity: c.identity || c.account_hint || c.email || '', color: c.color || (PROV[c.provider] && PROV[c.provider].color) || OFFICE,
        builtin: !!c.builtin, status: c.status || 'ok', reason: c.reason || c.state_reason || '',
        log: c.log || [], checked: (c.checked != null ? c.checked : null) };
    }
    // Avatar letter: for Drive/Mail/Chat the identity (an address) is the recognisable bit; for INDOX
    // the identity is a table name, so the company label is what a person actually recognises.
    function initial(a) {
      if (a.status === 'unread') return '?';                       // nobody's letter: the list was not read
      var t = ((isIndox ? (a.label || a.identity) : (a.identity || a.label)) || '?').replace(/^[\s·]+/, '');
      return (t[0] || '?').toUpperCase();
    }
    function avatar(a, sz) {
      return '<span class="dosw-av" style="width:' + sz + 'px;height:' + sz + 'px;background:' + a.color + '">' + initial(a) + '</span>';
    }
    // ---- connection-health vocabulary (propagated to the chip dot, the dropdown rows and the panel) ----
    var STCOL = { ok: 'var(--ok)', warning: 'var(--amber)', error: 'var(--red)', checking: 'var(--muted)', unread: 'var(--muted)' };   // the palette's: well · look here · failed · not known
    var STHE = { ok: 'מחובר', warning: 'דורש תשומת לב', error: 'שגיאת חיבור', checking: 'בודק…', unread: 'הרשימה לא נטענה' };
    function dot(st) { return '<span class="dosw-dot" style="background:' + (STCOL[st] || STCOL.ok) + '"></span>'; }
    function levCol(l) { return l === 'error' ? STCOL.error : l === 'warn' ? STCOL.warning : STCOL.ok; }
    function ago(m) { if (m == null) return ''; if (m < 1) return 'עכשיו'; if (m < 60) return 'לפני ' + m + ' דק׳'; if (m < 1440) return 'לפני ' + Math.round(m / 60) + ' שע׳'; var d = Math.round(m / 1440); return d === 1 ? 'לפני יום' : 'לפני ' + d + ' ימים'; }
    function anyBad() { if (!READ) return 'unread'; for (var i = 0; i < ITEMS.length; i++) { if (ITEMS[i].status === 'error') return 'error'; } for (var j = 0; j < ITEMS.length; j++) { if (ITEMS[j].status === 'warning') return 'warning'; } return 'ok'; }

    // ---- styles ----
    var st = document.createElement('style'); st.setAttribute('data-sim-overlay', 'switcher');
    st.textContent =
      '.dosw{position:relative;margin:10px 12px 4px;font-family:var(--font,inherit)}' +
      '.dosw-btn{display:flex;align-items:center;gap:9px;width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:12px;background:var(--surface);cursor:pointer;text-align:start;box-shadow:var(--shadow)}' +
      '.dosw-btn:hover{border-color:var(--accent)}' +
      '.dosw-av{flex:none;display:inline-flex;align-items:center;justify-content:center;border-radius:50%;color:var(--olive-ink);font-weight:700;font-size:12px;line-height:1}' +
      '.dosw-tx{flex:1;min-width:0}.dosw-tx b{display:block;font-size:13px;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
      // (the instance's identity: a line with no letter of its own — a phone number — reads left to right)
      '.dosw-tx small{display:block;font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;unicode-bidi:plaintext;text-align:right}' +
      '.dosw-chev{flex:none;color:var(--muted);font-size:11px}' +
      '.dosw-menu{position:absolute;inset-inline:0;top:calc(100% + 4px);background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow-lg);padding:6px;z-index:1000;max-height:70vh;overflow:auto}' +
      '.dosw-menu.hide{display:none}' +
      '.dosw-it{display:flex;align-items:center;gap:9px;padding:8px;border-radius:9px;cursor:pointer}' +
      '.dosw-it:hover{background:var(--surface-2)}.dosw-it.on{background:var(--accent-soft)}' +
      '.dosw-it .dosw-tx b{font-weight:600}.dosw-it .chk{margin-inline-start:auto;color:var(--accent)}' +
      '.dosw-sep{height:1px;background:var(--line);margin:6px 4px}' +
      '.dosw-add{display:flex;align-items:center;gap:9px;padding:9px 8px;border-radius:9px;cursor:pointer;color:var(--accent-d);font-weight:600;font-size:13px}' +
      '.dosw-add:hover{background:var(--accent-soft)}' +
      '.dosw-plus{flex:none;width:26px;height:26px;border-radius:50%;border:1.5px dashed var(--accent);display:inline-flex;align-items:center;justify-content:center;font-size:16px}' +
      /* connect modal (mail) */
      '.dosw-ov{position:fixed;inset:0;background:var(--scrim);z-index:10000;display:flex;align-items:center;justify-content:center}' +
      '.dosw-mod{background:var(--surface);border-radius:16px;width:min(560px,92vw);max-height:88vh;overflow:auto;box-shadow:var(--shadow-lg);padding:20px}' +
      '.dosw-mod h3{margin:0 0 4px;font-size:17px;color:var(--ink)}.dosw-steps{font-size:12px;color:var(--muted);margin-bottom:14px}' +
      '.dosw-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}' +
      '.dosw-card{border:1px solid var(--line);border-radius:12px;padding:12px;cursor:pointer;background:var(--surface)}' +
      '.dosw-card:hover{border-color:var(--accent);background:var(--surface-2)}' +
      '.dosw-card b{display:block;font-size:14px;color:var(--ink)}.dosw-card small{color:var(--muted);font-size:12px}' +
      '.dosw-tag{display:inline-block;font-size:10px;background:var(--accent-soft);color:var(--accent-d);border-radius:999px;padding:1px 7px;margin-inline-start:6px}' +
      '.dosw-fld{display:block;margin:10px 0}.dosw-fld span{display:block;font-size:12px;color:var(--muted);margin-bottom:3px}' +
      '.dosw-fld input{width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:9px;font:inherit}' +
      '.dosw-row{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}' +
      '.dosw-bt{padding:9px 16px;border-radius:9px;border:1px solid var(--line);background:var(--surface);cursor:pointer;font:inherit;font-weight:600}' +
      '.dosw-bt.pri{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}' +
      '.dosw-wait{display:flex;align-items:center;gap:10px;color:var(--muted);padding:14px 0}' +
      // connection-health bits
      '.dosw-dot{flex:none;width:8px;height:8px;border-radius:50%;display:inline-block}' +
      '.dosw-btn .dosw-dot{margin-inline-start:2px}.dosw-it .dosw-dot{margin-inline:1px 0}' +
      '.dosw-reason{display:block;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
      '.dosw-health{display:flex;align-items:center;gap:9px;padding:9px 8px;border-radius:9px;cursor:pointer;font-size:13px;font-weight:600;color:var(--ink)}' +
      '.dosw-health:hover{background:var(--surface-2)}' +
      '.dosw-badge{margin-inline-start:auto;color:var(--surface);font-weight:700;font-size:11px;min-width:18px;height:18px;border-radius:9px;display:inline-flex;align-items:center;justify-content:center}' +
      '.dosw-hlist{display:flex;flex-direction:column;gap:10px;max-height:56vh;overflow:auto;margin:6px 0}' +
      '.dosw-hcard{border:1px solid var(--line);border-radius:12px;padding:12px}' +
      '.dosw-hhead{display:flex;align-items:center;gap:9px}' +
      '.dosw-pill{margin-inline-start:auto;display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:700;border:1px solid;border-radius:999px;padding:2px 10px;white-space:nowrap}' +
      '.dosw-hreason{margin-top:9px;font-size:12.5px;font-weight:600}' +
      '.dosw-hmeta{margin-top:9px;font-size:11px;color:var(--muted);display:flex;gap:9px;align-items:center}' +
      '.dosw-recheck{border:1px solid var(--line);background:var(--surface);border-radius:7px;padding:2px 10px;font:inherit;font-size:11px;cursor:pointer;color:var(--accent-d)}' +
      '.dosw-recheck:hover{border-color:var(--accent)}' +
      '.dosw-hlog{margin-top:9px}.dosw-hlog summary{cursor:pointer;font-size:12px;color:var(--muted);user-select:none}' +
      '.dosw-logrow{display:flex;align-items:center;gap:8px;padding:5px 2px;font-size:12px}' +
      '.dosw-logmsg{flex:1;color:var(--ink)}.dosw-logt{color:var(--muted);font-size:11px;white-space:nowrap}' +
      // top-bar variant (mounted in the console's #acctBar): horizontal, chip sized to content.
      '.dosw-top{position:relative;margin:0;padding:0;display:flex;align-items:center;font-family:var(--font,inherit)}' +
      /* new-instance form fields (INDOX) */
      '.dosw-f{display:block;margin:10px 0}' +
      '.dosw-f label{display:block;font-size:12px;color:var(--muted);margin-bottom:3px}' +
      '.dosw-f input,.dosw-f select{width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:9px;font:inherit;background:var(--surface);color:var(--ink)}' +
      '.dosw-f input:focus,.dosw-f select:focus{outline:none;border-color:var(--accent)}' +
      '.dosw-f input[type=color]{padding:3px;height:38px;cursor:pointer}' +
      /* touch targets: on phones every control in the switcher/modals clears the 44px minimum */
      '@media (max-width:820px){' +
        '.dosw-f input,.dosw-f select,.dosw-bt,.dosw-recheck{min-height:44px}' +
        '.dosw-f input[type=color]{height:44px}' +
        '.dosw-it,.dosw-add,.dosw-health{min-height:44px}' +
        '.dosw-mod{width:min(560px,94vw);padding:16px}' +
      '}' +
      '.dosw-top .dosw-btn{width:300px}' +
      /* ── the chip, living in the console top bar ────────────────────────────────────────────
         Compact by default: avatar + label + status. The identity (an address, or a table name)
         is the second line only when there is room for it — below 1100px it would push the app
         title off the row, and a truncated address answers nothing anyway, so it is dropped and
         kept in the title attribute. Under 760px the label goes too and the avatar alone stands
         in, exactly as it does in the products this borrows from. */
      '.tb-right .dosw-top{margin-inline-start:6px}' +
      '.tb-right .dosw-top .dosw-btn{width:auto;max-width:240px;padding:5px 9px;border-radius:999px;gap:7px}' +
      '.tb-right .dosw-top .dosw-tx b{font-size:12.5px;line-height:1.25}' +
      '.tb-right .dosw-top .dosw-tx small{font-size:10.5px;line-height:1.2}' +
      '.tb-right .dosw-top .dosw-menu{inset-inline-start:auto;inset-inline-end:0;top:calc(100% + 8px)}' +
      /* Scope every collapse to the CHIP (.dosw-btn). The menu must never lose its labels: an
         account list of four identical coloured circles is not a compact switcher, it is a guessing
         game — and it is the one place the name is the whole point. */
      '@media (max-width:1100px){.tb-right .dosw-top .dosw-btn .dosw-tx small{display:none}}' +
      '@media (max-width:760px){.tb-right .dosw-top .dosw-btn .dosw-tx{display:none}' +
        '.tb-right .dosw-top .dosw-btn{max-width:none;padding:4px}' +
        '.tb-right .dosw-top .dosw-menu{min-width:min(280px,86vw)}}' +
      '#acctBar{overflow:visible!important;display:flex!important;align-items:center;padding:7px 16px}';
    var CSS_ALL = st.textContent;
    var nativeHide = (isDrive ? '#acct{display:none!important}' : '') + (isMail ? '#acctBox{display:none!important}' : '');
    function addStyle(doc, css) { var s = doc.createElement('style'); s.setAttribute('data-sim-overlay', 'switcher'); s.textContent = css; (doc.head || doc.documentElement).appendChild(s); }
    addStyle(mdoc, CSS_ALL);                    // chip + menu where the switcher is mounted
    if (topMode) addStyle(document, CSS_ALL);    // the connect modal is created in the APP document
    addStyle(document, nativeHide);              // hide the app's native account element

    // ---- switcher UI ----
    var wrap = mdoc.createElement('div'); wrap.className = 'dosw' + (topMode ? ' dosw-top' : '');
    if (ptop) {
      // last child of .tb-right = the far end of the line (screen-left in RTL), which is where the
      // account sits in Gmail/Drive and where the eye already goes for "who am I / switch".
      var prev = ptop.querySelector('.dosw-top'); if (prev) prev.remove();
      ptop.appendChild(wrap);
      // the band is now dead weight — collapse it so the app reclaims the height
      if (pbar) { pbar.classList.add('hidden'); pbar.innerHTML = ''; }
      if (embedwrap) embedwrap.classList.remove('has-bar');
    } else if (topMode) {
      pbar.classList.remove('hidden'); if (embedwrap) embedwrap.classList.add('has-bar');
      pbar.innerHTML = ''; pbar.appendChild(wrap);
    } else {
      var brand = side.querySelector('.brand');
      if (brand && brand.nextSibling) side.insertBefore(wrap, brand.nextSibling); else side.insertBefore(wrap, side.firstChild);
    }
    // READ: was the list of accounts read. A list that could not be read is not an empty one, and its chip is
    // not a connected account: it stood as «— · מקומי» beside a green dot, titled «מחובר», over a silent service.
    var open = false, ITEMS = [], ACTIVE = null, READ = false;

    function fetchJSON(u, o) { return fetch(u, o).then(function (r) { return r.json(); }); }
    function loadList(cb) {   // -> cb(items, active); items is null when the list could not be read
      if (isDrive) fetchJSON('connections').then(function (d) { cb((d.connections || d.instances || []).map(norm), d.active); }, function () { cb(null, null); });
      else fetchJSON(API + 'accounts').then(function (d) { cb((d.accounts || []).map(norm), d.active); }, function () { cb(null, null); });  // mail + chat
    }
    function activeItem() {
      for (var i = 0; i < ITEMS.length; i++) if (ITEMS[i].id === ACTIVE) return ITEMS[i];
      return ITEMS[0] || norm(READ ? { id: '?', label: '—' } : { id: '?', label: 'לא נטען', provider: '-', color: 'var(--muted)', status: 'unread' });
    }

    function render() {
      var a = activeItem();
      // (INDOX: an instance is recognised by its company — the chip's first line. The table it is kept in is an
      //  identifier: one hover away, in the title, not the chip's second line — «incoming_documents» stood there.)
      var head = avatar(a, 30) + '<span class="dosw-tx"><b>' + esc(a.label) + '</b><small>' + esc(isIndox ? '' : (a.identity || PROV[a.provider] && PROV[a.provider].name || '')) + '</small></span>' + dot(a.status);
      wrap.innerHTML = '<button class="dosw-btn" type="button" aria-haspopup="menu" aria-expanded="false" aria-label="חשבון פעיל: ' + esc(a.label) + ' — ' + esc(STHE[a.status]) + '. החלפת חשבון" title="' + esc(a.reason || STHE[a.status] + (isIndox && a.identity ? ' · ' + a.identity : '')) + '">' + head + '<span class="dosw-chev" aria-hidden="true">' + ic('chevron') + '</span></button>' +
        '<div class="dosw-menu hide" role="menu"></div>';
      wrap.querySelector('.dosw-btn').onclick = toggle;
      buildMenu();
    }
    // NOTE: a unified "all inboxes / all drives" view is intentionally omitted for now (unsupported
    // feature — see CONNECTED-INSTANCES.md, optional future). The mock still accepts active:"all".
    function buildMenu() {
      var menu = wrap.querySelector('.dosw-menu'); var html = '';
      ITEMS.forEach(function (a, i) {
        var sub = (a.status !== 'ok' && a.reason)
          ? '<small class="dosw-reason" style="color:' + STCOL[a.status] + '">' + esc(a.reason) + '</small>'
          : '<small>' + esc(a.identity || (PROV[a.provider] && PROV[a.provider].name) || '') + '</small>';
        html += '<div class="dosw-it' + (a.id === ACTIVE ? ' on' : '') + '" data-i="' + i + '" role="menuitemradio" tabindex="0" aria-checked="' + (a.id === ACTIVE ? 'true' : 'false') + '" aria-label="' + esc(a.label) + ' — ' + esc(STHE[a.status]) + '">' + avatar(a, 26) + dot(a.status) +
          '<span class="dosw-tx"><b>' + esc(a.label) + '</b>' + sub + '</span>' +
          (a.id === ACTIVE ? '<span class="chk">' + ic('check') + '</span>' : '') + '</div>';
      });
      html += '<div class="dosw-sep"></div>' +
        '<div class="dosw-health" data-health="1" role="menuitem" tabindex="0">' + dot(anyBad()) +
          (isIndox ? 'פרטי המופע' : 'מצב החיבורים') +
          (/^(warning|error)$/.test(anyBad()) ? '<span class="dosw-badge" style="background:' + STCOL[anyBad()] + '" role="img" aria-label="דורש טיפול" title="דורש טיפול">' + ic('bang') + '</span>' : '') + '</div>' +
        '<div class="dosw-add" data-add="1" role="menuitem" tabindex="0"><span class="dosw-plus" aria-hidden="true">' + ic('plus') + '</span>' +
          (isIndox ? 'מופע INDOX חדש' : 'חיבור חשבון' + (isDrive ? ' / מקור' : '') + ' חדש') + '</div>';
      menu.innerHTML = html;
      var hp = menu.querySelector('.dosw-health'); if (hp) hp.onclick = function () { close(); healthPanel(); };
      menu.querySelectorAll('.dosw-it').forEach(function (el) {
        el.onclick = function () {
          if (el.getAttribute('data-all')) { selectAll(); return; }
          switchTo(ITEMS[+el.getAttribute('data-i')]);
        };
      });
      menu.querySelector('.dosw-add').onclick = function () { close(); connect(); };
      // keyboard-activate every menu item (Enter/Space), matching the click handlers
      menu.querySelectorAll('[role^="menuitem"]').forEach(function (el) {
        el.onkeydown = function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); el.click(); }
          else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); var items = [].slice.call(menu.querySelectorAll('[role^="menuitem"]')); var idx = items.indexOf(el); var nx = items[(idx + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length]; if (nx) nx.focus(); } };
      });
    }
    function setExpanded(v) { var b = wrap.querySelector('.dosw-btn'); if (b) b.setAttribute('aria-expanded', v ? 'true' : 'false'); }
    function toggle() { open ? close() : openMenu(); }
    function openMenu() { open = true; wrap.querySelector('.dosw-menu').classList.remove('hide'); setExpanded(true); var f = wrap.querySelector('.dosw-menu [role^="menuitem"]'); if (f) try { f.focus(); } catch (e) {} }
    function close() { open = false; var m = wrap.querySelector('.dosw-menu'); if (m) m.classList.add('hide'); setExpanded(false); }
    mdoc.addEventListener('click', function (e) { if (open && !wrap.contains(e.target)) close(); }, true);
    mdoc.addEventListener('keydown', function (e) { if (open && e.key === 'Escape') { close(); var b = wrap.querySelector('.dosw-btn'); if (b) try { b.focus(); } catch (_) {} } }, true);

    function reload() {
      loadList(function (items, active) { READ = !!items; ITEMS = items || []; ACTIVE = active; render(); });
    }

    // ---- switch / connect (per app) ----
    function switchTo(a) {
      close();
      if (isDrive) { driveDelegate('pick', a); setTimeout(reload, 400); }
      else fetch(API + 'account/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: a.id }) })
        .then(function () { ACTIVE = a.id; appReload(); render(); });
    }
    function selectAll() {
      close();
      fetch(API + 'account/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: 'all' }) })
        .then(function () { ACTIVE = 'all'; appReload(); render(); });
    }
    function connect() { if (isDrive) driveDelegate('add'); else if (isIndox) openNewInstance(); else openConnect(); }

    // post-switch reload: mail re-clicks its inbox link; chat and INDOX re-boot via a global hook.
    // INDOX's hook also re-navigates to the NEW instance's table, since the route carries the id.
    function appReload() {
      if (isChat) { try { (window.__chatReload || function () {})(); } catch (e) {} return; }
      if (isIndox) { try { (window.__indoxReload || function () {})(); } catch (e) {} return; }
      var il = document.getElementById('inboxLink'); if (il) il.click();
    }

    // Drive: drive the native (hidden) account controls so the proven flow is used + refreshes properly.
    function driveDelegate(kind, a) {
      var btn = document.getElementById('acctBtn'); if (!btn) return;
      btn.click();
      setTimeout(function () {
        if (kind === 'add') { var add = document.querySelector('.acct-add'); if (add) add.click(); return; }
        var picks = document.querySelectorAll('.acct-pick'); var want = (a.label || '') + '';
        for (var i = 0; i < picks.length; i++) {
          var t = picks[i].textContent || '';
          if (t.indexOf(want) !== -1 || (a.identity && t.indexOf(a.identity) !== -1)) { picks[i].click(); return; }
        }
        btn.click(); // nothing matched — close native menu
      }, 60);
    }

    // Mail: own connect modal (providers → method → OAuth/form → verify → activate)
    function openConnect() {
      fetchJSON(isChat ? 'api/chat-providers' : 'api/mail-providers').then(function (d) { stepProvider(d.providers || []); }, function () {});
    }
    function modal(html) {
      var prevFocus = document.activeElement;
      var ov = document.createElement('div'); ov.className = 'dosw-ov';
      ov.setAttribute('role', 'dialog'); ov.setAttribute('aria-modal', 'true');
      ov.innerHTML = '<div class="dosw-mod">' + html + '</div>';
      ov.addEventListener('click', function (e) { if (e.target === ov) closeModal(ov); });
      // A10 UX bar: Esc closes; focus the first control; focus-trap; restore focus to the trigger on close.
      ov._onkey = function (e) {
        if (e.key === 'Escape') { e.preventDefault(); closeModal(ov); return; }
        if (e.key === 'Tab') {
          var f = ov.querySelectorAll('a[href],button:not([disabled]),input,select,textarea,[tabindex]:not([tabindex="-1"])');
          if (!f.length) return; var first = f[0], last = f[f.length - 1];
          if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
          else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
      };
      ov._prevFocus = prevFocus;
      document.addEventListener('keydown', ov._onkey, true);
      document.body.appendChild(ov);
      var f0 = ov.querySelector('input,button,a[href],select,textarea,[tabindex]:not([tabindex="-1"])'); if (f0) try { f0.focus(); } catch (e) {}
      return ov;
    }
    function closeModal(ov) {
      if (!ov || !ov.parentNode) return;
      if (ov._onkey) document.removeEventListener('keydown', ov._onkey, true);
      ov.parentNode.removeChild(ov);
      if (ov._prevFocus && ov._prevFocus.focus) try { ov._prevFocus.focus(); } catch (e) {}
    }
    function stepProvider(provs) {
      var cards = provs.map(function (p, i) {
        return '<div class="dosw-card" data-i="' + i + '"><b>' + esc(p.name) + (p.builtin ? '<span class="dosw-tag">מובנה</span>' : '') + '</b><small>' + esc(p.description || '') + '</small></div>';
      }).join('');
      var ov = modal('<h3>חיבור חשבון ' + (isChat ? 'צ׳אט' : 'דואר') + '</h3><div class="dosw-steps">1 ספק · 2 אופן החיבור · 3 אישור · 4 הפעלה</div><div class="dosw-grid">' + cards + '</div><div class="dosw-row"><button class="dosw-bt" data-x>ביטול</button></div>');
      ov.querySelector('[data-x]').onclick = function () { closeModal(ov); };
      ov.querySelectorAll('.dosw-card').forEach(function (el) { el.onclick = function () { closeModal(ov); stepMethod(provs[+el.getAttribute('data-i')]); }; });
    }
    function stepMethod(prov) {
      var ms = prov.auth_methods || [];
      var rows = ms.map(function (m, i) {
        return '<div class="dosw-card" data-i="' + i + '"><b>' + esc(m.label) + (m.recommended ? '<span class="dosw-tag">מומלץ</span>' : '') + '</b><small>' + esc(m.can || '') + '</small></div>';
      }).join('');
      var ov = modal('<h3>חיבור ' + esc(prov.name) + '</h3><div class="dosw-steps">2 אופן החיבור</div><div class="dosw-grid">' + rows + '</div><div class="dosw-row"><button class="dosw-bt" data-back>חזרה</button></div>');
      ov.querySelector('[data-back]').onclick = function () { closeModal(ov); openConnect(); };
      ov.querySelectorAll('.dosw-card').forEach(function (el) {
        el.onclick = function () { var m = ms[+el.getAttribute('data-i')]; closeModal(ov);
          if (m.protocol === 'local') return provisionSelect(prov, m, null);
          if (m.start_url) return stepOauth(prov, m);
          return stepForm(prov, m);
        };
      });
    }
    function stepOauth(prov, m) {
      var ov = modal('<h3>חיבור ' + esc(prov.name) + '</h3><div class="dosw-steps">3 אישור</div>' +
        '<p style="color:var(--muted);font-size:13px">' + esc(m.explain || 'נפתח חלון אישור מאובטח.') + '</p>' +
        '<div class="dosw-row"><button class="dosw-bt" data-back>חזרה</button><button class="dosw-bt pri" data-go>פתיחת חלון האישור</button></div>');
      ov.querySelector('[data-back]').onclick = function () { closeModal(ov); stepMethod(prov); };
      ov.querySelector('[data-go]').onclick = function () {
        var before = ITEMS.map(function (x) { return x.id; });
        window.open(m.start_url, '_blank', 'width=520,height=640');
        ov.querySelector('.dosw-mod').innerHTML = '<h3>חיבור ' + esc(prov.name) + '</h3><div class="dosw-wait"><span>⏳</span><div>ממתין לאישור בחלון של ' + esc(prov.name) + '…</div></div>';
        var tries = 0, t = setInterval(function () {
          tries++;
          loadList(function (items) {
            var fresh = (items || []).filter(function (x) { return before.indexOf(x.id) === -1; })[0];
            if (fresh) { clearInterval(t); closeModal(ov); ACTIVE = fresh.id; fetch(API + 'account/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: fresh.id }) }).then(function () { reload(); appReload(); }); }
            else if (tries > 20) { clearInterval(t); closeModal(ov); }
          });
        }, 400);
      };
    }
    function stepForm(prov, m) {
      var needs = m.needs || [];
      var fields = needs.map(function (n) { return '<label class="dosw-fld"><span>' + esc(n) + '</span><input data-need="' + esc(n) + '" dir="ltr"></label>'; }).join('');
      var ov = modal('<h3>חיבור ' + esc(prov.name) + '</h3><div class="dosw-steps">3 פרטי חיבור</div>' + fields +
        '<div class="dosw-row"><button class="dosw-bt" data-back>חזרה</button><button class="dosw-bt pri" data-go>חיבור</button></div>');
      ov.querySelector('[data-back]').onclick = function () { closeModal(ov); stepMethod(prov); };
      ov.querySelector('[data-go]').onclick = function () { closeModal(ov); provisionSelect(prov, m, null); };
    }
    function provisionSelect(prov, m) {
      fetch(API + 'account/add', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ protocol: m.protocol, label: prov.name }) })
        .then(function (r) { return r.json(); }).then(function (res) {
          if (res && res.id) fetch(API + 'account/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: res.id }) }).then(function () { ACTIVE = res.id; reload(); appReload(); });
          else reload();
        });
    }

    // ---- connection-health panel: the full picture — every instance's state + event/error log ----
    var APPNAME = isDrive ? 'דרייב' : isChat ? 'צ׳אט' : 'מייל';
    // ─────────────────────────────────────────────────────────────────────────────────────────────
    // INDOX · instance details + "new instance" flow
    // ─────────────────────────────────────────────────────────────────────────────────────────────
    // The details panel is where the deleted RepoDetail screen's information went: the active
    // instance's backend, target table, columns, sync registries and how much each of its OWN stores
    // holds (documents / settings / companies / tag rules) — the proof that an instance is a whole
    // INDOX, not a shared table with a different filter.
    function instancePanel() {
      fetchJSON(API + 'account/detail').then(function (d) {
        var a = d.account || {}, repo = d.repo || {}, counts = d.counts || {};
        var reg = (d.registry || []).map(function (r) {
          var what = r.source === 'gmail'
            ? 'תוויות: ' + Object.keys(r.labels || {}).map(function (k) { return (r.labels || {})[k]; }).join(' · ')
            : 'תיקיות: ' + (r.pairs || []).map(function (p) { return p.from + ' → ' + p.to; }).join(' · ');
          return '<div class="dosw-hcard"><div class="dosw-hhead">' +
            '<span class="dosw-av" style="width:26px;height:26px;background:' + (r.source === 'gmail' ? '#ea4335' : '#1a73e8') + '">' +
              (r.source === 'gmail' ? 'G' : 'D') + '</span>' +
            '<div class="dosw-tx"><b>' + esc(r.name) + '</b><small>' + esc(what || '—') + '</small></div>' +
            (r.type_hint ? '<span class="dosw-pill">' + esc(r.type_hint) + '</span>' : '') + '</div></div>';
        }).join('') || '<div class="dosw-hmeta">אין רישומי סנכרון למופע זה.</div>';
        var kv = function (k, v) { return '<div class="dosw-logrow"><span class="dosw-logmsg">' + esc(k) + '</span><span class="dosw-logt">' + esc(v) + '</span></div>'; };
        modal('<h3>פרטי המופע · ' + esc(a.label || '') + '</h3>' +
          '<div class="dosw-steps">כל מופע הוא INDOX שלם — טבלה, הגדרות ורישומי סנכרון משלו</div>' +
          '<div class="dosw-hcard">' +
            kv('טבלת יעד', d.target || '—') +
            kv('סוג אחסון', repo.backend || '—') +
            kv('מפתח ראשי', repo.primary_key || '—') +
            kv('עמודות', String((d.columns || []).length)) +
            kv('תדירות סריקה', (repo.poll_interval_seconds || '—') + ' שנ׳') +
          '</div>' +
          '<div class="dosw-steps" style="margin-top:14px">המאגרים של המופע</div>' +
          '<div class="dosw-hcard">' +
            kv('מסמכים', String(counts.docs != null ? counts.docs : '—')) +
            kv('הגדרות', String(counts.settings != null ? counts.settings : '—')) +
            kv('חברות', String(counts.companies != null ? counts.companies : '—')) +
            kv('כללי תיוג', String(counts.tag_rules != null ? counts.tag_rules : '—')) +
          '</div>' +
          '<div class="dosw-steps" style="margin-top:14px">רישומי סנכרון (' + (d.registry || []).length + ')</div>' + reg +
          '<div class="dosw-row"><button class="dosw-bt" data-x>סגירה</button></div>');
      }, function () {});
    }

    // New instance = a whole new INDOX. 3 steps: identity → target table → sync registries.
    // Step 3 is the one that matters: pick a CONNECTION, then what to sync from it — gmail labels
    // (tags) or drive folder pairs — which is exactly a SyncRegistryEntry in the real API.
    function openNewInstance() {
      // a new instance starts in the office's olive — READ from the palette (the colour field takes a value, not a token)
      var spec = { label: '', company: '', color: getComputedStyle(mdoc.documentElement).getPropertyValue('--olive').trim(), backend: 'supabase', table: '', registry: [] };
      var CONNS = [];
      fetchJSON(API + 'connections').then(function (d) { CONNS = d.connections || []; step1(); }, function () { CONNS = []; step1(); });

      function head(n, t) {
        return '<h3>' + esc(t) + '</h3><div class="dosw-steps">' +
          ['1 זהות', '2 טבלת יעד', '3 רישומי סנכרון'].map(function (s, i) {
            return (i + 1 === n ? '<b style="color:var(--accent-d)">' + s + '</b>' : s);
          }).join(' · ') + '</div>';
      }
      function step1() {
        var ov = modal(head(1, 'מופע INDOX חדש') +
          '<div class="dosw-f"><label>שם המופע</label><input id="ni-label" placeholder="למשל: כהן ובניו" value="' + esc(spec.label) + '"></div>' +
          '<div class="dosw-f"><label>חברה</label><input id="ni-company" placeholder="שם החברה המלא" value="' + esc(spec.company) + '"></div>' +
          '<div class="dosw-f"><label>צבע מזהה</label><input id="ni-color" type="color" value="' + esc(spec.color) + '"></div>' +
          '<div class="dosw-row"><button class="dosw-bt" data-x>ביטול</button><button class="dosw-bt pri" data-go>המשך</button></div>');
        ov.querySelector('[data-go]').onclick = function () {
          spec.label = (ov.querySelector('#ni-label').value || '').trim();
          spec.company = (ov.querySelector('#ni-company').value || '').trim() || spec.label;
          spec.color = ov.querySelector('#ni-color').value || spec.color;
          if (!spec.label) { ov.querySelector('#ni-label').focus(); return; }
          // Default table name stays ASCII — a Hebrew label shouldn't produce a Hebrew SQL identifier.
          if (!spec.table) {
            var slug = spec.label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
            spec.table = 'indox_' + (slug || ('co_' + (ITEMS.length + 1)));
          }
          closeModal(ov); step2();
        };
      }
      function step2() {
        var ov = modal(head(2, 'טבלת היעד') +
          '<div class="dosw-steps">כאן ייכתבו המסמכים של המופע הזה — טבלה נפרדת לחלוטין.</div>' +
          '<div class="dosw-f"><label>סוג אחסון</label><select id="ni-backend">' +
            '<option value="supabase"' + (spec.backend === 'supabase' ? ' selected' : '') + '>Supabase (טבלה)</option>' +
            '<option value="gsheet"' + (spec.backend === 'gsheet' ? ' selected' : '') + '>Google Sheets (גיליון)</option>' +
          '</select></div>' +
          '<div class="dosw-f"><label>שם הטבלה / הגיליון</label><input id="ni-table" value="' + esc(spec.table) + '"></div>' +
          '<div class="dosw-row"><button class="dosw-bt" data-back>חזרה</button><button class="dosw-bt pri" data-go>המשך</button></div>');
        ov.querySelector('[data-back]').onclick = function () { closeModal(ov); step1(); };
        ov.querySelector('[data-go]').onclick = function () {
          spec.backend = ov.querySelector('#ni-backend').value;
          spec.table = (ov.querySelector('#ni-table').value || '').trim() || spec.table;
          closeModal(ov); step3();
        };
      }
      function step3() {
        var opts = CONNS.map(function (c) {
          return '<option value="' + esc(c.id) + '" data-source="' + esc(c.source) + '">' + esc(c.label) + ' · ' + esc(c.identity || '') + '</option>';
        }).join('');
        var listHtml = spec.registry.length
          ? spec.registry.map(function (r, i) {
              var what = r.source === 'gmail'
                ? Object.keys(r.labels || {}).map(function (k) { return r.labels[k]; }).join(' · ')
                : (r.pairs || []).map(function (p) { return p.from + ' → ' + p.to; }).join(' · ');
              return '<div class="dosw-hcard"><div class="dosw-hhead">' +
                '<span class="dosw-av" style="width:24px;height:24px;background:' + (r.source === 'gmail' ? '#ea4335' : '#1a73e8') + '">' + (r.source === 'gmail' ? 'G' : 'D') + '</span>' +
                '<div class="dosw-tx"><b>' + esc(r.name) + '</b><small>' + esc(what) + '</small></div>' +
                '<button class="dosw-recheck" data-del="' + i + '">הסרה</button></div></div>';
            }).join('')
          : '<div class="dosw-hmeta">עדיין לא נבחרו מקורות סנכרון.</div>';
        var ov = modal(head(3, 'מאיפה לסנכרן') +
          '<div class="dosw-steps">בוחרים חיבור קיים (דרייב / מייל) ואז מה למשוך ממנו — תוויות או תיקיות.</div>' +
          listHtml +
          '<div class="dosw-sep"></div>' +
          '<div class="dosw-f"><label>חיבור</label><select id="ni-conn">' + (opts || '<option value="">אין חיבורים זמינים</option>') + '</select></div>' +
          '<div class="dosw-f"><label>סוג מסמך</label><select id="ni-type">' +
            ['INVOICE', 'ORDER', 'SHIPMENT', 'BALANCE_SHEET'].map(function (t) { return '<option>' + t + '</option>'; }).join('') +
          '</select></div>' +
          '<div class="dosw-f" id="ni-what-wrap"><label id="ni-what-lb">תיקיות (מקור → יעד)</label>' +
            '<input id="ni-what-a" placeholder="נכנס/חשבוניות"><input id="ni-what-b" placeholder="ארכיון/חשבוניות" style="margin-top:6px"></div>' +
          '<div class="dosw-row"><button class="dosw-bt" data-addreg>הוספת מקור</button></div>' +
          '<div class="dosw-sep"></div>' +
          '<div class="dosw-row"><button class="dosw-bt" data-back>חזרה</button><button class="dosw-bt pri" data-go>יצירת המופע</button></div>');

        function srcOf() { var s = ov.querySelector('#ni-conn'); var o = s && s.options[s.selectedIndex]; return (o && o.getAttribute('data-source')) || 'drive'; }
        function syncWhat() {
          var gmail = srcOf() === 'gmail';
          ov.querySelector('#ni-what-lb').textContent = gmail ? 'תוויות (לסנכרון / סונכרן)' : 'תיקיות (מקור → יעד)';
          ov.querySelector('#ni-what-a').placeholder = gmail ? 'INDOX/לסנכרון' : 'נכנס/חשבוניות';
          ov.querySelector('#ni-what-b').placeholder = gmail ? 'INDOX/סונכרן' : 'ארכיון/חשבוניות';
        }
        var connSel = ov.querySelector('#ni-conn'); if (connSel) connSel.onchange = syncWhat; syncWhat();
        Array.prototype.forEach.call(ov.querySelectorAll('[data-del]'), function (b) {
          b.onclick = function () { spec.registry.splice(+b.getAttribute('data-del'), 1); closeModal(ov); step3(); };
        });
        ov.querySelector('[data-addreg]').onclick = function () {
          var src = srcOf(), a = ov.querySelector('#ni-what-a').value.trim(), b = ov.querySelector('#ni-what-b').value.trim();
          if (!a) { ov.querySelector('#ni-what-a').focus(); return; }
          var cid = (connSel && connSel.value) || 'conn';
          var e = { name: src + '-' + cid + '-' + (spec.registry.length + 1), source: src, engine: 'n8n',
            type_hint: ov.querySelector('#ni-type').value, connection: cid,
            batch: { take: 20, chunk: 5, timeout_min: 10, schedule_min: 10 } };
          if (src === 'gmail') { e.labels = { to_sync: a, synced: b || a + '/סונכרן' }; e.claim_label = a + '/בעיבוד'; }
          else { e.pairs = [{ from: a, to: b || a + '/ארכיון' }]; e.dest_folder = b || a + '/ארכיון'; }
          spec.registry.push(e); closeModal(ov); step3();
        };
        ov.querySelector('[data-back]').onclick = function () { closeModal(ov); step2(); };
        ov.querySelector('[data-go]').onclick = function () {
          fetch(API + 'account/add', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(spec) })
            .then(function (r) { return r.json(); })
            .then(function (res) {
              closeModal(ov);
              var nid = res && res.account && res.account.id;
              if (!nid) return;
              fetch(API + 'account/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: nid }) })
                .then(function () { ACTIVE = nid; reload(); appReload(); });
            });
        };
      }
    }

    function healthPanel() {
      if (isIndox) return instancePanel();
      var rows = ITEMS.map(function (a) {
        var evs = (a.log && a.log.length) ? a.log : [{ mins: a.checked, level: 'info', msg: 'החשבון פעיל' }];
        var logHtml = evs.map(function (e) {
          return '<div class="dosw-logrow">' + dot(e.level === 'error' ? 'error' : e.level === 'warn' ? 'warning' : 'ok') +
            '<span class="dosw-logmsg">' + esc(e.msg) + '</span><span class="dosw-logt">' + ago(e.mins) + '</span></div>';
        }).join('');
        return '<div class="dosw-hcard">' +
          '<div class="dosw-hhead">' + avatar(a, 30) +
            '<div class="dosw-tx"><b>' + esc(a.label) + '</b><small>' + esc(a.identity) + '</small></div>' +
            '<span class="dosw-pill" style="color:' + STCOL[a.status] + ';border-color:color-mix(in srgb,' + STCOL[a.status] + ' 33%,transparent)">' + dot(a.status) + STHE[a.status] + '</span></div>' +
          (a.status !== 'ok' && a.reason ? '<div class="dosw-hreason" style="color:' + STCOL[a.status] + '">' + esc(a.reason) + '</div>' : '') +
          '<div class="dosw-hmeta">נבדק ' + ago(a.checked) + ' · <button class="dosw-recheck" data-id="' + esc(a.id) + '">בדוק שוב</button></div>' +
          '<details class="dosw-hlog"><summary>יומן חיבור (' + evs.length + ')</summary>' + logHtml + '</details>' +
        '</div>';
      }).join('');
      var bad = anyBad();
      var summary = bad === 'ok' ? 'כל החיבורים תקינים' : (bad === 'error' ? 'חיבור אחד או יותר דורשים טיפול' : 'חיבור אחד או יותר דורשים תשומת לב');
      var ov = modal('<h3>מצב החיבורים</h3><div class="dosw-steps">' + APPNAME + ' · ' + ITEMS.length + ' חשבונות · ' + esc(summary) + '</div>' +
        '<div class="dosw-hlist">' + rows + '</div><div class="dosw-row"><button class="dosw-bt" data-x>סגירה</button></div>');
      ov.querySelector('[data-x]').onclick = function () { closeModal(ov); };
      ov.querySelectorAll('.dosw-recheck').forEach(function (btn) {
        btn.onclick = function () {
          var id = btn.getAttribute('data-id');
          for (var i = 0; i < ITEMS.length; i++) if (ITEMS[i].id === id) ITEMS[i].checked = 0;
          closeModal(ov); healthPanel();
        };
      });
    }

    function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }

    reload();
    // keep the switcher present if the app re-renders its sidebar (sidebar fallback mode only —
    // in top mode the switcher lives in the parent #acctBar and is unaffected by app re-renders).
    if (!topMode && side) {
      try {
        new MutationObserver(function () { if (!document.body.contains(wrap) && side.parentNode) { var b = side.querySelector('.brand'); if (b && b.nextSibling) side.insertBefore(wrap, b.nextSibling); else side.insertBefore(wrap, side.firstChild); } })
          .observe(side, { childList: true });
      } catch (e) {}
    }
  });
})();
