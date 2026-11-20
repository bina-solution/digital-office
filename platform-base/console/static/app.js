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
  clipboard: '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/>',
  mail:      '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 6-10 7L2 6"/>',
  inbox:     '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  message:   '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8z"/>',
  activity:  '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
  mic:       '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/>',   // the recorder «הקלטות» (CHAT-81)
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
  globe:     '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
  logout:    '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
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
    + "#bina-tell[data-at~=top]{inset-block-start:16px;inset-block-end:auto}#bina-tell[data-at~=end]{inset-inline-start:auto;inset-inline-end:16px}"   // where it covers nothing (place())
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

  // The notice never sits on a control of the page (DGO-618): it keeps its corner while that covers nothing, and
  // otherwise takes the first corner that does — at every frame size, a desktop window of 380 x 260 included,
  // where the bottom corner is where a window keeps its buttons. With no corner free at its full width, the corners
  // again at two thirds and at half of it (a narrower notice fits over a title, beside a window's ✕); with none
  // free at all, the place that covers fewest.
  var CONTROLS = "button,a[href],input:not([type=hidden]),select,textarea,summary,[role=button],[tabindex]:not([tabindex='-1'])";
  function covered(box) {
    var b = box.getBoundingClientRect(), n = 0;
    if (b.width < 2 || b.height < 2) return 0;
    doc.querySelectorAll(CONTROLS).forEach(function (c) {
      var r = c.getBoundingClientRect();     // the cheap test first: on a screen of thousands of rows most are far away
      if (Math.min(b.right, r.right) - Math.max(b.left, r.left) <= 1 || Math.min(b.bottom, r.bottom) - Math.max(b.top, r.top) <= 1) return;
      // inside the notice, in a part of the page made inert (a window the page put over it), or not drawn: not a control here
      if (box.contains(c) || c.closest("[inert]") || (c.checkVisibility && !c.checkVisibility({ checkVisibilityCSS: true }))) return;
      n++;
    });
    return n;
  }
  function put(box, at, w) {
    if (at) box.setAttribute("data-at", at); else box.removeAttribute("data-at");
    box.style.maxWidth = w;
    // a top spot lets go of the bottom, written on the element: a page's own rule that lifts the notice off its bar
    // (`body:has(…) #bina-tell{inset-block-end:…}`) out-ranks the attribute, and the box stretched to the full height
    box.style.insetBlockEnd = at.indexOf("top") < 0 ? "" : "auto";
  }
  function place(box) {
    var best = null;
    ["", "min(280px,calc((100vw - 32px) * .66))", "min(210px,calc((100vw - 32px) * .5))"].some(function (w) {
      return ["", "end", "top", "top end"].some(function (at) {
        put(box, at, w);
        var n = covered(box);
        if (!best || n < best.n) best = { at: at, w: w, n: n };
        return n === 0;
      });
    });
    put(box, best.at, best.w);
  }
  var placing = 0;
  function replace() { var box = doc.getElementById("bina-tell"); if (box && box.firstChild) place(box); }
  window.addEventListener("resize", function () { clearTimeout(placing); placing = setTimeout(replace, 120); });

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
      go.addEventListener("click", function (e) { e.stopPropagation(); n.remove(); replace(); o.act[1](); });
      n.appendChild(go);
    }
    n.addEventListener("click", function () { n.remove(); replace(); });
    box.appendChild(n);
    place(box);
    if (!o.stay) setTimeout(function () { n.remove(); replace(); }, o.ms || (kind === "bad" ? 9000 : 5200));
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
    // is `app`: a neutral window that says "a tile" and nothing else.
    : `<svg class="ic-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${BINA_ICONS.app}</svg>`;
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
function localhostFamily(hostname) {
  return /(^|\.)localhost$/.test(String(hostname || "").toLowerCase());
}
function noNestedHost(hostname) {
  const h = String(hostname || "").toLowerCase();
  return localhostFamily(h)                    // the localhost family
    || !h.includes(".")                          // a bare name (or nothing at all)
    || /^\d{1,3}(\.\d{1,3}){3}$/.test(h)         // an IPv4 address
    || h.includes(":");                          // an IPv6 address
}
const NO_NESTED_HOST = noNestedHost(location.hostname);
// …and of those, the consoles under whose name a nested name cannot even be LOOKED UP: a bare service
// name or an address has no names under it (`bina.hp-laptop.console:8000` and `n8n.192.168.16.102` are DNS
// failures, measured 2026-11-02), while every name under `localhost` is answered by the browser itself, so
// on `console.localhost` a top-level trip to a nested host IS a sign-in (6adb272d) — to this office's own
// app behind the office's sign-in (DGO-1594: `n8n.console.localhost`) and to a linked office's on its own
// host (DGO-1502: Meet on vps1, Plane on the HP, another office's agent, which had become the «כתובת
// מספרית» card with nothing to press). The localhost family is the one whose nested names resolve.
function noNestedName(hostname) {
  return noNestedHost(hostname) && !localhostFamily(hostname);
}
const NO_NESTED_NAME = noNestedName(location.hostname);

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
// …and a trip with nowhere to go is not a trip. On a console whose own hostname has nothing under it
// (noNestedName, above) the name this trip would load cannot exist from here: `<alias>.<office>.console:8000`
// is a DNS failure, not a sign-in — measured 2026-11-02 on the live `console` run, where opening a
// linked office's tile was a top-level load of `bina.hp-laptop.console:8000` and the browser drew
// «This site can't be reached» in place of the whole shell. The trip is refused HERE, once, so every
// caller of it (the shell's own host, a desktop window) is covered by one answer, and `openOwnHost`
// then draws the card that says the name does not exist from this address.
// -> whether the browser is on its way. Refused only where the name cannot be LOOKED UP (NO_NESTED_NAME: a
// bare name or an address), never on the localhost family or a real domain: this office's own app behind the
// office's sign-in (DGO-1594 — refusing it left the n8n tile with «the office is open at a numeric address»
// and nothing to press) and a linked office's app on its own host (DGO-1502) both take the trip.
function leaveFor(url) {
  if (NO_NESTED_NAME) return false;
  location.assign(url);
  return true;                                  // …and the browser is on its way
}
function enterUrl(m) {
  const at = (parseModuleHash() || [])[1] === m.id ? location.hash.slice(1) : "/m/" + m.id;
  return externalUrl(m) + m.enter + at;
}
function enterOwnHost(m) {
  if (enterOwnHost.gone) return false;          // this page has already tried: the card stands
  const key = "do-enter:" + m.id;
  try {
    if (!m.enter || Date.now() - (+sessionStorage.getItem(key) || 0) < 60000) return false;
    sessionStorage.setItem(key, String(Date.now()));
  } catch (e) { return false; }                 // private mode: no memory of a trip, so no trip
  enterOwnHost.gone = true;                     // one attempt per page, however it ends
  return leaveFor(enterUrl(m));
}
let OWN_HOST_WAITING = "";   // the tile whose own host asked for a sign-in (the card is showing)
async function openOwnHost(m, url) {
  const state = await ownHostState(m);
  const cur = parseModuleHash();
  if (!cur || cur[1] !== m.id) return;          // the person moved on while the host was asked
  if (state === "signin" && enterOwnHost(m)) return;   // the trip's door takes it from here
  if (state === "signin" && NO_NESTED_NAME) {
    // …but a trip that `leaveFor` refused (NO_NESTED_NAME) went nowhere, and a shell left standing on the
    // screen it had is not an answer: say the name does not exist from this address, with nothing to press
    // (the same card a measured `address` already draws).
    renderExternalNotice(m, url, "address");
    return;
  }
  OWN_HOST_WAITING = state === "signin" ? m.id : "";
  if (state === "ok") return showEmbed(url);
  renderExternalNotice(m, url, state);
}

