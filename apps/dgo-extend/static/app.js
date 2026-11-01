// dgo-extend — the page. Everything it offers comes from /api/context, which asks the app that owns
// each fact: machines (computers), git accounts (git), domains (domains), apps (app-management).
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let CTX = null, EDIT = null, POLL = null, RUN_OFFICE = null, LOG_OFF = 0;

// One glyph from the set above, the size of the text it sits in — the same call the console's shell
// makes (app.js `mIcon`). A name the set lacks draws the neutral window rather than a word.
function mIcon(name) {
  const p = BINA_ICONS[name];
  return `<svg class="ic-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p || BINA_ICONS.app}</svg>`;
}

// The office's MARK, as this screen needs it (flt-004): the colour it publishes as a NAME, written as
// the attribute the palette's own rules paint, and its animal as a glyph. The server sends the pair on
// every linked office (/api/link → items[].mark) — the peer's own if it published one, the pair its
// name gets otherwise — so a card is never half-marked and never blank.
function officeMark(o) {
  const mk = (o && o.mark) || {};
  return { hue: mk.color ? ` data-office-hue="${esc(mk.color)}"` : "",
           animal: mk.animal ? `<span class="office-animal">${mIcon(mk.animal)}</span>` : "" };
}

/* THE GLYPHS THIS SCREEN DRAWS (flt-004) — the office's ANIMAL, on the cards that name a linked office.
   The set is the platform's own (platform-base/bina-ui/bina-icons.js), copied byte-identically and
   kept so by G27, exactly like the two blocks below: a screen that draws an icon draws it from here,
   never from a private set and never as an emoji (flt-003). */
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
/* @bina-said:start */
var binaSaid = (status) => (!status ? "אין תשובה מהשירות"
  : status < 300 ? "התשובה אינה מה שהמסך ציפה לו — רענן את הדף"
  : status === 401 ? "הכניסה פגה — רענן את הדף" : status === 403 ? "אין הרשאה לפעולה הזאת"
  : status === 404 ? "השירות לא מכיר את הבקשה הזאת"
  : status > 501 && status < 505 ? "השירות אינו זמין כרגע" : status >= 500 ? "השירות נתקל בשגיאה"
  : "הבקשה נדחתה");
// a request that could not even be sent answers like one that was refused, with status 0
var binaNoAnswer = () => ({ ok: false, status: 0, json: async () => ({}), text: async () => "" });
/* @bina-said:end */
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
async function api(path, opt) {
  const r = await fetch(path, opt).catch(binaNoAnswer);
  let body = {};
  try { body = await r.json(); } catch (_) { /* empty */ }
  if (!r.ok) throw Object.assign(new Error(body.error || binaSaid(r.status)), { body, status: r.status });
  return body;
}
const post = (p, b, m = "POST") => api(p, { method: m, headers: { "content-type": "application/json" }, body: JSON.stringify(b || {}) });

function pill(status) {
  const m = { ok: ["ok", "תקין"], warn: ["warn", "תקין עם הערות"], failed: ["bad", "נכשל"], running: ["warn", "רץ…"], pending: ["unset", "ממתין"], skipped: ["unset", "דולג"] };
  const [c, t] = m[status] || ["unset", "לא הופעל"];
  return `<span class="pill ${c}">${t}</span>`;
}
// One left-to-right token: bare in a Hebrew cell the line reordered it ("23:56:33 ,4.10.2026").
const when = (t) => (t ? `<bdi>${new Date(t * 1000).toLocaleString("he-IL", { dateStyle: "short", timeStyle: "short" })}</bdi>` : "—");

