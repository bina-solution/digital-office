/* App manager — the platform's app store.
 *
 * Three tabs, because an app is in exactly one of three situations and each needs different verbs:
 *   installed  — on the system: Open / Disable / Uninstall
 *   store      — in the catalog, not installed: Install
 *   core       — layer 1-2 chassis: no lifecycle (the API refuses it, so the UI must not offer it;
 *                a button that always errors is worse than no button)
 *
 * Everything rendered comes from the app MANIFESTS via /api/apps. This app and the console shell
 * are layer 1-2 — they cannot know which apps a deployment installs, so no name, icon, colour or
 * description is hardcoded here. An app that ships tomorrow renders correctly with no change.
 *
 * NO browser dialogs. confirm()/alert() steal focus, cannot be styled, and read as a different
 * product. Destructive confirmation is an in-UI sheet; results are toasts.
 *
 * IN-FLIGHT OBSERVABILITY: a lifecycle POST is synchronous and slow (pull, create, start, wait
 * healthy, import workflows). Rather than spin a meaningless spinner, the card keeps polling the
 * catalog WHILE the request is in flight and reports what is actually true right now — the live
 * container count climbing, then the automation import. Progress shown is measured, never faked.
 */
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const STATE = { apps: [], counts: {}, project: "", tab: "installed", q: "", office: "", jobs: new Map(),
                remote: null, loaded: false };

