// Bundles the REAL platform frontends (console shell + each app) into ONE self-contained HTML.
// Each app's real UI is untouched; only window.fetch/XHR is mocked (per-app files in mocks/).
// The console iframe (/a/<id>/) is repointed to the base64-embedded app via a runtime Blob patch.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');          // repo root
// SIM_OUT=<file> writes the build somewhere else, so a test's build does not rewrite the tracked
// file under another run that is reading it (flow-qa.py --url file://<file> then reads that one).
const OUT = path.resolve(process.env.SIM_OUT || path.join(__dirname, '..', 'platform-sim.html'));
const REVOGRID_BUNDLE = path.join(__dirname, 'vendor', 'revo-grid.bundle.js');   // built by bundle-revogrid.mjs

// app id here = the /a/<id>/ path segment the console navigates to (from modules.yaml).
// html = the app's real index page (relative to repo root); assets resolve next to it.
// ⚠ These paths were `production/…` and `development/…` until the platform-os refactor moved every
// app to `apps/` (layer 3) or `platform-base/` (layers 1–2). The skip-collector below would have
// caught it — it fails the build rather than shipping placeholders — so this was never going to ship
// a half-empty simulation. What it DID mean is that the simulation could no longer be rebuilt at
// all: six of the ten apps plus the console shell resolved to nothing, so any rebuild died on
// "html not found" and the committed platform-sim.html became the only copy that would ever exist.
// A specification you cannot regenerate is a specification that stops tracking the thing it
// specifies, and it is invisible for exactly as long as nobody runs the build.
const APPS = [
  { id: 'any-concurrency', html: 'apps/any-concurrency/static/index.html', mock: 'any-concurrency.js' },
  { id: 'my-docs',         html: 'apps/my-docs/static/index.html',                  mock: 'my-docs.js' },
  // The drive is the LIVE app's own frontend. It was a sim-owned fork (sim/apps/localdrive), made so
  // the simulation could take the screen past what the real app did then; the real app has since
  // taken all of it and gone further (a phone's row menu, the meter that reads what the service
  // sends, profiles), and the fork had become the older of the two - the layout suite was checking
  // code nobody is served. The mock answers what the live service answers (apps/drive/app.py).
  { id: 'localdrive',      html: 'apps/drive/static/index.html',                  mock: 'localdrive.js' },
  // The mail is the LIVE app's own frontend too. Its fork (sim/apps/mailview) was made to take the screen
  // past a read-only viewer - views that are queries, a conversation, compose and reply; the real app has
  // since taken all of it and gone further (the tag rules editor, the mailbox's settings, the guided
  // connect, the shared side menu), and the fork showed none of that. The mock answers what the live
  // service answers (apps/mail/mailview/app.py and the mail service behind it).
  { id: 'mailview',        html: 'apps/mail/mailview/static/index.html',          mock: 'mailview.js' },
  { id: 'alerts',          html: 'platform-base/notifications/static/index.html', mock: 'notifications.js' },
  { id: 'machine',         html: 'platform-base/machine/static/index.html',       mock: 'machine.js' },
  { id: 'connections',     html: 'platform-base/connections/ui.html',             mock: 'connections.js' },
  // The apps screen became an app (the shell's own grid was removed), and for a while its tile here
  // drew the "next version" placeholder — while verify-sim said "complete", because it counts what
  // this list names. The real frontend, over a mock whose catalogue is read from the manifests.
  { id: 'app-management',  html: 'platform-base/app-management/static/index.html', mock: 'app-management.js' },
  // feature-validation has no CONSOLE MODULE — no registry offers it, so the live platform has no
  // אימות מערכת screen. Its dashboard is not retired code, though: it is the status page of apitools'
  // own OCR/extraction suites, which moved out of the parked tree to apps/apitools/feature-validation/
  // and are run by `bbox test apitools`. It is kept in the simulation deliberately: dropping the panel
  // would renumber every panel after it, invalidating the committed ui-map and every comparison
  // written against those indices. Its panel is expected to have no live counterpart — see
  // PORT-STATUS.md, which records it as unrouted rather than as port work.
  { id: 'feature-validation', html: 'apps/apitools/feature-validation/api/dashboard.html', mock: 'feature-validation.js' },
  // INDOX is a sim-OWNED fork (sim/apps/indox) — see "INDOX fork" below. Auto-rebuilt by ensureIndox().
  // …and its mock is handed the LIVE app's display catalog (`catalog`, below): how INDOX's data reads has one owner.
  { id: 'incoming',        html: 'digital-office/sim/apps/indox/dist-sim/index.html', mock: 'incoming.js',
    catalog: 'apps/indox/blueprint/schema/display.json' },
  { id: 'wadmin',          html: 'digital-office/sim/wadmin.html',                mock: 'wadmin.js' },
];