// A sentence the server worded, in which a `backticked` run is something a person types or looks for
// (a file, a line of configuration, a command): the run is shown as one token.
const ticks = (s) => esc(s).replace(/`([^`]+)`/g, '<span class="tok">$1</span>');

// THIS office, as another office sees it. None of it needs the machine, so it is drawn at once.
let SELF = null, GIVING = null;
// what the office gives, in one cell: the count is the fact, the names are one hover away
const giveText = (g) => (g.mode === "all" ? `כל האפליקציות (${g.count})`
  : g.mode === "some" ? `${g.count} מתוך ${g.total}`
  : (g.chosen ? "לא נותנת דבר" : "עוד לא נבחר"));
async function loadSelf() {
  // an office on older code has no "giving" answer: the card is drawn without that cell
  const [p, g] = await Promise.all([api("api/pair"), api("api/pair/giving").catch(() => null)]);
  SELF = p.home || {};
  GIVING = g;
  const l = p.listen;
  // An office that cannot be dialed says WHY and what would change it (the server's words, one per
  // kind of machine). The cell holds the fact; the sentence under the strip holds the reason — an
  // older server sends no reason, and the cell alone is then what there is to say.
  const only = !l && p.dial_only ? p.dial_only : null;
  $("self").innerHTML = `${SELF.named ? "" : `<div class="callout warn"><b>ללשכה הזאת עוד אין שם.</b> עד שתקבל שם היא מופיעה בלשכות אחרות לפי המזהה שלה.</div>`}
    <div class="meta">
      ${SELF.named ? `<div><div class="k">שם</div><div class="v">${esc(SELF.label)}</div></div>` : ""}
      <div><div class="k">מזהה</div><div class="v"><span class="tok">${esc(SELF.id || "")}</span></div></div>
      <div><div class="k">טביעת זהות</div><div class="v"><span class="tok">${esc(SELF.fingerprint || "")}</span></div></div>
      <div><div class="k">כתובת למנהרה</div><div class="v" id="reachCell">${l ? `<span class="tok">${esc(l.endpoint)}:${esc(l.port)}</span>` : "אין — רק מחייגת"}</div></div>
      ${g ? `<div><div class="k">נותנת ללשכות מחוברות</div><div class="v" id="giveCell" title="${esc(g.apps.filter((a) => a.given).map((a) => a.name).join(" · "))}">${esc(giveText(g))}</div></div>` : ""}
    </div>
    ${only ? `<div class="callout subline" id="dialOnly"><b>הלשכה הזאת רק מחייגת</b> — היא מתחברת רק ללשכה שאפשר לחייג אליה. ${ticks(only.reason)} ${ticks(only.fix)}</div>` : ""}
    ${l && l.moved_from ? `<div class="callout subline" id="listenMoved"><b>הכתובת של המחשב התחלפה.</b> ההצהרה עדיין אומרת <span class="tok">${esc(l.moved_from)}</span>; הלשכות שמחייגות מגיעות לכתובת שלמעלה, וההצעה הבאה לצימוד תישא אותה. ההצהרה מתעדכנת בהפעלה הבאה של הלשכה.</div>` : ""}`;
  $("btnGive").classList.toggle("hidden", !g);
  const btn = $("btnRename");
  btn.textContent = SELF.named ? "שינוי שם" : "מתן שם";
  btn.className = SELF.named ? "btn ghost sm" : "btn sm";
}

async function loadContext() {
  CTX = await api("api/context");
  const h = CTX.home || {};
  // The version is read on the machine that runs this office. An office with no door to its own
  // machine cannot read it — and that is a state with consequences, so it is said as one sentence
  // with what it costs; the engine's own reason stays one hover away.
  // What it does NOT cost any more: a linked office's new app becomes a tile by itself (the
  // projection asks the control plane — measured here 2026-10-05 23:46, macbook/hello-bina). The
  // sentence went on saying tiles wait for a `bbox run` for a day after that stopped being true.
  // …and the button the sentence speaks of says the same thing: it was drawn exactly like its
  // enabled neighbour, right over a note that it does nothing here.
  $("btnAdd").disabled = !!h.error;
  if (h.error) $("btnAdd").title = "אינה זמינה מכאן: ללשכה הזאת אין גישה למחשב שהיא רצה עליו";
  if (h.error) {
    $("home").innerHTML = `<div class="callout warn subline" title="${esc(h.error)}"><b>ללשכה הזאת אין גישה למחשב שהיא רצה עליו.</b>
      לכן הגרסה שלה אינה ידועה ו„התקנת לשכה על מחשב” אינה זמינה מכאן. צימוד לשכה עובד בלי זה, ואפליקציה חדשה של לשכה מחוברת מופיעה כאן כאריח מעצמה.</div>`;
    return;
  }
  $("home").innerHTML = `<div class="meta">
    <div><div class="k">מאגר</div><div class="v mono small">${esc(h.repo)}</div></div>
    <div><div class="k">ענף</div><div class="v mono">${esc(h.branch)}</div></div>
    <div><div class="k">גרסה</div><div class="v mono">${esc((h.commit || "").slice(0, 10))}</div></div>
    <div><div class="k">פורסמה ל־origin</div><div class="v">${h.pushed ? "כן" : "<span style='color:var(--red)'>לא — לשכה מרוחקת לא תוכל למשוך אותה</span>"}</div></div>
  </div><div class="small muted subline">${esc(h.subject || "")}${h.dirty ? ` · ${h.dirty} שינויים שלא נשמרו ב־git (לא יגיעו ללשכה מרוחקת)` : ""}</div>`;
}

async function revealLogin(oid, btn) {
  try {
    const { login } = await api(`api/office/${oid}/login`);
    const box = document.createElement("div");
    box.className = "callout";
    box.innerHTML = `<b>כניסה ללשכה</b> · <a href="${esc(login.url)}" target="_blank" rel="noopener">${esc(login.url)}</a><br>
      <span class="mono">${esc(login.email || "")}</span> / <span class="mono">${esc(login.password || "")}</span>
      ${login.admin_email ? `<br><span class="small muted">מנהל authentik: <span class="mono">${esc(login.admin_email)}</span> / <span class="mono">${esc(login.admin_password || "")}</span></span>` : ""}`;
    btn.closest(".ocard").appendChild(box);
    btn.remove();
  } catch (e) { alertBox(e.message); }
}

// A PAIRED office (kind: paired) linked itself from its own screen: it has no machine, no domain and
// nothing to converge, so it gets its own card — what the link is, how the tunnel is reached, whether
// it answers — and ONE verb: unpair.
const DIR_HE = { use: "משתמשים כאן באפליקציות שלה", serve: "היא משתמשת באפליקציות מכאן", both: "דו־כיווני" };
// an age a person would say, one LTR-safe token: «לפני 61 שנ׳», «לפני 15 שע׳»
const ago = (s) => `לפני <bdi>${s < 90 ? Math.round(s) + " שנ׳" : s < 5400 ? Math.round(s / 60) + " דק׳" : s < 172800 ? Math.round(s / 3600) + " שע׳" : Math.round(s / 86400) + " ימים"}</bdi>`;
// THE TUNNEL, measured where its interface lives (the link's `tunnel`): when a handshake last
// completed. A session is dead at three minutes without one — and for fifteen hours once, and for
// two this afternoon, nothing on this screen could say so.
function shook(t) {
  if (!t) return "";                                    // nothing measures it here: say nothing
  const [cls, text] = t.handshake_age_s == null ? ["muted", "עוד לא הייתה"]
    : t.alive ? ["", ago(t.handshake_age_s)]
      : ["bad", `${ago(t.handshake_age_s)} — המנהרה לא חיה`];
  return `<div><div class="k">לחיצת יד אחרונה</div><div class="v ${cls}" title="${esc(t.endpoint ? "נשמעה לאחרונה מ-" + t.endpoint : "עוד לא נשמעה")}">${text}</div></div>`;
}
const STATE_HE = { up: ["ok", "מחוברת"], down: ["warn", "לא עונה"], unknown: ["unset", "ממתינה לחיבור"] };

// An office that is given LESS than the rest (`serve.only`) says so on its own card: the office's card
// above states what is given to linked offices, and this is the one fact that is per office. An
// office that is not narrowed gets no cell — it is given what that card says.
function givenTo(office, giving) {
  const list = giving && giving.only && giving.only[office];
  if (!list) return "";
  const names = list.map((a) => ((giving.apps || []).find((x) => x.alias === a || x.app === a) || {}).name || a);
  const text = !names.length ? "לא מקבלת דבר" : names.length <= 2 ? `רק ${names.join(" · ")}` : `רק ${names.length} אפליקציות`;
  return `<div><div class="k">מקבלת מהלשכה הזאת</div><div class="v" title="${esc(names.join(" · "))}">${esc(text)}</div></div>`;
}
function pairedCard(p, link, giving) {
  // DELIVERY, NOT THE TUNNEL. `state` says the peer's catalog arrived; `delivery` (when this office's
  // code measures it) adds whether this pair's own door answers HERE. A link with a live handshake
  // and a dead door was a whole day of "502" that no screen named — so a door that does not answer
  // takes the pill, with the port in the tooltip.
  // WHICH hop fell, and the sentence for it, are the office's own verdict (`verdict` — the one the
  // console marks her tiles by). What the catalog pull itself ended with is a detail after it, never
  // the reason: it is the name of an exception.
  let [cls, text] = STATE_HE[(link || {}).state] || STATE_HE.unknown;
  const v = (link || {}).verdict || {};
  if (v.hop === "door") [cls, text] = ["warn", "הדלת לא עונה"];
  // A pair written the wrong way round is neither "not answering" nor "waiting": nothing on this
  // side can repair it, and the pill says so instead of the card quietly describing a dial into a
  // network this office is not on (lnk-032).
  if (v.hop === "pair") [cls, text] = ["bad", "הצימוד הפוך"];
  // …and the door's port rides in the tooltip, as the paragraph above promises: the verdict's
  // sentence replaced the old one and the port went with it.
  const door = ((link || {}).delivery || {}).door || {};
  const why = [v.why, v.hop === "door" && door.port ? `פורט ${door.port}` : "", (link || {}).state_error].filter(Boolean).join(" · ");
  const listens = (p.dial === "host") === (p.role === "joiner");
  // short enough for one cell (the full address is the cell's title): which side is dialed, and where
  const addr = `${p.endpoint}:${p.port}`;
  const reach = p.dial === "relay" ? "דרך לשכה שלישית"
    : `${listens ? "מאזינה כאן" : "מחייגת אליה"} · <span class="mono num">${esc(listens ? "UDP " + p.port : addr)}</span>`;
  const apps = ((link || {}).apps || []).filter((a) => !a.hidden).length;
  const mark = officeMark(link);
  return `<div class="ocard"${mark.hue}><div class="top">
      <div><h4>${mark.animal}${esc(p.label || p.office)}</h4>
        <div class="small muted">לשכה מצומדת${p.paired_at ? " · מאז " + when(p.paired_at) : ""}</div></div>
      <div class="rowacts"><span class="pill ${cls}" title="${esc(why)}">${text}</span>
        <button class="btn danger sm" type="button" data-unpair="${esc(p.office)}" data-label="${esc(p.label || p.office)}" data-fp="${esc(p.fingerprint || "")}"
          title="מסיר את הקישור מהלשכה הזו: הרשומה, האסימון, העמית במנהרה והאריחים שלה">ביטול צימוד</button></div></div>
      <div class="meta">
        <div><div class="k">מה הקישור מאפשר</div><div class="v">${esc(DIR_HE[p.direction] || "")}</div></div>
        <div><div class="k">המנהרה</div><div class="v" title="${esc(addr)} · זוג ${esc(p.slot)}">${reach}</div></div>
        ${shook((link || {}).tunnel)}
        <div><div class="k">אפליקציות שהיא נותנת</div><div class="v">${(link || {}).publishes_nothing ? "לא נותנת דבר" : `<span class="num">${apps}</span>`}</div></div>
        ${givenTo(p.office, giving)}
        <div><div class="k">טביעת זהות</div><div class="v" title="מזהה: ${esc(p.office)}"><span class="tok">${esc(p.fingerprint || "")}</span></div></div>
      </div></div>`;
}

async function loadList() {
  const [{ items: all }, pairs, link, giving] = await Promise.all([
    api("api/office"),
    api("api/pair").catch(() => ({ items: [] })),          // an office on older code has no pairing yet
    api("api/link").catch(() => ({ items: [] })),
    api("api/pair/giving").catch(() => null),              // …and which office is given less than the rest
  ]);
  const paired = pairs.items || [];
  const pairedIds = new Set(paired.map((p) => p.office));
  const items = all.filter((o) => !pairedIds.has(o.id) && o.kind !== "paired");
  const linkOf = (id) => (link.items || []).find((i) => i.office === id);
  const pairedHtml = paired.map((p) => pairedCard(p, linkOf(p.office), giving)).join("");
  if (!items.length) {
    $("list").innerHTML = pairedHtml || `<div class="callout">עדיין אין לשכות מחוברות. <b>צימוד לשכה</b> מחבר לשכה שכבר מותקנת; <b>התקנת לשכה על מחשב</b> מקימה אחת חדשה על מחשב מחובר.</div>`;
    return;
  }
  const mname = (id) => ((CTX?.machines || []).find((m) => m.id === id) || {}).label || id;
  $("list").innerHTML = pairedHtml + items.map((o) => {
    const r = o.run || {};
    const behind = CTX?.home?.commit && o.source?.commit && !CTX.home.commit.startsWith(o.source.commit) && !o.source.commit.startsWith(CTX.home.commit.slice(0, 7));
    // `כניסה` — the console of THAT office and the account its deployment created. Fetched on click
    // and shown in place: a password that is rendered by default is a password in every screenshot.
    const loginBtn = `<button class="btn ghost sm" data-login="${esc(o.id)}" type="button">כניסה</button>`;
    const mark = officeMark(o);
    return `<div class="ocard"${mark.hue}><div class="top">
      <div><h4 title="${esc(o.id)}">${mark.animal}${esc(o.label || o.id)}</h4>
        <div class="small muted" title="${esc(o.path)}">${esc(mname(o.machine))}</div></div>
      <div class="rowacts">${pill(r.status)}
        <button class="btn sm" data-run="${esc(o.id)}" title="מביא את הלשכה הזאת למצב שהוצהר כאן">הפעלה</button>
        <a class="btn ghost sm" href="https://console.${esc(o.domain)}/" target="_blank" rel="noopener" title="פותח את המסוף של הלשכה בלשונית חדשה">פתיחה</a>
        <button class="btn ghost sm" data-log="${esc(o.id)}" title="מה קרה בהפעלה האחרונה">מצב</button>
        <button class="btn ghost sm" data-edit="${esc(o.id)}" title="שינוי ההצהרה של הלשכה">עריכה</button>
        <button class="btn ghost danger sm" data-forget="${esc(o.id)}" data-label="${esc(o.label || o.id)}" title="מוחק רק את ההצהרה מכאן — המחשב והלשכה שעליו נשארים כמו שהם">מחיקת ההצהרה</button></div></div>
      <div class="meta">
        <div><div class="k">דומיין</div><div class="v mono small">${esc(o.domain)}</div></div>
        <div><div class="k">גרסה מוצהרת</div><div class="v mono">${esc((o.source?.commit || "").slice(0, 10))}${behind ? ` <span class="pill warn">שונה מכאן</span>` : ""}</div></div>
        <div><div class="k">הפעלה אחרונה</div><div class="v small">${when(r.ended || r.started)}</div></div>
        <div><div class="k">קונטיינרים</div><div class="v">${r.health ? `${esc(r.health.healthy)}/${esc(r.health.total)} בריאים` : "—"}</div></div>
      </div>
      ${behind ? `<div class="small" style="margin-top:8px"><span class="link" data-upgrade="${esc(o.id)}">שדרוג לגרסה של הלשכה הזו (${esc(CTX.home.commit.slice(0, 10))})</span></div>` : ""}
    </div>`;
  }).join("");
}

function fillForm(o) {
  EDIT = o;
  $("dlgTitle").textContent = o ? `עריכה — ${o.label || o.id}` : "לשכה חדשה";
  $("fId").value = o?.id || ""; $("fId").disabled = !!o;
  $("fLabel").value = o?.label || "";
  $("fMachine").innerHTML = (CTX.machines || []).map((m) =>
    `<option value="${esc(m.id)}">${esc(m.label)} — ${esc(m.account_hint || m.host)}${m.status && m.status !== "ok" ? " (לא זמין)" : ""}${m.memory ? ` · ${esc(m.memory.total_mb || "")}MB` : ""}</option>`).join("")
    || `<option value="">אין מחשבים מחוברים — הוסף באפליקציית מחשבים</option>`;
  if (o) $("fMachine").value = o.machine;
  $("fPath").value = o?.path || "";
  $("fDomain").value = o?.domain || "";
  $("domList").innerHTML = (CTX.domains || []).map((d) => `<option value="office.${esc(d.name)}">`).join("");
  const h = CTX.home || {};
  $("fRepo").value = o?.source?.repo || h.repo || "";
  $("fBranch").value = o?.source?.branch || h.branch || "";
  $("fCommit").value = o?.source?.commit || h.commit || "";
  $("fAccount").innerHTML = `<option value="">ללא (מאגר ציבורי)</option>` + (CTX.git_accounts || []).map((a) =>
    `<option value="${esc(a.id)}">${esc(a.label)}${a.ok === false ? " (לא תקין)" : ""}</option>`).join("");
  $("fAccount").value = o ? (o.source?.account || "") : ((CTX.git_accounts || []).find((a) => a.ok) || {}).id || "";
  const want = o?.apps || {};
  const placed = new Set(o?.placement || []);
  $("fApps").innerHTML = (CTX.apps || []).map((a) => {
    const on = a.id in want ? want[a.id] === "enabled" : (a.core || a.enabled);
    // "מוצג כאן": the app runs on THAT office and keeps its tile in the home console. It is a
    // property of an app this office runs, which is why the box only makes sense next to a checked
    // one — and why the server refuses a placement for an app that is disabled there.
    const place = `<label class="place" title="רץ על הלשכה הזו, ונשאר מוצג ופתוח בלשכה שאתה נמצא בה"><input type="checkbox" data-place="${esc(a.id)}" ${placed.has(a.id) ? "checked" : ""} ${a.core ? "disabled" : ""}> מוצג כאן</label>`;
    return `<label class="${a.core ? "core" : ""}"><input type="checkbox" data-app="${esc(a.id)}" ${on ? "checked" : ""} ${a.core ? "disabled" : ""}>
      ${esc(typeof a.title === "object" ? (a.title.he || a.title.en) : a.title)} <span class="muted mono">${esc(a.memory || "")}</span>${a.core ? "" : place}</label>`;
  }).join("") || `<span class="muted small">רשימת האפליקציות אינה זמינה</span>`;
  $("fReplace").checked = !!o?.engine?.replace_docker;
  $("dlgErr").innerHTML = ""; $("inspectOut").innerHTML = "";
  $("dlg").classList.remove("hidden");
}

function formBody() {
  const apps = {};
  document.querySelectorAll("#fApps input[data-app]:not([disabled])").forEach((c) => { apps[c.dataset.app] = c.checked ? "enabled" : "disabled"; });
  return {
    id: $("fId").value.trim(), label: $("fLabel").value.trim(), machine: $("fMachine").value,
    path: $("fPath").value.trim(), domain: $("fDomain").value.trim().toLowerCase(),
    source: { repo: $("fRepo").value.trim(), branch: $("fBranch").value.trim(), commit: $("fCommit").value.trim(), account: $("fAccount").value || null },
    apps, engine: { replace_docker: $("fReplace").checked },
    // A placement is only meaningful for an app that runs there; an unchecked app drops out here
    // rather than being refused by the server after the fact.
    placement: [...document.querySelectorAll("#fApps input[data-place]")]
      .filter((c) => c.checked && !c.disabled && apps[c.dataset.place] === "enabled")
      .map((c) => c.dataset.place),
  };
}

async function save(andRun) {
  $("dlgErr").innerHTML = "";
  try {
    const b = formBody();
    const res = EDIT ? await post(`api/office/${EDIT.id}`, b, "PUT") : await post("api/office", b);
    $("dlg").classList.add("hidden");
    await loadList();
    if (andRun) await run(res.office.id);
  } catch (e) { $("dlgErr").innerHTML = `<div class="callout bad"><b>לא נשמר:</b> ${esc(e.message)}</div>`; }
}

async function inspect() {
  const machine = $("fMachine").value, path = $("fPath").value.trim() || `/opt/digital-office/${$("fId").value.trim()}`;
  $("inspectOut").innerHTML = `<span class="muted">בודק…</span>`;
  try {
    const r = await post("api/inspect", { machine, path });
    if (!r.exists) { $("inspectOut").innerHTML = `<div class="callout">אין לשכה ב־<span class="mono">${esc(path)}</span> — תותקן חדשה.</div>`; return; }
    if (r.domain) $("fDomain").value = r.domain;
    if (r.repo) $("fRepo").value = r.repo.replace(/https:\/\/[^@/]+@/, "https://");
    Object.entries(r.apps || {}).forEach(([k, v]) => { const c = document.querySelector(`#fApps input[data-app="${k}"]`); if (c && !c.disabled) c.checked = v === "enabled"; });
    $("inspectOut").innerHTML = `<div class="callout ok"><b>נמצאה לשכה קיימת</b> — דומיין <span class="mono">${esc(r.domain)}</span>, גרסה <span class="mono">${esc((r.commit || "").slice(0, 10))}</span> (${esc(r.branch)}). האפליקציות שמופעלות שם סומנו. הגרסה המוצהרת נשארת זו שבחרת — הפעלה תשדרג אליה; שינויים מקומיים יישמרו ב־git stash, ה־.env וה־volumes נשמרים.</div>`;
    if (!$("fPath").value.trim()) $("fPath").value = path;
  } catch (e) { $("inspectOut").innerHTML = `<div class="callout bad">${esc(e.message)}</div>`; }
}