// The tile icons — a copy of platform-base/bina-ui/bina-icons.js (gate G27), the set the console's
// rail draws from, so an app wears ONE icon on both screens. This screen had 18 glyphs of its own,
// drawn differently, and showed a box for the 13 apps whose name it lacked.
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
const icon = (n) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
  stroke-linecap="round" stroke-linejoin="round">${BINA_ICONS[n] || BINA_ICONS.app}</svg>`;


/* ── conditions ───────────────────────────────────────────────────────────────
   The server reports a list of claims, not one word. Three of them decide what the operator
   should DO, and the UI must not flatten them back together:
     NotReady   — it is coming up or waiting on something. Wait. Not an alarm.
     AuthFailed — a token expired. Waiting will never fix it; only a human re-authorising will.
     Error      — it is broken. Waiting will not fix it either, but re-auth is not the answer.
   Collapsing these into a red dot is exactly the failure that makes a dashboard untrustworthy. */
const cond = (a, type) => (a.conditions || []).find((c) => c.type === type);
const REASON_HE = {
  NotReady: "בהמתנה", AuthFailed: "נדרש חיבור מחדש", Error: "תקלה",
  AllChecksPassed: "תקין", Disabled: "מושבתת", Archived: "בארכיון",
  DockerUnavailable: "אין מידע", NotInstalled: "לא מותקנת",
  SomeContainersDown: "חלק מהשירותים כבויים", NoContainersRunning: "לא פועל",
  AllContainersRunning: "פועל", ContainersPresent: "מותקנת", InCatalog: "בקטלוג",
};
const COND_HE = { Resolved: "נמצאה", Installed: "מותקנת", Started: "הופעלה", Ready: "מוכנה" };
const STATUS_HE = { True: "כן", False: "לא", Unknown: "לא ידוע" };

/* `installed` (desired) and `running` (actual) are different questions; the card answers both.
   A stopped installed app is not an uninstalled one, and blurring that is how a dashboard lies. */
function statusBadge(a) {
  if (!a.installed) return `<span class="badge b-stop"><i class="dot"></i>לא מותקנת</span>`;
  // Archived is NOT uninstalled: the images are gone, the data and the tile are not.
  if (a.archived) return `<span class="badge b-arch"><i class="dot"></i>בארכיון · הנתונים נשמרו</span>`;
  if (!a.enabled) return `<span class="badge b-off"><i class="dot"></i>מושבתת</span>`;
  if (!a.total) return `<span class="badge b-run"><i class="dot"></i>מותקנת</span>`;
  if (a.running === 0) return `<span class="badge b-off"><i class="dot"></i>נעצרה</span>`;
  if (a.running < a.total) return `<span class="badge b-part"><i class="dot"></i>חלקי ${a.running}/${a.total}</span>`;
  const ready = cond(a, "Ready");
  // Re-auth needed is its own badge: it is actionable, and "unhealthy" would send the operator
  // to the logs instead of to the connect button.
  if (ready?.reason === "AuthFailed") return `<span class="badge b-auth"><i class="dot"></i>נדרש חיבור מחדש</span>`;
  if (ready?.reason === "Error" || a.health === "unhealthy") return `<span class="badge b-bad"><i class="dot"></i>לא תקין</span>`;
  if (ready?.reason === "NotReady") return `<span class="badge b-part"><i class="dot"></i>${esc(ready.message || "בהמתנה")}</span>`;
  return `<span class="badge b-run"><i class="dot"></i>פועל ${a.running}/${a.total}</span>`;
}

const bucket = (a) => (a.core ? "core" : a.installed ? "installed" : "store");
const TABS = [
  { id: "installed", icon: "grid", label: "האפליקציות שלי", lede: "אפליקציות מותקנות — פתיחה, כיבוי והסרה." },
  { id: "store", icon: "box", label: "חנות האפליקציות", lede: "זמינות להתקנה. התקנה מפעילה את השירותים של האפליקציה ומייבאת את האוטומציות שלה ל-n8n." },
  { id: "core", icon: "server", label: "שירותי ליבה", lede: "התשתית של הלשכה — מוגנת מפני כיבוי והסרה." },
  { id: "peers", icon: "globe", label: "לשכות מחוברות", lede: "לשכות מקושרות והאפליקציות שהן מריצות. אפליקציה של לשכה אחרת רצה שם — מכאן רק פותחים אותה." },
];
/* One drawn icon from the office's shared set (BinaNav), the size of the text it sits in. */
const ic = (n) => (typeof BinaNav === "undefined" ? "" : `<span class="gi">${BinaNav.svg(n)}</span>`);
/* ── the side menu: DECLARED, not drawn ────────────────────────────────────────────────────────
   The menu is the office's shared component (BinaNav, spliced into index.html by gate G27). This
   app states WHAT it holds — brand, the four sections of this screen, and the search — and the
   component owns the row, the count, the rail and the drawer. This screen used to build its own
   rows, its own count pill and its own two rail media queries, which is how one office ended up
   with eleven menus: three restatements of what the component already knows. */
let NAV = null;
const HEAD_SUB = "מרכז הבקרה של הפלטפורמה";

function mountNav() {
  if (NAV || typeof BinaNav === "undefined") return NAV;
  const el = $("#sideNav"); if (!el) return null;
  NAV = BinaNav.mount(el, {
    id: "app-management",
    brand: { name: "אפליקציות", sub: HEAD_SUB, avatar: "א" },
    /* ONE search box, in the menu, and it filters the store below — hence `filter:false`: what a
       person is looking for here is an app, not a menu row. */
    search: {
      placeholder: "חיפוש אפליקציה…",
      filter: false,
      value: STATE.q,
      onInput: (q) => { STATE.q = q; renderGrid(); },
    },
    sections: [{
      id: "tabs",
      title: "מצב האפליקציות",
      items: TABS.map((t) => ({
        id: t.id, icon: t.icon, label: t.label, badge: "", title: t.label,
        onClick: () => { STATE.tab = t.id; render(); },
      })),
    }],
  });
  /* The phone's two controls, and only there: the component shows them inside a drawer-sized
     container. The magnifier opens the drawer ON the search, because a phone cannot show both.
     The page only places them (`data-nav-toggle`, `data-nav-find`); the component draws and wires them. */
  return NAV;
}

/* The counts and the current place are UPDATED, not re-drawn: the menu is one object for the life of
   the screen, so a count that changes under the reader never makes the row jump. */
function renderNav(counts) {
  const nav = mountNav(); if (!nav) return;
  TABS.forEach((t) => nav.setBadge(t.id, counts ? String(counts[t.id].length) : ""));
  nav.setActive(STATE.tab);
}

function bucketize() {
  const b = { installed: [], store: [], core: [] };
  for (const a of STATE.apps) b[bucket(a)].push(a);
  return b;
}

/* ── remote apps: the apps of a LINKED office, shown in this list ─────────────────────────────────
   ai/context/dgo-remote-apps.md §5. A remote app is `(office, alias)`: it runs THERE, it is never
   installed, enabled, archived or removed from this screen, and the only verb this screen has for it
   is OPEN (plus the office's own show/hide, which is about this console's rail and not about the
   app). Two halves, each read from its owner and neither restated here:
     · WHICH apps, on which office, and the office's name — the CONSOLE's compiled registry
       (`/api/modules`, the same list the shell's rail renders: one source, so this screen and the
       rail cannot disagree); and
     · the linked offices and their link state — dgo-extend, the app that owns the link plane
       (`/a/dgo-extend/api/link`, through the console's own same-origin proxy). Not installed, or
       older than the link API → the section says exactly that instead of drawing an empty list.
   A failed read is never "no remote apps": what was last known stays, and the reason is printed. */
const REMOTE = { apps: [], offices: [], link: null, reason: "", at: 0, linkAt: 0, linkErr: "" };
const REMOTE_MSG = {
  no_registry: "רשומת האפליקציות המרוחקות עוד לא נוצרה — אין לשכה מקושרת שמפרסמת אפליקציות.",
  no_dgo: "אפליקציית הרחבת הלשכה אינה מותקנת, ולכן אין כאן מידע על לשכות מקושרות.",
  no_link_api: "אפליקציית הרחבת הלשכה מותקנת אבל עוד לא מצהירה על לשכות מקושרות (אין /api/link).",
  no_exclude: "השרת עוד לא מצהיר על מתג ההצגה (אין /api/link/exclude) — המתג יידלק כשהוא ייווצר.",
};

// A name as another office sends it: a string, or `{he, en}` — a catalog carries its titles in both
// languages. Written out as text it is "[object Object]", which is what every linked office's card
// was titled once the catalog started sending the pair (seen on hp-laptop, 2026-10-05).
const said = (v) => (typeof v === "string" ? v : v && typeof v === "object" ? (v.he || v.en || "") : "");

// The office of a registry entry, and its label — the ONE reading of `remote`, identical to the
// shell's (app.js remoteInfo): `label` is a string or `{he,en}`, and an office that did not answer
// says so in Hebrew rather than showing an empty tile. The office's MARK rides along (flt-004) — the
// colour and the animal it publishes as NAMES — so a card, a chip and a row can say WHICH office
// without the reader opening anything. An office that publishes none draws exactly what it drew before.
function remoteOf(m) {
  const r = m && m.remote;
  if (!r || typeof r !== "object") return null;
  const mk = (r.mark && typeof r.mark === "object") ? r.mark : null;
  return { office: String(r.office || ""), label: said(r.label) || String(r.office || ""), off: r.ok === false,
           hue: mk && mk.color ? String(mk.color) : "", animal: mk && mk.animal ? String(mk.animal) : "" };
}

// `data-office-hue="<name>"` — the one spelling of the office's colour on this screen, on whatever
// element already belongs to that office (flt-004). The palette's own `[data-office-hue="…"]` rules
// turn the name into `--office-hue`, so neither this file nor its stylesheet names a colour (G82).
const officeHue = (o) => (o && o.hue ? ` data-office-hue="${esc(o.hue)}"` : "");
// …and the animal, drawn from the same set every other glyph on this screen comes from. Absent when
// the office has none: `fallback` is what the surface drew before the mark existed.
const officeAnimal = (o, fallback) => icon(o && o.animal ? o.animal : fallback);

async function loadRemote() {
  const now = Date.now();
  // the registry half: the console answers /api/modules on the same origin as this screen
  if (now - REMOTE.at > 15000) {
    try {
      const d = await (await fetch("/api/modules")).json();
      REMOTE.apps = (d.modules || []).filter((m) => remoteOf(m));
      REMOTE.at = now;
      REMOTE.reason = REMOTE.apps.length ? "" : REMOTE_MSG.no_registry;
    } catch (e) {
      console.warn("modules", e);
      REMOTE.reason = "רשומת האפליקציות לא נענתה";
    }
  }
  // the link half: dgo-extend owns the link plane. Cheap and read-only (its own words), and asked
  // for at most once a minute — a screen that is open all day must not hammer it.
  if (now - REMOTE.linkAt > 60000) {
    REMOTE.linkAt = now;
    try {
      const r = await fetch("/a/dgo-extend/api/link");
      if (r.ok) {
        REMOTE.link = await r.json();
        REMOTE.linkErr = "";
      } else {
        REMOTE.link = null;
        REMOTE.linkErr = r.status === 404 ? REMOTE_MSG.no_dgo : `הרחבת הלשכה: ${binaSaid(r.status)}`;
      }
    } catch (e) {
      REMOTE.link = null;
      REMOTE.linkErr = REMOTE_MSG.no_dgo;
    }
  }
  REMOTE.offices = remoteOffices();
}

/* The linked offices, from the two halves: every office the registry knows an app of, plus every
   office dgo-extend says is linked (so an office whose apps are ALL hidden still appears, with the
   reason — a section that silently empties itself is the failure this file keeps warning about).
   Rows are keyed by ALIAS, because that is the name the link plane uses (`serve.exclude`, the
   catalog, the peer's own route); the module id is the console's name for the same app and is kept
   beside it. */
function remoteOffices() {
  const by = new Map();
  const add = (office) => {
    let o = by.get(office);
    // `hue`/`animal` are the office's MARK (flt-004), taken from any of its apps' registry entry: an
    // office dgo-extend knows and the registry does not is an office with no mark yet, and it draws
    // what it always drew (a server glyph) rather than a colour nobody published.
    if (!o) { o = { office, label: office, off: false, hue: "", animal: "", apps: new Map(), linked: null, state: "" }; by.set(office, o); }
    return o;
  };
  for (const m of REMOTE.apps) {
    const r = remoteOf(m);
    if (!r) continue;
    const o = add(r.office);
    o.label = r.label || o.label;
    o.off = o.off || r.off;
    o.hue = o.hue || r.hue;
    o.animal = o.animal || r.animal;
    // `/a/<alias>/` is the module's own statement of the alias; the id is the fallback and is what
    // the shell addresses (`#/m/<id>`), which is not always the alias (a local app can own it).
    const alias = (String(m.embed || "").match(/^\/a\/([^/]+)\//) || [])[1] || m.id;
    o.apps.set(alias, { id: m.id, alias, name: m.name, icon: m.icon, desc: m.desc || "", off: r.off, tile: true });
  }
  for (const it of ((REMOTE.link || {}).items || [])) {
    const id = String(it.office || "");
    if (!id) continue;
    const o = add(id);
    if (said(it.label)) o.label = said(it.label);
    o.linked = !!it.declared;
    o.state = it.state || "";
    o.machine = it.machine || "";
    // dgo-extend knows the office's WHOLE app set (including what is hidden here), which the
    // registry by definition cannot: a hidden app has no tile.
    for (const a of (it.apps || [])) {
      const alias = String(a.alias || a.id || "");
      if (!alias) continue;
      const cur = o.apps.get(alias);
      o.apps.set(alias, Object.assign(cur || { id: alias, alias, name: alias, icon: "app", desc: "" }, {
        name: said(a.title) || said(a.name) || (cur && cur.name) || alias,
        icon: a.icon || (cur && cur.icon) || "app",
        desc: said(a.desc) || (cur && cur.desc) || "",
        hidden: !!a.hidden, off: a.ok === false || !!(cur && cur.off), tile: !!cur,
      }));
    }
  }
  return [...by.values()]
    .map((o) => Object.assign(o, { apps: [...o.apps.values()] }))
    .sort((a, b) => String(a.label).localeCompare(String(b.label), "he"));
}

function remoteCard(o, a) {
  return `<article class="card is-remote${a.off ? " is-offline" : ""}"${officeHue(o)} data-remote="${esc(a.id)}">
    <div class="top">
      <div class="ic">${icon(a.icon)}</div>
      <div title="${esc(a.id)}"><div class="nm">${esc(a.name)}</div>
        <div class="idl">${esc(o.label)}</div></div>
    </div>
    <div class="desc">${esc(a.desc || "")}</div>
    <div class="row">
      <span class="badge b-rem"${officeHue(o)}><i class="dot"></i>${o.animal ? `<span class="office-animal">${icon(o.animal)}</span>` : ""}לשכה ${esc(o.label)}</span>
      ${a.off ? `<span class="badge b-off">${esc(o.label)} לא זמינה כרגע</span>` : ""}
    </div>
    <div class="acts"><button class="btn ghost" data-act="openRemote" data-remote="${esc(a.id)}">פתח</button></div>
  </article>`;
}