// sim-only runtime overlay, injected (in this order) after each app's mock. See sim/overlay/.
// (no `drive.js`: it painted a glyph per file type over the fork's one generic glyph; the live drive draws its own.
//  no `mail.js`: it gave the fork a compose window and a reply row; the live mail has its own, and under it the
//  overlay put a SECOND «כתיבה» button on the screen)
const OVERLAY_FILES = ['tokens.js', 'icons.js', 'brand.js', 'switcher.js', 'responsive.js', 'theme.js'];

const read = p => fs.readFileSync(p, 'utf8');
const mockPath = m => path.join(__dirname, 'mocks', m);
const exists = p => { try { fs.accessSync(p); return true; } catch { return false; } };

// THE PALETTE — the office's one («Olive Grove», platform-base/bina-ui/theme-tokens.css), read where it
// is written and put LAST in the <head> of every page this build embeds. So the simulation carries no
// copy of it: the forks (sim/apps/*), wadmin.html and the overlays name its tokens and nothing else,
// and a real app's own stamped copy says the same thing a second time. (Until 2026-10-07 the forks and
// overlay/tokens.js each wrote the previous palette out, and the simulation kept it when the office's
// changed.)
const PALETTE = (t => t.slice(t.indexOf('/* @bina-theme-tokens:start */'), t.indexOf('/* @bina-theme-tokens:end */')))(
  read(path.join(ROOT, 'platform-base', 'bina-ui', 'theme-tokens.css')));