function renderRun(run) {
  if (!run) { $("runSteps").innerHTML = `<div class="muted">עדיין לא הופעלה.</div>`; return; }
  $("runSteps").innerHTML = (CTX?.steps || []).map((s) => {
    const st = run.steps?.[s.id] || {};
    const txt = st.result?.summary || st.error?.reason || "";
    return `<div class="step ${esc(st.status)}"><span class="t">${esc(s.title)}</span><span class="s">${esc(txt)}</span>${pill(st.status)}</div>`;
  }).join("");
  const failed = Object.values(run.steps || {}).find((s) => s.status === "failed");
  $("runErr").innerHTML = failed?.error ? `<div class="callout bad"><b>${esc(failed.error.reason)}</b><div>${esc(failed.error.action || "")}</div>
     ${failed.error.detail ? `<pre class="out err" style="margin-top:8px">${esc(failed.error.detail)}</pre>` : ""}</div>` : "";
}

async function pollRun() {
  if (!RUN_OFFICE) return;
  try {
    const { run } = await api(`api/office/${RUN_OFFICE}/run?since=${LOG_OFF}`);
    renderRun(run);
    if (run?.log?.length) {
      const pre = $("runLog"), atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
      pre.textContent += run.log.map((l) => l.line).join("\n") + "\n";
      if (pre.textContent.length > 200000) pre.textContent = pre.textContent.slice(-150000);
      if (atEnd) pre.scrollTop = pre.scrollHeight;
      LOG_OFF = run.log_offset;
    }
    if (run?.status === "running") { POLL = setTimeout(pollRun, 3000); } else { loadList(); }
  } catch (_) { POLL = setTimeout(pollRun, 6000); }
}