/* The office filter — one chip per office and one for everything. It is a FILTER, not a switch: the
   show/hide switch lives in "לשכות מחוברות", because hiding an app from the rail is a decision about
   the office, not about the list somebody happens to be looking at. */
function officeBar() {
  if (!REMOTE.offices.length) return "";
  const chip = (v, label, n, mark) =>
    `<button class="chip${STATE.office === v ? " on" : ""}"${officeHue(mark)} data-office="${esc(v)}">${esc(label)}${
      n == null ? "" : ` <b>${n}</b>`}</button>`;
  const nOf = (id) => REMOTE.apps.filter((m) => remoteOf(m).office === id).length;
  // "Everything" carries no number: it used to say «כל הלשכות 10» — the linked offices' apps — over
  // a list of this office's forty.
  return `<div class="officebar">${chip("", "הכל")}${
    REMOTE.offices.map((o) => chip(o.office, o.label, nOf(o.office), o)).join("")}</div>`;
}

/* ── the "לשכות מחוברות" section ─────────────────────────────────────────────────────────────────
   One card per linked office: what it is (machine, link state), its apps with a show/hide switch,
   and the way to link another office — dgo-extend's own connect screens, opened in a tab because
   they are a flow (a machine, a QR code, a paste) and not a panel. */
function peersHTML() {
  if (!REMOTE.offices.length) {
    const why = REMOTE.linkErr || (REMOTE.link ? REMOTE_MSG.no_link_api : "") || REMOTE.reason || REMOTE_MSG.no_registry;
    return `<div class="empty">אין לשכות מקושרות להצגה.<br><span style="font-size:12px">${esc(why)}</span>
      <div style="margin-top:14px">${connectBtn()}</div></div>`;
  }
  return REMOTE.offices.map((o) => {
    const state = o.linked === false ? "מקושרת בלי מנהרה"
      : o.state === "up" ? "הקישור פעיל" : o.state === "down" ? "הקישור לא ענה" : "מקושרת";
    return `<article class="card peer"${officeHue(o)}>
      <div class="top">
        <div class="ic">${officeAnimal(o, "server")}</div>
        <div><div class="nm">${esc(o.label)}</div>
          <div class="idl">${esc(o.office)}${o.machine ? " · " + esc(o.machine) : ""}</div></div>
      </div>
      <div class="row"><span class="badge ${o.off ? "b-off" : "b-run"}"><i class="dot"></i>${esc(state)}</span>
        <span class="badge">${o.apps.length} אפליקציות</span></div>
      ${o.apps.length ? `<div class="peers-list">${o.apps.map((a) => `
        <label class="peers-row${a.off ? " off" : ""}" title="${esc(a.off ? o.label + " לא זמינה כרגע" : o.label)}">
          <span class="peers-ic${a.off ? "" : " is-remote"}"${officeHue(o)}>${icon(a.icon)}</span>
          <span class="peers-nm">${esc(a.name)}</span>
          <input type="checkbox" data-show="${esc(a.id)}" data-office="${esc(o.office)}"
                 data-alias="${esc(a.alias)}"${a.hidden ? "" : " checked"}>
        </label>`).join("")}</div>`
        : `<div class="idl">אין אפליקציות מוצגות מהלשכה הזאת כרגע.</div>`}
    </article>`;
  }).join("") + `<div class="peers-foot">${connectBtn()}</div>`;
}
const connectBtn = () => `<button class="btn" data-act="connect">חיבור לשכה</button>`;

/* The show/hide write. dgo-extend owns it (`serve.exclude`): this screen only says what the owner
   pressed, and reports the answer verbatim. A switch that flips on a 404 and says nothing is the
   "green container is not a usable instance" failure in UI form — so a refusal reverts the box. */
async function setRemoteHidden(office, alias, hidden, box) {
  try {
    const r = await fetch("/a/dgo-extend/api/link/exclude", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ office, alias, hidden }),
    }).catch(binaNoAnswer);
    if (r.status === 404 || r.status === 501) {
      if (box) box.checked = !hidden;
      return binaTell(REMOTE_MSG.no_exclude, "warn", 9000);
    }
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || d.detail || binaSaid(r.status));
    binaTell(hidden ? `${alias} הוסתרה מהקונסול של הלשכה הזאת` : `${alias} תוצג שוב בקונסול`, "ok");
    REMOTE.linkAt = 0;                       // the link half is stale now: re-read it
    await loadRemote(); render();
  } catch (e) {
    if (box) box.checked = !hidden;
    binaTell(`השינוי לא נשמר: ${e.message}`, "bad", 9000);
  }
}

/* Open a remote app the way a local tile opens: by MODULE ID, through the shell. The registry entry
   is the module (`#/m/<id>`), which is what the rail would do with the same click. */
function openRemote(id) {
  if (!id) return;
  const embedded = window.parent && window.parent !== window;
  try {
    if (embedded) { window.parent.location.hash = "#/m/" + id; return; }
  } catch { /* cross-origin parent */ }
  location.href = "/#/m/" + id;
}

/* The cards only — the menu's own search redraws THIS and nothing else, so typing never touches
   the menu's rows, its count badges or the focus the reader is in. */
function renderGrid() {
  const b = bucketize();
  const q = STATE.q.trim().toLowerCase();
  if (STATE.tab === "peers") {
    $("#officebar").innerHTML = "";
    $("#grid").innerHTML = peersHTML();
    return b;
  }
  const list = b[STATE.tab]
    .filter((a) => !q || [a.name, a.name_en, a.id, a.summary].some((v) => String(v ?? "").toLowerCase().includes(q)))
    .sort((a, x) => String(a.name).localeCompare(String(x.name), "he"));

  // The apps that run on a LINKED office are in the SAME list as the local ones ("my apps"),
  // because that is what they are to the person using them: apps this office opens. They are
  // marked, they name their office, and the office chips filter them out again.
  // ONLY what the console actually has a tile for (`tile`): an app the office hides
  // from this console has no tile, so it belongs in the office's own card — with its switch —
  // and not in a list of things that open.
  const rem = STATE.tab !== "installed" ? [] : REMOTE.offices
    .filter((o) => !STATE.office || o.office === STATE.office)
    .flatMap((o) => o.apps
      .filter((a) => a.tile)
      .filter((a) => !q || [a.name, a.id, a.desc].some((v) => String(v ?? "").toLowerCase().includes(q)))
      .map((a) => remoteCard(o, a)));

  $("#officebar").innerHTML = STATE.tab === "installed" ? officeBar() : "";
  const cards = list.map(card).concat(rem);
  $("#grid").innerHTML = cards.length ? cards.join("")
    : `<div class="empty">${q || STATE.office ? "לא נמצאו אפליקציות שמתאימות לסינון."
        : STATE.tab === "installed" && REMOTE.reason ? esc(REMOTE.reason) : "אין כאן אפליקציות."}</div>`;
  return b;
}

/* ── render ───────────────────────────────────────────────────────────────── */
function render() {
  // Nothing is drawn before the catalog has answered ONCE. The linked offices' half arrives beside
  // it and usually first; drawn alone it replaced the skeleton with "0 אפליקציות · 0 פועלות" and
  // those offices' cards — a false count, stated as a fact, for as long as the catalog took
  // (seconds after a restart). The page keeps its skeleton until there is something true to say;
  // the menu is drawn meanwhile, with no counts.
  if (!STATE.loaded) return renderNav(null);
  const b = renderGrid();
  // the peers tab's badge is the number of linked offices, not of apps: the section is about offices
  b.peers = REMOTE.offices;
  renderNav(b);
  $("#lede").textContent = TABS.find((t) => t.id === STATE.tab).lede;

  // Install-by-reference belongs to the store, and only to the store: it is how the catalog grows
  // beyond what shipped in this repo. It is meaningless on "my apps" and forbidden on core.
  $("#installer").hidden = STATE.tab !== "store";

  const c = STATE.counts;
  const rem = REMOTE.apps.length;
  // The same numbers the menu shows, in the menu's own words. "ניתנות להתקנה" used to print the
  // server's `installable` — every app that is not core, installed or not — beside a store badge
  // that counts what is actually left to install: 25 against 18 on one screen.
  $("#sub").textContent = `${c.total ?? 0} אפליקציות · ${c.running ?? 0} פועלות · ${b.store.length} בחנות` +
    (rem || REMOTE.offices.length
      ? ` · ${rem} מרוחקות ${REMOTE.offices.length === 1 ? "בלשכה אחת" : `ב-${REMOTE.offices.length} לשכות`}` : "");
  $("#note").textContent = `פרויקט ${STATE.project} · מתעדכן כל 5 שניות`;
}