if (!/--olive:\s*#/.test(PALETTE)) { console.error('✗ the palette block was not found in platform-base/bina-ui/theme-tokens.css'); process.exit(1); }
// THE QUESTION AND THE NOTICE — the office's own (`binaAsk` / `binaTell`, platform-base/bina-ui/bina-ask.js),
// read where they are written, as the palette is, and given to every page this build embeds. So the forks
// (sim/apps/*) and the overlays say and ask through them and carry no toast of their own; a real screen's
// stamped copy defines the same two names a second time, which the block is written to allow.
const ASK = (t => t.slice(t.indexOf('/* @bina-ask:start */'), t.indexOf('/* @bina-ask:end */')))(
  read(path.join(ROOT, 'platform-base', 'bina-ui', 'bina-ask.js')));
if (!/binaTell\s*=\s*function/.test(ASK)) { console.error('✗ the notice block was not found in platform-base/bina-ui/bina-ask.js'); process.exit(1); }
const withPalette = html => {
  const tag = `<style data-sim="palette">\n${PALETTE}\n</style>\n`;
  // the page's REAL </head> — the first that is not text inside a script: a mock, and INDOX's bundle,
  // hold the text of whole pages, and a tag put into one of those strings breaks the script
  for (const m of html.matchAll(/<script\b[\s\S]*?<\/script>|<\/head>/gi))
    if (/^<\/head>$/i.test(m[0])) return html.slice(0, m.index) + tag + html.slice(m.index);
  return html + tag;                                  // a page that closes no head (connections/ui.html)
};

// ── INDOX fork ───────────────────────────────────────────────────────────────────────────────────
// INDOX is the one app that is a React/Vite SPA rather than a static page, so it must be compiled
// before it can be inlined. It used to be compiled out of `development/incoming-documents/` — i.e. the
// sim silently depended on (and could not evolve) real app source. It now lives as a FULL SIM-OWNED
// FORK at `sim/apps/indox/`, seeded byte-identical to the platform build, so the simulation can be
// taken further (instances, screen flow, …) without ever touching `development/*` or `production/*`.
// Its `dist-sim/index.html` is a build artifact (gitignored); rebuild it whenever the fork's src is
// newer, so an edited fork can never be silently bundled stale.
const INDOX_DIR = path.join(__dirname, 'apps', 'indox');
function newestMtime(dir) {
  let t = 0;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name === 'dist-sim') continue;
    const p = path.join(dir, e.name);
    t = Math.max(t, e.isDirectory() ? newestMtime(p) : fs.statSync(p).mtimeMs);
  }
  return t;
}
// ── the fork's node_modules is PLATFORM-SPECIFIC ────────────────────────────────────────────────
// Vite's two heavy dependencies, rollup and esbuild, ship their native binary in an OPTIONAL
// per-platform package (`@rollup/rollup-linux-x64-gnu`, `@esbuild/win32-x64`, …). npm picks the one
// matching the machine that ran `npm install` and — this is npm's long-standing optional-dependency
// bug (npm/cli#4828) — will NOT add the missing one later just because you are now on a different
// OS. A `node_modules` installed on Windows therefore dies on WSL with
//
//     Error: Cannot find module @rollup/rollup-linux-x64-gnu
//
// and vice versa. Nothing about that message says "your node_modules is from the other OS", and the
// whole sim build (the thing that produces platform-sim.html) is dead until someone knows to
// reinstall. This is the same family as the exec-bit bug: an assumption true on one platform and
// false on the other, failing silently at the seam. So detect it and repair it, rather than
// documenting a step nobody will read at the moment they need it.
//
// Detection asks the tree, not a hard-coded matrix: `@rollup/` must hold a directory beginning
// `rollup-<platform>-<arch>` and `@esbuild/` one beginning `<platform>-<arch>` — true for
// linux/win32/darwin and x64/arm64 alike, including the `-gnu`/`-musl`/`-msvc` variants.
// The repair is `npm ci`: it removes node_modules and installs from the committed lockfile, which
// (npm records every optional dep, whatever its `os`/`cpu`) contains this platform's binaries.
const NATIVE_DEPS = [
  { scope: '@rollup', prefix: `rollup-${process.platform}-${process.arch}` },
  { scope: '@esbuild', prefix: `${process.platform}-${process.arch}` },
];

// npm is npm.cmd on Windows, and since Node 18.20/20.12 execFile refuses to run a .cmd without a
// shell (CVE-2024-27980). Same reason `npx` below needs it: without this the build fails on Windows
// with a bare ENOENT — the mirror image of the bug this whole block exists to fix.
const run = (cmd, args, opts = {}) =>
  execFileSync(cmd, args, { shell: process.platform === 'win32', ...opts });

function missingNativeDeps() {
  const nm = path.join(INDOX_DIR, 'node_modules');
  const missing = [];
  for (const { scope, prefix } of NATIVE_DEPS) {
    const dir = path.join(nm, scope);
    if (!exists(dir)) continue;              // dependency not installed at all — not this bug
    const have = fs.readdirSync(dir);
    if (!have.some(n => n.startsWith(prefix))) missing.push(`${scope}/${prefix}* (have: ${have.join(', ') || 'none'})`);
  }
  return missing;
}

