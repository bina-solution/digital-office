// Bundles the REAL vendored RevoGrid dist (production/my-docs/static/vendor/revo-grid, v4.43.2 — the
// exact build the live platform ships) into ONE self-contained IIFE with NO runtime dynamic imports,
// so bina-table.js's grid renders identically inside the offline about:srcdoc sim iframe. The live app
// lazy-loads `import(`./${bundleId}.entry.js`)` at first render; that resource load can't resolve in the
// sim (no network, opaque origin), so every BinaTable hangs on "טוען נתונים…". We rewrite that ONE
// computed import into a static switch over the finite, known bundle-id set, then esbuild inlines every
// entry chunk. Output: sim/vendor/revo-grid.bundle.js — injected by build.mjs before bina-table.js so
// `customElements.get('revo-grid')` is already defined and BinaTable reuses the real grid everywhere
// (מסמכים / לקוחות / פריטים and any other app using bina-table). Sim-only; edits NO real source.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const SRC = path.join(ROOT, 'production/my-docs/static/vendor/revo-grid');
const ESBUILD = path.join(ROOT, 'development/incoming-documents/app/webapp/node_modules/.bin/esbuild');
const WORK = path.join(__dirname, '.revogrid-build');
const OUT_DIR = path.join(__dirname, 'vendor');
const OUT = path.join(OUT_DIR, 'revo-grid.bundle.js');

fs.rmSync(WORK, { recursive: true, force: true });
fs.mkdirSync(WORK, { recursive: true });
fs.mkdirSync(OUT_DIR, { recursive: true });

// copy the whole dist verbatim into the workdir
for (const f of fs.readdirSync(SRC)) {
  if (f.endsWith('.js')) fs.copyFileSync(path.join(SRC, f), path.join(WORK, f));
}

// the finite set of lazy bundle ids == the *.entry.js files present in the dist
const entries = fs.readdirSync(SRC).filter(f => f.endsWith('.entry.js')).map(f => f.replace(/\.entry\.js$/, ''));

// patch the Stencil lazy loader (index-Chp_81rd.js): replace the ONE computed dynamic import with a
// static switch so esbuild can see and inline every entry chunk. Everything else is left byte-identical.
const loaderName = 'index-Chp_81rd.js';
const loaderPath = path.join(WORK, loaderName);
let loader = fs.readFileSync(loaderPath, 'utf8');

const marker = '/*!__STENCIL_STATIC_IMPORT_SWITCH__*/';
if (!loader.includes(marker)) throw new Error('static-import marker not found — dist layout changed');

const staticSwitch =
  '/* sim: computed import → static switch (offline-safe) */\n' +
  '  const __simEntries = {\n' +
  entries.map(id => `    ${JSON.stringify(id)}: () => import(${JSON.stringify('./' + id + '.entry.js')})`).join(',\n') +
  '\n  };\n' +
  '  return (__simEntries[bundleId] ? __simEntries[bundleId]() : Promise.reject(new Error("unknown bundle " + bundleId))).then(';

// swap the `return import( … ).then(` head (up to and including the `.then(`) for our static switch head
const importStart = loader.indexOf('return import(', loader.indexOf(marker));
const thenIdx = loader.indexOf(').then(', importStart);
if (importStart < 0 || thenIdx < 0) throw new Error('dynamic import block not found');
loader = loader.slice(0, importStart) + staticSwitch + loader.slice(thenIdx + ').then('.length);
fs.writeFileSync(loaderPath, loader);

// entry wrapper: importing revo-grid.esm.js runs patchBrowser()+bootstrapLazy() and registers <revo-grid>
fs.writeFileSync(path.join(WORK, '__entry.mjs'), "import './revo-grid.esm.js';\n");

// bundle → single IIFE. iife + no splitting makes esbuild inline the (now-static) dynamic imports.
execFileSync(ESBUILD, [
  path.join(WORK, '__entry.mjs'),
  '--bundle', '--format=iife', '--platform=browser',
  '--target=es2019', '--minify', '--legal-comments=none',
  '--define:import.meta.url="\\"about:srcdoc\\""',
  '--outfile=' + OUT,
], { stdio: ['ignore', 'ignore', 'inherit'] });

fs.rmSync(WORK, { recursive: true, force: true });
const kb = Math.round(fs.statSync(OUT).size / 1024);
console.log(`revo-grid.bundle.js (${kb} KB) ← real dist v4.43.2, entries: ${entries.join(', ')}`);