function card(a) {
  const job = STATE.jobs.get(a.id);
  // every button says what pressing it will do — the label names the verb, the title the effect
  const WILL = {
    open: "פתיחת האפליקציה", detail: "מה האפליקציה צריכה ומה היא מתקינה",
    install: a.installed ? "הפעלת השירותים של האפליקציה" : "התקנה והפעלה — כאן או בלשכה מקושרת",
    disable: "עצירת השירותים; הנתונים נשמרים", uninstall: "הסרת האפליקציה מהלשכה הזאת",
    move: "העברת האפליקציה והנתונים שלה ללשכה מקושרת",
    archive: "פינוי מקום בדיסק: המכולות והתמונות מוסרות, הנתונים נשמרים",
    unarchive: "הורדה והפעלה מחדש על הנתונים שנשמרו",
  };
  const btn = (cls, act, label) =>
    `<button class="btn ${cls}" data-act="${act}" data-id="${esc(a.id)}" title="${esc(WILL[act] || label)}"${job ? " disabled" : ""}>${label}</button>`;

  let acts;
  if (a.core) acts = a.launch ? btn("primary", "open", "פתח") : `<span class="idl">מוגן</span>`;
  else if (a.installed && a.enabled)
    acts = (a.launch ? btn("primary", "open", "פתח") : "") + btn("", "disable", "כבה")
      + (placeable().length ? btn("", "move", "העבר") : "") + btn("danger", "uninstall", "הסר");
  else if (a.archived)
    // Its data is still here, so the verb is restore, not install.
    acts = btn("primary", "unarchive", "שחזר") + btn("danger", "uninstall", "הסר");
  else if (a.installed)
    // Installed but switched off: it stays in My apps and the primary action is to turn it back
    // on. Offering "Install" here would be a lie — it is already installed. Its data is here whether
    // it runs or not, so it can be moved from this state too (the move switches it on for the read).
    acts = btn("primary", "install", "הפעל") + (placeable().length ? btn("", "move", "העבר") : "")
      + btn("", "archive", "לארכיון") + btn("danger", "uninstall", "הסר");
  else acts = btn("primary", "install", "התקן") + btn("ghost", "detail", "פרטים");

  return `<article class="card${job ? " working" : ""}" data-id="${esc(a.id)}">
    <div class="top">
      <div class="ic">${icon(a.icon)}</div>
      <div title="${esc(a.id)}"><div class="nm">${esc(a.name)}</div>
        <div class="idl">גרסה <bdi>${esc(a.version || "1.0.0")}</bdi></div></div>
    </div>
    <div class="desc">${esc(a.summary || "")}</div>
    <div class="row">${statusBadge(a)}${a.core ? '<span class="badge">ליבה</span>' : ""}</div>
    ${job ? progress(job) : ""}
    <div class="acts">${acts}</div>
  </article>`;
}

/* Measured progress: every line is something we actually observed, not a timed animation. */
function progress(job) {
  const steps = job.steps.map((s) => {
    const cls = s.state === "done" ? "ok" : s.state === "active" ? "on" : s.state === "fail" ? "bad" : "";
    const mark = s.state === "done" ? ic("check") : s.state === "fail" ? ic("x") : "";
    return `<li class="${cls}"><i>${mark}</i><span>${esc(s.label)}</span>${s.note ? `<em>${esc(s.note)}</em>` : ""}</li>`;
  }).join("");
  const bar = job.done ? "" : `<div class="bar"><i></i></div>`;
  const done = job.done ? `<div class="donerow">${ic("check")} ${esc(job.done)}</div>` : "";
  return `<div class="prog">${bar}<ul>${steps}</ul>${done}</div>`;
}

/* ── detail drawer ────────────────────────────────────────────────────────── */
function openDetail(a) {
  const pills = (arr) => (arr && arr.length ? arr.map((v) => `<span class="pill">${esc(v)}</span>`).join("") : `<span class="idl">—</span>`);
  const purge = a.on_uninstall === "purge";
  $("#drawer").innerHTML = `
    <div class="dhead">
      <div class="ic">${icon(a.icon)}</div>
      <div><div class="nm" id="dnm">${esc(a.name)}</div>
        <div class="idl">${esc(a.name_en || "")} · ${esc(a.id)} · v${esc(a.version || "1.0.0")}</div></div>
      <button class="x" data-act="close" aria-label="סגור" title="סגירה">${ic("x")}</button>
    </div>
    <div class="dbody">
      <p class="desc">${esc(a.summary || "")}</p>
      <div class="dsect">מצב</div>
      <div class="kv"><span>מותקנת</span><span>${a.installed ? "כן" : "לא"}</span></div>
      <div class="kv"><span>שירותים פועלים</span><span>${a.running ?? 0}/${a.total ?? 0}</span></div>
      <div class="kv"><span>שכבה</span><span>${a.layer ?? "?"}${a.core ? " · ליבה" : ""}</span></div>
      <div class="kv"><span>סוג</span><span><code>${esc(a.kind || "service")}</code></span></div>
      ${(a.conditions || []).length ? `<div class="dsect">תנאים</div>
      <div class="conds">${a.conditions.map((c) => `
        <div class="cond c-${c.status}">
          <span class="ct">${esc(COND_HE[c.type] || c.type)}</span>
          <span class="cs">${esc(STATUS_HE[c.status] || c.status)}</span>
          <span class="cr">${esc(REASON_HE[c.reason] || c.reason)}${c.message ? " · " + esc(c.message) : ""}</span>
        </div>`).join("")}</div>
      <div class="kv"><span>נצפה מול דור</span><span>${esc(String(a.conditions[0].observedGeneration ?? "—"))}</span></div>` : ""}
      <div class="dsect">שירותים</div>${pills(a.services)}
      <div class="dsect">אחסון</div>${pills(a.volumes)}
      <div class="dsect">בהסרה</div>
      ${purge ? `<div class="warnbox">הסרה תמחק גם את נתוני האפליקציה (<code>on_uninstall: purge</code>).</div>`
              : `<div class="kv"><span>הנתונים נשמרים</span><code>on_uninstall: keep</code></div>`}
    </div>`;
  $("#scrim").classList.add("on"); $("#drawer").classList.add("on");
}
const closeDetail = () => { $("#scrim").classList.remove("on"); $("#drawer").classList.remove("on"); };

/* (a yes/no and a notice are the office's own — `binaAsk` / `binaTell`, the copied block at the top:
   never a browser dialog, and no sheet or snackbar of this screen's own) */

function notifyModulesChanged() {
  if (!(window.parent && window.parent !== window)) return;
  try { window.parent.postMessage({ type: "platform:modules-changed" }, location.origin); } catch {}
}

/* ── actions ──────────────────────────────────────────────────────────────── */
const STEPS = {
  install: [{ k: "svc", label: "מפעיל שירותים" }, { k: "bp", label: "מייבא אוטומציות" }],
  disable: [{ k: "svc", label: "עוצר שירותים" }, { k: "bp", label: "מסיר אוטומציות" }],
  archive: [{ k: "svc", label: "מסיר מכולות ותמונות" }, { k: "bp", label: "מסיר אוטומציות" }],
  unarchive: [{ k: "svc", label: "מוריד ומפעיל מחדש" }, { k: "bp", label: "מייבא אוטומציות" }],
  uninstall: [{ k: "svc", label: "מסיר מכולות" }, { k: "bp", label: "מסיר אוטומציות" }],
  move: [{ k: "svc", label: "מעביר את האפליקציה" }, { k: "bp", label: "מכבה כאן" }],
};

/* A bring-up is a job: an image nobody has built yet, a database's first start, the app's own
   bootstrap. The call answers 202 with the step it is at while that goes on, and `<app>/job` then
   answers what the call would have — so this follows it to the END and hands back that answer.
   `base` is an app's API root on ANY office (this one's `api/apps/<id>`, or a linked office's
   through the console's door), which is what lets one function place an app anywhere. */
