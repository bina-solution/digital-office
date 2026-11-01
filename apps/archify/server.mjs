// archify — the office's diagrams, rendered from the sources this repository keeps.
//
// ONE job: every `<name>.<type>.json` under DIAGRAMS is rendered by the pinned Archify CLI into a
// self-contained page, and this serves the list and the pages. The SOURCE is the truth (it is in
// git, reviewed like code); nothing here is edited by hand and nothing is stored — a restart
// re-renders everything, and a source that changed is re-rendered the next time anyone looks.
//
// A diagram that does not validate is not hidden: its card says what the validator said. A gallery
// that silently drops the diagram somebody just wrote is how "the docs" stop being trusted.
import { execFile } from "node:child_process";
import { createServer } from "node:http";
import { mkdir, readdir, readFile, stat } from "node:fs/promises";
import { join } from "node:path";

const DIAGRAMS = process.env.ARCHIFY_DIAGRAMS || "/diagrams";
const OUT = process.env.ARCHIFY_OUT || "/tmp/archify-out";
const CLI = process.env.ARCHIFY_CLI || "/opt/archify/bin/archify.mjs";
const PORT = Number(process.env.PORT || 8080);
const TYPES = ["architecture", "workflow", "sequence", "dataflow", "lifecycle"];
const TYPE_HE = { architecture: "ארכיטקטורה", workflow: "תהליך", sequence: "רצף", dataflow: "זרימת נתונים", lifecycle: "מחזור חיים" };
const SOURCE = /^([a-z0-9][a-z0-9-]*)\.(architecture|workflow|sequence|dataflow|lifecycle)\.json$/;

/** name -> { name, type, file, mtime, title, subtitle, ok, problems[] } */
const rendered = new Map();
/** name -> { title, subtitle } — what a diagram is CALLED on this screen, in the screen's language
 *  (`diagrams/he.json`, beside the sources). A diagram is an English document and stays one; its
 *  row in a Hebrew list had been an English sentence in another typeface. One with no entry here
 *  shows its own title, set as what it is: a left-to-right token. */
let HE = {};
let pass = Promise.resolve();

const cli = (args) => new Promise((resolve) => {
  execFile(process.execPath, [CLI, ...args], { timeout: 120000, maxBuffer: 8 << 20 },
    (err, stdout, stderr) => resolve({ code: err ? (err.code ?? 1) : 0, out: String(stdout), err: String(stderr) }));
});

/** The validator's own sentences, once each — it prints every finding several times. */
const sentences = (text) => [...new Set(text.split("\n").map((l) => l.replace(/^\s*(?:-|\[[^\]]+\])\s*/, "").trim())
  .filter((l) => l && !/^(?:Sequence|Architecture|Workflow|Dataflow|Lifecycle) layout validation failed/.test(l)))].slice(0, 6);

async function renderOne(file) {
  const [, name, type] = file.match(SOURCE);
  const src = join(DIAGRAMS, file);
  const mtime = (await stat(src)).mtimeMs;
  const had = rendered.get(name);
  if (had && had.mtime === mtime) return;
  const entry = { name, type, file, mtime, title: name, subtitle: "", ok: false, problems: [] };
  try {
    const meta = JSON.parse(await readFile(src, "utf8")).meta || {};
    entry.title = String(meta.title || name);
    entry.subtitle = String(meta.subtitle || "");
  } catch (e) {
    entry.problems = [`the source is not JSON: ${e.message}`];
    rendered.set(name, entry);
    return;
  }
  const checked = await cli(["validate", type, src]);
  if (checked.code !== 0) {
    entry.problems = sentences(checked.err + "\n" + checked.out);
    rendered.set(name, entry);
    return;
  }
  const made = await cli(["render", type, src, join(OUT, `${name}.html`)]);
  entry.ok = made.code === 0;
  if (!entry.ok) entry.problems = sentences(made.err + "\n" + made.out);
  rendered.set(name, entry);
}

