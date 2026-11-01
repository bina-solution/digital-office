// הלשכה הדיגיטלית — the unified business-system shell. Builds the nav from the module registry,
// embeds each module in an iframe under shared chrome. The first-run install wizard is its own page
// connections credential plane.
const $ = s => document.querySelector(s);
const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; };

// ── the tile icons: ONE set for every surface that lists apps — a copy of
// platform-base/bina-ui/bina-icons.js, kept byte-identical by gate G27. mIcon() wraps a glyph.
/* @bina-icons:start */
const BINA_ICONS = {
  home:      '<path d="M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
  building:  '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01M12 6h.01M16 6h.01M8 10h.01M12 10h.01M16 10h.01M8 14h.01M12 14h.01M16 14h.01"/>',
  book:      '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  'file-text': '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/>',
  folder:    '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
  mail:      '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 6-10 7L2 6"/>',
  inbox:     '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  message:   '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8z"/>',
  activity:  '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
  bell:      '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
  server:    '<rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/>',
  monitor:   '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
  grid:      '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>',
  check:     '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
  key:       '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L22 7l-3-3"/>',
  workflow:  '<rect width="8" height="8" x="3" y="3" rx="2"/><path d="M7 11v4a2 2 0 0 0 2 2h4"/><rect width="8" height="8" x="13" y="13" rx="2"/>',
  alert:     '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  bang:      '<path d="M12 5v9"/><path d="M12 19h.01"/>',
  database:  '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>',
  box:       '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
  shield:    '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
  external:  '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  chevron:   '<path d="m6 9 6 6 6-6"/>',
  back:      '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  layers:    '<path d="m12 2 9 5-9 5-9-5z"/><path d="m3 12 9 5 9-5"/><path d="m3 17 9 5 9-5"/>',
  refresh:   '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  clock:     '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  link:      '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  plus:      '<path d="M5 12h14"/><path d="M12 5v14"/>',
  trash:     '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>',
  // A2 — the last four icons that were still characters. A glyph is not an icon: ☰ ✕ ↗ ✓ render in
  // whatever the reader's font stack decides, so they land at a different weight and a different
  // optical size from the 20 stroke icons beside them, and on a Hebrew-first stack they can fall
  // through to a fallback face entirely.
  menu:      '<path d="M3 6h18"/><path d="M3 12h18"/><path d="M3 18h18"/>',
  // "there is more behind this" — the desktop dock's overflow door (Feather's more-horizontal)
  more:      '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
  x:         '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  tick:      '<polyline points="20 6 9 17 4 12"/>',
  palette:   '<circle cx="13.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="10.5" r="2.5"/><circle cx="8.5" cy="7.5" r="2.5"/><circle cx="6.5" cy="12.5" r="2.5"/><path d="M12 2a10 10 0 1 0 0 20 2 2 0 0 0 2-2 2 2 0 0 1 2-2h1a4 4 0 0 0 4-4 10 10 0 0 0-9-10z"/>',
  // bina-ds (the office agent) — three candidates so the tile can be re-pointed from app.json alone.
  // `sparkles` is the AI convention every reader already knows; `brain` reads as the literal word
  // בינה; `bot` says "agent". Before these existed, app.json's icon:"sparkles" fell through to the
  // `key` fallback and the agent shared its glyph with the connections tile.
  // [2026-09-25] Owner request: the בינה (bina-ds) tile now points at `bot` — the robot, because the
  // tile opens an agent you talk to, not a star you admire. All three stay mapped so the tile can
  // still be re-pointed from app.json alone.
  sparkles:  '<path d="M9.94 14.34 12 21l2.06-6.66L21 12l-6.94-2.34L12 3 9.94 9.66 3 12z"/><path d="M5 3v4"/><path d="M19 17v4"/><path d="M3 5h4"/><path d="M17 19h4"/>',
  brain:     '<path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/><path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/><path d="M17.599 6.5a3 3 0 0 0 .399-1.375"/><path d="M6.003 5.125A3 3 0 0 0 6.401 6.5"/><path d="M3.477 10.896a4 4 0 0 1 .585-.396"/><path d="M19.938 10.5a4 4 0 0 1 .585.396"/><path d="M6 18a4 4 0 0 1-1.967-.516"/><path d="M19.967 17.484A4 4 0 0 1 18 18"/>',
  bot:       '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>',
  // git-branch — the version-control app's tile: a commit dot forking off a line, the one shape every
  // reader of a git host already knows. Without this entry app.json's icon:"git-branch" falls through
  // to the generic `app` window below.
  //
  // [2026-09-25] THE VOID THIS FILLED, and the reason it read as a mystery on the rail: the console
  // image running that morning had been built BEFORE this key existed, so the גיט tile was showing
  // the FALLBACK window — a real, deliberate-looking browser glyph that git had never asked for. The
  // owner asked for "the window גיט used to have" on אתרים and this glyph back on גיט; the window is
  // now `browser`, below, and it is declared on purpose rather than inherited from a missing key.
  'git-branch': '<line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
  // flt-003 — THE OFFICE ANIMALS (the owner, 2026-10-09): when offices are linked, a person READS
  // which office a thing belongs to, so each office's animal is a glyph here like every other one —
  // 24x24, outline, stroke = currentColor — and never an emoji, which is a font's opinion and lands
  // as a different animal on every OS. The hue that goes with it is a token of theme-tokens.css
  // (--office-hp / -mac / -vps). The office's own record names the animal.
  elephant:  '<circle cx="12" cy="10" r="6.3"/><circle cx="5.2" cy="10.4" r="3"/><circle cx="18.8" cy="10.4" r="3"/><path d="M12 14.8v3.4a2 2 0 0 0 4 0"/><path d="M9.7 7.7h.01M14.3 7.7h.01"/>',
  deer:      '<path d="M12 21a5 5 0 0 1-5-5v-4a5 5 0 0 1 10 0v4a5 5 0 0 1-5 5z"/><path d="M8.1 9 4.6 6.7M15.9 9l3.5-2.3"/><path d="M9 8.3 7.4 2.6M8.2 5.4 10.4 4.2M7.8 3.9 9.6 2.6"/><path d="M15 8.3 16.6 2.6M15.4 5.4 13.2 4.2M16.2 3.9 14.4 2.6"/><path d="M9.8 13.6h.01M14.2 13.6h.01"/><path d="M11 17.4h2"/>',
  eagle:     '<circle cx="12" cy="5.6" r="2.4"/><path d="M14.2 5.4 17 5.2l-2.2 2"/><path d="M11.6 8.4C8.4 8 5.4 6.6 3 4.4c1.2 3.8 3.6 6.6 8.2 8z"/><path d="M12.4 8.4c3.2-.4 6.2-1.8 8.6-4-1.2 3.8-3.6 6.6-8.2 8z"/><path d="M12 8.2v8.4"/><path d="M12 16.6 9.6 21l2.4-1.7 2.4 1.7z"/>',
  // THE REST OF THE VOCABULARY (flt-004). `identity.OFFICE_ANIMALS` names ten animals — the three the
  // owner chose, plus the seven the next offices take — and these seven had no glyph at all, so an
  // office wearing one of them drew mIcon's fallback window instead: the mark's second half missing on
  // every surface at once, and a `fox` office looking exactly like a `lion` one. Measured 2026-10-11
  // against the pairs the derivation hands out. Same hand as the three above — 24x24, outline, stroke
  // = currentColor — and each drawn once, here, in the file that owns the set.
  owl:       '<path d="M5 11.6a7 7 0 0 1 14 0v3a7 7 0 0 1-14 0z"/><path d="M6.6 7 5.2 2.8l4.1 2.3M17.4 7l1.4-4.2-4.1 2.3"/><circle cx="9.3" cy="11.4" r="2.2"/><circle cx="14.7" cy="11.4" r="2.2"/><path d="M12 13.6 10.9 16.2h2.2z"/>',
  fox:       '<path d="M4.4 4.6 5.4 12.2c0 4 3 7 6.6 7s6.6-3 6.6-7l1-7.6-4.6 3.4H9z"/><path d="M12 19.2V21.2"/><path d="M12 12.6 10.8 15h2.4z"/><path d="M9.4 10.6h.01M14.6 10.6h.01"/>',
  horse:     '<path d="M7 21V12.6L11 6.2 14.6 5l3.8 3.6-4.2 2.8v2.8l2.4 2.8V21"/><path d="M11.6 6.2 12.2 3.4l1.6 2"/><path d="M9.6 7.8 11 10.6"/><path d="M15.4 8.4h.01"/>',
  raven:     '<ellipse cx="14" cy="14" rx="4.4" ry="4.2"/><circle cx="9.8" cy="9" r="2.8"/><path d="M7.4 8.4 2.6 9.6l4.8 1.8"/><path d="M16.8 16.4 21 20.4M17.4 15.4 21 19.4"/><path d="M12.4 18v3M15.8 18v3"/><path d="M9.2 8.6h.01"/>',
  hare:      '<path d="M8.4 9.2 6.8 3.2l3.6 2.6M15.6 9.2 17.2 3.2l-3.6 2.6"/><circle cx="12" cy="14" r="4.8"/><path d="M10.3 13.2h.01M13.7 13.2h.01"/><path d="M12 15.4v1.2"/>',
  lion:      '<circle cx="12" cy="12.4" r="5"/><path d="M12 6.4V4.6M9.2 7.2 8 5.6M14.8 7.2 16 5.6M7 10.8 5.2 10M17 10.8l1.8-.8M7 14 5.2 14.8M17 14l1.8.8M9.2 17.6 8 19.2M14.8 17.6 16 19.2M12 18.4v1.8"/><path d="M10.4 11.6h3.2l-1.6 2.2z"/><path d="M12 13.8v1.1M10.8 15.3c.7.8 1.7.8 2.4 0"/><path d="M9.6 10.4h.01M14.4 10.4h.01"/>',
  swan:      '<path d="M6.2 17.4c0-2.6 2.1-4.6 4.6-4.6h2c2.8 0 5 2 5 4.6"/><path d="M11.4 12.6c-1.8-.7-2.9-2.2-2.9-3.9 0-2 1.6-3.6 3.6-3.6"/><circle cx="13.6" cy="5.6" r="1.7"/><path d="M15.2 5.6h2.2"/><path d="M3 19.4h18"/>',
  // The generic fallback for any icon name this set lacks (see mIcon): a plain app window.
  app:       '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M2 8h20"/><path d="M6 4v4"/><path d="M10 4v4"/>',
  // `browser` — the אתרים (sites) tile, and the same window shape as the fallback above, on purpose
  // (owner request, 2026-09-25): a window with a title bar is what a website actually opens in, and
  // it is the glyph the owner had already read as "the sites tile's mark". It is a SEPARATE key and
  // not `app` so the tile declares what it means; the cost is that a genuinely missing icon name and
  // this tile look alike, which is why mIcon's fallback stays documented as a fallback rather than a
  // design. Keyed to app.json icon:"browser".
  browser:   '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M2 8h20"/><path d="M6 4v4"/><path d="M10 4v4"/>',
  settings:  '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
};
/* @bina-icons:end */
/* @bina-ask:start */
var binaAsk, binaTell;
(function () {
  var doc = document;
  var CSS = ".bask{position:fixed;inset:0;z-index:2147483000;display:grid;grid-template:minmax(0,1fr)/minmax(0,1fr);place-items:center;padding:16px;background:var(--scrim)}"
    + ".bask-card{display:flex;flex-direction:column;width:min(440px,100%);max-height:100%;overflow:auto;box-sizing:border-box;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:var(--shadow-lg);font:14px/1.5 var(--font,system-ui,sans-serif);text-align:start;outline:0}"
    + ".bask-card h2{margin:0 0 8px;font-size:16px;font-weight:800;line-height:1.35}"
    + ".bask-read{overflow:auto}.bask-read:not(:empty){min-height:19px}"   // never squeezed to nothing: a line of it stays, and past that the card itself scrolls
    + ".bask-card p{margin:0 0 6px;font-size:13px;color:var(--muted)}"
    + ".bask-read p:last-child{margin:0}"
    + ".bask-facts{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:10px 0 0;padding:10px 12px;background:var(--surface-2);border:1px solid var(--line);border-radius:9px}"
    + ".bask-facts dt{color:var(--muted);font-size:11px;font-weight:600;line-height:1.7}"
    + ".bask-facts dd{margin:0;font-size:12.5px;font-weight:600;overflow-wrap:anywhere;unicode-bidi:plaintext;text-align:right}"
    + ".bask-field{display:grid;gap:5px;margin-top:10px;font-size:12px;font-weight:600;color:var(--muted)}"
    + ".bask-field input{font:inherit;font-size:13px;font-weight:400;height:36px;padding:0 10px;border:1px solid var(--line);border-radius:9px;background:var(--surface);color:var(--ink)}"
    + ".bask-said{margin-top:10px;padding:8px 12px;border-radius:9px;border-inline-start:4px solid var(--red);background:color-mix(in srgb,var(--red) 14%,var(--surface));font-size:12.5px;overflow-wrap:anywhere}"
    + ".bask-said:empty{display:none}"
    + ".bask-acts{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}"
    + ".bask-btn{height:34px;padding:0 16px;border-radius:9px;border:1px solid var(--line);background:transparent;color:var(--ink);font:inherit;font-size:13px;font-weight:700;cursor:pointer}"
    + ".bask-btn.primary{background:var(--accent);border-color:transparent;color:var(--accent-ink)}"
    + ".bask-btn.danger{background:var(--red);border-color:transparent;color:var(--surface)}"
    + ".bask-btn:disabled{opacity:.5;cursor:default}"
    + ".bask-field input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}"
    + "@media (pointer:coarse){.bask-btn{height:44px}.bask-field input{height:44px}}"
    + "@media (max-height:399px){.bask{padding:8px}.bask-card{padding:12px}.bask-acts{margin-top:10px}}"   // the side menu's own short frame
    + "#bina-tell{position:fixed;inset-block-end:16px;inset-inline-start:16px;z-index:2147483001;display:grid;gap:8px;max-width:min(420px,calc(100vw - 32px))}"
    + ".btell{--c:var(--ok);padding:10px 14px;border-radius:12px;background:color-mix(in srgb,var(--c) 14%,var(--surface));color:var(--ink);border:1px solid color-mix(in srgb,var(--c) 38%,var(--surface));border-inline-start:4px solid var(--c);font:13px/1.45 var(--font,system-ui,sans-serif);box-shadow:var(--shadow-lg);cursor:pointer;text-align:start}"
    + ".btell.warn{--c:var(--lime)}.btell.bad{--c:var(--red)}"   // --ok and --red, not the bare hues: they are the steps that are lifted on the dark ground
    + ".btell small{display:block;margin-top:2px;font-size:11.5px;color:var(--muted);overflow-wrap:anywhere;unicode-bidi:plaintext}"
    + ".btell button{margin-inline-start:12px;padding:0;border:0;background:none;font:inherit;font-weight:800;color:var(--blue);text-decoration:underline;cursor:pointer}";

  function el(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function style() {
    if (doc.getElementById("bina-ask-css")) return;
    var s = el("style", "", CSS);
    s.id = "bina-ask-css";
    doc.head.appendChild(s);
  }

  binaAsk = function (q) {
    style();
    return new Promise(function (resolve) {
      var back = doc.activeElement, field = null, must = q.input && q.input.must;
      var scrim = el("div", "bask"), card = el("div", "bask-card"), read = el("div", "bask-read"), said = el("div", "bask-said");
      card.setAttribute("role", "alertdialog");
      card.setAttribute("aria-modal", "true");
      card.setAttribute("dir", "rtl");
      card.setAttribute("tabindex", "-1");
      said.setAttribute("role", "alert");
      card.appendChild(el("h2", "", q.title));
      card.appendChild(read);
      String(q.body || "").split(/\n+/).forEach(function (line) { if (line.trim()) read.appendChild(el("p", "", line)); });
      if (q.facts && q.facts.length) {
        var dl = el("dl", "bask-facts");
        q.facts.forEach(function (f) { dl.appendChild(el("dt", "", f[0])); dl.appendChild(el("dd", "", f[1])); });
        read.appendChild(dl);
      }
      if (q.input) {
        var lab = el("label", "bask-field", q.input.label || "");
        field = el("input");
        field.value = q.input.value || "";
        if (q.input.dir) field.setAttribute("dir", q.input.dir);
        lab.appendChild(field);
        card.appendChild(lab);
      }
      var acts = el("div", "bask-acts"), no = el("button", "bask-btn", q.cancel || "ביטול"),
          yes = el("button", "bask-btn " + (q.danger ? "danger" : "primary"), q.ok || "אישור");
      no.setAttribute("type", "button");
      yes.setAttribute("type", "button");
      acts.appendChild(no);
      acts.appendChild(yes);
      card.appendChild(said);
      card.appendChild(acts);
      scrim.appendChild(card);
      doc.body.appendChild(scrim);

      function fit() { if (must) yes.disabled = field.value.trim() !== must; }
      function home() { (field || (q.danger ? no : yes)).focus(); }
      function done(v) {
        doc.removeEventListener("keydown", key, true);
        scrim.remove();
        if (back && back.focus) back.focus();
        resolve(v);
      }
      function cancel() { if (!no.disabled) done(field ? null : false); }
      function agree() {
        if (yes.disabled) return;
        var v = field ? field.value : true;
        if (!q.run) return done(v);
        yes.disabled = no.disabled = true;                // in flight: busy, and there is nothing left to cancel
        yes.textContent = "מבצע…";
        said.textContent = "";
        card.focus();
        Promise.resolve(v).then(q.run).then(function () { done(v); }, function (e) {
          yes.textContent = q.ok || "אישור";
          yes.disabled = no.disabled = false;
          fit();
          said.textContent = (e && e.message) || "הפעולה נכשלה";
          home();
        });
      }
      function key(e) {
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancel(); }
        else if (e.key === "Enter" && field && doc.activeElement === field) { e.preventDefault(); agree(); }
        else if (e.key === "Tab") {                       // the page behind is not reachable while asked
          var ring = [field, no, yes].filter(function (n) { return n && !n.disabled; });
          var i = ring.indexOf(doc.activeElement);
          e.preventDefault();
          if (ring.length) ring[(i + (e.shiftKey ? ring.length - 1 : 1)) % ring.length].focus();
        }
        else if (/^(Arrow|Page)(Up|Down)$/.test(e.key) && doc.activeElement !== field && read.scrollHeight > read.clientHeight) {
          e.preventDefault();                               // the focus lives on the buttons, outside what scrolls
          read.scrollTop += (/Up$/.test(e.key) ? -1 : 1) * (/^Page/.test(e.key) ? read.clientHeight : 40);
        }
      }
      yes.addEventListener("click", agree);
      no.addEventListener("click", cancel);
      scrim.addEventListener("mousedown", function (e) { if (e.target === scrim) cancel(); });
      if (field) field.addEventListener("input", fit);
      doc.addEventListener("keydown", key, true);
      fit();
      home();
    });
  };

  // The third word is how long the notice stays (ms) — or what more it carries: { ms, more, act, stay }.
  //   more  the service's own sentence, on a line of its own under the notice's words
  //   act   [label, fn] — one way on from the notice (an undo, a refresh): pressing it runs fn and takes the notice down
  //   stay  no clock: the notice is there until it is pressed
  binaTell = function (text, kind, opt) {
    style();
    var o = opt && typeof opt === "object" ? opt : { ms: opt };
    var box = doc.getElementById("bina-tell");
    if (!box) { box = el("div"); box.id = "bina-tell"; doc.body.appendChild(box); }
    var n = el("div", "btell " + (kind || "ok"), text);
    n.setAttribute("role", kind === "bad" ? "alert" : "status");
    n.setAttribute("dir", "rtl");
    if (o.more) n.appendChild(el("small", "", o.more));
    if (o.act) {
      var go = el("button", "", o.act[0]);
      go.setAttribute("type", "button");
      go.addEventListener("click", function (e) { e.stopPropagation(); n.remove(); o.act[1](); });
      n.appendChild(go);
    }
    n.addEventListener("click", function () { n.remove(); });
    box.appendChild(n);
    if (!o.stay) setTimeout(function () { n.remove(); }, o.ms || (kind === "bad" ? 9000 : 5200));
    return n;
  };
})();
/* @bina-ask:end */
function mIcon(name) {
  const p = BINA_ICONS[name];
  return p
    ? `<svg class="ic-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`
    // An unknown name used to render AS TEXT, on the theory that it might be a legacy glyph. It
    // never is: the only callers pass a key, so the fallback printed the key next to the label —
    // "whatsappוואטסאפ · Baileys" in the connect wizard, once provider icons started coming from
    // the services' own catalogues (chat serves icon:"whatsapp"/"telegram", which this set has no
    // glyph for). A missing icon must be INVISIBLE, not a word.
    // The fallback was then `key`, chosen for that wizard (no icon = a credential = a key) — and it
    // leaked into the module rail, where an app whose icon name this set lacked (bina-ds asked for
    // "sparkles" before it existed) showed the same glyph as the connections tile. The generic mark
    // is `app`: a neutral window that says "a tile" and nothing else. The wizard keeps its own
    // explicit `p.icon || "key"` default, so providers still read as credentials.
    : `<svg class="ic-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${BINA_ICONS.app}</svg>`;
}
// BANK-STANDARD re-entrancy guard: disable a button while its write is in flight so a double-click /
// slow response can't fire the same mutation twice. Always re-enables (and restores its label) in finally.
async function guard(btn, fn, loadingLabel) {
  if (!btn || btn.disabled) return;
  const orig = btn.textContent;
  btn.disabled = true; btn.setAttribute("aria-busy", "true");
  if (loadingLabel) btn.textContent = loadingLabel;
  try { return await fn(); }
  finally { btn.disabled = false; btn.removeAttribute("aria-busy"); if (loadingLabel) btn.textContent = orig; }
}
let MODULES = [], ME = null;