const BRINGUP_HE = {
  queued: "ממתין לתורו", state: "מעדכן את ההגדרות", prepare: "מכין את האפליקציה",
  containers: "בונה ומפעיל שירותים", health: "ממתין שהשירותים יענו",
  signin: "מחבר את הכתובת שלה לכניסה", onboard: "מגדיר את האפליקציה", automations: "מייבא אוטומציות",
  restore: "משחזר את הנתונים שהגיעו", export: "מייצא את הנתונים מכאן",
  place: "מתקין בלשכה השנייה ומשחזר שם את הנתונים", off: "מכבה כאן",
  wake: "מדליק כאן כדי לקרוא את הנתונים",
};
async function untilDone(base, verb, init, onStep) {
  let r = await fetch(`${base}/${verb}`, init).catch(binaNoAnswer);
  while (r.status === 202) {
    const d = await r.json().catch(() => ({}));
    if (onStep) onStep(d.step || "");
    await new Promise((res) => setTimeout(res, 2000));
    r = await fetch(`${base}/job`, { cache: "no-store" }).catch(binaNoAnswer);
  }
  return r;
}

/* ── WHERE an app runs: this office, or a linked one ─────────────────────────────────────────────
   A linked office that GIVES its app-management is an office this one may place apps on, and the way
   to it is the door the console already has for that tile (`/a/app-management.<office>/`). So there
   is no second lifecycle here: installing on another office is the same call to the same API, sent
   through that door — and an office that does not give its app-management simply is not offered. */
function placeable() {
  return REMOTE.offices.filter((o) => !o.off && o.apps.some((x) =>
    x.alias === "app-management" && x.tile && !x.off && !x.hidden));
}
const officeApi = (o, id) => `/a/app-management.${o.office}/api/apps/${encodeURIComponent(id)}`;

/* The question itself. Resolves to `null` (this office), an office, or `undefined` (cancelled).
   Each linked office ANSWERS FOR ITSELF before it can be chosen: whether the app is in its catalog
   and whether it is already there — a choice that is offered and then refused is a wasted click. */
function whereSheet({ a, title, body, here, verb }) {
  const offices = placeable();
  const row = (key, ic, name, sub, on, mark) => `
    <div class="peers-row" data-row="${esc(key)}">
      <span class="peers-ic${key ? " is-remote" : ""}"${officeHue(mark)}>${icon(ic)}</span>
      <span class="peers-nm">${esc(name)}<span class="idl" data-sub>${esc(sub)}</span><span class="idl room" data-room></span></span>
      <button class="btn${on && (here ? !key : true) ? " primary" : ""}" data-w="${esc(key)}"${on ? "" : " disabled"}
        title="${esc(verb)} — ${esc(name)}">${esc(verb)}</button>
    </div>`;
  return new Promise((resolve) => {
    $("#sheet").innerHTML = `
      <div class="sheetcard" role="dialog" aria-modal="true">
        <h2>${esc(title)}</h2><p>${body}</p>
        <div class="peers-list where">
          ${here ? row("", "monitor", "הלשכה הזאת", "המחשב שהקונסול הזה רץ עליו", true) : ""}
          ${offices.map((o) => row(o.office, officeAnimal(o, "server"), o.label, "בודק מול הלשכה…", false, o)).join("")}
        </div>
        <div class="sheetacts"><button class="btn ghost" data-x="0">ביטול</button></div>
      </div>`;
    $("#sheet").classList.add("on");
    let open = true;
    const done = (v) => { open = false; $("#sheet").classList.remove("on"); $("#sheet").innerHTML = ""; resolve(v); };
    $("#sheet").onclick = (e) => {
      const w = e.target.closest("[data-w]");
      if (w && !w.disabled) return done(w.dataset.w ? offices.find((o) => o.office === w.dataset.w) : null);
      if (e.target.closest("[data-x]") || e.target.id === "sheet") done(undefined);
    };
    // ROOM, in each office's own words — its control plane measures its own machine and answers with
    // numbers. A linked office that says it has none is not offered (the move would be refused there
    // anyway); THIS office is the owner's call, so it is warned and stays his to choose. An office
    // that cannot answer the question is simply not judged.
    const size = (mb) => (mb >= 1024 ? `${(mb / 1024).toFixed(1)}GB` : `${Math.round(mb)}MB`);
    const room = async (key, base) => {
      let d = null;
      try {
        const r = await fetch(`${base}/room`, { cache: "no-store" });
        if (r.ok) d = await r.json();
      } catch { /* not judged */ }
      const el = open && [...$("#sheet").querySelectorAll("[data-row]")].find((x) => x.dataset.row === key);
      if (!el || !d || typeof d.ok !== "boolean") return;
      const free = (d.have || {}).memory_available_mb;
      const line = el.querySelector("[data-room]");
      line.textContent = !d.ok ? (d.summary || "אין מקום")
        : d.undeclared ? d.summary : free ? `יש מקום — ${size(free)} זיכרון פנויים` : "יש מקום";
      line.classList.toggle("warn", !d.ok);
      line.title = "מה שהלשכה עצמה מדדה עכשיו: זיכרון פנוי, עומס ומקום בדיסק מול מה שהאפליקציה מצהירה";
      if (!d.ok && key) { const b = el.querySelector("[data-w]"); b.disabled = true; b.classList.remove("primary"); }
    };
    if (here) room("", `api/apps/${encodeURIComponent(a.id)}`);
    offices.forEach(async (o) => {
      let sub = "הלשכה לא ענתה", on = false;
      try {
        const r = await fetch(`/a/app-management.${o.office}/api/apps`, { cache: "no-store" });
        const d = await r.json().catch(() => ({}));
        const theirs = (d.apps || []).find((x) => x.id === a.id);
        if (!r.ok) sub = d.message || d.error || "הלשכה לא ענתה";
        else if (!theirs) sub = "האפליקציה אינה בקטלוג של הלשכה הזאת";
        else if (theirs.installed || theirs.enabled) sub = "כבר מותקנת שם";
        else { sub = "אינה מותקנת שם"; on = true; }
      } catch { /* said above */ }
      const el = open && [...$("#sheet").querySelectorAll("[data-row]")].find((x) => x.dataset.row === o.office);
      if (!el) return;
      el.querySelector("[data-sub]").textContent = sub;
      const b = el.querySelector("[data-w]");
      b.disabled = !on;
      b.classList.toggle("primary", on && !here);
      if (on) room(o.office, officeApi(o, a.id));
    });
  });
}

