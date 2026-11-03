/* bina-icons — the office's one glyph set (a copy; gate G27 keeps it identical to platform-base/bina-ui/bina-icons.js). */
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
window.BINA_ICONS = BINA_ICONS;

;
/* ═══════════════════════════════════════════════════════════════════════════════════════════════
   bina-ask.js — a question and a notice, asked and said INSIDE the page.

   Eight screens still asked through the browser's own dialogs (counted 2026-10-07: 27 places):
   «console.localhost says…», English OK / Cancel, left to right, outside the page, unstyled, and
   gone the moment a frame loses focus. `confirm()` also cannot show what it is about to remove —
   it has one line of text — which is how "are you sure?" came to be asked with no facts in it.

   USE:
       if (!await binaAsk({ title: "להסיר את המחשב מהרשימה?", body: "…", ok: "הסרה", danger: true,
                            facts: [["מחשב", name], ["כתובת", host]] })) return;
       const name = await binaAsk({ title: "שם לתצוגה", ok: "שמירה", input: { label: "שם", value: old } });
       if (name == null) return;                       // cancelled — an empty string is an answer
       binaTell("המחיקה נכשלה", "bad");                 // ok | warn | bad
       binaTell("הקובץ עבר לאשפה", "ok", { ms: 8000, act: ["ביטול", restore] });   // a notice with a way back
       binaTell("השליחה נכשלה", "bad", { more: whatTheServiceSaid, stay: true });    // …and one that waits to be read
       if (await binaAsk({ title: "לבטל את הצימוד?", ok: "ביטול הצימוד", danger: true,
                           run: () => api("api/pair/" + id, { method: "DELETE" }) })) reload();   // the question does it

   A question resolves true / false — or, with `input`, the text typed (null when cancelled).
   `input.must` is a text that has to be typed before the action is offered (deleting for good).
   A destructive question opens with the focus on «ביטול», so Enter never destroys by reflex. Esc
   and a click outside cancel; Tab stays inside; the focus goes back to where it was.
   With `run` (a function, handed the answer) the question stays up while the action runs — its
   button busy, and nothing cancels what is already in flight — and answers only once it succeeded.
   A refusal (`run` throwing) is said IN the question, in the error's own words, and the action is
   offered again: for a verb that takes a while, or that the service may well refuse.
   At any height the title, the field, a refusal and the buttons stay in sight: only what is READ
   between them — the body's lines and the facts — scrolls (a desktop window drags in to 380 x 260,
   where the card used to scroll as a whole to its focused button and lose its own title).

   Self-contained on purpose: it builds its own nodes and brings its own style (read off the theme
   tokens), so a screen needs this block and nothing else — no markup to add, no class to define.

   COPIED, NOT LINKED (see bina-page.css for why): every screen carries this block verbatim and
   gate G27 fails the build when a copy stops matching. Edit HERE, then:

       python3 scripts/refactor/theme-token-lint.py --fix
   ═══════════════════════════════════════════════════════════════════════════════════════════════ */
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

;
/* «פגישות» — core.js: the app's root and its server calls, Hebrew formatting, glyphs, the direction of a piece of
   text, people's colours, and the router (the centre at …/flow/, a meeting at …/flow/<room>/). Every other file
   hangs its part on window.MF. */
