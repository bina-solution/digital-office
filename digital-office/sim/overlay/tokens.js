/* sim overlay · design tokens (A1) — injected into every embedded app after its mock (build.mjs).
   Runs in the app iframe; edits NO real source.

   NO COLOUR IS WRITTEN HERE. The office has one palette («Olive Grove», platform-base/bina-ui/
   theme-tokens.css) and build.mjs puts it last in every embedded page. This overlay used to force
   the previous palette on the light ground and to define two more themes — a grey accent, and a
   dark ground of its own: three palettes beside the office's. What is left is what is not colour:
   the ramps, two utilities, and handing the GROUND the console chose (light / dark) to an
   embedded app. (The keyboard's focus ring — A10 — was written here; the live screens have it
   now, in the same palette block, so it arrives with the palette and is not said twice.)
   Catalogued in sim/ALIGNMENT-CHANGELOG.md (entry A1) for the live port. */
(function () {
  try {
    var st = document.createElement('style');
    st.setAttribute('data-sim-overlay', 'tokens');
    st.textContent =
      // ── Astryx-extraction Phase 0/1: token ramps (additive; nothing reads them yet so visuals are
      //    unchanged), exposed for the aesthetic pass and future components. The elevations are
      //    built from the palette's own shadow and scrim, as the console's stylesheet builds its. ──
      ':root{' +
        '--space-1:4px;--space-2:8px;--space-3:12px;--space-4:16px;--space-5:24px;--space-6:32px;--space-8:48px;' +
        '--radius-sm:8px;--radius-md:12px;--radius-lg:16px;--radius-pill:999px;' +
        '--elev-1:0 1px 2px color-mix(in srgb,var(--scrim) 12%,transparent);--elev-2:var(--shadow);' +
        '--elev-3:0 6px 20px color-mix(in srgb,var(--scrim) 20%,transparent),0 16px 40px color-mix(in srgb,var(--scrim) 12%,transparent);--elev-4:var(--shadow-lg);' +
        '--dur-fast:.12s;--dur-base:.2s;--dur-slow:.32s;--ease-standard:cubic-bezier(.2,.8,.2,1);' +
      '}' +
      // screen-reader-only utility (Astryx "Visually Hidden")
      '.visually-hidden{position:absolute!important;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;' +
        'clip:rect(0 0 0 0);white-space:nowrap;border:0}' +
      // respect reduced-motion: keep functional feedback but drop long/looping animation
      '@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.001ms!important;' +
        'animation-iteration-count:1!important;transition-duration:.05ms!important;scroll-behavior:auto!important}}';
    (document.head || document.documentElement).appendChild(st);
    // in an embedded app iframe, inherit the ground the console picked (persists across app navigations)
    try {
      if (window.parent && window.parent !== window) {
        var t = window.parent.__DO_THEME;
        if (t) document.documentElement.setAttribute('data-theme', t);
      }
    } catch (e) {}
  } catch (e) {}
})();