// ── apps that live on their own host (compiled `external: true`) ─────────────────────────────────
// The shell FRAMES such an app on that host instead of proxying it: the app keeps its own origin and
// its own login, and the shell shows it in the content frame (and in a desktop window), like any
// other app. The origin is derived here, at click time, from the shell's OWN hostname — the app's
// host label NESTS under it (`console.localhost` → `plane.console.localhost`), because on an
// unregistered TLD the site is the last two labels: nesting keeps both hosts in one site, which is
// what lets the session cookie travel, while `plane.localhost` would be a different site.
// Nothing host-specific is baked into the rendered registry this way.
function externalUrl(m) {
  if (m.url) return m.url;                                  // an app that names its own origin wins
  const label = m.host || m.id;
  const here = String(location.hostname || "");
  const target = here ? label + "." + here : label;
  return location.protocol + "//" + target + (location.port ? ":" + location.port : "") + (m.path || "");
}

// A console on which a REMOTE app's nested host cannot work. Two kinds of address, one answer:
//  · `*.localhost` — every label under `localhost` is its own site, so `auth.localhost` is
//    cross-site to this page: an app framed on its own nested host cannot authorize there (the
//    provider's session cookie is not sent to a cross-site frame, and its login page refuses
//    framing) and the frame shows a browser error.
//  · a name with nothing under it — a bare service name (`console:8000`, which is how anything
//    INSIDE the office's network reaches this console: the office's own browser, an agent) or an
//    IP address. `<alias>.<office>.console` resolves nowhere. Measured 2026-10-05 from the MacBook
//    office's browser: the tile of a linked office framed `drive.hp-laptop.console:8000` — a DNS
//    failure — while the same console answered the app on its own origin.
// On a real domain the nested host resolves and shares a registrable domain with the identity
// provider, so it works — and this is asked of the hostname, once.
function noNestedHost(hostname) {
  const h = String(hostname || "").toLowerCase();
  return /(^|\.)localhost$/.test(h)             // the localhost family
    || !h.includes(".")                          // a bare name (or nothing at all)
    || /^\d{1,3}(\.\d{1,3}){3}$/.test(h)         // an IPv4 address
    || h.includes(":");                          // an IPv6 address
}
const NO_NESTED_HOST = noNestedHost(location.hostname);

// …and the remote apps that have ONLY their own host there. The registry gives a remote app this
// console's own path (`proxy`) when it can live under one; an app that owns its origin — the
// office agent addresses `/api`, `/plugins` and a websocket at the ROOT, and on this origin the root
// is the local agent's — gets none and is framed on its nested host on every console. On a console
// of the kind above that frame cannot sign in by itself, so the host is ASKED first, on the path
// its tile names (`signed_in`), which this office's edge answers itself: a redirect is the sign-in
// door (an unsigned browser is sent to the identity provider), any other answer is a signed-in
// browser, and no answer at all is a name that does not exist from here.
async function ownHostState(m) {
  try {
    const r = await fetch(externalUrl(m) + m.signed_in,
                          { credentials: "include", redirect: "manual", cache: "no-store" });
    return r.type === "opaqueredirect" ? "signin" : "ok";
  } catch (e) {
    return /(^|\.)localhost$/i.test(location.hostname) ? "down" : "address";
  }
}
// …and "signin" is not an errand for the person. The office's sign-in is alive — this page is drawn
// from it — and the host has only never been shown it. So the browser is TAKEN there: a top-level
// load of the path the tile names (`enter`), which this office's edge answers with its sign-in and
// then with this page again, at the tile's own route. Once a minute per host and one trip per page:
// a host that still asks after that gets the card, whose button is the same trip.
function leaveFor(url) { location.assign(url); }
function enterUrl(m) {
  const at = (parseModuleHash() || [])[1] === m.id ? location.hash.slice(1) : "/m/" + m.id;
  return externalUrl(m) + m.enter + at;
}
function enterOwnHost(m) {
  if (enterOwnHost.gone) return true;           // this page is already on its way to one
  const key = "do-enter:" + m.id;
  try {
    if (!m.enter || Date.now() - (+sessionStorage.getItem(key) || 0) < 60000) return false;
    sessionStorage.setItem(key, String(Date.now()));
  } catch (e) { return false; }                 // private mode: no memory of a trip, so no trip
  enterOwnHost.gone = true;
  leaveFor(enterUrl(m));
  return true;
}
let OWN_HOST_WAITING = "";   // the tile whose own host asked for a sign-in (the card is showing)
async function openOwnHost(m, url) {
  const state = await ownHostState(m);
  const cur = parseModuleHash();
  if (!cur || cur[1] !== m.id) return;          // the person moved on while the host was asked
  if (state === "signin" && enterOwnHost(m)) return;
  OWN_HOST_WAITING = state === "signin" ? m.id : "";
  if (state === "ok") return showEmbed(url);
  renderExternalNotice(m, url, state);
}

// ── a tab that stays open ───────────────────────────────────────────────────────────────────────
// The shell is one page that lives for days while the office under it changes: a build is deployed,
// an office is linked, a tile changes where it opens, a sign-in on another host runs out. A page
// loaded before such a change kept drawing the office as it had been — measured 2026-10-05: the
// owner's tab showed a linked office's console as this office's own, an hour after the fix was
// live, because nothing ever told the page. So it asks (`/api/version`) what it should have been
// drawn from, on every navigation, on every return to the tab and every few minutes in view:
//  · a changed REGISTRY is re-read at once, and the tile in view re-opened only if ITS entry changed;
//  · a changed SHELL cannot be patched into a running page, so the page reloads — at the next
//    navigation, where one frame is being replaced by another anyway, never under a person's hands;
//  · a tile on its own host is asked again, so a card becomes the app once the sign-in is done and
//    an app whose sign-in ran out becomes the card instead of "reconnecting…" with no way forward.
//  · and the page's OWN sign-in is asked about with the same request: when it has run out, the edge
//    answers a REDIRECT to the identity provider where a signed-in page gets JSON. The page itself
//    stays, and from then on every request it makes and every frame it opens is sent to the
//    provider — the rail empties and each window is the browser's "could not connect to auth…",
//    with nothing saying why (measured 2026-10-06, hp-laptop, the owner's own tab the morning after).
//    There is one cure, a top-level load, where the provider's sign-in can be shown and where a
//    sign-in that is still alive THERE passes without a keystroke. Taken at once when nothing is
//    under anybody's hands (a navigation, a return to the tab, the first load); otherwise said, with
//    one button.
let STAMP = null;            // what this page was drawn from: {shell, registry}
// A top-level load the edge cannot answer from anybody's cache.
function signInAgain() { location.replace(location.pathname + "?signin=" + Date.now() + location.hash); }
function signedOut(now) {
  if (signedOut.asked) return;         // once: a second answer of the same kind changes nothing
  signedOut.asked = true;
  let last = 0;
  try { last = +sessionStorage.getItem("do-signin") || 0; sessionStorage.setItem("do-signin", String(Date.now())); } catch (e) { /* private mode */ }
  if (now && Date.now() - last > 30000) return signInAgain();      // …but never twice in a row: that is a loop
  const el = document.createElement("div");
  el.className = "modal-ov signed-out"; el.setAttribute("role", "alertdialog"); el.setAttribute("aria-live", "assertive");
  el.innerHTML = `<div class="modal"><div class="modal-h"><h3>הכניסה ללשכה פגה</h3></div>
    <span>כדי להמשיך צריך להיכנס שוב. אחרי הכניסה הלשכה נטענת מחדש, עם החלונות שהיו פתוחים.</span>
    <button class="btn" type="button" title="טוען את הלשכה מחדש דרך מסך הכניסה">כניסה</button></div>`;
  el.querySelector("button").onclick = signInAgain;
  document.body.appendChild(el);
  el.querySelector("button").focus();
}
const stamp = (now) => fetch("/api/version", { cache: "no-store", redirect: "manual" })
  .then(r => r.type === "opaqueredirect" ? (signedOut(now), null) : r.json()).catch(() => null);
// What a tile IS, apart from what was last measured about its office (`remote.ok` / `remote.why`).
// A changed verdict redraws every mark and reloads nothing: one catalog pull that timed out must not
// take a working app out from under a person's hands. The one exception loses nothing — the shell's
// own "office unreachable" card is what is showing, and the office is back.
const tileKey = (m) => JSON.stringify(m, (k, v) => (k === "ok" || k === "why" ? undefined : v));
function isOff(m) { return !!(remoteInfo(m) || {}).off; }
async function freshen(navigating, returned) {
  const now = await stamp(navigating || returned);
  if (!now || !STAMP) return;
  if (now.shell !== STAMP.shell) { if (navigating) location.reload(); return; }
  const cur = parseModuleHash();
  const inView = () => MODULES.find(x => cur && x.id === cur[1]) || null;
  if (now.registry !== STAMP.registry) {
    const was = inView(), wasKey = tileKey(was);
    STAMP = now;
    await refreshModules(false);
    const is = inView();
    const card = !$("#content").classList.contains("hidden") && $("#content .xn");
    if (wasKey !== tileKey(is) || (card && isOff(was) && !isOff(is))) return route();
    if (is) setViewTitle(is);
  }
  if (navigating) return;
  if (window.BinaDesktop && BinaDesktop.isOn()) return BinaDesktop.askOwnHosts();
  const m = inView();
  if (!m || !m.signed_in || !NO_NESTED_HOST) return;
  if (((await ownHostState(m)) === "signin") !== (OWN_HOST_WAITING === m.id)) route();
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) freshen(false, true); });
setInterval(() => { if (!document.hidden) freshen(false); }, 5 * 60 * 1000);

// The card is a FALLBACK, not the destination: it is shown only when the frame does not come up
// (a refused embed, a dead host). A same-origin frame that never left about:blank is the one that
// can be detected; a cross-origin one throws and is by definition loaded.
function externalFallback(m, url) {
  const f = $("#frame");
  let doc = null;
  try { doc = f && f.contentDocument; } catch (e) { return; }   // cross-origin: it loaded
  if (doc && (doc.location.href === "about:blank" || !doc.body || !doc.body.childElementCount)) {
    renderExternalNotice(m, url);
  }
}
// «נסה שוב» on the card of an office marked unreachable: the frame is opened for real, once, whatever
// was last measured — the verdict is up to a minute old, and asking is also what wakes a tunnel.
let ASKED_ANYWAY = "";
function askAnyway(id) {
  if (window.BinaDesktop && BinaDesktop.isOn()) return BinaDesktop.askAnyway(id);
  ASKED_ANYWAY = id; route();
}
// `need` is what an app's own host answered when it was asked first (ownHostState): "signin",
// "address", or nothing — the frame was tried and did not come up.
function renderExternalNotice(m, url, need) {
  $("#embedwrap").classList.add("hidden"); $("#content").classList.remove("hidden");
  setActive(m.id); setViewTitle(m);
  $("#content").innerHTML = externalNotice(m, url, need);
}
// The card itself — drawn in the shell's content and in a desktop window (desktop.js: askOwnHost).
function externalNotice(m, url, need) {
  const r = remoteInfo(m);
  // An app of a linked office is introduced by its office; an app of this one needs no introduction.
  const where = r ? esc(r.label) + " · " : "";
  const lead = r ? `האפליקציה הזאת רצה בלשכת <b>${esc(r.label)}</b> ו` : "האפליקציה הזאת ";
  let sub, body, action = `<a class="btn" href="${esc(url)}" target="_blank" rel="noopener">פתיחה בחלון נפרד</a>`;
  if (need === "signin") {
    sub = `${where}נדרשת כניסה`;
    body = `${lead}נפתחת כאן בכתובת משלה, והכתובת הזאת מבקשת את הכניסה ללשכה.
       לחיצה אחת עוברת דרך מסך הכניסה וחוזרת לכאן, אל האפליקציה.`;
    action = m.enter
      ? `<a class="btn" href="${esc(enterUrl(m))}" title="עובר דרך מסך הכניסה של הלשכה וחוזר לכאן">כניסה</a>`
      : `<a class="btn" href="${esc(url)}" target="_blank" rel="noopener"
       title="פותח את הכתובת של האפליקציה בלשונית חדשה, לכניסה">כניסה</a>`;
  } else if (need === "address") {
    // The address the office was opened at is one hover away, not a number in the sentence.
    sub = `${where}לא ניתנת להצגה מהכתובת הזאת`;
    body = `${lead}נפתחת בכתובת משלה, תחת השם של הלשכה.
       <span title="${esc(location.host)}">הלשכה פתוחה עכשיו בכתובת מספרית</span>, ולכתובת כזאת אין
       שמות תחתיה. פתחו את הלשכה בשם שלה, והאפליקציה תיפתח כאן.`;
    action = "";
  } else if (r) {
    // The remote card names the OFFICE and what is actually wrong with it: a blank frame tells the
    // owner nothing, and "the app did not load" sends them to the wrong office's logs.
    // …and WHICH hop of the link fell, in the office's own measured words (`remote.why`).
    sub = `${esc(r.label)} ${r.off ? "לא זמינה כרגע" : "לא ענתה"}`;
    body = `${lead}מגיעה לכאן דרך הקישור בין הלשכות.
       ${r.off ? esc(r.why || "הלשכה הזאת לא ענתה כרגע — היא מכובה, מנותקת או שהקישור אליה נפל.") : "הטעינה לא הושלמה."}`;
    if (r.off) action = `<div class="xn-acts"><button class="btn" type="button" onclick="askAnyway('${esc(m.id)}')"
       title="פותח את האפליקציה עכשיו, גם אם הלשכה סומנה כלא זמינה">נסה שוב</button>
       <a class="btn ghost" href="${esc(url)}" target="_blank" rel="noopener">פתיחה בחלון נפרד</a></div>`;
  } else {
    sub = "האפליקציה לא נטענה בתוך הלשכה — אפשר לפתוח אותה בחלון נפרד";
    body = `${esc(m.desc || "")}<br><code dir="ltr">${esc(url)}</code>`;
  }
  // ONE card for every "this app is not shown here": it was a title in one corner, a paragraph
  // floating mid-page and, under them, most of a blank screen.
  const mark = need === "signin" ? "shield" : need === "address" ? "link" : "alert";
  return `<div class="xn"><div class="xn-card">
      <span class="xn-ic">${mIcon(mark)}</span>
      <h2>${esc(m.name || "")}</h2>
      <div class="xn-sub">${sub}</div>
      <p>${body}</p>
      ${action}
    </div></div>`;
}
const GROUPS = ["ראשי", "עסק", "תשתית", "הגדרות"];

