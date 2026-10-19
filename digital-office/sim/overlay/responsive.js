/* sim overlay · mobile-first responsive layer — injected into every embedded app AND the console shell.
   Goal: a native, super-app feel on phones (single-column, thumb-reachable, full-screen sub-views) while
   leaving the desktop layout PIXEL-IDENTICAL (every rule is behind a max-width media query). Sim-only;
   edits no real source — the live port would fold these into each app's own stylesheet.

   • Console shell: the real console is already responsive (icon-rail ≤1024px, bottom tab bar ≤640px), but
     the account switcher adds `.has-bar` to `.embedwrap`, flipping `.embed` from position:absolute to
     flex:1 and killing the mobile `.embed{inset:0 0 60px 0}` rule — so an app's bottom 60px hides under
     the nav. We reserve that strip back.
   • Mail / Drive: the live apps, each with a drawer of its own on a phone — nothing is added to them
     here (the mail's fork had none, and this file used to give it one).
   • Docs (my-docs): its `.side` is a horizontal TOP BAR (not a drawer) — let it wrap and its nav scroll;
     the grid scrolls inside its card; the doc drawer is full-screen.
   The sim-authored chat handles its own mobile layout inside wadmin.html. */
(function () {
  var MOBILE = '(max-width:820px)';
  function ready(fn) { if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn); else fn(); }
  function addCss(css) { var s = document.createElement('style'); s.setAttribute('data-sim-overlay', 'responsive'); s.textContent = css; (document.head || document.documentElement).appendChild(s); }

  ready(function () {
    // A10.5/A10.6 — one consistent gesture everywhere: Esc closes the topmost open overlay/drawer/dialog
    // in ANY app (our own overlays already self-handle Esc; this covers the real apps' modals uniformly).
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      var open = document.querySelector('.overlay:not(.hidden),.modal:not(.hidden),[role=dialog]:not(.hidden),#reader:not(.hidden),.drawer:not(.hidden),.lightbox:not(.hidden),.details:not(.hidden)');
      if (!open || open.offsetParent === null) return;
      var c = open.querySelector('.x,.close,[data-x],[aria-label="סגור"],[aria-label="Close"],.modal-close,.drawer-close') || document.getElementById('rClose');
      if (c) { c.click(); return; }
      if (open.classList && open.classList.contains('overlay')) open.click();   // backdrop-dismiss
    }, false);

    if (document.getElementById('frame')) {   // console shell
      // A8.4 density: nudge the desktop hub to medium density — the launcher cards floated in a lot of
      // whitespace. Modest, tasteful tightening (padding + gap), desktop only.
      addCss('@media (min-width:1025px){.grid{gap:13px}.card{padding:16px}.card .t{margin-top:9px}.kpi{gap:11px}}');
      // Astryx App-Shell a11y: a "skip to content" link — first tab stop, hidden until focused, jumps
      // keyboard/screen-reader users past the nav straight to the main content.
      addCss('.do-skip{position:fixed;top:-64px;inset-inline-start:12px;z-index:3000;background:var(--accent);' +
        'color:var(--accent-ink);padding:10px 18px;border-radius:10px;font-weight:700;text-decoration:none;box-shadow:var(--shadow-lg);' +
        'transition:top .16s ease}.do-skip:focus{top:12px;outline:2px solid var(--accent-ink);outline-offset:2px}');
      var main = document.getElementById('content') || document.querySelector('main');
      if (main) {
        if (!main.id) main.id = 'content';
        main.setAttribute('tabindex', '-1');
        var skip = document.createElement('a'); skip.className = 'do-skip'; skip.href = '#' + main.id; skip.textContent = 'דלג לתוכן';
        skip.addEventListener('click', function (e) { e.preventDefault(); main.focus(); main.scrollIntoView(); });
        document.body.insertBefore(skip, document.body.firstChild);
      }
      addCss('@media (max-width:640px){' +
        '.embedwrap.has-bar{padding-bottom:60px;box-sizing:border-box}.embedwrap.has-bar .embed{min-height:0}#acctBar{flex:none}' +
        // reclaim vertical space: the console topbar + account-switcher bar stack above every app on a
        // phone (3 bars in chat). Slim them down so the app gets more of the screen.
        '.topbar{padding:9px 12px!important}.topbar h1{font-size:15.5px!important}' +
        '#acctBar{padding:5px 12px!important}' +
        '.dosw-btn{padding:6px 9px!important}.dosw-btn .dosw-av{width:26px!important;height:26px!important;font-size:11px!important}' +
        '.dosw-tx small{font-size:10.5px!important}' +
        // hub launcher: giant 1-col cards → compact 2-col app tiles (super-app home feel)
        '.grid{grid-template-columns:1fr 1fr!important;gap:10px!important}' +
        '.card{padding:14px 12px!important}' +
        '.card .d{display:none}' +                     // drop the description on tiles
        '.card .t{font-size:13.5px;margin-top:9px}' +
        '.card .ic .ic-svg{width:22px;height:22px}' +
        // KPI stat cards: tighter, and let a lone last card span the row instead of orphaning
        '.kpi{grid-template-columns:1fr 1fr}' +
        '.kpi>*:last-child:nth-child(odd){grid-column:1/-1}' +
        '}');
      return;
    }

    // MAIL (mailview) is the live app, and its side menu is the office's own component (BinaNav): a
    // drawer with its own button where the window is narrow. Like the drive below it gets NO second
    // drawer here — the fork's did, and under the live screen that was a second hamburger over the title.
    if (document.getElementById('msgTable')) return;

    // DRIVE (localdrive) is already fully mobile-native (own drawer + #sideToggle at ≤640) — do NOT add
    // a second drawer. BUT on mobile the tree is in a drawer and no folder auto-loads, so the file area
    // opens BLANK ("בחר תיקייה מהצד"). Auto-open the first/root folder on phones so files show.
    if (document.getElementById('treeList') || document.getElementById('railMount')) {
      // Drive opens to an empty pane ("בחר תיקייה מהצד") on BOTH desktop and mobile until a folder is
      // clicked — poor first impression. Auto-open the first/root folder so files show immediately.
      setTimeout(function () {
        var files = document.getElementById('filesTable');
        // the drive now lands on דף הבית with content; only rescue a genuinely empty pane, and never
        // hijack a view the user chose (an empty אשפה / starred view is a correct empty, not a bug)
        var empty = files && files.querySelector('.empty') &&
                    !files.querySelector('tr[data-id],.gcard[data-id],[data-folder]');
        if (!empty) return;
        var first = document.querySelector('#treeList [role=treeitem],#treeList a,#treeList li[data-id],#treeList .node,#treeList button');
        if (first) first.click();
      }, 1200);
      return;
    }

    // DOCS (my-docs): its `.kpi-strip` is a fixed 4-col grid (the overflow). Drop the KPIs to 2 cols,
    // scroll the data grid, and make the doc drawer full-screen. (The tab row is the app's own now:
    // one row that scrolls inside the bar, in apps/my-docs/static/style.css.)
    if (document.getElementById('docsTable') || document.querySelector('nav a[data-view="docs"]')) {
      addCss('@media ' + MOBILE + '{' +
        '.dash-top{grid-template-columns:1fr!important}' +          /* hero + KPIs stack */
        '.drawer-b{grid-template-columns:1fr!important}' +          /* doc preview + side stack */
        '.kpi-strip{grid-template-columns:repeat(2,1fr)!important;max-width:100%!important}' +
        '.kpi{min-width:0!important}' +
        '.main{max-width:100%!important;padding-inline:12px!important;min-width:0!important}' +
        '#recent,.tablewrap,.bina-table,.bt-card{display:block;width:100%;max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}' +
        '.bt-toolbar{flex-wrap:wrap}' +
        // The document drawer fills the phone - and that is all this layer changes about what is on top of
        // what. It used to lift the drawer, the veil and the modal to 1002 / 1001 / 1003 (the mail's numbers,
        // which exist there for its off-canvas menu; this screen has none) and left the EDITOR at the page's
        // own 50: on a phone the veil lay over the whole new-document editor - none of its fifteen controls
        // was what a finger hit, and the first touch closed it. The page's own order (veil 40, editor and
        // drawer 50, modal 70) is right at every width.
        '#drawer,.drawer{position:fixed!important;inset:0!important;width:100%!important;max-width:none!important}' +
        '}' +
        '@media (max-width:460px){.kpi-strip{grid-template-columns:1fr!important}}');
      return;
    }

    // GENERIC fallback for every other app (incoming-documents, infra dashboards, …): the two things
    // that overflow a phone are horizontal tab-bars/navs and wide data tables. Let both scroll inside
    // themselves instead of pushing the page wide, and let toolbars/filter rows wrap. (The shared
    // table's quick filters are a filter row that calls itself a tablist: kept on one line here, its
    // chips did not scroll - they shrank, each breaking its own words in two. They wrap, as live.)
    addCss('@media ' + MOBILE + '{' +
      'nav,.tabs,.tab-bar,[role=tablist]:not(.bt-chipsrow),.sapMITB,.sapMSegB{max-width:100%!important;overflow-x:auto;-webkit-overflow-scrolling:touch;flex-wrap:nowrap}' +
      'table{display:block;max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}' +
      '.toolbar,.filters,.actions,.filterbar,.btnrow{flex-wrap:wrap}' +
      'main,.main,.content,.container,#root{max-width:100%!important;min-width:0!important}' +
      'img,video,canvas{max-width:100%;height:auto}' +
      '}');
  });
})();