/** One pass over the sources. Serialized: two readers asking at once share one pass. */
function refresh() {
  pass = pass.then(async () => {
    await mkdir(OUT, { recursive: true });
    let files = [];
    try { files = (await readdir(DIAGRAMS)).filter((f) => SOURCE.test(f)).sort(); } catch { /* no sources yet */ }
    const names = new Set(files.map((f) => f.match(SOURCE)[1]));
    for (const name of [...rendered.keys()]) if (!names.has(name)) rendered.delete(name);
    for (const f of files) await renderOne(f);
    try { HE = JSON.parse(await readFile(join(DIAGRAMS, "he.json"), "utf8")); } catch { HE = {}; }
  }).catch(() => {});
  return pass;
}

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const list = () => [...rendered.values()].sort((a, b) => TYPES.indexOf(a.type) - TYPES.indexOf(b.type) || a.title.localeCompare(b.title));

const STYLE = `
:root{--mono:ui-monospace,Menlo,Consolas,monospace}   /* the colours are the office's palette, in the block below */
/* @bina-theme-tokens:start */
/* OLIVE GROVE — the one palette of the office (the owner, 2026-10-07 · DGO-450). Four hues, sampled
   from his mock-up, and the ground they stand on. A screen never writes a colour: it names one of
   these. Each hue is the colour itself (a FILL — a button, a bar, a dot), «-d» for text and thin
   lines on the ground (4.5:1 or more), «-soft» and «-line» for a tint and its hairline, and «-ink»
   for what is written ON the fill. The role names every screen already uses point at them:
   (no backtick in this block: one of its copies lives inside a script's template string)
     olive  the brand and the main action · what is well, what is done
     sky    what is in motion, what only informs · a link
     lime   look here — a warning, something waiting
     plum   a person must act — a failure, a removal, the one final action
   Contrast, measured (WCAG): ink on the ground 13.7 · muted 4.65 · light text on olive 5.51 and on
   plum 9.54 · ink on lime 6.88 · its ink on sky 6.32 · sky-d 4.61 · lime-d 4.70 · violet 5.32 ·
   on the desk: its ink 6.32 (dark: 13.96), and 11.2 where the sky pales (dark: 5.12). */
:root,:root[data-theme="light"]{
  color-scheme:light;
  accent-color:var(--accent);   /* the browser's OWN controls - a checkbox, a radio, a range, a progress bar - on both grounds: said once, here (it was said for eight single controls, and every other one was the browser's blue) */
  --bg:#f3f5f7; --surface:#fff; --surface-2:#f9fafb; --ink:#1f2a17; --muted:#6a7068; --line:#dcdfde;
  --olive:#56693f; --olive-d:#475734; --olive-soft:#e7eae4; --olive-line:#bfc6b6; --olive-ink:#f3f5f7;
  --sky:#7baae3; --sky-d:#2a6fc4; --sky-soft:#edf3fb; --sky-line:#cddff4; --sky-ink:#13263f;
  --lime:#a9b84c; --lime-d:#69732e; --lime-soft:#f3f5e6; --lime-line:#dee4bb; --lime-ink:#1f2a17;
  --plum:#5b3349; --plum-d:#4a303b; --plum-soft:#e8e2e6; --plum-line:#c1b1ba; --plum-ink:#f3f5f7;
  --accent:var(--olive); --accent-d:var(--olive-d); --accent-soft:var(--olive-soft); --accent-ink:var(--olive-ink);
  --blue:var(--sky-d); --amber:var(--lime-d); --red:var(--plum);
  --violet:#7c5c6d;   /* plum, lifted a fifth toward white: someone has to look — nothing has failed */
  --ok:var(--olive); --warn:var(--lime-d); --danger:var(--plum); --info:var(--sky-d);
  --ok-soft:var(--olive-soft); --warn-soft:var(--lime-soft); --danger-soft:var(--plum-soft); --info-soft:var(--sky-soft);
  --red-soft:var(--plum-soft); --amber-soft:var(--lime-soft); --blue-soft:var(--sky-soft); --violet-soft:var(--plum-soft);
  --side:var(--olive); --side-ink:#f3f5f7; --side-mut:#dce1da; --side-line:#788765;
  --desk:var(--sky); --desk-ink:var(--sky-ink);   /* desktop mode's ground is the sky (the owner, DGO-452), and what is written straight on it */
  --scrim:rgba(31,42,23,.5);                      /* what dims a screen behind a pop-up */
  --shadow:0 1px 3px rgba(31,42,23,.08),0 6px 24px rgba(31,42,23,.06);
  --shadow-lg:0 20px 60px rgba(31,42,23,.28);
  /* ONE COLOUR AND ONE ANIMAL PER OFFICE (the owner, 2026-10-09 · flt-002). When offices are linked,
     a person reads WHICH office a thing belongs to without opening it, so each office gets a hue of
     its own. The hue is an IDENTITY and never a health state: an office that stopped answering keeps
     its colour, and the quiet mark is the one that says "not answering". Each is an ALIAS of the
     palette's own hue — no fourth value is invented, and because the ground re-points the hue, the
     office mark follows the ground by itself. Each office's animal (elephant, deer, eagle) is a
     glyph of bina-icons.js. */
  --office-hp:var(--muted);   /* hp · elephant — grey: the heavy laptop at home, in the palette's own grey */
  --office-mac:var(--lime);   /* macbook · deer — yellow: the palette has one yellow and it is lime. A FILL, so what is written ON it is --lime-ink, never this */
  --office-vps:var(--sky-d);  /* vps · eagle — deep sky blue, «the eagle in the clouds». THE OWNER'S OWN CHOICE (2026-10-09, in writing: vps = נשר + כחול-שמיים) — this line is the colour he picked, not a default kept for him */
}

/* ── A LINKED OFFICE'S MARK, BY NAME (flt-004) ───────────────────────────────────────────────
   The link carries a NAME — mark: {color, animal} in the catalog, from the office's own identity
   — and never a value: the office that DRAWS a linked tile owns the pixels, so it paints the name
   with its own palette. These seven rules are that translation, one per family above; a screen sets
   data-office-hue="lime" and paints var(--office-hue).
   A name this file does not know paints nothing, which is why the vocabulary in
   apps/dgo-extend/identity.py may only name families that exist here — and why --red and --ok
   are not among them: they mean «danger» and «it is well» on every screen in the office. */
[data-office-hue="grey"]   { --office-hue:var(--muted); }
[data-office-hue="lime"]   { --office-hue:var(--lime); }
[data-office-hue="sky"]    { --office-hue:var(--sky-d); }
[data-office-hue="olive"]  { --office-hue:var(--olive-d); }
[data-office-hue="plum"]   { --office-hue:var(--plum); }
[data-office-hue="blue"]   { --office-hue:var(--blue); }
[data-office-hue="violet"] { --office-hue:var(--violet); }
/* the dark ground is the same four hues on the palette's own ink, and the SAME legend. Olive on that
   ink is 2.5:1, so its text step there is olive LIFTED — its own hue and saturation, lighter (7.14
   on a card, 4.82 on its own tint) — and the brand, the main action and «it is well» take that step.
   Lime stays «look here» and the sky «in motion», as on the light ground: were lime the accent here
   (it was, for a day), a warning, a selection and «it is well» were one colour. Each «-d» on its
   own «-soft» there, measured: olive 4.82 · sky 4.62 · lime 4.63 · plum 4.71. */
@media (prefers-color-scheme:dark){
  :root{ color-scheme:dark;
         --bg:#141b0f; --surface:#1f2a17; --surface-2:#192213; --ink:#f3f5f7; --muted:#a2a8a2; --line:#414a3b;
         --olive-d:#a5ba8c; --olive-soft:#384629; --olive-line:#56693f;
         --sky-d:#7baae3; --sky-soft:#2e3f38; --sky-line:#4d6a8c;
         --lime-d:#a9b84c; --lime-soft:#3b4622; --lime-line:#69732e;
         --plum-d:#ad99a4; --plum-soft:#402f33; --plum-line:#7c5c6d;
         --accent:var(--olive-d); --accent-ink:var(--surface);
         --red:#ad99a4; --violet:#bdadb6; --danger:#ad99a4; --ok:var(--olive-d); --side:var(--surface);
         --desk:var(--sky-ink); --desk-ink:var(--ink); --scrim:rgba(0,0,0,.6);
         --shadow:0 1px 3px rgba(0,0,0,.4),0 6px 24px rgba(0,0,0,.3);
         --shadow-lg:0 20px 60px rgba(0,0,0,.55); }
}
:root[data-theme="midnight"]{
  color-scheme:dark;
  --bg:#141b0f; --surface:#1f2a17; --surface-2:#192213; --ink:#f3f5f7; --muted:#a2a8a2; --line:#414a3b;
  --olive-d:#a5ba8c; --olive-soft:#384629; --olive-line:#56693f;
  --sky-d:#7baae3; --sky-soft:#2e3f38; --sky-line:#4d6a8c;
  --lime-d:#a9b84c; --lime-soft:#3b4622; --lime-line:#69732e;
  --plum-d:#ad99a4; --plum-soft:#402f33; --plum-line:#7c5c6d;
  --accent:var(--olive-d); --accent-ink:var(--surface);
  --red:#ad99a4; --violet:#bdadb6; --danger:#ad99a4; --ok:var(--olive-d); --side:var(--surface);
  --desk:var(--sky-ink); --desk-ink:var(--ink); --scrim:rgba(0,0,0,.6);
  --shadow:0 1px 3px rgba(0,0,0,.4),0 6px 24px rgba(0,0,0,.3);
  --shadow-lg:0 20px 60px rgba(0,0,0,.55);
}
/* THE KEYBOARD'S RING - what the browser draws around the stop the keyboard is on, in the palette, wherever
   a part draws none of its own. It has no specificity at all (:where), so any rule of a part wins. Two
   screens said this for themselves; on the others nearly every stop wore the browser's ring (DGO-455).
   A field keeps the offset it has - fourteen rules draw a field's own outline and say no offset. An area
   (a scroll box, a table) takes the ring inside, where nothing clips it; a control takes it outside,
   where a filled button does not hide it. */
:where(:focus-visible){outline:2px solid var(--accent)}
:where(:focus-visible:not(a,button,summary,[role=button],input,select,textarea)){outline-offset:-2px}
:where(a,button,summary,[role=button]):focus-visible{outline-offset:2px}
/* HEBREW AT A HEAVY WEIGHT - on Windows, where the first family of --font is installed. "Segoe UI" has its
   Hebrew in Light, Regular, Semibold and Bold. Asked for 800 or 900 the browser takes the family's Black
   face, which has none, and so has every family after it - so the Hebrew of every title at 800 was drawn in
   the system's last-resort serif, thin, beside Latin in Black: «חשבונות ומראות» at 20px is 150px wide at 700
   and 120px at 800 (Chrome 154; the screens ask for 800 in 167 places, the question's title among them).
   These faces give the family's HEBREW RANGE the faces that have it. A family a sheet names is no longer the
   system's for those characters, so every weight and both styles are named, each as the system resolves it:
   measured, only upright 800 and 900 change. Any other character is not theirs and goes on to the next
   family the screen names - system-ui in --font, on Windows the same faces, Black included - which is why
   G27 asks that system-ui follows wherever a screen names this family itself. Where the family is not
   installed nothing here resolves and nothing changes. */
@font-face{font-family:"Segoe UI";src:local("Segoe UI Light");font-weight:100 300;unicode-range:U+0590-05FF,U+FB1D-FB4F}
@font-face{font-family:"Segoe UI";src:local("Segoe UI");font-weight:400;unicode-range:U+0590-05FF,U+FB1D-FB4F}
@font-face{font-family:"Segoe UI";src:local("Segoe UI Semibold");font-weight:500 600;unicode-range:U+0590-05FF,U+FB1D-FB4F}
@font-face{font-family:"Segoe UI";src:local("Segoe UI Bold");font-weight:700 900;unicode-range:U+0590-05FF,U+FB1D-FB4F}
@font-face{font-family:"Segoe UI";src:local("Segoe UI Light Italic");font-weight:100 300;font-style:italic;unicode-range:U+0590-05FF,U+FB1D-FB4F}
@font-face{font-family:"Segoe UI";src:local("Segoe UI Italic");font-weight:400;font-style:italic;unicode-range:U+0590-05FF,U+FB1D-FB4F}
@font-face{font-family:"Segoe UI";src:local("Segoe UI Semibold Italic");font-weight:500 600;font-style:italic;unicode-range:U+0590-05FF,U+FB1D-FB4F}
@font-face{font-family:"Segoe UI";src:local("Segoe UI Bold Italic");font-weight:700 900;font-style:italic;unicode-range:U+0590-05FF,U+FB1D-FB4F}
/* @bina-theme-tokens:end */
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--ink);font:13px/1.55 "Segoe UI",system-ui,-apple-system,"Noto Sans Hebrew","Assistant",Arial,sans-serif}
.band{padding:22px 26px 14px}.band h1{margin:0;font-size:22px;font-weight:800}.band p{margin:4px 0 0;color:var(--muted)}
/* A LIST, not a grid of cards: the number of diagrams is whatever the repository holds, and a
   grid of N cards leaves one alone on its row for most N. Rows read the same at any count. */
.list{margin:6px 26px 26px;background:var(--surface);border:1px solid var(--line);border-radius:16px;overflow:hidden}
.row{display:grid;grid-template-columns:112px minmax(0,1fr) auto;gap:4px 14px;align-items:center;padding:12px 16px;border-top:1px solid var(--line)}
.row:first-child{border-top:0}
.what{min-width:0}
.what.raw,.bar b.raw{direction:ltr;unicode-bidi:isolate;text-align:right}
/* A title is never cut: in a console WINDOW the list is 650px wide, and "Moving an app to a linked o…"
   is not a title. It wraps, and the row grows. */
.what b{display:block;font-size:16px;font-weight:800}
.sub{display:block;color:var(--muted);font-size:12px}
.pill{justify-self:start;font-size:11.5px;padding:2px 10px;border-radius:999px;border:1px solid var(--line);background:var(--bg);color:var(--muted);white-space:nowrap}
.pill.bad{border-color:var(--plum-line);background:var(--danger-soft);color:var(--red)}
.btn{display:inline-flex;align-items:center;gap:6px;height:30px;padding:0 14px;border-radius:9px;border:1px solid var(--line);background:var(--surface);
  color:var(--ink);font:inherit;font-weight:600;text-decoration:none;cursor:pointer}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}.btn:hover{border-color:var(--muted)}
.src{font-family:var(--mono);font-size:11.5px;color:var(--muted);direction:ltr;unicode-bidi:isolate;white-space:nowrap}
.why{margin:2px 0 0;padding:0;list-style:none;font-family:var(--mono);font-size:11.5px;color:var(--amber);white-space:normal}
.empty{text-align:center;color:var(--muted);padding:48px 20px}
.bar{display:flex;align-items:center;gap:12px;padding:10px 16px;background:var(--surface);border-bottom:1px solid var(--line);height:52px}
.bar b{font-size:14px}
.frame{display:block;width:100%;height:calc(100% - 52px);border:0;background:var(--surface)}
@media (max-width:760px){.band{padding:16px 14px 10px}.list{margin:6px 14px 18px}
  .row{grid-template-columns:minmax(0,1fr) auto}.row .what{grid-column:1/-1}.row .btn{grid-column:2;grid-row:1}}
/* A short frame — a window in desktop mode: the title is one line and the sentence under it steps
   aside. In the smallest window they were two thirds of it, over one row of the list. */
@media (max-height:699px){.band{padding-block:10px 4px}.band h1{font-size:17px}.band p{display:none}
  .list{margin-top:4px}.row{padding-block:8px}}`;