function openRun(oid) {
  clearTimeout(POLL); RUN_OFFICE = oid; LOG_OFF = 0; $("runLog").textContent = "";
  $("runTitle").textContent = `הלשכה ${oid}`;
  $("runDlg").classList.remove("hidden");
  pollRun();
}

async function run(oid) {
  try { await post(`api/office/${oid}/converge`, {}); } catch (e) { if (e.status !== 409) { alertBox(e.message); return; } }
  openRun(oid);
}

// A removal is asked through the office's question, with the facts of what goes — and the question
// does it (`run`): its button is busy while the request runs, a refusal is said IN the question,
// and the list is reloaded on success so the effect is visible.
const askRemoval = async (q) => { if (await binaAsk({ danger: true, ...q })) await loadList().catch((e) => alertBox(e.message)); };
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") document.querySelectorAll(".modal-ov:not(.hidden)").forEach((m) => m.classList.add("hidden"));
});

function alertBox(msg) { $("alerts").innerHTML = `<div class="callout bad"><b>שגיאה:</b> ${esc(msg)}</div>`; }

document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("[data-close],[data-run],[data-edit],[data-log],[data-forget],[data-upgrade],[data-login],[data-unpair]");
  if (!t) return;
  if (t.dataset.close !== undefined) { t.closest(".modal-ov").classList.add("hidden"); if (t.closest("#runDlg")) { clearTimeout(POLL); RUN_OFFICE = null; } return; }
  if (t.dataset.run) return run(t.dataset.run);
  if (t.dataset.log) return openRun(t.dataset.log);
  if (t.dataset.login) return revealLogin(t.dataset.login, t);
  if (t.dataset.edit) { const o = await api(`api/office/${t.dataset.edit}`); return fillForm(o); }
  if (t.dataset.upgrade) {
    const o = await api(`api/office/${t.dataset.upgrade}`);
    await post(`api/office/${o.id}`, { source: { ...o.source, commit: CTX.home.commit, branch: CTX.home.branch } }, "PUT");
    return run(o.id);
  }
  if (t.dataset.unpair) {
    return askRemoval({
      title: `לבטל את הצימוד עם «${t.dataset.label}»?`, ok: "ביטול הצימוד",
      body: "יוסרו מהלשכה הזו: רשומת הצימוד, אסימון הקישור, העמית במנהרה — והאריחים שלה בקונסול (עד דקה).\n"
        + "הלשכה השנייה מסירה את הצד שלה באותה פעולה אצלה.",
      facts: t.dataset.fp && [["טביעת זהות", t.dataset.fp]],
      run: async () => {
        // the pair IS removed when this answers; what may still have failed is the compile that takes
        // her tiles off the console — said on the screen, not as a refusal of the unpairing
        const out = await api(`api/pair/${t.dataset.unpair}`, { method: "DELETE" });
        if (out.compiled && !out.compiled.ok) alertBox(`הצימוד הוסר, אבל האריחים של ${t.dataset.label} עוד בקונסול — ההידור לא הצליח${out.compiled.tail ? ": " + out.compiled.tail : ""}. ההפעלה הבאה של הלשכה מסירה אותם.`);
      },
    });
  }
  if (t.dataset.forget) {
    return askRemoval({
      title: `למחוק את ההצהרה של «${t.dataset.label || t.dataset.forget}»?`, ok: "מחיקת ההצהרה",
      body: "ההצהרה נמחקת מכאן בלבד.\nהמחשב והלשכה שרצה עליו נשארים כמו שהם.",
      run: () => api(`api/office/${t.dataset.forget}`, { method: "DELETE" }),
    });
  }
});
$("btnAdd").onclick = () => fillForm(null);
$("btnSave").onclick = () => save(false);
$("btnSaveRun").onclick = () => save(true);
$("btnInspect").onclick = inspect;
$("useHome").onclick = () => { $("fCommit").value = CTX.home.commit || ""; $("fBranch").value = CTX.home.branch || ""; };
$("fId").oninput = () => { if (!EDIT) $("fPath").placeholder = `/opt/digital-office/${$("fId").value.trim() || "…"}`; };
$("btnRefresh").onclick = () => boot();
$("btnRename").onclick = () => {
  $("fName").value = SELF?.named ? SELF.label : "";
  $("fName").placeholder = SELF?.id || "";
  $("renameErr").innerHTML = "";
  $("renameDlg").classList.remove("hidden");
  $("fName").focus();
};
$("btnRenameSave").onclick = async () => {
  const btn = $("btnRenameSave");
  btn.disabled = true; btn.textContent = "שומר…";
  try { await post("api/pair/home", { label: $("fName").value }); $("renameDlg").classList.add("hidden"); await loadSelf(); }
  catch (e) { $("renameErr").innerHTML = `<div class="callout bad">${esc(e.message)}</div>`; }
  finally { btn.disabled = false; btn.textContent = "שמירה"; }
};
$("fName").addEventListener("keydown", (ev) => { if (ev.key === "Enter") $("btnRenameSave").click(); });