(() => {
  "use strict";
  const MF = (window.MF = window.MF || {});
  const readCfg = () => { try { MF.cfg = JSON.parse((document.body && document.body.dataset.config) || "{}") || {}; } catch (e) { MF.cfg = {}; } };
  readCfg();
  // the app's root from the address: «/a/meet/» inside the console, «/» on the app's own host. The console gives
  // the page a <base> of its own; nothing here leans on it — every address is written from this root.
  MF.root = window.MF_ROOT || location.pathname.replace(/flow(\/.*)?$/, "");
  MF.url = (p) => MF.root + String(p || "").replace(/^\/+/, "");
  MF.roomUrl = (room, rest) => MF.url("flow/" + encodeURIComponent(room) + "/" + (rest || ""));

  /* ---------- text ---------- */
  MF.esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // a clock on the meeting's own axis: 0:12:34 (an hour or more) or 12:34
  MF.fmt = (t, long) => {
    t = Math.max(0, Math.floor(+t || 0));
    const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
    return h || long ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
  };
  MF.fmtLen = (sec) => {
    const m = Math.round((+sec || 0) / 60);
    if (m < 60) return `${m} דק׳`;
    const h = Math.floor(m / 60), r = m % 60;
    return r ? `${h}:${String(r).padStart(2, "0")} שע׳` : `${h} שע׳`;
  };
  const OFFICE_TZ = "Asia/Jerusalem";
  const dayKey = (d) => new Intl.DateTimeFormat("en-CA", { timeZone: OFFICE_TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
  // «2026-10-28 08:28» (the office's local time, as the recorder writes it) or epoch seconds
  MF.toDate = (v) => {
    if (v == null || v === "") return null;
    if (typeof v === "number") return new Date(v * 1000);
    const m = String(v).match(/^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/);
    if (!m) return null;
    // the string is the office's wall clock: find the instant whose office time it is
    const guess = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
    const off = (d) => { const p = new Intl.DateTimeFormat("en-US", { timeZone: OFFICE_TZ, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).formatToParts(d);
      const g = (k) => +p.find((x) => x.type === k).value; return Date.UTC(g("year"), g("month") - 1, g("day"), g("hour"), g("minute")) - d.getTime(); };
    return new Date(guess - off(new Date(guess)));
  };
  MF.day = (v, now) => {
    const d = MF.toDate(v); if (!d) return "";
    const today = dayKey(now ? new Date(now * 1000) : new Date()), k = dayKey(d);
    const y = new Date((now ? now * 1000 : Date.now()) - 86400000);
    if (k === today) return "היום";
    if (k === dayKey(y)) return "אתמול";
    return new Intl.DateTimeFormat("he-IL", { timeZone: OFFICE_TZ, weekday: "long", day: "numeric", month: "long" }).format(d);
  };
  MF.dayShort = (v) => { const d = MF.toDate(v); return d ? new Intl.DateTimeFormat("he-IL", { timeZone: OFFICE_TZ, day: "numeric", month: "short" }).format(d) : ""; };
  MF.clock = (v) => { const d = MF.toDate(v); return d ? new Intl.DateTimeFormat("he-IL", { timeZone: OFFICE_TZ, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(d) : ""; };
  MF.ago = (sec) => {
    const s = Math.max(0, Date.now() / 1000 - (+sec || 0));
    if (s < 60) return "עכשיו";
    if (s < 3600) return `לפני ${Math.round(s / 60)} דק׳`;
    if (s < 86400) return `לפני ${Math.round(s / 3600)} שע׳`;
    return `לפני ${Math.round(s / 86400)} ימים`;
  };
  MF.num = (n) => new Intl.NumberFormat("he-IL").format(+n || 0);

  // Which way a piece of text runs, by its letters (not by its first one: «Zoom עובד» starts Latin and is Hebrew)
  MF.dirOf = (s) => {
    const t = String(s || "").slice(0, 240);
    const he = (t.match(/[֐-׿]/g) || []).length, la = (t.match(/[A-Za-z]/g) || []).length;
    return la > 3 && la > he * 1.5 ? "ltr" : "rtl";
  };
  // the attributes of a block of content: its own direction; a long English paragraph reads from the left
  MF.dirAttr = (s) => (MF.dirOf(s) === "ltr" ? ` dir="ltr"${String(s || "").length > 160 ? " data-long" : ""}` : "");
  // search: case, niqqud and final letters do not matter
  MF.norm = (s) => String(s || "").toLowerCase().replace(/[֑-ׇ]/g, "")
    .replace(/[ךםןףץ]/g, (c) => ({ "ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ" }[c]));

  /* ---------- people ---------- */
  const HUES = ["sky", "lime", "plum", "olive"];
  MF.people = (colors) => {
    const map = Object.assign({}, colors || {});
    const used = new Set(Object.values(map));
    return (who) => {
      who = String(who || "?");
      if (!map[who]) { const free = HUES.find((h) => !used.has(h)) || HUES[Object.keys(map).length % HUES.length]; map[who] = free; used.add(free); }
      return map[who];
    };
  };
  MF.initial = (who) => { const s = String(who || "?").trim(); return (s.match(/[\p{L}\p{N}]/u) || ["?"])[0].toUpperCase(); };
  MF.avatar = (who, hue) => `<span class="mf-av" data-hue="${MF.esc(hue)}" title="${MF.esc(who)}" aria-hidden="true">${MF.esc(MF.initial(who))}</span>`;

  /* ---------- glyphs: the office's set (bina-icons.js), and the media/work ones it has no name for (Feather) ---------- */
  MF.ICONS = {
    play: '<polygon points="6 3 20 12 6 21 6 3"/>',
    pause: '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
    search: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    edit: '<path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>',
    users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
    flag: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/>',
    bookmark: '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
    task: '<polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    done: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
    share: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>',
    volume: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/>',
    mute: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/>',
    back10: '<polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>',
    fwd10: '<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>',
    expand: '<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/>',
    video: '<polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/>',
    headphones: '<path d="M3 18v-6a9 9 0 0 1 18 0v6"/><path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z"/>',
    list: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
    eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
    send: '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
    help: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    radio: '<circle cx="12" cy="12" r="2"/><path d="M16.24 7.76a6 6 0 0 1 0 8.49m-8.48-.01a6 6 0 0 1 0-8.49m11.31-2.82a10 10 0 0 1 0 14.14m-14.14 0a10 10 0 0 1 0-14.14"/>',
    target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    chevronL: '<polyline points="15 18 9 12 15 6"/>',
    chevronR: '<polyline points="9 18 15 12 9 6"/>',
    chevronD: '<polyline points="6 9 12 15 18 9"/>',
    arrowR: '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>',
    zoomIn: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/>',
    zoomOut: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="8" y1="11" x2="14" y2="11"/>',
    star: '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    type: '<polyline points="4 7 4 4 20 4 20 7"/><line x1="9" y1="20" x2="15" y2="20"/><line x1="12" y1="4" x2="12" y2="20"/>',
    film: '<rect x="2" y="2" width="20" height="20" rx="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="17" x2="22" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/>',
  };
  MF.ic = (name, cls) => {
    const p = MF.ICONS[name] || (window.BINA_ICONS || {})[name] || (window.BINA_ICONS || {}).app || "";
    return `<svg class="ic${cls ? " " + cls : ""}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${p}</svg>`;
  };

  /* ---------- the server ---------- */
  class MFError extends Error { constructor(code, he, doc) { super(he); this.code = code; this.doc = doc; } }
  MF.Error = MFError;
  MF.errorHe = (code, doc) => {
    const e = (doc && (doc.error || doc.detail)) || "";
    if (code === "net") return "אין חיבור לשרת הפגישות — בדקו את הרשת ונסו שוב";
    if (code === 401) return "צריך להיות מחוברים למשרד כדי לשנות פגישה";
    if (code === 403) return "השרת סירב לבקשה";
    if (code === 404) return "לא נמצא";
    if (code === 409) return "הקובץ השתנה בינתיים — ממשיכים מהנקודה שהשרת שמר";
    if (code === 413) return "הקובץ גדול מדי לשרת הזה";
    if (code === 502 && e === "plane") return "Plane לא ענה — המשימה לא נשלחה, אפשר לנסות שוב";
    if (code === 503 && e === "no store") return "האחסון של הפגישות עוד לא הוגדר בשרת — אי אפשר לשמור";
    if (code === 503) return "השירות לא זמין כרגע";
    return `השרת ענה בשגיאה (${code})`;
  };
  MF.api = async (path, opt = {}) => {
    const init = { method: opt.method || "GET", headers: { Accept: "application/json" }, credentials: "same-origin", cache: "no-store" };
    if (opt.body !== undefined) { init.body = JSON.stringify(opt.body); init.headers["Content-Type"] = "application/json"; }
    if (init.method !== "GET") init.headers["X-Meet-Flow"] = "1";
    if (opt.signal) init.signal = opt.signal;
    let r;
    try { r = await fetch(MF.url(path), init); } catch (e) { if (e && e.name === "AbortError") throw e; throw new MFError("net", MF.errorHe("net")); }
    const txt = await r.text();
    let doc = null;
    try { doc = txt ? JSON.parse(txt) : null; } catch (e) { doc = null; }
    if (!r.ok) throw new MFError(r.status, MF.errorHe(r.status, doc), doc);
    return doc;
  };
  // a meeting's full data (data.js sets window.MEETING): read as a script, once per address
  MF.loadData = (src) => new Promise((ok, bad) => {
    delete window.MEETING;
    const s = document.createElement("script");
    s.src = MF.url(src) + (src.includes("?") ? "&" : "?") + "at=" + Date.now();
    s.onload = () => { const M = window.MEETING; s.remove(); M ? ok(M) : bad(new MFError(404, "הנתונים של הפגישה ריקים")); };
    s.onerror = () => { s.remove(); bad(new MFError(404, "הנתונים של הפגישה לא נטענו")); };
    document.head.appendChild(s);
  });
  MF.tell = (text, kind, o) => (window.binaTell ? window.binaTell(text, kind || "ok", o) : console.log(text));
  MF.ask = (o) => (window.binaAsk ? window.binaAsk(o) : Promise.resolve(window.confirm(o.title)));
  MF.copy = async (text, said) => {
    try { await navigator.clipboard.writeText(text); MF.tell(said || "הקישור הועתק", "ok"); }
    catch (e) { MF.ask({ title: "הקישור", body: "העתיקו מכאן:", input: { label: "קישור", value: text }, ok: "סגירה" }); }
  };
  MF.store = {
    get(k, d) { try { const v = localStorage.getItem("mf:" + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("mf:" + k, JSON.stringify(v)); } catch (e) { /* private window */ } },
  };

  /* ---------- Hebrew names of states ---------- */
  MF.STATE = {
    before: { he: "לפני הפגישה", tone: "muted", hint: "הפגישה עוד לא התחילה" },
    live: { he: "בשידור", tone: "live", hint: "הפגישה מתקיימת עכשיו" },
    first: { he: "עיבוד ראשון", tone: "run", hint: "ההקלטה והכתוביות החיות, לפני העיבוד המלא" },
    ready: { he: "מעובדת", tone: "ok", hint: "התמלול, הנושאים, ההחלטות והמשימות מוכנים" },
    reviewed: { he: "נבדקה", tone: "ok", hint: "אדם עבר על התמלול" },
  };
  MF.STAGE = {
    record: "הקלטה", captions: "כתוביות חיות", first: "עיבוד ראשון", best: "תמלול מלא",
    speakers: "זיהוי דוברים", summary: "נושאים · החלטות · משימות", review: "בדיקה של אדם",
  };
  MF.STAGE_STATE = { done: "הושלם", running: "רץ עכשיו", waiting: "ממתין", off: "לא פעיל", failed: "נכשל" };
  MF.statePill = (state) => {
    const s = MF.STATE[state] || { he: state, tone: "muted" };
    return `<span class="mf-state" data-tone="${s.tone}" title="${MF.esc(s.hint || "")}">${s.tone === "live" ? '<i class="mf-pulse" aria-hidden="true"></i>' : ""}${MF.esc(s.he)}</span>`;
  };

  /* ---------- the router ---------- */
  MF.where = () => {
    const rest = location.pathname.slice(MF.root.length);
    const m = rest.match(/^flow\/([^/]+)\/?/);
    const q = new URLSearchParams(location.search);
    const h = location.hash.match(/^#t=?(\d+(?:\.\d+)?)/);
    return { room: m ? decodeURIComponent(m[1]).toLowerCase() : null, view: q.get("v") || "", q: q.get("q") || "", t: h ? +h[1] : null };
  };
  // the address of the page as it is, with one thing changed (the page's own path: a <base> must not move it)
  MF.setQuery = (k, v, replace = true) => {
    const q = new URLSearchParams(location.search);
    if (v == null || v === "") q.delete(k); else q.set(k, v);
    const s = q.toString();
    const href = location.pathname + (s ? "?" + s : "") + location.hash;
    try { history[replace ? "replaceState" : "pushState"](null, "", href); } catch (e) { /* a sandboxed page */ }
  };
  MF.setHash = (h) => { try { history.replaceState(null, "", location.pathname + location.search + (h ? "#" + h : "")); } catch (e) { /* */ } };
  let current = null;
  MF.go = (href, opt = {}) => {
    try { history[opt.replace ? "replaceState" : "pushState"](null, "", href); } catch (e) { location.href = href; return; }
    MF.render();
  };
  MF.render = () => {
    const w = MF.where(), app = document.getElementById("app");
    if (current && current.destroy) { try { current.destroy(); } catch (e) { console.error(e); } }
    current = null;
    window.scrollTo(0, 0);
    app.className = "mf " + (w.room ? "mf-is-meeting" : "mf-is-home");
    current = w.room ? MF.Meeting(app, w) : MF.Home(app, w);
  };
  // links inside the app move without reloading it (a click with a modifier still opens a new tab)
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a[data-go]");
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    MF.go(a.getAttribute("href"));
  });
  window.addEventListener("popstate", () => MF.render());
  // the page is drawn once the document is parsed (the scripts may run before the body exists) and its styles are in
  MF.start = () => {
    if (!(MF.Home && MF.Meeting)) return;
    const dom = document.readyState === "loading" ? new Promise((ok) => document.addEventListener("DOMContentLoaded", ok, { once: true })) : Promise.resolve();
    Promise.all([dom, window.MF_STYLES || Promise.resolve()]).then(() => { readCfg(); MF.render(); });
  };
})();

;
/* «פגישות» — stage.js: a meeting's one clock and its media (the recording's video, the side recordings), and every
   track of it on one zoomable time axis: screens, sound, who held the floor, every line and every word, topics,
   decisions, tasks, questions, the moments people marked. Media time runs LEFT TO RIGHT inside the right-to-left
   page — Material 3's rule for Hebrew and YouTube's Hebrew player: the screen, its controls and the axis are one
   left-to-right island, and only their words are Hebrew. */
(() => {
  "use strict";
  const MF = window.MF;

  MF.Stage = function Stage(M, mount, opt = {}) {
    const { esc, fmt, ic } = MF;
    const host = mount.host || document.documentElement;
    const cssv = (n) => getComputedStyle(host).getPropertyValue(n).trim() || "transparent";
    const hueOf = opt.hue || MF.people(M.colors);
    const fill = (who) => cssv("--" + hueOf(who));
    const textOf = opt.textOf || ((x) => x.text);
    const stateOf = opt.stateOf || (() => "");
    const DUR = Math.max(1, +M.meeting.duration || 0);
    const VDUR = M.video ? (+M.video.duration || DUR) : 0;
    const offs = [];
    const on = (el, ev, fn, o) => { if (!el) return; el.addEventListener(ev, fn, o); offs.push(() => el.removeEventListener(ev, fn, o)); };
    const subs = new Set();
    const abs = (u) => {
      if (!u) return u;
      if (/^([a-z][a-z0-9+.-]*:|\/|#)/i.test(u)) return u;
      if (u.startsWith("../../")) return MF.url(u.slice(6));          // the recorder's own files: …/recordings/<session>/…
      return (opt.base || "") + u;                                     // the meeting's flow folder: frames/, media/, docs/
    };
    const frameSrc = (f, kind) => (window.FRAMES && window.FRAMES[f]) || abs(`frames/${kind}/${f}`);
    const q = (sel, el) => (el || mount.root || document).querySelector(sel);

    /* ---------- the screen ---------- */
    if (mount.player) {
      mount.player.innerHTML = `
        <div class="mf-screen" dir="ltr">
          <video playsinline preload="metadata"></video>
          <img class="mf-still" alt="" hidden>
          <div class="mf-novideo" hidden>${ic("headphones")}<span dir="rtl">אין וידאו בפגישה הזו — הקול והתמלול</span></div>
          <div class="mf-after" dir="rtl" hidden></div>
          <div class="mf-cap" aria-hidden="true"></div>
          <button class="mf-bigplay" type="button" aria-label="ניגון">${ic("play")}</button>
        </div>`;
    }
    const video = mount.player ? mount.player.querySelector("video") : document.createElement("video");
    const still = mount.player ? mount.player.querySelector(".mf-still") : null;
    if (M.video && M.video.src) video.src = abs(M.video.src);
    else if (mount.player) {
      video.hidden = true;
      if ((M.frames || []).length) still.hidden = false;
      else mount.player.querySelector(".mf-novideo").hidden = false;
    }

    /* ---------- sound tracks: the meeting's own, and the side recordings (an iPad, a phone, an upload) ---------- */
    const audio = (M.audio || []).concat(opt.extraAudio || []).map((a) => {
      const el = a.src ? new Audio() : null;
      if (el) { el.preload = "none"; el.src = abs(a.src); }
      let env = null;
      if (a.env && a.env.b64) { const b = atob(a.env.b64); env = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) env[i] = b.charCodeAt(i); }
      return { ...a, el, env, rate: a.env ? a.env.rate : 10, on: a.id === "meet", offset: +a.offset || 0, duration: +a.duration || DUR };
    });
    const label = (a) => (a.id === "meet" ? "הפגישה" : a.short || a.label || a.id);

    /* ---------- the one clock ---------- */
    let t = 0, playing = false, rate = 1, follow = true, raf = 0, timer = 0, wall = null;
    const covering = (x) => audio.find((a) => a.el && a.on && x >= a.offset && x < a.offset + a.duration)
      || audio.find((a) => a.el && x >= a.offset && x < a.offset + a.duration);
    function masterTime() {
      if (M.video && t < VDUR - 0.05 && !video.ended) { wall = null; return video.currentTime; }
      const a = covering(t);
      if (a && !a.el.paused) { wall = null; return a.offset + a.el.currentTime; }
      if (!playing) return t;
      const now = performance.now();               // no media at this moment (a gap, a transcript-only meeting): a wall clock
      if (!wall) wall = { t0: t, at: now };
      return wall.t0 + ((now - wall.at) / 1000) * rate;
    }
    const videoActive = () => M.video && t < VDUR - 0.05;
    const videoRolling = () => !video.paused && !video.seeking && video.readyState >= 3;
    function syncSide(force) {
      const masterOk = videoActive() ? videoRolling() : true;   // side recordings move only while the master really moves
      for (const a of audio) {
        if (!a.el) continue;
        const inside = t >= a.offset && t < a.offset + a.duration;
        const afterVideo = !M.video || t >= VDUR - 0.05;
        const want = playing && masterOk && inside && (a.on || (afterVideo && a === covering(t)));
        a.el.muted = !(a.on || afterVideo);
        if (want) {
          const local = t - a.offset;
          if (a.el.paused) { a.el.currentTime = local; a.el.playbackRate = rate; a.el.play().catch(() => {}); }
          else if (force || Math.abs(a.el.currentTime - local) > 0.3) a.el.currentTime = local;
        } else if (!a.el.paused) a.el.pause();
      }
      const meet = audio.find((a) => a.id === "meet");
      video.muted = meet ? !meet.on : false;
    }
    function tick() {
      if (!playing) return;
      t = Math.min(DUR, masterTime());
      if (t >= DUR) { pause(); return; }
      syncSide(false);
      paint();
    }
    const frameLoop = () => { tick(); if (playing) raf = requestAnimationFrame(frameLoop); };
    function play() {
      if (playing) return;
      if (t >= DUR - 0.5) t = 0;
      playing = true; setPlayIcon();
      if (M.video && t < VDUR - 0.05) { video.playbackRate = rate; video.play().catch(() => {}); }
      syncSide(true);
      raf = requestAnimationFrame(frameLoop);
      timer = setInterval(tick, 120);              // keeps the clock and the side recordings in step when frames are throttled
      emit("play");
    }
    function pause() {
      if (!playing && video.paused) { paint(); return; }
      playing = false; wall = null; setPlayIcon();
      video.pause(); for (const a of audio) if (a.el) a.el.pause();
      cancelAnimationFrame(raf); clearInterval(timer);
      MF.setHash("t" + Math.floor(t));
      paint();
      emit("pause");
    }
    function seek(x, o = {}) {
      t = Math.max(0, Math.min(DUR, +x || 0)); wall = null;
      if (M.video) { try { video.currentTime = Math.min(t, VDUR - 0.05); } catch (e) { /* metadata not yet */ } }
      if (playing && M.video && t < VDUR - 0.05 && video.paused) video.play().catch(() => {});
      syncSide(true);
      if (!playing && o.hash !== false) MF.setHash("t" + Math.floor(t));
      paint(true);
      emit("seek");
    }
    for (const ev of ["playing", "waiting", "seeked", "stalled"]) on(video, ev, () => { if (playing) syncSide(true); });
    on(video, "ended", () => { if (playing) { t = VDUR; syncSide(true); } });
    on(video, "error", () => emit("mediaerror"));
    function setPlayIcon() {
      for (const b of (mount.root || document).querySelectorAll(".mf-play, .mf-bigplay")) {
        b.innerHTML = ic(playing ? "pause" : "play"); b.setAttribute("aria-label", playing ? "עצירה" : "ניגון");
        b.title = playing ? "עצירה (רווח)" : "ניגון (רווח)";
      }
      if (mount.player) mount.player.classList.toggle("is-playing", playing);
    }

    /* ---------- transport ---------- */
    if (mount.transport) {
      mount.transport.innerHTML = `
        <div class="mf-transport" dir="ltr" role="toolbar" aria-label="ניגון">
          <button class="mf-tb mf-play" type="button">${ic("play")}</button>
          <button class="mf-tb" type="button" data-skip="-10" title="10 שניות אחורה (חץ שמאלה)" aria-label="10 שניות אחורה">${ic("back10")}</button>
          <button class="mf-tb" type="button" data-skip="10" title="10 שניות קדימה (חץ ימינה)" aria-label="10 שניות קדימה">${ic("fwd10")}</button>
          <span class="mf-clock"><time class="mf-now">${fmt(0, DUR >= 3600)}</time><span class="mf-sep">/</span><time class="mf-dur">${fmt(DUR)}</time></span>
          <select class="mf-rate" title="מהירות ניגון" aria-label="מהירות ניגון">${[0.75, 1, 1.25, 1.5, 1.75, 2].map((r) => `<option value="${r}"${r === 1 ? " selected" : ""}>${r}×</option>`).join("")}</select>
          <span class="mf-tracks" role="group" aria-label="ערוצי קול">${audio.filter((a) => a.el || a.id === "meet").map((a, i) => `<button type="button" class="mf-chip${a.on ? " on" : ""}" data-a="${audio.indexOf(a)}" aria-pressed="${a.on}" title="${esc(a.label || label(a))} — להשמיע או להשתיק">${ic(a.on ? "volume" : "mute")}<span dir="auto">${esc(label(a))}</span></button>`).join("")}</span>
          <span class="mf-grow"></span>
          <button class="mf-tb mf-follow on" type="button" aria-pressed="true" title="התמלול וציר הזמן עוקבים אחרי הרגע המתנגן" aria-label="מעקב">${ic("target")}</button>
          <span class="mf-zoombox"><button class="mf-tb" type="button" data-zoom="out" title="להקטין את ציר הזמן (−)" aria-label="להקטין">${ic("zoomOut")}</button><input class="mf-zoom" type="range" min="0" max="1000" value="0" aria-label="זום בציר הזמן"><button class="mf-tb" type="button" data-zoom="in" title="להגדיל את ציר הזמן (+)" aria-label="להגדיל">${ic("zoomIn")}</button><button class="mf-tb" type="button" data-zoom="fit" title="כל הפגישה בציר" aria-label="כל הפגישה">${ic("expand")}</button></span>
        </div>`;
      on(mount.transport, "click", (e) => {
        const b = e.target.closest("button"); if (!b) return;
        if (b.classList.contains("mf-play")) playing ? pause() : play();
        else if (b.dataset.skip) seek(t + +b.dataset.skip);
        else if (b.dataset.a) {
          const a = audio[+b.dataset.a]; a.on = !a.on;
          b.classList.toggle("on", a.on); b.setAttribute("aria-pressed", a.on); b.querySelector("svg").outerHTML = ic(a.on ? "volume" : "mute");
          syncSide(true); drawWaves();
        } else if (b.classList.contains("mf-follow")) setFollow(!follow);
        else if (b.dataset.zoom === "in") zoomTo(pps * 1.6);
        else if (b.dataset.zoom === "out") zoomTo(pps / 1.6);
        else if (b.dataset.zoom === "fit") zoomTo(fitPps(), 0);
      });
      on(q(".mf-rate", mount.transport), "change", (e) => { rate = +e.target.value; video.playbackRate = rate; for (const a of audio) if (a.el) a.el.playbackRate = rate; });
      on(q(".mf-zoom", mount.transport), "input", (e) => zoomTo(fromSlider(+e.target.value)));
    }
    if (mount.player) on(mount.player, "click", (e) => { if (e.target.closest(".mf-bigplay") || e.target === video || e.target === still) playing ? pause() : play(); });
    function setFollow(v) {
      follow = !!v;
      for (const b of (mount.root || document).querySelectorAll(".mf-follow")) { b.classList.toggle("on", follow); b.setAttribute("aria-pressed", follow); }
      emit("follow");
    }

    /* ---------- the lanes ---------- */
    const tl = mount.timeline;
    let pps = 0.2;
    const LANES = [];
    const hidden = new Set(MF.store.get("hiddenLanes", ["captions", "likes", "insights"]));
    let playhead = null, lanes = null, inner = null, box = null, heads = null, ruler = null, tip = null, wordsC = null;
    const allTurns = (M.turns || []).concat((M.tail || []).map((x) => ({ ...x, tail: true })));
    const toks = (x) => String(textOf(x) || "").split(/\s+/).filter(Boolean);
    if (tl) {
      tl.innerHTML = `
        <div class="mf-tl" dir="ltr">
          <div class="mf-heads"><div class="mf-h mf-h-ruler"><button class="mf-tb sm mf-lanesbtn" type="button" title="אילו שורות להציג בציר" aria-expanded="false">${ic("layers")}<span dir="rtl">שורות</span></button></div></div>
          <div class="mf-lanes" tabindex="0" aria-label="ציר הזמן של הפגישה — לחיצה קופצת לרגע"><div class="mf-inner"><canvas class="mf-ruler"></canvas><div class="mf-lanebox"></div><div class="mf-playhead" aria-hidden="true"><i></i></div></div></div>
          <div class="mf-lanemenu" dir="rtl" hidden></div>
        </div>`;
      lanes = q(".mf-lanes", tl); inner = q(".mf-inner", tl); playhead = q(".mf-playhead", tl); box = q(".mf-lanebox", tl); heads = q(".mf-heads", tl); ruler = q(".mf-ruler", tl);
      tip = document.createElement("div"); tip.className = "mf-tip"; tip.hidden = true; document.body.appendChild(tip);
      offs.push(() => tip.remove());
    }
    function lane(id, title, group, cls = "") {
      if (!tl) return document.createElement("div");
      const n = LANES.length;
      heads.insertAdjacentHTML("beforeend", `<div class="mf-h ${cls}" data-lane="${id}" data-g="${group}"${hidden.has(id) ? " hidden" : ""}><span dir="rtl">${esc(title)}</span></div>`);
      const el = document.createElement("div"); el.className = "mf-lane " + cls; el.dataset.lane = id; el.dataset.g = group;
      if (hidden.has(id)) el.hidden = true;
      box.appendChild(el); LANES.push({ id, title, group, el, n }); return el;
    }
    const shown = (id) => !hidden.has(id);
    const item = (cls, s, d, html, tipText, data, style) => `<div class="${cls}" style="--s:${(+s).toFixed(2)};--d:${Math.max(0.2, +d).toFixed(2)}${style ? ";" + style : ""}" data-tip="${esc(tipText)}" ${data || ""}>${html}</div>`;
    function buildLanes() {
      if (!tl) return;
      box.innerHTML = ""; heads.querySelectorAll(".mf-h:not(.mf-h-ruler)").forEach((h) => h.remove()); LANES.length = 0; wordsC = null;
      if ((M.frames || []).length) {
        const L = lane("frames", "וידאו", "media");
        L.innerHTML = M.frames.map((f, i) => {
          const d = (M.frames[i + 1] ? M.frames[i + 1].t : f.t + 20) - f.t;
          return `<div class="mf-fr" style="--s:${f.t};--d:${d}" data-bg="${esc(frameSrc(f.f, "t"))}" data-tip="${fmt(f.t)}" data-k="frame" data-i="${i}"></div>`;
        }).join("");
      }
      if ((M.screens || []).length) {
        const L = lane("screens", "מה על המסך", "media");
        L.innerHTML = M.screens.map((s, i) => item("mf-it scr" + (s.kind === "camera" ? " cam" : ""), s.s, s.e - s.s, `<span dir="auto">${esc(s.label)}</span>`, `${fmt(s.s)}–${fmt(s.e)}\n${s.label}\n${s.detail || ""}`, `data-k="screen" data-i="${i}"`)).join("");
      }
      for (const a of audio) {
        if (!a.env && !a.el) continue;
        const L = lane("a-" + a.id, "קול · " + label(a), "media", "wave");
        if (a.env) { const c = document.createElement("canvas"); c.dataset.audio = a.id; L.appendChild(c); }
        else L.innerHTML = item("mf-it span", a.offset, a.duration, "", `${label(a)}\n${fmt(a.offset)}–${fmt(a.offset + a.duration)}`, "");
      }
      if ((M.presence || []).length) {
        const who = [...new Set(M.presence.map((p) => p.who))];
        for (const w of who) {
          const L = lane("pr-" + who.indexOf(w), "בשיחה · " + w, "speech");
          L.innerHTML = M.presence.filter((p) => p.who === w).map((p) => item("mf-it flr", p.s, p.e - p.s, "", `${w} ${fmt(p.s)}–${fmt(p.e)}`, "", `background:${fill(w)}`)).join("");
        }
      }
      if ((M.floor || []).length) {
        const L = lane("floor", "מי מדבר", "speech");
        L.innerHTML = M.floor.map((f) => item("mf-it flr", f.s, f.e - f.s, "", `${f.who} ${fmt(f.s)}`, "", `background:${fill(f.who)}`)).join("");
      }
      {
        const L = lane("turns", M.meeting.transcript_label || "תמלול", "speech", "tall");
        L.innerHTML = allTurns.map((x, i) => item("mf-it turn", x.s, Math.max(0.5, x.e - x.s), `<span dir="auto">${esc(textOf(x) || "—")}</span>`,
          `${fmt(x.s)} ${x.who}${x.tail ? " · אחרי השיחה" : ""}\n${textOf(x)}`, `data-k="turn" data-i="${i}"`, `--c:${fill(x.who)}`)).join("");
      }
      if (allTurns.some((x) => x.w)) { wordsC = document.createElement("canvas"); lane("words", "מילים", "speech").appendChild(wordsC); }
      if ((M.captions || []).length) {
        const L = lane("captions", "כתוביות חיות", "speech");
        if (shown("captions")) L.innerHTML = M.captions.map((c, i) => item("mf-it cap", c.s, Math.max(1, (c.e || c.s + 8) - c.s), `<span dir="auto">${esc(c.text)}</span>`, `${fmt(c.s)} (כתובית חיה)\n${c.text}`, `data-k="caption" data-i="${i}"`)).join("");
      }
      if ((M.topics || []).length) {
        const L = lane("topics", "נושאים", "content", "tall");
        L.innerHTML = M.topics.map((x, i) => item("mf-it top", x.s, Math.max(5, x.e - x.s), `<span dir="auto">${esc(x.title)}</span>`, `${fmt(x.s)}–${fmt(x.e)}\n${x.title}`, `data-k="topic" data-i="${i}"`)).join("");
      }
      const markers = (id, title, arr, cls, k) => {
        if (!arr || !arr.length) return;
        const L = lane(id, title, "content");
        if (shown(id)) L.innerHTML = arr.map((x, i) => `<div class="mf-mk ${typeof cls === "function" ? cls(x) : cls} st-${stateOf(k, x) || "none"}" style="--s:${+x.t || 0}" data-tip="${esc(fmt(x.t) + "\n" + (x.id ? x.id + " · " : "") + (x.text || x.label || ""))}" data-k="${k}" data-i="${i}"></div>`).join("");
      };
      markers("marks", "סימונים", opt.marks || [], (x) => "mark " + (x.label || ""), "mark");
      markers("decisions", "החלטות", M.decisions, "dec", "decision");
      markers("tasks", "משימות", M.tasks, "task", "task");
      markers("questions", "שאלות פתוחות", M.questions, "q", "question");
      markers("insights", "תובנות", M.insights, "ins", "insight");
      markers("likes", "אהבו / דחו", M.likes, (x) => (x.kind === "rejected" ? "rej" : "like"), "like");
      laneMenu();
    }
    function laneMenu() {
      const menu = tl && q(".mf-lanemenu", tl); if (!menu) return;
      const G = { media: "מדיה", speech: "דיבור", content: "תוכן" };
      menu.innerHTML = `<div class="mf-lm-h">שורות בציר הזמן</div>` + Object.entries(G).map(([g, gh]) => {
        const rows = LANES.filter((l) => l.group === g); if (!rows.length) return "";
        return `<div class="mf-lm-g">${gh}</div>` + rows.map((l) => `<label class="mf-lm-row"><input type="checkbox" data-l="${esc(l.id)}"${hidden.has(l.id) ? "" : " checked"}><span>${esc(l.title)}</span></label>`).join("");
      }).join("");
    }
    if (tl) {
      on(q(".mf-lanesbtn", tl), "click", (e) => {
        const menu = q(".mf-lanemenu", tl), open = menu.hidden;
        menu.hidden = !open; e.currentTarget.setAttribute("aria-expanded", open);
      });
      on(q(".mf-lanemenu", tl), "change", (e) => {
        const id = e.target.dataset.l; if (!id) return;
        if (e.target.checked) hidden.delete(id); else hidden.add(id);
        MF.store.set("hiddenLanes", [...hidden]);
        const box1 = tl.querySelector(`.mf-lane[data-lane="${CSS.escape(id)}"]`);
        if (e.target.checked && box1 && !box1.childElementCount) { buildLanes(); layout(); return; }   // drawn the first time it is shown
        for (const el of tl.querySelectorAll(`[data-lane="${CSS.escape(id)}"]`)) el.hidden = !e.target.checked;
        layout();
      });
      on(document, "click", (e) => {
        const menu = q(".mf-lanemenu", tl);
        if (menu && !menu.hidden && !e.target.closest(".mf-lanemenu, .mf-lanesbtn")) { menu.hidden = true; q(".mf-lanesbtn", tl).setAttribute("aria-expanded", "false"); }
      });
    }

    /* ---------- drawing: the ruler, the sound, the words ---------- */
    let W = 0;                                     // the axis's visible width, kept by the ResizeObserver
    const width = () => W || (W = lanes ? lanes.clientWidth : 800);
    const fitPps = () => Math.max(0.005, (width() - 4) / DUR);
    function layout() {
      if (!tl) return;
      inner.style.width = Math.ceil(DUR * pps) + "px";
      inner.style.setProperty("--pps", pps);
      inner.classList.toggle("far", pps < 1.5);
      drawRuler(); drawWaves(); drawWords(); paint(true);
    }
    let SL = 0;                                    // the axis's scroll, kept by its scroll event (reading it forces a layout)
    const setSL = (v) => { SL = Math.max(0, Math.min(v, DUR * pps - width())); lanes.scrollLeft = SL; };
    const view = () => { const w = width(); return { x0: SL, w, t0: SL / pps, t1: (SL + w) / pps }; };
    function prepCanvas(c, h) {
      const v = view(), dpr = window.devicePixelRatio || 1;
      c.style.left = v.x0 + "px"; c.style.width = v.w + "px"; c.style.height = h + "px";
      c.width = Math.max(1, Math.round(v.w * dpr)); c.height = Math.max(1, Math.round(h * dpr));
      const g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, v.w, h); return { g, v };
    }
    const font = (px, w) => `${w || 400} ${px}px ${cssv("--font") || "system-ui"}`;
    function drawRuler() {
      if (!ruler || !width()) return;
      const { g, v } = prepCanvas(ruler, 26);
      const steps = [1, 5, 10, 30, 60, 120, 300, 600, 900, 1800, 3600];
      const step = steps.find((s) => s * pps >= 74) || 3600;
      g.fillStyle = cssv("--muted"); g.strokeStyle = cssv("--line"); g.font = font(11); g.textBaseline = "top";
      for (let s = Math.floor(v.t0 / step) * step; s <= v.t1; s += step) {
        const x = s * pps - v.x0; g.beginPath(); g.moveTo(x + 0.5, 15); g.lineTo(x + 0.5, 26); g.stroke(); g.fillText(fmt(s), x + 4, 3);
      }
      if (M.video && VDUR < DUR - 1) {
        const x = VDUR * pps - v.x0;
        if (x > 0 && x < v.w) { g.fillStyle = cssv("--lime-d"); g.fillRect(x, 0, 2, 26); g.textAlign = "right"; g.fillText("סוף הווידאו", x - 4, 14); g.textAlign = "start"; }
      }
    }
    function showFrames() {
      const L = box && box.querySelector('.mf-lane[data-lane="frames"]'); if (!L || L.hidden) return;
      const v = view(), pad = v.t1 - v.t0;
      for (const el of L.children) {
        if (!el.dataset.bg) continue;
        const i = +el.dataset.i, f = M.frames[i];
        const d = ((M.frames[i + 1] ? M.frames[i + 1].t : f.t + 20) - f.t) * pps;
        // a thumbnail too thin to read is not fetched
        if (d >= 14 && f.t > v.t0 - pad && f.t < v.t1 + pad) { el.style.backgroundImage = `url('${el.dataset.bg}')`; delete el.dataset.bg; }
      }
    }
    function drawWaves() {
      showFrames();
      if (!box) return;
      for (const c of box.querySelectorAll("canvas[data-audio]")) {
        if (c.parentElement.hidden) continue;
        const a = audio.find((x) => x.id === c.dataset.audio), h = c.parentElement.clientHeight;
        const { g, v } = prepCanvas(c, h);
        const active = a.id === "meet" ? (!M.video || a.on) : (!a.el || a.on);   // a track this page cannot play keeps a readable shape
        g.fillStyle = active ? (a.id === "meet" ? cssv("--sky") : cssv("--lime")) : cssv("--line");
        const e = a.env, r = a.rate;
        for (let x = 0; x < v.w; x++) {
          const ta = (v.x0 + x) / pps - a.offset, tb = (v.x0 + x + 1) / pps - a.offset;
          if (tb < 0 || ta > a.duration) continue;
          const i0 = Math.max(0, Math.floor(ta * r)), i1 = Math.min(e.length - 1, Math.max(i0, Math.floor(tb * r)));
          let m = 0; for (let i = i0; i <= i1; i++) if (e[i] > m) m = e[i];
          const y = (m / 255) * (h - 6); g.fillRect(x, (h - y) / 2, 1, Math.max(1, y));
        }
        if (a.offset > 0 || a.duration < DUR) {
          g.fillStyle = cssv("--muted");
          for (const edge of [a.offset, a.offset + a.duration]) { const x = edge * pps - v.x0; if (x >= 0 && x <= v.w) g.fillRect(x, 0, 1, h); }
        }
      }
    }
    let nowTurn = -1, curWord = -1;
    function drawWords() {
      if (!wordsC || wordsC.parentElement.hidden || !width()) return;
      const h = wordsC.parentElement.clientHeight;
      const { g, v } = prepCanvas(wordsC, h);
      g.font = font(12); g.textBaseline = "middle";
      if (pps < 8) {                                 // too far out to read a word
        g.fillStyle = cssv("--muted"); g.textAlign = "center";
        g.direction = "rtl"; g.fillText("הגדילו את ציר הזמן כדי לראות כל מילה ברגע שנאמרה", v.w / 2, h / 2);
        g.textAlign = "start"; g.direction = "ltr"; return;
      }
      for (let i = Math.max(0, findAt(allTurns, v.t0 - 60)); i < allTurns.length && allTurns[i].s <= v.t1; i++) {
        const x = allTurns[i], tk = toks(x);
        if (!x.w || x.w.length !== tk.length) continue;
        const col = fill(x.who);
        for (let k = 0; k < tk.length; k++) {
          const ws = x.s + x.w[k] / 10, we = k + 1 < tk.length ? x.s + x.w[k + 1] / 10 : Math.max(x.e, ws + 0.3);
          if (we < v.t0 || ws > v.t1) continue;
          const px = ws * pps - v.x0, pw = Math.max(3, (we - ws) * pps), cur = i === nowTurn && k === curWord;
          g.fillStyle = cur ? col : cssv("--surface-2"); g.fillRect(px, 4, pw - 1, h - 8);
          g.fillStyle = col; g.fillRect(px, 4, 2, h - 8);
          g.save(); g.beginPath(); g.rect(px + 3, 0, Math.max(0, pw - 5), h); g.clip();
          g.direction = "rtl"; g.textAlign = "right";
          g.fillStyle = cur ? cssv("--" + hueOf(x.who) + "-ink") : cssv("--ink"); g.fillText(tk[k], px + pw - 3, h / 2);
          g.restore();
        }
      }
    }
    const findAt = (arr, x, s = "s") => { let lo = 0, hi = arr.length - 1, best = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (arr[m][s] <= x) { best = m; lo = m + 1; } else hi = m - 1; } return best; };
    if (tl) {
      on(lanes, "scroll", () => { SL = lanes.scrollLeft; drawRuler(); drawWaves(); drawWords(); heads.scrollTop = lanes.scrollTop; }, { passive: true });
      const ro = new ResizeObserver((es) => { W = Math.round(es[0].contentRect.width) || lanes.clientWidth; if (pps < fitPps()) pps = fitPps(); layout(); });
      ro.observe(lanes); offs.push(() => ro.disconnect());
    }

    /* ---------- zoom: from the whole meeting to 200 px a second (every word readable) ---------- */
    const zmax = 200;
    const toSlider = (p) => Math.round((1000 * Math.log(p / fitPps())) / Math.log(zmax / fitPps()));
    const fromSlider = (s) => fitPps() * Math.pow(zmax / fitPps(), s / 1000);
    function zoomTo(p, anchorX) {
      if (!tl) return;
      const old = pps; p = Math.max(fitPps(), Math.min(zmax, p));
      const ax = anchorX ?? Math.max(0, Math.min(width(), t * old - SL));
      const ta = (SL + ax) / old;
      pps = p; layout(); setSL(ta * pps - ax);
      const z = q(".mf-zoom", mount.transport || mount.root); if (z) z.value = toSlider(pps);
    }
    if (tl) on(lanes, "wheel", (e) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      const r = lanes.getBoundingClientRect();
      zoomTo(pps * Math.pow(1.0018, -e.deltaY), e.clientX - r.left);
    }, { passive: false });

    /* ---------- the moment being played ---------- */
    const cap = mount.player && q(".mf-cap", mount.player), after = mount.player && q(".mf-after", mount.player);
    const nowEl = () => q(".mf-now", mount.transport || mount.root);
    let curFrame = -1, lastSub = "";
    function paint(jump) {
      if (!M.video && still && (M.frames || []).length) {
        const fi = Math.max(0, findAt(M.frames, t, "t"));
        if (fi !== curFrame) { curFrame = fi; still.src = frameSrc(M.frames[fi].f, "f"); }
      }
      if (playhead) playhead.style.left = (t * pps).toFixed(1) + "px";
      const n = nowEl(); if (n) n.textContent = fmt(t, DUR >= 3600);
      if (after) {
        const past = M.video && t >= VDUR - 0.05;
        after.hidden = !past;
        if (past) { const a = covering(t); after.textContent = a ? `הווידאו נגמר כאן — ממשיכים מהקלטה נוספת: ${label(a)}` : "הווידאו נגמר כאן"; }
      }
      const i = findAt(allTurns, t);
      const x = allTurns[i], live = !!x && t - x.e < 4 && t >= x.s - 0.2;
      let k = -1;
      if (x && x.w) for (let j = 0; j < x.w.length && x.s + x.w[j] / 10 <= t; j++) k = j;
      if (i !== nowTurn || k !== curWord) {
        nowTurn = i; curWord = k;
        drawWords();
      }
      if (cap) {
        const html = live ? `<span class="mf-cap-line" dir="${MF.dirOf(textOf(x))}"><b data-hue="${esc(hueOf(x.who))}">${esc(x.who)}</b> ${x.w && toks(x).length === x.w.length ? toks(x).map((w, j) => (j === k ? `<span class="cw">${esc(w)}</span>` : esc(w))).join(" ") : esc(textOf(x))}</span>` : "";
        if (html !== lastSub) { cap.innerHTML = html; lastSub = html; }
      }
      if (tl && follow && (playing || jump)) {
        const px = t * pps - SL;
        if (px < 0 || px > width() * 0.9) setSL(t * pps - width() * 0.25);
      }
      if (mount.scrub) paintScrub();
      for (const f of subs) { try { f({ t, i, word: k, playing, jump: !!jump }); } catch (e) { console.error(e); } }
    }
    const evSubs = {};
    function emit(name) { for (const f of evSubs[name] || []) { try { f(); } catch (e) { console.error(e); } } }

    /* ---------- pointing at the axis ---------- */
    if (tl) {
      on(box, "mousemove", (e) => {
        const el = e.target.closest("[data-tip]");
        if (!el) { tip.hidden = true; return; }
        tip.textContent = el.dataset.tip; tip.dir = MF.dirOf(el.dataset.tip); tip.hidden = false;
        const w = tip.offsetWidth, h = tip.offsetHeight;
        tip.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, e.clientX + 12)) + "px";
        tip.style.top = Math.max(8, e.clientY - h - 12) + "px";
      });
      on(box, "mouseleave", () => { tip.hidden = true; });
      on(inner, "click", (e) => {
        const el = e.target.closest("[data-k]");
        const r = inner.getBoundingClientRect(), at = (e.clientX - r.left) / pps;
        if (!el) { seek(at); return; }
        const k = el.dataset.k, i = +el.dataset.i;
        const arr = { frame: M.frames, screen: M.screens, turn: allTurns, caption: M.captions, topic: M.topics, decision: M.decisions, task: M.tasks, question: M.questions, like: M.likes, insight: M.insights, mark: opt.marks }[k] || [];
        const x = arr[i]; if (!x) return;
        seek(x.t ?? x.s);
        if (opt.onPick) opt.onPick(k, x, i);
      });
      on(ruler, "pointerdown", (e) => {
        const r = inner.getBoundingClientRect();
        const go = (ev) => seek((ev.clientX - r.left) / pps, { hash: false });
        go(e);
        const up = () => { window.removeEventListener("pointermove", go); window.removeEventListener("pointerup", up); MF.setHash("t" + Math.floor(t)); };
        window.addEventListener("pointermove", go); window.addEventListener("pointerup", up);
      });
    }

    /* ---------- the thin bar of a phone: where we are, and where the decisions and tasks were said ---------- */
    function paintScrub() {
      const s = mount.scrub; if (!s.firstChild) {
        const ticks = [].concat((M.decisions || []).map((x) => `<i class="dec" style="--p:${(x.t / DUR) * 100}%"></i>`), (M.tasks || []).map((x) => `<i class="task" style="--p:${(x.t / DUR) * 100}%"></i>`), (opt.marks || []).map((x) => `<i class="mark" style="--p:${(x.t / DUR) * 100}%"></i>`));
        s.innerHTML = `<div class="mf-scrub" dir="ltr" role="slider" tabindex="0" aria-label="מיקום בפגישה" aria-valuemin="0" aria-valuemax="${Math.round(DUR)}"><div class="track"><div class="fill"></div>${ticks.join("")}</div><div class="knob"></div></div>`;
        const bar = s.firstChild;
        const go = (ev) => { const r = bar.getBoundingClientRect(); seek(((ev.clientX - r.left) / r.width) * DUR, { hash: false }); };
        bar.addEventListener("pointerdown", (ev) => { bar.setPointerCapture(ev.pointerId); go(ev); bar.onpointermove = go; });
        bar.addEventListener("pointerup", () => { bar.onpointermove = null; MF.setHash("t" + Math.floor(t)); });
        bar.addEventListener("keydown", (ev) => { if (ev.key === "ArrowRight") { seek(t + 10); ev.preventDefault(); } else if (ev.key === "ArrowLeft") { seek(t - 10); ev.preventDefault(); } });
      }
      const bar = s.firstChild;
      bar.style.setProperty("--p", (t / DUR) * 100 + "%");
      bar.setAttribute("aria-valuenow", Math.round(t)); bar.setAttribute("aria-valuetext", `${fmt(t)} מתוך ${fmt(DUR)}`);
    }

    /* ---------- start ---------- */
    buildLanes();
    if (tl) { pps = fitPps(); layout(); }
    setPlayIcon();
    const api = {
      M, audio, turns: allTurns, get t() { return t; }, get playing() { return playing; }, get follow() { return follow; }, DUR,
      play, pause, toggle: () => (playing ? pause() : play()), seek, setFollow, zoomTo, fit: () => zoomTo(fitPps(), 0),
      zoomIn: () => zoomTo(pps * 1.6), zoomOut: () => zoomTo(pps / 1.6), get pps() { return pps; },
      onTime(f) { subs.add(f); return () => subs.delete(f); },
      on(name, f) { (evSubs[name] = evSubs[name] || []).push(f); },
      rebuild() { buildLanes(); layout(); },            // after an edit, an approval, a new mark
      relayout: () => layout(),
      findTurn: (x) => findAt(allTurns, x),
      destroy() {
        pause(); for (const f of offs) f(); subs.clear();
        try { video.removeAttribute("src"); video.load(); } catch (e) { /* */ }
        for (const a of audio) if (a.el) { a.el.pause(); a.el.removeAttribute("src"); }
      },
    };
    window.__timeline = { audio, now: () => ({ t, playing, pps }) };   // for checks from the browser's console
    return api;
  };
})();

;
/* «פגישות» — transcript.js: every line of a meeting, following the player. A person can search it, show one
   speaker, correct a line (the machine's words stay one click away, with who changed them and when — the
   correction never erases its source), copy a link to a moment, and turn a moment into a task. */
(() => {
  "use strict";
  const MF = window.MF;

  MF.Transcript = function Transcript(el, ctx) {
    const { esc, fmt, ic } = MF;
    const { M, stage, room, hue } = ctx;
    const turns = stage ? stage.turns : (M.turns || []).concat((M.tail || []).map((x) => ({ ...x, tail: true })));
    const edits = ctx.edits || {};                      // target → the newest edit {after, before, by, at}
    const versions = ctx.versions || {};                // target → every correction of the line, oldest first (CHAT-63)
    const textOf = (x) => (edits[x.id] ? edits[x.id].after : x.text);
    const offs = [];
    const on = (n, ev, fn, o) => { n.addEventListener(ev, fn, o); offs.push(() => n.removeEventListener(ev, fn, o)); };
    const people = [...new Set(turns.map((x) => x.who).filter(Boolean))];
    const NOBODY = new Set(["?", "כתוביות", "משתתף"]);
    const names = () => [...new Set((ctx.people || []).concat(turns.map((x) => x.who)).filter((w) => w && !NOBODY.has(w)))];
    const doubt = (x) => { const low = new Set(x.low); return String(x.text).split(/\s+/).map((w, k) => (low.has(k) ? `<span class="mf-low" title="המזהה לא היה בטוח במילה הזו">${esc(w)}</span>` : esc(w))).join(" "); };
    const unsure = (s) => esc(s).replace(/\[\?\]/g, '<span class="mf-unsure" title="המילה לא נשמעה בוודאות">[?]</span>')
      .replace(/\[לא ברור\]/g, '<span class="mf-unsure" title="קטע שלא נשמע">[לא ברור]</span>');

    el.innerHTML = `
      <div class="mf-tr-bar">
        <label class="mf-find"><span class="mf-vh">חיפוש בתמלול</span>${ic("search")}<input type="search" placeholder="חיפוש במה שנאמר" autocomplete="off" enterkeyhint="search"><output class="mf-find-n" aria-live="polite"></output></label>
        <span class="mf-find-nav"><button class="mf-tb sm" type="button" data-hit="-1" title="הקודם" aria-label="התוצאה הקודמת" disabled>${ic("chevronR")}</button><button class="mf-tb sm" type="button" data-hit="1" title="הבא" aria-label="התוצאה הבאה" disabled>${ic("chevronL")}</button></span>
        ${ctx.onExport ? `<button class="mf-tb sm mf-expbtn" type="button" title="התמלול כקובץ — טקסט, VTT או SRT, עם כל התיקונים" aria-label="הורדת התמלול">${ic("download")}</button>` : ""}
        ${turns.some((x) => x.alts || (x.flags || []).length) ? `<button class="mf-tb sm mf-origbtn" type="button" aria-pressed="false" title="להציג ליד כל שורה מה כל מזהה דיבור שמע, והערות הבדיקה">${ic("layers")}<span>מקור</span></button>` : ""}
      </div>
      ${people.length > 1 ? `<div class="mf-who-filter" role="group" aria-label="להציג דובר">${people.map((w) => `<button type="button" class="mf-chip" data-who="${esc(w)}" aria-pressed="false">${MF.avatar(w, hue(w))}<bdi>${esc(w)}</bdi></button>`).join("")}</div>` : ""}
      <div class="mf-tr-list" role="list"></div>
      <button class="mf-backnow" type="button" hidden>${ic("target")}<span>חזרה לרגע המתנגן</span></button>`;
    const list = el.querySelector(".mf-tr-list"), input = el.querySelector("input[type=search]"), count = el.querySelector(".mf-find-n");
    const backNow = el.querySelector(".mf-backnow");
    const orig = el.querySelector(".mf-origbtn");
    const exp = el.querySelector(".mf-expbtn");
    if (exp) on(exp, "click", () => ctx.onExport());
    if (orig) on(orig, "click", () => { const v = orig.getAttribute("aria-pressed") !== "true"; orig.setAttribute("aria-pressed", v); el.classList.toggle("showorig", v); showOrig = v; const c = cur; render(); cur = -1; markNow(c, -1, true); });

    /* ---------- the lines ---------- */
    function row(x, i) {
      const tx = textOf(x), e = edits[x.id];
      const gone = (x.flags || []).some((f) => /moved/.test(f)) ? "המילים של השורה עברו לשורה הסמוכה" : "שורה שנמחקה בבדיקה";
      const alts = !showOrig ? "" : x.alts ? Object.entries(x.alts).map(([k, v]) => `<div class="mf-alt"><b dir="ltr">${esc(k)}</b> <span dir="auto">${esc(v)}</span></div>`).join("") : "";
      return `<div class="mf-line${x.tail ? " tail" : ""}${e ? " edited" : ""}" role="listitem" data-i="${i}" data-id="${esc(x.id || "")}" data-who="${esc(x.who || "")}" style="--c:var(--${hue(x.who)})">
        <button class="mf-t" type="button" data-seek="${x.s}" title="לנגן מכאן"><time dir="ltr">${fmt(x.s, stage && stage.DUR >= 3600)}</time></button>
        <div class="mf-line-b">
          <div class="mf-line-h"><button class="mf-who" type="button" data-act="who" data-hue="${esc(hue(x.who))}" title="${esc(x.whoWas ? `הדובר תוקן (המכונה: ${x.whoWas}) — לשנות` : "מי אמר את זה? — לבחור דובר")}" aria-label="${esc(`הדובר: ${x.who || "לא ידוע"} — לשנות`)}"><bdi>${esc(x.who || "?")}</bdi>${x.whoWas ? ic("edit") : ""}</button>${e ? `<span class="mf-edited" title="${esc(`תוקן בידי ${e.by && (e.by.name || e.by.username) || "?"} · ${MF.ago(e.at)}`)}">${ic("edit")}תוקן</span>` : ""}${x.tail ? '<span class="mf-tag">אחרי השיחה</span>' : ""}
            <span class="mf-line-acts"><button class="mf-tb xs" type="button" data-act="edit" title="לתקן את השורה" aria-label="לתקן">${ic("edit")}</button>${(versions[x.id] || []).length ? `<button class="mf-tb xs" type="button" data-act="vers" title="כל הגרסאות של השורה" aria-label="גרסאות השורה">${ic("history")}</button>` : ""}<button class="mf-tb xs" type="button" data-act="link" title="להעתיק קישור לרגע הזה" aria-label="קישור לרגע">${ic("link")}</button><button class="mf-tb xs" type="button" data-act="task" title="משימה מהרגע הזה" aria-label="משימה מכאן">${ic("task")}</button></span></div>
          <p class="mf-tx"${MF.dirAttr(tx)}>${tx ? (!e && x.low && x.low.length ? doubt(x) : unsure(tx)) : `<span class="muted">${gone}</span>`}</p>
          ${e ? `<div class="mf-was"><span class="k">היה כתוב</span> <span dir="auto">${esc(e.before)}</span></div>` : ""}
          ${showOrig && (alts || (x.flags || []).length) ? `<div class="mf-alts">${alts}${(x.flags || []).map((f) => `<div class="mf-flag" dir="auto">${esc(f)}</div>`).join("")}</div>` : ""}
        </div>
      </div>`;
    }
    let tailHead = -1, showOrig = false;
    function render() {
      tailHead = turns.findIndex((x) => x.tail);
      list.innerHTML = turns.map((x, i) => (i === tailHead ? `<div class="mf-divider" role="separator"><span>אחרי שהשיחה בווידאו נגמרה — מהקלטה נוספת</span></div>` : "") + row(x, i)).join("")
        || `<div class="mf-empty">${ic("message")}<p>אין עוד שורות בתמלול.</p></div>`;
      applyFilter();
    }

    /* ---------- following the player ---------- */
    let follow = true, cur = -1, userScroll = 0;
    const centerIn = (n, smooth) => {
      if (!n) return;
      const box = list.closest(".mf-pane") || list;
      const r = n.getBoundingClientRect(), b = box.getBoundingClientRect();
      const top = box.scrollTop + (r.top - b.top) - (box.clientHeight - r.height) / 2;
      programmatic = Date.now();
      box.scrollTo({ top, behavior: smooth ? "smooth" : "auto" });
    };
    let programmatic = 0;
    const paneOf = () => list.closest(".mf-pane") || list;
    function markNow(i, word, jump) {
      if (i !== cur) {
        list.querySelector(".mf-line.cur")?.classList.remove("cur");
        cur = i;
        const n = list.querySelector(`.mf-line[data-i="${i}"]`);
        if (n) { n.classList.add("cur"); if (follow && el.offsetParent) centerIn(n, !jump); }
      }
    }
    if (stage) offs.push(stage.onTime((s) => { if (s.playing || s.jump) markNow(s.i, s.word, s.jump); }));
    const pane = () => paneOf();
    const onScroll = () => {
      if (Date.now() - programmatic < 700 || !stage || !stage.playing) return;
      if (follow) { follow = false; backNow.hidden = false; }
    };
    setTimeout(() => on(pane(), "scroll", onScroll, { passive: true }), 0);
    on(backNow, "click", () => { follow = true; backNow.hidden = true; centerIn(list.querySelector(".mf-line.cur"), true); });

    /* ---------- search and the speaker filter ---------- */
    let hits = [], hitAt = -1, onlyWho = new Set();
    function applyFilter() {
      const qn = MF.norm(input.value.trim());
      const words = qn.split(/\s+/).filter(Boolean);
      hits = [];
      for (const n of list.querySelectorAll(".mf-line")) {
        const x = turns[+n.dataset.i], tx = textOf(x) || "";
        const whoOk = !onlyWho.size || onlyWho.has(x.who);
        const hit = !words.length || words.every((w) => MF.norm(tx).includes(w));
        n.hidden = !(whoOk && hit && (tx || !words.length));
        const p = n.querySelector(".mf-tx");
        if (words.length && hit && whoOk && tx) {
          hits.push(n);
          let h = unsure(tx);
          for (const w of words) h = markWord(h, w);
          p.innerHTML = h;
        } else if (p.dataset.marked) { p.innerHTML = tx ? unsure(tx) : p.innerHTML; }
        if (words.length) p.dataset.marked = "1"; else delete p.dataset.marked;
      }
      const d = list.querySelector(".mf-divider"); if (d) d.hidden = !!(words.length || onlyWho.size) && !hits.some((n) => turns[+n.dataset.i].tail);
      count.textContent = words.length ? (hits.length ? `${MF.num(hits.length)} שורות` : "לא נמצא") : "";
      el.querySelectorAll("[data-hit]").forEach((b) => { b.disabled = hits.length < 2; });
      hitAt = -1;
      if (!words.length && !onlyWho.size) setTimeout(() => centerIn(list.querySelector(".mf-line.cur"), false), 0);
    }
    // a word of the search, marked inside text that is already escaped (niqqud and final letters ignored)
    function markWord(html, w) {
      const parts = html.split(/(<[^>]+>)/);
      return parts.map((p) => {
        if (p.startsWith("<")) return p;
        const n = MF.norm(p); let out = "", from = 0, at;
        if (n.length !== p.length) return p;           // niqqud moved the letters: the line still counts, unmarked
        while ((at = n.indexOf(w, from)) >= 0) { out += p.slice(from, at) + "<mark>" + p.slice(at, at + w.length) + "</mark>"; from = at + w.length; }
        return out + p.slice(from);
      }).join("");
    }
    let qTimer = 0;
    on(input, "input", () => { clearTimeout(qTimer); qTimer = setTimeout(applyFilter, 120); });
    on(input, "keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); step(e.shiftKey ? -1 : 1); } if (e.key === "Escape") { input.value = ""; applyFilter(); } });
    function step(d) {
      if (!hits.length) return;
      hitAt = (hitAt + d + hits.length) % hits.length;
      const n = hits[hitAt]; centerIn(n, true);
      list.querySelector(".mf-line.hitcur")?.classList.remove("hitcur"); n.classList.add("hitcur");
      count.textContent = `${MF.num(hitAt + 1)} מתוך ${MF.num(hits.length)}`;
      if (stage) stage.seek(turns[+n.dataset.i].s);
    }
    el.querySelectorAll("[data-hit]").forEach((b) => on(b, "click", () => step(+b.dataset.hit)));
    const wf = el.querySelector(".mf-who-filter");
    if (wf) on(wf, "click", (e) => {
      const b = e.target.closest("[data-who]"); if (!b) return;
      const w = b.dataset.who; onlyWho.has(w) ? onlyWho.delete(w) : onlyWho.add(w);
      b.setAttribute("aria-pressed", onlyWho.has(w)); applyFilter();
    });

    /* ---------- a line's own actions: play from here, correct it, link to it, a task from it ---------- */
    on(list, "click", async (e) => {
      const t = e.target.closest("[data-seek]");
      if (t) { if (stage) { stage.seek(+t.dataset.seek); if (!stage.playing) stage.play(); } return; }
      const a = e.target.closest("[data-act]"); if (!a) return;
      const n = a.closest(".mf-line"), x = turns[+n.dataset.i];
      if (a.dataset.act === "link") MF.copy(location.origin + MF.roomUrl(room) + "#t" + Math.floor(x.s), "הקישור לרגע הועתק");
      else if (a.dataset.act === "edit") editLine(n, x);
      else if (a.dataset.act === "who") pickWho(n, x);
      else if (a.dataset.act === "vers") showVersions(n, x);
      else if (a.dataset.act === "task" && ctx.onTaskFrom) ctx.onTaskFrom(x, textOf(x));
    });

    /* ---------- who said it: the speaker of a line, corrected by a person (CHAT-63) ---------- */
    function closePanels(n) { n.querySelectorAll(".mf-whopick, .mf-vers").forEach((p) => p.remove()); }
    function pickWho(n, x) {
      if (!x.id) { MF.tell("לשורה הזו אין מזהה — אי אפשר לשמור תיקון", "warn"); return; }
      if (n.querySelector(".mf-whopick")) { closePanels(n); return; }
      closePanels(n);
      const all = names();
      n.querySelector(".mf-line-h").insertAdjacentHTML("afterend", `<div class="mf-whopick" role="group" aria-label="מי אמר את השורה">
        <span class="muted small">מי אמר את זה?</span>
        ${all.map((w) => `<button type="button" class="mf-chip" data-pick="${esc(w)}" aria-pressed="${w === x.who}">${MF.avatar(w, hue(w))}<bdi>${esc(w)}</bdi></button>`).join("")}
        <button type="button" class="mf-chip" data-pick-other>${ic("user")}<span>מישהו אחר…</span></button>
        ${x.whoWas ? `<button type="button" class="mf-chip" data-pick="${esc(x.whoWas)}" title="מה שהמכונה כתבה">${ic("history")}<span>כמו שהיה: <bdi>${esc(x.whoWas)}</bdi></span></button>` : ""}</div>`);
      const box = n.querySelector(".mf-whopick");
      box.querySelector("button").focus();
      box.addEventListener("click", async (ev) => {
        const b = ev.target.closest("[data-pick], [data-pick-other]"); if (!b) return;
        let name = b.dataset.pick;
        if (b.hasAttribute("data-pick-other")) {
          name = await MF.ask({ title: "מי אמר את השורה?", ok: "שמירה", input: { label: "שם הדובר", value: "" } });
          if (name == null || name === false) return;
          name = String(name).trim();
          if (!name) { MF.tell("צריך לכתוב שם", "warn"); return; }
        }
        if (name === x.who) { closePanels(n); return; }
        await setWho(n, x, name);
      });
    }
    async function setWho(n, x, name) {
      const before = x.who || "";
      try {
        await MF.api(`flow/${encodeURIComponent(room)}/edits`, { method: "POST", body: { kind: "speaker", target: x.id, before, after: name } });
      } catch (err) { MF.tell(err.message || "השמירה נכשלה", "bad"); return; }
      if (x.whoWas == null) x.whoWas = before;
      x.who = name;
      if (x.who === x.whoWas) delete x.whoWas;
      const i = +n.dataset.i;
      n.outerHTML = row(x, i);
      applyFilter();
      if (ctx.onSpeaker) ctx.onSpeaker(x);
      MF.tell(`הדובר נשמר: ${name}`, "ok", { act: ["ביטול", () => { const m = list.querySelector(`.mf-line[data-i="${i}"]`); if (m) setWho(m, x, before); }] });
    }

    /* ---------- every version of a line: the machine's, and each correction — any of them restored (CHAT-63) ---------- */
    function showVersions(n, x) {
      if (n.querySelector(".mf-vers")) { closePanels(n); return; }
      closePanels(n);
      const now = textOf(x) || "";
      const vs = [{ text: x.text || "", who: "המכונה", at: null, machine: true }].concat((versions[x.id] || []).map((e) => ({ text: e.after, who: (e.by && (e.by.name || e.by.username)) || "?", at: e.at })));
      n.querySelector(".mf-line-b").insertAdjacentHTML("beforeend", `<div class="mf-vers" role="list" aria-label="גרסאות השורה">
        ${vs.slice().reverse().map((v, k) => `<div class="mf-ver${v.text === now ? " cur" : ""}" role="listitem"><div class="mf-ver-h"><b>${esc(v.machine ? "מה שהמכונה כתבה" : v.who)}</b>${v.at ? `<span class="muted small">${esc(MF.ago(v.at))}</span>` : ""}${v.text === now ? '<span class="mf-tag" data-tone="ok">מוצגת עכשיו</span>' : `<button class="btn sm ghost" type="button" data-restore="${vs.length - 1 - k}">${ic("history")}<span>שחזור</span></button>`}</div><p dir="auto">${v.text ? esc(v.text) : '<span class="muted">(שורה ריקה)</span>'}</p></div>`).join("")}</div>`);
      n.querySelector(".mf-vers").addEventListener("click", async (ev) => {
        const b = ev.target.closest("[data-restore]"); if (!b) return;
        const v = vs[+b.dataset.restore];
        b.disabled = true;
        try {
          const r = await MF.api(`flow/${encodeURIComponent(room)}/edits`, { method: "POST", body: { kind: "line", target: x.id, before: now, after: v.text } });
          const ed = r && r.edit ? r.edit : { after: v.text, before: now, at: Date.now() / 1000, by: MF.cfg.me };
          (versions[x.id] = versions[x.id] || []).push(ed);
          if (v.text === x.text) delete edits[x.id]; else edits[x.id] = ed;
          const i = +n.dataset.i; n.outerHTML = row(x, i); applyFilter();
          if (ctx.onEdit) ctx.onEdit(x);
          MF.tell("הגרסה שוחזרה", "ok");
        } catch (err) { b.disabled = false; MF.tell(err.message || "השחזור נכשל", "bad"); }
      });
    }
    on(list, "dblclick", (e) => { const n = e.target.closest(".mf-line"); if (n && e.target.closest(".mf-tx")) editLine(n, turns[+n.dataset.i]); });
    function editLine(n, x) {
      if (!x.id) { MF.tell("לשורה הזו אין מזהה — אי אפשר לשמור תיקון", "warn"); return; }
      if (n.querySelector(".mf-edit")) return;
      const p = n.querySelector(".mf-tx"), before = textOf(x) || "";
      p.hidden = true;
      p.insertAdjacentHTML("afterend", `<div class="mf-edit"><textarea rows="2" dir="auto" aria-label="התיקון">${esc(before)}</textarea>
        <div class="mf-edit-acts"><button class="btn sm" type="button" data-e="save">שמירה</button><button class="btn sm ghost" type="button" data-e="cancel">ביטול</button><span class="muted small">Ctrl+Enter לשמירה · Esc לביטול</span></div></div>`);
      const box = n.querySelector(".mf-edit"), ta = box.querySelector("textarea");
      const grow = () => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + 2 + "px"; };
      grow(); ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length);
      ta.addEventListener("input", grow);
      const close = () => { box.remove(); p.hidden = false; };
      const save = async () => {
        const after = ta.value.trim();
        if (after === before.trim()) { close(); return; }
        const btn = box.querySelector('[data-e="save"]'); btn.disabled = true; btn.classList.add("busy");
        try {
          const r = await MF.api(`flow/${encodeURIComponent(room)}/edits`, { method: "POST", body: { kind: "line", target: x.id, before: x.text || "", after } });
          edits[x.id] = r && r.edit ? r.edit : { after, before: x.text, at: Date.now() / 1000, by: MF.cfg.me };
          (versions[x.id] = versions[x.id] || []).push(edits[x.id]);
          const i = +n.dataset.i;
          n.outerHTML = row(x, i);
          MF.tell("התיקון נשמר", "ok", { act: ["ביטול", () => undo(x, before)] });
          if (ctx.onEdit) ctx.onEdit(x);
          applyFilter();
        } catch (err) {
          btn.disabled = false; btn.classList.remove("busy");
          MF.tell(err.message || "השמירה נכשלה", "bad", { more: err.doc ? JSON.stringify(err.doc) : "" });
        }
      };
      box.addEventListener("click", (ev) => { const b = ev.target.closest("[data-e]"); if (!b) return; b.dataset.e === "save" ? save() : close(); });
      ta.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); save(); } else if (ev.key === "Escape") { ev.preventDefault(); close(); } });
    }
    async function undo(x, text) {
      try {
        const r = await MF.api(`flow/${encodeURIComponent(room)}/edits`, { method: "POST", body: { kind: "line", target: x.id, before: textOf(x) || "", after: text } });
        edits[x.id] = r && r.edit ? r.edit : edits[x.id];
        if (r && r.edit) (versions[x.id] = versions[x.id] || []).push(r.edit);
        if ((edits[x.id] || {}).after === x.text) delete edits[x.id];
        render(); if (ctx.onEdit) ctx.onEdit(x);
      } catch (err) { MF.tell(err.message, "bad"); }
    }

    render();
    return {
      el, refresh: render, focusSearch() { input.focus(); input.select(); },
      setQuery(v) { input.value = v || ""; applyFilter(); if (hits.length) step(1); },
      destroy() { for (const f of offs) f(); },
    };
  };
})();

