/* bina-icons.js — the glyphs a tile may name.
 *
 * An app's manifest NAMES its tile's icon (`routing[].module.icon`); every surface that lists apps
 * draws it. There were two sets — the console shell's, and a smaller one the apps screen drew for
 * itself — so one app wore two different icons on two screens, and 13 of 30 wore a box on the
 * second because that set never had their name (measured 2026-10-07).
 *
 * This is the one set. A surface must stay servable on its own, so it carries a COPY of the block
 * below and gate G27 (`scripts/refactor/theme-token-lint.py`) keeps every copy byte-identical:
 * add or change a glyph HERE, then `python3 scripts/refactor/theme-token-lint.py --fix`.
 * `platform-base/console/test_icons.mjs` holds the other half: no manifest names an icon this set
 * lacks. (`app` is the neutral mark a surface draws for a name it does not know, or for no name.)
 *
 * Monochrome, 24x24, stroke = currentColor (Feather/Lucide style): name -> inner SVG markup; the
 * surface wraps it in its own <svg>.
 */
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