// WHAT THIS OFFICE GIVES. `all` ticks every box and locks them (it also covers apps installed later,
// which no list of boxes can show); `some` is exactly the ticked ones; `none` hides the list.
function renderGive() {
  const mode = $("giveMode").value;
  $("giveAppsBox").classList.toggle("hidden", mode === "none");
  $("giveHint").textContent = mode === "none" ? "הקישורים נשארים, אבל הלשכות המחוברות לא יראו אף אפליקציה של הלשכה הזאת."
    : mode === "some" ? "אפליקציה שתותקן בעתיד לא תינתן עד שתסומן כאן." : "";
  $("giveApps").innerHTML = (GIVING?.apps || []).map((a) =>
    `<label><input type="checkbox" data-give="${esc(a.alias)}" ${mode === "all" || a.given ? "checked" : ""} ${mode === "all" ? "disabled" : ""}>
      ${esc(a.name)} <span class="muted tok">${esc(a.alias)}</span></label>`).join("")
    || `<span class="muted small">ללשכה הזאת אין אפליקציות לתת</span>`;
}
$("btnGive").onclick = () => {
  $("giveMode").value = GIVING?.mode === "none" && !GIVING?.chosen ? "all" : (GIVING?.mode || "all");
  $("giveErr").innerHTML = "";
  renderGive();
  $("giveDlg").classList.remove("hidden");
};
$("giveMode").onchange = renderGive;
$("btnGiveSave").onclick = async () => {
  const btn = $("btnGiveSave");
  btn.disabled = true; btn.textContent = "שומר…";
  const apps = [...document.querySelectorAll("#giveApps input[data-give]:checked")].map((c) => c.dataset.give);
  try { await post("api/pair/giving", { mode: $("giveMode").value, apps }); $("giveDlg").classList.add("hidden"); await loadSelf(); }
  catch (e) { $("giveErr").innerHTML = `<div class="callout bad">${esc(e.message)}</div>`; }
  finally { btn.disabled = false; btn.textContent = "שמירה"; }
};