// ON A REAL DOMAIN the order is the other way round, and it has to be. There the nested host shares a
// SITE with the identity provider, so a frame signs itself in silently while the provider's own
// session is alive — asking first would interrupt a person for nothing. What it does NOT share is the
// SESSION: every host behind the edge has its own proxy outpost cookie, host-only (`measured
// 2026-10-12`: `authentik_proxy_8M9zLX1H` on the console's host, `authentik_proxy_qt2aADxS` on the
// app's), so the frame's sign-in is the LOGIN PAGE whenever that session has run out — and that page
// answers `X-Frame-Options: DENY`, which a browser renders as its own error page: a flat grey, one
// grey icon, no sentence, no button (the owner's phone, 2026-10-12 23:59 — the identical dead end
// `issues/a-linked-office-tile-fails-blank-and-no-surface-says-why.yaml` ends for the hops the link
// measures). Nothing here can see INSIDE such a frame: it is cross-origin by construction, so
// `externalFallback` returns "cross-origin: it loaded" for an error page as readily as for an app.
// The HOST, though, can be asked — and by then it has had its chance: a host that took the browser
// answers the path its tile names (`signed_in`), and a host still sending an unsigned browser to a
// sign-in redirects. Redirects twice, and the shell draws the card it already owns, whose button is
// the top-level trip through the sign-in and back. `again` is for a window on the desktop, which
// draws its own card; the shell's frame gets `renderExternalNotice`.
function watchOwnHost(m, url, again) {
  if (!m.signed_in) return;
  let left = 2;                                 // one retry: a redirect chain mid-flight is not a verdict
  const ask = async () => {
    if (!again) {                               // the shell's one content frame
      const cur = parseModuleHash();
      if (!cur || cur[1] !== m.id) return;      // the person moved on while the host was asked
      if ($("#embedwrap").classList.contains("hidden")) return;   // a card is already standing there
    }
    if ((await ownHostState(m)) !== "signin") return;   // the host took the browser: the frame is the app
    if (--left > 0) return setTimeout(ask, 2500);
    OWN_HOST_WAITING = m.id;
    if (again) return again();
    renderExternalNotice(m, url, "signin");
  };
  setTimeout(ask, 3000);
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
  // …and the tile in view whose app lives on its own host, on EVERY console: it is the same question
  // `openOwnHost` and `watchOwnHost` ask, and its answer is what decides between the frame and the
  // card. Asked on the console's own clock (`measured 2026-10-12`: a sign-in that ran out under a
  // page left open for the evening turned the tile into a grey frame, and a page left open is the
  // normal case on a phone). On a real domain the old guard skipped this — the assumption above,
  // that a shared domain is a shared session, is what it rested on.
  const m = inView();
  if (!m || !m.signed_in) return;
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
  applyRail();                      // a card is the console's own view: the rail as the console's (DGO-160)
  setActive(m.id); setViewTitle(m);
  $("#content").innerHTML = externalNotice(m, url, need);
}
// The card itself — drawn in the shell's content and in a desktop window (desktop.js: askOwnHost).
function externalNotice(m, url, need, why) {
  const r = remoteInfo(m);
  // An app of a linked office is introduced by its office; an app of this one needs no introduction.
  const where = r ? esc(r.label) + " · " : "";
  const lead = r ? `האפליקציה הזאת רצה בלשכת <b>${esc(r.label)}</b> ו` : "האפליקציה הזאת ";
  let sub, body, action = `<a class="btn" href="${esc(url)}" target="_blank" rel="noopener">פתיחה בחלון נפרד</a>`;
  if (need === "old") {
    sub = `${where}הלשכה הזו עדיין לא מאפשרת את זה כאן`;
    body = `${lead}אינה מעודכנת לגרסה שמאפשרת לפתוח אותה בתוך הקונסול הזה.
       הקישור עצמו תקין — <b>אחרי עדכון אותה לשכה</b> האריח ייפתח כאן במלואו.
       בינתיים אפשר לפתוח אותה בחלון נפרד.`;
    action = `<a class="btn" href="${esc(url)}" target="_blank" rel="noopener">פתיחה בחלון נפרד</a>`;
  } else if (need === "signin") {
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
  } else if (need === "refused") {
    // #63: the app's own answer forbids showing it inside another page (X-Frame-Options or CSP
    // frame-ancestors, asked by /api/frame-check) — so it opens in a tab of its own, and the window
    // says so instead of staying empty.
    sub = `${where}נפתחת בלשונית נפרדת`;
    body = `${lead}אינה מאפשרת להציג אותה בתוך הלשכה, ולכן היא נפתחת בלשונית משלה.`
      + (why ? `<br><code dir="ltr">${esc(why)}</code>` : "");
    action = `<a class="btn" href="${esc(url)}" target="_blank" rel="noopener">פתיחה בלשונית</a>`;
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
  // …and its English name and description (`name_en`/`desc_en`, compiled from the manifest's own
  // title and summary) and its alias: an office in Hebrew is still searched in English (OP-12).
  const hay = [m.name, m.desc, m.id, m.alias, m.name_en, m.desc_en, r ? r.label : "", r ? r.office : ""]
    .join(" ").toLocaleLowerCase();
  if (hay.includes(q)) return true;
  // Every typed WORD on its own, in any order — and a Hebrew word that differs only in its ending:
  // the owner typed «שירותים» for «שירותי צ׳ימני» (EXF, C2 2:25:05; the construct form drops the ־ם).
  // A typed word finds a word that begins with it, or a word of 4+ letters that it begins with.
  const words = hay.split(/[\s·,.:;()\/\-–—]+/).filter(Boolean);
  return q.split(/\s+/).every(w => words.some(x => x.startsWith(w) || (x.length >= 4 && w.startsWith(x))));
}
// EVERY INSTALLED APP IS FOUND (OP-12). The palette reads MODULES — the apps this console FRAMES — and
// an app whose UI lives only on its own host (`embed: false`, e.g. the services apps) has no tile
// there, while the apps screen lists it: «אני עושה חיפוש אני לא מוצא את האפליקציה של השירותים» (EXF,
// C2 2:25:05). So the search also reads the apps screen's OWN list (app-management's /api/apps,
// through this console's proxy — one answer to "what is installed") and opens such an app the way
// that screen does (app-management openApp): a window on the desktop, a new tab anywhere else.
let OTHER_APPS = { at: 0, list: [], p: null };
// A screen the search (and the desktop's «כל האפליקציות») may offer from app-management's list: on, with a
// launch address, not already a tile — and DECLARED a screen. `launch.screen` false is a service whose host
// is all it has (forward-auth's sign-in, traefik's dashboard): they read as «two sign-in apps» (DGO-1760, the
// owner: «כפל זה חמור»). A list from an app-management before that field (no `screen`) is read as before.
function offersScreen(a, known) {
  return !!(a && a.enabled && a.launch && a.launch.url && a.launch.screen !== false
            && !known.has(a.id) && !known.has(a.launch.module));
}
function otherApps() {
  if (OTHER_APPS.p) return OTHER_APPS.p;
  if (Date.now() - OTHER_APPS.at < 60000) return Promise.resolve(OTHER_APPS.list);
  OTHER_APPS.p = fetch("/a/app-management/api/apps").then(r => r.ok ? r.json() : null).catch(() => null)
    .then(j => {
      const known = new Set(MODULES.map(m => m.id));
      const list = ((j && j.apps) || [])
        .filter(a => offersScreen(a, known))
        .map(a => ({ id: a.id, name: a.name || a.id, name_en: a.name_en || "", desc: a.summary || "",
                     icon: a.icon || "app", url: a.launch.url, outside: true }));
      OTHER_APPS = { at: j ? Date.now() : 0, list, p: null };
      return list;
    });
  return OTHER_APPS.p;
}
function openOutside(a) {
  const d = window.BinaDesktop;
  if (d && d.isOn && d.isOn() && d.openExternal && d.openExternal({ id: a.id, name: a.name, url: a.url, icon: a.icon })) return;
  window.open(a.url, "_blank", "noopener");
}
// MAY THIS URL BE SHOWN INSIDE THE OFFICE (#63)? A browser hides a refused frame's reason from the
// page that framed it, so the console asks the app's own answer server-side (/api/frame-check:
// X-Frame-Options and CSP frame-ancestors, judged against this console's origin). A refusal is kept
// per origin for the session, so the next open goes straight to a tab. Anything but a clear
// "refused" (no answer, a sign-in redirect) frames exactly as before.
const FRAME_SAID = {};
function frameKnown(url) { try { return FRAME_SAID[new URL(url).origin] || null; } catch (e) { return null; } }
function frameVerdict(url) {
  let o; try { o = new URL(url).origin; } catch (e) { return Promise.resolve(null); }
  if (FRAME_SAID[o]) return Promise.resolve(FRAME_SAID[o]);
  return fetch("/api/frame-check?url=" + encodeURIComponent(url)).then(r => r.ok ? r.json() : null)
    .catch(() => null).then(v => { if (v && v.verdict === "refused") FRAME_SAID[o] = v; return v; });
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
  // Before the first answer arrives: an address that names an app — or names nothing, which opens the first tile —
  // will be an app, so the rail is already the one it will be and does not fold under the person's eyes once the
  // tiles are in (DGO-160). route() below settles it by the view it actually shows.
  const addressesApp = () => /^(#\/?)?$|^#\/m\/(?!settings(?:[/?#]|$))/.test(location.hash);   // settings is the console's own
  applyRail(addressesApp());
  ME = await fetch("/api/me").then(r => r.json()).catch(() => ({ name: "אורח" }));
  tbMeInit();
  $("#userBox").innerHTML = `מחובר/ת<br><b>${esc(ME.name)}</b>`;
  signoutUrl();   // read once, early: desktop mode's office menu draws its «התנתקות» from it (DGO-1621)
  // the office's mark and the «מחובר/ת» line open the account menu (DGO-1621)
  for (const t of [$("#userBox"), document.querySelector(".brand .logo")].filter(Boolean)) {
    t.setAttribute("role", "button"); t.tabIndex = 0; t.title = "החשבון שלך: מי מחובר, והתנתקות";
    t.setAttribute("aria-haspopup", "menu"); t.setAttribute("aria-expanded", "false");
    t.onclick = () => meMenu(t);
    t.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); meMenu(t); } };
  }
  STAMP = await stamp(true);
  // …and the same answer names the build in the side nav (an unknown one leaves the placeholder).
  if (STAMP && STAMP.version) $("#buildVer").textContent = "digital-office " + STAMP.version;
  await refreshModules(false);
  applyRail(inApp() || addressesApp());
  const rt = $("#railToggle"); if (rt) rt.onclick = toggleRail;
  const pb = $("#paletteBtn"); if (pb) pb.onclick = shellSearch;
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
  // A link that names the CONSOLE and is clicked INSIDE an app's frame is the shell's to open —
  // the frame would otherwise navigate itself and the desk would not move (frame-links.js says why,
  // measured 2026-10-12). The shell's own navigation is the hash, in both modes: route() turns it
  // into the content frame or into a window.
  if (window.BinaFrameLinks) {
    BinaFrameLinks.watch((href) => {
      let hash = "";
      try { hash = new URL(href).hash; } catch (e) { return; }
      if (hash) location.hash = hash;
    });
  }
  // First-run is the SERVER's decision now (app.py spa(): a fresh office — no `installed_at` in the
  // control plane's record — is served install.html instead of this shell), so a bare visit that
  // reaches this line is an installed office, and it opens on its first tile.
  route();
  // An app that needs the person in another app's screen — a sign-in waiting in the office browser —
  // brings him there and back (handoffs.js, DGO-1336; the desktop's window beside it, DGO-1434). It asks
  // WHERE HE IS here, by the one grammar this file owns: on the phone the tile the address names; on the
  // desktop the focused window, with every open window in view — a press inside a window on an app's own
  // host moves neither the focus nor the address, so the address alone missed the window he pressed in.
  // …once per tab: a console view inside a desktop window (`?bare`) runs this shell too, and a second poller
  // would share the trip's memory with the top page (the second reader of DGO-1434).
  const tileOfWin = w => (w && !w.native && !w.sleeping ? String(w.mid).replace(/^ext:/, "") : "");
  if (window.BinaHandoffs && !new URLSearchParams(location.search).has("bare")) BinaHandoffs.start(() => {
    const dm = parseModuleHash();
    const m = dm ? BinaModuleRef.resolve(MODULES, dm[1]) : null;
    const addressed = m ? m.id : "";
    if (!(window.BinaDesktop && BinaDesktop.isOn())) return { front: addressed, seen: [], addressed };
    return { front: tileOfWin(BinaDesktop.wm.focused()), seen: BinaDesktop.wm.wins().map(tileOfWin).filter(Boolean), addressed };
  }, { name: id => (MODULES.find(x => x.id === id) || {}).name || "" });
}
window.addEventListener("hashchange", () => { route(); freshen(true); });
window.addEventListener("message", e => {
  if (e.origin !== location.origin) return;
  if (!e.data || e.data.type !== "platform:modules-changed") return;
  refreshModules();
});