async function act(id, action) {
  const a = STATE.apps.find((x) => x.id === id);
  if (!a) return;
  if (action === "open") return openApp(a);
  if (action === "detail") return openDetail(a);

  // WHERE. Installing asks only when there is another office to install on; a move always names one.
  let where = null;
  if (action === "install" && !a.installed && !a.archived && placeable().length) {
    where = await whereSheet({
      a, here: true, verb: "התקן", title: `איפה להתקין את ${a.name}?`,
      body: "האפליקציה תותקן ותופעל בלשכה שתבחר. מלשכה מקושרת היא נפתחת מכאן כמו כל אפליקציה אחרת.",
    });
    if (where === undefined) return;
  }
  // …and when there was nothing to choose, the office is still asked whether it has ROOM — the
  // sheet above shows that answer per office; without the sheet nobody saw it. A "no" is the
  // owner's call, with the office's own sentence and numbers in front of him; a "yes" asks nothing.
  if (action === "install" && where === null && !placeable().length) {
    const d = await fetch(`api/apps/${encodeURIComponent(id)}/room`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null)).catch(() => null);
    if (d && d.ok === false) {
      const ok = await binaAsk({
        title: `להפעיל את ${a.name} בכל זאת?`, ok: "הפעל בכל זאת",
        body: "הלשכה מדדה את המכונה שלה עכשיו, ולפי מה שמצאה אין לה מקום.",
        facts: d.summary ? [["המדידה", d.summary]] : [],
      });
      if (!ok) return;
    }
  }
  // The mover reads an app's data from its RUNNING stores, so an app that is not running here is
  // switched on for the read — said in the sheet before it is asked for, and asked for in the call.
  const asleep = a.total > 0 ? a.running !== a.total : !a.enabled;
  if (action === "move") {
    const n = (a.volumes || []).length;
    where = await whereSheet({
      a, here: false, verb: "העבר", title: `לאן להעביר את ${a.name}?`,
      body: `האפליקציה תותקן בלשכה שתבחר, <b>הנתונים שלה יועברו אליה</b>${n ? ` (${n} אחסונים)` : ""}
        ונבדקים שם מול מה שיצא מכאן, ורק אז היא תכובה כאן. הנתונים שכאן נשמרים עד שתסיר אותה.${
        asleep ? " האפליקציה אינה פועלת כאן כרגע, ולכן <b>תודלק לזמן קריאת הנתונים</b> ותכובה שוב." : ""}`,
    });
    if (!where) return;
  }

  if (action === "archive") {
    const ok = await binaAsk({
      title: `להעביר את ${a.name} לארכיון?`, ok: "העבר לארכיון",
      body: "המכולות והתמונות יוסרו כדי לפנות מקום בדיסק. הנתונים והאפליקציה יישמרו, וניתן לשחזר בכל רגע.",
      facts: a.volumes && a.volumes.length ? [["נשמר", a.volumes.join(", ")]] : [],
    });
    if (!ok) return;
  }
  if (action === "uninstall") {
    const purge = a.on_uninstall === "purge";
    // what the manifest declares about its data is a FACT of the question (a token, under a Hebrew key)
    const ok = await binaAsk({
      title: `להסיר את ${a.name}?`, danger: true, ok: "הסר",
      body: purge ? "המכולות והנתונים של האפליקציה יימחקו." : "המכולות יוסרו. הנתונים יישמרו, ותוכל להתקין מחדש.",
      facts: [["בהסרה", `on_uninstall: ${purge ? "purge" : "keep"}`]]
        .concat(a.volumes && a.volumes.length ? [[purge ? "יימחק" : "נשמר", a.volumes.join(", ")]] : []),
    });
    if (!ok) return;
  }

  const job = { action, steps: STEPS[action].map((s, i) => ({ ...s, state: i === 0 ? "active" : "" })) };
  // on another office the local container counts say nothing: the job's own step is the report
  if (where) job.following = true;
  STATE.jobs.set(id, job); render();

  // Poll WHILE the request is in flight so the card reports live truth, not a fake animation.
  const watch = setInterval(oneAtATime(async () => {
    try {
      if (where) return;
      const d = await (await fetch("api/apps")).json();
      const cur = (d.apps || []).find((x) => x.id === id);
      if (!cur) return;
      const s = job.steps[0];
      if (cur.total) s.note = `${cur.running}/${cur.total} שירותים`;
      const settled = action === "install" ? cur.running === cur.total && cur.total > 0 : cur.running === 0;
      if (settled && s.state === "active" && !job.following) { s.state = "done"; job.steps[1].state = "active"; }
      STATE.apps = d.apps; STATE.counts = d.counts || STATE.counts;
      render();
    } catch { /* transient during restarts — the final response is the source of truth */ }
  }), 1000);

  const path = { install: "enable", disable: "disable", uninstall: "uninstall",
                 archive: "archive", unarchive: "unarchive", move: "move" }[action];
  // an install on a linked office is the same call, to that office's own API; a move is asked of
  // THIS office, which is the one that holds the app and its data
  const base = where && action === "install" ? officeApi(where, id) : `api/apps/${encodeURIComponent(id)}`;
  const body = action === "uninstall" ? { purge: a.on_uninstall === "purge" }
    : action === "move" ? { to: where.office, wake: asleep } : {};
  try {
    const r = await untilDone(base, path, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }, (step) => {
      // the job names the step it is at, so the card says THAT rather than guessing from counts
      job.following = true;
      const [first, last] = job.steps;
      if (step === "automations" || step === "off") { first.state = "done"; last.state = "active"; }
      else first.label = BRINGUP_HE[step] || first.label;
      render();
    });
    const d = await r.json().catch(() => ({}));
    // An app another enabled app REQUIRES (drive needs the object store) is not taken from under
    // it: the office refuses to archive, remove or move it, and a switch-off leaves it running.
    // Said here in the owner's words, with the apps' names — not the engine's sentence.
    const nameOf = (x) => (STATE.apps.find((y) => y.id === x) || {}).name || x;
    const needs = (d.required_by || []).map(nameOf);
    if (!r.ok) throw new Error(needs.length
      ? `היא נדרשת ע״י ${needs.join(", ")} — כבה או העבר אותן קודם`
      : d.error || (d.create_errors || [])[0] || binaSaid(r.status));

    job.steps[0].state = "done";
    const bp = action === "move" ? (d.here || {}).blueprint : d.blueprint;
    const last = job.steps[1];
    if (!bp) { last.state = "done"; last.note = "אין אוטומציות"; }
    else if (bp.ok) { last.state = "done"; last.note = bp.detail ? String(bp.detail).slice(0, 90) : ""; }
    else { last.state = "fail"; last.note = String(bp.detail || "").slice(0, 90); }
    render();

    const verb = { install: where ? `הותקנה בלשכת ${where.label}` : "הותקנה", disable: "כובתה",
                   uninstall: "הוסרה", archive: "הועברה לארכיון (הנתונים נשמרו)", unarchive: "שוחזרה",
                   move: where ? `הועברה ללשכת ${where.label} — הנתונים שכאן נשמרו` : "" }[action];
    if (action === "disable" && needs.length) {
      binaTell(`${a.name} כובתה ברשימה שלך, אך ממשיכה לרוץ — ${needs.join(", ")} צריכה אותה`, "warn", 9000);
    } else if (bp && bp.ok === false) {
      // An app can start fine and still fail to import its workflows. Swallowing that is how
      // "installed" stops meaning anything, so it is reported as a distinct, non-fatal warning.
      binaTell(`${a.name} ${verb}, אך ייבוא האוטומציות נכשל — ${bp.detail || "שגיאה"}`, "warn", 9000);
    } else binaTell(`${a.name} ${verb} בהצלחה`, "ok");
  } catch (e) {
    job.steps.forEach((s) => { if (s.state === "active") s.state = "fail"; });
    render();
    binaTell(`הפעולה על ${a.name} נכשלה: ${e.message}`, "bad", 9000);
  } finally {
    clearInterval(watch);
    // Hold the finished job on screen so the outcome is READ before the card moves tab. An
    // uninstall that silently teleports the card to the store gives no confirmation that it
    // actually completed, so it lingers longer and with an explicit final line.
    const linger = action === "uninstall" ? 2200 : 900;
    if (action === "uninstall" && job.steps.every((x) => x.state !== "fail")) {
      job.done = "האפליקציה הוסרה";
      render();
    }
    setTimeout(() => {
      STATE.jobs.delete(id);
      notifyModulesChanged();
      load();
      // the linked office's tiles changed too: read them again rather than in twenty seconds
      if (where) { REMOTE.at = 0; REMOTE.linkAt = 0; loadRemote().then(render).catch(() => {}); }
    }, linger);
  }
}

/* Open an app INSIDE the console shell, not in a new tab.
 *
 * This screen normally runs embedded at console/#/m/apps, so "open" must route the SHELL to the
 * app's module (#/m/<module>) — the console then frames it with the menu still visible, which is
 * the product. window.open() threw the user out of the shell into a bare, unframed host and lost
 * the navigation entirely.
 *
 * An app whose module is not embeddable (an external UI on its own host) still opens in a tab,
 * because the shell cannot frame it — that is a property of the app, declared in its manifest.
 * Standalone (not embedded) we just navigate normally.
 *
 * Except in the console's desktop mode (console/static/desktop.js): there every app is a window,
 * and an external UI opens as a window on its own host, with a way out to a tab in its title bar.
 */
function openApp(a) {
  const l = a.launch;
  if (!l) return;
  const embedded = window.parent && window.parent !== window;
  if (l.embed && l.module) {
    if (embedded) {
      try { window.parent.location.hash = "#/m/" + l.module; return; } catch { /* cross-origin */ }
    } else { location.href = "/#/m/" + l.module; return; }
  }
  try {
    const desk = embedded && window.parent.BinaDesktop;
    if (desk && desk.isOn() && desk.openExternal &&
        desk.openExternal({ id: a.id, name: a.name, url: l.url, icon: a.icon })) return;
  } catch { /* cross-origin parent: fall through to a tab */ }
  window.open(l.url, "_blank", "noopener");
}

