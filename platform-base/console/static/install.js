/* install.js — the office's first-run wizard (core-004, DGO-480; the fleet step is flt-001).
 *
 * app.py serves install.html instead of the shell while the control plane's /api/office carries no
 * installed_at. Five steps: welcome → the terms (one checkbox, nothing moves without it) → the
 * office's name, animal and hue (what a linked office shows beside this office's apps) → the apps to
 * install, where ONLY the AI app is checked and NOTHING is installed until «התקנה» → the install,
 * followed app by app, then the office. Everything goes through the console's own origin
 * (/a/app-management/…): one PUT of the office record, one enable per chosen app — the same enable
 * the apps screen does, so dependencies (INDOX brings n8n) are the compiler's, not this page's.
 *
 * It names no colour: the hue is a palette family NAME, drawn as var(--<hue>) (G27/G82), and the
 * icons are the one set's copy below (G27 keeps it byte-identical to bina-icons.js).
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

const API = "/a/app-management/api";
const TERMS_VERSION = "2026-10-09.1";
const AI_APP = "bina-ds";          // the one app checked by default: "get to work with AI very fast"
const ANIMALS = [["elephant", "פיל"], ["deer", "צבי"], ["eagle", "נשר"]];
const HUES = [["olive", "זית"], ["lime", "ליים"], ["sky", "שמיים"], ["plum", "שזיף"], ["violet", "סגול"], ["muted", "אפור"]];
const JOB_POLL_MS = 3000, JOB_MAX_MS = 15 * 60 * 1000;

const st = {
  step: 0, terms: false, termsAt: "", name: "", animal: "elephant", hue: "muted",
  apps: null, appsError: "", chosen: new Set(), installing: false, done: false, error: "", results: {},
};

const $ = (s) => document.querySelector(s);
const esc = (s) => (s == null ? "" : String(s)).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const utc = () => new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
function icon(name) {
  const inner = BINA_ICONS[name] || BINA_ICONS.app;
  return '<svg class="ic-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + inner + "</svg>";
}
// What a failed request is CALLED: the service's own sentence when it sent one, the status otherwise.
async function said(r) {
  const body = await r.json().catch(() => null);
  return (body && (body.error || body.message)) || binaSaid(r.status);
}

// ── the steps ────────────────────────────────────────────────────────────────────────────────────
const TERMS = `
<h3>1. מהי הלשכה הדיגיטלית</h3>
<p>הלשכה הדיגיטלית היא תוכנה שמותקנת על המחשב שלכם ומריצה אפליקציות עסקיות — מסמכים, דואר, אוטומציות וסוכן בינה מלאכותית — בתוך הלשכה שלכם, על המכונה שלכם.</p>
<h3>2. הנתונים שלכם</h3>
<p>הנתונים נשמרים במחשב שבו הלשכה מותקנת. הלשכה אינה מעבירה נתונים לשום מקום אלא כשאתם מחברים חשבון או שירות חיצוני בעצמכם (למשל חשבון דואר), ואז לפי תנאיו של אותו שירות.</p>
<h3>3. אפליקציות ורכיבים</h3>
<p>כל אפליקציה שתבחרו להתקין מורדת ומופעלת כפי שהיא. רכיבי קוד פתוח שהלשכה משתמשת בהם כפופים לרישיונותיהם. אתם אחראים למה שאתם מריצים בלשכה ולמי שאתם נותנים גישה אליה.</p>
<h3>4. עדכונים</h3>
<p>הלשכה עשויה לעדכן את עצמה ואת האפליקציות המותקנות כדי לתקן ולשפר. עדכון אינו משנה את הנתונים שלכם ואינו מתקין אפליקציה שלא בחרתם.</p>
<h3>5. אחריות</h3>
<p>התוכנה מסופקת כמות שהיא. אין אחריות לכך שתתאים לכל מטרה או שתפעל ללא הפרעה, ואין אחריות לנזק שנגרם מהשימוש בה, ככל שהדין מתיר זאת.</p>
<h3>6. פרטיות</h3>
<p>הלשכה אינה אוספת מידע עליכם ואינה שולחת מידע למפתחיה. יומני המערכת נשמרים במחשב שלכם בלבד.</p>
<p class="sub">גרסת התנאים: ${TERMS_VERSION}</p>`;

function view(step) {
  if (step === 0) return `
<h2>ברוכים הבאים ללשכה הדיגיטלית</h2>
<p>הלשכה מותקנת על המחשב הזה. בשלבים הבאים תאשרו את תנאי השימוש, תיתנו ללשכה שם וסימן, ותבחרו אילו אפליקציות להתקין.</p>
<p class="sub">שום דבר לא מותקן בלי בחירה שלכם. אפשר לשנות כל בחירה לפני לחיצה על «התקנה», ולהוסיף אפליקציות אחר כך ממסך האפליקציות.</p>`;
  if (step === 1) return `
<h2>תנאי שימוש</h2>
<div class="terms" id="terms">${TERMS}</div>
<label class="check"><input type="checkbox" id="accept" ${st.terms ? "checked" : ""}/> קראתי ואני מקבל/ת את תנאי השימוש</label>`;
  if (step === 2) return `
<h2>הלשכה הזאת</h2>
<p class="sub">כשכמה לשכות מקושרות, כל אפליקציה נושאת את הסימן של הלשכה שלה — חיה וצבע — כדי שיֵדעו ממבט אחד של מי היא.</p>
<div class="field"><label for="oname">שם הלשכה</label><input type="text" id="oname" maxlength="60" placeholder="למשל: המשרד בחיפה" value="${esc(st.name)}"/></div>
<div class="field"><label>חיה</label><div class="picks" id="animals">${ANIMALS.map(([id, he]) =>
    `<button type="button" class="pick" data-animal="${id}" aria-pressed="${st.animal === id}">${icon(id)}<span>${he}</span></button>`).join("")}</div></div>
<div class="field"><label>צבע</label><div class="picks" id="hues">${HUES.map(([id, he]) =>
    `<button type="button" class="pick" data-hue="${id}" aria-pressed="${st.hue === id}" style="--pick-hue:var(--${id})"><span class="swatch"></span><span>${he}</span></button>`).join("")}</div></div>
<div class="mark-row"><span class="mark" style="--pick-hue:var(--${st.hue})">${icon(st.animal)}</span><span class="sub">כך תיראה הלשכה אצל לשכה מקושרת</span></div>`;
  if (step === 3) return appsView();
  if (step === 4) return installView();
  return "";
}

function appsView() {
  if (st.appsError) return `<h2>אפליקציות</h2><p class="bad">${esc(st.appsError)}</p><button type="button" class="btn ghost sm" id="retryApps">נסו שוב</button>`;
  if (!st.apps) return `<h2>אפליקציות</h2><p class="sub">טוען את רשימת האפליקציות…</p>`;
  const rows = st.apps.map(a => {
    const had = a.installed || a.enabled;
    const on = had || st.chosen.has(a.id);
    return `<label class="app"><input type="checkbox" data-app="${esc(a.id)}" ${on ? "checked" : ""} ${had ? "disabled" : ""}/>` +
      `<span><span class="name">${icon(a.icon)}${esc(a.name)}${had ? ' <span class="pill ok">כבר מותקנת</span>' : ""}</span>` +
      `<span class="sum">${esc(a.summary)}</span></span></label>`;
  }).join("");
  return `<h2>אילו אפליקציות להתקין?</h2>
<p class="sub">מסומנת רק אפליקציית הבינה — כדי להתחיל לעבוד עם AI מהר. השאר לבחירתכם, עכשיו או אחר כך. תלויות (למשל אוטומציות למסמכים נכנסים) מגיעות מעצמן.</p>
<div class="apps">${rows || '<p class="sub">אין אפליקציות להתקנה בחבילה הזאת.</p>'}</div>
<div class="count">נבחרו ${st.chosen.size} להתקנה</div>`;
}

function installView() {
  const ids = [...st.chosen];
  const rows = ids.map(id => {
    const a = st.apps.find(x => x.id === id) || { name: id, icon: "app" };
    const r = st.results[id] || { st: "", text: "ממתינה" };
    return `<div class="app"><span class="st ${r.st}">${esc(r.text)}</span><span><span class="name">${icon(a.icon)}${esc(a.name)}</span></span></div>`;
  }).join("");
  if (st.done) return `<h2>הלשכה מוכנה</h2><p>${esc(st.name || "הלשכה")} הותקנה. ${ids.length ? "האפליקציות שבחרתם:" : "לא נבחרו אפליקציות — אפשר להוסיף ממסך האפליקציות."}</p><div class="apps">${rows}</div>`;
  if (st.error) return `<h2>ההתקנה לא הושלמה</h2><p class="bad">${esc(st.error)}</p><div class="apps">${rows}</div>`;
  return `<h2>מתקינה…</h2><p class="sub">כל אפליקציה מופעלת בתורה. אפשר להשאיר את החלון פתוח; התקנה ארוכה ממשיכה גם אם נסגר.</p><div class="apps">${rows}</div>`;
}

// ── drawing ──────────────────────────────────────────────────────────────────────────────────────
function render() {
  document.querySelectorAll("#steps li").forEach(li => {
    const n = Number(li.dataset.step);
    li.classList.toggle("on", n === st.step);
    li.classList.toggle("done", n < st.step);
  });
  $("#view").innerHTML = view(st.step);
  const back = $("#back"), next = $("#next"), note = $("#note");
  back.hidden = st.step === 0 || st.installing || st.done;
  note.textContent = ""; note.className = "wiz-note";
  if (st.step === 1) { next.textContent = "הבא"; next.disabled = !st.terms; if (!st.terms) note.textContent = "סמנו שקראתם את התנאים כדי להמשיך"; }
  else if (st.step === 2) { next.textContent = "הבא"; next.disabled = false; }
  else if (st.step === 3) { next.textContent = st.chosen.size ? `התקנה (${st.chosen.size})` : "המשך בלי אפליקציות"; next.disabled = !st.apps; }
  else if (st.step === 4) {
    if (st.done) { next.textContent = "אל הלשכה"; next.disabled = false; }
    else if (st.error) { next.textContent = "נסו שוב"; next.disabled = false; back.hidden = false; }
    else { next.textContent = "מתקינה…"; next.disabled = true; }
  } else { next.textContent = "הבא"; next.disabled = false; }
  wire();
}

function wire() {
  const accept = $("#accept");
  if (accept) accept.onchange = () => { st.terms = accept.checked; if (st.terms) st.termsAt = utc(); render(); };
  const oname = $("#oname");
  if (oname) oname.oninput = () => { st.name = oname.value; };
  document.querySelectorAll("[data-animal]").forEach(b => b.onclick = () => { st.animal = b.dataset.animal; render(); });
  document.querySelectorAll("[data-hue]").forEach(b => b.onclick = () => { st.hue = b.dataset.hue; render(); });
  document.querySelectorAll("[data-app]").forEach(c => c.onchange = () => {
    if (c.checked) st.chosen.add(c.dataset.app); else st.chosen.delete(c.dataset.app);
    $(".count").textContent = `נבחרו ${st.chosen.size} להתקנה`;
    $("#next").textContent = st.chosen.size ? `התקנה (${st.chosen.size})` : "המשך בלי אפליקציות";
  });
  const retry = $("#retryApps");
  if (retry) retry.onclick = () => { st.appsError = ""; st.apps = null; render(); loadApps(); };
}

async function loadApps() {
  let r;
  try { r = await fetch(API + "/apps"); } catch (e) { st.appsError = "מסך האפליקציות אינו זמין כרגע."; render(); return; }
  if (!r.ok) { st.appsError = "רשימת האפליקציות לא נטענה: " + await said(r); render(); return; }
  const d = await r.json().catch(() => null);
  const apps = (d && Array.isArray(d.apps)) ? d.apps : [];
  // what a person may choose: the installable layer — never the core (it IS the office) and never a
  // broken manifest (it could not be installed anyway)
  st.apps = apps.filter(a => !a.core && !a.broken && (a.layer === 3 || a.layer == null));
  const ai = st.apps.find(a => a.id === AI_APP);
  if (ai && !(ai.installed || ai.enabled)) st.chosen.add(AI_APP);
  render();
}

// ── the install: ONE record, then one enable per chosen app, each followed to its end ────────────
async function followJob(id) {
  const until = Date.now() + JOB_MAX_MS;
  while (Date.now() < until) {
    await new Promise(res => setTimeout(res, JOB_POLL_MS));
    const r = await fetch(API + "/apps/" + encodeURIComponent(id) + "/job").catch(() => null);
    if (!r) continue;
    const body = await r.json().catch(() => ({}));
    if (r.status === 202) { st.results[id] = { st: "", text: "מתקינה… " + esc(body.step || "") }; render(); continue; }
    return { ok: r.ok && body.ok !== false, body };
  }
  return { ok: false, body: { error: "ההתקנה עדיין רצה ברקע — בדקו במסך האפליקציות" } };
}

async function install() {
  st.step = 4; st.installing = true; st.error = ""; st.results = {}; render();
  const record = {
    name: st.name.trim() || "הלשכה הדיגיטלית", animal: st.animal, hue: st.hue,
    terms_version: TERMS_VERSION, terms_accepted_at: st.termsAt || utc(), installed_at: utc(),
  };
  let r;
  try {
    r = await fetch(API + "/office", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(record) });
  } catch (e) { r = null; }
  if (!r || !r.ok) { st.error = "רישום הלשכה נכשל: " + (r ? await said(r) : "אין תשובה מהמערכת"); st.installing = false; render(); return; }
  for (const id of st.chosen) {
    st.results[id] = { st: "", text: "מתקינה…" }; render();
    let e, body = {};
    try {
      e = await fetch(API + "/apps/" + encodeURIComponent(id) + "/enable", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      body = await e.json().catch(() => ({}));
    } catch (err) { e = null; }
    let ok = !!(e && e.ok && body.ok !== false);
    if (e && e.status === 202) { const f = await followJob(id); ok = f.ok; body = f.body; }
    st.results[id] = ok ? { st: "ok", text: "הותקנה" } : { st: "bad", text: (body && body.error) || binaSaid(e ? e.status : 0) };
    render();
  }
  st.installing = false; st.done = true; render();
}

// ── the two buttons ──────────────────────────────────────────────────────────────────────────────
$("#next").onclick = () => {
  if (st.step === 1 && !st.terms) return;
  if (st.step === 3) { install(); return; }
  if (st.step === 4) {
    if (st.done) {
      // The shell is served at "/" now that the record carries installed_at — but from "/" a change
      // of hash alone is NOT a navigation (measured 2026-10-09: the wizard simply stayed), so the
      // page is reloaded with the hash set: the shell opens on the apps screen.
      location.hash = "#/m/apps"; location.reload(); return;
    }
    if (st.error) { install(); return; }
    return;
  }
  st.step += 1; render();
  if (st.step === 3 && !st.apps && !st.appsError) loadApps();
};
$("#back").onclick = () => { if (st.step > 0 && !st.installing) { st.step -= 1; render(); } };
render();