// ── REMOTE apps: an app that runs on a LINKED office ───────────────────────────────────────────
// ai/context/dgo-remote-apps.md §4. A remote app is `(office, alias)`: it runs THERE, is never
// copied, installed or disabled here, and it appears in every list a local app appears in — the
// rail, the launcher, the phone launcher, the recent-apps cards and the desktop dock — with ONE
// mark and its office's name. The compiler puts `remote: {office, label, port}` on the module entry
// (label = the office's own name, `{he,en}` or a plain string, because "הלשכה הזאת" is not a name
// anyone recognises from the other side); the shell reads those fields and nothing else.
//
// WHICH office is what the mark says, and the shell says it in Hebrew when that office does not
// answer — never a blank frame and never a tile that simply disappears. ONE source of truth for
// that: what the office itself last MEASURED about the link (`remote.ok === false`, and `remote.why`
// — the hop that fell, already a sentence), which the registry carries and every re-read of the
// registry replaces. So a mark appears before anything is opened and goes when the office is back.
// (There was a second source — a set of tiles whose frame this page once saw blank. Nothing ever
// took a tile out of it, so one slow load marked an office dead for the life of the page.)
// An app installed here AND on a linked office is TWO entries with two ids and two tiles; the id is
// the module's own (the compiler's, unique in the registry), never a name derived here.
function remoteInfo(m) {
  const r = m && m.remote;
  if (!r || typeof r !== "object") return null;
  const lab = r.label;
  const label = (typeof lab === "string" ? lab
    : lab && typeof lab === "object" ? (lab.he || lab.en || "") : "") || "";
  const office = String(r.office || "");
  // THE OFFICE'S OWN MARK (flt-004): `{color, animal}` — NAMES, never a value. The colour is drawn
  // by the palette's `[data-office-hue="<name>"]` rules (one per family, so the ground re-points it
  // by itself) and the animal is a glyph of the icon set below, the same one every other icon comes
  // from. An office that publishes neither is still the office the row names, so the mark is simply
  // absent and every surface draws exactly what it drew before this existed.
  const mk = (r.mark && typeof r.mark === "object") ? r.mark : null;
  return { office, label: label || office, off: r.ok === false, why: String(r.why || ""),
           hue: mk && mk.color ? String(mk.color) : "",
           animal: mk && mk.animal ? String(mk.animal) : "" };
}
// DOES THIS APP MATCH WHAT WAS TYPED — one answer, for every place a person types to find an app
// (⌘K, the desktop dock's «עוד» panel). It was written twice, both times as a case-sensitive
// search of the Hebrew name and description: typing `drive`, `Drive` or `macbook` found nothing in
// an office that has all three (hp-laptop, 2026-10-06 — 24 apps, 0 hits). A person types what they
// call the thing: its name, what it says it does, its id (`drive`, `plane`, `bina.macbook`) or the
// office it runs on — in whatever case their keyboard is in.
function moduleMatches(m, typed) {
  const q = String(typed || "").trim().toLocaleLowerCase();
  if (!q) return true;
  const r = remoteInfo(m);
  return [m.name, m.desc, m.id, r ? r.label : "", r ? r.office : ""]
    .join(" ").toLocaleLowerCase().includes(q);
}
// `<title> · <office label>` — the tooltip every surface of the shell uses for a remote app, and the
// one string the CLI/agent side can point at when asking "which of these two is the Mac's".
function remoteTip(m) {
  const r = remoteInfo(m);
  if (!r) return m.name || "";
  // The office's ANIMAL in words, beside its name: the rail's meta column is 5em and cannot carry a
  // glyph next to a name, so the mark's second half is said here — where the first half (the colour)
  // is drawn on the tag itself by `[data-office-hue]`.
  const said = r.animal ? ` (${r.animal})` : "";
  return r.off ? `${m.name} · ${r.label}${said} לא זמינה כרגע${r.why ? " — " + r.why : ""}`
               : `${m.name} · ${r.label}${said}`;
}
// `office-<id>` is what a stylesheet colours with: the token family `--office-hp/-mac/-vps` lives in
// platform-base/bina-ui/theme-tokens.css (and only there — G27/G82), and `remoteInfo` already carries
// the office's own id, so a row or a tile says WHOSE app it is without a second registry.
const remoteCls = (m) => { const r = remoteInfo(m); return r ? " is-remote office-" + r.office + (r.off ? " is-offline" : "") : ""; };
// The office line under a TILE (the phone launcher, the dock's «עוד» panel): whose app this is — and,
// when that office is not answering, that it is not, on a line of its own. A phone has no tooltip,
// and one line cut both halves ("MacBook לא זמי…").
function officeLine(m) {
  const r = remoteInfo(m);
  return !r ? "" : `<span class="htile-office${r.off ? " off" : ""}">${r.animal ? `<span class="office-animal">${mIcon(r.animal)}</span>` : ""}${esc(r.label)}${r.off ? "<br>לא זמינה כרגע" : ""}</span>`;
}

// `data-office-hue="<name>"` — the office's colour, on whatever element the surface already builds for
// that office (flt-004). The ONE spelling of the attribute: every surface that draws into a string
// takes it from here (the launcher tile, the palette row, the switcher card, the chip in the title
// bar, the desktop dock's icons and its «עוד» panel), and the two that build a NODE instead (the
// phone tab bar, the dock's app icon) set the same attribute from `remoteInfo`, which is where this
// helper reads it too. One CSS rule per surface paints it from the palette. Absent when the office
// publishes no colour: the surface draws exactly what it drew before.
function officeHue(m) {
  const r = remoteInfo(m);
  return r && r.hue ? ` data-office-hue="${esc(r.hue)}"` : "";
}


// ── the office record, read once per boot ──────────────────────────────────────
// One in-flight-or-last promise shared by every reader; `fresh=true` starts a new fetch. (The
// connections cache that sat beside it served the old install screen's rows and went with it.)
let _officeP = null;
function getOffice(fresh) {
  if (fresh || !_officeP) _officeP = fetch("/api/office").then(r => r.ok ? r.json() : null).catch(() => null);
  return _officeP;
}

// ── the brand line names the OFFICE ─────────────────────────────────────────────
// The name the install wizard asked for (the `office:` record the control plane keeps — /api/office)
// is the ONE place this office's name is kept: "ניהול תהליכים עסקיים של <name>" once the wizard has
// run, and the bare "ניהול תהליכים עסקיים" until then. index.html ships the bare form, so the frame
// before this resolves reads as a sentence rather than as a placeholder or as the wrong office. The
// business's trading name and registration number are the ledger's own (apitools), not the shell's:
// the install screen that collected them here is gone (core-003).
function applyBrand(rec) {
  const office = rec && rec.installed && rec.office ? rec.office : null;
  const name = office && office.name ? String(office.name).trim() : "";
  const sub = name ? `ניהול תהליכים עסקיים של ${name}` : "ניהול תהליכים עסקיים";
  const s = $("#brandSub"); if (s) s.textContent = sub;
  document.title = `הלשכה הדיגיטלית · ${sub}`;
}

async function refreshModules(reroute = true) {
  const list = (await fetch("/api/modules").then(r => r.json()).catch(() => ({}))).modules || [];
  // ONE entry per id: the hash grammar addresses a module by id (`#/m/<id>`), so two entries sharing
  // one id are one unreachable tile and two identical rail rows. A remote entry carries its own id —
  // `<alias>.<office>` when a local app already owns the alias — and this is the guard that says so
  // out loud instead of rendering the confusion.
  MODULES = [];
  for (const m of list) {
    if (MODULES.some((x) => x.id === m.id)) {
      console.warn("[console] the registry names module id twice — keeping the first:", m.id, m.remote || "");
      continue;
    }
    // A REMOTE app on such a console is framed through this console's OWN origin (`proxy`, served by
    // the console's same-origin proxy exactly like a local app) instead of on its nested host. Decided
    // here, once, so every surface that opens a module — the frame, a desktop window, the phone —
    // gets the same answer; the tile keeps its `remote` mark, which is what names the office.
    if (m.proxy && m.external && NO_NESTED_HOST) { m.external = false; m.embed = m.proxy; }
    MODULES.push(m);
  }
  buildNav();
  buildBottomNav();
  if (window.BinaDesktop) BinaDesktop.refresh();   // desktop mode's dock lists the same modules
  if (reroute) route();
}

async function boot() {
  ME = await fetch("/api/me").then(r => r.json()).catch(() => ({ name: "אורח" }));
  $("#userBox").innerHTML = `מחובר/ת<br><b>${esc(ME.name)}</b>`;
  STAMP = await stamp(true);
  // …and the same answer names the build in the side nav (an unknown one leaves the placeholder).
  if (STAMP && STAMP.version) $("#buildVer").textContent = "digital-office " + STAMP.version;
  await refreshModules(false);
  applyRail();
  const rt = $("#railToggle"); if (rt) rt.onclick = toggleRail;
  const pb = $("#paletteBtn"); if (pb) pb.onclick = openPalette;
  focusInit();
  buildBottomNav();
  // The palette (theme) menu that used to be built here is gone with the top bar's other two
  // ornaments (owner, 2026-09-25 — see index.html). The theme itself is still APPLIED below:
  // `do-theme` may already be in localStorage from when the menu existed.
  applyThemeTo(document, themeSaved());
  // The brand line names the OFFICE — read on every boot (one cached request, see the fetch cache
  // above), because a deep link into an app must not show the generic brand line either.
  applyBrand(await getOffice());
  openLoad();
  // Desktop mode (desktop.js, opt-in from the settings view) mounts before the first route, so that
  // route() opens a WINDOW for the addressed module instead of filling the single frame.
  if (window.BinaDesktop) BinaDesktop.boot();
  // First-run is the SERVER's decision now (app.py spa(): a fresh office — no `installed_at` in the
  // control plane's record — is served install.html instead of this shell), so a bare visit that
  // reaches this line is an installed office, and it opens on its first tile.
  route();
}
window.addEventListener("hashchange", () => { route(); freshen(true); });
window.addEventListener("message", e => {
  if (e.origin !== location.origin) return;
  if (!e.data || e.data.type !== "platform:modules-changed") return;
  refreshModules();
});

// ── phone mode ────────────────────────────────────────────────────────────────
// The breakpoint the stylesheet already hides the rail at. Declared once here so the sheet and
// the router cannot disagree about which mode the shell is in.
const PHONE = window.matchMedia("(max-width: 640px)");

// ── the home screen (phone only) ─────────────────────────────────────────────
// On a desktop the rail IS the launcher — that was an owner decision (2026-09-25: the old
// "לוח בקרה" screen only restated the rail beside it) and it still holds. On a phone the rail is
// hidden, so the same decision leaves a user with a bottom bar of four items and no way to see the
// other twelve apps. This is that screen, and it exists ONLY where the rail does not: the desktop
// path through route() is untouched.
//
// The tiles come from MODULES — the compiled registry — so a newly installed app appears here by
// itself, and the four pinned ids in the bottom bar are the only hard-coded thing left.
function renderHome() {
  setActive(null);
  setViewTitle(null);
  showContent();
  const groups = [];
  for (const m of MODULES) {
    let g = groups.find((x) => x.name === (m.group || ""));
    if (!g) { g = { name: m.group || "", mods: [] }; groups.push(g); }
    g.mods.push(m);
  }
  const tile = (m) => `<a class="htile${remoteCls(m)}"${officeHue(m)} href="#/m/${esc(m.id)}" data-hid="${esc(m.id)}">
      <span class="htile-ic">${mIcon(m.icon)}</span>
      <span class="htile-nm">${esc(m.name)}</span>
      ${officeLine(m)}
    </a>`;
  $("#content").innerHTML = `<div class="home">
    <div class="home-head">
      <div class="home-clock num" id="homeClock"></div>
      <div class="home-brand"><b>הלשכה הדיגיטלית</b>
        <small>${MODULES.length} אפליקציות מותקנות</small></div>
    </div>
    ${groups.map((g) => `${g.name ? `<div class="home-group">${esc(g.name)}</div>` : ""}
      <div class="home-grid">${g.mods.map(tile).join("")}</div>`).join("")}
  </div>`;
  const tick = () => {
    const el = $("#homeClock");
    if (!el) return;
    el.textContent = new Date().toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });
  };
  tick();
  clearInterval(renderHome._t);
  renderHome._t = setInterval(tick, 20000);
}

function buildNav() {
  // The markup is the shared side menu's (platform-base/bina-ui/bina-nav.css, gate G27):
  // .bnv-scroll > .bnv-group > (.bnv-ghead > .bnv-gtitle) + .bnv-list > .bnv-item(.is-active) with
  // .bnv-ic + .bnv-label. EXACTLY that, because the component can only hide what it can name: the
  // group's name used to be bare text in `.bnv-group`, so in the icon rail — every tablet, and a
  // desktop that collapsed it — the names stayed and were cut off at 56px (measured 2026-10-06).
  // The shell contributes the ids and the handler — never a size, a colour or a hover state.
  // A remote app's row is the same markup plus `is-remote`; the mark itself is declared in the
  // component (bina-nav.css), because a rail the component draws is a rail the component marks.
  const nav = $("#nav"); nav.innerHTML = "";
  for (const g of GROUPS) {
    const mods = MODULES.filter(m => m.group === g);
    if (!mods.length) continue;
    const grp = nav.appendChild(el("div", "bnv-group")), n = el("div", "bnv-list");
    if (g) grp.appendChild(el("div", "bnv-ghead", `<span class="bnv-gtitle">${esc(g)}</span>`));
    for (const m of mods) {
      const r = remoteInfo(m);
      const a = el("a", "bnv-item" + remoteCls(m),
        `<span class="bnv-ic">${mIcon(m.icon)}</span><span class="bnv-label">${esc(m.name)}</span>` +
        // The office's name is the SECOND column, and it is what tells the two tiles of one alias
        // apart in the rail ("בינה ודעת · MacBook" beside "בינה ודעת"). An office that is not
        // answering says so in FORM — the tag in the failure colour, the row dimmed (bina-nav.css,
        // `.is-offline`) — and in words in the row's tooltip: the column is 5em, the words never fit.
        (r ? `<span class="bnv-meta" data-office="${esc(r.office)}"${r.hue ? ` data-office-hue="${esc(r.hue)}"` : ""}>${esc(r.label)}</span>` : ""));
      a.dataset.id = m.id; a.title = remoteTip(m);   // title = tooltip when the rail is collapsed to icons
      a.onclick = () => location.hash = "#/m/" + m.id;   // external modules frame their own host
      n.appendChild(a);
    }
    grp.appendChild(n);
  }
}

// ── collapsible icon rail ──────────────────────────────────────────────────────
// The rail collapses to a 62px icon strip so an embedded app gets full width (VS Code / Slack model).
// Manual toggle, persisted; also auto-collapses at tablet width via CSS.
// The band where the rail is the only thing that fits. A media query cannot set a CLASS, and the
// component's rail trigger is a class (so the geometry lives in one file) — so the shell asks the
// same question in JS. The old version hid the labels with a second copy of the rail's rules in the
// media query, which is exactly the duplication bina-nav.css exists to remove.
const RAIL_BAND = window.matchMedia("(max-width:1024px) and (min-width:641px)");
function applyRail() {
  const collapsed = localStorage.getItem("railCollapsed") === "1" || RAIL_BAND.matches;
  // ONE class on the shell. `.rail-host` is the component's own trigger, so what a rail looks
  // like is defined in bina-nav.css for every app — the shell only says whether it is one.
  document.getElementById("app").classList.toggle("rail-host", collapsed);
  document.getElementById("app").classList.toggle("rail-collapsed", collapsed);
  const t = $("#railToggle"); if (t) t.setAttribute("aria-expanded", String(!collapsed));
}
if (RAIL_BAND.addEventListener) RAIL_BAND.addEventListener("change", applyRail);
function toggleRail() {
  const now = localStorage.getItem("railCollapsed") === "1";
  localStorage.setItem("railCollapsed", now ? "0" : "1");
  applyRail();
}