const page = (title, body) => `<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>${esc(title)}</title><style>${STYLE}</style></head><body>${body}</body></html>`;

/** What a diagram is called here, and whether that is its own (untranslated) title. */
const called = (d) => ({ title: d.title, subtitle: d.subtitle, raw: !HE[d.name], ...(HE[d.name] || {}) });

function indexPage(P) {
  const rows = list().map((d) => ({ d, c: called(d) })).map(({ d, c }) => d.ok
    ? `<article class="row"><span class="pill">${TYPE_HE[d.type]}</span>
        <span class="what${c.raw ? " raw" : ""}" title="${esc(d.title)} — ${esc(d.subtitle)} · קובץ המקור: ${esc(d.file)}"><b>${esc(c.title)}</b><span class="sub">${esc(c.subtitle)}</span></span>
        <a class="btn" href="${P}/v/${esc(d.name)}" title="פתיחת התרשים «${esc(c.title)}»">פתיחה</a></article>`
    : `<article class="row"><span class="pill bad" title="קובץ המקור לא עבר את הבדיקה של Archify">לא נוצר</span>
        <span class="what${c.raw ? " raw" : ""}"><b>${esc(c.title)}</b>
          <span class="src" title="קובץ המקור במאגר">${esc(d.file)}</span>
          <ul class="why" title="מה שהבודק של Archify אמר על קובץ המקור">${d.problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul></span>
        <span></span></article>`).join("");
  return page("ארכיטקטורה", `<header class="band"><h1>ארכיטקטורה</h1>
    <p>התרשימים של הלשכה ושל האפליקציות שלה. כל תרשים נוצר מקובץ מקור שבמאגר — מתקנים את הקובץ, והתרשים מתעדכן.</p></header>
    <main class="list">${rows || `<div class="empty">עוד אין תרשימים. קובץ מקור ראשון ב-<span class="src">apps/archify/diagrams/</span> יופיע כאן.</div>`}</main>`);
}