/* ── install by reference (signed catalog / URL / file) ───────────────────────
 *
 * Two round trips, and the split is the security property, not an implementation detail:
 *   preview  fetches, verifies the hash against the signed index, validates the manifest against
 *            the live catalog (id / route host / console tile conflicts) and STAGES the bytes.
 *   install  completes from those SAME staged bytes.
 * Approving a disclosure computed from one download and then installing a fresh one would be a
 * TOCTOU hole, so the server hands back a token instead of re-fetching.
 */
const LVL = { critical: "crit", warn: "warn", info: "" };
const GLYPH = { critical: "error", warn: "alert", info: "info" };
/* The disclosure's sentences are the catalog's, and English: they are computed with the signed
   index. This is what the owner reads before he lets an app in, so the screen says them in its own
   language — by the power's id — and takes what varies (a path, a port, a count) from the sentence.
   A power nobody translated is shown as the catalog wrote it; the original is always the tooltip. */
const powerHe = (p) => {
  const said = String(p.text || ""), what = `<bdi>${esc(said.split(": ").slice(1).join(": "))}</bdi>`;
  return ({
    "docker-socket": "מקבלת את שקע ה־Docker — שליטה מלאה במכונה כולה, כולל כל אפליקציה אחרת והנתונים שלה.",
    privileged: "רצה כמכולה עם הרשאות מלאות — יכולה לצאת אל המכונה עצמה.",
    "host-path": `מקבלת תיקייה מהמכונה: ${what}`,
    "host-port": `פותחת פורט במכונה: ${what}`,
    "no-auth": "פותחת כתובת בלי כניסה אחת (SSO) לפניה.",
    automations: `מייבאת ${(said.match(/\d+/) || ["?"])[0]} תהליכי אוטומציה אל n8n המשותף בהתקנה, ומסירה אותם בכיבוי.`,
  })[p.id] || esc(said);
};
const KIND_HE = { password: "סיסמה", "text-secret": "סוד", token: "אסימון", "app-password": "סיסמת אפליקציה",
                  "oauth-client": "OAuth", "oauth-grant": "OAuth", "qr-session": "QR", "sa-key": "חשבון שירות",
                  cert: "תעודה", config: "תצורה", derived: "נגזר" };

function provBanner(p) {
  if (!p) return "";
  const cls = p.verified ? "ok" : "no";
  const head = p.verified ? "מקור מאומת" : "מקור לא מאומת";
  const body = p.verified
    ? esc(p.how || "")
    : `לא נמצאה חתימה עבור הקובץ הזה. ${esc(p.how || "")} — אין דבר שמעיד מי יצר אותו.`;
  const sha = p.artifact_sha256 ? `<div><code>sha256:${esc(p.artifact_sha256)}</code></div>` : "";
  return `<div class="prov ${cls}"><div>${ic(p.verified ? "lock" : "alert")}</div>
    <div><b>${head}</b><div>${body}</div>${sha}</div></div>`;
}

/* The disclosure. Order is the finding, not a layout choice: credentials first, because every
   other line on this list is reversible and a secret handed to an app is not. */
function disclosureSheet(pre) {
  const d = pre.disclosure || {};
  const t = d.title || {};
  const name = t.he || t.en || d.id;
  const sect = (label, html) => `<div class="dsect">${esc(label)}</div>${html}`;
  const pills = (arr) => (arr && arr.length
    ? arr.map((v) => `<span class="pill">${esc(v)}</span>`).join("")
    : `<div class="none">—</div>`);

  const creds = (d.credentials || []).length
    ? `<ul class="creds">${d.credentials.map((c) =>
        `<li>${ic("key")}<span>${esc(c.title_he || c.title || c.id)}</span>
          <em title="${esc(c.kind)}">${esc(KIND_HE[c.kind] || c.kind)}${c.required ? "" : " · לא חובה"}</em></li>`).join("")}</ul>`
    : `<div class="none">אינה מבקשת אף סוד. </div>`;

  const powers = (d.powers || []).length
    ? `<ul class="risk">${d.powers.map((p) =>
        `<li class="${LVL[p.level] || ""}"><span class="g">${ic(GLYPH[p.level] || "info")}</span>
          <span title="${esc(p.text)}">${powerHe(p)}</span></li>`).join("")}</ul>`
    : `<div class="none">אין הרשאות מיוחדות מעבר לרשת הפנימית.</div>`;

  const pulls = (d.pulls_in || []).length
    ? `<ul class="risk">${d.pulls_in.map((p) =>
        `<li><span class="g">${ic("box")}</span><span>${esc(p.title)} <code>${esc(p.id)}</code> —
          תותקן גם היא, כי היא מספקת יכולת שהאפליקציה דורשת.</span></li>`).join("")}</ul>`
    : `<div class="none">לא נגררת אף אפליקציה נוספת.</div>`;

  const uses = (d.capabilities_used || []).length
    // a capability's name is an identifier (no manifest gives it a Hebrew one yet) — shown as the
    // token it is; whether the app cannot run without it is said in words
    ? d.capabilities_used.map((u) => `<span class="pill" title="${esc(u.capability)} (${esc(u.strength || "requires")})"><bdi>${
        esc(u.capability)}</bdi> · ${u.strength === "wants" ? "רשות" : "חובה"}</span>`).join("")
    : `<div class="none">אינה משתמשת ביכולות של אפליקציות אחרות.</div>`;

  const hosts = (d.hosts || []).length
    ? `<ul class="risk">${d.hosts.map((h) =>
        `<li><span class="g">${ic("globe")}</span><span><code>${esc(h.url)}</code> → פורט ${esc(h.port)} ·
          כניסה: ${h.auth === "sso" ? "מאחורי SSO" : esc(h.auth)}${h.tile ? " · מוסיפה אריח לתפריט" : ""}</span></li>`)
        .join("")}</ul>`
    : `<div class="none">אינה תופסת כתובת.</div>`;

  const r = d.resources || {};
  const auto = d.automations || {};
  const a = d.artifact || pre.provenance || {};
  const refusals = (pre.refusals || []).length
    ? `<div class="prov bad"><div>${ic("error")}</div><div><b>ההתקנה נדחתה</b><ul style="margin:6px 0 0;padding-inline-start:18px">
        ${pre.refusals.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div></div>`
    : "";

  return new Promise((resolve) => {
    $("#sheet").innerHTML = `
      <div class="sheetcard wide" role="alertdialog" aria-modal="true">
        <div class="dischead">
          <h2 style="margin:0">${esc(name)} <span class="idl">${esc(pre.id)} · v${esc(pre.version || "?")}</span></h2>
          <p style="margin:6px 0 0">${esc((d.summary || {}).he || (d.summary || {}).en || "")}</p>
          ${provBanner(pre.provenance)}
          ${refusals}
        </div>
        <div class="discbody">
          ${sect(`סודות שהאפליקציה תחזיק (${(d.credentials || []).length})`, creds)}
          ${sect("מה היא תוכל לעשות במכונה", powers)}
          ${sect("מה עוד יותקן", pulls)}
          ${sect("יכולות שהיא צורכת", uses)}
          ${sect("כתובות ופורטים", hosts)}
          ${sect("אחסון", pills(d.volumes))}
          ${sect("עלות", `<div class="kv"><span>מעבד</span><span>${esc(r.cpus ?? "—")}</span></div>
            <div class="kv"><span>זיכרון</span><span>${esc(r.memory ?? "—")}</span></div>
            <div class="kv"><span>אימג'ים</span><span>${esc((d.images || []).join(", ") || "—")}</span></div>
            <div class="kv"><span>אוטומציות</span><span>${auto.n8n ? `${auto.workflows} תהליכי n8n` : "—"}</span></div>
            ${a.size ? `<div class="kv"><span>גודל החבילה</span><span>${esc(a.size)} בתים</span></div>` : ""}`)}
        </div>
        <div class="discacts">
          <button class="btn ghost" data-x="0">ביטול</button>
          <button class="btn primary" data-x="1"${pre.installable ? "" : " disabled"}>התקן</button>
        </div>
      </div>`;
    $("#sheet").classList.add("on");
    const done = (v) => { $("#sheet").classList.remove("on"); $("#sheet").innerHTML = ""; resolve(v); };
    $("#sheet").onclick = (e) => {
      const b = e.target.closest("[data-x]");
      if (b) return done(b.dataset.x === "1");
      if (e.target.id === "sheet") done(false);
    };
  });
}

let INSTALL_FILE = null;