function installIndoxDeps(why) {
  const cmd = exists(path.join(INDOX_DIR, 'package-lock.json')) ? 'ci' : 'install';
  console.log(`· ${why}\n· running \`npm ${cmd}\` in sim/apps/indox (one-time, ~1-2 min) …`);
  try {
    run('npm', [cmd, '--no-audit', '--no-fund'], { cwd: INDOX_DIR, stdio: 'inherit' });
  } catch (e) {
    throw new Error(
      `INDOX fork dependencies could not be installed for ${process.platform}-${process.arch}.\n` +
      `  Run it yourself and re-run this build:\n` +
      `    cd ${INDOX_DIR} && npm ${cmd}\n` +
      `  (${why})`);
  }
}

function ensureIndox() {
  const out = path.join(INDOX_DIR, 'dist-sim', 'index.html');
  const newest = newestMtime(INDOX_DIR);        // read BEFORE the compile — see where the output is dated, below
  if (exists(out) && fs.statSync(out).mtimeMs >= newest) return;   // up to date
  if (!exists(path.join(INDOX_DIR, 'node_modules'))) {
    installIndoxDeps('INDOX fork has no node_modules');
  } else {
    const missing = missingNativeDeps();
    if (missing.length) {
      installIndoxDeps(
        `node_modules was installed on a different platform — no native build for ` +
        `${process.platform}-${process.arch}: ${missing.join('; ')}`);
    }
  }
  console.log('· compiling INDOX fork (sim/apps/indox) …');
  run('npx', ['vite', 'build', '--config', 'vite.config.sim.ts'],
    { cwd: INDOX_DIR, stdio: ['ignore', 'pipe', 'inherit'] });
  // THE OUTPUT IS DATED TO THE SOURCES IT WAS MADE FROM, not to the moment it was written. A source edited WHILE
  // the compile ran (half a minute; three writers share this checkout) is newer than what was compiled and older
  // than the output's own time: the next build called the output fresh, and the edit was left out of every
  // simulation built until some other source changed — silently, which is what the rule above exists to prevent.
  const made = new Date(Math.ceil(newest));
  fs.utimesSync(out, made, made);
}
ensureIndox();

// Opaque-origin (blob:null) iframes break app init two ways, so shim both before any app code runs:
//  1. localStorage/sessionStorage throw "Access is denied" → in-memory fallback.
//  2. `new URL('/relative')` (no base, no scheme) throws "Invalid URL" because the origin is null →
//     wrap URL to retry with a synthetic base (breaks React apps like INDOX otherwise).
const STORAGE_SHIM = `<script>(function(){
function mk(){var m={};return{getItem:function(k){return k in m?m[k]:null},setItem:function(k,v){m[k]=String(v)},removeItem:function(k){delete m[k]},clear:function(){m={}},key:function(i){return Object.keys(m)[i]||null},get length(){return Object.keys(m).length}}}
['localStorage','sessionStorage'].forEach(function(n){try{window[n].getItem('__t')}catch(e){try{Object.defineProperty(window,n,{value:mk(),configurable:true})}catch(_){}}});
try{var N=window.URL;var B='https://sim.local/';function P(u,b){try{return b!==undefined?new N(u,b):new N(u)}catch(e){try{return new N(u,B)}catch(_2){return new N(B+String(u).replace(/^\\/+/,''))}}}P.prototype=N.prototype;['createObjectURL','revokeObjectURL','canParse','parse'].forEach(function(k){if(N[k])P[k]=N[k].bind(N)});window.URL=P;}catch(_){}
// history.pushState/replaceState to a new PATH throws on an opaque (blob:null) origin; swallow it so
// path-routed apps (localdrive/mailview do nav()+openFolder()) don't abort before loading content.
try{var H=window.history;['pushState','replaceState'].forEach(function(k){var o=H[k];if(o)H[k]=function(){try{return o.apply(H,arguments)}catch(e){}};});}catch(_){}
// Route <img>/<iframe>/<embed> src that point at an app API through the MOCKED fetch, converting the
// response to a blob URL. Native resource loads (PDF preview, OCR/drawing/original images, QR) can't be
// intercepted by a fetch monkey-patch alone, and a Service Worker can't run from file://; this can.
// location.hash assignment and in-page anchor navigation can be flaky across embed contexts, which breaks
// hash-menu apps (wadmin). Fallback: after an in-page anchor click, if the hash didn't move, force it
// with replaceState + a hashchange event. Guarded so apps whose hash already changed are untouched.
try{document.addEventListener('click',function(e){var a=e.target&&e.target.closest&&e.target.closest('a[href^="#"]');if(!a||e.defaultPrevented||e.button)return;var href=a.getAttribute('href');if(!href||href.length<2)return;setTimeout(function(){if(location.hash!==href){try{history.replaceState(null,'',href)}catch(_){}try{window.dispatchEvent(new HashChangeEvent('hashchange'))}catch(_2){window.dispatchEvent(new Event('hashchange'))}}},0);},false);}catch(_){}
try{['HTMLImageElement','HTMLIFrameElement','HTMLEmbedElement'].forEach(function(TN){
  var pr=window[TN]&&window[TN].prototype;if(!pr)return;var d=Object.getOwnPropertyDescriptor(pr,'src');if(!d||!d.set)return;
  Object.defineProperty(pr,'src',{configurable:true,enumerable:d.enumerable,get:d.get,set:function(v){
    var s=String(v);
    if(/(^|\\/)(api|incomingDocuments)\\//.test(s)&&!/^(data:|blob:|about:)/.test(s)){
      var self=this;
      try{fetch(s).then(function(r){return r.blob();}).then(function(b){d.set.call(self,URL.createObjectURL(b));}).catch(function(){d.set.call(self,v);});return;}catch(e){}
    }
    d.set.call(this,v);
  }});
});}catch(_){}
})();</script>`;