;
/* «פגישות» — work.js: what a meeting decided, who has to do what, what stayed open — and the moments people marked.
   Everything the machine proposes waits for a person: approved, it becomes work (a task goes to Plane with a link back
   to the moment it was said); rejected, it stays visible and greyed, never deleted. Every item jumps to its moment. */
(() => {
  "use strict";
  const MF = window.MF;
  const K = { task: "T", question: "Q", decision: "D" };
  MF.itemId = (kind, x, i) => (x && x.id ? String(x.id) : (K[kind] || "U") + (i + 1));
  MF.KIND = {
    task: { he: "משימה", many: "משימות", icon: "task", approve: "אישור ושליחה ל-Plane", approved: "אושרה" },
    decision: { he: "החלטה", many: "החלטות", icon: "flag", approve: "אישור ההחלטה", approved: "אושרה" },
    question: { he: "שאלה פתוחה", many: "שאלות פתוחות", icon: "help", approve: "סימון כנענתה", approved: "נענתה" },
    mark: { he: "סימון", many: "סימונים", icon: "bookmark", approve: "אישור", approved: "אושר" },
  };
  MF.MARK = { decision: "החלטה", task: "משימה", important: "חשוב", question: "שאלה" };
  MF.ST = { proposed: "ממתין לאישור", approved: "אושר", rejected: "נדחה", edited: "נערך — ממתין" };

  // one item as it is now: the meeting's data under the stored overrides (edited text, owner, due) and state
  MF.itemView = (kind, x, i, items) => {
    const id = MF.itemId(kind, x, i), key = `${kind}:${id}`, st = (items || {})[key] || {};
    const f = Object.assign({}, st.fields || {});
    return {
      kind, id, key, src: x, state: st.state === "edited" ? "proposed" : st.state || "proposed", edited: st.state === "edited" || !!st.fields,
      text: f.text ?? x.text ?? "", owner: f.owner ?? x.who ?? x.owner ?? "", due: f.due ?? x.due ?? "", t: +(f.t ?? x.t ?? x.s ?? 0),
      also: x.also || [], type: x.type || "", area: x.area || "", where: x.where || "", label: f.label || x.label || "",
      plane: st.plane || null, by: st.by || null, at: st.at || null,
    };
  };
  // the items of one kind in a meeting: its data, then what people added (live marks, a task from a moment)
  MF.itemsOf = (kind, M, items) => {
    const base = kind === "mark" ? [] : (({ task: M.tasks, decision: M.decisions, question: M.questions })[kind] || []).map((x, i) => MF.itemView(kind, x, i, items));
    const added = Object.entries(items || {}).filter(([k, v]) => k.startsWith(kind + ":") && (v.added || /^[um]\d/.test(k.slice(kind.length + 1))))
      .map(([k, v]) => MF.itemView(kind, Object.assign({ id: k.slice(kind.length + 1) }, v.fields || {}), 0, items));
    return base.concat(added).sort((a, b) => (kind === "mark" ? a.t - b.t : 0));
  };

  async function act(room, v, action, fields) {
    const r = await MF.api(`flow/${encodeURIComponent(room)}/items`, { method: "POST", body: { kind: v.kind, id: v.id, action, fields: fields || {} } });
    return r && r.item ? r.item : null;
  }
  MF.act = act;

  /* ---------- one card ---------- */
  MF.itemCard = (v, o = {}) => {
    const { esc, fmt, ic } = MF;
    const k = MF.KIND[v.kind];
    const facts = [];
    if (v.kind === "task") { if (v.owner) facts.push(["אחראי", `<bdi>${esc(v.owner)}</bdi>`]); if (v.due) facts.push(["מתי", `<span dir="auto">${esc(v.due)}</span>`]); if (v.where) facts.push(["איפה", `<span dir="auto">${esc(v.where)}</span>`]); if (v.area) facts.push(["תחום", `<span dir="auto">${esc(v.area)}</span>`]); }
    if (v.kind === "decision" && v.type) facts.push(["סוג", `<span dir="auto">${esc(v.type)}</span>`]);
    if (v.kind === "mark" && v.label) facts.push(["סוג", esc(MF.MARK[v.label] || v.label)]);
    if (o.meeting) facts.unshift(["פגישה", `<a href="${esc(MF.roomUrl(o.meeting.room))}" data-go>${esc(o.meeting.title || o.meeting.room)}</a>`]);
    const times = [v.t].concat(v.also || []).filter((x) => x != null && !isNaN(x));
    const seek = (x) => (o.meeting ? `<a class="mf-t" href="${esc(MF.roomUrl(o.meeting.room) + "#t" + Math.floor(x))}" data-go title="לפתוח את הפגישה ברגע הזה"><time dir="ltr">${fmt(x)}</time></a>` : `<button class="mf-t" type="button" data-seek="${x}" title="לנגן מהרגע הזה"><time dir="ltr">${fmt(x)}</time></button>`);
    let foot = "";
    if (o.readOnly) foot = "";
    else if (v.state === "approved") foot = `${v.plane && v.plane.url ? `<a class="btn sm ghost" href="${esc(v.plane.url)}" target="_blank" rel="noopener">${ic("external")}<span>ב-Plane${v.plane.key ? " · " + esc(v.plane.key) : ""}</span></a>` : ""}<button class="btn sm ghost" type="button" data-a="reopen">פתיחה מחדש</button>`;
    else if (v.state === "rejected") foot = `<button class="btn sm ghost" type="button" data-a="reopen">פתיחה מחדש</button>`;
    else foot = `<button class="btn sm" type="button" data-a="approve">${ic(v.kind === "task" ? "send" : "tick")}<span>${esc(k.approve)}</span></button><button class="btn sm ghost" type="button" data-a="edit">עריכה</button><button class="btn sm ghost danger" type="button" data-a="reject">דחייה</button>`;
    if (o.compact) {
      const meta = facts.slice(0, 4).map(([a, b]) => `<span><span class="k">${a}</span> ${b}</span>`).join("");
      return `<article class="mf-item compact" data-key="${esc(v.key)}" data-state="${v.state}"${o.meeting ? ` data-room="${esc(o.meeting.room)}"` : ""}>
        <div class="mf-item-main"><header class="mf-item-h">${ic(k.icon)}<span class="mf-st" data-st="${v.state}">${esc(v.state === "approved" ? k.approved : MF.ST[v.state] || v.state)}</span>${times.slice(0, 1).map(seek).join("")}</header>
          <p class="mf-item-tx"${MF.dirAttr(v.text)}>${esc(v.text)}</p>${meta ? `<div class="mf-item-meta">${meta}</div>` : ""}</div>
        ${foot ? `<footer class="mf-item-f">${foot}</footer>` : ""}</article>`;
    }
    return `<article class="mf-item" data-key="${esc(v.key)}" data-state="${v.state}"${o.meeting ? ` data-room="${esc(o.meeting.room)}"` : ""}>
      <header class="mf-item-h">${ic(k.icon)}<span class="mf-item-id" dir="ltr">${esc(v.id)}</span><span class="mf-st" data-st="${v.state}">${esc(v.state === "approved" ? k.approved : MF.ST[v.state] || v.state)}</span>${v.edited ? `<span class="mf-tag">${ic("edit")}נערך</span>` : ""}<span class="mf-grow"></span>${times.slice(0, 4).map(seek).join("")}</header>
      <p class="mf-item-tx"${MF.dirAttr(v.text)}>${esc(v.text)}</p>
      ${facts.length ? `<dl class="mf-facts">${facts.map(([a, b]) => `<div><dt>${a}</dt><dd>${b}</dd></div>`).join("")}</dl>` : ""}
      ${foot ? `<footer class="mf-item-f">${foot}</footer>` : ""}
    </article>`;
  };

  /* ---------- a card's actions (one handler for a whole list, in a meeting or across meetings) ---------- */
  MF.bindItems = (root, getCtx) => {
    root.addEventListener("click", async (e) => {
      const s = e.target.closest("[data-seek]");
      if (s) { const c = getCtx(null); if (c.stage) { c.stage.seek(+s.dataset.seek); } return; }
      const b = e.target.closest("[data-a]"); if (!b) return;
      const card = b.closest(".mf-item"), c = getCtx(card);
      const v = c.find(card.dataset.key); if (!v) return;
      const a = b.dataset.a;
      if (a === "edit") return editCard(card, v, c);
      if (a === "reject" && !(await MF.ask({ title: `לדחות את ה${MF.KIND[v.kind].he}?`, body: "היא תישאר ברשימה, מסומנת כנדחתה — אפשר לפתוח אותה מחדש.", ok: "דחייה", danger: true, facts: [["נאמר ב-", MF.fmt(v.t)], ["הטקסט", v.text.slice(0, 120)]] }))) return;
      b.disabled = true; b.classList.add("busy");
      try {
        const item = await act(c.room, v, a);
        c.store(v.key, item || { state: a === "approve" ? "approved" : a === "reject" ? "rejected" : "proposed" });
        if (a === "approve" && v.kind === "task") {
          const p = item && item.plane;
          MF.tell(p && p.key ? `המשימה נשלחה ל-Plane · ${p.key}` : "המשימה אושרה ונשלחה ל-Plane", "ok", p && p.url ? { act: ["פתיחה", () => window.open(p.url, "_blank", "noopener")] } : {});
        } else MF.tell(a === "approve" ? `${MF.KIND[v.kind].he}: ${MF.KIND[v.kind].approved}` : a === "reject" ? "נדחתה" : "נפתחה מחדש", "ok");
        c.changed();
      } catch (err) {
        b.disabled = false; b.classList.remove("busy");
        MF.tell(err.message || "הפעולה נכשלה", "bad", { more: err.doc ? JSON.stringify(err.doc) : "", stay: err.code === 502 });
      }
    });
  };
  function editCard(card, v, c) {
    if (card.querySelector(".mf-item-edit")) return;
    const { esc } = MF;
    const people = c.people || [];
    const tx = card.querySelector(".mf-item-tx"); tx.hidden = true;
    tx.insertAdjacentHTML("afterend", `<div class="mf-item-edit">
      <label class="field"><span>הטקסט</span><textarea rows="3" dir="auto" name="text">${esc(v.text)}</textarea></label>
      ${v.kind === "task" ? `<div class="mf-edit-row"><label class="field"><span>אחראי</span><input name="owner" dir="auto" list="mf-people" value="${esc(v.owner)}"></label><label class="field"><span>מתי</span><input name="due" dir="auto" value="${esc(v.due)}" placeholder="למשל 2026-11-02 או «לפני התשלומים»"></label></div><datalist id="mf-people">${people.map((p) => `<option value="${esc(p)}">`).join("")}</datalist>` : ""}
      <div class="mf-edit-acts"><button class="btn sm" type="button" data-e="save">שמירה</button><button class="btn sm ghost" type="button" data-e="cancel">ביטול</button></div></div>`);
    const box = card.querySelector(".mf-item-edit");
    box.querySelector("textarea").focus();
    box.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-e]"); if (!b) return;
      if (b.dataset.e === "cancel") { box.remove(); tx.hidden = false; return; }
      const fields = { text: box.querySelector("[name=text]").value.trim() };
      if (v.kind === "task") { fields.owner = box.querySelector("[name=owner]").value.trim(); fields.due = box.querySelector("[name=due]").value.trim(); }
      if (!fields.text) { MF.tell("הטקסט ריק", "warn"); return; }
      b.disabled = true; b.classList.add("busy");
      try { const item = await act(c.room, v, "edit", fields); c.store(v.key, item || { state: "edited", fields }); MF.tell("נשמר", "ok"); c.changed(); }
      catch (err) { b.disabled = false; b.classList.remove("busy"); MF.tell(err.message, "bad"); }
    });
  }

  /* ---------- a list of one kind, inside a meeting ---------- */
  MF.WorkList = function WorkList(el, ctx) {
    const { esc, ic } = MF;
    const kind = ctx.kind, k = MF.KIND[kind];
    let filter = MF.store.get("wf:" + kind, "all"), who = "";
    function views() { return MF.itemsOf(kind, ctx.M, ctx.items); }
    function render() {
      const all = views();
      const n = { all: all.length, proposed: all.filter((v) => v.state === "proposed").length, approved: all.filter((v) => v.state === "approved").length, rejected: all.filter((v) => v.state === "rejected").length };
      const owners = kind === "task" ? [...new Set(all.map((v) => v.owner).filter(Boolean))] : [];
      const shown = all.filter((v) => (filter === "all" || v.state === filter) && (!who || v.owner === who));
      const seg = [["all", "הכול"], ["proposed", "ממתין"], ["approved", kind === "question" ? "נענו" : "אושרו"], ["rejected", "נדחו"]];
      el.innerHTML = `
        <div class="mf-work-bar">
          <div class="mf-seg" role="tablist" aria-label="סינון לפי מצב">${seg.map(([s, h]) => `<button type="button" role="tab" data-f="${s}" aria-selected="${filter === s}"${n[s] ? "" : " disabled"}>${h}<span class="n">${MF.num(n[s])}</span></button>`).join("")}</div>
          ${owners.length > 1 ? `<div class="mf-who-filter" role="group" aria-label="אחראי">${owners.map((w) => `<button type="button" class="mf-chip" data-own="${esc(w)}" aria-pressed="${who === w}">${MF.avatar(w, ctx.hue(w))}<bdi>${esc(w)}</bdi></button>`).join("")}</div>` : ""}
          ${kind === "task" && n.proposed ? `<button class="btn sm ghost" type="button" data-bulk="1" title="לאשר ולשלוח ל-Plane את כל המשימות שמוצגות וממתינות">${ic("send")}<span>אישור כל המוצגות</span></button>` : ""}
          ${kind === "task" ? `<button class="btn sm ghost" type="button" data-add="1">${ic("plus")}<span>משימה חדשה</span></button>` : ""}
        </div>
        <div class="mf-items">${shown.map((v) => MF.itemCard(v)).join("") || `<div class="mf-empty">${ic(k.icon)}<p>${all.length ? "אין פריטים במצב הזה." : `אין ${k.many} בפגישה הזו${ctx.M.meeting && ctx.state === "first" ? " עדיין — הן יופיעו אחרי העיבוד המלא" : ""}.`}</p></div>`}</div>`;
    }
    el.addEventListener("click", async (e) => {
      const f = e.target.closest("[data-f]"); if (f) { filter = f.dataset.f; MF.store.set("wf:" + kind, filter); render(); return; }
      const o = e.target.closest("[data-own]"); if (o) { who = who === o.dataset.own ? "" : o.dataset.own; render(); return; }
      if (e.target.closest("[data-add]")) { addTask(); return; }
      if (e.target.closest("[data-bulk]")) {
        const todo = views().filter((v) => v.state === "proposed" && (!who || v.owner === who));
        if (!todo.length) return;
        if (!(await MF.ask({ title: `לשלוח ${MF.num(todo.length)} משימות ל-Plane?`, body: "כל אחת תהיה פריט עבודה ב-Plane עם קישור לרגע שבו נאמרה.", ok: `שליחת ${MF.num(todo.length)}`, facts: [["אחראים", [...new Set(todo.map((v) => v.owner || "—"))].join(", ")], ["פגישה", ctx.title || ctx.room]] }))) return;
        let ok = 0, bad = 0;
        for (const v of todo) { try { const item = await act(ctx.room, v, "approve"); ctx.store(v.key, item || { state: "approved" }); ok++; } catch (err) { bad++; if (err.code === 502) break; } }
        MF.tell(bad ? `נשלחו ${MF.num(ok)}, ${MF.num(bad)} נכשלו` : `נשלחו ${MF.num(ok)} משימות ל-Plane`, bad ? "warn" : "ok");
        ctx.changed();
      }
    });
    async function addTask(pre) {
      pre = pre || {};
      const text = await MF.ask({ title: "משימה חדשה מהפגישה", body: pre.t != null ? `מהרגע ${MF.fmt(pre.t)}` : "", input: { label: "מה צריך לעשות", value: pre.text || "" }, ok: "הוספה" });
      if (text == null || !String(text).trim()) return;
      try {
        const r = await MF.api(`flow/${encodeURIComponent(ctx.room)}/items`, { method: "POST", body: { kind: "task", id: null, action: "add", fields: { text: String(text).trim(), t: pre.t ?? (ctx.stage ? ctx.stage.t : 0), owner: pre.owner || "" } } });
        const it = r && r.item; if (it && it.id) ctx.store(`task:${it.id}`, Object.assign({ added: true }, it));
        MF.tell("המשימה נוספה — ממתינה לאישור", "ok"); ctx.changed();
      } catch (err) { MF.tell(err.message, "bad"); }
    }
    MF.bindItems(el, () => ({ room: ctx.room, stage: ctx.stage, people: ctx.people, find: (key) => views().find((v) => v.key === key), store: ctx.store, changed: ctx.changed }));
    render();
    return { render, addTask };
  };
})();