/* ── ONE SEARCH ON THE SCREEN (DGO-1507) ────────────────────────────────────────────────────────
 * The owner's phone, 2026-11-09: mail under the console showed this bar's «חיפוש» (the palette: find
 * a SCREEN) and, a row lower, the app's own magnifier (find MAIL) — two searches, and the one at the top
 * was not the one he wanted inside mail. Google's shell has one: in Gmail its search searches mail.
 * So an app that has a search offers it, and while the frame shows that app the bar's search IS the
 * app's: it says what the app calls it («חיפוש בדואר») and a press opens the app's own search. The app
 * steps its magnifier aside only when the shell answers, so an app under an older console keeps it.
 * Ctrl/⌘ K stays the palette everywhere, and so does the button wherever no app offered.
 *   in   { type: 'bina:search-offer', app, label }   — only from the document #frame shows
 *   out  { type: 'bina:search-taken' }  ·  { type: 'bina:search-released' }  ·  { type: 'bina:find' }
 * The offer belongs to that DOCUMENT: the frame's window stays the same object across navigations,
 * its document does not, so another app in the same frame never inherits a search it did not offer.
 * …and it is taken only while this bar is ON the screen: full screen (`html.bare`) hides the bar, its
 * search and the phone's tab bar, so the shell gives the search back (`bina:search-released`) and takes
 * it again when the bar returns; a console inside a desktop window (`?bare`) has no bar and never takes
 * it. An app that had stepped its magnifier aside brings it back (the second reader of DGO-1507). */
