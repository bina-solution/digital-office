/* sim overlay · one icon pack (A2) — injected into every embedded app after its mock (build.mjs).
   Replaces pictographic emoji-as-icons with a single Lucide-style stroke SVG set (24x24, currentColor)
   via a text-node walker + MutationObserver. Edits NO real source. Catalogued in
   sim/ALIGNMENT-CHANGELOG.md (entry A2) for the live port. */
(function () {
  try {
    var st = document.createElement('style');
    st.setAttribute('data-sim-overlay', 'icons');
    st.textContent =
      '.sim-ic{display:inline-flex;align-items:center;justify-content:center;width:1em;height:1em;vertical-align:-0.14em}' +
      '.sim-ic svg{width:1em;height:1em}';
    (document.head || document.documentElement).appendChild(st);
  } catch (e) {}

  var ICONS = {
    inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    message: '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22z"/>',
    globe: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    box: '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
    shuffle: '<path d="M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l6.1-8.6c.8-1.1 2-1.7 3.3-1.7H22"/><path d="m18 2 4 4-4 4"/><path d="M2 6h1.9c1.5 0 2.9.9 3.6 2.2"/><path d="M22 18h-5.9c-1.3 0-2.6-.7-3.3-1.8l-.5-.8"/><path d="m18 14 4 4-4 4"/>',
    webhook: '<path d="M18 16.98h-5.99c-1.66 0-3.01-1.34-3.01-3s1.34-3 3.01-3H18"/><path d="m6 17 3.13-5.78c.53-.97.43-2.22-.26-3.07A3 3 0 1 1 14 7"/><path d="m10 16 3.13 5.78c.53.97 1.66 1.42 2.75 1.09A3 3 0 1 0 13 17"/>',
    'file-text': '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"/><path d="M14 2v5h5"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    tag: '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r="1.5"/>',
    paperclip: '<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 6.34l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
    bug: '<path d="m8 2 1.88 1.88"/><path d="M14.12 3.88 16 2"/><path d="M9 7.13v-1a3.003 3.003 0 1 1 6 0v1"/><path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6"/><path d="M12 20v-9"/><path d="M6.53 9C4.6 8.8 3 7.1 3 5"/><path d="M6 13H2"/><path d="M3 21c0-2.1 1.7-3.9 3.8-4"/><path d="M20.97 5c0 2.1-1.6 3.8-3.5 4"/><path d="M22 13h-4"/><path d="M17.2 17c2.1.1 3.8 1.9 3.8 4"/>',
    receipt: '<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/><path d="M12 17.5v-11"/>',
    refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    folder: '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    mail: '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
    settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    sparkles: '<path d="M9.94 14.32a1 1 0 0 1 .09-1.4l1.36-1.24a1 1 0 0 0 .09-1.4L9.94 8.32"/><path d="M12 3v2"/><path d="M12 19v2"/><path d="M5 12H3"/><path d="M21 12h-2"/><path d="m18.36 5.64-.7.7"/><path d="m6.34 17.66-.7.7"/><path d="m5.64 5.64.7.7"/><path d="m17.66 17.66.7.7"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    chevron: '<path d="m6 9 6 6 6-6"/>',
    plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
    bang: '<path d="M12 5v9"/><path d="M12 19h.01"/>'
  };
  var MAP = {
    '📥': 'inbox', '🔔': 'bell', '💬': 'message', '🌐': 'globe',
    '📦': 'box', '🔀': 'shuffle', '🪝': 'webhook', '📝': 'file-text',
    '🚨': 'alert', '🏷': 'tag', '📎': 'paperclip', '📄': 'file-text',
    '🐛': 'bug', '🧾': 'receipt', '🔄': 'refresh', '🔍': 'search',
    '🔎': 'search', '📁': 'folder', '🎉': 'sparkles',
    '✉': 'mail', '⚙': 'settings'
  };
  // Match each glyph plus an optional VS16 (U+FE0F) variation-selector (e.g. "⚙️" = ⚙ + FE0F). Group 1
  // is the bare glyph for the MAP lookup; the full match is what we advance past (no zero-width remnant).
  var re = new RegExp('(' + Object.keys(MAP).join('|') + ')\\uFE0F?', 'g');
  // `re` is global, so re.test() advances re.lastIndex; reset before each test so no leading match is missed.
  function has(t) { re.lastIndex = 0; return re.test(t); }
  function iconSpan(name) {
    var s = document.createElement('span'); s.className = 'sim-ic';
    s.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + (ICONS[name] || '') + '</svg>';
    return s;
  }
  // The same pack, by NAME, for the overlay's own controls (the switcher's chevron and check, the
  // theme menu's check): they drew a character of a font where the live shell draws an icon.
  window.__simIcon = function (name) { return iconSpan(name).outerHTML; };
  var SKIP = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, SVG: 1, NOSCRIPT: 1 };
  function replaceIn(textNode) {
    var t = textNode.nodeValue;
    if (!t || !has(t)) return;
    re.lastIndex = 0;
    var frag = document.createDocumentFragment(), last = 0, m;
    while ((m = re.exec(t))) {
      if (m.index > last) frag.appendChild(document.createTextNode(t.slice(last, m.index)));
      frag.appendChild(iconSpan(MAP[m[1]]));
      last = m.index + m[0].length;
    }
    if (last < t.length) frag.appendChild(document.createTextNode(t.slice(last)));
    textNode.parentNode && textNode.parentNode.replaceChild(frag, textNode);
  }
  function scan(root) {
    if (!root) return;
    var w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        var p = n.parentNode;
        if (!p || SKIP[p.nodeName] || (p.classList && p.classList.contains('sim-ic'))) return NodeFilter.FILTER_REJECT;
        return has(n.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
      }
    });
    var nodes = [], n;
    while ((n = w.nextNode())) nodes.push(n);
    nodes.forEach(replaceIn);
  }
  function boot() {
    scan(document.body);
    try {
      var mo = new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
          var a = muts[i].addedNodes;
          for (var k = 0; k < a.length; k++) {
            var nd = a[k];
            if (nd.nodeType === 3) replaceIn(nd);
            else if (nd.nodeType === 1) scan(nd);
          }
        }
      });
      mo.observe(document.body, { childList: true, subtree: true });
    } catch (e) {}
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
