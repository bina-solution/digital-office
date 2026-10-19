/* sim overlay · the ground switcher (Astryx extraction · Phase 2) — runs ONLY in the console shell.
   The office has ONE palette («Olive Grove», platform-base/bina-ui/theme-tokens.css — build.mjs puts
   it in every page), on a light ground and on a dark one. This menu chooses the GROUND, or leaves it
   to the device: the three states the live console keeps in `do-theme` ("" / light / midnight). It
   used to offer three PALETTES — emerald, a grey accent, a dark one of its own — which is two more
   than the office has. It sets data-theme on the console doc + the live app iframe, persists the
   choice, and each app self-applies from window.parent.__DO_THEME on load (tokens.js). Sim-only. */
(function () {
  // NB: overlays run in <head> BEFORE <body> is parsed, so the "#frame ⇒ console shell" guard must be
  // checked INSIDE ready() (once the DOM exists), not at script-execution time.
  function ready(fn) { if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn); else fn(); }

  // A swatch shows a GROUND, so it is drawn from the two tokens that do not turn with one: what is
  // written on olive (the light ground's own colour) and what is written on lime (the ink).
  var LIGHT = 'var(--olive-ink)', DARK = 'var(--lime-ink)';
  var THEMES = [
    { id: '', name: 'לפי המכשיר', dot: 'linear-gradient(90deg,' + DARK + ' 50%,' + LIGHT + ' 50%)' },
    { id: 'light', name: 'בהיר', dot: LIGHT },
    { id: 'midnight', name: 'כהה', dot: DARK }
  ];
  // a choice saved when the menu offered palettes (`slate`) names no ground: it is the device's again
  function saved() { try { var t = localStorage.getItem('do-theme'); return t === 'light' || t === 'midnight' ? t : ''; } catch (e) { return ''; } }
  function persist(t) { try { localStorage.setItem('do-theme', t); } catch (e) {} }

  function applyTo(doc, t) {
    if (!doc || !doc.documentElement) return;
    if (t) doc.documentElement.setAttribute('data-theme', t); else doc.documentElement.removeAttribute('data-theme');
  }
  function apply(t) {
    window.__DO_THEME = t;                 // apps read this on (re)load via tokens.js
    applyTo(document, t);                  // the console shell itself
    var f = document.getElementById('frame');
    try { if (f && f.contentDocument) applyTo(f.contentDocument, t); } catch (e) {}   // the live app
    persist(t);
  }

  ready(function () {
    if (!document.getElementById('frame')) return;   // console shell only (checked after DOM is parsed)
    var initial = saved(); if (initial) apply(initial);

    var css = document.createElement('style'); css.setAttribute('data-sim-overlay', 'theme');
    css.textContent =
      '.do-theme{position:relative;display:inline-flex}' +
      '.do-theme-btn{background:transparent;border:1px solid var(--line);border-radius:9px;width:34px;height:34px;cursor:pointer;color:var(--ink);display:grid;place-items:center;flex:none}' +
      '.do-theme-btn:hover{background:var(--surface-2)}' +
      '.do-theme-menu{position:absolute;top:calc(100% + 6px);inset-inline-end:0;background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow-lg);padding:6px;z-index:1200;min-width:150px}' +
      '.do-theme-menu.hide{display:none}' +
      '.do-theme-it{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:8px;cursor:pointer;font-size:13px;color:var(--ink)}' +
      '.do-theme-it:hover{background:var(--surface-2)}' +
      '.do-theme-it .sw{width:16px;height:16px;border-radius:50%;flex:none;box-shadow:inset 0 0 0 1px var(--muted)}' +
      '.do-theme-it .chk{margin-inline-start:auto;color:var(--accent-d);opacity:0}' +
      '.do-theme-it.on .chk{opacity:1}';
    (document.head || document.documentElement).appendChild(css);

    var wrap = document.createElement('span'); wrap.className = 'do-theme';
    wrap.innerHTML = '<button class="do-theme-btn" title="רקע בהיר או כהה" aria-label="רקע בהיר או כהה" aria-haspopup="true">' +
      '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="13.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="10.5" r="2.5"/><circle cx="8.5" cy="7.5" r="2.5"/><circle cx="6.5" cy="12.5" r="2.5"/><path d="M12 2a10 10 0 1 0 0 20 2 2 0 0 0 2-2 2 2 0 0 1 2-2h1a4 4 0 0 0 4-4 10 10 0 0 0-9-10z"/></svg></button>' +
      '<div class="do-theme-menu hide" role="menu"></div>';
    var mount = document.querySelector('.topbar .tb-right') || document.querySelector('.topbar');
    if (!mount) return;
    var searchBtn = mount.querySelector('#paletteBtn');
    if (searchBtn) mount.insertBefore(wrap, searchBtn.nextSibling); else mount.insertBefore(wrap, mount.firstChild);

    var menu = wrap.querySelector('.do-theme-menu');
    function build() {
      var cur = window.__DO_THEME || '';
      menu.innerHTML = THEMES.map(function (t) {
        return '<div class="do-theme-it' + (t.id === cur ? ' on' : '') + '" role="menuitemradio" data-t="' + t.id + '">' +
          '<span class="sw" style="background:' + t.dot + '"></span>' + t.name +
          '<span class="chk">' + (window.__simIcon ? window.__simIcon('check') : '') + '</span></div>';
      }).join('');
      menu.querySelectorAll('.do-theme-it').forEach(function (el) {
        el.onclick = function () { apply(el.getAttribute('data-t')); build(); close(); };
      });
    }
    var open = false;
    function openM() { open = true; build(); menu.classList.remove('hide'); }
    function close() { open = false; menu.classList.add('hide'); }
    wrap.querySelector('.do-theme-btn').onclick = function (e) { e.stopPropagation(); open ? close() : openM(); };
    document.addEventListener('click', function (e) { if (open && !wrap.contains(e.target)) close(); });
    document.addEventListener('keydown', function (e) { if (open && e.key === 'Escape') close(); });
    build();
  });
})();