;
/* «פגישות» — upload.js: a meeting's files. The recordings it already has (the bridge's video, the side recordings),
   its documents, and what people add to it: another recording of the same meeting (a phone, an iPad), a text, a
   document. A file goes up in 4 MB pieces (the console's proxy drops a long request), each piece confirmed by the
   server, so a dropped connection resumes where the server says it stopped. A recording is placed on the meeting's
   axis by saying when it started. */
(() => {
  "use strict";
  const MF = window.MF;
  const PIECE = 4 * 1024 * 1024;
  const KIND = (name) => {
    const x = (String(name).match(/\.([a-z0-9]+)$/i) || [, ""])[1].toLowerCase();
    if (["m4a", "mp3", "ogg", "opus", "wav", "webm", "aac", "flac"].includes(x)) return "audio";
    if (["mp4", "mov", "mkv"].includes(x)) return "video";
    if (["txt", "md", "vtt", "srt", "json"].includes(x)) return "text";
    if (["pdf", "docx", "xlsx", "pptx", "png", "jpg"].includes(x)) return "doc";
    return "";
  };
  const KIND_HE = { audio: "הקלטת קול", video: "וידאו", text: "טקסט", doc: "מסמך" };
  const KIND_IC = { audio: "headphones", video: "video", text: "type", doc: "file-text" };
  const size = (b) => (b >= 1 << 30 ? (b / (1 << 30)).toFixed(1) + " GB" : b >= 1 << 20 ? Math.round(b / (1 << 20)) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB");
  const parseClock = (s) => {
    const p = String(s || "").trim().split(":").map((x) => +x);
    if (!p.length || p.some((x) => isNaN(x))) return null;
    return p.reduce((a, x) => a * 60 + x, 0);
  };

  MF.Files = function Files(el, ctx) {
    const { esc, ic, fmt } = MF;
    const { M, room } = ctx;
    let uploads = [];
    const busy = new Map();                      // name → {sent, total, abort}
    const base = MF.roomUrl(room);
    async function load() {
      try { const r = await MF.api(`flow/${encodeURIComponent(room)}/uploads`); uploads = (r && r.uploads) || []; }
      catch (e) { uploads = []; if (e.code !== 404) MF.tell(e.message, "warn"); }
      render();
    }
    function trackRow(icon, title, meta, href) {
      return `<div class="mf-file"><span class="mf-file-ic">${ic(icon)}</span><div class="mf-file-b"><b dir="auto">${esc(title)}</b><span class="muted small">${meta}</span></div>${href ? `<a class="btn sm ghost" href="${esc(href)}" download>${ic("download")}<span>הורדה</span></a>` : ""}</div>`;
    }
    function render() {
      const own = [];
      if (M && M.video && M.video.src) own.push(trackRow("video", "הקלטת הפגישה (וידאו)", `${fmt(M.video.duration || 0)} · מהגשר של Jitsi`, M.video.src.startsWith("../../") ? MF.url(M.video.src.slice(6)) : base + M.video.src));
      for (const a of (M && M.audio) || []) if (a.id !== "meet") own.push(trackRow("headphones", a.label || a.short || a.id, `${fmt(a.duration || 0)} · מתחילה ב-${fmt(a.offset || 0)} בציר`, a.src ? base + a.src : ""));
      const docs = ((M && M.meeting && M.meeting.docs) || []).map((d) => `<button class="mf-file mf-doc" type="button" data-doc="${esc(d.href)}"><span class="mf-file-ic">${ic("file-text")}</span><div class="mf-file-b"><b dir="auto">${esc(d.title)}</b><span class="muted small">מסמך של הפגישה</span></div>${ic("chevronL", "mf-go")}</button>`);
      const ups = uploads.map((u) => {
        const b = busy.get(u.name), k = u.kind || KIND(u.name);
        const pct = b ? Math.round((b.sent / b.total) * 100) : u.done ? 100 : Math.round(((u.received || 0) / (u.size || 1)) * 100);
        const placed = k === "audio" || k === "video" ? (u.offset != null ? `מתחיל ב-${fmt(u.offset)} בציר` : "עוד לא שובץ בציר") : KIND_HE[k] || "";
        return `<div class="mf-file mf-up" data-name="${esc(u.name)}">
          <span class="mf-file-ic">${ic(KIND_IC[k] || "file-text")}</span>
          <div class="mf-file-b"><b dir="auto">${esc(u.label || u.name)}</b>
            <span class="muted small">${esc(size(u.size || 0))} · ${esc(placed)}${u.by ? ` · ${esc(u.by.name || u.by.username)}` : ""}${u.at ? ` · ${esc(MF.ago(u.at))}` : ""}</span>
            ${!u.done || b ? `<div class="mf-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><i style="--p:${pct}%"></i></div>` : ""}</div>
          <span class="mf-file-acts">${b ? `<button class="btn sm ghost" type="button" data-u="stop">עצירה</button>`
            : !u.done ? `<span class="mf-st" data-st="proposed">נעצר ב-${pct}%</span>`
            : (k === "audio" || k === "video") ? `<button class="btn sm ghost" type="button" data-u="place">${ic("clock")}<span>${u.offset != null ? "שינוי המיקום" : "שיבוץ בציר"}</span></button>` : ""}
            ${u.done ? `<a class="btn sm ghost" href="${esc(base + "uploads/" + encodeURIComponent(u.name))}" download>${ic("download")}<span>הורדה</span></a>` : ""}</span>
        </div>`;
      });
      el.innerHTML = `
        <section class="mf-sec"><h3>הקלטות</h3>${own.join("") || '<p class="muted small">ההקלטה של הפגישה תופיע כאן כשהמקליט יסיים.</p>'}</section>
        ${docs.length ? `<section class="mf-sec"><h3>מסמכים</h3>${docs.join("")}</section>` : ""}
        ${(M.turns || []).length ? `<section class="mf-sec mf-export"><h3>התמלול כקובץ</h3><p class="muted small">עם כל התיקונים — השורות והדוברים. הקובץ נכתב גם לתיקיית הפגישה ב«קבצים» מיד כשהעיבוד מוכן.</p>
          <div class="mf-export-acts">${[["txt", "טקסט", "file-text"], ["vtt", "כתוביות VTT", "type"], ["srt", "כתוביות SRT", "type"]].map(([x, h, i]) => `<a class="btn sm ghost" href="${esc(base + "transcript." + x)}" download="${esc(room + "." + x)}">${ic(i)}<span>${h}</span></a>`).join("")}</div></section>` : ""}
        <section class="mf-sec"><h3>קבצים שנוספו</h3>${ups.join("") || '<p class="muted small">עוד לא נוסף קובץ.</p>'}
          <label class="mf-drop" tabindex="0">${ic("upload")}<span><b>הוספת קובץ לפגישה</b><span class="muted small">הקלטה נוספת (טלפון, iPad), טקסט או מסמך · גררו לכאן או לחצו</span></span>
            <input type="file" multiple accept="audio/*,video/*,.txt,.md,.vtt,.srt,.json,.pdf,.docx,.xlsx,.pptx,.png,.jpg" hidden></label>
        </section>`;
    }
    async function send(file) {
      const k = KIND(file.name);
      if (!k) { MF.tell(`סוג הקובץ «${file.name}» לא נתמך`, "warn"); return; }
      const name = file.name.replace(/[\/\\:*?"<>|\x00-\x1f]/g, " ").replace(/\s+/g, " ").trim().slice(-120);
      const ctl = { sent: 0, total: file.size, stop: false };
      busy.set(name, ctl);
      if (!uploads.some((u) => u.name === name)) uploads.push({ name, size: file.size, kind: k, received: 0, done: false });
      render();
      const url = `flow/${encodeURIComponent(room)}/uploads/${encodeURIComponent(name)}`;
      try {
        while (ctl.sent < file.size && !ctl.stop) {
          const end = Math.min(file.size, ctl.sent + PIECE);
          const r = await fetch(MF.url(url), { method: "PUT", credentials: "same-origin", headers: { "X-Meet-Flow": "1", "Content-Range": `bytes ${ctl.sent}-${end - 1}/${file.size}`, "Content-Type": "application/octet-stream" }, body: file.slice(ctl.sent, end) });
          const doc = await r.json().catch(() => null);
          if (r.status === 409 && doc && doc.received != null) { ctl.sent = +doc.received; continue; }     // the server's count wins: resume there
          if (!r.ok) throw new MF.Error(r.status, MF.errorHe(r.status, doc), doc);
          ctl.sent = +(doc && doc.received) || end;
          const row = el.querySelector(`.mf-up[data-name="${CSS.escape(name)}"] .mf-bar i`);
          if (row) row.style.setProperty("--p", Math.round((ctl.sent / file.size) * 100) + "%");
        }
        busy.delete(name);
        if (!ctl.stop) MF.tell(`«${name}» הועלה`, "ok", k === "audio" || k === "video" ? { act: ["שיבוץ בציר", () => place(name)] } : {});
      } catch (e) {
        busy.delete(name);
        MF.tell(e.message || "ההעלאה נכשלה", "bad", { more: e.doc ? JSON.stringify(e.doc) : "" });
      }
      await load();
      if (ctx.onChange) ctx.onChange();
    }
    async function place(name) {
      const u = uploads.find((x) => x.name === name); if (!u) return;
      const now = ctx.stage ? ctx.stage.t : 0;
      const v = await MF.ask({ title: "מתי ההקלטה הזו מתחילה?", body: `השעה בציר של הפגישה שבה מתחיל הקובץ «${u.label || u.name}». אפשר לכתוב 0:00 אם הוא התחיל עם הפגישה, או את הרגע המתנגן עכשיו (${fmt(now)}).`, input: { label: "מתחיל ב- (דק׳:שנ׳ או ש׳:דק׳:שנ׳)", value: fmt(u.offset != null ? u.offset : now) }, ok: "שיבוץ" });
      if (v == null) return;
      const off = parseClock(v);
      if (off == null) { MF.tell("זה לא זמן — כתבו למשל 12:30", "warn"); return; }
      try { await MF.api(`${`flow/${encodeURIComponent(room)}/uploads/${encodeURIComponent(name)}`}/meta`, { method: "POST", body: { offset: off } }); MF.tell("ההקלטה שובצה בציר", "ok"); await load(); if (ctx.onChange) ctx.onChange(); }
      catch (e) { MF.tell(e.message, "bad"); }
    }
    el.addEventListener("change", (e) => { if (e.target.type === "file") { for (const f of e.target.files) send(f); e.target.value = ""; } });
    el.addEventListener("dragover", (e) => { const d = e.target.closest(".mf-drop"); if (d) { e.preventDefault(); d.classList.add("over"); } });
    el.addEventListener("dragleave", (e) => { const d = e.target.closest(".mf-drop"); if (d) d.classList.remove("over"); });
    el.addEventListener("drop", (e) => { const d = e.target.closest(".mf-drop"); if (!d) return; e.preventDefault(); d.classList.remove("over"); for (const f of e.dataTransfer.files) send(f); });
    el.addEventListener("keydown", (e) => { const d = e.target.closest(".mf-drop"); if (d && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); d.querySelector("input").click(); } });
    el.addEventListener("click", (e) => {
      const b = e.target.closest("[data-u]");
      if (b) { const name = b.closest(".mf-up").dataset.name; if (b.dataset.u === "stop") { const c = busy.get(name); if (c) c.stop = true; } else if (b.dataset.u === "place") place(name); return; }
      const d = e.target.closest("[data-doc]"); if (d && ctx.openDoc) ctx.openDoc(d.dataset.doc);
    });
    load();
    return { reload: load, get uploads() { return uploads; } };
  };
})();

;
/* «פגישות» — screens.js: the moments a screen was pointed at (M5-T44, fireplace 2026-10-29). Shlomo, call 5 [1:41:39]:
   whenever someone says «here», the shared screen's frame from that second belongs with the meeting; C1 [35:53]: every
   «צילום מסך», automatically. The transcript knows when each word was said, so the moments are found in it («צילום
   מסך» / screenshot: asked for; «פה», «הנה», «כאן»: pointed at), one per 15 s — the server's rule (screen_moments),
   the same list it writes to the meeting's Drive folder. Each moment's frame is drawn here from the recording itself
   (nothing leaves the office), and a person keeps a frame with one tap: it is stored in the meeting's folder in
   «קבצים» as «מסך HH-MM-SS.jpg», beside the recording, where every agent reads it. A frame is kept only by a person:
   a shared screen can show what must stay private (C1's password message, CHAT-106). */
(() => {
  "use strict";
  const MF = window.MF;
  Object.assign(MF.ICONS, {
    image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
    camera: '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
    history: '<path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><path d="M12 7v5l4 2"/>',
    user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  });
  const key = (w) => MF.norm(w).replace(/[^\p{L}\p{N}]/gu, "");
  const HERE = new Set(["פה", "הנה", "כאן", "מפה", "לפה", "מכאן", "לכאן", "here"].map(key));
  const SHOT_W = new Set(["screenshot", "screenshots"].map(key));
  const SHOT_P = new Set([["צילום", "מסך"], ["צלם", "מסך"], ["תצלם", "מסך"], ["צילומי", "מסך"], ["צילום", "המסך"]].map(([a, b]) => key(a) + " " + key(b)));

  /* the moments of a meeting's lines: [{t, kind: shot|here, words, line, text}], one per 15 s */
  MF.moments = (turns) => {
    const found = [];
    for (const x of turns || []) {
      const toks = String(x.text || "").split(/\s+/).filter(Boolean);
      if (!toks.length) continue;
      const keys = toks.map(key);
      const wt = Array.isArray(x.w) && x.w.length === toks.length ? x.w : null;
      keys.forEach((k, i) => {
        const kind = SHOT_W.has(k) || (i + 1 < keys.length && SHOT_P.has(k + " " + keys[i + 1])) ? "shot" : HERE.has(k) ? "here" : null;
        if (kind) found.push({ t: Math.round(((+x.s || 0) + (wt ? wt[i] / 10 : 0)) * 10) / 10, kind, word: toks[i].replace(/[.,!?;:"'״׳()]/g, ""), line: x.id, text: String(x.text).slice(0, 160) });
      });
    }
    found.sort((a, b) => a.t - b.t);
    const out = [];
    for (const f of found) {
      const last = out[out.length - 1];
      if (last && f.t - last.t < 15) { if (f.kind === "shot") last.kind = "shot"; if (!last.words.includes(f.word)) last.words.push(f.word); continue; }
      out.push({ t: f.t, kind: f.kind, words: [f.word], line: f.line, text: f.text });
    }
    return out;
  };
  const hms = (t) => { const s = Math.max(0, Math.floor(t)); return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60].map((n) => String(n).padStart(2, "0")).join("-"); };
  MF.frameName = (t) => `מסך ${hms(t)}.jpg`;

  MF.Screens = function Screens(el, ctx) {
    const { esc, ic, fmt } = MF;
    const { M, room } = ctx;
    const list = Array.isArray(M.moments) ? M.moments : MF.moments(M.turns);
    const src = M.video && M.video.src ? String(M.video.src) : "";
    const vsrc = !src ? "" : src.startsWith("../../") ? MF.url(src.slice(6)) : /^([a-z][a-z0-9+.-]*:|\/)/i.test(src) ? src : MF.roomUrl(room, src);
    const vdur = M.video ? (+M.video.duration || +(M.meeting || {}).duration || 0) : 0;
    const savedNames = () => new Set((ctx.uploads() || []).filter((u) => u.done !== false).map((u) => u.name));
    let saved = savedNames();
    const shots = list.filter((m) => m.kind === "shot");
    const card = (m, i) => {
      const has = saved.has(MF.frameName(m.t));
      const what = m.kind === "shot" ? "צילום מסך" : "«" + m.words.join("», «") + "»";
      return `<li class="mf-sc" data-i="${i}" data-kind="${m.kind}">
        <button class="mf-sc-shot" type="button" data-sc-seek="${m.t}" aria-label="לנגן מ-${fmt(m.t)}"><canvas width="320" height="180" aria-hidden="true"></canvas><span class="mf-sc-ph" aria-hidden="true">${ic("image")}</span><time dir="ltr">${fmt(m.t)}</time></button>
        <div class="mf-sc-b">
          <div class="mf-sc-h"><span class="mf-tag" data-tone="${m.kind === "shot" ? "warn" : ""}">${esc(what)}</span>${has ? `<span class="mf-tag mf-sc-kept" data-tone="ok">${ic("tick")}<span>נשמר בקבצים</span></span>` : ""}</div>
          <p class="mf-sc-tx" dir="auto">${esc(m.text)}</p>
          ${vsrc ? `<div class="mf-sc-acts"><button class="btn sm ghost" type="button" data-sc-save="${i}"${has ? " disabled" : ""}>${ic("camera")}<span>${has ? "נשמר" : "שמירה בקבצים"}</span></button></div>` : ""}
        </div></li>`;
    };
    let open = [];                                      // the «צילום מסך» moments whose frame nobody kept yet
    function render() {
      saved = savedNames();
      open = shots.filter((m) => !saved.has(MF.frameName(m.t)));
      el.innerHTML = list.length ? `
        <div class="mf-sc-head"><p class="muted small">${MF.num(list.length)} רגעים שבהם נאמר «פה», «כאן» או «צילום מסך» — כל אחד עם המסך מאותה שנייה בהקלטה. ${vsrc ? "מסך שנשמר נכנס לתיקיית הפגישה ב«קבצים»." : "לפגישה הזו אין הקלטת וידאו, אז אין מסכים לשמור."}</p>
          ${vsrc && open.length ? `<button class="btn sm" type="button" data-sc-all>${ic("camera")}<span>${open.length === 1 ? "שמירת צילום המסך" : `שמירת ${MF.num(open.length)} צילומי המסך`}</span></button>` : ""}</div>
        <ol class="mf-sc-list">${list.map(card).join("")}</ol>`
        : `<div class="mf-empty">${ic("image")}<p>בפגישה הזו לא נאמר «פה», «כאן» או «צילום מסך».</p><p class="muted small">כשמישהו מצביע על המסך המשותף במילים, הרגע והמסך שלו מופיעים כאן.</p></div>`;
      observe();
    }

    /* ---------- the frames, drawn from the recording itself: one hidden player, one moment at a time ---------- */
    let video = null, queue = [], busy = false, io = null;
    const want = new Set();
    function player() {
      if (video || !vsrc) return video;
      video = document.createElement("video");
      video.muted = true; video.preload = "auto"; video.playsInline = true; video.src = vsrc;
      return video;
    }
    const seekTo = (t) => new Promise((ok, bad) => {
      const v = player(); if (!v) { bad(new Error("no video")); return; }
      let done = false;
      const fin = (f) => { if (done) return; done = true; v.removeEventListener("seeked", on); clearTimeout(tm); f(); };
      const on = () => fin(ok);
      const tm = setTimeout(() => fin(() => bad(new Error("the recording did not answer"))), 12000);
      v.addEventListener("seeked", on);
      const go = () => { try { v.currentTime = Math.min(Math.max(0, t), (v.duration || vdur || t + 1) - 0.05); } catch (e) { fin(() => bad(e)); } };
      if (v.readyState >= 1) go(); else v.addEventListener("loadedmetadata", go, { once: true });
    });
    async function pump() {
      if (busy) return;
      busy = true;
      while (queue.length) {
        const i = queue.shift(), m = list[i], li = el.querySelector(`.mf-sc[data-i="${i}"]`);
        if (!li || li.dataset.drawn) continue;
        if (vdur && m.t > vdur) { li.dataset.drawn = "past"; continue; }
        try {
          await seekTo(m.t);
          const c = li.querySelector("canvas"), v = video;
          c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
          li.dataset.drawn = "1";
        } catch (e) { li.dataset.drawn = "failed"; }
      }
      busy = false;
    }
    function observe() {
      if (!vsrc) return;
      if (io) io.disconnect();
      io = "IntersectionObserver" in window ? new IntersectionObserver((es) => {
        for (const e of es) if (e.isIntersecting) { const i = +e.target.dataset.i; if (!want.has(i)) { want.add(i); queue.push(i); } io.unobserve(e.target); }
        pump();
      }, { root: null, rootMargin: "200px" }) : null;
      for (const li of el.querySelectorAll(".mf-sc")) { if (io) io.observe(li); else queue.push(+li.dataset.i); }
      if (!io) pump();
    }

    /* ---------- keeping a frame: the full picture, into the meeting's folder in «קבצים» ---------- */
    async function keep(i) {
      const m = list[i], name = MF.frameName(m.t);
      await seekTo(m.t);
      const v = video, w = Math.min(1280, v.videoWidth || 1280), h = Math.round(w * ((v.videoHeight || 720) / (v.videoWidth || 1280)));
      const c = document.createElement("canvas"); c.width = w; c.height = h;
      c.getContext("2d").drawImage(v, 0, 0, w, h);
      const blob = await new Promise((ok) => c.toBlob(ok, "image/jpeg", 0.86));
      if (!blob) throw new Error("לא הצלחנו לצייר את המסך");
      const url = `flow/${encodeURIComponent(room)}/uploads/${encodeURIComponent(name)}`;
      const r = await fetch(MF.url(url), { method: "PUT", credentials: "same-origin", body: blob,
        headers: { "X-Meet-Flow": "1", "Content-Range": `bytes 0-${blob.size - 1}/${blob.size}`, "Content-Type": "application/octet-stream" } });
      const doc = await r.json().catch(() => null);
      if (!r.ok && !(r.status === 409 && doc && +doc.received === blob.size)) throw new MF.Error(r.status, MF.errorHe(r.status, doc), doc);
      try { await MF.api(`${url}/meta`, { method: "POST", body: { label: `המסך ב-${fmt(m.t)} — ${m.kind === "shot" ? "צילום מסך" : "«" + m.words.join("», «") + "»"}` } }); } catch (e) { /* the name says it already */ }
      return name;
    }
    async function keepMany(idx, btn) {
      btn.disabled = true; btn.classList.add("busy");
      let ok = 0;
      for (const i of idx) {
        try { await keep(i); ok++; } catch (e) { MF.tell(e.message || "השמירה נכשלה", "bad"); break; }
      }
      if (ctx.onSaved) await ctx.onSaved();
      render();
      if (ok) MF.tell(ok === 1 ? "המסך נשמר בתיקיית הפגישה ב«קבצים»" : `${MF.num(ok)} מסכים נשמרו בתיקיית הפגישה ב«קבצים»`, "ok");
    }
    el.addEventListener("click", (e) => {
      const s = e.target.closest("[data-sc-seek]");
      if (s) { if (ctx.stage) { ctx.stage.seek(+s.dataset.scSeek); if (ctx.onSeek) ctx.onSeek(); } return; }
      const b = e.target.closest("[data-sc-save]");
      if (b) { keepMany([+b.dataset.scSave], b); return; }
      const all = e.target.closest("[data-sc-all]");
      if (all) keepMany(list.map((m, i) => (m.kind === "shot" && !saved.has(MF.frameName(m.t)) ? i : -1)).filter((i) => i >= 0), all);
    });
    render();
    return { count: list.length, refresh: render, destroy() { if (io) io.disconnect(); if (video) { video.removeAttribute("src"); video.load(); } } };
  };
})();

;
/* «פגישות» — meeting.js: ONE address for a meeting's whole life (…/flow/<room>/). Before it starts: what is left
   open from the meeting before it, and the way in. While it runs: what is being said, as it is said, and a button to
   mark a moment. The moment it ends: its recording and its captions. After processing: every word, who said it,
   what was decided and who does what — each on the one time axis, each a click from its moment. */
(() => {
  "use strict";
  const MF = window.MF;

  MF.Meeting = function Meeting(app, where) {
    const { esc, ic, fmt } = MF;
    const room = where.room;
    const api = (p) => `flow/${encodeURIComponent(room)}/${p}`;
    const offs = [], timers = [];
    const on = (el, ev, fn, o) => { el.addEventListener(ev, fn, o); offs.push(() => el.removeEventListener(ev, fn, o)); };
    let info = null, M = null, stage = null, tr = null, lists = {}, files = null, items = {}, edits = {}, uploads = [], dead = false;
    let versions = {}, whoEdits = {}, screens = null;    // CHAT-63: every correction of a line; a line's corrected speaker
    let hue = MF.people({});
    const isPhone = () => window.matchMedia("(max-width: 899px)").matches;
    document.title = `${room} · פגישות`;

    app.innerHTML = `<div class="mf-mtg" data-state="loading"><header class="mf-mh"><a class="mf-back" href="${esc(MF.url("flow/"))}" data-go>${ic("chevronR")}<span>פגישות</span></a><div class="mf-mh-t"><h1><bdi>${esc(room)}</bdi></h1><div class="mf-mh-meta"><span class="mf-skel w8"></span></div></div></header><div class="mf-loading" role="status"><span class="mf-spin"></span><span>טוען את הפגישה…</span></div></div>`;

    /* ---------- loading ---------- */
    async function load() {
      try { info = await MF.api(api("meeting.json")); }
      catch (e) { return fail(e); }
      if (dead) return;
      document.title = `${info.title || room} · פגישות`;
      if (info.state === "before") return renderBefore();
      if (info.state === "live") return renderLive();
      if (!info.data) return fail(new MF.Error(404, "לפגישה הזו עוד אין נתונים"));
      try {
        const [m, ed, it] = await Promise.all([
          MF.loadData(info.data),
          MF.api(api("edits")).catch(() => ({ edits: [] })),
          MF.api(api("items")).catch(() => ({ items: {} })),
        ]);
        M = m; items = (it && it.items) || {};
        edits = {}; versions = {}; whoEdits = {};
        for (const e of (ed && ed.edits) || []) {
          if (e.kind === "line") { edits[e.target] = e; (versions[e.target] = versions[e.target] || []).push(e); }
          else if (e.kind === "speaker" && e.after) whoEdits[e.target] = e;
        }
        for (const [k, e] of Object.entries(edits)) if (e.after === e.before) delete edits[k];
        // a corrected speaker is the line's speaker everywhere: the transcript, the axis, who talked how much
        for (const x of (M.turns || []).concat(M.tail || [])) { const w = whoEdits[x.id]; if (w && w.after !== x.who) { x.whoWas = x.who; x.who = w.after; } }
        if (!Array.isArray(M.moments)) M.moments = MF.moments ? MF.moments(M.turns) : [];
        try { const u = await MF.api(api("uploads")); uploads = (u && u.uploads) || []; } catch (e) { uploads = []; }
      } catch (e) { return fail(e); }
      if (dead) return;
      hue = MF.people(M.colors);
      renderFull();
    }
    function fail(e) {
      if (dead) return;
      app.querySelector(".mf-loading").outerHTML = `<div class="mf-fail callout warn"><b>${esc(e.code === 404 ? "הפגישה לא נמצאה" : "הפגישה לא נטענה")}</b><p>${esc(e.message || "")}</p><p><a class="btn sm ghost" href="${esc(MF.url("flow/"))}" data-go>חזרה לפגישות</a> <button class="btn sm" type="button" data-retry>לנסות שוב</button></p></div>`;
      app.querySelector("[data-retry]").onclick = () => MF.render();
    }

    /* ---------- the header and the ribbon of stages (the same for every state) ---------- */
    function head(extraActs) {
      const st = info.state, people = info.people || [];
      const when = info.started_ts ? `${MF.day(info.started_ts)} · ${MF.clock(info.started_ts)}` : "";
      const len = info.started_ts && info.ended_ts ? MF.fmtLen(info.ended_ts - info.started_ts) : "";
      const hostUrl = MF.url("r/" + encodeURIComponent(room));
      const join = st === "before" || st === "live" ? `<a class="btn" href="${esc(hostUrl)}" target="_blank" rel="noopener" title="פתיחת הפגישה בחלון חדש">${ic("video")}<span>${st === "live" ? "הצטרפות לפגישה" : "התחלת הפגישה"}</span></a>` : "";
      return `<header class="mf-mh">
        <a class="mf-back" href="${esc(MF.url("flow/"))}" data-go title="כל הפגישות">${ic("chevronR")}<span>פגישות</span></a>
        <div class="mf-mh-t"><h1><bdi>${esc(info.title || room)}</bdi></h1>
          <div class="mf-mh-meta">${MF.statePill(st)}${when ? `<span>${esc(when)}</span>` : ""}${len ? `<span>${esc(len)}</span>` : ""}${people.length ? `<span class="mf-people">${people.slice(0, 6).map((p) => MF.avatar(p, hue(p))).join("")}<span class="mf-people-n">${esc(people.slice(0, 3).join(", "))}${people.length > 3 ? ` +${people.length - 3}` : ""}</span></span>` : ""}</div></div>
        <div class="mf-mh-acts">${join}${extraActs || ""}<button class="btn ghost" type="button" data-share title="להעתיק את הקישור לפגישה">${ic("share")}<span>שיתוף</span></button></div>
      </header>${ribbon()}`;
    }
    function ribbon() {
      const s = info.stages || [];
      if (!s.length) return "";
      return `<ol class="mf-ribbon" aria-label="שלבי העיבוד">${s.map((x) => `<li data-st="${esc(x.state)}" title="${esc((MF.STAGE_STATE[x.state] || x.state) + (x.detail ? " — " + x.detail : ""))}"><i aria-hidden="true">${x.state === "done" ? ic("tick") : x.state === "running" ? '<span class="mf-spin sm"></span>' : x.state === "failed" ? ic("x") : ""}</i><span>${esc(MF.STAGE[x.key] || x.key)}</span></li>`).join("")}</ol>`;
    }
    function bindHead(root) {
      const sh = root.querySelector("[data-share]");
      if (sh) sh.onclick = () => MF.copy(location.origin + MF.roomUrl(room) + (stage && stage.t > 1 ? "#t" + Math.floor(stage.t) : ""), stage && stage.t > 1 ? `הקישור הועתק — נפתח ב-${fmt(stage.t)}` : "הקישור לפגישה הועתק");
    }

    /* ---------- BEFORE: the way in, and what the meeting before it left open ---------- */
    async function renderBefore() {
      let prevRows = [], prevMeet = null;
      if (info.prev) {
        try {
          const [inb, ms] = await Promise.all([MF.api("flow/api/inbox?all=1"), MF.api("flow/api/meetings")]);
          prevRows = ((inb && inb.items) || []).filter((r) => r.room === info.prev.room && r.state !== "rejected");
          prevMeet = ((ms && ms.meetings) || []).find((m) => m.room === info.prev.room) || null;
        } catch (e) { /* the prep is a help, not a condition */ }
      }
      if (dead) return;
      const guest = info.meet_url || (MF.cfg.meet ? MF.cfg.meet.replace(/\/$/, "") + "/" + encodeURIComponent(room) : "");
      const openTasks = prevRows.filter((r) => r.kind === "task" && r.state !== "approved");
      const sentTasks = prevRows.filter((r) => r.kind === "task" && r.state === "approved");
      const decs = prevRows.filter((r) => r.kind === "decision");
      const docs = (prevMeet && prevMeet.docs) || [];
      app.innerHTML = `<div class="mf-mtg" data-state="before">${head()}
        <div class="mf-before">
          <section class="mf-card mf-door">
            <div class="mf-door-ic">${ic("video")}</div>
            <h2>הפגישה עוד לא התחילה</h2>
            <p class="muted">כשהיא תתחיל, הדף הזה יראה אותה בשידור — כל מה שנאמר, ברגע שנאמר — ואחרי שתסתיים, את ההקלטה, התמלול, ההחלטות והמשימות. הכתובת לא משתנה.</p>
            <div class="mf-door-acts"><a class="btn" href="${esc(MF.url("r/" + encodeURIComponent(room)))}" target="_blank" rel="noopener">${ic("video")}<span>התחלת הפגישה</span></a>${guest ? `<button class="btn ghost" type="button" data-guest="${esc(guest)}">${ic("link")}<span>קישור לאורחים</span></button>` : ""}</div>
            <p class="muted small mf-watching"><span class="mf-pulse idle"></span>הדף בודק כל כמה שניות אם הפגישה התחילה</p>
          </section>
          ${info.prev ? `<section class="mf-card mf-prep">
            <header class="mf-sec-h"><h2>הכנה — מה נשאר פתוח מ<a href="${esc(MF.roomUrl(info.prev.room))}" data-go>${esc(info.prev.title || info.prev.room)}</a></h2></header>
            ${docs.length ? `<div class="mf-prep-docs">${docs.map((d) => { const href = Array.isArray(d) ? d[1] : d.href, title = Array.isArray(d) ? d[0] : d.title; return `<a class="mf-file mf-doc" href="${esc(MF.roomUrl(info.prev.room, href))}" target="_blank" rel="noopener"><span class="mf-file-ic">${ic("file-text")}</span><div class="mf-file-b"><b dir="auto">${esc(title)}</b><span class="muted small">מסמך מהפגישה הקודמת</span></div>${ic("external", "mf-go")}</a>`; }).join("")}</div>` : ""}
            <div class="mf-kpis">${[["משימות פתוחות", openTasks.length, "warn"], ["נשלחו ל-Plane", sentTasks.length, "ok"], ["החלטות", decs.length, ""]].map(([k, n, tone]) => `<div class="mf-kpi" data-tone="${tone}"><b>${MF.num(n)}</b><span>${k}</span></div>`).join("")}</div>
            ${openTasks.length ? `<h3 class="mf-h3">משימות שעוד לא אושרו</h3><div class="mf-items">${openTasks.slice(0, 12).map((r, i) => MF.itemCard(MF.itemView("task", Object.assign({ id: r.id, who: r.owner }, r), i, {}), { meeting: info.prev, readOnly: true, compact: true })).join("")}</div>${openTasks.length > 12 ? `<p><a class="btn sm ghost" href="${esc(MF.roomUrl(info.prev.room) + "?v=task")}" data-go>לכל ${MF.num(openTasks.length)} המשימות</a></p>` : ""}` : ""}
          </section>` : ""}
        </div></div>`;
      bindHead(app);
      const g = app.querySelector("[data-guest]"); if (g) g.onclick = () => MF.copy(g.dataset.guest, "הקישור לאורחים הועתק");
      poll(10000, async () => { const n = await MF.api(api("meeting.json")); if (n.state !== "before") MF.render(); });
    }

    /* ---------- LIVE: what is being said, as it is said ---------- */
    function renderLive() {
      app.innerHTML = `<div class="mf-mtg" data-state="live">${head()}
        <div class="mf-body mf-live">
          <section class="mf-stagecol">
            <div class="mf-card mf-onair">
              <div class="mf-onair-h"><span class="mf-state" data-tone="live"><i class="mf-pulse"></i>בשידור</span><time class="mf-elapsed" dir="ltr">0:00</time><span class="mf-rec muted small"></span></div>
              <div class="mf-bigcap" aria-live="polite"><p class="muted">מחכים למילים הראשונות…</p></div>
              <div class="mf-present"></div>
            </div>
            <div class="mf-card mf-markbar">
              <h3>לסמן את הרגע</h3>
              <div class="mf-marks-acts">${Object.entries(MF.MARK).map(([k, h]) => `<button class="btn ghost" type="button" data-mark="${k}">${ic(k === "decision" ? "flag" : k === "task" ? "task" : k === "question" ? "help" : "star")}<span>${h}</span></button>`).join("")}</div>
              <p class="muted small">סימון נשמר עם הרגע שבו נלחץ, ומופיע בציר הזמן של הפגישה אחרי שתסתיים.</p>
              <div class="mf-marklist"></div>
            </div>
          </section>
          <aside class="mf-side"><div class="mf-pane on mf-livelist" aria-live="off"><div class="mf-empty">${ic("mic")}<p>הכתוביות מופיעות כאן כשמישהו מדבר.</p></div></div></aside>
        </div></div>`;
      bindHead(app);
      const list = app.querySelector(".mf-livelist"), big = app.querySelector(".mf-bigcap"), present = app.querySelector(".mf-present");
      const el = app.querySelector(".mf-elapsed"), rec = app.querySelector(".mf-rec"), marklist = app.querySelector(".mf-marklist");
      let started = info.started_ts || Date.now() / 1000, stick = true, shown = 0;
      list.addEventListener("scroll", () => { stick = list.scrollTop + list.clientHeight > list.scrollHeight - 40; }, { passive: true });
      const tickClock = () => { el.textContent = fmt(Date.now() / 1000 - started); };
      timers.push(setInterval(tickClock, 1000)); tickClock();
      async function marks() {
        try { const r = await MF.api(api("items")); items = (r && r.items) || {}; } catch (e) { return; }
        const ms = MF.itemsOf("mark", { meeting: {} }, items);
        marklist.innerHTML = ms.length ? `<ol class="mf-mlist">${ms.slice(-8).reverse().map((v) => `<li><time dir="ltr">${fmt(v.t)}</time><b>${esc(MF.MARK[v.label] || "סימון")}</b>${v.by ? `<span class="muted small">${esc(v.by.name || v.by.username)}</span>` : ""}</li>`).join("")}</ol>` : "";
      }
      app.querySelector(".mf-marks-acts").addEventListener("click", async (e) => {
        const b = e.target.closest("[data-mark]"); if (!b) return;
        const t = Math.max(0, Date.now() / 1000 - started);
        b.disabled = true;
        try {
          const r = await MF.api(api("items"), { method: "POST", body: { kind: "mark", id: null, action: "add", fields: { t, label: b.dataset.mark } } });
          MF.tell(`סומן: ${MF.MARK[b.dataset.mark]} ב-${fmt(t)}`, "ok");
          if (r && r.item) await marks();
        } catch (err) { MF.tell(err.message, "bad"); }
        finally { b.disabled = false; }
      });
      async function pull() {
        let d;
        try { d = await MF.api(api("live.json")); } catch (e) { rec.textContent = "אין חיבור לכתוביות"; return; }
        if (dead) return;
        if (d && d.flow) { MF.tell("הפגישה הסתיימה — עוברים להקלטה ולתמלול", "ok"); MF.render(); return; }
        if (d.started) started = +d.started;
        const now = d.now || {};
        rec.textContent = now.recording === "on" ? "מוקלטת" : now.recording ? `הקלטה: ${now.recording}` : "";
        const names = now.names || d.people || [];
        const quiet = new Set(d.uncaptioned || []);
        present.innerHTML = names.length ? `<span class="muted small">בפגישה עכשיו</span>${names.map((n) => `<span class="mf-chip static${quiet.has(n) ? " quiet" : ""}" title="${quiet.has(n) ? "הקול שלו לא נכנס לכתוביות — רק להקלטה" : "בכתוביות"}">${MF.avatar(n, hue(n))}<bdi>${esc(n)}</bdi>${quiet.has(n) ? ic("mute") : ""}</span>`).join("")}` : "";
        const segs = (d.segments || []).slice().sort((a, b) => a.t - b.t);
        if (segs.length && segs.length !== shown) {
          shown = segs.length;
          list.innerHTML = segs.map((s) => `<div class="mf-line${s.final ? "" : " interim"}" style="--c:var(--${hue(s.name)})"><span class="mf-t static"><time dir="ltr">${fmt(s.t - started)}</time></span><div class="mf-line-b"><div class="mf-line-h"><b class="mf-who" data-hue="${esc(hue(s.name))}"><bdi>${esc(s.name || "?")}</bdi></b></div><p class="mf-tx"${MF.dirAttr(s.text)}>${esc(s.text)}</p></div></div>`).join("");
          if (stick) list.scrollTop = list.scrollHeight;
          const last = segs.slice(-2);
          big.innerHTML = last.map((s) => `<p${MF.dirAttr(s.text)}><b data-hue="${esc(hue(s.name))}"><bdi>${esc(s.name || "?")}</bdi></b> ${esc(s.text)}</p>`).join("");
        }
      }
      pull(); marks();
      poll(4000, pull); poll(20000, marks);
    }

    /* ---------- AFTER: the whole meeting on one axis ---------- */
    const TABS = [["tr", "תמלול", "message"], ["ov", "סקירה", "eye"], ["decision", "החלטות", "flag"], ["task", "משימות", "task"], ["question", "שאלות", "help"], ["sc", "מסכים", "image"], ["tl", "ציר זמן", "layers"], ["files", "קבצים", "folder"], ["hist", "יומן", "clock"]];
    function countOf(kind) { return MF.itemsOf(kind, M, items); }
    function tabBadge(k) {
      if (k === "sc") return M && (M.moments || []).length ? `<span class="n" title="רגעים שבהם הצביעו על המסך">${MF.num(M.moments.length)}</span>` : "";
      if (!["decision", "task", "question"].includes(k)) return "";
      const all = countOf(k), wait = all.filter((v) => v.state === "proposed").length;
      return all.length ? `<span class="n${wait ? " wait" : ""}" title="${wait ? `${wait} ממתינים לאישור` : "הכול טופל"}">${MF.num(all.length)}</span>` : "";
    }
    function renderFull() {
      const st = info.state;
      const extraAudio = uploads.filter((u) => u.done && (u.kind === "audio" || u.kind === "video") && u.offset != null).map((u) => ({ id: "up-" + u.name, label: u.label || u.name, short: u.label || u.name.replace(/\.[^.]+$/, ""), src: "uploads/" + encodeURIComponent(u.name), offset: +u.offset, duration: +u.duration || 0 }));
      app.innerHTML = `<div class="mf-mtg" data-state="${esc(st)}">${head(`<button class="btn ghost" type="button" data-upload title="הקלטה נוספת, טקסט או מסמך">${ic("upload")}<span>הוספת קובץ</span></button>`)}
        ${st === "first" ? `<div class="callout mf-firstnote">${ic("refresh")}<span><b>עיבוד ראשון.</b> ההקלטה והכתוביות החיות, מיד כשהפגישה נגמרה. התמלול המלא, הדוברים, הנושאים, ההחלטות והמשימות יחליפו את זה כאן — באותה כתובת.</span></div>` : ""}
        <div class="mf-body">
          <section class="mf-stagecol"><div class="mf-player"></div><div class="mf-transportbox"></div><div class="mf-scrubbox"></div></section>
          <aside class="mf-side">
            <nav class="mf-tabs" role="tablist" aria-label="חלקי הפגישה">${TABS.map(([k, h, i]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="false" aria-controls="mf-p-${k}"><span>${h}</span>${tabBadge(k)}</button>`).join("")}</nav>
            <div class="mf-panes">${TABS.map(([k]) => `<div class="mf-pane" id="mf-p-${k}" role="tabpanel" data-pane="${k}"></div>`).join("")}</div>
          </aside>
          <section class="mf-tlbox" aria-label="ציר הזמן"><div class="mf-tl-resize" role="separator" aria-orientation="horizontal" title="גרירה משנה את גובה ציר הזמן"></div><div class="mf-tlmount"></div></section>
        </div>
        <div class="mf-sheet" hidden role="dialog" aria-modal="true"><div class="mf-sheet-b"><header><b class="mf-sheet-t"></b><button class="mf-tb" type="button" data-close aria-label="סגירה">${ic("x")}</button></header><div class="mf-sheet-c"></div></div></div>
      </div>`;
      bindHead(app);
      const root = app.querySelector(".mf-mtg");
      const tlMount = app.querySelector(".mf-tlmount");
      stage = MF.Stage(M, {
        root, host: app, player: app.querySelector(".mf-player"), transport: app.querySelector(".mf-transportbox"), timeline: tlMount,
        scrub: app.querySelector(".mf-scrubbox"),
      }, {
        base: MF.roomUrl(room), hue, textOf: (x) => (edits[x.id] ? edits[x.id].after : x.text), extraAudio,
        stateOf: (k, x) => { const kind = { decision: "decision", task: "task", question: "question" }[k]; if (!kind) return ""; const arr = { decision: M.decisions, task: M.tasks, question: M.questions }[kind]; const i = arr.indexOf(x); const s = items[`${kind}:${MF.itemId(kind, x, i)}`]; return (s && s.state) || "proposed"; },
        marks: MF.itemsOf("mark", M, items).map((v) => ({ t: v.t, label: v.label, text: MF.MARK[v.label] || "" })),
        onPick: (k, x) => pick(k, x),
      });
      offs.push(() => stage && stage.destroy());
      const ctx = { M, room, title: info.title, stage, hue, items, state: st, people: [...new Set((M.turns || []).map((x) => x.who).filter(Boolean))],
        store: (key, v) => { items[key] = Object.assign({}, items[key] || {}, v || {}); },
        changed: () => { refreshWork(); stage.rebuild(); } };
      tr = MF.Transcript(app.querySelector('[data-pane="tr"]'), { M, stage, room, hue, edits, versions,
        people: (info.people || []).concat(M.people || []),
        onEdit: () => { stage.rebuild(); renderHistory(); },
        onSpeaker: () => { stage.rebuild(); renderOverview(); renderHistory(); },
        onExport: () => { showTab("files", true); setTimeout(() => { const x = app.querySelector(".mf-export"); if (x) { x.scrollIntoView({ block: "center", behavior: "smooth" }); const a = x.querySelector("a"); if (a) a.focus({ preventScroll: true }); } }, 60); },
        onTaskFrom: (x, text) => { showTab("task"); lists.task.addTask({ text, t: x.s, owner: x.who }); } });
      offs.push(() => tr && tr.destroy());
      for (const k of ["decision", "task", "question"]) lists[k] = MF.WorkList(app.querySelector(`[data-pane="${k}"]`), Object.assign({}, ctx, { kind: k }));
      renderOverview(); renderHistory();
      files = MF.Files(app.querySelector('[data-pane="files"]'), { M, room, stage, openDoc, onChange: async () => { try { const u = await MF.api(api("uploads")); uploads = (u && u.uploads) || []; } catch (e) { /* */ } if (screens) screens.refresh(); } });
      if (MF.Screens) {
        screens = MF.Screens(app.querySelector('[data-pane="sc"]'), { M, room, stage, uploads: () => uploads,
          onSeek: () => { if (isPhone()) window.scrollTo({ top: 0, behavior: "smooth" }); },
          onSaved: async () => { try { const u = await MF.api(api("uploads")); uploads = (u && u.uploads) || []; } catch (e) { /* */ } if (files) files.reload(); renderHistory(); } });
        offs.push(() => screens && screens.destroy());
      }
      // the axis: under the screen on a wide screen, a tab of its own on a phone
      placeTimeline();
      on(window, "resize", placeTimeline);
      app.querySelector(".mf-tabs").addEventListener("click", (e) => { const b = e.target.closest("[data-tab]"); if (b) showTab(b.dataset.tab, true); });
      app.querySelector("[data-upload]").onclick = () => { showTab("files", true); setTimeout(() => app.querySelector(".mf-drop input")?.click(), 50); };
      app.querySelector(".mf-sheet").addEventListener("click", (e) => { if (e.target.closest("[data-close]") || e.target.classList.contains("mf-sheet")) closeSheet(); });
      resizeTl();
      const want = where.view && TABS.some(([k]) => k === where.view) ? where.view : MF.store.get("tab", "tr");
      showTab(want === "tl" && !isPhone() ? "tr" : want);
      if (where.t != null) { stage.zoomTo(4); stage.seek(where.t); } else stage.seek(0, { hash: false });
      if (where.q) tr.setQuery(where.q);
      keys();
      on(window, "hashchange", () => { const w = MF.where(); if (w.t != null) stage.seek(w.t); });
    }
    function placeTimeline() {
      const box = app.querySelector(".mf-tlbox"), pane = app.querySelector('[data-pane="tl"]'), mount = app.querySelector(".mf-tlmount");
      if (!box || !mount) return;
      const target = isPhone() ? pane : box;
      if (mount.parentElement !== target) { target.appendChild(mount); if (stage) setTimeout(() => stage.relayout(), 0); }
      app.querySelector('[data-tab="tl"]').hidden = !isPhone();
      if (!isPhone() && app.querySelector('[data-tab="tl"][aria-selected="true"]')) showTab("tr");
    }
    function resizeTl() {
      const h = app.querySelector(".mf-tl-resize"), box = app.querySelector(".mf-tlbox"); if (!h) return;
      const saved = MF.store.get("tlH", 0); if (saved) box.style.setProperty("--tlh", saved + "px");
      h.addEventListener("pointerdown", (e) => {
        h.setPointerCapture(e.pointerId);
        const y0 = e.clientY, h0 = box.getBoundingClientRect().height;
        h.onpointermove = (ev) => { const v = Math.max(140, Math.min(window.innerHeight * 0.7, h0 - (ev.clientY - y0))); box.style.setProperty("--tlh", v + "px"); };
        h.onpointerup = () => { h.onpointermove = null; MF.store.set("tlH", Math.round(box.getBoundingClientRect().height)); stage && stage.relayout(); };
      });
    }
    function showTab(k, user) {
      for (const b of app.querySelectorAll(".mf-tabs [data-tab]")) b.setAttribute("aria-selected", b.dataset.tab === k);
      for (const p of app.querySelectorAll(".mf-pane")) p.classList.toggle("on", p.dataset.pane === k);
      if (user) { MF.store.set("tab", k); MF.setQuery("v", k === "tr" ? "" : k); }
      if (k === "tl" && stage) setTimeout(() => stage.relayout(), 0);
      const sel = app.querySelector(`.mf-tabs [data-tab="${k}"]`); if (sel && sel.scrollIntoView && isPhone()) sel.scrollIntoView({ block: "nearest", inline: "center" });
    }
    function refreshWork() {
      for (const k of Object.keys(lists)) lists[k].render();
      for (const b of app.querySelectorAll(".mf-tabs [data-tab]")) { const n = b.querySelector(".n"); const nb = tabBadge(b.dataset.tab); if (n) n.outerHTML = nb || ""; else if (nb) b.insertAdjacentHTML("beforeend", nb); }
      renderOverview(); renderHistory();
    }
    function pick(k, x) {
      if (["decision", "task", "question"].includes(k)) {
        showTab(k, true);
        const arr = { decision: M.decisions, task: M.tasks, question: M.questions }[k];
        const key = `${k}:${MF.itemId(k, x, arr.indexOf(x))}`;
        const card = app.querySelector(`.mf-pane.on .mf-item[data-key="${CSS.escape(key)}"]`);
        if (card) { card.scrollIntoView({ block: "center", behavior: "smooth" }); card.classList.add("flash"); setTimeout(() => card.classList.remove("flash"), 1600); }
      } else if (k === "frame" || k === "screen") {
        const f = k === "frame" ? x.f : (x.frames || [])[0];
        sheet(k === "screen" ? x.label : `המסך ב-${fmt(x.t)}`, `${f ? `<img class="mf-frame" src="${esc(MF.roomUrl(room, "frames/f/" + f))}" alt="">` : ""}${k === "screen" && x.detail ? `<p dir="auto">${esc(x.detail)}</p>` : ""}<p class="muted small">${fmt(x.s ?? x.t)}${x.e ? "–" + fmt(x.e) : ""}</p>`);
      } else if (k === "topic") {
        showTab("ov", true);
        const n = app.querySelector(`.mf-topic[data-s="${x.s}"]`); if (n) { n.open = true; n.scrollIntoView({ block: "center", behavior: "smooth" }); }
      } else if (k === "turn" && !isPhone()) showTab("tr");
    }
    function sheet(title, html) {
      const s = app.querySelector(".mf-sheet"); s.querySelector(".mf-sheet-t").textContent = title || ""; s.querySelector(".mf-sheet-c").innerHTML = html; s.hidden = false;
      s.querySelector("[data-close]").focus();
    }
    function closeSheet() { const s = app.querySelector(".mf-sheet"); if (s) { s.hidden = true; s.querySelector(".mf-sheet-c").innerHTML = ""; } }
    function openDoc(href) {
      sheet("מסמך", `<iframe class="mf-docframe" src="${esc(MF.roomUrl(room, href))}" title="מסמך"></iframe>`);
      const f = app.querySelector(".mf-docframe");
      f.addEventListener("load", () => {
        try {
          const d = f.contentDocument; app.querySelector(".mf-sheet-t").textContent = d.title || "מסמך";
          d.addEventListener("click", (e) => {
            const a = e.target.closest("a[href]"); if (!a) return;
            const m = a.getAttribute("href").match(/#t=?(\d+(?:\.\d+)?)/);
            if (m) { e.preventDefault(); stage.seek(+m[1]); if (isPhone()) closeSheet(); MF.tell(`קופצים ל-${fmt(+m[1])}`, "ok", { ms: 1500 }); }
          });
        } catch (e) { /* another origin: its links stay its own */ }
      });
    }

    /* ---------- the overview: the meeting in one screen ---------- */
    function renderOverview() {
      const p = app.querySelector('[data-pane="ov"]'); if (!p) return;
      const turns = stage.turns, words = turns.reduce((n, x) => n + String(x.text || "").split(/\s+/).filter(Boolean).length, 0);
      const people = [...new Set(turns.map((x) => x.who).filter(Boolean))];
      const talk = people.map((w) => [w, turns.filter((x) => x.who === w).reduce((n, x) => n + Math.max(0, x.e - x.s), 0)]).sort((a, b) => b[1] - a[1]);
      const tot = talk.reduce((n, x) => n + x[1], 0) || 1;
      const k = (kind) => countOf(kind);
      const marks = MF.itemsOf("mark", M, items);
      const kp = [["משך", MF.fmtLen(M.meeting.duration)], ["שורות", MF.num(turns.length)], ["מילים", MF.num(words)], ["החלטות", MF.num(k("decision").length)], ["משימות", MF.num(k("task").length)], ["שאלות", MF.num(k("question").length)]];
      const sec = (title, n, body, open) => `<details class="mf-sec mf-fold"${open ? " open" : ""}><summary><h3>${title}</h3>${n != null ? `<span class="n">${MF.num(n)}</span>` : ""}${MF.ic("chevronD", "mf-caret")}</summary>${body}</details>`;
      p.innerHTML = `
        <div class="mf-strip">${kp.map(([a, b]) => `<div><span>${a}</span><b>${b}</b></div>`).join("")}</div>
        ${people.length ? `<section class="mf-sec"><h3>מי דיבר כמה</h3><div class="mf-talk">${talk.map(([w, s]) => `<div class="mf-talk-row"><span class="mf-talk-who">${MF.avatar(w, hue(w))}<bdi>${esc(w)}</bdi></span><span class="mf-talk-bar"><i style="--p:${(s / tot) * 100}%;--c:var(--${hue(w)})"></i></span><span class="mf-talk-n" dir="ltr">${Math.round((s / tot) * 100)}%</span></div>`).join("")}</div></section>` : ""}
        ${(M.meeting.docs || []).length ? `<section class="mf-sec"><h3>מסמכים</h3>${M.meeting.docs.map((d) => `<button class="mf-file mf-doc" type="button" data-doc="${esc(d.href)}"><span class="mf-file-ic">${ic("file-text")}</span><div class="mf-file-b"><b dir="auto">${esc(d.title)}</b></div>${ic("chevronL", "mf-go")}</button>`).join("")}</section>` : ""}
        ${(M.topics || []).length ? sec("נושאים לפי הסדר", M.topics.length, `<div class="mf-topics">${M.topics.map((x) => `<details class="mf-topic" data-s="${x.s}"><summary><button class="mf-t" type="button" data-seek="${x.s}"><time dir="ltr">${fmt(x.s)}</time></button><b${MF.dirAttr(x.title)}>${esc(x.title)}</b></summary><div class="mf-topic-b"${MF.dirAttr(x.body)}>${esc(x.body || "")}</div></details>`).join("")}</div>`, true) : ""}
        ${marks.length ? sec("רגעים שסומנו", marks.length, `<ol class="mf-mlist">${marks.map((v) => `<li><button class="mf-t" type="button" data-seek="${v.t}"><time dir="ltr">${fmt(v.t)}</time></button><b>${esc(MF.MARK[v.label] || "סימון")}</b>${v.text ? `<span dir="auto">${esc(v.text)}</span>` : ""}${v.by ? `<span class="muted small">${esc(v.by.name || v.by.username)}</span>` : ""}</li>`).join("")}</ol>`, true) : ""}
        ${(M.likes || []).length ? sec("מה אהבו ומה דחו", M.likes.length, `<ul class="mf-plain">${M.likes.map((x) => `<li><button class="mf-t" type="button" data-seek="${x.t}"><time dir="ltr">${fmt(x.t)}</time></button><span class="mf-tag" data-tone="${x.kind === "rejected" ? "bad" : "ok"}">${x.kind === "rejected" ? "נדחה" : "אהבו"}</span><span${MF.dirAttr(x.text)}>${esc(x.text)}</span></li>`).join("")}</ul>`) : ""}
        ${(M.insights || []).length ? sec("תובנות", M.insights.length, `<ul class="mf-plain">${M.insights.map((x) => `<li><button class="mf-t" type="button" data-seek="${x.t}"><time dir="ltr">${fmt(x.t)}</time></button>${x.kind ? `<span class="mf-tag">${esc(x.kind)}</span>` : ""}<span${MF.dirAttr(x.text)}>${esc(x.text)}</span></li>`).join("")}</ul>`) : ""}
        ${(M.meeting.facts || []).length ? sec("על הנתונים", null, `<dl class="mf-facts col">${M.meeting.facts.map(([a, b]) => `<div><dt>${esc(a)}</dt><dd dir="auto">${esc(b)}</dd></div>`).join("")}</dl>`) : ""}`;
      p.onclick = (e) => {
        const s = e.target.closest("[data-seek]"); if (s) { e.preventDefault(); stage.seek(+s.dataset.seek); return; }
        const d = e.target.closest("[data-doc]"); if (d) openDoc(d.dataset.doc);
      };
    }

    /* ---------- the meeting's lifetime: its stages, and what people did to it ---------- */
    function renderHistory() {
      const p = app.querySelector('[data-pane="hist"]'); if (!p) return;
      const ev = [];
      const tOf = (id) => (stage.turns.find((x) => x.id === id) || {}).s;
      for (const vs of Object.values(versions)) for (const e of vs) ev.push({ at: e.at, who: e.by, what: `תיקן שורה`, detail: e.after, t: tOf(e.target) });
      for (const e of Object.values(whoEdits)) ev.push({ at: e.at, who: e.by, what: "תיקן דובר", detail: `${e.before || "?"} ← ${e.after}`, t: tOf(e.target) });
      for (const [k, v] of Object.entries(items)) if (v.at) ev.push({ at: v.at, who: v.by, what: `${({ approved: "אישר", rejected: "דחה", edited: "ערך", proposed: "פתח מחדש" })[v.state] || "הוסיף"} ${(MF.KIND[k.split(":")[0]] || {}).he || ""}`, detail: (v.fields && v.fields.text) || k.split(":")[1], t: v.fields && v.fields.t != null ? +v.fields.t : null, plane: v.plane });
      for (const u of uploads) if (u.at) ev.push({ at: u.at, who: u.by, what: "הוסיף קובץ", detail: u.label || u.name });
      ev.sort((a, b) => b.at - a.at);
      p.innerHTML = `
        <section class="mf-sec"><h3>שלבי העיבוד</h3><ol class="mf-stages">${(info.stages || []).map((x) => `<li data-st="${esc(x.state)}"><i aria-hidden="true">${x.state === "done" ? ic("tick") : x.state === "running" ? '<span class="mf-spin sm"></span>' : ""}</i><div><b>${esc(MF.STAGE[x.key] || x.key)}</b><span class="muted small">${esc(MF.STAGE_STATE[x.state] || x.state)}${x.detail ? " · " + esc(x.detail) : ""}</span></div></li>`).join("")}</ol></section>
        <section class="mf-sec"><h3>מה נעשה בפגישה הזו</h3>${ev.length ? `<ol class="mf-activity">${ev.slice(0, 200).map((x) => `<li><span class="muted small">${esc(MF.ago(x.at))}</span><b><bdi>${esc((x.who && (x.who.name || x.who.username)) || "מישהו")}</bdi> ${esc(x.what)}</b>${x.t != null ? `<button class="mf-t" type="button" data-seek="${x.t}"><time dir="ltr">${fmt(x.t)}</time></button>` : ""}<span class="mf-act-d" dir="auto">${esc(String(x.detail || "").slice(0, 160))}</span>${x.plane && x.plane.url ? `<a href="${esc(x.plane.url)}" target="_blank" rel="noopener">${esc(x.plane.key || "Plane")}</a>` : ""}</li>`).join("")}</ol>` : '<p class="muted small">עוד אף אחד לא תיקן, אישר או הוסיף כאן דבר.</p>'}</section>`;
      p.onclick = (e) => { const s = e.target.closest("[data-seek]"); if (s) stage.seek(+s.dataset.seek); };
    }

    /* ---------- the keyboard ---------- */
    function keys() {
      on(window, "keydown", (e) => {
        if (e.target.closest && e.target.closest("input, textarea, select, [contenteditable], .bask, dialog")) return;
        if (e.key === "Escape") { closeSheet(); return; }
        if (!stage || e.ctrlKey || e.metaKey || e.altKey) return;
        // by the key's place, not its letter: K / L / J / F are the same keys on a Hebrew keyboard (ל / ך / ח / כ)
        if (e.code === "Space" || e.code === "KeyK") { e.preventDefault(); stage.toggle(); }
        else if (e.key === "ArrowRight") { e.preventDefault(); stage.seek(stage.t + (e.shiftKey ? 30 : 5)); }
        else if (e.key === "ArrowLeft") { e.preventDefault(); stage.seek(stage.t - (e.shiftKey ? 30 : 5)); }
        else if (e.code === "KeyL") stage.seek(stage.t + 10);
        else if (e.code === "KeyJ") stage.seek(stage.t - 10);
        else if (e.key === "+" || e.key === "=") stage.zoomIn();
        else if (e.key === "-") stage.zoomOut();
        else if (e.code === "KeyF") stage.setFollow(!stage.follow);
        else if (e.key === "/" || e.code === "Slash") { e.preventDefault(); showTab("tr"); tr.focusSearch(); }
      });
    }
    function poll(ms, f) { timers.push(setInterval(() => { if (dead || document.hidden) return; const p = f(); if (p && p.catch) p.catch(() => {}); }, ms)); }

    load();
    return { destroy() { dead = true; for (const t of timers) clearInterval(t); for (const f of offs) f(); } };
  };
})();

;
/* «פגישות» — home.js: the centre of the office's meetings and the work they create (…/flow/). What is on now, what
   comes next in each series (and what it inherits: what the meeting before it left open), what waits for a person to
   approve, every meeting by day, and one search over everything that was ever said, decided or assigned. */
(() => {
  "use strict";
  const MF = window.MF;

  MF.Home = function Home(app, where) {
    const { esc, ic, fmt } = MF;
    const timers = [];
    let dead = false, data = null, inbox = null, view = ["meetings", "tasks", "decisions"].includes(where.view) ? where.view : "meetings";
    let hue = MF.people({});
    document.title = "פגישות";

    app.innerHTML = `<div class="pg mf-home">
      <header class="pg-head">
        <div><h1>פגישות</h1><div class="pg-sub">כל פגישה במקום אחד — מההקלטה, דרך כל מילה, ועד ההחלטות והמשימות</div></div>
        <div class="pg-actions"><form class="mf-roomform" data-room-form novalidate><label class="mf-vh" for="mf-room-name">שם החדר</label><input id="mf-room-name" name="room" dir="ltr" autocomplete="off" autocapitalize="off" spellcheck="false" enterkeyhint="go" placeholder="fpg107" aria-describedby="mf-room-err"><button class="btn ghost" type="submit" title="פתיחת החדר בשם הזה, כמארח, בחלון חדש">${ic("video")}<span>פתיחה לפי שם</span></button><output id="mf-room-err" class="mf-room-err" aria-live="polite"></output></form><a class="btn" href="${esc(MF.url("new"))}" target="_blank" rel="noopener" data-new title="פגישה חדשה בחלון חדש">${ic("plus")}<span>פגישה חדשה</span></a></div>
      </header>
      <label class="mf-bigsearch"><span class="mf-vh">חיפוש בכל הפגישות</span>${ic("search")}<input type="search" placeholder="חיפוש בכל הפגישות — מילה, שם, החלטה, משימה" autocomplete="off" enterkeyhint="search" value="${esc(where.q)}"><output class="muted small" aria-live="polite"></output></label>
      <div class="mf-home-body"><div class="mf-loading" role="status"><span class="mf-spin"></span><span>טוען…</span></div></div>
    </div>`;
    const body = app.querySelector(".mf-home-body"), input = app.querySelector(".mf-bigsearch input"), out = app.querySelector(".mf-bigsearch output");
    // «פגישה חדשה»: the host's door with a fresh room (the same as the Meet tile's own button). «פתיחה לפי שם»: a room the
    // office names (fpg107: the series the centre reads), as Jitsi's own welcome page did before the tile opened here
    // (CHAT-67): the host's door r/<room>, in a new window. Jitsi refuses / ? & : " ' % # in a room's name.
    const roomForm = app.querySelector("[data-room-form]");
    roomForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const inp = roomForm.querySelector("input"), err = roomForm.querySelector("output");
      const name = inp.value.normalize("NFKC").trim().toLowerCase();
      if (!name) { err.textContent = "כתבו שם לחדר"; inp.setAttribute("aria-invalid", "true"); inp.focus(); return; }
      if (name.length > 200 || /[\/?&:"'%#\s]/.test(name)) { err.textContent = "בלי רווחים ובלי / ? & : \" ' % #"; inp.setAttribute("aria-invalid", "true"); inp.focus(); return; }
      err.textContent = ""; inp.removeAttribute("aria-invalid");
      window.open(MF.url("r/" + encodeURIComponent(name)), "_blank", "noopener");
    });


    async function load() {
      try {
        const [m, i] = await Promise.all([MF.api("flow/api/meetings"), MF.api("flow/api/inbox?all=1").catch(() => ({ items: [] }))]);
        data = m || { meetings: [], live: [] }; inbox = (i && i.items) || [];
      } catch (e) {
        body.innerHTML = `<div class="callout warn"><b>הפגישות לא נטענו</b><p>${esc(e.message)}</p><button class="btn sm" type="button" data-retry>לנסות שוב</button></div>`;
        body.querySelector("[data-retry]").onclick = load; return;
      }
      if (dead) return;
      const names = {}; for (const m of data.meetings || []) for (const p of m.people || []) names[p] = names[p] || null;
      hue = MF.people(names);
      if (input.value.trim().length >= 2) search(); else render();
    }

    /* ---------- the centre ---------- */
    function render() {
      const ms = data.meetings || [], live = data.live || [];
      const byRoom = Object.fromEntries(ms.map((m) => [m.room, m]));
      const waiting = inbox.filter((r) => r.state === "proposed");
      // what comes next in a series: the newest meeting of a series + 1, when the series has more than one meeting
      const series = {};
      for (const m of ms) if (m.n != null && m.series) (series[m.series] = series[m.series] || []).push(m);
      const next = Object.entries(series).filter(([, a]) => a.length > 1).map(([s, a]) => {
        const last = a.slice().sort((x, y) => y.n - x.n)[0];
        const room = s + (last.n + 1);
        if (byRoom[room] || live.some((l) => l.room === room)) return null;
        const open = inbox.filter((r) => r.room === last.room && r.kind === "task" && r.state !== "approved" && r.state !== "rejected").length;
        return { room, last, open };
      }).filter(Boolean);
      const days = [];
      for (const m of ms) { const d = MF.day(m.start_ts || m.started, data.now); const g = days.find((x) => x.d === d); g ? g.rows.push(m) : days.push({ d, rows: [m] }); }
      const seg = [["meetings", "פגישות", ms.length], ["tasks", "משימות", inbox.filter((r) => r.kind === "task").length], ["decisions", "החלטות", inbox.filter((r) => r.kind === "decision").length]];
      body.innerHTML = `
        ${live.length ? `<section class="mf-home-sec"><h2 class="mf-h2"><i class="mf-pulse"></i>עכשיו בשידור</h2><div class="mf-cards live">${live.map((l) => `
          <article class="mf-card mf-livecard"><div class="mf-livecard-h">${MF.statePill("live")}<b dir="auto">${esc((byRoom[l.room] || {}).title || l.room)}</b></div>
            <p class="muted small">${l.since ? `התחילה ${esc(MF.ago(l.since))}` : ""}${l.people ? ` · ${MF.num(l.people)} משתתפים` : ""}${l.recording === "on" ? " · מוקלטת" : ""}</p>
            ${(l.names || []).length ? `<div class="mf-people">${l.names.slice(0, 8).map((n) => MF.avatar(n, hue(n))).join("")}<span class="mf-people-n">${esc(l.names.slice(0, 3).join(", "))}</span></div>` : ""}
            <footer><a class="btn sm" href="${esc(MF.url("r/" + encodeURIComponent(l.room)))}" target="_blank" rel="noopener">${ic("video")}<span>הצטרפות</span></a><a class="btn sm ghost" href="${esc(MF.roomUrl(l.room))}" data-go>${ic("eye")}<span>צפייה חיה</span></a></footer></article>`).join("")}</div></section>` : ""}
        ${next.length ? `<section class="mf-home-sec"><h2 class="mf-h2">${ic("calendar")}הבאה בתור</h2><div class="mf-cards">${next.map((x) => `
          <a class="mf-card mf-nextcard" href="${esc(MF.roomUrl(x.room))}" data-go><span class="mf-next-room" dir="ltr">${esc(x.room)}</span>
            <span class="muted small">אחרי ${esc(x.last.title || x.last.room)}${x.open ? ` · ${MF.num(x.open)} משימות פתוחות ממנה` : ""}</span><span class="mf-next-go">הכנה ופתיחה ${ic("chevronL")}</span></a>`).join("")}</div></section>` : ""}
        ${waiting.length ? `<section class="mf-home-sec"><h2 class="mf-h2">${ic("inbox")}ממתין לאישור<span class="n wait">${MF.num(waiting.length)}</span></h2>
          <div class="mf-items mf-inbox">${waiting.slice(0, 4).map((r) => card(r, byRoom)).join("")}</div>
          ${waiting.length > 4 ? `<button class="btn sm ghost" type="button" data-view="tasks">לכל ${MF.num(waiting.length)} הממתינים</button>` : ""}</section>` : ""}
        <section class="mf-home-sec">
          <div class="mf-seg mf-homeseg" role="tablist" aria-label="תצוגה">${seg.map(([k, h, n]) => `<button type="button" role="tab" data-view="${k}" aria-selected="${view === k}">${h}<span class="n">${MF.num(n)}</span></button>`).join("")}</div>
          <div class="mf-home-view"></div>
        </section>`;
      const v = body.querySelector(".mf-home-view");
      if (view === "meetings") v.innerHTML = days.length ? days.map((g) => `<div class="mf-day"><h3 class="mf-day-h">${esc(g.d)}</h3><div class="mf-rows">${g.rows.map(row).join("")}</div></div>`).join("")
        : `<div class="mf-empty big">${ic("video")}<p><b>עוד אין פגישות.</b> פגישה שמוקלטת מופיעה כאן מעצמה — בשידור בזמן שהיא מתקיימת, ואחריה עם ההקלטה והתמלול.</p><a class="btn" href="${esc(MF.url("new"))}" target="_blank" rel="noopener">${ic("plus")}<span>פגישה ראשונה</span></a></div>`;
      else work(v, view === "tasks" ? "task" : "decision", byRoom);
    }
    function row(m) {
      const c = m.counts || {};
      const st = MF.STATE[m.state] || {};
      return `<a class="mf-row" href="${esc(MF.roomUrl(m.room))}" data-go data-state="${esc(m.state)}">
        <span class="mf-row-time" dir="ltr">${esc(MF.clock(m.start_ts || m.started))}</span>
        <span class="mf-row-main"><b dir="auto">${esc(m.title || m.room)}</b>
          <span class="mf-row-meta">${m.length_min ? `<span>${esc(MF.fmtLen(m.length_min * 60))}</span>` : ""}${(m.people || []).length ? `<span class="mf-people sm">${m.people.slice(0, 4).map((p) => MF.avatar(p, hue(p))).join("")}<span class="mf-people-n">${esc(m.people.slice(0, 3).join(", "))}</span></span>` : ""}${(m.tags || []).filter((t) => t[1] === "bad").map((t) => `<span class="mf-tag" data-tone="bad">${esc(t[0])}</span>`).join("")}</span></span>
        <span class="mf-row-counts">${c.decisions ? `<span title="החלטות">${ic("flag")}${MF.num(c.decisions)}</span>` : ""}${c.tasks ? `<span title="משימות">${ic("task")}${MF.num(c.tasks)}</span>` : ""}${c.proposed ? `<span class="wait" title="ממתינים לאישור">${MF.num(c.proposed)} ממתינים</span>` : ""}</span>
        <span class="mf-state" data-tone="${esc(st.tone || "muted")}" title="${esc(st.hint || "")}">${st.tone === "live" ? '<i class="mf-pulse"></i>' : ""}${esc(st.he || m.state)}</span>
        ${ic("chevronL", "mf-go")}
      </a>`;
    }
    function card(r, byRoom) {
      const meet = byRoom[r.room] || { room: r.room, title: r.title || r.room };
      const v = MF.itemView(r.kind, Object.assign({ id: r.id, who: r.owner }, r), 0, {});
      v.state = r.state === "edited" ? "proposed" : r.state || "proposed"; v.plane = r.plane || null;
      if (r.fields) { if (r.fields.text) v.text = r.fields.text; if (r.fields.owner) v.owner = r.fields.owner; if (r.fields.due) v.due = r.fields.due; v.edited = true; }
      return MF.itemCard(v, { meeting: meet, compact: true });
    }
    function work(v, kind, byRoom) {
      let f = MF.store.get("hw:" + kind, "proposed");
      const draw = () => {
        const rows = inbox.filter((r) => r.kind === kind);
        const n = (s) => rows.filter((r) => (s === "all" ? true : (r.state === "edited" ? "proposed" : r.state) === s)).length;
        const shown = rows.filter((r) => f === "all" || (r.state === "edited" ? "proposed" : r.state) === f);
        v.innerHTML = `<div class="mf-work-bar"><div class="mf-seg sm" role="tablist">${[["proposed", "ממתין"], ["approved", "אושרו"], ["rejected", "נדחו"], ["all", "הכול"]].map(([s, h]) => `<button type="button" role="tab" data-hf="${s}" aria-selected="${f === s}">${h}<span class="n">${MF.num(n(s))}</span></button>`).join("")}</div></div>
          <div class="mf-items">${shown.slice(0, 300).map((r) => card(r, byRoom)).join("") || `<div class="mf-empty">${ic(kind === "task" ? "task" : "flag")}<p>${rows.length ? "אין פריטים במצב הזה." : kind === "task" ? "עוד אין משימות מפגישות." : "עוד אין החלטות מפגישות."}</p></div>`}</div>`;
      };
      v.onclick = (e) => { const b = e.target.closest("[data-hf]"); if (b) { f = b.dataset.hf; MF.store.set("hw:" + kind, f); draw(); } };
      draw();
    }
    // approve / reject / edit from the centre: the same cards and the same server calls as inside a meeting
    MF.bindItems(body, (cardEl) => {
      const room = cardEl && cardEl.dataset.room;
      return {
        room, stage: null, people: [],
        find: (key) => { const [kind, id] = key.split(":"); const r = inbox.find((x) => x.room === room && x.kind === kind && String(x.id) === id); return r ? Object.assign(MF.itemView(kind, Object.assign({ id: r.id, who: r.owner }, r), 0, {}), { state: r.state === "edited" ? "proposed" : r.state }) : null; },
        store: (key, item) => { const [kind, id] = key.split(":"); const r = inbox.find((x) => x.room === room && x.kind === kind && String(x.id) === id); if (r && item) { r.state = item.state || r.state; if (item.plane) r.plane = item.plane; if (item.fields) r.fields = item.fields; } },
        changed: () => render(),
      };
    });
    body.addEventListener("click", (e) => { const b = e.target.closest("[data-view]"); if (b) { view = b.dataset.view; MF.setQuery("v", view === "meetings" ? "" : view); render(); body.querySelector(".mf-homeseg")?.scrollIntoView({ block: "start", behavior: "smooth" }); } });

    /* ---------- one search over every meeting ---------- */
    let qt = 0, ctl = null;
    async function search() {
      const q = input.value.trim();
      MF.setQuery("q", q);
      if (q.length < 2) { out.textContent = ""; if (data) render(); return; }
      if (ctl) ctl.abort(); ctl = new AbortController();
      out.textContent = "מחפש…";
      let r;
      try { r = await MF.api("flow/api/search?q=" + encodeURIComponent(q), { signal: ctl.signal }); } catch (e) { if (e.name === "AbortError") return; out.textContent = e.message; return; }
      const hits = (r && r.hits) || [];
      out.textContent = hits.length ? `${MF.num(r.total || hits.length)} תוצאות` : "לא נמצא";
      const groups = [];
      for (const h of hits) { const g = groups.find((x) => x.room === h.room); g ? g.hits.push(h) : groups.push({ room: h.room, title: h.title, hits: [h] }); }
      const KH = { line: "נאמר", decision: "החלטה", task: "משימה", question: "שאלה" };
      const words = MF.norm(q).split(/\s+/).filter(Boolean);
      const mark = (s) => { let h = esc(s); for (const w of words) { const n = MF.norm(h); if (n.length !== h.length) continue; let o = "", from = 0, at; while ((at = n.indexOf(w, from)) >= 0) { o += h.slice(from, at) + "<mark>" + h.slice(at, at + w.length) + "</mark>"; from = at + w.length; } h = o + h.slice(from); } return h; };
      body.innerHTML = groups.length ? groups.map((g) => `<section class="mf-home-sec mf-hits"><h2 class="mf-h2"><a href="${esc(MF.roomUrl(g.room))}" data-go>${esc(g.title || g.room)}</a><span class="n">${MF.num(g.hits.length)}</span></h2>
        <ol class="mf-hitlist">${g.hits.slice(0, 40).map((h) => `<li><a href="${esc(MF.roomUrl(h.room) + (h.kind === "line" ? "?q=" + encodeURIComponent(q) : "?v=" + h.kind) + "#t" + Math.floor(h.t || 0))}" data-go>
          <time dir="ltr">${fmt(h.t || 0)}</time><span class="mf-tag">${KH[h.kind] || h.kind}</span>${h.who ? `<b class="mf-who" data-hue="${esc(hue(h.who))}"><bdi>${esc(h.who)}</bdi></b>` : ""}<span class="mf-hit-tx"${MF.dirAttr(h.text)}>${mark(h.text)}</span></a></li>`).join("")}</ol>
        ${g.hits.length > 40 ? `<p class="muted small">ועוד ${MF.num(g.hits.length - 40)} בפגישה הזו — חפשו בתוכה.</p>` : ""}</section>`).join("")
        : `<div class="mf-empty big">${ic("search")}<p>לא נמצא «${esc(q)}» באף פגישה.</p></div>`;
    }
    input.addEventListener("input", () => { clearTimeout(qt); qt = setTimeout(search, 250); });
    input.addEventListener("keydown", (e) => { if (e.key === "Escape") { input.value = ""; search(); } });
    window.addEventListener("keydown", function slash(e) { if (dead) { window.removeEventListener("keydown", slash); return; } if ((e.key === "/" || e.code === "Slash") && !e.target.closest("input, textarea")) { e.preventDefault(); input.focus(); } });

    load();
    timers.push(setInterval(() => { if (!dead && !document.hidden && input.value.trim().length < 2) load(); }, 30000));
    return { destroy() { dead = true; for (const t of timers) clearInterval(t); if (ctl) ctl.abort(); } };
  };
  MF.start();
})();

;