// THE LIST NEVER WAITS FOR THE CONTEXT. The context asks four neighbours and reads this office's own
// checkout; on an office with no door to its own machine that takes its whole timeout, and the list —
// which needs none of it for a paired office — sat on „טוען…” the entire time (seen 2026-10-05).
// Only an INSTALLED office's card reads the context (the machine's name, "differs from here"), so the
// list is drawn again once it lands only when such a card exists.
async function boot() {
  const ctx = loadContext().catch((e) => alertBox(e.message));
  loadSelf().catch((e) => {
    // 409 = the office REFUSES in words (no identity yet: the sentence names the command to run) —
    // a state, shown as one, with the two verbs that would be refused the same way put away.
    // Anything else is a failure to load.
    const refused = e.status === 409;
    $("self").innerHTML = refused
      ? `<div class="callout warn" id="selfRefused">${ticks(e.message)}</div>`
      : `<div class="callout bad"><b>פרטי הלשכה לא נטענו:</b> ${esc(e.message)}</div>`;
    if (refused) { $("btnRename").classList.add("hidden"); $("btnGive").classList.add("hidden"); }
  });
  try { await loadList(); }
  catch (e) {
    // A list that was never read says so where it stands, as the office's own card above it does: under an
    // alert at the top of the page it went on saying „טוען…” for good. One that was read keeps what it read.
    if ($("list").querySelector(":scope > .spin, :scope > #listFailed"))
      $("list").innerHTML = `<div class="callout bad" id="listFailed"><b>הלשכות לא נטענו:</b> ${esc(e.message)}</div>`;
    else alertBox(e.message);
  }
  await ctx;
  if (document.querySelector("#list [data-run]")) { try { await loadList(); } catch (e) { alertBox(e.message); } }
}
boot();