function instNote(html) { $("#instnote").innerHTML = html; }

async function previewAndInstall() {
  const go = $("#instgo");
  const ref = $("#instref").value.trim();
  if (!ref && !INSTALL_FILE) {
    instNote(`<b>הדביקו כתובת</b> לחבילת אפליקציה (<code>.zip</code>/<code>.tar.gz</code>),
      מזהה אפליקציה מהקטלוג החתום, או בחרו קובץ מהמחשב.`);
    return;
  }
  go.classList.add("busy"); go.disabled = true;
  instNote("בודק את החבילה — הורדה, אימות חתימה וגיבוב, ואימות המניפסט מול הקטלוג…");
  let pre;
  try {
    let r;
    if (INSTALL_FILE) {
      const fd = new FormData();
      fd.append("file", INSTALL_FILE);
      r = await fetch("api/catalog/preview", { method: "POST", body: fd }).catch(binaNoAnswer);
    } else {
      r = await fetch("api/catalog/preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ref }),
      }).catch(binaNoAnswer);
    }
    pre = await r.json().catch(() => null);
    if (!r.ok || !pre) throw new Error((pre && pre.error) || binaSaid(r.status));
  } catch (e) {
    instNote(`<b style="color:var(--red)">נדחה:</b> ${esc(e.message)}`);
    binaTell(`הבדיקה נכשלה: ${e.message}`, "bad", 9000);
    return;
  } finally { go.classList.remove("busy"); go.disabled = false; }

  const ok = await disclosureSheet(pre);
  if (!ok) { instNote("בוטל — לא נכתב דבר."); return; }

  instNote(`מתקין את <b>${esc(pre.id)}</b>…`);
  try {
    let r = await fetch("api/catalog/install", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: pre.token }),
    }).catch(binaNoAnswer);
    let d = await r.json().catch(() => null);
    if (!d) throw new Error(binaSaid(r.status));
    if (r.status === 202) {                 // placed, and still being brought up: follow it to the end
      r = await untilDone(`api/apps/${encodeURIComponent(pre.id)}`, "job", { cache: "no-store" },
        (step) => instNote(`מתקין את <b>${esc(pre.id)}</b> — ${esc(BRINGUP_HE[step] || "")}…`));
      d = Object.assign(d, await r.json().catch(() => ({})));
    }
    if (!r.ok) throw new Error(d.error || (d.create_errors || [])[0] || binaSaid(r.status));
    instNote(`<b>${esc(pre.id)}</b> הותקנה — ${esc(d.installed_from || "")}`);
    binaTell(`${pre.id} הותקנה והופעלה (${d.running ?? 0}/${d.total ?? 0} שירותים)`, "ok", 8000);
    $("#instref").value = ""; INSTALL_FILE = null; $("#instfile").value = "";
    STATE.tab = "installed";
    notifyModulesChanged();
    await load();
  } catch (e) {
    instNote(`<b style="color:var(--red)">ההתקנה נכשלה:</b> ${esc(e.message)}`);
    binaTell(`ההתקנה נכשלה: ${e.message}`, "bad", 9000);
  }
}

/* What this deployment's own signed catalog offers — so "install by id" is a real affordance and
   the store can say, honestly, whether it is reading a verified index at all. */
async function loadCatalogMeta() {
  try {
    const d = await (await fetch("api/catalog")).json();
    if (d.error) {
      $("#instsub").textContent = "אין קטלוג חתום מקומי — ניתן להתקין מכתובת או מקובץ. " +
        "(ליצירת קטלוג: bbox catalog build)";
      return;
    }
    const ids = (d.entries || []).map((e) => e.id);
    $("#instsub").innerHTML = `קטלוג חתום: <b>${esc((d.meta || {}).signature || "")}</b> · ` +
      `${ids.length} אפליקציות: ${esc(ids.join(", "))}`;
  } catch { /* the store still works without a local catalog */ }
}

/* ── data ─────────────────────────────────────────────────────────────────── */
/* A failed read is never "no apps". An error answer (the console's 502 when this service is slow,
   a restart in progress) used to be parsed as a catalog with no `apps` key and rendered as
   "0 אפליקציות · אין כאן אפליקציות" — the one wrong answer this screen must never show. Now an error
   keeps the last list on screen and says what happened; with nothing loaded yet it says so plainly. */
/* A tick that finds its last read still OUT is dropped. The list is asked for every 5 s — every
   second while a job runs — and an answer can take longer than that: on 2026-10-09 it took 5 to 13
   seconds on the HP office, so two or three reads were in flight for as long as the screen stood
   open (one more every second during an install), each of them slowing the next. */
const oneAtATime = (fn) => {
  let out = false;
  return async () => { if (out) return; out = true; try { await fn(); } finally { out = false; } };
};
async function load() {
  let r, d;
  r = await fetch("api/apps").catch(binaNoAnswer);
  d = (await r.json().catch(() => null)) || {};
  if (!r.ok || !Array.isArray(d.apps)) {
    return loadFailed(d.message || d.error ? String(d.message || d.error).slice(0, 160) : binaSaid(r.status));
  }
  STATE.apps = d.apps; STATE.counts = d.counts || {}; STATE.project = d.project || "";
  STATE.loadError = null;
  STATE.loaded = true;
  render();
}
function loadFailed(why) {
  STATE.loadError = why;
  if (STATE.apps.length) {
    render();
    $("#note").textContent = `הרענון האחרון נכשל — מוצג המצב הקודם · ${why}`;
    return;
  }
  $("#sub").textContent = "טוען את רשימת האפליקציות…";
  $("#grid").innerHTML = `<div class="empty">רשימת האפליקציות עוד לא נטענה — שירות ניהול האפליקציות איטי או מופעל מחדש.
    <br><span style="font-size:12px">${esc(why)}</span></div>`;
}

document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-act]");
  if (t) {
    if (t.dataset.act === "close") return closeDetail();
    if (t.dataset.act === "connect") return window.open("/a/dgo-extend/connect", "_blank", "noopener");
    if (t.dataset.act === "openRemote") return openRemote(t.dataset.remote);
    return act(t.dataset.id, t.dataset.act);
  }
  const chip = e.target.closest("[data-office]");
  if (chip && chip.classList.contains("chip")) { STATE.office = chip.dataset.office; return render(); }
  if (e.target.id === "scrim") return closeDetail();
  const c = e.target.closest(".card");
  // A remote card's detail drawer is not this screen's business: there is no manifest here, no
  // lifecycle and no conditions to report — the app is not installed on this machine.
  if (c && !e.target.closest(".acts") && !c.dataset.remote) {
    const a = STATE.apps.find((x) => x.id === c.dataset.id);
    if (a) openDetail(a);
  }
});
// The show/hide switch writes through dgo-extend (serve.exclude) and REVERTS when refused.
document.addEventListener("change", (e) => {
  const box = e.target.closest("input[data-show]");
  if (!box) return;
  setRemoteHidden(box.dataset.office, box.dataset.alias, !box.checked, box);
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDetail(); });

$("#instpick").addEventListener("click", () => $("#instfile").click());
$("#instfile").addEventListener("change", (e) => {
  INSTALL_FILE = e.target.files[0] || null;
  if (INSTALL_FILE) {
    $("#instref").value = "";
    instNote(`נבחר קובץ: <b>${esc(INSTALL_FILE.name)}</b> (${INSTALL_FILE.size} בתים). ` +
      `קובץ שהועלה אינו חתום — אלא אם הגיבוב שלו מופיע בקטלוג החתום, וזה ייבדק בשלב הבא.`);
  }
});
$("#instref").addEventListener("input", () => {
  if ($("#instref").value.trim()) { INSTALL_FILE = null; $("#instfile").value = ""; }
});
$("#instgo").addEventListener("click", previewAndInstall);
$("#instref").addEventListener("keydown", (e) => { if (e.key === "Enter") previewAndInstall(); });

loadCatalogMeta();
render();
// The remote half (linked offices + their apps) is loaded BESIDE the local catalog and never blocks
// it: an office with no dgo-extend installed, or one that is slow, must not keep "my apps" spinning.
loadRemote().then(render).catch(() => {});
load();
setInterval(oneAtATime(async () => { if (!STATE.jobs.size && !$("#drawer").classList.contains("on")) await load(); }), 5000);
setInterval(() => { loadRemote().then(render).catch(() => {}); }, 20000);
