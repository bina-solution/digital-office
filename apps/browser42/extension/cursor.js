// browser42 agent cursor overlay
// Reads chrome.storage for cursor positions and renders colored dots
// matching each agent session's slug + color.

(function() {
  // The ownership tag MUST land in the page MAIN world: this content script runs in the
  // ISOLATED world, where `window.name = ...` is invisible to the runner's MAIN-world
  // window.name reads (group_tabs/owned_page over Playwright CDP). Inject an inline
  // script so the assignment executes MAIN. Idempotent + cheap; retried on every claim.
  function claim(slug) {
    if (!slug) return;
    window.name = `b42g:${slug}`; // keep ISOLATED consistent too (harmless)
    const script = document.createElement('script');
    script.textContent = `window.name = ${JSON.stringify(`b42g:${slug}`)};`;
    (document.documentElement || document.head || document.body).appendChild(script);
    script.remove();
  }

  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type === 'browser42-claim') claim(message.slug);
  });
  chrome.runtime.sendMessage({ type: 'browser42-whoami' }, (response) => claim(response?.slug));

  if (document.getElementById('browser42-cursor-layer')) return;

  const layer = document.createElement('div');
  layer.id = 'browser42-cursor-layer';
  layer.style.cssText =
    'position:fixed;top:0;left:0;width:100%;height:100%;' +
    'pointer-events:none;z-index:2147483647;';
  document.documentElement.appendChild(layer);

  const cursors = {};

  function tick() {
    chrome.storage.local.get(null, (items) => {
      // Update or create cursor elements for each agent
      for (const [key, val] of Object.entries(items)) {
        if (!key.startsWith('cursor_')) continue;
        const slug = key.replace('cursor_', '');
        let el = cursors[slug];

        if (!val.visible) {
          if (el) { el.remove(); delete cursors[slug]; }
          continue;
        }

        if (!el) {
          el = document.createElement('div');
          el.style.cssText =
            'position:fixed;width:12px;height:12px;border-radius:50%;' +
            'z-index:2147483646;pointer-events:none;' +
            'transition:all 0.1s linear;';
          const label = document.createElement('div');
          label.style.cssText =
            'position:absolute;top:-16px;left:0;font-size:10px;' +
            'white-space:nowrap;color:' + val.color + ';' +
            'text-shadow:0 1px 2px rgba(0,0,0,0.7);';
          label.textContent = val.label || slug;
          el.appendChild(label);
          layer.appendChild(el);
          cursors[slug] = el;
        }

        el.style.left = val.x + 'px';
        el.style.top = val.y + 'px';
        el.style.background = val.color;
        el.style.boxShadow = '0 0 8px 3px ' + val.color;
      }
    });
  }

  setInterval(tick, 200);
  tick();
})();