// Shared mock harness — one implementation of the fetch save/replace/Response dance that all 11 mocks
// otherwise hand-roll. A mock can `window.__mock(routes, fallback)` instead of rewriting window.fetch:
//   routes   = [[RegExp|fn(u), handler(url,opts,match)], …]  — handler may return a plain object
//              (auto-JSON), a Response, or a Promise of either.
//   fallback = optional fn(url,opts); return a value to serve, or null/undefined to defer to realFetch.
// window.__json(obj|string, status?, type?) builds the Response. Injected before each mock so it's ready.
const MOCK_PRELUDE = `<script>(function(){
window.__json=function(o,status,type){return Promise.resolve(new Response(typeof o==='string'?o:JSON.stringify(o),{status:status||200,headers:{'Content-Type':type||'application/json'}}));};
window.__mock=function(routes,fallback){
  var real=window.fetch?window.fetch.bind(window):null;
  function norm(r){return (r&&typeof r.then==='function')?r:(r instanceof Response)?Promise.resolve(r):window.__json(r);}
  window.fetch=function(url,opts){
    var u=String(url),i,pat,r;
    for(i=0;i<routes.length;i++){pat=routes[i][0];
      var hit=typeof pat==='function'?pat(u):pat.test(u);
      if(hit){r=routes[i][1](u,opts,pat.exec?pat.exec(u):hit);return norm(r);}}
    if(fallback){r=fallback(u,opts);if(r!=null)return norm(r);}
    return real?real(url,opts):Promise.reject(new Error('mock: no route '+u));
  };
};
})();</script>`;

// A tile can be LOADED while its service is silent. In every suite the mock answers, so what a screen
// says when nothing does had never been asked of one as it comes up — only where it already stood
// (flow-qa.py, rule 14). Rule 15 names the way on the shell (`__simSilent`) and loads the tile's frame
// again: 'none' is no answer at all, 'refused' the 502 page a proxy answers while a service restarts.
// After the mock, so it is the mock that goes silent; nothing here runs unless the suite asked.
const SILENT = `\n<script data-sim="silent">(function(){
var how;try{how=parent!==window&&parent.__simSilent}catch(e){}
if(!how)return;
window.fetch=function(){return how==='refused'
  ?Promise.resolve(new Response('<html><body><h1>502 Bad Gateway</h1></body></html>',{status:502,headers:{'Content-Type':'text/html'}}))
  :Promise.reject(new TypeError('Failed to fetch'));};
XMLHttpRequest.prototype.send=function(){var x=this;setTimeout(function(){x.dispatchEvent(new ProgressEvent('error'));},0);};
})();</script>`;