function viewerPage(d, P) {
  const c = called(d);
  return page(c.title, `<div class="bar"><a class="btn" href="${P}/" title="חזרה לרשימת התרשימים">חזרה</a><b${c.raw ? ' class="raw"' : ""}>${esc(c.title)}</b>
    <span class="src" title="קובץ המקור במאגר">${esc(d.file)}</span></div>
    <iframe class="frame" src="${P}/d/${esc(d.name)}.html" title="${esc(d.title)}"></iframe>`);
}

const send = (res, code, type, body, more = {}) => {
  res.writeHead(code, { "Content-Type": type, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", ...more });
  res.end(body);
};
// A rendered diagram is a page of scripts a tool made from a source file, and a console shows it on
// the console's OWN origin. So it is served sandboxed: its scripts run (the diagram is interactive)
// as an origin of its own, with no way to the console's session, its storage or its API. The page
// expects exactly this — it guards every `localStorage` call "for sandboxed iframes".
const SANDBOXED = { "Content-Security-Policy": "sandbox allow-scripts allow-downloads allow-popups" };

createServer(async (req, res) => {
  const path = decodeURIComponent(new URL(req.url, "http://x").pathname);
  // WHERE THIS APP IS MOUNTED, as whoever is in front says: nothing at its own host, `/a/<alias>` under
  // a console (which may be another office's). Every link is written from it, because a page framed
  // by a console gets that console's base address and a relative link would resolve against THAT.
  const P = String(req.headers["x-forwarded-prefix"] || "").replace(/[^A-Za-z0-9._\/-]/g, "").replace(/\/+$/, "");
  if (path === "/healthz") return send(res, 200, "application/json", JSON.stringify({ ok: true, diagrams: rendered.size }));
  await refresh();
  if (path === "/api/diagrams") {
    return send(res, 200, "application/json", JSON.stringify({ diagrams: list().map(({ mtime, ...d }) => d) }));
  }
  if (path === "/" || path === "/index.html") return send(res, 200, "text/html; charset=utf-8", indexPage(P));
  let m = path.match(/^\/v\/([a-z0-9][a-z0-9-]*)$/);
  if (m && rendered.get(m[1])?.ok) return send(res, 200, "text/html; charset=utf-8", viewerPage(rendered.get(m[1]), P));
  m = path.match(/^\/d\/([a-z0-9][a-z0-9-]*)\.html$/);
  if (m && rendered.get(m[1])?.ok) {
    try { return send(res, 200, "text/html; charset=utf-8", await readFile(join(OUT, `${m[1]}.html`)), SANDBOXED); } catch { /* falls through */ }
  }
  send(res, 404, "text/html; charset=utf-8", page("לא נמצא", `<header class="band"><h1>התרשים לא נמצא</h1>
    <p>אין תרשים בשם הזה, או שקובץ המקור שלו לא עבר בדיקה. <a class="btn" href="${P}/" title="רשימת התרשימים">לרשימה</a></p></header>`));
}).listen(PORT, () => { console.log(`archify: listening on :${PORT}, sources in ${DIAGRAMS}`); refresh(); });
