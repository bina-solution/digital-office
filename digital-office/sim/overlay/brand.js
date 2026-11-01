/* sim overlay · brand + version (A3/A4) — injected into every embedded app after its mock (build.mjs).
   Runs in the app iframe; edits NO real source.
   • brand rename המרכז → הלשכה הדיגיטלית (only the console shell carries the string, so a global text
     swap is safe; also relabels the single-letter brand logo and the tab title).
   • a visible build version pinned to the bottom of the main side menu — bump DO_VERSION on EVERY
     change so you always know which build you're viewing. Rendered only in the console shell (the one
     doc that has the embed <iframe id="frame">).
   Catalogued in sim/ALIGNMENT-CHANGELOG.md for the live port. */
(function () {
  var BRAND_OLD = 'המרכז', BRAND_NEW = 'הלשכה הדיגיטלית';
  // ⇩ bump this on every sim change ⇩
  var DO_VERSION = '0.26.0';

  function brand() {
    try {
      var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null), n, hits = [];
      while ((n = w.nextNode())) { if (n.nodeValue && n.nodeValue.indexOf(BRAND_OLD) !== -1) hits.push(n); }
      hits.forEach(function (n) { n.nodeValue = n.nodeValue.split(BRAND_OLD).join(BRAND_NEW); });
      var logos = document.querySelectorAll('.logo');
      for (var i = 0; i < logos.length; i++) { if ((logos[i].textContent || '').trim() === 'מ') logos[i].textContent = 'ל'; }
      if (/המרכז/.test(document.title)) document.title = document.title.replace(/המרכז/g, BRAND_NEW);
    } catch (e) {}
  }
  function version() {
    try {
      if (!document.getElementById('frame')) return;                 // console shell only
      var side = document.querySelector('aside.side'); if (!side) return;
      var v = side.querySelector('.do-version');
      if (!v) {
        v = document.createElement('div'); v.className = 'do-version';
        v.style.cssText = 'margin-top:auto;padding:8px 14px 12px;font-size:11px;color:var(--muted);text-align:center;letter-spacing:.02em';
        side.appendChild(v);
      }
      v.textContent = 'digital-office v' + DO_VERSION;
    } catch (e) {}
  }
  function boot() { brand(); version(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