// ── full screen: the app in the whole screen, and a way back that cannot be hidden ──────────────
// The owner's ask (2026-10-12): «איך כדאי לאפשר מצב מסך מלא וחזרה כדי לאפשר את ייעול השימוש במסך».
// On a phone the shell's own chrome is paid twice — 58px of top bar above the app, 60px of tab bar
// below — and 15% of the screen is not a detail. Two layers, one control, because whoever is holding
// the phone does not care which of them is which:
//
//   * the SHELL's chrome goes by the class `bare`, which desktop.css already defines for a console
//     view shown inside a desktop window (html.bare .side/.topbar/.bottomnav). Same rule, given a
//     door a phone can reach — plus ONE line it needs to be honest, in style.css: the phone block
//     reserves the tab bar's 60px inside the embed (.embed{inset:0 0 60px 0}), and a reservation
//     without the bar is a 60px hole under the app.
//   * the BROWSER's own chrome goes by the Fullscreen API, where the browser allows it: no page can
//     hide an address bar any other way. A refusal or an unsupported browser is not a failure of
//     this mode — the API is asked for, never depended on.
//
// The way back is the chip in index.html, Esc, or the phone's own back button — and NOT only the
// button that just disappeared with the chrome: a state that hides its own control is a trap, and
// this is the one place the shell could set one.
const FOCUS_KEY = "do-focus";
// How long the exit control keeps its words after full screen begins: long enough to be read and
// remembered, short enough that it does not sit on an app's own corner for the rest of the session.
const FOCUS_LABEL_MS = 5000;
let focusLabelT = 0;
const focusSaved = () => { try { return localStorage.getItem(FOCUS_KEY) === "1"; } catch (e) { return false; } };
const focusOn = () => document.documentElement.classList.contains("focus");
function applyFocus(on, opts) {
  const save = !opts || opts.save !== false;
  document.documentElement.classList.toggle("focus", on);
  document.documentElement.classList.toggle("bare", on);
  const b = $("#focusBtn");
  if (b) {
    const label = on ? "יציאה ממסך מלא" : "מסך מלא";
    b.setAttribute("aria-pressed", String(on));
    b.title = label; b.setAttribute("aria-label", label);
  }
  if (save) { try { localStorage.setItem(FOCUS_KEY, on ? "1" : "0"); } catch (e) { /* private mode */ } }
  clearTimeout(focusLabelT);
  document.documentElement.classList.toggle("focus-armed", on);
  if (on) focusLabelT = setTimeout(() => document.documentElement.classList.remove("focus-armed"), FOCUS_LABEL_MS);
  if (!on) leaveFullscreen();
}
function askFullscreen() {
  if (!document.fullscreenEnabled || !document.documentElement.requestFullscreen) return;
  document.documentElement.requestFullscreen().catch(() => { /* refused: focus mode is still on */ });
}
function leaveFullscreen() {
  if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(() => {});
}
function toggleFocus() {
  if (focusOn()) { applyFocus(false); return; }
  applyFocus(true);
  askFullscreen();
  // An entry of its own, so the phone's back button is a way out as well. (`#` routes use the hash,
  // so this does not disturb the router.)
  try { history.pushState({ doFocus: 1 }, ""); } catch (e) { /* about:blank frames */ }
}
function focusInit() {
  // A console view inside a desktop WINDOW arrives as `?bare=1` and is desktop.js's business: its
  // chrome is deliberately off there, and a floating exit button inside such a window would be
  // chrome of its own.
  if (new URLSearchParams(location.search).has("bare")) return;
  const fb = $("#focusBtn"); if (fb) fb.onclick = toggleFocus;
  const fx = $("#focusExit"); if (fx) fx.onclick = () => applyFocus(false);
  window.addEventListener("popstate", () => { if (focusOn()) applyFocus(false); });
  window.addEventListener("keydown", e => { if (e.key === "Escape" && focusOn()) applyFocus(false); });
  // A remembered choice is re-applied, and WITHOUT asking for the browser's fullscreen: browsers
  // grant that to a gesture only, and a page that asks on load is refused — silently, every time.
  if (focusSaved()) applyFocus(true, { save: false });
}

// ── B6 · theming: applied, not switched ────────────────────────────────────────
// A theme is JUST a set of CSS-variable overrides — the palettes live in style.css keyed on
// :root[data-theme], and the shell only decides which attribute is set. No JS touches a colour.
//
// The top bar's palette MENU was removed on the owner's request (2026-09-25), together with #hint
// and #installPill beside it: three ornaments that named no screen and no state the rail did not
// already carry. What stays is the APPLICATION of a theme, because `do-theme` may already be in
// localStorage from when the menu existed.
//
// "" means no attribute at all, which is not the same as "light": it lets @media
// (prefers-color-scheme) decide, so a person whose machine is dark gets a dark console without ever
// choosing anything.
const themeSaved = () => { try { return localStorage.getItem("do-theme") || ""; } catch (e) { return ""; } };
function applyThemeTo(doc, t) {
  if (!doc || !doc.documentElement) return;
  if (t) doc.documentElement.setAttribute("data-theme", t);
  else doc.documentElement.removeAttribute("data-theme");
}
// The embedded app is same-origin (the console proxies every app under /a/<name>/), so the shell can
// set the attribute on the app's own document and the app's bundled bina-ui.css does the rest. If a
// future app is ever cross-origin this throws and is swallowed: a themed shell around an unthemed
// app is a blemish, an exception during navigation is a broken console.
function themeIntoFrame() {
  const f = $("#frame");
  try { if (f && f.contentDocument) applyThemeTo(f.contentDocument, themeSaved()); } catch (e) {}
}

// ── ⌘K / Ctrl-K command palette ────────────────────────────────────────────────
function openPalette() {
  closePalette();
  const ov = el("div", "pal-ov");
  const box = el("div", "pal");
  box.innerHTML = `<input id="palInput" class="pal-input" placeholder="חיפוש מסך…  (Esc לסגירה)" autocomplete="off">
                   <div id="palList" class="pal-list"></div>`;
  ov.appendChild(box); document.body.appendChild(ov);
  ov.onclick = e => { if (e.target === ov) closePalette(); };
  const input = $("#palInput"), list = $("#palList");
  let items = [], sel = 0;
  const render = () => {
    items = MODULES.filter(m => moduleMatches(m, input.value));
    if (sel >= items.length) sel = Math.max(0, items.length - 1);
    list.innerHTML = items.map((m, i) => {
      const r = remoteInfo(m);
      // The palette's second column is what a search result is FILTERED on and what a person needs
      // to choose between two rows of the same name: for a remote app, the office it runs on (and
      // that it is not answering, when that is what was observed).
      //
      // The office is added here only when `desc` does not already END with it, because the
      // compiler appends it to a remote app's description itself (`serve.py`: every one of the 29
      // remote tiles carries `… · <office>`). Adding it unconditionally read "… · HP · HP" in the
      // palette — found on 2026-10-05 in a screenshot of the move's own tile, where the row's two
      // halves said the same thing.
      //
      // …and only for a REMOTE app at all: `r` is null for an app of this office, which is most of
      // them. 65e6f3d2 read `r.off` before asking, so the palette threw on its first local row and
      // ⌘K opened nothing, on every office that ran that build (hp-laptop from 2026-10-06 00:45
      // until this fix) — unseen because no flow ever opened the palette. `console/find` in
      // digital-office/sim/flow-qa.py does now, and it is what found this.
      let d = m.desc || "";
      if (r) {
        const who = r.label && !d.trimEnd().endsWith(r.label) ? `${d ? " · " : ""}${r.label}` : "";
        d = `${d}${who}${r.off ? " לא זמינה כרגע" : ""}`;
      }
      return `<div class="pal-item${i === sel ? " sel" : ""}${remoteCls(m)}"${r && r.hue ? ` data-office-hue="${esc(r.hue)}"` : ""} data-i="${i}" title="${esc(remoteTip(m))}"><span class="pal-ic">${mIcon(m.icon)}</span>` +
        `<span class="pal-t">${esc(m.name)}</span><span class="pal-d">${esc(d)}</span></div>`;
    }).join("")
      || `<div class="pal-empty">אין תוצאות</div>`;
    list.querySelectorAll(".pal-item").forEach(d => {
      d.onmousemove = () => { sel = +d.dataset.i; markSel(); };
      d.onclick = () => go(+d.dataset.i);
    });
  };
  const markSel = () => list.querySelectorAll(".pal-item").forEach(d =>
    d.classList.toggle("sel", +d.dataset.i === sel));
  const go = i => { const m = items[i]; if (m) { closePalette(); location.hash = "#/m/" + m.id; } };
  input.oninput = render;
  input.onkeydown = e => {
    if (e.key === "ArrowDown") { sel = Math.min(items.length - 1, sel + 1); markSel(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); markSel(); e.preventDefault(); }
    else if (e.key === "Enter") { go(sel); e.preventDefault(); }
    else if (e.key === "Escape") closePalette();
  };
  render(); input.focus();
}
function closePalette() { const o = document.querySelector(".pal-ov"); if (o) o.remove(); }
window.addEventListener("keydown", e => {
  if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) { e.preventDefault(); openPalette(); }
});

// ── mobile bottom tab bar (shown < 640px via CSS; the rail is hidden there) ──
function buildBottomNav() {
  const old = document.querySelector(".bottomnav"); if (old) old.remove();
  // The four business apps, in rail order — the same four a phone user actually opens. Any pick
  // that isn't installed is dropped rather than rendered dead.
  const picks = ["drive", "mail", "chat", "incoming"].map(id => MODULES.find(m => m.id === id)).filter(Boolean);
  const bn = el("div", "bottomnav");
  // Home first, always: on a phone it is the only way to the twelve apps the three picks below
  // do not cover. `#/` renders the launcher (see route()).
  const homeBtn = el("a", "bn-item", `<span class="bn-ic">${mIcon("home")}</span><span>בית</span>`);
  homeBtn.dataset.id = "";
  homeBtn.onclick = () => { location.hash = "#/"; };
  bn.appendChild(homeBtn);
  for (const m of picks) {
    // A pick that runs on a LINKED office carries the office's mark here too (flt-004): the hue on the
    // tab (the palette's own rule colours the corner bracket) and the animal BESIDE THE NAME, because
    // a phone has no tooltip and the mark would otherwise be a colour nobody can name.
    const r = remoteInfo(m);
    const a = el("a", "bn-item" + remoteCls(m),
      `<span class="bn-ic">${mIcon(m.icon)}</span><span>${esc(m.name)}${r && r.animal ? ` <span class="office-animal">${mIcon(r.animal)}</span>` : ""}</span>`);
    if (r && r.hue) a.dataset.officeHue = r.hue;
    a.dataset.id = m.id; a.title = remoteTip(m); a.onclick = () => location.hash = "#/m/" + m.id;
    bn.appendChild(a);
  }
  // Open apps, between the picks and "more": a phone user needs one tap back to what they were
  // doing, not a search box. The count is the whole affordance that something is waiting.
  const rec = el("a", "bn-item",
    `<span class="bn-ic">${mIcon("layers")}<span class="bn-badge" id="bnOpen"></span></span><span>פתוחים</span>`);
  rec.onclick = () => renderSwitcher();
  bn.appendChild(rec);
  const more = el("a", "bn-item", `<span class="bn-ic">${mIcon("menu")}</span><span>עוד</span>`);
  more.onclick = openPalette;
  bn.appendChild(more);
  document.body.appendChild(bn);
}

function updateOpenBadge() {
  const b = document.getElementById("bnOpen");
  if (!b) return;
  b.textContent = OPEN.length ? String(OPEN.length) : "";
  b.classList.toggle("on", OPEN.length > 0);
}

function setActive(id) {
  updateOpenBadge();
  document.querySelectorAll(".bnv-item, .bottomnav .bn-item")
    .forEach(a => a.classList.toggle(a.classList.contains("bnv-item") ? "is-active" : "active",
                                     a.dataset.id === id));
  // …and the open tile is IN VIEW in the rail: the list is longer than the screen, and for the
  // tiles under the fold nothing was highlighted — the rail said no app was open.
  const on = document.querySelector("#nav .bnv-item.is-active");
  if (on) on.scrollIntoView({block: "nearest"});
}
// The top bar names the screen — and, for a linked office's tile, WHOSE it is. The same title over
// the same «הסר» / «מחק סודות» was this office's screen and the other's; the only difference was a
// pale tag in the rail, and for a tile under the fold not even that.
function setViewTitle(m) {
  const r = m ? remoteInfo(m) : null;
  $("#viewTitle").innerHTML = !m ? "" : esc(m.name || "")
    + (r ? `<span class="vt-office${r.off ? " is-off" : ""}"${r.hue ? ` data-office-hue="${esc(r.hue)}"` : ""} title="${esc(remoteTip(m))}">${r.animal ? `<span class="vt-animal">${mIcon(r.animal)}</span>` : ""}${esc(r.label)}</span>` : "");
}

// The rail IS the launcher: the shell has no home screen, so a hash naming no live module (first
// load, or a bookmark to an uninstalled app) opens the FIRST tile in it. location.replace, not
// assignment, so the dead hash doesn't become a history entry the back button returns to.
// The ONE parser of the shell's hash grammar: #/m/<id>[/inner/path][?query].
// [1] = module id, [2] = the embedded app's inner route (or undefined).
function parseModuleHash() {
  return /^#\/m\/([^/?#]+)([/?].*)?$/.exec(location.hash || "#/");
}

// Module ids that were RENAMED, old -> new.
//
// A console URL is a permanent address: it is in the owner's bookmarks, in ai/context, in the sim's
// ui-map and on every screenshot ever taken. So a rename ADDS a line here and never repoints or
// removes the old route. Without this the old hash names no live module and route() falls through
// to "open the FIRST tile", which is not a 404 the user can see — it silently teleports them to
// drive, exactly the failure the #content guard above was added for.
//
// `whatsapp` -> `chat` (2026-09-02): the module stopped being a WhatsApp bot and became the chat
// service — local profiles, Telegram and Baileys behind one API — so the id was the last place
// still naming one transport. The app's alias and service were already `chat`.
const LEGACY_MODULE_IDS = { whatsapp: "chat" };

function route() {
  // Plain fragments (#content — the a11y skip link) are the BROWSER's business, not a
  // module address. Hijacking them to the fallback silently teleported the user to the
  // first module (measured live 2026-08-24).
  if (location.hash && !location.hash.startsWith("#/")) return;
  // Deep link: everything after the module id is the APP's inner route, handed to its
  // iframe. "המקור היחיד לסלקטור הוא הקישור" (owner, 2026-08-24): a console URL restores
  // the exact screen inside the exact app, same as the direct mount.
  const dm = parseModuleHash();
  // WHAT A LINK NAMES. `<app>` was read as the module id of THIS office; a link is written once and
  // read on whichever office it reaches, so it may carry the app's alias (`plane`), or the module id
  // of the office that WROTE it (`project-pln` — a tile here is `plane.hp-laptop`). Reading only the
  // id made such a link fall through to the first tile: the owner got the AGENT where he asked for
  // the work item (measured 2026-10-09, DGO-511). module-ref.js holds the resolution and its test.
  const m = dm ? BinaModuleRef.resolve(MODULES, dm[1]) : null;
  if (m) return openModule(m, dm[2] || "");
  // A renamed module: rewrite the address and keep the inner route, so a deep link into the old id
  // survives the rename intact. location.replace, so the dead id never becomes a history entry.
  const renamed = dm && LEGACY_MODULE_IDS[dm[1]];
  if (renamed && MODULES.some(x => x.id === renamed)) {
    return location.replace("#/m/" + renamed + (dm[2] || ""));
  }
  // Phone: the rail is hidden, so the bare hash opens the launcher instead of teleporting into
  // whichever app happens to be first in the registry.
  if (PHONE.matches && MODULES.length) return renderHome();
  const first = MODULES[0];
  if (first) return location.replace("#/m/" + first.id);
  return renderNoModules();
}

// "/a/incoming/" + "/repos/x?y=1" → "/a/incoming/repos/x?y=1"; a bare "?y=1" appends to the root.
function joinEmbed(embed, rest) {
  if (!rest) return embed;
  return rest.startsWith("?") ? embed + rest : embed.replace(/\/+$/, "") + rest;
}