var SEARCH_OFFER = null;                        // { doc, label } — `var`: showContent may ask before this line has run
function shellBarShown() {
  return !document.documentElement.classList.contains("bare") && !new URLSearchParams(location.search).has("bare");
}
/* tell the app that offered whether the bar is over it now (after full screen comes or goes) */
function searchToFrame() {
  const o = offeredSearch(); if (!o) return;
  try { $("#frame").contentWindow.postMessage({ type: shellBarShown() ? "bina:search-taken" : "bina:search-released" }, location.origin); }
  catch (err) { /* gone */ }
}
function offeredSearch() {
  if (!SEARCH_OFFER) return null;
  try {
    const f = $("#frame");
    if (!f || $("#embedwrap").classList.contains("hidden")) return null;
    return f.contentWindow.document === SEARCH_OFFER.doc ? SEARCH_OFFER : null;
  } catch (err) { return null; }                // the frame went to another host
}
function syncShellSearch() {
  const pb = $("#paletteBtn"); if (!pb) return;
  const o = offeredSearch();
  const label = pb.querySelector("span:not(.kbd)");
  if (label) label.textContent = o ? o.label : "חיפוש";
  pb.title = o ? `${o.label} (Ctrl+K: חיפוש מסך)` : "חיפוש מסך (Ctrl+K)";
}
function shellSearch() {
  const o = offeredSearch();
  if (!o) { openPalette(); return; }
  try { $("#frame").contentWindow.postMessage({ type: "bina:find" }, location.origin); }
  catch (err) { openPalette(); }
}
window.addEventListener("message", e => {
  if (e.origin !== location.origin || !e.data || e.data.type !== "bina:search-offer") return;
  let doc = null;
  try {
    const f = $("#frame");
    if (f && e.source === f.contentWindow) doc = f.contentWindow.document;
  } catch (err) { return; }
  if (!doc) return;                             // a desktop window, a widget: not the bar's frame
  const label = String(e.data.label || "").trim().slice(0, 40) || "חיפוש";
  SEARCH_OFFER = { doc, label };
  if (shellBarShown()) {
    try { e.source.postMessage({ type: "bina:search-taken" }, location.origin); } catch (err) { /* gone */ }
  }
  syncShellSearch();
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
// THE ACCOUNT, AND THE WAY OUT (DGO-1621 — the owner, 2026-11-09: «אין לי אפשרות להתנתקות … אתה לוחץ על האייקון של
// הלשכה הדיגיטלית, ואז … ניהול חשבון … תחשוב טוב טוב איפה לשים את זה … שיהיה נקי»; he cleared the browser's site
// data to leave). One small menu, opened from the office's mark and from the «מחובר/ת» line (on a phone, from the
// home screen's header): who is signed in, and «התנתקות» — the office's own sign-out (/api/signout), told to
// come back to this console. A visitor nobody signed in is told there is nothing to leave.
let SIGNOUT = null;   // the office's sign-out page (/api/signout), read once; "" = none here
async function signoutUrl() {
  if (SIGNOUT === null) SIGNOUT = await fetch("/api/signout").then((r) => r.json()).then((d) => d.url || "").catch(() => "");
  return SIGNOUT;
}
let meOpen = null;   // { menu, from } while the menu stands
function meClose(focusBack) {
  if (!meOpen) return;
  const { menu, from } = meOpen;
  meOpen = null;
  menu.remove();
  from.setAttribute("aria-expanded", "false");
  document.removeEventListener("pointerdown", meOutside, true);
  document.removeEventListener("keydown", meKey, true);
  if (focusBack) from.focus();
}
function meOutside(e) { if (meOpen && !meOpen.menu.contains(e.target) && !meOpen.from.contains(e.target)) meClose(false); }
function meKey(e) { if (meOpen && e.key === "Escape") { e.stopPropagation(); e.preventDefault(); meClose(true); } }
let meAsking = null;   // the anchor whose menu waits for /api/signout: a second press meanwhile opens nothing more
// The account button in the top bar, on every screen (DGO-1892): the person's initial in a circle, where every phone
// app keeps it, opening the same account menu as the office's mark (DGO-1621).
function tbMeInit() {
  const b = $("#tbMe"); if (!b) return;
  b.textContent = (((ME && ME.name) || "?").trim().charAt(0) || "?");
  b.onclick = () => meMenu(b);
}
async function meMenu(anchor) {
  const was = meOpen && meOpen.from;
  meClose(false);
  if (was === anchor || meAsking) return;   // a second press on what opened it closes it
  meAsking = anchor;
  const url = await signoutUrl();
  meAsking = null;
  const m = el("div", "me-menu");
  m.setAttribute("role", "menu");
  const back = encodeURIComponent(location.origin + "/");
  m.innerHTML = `<div class="me-who" title="${esc(ME.email || "")}">מחובר/ת בתור<b>${esc(ME.name)}</b></div>` +
    (url
      ? `<a class="me-out" role="menuitem" href="${esc(url + (url.includes("?") ? "&" : "?") + "rd=" + back)}"
           title="יוצא מהלשכה בכל האפליקציות; הכניסה הבאה תבקש סיסמה">${mIcon("logout")}<span>התנתקות</span></a>`
      : `<div class="me-none">בלשכה הזאת אין התנתקות מכאן</div>`);
  document.body.appendChild(m);
  // beside what opened it, inside the window: under it in the top half, above it in the bottom half
  const r = anchor.getBoundingClientRect(), w = m.offsetWidth, h = m.offsetHeight;
  m.style.top = `${Math.max(8, Math.min(r.top < innerHeight / 2 ? r.bottom + 6 : r.top - h - 6, innerHeight - h - 8))}px`;
  m.style.left = `${Math.max(8, Math.min(r.right - w, innerWidth - w - 8))}px`;
  meOpen = { menu: m, from: anchor };
  anchor.setAttribute("aria-expanded", "true");
  document.addEventListener("pointerdown", meOutside, true);
  document.addEventListener("keydown", meKey, true);
  const out = m.querySelector(".me-out");
  if (out) out.focus();
}

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
    ${groups.map((g) => `${g.name ? `<div class="home-group">${esc(g.name)}</div>` : ""}
      <div class="home-grid">${g.mods.map(tile).join("")}</div>`).join("")}
  </div>`;
  // The home screen is its tiles (the owner, 2026-11-18, msg 1270, DGO-1892): no clock and no account button inside
  // the view — the office's name is the top bar's title here, and the account is the bar's last control (#tbMe).
  $("#viewTitle").innerHTML = `<span class="logo vt-home-logo" aria-hidden="true">${(document.querySelector(".brand .logo svg") || {}).outerHTML || ""}</span>הלשכה הדיגיטלית`;
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
        // apart in the rail ("עזריה · MacBook" beside "עזריה"). An office that is not
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
// WHILE AN APP IS OPEN, THE RAIL GETS OUT OF ITS WAY (DGO-160 · ai/context/platform-navigation-design.md §3.9 — the
// owner: «should be perfect and auto collaps when using the apps»). On a desktop the rail is the whole menu on the
// console's own views (#content: the home, install, connections, a card) and folds to its icons the moment a view
// is an app (#embedwrap), so the app has the width; it comes back when the view is the console's again. That is
// the desktop's DEFAULT, and the person's pin beats it: the toggle pins the opposite of what is shown, and a pin
// that equals the default of the view it was set on is no pin (so one more press is «automatic» again). The tablet
// band is a rail whatever is pinned (the full menu does not fit there). Evaluated on a change of VIEW (showEmbed,
// showContent, a card) and of band only — never on the app's own navigation inside its frame, so the rail does not
// breathe while one moves around inside an app; folding moves the grid's column, never the frame, so nothing reloads.
const RAIL_PIN = "nav.pin.desktop";   // "rail" | "open" | absent (the default above)
// The pin is read from storage ONCE and held: a browser that reads but cannot write (a full quota, a private
// window) would otherwise keep answering the old value, and the toggle would do nothing (the second reader).
let railPinHeld;
function railPin() {
  if (railPinHeld !== undefined) return railPinHeld;
  railPinHeld = null;
  try {
    // the toggle's old key meant «always folded» when it was "1": carried over once as that pin
    const old = localStorage.getItem("railCollapsed");
    railPinHeld = localStorage.getItem(RAIL_PIN) || (old === "1" ? "rail" : null);
    if (old !== null) {
      if (railPinHeld) localStorage.setItem(RAIL_PIN, railPinHeld);
      localStorage.removeItem("railCollapsed");
    }
  } catch (e) { /* no storage: the default, held as null */ }
  return railPinHeld;
}
function setRailPin(pin) {
  railPinHeld = pin;
  try {
    if (pin) localStorage.setItem(RAIL_PIN, pin); else localStorage.removeItem(RAIL_PIN);
  } catch (e) { /* held above for this page's life */ }
}
function inApp() {
  const w = document.getElementById("embedwrap");
  return !!w && !w.classList.contains("hidden");
}
function applyRail(app = inApp()) {
  const pin = railPin();
  // A phone has no rail at all (the side is hidden, the tab bar is the menu): `.rail-collapsed`'s 56px column there
  // would squeeze the whole app into it, since that rule outweighs the phone's one column (the second reader).
  const collapsed = !PHONE.matches && (RAIL_BAND.matches || (pin ? pin === "rail" : app));
  // ONE class on the shell. `.rail-host` is the component's own trigger, so what a rail looks
  // like is defined in bina-nav.css for every app — the shell only says whether it is one.
  document.getElementById("app").classList.toggle("rail-host", collapsed);
  document.getElementById("app").classList.toggle("rail-collapsed", collapsed);
  const t = $("#railToggle"); if (t) t.setAttribute("aria-expanded", String(!collapsed));
}
if (RAIL_BAND.addEventListener) RAIL_BAND.addEventListener("change", () => applyRail());
if (PHONE.addEventListener) PHONE.addEventListener("change", () => applyRail());
function toggleRail() {
  // a rail here whatever is pinned (or, on a phone, no rail): a press would only hide a pin for the desktop
  if (RAIL_BAND.matches || PHONE.matches) return;
  const want = document.getElementById("app").classList.contains("rail-collapsed") ? "open" : "rail";
  setRailPin(want === (inApp() ? "rail" : "open") ? null : want);
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
  focusToFrame(on);
  searchToFrame();                          // the bar's search goes with the bar, and comes back with it (DGO-1507)
  if (!on) leaveFullscreen();
}
// The embedded app's own navigation is the app's to hide — and it is the other half of the same
// screen: on a phone the agent's rail is 57px of a 390px frame (15% of the width, always), and its
// side panel opens over another 45–70%. So the shell DECLARES its state on the app's own document
// (`data-shell-focus`), exactly as it already declares the theme there (`applyThemeTo`), and the
// app's plugin reads it: one writer of one fact, and an app that knows nothing about it simply
// ignores the attribute. Same-origin by construction — every app is proxied under /a/<name>/.
function focusToFrame(on) {
  const f = $("#frame");
  if (!f) return;
  try {
    const d = f.contentDocument;
    if (d && d.documentElement) d.documentElement.toggleAttribute("data-shell-focus", !!on);
  } catch (e) { /* a frame not loaded yet, or a future cross-origin app: the shell's half still works */ }
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
  focusToFrame(focusOn());     // the fact, not a request: the app folds its own navigation with it
}

// ── a link inside an app that points INTO the office opens HERE ───────────────────────────────────
// An app framed at `/a/<alias>/` is same-origin with this shell, so the shell can read its document —
// and it must, because a link in it to another part of the office was leaving the office: the agent's
// own answer carries a work-item link, the harness renders every absolute http(s) link with
// `target="_blank"` (its own renderer, by design), and the click opened a SECOND TAB that then asked
// for a sign-in — while the office was open, signed in, one click away (owner, 2026-10-09: «אין מצב
// שכל פעם שאני שולח לי קישור למשימה זה יפתח בחלון נוסף וידרוש לוגין»).
//
// What opens here is a URL THIS OFFICE serves: this console's own route (`#/m/<id>…`) or a tile's
// nested host (`<host>.<this console's host>`). Anything else — a site on the internet — is somebody
// else's page; a new tab is right for it and this listener does nothing to it.
//
// `officeTarget` is the rule, whole and pure, so the test can hold it without a browser.
function officeTarget(href, base, modules, here) {
  let u, me;
  try { u = new URL(href, base); me = new URL(base); } catch (e) { return null; }
  if (u.origin !== me.origin) {
    // a linked office's app lives on its own nested host, port-less match on the host name
    if (u.hostname.endsWith("." + me.hostname)) {
      const label = u.hostname.slice(0, -(me.hostname.length + 1));
      const m = (modules || []).find(x => (x.host || x.id) === label);
      if (m && m.external) return { module: m.id, path: u.pathname + u.search };
    }
    return null;
  }
  // a person's link (DGO-1433): `/go/<ref>`, which this console resolves into one of its own routes
  if (/^\/go(\/|$)/.test(u.pathname)) return { go: u.pathname + u.search };
  const route = /^#\/m\/([^/?#]+)([/?].*)?$/.exec(u.hash || "");
  if (route) {
    const m = (modules || []).find(x => x.id === route[1]);
    if (m) return { module: m.id, path: route[2] || "" };
    return null;
  }
  return null;
}

// …a `/go/<ref>` is asked of this console's own resolver, which answers the route as JSON when asked for JSON
// (app.py `go`), and the shell moves its own route: navigated as it is, the FRAME would load the shell again
// inside itself. A console that cannot answer: the address itself, as a top-level page.
function goTo(path) {
  fetch(path, { headers: { Accept: "application/json" }, credentials: "same-origin", redirect: "manual" })
    .then(r => (r.ok ? r.json() : null))
    .then(j => { if (j && typeof j.to === "string" && j.to.startsWith("/#/m/")) location.hash = j.to.slice(1); else location.assign(path); })
    .catch(() => location.assign(path));
}

// …and the listener that uses it, on the APP's document (the frame is replaced on every navigation,
// so the mark is put on the document, not on the shell).
function officeLinksIntoFrame() {
  const f = $("#frame");
  let doc;
  try { doc = f && f.contentDocument; } catch (e) { return; }   // cross-origin: not ours to read
  if (!doc || doc.__officeLinks) return;
  doc.__officeLinks = true;
  doc.addEventListener("click", (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
    if (!a) return;
    const t = officeTarget(a.getAttribute("href"), doc.baseURI || location.href, MODULES);
    if (!t) return;
    e.preventDefault();
    e.stopPropagation();
    if (t.go) { goTo(t.go); return; }
    location.hash = "#/m/" + t.module + (t.path || "");
  }, true);
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
  let items = [], sel = 0, others = [];
  const render = () => {
    items = MODULES.filter(m => moduleMatches(m, input.value))
      .concat(others.filter(m => moduleMatches(m, input.value)));
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
  const go = i => {
    const m = items[i]; if (!m) return;
    closePalette();
    if (m.outside) openOutside(m); else location.hash = "#/m/" + m.id;
  };
  input.oninput = render;
  input.onkeydown = e => {
    if (e.key === "ArrowDown") { sel = Math.min(items.length - 1, sel + 1); markSel(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); markSel(); e.preventDefault(); }
    else if (e.key === "Enter") { go(sel); e.preventDefault(); }
    else if (e.key === "Escape") closePalette();
  };
  render(); input.focus();
  // the apps that are not framed here join the list when the apps screen's answer comes in
  otherApps().then(l => { others = l; if (l.length && document.body.contains(list)) render(); });
}
function closePalette() { const o = document.querySelector(".pal-ov"); if (o) o.remove(); }
window.addEventListener("keydown", e => {
  // not behind an open dialog: it opens over the desktop now (DGO-1634), and the palette would open unseen under
  // it — the key is still this page's (not the browser's address bar), it only waits for the dialog to close
  if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
    e.preventDefault();
    if (!document.querySelector(".modal-ov")) openPalette();
  }
});

// ── mobile bottom tab bar (shown < 640px via CSS; the rail is hidden there) ──
const BOTTOM_PICKS = 4;   // the bar holds seven: «בית», four apps, «פתוחים», «עוד» (the four it always had)
function buildBottomNav() {
  const old = document.querySelector(".bottomnav"); if (old) old.remove();
  // The apps that ASK for a place here (`routing[].module.tab: true` in their app.json, carried by the
  // compiler), in rail order, at most four — the console names no app above it (gate G9; DGO-1800). An app
  // that is not installed has no tile and so no place. A linked office's `remote:` tile carries no `tab`; an app
  // PLACED on this office from another (dgo-extend) keeps the tile its own app.json gives, `tab` included.
  const picks = GROUPS.flatMap(g => MODULES.filter(m => m.group === g && m.tab === true)).slice(0, BOTTOM_PICKS);
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
  // A LINK THAT NAMES NOTHING IS SAID, NOT TELEPORTED. Until now an unknown id went to the office's
  // FIRST tile (`location.replace("#/m/" + MODULES[0].id)`), so a link to an app this office does not
  // run put the person in a different app, under a different address, with nothing explaining it —
  // the same shape as the rename bug above (the owner got the agent where he asked for the work item),
  // and the `layout` suite catches it as «the office has no tile of this name: its address became …».
  // The address is KEPT and the screen says what it is.
  // …and only once the registry is IN. `route()` also runs while the module list is still being
  // fetched (the address is read at load, the tiles arrive a moment later), and an unknown id at that
  // moment is not an unknown id at all — saying "no such screen" then covered EVERY screen on the
  // office and made the live `layout` suite skip six of its modules and pass green (measured
  // 2026-10-13). With nothing in the registry this falls through to the old behaviour, and the
  // shell re-routes when the tiles arrive.
  if (dm && MODULES.length) return renderNoSuchScreen(dm[1]);
  // Phone: the rail is hidden, so the bare hash opens the launcher instead of teleporting into
  // whichever app happens to be first in the registry.
  if (PHONE.matches && MODULES.length) return renderHome();
  const first = MODULES[0];
  if (first) return location.replace("#/m/" + first.id);
  return renderNoModules();
}

// "/a/incoming/" + "/repos/x?y=1" → "/a/incoming/repos/x?y=1"; a bare "?y=1" appends to the root.
function joinEmbed(embed, rest) {
  // `dgoUrl` (mount.js) keeps an embed inside the mount when this shell is served from another
  // office's console (`/a/console-home.<office>/`); at home it is the identity function.
  var base = (typeof dgoUrl === "function") ? dgoUrl(embed) : embed;
  if (!rest) return base;
  return rest.startsWith("?") ? base + rest : base.replace(/\/+$/, "") + rest;
}

// The embedded app reports its inner route after every in-app navigation (same-origin
// postMessage), and the shell mirrors it into the hash with replaceState — the address bar
// is therefore ALWAYS a copyable deep link, with no history spam and no hashchange loop
// (replaceState does not fire hashchange, so route() never re-runs on its own echo).
//
// ── THE `bina:route` LISTENER THAT USED TO BE HERE (deleted 2026-10-13) ─────────────────────────
// It listened for `{type:"bina:route", path}` from the embedded frame and wrote the address bar with
// replaceState — the office protocol the owner retired: «אסור שזה תהיה תלוי בסריקות וקוד מורכב חייב
// פשוט לנתב את כל מה שהקישור בפנימי של אפלקציות בברירת מחדל». The shell reads the frame's own URL
// now (`watchFrameRoute` above, the standard Navigation API), so nothing has to be told. It went once
// its last two carriers — `mailview` and `incoming` — were converted, deployed and measured, and once
// no app in the tree sent it any more (verified repo-wide; `desktop.js`'s twin went with it).
// The two apps that are not installed on this office, `digital-assets` and `social-list`, are
// converted in SOURCE too; a build of them older than that would simply not report its route, and any
// `bbox run`/`bbox update` rebuilds them from source.

// Reachable only when /api/modules answered with nothing — a shell whose registry is empty or whose
// backend is still starting. Better an honest empty state than a blank content pane.
function renderNoModules() {
  setActive(null); setViewTitle(null);
  showContent();
  $("#content").innerHTML = `<div class="wcard"><h3>אין מסכים זמינים</h3>` +
    `<div class="sub">רשימת האפליקציות חזרה ריקה. ודאו שהשירותים פועלים, ורעננו את הדף.</div></div>`;
}

/* The address asks for a screen this office does not have — an app it does not run, or an id from
   another office's tile. Said, with the address kept: the person asked for something specific, and a
   screen that quietly shows a different app is how a link "does not work" (see the note in route()). */
function renderNoSuchScreen(id) {
  setActive(null); setViewTitle(null);
  showContent();
  $("#content").innerHTML = `<div class="wcard"><h3>אין מסך בשם הזה בלשכה הזאת</h3>` +
    `<div class="sub">הכתובת מבקשת <bdi>${esc(id)}</bdi>, ולשכה הזאת לא מריצה אריח בשם הזה. ` +
    `אפשר לבחור מסך מהסרגל — הכתובת נשארת כפי שהיא.</div></div>`;
}

function showContent() {
  $("#content").classList.remove("hidden"); $("#embedwrap").classList.add("hidden");
  syncShellSearch();                        // …and so does the bar's search, when an app had offered its own
  applyRail();                              // the console's own view: the whole menu, unless pinned (DGO-160)
}
function showEmbed(url, service) {
  $("#embedwrap").classList.remove("hidden"); $("#content").classList.add("hidden");
  applyRail();                              // an app: the rail folds to its icons, unless pinned (DGO-160)
  const f = $("#frame");
  // Skip the reload only when the frame is ALREADY THERE — compared against the frame's
  // LIVE location, never the src attribute. SPA navigation moves the frame without
  // touching the attribute, and the account-switch reload rewrites it to an absolute
  // URL; both made the attribute a record of where the shell last AIMED, not where the
  // app IS — which is how a rail click could desync the address bar from the screen
  // (measured live 2026-08-24). Same-origin, so reading the location is ours to do.
  let cur = null;
  try { cur = f.contentWindow.location.pathname + f.contentWindow.location.search; } catch (err) { /* not ours */ }
  // No app's account in the office's bar (DGO-1624, DGO-1641 — the owner: «התפריט הזה אמור להיות נקי, בלי החשבון
  // של הדרייב או החשבון של המייל … בתוך הכותרת של האפליקציה, לא הכותרת של כל האפליקציות»). Every app that has
  // accounts shows, switches and connects them in its own screen (drive's «כוננים», mail's mailboxes, git's
  // «חשבונות ומראות», computers, digital assets, the registrar's session), so the bar keeps the screen's name,
  // the search and full screen. `service` still names whose account switches reload this frame.
  if (cur === url) { watchFrameRoute(); return; } // already there
  // the app arrives with the shell's theme already applied — set it on load, not after, so the app
  // never paints light for a frame and then flips
  f.onload = () => { themeIntoFrame(); watchFrameRoute(); officeLinksIntoFrame(); syncShellSearch(); };
  f.src = url;
  watchFrameRoute();
  syncShellSearch();                        // the app that offered is leaving: the bar is the palette until the next one offers
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
  try {                                                             // a frame that is not ours: a
    w = f.contentWindow;                                            // tile redirected to its own host
    if (!w || !w.location || !w.location.pathname) return;          // throws on reading pathname
  } catch (err) { return; }
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
    //
    // The frame's FRAGMENT is deliberately NOT carried. An app that routes by hash (domains, sites)
    // TRANSLATES the path it is handed into its own hash on load, so the path is the canonical form —
    // and appending the fragment put a second `#` inside the console's tail
    // (`#/m/sites/s/<id>/overview#/s/<id>/overview`, measured 2026-10-12), which the shell's own
    // grammar (`#/m/<id>[/inner][?query]`) has no room for.
    return (path === "/" ? "" : path) + url.search;
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

// A LINKED OFFICE'S «המרכז» THAT CARRIES NO DOOR is an office whose console cannot be mounted: its
// `/mount.js` is not JavaScript there, so the tile can only reach the nested host — another SITE on
// `*.localhost`, where a frame can neither sign a browser in nor be inspected (measured 2026-11-01:
// the MacBook's `/mount.js` answered `text/html` — its own SPA). That is a RELEASE, not a sign-in
// problem, and it has to be answered BEFORE the own-host flow: that flow would try to sign the person
// in and end in a card about «כניסה» or «כתובת», sending the owner to look for the wrong thing.
//
// ONE RULE, BOTH SURFACES: the desktop draws the same card for the same window and calls this through
// the window (desktop.js:askOwnHost), because a fix that reaches only the framed view leaves the other
// one lying. The own-host flow stays right for every OTHER remote app that owns its origin (Plane,
// בינה) — those keep it.
function staleRemoteConsole(m) {
  return !!(NO_NESTED_HOST && m && m.remote && !m.door && m.remote.module_id === "console");
}
window.staleRemoteConsole = staleRemoteConsole;

function openModule(m, rest) {
  // A tile that opens AS THE PAGE (`top`): the business's door on a phone (DGO-1328) — another site, whose
  // sign-in and cookies work only first-party; a frame of it (the content frame or a desktop window) on a
  // localhost console could not sign in. An https address only — a peer's tile is copied as its office
  // wrote it — and its own address alone, no inner path. The tile's hash goes first, so the phone's back
  // lands on the launcher, not on a route that would leave for the door again.
  if (m.top && m.external && /^https:\/\/[^/]/i.test(m.url || "")) {
    history.replaceState(null, "", location.pathname + location.search);
    location.assign(m.url);
    return;
  }
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
    if (staleRemoteConsole(m)) return renderExternalNotice(m, url, "old");
    if (NO_NESTED_HOST && m.signed_in) return openOwnHost(m, url);
    // A REMOTE APP WITH NO DOOR ON A `*.localhost` OFFICE cannot be framed at all: its tile carries
    // no `door` (the linked office publishes it as own-host-only), so the frame would open the
    // nested host — another SITE here — and that frame can neither sign a browser in nor be
    // inspected (a cross-origin frame is by definition "loaded"), so the person sees a dead pane
    // with no explanation (DGO-553: the «המרכז» tile of an office that has not been updated yet).
    // Saying so beats a blank frame: the link is fine, the other office is older.
    if (NO_NESTED_HOST && m.remote && !m.door) return renderExternalNotice(m, url, "old");
    showEmbed(url);
    setTimeout(() => externalFallback(m, url), 2500);   // card only when nothing rendered
    watchOwnHost(m, url);                               // …and the host itself, once the frame had its chance
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

// An app's accounts are the app's own (DGO-1624, DGO-1641): drive's «כוננים», mail's mailboxes, git's «חשבונות
// ומראות» list, switch, connect and remove them in their own screens, so the shell keeps no account bar, no
// health panel and no connect wizard of its own (they were removed with the chip, DGO-1621).

function esc(s) { return (s == null ? "" : String(s)).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
boot();
