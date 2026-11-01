/**
 * build-client.mjs — assemble lib/client.js, the browser half of the Hebrew language pack.
 *
 * Output format: the harness's closure-factory client bundle (window.__ModuleLoader__.load with a
 * CommonJS-style factory), hand-written rather than tsdown-built because this plugin is pure data
 * plus a few lines of registration — no React, no CSS modules, nothing to compile.
 *
 * Input: dicts/he/<ns>.json, one dictionary per harness UI namespace; dicts/en/<ns>.json is the
 * pinned English source (dsh version in dicts/index.json). The build refuses a Hebrew dictionary
 * whose key set differs from its English source: a missing key would silently fall back to English
 * in the middle of a Hebrew screen, an extra one is a typo.
 *
 * Second input: phrases.json — the keys whose Hebrew value is drawn at RANDOM from a pool instead
 * of being one fixed sentence (the hero title, the turn-status verb). Every entry is validated
 * against the two dictionaries here and baked into the bundle; the browser half picks one value per
 * page load, before the dictionaries are registered with the host locale service.
 *
 *   node build-client.mjs            # writes lib/client.js
 *   node build-client.mjs --check    # exits non-zero on any key-set drift, writes nothing
 */
import { readFileSync, readdirSync, writeFileSync, mkdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const EN = join(HERE, 'dicts', 'en')
const HE = join(HERE, 'dicts', 'he')
const index = JSON.parse(readFileSync(join(HERE, 'dicts', 'index.json'), 'utf8'))
const check = process.argv.includes('--check')

const dicts = {}
const english = {}
const problems = []
let translated = 0
for (const [ns, meta] of Object.entries(index.namespaces)) {
  const en = JSON.parse(readFileSync(join(EN, meta.file), 'utf8'))
  let he
  try { he = JSON.parse(readFileSync(join(HE, meta.file), 'utf8')) } catch { problems.push(`${ns}: no Hebrew dictionary (dicts/he/${meta.file})`); continue }
  const missing = Object.keys(en).filter(k => !(k in he))
  const extra = Object.keys(he).filter(k => !(k in en))
  if (missing.length) problems.push(`${ns}: missing ${missing.length} key(s): ${missing.slice(0, 5).join(', ')}${missing.length > 5 ? '…' : ''}`)
  if (extra.length) problems.push(`${ns}: unknown key(s): ${extra.slice(0, 5).join(', ')}`)
  // Placeholders must survive translation: every {name} in the English text must appear in the Hebrew one.
  // Exception: a singular (`.one`) form may drop its count — Hebrew says "שיחה אחת", never "1 שיחה".
  for (const [k, v] of Object.entries(en)) {
    if (k.endsWith('.one')) continue
    const want = [...String(v).matchAll(/\{[a-zA-Z0-9_]+\}/g)].map(m => m[0])
    const got = new Set([...String(he[k] ?? '').matchAll(/\{[a-zA-Z0-9_]+\}/g)].map(m => m[0]))
    for (const p of want) if (!got.has(p)) problems.push(`${ns}.${k}: placeholder ${p} lost in translation`)
  }
  dicts[ns] = he
  english[ns] = en
  translated += Object.keys(he).length
}

// ── random pools (phrases.json) ────────────────────────────────────────────────────────────────
// One entry per dictionary key whose Hebrew value is picked at random on page load. Checked here so
// a renamed harness key or an empty pool fails the image build, not a Hebrew screen at runtime.
const phrases = JSON.parse(readFileSync(join(HERE, 'phrases.json'), 'utf8'))
const random = {}
for (const [path, values] of Object.entries(phrases)) {
  if (path.startsWith('$')) continue
  const cut = path.indexOf('/')
  const ns = cut === -1 ? '' : path.slice(0, cut)
  const key = cut === -1 ? '' : path.slice(cut + 1)
  if (!ns || !key) { problems.push(`phrases.json: "${path}" is not <namespace>/<key>`); continue }
  if (!(ns in english)) { problems.push(`phrases.json: unknown namespace "${ns}"`); continue }
  if (!(key in english[ns])) { problems.push(`phrases.json: ${ns} has no key "${key}"`); continue }
  if (!Array.isArray(values) || values.length < 2) { problems.push(`phrases.json: ${path} needs at least 2 values`); continue }
  if (values.some(v => typeof v !== 'string' || v.trim() === '')) { problems.push(`phrases.json: ${path} has an empty value`); continue }
  if (values.some(v => /\{[a-zA-Z0-9_]+\}/.test(v))) { problems.push(`phrases.json: ${path} carries a {placeholder} the host fills`); continue }
  // The English source says how the string is written; a "..." in it means the Hebrew one ends
  // with an ellipsis, and every picked verb is displayed that way ("עובד…", the harness's
  // "Deep diving..."). Baked in, so the pools stay plain words.
  random[path] = { ns, key, suffix: String(english[ns][key]).endsWith('...') ? '…' : '', values }
}
const pooled = Object.keys(random).length

if (problems.length) {
  console.error(`locale-he: ${problems.length} problem(s):`)
  for (const p of problems) console.error('  - ' + p)
  process.exit(1)
}
console.error(`locale-he: ${Object.keys(dicts).length} namespaces, ${translated} strings, ${pooled} random pool(s)`)
if (check) process.exit(0)

// ── right-to-left corrections ──────────────────────────────────────────────────────────────────
// The harness has no bidi layer of its own: `<html dir=rtl>` (set by syncDirection) mirrors every
// flex row and every `start`/`end` alignment for free, and this stylesheet covers what mirroring
// cannot. Scoped to html[dir="rtl"] so an English or Chinese session is untouched. Selectors use
// the readable CSS-module suffixes (`<hash>_title`) — stable across rebuilds of one harness version.
const RTL_CSS = `
/* Code, commands, paths, keys: always left-to-right and isolated, so slashes, brackets and dots
   stay where the author put them ("/root/one/" was rendering as "root/one/"). */
html[dir="rtl"] code, html[dir="rtl"] pre, html[dir="rtl"] kbd, html[dir="rtl"] samp, html[dir="rtl"] tt {
  direction: ltr; unicode-bidi: isolate; text-align: left;
}
html[dir="rtl"] pre code { unicode-bidi: normal; }
/* Links follow their own text: a URL runs left-to-right, a Hebrew label right-to-left. */
html[dir="rtl"] a[href] { unicode-bidi: plaintext; }
/* Every paragraph-level block resolves its own bidi ORDER from its first strong character (so an
   English sentence keeps its period at its end), but every block is ANCHORED to the page's start
   edge — the right — in both languages. Owner's rule (2026-09-17): text sits near start, Hebrew or
   English; an English answer hugging the left edge reads as a mirrored page. */
html[dir="rtl"] p, html[dir="rtl"] li, html[dir="rtl"] h1, html[dir="rtl"] h2, html[dir="rtl"] h3,
html[dir="rtl"] h4, html[dir="rtl"] h5, html[dir="rtl"] h6, html[dir="rtl"] blockquote,
html[dir="rtl"] dd, html[dir="rtl"] dt {
  unicode-bidi: plaintext; text-align: right;
}
html[dir="rtl"] td, html[dir="rtl"] th { unicode-bidi: plaintext; text-align: start; }
/* The person's own message: a column the harness pins to the END edge (right in English, which
   mirrors to the left here). The owner wants it at START — the same edge the person types from. */
html[dir="rtl"] [class*="_userRow"], html[dir="rtl"] [class*="_userStack"] { align-items: flex-start; }
/* Typing: the composer and every text field follow what is being typed. */
html[dir="rtl"] textarea, html[dir="rtl"] input:not([type="checkbox"]):not([type="radio"]):not([type="range"]),
html[dir="rtl"] [contenteditable="true"] { unicode-bidi: plaintext; }
/* The composer's control row: the harness pins its trailing cluster (model, context meter, stop,
   SEND) with a PHYSICAL 'margin-left: auto', which is right in English and wrong here. In RTL the
   free space already sits to the left of that cluster, so the auto margin only swallows it and the
   cluster stays where the tools ended — the send button floated in the middle of the row with a
   hole beside it. The logical equivalent (margin-inline-start: auto, which is the upstream fix)
   puts that space on the cluster's START side, so the send button hugs the END edge — the left —
   exactly as it hugs the right in English, balancing the "+" at the other end.
   Owner's request 2026-09-25; _trailing is this row's class only (uV2eYG_trailing). */
html[dir="rtl"] [class*="_trailing"] { margin-left: 0; margin-right: auto; }
/* Titles, crumbs and summaries that may carry English (a model-generated session title, a file
   name, a command): resolve per content and clip at the END of the text, not its start
   ("…eeting to AI coding assistant" was showing the tail). */
html[dir="rtl"] [class*="_title"], html[dir="rtl"] [class*="_crumb"], html[dir="rtl"] [class*="_summaryText"],
html[dir="rtl"] [class*="_projectText"], html[dir="rtl"] [class*="_label"], html[dir="rtl"] [class*="_fileName"],
html[dir="rtl"] [class*="_path"] { unicode-bidi: plaintext; }
/* Developer surfaces are code end to end: the trajectory table, terminals, diffs. */
html[dir="rtl"] [class*="_trajectory"], html[dir="rtl"] [class*="_timeline"], html[dir="rtl"] [class*="_terminal"],
html[dir="rtl"] [class*="_diff"], html[dir="rtl"] [class*="xterm"], html[dir="rtl"] [class*="_codeBlock"],
html[dir="rtl"] [class*="_monospace"] { direction: ltr; text-align: left; }
/* The trajectory ledger (event table + timeline plot) is a developer log: left-to-right as a whole;
   its toolbar keeps the page direction. */
html[dir="rtl"] [class*="_ledger"], html[dir="rtl"] [class*="_tablePane"], html[dir="rtl"] [class*="_plot"] {
  direction: ltr; text-align: left;
}
/* Prose inside a left-to-right developer surface follows that surface, not the page. */
html[dir="rtl"] :is([class*="_trajectory"], [class*="_timeline"], [class*="_terminal"], [class*="_diff"],
  [class*="_codeBlock"], [class*="_ledger"], [class*="_tablePane"], [class*="_plot"])
  :is(p, li, h1, h2, h3, h4, h5, h6, blockquote, dd, dt) { text-align: left; }
`

const body = `window.__ModuleLoader__.load({
\tid: "@bina/dsh-client-locale-he",
\tfactory: (require) => {
\t\tvar module = { exports: {} };
\t\tvar exports = module.exports;
\t\tObject.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
\t\t/** Hebrew language pack for dsh ${index.dsh} — generated by build-client.mjs, do not edit. */
\t\tconst DICTS = ${JSON.stringify(dicts)};
\t\t/** Keys whose value is drawn from a pool (phrases.json) instead of the dictionary above. */
\t\tconst RANDOM = ${JSON.stringify(random)};
\t\tconst RTL_CSS = ${JSON.stringify(RTL_CSS)};
\t\tconst inject = ["locale"];
\t\t/** One value out of a pool. */
\t\tfunction pick(values) {
\t\t\treturn values[Math.floor(Math.random() * values.length)];
\t\t}
\t\t/**
\t\t* Replace each pooled dictionary value with one random draw. Runs once, before the dictionaries
\t\t* reach the host locale service, so the whole page — hero title and turn-status verb — shows the
\t\t* same pick until the next load.
\t\t*/
\t\tfunction randomize() {
\t\t\tfor (const spec of Object.values(RANDOM)) DICTS[spec.ns][spec.key] = pick(spec.values) + spec.suffix;
\t\t}
\t\tfunction installRtlStyles() {
\t\t\tif (typeof document === "undefined" || document.getElementById("bina-rtl-css")) return;
\t\t\tconst tag = document.createElement("style");
\t\t\ttag.id = "bina-rtl-css";
\t\t\ttag.textContent = RTL_CSS;
\t\t\tdocument.head.appendChild(tag);
\t\t}
\t\tfunction syncDirection(ctx) {
\t\t\tif (typeof document === "undefined") return;
\t\t\tconst rtl = ctx.locale.getSnapshot().active === "he";
\t\t\tdocument.documentElement.dir = rtl ? "rtl" : "ltr";
\t\t\tdocument.documentElement.classList.toggle("bina-rtl", rtl);
\t\t}
\t\tfunction apply(ctx) {
\t\t\tinstallRtlStyles();
\t\t\trandomize();
\t\t\tctx.effect(() => ctx.locale.addLanguage({ id: "he", label: "עברית", fallback: "en" }), "locale-he: language");
\t\t\tfor (const ns of Object.keys(DICTS)) ctx.effect(() => ctx.locale.register(ns, "he", DICTS[ns]), "locale-he: " + ns);
\t\t\tctx.effect(() => ctx.locale.subscribe(() => syncDirection(ctx)), "locale-he: document direction");
\t\t\tsyncDirection(ctx);
\t\t}
\t\texports.apply = apply;
\t\texports.inject = inject;
\t\treturn module.exports;
\t}
});
`
mkdirSync(join(HERE, 'lib'), { recursive: true })
writeFileSync(join(HERE, 'lib', 'client.js'), body)
console.error(`locale-he: wrote lib/client.js (${body.length} bytes)`)
