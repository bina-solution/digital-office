/* test_disclosure_words.mjs — every power the catalog can disclose has the screen's words for it.
 *
 *   node platform-base/app-management/test_disclosure_words.mjs
 *
 * The install disclosure is what an owner reads before he lets an app in: «מקבלת את שקע ה־Docker…».
 * Its sentences are computed by platform/manager/catalog.py — in English, with the signed index —
 * and the apps screen says them in Hebrew by the power's id (`powerHe` in static/app.js). The two
 * lists live in two files, so the day the catalog learns a seventh power the screen would show it
 * in English and nobody would be told. This reads both files and fails when an id the catalog can
 * emit has no sentence on the screen, or when the screen keeps one the catalog no longer emits.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const catalog = readFileSync(join(here, '..', '..', 'platform', 'manager', 'catalog.py'), 'utf8');
const screen = readFileSync(join(here, 'static', 'app.js'), 'utf8');

const emitted = [...catalog.matchAll(/powers\.append\(\{[^}]*?"id":\s*"([a-z0-9-]+)"/g)].map((m) => m[1]);
const body = (screen.match(/const powerHe = \(p\) => \{[\s\S]*?\n\};/) || [''])[0];
const said = [...body.matchAll(/^\s+"?([a-z0-9-]+)"?:\s*[`"]/gm)].map((m) => m[1]);

let passed = 0;
function ok(cond, what) {
  if (!cond) { console.error('FAIL  ' + what); process.exit(1); }
  passed += 1;
}
ok(emitted.length >= 6 && new Set(emitted).size === emitted.length, `the catalog's powers were read (${emitted.join(', ') || 'none — the pattern no longer matches catalog.py'})`);
ok(said.length >= 6, `the screen's sentences were read (${said.join(', ') || 'none — powerHe was not found in app.js'})`);
for (const id of emitted) ok(said.includes(id), `«${id}» — a power the catalog discloses — has the screen's words`);
for (const id of said) ok(emitted.includes(id), `«${id}» is still a power the catalog discloses (a sentence for nothing is dead copy)`);
ok(/\[p\.id\] \|\| esc\(said\)/.test(body), 'a power nobody translated is shown as the catalog wrote it, never dropped');
ok(/<span title="\$\{esc\(p\.text\)\}">\$\{powerHe\(p\)\}<\/span>/.test(screen), "the catalog's own sentence stays in the tooltip");

console.log(`disclosure words: ${passed} checks passed (${emitted.length} powers)`);