// The embedded app reports its inner route after every in-app navigation (same-origin
// postMessage), and the shell mirrors it into the hash with replaceState — the address bar
// is therefore ALWAYS a copyable deep link, with no history spam and no hashchange loop
// (replaceState does not fire hashchange, so route() never re-runs on its own echo).
window.addEventListener("message", (e) => {
  if (e.origin !== location.origin) return;
  const d = e.data;
  if (!d || d.type !== "bina:route" || typeof d.path !== "string") return;
  // Only the CURRENTLY EMBEDDED frame may write the address bar — same rule the
  // reload-ack listener enforces. A late message from a swapped-out app, a nested
  // frame or an opener must not relabel another module's URL.
  const f = $("#frame");
  if (!f || e.source !== f.contentWindow) return;
  // shape: an inner route ("/x" or "?q="), never a fragment or a bare word
  if (!/^[/?][^#]*$/.test(d.path)) return;
  const cur = parseModuleHash();
  if (!cur) return;
  const m = MODULES.find(x => x.id === cur[1]);
  if (!m || !m.embed) return;
  const path = d.path === "/" ? "" : d.path;
  history.replaceState(null, "", "#/m/" + cur[1] + path);
});

// Reachable only when /api/modules answered with nothing — a shell whose registry is empty or whose
// backend is still starting. Better an honest empty state than a blank content pane.
function renderNoModules() {
  setActive(null); setViewTitle(null);
  showContent();
  $("#content").innerHTML = `<div class="wcard"><h3>אין מסכים זמינים</h3>` +
    `<div class="sub">רשימת האפליקציות חזרה ריקה. ודאו שהשירותים פועלים, ורעננו את הדף.</div></div>`;
}

function showContent() {
  $("#content").classList.remove("hidden"); $("#embedwrap").classList.add("hidden");
  $("#acctChip").classList.add("hidden");   // the chip belongs to an embedded service, not to a console view
}
function showEmbed(url, service) {
  $("#embedwrap").classList.remove("hidden"); $("#content").classList.add("hidden");
  const f = $("#frame");
  // Skip the reload only when the frame is ALREADY THERE — compared against the frame's
  // LIVE location, never the src attribute. SPA navigation moves the frame without
  // touching the attribute, and the account-switch reload rewrites it to an absolute
  // URL; both made the attribute a record of where the shell last AIMED, not where the
  // app IS — which is how a rail click could desync the address bar from the screen
  // (measured live 2026-08-24). Same-origin, so reading the location is ours to do.
  let cur = null;
  try { cur = f.contentWindow.location.pathname + f.contentWindow.location.search; } catch (err) { /* not ours */ }
  const chip = $("#acctChip");
  chip.classList.toggle("hidden", !service);
  if (cur === url) { watchFrameRoute(); return; } // already there — and the account bar is already rendered too
  if (service) renderAccountBar(service, chip); else chip.innerHTML = "";
  // the app arrives with the shell's theme already applied — set it on load, not after, so the app
  // never paints light for a frame and then flips
  f.onload = () => { themeIntoFrame(); watchFrameRoute(); };
  f.src = url;
  watchFrameRoute();
}

/* ── the app's route IS the shell's route ────────────────────────────────────────────────────────
 * One rule, and no protocol for the apps: the tail of the console's hash and the app's own URL are
 * the SAME string under the app's mount — `#/m/drive/folder/5` is `/a/drive/folder/5`. Nothing is
 * encoded, nothing is translated, and the address a person copies is the address that reopens that
 * exact screen (owner, 2026-10-12: «הנתיב תמיד יהיה הנתיב המלא שניתן לשתף ומוביל לאותה נקודת מסך»).
 *
 * The half that cannot be a rule is TIME: the app moves inside its frame without telling anybody
 * (that is what a router does), so the shell has to hear about it. It hears it from the frame's own
 * navigations — the Navigation API's `navigate` event, subscribed from here because the frame is
 * same-origin (every embedded app is proxied under /a/<alias>/). One listener, no polling, no code
 * in the app, no message protocol: measured 2026-10-12 (`ci-artifacts/route-contract/
 * navigate-probe.py`) — a click in the app's own rail reached this listener and the console's
 * address became `#/m/drive/p/home`, the app's own route, verbatim.
 *
 * `navigate` fires BEFORE the URL moves, so the route comes from `event.destination` — one
 * property, no waiting. A frame that loads a document of its own (a full page inside the app)
 * replaces its window's navigation object, which is why this is subscribed again from `f.onload`:
 * the console already hooks `load` to hand the app its theme. Engines without the Navigation API
 * get the two events every router also fires (`hashchange`/`popstate` on the frame) — still no
 * polling, and nothing the app has to do.
 */
function watchFrameRoute() {
  const f = $("#frame");
  let w = null;
  try { w = f.contentWindow; } catch (err) { return; }              // a frame that is not ours
  if (!w || !w.location || !w.location.pathname) return;
  const map = parseModuleHash();
  const m = map && MODULES.find(x => x.id === map[1]);
  if (!m || !m.embed) return;                                       // an external host: its own URL is its own
  const mount = m.embed.replace(/\/+$/, "");                        // "/a/<alias>"
  const inner = (href) => {
    const url = new URL(href, location.origin);
    if (!url.pathname.startsWith(mount)) return null;               // the frame left the app
    const path = url.pathname.slice(mount.length);
    // The mount itself IS the root: `/a/bina/` must read as `#/m/bina`, never `#/m/bina/`, or the
    // address a person copies after a step is a different string from the one they arrived with.
    return (path === "/" ? "" : path) + url.search + url.hash;
  };
  const reflect = (href) => {
    const route = inner(href);
    if (route === null) return;
    const now = parseModuleHash();
    if (!now || now[1] !== m.id) return;                            // the person moved on meanwhile
    const next = "#/m/" + m.id + (route === "/" ? "" : route);
    if (location.hash !== next) history.replaceState(null, "", next);
  };
  if (!w.__binaWatched) {
    w.__binaWatched = true;
    if (w.navigation && typeof w.navigation.addEventListener === "function") {
      w.navigation.addEventListener("navigate", (event) => reflect(event.destination.url));
    } else {
      w.addEventListener("hashchange", () => reflect(w.location.href));
      w.addEventListener("popstate", () => reflect(w.location.href));
    }
  }
  reflect(w.location.href);                                         // whatever the frame is on right now
}

// openLauncher() + renderKpis() are gone with the "לוח בקרה" module: a tile grid of the modules
// already in the rail beside it, over KPIs that each linked to the screen that owns them. Its only
// backend, /api/overview, went with it (console/app.py).

// `m` is the module OBJECT — route() is the only caller and has already resolved it.
// `rest` is the deep-link tail ("/inner/path?query"), empty for a bare module link.
// Every compiled module carries an `/a/<alias>/` embed (reconcile.py refuses to emit one
// without it), so embed-or-install is the WHOLE dispatch — the old launch-card path for
// external hosts was structurally unreachable and is gone.
// ── open apps (the phone's recents) ──────────────────────────────────────────
// A phone has no rail and no windows: the two things a person needs to keep their place are
// "what did I open" and "where was I in it". This tracks both — the list is MRU, and each entry
// remembers the app's INNER route, so coming back lands where you left rather than at its root.
//
// ONE live frame, not N. Keeping several apps alive would preserve in-app state (a half-typed
// form), and it is what Android does — but it costs one document per app on a host where the
// whole office shares 5 GB. The honest tradeoff: the LIST and the LOCATION survive, the app's
// in-memory state does not, and switching reloads it. `sessionStorage`, so a reload keeps the
// list and a new tab starts empty.
const OPEN = [];
const OPEN_KEY = "do-open-apps";
function openLoad() {
  try {
    const raw = JSON.parse(sessionStorage.getItem(OPEN_KEY) || "[]");
    if (Array.isArray(raw)) OPEN.push(...raw.filter((e) => e && typeof e.id === "string"));
  } catch (e) { /* private mode: recents simply do not survive a reload */ }
}
function openSave() {
  try { sessionStorage.setItem(OPEN_KEY, JSON.stringify(OPEN.slice(0, 8))); } catch (e) { /* ignore */ }
}
function openTouch(id, route) {
  const i = OPEN.findIndex((e) => e.id === id);
  if (i >= 0) OPEN.splice(i, 1);
  OPEN.unshift({ id, route: route || "" });
  openSave();
}
function openClose(id) {
  const i = OPEN.findIndex((e) => e.id === id);
  if (i >= 0) OPEN.splice(i, 1);
  openSave();
  renderSwitcher();
}

// The switcher: the cards of what is open. Phone-only surface, like the home screen — on a
// desktop the windows ARE the open apps, and desktop.js already draws them.
function renderSwitcher() {
  const old = document.querySelector(".switcher"); if (old) old.remove();
  if (!PHONE.matches || !OPEN.length) return;
  const ov = el("div", "switcher");
  ov.innerHTML = `<div class="sw-head"><b>אפליקציות פתוחות</b>
      <button class="sw-close" type="button" aria-label="סגירה" title="סגירה">${mIcon("x")}</button></div>
    <div class="sw-list">${OPEN.map((e) => {
      const m = MODULES.find((x) => x.id === e.id);
      if (!m) return "";
      return `<div class="sw-card${remoteCls(m)}"${officeHue(m)} data-sw="${esc(m.id)}">
        <button class="sw-open" type="button" data-open="${esc(m.id)}" title="${esc(remoteTip(m))}">
          <span class="sw-ic">${mIcon(m.icon)}</span>
          <span class="sw-nm">${esc(m.name)}</span>
        </button>
        <button class="sw-x" type="button" aria-label="הסרה" title="סגירת האפליקציה" data-x="${esc(m.id)}">${mIcon("x")}</button>
      </div>`;
    }).join("")}</div>`;
  document.body.appendChild(ov);
  ov.querySelector(".sw-close").onclick = () => ov.remove();
  ov.onclick = (e) => { if (e.target === ov) ov.remove(); };
  ov.querySelectorAll("[data-open]").forEach((b) => {
    b.onclick = () => {
      const entry = OPEN.find((x) => x.id === b.dataset.open);
      ov.remove();
      location.hash = "#/m/" + b.dataset.open + ((entry && entry.route) || "");
    };
  });
  ov.querySelectorAll("[data-x]").forEach((b) => {
    b.onclick = (e) => { e.stopPropagation(); openClose(b.dataset.x); };
  });
}

function openModule(m, rest) {
  // Desktop mode: every module is a window on the desktop, not the content of the one frame. For an
  // app of its own host the window IS that host (desktop.js's openExternal), so nothing is proxied.
  if (window.BinaDesktop && BinaDesktop.isOn()) return BinaDesktop.openModule(m, rest);
  if (m.external) {
    const url = externalUrl(m) + (rest || "");
    setActive(m.id); setViewTitle(m);
    // An office MEASURED unreachable gets the card, not the frame: on its own host a frame that
    // cannot load is the browser's error page, which nothing here can read, replace or explain
    // (2026-10-04: the owner's only sign that a tunnel had been dead for fifteen hours).
    const asked = ASKED_ANYWAY === m.id; ASKED_ANYWAY = "";
    if (isOff(m) && !asked) return renderExternalNotice(m, url);
    if (NO_NESTED_HOST && m.signed_in) return openOwnHost(m, url);
    showEmbed(url);
    setTimeout(() => externalFallback(m, url), 2500);   // card only when nothing rendered
    return;
  }
  if (m.embed) openTouch(m.id, rest || "");
  setActive(m.id); setViewTitle(m);
  if (m.view === "settings") { showContent(); return BinaDesktop.renderSettings($("#content")); }
  return showEmbed(joinEmbed(m.embed, rest), m.service);
}


// The "apps" screen used to be a native console view (renderApps) listing apps + tools. It is now
// the app-management app (#/m/apps embeds /a/app-management/), which owns launching AND lifecycle
// (enable/disable/install/uninstall) in one place. The old renderApps was removed here.

// ── account bar (platform services: drive :8975 / mail :8970) ───────────────────
// A platform service owns N connections (accounts) + ONE active pointer; every op it runs — for the
// embedded app AND for n8n — goes to the active one. So the bar is the single place a human answers
// "which account is this working on right now?". Contract (ai/context/platform-service-contract.md §2):
//   GET  /connections        -> {active, connections:[{id,protocol,label,account_hint,status}]}
//   POST /connections/select {id} · POST /connections {protocol,label,secret} · DELETE /connections/<id>
//   GET  /readyz             -> 200 {ready:true} | 503 {ready:false, reason}
// Reached through the console's same-origin /api/svc/<service>/… proxy (SSO already applied).
const SVC_HE = { drive: "דרייב", mail: "דואר", chat: "צ׳אט" };

// ══ PROVIDER CATALOG — fetched from the SERVICE, never authored here ═════════════════════════
// §4b: "Users pick a PROVIDER, not a protocol." A protocol (`chat_tg_bot`) is capability + auth
// method — a derived string, never a thing a human chose.
//
// This used to be a hardcoded map in this file, with a generic username/password card as the
// fallback for any protocol it did not know. Its own header said to delete it "the moment drive
// (:8975) and mail (:8970) serve GET /providers". All three services serve it — drive app.py:1020,
// mail service.py:573, chat server.js:231 — and the map was never deleted. What that cost, measured
// live 2026-09-02:
//
//   · TELEGRAM: no card, so the fallback asked for username+password and POSTed {username,password}.
//     The chat adapter wants {token}. The operator got "connection chat_tg_bot-…: secret needs
//     {token}" — their correct token rejected as if THEY had mistyped it. The service had been
//     serving needs:['token'] the whole time.
//   · WHATSAPP: no card, so the fallback offered a CREDENTIAL FORM for a pairing that is a browser
//     ceremony. There is no secret to type; the connection was created anyway, baileys ran out of
//     QR regenerations and the operator got baileys' own "QR refs attempts ended".
//
// A fallback that invents a form the service cannot accept is worse than no card at all: it turns
// "this console does not know that protocol" into "your credentials are wrong". So there is no
// fallback now — the service is the authority on what it can connect and what each method needs,
// and a protocol absent from its own catalog is simply not offered.
//
// Service shape (identical across drive/mail/chat):
//   { id, name, icon, builtin?, description,
//     auth_methods: [{ id, label, protocol, needs:[<field key>], recommended,
//                      direct?, can, explain?, help_url?, start_url? }] }

// The one thing that IS the console's to own: how a field key is PRESENTED. The service says it
// needs "token"; what that is called in Hebrew, whether it masks, and what a valid one looks like is
// this screen's business. An unknown key still renders — as a plain text field under its own name —
// because a new field the service asks for must never be silently undisplayable.
const FIELD_HE = {
  token: { label: "Bot Token", type: "password", placeholder: "123456789:AA…",
           hint: "הטוקן ש-BotFather מחזיר כשיוצרים בוט." },
  username: { label: "שם משתמש / כתובת", type: "text", is_hint: true },
  password: { label: "סיסמה / מפתח גישה", type: "password" },
  service_account_json: { label: "מפתח חשבון שירות (JSON)", type: "textarea",
                          hint: "הקובץ שמורידים מ-Google Cloud ← IAM ← חשבונות שירות." },
};
const fieldSpec = (key) => ({ key, label: key, type: "text", ...(FIELD_HE[key] || {}) });

// service -> the catalog it served, and a flat protocol index the account bar reads.
const _PROV = {};
const PROTO_INDEX = {};

/** Fetch and cache one service's catalog. Returns null when the service could not answer — the
 *  caller must SAY so rather than substituting a guess. */
async function loadProviders(service) {
  const r = await svcJson(service, "/providers");
  const list = (r && r.ok && r.d && Array.isArray(r.d.providers)) ? r.d.providers : null;
  if (!list) return null;
  _PROV[service] = list;
  for (const p of list) {
    for (const m of (p.auth_methods || [])) {
      if (!m.protocol) continue;
      PROTO_INDEX[m.protocol] = {
        provider_name: p.name, method_label: m.label,
        // "always on" is the service's `builtin` — a provider whose engine the deployment runs
        // itself. Derived from the catalog, never from the shape of an id.
        always_on: !!p.builtin || (!m.needs || !m.needs.length) && !m.start_url && m.direct !== true,
      };
    }
  }
  return list;
}

/** The service's catalog -> the wizard's card shape. The ONLY mapper. */
function providerCards(service) {
  const list = _PROV[service] || [];
  return list.map(p => ({
    id: p.id, name: p.name, icon: p.icon || "key", desc: p.description || "",
    always_on: !!p.builtin,
    methods: (p.auth_methods || []).map(m => ({
      protocol: m.protocol,
      provider_name: p.name,
      auth_method_id: m.id,
      auth_method_label: m.label,
      auth_desc: m.explain || (m.needs && m.needs.length
        ? `נדרשים: ${m.needs.join(", ")}.` : "לא נדרשים פרטי גישה."),
      grants: m.can || "ההרשאות נקבעות על ידי השירות.",
      needs: (m.needs || []).map(fieldSpec),
      recommended: !!m.recommended,
      help_url: m.help_url || null,
      start_url: m.start_url || null,
      // THREE shapes, and the service distinguishes them — this console must not guess:
      //   always_on  nothing to provide (a private engine we run)
      //   oauth      a consent window we open        (start_url + no needs)
      //   handoff    a ceremony elsewhere            (start_url + direct === false) ← WhatsApp's QR
      //   form       fields the operator types       (needs[])
      always_on: !!p.builtin,
      oauth: !!m.start_url && m.direct !== false && !(m.needs || []).length,
      handoff: m.direct === false && !!m.start_url,
    })).sort((a, b) => (b.recommended ? 1 : 0) - (a.recommended ? 1 : 0)),
  })).sort((a, b) => (b.always_on ? 1 : 0) - (a.always_on ? 1 : 0));   // §4b: local listed first
}

const protoHe = p => (PROTO_INDEX[p] ? PROTO_INDEX[p].provider_name : (p || ""));
const protoFullHe = p => {
  const c = PROTO_INDEX[p];
  return c ? `${c.provider_name} · ${c.method_label}` : (p || "");
};
// A connection ON A PRIVATE ENGINE — one whose process the deployment runs itself. It is never
// removable from here: on a private engine you do not disconnect an account, you delete a PROFILE,
// and that is an operation in the owning app (deleting the mailbox removes its connection with it).
//
// Derived from the catalogue's own `always_on`, not from the shape of the id. It used to be
// `/-local$/`, which worked only while each private engine had exactly ONE synthetic connection
// called `<proto>-local`. Mail's private engine now has N real vault instances
// (`mail_imap_local-<8hex>`, one per declared profile), so the id says nothing — and reading an id
// as a data structure is precisely the habit that made every profile of every app read as "מקומי".
// `-local` is kept as a SECOND signal, not as the definition: drive and chat still synthesise a
// `<proto>-local` row, and this console serves every service at once. Either signal is enough.
const isLocalConn = c => !!((PROTO_INDEX[(c && c.protocol) || ""] || {}).always_on)
                      || /-local$/.test((c && c.id) || "");
// N profiles on one private engine means the NAME has to be the profile's. "מקומי" for all of them
// would render the switcher as a column of identical rows.
const connHe = c => (c && c.label) || protoHe(c && c.protocol) || (c && c.id) || "";
// The hint is a SECOND line of identity (the Google address). When a connection is labelled by its
// address — which is exactly what the OAuth broker does — label and hint are the same string, and
// echoing it twice reads as a rendering bug. Show it only when it actually adds something.
const connHint = c => {
  const h = c.account_hint;
  // NOT for a private-engine profile: its hint is its id ("admin" printed under «מנהל» in the top
  // bar of every screen) — the office's word, not an address a person recognises. Two such profiles
  // are told apart by their names; the id is one hover away (`connId`, in the chip's title).
  return h && h !== connHe(c) && !c.is_private ? h : null;
};
const connId = c => (c && c.is_private && c.account_hint && c.account_hint !== connHe(c) ? "פרופיל " + c.account_hint : "");

// One fetch shape for the whole plane: a service that is down and a service that returns an error
// body must both degrade to "not available", never to a thrown render.
async function svcJson(service, path, opt) {
  try {
    const r = await fetch(`/api/svc/${service}${path}`, opt);
    return { ok: r.ok, d: await r.json().catch(() => null) };
  } catch (e) { return { ok: false, d: null }; }
}
const svcPost = (service, path, body) => svcJson(service, path,
  { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function closeAcctMenus(keep) {
  document.querySelectorAll(".acct-menu").forEach(m => {
    if (m === keep) return;
    m.classList.add("hidden");
    // the trigger's aria-expanded is part of the menu's state, not decoration: leaving it "true" on
    // a closed menu tells a screen reader the opposite of what the screen shows.
    const b = m.parentNode && m.parentNode.querySelector(".acct-btn");
    if (b) b.setAttribute("aria-expanded", "false");
  });
}
// click-away closes any open account menu; clicks INSIDE a switch are its own business
document.addEventListener("click", e => { if (!e.target.closest(".acct-switch")) closeAcctMenus(); });
// C14.1 — layered Escape: the menu is the innermost layer, so it takes Escape before anything else
// and returns focus to the chip that opened it.
document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  const open = document.querySelector(".acct-menu:not(.hidden)");
  if (!open) return;
  e.preventDefault(); e.stopPropagation();
  closeAcctMenus();
  const b = open.parentNode && open.parentNode.querySelector(".acct-btn");
  if (b) b.focus();
}, true);

// ── live state chips (§4b) ──────────────────────────────────────────────────────
// Four states, one vocabulary, everywhere a connection is shown. "בבדיקה" is a REAL state, not a
// spinner: it is what a write looks like between "sent" and "confirmed by the probe" — the console
// never renders a write as done on the strength of a 200 alone.
const CHIP_HE = { ok: "מחובר", checking: "בבדיקה", action: "דורש טיפול", error: "שגיאה" };
const CHIP_CLS = { ok: "healthy", checking: "checking", action: "needs_action", error: "degraded" };
const chipHtml = (st, title) =>
  `<span class="chip ${CHIP_CLS[st]}"${title ? ` title="${esc(title)}"` : ""}>` +
  `<span class="dot ${CHIP_CLS[st]}"></span>${CHIP_HE[st]}</span>`;

// /readyz is the ONLY readiness truth (§2) — n8n reads the same endpoint, so the operator's chip and
// the automation layer's view of "usable" can never disagree. Distinguish the two failures: the
// service ANSWERED that it isn't ready (it knows why -> דורש טיפול) vs. it didn't answer at all
// (nobody knows why -> שגיאה). They need different actions, so they must not share a chip.
function readyState(ready) {
  if (ready.ok && ready.d && ready.d.ready) return "ok";
  if (ready.d && ready.d.ready === false) return "action";
  return "error";
}
function readyReason(ready, st) {
  if (st === "ok") return "החשבון מחובר, והשירות מאמת זאת מול הספק.";
  if (ready.d && ready.d.reason) return ready.d.reason;          // the service's OWN words
  if (ready.d && ready.d.message) return ready.d.message;
  // Third case, and it is NOT "no answer": the service replied, but without the `ready` the contract
  // (§2) requires, so nothing here can say whether it is usable. Saying "לא השיב" instead would be a
  // plain falsehood, and it sends the reader to look at the wrong thing — a restarting container
  // rather than a service answering off-contract.
  if (ready.d) return "השירות השיב לבדיקת המוכנות בלי לדווח על מצבו. ייתכן שגרסת השירות ישנה מזו של המסך.";
  return "השירות לא השיב לבדיקת המוכנות. ייתכן שהוא מופעל מחדש כרגע.";
}
const hhmm = t => new Date(t).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });

// The chip in its pending state: shown while a write is in flight, BEFORE any probe confirms it.
function acctChipChecking(mount, text) {
  mount.innerHTML = `<button class="acct-btn" type="button" disabled aria-busy="true">` +
    `<span class="dot checking"></span>` +
    `<span class="acct-tx"><b class="acct-lbl muted">${esc(text)}</b></span></button>`;
}

// C4 — everything the health panel needs, captured at the moment the chip last rendered. Kept so the
// panel reports the same probe the chip is showing rather than issuing a second, later one that could
// disagree with the dot the person just clicked.
let _acct = null;

// The worst state across every connection: the ACTIVE one's live verdict, plus the last-known status
// of the rest. One definition, used by both the menu entry and the panel header, so the badge and the
// summary sentence can never contradict each other.
function acctWorst(conns, activeSt) {
  if (activeSt === "error") return "error";
  if (activeSt !== "ok") return "action";
  return conns.some(c => c.status && c.status !== "ok") ? "action" : "ok";
}

// C3/C15 — one switcher, in the top bar. The chip is deliberately small: avatar-free, dot + name +
// chevron. Everything that used to sprawl across the band — the connect button, the last-checked
// stamp, the refresh, the service's reason — moves into the menu, where there is room to say it in
// words instead of abbreviating it to fit a row.
async function renderAccountBar(service, mount) {
  acctChipChecking(mount, "טוען חשבונות…");
  const [conn, ready, man] = await Promise.all([
    svcJson(service, "/connections"), svcJson(service, "/readyz"), svcJson(service, "/manifest"),
  ]);
  const at = Date.now();
  mount.innerHTML = "";
  if (!conn.ok || !conn.d || !Array.isArray(conn.d.connections)) {
    _acct = null;
    const b = el("button", "acct-btn bad",
      `<span class="dot degraded"></span><span class="acct-tx"><b>שירות החשבונות אינו זמין</b></span>` +
      `<span class="acct-chev">${mIcon("refresh")}</span>`);
    b.title = "לא ניתן לקרוא את רשימת החשבונות. לחצו לבדיקה חוזרת.";
    b.onclick = () => renderAccountBar(service, mount);
    mount.appendChild(b);
    return;
  }
  const conns = conn.d.connections;
  const active = conns.find(c => c.id === conn.d.active) || null;
  const st = active ? readyState(ready) : "action";
  const reason = active ? readyReason(ready, st) : "לא נבחר חשבון פעיל — בחרו חשבון או חברו חשבון חדש.";
  // Populate PROTO_INDEX before the rows render — protoFullHe/isLocalConn read it, and an
  // unloaded index would print raw protocol ids and mark every account as removable.
  if (!_PROV[service]) await loadProviders(service);
  const protos = ((man.d && man.d.protocols) || [])
    .map(p => (typeof p === "string" ? p : (p && (p.id || p.protocol))))
    .filter(Boolean);
  _acct = { service, conns, active, st, reason, at, mount };

  // ── the chip ──
  const sw = el("div", "acct-switch");
  const b = el("button", "acct-btn",
    `<span class="dot ${CHIP_CLS[st]}"></span>` +
    `<span class="acct-tx"><b class="acct-lbl">${esc(active ? connHe(active) : "לא נבחר חשבון")}</b>` +
    (active && connHint(active) ? `<small class="acct-hint">${esc(connHint(active))}</small>` : "") +
    `</span><span class="acct-chev">${mIcon("chevron")}</span>`);
  b.title = [`${CHIP_HE[st]} — ${reason}`, connId(active)].filter(Boolean).join(" · ");
  b.setAttribute("aria-haspopup", "menu");
  b.setAttribute("aria-expanded", "false");
  b.setAttribute("aria-label", `חשבון פעיל: ${active ? connHe(active) : "לא נבחר"} — ${CHIP_HE[st]}. החלפת חשבון`);

  // ── the menu ──
  const menu = el("div", "acct-menu hidden");
  menu.setAttribute("role", "menu");
  const others = conns.filter(c => !active || c.id !== active.id);
  if (!others.length) menu.appendChild(el("div", "acct-empty", "אין חשבונות נוספים"));
  for (const c of others) {
    const item = el("div", "acct-item");
    // A non-active connection cannot be probed — /readyz probes the ACTIVE one only (§2). So its chip
    // reports the instance's own last-known status, and says so, rather than implying a live check.
    const cst = c.status === "ok" ? "ok" : "action";
    const ctitle = c.status === "ok"
      ? "מצב אחרון מהשירות. בדיקה חיה מתבצעת רק על החשבון הפעיל."
      : "השירות סימן את החשבון הזה כדורש טיפול.";
    // Three facts about this account — name, address, how it connects — STACKED. Side by side they
    // compete for one 290px row and all three lose: the name truncates to two letters, the address to an
    // ellipsis, and the row answers nothing. Vertical costs a few pixels of menu height and keeps
    // every one of them readable.
    const pick = el("button", "acct-pick",
      `<span class="acct-tx2">` +
        `<span class="acct-l1">${chipHtml(cst, ctitle)}<b>${esc(connHe(c))}</b></span>` +
        (connHint(c) ? `<small class="acct-hint">${esc(connHint(c))}</small>` : "") +
        `<small class="acct-proto">${esc(protoFullHe(c.protocol))}</small>` +
      `</span>`);
    pick.setAttribute("role", "menuitemradio"); pick.setAttribute("aria-checked", "false");
    pick.onclick = () => svcSelect(service, c.id, mount);
    item.appendChild(pick);
    if (!isLocalConn(c)) {   // the synthetic local account is the floor of the service — never removable
      const rm = el("button", "acct-rm icon-btn", mIcon("trash"));
      rm.title = "הסר חשבון";
      rm.onclick = () => svcRemove(service, c, mount);
      item.appendChild(rm);
    }
    menu.appendChild(item);
  }
  menu.appendChild(el("div", "acct-sep"));

  // ── connection health (C4) ──
  // The entry summarises EVERY connection, so its dot is the worst of them — not the active one's.
  // Keying the badge off the active state instead would hide the one case the badge exists for: the
  // account you are not looking at is the broken one.
  const worst = acctWorst(conns, st);
  const hp = el("button", "acct-act",
    `<span class="dot ${CHIP_CLS[worst]}"></span><span>מצב החיבורים</span>` +
    (worst === "ok" ? "" : `<span class="acct-badge ${CHIP_CLS[worst]}" role="img" aria-label="דורש טיפול" title="דורש טיפול">${mIcon("bang")}</span>`));
  hp.setAttribute("role", "menuitem");
  hp.onclick = () => { closeAcctMenus(); healthPanel(); };
  menu.appendChild(hp);

  // ── connect a new account — a GUIDED flow, never a jump to an authorize_url (§4b) ──
  // The manifest says which protocols this service can connect; the wizard turns them into PROVIDER
  // cards. Local is NOT filtered out here: it is a first-class provider, and "make the local account
  // the active one" is a legitimate thing to walk a human through.
  if (protos.length) {
    const ab = el("button", "acct-act add", `<span class="acct-plus">${mIcon("plus")}</span><span>חיבור חשבון חדש</span>`);
    ab.setAttribute("role", "menuitem");
    ab.onclick = () => { closeAcctMenus(); openConnectWizard(service, protos, mount); };
    menu.appendChild(ab);
  }

  // ── last-checked + refresh, at the foot of the menu where there is room for the full sentence ──
  const foot = el("div", "acct-foot",
    `<span class="acct-when">${mIcon("clock")} נבדק ב-${esc(hhmm(at))}</span>`);
  const rt = el("button", "acct-recheck", "בדיקה מחדש");
  rt.onclick = () => renderAccountBar(service, mount);
  foot.appendChild(rt);
  menu.appendChild(foot);
  if (st !== "ok") menu.appendChild(el("div", "acct-warn", esc(reason)));

  b.onclick = () => {
    closeAcctMenus(menu);
    const openNow = menu.classList.toggle("hidden") === false;
    b.setAttribute("aria-expanded", openNow ? "true" : "false");
  };
  sw.appendChild(b); sw.appendChild(menu);
  mount.appendChild(sw);
}

// ── C4 · connection health: every connection's state, its reason, and what to do about it ────────
// The chip answers "which account, and is it up?". This answers "what is wrong with WHICH one" — the
// question you have when something is wrong, which is the only time you open it.
//
// One honesty rule runs through it: §2 lets the service probe the ACTIVE connection only. So exactly
// one card here carries a live verdict and the rest carry the service's last-known status, and the
// panel SAYS which is which. A grid of confident green ticks, only one of which was actually checked,
// is worse than no panel at all.
function healthPanel() {
  if (!_acct) return;
  closeModal();
  const { service, conns, active, st, reason, at } = _acct;
  const svcName = SVC_HE[service] || service;
  const worst = acctWorst(conns, st);
  const summary = worst === "ok" ? "כל החיבורים תקינים"
    : worst === "error" ? "חיבור אחד או יותר דורשים טיפול" : "חיבור אחד או יותר דורשים תשומת לב";

  const card = c => {
    const isActive = !!active && c.id === active.id;
    const cst = isActive ? st : (c.status === "ok" ? "ok" : "action");
    const line = isActive ? reason
      : (c.status === "ok" ? "מצב אחרון שדיווח השירות." : "השירות סימן את החשבון הזה כדורש טיפול.");
    return `<div class="hc${isActive ? " on" : ""}">` +
      `<div class="hc-h">` +
        `<span class="hc-tx"><b>${esc(connHe(c))}</b>` +
        (connHint(c) ? `<small>${esc(connHint(c))}</small>` : "") + `</span>` +
        chipHtml(cst) +
      `</div>` +
      `<div class="hc-proto">${esc(protoFullHe(c.protocol))}</div>` +
      `<div class="hc-reason${cst === "ok" ? "" : " bad"}">${esc(line)}</div>` +
      `<div class="hc-meta">` +
        (isActive
          ? `${mIcon("check")} נבדק חי מול השירות ב-${esc(hhmm(at))}`
          : `${mIcon("clock")} לא נבדק — בדיקה חיה מתבצעת על החשבון הפעיל בלבד`) +
      `</div></div>`;
  };

  const ov = el("div", "modal-ov");
  const box = el("div", "modal wide");
  box.innerHTML =
    `<div class="modal-h"><h3>מצב החיבורים</h3><button class="ghost" id="mX">${mIcon("x")}</button></div>` +
    `<div class="cw-body">` +
      `<div class="sub">${esc(svcName)} · ${conns.length} חשבונות · ${esc(summary)}</div>` +
      `<div class="hlist">${conns.map(card).join("")}</div>` +
      // The sim's panel carries a per-connection event log. No platform service serves one, and a
      // panel that invents a plausible history is worse than one that admits the gap — so this says
      // where the history actually lives instead of manufacturing rows.
      `<div class="cw-msg soft">${mIcon("alert")} יומן אירועים לכל חיבור עדיין לא נשמר בשירותים. ` +
        `אירועי חיבור מלאים זמינים במסך <b>חיבורים ומפתחות</b>.</div>` +
      `<div class="cw-foot"><button class="btn ghost" id="hRe">${mIcon("refresh")} בדיקה מחדש</button>` +
        `<span class="grow"></span><button class="btn" id="hX">סגירה</button></div>` +
    `</div>`;
  ov.appendChild(box); document.body.appendChild(ov);
  box.querySelector("#mX").onclick = closeModal;
  box.querySelector("#hX").onclick = closeModal;
  box.querySelector("#hRe").onclick = async () => {
    await renderAccountBar(service, _acct.mount);
    healthPanel();          // re-open on the FRESH probe, so the panel never shows a stale verdict
  };
  ov.onclick = e => { if (e.target === ov) closeModal(); };
}

// Writes are pending → confirmed-by-probe, never optimistic (§4b): show "בבדיקה" the moment the write
// leaves, and let the re-render's /readyz decide what the bar ends up saying.
async function svcSelect(service, id, mount) {
  closeAcctMenus();
  acctChipChecking(mount, "מחליפים חשבון ומאמתים מול השירות…");
  const r = await svcPost(service, "/connections/select", { id });
  if (!r.ok) {
    mount.innerHTML = "";
    const bar = el("div", "acctbar", chipHtml("error") +
      `<span class="acct-lbl">החלפת החשבון נכשלה</span>` +
      `<span class="acct-warn">${esc((r.d && (r.d.reason || r.d.error || r.d.message)) || "השירות דחה את הבקשה.")}</span>`);
    const rt = el("button", "icon-btn acct-refresh", mIcon("refresh"));
    rt.title = "בדיקה מחדש"; rt.onclick = () => renderAccountBar(service, mount);
    bar.appendChild(rt); mount.appendChild(bar); return;
  }
  renderAccountBar(service, mount);   // re-read: select also changes what /readyz reports
  reloadEmbeddedApp(service);         // …and tell the app, which is showing the OLD account's data
}

/**
 * Re-load the embedded app after the SHELL has changed its active account.
 *
 * The chip and the app both act on ONE server-side pointer, and nothing connected them: switching
 * from the chip changed the pointer, the chip re-read and showed the new account, and the iframe —
 * which had already fetched everything — went on showing the previous account's conversations, its
 * own switcher still naming the old connection. Two controls disagreeing about which account you are
 * on, with the data belonging to neither.
 *
 * Reloading the frame rather than posting a message, deliberately: every embedded service (drive,
 * mail, chat) re-reads its whole world on boot, so one line here fixes all of them and any future
 * one, with no per-app protocol to define, version and keep in sync. The cost is a re-fetch the user
 * asked for anyway by switching accounts.
 *
 * `src = src` is not a no-op on an iframe — assigning src reloads it even when the value is
 * unchanged, which is what we want, because the URL does not encode the account.
 */
function reloadEmbeddedApp(service) {
  // desktop mode: every window showing this service re-reads it, not the (hidden) single frame
  if (window.BinaDesktop && BinaDesktop.isOn()) return BinaDesktop.reloadService(service);
  const f = $("#frame");
  if (!f || !f.src || $("#embedwrap").classList.contains("hidden")) return;

  // ASK FIRST, RELOAD IF UNANSWERED.
  //
  // An app that knows how to re-read a connection switch does it in place: no white flash, no lost
  // scroll position, no re-download. One that does not — or is mid-navigation, or predates this —
  // simply never answers, and the reload below still puts it right. So the fast path is an
  // optimisation and the correct path is the fallback, which is the order that cannot regress.
  //
  // Same-origin: the app is proxied under /a/<name>/ on this very host, so targetOrigin is our own
  // origin and no cross-origin trust is being extended to anything.
  // THE CONTRACT — must stay identical to the listener in apps/chat/src/api/ui/chat.ejs:
  //   out  { type: 'platform:connection-changed', service: <app id> }
  //   in   { type: 'platform:reload-ack',         service: <app id> }
  // `platform:` rather than `console:` because this is the shell↔app boundary generally, not one
  // console feature, and every embedded service is expected to answer it eventually. `service` is
  // sent so an app that shares a frame with others can ignore a broadcast meant for a sibling.
  //
  // The message carries NO connection id, deliberately: the shell knows THAT the pointer moved,
  // never where to. The app re-asks the service, which owns the pointer — so a compromised or buggy
  // shell cannot point an app at a connection nobody selected.
  let acked = false;
  const onAck = (e) => {
    if (e.origin !== location.origin) return;
    if (e.source === f.contentWindow && e.data && e.data.type === "platform:reload-ack") acked = true;
  };
  window.addEventListener("message", onAck);
  try {
    f.contentWindow.postMessage({ type: "platform:connection-changed", service }, location.origin);
  } catch { /* cross-origin or not yet loaded — the reload covers it */ }

  setTimeout(() => {
    window.removeEventListener("message", onAck);
    if (!acked) f.src = f.src;
  }, 400);
}