// Inline every local <script src> and <link rel=stylesheet> in an app's index page, then inject
// the storage shim + mock (+ `last`, a page's own addition; `first`, what its mock is handed) as the
// first <head> scripts so they run before app code.
function selfContain(htmlRel, mockFile, framed = true, last = '', first = '') {
  const htmlPath = path.join(ROOT, htmlRel);
  const staticDir = path.dirname(htmlPath);
  let html = read(htmlPath);
  const usesGrid = /bina-table/i.test(html);   // capture BEFORE inlining strips the <script src>
  // resolve an asset href: try next to the html, then the app root (handles `static/…` refs from an
  // index that is itself served at `/` while assets live under `/static/`).
  const resolve = href => {
    const rel = href.replace(/^\//, '').split('?')[0];
    const cands = [path.join(staticDir, rel), path.join(staticDir, '..', rel), path.join(ROOT, rel)];
    return cands.find(exists) || cands[0];
  };

  // Inline JS bulletproofly: base64, run as a SCRIPT ELEMENT in the tag's own place. base64 has no
  // HTML-breaking chars, so no </script / <!-- / <script sequence inside a vendor lib can corrupt
  // the wrapping tag. A script element and not (0,eval): eval keeps a file's top-level `let` and
  // `const` to itself, and the files of a page share them — the shell's desktop.js reads app.js's
  // `let MODULES`, found none here, and every window of desktop mode was empty in the simulation.
  const inlineJs = js => `<script>(s=>{s.text=decodeURIComponent(escape(atob("${b64(js)}")));document.currentScript.replaceWith(s)})(document.createElement("script"))</script>`;
  const safeJs = js => js;                                     // kept for the mock-inject call below
  html = html.replace(/<script\s+[^>]*src=["']([^"']+)["'][^>]*>\s*<\/script>/gi, (m, src) => {
    if (/^https?:/i.test(src)) return m;                       // leave true externals
    try { return inlineJs(read(resolve(src))); } catch { return m; }
  });
  html = html.replace(/<link\s+[^>]*rel=["']stylesheet["'][^>]*href=["']([^"']+)["'][^>]*>/gi, (m, href) => {
    if (/^https?:/i.test(href)) return m;
    try { return `<style>\n${read(resolve(href))}\n</style>`; } catch { return m; }
  });
  // The tab's icon is a FILE the server answers. A page opened from disk asks the disk's root for it
  // on every load and gets nothing — 53 failed requests in one flow run. Carried inline like the rest.
  html = html.replace(/<link\s+[^>]*rel=["']icon["'][^>]*href=["']([^"']+)["'][^>]*>/gi, (m, href) => {
    if (/^(https?|data):/i.test(href)) return m;
    try { return m.replace(href, 'data:image/svg+xml;base64,' + b64(read(resolve(href)))); } catch { return m; }
  });

  // <base> FIRST: srcdoc's default base is the parent URL, so the app's own "#x" / relative links
  // would reload the whole console into the frame. about:srcdoc keeps them in-document.
  // FOR A FRAMED APP ONLY. The shell is the top page, and there the same tag sends its own
  // `location.replace("#/m/…")` — the rewrite of a renamed tile's address, the fall-back to the
  // first tile — to about:srcdoc: the whole simulation was replaced by the browser's error page.
  // business.js (the shared "running business" data spine) loads before the mock so a mock can read
  // window.__biz and project app-specific shapes from the one canonical entity set (see sim/business.js).
  // OVERLAY files LAST: the sim-only runtime overlay layer (design tokens, one icon pack, brand +
  // version). They run in the app iframe and edit nothing in real source — see sim/overlay/ and
  // sim/ALIGNMENT-CHANGELOG.md. Order: tokens → icons → brand.
  const overlay = OVERLAY_FILES.map(f => `<script>\n${read(path.join(__dirname, 'overlay', f))}\n</script>`).join('\n');
  // Apps that use the platform grid (vendor/bina-table.js) lazy-load RevoGrid via a runtime module
  // import that can't resolve offline — so pre-register the REAL grid from the pre-bundled dist
  // (sim/vendor/revo-grid.bundle.js, built by bundle-revogrid.mjs). Injected after the URL shim (its
  // patchBrowser reads import.meta.url) and before app code, so customElements.get('revo-grid') is
  // already defined when BinaTable.create() runs → identical grid, everywhere it's used.
  const revogrid = usesGrid && exists(REVOGRID_BUNDLE)
    ? `\n<script>(0,eval)(decodeURIComponent(escape(atob("${b64(read(REVOGRID_BUNDLE))}"))))</script>` : '';
  // <meta charset> MUST be the first thing in <head> (within the first ~1KB) or mobile browsers sniff a
  // locale encoding and render Hebrew as mojibake. selfContain prepends this whole block right after
  // <head>, so putting charset first here fixes both the console shell and every embedded app.
  const inject = `<meta charset="utf-8">\n` + (framed ? `<base href="about:srcdoc">\n` : '') + STORAGE_SHIM + revogrid + `\n` + MOCK_PRELUDE +
    `\n<script data-sim="ask">\n${ASK}\n</script>` +
    `\n<script>\n${read(path.join(__dirname, 'business.js'))}\n</script>` + first +
    `\n<script>\n${safeJs(read(mockPath(mockFile)))}\n</script>` + (framed ? SILENT : '') +
    `\n` + overlay + last;
  html = /<head[^>]*>/i.test(html) ? html.replace(/<head[^>]*>/i, m => m + '\n' + inject) : inject + html;
  return withPalette(html);
}

const b64 = s => Buffer.from(s, 'utf8').toString('base64');

// ---- build each embedded app (skip any whose mock isn't ready yet) ----
const registry = {};
/* An app that fails to embed does NOT stop the build — it silently becomes a "מודול זה ייטען
   בגרסה הבאה" placeholder in the output. That was a deliberate convenience while apps were being
   added one at a time, and it is a trap now: the build still exits 0, still prints a cheerful
   summary, and ships a file where a whole app is a grey apology. Anyone who pipes the build to
   /dev/null (which is most CI, and was most of this session) never sees it.
   So: skips are collected and the build FAILS on them unless partial output is explicitly asked
   for with BBOX_ALLOW_PARTIAL=1. */
const skipped = [];
for (const a of APPS) {
  if (!exists(mockPath(a.mock))) { skipped.push(`${a.id}: mock ${a.mock} not found`); continue; }
  if (!exists(path.join(ROOT, a.html))) { skipped.push(`${a.id}: html ${a.html} not found`); continue; }
  // An app's DISPLAY CATALOG — how its data reads: the heading of each column, the word and the colour of each
  // value — is the LIVE app's own file. It is handed whole to the mock that stands for that app's server, which
  // merges it into what it serves as the server does; the simulation keeps no words of its own for an app's data.
  const catalog = a.catalog ? (({ $comment, ...says }) =>               // (its own notes to its writers stay in the file)
    `\n<script data-sim="catalog">window.__catalog=${JSON.stringify(says).replace(/</g, '\\u003c')}</script>`)(
    JSON.parse(read(path.join(ROOT, a.catalog)))) : '';
  try { registry[a.id] = b64(selfContain(a.html, a.mock, true, '', catalog)); console.log(`✓ ${a.id}`); }
  catch (e) { skipped.push(`${a.id}: ${e.message}`); console.log(`✗ ${a.id}: ${e.message}`); }
}

// ---- build the console shell (real UI + console mock + iframe→srcdoc patch) ----
const patch = `
(function(){
  var REG = ${JSON.stringify(registry)};
  var PALETTE = ${JSON.stringify(PALETTE)};          // for the one page written here, which no build step touches
  function htmlFor(id){ return REG[id] ? decodeURIComponent(escape(atob(REG[id]))) :
    '<!doctype html><meta charset=utf8><style>' + PALETTE + '</style><body style="margin:0;font-family:system-ui;direction:rtl;display:flex;align-items:center;justify-content:center;height:100vh;color:var(--muted);background:var(--bg)"><div style="text-align:center"><div style="font-size:15px;font-weight:700">'+id+'</div><div style="font-size:13px;margin-top:6px">מודול זה ייטען בגרסה הבאה של הסימולטור</div></div>'; }
  // Embed via srcdoc (real parent origin → localStorage / location.hash / new URL all work). Each app
  // has an injected <base href="about:srcdoc"> so its own hash/relative links resolve IN-document
  // (default srcdoc base is the PARENT url, which would reload the whole console into the frame).
  // Patched on the PROTOTYPE, not on #frame alone: desktop mode (console/static/desktop.js) opens
  // every app in a window of its own, and each of those frames has to be served from REG too.
  function patchFrames(){
    var proto = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'src');
    Object.defineProperty(HTMLIFrameElement.prototype, 'src', {
      configurable: true,
      get: function(){ return proto.get.call(this); },
      set: function(v){
        var m = String(v).match(/\\/a\\/([^\\/]+)\\//);
        if (m) { this.removeAttribute('src'); this.srcdoc = htmlFor(m[1]); }
        // a console-own view in a window is the shell itself, bare (desktop.js urlFor) — and the
        // shell is THIS file, where "/" is the disk's root and its listing
        else { this.removeAttribute('srcdoc'); proto.set.call(this, String(v).replace(/^\\/(?=\\?bare=)/, function(){ return location.pathname; })); }
      }
    });
  }
  patchFrames();
})();
`;
// The patch runs BEFORE the shell's own scripts. After them it was too late for a page opened — or
// reloaded — on an app's address: the mocked registry answers at once, the shell draws that app's
// frame while it boots, and a frame drawn before the patch asked the disk for /a/<alias>/ and
// showed the browser's "file not found" where the app belongs.
const shell = selfContain('platform-base/console/static/index.html', 'console.js', false, `\n<script>${patch}</script>`);

// Prepend a UTF-8 BOM so even a browser that ignores the <meta charset> (mobile file:// / content://
// opens) detects UTF-8 unambiguously. Browsers strip the BOM; it never renders.
fs.writeFileSync(OUT, '﻿' + shell);
const kb = (fs.statSync(OUT).size / 1024).toFixed(0);
console.log(`\nplatform-sim.html -> ${OUT} (${kb} KB); embedded apps: ${Object.keys(registry).join(', ')}`);

/* Fail loudly. A placeholdered app looks like a finished feature that "will arrive next version",
   which is the most expensive kind of wrong thing to ship. */
if (skipped.length) {
  console.error(`\n✗ ${skipped.length} app(s) DID NOT EMBED and are grey placeholders in the output:`);
  for (const s of skipped) console.error(`    · ${s}`);
  if (process.env.BBOX_ALLOW_PARTIAL === '1') {
    console.error('  BBOX_ALLOW_PARTIAL=1 — emitting the partial file anyway.');
  } else {
    console.error('  Refusing to call this a build. Fix the paths, or set BBOX_ALLOW_PARTIAL=1 if');
    console.error('  a partial simulation is genuinely what you want.');
    process.exit(1);
  }
}