async function svcRemove(service, c, mount) {
  closeAcctMenus();
  if (!await binaAsk({ title: "להסיר את החשבון?", body: "הפעולה מוחקת את פרטי הגישה שלו.", ok: "הסרה", danger: true,
                       facts: [["חשבון", connHe(c)]] })) return;
  acctChipChecking(mount, "מסירים את החשבון…");
  const r = await svcJson(service, "/connections/" + encodeURIComponent(c.id), { method: "DELETE" });
  if (!r.ok) binaTell("הסרת החשבון נכשלה — " +
    ((r.d && (r.d.reason || r.d.error || r.d.message)) || "השירות דחה את הבקשה."), "bad");
  renderAccountBar(service, mount);
  // Removing the ACTIVE account moves the pointer too (the service clears it), so the app is now
  // showing data for an account that no longer exists. Same reload, same reason as svcSelect.
  if (r.ok) reloadEmbeddedApp(service);
}

// ══ GUIDED CONNECT FLOW (§4b) ═════════════════════════════════════════════════
// The anti-pattern this replaces: "חבר חשבון חדש" → straight to an authorize_url. No provider
// choice, no auth-method choice, no explanation, no waiting state, no verification — a flow that
// can fail silently. Here every step is a named state with a visible outcome and a way back.
//
//   provider → method → provide → verify → done
//                          │         └─ probing → ok | fail          (never "added", only "verified")
//                          └─ oauth: intro → waiting → timeout|error (consent can simply not happen)
const CW_STEPS = ["provider", "method", "provide", "verify", "done"];
const CW_STEP_HE = { provider: "ספק", method: "אופן חיבור", provide: "פרטי גישה",
                     verify: "אימות", done: "שם והפעלה" };
const CW_WAIT_MS = 180000;   // 3 min: long enough to pick an account + read a consent screen

let _cw = null;   // the open wizard's state (one at a time, like the QR modal)

async function openConnectWizard(service, protocols, mount) {
  closeAcctMenus(); closeModal();
  // The catalog is the SERVICE's. Fetch before rendering: a wizard that opened on a guess is how
  // the operator ends up typing a real Telegram token into a field named "password".
  const list = await loadProviders(service);
  _cw = { service, mount, providers: list ? providerCards(service) : [], step: "provider", sub: null,
          catalogErr: list ? null : "לא ניתן לקרוא מהשירות אילו ספקים אפשר לחבר. נסו שוב בעוד רגע.",
          provider: null, method: null, secret: null, hint: null, label: "", connId: null,
          prevActive: null, poll: null, deadline: 0, verify: null, err: null, authUrl: null };
  const ov = el("div", "modal-ov cw-ov");
  ov.appendChild(el("div", "modal wide"));
  document.body.appendChild(ov);
  ov.onclick = e => { if (e.target === ov) closeConnectWizard(); };
  cwRender();
}

function cwStopPoll() { if (_cw && _cw.poll) { clearInterval(_cw.poll); _cw.poll = null; } }
function closeConnectWizard() {
  cwStopPoll();          // MUST precede clearing _cw — cwStopPoll reads the timer off it
  const s = _cw; _cw = null;
  const ov = document.querySelector(".cw-ov"); if (ov) ov.remove();
  // Re-render the bar rather than trusting whatever the wizard did: the bar re-probes, so the state
  // the operator is left looking at is confirmed, not assumed.
  if (s) renderAccountBar(s.service, s.mount);
}
function cwGo(step, sub) { if (!_cw) return; cwStopPoll(); _cw.step = step; _cw.sub = sub || null; cwRender(); }

function cwRender() {
  if (!_cw) return;
  const box = document.querySelector(".cw-ov .modal"); if (!box) return;
  const i = CW_STEPS.indexOf(_cw.step);
  box.innerHTML =
    `<div class="modal-h"><h3>חיבור חשבון · ${esc(SVC_HE[_cw.service] || _cw.service)}</h3>` +
    `<button class="ghost" id="cwX" title="סגירה" aria-label="סגירה">${mIcon("x")}</button></div>` +
    `<div class="cw-steps" role="list">` +
    CW_STEPS.map((s, n) => `<span class="cw-step${n < i ? " done" : n === i ? " cur" : ""}" role="listitem">` +
      `${n + 1}. ${esc(CW_STEP_HE[s])}</span>`).join("") + `</div>` +
    `<div class="cw-body" id="cwBody"></div><div class="cw-foot" id="cwFoot"></div>`;
  $("#cwX").onclick = closeConnectWizard;
  const body = $("#cwBody"), foot = $("#cwFoot");
  ({ provider: cwProvider, method: cwMethod, provide: cwProvide,
     verify: cwVerify, done: cwDone })[_cw.step](body, foot);
}

// every step that isn't the first offers a way back — "no dead ends" is structural, not per-screen
function cwBackBtn(foot, step, sub, label) {
  const b = el("button", "btn ghost sm", `${mIcon("back")} ${label || "חזרה"}`);
  b.onclick = () => cwGo(step, sub);
  foot.appendChild(b);
}

async function cwList() {
  const r = await svcJson(_cw.service, "/connections");
  return (r.ok && r.d && Array.isArray(r.d.connections)) ? r.d : null;
}

// ── step 1: provider — "what it is, not how it authenticates" ──
function cwProvider(body, foot) {
  if (_cw.catalogErr) {
    body.innerHTML = `<div class="cw-msg err">${esc(_cw.catalogErr)}</div>`;
    foot.appendChild(el("span", "cw-note grow", "אין קטלוג מקומי לנפול אליו — הספקים נקראים מהשירות."));
    return;
  }
  body.innerHTML = `<div class="sub">מאיפה להביא את ה${esc(SVC_HE[_cw.service] || _cw.service)}? ` +
                   `בוחרים ספק — על אופן ההתחברות נחליט בשלב הבא.</div>`;
  if (!_cw.providers.length) {
    body.appendChild(el("div", "cw-msg err",
      "השירות לא מדווח על אף ספק שאפשר לחבר. ייתכן שהוא מופעל מחדש — נסו שוב בעוד רגע."));
    const r = el("button", "btn", "סגירה"); r.onclick = closeConnectWizard; foot.appendChild(r);
    return;
  }
  const grid = el("div", "cw-grid");
  for (const p of _cw.providers) {
    const card = el("button", "cw-card",
      `<div class="cw-ic">${mIcon(p.icon)}</div>` +
      `<div class="cw-t">${esc(p.name)}</div>` +
      `<div class="cw-d">${esc(p.desc)}</div>` +
      (p.always_on ? `<span class="pill ok">זמין תמיד</span>`
                   : p.methods.length > 1 ? `<span class="cw-ways">${p.methods.length} דרכי חיבור</span>` : ``));
    card.onclick = () => { _cw.provider = p; cwGo("method"); };
    grid.appendChild(card);
  }
  body.appendChild(grid);
  foot.appendChild(el("span", "cw-note", "שלב 1 מתוך 5 · אפשר לחזור אחורה בכל שלב."));
}

// ── step 2: how to connect — what each method needs, and what it will be able to do ──
function cwMethod(body, foot) {
  const p = _cw.provider;
  body.innerHTML = `<div class="sub">איך להתחבר אל <b>${esc(p.name)}</b>?</div>`;
  for (const m of p.methods) {
    const row = el("button", "cw-m",
      `<div class="cw-m-h"><span class="cw-m-ic">${mIcon(m.icon_method || (m.oauth ? "shield" : m.always_on ? "check" : "key"))}</span>` +
      `<b>${esc(m.auth_method_label)}</b>` +
      (m.recommended ? `<span class="pill ok">מומלץ</span>` : ``) + `</div>` +
      `<div class="cw-m-d"><b>מה נדרש:</b> ${esc(m.auth_desc)}</div>` +
      `<div class="cw-m-d"><b>מה זה מאפשר:</b> ${esc(m.grants)}</div>` +
      (m.needs && m.needs.length
        ? `<div class="cw-m-need">${m.needs.map(f => `<span>${esc(f.label)}</span>`).join("")}</div>` : ``));
    row.onclick = () => { _cw.method = m; _cw.err = null; cwGo("provide", m.oauth ? "intro" : null); };
    body.appendChild(row);
  }
  cwBackBtn(foot, "provider", null, "חזרה לבחירת ספק");
  foot.appendChild(el("span", "cw-note grow", "כל דרך מייצרת חשבון נפרד — אפשר להחזיק כמה במקביל."));
}

// ── step 3: provide ──────────────────────────────────────────────────────────
function cwProvide(body, foot) {
  const m = _cw.method;
  if (m.always_on) return cwProvideLocal(body, foot);
  if (m.oauth) return cwProvideOauth(body, foot);
  if (m.handoff) return cwProvideHandoff(body, foot);
  if (!m.needs.length) return cwProvideLocal(body, foot);
  return cwProvideForm(body, foot);
}

// A pairing that is a browser CEREMONY somewhere else — WhatsApp's QR, which is scanned on the
// חיבורים ומפתחות screen where connections proxies the code from the bot. There is no secret to
// type, so this step hands over instead of rendering a form. It used to render the generic
// username/password form, which created a credential-less connection and left the operator reading
// baileys' "QR refs attempts ended" with nothing to do about it.
function cwProvideHandoff(body, foot) {
  const m = _cw.method;
  body.innerHTML =
    `<div class="sub">${esc(m.provider_name)} · ${esc(m.auth_method_label)}</div>` +
    `<div class="cw-msg">${esc(m.auth_desc)}</div>` +
    `<div class="cw-msg soft">${mIcon("shield")} אין כאן מה להקליד: הקישור נעשה בסריקת קוד מהטלפון, ` +
    `והקוד מוצג במסך «חיבורים ומפתחות». לאחר הסריקה החשבון יופיע ברשימה כאן.</div>` +
    (_cw.err ? `<div class="cw-msg err">${esc(_cw.err)}</div>` : ``);
  cwBackBtn(foot, "method");
  const go = el("button", "btn grow", "פתחו את מסך הקישור");
  go.onclick = () => {
    const target = m.start_url || "#/m/connections";
    closeConnectWizard();
    if (/^#/.test(target)) location.hash = target; else window.open(target, "_blank", "noopener");
  };
  foot.appendChild(go);
}

// local: there is nothing to provide — say so plainly instead of showing an empty form
function cwProvideLocal(body, foot) {
  body.innerHTML =
    `<div class="sub">אין מה להזין — ${esc(_cw.provider.name)} כבר קיים במערכת.</div>` +
    `<div class="cw-msg">החשבון המקומי נוצר עם ההתקנה ואינו דורש פרטי גישה. בשלב הבא נאמת שהוא ` +
    `אכן עונה, ואז תוכלו להפוך אותו לחשבון הפעיל.</div>` +
    (_cw.err ? `<div class="cw-msg err">${esc(_cw.err)}</div>` : ``);
  cwBackBtn(foot, "method");
  const go = el("button", "btn grow", "המשך לאימות");
  go.onclick = () => guard(go, cwUseLocal, "בודקים…");
  foot.appendChild(go);
}

async function cwUseLocal() {
  const d = await cwList();
  if (!_cw) return;
  if (!d) { _cw.err = "לא ניתן לקרוא את רשימת החשבונות מהשירות. נסו שוב בעוד רגע."; return cwRender(); }
  _cw.prevActive = d.active;
  const local = d.connections.find(c => isLocalConn(c) && c.protocol === _cw.method.protocol)
             || d.connections.find(c => isLocalConn(c));
  if (!local) {
    _cw.err = "החשבון המקומי אינו מופיע ברשימת החשבונות של השירות. ייתכן שהשירות עולה כרגע.";
    return cwRender();
  }
  _cw.connId = local.id; _cw.label = connHe(local); _cw.hint = local.account_hint || null;
  cwGo("verify"); cwVerifyRun();
}

// oauth: explain what is about to happen BEFORE anything opens — the consent window is the one place
// the user leaves our UI, so they must know what to expect when they get there.
function cwProvideOauth(body, foot) {
  const m = _cw.method;
  if (_cw.sub === "waiting") return cwProvideOauthWaiting(body, foot);
  if (_cw.sub === "timeout") return cwProvideOauthTimeout(body, foot);
  body.innerHTML =
    `<div class="sub">חיבור אל <b>${esc(_cw.provider.name)}</b> באמצעות ${esc(m.auth_method_label)}.</div>` +
    `<div class="cw-msg"><b>מה יקרה עכשיו</b><ol class="cw-ol">` +
    `<li>ייפתח חלון חדש של Google.</li>` +
    `<li>תבחרו חשבון ותאשרו את ההרשאות: ${esc(m.grants)}</li>` +
    `<li>Google יחזיר אתכם לשירות החיבורים, והחשבון ייווצר אוטומטית.</li>` +
    `<li>המסך הזה ימתין ויזהה את החשבון החדש לבד — אין צורך לרענן.</li></ol></div>` +
    `<div class="cw-msg soft">${mIcon("shield")} הסיסמה שלכם לא מוזנת כאן ולא עוברת דרך המסך הזה. ` +
    `אסימוני הגישה נשמרים בשירות החיבורים בלבד.</div>` +
    (_cw.err ? `<div class="cw-msg err">${esc(_cw.err)}</div>` : ``);
  cwBackBtn(foot, "method");
  const go = el("button", "btn grow", "פתחו את חלון ההרשאה");
  go.onclick = () => guard(go, cwOauthStart, "פותחים…");
  foot.appendChild(go);
}

async function cwOauthStart() {
  const d = await cwList();
  if (!_cw) return;
  if (!d) { _cw.err = "לא ניתן לקרוא את רשימת החשבונות מהשירות, ולכן גם לא לזהות חשבון חדש. נסו שוב."; return cwRender(); }
  _cw.before = d.connections.map(c => c.id);
  _cw.prevActive = d.active;
  // as_instance=1 = "the callback should CREATE a connection instance holding these tokens" instead
  // of injecting them into n8n (§1). Same broker + same registered redirect URI as the install wizard.
  const r = await connectOauth(_cw.method.grant_cid || _cw.method.protocol, { as_instance: "1" });
  if (!_cw) return;
  // frame the broker's own words (often English, from its API) so they read as an explanation rather
  // than as a leaked error string — but never replace them: they are the only real diagnosis we have.
  if (!r.ok) { _cw.err = "לא ניתן לפתוח את מסך ההרשאה — " + r.error; return cwRender(); }
  _cw.authUrl = r.authorize_url; _cw.err = null;
  _cw.sub = "waiting"; _cw.deadline = Date.now() + CW_WAIT_MS;
  cwRender(); cwPoll();
}

// THE state the anti-pattern had no room for: consent may simply never arrive, and the UI has to be
// able to say so. Bounded (it times out), cancellable, and it names the ways it can fail.
function cwProvideOauthWaiting(body, foot) {
  body.innerHTML =
    `<div class="sub">ממתינים לאישור בחלון של Google…</div>` +
    `<div class="cw-msg wait">${chipHtml("checking")} <span id="cwWaitLeft">${esc(cwLeftHe())}</span></div>` +
    `<div class="cw-msg soft"><b>אם שום דבר לא קורה, בדרך כלל זו אחת מאלה:</b><ul class="cw-ul">` +
    `<li>חלון ההרשאה נסגר לפני האישור — פתחו אותו שוב.</li>` +
    `<li>הדפדפן חסם את החלון הקופץ — אשרו חלונות קופצים לאתר, או פתחו ידנית בקישור למטה.</li>` +
    `<li>ההרשאה נדחתה במסך של Google — נסו שוב ואשרו את כל ההרשאות.</li>` +
    `<li>כתובת ההחזרה (redirect URI) אינה תואמת את המוגדר ב-Google — יש לתקן בהגדרות ה-OAuth.</li>` +
    `</ul></div>` +
    (_cw.authUrl ? `<div class="cw-msg soft">${mIcon("link")} <a href="${esc(_cw.authUrl)}" target="_blank" ` +
      `rel="noopener">לא נפתח חלון? פתחו את מסך ההרשאה ידנית</a></div>` : ``);
  const cancel = el("button", "btn ghost sm", "ביטול");
  cancel.onclick = () => cwGo("provide", "intro");
  foot.appendChild(cancel);
  const again = el("button", "btn ghost sm", "פתחו שוב");
  again.onclick = () => guard(again, cwOauthReopen, "פותחים…");
  foot.appendChild(again);
  const now = el("button", "btn grow", "בדקו עכשיו");
  now.onclick = () => guard(now, cwPollOnce, "בודקים…");
  foot.appendChild(now);
}
function cwLeftHe() {
  const s = Math.max(0, Math.round((_cw.deadline - Date.now()) / 1000));
  return `נפסיק להמתין בעוד ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
async function cwOauthReopen() {
  const r = await connectOauth(_cw.method.grant_cid || _cw.method.protocol, { as_instance: "1" });
  if (!_cw) return;
  if (!r.ok) { _cw.err = "לא ניתן לפתוח את מסך ההרשאה — " + r.error; return cwGo("provide", "intro"); }
  _cw.authUrl = r.authorize_url; _cw.deadline = Date.now() + CW_WAIT_MS; cwRender();
}

// Poll for the instance the CALLBACK creates: the broker mints it server-side, so a new id appearing
// in the service's own list is the only honest signal that consent actually completed.
function cwPoll() {
  cwStopPoll();
  _cw.poll = setInterval(async () => {
    if (!_cw || _cw.sub !== "waiting") return cwStopPoll();
    if (await cwPollOnce(true)) return;
    if (!_cw || _cw.sub !== "waiting") return;
    if (Date.now() > _cw.deadline) { cwStopPoll(); _cw.sub = "timeout"; return cwRender(); }
    const t = document.getElementById("cwWaitLeft"); if (t) t.textContent = cwLeftHe();
  }, 2000);
}
async function cwPollOnce(quiet) {
  const d = await cwList();
  if (!_cw) return false;
  if (!d) return false;
  const fresh = d.connections.filter(c => !_cw.before.includes(c.id));
  if (!fresh.length) {
    if (!quiet) { const t = document.getElementById("cwWaitLeft"); if (t) t.textContent = "עדיין אין חשבון חדש… " + cwLeftHe(); }
    return false;
  }
  cwStopPoll();
  const inst = fresh[0];
  _cw.connId = inst.id; _cw.label = inst.label || _cw.provider.name; _cw.hint = inst.account_hint || null;
  cwGo("verify"); cwVerifyRun();
  return true;
}

// timeout is a first-class state, not a stuck spinner
function cwProvideOauthTimeout(body, foot) {
  body.innerHTML =
    `<div class="sub">לא זוהה חשבון חדש.</div>` +
    `<div class="cw-msg err">חיכינו שלוש דקות ולא נוצר חשבון חדש בשירות. סימן שהאישור לא הושלם.</div>` +
    `<div class="cw-msg soft"><b>מה לבדוק:</b><ul class="cw-ul">` +
    `<li>האם חלון ההרשאה נפתח בכלל? אם לא — הדפדפן חסם אותו.</li>` +
    `<li>האם הגעתם למסך "connections: … connected ✓"? אם לא, האישור לא הסתיים.</li>` +
    `<li>אם ראיתם שגיאת redirect_uri_mismatch — כתובת ההחזרה ב-Google אינה תואמת להגדרה.</li>` +
    `</ul></div>`;
  cwBackBtn(foot, "method", null, "חזרה לאופן החיבור");
  const retry = el("button", "btn grow", "נסו שוב");
  retry.onclick = () => cwGo("provide", "intro");
  foot.appendChild(retry);
}

// key / password: a real form — labels, hints, and a link to where the value comes from
function cwProvideForm(body, foot) {
  const m = _cw.method;
  body.innerHTML = `<div class="sub">פרטי הגישה עבור <b>${esc(_cw.provider.name)}</b> · ${esc(m.auth_method_label)}</div>`;
  const f = el("div", "cw-form");
  for (const fld of m.needs) {
    const row = el("div", "cw-field",
      `<span class="cw-f-l">${esc(fld.label)}</span>` +
      (fld.hint ? `<span class="cw-f-h">${esc(fld.hint)}</span>` : ``));
    const control = el(fld.type === "textarea" ? "textarea" : "input");
    if (fld.type !== "textarea") control.type = fld.type || "text";
    control.dataset.k = fld.key; control.placeholder = fld.placeholder || "";
    control.autocomplete = fld.type === "password" ? "new-password" : "off";
    if (fld.type === "textarea") {
      control.rows = 7; control.dir = "ltr";
      const fileId = "cwFile_" + Math.random().toString(36).slice(2, 9);
      const picker = el("input", "cw-file-input");
      picker.id = fileId; picker.type = "file";
      picker.accept = ".json,application/json,text/plain";
      const load = el("label", "btn ghost sm cw-file-load", `${mIcon("upload")} בחירת קובץ JSON`);
      load.htmlFor = fileId; load.title = "בחירת קובץ JSON";
      picker.addEventListener("change", () => {
        const file = picker.files?.[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = event => {
          if (typeof event.target?.result === "string") control.value = event.target.result;
        };
        reader.onerror = () => { _cw.err = "שגיאה בקריאת הקובץ."; cwRender(); };
        reader.readAsText(file);
      });
      row.appendChild(load); row.appendChild(picker);
    }
    row.appendChild(control); f.appendChild(row);
  }
  const nameRow = el("label", "cw-field",
    `<span class="cw-f-l">שם לתצוגה</span><span class="cw-f-h">איך החשבון ייקרא במערכת. אפשר לשנות בשלב הבא.</span>`);
  const nameInp = el("input"); nameInp.type = "text"; nameInp.id = "cwLabel";
  nameInp.placeholder = "לדוגמה: תיבת החשבוניות"; nameInp.value = _cw.label || "";
  nameRow.appendChild(nameInp); f.appendChild(nameRow);
  body.appendChild(f);
  if (m.help_url)
    body.insertAdjacentHTML("beforeend",
      `<div class="cw-msg soft">${mIcon("link")} <a href="${esc(m.help_url)}" target="_blank" rel="noopener">` +
      `מהיכן משיגים את הערך הזה?</a></div>`);
  body.insertAdjacentHTML("beforeend",
    `<div class="cw-msg soft">${mIcon("shield")} הערכים נשמרים בכספת של שירות החיבורים ומועברים לשירות ` +
    `${esc(SVC_HE[_cw.service] || _cw.service)} בלבד. הם לא נשמרים בדפדפן ואינם מוחזרים לרשימת החשבונות.</div>`);
  if (_cw.err) body.insertAdjacentHTML("beforeend", `<div class="cw-msg err">${esc(_cw.err)}</div>`);
  cwBackBtn(foot, "method");
  const go = el("button", "btn grow", "שמרו ואמתו");
  go.onclick = () => guard(go, () => cwCreateFromForm(f), "שומרים…");
  foot.appendChild(go);
}

async function cwCreateFromForm(f) {
  const m = _cw.method, secret = {};
  let hint = null, missing = null;
  for (const fld of m.needs) {
    const inp = f.querySelector(`[data-k="${fld.key}"]`);
    const v = (inp && inp.value || "").trim();
    if (!v) { missing = missing || fld.label; continue; }
    secret[fld.key] = v;
    if (fld.is_hint) hint = v;
  }
  if (missing) { _cw.err = `חסר ערך בשדה "${missing}".`; return cwRender(); }
  const label = ($("#cwLabel") && $("#cwLabel").value.trim()) || hint || m.provider_name;
  const d = await cwList();
  if (!_cw) return;
  _cw.prevActive = d ? d.active : null;
  const r = await svcPost(_cw.service, "/connections",
    { protocol: m.protocol, label, account_hint: hint, secret });
  if (!_cw) return;
  if (!r.ok || !(r.d && r.d.id)) {
    _cw.err = (r.d && (r.d.error || r.d.message)) || "השירות לא הצליח לשמור את החשבון. בדקו את הערכים ונסו שוב.";
    return cwRender();
  }
  // keep the secret in memory ONLY until the wizard closes — the rename in step 5 needs it (there is
  // no rename endpoint; see cwFinish). Never persisted, never sent anywhere but this service.
  _cw.secret = secret; _cw.hint = hint; _cw.label = label; _cw.connId = r.d.id;
  cwGo("verify"); cwVerifyRun();
}

// ── step 4: verify — "a connection is never merely added; it is VERIFIED" ────────
// /readyz probes the ACTIVE connection only (§2) and there is no per-connection probe endpoint. So
// verification necessarily selects the new connection first. If the operator then declines to make it
// active, cwFinish restores the previous pointer — the probe must not silently repoint the service.
async function cwVerifyRun() {
  if (!_cw) return;
  _cw.verify = { state: "probing" }; cwRender();
  const sel = await svcPost(_cw.service, "/connections/select", { id: _cw.connId });
  if (!_cw) return;
  if (!sel.ok) {
    _cw.verify = { state: "fail", at: Date.now(),
      reason: (sel.d && (sel.d.reason || sel.d.error || sel.d.message)) || "השירות לא הצליח לבחור את החשבון." };
    return cwRender();
  }
  const ready = await svcJson(_cw.service, "/readyz");
  if (!_cw) return;
  const list = await cwList();
  if (!_cw) return;
  const inst = list && list.connections.find(c => c.id === _cw.connId);
  const st = readyState(ready);
  _cw.verify = { state: st === "ok" ? "ok" : "fail", at: Date.now(), reason: readyReason(ready, st), inst };
  if (inst && inst.label) _cw.label = inst.label;
  if (inst && inst.account_hint) _cw.hint = inst.account_hint;
  cwRender();
}

function cwVerify(body, foot) {
  const v = _cw.verify || { state: "probing" };
  if (v.state === "probing") {
    body.innerHTML = `<div class="sub">מאמתים את החשבון מול השירות…</div>` +
      `<div class="cw-msg wait">${chipHtml("checking")} השירות מנסה להתחבר בפועל עם הפרטים שנשמרו. ` +
      `זו אותה בדיקה (/readyz) שהאוטומציה מסתמכת עליה — לכן חשבון שעובר אותה עובד גם בתהליכים.</div>`;
    foot.appendChild(el("span", "cw-note", "רגע…"));
    return;
  }
  if (v.state === "ok") {
    body.innerHTML = `<div class="sub">החשבון אומת.</div>` +
      `<div class="cw-msg ok">${chipHtml("ok")} ${esc(v.reason)}</div>` +
      `<div class="cw-msg soft">` +
      `<div><b>חשבון:</b> ${esc(_cw.label)}${_cw.hint && _cw.hint !== _cw.label ? " · " + esc(_cw.hint) : ""}</div>` +
      `<div><b>אופן חיבור:</b> ${esc(_cw.method.auth_method_label)}</div>` +
      `<div><b>נבדק:</b> ${esc(hhmm(v.at))}</div></div>`;
    const go = el("button", "btn grow", "המשך");
    go.onclick = () => cwGo("done");
    foot.appendChild(go);
    return;
  }
  // failure names what to fix, in the SERVICE's own words — never a stack trace, never a dead end
  body.innerHTML = `<div class="sub">האימות נכשל.</div>` +
    `<div class="cw-msg err">${chipHtml("error")} <b>השירות מדווח:</b> ${esc(v.reason)}</div>` +
    (_cw.method.fix_hint ? `<div class="cw-msg soft"><b>מה לבדוק:</b> ${esc(_cw.method.fix_hint)}</div>` : ``) +
    `<div class="cw-msg soft">החשבון נשמר, אך הוא לא עובד כרגע — אפשר לתקן ולנסות שוב, או להסיר אותו.</div>`;
  const retry = el("button", "btn ghost sm", `${mIcon("refresh")} בדקו שוב`);
  retry.onclick = () => cwVerifyRun();
  foot.appendChild(retry);
  if (_cw.secret) cwBackBtn(foot, "provide", null, "תיקון פרטי הגישה");
  else cwBackBtn(foot, "method", null, "חזרה לאופן החיבור");
  if (!_cw.method.always_on) {
    const rm = el("button", "btn ghost sm cw-danger", `${mIcon("trash")} הסירו את החשבון`);
    rm.onclick = () => guard(rm, cwDropConn, "מסירים…");
    foot.appendChild(rm);
  }
  const anyway = el("button", "btn grow", "המשך בכל זאת");
  anyway.title = "החשבון יישמר במצב 'דורש טיפול'";
  anyway.onclick = () => cwGo("done");
  foot.appendChild(anyway);
}

async function cwDropConn() {
  if (!_cw || !_cw.connId) return;
  await svcJson(_cw.service, "/connections/" + encodeURIComponent(_cw.connId), { method: "DELETE" });
  if (!_cw) return;
  if (_cw.prevActive) await svcPost(_cw.service, "/connections/select", { id: _cw.prevActive });
  closeConnectWizard();
}

// ── step 5: name + activate ──────────────────────────────────────────────────
function cwDone(body, foot) {
  const v = _cw.verify || {};
  const ok = v.state === "ok";
  // The contract has POST/DELETE only — no rename endpoint (§1/§2). We can honour a rename exactly
  // where the console still holds the secret (a key/password account, created moments ago): recreate
  // + drop the old one. An OAuth account's tokens never reach the browser (§5) and the local account
  // has no secret at all, so their names stay as the service set them — and the field says so.
  const canRename = !!_cw.secret;
  body.innerHTML =
    `<div class="sub">כמעט סיימנו — שם לתצוגה, והאם זה החשבון שהמערכת תעבוד מולו.</div>` +
    (ok ? `<div class="cw-msg ok">${chipHtml("ok")} החשבון אומת ב-${esc(hhmm(v.at))}.</div>`
        : `<div class="cw-msg err">${chipHtml("action")} החשבון נשמר אך לא עבר אימות: ${esc(v.reason || "")}</div>`);
  const f = el("div", "cw-form");
  const row = el("label", "cw-field",
    `<span class="cw-f-l">שם לתצוגה</span>` +
    `<span class="cw-f-h">${canRename ? "כך החשבון ייקרא בכל מקום במערכת."
      : _cw.method.always_on ? "לחשבון המקומי יש שם קבוע שנקבע על ידי השירות."
      : "השם נקבע לפי החשבון שאישרתם אצל הספק, ולא ניתן לשנותו מכאן."}</span>`);
  const inp = el("input"); inp.type = "text"; inp.id = "cwName"; inp.value = _cw.label || "";
  inp.disabled = !canRename;
  row.appendChild(inp); f.appendChild(row);
  body.appendChild(f);
  const act = el("label", "cw-check");
  act.innerHTML = `<input type="checkbox" id="cwActive" checked>` +
    `<span><b>הפוך לחשבון הפעיל</b><small>כל פעולה של ${esc(SVC_HE[_cw.service] || _cw.service)} — גם ` +
    `במסך וגם באוטומציה — תרוץ מול החשבון הפעיל.</small></span>`;
  body.appendChild(act);
  if (_cw.prevActive && _cw.prevActive !== _cw.connId)
    body.insertAdjacentHTML("beforeend",
      `<div class="cw-msg soft">אם לא תסמנו, נחזיר את החשבון הפעיל הקודם.</div>`);
  if (_cw.err) body.insertAdjacentHTML("beforeend", `<div class="cw-msg err">${esc(_cw.err)}</div>`);
  cwBackBtn(foot, "verify");
  const fin = el("button", "btn grow", "סיום");
  fin.onclick = () => guard(fin, cwFinish, "שומרים…");
  foot.appendChild(fin);
}

async function cwFinish() {
  if (!_cw) return;
  const inp = $("#cwName");
  const makeActive = !!($("#cwActive") && $("#cwActive").checked);
  const newLabel = inp && !inp.disabled ? inp.value.trim() : null;
  if (inp && !inp.disabled && !newLabel) { _cw.err = "נא לתת שם לחשבון."; return cwRender(); }
  _cw.err = null;
  if (newLabel && _cw.secret && newLabel !== _cw.label) {   // rename = recreate (no rename endpoint)
    const mk = await svcPost(_cw.service, "/connections",
      { protocol: _cw.method.protocol, label: newLabel, account_hint: _cw.hint, secret: _cw.secret });
    if (!_cw) return;
    if (!mk.ok || !(mk.d && mk.d.id)) {
      _cw.err = "שינוי השם נכשל, והחשבון נשאר בשם הקודם. אפשר לסיים כך ולנסות שוב מאוחר יותר.";
      return cwRender();
    }
    const old = _cw.connId;
    _cw.connId = mk.d.id; _cw.label = newLabel;
    await svcJson(_cw.service, "/connections/" + encodeURIComponent(old), { method: "DELETE" });
    if (!_cw) return;
  }
  const target = makeActive ? _cw.connId : (_cw.prevActive || _cw.connId);
  const s = await svcPost(_cw.service, "/connections/select", { id: target });
  if (!_cw) return;
  if (!s.ok) {
    _cw.err = "עדכון החשבון הפעיל נכשל: " +
      ((s.d && (s.d.reason || s.d.error || s.d.message)) || "השירות דחה את הבקשה.");
    return cwRender();
  }
  const service = _cw.service;
  closeConnectWizard();   // the bar re-probes on close — the final state is confirmed, not claimed
  if (makeActive) reloadEmbeddedApp(service);
}




function closeModal() {
  cwStopPoll();   // a wizard removed by this generic close must not leave its consent poll running
  const ov = document.querySelector(".modal-ov"); if (ov) ov.remove();
}
// Esc closes the connect wizard (the palette has the same affordance) — a modal you can't dismiss
// with the keyboard is its own small dead end.
window.addEventListener("keydown", e => {
  if (e.key === "Escape" && _cw) { e.preventDefault(); closeConnectWizard(); }
});


// `params` (optional) rides through to the broker — the console's /api/conn/oauth/<cid>/start proxy
// forwards the query string. No params = grant → inject (the credential plane's default); the connect
// wizard passes as_instance=1 (grant → new connection instance).
//
// Returns {ok, authorize_url} | {ok:false, error} — it must never just do nothing. Silently
// swallowing a broker failure here IS the console→connections 404 bug (§4b): a primary CTA that
// looks like it worked and didn't. Callers are responsible for showing `error`.
async function connectOauth(id, params) {
  const q = params ? "?" + new URLSearchParams(params) : "";
  let d = null, err = null;
  try {
    const r = await fetch("/api/conn/oauth/" + id + "/start" + q);
    d = await r.json().catch(() => null);
    if (!r.ok) err = (d && (d.message || d.error)) || `שירות החיבורים החזיר שגיאה (${r.status})`;
  } catch (e) { err = "שירות החיבורים אינו זמין כרגע."; }
  if (!err && !(d && d.authorize_url)) err = "לא התקבלה כתובת הרשאה משירות החיבורים.";
  if (err) return { ok: false, error: err };
  // NOTE: with "noopener" the browser returns null by design, so the handle says nothing about
  // whether a popup blocker ate it — callers offer the URL as a plain link instead of guessing.
  window.open(d.authorize_url, "_blank", "noopener");
  return { ok: true, authorize_url: d.authorize_url, client_id_present: d.client_id_present };
}


function esc(s) { return (s == null ? "" : String(s)).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
boot();
